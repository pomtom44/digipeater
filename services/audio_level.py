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
import math
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
        # Direwolf holding the device open is the most common real-world cause, but this app's own
        # audio-level meter and loopback test (below) also share this device and can collide with
        # each other if run concurrently -- don't name Direwolf specifically, it may not be it.
        if "busy" in reason.lower() or "resource" in reason.lower():
            reason = f"Audio device is busy -- stop Direwolf first, or wait if another audio test is running ({reason})"
        return {"ok": False, "reason": reason or "No audio captured"}

    sample_count = len(data) // 2
    samples = struct.unpack(f"<{sample_count}h", data[:sample_count * 2])
    peak, valley = _trimmed_peak_valley(samples)
    level = round((peak - valley) / _FSAM_DIVISOR * 50)
    return {"ok": True, "level": level}


# ── Line-out -> mic-in loopback clipping check ──
# Jumper the Pi's headphone/line-out to its mic-in temporarily: plays a known tone out one and
# records it back on the other, to confirm the Pi's own audio output isn't already clipping before
# it's ever wired into the radio. A clean sine's peak/RMS ("crest factor") is ~1.414 regardless of
# absolute level; clipping flattens the waveform's peaks, which pulls crest factor down -- that's a
# scale-invariant way to detect real distortion without needing to know the "right" absolute level,
# and it correctly ignores pure gain/attenuation in the loop (verified against synthetic clipped vs.
# merely-attenuated signals during development). Shares its device with read_level() above --
# web/static/shared.js's createLoopbackTest()/createAudioLevelMeter() coordinate so they don't run
# concurrently, but the busy-device message below stays generic since that's JS-side, not guaranteed.
_LOOPBACK_SAMPLE_RATE = 8000
_LOOPBACK_TONE_HZ = 1000.0
_LOOPBACK_DURATION_S = 1.0
_LOOPBACK_WARMUP_S = 0.15  # same USB codec settle-time reasoning as read_level, see module docstring
_LOOPBACK_CAPTURE_MARGIN_S = 0.5
_LOOPBACK_CREST_CLEAN = math.sqrt(2)
_LOOPBACK_CREST_DROP_WARN = 0.15


def _build_tone_pcm(duration_s: float, sample_rate: int, freq_hz: float) -> bytes:
    n = int(sample_rate * duration_s)
    frames = bytearray()
    phase = 0.0
    for _ in range(n):
        phase += 2 * math.pi * freq_hz / sample_rate
        frames += struct.pack("<h", int(32767 * math.sin(phase)))
    return bytes(frames)


async def test_loopback(play_device: str, capture_device: str) -> dict:
    """Returns {"ok": True, "clipped": bool, "crest_factor": float, ...} or {"ok": False, "reason": str}."""
    if not play_device or not capture_device:
        return {"ok": False, "reason": "No audio device selected"}

    tone_pcm = _build_tone_pcm(_LOOPBACK_DURATION_S, _LOOPBACK_SAMPLE_RATE, _LOOPBACK_TONE_HZ)
    capture_bytes = int(_LOOPBACK_SAMPLE_RATE *
                         (_LOOPBACK_DURATION_S + _LOOPBACK_WARMUP_S + _LOOPBACK_CAPTURE_MARGIN_S)) * 2

    try:
        recorder = await asyncio.create_subprocess_exec(
            "arecord", "-D", capture_device, "-f", "S16_LE", "-r", str(_LOOPBACK_SAMPLE_RATE),
            "-c", "1", "-t", "raw", "-q", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {"ok": False, "reason": "arecord isn't installed (alsa-utils)"}
    await asyncio.sleep(0.3)  # let arecord open the device before playback starts, same as read_level

    try:
        player = await asyncio.create_subprocess_exec(
            "aplay", "-D", play_device, "-f", "S16_LE", "-r", str(_LOOPBACK_SAMPLE_RATE), "-c", "1",
            "-t", "raw", "-q", "-",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        recorder.terminate()
        await recorder.wait()
        return {"ok": False, "reason": "aplay isn't installed (alsa-utils)"}

    _, player_stderr = await player.communicate(tone_pcm)

    data = b""
    stderr_data = b""
    try:
        data = await asyncio.wait_for(recorder.stdout.readexactly(capture_bytes), timeout=_CAPTURE_TIMEOUT_S)
    except asyncio.IncompleteReadError as e:
        data = e.partial
    except asyncio.TimeoutError:
        pass
    finally:
        if recorder.returncode is None:
            recorder.terminate()
        stderr_data = await recorder.stderr.read()
        await recorder.wait()

    if player.returncode not in (0, None):
        reason = player_stderr.decode(errors="replace").strip() if player_stderr else "aplay failed"
        return {"ok": False, "reason": f"Playback failed: {reason}"}

    warmup_bytes = int(_LOOPBACK_SAMPLE_RATE * _LOOPBACK_WARMUP_S) * 2
    data = data[warmup_bytes:]
    if len(data) < 4:
        reason = stderr_data.decode(errors="replace").strip() if stderr_data else ""
        if "busy" in reason.lower() or "resource" in reason.lower():
            reason = f"Audio device is busy -- stop Direwolf first, or wait if another audio test is running ({reason})"
        return {"ok": False, "reason": reason or "No audio captured"}

    sample_count = len(data) // 2
    samples = struct.unpack(f"<{sample_count}h", data[:sample_count * 2])
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms < 1:
        return {"ok": False, "reason": "No audio detected on the capture device -- check the jumper cable"}

    crest_factor = peak / rms
    crest_drop = _LOOPBACK_CREST_CLEAN - crest_factor
    return {
        "ok": True,
        "clipped": crest_drop >= _LOOPBACK_CREST_DROP_WARN,
        "crest_factor": round(crest_factor, 2),
        "peak": peak,
        "rms": round(rms, 1),
    }
