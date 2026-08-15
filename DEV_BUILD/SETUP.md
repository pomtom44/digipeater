# APRS Digipeater: Dev Build Setup Guide

This guide covers the dev build only. It grows as each part gets built: right now that's the Raspberry Pi image, the e-ink display, first-boot network setup, and the web server framework.

---

## Part 1: Flash the Pi

**What you need:**
- Raspberry Pi 3B (or later)
- MicroSD card (16GB minimum)
- Raspberry Pi Imager: https://www.raspberrypi.com/software/

**Steps:**
1. Insert the MicroSD card into your computer and open Raspberry Pi Imager
2. **Choose Device** → Raspberry Pi 3
3. **Choose OS** → Raspberry Pi OS (other) → **Raspberry Pi OS (Legacy, 64-bit) Lite**
   - This project is built and tested against Bookworm specifically. The plain "Raspberry Pi OS Lite (64-bit)" option now installs Trixie (Debian 13) by default, which is untested here. Use the Legacy option to get Bookworm.
4. **Choose Storage** → select your SD card
5. Click **Next**, then **Edit Settings** when asked about OS customisation

**General tab:**
- Hostname: `digipeater`
- Username: `pi` (or your preference), and set a password (you'll need it to SSH in)
- If using WiFi for setup, enter your SSID/password here (leave blank if using ethernet)

**Services tab:**
- Enable SSH: checked, using password authentication

Save, confirm, and write. Once flashing finishes:
1. Insert the SD card into the Pi and power it on
2. Wait ~60–90 seconds for first boot
3. SSH in: `ssh pi@digipeater.local` (or find its IP via your router if `.local` doesn't resolve)

---

## Part 2: Wire the E-Ink Display

If an e-ink display is being used, wire it to the Pi before installing; see [PINOUT.md](PINOUT.md) for supported models and their pin tables. Most e-ink displays aren't direct-plug RPi HATs and need to be wired by hand.

No display connected? Skip this step: it's selected as "None" during install.

---

## Part 3: Install the Tool

**Before you start, have ready:**
- Your callsign and SSID (the APRS-IS passcode fills in automatically from these, no need to look it up)
- A decision on IGate mode (Off / RX only / RX & TX): RX only is the safe default if unsure; RX & TX also relays internet messages back onto RF
- If using a GPIO-pin or CM108 PTT connection, see [PINOUT.md](PINOUT.md): GPIO-pin PTT uses a fixed pin (BCM GPIO 22), not something you pick in the wizard
- If using GPS, have it connected before running the installer: `gpsd` is installed and started automatically, and USB GPS devices are picked up on their own

SSH into the Pi, then run:

```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/DEV_BUILD/install.sh | bash
```

Along the way the installer also downloads a coarse whole-world offline map (~1GB) so the map step has something to show even with no internet at setup time. This is best-effort, so a flaky connection at that point doesn't abort the install; if it's skipped, map caching just won't be usable until it's re-run later.

Near the end you'll be asked for a WiFi country code (only if one isn't already set; needed for the hotspot to work at all) and which e-ink display is connected (pick "None" if there isn't one). The installer then reboots when finished.

**After reboot:**
- The e-ink display shows first-boot status, including the IP and network method currently configured
- Ethernet, Wifi, or Hotspot with SSID, Password, and the address to browse to
- Either make sure you are connected to your network and getting an IP, or connect to the hotspot
- Open `http://digipeater.local`, or the IP address shown on the display, in a browser to continue the setup

**The setup wizard has nine steps:**
1. **Network setup**: shows current connection status; if on the hotspot, lets you scan for and save WiFi credentials to connect to on the next normal boot.
2. **APRS settings**: callsign/SSID, digipeating and IGate modes, IGate connection details (sensible defaults pre-filled), station icon/comment, and RF/IGate beacon settings.
3. **Radio setup**: audio device, PTT method (GPIO pin is the default, VOX and CM108 are also available), initial frequency, and TX power (radio model and power level are placeholders for now; see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md)).
4. **GPS setup**: pick a connected GPS device (or "No GPS"), beacon position source (GPS or manual lat/lon), optional system time sync with a timezone picker, and a live GPS status display. Manual position accepts decimal degrees, degrees/minutes/seconds, a Maidenhead grid square (e.g. `RF80qh`), or a Plus Code (including the short form Google Maps gives out, e.g. `57QW+PXQ`). All formats work fully offline.
5. **Map caching**: drag the pin to move the region and the edge handles to resize it, pick a detail level (1-15), then download it for offline use. Works with or without internet: offline you still get a coarse whole-world map to browse, just can't download a detailed region until you're connected. Optional, can be skipped and revisited later from the Config page.
6. **E-Ink display**: pick the connected display (preset from install). Below that, a reorderable list of status screens to rotate through (not active yet).
7. **User management**: pick a security mode: No security, Read only (viewing open, changes need a password), or Full (password needed for everything). Changeable later from the Config page's User tab.
8. **Startup**: "start automatically on boot" and "restart automatically if it crashes", both on by default. Also an "automatically check for map updates" toggle, defaulted on if there's internet right now.
9. **Finish**: reboots into normal operating mode. If a map download from step 5 is still running, Finish waits for it to complete first.

**Changing settings after setup:** the Config button in the dashboard sidebar leads to a tabbed settings page mirroring everything the wizard collected, plus a GPIO tab for pin overrides. Edit whatever's needed, then **Save all changes**. Most changes take effect within a few seconds; a few (GPIO pin changes, the e-ink display model, network credentials) need a reboot, which the page tells you plainly with a **Reboot now** button when needed.

**Useful commands:**
```bash
journalctl -u digipeater -f              # live logs
sudo systemctl restart digipeater        # restart after manual changes
journalctl -u digipeater-tile-update -f  # map auto-update check logs (only does real work once a day; see step 5 above)
journalctl -u direwolf -f                # Direwolf's own output: modem/audio init, PTT, packets heard/sent, direwolf.conf parse errors
systemctl status direwolf                # whether it's currently running, and its last exit status if not
cat direwolf.conf                        # the config actually generated from config.yaml, in the app's working directory
```

Re-running the install command pulls the latest code and redeploys.

---

## Credits

- APRS symbol icons used in the setup wizard: [hessu/aprs-symbols](https://github.com/hessu/aprs-symbols) by Heikki Hannikainen, OH7LZB, CC BY-SA 4.0. See [`web/static/aprs-symbols/COPYRIGHT.md`](web/static/aprs-symbols/COPYRIGHT.md) for the full license and per-symbol attribution.
