"""Queries gpsd for live GPS status (position, fix quality, satellite
count) over its JSON protocol on localhost:2947.

gpsd isn't installed by install.sh yet, so this will gracefully report
"unavailable" until that's added and a real GPS device is attached; this
is real client code waiting on that infrastructure, not a stub.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

_GPSD_HOST = "127.0.0.1"
_GPSD_PORT = 2947
_CONNECT_TIMEOUT_S = 1.5
_READ_TIMEOUT_S = 2.0

# gpsd_json(5): TPV.mode (0=unknown, 1=no fix, 2=2D, 3=3D)
_FIX_MODES = {0: "unknown", 1: "no fix", 2: "2D fix", 3: "3D fix"}


async def get_status() -> dict:
    """One-shot: connect, watch briefly, collect the latest TPV/SKY reports
    seen, then disconnect. Returns {"available": False, "reason": ...} if
    gpsd isn't reachable or nothing was reported in time."""
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
        while (tpv is None or sky is None):
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
    return {
        "available": True,
        "fix": _FIX_MODES.get(mode, "unknown"),
        "has_fix": mode >= 2,
        "latitude": tpv.get("lat"),
        "longitude": tpv.get("lon"),
        "satellites_used": sky.get("uSat") if sky else None,
        "satellites_visible": sky.get("nSat") if sky else None,
    }


async def get_position() -> dict:
    """Just lat/lon, for the wizard's one-shot "Get current" button."""
    status = await get_status()
    if not status.get("available") or not status.get("has_fix"):
        return {"available": False, "reason": status.get("reason", "No GPS fix yet")}
    return {"available": True, "latitude": status["latitude"], "longitude": status["longitude"]}
