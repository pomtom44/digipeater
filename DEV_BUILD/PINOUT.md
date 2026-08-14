# GPIO Pinout

**BCM numbering** (not physical pin numbers) throughout.

---

## E-Ink Display

All supported displays share the same 8-pin SPI EPD wiring convention and the same pin assignments (set once in `display/waveshare/epdconfig.py`); only one display is wired at a time, selected during install.

| Display pin | BCM | Physical pin |
|---|---|---|
| VCC | N/A | 1 (or 17) |
| GND | N/A | 9 (any GND pin works) |
| DIN (MOSI) | GPIO 10 | 19 |
| CLK (SCLK) | GPIO 11 | 23 |
| CS | GPIO 8 (SPI CE0) | 24 |
| DC | GPIO 25 | 22 |
| RST | GPIO 17 | 11 |
| BUSY | GPIO 24 | 18 |

**BCM and physical pin numbers are not the same thing**: e.g. physical pin 17 is 3.3V power, not GPIO17. Wiring against the wrong column is a common mistake and will produce a consistent, clean failure (not a flaky one), since every wire is solidly connected, just to the wrong signal. Count physical header holes, not GPIO labels, when in doubt, or run `pinout` over SSH on the Pi for a labeled diagram of the actual header.

If you wire to different pins, update the constants at the top of `display/waveshare/epdconfig.py` to match (those are BCM numbers).

Neither of the two currently supported displays is a direct-plug RPi HAT; both need to be wired to the Pi by hand:

- **Generic 1.54" SPI e-Paper (200×200)**: primary/main hardware target. No direct-plug header at all (bare module), wire by hand.
- **Waveshare Pico-ePaper-2.9-B (296×128, B/W/R)**: dev/secondary display. Wired for a Pico's header, not a direct-plug RPi HAT.

---

## PTT (Push-to-Talk)

Wiring depends on which PTT method is picked in the setup wizard's Radio step; see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md) for what's actually been tested:

| Method | GPIO wiring needed? | Notes |
|---|---|---|
| VOX | No | Audio-only: the radio keys itself off the transmit audio. No Pi GPIO involved. |
| GPIO pin | Yes: one wire from **BCM GPIO 22** (physical pin 15) to the radio's PTT input | Fixed pin, not wizard-configurable; this hardware target has one wiring convention, same as the display pins above. Selecting "GPIO pin" in the wizard saves `radio.ptt_gpio_pin: 22` to `config.yaml` automatically, and the dropdown itself shows the pin ("GPIO pin (BCM 22, physical pin 15)") so it's never ambiguous which pin to wire. If you ever need a different pin, edit both `RADIO_DEFAULT_PTT_GPIO_PIN` and `RADIO_DEFAULT_PTT_GPIO_PHYSICAL_PIN` in `web/static/first_run.html` (and this table) to match your wiring; don't just rewire without updating all three. |
| CM108-family USB adapter | No | PTT is driven entirely over USB by the adapter itself: the adapter's own output (often a radio-specific or 3.5mm connector) goes straight to the radio. No Pi GPIO pin is used at all. |

GPIO 22 was picked because it's free on every currently-supported display wiring (not used by SPI, I2C, or UART); see the E-Ink Display table above and avoid GPIO 14/15 (UART, reserved for a UART-connected GPS) if wiring anything else to this Pi.
