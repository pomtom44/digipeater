"""Detects audio and serial hardware attached to the Pi, for the radio setup wizard."""

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_ASOUND_CARDS = Path("/proc/asound/cards")
# e.g. " 1 [CODEC          ]: USB-Audio - USB Audio CODEC"
_CARD_LINE_RE = re.compile(r"^\s*(\d+)\s*\[([^\]]*)\]:\s*(.*)$")


async def list_audio_devices() -> list[dict]:
    """List ALSA sound cards straight from /proc/asound/cards — a
    kernel-exposed file, so no extra package (e.g. alsa-utils) is needed."""
    if not _ASOUND_CARDS.exists():
        return []
    devices = []
    for line in _ASOUND_CARDS.read_text().splitlines():
        m = _CARD_LINE_RE.match(line)
        if not m:
            continue
        index, name, desc = m.groups()
        devices.append({"id": f"hw:{index}", "name": name.strip(), "description": desc.strip()})
    return devices


async def list_serial_devices() -> list[dict]:
    """List serial ports — USB-serial CAT cables, etc. Run in a thread since
    pyserial's enumeration does blocking udev/sysfs queries."""
    def _list():
        from serial.tools import list_ports
        return [
            {"device": p.device, "description": p.description or ""}
            for p in list_ports.comports()
        ]
    try:
        return await asyncio.to_thread(_list)
    except Exception as e:
        logger.error("Failed to list serial devices: %s", e)
        return []
