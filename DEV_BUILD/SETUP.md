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

Along the way the installer also fetches `go-pmtiles` (a small static binary used by the wizard's Map caching step to download offline map data), the basemap fonts/icons it renders with, and pre-caches a coarse whole-world map (~1GB) so the region picker has something to show even with no internet at setup time. All of this is best-effort, so a flaky connection at that point doesn't abort the install. If any of it is skipped, Map caching just won't be usable until it's re-run later (see [TODO.md](../TODO.md)).

It also installs Direwolf itself and its own `direwolf.service` unit, though that unit is deliberately left disabled at the systemd level: the app starts and stops it based on the "start automatically on boot" setting from step 8 below (and the region/mode settings from step 2), regenerating `direwolf.conf` fresh from `config.yaml` on every normal boot rather than depending on the file surviving between installs.

Near the end you'll be asked for a WiFi country code (only if one isn't already set; needed for the hotspot to work at all) and which e-ink display is connected (pick "None" if there isn't one). The installer then sets up the `digipeater` service to start on every boot and reboots when finished.

**After reboot:**
- The e-ink display shows first-boot status, including the IP and network method currently configured
- Ethernet, Wifi, or Hotspot with SSID, Password, and the address to browse to
- Either make sure you are connected to your network and getting an IP, or connect to the hotspot
- Open `http://digipeater.local`, or the IP address shown on the display, in a browser to continue the setup

**The setup wizard has nine steps:**
1. **Network setup**: shows current connection status; if on the hotspot, lets you scan for and save WiFi credentials to connect to on the next normal boot
2. **APRS settings**: callsign/SSID, digipeating and IGate modes, IGate connection details (collapsed by default, sensible defaults pre-filled), station icon/comment, and RF/IGate beacon settings
3. **Radio setup**: audio device, PTT method (GPIO pin is the default, VOX and CM108 are also available), initial frequency, and TX power (radio model and power level are placeholders for now; see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md)). Leaving the frequency blank prompts a confirm before moving on, same as the APRS step's IGate region check, since Direwolf needs a real one to transmit on.
4. **GPS setup**: pick a connected GPS device (or "No GPS"), beacon position source (GPS or manual lat/lon), optional system time sync from GPS with a timezone picker, and a live GPS status display (position/fix/satellite count). This needs `gpsd` actually running with a device attached to show real data. Manual position can be entered as decimal degrees, degrees/minutes/seconds (accepts DMS or DDM, with a leading/trailing N/S/E/W or a bare minus sign), a Maidenhead grid square (e.g. `RF80qh`), or a Plus Code, including the short form Google Maps often gives out (e.g. `8FVC9G8F+6X` or just `57QW+PXQ`; pasting the trailing place name Google Maps adds, e.g. "...+6X Auckland, New Zealand", is fine too, it's stripped automatically). A short code needs a nearby reference position to resolve (a live GPS fix, or whatever position was last entered in another format); with neither available, it says so instead of a generic parse error. A format dropdown switches between them, converting whatever's already entered rather than clearing it, and all four work with no internet connection since it's just arithmetic (unlike something like what3words, which was deliberately left out for needing a live call to a commercial API just to resolve three words to a position; Plus Codes are Google's own open, offline alternative to exactly that). Device selection, time sync, and timezone are all applied to the system (gpsd, chrony, `timedatectl`) on the next boot; beacon position source feeds straight into `direwolf.conf`'s `PBEACON` line on every normal boot (a manual position as plain `LAT=`/`LONG=` degrees, or a bare `GPSD` directive if the beacon should follow the live fix instead).
5. **Map caching**: the region picker itself always works, with or without internet, since it renders from a coarse whole-world map (`world.pmtiles`, zoom 0–8) pre-cached by the installer rather than live tiles (if that pre-cache is missing entirely, whether no internet during install or the step was skipped, this step instead shows a "map caching isn't available" message and stops there). Drag the pin (or click anywhere, or reuse the station's own GPS position) to move the whole region, and drag the small squares on each edge to resize it independently: drag one side to turn it into a rectangle rather than a square. No coordinate fields to type into; the map alone defines the region. Pick a detail level with a single zoom slider (1–15, default 10), then download that region right there in the wizard as a single, more-detailed offline map data file, extracted from [Protomaps'](https://protomaps.com/) free hosted planet build; no account or API key needed. That part does need a live connection: if there isn't one, a note says so, and dragging/clicking/the Download button are disabled while the pre-cached map stays viewable. There's no reliable size estimate beforehand (it depends on how much map data actually exists in the area, tucked behind a "?" next to the Download button); real progress (bytes downloaded, elapsed time) shows once a download starts, and it keeps running in the background even after moving on to later steps. Entirely optional: never blocks moving on, and can be skipped and revisited later. (The auto-update toggle for this cached data lives on the Finish step, below.)
6. **E-Ink display**: pick the connected display, preset to whatever `install.sh` configured. Unlike most of the wizard, this one takes effect for real: it's written straight to `display_config.json` and Finish always reboots right after. Below that, a reorderable list of future rotation screens (Status/Config summary/Location/Last beacon/Last heard), each with a duration (30s default); move a screen to Disabled and back, or reorder with the arrows. The list itself is saved but not applied yet, since there's no page-rotation renderer built in `DEV_BUILD` yet (see [TODO.md](../TODO.md)).
7. **User management**: pick a web UI security mode: No security (open access), Read only (viewing is open, changes need the password), or Full security (password needed for everything, including viewing). Anything but No security shows an admin password field plus a confirm field; Next stays disabled until they match and meet the 8-character minimum, since there's no way to recover or change this password later yet. The password itself is hashed (PBKDF2, salted) before it's written to `config.yaml`, never stored in plaintext, and is enforced for real on every login from then on (a plain form POST to the server, which checks the hash and sets a session cookie).
8. **Startup**: last step before Finish: "start automatically on boot" and "restart automatically if it crashes" (with max attempts / delay between attempts), both checked by default. "Start automatically on boot" is applied for real: it's what decides whether `direwolf.service` gets started on every normal boot. The crash-restart fields are still collected only for now, not yet wired to the systemd service's own `Restart=`/`RestartSec=` behaviour (see [TODO.md](../TODO.md)). Below that, an "Automatically check for map updates" toggle plus a check-time field, defaulted **on** if there's internet right now (off otherwise, so a station that's normally offline isn't left with a background task quietly failing every day); when on, the device checks once a day for a newer map build and silently re-downloads the world map (and the region from step 5, if one was picked) in the background from then on.
9. **Finish**: if a region download from step 5 is still running in the background, **Finish & Reboot** stays disabled (with live progress shown right there) until it finishes. Rebooting mid-download would stop it for good, since this wizard only exists on first boot. Otherwise, press **Finish & Reboot** to save everything and reboot into standard mode; the page auto-reloads into the normal dashboard once it's back up

**Useful commands:**
```bash
journalctl -u digipeater -f              # live logs
sudo systemctl restart digipeater        # restart after manual changes
journalctl -u digipeater-tile-update -f  # map auto-update check logs (only does real work once a day; see step 5 above)
```

Re-running the install command pulls the latest code and redeploys.

---

## Credits

- APRS symbol icons used in the setup wizard: [hessu/aprs-symbols](https://github.com/hessu/aprs-symbols) by Heikki Hannikainen, OH7LZB, CC BY-SA 4.0. See [`web/static/aprs-symbols/COPYRIGHT.md`](web/static/aprs-symbols/COPYRIGHT.md) for the full license and per-symbol attribution.
