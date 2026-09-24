"""Today's analysis, computed once and shared by the report and the export."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import __version__, bias, cot, export, rates


@dataclass
class Today:
    cot: pd.DataFrame
    snapshot: pd.DataFrame  # one row per currency from the latest report
    report_date: pd.Timestamp
    prev_report_date: pd.Timestamp
    rates: dict
    rates_source: str
    biases: list  # PairBias for the latest report
    prev_biases: list  # PairBias for the report before (bridges Friday's release to the weekend)


def today(cfg: dict) -> Today:
    band = cfg["cot"]["neutral_band_pct"]
    min_carry = cfg["strategy"]["min_carry"]
    cot_df = cot.load(cfg["data_dir"])
    current_rates, source = rates.current(cfg)
    dates = sorted(cot_df["date"].unique())
    report_date, prev_date = pd.Timestamp(dates[-1]), pd.Timestamp(dates[-2])
    snap = cot.snapshot(cot_df, band)
    prev_snap = cot.snapshot(cot_df, band, prev_date)
    return Today(
        cot=cot_df,
        snapshot=snap,
        report_date=report_date,
        prev_report_date=prev_date,
        rates=current_rates,
        rates_source=source,
        biases=bias.all_biases(snap["side"].to_dict(), current_rates, min_carry, cfg["overrides"]),
        prev_biases=bias.all_biases(prev_snap["side"].to_dict(), current_rates, min_carry, cfg["overrides"]),
    )


def _week_rows(report_date, biases) -> list[dict]:
    valid_from = report_date + pd.Timedelta(days=cot.AVAILABLE_AFTER_DAYS)
    return [{**asdict(b), "report_date": report_date, "valid_from": valid_from} for b in biases]


def write_files(cfg: dict, state: Today) -> tuple[list[Path], list[str]]:
    """Write the live and history bias files. Returns (paths written, warnings)."""
    live = pd.DataFrame(_week_rows(state.prev_report_date, state.prev_biases) + _week_rows(state.report_date, state.biases))
    warnings = []
    history = None
    try:
        rates_hist = rates.bis_history(cfg["data_dir"])
        past = bias.history(state.cot, rates_hist, cfg["cot"]["neutral_band_pct"], cfg["strategy"]["min_carry"])
        past = past[past["report_date"] < state.prev_report_date]
        history = export.frame(pd.concat([past, live], ignore_index=True))
    except Exception as exc:  # the live file matters most; the history file is for backtests
        warnings.append(f"history file not updated (BIS rates unavailable: {exc})")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    notes = [
        f"fxbot {__version__} generated {stamp}",
        f"cot_report {state.report_date:%Y-%m-%d} rates_source {state.rates_source}",
    ]
    live = export.frame(live)
    written = []
    for folder in export.target_dirs(cfg):
        export.write(live, folder / export.LIVE_FILE, notes)
        written.append(folder / export.LIVE_FILE)
        if history is not None:
            export.write(history, folder / export.HISTORY_FILE, notes)
            written.append(folder / export.HISTORY_FILE)
    return written, warnings
