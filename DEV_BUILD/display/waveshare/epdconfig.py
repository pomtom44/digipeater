"""
Low-level GPIO and SPI hardware layer shared by all Waveshare e-Paper drivers.

Default wiring (BCM numbering):
  RST = 17   DC = 25   CS = 8 (SPI CE0)   BUSY = 24
  DIN (MOSI) = 10   CLK (SCLK) = 11   VCC = 3.3V   GND = GND

These are the standard Waveshare RPi-HAT pin assignments. Boards like the
Pico-ePaper series are wired for a Pico's header rather than a direct-plug
RPi HAT, so when driving one from a Raspberry Pi the 8 signal wires above
must be connected by hand to these BCM pins (or change the constants below
to match whatever pins you actually wired).

The project default relay_pin is GPIO 27, which avoids the RST conflict.
Do not change relay_pin to 17 when an e-ink display is installed.

Falls back to a no-op simulation when RPi.GPIO or spidev are unavailable.
"""

import time
import logging

logger = logging.getLogger(__name__)

RST_PIN  = 17
DC_PIN   = 25
CS_PIN   = 8
BUSY_PIN = 24

try:
    import RPi.GPIO as GPIO
    import spidev
    _SPI = spidev.SpiDev()
    _HW = True
except ImportError:
    _HW = False
    logger.info("RPi.GPIO/spidev unavailable — e-ink display running in simulation mode")


def module_init() -> int:
    if not _HW:
        return 0
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(RST_PIN, GPIO.OUT)
    GPIO.setup(DC_PIN,  GPIO.OUT)
    GPIO.setup(CS_PIN,  GPIO.OUT)
    GPIO.setup(BUSY_PIN, GPIO.IN)
    _SPI.open(0, 0)
    _SPI.max_speed_hz = 4000000  # matches Waveshare's official reference for this board family
    _SPI.mode = 0b00
    return 0


def module_exit():
    if not _HW:
        return
    GPIO.output(RST_PIN, 0)
    GPIO.output(DC_PIN,  0)
    _SPI.close()
    GPIO.cleanup()


def digital_write(pin: int, value: int):
    if _HW:
        GPIO.output(pin, value)


def digital_read(pin: int) -> int:
    return GPIO.input(pin) if _HW else 0


def delay_ms(ms: float):
    time.sleep(ms / 1000.0)


def spi_writebyte(data: list):
    """Write a short list of bytes (commands/args)."""
    if _HW:
        _SPI.writebytes(data)


def spi_writebytes(data) -> None:
    """Write a large buffer (pixel data). Uses writebytes2 if available."""
    if not _HW:
        return
    if hasattr(_SPI, "writebytes2"):
        _SPI.writebytes2(data)
    else:
        data = list(data)
        for i in range(0, len(data), 4096):
            _SPI.writebytes(data[i : i + 4096])
