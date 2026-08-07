"""Shared helpers for page templates — font loading with a fit-to-width
fallback so text can't overflow whatever screen it's drawn on."""

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
FONT_BOLD = f"{FONT_DIR}/DejaVuSans-Bold.ttf"
FONT_REGULAR = f"{FONT_DIR}/DejaVuSans.ttf"


def load_font(path: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def fit_font(draw, text: str, path: str, max_width: int, start_size: int, min_size: int = 9):
    """Largest font size (down to min_size) at which text fits within max_width."""
    size = start_size
    while size > min_size:
        font = load_font(path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 1
    return load_font(path, min_size)
