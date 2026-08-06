"""Manages the Direwolf process — start, stop, restart, and stdout streaming."""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class State(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    ERROR = "error"


class DirewolfManager:
    def __init__(self, config: dict, on_line: Callable[[str], Awaitable[None]] = None, on_state: Callable[[State], Awaitable[None]] = None):
        self._config = config
        self._on_line = on_line      # called with each stdout line
        self._on_state = on_state    # called on state change
        self._process: asyncio.subprocess.Process = None
        self._state = State.STOPPED
        self._attempt = 0
        self._start_time: datetime = None
        self._reader_task: asyncio.Task = None

    @property
    def state(self) -> State:
        return self._state

    @property
    def uptime(self) -> str:
        if self._start_time is None or self._state != State.RUNNING:
            return "—"
        delta = datetime.now() - self._start_time
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"

    async def start(self) -> None:
        if self._state in (State.RUNNING, State.STARTING):
            return
        self._attempt = 0
        await self._launch()

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
        if self._reader_task:
            self._reader_task.cancel()
        self._process = None
        self._start_time = None
        await self._set_state(State.STOPPED)

    async def _launch(self) -> None:
        dw = self._config.get("direwolf", {})
        binary = dw.get("binary", "/usr/bin/direwolf")
        conf = dw.get("config_path", "/etc/direwolf/direwolf.conf")

        await self._set_state(State.STARTING)
        await self._emit(f"[system] Starting Direwolf (attempt {self._attempt + 1})...")

        try:
            self._process = await asyncio.create_subprocess_exec(
                binary, "-c", conf, "-t", "0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            await self._emit(f"[error] Direwolf binary not found at {binary}")
            await self._set_state(State.ERROR)
            return

        self._start_time = datetime.now()
        await self._set_state(State.RUNNING)
        self._reader_task = asyncio.create_task(self._read_output())

    async def _read_output(self) -> None:
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                await self._emit(line.decode(errors="replace").rstrip())
        except Exception as e:
            logger.error("Error reading Direwolf output: %s", e)
        finally:
            await self._process.wait()
            if self._state == State.RUNNING:
                await self._handle_crash()

    async def _handle_crash(self) -> None:
        dw = self._config.get("direwolf", {})
        max_attempts = dw.get("restart_attempts", 3)
        delays = dw.get("restart_delays", [10, 30, 60])

        if self._attempt >= max_attempts:
            await self._emit("[error] Direwolf failed 3 times — giving up.")
            await self._set_state(State.ERROR)
            return

        delay = delays[min(self._attempt, len(delays) - 1)]
        await self._emit(f"[system] Direwolf exited unexpectedly. Restarting in {delay}s... (attempt {self._attempt + 1}/{max_attempts})")
        await self._set_state(State.RESTARTING)
        self._attempt += 1
        await asyncio.sleep(delay)
        await self._launch()

    async def _emit(self, line: str) -> None:
        if self._on_line:
            await self._on_line(line)

    async def _set_state(self, state: State) -> None:
        self._state = state
        if self._on_state:
            await self._on_state(state)
