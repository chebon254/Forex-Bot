"""Central bank policy rates: your Forex Chart page for today, the BIS for history."""

import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

from .currencies import BIS_AREAS, PRIORITY

BIS_URL = "https://stats.bis.org/api/v1/data/WS_CBPOL/D.{areas}"
BIS_CACHE = "bis_policy_rates.csv"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")


def parse_site(html: str) -> dict[str, dict]:
    """The rates table on the Forex Chart page: {currency: {rate, changed, bank}}.

    Rows are Central Bank | Country | Current Rate | Last Change | Currency.
    """
    out = {}
    for row in _ROW.findall(html):
        cells = [_TAG.sub(" ", cell).strip() for cell in _CELL.findall(row)]
        if len(cells) < 5:
            continue
        ccy = cells[4].upper()
        match = _PCT.search(cells[2])
        if ccy in PRIORITY and match:
            out[ccy] = {"rate": float(match.group(1)), "changed": cells[3], "bank": cells[0]}
    return out


def from_site(url_or_path: str) -> dict[str, float]:
    if url_or_path.startswith(("http://", "https://")):
        resp = requests.get(url_or_path, timeout=30)
        resp.raise_for_status()
        html = resp.text
    else:
        html = Path(url_or_path).expanduser().read_text()
    return {ccy: row["rate"] for ccy, row in parse_site(html).items()}


def bis_history(data_dir: Path, max_age_hours: float = 24, start: str = "1999-01-01") -> pd.DataFrame:
    """Daily policy rates, one column per currency, forward-filled over weekends and holidays.

    Conventions differ slightly from the Forex Chart table (BIS uses the middle of the Fed's
    target range and the ECB deposit rate), which moves a differential by at most ~0.15.
    """
    path = Path(data_dir) / BIS_CACHE
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        raw = pd.read_csv(path)
    else:
        resp = requests.get(
            BIS_URL.format(areas="+".join(BIS_AREAS.values())),
            params={"format": "csv", "detail": "dataonly", "startPeriod": start},
            timeout=120,
        )
        resp.raise_for_status()
        raw = pd.read_csv(io.StringIO(resp.text))
        path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(path, index=False)
    by_area = {area: ccy for ccy, area in BIS_AREAS.items()}
    raw = raw.assign(currency=raw["REF_AREA"].map(by_area), date=pd.to_datetime(raw["TIME_PERIOD"]))
    wide = raw.pivot_table(index="date", columns="currency", values="OBS_VALUE", aggfunc="last")
    return wide.reindex(columns=list(PRIORITY)).sort_index().ffill()


def current(cfg: dict) -> tuple[dict[str, float], str]:
    """Today's rates from the first source that has all eight currencies, plus manual pins."""
    manual = {k.upper(): float(v) for k, v in cfg["rates"]["manual"].items()}
    if all(ccy in manual for ccy in PRIORITY):
        return {ccy: manual[ccy] for ccy in PRIORITY}, "manual"
    errors = []
    for source in cfg["rates"]["sources"]:
        try:
            if source == "site":
                rates = from_site(cfg["rates"]["site_url"])
            elif source == "bis":
                rates = bis_history(cfg["data_dir"]).iloc[-1].to_dict()
            else:
                raise ValueError("unknown source (use site or bis)")
        except Exception as exc:  # network or parsing trouble: try the next source
            errors.append(f"{source}: {exc}")
            continue
        rates.update(manual)
        missing = [ccy for ccy in PRIORITY if pd.isna(rates.get(ccy))]
        if missing:
            errors.append(f"{source}: no rate for {', '.join(missing)}")
            continue
        return {ccy: float(rates[ccy]) for ccy in PRIORITY}, source + (" + manual" if manual else "")
    raise RuntimeError("could not get interest rates - " + "; ".join(errors))
