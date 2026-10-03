"""SQLite connection, schema migrations, and async query helpers, shared by any service that needs
persistent storage (heard-station history, beacon log, etc, as those migrate off in-memory state)."""

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services import log_settings

logger = logging.getLogger(__name__)

DB_PATH = Path("digipeater.db")

# Ordered, one-way migrations: (version, [statements]). Add a new tuple to extend the schema, never
# edit a past one, an already-deployed database has already applied it.
_MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        # One row per decoded packet heard on RF (services/packet_log.py), not just current state, so
        # history survives a restart/crash and later queries (maps, stats) have more than a snapshot.
        """
        CREATE TABLE heard_packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            callsign TEXT NOT NULL,
            heard_at REAL NOT NULL,
            symbol_table TEXT,
            symbol TEXT,
            latitude REAL,
            longitude REAL,
            comment TEXT
        )
        """,
        "CREATE INDEX idx_heard_packets_callsign ON heard_packets (callsign)",
        "CREATE INDEX idx_heard_packets_heard_at ON heard_packets (heard_at)",
    ]),
    (2, [
        # One row per frame Direwolf actually transmits (services/packet_log.py's journald tail),
        # whatever triggered it: our own PBEACON (rf_beacon/igate_beacon), a DIGIPEAT repeat of someone
        # else's packet (digipeat), an RF packet gated to APRS-IS (igate_gate), or an outbound message
        # we sent ourselves e.g. the signal test ping (message). callsign is the frame's AX.25 source,
        # which for digipeat/igate_gate is the *original* station, not us.
        """
        CREATE TABLE sent_packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at REAL NOT NULL,
            type TEXT NOT NULL,
            callsign TEXT NOT NULL,
            raw_packet TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_sent_packets_callsign ON sent_packets (callsign)",
        "CREATE INDEX idx_sent_packets_sent_at ON sent_packets (sent_at)",
        "CREATE INDEX idx_sent_packets_type ON sent_packets (type)",
    ]),
    (3, [
        # Every Direwolf start/stop attempt (services/system.py's set_direwolf_running), success or
        # failure, so "why did it go down" is a query instead of journalctl archaeology.
        """
        CREATE TABLE direwolf_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            action TEXT NOT NULL,
            ok INTEGER NOT NULL,
            reason TEXT,
            simulated INTEGER NOT NULL
        )
        """,
        "CREATE INDEX idx_direwolf_events_at ON direwolf_events (at)",
    ]),
    (4, [
        # Every explicit "Write to radio" attempt (services/system.py's write_radio), including ones
        # that failed validation before touching hardware, e.g. no port selected.
        """
        CREATE TABLE radio_write_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            model TEXT,
            ok INTEGER NOT NULL,
            reason TEXT,
            was_running INTEGER NOT NULL
        )
        """,
        "CREATE INDEX idx_radio_write_events_at ON radio_write_events (at)",
    ]),
    (5, [
        # One row per changed top-level config section on each config page save (web/server.py's
        # config_save), before/after as JSON, so "what changed right before behavior changed" is a
        # query instead of a guess.
        """
        CREATE TABLE config_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            section TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT
        )
        """,
        "CREATE INDEX idx_config_changes_at ON config_changes (at)",
        "CREATE INDEX idx_config_changes_section ON config_changes (section)",
    ]),
    (6, [
        # One row per GPS fix wait outcome (services/system.py's _wait_for_gps_fix), each time a
        # Direwolf start attempt needed one. Not a continuous fix-quality log, just gate outcomes.
        """
        CREATE TABLE gps_fix_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            ok INTEGER NOT NULL,
            reason TEXT
        )
        """,
        "CREATE INDEX idx_gps_fix_events_at ON gps_fix_events (at)",
    ]),
    (7, [
        # One row per RF-reach signal test (services/signal_test.py, tracked live in
        # packet_log.py's _signal_tests), inserted on send and updated in place once/if a reply
        # arrives. test_id is already a unique token (secrets.token_hex) so it's the natural key.
        """
        CREATE TABLE signal_test_results (
            test_id TEXT PRIMARY KEY,
            started_at REAL NOT NULL,
            my_call TEXT NOT NULL,
            target_callsign TEXT NOT NULL,
            received INTEGER NOT NULL DEFAULT 0,
            reply_text TEXT,
            received_at REAL
        )
        """,
        "CREATE INDEX idx_signal_test_results_started_at ON signal_test_results (started_at)",
    ]),
    (8, [
        # Coarse one-off system events with no richer payload worth a dedicated table: reboots and
        # radio relay power toggles (services/system.py, services/relay.py).
        """
        CREATE TABLE system_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            type TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_system_events_at ON system_events (at)",
        "CREATE INDEX idx_system_events_type ON system_events (type)",
    ]),
    (9, [
        # Direwolf's own "audio level" for the packet, correlated in from its journald "heard" line
        # (services/packet_log.py) after the fact -- not available from the KISS-decoded packet
        # itself, which carries no signal-quality metadata. NULL when correlation didn't find a match
        # (e.g. a packet heard via a named digipeater rather than directly from the source).
        "ALTER TABLE heard_packets ADD COLUMN signal_level INTEGER",
    ]),
]

_connection: sqlite3.Connection | None = None
# Serializes access: sqlite3 connections aren't safe for concurrent use from multiple threads at once,
# and asyncio.to_thread() may run each call on a different worker thread.
_lock = asyncio.Lock()


def _connect(path: Path) -> sqlite3.Connection:
    # check_same_thread=False: to_thread() calls can land on any worker thread; _lock still ensures
    # only one of them touches the connection at a time.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = row["version"] if row else 0
    pending = [(version, statements) for version, statements in _MIGRATIONS if version > current]
    for version, statements in pending:
        for statement in statements:
            conn.execute(statement)
        current = version
    if pending:
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (current,))
        else:
            conn.execute("UPDATE schema_version SET version = ?", (current,))
        conn.commit()


def init(path: Path = DB_PATH) -> None:
    """Opens the database and applies any pending migrations. Safe to call more than once; only the
    first call does anything. Synchronous and cheap (local file, runs once at startup)."""
    global _connection
    if _connection is not None:
        return
    conn = _connect(path)
    _migrate(conn)
    _connection = conn
    logger.info("Database ready at %s (schema v%d)", path, current_schema_version())


def current_schema_version() -> int:
    return _MIGRATIONS[-1][0] if _MIGRATIONS else 0


def _require_connection() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("db.init() has not been called yet")
    return _connection


def _execute_sync(sql: str, params: tuple) -> None:
    conn = _require_connection()
    conn.execute(sql, params)
    conn.commit()


def _fetchone_sync(sql: str, params: tuple) -> sqlite3.Row | None:
    return _require_connection().execute(sql, params).fetchone()


def _fetchall_sync(sql: str, params: tuple) -> list[sqlite3.Row]:
    return _require_connection().execute(sql, params).fetchall()


def _run_sync(fn) -> None:
    conn = _require_connection()
    try:
        fn(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


async def execute(sql: str, params: tuple = ()) -> None:
    """Runs one INSERT/UPDATE/DELETE and commits it."""
    async with _lock:
        await asyncio.to_thread(_execute_sync, sql, params)


async def fetchone(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    async with _lock:
        return await asyncio.to_thread(_fetchone_sync, sql, params)


async def fetchall(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    async with _lock:
        return await asyncio.to_thread(_fetchall_sync, sql, params)


async def transaction(fn) -> None:
    """Runs fn(conn), a plain sqlite3.Connection, in the worker thread as a single commit/rollback.
    Use this instead of separate execute() calls when multiple statements must land atomically."""
    async with _lock:
        await asyncio.to_thread(_run_sync, fn)


# ── Retention: age and/or size limits, each independently optional (0 = no limit) ──────────────

# Every table with a timestamp column, pruned by age. The first two are also the only ones pruned by
# size -- they're the only ones with a per-packet write rate, so they're what actually drives growth;
# the other five are rare one-row-per-event audit tables where a size limit wouldn't do much.
_HIGH_VOLUME_TABLES = [("heard_packets", "heard_at"), ("sent_packets", "sent_at")]
_TABLES_WITH_TIMESTAMP = _HIGH_VOLUME_TABLES + [
    ("direwolf_events", "at"),
    ("radio_write_events", "at"),
    ("config_changes", "at"),
    ("gps_fix_events", "at"),
    ("signal_test_results", "started_at"),
    ("system_events", "at"),
]

_RETENTION_CHECK_INTERVAL_S = 600
_SIZE_PRUNE_BATCH = 500


def _prune_by_age_sync(conn: sqlite3.Connection, max_age_days: float) -> None:
    cutoff = time.time() - max_age_days * 86400
    for table, ts_col in _TABLES_WITH_TIMESTAMP:
        conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff,))


def _db_size_bytes(conn: sqlite3.Connection) -> int:
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return page_count * page_size


def _prune_by_size_sync(conn: sqlite3.Connection, max_size_bytes: int) -> None:
    """Deletes the oldest rows from whichever high-volume table has more, in one estimate-based pass
    (not a delete-then-recheck loop: page_count doesn't shrink until VACUUM, which is too expensive to
    run per batch). The estimate assumes uniform row size, so it can under- or overshoot a bit -- if
    still over budget, the next sweep (_RETENTION_CHECK_INTERVAL_S later) deletes more."""
    current_size = _db_size_bytes(conn)
    if current_size <= max_size_bytes:
        return
    total_rows = sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t, _ in _HIGH_VOLUME_TABLES)
    if total_rows == 0:
        return
    excess_fraction = 1 - (max_size_bytes / current_size)
    rows_to_delete = max(_SIZE_PRUNE_BATCH, int(total_rows * excess_fraction * 1.1))  # +10% margin

    deleted = 0
    while deleted < rows_to_delete:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table, _ in _HIGH_VOLUME_TABLES}
        table = max(counts, key=counts.get)
        if counts[table] == 0:
            break  # both high-volume tables empty; can't shrink further this way
        ts_col = dict(_HIGH_VOLUME_TABLES)[table]
        batch = min(_SIZE_PRUNE_BATCH, rows_to_delete - deleted, counts[table])
        conn.execute(
            f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} ORDER BY {ts_col} ASC LIMIT ?)",
            (batch,),
        )
        deleted += batch


def _apply_retention_sync(conn: sqlite3.Connection, max_age_days: float, max_size_mb: float) -> None:
    before_changes = conn.total_changes
    if max_age_days > 0:
        _prune_by_age_sync(conn, max_age_days)
    if max_size_mb > 0:
        _prune_by_size_sync(conn, max_size_mb * 1024 * 1024)
    if conn.total_changes > before_changes:
        # Deletes alone don't shrink the file (freed pages just go on sqlite's internal freelist);
        # VACUUM is what actually reclaims the disk space, so only run it when something changed.
        conn.commit()
        conn.execute("VACUUM")


async def apply_retention(max_age_days: float, max_size_mb: float) -> None:
    """Deletes rows older than max_age_days (all tables) and/or prunes heard_packets/sent_packets,
    oldest first, until under max_size_mb -- whichever limits are non-zero, both independently."""
    await transaction(lambda conn: _apply_retention_sync(conn, max_age_days, max_size_mb))


# services.log_settings.LOG_TYPES key -> table name; only "heard_stations" differs from its table
# (heard_packets), everything else matches its log type key exactly.
LOG_TYPE_TABLES: dict[str, str] = {
    "heard_stations": "heard_packets",
    "sent_packets": "sent_packets",
    "direwolf_events": "direwolf_events",
    "radio_write_events": "radio_write_events",
    "config_changes": "config_changes",
    "gps_fix_events": "gps_fix_events",
    "signal_test_results": "signal_test_results",
    "system_events": "system_events",
}


def _clear_table_sync(table: str) -> int:
    conn = _require_connection()
    conn.execute(f"DELETE FROM {table}")
    deleted = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    if deleted:
        conn.execute("VACUUM")
    return deleted


async def clear_log_type(log_type: str) -> int:
    """Deletes every row from the table behind this log type manually (the config page's per-type
    Clear button); returns how many rows were deleted. Raises ValueError for an unknown log_type --
    table names come only from LOG_TYPE_TABLES, never built from raw caller input."""
    table = LOG_TYPE_TABLES.get(log_type)
    if table is None:
        raise ValueError(f"Unknown log type: {log_type}")
    async with _lock:
        return await asyncio.to_thread(_clear_table_sync, table)


async def clear_all_logs() -> dict[str, int]:
    """Clears every log table (the config page's Clear all button). Returns {log_type: rows_deleted}."""
    return {log_type: await clear_log_type(log_type) for log_type in LOG_TYPE_TABLES}


# log_settings.LOG_TYPES key -> that type's timestamp column, within its own table.
LOG_TYPE_TIMESTAMP_COL: dict[str, str] = {
    "heard_stations": "heard_at",
    "sent_packets": "sent_at",
    "direwolf_events": "at",
    "radio_write_events": "at",
    "config_changes": "at",
    "gps_fix_events": "at",
    "signal_test_results": "started_at",
    "system_events": "at",
}


def _fetch_type_history_sync(conn: sqlite3.Connection, log_type: str, limit: int, before: float | None) -> list[dict]:
    table = LOG_TYPE_TABLES[log_type]
    ts_col = LOG_TYPE_TIMESTAMP_COL[log_type]
    if before is not None:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {ts_col} < ? ORDER BY {ts_col} DESC LIMIT ?", (before, limit),
        ).fetchall()
    else:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {ts_col} DESC LIMIT ?", (limit,)).fetchall()
    return [{"log_type": log_type, "at": row[ts_col], **dict(row)} for row in rows]


def _fetch_history_sync(log_types: list[str], limit: int, before: float | None) -> list[dict]:
    conn = _require_connection()
    all_rows = []
    for log_type in log_types:
        all_rows.extend(_fetch_type_history_sync(conn, log_type, limit, before))
    all_rows.sort(key=lambda r: r["at"], reverse=True)
    return all_rows[:limit]


async def fetch_history(log_types: list[str], limit: int, before: float | None = None) -> list[dict]:
    """Merged, newest-first rows across the given log types (services/log_settings.py's LOG_TYPES
    keys), each row tagged with its log_type and a normalized "at" timestamp. Each type is queried
    for up to `limit` rows independently, then merged and re-capped -- simple, at the cost of some
    over-fetching for sparse types when several are selected; fine at this scale."""
    async with _lock:
        return await asyncio.to_thread(_fetch_history_sync, log_types, limit, before)


_STATS_WINDOW_DAYS = 30
_SENT_PACKET_TYPES = ["digipeat", "rf_beacon", "igate_beacon", "igate_gate", "message"]
_TOP_CALLSIGNS_LIMIT = 10


def _count_sync(
    conn: sqlite3.Connection, table: str, ts_col: str, since: float | None = None,
    extra_where: str = "", extra_params: tuple = (),
) -> int:
    clauses = []
    params: list = []
    if since is not None:
        clauses.append(f"{ts_col} >= ?")
        params.append(since)
    if extra_where:
        clauses.append(extra_where)
        params.extend(extra_params)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0]


def _get_stats_sync() -> dict:
    conn = _require_connection()
    now = time.time()
    cutoff_24h = now - 86400
    cutoff_7d = now - 7 * 86400
    cutoff_30d = now - _STATS_WINDOW_DAYS * 86400

    heard = {
        "total_24h": _count_sync(conn, "heard_packets", "heard_at", cutoff_24h),
        "total_7d": _count_sync(conn, "heard_packets", "heard_at", cutoff_7d),
        "total_30d": _count_sync(conn, "heard_packets", "heard_at", cutoff_30d),
        "total_all_time": _count_sync(conn, "heard_packets", "heard_at"),
        "top_callsigns": [
            {"callsign": row["callsign"], "count": row["count"]}
            for row in conn.execute(
                "SELECT callsign, COUNT(*) AS count FROM heard_packets "
                "GROUP BY callsign ORDER BY count DESC, callsign ASC LIMIT ?",
                (_TOP_CALLSIGNS_LIMIT,),
            ).fetchall()
        ],
    }

    by_type = {
        t: _count_sync(conn, "sent_packets", "sent_at", extra_where="type = ?", extra_params=(t,))
        for t in _SENT_PACKET_TYPES
    }
    sent = {
        "total_24h": _count_sync(conn, "sent_packets", "sent_at", cutoff_24h),
        "total_7d": _count_sync(conn, "sent_packets", "sent_at", cutoff_7d),
        "total_30d": _count_sync(conn, "sent_packets", "sent_at", cutoff_30d),
        "total_all_time": sum(by_type.values()),
        "by_type": by_type,
    }

    last_failure = conn.execute(
        "SELECT at, reason FROM direwolf_events WHERE ok = 0 ORDER BY at DESC LIMIT 1"
    ).fetchone()
    direwolf = {
        "starts_24h": _count_sync(conn, "direwolf_events", "at", cutoff_24h, "action = 'start'"),
        "starts_7d": _count_sync(conn, "direwolf_events", "at", cutoff_7d, "action = 'start'"),
        "starts_30d": _count_sync(conn, "direwolf_events", "at", cutoff_30d, "action = 'start'"),
        "start_failures_30d": _count_sync(conn, "direwolf_events", "at", cutoff_30d, "action = 'start' AND ok = 0"),
        "last_failure_at": last_failure["at"] if last_failure else None,
        "last_failure_reason": last_failure["reason"] if last_failure else None,
    }

    sig_total_30d = _count_sync(conn, "signal_test_results", "started_at", cutoff_30d)
    sig_replied_30d = _count_sync(conn, "signal_test_results", "started_at", cutoff_30d, "received = 1")
    signal_test = {
        "total_30d": sig_total_30d,
        "replied_30d": sig_replied_30d,
        "success_rate_30d": round(100 * sig_replied_30d / sig_total_30d) if sig_total_30d else None,
    }

    # Daily activity, last _STATS_WINDOW_DAYS days (UTC calendar days), zero-filled so the chart has
    # no gaps even on a quiet day.
    heard_by_day = dict(conn.execute(
        "SELECT date(heard_at, 'unixepoch') AS day, COUNT(*) AS c FROM heard_packets "
        "WHERE heard_at >= ? GROUP BY day", (cutoff_30d,),
    ).fetchall())
    sent_by_day = dict(conn.execute(
        "SELECT date(sent_at, 'unixepoch') AS day, COUNT(*) AS c FROM sent_packets "
        "WHERE sent_at >= ? GROUP BY day", (cutoff_30d,),
    ).fetchall())
    today = datetime.now(timezone.utc).date()
    daily_activity = []
    for i in range(_STATS_WINDOW_DAYS - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        daily_activity.append({"day": day, "heard": heard_by_day.get(day, 0), "sent": sent_by_day.get(day, 0)})

    return {
        "heard": heard, "sent": sent, "direwolf": direwolf, "signal_test": signal_test,
        "daily_activity": daily_activity,
    }


async def get_stats() -> dict:
    """Summary counts (heard/sent totals by period, top callsigns, sent-by-type breakdown, Direwolf
    restart/failure counts, signal-test success rate) plus a 30-day daily activity series, for the
    Stats page. One thread hop for the whole bundle, not one per metric."""
    async with _lock:
        return await asyncio.to_thread(_get_stats_sync)


_retention_task: asyncio.Task | None = None


async def _retention_loop() -> None:
    while True:
        max_age_days, max_size_mb = log_settings.retention()
        if max_age_days > 0 or max_size_mb > 0:
            try:
                await apply_retention(max_age_days, max_size_mb)
            except Exception as e:
                logger.error("Retention sweep failed: %s", e)
        await asyncio.sleep(_RETENTION_CHECK_INTERVAL_S)


def start_retention_loop() -> None:
    """Checks age/size limits immediately, then every _RETENTION_CHECK_INTERVAL_S; re-reads
    log_settings each cycle so a config change takes effect without a restart. Safe to call once."""
    global _retention_task
    if _retention_task is None:
        _retention_task = asyncio.create_task(_retention_loop())


def stop_retention_loop() -> None:
    global _retention_task
    if _retention_task:
        _retention_task.cancel()
        _retention_task = None
