"""Shared HackRF capture + FM-demod code for sdr_tune.py and sdr_listen.py.

Runs on the PC with the HackRF attached (not the Pi). Shells out to hackrf_transfer.exe (part of
PothosSDR, already installed) rather than using Python SDR bindings, to avoid ABI/driver friction.

Tunes slightly off the target frequency and digitally mixes back down, so the HackRF's DC spike
(which sits exactly at the tuned center) doesn't land on top of the signal being measured.
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from scipy import signal

HACKRF_BIN_DEFAULT = r"C:\Program Files\PothosSDR\bin\hackrf_transfer.exe"
SAMPLE_RATE_DEFAULT = 2_000_000
OFFSET_HZ_DEFAULT = 500_000       # tune this far below the target freq, mix back up in software
CHANNEL_HALF_BW_HZ = 8_000        # NBFM channel half-bandwidth for the low-pass filter
DECIMATE_FACTOR = 10              # 2,000,000 Hz -> 200,000 Hz baseband rate for demod
BLOCK_S = 0.02                    # power-detection block size
BURST_MARGIN_DB = 12.0            # how far above the noise floor counts as "a burst"
BURST_MIN_S = 0.3                 # ignore detected regions shorter than this (noise spikes)
BURST_MERGE_GAP_S = 0.1           # bridge gaps shorter than this between active blocks
CLIP_THRESHOLD = 126              # raw int8 sample magnitude considered ADC overload
CLIP_FRACTION_WARN = 0.001        # fraction of samples at/above CLIP_THRESHOLD that flags clipping

CONFIG_PATH = Path(__file__).parent / "sdr_config.json"


def capture_iq(freq_hz, duration_s, sample_rate, lna_gain, vga_gain, amp_enable,
               offset_hz=OFFSET_HZ_DEFAULT, hackrf_bin=HACKRF_BIN_DEFAULT):
    """Captures raw IQ via hackrf_transfer, tuned offset_hz below freq_hz. Returns complex128 baseband
    samples already mixed back up to freq_hz and decimated, plus the raw int8 bytes for clip checks."""
    tuned_freq = freq_hz - offset_hz
    num_samples = int(sample_rate * duration_s)
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        raw_path = Path(tmp.name)
    print(f"  [hackrf] tuning to {tuned_freq/1e6:.4f} MHz (target {freq_hz/1e6:.4f} MHz, "
          f"offset {offset_hz/1e6:+.4f} MHz), {sample_rate/1e6:.1f} Msps, "
          f"LNA={lna_gain} VGA={vga_gain} amp={'on' if amp_enable else 'off'}")
    try:
        cmd = [
            hackrf_bin, "-r", str(raw_path), "-f", str(tuned_freq), "-s", str(sample_rate),
            "-n", str(num_samples), "-l", str(lna_gain), "-g", str(vga_gain),
            "-a", "1" if amp_enable else "0",
        ]
        deadline = time.time() + duration_s + 15
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1)
        while True:
            line = proc.stderr.readline()
            if line:
                print(f"  [hackrf] {line.rstrip()}")
            elif proc.poll() is not None:
                break
            if time.time() > deadline:
                proc.kill()
                raise RuntimeError(f"hackrf_transfer did not finish within {duration_s + 15:.0f}s, killed it")
        returncode = proc.wait()
        raw_bytes = raw_path.read_bytes()
        if not raw_bytes:
            raise RuntimeError(f"hackrf_transfer produced no data (exit {returncode})")
        print(f"  [hackrf] capture done: {len(raw_bytes)/1e6:.1f} MB")
    finally:
        raw_path.unlink(missing_ok=True)

    raw_i8 = np.frombuffer(raw_bytes, dtype=np.int8)
    raw_i8 = raw_i8[: len(raw_i8) - (len(raw_i8) % 2)]  # drop a trailing odd byte, if any
    iq = raw_i8.astype(np.float32).reshape(-1, 2)
    complex_samples = (iq[:, 0] + 1j * iq[:, 1]) / 128.0

    n = np.arange(complex_samples.size)
    mixer = np.exp(-1j * 2 * np.pi * offset_hz * n / sample_rate)
    mixed = complex_samples * mixer

    nyquist = sample_rate / 2
    sos = signal.butter(6, CHANNEL_HALF_BW_HZ / nyquist, btype="low", output="sos")
    filtered = signal.sosfiltfilt(sos, mixed)
    baseband = signal.decimate(filtered, DECIMATE_FACTOR, ftype="fir")
    baseband_rate = sample_rate / DECIMATE_FACTOR

    return baseband, baseband_rate, raw_i8


def fm_demod(baseband, baseband_rate):
    """Instantaneous-frequency FM demod: returns deviation in Hz, one sample shorter than input."""
    phase_diff = np.angle(baseband[1:] * np.conj(baseband[:-1]))
    return phase_diff * baseband_rate / (2 * np.pi)


def find_bursts(baseband, baseband_rate):
    """Splits a capture into (start_s, end_s) regions where RF power sits well above the noise floor."""
    block_n = max(1, int(baseband_rate * BLOCK_S))
    n_blocks = len(baseband) // block_n
    if n_blocks == 0:
        return []
    power = np.array([
        np.mean(np.abs(baseband[i * block_n:(i + 1) * block_n]) ** 2)
        for i in range(n_blocks)
    ])
    power_db = 10 * np.log10(power + 1e-12)
    noise_floor_db = np.percentile(power_db, 10)
    active = power_db > (noise_floor_db + BURST_MARGIN_DB)

    merge_blocks = max(1, int(BURST_MERGE_GAP_S / BLOCK_S))
    min_blocks = max(1, int(BURST_MIN_S / BLOCK_S))
    bursts = []
    i = 0
    while i < len(active):
        if not active[i]:
            i += 1
            continue
        start = i
        while i < len(active):
            if active[i]:
                i += 1
                continue
            # allow a short gap before deciding the burst really ended
            lookahead = active[i:i + merge_blocks]
            if lookahead.any():
                i += 1
                continue
            break
        end = i
        if end - start >= min_blocks:
            bursts.append((start * BLOCK_S, end * BLOCK_S))
    return bursts


EDGE_TRIM_S = 0.05     # phase is ill-defined right at keyup/keydown (amplitude crosses near-zero);
                       # trim this much off each end of a burst before computing deviation metrics
PEAK_PERCENTILE = 99.0  # use a percentile instead of true max, to reject single-sample phase glitches


def analyze_capture(baseband, baseband_rate, raw_i8, sample_rate, freq_hz):
    """Returns a list of per-burst metric dicts for one capture. freq_hz is the target frequency the
    baseband has already been mixed to 0 Hz against -- a burst's mean instantaneous frequency is then
    directly the actual transmitter's frequency error, used here to report what it was really on."""
    bursts = find_bursts(baseband, baseband_rate)
    demod = fm_demod(baseband, baseband_rate)
    results = []
    for start_s, end_s in bursts:
        trimmed_start_s = start_s + EDGE_TRIM_S
        trimmed_end_s = end_s - EDGE_TRIM_S
        if trimmed_end_s <= trimmed_start_s:
            trimmed_start_s, trimmed_end_s = start_s, end_s  # burst too short to trim, use it whole
        start_i = int(trimmed_start_s * baseband_rate)
        end_i = min(int(trimmed_end_s * baseband_rate), len(demod))
        if end_i <= start_i:
            continue
        segment = demod[start_i:end_i]

        raw_start = int(start_s * sample_rate) * 2
        raw_end = int(end_s * sample_rate) * 2
        raw_segment = raw_i8[raw_start:raw_end]
        clip_fraction = float(np.mean(np.abs(raw_segment) >= CLIP_THRESHOLD)) if raw_segment.size else 0.0
        freq_offset_hz = float(np.mean(segment))  # steady-carrier offset, modulation averages out

        results.append({
            "start_s": round(start_s, 2),
            "end_s": round(end_s, 2),
            "duration_s": round(end_s - start_s, 2),
            "measured_freq_hz": round(freq_hz + freq_offset_hz, 1),
            "freq_offset_hz": round(freq_offset_hz, 1),
            "deviation_rms_hz": round(float(np.sqrt(np.mean((segment - freq_offset_hz) ** 2))), 1),
            "deviation_peak_hz": round(float(np.percentile(np.abs(segment - freq_offset_hz), PEAK_PERCENTILE)), 1),
            "clipped": clip_fraction >= CLIP_FRACTION_WARN,
            "clip_fraction": round(clip_fraction, 5),
        })
    return results


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def load_partial_config() -> dict | None:
    """Like load_config, but returns None instead of raising when there's nothing saved yet --
    for picking up defaults from a previous (possibly clipped/unlocked) sdr_tune.py attempt."""
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{CONFIG_PATH} not found -- run sdr_tune.py first to pick and save gain settings"
        )
    return json.loads(CONFIG_PATH.read_text())
