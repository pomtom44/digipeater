"""Entry point — wires all components together and starts the web server."""

import asyncio
import logging
from datetime import datetime
import yaml
from pathlib import Path

from core.direwolf import DirewolfManager, State
from core.packet_store import PacketStore
from hardware.relay import PowerRelay
from hardware.gps import GPSReader, GPSFix, GPSState
from hardware.radio import RadioController
from hardware.radio_programmer import RadioProgrammer
from display.manager import DisplayManager
from display.driver_none import NullDriver
from core import config_gen
from services import time_sync, network

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG_PATH = Path("config.example.yaml")

# ── Shared application state ──────────────────────────────────
class AppState:
    def __init__(self):
        self.config: dict = {}
        self.direwolf: DirewolfManager = None
        self.relay: PowerRelay = None
        self.gps: GPSReader = None
        self.display: DisplayManager = None
        self.gps_fix: GPSFix = None
        self.last_beacon_time: str = "—"
        self.last_beacon_text: str = "—"
        self.last_heard_call: str = "—"
        self.last_heard_time: str = "—"
        self.stats = {"heard": 0, "digipeated": 0, "gated": 0}
        self.direwolf_version: str = "—"
        self.direwolf_audio_device: str = "—"
        self.aprs_is_connected: bool = False
        self.aprs_is_server: str = "—"
        self.radio: RadioController = None
        self.radio_frequency: float = None
        self.radio_programmer: RadioProgrammer = None
        self.packet_store: PacketStore = None
        self.log_subscribers: set = set()   # WebSocket connections for log
        self.map_subscribers: set = set()   # WebSocket connections for map

    def get_display_state(self) -> dict:
        """Build the state dict for the display manager."""
        hw = self.config.get("hardware", {})
        mode = self.config.get("mode", {})
        modes = []
        if mode.get("rx_only"):
            modes.append("RX")
        if mode.get("igate"):
            modes.append("igate")
        if mode.get("digipeater"):
            modes.append("digi")
        if mode.get("beacon"):
            modes.append("beacon")

        return {
            "direwolf_state": self.direwolf.state.value if self.direwolf else "—",
            "relay_on": self.relay.powered if self.relay else False,
            "ip": "—",  # populated at runtime
            "callsign": self.config.get("callsign", "—"),
            "mode_summary": "+".join(modes) or "—",
            "start_mode": self.config.get("direwolf", {}).get("start_mode", "manual"),
            "gps_fix": {
                "latitude": self.gps_fix.latitude,
                "longitude": self.gps_fix.longitude,
                "hdop": self.gps_fix.hdop,
            } if self.gps_fix else None,
            "fixed_lat": self.config.get("rf_beacon", {}).get("location", {}).get("latitude"),
            "fixed_lon": self.config.get("rf_beacon", {}).get("location", {}).get("longitude"),
            "last_beacon_time": self.last_beacon_time,
            "last_beacon_text": self.last_beacon_text,
            "last_heard_call": self.last_heard_call,
            "last_heard_time": self.last_heard_time,
        }


app_state = AppState()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        if EXAMPLE_CONFIG_PATH.exists():
            logger.warning("config.yaml not found — copying from example")
            CONFIG_PATH.write_text(EXAMPLE_CONFIG_PATH.read_text())
        else:
            raise FileNotFoundError("No config.yaml found and no example config to copy from")
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


async def on_log_line(line: str) -> None:
    """Called for each Direwolf stdout line — parse and broadcast."""
    from core.log_parser import parse_line

    entry, map_event, status_update = parse_line(line)

    if status_update:
        if status_update.version:
            app_state.direwolf_version = status_update.version
        if status_update.audio_device:
            app_state.direwolf_audio_device = status_update.audio_device
        if status_update.aprs_is_connected is not None:
            app_state.aprs_is_connected = status_update.aprs_is_connected
        if status_update.aprs_is_server:
            app_state.aprs_is_server = status_update.aprs_is_server

    if entry:
        _update_stats(entry.message)
        payload = {"type": "log", "level": entry.level, "time": entry.timestamp, "message": entry.message}
        for ws in list(app_state.log_subscribers):
            try:
                await ws.send_json(payload)
            except Exception:
                app_state.log_subscribers.discard(ws)

    if map_event:
        packet = {
            "callsign": map_event.callsign,
            "latitude": map_event.latitude,
            "longitude": map_event.longitude,
            "timestamp": datetime.now().timestamp(),
            "time": map_event.timestamp,
            "packet_type": map_event.packet_type,
            "direct": map_event.direct,
            "symbol_table": map_event.symbol_table,
            "symbol_code": map_event.symbol_code,
            "comment": map_event.comment,
            "path": map_event.path,
            "weather": map_event.weather,
        }
        is_new = app_state.packet_store.add(packet)
        if map_event.latitude is not None and map_event.longitude is not None:
            payload = {"type": "station", "new": is_new, **packet}
            for ws in list(app_state.map_subscribers):
                try:
                    await ws.send_json(payload)
                except Exception:
                    app_state.map_subscribers.discard(ws)


def _update_stats(message: str) -> None:
    if message.startswith("Heard "):
        app_state.stats["heard"] += 1
        call = message.split(" ")[1]
        app_state.last_heard_call = call
        app_state.last_heard_time = datetime.now().strftime("%H:%M:%S")
    elif message.startswith("Digipeated "):
        app_state.stats["digipeated"] += 1
    elif message.startswith("Gated to APRS-IS"):
        app_state.stats["gated"] += 1
    elif message.startswith("Beacon sent"):
        app_state.last_beacon_time = datetime.now().strftime("%H:%M:%S")
        app_state.last_beacon_text = message


async def on_direwolf_state(state: State) -> None:
    """Called on Direwolf state changes."""
    logger.info("Direwolf state → %s", state.value)

    if state == State.ERROR:
        app_state.display.override(
            "Direwolf Error\nCheck log for\ndetails",
            is_error=True,
        )
        if app_state.relay:
            app_state.relay.power_off()
        app_state.aprs_is_connected = False
        app_state.aprs_is_server = "—"
    elif state == State.RUNNING:
        app_state.display.clear_override()
    elif state == State.STOPPED:
        app_state.display.clear_override()
        app_state.aprs_is_connected = False
        app_state.aprs_is_server = "—"


async def startup_sequence() -> bool:
    """
    Run the startup sequence before launching Direwolf:
    1. Power relay on (with countdown)
    2. Wait for GPS fix if GPS location is configured
    Returns True if startup should proceed, False to abort.
    """
    config = app_state.config
    hw = config.get("hardware", {})

    async def display_status(msg: str) -> None:
        app_state.display.override(msg)

    # Step 1 — relay
    if app_state.relay:
        await app_state.relay.power_on(on_status=display_status)

    # Step 2 — GPS wait
    needs_gps = (
        config.get("rf_beacon", {}).get("location", {}).get("source") == "gps"
        or config.get("igate_beacon", {}).get("location", {}).get("source") == "gps"
    )

    if needs_gps and app_state.gps:
        await display_status("Waiting for GPS fix...")
        while True:
            if app_state.gps.state == GPSState.FIXED:
                break
            if app_state.gps.state == GPSState.ERROR:
                await display_status("GPS Error\nCheck connection\nDirewolf stopped")
                return False
            elapsed = app_state.gps.waiting_seconds
            await display_status(f"Waiting GPS\n{elapsed}s elapsed")
            await asyncio.sleep(2)

    return True


async def start_direwolf() -> None:
    proceed = await startup_sequence()
    if not proceed:
        return

    config_gen.write(app_state.config)
    await app_state.direwolf.start()


async def main() -> None:
    # ── Load config ───────────────────────────────────────────
    try:
        app_state.config = load_config()
    except FileNotFoundError as e:
        logger.critical(str(e))
        return

    config = app_state.config

    # ── Time sync ─────────────────────────────────────────────
    asyncio.create_task(time_sync.ensure_time_sync(config))

    # ── Display ───────────────────────────────────────────────
    disp_cfg = config.get("display", {})
    driver_name = disp_cfg.get("driver", "none")
    driver_model = disp_cfg.get("model", "epd1in54_v2")
    driver = _load_driver(driver_name, driver_model)
    app_state.display = DisplayManager(driver, config)
    app_state.display.set_state_provider(app_state.get_display_state)
    app_state.display.start()

    # ── GPS ───────────────────────────────────────────────────
    gps_config = config.get("hardware", {}).get("gps", {})
    _use_gpsd = (
        config.get("rf_beacon", {}).get("location", {}).get("source") == "gps"
        or config.get("igate_beacon", {}).get("location", {}).get("source") == "gps"
    )
    app_state.gps = GPSReader(
        device=gps_config.get("device", "/dev/ttyAMA0"),
        baud=gps_config.get("baud", 9600),
        on_fix=_on_gps_fix,
        on_status=_on_gps_status,
        use_gpsd=_use_gpsd,
    )
    app_state.gps.start()

    # ── Relay ─────────────────────────────────────────────────
    relay_pin = config.get("hardware", {}).get("relay_pin", 27)
    boot_delay = config.get("hardware", {}).get("radio_boot_delay", 10)
    app_state.relay = PowerRelay(relay_pin, boot_delay)

    # ── Radio CAT control ─────────────────────────────────────
    radio_config = config.get("radio", {})
    app_state.radio = RadioController(radio_config)
    await app_state.radio.start()
    if app_state.radio.enabled:
        asyncio.create_task(_poll_radio())

    # ── Radio memory programmer ───────────────────────────────
    app_state.radio_programmer = RadioProgrammer(config.get("radio_programmer", {}))

    # ── Packet store ──────────────────────────────────────────
    app_state.packet_store = PacketStore()

    # ── Direwolf manager ──────────────────────────────────────
    app_state.direwolf = DirewolfManager(
        config=config,
        on_line=on_log_line,
        on_state=on_direwolf_state,
    )

    # ── Network ───────────────────────────────────────────────
    net = config.get("network", {})
    mode = net.get("mode", "hotspot")
    if mode == "hotspot":
        await network.setup_hotspot(
            net.get("hotspot", {}).get("ssid", "Digipeater"),
            net.get("hotspot", {}).get("password", "Digipeater"),
        )
    elif mode == "wifi_client":
        connected = await network.connect_wifi(
            net.get("wifi_client", {}).get("ssid", ""),
            net.get("wifi_client", {}).get("password", ""),
        )
        if connected:
            asyncio.create_task(
                network.monitor_wifi_connection(
                    net.get("wifi_client", {}).get("ssid", ""),
                    on_disconnect=lambda: logger.warning("WiFi lost"),
                )
            )
    elif mode == "ethernet":
        await network.disable_wifi()

    # ── Web server ────────────────────────────────────────────
    from web.server import create_app
    import uvicorn

    web_config = config.get("web", {})
    fastapi_app = create_app(app_state)

    server_config = uvicorn.Config(
        fastapi_app,
        host=web_config.get("host", "0.0.0.0"),
        port=web_config.get("port", 8080),
        log_level="warning",
    )
    server = uvicorn.Server(server_config)

    # ── Auto-start ────────────────────────────────────────────
    if config.get("direwolf", {}).get("start_mode") == "auto":
        asyncio.create_task(start_direwolf())

    await server.serve()


async def _poll_radio() -> None:
    """Background task: refresh cached radio frequency every 5 s."""
    while True:
        try:
            freq = await app_state.radio.get_frequency()
            if freq is not None:
                app_state.radio_frequency = freq
        except Exception:
            pass
        await asyncio.sleep(5)


async def _on_gps_fix(fix: GPSFix) -> None:
    app_state.gps_fix = fix


async def _on_gps_status(state: str, message: str) -> None:
    logger.info("GPS: %s", message)


def _load_driver(name: str, model: str = "epd1in54_v2"):
    if name == "none" or not name:
        from display.driver_none import NullDriver
        return NullDriver()
    if name == "waveshare":
        try:
            from display.driver_waveshare import WaveshareDriver
            return WaveshareDriver(model)
        except Exception as e:
            logger.error("Failed to load Waveshare driver for model '%s': %s — falling back to NullDriver", model, e)
            from display.driver_none import NullDriver
            return NullDriver()
    logger.warning("Unknown display driver '%s' — using NullDriver", name)
    from display.driver_none import NullDriver
    return NullDriver()


if __name__ == "__main__":
    asyncio.run(main())
