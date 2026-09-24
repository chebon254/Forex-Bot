"""What the bot prints."""

import os
import sys

import pandas as pd

from .cot import note
from .currencies import PRIORITY

GREEN, RED, YELLOW, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"


def _paint(text: str, code: str) -> str:
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        return f"{code}{text}{RESET}"
    return text


def _side(side: int) -> str:
    word = {1: "bullish", -1: "bearish", 0: "flat"}[int(side)]
    return _paint(f"{word:<8}", {1: GREEN, -1: RED, 0: DIM}[int(side)])


def _direction(direction: str) -> str:
    return _paint(f"{direction:<5}", {"BUY": GREEN, "SELL": RED}.get(direction, DIM))


def today(state, cfg) -> str:
    band = cfg["cot"]["neutral_band_pct"]
    released = state.report_date + pd.Timedelta(days=3)
    out = [
        _paint("FxBot - fundamental bias (interest differential + COT commercials)", BOLD),
        f"COT report: {state.report_date:%a %d %b %Y}, released {released:%a %d %b}; "
        f"next release {released + pd.Timedelta(days=7):%a %d %b} after 22:30 EAT",
        f"Interest rates from: {state.rates_source}",
    ]
    age = (pd.Timestamp.now() - released).days
    if age > 8:
        out.append(_paint(f"Warning: the newest COT report is {age} days old - CFTC releases may be delayed.", YELLOW))

    out += ["", _paint("CURRENCIES  (commercials above zero = bullish, below = bearish)", BOLD)]
    out.append(f"{'':3}{'RATE':>7}  {'COMM. NET':>10}  {'% OI':>6}  {'SIDE':<8}  {'W/W':>9}  NOTE")
    snap = state.snapshot
    for ccy in sorted(PRIORITY, key=lambda c: -state.rates[c]):
        if ccy not in snap.index:
            out.append(f"{ccy:<3}{state.rates[ccy]:>6.2f}%  {'no COT data':>10}")
            continue
        row = snap.loc[ccy]
        change = f"{row['net_change']:+,.0f}" if pd.notna(row["net_change"]) else "-"
        out.append(
            f"{ccy:<3}{state.rates[ccy]:>6.2f}%  {row['comm_net']:>+10,.0f}  {row['pct_oi']:>+5.1f}%  "
            f"{_side(row['side'])}  {change:>9}  {_paint(note(row['side'], row['change_pct_oi'], row['pct_oi'], band), DIM)}"
        )

    in_play = [b for b in state.biases if b.direction != "NEUTRAL"]
    out += ["", _paint("PAIRS IN PLAY  (currencies on opposite sides of zero, widest differential first)", BOLD)]
    if in_play:
        out.append(f"{'PAIR':<8}{'BIAS':<6}{'GRADE':<7}{'CARRY':>7}   WHY")
        for b in in_play:
            base, quote = b.symbol[:3], b.symbol[3:]
            if b.source == "override":
                why = "your override"
            else:
                why = f"{base} {'bullish' if b.base_side > 0 else 'bearish'}, {quote} {'bullish' if b.quote_side > 0 else 'bearish'}"
                if b.grade == "B":
                    why += " - against the carry" if b.carry <= 0 else " - carry too small"
            grade = _paint(f"{b.grade:<7}", GREEN if b.grade in ("A", "M") else YELLOW)
            out.append(f"{b.symbol:<8}{_direction(b.direction)} {grade}{b.carry:>+6.2f}%   {why}")
    else:
        out.append("None this week - no two currencies sit on opposite sides of the zero line.")
    neutral = [b.symbol for b in state.biases if b.direction == "NEUTRAL"]
    out += [
        "",
        _paint(f"No trade ({len(neutral)}): same side or flat - " + ", ".join(neutral), DIM),
        "",
        f"Grade A = COT and interest rates agree, carry at least {cfg['strategy']['min_carry']:.2f}% (traded by the EA). "
        "Grade B = carry small or against you (skipped by default).",
        "The EA enters only after a market structure break in the bias direction on the chart.",
    ]
    return "\n".join(out)


def backtest(result: dict) -> str:
    p = result["params"]
    out = [
        _paint(f"FxBot backtest since {result['since']} ({result['weeks']} weekly COT reports, FRED daily closes)", BOLD),
        "",
        _paint("1) Does the weekly bias point the right way? (equal-weight basket, price only, no swaps)", BOLD),
    ]
    for h, table in result["edge"].items():
        out += [f"  Over the next {h} week{'s' if h > 1 else ''}:", _table(table), ""]
    out.append("  t_stat above ~2 means the edge is unlikely to be luck; near 0 means no edge.")

    s = result["summary"]
    out += [
        "",
        _paint("2) Full strategy: bias + market structure break", BOLD),
        f"  structure strength {p.strength}, "
        + (f"limit entry at {p.retrace:.0%} of the leg (expires after {p.expiry_bars} bars)" if p.retrace > 0 else "entry at the break close")
        + f", target {p.reward_risk}R, cost {p.cost_pips} pips/trade, "
        f"{'MSB only' if p.msb_only else 'MSB + BOS'}, "
        + (f"grade {'A+B' if p.allow_grade_b else 'A'}" if p.use_bias else "NO BIAS (technicals only)"),
    ]
    if not s.get("trades"):
        out.append("  No trades.")
        return "\n".join(out)
    out += [
        f"  trades {s['trades']} ({s['trades_per_year']:.1f}/year) | win rate {s['win_rate_%']:.1f}% | "
        f"avg {s['avg_r']:+.3f}R | total {s['total_r']:+.1f}R | profit factor {s['profit_factor']:.2f} | "
        f"max drawdown {s['max_drawdown_r']:.1f}R",
        f"  exits: {', '.join(f'{k} {v}' for k, v in s['outcomes'].items())}",
        "  R by year: " + "  ".join(f"{y}:{r:+.1f}" for y, r in s["by_year"].items()),
        "",
        "  At 1% risk per trade, 1R = 1% of the account (before compounding).",
    ]
    return "\n".join(out)


def _table(df: pd.DataFrame) -> str:
    text = df.to_string(float_format=lambda v: f"{v:,.2f}")
    return "\n".join("    " + line for line in text.splitlines())


def lab(fx: dict, index: dict) -> str:
    """Strategy lab results: fixed textbook rules, long history, retail costs."""
    num = lambda df: df.round(2).to_string()
    indent = lambda text: "\n".join("  " + line for line in text.splitlines())
    return "\n".join([
        _paint("Strategy lab - textbook rules fixed in advance, FRED/BIS data, retail costs", BOLD),
        "",
        _paint("FOREX  (Sharpe: return per unit of risk; t_stat above ~2 = unlikely to be luck;", BOLD),
        _paint("        growth/drawdown shown at 10% yearly volatility so strategies compare fairly)", BOLD),
        indent(num(fx["table"])),
        "",
        "  Sharpe by decade, dollar pairs, after retail swaps:",
        indent(num(fx["decades"])),
        "",
        _paint("STOCK INDEX  (1x exposure, no leverage; CFD longs pay Fed funds + 2.5%/yr)", BOLD),
        indent(num(index["table"])),
        "",
        "  Sharpe by decade, after CFD financing:",
        indent(num(index["decades"])),
    ])


def intraday(res: dict) -> str:
    """Intraday test: London open to New York midday on FBS 15-minute bars."""
    d, b, n = res["bias_drift"], res["bias_msb"], res["msb_no_bias"]
    line = lambda name, s: (f"  {name:<42} {s['trades']:>7,} trades  win {s['win_%']:4.1f}%  "
                            f"avg {s['avg_r']:+.3f}R  t {s['t_stat']:+5.1f}  total {s['total_r']:+9.1f}R")
    return "\n".join([
        _paint("Intraday: London open (10:00 server) to New York midday (19:00), FBS 15-minute bars", BOLD),
        f"  {'bias only (open at London, close at midday)':<42} {d['trades']:>7,} trades  win {d['win_%']:4.1f}%  "
        f"avg {d['avg_pips']:+.2f} pips  t {d['t_stat']:+5.1f}",
        line("your strategy (bias + 15-minute MSB)", b),
        line("same entries without the bias", n),
        "",
        "  your strategy, R by year: " + "  ".join(f"{y}:{r:+.0f}" for y, r in b["by_year"].items()),
        f"  median stop {b['median_stop_pips']:.0f} pips; exits {b['exits']}",
        "  Costs: FBS's recorded spread on every trade + 0.3 pips slippage.",
    ])


def indexlab(res: dict) -> str:
    """IndexBot stress tests."""
    num = lambda df, **kw: "\n".join("  " + line for line in df.round(2).to_string(**kw).splitlines())
    s = res["settings"]
    default = s[(s.trend_days == 200) & (s.rsi_below == 10) & (s.exit_days == 5)].sharpe.iloc[0]
    return "\n".join([
        _paint("IndexBot stress tests (both rules at 0.5x; FBS-like costs: 4%/yr swap, 1 bp spread)", BOLD),
        "", _paint("1) Same rules, unchanged, on other markets", BOLD), num(res["markets"]),
        "", _paint("2) Nearby settings on NASDAQ 100 1986-2026 (Sharpe)", BOLD),
        f"  27 combinations: min {s.sharpe.min():.2f}, median {s.sharpe.median():.2f}, max {s.sharpe.max():.2f}; default {default:.2f}",
        num(s.pivot_table(index=["trend_days", "rsi_below"], columns="exit_days", values="sharpe")),
        "", _paint("3) Higher costs", BOLD), num(res["costs"], index=False),
        "", _paint("4) Luck: 2,000 ten-year paths stitched from one-year blocks of 1986-2026", BOLD), num(res["luck"]),
        "", _paint("5) MT5 not running at 22:45 on some days", BOLD), num(res["missed_days"]),
        "", _paint("6) EA vs rules, trade by trade (FBS US100, 2020-2026)", BOLD), num(res["parity"]),
    ])
