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

## Startup

- Its own wizard step now — last one before Finish, not a checkbox tucked under Radio. Covers "start automatically on boot" (`startup.autostart`) and "restart automatically if it crashes" with max attempts/delay (`startup.autorestart`, `startup.restart_attempts`, `startup.restart_delay_s`, matching `ORIGINAL`'s `direwolf.restart_attempts`/`restart_delays` which never had a UI). All checked/defaulted, none of it applied anywhere yet — there's no Direwolf process for anything to start/stop/restart (part of the big gap above).

## GPS

- Device selection, system time sync (via `chrony`'s GPS SHM refclock), and timezone (via `timedatectl`) are now fully applied at every boot by `services/gpsconfig.py` / `scripts/apply-gps-config.sh` — not hardware-tested yet, but real, wired-up code, not a stub.
- Beacon position source (GPS vs. manual lat/lon) is still just collected, not applied — that's specifically the "direwolf GPS part" (feeds `PBEACON`), which is deliberately still waiting on the `direwolf.conf` generator described in the big gap above.
- Live GPS status and "Get current position" are real, working `gpsd` client code — just needs `gpsd` + a real GPS device to actually test end-to-end.

## Network

- Nothing outstanding — first-boot hotspot/WiFi-scan flow and normal-boot WiFi reconnect are both fully wired.

## Display

- Generic 1.54" SPI e-Paper driver (`epd1in54_v2`) is a best-guess port — hardware not in hand, never verified.
- Only two display models are supported; other sizes/models mentioned in `OVERVIEW.md` haven't been ported from `ORIGINAL/`.
- The wizard's E-Ink display step now lets you pick/change the display driver+model (preset from `display_config.json`, the same file `install.sh` writes) — this one actually takes effect on the reboot Finish triggers, unlike almost everything else in the wizard.
- The same step also collects a reorderable page-rotation list (order + duration + enabled/disabled, `config.yaml`'s `display.pages`) — collected only, since no page-rotation renderer exists yet in `DEV_BUILD` (still the "E-ink display page rotation" item below). Reordering/disabling uses buttons (▲/▼/Disable/Enable), not drag-and-drop like `ORIGINAL` — deliberate, since this wizard is likely used from a phone over the first-boot hotspot and native HTML5 drag-and-drop has no touch support.

## Map

- Tile downloading/caching (wizard step) and offline tile serving (`GET /tiles/{z}/{x}/{y}.png`) are implemented — `services/tiles.py`, ported and adapted from `ORIGINAL/services/tile_cache.py`. Uses OSM's standard open tile server, no API key. Not hardware-tested (needs a real internet connection + a real region download to verify tile math/disk layout end-to-end).
- The region picker itself is a real Leaflet map with a draggable pin, a draggable corner handle to resize the (square) region, and a live preview rectangle (`web/static/leaflet/`, vendored from `ORIGINAL`) — click-to-move, drag-to-move, and drag-to-resize all update the region and re-estimate. Zoom is a single "detail level" slider (1–16, default 10) — min zoom is fixed at 1, not user-adjustable, since it barely changes tile count regardless of region size.
- The actual map *view* for the (not yet built) dashboard — station markers/traces, filtering — is still not built; this only covers downloading/serving/picking a region for one to eventually use.
- `install.sh` now pre-caches a coarse zoom 0–5 whole-world layer (`scripts/precache_world_map.py`, ~20MB) as a best-effort step — not a real offline world map, just enough that a future map view has *something* to show before a region's been downloaded via the wizard. `services/tiles.TileDownloader` was refactored to take an explicit bounds dict rather than only center+radius, to support this (wizard path unchanged, now via `TileDownloader.for_radius(...)`).
- Fixed a real bug found while wiring this up: `_lon_to_tile`/`_lat_to_tile` didn't clamp to `[0, 2^zoom - 1]`, so a bound sitting exactly on the antimeridian (e.g. `WORLD_BOUNDS`'s east edge, 180°) computed an out-of-range index one column past the real last tile — silently doubling tile counts at every zoom level for anything reaching that boundary. Fixed; verified zoom 0–5 world count now matches the expected 1,365 tiles exactly.

## User management

- Security mode + password now collected in the wizard (between E-Ink display and Startup) — three levels (`none`/`readonly`/`full`), simplified down from `ORIGINAL`'s four (`web.security.mode`: none/config/readonly/full). "Config password" (start/stop free, config locked) was deliberately dropped — not useful without a dashboard that actually distinguishes start/stop from config changes, and it's also what made `ORIGINAL`'s own gating inconsistent (see below). Password is hashed (PBKDF2-HMAC-SHA256, salted, `services/auth.py`) before it's written to `config.yaml` — improved over `ORIGINAL`, which stored it in plaintext and compared with a bare `==`.
- Not enforced anywhere — no login system/session/auth-gated endpoints exist in `DEV_BUILD` yet, so every mode currently behaves like "No security." This is the "Web UI security/password protection" item below, now half done (the setting exists; the enforcement doesn't).
- Worth knowing for whenever enforcement gets built: `ORIGINAL`'s "Read only" mode only gated Start/Stop/relay actions, not config-editing endpoints (`require_auth_if_readonly` vs `require_auth_if_config` were independent checks, and "readonly" wasn't included in the config gate) — so under `ORIGINAL`, "Read only" mode could still have its config changed with no password, despite the UI label ("view only without a password") implying otherwise. `DEV_BUILD`'s "Read only" should mean what it says: viewing open, any change (not just start/stop) needs the password.

## Not yet ported from `ORIGINAL/` at all

- Power relay (radio power-on GPIO sequencing)
- Radio CAT control (Hamlib rig control, live frequency polling/display)
- Radio channel programmer (Alinco DR-138T specific)
- E-ink display page rotation (multi-page cycling through status/config/location/etc.)
- Web UI security/password *enforcement* — login/session/auth-gated endpoints. The mode + password setting itself is now collected (see User management above); nothing checks it yet.
