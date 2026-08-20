"""Waveshare 2.9" e-Paper (B) V4 driver, 296x128 pixels, black/white/red, SSD1680-family controller. No fast/partial refresh: confirmed on real hardware that fast silently no-ops and partial hangs forever on this panel."""

import logging
from . import epdconfig

logger = logging.getLogger(__name__)

EPD_WIDTH  = 128
EPD_HEIGHT = 296

# ── Screen registry metadata, see waveshare/__init__.py for how this is used.
DESC = '2.9"  B/W/R  296x128'
LANDSCAPE_WIDTH  = 296
LANDSCAPE_HEIGHT = 128
LINE_HEIGHT = 16
MARGIN = 4


class EPD:
    def __init__(self):
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin    = epdconfig.DC_PIN
        self.busy_pin  = epdconfig.BUSY_PIN
        self.cs_pin    = epdconfig.CS_PIN
        self.width  = EPD_WIDTH
        self.height = EPD_HEIGHT

    def _reset(self):
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(200)
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(2)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(200)

    def _cmd(self, cmd: int):
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([cmd])
        epdconfig.digital_write(self.cs_pin, 1)

    def _data(self, data: int):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([data])
        epdconfig.digital_write(self.cs_pin, 1)

    def _data_block(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebytes(data)
        epdconfig.digital_write(self.cs_pin, 1)

    def _wait_busy(self, timeout_ms: int = 30000):
        # Bounded: confirmed on real hardware that BUSY can hang forever (0x1C never releases it).
        self._cmd(0x71)
        waited = 0
        while epdconfig.digital_read(self.busy_pin) == 1:
            if waited >= timeout_ms:
                logger.error("e-Paper busy-wait timed out after %dms", timeout_ms)
                return
            epdconfig.delay_ms(200)
            waited += 200

    def _turn_on(self):
        """Full refresh, the only refresh mode this driver uses (see module docstring)."""
        self._cmd(0x22)   # Display update control
        self._data(0xF7)
        self._cmd(0x20)   # Activate display update sequence
        self._wait_busy()

    def init(self):
        epdconfig.module_init()
        self._reset()

        self._wait_busy()
        self._cmd(0x12)   # SWRESET
        self._wait_busy()

        self._cmd(0x01)   # Driver output control
        self._data((self.height - 1) % 256)
        self._data((self.height - 1) // 256)
        self._data(0x00)

        self._cmd(0x11)   # Data entry mode
        self._data(0x03)

        self._cmd(0x44)   # Set RAM X address start/end
        self._data(0x00)
        self._data(self.width // 8 - 1)

        self._cmd(0x45)   # Set RAM Y address start/end
        self._data(0x00)
        self._data(0x00)
        self._data((self.height - 1) % 256)
        self._data((self.height - 1) // 256)

        self._cmd(0x3C)   # Border waveform
        self._data(0x05)

        self._cmd(0x21)   # Display update control
        self._data(0x00)
        self._data(0x80)

        self._cmd(0x18)   # Temperature sensor: built-in
        self._data(0x80)

        self._cmd(0x4E)   # RAM X address counter
        self._data(0x00)
        self._cmd(0x4F)   # RAM Y address counter
        self._data(0x00)
        self._data(0x00)

        self._wait_busy()

    def getbuffer(self, image):
        img = image.convert("1")
        iw, ih = img.size
        linewidth = self.width // 8
        buf = [0xFF] * (linewidth * self.height)
        pixels = img.load()
        if iw == self.width and ih == self.height:
            for y in range(ih):
                for x in range(iw):
                    if pixels[x, y] == 0:
                        buf[(x + y * self.width) // 8] &= ~(0x80 >> (x % 8))
        elif iw == self.height and ih == self.width:
            for y in range(ih):
                for x in range(iw):
                    newx = y
                    newy = self.height - x - 1
                    if pixels[x, y] == 0:
                        buf[(newx + newy * self.width) // 8] &= ~(0x80 >> (y % 8))
        return buf

    def display(self, buf):
        blank_red = [0x00] * (self.width // 8 * self.height)
        self._cmd(0x24)   # Black/white plane
        self._data_block(buf)
        self._cmd(0x26)   # Red plane, left blank, no colour content yet
        self._data_block(blank_red)
        self._turn_on()

    def Clear(self):
        blank_black = [0xFF] * (self.width // 8 * self.height)
        blank_red = [0x00] * (self.width // 8 * self.height)
        self._cmd(0x24)
        self._data_block(blank_black)
        self._cmd(0x26)
        self._data_block(blank_red)
        self._turn_on()

    def sleep(self):
        self._cmd(0x10)   # Deep sleep
        self._data(0x01)
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()
