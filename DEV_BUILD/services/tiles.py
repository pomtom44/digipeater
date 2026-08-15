"""Downloads a single offline map data file (PMTiles) covering a region
around the station, via Protomaps' hosted daily planet build.

This deliberately does NOT scrape individual tiles from a live tile
server. OpenStreetMap's own tile usage policy is explicit that this isn't
just discouraged, it's disallowed outright: "Offline use is not permitted
on tile.openstreetmap.org", and bulk downloading is defined to include
exactly what an earlier version of this module did: pre-emptive fetching
of tiles beyond what's being actively viewed, pre-seeding areas, building
tile archives. See operations.osmfoundation.org/policies/tiles/ and
TODO.md.

PMTiles is the legitimate, designed-for-this-exact-purpose alternative
(also what OSM's own policy page recommends for offline use): a single
static file containing a region's map data, extracted from a hosted
planet-wide build via HTTP range requests: you only download the bytes
for your region, not the whole planet, and no API key or account is
needed for this self-hosted extraction path (unlike Protomaps' hosted
*live* tile API, which is a separate, unrelated commercial product this
project doesn't use). Region-extraction is only implemented in the
official Go CLI (protomaps/go-pmtiles), not the Python package, so
install.sh fetches that one static binary rather than reimplementing the
PMTiles archive format from scratch, the same "shell out to a well-tested
external tool" approach this project already uses for gpsd/nmcli/etc.

The wizard's interactive region-picker map is now MapLibre GL JS + this
same PMTiles machinery, not Leaflet + live OSM raster tiles. It always
renders from the local WORLD_PMTILES_PATH cache (extracted once at
install time, see scripts/precache_world.py), so the picker itself works
with or without internet at setup time. Only downloading a more detailed
*region* on top of that coarse world layer needs a real connection to
Protomaps' build host.

Two RegionDownloader use cases share this module: the one-off whole-world
install-time precache (coarse, fixed zoom, run by
scripts/precache_world.py) and the wizard's on-demand region extracts
(finer detail, user-picked bounds/zoom, run from web/server.py). Same
class, different output path and bounds/zoom.

A third use case, resolve_cached_source_url(), backs the dashboard's live
map streaming (see web/server.py's /map-data/live.pmtiles): the same
legitimate PMTiles range-read access pattern as RegionDownloader, just
proxied live per-viewport instead of extracted once to a local file, so it
still isn't the bulk/pre-emptive tile scraping the OSM policy above rules
out. The proxy exists because build.protomaps.com itself has no CORS
headers (confirmed directly against the live host, not assumed): a browser
can't range-request it cross-origin, so the Pi relays those requests
same-origin instead. This means live streaming needs the Pi's own
internet, not just the viewer's browser's, even when the dashboard itself
is being viewed from off-site over a tunnel/VPN.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PMTILES_BIN = Path(__file__).resolve().parent.parent / "bin" / "pmtiles"
MAP_DATA_DIR = Path("map_data")
REGION_PATH = MAP_DATA_DIR / "region.pmtiles"
# Written once at install time (scripts/precache_world.py): the always-
# available basemap for the wizard's region picker, regardless of whether
# there's internet at setup time. Coarse (maxzoom 8, ~1GB) on purpose;
# see TODO.md for the sizing reasoning.
WORLD_PMTILES_PATH = MAP_DATA_DIR / "world.pmtiles"
WORLD_MAX_ZOOM = 8
# 85.0 rather than 90.0: Web Mercator (what PMTiles/Protomaps' planet
# build uses, same as every other slippy-map tile scheme) is undefined at
# the poles; ~85.05 is the standard cutoff.
WORLD_BOUNDS = {"north": 85.0, "south": -85.0, "east": 180.0, "west": -180.0}

_BUILD_HOST = "build.protomaps.com"
_BUILD_URL_TEMPLATE = f"https://{_BUILD_HOST}/{{date}}.pmtiles"
# The daily build lags real time by roughly a day (confirmed against the
# live service: today's date 404s, the two before it don't), so walk
# backward a few days rather than assuming any single date is ready yet.
_BUILD_LOOKBACK_DAYS = 5

_INTERNET_CHECK_PORT = 443
_INTERNET_CHECK_TIMEOUT_S = 3.0

_BUILD_DATE_RE = re.compile(r"/(\d{8})\.pmtiles$")


def _build_date_marker_path(output_path: Path) -> Path:
    """Sidecar file recording which planet build an extract came from.
    Lets scripts/auto_tile_update.py tell "is there a newer build than
    what's cached" apart from re-parsing the pmtiles archive itself."""
    return output_path.with_name(output_path.name + ".build_date")


def cached_build_date(output_path: Path) -> str | None:
    """The build date (YYYYMMDD) the file at output_path was last
    extracted from, or None if it doesn't exist / was never recorded
    (e.g. a file left over from before this tracking existed)."""
    marker = _build_date_marker_path(output_path)
    if not marker.exists():
        return None
    return marker.read_text().strip() or None


async def has_internet() -> bool:
    """Checks reachability of Protomaps' build host specifically, not just
    "any" internet: what actually matters for this feature is whether a
    region extract can be fetched at all."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_BUILD_HOST, _INTERNET_CHECK_PORT),
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


# Cache for the live-streaming proxy (see web/server.py's /map-data/live.pmtiles):
# a single dashboard page load can trigger dozens of tile requests, each of
# which would otherwise re-run find_source_url()'s lookback-day HEAD probing.
# The daily build only changes once a day, so an hour-old answer is still
# correct in practice.
_LIVE_SOURCE_CACHE_TTL_S = 3600
_live_source_cache: dict = {"url": None, "resolved_at": 0.0}


async def resolve_cached_source_url() -> str:
    """Like find_source_url(), but memoized for _LIVE_SOURCE_CACHE_TTL_S so
    the live-tile proxy isn't re-probing build.protomaps.com on every single
    tile request. Falls back to a stale cached URL on a transient
    re-resolution failure (the daily build rarely changes day-to-day, so a
    few-hour-old URL is still almost certainly valid) rather than breaking
    an otherwise-working map over one flaky probe; only raises RuntimeError
    (same as find_source_url()) if nothing has ever resolved yet."""
    now = asyncio.get_event_loop().time()
    cached_url = _live_source_cache["url"]
    if cached_url and now - _live_source_cache["resolved_at"] < _LIVE_SOURCE_CACHE_TTL_S:
        return cached_url
    try:
        url, _ = await find_source_url()
    except RuntimeError:
        if cached_url:
            return cached_url
        raise
    _live_source_cache["url"] = url
    _live_source_cache["resolved_at"] = now
    return url


async def find_source_url() -> tuple[str, str]:
    """Finds the most recent available daily planet build. Returns
    (url, date_str): the date is handed back separately (rather than
    re-parsed from the URL by callers) since it's also the value recorded
    in the build_date marker file for future update checks (see
    cached_build_date). Raises RuntimeError if none of the last few days
    resolve. The build host being reachable (has_internet) doesn't
    guarantee a specific date's file exists yet."""
    async with httpx.AsyncClient(timeout=10) as client:
        today = datetime.now(timezone.utc).date()
        for days_back in range(_BUILD_LOOKBACK_DAYS):
            date_str = (today - timedelta(days=days_back)).strftime("%Y%m%d")
            url = _BUILD_URL_TEMPLATE.format(date=date_str)
            try:
                response = await client.head(url)
                if response.status_code == 200:
                    return url, date_str
            except httpx.HTTPError:
                continue
    raise RuntimeError(
        f"No Protomaps planet build found in the last {_BUILD_LOOKBACK_DAYS} days "
        f"(the build host may be reachable but not currently serving builds)."
    )


class RegionDownloader:
    """One region extraction at a time; status()/cancel() are polled/
    called from the web layer while run() executes as a background task.

    Unlike the old per-tile raster downloader, there's no meaningful
    "N of M tiles" progress; pmtiles extract is a single CLI invocation.
    Progress is instead read from the output file's growing size on disk,
    which is honest (it's the real file being built) rather than parsing
    CLI-specific log output that could change format across versions.
    """

    def __init__(self, bounds: dict, zoom_max: int, output_path: Path = REGION_PATH):
        self._bounds = bounds
        self._zoom_max = zoom_max
        self._output_path = output_path
        # Extraction writes here, not directly to output_path; see run()'s
        # atomic-rename comment below.
        self._tmp_path = output_path.with_name(output_path.name + ".part")
        self._active = False
        self._done = False
        self._cancelled = False
        self._error: str | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None

    def status(self) -> dict:
        # While active, real progress is the growing temp file; once
        # finished, tmp_path is gone (renamed on success, deleted on
        # failure/cancel) and output_path is the thing to report on.
        progress_path = self._tmp_path if self._active else self._output_path
        bytes_so_far = progress_path.stat().st_size if progress_path.exists() else 0
        elapsed_s = None
        if self._started_at is not None:
            end = self._finished_at if self._finished_at is not None else asyncio.get_event_loop().time()
            elapsed_s = round(end - self._started_at, 1)
        return {
            "active": self._active,
            "done": self._done,
            "cancelled": self._cancelled,
            "error": self._error,
            "bytes": bytes_so_far,
            "elapsed_s": elapsed_s,
        }

    def cancel(self) -> None:
        self._cancelled = True
        if self._process and self._process.returncode is None:
            self._process.terminate()

    async def run(self) -> None:
        self._active = True
        self._started_at = asyncio.get_event_loop().time()
        MAP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Stale temp file from a previous crashed/killed run at this same
        # path, if any; extract always starts from scratch.
        self._tmp_path.unlink(missing_ok=True)

        try:
            source_url, source_date = await find_source_url()
        except RuntimeError as e:
            self._error = str(e)
            self._active = False
            self._finished_at = asyncio.get_event_loop().time()
            logger.error("Region download failed: %s", e)
            return

        b = self._bounds
        bbox = f"{b['west']},{b['south']},{b['east']},{b['north']}"
        logger.info("Download started: output=%s bbox=%s maxzoom=%d source=%s", self._output_path, bbox, self._zoom_max, source_url)

        try:
            # Extracted into self._tmp_path, a sibling of the real output
            # path, and only renamed onto it once fully written (see
            # below), so a scheduled refresh of an *already-cached* file
            # (scripts/auto_tile_update.py) never leaves anything reading
            # output_path mid-write (the wizard's live map, or a future
            # dashboard) looking at a truncated/corrupt archive, and a
            # failed refresh leaves the previous good cache untouched
            # instead of deleting it upfront and coming up empty.
            self._process = await asyncio.create_subprocess_exec(
                str(PMTILES_BIN), "extract", source_url, str(self._tmp_path),
                f"--bbox={bbox}", f"--maxzoom={self._zoom_max}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            self._error = f"pmtiles binary not found at {PMTILES_BIN}. Was install.sh run?"
            self._active = False
            self._finished_at = asyncio.get_event_loop().time()
            logger.error(self._error)
            return

        _, stderr = await self._process.communicate()

        self._active = False
        self._finished_at = asyncio.get_event_loop().time()
        if self._cancelled:
            self._tmp_path.unlink(missing_ok=True)
            logger.info("Download cancelled")
            return
        if self._process.returncode != 0:
            self._error = stderr.decode(errors="replace").strip() or f"pmtiles exited with code {self._process.returncode}"
            self._tmp_path.unlink(missing_ok=True)
            logger.error("Download failed: %s", self._error)
            return

        self._tmp_path.replace(self._output_path)
        _build_date_marker_path(self._output_path).write_text(source_date)
        self._done = True
        logger.info("Download finished: %s (%d bytes)", self._output_path, self._output_path.stat().st_size)
