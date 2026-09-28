# How It Works

A high-level look at what's actually running on the Pi and how the pieces talk to each other. For wiring, see [PINOUT.md](PINOUT.md); for setup, see [SETUP.md](SETUP.md); for the exact known-working parts list, see [IDEAL_SETUP.md](IDEAL_SETUP.md).

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

1. The Python app starts, initializes the e-ink display (if one's connected), and figures out networking: use ethernet or WiFi if already connected, otherwise fall back to broadcasting its own WiFi hotspot (SSID `Digipeater`, password `Digi1234`) so you can reach it from a phone or laptop.
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

## Signal test (RF reach check)

For an RF-only setup (digipeating on, IGate off), the Config page's Signal Test tab checks whether this digipeater's transmissions actually reach far enough to be gated onto APRS-IS by some other station.

It doesn't use APRS-IS or the internet on this station's side at all:

1. The app builds an APRS message packet addressed to a callsign you enter (a nearby igate-enabled station), and writes it straight to Direwolf's KISS port so Direwolf transmits it over RF, same as any other packet.
2. If that station hears it, its own igate gates it onto APRS-IS as normal.
3. A listener watching APRS-IS for that callsign (not part of this project) replies over APRS-IS.
4. If that station's igate is running in full RX & TX mode, it relays the reply back out over RF.
5. This digipeater hears the reply directly on its own radio; `packet_log.py`'s existing packet-decoding loop (the same one that tracks heard stations) catches it and matches it back to the test.

Since only steps 1 and 5 happen on this station, the test works even with no internet access at all here. It confirms RF reach to another station's igate, not this digipeater's own IGate/APRS-IS access. That's a separate concern, which is why this feature is disabled whenever this station's own IGate is turned on.

`ZL4ST-16` runs a public listener for step 3, on by default in the Signal Test tab. To self-host your own instead (a different callsign, closer to your own coverage area), see [DigipeaterPing](https://github.com/pomtom44/DigipeaterPing).

**No reply?** Check [digiping.zl4st.com](https://digiping.zl4st.com) to see if your ping was heard at all. If it shows up there, steps 1-3 worked, this digipeater is reaching that station and getting into APRS-IS fine, and the fault is on the return leg (step 4 or 5: their igate not relaying back, or you're out of RF range for the reply). If it never shows up, your signal isn't reaching that station in the first place.

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
curl -sSL https://raw.githubusercontent.com/pomtom44/digipeater/main/install.sh | bash
```
