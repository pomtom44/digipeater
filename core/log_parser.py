"""
Parses Direwolf stdout into simplified log entries and map events.

Uses aprslib as the primary packet parser (handles MIC-E, compressed,
timestamped, and standard formats). Falls back to regex for anything
aprslib can't handle.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import aprslib
    HAS_APRSLIB = True
except ImportError:
    HAS_APRSLIB = False


@dataclass
class LogEntry:
    timestamp: str
    level: str          # "info", "error", "raw"
    message: str


_WX_FIELDS = (
    "wind_speed", "wind_direction", "temperature", "humidity",
    "rain_1h", "rain_24h", "rain_midnight", "pressure", "luminosity", "snow",
)


@dataclass
class MapEvent:
    callsign: str
    latitude: Optional[float]
    longitude: Optional[float]
    timestamp: str
    packet_type: str        # "position", "object", "wx", etc.
    direct: bool            # heard directly (no digi hop)
    symbol_table: str = "/"
    symbol_code: str = ">"
    comment: str = ""
    path: str = ""
    raw: str = ""
    weather: dict = field(default_factory=dict)   # populated for wx packets


@dataclass
class StatusUpdate:
    """Parsed Direwolf status info — version, audio device, ready flags, APRS-IS state."""
    version: Optional[str] = None
    audio_device: Optional[str] = None
    agw_ready: bool = False
    kiss_ready: bool = False
    aprs_is_connected: Optional[bool] = None   # True = connected, False = disconnected, None = no change
    aprs_is_server: Optional[str] = None


# ── Log line timestamp (GPS time from Direwolf) ───────────────
# Format: [2025-12-11T01:26:35Z]
_RE_LOG_TS = re.compile(r"^\[([^\]]+Z?)\]")

# ── Direwolf packet line ──────────────────────────────────────
# [timestamp] [channel] source>path:data
_RE_PACKET_LINE = re.compile(r"\[([^\]]+)\]\s+([^>]+)>([^:]+):(.+)")

# ── Simplified output patterns ────────────────────────────────
_RE_DIGIPEAT = re.compile(r"Digipeating\s+([A-Z0-9]+-?\d*)\s+to\s+([A-Z0-9]+-?\d*)", re.IGNORECASE)
_RE_GATED = re.compile(r"(?:ig_send|igated|IGATE[^D])\s+([A-Z0-9]+-?\d*)", re.IGNORECASE)
_RE_RF_BEACON = re.compile(r"(?:Transmitting|Sending).*?beacon", re.IGNORECASE)
_RE_IG_BEACON = re.compile(r"Sending\s+to\s+(?:IS|APRS-IS)", re.IGNORECASE)
_RE_ERROR = re.compile(r"\b(ERROR|Error|error|FATAL|fatal|Warning|WARNING)\b")

# ── Direwolf status line patterns ─────────────────────────────
_RE_VERSION = re.compile(r"Dire Wolf Release ([\d.]+)")
_RE_AUDIO_DEV = re.compile(r"Audio device.*?:\s*(.+)")
_RE_AGW_READY = re.compile(r"Ready to accept.*AGW", re.IGNORECASE)
_RE_KISS_READY = re.compile(r"Ready to accept.*KISS", re.IGNORECASE)

# ── APRS-IS connection state ──────────────────────────────────
# Direwolf outputs these on connect/disconnect regardless of version
_RE_IS_CONNECT = re.compile(
    r"(?:Connected to APRS-IS|APRS-IS server.*connected|igate:.*connect)",
    re.IGNORECASE,
)
_RE_IS_SERVER = re.compile(
    r"(?:Connected to APRS-IS server|APRS-IS server)[,\s]+(\S+)",
    re.IGNORECASE,
)
_RE_IS_DISCONNECT = re.compile(
    r"(?:Lost connection|Disconnected from|igate:.*disconnect|APRS-IS.*lost|server disconnect)",
    re.IGNORECASE,
)

# ── Fallback position regex (standard + timestamped) ─────────
_RE_POS_STD = re.compile(
    r"[!=](\d{2})(\d{2}\.\d{2})([NS])([/\\])(\d{3})(\d{2}\.\d{2})([EW])(.)"
)
_RE_POS_TS = re.compile(
    r"@\d{6}[hz](\d{2})(\d{2}\.\d{2})([NS])([/\\])(\d{3})(\d{2}\.\d{2})([EW])(.)",
    re.IGNORECASE,
)


def parse_line(raw: str) -> tuple[Optional[LogEntry], Optional[MapEvent], Optional[StatusUpdate]]:
    """
    Parse one line of Direwolf stdout.
    Returns (LogEntry, MapEvent, StatusUpdate) — any can be None.
    """
    raw = raw.strip()
    if not raw:
        return None, None, None

    ts = _extract_log_timestamp(raw) or datetime.now().strftime("%H:%M:%S")

    # ── Direwolf status lines ─────────────────────────────────
    status = _parse_status(raw)
    if status:
        return LogEntry(ts, "raw", raw), None, status

    # ── Errors — always pass through in full ──────────────────
    if _RE_ERROR.search(raw):
        return LogEntry(ts, "error", raw), None, None

    # ── Digipeated ────────────────────────────────────────────
    m = _RE_DIGIPEAT.search(raw)
    if m:
        return LogEntry(ts, "info", f"Digipeated {m.group(1)} → {m.group(2)}"), None, None

    # ── Gated to APRS-IS ──────────────────────────────────────
    m = _RE_GATED.search(raw)
    if m:
        return LogEntry(ts, "info", f"Gated to APRS-IS — {m.group(1)}"), None, None

    # ── RF beacon ─────────────────────────────────────────────
    if _RE_RF_BEACON.search(raw):
        payload = _extract_payload(raw)
        return LogEntry(ts, "info", f"Beacon sent to RF — {payload}"), None, None

    # ── Igate beacon ──────────────────────────────────────────
    if _RE_IG_BEACON.search(raw):
        payload = _extract_payload(raw)
        return LogEntry(ts, "info", f"Beacon sent to APRS-IS — {payload}"), None, None

    # ── APRS packet line ──────────────────────────────────────
    map_event = _parse_packet(raw, ts)
    if map_event:
        has_pos = map_event.latitude is not None and map_event.longitude is not None
        coord = (f"{_fmt(map_event.latitude, 'NS')} {_fmt(map_event.longitude, 'EW')}"
                 if has_pos else "")
        if map_event.packet_type in ("wx", "weather") and map_event.weather:
            wx = map_event.weather
            temp_str = ""
            if wx.get("temperature") is not None:
                c = round((wx["temperature"] - 32) * 5 / 9, 1)
                temp_str = f" {c}°C"
            wind_str = ""
            if wx.get("wind_speed") is not None:
                kmh = round(wx["wind_speed"] * 1.852)
                wind_str = f" {kmh}km/h"
            msg = f"WX {map_event.callsign}{temp_str}{wind_str}" + (f" — {coord}" if coord else "")
        elif map_event.packet_type == "object":
            msg = f"Object {map_event.callsign}" + (f" — {coord}" if coord else "")
        else:
            msg = f"Heard {map_event.callsign}" + (f" — {coord}" if coord else "")
        entry = LogEntry(ts, "info", msg)
        return entry, map_event, None

    # ── Heard without parseable position ─────────────────────
    # Direwolf prints the raw AX.25 line even for non-position packets
    if ">" in raw and ":" in raw:
        callsign = raw.split(">")[0].strip().split()[-1]
        if callsign and re.match(r"[A-Z0-9]", callsign):
            path_part = raw.split(">", 1)[1].split(":")[0]
            event = MapEvent(
                callsign=callsign,
                latitude=None,
                longitude=None,
                timestamp=ts,
                packet_type="heard",
                direct="*" not in path_part,
                path=path_part,
                raw=raw,
            )
            return LogEntry(ts, "info", f"Heard {callsign}"), event, None

    # ── Unrecognised — pass through ───────────────────────────
    return LogEntry(ts, "raw", raw), None, None


def _parse_packet(raw: str, ts: str) -> Optional[MapEvent]:
    """Attempt to extract a MapEvent from a raw Direwolf output line."""
    # Direwolf packet lines contain source>path:data
    m = re.search(r"([A-Z0-9]+-?\d*)>([^:]+):(.+)", raw)
    if not m:
        return None

    source = m.group(1)
    path = m.group(2)
    data = m.group(3)
    direct = "*" not in path

    # ── Try aprslib first ─────────────────────────────────────
    if HAS_APRSLIB:
        try:
            packet_str = f"{source}>{path}:{data}"
            parsed = aprslib.parse(packet_str)
            if "latitude" in parsed and "longitude" in parsed:
                pkt_format = parsed.get("format", "position")
                full_call = parsed.get("from", source)

                # Object packets: identify by object name, not sender callsign
                if pkt_format == "object":
                    obj_name = parsed.get("object_name", "").strip()
                    if obj_name:
                        full_call = obj_name

                # Extract weather fields (all optional, aprslib uses F/knots/hPa)
                weather = {}
                if pkt_format in ("wx", "weather"):
                    for key in _WX_FIELDS:
                        val = parsed.get(key)
                        if val is not None:
                            weather[key] = val

                return MapEvent(
                    callsign=full_call,
                    latitude=round(parsed["latitude"], 6),
                    longitude=round(parsed["longitude"], 6),
                    timestamp=ts,
                    packet_type=pkt_format,
                    direct=direct,
                    symbol_table=parsed.get("symbol_table", "/"),
                    symbol_code=parsed.get("symbol", ">"),
                    comment=parsed.get("comment", ""),
                    path=path,
                    raw=data,
                    weather=weather,
                )
            else:
                # Non-position packet (message, status, telemetry, etc.) — store without coords
                return MapEvent(
                    callsign=parsed.get("from", source),
                    latitude=None,
                    longitude=None,
                    timestamp=ts,
                    packet_type=parsed.get("format", "unknown"),
                    direct=direct,
                    comment=parsed.get("comment", ""),
                    path=path,
                    raw=data,
                )
        except Exception:
            pass

    # ── Fallback: regex for standard and timestamped formats ──
    for pattern in (_RE_POS_TS, _RE_POS_STD):
        pm = pattern.search(data)
        if pm:
            try:
                lat = _nmea_to_decimal(pm.group(1), pm.group(2), pm.group(3))
                lon = _nmea_to_decimal(pm.group(5), pm.group(6), pm.group(7))
                symbol_table = pm.group(4)
                symbol_code = pm.group(8)
                comment = data[pm.end():].strip()
                comment = re.sub(r"^\d{3}/\d{3}\s*", "", comment)
                return MapEvent(
                    callsign=source,
                    latitude=lat,
                    longitude=lon,
                    timestamp=ts,
                    packet_type="position",
                    direct=direct,
                    symbol_table=symbol_table,
                    symbol_code=symbol_code,
                    comment=comment,
                    path=path,
                    raw=data,
                )
            except (ValueError, IndexError):
                continue

    return None


def _parse_status(raw: str) -> Optional[StatusUpdate]:
    s = StatusUpdate()
    changed = False
    m = _RE_VERSION.search(raw)
    if m:
        s.version = m.group(1)
        changed = True
    m = _RE_AUDIO_DEV.search(raw)
    if m:
        s.audio_device = m.group(1).strip()
        changed = True
    if _RE_AGW_READY.search(raw):
        s.agw_ready = True
        changed = True
    if _RE_KISS_READY.search(raw):
        s.kiss_ready = True
        changed = True
    if _RE_IS_CONNECT.search(raw):
        s.aprs_is_connected = True
        m = _RE_IS_SERVER.search(raw)
        if m:
            s.aprs_is_server = m.group(1).rstrip(",")
        changed = True
    elif _RE_IS_DISCONNECT.search(raw):
        s.aprs_is_connected = False
        changed = True
    return s if changed else None


def _extract_log_timestamp(raw: str) -> Optional[str]:
    """Pull GPS timestamp from a Direwolf log line if present."""
    m = _RE_LOG_TS.match(raw)
    if not m:
        return None
    ts_str = m.group(1).replace("Z", "+00:00")
    if "+" not in ts_str and ts_str.count("-") <= 2:
        ts_str += "+00:00"
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.strftime("%H:%M:%S")
    except ValueError:
        return None


def _extract_payload(raw: str) -> str:
    if ":" in raw:
        return raw.split(":", 1)[-1].strip()
    return raw


def _nmea_to_decimal(deg_str: str, min_str: str, hemi: str) -> float:
    deg = int(deg_str)
    mins = float(min_str)
    result = deg + mins / 60
    if hemi in ("S", "W"):
        result = -result
    return round(result, 6)


def _fmt(val: float, hemi_pair: str) -> str:
    hemi = hemi_pair[0] if val >= 0 else hemi_pair[1]
    return f"{abs(val):.4f}°{hemi}"
