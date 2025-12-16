#!/bin/bash
#
# Script: Parse Dire Wolf Log Daemon
# Created by: 
# Created Date: 
# Modified By:
# Modified Date:
# Description: Runs parse_log.sh every 10 seconds continuously
#

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Set up logging
LOG_FILE="${SCRIPT_DIR}/parse_log_daemon.log"
PID_FILE="${SCRIPT_DIR}/parse_log_daemon.pid"

# Log function
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" | tee -a "$LOG_FILE"
}

# Default log file location (adjust as needed)
DIREWOLF_LOG="${1:-/var/log/direwolf/direwolf.log}"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        log_message "Daemon already running with PID $OLD_PID"
        exit 1
    else
        log_message "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Save PID
echo $$ > "$PID_FILE"
log_message "Starting parser daemon (PID: $$)"

# Trap signals for clean shutdown
trap "log_message 'Shutting down parser daemon'; rm -f '$PID_FILE'; exit 0" SIGTERM SIGINT

# Main loop
while true; do
    log_message "Running parser..."
    "$SCRIPT_DIR/parse_log.sh" "$DIREWOLF_LOG"
    
    # Sleep for 10 seconds
    sleep 10
done

