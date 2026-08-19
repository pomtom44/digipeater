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
    """Lists ALSA sound cards from /proc/asound/cards, flagging which have capture input."""
    if not _ASOUND_CARDS.exists():
        return []
    devices = []
    for line in _ASOUND_CARDS.read_text().splitlines():
        m = _CARD_LINE_RE.match(line)
        if not m:
            continue
        index, name, desc = m.groups()
        has_input = any(Path(f"/proc/asound/card{index}").glob("pcm*c"))
        devices.append({
            "id": f"hw:{index}", "name": name.strip(), "description": desc.strip(),
            "has_input": has_input,
        })
    return devices


async def list_serial_devices() -> list[dict]:
    """Lists serial ports (USB-serial CAT cables etc), run in a thread since pyserial's enumeration blocks."""
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


# USB VID/PID pairs for CM108/CM119-family chips (and compatible clones) that Direwolf can drive.
_CM108_IDS = {(0x0d8c, pid) for pid in range(0x0008, 0x0010)} | {
    (0x0d8c, 0x0012),  # CM108B
    (0x0d8c, 0x0013),  # CM119B
    (0x0d8c, 0x0139),  # CM108AH
    (0x0d8c, 0x013a),  # CM119A
    (0x0d8c, 0x013c),  # CM108AH / HS100
    (0x0c76, 0x1605),  # SSS1621, SSS1623
    (0x0c76, 0x1607),  # SSS1623
    (0x0c76, 0x160b),  # SSS1623
    (0x1209, 0x7388),  # AIOC (microcontroller-based emulation)
}


def _read_text(path: Path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _read_hex(path: Path):
    text = _read_text(path)
    try:
        return int(text, 16) if text else None
    except ValueError:
        return None


def _find_usb_device_dir(start: Path, max_depth: int = 6):
    """Walks up from a hidraw sysfs entry to the enclosing USB device directory (with idVendor/idProduct)."""
    current = start.resolve()
    for _ in range(max_depth):
        if (current / "idVendor").exists() and (current / "idProduct").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent
    return None


async def list_cm108_devices() -> list[dict]:
    """Lists connected CM108/CM119-family USB adapters usable for Direwolf's PTT CM108."""
    def _list():
        base = Path("/sys/class/hidraw")
        if not base.exists():
            return []
        results = []
        for entry in sorted(base.iterdir()):
            usb_dir = _find_usb_device_dir(entry / "device")
            if usb_dir is None:
                continue
            vid, pid = _read_hex(usb_dir / "idVendor"), _read_hex(usb_dir / "idProduct")
            if vid is None or pid is None or (vid, pid) not in _CM108_IDS:
                continue
            product = _read_text(usb_dir / "product") or "CM108-compatible USB adapter"
            results.append({"device": f"/dev/{entry.name}", "description": product})
        return results
    try:
        return await asyncio.to_thread(_list)
    except Exception as e:
        logger.error("Failed to list CM108 devices: %s", e)
        return []
