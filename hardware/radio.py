"""CAT radio control via Hamlib's rigctld daemon.

rigctld is started as a subprocess when radio.enabled = true in config.
Frequency get/set are done over a short-lived TCP connection to localhost:4532.
Falls back gracefully when rigctld is missing or the radio is disconnected.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_HOST = "localhost"
_PORT = 4532


class RadioController:
    def __init__(self, config: dict):
        self.enabled: bool = config.get("enabled", False)
        self._model: str = str(config.get("model", 1))
        self._rig_port: str = config.get("port", "/dev/ttyUSB0")
        self._baud: str = str(config.get("baud", 9600))
        self._proc: Optional[asyncio.subprocess.Process] = None

    async def start(self) -> None:
        if not self.enabled:
            return
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "rigctld",
                "-m", self._model,
                "-r", self._rig_port,
                "-s", self._baud,
                "-T", _HOST,
                "-t", str(_PORT),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(1.0)   # give rigctld time to bind the port
            logger.info("rigctld started (model=%s port=%s baud=%s)", self._model, self._rig_port, self._baud)
        except FileNotFoundError:
            logger.warning("rigctld not found — install hamlib: sudo apt install hamlib")
            self.enabled = False
        except Exception as e:
            logger.error("Failed to start rigctld: %s", e)
            self.enabled = False

    async def stop(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                pass
            self._proc = None

    async def get_frequency(self) -> Optional[float]:
        """Return VFO-A frequency in Hz, or None if unavailable."""
        return await _tcp_get("f")

    async def set_frequency(self, freq_hz: float) -> bool:
        """Set VFO-A frequency in Hz. Returns True on success."""
        return await _tcp_set(f"F {int(freq_hz)}")

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None


async def _tcp_get(cmd: str) -> Optional[float]:
    """Send a rigctld query command; parse float response."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_HOST, _PORT), timeout=2.0
        )
        writer.write(f"{cmd}\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(64), timeout=2.0)
        writer.close()
        await writer.wait_closed()
        return float(data.decode().strip())
    except Exception:
        return None


async def _tcp_set(cmd: str) -> bool:
    """Send a rigctld set command; return True if RPRT 0."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_HOST, _PORT), timeout=2.0
        )
        writer.write(f"{cmd}\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(64), timeout=2.0)
        writer.close()
        await writer.wait_closed()
        return data.decode().strip() == "RPRT 0"
    except Exception:
        return False
