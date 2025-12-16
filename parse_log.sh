#!/bin/bash
#
# Script: Parse Dire Wolf Log
# Created by: 
# Created Date: 
# Modified By:
# Modified Date:
# Description: Shell script wrapper for parse_log.py, can be used with cron
#

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Set up logging
LOG_FILE="${SCRIPT_DIR}/parse_log.log"
ERROR_LOG="${SCRIPT_DIR}/parse_log_error.log"

# Log function
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$LOG_FILE"
}

log_error() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): ERROR: $1" >> "$ERROR_LOG"
    log_message "ERROR: $1"
}

# Find python3 - try common locations
if command -v python3 >/dev/null 2>&1; then
    PYTHON3=$(command -v python3)
elif [ -f /usr/bin/python3 ]; then
    PYTHON3=/usr/bin/python3
elif [ -f /usr/local/bin/python3 ]; then
    PYTHON3=/usr/local/bin/python3
else
    log_error "python3 not found in PATH or common locations"
    exit 1
fi

# Default log file location (adjust as needed)
DIREWOLF_LOG="${1:-/var/log/direwolf/direwolf.log}"

# Check if log file exists
if [ ! -f "$DIREWOLF_LOG" ]; then
    log_error "Dire Wolf log file not found: $DIREWOLF_LOG"
    exit 1
fi

# Check if log file is readable
if [ ! -r "$DIREWOLF_LOG" ]; then
    log_error "Dire Wolf log file is not readable: $DIREWOLF_LOG"
    exit 1
fi

# Run the parser (output only goes to log files, no console messages)
if "$PYTHON3" parse_log.py "$DIREWOLF_LOG" >> "$LOG_FILE" 2>> "$ERROR_LOG"; then
    exit 0
else
    log_error "Parser failed with exit code $?"
    exit 1
fi

