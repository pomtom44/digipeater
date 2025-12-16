#!/usr/bin/env python3
"""
Script: Digipeater Web Server
Created by: 
Created Date: 
Modified By:
Modified Date:
Description: Lightweight web server for APRS digipeater monitoring
"""

import json
import os
import time
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

DATA_FILE = "digipeater_data.json"
STATUS_FILE = "digipeater_status.json"
RESET_TIMESTAMP_FILE = "reset_timestamp.json"
LAST_LOG_READ_FILE = "last_log_read_timestamp.json"

class DigipeaterHandler(BaseHTTPRequestHandler):
    """HTTP request handler for digipeater web interface"""
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # Serve static files
        if path == '/' or path == '/index.html':
            self.serve_file('index.html', 'text/html')
        elif path == '/styles.css':
            self.serve_file('styles.css', 'text/css')
        elif path == '/app.js':
            self.serve_file('app.js', 'application/javascript')
        elif path == '/symbols.js':
            self.serve_file('symbols.js', 'application/javascript')
        elif path == '/aprs-symbols-48-0.png':
            self.serve_file('aprs-symbols-48-0.png', 'image/png')
        elif path.startswith('/leaflet/'):
            # Serve Leaflet files
            leaflet_file = path[9:]  # Remove '/leaflet/' prefix
            if leaflet_file.endswith('.css'):
                self.serve_file(f'leaflet/{leaflet_file}', 'text/css')
            elif leaflet_file.endswith('.js'):
                self.serve_file(f'leaflet/{leaflet_file}', 'application/javascript')
            elif 'images/' in leaflet_file:
                # Handle images in images/ subdirectory
                if leaflet_file.endswith('.png'):
                    self.serve_file(f'leaflet/{leaflet_file}', 'image/png')
                elif leaflet_file.endswith('.jpg') or leaflet_file.endswith('.jpeg'):
                    self.serve_file(f'leaflet/{leaflet_file}', 'image/jpeg')
                else:
                    self.send_error(404)
            else:
                self.send_error(404)
        elif path.startswith('/tiles/'):
            # Serve offline map tiles
            tile_path = path[7:]  # Remove '/tiles/' prefix
            if tile_path.endswith('.png'):
                self.serve_file(f'tiles/{tile_path}', 'image/png')
            else:
                self.send_error(404)
        # API endpoints
        elif path == '/api/packets':
            self.serve_packets()
        elif path == '/api/status':
            self.serve_status()
        elif path == '/api/callsigns':
            self.serve_callsigns()
        else:
            self.send_error(404)
    
    def do_DELETE(self):
        """Handle DELETE requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/api/reset':
            self.reset_database()
        else:
            self.send_error(404)
    
    def serve_file(self, filepath, content_type):
        """Serve a static file"""
        try:
            if not os.path.exists(filepath):
                self.send_error(404)
                return
            
            with open(filepath, 'rb') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', content_type)
            self.send_header('Content-length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            print(f"Error serving file {filepath}: {e}")
            self.send_error(500)
    
    def serve_packets(self):
        """Serve packet data as JSON"""
        try:
            query_params = parse_qs(urlparse(self.path).query)
            callsign = query_params.get('callsign', [None])[0]
            
            if not os.path.exists(DATA_FILE):
                packets = []
            else:
                with open(DATA_FILE, 'r') as f:
                    all_packets = json.load(f)
                
                # Filter by callsign if provided
                if callsign:
                    packets = [p for p in all_packets if p.get('callsign') == callsign]
                else:
                    packets = all_packets
                
                # Limit to last 1000 packets
                packets = packets[:1000]
            
            self.send_json_response(packets)
        except Exception as e:
            print(f"Error serving packets: {e}")
            self.send_error(500)
    
    def get_current_gps_time(self):
        """
        Get current GPS time using gpspipe -w -n 10
        Reads multiple messages to find one with a time field (TPV messages have time)
        Returns Unix timestamp or None if not available
        """
        try:
            # Run gpspipe to get current GPS time
            # Use -n 10 to read multiple messages and find one with a time field (TPV messages)
            result = subprocess.run(
                ['gpspipe', '-w', '-n', '10'],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode == 0:
                # Parse JSON output from gpspipe
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if 'time' in data and data['time']:
                            # Parse GPS time string
                            time_str = data['time']
                            if time_str.endswith('Z'):
                                time_str = time_str.replace('Z', '+00:00')
                            timestamp = datetime.fromisoformat(time_str)
                            return timestamp.timestamp()
                    except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
                        continue
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError) as e:
            # Silently fail - will use status file value or fallback
            pass
        except Exception:
            pass
        
        return None
    
    def serve_status(self):
        """Serve status information as JSON"""
        try:
            # Load base status from file
            if not os.path.exists(STATUS_FILE):
                status = {
                    'version': None,
                    'gps_status': None,
                    'audio_device': None,
                    'audio_error': False,
                    'agw_ready': False,
                    'kiss_ready': False,
                    'last_update': None,
                    'gps_time': None
                }
            else:
                with open(STATUS_FILE, 'r') as f:
                    status = json.load(f)
                    # Ensure gps_time field exists
                    if 'gps_time' not in status:
                        status['gps_time'] = None
            
            # Always get fresh GPS time from gpspipe for accurate "now" reference
            current_gps_time = self.get_current_gps_time()
            if current_gps_time:
                status['gps_time'] = current_gps_time
                status['last_update'] = datetime.fromtimestamp(current_gps_time).isoformat()
            elif status.get('gps_time') is None:
                # Fallback to system time if no GPS time available
                status['gps_time'] = time.time()
                status['last_update'] = datetime.now().isoformat()
            
            self.send_json_response(status)
        except Exception as e:
            print(f"Error serving status: {e}")
            self.send_error(500)
    
    def serve_callsigns(self):
        """Serve list of unique callsigns"""
        try:
            if not os.path.exists(DATA_FILE):
                callsigns = []
            else:
                with open(DATA_FILE, 'r') as f:
                    packets = json.load(f)
                
                # Get unique callsigns with last seen timestamp and SSID
                callsign_data = {}
                for packet in packets:
                    callsign = packet.get('callsign')
                    if callsign:
                        timestamp = packet.get('timestamp', 0)
                        ssid = packet.get('ssid')
                        # Use callsign-SSID as key to handle multiple SSIDs for same callsign
                        callsign_key = f"{callsign}-{ssid}" if ssid else callsign
                        if callsign_key not in callsign_data or timestamp > callsign_data[callsign_key]['last_seen']:
                            callsign_data[callsign_key] = {
                                'callsign': callsign,
                                'ssid': ssid,
                                'last_seen': timestamp
                            }
                
                # Convert to list and sort by last seen (newest first)
                callsigns = sorted(callsign_data.values(), key=lambda x: x['last_seen'], reverse=True)
            
            self.send_json_response(callsigns)
        except Exception as e:
            print(f"Error serving callsigns: {e}")
            self.send_error(500)
    
    def reset_database(self):
        """Reset the database by clearing all packet data and storing current GPS time"""
        try:
            # Get current GPS time from status file
            gps_timestamp = None
            if os.path.exists(STATUS_FILE):
                try:
                    with open(STATUS_FILE, 'r') as f:
                        status = json.load(f)
                        gps_timestamp = status.get('gps_time')
                except Exception:
                    pass
            
            # If no GPS time in status, use current system time as fallback
            if not gps_timestamp:
                gps_timestamp = time.time()
                print("Warning: No GPS time available, using system time")
            
            # Save reset timestamp (GPS time)
            reset_data = {'reset_timestamp': gps_timestamp}
            with open(RESET_TIMESTAMP_FILE, 'w') as f:
                json.dump(reset_data, f, indent=2)
            
            # Delete the last log read timestamp file to start fresh
            if os.path.exists(LAST_LOG_READ_FILE):
                os.remove(LAST_LOG_READ_FILE)
            
            # Delete the data file if it exists
            if os.path.exists(DATA_FILE):
                os.remove(DATA_FILE)
            
            # Create an empty data file
            with open(DATA_FILE, 'w') as f:
                json.dump([], f)
            
            from datetime import datetime
            reset_time_str = datetime.fromtimestamp(gps_timestamp).isoformat()
            response_data = {
                'success': True, 
                'message': 'Database reset successfully',
                'reset_timestamp': gps_timestamp,
                'reset_time': reset_time_str
            }
            print(f"Database reset at GPS time: {reset_time_str}")
            self.send_json_response(response_data)
        except Exception as e:
            print(f"Error resetting database: {e}")
            error_data = {'success': False, 'error': str(e)}
            json_data = json.dumps(error_data)
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json_data.encode('utf-8'))
    
    def send_json_response(self, data):
        """Send JSON response"""
        json_data = json.dumps(data)
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json_data.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to reduce log noise"""
        # Only log errors
        if '404' in format or '500' in format:
            super().log_message(format, *args)

def run_server(port=8080):
    """Run the web server"""
    server_address = ('', port)
    httpd = HTTPServer(server_address, DigipeaterHandler)
    print(f"Digipeater web server running on http://0.0.0.0:{port}")
    print("Press Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.shutdown()

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)

