"""IndexBot stress tests: is the edge real, or did we get lucky with the NASDAQ?

  markets      The same rules, unchanged, on every stock index FBS offers (FBS daily bars,
               2013-2026) and on the NASDAQ Composite back to 1971.
  settings     Nearby settings (150/200/250-day trend, RSI 5/10/15, 3/5/10-day exit): a real edge
               survives small changes; a lucky one falls apart.
  costs        Higher swaps and spreads than FBS charges today.
  luck         Reshuffle 40 years of history in one-year blocks, many times: the range of 10-year
               outcomes, not just the one path that happened.
  missed_days  MT5 not running at 22:45 on some days (laptop off): act a day late.
  parity       Replay the EA's exact daily decisions on FBS data and match them, trade by trade,
               with the MT5 Strategy Tester's trades.

Costs are FBS-like: a flat ~4%/yr swap on long positions (what the MT5 runs showed for US100)
and a 1 bp spread each time the position changes.
"""

import html
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import export, intraday, lab, prices

DAYS = 252
SWAP = 0.04
HALF_SPREAD = 0.0001
FBS_INDEXES = ["US100", "US500", "US30", "DE30", "UK100", "JP225", "EU50", "FR40", "HK50", "ES35"]


def _common(cfg: dict) -> Path:
    setting = str(cfg["mt5"].get("common_files_dir") or "auto")
    return export.find_mt5_common_dirs()[0] if setting == "auto" else Path(setting).expanduser()


def strategy_returns(close: pd.Series, swap: float = SWAP, half_spread: float = HALF_SPREAD, **rule_settings) -> dict[str, pd.Series]:
    """Daily returns of both rules (0.5x each), each rule alone (1x) and buy-and-hold (1x)."""
    zero = pd.Series(0.0, index=close.index)
    pos = lab.index_positions(close, **rule_settings)
    r = {k: lab.index_returns(v, close, zero, half_spread=half_spread, markup=swap)["after CFD financing"] for k, v in pos.items()}
    return {"both": 0.5 * r["above_200d"] + 0.5 * r["rsi2_dip"], "trend": r["above_200d"], "dip": r["rsi2_dip"],
            "buy_and_hold": r["buy_and_hold"]}


def perf(r: pd.Series) -> dict:
    r = r.iloc[300:]  # skip the 200-day warm-up
    years = len(r) / DAYS
    eq = (1 + r).cumprod()
    return {
        "sharpe": r.mean() / r.std() * np.sqrt(DAYS),
        "yearly_%": 100 * (eq.iloc[-1] ** (1 / years) - 1),
        "max_dd_%": 100 * (1 - eq / eq.cummax()).max(),
        "years": round(years, 1),
    }


# ---------------------------------------------------------------- the tests


def markets(cfg: dict) -> pd.DataFrame:
    rows = []
    folder = _common(cfg) / "bars_index"
    series = {f"{s} (FBS)": intraday.load_bars(folder, s, "D1")["close"] for s in FBS_INDEXES}
    series["NASDAQ Composite 1971- (FRED)"] = prices._series("NASDAQCOM", cfg["data_dir"], 24).dropna()
    series["NASDAQ 100 1986- (FRED)"] = prices._series("NASDAQ100", cfg["data_dir"], 24).dropna()
    for name, close in series.items():
        res = strategy_returns(close)
        row = {"market": name}
        for k in ("both", "buy_and_hold"):
            p = perf(res[k])
            row.update({f"{k}_sharpe": p["sharpe"], f"{k}_yearly_%": p["yearly_%"], f"{k}_max_dd_%": p["max_dd_%"]})
        row["trend_sharpe"], row["dip_sharpe"] = perf(res["trend"])["sharpe"], perf(res["dip"])["sharpe"]
        row["years"] = perf(res["both"])["years"]
        rows.append(row)
    return pd.DataFrame(rows).set_index("market")


def settings(close: pd.Series) -> pd.DataFrame:
    rows = []
    for trend_days in (150, 200, 250):
        for buy_below in (5.0, 10.0, 15.0):
            for exit_days in (3, 5, 10):
                p = perf(strategy_returns(close, trend_days=trend_days, buy_below=buy_below, exit_days=exit_days)["both"])
                rows.append({"trend_days": trend_days, "rsi_below": buy_below, "exit_days": exit_days, **p})
    return pd.DataFrame(rows)


def costs(close: pd.Series) -> pd.DataFrame:
    rows = []
    for swap in (0.02, 0.04, 0.06, 0.08):
        for half_spread in (0.0001, 0.0003):
            p = perf(strategy_returns(close, swap=swap, half_spread=half_spread)["both"])
            rows.append({"swap_%/yr": 100 * swap, "spread_bp_round_trip": 2e4 * half_spread, **p})
    return pd.DataFrame(rows)


def luck(close: pd.Series, horizon_years: int = 10, samples: int = 2000, block: int = DAYS, seed: int = 7) -> pd.DataFrame:
    """Block bootstrap: stitch random one-year blocks of real history into many 10-year paths."""
    rng = np.random.default_rng(seed)
    res = strategy_returns(close)
    out = []
    n_days = horizon_years * DAYS
    for name in ("both", "buy_and_hold"):
        r = res[name].iloc[300:].to_numpy()
        starts = rng.integers(0, len(r) - block, size=(samples, n_days // block + 1))
        paths = np.stack([np.concatenate([r[s:s + block] for s in row])[:n_days] for row in starts])
        eq = np.cumprod(1 + paths, axis=1)
        cagr = 100 * (eq[:, -1] ** (1 / horizon_years) - 1)
        dd = 100 * np.max(1 - eq / np.maximum.accumulate(eq, axis=1), axis=1)
        out.append({"strategy": name, "yearly_%_p5": np.percentile(cagr, 5), "yearly_%_median": np.median(cagr),
                    "yearly_%_p95": np.percentile(cagr, 95), "max_dd_%_median": np.median(dd),
                    "max_dd_%_p95": np.percentile(dd, 95), "chance_of_loss_over_10y_%": 100 * (eq[:, -1] < 1).mean()})
    return pd.DataFrame(out).set_index("strategy")


def missed_days(close: pd.Series, seed: int = 11) -> pd.DataFrame:
    """Each day, with probability p, MT5 was off at 22:45 and the rules act one day late."""
    rng = np.random.default_rng(seed)
    zero = pd.Series(0.0, index=close.index)
    pos = lab.index_positions(close)
    rows = []
    for p_miss in (0.0, 0.1, 0.3, 0.5):
        late = {}
        for k in ("above_200d", "rsi2_dip"):
            target = pos[k].to_numpy()
            held, actual = 0.0, np.zeros(len(target))
            for t in range(len(target)):
                if rng.random() >= p_miss:  # MT5 was running today: catch up with the rule
                    held = target[t]
                actual[t] = held
            late[k] = lab.index_returns(pd.Series(actual, index=close.index), close, zero, markup=SWAP)["after CFD financing"]
        rows.append({"days_missed_%": 100 * p_miss, **perf(0.5 * late["above_200d"] + 0.5 * late["rsi2_dip"])})
    return pd.DataFrame(rows).set_index("days_missed_%")


# ---------------------------------------------------------------- parity with the EA


def ea_rsi(c: np.ndarray, period: int = 2) -> float:
    """Exactly the EA's Rsi(): Wilder's average over the window it copies."""
    a, up, down = 1.0 / period, 0.0, 0.0
    for k in range(1, len(c)):
        d = c[k] - c[k - 1]
        gain, loss = max(d, 0.0), max(-d, 0.0)
        up, down = (gain, loss) if k == 1 else ((1 - a) * up + a * gain, (1 - a) * down + a * loss)
    return 100.0 if down == 0 else 100 - 100 / (1 + up / down)


def replay_ea(d1: pd.DataFrame, m15: pd.DataFrame, start: str) -> dict[str, list]:
    """The EA's decisions each day at 22:45: yesterday's daily closes + today's 22:45 price."""
    at_2245 = m15[(m15.index.hour == 22) & (m15.index.minute == 30)]["close"]  # the bar ending 22:45
    at_2245.index = at_2245.index.normalize()
    closes = d1["close"]
    trades = {"trend": [], "dip": []}
    have = {"trend": False, "dip": False}
    for day, price in at_2245[at_2245.index >= pd.Timestamp(start)].items():
        window = np.append(closes[closes.index < day].to_numpy()[-259:], price)  # 260 closes, as the EA copies
        if len(window) < 260:
            continue
        trend_avg, exit_avg, r = window[-200:].mean(), window[-5:].mean(), ea_rsi(window)
        want = {"trend": price > trend_avg,
                "dip": (price <= exit_avg) if have["dip"] else (price > trend_avg and r < 10)}
        for rule in ("trend", "dip"):
            if want[rule] != have[rule]:
                trades[rule].append((day, "buy" if want[rule] else "sell"))
                have[rule] = want[rule]
    return trades


def mt5_trades(report: Path) -> list:
    raw = report.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    rows, out, on = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I), [], False
    for r in rows:
        c = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
        if c[:4] == ["Time", "Deal", "Symbol", "Type"]:
            on, header = True, c
            continue
        if on and len(c) == len(header) and re.match(r"\d{4}\.\d\d\.\d\d", c[0]) and c[header.index("Direction")] in ("in", "out"):
            day = pd.Timestamp(c[0][:10].replace(".", "-"))
            if c[0][11:13] < "10":  # an order sent after midnight belongs to the previous day's decision
                day -= pd.Timedelta(days=1)
            if c[header.index("Comment")] != "end of test":
                out.append((day, c[header.index("Type")]))
    return out


def parity(cfg: dict) -> pd.DataFrame:
    common = _common(cfg)
    d1 = intraday.load_bars(common / "bars_index", "US100", "D1")
    m15 = intraday.load_bars(common / "bars_us100", "US100", "M15")
    mt5_dir = Path.home() / ".mt5/drive_c/Program Files/MetaTrader 5"
    ours = replay_ea(d1, m15, "2020-05-28")
    rows = []
    for rule in ("trend", "dip"):
        theirs = mt5_trades(mt5_dir / f"IndexBot_{rule}.htm")
        mine = set(ours[rule])
        matched = sum(1 for t in theirs if t in mine)
        rows.append({"rule": rule, "mt5_orders": len(theirs), "replay_orders": len(ours[rule]), "same_day_and_side": matched,
                     "match_%": 100 * matched / max(len(theirs), 1)})
    return pd.DataFrame(rows).set_index("rule")


def run(cfg: dict) -> dict:
    ndx = prices._series("NASDAQ100", cfg["data_dir"], 24).dropna()
    return {
        "markets": markets(cfg),
        "settings": settings(ndx),
        "costs": costs(ndx),
        "luck": luck(ndx),
        "missed_days": missed_days(ndx),
        "parity": parity(cfg),
    }
