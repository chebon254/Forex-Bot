"""Test the strategy on history before risking money.

1. Edge study - does the weekly bias on its own point the right way? For every week since
   2000, how did pairs move over the next 1 and 4 weeks in the direction the bot called?
2. Strategy simulation - the full trade: bias + market structure break + limit entry at the
   retracement, stop beyond the leg, target at a multiple of the risk.

Both run on FRED daily closes: no intraday highs/lows and a flat cost per trade, so treat
them as a first filter. The definitive test is MT5's Strategy Tester on FBS's own data with
the history file that `fxbot export` writes.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import bias, cot, prices, rates
from .currencies import all_pairs, pip_size
from .structure import analyze, atr, entry_levels

DIR = {"BUY": 1, "SELL": -1, "NEUTRAL": 0}


# ---------------------------------------------------------------- edge study


def forward_returns(bias_hist: pd.DataFrame, px: pd.DataFrame, horizon_weeks: int) -> pd.DataFrame:
    """Adds `fwd`: log return of each pair from the Monday the bias applies to `horizon_weeks` later."""
    weeks = pd.DatetimeIndex(sorted(bias_hist["valid_from"].unique()))
    start = px.index.searchsorted(weeks)
    end = px.index.searchsorted(weeks + pd.Timedelta(weeks=horizon_weeks))
    ok = end < len(px.index)
    logpx = np.log(px.to_numpy())
    fwd = np.full((len(weeks), px.shape[1]), np.nan)
    fwd[ok] = logpx[end[ok]] - logpx[start[ok]]
    table = pd.DataFrame(fwd, index=weeks, columns=px.columns).stack().rename("fwd")
    out = bias_hist.join(table, on=["valid_from", "symbol"])
    return out.dropna(subset=["fwd"])


def edge_study(bias_hist: pd.DataFrame, px: pd.DataFrame, horizon_weeks: int, min_carry: float) -> pd.DataFrame:
    """One row per rule: how an equal-weight basket of its signals did, per `horizon_weeks` period."""
    df = forward_returns(bias_hist, px, horizon_weeks)
    # Non-overlapping periods only, so the statistics are honest.
    periods = sorted(df["valid_from"].unique())[::horizon_weeks]
    df = df[df["valid_from"].isin(periods)].copy()

    df["cot_dir"] = df["direction"].map(DIR)
    df["carry_dir"] = np.where(df["differential"].abs() >= min_carry, np.sign(df["differential"]), 0)
    rules = {
        "Grade A: COT + carry agree": np.where(df["grade"] == "A", df["cot_dir"], 0),
        "COT only (grades A+B)": df["cot_dir"],
        "Grade B: COT against carry": np.where(df["grade"] == "B", df["cot_dir"], 0),
        "Carry only (buy the higher rate)": df["carry_dir"],
    }
    rows = []
    for name, direction in rules.items():
        sig = df.assign(d=direction)
        sig = sig[sig["d"] != 0]
        signal_returns = sig["d"] * sig["fwd"]
        basket = signal_returns.groupby(sig["valid_from"]).mean().reindex(periods, fill_value=0.0)
        per_year = 52 / horizon_weeks
        mean, std = basket.mean(), basket.std()
        rows.append(
            {
                "rule": name,
                "signals": len(sig),
                "signal_hit_%": 100 * (signal_returns > 0).mean() if len(sig) else np.nan,
                "avg_signal_%": 100 * signal_returns.mean() if len(sig) else np.nan,
                "basket_return_%/yr": 100 * mean * per_year,
                "basket_vol_%/yr": 100 * std * np.sqrt(per_year),
                "sharpe": mean / std * np.sqrt(per_year) if std > 0 else np.nan,
                "t_stat": mean / (std / np.sqrt(len(basket))) if std > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("rule")


# ---------------------------------------------------------------- trade simulation


@dataclass
class SimParams:
    """Mirrors the EA's inputs (defaults match mt5/FxBot.mq5)."""

    strength: int = 3
    retrace: float = 0.0  # 0 = enter at the break's close; 0.5 = limit order at 50% of the leg
    expiry_bars: int = 10
    reward_risk: float = 2.0
    stop_buffer_atr: float = 0.1
    msb_only: bool = True
    allow_grade_b: bool = False
    exit_on_flip: bool = True
    max_bias_age_days: int = 10
    cost_pips: float = 2.0
    use_bias: bool = True  # False = technicals only: trade every break in its own direction


@dataclass
class Trade:
    symbol: str
    direction: int
    grade: str
    kind: str
    placed: pd.Timestamp
    opened: pd.Timestamp
    closed: pd.Timestamp
    entry: float
    stop: float
    target: float
    exit: float
    r: float
    outcome: str  # target, stop, flip, or open (still running at the end of the data)


def simulate_pair(symbol: str, px: pd.Series, bias_rows: pd.DataFrame, p: SimParams) -> list[Trade]:
    px = px.dropna()
    close = px.to_numpy()
    dates = px.index
    d64 = dates.to_numpy(dtype="datetime64[ns]")
    structure = analyze(close, close, close, p.strength)
    breaks_at: dict[int, list] = {}
    for brk in structure.breaks:
        breaks_at.setdefault(brk.bar, []).append(brk)
    vol = atr(close, close, close, 14)

    rows = bias_rows.sort_values("valid_from")
    valid_from = rows["valid_from"].to_numpy(dtype="datetime64[ns]")
    dirs = rows["direction"].map(DIR).to_numpy()
    grades = rows["grade"].to_numpy()
    idx = np.searchsorted(valid_from, d64, side="right") - 1
    max_age = np.timedelta64(p.max_bias_age_days, "D")
    pip = pip_size(symbol)

    def finish(pos, when, price, outcome):
        risk = abs(pos["entry"] - pos["stop"])
        r = pos["dir"] * (price - pos["entry"]) / risk - p.cost_pips * pip / risk
        return Trade(symbol, pos["dir"], pos["grade"], pos["kind"], pos["placed"], pos["opened"], when,
                     pos["entry"], pos["stop"], pos["target"], price, r, outcome)

    trades, pos, order = [], None, None
    for t, price in enumerate(close):
        k = idx[t]
        fresh = k >= 0 and d64[t] - valid_from[k] <= max_age
        bias_dir = int(dirs[k]) if fresh else 0
        grade = grades[k] if k >= 0 else "-"
        want = bias_dir if (grade == "A" or (p.allow_grade_b and grade == "B")) else 0
        if not p.use_bias:
            bias_dir = 0

        # 1. a pending limit order fills when price trades back to it
        if order is not None and t > order["bar"]:
            if (order["dir"] < 0 and price >= order["entry"]) or (order["dir"] > 0 and price <= order["entry"]):
                pos, order = {**order, "opened": dates[t]}, None
        # 2. stop loss / take profit (these sit on the broker's server in MT5)
        if pos is not None:
            d = pos["dir"]
            if (d < 0 and price >= pos["stop"]) or (d > 0 and price <= pos["stop"]):
                # With closing prices only, a breach is first seen at a close, so exit there.
                # (Filling at the stop level instead would be optimistic: it keeps the close-only
                # view's fewer stop-outs but not its worse fills. A real stop also fires on wicks.)
                trades.append(finish(pos, dates[t], price, "stop"))
                pos = None
            elif (d < 0 and price <= pos["target"]) or (d > 0 and price >= pos["target"]):
                trades.append(finish(pos, dates[t], pos["target"], "target"))
                pos = None
        # 3. the weekly bias turned against the open trade
        if pos is not None and p.exit_on_flip and bias_dir == -pos["dir"]:
            trades.append(finish(pos, dates[t], price, "flip"))
            pos = None
        # 4. a pending order the bias no longer supports, or that waited too long
        if order is not None and ((p.use_bias and want != order["dir"]) or t - order["bar"] >= p.expiry_bars):
            order = None
        # 5. a structure break on this bar, in the bias direction, sets up a trade
        for brk in breaks_at.get(t, ()):
            if pos is not None or (p.use_bias and brk.direction != want):
                continue
            if p.msb_only and brk.kind != "MSB":
                continue
            buffer = p.stop_buffer_atr * (vol[t] if np.isfinite(vol[t]) else 0.0)
            entry, stop, target = entry_levels(brk, p.retrace, p.reward_risk, buffer, price)
            if entry == stop:
                continue
            setup = dict(dir=brk.direction, entry=entry, stop=stop, target=target, bar=t,
                         placed=dates[t], kind=brk.kind, grade=grade)
            if p.retrace > 0:
                order = setup  # a newer setup replaces an older pending order
            else:
                pos, order = {**setup, "opened": dates[t]}, None
    if pos is not None:
        trades.append(finish(pos, dates[-1], close[-1], "open"))
    return trades


def summarize(trades: list[Trade]) -> dict:
    done = sorted((t for t in trades if t.outcome != "open"), key=lambda t: t.closed)
    if not done:
        return {"trades": 0}
    r = np.array([t.r for t in done])
    equity = np.cumsum(r)
    drawdown = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:] - equity
    years = max((done[-1].closed - done[0].placed).days / 365.25, 1e-9)
    losses = -r[r <= 0].sum()
    by_year = pd.Series(r, index=[t.closed.year for t in done]).groupby(level=0).sum()
    return {
        "trades": len(done),
        "trades_per_year": len(done) / years,
        "win_rate_%": 100 * (r > 0).mean(),
        "avg_r": r.mean(),
        "total_r": r.sum(),
        "profit_factor": r[r > 0].sum() / losses if losses > 0 else np.inf,
        "max_drawdown_r": drawdown.max(),
        "outcomes": pd.Series([t.outcome for t in done]).value_counts().to_dict(),
        "by_year": by_year,
    }


# ---------------------------------------------------------------- everything together


def load_history(cfg: dict, since: str):
    """Weekly bias history (BIS rates + CFTC COT) and daily closes for all 28 pairs."""
    cot_df = cot.load(cfg["data_dir"])
    rates_hist = rates.bis_history(cfg["data_dir"])
    hist = bias.history(cot_df, rates_hist, cfg["cot"]["neutral_band_pct"], cfg["strategy"]["min_carry"])
    hist = hist[hist["valid_from"] >= pd.Timestamp(since)].reset_index(drop=True)
    values = prices.usd_values(cfg["data_dir"])
    px = pd.DataFrame({s: prices.closes(values, s) for s in all_pairs()})
    return hist, px


def run(cfg: dict, since: str = "2000-01-01", params: SimParams | None = None) -> dict:
    params = params or SimParams()
    hist, px = load_history(cfg, since)
    min_carry = cfg["strategy"]["min_carry"]
    edge = {h: edge_study(hist, px, h, min_carry) for h in (1, 4)}
    # Warm-up: structure needs some bars before the first bias week.
    px_sim = px[px.index >= pd.Timestamp(since) - pd.Timedelta(days=120)]
    trades = []
    for symbol in all_pairs():
        trades += simulate_pair(symbol, px_sim[symbol], hist[hist["symbol"] == symbol], params)
    per_pair = (
        pd.DataFrame([{"symbol": t.symbol, "r": t.r} for t in trades if t.outcome != "open"])
        .groupby("symbol")["r"].agg(["count", "sum", "mean"])
        .sort_values("sum", ascending=False)
        if trades else pd.DataFrame()
    )
    return {
        "since": since,
        "weeks": hist["valid_from"].nunique(),
        "edge": edge,
        "trades": trades,
        "summary": summarize(trades),
        "per_pair": per_pair,
        "params": params,
    }
