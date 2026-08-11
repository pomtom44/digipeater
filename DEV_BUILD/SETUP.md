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
- If using a GPIO-pin or CM108 PTT connection, see [PINOUT.md](PINOUT.md) — GPIO-pin PTT uses a fixed pin (BCM GPIO 22), not something you pick in the wizard
- If using GPS, have it connected before running the installer — `gpsd` is installed and started automatically, and USB GPS devices are picked up on their own

SSH into the Pi, then run:

```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/DEV_BUILD/install.sh | bash
```

Along the way the installer also pre-caches a coarse whole-world map base layer (zoom 0–5, ~20MB from OpenStreetMap) — best-effort, so a flaky connection at that point doesn't abort the install; re-run `DEV_BUILD/scripts/precache_world_map.py` later if it gets skipped. This just means a future map view has *something* to show before you've downloaded your own station's region via the wizard's Map caching step — it's not detailed enough to be useful on its own.

Near the end you'll be asked for a WiFi country code (only if one isn't already set — needed for the hotspot to work at all) and which e-ink display is connected (pick "None" if there isn't one). The installer then sets up the `digipeater` service to start on every boot and reboots when finished.

**After reboot:**
- The e-ink display shows first-boot status, including the IP and network method currently configured
- Ethernet, Wifi, or Hotspot with SSID, Password, and the address to browse to
- Either make sure you are connected to your network and getting an IP, or connect to the hotspot
- Open `http://digipeater.local`, or the IP address shown on the display, in a browser to continue the setup

**The setup wizard has nine steps:**
1. **Network setup** — shows current connection status; if on the hotspot, lets you scan for and save WiFi credentials to connect to on the next normal boot
2. **APRS settings** — callsign/SSID, digipeating and IGate modes, IGate connection details (collapsed by default, sensible defaults pre-filled), station icon/comment, and RF/IGate beacon settings
3. **Radio setup** — audio device, PTT method, initial frequency, and TX power (radio model and power level are placeholders for now — see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md))
4. **GPS setup** — pick a connected GPS device (or "No GPS"), beacon position source (GPS or manual lat/lon), optional system time sync from GPS with a timezone picker, and a live GPS status display (position/fix/satellite count) — needs `gpsd` actually running with a device attached to show real data. Device selection, time sync, and timezone are all applied to the system (gpsd, chrony, `timedatectl`) on the next boot; beacon position source is saved but not yet used anywhere (no `direwolf.conf` generator exists yet — see [TODO.md](../TODO.md)).
5. **Map caching** — checks for an internet connection; if there isn't one, just shows a warning (nothing to cache without one). If there is, drag the pin (or click anywhere, or reuse the station's own GPS position) to move the whole region, and drag the small squares on each edge to resize it independently — drag one side to turn it into a rectangle rather than a square. No coordinate fields to type into; the map alone defines the region. Pick a detail level with a single zoom slider (1–16, default 10 — min zoom is always 1, since that barely adds any tiles regardless of region size), see an estimated tile count/size (shown in GB once it passes ~1.2GB), then download that region right there in the wizard from OpenStreetMap's free tile server — no account or API key needed, with a live ETA once it's running. Cached tiles are then served from disk with no internet needed at all until re-downloaded. Entirely optional — never blocks moving on, and can be skipped and revisited later.
6. **E-Ink display** — pick the connected display, preset to whatever `install.sh` configured. Unlike most of the wizard, this one takes effect for real: it's written straight to `display_config.json` and Finish always reboots right after. Below that, a reorderable list of future rotation screens (Status/Config summary/Location/Last beacon/Last heard), each with a duration (30s default) — move a screen to Disabled and back, or reorder with the arrows. The list itself is saved but not applied yet, since there's no page-rotation renderer built in `DEV_BUILD` yet (see [TODO.md](../TODO.md)).
7. **User management** — pick a web UI security mode: No security (open access), Read only (viewing is open, changes need the password), or Full security (password needed for everything, including viewing). Anything but No security shows an admin password field plus a confirm field — Next stays disabled until they match and meet the 8-character minimum, since there's no way to recover or change this password later yet. Collected only — there's no login system built yet in `DEV_BUILD` to actually enforce it (see [TODO.md](../TODO.md)), but the password itself is hashed (PBKDF2, salted) before it's written to `config.yaml` — never stored in plaintext.
8. **Startup** — last step before Finish, deliberately: "start automatically on boot" and "restart automatically if it crashes" (with max attempts / delay between attempts), both checked by default. Collected-only for now — no Direwolf process exists yet to actually start or restart (see [TODO.md](../TODO.md)).
9. **Finish** — press **Finish & Reboot** to save everything and reboot into standard mode; the page auto-reloads into the normal dashboard once it's back up

**Useful commands:**
```bash
journalctl -u digipeater -f       # live logs
sudo systemctl restart digipeater # restart after manual changes
```

Re-running the install command pulls the latest code and redeploys.

---

## Credits

- APRS symbol icons used in the setup wizard: [hessu/aprs-symbols](https://github.com/hessu/aprs-symbols) by Heikki Hannikainen, OH7LZB — CC BY-SA 4.0. See [`web/static/aprs-symbols/COPYRIGHT.md`](web/static/aprs-symbols/COPYRIGHT.md) for the full license and per-symbol attribution.
