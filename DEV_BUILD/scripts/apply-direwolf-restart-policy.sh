#!/bin/bash
# Applies the Startup tab's "restart automatically if it crashes" policy
# (config.yaml's startup.autorestart/restart_attempts/restart_delay_s) to
# direwolf.service via a systemd drop-in override, rather than the fixed
# Restart=on-failure/RestartSec=10 install.sh bakes into the unit file at
# install time: that never read these three settings at all, and had no
# StartLimitBurst, so a crash loop just retried forever instead of stopping
# after the configured number of attempts (systemd's own default burst
# window is short enough that a ~15s+ gap between attempts never trips it).
# A drop-in means a later change on the Startup tab (wizard or config.html,
# post-setup) takes effect without re-running the installer.
# Root-only (writing under /etc/systemd/system/, daemon-reload), invoked via
# a sudoers NOPASSWD rule scoped to exactly this script path (see
# install.sh), same pattern as apply-gps-config.sh.
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
    # StartLimitBurst counts every start, the initial one plus each
    # auto-restart, so this many total attempts matches "ATTEMPTS" the way
    # the Startup tab describes it. StartLimitIntervalSec has to cover the
    # whole attempt window (all of them DELAY_S apart) or the counter
    # window slides past before the last attempt and it just retries
    # forever again; +5s per attempt is slack for direwolf's own
    # startup-to-failure time, not exact, just enough to not undercount.
    INTERVAL=$(( ATTEMPTS * (DELAY_S + 5) ))
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
