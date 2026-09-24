"""Command line: `fxbot report`, `fxbot export`, `fxbot backtest`, `fxbot paths`."""

import argparse
import json
import sys
from dataclasses import asdict

from . import __version__, config, export, pipeline, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fxbot", description="Interest differential + COT bias for the FxBot MT5 EA.")
    parser.add_argument("--config", help="path to config.yaml (default: the one in the project folder)")
    parser.add_argument("--version", action="version", version=f"fxbot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    rep = sub.add_parser("report", help="show this week's bias for all 28 pairs")
    rep.add_argument("--json", action="store_true", help="machine-readable output")

    exp = sub.add_parser("export", help="report + write the bias files the EA reads")
    exp.add_argument("--quiet", action="store_true", help="only print errors (for timers/cron)")

    bt = sub.add_parser("backtest", help="test the strategy on history (FRED daily closes)")
    bt.add_argument("--since", default="2000-01-01")
    bt.add_argument("--strength", type=int, default=3, help="bars each side of a swing point")
    bt.add_argument("--retrace", type=float, default=0.0, help="0 = enter at the break (EA default); 0.5 = limit at 50%% of the leg")
    bt.add_argument("--rr", type=float, default=2.0, help="take profit in R")
    bt.add_argument("--expiry", type=int, default=10, help="bars before an unfilled order is cancelled")
    bt.add_argument("--bos", action="store_true", help="also trade continuation breaks (BOS), not just the MSB")
    bt.add_argument("--grade-b", action="store_true", help="also trade grade B (against the carry)")
    bt.add_argument("--no-flip-exit", action="store_true", help="keep trades when the weekly bias flips")
    bt.add_argument("--cost", type=float, default=2.0, help="spread + commission per trade, in pips")
    bt.add_argument("--no-bias", action="store_true", help="technicals only: ignore the COT/rates bias")
    bt.add_argument("--trades-csv", help="save every simulated trade to this CSV")

    sub.add_parser("paths", help="show where the bias files go")

    args = parser.parse_args(argv)
    cfg = config.load(args.config)

    if args.command == "paths":
        for folder in export.target_dirs(cfg):
            print(folder)
        if not export.find_mt5_common_dirs():
            print("No MT5 found in a Wine prefix yet: run scripts/install_mt5.sh and start the terminal once.")
        return 0

    if args.command in ("report", "export"):
        try:
            state = pipeline.today(cfg)
        except Exception as exc:
            print(f"fxbot: {exc}", file=sys.stderr)
            return 1
        if args.command == "report" and args.json:
            print(json.dumps({
                "cot_report": f"{state.report_date:%Y-%m-%d}",
                "rates": state.rates,
                "rates_source": state.rates_source,
                "pairs": [asdict(b) for b in state.biases],
            }, indent=2))
            return 0
        if not getattr(args, "quiet", False):
            print(report.today(state, cfg))
        if args.command == "export":
            written, warnings = pipeline.write_files(cfg, state)
            for w in warnings:
                print(f"fxbot: {w}", file=sys.stderr)
            if not args.quiet:
                print("\nWrote:")
                for path in written:
                    print(f"  {path}")
                if len(written) <= 2:
                    print("  (no MT5 folder found - run `fxbot paths`)")
        return 0

    if args.command == "backtest":
        from .backtest import SimParams, run  # pandas-heavy; only needed here

        params = SimParams(
            strength=args.strength, retrace=args.retrace, expiry_bars=args.expiry, reward_risk=args.rr,
            msb_only=not args.bos, allow_grade_b=args.grade_b, exit_on_flip=not args.no_flip_exit,
            cost_pips=args.cost, use_bias=not args.no_bias,
        )
        result = run(cfg, since=args.since, params=params)
        print(report.backtest(result))
        if args.trades_csv:
            import pandas as pd

            pd.DataFrame([asdict(t) for t in result["trades"]]).to_csv(args.trades_csv, index=False)
            print(f"\nTrades saved to {args.trades_csv}")
        return 0
    return 2
