"""Default page template — used for any display model without a dedicated
template file. Sizes and positions itself from the driver's actual
dimensions so it's reasonable on any screen shape, but a model-specific
template (see epd2in9b_v4.py / epd1in54_v2.py for examples) will generally
look better since it can be designed for that exact aspect ratio."""

from ._shared import load_font, fit_font, FONT_BOLD, FONT_REGULAR


def draw_loading_page(driver):
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w - 1, h - 1), outline=0)

    margin = 8
    text = "Loading..."
    font = fit_font(draw, text, FONT_BOLD, w - 2 * margin, 22)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2, (h - th) / 2 - bbox[1]), text, font=font, fill=0)
    return image


def draw_status_page(driver, title: str, rows: list[tuple[str, str]]):
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    margin = 8
    label_value_gap = 8
    row_height = 22
    divider_gap = 10

    content_width = w - 2 * margin
    title_font = fit_font(draw, title, FONT_BOLD, content_width, 16)
    tbbox = draw.textbbox((0, 0), title, font=title_font)
    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]

    block_h = th + divider_gap + len(rows) * row_height
    top = max(margin, (h - block_h) / 2)

    draw.text(((w - tw) / 2, top), title, font=title_font, fill=0)
    divider_y = top + th + divider_gap / 2
    draw.line((margin, divider_y, w - margin, divider_y), fill=0, width=1)

    y = divider_y + divider_gap / 2 + 4
    label_font = load_font(FONT_BOLD, 13)
    for label, value in rows:
        lbbox = draw.textbbox((0, 0), label, font=label_font)
        lw = lbbox[2] - lbbox[0]
        value_font = fit_font(draw, value, FONT_REGULAR, content_width - lw - label_value_gap, 13, min_size=8)
        vbbox = draw.textbbox((0, 0), value, font=value_font)
        vw = vbbox[2] - vbbox[0]
        row_w = lw + label_value_gap + vw
        x = (w - row_w) / 2
        draw.text((x, y), label, font=label_font, fill=0)
        draw.text((x + lw + label_value_gap, y), value, font=value_font, fill=0)
        y += row_height

    return image
