#!/usr/bin/env python3
"""Read-only smoke test for the TYT TH-9000D clone-mode protocol: handshake, then dump the full 16KB memory image to a file for comparison against a CHIRP-exported dump. No writes, safe to run against a real radio. Protocol independently reimplemented from CHIRP's th9000.py (GPLv2+) as a reference for the byte-level facts, not a port of its code."""

import argparse
import struct
import sys
import time

import serial

# Some programming cables power their internal chip parasitically off DTR/RTS; CHIRP
# asserts both by default (WANTS_DTR/WANTS_RTS in chirp_common.py), so we match that.
DTR_RTS_SETTLE_S = 0.3

BAUD = 9600
TIMEOUT_S = 1
IDENT_RETRIES = 5
MMAP_SIZE = 0x4000
BLOCK_SIZE = 0x10


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB0 or COM5")
    parser.add_argument("--out", default="radio_dump.bin", help="Where to save the raw memory dump")
    args = parser.parse_args()

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

        dump = bytearray()
        total_blocks = MMAP_SIZE // BLOCK_SIZE
        start = time.monotonic()
        for i, addr in enumerate(range(0, MMAP_SIZE, BLOCK_SIZE)):
            dump += read_block(port, addr)
            if i % 100 == 0 or i == total_blocks - 1:
                print(f"  read {i + 1}/{total_blocks} blocks ({addr:04x}/{MMAP_SIZE:04x})")

        echo_write(port, b"END")
        port.read(1)  # ACK if the radio sends one; empty is also fine here

    elapsed = time.monotonic() - start
    with open(args.out, "wb") as f:
        f.write(dump)
    print(f"Done in {elapsed:.1f}s. Wrote {len(dump)} bytes to {args.out}.")
    print("Compare this against a CHIRP-exported .img of the same radio to verify the read path.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, serial.SerialException) as e:
        print(f"Failed: {e}")
        sys.exit(1)
