#!/usr/bin/env python3
"""Standalone write test for the Alinco DR-138 clone-mode protocol: reads the full memory image, patches one channel's frequency and name, writes it all back, then reads that channel back to verify — protocol per ORIGINAL/hardware/radio_programmer.py, confirmed 2026-07-06 via a serial-sniffer capture of the real Alinco DR_X38.exe software against a DR-138T, not yet confirmed against a DR-138 MK2."""

import argparse
import sys

import serial

SCRIPT_VERSION = "1"

BAUD = 9600
TIMEOUT_S = 3
IDENT_RETRIES = 5
BLOCK_SIZE = 0x10
FIRST_ADDR = 0x0010
MEM_SIZE = 0x4000

CHANNEL0_OFFSET = 0x2000
CHANNEL_SIZE = 0x20
NAME_OFFSET = 0x13
NAME_LEN = 7

HANDSHAKE = b"PROGRAM"
HANDSHAKE_READY = bytes([0x51, 0x58, 0x06])
ID_QUERY = bytes([0x02])
READ_CMD = 0x52
WRITE_CMD = 0x57
ACK = 0x06


def checksum8(data: bytes) -> int:
    return sum(data) & 0xFF


def echo_write(port: serial.Serial, data: bytes) -> None:
    """This radio echoes back whatever it's sent before its real reply; write and discard that echo."""
    port.write(data)
    port.read(len(data))


def ident(port: serial.Serial) -> str:
    for attempt in range(IDENT_RETRIES):
        port.reset_input_buffer()
        echo_write(port, HANDSHAKE)
        resp = port.read(3)
        if resp == HANDSHAKE_READY:
            break
        print(f"  handshake attempt {attempt + 1}/{IDENT_RETRIES} got {resp!r}, retrying...")
    else:
        raise RuntimeError(f"No {HANDSHAKE_READY!r} response after {IDENT_RETRIES} attempts, check port/cable/power.")

    echo_write(port, ID_QUERY)
    id_reply = port.read(10)
    port.read(7)  # version reply, e.g. b"V100..." - not currently checked
    if len(id_reply) != 10:
        raise RuntimeError(f"Short ID reply: got {len(id_reply)} of 10 bytes ({id_reply!r}).")
    model = id_reply[1:8].decode("ascii", errors="replace").rstrip("\x00")
    if "138" not in model:
        print(f"WARNING: radio ID {model!r} doesn't contain '138' - double check this is the right radio before continuing.")
    return model


def read_block(port: serial.Serial, addr: int) -> bytes:
    cmd = bytes([READ_CMD, addr >> 8, addr & 0xFF, BLOCK_SIZE])
    echo_write(port, cmd)
    header = port.read(4)
    data = port.read(BLOCK_SIZE)
    checksum = port.read(1)
    ack = port.read(1)
    if len(header) != 4 or header[0] != WRITE_CMD or header[1:3] != cmd[1:3] or header[3] != BLOCK_SIZE:
        raise RuntimeError(f"Malformed read header @ {addr:#06x}: {header!r}")
    if len(data) != BLOCK_SIZE or len(checksum) != 1:
        raise RuntimeError(f"Short read @ {addr:#06x}: {len(data)} data bytes, {len(checksum)} checksum bytes.")
    expected = checksum8(header[1:] + data)
    if checksum[0] != expected:
        raise RuntimeError(f"Checksum mismatch @ {addr:#06x}: expected {expected:#04x}, got {checksum[0]:#04x}.")
    if ack != bytes([ACK]):
        raise RuntimeError(f"Missing ACK @ {addr:#06x}: got {ack!r}.")
    return data


def write_block(port: serial.Serial, addr: int, data: bytes) -> None:
    header = bytes([addr >> 8, addr & 0xFF, BLOCK_SIZE])
    frame = bytes([WRITE_CMD]) + header + data + bytes([checksum8(header + data)])
    echo_write(port, frame)
    ack = port.read(1)
    if ack != bytes([ACK]):
        raise RuntimeError(f"Write not ACKed @ {addr:#06x}: got {ack!r}.")


def end_session(port: serial.Serial) -> None:
    echo_write(port, b"END")
    port.read(2)  # two 0x06 acks, per the confirmed capture


def bcd(n: int) -> int:
    tens, ones = divmod(n, 10)
    return (tens << 4) | ones


def unbcd(b: int) -> int:
    return (b >> 4) * 10 + (b & 0x0F)


def encode_frequency(freq_hz: int) -> bytes:
    units = round(freq_hz / 100)
    s = f"{units:07d}"
    return bytes([int(s[0]), bcd(int(s[1:3])), bcd(int(s[3:5])), bcd(int(s[5:7]))])


def decode_frequency(data: bytes) -> int:
    units = int(f"{data[0]}{unbcd(data[1]):02d}{unbcd(data[2]):02d}{unbcd(data[3]):02d}")
    return units * 100


def encode_name(name: str) -> bytes:
    return name[:NAME_LEN].upper().ljust(NAME_LEN).encode("ascii", errors="replace")


def decode_name(data: bytes) -> str:
    return data[:NAME_LEN].decode("ascii", errors="replace").rstrip()


def main():
    print(f"test_alinco_write.py version {SCRIPT_VERSION}")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB0 or COM5")
    parser.add_argument("--channel", type=int, default=0, help="0-indexed channel to patch (0 = display channel 1)")
    parser.add_argument("--freq-mhz", type=float, default=146.520, help="Test frequency to write, MHz")
    parser.add_argument("--name", default="TEST", help="Test channel name to write, up to 7 chars")
    args = parser.parse_args()

    offset = CHANNEL0_OFFSET + args.channel * CHANNEL_SIZE
    if offset + CHANNEL_SIZE > MEM_SIZE:
        raise ValueError(f"channel {args.channel} is out of range for this radio")
    freq_hz = round(args.freq_mhz * 1_000_000)

    with serial.Serial(args.port, BAUD, timeout=TIMEOUT_S) as port:
        print(f"Connecting to {args.port} at {BAUD} baud...")
        model = ident(port)
        print(f"Radio identified: {model!r}")

        print("Reading full memory image...")
        memory = bytearray(MEM_SIZE)
        total_blocks = (MEM_SIZE - FIRST_ADDR) // BLOCK_SIZE
        for i, addr in enumerate(range(FIRST_ADDR, MEM_SIZE, BLOCK_SIZE)):
            memory[addr:addr + BLOCK_SIZE] = read_block(port, addr)
            if i % 100 == 0 or i == total_blocks - 1:
                print(f"  read {i + 1}/{total_blocks} blocks (0x{addr:04x})")

        old_freq = decode_frequency(memory[offset:offset + 4])
        old_name = decode_name(memory[offset + NAME_OFFSET:offset + NAME_OFFSET + NAME_LEN])
        print(f"Channel {args.channel} currently: {old_freq / 1_000_000:.4f} MHz {old_name!r}")

        memory[offset:offset + 4] = encode_frequency(freq_hz)
        memory[offset + NAME_OFFSET:offset + NAME_OFFSET + NAME_LEN] = encode_name(args.name)

        print(f"Writing full memory image back, patching channel {args.channel} to "
              f"{args.freq_mhz:.4f} MHz {args.name!r}, watch the radio for a CLONE display now...")
        try:
            for i, addr in enumerate(range(FIRST_ADDR, MEM_SIZE, BLOCK_SIZE)):
                write_block(port, addr, bytes(memory[addr:addr + BLOCK_SIZE]))
                if i % 100 == 0 or i == total_blocks - 1:
                    print(f"  wrote {i + 1}/{total_blocks} blocks (0x{addr:04x})")

            record = bytearray(CHANNEL_SIZE)
            record[0:BLOCK_SIZE] = read_block(port, offset)
            record[BLOCK_SIZE:CHANNEL_SIZE] = read_block(port, offset + BLOCK_SIZE)
        finally:
            end_session(port)

        readback_freq = decode_frequency(record[0:4])
        readback_name = decode_name(record[NAME_OFFSET:NAME_OFFSET + NAME_LEN])
        print(f"Read back {readback_freq / 1_000_000:.4f} MHz {readback_name!r}")

        if readback_freq == freq_hz and readback_name == args.name[:NAME_LEN].upper().rstrip():
            print("PASS: write confirmed, radio accepted and stored the new channel data.")
        else:
            print("FAIL: readback does not match what was written.")
            sys.exit(1)

    print("Done. Power-cycle the radio and check the channel display now.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, serial.SerialException) as e:
        print(f"Failed: {e}")
        sys.exit(1)
