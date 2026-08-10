"""System-level actions and info (reboot, timezones) requested by the web layer."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def reboot() -> None:
    """Reboot the Pi. Needs its own narrowly-scoped sudoers rule (separate
    from network.py's nmcli rule, since it's a different binary) — installed
    by install.sh as /etc/sudoers.d/digipeater-reboot.
    """
    logger.info("Rebooting...")
    proc = await asyncio.create_subprocess_exec("sudo", "-n", "reboot")
    await proc.wait()


# Only used if the real system lookup below comes up empty (e.g. tzdata
# missing) — a small set of major zones so the picker is never completely
# empty, not the primary source of truth.
_TIMEZONE_FALLBACK = [
    "UTC", "Pacific/Auckland", "Australia/Sydney", "Asia/Tokyo",
    "Asia/Shanghai", "Asia/Kolkata", "Asia/Dubai", "Europe/Moscow",
    "Europe/Berlin", "Europe/London", "Africa/Johannesburg",
    "America/Sao_Paulo", "America/New_York", "America/Chicago",
    "America/Denver", "America/Los_Angeles", "Pacific/Honolulu",
]


async def list_timezones() -> list[str]:
    """Real IANA timezone names from Python's own tzdata — same list the OS
    itself would offer, not a hand-picked guess."""
    def _list():
        from zoneinfo import available_timezones
        return sorted(available_timezones())
    zones = await asyncio.to_thread(_list)
    return zones if zones else _TIMEZONE_FALLBACK
