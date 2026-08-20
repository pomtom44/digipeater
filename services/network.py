"""Manages WiFi and ethernet via nmcli (NetworkManager)."""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_HOTSPOT_CON = "digipeater-hotspot"
_WIFI_CLIENT_CON = "digipeater-wifi"

# Pinned explicitly since it's shown on the e-ink screen and must be guaranteed correct.
HOTSPOT_IP = "10.42.0.1"


async def _nmcli(*args) -> tuple[int, str, str]:
    """Runs an nmcli command via sudo and returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "sudo", "-n", "nmcli", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode().strip(), err.decode().strip()


async def get_ip() -> dict:
    """Returns current IP addresses as {interface: ip}, using `ip addr` (no sudo needed)."""
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
    """Returns wlan0's IP if connected as a client; only meaningful before our hotspot starts."""
    ips = await get_ip()
    return ips.get("wlan0")


async def scan_wifi() -> list[dict]:
    """Scans for nearby WiFi networks, returning list of {ssid, signal, security}."""
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


async def connect_wifi(ssid: str, password: str) -> bool:
    """Creates (or replaces) a WiFi client connection profile and brings it up; autoconnect=yes."""
    await _nmcli("connection", "delete", _WIFI_CLIENT_CON)

    args = [
        "connection", "add",
        "type", "wifi",
        "ifname", "wlan0",
        "con-name", _WIFI_CLIENT_CON,
        "autoconnect", "yes",
        "ssid", ssid,
    ]
    if password:
        args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]

    code, out, err = await _nmcli(*args)
    if code != 0:
        logger.error("Failed to create WiFi client connection: %s", err)
        return False

    code, _, err = await _nmcli("connection", "up", _WIFI_CLIENT_CON)
    if code != 0:
        logger.error("Failed to connect to WiFi (SSID=%s): %s", ssid, err)
        return False

    logger.info("Connected to WiFi: SSID=%s", ssid)
    return True


async def setup_hotspot(ssid: str, password: str) -> bool:
    """Create or reconfigure the WiFi hotspot."""
    await _nmcli("connection", "delete", _HOTSPOT_CON)

    code, out, err = await _nmcli(
        "connection", "add",
        "type", "wifi",
        "ifname", "wlan0",
        "con-name", _HOTSPOT_CON,
        # autoconnect=no: the app decides at boot whether the hotspot is needed, not NetworkManager.
        "autoconnect", "no",
        "ssid", ssid,
        "mode", "ap",
        "ipv4.method", "shared",
        "ipv4.addresses", f"{HOTSPOT_IP}/24",
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
