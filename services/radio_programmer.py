"""Programs the radio's active channel over a per-model serial protocol before Direwolf starts."""

import logging

logger = logging.getLogger(__name__)

# Radio models known to support channel programming, and their protocol.
RADIO_CAPABILITIES = {
    "Alinco DR-138T": {"can_program": True, "protocol": "alinco_erw4"},
}

# Settle time after programming before Direwolf starts using the radio.
PROGRAM_SETTLE_DELAY_S = 5


def can_program(model: str | None) -> bool:
    return RADIO_CAPABILITIES.get(model or "", {}).get("can_program", False)


async def program_channel(radio_config: dict) -> dict:
    """Placeholder; doesn't touch hardware yet. Returns {"ok": True, "skipped": bool, "reason": None}."""
    model = radio_config.get("model")
    if not can_program(model):
        return {"ok": True, "skipped": True, "reason": None}
    logger.info("Programming radio channel for %s (not yet implemented, no-op)", model)
    return {"ok": True, "skipped": False, "reason": None}
