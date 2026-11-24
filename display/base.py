"""Abstract base class for e-ink display drivers."""

import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


async def render_page(driver, draw_fn, *args, warn_missing_pillow: bool = False) -> None:
    """Draws via draw_fn in a worker thread and shows it as a full refresh, off-thread so a
    hardware hang can't freeze the caller's event loop."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401 (import check before threading)
    except ImportError:
        if warn_missing_pillow:
            logger.warning("Pillow not installed, skipping display render")
        return
    try:
        image = await asyncio.to_thread(draw_fn, driver, *args)
        await asyncio.to_thread(driver.show, image)
    except Exception as e:
        logger.error("Display render failed: %s", e)


class DisplayDriver(ABC):
    """All display drivers must implement this interface."""

    @abstractmethod
    def init(self) -> None:
        """Initialise the display hardware."""

    @abstractmethod
    def show(self, image) -> None:
        """Render a PIL Image to the display using a full refresh."""

    def show_fast(self, image) -> None:
        """Render a PIL Image using a fast/partial refresh if the driver supports one, otherwise a full refresh."""
        self.show(image)

    @abstractmethod
    def clear(self) -> None:
        """Clear the display to white."""

    @abstractmethod
    def sleep(self) -> None:
        """Put the display into low-power sleep mode."""

    @property
    @abstractmethod
    def width(self) -> int:
        """Display width in pixels."""

    @property
    @abstractmethod
    def height(self) -> int:
        """Display height in pixels."""

    @property
    def line_height(self) -> int:
        """Vertical spacing in pixels between rendered text lines (drivers may override)."""
        return 16

    @property
    def margin(self) -> int:
        """Inset in pixels from the top-left corner when rendering (drivers may override)."""
        return 4
