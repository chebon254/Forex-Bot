"""Daily closes for research: Federal Reserve (FRED) noon rates in New York, free and keyless.

These are closing prices only (no highs/lows), so backtests on them treat each day as a
single price. Crosses such as GBPJPY are built from the two dollar legs.
"""

import time
from pathlib import Path

import pandas as pd
import requests

from .currencies import FRED_SERIES, split

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def _series(series_id: str, data_dir: Path, max_age_hours: float) -> pd.Series:
    path = Path(data_dir) / f"fred_{series_id}.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > max_age_hours * 3600:
        resp = requests.get(FRED_CSV, params={"id": series_id}, timeout=60)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text)
    df = pd.read_csv(path)
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy()
    return pd.Series(values, index=pd.to_datetime(df.iloc[:, 0]), name=series_id)


def usd_values(data_dir: Path, max_age_hours: float = 24) -> pd.DataFrame:
    """Value of one unit of each currency in US dollars, one row per New York business day."""
    cols = {}
    for ccy, (series_id, usd_per_unit) in FRED_SERIES.items():
        s = _series(series_id, data_dir, max_age_hours)
        cols[ccy] = s if usd_per_unit else 1.0 / s
    df = pd.DataFrame(cols).sort_index()
    df["USD"] = 1.0
    return df.ffill(limit=3).dropna()


def closes(values: pd.DataFrame, symbol: str) -> pd.Series:
    base, quote = split(symbol)
    return (values[base] / values[quote]).rename(symbol)
