"""System-level actions and info (reboot, timezones) requested by the web layer."""

import asyncio
import logging

from services import gps, radio_programmer, relay, restart_policy

logger = logging.getLogger(__name__)


async def reboot() -> None:
    """Reboots the Pi via a dedicated sudoers rule."""
    logger.info("Rebooting...")
    proc = await asyncio.create_subprocess_exec("sudo", "-n", "reboot")
    await proc.wait()


_DIREWOLF_UNIT = "direwolf"

# In-memory fallback state used when systemctl/the direwolf unit isn't available; marked "simulated": True.
_simulated_running = False
# "starting"/"stopping" while set_direwolf_running() is actively in flight.
_transition: str | None = None
# Reason the last completed start/stop attempt failed, if any; cleared on next success.
_last_error: str | None = None


def _idle_status(simulated: bool) -> dict:
    if simulated and _simulated_running:
        return {"available": True, "state": "running", "running": True, "reason": None, "simulated": True}
    state = "error" if _last_error else "standby"
    return {"available": True, "state": state, "running": False, "reason": _last_error, "simulated": simulated}


async def _query_direwolf_state() -> tuple[str, bytes] | None:
    """Returns the raw `systemctl is-active` word plus stderr, or None if systemctl isn't available."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", _DIREWOLF_UNIT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        return None
    return stdout.decode(errors="replace").strip(), stderr


async def get_direwolf_status() -> dict:
    """Returns the direwolf service state (running/starting/waiting_gps/standby/stopping/error); checks
    stderr too since a missing unit and a stopped one both report "inactive"."""
    global _last_error
    if _transition:
        return {"available": True, "state": _transition, "running": False, "reason": None, "simulated": False}
    queried = await _query_direwolf_state()
    if queried is None:
        return _idle_status(simulated=True)
    state, stderr = queried
    if state == "active":
        return {"available": True, "state": "running", "running": True, "reason": None, "simulated": False}
    if state in ("activating", "deactivating"):
        # systemd's own auto-restart loop cycling in the background; reuse starting/stopping vocabulary.
        return {
            "available": True,
            "state": "starting" if state == "activating" else "stopping",
            "running": False, "reason": None, "simulated": False,
        }
    if state == "failed":
        # Reached when the restart policy's attempt limit is exhausted; sticky until the next start attempt.
        if not _last_error:
            _last_error = (
                "Direwolf kept failing to start and exceeded its configured "
                "restart limit (see the Startup tab). Check journalctl -u "
                "direwolf for why."
            )
        return {"available": True, "state": "error", "running": False, "reason": _last_error, "simulated": False}
    if b"could not be found" in stderr or b"not been loaded" in stderr:
        return _idle_status(simulated=True)
    return _idle_status(simulated=False)


# How often to poll gpsd for a fix, and how long to wait before giving up.
GPS_FIX_POLL_INTERVAL_S = 5
GPS_FIX_WAIT_TIMEOUT_S = 300


async def _wait_for_gps_fix(gps_config: dict) -> tuple[bool, str | None]:
    """Gate before powering the radio on: checks a manual position instantly, or polls gpsd for a live fix."""
    global _transition
    if gps_config.get("position_source") == "manual":
        lat, lon = gps_config.get("latitude"), gps_config.get("longitude")
        if lat in (None, "") or lon in (None, ""):
            return False, "No manual position set"
        return True, None

    deadline = asyncio.get_event_loop().time() + GPS_FIX_WAIT_TIMEOUT_S
    while True:
        status = await gps.get_status()
        if not status.get("available"):
            # gpsd itself isn't reachable, not just "no fix yet"; fail immediately rather than polling.
            return False, status.get("reason", "GPS not available")
        if status.get("has_fix"):
            return True, None
        if asyncio.get_event_loop().time() >= deadline:
            return False, f"Timed out waiting for a GPS fix after {GPS_FIX_WAIT_TIMEOUT_S}s"
        _transition = "waiting_gps"
        await asyncio.sleep(GPS_FIX_POLL_INTERVAL_S)


# Consecutive polls of a steady "active" state needed to confirm Direwolf has actually settled, not just forked.
DIREWOLF_STARTUP_CONFIRM_S = 8
DIREWOLF_STARTUP_POLL_INTERVAL_S = 1


async def _supervise_direwolf_startup(attempts: int, delay_s: int) -> dict:
    """Watches Direwolf's state after start, until it settles active or systemd exhausts its restart attempts."""
    deadline = asyncio.get_event_loop().time() + attempts * (delay_s + 15) + 30
    consecutive_active = 0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(DIREWOLF_STARTUP_POLL_INTERVAL_S)
        queried = await _query_direwolf_state()
        if queried is None:
            # systemctl vanished mid-check; nothing more to learn from here.
            return {"ok": True, "reason": None, "simulated": False}
        state, _ = queried
        if state == "failed":
            return {
                "ok": False,
                "reason": (
                    f"Direwolf failed to start after {attempts} attempt(s). "
                    "See the logs for details."
                ),
            }
        if state == "active":
            consecutive_active += 1
            if consecutive_active >= DIREWOLF_STARTUP_CONFIRM_S:
                return {"ok": True, "reason": None, "simulated": False}
        else:
            # activating/deactivating: mid-retry-cycle, not a failure by itself.
            consecutive_active = 0
    return {
        "ok": False,
        "reason": "Timed out waiting to confirm Direwolf actually started. See the logs for details.",
    }


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
    """Starts or stops direwolf, sequencing GPS fix wait, radio power, channel programming, and settle
    time around the systemctl call."""
    global _transition, _last_error
    config = config or {}
    action = "start" if running else "stop"
    _transition = "starting" if running else "stopping"
    try:
        if running:
            gps_ok, gps_reason = await _wait_for_gps_fix(config.get("gps", {}))
            _transition = "starting"  # back from _wait_for_gps_fix's "waiting_gps"
            if not gps_ok:
                logger.error("Direwolf start blocked: %s", gps_reason)
                _last_error = f"Cannot start Direwolf: {gps_reason}"
                return {"ok": False, "reason": _last_error}

            await relay.power_on()

            radio_config = config.get("radio", {})
            prog_result = await radio_programmer.program_channel(radio_config)
            if not prog_result["ok"]:
                await relay.power_off()
                _last_error = f"Radio programming failed: {prog_result['reason']}"
                logger.error(_last_error)
                return {"ok": False, "reason": _last_error}
            await asyncio.sleep(radio_programmer.PROGRAM_SETTLE_DELAY_S)

        result = await _run_systemctl(action)
        if running and result["ok"] and not result.get("simulated"):
            # systemctl accepting the start command isn't the same as Direwolf staying up.
            startup_cfg = config.get("startup", {}) or {}
            attempts = (
                int(startup_cfg.get("restart_attempts") or restart_policy.DEFAULT_RESTART_ATTEMPTS)
                if startup_cfg.get("autorestart", True) else 1
            )
            delay_s = int(startup_cfg.get("restart_delay_s") or restart_policy.DEFAULT_RESTART_DELAY_S)
            result = await _supervise_direwolf_startup(attempts, delay_s)

        if running and not result["ok"]:
            # Don't leave the radio powered with no Direwolf process using it.
            await relay.power_off()
        elif not running and result["ok"]:
            await asyncio.sleep(relay.SHUTDOWN_DELAY_S)
            await relay.power_off()

        _last_error = None if result["ok"] else result["reason"]
        return result
    finally:
        _transition = None


_DIREWOLF_LOG_LINES = 200


async def get_direwolf_logs() -> str:
    """Returns recent journalctl output for the direwolf unit, for the dashboard's error-state logs modal."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "journalctl", "-u", _DIREWOLF_UNIT,
            "-n", str(_DIREWOLF_LOG_LINES), "--no-pager", "--no-hostname",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        return "journalctl is not available (not running under systemd)."
    if proc.returncode != 0:
        return f"Could not read logs: {stderr.decode(errors='replace').strip()}"
    return stdout.decode(errors="replace") or "No log output yet."


# Fallback zones used only if the real tzdata lookup comes up empty.
_TIMEZONE_FALLBACK = [
    "UTC", "Pacific/Auckland", "Australia/Sydney", "Asia/Tokyo",
    "Asia/Shanghai", "Asia/Kolkata", "Asia/Dubai", "Europe/Moscow",
    "Europe/Berlin", "Europe/London", "Africa/Johannesburg",
    "America/Sao_Paulo", "America/New_York", "America/Chicago",
    "America/Denver", "America/Los_Angeles", "Pacific/Honolulu",
]


async def list_timezones() -> list[str]:
    """Returns real IANA timezone names from Python's tzdata."""
    def _list():
        from zoneinfo import available_timezones
        return sorted(available_timezones())
    zones = await asyncio.to_thread(_list)
    return zones if zones else _TIMEZONE_FALLBACK
