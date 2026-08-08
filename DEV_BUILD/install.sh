#!/bin/bash
set -e

# ─────────────────────────────────────────────
# APRS Digipeater — Install Script
# ─────────────────────────────────────────────

INSTALL_DIR="/opt/digipeater"
SERVICE_NAME="digipeater"
VENV_DIR="$INSTALL_DIR/venv"
REPO_URL="https://github.com/pomtom44/digipeater.git"
APP_DIR="$INSTALL_DIR/DEV_BUILD"

# ── Colours ──────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
info() { echo -e "${YELLOW}  → $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

# Runs a command with its output hidden behind a spinner, only showing that
# output if the command actually fails (e.g. apt-get's per-package unpacking
# noise, which -qq alone doesn't suppress since that's dpkg's own output).
run_with_spinner() {
    local msg="$1"; shift
    local logfile
    logfile=$(mktemp)
    "$@" > "$logfile" 2>&1 &
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
    if [ $status -ne 0 ]; then
        echo -e "${RED}  ✗ $msg failed:${NC}"
        cat "$logfile"
        rm -f "$logfile"
        exit 1
    fi
    rm -f "$logfile"
}

echo ""
echo "╔══════════════════════════════════════╗"
echo "║    APRS Digipeater — Installer       ║"
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
# backgrounds a sudo call — an interactive password prompt doesn't mix well
# with a backgrounded command. This also keeps the credential cached for the
# rest of the script (sudo's default timeout comfortably covers the install).
info "This installer needs sudo access..."
sudo -v
ok "Sudo access confirmed"

# ── System update ─────────────────────────────
run_with_spinner "Updating package lists..." sudo apt-get update -qq
ok "Package lists updated"

# ── Install system packages ───────────────────
# More packages get added here as later parts (direwolf, GPS, etc.) come online.
run_with_spinner "Installing system packages..." sudo apt-get install -y -qq \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-rpi.gpio \
    python3-spidev \
    fonts-dejavu-core \
    curl
ok "System packages installed"

# ── Create directories ────────────────────────
run_with_spinner "Creating application directories..." bash -c "
    sudo mkdir -p '$INSTALL_DIR' &&
    sudo chown -R '$USER:$USER' '$INSTALL_DIR'
"
ok "Directories created"

# ── Clone or update repository ────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    run_with_spinner "Existing install found — updating..." git -C "$INSTALL_DIR" pull --quiet
    ok "Application updated"
else
    run_with_spinner "Downloading application..." git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    ok "Application downloaded"
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
# hotspot) requires root. Scoped narrowly to nmcli only — not blanket sudo.
NMCLI_PATH="$(command -v nmcli)"
SUDOERS_TMP="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $NMCLI_PATH" > "$SUDOERS_TMP"
if sudo visudo -c -f "$SUDOERS_TMP" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/digipeater-nmcli
    rm -f "$SUDOERS_TMP"
    ok "nmcli permissions configured"
else
    rm -f "$SUDOERS_TMP"
    fail "Generated sudoers rule failed validation — aborting for safety"
fi

# ── Grant reboot access for the setup wizard's "Finish & Reboot" step ──
# Separate sudoers file from nmcli's above — one rule per binary, so each
# stays scoped to exactly what it needs and nothing more.
REBOOT_PATH="$(command -v reboot)"
SUDOERS_TMP2="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: $REBOOT_PATH" > "$SUDOERS_TMP2"
if sudo visudo -c -f "$SUDOERS_TMP2" > /dev/null 2>&1; then
    sudo install -o root -g root -m 0440 "$SUDOERS_TMP2" /etc/sudoers.d/digipeater-reboot
    rm -f "$SUDOERS_TMP2"
    ok "reboot permissions configured"
else
    rm -f "$SUDOERS_TMP2"
    fail "Generated sudoers rule failed validation — aborting for safety"
fi

# ── Python virtual environment ────────────────
# --system-site-packages so the venv can see the apt-installed RPi.GPIO/spidev
# (those build native extensions against the Pi's kernel headers — pip-installing
# them inside an isolated venv is unreliable, so apt is the source of truth).
run_with_spinner "Setting up Python environment..." bash -c "
    python3 -m venv '$VENV_DIR' --system-site-packages &&
    '$VENV_DIR/bin/pip' install --quiet --upgrade pip
"
ok "Virtual environment created"

# ── Install Python dependencies ───────────────
run_with_spinner "Installing Python packages..." "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "Python packages installed"

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
# Binding port 80 needs root normally — grant just that one capability
# instead of running the whole service as root. Deliberately no
# CapabilityBoundingSet here: that directive caps the maximum capabilities
# of every child process too, including the `sudo nmcli` calls this service
# shells out to for hotspot management — restricting it broke sudo's own
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
ok "Systemd service installed and enabled — it will start automatically on boot"

# ── WiFi country ───────────────────────────────
# Without this set, the WiFi radio is soft-blocked by rfkill and the hotspot
# can never come up — bites anyone who left WiFi blank in Raspberry Pi Imager
# (e.g. ethernet-only setups). Only asked once; re-run raspi-config directly
# to change it later.
# Checked via rfkill directly, not `raspi-config nonint get_wifi_country` —
# that returns a non-empty sentinel ("00") even when no country is actually
# set, which made the old version of this check skip the prompt incorrectly.
if ! rfkill list wifi | grep -q "Soft blocked: yes"; then
    info "WiFi radio already unblocked — skipping."
else
    echo ""
    read -p "  WiFi country code not set (needed for the hotspot to work) — enter a 2-letter code (e.g. NZ, US, GB): " wifi_country < /dev/tty
    wifi_country="$(echo "$wifi_country" | tr '[:lower:]' '[:upper:]')"
    if [[ "$wifi_country" =~ ^[A-Z]{2}$ ]]; then
        sudo raspi-config nonint do_wifi_country "$wifi_country"
        sudo rfkill unblock wifi
        ok "WiFi country set to $wifi_country"
    else
        echo -e "${YELLOW}  Skipped (invalid or blank) — the WiFi hotspot won't work until this is set:${NC}"
        echo -e "${YELLOW}  sudo raspi-config nonint do_wifi_country XX && sudo rfkill unblock wifi${NC}"
    fi
fi

# ── Select e-ink display ──────────────────────
# Everything unattended is done by this point — this is the one thing that
# needs a human, so it's asked last, right alongside the reboot confirmation
# below. The display is needed during first boot, before any web-based config
# wizard exists to ask this question, so it's a fixed pre-boot choice, not
# something the wizard can ask instead. Read live from the driver registry
# rather than a hardcoded list, so this never goes stale as new display
# modules get added to display/waveshare/.
DISPLAY_CONFIG="$APP_DIR/display_config.json"
if [ -f "$DISPLAY_CONFIG" ]; then
    info "Display already configured ($(cat "$DISPLAY_CONFIG")) — skipping."
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
    echo "    0) None — no display connected"
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
read -t 30 -p "Rebooting in 30 seconds — press Enter to reboot now, or Ctrl+C to cancel..." < /dev/tty || true
sudo reboot
