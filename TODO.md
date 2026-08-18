# To Do Later

Known gaps in `DEV_BUILD`, collected in one place. See `DEV_BUILD/SUPPORTED_HARDWARE.md` and `DEV_BUILD/PINOUT.md` for hardware-specific detail.

## Not ported from `ORIGINAL/`

- **Radio CAT control** (Hamlib rig control, live frequency polling/display): `ORIGINAL/hardware/radio.py` had it; `DEV_BUILD`'s "Radio model"/"TX power level" dropdowns are placeholders with no behavior behind them.
- **Radio channel programmer's serial protocol** (Alinco DR-138T specific): `ORIGINAL/hardware/radio_programmer.py` had the real protocol; `DEV_BUILD`'s `services/radio_programmer.py` only has the capability-registry shape (`RADIO_CAPABILITIES`), not the protocol itself.

## Not fully implemented or broken

- Direwolf integration not tested against the real `direwolf` binary (sandbox can't run Linux binaries), only checked for well-formed config syntax.
- Generic 1.54" SPI e-Paper driver is a best-guess port, hardware not in hand, never verified.
- `services/packet_log.py`'s RF/IGate beacon-transmission detection (the regexes matching Direwolf's log wording for "beacon sent") is carried over verbatim from `ORIGINAL`, not re-verified against a real beacon transmit yet (no working audio device in hand this session, see `SUPPORTED_HARDWARE.md`).

## New nice to have features

- `AGWPORT` (would let third-party APRS clients use this station as a remote TNC), CSMA radio timing (`TXDELAY`/`TXTAIL`/`DWAIT`/`PERSIST`/`SLOTTIME`), and digipeat `NOID`/preemptive options: real Direwolf capabilities, never exposed in either codebase's wizard. (`KISSPORT` itself is now enabled, loopback only for `services/packet_log.py`'s own use, not exposed as a user-facing feature for external KISS clients.)
- Support more e-ink display models (only two exist today).
