"""Generic 1.54" SPI e-Paper module — 200×200 pixels, SSD1681 controller.

BEST-GUESS DRIVER — UNVERIFIED. Ported for a generic "LA-SPI 1.54inch E-Ink"
AliExpress module the hardware isn't in hand for yet; the linked "manual" for
that listing turned out to be generic safety/compliance boilerplate with no
electrical specs, pin definitions, or controller info at all. 200×200 SSD1681
is simply the overwhelmingly standard reference design for 1.54" SPI e-paper
panels — virtually every manufacturer, including generic rebadges, converges
on it — so that's the basis here, not anything confirmed for this exact board.
Verify against real hardware before trusting this; expect to revisit pin
polarity/timing the same way epd2in9b_v4.py needed real hardware to nail down.
"""

import logging
from . import epdconfig

logger = logging.getLogger(__name__)

EPD_WIDTH  = 200
EPD_HEIGHT = 200

# ── Screen registry metadata — see waveshare/__init__.py for how this is used.
DESC = '1.54"  — 200×200 (unverified — best guess, no hardware in hand)'
LANDSCAPE_WIDTH  = 200
LANDSCAPE_HEIGHT = 200
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

    def _wait_busy(self):
        # busy=1 means busy, 0=idle — matches every SSD168x-family chip
        # confirmed so far in this project (see epd2in9b_v4.py).
        while epdconfig.digital_read(self.busy_pin) == 1:
            epdconfig.delay_ms(10)

    def _set_window(self, x0, y0, x1, y1):
        self._cmd(0x44)
        self._data((x0 >> 3) & 0xFF)
        self._data((x1 >> 3) & 0xFF)
        self._cmd(0x45)
        self._data(y0 & 0xFF)
        self._data((y0 >> 8) & 0xFF)
        self._data(y1 & 0xFF)
        self._data((y1 >> 8) & 0xFF)

    def _set_cursor(self, x, y):
        self._cmd(0x4E)
        self._data(x & 0xFF)
        self._cmd(0x4F)
        self._data(y & 0xFF)
        self._data((y >> 8) & 0xFF)

    def _turn_on(self):
        self._cmd(0x22)
        self._data(0xF7)
        self._cmd(0x20)
        self._wait_busy()

    def _turn_on_fast(self):
        self._cmd(0x22)
        self._data(0xC7)
        self._cmd(0x20)
        self._wait_busy()

    def init(self):
        epdconfig.module_init()
        self._reset()

        self._cmd(0x12)   # SWRESET
        self._wait_busy()

        self._cmd(0x01)   # Driver Output Control  (MUX = 199 = 0xC7)
        self._data(0xC7)
        self._data(0x00)
        self._data(0x00)

        self._cmd(0x11)   # Data Entry Mode
        self._data(0x01)  # X-increment, Y-decrement (top-left origin)

        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._set_cursor(0, self.height - 1)

        self._cmd(0x3C)   # Border Waveform
        self._data(0x05)

        self._cmd(0x18)   # Temperature Sensor: built-in
        self._data(0x80)

        self._wait_busy()

    def getbuffer(self, image):
        img = image.copy().convert("1")
        linewidth = (self.width + 7) >> 3
        buf = [0xFF] * (linewidth * self.height)
        pixels = img.load()
        for y in range(self.height):
            for x in range(self.width):
                if pixels[x, y] == 0:
                    buf[x // 8 + y * linewidth] &= ~(0x80 >> (x % 8))
        return buf

    def display(self, buf):
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._set_cursor(0, self.height - 1)
        self._cmd(0x24)
        self._data_block(buf)
        self._turn_on()

    def display_fast(self, buf):
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._set_cursor(0, self.height - 1)
        self._cmd(0x24)
        self._data_block(buf)
        self._turn_on_fast()

    def Clear(self):
        linewidth = (self.width + 7) >> 3
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._set_cursor(0, self.height - 1)
        self._cmd(0x24)
        self._data_block([0xFF] * linewidth * self.height)
        self._turn_on()

    def sleep(self):
        self._cmd(0x10)
        self._data(0x01)
        epdconfig.delay_ms(100)
        epdconfig.module_exit()
