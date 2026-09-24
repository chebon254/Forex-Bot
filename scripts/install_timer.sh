#!/usr/bin/env bash
# Refresh the bias every 6 hours (and after the machine wakes up) with a systemd user timer.
# Undo with:  systemctl --user disable --now fxbot-export.timer
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/fxbot-export.service" <<EOF
[Unit]
Description=FxBot: refresh the COT + interest-rate bias for MT5

[Service]
Type=oneshot
ExecStart="$HERE/.venv/bin/fxbot" export --quiet
EOF

cat > "$UNIT_DIR/fxbot-export.timer" <<EOF
[Unit]
Description=FxBot: refresh the bias every 6 hours (COT lands Fridays 22:30-23:30 EAT)

[Timer]
OnCalendar=*-*-* 00/6:30:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now fxbot-export.timer
systemctl --user list-timers fxbot-export.timer --no-pager
echo
echo "Run it now:  systemctl --user start fxbot-export.service"
echo "Logs:        journalctl --user -u fxbot-export"
echo "Stop:        systemctl --user disable --now fxbot-export.timer"
