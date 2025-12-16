#!/bin/bash
#
# Script: Install aprslib
# Created by: 
# Created Date: 
# Modified By:
# Modified Date:
# Description: Installs aprslib Python package for APRS packet parsing
#

echo "Installing aprslib for APRS packet parsing..."
echo ""

# Check if we're on a Debian/Ubuntu system
if command -v apt-get >/dev/null 2>&1; then
    echo "Detected Debian/Ubuntu system"
    
    # Try to install pip3 using apt
    if ! command -v pip3 >/dev/null 2>&1; then
        echo "Installing python3-pip..."
        sudo apt-get update
        sudo apt-get install -y python3-pip
    fi
    
    # Now try to install aprslib
    if command -v pip3 >/dev/null 2>&1; then
        echo "Installing aprslib..."
        pip3 install aprslib
        if [ $? -eq 0 ]; then
            echo ""
            echo "✓ aprslib installed successfully!"
            echo "You can now test it with: python3 test_aprslib.py"
        else
            echo ""
            echo "✗ Failed to install aprslib"
            exit 1
        fi
    else
        echo "✗ pip3 is still not available after installation attempt"
        echo "Try manually: sudo apt-get install python3-pip"
        exit 1
    fi

# Check if we're on a RedHat/CentOS system
elif command -v yum >/dev/null 2>&1; then
    echo "Detected RedHat/CentOS system"
    
    # Try to install pip3 using yum
    if ! command -v pip3 >/dev/null 2>&1; then
        echo "Installing python3-pip..."
        sudo yum install -y python3-pip
    fi
    
    # Now try to install aprslib
    if command -v pip3 >/dev/null 2>&1; then
        echo "Installing aprslib..."
        pip3 install aprslib
        if [ $? -eq 0 ]; then
            echo ""
            echo "✓ aprslib installed successfully!"
            echo "You can now test it with: python3 test_aprslib.py"
        else
            echo ""
            echo "✗ Failed to install aprslib"
            exit 1
        fi
    else
        echo "✗ pip3 is still not available after installation attempt"
        echo "Try manually: sudo yum install python3-pip"
        exit 1
    fi

else
    echo "Unknown system - cannot auto-install pip"
    echo "Please install pip3 manually for your system, then run:"
    echo "  pip3 install aprslib"
    exit 1
fi

