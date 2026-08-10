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
| GPIO pin | ⚠️ Not hardware-tested, incomplete | Selectable in the wizard, but there's no pin-number field yet — the actual BCM pin isn't configurable. Don't rely on this method until that's built. |
| CM108-family USB adapter | ⚠️ Detection untested on real hardware | Wizard auto-detects connected adapters (`services/hardware.py: list_cm108_devices`) by matching USB VID/PID against the exact list Direwolf's own `cm108.c` recognizes — not a guess. Recognized chips: C-Media CM108, CM108B, CM108AH, CM119, CM119A, CM119B, HS100; SSS1621/SSS1623 clones; AIOC (microcontroller-based emulation). No GPIO wiring needed — PTT is driven over USB. |

---

## Audio Interface

Not a fixed hardware list — the wizard reads connected ALSA sound cards live from `/proc/asound/cards` (`services/hardware.py: list_audio_devices`) and serial ports live via `pyserial` (`list_serial_devices`), so any USB audio device or USB-serial adapter the Pi actually sees shows up automatically.

---

## Radio

The "Radio model" dropdown in the wizard (Baofeng UV-5R, Yaesu FT-2980R, Kenwood TM-D710G, Icom IC-2730A) is a **placeholder list only** — there's no radio-specific configuration or CAT control behind it yet. Selecting one doesn't currently change any behavior.

---

## Not Yet Built / Not Yet Tested

Everything else described in `OVERVIEW.md` (GPS, power relay, radio CAT control, radio channel programmer, other e-ink sizes) has no hardware testing yet — code for some of it exists in `ORIGINAL/` from before the rebuild, but none of it has been ported into `DEV_BUILD` or verified.

GPS-based beacon location (RF Beacon / IGate Beacon → Location → GPS, and the "Use current position" button) is a disabled placeholder in the wizard — it's wired up in the UI but does nothing until GPS device setup exists.
