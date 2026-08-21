#!/usr/bin/env python3
"""Diagnostic only: replays a byte-perfect capture of a real CHIRP upload (chirp_reference_image.bin, extracted from debug.log) verbatim, unmodified, to see whether the radio behaves the same as it did for CHIRP itself. Same clone-mode protocol as test_radio_program.py, reimplemented fresh from CHIRP's th9000.py (GPLv2+) as a reference, not a port."""

import struct
import sys
import time

import serial

DTR_RTS_SETTLE_S = 0.3
BAUD = 9600
TIMEOUT_S = 1
IDENT_RETRIES = 5
BLOCK_SIZE = 0x10
IMAGE_PATH = "chirp_reference_image.bin"
IMAGE_BASE = 0x0100


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


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--port":
        print("Usage: test_radio_replay.py --port /dev/ttyUSB0")
        sys.exit(1)
    port_name = sys.argv[2]

    with open(IMAGE_PATH, "rb") as f:
        image = f.read()
    total_blocks = len(image) // BLOCK_SIZE
    print(f"Loaded {len(image)} bytes from {IMAGE_PATH} ({total_blocks} blocks, unmodified from the capture).")

    with serial.Serial(port_name, BAUD, timeout=TIMEOUT_S) as port:
        print(f"Connecting to {port_name} at {BAUD} baud...")
        port.dtr = True
        port.rts = True
        time.sleep(DTR_RTS_SETTLE_S)
        port.reset_input_buffer()
        radio_id = ident(port)
        print(f"Radio identified: {radio_id!r}")

        print("Replaying the captured image verbatim, watch the radio for a clone-mode display now...")
        try:
            for i in range(total_blocks):
                addr = IMAGE_BASE + i * BLOCK_SIZE
                write_block(port, addr, image[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE])
                if i % 100 == 0 or i == total_blocks - 1:
                    print(f"  wrote {i + 1}/{total_blocks} blocks (0x{addr:04x})")
        finally:
            echo_write(port, b"END")
            port.read(1)

    print("Done. Check the radio now.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, serial.SerialException) as e:
        print(f"Failed: {e}")
        sys.exit(1)
