import pytest

from dolar_bot import storage
from dolar_bot.core import (
    Alert,
    DolarError,
    alert_fires,
    convert,
    format_quotes,
    gap_percent,
    money,
    parse_quotes,
    resolve_rate,
)

PAYLOAD = [
    {"casa": "oficial", "nombre": "Oficial", "compra": 1495, "venta": 1545, "fechaActualizacion": "x"},
    {"casa": "blue", "nombre": "Blue", "compra": 1550, "venta": 1570},
    {"casa": "bolsa", "nombre": "Bolsa", "compra": 1542.5, "venta": 1548.8},
]


@pytest.fixture
def quotes():
    return parse_quotes(PAYLOAD)


def test_parse_reads_all_entries(quotes):
    assert set(quotes) == {"oficial", "blue", "bolsa"}
    assert quotes["blue"].sell == 1570.0


def test_parse_skips_broken_entries_but_keeps_good_ones():
    q = parse_quotes([{"casa": "blue"}, {"casa": "oficial", "nombre": "O", "compra": 1, "venta": 2}])
    assert set(q) == {"oficial"}


def test_parse_rejects_non_list_and_empty():
    with pytest.raises(DolarError):
        parse_quotes({"error": "x"})
    with pytest.raises(DolarError):
        parse_quotes([{"nope": 1}])


def test_aliases_mep_and_ccl():
    assert resolve_rate("MEP") == "bolsa"
    assert resolve_rate(" ccl ") == "contadoconliqui"


def test_unknown_rate_lists_the_options():
    with pytest.raises(DolarError, match="Opciones"):
        resolve_rate("euro")


def test_money_uses_argentine_format():
    assert money(1545.5) == "$ 1.545,50"
    assert money(1234567.891) == "$ 1.234.567,89"
    assert money(0.5) == "$ 0,50"


def test_gap_is_blue_over_official_on_sell(quotes):
    assert gap_percent(quotes) == pytest.approx((1570 / 1545 - 1) * 100)


def test_gap_without_base_is_a_clear_error():
    q = parse_quotes([{"casa": "blue", "nombre": "B", "compra": 1, "venta": 2}])
    with pytest.raises(DolarError):
        gap_percent(q)


def test_format_lists_known_rates_in_order_and_the_gap(quotes):
    text = format_quotes(quotes)
    assert text.index("Oficial") < text.index("Blue") < text.index("Bolsa")
    assert "Brecha blue / oficial: 1.6%" in text


def test_selling_dollars_uses_the_buy_price(quotes):
    assert convert(100, "usd", "blue", quotes) == "USD 100.00 vendidos al Blue ($ 1.550,00) = $ 155.000,00"


def test_buying_dollars_uses_the_sell_price(quotes):
    out = convert(157000, "ars", "blue", quotes)
    assert out.endswith("= USD 100.00")


@pytest.mark.parametrize("amount", [0, -5])
def test_convert_rejects_non_positive_amounts(quotes, amount):
    with pytest.raises(DolarError):
        convert(amount, "usd", "blue", quotes)


def test_convert_rejects_unknown_direction_and_missing_rate(quotes):
    with pytest.raises(DolarError):
        convert(1, "eur", "blue", quotes)
    with pytest.raises(DolarError):
        convert(1, "usd", "cripto", quotes)


def test_alert_above_fires_at_the_target_and_over(quotes):
    assert alert_fires(Alert(1, "blue", "sell", True, 1570), quotes)
    assert alert_fires(Alert(1, "blue", "sell", True, 1500), quotes)
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
    assert len(storage.add(alerts, Alert(2, "blue", "sell", True, 1))) == len(alerts) + 1


def test_remove_uses_the_users_own_numbering():
    a1, a2, other = (
        Alert(1, "blue", "sell", True, 1),
        Alert(1, "blue", "sell", True, 2),
        Alert(2, "blue", "sell", True, 3),
    )
    assert storage.remove([a1, other, a2], 1, 2) == [a1, other]


def test_remove_rejects_a_number_that_does_not_exist():
    with pytest.raises(ValueError):
        storage.remove([Alert(1, "blue", "sell", True, 1)], 1, 2)
