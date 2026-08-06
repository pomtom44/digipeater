"""
Manages e-ink display page rotation, override states, and rendering.
Pages rotate on a configurable timer. Override states (startup, error)
pause rotation and show a full-screen message.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Callable

from .base import DisplayDriver

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    logger.warning("Pillow not installed — display rendering disabled")


@dataclass
class Page:
    id: str
    enabled: bool
    duration: int


class DisplayManager:
    def __init__(self, driver: DisplayDriver, config: dict):
        self._driver = driver
        self._pages = _load_pages(config)
        self._current_index = 0
        self._override_message: Optional[str] = None
        self._override_is_error: bool = False
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._state_provider: Optional[Callable[[], dict]] = None

    def set_state_provider(self, fn: Callable[[], dict]) -> None:
        """Register a function that returns current system state for rendering."""
        self._state_provider = fn

    def reload_pages(self, config: dict) -> None:
        """Hot-reload page list from updated config without restarting the manager."""
        self._pages = _load_pages(config)
        self._current_index = 0

    def start(self) -> None:
        self._running = True
        self._driver.init()
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        self._driver.sleep()

    def override(self, message: str, is_error: bool = False) -> None:
        """Show a full-screen message, pausing page rotation."""
        self._override_message = message
        self._override_is_error = is_error
        asyncio.create_task(self._render_override())

    def clear_override(self) -> None:
        """Resume normal page rotation."""
        self._override_message = None
        self._override_is_error = False

    async def _loop(self) -> None:
        while self._running:
            if self._override_message:
                await asyncio.sleep(1)
                continue

            enabled = [p for p in self._pages if p.enabled]
            if not enabled:
                await asyncio.sleep(5)
                continue

            page = enabled[self._current_index % len(enabled)]
            await self._render_page(page)
            await asyncio.sleep(page.duration)

            self._current_index = (self._current_index + 1) % len(enabled)

    async def _render_page(self, page: Page) -> None:
        if not _PIL_AVAILABLE:
            return
        state = self._state_provider() if self._state_provider else {}
        image = _draw_page(page.id, state, self._driver)
        self._driver.show(image)

    async def _render_override(self) -> None:
        if not _PIL_AVAILABLE:
            return
        image = _draw_text_page(
            self._override_message,
            self._driver,
            bold=self._override_is_error,
        )
        self._driver.show(image)


def _load_pages(config: dict) -> list[Page]:
    raw = config.get("display", {}).get("pages", [])
    return [Page(p["id"], p.get("enabled", True), p.get("duration", 10)) for p in raw]


def _draw_page(page_id: str, state: dict, driver: DisplayDriver):
    """Render a named page using current system state."""
    w, h = driver.width, driver.height
    img = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(img)

    lines = []
    if page_id == "status":
        lines = [
            f"Status: {state.get('direwolf_state', '—')}",
            f"Radio: {'ON' if state.get('relay_on') else 'OFF'}",
            f"IP: {state.get('ip', '—')}",
        ]
    elif page_id == "config_summary":
        lines = [
            f"Call: {state.get('callsign', '—')}",
            f"Mode: {state.get('mode_summary', '—')}",
            f"Start: {state.get('start_mode', '—')}",
        ]
    elif page_id == "location":
        fix = state.get("gps_fix")
        if fix:
            lines = [
                "Location: GPS",
                f"Lat: {fix.get('latitude', '—')}",
                f"Lon: {fix.get('longitude', '—')}",
                f"HDOP: {fix.get('hdop', '—')}",
            ]
        else:
            lines = [
                "Location: Fixed",
                f"Lat: {state.get('fixed_lat', '—')}",
                f"Lon: {state.get('fixed_lon', '—')}",
            ]
    elif page_id == "last_beacon":
        lines = [
            "Last Beacon",
            state.get("last_beacon_time", "—"),
            state.get("last_beacon_text", "—"),
        ]
    elif page_id == "last_heard":
        lines = [
            "Last Heard",
            state.get("last_heard_call", "—"),
            state.get("last_heard_time", "—"),
        ]

    _draw_lines(draw, lines, driver)
    return img


def _draw_text_page(message: str, driver: DisplayDriver, bold: bool = False):
    """Render a single full-screen message."""
    img = Image.new("1", (driver.width, driver.height), 255)
    draw = ImageDraw.Draw(img)
    _draw_lines(draw, message.splitlines(), driver)
    return img


def _draw_lines(draw, lines: list[str], driver: DisplayDriver) -> None:
    """Simple line-by-line text renderer. Spacing/margin come from the driver
    (model-specific — see display/waveshare/epd1in54_v2.py LINE_HEIGHT/MARGIN)
    so each screen can tune layout without any change here."""
    margin = driver.margin
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill=0)
        y += driver.line_height
