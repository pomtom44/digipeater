"""Controls the radio power relay via GPIO, powering it on before Direwolf starts and off after it stops."""

import asyncio
import logging

logger = logging.getLogger(__name__)

# GPIO 27 (not 17, which conflicts with the e-ink display's RST pin); default when config.yaml doesn't override it.
DEFAULT_RELAY_PIN = 27
BOOT_DELAY_S = 10
SHUTDOWN_DELAY_S = 10

try:
    import RPi.GPIO as GPIO
    _HW = True
except ImportError:
    _HW = False
    logger.info("RPi.GPIO unavailable, radio power relay running in simulation mode")

RELAY_PIN = DEFAULT_RELAY_PIN
_initialized = False
_powered = False


def init(pin: int = DEFAULT_RELAY_PIN) -> None:
    """Claims the relay's GPIO pin; safe to call more than once, releasing the previous pin if changed."""
    global RELAY_PIN, _initialized
    if _initialized and pin == RELAY_PIN:
        return
    if _HW:
        if _initialized:
            GPIO.cleanup(RELAY_PIN)
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    RELAY_PIN = pin
    _initialized = True
    logger.info("Radio power relay initialized on GPIO %d", pin)


def is_powered() -> bool:
    return _powered


async def power_on() -> None:
    """Powers the radio on and waits BOOT_DELAY_S for it to boot; a no-op if already on."""
    global _powered
    if not _initialized:
        init()
    if _powered:
        return
    logger.info("Radio power relay ON (GPIO %d)", RELAY_PIN)
    if _HW:
        GPIO.output(RELAY_PIN, GPIO.HIGH)
    _powered = True
    await asyncio.sleep(BOOT_DELAY_S)


async def power_off() -> None:
    """Powers the radio off; callers must wait for Direwolf's shutdown to finish first."""
    global _powered
    if not _powered:
        return
    logger.info("Radio power relay OFF (GPIO %d)", RELAY_PIN)
    if _HW:
        GPIO.output(RELAY_PIN, GPIO.LOW)
    _powered = False
