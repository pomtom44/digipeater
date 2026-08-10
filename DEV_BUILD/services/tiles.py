"""Downloads and caches OpenStreetMap tiles for a region around the
station, so a map view can eventually work fully offline. Uses OSM's own
standard tile server — open, free, no account or API key needed.

OSM's tile usage policy (operations.osmfoundation.org/policies/tiles/) asks
bulk consumers to be considerate: a real User-Agent, no hammering the
server. Downloads here run in small sequential batches (not one big
parallel blast) for that reason — same approach ORIGINAL/services/
tile_cache.py used, ported here since this is otherwise a straight rebuild
of that module for DEV_BUILD's layout.
"""

import asyncio
import logging
import math
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TILE_SERVER = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# Relative to the working directory, same convention as config.yaml /
# wifi_pending.json — the systemd unit sets WorkingDirectory to the app dir.
TILE_DIR = Path("map_tiles")
_USER_AGENT = "digipeater-setup/1.0 (+https://github.com/pomtom44/digipeater)"

_INTERNET_CHECK_HOST = "tile.openstreetmap.org"
_INTERNET_CHECK_PORT = 443
_INTERNET_CHECK_TIMEOUT_S = 3.0

AVG_TILE_KB = 15  # rough average tile size, for the size estimate only


async def has_internet() -> bool:
    """Checks reachability of the tile server specifically, not just "any"
    internet — what actually matters for this feature is whether tiles can
    be fetched at all."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_INTERNET_CHECK_HOST, _INTERNET_CHECK_PORT),
            timeout=_INTERNET_CHECK_TIMEOUT_S,
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


def _bounds_from_radius(lat: float, lon: float, radius_km: float) -> dict:
    """A simple flat-earth approximation (111km/degree latitude, scaled by
    cos(lat) for longitude) — plenty accurate for picking a tile range, not
    meant for precision navigation."""
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return {
        "north": lat + lat_delta,
        "south": lat - lat_delta,
        "east": lon + lon_delta,
        "west": lon - lon_delta,
    }


def _lon_to_tile(lon: float, z: int) -> int:
    return int((lon + 180) / 360 * (2 ** z))


def _lat_to_tile(lat: float, z: int) -> int:
    lat_r = math.radians(lat)
    return int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * (2 ** z))


def estimate_tiles(lat: float, lon: float, radius_km: float, zoom_min: int, zoom_max: int) -> tuple[int, float]:
    """Return (tile_count, estimated_mb)."""
    bounds = _bounds_from_radius(lat, lon, radius_km)
    total = 0
    for z in range(zoom_min, zoom_max + 1):
        x_min, x_max = _lon_to_tile(bounds["west"], z), _lon_to_tile(bounds["east"], z)
        y_min, y_max = _lat_to_tile(bounds["north"], z), _lat_to_tile(bounds["south"], z)
        total += (abs(x_max - x_min) + 1) * (abs(y_max - y_min) + 1)
    size_mb = (total * AVG_TILE_KB) / 1024
    return total, size_mb


class TileDownloader:
    """One region download at a time — status()/cancel() are polled/called
    from the web layer while run() executes as a background asyncio task."""

    def __init__(self, lat: float, lon: float, radius_km: float, zoom_min: int, zoom_max: int):
        self._bounds = _bounds_from_radius(lat, lon, radius_km)
        self._zoom_min = zoom_min
        self._zoom_max = zoom_max
        self._total, _ = estimate_tiles(lat, lon, radius_km, zoom_min, zoom_max)
        self._done = 0
        self._failed = 0
        self._active = False
        self._cancelled = False
        self._current_zoom = zoom_min

    def status(self) -> dict:
        pct = round((self._done / self._total) * 100, 1) if self._total else 0
        return {
            "active": self._active,
            "cancelled": self._cancelled,
            "total": self._total,
            "done": self._done,
            "failed": self._failed,
            "percent": pct,
            "current_zoom": self._current_zoom,
        }

    def cancel(self) -> None:
        self._cancelled = True

    async def run(self) -> None:
        self._active = True
        self._cancelled = False
        logger.info("Tile download started — %d tiles", self._total)

        async with httpx.AsyncClient(timeout=10) as client:
            for z in range(self._zoom_min, self._zoom_max + 1):
                if self._cancelled:
                    break
                self._current_zoom = z
                x_min = _lon_to_tile(self._bounds["west"], z)
                x_max = _lon_to_tile(self._bounds["east"], z)
                y_min = _lat_to_tile(self._bounds["north"], z)
                y_max = _lat_to_tile(self._bounds["south"], z)

                tasks = []
                for x in range(min(x_min, x_max), max(x_min, x_max) + 1):
                    for y in range(min(y_min, y_max), max(y_min, y_max) + 1):
                        tasks.append(self._download_tile(client, z, x, y))

                # Small batches — considerate of the tile server, not a scraper.
                for i in range(0, len(tasks), 8):
                    if self._cancelled:
                        break
                    await asyncio.gather(*tasks[i:i + 8], return_exceptions=True)

        self._active = False
        logger.info("Tile download finished — %d done, %d failed", self._done, self._failed)

    async def _download_tile(self, client: httpx.AsyncClient, z: int, x: int, y: int) -> None:
        tile_path = TILE_DIR / str(z) / str(x) / f"{y}.png"
        if tile_path.exists():
            self._done += 1
            return
        try:
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            response = await client.get(
                TILE_SERVER.format(z=z, x=x, y=y),
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
            tile_path.write_bytes(response.content)
            self._done += 1
        except Exception as e:
            self._failed += 1
            logger.debug("Tile %d/%d/%d failed: %s", z, x, y, e)
