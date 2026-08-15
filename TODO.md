# To Do Later

Known gaps in `DEV_BUILD`, collected in one place. See `DEV_BUILD/SUPPORTED_HARDWARE.md` and `DEV_BUILD/PINOUT.md` for hardware-specific detail.

## Direwolf config generation

`services/direwolf_config.py` turns `config.yaml` into `direwolf.conf`, regenerated fresh on every normal boot. `services/system.set_direwolf_running()` starts/stops the real `direwolf` systemd service accordingly (installed by `install.sh`, not auto-enabled; the app decides each boot).

Start sequence: confirm a GPS fix exists (manual position needs lat/lon set; live GPS needs `gpsd` to report an actual fix) → power the radio via `services/relay.py` (~10s boot wait) → program its channel if the radio model supports it (currently always a no-op, see below) → ~5s settle → `systemctl start direwolf`. A failure before Direwolf actually starts (no GPS fix, programming failure) powers the relay back off. Stop sequence: `systemctl stop direwolf` → ~10s wait → relay off.

Known gaps:
- Not tested against the real `direwolf` binary (sandbox can't run Linux binaries), only checked for well-formed config syntax.
- Serial PTT (`serial:/dev/ttyUSBx`) always uses RTS, no field to pick DTR instead.
- `startup.autorestart`/`restart_attempts`/`restart_delay_s` aren't wired to the `direwolf.service` unit's `Restart=`/`RestartSec=`; only plain on/off autostart is applied.
- `AGWPORT`/`KISSPORT`, CSMA radio timing (`TXDELAY`/`TXTAIL`/`DWAIT`/`PERSIST`/`SLOTTIME`), and digipeat `NOID`/preemptive options aren't exposed in the wizard.
- A manual dashboard "Start" click can take 15+ seconds before Direwolf is actually running, with no progress feedback.
- If `gpsd` was just reconfigured this same boot, a cold GPS fix may not exist yet, so a fresh boot can fail the start gate with no retry (a logged error, not surfaced to the UI); the dashboard's manual Start button is the way to recover.

`services/radio_programmer.py` is a deliberate stub: `RADIO_CAPABILITIES` is a code-only registry of which radio models support channel programming (currently just Alinco DR-138T, ported from `ORIGINAL/hardware/radio_programmer.py` but not the actual serial protocol yet). Not user-configurable; a model either has a real protocol implemented here or it doesn't.

## In-program config page

`web/static/config.html`, linked from the dashboard sidebar's Config button, is a tabbed settings page (Network / APRS / Radio / GPS / Map / E-Ink / User / Startup / GPIO) backed by `POST /api/config/save`. One global "Save all changes" button, not per-tab.

Applies live where possible: GPS, radio/APRS (regenerates `direwolf.conf` and restarts Direwolf if running), user/startup settings (already read fresh on every use). Needs a reboot for: GPIO relay/e-ink pin changes, the e-ink display driver/model, and network credentials (deliberately not applied live, to avoid disconnecting the session making the change). The Map tab saves itself via its own live download action, not through the Save-all endpoint.

GPIO pins (relay, e-ink RST/DC/CS/BUSY) are now config-driven (`config.yaml`'s `gpio` section) instead of hardcoded, editable on the GPIO tab; the PTT pin lives under `radio.ptt_gpio_pin` as before, also editable there.

## Digipeater / APRS

- Applied for real: digipeat rules (alias/wide patterns), dedupe window, RF filter, PHG (Power/Height/Gain).
- `AGWPORT`/`KISSPORT` (would let third-party APRS clients use this station as a remote TNC), digipeat `NOID`/preemptive options, and CSMA radio timing are not exposed anywhere.

## Radio

- "Radio model" and "TX power level" dropdowns are placeholders; no real CAT control or model-specific behavior yet.
- CM108 PTT detection is real and wired into `direwolf.conf` generation.

## Startup

- `startup.autostart` is applied for real (decides whether Direwolf starts each boot). `autorestart`/`restart_attempts`/`restart_delay_s` are collected but not wired to systemd.

## GPS

- Device selection, time sync, and timezone are applied at every boot.
- Manual position supports 4 entry formats (decimal, DMS/DDM, Maidenhead, Plus Code), all pure client-side arithmetic, no network call needed. A short Plus Code needs a nearby reference position (a live fix or a previously-entered position) to resolve.

## Network

- Nothing outstanding: first-boot hotspot/WiFi-scan flow and normal-boot reconnect are both fully wired.

## Display

- Generic 1.54" SPI e-Paper driver is a best-guess port, hardware not in hand, never verified.
- Only two display models are supported.
- Display driver/model selection takes effect on reboot. The page-rotation list (order/duration/enabled per screen) is collected but not applied: no page-rotation renderer exists yet.

## Map

- Uses [Protomaps](https://protomaps.com/)/PMTiles (a region-extract CLI, `services/tiles.py`) instead of live raster tile scraping, which OSM's usage policy disallows for offline use.
- The wizard's region picker (drag pin, resize handles, zoom slider) always works, with or without internet, from a pre-cached coarse whole-world map; downloading a more detailed region needs a live connection.
- No precise pre-download size estimate; real progress (bytes/elapsed time) shows once a download starts.
- Not end-to-end tested against the real `pmtiles` binary (sandbox can't run Linux binaries).
- A running region download doesn't survive a reboot and can't be resumed.
- The dashboard streams the live planet build when the Pi has internet (via a same-origin proxy, `GET /map-data/live.pmtiles`), so panning outside the cached region doesn't show blank tiles. Needs the **Pi's own** internet, not just the viewer's browser, since Protomaps' hosted archive has no CORS headers and can't be range-requested directly from a browser.
- Independent light/dark theme toggles exist for the page UI and the map itself (tracked separately, since they're unrelated).
- Beacon stats and Heard stations on the dashboard are hardcoded sample data (flagged as such in code, `SAMPLE_HEARD_STATIONS` etc. in `normal.html`): no packet source exists yet to populate them for real.
- Auto-update: a daily-build check (`digipeater-tile-update.timer`, runs every 15 min but only does real work once/day) re-downloads the world map and any saved region if a newer Protomaps build exists.

## User management

- Security mode + password enforcement is real: session cookie, PBKDF2-hashed password, `readonly`/`full` modes gate changes, `full` also gates viewing.
- Session expiry doesn't proactively redirect an already-open tab; only a fresh page load re-checks.

## Not yet ported from `ORIGINAL/` at all

- Radio CAT control (Hamlib rig control, live frequency polling/display).
- Radio channel programmer's actual serial protocol (Alinco DR-138T specific): the capability-registry shape exists, the protocol itself doesn't.
- E-ink display page rotation (multi-page cycling through status/config/location/etc.).
