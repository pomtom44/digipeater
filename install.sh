#!/bin/bash
set -e

# ─────────────────────────────────────────────
# APRS Digipeater: Install Script
# ─────────────────────────────────────────────

INSTALL_DIR="/opt/digipeater"
SERVICE_NAME="digipeater"
VENV_DIR="$INSTALL_DIR/venv"
REPO_URL="https://github.com/pomtom44/digipeater.git"
APP_DIR="$INSTALL_DIR"

# ── Colours ──────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
info() { echo -e "${YELLOW}  → $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

# Internal: shows a spinner while running a command with output captured
# to $_SPIN_LOG, restoring the cursor line when done. Returns the command's
# exit status; the two wrappers below decide what to do with a failure.
_spin() {
    local msg="$1"; shift
    _SPIN_LOG=$(mktemp)
    "$@" > "$_SPIN_LOG" 2>&1 &
    local pid=$!
    local spinstr='|/-\'
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        i=$(( (i + 1) % 4 ))
        printf "\r${YELLOW}  → %s %s${NC}" "$msg" "${spinstr:$i:1}"
        sleep 0.1
    done
    wait "$pid"
    local status=$?
    printf "\r\033[K"
    return $status
}

# Runs a command with its output hidden behind a spinner, only showing that
# output if the command actually fails (e.g. apt-get's per-package unpacking
# noise, which -qq alone doesn't suppress since that's dpkg's own output).
# Aborts the whole installer on failure.
run_with_spinner() {
    local msg="$1"
    if ! _spin "$@"; then
        echo -e "${RED}  ✗ $msg failed:${NC}"
        cat "$_SPIN_LOG"
        rm -f "$_SPIN_LOG"
        exit 1
    fi
    rm -f "$_SPIN_LOG"
}

# Same spinner UI, but a failure is just a warning (with the captured
# output) instead of aborting the whole install, for steps like the world
# map pre-cache, where a flaky connection at that exact moment shouldn't
# sink the rest of setup the way a failed apt/git step should. Returns 1 on
# failure so the caller can skip its own success message.
run_with_spinner_soft() {
    local msg="$1"
    if _spin "$@"; then
        rm -f "$_SPIN_LOG"
        return 0
    fi
    echo -e "${YELLOW}  ⚠ $msg failed, continuing:${NC}"
    cat "$_SPIN_LOG"
    rm -f "$_SPIN_LOG"
    return 1
}

echo ""
echo "╔══════════════════════════════════════╗"
echo "║    APRS Digipeater: Installer        ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Check running as correct user ────────────
if [ "$EUID" -eq 0 ]; then
    fail "Do not run this script as root. Run as your normal user (e.g. pi). sudo will be used where needed."
fi

# ── Check OS ─────────────────────────────────
if ! grep -qi "bookworm" /etc/os-release 2>/dev/null; then
    echo -e "${YELLOW}  Warning: This script is tested on Raspberry Pi OS Bookworm.${NC}"
    echo -e "${YELLOW}  Other versions may work but are not guaranteed.${NC}"
    read -p "  Continue anyway? [y/N] " confirm < /dev/tty
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi
ok "OS check passed"

# ── Prime sudo ─────────────────────────────────
# Ask for the sudo password up front, in the foreground, before any spinner
# backgrounds a sudo call; an interactive password prompt doesn't mix well
# with a backgrounded command. This also keeps the credential cached for the
# rest of the script (sudo's default timeout comfortably covers the install).
info "This installer needs sudo access..."
sudo -v
ok "Sudo access confirmed"

# ── System update ─────────────────────────────
run_with_spinner "Updating package lists..." sudo apt-get update -qq
ok "Package lists updated"

# ── Install system packages ───────────────────
# direwolf isn't apt-installed (Bookworm's package is stuck on 1.6, no libgpiod); built from source below instead.
run_with_spinner "Installing system packages..." sudo apt-get install -y -qq \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-rpi.gpio \
    python3-spidev \
    fonts-dejavu-core \
    gpsd \
    gpsd-clients \
    chrony \
    curl \
    build-essential \
    cmake \
    libasound2-dev \
    libudev-dev \
    libavahi-client-dev \
    libgpiod-dev \
    libgps-dev \
    libhamlib-dev
ok "System packages installed"

# ── Use chrony for system time, not systemd-timesyncd ──
# chrony is what lets the GPS setup step's "update system time from GPS"
# option actually work (via a GPS refclock, see services/gpsconfig.py);
# systemd-timesyncd has no equivalent. Swapped in as a straight 1:1
# replacement for normal internet NTP too, so this isn't a downgrade for
# anyone who leaves GPS time sync off.
run_with_spinner "Switching to chrony for time sync..." bash -c "
    sudo systemctl disable --now systemd-timesyncd --quiet 2>/dev/null;
    sudo systemctl enable chrony --quiet &&
    sudo systemctl restart chrony
"

# ── Ensure gpsd is running (required for the GPS setup step) ──
# gpsd's own postinst usually enables its socket-activated unit already,
# but making it explicit here matches how NetworkManager is handled below
# rather than relying on packaging defaults. This is just the default
# on-demand/USB-auto-detect mode; if the wizard's GPS step picks an
# explicit device (needed for a UART-wired GPS), services/gpsconfig.py
# switches gpsd over to always-running mode pointed at that device on the
# next boot (see scripts/apply-gps-config.sh).
run_with_spinner "Configuring gpsd..." bash -c "
    sudo systemctl enable gpsd.socket --quiet &&
    sudo systemctl start gpsd.socket
"
ok "Time sync and GPS configured"

# ── Create directories ────────────────────────
run_with_spinner "Creating application directories..." bash -c "
    sudo mkdir -p '$INSTALL_DIR' &&
    sudo chown -R '$USER:$USER' '$INSTALL_DIR'
"

# ── Clone or update repository ────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    run_with_spinner "Existing install found, updating..." git -C "$INSTALL_DIR" pull --quiet
else
    run_with_spinner "Downloading application..." git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi
ok "Application installed"

# ── Build Direwolf from source ────────────────
# Skips the rebuild on a repeat install if DIREWOLF_VERSION_MARKER already matches.
DIREWOLF_VERSION="1.8.1"
DIREWOLF_SRC_DIR="$INSTALL_DIR/direwolf-src"
DIREWOLF_VERSION_MARKER="$INSTALL_DIR/.direwolf_version"
if [ -x /usr/local/bin/direwolf ] && [ "$(cat "$DIREWOLF_VERSION_MARKER" 2>/dev/null)" = "$DIREWOLF_VERSION" ]; then
    ok "Direwolf $DIREWOLF_VERSION already built"
else
    run_with_spinner "Fetching Direwolf $DIREWOLF_VERSION source..." bash -c "
        if [ -d '$DIREWOLF_SRC_DIR/.git' ]; then
            git -C '$DIREWOLF_SRC_DIR' fetch --quiet --tags
        else
            git clone --quiet https://github.com/wb2osz/direwolf.git '$DIREWOLF_SRC_DIR'
        fi &&
        git -C '$DIREWOLF_SRC_DIR' checkout --quiet '$DIREWOLF_VERSION'
    "
    run_with_spinner "Building Direwolf $DIREWOLF_VERSION (several minutes on a Pi)..." bash -c "
        mkdir -p '$DIREWOLF_SRC_DIR/build' &&
        cd '$DIREWOLF_SRC_DIR/build' &&
        cmake -DCMAKE_BUILD_TYPE=Release .. &&
        make -j\"\$(nproc)\" &&
        sudo make install
    "
    echo "$DIREWOLF_VERSION" > "$DIREWOLF_VERSION_MARKER"
    ok "Direwolf $DIREWOLF_VERSION built and installed"
fi

# ── Enable SPI (required for the e-ink display) ──
run_with_spinner "Enabling SPI interface..." sudo raspi-config nonint do_spi 0
ok "SPI enabled (reboot required the first time this is enabled)"

# ── Ensure NetworkManager is running (required for the WiFi hotspot) ──
run_with_spinner "Configuring NetworkManager..." bash -c "
    sudo systemctl enable NetworkManager --quiet &&
    sudo systemctl start NetworkManager
"
ok "NetworkManager configured"

# ── Grant nmcli access for the app's hotspot management ──────
# The digipeater service runs as a normal user (see the systemd unit below),
# but creating/managing NetworkManager connections (e.g. the first-boot WiFi
# hotspot) requires root. Scoped narrowly to nmcli only, not blanket sudo.
NMCLI_PATH="$(command -v nmcli)"
SUDOERS_TMP="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $NMCLI_PATH" > "$SUDOERS_TMP"
if sudo visudo -c -f "$SUDOERS_TMP" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/digipeater-nmcli
    rm -f "$SUDOERS_TMP"
else
    rm -f "$SUDOERS_TMP"
    fail "Generated sudoers rule failed validation, aborting for safety"
fi

# ── Grant reboot access for the setup wizard's "Finish & Reboot" step ──
# Separate sudoers file from nmcli's above: one rule per binary, so each
# stays scoped to exactly what it needs and nothing more.
REBOOT_PATH="$(command -v reboot)"
SUDOERS_TMP2="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $REBOOT_PATH" > "$SUDOERS_TMP2"
if sudo visudo -c -f "$SUDOERS_TMP2" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP2" /etc/sudoers.d/digipeater-reboot
    rm -f "$SUDOERS_TMP2"
else
    rm -f "$SUDOERS_TMP2"
    fail "Generated sudoers rule failed validation, aborting for safety"
fi

# ── Grant access to the GPS config helper for the GPS setup step ──
# Root-only actions (gpsd/chrony config, timezone) live in this one script
# rather than being run ad hoc, scoped to exactly this path, same pattern
# as nmcli/reboot above, not blanket root access. Must be executable for
# sudo to run it directly.
chmod +x "$APP_DIR/scripts/apply-gps-config.sh"
GPSCONFIG_PATH="$APP_DIR/scripts/apply-gps-config.sh"
SUDOERS_TMP3="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $GPSCONFIG_PATH" > "$SUDOERS_TMP3"
if sudo visudo -c -f "$SUDOERS_TMP3" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP3" /etc/sudoers.d/digipeater-gpsconfig
    rm -f "$SUDOERS_TMP3"
else
    rm -f "$SUDOERS_TMP3"
    fail "Generated sudoers rule failed validation, aborting for safety"
fi

# ── Grant systemctl start/stop access for the dashboard's Direwolf control ──
# Scoped to exactly these two commands, not blanket systemctl access (which
# could stop/restart any unit, including this app's own service), following
# the same one-rule-per-purpose pattern as nmcli/reboot/gpsconfig above. Used
# both by the dashboard's manual toggle and by main.py's own boot sequence
# (see services/system.py), which starts or stops direwolf.service itself
# based on config.yaml rather than leaving it enabled at the systemd level.
SYSTEMCTL_PATH="$(command -v systemctl)"
SUDOERS_TMP4="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH start direwolf, $SYSTEMCTL_PATH stop direwolf" > "$SUDOERS_TMP4"
if sudo visudo -c -f "$SUDOERS_TMP4" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP4" /etc/sudoers.d/digipeater-direwolf-control
    rm -f "$SUDOERS_TMP4"
else
    rm -f "$SUDOERS_TMP4"
    fail "Generated sudoers rule failed validation, aborting for safety"
fi

# ── Grant access to the restart-policy helper for the Startup tab ──
# Writes direwolf.service's systemd drop-in override (Restart=/RestartSec=/
# StartLimitBurst=), same scoped-script pattern as GPSCONFIG_PATH above, not
# blanket systemd-unit-editing access. Used by main.py's own boot sequence
# and by /api/config/save whenever the Startup tab changes (see
# services/restart_policy.py), so the wizard's/config page's "restart
# automatically if it crashes" setting actually takes effect instead of the
# fixed Restart=on-failure/RestartSec=10 below being the only thing direwolf
# ever sees.
chmod +x "$APP_DIR/scripts/apply-direwolf-restart-policy.sh"
RESTARTPOLICY_PATH="$APP_DIR/scripts/apply-direwolf-restart-policy.sh"
SUDOERS_TMP5="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $RESTARTPOLICY_PATH" > "$SUDOERS_TMP5"
if sudo visudo -c -f "$SUDOERS_TMP5" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP5" /etc/sudoers.d/digipeater-restart-policy
    rm -f "$SUDOERS_TMP5"
else
    rm -f "$SUDOERS_TMP5"
    fail "Generated sudoers rule failed validation, aborting for safety"
fi

# ── Grant access to read Direwolf's journal (error-log modal + live packet tailing) ──
# A normal user isn't guaranteed read access to the systemd journal
# (depends on group membership/journald config), so this goes through
# sudo like everything else here. One wildcarded rule covers both real
# uses: the dashboard's error-log modal's one-shot fetch (see
# services/system.py's get_direwolf_logs) and services/packet_log.py's
# continuous `-f` follow-mode tail for heard-station/beacon tracking,
# still scoped to exactly the direwolf unit's own logs, never blanket
# journal access.
JOURNALCTL_PATH="$(command -v journalctl)"
SUDOERS_TMP6="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $JOURNALCTL_PATH -u direwolf *" > "$SUDOERS_TMP6"
if sudo visudo -c -f "$SUDOERS_TMP6" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP6" /etc/sudoers.d/digipeater-journalctl
    rm -f "$SUDOERS_TMP6"
else
    rm -f "$SUDOERS_TMP6"
    fail "Generated sudoers rule failed validation, aborting for safety"
fi
ok "Permissions configured"

# ── Python virtual environment ────────────────
# --system-site-packages so the venv can see the apt-installed RPi.GPIO/spidev
# (those build native extensions against the Pi's kernel headers; pip-installing
# them inside an isolated venv is unreliable, so apt is the source of truth).
run_with_spinner "Setting up Python environment..." bash -c "
    python3 -m venv '$VENV_DIR' --system-site-packages &&
    '$VENV_DIR/bin/pip' install --quiet --upgrade pip
"

# ── Install Python dependencies ───────────────
run_with_spinner "Installing Python packages..." "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "Python environment ready"

# ── Install go-pmtiles (offline map region downloads) ──────
# A single static binary, not available via apt, fetched directly from
# its latest GitHub release. services/tiles.py shells out to it to extract
# one region's worth of map data from Protomaps' hosted planet build, the
# legitimate way to get OSM map data for offline use. This replaced an
# earlier design that scraped individual raster tiles from a live tile
# server. OpenStreetMap's own tile usage policy is explicit that offline
# use and bulk/pre-emptive tile fetching aren't just discouraged, they're
# not permitted at all (operations.osmfoundation.org/policies/tiles/).
# Soft/non-fatal: the digipeater's actual RF/APRS function
# doesn't depend on this, so a flaky connection here shouldn't block the
# rest of setup: the Map caching wizard step just reports it's missing
# if this didn't succeed, same as any other missing optional dependency.
PMTILES_ARCH="$(uname -m)"
case "$PMTILES_ARCH" in
    aarch64|arm64) PMTILES_ARCH="arm64" ;;
    x86_64|amd64)  PMTILES_ARCH="x86_64" ;;
    *) PMTILES_ARCH="" ;;
esac
if [ -z "$PMTILES_ARCH" ]; then
    echo -e "${YELLOW}  ⚠ Unrecognised CPU architecture ($(uname -m)): skipping go-pmtiles, map caching won't work. Continuing.${NC}"
else
    run_with_spinner_soft "Installing go-pmtiles..." bash -c "
        PMTILES_URL=\$(curl -sL https://api.github.com/repos/protomaps/go-pmtiles/releases/latest | grep -o '\"browser_download_url\": *\"[^\"]*Linux_${PMTILES_ARCH}[^\"]*\"' | grep -o 'https://[^\"]*') &&
        [ -n \"\$PMTILES_URL\" ] &&
        mkdir -p '$APP_DIR/bin' &&
        curl -sL \"\$PMTILES_URL\" | tar -xz -C '$APP_DIR/bin' pmtiles &&
        chmod +x '$APP_DIR/bin/pmtiles'
    " || true
fi

# ── Install map basemap assets (fonts + sprites) ──────
# ~19MB uncompressed (~6MB download): the label fonts and icon sprites
# MapLibre needs to render the local map data, vendored from Protomaps'
# own hosted asset bundle the same way the go-pmtiles binary above is.
# Soft/non-fatal for the same reason: without these the wizard's map step
# just can't render (falls back to a plain message), it doesn't break the
# digipeater's actual RF/APRS function.
run_with_spinner_soft "Installing map basemap assets (fonts, icons)..." bash -c "
    mkdir -p '$APP_DIR/web/static/maplibre-assets' &&
    curl -sL https://codeload.github.com/protomaps/basemaps-assets/tar.gz/refs/heads/main | tar -xz -C '$APP_DIR/web/static/maplibre-assets' --strip-components=1 'basemaps-assets-main/fonts' 'basemaps-assets-main/sprites/v4'
" || true

# ── Pre-cache the whole world map (zoom 0-8) ──────
# Soft version of run_with_spinner: a coarse ~1GB whole-world PMTiles
# layer, so the wizard's Map caching step always has a real offline
# basemap to show and pick a region on, whether or not there's internet
# at setup time. Only runs if go-pmtiles installed successfully above
# (map caching just won't offer a picker at all otherwise, same as any
# other missing optional dependency).
if [ -x "$APP_DIR/bin/pmtiles" ]; then
    run_with_spinner_soft "Pre-caching world map (zoom 0-8, ~1GB)..." bash -c "cd '$APP_DIR' && '$VENV_DIR/bin/python' scripts/precache_world.py" || true
else
    info "Skipping world map pre-cache (go-pmtiles not installed); re-run scripts/precache_world.py later once it is."
fi
ok "Map data installed"

# ── Install systemd service ───────────────────
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=APRS Digipeater
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
# Binding port 80 needs root normally: grant just that one capability
# instead of running the whole service as root. Deliberately no
# CapabilityBoundingSet here: that directive caps the maximum capabilities
# of every child process too, including the sudo nmcli calls this service
# shells out to for hotspot management; restricting it broke sudo's own
# privilege escalation ("unable to change to root gid: Operation not
# permitted"), silently killing the hotspot feature.
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF

run_with_spinner "Installing systemd service..." bash -c "
    sudo systemctl daemon-reload &&
    sudo systemctl enable ${SERVICE_NAME} --quiet
"

# ── Install direwolf systemd service ──────────
# Not enabled here; main.py starts/stops it based on config.yaml. Restart=/RestartSec= are
# just install-time fallbacks, overridden by services/restart_policy.py's drop-in on every boot.
sudo tee /etc/systemd/system/direwolf.service > /dev/null <<EOF
[Unit]
Description=Direwolf (APRS soundcard TNC/digipeater)
After=network.target sound.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/local/bin/direwolf -c $APP_DIR/direwolf.conf -t 0
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

run_with_spinner "Installing direwolf systemd service..." sudo systemctl daemon-reload

# ── Install scheduled map auto-update ─────────
# Off by default (see scripts/auto_tile_update.py and config.yaml's
# map.auto_update, set from the Map caching wizard step). The timer runs
# every 15 minutes, well below any sane check-time granularity, rather
# than being pointed at the user's configured time directly: that way
# changing the time in the web UI later doesn't require regenerating or
# reloading any systemd unit; the script just reads config.yaml fresh each
# time and mostly no-ops (see its own docstring for the once-a-day marker
# file that keeps this cheap).
sudo tee /etc/systemd/system/${SERVICE_NAME}-tile-update.service > /dev/null <<EOF
[Unit]
Description=APRS Digipeater: scheduled map tile update check
After=network.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python scripts/auto_tile_update.py
StandardOutput=journal
StandardError=journal
EOF

sudo tee /etc/systemd/system/${SERVICE_NAME}-tile-update.timer > /dev/null <<EOF
[Unit]
Description=Run the APRS Digipeater map tile update check periodically

[Timer]
OnBootSec=10min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF

run_with_spinner "Installing map auto-update timer..." bash -c "
    sudo systemctl daemon-reload &&
    sudo systemctl enable --now ${SERVICE_NAME}-tile-update.timer --quiet
"
ok "Background services installed"

# ── WiFi country ───────────────────────────────
# Without this set, the WiFi radio is soft-blocked by rfkill and the hotspot
# can never come up. This bites anyone who left WiFi blank in Raspberry Pi Imager
# (e.g. ethernet-only setups). Only asked once; re-run raspi-config directly
# to change it later.
# Checked via rfkill directly, not `raspi-config nonint get_wifi_country`:
# that returns a non-empty sentinel ("00") even when no country is actually
# set, which made the old version of this check skip the prompt incorrectly.
if ! rfkill list wifi | grep -q "Soft blocked: yes"; then
    info "WiFi radio already unblocked, skipping."
else
    echo ""
    read -p "  WiFi country code not set (needed for the hotspot to work), enter a 2-letter code (e.g. NZ, US, GB): " wifi_country < /dev/tty
    wifi_country="$(echo "$wifi_country" | tr '[:lower:]' '[:upper:]')"
    if [[ "$wifi_country" =~ ^[A-Z]{2}$ ]]; then
        sudo raspi-config nonint do_wifi_country "$wifi_country"
        sudo rfkill unblock wifi
        ok "WiFi country set to $wifi_country"
    else
        echo -e "${YELLOW}  Skipped (invalid or blank); the WiFi hotspot won't work until this is set:${NC}"
        echo -e "${YELLOW}  sudo raspi-config nonint do_wifi_country XX && sudo rfkill unblock wifi${NC}"
    fi
fi

# ── Select e-ink display ──────────────────────
# Everything unattended is done by this point; this is the one thing that
# needs a human, so it's asked last, right alongside the reboot confirmation
# below. The display is needed during first boot, before any web-based config
# wizard exists to ask this question, so it's a fixed pre-boot choice, not
# something the wizard can ask instead. Read live from the driver registry
# rather than a hardcoded list, so this never goes stale as new display
# modules get added to display/waveshare/.
DISPLAY_CONFIG="$APP_DIR/display_config.json"
if [ -f "$DISPLAY_CONFIG" ]; then
    info "Display already configured ($(cat "$DISPLAY_CONFIG")), skipping."
    echo "  Delete $DISPLAY_CONFIG and re-run this script to change it."
else
    info "Detecting available e-ink display drivers..."
    mapfile -t MODEL_LINES < <(cd "$APP_DIR" && "$VENV_DIR/bin/python" -c '
from display.waveshare import MODELS
for k, v in MODELS.items():
    print(k + "|" + v["desc"])
')

    echo ""
    echo "  Which e-ink display is connected?"
    echo "    0) None (no display connected)"
    declare -A MODEL_KEYS
    i=1
    for line in "${MODEL_LINES[@]}"; do
        key="${line%%|*}"
        desc="${line#*|}"
        echo "    $i) $desc  [$key]"
        MODEL_KEYS[$i]="$key"
        i=$((i+1))
    done
    echo ""
    read -p "  Enter a number [0]: " disp_choice < /dev/tty
    disp_choice="${disp_choice:-0}"

    if [ "$disp_choice" = "0" ]; then
        DISPLAY_DRIVER="none"
        DISPLAY_MODEL=""
    else
        DISPLAY_DRIVER="waveshare"
        DISPLAY_MODEL="${MODEL_KEYS[$disp_choice]:-}"
        [ -n "$DISPLAY_MODEL" ] || fail "Invalid selection"
    fi

    echo "{\"driver\": \"$DISPLAY_DRIVER\", \"model\": \"$DISPLAY_MODEL\"}" > "$DISPLAY_CONFIG"
    ok "Display set to: ${DISPLAY_MODEL:-none}"
fi

# ── Done ──────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════╗"
echo "║        Installation Complete         ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo -e "${GREEN}The system will now reboot and start the tool automatically.${NC}"
echo -e "${GREEN}Watch the e-ink display for first-boot status, and look for the${NC}"
echo -e "${GREEN}'Digipeater' WiFi hotspot once it comes back up.${NC}"
echo ""
echo "Logs after reboot: journalctl -u ${SERVICE_NAME} -f"
echo "Re-run this script any time to pull the latest changes and redeploy."
echo ""
read -t 30 -p "Rebooting in 30 seconds: press Enter to reboot now, or Ctrl+C to cancel..." < /dev/tty || true
sudo reboot
