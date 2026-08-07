"""Manages WiFi and ethernet via nmcli (NetworkManager)."""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_HOTSPOT_CON = "digipeater-hotspot"


async def _nmcli(*args) -> tuple[int, str, str]:
    """Run an nmcli command and return (returncode, stdout, stderr).

    Runs via sudo — creating/modifying NetworkManager connections (e.g. the
    hotspot) needs root, and this service runs as a normal user. install.sh
    installs a sudoers rule scoping NOPASSWD access to nmcli specifically,
    not blanket root access.
    """
    proc = await asyncio.create_subprocess_exec(
        "sudo", "-n", "nmcli", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode().strip(), err.decode().strip()


async def get_ip() -> dict:
    """Return current IP addresses. Returns dict of {interface: ip}."""
    code, out, _ = await _nmcli("-t", "-f", "IP4.ADDRESS,DEVICE", "device", "show")
    ips = {}
    current_device = None
    for line in out.splitlines():
        if line.startswith("DEVICE:"):
            current_device = line.split(":", 1)[1]
        elif line.startswith("IP4.ADDRESS") and current_device:
            addr = line.split(":", 1)[1].split("/")[0]
            if addr:
                ips[current_device] = addr
    return ips


async def get_ethernet_ip() -> Optional[str]:
    """Return the IP of the first wired ethernet interface, or None if not connected."""
    ips = await get_ip()
    for iface, addr in ips.items():
        name = iface.lower()
        if name.startswith("wlan") or name == "lo":
            continue
        if name.startswith("eth") or name.startswith("en"):
            return addr
    return None


async def setup_hotspot(ssid: str, password: str) -> bool:
    """Create or reconfigure the WiFi hotspot."""
    # Remove existing connection if present
    await _nmcli("connection", "delete", _HOTSPOT_CON)

    code, out, err = await _nmcli(
        "connection", "add",
        "type", "wifi",
        "ifname", "wlan0",
        "con-name", _HOTSPOT_CON,
        "autoconnect", "yes",
        "ssid", ssid,
        "mode", "ap",
        "ipv4.method", "shared",
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", password,
    )
    if code != 0:
        logger.error("Failed to create hotspot: %s", err)
        return False

    code, _, err = await _nmcli("connection", "up", _HOTSPOT_CON)
    if code != 0:
        logger.error("Failed to bring up hotspot: %s", err)
        return False

    logger.info("Hotspot started: SSID=%s", ssid)
    return True
