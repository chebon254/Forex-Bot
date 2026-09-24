"""Your strategy as a day trade: only from the London open to New York midday.

Runs on FBS's own 15-minute bars (exported from MT5 with mt5/ExportBars.mq5) with the weekly
COT + interest-rate bias. Three tests, rules fixed in advance:

  bias_drift   Open every grade A pair in the bias direction at the London open and close it
               at New York midday. Does the bias predict the day's move by itself?
  bias_msb     Your strategy, intraday: inside the window, enter on a market structure break
               (15-minute swings, strength 3, MSB only) in the bias direction; stop beyond the
               breaking leg, target 2R, anything still open closes at New York midday.
  msb_no_bias  The same entries in both directions, ignoring the bias - the control.

Times are FBS server time (EET/EEST, New York close = midnight): London 08:00 = 10:00 and
New York 12:00 = 19:00 all year (except ~3 weeks when US and EU clocks change on different
dates). Fills are pessimistic: buys pay the recorded spread, stops are checked against each
bar's high/low, a bar that touches both stop and target counts as a stop, plus 0.3 pips of
slippage per trade.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import bias, cot, export, rates
from .currencies import all_pairs, pip_size
from .structure import analyze, atr

BAR = np.dtype([("time", "<i8"), ("open", "<i4"), ("high", "<i4"), ("low", "<i4"), ("close", "<i4"), ("spread", "<i4")])
WINDOW_START = 10 * 60  # London 08:00, in server minutes after midnight
WINDOW_END = 19 * 60  # New York 12:00


@dataclass
class Params:
    strength: int = 3
    reward_risk: float = 2.0
    stop_buffer_atr: float = 0.1
    slippage_pips: float = 0.3
    max_bias_age_days: int = 10


# ---------------------------------------------------------------- data


def bars_folder(cfg: dict) -> Path:
    setting = str(cfg["mt5"].get("common_files_dir") or "auto")
    base = export.find_mt5_common_dirs()[0] if setting == "auto" else Path(setting).expanduser()
    return base / "bars"


def load_bars(folder: Path, symbol: str, timeframe: str = "M15") -> pd.DataFrame:
    """One symbol's bars in prices (spread too), indexed by FBS server time."""
    meta = pd.read_csv(folder / "meta.csv", skipinitialspace=True).set_index("symbol")
    point = float(meta.loc[symbol, "point"])
    raw = np.fromfile(folder / f"{symbol}_{timeframe}.bin", dtype=BAR)
    idx = pd.to_datetime(raw["time"], unit="s")
    return pd.DataFrame({k: raw[k] * point for k in ("open", "high", "low", "close", "spread")}, index=idx)


def weekly_bias(cfg: dict) -> pd.DataFrame:
    return bias.history(cot.load(cfg["data_dir"]), rates.bis_history(cfg["data_dir"]),
                        cfg["cot"]["neutral_band_pct"], cfg["strategy"]["min_carry"])


def bias_per_bar(index: pd.DatetimeIndex, rows: pd.DataFrame, max_age_days: int) -> np.ndarray:
    """+1/-1 where a fresh grade A bias applies to the bar, else 0."""
    rows = rows.sort_values("valid_from")
    vf = rows["valid_from"].to_numpy(dtype="datetime64[ns]")
    d = np.where(rows["grade"].to_numpy() == "A", rows["direction"].map({"BUY": 1, "SELL": -1, "NEUTRAL": 0}).to_numpy(), 0)
    t = index.to_numpy(dtype="datetime64[ns]")
    k = np.searchsorted(vf, t, side="right") - 1
    fresh = (k >= 0) & (t - vf[np.maximum(k, 0)] <= np.timedelta64(max_age_days, "D"))
    return np.where(fresh, d[np.maximum(k, 0)], 0)


# ---------------------------------------------------------------- the three tests


def drift_trades(symbol: str, bars: pd.DataFrame, bias_dir: np.ndarray, p: Params) -> pd.DataFrame:
    """bias_drift: London-open entry, New York-midday exit, no stop. Returns in pips."""
    minutes = bars.index.hour * 60 + bars.index.minute
    day = bars.index.normalize()
    first = pd.Series(np.arange(len(bars)))[minutes == WINDOW_START].groupby(day[minutes == WINDOW_START]).first()
    last = pd.Series(np.arange(len(bars)))[(minutes >= WINDOW_START) & (minutes < WINDOW_END)]
    last = last.groupby(day[(minutes >= WINDOW_START) & (minutes < WINDOW_END)]).last()
    days = first.index.intersection(last.index)
    o, c, sp = bars["open"].to_numpy(), bars["close"].to_numpy(), bars["spread"].to_numpy()
    rows = []
    for d in days:
        i, j = first[d], last[d]
        direction = bias_dir[i]
        if direction == 0 or bars.index[j].hour * 60 + bars.index[j].minute != WINDOW_END - 15:
            continue  # no bias, or the window was cut short (holiday)
        entry = o[i] + (sp[i] if direction > 0 else 0.0)  # buys pay the ask
        exit_ = c[j] + (sp[j] if direction < 0 else 0.0)  # shorts buy back at the ask
        pips = direction * (exit_ - entry) / pip_size(symbol) - p.slippage_pips
        rows.append({"symbol": symbol, "day": d, "direction": direction, "pips": pips})
    return pd.DataFrame(rows)


def msb_trades(symbol: str, bars: pd.DataFrame, bias_dir: np.ndarray | None, p: Params, structure=None) -> pd.DataFrame:
    """bias_msb (with bias_dir) or msb_no_bias (bias_dir=None). Returns one row per trade, in R.
    Pass `structure` (from structure.analyze) to reuse it across calls."""
    h, l, c, o, sp = (bars[k].to_numpy() for k in ("high", "low", "close", "open", "spread"))
    minutes = (bars.index.hour * 60 + bars.index.minute).to_numpy()
    day = bars.index.normalize().to_numpy()
    vol = atr(h, l, c, 14)
    structure = structure or analyze(h, l, c, p.strength)
    pip = pip_size(symbol)
    rows, busy_until = [], -1
    for brk in structure.breaks:
        j = brk.bar
        entry_minute = minutes[j] + 15  # entry at the close of the breaking bar
        if brk.kind != "MSB" or j <= busy_until or not (WINDOW_START <= entry_minute <= WINDOW_END - 15):
            continue
        d = brk.direction
        if bias_dir is not None and bias_dir[j] != d:
            continue
        buffer = p.stop_buffer_atr * (vol[j] if np.isfinite(vol[j]) else 0.0)
        entry = c[j] + (sp[j] if d > 0 else 0.0)
        stop = brk.range_low - buffer if d > 0 else brk.range_high + buffer
        risk = abs(entry - stop)
        if risk <= 0 or (d > 0 and stop >= entry) or (d < 0 and stop <= entry):
            continue
        target = entry + d * p.reward_risk * risk
        k, outcome, exit_ = j + 1, "time", None
        while k < len(c) and day[k] == day[j] and minutes[k] < WINDOW_END:
            if d > 0:  # long: exits sell at the bid (bar prices are bids)
                if l[k] <= stop:
                    exit_, outcome = min(stop, o[k]), "stop"
                elif h[k] >= target:
                    exit_, outcome = target, "target"  # never assume a better fill than the target
            else:  # short: exits buy at the ask = bid + spread
                if h[k] + sp[k] >= stop:
                    exit_, outcome = max(stop, o[k] + sp[k]), "stop"
                elif l[k] + sp[k] <= target:
                    exit_, outcome = target, "target"
            if exit_ is not None:
                break
            k += 1
        if exit_ is None:  # New York midday: close at the last bar of the window
            k -= 1
            exit_ = c[k] + (sp[k] if d < 0 else 0.0)
        r = d * (exit_ - entry) / risk - p.slippage_pips * pip / risk
        rows.append({"symbol": symbol, "time": bars.index[j], "direction": d, "risk_pips": risk / pip,
                     "r": r, "outcome": outcome})
        busy_until = k
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- summaries


def summarize_r(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0}
    t = t.sort_values("time")
    eq = t["r"].cumsum().to_numpy()
    years = (t["time"].iloc[-1] - t["time"].iloc[0]).days / 365.25
    losses = -t.loc[t["r"] <= 0, "r"].sum()
    return {
        "trades": len(t),
        "per_year": len(t) / years,
        "win_%": 100 * (t["r"] > 0).mean(),
        "avg_r": t["r"].mean(),
        "t_stat": t["r"].mean() / t["r"].std() * np.sqrt(len(t)),
        "total_r": t["r"].sum(),
        "profit_factor": t.loc[t["r"] > 0, "r"].sum() / losses if losses > 0 else np.inf,
        "max_dd_r": (np.maximum.accumulate(np.concatenate(([0.0], eq)))[1:] - eq).max(),
        "median_stop_pips": t["risk_pips"].median(),
        "exits": t["outcome"].value_counts().to_dict(),
        "by_year": t.groupby(t["time"].dt.year)["r"].sum().round(1).to_dict(),
    }


def summarize_pips(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0}
    daily = t.groupby("day")["pips"].mean()
    return {
        "trades": len(t),
        "win_%": 100 * (t["pips"] > 0).mean(),
        "avg_pips": t["pips"].mean(),
        "t_stat": t["pips"].mean() / t["pips"].std() * np.sqrt(len(t)),
        "daily_basket_t_stat": daily.mean() / daily.std() * np.sqrt(len(daily)),
        "by_year_avg_pips": t.groupby(t["day"].dt.year)["pips"].mean().round(2).to_dict(),
    }


def run(cfg: dict, p: Params | None = None, symbols: list[str] | None = None) -> dict:
    p = p or Params()
    folder = bars_folder(cfg)
    hist = weekly_bias(cfg)
    drift, with_bias, no_bias = [], [], []
    for symbol in symbols or all_pairs():
        bars = load_bars(folder, symbol)
        bdir = bias_per_bar(bars.index, hist[hist["symbol"] == symbol], p.max_bias_age_days)
        drift.append(drift_trades(symbol, bars, bdir, p))
        structure = analyze(bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy(), p.strength)
        with_bias.append(msb_trades(symbol, bars, bdir, p, structure))
        no_bias.append(msb_trades(symbol, bars, None, p, structure))
    frames = {"bias_drift": pd.concat(drift), "bias_msb": pd.concat(with_bias), "msb_no_bias": pd.concat(no_bias)}
    return {
        "frames": frames,
        "bias_drift": summarize_pips(frames["bias_drift"]),
        "bias_msb": summarize_r(frames["bias_msb"]),
        "msb_no_bias": summarize_r(frames["msb_no_bias"]),
        "params": p,
    }
