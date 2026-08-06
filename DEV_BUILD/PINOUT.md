# GPIO Pinout

**BCM numbering** (not physical pin numbers) throughout.

---

## E-Ink Display — Waveshare Pico-ePaper-2.9-B

Not a direct-plug RPi HAT (it's wired for a Pico's header), so it's wired to the Pi by hand.

| Display pin | Raspberry Pi pin (BCM) |
|---|---|
| VCC | 3.3V |
| GND | GND |
| DIN (MOSI) | GPIO 10 |
| CLK (SCLK) | GPIO 11 |
| CS | GPIO 8 (SPI CE0) |
| DC | GPIO 25 |
| RST | GPIO 17 |
| BUSY | GPIO 24 |

If you wire it to different pins, update the constants at the top of `display/waveshare/epdconfig.py` to match.
