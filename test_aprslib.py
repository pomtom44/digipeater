#!/usr/bin/env python3
"""
Quick test script to check if aprslib is installed and working
"""

import sys

print("Testing aprslib installation...")
print("-" * 50)

# Test 1: Check if aprslib can be imported
try:
    import aprslib
    print("✓ aprslib is installed")
    print(f"  Version: {aprslib.__version__ if hasattr(aprslib, '__version__') else 'unknown'}")
except ImportError:
    print("✗ aprslib is NOT installed")
    print("  Install with: pip3 install aprslib")
    sys.exit(1)

print()

# Test 2: Try parsing a standard position packet
print("Test 2: Parsing standard position packet...")
try:
    packet_text = "ZL1ST-3>APMI0A,WIDE1-1,WIDE2-1:!3745.40S/17516.68E#APRS Digi"
    packet = aprslib.parse(packet_text)
    if 'latitude' in packet and 'longitude' in packet:
        print(f"✓ Standard position parsed successfully")
        print(f"  Latitude: {packet['latitude']}")
        print(f"  Longitude: {packet['longitude']}")
    else:
        print("✗ Standard position parsed but missing lat/lon")
except Exception as e:
    print(f"✗ Failed to parse standard position: {e}")

print()

# Test 3: Try parsing a timestamped position packet
print("Test 3: Parsing timestamped position packet...")
try:
    packet_text = "ZL2AJ-2>APMI06,ZL2AJ-6*,WIDE2-1:@130548z3821.14S/17448.43E#PHG4720"
    packet = aprslib.parse(packet_text)
    if 'latitude' in packet and 'longitude' in packet:
        print(f"✓ Timestamped position parsed successfully")
        print(f"  Latitude: {packet['latitude']}")
        print(f"  Longitude: {packet['longitude']}")
    else:
        print("✗ Timestamped position parsed but missing lat/lon")
except Exception as e:
    print(f"✗ Failed to parse timestamped position: {e}")

print()

# Test 4: Try parsing a MIC-E packet
print("Test 4: Parsing MIC-E packet...")
try:
    packet_text = "ZL2WG-5>SYR3R5,ZL2AS-3,WIDE1,ZL2AJ-6,WIDE2*:`hM'p\\{>/\"4&}Wayne"
    packet = aprslib.parse(packet_text)
    if 'latitude' in packet and 'longitude' in packet:
        print(f"✓ MIC-E packet parsed successfully")
        print(f"  Latitude: {packet['latitude']}")
        print(f"  Longitude: {packet['longitude']}")
        if 'comment' in packet:
            print(f"  Comment: {packet['comment']}")
    else:
        print("✗ MIC-E packet parsed but missing lat/lon")
except Exception as e:
    print(f"✗ Failed to parse MIC-E packet: {e}")
    print(f"  Error type: {type(e).__name__}")

print()
print("-" * 50)
print("Test complete!")

