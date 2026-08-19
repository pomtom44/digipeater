"""Waveshare 1.54inch e-Paper Module (Rev2.1) driver, ported from Waveshare's official epd1in54_V2.py, source-verified but not yet hardware-tested."""

import logging
from . import epdconfig

logger = logging.getLogger(__name__)

EPD_WIDTH  = 200
EPD_HEIGHT = 200

# ── Screen registry metadata, see waveshare/__init__.py for how this is used.
DESC = '1.54" 200x200, Waveshare 1.54inch e-Paper Module (Rev2.1)'
LANDSCAPE_WIDTH  = 200
LANDSCAPE_HEIGHT = 200
LINE_HEIGHT = 16
MARGIN = 4

# Full-refresh waveform LUT, transcribed verbatim from Waveshare's driver.
_LUT_FULL = [
    0x80, 0x48, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x40, 0x48, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0x48, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x40, 0x48, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x0A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x08, 0x01, 0x00, 0x08, 0x01, 0x00, 0x02,
    0x0A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x00, 0x00, 0x00,
    0x22, 0x17, 0x41, 0x00, 0x32, 0x20,
]

# Partial/fast-refresh waveform LUT, transcribed verbatim from Waveshare's driver.
_LUT_PARTIAL = [
    0x00, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x40, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x00, 0x00, 0x00,
    0x02, 0x17, 0x41, 0xB0, 0x32, 0x28,
]

# Data bytes for command 0x37 ("write display option"), sent before partial refresh.
_PARTIAL_DISPLAY_OPTION = [0x00, 0x00, 0x00, 0x00, 0x00, 0x40, 0x00, 0x00, 0x00, 0x00]


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
        epdconfig.delay_ms(5)
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
        # busy=1 means busy, 0=idle
        while epdconfig.digital_read(self.busy_pin) == 1:
            epdconfig.delay_ms(20)

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
        self._data(0xC7)
        self._cmd(0x20)
        self._wait_busy()

    def _turn_on_fast(self):
        self._cmd(0x22)
        self._data(0xCF)
        self._cmd(0x20)
        self._wait_busy()

    def _set_lut(self, lut):
        self._cmd(0x32)  # WRITE_LUT_REGISTER
        self._data_block(lut)
        self._cmd(0x3F)
        self._data(lut[153])
        self._cmd(0x03)
        self._data(lut[154])
        self._cmd(0x04)
        self._data(lut[155])
        self._data(lut[156])
        self._data(lut[157])
        self._cmd(0x2C)
        self._data(lut[158])

    def init(self):
        """Full-refresh init sequence, matches Waveshare's own driver."""
        epdconfig.module_init()
        self._reset()

        self._wait_busy()
        self._cmd(0x12)   # SWRESET
        self._wait_busy()

        self._cmd(0x01)   # Driver Output Control (MUX = height-1)
        self._data((self.height - 1) & 0xFF)
        self._data(((self.height - 1) >> 8) & 0xFF)
        self._data(0x01)

        self._cmd(0x11)   # Data Entry Mode: X-increment, Y-decrement
        self._data(0x01)

        # Y range given high-to-low, matching the Y-decrement entry mode above.
        self._set_window(0, self.height - 1, self.width - 1, 0)

        self._cmd(0x3C)   # Border Waveform
        self._data(0x01)

        self._cmd(0x18)   # Temperature Sensor: built-in
        self._data(0x80)

        self._cmd(0x22)   # Load Temperature and waveform setting
        self._data(0xB1)
        self._cmd(0x20)

        self._set_cursor(0, self.height - 1)
        self._wait_busy()

        self._set_lut(_LUT_FULL)

    def _init_partial(self):
        """Partial-refresh init, re-entered fresh before every display_fast() call."""
        self._reset()
        self._wait_busy()

        self._set_lut(_LUT_PARTIAL)

        self._cmd(0x37)  # Write display option
        for b in _PARTIAL_DISPLAY_OPTION:
            self._data(b)

        self._cmd(0x3C)  # Border Waveform
        self._data(0x80)

        self._cmd(0x22)
        self._data(0xC0)
        self._cmd(0x20)
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
        self._cmd(0x24)
        self._data_block(buf)
        self._turn_on()

    def display_fast(self, buf):
        self._init_partial()
        self._cmd(0x24)
        self._data_block(buf)
        self._turn_on_fast()

    def Clear(self):
        linewidth = (self.width + 7) >> 3
        self._cmd(0x24)
        self._data_block([0xFF] * linewidth * self.height)
        self._turn_on()

    def sleep(self):
        self._cmd(0x10)
        self._data(0x01)
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()
