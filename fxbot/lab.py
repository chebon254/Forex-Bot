"""Strategy lab: well-known strategies tested on long history, before building any of them.

Every rule uses the standard settings from the research it comes from, fixed before looking
at results. Tuning settings until a backtest looks good is how the COT test fooled us; with
fixed rules the numbers are closer to what you would actually get.

  trend_12m    Time-series momentum (Moskowitz, Ooi & Pedersen, 2012): each month, long the
               pairs that rose over the past 12 months, short the ones that fell.
  ma_50_200    Long while the 50-day average is above the 200-day, short while below.
  donchian     Turtle breakout: enter on a close beyond the 55-day high/low, exit on a close
               beyond the 20-day low/high.
  carry        Each month, hold pairs with an interest differential of at least 1 point, on
               the high-yield side.
  carry_trend  Carry, but only while the 50/200 trend points the same way.
  cot_bias     Your fundamental rules: grade A pairs in the bias direction, updated weekly.

Every pair gets the same risk (weight = signal / its 60-day volatility, updated monthly),
position changes pay the spread, and results are shown on price alone and after retail swaps
(the interest differential minus a broker markup).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import bias, cot, prices, rates
from .currencies import FRED_SERIES, all_pairs

DAYS = 252
DOLLAR_PAIRS = [p for p in all_pairs() if "USD" in p]
DECADES = [(1975, 1984), (1985, 1994), (1995, 2004), (2005, 2014), (2015, 2026)]


@dataclass
class Costs:
    half_spread_dollar: float = 0.0001  # 1 bp, paid on every change of position (~2.3 pips round trip on EURUSD)
    half_spread_cross: float = 0.00015  # 1.5 bp
    swap_markup: float = 0.01  # retail swaps pay ~1%/yr less than the differential (or charge 1% more)
    max_weight: float = 1.0  # never more than 1x equity in one pair


# ---------------------------------------------------------------- data


def load(cfg: dict, since: str = "1975-01-01") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily closes for the 28 pairs (dollar pairs from 1971, crosses from 1999) and each pair's
    interest differential in points (base minus quote) on the same dates."""
    usd = {}
    for ccy, (series_id, usd_per_unit) in FRED_SERIES.items():
        s = prices._series(series_id, cfg["data_dir"], 24)
        usd[ccy] = s if usd_per_unit else 1.0 / s
    usd = pd.DataFrame(usd).sort_index().ffill(limit=3)
    usd["USD"] = 1.0
    px = pd.DataFrame({p: usd[p[:3]] / usd[p[3:]] for p in all_pairs()})
    px = px[px.index >= pd.Timestamp(since)].dropna(how="all")
    r = rates.bis_history(cfg["data_dir"], start="1970-01-01").reindex(px.index, method="ffill")
    diff = pd.DataFrame({p: r[p[:3]] - r[p[3:]] for p in all_pairs()}, index=px.index)
    return px, diff


# ---------------------------------------------------------------- signals (+1 long, -1 short, 0 flat)


def _month_ends(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(index, index=index)
    return (s.groupby(index.to_period("M")).transform("max") == s).to_numpy()


def _monthly(frame: pd.DataFrame) -> pd.DataFrame:
    """Take the value at each month-end and hold it through the next month."""
    out = frame.copy()
    out.loc[~_month_ends(frame.index)] = np.nan
    return out.ffill()


def trend_12m(px: pd.DataFrame) -> pd.DataFrame:
    return _monthly(np.sign(np.log(px).diff(DAYS)))


def ma_50_200(px: pd.DataFrame) -> pd.DataFrame:
    return np.sign(px.rolling(50).mean() - px.rolling(200).mean())


def donchian(px: pd.DataFrame, entry: int = 55, exit: int = 20) -> pd.DataFrame:
    c = px.to_numpy()
    hi_in, lo_in = px.rolling(entry).max().shift(1).to_numpy(), px.rolling(entry).min().shift(1).to_numpy()
    hi_out, lo_out = px.rolling(exit).max().shift(1).to_numpy(), px.rolling(exit).min().shift(1).to_numpy()
    out = np.full(c.shape, np.nan)
    for j in range(c.shape[1]):
        pos = 0
        for t in range(c.shape[0]):
            if np.isnan(c[t, j]) or np.isnan(hi_in[t, j]):
                continue
            if (pos == 1 and c[t, j] < lo_out[t, j]) or (pos == -1 and c[t, j] > hi_out[t, j]):
                pos = 0
            if pos == 0:
                pos = 1 if c[t, j] > hi_in[t, j] else (-1 if c[t, j] < lo_in[t, j] else 0)
            out[t, j] = pos
    return pd.DataFrame(out, index=px.index, columns=px.columns)


def carry(diff: pd.DataFrame, threshold: float = 1.0) -> pd.DataFrame:
    return _monthly(np.sign(diff).where(diff.abs() >= threshold, 0.0))


def carry_trend(diff: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    c, t = carry(diff), ma_50_200(px)
    return c.where(c == t, 0.0)


def cot_bias(cfg: dict, px: pd.DataFrame) -> pd.DataFrame:
    hist = bias.history(cot.load(cfg["data_dir"]), rates.bis_history(cfg["data_dir"]),
                        cfg["cot"]["neutral_band_pct"], cfg["strategy"]["min_carry"])
    graded = hist.assign(d=np.where(hist["grade"] == "A", hist["direction"].map({"BUY": 1, "SELL": -1, "NEUTRAL": 0}), 0))
    weekly = graded.pivot_table(index="valid_from", columns="symbol", values="d", aggfunc="last")
    return weekly.reindex(columns=px.columns).sort_index().reindex(px.index, method="ffill")


# ---------------------------------------------------------------- portfolio and returns


def weights(signal: pd.DataFrame, px: pd.DataFrame, costs: Costs, vol_target: float = 0.10, lookback: int = 60) -> pd.DataFrame:
    """Same risk in every pair: signal / 60-day volatility (updated monthly), shared across the
    pairs that have prices that day."""
    vol = _monthly(px.pct_change().rolling(lookback).std() * np.sqrt(DAYS))
    n = px.notna().sum(axis=1).replace(0, np.nan)
    w = (signal * (vol_target / vol)).div(n, axis=0)
    return w.clip(-costs.max_weight, costs.max_weight).fillna(0.0)


def returns(w: pd.DataFrame, px: pd.DataFrame, diff: pd.DataFrame, costs: Costs) -> dict[str, pd.Series]:
    """Daily returns. The position held on a day is the one set at the previous close."""
    held = w.shift(1).fillna(0.0)
    days = px.index.to_series().diff().dt.days.fillna(1.0)
    price = (held * px.pct_change().fillna(0.0)).sum(axis=1)
    interest = (held * diff.fillna(0.0) / 100.0).mul(days / 365.0, axis=0).sum(axis=1)
    markup = held.abs().mul(days * costs.swap_markup / 365.0, axis=0).sum(axis=1)
    half = pd.Series([costs.half_spread_dollar if "USD" in p else costs.half_spread_cross for p in px.columns], index=px.columns)
    trading = ((w - held).abs() * half).sum(axis=1)
    return {"price only": price - trading, "after retail swaps": price + interest - markup - trading}


def stats(r: pd.Series) -> dict:
    """Sharpe is scale-free; the growth and drawdown figures are for the strategy run at 10%
    yearly volatility, so strategies compare fairly."""
    r = r[(r != 0).cumsum() > 0]
    years = len(r) / DAYS
    mean, sd = r.mean() * DAYS, r.std() * np.sqrt(DAYS)
    scaled = r * (0.10 / sd)
    equity = (1 + scaled).cumprod()
    yearly = (1 + scaled).groupby(scaled.index.year).prod() - 1
    return {
        "from": scaled.index[0].year,
        "sharpe": mean / sd,
        "t_stat": mean / sd * np.sqrt(years),
        "yearly_%_at_10%_vol": 100 * (equity.iloc[-1] ** (1 / years) - 1),
        "max_drawdown_%": 100 * (1 - equity / equity.cummax()).max(),
        "losing_years_%": 100 * (yearly < 0).mean(),
        "worst_year_%": 100 * yearly.min(),
    }


def decade_sharpes(r: pd.Series) -> dict:
    out = {}
    for a, b in DECADES:
        part = r[(r.index.year >= a) & (r.index.year <= b)]
        part = part[(part != 0).cumsum() > 0]
        out[f"{a}-{str(b)[2:]}"] = part.mean() / part.std() * np.sqrt(DAYS) if len(part) > DAYS else np.nan
    return out


# ---------------------------------------------------------------- the whole lab


def run(cfg: dict, costs: Costs | None = None) -> dict:
    costs = costs or Costs()
    px_all, diff_all = load(cfg)
    universes = {
        "dollar pairs 1975-2026": (DOLLAR_PAIRS, "1975-01-01"),
        "all 28 pairs 2000-2026": (all_pairs(), "2000-01-01"),
    }
    rows, decades = [], []
    for universe, (cols, since) in universes.items():
        px = px_all.loc[px_all.index >= since, cols]
        diff = diff_all.loc[px.index, cols]
        signals = {
            "trend_12m": trend_12m(px),
            "ma_50_200": ma_50_200(px),
            "donchian": donchian(px),
            "carry": carry(diff),
            "carry_trend": carry_trend(diff, px),
        }
        if since >= "1999":
            signals["cot_bias"] = cot_bias(cfg, px)
        for name, sig in signals.items():
            for mode, series in returns(weights(sig, px, costs), px, diff, costs).items():
                rows.append({"universe": universe, "strategy": name, "returns": mode, **stats(series)})
                if since < "1999" and mode == "after retail swaps":
                    decades.append({"strategy": name, **decade_sharpes(series)})
    return {
        "table": pd.DataFrame(rows).set_index(["universe", "strategy", "returns"]),
        "decades": pd.DataFrame(decades).set_index("strategy"),
        "costs": costs,
    }


# ---------------------------------------------------------------- stock index strategies (US100 CFD)
#
#   buy_and_hold  The benchmark.
#   above_200d    Hold the index only while it closes above its 200-day average (Faber, 2007).
#   rsi2_dip      Buy when the index is above its 200-day average and the 2-day RSI closes below
#                 10; sell on a close above the 5-day average (Connors, 2008).
#
# CFD reality: a long position pays overnight financing (benchmark rate + a markup) every day.

INDEXES = {"NASDAQ Composite": "NASDAQCOM", "NASDAQ 100": "NASDAQ100"}


def rsi(close: pd.Series, n: int = 2) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


def index_positions(close: pd.Series, trend_days: int = 200, rsi_days: int = 2, buy_below: float = 10.0,
                    exit_days: int = 5) -> dict[str, pd.Series]:
    ma200, ma5, r2 = close.rolling(trend_days).mean(), close.rolling(exit_days).mean(), rsi(close, rsi_days)
    dip, pos = [], 0
    for c, m200, m5, r in zip(close, ma200, ma5, r2):
        if pos == 1 and c > m5:
            pos = 0
        elif pos == 0 and c > m200 and r < buy_below:
            pos = 1
        dip.append(pos)
    return {
        "buy_and_hold": pd.Series(1.0, index=close.index),
        "above_200d": (close > ma200).astype(float),
        "rsi2_dip": pd.Series(dip, index=close.index, dtype=float),
    }


def index_returns(pos: pd.Series, close: pd.Series, cash_rate: pd.Series,
                  half_spread: float = 0.0001, markup: float = 0.025) -> dict[str, pd.Series]:
    held = pos.shift(1).fillna(0.0)
    days = close.index.to_series().diff().dt.days.fillna(1.0)
    price = held * close.pct_change().fillna(0.0) - (pos - held).abs() * half_spread
    financing = held * (cash_rate / 100.0 + markup) * days / 365.0
    return {"price only": price, "after CFD financing": price - financing}


def plain_stats(r: pd.Series) -> dict:
    """At 1x exposure, no leverage: what the account would have done."""
    r = r[r.index >= r.index[0] + pd.Timedelta(days=300)]  # skip the 200-day warm-up
    years = len(r) / DAYS
    equity = (1 + r).cumprod()
    return {
        "sharpe": r.mean() / r.std() * np.sqrt(DAYS),
        "t_stat": r.mean() / r.std() * np.sqrt(len(r)),
        "yearly_%": 100 * (equity.iloc[-1] ** (1 / years) - 1),
        "max_drawdown_%": 100 * (1 - equity / equity.cummax()).max(),
        "time_in_market_%": np.nan,
    }


def index_lab(cfg: dict) -> dict:
    cash = prices._series("DFF", cfg["data_dir"], 24)
    rows, decades = [], []
    for name, series_id in INDEXES.items():
        close = prices._series(series_id, cfg["data_dir"], 24).dropna()
        rate = cash.reindex(close.index, method="ffill")
        for strategy, pos in index_positions(close).items():
            for mode, r in index_returns(pos, close, rate).items():
                row = {"index": name, "strategy": strategy, "returns": mode, **plain_stats(r)}
                row["time_in_market_%"] = 100 * pos.iloc[300:].mean()
                rows.append(row)
                if mode == "after CFD financing":
                    decades.append({"index": name, "strategy": strategy, **decade_sharpes(r.iloc[300:])})
    return {
        "table": pd.DataFrame(rows).set_index(["index", "strategy", "returns"]),
        "decades": pd.DataFrame(decades).set_index(["index", "strategy"]),
    }
