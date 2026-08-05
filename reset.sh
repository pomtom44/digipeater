#!/bin/bash
set -e

# ─────────────────────────────────────────────
# APRS Digipeater — Reset Script
# Removes everything install.sh sets up so a
# fresh install can be run from a clean state.
# ─────────────────────────────────────────────

INSTALL_DIR="/opt/digipeater"
SERVICE_NAME="digipeater"
VAR_DIR="/var/digipeater"
DIREWOLF_CONF_DIR="/etc/direwolf"

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
echo "║      APRS Digipeater — Reset         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Check running as correct user ────────────
if [ "$EUID" -eq 0 ]; then
    fail "Do not run this script as root. Run as your normal user (e.g. pi). sudo will be used where needed."
fi

echo -e "${YELLOW}This will permanently remove:${NC}"
echo "    - the digipeater systemd service"
echo "    - $INSTALL_DIR (application, venv, config.yaml)"
echo "    - $VAR_DIR (tile cache, packet history)"
echo "    - $DIREWOLF_CONF_DIR (generated direwolf.conf)"
echo ""
read -p "  Continue? [y/N] " confirm < /dev/tty
[[ "$confirm" =~ ^[Yy]$ ]] || exit 1
echo ""

# ── Stop and remove systemd service ──────────
if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
    info "Stopping and removing systemd service..."
    sudo systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    sudo systemctl disable "${SERVICE_NAME}" --quiet 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo systemctl daemon-reload
    ok "Service removed"
else
    info "No systemd service found — skipping"
fi

# ── Remove application directory ─────────────
if [ -d "$INSTALL_DIR" ]; then
    sudo rm -rf "$INSTALL_DIR"
    ok "Removed $INSTALL_DIR"
else
    info "$INSTALL_DIR not present — skipping"
fi

# ── Remove runtime data directory ────────────
if [ -d "$VAR_DIR" ]; then
    sudo rm -rf "$VAR_DIR"
    ok "Removed $VAR_DIR"
else
    info "$VAR_DIR not present — skipping"
fi

# ── Remove direwolf config directory ─────────
if [ -d "$DIREWOLF_CONF_DIR" ]; then
    sudo rm -rf "$DIREWOLF_CONF_DIR"
    ok "Removed $DIREWOLF_CONF_DIR"
else
    info "$DIREWOLF_CONF_DIR not present — skipping"
fi

# ── Restore network interfaces backup ────────
if [ -f /etc/network/interfaces.bak ]; then
    sudo mv /etc/network/interfaces.bak /etc/network/interfaces
    ok "Restored /etc/network/interfaces"
fi

# ── Optionally remove installed system packages ─
echo ""
read -p "  Also remove system packages installed for the digipeater (direwolf, gpsd, libhamlib-utils, python3-rpi.gpio, python3-spidev)? [y/N] " purge < /dev/tty
if [[ "$purge" =~ ^[Yy]$ ]]; then
    info "Removing system packages..."
    sudo apt-get purge -y -qq \
        direwolf \
        gpsd \
        gpsd-clients \
        libhamlib-utils \
        python3-rpi.gpio \
        python3-spidev \
        2>/dev/null || true
    sudo apt-get autoremove -y -qq
    ok "System packages removed"
else
    info "Keeping system packages installed"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║           Reset Complete             ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo -e "${GREEN}You can now run install.sh for a fresh install.${NC}"
echo ""
