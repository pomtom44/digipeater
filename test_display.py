#!/usr/bin/env python3
"""
Standalone e-ink display test script — Waveshare Pico-ePaper-2.9-B (296x128, B/W/R).

Fully self-contained: no dependency on the DEV_BUILD package structure, so this
is the only file that needs copying to the Pi to iterate on driver-level fixes
(pins, SPI speed, timing) without going through install.sh/git/systemd at all.

Usage:
    python3 test_display.py init        # just run init(), watch busy behaviour
    python3 test_display.py clear       # init() + Clear()
    python3 test_display.py pattern     # init() + draw a test pattern
    python3 test_display.py busy        # only watch the BUSY pin, no commands sent

    # OLD (wrong-for-this-board) SSD1680 protocol — A/B control only, to check
    # whether the panel is still alive/responsive under current wiring:
    python3 test_display.py old-init
    python3 test_display.py old-clear
    python3 test_display.py old-pattern

Edit the constants below to test different pins/timing without hunting through
the real driver files.
"""

import sys
import time

# ── Edit these to test different values quickly ─────────────────────────
RST_PIN  = 17
DC_PIN   = 25
CS_PIN   = 8
BUSY_PIN = 24

SPI_SPEED_HZ = 1_000_000
RESET_HIGH_MS = 200          # matches epd2in9b_V4.py's official reset timing
RESET_LOW_MS = 2

BUSY_POLL_MS = 200            # matches epd2in9b_V4.py's official poll interval
BUSY_TIMEOUT_MS = 60_000     # give up and report, rather than hang forever
BUSY_LOG_EVERY_MS = 1000     # print a status line this often while waiting

EPD_WIDTH = 128
EPD_HEIGHT = 296

# ── GPIO / SPI setup ──────────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    import spidev
    HW = True
except ImportError:
    HW = False
    print("!! RPi.GPIO/spidev not available — running in simulation mode (no real hardware access)")

spi = None


def module_init():
    global spi
    if not HW:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(RST_PIN, GPIO.OUT)
    GPIO.setup(DC_PIN, GPIO.OUT)
    GPIO.setup(CS_PIN, GPIO.OUT)
    # Internal pull-up: if BUSY is open-drain (only actively pulled low when
    # busy), a plain floating input with no pull reads a constant LOW
    # regardless of the panel's real state — matches everything observed so far.
    GPIO.setup(BUSY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode = 0b00
    print(f"GPIO/SPI initialised — RST={RST_PIN} DC={DC_PIN} CS={CS_PIN} BUSY={BUSY_PIN}, SPI={SPI_SPEED_HZ}Hz")


def module_exit():
    if not HW:
        return
    GPIO.output(RST_PIN, 0)
    GPIO.output(DC_PIN, 0)
    spi.close()
    GPIO.cleanup()


def digital_write(pin, value):
    if HW:
        GPIO.output(pin, value)


def digital_read(pin):
    return GPIO.input(pin) if HW else 0


def delay_ms(ms):
    time.sleep(ms / 1000.0)


def spi_writebyte(data):
    if HW:
        spi.writebytes(data)


def spi_writebytes(data):
    if not HW:
        return
    if hasattr(spi, "writebytes2"):
        spi.writebytes2(data)
    else:
        data = list(data)
        for i in range(0, len(data), 4096):
            spi.writebytes(data[i:i + 4096])


# ── EPD driver — matches Waveshare's official epd2in9b_V4.py exactly ──
# (V3 was the wrong hardware revision — see old_* functions below and the
# conversation history. V4 is SSD1680-family, same style as old_*, plus a
# second red-plane command. Confirmed: busy=1 means busy, 0=idle — SAME
# polarity as old_*, opposite of what V3 used.)

def reset():
    print("Reset pulse...")
    digital_write(RST_PIN, 1)
    delay_ms(RESET_HIGH_MS)
    digital_write(RST_PIN, 0)
    delay_ms(RESET_LOW_MS)
    digital_write(RST_PIN, 1)
    delay_ms(RESET_HIGH_MS)


def cmd(c):
    digital_write(DC_PIN, 0)
    digital_write(CS_PIN, 0)
    spi_writebyte([c])
    digital_write(CS_PIN, 1)


def data(d):
    digital_write(DC_PIN, 1)
    digital_write(CS_PIN, 0)
    spi_writebyte([d])
    digital_write(CS_PIN, 1)


def data_block(d):
    digital_write(DC_PIN, 1)
    digital_write(CS_PIN, 0)
    spi_writebytes(d)
    digital_write(CS_PIN, 1)


def wait_busy(label=""):
    """Busy is signalled HIGH on this controller (idle is LOW) — same
    polarity as old_wait_busy(). Verbose live status so you can correlate
    against a multimeter in real time."""
    cmd(0x71)
    waited = 0
    last_log = 0
    start = time.time()
    while True:
        level = digital_read(BUSY_PIN)
        if level == 0:
            print(f"[{label}] BUSY -> idle (LOW) after {time.time() - start:.1f}s")
            return True
        if waited >= BUSY_TIMEOUT_MS:
            print(f"[{label}] TIMED OUT after {waited/1000:.1f}s — BUSY still reads HIGH (1)")
            return False
        if waited - last_log >= BUSY_LOG_EVERY_MS:
            print(f"[{label}] still busy (HIGH) at {waited/1000:.1f}s...")
            last_log = waited
        delay_ms(BUSY_POLL_MS)
        waited += BUSY_POLL_MS


def init():
    module_init()
    reset()

    ok1 = wait_busy("pre-reset")
    print("Sending SWRESET (0x12)...")
    cmd(0x12)
    ok2 = wait_busy("swreset")

    print("Sending driver output control, data entry mode, window/cursor, config...")
    cmd(0x01); data((EPD_HEIGHT - 1) % 256); data((EPD_HEIGHT - 1) // 256); data(0x00)
    cmd(0x11); data(0x03)
    cmd(0x44); data(0x00); data(EPD_WIDTH // 8 - 1)
    cmd(0x45); data(0x00); data(0x00); data((EPD_HEIGHT - 1) % 256); data((EPD_HEIGHT - 1) // 256)
    cmd(0x3C); data(0x05)
    cmd(0x21); data(0x00); data(0x80)
    cmd(0x18); data(0x80)
    cmd(0x4E); data(0x00)
    cmd(0x4F); data(0x00); data(0x00)
    ok3 = wait_busy("init-final")

    ok = ok1 and ok2 and ok3
    print(f"init() complete ({'succeeded' if ok else 'timed out at some stage'})")
    return ok


def turn_on_display(label="refresh"):
    cmd(0x22); data(0xF7)
    cmd(0x20)
    return wait_busy(label)


def clear():
    blank_black = [0xFF] * (EPD_WIDTH // 8 * EPD_HEIGHT)
    blank_red = [0x00] * (EPD_WIDTH // 8 * EPD_HEIGHT)   # V4's own convention — NOT 0xFF
    cmd(0x24); data_block(blank_black)
    cmd(0x26); data_block(blank_red)
    print("Clear() data sent, waiting for refresh...")
    turn_on_display("clear-refresh")


def getbuffer(image):
    img = image.convert("1")
    iw, ih = img.size
    linewidth = EPD_WIDTH // 8
    buf = [0xFF] * (linewidth * EPD_HEIGHT)
    pixels = img.load()
    if iw == EPD_WIDTH and ih == EPD_HEIGHT:
        for y in range(ih):
            for x in range(iw):
                if pixels[x, y] == 0:
                    buf[(x + y * EPD_WIDTH) // 8] &= ~(0x80 >> (x % 8))
    elif iw == EPD_HEIGHT and ih == EPD_WIDTH:
        for y in range(ih):
            for x in range(iw):
                newx = y
                newy = EPD_HEIGHT - x - 1
                if pixels[x, y] == 0:
                    buf[(newx + newy * EPD_WIDTH) // 8] &= ~(0x80 >> (y % 8))
    return buf


def show_pattern():
    from PIL import Image, ImageDraw
    w, h = 296, 128  # landscape
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w - 1, h - 1), outline=0)
    draw.text((10, 10), "APRS Digipeater", fill=0)
    draw.text((10, 30), "E-Ink test pattern", fill=0)
    draw.text((10, 50), time.strftime("%Y-%m-%d %H:%M:%S"), fill=0)

    buf = getbuffer(image)
    blank_red = [0x00] * (EPD_WIDTH // 8 * EPD_HEIGHT)
    cmd(0x24); data_block(buf)
    cmd(0x26); data_block(blank_red)  # red plane left blank
    print("Pattern data sent, waiting for refresh...")
    turn_on_display("pattern-refresh")


def sleep():
    cmd(0x10)   # deep sleep
    data(0x01)
    delay_ms(2000)
    module_exit()


# ── OLD driver (SSD1680, mono 2.9" V2) — for A/B comparison only ──────
# This is the WRONG protocol for this board (it's a B/W/R panel, not the plain
# SSD1680 one), included only to check whether the panel is still alive and
# responsive under current wiring/pull-up — not as something to actually use.
# Busy polarity is opposite (busy=HIGH here) and it never sends 0x71.

def old_wait_busy():
    while digital_read(BUSY_PIN) == 1:
        delay_ms(10)


def old_set_window(x0, y0, x1, y1):
    cmd(0x44); data((x0 >> 3) & 0xFF); data((x1 >> 3) & 0xFF)
    cmd(0x45); data(y0 & 0xFF); data((y0 >> 8) & 0xFF); data(y1 & 0xFF); data((y1 >> 8) & 0xFF)


def old_set_cursor(x, y):
    cmd(0x4E); data(x & 0xFF)
    cmd(0x4F); data(y & 0xFF); data((y >> 8) & 0xFF)


def old_turn_on():
    cmd(0x22); data(0xF7)
    cmd(0x20)
    old_wait_busy()


def old_init():
    module_init()
    print("OLD driver: reset pulse...")
    digital_write(RST_PIN, 1); delay_ms(20)
    digital_write(RST_PIN, 0); delay_ms(2)
    digital_write(RST_PIN, 1); delay_ms(20)
    old_wait_busy()

    print("OLD driver: SWRESET + panel config...")
    cmd(0x12); old_wait_busy()                          # SWRESET
    cmd(0x01); data(0x27); data(0x01); data(0x00)        # Driver output control
    cmd(0x11); data(0x03)                                 # Data entry mode
    old_set_window(0, 0, EPD_WIDTH - 1, EPD_HEIGHT - 1)
    old_set_cursor(0, 0)
    cmd(0x3C); data(0x05)                                  # Border waveform
    cmd(0x21); data(0x00); data(0x80)                     # Display update control
    cmd(0x18); data(0x80)                                  # Temperature sensor
    old_wait_busy()
    print("OLD driver: init() complete")


def old_getbuffer(image):
    img = image.copy()
    iw, ih = img.size
    if iw == EPD_HEIGHT and ih == EPD_WIDTH:
        img = img.rotate(90, expand=True)
    img = img.convert("1")
    linewidth = (EPD_WIDTH + 7) >> 3
    buf = [0xFF] * (linewidth * EPD_HEIGHT)
    pixels = img.load()
    for y in range(EPD_HEIGHT):
        for x in range(EPD_WIDTH):
            if pixels[x, y] == 0:
                buf[x // 8 + y * linewidth] &= ~(0x80 >> (x % 8))
    return buf


def old_clear():
    linewidth = (EPD_WIDTH + 7) >> 3
    old_set_window(0, 0, EPD_WIDTH - 1, EPD_HEIGHT - 1)
    old_set_cursor(0, 0)
    cmd(0x24)
    data_block([0xFF] * linewidth * EPD_HEIGHT)
    print("OLD driver: Clear() sent, turning on display...")
    old_turn_on()


def old_show_pattern():
    from PIL import Image, ImageDraw
    image = Image.new("1", (296, 128), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 295, 127), outline=0)
    draw.text((10, 10), "OLD DRIVER TEST", fill=0)
    draw.text((10, 30), time.strftime("%Y-%m-%d %H:%M:%S"), fill=0)

    buf = old_getbuffer(image)
    old_set_window(0, 0, EPD_WIDTH - 1, EPD_HEIGHT - 1)
    old_set_cursor(0, 0)
    cmd(0x24)
    data_block(buf)
    print("OLD driver: pattern sent, turning on display...")
    old_turn_on()


def watch_busy_only():
    """No commands sent at all — just watch the raw pin level. Useful to see
    its resting state and whether anything external changes it."""
    module_init()
    print(f"Watching BUSY (GPIO{BUSY_PIN}) raw level — Ctrl+C to stop")
    try:
        last = None
        while True:
            level = digital_read(BUSY_PIN)
            if level != last:
                print(f"BUSY -> {'HIGH (3.3V)' if level else 'LOW (0V)'}")
                last = level
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup() if HW else None


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pattern"

    if mode == "busy":
        watch_busy_only()
    elif mode == "init":
        init()
        module_exit()
    elif mode == "clear":
        init()
        clear()
        module_exit()
    elif mode == "pattern":
        init()
        show_pattern()
        module_exit()
    elif mode == "old-init":
        old_init()
        module_exit()
    elif mode == "old-clear":
        old_init()
        old_clear()
        module_exit()
    elif mode == "old-pattern":
        old_init()
        old_show_pattern()
        module_exit()
    else:
        print(f"Unknown mode '{mode}' — use init, clear, pattern, busy, old-init, old-clear, or old-pattern")
        sys.exit(1)

    print("Done.")
