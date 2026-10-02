"""Dispatches radio channel programming to the driver registered for the configured model, before Direwolf starts."""

import asyncio
import logging

from services.radio_programmers import DRIVERS

logger = logging.getLogger(__name__)

PROGRAM_SETTLE_DELAY_S = 5


def can_program(model: str | None) -> bool:
    return (model or "") in DRIVERS


async def program_channel(radio_config: dict) -> dict:
    model = radio_config.get("model")
    driver = DRIVERS.get(model or "")
    if driver is None:
        return {"ok": True, "skipped": True, "reason": None}

    port = radio_config.get("programmer_port")
    if not port:
        # No cable port chosen; assume the radio was already programmed by hand rather than blocking Direwolf.
        return {"ok": True, "skipped": True, "reason": None}

    try:
        image = driver.build_image(radio_config)
        await asyncio.get_event_loop().run_in_executor(None, driver.program_sync, port, image)
    except (IOError, OSError) as e:
        logger.error("Radio programming failed: %s", e)
        return {"ok": False, "skipped": False, "reason": str(e)}

    logger.info("Programmed %s channel 0 via %s", model, port)
    return {"ok": True, "skipped": False, "reason": None}
