import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from display.base import DisplayDriver
from services import aprs, auth, gps, hardware, network, system, tiles

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
# Saved but not connected to yet — actually applying this is part of the
# "normal boot" network flow, which is separate/later work. First boot only
# ever stores the intent here.
WIFI_PENDING_PATH = Path("wifi_pending.json")
# Its mere existence is what main.py's first_boot check looks for — see
# CONFIG_PATH there. Written only by the wizard's final "Finish & Reboot"
# step, once all setup steps have been completed.
CONFIG_PATH = Path("config.yaml")
# Written by install.sh's display-selection prompt, read by main.py on
# every boot (see main.py: _load_display_config). The E-Ink display wizard
# step reads this to preset its dropdown, and can overwrite it — unlike
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


def create_app(display_driver: DisplayDriver, first_boot: bool, network_status: dict) -> FastAPI:
    app = FastAPI(title="APRS Digipeater")

    # Static assets referenced by URL from within the served HTML (e.g. the
    # APRS symbol sprite sheets) — separate from the explicit FileResponse
    # routes below, which serve the HTML pages themselves at clean paths.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Holds the in-progress region download, if any — one at a time. A
    # plain closure-local dict rather than a module global, since this is
    # runtime state scoped to this app instance, not app configuration.
    map_download_state = {"downloader": None}

    @app.get("/")
    async def root():
        page = "first_run.html" if first_boot else "normal.html"
        return FileResponse(STATIC_DIR / page)

    @app.get("/test")
    async def test_page():
        return FileResponse(STATIC_DIR / "test.html")

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
        body = await request.json()
        ssid = (body.get("ssid") or "").strip()
        password = body.get("password") or ""
        if not ssid:
            raise HTTPException(status_code=400, detail="SSID is required")
        if password and len(password) < 8:
            raise HTTPException(status_code=400, detail="WiFi password must be at least 8 characters")
        # Saved only — not connected now. Applying this is part of the normal
        # boot network flow, so the hotspot this request likely arrived over
        # isn't interrupted mid-setup.
        #
        # Written owner-only (0600) from the moment it's created — the
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

    @app.get("/api/gps/status")
    async def gps_status():
        return await gps.get_status()

    @app.get("/api/gps/position")
    async def gps_position():
        return await gps.get_position()

    @app.get("/api/system/timezones")
    async def system_timezones():
        return {"timezones": await system.list_timezones()}

    @app.get("/api/network/internet")
    async def internet_status():
        return {"online": await tiles.has_internet()}

    @app.get("/api/map/world-status")
    async def map_world_status():
        return {"available": tiles.WORLD_PMTILES_PATH.exists()}

    # Range-request serving (needed by the PMTiles JS reader, which reads
    # chunks of the archive on demand rather than the whole file at once —
    # Starlette's FileResponse has supported Range since 0.39, see
    # requirements.txt) for whichever local map data exists. 404 rather
    # than a partial/placeholder response if a file isn't there yet — the
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

    # No size/tile-count estimate endpoint — unlike the old per-tile raster
    # approach, a PMTiles region extract's size depends on how much actual
    # map data exists in the area (a dense city vs. open countryside at the
    # same bbox/zoom can differ by an order of magnitude), not a clean
    # geometric formula. Better to say so honestly than show a fake-precise
    # number — see TODO.md.

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
        # dedicated backend yet — nothing generates direwolf.conf from this
        # in DEV_BUILD — saved here as-is so it's not lost, ready for
        # whatever actually consumes it once that lands. GPS's device/time-
        # sync/timezone settings are applied for real on the next boot (see
        # services/gpsconfig.py); map tiles are already downloaded live
        # during the wizard itself, not deferred.
        display_cfg = body.get("display", {})
        user_cfg = body.get("user", {})
        security_mode = user_cfg.get("mode", "none")
        # Only ever a hash + salt on disk, never the password itself — see
        # services/auth.py. Not enforced anywhere yet (no login system
        # exists in DEV_BUILD — see TODO.md), but there's no reason to
        # store it insecurely just because nothing checks it yet.
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
            # Only the page-rotation list — driver/model live in
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
        # Reboot is fired off in the background rather than awaited here —
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

    # Display calls run in a worker thread, not on the event loop — a hardware
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
            from PIL import Image, ImageDraw  # noqa: F401 — import check before threading
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
