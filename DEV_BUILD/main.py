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
HOTSPOT_PASSWORD = "Digipeater"


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


def _draw_lines(driver, lines: list[str]):
    from PIL import Image, ImageDraw
    image = Image.new("1", (driver.width, driver.height), 255)
    draw = ImageDraw.Draw(image)
    margin = driver.margin
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill=0)
        y += driver.line_height
    return image


async def _render_lines(driver, lines: list[str]) -> None:
    """Render text to the display off the event loop thread — a hardware hang
    here (e.g. a stuck BUSY pin) must not freeze the whole web server with it."""
    try:
        from PIL import Image, ImageDraw  # noqa: F401 — import check before threading
    except ImportError:
        logger.warning("Pillow not installed — skipping display render")
        return
    try:
        image = await asyncio.to_thread(_draw_lines, driver, lines)
        await asyncio.to_thread(driver.show, image)
    except Exception as e:
        logger.error("Display render failed: %s", e)


async def _first_boot_sequence(driver) -> None:
    """Show first-boot status on the e-ink display and bring up the WiFi hotspot."""
    await _render_lines(driver, ["First boot config", "", "Starting network..."])

    await network.setup_hotspot(HOTSPOT_SSID, HOTSPOT_PASSWORD)
    eth_ip = await network.get_ethernet_ip()

    await _render_lines(driver, [
        "First boot config",
        "",
        f"Eth: {eth_ip or 'not connected'}",
        f"AP: {HOTSPOT_SSID}",
        f"Pass: {HOTSPOT_PASSWORD}",
    ])


async def main() -> None:
    first_boot = not CONFIG_PATH.exists()

    driver_name, driver_model = _load_display_config()
    display_driver = _load_display_driver(driver_name, driver_model)
    try:
        await asyncio.to_thread(display_driver.init)
        logger.info("Display initialised: %dx%d", display_driver.width, display_driver.height)
    except Exception as e:
        logger.error("Display init failed: %s", e)

    if first_boot:
        logger.info("No config.yaml found — running first-boot sequence")
        await _first_boot_sequence(display_driver)
    else:
        await _render_lines(display_driver, ["Digipeater", "Running"])

    app = create_app(display_driver, first_boot)

    server_config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
