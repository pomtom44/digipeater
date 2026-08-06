# APRS Digipeater — Project Overview

## Target Platform

**Primary hardware:** Raspberry Pi 3B. Code should be modular so hardware-specific components (GPIO, display driver) can be swapped for future Pi models without rewriting application logic.

**Recommended OS:** Raspberry Pi OS Bookworm (64-bit).
- Ships with NetworkManager as default — `nmcli` works out of the box for hotspot and WiFi client management
- Python 3.11+, `apt install direwolf` available
- `avahi-daemon` for mDNS (`digipeater.local`)

**Direwolf:** installed via `apt`, binary at `/usr/bin/direwolf`.

**GPIO library:** `gpiozero` — abstracts pin numbering across Pi hardware revisions.

**mDNS hostname:** `digipeater.local` — accessible on the local network without knowing the IP.

**First boot defaults:**
- Hotspot SSID: `Digipeater`
- Hotspot password: `Digipeater`

---

## Architecture

Direwolf runs as a standalone background process and handles everything APRS — audio in/out, packet decoding, digipeating, beaconing, igate. Once running, it has no dependency on this application.

This application manages Direwolf and the attached hardware:

```
[GPS Module]   [Power Relay]   [E-Ink Display]
      ↓               ↓                ↑
 [This application]  ←→  config editor + process control + log viewer
                              ↕ (stdout/stderr only)
                         [Direwolf]          ← fully self-contained once started
                              ↕
                    [Radio / Soundcard]
                              ↕
                         [Web Browser]
```

---

## Responsibilities

| Area               | What the app does                                              |
|--------------------|----------------------------------------------------------------|
| **Config**         | UI to edit station settings, writes `direwolf.conf` on save   |
| **Direwolf**       | Start / stop the process, stream stdout/stderr to web UI       |
| **Power relay**    | Turn the radio on or off via GPIO                             |
| **GPS**            | Read current location, feed into beacon config automatically   |
| **E-ink display**  | Show current status, Direwolf state, and GPS fix locally       |

---

## Hardware

### Power Relay
Controls power to the radio via GPIO. Pin number is fixed in `config.yaml` (default provided). Powered on when Direwolf is starting — a 10-second delay follows to allow the radio to initialise before the rest of the startup sequence continues. Powered off when Direwolf stops or errors out.

### GPS
Provides live location. Used to populate beacon coordinates in `direwolf.conf` automatically. Read via serial (NMEA) or USB GPS receiver.

### Radio CAT Control *(optional)*
For CAT-capable radios (`hardware/radio.py`). When `radio.enabled` is set, `RadioController` starts `rigctld` (Hamlib) as a subprocess on app launch and talks to it over TCP on `localhost:4532`. Exposes async `get_frequency()` / `set_frequency()`; falls back gracefully if `rigctld` isn't installed or the radio isn't connected. A background task polls frequency every 5 seconds. Config page: enable toggle, Hamlib model number, CAT serial port, CAT baud. Dashboard: a "Radio" sidebar section (hidden when disabled) shows current frequency in MHz, three regional presets (144.390 NA / 144.800 EU / 144.575 NZ-Pacific), and a manual MHz input.

### Channel Programmer *(optional)*
For radios without CAT support (`hardware/radio_programmer.py`) — writes the APRS frequency and channel name directly into a memory channel over the radio's serial programming cable. See README for the currently supported radio model. Mode, CTCSS/DCS tone, and power level are accepted in config but not yet implemented — a warning is logged rather than guessing undocumented byte offsets.

### E-Ink Display
Driven through a hardware abstraction layer (`display/base.py` / `display/waveshare/`) so any supported screen can be selected from the config page without changing application code — see README for the current list of supported models and their sizes. Driver code is complete for each, but none have been verified against real hardware yet.

Displays key status without needing a browser or monitor attached. Rotates through the following pages on a timed interval:

| Page | Content |
|------|---------|
| **Status** | Direwolf state (running / stopped / error), radio power state, IP address |
| **Config** | Active modes (RX only / igate / digipeat), callsign, start mode |
| **Location** | Source: Fixed or GPS. Coordinates. If GPS: accuracy and fix quality |
| **Last Beacon** | Timestamp and content of the last beacon transmitted |
| **Last Heard** | Callsign, timestamp, and packet type of the most recently heard station |

Each page refreshes its content when rotated to. The display does not continuously redraw — only updates when the page changes or a state change occurs, to minimise e-ink refresh flicker.

The rotation is fully configurable in `config.yaml` — each page can be enabled or disabled, reordered, and given its own display duration:

```yaml
display:
  pages:
    - id: status
      enabled: true
      duration: 10        # seconds
    - id: config
      enabled: true
      duration: 10
    - id: location
      enabled: true
      duration: 15
    - id: last_beacon
      enabled: true
      duration: 10
    - id: last_heard
      enabled: true
      duration: 10
```

Pages are shown in the order listed. Disabled pages are skipped entirely. Display config is editable from the config page — pages can be toggled, reordered by drag, and durations adjusted. Changes take effect immediately without restarting.

**Override states** — the display pauses rotation and shows a full-screen message for:
- Direwolf startup sequence (relay on, GPS wait, launch)
- Direwolf crash / repeated failure
- GPS error

---

## Order of Operations

### Every Boot — Config Check
On boot, the app checks whether a valid `config.yaml` exists.
- If missing or unreadable → treat as first boot, run the full setup flow
- If present → skip setup, apply saved network and system config

---

### Step 1 — Network Setup (First Boot Only)

1. Device boots
2. WiFi hotspot is created with a default SSID/password
3. If ethernet is connected, it attempts DHCP
4. Hotspot SSID, password, and ethernet IP (if available) are shown on the e-ink screen
5. **Nothing else starts**

6. User connects to the hotspot or ethernet IP and opens the web interface
7. Web interface presents three network options:
   - **Ethernet only** — disables WiFi entirely
   - **WiFi hotspot** — prompts for custom SSID and password
   - **WiFi client** — prompts for SSID and password of network to join

8. User submits choice
9. System applies network config and restarts networking
10. E-ink screen shows progress and outcome

11. Once networking is stable → **proceed to Step 2**

**Subsequent boots** — saved network config is applied automatically:
- Ethernet only: WiFi stays off
- WiFi hotspot: hotspot starts with saved SSID/password
- WiFi client: attempts to connect to saved network; if it fails, retries continuously and shows status on screen
- If both ethernet and WiFi are active, both interfaces expose the web interface

---

### Step 2 — Core System Setup (First Boot Only)

E-ink screen shows "Connect to configure" with the IP address.

User opens the web interface. A setup wizard collects the following in order:

**Interface**
- Serial (hardware TNC via serial port) — enter device path
- Audio TNC (soundcard / onboard Pi audio) — select input and output device from a dropdown populated by querying the OS at page load

**PTT** *(TX only — hidden if Listen Only)*
- Dropdown: GPIO pin, Serial RTS, Serial DTR, CM108, VOX
- Field for the relevant pin or port depending on selection

**Listen Only or TX**
- If Listen Only: PTT, digipeat, and RF beacon sections are hidden

**Callsign and SSID** *(TX only)*

**Digipeat** *(TX only)*
- On / off toggle
- If on: dropdown of standard path presets (WIDE1-1, WIDE2-1, WIDE2-2, etc.)

**Igate**
- On / off toggle
- If on: server address, username and password, filter path dropdown with preset values

**RF Beacon** *(TX only)*
- On / off toggle
- If on: type (e.g. PBEACON), delay, interval, overlay, symbol
- Location: GPS (auto) or hardcoded (manual coordinate input)

**Igate Beacon**
- On / off toggle
- If on: same fields as RF beacon

**Direwolf Start Mode**
- Auto — starts automatically on boot
- Manual — user starts from the dashboard

On submit, config is validated, `direwolf.conf` is written, and the user is taken to the main dashboard.

---

### Step 3 — Direwolf Startup Sequence

Triggered automatically (if auto-start) or by the user pressing Start. The e-ink display shows each stage:

1. **Power relay on** — radio powered up
2. **Waiting 10 seconds** — radio boot delay, shown on screen with countdown
3. **Waiting for GPS fix** *(if GPS location selected)* — screen shows "Waiting GPS" with a running timer
   - If GPS hardware error: show error on screen, halt, do not start Direwolf
   - If just waiting: keep waiting and displaying status — no timeout
4. **Launching Direwolf** — process started, log begins streaming

---

### Direwolf Crash Handling

If Direwolf exits unexpectedly while running:

1. Log the crash with timestamp
2. Wait 10 seconds, attempt restart (attempt 1 of 3)
3. If crashes again, wait 30 seconds, attempt restart (attempt 2 of 3)
4. If crashes again, wait 60 seconds, attempt restart (attempt 3 of 3)
5. If all three attempts fail: hard stop, power relay off
6. E-ink display pauses rotation and shows the Direwolf error output — no rotation until user intervenes

---

## Time Sync

On boot, the app attempts NTP sync over the network. If no network is available (or NTP fails), it waits for a GPS fix and uses GPS time. Timestamps in logs are held until a reliable time source is available.

---

## Web Interface Security

Configurable in `config.yaml`. Four modes:

| Mode | Effect |
|------|--------|
| `none` | No authentication — open access |
| `config` | Start/stop freely; config page requires password |
| `readonly` | View logs and status only; start/stop and config require password |
| `full` | Everything behind a login page |

---

## Operating Modes

Set in config. Modes can be combined. The config generator enables or disables the relevant sections of `direwolf.conf` based on the selection.

| Mode         | What Direwolf does                                              |
|--------------|-----------------------------------------------------------------|
| `rx_only`    | Receives and decodes packets — no transmit                      |
| `igate`      | Forwards received packets to APRS-IS over the internet          |
| `digipeater` | Retransmits received packets to extend RF range                 |
| `beacon`     | Periodically transmits the station's own position/status        |

---

## Web Interface

### Config Page
Single page for all user configuration — used as the setup wizard on first boot, and accessible from the dashboard Configure button thereafter. Direwolf must be stopped before config can be saved. Sections:

- Interface (serial or audio, device selection)
- PTT method + **PTT Test button** (keys radio for 1 second to verify PTT is working)
- Listen only / TX, callsign and SSID
- **APRS-IS Passcode** — input field pre-populated by auto-calculating from callsign, with a Generate button; can be overridden manually
- Digipeat settings
- Igate settings
- RF beacon settings
- Igate beacon settings
- Direwolf start mode (auto / manual)
- Map settings (tile mode, cache region/zoom, cache download with progress bar)
- Station aging — how long before a heard station is removed from the map (configurable)
- Display page rotation (order, enabled/disabled, per-page duration)
- **GPIO Pinout** — visual diagram of the Pi GPIO header showing which pins are assigned to the relay, GPS serial, and e-ink display. Updates live as pin config changes.
- Network settings
- Web interface security mode and password
- **Export config** — downloads `config.yaml`
- **Import config** — uploads a `config.yaml` to restore settings

Writing config validates inputs, saves `config.yaml`, and regenerates `direwolf.conf`. Direwolf must be stopped before config can be saved.

### Main Dashboard

```
┌─────────────────────────────────────────────────┬──────────────────┐
│  [All] [Direct] [Position]  [Traces: on/off]    │ [● Running]      │
│ ─────────────────────────────────────────────── │ [Stop][Configure]│
│                                                 │ ──────────────── │
│                    Map                          │ Heard:  42       │
│             (centered on GPS)                   │ Digipd: 18       │
│                                                 │ Gated:  31       │
│                                                 │ Uptime: 3h 21m   │
│                                                 │ IS: Connected    │
│                                                 │ ──────────────── │
│                                                 │ Direwolf Log     │
│                                                 │ Heard ZL4ST-9…   │
│                                                 │ Beacon sent RF…  │
│                                                 │ Gated ZL2JRB…    │
└─────────────────────────────────────────────────┴──────────────────┘
```

**Sidebar — controls**
- Direwolf status indicator (running / stopped / error)
- Start / Stop button
- Configure button — clickable only when stopped; shows "Stop Direwolf before configuring" when running

**Sidebar — stats**
- Packets heard
- Packets digipeated
- Packets gated to APRS-IS
- Direwolf uptime
- APRS-IS connection status (Connected / Disconnected / N/A)

**Sidebar — log**
- Live simplified Direwolf log, scrolling
- Errors highlighted in full

**Map toolbar (above map)**
- Filter: All stations / Direct heard only / Position only
- Traces toggle: show or hide the path line from each station marker to the digipeater

**Main area** — map centered on GPS location. See Map section below.

**Auto-start** — if auto-start is set, Direwolf starts (via the startup sequence) as soon as the dashboard loads. If manual, it waits for the user to press Start.

---

## Logging & Log Parsing

Direwolf stdout is piped into a log parser before anything is displayed or stored. The parser has two jobs: produce a simplified human-readable log for the GUI, and extract position data for the map.

### GUI Log (Simplified)

Raw Direwolf output is noisy and technical. The parser translates it into clean one-line entries:

| Event | Display format |
|-------|---------------|
| Packet heard from station with position | `Heard ZL4ST-9 — 36.8485°S 174.7633°E` |
| Packet heard, no position | `Heard ZL4ST-9` |
| Packet digipeated | `Digipeated ZL4ST-9 → ZL2JRB` |
| RF beacon sent | `Beacon sent to RF — !3641.23S/17445.80E#` |
| Igate beacon sent | `Beacon sent to APRS-IS — !3641.23S/17445.80E#` |
| Packet gated to APRS-IS | `Gated to APRS-IS — ZL4ST-9` |
| Error | Full raw Direwolf error line (unmodified) |
| Anything unrecognised | Shown as-is |

Errors are highlighted in the log panel. All other entries are plain text.

### Packet Parsing

`aprslib` is used as the primary packet parser. It handles all real-world APRS formats:
- **Standard position** — `!DDMM.mmN/DDDMM.mmE`
- **Timestamped position** — `@HHMMSSz...`
- **Compressed position** — base-91 encoded lat/lon
- **MIC-E** — common in Kenwood and Yaesu mobile radios

If `aprslib` fails for a packet, a regex fallback handles standard and timestamped formats. MIC-E and compressed packets require `aprslib` — without it they are silently skipped.

Direwolf log lines may carry GPS-sourced timestamps (`[2025-12-11T01:26:35Z]`) — the parser extracts these for accurate packet timing rather than using system clock time.

The parser also extracts Direwolf status lines: version string, audio device in use, and AGW/KISS ready notifications — fed into the stats panel.

### Map Data

When a position packet is parsed, a map event is emitted via WebSocket to the browser and the packet is persisted to `packet_store.py`.

Data extracted per position packet:
- Callsign + SSID
- Latitude and longitude
- Timestamp (from GPS log timestamp if available, otherwise system time)
- Packet type (position, object, weather, MIC-E, compressed)
- Whether heard directly or via another digi
- **APRS symbol table and symbol code** — determines which icon is shown on the map (car, house, digipeater, weather station, etc.)
- Comment field
- Path

**Track history** — all position packets are stored per callsign (up to 5000 entries each). Mobile stations show movement tracks on the map.

**Traces** — each station marker can optionally show a line drawn from it to the digipeater position. Toggled on/off from the map toolbar.

**Station aging** — stations are removed from the map after a configurable idle period (default 2 hours). Configurable in the config page.

### Packet Persistence (`packet_store.py`)

All decoded position packets are saved to `/var/digipeater/packets.json`. On app restart or browser refresh, the full station history is reloaded — nothing is lost between restarts.

Deduplication is keyed on callsign + rounded timestamp + rounded position. Per-callsign limit is 5000 packets. A reset API endpoint clears all stored data.

### Parser Module

`log_parser.py` reads Direwolf stdout line by line and returns three optional outputs per line:
- **LogEntry** — simplified human-readable message for the GUI log panel
- **MapEvent** — position data for the map (if the packet contained coordinates)
- **StatusUpdate** — Direwolf version, audio device, ready flags (if a status line)

---

## Map

Two modes, selected in config and configurable from the config page:

### Live Tiles (online)
Fetches map tiles from an online tile server (e.g. OpenStreetMap) as the user pans and zooms. Requires internet access. No local storage needed.

### Cached Tiles (offline)
Pre-downloads tiles for a selected region and zoom range. The device serves them locally — the map works with no internet connection. Suited for remote deployments.

**Cache config (in config page):**
- Region selection — draw a bounding box on a small preview map
- Zoom levels — min and max (e.g. 8–16). Higher max = more detail = much larger download
- Estimated disk usage — calculated and displayed before downloading (tile count × average tile size)
- Cache button — starts the download

**During download:**
- Progress bar showing tiles downloaded / total
- Current zoom level being fetched
- Estimated time remaining
- Cancel button

Cached tiles are stored locally and served by the app's web server. Leaflet.js is bundled locally in `web/static/leaflet/` so the map UI works in both modes — including full offline with no CDN dependency.

```yaml
map:
  mode: live             # "live" or "cached"
  tile_server: https://tile.openstreetmap.org/{z}/{x}/{y}.png  # live only
  cache:
    region:
      north: 0.0
      south: 0.0
      east: 0.0
      west: 0.0
    zoom_min: 8
    zoom_max: 14
    tile_dir: /var/digipeater/tiles
```

---

## File Structure

```
Digipeater/
│
├── OVERVIEW.md
├── SETUP.md
├── install.sh
│
├── main.py              ← entry point — wires all modules, starts web server
├── config.yaml          ← live config (not committed)
├── config.example.yaml  ← documented template
│
├── core/                ← APRS and Direwolf logic
│   ├── direwolf.py      ← start/stop/restart process, crash handling, stdout stream
│   ├── config_gen.py    ← generates direwolf.conf from config.yaml
│   ├── log_parser.py    ← parses Direwolf stdout → log entries, map events, status
│   └── packet_store.py  ← persists decoded packets to JSON, deduplication, reset
│
├── hardware/            ← physical hardware drivers
│   ├── relay.py             ← GPIO power relay control
│   ├── gps.py               ← serial NMEA GPS reader (+ gpsd TCP mode)
│   ├── radio.py             ← CAT frequency control via rigctld/Hamlib
│   └── radio_programmer.py  ← Alinco DR-138T channel programmer (ERW-4 cable)
│
├── display/             ← e-ink display
│   ├── manager.py            ← page rotation, override states, rendering
│   ├── base.py               ← abstract driver interface (swappable per hardware)
│   ├── driver_none.py        ← null driver for dev/testing
│   ├── driver_waveshare.py   ← adapts a waveshare/ model to the driver interface
│   └── waveshare/            ← one file per supported screen — see its __init__.py
│       ├── epdconfig.py      ← shared GPIO/SPI layer (simulated if unavailable)
│       ├── epd1in54_v2.py    ← 1.54" 200×200, SSD1681 (default)
│       ├── epd2in13_v4.py    ← 2.13" 250×122, SSD1680
│       ├── epd2in9_v2.py     ← 2.9"  296×128, SSD1680
│       └── epd4in2.py        ← 4.2"  400×300, UC8176
│
├── services/            ← system-level services
│   ├── network.py       ← WiFi/ethernet config via nmcli, reconnect monitor
│   ├── time_sync.py     ← NTP sync with GPS fallback
│   └── tile_cache.py    ← offline map tile downloader
│
├── tools/               ← standalone dev utilities (not imported by the app)
│   └── serial_sniffer.py  ← transparent serial bridge + hex logger, used to
│                             reverse-engineer new radio_programmer protocols
│
└── web/                 ← web interface
    ├── server.py        ← FastAPI app, REST endpoints, WebSocket server, auth
    └── static/
        ├── index.html
        ├── app.js
        ├── style.css
        ├── leaflet/     ← Leaflet.js bundled locally (no CDN dependency)
        ├── symbols/     ← APRS symbol sprite sheets (primary + alternate table)
        └── tiles/       ← cached map tiles (offline mode, created on first use)
```

---

## Tech Stack

| Component     | Choice                                                           |
|---------------|------------------------------------------------------------------|
| Language      | Python 3                                                         |
| Process mgmt  | `asyncio.create_subprocess_exec` — spawns Direwolf, streams output |
| Web server    | FastAPI — serves UI and REST endpoints                           |
| Real-time UI  | WebSocket — pushes Direwolf output and state changes to browser  |
| GPS           | `pyserial` — reads NMEA sentences from GPS receiver              |
| GPIO / relay  | `gpiozero` — abstracts pin control across Pi hardware revisions  |
| E-ink         | Abstracted driver — screen model selectable from config, no app code changes needed (see README for supported models) |
| Network mgmt  | `nmcli` (NetworkManager) — hotspot, WiFi client, ethernet        |
| mDNS          | `avahi-daemon` — exposes `digipeater.local` on the local network |
| Map UI        | Leaflet.js (bundled locally) — works online and fully offline    |
| APRS parsing  | `aprslib` — MIC-E, compressed, timestamped, standard formats     |
| Tile cache    | `httpx` + asyncio — downloads and stores OSM tiles locally       |
| Config        | YAML — maps directly to Direwolf config options                  |
| Radio CAT     | Hamlib `rigctld` (subprocess) — frequency read/set over TCP      |
