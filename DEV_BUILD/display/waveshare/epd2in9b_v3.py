"""Waveshare 2.9" e-Paper (B) V3 — 296×128 pixels, black/white/red.

Covers the Pico-ePaper-2.9-B board.

This app doesn't generate colour content yet, so the red plane is always
sent blank (all white) — display()/Clear() still refresh both planes, since
the controller expects both on every update regardless.
"""

import logging
from . import epdconfig

logger = logging.getLogger(__name__)

EPD_WIDTH  = 128
EPD_HEIGHT = 296

# ── Screen registry metadata — see waveshare/__init__.py for how this is used.
DESC = '2.9"  B/W/R — 296×128'
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
        epdconfig.delay_ms(50)
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(2)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(50)

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

    def _wait_busy(self, timeout_ms: int = 90000):
        # This controller is polled via command 0x71 while waiting, and busy
        # is signalled LOW (idle is HIGH) — opposite polarity to the mono driver.
        # Confirmed correct with a multimeter: BUSY reads 3.3V (idle) once the
        # panel actually finishes — its first power-on cycle just takes longer
        # than a refresh does, hence the generous timeout.
        # Bounded so a genuine wiring fault (BUSY stuck low forever) still can't
        # hang forever — a blocking hang here would freeze the whole asyncio
        # event loop, not just the display (see driver_waveshare.py for how
        # calls are isolated from that).
        self._cmd(0x71)
        waited = 0
        while epdconfig.digital_read(self.busy_pin) == 0:
            if waited >= timeout_ms:
                logger.error("e-Paper busy-wait timed out after %dms — BUSY pin stuck? Check wiring.", timeout_ms)
                return
            self._cmd(0x71)
            epdconfig.delay_ms(10)
            waited += 10

    def init(self):
        epdconfig.module_init()
        self._reset()

        self._cmd(0x04)   # Power on
        self._wait_busy()

        self._cmd(0x00)   # Panel setting
        self._data(0x0f)  # LUT from OTP, 128x296
        self._data(0x89)  # Temperature sensor, boost and related timing

        self._cmd(0x61)   # Resolution setting
        self._data(0x80)
        self._data(0x01)
        self._data(0x28)

        self._cmd(0x50)   # VCOM and data interval setting
        self._data(0x77)

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
        blank = [0xFF] * (self.width // 8 * self.height)
        self._cmd(0x10)   # Black/white plane
        self._data_block(buf)
        self._cmd(0x13)   # Red plane — left blank, no colour content yet
        self._data_block(blank)
        self._cmd(0x12)   # Refresh
        epdconfig.delay_ms(200)
        self._wait_busy()

    def Clear(self):
        blank = [0xFF] * (self.width // 8 * self.height)
        self._cmd(0x10)
        self._data_block(blank)
        self._cmd(0x13)
        self._data_block(blank)
        self._cmd(0x12)
        epdconfig.delay_ms(200)
        self._wait_busy()

    def sleep(self):
        self._cmd(0x02)   # Power off
        self._wait_busy()
        self._cmd(0x07)   # Deep sleep
        self._data(0xA5)
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()
