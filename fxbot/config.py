"""Settings: built-in defaults, overridden by config.yaml in the project folder."""

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "rates": {
        "sources": ["site", "bis"],
        "site_url": "https://forexchart-kibet.web.app/",
        "manual": {},
    },
    "cot": {"neutral_band_pct": 2.0},
    "strategy": {"min_carry": 0.5},
    "overrides": {},
    "mt5": {"common_files_dir": "auto"},
    "data_dir": "data",
    "output_dir": "output",
}


def load(path: str | Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(path) if path else ROOT / "config.yaml"
    if path.exists():
        _merge(cfg, yaml.safe_load(path.read_text()) or {})
    # An empty YAML key ("overrides:") loads as None.
    cfg["overrides"] = cfg.get("overrides") or {}
    cfg["rates"]["manual"] = cfg["rates"].get("manual") or {}
    for key in ("data_dir", "output_dir"):
        p = Path(cfg[key]).expanduser()
        cfg[key] = p if p.is_absolute() else ROOT / p
    return cfg


def _merge(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
