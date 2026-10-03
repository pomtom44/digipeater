import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from display.base import DisplayDriver
from display.rotation import load_pages
from display.waveshare import epdconfig
from services import (
    aprs, audio_level, auth, db, direwolf_config, gps, gpsconfig, hardware, log_settings, network,
    radio_programmer, relay, restart_policy, signal_test, system, tiles,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
# Session cookie for the web UI's security mode (none/readonly/full). Held in memory only; the
# Secure flag is omitted since the server runs plain HTTP.
SESSION_COOKIE_NAME = "digi_session"
SESSION_TTL_S = 7 * 24 * 3600
# WiFi credentials saved during first boot, applied later by main.py's normal-boot network flow.
WIFI_PENDING_PATH = Path("wifi_pending.json")
# Its existence marks first-boot setup complete; written by the wizard's Finish step.
CONFIG_PATH = Path("config.yaml")
# Written by install.sh's display-selection prompt and by the wizard's display step; read by main.py on every boot.
DISPLAY_CONFIG_PATH = Path("display_config.json")


def _build_test_image(display_driver: DisplayDriver):
    from PIL import Image, ImageDraw
    w, h = display_driver.width, display_driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w - 1, h - 1), outline=0)
    margin = display_driver.margin
    line_height = display_driver.line_height
    lines = [
        "APRS Digipeater",
        "E-Ink test pattern",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"{w} x {h}",
    ]
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill=0)
        y += line_height
    return image


_SENT_PACKET_TYPE_LABELS = {
    "digipeat": "Digipeat", "rf_beacon": "RF beacon", "igate_beacon": "IGate beacon",
    "igate_gate": "IGate gate", "message": "Message",
}


def _history_summary(log_type: str, e: dict) -> str:
    """One-line human-readable summary for the History page's table; the full row is still sent
    separately as "detail" for anyone who wants to see every field."""
    if log_type == "heard_stations":
        pos = f" ({e['latitude']:.4f}, {e['longitude']:.4f})" if e.get("latitude") is not None else ""
        comment = f" — {e['comment']}" if e.get("comment") else ""
        return f"Heard {e['callsign']}{pos}{comment}"
    if log_type == "sent_packets":
        label = _SENT_PACKET_TYPE_LABELS.get(e["type"], e["type"])
        return f"{label}: {e['callsign']}"
    if log_type == "direwolf_events":
        status = "ok" if e["ok"] else f"failed — {e.get('reason') or 'unknown reason'}"
        sim = " (simulated)" if e.get("simulated") else ""
        return f"Direwolf {e['action']}: {status}{sim}"
    if log_type == "radio_write_events":
        status = "ok" if e["ok"] else f"failed — {e.get('reason') or 'unknown reason'}"
        return f"Radio write ({e.get('model') or 'no model'}): {status}"
    if log_type == "config_changes":
        return f"Config changed: {e['section']}"
    if log_type == "gps_fix_events":
        status = "ok" if e["ok"] else f"failed — {e.get('reason') or 'unknown reason'}"
        return f"GPS fix: {status}"
    if log_type == "signal_test_results":
        status = "replied" if e.get("received") else "no reply (yet)"
        return f"Signal test → {e['target_callsign']}: {status}"
    if log_type == "system_events":
        return f"System: {e['type']}"
    return log_type


def create_app(
    display_driver: DisplayDriver, first_boot: bool, network_status: dict, rotation=None, packets=None,
) -> FastAPI:
    app = FastAPI(title="APRS Digipeater")

    # Static assets referenced by URL from the served HTML (e.g. APRS symbol sprite sheets).
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Tracks the in-progress region download, if any (one at a time).
    map_download_state = {"downloader": None}

    # token -> expiry (unix time)
    sessions: dict[str, float] = {}

    # Reused across live tile requests to keep upstream connections alive between range requests.
    live_tile_client = httpx.AsyncClient(timeout=15.0)

    def _read_security() -> dict:
        if not CONFIG_PATH.exists():
            return {"mode": "none"}
        try:
            config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception as e:
            logger.error("Failed to read %s: %s", CONFIG_PATH, e)
            return {"mode": "none"}
        return config.get("security", {}) or {"mode": "none"}

    def _create_session() -> str:
        token = secrets.token_urlsafe(32)
        sessions[token] = time.time() + SESSION_TTL_S
        return token

    def _is_logged_in(request: Request) -> bool:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if not token:
            return False
        expiry = sessions.get(token)
        if expiry is None:
            return False
        if time.time() > expiry:
            del sessions[token]
            return False
        return True

    @app.get("/")
    async def root(request: Request):
        if first_boot:
            return FileResponse(STATIC_DIR / "first_run.html")
        # "Full" security mode requires login even to view the dashboard, beyond gating changes.
        if _read_security().get("mode") == "full" and not _is_logged_in(request):
            return FileResponse(STATIC_DIR / "login.html")
        return FileResponse(STATIC_DIR / "normal.html")

    @app.get("/login")
    async def login_page():
        # No login during first boot; only the setup wizard should be reachable then.
        if first_boot:
            return RedirectResponse(url="/")
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/config")
    async def config_page(request: Request):
        if first_boot:
            return RedirectResponse(url="/")
        # Config changes require login under both readonly and full modes.
        mode = _read_security().get("mode", "none")
        if mode != "none" and not _is_logged_in(request):
            return FileResponse(STATIC_DIR / "login.html")
        return FileResponse(STATIC_DIR / "config.html")

    @app.get("/history")
    async def history_page(request: Request):
        if first_boot:
            return RedirectResponse(url="/")
        # Same gate as /config: history is operational/diagnostic detail, gated the same way as the live dashboard.
        mode = _read_security().get("mode", "none")
        if mode != "none" and not _is_logged_in(request):
            return FileResponse(STATIC_DIR / "login.html")
        return FileResponse(STATIC_DIR / "history.html")

    @app.get("/stats")
    async def stats_page(request: Request):
        if first_boot:
            return RedirectResponse(url="/")
        # Same gate as /config and /history.
        mode = _read_security().get("mode", "none")
        if mode != "none" and not _is_logged_in(request):
            return FileResponse(STATIC_DIR / "login.html")
        return FileResponse(STATIC_DIR / "stats.html")

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        return {"mode": _read_security().get("mode", "none"), "logged_in": _is_logged_in(request)}

    # Uses a native form POST (not fetch+redirect) so the Set-Cookie reliably lands before navigation; 303 makes the browser follow up with GET.
    @app.post("/api/auth/login")
    async def auth_login(password: str = Form("")):
        security = _read_security()
        mode = security.get("mode", "none")
        if mode == "none":
            return RedirectResponse(url="/login?error=disabled", status_code=303)
        if not auth.verify_password(password, security.get("salt", ""), security.get("hash", "")):
            return RedirectResponse(url="/login?error=1", status_code=303)
        token = _create_session()
        redirect = RedirectResponse(url="/", status_code=303)
        redirect.set_cookie(
            SESSION_COOKIE_NAME, token, max_age=SESSION_TTL_S,
            httponly=True, samesite="lax",
        )
        return redirect

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token:
            sessions.pop(token, None)
        response.delete_cookie(SESSION_COOKIE_NAME)
        return {"ok": True}

    @app.get("/api/network/status")
    async def network_status_endpoint():
        return network_status

    @app.get("/api/network/scan")
    async def network_scan():
        try:
            return {"networks": await network.scan_wifi()}
        except Exception as e:
            logger.error("WiFi scan failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/network/wifi")
    async def network_save_wifi(request: Request):
        # Unauthenticated at first boot; requires login when reached later from the config page.
        _require_login_for_action(request)
        body = await request.json()
        ssid = (body.get("ssid") or "").strip()
        password = body.get("password") or ""
        if not ssid:
            raise HTTPException(status_code=400, detail="SSID is required")
        if password and len(password) < 8:
            raise HTTPException(status_code=400, detail="WiFi password must be at least 8 characters")
        # Saved for the next boot to pick up; written owner-only (0600) since the password is stored in plaintext.
        fd = os.open(WIFI_PENDING_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"ssid": ssid, "password": password}))
        return {"ok": True}

    @app.get("/api/hardware/audio-devices")
    async def audio_devices():
        return {"devices": await hardware.list_audio_devices()}

    @app.get("/api/radio/audio_level")
    async def radio_audio_level(device: str):
        """The radio setup page's live level meter: one ~0.3s capture, scored on Direwolf's own
        "audio level" convention, so the radio's volume can be tuned against background static
        before a signal shows up."""
        return await audio_level.read_level(device)

    @app.get("/api/hardware/serial-devices")
    async def serial_devices():
        return {"devices": await hardware.list_serial_devices()}

    @app.get("/api/hardware/cm108-devices")
    async def cm108_devices():
        return {"devices": await hardware.list_cm108_devices()}

    @app.get("/api/aprs/passcode")
    async def aprs_passcode(callsign: str = ""):
        callsign = callsign.strip()
        if not callsign:
            raise HTTPException(status_code=400, detail="Callsign is required")
        return {"passcode": aprs.calculate_passcode(callsign)}

    @app.get("/api/aprs/heard")
    async def aprs_heard():
        enabled = log_settings.is_enabled("heard_stations")
        # stations: None distinguishes "not tracking" (disabled, or packet logging isn't running at
        # all) from "nothing heard yet" (enabled, stations: []).
        stations = await packets.heard_stations() if (packets and enabled) else None
        return {"enabled": enabled, "stations": stations}

    @app.get("/api/aprs/beacon-stats")
    async def aprs_beacon_stats():
        enabled = log_settings.is_enabled("sent_packets")
        if not packets or not enabled:
            return {
                "enabled": enabled,
                "last_rf_beacon_seconds_ago": None, "last_igate_beacon_seconds_ago": None,
            }
        return {"enabled": True, **await packets.beacon_stats()}

    @app.post("/api/aprs/signal_test")
    async def aprs_signal_test_start(request: Request):
        _require_login_for_action(request)
        if not log_settings.is_enabled("signal_test_results"):
            raise HTTPException(
                status_code=400, detail="Signal test history is turned off (Settings > Database); enable it first",
            )
        body = await request.json()
        target = (body.get("callsign") or "").strip().upper()
        if not target:
            raise HTTPException(status_code=400, detail="Callsign is required")
        if len(target) > 9:
            raise HTTPException(status_code=400, detail="Callsign is too long")
        aprs_cfg = _read_config().get("aprs", {}) or {}
        # RF-reach test only: needs RF TX/RX, and only makes sense when there's no IGate uplink of our own.
        if aprs_cfg.get("digipeat_mode") != "digipeater":
            raise HTTPException(status_code=400, detail="Signal test needs digipeating set to RX & TX first")
        if aprs_cfg.get("igate_mode", "off") != "off":
            raise HTTPException(status_code=400, detail="Signal test is for RF-only setups; turn IGate off first")
        if packets is None:
            raise HTTPException(status_code=503, detail="Packet logging isn't running")
        my_callsign = (aprs_cfg.get("callsign") or "").strip().upper()
        if not my_callsign:
            raise HTTPException(status_code=400, detail="This digipeater has no callsign configured yet")
        ssid = aprs_cfg.get("ssid")
        my_call = f"{my_callsign}-{ssid}" if ssid else my_callsign
        path_str = (aprs_cfg.get("rf_beacon", {}) or {}).get("path") or "WIDE1-1"
        path = [p.strip().upper() for p in path_str.split(",") if p.strip()]
        test_id = secrets.token_hex(4)
        try:
            await packets.start_signal_test(test_id, my_call, target)
        except Exception as e:
            logger.error("Failed to start signal test: %s", e)
            raise HTTPException(status_code=500, detail="Could not record the signal test; nothing was sent")
        try:
            await signal_test.send_ping(my_call, target, path, test_id)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return {"ok": True, "test_id": test_id}

    @app.get("/api/aprs/signal_test/{test_id}")
    async def aprs_signal_test_status(test_id: str):
        if packets is None:
            raise HTTPException(status_code=503, detail="Packet logging isn't running")
        result = await packets.signal_test_status(test_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Unknown test id")
        return {"ok": True, **result}

    @app.get("/api/gps/status")
    async def gps_status():
        return await gps.get_status()

    @app.get("/api/gps/position")
    async def gps_position():
        return await gps.get_position()

    @app.get("/api/system/timezones")
    async def system_timezones():
        return {"timezones": await system.list_timezones()}

    @app.get("/api/system/direwolf/status")
    async def direwolf_status():
        # Read-only, ungated.
        return await system.get_direwolf_status()

    @app.get("/api/system/direwolf/logs")
    async def direwolf_logs():
        # Read-only, backs the dashboard's error-badge "view logs" modal.
        return {"logs": await system.get_direwolf_logs()}

    def _require_login_for_action(request: Request) -> None:
        # Changes require login under both "readonly" and "full" modes; "full" mode also gates viewing.
        if _read_security().get("mode", "none") != "none" and not _is_logged_in(request):
            raise HTTPException(status_code=401, detail="Login required")

    def _read_config() -> dict:
        if not CONFIG_PATH.exists():
            return {}
        try:
            return yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception as e:
            logger.error("Failed to read %s: %s", CONFIG_PATH, e)
            return {}

    @app.post("/api/system/direwolf/start")
    async def direwolf_start(request: Request):
        _require_login_for_action(request)
        result = await system.set_direwolf_running(True, _read_config())
        if not result["ok"]:
            raise HTTPException(status_code=500, detail=result["reason"])
        return {"ok": True}

    @app.post("/api/system/direwolf/stop")
    async def direwolf_stop(request: Request):
        _require_login_for_action(request)
        result = await system.set_direwolf_running(False, _read_config())
        if not result["ok"]:
            raise HTTPException(status_code=500, detail=result["reason"])
        return {"ok": True}

    @app.get("/api/radio/write/status")
    async def radio_write_status():
        # Read-only, ungated; polled by the progress bar while a write is in flight.
        return system.get_radio_write_status()

    @app.post("/api/radio/write")
    async def radio_write(request: Request):
        """Writes channel settings to the radio on demand: from the setup wizard (radio not yet powered) or the
        config page's "Write to radio" button (may need to stop a running Direwolf first)."""
        _require_login_for_action(request)
        body = await request.json()
        # Failures come back as a 200 with ok:false, so the frontend still learns was_running
        # and can offer to restart Direwolf if this stopped it.
        return await system.write_radio(body.get("radio") or {})

    @app.post("/api/radio/power_off")
    async def radio_power_off(request: Request):
        """Powers the radio off after write_radio() left it on and the user chose not to restart Direwolf."""
        _require_login_for_action(request)
        await system.power_off_radio()
        return {"ok": True}

    @app.post("/api/logging/clear/{log_type}")
    async def logging_clear(log_type: str, request: Request):
        """The Database tab's per-row Clear button: permanently deletes that log type's history."""
        _require_login_for_action(request)
        try:
            deleted = await db.clear_log_type(log_type)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Unknown log type: {log_type}")
        return {"ok": True, "deleted": deleted}

    @app.post("/api/logging/clear_all")
    async def logging_clear_all(request: Request):
        """The Database tab's Clear all button: permanently deletes every log type's history."""
        _require_login_for_action(request)
        deleted = await db.clear_all_logs()
        return {"ok": True, "deleted": deleted}

    @app.get("/api/history")
    async def api_history(request: Request, types: str = "", limit: int = 100, before: float | None = None):
        """The History page's table: merged, newest-first rows across the requested log types."""
        # Same gate as the /history page itself.
        if _read_security().get("mode", "none") != "none" and not _is_logged_in(request):
            raise HTTPException(status_code=401, detail="Login required")
        requested = [t.strip() for t in types.split(",") if t.strip()] or list(log_settings.LOG_TYPES.keys())
        unknown = [t for t in requested if t not in log_settings.LOG_TYPES]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown log type(s): {', '.join(unknown)}")
        limit = max(1, min(limit, 500))
        rows = await db.fetch_history(requested, limit, before)
        entries = [
            {
                "log_type": r["log_type"],
                "at": r["at"],
                "summary": _history_summary(r["log_type"], r),
                "detail": {k: v for k, v in r.items() if k != "log_type"},
            }
            for r in rows
        ]
        next_before = entries[-1]["at"] if len(entries) == limit else None
        return {"entries": entries, "next_before": next_before}

    @app.get("/api/stats")
    async def api_stats(request: Request):
        """The Stats page: summary counts plus a 30-day daily activity series."""
        if _read_security().get("mode", "none") != "none" and not _is_logged_in(request):
            raise HTTPException(status_code=401, detail="Login required")
        return await db.get_stats()

    @app.post("/api/system/reboot")
    async def system_reboot(request: Request):
        # Post-setup equivalent of /api/setup/complete's reboot: the config page's "Reboot now" button.
        _require_login_for_action(request)
        async def _delayed_reboot():
            if rotation is not None:
                await rotation.show_message("Rebooting", [("Status:", "Restarting now...")])
            await asyncio.sleep(1.5)
            await system.reboot()
        asyncio.create_task(_delayed_reboot())
        return {"ok": True}

    @app.get("/api/network/internet")
    async def internet_status():
        return {"online": await tiles.has_internet()}

    @app.get("/api/map/world-status")
    async def map_world_status():
        return {"available": tiles.WORLD_PMTILES_PATH.exists()}

    @app.get("/api/map/region-status")
    async def map_region_status():
        return {"available": tiles.REGION_PATH.exists()}

    # Serves cached map data with Range support for the PMTiles JS reader; 404 if not downloaded yet.
    @app.get("/map-data/world.pmtiles")
    async def serve_world_pmtiles():
        if not tiles.WORLD_PMTILES_PATH.exists():
            raise HTTPException(status_code=404, detail="World map not cached yet")
        return FileResponse(tiles.WORLD_PMTILES_PATH, media_type="application/octet-stream")

    @app.get("/map-data/region.pmtiles")
    async def serve_region_pmtiles():
        if not tiles.REGION_PATH.exists():
            raise HTTPException(status_code=404, detail="No region downloaded yet")
        return FileResponse(tiles.REGION_PATH, media_type="application/octet-stream")

    @app.get("/map-data/live.pmtiles")
    async def serve_live_pmtiles(request: Request):
        """Same-origin proxy for Protomaps' hosted planet build, streaming ranged tile requests through (no CORS upstream)."""
        try:
            source_url = await tiles.resolve_cached_source_url()
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))

        upstream_headers = {}
        range_header = request.headers.get("range")
        if range_header:
            upstream_headers["Range"] = range_header

        stream_ctx = live_tile_client.stream("GET", source_url, headers=upstream_headers)
        try:
            upstream = await stream_ctx.__aenter__()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Could not reach map source: {e}")

        async def body():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await stream_ctx.__aexit__(None, None, None)

        passthrough_headers = {
            h: upstream.headers[h]
            for h in ("content-range", "content-length", "accept-ranges", "etag")
            if h in upstream.headers
        }
        return StreamingResponse(
            body(),
            status_code=upstream.status_code,
            media_type="application/octet-stream",
            headers=passthrough_headers,
        )

    # No size/tile-count estimate endpoint: region extract size depends on actual map data density,
    # which varies per region and can only be known by running the extract.

    @app.post("/api/map/cache/start")
    async def map_cache_start(request: Request):
        _require_login_for_action(request)
        body = await request.json()
        try:
            north = float(body.get("north"))
            south = float(body.get("south"))
            east = float(body.get("east"))
            west = float(body.get("west"))
            zoom_max = int(body.get("zoom_max"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid region parameters")
        if zoom_max < 1 or zoom_max > 15 or north <= south or east <= west:
            raise HTTPException(status_code=400, detail="Invalid region")
        existing = map_download_state["downloader"]
        if existing and existing.status()["active"]:
            raise HTTPException(status_code=409, detail="A download is already in progress")
        bounds = {"north": north, "south": south, "east": east, "west": west}
        # Persisted immediately; gated on config.yaml already existing so this can't create it mid-wizard.
        if CONFIG_PATH.exists():
            config = _read_config()
            config["map"] = {**config.get("map", {}), **bounds, "zoom_max": zoom_max}
            CONFIG_PATH.write_text(
                "# Written by the config page. Manual edits here survive until the next save.\n"
                + yaml.safe_dump(config, sort_keys=False)
            )
        downloader = tiles.RegionDownloader(bounds, zoom_max)
        map_download_state["downloader"] = downloader
        asyncio.create_task(downloader.run())
        return {"ok": True}

    @app.get("/api/map/cache/status")
    async def map_cache_status():
        downloader = map_download_state["downloader"]
        if not downloader:
            return {"active": False, "done": False, "cancelled": False, "error": None, "bytes": 0, "elapsed_s": None}
        return downloader.status()

    @app.post("/api/map/cache/cancel")
    async def map_cache_cancel(request: Request):
        _require_login_for_action(request)
        downloader = map_download_state["downloader"]
        if downloader:
            downloader.cancel()
        return {"ok": True}

    @app.post("/api/setup/complete")
    async def setup_complete(request: Request):
        if not first_boot:
            raise HTTPException(status_code=400, detail="Setup has already been completed")
        body = await request.json()
        display_cfg = body.get("display", {})
        user_cfg = body.get("user", {})
        security_mode = user_cfg.get("mode", "none")
        # Only ever a hash + salt on disk, never the password itself.
        security = {"mode": security_mode}
        password = user_cfg.get("password", "")
        if security_mode != "none" and password:
            security.update(auth.hash_password(password))
        config = {
            "setup_complete": True,
            "radio": body.get("radio", {}),
            "aprs": body.get("aprs", {}),
            "gps": body.get("gps", {}),
            "map": body.get("map", {}),
            "startup": body.get("startup", {}),
            # Only the page-rotation list; driver/model live in display_config.json instead.
            "display": {"pages": display_cfg.get("pages", [])},
            "security": security,
        }
        DISPLAY_CONFIG_PATH.write_text(json.dumps({
            "driver": display_cfg.get("driver", "none"),
            "model": display_cfg.get("model", ""),
        }))
        CONFIG_PATH.write_text(
            "# Written by the first-boot setup wizard.\n"
            "# Its existence is what marks first-boot setup as complete.\n"
            + yaml.safe_dump(config, sort_keys=False)
        )
        # Reboot fires in the background with a short delay so the response reaches the client first.
        async def _delayed_reboot():
            # No RotationManager exists yet during first boot (it's only created on a normal boot),
            # so render directly via the already-running display_driver instead.
            try:
                from display.templates import get_template
                template = get_template(display_cfg.get("model", ""))
                image = await asyncio.to_thread(
                    template.draw_status_page, display_driver, "Rebooting", [("Status:", "Restarting now...")],
                )
                await asyncio.to_thread(display_driver.show, image)
            except Exception as e:
                logger.error("Failed to show reboot message on display: %s", e)
            await asyncio.sleep(1.5)
            await system.reboot()
        asyncio.create_task(_delayed_reboot())
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        return {"ok": True, "first_boot": first_boot}

    # Unauthenticated even under "full" mode: a callsign is public information.
    @app.get("/api/station-id")
    async def station_id():
        if not CONFIG_PATH.exists():
            return {"callsign": None, "ssid": None}
        try:
            config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception:
            return {"callsign": None, "ssid": None}
        aprs_cfg = config.get("aprs", {}) or {}
        return {"callsign": aprs_cfg.get("callsign") or None, "ssid": aprs_cfg.get("ssid") or None}

    @app.get("/api/config")
    async def get_config(request: Request):
        if not CONFIG_PATH.exists():
            raise HTTPException(status_code=404, detail="Setup has not been completed yet")
        # Mirrors root()'s gating: "full" mode requires login to view, beyond gating changes.
        if _read_security().get("mode") == "full" and not _is_logged_in(request):
            raise HTTPException(status_code=401, detail="Login required")
        try:
            config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception as e:
            logger.error("Failed to read %s: %s", CONFIG_PATH, e)
            raise HTTPException(status_code=500, detail="Failed to read config")
        # Never hand the password hash/salt back to the frontend.
        security = config.get("security", {})
        config["security"] = {"mode": security.get("mode", "none")}
        return config

    def _normalize_gpio(gpio_cfg: dict | None) -> dict:
        """Fills in default GPIO pin values so a missing section compares equal to explicit defaults."""
        gpio_cfg = gpio_cfg or {}
        return {
            "relay_pin": gpio_cfg.get("relay_pin", relay.DEFAULT_RELAY_PIN),
            "eink_rst": gpio_cfg.get("eink_rst", epdconfig.DEFAULT_RST_PIN),
            "eink_dc": gpio_cfg.get("eink_dc", epdconfig.DEFAULT_DC_PIN),
            "eink_cs": gpio_cfg.get("eink_cs", epdconfig.DEFAULT_CS_PIN),
            "eink_busy": gpio_cfg.get("eink_busy", epdconfig.DEFAULT_BUSY_PIN),
        }

    async def _log_config_change(section: str, before_val, after_val) -> None:
        if before_val == after_val or not log_settings.is_enabled("config_changes"):
            return
        try:
            await db.execute(
                "INSERT INTO config_changes (at, section, before_json, after_json) VALUES (?, ?, ?, ?)",
                (time.time(), section, json.dumps(before_val), json.dumps(after_val)),
            )
        except Exception as e:
            logger.error("Failed to log config change (%s) to database: %s", section, e)

    @app.post("/api/config/save")
    async def config_save(request: Request):
        """The config page's "Save all changes" button: applies changes live where possible and reports what still needs a reboot."""
        _require_login_for_action(request)
        if not CONFIG_PATH.exists():
            raise HTTPException(status_code=400, detail="Setup has not been completed yet")
        body = await request.json()
        config = _read_config()
        before = {k: config.get(k) for k in ("radio", "aprs", "gps", "startup", "gpio", "logging")}
        before_display_config = None
        if "display" in body and DISPLAY_CONFIG_PATH.exists():
            try:
                before_display_config = json.loads(DISPLAY_CONFIG_PATH.read_text())
            except Exception:
                before_display_config = None

        for key in ("radio", "aprs", "gps", "startup", "gpio", "logging"):
            if key in body:
                config[key] = body[key]

        before_pages = (config.get("display") or {}).get("pages", [])
        display_driver_changed = False
        if "display" in body:
            display_cfg = body["display"] or {}
            config["display"] = {
                "pages": display_cfg.get("pages", (config.get("display") or {}).get("pages", []))
            }
            # Driver/model take effect only after a reboot; only written if genuinely changed from disk.
            if "driver" in display_cfg or "model" in display_cfg:
                new_display_config = {
                    "driver": display_cfg.get("driver", "none"),
                    "model": display_cfg.get("model", ""),
                }
                # Missing file normalizes to the same default main.py falls back to.
                before_normalized = before_display_config or {"driver": "none", "model": ""}
                if new_display_config != before_normalized:
                    DISPLAY_CONFIG_PATH.write_text(json.dumps(new_display_config))
                    display_driver_changed = True

        if "user" in body:
            user_cfg = body["user"] or {}
            existing_security = config.get("security", {}) or {}
            security_mode = user_cfg.get("mode", existing_security.get("mode", "none"))
            security = {"mode": security_mode}
            password = user_cfg.get("password", "")
            if security_mode != "none":
                if password:
                    security.update(auth.hash_password(password))
                else:
                    # Blank password keeps the existing hash/salt, so the password only changes when a new one is entered.
                    security["hash"] = existing_security.get("hash", "")
                    security["salt"] = existing_security.get("salt", "")
            config["security"] = security

        CONFIG_PATH.write_text(
            "# Written by the config page. Manual edits here survive until the next save.\n"
            + yaml.safe_dump(config, sort_keys=False)
        )

        for key in ("radio", "aprs", "gps", "startup", "gpio", "logging"):
            await _log_config_change(key, before[key], config.get(key))
        if "display" in body:
            await _log_config_change("display_pages", before_pages, config.get("display", {}).get("pages", []))
            if display_driver_changed:
                await _log_config_change(
                    "display_driver", before_display_config or {"driver": "none", "model": ""}, new_display_config,
                )
        if "user" in body:
            # Mode only, never the password/hash/salt.
            await _log_config_change(
                "security", {"mode": existing_security.get("mode", "none")}, {"mode": security_mode},
            )

        applied: list[str] = []
        reboot_required: list[str] = []

        if config.get("gps") != before["gps"]:
            await gpsconfig.apply(config.get("gps", {}))
            applied.append("gps")

        if config.get("startup") != before["startup"]:
            await restart_policy.apply(config.get("startup", {}))
            applied.append("startup")

        if config.get("logging") != before["logging"]:
            log_settings.apply(config.get("logging", {}))
            applied.append("logging")

        radio_changed = config.get("radio") != before["radio"]
        aprs_changed = config.get("aprs") != before["aprs"]
        radio_write_pending = False
        if radio_changed or aprs_changed:
            try:
                direwolf_config.write(config)
            except OSError as e:
                logger.error("Failed to write direwolf.conf: %s", e)
            radio_needs_programming = radio_changed and radio_programmer.can_program(config.get("radio", {}).get("model"))
            if radio_needs_programming:
                # A radio change needs a physical write to the radio, which the config page prompts for
                # separately via the Write to radio button, keeping the write visible and user-initiated.
                radio_write_pending = True
            else:
                status = await system.get_direwolf_status()
                if status.get("running"):
                    # Direwolf only reads config at startup, so a running instance needs a stop/start to pick up changes.
                    await system.set_direwolf_running(False, config)
                    restart_result = await system.set_direwolf_running(True, config)
                    if not restart_result["ok"]:
                        logger.error(
                            "Failed to restart direwolf after config save: %s",
                            restart_result["reason"],
                        )
            # Reported separately since only one of the two may have actually changed.
            if radio_changed:
                applied.append("radio")
            if aprs_changed:
                applied.append("aprs")

        if rotation is not None and config.get("display", {}).get("pages") != before_pages:
            # Page-rotation list re-applies live; driver/model changes wait for the next display reboot.
            rotation.reload_pages(load_pages(config["display"]))
            applied.append("display_pages")

        if _normalize_gpio(config.get("gpio")) != _normalize_gpio(before["gpio"]):
            # Relay/e-ink pins are claimed once at process start, so changing them always needs a reboot.
            reboot_required.append("gpio")
        if display_driver_changed:
            reboot_required.append("display")

        return {
            "ok": True, "applied": applied, "reboot_required": reboot_required,
            "radio_write_pending": radio_write_pending,
        }

    @app.get("/api/display/status")
    async def display_status():
        return {
            "driver": type(display_driver).__name__,
            "width": display_driver.width,
            "height": display_driver.height,
        }

    @app.get("/api/display/models")
    async def display_models():
        from display.waveshare import MODELS
        return {"models": [{"id": name, "desc": info["desc"]} for name, info in MODELS.items()]}

    @app.get("/api/display/config")
    async def display_config():
        if not DISPLAY_CONFIG_PATH.exists():
            return {"driver": "none", "model": ""}
        try:
            data = json.loads(DISPLAY_CONFIG_PATH.read_text())
        except Exception as e:
            logger.error("Failed to read %s: %s", DISPLAY_CONFIG_PATH, e)
            return {"driver": "none", "model": ""}
        return {"driver": data.get("driver", "none"), "model": data.get("model", "")}

    # Display calls run in a worker thread so a hardware hang doesn't freeze the whole server.

    @app.post("/api/display/clear")
    async def display_clear(request: Request):
        _require_login_for_action(request)
        try:
            await asyncio.to_thread(display_driver.clear)
        except Exception as e:
            logger.error("Display clear failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    @app.post("/api/display/test")
    async def display_test(request: Request):
        _require_login_for_action(request)
        try:
            from PIL import Image, ImageDraw  # noqa: F401 (import check before threading)
        except ImportError:
            raise HTTPException(status_code=500, detail="Pillow not installed")
        try:
            image = await asyncio.to_thread(_build_test_image, display_driver)
            await asyncio.to_thread(display_driver.show, image)
        except Exception as e:
            logger.error("Display test render failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    @app.post("/api/display/sleep")
    async def display_sleep(request: Request):
        _require_login_for_action(request)
        try:
            await asyncio.to_thread(display_driver.sleep)
        except Exception as e:
            logger.error("Display sleep failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    return app
