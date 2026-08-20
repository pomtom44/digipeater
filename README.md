# APRS Digipeater

**A self-contained, Raspberry Pi-based APRS digipeater and IGate with a full web dashboard, no laptop or command line required.**

Setting up an APRS digipeater or IGate normally means hand-editing [Direwolf](https://github.com/wb2osz/direwolf) config files over SSH, with no easy way to check status or change anything once it's running. This project wraps that setup in a guided wizard and web dashboard instead: point a phone or laptop at the Pi's own WiFi hotspot, answer a few questions, and it's on the air. Live station status, an offline map, and every setting stay reachable from that same dashboard afterward, not just at first boot.

### Why not just run Direwolf directly?

You still are, under the hood, this project doesn't replace Direwolf's TNC/modem, it drives it. What it adds is everything around Direwolf: a setup wizard instead of hand-written config files, a web dashboard for live status instead of SSH and log-watching, and a settings page for changing things afterward instead of editing config and restarting by hand.

## Features

- Digipeating and/or IGating (RX-only or RX & TX), fully configurable through a web UI
- Works over ethernet, existing WiFi, or its own hotspot if nothing else is available
- Supports different radio hardware: GPIO PTT, VOX, USB (CM108), or serial
- Live dashboard showing your station's status and map at a glance
- Offline vector maps for the dashboard, no internet required after initial setup
- Optional GPS for live position beaconing and system time sync
- Optional e-ink display for at-a-glance status

## Hardware

- Raspberry Pi (3B recommended, others may work, see [`SUPPORTED_HARDWARE.md`](SUPPORTED_HARDWARE.md))
- MicroSD card and power supply
- External USB audio device with both mic and headphone jacks (the Pi's own jack is playback-only)
OR
- Serial connection to a radio that supports audio over serial
- A radio with PTT control (Pin in, modified handset, etc)
OR
- A radio that supports PTT over serial / data connnections
- USB GPS module, for live position beaconing and system time sync
- Radio power relay, to power the radio on/off automatically
- E-ink display, for at-a-glance status without opening the dashboard

## Getting Started

1. Download the latest image from the [Releases page](https://github.com/pomtom44/digipeater/releases) and flash it with Raspberry Pi Imager
2. Assemble your hardware (skip anything you're not using)
3. Boot the Pi and follow the setup wizard from your phone or laptop, over its own WiFi hotspot

For the full walkthrough, see [`SETUP.md`](SETUP.md). For how it all works under the hood, see [`OVERVIEW.md`](OVERVIEW.md). For supported hardware and GPIO wiring specifics, see [`SUPPORTED_HARDWARE.md`](SUPPORTED_HARDWARE.md) and [`PINOUT.md`](PINOUT.md).

## Project Structure

- **`main.py`**, **`services/`**, **`display/`**, **`web/`**: the application itself.
- **`ORIGINAL/`**: an earlier prototype, kept for reference only, not actively developed.
- **`TODO.md`**: known gaps and in-progress work.

## License

MIT, see [LICENSE](LICENSE).

### Third-Party Licensing

This project drives or vendors:

- [Direwolf](https://github.com/wb2osz/direwolf) (GPL-2.0): run as a separate process, not modified or redistributed
- [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) (BSD-3-Clause): vendored in `web/static/maplibre/`
- [PMTiles](https://github.com/protomaps/PMTiles) (BSD-3-Clause): vendored in `web/static/maplibre/`
- [Waveshare e-Paper driver](https://github.com/waveshareteam/e-Paper) (MIT): ported in `display/waveshare/`

Python dependencies (FastAPI, Starlette, Pillow, and others, see [`requirements.txt`](requirements.txt)) are installed via pip and covered by their own licenses, not vendored in this repo.
