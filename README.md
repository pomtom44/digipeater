# APRS Digipeater

A self-contained, Raspberry Pi-based APRS digipeater and IGate: a web dashboard and setup wizard wrapped around [Direwolf](https://github.com/wb2osz/direwolf), with an optional e-ink status display. Configure it from a phone or laptop over its own WiFi hotspot, no separate computer or command-line setup required.

## Features

- Digipeating and/or IGating (RX-only or RX & TX), fully configurable through a web UI
- Works over ethernet, existing WiFi, or its own hotspot if nothing else is available
- Offline vector maps for the dashboard, no internet required after initial setup
- Optional GPS for live position beaconing and system time sync
- Optional e-ink display for at-a-glance status
- Settings remain editable after setup, not just a one-time wizard

## Getting Started

See [`DEV_BUILD/SETUP.md`](DEV_BUILD/SETUP.md) for hardware wiring and installation.

For how it all works under the hood, see [`DEV_BUILD/OVERVIEW.md`](DEV_BUILD/OVERVIEW.md). For supported hardware and GPIO wiring specifics, see [`DEV_BUILD/SUPPORTED_HARDWARE.md`](DEV_BUILD/SUPPORTED_HARDWARE.md) and [`DEV_BUILD/PINOUT.md`](DEV_BUILD/PINOUT.md).

## Project Structure

- **`DEV_BUILD/`**: the active, current codebase. Everything above points here.
- **`ORIGINAL/`**: an earlier prototype, kept for reference only, not actively developed.
- **`TODO.md`**: known gaps and in-progress work.

## License

MIT, see [LICENSE](LICENSE).
