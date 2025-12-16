#!/bin/bash
#
# Script: Download Map Tiles for Offline Use
# Created by: 
# Created Date: 
# Modified By:
# Modified Date:
# Description: Downloads OpenStreetMap tiles for offline use using a specific area and zoom levels
#

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Configuration
TILES_DIR="${SCRIPT_DIR}/tiles"

echo "=========================================="
echo "APRS Digipeater - Map Tile Downloader"
echo "=========================================="
echo ""
echo "To get your area coordinates:"
echo "1. Open: https://boundingbox.klokantech.com/"
echo "2. Select your area on the map"
echo "3. Click 'CSV' format in the bottom left"
echo "4. Copy the coordinates (format: lon,lat,lon,lat)"
echo ""
echo "Example: 174.4004,-38.4035,176.2049,-37.002"
echo ""

# Get coordinates from user
read -p "Enter coordinates (lon,lat,lon,lat): " COORDS_INPUT

if [ -z "$COORDS_INPUT" ]; then
    echo "Error: No coordinates provided"
    exit 1
fi

# Parse coordinates (CSV format: min_lon,min_lat,max_lon,max_lat)
IFS=',' read -r min_lon min_lat max_lon max_lat <<< "$COORDS_INPUT"

# Validate coordinates
if [ -z "$min_lon" ] || [ -z "$min_lat" ] || [ -z "$max_lon" ] || [ -z "$max_lat" ]; then
    echo "Error: Invalid coordinate format. Expected: lon,lat,lon,lat"
    exit 1
fi

# Get zoom levels from user
echo ""
read -p "Enter zoom levels (min,max, e.g., 5,15): " ZOOM_INPUT

if [ -z "$ZOOM_INPUT" ]; then
    echo "Error: No zoom levels provided"
    exit 1
fi

# Parse zoom levels
IFS=',' read -r MIN_ZOOM MAX_ZOOM <<< "$ZOOM_INPUT"

# Validate zoom levels
if [ -z "$MIN_ZOOM" ] || [ -z "$MAX_ZOOM" ]; then
    echo "Error: Invalid zoom format. Expected: min,max"
    exit 1
fi

# Validate zoom range
if [ "$MIN_ZOOM" -lt 0 ] || [ "$MIN_ZOOM" -gt 19 ] || [ "$MAX_ZOOM" -lt 0 ] || [ "$MAX_ZOOM" -gt 19 ]; then
    echo "Error: Zoom levels must be between 0 and 19"
    exit 1
fi

if [ "$MIN_ZOOM" -gt "$MAX_ZOOM" ]; then
    echo "Error: Minimum zoom must be less than or equal to maximum zoom"
    exit 1
fi

echo ""
echo "=========================================="
echo "Download Configuration:"
echo "=========================================="
echo "Area: $min_lon,$min_lat to $max_lon,$max_lat"
echo "Zoom levels: $MIN_ZOOM to $MAX_ZOOM"
echo "Tiles directory: $TILES_DIR"
echo ""
read -p "Continue with download? (y/n): " CONFIRM

if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "Download cancelled."
    exit 0
fi

echo ""
echo "Starting download..."
echo ""

# Create tiles directory
mkdir -p "$TILES_DIR"

# Function to convert lat/lon to tile coordinates
# Using Python for reliable math functions
lat2tile() {
    local lat=$1
    local zoom=$2
    python3 -c "import math; lat=$lat; zoom=$zoom; n=2**zoom; lat_rad=math.radians(lat); y=int((1 - math.log(math.tan(lat_rad) + 1/math.cos(lat_rad)) / math.pi) / 2 * n); print(y)"
}

lon2tile() {
    local lon=$1
    local zoom=$2
    python3 -c "lon=$lon; zoom=$zoom; n=2**zoom; x=int((lon + 180) / 360 * n); print(x)"
}

# Check if required tools are installed
if ! command -v python3 &> /dev/null; then
    echo "Error: 'python3' command not found. Installing..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y python3
    elif command -v yum &> /dev/null; then
        sudo yum install -y python3
    else
        echo "Please install 'python3' manually and run this script again."
        exit 1
    fi
fi

# Check if curl is installed
if ! command -v curl &> /dev/null; then
    echo "Error: 'curl' command not found. Installing..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y curl
    elif command -v yum &> /dev/null; then
        sudo yum install -y curl
    else
        echo "Please install 'curl' manually and run this script again."
        exit 1
    fi
fi

# Download tiles for each zoom level
for zoom in $(seq $MIN_ZOOM $MAX_ZOOM); do
    echo "Downloading zoom level $zoom..."
    
    # Calculate tile coordinates
    min_x=$(lon2tile $min_lon $zoom)
    max_x=$(lon2tile $max_lon $zoom)
    min_y=$(lat2tile $max_lat $zoom)  # Note: max_lat for min_y
    max_y=$(lat2tile $min_lat $zoom)  # Note: min_lat for max_y
    
    # Validate tile coordinates
    if [ -z "$min_x" ] || [ -z "$max_x" ] || [ -z "$min_y" ] || [ -z "$max_y" ]; then
        echo "  Error: Failed to calculate tile coordinates for zoom level $zoom"
        continue
    fi
    
    echo "  Tile range: X[$min_x-$max_x] Y[$min_y-$max_y]"
    
    # Download each tile
    for x in $(seq $min_x $max_x); do
        for y in $(seq $min_y $max_y); do
            tile_dir="${TILES_DIR}/${zoom}/${x}"
            mkdir -p "$tile_dir"
            tile_file="${tile_dir}/${y}.png"
            
            # Skip if already downloaded
            if [ -f "$tile_file" ]; then
                continue
            fi
            
            # Download tile with User-Agent header (required by OSM)
            url="https://tile.openstreetmap.org/${zoom}/${x}/${y}.png"
            if curl -s -f -L -H "User-Agent: APRS-Digipeater-Tile-Downloader/1.0" -o "$tile_file" "$url"; then
                # Verify the file is actually a PNG (not an error page)
                if file "$tile_file" | grep -q "PNG"; then
                    echo "  Downloaded: z${zoom}/x${x}/y${y}.png"
                else
                    echo "  Failed (not a PNG): z${zoom}/x${x}/y${y}.png"
                    rm -f "$tile_file"
                fi
            else
                echo "  Failed: z${zoom}/x${x}/y${y}.png"
                rm -f "$tile_file"
            fi
            
            # Be nice to the server
            sleep 0.1
        done
    done
done

echo ""
echo "Tile download complete!"
echo "Tiles saved to: $TILES_DIR"
echo ""
echo "Summary:"
total_tiles=0
for zoom in $(seq $MIN_ZOOM $MAX_ZOOM); do
    if [ -d "${TILES_DIR}/${zoom}" ]; then
        zoom_count=$(find "${TILES_DIR}/${zoom}" -name "*.png" | wc -l)
        echo "  Zoom level $zoom: $zoom_count tiles"
        total_tiles=$((total_tiles + zoom_count))
    fi
done
echo "  Total tiles: $total_tiles"