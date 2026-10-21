"""Shows in the terminal what DOLAR CHE would answer, with real data and no Discord.

python -m dolar_che.preview            every command
python -m dolar_che.preview dolar      just one: dolar, monedas, convertir, compra, historial, resumen
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from .api import Rates
from .chart import render
from .core import (
    ART,
    SHORT_NAMES,
    DolarError,
    card_purchase,
    convert,
    format_currencies,
    format_daily_summary,
    format_history,
    format_quotes,
    last_days,
)


def show(title: str, body: str) -> None:
    print(f"\n── /{title} " + "─" * max(4, 50 - len(title)))
    print(body.replace("**", ""))


def main(argv: list[str]) -> int:
    rates = Rates()
    now = datetime.now(timezone.utc)
    today = now.astimezone(ART).date()
    wanted = set(argv) or {"dolar", "monedas", "convertir", "compra", "historial", "resumen"}
    try:
        if wanted & {"dolar", "convertir", "compra"}:
            quotes = rates.dollars()
        if "dolar" in wanted:
            show("dolar", format_quotes(quotes, now))
        if "monedas" in wanted:
            show("monedas", format_currencies(rates.currencies(), now))
        if "convertir" in wanted:
            show("convertir monto:100 moneda:dólares tipo:Blue", convert(100, "usd", "blue", quotes, now))
        if "compra" in wanted:
            show("compra dolares:20", card_purchase(20, quotes, now))
        if "historial" in wanted:
            window = last_days(rates.history("blue"), 30, today)
            show("historial tipo:Blue dias:30", format_history("blue", 30, window))
            out = Path("historial-blue.png").resolve()
            out.write_bytes(render(window, f"Dólar {SHORT_NAMES['blue']} · últimos 30 días"))
            print(f"(gráfico guardado en {out})")
        if "resumen" in wanted:
            histories = {r: rates.history(r) for r in ("blue", "oficial", "bolsa", "contadoconliqui")}
            try:
                show("resumen diario (18:00)", format_daily_summary(histories, today))
            except DolarError as exc:
                show("resumen diario (18:00)", f"(hoy no se publicaría: {exc})")
    except DolarError as exc:
        print(f"\n😕 {exc}", file=sys.stderr)
        return 1
    return 0


def main_cli() -> int:
    return main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main_cli())
