"""Draws the /historial chart as a PNG, with Pillow. Pure: data in, bytes out."""

from __future__ import annotations

import functools
import io
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from .core import DayClose, arrow, average, money, signed_money, signed_percent

WIDTH, HEIGHT = 1000, 520
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 96, 40, 112, 78
# Argentine flag light blue for the line, on a dark background that suits Discord.
BG = (30, 33, 40)
GRID = (52, 58, 70)
TEXT = (230, 234, 240)
MUTED = (150, 158, 170)
SELL = (116, 172, 223)
BUY = (190, 214, 238)
BAND = (116, 172, 223, 40)
SUN = (246, 180, 14)
UP = (63, 211, 154)
DOWN = (240, 112, 90)
AVG = (150, 158, 170)

# Pillow's built-in font has no accented letters ("Dólar" came out as "D□lar"), so a system
# font is preferred. These cover Windows, most Linux servers and macOS.
REGULAR = ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf", "Helvetica.ttc")
BOLD = ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf", *REGULAR)


@functools.cache
def _font(size: int, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in BOLD if bold else REGULAR:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _safe(text: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont) -> str:
    """Without a system font, drop accents rather than draw empty boxes."""
    if isinstance(font, ImageFont.FreeTypeFont) and getattr(font, "path", ""):
        return text
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _label(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, color, anchor: str) -> None:
    """A value tag with a dark box behind it, so it stays readable over the lines."""
    font = _font(14, bold=True)
    box = draw.textbbox(xy, text, font=font, anchor=anchor)
    draw.rounded_rectangle([box[0] - 6, box[1] - 4, box[2] + 6, box[3] + 4], radius=6, fill=(20, 22, 28, 230))
    draw.text(xy, text, fill=color, font=font, anchor=anchor)


def render(window: list[DayClose], title: str, footer: str = "") -> bytes:
    """Buy and sell lines with the spread between them, average, low, high and the change."""
    if len(window) < 2:
        raise ValueError("a chart needs at least two days")
    sells = [h.sell for h in window]
    buys = [h.buy for h in window]
    low, high = min(min(buys), min(sells)), max(max(buys), max(sells))
    if high == low:  # a flat line still needs a vertical range
        low, high = low - 1, high + 1
    span = high - low
    low, high = low - span * 0.12, high + span * 0.12

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    bottom = PAD_TOP + plot_h

    def x_at(i: int) -> float:
        return PAD_LEFT + plot_w * i / (len(window) - 1)

    def y_at(price: float) -> float:
        return PAD_TOP + plot_h * (1 - (price - low) / (high - low))

    # Header: title, then the change in the period in green or red.
    first, last = window[0], window[-1]
    change = last.sell - first.sell
    pct = (last.sell / first.sell - 1) * 100 if first.sell else 0.0
    draw.text((PAD_LEFT, 26), _safe(title, _font(26, True)), fill=TEXT, font=_font(26, True))
    color = UP if change > 0 else DOWN if change < 0 else MUTED
    summary = (
        f"{money(last.sell)}  {arrow(change)} {signed_money(change)} ({signed_percent(pct)})"
        f"  desde el {first.day:%d/%m/%Y}"
    )
    draw.text((PAD_LEFT, 66), _safe(summary, _font(18)), fill=color, font=_font(18))

    # Grid with prices.
    for k in range(6):
        value = low + (high - low) * k / 5
        y = y_at(value)
        draw.line([(PAD_LEFT, y), (WIDTH - PAD_RIGHT, y)], fill=GRID, width=1)
        draw.text((PAD_LEFT - 10, y), money(value, 0), fill=MUTED, font=_font(13), anchor="rm")

    sell_pts = [(x_at(i), y_at(p)) for i, p in enumerate(sells)]
    buy_pts = [(x_at(i), y_at(p)) for i, p in enumerate(buys)]
    draw.polygon([*sell_pts, *reversed(buy_pts)], fill=BAND)

    # Average of the selling price, dashed.
    avg = average(window)
    y_avg = y_at(avg)
    x = PAD_LEFT
    while x < WIDTH - PAD_RIGHT:
        draw.line([(x, y_avg), (min(x + 8, WIDTH - PAD_RIGHT), y_avg)], fill=AVG, width=1)
        x += 14
    draw.line(buy_pts, fill=BUY, width=2, joint="curve")
    draw.line(sell_pts, fill=SELL, width=3, joint="curve")
    # Drawn after the lines, on its own box, so a line never crosses it.
    _label(draw, (PAD_LEFT + 8, y_avg), _safe(f"promedio {money(avg, 0)}", _font(14, True)), AVG, "lm")

    # Low and high of the selling price, marked and labelled.
    i_low = min(range(len(sells)), key=lambda i: sells[i])
    i_high = max(range(len(sells)), key=lambda i: sells[i])
    for i, color, below in ((i_high, UP, False), (i_low, DOWN, True)):
        px, py = sell_pts[i]
        draw.ellipse([px - 5, py - 5, px + 5, py + 5], fill=color)
        text = f"{'máx' if not below else 'mín'} {money(sells[i], 0)} · {window[i].day:%d/%m}"
        anchor = (
            "m"
            if 0.15 < i / (len(window) - 1) < 0.85
            else "l"
            if i == 0 or i / (len(window) - 1) <= 0.15
            else "r"
        ) + ("t" if below else "b")
        _label(draw, (px, py + 12 if below else py - 12), _safe(text, _font(14, True)), color, anchor)

    # Today.
    lx, ly = sell_pts[-1]
    draw.ellipse([lx - 7, ly - 7, lx + 7, ly + 7], fill=SUN, outline=BG, width=2)

    # Dates along the bottom.
    ticks = sorted({round(k * (len(window) - 1) / 5) for k in range(6)})
    long_range = (window[-1].day - window[0].day).days > 120
    for i in ticks:
        label = f"{window[i].day:%d/%m/%y}" if long_range else f"{window[i].day:%d/%m}"
        draw.text((x_at(i), bottom + 12), label, fill=MUTED, font=_font(13), anchor="mt")

    # Legend and footer.
    ly0 = HEIGHT - 26
    draw.line([(PAD_LEFT, ly0), (PAD_LEFT + 22, ly0)], fill=SELL, width=3)
    draw.text((PAD_LEFT + 28, ly0), "venta", fill=MUTED, font=_font(13), anchor="lm")
    draw.line([(PAD_LEFT + 90, ly0), (PAD_LEFT + 112, ly0)], fill=BUY, width=2)
    draw.text((PAD_LEFT + 118, ly0), "compra", fill=MUTED, font=_font(13), anchor="lm")
    if footer:
        draw.text((WIDTH - PAD_RIGHT, ly0), _safe(footer, _font(12)), fill=MUTED, font=_font(12), anchor="rm")

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
