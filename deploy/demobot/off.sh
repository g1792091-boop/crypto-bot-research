#!/usr/bin/env bash
# Demo lab bot off: stop the engine, the dashboard and the hourly ranking (timer and a running pass) and a running
# first fill, and keep them off after a reboot. The database stays; on.sh turns it on again and it continues.
#   sudo bash deploy/demobot/off.sh
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
systemctl stop demobot-warm.service 2>/dev/null || true
systemctl disable --now --quiet demobot-live.service demobot-dash.service demobot-rank.timer
systemctl stop demobot-rank.service 2>/dev/null || true
for u in demobot-live.service demobot-dash.service demobot-rank.timer; do
  echo "$u: $(systemctl is-active "$u" || true)"
done
