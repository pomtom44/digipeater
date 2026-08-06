# APRS Digipeater

A Raspberry Pi-based APRS digipeater with a web management interface. Runs [Direwolf](https://github.com/wb2osz/direwolf) as the APRS engine and provides a browser-based UI for configuration, control, and live monitoring.

## Features

- **Web interface** — configure, start/stop, and monitor from any browser on the local network
- **Live map** — heard stations plotted in real time with APRS symbols, traces, and track history
- **Flexible modes** — RX only, digipeater, igate, beacon — enable any combination
- **GPS integration** — automatic beacon coordinates, GPS fix status on startup
- **Power control** — timed power sequencing for the radio, with automatic recovery on crash
- **Status display** — rotating at-a-glance status pages (callsign, GPS, last heard, last beacon)
- **Offline map** — pre-cache tiles for a region for deployments without internet
- **First-boot wizard** — guided network and station setup on a fresh install
- **Radio control** — automatic control of radio settings for supported hardware

## Quick Start

See [SETUP.md](SETUP.md) for the full installation guide.

**In brief:**
1. Flash Raspberry Pi OS Bookworm Lite to an SD card using Raspberry Pi Imager
2. Enable SSH and set a hostname (`digipeater`) in the Imager settings
3. Boot the Pi and SSH in
4. Run the install script:

```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/install.sh | bash
```

5. After reboot, open `http://digipeater.local:8080` in a browser and follow the setup wizard

## Configuration

Recommended to use the web based setup wizard, however if required, you can edit the config file manually

Copy `config.example.yaml` to `config.yaml` and edit as needed. The web interface writes this file on save — direct editing is also supported while Direwolf is stopped.

`config.yaml` is in `.gitignore` and should never be committed — it contains callsign, passwords, and passcodes.

## Required Hardware

| Component | Notes |
|-----------|-------|
| Raspberry Pi 3B or later | Tested on Pi 3B |
| USB audio adapter | For soundcard TNC mode |
| GPS module | Serial NMEA, e.g. u-blox Neo-6M |
| Power relay | GPIO-controlled, for radio power switching |

## Supported Hardware

### Screens

*Driver code is complete for all models below, but untested against real hardware — verification pending until each unit is in hand.*

| Model | Notes |
|-------|-------|
| Waveshare 1.54" e-Paper HAT | 200×200, SSD1681 — default |
| Waveshare 2.13" e-Paper HAT | 250×122, SSD1680 |
| Waveshare 2.9" e-Paper HAT | 296×128, SSD1680 |
| Waveshare 4.2" e-Paper HAT | 400×300, UC8176 |

### Radios

| Model | Notes |
|-------|-------|
| Any Hamlib/rigctld-supported radio | CAT frequency control |
| Alinco DR-138T (via ERW-4 cable) | One-click channel programming |

## Project Structure

```
core/        APRS logic — Direwolf manager, config generator, log parser, packet store
hardware/    Hardware drivers — GPIO relay, GPS serial reader, radio CAT control, channel programmer
display/     E-ink display — page rotation, abstract driver interface, Waveshare HAT drivers
services/    System services — network (nmcli), NTP/GPS time sync, tile cache
web/         FastAPI web server, WebSocket, frontend
```

## Contributing

Issues and pull requests are welcome. This started as a personal build for a specific deployment, so please open an issue to discuss any larger change before sending a PR.

## License

MIT — see [LICENSE](LICENSE)
