#!/bin/bash
# Applies the GPS device / system-time-sync settings collected by the setup
# wizard. Root-only actions (editing /etc/default/gpsd, chrony config,
# system timezone) that the app itself can't do as a normal user, invoked
# via a sudoers NOPASSWD rule scoped to exactly this script path
# (see install.sh), not blanket root access.
#
# Deliberately does NOT touch direwolf.conf or any APRS beacon position
# source: that's services/direwolf_config.py's job, called separately from
# main.py's own boot sequence. This script only makes gpsd/chrony/the
# system clock actually use the GPS.
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
# gpsd.socket (on-demand, USB auto-detect only, installed enabled by
# install.sh) and gpsd.service (always running, explicit device) are
# alternate activation paths for the same daemon and shouldn't both be
# enabled at once. Switch between them based on whether a device was
# actually picked in the wizard.
if [ "$DEVICE" != "none" ]; then
    if grep -q "^DEVICES=" "$GPSD_DEFAULT" 2>/dev/null; then
        sed -i -E "s#^DEVICES=.*#DEVICES=\"$DEVICE\"#" "$GPSD_DEFAULT"
    else
        echo "DEVICES=\"$DEVICE\"" >> "$GPSD_DEFAULT"
    fi
    # -n: start reading the device immediately at boot rather than waiting
    # for a client to connect first: needed for chrony's SHM refclock
    # below to ever see data, and keeps live GPS status always fresh.
    if grep -q "^GPSD_OPTIONS=" "$GPSD_DEFAULT" 2>/dev/null; then
        sed -i -E 's#^GPSD_OPTIONS=.*#GPSD_OPTIONS="-n"#' "$GPSD_DEFAULT"
    else
        echo 'GPSD_OPTIONS="-n"' >> "$GPSD_DEFAULT"
    fi
    systemctl disable --now gpsd.socket --quiet 2>/dev/null || true
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
# No PPS wiring in this project (see PINOUT.md), so NMEA-over-SHM time is
# only accurate to ~0.2-0.5s, plenty for a digipeater's own clock, not a
# precision reference. Still genuinely useful: it's the only time source
# available at all for a station deployed somewhere with no internet.
if [ "$TIME_SYNC" = "on" ] && [ "$DEVICE" != "none" ]; then
    cat > "$CHRONY_GPS_CONF" <<EOF
# Written by the digipeater setup wizard: GPS time sync enabled.
refclock SHM 0 refid GPS precision 1e-1 offset 0.0 delay 0.2
EOF
else
    rm -f "$CHRONY_GPS_CONF"
fi
systemctl restart chrony
