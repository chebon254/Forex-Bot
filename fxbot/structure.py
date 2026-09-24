"""Market structure: swing points, higher highs/lows, and the break that shifts the trend.

This is the Python twin of the logic in mt5/FxBot.mq5 - keep the two in step.

A swing high is a bar whose high is strictly above the `strength` bars before it and at
least as high as the `strength` bars after it (swing lows mirror that). It is only known
once those later bars have closed, so nothing here looks ahead.

A bar that closes beyond the most recent unbroken swing is a break:
  - MSB (market structure break): against the current trend - in your diagram, the close
    below the higher low that turns an uptrend into a lower low.
  - BOS (break of structure): with the trend - a continuation.

Each break also carries the price leg that did the breaking (the dealing range). The EA
sells in the upper part of a bearish leg and buys in the lower part of a bullish one:
"sell it when high, buy low".
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Swing:
    bar: int
    price: float
    is_high: bool
    label: str  # HH, LH, HL, LL (H / L for the first of each kind)


@dataclass
class Break:
    bar: int  # the bar whose close broke the swing
    direction: int  # +1 broke a high (bullish), -1 broke a low (bearish)
    kind: str  # MSB or BOS
    level: float  # price of the broken swing
    swing_bar: int
    range_high: float  # the leg that made the break
    range_low: float


@dataclass
class Structure:
    swings: list[Swing]
    breaks: list[Break]
    trend: int  # +1 up, -1 down, 0 unknown


def analyze(high, low, close, strength: int = 3) -> Structure:
    high, low, close = (np.asarray(a, dtype=float) for a in (high, low, close))
    n = len(close)
    swings: list[Swing] = []
    breaks: list[Break] = []
    trend = 0
    hi_price = lo_price = 0.0
    hi_bar = lo_bar = -1
    hi_broken = lo_broken = True
    last_high_price = last_low_price = None

    for t in range(n):
        i = t - strength
        if i >= strength:
            if high[i] > high[i - strength : i].max() and high[i] >= high[i + 1 : t + 1].max():
                hi_price, hi_bar, hi_broken = high[i], i, False
                label = "H" if last_high_price is None else ("HH" if high[i] > last_high_price else "LH")
                swings.append(Swing(i, high[i], True, label))
                last_high_price = high[i]
            if low[i] < low[i - strength : i].min() and low[i] <= low[i + 1 : t + 1].min():
                lo_price, lo_bar, lo_broken = low[i], i, False
                label = "L" if last_low_price is None else ("LL" if low[i] < last_low_price else "HL")
                swings.append(Swing(i, low[i], False, label))
                last_low_price = low[i]

        if hi_bar >= 0 and not hi_broken and close[t] > hi_price:
            hi_broken = True
            start = hi_bar + int(np.argmin(low[hi_bar : t + 1]))  # the low the rally started from
            top = high[start : t + 1].max()
            breaks.append(Break(t, 1, "BOS" if trend == 1 else "MSB", hi_price, hi_bar, top, low[start]))
            trend = 1

        if lo_bar >= 0 and not lo_broken and close[t] < lo_price:
            lo_broken = True
            start = lo_bar + int(np.argmax(high[lo_bar : t + 1]))  # the high the drop started from
            bottom = low[start : t + 1].min()
            breaks.append(Break(t, -1, "BOS" if trend == -1 else "MSB", lo_price, lo_bar, high[start], bottom))
            trend = -1

    return Structure(swings, breaks, trend)


def entry_levels(brk: Break, retrace: float, reward_risk: float, stop_buffer: float, last_close: float):
    """(entry, stop, target) for a break. retrace=0 means enter at the breaking bar's close."""
    span = brk.range_high - brk.range_low
    if brk.direction < 0:
        entry = brk.range_low + retrace * span if retrace > 0 else last_close
        stop = brk.range_high + stop_buffer
        target = entry - reward_risk * (stop - entry)
    else:
        entry = brk.range_high - retrace * span if retrace > 0 else last_close
        stop = brk.range_low - stop_buffer
        target = entry + reward_risk * (entry - stop)
    return entry, stop, target


def atr(high, low, close, period: int = 14) -> np.ndarray:
    """Simple-average true range; value at bar t uses bars t-period+1..t (NaN before that)."""
    high, low, close = (np.asarray(a, dtype=float) for a in (high, low, close))
    prev = np.concatenate(([np.nan], close[:-1]))
    tr = np.maximum(high, prev) - np.minimum(low, prev)
    out = np.full(len(close), np.nan)
    if len(close) > period:
        csum = np.cumsum(np.nan_to_num(tr[1:]))
        csum = np.concatenate(([0.0], csum))
        out[period:] = (csum[period:] - csum[:-period]) / period
    return out
