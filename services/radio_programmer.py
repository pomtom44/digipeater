"""Dispatches radio channel programming to the driver registered for the configured model, before Direwolf starts."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from services.radio_programmers import DRIVERS

logger = logging.getLogger(__name__)

PROGRAM_SETTLE_DELAY_S = 5

# Remembers the image actually written last time, so the auto-start path (program_channel_if_changed)
# can skip a redundant rewrite on every boot/restart -- real serial time, and real EEPROM/flash wear.
_LAST_PROGRAMMED_PATH = Path("radio_programmed.json")


def can_program(model: str | None) -> bool:
    return (model or "") in DRIVERS


def _image_fingerprint(radio_config: dict) -> str | None:
    """model:sha256(built image), or None if this model isn't programmable or the image can't be
    built from the given config (e.g. a required field like frequency is missing) -- in both cases
    the caller falls through to program_channel()'s own handling instead of fingerprinting."""
    model = radio_config.get("model")
    driver = DRIVERS.get(model or "")
    if driver is None:
        return None
    try:
        image = driver.build_image(radio_config)
    except Exception:
        return None
    return f"{model}:{hashlib.sha256(bytes(image)).hexdigest()}"


def _load_last_fingerprint() -> str | None:
    if not _LAST_PROGRAMMED_PATH.exists():
        return None
    try:
        return json.loads(_LAST_PROGRAMMED_PATH.read_text()).get("fingerprint")
    except Exception:
        return None


def _save_last_fingerprint(fingerprint: str) -> None:
    try:
        _LAST_PROGRAMMED_PATH.write_text(json.dumps({"fingerprint": fingerprint}))
    except OSError as e:
        logger.error("Failed to save last-programmed radio fingerprint: %s", e)


async def program_channel(radio_config: dict, on_progress=None) -> dict:
    """Always writes when called -- used directly by the manual Write-to-radio button, which is a
    forced rewrite regardless of whether anything changed. If given, on_progress(blocks_done,
    blocks_total) is called from the driver's worker thread after each block write -- a plain
    callback, not a coroutine, since it crosses from the executor thread back into this event-loop
    code without its own async machinery."""
    model = radio_config.get("model")
    driver = DRIVERS.get(model or "")
    if driver is None:
        return {"ok": True, "skipped": True, "reason": None}

    port = radio_config.get("programmer_port")
    if not port:
        # No cable port chosen; assume the radio was already programmed by hand rather than blocking Direwolf.
        return {"ok": True, "skipped": True, "reason": None}

    try:
        image = driver.build_image(radio_config)
        await asyncio.get_event_loop().run_in_executor(None, driver.program_sync, port, image, on_progress)
    except (IOError, OSError) as e:
        logger.error("Radio programming failed: %s", e)
        return {"ok": False, "skipped": False, "reason": str(e)}

    logger.info("Programmed %s channel 0 via %s", model, port)
    fingerprint = _image_fingerprint(radio_config)
    if fingerprint:
        _save_last_fingerprint(fingerprint)
    return {"ok": True, "skipped": False, "reason": None}


async def program_channel_if_changed(radio_config: dict) -> dict:
    """Used only by the auto-start path (services/system.py's set_direwolf_running): skips the write
    entirely if this exact config was already successfully written last time. The manual Write-to-radio
    button calls program_channel() directly instead, bypassing this check -- a forced rewrite regardless
    of whether anything changed is its whole purpose."""
    fingerprint = _image_fingerprint(radio_config)
    if fingerprint is not None and fingerprint == _load_last_fingerprint():
        logger.info("Radio config unchanged since last successful write, skipping auto-reprogram.")
        return {"ok": True, "skipped": True, "reason": None}
    return await program_channel(radio_config)
