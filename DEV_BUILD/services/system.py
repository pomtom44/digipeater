"""System-level actions and info (reboot, timezones) requested by the web layer."""

import asyncio
import logging

from services import gps, radio_programmer, relay

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

# In-memory fallback used only when there's no real answer available: no
# systemctl at all (e.g. this project's own dev sandbox, which can't run
# Linux binaries), or a real Linux box that hasn't run install.sh yet (no
# direwolf.service unit installed). On a normally-installed Pi this is
# dead code in practice, since both the unit and systemctl are always
# there, but it's what let the dashboard's start/stop UX (confirm modal,
# login gating, badge state) get built and tested before install.sh
# actually created the unit. Every response built from this path sets
# "simulated": True so the frontend can label it clearly rather than
# imply real control that doesn't exist; a real systemd answer always
# takes priority over this.
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


async def _confirm_gps_ready(gps_config: dict) -> tuple[bool, str | None]:
    """Gate before powering the radio on at all: a manual position only
    needs its lat/lon to actually be set (see first_run.html's GPS step),
    a live-GPS position needs gpsd to currently report an actual fix, not
    just be running. Checked here rather than left to Direwolf itself,
    since PBEACON would otherwise happily beacon a stale/missing position
    with no indication anything's wrong."""
    if gps_config.get("position_source") == "manual":
        lat, lon = gps_config.get("latitude"), gps_config.get("longitude")
        if lat in (None, "") or lon in (None, ""):
            return False, "No manual position set"
        return True, None
    status = await gps.get_status()
    if not status.get("available"):
        return False, status.get("reason", "GPS not available")
    if not status.get("has_fix"):
        return False, "Waiting for GPS fix"
    return True, None


async def _run_systemctl(action: str) -> dict:
    global _simulated_running
    running = action == "start"
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


async def set_direwolf_running(running: bool, config: dict | None = None) -> dict:
    """Starts or stops the direwolf systemd service, wrapping the actual
    systemctl call (see _run_systemctl) with the full radio power
    sequence around it. Or, absent a real service to control, flips the
    simulated in-memory state instead (see _simulated_running above),
    still going through the same GPS/relay/programmer sequence either way
    so that UX (timing, failure messages) matches what a real Pi would do.

    Starting: confirm GPS fix -> power the radio on (services/relay.py,
    ~10s boot wait) -> program its channel if the configured model
    supports it (services/radio_programmer.py, currently a no-op stub,
    see its own docstring) -> a short settle wait -> only then start
    Direwolf. A failure at any step before Direwolf actually starts backs
    the relay off again rather than leaving the radio powered with
    nothing using it.

    Stopping: stop Direwolf first, then wait for it to actually finish
    releasing the audio device / de-keying PTT before cutting power to
    the radio, rather than cutting power out from under a process that
    might still be mid-shutdown.

    Needs its own narrowly-scoped sudoers rule for the real systemctl
    path: exactly these two commands, not blanket systemctl access (which
    could stop/restart any unit, including this app's own service),
    installed by install.sh as /etc/sudoers.d/digipeater-direwolf-control.
    """
    config = config or {}
    action = "start" if running else "stop"

    if running:
        gps_ok, gps_reason = await _confirm_gps_ready(config.get("gps", {}))
        if not gps_ok:
            logger.error("Direwolf start blocked: %s", gps_reason)
            return {"ok": False, "reason": f"Cannot start Direwolf: {gps_reason}"}

        await relay.power_on()

        radio_config = config.get("radio", {})
        prog_result = await radio_programmer.program_channel(radio_config)
        if not prog_result["ok"]:
            await relay.power_off()
            reason = f"Radio programming failed: {prog_result['reason']}"
            logger.error(reason)
            return {"ok": False, "reason": reason}
        await asyncio.sleep(radio_programmer.PROGRAM_SETTLE_DELAY_S)

    result = await _run_systemctl(action)

    if running and not result["ok"]:
        # Powered the relay on for nothing; don't leave the radio
        # powered with no Direwolf process actually using it.
        await relay.power_off()
    elif not running and result["ok"]:
        await asyncio.sleep(relay.SHUTDOWN_DELAY_S)
        await relay.power_off()

    return result


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
