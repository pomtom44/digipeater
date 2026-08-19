"""Layout for the generic 1.54" square e-paper (200x200): each row stacks label above value, both centered."""

from ._shared import load_font, fit_font, FONT_BOLD, FONT_REGULAR
# Reuse default.py's generic column-table, icon+text, and station-card layouts rather than duplicating them.
from .default import draw_table_page, draw_symbol_page, draw_station_page  # noqa: F401

MARGIN = 14
LABEL_ROW_H = 18
VALUE_ROW_H = 26


def draw_loading_page(driver, text: str = "Loading..."):
    """Full-screen bordered centered text."""
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, w - 5, h - 5), outline=0)

    font = fit_font(draw, text, FONT_BOLD, w - 2 * MARGIN, 20)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2, (h - th) / 2 - bbox[1]), text, font=font, fill=0)
    return image


def draw_status_page(driver, title: str, rows: list[tuple[str, str]]):
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    content_width = w - 2 * MARGIN

    title_font = fit_font(draw, title, FONT_BOLD, content_width, 20)
    label_font = load_font(FONT_BOLD, 13)

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

        value_font = fit_font(draw, value, FONT_REGULAR, content_width, 15, min_size=9)
        vbbox = draw.textbbox((0, 0), value, font=value_font)
        vw = vbbox[2] - vbbox[0]
        draw.text(((w - vw) / 2, y), value, font=value_font, fill=0)
        y += VALUE_ROW_H

    return image
