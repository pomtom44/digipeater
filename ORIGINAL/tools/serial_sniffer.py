"""Transparent serial bridge + hex logger.

Sits between the real ERW-4 cable (PL-2303 COM port) and one end of a
com0com virtual port pair, relaying bytes in both directions while logging
everything with a timestamp and direction so the Alinco DR_X38.exe protocol
can be reverse-engineered (see hardware/radio_programmer.py).

Wiring for a capture session:

    DR_X38.exe  --(virtual port A, e.g. COM10)-->  com0com pair  --(virtual port B, e.g. COM11)-->  this script  --(real port, e.g. COM3)-->  ERW-4 cable --> radio

Usage:
    python tools/serial_sniffer.py --real COM3 --virtual COM11 --log capture.log

Point DR_X38.exe at the *other* virtual port (COM10 in the example above).
"""

import argparse
import threading
import time

import serial


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def pump(src: serial.Serial, dst: serial.Serial, label: str, log_lines: list, lock: threading.Lock) -> None:
    while True:
        data = src.read(src.in_waiting or 1)
        if not data:
            continue
        dst.write(data)
        line = f"{time.time():.3f}  {label:12s}  {hexdump(data)}"
        with lock:
            log_lines.append(line)
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", required=True, help="Real COM port wired to the ERW-4 cable / radio, e.g. COM3")
    parser.add_argument("--virtual", required=True, help="Virtual com0com port bridged to the real port, e.g. COM11")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--log", default="capture.log", help="Path to write the full capture log")
    args = parser.parse_args()

    real = serial.Serial(args.real, args.baud, timeout=0.1)
    virt = serial.Serial(args.virtual, args.baud, timeout=0.1)

    log_lines: list = []
    lock = threading.Lock()

    t1 = threading.Thread(target=pump, args=(real, virt, "RADIO->PC", log_lines, lock), daemon=True)
    t2 = threading.Thread(target=pump, args=(virt, real, "PC->RADIO", log_lines, lock), daemon=True)
    t1.start()
    t2.start()

    print(f"Bridging {args.real} <-> {args.virtual} at {args.baud} baud. Ctrl+C to stop and save log.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        with open(args.log, "w") as f:
            f.write("\n".join(log_lines) + "\n")
        print(f"\nSaved {len(log_lines)} lines to {args.log}")


if __name__ == "__main__":
    main()
