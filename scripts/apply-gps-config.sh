#!/bin/bash
# Applies the GPS device / system-time-sync settings from the setup wizard: root-only actions
# (gpsd, chrony, timezone), invoked via a sudoers NOPASSWD rule scoped to this script (see install.sh).
set -e

DEVICE="$1"      # a /dev/... path, or "none"
TIME_SYNC="$2"   # "on" or "off"
TIMEZONE="$3"    # an IANA zone name, or "" to leave the timezone alone

GPSD_DEFAULT=/etc/default/gpsd
CHRONY_GPS_CONF=/etc/chrony/conf.d/digipeater-gps.conf

if [ "$DEVICE" != "none" ] && ! [[ "$DEVICE" =~ ^/dev/[A-Za-z0-9_.-]+$ ]]; then
    echo "Refusing suspicious device path: $DEVICE" >&2
    exit 1
fi
if [ -n "$TIMEZONE" ] && ! [[ "$TIMEZONE" =~ ^[A-Za-z0-9_+/-]+$ ]]; then
    echo "Refusing suspicious timezone: $TIMEZONE" >&2
    exit 1
fi

# ── gpsd device ──
# gpsd.socket (on-demand, auto-detect) and gpsd.service (always running, explicit device) are
# alternate activation paths for the same daemon; switch between them based on the wizard's pick.
if [ "$DEVICE" != "none" ]; then
    if grep -q "^DEVICES=" "$GPSD_DEFAULT" 2>/dev/null; then
        sed -i -E "s#^DEVICES=.*#DEVICES=\"$DEVICE\"#" "$GPSD_DEFAULT"
    else
        echo "DEVICES=\"$DEVICE\"" >> "$GPSD_DEFAULT"
    fi
    # -n: start reading immediately at boot rather than waiting for a client -- chrony's SHM
    # refclock below needs this to ever see data.
    if grep -q "^GPSD_OPTIONS=" "$GPSD_DEFAULT" 2>/dev/null; then
        sed -i -E 's#^GPSD_OPTIONS=.*#GPSD_OPTIONS="-n"#' "$GPSD_DEFAULT"
    else
        echo 'GPSD_OPTIONS="-n"' >> "$GPSD_DEFAULT"
    fi
    systemctl disable --now gpsd.socket --quiet 2>/dev/null || true
    sleep 1
    systemctl enable gpsd.service --quiet
    systemctl restart gpsd.service
else
    sed -i -E 's#^DEVICES=.*#DEVICES=""#' "$GPSD_DEFAULT" 2>/dev/null || true
    sed -i -E 's#^GPSD_OPTIONS=.*#GPSD_OPTIONS=""#' "$GPSD_DEFAULT" 2>/dev/null || true
    systemctl disable --now gpsd.service --quiet 2>/dev/null || true
    systemctl enable gpsd.socket --quiet
    systemctl restart gpsd.socket
fi

# ── Timezone ──
if [ -n "$TIMEZONE" ]; then
    timedatectl set-timezone "$TIMEZONE"
fi

# ── System time sync from GPS ──
# No PPS wiring (see PINOUT.md), so NMEA-over-SHM is only accurate to ~0.2-0.5s -- plenty for a
# digipeater's own clock, and the only time source at all for a station deployed with no internet.
if [ "$TIME_SYNC" = "on" ] && [ "$DEVICE" != "none" ]; then
    cat > "$CHRONY_GPS_CONF" <<EOF
# Written by the digipeater setup wizard: GPS time sync enabled.
refclock SHM 0 refid GPS precision 1e-1 offset 0.0 delay 0.2
EOF
else
    rm -f "$CHRONY_GPS_CONF"
fi
systemctl restart chrony
