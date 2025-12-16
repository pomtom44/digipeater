#!/bin/bash
#
# Script: Download Leaflet for Offline Use
# Created by: 
# Created Date: 
# Modified By:
# Modified Date:
# Description: Downloads Leaflet CSS and JS files for offline use
#

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create leaflet directory
mkdir -p leaflet/images

# Leaflet version
LEAFLET_VERSION="1.9.4"

# Download Leaflet CSS
echo "Downloading Leaflet CSS..."
curl -L "https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.css" -o leaflet/leaflet.css

# Download Leaflet JS
echo "Downloading Leaflet JS..."
curl -L "https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js" -o leaflet/leaflet.js

# Download Leaflet images
echo "Downloading Leaflet images..."
curl -L "https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/images/marker-icon.png" -o leaflet/images/marker-icon.png
curl -L "https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/images/marker-icon-2x.png" -o leaflet/images/marker-icon-2x.png
curl -L "https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/images/marker-shadow.png" -o leaflet/images/marker-shadow.png
curl -L "https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/images/layers.png" -o leaflet/images/layers.png
curl -L "https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/images/layers-2x.png" -o leaflet/images/layers-2x.png

# Fix image paths in CSS (Leaflet CSS references images/ directory)
# The paths should remain as images/ since we're serving from /leaflet/images/
# No change needed - Leaflet CSS uses relative paths which work with our server setup

echo "Leaflet downloaded successfully!"

