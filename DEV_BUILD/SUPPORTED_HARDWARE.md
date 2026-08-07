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

## Not Yet Built / Not Yet Tested

Everything else described in `OVERVIEW.md` (GPS, power relay, radio CAT control, radio channel programmer, other e-ink sizes) has no hardware testing yet — code for some of it exists in `ORIGINAL/` from before the rebuild, but none of it has been ported into `DEV_BUILD` or verified.
