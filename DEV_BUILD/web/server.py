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
from services import aprs, gps, hardware, network, system

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

    @app.post("/api/setup/complete")
    async def setup_complete(request: Request):
        if not first_boot:
            raise HTTPException(status_code=400, detail="Setup has already been completed")
        body = await request.json()
        # Radio/APRS/GPS config have no dedicated backend yet (nothing
        # generates direwolf.conf or a gpsd device config from this in
        # DEV_BUILD) — saved here as-is so it's not lost, ready for
        # whatever actually consumes it once that lands.
        config = {
            "setup_complete": True,
            "radio": body.get("radio", {}),
            "aprs": body.get("aprs", {}),
            "gps": body.get("gps", {}),
        }
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
