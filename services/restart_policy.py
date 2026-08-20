"""Applies the Startup tab's restart-on-crash policy to direwolf.service via a systemd drop-in override."""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_HELPER = str(Path(__file__).resolve().parent.parent / "scripts" / "apply-direwolf-restart-policy.sh")

DEFAULT_RESTART_ATTEMPTS = 3
DEFAULT_RESTART_DELAY_S = 30


async def apply(startup_config: dict) -> None:
    """Applies the restart policy; idempotent, re-applied on every boot and whenever the Startup tab is saved."""
    startup_config = startup_config or {}
    autorestart = bool(startup_config.get("autorestart", True))
    attempts = int(startup_config.get("restart_attempts") or DEFAULT_RESTART_ATTEMPTS)
    delay_s = int(startup_config.get("restart_delay_s") or DEFAULT_RESTART_DELAY_S)

    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", _HELPER, "on" if autorestart else "off", str(attempts), str(delay_s),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except OSError as e:
        logger.error("Failed to run restart-policy helper: %s", e)
        return

    if proc.returncode != 0:
        logger.error("Restart-policy helper failed: %s", err.decode(errors="replace").strip())
    else:
        logger.info(
            "Direwolf restart policy applied: autorestart=%s attempts=%d delay_s=%d",
            autorestart, attempts, delay_s,
        )
