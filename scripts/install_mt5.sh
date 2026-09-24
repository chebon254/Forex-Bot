#!/usr/bin/env bash
# Install MetaTrader 5 under Wine on Linux (the same prefix MetaQuotes' own Linux script uses).
# Safe to re-run: it skips whatever is already installed.
set -euo pipefail

export WINEPREFIX="${WINEPREFIX:-$HOME/.mt5}"
export WINEDEBUG=-all
MT5_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5"
SETUP_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

if ! command -v wine >/dev/null; then
  echo "Wine is not installed. Run:  sudo apt install wine" >&2
  exit 1
fi

if [ -f "$MT5_DIR/terminal64.exe" ]; then
  echo "MetaTrader 5 is already installed in $MT5_DIR"
  exit 0
fi

# Ubuntu's package keeps wineserver off the PATH.
WINESERVER="$(command -v wineserver || ls /usr/lib/*/wine/wineserver /usr/lib/wine/wineserver 2>/dev/null | head -1 || true)"

if [ ! -f "$WINEPREFIX/system.reg" ]; then
  echo "Creating Wine prefix $WINEPREFIX"
  # MT5 needs neither .NET (mono) nor the HTML engine (gecko); skipping them avoids two install pop-ups.
  WINEDLLOVERRIDES="mscoree,mshtml=" wineboot --init
  [ -n "$WINESERVER" ] && "$WINESERVER" -w
fi
wine reg add 'HKCU\Software\Wine' /v Version /d win10 /f >/dev/null

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Downloading the MetaTrader 5 installer"
curl -fsSL --retry 3 -o "$tmp/mt5setup.exe" "$SETUP_URL"

echo "Installing MetaTrader 5 (takes a few minutes; the terminal opens when done)"
# The installer exits non-zero even when it succeeds, so judge it by the files it leaves.
wine "$tmp/mt5setup.exe" /auto || true

for _ in $(seq 1 180); do
  [ -f "$MT5_DIR/terminal64.exe" ] && break
  sleep 2
done
if [ ! -f "$MT5_DIR/terminal64.exe" ]; then
  echo "Installer finished but terminal64.exe was not found in $MT5_DIR" >&2
  exit 1
fi
echo "Installed: $MT5_DIR"
echo "Start it any time with:  WINEPREFIX=$WINEPREFIX wine \"$MT5_DIR/terminal64.exe\""
