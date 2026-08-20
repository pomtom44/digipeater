"""Default page template for any display model without a dedicated template file, sized from the driver's dimensions."""

from ._shared import load_font, fit_font, wrap_text, FONT_BOLD, FONT_REGULAR


def draw_symbol_page(driver, title: str, symbol_image, comment: str, *, title_size: int = 16, comment_size: int = 12):
    """Icon centered below the title, with the comment word-wrapped underneath."""
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    margin = 8
    divider_gap = 8

    content_width = w - 2 * margin
    title_font = fit_font(draw, title, FONT_BOLD, content_width, title_size)
    tbbox = draw.textbbox((0, 0), title, font=title_font)
    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]
    draw.text(((w - tw) / 2, margin), title, font=title_font, fill=0)
    divider_y = margin + th + divider_gap / 2
    draw.line((margin, divider_y, w - margin, divider_y), fill=0, width=1)

    icon_top = divider_y + divider_gap
    icon_x = (w - symbol_image.width) / 2
    image.paste(symbol_image, (int(icon_x), int(icon_top)))

    comment_font = load_font(FONT_REGULAR, comment_size)
    lines = wrap_text(draw, comment or "(no comment set)", comment_font, content_width)
    line_height = comment_size + 3
    y = icon_top + symbol_image.height + 6
    for line in lines:
        if y + line_height > h - margin:
            break
        lbbox = draw.textbbox((0, 0), line, font=comment_font)
        lw = lbbox[2] - lbbox[0]
        draw.text(((w - lw) / 2, y), line, font=comment_font, fill=0)
        y += line_height

    return image


def draw_station_page(
    driver, title: str, symbol_image, callsign: str, lat: str, lon: str, comment: str,
    *, title_size: int = 16, call_size: int = 18, text_size: int = 12,
):
    """Icon and callsign side by side, a compact Lat/Lon line, then wrapped comment text underneath. symbol_image may be None to skip the icon."""
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    margin = 8
    divider_gap = 6

    content_width = w - 2 * margin
    title_font = fit_font(draw, title, FONT_BOLD, content_width, title_size)
    tbbox = draw.textbbox((0, 0), title, font=title_font)
    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]
    draw.text(((w - tw) / 2, margin), title, font=title_font, fill=0)
    divider_y = margin + th + divider_gap / 2
    draw.line((margin, divider_y, w - margin, divider_y), fill=0, width=1)

    row_top = divider_y + divider_gap
    icon_w = icon_h = 0
    if symbol_image is not None:
        image.paste(symbol_image, (margin, int(row_top)))
        icon_w, icon_h = symbol_image.width, symbol_image.height

    call_max_w = content_width - icon_w - (8 if icon_w else 0)
    call_font = fit_font(draw, callsign, FONT_BOLD, call_max_w, call_size)
    cbbox = draw.textbbox((0, 0), callsign, font=call_font)
    ch = cbbox[3] - cbbox[1]
    call_x = margin + icon_w + (8 if icon_w else 0)
    call_y = row_top + (icon_h - ch) / 2 if icon_h else row_top
    draw.text((call_x, call_y), callsign, font=call_font, fill=0)

    y = row_top + max(icon_h, ch) + 6
    loc_text = f"Lat {lat}  Lon {lon}"
    loc_font = fit_font(draw, loc_text, FONT_REGULAR, content_width, text_size, min_size=8)
    lbbox = draw.textbbox((0, 0), loc_text, font=loc_font)
    lw = lbbox[2] - lbbox[0]
    draw.text(((w - lw) / 2, y), loc_text, font=loc_font, fill=0)
    y += text_size + 6

    comment_font = load_font(FONT_REGULAR, text_size)
    lines = wrap_text(draw, comment or "-", comment_font, content_width)
    line_height = text_size + 3
    for line in lines:
        if y + line_height > h - margin:
            break
        lbbox2 = draw.textbbox((0, 0), line, font=comment_font)
        lw2 = lbbox2[2] - lbbox2[0]
        draw.text(((w - lw2) / 2, y), line, font=comment_font, fill=0)
        y += line_height

    return image


def draw_loading_page(driver, text: str = "Loading..."):
    """Full-screen bordered centered text."""
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w - 1, h - 1), outline=0)

    margin = 8
    font = fit_font(draw, text, FONT_BOLD, w - 2 * margin, 22)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2, (h - th) / 2 - bbox[1]), text, font=font, fill=0)
    return image


def draw_table_page(
    driver, title: str, headers: list[str], rows: list[tuple[str, list[str]]],
    *, title_size: int = 16, header_size: int = 11, value_size: int = 12, row_height: int = 20,
):
    """A small column table: header row of column labels above data rows of (row_label, values)."""
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    margin = 8
    divider_gap = 10

    content_width = w - 2 * margin
    title_font = fit_font(draw, title, FONT_BOLD, content_width, title_size)
    tbbox = draw.textbbox((0, 0), title, font=title_font)
    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]

    label_font = load_font(FONT_BOLD, value_size)
    header_font = load_font(FONT_REGULAR, header_size)
    value_font = load_font(FONT_REGULAR, value_size)

    label_col_w = 40
    for row_label, _ in rows:
        lbbox = draw.textbbox((0, 0), row_label, font=label_font)
        label_col_w = max(label_col_w, lbbox[2] - lbbox[0] + 12)
    col_count = max(len(headers), 1)
    col_w = (content_width - label_col_w) / col_count
    col_x = [margin + label_col_w + col_w * (i + 0.5) for i in range(col_count)]

    # Title/divider always at the same fixed position, so it doesn't jump between pages with different row counts.
    draw.text(((w - tw) / 2, margin), title, font=title_font, fill=0)
    divider_y = margin + th + divider_gap / 2
    draw.line((margin, divider_y, w - margin, divider_y), fill=0, width=1)

    y = divider_y + divider_gap / 2 + 4
    for i, header_text in enumerate(headers):
        hbbox = draw.textbbox((0, 0), header_text, font=header_font)
        hw = hbbox[2] - hbbox[0]
        draw.text((col_x[i] - hw / 2, y), header_text, font=header_font, fill=0)
    y += row_height

    for row_label, values in rows:
        draw.text((margin, y), row_label, font=label_font, fill=0)
        if len(values) == 1 and col_count > 1:
            draw.text((margin + label_col_w, y), values[0], font=value_font, fill=0)
        else:
            for i, value in enumerate(values):
                vbbox = draw.textbbox((0, 0), value, font=value_font)
                vw = vbbox[2] - vbbox[0]
                draw.text((col_x[i] - vw / 2, y), value, font=value_font, fill=0)
        y += row_height

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

    # Title/divider always at the same fixed position, see draw_table_page above.
    draw.text(((w - tw) / 2, margin), title, font=title_font, fill=0)
    divider_y = margin + th + divider_gap / 2
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
