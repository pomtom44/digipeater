"""Null display driver — used when no display hardware is configured."""

import logging
from .base import DisplayDriver

logger = logging.getLogger(__name__)


class NullDriver(DisplayDriver):
    """Logs display output instead of rendering to hardware. Used for dev/testing."""

    def init(self) -> None:
        logger.debug("NullDriver: init")

    def show(self, image) -> None:
        logger.debug("NullDriver: show image %dx%d", image.width, image.height)

    def clear(self) -> None:
        logger.debug("NullDriver: clear")

    def sleep(self) -> None:
        logger.debug("NullDriver: sleep")

    @property
    def width(self) -> int:
        return 250

    @property
    def height(self) -> int:
        return 122
