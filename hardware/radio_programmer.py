"""Alinco DR-138T channel memory programmer via ERW-4 serial cable.

Hardware: ERW-4 cable (PL-2303 USB-serial chipset), appears as /dev/ttyUSB0
(Linux) or COMn (Windows, used only for capture/testing).
Serial: 9600 baud, 8N1, no flow control.

Protocol status: CONFIRMED — captured 2026-07-06 via com0com + a custom
transparent serial-bridge logger (tools/serial_sniffer.py) sitting between
the real ERW-4 port and the Alinco DR_X38.exe software, for both a memory
read and a memory write (channel name changed "APRS" -> "APRS1", frequency
144.575 -> 144.585 MHz). Checksums verified on all 1023+1008 blocks seen
across both captures.

Wire protocol (half-duplex clone-mode, radio echoes every command back
before replying):
    1. PC -> "PROGRAM" (7 bytes ASCII)          radio echoes "PROGRAM"
    2. radio -> 0x51 0x58 0x06                    (unprompted "ready" bytes)
    3. PC -> 0x02                                 (ID query)
       radio -> 0x02 + 7-byte model ID + 0x00 + 1 byte      (e.g. "IDJ-138")
       radio -> 0x56 + "100" + 0xE0 0x00 + 0x06             (version "V100")
    4. Per 16-byte block, address 0x0010..0x3FF0 (0x0000-0x000F is never
       touched by the official tool and is left alone here too):
         PC -> 'R' addr_hi addr_lo 0x10           radio echoes same 4 bytes
         radio -> 'W' addr_hi addr_lo 0x10 + data[16] + checksum
         radio -> 0x06                            (ack, ready for next block)
       Same 4/21/1-byte shape for writes, PC sends the 'W' frame instead.
    5. PC -> "END"                                radio echoes "END" + 0x06,
                                                   then a final 0x06.

    checksum = sum(addr_hi, addr_lo, length, *data) & 0xFF   (confirmed on
    every block of both captures, 0 mismatches).

Total memory image is 0x4000 (16384) bytes. Channel 0's record lives at a
fixed offset 0x2000, 0x20 (32) bytes long:
    +0x00        frequency, 4 bytes (see _encode_frequency/_decode_frequency)
    +0x04..0x07  unknown/reserved (all zero on this radio; left untouched)
    +0x08        0x01 — channel-enabled flag (left untouched, already set)
    +0x09..0x12  unknown/reserved (left untouched)
    +0x13..0x19  channel name, 7 ASCII bytes, space-padded
    +0x1A..0x1F  unknown/reserved (left untouched)
Mode / CTCSS / power fields were never exercised in the capture (only name
and frequency changed), so their offsets are NOT known — see the warning
logged in _patch_channel() if a caller requests anything other than the
default FM_WIDE / no-CTCSS / HIGH power.

Safety note: the official DR_X38.exe "Write CH Data to Radio" appears to
zero out large chunks of memory outside the edited channel on every write
(diffed against a full read taken moments earlier — see addresses 0x3900-
0x3FFF, which look like S-meter/AFC calibration tables). This module does a
read-modify-write of its own full read instead, so it only ever changes the
frequency/name bytes of the target channel and leaves everything else,
including that calibration data, exactly as read from the radio.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ── APRS frequency presets (Hz) ──────────────────────────────────────────────
APRS_PRESETS = {
    "NZ":  144_575_000,   # New Zealand / Pacific
    "EU":  144_800_000,   # Europe / UK
    "NA":  144_390_000,   # North America
    "AU":  145_175_000,   # Australia
}


# ── Protocol constants ────────────────────────────────────────────────────────
_SERIAL_BAUD = 9600
_SERIAL_TIMEOUT = 10.0   # seconds

_HANDSHAKE = b"PROGRAM"
_HANDSHAKE_READY = bytes([0x51, 0x58, 0x06])
_ID_QUERY = bytes([0x02])
_READ_CMD = 0x52   # 'R'
_WRITE_CMD = 0x57  # 'W'
_ACK = 0x06
_END_CMD = b"END"

_BLOCK_LEN = 0x10
_FIRST_BLOCK_ADDR = 0x0010
_MEMORY_SIZE = 0x4000

_CHANNEL_0_OFFSET = 0x2000
_CHANNEL_RECORD_SIZE = 0x20   # stride for channels > 0 is unverified — this
                              # programmer only ever targets channel 0
_FREQ_LEN = 4
_NAME_OFFSET = 0x13
_NAME_LEN = 7


# ── Data types ────────────────────────────────────────────────────────────────
class ProgrammerState(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    READING = "reading"
    WRITING = "writing"
    DONE = "done"
    ERROR = "error"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass
class ChannelSettings:
    frequency_hz: int        # e.g. 144_575_000
    mode: str                # "FM_WIDE" | "FM_NARROW" — not yet implemented
    ctcss_hz: float          # 0.0 = none — not yet implemented
    power: str               # "HIGH" | "LOW" — not yet implemented
    name: str                # up to 7 chars; auto-set to freq if blank


# ── Programmer ────────────────────────────────────────────────────────────────
class RadioProgrammer:
    def __init__(self, config: dict):
        self.enabled: bool = config.get("enabled", False)
        self._port: str = config.get("port", "/dev/ttyUSB0")
        self._channel: int = config.get("channel", 0)
        self.state: ProgrammerState = ProgrammerState.IDLE
        self.last_error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None

    # ── Public API ─────────────────────────────────────────────────────────

    async def program(self, settings: ChannelSettings) -> bool:
        """Start a programming job. Returns False if already running."""
        if self._task and not self._task.done():
            return False
        if not settings.name:
            mhz = settings.frequency_hz / 1_000_000
            settings.name = f"{mhz:.3f}"[:_NAME_LEN]
        self.state = ProgrammerState.CONNECTING
        self.last_error = None
        self._task = asyncio.create_task(self._run(settings))
        return True

    def status(self) -> dict:
        return {
            "state": self.state.value,
            "error": self.last_error,
            "port": self._port,
        }

    # ── Internal ───────────────────────────────────────────────────────────

    async def _run(self, settings: ChannelSettings) -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._program_sync, settings
            )
        except ImportError:
            self.state = ProgrammerState.ERROR
            self.last_error = "pyserial not installed — run: pip install pyserial"
            logger.error(self.last_error)
        except Exception as e:
            self.state = ProgrammerState.ERROR
            self.last_error = str(e)
            logger.error("Radio programming failed: %s", e)

    def _program_sync(self, settings: ChannelSettings) -> None:
        """Blocking serial communication — runs in a thread-pool executor."""
        import serial   # pyserial

        with serial.Serial(
            port=self._port,
            baudrate=_SERIAL_BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=_SERIAL_TIMEOUT,
            rtscts=False,
            dsrdtr=False,
        ) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            model = _handshake(ser)
            logger.info("Radio programmer: connected to %s (%s)", self._port, model)

            self.state = ProgrammerState.READING
            memory = bytearray(_MEMORY_SIZE)
            addr = _FIRST_BLOCK_ADDR
            while addr < _MEMORY_SIZE:
                memory[addr:addr + _BLOCK_LEN] = _read_block(ser, addr)
                addr += _BLOCK_LEN
            logger.info(
                "Radio programmer: read %d bytes from radio",
                _MEMORY_SIZE - _FIRST_BLOCK_ADDR,
            )

            self.state = ProgrammerState.WRITING
            _patch_channel(memory, self._channel, settings)
            logger.info(
                "Radio programmer: patched channel %d -> %d Hz (%r)",
                self._channel, settings.frequency_hz, settings.name,
            )

            addr = _FIRST_BLOCK_ADDR
            while addr < _MEMORY_SIZE:
                _write_block(ser, addr, bytes(memory[addr:addr + _BLOCK_LEN]))
                addr += _BLOCK_LEN

            _end_session(ser)
            logger.info("Radio programmer: write complete")

        self.state = ProgrammerState.DONE


# ── Low-level protocol I/O ────────────────────────────────────────────────────

def _checksum(payload: bytes) -> int:
    return sum(payload) & 0xFF


def _read_exact(ser, n: int, what: str = "") -> bytes:
    data = ser.read(n)
    if len(data) != n:
        raise IOError(
            f"Timed out reading {what or n} from radio (got {len(data)} of {n} bytes). "
            "Check the cable, confirm the radio is in RS-232C clone mode, "
            "and that the baud rate matches."
        )
    return data


def _expect(ser, expected: bytes, what: str = "") -> None:
    got = _read_exact(ser, len(expected), what)
    if got != expected:
        raise IOError(f"Unexpected reply from radio for {what}: expected {expected!r}, got {got!r}")


def _handshake(ser) -> str:
    ser.write(_HANDSHAKE)
    ser.flush()
    _expect(ser, _HANDSHAKE, "handshake echo")
    _expect(ser, _HANDSHAKE_READY, "handshake ready bytes")

    ser.write(_ID_QUERY)
    ser.flush()
    id_reply = _read_exact(ser, 10, "ID reply")
    _read_exact(ser, 7, "version reply")
    return id_reply[1:8].decode("ascii", errors="replace").rstrip("\x00")


def _read_block(ser, addr: int) -> bytes:
    cmd = bytes([_READ_CMD, addr >> 8, addr & 0xFF, _BLOCK_LEN])
    ser.write(cmd)
    ser.flush()
    _expect(ser, cmd, f"read echo @ {addr:#06x}")

    header = _read_exact(ser, 4, f"reply header @ {addr:#06x}")
    if header[0] != _WRITE_CMD or header[1] != cmd[1] or header[2] != cmd[2] or header[3] != _BLOCK_LEN:
        raise IOError(f"Malformed read reply header @ {addr:#06x}: {header!r}")
    data = _read_exact(ser, _BLOCK_LEN, f"data @ {addr:#06x}")
    checksum = _read_exact(ser, 1, f"checksum @ {addr:#06x}")[0]

    expected = _checksum(header[1:] + data)
    if checksum != expected:
        raise IOError(f"Checksum mismatch @ {addr:#06x}: expected {expected:#04x}, got {checksum:#04x}")
    _expect(ser, bytes([_ACK]), f"ack @ {addr:#06x}")
    return data


def _write_block(ser, addr: int, data: bytes) -> None:
    assert len(data) == _BLOCK_LEN
    header = bytes([addr >> 8, addr & 0xFF, _BLOCK_LEN])
    checksum = _checksum(header + data)
    frame = bytes([_WRITE_CMD]) + header + data + bytes([checksum])

    ser.write(frame)
    ser.flush()
    _expect(ser, frame, f"write echo @ {addr:#06x}")
    _expect(ser, bytes([_ACK]), f"ack @ {addr:#06x}")


def _end_session(ser) -> None:
    ser.write(_END_CMD)
    ser.flush()
    _expect(ser, _END_CMD, "END echo")
    _expect(ser, bytes([_ACK]), "END ack")
    _expect(ser, bytes([_ACK]), "final ack")


# ── Memory format helpers ─────────────────────────────────────────────────────

def _bcd(n: int) -> int:
    tens, ones = divmod(n, 10)
    return (tens << 4) | ones


def _unbcd(b: int) -> int:
    return (b >> 4) * 10 + (b & 0x0F)


def _encode_frequency(freq_hz: int) -> bytes:
    """4-byte frequency encoding, confirmed from capture.

    144_575_000 Hz -> b'\\x01\\x44\\x57\\x50'  (144.5750 MHz)
    144_585_000 Hz -> b'\\x01\\x44\\x58\\x50'  (144.5850 MHz, only the 3rd
    byte changes for a 10 kHz step — matches the captured "APRS"->"APRS1"
    write, where 0x57 became 0x58 and nothing else in the frequency did).

    Layout: units of 100 Hz as a 7-digit decimal number; digit 0 stored as a
    raw byte, the remaining 3 digit-pairs as BCD.
    """
    units = round(freq_hz / 100)
    s = f"{units:07d}"
    if len(s) != 7 or units < 0:
        raise ValueError(f"Frequency {freq_hz} Hz is out of the encodable range")
    return bytes([int(s[0]), _bcd(int(s[1:3])), _bcd(int(s[3:5])), _bcd(int(s[5:7]))])


def _decode_frequency(data: bytes) -> int:
    digit0, b1, b2, b3 = data[0], data[1], data[2], data[3]
    units = int(f"{digit0}{_unbcd(b1):02d}{_unbcd(b2):02d}{_unbcd(b3):02d}")
    return units * 100


def _encode_name(name: str) -> bytes:
    return name[:_NAME_LEN].upper().ljust(_NAME_LEN).encode("ascii", errors="replace")


def _decode_name(data: bytes) -> str:
    return data[:_NAME_LEN].decode("ascii", errors="replace").rstrip()


def _patch_channel(memory: bytearray, channel: int, settings: ChannelSettings) -> None:
    offset = _CHANNEL_0_OFFSET + channel * _CHANNEL_RECORD_SIZE
    if offset + _CHANNEL_RECORD_SIZE > len(memory):
        raise ValueError(f"channel {channel} is out of range for this radio")

    memory[offset:offset + _FREQ_LEN] = _encode_frequency(settings.frequency_hz)
    name_off = offset + _NAME_OFFSET
    memory[name_off:name_off + _NAME_LEN] = _encode_name(settings.name)

    if settings.mode != "FM_WIDE" or settings.ctcss_hz or settings.power != "HIGH":
        logger.warning(
            "Radio programmer: mode/CTCSS/power byte offsets are not yet "
            "reverse-engineered (only frequency and name were captured). "
            "Requested mode=%s ctcss_hz=%s power=%s were NOT written.",
            settings.mode, settings.ctcss_hz, settings.power,
        )


def build_settings_from_config(cfg: dict) -> ChannelSettings:
    """Build ChannelSettings from the radio_programmer config dict."""
    rp = cfg.get("radio_programmer", {})
    freq_hz = int(rp.get("frequency_hz", APRS_PRESETS["NZ"]))
    mode = rp.get("mode", "FM_WIDE")
    ctcss_hz = float(rp.get("ctcss_hz", 0.0))
    power = rp.get("power", "HIGH")
    mhz = freq_hz / 1_000_000
    name = rp.get("name") or f"{mhz:.3f}"[:_NAME_LEN]
    return ChannelSettings(
        frequency_hz=freq_hz,
        mode=mode,
        ctcss_hz=ctcss_hz,
        power=power,
        name=name,
    )
