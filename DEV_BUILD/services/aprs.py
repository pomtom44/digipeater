"""APRS protocol helpers: currently just the APRS-IS login passcode."""


def calculate_passcode(callsign: str) -> int:
    """Calculate the APRS-IS login passcode from a callsign."""
    call = callsign.upper().split("-")[0]
    code = 0x73E2
    for i, char in enumerate(call):
        if i % 2 == 0:
            code ^= ord(char) << 8
        else:
            code ^= ord(char)
    return code & 0x7FFF
