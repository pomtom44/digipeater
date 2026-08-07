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

SSH into the Pi, then run:

```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/DEV_BUILD/install.sh | bash
```

You'll be asked which e-ink display is connected (pick "None" if there isn't one). The installer then sets up the `digipeater` service to start on every boot and reboots when finished.

**After reboot:**
- The e-ink display shows first-boot status, including the WiFi hotspot's SSID/password
- Connect to the `Digipeater` hotspot (password `Digipeater`), or use ethernet
- Open `http://digipeater.local:8080`, or `http://IP:8080` in a browser to continue the setup

**Useful commands:**
```bash
journalctl -u digipeater -f       # live logs
sudo systemctl restart digipeater # restart after manual changes
```

Re-running the install command pulls the latest code and redeploys.
