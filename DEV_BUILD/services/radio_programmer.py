"""Programs the radio's active channel (frequency/name) over a per-model
serial protocol, as part of every Direwolf start sequence (see
services/system.py's set_direwolf_running): GPS confirmed -> radio powered
on via services/relay.py -> channel programmed here -> a short settle
wait -> Direwolf actually starts.

Stub for now, at the caller's request: RADIO_CAPABILITIES below is real
and meant to stay accurate as radio models are added (flag a model
can_program: True only once its actual protocol is implemented here), but
program_channel() itself doesn't touch any hardware yet. The one existing
prior-art protocol is ORIGINAL/hardware/radio_programmer.py's Alinco
DR-138T implementation (ERW-4 cable, full memory read-modify-write,
protocol confirmed against a real capture, see that file's docstring):
not ported in yet, deliberately deferred. Wiring this stub in now, rather
than leaving the calling sequence to add later, means the real protocol
can just be dropped in here without reshaping set_direwolf_running.
"""

import logging

logger = logging.getLogger(__name__)

# Which radio models are known to support channel programming, and (once
# implemented) via which protocol. Add an entry here whenever a model's
# real protocol gets ported below; anything absent, including every model
# in first_run.html's current placeholder dropdown list, is treated as
# not programmable rather than guessed at.
RADIO_CAPABILITIES = {
    "Alinco DR-138T": {"can_program": True, "protocol": "alinco_erw4"},
}

# Settle time after programming, before Direwolf actually starts using the
# radio. Only meaningful once program_channel() does real serial I/O; an
# arbitrary placeholder for now, easy to tune once there's real hardware
# behavior to time against.
PROGRAM_SETTLE_DELAY_S = 5


def can_program(model: str | None) -> bool:
    return RADIO_CAPABILITIES.get(model or "", {}).get("can_program", False)


async def program_channel(radio_config: dict) -> dict:
    """Placeholder. Returns {"ok": True, "skipped": ..., "reason": None}
    without touching any hardware: skipped=True when the configured model
    isn't in RADIO_CAPABILITIES (the common case today, since no model's
    protocol is implemented yet), skipped=False (state "programming") when
    it is, so the caller's logging/timing already behaves correctly ahead
    of a real protocol landing here."""
    model = radio_config.get("model")
    if not can_program(model):
        return {"ok": True, "skipped": True, "reason": None}
    logger.info("Programming radio channel for %s (not yet implemented, no-op)", model)
    return {"ok": True, "skipped": False, "reason": None}
