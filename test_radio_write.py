#!/usr/bin/env python3
"""Single-pass write test: one full programming run, as a real deploy would do it. Erases every channel except channel 1 (data and set/skip flags), writes a random frequency+power to channel 1, verifies the read-back, then exits; re-run the script for another value. Same clone-mode protocol as test_radio_program.py, reimplemented fresh from CHIRP's th9000.py (GPLv2+) as a reference, not a port."""

import argparse
import random
import struct
import sys
import time

import serial

DTR_RTS_SETTLE_S = 0.3
BAUD = 9600
TIMEOUT_S = 1
IDENT_RETRIES = 5
BLOCK_SIZE = 0x10
CHANNEL_BASE = 0x2000
CHANNEL_SIZE = 0x20
TOTAL_CHANNELS = 200
TEST_CHANNEL = 1  # 1-indexed, first channel in the radio's programming list
BLANK_BLOCK = b"\xFF" * BLOCK_SIZE

# Separate 1-bit-per-channel flag arrays: whether a channel is programmed at all is tracked
# here, independent of its own data bytes, so a channel with valid data but the wrong flag
# still won't show on the radio. bit=1 means empty/skip, bit=0 means set/don't-skip, and
# channel index 0 (channel 1) is the MSB of the first byte (CHIRP's `7 - (n % 8)` convention).
CSETFLAG_BASE = 0x0100
CSKIPFLAG_BASE = 0x0120
FLAG_BYTES = 32  # covers up to 256 channels, 1 bit each

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
    """8-digit packed BCD in units of 10Hz, most-significant digit pair first (CHIRP's bbcd array convention)."""
    digits = f"{freq_hz // 10:08d}"
    return bytes((int(digits[i]) << 4) | int(digits[i + 1]) for i in range(0, 8, 2))


def bbcd_to_freq_hz(data: bytes) -> int:
    val = 0
    for b in data:
        val = val * 100 + (((b >> 4) & 0xF) * 10 + (b & 0xF))
    return val * 10


def random_test_value() -> tuple[float, int]:
    steps = round((FREQ_MAX_MHZ - FREQ_MIN_MHZ) / FREQ_STEP_MHZ)
    freq_mhz = round(FREQ_MIN_MHZ + random.randint(0, steps) * FREQ_STEP_MHZ, 3)
    power = random.choice([0, 1, 2])
    return freq_mhz, power


def build_channel_block(freq_mhz: float, power: int) -> bytearray:
    """A fresh, fully-zeroed block with only freq+power set, matching CHIRP's zero-then-set approach."""
    block = bytearray(BLOCK_SIZE)
    block[0:4] = freq_to_bbcd(round(freq_mhz * 1_000_000))
    block[10] = power << 2
    return block


def erase_other_channels(port: serial.Serial) -> None:
    """Blanks every channel except TEST_CHANNEL, so the test channel is always the only programmed one."""
    print(f"Erasing channels 1-{TOTAL_CHANNELS} except channel {TEST_CHANNEL}...")
    for ch in range(1, TOTAL_CHANNELS + 1):
        if ch == TEST_CHANNEL:
            continue
        addr = CHANNEL_BASE + (ch - 1) * CHANNEL_SIZE
        write_block(port, addr, BLANK_BLOCK)
        write_block(port, addr + BLOCK_SIZE, BLANK_BLOCK)
        if ch % 20 == 0 or ch == TOTAL_CHANNELS:
            print(f"  erased {ch}/{TOTAL_CHANNELS}")
    print("Done erasing.\n")


def build_flag_bytes(set_channel_index: int) -> bytes:
    """All channels flagged empty/skip except set_channel_index (0-based), flagged set/don't-skip."""
    data = bytearray([0xFF] * FLAG_BYTES)
    cbyte, cbit = set_channel_index // 8, 7 - (set_channel_index % 8)
    data[cbyte] &= ~(1 << cbit)
    return bytes(data)


def write_flags(port: serial.Serial, base_addr: int, flag_bytes: bytes) -> None:
    for i in range(0, len(flag_bytes), BLOCK_SIZE):
        write_block(port, base_addr + i, flag_bytes[i:i + BLOCK_SIZE])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB0 or COM5")
    parser.add_argument("--skip-erase", action="store_true", help="Skip re-erasing the other channels this run")
    args = parser.parse_args()

    channel_addr = CHANNEL_BASE + (TEST_CHANNEL - 1) * CHANNEL_SIZE
    with serial.Serial(args.port, BAUD, timeout=TIMEOUT_S) as port:
        print(f"Connecting to {args.port} at {BAUD} baud...")
        port.dtr = True
        port.rts = True
        time.sleep(DTR_RTS_SETTLE_S)
        port.reset_input_buffer()
        radio_id = ident(port)
        print(f"Radio identified: {radio_id!r}")
        print(f"Using channel {TEST_CHANNEL} (0x{channel_addr:04x}) as the test channel.\n")

        try:
            if not args.skip_erase:
                erase_other_channels(port)
                print(f"Setting the set/skip flags so only channel {TEST_CHANNEL} shows as programmed...")
                flag_bytes = build_flag_bytes(TEST_CHANNEL - 1)
                write_flags(port, CSETFLAG_BASE, flag_bytes)
                write_flags(port, CSKIPFLAG_BASE, flag_bytes)
                print("Done.\n")

            freq_mhz, power = random_test_value()
            block = build_channel_block(freq_mhz, power)
            write_block(port, channel_addr, bytes(block))

            readback = read_block(port, channel_addr)
            readback_freq = bbcd_to_freq_hz(readback[0:4]) / 1_000_000
            readback_power = (readback[10] >> 2) & 0b11
        finally:
            # Always exit clone mode before the script ends: this radio appears to time out of clone
            # mode on its own after a few seconds of inactivity, leaving it stuck on a frozen "CLONE"
            # screen until power-cycled if it's left in that state rather than exited cleanly.
            try:
                echo_write(port, b"END")
                port.read(1)
            except serial.SerialException:
                pass

        print(f"Wrote {freq_mhz:.3f} MHz, power={POWER_NAMES[power]} to channel {TEST_CHANNEL}")
        print(f"Read back {readback_freq:.5f} MHz, power={POWER_NAMES.get(readback_power, readback_power)}")
        print(f"Check channel {TEST_CHANNEL} on the radio now. Re-run this script for a new value.")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, serial.SerialException) as e:
        print(f"Failed: {e}")
        sys.exit(1)
