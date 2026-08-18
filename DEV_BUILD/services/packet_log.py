"""Tracks heard stations and beacon transmissions in real time, so the
dashboard's Heard stations/Beacon stats cards and the e-ink Last beacon/
Last heard pages show real data instead of placeholders.

Two independent live sources feed the same in-memory state, for different
reasons:

- Heard-station decoding comes from Direwolf's KISS TCP port (see
  services/direwolf_config.py's unconditional `KISSPORT 8001`, loopback
  only, this app is its one and only client): real raw AX.25 frames, not
  text scraped from a log line, so it doesn't depend on Direwolf's log
  wording at all, more of a "real" packet capture than parsing a
  human-readable rendering of one.
- Beacon-transmission timing still comes from tailing Direwolf's journald
  output (`journalctl -u direwolf -f`, the DEV_BUILD equivalent of
  ORIGINAL/core/log_parser.py reading Direwolf's stdout live off a
  subprocess it supervised directly): "sent to APRS-IS" isn't an RF frame
  at all, so it never appears over KISS, and there's no other live signal
  for exactly when a PBEACON fired. The RF/IGate beacon detection regexes
  here are carried over verbatim from ORIGINAL, which verified them
  against a real running station; not re-verified here yet (no working
  audio device in hand this session, see SUPPORTED_HARDWARE.md and
  TODO.md).

Both paths converge on the same aprslib-based APRS payload parsing
(_handle_packet_string): KISS decodes an AX.25 frame into a TNC2-style
"SRC>DEST,PATH:payload" string first (_decode_ax25_ui_frame), then it's
handed to aprslib exactly the same as a payload found directly in a log
line would be, one interpretation path either way.

State is in-memory only, not persisted to disk: this is "what's been heard
since the app last started", not a permanent packet archive, and a station
worth caring about will be heard again within its own beacon interval
anyway. Same trade-off web/server.py's session dict already makes.
"""

import asyncio
import logging
import re
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

try:
    import aprslib
    _HAS_APRSLIB = True
except ImportError:
    _HAS_APRSLIB = False
    logger.warning("aprslib not installed, heard-station/beacon tracking disabled")

CONFIG_PATH = Path("config.yaml")
_DIREWOLF_UNIT = "direwolf"

_RE_RF_BEACON = re.compile(r"(?:Transmitting|Sending).*?beacon", re.IGNORECASE)
_RE_IG_BEACON = re.compile(r"Sending\s+to\s+(?:IS|APRS-IS)", re.IGNORECASE)

_MAX_HEARD_STATIONS = 50
# How long to wait before reconnecting journalctl/KISS if either drops
# (journald restarting, or Direwolf itself not up yet/mid-restart); on a
# dev box with no systemd/Direwolf at all, this just backs off to
# effectively "don't busy-loop" once the immediate connect attempt fails.
_JOURNALCTL_RECONNECT_DELAY_S = 5
_KISS_RECONNECT_DELAY_S = 5

# Loopback only, matches services/direwolf_config.py's unconditional
# `KISSPORT 8001`.
_KISS_HOST = "127.0.0.1"
_KISS_PORT = 8001
_KISS_FEND = 0xC0
_KISS_FESC = 0xDB
_KISS_TFEND = 0xDC
_KISS_TFESC = 0xDD


def _my_callsign() -> str:
    if not CONFIG_PATH.exists():
        return ""
    try:
        config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception:
        return ""
    return ((config.get("aprs", {}) or {}).get("callsign") or "").upper()


def _kiss_unescape(data: bytes) -> bytes:
    """KISS byte-stuffing: FESC TFEND -> FEND, FESC TFESC -> FESC."""
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == _KISS_FESC and i + 1 < len(data):
            nxt = data[i + 1]
            if nxt == _KISS_TFEND:
                out.append(_KISS_FEND)
                i += 2
                continue
            if nxt == _KISS_TFESC:
                out.append(_KISS_FESC)
                i += 2
                continue
        out.append(b)
        i += 1
    return bytes(out)


def _decode_ax25_addr(data: bytes, offset: int) -> tuple[str, bool, bool]:
    """One 7-byte AX.25 address field. Each callsign character is ASCII
    shifted left 1 bit (space-padded to 6 chars); the 7th byte packs SSID
    (bits 1-4), the "has been repeated" digipeater flag (bit 7, shown as a
    trailing `*` in TNC2 format), and the address-extension bit (bit 0,
    set on the last address in the frame). Returns (callsign-ssid,
    has_been_repeated, is_last_address)."""
    callsign = "".join(chr(b >> 1) for b in data[offset:offset + 6]).strip()
    ssid_byte = data[offset + 6]
    ssid = (ssid_byte >> 1) & 0x0F
    has_been_repeated = bool(ssid_byte & 0x80)
    is_last = bool(ssid_byte & 0x01)
    call = f"{callsign}-{ssid}" if ssid else callsign
    return call, has_been_repeated, is_last


def _decode_ax25_ui_frame(frame: bytes) -> str | None:
    """Raw AX.25 UI frame bytes (as delivered over KISS, KISS command
    byte already stripped) -> a TNC2-style "SRC>DEST,PATH:payload"
    string, the exact shape aprslib.parse() expects, same interpretation
    path as a packet line found in Direwolf's own log text."""
    if len(frame) < 16:
        return None
    dest, _, _ = _decode_ax25_addr(frame, 0)
    source, _, is_last = _decode_ax25_addr(frame, 7)
    offset = 14
    path_parts = []
    while not is_last:
        if offset + 7 > len(frame):
            return None
        addr, repeated, is_last = _decode_ax25_addr(frame, offset)
        path_parts.append(addr + ("*" if repeated else ""))
        offset += 7
    if offset + 2 > len(frame):
        return None
    control, pid = frame[offset], frame[offset + 1]
    if control != 0x03 or pid != 0xF0:
        return None  # not a UI frame carrying an APRS-style payload
    info = frame[offset + 2:].decode("ascii", errors="replace")
    full_path = ",".join([dest] + path_parts)
    return f"{source}>{full_path}:{info}"


class PacketLog:
    def __init__(self):
        self._heard: dict[str, dict] = {}
        self._last_rf_beacon_at: float | None = None
        self._last_igate_beacon_at: float | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def heard_stations(self) -> list[dict]:
        """Every distinct heard callsign, most recent first."""
        now = time.time()
        stations = [
            {**info, "seconds_ago": round(now - info["_last_heard_at"])}
            for info in self._heard.values()
        ]
        stations.sort(key=lambda s: s["seconds_ago"])
        for s in stations:
            del s["_last_heard_at"]
        return stations[:_MAX_HEARD_STATIONS]

    def last_heard(self) -> dict | None:
        """The single most recently heard station, or None if nothing's
        been heard yet this run (see e-ink display/rotation.py's Last
        Heard page)."""
        if not self._heard:
            return None
        info = max(self._heard.values(), key=lambda s: s["_last_heard_at"])
        station = dict(info)
        station["seconds_ago"] = round(time.time() - station.pop("_last_heard_at"))
        return station

    def beacon_stats(self) -> dict:
        now = time.time()
        return {
            "last_rf_beacon_seconds_ago": round(now - self._last_rf_beacon_at) if self._last_rf_beacon_at else None,
            "last_igate_beacon_seconds_ago": (
                round(now - self._last_igate_beacon_at) if self._last_igate_beacon_at else None
            ),
        }

    async def _run(self) -> None:
        await asyncio.gather(self._journal_loop(), self._kiss_loop())

    async def _journal_loop(self) -> None:
        while True:
            try:
                await self._tail_journal()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Packet log journal tail failed: %s", e)
            await asyncio.sleep(_JOURNALCTL_RECONNECT_DELAY_S)

    async def _kiss_loop(self) -> None:
        while True:
            try:
                await self._tail_kiss()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Packet log KISS tail failed: %s", e)
            await asyncio.sleep(_KISS_RECONNECT_DELAY_S)

    async def _tail_journal(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-n", "journalctl", "-u", _DIREWOLF_UNIT, "-f", "-n", "0",
                "--no-pager", "-o", "cat",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # No systemctl/journalctl at all (dev sandbox, no systemd):
            # nothing to tail, and retrying every 5s forever would just be
            # log noise for a condition that will never change this run.
            await asyncio.sleep(3600)
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                self._handle_log_line(line.decode(errors="replace").rstrip())
        finally:
            if proc.returncode is None:
                proc.terminate()

    async def _tail_kiss(self) -> None:
        try:
            reader, writer = await asyncio.open_connection(_KISS_HOST, _KISS_PORT)
        except OSError:
            # Direwolf isn't listening yet: not started, still starting,
            # or (pre-boot dev sandbox) not running at all. Backed off and
            # retried by _kiss_loop above, not an error worth logging
            # every 5s.
            return
        my_call = _my_callsign()
        buf = bytearray()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                while _KISS_FEND in buf:
                    idx = buf.index(_KISS_FEND)
                    raw_frame = bytes(buf[:idx])
                    del buf[:idx + 1]
                    if not raw_frame:
                        continue  # KISS tolerates back-to-back FENDs
                    frame = _kiss_unescape(raw_frame)
                    if not frame or frame[0] != 0x00:
                        continue  # not a data frame on KISS port/channel 0
                    packet_str = _decode_ax25_ui_frame(frame[1:])
                    if packet_str:
                        self._handle_packet_string(packet_str, my_call)
        finally:
            writer.close()

    def _handle_log_line(self, line: str) -> None:
        """journalctl path: beacon-transmission detection only, see this
        module's own docstring for why heard-packet parsing moved to KISS
        instead."""
        if _RE_RF_BEACON.search(line):
            self._last_rf_beacon_at = time.time()
        elif _RE_IG_BEACON.search(line):
            self._last_igate_beacon_at = time.time()

    def _handle_packet_string(self, packet_str: str, my_call: str) -> None:
        """KISS path: packet_str is already a TNC2-style "SRC>DEST,PATH:
        payload" string (see _decode_ax25_ui_frame), same shape aprslib
        expects regardless of where it came from."""
        if not _HAS_APRSLIB:
            return
        try:
            parsed = aprslib.parse(packet_str)
        except Exception:
            return  # not everything heard is a decodable APRS packet
        callsign = parsed.get("from", "")
        if not callsign:
            return
        if my_call and callsign.split("-")[0].upper() == my_call.split("-")[0]:
            return  # our own transmission, not a heard station
        existing_count = self._heard.get(callsign, {}).get("count", 0)
        self._heard[callsign] = {
            "callsign": callsign,
            "symbol": {
                "table": parsed.get("symbol_table", "/"),
                "symbol": parsed.get("symbol", ">"),
            },
            "latitude": parsed.get("latitude"),
            "longitude": parsed.get("longitude"),
            "comment": parsed.get("comment", ""),
            "count": existing_count + 1,
            "_last_heard_at": time.time(),
        }
