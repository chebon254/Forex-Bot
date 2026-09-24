"""Commitment of Traders data straight from the CFTC: the numbers Barchart plots.

Uses the Legacy futures-only report, which splits traders into commercials (the red
line in your charts) and non-commercials (large speculators).
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .currencies import CFTC_CODES

API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
FIELDS = {
    "report_date_as_yyyy_mm_dd": "date",
    "cftc_contract_market_code": "code",
    "open_interest_all": "open_interest",
    "comm_positions_long_all": "comm_long",
    "comm_positions_short_all": "comm_short",
    "noncomm_positions_long_all": "spec_long",
    "noncomm_positions_short_all": "spec_short",
}
CACHE_FILE = "cot_legacy.csv"

# Report positions are as of Tuesday and published Friday 15:30 New York time, so a report
# is only usable from the weekend after. (Government shutdowns in 2019 and 2025 delayed some
# releases by weeks; the history treats those as on time.)
AVAILABLE_AFTER_DAYS = 4


def fetch(since: str = "1999-01-01") -> pd.DataFrame:
    codes = ",".join(f"'{c}'" for c in CFTC_CODES.values())
    params = {
        "$select": ",".join(FIELDS),
        "$where": f"cftc_contract_market_code in({codes}) AND report_date_as_yyyy_mm_dd >= '{since}T00:00:00'",
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": 50000,
    }
    resp = requests.get(API, params=params, timeout=60)
    resp.raise_for_status()
    return tidy(pd.DataFrame(resp.json()))


def tidy(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=FIELDS)[list(FIELDS.values())].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["currency"] = df["code"].map({code: ccy for ccy, code in CFTC_CODES.items()})
    numeric = ["open_interest", "comm_long", "comm_short", "spec_long", "spec_short"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["currency", "open_interest", "comm_long", "comm_short"])
    df = df[df["open_interest"] > 0]
    df["comm_net"] = df["comm_long"] - df["comm_short"]
    df["spec_net"] = df["spec_long"] - df["spec_short"]
    # A few old weeks carry two rows for one contract code; keep the bigger market.
    df = df.sort_values(["date", "currency", "open_interest"]).drop_duplicates(["date", "currency"], keep="last")
    return df.drop(columns="code").reset_index(drop=True)


def load(data_dir: Path, max_age_hours: float = 6) -> pd.DataFrame:
    """COT history since 1999, cached on disk and refetched when older than `max_age_hours`."""
    path = Path(data_dir) / CACHE_FILE
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return pd.read_csv(path, parse_dates=["date"])
    df = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def sides(net, open_interest, band_pct: float) -> np.ndarray:
    """+1 above the zero line (commercials net long = bullish), -1 below, 0 inside the band."""
    pct = 100.0 * np.asarray(net, dtype=float) / np.asarray(open_interest, dtype=float)
    return np.where(pct > band_pct, 1, np.where(pct < -band_pct, -1, 0))


def snapshot(cot: pd.DataFrame, band_pct: float, date=None) -> pd.DataFrame:
    """One row per currency from the latest report (or the last one on/before `date`)."""
    df = cot.sort_values("date").copy()
    df["net_change"] = df.groupby("currency")["comm_net"].diff()
    if date is not None:
        df = df[df["date"] <= pd.Timestamp(date)]
    snap = df.groupby("currency").tail(1).set_index("currency")
    snap["pct_oi"] = 100.0 * snap["comm_net"] / snap["open_interest"]
    snap["change_pct_oi"] = 100.0 * snap["net_change"] / snap["open_interest"]
    snap["side"] = sides(snap["comm_net"], snap["open_interest"], band_pct)
    return snap


def note(side: int, change_pct_oi: float, pct_oi: float, band_pct: float) -> str:
    """Plain-language reading of one currency's commercials line.

    `change_pct_oi` is this week's change in the net position as % of open interest;
    moves under 1% are noise and get no comment.
    """
    if side == 0:
        return "on the zero line - no side"
    if abs(pct_oi) < 2 * band_pct:
        return "close to the zero line - watch for a flip"
    if pd.notna(change_pct_oi) and abs(change_pct_oi) >= 1.0 and change_pct_oi * side < 0:
        # Your hedging rule: a move against the side is smart money taking profit, not a
        # reversal, for as long as the line stays on its side of zero.
        if side < 0:
            return "shorts covered this week (hedging) - still below zero"
        return "longs trimmed this week (hedging) - still above zero"
    return ""
