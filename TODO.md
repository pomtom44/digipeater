# To Do Later

Everything currently deferred or flagged as a known gap in `DEV_BUILD`, collected in one place so nothing gets lost. See `DEV_BUILD/SUPPORTED_HARDWARE.md` and `DEV_BUILD/PINOUT.md` for more detail on the hardware-specific items below.

## The big one

**Nothing generates an actual `direwolf.conf` yet.** The setup wizard (APRS settings, Radio setup, GPS setup) collects everything into `config.yaml` on Finish, but no backend currently turns it into a working Direwolf configuration. Every item below that says "collected but not applied" is downstream of this one gap — building the generator is what actually makes the rest of this list matter. (GPS is the one exception: `services/gpsconfig.py` applies gpsd/chrony/timezone directly from `config.yaml` on every boot, independent of Direwolf — see the GPS section below.)

## Digipeater / APRS

- Digipeat rules (alias/wide patterns) are collected via the wizard's Fill-in/Wide-area/Custom presets, but not yet applied anywhere.
- PHG (Power/Height/Gain) — now collected as three optional fields (Power/Height/Gain) on the RF Beacon subsection of the APRS step, matching Direwolf's `PBEACON` `POWER=`/`HEIGHT=`/`GAIN=` parameters. Not yet applied anywhere (per the big gap above); `DIR=`/directivity wasn't added, so Direwolf will treat it as omni.
- `AGWPORT`/`KISSPORT` — would let third-party APRS clients (Xastir, YAAC) use this station as a remote TNC. Flagged as low-priority/optional, not exposed.
- Digipeat `NOID`/preemptive options — couldn't confirm exact Direwolf syntax during research, not added.
- CSMA radio timing (`TXDELAY`, `TXTAIL`, `DWAIT`, `PERSIST`, `SLOTTIME`) — real, commonly-tuned settings, but about modem/PTT timing rather than APRS content. Belongs on the Radio step if it gets built at all.

## Radio

- "Radio model" dropdown is a placeholder list (Baofeng UV-5R, Yaesu FT-2980R, Kenwood TM-D710G, Icom IC-2730A) — no real CAT control or model-specific behavior behind it.
- "TX power level" dropdown is also a placeholder.
- GPIO-pin PTT now uses a fixed, hardcoded BCM pin (GPIO 22 — see `PINOUT.md`) saved to `config.yaml` automatically, rather than a wizard field. Same "hardcoded default, config-editable, not wizard-exposed" pattern should be followed for any future GPIO-based hardware (e.g. the power relay below).
- CM108 PTT device detection is real and working, but (per the big gap above) isn't yet wired into an actual PTT-triggering config.
- "Start automatically on boot" checkbox added, collected into `config.yaml` as `radio.autostart` — not applied anywhere yet, since there's no Direwolf process for anything to start/stop (part of the big gap above).

## GPS

- Device selection, system time sync (via `chrony`'s GPS SHM refclock), and timezone (via `timedatectl`) are now fully applied at every boot by `services/gpsconfig.py` / `scripts/apply-gps-config.sh` — not hardware-tested yet, but real, wired-up code, not a stub.
- Beacon position source (GPS vs. manual lat/lon) is still just collected, not applied — that's specifically the "direwolf GPS part" (feeds `PBEACON`), which is deliberately still waiting on the `direwolf.conf` generator described in the big gap above.
- Live GPS status and "Get current position" are real, working `gpsd` client code — just needs `gpsd` + a real GPS device to actually test end-to-end.

## Network

- Nothing outstanding — first-boot hotspot/WiFi-scan flow and normal-boot WiFi reconnect are both fully wired.

## Display

- Generic 1.54" SPI e-Paper driver (`epd1in54_v2`) is a best-guess port — hardware not in hand, never verified.
- Only two display models are supported; other sizes/models mentioned in `OVERVIEW.md` haven't been ported from `ORIGINAL/`.

## Map

- Tile downloading/caching (wizard step) and offline tile serving (`GET /tiles/{z}/{x}/{y}.png`) are implemented — `services/tiles.py`, ported and adapted from `ORIGINAL/services/tile_cache.py`. Uses OSM's standard open tile server, no API key. Not hardware-tested (needs a real internet connection + a real region download to verify tile math/disk layout end-to-end).
- The region picker itself is a real Leaflet map with a draggable pin and live preview rectangle (`web/static/leaflet/`, vendored from `ORIGINAL`) — click-to-move and drag-to-move both update the region and re-estimate.
- The actual map *view* for the (not yet built) dashboard — station markers/traces, filtering — is still not built; this only covers downloading/serving/picking a region for one to eventually use.

## Placeholders (wizard steps that exist but do nothing yet)

- **E-Ink display** — step exists between Map caching and Finish, renders a "not built yet" message, saves nothing. Intended for display driver/model selection and page-rotation config once that's moved into the web wizard (currently install.sh-only — see `SETUP.md`).
- **User management** — step exists between E-Ink display and Finish, same placeholder treatment. Intended to eventually cover the "Web UI security/password protection" item below.

## Not yet ported from `ORIGINAL/` at all

- Power relay (radio power-on GPIO sequencing)
- Radio CAT control (Hamlib rig control, live frequency polling/display)
- Radio channel programmer (Alinco DR-138T specific)
- E-ink display page rotation (multi-page cycling through status/config/location/etc.)
- Web UI security/password protection
