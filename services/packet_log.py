"""Decodes heard stations and transmitted frames from Direwolf's KISS port and journald log, logging
them to the database (services/db.py) -- the only copy of this state, live reads included, not a
separate in-memory cache kept alongside it."""

import asyncio
import logging
import re
import time
from pathlib import Path

import yaml

from services import db, log_settings

logger = logging.getLogger(__name__)

try:
    import aprslib
    _HAS_APRSLIB = True
except ImportError:
    _HAS_APRSLIB = False
    logger.warning("aprslib not installed, heard-station/beacon tracking disabled")

CONFIG_PATH = Path("config.yaml")
_DIREWOLF_UNIT = "direwolf"

# Captures the full "SRC>PATH:payload" remainder, so every transmitted frame can be logged and
# classified, whichever callsign it goes out under.
_RE_RF_XMIT = re.compile(r"^\[\d[HL][^\]]*\]\s*([^>\s]+>.*)$")
_RE_IG_XMIT = re.compile(r"^\[ig\]\s*([^>\s]+>.*)$")

# Direwolf's own per-packet "heard" summary line (src/direwolf.c), printed right after a decoded
# packet unless started with "-q h". e.g. "N8VIM audio level = 27   [NONE]" or, when repeated through
# a WIDEn-0 alias, "WIDE2-1 (probably N3LEE-4) audio level = 28(10/6)   [NONE]   __|||||||". Only the
# callsign and the leading number matter here -- the rest (DCD state, retry/spectrum display) isn't
# used. When digipeated through a *named* repeater (distinct from a generic WIDEn alias), "heard"
# reports the repeater's own callsign; the original source is already logged separately via the KISS
# path. Correlation below won't find a row to match in that case, which is correct (attaching the
# repeater's signal level to the original station's row would misattribute it).
_RE_HEARD_LEVEL = re.compile(r"^(?:Digipeater )?(\S+)(?: \(probably (\S+)\))? audio level = (\d+)")
# How recent a heard_packets row must be to still accept a correlated signal level.
_HEARD_LEVEL_CORRELATION_WINDOW_S = 5

_MAX_HEARD_STATIONS = 50
_SIGNAL_TEST_TTL_S = 900
# Backoff before reconnecting journalctl/KISS after either drops.
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
    """Decodes one 7-byte AX.25 address field into (callsign-ssid, has_been_repeated, is_last_address)."""
    callsign = "".join(chr(b >> 1) for b in data[offset:offset + 6]).strip()
    ssid_byte = data[offset + 6]
    ssid = (ssid_byte >> 1) & 0x0F
    has_been_repeated = bool(ssid_byte & 0x80)
    is_last = bool(ssid_byte & 0x01)
    call = f"{callsign}-{ssid}" if ssid else callsign
    return call, has_been_repeated, is_last


def _decode_ax25_ui_frame(frame: bytes) -> str | None:
    """Converts raw AX.25 UI frame bytes into a TNC2-style "SRC>DEST,PATH:payload" string for aprslib."""
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
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def heard_stations(self) -> list[dict]:
        """Every distinct heard callsign, most recent first, straight from heard_packets."""
        rows = await db.fetchall(
            """
            SELECT h.callsign, h.heard_at, h.symbol_table, h.symbol, h.latitude, h.longitude,
                   h.comment, h.signal_level, agg.count
            FROM heard_packets h
            INNER JOIN (
                SELECT callsign, MAX(id) AS latest_id, COUNT(*) AS count
                FROM heard_packets
                GROUP BY callsign
            ) agg ON h.id = agg.latest_id
            ORDER BY h.heard_at DESC
            LIMIT ?
            """,
            (_MAX_HEARD_STATIONS,),
        )
        now = time.time()
        return [
            {
                "callsign": r["callsign"],
                "symbol": {"table": r["symbol_table"], "symbol": r["symbol"]},
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "comment": r["comment"],
                "signal_level": r["signal_level"],
                "count": r["count"],
                "seconds_ago": round(now - r["heard_at"]),
            }
            for r in rows
        ]

    async def last_heard(self) -> dict | None:
        """The single most recently heard station, or None if nothing's been heard yet."""
        row = await db.fetchone("SELECT * FROM heard_packets ORDER BY heard_at DESC, id DESC LIMIT 1")
        if row is None:
            return None
        return {
            "callsign": row["callsign"],
            "symbol": {"table": row["symbol_table"], "symbol": row["symbol"]},
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "comment": row["comment"],
            "signal_level": row["signal_level"],
            "seconds_ago": round(time.time() - row["heard_at"]),
        }

    async def start_signal_test(self, test_id: str, my_call: str, target_callsign: str) -> None:
        """Registers a pending RF-reach test in the database -- its only state now, not just
        incidental logging, so a failure here is raised rather than swallowed: the caller needs to
        know the test wasn't actually recorded, since nothing else is tracking it."""
        await db.execute(
            "INSERT INTO signal_test_results (test_id, started_at, my_call, target_callsign) VALUES (?, ?, ?, ?)",
            (test_id, time.time(), my_call, target_callsign),
        )

    async def signal_test_status(self, test_id: str) -> dict | None:
        row = await db.fetchone(
            "SELECT received, reply_text FROM signal_test_results WHERE test_id = ?", (test_id,),
        )
        if row is None:
            return None
        return {"received": bool(row["received"]), "reply_text": row["reply_text"]}

    async def _check_signal_test_reply(self, parsed: dict) -> None:
        # A far igate relaying a reply to RF may wrap it in third-party format; unwrap if so.
        message = parsed.get("subpacket", parsed) if parsed.get("format") == "thirdparty" else parsed
        if message.get("format") != "message":
            return
        addresse = (message.get("addresse") or "").strip().upper()
        text = message.get("message_text", "")
        if not addresse or not text:
            return
        # Bounds the query to recent pending tests only, same role the old in-memory TTL prune played.
        cutoff = time.time() - _SIGNAL_TEST_TTL_S
        pending = await db.fetchall(
            "SELECT test_id, my_call FROM signal_test_results WHERE received = 0 AND started_at > ?",
            (cutoff,),
        )
        for row in pending:
            if row["my_call"].upper() == addresse and row["test_id"] in text:
                try:
                    await db.execute(
                        "UPDATE signal_test_results SET received = 1, reply_text = ?, received_at = ? "
                        "WHERE test_id = ?",
                        (text, time.time(), row["test_id"]),
                    )
                except Exception as e:
                    logger.error("Failed to log signal test reply to database: %s", e)

    async def beacon_stats(self) -> dict:
        rf_row = await db.fetchone("SELECT MAX(sent_at) AS ts FROM sent_packets WHERE type = 'rf_beacon'")
        ig_row = await db.fetchone("SELECT MAX(sent_at) AS ts FROM sent_packets WHERE type = 'igate_beacon'")
        now = time.time()
        return {
            "last_rf_beacon_seconds_ago": round(now - rf_row["ts"]) if rf_row and rf_row["ts"] else None,
            "last_igate_beacon_seconds_ago": round(now - ig_row["ts"]) if ig_row and ig_row["ts"] else None,
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
            # No journalctl available; back off instead of retrying forever.
            await asyncio.sleep(3600)
            return
        my_call = _my_callsign()
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await self._handle_log_line(line.decode(errors="replace").rstrip(), my_call)
        finally:
            if proc.returncode is None:
                proc.terminate()

    async def _tail_kiss(self) -> None:
        try:
            reader, writer = await asyncio.open_connection(_KISS_HOST, _KISS_PORT)
        except OSError:
            # Direwolf's KISS port isn't listening yet; retried by _kiss_loop.
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
                        await self._handle_packet_string(packet_str, my_call)
        finally:
            writer.close()

    def _classify_tx(self, packet_text: str, is_own: bool, *, via_igate: bool) -> str:
        if via_igate:
            return "igate_beacon" if is_own else "igate_gate"
        if not is_own:
            return "digipeat"
        # Our own RF frame that isn't a position beacon is something we sent directly (e.g. the
        # signal test's ping message) rather than Direwolf's own PBEACON schedule.
        if _HAS_APRSLIB:
            try:
                if aprslib.parse(packet_text).get("format") == "message":
                    return "message"
            except Exception:
                pass
        return "rf_beacon"

    async def _correlate_heard_level(self, match: "re.Match") -> None:
        """Attaches Direwolf's own audio-level number to the heard_packets row the KISS path already
        logged for the same packet, matched by callsign within a short recency window. No match (a
        named-digipeater repeat, or the KISS decode never landing) just leaves signal_level NULL."""
        if not log_settings.is_enabled("heard_stations"):
            return
        heard_call = match.group(2) or match.group(1)
        level = int(match.group(3))
        cutoff = time.time() - _HEARD_LEVEL_CORRELATION_WINDOW_S
        try:
            await db.execute(
                """
                UPDATE heard_packets SET signal_level = ?
                WHERE id = (
                    SELECT id FROM heard_packets WHERE callsign = ? AND heard_at > ?
                    ORDER BY heard_at DESC LIMIT 1
                )
                """,
                (level, heard_call, cutoff),
            )
        except Exception as e:
            logger.error("Failed to correlate signal level for %s: %s", heard_call, e)

    async def _handle_log_line(self, line: str, my_call: str) -> None:
        """journalctl path: matches Direwolf's own TX log line for any frame it transmits -- a beacon,
        a DIGIPEAT repeat of someone else's packet, an RF packet gated to APRS-IS, or anything else
        handed to it, e.g. over KISS -- not just ones Direwolf happens to send under our own callsign.
        Also matches Direwolf's per-packet "heard" summary line, which carries its own audio level."""
        heard_match = _RE_HEARD_LEVEL.match(line)
        if heard_match:
            await self._correlate_heard_level(heard_match)
            return

        if not my_call:
            return
        call_root = my_call.split("-")[0].upper()

        via_igate = False
        m = _RE_RF_XMIT.match(line)
        if not m:
            m = _RE_IG_XMIT.match(line)
            via_igate = True
        if not m:
            return

        packet_text = m.group(1)
        source = packet_text.split(">", 1)[0]
        is_own = source.split("-")[0].upper() == call_root

        if not log_settings.is_enabled("sent_packets"):
            # Not just history: beacon_stats() now reads "last beacon sent" straight from this table,
            # so skipping the write is what makes that card show up as disabled too.
            return

        now = time.time()
        packet_type = self._classify_tx(packet_text, is_own, via_igate=via_igate)
        try:
            await db.execute(
                "INSERT INTO sent_packets (sent_at, type, callsign, raw_packet) VALUES (?, ?, ?, ?)",
                (now, packet_type, source, packet_text),
            )
        except Exception as e:
            logger.error("Failed to log sent packet to database: %s", e)

    async def _handle_packet_string(self, packet_str: str, my_call: str) -> None:
        """KISS path: parses a TNC2-style packet string via aprslib."""
        if not _HAS_APRSLIB:
            return
        try:
            parsed = aprslib.parse(packet_str)
        except Exception:
            return  # not everything heard is a decodable APRS packet

        await self._check_signal_test_reply(parsed)

        callsign = parsed.get("from", "")
        if not callsign:
            return
        if my_call and callsign.split("-")[0].upper() == my_call.split("-")[0]:
            return  # our own transmission, not a heard station
        if not log_settings.is_enabled("heard_stations"):
            # heard_stations()/last_heard() read straight from this table, so skipping the write here
            # disables the live list/map/e-ink page along with the history.
            return

        heard_at = time.time()
        symbol_table = parsed.get("symbol_table", "/")
        symbol = parsed.get("symbol", ">")
        latitude = parsed.get("latitude")
        longitude = parsed.get("longitude")
        comment = parsed.get("comment", "")

        try:
            await db.execute(
                "INSERT INTO heard_packets (callsign, heard_at, symbol_table, symbol, latitude, longitude, comment) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (callsign, heard_at, symbol_table, symbol, latitude, longitude, comment),
            )
        except Exception as e:
            logger.error("Failed to log heard station %s to database: %s", callsign, e)
