#!/bin/bash
# Clean restart of the paper v3 run (the owners' decision 2026-10-04: fix the early 1m read in paperbot/feed.py,
# remove the 5m timeframe (docs/paper-v3-rules-change-1.md) and start the 30 days again from scratch, once).
# Run from the repository after `git pull`:
#
#     sudo bash deploy/paperbot-reset.sh --yes
#
# 1. stops the bot, dashboard, trade alerts and the scheduled jobs (waits for a running nightly job to finish);
#    the market recorders (liquidations, GH Coin calls, flow, market) keep running;
# 2. MOVES (never deletes) the run's files to /var/lib/paperbot/archive/run-<UTC time>/: paper3.db, daily3.db,
#    checkpoint.db, agents3.db, inbox.db (with their -wal/-shm), checkpoint_bars/, rehearsal/, tradealerts.json,
#    evening-latest.json;
# 3. installs the pulled code (deploy/install.sh);
# 4. starts everything that was running again: the bot creates 156 fresh $5,000 accounts (36 strategies + 3 coin-flip
#    accounts on each of 15m, 30m, 1h, 4h; no 5m) and that moment is the new start (30-day checkpoint = start
#    day + 30, observation period = start + 21 days; both follow the start by rule).
#
# Not touched: /etc/paperbot/*.env, the order executor and its keys, liq.db, market.db, flow.db, ghcoin/, lab/,
# failalert/, the backups. Do not run it between 08:30 and 09:40 KST (nightly check and checkpoint time).
set -euo pipefail

[ "${1:-}" = "--yes" ] || { echo "usage: sudo bash deploy/paperbot-reset.sh --yes   (moves the current run to an archive and starts a new one)"; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA=/var/lib/paperbot

hm=$(TZ=Asia/Seoul date +%H%M)
if [ "$hm" -ge 0830 ] && [ "$hm" -lt 0940 ]; then
  echo "08:30-09:40 KST is the nightly check / checkpoint window: run this after 09:40"; exit 1
fi

SERVICES="paperbot-live3 paperbot-dash paperbot-tgtrades"
TIMERS="paperbot-agents.timer paperbot-daily3.timer paperbot-checkpoint.timer paperbot-rehearsal.timer \
paperbot-backup.timer paperbot-offsite.timer paperbot-labmonthly.timer paperbot-evening.timer"
JOBS="paperbot-daily3.service paperbot-backup.service paperbot-checkpoint.service paperbot-labmonthly.service \
paperbot-offsite.service paperbot-rehearsal.service paperbot-evening.service"

echo "== 1. stop"
RUNNING=""
for u in $SERVICES $TIMERS; do
  if systemctl is-active --quiet "$u" 2>/dev/null; then RUNNING="$RUNNING $u"; fi
done
if [ -n "$RUNNING" ]; then systemctl stop $RUNNING; fi
if systemctl is-active --quiet paperbot-agents.service 2>/dev/null; then systemctl stop paperbot-agents.service; fi
n=0
while busy="$(for j in $JOBS; do systemctl is-active --quiet "$j" 2>/dev/null && echo "$j"; done)"; [ -n "$busy" ]; do
  n=$((n+1)); [ "$n" -ge 120 ] && { echo "still running after 60 min: $busy; start again later with: sudo systemctl start$RUNNING"; exit 1; }
  echo "waiting for a scheduled job to finish: $busy ($n/120)"; sleep 30
done
echo "stopped:${RUNNING:- (nothing was running)}"

echo "== 2. archive the old run (moved, not deleted)"
ARCH="$DATA/archive/run-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o paperbot -g paperbot -m 750 "$DATA/archive" "$ARCH"
moved=0
for f in paper3.db daily3.db checkpoint.db agents3.db inbox.db; do
  for s in "" -wal -shm -journal; do
    if [ -e "$DATA/$f$s" ]; then mv "$DATA/$f$s" "$ARCH/"; moved=$((moved+1)); fi
  done
done
for f in agents3.db.lock tradealerts.json evening-latest.json checkpoint_bars rehearsal; do
  if [ -e "$DATA/$f" ]; then mv "$DATA/$f" "$ARCH/"; moved=$((moved+1)); fi
done
install -d -o paperbot -g paperbot -m 750 "$DATA/rehearsal"
echo "moved $moved items to $ARCH"

echo "== 3. install the pulled code"
bash "$REPO_DIR/deploy/install.sh"

echo "== 4. start the new run"
if [ -n "$RUNNING" ]; then
  systemctl start $RUNNING
  echo "started:$RUNNING"
else
  echo "nothing was running before; start the bot as in docs/server-setup-v3.md"
fi
sleep 20
if systemctl is-active --quiet paperbot-live3; then
  echo "new run started $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST') with 156 accounts (15m/30m/1h/4h, no 5m); first 30-day checkpoint: $(TZ=Asia/Seoul date -d '+30 days' '+%Y-%m-%d') (by the start day)"
  echo "check in 5 minutes: sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.launchcheck after"
else
  echo "paperbot-live3 is not running: sudo journalctl -u paperbot-live3 -n 50 --no-pager"
fi
