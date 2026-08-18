"""Layout for the Waveshare Pico-ePaper-2.9-B (296×128 — wide, short).

Plenty of horizontal room and not much vertical, so each row sits as a
single centered "Label: value" line rather than stacking — see
epd1in54_v2.py for the square-panel equivalent, which stacks instead.
"""

from ._shared import fit_font, FONT_BOLD, FONT_REGULAR
# Column-table, icon+text, and station-card layouts (currently just the
# Last Beacon, Symbol, and Last Heard pages) aren't worth a bespoke
# version of on every model yet, only one page each needs them: reuse
# default.py's generic versions here rather than duplicating them.
from .default import draw_table_page, draw_symbol_page, draw_station_page  # noqa: F401

MARGIN = 10
LABEL_VALUE_GAP = 8


def draw_loading_page(driver, text: str = "Loading..."):
    """Full-screen bordered centered text — used both for the boot-time
    loading indicator and, with a different string, the normal-boot
    "Digipeater" idle screen."""
    from PIL import Image, ImageDraw
    w, h = driver.width, driver.height
    image = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w - 1, h - 1), outline=0)

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

    # Title/divider always at the same fixed position (MARGIN), not
    # centered against how tall this particular page's content happens to
    # be: otherwise the title jumps up and down page to page as rotation
    # cycles through pages with different row counts, especially visible
    # on this panel since it has no fast refresh (every tick is already a
    # full visible flash, see this module's own docstring).
    draw.text(((w - tw) / 2, MARGIN), title, font=title_font, fill=0)
    divider_y = MARGIN + th + 7
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
