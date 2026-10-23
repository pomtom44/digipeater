#!/usr/bin/env python3
"""Standalone TX volume/deviation test. Powers the radio relay, keys PTT, and plays a sequence of
AFSK-like tone bursts at stepped volumes so relative levels can be compared on an SDR, without
installing or running the rest of the digipeater stack.

Assumes: radio already manually set to the test frequency/power (e.g. 144.500 simplex, low power)
and wired exactly as in PINOUT.md (relay GPIO27/pin13, PTT GPIO22/pin15, audio into the radio's
mic/data input). This script does NOT control frequency or power level -- no live CAT/VFO control
exists in this project, only offline clone-mode memory programming (see services/radio_programmer.py).

Only dependency beyond the standard library is the `aplay` command (part of alsa-utils, already
present on any Pi that's run Direwolf) and RPi.GPIO (apt package python3-rpi.gpio).

Usage:
    python3 tx_volume_test.py
    python3 tx_volume_test.py --steps 0.1,0.3,0.6,1.0 --tone-duration 2 --repeat 2
    python3 tx_volume_test.py --no-relay              # radio already powered externally
"""

import argparse
import math
import re
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("RPi.GPIO not importable (apt install python3-rpi.gpio). Aborting -- nothing was touched.")
    sys.exit(1)

RELAY_PIN_DEFAULT = 27  # PINOUT.md: physical pin 13
PTT_PIN_DEFAULT = 22    # PINOUT.md: physical pin 15
BOOT_DELAY_S_DEFAULT = 10
TXDELAY_S = 0.3   # carrier-up time before audio starts, matches Direwolf's default TXDELAY
TXTAIL_S = 0.2    # audio-to-unkey gap, matches Direwolf's default TXTAIL
SAMPLE_RATE = 48000
MARK_HZ = 1200.0   # Bell 202 mark/space tones, same pair Direwolf's AFSK modem uses
SPACE_HZ = 2200.0
TONE_SWITCH_S = 0.02  # how often to alternate mark/space within a burst, for a packet-like warble
CONFIG_YAML_PATH = Path("/opt/digipeater/config.yaml")


def detect_audio_device() -> tuple[str | None, str | None]:
    """Picks the same ALSA device the real digipeater install would use, instead of falling back to
    aplay's bare default device -- which on a Pi is the onboard bcm2835/HDMI output, not the USB sound
    card the radio is actually wired to. Returns (device, source) or (None, None) if nothing found."""
    if CONFIG_YAML_PATH.exists():
        for line in CONFIG_YAML_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("audio_device:"):
                value = stripped.split(":", 1)[1].strip().strip("\"'")
                if value and value != "default":
                    return value, str(CONFIG_YAML_PATH)

    cards_path = Path("/proc/asound/cards")
    if cards_path.exists():
        pattern = re.compile(r"^\s*(\d+)\s+\[")
        for line in cards_path.read_text().splitlines():
            m = pattern.match(line)
            if m and "bcm2835" not in line.lower() and "hdmi" not in line.lower():
                return f"plughw:{m.group(1)},0", "/proc/asound/cards (first non-onboard card)"
    return None, None


def build_tone_wav(path: Path, duration_s: float, amplitude: float) -> None:
    """Writes a mono 16-bit WAV alternating MARK_HZ/SPACE_HZ at the given amplitude fraction (0-1]."""
    n_samples = int(SAMPLE_RATE * duration_s)
    switch_samples = int(SAMPLE_RATE * TONE_SWITCH_S)
    peak = int(32767 * max(0.0, min(1.0, amplitude)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        frames = bytearray()
        phase = 0.0
        for i in range(n_samples):
            freq = MARK_HZ if (i // switch_samples) % 2 == 0 else SPACE_HZ
            phase += 2 * math.pi * freq / SAMPLE_RATE
            sample = int(peak * math.sin(phase))
            frames += struct.pack("<h", sample)
        wf.writeframes(bytes(frames))


def parse_steps(raw: str) -> list[float]:
    steps = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = float(part)
        if not (0.0 < value <= 1.0):
            raise argparse.ArgumentTypeError(f"volume step {value!r} must be in (0, 1]")
        steps.append(value)
    if not steps:
        raise argparse.ArgumentTypeError("no volume steps given")
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--relay-pin", type=int, default=RELAY_PIN_DEFAULT)
    parser.add_argument("--ptt-pin", type=int, default=PTT_PIN_DEFAULT)
    parser.add_argument("--no-relay", action="store_true", help="skip powering the relay; radio already on")
    parser.add_argument("--leave-powered", action="store_true", help="don't power off the relay when done")
    parser.add_argument("--boot-delay", type=float, default=BOOT_DELAY_S_DEFAULT, help="seconds to wait after relay on")
    parser.add_argument("--tone-duration", type=float, default=3.0, help="seconds per volume step")
    parser.add_argument("--gap", type=float, default=2.0, help="seconds of silence between steps")
    parser.add_argument("--repeat", type=int, default=1, help="how many times to loop through all steps")
    parser.add_argument("--steps", type=parse_steps, default=parse_steps("0.1,0.25,0.5,0.75,1.0"),
                         help="comma-separated volume fractions, e.g. 0.1,0.5,1.0")
    parser.add_argument("--device", default=None, help="aplay -D device, e.g. plughw:2,0 (auto-detected if omitted)")
    args = parser.parse_args()

    print("=" * 60)
    print("TX volume test")
    print("=" * 60)
    print(f"Relay pin: {args.relay_pin} (GPIO/BCM)   PTT pin: {args.ptt_pin} (GPIO/BCM)")
    print(f"Steps: {args.steps}   duration: {args.tone_duration}s each   repeat: {args.repeat}")

    if args.device:
        print(f"Audio device: {args.device} (--device flag)")
    else:
        detected, source = detect_audio_device()
        if detected:
            print(f"Audio device: {detected} (auto-detected from {source})")
            args.device = detected
        else:
            print("WARNING: no non-onboard sound card found -- falling back to ALSA's default device, "
                  "which is almost certainly wrong (onboard bcm2835/HDMI, not the radio's USB card). "
                  "Pass --device plughw:N,0 explicitly.")
    print()
    print("Before continuing, confirm:")
    print("  - radio manually set to the test frequency, LOW power")
    print("  - audio output wired into the radio's mic/data input")
    print("  - antenna connected")
    print()
    confirm = input("Continue? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted, nothing was touched.")
        return 1

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(args.ptt_pin, GPIO.OUT, initial=GPIO.LOW)
    if not args.no_relay:
        GPIO.setup(args.relay_pin, GPIO.OUT, initial=GPIO.LOW)

    tmp_dir = Path(tempfile.mkdtemp(prefix="tx_volume_test_"))
    try:
        if not args.no_relay:
            print(f"Powering radio on (GPIO {args.relay_pin} HIGH), waiting {args.boot_delay}s to boot...")
            GPIO.output(args.relay_pin, GPIO.HIGH)
            time.sleep(args.boot_delay)

        for rep in range(1, args.repeat + 1):
            for i, amplitude in enumerate(args.steps, start=1):
                print(f"[rep {rep}/{args.repeat}] Step {i}/{len(args.steps)}: {amplitude:.0%} volume -- watch SDR now")
                wav_path = tmp_dir / f"tone_{i}.wav"
                build_tone_wav(wav_path, args.tone_duration, amplitude)

                GPIO.output(args.ptt_pin, GPIO.HIGH)
                time.sleep(TXDELAY_S)
                cmd = ["aplay", "-q"]
                if args.device:
                    cmd += ["-D", args.device]
                cmd.append(str(wav_path))
                subprocess.run(cmd, check=False)
                time.sleep(TXTAIL_S)
                GPIO.output(args.ptt_pin, GPIO.LOW)

                time.sleep(args.gap)

        print("Done.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted, unkeying PTT and stopping.")
        return 130
    finally:
        GPIO.output(args.ptt_pin, GPIO.LOW)
        if not args.no_relay and not args.leave_powered:
            print(f"Powering radio off (GPIO {args.relay_pin} LOW).")
            GPIO.output(args.relay_pin, GPIO.LOW)
        for f in tmp_dir.glob("*.wav"):
            f.unlink(missing_ok=True)
        tmp_dir.rmdir()
        # Relay/PTT pins left driven at their last level, not cleanup()'d -- see reset.sh's comment
        # on why cleanup() (floating the pin) can re-energize a relay board with a pulled-up trigger.


if __name__ == "__main__":
    sys.exit(main())
