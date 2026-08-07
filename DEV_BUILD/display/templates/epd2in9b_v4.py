"""Layout for the Waveshare Pico-ePaper-2.9-B (296×128 — wide, short).

Plenty of horizontal room and not much vertical, so rows sit label+value on
a single line with a fixed label column, left-aligned rather than centered.
"""

from ._shared import load_font, fit_font, FONT_BOLD, FONT_REGULAR

MARGIN = 10
LABEL_COL = 90


def draw_loading_page(driver):
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w - 1, h - 1), outline=0)

    text = "Loading..."
    font = fit_font(draw, text, FONT_BOLD, w - 2 * MARGIN, 26)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2, (h - th) / 2 - bbox[1]), text, font=font, fill=0)
    return image


def draw_status_page(driver, title: str, rows: list[tuple[str, str]]):
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)

    title_font = load_font(FONT_BOLD, 18)
    label_font = load_font(FONT_BOLD, 14)

    draw.text((MARGIN, 6), title, font=title_font, fill=0)
    draw.line((MARGIN, 30, w - MARGIN, 30), fill=0, width=1)

    y = 40
    row_height = 24
    value_max_width = w - MARGIN - (MARGIN + LABEL_COL)
    for label, value in rows:
        draw.text((MARGIN, y), label, font=label_font, fill=0)
        value_font = fit_font(draw, value, FONT_REGULAR, value_max_width, 14, min_size=9)
        draw.text((MARGIN + LABEL_COL, y), value, font=value_font, fill=0)
        y += row_height

    return image
