"""
Persistent packet store.

Saves decoded APRS position packets to a JSON file.
Handles deduplication, per-callsign history limits, and reset.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_FILE = Path("/var/digipeater/packets.json")
MAX_PER_CALLSIGN = 5000


class PacketStore:
    def __init__(self, path: Path = DATA_FILE):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._packets: list[dict] = []
        self._ids: set[str] = set()
        self._load()

    # ── Public API ────────────────────────────────────────────

    def add(self, packet: dict) -> bool:
        """
        Add a packet. Returns True if it was new (not a duplicate).
        Packet dict must have: callsign, latitude, longitude, timestamp.
        """
        pid = _packet_id(packet)
        with self._lock:
            if pid in self._ids:
                return False
            self._packets.append(packet)
            self._ids.add(pid)
            self._trim()
        self._save()
        return True

    def get_all(self, limit: int = 1000) -> list[dict]:
        return sorted(self._packets, key=lambda p: p.get("timestamp", 0), reverse=True)[:limit]

    def get_by_callsign(self, callsign: str, limit: int = 500) -> list[dict]:
        base = callsign.split("-")[0].upper()
        matches = [p for p in self._packets if p.get("callsign", "").split("-")[0].upper() == base]
        return sorted(matches, key=lambda p: p.get("timestamp", 0), reverse=True)[:limit]

    def get_callsigns(self) -> list[dict]:
        """Return unique callsigns with last-seen timestamp, newest first."""
        seen: dict[str, dict] = {}
        for p in self._packets:
            call = p.get("callsign", "")
            ts = p.get("timestamp", 0)
            if call not in seen or ts > seen[call]["last_seen"]:
                seen[call] = {"callsign": call, "last_seen": ts}
        return sorted(seen.values(), key=lambda x: x["last_seen"], reverse=True)

    def get_latest_per_callsign(self) -> list[dict]:
        """Return the most recent packet for each callsign."""
        seen: dict[str, dict] = {}
        for p in self._packets:
            call = p.get("callsign", "")
            ts = p.get("timestamp", 0)
            if call not in seen or ts > seen[call].get("timestamp", 0):
                seen[call] = p
        return list(seen.values())

    def get_latest_position_per_callsign(self) -> list[dict]:
        """Return the most recent packet with lat/lon for each callsign — for map display."""
        seen: dict[str, dict] = {}
        for p in self._packets:
            if p.get("latitude") is None or p.get("longitude") is None:
                continue
            call = p.get("callsign", "")
            ts = p.get("timestamp", 0)
            if call not in seen or ts > seen[call].get("timestamp", 0):
                seen[call] = p
        return list(seen.values())

    def reset(self) -> None:
        """Clear all packets."""
        with self._lock:
            self._packets = []
            self._ids = set()
        self._save()
        logger.info("Packet store reset")

    def count(self) -> int:
        return len(self._packets)

    # ── Internal ──────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                self._packets = json.load(f)
            self._ids = {_packet_id(p) for p in self._packets}
            logger.info("Loaded %d packets from store", len(self._packets))
        except Exception as e:
            logger.error("Failed to load packet store: %s", e)
            self._packets = []
            self._ids = set()

    def _save(self) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(self._packets, f)
        except Exception as e:
            logger.error("Failed to save packet store: %s", e)

    def _trim(self) -> None:
        """Enforce per-callsign limit to prevent unbounded growth."""
        counts: dict[str, int] = {}
        kept = []
        # Sort newest first so we keep the most recent
        for p in sorted(self._packets, key=lambda x: x.get("timestamp", 0), reverse=True):
            call = p.get("callsign", "")
            if counts.get(call, 0) < MAX_PER_CALLSIGN:
                kept.append(p)
                counts[call] = counts.get(call, 0) + 1
        self._packets = kept
        self._ids = {_packet_id(p) for p in self._packets}


def _packet_id(packet: dict) -> str:
    """Unique ID based on callsign + rounded timestamp + position (if present)."""
    call = packet.get("callsign", "")
    ts = round(packet.get("timestamp", 0), 1)
    lat = packet.get("latitude")
    lon = packet.get("longitude")
    if lat is not None and lon is not None:
        return f"{call}_{ts}_{round(lat, 4)}_{round(lon, 4)}"
    return f"{call}_{ts}_nopos"
