#!/usr/bin/env python3
"""Pre-caches a coarse zoom 0-5 whole-world base layer during install, so a
future map view never renders as a blank grey grid before anyone's actually
downloaded their own station's region via the setup wizard.

~20MB total, not a real "offline map of the world" — zoom 5 is regional
detail at best. A full-detail world cache was deliberately ruled out (tens
of GB for coverage a single fixed station never needs — see TODO.md); this
is just enough for orientation.

Run from install.sh with the app's own venv and cwd set to the app
directory, so tiles land in the same map_tiles/ the running app later
reads from (see services/tiles.py: TILE_DIR, a path relative to cwd).
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import tiles  # noqa: E402 — after sys.path fix-up above

logging.basicConfig(level=logging.INFO, format="%(message)s")

WORLD_MAX_ZOOM = 5


async def main() -> None:
    downloader = tiles.TileDownloader(tiles.WORLD_BOUNDS, 0, WORLD_MAX_ZOOM)
    total = downloader.status()["total"]
    print(f"Pre-caching world map (zoom 0-{WORLD_MAX_ZOOM}, {total} tiles)...")
    await downloader.run()
    status = downloader.status()
    print(f"World map pre-cache done — {status['done']} cached, {status['failed']} failed.")


if __name__ == "__main__":
    asyncio.run(main())
