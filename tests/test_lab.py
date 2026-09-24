import numpy as np
import pandas as pd
import pytest

from fxbot import lab


def frame(values, cols=("EURUSD",)):
    idx = pd.bdate_range("2020-01-01", periods=len(values))
    return pd.DataFrame({c: values for c in cols}, index=idx, dtype=float)


def test_returns_use_yesterdays_position_so_nothing_looks_ahead():
    px = frame([100, 110, 121])
    w = frame([1.0, 1.0, 0.0])  # decided at each close
    r = lab.returns(w, px, px * 0, lab.Costs(half_spread_dollar=0.0))["price only"]
    # day 2 earns +10% on the position set at day 1's close; day 3 earns +10% on the day-2 position
    assert r.tolist() == pytest.approx([0.0, 0.10, 0.10])


def test_trading_cost_is_charged_on_position_changes():
    px = frame([100, 100, 100])
    w = frame([1.0, 1.0, -1.0])
    r = lab.returns(w, px, px * 0, lab.Costs(half_spread_dollar=0.001))["price only"]
    assert r.tolist() == pytest.approx([-0.001, 0.0, -0.002])  # open, hold, flip long->short


def test_donchian_enters_on_breakout_and_exits_on_opposite_channel():
    up = list(np.linspace(100, 110, 60))  # steady rise: breaks the 55-day high
    down = list(np.linspace(110, 100, 30))  # falls through the 20-day low
    sig = lab.donchian(frame(up + down)).iloc[:, 0]
    assert sig.iloc[56] == 1  # long after the 55-day high breaks
    assert (sig.iloc[-5:] <= 0).all()  # out (or short) after the drop


def test_rsi2_dip_buys_a_pullback_in_an_uptrend_and_sells_the_bounce():
    close = pd.Series(np.r_[np.linspace(100, 200, 250), [190, 185, 200, 205]],
                      index=pd.bdate_range("2020-01-01", periods=254))
    pos = lab.index_positions(close)["rsi2_dip"]
    assert pos.iloc[251] == 1  # two down closes above the 200-day average: buy
    assert pos.iloc[252] == 0  # close back above the 5-day average: sell
