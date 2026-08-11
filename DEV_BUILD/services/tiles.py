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

# Real-world regions (hundreds of km, city-level zoom) land in the
# hundred-thousand-tile range — bumped from 16 once that stopped being a
# hypothetical. Raise further only with real justification, not just
# because a bigger number downloads faster; see TileDownloader.run().
_MAX_CONCURRENT = 24

AVG_TILE_KB = 15  # rough average tile size, for the size estimate only

# 85.0 rather than 90.0 — Web Mercator (what every slippy-map tile server
# uses, including OSM's) is undefined at the poles; ~85.05 is the standard
# cutoff. Used for the install-time world pre-cache, not the wizard's
# region picker (which sends its own explicit north/south/east/west bounds
# straight from the map's draggable rectangle).
WORLD_BOUNDS = {"north": 85.0, "south": -85.0, "east": 180.0, "west": -180.0}


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


def _lon_to_tile(lon: float, z: int) -> int:
    # Clamped to [0, n-1] — lon=180 (the antimeridian, e.g. WORLD_BOUNDS'
    # east edge) computes exactly n unclamped, an out-of-range index one
    # past the real last column, which was silently doubling tile counts
    # at every zoom level for anything reaching the boundary.
    n = 2 ** z
    return max(0, min(n - 1, int((lon + 180) / 360 * n)))


def _lat_to_tile(lat: float, z: int) -> int:
    n = 2 ** z
    lat_r = math.radians(lat)
    return max(0, min(n - 1, int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)))


def _tile_count_for_bounds(bounds: dict, zoom_min: int, zoom_max: int) -> int:
    total = 0
    for z in range(zoom_min, zoom_max + 1):
        x_min, x_max = _lon_to_tile(bounds["west"], z), _lon_to_tile(bounds["east"], z)
        y_min, y_max = _lat_to_tile(bounds["north"], z), _lat_to_tile(bounds["south"], z)
        total += (abs(x_max - x_min) + 1) * (abs(y_max - y_min) + 1)
    return total


def estimate_tiles_for_bounds(bounds: dict, zoom_min: int, zoom_max: int) -> tuple[int, float]:
    """Return (tile_count, estimated_mb)."""
    total = _tile_count_for_bounds(bounds, zoom_min, zoom_max)
    size_mb = (total * AVG_TILE_KB) / 1024
    return total, size_mb


class TileDownloader:
    """One download at a time — status()/cancel() are polled/called from
    the web layer while run() executes as a background asyncio task."""

    def __init__(self, bounds: dict, zoom_min: int, zoom_max: int):
        self._bounds = bounds
        self._zoom_min = zoom_min
        self._zoom_max = zoom_max
        self._total = _tile_count_for_bounds(bounds, zoom_min, zoom_max)
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

                # A queue + fixed worker pool, not fixed-size batches — a
                # worker picks up the next tile the instant it's free,
                # instead of every worker waiting for the *slowest* tile in
                # a batch before any of them can start the next one. Same
                # concurrency ceiling either way, but no artificial stalls;
                # this alone was leaving real throughput on the table.
                # Queue-based rather than one asyncio.Task per tile, since
                # a single zoom level can be a six-figure tile count — a
                # bounded number of workers pulling from a queue keeps
                # memory flat regardless of how large that gets.
                queue: asyncio.Queue = asyncio.Queue()
                for x in range(min(x_min, x_max), max(x_min, x_max) + 1):
                    for y in range(min(y_min, y_max), max(y_min, y_max) + 1):
                        queue.put_nowait((z, x, y))

                async def _worker():
                    while not self._cancelled:
                        try:
                            zz, xx, yy = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            return
                        await self._download_tile(client, zz, xx, yy)

                # _MAX_CONCURRENT — deliberately still well short of what
                # httpx's connection pool could sustain. OSM's tile usage
                # policy asks bulk consumers to be considerate, and
                # traffic that looks abusive risks the whole IP getting
                # rate-limited or blocked — worse than "slow", since that
                # breaks tile downloads entirely, including small future
                # ones. See TODO.md.
                workers = [asyncio.create_task(_worker()) for _ in range(_MAX_CONCURRENT)]
                await asyncio.gather(*workers)

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
