"""Parsing the outside data: CFTC rows, the Forex Chart rates table."""

import numpy as np
import pandas as pd

from fxbot import cot, rates

# Rows as the CFTC API returns them (every value is a string).
CFTC_ROWS = [
    {"report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000", "cftc_contract_market_code": "092741",
     "open_interest_all": "171000", "comm_positions_long_all": "90000", "comm_positions_short_all": "45526",
     "noncomm_positions_long_all": "20000", "noncomm_positions_short_all": "60000"},
    {"report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000", "cftc_contract_market_code": "097741",
     "open_interest_all": "540000", "comm_positions_long_all": "100000", "comm_positions_short_all": "224674",
     "noncomm_positions_long_all": "150000", "noncomm_positions_short_all": "40000"},
    # duplicate contract row in the same week: the larger market wins
    {"report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000", "cftc_contract_market_code": "097741",
     "open_interest_all": "10", "comm_positions_long_all": "5", "comm_positions_short_all": "1",
     "noncomm_positions_long_all": "1", "noncomm_positions_short_all": "1"},
    # unrelated contract: dropped
    {"report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000", "cftc_contract_market_code": "999999",
     "open_interest_all": "1", "comm_positions_long_all": "1", "comm_positions_short_all": "1",
     "noncomm_positions_long_all": "1", "noncomm_positions_short_all": "1"},
]


def test_cftc_rows_become_net_positions_per_currency():
    df = cot.tidy(pd.DataFrame(CFTC_ROWS)).set_index("currency")
    assert sorted(df.index) == ["CHF", "JPY"]
    assert df.loc["CHF", "comm_net"] == 44474
    assert df.loc["JPY", "comm_net"] == -124674
    assert df.loc["JPY", "open_interest"] == 540000
    assert df.loc["CHF", "spec_net"] == -40000


def test_zero_line_with_neutral_band():
    s = cot.sides([500, -500, 10, -10, 0], [1000] * 5, band_pct=2.0)
    assert s.tolist() == [1, -1, 0, 0, 0]
    assert cot.sides([10, -10], [1000, 1000], band_pct=0.0).tolist() == [1, -1]


def test_hedging_note_follows_your_rule():
    assert "hedging" in cot.note(-1, +15.9, -28.0, 2.0)  # net short, shorts covered
    assert "hedging" in cot.note(1, -7.7, 18.0, 2.0)  # net long, longs trimmed
    assert cot.note(1, -0.01, 18.0, 2.0) == ""  # a tiny change is noise
    assert cot.note(-1, -5.0, -28.0, 2.0) == ""  # adding to shorts: nothing to explain
    assert "zero line" in cot.note(0, np.nan, 0.0, 2.0)


SITE_HTML = """
<table><thead><tr><th>Central Bank</th><th>Country/Region</th><th>Current Rate</th></tr></thead>
<tbody>
  <tr>
    <td>American Fed</td>
    <td>United States</td>
    <td>
      <span class="rate-badge rate-high">4.00%</span>
      <i class="fas fa-arrow-up trend-up text-xs ml-1" title="Previous: 3.75%"></i>
    </td>
    <td>09-17-2026</td>
    <td><span class="font-semibold">USD</span></td>
  </tr>
  <tr>
    <td>SNB</td><td>Switzerland</td>
    <td><span class="rate-badge rate-low">0.00%</span><i title="Previous: 0.25%"></i></td>
    <td>06-19-2025</td><td><span class="font-semibold">CHF</span></td>
  </tr>
</tbody></table>
"""


def test_rates_table_from_the_forex_chart_page():
    parsed = rates.parse_site(SITE_HTML)
    assert parsed["USD"] == {"rate": 4.0, "changed": "09-17-2026", "bank": "American Fed"}
    assert parsed["CHF"]["rate"] == 0.0  # the "Previous: 0.25%" tooltip is ignored


def test_manual_rates_skip_the_network():
    cfg = {"rates": {"manual": {c: 1.0 for c in ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]}, "sources": []}}
    got, source = rates.current(cfg)
    assert source == "manual" and set(got.values()) == {1.0}
