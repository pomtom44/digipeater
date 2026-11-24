#!/bin/bash
# Applies the Startup tab's restart-on-crash policy to direwolf.service via a systemd drop-in.
# Root-only, invoked via a sudoers NOPASSWD rule scoped to this script path (see install.sh).
set -e

AUTORESTART="$1"   # "on" or "off"
ATTEMPTS="$2"       # positive integer, total start attempts (initial + retries)
DELAY_S="$3"        # positive integer, seconds between attempts

if [ "$AUTORESTART" != "on" ] && [ "$AUTORESTART" != "off" ]; then
    echo "Invalid autorestart value: $AUTORESTART" >&2
    exit 1
fi
if ! [[ "$ATTEMPTS" =~ ^[0-9]+$ ]] || [ "$ATTEMPTS" -lt 1 ]; then
    echo "Invalid attempts value: $ATTEMPTS" >&2
    exit 1
fi
if ! [[ "$DELAY_S" =~ ^[0-9]+$ ]] || [ "$DELAY_S" -lt 1 ]; then
    echo "Invalid delay value: $DELAY_S" >&2
    exit 1
fi

DROPIN_DIR=/etc/systemd/system/direwolf.service.d
mkdir -p "$DROPIN_DIR"

if [ "$AUTORESTART" = "on" ]; then
    # StartLimitIntervalSec (sliding window) must outlast accumulating ATTEMPTS starts, or the burst
    # count never climbs enough to stop retrying; +1 attempt/+10s is slack -- a tighter formula let a real crash loop run 8+ restarts deep before stopping.
    INTERVAL=$(( (ATTEMPTS + 1) * (DELAY_S + 10) ))
    cat > "$DROPIN_DIR/override.conf" <<EOF
[Unit]
StartLimitIntervalSec=$INTERVAL
StartLimitBurst=$ATTEMPTS

[Service]
Restart=on-failure
RestartSec=$DELAY_S
EOF
else
    cat > "$DROPIN_DIR/override.conf" <<EOF
[Service]
Restart=no
EOF
fi

systemctl daemon-reload
