"""Layout for the generic 1.54" square e-paper (200x200): each row stacks label above value, both centered."""

from ._shared import load_font, fit_font, FONT_BOLD, FONT_REGULAR
from . import default

MARGIN = 12
LABEL_ROW_H = 20
VALUE_ROW_H = 27


def draw_table_page(driver, title, headers, rows):
    """Same layout as default.py, larger fonts and a header matched to the other pages on this panel."""
    return default.draw_table_page(
        driver, title, headers, rows, title_size=20, header_size=16, value_size=17, row_height=28,
        margin=MARGIN, divider_gap=20,
    )


def draw_symbol_page(driver, title, symbol_image, comment):
    """Same layout as default.py, larger fonts and a header matched to the other pages on this panel."""
    return default.draw_symbol_page(
        driver, title, symbol_image, comment, title_size=20, comment_size=17, margin=MARGIN, divider_gap=20,
    )


def draw_station_page(driver, title, symbol_image, callsign, lat, lon, comment):
    """Same layout as default.py, larger fonts and a header matched to the other pages on this panel."""
    return default.draw_station_page(
        driver, title, symbol_image, callsign, lat, lon, comment, title_size=20, call_size=22, text_size=17,
        margin=MARGIN, divider_gap=20,
    )


def draw_loading_page(driver, title: str = "Digipeater", subtitle: str = "Loading"):
    """Same splash as default.py, bigger fonts and an inset border matched to this panel."""
    return default.draw_loading_page(
        driver, title, subtitle, margin=MARGIN, border_inset=4, title_size=26, subtitle_size=18, gap=8,
    )


def draw_status_page(driver, title: str, rows: list[tuple[str, str]]):
    """Title bar over a simple key/value row list, sized for this panel."""
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    content_width = w - 2 * MARGIN

    title_font = fit_font(draw, title, FONT_BOLD, content_width, 20)
    label_font = load_font(FONT_BOLD, 16)

    tbbox = draw.textbbox((0, 0), title, font=title_font)
    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]

    # Title/divider always at the same fixed position, so it doesn't jump between pages with different row counts.
    draw.text(((w - tw) / 2, MARGIN), title, font=title_font, fill=0)
    divider_y = MARGIN + th + 10
    draw.line((MARGIN, divider_y, w - MARGIN, divider_y), fill=0, width=1)

    y = divider_y + 14
    for label, value in rows:
        lbbox = draw.textbbox((0, 0), label, font=label_font)
        lw = lbbox[2] - lbbox[0]
        draw.text(((w - lw) / 2, y), label, font=label_font, fill=0)
        y += LABEL_ROW_H

        value_font = fit_font(draw, value, FONT_REGULAR, content_width, 18, min_size=10)
        vbbox = draw.textbbox((0, 0), value, font=value_font)
        vw = vbbox[2] - vbbox[0]
        draw.text(((w - vw) / 2, y), value, font=value_font, fill=0)
        y += VALUE_ROW_H

    return image
