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
from services import aprs, auth, direwolf_config, gps, gpsconfig, hardware, network, relay, restart_policy, system, tiles

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
# Session cookie for the web UI's security mode (none/readonly/full; see
# services/auth.py). Sessions live
# in memory only (see `sessions` below); a restart forces re-login, which
# is an acceptable trade-off for a single-admin embedded device that
# doesn't restart often, and avoids needing any persistent token storage.
# Not marked Secure: this device is typically reached over plain HTTP on a
# LAN or its own setup hotspot, no TLS anywhere in this project.
SESSION_COOKIE_NAME = "digi_session"
SESSION_TTL_S = 7 * 24 * 3600
# Saved but not connected to yet; actually applying this is part of the
# "normal boot" network flow, which is separate/later work. First boot only
# ever stores the intent here.
WIFI_PENDING_PATH = Path("wifi_pending.json")
# Its mere existence is what main.py's first_boot check looks for: see
# CONFIG_PATH there. Written only by the wizard's final "Finish & Reboot"
# step, once all setup steps have been completed.
CONFIG_PATH = Path("config.yaml")
# Written by install.sh's display-selection prompt, read by main.py on
# every boot (see main.py: _load_display_config). The E-Ink display wizard
# step reads this to preset its dropdown, and can overwrite it; unlike
# most of the wizard, this one takes effect for real, since Finish always
# reboots right after.
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


def create_app(
    display_driver: DisplayDriver, first_boot: bool, network_status: dict, rotation=None, packets=None,
) -> FastAPI:
    app = FastAPI(title="APRS Digipeater")

    # Static assets referenced by URL from within the served HTML (e.g. the
    # APRS symbol sprite sheets), separate from the explicit FileResponse
    # routes below, which serve the HTML pages themselves at clean paths.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Holds the in-progress region download, if any: one at a time. A
    # plain closure-local dict rather than a module global, since this is
    # runtime state scoped to this app instance, not app configuration.
    map_download_state = {"downloader": None}

    # token -> expiry (unix time). Closure-local for the same reason as
    # map_download_state above: one process's worth of runtime state.
    sessions: dict[str, float] = {}

    # Reused across every /map-data/live.pmtiles request so TCP/TLS
    # connections to build.protomaps.com stay alive between range requests
    # instead of paying a fresh handshake per request: a single viewport can
    # trigger dozens of small range requests (directory lookups plus tile
    # data), and that handshake cost, doubled by this proxy's browser-to-Pi
    # then Pi-to-upstream hop, was the actual source of the slowdown, not
    # the data volume (cached region/world files skip all of this, served
    # straight off local disk).
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
        # "Full" security means viewing needs a password too, not just
        # changes: everything else (none/readonly) leaves the dashboard
        # itself open.
        if _read_security().get("mode") == "full" and not _is_logged_in(request):
            return FileResponse(STATIC_DIR / "login.html")
        return FileResponse(STATIC_DIR / "normal.html")

    @app.get("/login")
    async def login_page():
        # No security config exists yet during first boot (there's nothing
        # to log into), and the wizard is the only page that should be
        # reachable at all then: see root()'s own first_boot check above.
        if first_boot:
            return RedirectResponse(url="/")
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/config")
    async def config_page(request: Request):
        if first_boot:
            return RedirectResponse(url="/")
        # Config changes need a password under both readonly and full,
        # unlike root() above, which only gates full.
        mode = _read_security().get("mode", "none")
        if mode != "none" and not _is_logged_in(request):
            return FileResponse(STATIC_DIR / "login.html")
        return FileResponse(STATIC_DIR / "config.html")

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        return {"mode": _read_security().get("mode", "none"), "logged_in": _is_logged_in(request)}

    # A native <form> POST, not a fetch()-then-redirect: verified live
    # (real Chromium, not just reasoning about it) that a cookie set by a
    # fetch() response is reliably visible to a same-tab *fetch* made
    # right after, but NOT to a subsequent top-level navigation
    # (location.href, or even a fresh page load moments later): the
    # cookie sat in the browser's own jar the whole time, just never got
    # attached to the navigation request, bouncing straight back to the
    # login page despite the password having been accepted. A real
    # browser's native form submission goes through its own
    # navigation-with-body machinery, where the redirect this returns and
    # the Set-Cookie on it are part of the same round trip: this is the
    # standard, battle-tested pattern for exactly this reason, not a
    # workaround. 303 (not a plain redirect default) so the browser
    # reissues the follow-up as GET rather than replaying the POST.
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
        # Unauthenticated at first boot (no login system is even active
        # yet at that point), but this same endpoint is also reachable
        # from the post-setup config page's Network tab now, where a
        # readonly/full session should be required same as any other
        # change: see _require_login_for_action below. A no-op check
        # during first boot itself, since _read_security() reports mode
        # "none" before config.yaml exists.
        _require_login_for_action(request)
        body = await request.json()
        ssid = (body.get("ssid") or "").strip()
        password = body.get("password") or ""
        if not ssid:
            raise HTTPException(status_code=400, detail="SSID is required")
        if password and len(password) < 8:
            raise HTTPException(status_code=400, detail="WiFi password must be at least 8 characters")
        # Saved only: not connected now. Applying this is part of the normal
        # boot network flow, so the hotspot this request likely arrived over
        # isn't interrupted mid-setup.
        #
        # Written owner-only (0600) from the moment it's created: the
        # password has to be stored in plaintext (nmcli needs it verbatim to
        # actually connect later, unlike a login credential that could be
        # hashed), so the file permission is the only protection it gets.
        # os.open with an explicit mode avoids the brief window a
        # write-then-chmod would leave the file world-readable in.
        fd = os.open(WIFI_PENDING_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"ssid": ssid, "password": password}))
        return {"ok": True}

    @app.get("/api/hardware/audio-devices")
    async def audio_devices():
        return {"devices": await hardware.list_audio_devices()}

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
        # None (not empty-and-hidden) when there's no live tracking at all
        # (first boot, or packets=None in some other code path), so the
        # frontend can tell "nothing heard yet" apart from "not tracking".
        return {"stations": packets.heard_stations() if packets else None}

    @app.get("/api/aprs/beacon-stats")
    async def aprs_beacon_stats():
        return packets.beacon_stats() if packets else {
            "last_rf_beacon_seconds_ago": None, "last_igate_beacon_seconds_ago": None,
        }

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
        # Read-only, not gated: same as everything else "viewing is open"
        # covers, and under "full" mode the dashboard itself already
        # required login before this could ever be called anyway.
        return await system.get_direwolf_status()

    @app.get("/api/system/direwolf/logs")
    async def direwolf_logs():
        # Read-only, same gating (none) as direwolf_status above: backs
        # the dashboard's error-badge "view logs" modal.
        return {"logs": await system.get_direwolf_logs()}

    def _require_login_for_action(request: Request) -> None:
        # Starting/stopping Direwolf is a change, so both "readonly" and
        # "full" gate it (unlike viewing, where only "full" does): same
        # split /api/config/save below uses for the same reason.
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

    @app.post("/api/system/reboot")
    async def system_reboot(request: Request):
        # The one other place system.reboot() gets called is
        # /api/setup/complete's own background task, first-boot only. This
        # is the post-setup equivalent: the config page's "Reboot now"
        # button, for GPIO/display/network changes that need one to apply
        # (see /api/config/save's reboot_required list).
        _require_login_for_action(request)
        async def _delayed_reboot():
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

    # Range-request serving (needed by the PMTiles JS reader, which reads
    # chunks of the archive on demand rather than the whole file at once;
    # Starlette's FileResponse has supported Range since 0.39, see
    # requirements.txt) for whichever local map data exists. 404 rather
    # than a partial/placeholder response if a file isn't there yet: the
    # frontend checks availability via world-status/cache-status first and
    # shouldn't be requesting a path that can't exist.
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
        """Same-origin proxy for Protomaps' hosted planet build, letting the
        dashboard map stream live tiles for areas outside the local cache
        (see services/tiles.py's module docstring for why this proxy has to
        exist at all: build.protomaps.com itself has no CORS headers, so
        the browser can't range-request it directly). Forwards the
        browser's Range header upstream and passes the response straight
        back through, unbuffered, rather than downloading a whole (~100+ GB)
        planet archive to the Pi first."""
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

    # No size/tile-count estimate endpoint: unlike the old per-tile raster
    # approach, a PMTiles region extract's size depends on how much actual
    # map data exists in the area (a dense city vs. open countryside at the
    # same bbox/zoom can differ by an order of magnitude), not a clean
    # geometric formula. Better to say so honestly than show a fake-precise
    # number.

    @app.post("/api/map/cache/start")
    async def map_cache_start(request: Request):
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
        # Persisted immediately here, not deferred to a later "save"
        # step: matches how this endpoint already behaves during the
        # wizard (the download itself starts immediately too), and the
        # config page's Map tab doesn't have a "Next"/Finish to defer to.
        # Gated on config.yaml already existing so this can't accidentally
        # create it during first-boot setup, before Finish: config.yaml's
        # mere existence is what main.py's first_boot check looks for
        # (see CONFIG_PATH there), so creating it early here would corrupt
        # that check and skip the rest of the wizard on next restart.
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
    async def map_cache_cancel():
        downloader = map_download_state["downloader"]
        if downloader:
            downloader.cancel()
        return {"ok": True}

    @app.post("/api/setup/complete")
    async def setup_complete(request: Request):
        if not first_boot:
            raise HTTPException(status_code=400, detail="Setup has already been completed")
        body = await request.json()
        # Radio/APRS config (and GPS's beacon-position piece) have no
        # dedicated backend yet: nothing generates direwolf.conf from this
        # in DEV_BUILD. It's saved here as-is so it's not lost, ready for
        # whatever actually consumes it once that lands. GPS's device/time-
        # sync/timezone settings are applied for real on the next boot (see
        # services/gpsconfig.py); map tiles are already downloaded live
        # during the wizard itself, not deferred.
        display_cfg = body.get("display", {})
        user_cfg = body.get("user", {})
        security_mode = user_cfg.get("mode", "none")
        # Only ever a hash + salt on disk, never the password itself: see
        # services/auth.py. Enforced by root()/get_config()/config_page()
        # and Direwolf start/stop above once this is written; nothing
        # retroactively re-checks pages/endpoints added before this
        # config existed, since first_boot gates them out entirely anyway.
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
            # Only the page-rotation list: driver/model live in
            # display_config.json instead (see below), not duplicated here.
            "display": {"pages": display_cfg.get("pages", [])},
            "security": security,
        }
        # Unlike everything else in config.yaml, this one takes effect for
        # real: main.py reads display_config.json fresh on every boot, and
        # Finish always reboots right after this request completes.
        DISPLAY_CONFIG_PATH.write_text(json.dumps({
            "driver": display_cfg.get("driver", "none"),
            "model": display_cfg.get("model", ""),
        }))
        CONFIG_PATH.write_text(
            "# Written by the first-boot setup wizard.\n"
            "# Its existence is what marks first-boot setup as complete.\n"
            + yaml.safe_dump(config, sort_keys=False)
        )
        # Reboot is fired off in the background rather than awaited here:
        # awaiting it would mean the process (and the connection carrying
        # this response) gets killed by the reboot itself before the client
        # ever sees a reply. The short delay gives the response time to
        # actually reach the browser first.
        async def _delayed_reboot():
            await asyncio.sleep(1.5)
            await system.reboot()
        asyncio.create_task(_delayed_reboot())
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        return {"ok": True, "first_boot": first_boot}

    # Deliberately unauthenticated even under "full" security mode: a
    # callsign is public information by regulation, not a secret, so the
    # login page can show it in its title without needing a session first.
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
        # Only meaningful once setup's actually run: the dashboard that
        # calls this only renders post-setup anyway (see root() above), but
        # guard it directly rather than relying on that.
        if not CONFIG_PATH.exists():
            raise HTTPException(status_code=404, detail="Setup has not been completed yet")
        # Mirrors root()'s gating: "full" mode means viewing needs a
        # password too, not just changes. Defense in depth: root() already
        # keeps normal.html's JS from ever calling this unauthenticated,
        # but this endpoint shouldn't rely on that alone.
        if _read_security().get("mode") == "full" and not _is_logged_in(request):
            raise HTTPException(status_code=401, detail="Login required")
        try:
            config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception as e:
            logger.error("Failed to read %s: %s", CONFIG_PATH, e)
            raise HTTPException(status_code=500, detail="Failed to read config")
        # Never hand the password hash/salt back to the frontend: nothing
        # legitimate needs them client-side (login posts a plaintext
        # password for the server to check, see auth.verify_password),
        # only a reason to leak crackable material for no benefit.
        security = config.get("security", {})
        config["security"] = {"mode": security.get("mode", "none")}
        return config

    def _normalize_gpio(gpio_cfg: dict | None) -> dict:
        """Fills in the same fixed defaults services/relay.py and
        display/waveshare/epdconfig.py themselves fall back to when a key
        is absent, so "the section was never written" and "the section
        was written with exactly the default values" compare as equal.
        Without this, the very first save through this page (any
        config.yaml the wizard produced has no gpio section at all, since
        first_run.html has no GPIO tab) would always report a reboot as
        needed even though the effective pin values, and therefore actual
        post-reboot behavior, haven't changed at all.
        """
        gpio_cfg = gpio_cfg or {}
        return {
            "relay_pin": gpio_cfg.get("relay_pin", relay.DEFAULT_RELAY_PIN),
            "eink_rst": gpio_cfg.get("eink_rst", epdconfig.DEFAULT_RST_PIN),
            "eink_dc": gpio_cfg.get("eink_dc", epdconfig.DEFAULT_DC_PIN),
            "eink_cs": gpio_cfg.get("eink_cs", epdconfig.DEFAULT_CS_PIN),
            "eink_busy": gpio_cfg.get("eink_busy", epdconfig.DEFAULT_BUSY_PIN),
        }

    @app.post("/api/config/save")
    async def config_save(request: Request):
        """The config page's global "Save all changes" button: unlike
        /api/setup/complete (first-boot only, whole-config, always reboots),
        this applies live wherever the codebase actually allows it and
        reports back what did vs. what still needs a reboot, rather than
        rebooting unconditionally.

        Body: any subset of {radio, aprs, gps, startup, gpio, display,
        user}. map and network are intentionally not accepted here: map
        saves itself as part of its own live download action
        (/api/map/cache/start), and network changes go through
        /api/network/wifi's own reboot-required flow, both to avoid this
        endpoint silently doing something as disruptive as reconnecting
        the network out from under the session making the request.
        """
        _require_login_for_action(request)
        if not CONFIG_PATH.exists():
            raise HTTPException(status_code=400, detail="Setup has not been completed yet")
        body = await request.json()
        config = _read_config()
        before = {k: config.get(k) for k in ("radio", "aprs", "gps", "startup", "gpio")}
        before_display_config = None
        if "display" in body and DISPLAY_CONFIG_PATH.exists():
            try:
                before_display_config = json.loads(DISPLAY_CONFIG_PATH.read_text())
            except Exception:
                before_display_config = None

        for key in ("radio", "aprs", "gps", "startup", "gpio"):
            if key in body:
                config[key] = body[key]

        before_pages = (config.get("display") or {}).get("pages", [])
        display_driver_changed = False
        if "display" in body:
            display_cfg = body["display"] or {}
            config["display"] = {
                "pages": display_cfg.get("pages", (config.get("display") or {}).get("pages", []))
            }
            # Unlike everything else here, driver/model take effect for
            # real only after a reboot (see main.py: display_driver.init()
            # runs once, early in main(), same as /api/setup/complete's
            # own note about this file). Only actually written, and only
            # counted as a reboot-required change below, if it's
            # genuinely different from what's already on disk: the
            # frontend always includes the full hydrated display section
            # in every save (not just what was actually edited), so
            # presence in the payload alone isn't a real signal of change.
            if "driver" in display_cfg or "model" in display_cfg:
                new_display_config = {
                    "driver": display_cfg.get("driver", "none"),
                    "model": display_cfg.get("model", ""),
                }
                # Same "missing == explicit default" normalization as
                # _normalize_gpio below: a brand new install with no
                # display_config.json yet (main.py's own _load_display_
                # config() falls back to exactly "none"/"") shouldn't
                # report a reboot as needed just because this file didn't
                # exist before, if what's being written matches that same
                # fallback anyway.
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
                    # No new password given: keep the existing hash/salt
                    # rather than requiring a fresh one on every save, the
                    # way the wizard's own always-mandatory password field
                    # does (fine for a one-time setup step, hostile in an
                    # edit context). GET /api/config never hands the hash
                    # back to the frontend, so "leave it blank" is the only
                    # sane contract for "keep the current password".
                    security["hash"] = existing_security.get("hash", "")
                    security["salt"] = existing_security.get("salt", "")
            config["security"] = security

        CONFIG_PATH.write_text(
            "# Written by the config page. Manual edits here survive until the next save.\n"
            + yaml.safe_dump(config, sort_keys=False)
        )

        applied: list[str] = []
        reboot_required: list[str] = []

        if config.get("gps") != before["gps"]:
            await gpsconfig.apply(config.get("gps", {}))
            applied.append("gps")

        if config.get("startup") != before["startup"]:
            await restart_policy.apply(config.get("startup", {}))
            applied.append("startup")

        radio_changed = config.get("radio") != before["radio"]
        aprs_changed = config.get("aprs") != before["aprs"]
        if radio_changed or aprs_changed:
            try:
                direwolf_config.write(config)
            except OSError as e:
                logger.error("Failed to write direwolf.conf: %s", e)
            status = await system.get_direwolf_status()
            if status.get("running"):
                # Direwolf only reads its config at its own startup, so a
                # running instance needs a stop/start cycle to actually
                # pick up the new radio/APRS settings: a brief on-air
                # interruption, which is why this only happens when
                # something that actually feeds direwolf.conf changed.
                await system.set_direwolf_running(False, config)
                restart_result = await system.set_direwolf_running(True, config)
                if not restart_result["ok"]:
                    logger.error(
                        "Failed to restart direwolf after config save: %s",
                        restart_result["reason"],
                    )
            # Reported separately, not as one combined "radio/aprs" entry:
            # only one of the two may have actually changed, and the
            # frontend shows this list verbatim in its summary banner.
            if radio_changed:
                applied.append("radio")
            if aprs_changed:
                applied.append("aprs")

        if rotation is not None and config.get("display", {}).get("pages") != before_pages:
            # Unlike driver/model (see display_driver_changed below), the
            # page-rotation list has a live re-apply path: it's just data
            # RotationManager reads, not a GPIO pin claimed once at process
            # start, so no reboot is needed for an edited page list to
            # actually take effect.
            rotation.reload_pages(load_pages(config["display"]))
            applied.append("display_pages")

        if _normalize_gpio(config.get("gpio")) != _normalize_gpio(before["gpio"]):
            # Relay/e-ink pins are claimed once at process start (see
            # services/relay.py's init() and display/waveshare/
            # epdconfig.py's configure(), both called from main.py before
            # config.yaml is even fully read the normal-boot way): no live
            # re-claim path exists, so this always needs a reboot, unlike
            # the PTT pin (which lives under radio, not gpio, and is
            # already covered by the radio/aprs branch above).
            reboot_required.append("gpio")
        if display_driver_changed:
            reboot_required.append("display")

        return {"ok": True, "applied": applied, "reboot_required": reboot_required}

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

    # Display calls run in a worker thread, not on the event loop: a hardware
    # hang (e.g. a stuck BUSY pin) would otherwise freeze every other request
    # the server is handling, not just the display endpoint.

    @app.post("/api/display/clear")
    async def display_clear():
        try:
            await asyncio.to_thread(display_driver.clear)
        except Exception as e:
            logger.error("Display clear failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    @app.post("/api/display/test")
    async def display_test():
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
    async def display_sleep():
        try:
            await asyncio.to_thread(display_driver.sleep)
        except Exception as e:
            logger.error("Display sleep failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    return app
