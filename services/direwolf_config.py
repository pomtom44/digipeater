"""Generates direwolf.conf from config.yaml."""

import re
from pathlib import Path

from services import gps as gps_service

CONFIG_PATH = Path("direwolf.conf")


def _mycall(aprs: dict) -> str:
    callsign = (aprs.get("callsign") or "NOCALL").upper()
    ssid = aprs.get("ssid")
    return f"{callsign}-{ssid}" if ssid else callsign


# Direwolf's TXDELAY is in 10ms units. VOX needs much longer than hardware PTT (GPIO/CM108/serial):
# the radio has to sense the audio and trip its own VOX circuit before it's actually transmitting,
# and 300ms often isn't enough -- the first part of the packet goes out before the radio's keyed up.
_TXDELAY_DEFAULT_MS = {"vox": 600}
_TXDELAY_FALLBACK_MS = 300


def _txdelay_line(radio: dict, can_transmit: bool) -> str | None:
    if not can_transmit:
        return None
    ms = (radio.get("advanced") or {}).get("txdelay_ms")
    if not ms:
        ms = _TXDELAY_DEFAULT_MS.get(radio.get("ptt_method", "vox"), _TXDELAY_FALLBACK_MS)
    return f"TXDELAY {round(ms / 10)}"


def _ptt_lines(radio: dict, can_transmit: bool) -> list[str]:
    if not can_transmit:
        return []
    method = radio.get("ptt_method", "vox")
    if method == "vox":
        # VOX: the radio keys up on its own from audio, no PTT line needed (no VOX directive exists).
        return []
    if method == "gpio":
        # Uses GPIOD, the GPIO interface current Raspberry Pi OS kernels provide (the older sysfs
        # directive stopped working on them).
        pin = radio.get("ptt_gpio_pin", 22)
        return [f"PTT GPIOD gpiochip0 {pin}"]
    if method == "cm108":
        return ["PTT CM108"]
    if method.startswith("cm108:"):
        return [f"PTT CM108 {method[len('cm108:'):]}"]
    if method.startswith("serial:"):
        # Serial PTT control line (RTS or DTR); defaults to RTS.
        line = radio.get("ptt_serial_line") or "RTS"
        return [f"PTT {method[len('serial:'):]} {line}"]
    return []


def _callsign_filter_expr(pattern_str: str) -> str:
    """Converts comma/space-separated callsign patterns into a Direwolf budlist filter expression."""
    patterns = [p.strip().upper() for p in re.split(r"[,\s]+", pattern_str) if p.strip()]
    if not patterns:
        return ""
    return "b/" + "/".join(patterns)


def _combine_filters(*parts: str) -> str:
    """Combines multiple filter expressions with AND so none silently overrides the other."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " & ".join(f"({p})" for p in parts)


def _digipeat_lines(aprs: dict) -> list[str]:
    digipeat = aprs.get("digipeat") or {}
    alias = digipeat.get("alias") or "^WIDE[3-7]-[1-7]$|^TEST$"
    wide = digipeat.get("wide") or "^WIDE[12]-[12]$"
    lines = [f"DIGIPEAT 0 0 {alias} {wide}"]
    dedupe = digipeat.get("dedupe")
    if dedupe:
        lines.append(f"DEDUPE {dedupe}")
    rf_filter = (digipeat.get("filter") or "").strip()
    callsign_filter = _callsign_filter_expr(digipeat.get("callsign_filter") or "")
    combined = _combine_filters(rf_filter, callsign_filter)
    if combined:
        lines.append(f"FILTER 0 0 {combined}")
    return lines


def _igate_lines(aprs: dict) -> list[str]:
    igate = aprs.get("igate") or {}
    igate_mode = aprs.get("igate_mode", "off")
    server = igate.get("server") or "rotate.aprs2.net"
    port = igate.get("port") or 14580
    passcode = igate.get("passcode") or ""
    lines = [
        f"IGSERVER {server}:{port}",
        # IGLOGIN uses callsign+SSID; the passcode is computed from the base callsign only.
        f"IGLOGIN {_mycall(aprs)} {passcode}",
    ]
    server_filter = (igate.get("filter") or "").strip()
    if server_filter:
        lines.append(f"IGFILTER {server_filter}")
    gate_filter = (igate.get("gate_filter") or "").strip()
    callsign_filter = _callsign_filter_expr(igate.get("callsign_filter") or "")
    combined = _combine_filters(gate_filter, callsign_filter)
    if combined:
        lines.append(f"FILTER 0 IG {combined}")
    if igate_mode == "rxtx":
        tx_via = igate.get("tx_via") or "WIDE1-1,WIDE2-1"
        lines.append(f"IGTXVIA 0 {tx_via}")
    rate_1min = igate.get("rate_limit_1min")
    rate_5min = igate.get("rate_limit_5min")
    if rate_1min and rate_5min:
        lines.append(f"IGTXLIMIT {rate_1min} {rate_5min}")
    return lines


def _symbol_tokens(aprs: dict) -> tuple[str, str]:
    """Returns (OVERLAY= token or '', SYMBOL= token) for the beacon's symbol."""
    symbol = aprs.get("symbol") or {}
    table = symbol.get("table") or "/"
    char = symbol.get("symbol") or "#"
    overlay = symbol.get("overlay") or ""
    overlay_token = f"OVERLAY={overlay} " if overlay else ""
    return overlay_token, f"SYMBOL={table}{char}"


def _beacon_position(gps: dict) -> str:
    """Returns LAT=/LONG= tokens from whatever coordinates are on hand -- manually entered, or
    resolved from a live GPS fix by resolve_gps_position() before this ever gets called. This
    station doesn't move, so PBEACON with a static position is all it ever needs; direwolf's own
    GPSD-sourced TBEACON was dropped because its gpsd client hits the same bugs as everyone
    else's (startup race, and gpsd/u-blox combos that report a zeroed lat/lon despite a real fix)."""
    lat = gps.get("latitude")
    lon = gps.get("longitude")
    if lat in (None, "") or lon in (None, ""):
        return ""
    return f"LAT={lat} LONG={lon} "


def _pbeacon_line(beacon: dict, aprs: dict, gps: dict, *, send_to_igate: bool) -> str:
    overlay_token, symbol_token = _symbol_tokens(aprs)
    tokens = [
        "PBEACON",
        "SENDTO=IG" if send_to_igate else None,
        f"DELAY={beacon.get('delay', 1)}",
        f"EVERY={beacon.get('interval', 30)}",
        overlay_token.strip() or None,
        symbol_token,
        _beacon_position(gps).strip() or None,
    ]
    phg = beacon.get("phg") or {}
    if phg.get("power"):
        tokens.append(f"POWER={phg['power']}")
    if phg.get("height"):
        tokens.append(f"HEIGHT={phg['height']}")
    if phg.get("gain"):
        tokens.append(f"GAIN={phg['gain']}")
    path = beacon.get("path")
    if path:
        tokens.append(f"VIA={path}")
    # Direwolf's config parser has no quote-escaping, so a literal " would break this token.
    comment = (aprs.get("comment") or "").replace('"', "'")
    tokens.append(f'COMMENT="{comment}"')
    return " ".join(t for t in tokens if t)


def generate(config: dict, *, test_only: bool = False) -> str:
    """Pure function: parsed config.yaml -> direwolf.conf text. No I/O.

    test_only suppresses digipeating and beaconing (but keeps MYCALL/PTT/KISS as configured) --
    used for the signal test's own transient Direwolf start, so it can TX/RX a single test packet
    without also digipeating other stations' real traffic during the test window.
    """
    aprs = config.get("aprs") or {}
    radio = config.get("radio") or {}
    gps = config.get("gps") or {}

    digipeat_mode = aprs.get("digipeat_mode", "rxonly")
    igate_mode = aprs.get("igate_mode", "off")
    is_digipeater = digipeat_mode == "digipeater"
    igate_on = igate_mode != "off"
    # Whether this station transmits on RF at all (drives whether a PTT line is needed); unaffected
    # by test_only so the signal test can still key up to send its own packet.
    can_transmit = is_digipeater or igate_mode == "rxtx"
    digipeat_active = is_digipeater and not test_only

    rf_beacon = aprs.get("rf_beacon") or {}
    igate_beacon = aprs.get("igate_beacon") or {}
    # Guard against a stale rf_beacon.enabled left over from switching digipeat_mode.
    rf_beacon_on = digipeat_active and bool(rf_beacon.get("enabled"))
    igate_beacon_on = igate_on and bool(igate_beacon.get("enabled")) and not test_only

    lines = [
        "# direwolf.conf: generated by the APRS Digipeater web UI.",
        "# Regenerated on every boot from config.yaml: manual edits here will be lost.",
    ]
    if test_only:
        lines.append("# TEMPORARY: signal-test-only config (digipeating/beaconing disabled); restored after the test.")
    lines.append("")

    audio_device = radio.get("audio_device")
    if audio_device and audio_device != "default":
        lines.append(f"ADEVICE {audio_device}")
    lines.append("CHANNEL 0")
    lines.append(f"MYCALL {_mycall(aprs)}")
    lines.append("MODEM 1200")
    txdelay_line = _txdelay_line(radio, can_transmit)
    if txdelay_line:
        lines.append(txdelay_line)
    # KISS port for packet_log.py to decode heard packets; always on regardless of mode.
    lines.append("KISSPORT 8001")
    lines.append("")

    ptt_lines = _ptt_lines(radio, can_transmit)
    if ptt_lines:
        lines.extend(ptt_lines)
        lines.append("")

    if digipeat_active:
        lines.extend(_digipeat_lines(aprs))
        lines.append("")

    if igate_on:
        lines.extend(_igate_lines(aprs))
        lines.append("")

    if rf_beacon_on:
        lines.append(_pbeacon_line(rf_beacon, aprs, gps, send_to_igate=False))
        lines.append("")

    if igate_beacon_on:
        lines.append(_pbeacon_line(igate_beacon, aprs, gps, send_to_igate=True))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write(config: dict, path: Path = CONFIG_PATH, *, test_only: bool = False) -> None:
    path.write_text(generate(config, test_only=test_only))


async def resolve_gps_position(config: dict) -> dict:
    """Returns config with gps.latitude/longitude snapshotted from the current GPS fix, when
    position_source is "gps". This station is stationary, so a fix taken once -- right before
    direwolf.conf is (re)written -- is all PBEACON needs; it also sidesteps every gpsd-related
    beacon bug (startup race, zeroed lat/lon on some receivers) since direwolf never has to talk
    to gpsd itself for this. If there's no fix yet, config is returned unchanged -- generate()
    then simply omits LAT=/LONG=, so direwolf reports the real "position missing" error rather
    than silently beaconing a stale or wrong position."""
    gps_cfg = config.get("gps") or {}
    if gps_cfg.get("position_source") != "gps":
        return config
    status = await gps_service.get_status()
    if not status.get("has_fix"):
        return config
    resolved = dict(config)
    resolved["gps"] = {**gps_cfg, "latitude": status["latitude"], "longitude": status["longitude"]}
    return resolved


async def write_live(config: dict, path: Path = CONFIG_PATH, *, test_only: bool = False) -> None:
    """write(), but first resolves a live GPS position into static coordinates -- use this at
    every call site instead of write() directly, so gps-mode beacons always get a real position."""
    write(await resolve_gps_position(config), path, test_only=test_only)
