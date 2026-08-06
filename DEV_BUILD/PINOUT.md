# GPIO Pinout

**BCM numbering** (not physical pin numbers) throughout.

---

## E-Ink Display — Waveshare Pico-ePaper-2.9-B

Not a direct-plug RPi HAT (it's wired for a Pico's header), so it's wired to the Pi by hand.

| Display pin | BCM | Physical pin |
|---|---|---|
| VCC | — | 1 (or 17) |
| GND | — | 9 (any GND pin works) |
| DIN (MOSI) | GPIO 10 | 19 |
| CLK (SCLK) | GPIO 11 | 23 |
| CS | GPIO 8 (SPI CE0) | 24 |
| DC | GPIO 25 | 22 |
| RST | GPIO 17 | 11 |
| BUSY | GPIO 24 | 18 |

**BCM and physical pin numbers are not the same thing** — e.g. physical pin 17 is 3.3V power, not GPIO17. Wiring against the wrong column is a common mistake and will produce a consistent, clean failure (not a flaky one), since every wire is solidly connected — just to the wrong signal. Count physical header holes, not GPIO labels, when in doubt — or run `pinout` over SSH on the Pi for a labeled diagram of the actual header.

If you wire it to different pins, update the constants at the top of `display/waveshare/epdconfig.py` to match (those are BCM numbers).
