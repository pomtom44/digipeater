# APRS Digipeater — Dev Build Setup Guide

This guide covers the dev build only. It grows as each part gets built — right now that's the Raspberry Pi image, the e-ink display, first-boot network setup, and the web server framework.

---

## Part 1 — Flash the Pi

**What you need:**
- Raspberry Pi 3B (or later)
- MicroSD card — 16GB minimum
- Raspberry Pi Imager: https://www.raspberrypi.com/software/

**Steps:**
1. Insert the MicroSD card into your computer and open Raspberry Pi Imager
2. **Choose Device** → Raspberry Pi 3
3. **Choose OS** → Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**
4. **Choose Storage** → select your SD card
5. Click **Next**, then **Edit Settings** when asked about OS customisation

**General tab:**
- Hostname: `digipeater`
- Username: `pi` (or your preference), and set a password — you'll need it to SSH in
- If using WiFi for setup, enter your SSID/password here (leave blank if using ethernet)

**Services tab:**
- Enable SSH: checked, using password authentication

Save, confirm, and write. Once flashing finishes:
1. Insert the SD card into the Pi and power it on
2. Wait ~60–90 seconds for first boot
3. SSH in: `ssh pi@digipeater.local` (or find its IP via your router if `.local` doesn't resolve)

---

## Part 2 — Wire the E-Ink Display

Current dev build targets a Waveshare 2.9" e-Paper panel (296×128, SSD1680 controller) — this covers both the standard RPi-HAT 2.9" V2 module and the Pico-ePaper-2.9 board (same panel/controller; the Pico board just breaks the signals out for a Pico's header instead of an RPi HAT connector).

Since it isn't a direct-plug RPi HAT, wire it by hand to these BCM pins:

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

> Note: the project's power-relay pin (for later parts) defaults to GPIO 27, specifically chosen to avoid clashing with the display's RST pin (GPIO 17). Don't reassign the relay to GPIO 17 once the display is wired.

---

## Part 3 — Install the Tool

SSH into the Pi, then run:

```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/DEV_BUILD/install.sh | bash
```

This installs Python, the e-ink display libraries, sets up a systemd service (`digipeater`) so the tool starts automatically on every boot, and prompts you to reboot at the end (needed the first time SPI is enabled).

**What to expect after reboot:**
- The e-ink display shows `First boot config`, then the ethernet IP (if connected) and the WiFi hotspot's SSID/password
- A WiFi hotspot named `Digipeater` (password `Digipeater`) becomes available to connect to
- Opening `http://digipeater.local:8080` (or the Pi's IP) in a browser shows a minimal "First boot config" page

There's no setup wizard yet — that page and the hotspot's WiFi-client option get built in a later part.

**Useful commands:**
```bash
journalctl -u digipeater -f       # live logs
sudo systemctl restart digipeater # restart after manual changes
```

Re-running the `curl` install command pulls the latest code and redeploys.
