# GPIO Pinout

**BCM numbering** shown first, physical pin number in parentheses. All GPIO signal pins below can be changed after setup on the dashboard's **Config → GPIO** tab if you need to wire something differently.

## Raspberry Pi 3 GPIO Header

Physical pin numbers down the middle, matching the two columns of the actual header (pin 1 at the top-left, nearest the SD card). `---` means that pin isn't used by this project.

| | Pin | Pin | |
|---|---|---|---|
| E-Ink VCC | 1 | 2 | Relay 5V |
| --- | 3 | 4 | --- |
| --- | 5 | 6 | Relay GND |
| --- | 7 | 8 | GPS UART TX |
| E-Ink GND | 9 | 10 | GPS UART RX |
| E-Ink RST | 11 | 12 | --- |
| Relay control | 13 | 14 | PTT GND |
| PTT control | 15 | 16 | --- |
| GPS 3.3V | 17 | 18 | E-Ink BUSY |
| E-Ink DIN | 19 | 20 | GPS GND |
| --- | 21 | 22 | E-Ink DC |
| E-Ink CLK | 23 | 24 | E-Ink CS |
| --- | 25 | 26 | --- |
| --- | 27 | 28 | --- |
| --- | 29 | 30 | --- |
| --- | 31 | 32 | --- |
| --- | 33 | 34 | --- |
| --- | 35 | 36 | --- |
| --- | 37 | 38 | --- |
| --- | 39 | 40 | --- |

---

## E-Ink Display

These are the pins you will use:

| Display pin | Pi pin |
|---|---|
| VCC | 3.3V (pin 1) |
| GND | GND (pin 9) |
| DIN (MOSI) | GPIO10 (pin 19) |
| CLK (SCLK) | GPIO11 (pin 23) |
| CS | GPIO8 / CE0 (pin 24) |
| DC | GPIO25 (pin 22) |
| RST | GPIO17 (pin 11) |
| BUSY | GPIO24 (pin 18) |

**BCM and physical pin numbers are not the same thing**: e.g. physical pin 17 is 3.3V power, not GPIO17. Count physical header holes, not GPIO labels, when in doubt, or run `pinout` over SSH on the Pi for a labeled diagram.

Neither supported display is a direct-plug RPi HAT; both need to be wired to the Pi by hand:

- **Generic 1.54" SPI e-Paper (200×200)**: primary/main hardware target. No direct-plug header at all (bare module), wire by hand.
- **Waveshare Pico-ePaper-2.9-B (296×128, B/W/R)**: dev/secondary display. Wired for a Pico's header, not a direct-plug RPi HAT.

---

## PTT (Push-to-Talk)

This is the pin you will use if PTT is set to GPIO pin mode (see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md) for other PTT methods, which don't use GPIO at all):

| Signal | Pi pin |
|---|---|
| PTT control | GPIO22 (pin 15) |
| PTT return | GND (pin 14) |

Wired through an **optocoupler**, not directly into the radio: GPIO22 and pin 14 drive the optocoupler's input LED, and the optocoupler's output switches the radio's PTT line to ground to key it. This electrically isolates the Pi from the radio's PTT circuit, so a fault on the radio side can't damage the Pi's GPIO.

---

## Radio Power Relay

This is the pin you will use:

| Signal | Pi pin |
|---|---|
| Relay control signal | GPIO27 (pin 13) |
| Relay module power | 5V (pin 2) |
| Relay module ground | GND (pin 6) |

Powers the radio on before the digipeater software starts and off after it stops.

---

## GPS (UART-wired, optional)

Only relevant if wiring a GPS module directly to the Pi's UART instead of using a USB GPS (USB GPS devices are detected automatically and don't need any of this):

| Signal | Pi pin |
|---|---|
| GPS TX → Pi RX | GPIO15 / RXD (pin 10) |
| GPS RX → Pi TX | GPIO14 / TXD (pin 8) |
| GPS power | 3.3V (pin 17) |
| GPS ground | GND (pin 20) |

---

## Changing pins after setup

The GPIO tab under **Config** in the dashboard is the one place the PTT, relay, and e-ink signal pins above become editable. It warns if two pins end up set to the same value. Relay and e-ink pin changes need a reboot to take effect; a PTT pin change applies immediately.
