import numpy as np

from fxbot.structure import analyze, atr, entry_levels

# The market-structure diagram from the Forex Chart page as a price path:
# Low -> High -> Higher low -> Higher high -> close below the higher low (lower low).
DIAGRAM = [10, 9, 8, 9, 10, 11, 12, 11, 10.5, 10, 11, 12.5, 13, 14, 13, 12, 11, 9.5, 9, 9.2]


def test_diagram_swings_are_labelled_like_the_picture():
    s = analyze(DIAGRAM, DIAGRAM, DIAGRAM, strength=2)
    assert [(w.bar, w.price, w.label) for w in s.swings] == [
        (2, 8, "L"),
        (6, 12, "H"),
        (9, 10, "HL"),
        (13, 14, "HH"),
    ]


def test_close_below_the_higher_low_is_a_bearish_msb():
    s = analyze(DIAGRAM, DIAGRAM, DIAGRAM, strength=2)
    first, second = s.breaks
    # breaking above the first high starts the uptrend
    assert (first.bar, first.direction, first.kind, first.level) == (11, 1, "MSB", 12)
    assert (first.range_low, first.range_high) == (10, 12.5)
    # the close at 9.5 breaks the higher low at 10: structure shifts down
    assert (second.bar, second.direction, second.kind, second.level, second.swing_bar) == (17, -1, "MSB", 10, 9)
    assert (second.range_high, second.range_low) == (14, 9.5)
    assert s.trend == -1


def test_break_in_trend_direction_is_bos():
    # uptrend, pullback, then a new high above the last swing high = continuation
    path = [10, 9, 8, 9, 10, 11, 12, 11, 10.5, 10, 11, 12.5, 13, 14, 13, 12.5, 12.8, 14.5]
    s = analyze(path, path, path, strength=2)
    assert [(b.bar, b.kind, b.direction) for b in s.breaks] == [(11, "MSB", 1), (17, "BOS", 1)]


def test_swings_need_bars_after_them_so_nothing_looks_ahead():
    # the top at bar 13 is only a swing once two lower bars have closed after it
    s = analyze(DIAGRAM[:15], DIAGRAM[:15], DIAGRAM[:15], strength=2)
    assert 13 not in [w.bar for w in s.swings]


def test_entry_levels_market_and_limit():
    s = analyze(DIAGRAM, DIAGRAM, DIAGRAM, strength=2)
    bear = s.breaks[1]
    entry, stop, target = entry_levels(bear, retrace=0.0, reward_risk=2.0, stop_buffer=0.0, last_close=9.5)
    assert (entry, stop, target) == (9.5, 14, 9.5 - 2 * 4.5)
    entry, stop, target = entry_levels(bear, retrace=0.5, reward_risk=2.0, stop_buffer=0.1, last_close=9.5)
    assert entry == 11.75  # "sell it when high": halfway back up the breaking leg
    assert stop == 14.1
    assert target == 11.75 - 2 * (14.1 - 11.75)


def test_atr_is_simple_average_true_range():
    close = [1, 2, 4, 7, 11]
    out = atr(close, close, close, period=2)
    assert np.isnan(out[:2]).all()  # not enough bars yet
    assert out[2] == (1 + 2) / 2
    assert out[4] == (3 + 4) / 2
