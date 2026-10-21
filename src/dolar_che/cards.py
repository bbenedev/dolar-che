"""Discord cards (embeds) for each reply. Built from core's data; no network here."""

from __future__ import annotations

from datetime import datetime

import discord

from .core import (
    CURRENCY_NAMES,
    CURRENCY_ORDER,
    PERIODS,
    SHORT_NAMES,
    DayClose,
    Move,
    Quote,
    Row,
    arrow,
    average,
    money,
    percent,
    signed_money,
    signed_percent,
    when,
)

CELESTE = 0x74ACDF
UP = 0x3FD39A
DOWN = 0xF0705A
SOURCE_RATES = "Fuente: dolarapi.com"
SOURCE_HISTORY = "Fuente: argentinadatos.com"


def _color(change: float | None) -> int:
    if change is None or change == 0:
        return CELESTE
    return UP if change > 0 else DOWN


def _footer(source: str, tip: str) -> str:
    return f"{source}  ·  💡 {tip}"


def dolar(rows: list[Row], gap: float | None, stamps: str, now: datetime) -> discord.Embed:
    blue = next((r for r in rows if r.key == "blue"), None)
    e = discord.Embed(title="💵 El dólar ahora", color=_color(blue.change if blue else None))
    lines = []
    if gap is not None:
        lines.append(f"Brecha blue / oficial: **{percent(gap)}**")
    lines.append(f"🕒 {stamps}")
    # Say once which close the changes compare against, so each rate fits in three short lines.
    prev_days = {r.prev.day for r in rows if r.prev is not None}
    if len(prev_days) == 1:
        lines.append(f"Variación contra el cierre del {next(iter(prev_days)):%d/%m}")
    e.description = "\n".join(lines)
    for r in rows:
        change = r.change_text(with_date=len(prev_days) > 1) or "sin dato del día anterior"
        e.add_field(
            name=SHORT_NAMES.get(r.key, r.name),
            value=f"Compra {money(r.buy)}\nVenta **{money(r.sell)}**\n{change}",
            inline=True,
        )
    # Discord shows three per row; pad so the last row lines up.
    while len(e.fields) % 3:
        e.add_field(name="\u200b", value="\u200b", inline=True)
    e.set_footer(
        text=_footer(
            SOURCE_RATES, "/historial muestra el gráfico · /alerta te avisa cuando llegue a tu número"
        )
    )
    return e


def history(rate: str, days: int, window: list[DayClose]) -> discord.Embed:
    first, last = window[0], window[-1]
    change = last.sell - first.sell
    pct = (last.sell / first.sell - 1) * 100 if first.sell else 0.0
    low = min(window, key=lambda h: h.sell)
    high = max(window, key=lambda h: h.sell)
    e = discord.Embed(
        title=f"📈 Dólar {SHORT_NAMES.get(rate, rate)} · últimos {days} días",
        description=f"**{money(last.sell)}** {arrow(change)} {signed_money(change)} ({signed_percent(pct)}) desde el {first.day:%d/%m/%Y}",
        color=_color(change),
    )
    # Over a long range "22/10" is ambiguous: add the year.
    fmt = "%d/%m/%y" if (last.day - first.day).days > 120 else "%d/%m"
    e.add_field(name="Al inicio", value=f"{money(first.sell)}\n{first.day:{fmt}}", inline=True)
    e.add_field(name="Hoy", value=f"{money(last.sell)}\n{last.day:{fmt}}", inline=True)
    e.add_field(name="Promedio", value=money(average(window)), inline=True)
    e.add_field(name="Mínimo", value=f"{money(low.sell)}\n{low.day:{fmt}}", inline=True)
    e.add_field(name="Máximo", value=f"{money(high.sell)}\n{high.day:{fmt}}", inline=True)
    e.add_field(name="Compra hoy", value=money(last.buy), inline=True)
    # The chart goes as a normal upload under the card, not inside it: Discord hides images
    # inside cards for people who turned off link previews, and uploads are always shown.
    other = 365 if days < 365 else 30
    e.set_footer(
        text=_footer(
            SOURCE_HISTORY + " · precio de venta", f"probá /historial dias:{other} para otro período"
        )
    )
    return e


def summary(period: int, moves: list[tuple[str, Move]]) -> discord.Embed:
    e = discord.Embed(title=f"🧉 Cómo se movió el dólar · {PERIODS[period]}", color=CELESTE)
    for key, m in moves:
        e.add_field(
            name=f"{arrow(m.change)} {SHORT_NAMES.get(key, key)}",
            value=(
                f"**{money(m.last.sell)}**\n{signed_money(m.change)} ({signed_percent(m.change_pct)})\n"
                f"desde {money(m.first.sell)} el {m.first.day:%d/%m}"
            ),
            inline=True,
        )
    while len(e.fields) % 3:
        e.add_field(name="\u200b", value="\u200b", inline=True)
    e.set_footer(text=_footer(SOURCE_HISTORY, "/historial te muestra el gráfico de cualquiera de estos"))
    return e


def currencies(quotes: dict[str, Quote], now: datetime) -> discord.Embed:
    e = discord.Embed(title="🌎 Otras monedas, en pesos", color=CELESTE)
    stamp = max((q.updated for q in quotes.values() if q.updated), default="")
    e.description = (
        f"Cotización oficial · 🕒 {when(stamp, now)} (hora argentina)" if stamp else "Cotización oficial"
    )
    for code in CURRENCY_ORDER:
        q = quotes.get(code)
        if q:
            d = 4 if q.sell < 10 else 2
            e.add_field(
                name=CURRENCY_NAMES[code],
                value=f"Compra {money(q.buy, d)}\nVenta **{money(q.sell, d)}**",
                inline=True,
            )
    e.set_footer(text=_footer(SOURCE_RATES, "/convertir pasa dólares a pesos y al revés"))
    return e


def simple(title: str, text: str, tip: str, source: str = SOURCE_RATES) -> discord.Embed:
    e = discord.Embed(title=title, description=text, color=CELESTE)
    e.set_footer(text=_footer(source, tip))
    return e


def problem(text: str) -> discord.Embed:
    return discord.Embed(description=f"😕 {text}", color=DOWN)
