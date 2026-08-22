#!/usr/bin/env python3
"""Single-pass write test: one full programming run, as a real deploy would do it. Starts from the known-working chirp_reference_image.bin, patches in a random frequency+power for channel 1, blanks every other channel (data and set/skip flags), and sets the radio to boot into Memory mode, then writes the whole thing out in one continuous ascending address sweep (0x0100 to 0x3ff0, no gaps) since this radio's clone mode appears to require that, not the out-of-order patch writes an earlier version of this script used. Verifies the read-back, then exits; re-run the script for another value. Same clone-mode protocol as test_radio_program.py, reimplemented fresh from CHIRP's th9000.py (GPLv2+) as a reference, not a port."""

import argparse
import random
import struct
import sys
import time
from pathlib import Path

import serial

SCRIPT_VERSION = "4"

DTR_RTS_SETTLE_S = 0.3
BAUD = 9600
TIMEOUT_S = 1
IDENT_RETRIES = 5
BLOCK_SIZE = 0x10

IMAGE_PATH = Path(__file__).parent / "chirp_reference_image.bin"
IMAGE_BASE = 0x0100

CHANNEL_BASE = 0x2000
CHANNEL_SIZE = 0x20
TOTAL_CHANNELS = 200
TEST_CHANNEL = 1  # 1-indexed, first channel in the radio's programming list

# Separate 1-bit-per-channel flag arrays: whether a channel is programmed at all is tracked
# here, independent of its own data bytes, so a channel with valid data but the wrong flag
# still won't show on the radio. bit=1 means empty/skip, bit=0 means set/don't-skip, and
# channel index 0 (channel 1) is the MSB of the first byte (CHIRP's `7 - (n % 8)` convention).
CSETFLAG_BASE = 0x0100
CSKIPFLAG_BASE = 0x0120
FLAG_BYTES = 32  # covers up to 256 channels, 1 bit each

# vfo_mr at 0x0221: 0=boots into VFO mode after a clone/power-cycle, 1=boots into Memory mode.
# Without this the radio can't be remotely operated after programming, someone has to walk over
# and press V/M by hand. Not exposed in CHIRP's own settings UI, but it's a real memory byte.
VFO_MR_ADDR = 0x0221
MEMORY_MODE = 1

FREQ_MIN_MHZ = 144.000
FREQ_MAX_MHZ = 148.000
FREQ_STEP_MHZ = 0.005
POWER_NAMES = {0: "Hi", 1: "Mid", 2: "Lo"}


def checksum8(data: bytes) -> int:
    return sum(data) & 0xFF


def echo_write(port: serial.Serial, data: bytes) -> None:
    """This radio always echoes back whatever it's sent, before its real reply; write and discard that echo."""
    port.write(data)
    port.read(len(data))


def ident(port: serial.Serial) -> bytes:
    for attempt in range(IDENT_RETRIES):
        port.reset_input_buffer()
        echo_write(port, b"PROGRAM")
        resp = port.read(3)
        if resp == b"QX\x06":
            break
        print(f"  handshake attempt {attempt + 1}/{IDENT_RETRIES} got {resp!r}, retrying...")
    else:
        raise RuntimeError(f"No QX\\x06 response after {IDENT_RETRIES} attempts, check port/cable/power.")

    echo_write(port, b"\x02")
    radio_id = port.read(16)
    if b"TH-9000" not in radio_id:
        raise RuntimeError(f"Unexpected radio ID {radio_id!r}, expected it to contain b'TH-9000'.")
    return radio_id


def read_block(port: serial.Serial, addr: int) -> bytes:
    echo_write(port, struct.pack(">cHb", b"R", addr, BLOCK_SIZE))
    resp = port.read(BLOCK_SIZE + 6)
    if len(resp) != BLOCK_SIZE + 6:
        raise RuntimeError(f"Short read at 0x{addr:04x}: got {len(resp)} bytes, expected {BLOCK_SIZE + 6}.")
    body, checksum, ack = resp[1:-2], resp[-2], resp[-1]
    if checksum8(body) != checksum:
        raise RuntimeError(f"Checksum mismatch at 0x{addr:04x}: computed {checksum8(body):02x}, got {checksum:02x}.")
    if ack != 0x06:
        raise RuntimeError(f"Missing ACK at 0x{addr:04x}: got {ack:02x}.")
    return resp[4:-2]


def write_block(port: serial.Serial, addr: int, data: bytes) -> None:
    if len(data) != BLOCK_SIZE:
        raise ValueError(f"write_block needs exactly {BLOCK_SIZE} bytes, got {len(data)}")
    header = struct.pack(">cHb", b"W", addr, BLOCK_SIZE)
    frame = header + data
    frame += bytes([checksum8(frame[1:])]) + b"\x06"
    echo_write(port, frame)
    ack = port.read(1)
    if ack != b"\x06":
        raise RuntimeError(f"Write not ACKed at 0x{addr:04x}: got {ack!r}.")


def freq_to_bbcd(freq_hz: int) -> bytes:
    """8-digit packed BCD in units of 100Hz, most-significant digit pair first, confirmed against two real CHIRP writes (130.000000 MHz and 140.000000 MHz) since an earlier x10-Hz assumption was off by exactly 10x."""
    digits = f"{freq_hz // 100:08d}"
    return bytes((int(digits[i]) << 4) | int(digits[i + 1]) for i in range(0, 8, 2))


def bbcd_to_freq_hz(data: bytes) -> int:
    val = 0
    for b in data:
        val = val * 100 + (((b >> 4) & 0xF) * 10 + (b & 0xF))
    return val * 100


def random_test_value() -> tuple[float, int]:
    steps = round((FREQ_MAX_MHZ - FREQ_MIN_MHZ) / FREQ_STEP_MHZ)
    freq_mhz = round(FREQ_MIN_MHZ + random.randint(0, steps) * FREQ_STEP_MHZ, 3)
    power = random.choice([0, 1, 2])
    return freq_mhz, power


def build_flag_bytes(set_channel_index: int) -> bytes:
    """All channels flagged empty/skip except set_channel_index (0-based); bit N = channel N, confirmed against real hardware (CHIRP's own `7 - (n % 8)` formula tested backwards)."""
    data = bytearray([0xFF] * FLAG_BYTES)
    cbyte, cbit = set_channel_index // 8, set_channel_index % 8
    data[cbyte] &= ~(1 << cbit)
    return bytes(data)


def build_image(freq_mhz: float, power: int) -> bytearray:
    """Patches the known-working reference image in memory: only channel 1 stays programmed."""
    image = bytearray(IMAGE_PATH.read_bytes())

    flag_bytes = build_flag_bytes(TEST_CHANNEL - 1)
    image[CSETFLAG_BASE - IMAGE_BASE:CSETFLAG_BASE - IMAGE_BASE + FLAG_BYTES] = flag_bytes
    image[CSKIPFLAG_BASE - IMAGE_BASE:CSKIPFLAG_BASE - IMAGE_BASE + FLAG_BYTES] = flag_bytes

    image[VFO_MR_ADDR - IMAGE_BASE] = MEMORY_MODE

    for ch in range(1, TOTAL_CHANNELS + 1):
        if ch == TEST_CHANNEL:
            continue
        off = CHANNEL_BASE + (ch - 1) * CHANNEL_SIZE - IMAGE_BASE
        image[off:off + CHANNEL_SIZE] = b"\xFF" * CHANNEL_SIZE

    ch1_off = CHANNEL_BASE + (TEST_CHANNEL - 1) * CHANNEL_SIZE - IMAGE_BASE
    image[ch1_off:ch1_off + 4] = freq_to_bbcd(round(freq_mhz * 1_000_000))
    image[ch1_off + 10] = power << 2

    return image


def write_image(port: serial.Serial, image: bytes) -> None:
    total_blocks = len(image) // BLOCK_SIZE
    for i in range(total_blocks):
        addr = IMAGE_BASE + i * BLOCK_SIZE
        write_block(port, addr, image[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE])
        if i % 100 == 0 or i == total_blocks - 1:
            print(f"  wrote {i + 1}/{total_blocks} blocks (0x{addr:04x})")


def main():
    print(f"test_radio_write.py version {SCRIPT_VERSION}")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB0 or COM5")
    args = parser.parse_args()

    channel_addr = CHANNEL_BASE + (TEST_CHANNEL - 1) * CHANNEL_SIZE
    freq_mhz, power = random_test_value()
    image = build_image(freq_mhz, power)

    with serial.Serial(args.port, BAUD, timeout=TIMEOUT_S) as port:
        print(f"Connecting to {args.port} at {BAUD} baud...")
        # Forced low first so the True below is a real transition, not a no-op if the port already opened
        # high: this radio's clone mode may be triggered by the DTR/RTS edge, not just the held level.
        port.dtr = False
        port.rts = False
        time.sleep(DTR_RTS_SETTLE_S)
        port.dtr = True
        port.rts = True
        time.sleep(DTR_RTS_SETTLE_S)
        port.reset_input_buffer()
        radio_id = ident(port)
        print(f"Radio identified: {radio_id!r}")
        print(f"Writing {len(image)} bytes in one ascending sweep (0x{IMAGE_BASE:04x} to "
              f"0x{IMAGE_BASE + len(image) - BLOCK_SIZE:04x}), watch for the CLONE display now...")

        try:
            write_image(port, image)
            readback = read_block(port, channel_addr)
            readback_freq = bbcd_to_freq_hz(readback[0:4]) / 1_000_000
            readback_power = (readback[10] >> 2) & 0b11
            vfo_mr_readback = read_block(port, VFO_MR_ADDR - (VFO_MR_ADDR % BLOCK_SIZE))[VFO_MR_ADDR % BLOCK_SIZE]
        finally:
            try:
                echo_write(port, b"END")
                port.read(1)
            except serial.SerialException:
                pass

        print(f"Wrote {freq_mhz:.3f} MHz, power={POWER_NAMES[power]} to channel {TEST_CHANNEL}")
        print(f"Read back {readback_freq:.5f} MHz, power={POWER_NAMES.get(readback_power, readback_power)}")
        print(f"vfo_mr read back as {vfo_mr_readback} (1=Memory mode, this is what's actually stored, "
              f"whether or not the radio boots into it)")
        print(f"Check channel {TEST_CHANNEL} on the radio now. Re-run this script for a new value.")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, serial.SerialException) as e:
        print(f"Failed: {e}")
        sys.exit(1)
