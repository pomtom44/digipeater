#!/usr/bin/env python3
"""Confirms what audio level is actually leaving the Pi, before blaming the radio.

tx_volume_test.py's 5 volume steps showed almost no difference at the SDR (136-156 Hz RMS
deviation across a 10x digital amplitude range) -- this checks two things separately so we know
whether that's a WAV-generation bug, an ALSA mixer clamping the level, or genuinely downstream
(cable/radio), without needing the SDR at all:

  1. Dumps the ALSA mixer levels for every playback card/control, so a muted or fixed-low control
     overriding our per-file amplitude is visible directly.
  2. Rebuilds the same 5 tone files tx_volume_test.py plays and reads back their actual peak/RMS
     sample values from the WAV data itself, confirming the files really do differ 10x before
     they ever reach aplay/ALSA.
  3. Optionally plays each step through aplay (same as tx_volume_test.py would, minus PTT/relay),
     printing the active mixer level alongside each one, for a multimeter/scope on the Pi's audio
     output to confirm against.

Does NOT touch GPIO (no PTT, no relay) -- pure audio-path check, safe to run with the radio off.

Usage:
    python3 check_audio_output.py              # mixer dump + WAV sanity-check only
    python3 check_audio_output.py --play       # also plays each step through aplay
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

# Duplicated from tx_volume_test.py rather than imported, so this script has no RPi.GPIO dependency
# (tx_volume_test.py hard-exits at import time if RPi.GPIO is missing, which this check doesn't need).
SAMPLE_RATE = 48000
MARK_HZ = 1200.0
SPACE_HZ = 2200.0
TONE_SWITCH_S = 0.02
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


STEPS = [0.1, 0.25, 0.5, 0.75, 1.0]


def build_tone_wav(path: Path, duration_s: float, amplitude: float) -> None:
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


def read_wav_levels(path: Path) -> tuple[int, float]:
    """Returns (peak_abs_sample, rms_sample) read back from the WAV's own data, int16 scale."""
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    samples = struct.unpack(f"<{len(raw)//2}h", raw)
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return peak, rms


def dump_alsa_mixers() -> None:
    print("=" * 60)
    print("ALSA playback cards and mixer levels")
    print("=" * 60)
    try:
        cards = subprocess.run(["aplay", "-l"], capture_output=True, text=True, check=False)
        print(cards.stdout.strip() or cards.stderr.strip())
    except FileNotFoundError:
        print("aplay not found -- is alsa-utils installed?")
        return

    card_indices = []
    for line in cards.stdout.splitlines():
        if line.startswith("card "):
            try:
                card_indices.append(int(line.split(":")[0].split()[1]))
            except (IndexError, ValueError):
                pass

    for card in sorted(set(card_indices)):
        print(f"\n-- card {card} mixer controls --")
        scontrols = subprocess.run(["amixer", "-c", str(card), "scontrols"], capture_output=True, text=True)
        print(scontrols.stdout.strip())
        for line in scontrols.stdout.splitlines():
            if "'" not in line:
                continue
            name = line.split("'")[1]
            sget = subprocess.run(["amixer", "-c", str(card), "sget", name], capture_output=True, text=True)
            print(f"\n  [{name}]")
            for out_line in sget.stdout.splitlines():
                if "Limits" in out_line or "Mono" in out_line or "Left" in out_line or "Right" in out_line or "Playback" in out_line:
                    print(f"    {out_line.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--play", action="store_true", help="also play each step through aplay")
    parser.add_argument("--device", default=None, help="aplay -D device, e.g. plughw:2,0 (auto-detected if omitted)")
    parser.add_argument("--tone-duration", type=float, default=3.0)
    parser.add_argument("--gap", type=float, default=1.5, help="seconds of silence between --play steps")
    args = parser.parse_args()

    dump_alsa_mixers()

    if args.device:
        print(f"\nUsing audio device: {args.device} (--device flag)")
    else:
        detected, source = detect_audio_device()
        if detected:
            print(f"\nUsing audio device: {detected} (auto-detected from {source})")
            args.device = detected
        else:
            print("\nNo non-onboard sound card found and no --device given -- falling back to ALSA's "
                  "default device, which is almost certainly the WRONG one (onboard bcm2835/HDMI, not "
                  "the USB card the radio/speaker is wired to). Pass --device plughw:N,0 explicitly.")

    print()
    print("=" * 60)
    print("WAV file sanity check (read back from disk, before aplay)")
    print("=" * 60)
    tmp_dir = Path(tempfile.mkdtemp(prefix="check_audio_output_"))
    try:
        results = []
        for amplitude in STEPS:
            wav_path = tmp_dir / f"tone_{amplitude:.2f}.wav"
            build_tone_wav(wav_path, args.tone_duration, amplitude)
            peak, rms = read_wav_levels(wav_path)
            results.append((amplitude, peak, rms))
            print(f"  amplitude {amplitude:.0%} -> file peak {peak}/32767  file RMS {rms:.0f}")

        first_peak = results[0][1]
        last_peak = results[-1][1]
        ratio = last_peak / first_peak if first_peak else float("nan")
        print(f"\nFile peak ratio, last step / first step: {ratio:.1f}x "
              f"(expected ~{STEPS[-1]/STEPS[0]:.1f}x)")
        if ratio < (STEPS[-1] / STEPS[0]) * 0.8:
            print("WAV generation itself is NOT producing the expected amplitude spread -- bug is upstream"
                  " of ALSA, in build_tone_wav/tx_volume_test.py.")
        else:
            print("WAV files are correct -- if the SDR still shows flat levels across steps, the problem"
                  " is in ALSA mixer settings, the sound card, the cable, or the radio -- not this script.")

        if args.play:
            print()
            print("=" * 60)
            print("Playing each step -- listen on the speaker / watch the Pi's audio output now")
            print("=" * 60)
            for i, amplitude in enumerate(STEPS, start=1):
                wav_path = tmp_dir / f"tone_{amplitude:.2f}.wav"
                print(f"\nStep {i}/{len(STEPS)}: {amplitude:.0%} volume ({args.tone_duration:.0f}s)...")
                cmd = ["aplay", "-q"]
                if args.device:
                    cmd += ["-D", args.device]
                cmd.append(str(wav_path))
                subprocess.run(cmd, check=False)
                if i < len(STEPS):
                    time.sleep(args.gap)
            print("\nDid the loudness audibly step up from 10% to 100%, or sound about the same throughout?")
        return 0
    finally:
        for f in tmp_dir.glob("*.wav"):
            f.unlink(missing_ok=True)
        tmp_dir.rmdir()


if __name__ == "__main__":
    sys.exit(main())
