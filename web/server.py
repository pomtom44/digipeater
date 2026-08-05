"""FastAPI web server — REST endpoints, WebSocket streams, static files, auth."""

import asyncio
import logging
import os
import subprocess
import yaml
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
CONFIG_PATH = Path("config.yaml")
TILE_DIR = Path("/var/digipeater/tiles")

# Simple in-memory token store {token: True}
_valid_tokens: set[str] = set()


def create_app(state) -> FastAPI:
    app = FastAPI(title="APRS Digipeater", docs_url=None, redoc_url=None)

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    # ── Auth helpers ──────────────────────────────────────────

    def _security_mode() -> str:
        return state.config.get("web", {}).get("security", {}).get("mode", "none")

    def _correct_password(pw: str) -> bool:
        configured = state.config.get("web", {}).get("security", {}).get("password", "")
        return pw == configured

    def _check_token(request: Request) -> bool:
        if _security_mode() == "none":
            return True
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:] in _valid_tokens
        return False

    def require_auth(request: Request):
        if not _check_token(request):
            raise HTTPException(status_code=401, detail="Unauthorised")

    def require_auth_if_readonly(request: Request):
        mode = _security_mode()
        if mode in ("readonly", "full") and not _check_token(request):
            raise HTTPException(status_code=401, detail="Unauthorised")

    def require_auth_if_config(request: Request):
        mode = _security_mode()
        if mode in ("config", "full") and not _check_token(request):
            raise HTTPException(status_code=401, detail="Unauthorised")

    # ── Auth endpoints ────────────────────────────────────────

    @app.post("/api/auth/login")
    async def login(request: Request):
        body = await request.json()
        pw = body.get("password", "")
        if not _correct_password(pw):
            raise HTTPException(status_code=401, detail="Wrong password")
        import secrets
        token = secrets.token_hex(32)
        _valid_tokens.add(token)
        return {"token": token}

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            _valid_tokens.discard(auth[7:])
        return {"ok": True}

    # ── Status ────────────────────────────────────────────────

    @app.get("/api/status")
    async def get_status():
        dw = state.direwolf
        gps = state.gps
        fix = state.gps_fix

        return {
            "direwolf": {
                "state": dw.state.value if dw else "stopped",
                "uptime": dw.uptime if dw else "—",
                "version": state.direwolf_version,
                "audio_device": state.direwolf_audio_device,
            },
            "relay_on": state.relay.powered if state.relay else False,
            "gps": {
                "state": gps.state if gps else "no_device",
                "fix": {
                    "latitude": fix.latitude,
                    "longitude": fix.longitude,
                    "hdop": fix.hdop,
                    "satellites": fix.satellites,
                } if fix else None,
            },
            "stats": state.stats,
            "last_beacon_time": state.last_beacon_time,
            "last_heard_call": state.last_heard_call,
            "last_heard_time": state.last_heard_time,
            "setup_complete": CONFIG_PATH.exists(),
            "security_mode": state.config.get("web", {}).get("security", {}).get("mode", "none"),
            "aprs_is": {
                "connected": state.aprs_is_connected,
                "server": state.aprs_is_server,
            },
            "radio": {
                "enabled": state.radio.enabled if state.radio else False,
                "frequency": state.radio_frequency,
            },
            "radio_programmer": state.radio_programmer.status() if state.radio_programmer else None,
        }

    # ── Radio CAT control ─────────────────────────────────────

    @app.post("/api/radio/frequency")
    async def set_radio_frequency(request: Request, _=Depends(require_auth_if_config)):
        if not state.radio or not state.radio.enabled:
            raise HTTPException(status_code=503, detail="Radio CAT control not enabled")
        body = await request.json()
        freq = body.get("frequency")
        if not freq:
            raise HTTPException(status_code=400, detail="frequency required")
        ok = await state.radio.set_frequency(float(freq))
        if ok:
            state.radio_frequency = float(freq)
        return {"ok": ok}

    # ── Radio memory programmer ───────────────────────────────

    @app.get("/api/radio/programmer/status")
    async def programmer_status():
        if not state.radio_programmer:
            return {"state": "unavailable", "error": None, "port": None}
        return state.radio_programmer.status()

    @app.post("/api/radio/programmer/run")
    async def programmer_run(request: Request, _=Depends(require_auth_if_config)):
        if not state.radio_programmer:
            raise HTTPException(status_code=503, detail="Radio programmer not initialised")
        body = await request.json()
        from hardware.radio_programmer import ChannelSettings, APRS_PRESETS
        freq_hz = int(body.get("frequency_hz", APRS_PRESETS["NZ"]))
        mode = body.get("mode", "FM_WIDE")
        ctcss_hz = float(body.get("ctcss_hz", 0.0))
        power = body.get("power", "HIGH")
        mhz = freq_hz / 1_000_000
        name = body.get("name") or f"{mhz:.3f}"[:6]
        settings = ChannelSettings(
            frequency_hz=freq_hz,
            mode=mode,
            ctcss_hz=ctcss_hz,
            power=power,
            name=name,
        )
        started = await state.radio_programmer.program(settings)
        if not started:
            raise HTTPException(status_code=409, detail="Programming already in progress")
        return {"ok": True}

    # ── Direwolf control ──────────────────────────────────────

    @app.post("/api/direwolf/start")
    async def direwolf_start(request: Request, _=Depends(require_auth_if_readonly)):
        if not state.direwolf:
            raise HTTPException(status_code=503, detail="Direwolf manager not initialised")
        asyncio.create_task(_do_start(state))
        return {"ok": True}

    @app.post("/api/direwolf/stop")
    async def direwolf_stop(request: Request, _=Depends(require_auth_if_readonly)):
        if state.direwolf:
            await state.direwolf.stop()
        if state.relay:
            state.relay.power_off()
        return {"ok": True}

    # ── Relay ─────────────────────────────────────────────────

    @app.post("/api/relay/on")
    async def relay_on(_=Depends(require_auth_if_readonly)):
        if state.relay:
            asyncio.create_task(state.relay.power_on())
        return {"ok": True}

    @app.post("/api/relay/off")
    async def relay_off(_=Depends(require_auth_if_readonly)):
        if state.relay:
            state.relay.power_off()
        return {"ok": True}

    # ── Packets / map data ────────────────────────────────────

    @app.get("/api/packets")
    async def get_packets(callsign: str = None, limit: int = 1000):
        if not state.packet_store:
            return []
        if callsign:
            return state.packet_store.get_by_callsign(callsign, limit)
        return state.packet_store.get_all(limit)

    @app.get("/api/packets/latest")
    async def get_latest_packets():
        """Latest position per callsign — used to populate map on page load."""
        if not state.packet_store:
            return []
        return state.packet_store.get_latest_position_per_callsign()

    @app.get("/api/callsigns")
    async def get_callsigns():
        if not state.packet_store:
            return []
        return state.packet_store.get_callsigns()

    @app.delete("/api/packets")
    async def reset_packets(_=Depends(require_auth_if_config)):
        if state.packet_store:
            state.packet_store.reset()
        return {"ok": True}

    # ── Config ────────────────────────────────────────────────

    @app.get("/api/config")
    async def get_config(_=Depends(require_auth_if_config)):
        if not CONFIG_PATH.exists():
            return {}
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)

    @app.post("/api/config")
    async def save_config(request: Request, _=Depends(require_auth_if_config)):
        if state.direwolf and state.direwolf.state.value == "running":
            raise HTTPException(status_code=409, detail="Stop Direwolf before saving config")
        body = await request.json()
        from core import config_gen
        errors = config_gen.validate(body)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(body, f, default_flow_style=False, allow_unicode=True)
        state.config = body
        config_gen.write(body)
        if state.display:
            state.display.reload_pages(body)
        return {"ok": True}

    @app.get("/api/config/export")
    async def export_config(_=Depends(require_auth_if_config)):
        if not CONFIG_PATH.exists():
            raise HTTPException(status_code=404, detail="No config found")
        return FileResponse(CONFIG_PATH, filename="config.yaml", media_type="application/x-yaml")

    @app.post("/api/config/import")
    async def import_config(request: Request, _=Depends(require_auth_if_config)):
        if state.direwolf and state.direwolf.state.value == "running":
            raise HTTPException(status_code=409, detail="Stop Direwolf before importing config")
        body = await request.body()
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")
        with open(CONFIG_PATH, "wb") as f:
            f.write(body)
        state.config = parsed
        return {"ok": True}

    # ── APRS-IS passcode calculator ───────────────────────────

    @app.get("/api/passcode")
    async def get_passcode(callsign: str):
        from core.config_gen import calculate_passcode
        return {"passcode": calculate_passcode(callsign)}

    # ── Hardware info ─────────────────────────────────────────

    @app.get("/api/audio-devices")
    async def get_audio_devices():
        """List ALSA audio devices available on the system."""
        devices = []
        try:
            result = subprocess.run(
                ["aplay", "-l"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if line.startswith("card "):
                    devices.append(line.strip())
        except Exception:
            devices = ["default"]
        return {"devices": devices or ["default"]}

    @app.get("/api/serial-ports")
    async def get_serial_ports():
        """List available serial ports."""
        try:
            import serial.tools.list_ports
            ports = [{"device": p.device, "description": p.description}
                     for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []
        return {"ports": ports}

    @app.get("/api/display/models")
    async def get_display_models():
        """List e-ink screens available to the Waveshare driver, discovered from
        display/waveshare/ — adding a driver module there makes it show up here
        with no server code changes."""
        from display.waveshare import MODELS
        models = [
            {"value": key, "desc": info["desc"], "w": info["w"], "h": info["h"]}
            for key, info in sorted(MODELS.items())
        ]
        return {"models": models}

    @app.post("/api/ptt-test")
    async def ptt_test(_=Depends(require_auth_if_config)):
        """Key the PTT for 1 second to verify the relay/PTT wiring."""
        if not state.relay:
            raise HTTPException(status_code=503, detail="No relay configured")
        gpio_fired = await state.relay.test_ptt()
        if not gpio_fired:
            return {"ok": True, "simulated": True, "detail": "GPIO not available — ran in simulation mode"}
        return {"ok": True, "simulated": False}

    # ── Network ───────────────────────────────────────────────

    @app.get("/api/network/scan")
    async def wifi_scan():
        from services import network
        return {"networks": await network.scan_wifi()}

    @app.get("/api/network/ip")
    async def get_ip():
        from services import network
        return await network.get_ip()

    @app.post("/api/network/apply")
    async def apply_network(request: Request, _=Depends(require_auth_if_config)):
        body = await request.json()
        mode = body.get("mode")
        from services import network
        if mode == "hotspot":
            ok = await network.setup_hotspot(body.get("ssid", "Digipeater"), body.get("password", "Digipeater"))
        elif mode == "wifi_client":
            ok = await network.connect_wifi(body.get("ssid", ""), body.get("password", ""))
        elif mode == "ethernet":
            ok = await network.disable_wifi()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")
        return {"ok": ok}

    # ── Map tile cache ────────────────────────────────────────

    @app.get("/api/map/cache/estimate")
    async def tile_estimate(north: float, south: float, east: float, west: float,
                            zoom_min: int = 8, zoom_max: int = 14):
        from services.tile_cache import estimate_tiles
        count, size_mb = estimate_tiles(
            {"north": north, "south": south, "east": east, "west": west},
            zoom_min, zoom_max
        )
        return {"tile_count": count, "estimated_mb": round(size_mb, 1)}

    @app.post("/api/map/cache/start")
    async def tile_cache_start(request: Request, _=Depends(require_auth_if_config)):
        body = await request.json()
        from services.tile_cache import TileDownloader
        tile_server = state.config.get("map", {}).get(
            "tile_server", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        )
        downloader = TileDownloader(
            bounds=body.get("region", {}),
            zoom_min=body.get("zoom_min", 8),
            zoom_max=body.get("zoom_max", 14),
            tile_dir=TILE_DIR,
            tile_server=tile_server,
        )
        asyncio.create_task(downloader.run())
        state.tile_downloader = downloader
        return {"ok": True}

    @app.get("/api/map/cache/status")
    async def tile_cache_status():
        dl = getattr(state, "tile_downloader", None)
        if not dl:
            return {"active": False}
        return dl.status()

    @app.post("/api/map/cache/cancel")
    async def tile_cache_cancel():
        dl = getattr(state, "tile_downloader", None)
        if dl:
            dl.cancel()
        return {"ok": True}

    # ── Offline tile serving ──────────────────────────────────

    @app.get("/tiles/{z}/{x}/{y}.png")
    async def serve_tile(z: int, x: int, y: int):
        tile_path = TILE_DIR / str(z) / str(x) / f"{y}.png"
        if not tile_path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(tile_path, media_type="image/png")

    # ── System ────────────────────────────────────────────────

    @app.post("/api/system/reboot")
    async def reboot(_=Depends(require_auth)):
        asyncio.create_task(_do_reboot())
        return {"ok": True}

    # ── WebSocket — log stream ────────────────────────────────

    @app.websocket("/ws/log")
    async def ws_log(websocket: WebSocket):
        if _security_mode() != "none":
            auth = websocket.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and auth[7:] in _valid_tokens):
                await websocket.close(code=1008, reason="Unauthorized")
                return
        await websocket.accept()
        state.log_subscribers.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            state.log_subscribers.discard(websocket)

    # ── WebSocket — map stream ────────────────────────────────

    @app.websocket("/ws/map")
    async def ws_map(websocket: WebSocket):
        if _security_mode() != "none":
            auth = websocket.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and auth[7:] in _valid_tokens):
                await websocket.close(code=1008, reason="Unauthorized")
                return
        await websocket.accept()
        state.map_subscribers.add(websocket)
        # Send current station state immediately on connect
        if state.packet_store:
            for packet in state.packet_store.get_latest_position_per_callsign():
                await websocket.send_json({"type": "station", "new": False, **packet})
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            state.map_subscribers.discard(websocket)

    # ── Static files (must be last) ───────────────────────────

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


# ── Background helpers ────────────────────────────────────────

async def _do_start(state) -> None:
    """Runs the startup sequence and launches Direwolf."""
    from main import start_direwolf
    await start_direwolf()


async def _do_reboot() -> None:
    await asyncio.sleep(1)
    subprocess.run(["sudo", "reboot"])
