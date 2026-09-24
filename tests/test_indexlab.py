import numpy as np
import pandas as pd
import pytest

from fxbot import indexlab, lab


def test_ea_rsi_matches_the_research_rsi_once_warmed_up():
    rng = np.random.default_rng(3)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 600)))
    assert indexlab.ea_rsi(close.to_numpy()[-260:]) == pytest.approx(lab.rsi(close, 2).iloc[-1], abs=1e-6)


def test_mt5_report_orders_after_midnight_belong_to_the_previous_decision(tmp_path):
    rows = "".join(f"<tr><td>{t}</td><td>{i}</td><td>US100</td><td>{side}</td><td>{d}</td><td>0.1</td><td>1</td>"
                   f"<td>{i}</td><td>0</td><td>0</td><td>0</td><td>0</td><td>{c}</td></tr>"
                   for i, (t, side, d, c) in enumerate([
                       ("2024.11.14 22:45:00", "buy", "in", "IndexBot dip"),
                       ("2024.11.19 00:05:00", "sell", "out", ""),  # retried after midnight
                       ("2026.09.23 23:59:59", "sell", "out", "end of test")]))
    report = tmp_path / "r.htm"
    header = "<tr><th>Time</th><th>Deal</th><th>Symbol</th><th>Type</th><th>Direction</th><th>Volume</th><th>Price</th>" \
             "<th>Order</th><th>Commission</th><th>Swap</th><th>Profit</th><th>Balance</th><th>Comment</th></tr>"
    report.write_bytes(("<table>" + header + rows + "</table>").encode("utf-16"))
    assert indexlab.mt5_trades(report) == [(pd.Timestamp("2024-11-14"), "buy"), (pd.Timestamp("2024-11-18"), "sell")]


def test_missing_no_days_changes_nothing():
    close = pd.Series(np.linspace(100, 200, 400), index=pd.bdate_range("2020-01-01", periods=400))
    base = indexlab.perf(indexlab.strategy_returns(close)["both"])
    assert indexlab.missed_days(close).loc[0.0, "sharpe"] == pytest.approx(base["sharpe"])
