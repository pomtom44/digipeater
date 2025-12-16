#!/usr/bin/env python3
"""
Script: Parse Dire Wolf Log
Created by: 
Created Date: 
Modified By:
Modified Date:
Description: Parses Dire Wolf log files and extracts APRS packet data
"""

import re
import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Try to import aprslib for better parsing, but work without it
try:
    import aprslib
    HAS_APRSLIB = True
except ImportError:
    HAS_APRSLIB = False

# Default log file location
DEFAULT_LOG_FILE = "/var/log/direwolf/direwolf.log"
DATA_FILE = "digipeater_data.json"
STATUS_FILE = "digipeater_status.json"
RESET_TIMESTAMP_FILE = "reset_timestamp.json"
LAST_LOG_READ_FILE = "last_log_read_timestamp.json"

def parse_aprs_position(position_str):
    """
    Parse APRS position string like: !3748.60S/17517.80E
    Returns (latitude, longitude) or (None, None)
    """
    # Pattern: !DDMM.mmN/DDDMM.mmW or !DDMM.mmS/DDDMM.mmE
    pattern = r'!(\d{2})(\d{2}\.\d{2})([NS])/(\d{3})(\d{2}\.\d{2})([EW])'
    match = re.match(pattern, position_str)
    
    if not match:
        return None, None
    
    try:
        lat_deg = int(match.group(1))
        lat_min = float(match.group(2))
        lat_dir = match.group(3)
        
        lon_deg = int(match.group(4))
        lon_min = float(match.group(5))
        lon_dir = match.group(6)
        
        # Convert to decimal degrees
        latitude = lat_deg + (lat_min / 60.0)
        if lat_dir == 'S':
            latitude = -latitude
        
        longitude = lon_deg + (lon_min / 60.0)
        if lon_dir == 'W':
            longitude = -longitude
        
        return latitude, longitude
    except (ValueError, IndexError):
        return None, None

def parse_aprs_packet(line):
    """
    Parse a Dire Wolf log line containing an APRS packet
    Format: [timestamp] [channel] callsign>path:data
    """
    # Pattern to match log line with APRS packet
    # Example: [2025-12-11T01:26:35Z] [0L] ZL4ST-15>APDW18,WIDE1-1:!3748.60S/17517.80E`278/000ZL4ST Portable Digipeater
    pattern = r'\[([^\]]+)\]\s+\[([^\]]+)\]\s+([^>]+)>([^:]+):(.+)'
    match = re.match(pattern, line)
    
    if not match:
        return None
    
    try:
        timestamp_str = match.group(1)
        channel = match.group(2)
        source = match.group(3).strip()
        path = match.group(4).strip()
        data = match.group(5).strip()
        
        # Parse timestamp from log entry (should be GPS time from direwolf-gpstime.sh)
        # GPS time is always UTC, so treat timestamps without timezone as UTC
        try:
            # If timestamp has 'Z', replace with '+00:00' for UTC
            # If no timezone indicator, assume UTC (GPS time is always UTC)
            if 'Z' in timestamp_str:
                timestamp_str_utc = timestamp_str.replace('Z', '+00:00')
            elif '+' in timestamp_str or timestamp_str.count('-') > 2:
                # Already has timezone indicator
                timestamp_str_utc = timestamp_str
            else:
                # No timezone - assume UTC (GPS time)
                timestamp_str_utc = timestamp_str + '+00:00'
            
            # Parse as UTC datetime and convert to Unix timestamp
            # This preserves the raw GPS/UTC time without any timezone conversion
            timestamp = datetime.fromisoformat(timestamp_str_utc)
            # .timestamp() on a UTC datetime returns the correct Unix timestamp (UTC-based)
            timestamp_unix = timestamp.timestamp()
        except ValueError:
            # If timestamp can't be parsed, skip this packet rather than using system time
            # This ensures we only use GPS timestamps from the log
            return None
        
        # Extract callsign and SSID
        source_parts = source.split('-')
        callsign = source_parts[0].strip()
        ssid = source_parts[1].strip() if len(source_parts) > 1 else None
        
        # Try to parse with aprslib first (handles MIC-E, compressed, and standard formats)
        if HAS_APRSLIB:
            try:
                # Reconstruct packet for aprslib
                packet_text = f"{source}>{path}:{data}"
                packet = aprslib.parse(packet_text)
                
                # aprslib can parse MIC-E, compressed, and standard position packets
                # Check for position data (latitude/longitude)
                if 'latitude' in packet and 'longitude' in packet:
                    # Extract callsign and SSID from aprslib 'from' field if present
                    if 'from' in packet:
                        from_field = packet['from']
                        from_parts = from_field.split('-')
                        packet_callsign = from_parts[0].strip()
                        packet_ssid = from_parts[1].strip() if len(from_parts) > 1 else None
                    else:
                        # Fall back to source field if 'from' not available
                        packet_callsign = callsign
                        packet_ssid = ssid
                    
                    return {
                        'callsign': packet_callsign,
                        'ssid': packet_ssid,
                        'latitude': packet['latitude'],
                        'longitude': packet['longitude'],
                        'timestamp': timestamp_unix,
                        'channel': channel,
                        'path': path,
                        'comment': packet.get('comment', ''),
                        'symbol_table': packet.get('symbol_table', '/'),
                        'symbol_code': packet.get('symbol', '>'),
                        'raw': data
                    }
            except Exception as e:
                # aprslib failed - log the error and fall through to manual parsing
                # Only log errors for non-standard formats (MIC-E, compressed, timestamped) since standard formats can be manually parsed
                # MIC-E can start with ':' or  (single quote)
                # Compressed can start with '=' or '/'
                # Timestamped starts with '@'
                if data.startswith(':') or data.startswith("'") or data.startswith('=') or data.startswith('/') or data.startswith('@'):
                    # MIC-E, compressed, or timestamped format - aprslib is required
                    # Log error but keep it minimal
                    print(f"aprslib error: {type(e).__name__}: {str(e)[:100]} - {callsign}")
                # Fall through to manual parsing for standard position format
                pass
        
        # Manual parsing - look for position data
        # APRS format: !DDMM.mmN[symbol_table]DDDMM.mmW[symbol_code]... (standard position)
        # APRS format: @HHMMSSzDDMM.mmN[symbol_table]DDDMM.mmW[symbol_code]... (timestamped position)
        # Example: !3748.60S/17517.80E`278/000 or !3745.40S/17516.68E#
        # Example: @130548z3821.14S/17448.43E#PHG4720
        # Symbol table is between latitude and longitude (can be / or \)
        # Symbol code is after longitude direction
        
        # Try timestamped position format first (@HHMMSSz...)
        pos_match = re.search(r'@\d{6}z(\d{2})(\d{2}\.\d{2})([NS])([/\\])(\d{3})(\d{2}\.\d{2})([EW])(.)', data)
        if not pos_match:
            # Try standard position format (!...)
            pos_match = re.search(r'!(\d{2})(\d{2}\.\d{2})([NS])([/\\])(\d{3})(\d{2}\.\d{2})([EW])(.)', data)
        if pos_match:
            # Extract components
            lat_deg = pos_match.group(1)
            lat_min = pos_match.group(2)
            lat_dir = pos_match.group(3)
            symbol_table = pos_match.group(4)  # Symbol table is between lat and lon
            lon_deg = pos_match.group(5)
            lon_min = pos_match.group(6)
            lon_dir = pos_match.group(7)
            symbol_code = pos_match.group(8)  # Symbol code is after longitude
            
            # Reconstruct position string for parsing
            pos_str = f"!{lat_deg}{lat_min}{lat_dir}/{lon_deg}{lon_min}{lon_dir}"
            lat, lon = parse_aprs_position(pos_str)
            if lat is not None and lon is not None:
                
                # Extract comment (everything after position, symbol, and course/speed)
                # APRS format: position + symbol + course/speed + comment
                # Example: !3748.60S/17517.80E`278/000ZL4ST Portable Digipeater
                # After symbol_code, there may be course/speed (format: 278/000)
                comment_start = pos_match.end()
                comment = data[comment_start:].strip()
                # Remove course/speed if present (format: 278/000)
                if comment:
                    comment = re.sub(r'^\d{3}/\d{3}\s*', '', comment)
                
                result = {
                    'callsign': callsign,
                    'ssid': ssid,
                    'latitude': lat,
                    'longitude': lon,
                    'timestamp': timestamp_unix,
                    'channel': channel,
                    'path': path,
                    'comment': comment,
                    'symbol_table': symbol_table,
                    'symbol_code': symbol_code,
                    'raw': data
                }
                
                # If aprslib was used, try to get symbol from it
                if HAS_APRSLIB:
                    try:
                        packet_text = f"{source}>{path}:{data}"
                        packet = aprslib.parse(packet_text)
                        if 'symbol' in packet:
                            result['symbol_table'] = packet.get('symbol_table', symbol_table)
                            result['symbol_code'] = packet.get('symbol', symbol_code)
                    except Exception:
                        pass
                
                return result
        
        return None
    except (ValueError, IndexError, AttributeError) as e:
        return None

def parse_status_line(line):
    """
    Parse status/info lines from Dire Wolf log
    Returns status info dict or None
    """
    status_info = {}
    
    # Check for version info
    if 'Dire Wolf Release' in line:
        match = re.search(r'Dire Wolf Release ([\d.]+)', line)
        if match:
            status_info['version'] = match.group(1)
    
    # Check for GPS status
    if 'GPSD:' in line:
        if 'Location fix is now 3D' in line:
            status_info['gps_status'] = '3D Fix'
        elif 'No location fix' in line:
            status_info['gps_status'] = 'No Fix'
    
    # Check for audio device
    if 'Audio device' in line:
        match = re.search(r'Audio device.*?:\s*(.+)', line)
        if match:
            status_info['audio_device'] = match.group(1).strip()
    
    # Audio error check removed
    
    # Check for ready status
    if 'Ready to accept' in line:
        if 'AGW' in line:
            status_info['agw_ready'] = True
        if 'KISS' in line:
            status_info['kiss_ready'] = True
    
    return status_info if status_info else None

def get_reset_timestamp():
    """Get the reset timestamp (GPS time) from file"""
    if os.path.exists(RESET_TIMESTAMP_FILE):
        try:
            with open(RESET_TIMESTAMP_FILE, 'r') as f:
                data = json.load(f)
                return data.get('reset_timestamp', 0)
        except Exception:
            return 0
    return 0

def get_last_log_read_timestamp():
    """
    Get the last timestamp we processed from the log file
    This is stored separately from packet data to track log reading progress
    """
    if os.path.exists(LAST_LOG_READ_FILE):
        try:
            with open(LAST_LOG_READ_FILE, 'r') as f:
                data = json.load(f)
                return data.get('last_log_read_timestamp', 0)
        except Exception:
            return 0
    return 0

def save_last_log_read_timestamp(timestamp):
    """
    Save the last timestamp we processed from the log file
    """
    try:
        with open(LAST_LOG_READ_FILE, 'w') as f:
            json.dump({'last_log_read_timestamp': timestamp}, f, indent=2)
    except Exception as e:
        print(f"Error saving last log read timestamp: {e}")

def get_current_gps_time():
    """
    Get current GPS time using gpspipe -w -n 10
    Reads multiple messages until we find one with a time field (TPV messages have time)
    Returns Unix timestamp or None if not available
    """
    try:
        # Run gpspipe to get GPS time
        # -w: wait for data
        # -n 10: read up to 10 messages to find one with time
        result = subprocess.run(
            ['gpspipe', '-w', '-n', '10'],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode != 0:
            return None
        
        if not result.stdout:
            return None
        
        # Parse JSON output from gpspipe
        # Look for time field in the messages (TPV messages have time)
        for line in result.stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                # Check for time field - TPV (Time-Position-Velocity) messages have it
                # Also check message class to prefer TPV messages
                if 'time' in data and data['time']:
                    # Parse GPS time string (format: "2025-12-11T01:26:35.000Z" or "2025-12-11T01:26:35Z")
                    time_str = data['time']
                    # Handle both formats with and without milliseconds
                    # Parse raw GPS time from gpspipe (always UTC)
                    if time_str.endswith('Z'):
                        time_str = time_str.replace('Z', '+00:00')
                    # Parse as UTC datetime and convert to Unix timestamp
                    # This preserves the raw GPS/UTC time without any timezone conversion
                    timestamp = datetime.fromisoformat(time_str)
                    # .timestamp() on a UTC datetime returns the correct Unix timestamp (UTC-based)
                    return timestamp.timestamp()
            except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
                # Continue to next line if this one doesn't have time
                continue
        
        # No time field in gpspipe output (silent)
        
    except subprocess.TimeoutExpired:
        # gpspipe timeout (silent)
        pass
    except FileNotFoundError:
        # gpspipe not found (silent)
        pass
    except subprocess.SubprocessError as e:
        # Error running gpspipe (silent)
        pass
    except Exception as e:
        # Unexpected error getting GPS time (silent)
        pass
    
    return None

def get_latest_gps_time_from_log(log_file_path):
    """
    Extract the latest GPS timestamp from the log file
    Returns Unix timestamp or None if not found
    """
    if not os.path.exists(log_file_path):
        return None
    
    latest_timestamp = None
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Read file in reverse to get latest timestamp faster
            lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                
                # Look for timestamp pattern: [2025-12-11T01:26:35Z]
                # GPS time is always UTC, so treat timestamps without timezone as UTC
                timestamp_match = re.search(r'\[([^\]]+)\]', line)
                if timestamp_match:
                    timestamp_str = timestamp_match.group(1)
                    try:
                        # If timestamp has 'Z', replace with '+00:00' for UTC
                        # If no timezone indicator, assume UTC (GPS time is always UTC)
                        if 'Z' in timestamp_str:
                            timestamp_str_utc = timestamp_str.replace('Z', '+00:00')
                        elif '+' in timestamp_str or timestamp_str.count('-') > 2:
                            # Already has timezone indicator
                            timestamp_str_utc = timestamp_str
                        else:
                            # No timezone - assume UTC (GPS time)
                            timestamp_str_utc = timestamp_str + '+00:00'
                        
                        # Parse as UTC datetime and convert to Unix timestamp
                        # This preserves the raw GPS/UTC time without any timezone conversion
                        timestamp = datetime.fromisoformat(timestamp_str_utc)
                        # .timestamp() on a UTC datetime returns the correct Unix timestamp (UTC-based)
                        timestamp_unix = timestamp.timestamp()
                        if latest_timestamp is None or timestamp_unix > latest_timestamp:
                            latest_timestamp = timestamp_unix
                    except ValueError:
                        continue
    except Exception as e:
        print(f"Error reading log file for GPS time: {e}")
    
    return latest_timestamp

def parse_log_file(log_file_path):
    """
    Parse Dire Wolf log file and extract packets and status
    Uses GPS time from log timestamps and skips entries before reset_timestamp
    """
    packets = []
    status = {
        'version': None,
        'gps_status': None,
        'audio_device': None,
        'agw_ready': False,
        'kiss_ready': False,
        'last_update': None,
        'gps_time': None  # Store latest GPS time
    }
    
    # Get reset timestamp - skip logs before this (hard cutoff)
    reset_timestamp = get_reset_timestamp()
    
    # Get last log read timestamp - skip entries we've already read from the log
    last_log_read_timestamp = get_last_log_read_timestamp()
    
    # Use the maximum of reset_timestamp and last_log_read_timestamp as the cutoff
    # Reset timestamp takes precedence (hard cutoff), but we also skip entries we've already read
    cutoff_timestamp = max(reset_timestamp, last_log_read_timestamp)
    
    # Get current GPS time from gpspipe for "now" reference
    current_gps_time = get_current_gps_time()
    if current_gps_time:
        status['gps_time'] = current_gps_time
        status['last_update'] = datetime.fromtimestamp(current_gps_time, tz=timezone.utc).isoformat()
        # GPS time will be shown only if new packets are found
    else:
        # Fallback to latest GPS time from log if gpspipe fails
        latest_gps_time = get_latest_gps_time_from_log(log_file_path)
        if latest_gps_time:
            status['gps_time'] = latest_gps_time
            status['last_update'] = datetime.fromtimestamp(latest_gps_time, tz=timezone.utc).isoformat()
            # Using latest log GPS time as fallback (silent)
        else:
            # Last resort: system time
            current_time = datetime.now().timestamp()
            status['gps_time'] = current_time
            status['last_update'] = datetime.now(timezone.utc).isoformat()
            # Using system time as fallback (silent)
    
    if not os.path.exists(log_file_path):
        # Log file not found (silent)
        return packets, status
    
    try:
        latest_seen_timestamp = cutoff_timestamp  # Track latest timestamp seen (even if skipped)
        
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Extract timestamp from line to check if we should skip it
                # GPS time is always UTC, so treat timestamps without timezone as UTC
                timestamp_match = re.search(r'\[([^\]]+)\]', line)
                line_timestamp = None
                if timestamp_match:
                    timestamp_str = timestamp_match.group(1)
                    try:
                        # If timestamp has 'Z', replace with '+00:00' for UTC
                        # If no timezone indicator, assume UTC (GPS time is always UTC)
                        if 'Z' in timestamp_str:
                            timestamp_str_utc = timestamp_str.replace('Z', '+00:00')
                        elif '+' in timestamp_str or timestamp_str.count('-') > 2:
                            # Already has timezone indicator
                            timestamp_str_utc = timestamp_str
                        else:
                            # No timezone - assume UTC (GPS time)
                            timestamp_str_utc = timestamp_str + '+00:00'
                        
                        timestamp = datetime.fromisoformat(timestamp_str_utc)
                        line_timestamp = timestamp.timestamp()
                        
                        # Track the latest timestamp we've seen (even if we skip the entry)
                        if line_timestamp > latest_seen_timestamp:
                            latest_seen_timestamp = line_timestamp
                    except ValueError:
                        pass
                
                # Skip log entries before or equal to cutoff timestamp (reset or already processed)
                # Use <= to skip entries with timestamp <= cutoff (already processed)
                # Add small epsilon (0.1 seconds) to handle floating point precision and timing issues
                if cutoff_timestamp > 0 and line_timestamp:
                    # Skip if timestamp is less than or very close to cutoff (within 0.1s)
                    # This accounts for floating point precision and slight timing differences
                    cutoff_with_epsilon = cutoff_timestamp + 0.1
                    if line_timestamp <= cutoff_with_epsilon:
                        # Debug: show what we're skipping (only first few to avoid spam)
                        if not hasattr(parse_log_file, '_skip_count'):
                            parse_log_file._skip_count = 0
                        parse_log_file._skip_count += 1
                        if parse_log_file._skip_count <= 3:
                            line_time_str = datetime.fromtimestamp(line_timestamp, tz=timezone.utc).isoformat()
                            cutoff_time_str = datetime.fromtimestamp(cutoff_timestamp, tz=timezone.utc).isoformat()
                            # Skipping entry (silent)
                        continue
                
                # Try to parse as APRS packet
                packet = parse_aprs_packet(line)
                if packet:
                    # Ensure packet timestamp is GPS time (from log)
                    if line_timestamp:
                        packet['timestamp'] = line_timestamp
                    packets.append(packet)
                else:
                    # Try to parse as status line
                    status_info = parse_status_line(line)
                    if status_info:
                        status.update(status_info)
        
        # Update the last log read timestamp to the latest we've seen in the log
        # This ensures we advance even if all packets were skipped (duplicates)
        # latest_seen_timestamp was tracked during the loop above
        if latest_seen_timestamp > cutoff_timestamp:
            save_last_log_read_timestamp(latest_seen_timestamp)
            latest_time_str = datetime.fromtimestamp(latest_seen_timestamp, tz=timezone.utc).isoformat()
            # Updated last log read timestamp (silent)
    
    except Exception as e:
        print(f"Error: {e}")
    
    return packets, status

def load_existing_data():
    """Load existing packet data from JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def create_packet_id(packet):
    """
    Create a unique identifier for a packet to detect duplicates
    Uses callsign, timestamp, latitude, and longitude
    """
    callsign = packet.get('callsign', '')
    timestamp = packet.get('timestamp', 0)
    lat = packet.get('latitude', 0)
    lon = packet.get('longitude', 0)
    
    # Round coordinates to 4 decimal places to handle floating point differences
    lat_rounded = round(lat, 4)
    lon_rounded = round(lon, 4)
    
    # Round timestamp to 1 decimal place to handle floating point precision issues
    # This helps catch duplicates even if timestamps differ slightly due to parsing
    timestamp_rounded = round(timestamp, 1)
    
    # Create unique ID
    return f"{callsign}_{timestamp_rounded}_{lat_rounded}_{lon_rounded}"

def save_data(packets, all_packets):
    """Save packet data to JSON file, merging with existing data and avoiding duplicates"""
    # Load existing data
    existing = load_existing_data()
    
    # Create a set of existing packet IDs for fast lookup
    existing_ids = set()
    for packet in existing:
        packet_id = create_packet_id(packet)
        existing_ids.add(packet_id)
    
    # Filter out duplicates from new packets
    new_packets = []
    duplicate_count = 0
    for packet in packets:
        packet_id = create_packet_id(packet)
        if packet_id not in existing_ids:
            new_packets.append(packet)
            existing_ids.add(packet_id)  # Add to set to avoid duplicates within new packets
        else:
            duplicate_count += 1
    
    if not new_packets:
        return existing
    
    # Combine existing and new packets
    all_packets_list = existing + new_packets
    
    # Sort by timestamp (newest first)
    all_packets_list.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    # Keep only last 5000 packets per callsign to prevent file from growing too large
    # Increased from 1000 to allow more history
    limited_packets = []
    callsign_counts = {}
    for packet in all_packets_list:
        callsign = packet.get('callsign')
        if callsign:
            count = callsign_counts.get(callsign, 0)
            if count < 5000:
                limited_packets.append(packet)
                callsign_counts[callsign] = count + 1
    
    # Save to file
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(limited_packets, f, indent=2)
        # Return new_packets for logging (will be logged in main)
        return limited_packets
    except Exception as e:
        print(f"Error saving data: {e}")
        return []

def save_status(status):
    """Save status information to JSON file"""
    try:
        with open(STATUS_FILE, 'w') as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        print(f"Error saving status: {e}")

def save_reset_timestamp(gps_timestamp):
    """Save reset timestamp (GPS time) to file"""
    try:
        with open(RESET_TIMESTAMP_FILE, 'w') as f:
            json.dump({'reset_timestamp': gps_timestamp}, f, indent=2)
        # Reset timestamp saved (silent)
    except Exception as e:
        # Error saving reset timestamp (silent)
        pass

def main():
    """Main function"""
    # Get log file path from command line or use default
    log_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG_FILE
    
    # Check if aprslib is available and log if not (only once)
    if not HAS_APRSLIB:
        if not hasattr(main, '_aprslib_warning_logged'):
            print("Warning: aprslib not available - MIC-E and compressed packets cannot be parsed")
            main._aprslib_warning_logged = True
    
    # Parse log file
    new_packets, status = parse_log_file(log_file)
    
    # Check if aprslib is available and log if not
    if not HAS_APRSLIB:
        # Only log this once per run, not for every packet
        if not hasattr(main, '_aprslib_warning_logged'):
            print("Warning: aprslib not available - MIC-E and compressed packets cannot be parsed")
            main._aprslib_warning_logged = True
    
    # Only show output if there are new packets
    if not new_packets:
        return
    
    # Get current GPS time for display
    current_gps_time = status.get('gps_time')
    if current_gps_time:
        gps_time_str = datetime.fromtimestamp(current_gps_time, tz=timezone.utc).isoformat()
    else:
        # Fallback to latest log GPS time or system time
        gps_time_str = status.get('last_update', datetime.now(timezone.utc).isoformat())
    
    # Load existing data
    existing_packets = load_existing_data()
    
    # Merge and save
    all_packets = save_data(new_packets, existing_packets + new_packets)
    
    # Save status
    save_status(status)
    
    # Get unique callsigns with SSID from new packets
    new_callsigns_with_ssid = []
    for p in new_packets:
        callsign = p.get('callsign', '')
        if callsign:
            ssid = p.get('ssid')
            if ssid:
                callsign_with_ssid = f"{callsign}-{ssid}"
            else:
                callsign_with_ssid = callsign
            if callsign_with_ssid not in new_callsigns_with_ssid:
                new_callsigns_with_ssid.append(callsign_with_ssid)
    
    # Sort and format
    new_callsigns_with_ssid.sort()
    
    # Only show GPS time and new callsigns with SSID
    if new_callsigns_with_ssid:
        callsigns_str = ', '.join(new_callsigns_with_ssid)
        print(f"{gps_time_str} {callsigns_str}")

if __name__ == '__main__':
    main()

