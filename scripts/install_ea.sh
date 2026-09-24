#!/usr/bin/env bash
# Copy the FxBot EA into MetaTrader 5 (under Wine) and compile it with MetaEditor.
# Re-run after every change to mt5/FxBot.mq5.
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

DEST="$MQL5_DIR/Experts/FxBot"
mkdir -p "$DEST"
cp "$HERE/mt5/FxBot.mq5" "$DEST/FxBot.mq5"
rm -f "$DEST/FxBot.log" "$DEST/FxBot.ex5"

echo "Compiling $DEST/FxBot.mq5"
# Paths relative to the data folder: Wine re-quotes absolute "C:\Program Files\..." arguments
# in a way MetaEditor does not understand. Its exit code is not meaningful; the log is.
(cd "$(dirname "$MQL5_DIR")" && wine "$MT5_DIR/MetaEditor64.exe" \
  /compile:'MQL5\Experts\FxBot\FxBot.mq5' /log:'MQL5\Experts\FxBot\FxBot.log') || true

if [ -f "$DEST/FxBot.log" ]; then
  iconv -f UTF-16 -t UTF-8 "$DEST/FxBot.log" | tr -d '\r' | grep -E 'error|warning|Result' || true
fi
if [ -f "$DEST/FxBot.ex5" ]; then
  echo "OK: $DEST/FxBot.ex5"
  echo "In MT5 it appears under Navigator > Expert Advisors > FxBot (right-click > Refresh if needed)."
else
  echo "Compile failed - see the messages above." >&2
  exit 1
fi
