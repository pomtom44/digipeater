"""Downloads offline map data (PMTiles) covering a region around the station, via Protomaps' hosted planet build."""

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
# Coarse world basemap (maxzoom 8) written once at install time, always available offline.
WORLD_PMTILES_PATH = MAP_DATA_DIR / "world.pmtiles"
WORLD_MAX_ZOOM = 8
# 85.0 not 90.0: Web Mercator is undefined at the poles.
WORLD_BOUNDS = {"north": 85.0, "south": -85.0, "east": 180.0, "west": -180.0}

_BUILD_HOST = "build.protomaps.com"
_BUILD_URL_TEMPLATE = f"https://{_BUILD_HOST}/{{date}}.pmtiles"
# The daily build lags real time by roughly a day; walk backward a few days to find one that's ready.
_BUILD_LOOKBACK_DAYS = 5

_INTERNET_CHECK_PORT = 443
_INTERNET_CHECK_TIMEOUT_S = 3.0

_BUILD_DATE_RE = re.compile(r"/(\d{8})\.pmtiles$")


def _build_date_marker_path(output_path: Path) -> Path:
    """Sidecar file path recording which planet build an extract came from."""
    return output_path.with_name(output_path.name + ".build_date")


def cached_build_date(output_path: Path) -> str | None:
    """Returns the build date (YYYYMMDD) the file was last extracted from, or None if unrecorded."""
    marker = _build_date_marker_path(output_path)
    if not marker.exists():
        return None
    return marker.read_text().strip() or None


async def has_internet() -> bool:
    """Checks reachability of Protomaps' build host specifically."""
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


# Cache for the live-streaming proxy so tile requests don't re-probe find_source_url() every time.
_LIVE_SOURCE_CACHE_TTL_S = 3600
_live_source_cache: dict = {"url": None, "resolved_at": 0.0}


async def resolve_cached_source_url() -> str:
    """Like find_source_url(), but memoized and falling back to a stale cached URL on transient failure."""
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
    """Finds the most recent available daily planet build. Returns (url, date_str); raises RuntimeError
    if none of the last few days resolve."""
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
    """One region extraction at a time; progress is read from the growing output file's size on disk."""

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
        # While active, progress is the growing temp file; once finished, report on output_path.
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
        # Remove any stale temp file from a previous crashed/killed run.
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
            # Extracted into a temp file, only renamed onto output_path once fully written,
            # so readers never see a truncated archive.
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
