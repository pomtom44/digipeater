#!/usr/bin/env python3
"""Extracts a coarse whole-world PMTiles basemap during install for the setup wizard's map caching step."""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import tiles  # noqa: E402, after sys.path fix-up above

logging.basicConfig(level=logging.INFO, format="%(message)s")
# httpx logs one INFO line per HTTP request at this level; fine for the
# handful of requests find_source_url() makes, but not worth the noise.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    print(f"Pre-caching world map (zoom 0-{tiles.WORLD_MAX_ZOOM})...")
    downloader = tiles.RegionDownloader(
        tiles.WORLD_BOUNDS, tiles.WORLD_MAX_ZOOM, output_path=tiles.WORLD_PMTILES_PATH,
    )
    await downloader.run()
    status = downloader.status()
    if status["error"]:
        print(f"World map pre-cache failed: {status['error']}")
        sys.exit(1)
    print(f"World map pre-cache done: {status['bytes']:,} bytes")


if __name__ == "__main__":
    asyncio.run(main())
