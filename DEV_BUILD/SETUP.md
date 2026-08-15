# APRS Digipeater: Setup Guide

---

## Part 1: Wire Up Hardware

Wire up whatever hardware you're using before flashing/installing; see [PINOUT.md](PINOUT.md) for the full pin diagram and per-component wiring tables. Skip anything you're not using, it's selected as "None"/left disconnected during setup and can be added later.

- **E-Ink display**: most models aren't direct-plug RPi HATs and need to be wired to the Pi by hand.
- **PTT**: only needed if using GPIO-pin PTT (wired through an optocoupler, not directly to the radio). VOX and CM108-adapter PTT need no Pi wiring at all.
- **Radio power relay**: powers the radio on/off automatically with the digipeater software.
- **GPS**: only needs wiring if using a UART-connected module; a USB GPS just plugs in and is detected automatically.

---

## Part 2: Install

### Method 1: Pre-built image (recommended)

1. Download the latest image from the [Releases page](https://github.com/pomtom44/digipeater/releases)
2. Open Raspberry Pi Imager, **Choose OS** → **Use custom**, and select the downloaded image
3. **Choose Storage** → select your SD card, then write

The image already has everything installed; it just needs to boot.

### Method 2: Manual install

1. Open Raspberry Pi Imager
2. **Choose Device** → Raspberry Pi 3
3. **Choose OS** → Raspberry Pi OS (other) → **Raspberry Pi OS (Legacy, 64-bit) Lite**
   - This project is built and tested against Bookworm specifically. The plain "Raspberry Pi OS Lite (64-bit)" option now installs Trixie (Debian 13) by default, which is untested here. Use the Legacy option to get Bookworm.
4. **Choose Storage** → select your SD card
5. Click **Next**, then **Edit Settings**:
   - **General tab**: hostname `digipeater`, a username/password (you'll need it to SSH in), and WiFi SSID/password if not using ethernet
   - **Services tab**: enable SSH, using password authentication
6. Save, confirm, and write

Once flashing finishes, insert the SD card into the Pi and power it on. After ~60-90 seconds, SSH in and run the installer:

```bash
ssh pi@digipeater.local
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/DEV_BUILD/install.sh | bash
```

You'll be asked for a WiFi country code (only if one isn't already set) and which e-ink display is connected (pick "None" if there isn't one).

---

## Part 3: Initial Setup

**Before you start, have ready:**
- Your callsign and SSID (the APRS-IS passcode fills in automatically from these, no need to look it up)
- A decision on IGate mode (Off / RX only / RX & TX): RX only is the safe default if unsure; RX & TX also relays internet messages back onto RF

Reboot and follow the setup wizard.
