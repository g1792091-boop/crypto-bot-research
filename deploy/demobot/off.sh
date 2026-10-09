#!/usr/bin/env bash
# Demo lab bot off: stop the engine, the dashboard, the hourly ranking, the nightly backup and the outside watch
# (timers and a running pass) and a running first fill, and keep them off after a reboot. The database stays; on.sh
# turns it on again and it continues.
#   sudo bash deploy/demobot/off.sh
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
systemctl stop demobot-warm.service 2>/dev/null || true
systemctl disable --now --quiet demobot-live.service demobot-dash.service demobot-rank.timer
# the round-3 timers on their own line: before update.sh has installed them they do not exist
systemctl disable --now --quiet demobot-backup.timer demobot-watch.timer 2>/dev/null || true
systemctl stop demobot-rank.service demobot-backup.service demobot-watch.service 2>/dev/null || true
for u in demobot-live.service demobot-dash.service demobot-rank.timer demobot-backup.timer demobot-watch.timer; do
  echo "$u: $(systemctl is-active "$u" || true)"
done
