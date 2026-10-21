from datetime import date, datetime, timezone

import pytest

from dolar_che import storage
from dolar_che.core import (
    Alert,
    DayClose,
    DolarError,
    alert_fires,
    card_purchase,
    convert,
    format_currencies,
    format_daily_summary,
    format_history,
    format_quotes,
    gap_percent,
    last_days,
    money,
    parse_history,
    parse_quotes,
    percent,
    resolve_rate,
    when,
)

# 21/10/2026 15:00 in Argentina (UTC-3).
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)

PAYLOAD = [
    {
        "casa": "oficial",
        "nombre": "Oficial",
        "compra": 1495,
        "venta": 1545,
        "fechaActualizacion": "2026-10-21T16:58:00.000Z",
    },
    {
        "casa": "blue",
        "nombre": "Blue",
        "compra": 1550,
        "venta": 1570,
        "fechaActualizacion": "2026-10-21T16:58:00.000Z",
    },
    {
        "casa": "bolsa",
        "nombre": "Bolsa",
        "compra": 1542.5,
        "venta": 1548.8,
        "fechaActualizacion": "2026-10-21T16:58:00.000Z",
    },
    {
        "casa": "tarjeta",
        "nombre": "Tarjeta",
        "compra": 1943.5,
        "venta": 2008.5,
        "fechaActualizacion": "2026-10-20T18:00:00.000Z",
    },
]


@pytest.fixture
def quotes():
    return parse_quotes(PAYLOAD)


# ---------------------------------------------------------------- reading and formats


def test_parse_reads_all_entries(quotes):
    assert set(quotes) == {"oficial", "blue", "bolsa", "tarjeta"}
    assert quotes["blue"].sell == 1570.0


def test_parse_skips_broken_entries_but_keeps_good_ones():
    q = parse_quotes([{"casa": "blue"}, {"casa": "oficial", "nombre": "O", "compra": 1, "venta": 2}])
    assert set(q) == {"oficial"}


def test_parse_rejects_non_list_and_empty():
    with pytest.raises(DolarError):
        parse_quotes({"error": "x"})
    with pytest.raises(DolarError):
        parse_quotes([{"nope": 1}])


def test_other_currencies_are_keyed_by_currency_code():
    q = parse_quotes(
        [{"moneda": "EUR", "casa": "oficial", "nombre": "Euro", "compra": 1700, "venta": 1715}],
        key_field="moneda",
    )
    assert set(q) == {"EUR"}


def test_aliases_mep_and_ccl():
    assert resolve_rate("MEP") == "bolsa"
    assert resolve_rate(" ccl ") == "contadoconliqui"


def test_unknown_rate_suggests_the_options():
    with pytest.raises(DolarError, match="Probá con"):
        resolve_rate("euro")


def test_money_and_percent_use_argentine_format():
    assert money(1545.5) == "$1.545,50"
    assert money(1234567.891) == "$1.234.567,89"
    assert money(1.5643, 4) == "$1,5643"
    assert percent(1.64) == "1,6 %"


# ---------------------------------------------------------------- time of the quote


def test_when_converts_utc_to_argentine_time_and_names_the_day():
    assert when("2026-10-21T16:58:00.000Z", NOW) == "hoy a las 13:58"
    assert when("2026-10-20T18:00:00.000Z", NOW) == "ayer a las 15:00"
    assert when("2026-10-18T12:00:00.000Z", NOW) == "el 18/10 a las 09:00"


def test_when_after_midnight_utc_is_still_the_same_argentine_day():
    # 02:30 UTC on the 22nd is 23:30 on the 21st in Argentina.
    assert (
        when("2026-10-22T02:30:00Z", datetime(2026, 10, 22, 2, 45, tzinfo=timezone.utc)) == "hoy a las 23:30"
    )


def test_when_with_an_unreadable_timestamp_says_so():
    assert when("", NOW) == "hora desconocida"
    assert when("ayer", NOW) == "hora desconocida"


def test_dolar_reply_has_table_gap_and_time_range(quotes):
    text = format_quotes(quotes, NOW)
    assert text.index("Oficial") < text.index("Blue") < text.index("MEP")
    assert "Brecha blue / oficial: **1,6 %**" in text
    assert "🕒 Cotizado entre ayer a las 15:00 y hoy a las 13:58 (hora argentina)" in text


def test_dolar_reply_with_one_timestamp_shows_a_single_time():
    q = parse_quotes(PAYLOAD[:2])
    assert "🕒 Cotizado hoy a las 13:58 (hora argentina)" in format_quotes(q, NOW)


def test_gap_is_blue_over_official_on_sell(quotes):
    assert gap_percent(quotes) == pytest.approx((1570 / 1545 - 1) * 100)


def test_gap_without_base_is_a_clear_error():
    with pytest.raises(DolarError):
        gap_percent(parse_quotes([{"casa": "blue", "nombre": "B", "compra": 1, "venta": 2}]))


def test_currencies_reply_uses_more_decimals_for_small_values():
    q = parse_quotes(
        [
            {
                "moneda": "EUR",
                "nombre": "Euro",
                "compra": 1701.5584,
                "venta": 1715.4725,
                "fechaActualizacion": "2026-10-21T17:00:00Z",
            },
            {
                "moneda": "CLP",
                "nombre": "Peso Chileno",
                "compra": 1.5643,
                "venta": 1.5643,
                "fechaActualizacion": "2026-10-21T17:00:00Z",
            },
        ],
        key_field="moneda",
    )
    text = format_currencies(q, NOW)
    assert "$1.715,47" in text and "$1,5643" in text and "hoy a las 14:00" in text


def test_currencies_reply_without_known_currencies_is_an_error():
    q = parse_quotes([{"moneda": "XYZ", "nombre": "?", "compra": 1, "venta": 1}], key_field="moneda")
    with pytest.raises(DolarError):
        format_currencies(q, NOW)


# ---------------------------------------------------------------- converting and buying


def test_selling_dollars_uses_the_buy_price(quotes):
    text = convert(100, "usd", "blue", quotes, NOW)
    assert "recibís **$155.000,00**" in text and "hoy a las 13:58" in text


def test_buying_dollars_uses_the_sell_price(quotes):
    assert "**US$ 100,00**" in convert(157000, "ars", "blue", quotes, NOW)


@pytest.mark.parametrize("amount", [0, -5])
def test_convert_rejects_non_positive_amounts(quotes, amount):
    with pytest.raises(DolarError):
        convert(amount, "usd", "blue", quotes, NOW)


def test_convert_rejects_unknown_direction_and_missing_rate(quotes):
    with pytest.raises(DolarError):
        convert(1, "eur", "blue", quotes, NOW)
    with pytest.raises(DolarError):
        convert(1, "usd", "cripto", quotes, NOW)


def test_card_purchase_uses_the_card_rate_with_taxes(quotes):
    text = card_purchase(20, quotes, NOW)
    assert "**$40.170,00**" in text and "impuestos incluidos" in text and "ayer a las 15:00" in text


def test_card_purchase_rejects_zero_and_a_missing_card_rate():
    with pytest.raises(DolarError):
        card_purchase(0, parse_quotes(PAYLOAD), NOW)
    with pytest.raises(DolarError):
        card_purchase(10, parse_quotes(PAYLOAD[:2]), NOW)


# ---------------------------------------------------------------- history


def closes(*pairs):
    return [DayClose(date(2026, 10, d), v - 20, v) for d, v in pairs]


def test_history_is_sorted_and_skips_bad_rows_and_keeps_the_last_duplicate():
    h = parse_history(
        [
            {"fecha": "2026-10-20", "compra": 1, "venta": 1560},
            {"fecha": "2026-10-19", "compra": 1, "venta": 1555},
            {"fecha": "nope", "compra": 1, "venta": 1},
            {"fecha": "2026-10-20", "compra": 1, "venta": 1561},
        ]
    )
    assert [(c.day.day, c.sell) for c in h] == [(19, 1555), (20, 1561)]


def test_empty_history_is_an_error():
    with pytest.raises(DolarError):
        parse_history([])


def test_last_days_counts_calendar_days_including_today():
    h = closes((10, 1), (14, 2), (15, 3), (21, 4))
    assert [c.day.day for c in last_days(h, 7, date(2026, 10, 21))] == [15, 21]


def test_history_text_shows_change_low_and_high():
    text = format_history("blue", 7, closes((15, 1550), (16, 1540), (20, 1580), (21, 1570)))
    assert "15/10: $1.550,00 → 21/10: $1.570,00 ▲ +$20,00 (+1,3 %)" in text
    assert "Mínimo $1.540,00 el 16/10" in text and "Máximo $1.580,00 el 20/10" in text


def test_history_text_needs_two_days():
    with pytest.raises(DolarError):
        format_history("blue", 7, closes((21, 1570)))


def test_daily_summary_compares_with_the_previous_day_with_data():
    histories = {
        "blue": closes((17, 1550), (20, 1560), (21, 1570)),
        "oficial": closes((20, 1550), (21, 1545)),
    }
    text = format_daily_summary(histories, date(2026, 10, 21))
    assert "▲ Blue: **$1.570,00** (+$10,00, +0,6 % contra el 20/10)" in text
    assert "▼ Oficial: **$1.545,00** (−$5,00, −0,3 % contra el 20/10)" in text


def test_daily_summary_never_reports_an_old_close_as_today():
    histories = {"blue": closes((19, 1550), (20, 1560))}
    with pytest.raises(DolarError, match="Todavía no hay cierre"):
        format_daily_summary(histories, date(2026, 10, 21))


def test_daily_summary_is_skipped_on_weekends_even_if_the_source_repeats_a_value():
    # 24/10/2026 is a Saturday.
    histories = {"blue": closes((23, 1570), (24, 1570))}
    with pytest.raises(DolarError, match="fines de semana"):
        format_daily_summary(histories, date(2026, 10, 24))


# ---------------------------------------------------------------- alerts


def test_alert_above_fires_at_the_target_and_over(quotes):
    assert alert_fires(Alert(1, "blue", "sell", True, 1570), quotes)
    assert not alert_fires(Alert(1, "blue", "sell", True, 1571), quotes)


def test_alert_below_fires_at_the_target_and_under(quotes):
    assert alert_fires(Alert(1, "blue", "sell", False, 1570), quotes)
    assert not alert_fires(Alert(1, "blue", "sell", False, 1569), quotes)


def test_alert_on_a_missing_rate_does_not_fire(quotes):
    assert not alert_fires(Alert(1, "cripto", "sell", True, 1), quotes)


def test_storage_roundtrip(tmp_path):
    path = tmp_path / "a.json"
    alerts = [Alert(7, "blue", "sell", True, 1600.0)]
    storage.save(path, alerts)
    assert storage.load(path) == alerts


def test_storage_missing_or_corrupt_file_means_no_alerts(tmp_path):
    assert storage.load(tmp_path / "none.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert storage.load(bad) == []


def test_storage_add_limits_alerts_per_user_and_ignores_duplicates():
    alerts = []
    for i in range(storage.MAX_ALERTS_PER_USER):
        alerts = storage.add(alerts, Alert(1, "blue", "sell", True, 1000 + i))
    with pytest.raises(ValueError, match="Máximo"):
        storage.add(alerts, Alert(1, "blue", "sell", True, 9999))
    assert storage.add(alerts, alerts[0]) == alerts


def test_remove_uses_the_users_own_numbering():
    a1, a2, other = (
        Alert(1, "blue", "sell", True, 1),
        Alert(1, "blue", "sell", True, 2),
        Alert(2, "blue", "sell", True, 3),
    )
    assert storage.remove([a1, other, a2], 1, 2) == [a1, other]
