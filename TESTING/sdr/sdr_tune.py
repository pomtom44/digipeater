#!/usr/bin/env python3
"""Run FIRST: captures reference transmissions from the known-good handheld, picks a HackRF gain
that doesn't clip, and saves it + the reference deviation level to sdr_config.json for sdr_listen.py
to reuse. Runs on the PC with the HackRF attached, not the Pi.

Waits --lead-time seconds (default 20s) after launch before capturing, so there's time to walk
outside with the handheld. Then do THREE transmissions, ~4 seconds each, ~4 seconds apart, starting
as soon as it prints "Listening...". Total capture window is 30s, with margin either side.

Usage:
    python sdr_tune.py --freq 144575000
"""

import argparse
import sys
import time

import sdr_common as sdr


def main() -> int:
    # Pick up gain (and amp) from whatever the last run left behind -- a clipped run's suggested
    # lower gain, or a previously locked run's gain -- so repeated runs converge without needing to
    # retype --lna-gain/--vga-gain each time. Only used as defaults; explicit flags still override.
    prior = sdr.load_partial_config() or {}

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--freq", type=float, default=prior.get("freq_hz", 144_575_000), help="target frequency in Hz")
    parser.add_argument("--lead-time", type=float, default=20.0, help="seconds to wait before capture starts")
    parser.add_argument("--duration", type=float, default=30.0, help="total capture window, seconds")
    parser.add_argument("--lna-gain", type=int, default=prior.get("lna_gain", 16), help="starting LNA gain, 0-40 step 8")
    parser.add_argument("--vga-gain", type=int, default=prior.get("vga_gain", 20), help="starting VGA gain, 0-62 step 2")
    parser.add_argument("--amp", action="store_true", default=prior.get("amp_enable", False),
                         help="enable the HackRF's front-end amp")
    parser.add_argument("--hackrf-bin", default=prior.get("hackrf_bin", sdr.HACKRF_BIN_DEFAULT))
    args = parser.parse_args()

    if prior:
        state = "locked" if prior.get("locked") else "unlocked (clipped last time)"
        print(f"Picked up gain from previous run ({state}): LNA={args.lna_gain} VGA={args.vga_gain}")

    print("=" * 60)
    print("SDR tune: capturing handheld reference transmissions")
    print("=" * 60)
    print(f"Freq: {args.freq/1e6:.4f} MHz   LNA: {args.lna_gain}   VGA: {args.vga_gain}   Amp: {args.amp}")
    print()
    print(f"Starting in {args.lead_time:.0f}s -- get outside with the handheld now.")
    time.sleep(args.lead_time)
    print()
    print("Do THREE transmissions, ~4s each, ~4s apart, starting now.")
    print(f"Listening for {args.duration:.0f}s...")

    try:
        baseband, baseband_rate, raw_i8 = sdr.capture_iq(
            freq_hz=args.freq, duration_s=args.duration, sample_rate=sdr.SAMPLE_RATE_DEFAULT,
            lna_gain=args.lna_gain, vga_gain=args.vga_gain, amp_enable=args.amp,
            hackrf_bin=args.hackrf_bin,
        )
    except Exception as e:
        print(f"Capture failed: {e}")
        return 1

    bursts = sdr.analyze_capture(baseband, baseband_rate, raw_i8, sdr.SAMPLE_RATE_DEFAULT, args.freq)
    if not bursts:
        print("No transmissions detected. Check the handheld actually keyed up on this frequency, then re-run.")
        return 1

    print(f"\nDetected {len(bursts)} burst(s):")
    for i, b in enumerate(bursts, start=1):
        flag = "  ** CLIPPED **" if b["clipped"] else ""
        off_flag = "  ** check handheld's channel/freq **" if abs(b["freq_offset_hz"]) > 2500 else ""
        print(f"  {i}. {b['start_s']:.2f}-{b['end_s']:.2f}s  "
              f"measured freq: {b['measured_freq_hz']/1e6:.4f} MHz (offset {b['freq_offset_hz']:+.0f} Hz){off_flag}  "
              f"RMS dev: {b['deviation_rms_hz']:.0f} Hz  peak: {b['deviation_peak_hz']:.0f} Hz{flag}")

    clipped = [b for b in bursts if b["clipped"]]
    if clipped:
        new_lna = max(0, args.lna_gain - 8)
        new_vga = max(0, args.vga_gain - 10)
        print(f"\n{len(clipped)} burst(s) clipped at LNA={args.lna_gain}/VGA={args.vga_gain}.")
        print(f"Saved LNA={new_lna}/VGA={new_vga} for next run -- just re-run with no flags, "
              f"or pass --lna-gain {new_lna} --vga-gain {new_vga} explicitly.")
        sdr.save_config({
            "freq_hz": args.freq, "sample_rate": sdr.SAMPLE_RATE_DEFAULT, "offset_hz": sdr.OFFSET_HZ_DEFAULT,
            "lna_gain": new_lna, "vga_gain": new_vga, "amp_enable": args.amp, "hackrf_bin": args.hackrf_bin,
            "locked": False,
        })
        return 1

    rms_values = [b["deviation_rms_hz"] for b in bursts]
    peak_values = [b["deviation_peak_hz"] for b in bursts]
    reference_rms = sorted(rms_values)[len(rms_values) // 2]   # median, robust to one odd burst
    reference_peak = max(peak_values)

    config = {
        "freq_hz": args.freq,
        "sample_rate": sdr.SAMPLE_RATE_DEFAULT,
        "offset_hz": sdr.OFFSET_HZ_DEFAULT,
        "lna_gain": args.lna_gain,
        "vga_gain": args.vga_gain,
        "amp_enable": args.amp,
        "hackrf_bin": args.hackrf_bin,
        "reference_deviation_rms_hz": reference_rms,
        "reference_deviation_peak_hz": reference_peak,
        "reference_burst_count": len(bursts),
        "locked": True,
    }

    print(f"\nLocked gain LNA={args.lna_gain}/VGA={args.vga_gain}, no clipping.")
    print(f"Reference deviation: RMS {reference_rms:.0f} Hz, peak {reference_peak:.0f} Hz "
          f"(median/max across {len(bursts)} bursts)")
    if prior.get("locked") and prior.get("freq_hz") == args.freq and prior.get("reference_deviation_rms_hz"):
        prev_rms = prior["reference_deviation_rms_hz"]
        delta_pct = (reference_rms - prev_rms) / prev_rms * 100 if prev_rms else float("nan")
        print(f"Previous locked run: RMS {prev_rms:.0f} Hz -- this run differs by {delta_pct:+.0f}%")

    sdr.save_config(config)
    print(f"Saved to {sdr.CONFIG_PATH}")
    print("\nNow run sdr_listen.py while the digipeater's tx_volume_test.py runs on the Pi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
