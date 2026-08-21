#!/usr/bin/env python3
"""Renders each e-ink page with sample data on the real configured display, for visual validation without live data. Run from the app directory (same cwd as main.py)."""

import json
import sys
import yaml
from pathlib import Path

DISPLAY_CONFIG_PATH = Path("display_config.json")
CONFIG_PATH = Path("config.yaml")


def _load_driver():
    if not DISPLAY_CONFIG_PATH.exists():
        print(f"{DISPLAY_CONFIG_PATH} not found, run install.sh's display selection step first.")
        sys.exit(1)
    data = json.loads(DISPLAY_CONFIG_PATH.read_text())
    driver_name, model = data.get("driver", "none"), data.get("model", "")
    if driver_name != "waveshare":
        print(f"Configured driver is '{driver_name}', not 'waveshare', nothing to preview.")
        sys.exit(1)

    gpio_config = {}
    if CONFIG_PATH.exists():
        gpio_config = (yaml.safe_load(CONFIG_PATH.read_text()) or {}).get("gpio", {}) or {}
    from display.waveshare import epdconfig
    epdconfig.configure(
        rst=gpio_config.get("eink_rst"), dc=gpio_config.get("eink_dc"),
        cs=gpio_config.get("eink_cs"), busy=gpio_config.get("eink_busy"),
    )

    from display.driver_waveshare import WaveshareDriver
    return WaveshareDriver(model), model


def _build_pages(template):
    from display.rotation import _render_symbol_glyph, _SYMBOL_ICON_SIZE, _STATION_ICON_SIZE

    symbol_icon = _render_symbol_glyph("/", "#", _SYMBOL_ICON_SIZE)
    station_icon = _render_symbol_glyph("/", ">", _STATION_ICON_SIZE)

    return [
        ("Loading", lambda d: template.draw_loading_page(d, "Digipeater")),
        ("Status", lambda d: template.draw_status_page(d, "Status", [
            ("State", "Running"), ("IP", "192.168.1.50"), ("Uptime", "2h 14m"),
        ])),
        ("Config", lambda d: template.draw_status_page(d, "Config", [
            ("Call", "ZL1ABC-9"), ("Freq", "144.575 MHz"), ("Mode", "Digi+IGate"),
        ])),
        ("Location", lambda d: template.draw_status_page(d, "Location", [
            ("GPS", "8/12 sats"), ("Lat", "-41.2865"), ("Lon", "174.7762"),
        ])),
        ("Symbol", lambda d: template.draw_symbol_page(
            d, "Symbol", symbol_icon, "Digipeater, 25W into a J-pole at 10m AGL",
        )),
        ("Last Beacon", lambda d: template.draw_table_page(d, "Last Beacon", ["Last", "Next"], [
            ("RF", ["5m", "25m"]), ("IGate", ["12m", "18m"]),
        ])),
        ("Last Heard", lambda d: template.draw_station_page(
            d, "Last Heard", station_icon, "ZL2XYZ-7", "-41.2900", "174.7800", "Mobile portable",
        )),
    ]


def main():
    driver, model = _load_driver()
    driver.init()

    from display.templates import get_template
    template = get_template(model)
    pages = _build_pages(template)

    print(f"Previewing {len(pages)} pages on {model}.")
    print("Press Enter to advance, 'q' then Enter to quit.\n")
    try:
        for name, draw_fn in pages:
            print(f"-> {name}")
            driver.show(draw_fn(driver))
            if input().strip().lower() == "q":
                break
    finally:
        driver.sleep()
    print("Done.")


if __name__ == "__main__":
    main()
