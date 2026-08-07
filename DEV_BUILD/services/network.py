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
    """Return current IP addresses. Returns dict of {interface: ip}.

    Uses `ip addr` rather than `nmcli device show` — nmcli's device-name
    field there is the dotted `GENERAL.DEVICE`, not bare `DEVICE`, which a
    prior version of this function filtered for incorrectly (silently
    matching nothing, so no address ever got attributed to a device). `ip`
    has a flat, unambiguous format and doesn't need sudo either.
    """
    proc = await asyncio.create_subprocess_exec(
        "ip", "-4", "-o", "addr", "show",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    ips = {}
    for line in out.decode().splitlines():
        # e.g. "2: eth0    inet 192.168.1.42/24 brd ... scope global eth0"
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "inet":
            iface = parts[1]
            addr = parts[3].split("/")[0]
            ips[iface] = addr
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


async def get_wifi_client_ip() -> Optional[str]:
    """Return wlan0's IP if it already has one. Only meaningful when called
    BEFORE our own hotspot is started — at that point an IP here can only
    mean wlan0 is connected to some other network as a client, not our AP."""
    ips = await get_ip()
    return ips.get("wlan0")


async def scan_wifi() -> list[dict]:
    """Scan for nearby WiFi networks. Returns list of {ssid, signal, security}.

    Works even while wlan0 is currently our own hotspot (AP mode) — scanning
    is a passive listen, unlike actually connecting, which needs to leave AP
    mode and would drop the hotspot the caller is likely using right now.
    """
    await _nmcli("device", "wifi", "rescan")
    await asyncio.sleep(2)
    code, out, _ = await _nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list")
    networks = []
    seen = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] and parts[0] not in seen:
            seen.add(parts[0])
            networks.append({
                "ssid": parts[0],
                "signal": parts[1] if len(parts) > 1 else "",
                "security": parts[2] if len(parts) > 2 else "",
            })
    return networks


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
