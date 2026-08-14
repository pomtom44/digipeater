"""System-level actions and info (reboot, timezones) requested by the web layer."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def reboot() -> None:
    """Reboot the Pi. Needs its own narrowly-scoped sudoers rule (separate
    from network.py's nmcli rule, since it's a different binary), installed
    by install.sh as /etc/sudoers.d/digipeater-reboot.
    """
    logger.info("Rebooting...")
    proc = await asyncio.create_subprocess_exec("sudo", "-n", "reboot")
    await proc.wait()


_DIREWOLF_UNIT = "direwolf"

# In-memory fallback used only when there's no real answer available (no
# systemctl at all (developing off a real Linux box) or systemctl exists
# but the direwolf.service unit doesn't yet, see TODO.md's direwolf.conf
# generator gap). Lets the dashboard's start/stop UX (confirm modal,
# login gating, badge state) actually be clicked through and tested
# before that gap is closed. Every response built from this path sets
# "simulated": True so the frontend can label it clearly rather than
# imply real control that doesn't exist; a real systemd answer, once
# there's a real unit to ask about, always takes priority over this.
_simulated_running = False


async def get_direwolf_status() -> dict:
    """Whether the direwolf systemd service is running. Or, absent a
    real service to ask, the simulated in-memory state (see
    _simulated_running above).

    `systemctl is-active` on a completely unknown unit still prints
    "inactive" on the systemd versions this was checked against (rather
    than an unambiguous "not found" state), so a missing unit and a real
    stopped one aren't perfectly distinguishable from stdout alone;
    stderr is checked too for the "could not be found" wording systemd
    prints in that case. Not verified against a real system in this
    sandbox (no systemd here); worth confirming on real hardware.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", _DIREWOLF_UNIT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        return {"available": True, "running": _simulated_running, "reason": None, "simulated": True}
    state = stdout.decode(errors="replace").strip()
    if state == "active":
        return {"available": True, "running": True, "reason": None, "simulated": False}
    if b"could not be found" in stderr or b"not been loaded" in stderr:
        return {"available": True, "running": _simulated_running, "reason": None, "simulated": True}
    return {"available": True, "running": False, "reason": None, "simulated": False}


async def set_direwolf_running(running: bool) -> dict:
    """Starts or stops the direwolf systemd service. Or, absent a real
    service to control, flips the simulated in-memory state instead (see
    _simulated_running above). Needs its own narrowly-scoped sudoers rule
    for the real path: exactly these two commands, not blanket systemctl
    access (which could stop/restart any unit, including this app's own
    service), installed by install.sh as
    /etc/sudoers.d/digipeater-direwolf-control.
    """
    global _simulated_running
    action = "start" if running else "stop"
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "systemctl", action, _DIREWOLF_UNIT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
    except FileNotFoundError:
        _simulated_running = running
        return {"ok": True, "reason": None, "simulated": True}
    if proc.returncode != 0:
        stderr_text = stderr.decode(errors="replace")
        if "could not be found" in stderr_text or "not been loaded" in stderr_text:
            _simulated_running = running
            return {"ok": True, "reason": None, "simulated": True}
        reason = stderr_text.strip() or f"systemctl {action} failed"
        logger.error("Direwolf %s failed: %s", action, reason)
        return {"ok": False, "reason": reason}
    logger.info("Direwolf %s succeeded", action)
    return {"ok": True, "reason": None, "simulated": False}


# Only used if the real system lookup below comes up empty (e.g. tzdata
# missing): a small set of major zones so the picker is never completely
# empty, not the primary source of truth.
_TIMEZONE_FALLBACK = [
    "UTC", "Pacific/Auckland", "Australia/Sydney", "Asia/Tokyo",
    "Asia/Shanghai", "Asia/Kolkata", "Asia/Dubai", "Europe/Moscow",
    "Europe/Berlin", "Europe/London", "Africa/Johannesburg",
    "America/Sao_Paulo", "America/New_York", "America/Chicago",
    "America/Denver", "America/Los_Angeles", "Pacific/Honolulu",
]


async def list_timezones() -> list[str]:
    """Real IANA timezone names from Python's own tzdata, same list the OS
    itself would offer, not a hand-picked guess."""
    def _list():
        from zoneinfo import available_timezones
        return sorted(available_timezones())
    zones = await asyncio.to_thread(_list)
    return zones if zones else _TIMEZONE_FALLBACK
