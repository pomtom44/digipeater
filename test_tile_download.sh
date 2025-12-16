#!/bin/bash
# Quick test script to verify tile download works

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Testing tile download script..."
echo ""

# Test 1: Check if script is executable
if [ ! -x "download_tiles.sh" ]; then
    echo "Making download_tiles.sh executable..."
    chmod +x download_tiles.sh
fi

# Test 2: Check dependencies
echo "Checking dependencies..."
if ! command -v bc &> /dev/null; then
    echo "  ❌ bc not found"
else
    echo "  ✓ bc found"
fi

if ! command -v curl &> /dev/null; then
    echo "  ❌ curl not found"
else
    echo "  ✓ curl found"
fi

# Test 3: Test downloading a single tile
echo ""
echo "Testing single tile download..."
TEST_TILE_DIR="${SCRIPT_DIR}/test_tiles/10/512"
mkdir -p "$TEST_TILE_DIR"
TEST_TILE="${TEST_TILE_DIR}/512.png"

if curl -s -f -L -H "User-Agent: APRS-Digipeater-Tile-Downloader/1.0" \
    -o "$TEST_TILE" "https://tile.openstreetmap.org/10/512/512.png"; then
    if [ -f "$TEST_TILE" ] && file "$TEST_TILE" | grep -q "PNG"; then
        echo "  ✓ Successfully downloaded test tile"
        echo "  ✓ Tile is a valid PNG file"
        rm -rf "${SCRIPT_DIR}/test_tiles"
        echo ""
        echo "All tests passed! The download script should work."
        echo ""
        echo "To download tiles, run:"
        echo "  ./download_tiles.sh"
        echo ""
        echo "Or with custom area:"
        echo "  ./download_tiles.sh \"min_lat,min_lon,max_lat,max_lon\""
    else
        echo "  ❌ Downloaded file is not a valid PNG"
        rm -rf "${SCRIPT_DIR}/test_tiles"
        exit 1
    fi
else
    echo "  ❌ Failed to download test tile"
    echo "  Check your internet connection and try again"
    rm -rf "${SCRIPT_DIR}/test_tiles"
    exit 1
fi

