#!/bin/bash
set -e

# ─────────────────────────────────────────────
# APRS Digipeater — Install Script
# Tested on: Raspberry Pi OS Bookworm 64-bit Lite
# ─────────────────────────────────────────────

INSTALL_DIR="/opt/digipeater"
SERVICE_NAME="digipeater"
TILE_DIR="/var/digipeater/tiles"
VENV_DIR="$INSTALL_DIR/venv"
REPO_URL="https://github.com/pomtom44/digipeater.git"

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
info "Installing system packages..."
sudo apt-get install -y -qq \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-rpi.gpio \
    python3-spidev \
    direwolf \
    avahi-daemon \
    network-manager \
    gpsd \
    gpsd-clients \
    alsa-utils \
    libhamlib-utils \
    curl
ok "System packages installed"

# ── Enable SPI (required for Waveshare e-ink display) ─────────
info "Enabling SPI interface..."
sudo raspi-config nonint do_spi 0
ok "SPI enabled (reboot required to take effect)"

# ── Verify direwolf installed ─────────────────
if ! command -v direwolf &> /dev/null; then
    fail "direwolf was not installed correctly. Check apt output above."
fi
ok "Direwolf found at $(command -v direwolf)"

# ── Configure avahi (mDNS) ────────────────────
info "Configuring mDNS hostname (digipeater.local)..."
sudo hostnamectl set-hostname digipeater
# Ensure avahi is enabled and running
sudo systemctl enable avahi-daemon --quiet
sudo systemctl start avahi-daemon
ok "mDNS configured — device will be reachable at digipeater.local"

# ── Create directories ────────────────────────
info "Creating application directories..."
sudo mkdir -p "$INSTALL_DIR"
sudo mkdir -p "$TILE_DIR"
sudo chown -R "$USER:$USER" "$INSTALL_DIR"
sudo chown -R "$USER:$USER" /var/digipeater
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
info "Setting up Python environment..."
python3 -m venv "$VENV_DIR" --system-site-packages
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
ok "Virtual environment created"

# ── Install Python dependencies ───────────────
info "Installing Python packages..."
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
ok "Python packages installed"

# ── Create direwolf config directory ─────────
info "Setting up direwolf config directory..."
sudo mkdir -p /etc/direwolf
sudo chown "$USER:$USER" /etc/direwolf
ok "Direwolf config directory ready"

# ── Configure gpsd ───────────────────────────
info "Configuring gpsd..."
sudo systemctl stop gpsd 2>/dev/null || true
sudo systemctl disable gpsd 2>/dev/null || true
# gpsd is managed by the application directly via pyserial
ok "gpsd disabled (application handles GPS directly)"

# ── Set up NetworkManager for hotspot support ─
info "Configuring NetworkManager..."
sudo systemctl enable NetworkManager --quiet
sudo systemctl start NetworkManager
# Ensure NetworkManager manages all interfaces
if [ -f /etc/network/interfaces ]; then
    sudo mv /etc/network/interfaces /etc/network/interfaces.bak
    info "Backed up /etc/network/interfaces"
fi
ok "NetworkManager configured"

# ── Add user to required groups ───────────────
info "Configuring user permissions..."
sudo usermod -aG dialout "$USER"   # serial port access (GPS, TNC)
sudo usermod -aG audio "$USER"     # audio device access
sudo usermod -aG gpio "$USER"      # GPIO access (relay)
ok "User added to dialout, audio, gpio groups"

# ── Install systemd service ───────────────────
info "Installing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=APRS Digipeater
After=network.target avahi-daemon.service
Wants=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
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
ok "Systemd service installed and enabled"

# ── Copy example config if no config exists ───
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    info "Creating initial config from template..."
    cp "$INSTALL_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
    ok "config.yaml created from template"
else
    ok "Existing config.yaml found — not overwritten"
fi

# ── Done ──────────────────────────────────────
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo "╔══════════════════════════════════════╗"
echo "║        Installation Complete         ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo -e "${GREEN}The system will now reboot.${NC}"
echo -e "${GREEN}After reboot, open a browser and go to:${NC}"
echo ""
echo -e "    ${YELLOW}http://digipeater.local:8080${NC}"
if [ -n "$IP_ADDR" ]; then
    echo -e "    ${YELLOW}http://$IP_ADDR:8080${NC}"
fi
echo ""
echo -e "${YELLOW}Note: Group permission changes require the reboot to take effect.${NC}"
echo ""
read -p "Press Enter to reboot now, or Ctrl+C to cancel..." < /dev/tty
sudo reboot
