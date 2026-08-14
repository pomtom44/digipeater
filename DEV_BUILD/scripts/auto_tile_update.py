#!/usr/bin/env python3
"""Checks whether Protomaps has published a newer daily planet build than
whatever is currently cached, and re-extracts the world map (and the saved
region, if one was ever downloaded) when there is one.

Invoked frequently by a systemd timer (digipeater-tile-update.timer, see
install.sh) rather than run as a long-lived daemon; each invocation reads
config.yaml fresh and mostly no-ops, same "apply from disk on a schedule"
pattern as scripts/apply-gps-config.sh. A marker file
(map_data/.auto_update_last_run) caps this to one real attempt per day, at
or after the user's configured check time; a failed or offline attempt
does NOT set the marker, so it's retried on the timer's next tick instead
of waiting a full day.

Must be run with cwd set to the app directory, same as
scripts/precache_world.py, so map_data/ and config.yaml resolve correctly.
"""

import asyncio
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import tiles  # noqa: E402, after sys.path fix-up above

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("auto_tile_update")

CONFIG_PATH = Path("config.yaml")
LAST_RUN_MARKER = tiles.MAP_DATA_DIR / ".auto_update_last_run"
DEFAULT_CHECK_TIME = "03:00"


def _load_map_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception as e:
        logger.error("Failed to read %s: %s", CONFIG_PATH, e)
        return {}
    return config.get("map", {}) or {}


def _already_ran_today() -> bool:
    if not LAST_RUN_MARKER.exists():
        return False
    return LAST_RUN_MARKER.read_text().strip() == date.today().isoformat()


def _mark_ran_today() -> None:
    tiles.MAP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_MARKER.write_text(date.today().isoformat())


def _parse_check_time(raw: str) -> tuple[int, int]:
    try:
        hh_str, mm_str = raw.split(":", 1)
        hh, mm = int(hh_str), int(mm_str)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    hh_str, mm_str = DEFAULT_CHECK_TIME.split(":")
    return int(hh_str), int(mm_str)


async def _refresh(bounds: dict, zoom_max: int, output_path: Path, label: str) -> bool:
    downloader = tiles.RegionDownloader(bounds, zoom_max, output_path=output_path)
    await downloader.run()
    status = downloader.status()
    if status["error"]:
        logger.error("%s refresh failed: %s", label, status["error"])
        return False
    logger.info("%s refreshed: %d bytes", label, status["bytes"])
    return True


async def main() -> None:
    map_config = _load_map_config()
    auto_update = map_config.get("auto_update", {}) or {}
    if not auto_update.get("enabled"):
        logger.info("Auto-update is disabled, nothing to do.")
        return

    hh, mm = _parse_check_time(auto_update.get("time", DEFAULT_CHECK_TIME))
    now = datetime.now()
    if (now.hour, now.minute) < (hh, mm):
        logger.info("Configured check time %02d:%02d hasn't passed yet today, skipping.", hh, mm)
        return
    if _already_ran_today():
        logger.info("Already checked today, skipping.")
        return

    if not await tiles.has_internet():
        logger.info("No internet reachable, will retry on the next check.")
        return

    try:
        _, latest_date = await tiles.find_source_url()
    except RuntimeError as e:
        logger.warning("Could not determine the latest build, will retry: %s", e)
        return

    any_failure = False

    world_current = tiles.cached_build_date(tiles.WORLD_PMTILES_PATH)
    if world_current != latest_date:
        logger.info("World map: %s -> %s", world_current or "(never cached)", latest_date)
        if not await _refresh(tiles.WORLD_BOUNDS, tiles.WORLD_MAX_ZOOM, tiles.WORLD_PMTILES_PATH, "World map"):
            any_failure = True
    else:
        logger.info("World map already up to date (%s).", world_current)

    region_bound_keys = ("north", "south", "east", "west")
    if all(k in map_config for k in region_bound_keys):
        region_bounds = {k: float(map_config[k]) for k in region_bound_keys}
        region_zoom = int(map_config.get("zoom_max", tiles.WORLD_MAX_ZOOM))
        region_current = tiles.cached_build_date(tiles.REGION_PATH)
        if region_current != latest_date:
            logger.info("Region map: %s -> %s", region_current or "(never cached)", latest_date)
            if not await _refresh(region_bounds, region_zoom, tiles.REGION_PATH, "Region map"):
                any_failure = True
        else:
            logger.info("Region map already up to date (%s).", region_current)
    else:
        logger.info("No region was ever downloaded, nothing to refresh there.")

    if any_failure:
        logger.warning("At least one refresh failed; not marking today as checked, will retry on the next tick.")
        return

    _mark_ran_today()
    logger.info("Auto-update check complete.")


if __name__ == "__main__":
    asyncio.run(main())
