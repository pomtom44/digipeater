"""Time synchronisation — NTP first, GPS fallback."""

import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def sync_ntp(servers: list[str]) -> bool:
    """Attempt NTP sync via chronyc or timedatectl. Returns True on success."""
    for server in servers:
        try:
            result = await asyncio.create_subprocess_exec(
                "chronyc", "makestep",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await result.wait()
            if result.returncode == 0:
                logger.info("NTP sync successful via chronyc")
                return True
        except FileNotFoundError:
            pass

    # Fallback: timedatectl
    try:
        result = await asyncio.create_subprocess_exec(
            "timedatectl", "set-ntp", "true",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await result.wait()
        if result.returncode == 0:
            logger.info("NTP enabled via timedatectl")
            return True
    except FileNotFoundError:
        pass

    logger.warning("NTP sync failed — no suitable tool found")
    return False


async def set_time_from_gps(dt: datetime) -> bool:
    """Set system time from a GPS datetime. Requires root or sudo."""
    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    try:
        result = await asyncio.create_subprocess_exec(
            "sudo", "date", "-s", time_str,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await result.wait()
        if result.returncode == 0:
            logger.info("System time set from GPS: %s", time_str)
            return True
    except Exception as e:
        logger.error("Failed to set time from GPS: %s", e)
    return False


async def ensure_time_sync(config: dict, gps_time: Optional[datetime] = None) -> bool:
    """
    Try NTP first. If that fails and we have a GPS time, use that.
    Returns True once time is considered reliable.
    """
    servers = config.get("time", {}).get("ntp_servers", ["pool.ntp.org"])

    if await sync_ntp(servers):
        return True

    if gps_time:
        logger.info("NTP unavailable — using GPS time")
        return await set_time_from_gps(gps_time)

    logger.warning("No reliable time source available")
    return False
