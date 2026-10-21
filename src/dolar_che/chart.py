"""Draws the /historial chart as a PNG, with Pillow. Pure: data in, bytes out."""

from __future__ import annotations

import functools
import io
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from .core import DayClose, money

WIDTH, HEIGHT = 900, 420
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 110, 30, 70, 50
# Argentine flag light blue for the line, on a dark background that suits Discord.
BG = (30, 33, 40)
GRID = (60, 66, 78)
TEXT = (220, 225, 232)
MUTED = (150, 158, 170)
LINE = (116, 172, 223)
FILL = (116, 172, 223, 45)
SUN = (246, 180, 14)


# Pillow's built-in font has no accented letters ("Dólar" came out as "D□lar"), so a system
# font is preferred. These cover Windows, most Linux servers and macOS.
SYSTEM_FONTS = ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf", "Helvetica.ttc")


@functools.cache
def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in SYSTEM_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _has_accents(font: ImageFont.ImageFont | ImageFont.FreeTypeFont) -> bool:
    return isinstance(font, ImageFont.FreeTypeFont) and getattr(font, "path", "") != ""


def _safe(text: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont) -> str:
    """Without a system font, drop accents rather than draw empty boxes."""
    if _has_accents(font):
        return text
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def render(window: list[DayClose], title: str) -> bytes:
    """Line chart of the selling price, one point per day."""
    if len(window) < 2:
        raise ValueError("a chart needs at least two days")
    prices = [h.sell for h in window]
    low, high = min(prices), max(prices)
    if high == low:  # a flat line still needs a vertical range
        low, high = low - 1, high + 1
    span = high - low
    low, high = low - span * 0.08, high + span * 0.08

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM

    def xy(i: int, price: float) -> tuple[float, float]:
        x = PAD_LEFT + plot_w * i / (len(window) - 1)
        y = PAD_TOP + plot_h * (1 - (price - low) / (high - low))
        return x, y

    draw.text((PAD_LEFT, 22), _safe(title, _font(22)), fill=TEXT, font=_font(22))

    for k in range(5):
        value = low + (high - low) * k / 4
        _, y = xy(0, value)
        draw.line([(PAD_LEFT, y), (WIDTH - PAD_RIGHT, y)], fill=GRID, width=1)
        draw.text((PAD_LEFT - 12, y), money(value, 0), fill=MUTED, font=_font(14), anchor="rm")

    points = [xy(i, p) for i, p in enumerate(prices)]
    bottom = PAD_TOP + plot_h
    draw.polygon([(points[0][0], bottom), *points, (points[-1][0], bottom)], fill=FILL)
    draw.line(points, fill=LINE, width=3, joint="curve")

    last_x, last_y = points[-1]
    draw.ellipse([last_x - 6, last_y - 6, last_x + 6, last_y + 6], fill=SUN)
    draw.text((last_x - 10, last_y - 12), money(prices[-1], 0), fill=TEXT, font=_font(16), anchor="rb")

    for i in sorted({0, len(window) // 2, len(window) - 1}):
        x, _ = xy(i, prices[i])
        draw.text((x, bottom + 14), f"{window[i].day:%d/%m}", fill=MUTED, font=_font(14), anchor="mt")

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
