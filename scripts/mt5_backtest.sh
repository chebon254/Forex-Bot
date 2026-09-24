#!/usr/bin/env bash
# Backtest an EA in MetaTrader 5's Strategy Tester on your broker's own data.
#
# Needs: MT5 logged in to your FBS account at least once (tick "save password") and the EA
#        compiled (scripts/install_ea.sh). FxBot also needs the bias history (fxbot export).
# MT5 must be closed first: the tester run starts its own terminal and shuts it down after.
#
# Usage: scripts/mt5_backtest.sh [FROM yyyy.mm.dd] [TO yyyy.mm.dd]
#   FxBot (default):   scripts/mt5_backtest.sh 2016.01.01
#                      PERIOD=H4 scripts/mt5_backtest.sh
#   IndexBot:          EA=IndexBot SYMBOL=US100 scripts/mt5_backtest.sh 2015.01.01
#                      EA=IndexBot SYMBOL=US100 INPUTS="InpRules=1 InpTrendExposure=1" scripts/mt5_backtest.sh
set -euo pipefail

export WINEPREFIX="${WINEPREFIX:-$HOME/.mt5}"
export WINEDEBUG=-all
MT5_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5"
EA="${EA:-FxBot}"
SYMBOL="${SYMBOL:-EURUSD}"
FROM="${1:-2016.01.01}"
TO="${2:-$(date +%Y.%m.%d)}"
PERIOD="${PERIOD:-D1}"
INPUTS="${INPUTS:-}"
REPORT_NAME="${REPORT:-${EA}_report}"

# Under Wine, MT5 runs as a process called "main" whose arguments name terminal64.exe; skip
# shells, whose command lines may mention it too.
mt5_running() {
  ps -eo comm=,args= | awk '$1 !~ /^(bash|sh|awk|grep|timeout|setsid|nohup)$/ && index($0, "terminal64.exe") { f = 1 } END { exit !f }'
}
if mt5_running; then
  echo "Close MetaTrader 5 first - the tester run starts its own copy." >&2
  exit 1
fi

if [ "$EA" = "FxBot" ]; then
  case "$PERIOD" in  # ENUM_TIMEFRAMES values; FxBot's structure timeframe follows PERIOD
    H1) TF=16385 ;; H4) TF=16388 ;; W1) TF=32769 ;; *) TF=16408 ;;
  esac
  INPUTS="InpTimeframe=$TF $INPUTS"
fi

# Model 1 = "1 minute OHLC": realistic enough for daily and 4-hour systems, and fast.
# (MODEL=2 = open prices only, for tools like ExportBars that don't trade.)
{
  printf '%s\r\n' "[Tester]" "Expert=$EA\\$EA.ex5" "Symbol=$SYMBOL" "Period=$PERIOD" "Model=${MODEL:-1}" \
    "FromDate=$FROM" "ToDate=$TO" "Deposit=${DEPOSIT:-10000}" "Currency=USD" "Leverage=100" \
    "Optimization=0" "Visual=0" "Report=$REPORT_NAME" "ReplaceReport=1" "ShutdownTerminal=1" "[TesterInputs]"
  for kv in $INPUTS; do
    k="${kv%%=*}"; v="${kv#*=}"
    # numbers take value||start||step||stop||optimize; text and true/false are written as-is
    if [[ "$v" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; then printf '%s\r\n' "$k=$v||$v||0||$v||N"; else printf '%s\r\n' "$k=$v"; fi
  done
} > "$MT5_DIR/fxbot_tester.ini"

echo "Running the Strategy Tester: $EA on $SYMBOL $PERIOD, $FROM - $TO ${INPUTS:+($INPUTS)}"
(cd "$MT5_DIR" && wine terminal64.exe /config:fxbot_tester.ini) || true

REPORT="$MT5_DIR/$REPORT_NAME.htm"
if [ ! -f "$REPORT" ]; then
  echo "No report was written. Open MT5, check you are logged in, and look at the Journal tab." >&2
  exit 1
fi
echo "Report: $REPORT"
# Headline numbers: each label sits in its own table cell with the value in the next one.
python3 - "$REPORT" <<'PY'
import html, re, sys
raw = open(sys.argv[1], "rb").read()
text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", text, re.S | re.I)]
want = ["History Quality:", "Total Net Profit:", "Profit Factor:", "Balance Drawdown Maximal:", "Total Trades:",
        "Profit Trades (% of total):", "Expected Payoff:", "Sharpe Ratio:"]
for i, c in enumerate(cells[:-1]):
    if c in want:
        print(f"  {c:<28} {cells[i + 1]}")
        want.remove(c)
PY
