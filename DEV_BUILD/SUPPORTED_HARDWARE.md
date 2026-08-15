# Supported Hardware

## Raspberry Pi Board

| Make / Model | Status | Notes |
|---|---|---|
| Raspberry Pi 3B | ✅ Confirmed | Raspberry Pi OS Bookworm Lite (64-bit). |

---

## E-Ink Display

| Make / Model | Status |
|---|---|
| Generic 1.54" SPI e-Paper (200×200, "LA-SPI" AliExpress module) | ⚠️ Best guess: hardware not in hand |
| Waveshare Pico-ePaper-2.9-B (296×128, B/W/R) | ✅ Confirmed (dev/secondary display) |

---

## PTT / Radio Interface

| Method | Status | Notes |
|---|---|---|
| VOX | ⚠️ Not hardware-tested | No wiring beyond audio in/out; relies on the radio's own voice-operated switch. |
| GPIO pin | ⚠️ Not hardware-tested | Fixed pin by default (GPIO 22, see [PINOUT.md](PINOUT.md)), changeable later in Settings. |
| CM108-family USB adapter | ⚠️ Detection untested on real hardware | Auto-detected when plugged in. Covers C-Media CM108/CM108B/CM108AH/CM119/CM119A/CM119B/HS100, SSS1621/SSS1623 clones, and AIOC. No GPIO wiring needed. |

---

## Audio Interface

Not a fixed list: any USB audio device the Pi sees shows up automatically during setup.

---

## Radio

The "Radio model" and "TX power" dropdowns during setup are **placeholders only** for now: there's no radio-specific configuration or CAT control behind them yet. Selecting one doesn't currently change any behavior.

---

## GPS

| Piece | Status | Notes |
|---|---|---|
| Device detection | ⚠️ Not hardware-tested | Any USB or UART-exposed serial GPS shows up automatically as a pickable option. |
| Live status (position/fix/satellites) | ⚠️ Needs a real device to test | Reports "not available" gracefully if no GPS is attached. |
| System time sync from GPS | ⚠️ Not hardware-tested | No PPS wiring in this project, so time accuracy is roughly ±0.2-0.5s: fine for a station clock, not a precision reference. |

---

## Not Yet Built / Not Yet Tested

Power relay control, radio CAT control, and the radio channel programmer have no hardware testing yet. Other e-ink sizes/models beyond the two above aren't supported.
