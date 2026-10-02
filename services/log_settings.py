"""Which database log types are enabled, cached in memory and refreshed whenever config.yaml's
"logging" section changes (applied the same way as services/gpsconfig.py, restart_policy.py, etc).
Lets someone who just wants a digipeater, no history, turn off the log types they don't want -- the
capture itself is skipped, not just the DB write, so a disabled type's live features go with it."""

# key -> (default enabled, whether a live feature depends on the live-tracked state itself, not just
# its history -- surfaced by the frontend/API as "disabled because logging is off" rather than "empty").
LOG_TYPES: dict[str, dict] = {
    "heard_stations": {
        "label": "Heard stations",
        "depends": "Dashboard's heard-stations list and map markers, and the e-ink \"last heard\" page.",
    },
    "sent_packets": {
        "label": "Sent packets (digipeats, beacons, IGate gates, messages)",
        "depends": "Dashboard's beacon-stats card (last RF/IGate beacon sent) reads this table directly, not a separate live counter.",
    },
    "direwolf_events": {
        "label": "Direwolf start/stop history",
        "depends": None,
    },
    "radio_write_events": {
        "label": "Radio programming history",
        "depends": None,
    },
    "config_changes": {
        "label": "Config change history",
        "depends": None,
    },
    "gps_fix_events": {
        "label": "GPS fix history",
        "depends": None,
    },
    "signal_test_results": {
        "label": "Signal test history",
        "depends": "The signal test itself: a pending test's state lives in this table now, so the Signal Test tab is unusable while this is off, not just its history.",
    },
    "system_events": {
        "label": "System events (reboots, radio relay power)",
        "depends": None,
    },
}

_enabled: dict[str, bool] = {key: True for key in LOG_TYPES}
# 0 = no limit, for either. Age defaults to a real limit (90 days) rather than "keep everything
# forever" -- a size limit almost never ends up mattering (even a busy station's 30-day traffic is
# only a rough 5-10 MB), so that one defaults off.
DEFAULT_RETENTION_DAYS = 90
DEFAULT_RETENTION_SIZE_MB = 0
_retention_days: float = DEFAULT_RETENTION_DAYS
_retention_size_mb: float = DEFAULT_RETENTION_SIZE_MB


def apply(logging_config: dict | None) -> None:
    global _enabled, _retention_days, _retention_size_mb
    logging_config = logging_config or {}
    _enabled = {key: bool(logging_config.get(key, True)) for key in LOG_TYPES}
    # Distinguish "key absent" (use the default) from "explicitly 0" (disabled) -- `or` would
    # collapse an explicit 0 back into the default since 0 is falsy.
    raw_days = logging_config.get("retention_days")
    _retention_days = float(raw_days) if raw_days is not None else DEFAULT_RETENTION_DAYS
    raw_size = logging_config.get("retention_size_mb")
    _retention_size_mb = float(raw_size) if raw_size is not None else DEFAULT_RETENTION_SIZE_MB


def is_enabled(log_type: str) -> bool:
    return _enabled.get(log_type, True)


def current() -> dict[str, bool]:
    return dict(_enabled)


def retention() -> tuple[float, float]:
    """(max_age_days, max_size_mb), each 0 meaning no limit."""
    return _retention_days, _retention_size_mb
