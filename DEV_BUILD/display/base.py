"""Abstract base class for e-ink display drivers."""

from abc import ABC, abstractmethod


class DisplayDriver(ABC):
    """All display drivers must implement this interface."""

    @abstractmethod
    def init(self) -> None:
        """Initialise the display hardware."""

    @abstractmethod
    def show(self, image) -> None:
        """Render a PIL Image to the display using a full refresh (visible
        flash). Clears ghosting from prior updates."""

    def show_fast(self, image) -> None:
        """Render a PIL Image using a fast/partial refresh if the driver
        supports one (no full-screen flash), otherwise falls back to a full
        refresh. Ghosting accumulates slightly over repeated fast refreshes —
        not a substitute for occasional full refreshes, just for routine
        updates in between."""
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
        """Vertical spacing in pixels between rendered text lines. Drivers may override."""
        return 16

    @property
    def margin(self) -> int:
        """Inset in pixels from the top-left corner when rendering. Drivers may override."""
        return 4
