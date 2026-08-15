# Supported Hardware

The items in this list have been tested and verified working for this project
You may be able to replace some items, however some will require changes to get working
I.E. Display resolutions and screen layouts

## Raspberry Pi Board

| Make / Model | Status | Notes |
|---|---|---|
| Raspberry Pi 3B | ✅ Confirmed | Raspberry Pi OS Bookworm Lite (64-bit). |
| Raspberry Pi 4 | ⚠️ Likely to work, untested | Same GPIO chip generation as the Pi 3, no known blocker. |
| Raspberry Pi 5 | ❌ Will not work as-is | This project uses `RPi.GPIO` directly, which doesn't support the Pi 5 at all: it moved GPIO control to a separate RP1 chip needing different kernel drivers, and `RPi.GPIO` hasn't been updated to support it. Would need a code change (e.g. swapping to `rpi-lgpio`, a drop-in replacement) before it could work. |
| Pi 1 / original Zero / Zero W | ❌ Will not work | Different problem from the Pi 5: these use the older 32-bit-only ARMv6 chip, which can't run the 64-bit Raspberry Pi OS this project requires at all. GPIO itself isn't the issue here. |
| Pi 2, Pi Zero 2 W | ⚠️ Depends on revision, untested | Pi Zero 2 W and later Pi 2 revisions (v1.2) use the same 64-bit-capable chip as the Pi 3, so the OS should run; the original Pi 2 v1.1 doesn't. Even where the OS runs, this combination (web server, Direwolf, gpsd, chrony, hotspot, all at once) has only been verified on a 3B, and these boards have meaningfully less RAM. |

---

## E-Ink Display

| Make / Model | Status |
|---|---|
| Generic 1.54" SPI e-Paper (200×200, "LA-SPI" AliExpress module) | ⚠️ Not confirmed yet, hardware still in testing |
| Waveshare Pico-ePaper-2.9-B (296×128, B/W/R) | ✅ Confirmed |

---

## PTT / Radio Interface

| Method | Status | Notes |
|---|---|---|
| GPIO pin | ✅ Confirmed | GPIO 22, see [PINOUT.md](PINOUT.md). Uses octocoupler for wiring seperation. |
| VOX | ⚠️ Radio Specific | Relies on the radio's own voice-operated switch. |
| CM108-family USB adapter | ⚠️ Untested on real hardware | Auto-detected when plugged in. No GPIO wiring needed. |
| Serial (direct to radio, RTS line) | ⚠️ Untested | No serial-enabled radio available to test against. Auto-detected the same way as CM108, keys PTT via the serial port's RTS line. |

---

## Audio Interface

Not a fixed list: any USB audio device the Pi sees shows up automatically during setup. An **external USB audio device with both a headphone (playback) and mic (capture) input is recommended**: the Pi's own native 3.5mm audio jack is playback-only, it has no mic/capture input at all, so it can't be used on its own for the RX side of this project. Any USB headphone/mic combo device should work; nothing specific to one model or brand.

---

## Radio

The "Radio model" and "TX power" dropdowns during setup are **placeholders only** for now: there's no radio-specific configuration or CAT control behind them yet. Selecting one doesn't currently change any behavior.

---

## GPS

| Piece | Status | Notes |
|---|---|---|
| Device detection | ✅ Confirmed | Tested with a generic, cheap USB GPS module. Any USB or UART-exposed serial GPS shows up automatically as a pickable option. |
| Live status (position/fix/satellites) | ✅ Confirmed | Tested with the same generic USB GPS module. Reports "not available" gracefully if no GPS is attached. |
| System time sync from GPS | ✅ Confirmed | Accuracy depends on the specific GPS hardware, typically within about ±1 second. |

This project doesn't talk to a GPS device directly; it goes through `gpsd`, which does. So any device `gpsd` itself supports should work, not just the specific module tested, which in practice covers virtually any GPS, since almost all of them speak NMEA 0183 (the near-universal standard `gpsd` reads).

