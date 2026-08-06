"""Manages WiFi and ethernet via nmcli (NetworkManager)."""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_HOTSPOT_CON = "digipeater-hotspot"
_WIFI_CON = "digipeater-wifi"


async def _nmcli(*args) -> tuple[int, str, str]:
    """Run an nmcli command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "nmcli", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode().strip(), err.decode().strip()


async def get_ip(interface: str = None) -> dict:
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


async def connect_wifi(ssid: str, password: str) -> bool:
    """Connect to an existing WiFi network."""
    await _nmcli("connection", "delete", _WIFI_CON)

    code, _, err = await _nmcli(
        "device", "wifi", "connect", ssid,
        "password", password,
        "name", _WIFI_CON,
    )
    if code != 0:
        logger.error("Failed to connect to WiFi %s: %s", ssid, err)
        return False

    logger.info("Connected to WiFi: %s", ssid)
    return True


async def disable_wifi() -> bool:
    """Disable WiFi entirely."""
    code, _, err = await _nmcli("radio", "wifi", "off")
    if code != 0:
        logger.error("Failed to disable WiFi: %s", err)
        return False
    logger.info("WiFi disabled")
    return True


async def wifi_status() -> str:
    """Return current WiFi state string."""
    code, out, _ = await _nmcli("-t", "-f", "WIFI", "radio")
    return out.strip()


async def scan_wifi() -> list[dict]:
    """Scan for nearby WiFi networks. Returns list of {ssid, signal, security}."""
    await _nmcli("device", "wifi", "rescan")
    await asyncio.sleep(2)
    code, out, _ = await _nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list")
    networks = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0]:
            networks.append({
                "ssid": parts[0],
                "signal": parts[1] if len(parts) > 1 else "",
                "security": parts[2] if len(parts) > 2 else "",
            })
    return networks


async def monitor_wifi_connection(ssid: str, on_disconnect: callable, interval: int = 30) -> None:
    """Continuously check WiFi connection and attempt reconnect if lost."""
    while True:
        await asyncio.sleep(interval)
        code, out, _ = await _nmcli("-t", "-f", "GENERAL.STATE", "device", "show", "wlan0")
        if "connected" not in out.lower():
            logger.warning("WiFi connection lost — attempting reconnect...")
            if on_disconnect:
                result = on_disconnect()
                if asyncio.iscoroutine(result):
                    await result
            await _nmcli("connection", "up", _WIFI_CON)
