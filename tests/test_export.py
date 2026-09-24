"""The bias file is the contract with the MT5 EA - its layout must not drift."""

import pandas as pd

from fxbot import export


def test_file_layout_the_ea_expects(tmp_path):
    rows = pd.DataFrame([
        {"symbol": "USDCHF", "direction": "SELL", "grade": "B", "carry": -4.0, "differential": 4.0,
         "base_side": -1, "quote_side": 1, "valid_from": pd.Timestamp("2026-09-19"), "source": "auto"},
        {"symbol": "AUDJPY", "direction": "BUY", "grade": "A", "carry": 3.1, "differential": 3.1,
         "base_side": 1, "quote_side": -1, "valid_from": pd.Timestamp("2026-09-19"), "source": None},
        {"symbol": "AUDJPY", "direction": "BUY", "grade": "A", "carry": 3.1, "differential": 3.1,
         "base_side": 1, "quote_side": -1, "valid_from": pd.Timestamp("2026-09-12"), "source": "auto"},
    ])
    path = tmp_path / "fxbot_bias.csv"
    export.write(export.frame(rows), path, ["fxbot test", "cot_report 2026-09-15 rates_source site"])

    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")  # CRLF only
    lines = raw.decode().split("\r\n")
    assert lines[0] == "# fxbot test"
    assert lines[1] == "# cot_report 2026-09-15 rates_source site"  # the EA reads the date after "cot_report "
    assert lines[2].split(",") == export.COLUMNS
    fields = lines[3].split(",")
    # sorted by pair, then oldest week first (the EA walks rows forward in time)
    assert fields[:3] == ["AUDJPY", "BUY", "A"] and fields[7] == "2026-09-12"
    assert lines[4].split(",")[7] == "2026-09-19"
    assert int(lines[4].split(",")[8]) == 1789776000  # 2026-09-19 00:00 UTC
    assert lines[4].split(",")[9] == "auto"
    assert lines[5].startswith("USDCHF,SELL,B,-4.0000,")
    assert not list(tmp_path.glob("*.tmp"))
