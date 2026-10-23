#!/usr/bin/env python3
"""Run SECOND: reuses the gain settings + reference level sdr_tune.py saved (but not its frequency --
the digipeater's test channel is different from the handheld reference frequency), listens while the
digipeater's TESTING/tx_volume_test.py runs on the Pi, and reports each detected burst's deviation
as a ratio against the handheld reference. Runs on the PC with the HackRF attached, not the Pi.

Start this first (it prints "Listening..."), then start tx_volume_test.py on the Pi with its
defaults (5 steps, 3s tone each, 2s gap) -- this listens for 45s by default, enough margin for that
whole sequence.

Usage:
    python sdr_listen.py
    python sdr_listen.py --freq 145225000
"""

import argparse
import sys

import sdr_common as sdr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--freq", type=float, default=145_225_000, help="target frequency in Hz")
    parser.add_argument("--duration", type=float, default=45.0, help="total capture window, seconds")
    args = parser.parse_args()

    try:
        config = sdr.load_config()
    except FileNotFoundError as e:
        print(e)
        return 1

    print("=" * 60)
    print("SDR listen: capturing digipeater transmissions")
    print("=" * 60)
    print(f"Freq: {args.freq/1e6:.4f} MHz   LNA: {config['lna_gain']}   VGA: {config['vga_gain']}")
    print(f"Reference (handheld, captured at {config['freq_hz']/1e6:.4f} MHz): "
          f"RMS {config['reference_deviation_rms_hz']:.0f} Hz, peak {config['reference_deviation_peak_hz']:.0f} Hz")
    print()
    print(f"Listening for {args.duration:.0f}s -- start tx_volume_test.py on the Pi now...")

    try:
        baseband, baseband_rate, raw_i8 = sdr.capture_iq(
            freq_hz=args.freq, duration_s=args.duration, sample_rate=config["sample_rate"],
            lna_gain=config["lna_gain"], vga_gain=config["vga_gain"], amp_enable=config["amp_enable"],
            offset_hz=config["offset_hz"], hackrf_bin=config["hackrf_bin"],
        )
    except Exception as e:
        print(f"Capture failed: {e}")
        return 1

    bursts = sdr.analyze_capture(baseband, baseband_rate, raw_i8, config["sample_rate"], args.freq)
    if not bursts:
        print("No transmissions detected. Check the digipeater actually keyed up on this frequency, then re-run.")
        return 1

    reference_rms = config["reference_deviation_rms_hz"]
    print(f"\nDetected {len(bursts)} burst(s):")
    for i, b in enumerate(bursts, start=1):
        ratio = b["deviation_rms_hz"] / reference_rms if reference_rms else float("nan")
        flag = "  ** CLIPPED, ratio unreliable **" if b["clipped"] else ""
        off_flag = "  ** check digipeater's channel/freq **" if abs(b["freq_offset_hz"]) > 2500 else ""
        print(f"  {i}. {b['start_s']:.2f}-{b['end_s']:.2f}s  "
              f"measured freq: {b['measured_freq_hz']/1e6:.4f} MHz (offset {b['freq_offset_hz']:+.0f} Hz){off_flag}  "
              f"RMS dev: {b['deviation_rms_hz']:.0f} Hz  peak: {b['deviation_peak_hz']:.0f} Hz  "
              f"({ratio:.0%} of handheld reference){flag}")

    if any(b["clipped"] for b in bursts):
        print("\nAt least one burst clipped at this gain -- the digipeater is transmitting hotter than "
              "the handheld was when sdr_tune.py locked this gain. Re-run sdr_tune.py with lower gain "
              "and redo both tests before trusting these ratios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
