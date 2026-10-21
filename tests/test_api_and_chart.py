from datetime import date

import pytest

from dolar_che.api import DOLARES_URL, HISTORY_URL, MONEDAS_URL, Rates
from dolar_che.chart import render
from dolar_che.core import DayClose


class FakeFetch:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.routes[url]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


DOLARES = [{"casa": "blue", "nombre": "Blue", "compra": 1550, "venta": 1570}]


def test_rates_are_cached_for_a_minute():
    fetch, clock = FakeFetch({DOLARES_URL: DOLARES}), Clock()
    rates = Rates(fetch, clock)
    rates.dollars()
    clock.t = 59
    rates.dollars()
    assert len(fetch.calls) == 1
    clock.t = 61
    rates.dollars()
    assert len(fetch.calls) == 2


def test_currencies_drop_the_repeated_us_dollar():
    fetch = FakeFetch(
        {
            MONEDAS_URL: [
                {"moneda": "USD", "nombre": "Dólar", "compra": 1495, "venta": 1545},
                {"moneda": "EUR", "nombre": "Euro", "compra": 1700, "venta": 1715},
            ]
        }
    )
    assert set(Rates(fetch).currencies()) == {"EUR"}


def test_history_asks_for_the_right_rate():
    url = HISTORY_URL.format(rate="blue")
    fetch = FakeFetch({url: [{"fecha": "2026-10-21", "compra": 1, "venta": 2}]})
    assert Rates(fetch).history("blue")[0].sell == 2
    assert fetch.calls == [url]


def test_chart_is_a_png():
    window = [DayClose(date(2026, 10, d), 1, 1500 + d) for d in range(1, 11)]
    png = render(window, "Dólar Blue · últimos 10 días")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_chart_handles_a_flat_line():
    window = [DayClose(date(2026, 10, d), 1, 1500) for d in range(1, 4)]
    assert render(window, "flat")[:4] == b"\x89PNG"


def test_chart_needs_two_days():
    with pytest.raises(ValueError):
        render([DayClose(date(2026, 10, 1), 1, 1)], "x")
