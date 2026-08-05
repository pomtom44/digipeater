"""Reads GPS position — serial NMEA or gpsd client."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Awaitable

import serial

logger = logging.getLogger(__name__)


@dataclass
class GPSFix:
    latitude: float
    longitude: float
    hdop: Optional[float]   # horizontal dilution of precision — lower is better
    satellites: int
    timestamp: str


class GPSState:
    NO_DEVICE = "no_device"
    WAITING = "waiting"
    FIXED = "fixed"
    ERROR = "error"


class GPSReader:
    def __init__(
        self,
        device: str,
        baud: int = 9600,
        on_fix: Callable[[GPSFix], Awaitable[None]] = None,
        on_status: Callable[[str, str], Awaitable[None]] = None,
        use_gpsd: bool = False,
        gpsd_host: str = "localhost",
        gpsd_port: int = 2947,
    ):
        self._device = device
        self._baud = baud
        self._on_fix = on_fix
        self._on_status = on_status  # called with (state, message)
        self._use_gpsd = use_gpsd
        self._gpsd_host = gpsd_host
        self._gpsd_port = gpsd_port
        self._fix: Optional[GPSFix] = None
        self._state = GPSState.WAITING
        self._waiting_since: Optional[datetime] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def fix(self) -> Optional[GPSFix]:
        return self._fix

    @property
    def state(self) -> str:
        return self._state

    @property
    def waiting_seconds(self) -> int:
        if self._waiting_since:
            return int((datetime.now() - self._waiting_since).total_seconds())
        return 0

    def start(self) -> None:
        self._running = True
        self._waiting_since = datetime.now()
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        if self._use_gpsd:
            await self._run_gpsd()
        else:
            await self._run_serial()

    async def _run_serial(self) -> None:
        try:
            port = serial.Serial(self._device, self._baud, timeout=1)
        except serial.SerialException as e:
            await self._set_status(GPSState.ERROR, f"GPS device error: {e}")
            return

        await self._set_status(GPSState.WAITING, "Waiting for GPS fix...")

        loop = asyncio.get_event_loop()
        try:
            while self._running:
                line = await loop.run_in_executor(None, port.readline)
                decoded = line.decode(errors="replace").strip()
                fix = _parse_nmea(decoded)
                if fix:
                    self._fix = fix
                    await self._set_status(GPSState.FIXED, f"GPS fixed — {fix.latitude:.4f}, {fix.longitude:.4f}")
                    if self._on_fix:
                        await self._on_fix(fix)
                elif self._state == GPSState.WAITING:
                    elapsed = self.waiting_seconds
                    await self._set_status(GPSState.WAITING, f"Waiting GPS — {elapsed}s")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._set_status(GPSState.ERROR, f"GPS error: {e}")
        finally:
            port.close()

    async def _run_gpsd(self) -> None:
        """Connect to gpsd via TCP JSON protocol and stream position fixes."""
        await self._set_status(GPSState.WAITING, f"Connecting to gpsd at {self._gpsd_host}:{self._gpsd_port}...")
        try:
            reader, writer = await asyncio.open_connection(self._gpsd_host, self._gpsd_port)
        except OSError as e:
            await self._set_status(GPSState.ERROR, f"gpsd connect failed: {e}")
            return

        writer.write(b'?WATCH={"enable":true,"json":true}\n')
        await writer.drain()
        await self._set_status(GPSState.WAITING, "Waiting for GPS fix via gpsd...")

        try:
            while self._running:
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    obj = json.loads(raw.decode())
                except json.JSONDecodeError:
                    continue

                if obj.get("class") == "TPV" and obj.get("mode", 0) >= 2:
                    lat = obj.get("lat")
                    lon = obj.get("lon")
                    if lat is None or lon is None:
                        continue
                    fix = GPSFix(
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        hdop=self._fix.hdop if self._fix else None,
                        satellites=self._fix.satellites if self._fix else 0,
                        timestamp=_timestamp(),
                    )
                    self._fix = fix
                    await self._set_status(GPSState.FIXED, f"GPS fixed — {fix.latitude:.4f}, {fix.longitude:.4f}")
                    if self._on_fix:
                        await self._on_fix(fix)
                elif obj.get("class") == "SKY":
                    sats = [s for s in obj.get("satellites", []) if s.get("used")]
                    if self._fix:
                        self._fix = GPSFix(
                            latitude=self._fix.latitude,
                            longitude=self._fix.longitude,
                            hdop=obj.get("hdop", self._fix.hdop),
                            satellites=len(sats),
                            timestamp=self._fix.timestamp,
                        )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._set_status(GPSState.ERROR, f"gpsd error: {e}")
        finally:
            writer.close()

    async def _set_status(self, state: str, message: str) -> None:
        self._state = state
        if self._on_status:
            await self._on_status(state, message)


def _parse_nmea(sentence: str) -> Optional[GPSFix]:
    """Parse GPRMC or GPGGA sentence and return a GPSFix if valid."""
    if not sentence.startswith("$"):
        return None

    parts = sentence.split(",")

    if sentence.startswith("$GPRMC") or sentence.startswith("$GNRMC"):
        # $GPRMC,time,status,lat,N/S,lon,E/W,...
        if len(parts) < 7 or parts[2] != "A":  # A = active fix
            return None
        try:
            lat = _nmea_to_decimal(parts[3], parts[4])
            lon = _nmea_to_decimal(parts[5], parts[6])
            return GPSFix(lat, lon, None, 0, _timestamp())
        except (ValueError, IndexError):
            return None

    if sentence.startswith("$GPGGA") or sentence.startswith("$GNGGA"):
        # $GPGGA,time,lat,N/S,lon,E/W,fix_quality,satellites,hdop,...
        if len(parts) < 10 or parts[6] == "0":  # fix_quality 0 = no fix
            return None
        try:
            lat = _nmea_to_decimal(parts[2], parts[3])
            lon = _nmea_to_decimal(parts[4], parts[5])
            sats = int(parts[7]) if parts[7] else 0
            hdop = float(parts[8]) if parts[8] else None
            return GPSFix(latitude=lat, longitude=lon, hdop=hdop, satellites=sats, timestamp=_timestamp())
        except (ValueError, IndexError):
            return None

    return None


def _nmea_to_decimal(value: str, hemi: str) -> float:
    """Convert NMEA DDDMM.MMMMM to decimal degrees."""
    if not value:
        raise ValueError("empty value")
    if hemi in ("N", "S"):
        deg = int(value[:2])
        mins = float(value[2:])
    else:
        deg = int(value[:3])
        mins = float(value[3:])
    result = deg + mins / 60
    if hemi in ("S", "W"):
        result = -result
    return round(result, 6)


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")
