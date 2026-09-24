#!/usr/bin/env bash
# Backtest FxBot in MetaTrader 5's Strategy Tester on your broker's own data.
#
# Needs: MT5 logged in to your FBS account at least once (tick "save password"),
#        the EA compiled (scripts/install_ea.sh) and the bias history (fxbot export).
# Usage: scripts/mt5_backtest.sh [FROM yyyy.mm.dd] [TO yyyy.mm.dd]
#        DEPOSIT=5000 PERIOD=H4 scripts/mt5_backtest.sh 2018.01.01
# MT5 must be closed first: the tester run starts its own terminal and shuts it down after.
set -euo pipefail

export WINEPREFIX="${WINEPREFIX:-$HOME/.mt5}"
export WINEDEBUG=-all
MT5_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5"
FROM="${1:-2016.01.01}"
TO="${2:-$(date +%Y.%m.%d)}"
PERIOD="${PERIOD:-D1}"

if pgrep -f "terminal64.exe" >/dev/null; then
  echo "Close MetaTrader 5 first - the tester run starts its own copy." >&2
  exit 1
fi

case "$PERIOD" in  # ENUM_TIMEFRAMES values
  H1) TF=16385 ;; H4) TF=16388 ;; W1) TF=32769 ;; *) TF=16408 ;;
esac

# Model 1 = "1 minute OHLC": realistic enough for stops and targets on D1/H4, and fast.
# The EA's inputs keep their defaults; the timeframe input follows PERIOD.
printf '%s\r\n' \
  "[Tester]" \
  "Expert=FxBot\\FxBot.ex5" \
  "Symbol=EURUSD" \
  "Period=$PERIOD" \
  "Model=1" \
  "FromDate=$FROM" \
  "ToDate=$TO" \
  "Deposit=${DEPOSIT:-10000}" \
  "Currency=USD" \
  "Leverage=100" \
  "Optimization=0" \
  "Visual=0" \
  "Report=fxbot_report" \
  "ReplaceReport=1" \
  "ShutdownTerminal=1" \
  "[TesterInputs]" \
  "InpTimeframe=${TF}||${TF}||0||${TF}||N" \
  > "$MT5_DIR/fxbot_tester.ini"

echo "Running the Strategy Tester ($PERIOD, $FROM - $TO). This can take several minutes..."
(cd "$MT5_DIR" && wine terminal64.exe /config:fxbot_tester.ini) || true

REPORT="$(ls -t "$MT5_DIR"/fxbot_report*.htm* 2>/dev/null | head -1 || true)"
if [ -z "$REPORT" ]; then
  echo "No report was written. Open MT5, check you are logged in, and look at the Journal tab." >&2
  exit 1
fi
echo "Report: $REPORT"
# Pull the headline numbers out of the HTML report (UTF-16 on most builds).
{ iconv -f UTF-16 -t UTF-8 "$REPORT" 2>/dev/null || cat "$REPORT"; } \
  | sed 's/<[^>]*>/ /g; s/&nbsp;/ /g' | tr -s ' \t' ' ' \
  | grep -E "Total Net Profit|Profit Factor|Total Trades|Balance Drawdown Maximal|Profit Trades|Expected Payoff" | sed 's/^ //'
