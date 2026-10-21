from datetime import date, datetime, timezone

import pytest

from dolar_che import cards
from dolar_che.core import (
    DayClose,
    DolarError,
    average,
    dollar_rows,
    parse_quotes,
    period_moves,
    previous_close,
    stamps_text,
)

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)  # 15:00 in Argentina
TODAY = date(2026, 10, 21)


def closes(*pairs):
    return [DayClose(date(2026, 10, d), v - 20, v) for d, v in pairs]


QUOTES = parse_quotes(
    [
        {
            "casa": "oficial",
            "nombre": "Oficial",
            "compra": 1495,
            "venta": 1545,
            "fechaActualizacion": "2026-10-21T16:58:00Z",
        },
        {
            "casa": "blue",
            "nombre": "Blue",
            "compra": 1550,
            "venta": 1570,
            "fechaActualizacion": "2026-10-21T16:58:00Z",
        },
    ]
)


def test_previous_close_skips_today_and_weekends_naturally():
    h = closes((16, 1550), (19, 1560), (21, 1570))  # 17 and 18 are a weekend
    assert previous_close(h, TODAY).day == date(2026, 10, 19)
    assert previous_close(h, date(2026, 10, 19)).day == date(2026, 10, 16)
    assert previous_close([], TODAY) is None


def test_rows_compare_the_current_price_with_the_previous_close():
    rows = dollar_rows(QUOTES, {"blue": closes((20, 1560), (21, 1570))}, TODAY)
    blue = next(r for r in rows if r.key == "blue")
    assert blue.change == 10
    assert blue.change_text() == "▲ +$10,00 (+0,6 %) vs 20/10"
    official = next(r for r in rows if r.key == "oficial")
    assert official.change is None and official.change_text() == ""


def test_stamps_text_with_one_or_several_times():
    assert stamps_text(QUOTES, NOW) == "Cotizado hoy a las 13:58 (hora argentina)"
    mixed = parse_quotes(
        [
            {
                "casa": "blue",
                "nombre": "B",
                "compra": 1,
                "venta": 2,
                "fechaActualizacion": "2026-10-21T16:58:00Z",
            },
            {
                "casa": "tarjeta",
                "nombre": "T",
                "compra": 1,
                "venta": 2,
                "fechaActualizacion": "2026-10-20T18:00:00Z",
            },
        ]
    )
    assert stamps_text(mixed, NOW) == "Cotizado entre ayer a las 15:00 y hoy a las 13:58 (hora argentina)"


def test_period_moves_for_today_uses_the_last_two_closes():
    moves = dict(period_moves({"blue": closes((15, 1500), (20, 1560), (21, 1570))}, 1, TODAY))
    assert moves["blue"].first.sell == 1560 and moves["blue"].change == 10


def test_period_moves_for_a_week():
    moves = dict(period_moves({"blue": closes((10, 1400), (15, 1500), (20, 1560), (21, 1570))}, 7, TODAY))
    assert moves["blue"].first.day == date(2026, 10, 15)


def test_period_moves_without_data_is_a_clear_error():
    with pytest.raises(DolarError):
        period_moves({"blue": closes((21, 1570))}, 7, TODAY)


def test_average_of_selling_price():
    assert average(closes((20, 1560), (21, 1580))) == 1570


def test_dolar_card_has_one_field_per_rate_padded_to_rows_of_three():
    rows = dollar_rows(QUOTES, {"blue": closes((20, 1560), (21, 1570))}, TODAY)
    e = cards.dolar(rows, 1.6, stamps_text(QUOTES, NOW), NOW)
    assert len(e.fields) % 3 == 0
    blue = next(f for f in e.fields if f.name == "Blue")
    assert "Venta **$1.570,00**" in blue.value and "▲ +$10,00 (+0,6 %)" in blue.value
    assert "cierre del 20/10" in e.description
    assert "💡" in e.footer.text and "dolarapi.com" in e.footer.text
    assert e.color.value == cards.UP


def test_history_card_has_the_key_numbers_and_points_to_the_chart():
    window = closes((15, 1550), (16, 1540), (20, 1580), (21, 1570))
    e = cards.history("blue", 7, window)
    names = [f.name for f in e.fields]
    assert names == ["Al inicio", "Hoy", "Promedio", "Mínimo", "Máximo", "Compra hoy"]
    assert e.image.url is None, "the chart goes as an upload under the card, which every client shows"
    assert "dias:365" in e.footer.text


def test_summary_card_lists_each_rate():
    moves = period_moves(
        {"blue": closes((20, 1560), (21, 1570)), "oficial": closes((20, 1550), (21, 1545))}, 1, TODAY
    )
    e = cards.summary(1, moves)
    assert [f.name for f in e.fields][:2] == ["▼ Oficial", "▲ Blue"]


def test_dolar_card_names_the_compared_close_once_when_all_rates_share_it():
    rows = dollar_rows(QUOTES, {"blue": closes((20, 1560)), "oficial": closes((20, 1540))}, TODAY)
    e = cards.dolar(rows, 1.6, stamps_text(QUOTES, NOW), NOW)
    assert "Variación contra el cierre del 20/10" in e.description
    assert all("vs 20/10" not in f.value for f in e.fields)


def test_history_card_adds_the_year_over_long_ranges():
    window = [DayClose(date(2025, 10, 22), 1, 1500), DayClose(date(2026, 10, 21), 1, 1570)]
    e = cards.history("blue", 365, window)
    assert "22/10/25" in e.fields[0].value
