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
3. **Choose OS** → Raspberry Pi OS (other) → **Raspberry Pi OS (Legacy, 64-bit) Lite**
   - This project is built and tested against Bookworm specifically. The plain "Raspberry Pi OS Lite (64-bit)" option now installs Trixie (Debian 13) by default, which is untested here — use the Legacy option to get Bookworm.
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

If an e-ink display is being used, wire it to the Pi before installing — see [PINOUT.md](PINOUT.md) for supported models and their pin tables. Most e-ink displays aren't direct-plug RPi HATs and need to be wired by hand.

No display connected? Skip this step — it's selected as "None" during install.

---

## Part 3 — Install the Tool

**Before you start, have ready:**
- Your callsign and SSID (the APRS-IS passcode fills in automatically from these — no need to look it up)
- A decision on IGate mode (Off / RX only / RX & TX) — RX only is the safe default if unsure; RX & TX also relays internet messages back onto RF
- If using a GPIO-pin or CM108 PTT connection, see [PINOUT.md](PINOUT.md) — note GPIO-pin PTT isn't fully wired up in software yet

SSH into the Pi, then run:

```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/DEV_BUILD/install.sh | bash
```

Near the end you'll be asked for a WiFi country code (only if one isn't already set — needed for the hotspot to work at all) and which e-ink display is connected (pick "None" if there isn't one). The installer then sets up the `digipeater` service to start on every boot and reboots when finished.

**After reboot:**
- The e-ink display shows first-boot status, including the IP and network method currently configured
- Ethernet, Wifi, or Hotspot with SSID, Password, and the address to browse to
- Either make sure you are connected to your network and getting an IP, or connect to the hotspot
- Open `http://digipeater.local`, or the IP address shown on the display, in a browser to continue the setup

**The setup wizard has four steps:**
1. **Network setup** — shows current connection status; if on the hotspot, lets you scan for and save WiFi credentials to connect to on the next normal boot
2. **APRS settings** — callsign/SSID, digipeating and IGate modes, IGate connection details (collapsed by default, sensible defaults pre-filled), station icon/comment, and RF/IGate beacon settings
3. **Radio setup** — audio device, PTT method, initial frequency, and TX power (radio model and power level are placeholders for now — see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md))
4. **Finish** — press **Finish & Reboot** to save everything and reboot into standard mode; the page auto-reloads into the normal dashboard once it's back up

For exactly how each wizard field maps to the underlying Direwolf configuration, see [`reference/direwolf.conf.annotated`](reference/direwolf.conf.annotated) — Direwolf's own official sample config, annotated line-by-line with where (or whether) each setting is currently exposed in the wizard.

**Useful commands:**
```bash
journalctl -u digipeater -f       # live logs
sudo systemctl restart digipeater # restart after manual changes
```

Re-running the install command pulls the latest code and redeploys.

---

## Credits

- APRS symbol icons used in the setup wizard: [hessu/aprs-symbols](https://github.com/hessu/aprs-symbols) by Heikki Hannikainen, OH7LZB — CC BY-SA 4.0. See [`web/static/aprs-symbols/COPYRIGHT.md`](web/static/aprs-symbols/COPYRIGHT.md) for the full license and per-symbol attribution.
