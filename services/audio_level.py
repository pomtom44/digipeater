"""Measures a short burst of raw audio from an ALSA capture device and scores it on Direwolf's own
"audio level" convention -- peak-to-peak amplitude, normalized the same way Direwolf's demodulator
does (src/demod.c: `fsam = sample / 16384.0`, `alevel.rec = (peak - valley) * 50`) -- so the radio
setup page's live meter lines up with Direwolf's documented "~50 is the target" guidance for tuning
the radio's volume against background static. This is a standalone measurement (via `arecord`, not
Direwolf's own smoothed envelope follower), so treat it as a close approximation, not an exact replay
of what Direwolf itself would report once running.
"""

import asyncio
import logging
import struct

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 8000
# Each call opens a fresh ALSA stream (simplest implementation, and the only way that doesn't hold the
# device open between polls, blocking Direwolf from ever starting). USB audio codecs commonly need a
# short settle time right after a stream opens (DC-coupling/mute ramp-off), which shows up as a brief,
# much-louder-than-real transient -- confirmed against this project's own hardware: `arecord -V mono`
# run continuously on the same signal never shows it, only our open-capture-close-repeat approach does.
# Capture a bit longer than we need and throw away the warm-up portion before measuring anything.
_WARMUP_SECONDS = 0.15
_MEASURE_SECONDS = 0.35
_CAPTURE_SECONDS = _WARMUP_SECONDS + _MEASURE_SECONDS
_CAPTURE_BYTES = int(_SAMPLE_RATE * _CAPTURE_SECONDS) * 2  # 16-bit mono
_WARMUP_BYTES = int(_SAMPLE_RATE * _WARMUP_SECONDS) * 2
_CAPTURE_TIMEOUT_S = 3.0
_FSAM_DIVISOR = 16384.0
# Trims the most extreme ~1% of samples before taking peak/valley, so one stray sample (a USB
# underrun blip, electrical noise, anything not actually the incoming audio) can't swing the whole
# reading -- a true max()/min() is exactly one bad sample away from a false spike.
_TRIM_FRACTION = 0.01


def _trimmed_peak_valley(samples: tuple) -> tuple[int, int]:
    ordered = sorted(samples)
    n = len(ordered)
    trim = max(1, int(n * _TRIM_FRACTION))
    return ordered[n - 1 - trim], ordered[trim]


async def read_level(device: str) -> dict:
    """Returns {"ok": True, "level": int} (Direwolf-style 0-100ish scale) or {"ok": False, "reason": str}."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "arecord", "-D", device, "-f", "S16_LE", "-r", str(_SAMPLE_RATE), "-c", "1", "-t", "raw", "-q", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {"ok": False, "reason": "arecord isn't installed (alsa-utils)"}

    data = b""
    try:
        data = await asyncio.wait_for(proc.stdout.readexactly(_CAPTURE_BYTES), timeout=_CAPTURE_TIMEOUT_S)
    except asyncio.IncompleteReadError as e:
        data = e.partial
    except asyncio.TimeoutError:
        pass
    finally:
        if proc.returncode is None:
            proc.terminate()
        stderr_data = await proc.stderr.read()
        await proc.wait()

    data = data[_WARMUP_BYTES:]
    if len(data) < 4:
        reason = stderr_data.decode(errors="replace").strip() if stderr_data else ""
        # Direwolf (or anything else) holding the device open is the most likely real-world cause.
        if "busy" in reason.lower() or "resource" in reason.lower():
            reason = f"Audio device is busy -- stop Direwolf first ({reason})"
        return {"ok": False, "reason": reason or "No audio captured"}

    sample_count = len(data) // 2
    samples = struct.unpack(f"<{sample_count}h", data[:sample_count * 2])
    peak, valley = _trimmed_peak_valley(samples)
    level = round((peak - valley) / _FSAM_DIVISOR * 50)
    return {"ok": True, "level": level}
