"""Write the bias where the MT5 expert advisor reads it: MT5's Common\\Files folder."""

import os
from pathlib import Path

import pandas as pd

LIVE_FILE = "fxbot_bias.csv"
HISTORY_FILE = "fxbot_bias_history.csv"
COLUMNS = [
    "symbol", "direction", "grade", "carry", "differential",
    "base_side", "quote_side", "valid_from", "valid_from_unix", "source",
]
# MT5 creates this folder the first time the terminal runs.
_COMMON = "drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common"


def find_mt5_common_dirs() -> list[Path]:
    """MT5 Common\\Files folders inside the Wine prefixes in your home folder."""
    home = Path.home()
    prefixes = [
        home / ".mt5",
        home / ".wine",
        *sorted(home.glob(".wine?*")),
        *sorted((home / ".local/share/wineprefixes").glob("*")),
    ]
    found = [common / "Files" for prefix in prefixes for common in sorted(prefix.glob(_COMMON)) if common.is_dir()]
    return list(dict.fromkeys(found))


def target_dirs(cfg: dict) -> list[Path]:
    """The project's output folder plus every MT5 folder that should get the files."""
    setting = str(cfg["mt5"].get("common_files_dir") or "auto")
    mt5_dirs = find_mt5_common_dirs() if setting == "auto" else [Path(setting).expanduser()]
    return [Path(cfg["output_dir"]), *mt5_dirs]


def frame(rows: pd.DataFrame) -> pd.DataFrame:
    """The EA's column layout, sorted by pair then time (the EA relies on that order)."""
    df = rows.copy()
    valid_from = pd.to_datetime(df["valid_from"])
    df["valid_from_unix"] = (valid_from - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
    df["valid_from"] = valid_from.dt.strftime("%Y-%m-%d")
    if "source" not in df:
        df["source"] = "auto"
    df["source"] = df["source"].fillna("auto")
    return df.sort_values(["symbol", "valid_from_unix"], kind="stable")[COLUMNS]


def write(df: pd.DataFrame, path: Path, notes: list[str]) -> None:
    """Atomic write (the EA never sees half a file), Windows line endings for MQL5."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="") as fh:
        for note in notes:
            fh.write(f"# {note}\r\n")
        df.to_csv(fh, index=False, lineterminator="\r\n", float_format="%.4f")
    os.replace(tmp, path)
