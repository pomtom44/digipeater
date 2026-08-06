"""Waveshare 2.9" e-Paper V2 — 296×128 pixels — SSD1680 controller.

Covers the standard RPi-HAT 2.9" V2 module and the Pico-ePaper-2.9 board
(same panel and controller; the Pico board just breaks the signals out for
a Pico's header instead of an RPi HAT connector — see epdconfig.py).
"""

import logging
from . import epdconfig

logger = logging.getLogger(__name__)

EPD_WIDTH  = 128
EPD_HEIGHT = 296

# ── Screen registry metadata — see waveshare/__init__.py for how this is used.
DESC = '2.9"  — 296×128'
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
        epdconfig.delay_ms(20)
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(2)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)

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

    def _wait_busy(self):
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

    def init(self):
        epdconfig.module_init()
        self._reset()
        self._wait_busy()

        self._cmd(0x12)   # SWRESET
        self._wait_busy()

        self._cmd(0x01)   # Driver Output Control  (MUX = 295 = 0x127)
        self._data(0x27)
        self._data(0x01)
        self._data(0x00)

        self._cmd(0x11)   # Data Entry Mode
        self._data(0x03)

        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._set_cursor(0, 0)

        self._cmd(0x3C)   # Border Waveform
        self._data(0x05)

        self._cmd(0x21)   # Display Update Control
        self._data(0x00)
        self._data(0x80)

        self._cmd(0x18)   # Temperature Sensor: built-in
        self._data(0x80)

        self._wait_busy()

    def getbuffer(self, image):
        img = image.copy()
        iw, ih = img.size
        if iw == self.height and ih == self.width:
            img = img.rotate(90, expand=True)
        img = img.convert("1")
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
        self._set_cursor(0, 0)
        self._cmd(0x24)
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebytes(buf)
        epdconfig.digital_write(self.cs_pin, 1)
        self._turn_on()

    def Clear(self):
        linewidth = (self.width + 7) >> 3
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._set_cursor(0, 0)
        self._cmd(0x24)
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebytes([0xFF] * linewidth * self.height)
        epdconfig.digital_write(self.cs_pin, 1)
        self._turn_on()

    def sleep(self):
        self._cmd(0x10)
        self._data(0x01)
        epdconfig.delay_ms(100)
        epdconfig.module_exit()
