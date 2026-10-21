"""Pure logic: read the quotes, format them, convert amounts, decide when an alert fires."""

from __future__ import annotations

from dataclasses import dataclass

# Order shown to users. Keys are the "casa" ids used by the API.
RATE_ORDER = ("oficial", "blue", "bolsa", "contadoconliqui", "mayorista", "cripto", "tarjeta")
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


class DolarError(ValueError):
    """A problem the user can fix. The message is safe to show in the chat."""


@dataclass(frozen=True)
class Quote:
    key: str
    name: str
    buy: float
    sell: float
    updated: str  # ISO timestamp from the API


def parse_quotes(payload) -> dict[str, Quote]:
    """Turn the API list into {key: Quote}. Malformed entries are skipped, not fatal."""
    if not isinstance(payload, list):
        raise DolarError("The quotes service returned something unexpected.")
    quotes = {}
    for item in payload:
        try:
            q = Quote(
                key=str(item["casa"]),
                name=str(item["nombre"]),
                buy=float(item["compra"]),
                sell=float(item["venta"]),
                updated=str(item.get("fechaActualizacion", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        quotes[q.key] = q
    if not quotes:
        raise DolarError("The quotes service returned no usable rates.")
    return quotes


def resolve_rate(text: str) -> str:
    key = RATE_ALIASES.get(text.strip().lower())
    if key is None:
        options = ", ".join(sorted(RATE_ALIASES))
        raise DolarError(f"No conozco '{text.strip()}'. Opciones: {options}.")
    return key


def money(value: float) -> str:
    """1545.5 -> '$ 1.545,50' (Argentine format)."""
    s = f"{value:,.2f}"
    return "$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def gap_percent(quotes: dict[str, Quote], rate: str = "blue", base: str = "oficial") -> float:
    """How much more expensive `rate` is than `base`, on the selling price, in percent."""
    try:
        return (quotes[rate].sell / quotes[base].sell - 1) * 100
    except KeyError:
        raise DolarError("Falta una de las cotizaciones para calcular la brecha.") from None
    except ZeroDivisionError:
        raise DolarError("La cotización base vale cero.") from None


def format_quotes(quotes: dict[str, Quote]) -> str:
    lines = [f"{'Tipo':<24}{'Compra':>14}{'Venta':>14}"]
    for key in RATE_ORDER:
        q = quotes.get(key)
        if q:
            lines.append(f"{q.name:<24}{money(q.buy):>14}{money(q.sell):>14}")
    if "blue" in quotes and "oficial" in quotes:
        lines.append(f"\nBrecha blue / oficial: {gap_percent(quotes):.1f}%")
    return "\n".join(lines)


def convert(amount: float, direction: str, rate: str, quotes: dict[str, Quote]) -> str:
    """direction 'usd' converts dollars to pesos at the BUY price (what you get if you sell);
    'ars' converts pesos to dollars at the SELL price (what you pay to buy)."""
    if amount <= 0:
        raise DolarError("El monto tiene que ser mayor que cero.")
    q = quotes.get(rate)
    if q is None:
        raise DolarError("Esa cotización no está disponible ahora.")
    if direction == "usd":
        return f"USD {amount:,.2f} vendidos al {q.name} ({money(q.buy)}) = {money(amount * q.buy)}"
    if direction == "ars":
        return f"{money(amount)} comprando al {q.name} ({money(q.sell)}) = USD {amount / q.sell:,.2f}"
    raise DolarError("La moneda tiene que ser 'usd' o 'ars'.")


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
    side = "venta" if alert.side == "sell" else "compra"
    return f"{alert.rate} ({side}) {word} {money(alert.target)}"
