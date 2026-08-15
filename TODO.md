# To Do Later

Known gaps in `DEV_BUILD`, collected in one place. See `DEV_BUILD/SUPPORTED_HARDWARE.md` and `DEV_BUILD/PINOUT.md` for hardware-specific detail.

## Not ported from `ORIGINAL/`

- **Real heard-stations / packet history**: parsing Direwolf's live output into position/weather packets and a persisted history. `ORIGINAL/core/log_parser.py` (parsed stdout via `aprslib`) and `core/packet_store.py` (deduped/persisted to a JSON history file) did this; `DEV_BUILD`'s dashboard fakes it with hardcoded sample data (`SAMPLE_HEARD_STATIONS` etc. in `normal.html`). The single biggest missing piece of real functionality carried over from `ORIGINAL`.
- **Radio CAT control** (Hamlib rig control, live frequency polling/display): `ORIGINAL/hardware/radio.py` had it; `DEV_BUILD`'s "Radio model"/"TX power level" dropdowns are placeholders with no behavior behind them.
- **Radio channel programmer's serial protocol** (Alinco DR-138T specific): `ORIGINAL/hardware/radio_programmer.py` had the real protocol; `DEV_BUILD`'s `services/radio_programmer.py` only has the capability-registry shape (`RADIO_CAPABILITIES`), not the protocol itself.

## Not fully implemented or broken

- Direwolf integration not tested against the real `direwolf` binary (sandbox can't run Linux binaries), only checked for well-formed config syntax.
- Generic 1.54" SPI e-Paper driver is a best-guess port, hardware not in hand, never verified.

## New nice to have features

- `AGWPORT`/`KISSPORT` (would let third-party APRS clients use this station as a remote TNC), CSMA radio timing (`TXDELAY`/`TXTAIL`/`DWAIT`/`PERSIST`/`SLOTTIME`), and digipeat `NOID`/preemptive options: real Direwolf capabilities, never exposed in either codebase's wizard.
- Support more e-ink display models (only two exist today).
