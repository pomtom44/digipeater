# Supported Hardware

## Raspberry Pi Board

| Make / Model | Status | Notes |
|---|---|---|
| Raspberry Pi 3B | ✅ Confirmed | Raspberry Pi OS Bookworm Lite (64-bit). |

---

## E-Ink Display

| Make / Model | Driver | Status |
|---|---|---|
| Generic 1.54" SPI e-Paper (200×200, "LA-SPI" AliExpress module) | `epd1in54_v2` | ⚠️ Best guess — hardware not in hand |
| Waveshare Pico-ePaper-2.9-B (296×128, B/W/R) | `epd2in9b_v4` | ✅ Confirmed (dev/secondary display) |

---

## PTT / Radio Interface

| Method | Status | Notes |
|---|---|---|
| VOX | ⚠️ Not hardware-tested | No wiring beyond audio in/out — relies on the radio's own voice-operated switch. |
| GPIO pin | ⚠️ Not hardware-tested | Selectable in the wizard; wired to a fixed BCM pin (GPIO 22 — see [PINOUT.md](PINOUT.md)) rather than a wizard field, since this hardware target has one wiring convention. Saved to `config.yaml` automatically when selected. |
| CM108-family USB adapter | ⚠️ Detection untested on real hardware | Wizard auto-detects connected adapters (`services/hardware.py: list_cm108_devices`) by matching USB VID/PID against the exact list Direwolf's own `cm108.c` recognizes — not a guess. Recognized chips: C-Media CM108, CM108B, CM108AH, CM119, CM119A, CM119B, HS100; SSS1621/SSS1623 clones; AIOC (microcontroller-based emulation). No GPIO wiring needed — PTT is driven over USB. |

---

## Audio Interface

Not a fixed hardware list — the wizard reads connected ALSA sound cards live from `/proc/asound/cards` (`services/hardware.py: list_audio_devices`) and serial ports live via `pyserial` (`list_serial_devices`), so any USB audio device or USB-serial adapter the Pi actually sees shows up automatically.

---

## Radio

The "Radio model" dropdown in the wizard (Baofeng UV-5R, Yaesu FT-2980R, Kenwood TM-D710G, Icom IC-2730A) is a **placeholder list only** — there's no radio-specific configuration or CAT control behind it yet. Selecting one doesn't currently change any behavior.

---

## GPS

| Piece | Status | Notes |
|---|---|---|
| Device detection | ⚠️ Not hardware-tested | Reuses the same live serial-port detection as PTT (`services/hardware.py: list_serial_devices`) — any USB or UART-exposed serial device shows up as a pickable option. |
| Live status (position/fix/satellites) | ⚠️ Needs `gpsd` + a real device to test | `services/gps.py` is a real `gpsd` JSON-protocol client (connects to `localhost:2947`, reads `TPV`/`SKY` reports) — genuinely functional code, not a stub, but it needs `gpsd` actually running with a GPS attached to return real data. Reports "not available" gracefully otherwise. |
| `gpsd` package | Installed and enabled by `install.sh` | USB GPS devices are picked up automatically via `gpsd`'s own udev rules by default. If the wizard's GPS step picks an explicit device (needed for a UART-wired GPS), `services/gpsconfig.py` switches `gpsd` to always-running mode pointed at that device on next boot — see `scripts/apply-gps-config.sh`. |
| System time sync from GPS | ⚠️ Not hardware-tested | `chrony` (installed by `install.sh` in place of `systemd-timesyncd`) is configured with a GPS SHM refclock when the wizard's "update system time from GPS" option is checked. No PPS wiring in this project, so NMEA-over-SHM time is accurate to ~0.2-0.5s — fine for a station clock, not a precision reference. |
| Timezone list | Real system data | `services/system.py: list_timezones` uses Python's `zoneinfo.available_timezones()` — the actual IANA list Bookworm ships, with a small hardcoded fallback only if that comes up empty. Applied via `timedatectl set-timezone` when time sync is enabled. |

Beacon position source (GPS vs. manual lat/lon) is collected by the wizard's GPS step but not yet consumed — that's the one piece still waiting on a `direwolf.conf` generator (see `TODO.md`), since it feeds directly into Direwolf's `PBEACON`. Device selection, time sync, and timezone are all fully applied at boot by `services/gpsconfig.py`.

---

## Not Yet Built / Not Yet Tested

Everything else described in `OVERVIEW.md` (power relay, radio CAT control, radio channel programmer, other e-ink sizes) has no hardware testing yet — code for some of it exists in `ORIGINAL/` from before the rebuild, but none of it has been ported into `DEV_BUILD` or verified.
