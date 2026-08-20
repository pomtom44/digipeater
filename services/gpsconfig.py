"""Applies the GPS section of config.yaml to gpsd, system timezone, and chrony's GPS time refclock."""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_HELPER = str(Path(__file__).resolve().parent.parent / "scripts" / "apply-gps-config.sh")


async def apply(gps_config: dict) -> None:
    """Applies GPS config; idempotent, re-applied on every boot."""
    if not gps_config:
        return

    device = gps_config.get("device") or "none"
    if device.startswith("serial:"):
        device = device[len("serial:"):]
    elif device != "none":
        logger.error("Unrecognized GPS device value in config.yaml: %r, treating as no GPS", device)
        device = "none"

    time_sync = bool(gps_config.get("time_sync"))
    timezone = gps_config.get("timezone", "") if time_sync else ""

    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", _HELPER, device, "on" if time_sync else "off", timezone,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except OSError as e:
        logger.error("Failed to run GPS config helper: %s", e)
        return

    if proc.returncode != 0:
        logger.error("GPS config helper failed: %s", err.decode().strip())
    else:
        logger.info(
            "GPS config applied: device=%s time_sync=%s timezone=%s",
            device, time_sync, timezone or "-",
        )
