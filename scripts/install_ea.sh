#!/usr/bin/env bash
# Copy the EAs (mt5/) and indicators (mt5/indicators/) into MetaTrader 5 under Wine and compile
# them with MetaEditor. Re-run after every change.  Usage: scripts/install_ea.sh [name ...]
set -euo pipefail

export WINEPREFIX="${WINEPREFIX:-$HOME/.mt5}"
export WINEDEBUG=-all
HERE="$(cd "$(dirname "$0")/.." && pwd)"
MT5_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5"

# Under Wine, MT5 usually keeps its data in the install folder; otherwise it is under AppData.
MQL5_DIR="$MT5_DIR/MQL5"
if [ ! -d "$MQL5_DIR" ]; then
  MQL5_DIR="$(ls -d "$WINEPREFIX"/drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/MQL5 2>/dev/null | head -1 || true)"
fi
if [ -z "$MQL5_DIR" ] || [ ! -d "$MQL5_DIR" ]; then
  echo "MetaTrader 5 data folder not found. Run scripts/install_mt5.sh, then open the terminal once." >&2
  exit 1
fi

# EAs live in mt5/*.mq5 (-> MQL5/Experts/<name>/), indicators in mt5/indicators/*.mq5 (-> MQL5/Indicators/<name>/).
targets=()
if [ $# -gt 0 ]; then
  for name in "$@"; do
    if [ -f "$HERE/mt5/$name.mq5" ]; then targets+=("Experts|$HERE/mt5/$name.mq5")
    elif [ -f "$HERE/mt5/indicators/$name.mq5" ]; then targets+=("Indicators|$HERE/mt5/indicators/$name.mq5")
    else echo "No mt5/$name.mq5 or mt5/indicators/$name.mq5" >&2; exit 1; fi
  done
else
  for f in "$HERE"/mt5/*.mq5; do targets+=("Experts|$f"); done
  for f in "$HERE"/mt5/indicators/*.mq5; do [ -e "$f" ] && targets+=("Indicators|$f"); done
fi

failed=0
for t in "${targets[@]}"; do
  kind="${t%%|*}"; src="${t#*|}"; name="$(basename "$src" .mq5)"
  DEST="$MQL5_DIR/$kind/$name"
  mkdir -p "$DEST"
  cp "$src" "$DEST/$name.mq5"
  rm -f "$DEST/$name.log" "$DEST/$name.ex5"
  echo "Compiling $kind/$name"
  # Paths relative to the data folder: Wine re-quotes absolute "C:\Program Files\..." arguments
  # in a way MetaEditor does not understand. Its exit code is not meaningful; the log is.
  (cd "$(dirname "$MQL5_DIR")" && wine "$MT5_DIR/MetaEditor64.exe" \
    /compile:"MQL5\\$kind\\$name\\$name.mq5" /log:"MQL5\\$kind\\$name\\$name.log") || true
  if [ -f "$DEST/$name.log" ]; then
    iconv -f UTF-16 -t UTF-8 "$DEST/$name.log" | tr -d '\r' | grep -E 'error|warning|Result' || true
  fi
  if [ -f "$DEST/$name.ex5" ]; then
    echo "OK: $DEST/$name.ex5"
  else
    echo "$name: compile failed - see the messages above." >&2
    failed=1
  fi
done
[ "$failed" = 0 ] && echo "In MT5 they appear in the Navigator under Expert Advisors / Indicators (right-click > Refresh if needed)."
exit "$failed"
