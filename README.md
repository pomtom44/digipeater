# APRS Digipeater Monitor

A web-based monitoring system for APRS digipeaters running on Dire Wolf. Displays digipeater status and visualizes repeated APRS packets on an interactive map.

## Features

- **Real-time Status Monitoring**: View digipeater version, GPS status, audio device status, and AGW/KISS readiness
- **Interactive Map**: See all repeated APRS packets on a map with line tracking
- **Asset Management**: Sidebar showing recently seen assets with toggle to show/hide on map
- **Offline Capable**: All assets are local - works without internet (except map tiles)
- **Automatic Updates**: Web interface refreshes every 5 seconds, parser runs every 10 seconds

## Quick Start

1. **Copy files to Raspberry Pi**:
   ```bash
   # Copy Digipeater folder to your home directory, e.g.:
   # /home/pi/digipeater or /home/YOUR_USERNAME/digipeater
   ```

2. **Download Leaflet**:
   ```bash
   cd ~/digipeater  # or cd /home/YOUR_USERNAME/digipeater
   chmod +x download_leaflet.sh
   ./download_leaflet.sh
   ```

3. **Set up log parsing** (daemon service - runs every 10 seconds):
   ```bash
   chmod +x ~/digipeater/parse_log.sh
   chmod +x ~/digipeater/parse_log_daemon.sh
   # Then create systemd service (see detailed setup below)
   ```

4. **Start web server**:
   ```bash
   cd ~/digipeater
   python3 web_server.py 8080
   ```

5. **Access in browser**:
   ```
   http://<raspberry-pi-ip>:8080
   ```

## Detailed Setup

### Prerequisites

- Raspberry Pi running Dire Wolf
- Python 3 (usually pre-installed)
- Internet connection (initially, for downloading Leaflet)

### Installation Steps

#### 1. Copy Files to Raspberry Pi

Copy all files from the `Digipeater` folder to your Raspberry Pi. A good location would be in your home directory:
```bash
~/digipeater/  # or /home/YOUR_USERNAME/digipeater/
```

#### 2. Install Python Dependencies

The parser works without external dependencies, but for better APRS parsing, you can optionally install `aprslib`:

```bash
pip3 install aprslib
```

This is optional - the parser will work without it using manual parsing.

#### 3. Download Leaflet for Offline Use

Run the download script to get Leaflet files:

```bash
cd ~/digipeater  # or cd /home/YOUR_USERNAME/digipeater
chmod +x download_leaflet.sh
./download_leaflet.sh
```

This will download Leaflet CSS, JavaScript, and images to the `leaflet/` directory.

**Note**: For true offline operation, you'll also need to cache map tiles. See the "Offline Map Tiles" section below.

#### 4. Set Up Log File Parsing

##### Option A: Manual Parsing

You can run the parser manually:
```bash
python3 parse_log.py /var/log/direwolf/direwolf.log
```

##### Option B: Daemon Service (Recommended - runs every 10 seconds)

For faster updates, use a daemon service that runs continuously and parses every 10 seconds:

1. **Make scripts executable**:
   ```bash
   chmod +x /home/administrator/aprs-dashboard/parse_log.sh
   chmod +x /home/administrator/aprs-dashboard/parse_log_daemon.sh
   ```

2. **Create a systemd service**:
   ```bash
   sudo nano /etc/systemd/system/digipeater-parser.service
   ```

3. **Add this content** (adjust paths to match your installation):
   ```ini
   [Unit]
   Description=APRS Digipeater Log Parser Daemon
   After=network.target

   [Service]
   Type=simple
   User=administrator
   WorkingDirectory=/home/administrator/aprs-dashboard
   ExecStart=/home/administrator/aprs-dashboard/parse_log_daemon.sh /var/log/direwolf/direwolf.log
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

4. **Enable and start the service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable digipeater-parser.service
   sudo systemctl start digipeater-parser.service
   sudo systemctl status digipeater-parser.service
   ```

##### Option C: Cron Job (runs every 5 minutes)

If you prefer using cron (runs every 5 minutes, which is cron's minimum):

```bash
crontab -e
```

Add this line, **using full absolute paths** (cron doesn't expand `~`):
```
*/5 * * * * /home/administrator/aprs-dashboard/parse_log.sh /var/log/direwolf/direwolf.log
```

**Important**: Replace `/home/administrator/aprs-dashboard` with your actual installation path.

Make sure the script is executable:
```bash
chmod +x /home/administrator/aprs-dashboard/parse_log.sh
```

**Note**: 
- Always use **full absolute paths** in cron (cron doesn't expand `~`)
- Adjust the log file path (`/var/log/direwolf/direwolf.log`) to match your actual Dire Wolf log location
- Common log locations:
  - `/var/log/direwolf/direwolf.log`
  - `/var/log/direwolf.log`
  - `~/direwolf.log`
  - Check your Dire Wolf configuration for the actual log file location
- The script will create log files: `parse_log.log` and `parse_log_error.log` in the same directory for debugging

#### 5. Start the Web Server

##### Option A: Manual Start

```bash
cd ~/digipeater
python3 web_server.py 8080
```

The server will run on port 8080. You can change the port by passing a different number:
```bash
python3 web_server.py 8000
```

##### Option B: Systemd Service (Recommended)

First, determine your username and home directory:

```bash
whoami
echo $HOME
```

Create a systemd service file for automatic startup:

```bash
sudo nano /etc/systemd/system/digipeater-monitor.service
```

Add this content, **replacing `YOUR_USERNAME` and paths** with your actual username and installation directory:

```ini
[Unit]
Description=APRS Digipeater Monitor Web Server
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/YOUR_DIRECTORY
ExecStart=/usr/bin/python3 /home/YOUR_USERNAME/YOUR_DIRECTORY/web_server.py 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Example** (for username `administrator` and directory `aprs-dashboard`):
```ini
[Unit]
Description=APRS Digipeater Monitor Web Server
After=network.target

[Service]
Type=simple
User=administrator
WorkingDirectory=/home/administrator/aprs-dashboard
ExecStart=/usr/bin/python3 /home/administrator/aprs-dashboard/web_server.py 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Note**: If your directory is named something other than `digipeater` (like `aprs-dashboard`), make sure to update all paths in the service file accordingly.

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable digipeater-monitor.service
sudo systemctl start digipeater-monitor.service
```

Check status:
```bash
sudo systemctl status digipeater-monitor.service
```

**If you get a "Failed to determine user credentials" error**, it means the username in the service file doesn't exist. Check your username with `whoami` and update the service file accordingly.

#### 6. Access the Web Interface

Once the server is running, you can access the interface from any device on your local network:

1. Find your Raspberry Pi's IP address:
   ```bash
   hostname -I
   ```

2. Open a web browser and navigate to:
   ```
   http://<raspberry-pi-ip>:8080
   ```

   For example: `http://192.168.1.100:8080`

## Configuration

### Changing the Log File Path

If your Dire Wolf log file is in a different location, update:

1. **Cron job**: Edit the cron entry to use the correct path
2. **parse_log.sh**: Update the default path in the script
3. **parse_log.py**: Update `DEFAULT_LOG_FILE` constant

### Changing the Web Server Port

Edit the port number in:
- Command line: `python3 web_server.py <port>`
- Systemd service: Change the port in `ExecStart`

### Map Center Location

To change the default map center (currently set to Hamilton, New Zealand), edit `app.js`:

```javascript
const MAP_CENTER = [-37.7870, 175.2793]; // [latitude, longitude]
const MAP_ZOOM = 12;
```

## Offline Map Tiles

For true offline operation, you need to cache map tiles. Here are some options:

### Option 1: Use Leaflet Offline Plugin

Install and configure a tile caching solution like `leaflet.offline` or use a tile server that can run locally.

### Option 2: Pre-cache Tiles

Use a tool like `tilemill` or `mbutil` to generate offline tiles for your area of interest.

### Option 3: Use Static Map Images

For a simpler solution, you could use static map images or a local tile server.

**Note**: The current setup will work with internet connection for map tiles. For offline use, additional tile caching is required.

## Setting Up WiFi Access Point (Hotspot)

To allow phones and laptops to connect to the Raspberry Pi via WiFi and access the dashboard without internet:

### Prerequisites

- Raspberry Pi with WiFi capability
- Raspberry Pi OS (or similar Linux distribution)
- Root/sudo access

### Step 1: Install Required Packages

```bash
sudo apt-get update
sudo apt-get install -y hostapd dnsmasq
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq
```

### Step 2: Configure Static IP for WiFi Interface

Edit the network configuration:

```bash
sudo nano /etc/dhcpcd.conf
```

Add at the end:

```
interface wlan0
static ip_address=192.168.4.1/24
nohook wpa_supplicant
```

### Step 3: Configure hostapd (Access Point)

Create the hostapd configuration file:

```bash
sudo nano /etc/hostapd/hostapd.conf
```

Add the following (adjust `ssid` and `wpa_passphrase` to your preferences):

```
interface=wlan0
driver=nl80211
ssid=APRS-Digipeater
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=YourPassword123
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
```

**Important:** Change `wpa_passphrase` to a secure password of your choice.

### Step 4: Configure hostapd Service

Edit the hostapd defaults:

```bash
sudo nano /etc/default/hostapd
```

Find the line with `DAEMON_CONF=` and set it to:

```
DAEMON_CONF="/etc/hostapd/hostapd.conf"
```

### Step 5: Configure dnsmasq (DHCP Server)

Backup the original config and create a new one:

```bash
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
sudo nano /etc/dnsmasq.conf
```

Add the following:

```
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
```

### Step 6: Enable IP Forwarding (Optional - for internet sharing)

If you want connected devices to access the internet through the Pi's ethernet connection:

```bash
sudo nano /etc/sysctl.conf
```

Uncomment the line:
```
net.ipv4.ip_forward=1
```

Then add iptables rules (only if you want internet sharing):

```bash
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
sudo iptables -A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT
```

To make iptables rules persistent:

```bash
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

### Step 7: Start Services

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq
sudo systemctl start hostapd
sudo systemctl start dnsmasq
```

### Step 8: Configure Web Server to Listen on All Interfaces

Make sure your web server is configured to listen on all network interfaces (0.0.0.0) so it's accessible from connected devices.

The `web_server.py` should already be configured correctly, but verify it's listening on `0.0.0.0` or all interfaces.

### Step 9: Test the Setup

1. **On your phone/laptop:**
   - Look for WiFi network named "APRS-Digipeater" (or whatever you set in `ssid`)
   - Connect using the password you set in `wpa_passphrase`
   - Your device should get an IP address like `192.168.4.x`

2. **Access the dashboard:**
   - Open a web browser
   - Navigate to: `http://192.168.4.1:8000` (or whatever port your web server uses)
   - The dashboard should load!

### Troubleshooting WiFi Access Point

**If the access point doesn't appear:**

1. Check hostapd status:
   ```bash
   sudo systemctl status hostapd
   ```

2. Check dnsmasq status:
   ```bash
   sudo systemctl status dnsmasq
   ```

3. Check for errors in logs:
   ```bash
   sudo journalctl -u hostapd
   sudo journalctl -u dnsmasq
   ```

4. Verify WiFi interface:
   ```bash
   ip addr show wlan0
   ```

5. Some WiFi adapters may need additional drivers. Check compatibility:
   ```bash
   lsusb
   iw list
   ```

**If devices can't connect:**

- Verify the password is correct
- Check that the WiFi interface is up: `ip link show wlan0`
- Restart services: `sudo systemctl restart hostapd dnsmasq`

**If devices connect but can't access the dashboard:**

- Verify web server is running: `sudo systemctl status digipeater-monitor`
- Check firewall rules: `sudo iptables -L`
- Try accessing from the Pi itself: `curl http://localhost:8000`
- Check web server is listening on all interfaces (not just 127.0.0.1)

### Alternative: Using NetworkManager (Raspberry Pi OS Desktop)

If you're using Raspberry Pi OS with desktop, you can also set up a hotspot using NetworkManager:

1. Right-click the network icon in the system tray
2. Select "Turn On Wi-Fi Hotspot..."
3. Configure the SSID and password
4. The Pi will automatically set up DHCP

However, the command-line method above gives you more control and works on headless systems.

## Troubleshooting

### Parser Not Finding Packets

1. Check that the log file path is correct
2. Verify Dire Wolf is logging packets (check log file manually)
3. Check log file permissions - the script needs read access

### Cron Job Not Working

If the cron job doesn't appear to be running:

1. **Check cron logs**:
   ```bash
   # Check if cron is running
   sudo systemctl status cron
   
   # View cron execution logs (location varies by distro)
   grep CRON /var/log/syslog
   # or
   journalctl -u cron
   ```

2. **Verify the cron job is installed**:
   ```bash
   crontab -l
   ```

3. **Check the parser log files** (created by the script):
   ```bash
   cat /home/administrator/aprs-dashboard/parse_log.log
   cat /home/administrator/aprs-dashboard/parse_log_error.log
   ```

4. **Test the script manually**:
   ```bash
   /home/administrator/aprs-dashboard/parse_log.sh /var/log/direwolf/direwolf.log
   ```

5. **Common issues**:
   - **Using `~` in cron**: Cron doesn't expand `~`, use full paths like `/home/administrator/aprs-dashboard/`
   - **PATH issues**: The script now finds python3 automatically, but if issues persist, use full path: `/usr/bin/python3`
   - **File permissions**: Make sure the script is executable: `chmod +x parse_log.sh`
   - **Log file permissions**: Make sure the user running cron can read the Dire Wolf log file
   - **Python not found**: Check `which python3` and update the script if needed

6. **Add MAILTO to cron** (optional, to get email on errors):
   ```bash
   crontab -e
   # Add at top:
   MAILTO=your-email@example.com
   ```

### Web Server Not Starting

1. Check if port is already in use:
   ```bash
   sudo netstat -tulpn | grep 8080
   ```
2. Check Python version:
   ```bash
   python3 --version
   ```
3. Check for errors in systemd logs:
   ```bash
   sudo journalctl -u digipeater-monitor.service -f
   ```

### Systemd Service Failing with "Failed to determine user credentials"

If you see errors like:
```
digipeater-monitor.service: Failed to determine user credentials: No such process
digipeater-monitor.service: Failed at step USER spawning /usr/bin/python3: No such process
```

This means the username in your systemd service file doesn't exist. To fix:

1. Find your actual username:
   ```bash
   whoami
   ```

2. Edit the service file and update the `User=` line:
   ```bash
   sudo nano /etc/systemd/system/digipeater-monitor.service
   ```
   
   Change `User=pi` (or whatever is there) to your actual username, for example:
   ```ini
   User=administrator
   ```

3. Also update the `WorkingDirectory` and `ExecStart` paths to match your actual installation directory. For example, if installed at `/home/administrator/aprs-dashboard`:
   ```ini
   WorkingDirectory=/home/administrator/aprs-dashboard
   ExecStart=/usr/bin/python3 /home/administrator/aprs-dashboard/web_server.py 8080
   ```

4. Reload and restart:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart digipeater-monitor.service
   sudo systemctl status digipeater-monitor.service
   ```

### Map Not Loading

1. Check browser console for errors (F12)
2. Verify Leaflet files were downloaded correctly
3. Check that `leaflet/` directory exists with all files

### No Data Showing

1. Verify the parser is running and creating `digipeater_data.json`
2. Check file permissions - web server needs read access
3. Check that APRS packets are being received by Dire Wolf

## File Structure

After setup, your directory should look like:

```
~/digipeater/  (or /home/YOUR_USERNAME/digipeater/)
├── parse_log.py
├── parse_log.sh
├── web_server.py
├── download_leaflet.sh
├── index.html
├── styles.css
├── app.js
├── README.md
├── digipeater_data.json (created by parser)
├── digipeater_status.json (created by parser)
└── leaflet/
    ├── leaflet.css
    ├── leaflet.js
    └── images/
        ├── marker-icon.png
        ├── marker-icon-2x.png
        ├── marker-shadow.png
        ├── layers.png
        └── layers-2x.png
```

## Files

- `parse_log.py` - Parses Dire Wolf logs and extracts APRS packets
- `parse_log.sh` - Shell wrapper for parsing (used by daemon and cron)
- `parse_log_daemon.sh` - Daemon script that runs parser every 10 seconds
- `web_server.py` - Lightweight Python web server
- `index.html` - Web interface
- `styles.css` - Styling
- `app.js` - JavaScript for map and UI
- `download_leaflet.sh` - Downloads Leaflet library for offline use

## Requirements

- Python 3
- Dire Wolf running and logging
- Optional: `aprslib` for better APRS parsing (`pip3 install aprslib`)

## Notes

- Map tiles require internet connection (or offline tile caching)
- Data is stored in JSON files (`digipeater_data.json`, `digipeater_status.json`)
- Automatically limits to 1000 packets per callsign to prevent file growth

## Security Notes

- The web server is designed for local network use only
- No authentication is implemented - anyone on your network can access it
- For production use, consider adding authentication or firewall rules
- The server binds to all interfaces (0.0.0.0) - restrict with firewall if needed

## Maintenance

- The parser automatically limits data to 1000 packets per callsign to prevent file growth
- Old data can be cleared by deleting `digipeater_data.json` (it will be recreated)
- Log files can grow large - consider log rotation for Dire Wolf logs

## Support

For issues or questions, check:
- Dire Wolf log file for errors
- Python script output for parsing errors
- Browser console (F12) for JavaScript errors
- System logs for service issues
