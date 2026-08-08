"""Layout for the Waveshare Pico-ePaper-2.9-B (296×128 — wide, short).

Plenty of horizontal room and not much vertical, so each row sits as a
single centered "Label: value" line rather than stacking — see
epd1in54_v2.py for the square-panel equivalent, which stacks instead.
"""

from ._shared import fit_font, FONT_BOLD, FONT_REGULAR

MARGIN = 10
LABEL_VALUE_GAP = 8


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
    content_width = w - 2 * MARGIN
    row_height = 24

    title_font = fit_font(draw, title, FONT_BOLD, content_width, 18)

    tbbox = draw.textbbox((0, 0), title, font=title_font)
    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]

    block_h = th + 14 + len(rows) * row_height
    top = max(MARGIN, (h - block_h) / 2)

    draw.text(((w - tw) / 2, top), title, font=title_font, fill=0)
    divider_y = top + th + 7
    draw.line((MARGIN, divider_y, w - MARGIN, divider_y), fill=0, width=1)

    # Labels right-align and values left-align against a shared center
    # column (split at the gap around the colon) instead of each row
    # centering independently — otherwise the colon position drifts row to
    # row depending on how wide that row's label+value happens to be.
    center_x = w / 2
    half_gap = LABEL_VALUE_GAP / 2
    label_max_w = center_x - half_gap - MARGIN
    value_max_w = w - MARGIN - (center_x + half_gap)

    y = divider_y + 11
    for label, value in rows:
        row_label_font = fit_font(draw, label, FONT_BOLD, label_max_w, 14, min_size=9)
        lbbox = draw.textbbox((0, 0), label, font=row_label_font)
        lw = lbbox[2] - lbbox[0]
        value_font = fit_font(draw, value, FONT_REGULAR, value_max_w, 14, min_size=9)
        draw.text((center_x - half_gap - lw, y), label, font=row_label_font, fill=0)
        draw.text((center_x + half_gap, y), value, font=value_font, fill=0)
        y += row_height

    return image
