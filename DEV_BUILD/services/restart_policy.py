"""Applies the Startup tab's "restart automatically if it crashes" policy
(config.yaml's startup.autorestart/restart_attempts/restart_delay_s) to
direwolf.service.

Deliberately not baked into the unit file at install time (see
install.sh): that left Restart=on-failure/RestartSec=10 fixed forever
regardless of what the wizard or config page's Startup tab actually said,
with no StartLimitBurst at all, so a crash loop just retried forever
instead of stopping after the configured number of attempts. This module
writes a systemd drop-in override instead
(scripts/apply-direwolf-restart-policy.sh, run via a sudoers NOPASSWD rule
scoped to exactly that script path, installed by install.sh), the same
pattern as gpsconfig.py/apply-gps-config.sh, so a later change on the
Startup tab takes effect without re-running the installer.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_HELPER = str(Path(__file__).resolve().parent.parent / "scripts" / "apply-direwolf-restart-policy.sh")

DEFAULT_RESTART_ATTEMPTS = 3
DEFAULT_RESTART_DELAY_S = 30


async def apply(startup_config: dict) -> None:
    """Re-applied on every normal boot (idempotent, same as
    gpsconfig.apply), and whenever the Startup tab is saved post-setup (see
    web/server.py's /api/config/save)."""
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
