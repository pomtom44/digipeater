#!/bin/bash
#
# Script: Reset All Data
# Created by: 
# Created Date: 
# Modified By:
# Modified Date:
# Description: Clears database, parser logs, and direwolf logs
#

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Determine the working directory
# If script is in aprs-dashboard, use that. Otherwise, try to find aprs-dashboard
if [[ "$SCRIPT_DIR" == *"aprs-dashboard"* ]]; then
    WORK_DIR="$SCRIPT_DIR"
else
    # Try common locations
    if [ -d "/home/administrator/aprs-dashboard" ]; then
        WORK_DIR="/home/administrator/aprs-dashboard"
    elif [ -d "$HOME/aprs-dashboard" ]; then
        WORK_DIR="$HOME/aprs-dashboard"
    else
        # Fall back to script directory
        WORK_DIR="$SCRIPT_DIR"
    fi
fi

cd "$WORK_DIR"

# Configuration
DATA_FILE="${WORK_DIR}/digipeater_data.json"
STATUS_FILE="${WORK_DIR}/digipeater_status.json"
RESET_TIMESTAMP_FILE="${WORK_DIR}/reset_timestamp.json"
LAST_LOG_READ_FILE="${WORK_DIR}/last_log_read_timestamp.json"
PARSER_LOG_FILE="${WORK_DIR}/parse_log.log"
PARSER_ERROR_LOG="${WORK_DIR}/parse_log_error.log"
PARSER_DAEMON_LOG="${WORK_DIR}/parse_log_daemon.log"
DIREWOLF_LOG="/var/log/direwolf/direwolf.log"

echo "Working directory: $WORK_DIR"

# Function to get current GPS time
get_gps_time() {
    gps_raw=$(timeout 5 gpspipe -w -n 10 2>/dev/null)
    gpstime=$(echo "$gps_raw" | jq -r 'select(.class=="TPV" and .time != null) | .time' | head -n1)
    if [ -n "$gpstime" ]; then
        echo "$gpstime"
        return 0
    fi
    return 1
}

# Function to convert GPS time to Unix timestamp
gps_time_to_timestamp() {
    local gps_time_str="$1"
    python3 << EOF
from datetime import datetime, timezone
import sys
try:
    gps_time = "$gps_time_str"
    if gps_time.endswith('Z'):
        gps_time = gps_time.replace('Z', '+00:00')
    dt = datetime.fromisoformat(gps_time)
    print(int(dt.timestamp()))
except Exception as e:
    print(0)
    sys.exit(1)
EOF
}

echo "=========================================="
echo "Reset All Data Script"
echo "=========================================="
echo ""

# Confirm action
read -p "This will clear ALL data. Are you sure? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Reset cancelled."
    exit 0
fi

echo ""
echo "A) Clearing database files..."

# Clear database
if [ -f "$DATA_FILE" ]; then
    rm -f "$DATA_FILE"
    echo "  - Removed: $DATA_FILE"
fi

# Get current GPS time for reset timestamp
echo ""
echo "B) Getting current GPS time for reset timestamp..."
GPS_TIME=$(get_gps_time)
if [ -n "$GPS_TIME" ]; then
    GPS_TIMESTAMP=$(gps_time_to_timestamp "$GPS_TIME")
    if [ "$GPS_TIMESTAMP" != "0" ]; then
        # Save reset timestamp
        echo "{\"reset_timestamp\": $GPS_TIMESTAMP}" > "$RESET_TIMESTAMP_FILE"
        echo "  - Reset timestamp saved: $GPS_TIME"
    else
        echo "  - Warning: Could not convert GPS time to timestamp"
    fi
else
    echo "  - Warning: Could not get GPS time, using current system time"
    GPS_TIMESTAMP=$(date +%s)
    echo "{\"reset_timestamp\": $GPS_TIMESTAMP}" > "$RESET_TIMESTAMP_FILE"
fi

# Clear last log read timestamp
if [ -f "$LAST_LOG_READ_FILE" ]; then
    rm -f "$LAST_LOG_READ_FILE"
    echo "  - Removed: $LAST_LOG_READ_FILE"
fi

# Clear status file (or reset gps_time)
if [ -f "$STATUS_FILE" ]; then
    # Keep status but reset gps_time
    python3 << EOF
import json
import os
from datetime import datetime, timezone

status_file = "$STATUS_FILE"
if os.path.exists(status_file):
    with open(status_file, 'r') as f:
        status = json.load(f)
    
    # Reset gps_time to None
    status['gps_time'] = None
    status['last_update'] = None
    
    with open(status_file, 'w') as f:
        json.dump(status, f, indent=2)
    print("  - Reset GPS time in status file")
EOF
fi

echo ""
echo "C) Clearing parser logs..."

# Clear parser logs
if [ -f "$PARSER_LOG_FILE" ]; then
    rm -f "$PARSER_LOG_FILE"
    echo "  - Removed: $PARSER_LOG_FILE"
fi

if [ -f "$PARSER_ERROR_LOG" ]; then
    rm -f "$PARSER_ERROR_LOG"
    echo "  - Removed: $PARSER_ERROR_LOG"
fi

if [ -f "$PARSER_DAEMON_LOG" ]; then
    rm -f "$PARSER_DAEMON_LOG"
    echo "  - Removed: $PARSER_DAEMON_LOG"
fi

echo ""
echo "D) Clearing direwolf log..."

# Clear direwolf log (requires appropriate permissions)
if [ -f "$DIREWOLF_LOG" ]; then
    if [ -w "$DIREWOLF_LOG" ]; then
        > "$DIREWOLF_LOG"
        echo "  - Cleared: $DIREWOLF_LOG"
    else
        echo "  - Warning: Cannot write to $DIREWOLF_LOG (may need sudo)"
        echo "  - Attempting with sudo..."
        if sudo sh -c "> $DIREWOLF_LOG"; then
            echo "  - Cleared: $DIREWOLF_LOG (with sudo)"
        else
            echo "  - Error: Could not clear direwolf log (permission denied)"
        fi
    fi
else
    echo "  - Direwolf log not found: $DIREWOLF_LOG"
fi

echo ""
echo "=========================================="
echo "Reset complete!"
echo "=========================================="
echo ""
echo "All data has been cleared:"
echo "  - Database cleared"
echo "  - Parser logs cleared"
echo "  - Direwolf log cleared"
echo "  - Reset timestamp set to current GPS time"
echo ""

