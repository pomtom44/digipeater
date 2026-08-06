"""Waveshare e-Paper display driver — wraps a model-specific EPD class into DisplayDriver."""

import importlib
import logging

from .base import DisplayDriver
from .waveshare import MODELS

logger = logging.getLogger(__name__)


class WaveshareDriver(DisplayDriver):
    """
    Loads the correct Waveshare EPD class for the configured model and adapts it
    to the DisplayDriver interface.  The display manager always works in landscape
    coordinates (width × height); this driver handles any internal rotation.
    """

    def __init__(self, model: str):
        info = MODELS.get(model)
        if not info:
            known = ", ".join(MODELS)
            raise ValueError(f"Unknown Waveshare model '{model}'. Known models: {known}")

        mod = importlib.import_module(f".waveshare.{info['module']}", package="display")
        self._epd = mod.EPD()
        # Landscape dimensions + layout metrics exposed to the display manager,
        # sourced from the model's own metadata (display/waveshare/__init__.py)
        self._w = info["w"]
        self._h = info["h"]
        self._line_height = info["line_height"]
        self._margin = info["margin"]
        logger.info("Waveshare driver loaded: %s (%d×%d)", model, self._w, self._h)

    # ── DisplayDriver interface ───────────────────────────────────────────

    def init(self) -> None:
        self._epd.init()

    def show(self, image) -> None:
        """Render a PIL Image (width×height, mode '1') to the display."""
        buf = self._epd.getbuffer(image)
        self._epd.display(buf)

    def clear(self) -> None:
        self._epd.Clear()

    def sleep(self) -> None:
        self._epd.sleep()

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    @property
    def line_height(self) -> int:
        return self._line_height

    @property
    def margin(self) -> int:
        return self._margin
