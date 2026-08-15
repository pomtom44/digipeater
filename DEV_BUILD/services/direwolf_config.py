"""Generates direwolf.conf from config.yaml.

This is the piece TODO.md has called "the big one" all session: every other
"collected but not applied" item downstream of it. Directive syntax here
was verified against Direwolf's actual config-file parser
(github.com/wb2osz/direwolf, src/config.c), not just its sample config or
ORIGINAL's own generator (ORIGINAL/core/config_gen.py): a few things
ORIGINAL did turned out to be wrong or incomplete when checked against the
real parser, called out inline below where it matters. Not verified
against the real `direwolf` binary itself: this sandbox can't run Linux
binaries (same limitation as services/tiles.py's pmtiles handling), so the
generator's output has only been checked for well-formed, self-consistent
directive syntax against the parser source, not by actually feeding it to
Direwolf. Worth confirming on real hardware.

Written to a plain file in the app's own working directory (not
/etc/direwolf/, unlike ORIGINAL): the app already owns that directory, so
no root/sudo is needed just to write a config file, only to actually
start/stop the direwolf systemd service itself (see services/system.py).
"""

from pathlib import Path

CONFIG_PATH = Path("direwolf.conf")


def _mycall(aprs: dict) -> str:
    callsign = (aprs.get("callsign") or "NOCALL").upper()
    ssid = aprs.get("ssid")
    return f"{callsign}-{ssid}" if ssid else callsign


def _ptt_lines(radio: dict, can_transmit: bool) -> list[str]:
    if not can_transmit:
        return []
    method = radio.get("ptt_method", "vox")
    if method == "vox":
        # Not a real Direwolf directive (confirmed against config.c's PTT
        # parser: GPIO/GPIOD/LPT/RIG/CM108 and a serial-port form are the
        # only recognized cases, no VOX keyword exists at all). VOX means
        # the radio's own hardware keys up off the audio tone by itself;
        # Direwolf needs no PTT line whatsoever for that to work. ORIGINAL
        # emitted a "PTT VOX" line that isn't valid syntax, worth noting
        # since it's exactly the kind of thing this rewrite double-checked
        # against the real parser rather than assuming prior art was right.
        return []
    if method == "gpio":
        pin = radio.get("ptt_gpio_pin", 22)
        return [f"PTT GPIO {pin}"]
    if method == "cm108":
        return ["PTT CM108"]
    if method.startswith("cm108:"):
        return [f"PTT CM108 {method[len('cm108:'):]}"]
    if method.startswith("serial:"):
        # Direwolf needs to know which serial control line actually keys
        # PTT: RTS or DTR, picked on the Radio tab (radio.ptt_serial_line),
        # defaulting to RTS (the more common of the two for a simple PTT
        # interface) for configs saved before that field existed.
        line = radio.get("ptt_serial_line") or "RTS"
        return [f"PTT {method[len('serial:'):]} {line}"]
    return []


def _digipeat_lines(aprs: dict) -> list[str]:
    digipeat = aprs.get("digipeat") or {}
    alias = digipeat.get("alias") or "^WIDE[3-7]-[1-7]$|^TEST$"
    wide = digipeat.get("wide") or "^WIDE[12]-[12]$"
    lines = [f"DIGIPEAT 0 0 {alias} {wide}"]
    dedupe = digipeat.get("dedupe")
    if dedupe:
        lines.append(f"DEDUPE {dedupe}")
    rf_filter = (digipeat.get("filter") or "").strip()
    if rf_filter:
        lines.append(f"FILTER 0 0 {rf_filter}")
    return lines


def _igate_lines(aprs: dict) -> list[str]:
    igate = aprs.get("igate") or {}
    igate_mode = aprs.get("igate_mode", "off")
    server = igate.get("server") or "rotate.aprs2.net"
    port = igate.get("port") or 14580
    passcode = igate.get("passcode") or ""
    lines = [
        f"IGSERVER {server}:{port}",
        # Login callsign includes the SSID (matches Direwolf's own sample:
        # "IGLOGIN WB2OSZ-5 123456"), not bare callsign like ORIGINAL used.
        # The passcode itself is still only ever computed from the base
        # callsign (see services/aprs.py), that part ORIGINAL had right.
        f"IGLOGIN {_mycall(aprs)} {passcode}",
    ]
    server_filter = (igate.get("filter") or "").strip()
    if server_filter:
        lines.append(f"IGFILTER {server_filter}")
    gate_filter = (igate.get("gate_filter") or "").strip()
    if gate_filter:
        lines.append(f"FILTER 0 IG {gate_filter}")
    if igate_mode == "rxtx":
        tx_via = igate.get("tx_via") or "WIDE1-1,WIDE2-1"
        lines.append(f"IGTXVIA 0 {tx_via}")
    rate_1min = igate.get("rate_limit_1min")
    rate_5min = igate.get("rate_limit_5min")
    if rate_1min and rate_5min:
        lines.append(f"IGTXLIMIT {rate_1min} {rate_5min}")
    return lines


def _symbol_tokens(aprs: dict) -> tuple[str, str]:
    """Returns (OVERLAY= token or '', SYMBOL= token). Confirmed against
    config.c's beacon_options(): SYMBOL takes either a 2-character
    table+symbol code (e.g. "/#") or a name to look up via `direwolf -S`:
    the 2-character form is what the wizard's symbol picker already
    produces directly, no name-lookup table needed on this end. When an
    overlay is set, Direwolf takes the table from OVERLAY instead of
    SYMBOL's first character, but still wants a 2-character SYMBOL value
    (table char is then ignored); passing the same table+symbol pair
    either way is simplest and correct in both cases."""
    symbol = aprs.get("symbol") or {}
    table = symbol.get("table") or "/"
    char = symbol.get("symbol") or "#"
    overlay = symbol.get("overlay") or ""
    overlay_token = f"OVERLAY={overlay} " if overlay else ""
    return overlay_token, f"SYMBOL={table}{char}"


def _beacon_position(gps: dict) -> str:
    """LAT=/LONG= tokens for a fixed position, or '' when the beacon
    should get its position from gpsd instead (see _needs_gpsd). Plain
    signed decimal degrees: confirmed against config.c's parse_ll(),
    which accepts that directly (Direwolf's own sample config uses
    exactly this form: "lat=43.077104 long=-79.075674"), not the
    DDMM.MM-with-hemisphere-letter format ORIGINAL converted to. No
    conversion needed at all: config.yaml already stores plain decimal
    degrees regardless of which format the wizard's GPS step used to
    collect them (see first_run.html's coordinate-format dropdown)."""
    if gps.get("position_source") != "manual":
        return ""
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
    comment = aprs.get("comment") or ""
    tokens.append(f'COMMENT="{comment}"')
    return " ".join(t for t in tokens if t)


def generate(config: dict) -> str:
    """Pure function: parsed config.yaml -> direwolf.conf text. No I/O."""
    aprs = config.get("aprs") or {}
    radio = config.get("radio") or {}
    gps = config.get("gps") or {}

    digipeat_mode = aprs.get("digipeat_mode", "rxonly")
    igate_mode = aprs.get("igate_mode", "off")
    is_digipeater = digipeat_mode == "digipeater"
    igate_on = igate_mode != "off"
    # Whether this station transmits on RF at all: drives whether a PTT
    # line is needed. IGate RX-only never keys the radio (SENDTO=IG
    # bypasses RF entirely); IGate RX&TX does, to relay internet messages
    # back onto RF via IGTXVIA.
    can_transmit = is_digipeater or igate_mode == "rxtx"

    rf_beacon = aprs.get("rf_beacon") or {}
    igate_beacon = aprs.get("igate_beacon") or {}
    # RF Beacon is only ever collected when digipeat_mode is "digipeater"
    # (the wizard disables the checkbox otherwise, see first_run.html's
    # updateModeVisibility), checking is_digipeater here too rather than
    # trusting rf_beacon.enabled alone protects against a stale value left
    # over from switching digipeat_mode back to rxonly after enabling it.
    rf_beacon_on = is_digipeater and bool(rf_beacon.get("enabled"))
    igate_beacon_on = igate_on and bool(igate_beacon.get("enabled"))
    needs_gpsd = gps.get("position_source") == "gps" and (rf_beacon_on or igate_beacon_on)

    lines = [
        "# direwolf.conf: generated by the APRS Digipeater web UI.",
        "# Regenerated on every boot from config.yaml: manual edits here will be lost.",
        "",
    ]

    audio_device = radio.get("audio_device")
    if audio_device and audio_device != "default":
        lines.append(f"ADEVICE {audio_device}")
    lines.append("CHANNEL 0")
    lines.append(f"MYCALL {_mycall(aprs)}")
    lines.append("MODEM 1200")
    lines.append("")

    ptt_lines = _ptt_lines(radio, can_transmit)
    if ptt_lines:
        lines.extend(ptt_lines)
        lines.append("")

    if needs_gpsd:
        lines.append("GPSD")
        lines.append("")

    if is_digipeater:
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


def write(config: dict, path: Path = CONFIG_PATH) -> None:
    path.write_text(generate(config))
