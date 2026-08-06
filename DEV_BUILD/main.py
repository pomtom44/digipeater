import asyncio
import logging
from pathlib import Path

import uvicorn

from display.driver_none import NullDriver
from services import network
from web.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Hardcoded for now — becomes config-driven once the config system is built.
DISPLAY_DRIVER = "waveshare"
DISPLAY_MODEL = "epd2in9b_v3"
CONFIG_PATH = Path("config.yaml")

HOTSPOT_SSID = "Digipeater"
HOTSPOT_PASSWORD = "Digipeater"


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


def _render_lines(driver, lines: list[str]) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not installed — skipping display render")
        return
    image = Image.new("1", (driver.width, driver.height), 255)
    draw = ImageDraw.Draw(image)
    margin = driver.margin
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill=0)
        y += driver.line_height
    driver.show(image)


async def _first_boot_sequence(driver) -> None:
    """Show first-boot status on the e-ink display and bring up the WiFi hotspot."""
    _render_lines(driver, ["First boot config", "", "Starting network..."])

    await network.setup_hotspot(HOTSPOT_SSID, HOTSPOT_PASSWORD)
    eth_ip = await network.get_ethernet_ip()

    _render_lines(driver, [
        "First boot config",
        "",
        f"Eth: {eth_ip or 'not connected'}",
        f"AP: {HOTSPOT_SSID}",
        f"Pass: {HOTSPOT_PASSWORD}",
    ])


async def main() -> None:
    first_boot = not CONFIG_PATH.exists()

    display_driver = _load_display_driver(DISPLAY_DRIVER, DISPLAY_MODEL)
    try:
        display_driver.init()
        logger.info("Display initialised: %dx%d", display_driver.width, display_driver.height)
    except Exception as e:
        logger.error("Display init failed: %s", e)

    if first_boot:
        logger.info("No config.yaml found — running first-boot sequence")
        await _first_boot_sequence(display_driver)
    else:
        _render_lines(display_driver, ["Digipeater", "Running"])

    app = create_app(display_driver, first_boot)

    server_config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
