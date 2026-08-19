"""Rotates the e-ink display through the status pages configured in config.yaml's display.pages."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from services import gps, system

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")

# Page types offered by the wizard/config page's E-Ink step, in default order.
PAGE_IDS = ("status", "config_summary", "location", "symbol", "last_beacon", "last_heard")
DEFAULT_DURATION_S = 30

# Sprite sheet layout for APRS symbol icons (hessu/aprs-symbols).
_SPRITE_DIR = Path("web/static/aprs-symbols")
_SPRITE_CELL = 64
_SPRITE_COLS = 16
_SYMBOL_ICON_SIZE = 56
_STATION_ICON_SIZE = 40
_symbol_sheet_cache: dict = {}


@dataclass
class Page:
    id: str
    enabled: bool
    duration: int


DEFAULT_PAGES = [Page(page_id, True, DEFAULT_DURATION_S) for page_id in PAGE_IDS]


def load_pages(display_config: dict | None) -> list[Page]:
    """Loads pages from config.yaml, falling back to DEFAULT_PAGES if empty or missing."""
    raw = (display_config or {}).get("pages") or []
    if not raw:
        return list(DEFAULT_PAGES)
    return [
        Page(p["id"], p.get("enabled", True), int(p.get("duration") or DEFAULT_DURATION_S))
        for p in raw
    ]


def _format_coord(value) -> str:
    """Formats a coordinate to 4 decimal places."""
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception as e:
        logger.error("Failed to read %s: %s", CONFIG_PATH, e)
        return {}


def _load_symbol_sheet(sheet_name: str):
    """Loads and caches a symbol sprite sheet image."""
    if sheet_name not in _symbol_sheet_cache:
        from PIL import Image
        _symbol_sheet_cache[sheet_name] = Image.open(_SPRITE_DIR / sheet_name).convert("RGBA")
    return _symbol_sheet_cache[sheet_name]


def _render_symbol_glyph(table: str, symbol: str, size: int):
    """Crops, flattens onto white, and resizes a symbol glyph from the sprite sheet into a 1-bit image."""
    from PIL import Image
    sheet = _load_symbol_sheet("sheet1.png" if table == "\\" else "sheet0.png")
    code = ord(symbol) - 0x21
    col, row = code % _SPRITE_COLS, code // _SPRITE_COLS
    x, y = col * _SPRITE_CELL, row * _SPRITE_CELL
    cell = sheet.crop((x, y, x + _SPRITE_CELL, y + _SPRITE_CELL))
    flat = Image.new("RGBA", cell.size, (255, 255, 255, 255))
    flat.alpha_composite(cell)
    return flat.convert("L").resize((size, size), Image.LANCZOS).convert("1")


# Direwolf state labels, mirroring normal.html's dashboard badge text.
_DIREWOLF_STATE_LABELS = {
    "running": "Running",
    "starting": "Starting",
    "waiting_gps": "Waiting for GPS fix",
    "standby": "Standby",
    "stopping": "Stopping",
    "error": "Error",
}
_EMPTY_ROTATION_POLL_S = 5
# Partial refresh leaves faint ghosting over time, so every Nth tick forces a full refresh instead.
_FULL_REFRESH_EVERY = 10


def _format_duration(seconds: float) -> str:
    """Formats a duration as a human-readable span, e.g. "5m", "2h 14m", "3d 5h"."""
    seconds = max(0, seconds)
    total_minutes = int(seconds // 60)
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class RotationManager:
    def __init__(self, driver, template, pages: list[Page], network_status: dict, packets=None):
        self._driver = driver
        self._template = template
        self._pages = pages
        self._network_status = network_status
        self._packets = packets
        self._index = 0
        self._render_count = 0
        self._task: asyncio.Task | None = None
        # Monotonic clock, unaffected by GPS time sync jumps at runtime.
        self._started_at = asyncio.get_event_loop().time()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def reload_pages(self, pages: list[Page]) -> None:
        """Hot-swaps the rotation list; takes effect on the next tick, no reboot needed."""
        self._pages = pages
        self._index = 0

    async def _loop(self) -> None:
        while True:
            try:
                enabled = [p for p in self._pages if p.enabled]
                if not enabled:
                    await asyncio.sleep(_EMPTY_ROTATION_POLL_S)
                    continue

                page = enabled[self._index % len(enabled)]
                await self._render_page(page)
                self._index = (self._index + 1) % len(enabled)
                await asyncio.sleep(page.duration)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Display rotation tick failed: %s", e)
                await asyncio.sleep(_EMPTY_ROTATION_POLL_S)

    async def _render_page(self, page: Page) -> None:
        # last_beacon/symbol/last_heard use dedicated template functions, not draw_status_page below.
        if page.id == "last_beacon":
            title, headers, rows = self._last_beacon_page(_read_config())
            await self._render(self._template.draw_table_page, title, headers, rows, fast=True)
            return
        if page.id == "symbol":
            title, symbol_image, comment = self._symbol_page(_read_config())
            await self._render(self._template.draw_symbol_page, title, symbol_image, comment, fast=True)
            return
        if page.id == "last_heard":
            title, symbol_image, callsign, lat, lon, comment = self._last_heard_page()
            await self._render(
                self._template.draw_station_page, title, symbol_image, callsign, lat, lon, comment, fast=True,
            )
            return
        title, rows = await self._build_page_content(page.id)
        await self._render(self._template.draw_status_page, title, rows, fast=True)

    async def _render(self, draw_fn, *args, fast: bool) -> None:
        """Off-thread draw and show so a hardware hang can't freeze this loop or the web server."""
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401 (import check before threading)
        except ImportError:
            return
        self._render_count += 1
        use_fast = fast and self._render_count % _FULL_REFRESH_EVERY != 0
        try:
            image = await asyncio.to_thread(draw_fn, self._driver, *args)
            show = self._driver.show_fast if use_fast else self._driver.show
            await asyncio.to_thread(show, image)
        except Exception as e:
            logger.error("Display render failed: %s", e)

    async def _build_page_content(self, page_id: str) -> tuple[str, list[tuple[str, str]]]:
        if page_id == "status":
            return await self._status_page()
        config = _read_config()
        if page_id == "config_summary":
            return self._config_summary_page(config)
        if page_id == "location":
            return await self._location_page(config)
        return page_id, []

    async def _status_page(self) -> tuple[str, list[tuple[str, str]]]:
        # Radio power isn't shown separately, it's fully implied by State.
        direwolf_status = await system.get_direwolf_status()
        state_label = _DIREWOLF_STATE_LABELS.get(direwolf_status["state"], direwolf_status["state"])
        uptime = _format_duration(asyncio.get_event_loop().time() - self._started_at)
        rows = [
            ("State", state_label),
            ("IP", self._network_status.get("ip") or "-"),
            ("Uptime", uptime),
        ]
        return "Status", rows

    def _config_summary_page(self, config: dict) -> tuple[str, list[tuple[str, str]]]:
        aprs = config.get("aprs", {}) or {}
        radio = config.get("radio", {}) or {}
        callsign = aprs.get("callsign") or "-"
        ssid = aprs.get("ssid")
        call = f"{callsign}-{ssid}" if callsign != "-" and ssid else callsign

        parts = []
        if aprs.get("digipeat_mode") == "digipeater":
            parts.append("Digi")
        if (aprs.get("igate_mode") or "off") != "off":
            parts.append("IGate")
        mode_summary = "+".join(parts) or "Off"

        frequency = radio.get("frequency_mhz")
        freq_label = f"{frequency} MHz" if frequency not in (None, "") else "-"

        rows = [
            ("Call", call),
            ("Freq", freq_label),
            ("Mode", mode_summary),
        ]
        return "Config", rows

    async def _location_page(self, config: dict) -> tuple[str, list[tuple[str, str]]]:
        gps_config = config.get("gps", {}) or {}
        if gps_config.get("position_source") == "manual":
            lat, lon = gps_config.get("latitude"), gps_config.get("longitude")
            rows = [
                ("GPS", "Manual"),
                ("Lat", _format_coord(lat)),
                ("Lon", _format_coord(lon)),
            ]
            return "Location", rows

        status = await gps.get_status()
        if not status.get("available") or not status.get("has_fix"):
            return "Location", [("GPS", "Searching")]
        sats = f"{status.get('satellites_used', '-')}/{status.get('satellites_visible', '-')} sats"
        rows = [
            ("GPS", sats),
            ("Lat", _format_coord(status["latitude"])),
            ("Lon", _format_coord(status["longitude"])),
        ]
        return "Location", rows

    def _last_beacon_page(self, config: dict) -> tuple[str, list[str], list[tuple[str, list[str]]]]:
        aprs = config.get("aprs", {}) or {}
        # RF and IGate beacons are configured independently, not a shared aprs.beacon block.
        rf_beacon = aprs.get("rf_beacon") or {}
        igate_beacon = aprs.get("igate_beacon") or {}
        rf_enabled = aprs.get("digipeat_mode") == "digipeater" and bool(rf_beacon.get("enabled"))
        igate_enabled = (aprs.get("igate_mode") or "off") != "off" and bool(igate_beacon.get("enabled"))
        stats = self._packets.beacon_stats() if self._packets else {}
        rows = [
            (
                "RF",
                self._beacon_row(
                    rf_enabled, stats.get("last_rf_beacon_seconds_ago"), int(rf_beacon.get("interval", 30)) * 60,
                ),
            ),
            (
                "IGate",
                self._beacon_row(
                    igate_enabled, stats.get("last_igate_beacon_seconds_ago"),
                    int(igate_beacon.get("interval", 30)) * 60,
                ),
            ),
        ]
        return "Last Beacon", ["Last", "Next"], rows

    def _beacon_row(self, enabled: bool, last_ago: int | None, interval_s: int) -> list[str]:
        if not enabled:
            return ["Disabled"]
        if last_ago is None:
            # No beacon logged yet this run.
            return ["None", "None"]
        remaining = interval_s - last_ago
        return [_format_duration(last_ago), "Due" if remaining <= 0 else _format_duration(remaining)]

    def _symbol_page(self, config: dict):
        aprs = config.get("aprs", {}) or {}
        symbol = aprs.get("symbol") or {}
        # Same fallback normal.html's station card uses for a not-yet-set symbol.
        table = symbol.get("table") or "/"
        char = symbol.get("symbol") or "#"
        icon = _render_symbol_glyph(table, char, _SYMBOL_ICON_SIZE)
        comment = aprs.get("comment") or ""
        return "Symbol", icon, comment

    def _last_heard_page(self):
        station = self._packets.last_heard() if self._packets else None
        if not station:
            # Nothing heard yet this run; no icon, avoid implying this station's own symbol is a heard station.
            return "Last Heard", None, "None", "None", "None", "None"
        icon = _render_symbol_glyph(
            station["symbol"]["table"], station["symbol"]["symbol"], _STATION_ICON_SIZE,
        )
        lat = _format_coord(station["latitude"]) if station.get("latitude") is not None else "None"
        lon = _format_coord(station["longitude"]) if station.get("longitude") is not None else "None"
        comment = station.get("comment") or "None"
        return "Last Heard", icon, station["callsign"], lat, lon, comment
