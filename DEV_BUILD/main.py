import asyncio
import json
import logging
from pathlib import Path

import uvicorn

from display.driver_none import NullDriver
from services import network
from web.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")
# Written by install.sh's display-selection prompt (the display is needed during
# first boot, before any web-based config wizard exists, so it can't wait for
# the wizard — see DEV_BUILD/SETUP.md). Defaults to no display if absent.
DISPLAY_CONFIG_PATH = Path("display_config.json")

HOTSPOT_SSID = "Digipeater"
HOTSPOT_PASSWORD = "Digi1234"

# How long to wait for an existing ethernet/WiFi connection to come up on its
# own after boot (DHCP/association can take a few seconds) before concluding
# neither is connected and starting the hotspot instead.
CONNECTION_WAIT_TIMEOUT_S = 10.0
CONNECTION_POLL_INTERVAL_S = 1.0


def _load_display_config() -> tuple[str, str]:
    if not DISPLAY_CONFIG_PATH.exists():
        return "none", ""
    try:
        data = json.loads(DISPLAY_CONFIG_PATH.read_text())
        return data.get("driver", "none"), data.get("model", "")
    except Exception as e:
        logger.error("Failed to read %s: %s — defaulting to no display", DISPLAY_CONFIG_PATH, e)
        return "none", ""


def _load_display_driver(name: str, model: str):
    if name == "none" or not name:
        return NullDriver()
    if name == "waveshare":
        try:
            from display.driver_waveshare import WaveshareDriver
            return WaveshareDriver(model)
        except Exception as e:
            logger.error("Failed to load Waveshare driver for model '%s': %s — falling back to NullDriver", model, e)
            return NullDriver()
    logger.warning("Unknown display driver '%s' — using NullDriver", name)
    return NullDriver()


async def _render(driver, draw_fn, *args, fast: bool = False) -> None:
    """Render via draw_fn(driver, *args) off the event loop thread — a hardware
    hang here (e.g. a stuck BUSY pin) must not freeze the whole web server with it.

    fast=True uses a partial/fast refresh (no full-screen flash) where the
    driver supports one — for routine updates. Leave fast=False (full
    refresh) for the first draw of a session, to clear any prior ghosting."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401 — import check before threading
    except ImportError:
        logger.warning("Pillow not installed — skipping display render")
        return
    try:
        image = await asyncio.to_thread(draw_fn, driver, *args)
        show = driver.show_fast if fast else driver.show
        await asyncio.to_thread(show, image)
    except Exception as e:
        logger.error("Display render failed: %s", e)


async def _wait_for_existing_connection():
    """Poll for an ethernet or WiFi-client IP for a short window — DHCP/
    association can take a few seconds, so checking once immediately would
    too easily miss a connection that's about to come up on its own. Must be
    called before the hotspot is started, so a wlan0 IP here can only mean
    an existing client connection, not our own AP.

    Returns ("ethernet"|"wifi", ip) or (None, None) if nothing came up in time.
    """
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


async def _resolve_network() -> tuple[str, str]:
    """Core network policy — runs on every boot, first-time or normal alike,
    not just during initial setup. Checked in priority order: ethernet, then
    an existing WiFi client connection, then — only if neither is already
    connected — our own hotspot as a last resort. This is deliberate: the
    device should never silently strand itself with no way to reach it, but
    it also shouldn't start broadcasting a hotspot just because ethernet
    dropped for a moment while a real connection was still coming up.

    Returns ("ethernet"|"wifi"|"hotspot", ip_or_none).
    """
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

    driver_name, driver_model = _load_display_config()
    display_driver = _load_display_driver(driver_name, driver_model)
    try:
        await asyncio.to_thread(display_driver.init)
        logger.info("Display initialised: %dx%d", display_driver.width, display_driver.height)
    except Exception as e:
        logger.error("Display init failed: %s", e)

    from display.templates import get_template
    template = get_template(driver_model)

    if first_boot:
        logger.info("No config.yaml found — running first-boot sequence")
        await _render(display_driver, template.draw_loading_page)
        kind, ip = await _resolve_network()
        await _show_network_status(display_driver, template, "Initial config", kind, ip, fast=True)
    else:
        kind, ip = await _resolve_network()
        await _show_network_status(display_driver, template, "Digipeater", kind, ip, fast=False)

    network_status = {"kind": kind, "ip": ip, "hotspot_ssid": HOTSPOT_SSID}
    app = create_app(display_driver, first_boot, network_status)

    server_config = uvicorn.Config(app, host="0.0.0.0", port=80, log_level="warning")
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
