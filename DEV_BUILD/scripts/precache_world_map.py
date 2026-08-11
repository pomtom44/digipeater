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
# httpx (and httpcore underneath it) log one INFO line per HTTP request at
# this level — harmless for a handful of requests, but a 1365-tile world
# pre-cache turned that into 1365 lines of install output. Only our own
# messages below are meant to show.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

WORLD_MAX_ZOOM = 5
_PROGRESS_INTERVAL_S = 3


async def main() -> None:
    downloader = tiles.TileDownloader(tiles.WORLD_BOUNDS, 0, WORLD_MAX_ZOOM)
    total = downloader.status()["total"]
    print(f"Pre-caching world map (zoom 0-{WORLD_MAX_ZOOM}, {total} tiles)...")

    async def _report_progress():
        while True:
            await asyncio.sleep(_PROGRESS_INTERVAL_S)
            s = downloader.status()
            print(f"  {s['done']}/{s['total']} tiles (zoom {s['current_zoom']})...")

    progress_task = asyncio.create_task(_report_progress())
    try:
        await downloader.run()
    finally:
        progress_task.cancel()

    status = downloader.status()
    print(f"World map pre-cache done — {status['done']} cached, {status['failed']} failed.")


if __name__ == "__main__":
    asyncio.run(main())
