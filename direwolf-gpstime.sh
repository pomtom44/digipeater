#!/bin/bash
LOGFILE="/var/log/direwolf/direwolf.log"
GPS_TIME_FILE="/tmp/direwolf_gpstime.txt"

echo "Waiting for GPS fix..." | tee -a "$LOGFILE"

last_gpstime=""

# Poll GPS for a valid fix (non-blocking)
while true; do
    # Get the latest TPV, read multiple messages to ensure we get one
    gps_raw=$(timeout 5 gpspipe -w -n 10 2>/dev/null)
    gpstime=$(echo "$gps_raw" | jq -r 'select(.class=="TPV" and .time != null) | .time' | head -n1)

    if [ -n "$gpstime" ]; then
        last_gpstime="$gpstime"
        echo "$gpstime" > "$GPS_TIME_FILE"
        echo "GPS fix acquired: $gpstime" | tee -a "$LOGFILE"
        break
    fi

    sleep 1
done

# Background process to update GPS time periodically (every 2 seconds)
(
    while true; do
        gps_raw=$(timeout 3 gpspipe -w -n 10 2>/dev/null)
        gpstime=$(echo "$gps_raw" | jq -r 'select(.class=="TPV" and .time != null) | .time' | head -n1)
        if [ -n "$gpstime" ]; then
            last_gpstime="$gpstime"
            echo "$gpstime" > "$GPS_TIME_FILE"
        fi
        sleep 2
    done
) &
GPS_UPDATE_PID=$!

# Cleanup function
cleanup() {
    kill $GPS_UPDATE_PID 2>/dev/null
    exit
}
trap cleanup EXIT INT TERM

# Now start Direwolf
/usr/local/bin/direwolf -c /etc/direwolf.conf 2>&1 | while IFS= read -r line
do
    # Read the most recent GPS time from file (non-blocking, fast)
    if [ -f "$GPS_TIME_FILE" ]; then
        last_gpstime=$(cat "$GPS_TIME_FILE" 2>/dev/null)
    fi
    
    # Use the GPS time if available, otherwise use empty (will be handled by parser)
    if [ -n "$last_gpstime" ]; then
        echo "[$last_gpstime] $line" >> "$LOGFILE"
    else
        echo "[$line" >> "$LOGFILE"
    fi
done
