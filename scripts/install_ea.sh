#!/usr/bin/env bash
# Copy the EAs in mt5/ into MetaTrader 5 (under Wine) and compile them with MetaEditor.
# Re-run after every change to an .mq5 file.  Usage: scripts/install_ea.sh [FxBot|IndexBot]
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

if [ $# -gt 0 ]; then names=("$@"); else names=(); for f in "$HERE"/mt5/*.mq5; do names+=("$(basename "$f" .mq5)"); done; fi

failed=0
for name in "${names[@]}"; do
  DEST="$MQL5_DIR/Experts/$name"
  mkdir -p "$DEST"
  cp "$HERE/mt5/$name.mq5" "$DEST/$name.mq5"
  rm -f "$DEST/$name.log" "$DEST/$name.ex5"
  echo "Compiling $name"
  # Paths relative to the data folder: Wine re-quotes absolute "C:\Program Files\..." arguments
  # in a way MetaEditor does not understand. Its exit code is not meaningful; the log is.
  (cd "$(dirname "$MQL5_DIR")" && wine "$MT5_DIR/MetaEditor64.exe" \
    /compile:"MQL5\\Experts\\$name\\$name.mq5" /log:"MQL5\\Experts\\$name\\$name.log") || true
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
[ "$failed" = 0 ] && echo "In MT5 they appear under Navigator > Expert Advisors (right-click > Refresh if needed)."
exit "$failed"
