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

# Installed via install.sh (fonts-dejavu-core) — standard, stable path on
# Raspberry Pi OS / Debian. Falls back to PIL's tiny bitmap font if missing
# (e.g. running this locally on a dev machine).
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
FONT_BOLD = f"{FONT_DIR}/DejaVuSans-Bold.ttf"
FONT_REGULAR = f"{FONT_DIR}/DejaVuSans.ttf"


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


def _load_font(path: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


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


def _draw_loading_page(driver):
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w - 1, h - 1), outline=0)

    font = _load_font(FONT_BOLD, 22)
    text = "Loading..."
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2, (h - th) / 2 - bbox[1]), text, font=font, fill=0)
    return image


def _draw_network_page(driver, eth_ip: str, ssid: str, password: str):
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    margin = 8

    title_font = _load_font(FONT_BOLD, 16)
    label_font = _load_font(FONT_BOLD, 13)
    value_font = _load_font(FONT_REGULAR, 13)

    draw.text((margin, 4), "First Boot — Connect", font=title_font, fill=0)
    draw.line((margin, 26, w - margin, 26), fill=0, width=1)

    rows = [
        ("Ethernet:", eth_ip or "not connected"),
        ("Hotspot:", ssid),
        ("Password:", password),
    ]
    y = 34
    for label, value in rows:
        draw.text((margin, y), label, font=label_font, fill=0)
        draw.text((margin + 70, y), value, font=value_font, fill=0)
        y += 22

    return image


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


async def _first_boot_sequence(driver) -> None:
    """Show first-boot status on the e-ink display and bring up the WiFi hotspot."""
    await _render(driver, _draw_loading_page)

    await network.setup_hotspot(HOTSPOT_SSID, HOTSPOT_PASSWORD)
    eth_ip = await network.get_ethernet_ip()

    await _render(driver, _draw_network_page, eth_ip, HOTSPOT_SSID, HOTSPOT_PASSWORD, fast=True)


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
        await _render(display_driver, _draw_lines, ["Digipeater", "Running"])

    app = create_app(display_driver, first_boot)

    server_config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
