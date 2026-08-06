# Supported Hardware

Tracks exact hardware that's been tried against the dev build, and whether it actually works. Updated as each part is built and tested — this is a record of what's been verified on real hardware, not a spec sheet of what the code merely has a driver for.

**Status key:**
- ✅ Confirmed working on real hardware
- ⚠️ Driver implemented, not yet verified on real hardware
- ❌ Tried and does not work — kept here as a record so it isn't tried again by mistake

---

## Raspberry Pi Board

| Make / Model | Status | Notes |
|---|---|---|
| Raspberry Pi 3B | ✅ Confirmed | Raspberry Pi OS Bookworm Lite (64-bit). Boots, installs via `install.sh`, runs the web server. |

---

## E-Ink Display

| Make / Model | Driver | Status | Notes |
|---|---|---|---|
| Waveshare Pico-ePaper-2.9-B (296×128, black/white/red) | `epd2in9b_v3` | ⚠️ Driver implemented | Ported from Waveshare's official `epd2in9b_V3.py` (RPi/GPIO+spidev version). Awaiting confirmation that the test pattern renders cleanly on hardware. |
| Waveshare 2.9" e-Paper V2, plain black/white (296×128, SSD1680) | `epd2in9_v2` | ❌ Does not work with the -B board | Different controller and opposite BUSY-pin polarity from the -B module — using this driver against the Pico-ePaper-2.9-B produces static/garbage, not just a wrong image. Would presumably work on the actual plain black/white module, but that hasn't been tested since we don't own one.

---

## Not Yet Built / Not Yet Tested

Everything else described in `OVERVIEW.md` (GPS, power relay, radio CAT control, radio channel programmer, other e-ink sizes) has no hardware testing yet — code for some of it exists in `ORIGINAL/` from before the rebuild, but none of it has been ported into `DEV_BUILD` or verified.
