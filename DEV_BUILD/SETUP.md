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

Current dev build targets the **Waveshare Pico-ePaper-2.9-B** — a black/white/**red** 296×128 panel. It isn't a direct-plug RPi HAT (it's wired for a Pico's header), so it needs to be wired to the Pi by hand.

> If you have the plain black/white 2.9" V2 module instead (no red), the driver for that (`epd2in9_v2.py`, SSD1680 controller) already exists in `display/waveshare/` too — just change `DISPLAY_MODEL` in `main.py` to `epd2in9_v2`. The two are electrically similar but use different controllers and are not interchangeable — using the wrong one produces static/garbage on screen, not just a wrong image.

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

This installs Python and the e-ink display libraries, then **asks which e-ink display is connected** (the list is read live from the drivers available in `display/waveshare/`, so it always matches what's actually in the code — pick `0` if you have no display wired up). That choice gets saved to `display_config.json` and is only asked once; delete that file and re-run the script to change it later.

It then sets up a systemd service (`digipeater`) so the tool starts automatically on every boot, and prompts you to reboot at the end (needed the first time SPI is enabled).

> Why ask this at install time instead of in the web setup wizard? The display needs to show status *during* first boot — before any wizard page could possibly run — so the choice has to be made before the tool ever starts.

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
