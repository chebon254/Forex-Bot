import pandas as pd
import pytest

from fxbot.backtest import SimParams, simulate_pair, summarize

DIAGRAM = [10, 9, 8, 9, 10, 11, 12, 11, 10.5, 10, 11, 12.5, 13, 14, 13, 12, 11, 9.5, 9, 9.2]
P = SimParams(strength=2, stop_buffer_atr=0.0, cost_pips=0.0)


def series(values):
    return pd.Series(values, index=pd.bdate_range("2021-01-04", periods=len(values)), dtype=float)


def weekly_bias(px, direction, grade="A", flip_on=None, flip_to=None):
    weeks = pd.date_range(px.index[0] - pd.Timedelta(days=7), px.index[-1], freq="W-SAT")
    rows = []
    for w in weeks:
        d = flip_to if flip_on is not None and w >= flip_on else direction
        rows.append({"valid_from": w, "direction": d, "grade": grade})
    return pd.DataFrame(rows)


def test_sell_bias_trades_the_bearish_msb_and_reaches_target():
    # after the break at 9.5 (stop 14, risk 4.5) price falls to the 2R target at 0.5
    px = series(DIAGRAM + [8, 6, 4, 2, 0.4])
    trades = simulate_pair("EURUSD", px, weekly_bias(px, "SELL"), P)
    assert len(trades) == 1
    t = trades[0]
    assert (t.direction, t.kind, t.entry, t.stop, t.outcome) == (-1, "MSB", 9.5, 14, "target")
    assert t.r == pytest.approx(2.0)


def test_buy_bias_ignores_bearish_breaks_and_gets_stopped_on_the_msb_down():
    # the bullish MSB at 12.5 is taken; the fall to 9.5 closes below its stop at 10
    px = series(DIAGRAM)
    trades = simulate_pair("EURUSD", px, weekly_bias(px, "BUY"), P)
    assert len(trades) == 1
    assert (trades[0].direction, trades[0].entry, trades[0].outcome, trades[0].r) == (1, 12.5, "stop", -1.0)


def test_grade_b_is_skipped_unless_allowed():
    px = series(DIAGRAM + [8, 6, 4, 2, 0.4])
    assert simulate_pair("EURUSD", px, weekly_bias(px, "SELL", grade="B"), P) == []
    allowed = SimParams(strength=2, stop_buffer_atr=0.0, cost_pips=0.0, allow_grade_b=True)
    assert len(simulate_pair("EURUSD", px, weekly_bias(px, "SELL", grade="B"), allowed)) == 1


def test_bias_flip_closes_the_trade():
    px = series(DIAGRAM + [9.0, 8.8, 8.9, 9.1, 9.0, 8.9, 9.0])
    flip = px.index[20] - pd.Timedelta(days=px.index[20].dayofweek + 2)  # the Saturday before bar 20
    trades = simulate_pair("EURUSD", px, weekly_bias(px, "SELL", flip_on=flip, flip_to="BUY"), P)
    assert trades[0].outcome == "flip"
    assert trades[0].exit == px.iloc[20]


def test_stale_bias_means_no_new_trades():
    px = series(DIAGRAM + [8, 6, 4, 2, 0.4])
    old = pd.DataFrame([{"valid_from": px.index[0] - pd.Timedelta(days=30), "direction": "SELL", "grade": "A"}])
    assert simulate_pair("EURUSD", px, old, P) == []


def test_limit_entry_waits_for_the_retracement():
    # break at 9.5 from a leg topping at 14: sell limit at 11.75, filled on the close at 12
    px = series(DIAGRAM + [9.8, 10.5, 11.2, 12.0, 10.0, 8.0, 7.0])
    limit = SimParams(strength=2, stop_buffer_atr=0.0, cost_pips=0.0, retrace=0.5)
    trades = simulate_pair("EURUSD", px, weekly_bias(px, "SELL"), limit)
    assert len(trades) == 1
    t = trades[0]
    assert (t.entry, t.opened, t.outcome) == (11.75, px.index[23], "target")
    assert t.r == pytest.approx(2.0)


def test_cost_is_charged_in_r():
    px = series(DIAGRAM + [8, 6, 4, 2, 0.4])
    costly = SimParams(strength=2, stop_buffer_atr=0.0, cost_pips=4500.0)  # 4500 pips = 0.45 = 0.1R here
    t = simulate_pair("EURUSD", px, weekly_bias(px, "SELL"), costly)[0]
    assert t.r == pytest.approx(1.9)


def test_summary_numbers():
    px = series(DIAGRAM + [8, 6, 4, 2, 0.4])
    s = summarize(simulate_pair("EURUSD", px, weekly_bias(px, "SELL"), P))
    assert s["trades"] == 1 and s["win_rate_%"] == 100.0 and s["max_drawdown_r"] == 0.0
