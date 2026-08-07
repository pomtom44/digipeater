#!/usr/bin/env python3
"""
Standalone e-ink refresh-mode test — Waveshare Pico-ePaper-2.9-B (296x128, B/W/R).

Draws large text to the panel using each of the four refresh modes the
SSD1680-family controller supports, so they can be compared directly on real
hardware to decide which one the app should actually use. Every pin, SPI
setting, and command byte below is copied from the real driver —
DEV_BUILD/display/waveshare/epd2in9b_v4.py and epdconfig.py — so nothing
tested here can diverge from what the app actually runs. If those files
change, update this to match.

Usage:
    python3 test_display.py slide1   # draws "Slide 1"        (full refresh,    0xF7)
    python3 test_display.py slow     # draws "Reset Slow"      (full refresh,    0xF7)
    python3 test_display.py fast     # draws "Reset Fast"      (fast refresh,    0xC7)
    python3 test_display.py base     # draws "Reset Base"      (base refresh,    0xF4)
    python3 test_display.py partial  # draws "Reset Partial"   (partial refresh, 0x1C)

Each run is independent — init() re-runs every time, then draws with
whichever refresh mode that slide uses. Run them one at a time and watch
the panel between runs.
"""

import sys
import time

# ── Pins / SPI — must match DEV_BUILD/display/waveshare/epdconfig.py ────
RST_PIN = 17
DC_PIN = 25
CS_PIN = 8
BUSY_PIN = 24
SPI_SPEED_HZ = 1_000_000

EPD_WIDTH = 128
EPD_HEIGHT = 296

try:
    import RPi.GPIO as GPIO
    import spidev
    HW = True
except ImportError:
    HW = False
    print("!! RPi.GPIO/spidev not available — simulation mode, no real hardware access")

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
    GPIO.setup(BUSY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode = 0b00


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


# ── EPD driver — mirrors epd2in9b_v4.py exactly ──────────────────────

def reset():
    digital_write(RST_PIN, 1)
    delay_ms(200)
    digital_write(RST_PIN, 0)
    delay_ms(2)
    digital_write(RST_PIN, 1)
    delay_ms(200)


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


def wait_busy():
    cmd(0x71)
    while digital_read(BUSY_PIN) == 1:
        delay_ms(200)


def turn_on():
    """Full refresh — visible black/white flash."""
    cmd(0x22); data(0xF7)
    cmd(0x20)
    wait_busy()


def turn_on_fast():
    """Fast refresh — shorter waveform."""
    cmd(0x22); data(0xC7)
    cmd(0x20)
    wait_busy()


def turn_on_base():
    """'Base' refresh — used internally by Waveshare's own driver as a
    reference frame before partial updates, not really meant as a standalone
    refresh. Included anyway to see how it actually behaves here."""
    cmd(0x22); data(0xF4)
    cmd(0x20)
    wait_busy()


def turn_on_partial():
    """'Partial' refresh — designed for a restricted sub-region (set via
    0x44/0x45 before writing), tested here against a full-screen write like
    the other modes since that's what the app actually does on every update
    (always redraws the whole page, never just a region)."""
    cmd(0x22); data(0x1C)
    cmd(0x20)
    wait_busy()


def init():
    module_init()
    reset()
    wait_busy()
    cmd(0x12)   # SWRESET
    wait_busy()

    cmd(0x01); data((EPD_HEIGHT - 1) % 256); data((EPD_HEIGHT - 1) // 256); data(0x00)
    cmd(0x11); data(0x03)
    cmd(0x44); data(0x00); data(EPD_WIDTH // 8 - 1)
    cmd(0x45); data(0x00); data(0x00); data((EPD_HEIGHT - 1) % 256); data((EPD_HEIGHT - 1) // 256)
    cmd(0x3C); data(0x05)
    cmd(0x21); data(0x00); data(0x80)
    cmd(0x18); data(0x80)
    cmd(0x4E); data(0x00)
    cmd(0x4F); data(0x00); data(0x00)
    wait_busy()


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


# ── Test image + slides ────────────────────────────────────────────────

def build_image(text):
    from PIL import Image, ImageDraw, ImageFont
    w, h = 296, 128
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2, (h - th) / 2 - bbox[1]), text, font=font, fill=0)
    return image


def send_image(image):
    buf = getbuffer(image)
    blank_red = [0x00] * (EPD_WIDTH // 8 * EPD_HEIGHT)
    cmd(0x24); data_block(buf)
    cmd(0x26); data_block(blank_red)


SLIDES = {
    "slide1": ("Slide 1", turn_on),
    "slow": ("Reset Slow", turn_on),
    "fast": ("Reset Fast", turn_on_fast),
    "base": ("Reset Base", turn_on_base),
    "partial": ("Reset Partial", turn_on_partial),
}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "slide1"
    if mode not in SLIDES:
        print(f"Unknown mode '{mode}' — use: {', '.join(SLIDES)}")
        sys.exit(1)

    text, refresh_fn = SLIDES[mode]
    print(f"Drawing '{text}' using {refresh_fn.__name__}()...")
    init()
    send_image(build_image(text))
    refresh_fn()
    module_exit()
    print("Done.")
