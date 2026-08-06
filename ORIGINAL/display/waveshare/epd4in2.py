"""Waveshare 4.2" e-Paper — 400×300 pixels — UC8176 controller."""

import logging
from . import epdconfig

logger = logging.getLogger(__name__)

EPD_WIDTH  = 400
EPD_HEIGHT = 300

# ── Screen registry metadata — see epd1in54_v2.py for how to add a new screen.
DESC = '4.2"  — 400×300'
LANDSCAPE_WIDTH  = 400
LANDSCAPE_HEIGHT = 300
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
        epdconfig.delay_ms(10)
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

    def _wait_busy(self):
        while epdconfig.digital_read(self.busy_pin) == 0:  # UC8176: busy LOW = busy
            epdconfig.delay_ms(10)

    def _turn_on(self):
        self._cmd(0x12)   # DISPLAY_REFRESH
        self._wait_busy()

    def init(self):
        epdconfig.module_init()
        self._reset()

        self._cmd(0x01)   # POWER_SETTING
        self._data(0x03)  # VDS_EN, VDG_EN
        self._data(0x00)  # VCOM_HV, VGHL_LV[1], VGHL_LV[0]
        self._data(0x2B)  # VDH = 11V
        self._data(0x2B)  # VDL = -11V
        self._data(0xFF)  # VDHR = 3V

        self._cmd(0x06)   # BOOSTER_SOFT_START
        self._data(0x17)
        self._data(0x17)
        self._data(0x17)

        self._cmd(0x04)   # POWER_ON
        self._wait_busy()

        self._cmd(0x00)   # PANEL_SETTING
        self._data(0xBF)  # KW-BF, KWR-AF, BWROTP 0, BWROTP 0
        self._data(0x0B)

        self._cmd(0x30)   # PLL_CONTROL
        self._data(0x3C)  # 50 Hz

        self._cmd(0x61)   # TCON_RESOLUTION
        self._data(EPD_WIDTH >> 8)
        self._data(EPD_WIDTH & 0xFF)
        self._data(EPD_HEIGHT >> 8)
        self._data(EPD_HEIGHT & 0xFF)

        self._cmd(0x82)   # VCM_DC_SETTING_REGISTER
        self._data(0x12)

        self._cmd(0X50)   # VCOM_AND_DATA_INTERVAL_SETTING
        self._data(0x97)

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
        self._cmd(0x10)   # DATA_START_TRANSMISSION_1 (old data)
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebytes([0xFF] * len(buf))
        epdconfig.digital_write(self.cs_pin, 1)
        epdconfig.delay_ms(2)

        self._cmd(0x13)   # DATA_START_TRANSMISSION_2 (new data)
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebytes(buf)
        epdconfig.digital_write(self.cs_pin, 1)
        epdconfig.delay_ms(2)

        self._turn_on()

    def Clear(self):
        linewidth = (self.width + 7) >> 3
        total = linewidth * self.height
        self._cmd(0x10)
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebytes([0xFF] * total)
        epdconfig.digital_write(self.cs_pin, 1)
        epdconfig.delay_ms(2)

        self._cmd(0x13)
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebytes([0xFF] * total)
        epdconfig.digital_write(self.cs_pin, 1)
        epdconfig.delay_ms(2)

        self._turn_on()

    def sleep(self):
        self._cmd(0x02)   # POWER_OFF
        self._wait_busy()
        self._cmd(0x07)   # DEEP_SLEEP
        self._data(0xA5)
        epdconfig.module_exit()
