"""Queries gpsd for live GPS status over its JSON protocol on localhost:2947."""

import asyncio
import json
import logging
import math

logger = logging.getLogger(__name__)

# WGS84 ellipsoid, used only for the ECEF fallback below.
_WGS84_A = 6378137.0
_WGS84_F = 1 / 298.257223563
_WGS84_E2 = _WGS84_F * (2 - _WGS84_F)

_GPSD_HOST = "127.0.0.1"
_GPSD_PORT = 2947
_CONNECT_TIMEOUT_S = 1.5
_READ_TIMEOUT_S = 2.0

# gpsd_json(5): TPV.mode (0=unknown, 1=no fix, 2=2D, 3=3D)
_FIX_MODES = {0: "unknown", 1: "no fix", 2: "2D fix", 3: "3D fix"}


def _ecef_to_latlon(x: float, y: float, z: float) -> tuple[float, float]:
    """Bowring's method, iterated to convergence; +-1mm accuracy in a few iterations."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - _WGS84_E2))
    for _ in range(5):
        sin_lat = math.sin(lat)
        n = _WGS84_A / math.sqrt(1 - _WGS84_E2 * sin_lat * sin_lat)
        lat = math.atan2(z + _WGS84_E2 * n * sin_lat, p)
    return math.degrees(lat), math.degrees(lon)


async def get_status() -> dict:
    """Connects to gpsd, collects the latest TPV/SKY reports, then disconnects."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_GPSD_HOST, _GPSD_PORT), timeout=_CONNECT_TIMEOUT_S
        )
    except (OSError, asyncio.TimeoutError):
        return {"available": False, "reason": "gpsd is not running or not installed"}

    tpv = None
    sky = None
    try:
        writer.write(b'?WATCH={"enable":true,"json":true}\n')
        await writer.drain()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _READ_TIMEOUT_S
        while True:
            have_good_tpv = tpv is not None and tpv.get("lat") is not None and tpv.get("lon") is not None
            if have_good_tpv and sky is not None:
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            cls = obj.get("class")
            if cls == "TPV":
                tpv = obj
            elif cls == "SKY":
                sky = obj
    except OSError as e:
        return {"available": False, "reason": f"Lost connection to gpsd: {e}"}
    finally:
        writer.close()

    if tpv is None:
        return {"available": False, "reason": "gpsd is running, but no GPS data received; check the device is connected"}

    mode = tpv.get("mode", 0)
    lat, lon = tpv.get("lat"), tpv.get("lon")
    # Some gpsd/u-blox combos report a valid ECEF fix but leave lat/lon at 0.0
    # (geodetic conversion not populated); fall back to converting it ourselves.
    if lat == 0.0 and lon == 0.0:
        ecefx, ecefy, ecefz = tpv.get("ecefx"), tpv.get("ecefy"), tpv.get("ecefz")
        if ecefx is not None and ecefy is not None and ecefz is not None and math.hypot(ecefx, ecefy, ecefz) > 1000:
            lat, lon = _ecef_to_latlon(ecefx, ecefy, ecefz)

    return {
        "available": True,
        "fix": _FIX_MODES.get(mode, "unknown"),
        "has_fix": mode >= 2,
        "latitude": lat,
        "longitude": lon,
        "satellites_used": sky.get("uSat") if sky else None,
        "satellites_visible": sky.get("nSat") if sky else None,
    }


async def get_position() -> dict:
    """Just lat/lon, for the wizard's one-shot "Get current" button."""
    status = await get_status()
    if not status.get("available") or not status.get("has_fix"):
        return {"available": False, "reason": status.get("reason", "No GPS fix yet")}
    return {"available": True, "latitude": status["latitude"], "longitude": status["longitude"]}
