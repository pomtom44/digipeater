"""Rotates the e-ink display through the status pages configured on the
wizard's/config page's E-Ink step (config.yaml's display.pages). Direwolf's
transient states (starting/waiting on a GPS fix/stopping/error) show up as
the Status page's "State" value rather than a separate full-screen
takeover, so they're just whatever the rotation happens to land on, same
as any other page.

Started once from main.py's normal-boot sequence and runs for the life of
the process (see RotationManager.start()); config.html's /api/config/save
can hot-swap the page list via reload_pages() without a reboot.

Ported from ORIGINAL/display/manager.py's DisplayManager (which also had a
page-rotation loop), adapted here to poll services.system's real Direwolf
state instead of receiving push callbacks: ORIGINAL ran Direwolf as a
supervised Python subprocess with its own state-change events; DEV_BUILD
drives it via systemd and polling throughout (see services/system.py's
get_direwolf_status).
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from services import gps, system

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")

# Matches first_run.html's EINK_DEFAULT_PAGES/EINK_DEFAULT_DURATION_S: the
# page types the wizard/config page's E-Ink step offers, in the same
# default order. last_beacon/last_heard render a placeholder (see
# _build_page_content). last_beacon/last_heard are backed by
# services/packet_log.py; both read as "None" until it's actually seen a
# beacon/packet since this run started.
PAGE_IDS = ("status", "config_summary", "location", "symbol", "last_beacon", "last_heard")
DEFAULT_DURATION_S = 30

# Same sprite sheet / cell math as normal.html's symbolGlyphHTML (hessu/
# aprs-symbols, CC BY-SA 4.0, see web/static/aprs-symbols/COPYRIGHT.md):
# sheet0.png is table '/', sheet1.png is table '\', each a 16-column grid
# of 64px cells.
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
    """config.yaml's display.pages, or DEFAULT_PAGES if empty/missing: a
    config.yaml written before this feature existed (or never touched from
    the wizard's own default) should still rotate something, not sit on a
    dead/empty list."""
    raw = (display_config or {}).get("pages") or []
    if not raw:
        return list(DEFAULT_PAGES)
    return [
        Page(p["id"], p.get("enabled", True), int(p.get("duration") or DEFAULT_DURATION_S))
        for p in raw
    ]


def _format_coord(value) -> str:
    """4 decimal places (~11m precision, plenty for a station's own
    position), not whatever precision the source happened to store: a
    Maidenhead-grid-derived manual position in particular comes out as a
    long repeating decimal (e.g. -37.770833333333) if just stringified
    as-is."""
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
    """Cached: the rotation loop re-renders the Symbol page on every
    cycle, and there's no reason to re-read the same PNG off disk every
    time when the symbol practically never changes mid-run."""
    if sheet_name not in _symbol_sheet_cache:
        from PIL import Image
        _symbol_sheet_cache[sheet_name] = Image.open(_SPRITE_DIR / sheet_name).convert("RGBA")
    return _symbol_sheet_cache[sheet_name]


def _render_symbol_glyph(table: str, symbol: str, size: int):
    """Crops the matching cell out of the sprite sheet, flattens it onto
    white (the source sprites have transparency; e-ink has no alpha
    channel), and resizes/dithers it down to a 1-bit image at the
    requested size."""
    from PIL import Image
    sheet = _load_symbol_sheet("sheet1.png" if table == "\\" else "sheet0.png")
    code = ord(symbol) - 0x21
    col, row = code % _SPRITE_COLS, code // _SPRITE_COLS
    x, y = col * _SPRITE_CELL, row * _SPRITE_CELL
    cell = sheet.crop((x, y, x + _SPRITE_CELL, y + _SPRITE_CELL))
    flat = Image.new("RGBA", cell.size, (255, 255, 255, 255))
    flat.alpha_composite(cell)
    return flat.convert("L").resize((size, size), Image.LANCZOS).convert("1")


# Mirrors normal.html's DIREWOLF_STATE_LABELS, so the Status page's "State"
# row reads the same as the dashboard badge.
_DIREWOLF_STATE_LABELS = {
    "running": "Running",
    "starting": "Starting",
    "waiting_gps": "Waiting for GPS fix",
    "standby": "Standby",
    "stopping": "Stopping",
    "error": "Error",
}
_EMPTY_ROTATION_POLL_S = 5


def _format_duration(seconds: float) -> str:
    """A human-scale span, e.g. "5m", "2h 14m", "3d 5h": used for both
    Status's Uptime and Last Beacon's Last/Next columns."""
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
        self._task: asyncio.Task | None = None
        # Monotonic, not wall-clock: GPS time sync can jump the system
        # clock at runtime, which would corrupt a time.time()-based
        # uptime figure.
        self._started_at = asyncio.get_event_loop().time()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def reload_pages(self, pages: list[Page]) -> None:
        """Hot-swap the rotation list (see web/server.py's
        /api/config/save): takes effect on the next tick, no reboot
        needed, unlike the display driver/model themselves."""
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
        # last_beacon/symbol/last_heard aren't label:value rows like
        # everything else (see display/templates/default.py's
        # draw_table_page/draw_symbol_page/draw_station_page): different
        # template functions and argument shapes than draw_status_page
        # below.
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
        """Mirrors main.py's own _render() (off-thread draw + show, so a
        hardware hang, e.g. a stuck BUSY pin, can't freeze this loop or the
        web server sharing the same event loop). Kept local rather than
        imported from main.py to avoid a circular import: main.py
        constructs this manager."""
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401 (import check before threading)
        except ImportError:
            return
        try:
            image = await asyncio.to_thread(draw_fn, self._driver, *args)
            show = self._driver.show_fast if fast else self._driver.show
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
        # Radio power isn't shown separately: it's fully implied by State
        # in every real code path (set_direwolf_running powers the relay
        # on right before Direwolf actually starts, and off again on any
        # failure or on stop), so it'd just be redundant with State here.
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
        # RF and IGate beacons are independently configured (separate
        # enabled/interval each, see services/direwolf_config.py's
        # rf_beacon/igate_beacon), not a shared aprs.beacon block.
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
            # Enabled, but services/packet_log.py hasn't actually seen a
            # beacon transmission log line yet this run (just started, or
            # none due yet): "None", not a bare "-", so it reads as "no
            # data yet" rather than a formatting placeholder.
            return ["None", "None"]
        remaining = interval_s - last_ago
        return [_format_duration(last_ago), "Due" if remaining <= 0 else _format_duration(remaining)]

    def _symbol_page(self, config: dict):
        aprs = config.get("aprs", {}) or {}
        symbol = aprs.get("symbol") or {}
        # Same fallback normal.html's station card uses for a not-yet-set
        # symbol.
        table = symbol.get("table") or "/"
        char = symbol.get("symbol") or "#"
        icon = _render_symbol_glyph(table, char, _SYMBOL_ICON_SIZE)
        comment = aprs.get("comment") or ""
        return "Symbol", icon, comment

    def _last_heard_page(self):
        station = self._packets.last_heard() if self._packets else None
        if not station:
            # Nothing heard yet this run (see services/packet_log.py): no
            # icon (draw_station_page accepts None), this station's own
            # symbol would misleadingly look like an actual heard station.
            # "None" for every field rather than a bare "-", so it reads
            # as "no data yet" rather than a formatting placeholder.
            return "Last Heard", None, "None", "None", "None", "None"
        icon = _render_symbol_glyph(
            station["symbol"]["table"], station["symbol"]["symbol"], _STATION_ICON_SIZE,
        )
        lat = _format_coord(station["latitude"]) if station.get("latitude") is not None else "None"
        lon = _format_coord(station["longitude"]) if station.get("longitude") is not None else "None"
        comment = station.get("comment") or "None"
        return "Last Heard", icon, station["callsign"], lat, lon, comment
