# GPIO Pinout

**BCM numbering** shown first, physical pin number in parentheses. All pins below can be changed after setup on the dashboard's **Config → GPIO** tab if you need to wire something differently.

## Raspberry Pi 3 GPIO Header

Looking at the header with pin 1 at the top-left (the corner nearest the SD card):

| Left column | | Right column |
|---|---|---|
| 1 &nbsp; 3.3V | | 5V &nbsp; 2 |
| 3 &nbsp; GPIO2 (SDA) | | 5V &nbsp; 4 |
| 5 &nbsp; GPIO3 (SCL) | | GND &nbsp; 6 |
| 7 &nbsp; GPIO4 | | **GPIO14 (TXD): GPS UART, if used** &nbsp; 8 |
| GND &nbsp; 9 | | **GPIO15 (RXD): GPS UART, if used** &nbsp; 10 |
| **GPIO17: E-Ink RST** &nbsp; 11 | | GPIO18 &nbsp; 12 |
| **GPIO27: Relay control** &nbsp; 13 | | GND &nbsp; 14 |
| **GPIO22: PTT** &nbsp; 15 | | GPIO23 &nbsp; 16 |
| 3.3V &nbsp; 17 | | **GPIO24: E-Ink BUSY** &nbsp; 18 |
| **GPIO10 (MOSI): E-Ink DIN** &nbsp; 19 | | GND &nbsp; 20 |
| GPIO9 (MISO) &nbsp; 21 | | **GPIO25: E-Ink DC** &nbsp; 22 |
| **GPIO11 (SCLK): E-Ink CLK** &nbsp; 23 | | **GPIO8 (CE0): E-Ink CS** &nbsp; 24 |
| GND &nbsp; 25 | | GPIO7 (CE1) &nbsp; 26 |
| ID_SD &nbsp; 27 | | ID_SC &nbsp; 28 |
| GPIO5 &nbsp; 29 | | GND &nbsp; 30 |
| GPIO6 &nbsp; 31 | | GPIO12 &nbsp; 32 |
| GPIO13 &nbsp; 33 | | GND &nbsp; 34 |
| GPIO19 &nbsp; 35 | | GPIO16 &nbsp; 36 |
| GPIO26 &nbsp; 37 | | GPIO20 &nbsp; 38 |
| GND &nbsp; 39 | | GPIO21 &nbsp; 40 |

**Bold** = used by this project. Any GND pin can supply ground for the components below; the wiring diagrams pick a convenient nearby one, but any of them works.

---

## E-Ink Display

These are the pins you will use:

| Display pin | Pi pin |
|---|---|
| VCC | 3.3V (pin 1 or 17) |
| GND | GND (pin 9, or any other GND) |
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
| Return | GND (any GND pin) |

Wired through an **optocoupler**, not directly into the radio: GPIO22 and a GND pin drive the optocoupler's input LED, and the optocoupler's output switches the radio's PTT line to ground to key it. This electrically isolates the Pi from the radio's PTT circuit, so a fault on the radio side can't damage the Pi's GPIO.

---

## Radio Power Relay

This is the pin you will use:

| Signal | Pi pin |
|---|---|
| Relay control signal | GPIO27 (pin 13) |
| Relay module power | 5V (pin 2 or 4) |
| Relay module ground | GND (any GND pin) |

Powers the radio on before the digipeater software starts and off after it stops.

---

## GPS (UART-wired, optional)

Only relevant if wiring a GPS module directly to the Pi's UART instead of using a USB GPS (USB GPS devices are detected automatically and don't need any of this):

| Signal | Pi pin |
|---|---|
| GPS TX → Pi RX | GPIO15 / RXD (pin 10) |
| GPS RX → Pi TX | GPIO14 / TXD (pin 8) |
| GPS power | 3.3V or 5V, per your GPS module's spec |
| GPS ground | GND (any GND pin) |

---

## Changing pins after setup

The GPIO tab under **Config** in the dashboard is the one place the PTT, relay, and e-ink pins above become editable. It warns if two pins end up set to the same value. Relay and e-ink pin changes need a reboot to take effect; a PTT pin change applies immediately.
