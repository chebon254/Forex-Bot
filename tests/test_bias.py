import pandas as pd
import pytest

from fxbot import bias
from fxbot.currencies import PRIORITY, all_pairs, pair_name

RATES = {"USD": 4.00, "GBP": 3.75, "AUD": 4.35, "NZD": 2.75, "CAD": 2.25, "EUR": 2.65, "JPY": 1.25, "CHF": 0.00}


def test_28_pairs_in_broker_naming():
    pairs = all_pairs()
    assert len(pairs) == len(set(pairs)) == 28
    for p in ("EURUSD", "GBPJPY", "AUDNZD", "USDCHF", "CADJPY", "CHFJPY", "NZDCAD", "EURGBP"):
        assert p in pairs
    assert pair_name("JPY", "GBP") == "GBPJPY"
    assert pair_name("CHF", "USD") == "USDCHF"


def test_your_example_usd_above_zero_chf_below_is_a_buy():
    # "USD is bullish if USD is above zero basis line and CHF is below"
    b = bias.pair_bias("USDCHF", {"USD": 1, "CHF": -1}, RATES, min_carry=0.5)
    assert (b.direction, b.grade, b.carry) == ("BUY", "A", 4.0)


def test_opposite_cot_against_the_carry_is_grade_b():
    b = bias.pair_bias("USDCHF", {"USD": -1, "CHF": 1}, RATES, min_carry=0.5)
    assert (b.direction, b.grade, b.carry) == ("SELL", "B", -4.0)


def test_small_carry_is_grade_b():
    b = bias.pair_bias("AUDUSD", {"AUD": 1, "USD": -1}, RATES, min_carry=0.5)
    assert (b.direction, b.grade) == ("BUY", "B")
    assert b.carry == pytest.approx(0.35)


@pytest.mark.parametrize("sides", [{"USD": 1, "CHF": 1}, {"USD": -1, "CHF": -1}, {"USD": 1, "CHF": 0}, {}])
def test_same_side_or_flat_is_no_trade(sides):
    b = bias.pair_bias("USDCHF", sides, RATES, min_carry=0.5)
    assert (b.direction, b.grade) == ("NEUTRAL", "-")


def test_ranking_puts_grade_a_first_widest_carry_first():
    sides = {"AUD": 1, "GBP": 1, "JPY": -1, "NZD": -1, "USD": -1, "CAD": 1, "CHF": 1, "EUR": 0}
    ranked = bias.all_biases(sides, RATES, min_carry=0.5)
    a = [b.symbol for b in ranked if b.grade == "A"]
    assert a[:3] == ["AUDJPY", "GBPJPY", "AUDNZD"]
    grades = [b.grade for b in ranked]
    assert grades == sorted(grades, key={"A": 0, "B": 1, "-": 2}.get)


def test_override_wins_and_is_marked_manual():
    ranked = bias.all_biases({}, RATES, 0.5, overrides={"usdchf": "sell"})
    b = next(b for b in ranked if b.symbol == "USDCHF")
    assert (b.direction, b.grade, b.source, b.carry) == ("SELL", "M", "override", -4.0)


def test_bad_override_is_rejected():
    with pytest.raises(ValueError):
        bias.all_biases({}, RATES, 0.5, overrides={"USDCHF": "LONG"})
    with pytest.raises(ValueError):
        bias.all_biases({}, RATES, 0.5, overrides={"USDXYZ": "BUY"})


def test_history_uses_rates_known_at_the_time_and_starts_the_weekend_after():
    report = pd.Timestamp("2024-03-05")  # a Tuesday
    cot = pd.DataFrame(
        [{"date": report, "currency": c, "comm_net": 100 if c == "USD" else -100, "open_interest": 1000} for c in PRIORITY]
    )
    rates_hist = pd.DataFrame([{**RATES}, {**RATES, "CHF": 5.0}], index=pd.to_datetime(["2024-01-01", "2024-03-20"]))
    hist = bias.history(cot, rates_hist, band_pct=2.0, min_carry=0.5)
    row = hist[hist["symbol"] == "USDCHF"].iloc[0]
    assert row["valid_from"] == pd.Timestamp("2024-03-09")  # Saturday after Friday's release
    assert (row["direction"], row["grade"], row["carry"]) == ("BUY", "A", 4.0)  # CHF hike on 03-20 not used yet
