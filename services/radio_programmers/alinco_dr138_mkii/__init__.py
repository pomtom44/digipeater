"""Driver for the Alinco DR-138 MKII: builds channel 0's programming image and speaks its ERW-7 wire protocol."""

from pathlib import Path

import serial

MODEL = "Alinco DR-138 MKII"

_FACTORY_IMAGE_PATH = Path(__file__).parent / "factory_default.bin"
_FACTORY_IMAGE_BASE = 0x0100
_WRITE_START = 0x0100
_WRITE_END = 0x3ff0

# Wire protocol, see the byte-exact reference:
# https://github.com/pomtom44/Alinco-Radio-Programming-Values/blob/main/radios/alinco-dr138-mkii/alinco-dr138-mkii_protocol.md
_SERIAL_BAUD = 9600
_SERIAL_TIMEOUT = 10.0
_HANDSHAKE = b"PROGRAM"
_HANDSHAKE_READY = bytes([0x51, 0x58, 0x06])
_READ_CMD = 0x52
_WRITE_CMD = 0x57
_ACK = 0x06
_END_CMD = b"END"
_BLOCK_LEN = 0x10
_MANDATORY_PROBE_ADDR = 0x0040
_EXPECTED_ID = "DJ-138"

_CHANNEL0 = 0x2000  # channel 0's record start; this radio only ever targets channel 0
_TIME_OUT_TIMER_OFFSET = 0x022c

# Boots to memory (channel) mode on channel 0 rather than the factory default of VFO/frequency mode,
# since this driver only ever programs channel 0 -- there's nothing else to tune to. Display Mode and
# VFO/MR are set together: the radio's own menu auto-forces VFO/MR to MR when Display Mode=Channel,
# but that's UI-side logic, not guaranteed to apply to a directly-written image, so both are set here.
_DISPLAY_MODE_OFFSET = 0x0220
_VFO_MR_OFFSET = 0x0221
_MR_CHANNEL_OFFSET = 0x0222
_DISPLAY_MODE_CHANNEL = 0x01
_VFO_MR_MR = 0x01

_STEP_VALUES = {
    "2.5K": 0x00, "5K": 0x01, "6.25K": 0x02, "8.33K": 0x03, "10K": 0x04,
    "12.5K": 0x05, "20K": 0x06, "25K": 0x07, "30K": 0x08, "50K": 0x09,
}
_TX_POWER_VALUES = {"HIGH": 0x00, "MID": 0x04, "LOW": 0x08}
_SIGNALING_ENCODE = {"OFF": 0x00, "CTCSS": 0x01}
_SIGNALING_DECODE = {"OFF": 0x00, "CTCSS": 0x04}
_CTCSS_TABLE = {
    67.0: 1, 69.3: 2, 71.9: 3, 74.4: 4, 77.0: 5, 79.7: 6, 82.5: 7, 85.4: 8, 88.5: 9, 91.5: 10,
    94.8: 11, 97.4: 12, 100.0: 13, 103.5: 14, 107.2: 15, 110.9: 16, 114.8: 17, 118.8: 18, 123.0: 19,
    127.3: 20, 131.8: 21, 136.5: 22, 141.3: 23, 146.2: 24, 151.4: 25, 156.7: 26, 159.8: 27,
    162.2: 28, 165.5: 29, 167.9: 30, 171.3: 31, 173.8: 32, 177.3: 33, 179.9: 34, 183.5: 35,
    186.2: 36, 189.9: 37, 192.8: 38, 196.6: 39, 199.5: 40, 203.5: 41, 206.5: 42, 210.7: 43,
    218.1: 44, 225.7: 45, 229.1: 46, 233.6: 47, 241.8: 48, 250.3: 49, 254.1: 50,
}


def _encode_frequency(freq_hz: int) -> bytes:
    """4-byte RX/TX frequency: leading digit raw, then 3 BCD-pair bytes, units of 100Hz."""
    units = round(freq_hz / 100)
    digits = f"{units:07d}"

    def bcd(n: int) -> int:
        tens, ones = divmod(n, 10)
        return (tens << 4) | ones

    return bytes([int(digits[0]), bcd(int(digits[1:3])), bcd(int(digits[3:5])), bcd(int(digits[5:7]))])


def _encode_offset_magnitude(offset_hz: int) -> bytes:
    """3-byte duplex offset magnitude: BCD-pair bytes, units of 100Hz, no leading raw digit."""
    units = round(abs(offset_hz) / 100)
    digits = f"{units:06d}"

    def bcd(n: int) -> int:
        tens, ones = divmod(n, 10)
        return (tens << 4) | ones

    return bytes([bcd(int(digits[0:2])), bcd(int(digits[2:4])), bcd(int(digits[4:6]))])


def _encode_name(name: str) -> bytes:
    return name[:7].upper().ljust(7).encode("ascii", errors="replace")


def _build_overrides(radio_config: dict) -> dict:
    """Maps the user's radio config onto {offset: bytes} patches over the factory image."""
    freq_hz = round(float(radio_config["frequency_mhz"]) * 1_000_000)
    name = radio_config.get("name") or f"{freq_hz / 1_000_000:.3f}"
    power = {"MEDIUM": "MID"}.get((radio_config.get("power_level") or "HIGH").upper(), (radio_config.get("power_level") or "HIGH").upper())
    advanced = radio_config.get("advanced") or {}

    overrides = {
        _CHANNEL0 + 0x00: _encode_frequency(freq_hz),
        _CHANNEL0 + 0x13: _encode_name(name),
        # Boot to memory mode on channel 0, not VFO/frequency mode (see the constants above).
        _DISPLAY_MODE_OFFSET: bytes([_DISPLAY_MODE_CHANNEL]),
        _VFO_MR_OFFSET: bytes([_VFO_MR_MR]),
        _MR_CHANNEL_OFFSET: bytes([0x00]),
    }

    direction_bit = 0x01 if advanced.get("duplex_direction") == "+" else 0x00
    overrides[_CHANNEL0 + 0x0a] = bytes([_TX_POWER_VALUES.get(power, _TX_POWER_VALUES["HIGH"]) | direction_bit])

    if advanced.get("duplex_offset_hz"):
        overrides[_CHANNEL0 + 0x05] = _encode_offset_magnitude(int(advanced["duplex_offset_hz"]))

    encode_on = bool(advanced.get("ctcss_encode_hz"))
    decode_on = bool(advanced.get("ctcss_decode_hz"))
    if encode_on or decode_on:
        overrides[_CHANNEL0 + 0x0b] = bytes([
            _SIGNALING_ENCODE["CTCSS" if encode_on else "OFF"] | _SIGNALING_DECODE["CTCSS" if decode_on else "OFF"]
        ])
    if encode_on:
        overrides[_CHANNEL0 + 0x0c] = bytes([_CTCSS_TABLE[advanced["ctcss_encode_hz"]]])
    if decode_on:
        overrides[_CHANNEL0 + 0x0d] = bytes([_CTCSS_TABLE[advanced["ctcss_decode_hz"]]])

    if advanced.get("busy_lockout"):
        overrides[_CHANNEL0 + 0x1a] = bytes([0x02])  # Busy
    if advanced.get("time_out_timer_min"):
        overrides[_TIME_OUT_TIMER_OFFSET] = bytes([int(advanced["time_out_timer_min"])])

    return overrides


def build_image(radio_config: dict) -> bytearray:
    image = bytearray(_FACTORY_IMAGE_PATH.read_bytes())
    for addr, value in _build_overrides(radio_config).items():
        offset = addr - _FACTORY_IMAGE_BASE
        image[offset:offset + len(value)] = value
    return image


def _read_exact(ser: serial.Serial, n: int, what: str) -> bytes:
    data = ser.read(n)
    if len(data) != n:
        raise IOError(f"Timed out reading {what} (got {len(data)} of {n} bytes)")
    return data


def _expect(ser: serial.Serial, expected: bytes, what: str) -> None:
    got = _read_exact(ser, len(expected), what)
    if got != expected:
        raise IOError(f"Unexpected reply for {what}: expected {expected!r}, got {got!r}")


def _read_block(ser: serial.Serial, addr: int) -> bytes:
    cmd = bytes([_READ_CMD, addr >> 8, addr & 0xFF, _BLOCK_LEN])
    ser.write(cmd)
    ser.flush()
    _expect(ser, cmd, f"read echo @ {addr:#06x}")
    header = _read_exact(ser, 4, f"reply header @ {addr:#06x}")
    data = _read_exact(ser, _BLOCK_LEN, f"data @ {addr:#06x}")
    checksum = _read_exact(ser, 1, f"checksum @ {addr:#06x}")[0]
    if checksum != (sum(header[1:4]) + sum(data)) & 0xFF:
        raise IOError(f"Checksum mismatch @ {addr:#06x}")
    _expect(ser, bytes([_ACK]), f"ack @ {addr:#06x}")
    return data


def _write_block(ser: serial.Serial, addr: int, data: bytes) -> None:
    header = bytes([addr >> 8, addr & 0xFF, _BLOCK_LEN])
    checksum = (sum(header) + sum(data)) & 0xFF
    frame = bytes([_WRITE_CMD]) + header + data + bytes([checksum, 0x06])  # trailing 0x06 is MKII-specific
    ser.write(frame)
    ser.flush()
    _expect(ser, frame, f"write echo @ {addr:#06x}")
    _expect(ser, bytes([_ACK]), f"write ack @ {addr:#06x}")


def _handshake(ser: serial.Serial) -> str:
    ser.write(_HANDSHAKE)
    ser.flush()
    _expect(ser, _HANDSHAKE, "handshake echo")
    _expect(ser, _HANDSHAKE_READY, "handshake ready bytes")
    ser.write(bytes([0x02]))
    ser.flush()
    id_reply = _read_exact(ser, 9, "ID reply")
    # 8 bytes, not 7: `05` + "V100" + 2 variable bytes + a trailing 06 ack (see the protocol doc).
    # Leaving that ack unread shifts every subsequent read by one byte, corrupting the next echo check.
    version_reply = _read_exact(ser, 8, "version reply")
    if version_reply[-1] != _ACK:
        raise IOError(f"version reply missing trailing ack: {version_reply!r}")
    _read_block(ser, _MANDATORY_PROBE_ADDR)  # mandatory first read every session, or writes won't auto-reset
    return id_reply[1:8].decode("ascii", errors="replace").rstrip("\x00")


_TOTAL_BLOCKS = (_WRITE_END - _WRITE_START) // _BLOCK_LEN + 1


def program_sync(port: str, image: bytearray, on_progress=None) -> None:
    """Blocking; runs in a thread-pool executor, see radio_programmer.program_channel(). If given,
    on_progress(blocks_done, blocks_total) is called after each block write."""
    with serial.Serial(port=port, baudrate=_SERIAL_BAUD, timeout=_SERIAL_TIMEOUT) as ser:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        model = _handshake(ser)
        if _EXPECTED_ID not in model:
            raise IOError(f"radio ID reply {model!r} doesn't match expected {_EXPECTED_ID!r}")
        addr = _WRITE_START
        done = 0
        while addr <= _WRITE_END:
            offset = addr - _FACTORY_IMAGE_BASE
            _write_block(ser, addr, bytes(image[offset:offset + _BLOCK_LEN]))
            addr += _BLOCK_LEN
            done += 1
            if on_progress:
                on_progress(done, _TOTAL_BLOCKS)
        ser.write(_END_CMD)
        ser.flush()
        _expect(ser, _END_CMD + bytes([_ACK]), "END echo+ack")
        _expect(ser, bytes([_ACK]), "final ack")
