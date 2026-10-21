"""Pure logic: read the quotes, format them, convert, history, alerts. No network, no Discord.

Everything the user reads is in Argentine Spanish ("criollo pero claro").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# Argentina has used UTC-3 all year since 2009, so a fixed offset avoids a time zone database.
ART = timezone(timedelta(hours=-3), "ART")

# Order shown to users. Keys are the "casa" ids used by the API.
RATE_ORDER = ("oficial", "blue", "bolsa", "contadoconliqui", "mayorista", "cripto", "tarjeta")
SHORT_NAMES = {
    "oficial": "Oficial",
    "blue": "Blue",
    "bolsa": "MEP",
    "contadoconliqui": "CCL",
    "mayorista": "Mayorista",
    "cripto": "Cripto",
    "tarjeta": "Tarjeta",
}
# What people type -> API id.
RATE_ALIASES = {
    "oficial": "oficial",
    "blue": "blue",
    "mep": "bolsa",
    "bolsa": "bolsa",
    "ccl": "contadoconliqui",
    "contadoconliqui": "contadoconliqui",
    "mayorista": "mayorista",
    "cripto": "cripto",
    "tarjeta": "tarjeta",
}
# Rates the history API has, by the same ids.
HISTORY_RATES = ("oficial", "blue", "bolsa", "contadoconliqui", "mayorista", "cripto", "tarjeta")
CURRENCY_ORDER = ("EUR", "BRL", "CLP", "UYU")
CURRENCY_NAMES = {"EUR": "Euro", "BRL": "Real", "CLP": "Peso chileno", "UYU": "Peso uruguayo"}


class DolarError(ValueError):
    """A problem worth telling the user. The message is safe to show in the chat."""


@dataclass(frozen=True)
class Quote:
    key: str
    name: str
    buy: float
    sell: float
    updated: str  # ISO timestamp from the API, in UTC


def parse_quotes(payload, key_field: str = "casa") -> dict[str, Quote]:
    """Turn the API list into {key: Quote}. Malformed entries are skipped, not fatal.

    key_field is "casa" for the dollar list and "moneda" for other currencies."""
    if not isinstance(payload, list):
        raise DolarError("Las cotizaciones llegaron en un formato raro. Probá en un ratito.")
    quotes = {}
    for item in payload:
        try:
            q = Quote(
                key=str(item[key_field]),
                name=str(item["nombre"]),
                buy=float(item["compra"]),
                sell=float(item["venta"]),
                updated=str(item.get("fechaActualizacion", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        quotes[q.key] = q
    if not quotes:
        raise DolarError("No llegó ninguna cotización que sirva. Probá en un ratito.")
    return quotes


def resolve_rate(text: str) -> str:
    key = RATE_ALIASES.get(text.strip().lower())
    if key is None:
        options = ", ".join(sorted({"oficial", "blue", "mep", "ccl", "mayorista", "cripto", "tarjeta"}))
        raise DolarError(f"No conozco el dólar '{text.strip()}'. Probá con: {options}.")
    return key


def money(value: float, decimals: int = 2) -> str:
    """1545.5 -> '$1.545,50' (Argentine format)."""
    s = f"{value:,.{decimals}f}"
    return "$" + s.replace(",", "X").replace(".", ",").replace("X", ".")


def percent(value: float) -> str:
    """1.64 -> '1,6 %'."""
    return f"{value:.1f}".replace(".", ",") + " %"


def local_time(iso: str) -> datetime | None:
    """API timestamp (UTC, ISO 8601) -> Argentine time. None if it cannot be read."""
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(ART)


def when(iso: str, now: datetime) -> str:
    """'hoy a las 13:58', 'ayer a las 17:00' or '18/10 a las 17:00', in Argentine time."""
    moment = local_time(iso)
    if moment is None:
        return "hora desconocida"
    today = now.astimezone(ART).date()
    day = moment.date()
    if day == today:
        prefix = "hoy"
    elif day == today - timedelta(days=1):
        prefix = "ayer"
    else:
        prefix = f"el {day:%d/%m}"
    return f"{prefix} a las {moment:%H:%M}"


def latest_update(quotes: dict[str, Quote]) -> str:
    """The most recent timestamp among the quotes (ISO strings in the same format sort correctly)."""
    return max((q.updated for q in quotes.values() if q.updated), default="")


def gap_percent(quotes: dict[str, Quote], rate: str = "blue", base: str = "oficial") -> float:
    """How much more expensive `rate` is than `base`, on the selling price, in percent."""
    try:
        return (quotes[rate].sell / quotes[base].sell - 1) * 100
    except KeyError:
        raise DolarError("Me falta una de las cotizaciones para calcular la brecha.") from None
    except ZeroDivisionError:
        raise DolarError("La cotización oficial vino en cero, algo anda mal.") from None


def format_quotes(quotes: dict[str, Quote], now: datetime) -> str:
    """The /dolar reply: a table in a code block, the gap and when each rate was taken."""
    rows = [f"{'':<10}{'Compra':>12}{'Venta':>12}"]
    for key in RATE_ORDER:
        q = quotes.get(key)
        if q:
            rows.append(f"{SHORT_NAMES[key]:<10}{money(q.buy):>12}{money(q.sell):>12}")
    lines = ["💵 **Así está el dólar, che:**", "```", *rows, "```"]
    if "blue" in quotes and "oficial" in quotes:
        lines.append(f"Brecha blue / oficial: **{percent(gap_percent(quotes))}**")
    stamps = sorted({q.updated for q in quotes.values() if q.updated})
    if len(stamps) > 1:
        first, last = when(stamps[0], now), when(stamps[-1], now)
        lines.append(f"🕒 Cotizado entre {first} y {last} (hora argentina)")
    elif stamps:
        lines.append(f"🕒 Cotizado {when(stamps[0], now)} (hora argentina)")
    return "\n".join(lines)


def format_currencies(quotes: dict[str, Quote], now: datetime) -> str:
    """The /monedas reply."""
    rows = [f"{'':<15}{'Compra':>12}{'Venta':>12}"]
    for code in CURRENCY_ORDER:
        q = quotes.get(code)
        if q:
            decimals = 4 if q.sell < 10 else 2
            rows.append(
                f"{CURRENCY_NAMES[code]:<15}{money(q.buy, decimals):>12}{money(q.sell, decimals):>12}"
            )
    if len(rows) == 1:
        raise DolarError("No encontré otras monedas en este momento. Probá en un ratito.")
    lines = ["🌎 **Otras monedas, en pesos (oficial):**", "```", *rows, "```"]
    stamp = latest_update(quotes)
    if stamp:
        lines.append(f"🕒 Cotizado {when(stamp, now)} (hora argentina)")
    return "\n".join(lines)


def convert(amount: float, direction: str, rate: str, quotes: dict[str, Quote], now: datetime) -> str:
    """direction 'usd': dollars to pesos at the BUY price (what you get if you sell).
    direction 'ars': pesos to dollars at the SELL price (what you pay to buy)."""
    if amount <= 0:
        raise DolarError("El monto tiene que ser mayor que cero, che.")
    q = quotes.get(rate)
    if q is None:
        raise DolarError("Esa cotización no está disponible ahora. Probá con otra.")
    name = SHORT_NAMES.get(rate, q.name)
    stamp = f"\n🕒 Cotizado {when(q.updated, now)}" if q.updated else ""
    if direction == "usd":
        return f"Si vendés **US$ {_num(amount)}** al {name} ({money(q.buy)}), recibís **{money(amount * q.buy)}**.{stamp}"
    if direction == "ars":
        return f"Con **{money(amount)}** comprás **US$ {_num(amount / q.sell)}** al {name} ({money(q.sell)}).{stamp}"
    raise DolarError("La moneda tiene que ser dólares o pesos.")


def card_purchase(amount_usd: float, quotes: dict[str, Quote], now: datetime) -> str:
    """The /compra reply: what a purchase in dollars costs with an Argentine card.

    The API's "tarjeta" rate already includes the taxes on card purchases abroad."""
    if amount_usd <= 0:
        raise DolarError("Poné cuánto sale en dólares, mayor que cero.")
    q = quotes.get("tarjeta")
    if q is None:
        raise DolarError("Ahora no tengo el dólar tarjeta. Probá en un ratito.")
    stamp = f"\n🕒 Cotizado {when(q.updated, now)}" if q.updated else ""
    return (
        f"💳 Algo de **US$ {_num(amount_usd)}** con tarjeta te sale unos **{money(amount_usd * q.sell)}**.\n"
        f"Dólar tarjeta: {money(q.sell)}, con los impuestos incluidos. "
        f"Es una referencia: tu banco puede cobrar un poco distinto.{stamp}"
    )


def _num(value: float) -> str:
    s = f"{value:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- history


@dataclass(frozen=True)
class DayClose:
    day: date
    buy: float
    sell: float


def parse_history(payload) -> list[DayClose]:
    """Daily closes, oldest first. Bad rows are skipped; duplicated days keep the last one."""
    if not isinstance(payload, list):
        raise DolarError("El historial llegó en un formato raro. Probá en un ratito.")
    by_day: dict[date, DayClose] = {}
    for item in payload:
        try:
            d = date.fromisoformat(str(item["fecha"]))
            by_day[d] = DayClose(d, float(item["compra"]), float(item["venta"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not by_day:
        raise DolarError("No encontré historial para esa cotización.")
    return [by_day[d] for d in sorted(by_day)]


def last_days(history: list[DayClose], days: int, today: date) -> list[DayClose]:
    """Closes from the last `days` calendar days, today included."""
    since = today - timedelta(days=days - 1)
    return [h for h in history if h.day >= since]


@dataclass(frozen=True)
class Move:
    first: DayClose
    last: DayClose
    low: DayClose
    high: DayClose

    @property
    def change(self) -> float:
        return self.last.sell - self.first.sell

    @property
    def change_pct(self) -> float:
        return (self.last.sell / self.first.sell - 1) * 100 if self.first.sell else 0.0


def move_of(window: list[DayClose]) -> Move:
    if len(window) < 2:
        raise DolarError("No hay suficientes días de historial para comparar.")
    return Move(
        first=window[0],
        last=window[-1],
        low=min(window, key=lambda h: h.sell),
        high=max(window, key=lambda h: h.sell),
    )


def arrow(change: float) -> str:
    return "▲" if change > 0 else "▼" if change < 0 else "="


def signed_money(value: float) -> str:
    return ("+" if value > 0 else "−" if value < 0 else "") + money(abs(value))


def signed_percent(value: float) -> str:
    return ("+" if value > 0 else "−" if value < 0 else "") + percent(abs(value))


def format_history(rate: str, days: int, window: list[DayClose]) -> str:
    """The text that goes with the /historial chart."""
    m = move_of(window)
    name = SHORT_NAMES.get(rate, rate)
    return (
        f"📈 **Dólar {name}, últimos {days} días** (precio de venta)\n"
        f"{m.first.day:%d/%m}: {money(m.first.sell)} → {m.last.day:%d/%m}: {money(m.last.sell)} "
        f"{arrow(m.change)} {signed_money(m.change)} ({signed_percent(m.change_pct)})\n"
        f"Mínimo {money(m.low.sell)} el {m.low.day:%d/%m} · Máximo {money(m.high.sell)} el {m.high.day:%d/%m}"
    )


def format_daily_summary(histories: dict[str, list[DayClose]], today: date) -> str:
    """The daily message: today's close of each rate against the previous day with data."""
    if today.weekday() >= 5:
        # The market is closed; the history source may still repeat Friday's value for today.
        raise DolarError("Los fines de semana no hay cierre.")
    lines = [f"🧉 **Así cerró el dólar hoy, {today:%d/%m}:**"]
    for rate in ("blue", "oficial", "bolsa", "contadoconliqui"):
        hist = [h for h in histories.get(rate, []) if h.day <= today]
        if len(hist) < 2 or hist[-1].day != today:
            continue  # no close for today yet: better to say nothing than to say something old
        prev, last = hist[-2], hist[-1]
        change = last.sell - prev.sell
        pct = (last.sell / prev.sell - 1) * 100 if prev.sell else 0.0
        lines.append(
            f"{arrow(change)} {SHORT_NAMES[rate]}: **{money(last.sell)}** "
            f"({signed_money(change)}, {signed_percent(pct)} contra el {prev.day:%d/%m})"
        )
    if len(lines) == 1:
        raise DolarError("Todavía no hay cierre de hoy.")
    return "\n".join(lines)


# ---------------------------------------------------------------- data for the cards


def stamps_text(quotes: dict[str, Quote], now: datetime) -> str:
    """'Cotizado hoy a las 13:58 (hora argentina)' or 'Cotizado entre ... y ...'."""
    stamps = sorted({q.updated for q in quotes.values() if q.updated})
    if not stamps:
        return "Hora de cotización desconocida"
    if len(stamps) == 1 or when(stamps[0], now) == when(stamps[-1], now):
        return f"Cotizado {when(stamps[-1], now)} (hora argentina)"
    return f"Cotizado entre {when(stamps[0], now)} y {when(stamps[-1], now)} (hora argentina)"


def previous_close(history: list[DayClose], today: date) -> DayClose | None:
    """The last close before today: what "vs ayer" compares against (Friday on a Monday)."""
    before = [h for h in history if h.day < today]
    return before[-1] if before else None


@dataclass(frozen=True)
class Row:
    """One rate in /dolar: today's prices and the change against the previous close."""

    key: str
    name: str
    buy: float
    sell: float
    prev: DayClose | None

    @property
    def change(self) -> float | None:
        return None if self.prev is None else self.sell - self.prev.sell

    @property
    def change_pct(self) -> float | None:
        if self.prev is None or not self.prev.sell:
            return None
        return (self.sell / self.prev.sell - 1) * 100

    def change_text(self) -> str:
        """'▲ +$10,00 (+0,6 %) vs 20/10', or '' when there is nothing to compare against."""
        if self.change is None or self.change_pct is None or self.prev is None:
            return ""
        return (
            f"{arrow(self.change)} {signed_money(self.change)} ({signed_percent(self.change_pct)}) "
            f"vs {self.prev.day:%d/%m}"
        )


def dollar_rows(quotes: dict[str, Quote], histories: dict[str, list[DayClose]], today: date) -> list[Row]:
    rows = []
    for key in RATE_ORDER:
        q = quotes.get(key)
        if q is None:
            continue
        prev = previous_close(histories.get(key, []), today)
        rows.append(Row(key, SHORT_NAMES[key], q.buy, q.sell, prev))
    if not rows:
        raise DolarError("No llegó ninguna cotización que sirva. Probá en un ratito.")
    return rows


PERIODS = {1: "hoy contra el día anterior", 7: "últimos 7 días", 30: "últimos 30 días"}


def period_moves(histories: dict[str, list[DayClose]], days: int, today: date) -> list[tuple[str, Move]]:
    """How each rate moved in a period. days=1 compares the last close with the one before."""
    out = []
    for key in RATE_ORDER:
        hist = [h for h in histories.get(key, []) if h.day <= today]
        if len(hist) < 2:
            continue
        window = hist[-2:] if days == 1 else last_days(hist, days, today)
        if len(window) >= 2:
            out.append((key, move_of(window)))
    if not out:
        raise DolarError("No hay suficiente historial para ese período.")
    return out


def average(window: list[DayClose]) -> float:
    return sum(h.sell for h in window) / len(window)


# ---------------------------------------------------------------- alerts


@dataclass(frozen=True)
class Alert:
    user_id: int
    rate: str
    side: str  # "buy" or "sell"
    above: bool  # True: fire when the price is at or above the target
    target: float


def alert_fires(alert: Alert, quotes: dict[str, Quote]) -> bool:
    q = quotes.get(alert.rate)
    if q is None:
        return False
    price = q.sell if alert.side == "sell" else q.buy
    return price >= alert.target if alert.above else price <= alert.target


def describe_alert(alert: Alert) -> str:
    word = "sube a" if alert.above else "baja a"
    return f"el {SHORT_NAMES.get(alert.rate, alert.rate)} {word} {money(alert.target)}"
