#!/bin/bash
set -e

# ─────────────────────────────────────────────
# APRS Digipeater: Reset Script
# Full uninstall, reverses everything install.sh sets up, back to a clean state.
# ─────────────────────────────────────────────

INSTALL_DIR="/opt/digipeater"
SERVICE_NAME="digipeater"
VAR_DIR="/var/digipeater"
DIREWOLF_BIN="/usr/local/bin/direwolf"

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
echo "║      APRS Digipeater: Reset          ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Check running as correct user ────────────
if [ "$EUID" -eq 0 ]; then
    fail "Do not run this script as root. Run as your normal user (e.g. pi). sudo will be used where needed."
fi

echo -e "${YELLOW}This will permanently remove:${NC}"
echo "    - the digipeater systemd service"
echo "    - $INSTALL_DIR (application, venv, config.yaml, saved WiFi credentials, Direwolf source build)"
echo "    - $VAR_DIR (tile cache, packet history)"
echo "    - $DIREWOLF_BIN (Direwolf, built from source by install.sh)"
echo "    - /etc/sudoers.d/digipeater-* (all sudo permissions this app granted)"
echo "    - the digipeater-hotspot NetworkManager connection profile"
echo "    - the SPI interface (disabled again)"
echo "    - the WiFi country setting (radio re-blocked, same as before install)"
echo "    - system packages: gpsd, gpsd-clients, chrony,"
echo "      python3-rpi.gpio, python3-spidev, fonts-dejavu-core, python3-pip,"
echo "      python3-venv, git"
echo "    - chrony as the time-sync service (systemd-timesyncd re-enabled)"
echo ""
echo -e "${YELLOW}Deliberately NOT touched (real risk of bricking the Pi or losing SSH access):${NC}"
echo "    - python3 itself: a dependency root for much of the base OS, purging"
echo "      it can cascade into removing core system tooling, needing a reflash"
echo "    - NetworkManager: Bookworm's actual network stack, disabling it would"
echo "      very likely cut off SSH access to the Pi entirely"
echo "    - build tools (build-essential, cmake, lib*-dev): generically useful, not project-specific"
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
    info "No systemd service found, skipping"
fi

# ── Turn off GPIO outputs (radio power relay, e-ink) ─
# Must run before python3-rpi.gpio is purged and before $INSTALL_DIR (holds config.yaml) is removed.
# Without this, a relay left HIGH keeps the radio powered after reset.
info "Turning off GPIO outputs (radio power relay, e-ink)..."
GPIO_PY="$VENV_DIR/bin/python"
[ -x "$GPIO_PY" ] || GPIO_PY="$(command -v python3 || true)"
if [ -n "$GPIO_PY" ]; then
    "$GPIO_PY" - "$INSTALL_DIR/config.yaml" <<'PYEOF' 2>/dev/null || true
import sys
try:
    import RPi.GPIO as GPIO
except ImportError:
    sys.exit(0)

relay_pin, rst_pin, dc_pin, cs_pin, busy_pin = 27, 17, 25, 8, 24
config_path = sys.argv[1] if len(sys.argv) > 1 else None
if config_path:
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        gpio_cfg = cfg.get("gpio", {}) or {}
        relay_pin = gpio_cfg.get("relay_pin", relay_pin)
        rst_pin = gpio_cfg.get("eink_rst", rst_pin)
        dc_pin = gpio_cfg.get("eink_dc", dc_pin)
        cs_pin = gpio_cfg.get("eink_cs", cs_pin)
        busy_pin = gpio_cfg.get("eink_busy", busy_pin)
    except Exception:
        pass

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
# Relay pin: drive LOW and leave it driven, do NOT cleanup() it -- cleanup() floats the pin to an
# input, and a floating trigger input re-energizes some relay boards. Register state stays latched
# after this process exits even without cleanup(), same reasoning as services/relay.py's own pattern.
GPIO.setup(relay_pin, GPIO.OUT, initial=GPIO.LOW)
GPIO.output(relay_pin, GPIO.LOW)
GPIO.cleanup([rst_pin, dc_pin, cs_pin, busy_pin])
PYEOF
    ok "GPIO outputs turned off"
else
    info "No Python with RPi.GPIO found, skipping GPIO cleanup"
fi

# ── Remove application directory ─────────────
if [ -d "$INSTALL_DIR" ]; then
    sudo rm -rf "$INSTALL_DIR"
    ok "Removed $INSTALL_DIR"
else
    info "$INSTALL_DIR not present, skipping"
fi

# ── Remove runtime data directory ────────────
if [ -d "$VAR_DIR" ]; then
    sudo rm -rf "$VAR_DIR"
    ok "Removed $VAR_DIR"
else
    info "$VAR_DIR not present, skipping"
fi

# ── Remove Direwolf binary (built from source by install.sh) ─
if [ -x "$DIREWOLF_BIN" ]; then
    sudo rm -f "$DIREWOLF_BIN"
    ok "Removed $DIREWOLF_BIN"
else
    info "$DIREWOLF_BIN not present, skipping"
fi

# ── Remove sudoers rules ──────────────────────
if compgen -G "/etc/sudoers.d/digipeater-*" > /dev/null; then
    sudo rm -f /etc/sudoers.d/digipeater-*
    ok "Removed digipeater sudoers rules"
else
    info "No digipeater sudoers rules present, skipping"
fi

# ── Remove hotspot NetworkManager connection profile ─
# Created by services/network.py's setup_hotspot, stored outside every other path cleaned up above.
if sudo nmcli -t -f NAME connection show 2>/dev/null | grep -qx "digipeater-hotspot"; then
    sudo nmcli connection delete digipeater-hotspot
    ok "Removed digipeater-hotspot connection profile"
else
    info "digipeater-hotspot connection profile not present, skipping"
fi

# ── Disable SPI ───────────────────────────────
info "Disabling SPI interface..."
sudo raspi-config nonint do_spi 1
ok "SPI disabled"

# ── Re-block WiFi radio ───────────────────────
# Restores the soft-blocked state install.sh's WiFi-country step lifted; scoped to WiFi, leaving ethernet untouched.
info "Re-blocking WiFi radio..."
sudo rfkill block wifi
ok "WiFi radio re-blocked"

# ── Restore systemd-timesyncd as the time-sync service ─
# Reverses install.sh's switch to chrony (needed for GPS time sync).
info "Restoring systemd-timesyncd..."
sudo systemctl disable --now chrony --quiet 2>/dev/null || true
sudo systemctl enable --now systemd-timesyncd --quiet 2>/dev/null || true
ok "systemd-timesyncd restored"

# ── Remove system packages ───────────────────
# python3, network-manager, and curl are deliberately excluded, curl is needed to re-run install.sh itself.
info "Removing system packages..."
sudo apt-get purge -y -qq \
    gpsd \
    gpsd-clients \
    chrony \
    python3-rpi.gpio \
    python3-spidev \
    fonts-dejavu-core \
    python3-pip \
    python3-venv \
    git \
    2>/dev/null || true
sudo apt-get autoremove -y -qq
ok "System packages removed"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║           Reset Complete             ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo -e "${GREEN}You can now run install.sh for a fresh install.${NC}"
echo ""
