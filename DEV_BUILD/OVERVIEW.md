# How It Works

A high-level look at what's actually running on the Pi and how the pieces talk to each other. For wiring, see [PINOUT.md](PINOUT.md); for setup, see [SETUP.md](SETUP.md).

---

## The big picture

This project doesn't reimplement APRS packet handling itself. It's a Raspberry Pi that runs [Direwolf](https://github.com/wb2osz/direwolf) (a well-established open-source soundmodem/TNC) to do the actual digipeating and IGating, wrapped in a web dashboard and setup wizard that generate Direwolf's config for you and manage it, plus an optional e-ink display for at-a-glance status.

Three systemd services do the real work:

| Service | What it does |
|---|---|
| `digipeater` | The Python app: web dashboard, setup wizard, e-ink display, and everything that manages the other two services below |
| `direwolf` | The actual APRS soundmodem: digipeating, IGating, beaconing |
| `digipeater-tile-update.timer` | Checks once a day for a newer offline map build |

A few standard Linux services this project configures but doesn't replace: `gpsd` (GPS), `chrony` (system clock, optionally synced from GPS), and NetworkManager (WiFi/hotspot).

---

## Boot sequence

1. The Python app starts, initializes the e-ink display (if one's connected), and figures out networking: use ethernet or WiFi if already connected, otherwise fall back to broadcasting its own WiFi hotspot so you can reach it from a phone or laptop.
2. **First boot** (no saved config yet): serves the setup wizard. Nothing else starts until setup is finished.
3. **Every boot after that**: reads the saved config, applies GPS/relay/display settings, regenerates Direwolf's config file, and starts or stops the `direwolf` service to match.
4. The web dashboard comes up either way, on port 80.

Settings live in one file, `config.yaml`, written by the wizard once and editable afterward from the dashboard's Config page. Nothing is applied "live" by editing that file directly, the app only reads it at boot or when you save a change through the web UI.

---

## Radio path

Starting the radio isn't instant, since real hardware needs time to settle:

1. Confirm there's a usable position (a GPS fix, or a manual position you've entered), since the station shouldn't beacon a bogus location.
2. Power the radio on via a GPIO-controlled relay, and wait for it to finish booting.
3. Start Direwolf, which now takes over: it keys PTT when it needs to transmit, reads audio in/out for the actual APRS tones, and handles all the on-air protocol logic itself.

Stopping reverses this: stop Direwolf first, wait for it to actually finish shutting down, then power the relay off, rather than cutting power out from under it.

---

## Web dashboard and wizard

Both are plain web pages served by the Python app, no separate frontend framework or build step. The setup wizard only exists before first boot; once `config.yaml` exists, it's gone for good and the dashboard takes over. The dashboard's Config page is where all the same settings become editable again afterward.

The dashboard's map works offline, using pre-downloaded vector map tiles rather than live internet tiles (downloading arbitrary live map tiles for offline use isn't allowed under OpenStreetMap's usage policy). If the Pi has internet, it can also stream full-detail map data live to fill in areas you haven't downloaded.

---

## Troubleshooting

**See everything at once**, interleaved by time, across the app and Direwolf:
```bash
journalctl -u digipeater -u direwolf -f
```

**Individual logs:**
```bash
journalctl -u digipeater -f              # the web app / wizard / boot sequence
journalctl -u direwolf -f                # Direwolf's own output: modem/audio init, PTT, packets heard/sent
journalctl -u digipeater-tile-update -f  # map auto-update checks (only does real work once a day)
```

**Service status:**
```bash
systemctl status digipeater
systemctl status direwolf
sudo systemctl restart digipeater        # restart the web app after a manual change
```

**Check what Direwolf is actually configured to do:**
```bash
cat direwolf.conf   # in the app's working directory; regenerated from config.yaml on every boot
```

**Re-run the installer** to pull the latest code and redeploy:
```bash
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/DEV_BUILD/install.sh | bash
```
