import numpy as np
import pandas as pd
import pytest

from fxbot import intraday

# The market-structure diagram, placed so the bearish MSB bar (index 17) opens at 10:15 server
# time: inside the London open -> New York midday window.
DIAGRAM = [10, 9, 8, 9, 10, 11, 12, 11, 10.5, 10, 11, 12.5, 13, 14, 13, 12, 11, 9.5, 9, 9.2]


def bars(path, start="2024-01-02 06:00", spread=0.0):
    idx = pd.date_range(start, periods=len(path), freq="15min")
    p = np.asarray(path, dtype=float)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "spread": spread}, index=idx)


P = intraday.Params(strength=2, stop_buffer_atr=0.0, slippage_pips=0.0)


def test_short_on_msb_in_window_hits_target():
    b = bars(DIAGRAM + [8, 6, 4, 2, 0.4])
    t = intraday.msb_trades("EURUSD", b, np.full(len(b), -1), P)
    assert len(t) == 1
    assert (t.iloc[0]["direction"], t.iloc[0]["outcome"]) == (-1, "target")
    assert t.iloc[0]["r"] == pytest.approx(2.0)  # entry 9.5, stop 14, target 0.5


def test_open_trade_closes_at_new_york_midday():
    b = bars(DIAGRAM + [9.0] * 60)  # drifts sideways until the window ends at 19:00
    t = intraday.msb_trades("EURUSD", b, np.full(len(b), -1), P)
    assert t.iloc[0]["outcome"] == "time"
    assert t.iloc[0]["r"] == pytest.approx((9.5 - 9.0) / 4.5)


def test_no_trade_against_the_bias_or_outside_the_window():
    b = bars(DIAGRAM + [8, 6, 4, 2, 0.4])
    assert intraday.msb_trades("EURUSD", b, np.full(len(b), 1), P).empty  # bias says buy
    early = bars(DIAGRAM + [8, 6, 4, 2, 0.4], start="2024-01-02 01:00")  # break at 05:15
    assert intraday.msb_trades("EURUSD", early, np.full(len(early), -1), P).empty


def test_shorts_pay_the_spread_when_buying_back():
    b = bars(DIAGRAM + [9.0] * 60, spread=0.1)
    t = intraday.msb_trades("EURUSD", b, np.full(len(b), -1), P)
    assert t.iloc[0]["r"] == pytest.approx((9.5 - 9.1) / 4.5)  # exit at the ask = 9.0 + 0.1
