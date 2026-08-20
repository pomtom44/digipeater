# To Do Later

Known gaps in this project, collected in one place. See `SUPPORTED_HARDWARE.md` and `PINOUT.md` for hardware-specific detail.

## Not ported from `ORIGINAL/`

- **Radio CAT control** (Hamlib rig control, live frequency polling/display): `ORIGINAL/hardware/radio.py` had it; this project's "Radio model"/"TX power level" dropdowns are placeholders with no behavior behind them.
- **Radio channel programmer's serial protocol** (Alinco DR-138T specific): `ORIGINAL/hardware/radio_programmer.py` had the real protocol; `services/radio_programmer.py` only has the capability-registry shape (`RADIO_CAPABILITIES`), not the protocol itself.

## Not fully implemented or broken

- Direwolf integration not tested against the real `direwolf` binary (sandbox can't run Linux binaries), only checked for well-formed config syntax.
- Waveshare 1.54inch e-Paper (Rev2.1) driver is now a source-verified port of Waveshare's own reference driver, but not yet run against the real panel (hardware in hand, not yet tested end to end).
- `services/packet_log.py`'s RF/IGate beacon-transmission detection now matches Direwolf's real TX log line format (source-verified against Direwolf 1.8.1's own source, replacing an old regex that never matched real output), but not yet confirmed against a real beacon transmit.

## New nice to have features

- `AGWPORT` (would let third-party APRS clients use this station as a remote TNC), CSMA radio timing (`TXDELAY`/`TXTAIL`/`DWAIT`/`PERSIST`/`SLOTTIME`), and digipeat `NOID`/preemptive options: real Direwolf capabilities, never exposed in either codebase's wizard. (`KISSPORT` itself is now enabled, loopback only for `services/packet_log.py`'s own use, not exposed as a user-facing feature for external KISS clients.)
- Support more e-ink display models (only two exist today).
