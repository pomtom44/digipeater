"""Controls the radio power relay via GPIO: powers the radio on before
Direwolf starts and off after it stops (see services/system.py's
set_direwolf_running, the only caller of power_on()/power_off()).

Ported from ORIGINAL/hardware/relay.py's gpiozero-based PowerRelay class,
rewritten as direct RPi.GPIO calls instead: gpiozero isn't a dependency
anywhere else in DEV_BUILD, and RPi.GPIO already is (see
display/waveshare/epdconfig.py), so this avoids adding a second GPIO
library for the same job. Falls back to a no-op simulation when RPi.GPIO
is unavailable, the same pattern as epdconfig.py and services/system.py's
own simulated-systemctl fallback.

The pin itself is claimed via an explicit init(pin) call, not as an
import-time side effect: main.py calls it once, right after reading
config.yaml, with config['gpio']['relay_pin'] (see web/server.py's
/api/config/save for where that setting is edited). Changing the pin
still needs a process restart to actually move which physical pin is
used (there's no live GPIO.cleanup()-then-reclaim path wired into the
config-save flow), but this is what makes the *next* boot after an edit
pick the new value up correctly, rather than always reclaiming the same
hardcoded pin regardless of config.yaml.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# GPIO 27, not 17: avoids the e-ink display's RST pin (see
# display/waveshare/epdconfig.py, which already documented this exact
# conflict before any relay code existed to back it up), and is otherwise
# free on every currently-supported display/PTT wiring (see PINOUT.md).
# Used as init()'s default when nothing in config.yaml overrides it.
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
    """Claims the relay's GPIO pin. Safe to call more than once (e.g. a
    reload in a dev context): releases the previous pin first if it's
    changed. Real hardware claiming only happens here, not at import
    time, so this can run after config.yaml has actually been read."""
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
    """Powers the radio on and waits BOOT_DELAY_S for it to finish
    booting before returning. A no-op if already on, so callers (see
    set_direwolf_running) don't need to track relay state themselves."""
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
    """Powers the radio off. Callers are responsible for waiting for
    Direwolf's own shutdown to finish first (see set_direwolf_running's
    SHUTDOWN_DELAY_S wait before calling this): this function only does
    the relay side, since Direwolf's stop and this relay's off are two
    separate systems, not something this module can sequence on its own."""
    global _powered
    if not _powered:
        return
    logger.info("Radio power relay OFF (GPIO %d)", RELAY_PIN)
    if _HW:
        GPIO.output(RELAY_PIN, GPIO.LOW)
    _powered = False
