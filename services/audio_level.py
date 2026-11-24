"""Measures a short burst from an ALSA capture device, scored on Direwolf's own "audio level"
convention, so the radio setup page's meter lines up with its own ~50-is-the-target guidance."""

import asyncio
import logging
import math
import struct

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 8000
# Fresh ALSA stream per call needs a short settle time before readings stabilize (USB codec
# mute-ramp transient); captures a bit longer and discards this warm-up portion.
_WARMUP_SECONDS = 0.15
_MEASURE_SECONDS = 0.35
_CAPTURE_SECONDS = _WARMUP_SECONDS + _MEASURE_SECONDS
_CAPTURE_BYTES = int(_SAMPLE_RATE * _CAPTURE_SECONDS) * 2  # 16-bit mono
_WARMUP_BYTES = int(_SAMPLE_RATE * _WARMUP_SECONDS) * 2
_CAPTURE_TIMEOUT_S = 3.0
_FSAM_DIVISOR = 16384.0
# Trims the most extreme ~1% of samples before peak/valley, so one stray sample can't swing
# the whole reading.
_TRIM_FRACTION = 0.01


def _trimmed_peak_valley(samples: tuple) -> tuple[int, int]:
    ordered = sorted(samples)
    n = len(ordered)
    trim = max(1, int(n * _TRIM_FRACTION))
    return ordered[n - 1 - trim], ordered[trim]


def _unpack_s16le(data: bytes) -> tuple[int, ...]:
    sample_count = len(data) // 2
    return struct.unpack(f"<{sample_count}h", data[:sample_count * 2])


def _describe_capture_failure(stderr_data: bytes) -> str:
    """Busy-device message shared by read_level/test_loopback -- stopping Direwolf is the common fix."""
    reason = stderr_data.decode(errors="replace").strip() if stderr_data else ""
    if "busy" in reason.lower() or "resource" in reason.lower():
        reason = f"Audio device is busy -- stop Direwolf first, or wait if another audio test is running ({reason})"
    return reason or "No audio captured"


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
        return {"ok": False, "reason": _describe_capture_failure(stderr_data)}

    samples = _unpack_s16le(data)
    peak, valley = _trimmed_peak_valley(samples)
    level = round((peak - valley) / _FSAM_DIVISOR * 50)
    return {"ok": True, "level": level}


# Line-out -> mic-in loopback clipping check: jumper headphone/line-out to mic-in, play a known
# tone, and check crest factor (peak/RMS) for clipping -- scale-invariant, ignores pure gain.
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

    tone_pcm = _build_tone_pcm(_LOOPBACK_DURATION_S, _SAMPLE_RATE, _LOOPBACK_TONE_HZ)
    capture_bytes = int(_SAMPLE_RATE *
                         (_LOOPBACK_DURATION_S + _LOOPBACK_WARMUP_S + _LOOPBACK_CAPTURE_MARGIN_S)) * 2

    try:
        recorder = await asyncio.create_subprocess_exec(
            "arecord", "-D", capture_device, "-f", "S16_LE", "-r", str(_SAMPLE_RATE),
            "-c", "1", "-t", "raw", "-q", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {"ok": False, "reason": "arecord isn't installed (alsa-utils)"}
    await asyncio.sleep(0.3)  # let arecord open the device before playback starts, same as read_level

    try:
        player = await asyncio.create_subprocess_exec(
            "aplay", "-D", play_device, "-f", "S16_LE", "-r", str(_SAMPLE_RATE), "-c", "1",
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

    warmup_bytes = int(_SAMPLE_RATE * _LOOPBACK_WARMUP_S) * 2
    data = data[warmup_bytes:]
    if len(data) < 4:
        return {"ok": False, "reason": _describe_capture_failure(stderr_data)}

    samples = _unpack_s16le(data)
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
