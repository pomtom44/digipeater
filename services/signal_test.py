"""RF-reach test: transmits an APRS message over RF via Direwolf, addressed to a nearby igate-enabled
station, to confirm this (RF-only) digipeater's signal actually reaches far enough to be gated onto
APRS-IS. The reply, if the far station's igate relays one back, is caught by packet_log.py's existing
KISS tail -- this module only builds and sends the outbound frame.
"""

import asyncio

# Matches services/packet_log.py's KISS constants: same protocol, same Direwolf instance.
_KISS_HOST = "127.0.0.1"
_KISS_PORT = 8001
_KISS_FEND = 0xC0
_KISS_FESC = 0xDB
_KISS_TFEND = 0xDC
_KISS_TFESC = 0xDD

_CONNECT_TIMEOUT_S = 5


def _encode_ax25_addr(callsign_ssid: str, *, is_last: bool) -> bytes:
    call, _, ssid_str = callsign_ssid.partition("-")
    ssid = int(ssid_str) if ssid_str else 0
    call_bytes = bytes(ord(c) << 1 for c in call.upper().ljust(6)[:6])
    # Reserved bits (5,6) set per convention; bit0 marks the last address in the chain.
    ssid_byte = ((ssid & 0x0F) << 1) | 0x60 | (0x01 if is_last else 0x00)
    return call_bytes + bytes([ssid_byte])


def _build_ax25_ui_frame(source: str, dest: str, path: list[str], info: bytes) -> bytes:
    addrs = [dest, source] + path
    frame = bytearray()
    for i, addr in enumerate(addrs):
        frame += _encode_ax25_addr(addr, is_last=(i == len(addrs) - 1))
    frame += bytes([0x03, 0xF0])  # control = UI frame, PID = no layer 3 protocol
    frame += info
    return bytes(frame)


def _kiss_escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == _KISS_FEND:
            out += bytes([_KISS_FESC, _KISS_TFEND])
        elif b == _KISS_FESC:
            out += bytes([_KISS_FESC, _KISS_TFESC])
        else:
            out.append(b)
    return bytes(out)


def _build_kiss_frame(ax25_frame: bytes) -> bytes:
    # 0x00 data-frame marker on KISS port/channel 0, matching packet_log.py's decode side.
    escaped = _kiss_escape(bytes([0x00]) + ax25_frame)
    return bytes([_KISS_FEND]) + escaped + bytes([_KISS_FEND])


async def send_ping(my_call: str, target_callsign: str, path: list[str], test_id: str) -> None:
    """Transmits an APRS message addressed to target_callsign, with test_id embedded in the text."""
    addressee = target_callsign.upper().ljust(9)
    info = f":{addressee}:PING {test_id}".encode("ascii")
    frame = _build_ax25_ui_frame(my_call.upper(), "APRS", path, info)
    kiss_frame = _build_kiss_frame(frame)
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_KISS_HOST, _KISS_PORT), timeout=_CONNECT_TIMEOUT_S,
        )
    except (OSError, asyncio.TimeoutError) as e:
        raise RuntimeError(f"Could not reach Direwolf's KISS port: {e}")
    try:
        writer.write(kiss_frame)
        await writer.drain()
    finally:
        writer.close()
