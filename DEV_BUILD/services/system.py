"""System-level actions and info (reboot, timezones) requested by the web layer."""

import asyncio
import logging

from services import gps, radio_programmer, relay, restart_policy

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
# "starting"/"stopping" while a set_direwolf_running() call is actively in
# flight (see its own docstring): systemd has no notion of this multi-step
# app-level sequence (GPS confirmation, relay timing, channel programming)
# being in progress, only "active"/"inactive" for the unit itself, which
# covers a much narrower span of time than the badge needs to reflect.
_transition: str | None = None
# The reason the most recently *completed* start/stop attempt failed, if
# it did; cleared on the next successful one. Lets a fresh page load (or a
# second browser tab) show "Error" too, not just the tab that made the
# failed attempt.
_last_error: str | None = None


def _idle_status(simulated: bool) -> dict:
    if simulated and _simulated_running:
        return {"available": True, "state": "running", "running": True, "reason": None, "simulated": True}
    state = "error" if _last_error else "standby"
    return {"available": True, "state": state, "running": False, "reason": _last_error, "simulated": simulated}


async def _query_direwolf_state() -> tuple[str, bytes] | None:
    """The literal `systemctl is-active` word ("active"/"activating"/
    "failed"/etc.) plus raw stderr, with none of get_direwolf_status()'s
    _transition/simulated-fallback interpretation layered on. None if
    systemctl itself isn't available (see _idle_status's simulated path).
    Shared by get_direwolf_status() and set_direwolf_running()'s post-start
    grace check below, both need the raw answer, not just the badge-ready
    version."""
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
    """The direwolf systemd service's state, or absent a real service to
    ask, the simulated in-memory state (see _simulated_running above).
    `state` is one of "running"/"starting"/"waiting_gps"/"standby"/
    "stopping"/"error"; `running` (bool) is kept alongside it for existing
    callers that only care about the binary question.

    `systemctl is-active` on a completely unknown unit still prints
    "inactive" on the systemd versions this was checked against (rather
    than an unambiguous "not found" state), so a missing unit and a real
    stopped one aren't perfectly distinguishable from stdout alone;
    stderr is checked too for the "could not be found" wording systemd
    prints in that case. Not verified against a real system in this
    sandbox (no systemd here); worth confirming on real hardware.
    """
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
        # systemd's own auto-restart loop cycling in the background (not
        # one set_direwolf_running triggered, hence no _transition set
        # above): reuse the same starting/stopping vocabulary so the badge
        # shows the same pending state either way.
        return {
            "available": True,
            "state": "starting" if state == "activating" else "stopping",
            "running": False, "reason": None, "simulated": False,
        }
    if state == "failed":
        # Reached once the restart policy's attempt limit is exhausted (see
        # services/restart_policy.py); before that fix this never happened
        # at all, since the unit had no StartLimitBurst and just retried
        # forever. Sticky until the next start attempt, same as an error
        # set_direwolf_running() caused directly (which clears this via its
        # own _last_error assignment).
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


# How often to re-check gpsd while waiting for a live fix, and how long to
# keep at it before giving up. gpsd was very likely just restarted this
# same boot (see services/gpsconfig.py), and a cold GPS fix can take
# anywhere from several seconds to a couple of minutes, so a single
# point-in-time check (the old behaviour) was failing real, working GPS
# hardware just because of bad timing. Bounded rather than unlimited so a
# genuinely absent/broken GPS doesn't leave a Start click hung forever.
GPS_FIX_POLL_INTERVAL_S = 5
GPS_FIX_WAIT_TIMEOUT_S = 300


async def _wait_for_gps_fix(gps_config: dict) -> tuple[bool, str | None]:
    """Gate before powering the radio on at all: a manual position only
    needs its lat/lon to actually be set (see first_run.html's GPS step),
    checked once and instantly. A live-GPS position needs gpsd to actually
    report a fix, which this polls for (see the constants above) rather
    than checking once, setting the module-level _transition to
    "waiting_gps" for the duration so get_direwolf_status() (and so the
    dashboard's badge and GPS card) can show it's actively waiting, not
    just stuck. Checked here rather than left to Direwolf itself, since
    PBEACON would otherwise happily beacon a stale/missing position with
    no indication anything's wrong."""
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
            # Not just "no fix yet": gpsd itself isn't reachable or has no
            # device at all. Waiting longer won't fix that (gpsd failed to
            # start, or the wrong device was picked), so fail immediately
            # rather than polling for the full timeout pointlessly.
            return False, status.get("reason", "GPS not available")
        if status.get("has_fix"):
            return True, None
        if asyncio.get_event_loop().time() >= deadline:
            return False, f"Timed out waiting for a GPS fix after {GPS_FIX_WAIT_TIMEOUT_S}s"
        _transition = "waiting_gps"
        await asyncio.sleep(GPS_FIX_POLL_INTERVAL_S)


# How many consecutive polls (DIREWOLF_STARTUP_POLL_INTERVAL_S apart) of a
# steady "active" state are needed before believing Direwolf has actually
# settled, not just forked. Type=simple means systemd considers the unit
# "active" the instant the process forks, well before Direwolf has opened
# its audio device; a real failure there showed up a few seconds after
# start in practice.
DIREWOLF_STARTUP_CONFIRM_S = 8
DIREWOLF_STARTUP_POLL_INTERVAL_S = 1


async def _supervise_direwolf_startup(attempts: int, delay_s: int) -> dict:
    """Called right after the first `systemctl start` succeeds. Doesn't
    call systemctl again itself: systemd's own Restart=on-failure/
    RestartSec=<delay_s>/StartLimitBurst=<attempts> (see
    services/restart_policy.py) is what actually retries a crashed
    Direwolf in the background, this just watches the real state and
    keeps the caller's _transition at "starting" for the *entire*
    multi-attempt cascade, so the dashboard badge never bounces to
    Running (or flickers) between attempts, only reporting the final,
    real outcome once one of two things happens: it settles on genuinely
    running (a steady "active" for DIREWOLF_STARTUP_CONFIRM_S straight,
    which naturally covers "worked first try" and "took a couple of
    retries" the same way), or systemd itself gives up after exhausting
    every attempt (state "failed").

    The deadline below is a generous safety-net ceiling, not the normal
    way a multi-attempt failure gets reported, that's the "failed" check,
    which fires as soon as systemd gives up, almost always well before
    this ceiling. It only matters if something is genuinely stuck."""
    deadline = asyncio.get_event_loop().time() + attempts * (delay_s + 15) + 30
    consecutive_active = 0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(DIREWOLF_STARTUP_POLL_INTERVAL_S)
        queried = await _query_direwolf_state()
        if queried is None:
            # systemctl vanished mid-check (shouldn't happen if _run_systemctl
            # just succeeded moments ago); nothing more to learn from here.
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
            # "activating"/"deactivating": mid-retry-cycle (waiting out
            # RestartSec for the next attempt), not a failure by itself.
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
    """Starts or stops the direwolf systemd service, wrapping the actual
    systemctl call (see _run_systemctl) with the full radio power
    sequence around it. Or, absent a real service to control, flips the
    simulated in-memory state instead (see _simulated_running above),
    still going through the same GPS/relay/programmer sequence either way
    so that UX (timing, failure messages) matches what a real Pi would do.

    Starting: wait for a GPS fix, polling rather than a single check (see
    _wait_for_gps_fix) -> power the radio on (services/relay.py, ~10s boot
    wait) -> program its channel if the configured model supports it
    (services/radio_programmer.py, currently a no-op stub, see its own
    docstring) -> a short settle wait -> only then start Direwolf. A
    failure at any step before Direwolf actually starts backs the relay
    off again rather than leaving the radio powered with nothing using it.

    Stopping: stop Direwolf first, then wait for it to actually finish
    releasing the audio device / de-keying PTT before cutting power to
    the radio, rather than cutting power out from under a process that
    might still be mid-shutdown.

    Needs its own narrowly-scoped sudoers rule for the real systemctl
    path: exactly these two commands, not blanket systemctl access (which
    could stop/restart any unit, including this app's own service),
    installed by install.sh as /etc/sudoers.d/digipeater-direwolf-control.

    Sets the module-level _transition flag ("starting"/"waiting_gps"/
    "stopping") for the full duration of this call, cleared via `finally`
    no matter which return path executes below, so get_direwolf_status()
    can report it even from a different request/tab than the one that
    triggered it.
    """
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
            # systemctl accepting the start command isn't the same as
            # Direwolf actually staying up, see _supervise_direwolf_startup.
            startup_cfg = config.get("startup", {}) or {}
            attempts = (
                int(startup_cfg.get("restart_attempts") or restart_policy.DEFAULT_RESTART_ATTEMPTS)
                if startup_cfg.get("autorestart", True) else 1
            )
            delay_s = int(startup_cfg.get("restart_delay_s") or restart_policy.DEFAULT_RESTART_DELAY_S)
            result = await _supervise_direwolf_startup(attempts, delay_s)

        if running and not result["ok"]:
            # Powered the relay on for nothing; don't leave the radio
            # powered with no Direwolf process actually using it.
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
    """Recent journalctl output for the direwolf unit: backs the
    dashboard's error-state "view logs" modal (see web/server.py's
    /api/system/direwolf/logs), the actual detail behind a sticky "Error"
    badge instead of a raw error string on the page itself. Needs sudo,
    a normal user isn't guaranteed read access to the systemd journal;
    scoped to exactly this fixed command (see install.sh's
    digipeater-journalctl sudoers rule), not blanket journal access."""
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
