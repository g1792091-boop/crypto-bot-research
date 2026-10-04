#!/bin/bash
# Clean restart of the paper v3 run (the owners' decision 2026-10-04: fix the early 1m read in paperbot/feed.py,
# remove the 5m timeframe (docs/paper-v3-rules-change-1.md) and start the 30 days again from scratch, once).
# Run from the repository after `git pull` (docs/server-setup-v3.md "처음부터 다시 시작"):
#
#     sudo bash deploy/paperbot-reset.sh --dry-run    # shows what it would do; changes nothing, stops nothing
#     sudo bash deploy/paperbot-reset.sh --yes
#
# 1. stops the bot, dashboard, trade alerts, the agents and the scheduled jobs (waits for a running nightly job to
#    finish); the market recorders (liquidations, GH Coin calls, flow, market) keep running. Refuses while the order
#    executor runs (it reads paper3.db) and checks that no process still has a run file open;
# 2. installs the pulled code (deploy/install.sh): a failure here leaves the old run untouched;
# 3. MOVES (never deletes) the run's own files to /var/lib/paperbot/archive/run-<UTC time>/ (ARCHIVE_DBS and
#    ARCHIVE_FILES below);
# 4. KEEPS the agents' memory and the owners' inbox in place (agents3.db, inbox.db): paperbot/resetrun.py copies
#    both into the archive folder first, then resets only the agents' cursors that point into the old paper3.db,
#    closes proposals of the old run and tells every room once that the experiment restarted;
# 5. starts everything that was running again: the bot creates 156 fresh $5,000 accounts (36 strategies + 3 coin-flip
#    accounts on each of 15m, 30m, 1h, 4h; no 5m) and that moment is the new start (30-day checkpoint: the start's
#    UTC day + 30, paperbot.checkpoint.checkpoint_ts; observation period: start + 21 days).
#
# Not touched (KEEP below): /etc/paperbot/*, the order executor and its keys, liq.db, market.db, flow.db, paper.db,
# ghcoin/, lab/, failalert/, exec/, price_alerts.json, the backups. Not between 08:30 and 09:40 KST (nightly check
# and checkpoint time).
set -Eeuo pipefail

MODE="${1:-}"
case "$MODE" in
  --yes|--dry-run) ;;
  *) echo "usage: sudo bash deploy/paperbot-reset.sh --dry-run | --yes   (--yes moves the current run to an archive and starts a new one)"
     exit 2 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${PAPERBOT_LIB:-/var/lib/paperbot}"
ETC="${PAPERBOT_ETC:-/etc/paperbot}"
PY="${PAPERBOT_PY:-/opt/paperbot/venv/bin/python}"
RUN_USER="${PAPERBOT_RESET_USER-paperbot}"
SYSTEMCTL="${PAPERBOT_SYSTEMCTL:-systemctl}"
INSTALL="${PAPERBOT_INSTALL:-$REPO_DIR/deploy/install.sh}"
WAIT_S="${PAPERBOT_RESET_WAIT:-180}"           # how long to wait for the bot's new accounts
# (the PAPERBOT_* overrides exist for tests/test_reset_script.py; the server uses the defaults)

# What a restart archives (moved with their -wal/-shm/-journal) and what it keeps. Only the run's own files are
# here: never agents3.db / inbox.db (the agents' memory, the owners' posts and price alerts) or a market recorder
# (tests/test_reset_script.py checks these lists).
ARCHIVE_DBS="paper3.db daily3.db checkpoint.db"
ARCHIVE_FILES="tradealerts.json evening-latest.json checkpoint_bars rehearsal"
KEEP="agents3.db inbox.db price_alerts.json liq.db market.db flow.db paper.db ghcoin lab failalert exec"

SERVICES="paperbot-live3 paperbot-dash paperbot-tgtrades"
TIMERS="paperbot-agents.timer paperbot-daily3.timer paperbot-checkpoint.timer paperbot-rehearsal.timer \
paperbot-backup.timer paperbot-offsite.timer paperbot-labmonthly.timer paperbot-evening.timer"
JOBS="paperbot-agents.service paperbot-daily3.service paperbot-backup.service paperbot-checkpoint.service \
paperbot-labmonthly.service paperbot-offsite.service paperbot-rehearsal.service paperbot-evening.service"
# every process that writes (or reads, the executor) a file the restart moves or changes
WRITERS="$SERVICES $JOBS paperbot-executor"

active() { "$SYSTEMCTL" is-active --quiet "$1" 2>/dev/null; }

# the helper runs from this repository (the code being installed) and, as root, becomes the services' user first
helper() { ( trap - ERR; cd "$REPO_DIR" && "$PY" -m paperbot.resetrun "$@" --user "$RUN_USER" ); }

# files of the run that a process still has open (fuser, else lsof, else /proc); prints them
holders() {
  local f found=""
  for f in $ARCHIVE_DBS agents3.db inbox.db; do
    for s in "" -wal -shm -journal; do
      [ -e "$DATA/$f$s" ] || continue
      if command -v fuser >/dev/null 2>&1; then
        if fuser -s "$DATA/$f$s" 2>/dev/null; then found="$found $f$s"; fi
      elif command -v lsof >/dev/null 2>&1; then
        if lsof -t -- "$DATA/$f$s" >/dev/null 2>&1; then found="$found $f$s"; fi
      else
        if find /proc/[0-9]*/fd -lname "$DATA/$f$s" 2>/dev/null | grep -q .; then found="$found $f$s"; fi
      fi
    done
  done
  echo "$found"
}

hm=$(TZ=Asia/Seoul date +%H%M)
hm="${PAPERBOT_RESET_HM:-$hm}"
in_window=0
if [ "$((10#$hm))" -ge 830 ] && [ "$((10#$hm))" -lt 940 ]; then in_window=1; fi

# ------------------------------------------------------------------------------------------------- dry run
if [ "$MODE" = "--dry-run" ]; then
  echo "== 미리 보기 (--dry-run): 아무것도 멈추거나 옮기거나 바꾸지 않습니다"
  if [ "$in_window" -eq 1 ]; then
    echo "!! 지금은 08:30-09:40 KST(밤 점검·판정 시간)라 --yes는 거절됩니다. 09:40 뒤에 하세요"
  fi
  run_now=""
  for u in $SERVICES $TIMERS $JOBS; do
    if active "$u"; then run_now="$run_now $u"; fi
  done
  echo "[멈출 것]${run_now:- (지금 도는 것 없음)}"
  if active paperbot-executor; then
    echo "!! paperbot-executor(주문 실행기)가 돌고 있습니다: paper3.db를 읽으므로 --yes 전에 직접 멈춰야 합니다 (sudo systemctl stop paperbot-executor)"
  fi
  echo "[보관 폴더로 옮길 것: $DATA/archive/run-<UTC 시각>/]"
  for f in $ARCHIVE_DBS; do
    for s in "" -wal -shm -journal; do
      if [ -e "$DATA/$f$s" ]; then echo "  $f$s ($(du -sh "$DATA/$f$s" | cut -f1))"; fi
    done
  done
  for f in $ARCHIVE_FILES; do
    if [ -e "$DATA/$f" ]; then echo "  $f ($(du -sh "$DATA/$f" | cut -f1))"; fi
  done
  echo "[그대로 둘 것]"
  for f in $KEEP; do
    if [ -e "$DATA/$f" ]; then echo "  $f"; fi
  done
  echo "  /etc/paperbot/*, 백업(/var/backups/paperbot), 주문 실행기"
  echo "[agents3.db / inbox.db: 보관 폴더에 사본을 만든 뒤 아래만 바꿈]"
  helper plan --lib "$DATA" --etc "$ETC"
  echo "[코드] $REPO_DIR -> deploy/install.sh ($(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo '?'))"
  if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "!! 저장소에 커밋 안 된 수정이 있어 install.sh가 멈춥니다"
  fi
  echo "실제로 하려면: sudo bash deploy/paperbot-reset.sh --yes"
  exit 0
fi

# ------------------------------------------------------------------------------------------------- the reset
if [ "$in_window" -eq 1 ]; then
  echo "08:30-09:40 KST is the nightly check / checkpoint window: run this after 09:40"; exit 1
fi
if active paperbot-executor; then
  echo "paperbot-executor (the order executor) is running and reads paper3.db. Stop it yourself first:"
  echo "  sudo systemctl stop paperbot-executor"
  echo "then run this again, and start it after the reset (check its paper account: 5m accounts are gone)."
  exit 1
fi
[ -x "$PY" ] || { echo "$PY not found: install the server first (deploy/install.sh)"; exit 1; }
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
  echo "the repository has uncommitted changes (install.sh would stop): deploy only committed code"; exit 1
fi
echo "== 0. check (nothing changed yet)"
helper plan --lib "$DATA" --etc "$ETC"

PHASE=none
RUNNING=""
ARCH=""
MOVED=""
on_fail() {
  local line="$1"
  trap - ERR
  echo
  echo "!! 실패 (줄 $line, 단계 $PHASE)"
  case "$PHASE" in
    stopping|stopped|installing|installed)
      echo "이전 실행은 그대로입니다(아무 파일도 옮기지 않음)."
      if [ -n "$RUNNING" ]; then echo "다시 켜기: sudo systemctl start$RUNNING"; fi
      if [ "$PHASE" = installed ]; then echo "(새 코드는 설치됐습니다. 원인을 고친 뒤 이 스크립트를 다시 돌리면 됩니다)"; fi
      if [ "$PHASE" = installing ]; then
        echo "(install.sh가 코드를 바꾼 뒤에 멈췄다면 새 코드로 이전 실행이 켜집니다: 원인을 고친 뒤 이 스크립트를 다시 돌리세요)"
      fi
      ;;
    moving|moved|reset)
      echo "이전 실행 파일을 $ARCH 로 옮겼습니다:${MOVED:- (아직 없음)}"
      echo "새 실행으로 계속하기(권장): 원인을 고친 뒤"
      echo "  sudo $PY -m paperbot.resetrun apply --lib $DATA --archive $ARCH --user paperbot   (여러 번 해도 같음)"
      if [ -n "$RUNNING" ]; then echo "  sudo systemctl start$RUNNING"; fi
      echo "이전 실행으로 되돌리기:"
      for m in $MOVED; do echo "  sudo mv $ARCH/$m $DATA/"; done
      echo "  (agents3.db/inbox.db를 이전 상태로: sudo -u paperbot cp $ARCH/agents3-before-reset.db $DATA/agents3.db 등 — 커서만 다르고 기억은 같음)"
      if [ -n "$RUNNING" ]; then echo "  sudo systemctl start$RUNNING"; fi
      ;;
    starting)
      echo "새 실행 준비는 끝났습니다. 다시 켜기: sudo systemctl start$RUNNING"
      ;;
    *) echo "아무것도 바뀌지 않았습니다." ;;
  esac
  exit 1
}
trap 'on_fail $LINENO' ERR

echo "== 1. stop"
PHASE=stopping
for u in $SERVICES $TIMERS; do
  if active "$u"; then RUNNING="$RUNNING $u"; fi
done
# shellcheck disable=SC2086  # unit names, split on purpose
if [ -n "$RUNNING" ]; then "$SYSTEMCTL" stop $RUNNING; fi
if active paperbot-agents.service; then "$SYSTEMCTL" stop paperbot-agents.service; fi
n=0
while busy="$(for j in $JOBS; do if active "$j"; then echo "$j"; fi; done)"; [ -n "$busy" ]; do
  n=$((n+1)); [ "$n" -ge 120 ] && { echo "still running after 60 min: $busy"; false; }
  echo "waiting for a scheduled job to finish: $busy ($n/120)"; sleep 30
done
PHASE=stopped
echo "stopped:${RUNNING:- (nothing was running)}"
for u in $WRITERS; do
  if active "$u"; then echo "$u is still active"; false; fi
done
open_now="$(holders)"
if [ -n "$open_now" ]; then
  echo "still open by a process:$open_now"
  command -v fuser >/dev/null 2>&1 && for f in $open_now; do fuser -v "$DATA/$f" || true; done
  false
fi
echo "no process has the run files open"

echo "== 2. install the pulled code"
PHASE=installing
bash "$INSTALL"
PHASE=installed
echo "(install.sh의 마지막 안내는 처음 설치용입니다. 이 스크립트가 이어서 진행합니다)"

echo "== 3. archive the old run (moved, not deleted)"
ARCH="$DATA/archive/run-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o "${RUN_USER:-root}" -g "${RUN_USER:-root}" -m 750 "$DATA/archive" "$ARCH"
PHASE=moving
for f in $ARCHIVE_DBS; do
  for s in "" -wal -shm -journal; do
    if [ -e "$DATA/$f$s" ]; then mv "$DATA/$f$s" "$ARCH/"; MOVED="$MOVED $f$s"; fi
  done
done
for f in $ARCHIVE_FILES; do
  if [ -e "$DATA/$f" ]; then mv "$DATA/$f" "$ARCH/"; MOVED="$MOVED $f"; fi
done
install -d -o "${RUN_USER:-root}" -g "${RUN_USER:-root}" -m 750 "$DATA/rehearsal"
PHASE=moved
echo "moved to $ARCH:${MOVED:- (nothing)}"

echo "== 4. agents' memory kept; run-bound cursors reset (backup first)"
helper apply --lib "$DATA" --archive "$ARCH"
PHASE=reset

echo "== 5. start the new run"
PHASE=starting
if [ -n "$RUNNING" ]; then
  # shellcheck disable=SC2086  # unit names, split on purpose
  "$SYSTEMCTL" start $RUNNING
  echo "started:$RUNNING"
else
  echo "nothing was running before; start the bot as in docs/server-setup-v3.md"
fi
trap - ERR
PHASE=finished

echo
echo "================ 요약 ================"
echo "보관(옮김, 지우지 않음): $ARCH"
echo " ${MOVED:- (없음)}"
echo "그대로 둠: agents3.db(시험 장부·메모·채점·회의 기록·제안 기록), inbox.db(두 분의 글·승인 기록·가격 알림),"
echo "  price_alerts.json, liq.db·flow.db·market.db·ghcoin(시장 기록), lab, failalert, exec, /etc/paperbot, 백업"
echo "  agents3.db·inbox.db의 바꾸기 전 사본: $ARCH/agents3-before-reset.db, $ARCH/inbox-before-reset.db"
echo "초기화: 이전 paper3.db를 가리키던 에이전트 커서(위 4단계), 이전 실행의 열린 제안(닫음)"
if active paperbot-live3; then
  if ! helper start --paper-db "$DATA/paper3.db" --wait "$WAIT_S"; then
    echo "몇 분 뒤 시작 시각과 첫 판정일 확인:"
    echo "  cd /opt/crypto-bot-research && sudo -u paperbot $PY -m paperbot.resetrun start --paper-db $DATA/paper3.db"
  fi
  echo "5분 뒤 점검: cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after"
else
  echo "paperbot-live3 is not running: sudo journalctl -u paperbot-live3 -n 50 --no-pager"
fi
