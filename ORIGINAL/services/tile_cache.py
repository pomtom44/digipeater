"""Downloads and stores OSM map tiles for offline use."""

import asyncio
import logging
import math
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

AVG_TILE_KB = 15  # rough average tile size in KB


def estimate_tiles(bounds: dict, zoom_min: int, zoom_max: int) -> tuple[int, float]:
    """Return (tile_count, estimated_mb)."""
    total = 0
    for z in range(zoom_min, zoom_max + 1):
        x_min, x_max = _lon_to_tile(bounds["west"], z), _lon_to_tile(bounds["east"], z)
        y_min, y_max = _lat_to_tile(bounds["north"], z), _lat_to_tile(bounds["south"], z)
        total += (abs(x_max - x_min) + 1) * (abs(y_max - y_min) + 1)
    size_mb = (total * AVG_TILE_KB) / 1024
    return total, size_mb


class TileDownloader:
    def __init__(self, bounds: dict, zoom_min: int, zoom_max: int,
                 tile_dir: Path, tile_server: str):
        self._bounds = bounds
        self._zoom_min = zoom_min
        self._zoom_max = zoom_max
        self._tile_dir = Path(tile_dir)
        self._tile_server = tile_server
        self._total, _ = estimate_tiles(bounds, zoom_min, zoom_max)
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

                # Download in batches of 8 to be polite to the tile server
                for i in range(0, len(tasks), 8):
                    if self._cancelled:
                        break
                    await asyncio.gather(*tasks[i:i + 8], return_exceptions=True)

        self._active = False
        logger.info("Tile download complete — %d done, %d failed", self._done, self._failed)

    async def _download_tile(self, client: httpx.AsyncClient, z: int, x: int, y: int) -> None:
        tile_path = self._tile_dir / str(z) / str(x) / f"{y}.png"
        if tile_path.exists():
            self._done += 1
            return

        url = self._tile_server.format(z=z, x=x, y=y)
        try:
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            response = await client.get(url, headers={"User-Agent": "APRS-Digipeater/1.0"})
            response.raise_for_status()
            tile_path.write_bytes(response.content)
            self._done += 1
        except Exception as e:
            self._failed += 1
            logger.debug("Tile %d/%d/%d failed: %s", z, x, y, e)


def _lon_to_tile(lon: float, z: int) -> int:
    return int((lon + 180) / 360 * (2 ** z))


def _lat_to_tile(lat: float, z: int) -> int:
    lat_r = math.radians(lat)
    return int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * (2 ** z))
