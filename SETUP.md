# APRS Digipeater — Installation Guide

## What You Need

- Raspberry Pi 3B (or later model)
- MicroSD card — 16GB minimum, 32GB recommended
- Power supply for the Pi
- A computer to flash the SD card
- Internet connection (ethernet cable or WiFi credentials for initial setup)

---

## Step 1 — Download Raspberry Pi Imager

Download and install **Raspberry Pi Imager** on your computer:
- https://www.raspberrypi.com/software/

---

## Step 2 — Flash the SD Card

1. Insert the MicroSD card into your computer
2. Open Raspberry Pi Imager
3. Click **Choose Device** → select **Raspberry Pi 3**
4. Click **Choose OS** → **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (64-bit)**
   - Lite = no desktop, command line only — this is correct
5. Click **Choose Storage** → select your SD card
6. Click **Next** — when asked about OS customisation, click **Edit Settings**

---

## Step 3 — Configure the Image

In the OS Customisation screen, set the following:

**General tab:**
- Hostname: `digipeater`
- Username: `pi` (or your preference)
- Password: set a strong password — you will need this to SSH in
- If you want to use WiFi for the initial setup, enter your WiFi SSID and password here
  - If you will use ethernet, leave WiFi blank

**Services tab:**
- Enable SSH: **checked**
- Use password authentication

Click **Save**, then **Yes** to apply, then **Yes** to confirm writing.

Wait for the flash and verify to complete.

---

## Step 4 — First Boot

1. Insert the SD card into the Pi
2. Connect ethernet if you are using it
3. Power on the Pi
4. Wait approximately 60–90 seconds for first boot to complete

---

## Step 5 — Find the Pi on Your Network

**Option A — Use the hostname:**
```
ssh pi@digipeater.local
```

**Option B — Find the IP via your router:**
Log in to your router's admin page and look for a device named `digipeater` in the connected devices list, then:
```
ssh pi@<ip-address>
```

When prompted, type `yes` to accept the host key, then enter the password you set in Step 3.

---

## Step 6 — Run the Install Script

Once logged in via SSH, run:

```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/install.sh | bash
```

> Alternatively, copy `install.sh` to the Pi via SCP and run it directly:
> ```bash
> bash install.sh
> ```

The script will handle everything from here. It will print progress as it goes. The full install takes approximately 5–10 minutes depending on your internet speed.

---

## Step 7 — Access the Web Interface

Once the install script completes, the Pi will reboot. After it comes back up:

- Open a browser and go to **http://digipeater.local**
- Or use the IP address: **http://\<ip-address\>**

You will be taken through the network and system setup wizard.

---

## Troubleshooting

**Cannot connect via SSH:**
- Confirm the SD card was flashed with SSH enabled (Step 3)
- Try using the IP address instead of the hostname
- Ensure the Pi has had 90 seconds to fully boot

**`digipeater.local` not resolving:**
- This requires mDNS support on your computer
- Windows: install [Bonjour](https://support.apple.com/kb/DL999) if not already present (iTunes installs it automatically)
- Linux/Mac: should work out of the box
- Fallback: use the IP address directly

**WiFi not connecting on first boot:**
- Double-check the SSID and password entered in Imager
- Ensure the WiFi network is 2.4GHz — the Pi 3B does not support 5GHz
- Use ethernet for the initial setup if WiFi is unreliable
