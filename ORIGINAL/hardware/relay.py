"""Controls the radio power relay via GPIO."""

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from gpiozero import OutputDevice
    _GPIO_AVAILABLE = True
except (ImportError, Exception):
    _GPIO_AVAILABLE = False
    logger.warning("gpiozero not available — relay running in simulation mode")


class PowerRelay:
    def __init__(self, pin: int, boot_delay: int = 10):
        self._pin = pin
        self._boot_delay = boot_delay
        self._powered = False
        self._device = None

        if _GPIO_AVAILABLE:
            try:
                self._device = OutputDevice(pin, active_high=True, initial_value=False)
            except Exception as e:
                logger.error("Failed to initialise relay on pin %d: %s", pin, e)

    @property
    def powered(self) -> bool:
        return self._powered

    async def power_on(self, on_status: callable = None) -> None:
        """Power on the radio and wait for boot delay."""
        if self._powered:
            return

        logger.info("Relay ON — pin %d", self._pin)
        if self._device:
            self._device.on()
        self._powered = True

        for remaining in range(self._boot_delay, 0, -1):
            if on_status:
                await on_status(f"Radio powering up — {remaining}s")
            await asyncio.sleep(1)

        if on_status:
            await on_status("Radio ready")

    def power_off(self) -> None:
        """Power off the radio immediately."""
        logger.info("Relay OFF — pin %d", self._pin)
        if self._device:
            self._device.off()
        self._powered = False

    async def test_ptt(self) -> bool:
        """Key PTT for 1 second. Returns True if GPIO fired, False in simulation."""
        if self._device:
            logger.info("PTT test — keying pin %d for 1 s", self._pin)
            self._device.on()
            await asyncio.sleep(1)
            self._device.off()
            return True
        logger.warning("PTT test — GPIO not available, simulation mode only")
        await asyncio.sleep(1)
        return False

    def __del__(self):
        if self._device:
            self._device.close()
