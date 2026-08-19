import asyncio
import json
import logging
from pathlib import Path

import uvicorn
import yaml

from display.driver_none import NullDriver
from display.rotation import RotationManager, load_pages
from services import direwolf_config, gpsconfig, network, packet_log, relay, restart_policy, system
from web.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Suppress httpx's per-request INFO logs (noisy during map tile proxying).
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")
# Written by install.sh's display-selection prompt. Defaults to no display if absent.
DISPLAY_CONFIG_PATH = Path("display_config.json")
# Written by web/server.py's /api/network/wifi, consumed once then deleted.
WIFI_PENDING_PATH = Path("wifi_pending.json")

HOTSPOT_SSID = "Digipeater"
HOTSPOT_PASSWORD = "Digi1234"

# Max time to wait for an existing ethernet/WiFi connection before starting the hotspot.
CONNECTION_WAIT_TIMEOUT_S = 10.0
CONNECTION_POLL_INTERVAL_S = 1.0


def _load_display_config() -> tuple[str, str]:
    if not DISPLAY_CONFIG_PATH.exists():
        return "none", ""
    try:
        data = json.loads(DISPLAY_CONFIG_PATH.read_text())
        return data.get("driver", "none"), data.get("model", "")
    except Exception as e:
        logger.error("Failed to read %s: %s, defaulting to no display", DISPLAY_CONFIG_PATH, e)
        return "none", ""


def _load_display_driver(name: str, model: str):
    if name == "none" or not name:
        return NullDriver()
    if name == "waveshare":
        try:
            from display.driver_waveshare import WaveshareDriver
            return WaveshareDriver(model)
        except Exception as e:
            logger.error("Failed to load Waveshare driver for model '%s': %s, falling back to NullDriver", model, e)
            return NullDriver()
    logger.warning("Unknown display driver '%s', using NullDriver", name)
    return NullDriver()


async def _render(driver, draw_fn, *args, fast: bool = False) -> None:
    """Render via draw_fn in a worker thread; fast=True uses a partial refresh instead of full."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401 (import check before threading)
    except ImportError:
        logger.warning("Pillow not installed, skipping display render")
        return
    try:
        image = await asyncio.to_thread(draw_fn, driver, *args)
        show = driver.show_fast if fast else driver.show
        await asyncio.to_thread(show, image)
    except Exception as e:
        logger.error("Display render failed: %s", e)


async def _wait_for_existing_connection():
    """Poll for an ethernet or WiFi-client IP for a short window before giving up."""
    elapsed = 0.0
    while True:
        eth_ip = await network.get_ethernet_ip()
        if eth_ip:
            return "ethernet", eth_ip
        wifi_ip = await network.get_wifi_client_ip()
        if wifi_ip:
            return "wifi", wifi_ip
        if elapsed >= CONNECTION_WAIT_TIMEOUT_S:
            return None, None
        await asyncio.sleep(CONNECTION_POLL_INTERVAL_S)
        elapsed += CONNECTION_POLL_INTERVAL_S


async def _apply_pending_wifi() -> bool:
    """Consume WiFi credentials saved by the first-boot wizard, if any."""
    if not WIFI_PENDING_PATH.exists():
        return False
    try:
        data = json.loads(WIFI_PENDING_PATH.read_text())
    except Exception as e:
        logger.error("Failed to read %s: %s", WIFI_PENDING_PATH, e)
        return False
    ok = await network.connect_wifi(data.get("ssid", ""), data.get("password", ""))
    if ok:
        WIFI_PENDING_PATH.unlink(missing_ok=True)
    return ok


async def _resolve_network() -> tuple[str, str]:
    """Try ethernet, then WiFi, then pending WiFi credentials, then fall back to a hotspot."""
    kind, ip = await _wait_for_existing_connection()
    if kind:
        return kind, ip
    if await _apply_pending_wifi():
        kind, ip = await _wait_for_existing_connection()
        if kind:
            return kind, ip
    await network.setup_hotspot(HOTSPOT_SSID, HOTSPOT_PASSWORD)
    return "hotspot", None


async def _show_network_status(driver, template, title: str, kind: str, ip: str, fast: bool) -> None:
    if kind == "ethernet":
        rows = [("Ethernet IP:", ip)]
    elif kind == "wifi":
        rows = [("Wifi IP:", ip)]
    else:
        rows = [
            ("Hotspot:", HOTSPOT_SSID),
            ("Password:", HOTSPOT_PASSWORD),
            ("Browse to:", network.HOTSPOT_IP),
        ]
    await _render(driver, template.draw_status_page, title, rows, fast=fast)


async def main() -> None:
    first_boot = not CONFIG_PATH.exists()

    # Read early so GPIO pin overrides apply before the display driver claims them.
    config = {}
    if not first_boot:
        try:
            config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception as e:
            logger.error("Failed to read %s: %s", CONFIG_PATH, e)
            config = {}

    gpio_config = config.get("gpio", {}) or {}
    relay.init(gpio_config.get("relay_pin", relay.DEFAULT_RELAY_PIN))
    from display.waveshare import epdconfig
    epdconfig.configure(
        rst=gpio_config.get("eink_rst"),
        dc=gpio_config.get("eink_dc"),
        cs=gpio_config.get("eink_cs"),
        busy=gpio_config.get("eink_busy"),
    )

    driver_name, driver_model = _load_display_config()
    display_driver = _load_display_driver(driver_name, driver_model)
    try:
        await asyncio.to_thread(display_driver.init)
        logger.info("Display initialised: %dx%d", display_driver.width, display_driver.height)
    except Exception as e:
        logger.error("Display init failed: %s", e)

    from display.templates import get_template
    template = get_template(driver_model)

    await _render(display_driver, template.draw_loading_page)
    kind, ip = await _resolve_network()
    network_status = {"kind": kind, "ip": ip, "hotspot_ssid": HOTSPOT_SSID}

    rotation = None
    packets = None
    if first_boot:
        logger.info("No config.yaml found, running first-boot sequence")
        await _show_network_status(display_driver, template, "Initial config", kind, ip, fast=True)
    else:
        # Normal boot: no static screen render here, the rotation manager's own first tick takes over.
        packets = packet_log.PacketLog()
        packets.start()
        rotation = RotationManager(
            display_driver, template, load_pages(config.get("display", {})), network_status, packets,
        )
        rotation.start()

        await gpsconfig.apply(config.get("gps", {}))
        await restart_policy.apply(config.get("startup", {}))

        # Regenerated fresh on every boot so a manually edited config.yaml still takes effect.
        try:
            direwolf_config.write(config)
        except OSError as e:
            logger.error("Failed to write direwolf.conf: %s", e)
        want_running = (config.get("startup", {}) or {}).get("autostart", True)
        result = await system.set_direwolf_running(want_running, config)
        if not result["ok"]:
            logger.error("Failed to %s direwolf: %s", "start" if want_running else "stop", result["reason"])

    app = create_app(display_driver, first_boot, network_status, rotation, packets)

    server_config = uvicorn.Config(app, host="0.0.0.0", port=80, log_level="warning")
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
