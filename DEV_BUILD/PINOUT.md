# GPIO Pinout

**BCM numbering** (not physical pin numbers) throughout.

---

## E-Ink Display

All supported displays share the same 8-pin SPI EPD wiring convention and the same pin assignments (set once in `display/waveshare/epdconfig.py`) — only one display is wired at a time, selected during install.

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

If you wire to different pins, update the constants at the top of `display/waveshare/epdconfig.py` to match (those are BCM numbers).

Neither of the two currently supported displays is a direct-plug RPi HAT — both need to be wired to the Pi by hand:

- **Generic 1.54" SPI e-Paper (200×200)** — primary/main hardware target. No direct-plug header at all (bare module), wire by hand.
- **Waveshare Pico-ePaper-2.9-B (296×128, B/W/R)** — dev/secondary display. Wired for a Pico's header, not a direct-plug RPi HAT.
