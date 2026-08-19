"""Low-level GPIO and SPI hardware layer shared by all Waveshare e-Paper drivers, simulated if RPi.GPIO/spidev are unavailable."""

import time
import logging

logger = logging.getLogger(__name__)

# Immutable reference defaults, separate from the mutable pins below that configure() overwrites at boot.
DEFAULT_RST_PIN = 17
DEFAULT_DC_PIN = 25
DEFAULT_CS_PIN = 8
DEFAULT_BUSY_PIN = 24

# relay_pin defaults to GPIO 27, not 17, to avoid conflicting with RST_PIN.
RST_PIN  = DEFAULT_RST_PIN
DC_PIN   = DEFAULT_DC_PIN
CS_PIN   = DEFAULT_CS_PIN
BUSY_PIN = DEFAULT_BUSY_PIN

try:
    import RPi.GPIO as GPIO
    import spidev
    _SPI = spidev.SpiDev()
    _HW = True
except ImportError:
    _HW = False
    logger.info("RPi.GPIO/spidev unavailable, e-ink display running in simulation mode")


def configure(rst: int = None, dc: int = None, cs: int = None, busy: int = None) -> None:
    """Overrides the pin constants above; must be called before the EPD is constructed, since it snapshots them at construction time."""
    global RST_PIN, DC_PIN, CS_PIN, BUSY_PIN
    if rst is not None:
        RST_PIN = rst
    if dc is not None:
        DC_PIN = dc
    if cs is not None:
        CS_PIN = cs
    if busy is not None:
        BUSY_PIN = busy


def module_init() -> int:
    if not _HW:
        return 0
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(RST_PIN, GPIO.OUT)
    GPIO.setup(DC_PIN,  GPIO.OUT)
    GPIO.setup(CS_PIN,  GPIO.OUT)
    # Internal pull-up: BUSY floats and reads a constant LOW without one.
    GPIO.setup(BUSY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    _SPI.open(0, 0)
    # Kept at 1MHz (below Waveshare's 4MHz reference) for reliability over breadboard jumper wires.
    _SPI.max_speed_hz = 1000000
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
