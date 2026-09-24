"""Your strategy's fundamental rules, turned into a bias for each of the 28 pairs.

1. Commercials in each currency's futures (COT): above the zero line = bullish (they see it
   as oversold), below = bearish (overbought).
2. A pair is only in play when its two currencies sit on opposite sides of the line:
   base bullish + quote bearish = BUY, base bearish + quote bullish = SELL.
3. Grade A when the trade also earns the interest differential - you are buying the
   higher-yielding currency - by at least `min_carry` points. Otherwise grade B.
4. Rank by that differential, widest first.

The entry itself (waiting for a market structure break) happens in the MT5 EA.
"""

from dataclasses import asdict, dataclass

import pandas as pd

from .cot import AVAILABLE_AFTER_DAYS, sides
from .currencies import all_pairs, split

DIRECTIONS = ("BUY", "SELL", "NEUTRAL")


@dataclass
class PairBias:
    symbol: str
    direction: str  # BUY, SELL or NEUTRAL
    grade: str  # A, B, M (your override) or -
    carry: float  # differential earned in the trade direction; base minus quote when NEUTRAL
    differential: float  # base rate minus quote rate
    base_side: int
    quote_side: int
    source: str = "auto"


def pair_bias(symbol: str, sides_by_ccy: dict, rates: dict, min_carry: float) -> PairBias:
    base, quote = split(symbol)
    base_side, quote_side = int(sides_by_ccy.get(base, 0)), int(sides_by_ccy.get(quote, 0))
    diff = round(rates[base] - rates[quote], 4)
    if base_side == 1 and quote_side == -1:
        direction, carry = "BUY", diff
    elif base_side == -1 and quote_side == 1:
        direction, carry = "SELL", -diff
    else:
        return PairBias(symbol, "NEUTRAL", "-", diff, diff, base_side, quote_side)
    grade = "A" if carry >= min_carry else "B"
    return PairBias(symbol, direction, grade, carry, diff, base_side, quote_side)


def apply_override(bias: PairBias, direction: str) -> PairBias:
    direction = str(direction).upper()
    if direction not in DIRECTIONS:
        raise ValueError(f"override for {bias.symbol} must be BUY, SELL or NEUTRAL, not {direction!r}")
    carry = -bias.differential if direction == "SELL" else bias.differential
    grade = "-" if direction == "NEUTRAL" else "M"
    return PairBias(bias.symbol, direction, grade, carry, bias.differential, bias.base_side, bias.quote_side, "override")


def all_biases(sides_by_ccy: dict, rates: dict, min_carry: float, overrides: dict | None = None) -> list[PairBias]:
    """All 28 pairs, tradeable ones first, widest differential first."""
    overrides = {str(k).upper(): v for k, v in (overrides or {}).items()}
    unknown = set(overrides) - set(all_pairs())
    if unknown:
        raise ValueError(f"unknown pair(s) in overrides: {', '.join(sorted(unknown))}")
    out = []
    for symbol in all_pairs():
        bias = pair_bias(symbol, sides_by_ccy, rates, min_carry)
        if symbol in overrides:
            bias = apply_override(bias, overrides[symbol])
        out.append(bias)
    return sorted(out, key=_rank)


def _rank(b: PairBias):
    tier = {"A": 0, "M": 0, "B": 1, "-": 2}[b.grade]
    width = b.carry if b.direction != "NEUTRAL" else abs(b.differential)
    return (tier, -width, b.symbol)


def history(cot: pd.DataFrame, rates_hist: pd.DataFrame, band_pct: float, min_carry: float) -> pd.DataFrame:
    """Bias for every pair and every weekly report, as the bot would have seen it at the time.

    `valid_from` is the weekend after the report came out; rates are the ones known that Friday.
    """
    cot = cot.assign(side=sides(cot["comm_net"], cot["open_interest"], band_pct))
    weekly = cot.pivot_table(index="date", columns="currency", values="side", aggfunc="last")
    rows = []
    for report_date, week in weekly.iterrows():
        valid_from = report_date + pd.Timedelta(days=AVAILABLE_AFTER_DAYS)
        rates = rates_hist.asof(valid_from - pd.Timedelta(days=1))
        if rates.isna().any():
            continue
        week_sides = {ccy: (0 if pd.isna(s) else int(s)) for ccy, s in week.items()}
        rate_map = rates.to_dict()
        for symbol in all_pairs():
            row = asdict(pair_bias(symbol, week_sides, rate_map, min_carry))
            row.update(report_date=report_date, valid_from=valid_from)
            rows.append(row)
    return pd.DataFrame(rows)
