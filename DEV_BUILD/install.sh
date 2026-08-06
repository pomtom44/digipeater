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
PORT=8080

# ── Colours ──────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
info() { echo -e "${YELLOW}  → $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

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
info "Checking system..."
if ! grep -qi "bookworm" /etc/os-release 2>/dev/null; then
    echo -e "${YELLOW}  Warning: This script is tested on Raspberry Pi OS Bookworm.${NC}"
    echo -e "${YELLOW}  Other versions may work but are not guaranteed.${NC}"
    read -p "  Continue anyway? [y/N] " confirm < /dev/tty
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi
ok "OS check passed"

# ── System update ─────────────────────────────
info "Updating package lists..."
sudo apt-get update -qq
ok "Package lists updated"

# ── Install system packages ───────────────────
# More packages get added here as later parts (direwolf, GPS, etc.) come online.
info "Installing system packages..."
sudo apt-get install -y -qq \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-rpi.gpio \
    python3-spidev \
    curl
ok "System packages installed"

# ── Enable SPI (required for the e-ink display) ──
info "Enabling SPI interface..."
sudo raspi-config nonint do_spi 0
ok "SPI enabled (reboot required the first time this is enabled)"

# ── Ensure NetworkManager is running (required for the WiFi hotspot) ──
info "Configuring NetworkManager..."
sudo systemctl enable NetworkManager --quiet
sudo systemctl start NetworkManager
ok "NetworkManager configured"

# ── Create directories ────────────────────────
info "Creating application directories..."
sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$USER:$USER" "$INSTALL_DIR"
ok "Directories created"

# ── Clone or update repository ────────────────
info "Downloading application..."
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Existing install found — updating..."
    git -C "$INSTALL_DIR" pull --quiet
    ok "Application updated"
else
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    ok "Application downloaded"
fi

# ── Python virtual environment ────────────────
# --system-site-packages so the venv can see the apt-installed RPi.GPIO/spidev
# (those build native extensions against the Pi's kernel headers — pip-installing
# them inside an isolated venv is unreliable, so apt is the source of truth).
info "Setting up Python environment..."
python3 -m venv "$VENV_DIR" --system-site-packages
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
ok "Virtual environment created"

# ── Install Python dependencies ───────────────
info "Installing Python packages..."
"$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "Python packages installed"

# ── Install systemd service ───────────────────
info "Installing systemd service..."
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

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME} --quiet
ok "Systemd service installed and enabled — it will start automatically on boot"

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
