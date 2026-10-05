#!/bin/bash
# Clean restart of the paper run. Paper v4 (the owners' decision 2026-10-05, docs/paper-v4-rules.md): the v3 run is
# archived without a day-30 verdict and a new run starts with the 36 strategies, the DeepSeek-200 definitions, the 5m
# reel and the coin flips (config.V4_GROUPS). (The v3 restart of 2026-10-04 used this same script.)
# Run from the repository after `git pull` (docs/server-setup-v4.md, step by step):
#
#     sudo bash deploy/paperbot-reset.sh --dry-run    # shows what it would do; changes nothing, stops nothing
#     sudo bash deploy/paperbot-reset.sh --yes [--agents-off]
#
# --agents-off: keep the agents' tick (paperbot-agents.timer) off with the new run: stopped, disabled, not started
# (owners' D15: on only when the agents' v4 must-items have landed; the developer tells the owners whether to add
# it). Without it the tick comes back like every other unit that ran or was enabled (--agents-on says the same
# explicitly). With the tick off there are no morning, ranking, evening, weekly or market-move messages: the summary
# and launchcheck say so (AGENTS_OFF_KO) and print the one command that turns it on.
# The Obsidian export and the DeepSeek nightly recompute check (AFTER_CHECK_TIMERS) are stopped, installed and kept
# OFF (disabled) whatever their state before; the owners switch them on, with the DeepSeek-200 shadow test's timer,
# after the post-reset checks (docs/server-setup-v4.md step 5). Every other unit that ran (or was enabled) comes back.
#
# --yes refuses to run a second time: when the current paper3.db holds a v4 run (paper-v4) that started less than
# 24 h ago right after a restart marker (agents3.db cursor run:restarted, paperbot.resetrun guard), that run is the
# reset's new run. A young v3 run (the v3 restart wrote the same marker) is not refused.
# `--yes --force-again` overrides it (only after talking to the developer).
#
# 1. stops the bot, dashboard, trade alerts, the 24-hour debate room, the agents and the scheduled jobs (also the
#    Obsidian export and the DeepSeek nightly recompute check, which read the run's files; waits for a running nightly
#    job to finish); the market recorders (liquidations, GH Coin calls, flow, market) and the DeepSeek-200 shadow test
#    (its own database and T0, pinned; it never reads a run file) keep running. Every listed service
#    and timer that is loaded is stopped (stop is idempotent), whatever its state: a unit waiting to auto-restart
#    after a crash shows "activating", not "active", and would otherwise come back while files move. The ones that
#    were running (active / activating / deactivating / reloading) or are enabled are started again in step 6.
#    A running oneshot job also shows "activating": the job wait and the writer check treat it as running.
#    Refuses while the order executor runs (it reads paper3.db) and checks that no process still has a run file open;
# 2. takes a fresh backup of the stopped run before anything moves: starts paperbot-backup.service (a oneshot:
#    `systemctl start` returns when it has finished), checks its result and that today's backup folder holds a
#    new copy of paper3.db / daily3.db / checkpoint.db; a failure stops the reset here (nothing moved). The day's
#    folder is then copied to $BACKUPS/<UTC date>-before-reset-<UTC time>/<UTC date>/, which the 08:40 KST nightly
#    backup never writes (it rewrites the day's own folder with the NEW run; 14 days kept like the others). Then the
#    off-site copy (paperbot-offsite.service) when its timer is enabled: a failure there is only a warning (the
#    server's own copy is already made; the summary prints how to send the kept copy again);
# 3. installs the pulled code (deploy/install.sh with PAPERBOT_RESETTING=1: it installs the Obsidian, shadow-test and
#    DeepSeek-check timers without switching them on); a failure here leaves the old run untouched;
# 4. MOVES (never deletes) the run's own files to /var/lib/paperbot/archive/run-<UTC time>/ (ARCHIVE_DBS and
#    ARCHIVE_FILES below);
# 5. KEEPS the agents' memory and the owners' inbox in place (agents3.db, inbox.db): paperbot/resetrun.py copies
#    both into the archive folder first, then resets only the agents' cursors that point into the old paper3.db,
#    closes proposals of the old run and tells every room once that the experiment restarted;
# 6. starts everything that was running again (not the agents' tick with --agents-off, never the Obsidian export or
#    the DeepSeek check: AFTER_CHECK_TIMERS stay off until the owners' checks): the bot creates the paper v4
#    accounts (config.V4_ACCOUNTS fresh $5,000 accounts, every group in one step) and that moment is the new start
#    (30-day checkpoint: the start's UTC day + 30, paperbot.checkpoint.checkpoint_ts; observation period: start + 21
#    days; no date is typed anywhere, all follow from the start).
#
# Not touched (KEEP below): /etc/paperbot/*, the order executor and its keys, liq.db, market.db, flow.db, paper.db,
# ghcoin/, lab/, failalert/, exec/, price_alerts.json, debate/, shadow200/, obsidian/, the backups. Not between 08:30
# and 09:40 KST (nightly check and checkpoint time).
set -Eeuo pipefail

MODE=""
AGAIN=""
AGENTS_ON=1
AGENTS_FLAG=""
USAGE="usage: sudo bash deploy/paperbot-reset.sh --dry-run | --yes [--force-again] [--agents-off]   (--yes moves the current run to an archive and starts a new one; --agents-off keeps the agents' tick off)"
for arg in "$@"; do
  case "$arg" in
    --yes|--dry-run) [ -z "$MODE" ] || { echo "$USAGE"; exit 2; }; MODE="$arg" ;;
    --force-again) AGAIN="$arg" ;;
    --agents-on|--agents-off)
      if [ -n "$AGENTS_FLAG" ] && [ "$AGENTS_FLAG" != "$arg" ]; then echo "$USAGE"; exit 2; fi
      AGENTS_FLAG="$arg"
      if [ "$arg" = --agents-off ]; then AGENTS_ON=0; else AGENTS_ON=1; fi ;;
    *) echo "$USAGE"; exit 2 ;;
  esac
done
[ -n "$MODE" ] || { echo "$USAGE"; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${PAPERBOT_LIB:-/var/lib/paperbot}"
ETC="${PAPERBOT_ETC:-/etc/paperbot}"
PY="${PAPERBOT_PY:-/opt/paperbot/venv/bin/python}"
RUN_USER="${PAPERBOT_RESET_USER-paperbot}"
SYSTEMCTL="${PAPERBOT_SYSTEMCTL:-systemctl}"
INSTALL="${PAPERBOT_INSTALL:-$REPO_DIR/deploy/install.sh}"
WAIT_S="${PAPERBOT_RESET_WAIT:-180}"           # how long to wait for the bot's new accounts
POLL_S="${PAPERBOT_RESET_POLL:-30}"            # how often to look again while a scheduled job runs
BACKUPS="${PAPERBOT_BACKUPS:-/var/backups/paperbot}"   # where paperbot-backup.service writes (deploy/paperbot-backup.sh)
# (the PAPERBOT_* overrides exist for tests/test_reset_script.py; the server uses the defaults)

# What a restart archives (moved with their -wal/-shm/-journal) and what it keeps. Only the run's own files are
# here: never agents3.db / inbox.db (the agents' memory, the owners' posts and price alerts) or a market recorder
# (tests/test_reset_script.py checks these lists).
ARCHIVE_DBS="paper3.db daily3.db checkpoint.db"
# dscheck: the DeepSeek nightly recompute check's summary of the run (and its bar cache); made again, empty, below
ARCHIVE_FILES="tradealerts.json evening-latest.json checkpoint_bars rehearsal dscheck"
# debate: the debate room's own claims (paperbot/agents/debate.py voids a claim made in another run when grading);
# shadow200: the DeepSeek-200 shadow test (own T0, pinned); obsidian: the vault export, rebuilt every night
KEEP="agents3.db inbox.db price_alerts.json liq.db market.db flow.db paper.db ghcoin lab failalert exec debate \
shadow200 obsidian"

# paperbot-debate reads paper3.db (read-only) all the time: stopped while the files move, started again after
SERVICES="paperbot-live3 paperbot-dash paperbot-tgtrades paperbot-debate"
TIMERS="paperbot-agents.timer paperbot-daily3.timer paperbot-checkpoint.timer paperbot-rehearsal.timer \
paperbot-backup.timer paperbot-offsite.timer paperbot-labmonthly.timer paperbot-evening.timer \
paperbot-obsidian.timer paperbot-dscheck.timer"
JOBS="paperbot-agents.service paperbot-daily3.service paperbot-backup.service paperbot-checkpoint.service \
paperbot-labmonthly.service paperbot-offsite.service paperbot-rehearsal.service paperbot-evening.service \
paperbot-obsidian.service paperbot-dscheck.service"
# the agents' tick: started again in step 6 unless --agents-off (owners' D15)
AGENT_TIMER="paperbot-agents.timer"
# what the owners lose while the agents' tick is off (the same words as paperbot/launchcheck.py AGENTS_OFF_KO)
AGENTS_OFF_KO="에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음"
# installed by install.sh during the reset but not switched on (PAPERBOT_RESETTING=1): on after the checks
# (docs/server-setup-v4.md step 5). The reset stops and keeps off the two of them in TIMERS (step 6 disables them);
# the shadow test (never stopped) is left as it is.
AFTER_CHECK_TIMERS="paperbot-obsidian.timer paperbot-shadow200.timer paperbot-dscheck.timer"
# the DeepSeek check's bar cache (final public 5m klines, regenerable, about 60 MB): stays in $DATA/dscheck when the
# run's dscheck summaries are archived; never in the backup or the off-site copy (their lists name databases only)
DSCHECK_CACHE="bars5m.db"
# every process that writes (or reads, the executor) a file the restart moves or changes
WRITERS="$SERVICES $JOBS paperbot-executor"

# a unit's state as `systemctl is-active` prints it: active, activating (starting, a oneshot job while it runs, a
# service waiting to auto-restart), deactivating, reloading, failed, inactive, ... ("unknown" when it prints nothing)
state() { local s; s="$("$SYSTEMCTL" is-active "$1" 2>/dev/null || true)"; echo "${s:-unknown}"; }
# running, or about to run again
busy() { case "$(state "$1")" in active|activating|deactivating|reloading|refreshing) return 0 ;; *) return 1 ;; esac; }
enabled() { "$SYSTEMCTL" is-enabled --quiet "$1" 2>/dev/null; }
# installed on this server (stopping a unit that is not loaded fails)
loaded() { [ "$("$SYSTEMCTL" show -p LoadState --value "$1" 2>/dev/null || true)" = loaded ]; }
# what step 6 starts again: what ran or was meant to run (enabled; a crashed, failed unit that is enabled too)
restart_set() {
  local u out=""
  for u in $SERVICES $TIMERS; do
    if busy "$u" || enabled "$u"; then out="$out $u"; fi
  done
  echo "$out"
}
in_list() { local x; for x in $2; do [ "$x" = "$1" ] && return 0; done; return 1; }
# split a unit list into what step 6 starts (START_NOW) and what it keeps off and disables (HELD_BACK): the agents'
# tick with --agents-off, the after-check timers always
split_start() {
  local u
  START_NOW=""
  HELD_BACK=""
  for u in $1; do
    if { [ "$u" = "$AGENT_TIMER" ] && [ "$AGENTS_ON" != 1 ]; } || in_list "$u" "$AFTER_CHECK_TIMERS"; then
      HELD_BACK="$HELD_BACK $u"
    else
      START_NOW="$START_NOW $u"
    fi
  done
}
# one line per held-back unit (dry run and step 1)
held_lines() {
  local u
  for u in $HELD_BACK; do
    if [ "$u" = "$AGENT_TIMER" ]; then
      echo "[꺼 둘 것] $u (--agents-off: $AGENTS_OFF_KO. 다시 켜지 않고 자동 시작도 끔. 두 분 결정 D15)"
    else
      echo "[꺼 둘 것] $u (리셋 뒤 점검을 마치고 두 분이 켬: docs/server-setup-v4.md 5단계)"
    fi
  done
}
# what the agents' tick will be after step 6 (dry run)
agents_after() {
  if [ "$AGENTS_ON" != 1 ]; then echo "꺼짐(--agents-off) · $AGENTS_OFF_KO"
  elif in_list "$AGENT_TIMER" "$START_NOW"; then echo "다시 켬(지금처럼)"
  else echo "꺼져 있었으므로 꺼진 채 · $AGENTS_OFF_KO"; fi
}
# the off-site copy is set up only when its timer is enabled (docs/server-setup-v3.md 4-3)
offsite_on() { "$SYSTEMCTL" is-enabled --quiet paperbot-offsite.timer 2>/dev/null; }

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
        # not `find | grep -q`: find over /proc nearly always exits 1 (a PID vanishes mid-walk), and pipefail would
        # then hide a match
        if [ -n "$(find /proc/[0-9]*/fd -lname "$DATA/$f$s" 2>/dev/null || true)" ]; then found="$found $f$s"; fi
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
    if busy "$u"; then run_now="$run_now $u"; fi
  done
  echo "[멈출 것]${run_now:- (지금 도는 것 없음)} (설치된 서비스·타이머는 상태와 상관없이 모두 멈춤)"
  again="$(restart_set)"
  split_start "$again"
  echo "[끝나고 다시 켤 것]${START_NOW:- (없음)}"
  held_lines
  echo "[에이전트 회의] $(agents_after)"
  echo "[계속 돌 것] paperbot-shadow200.timer(딥시크 200 그림자 시험: 자기 DB, 실행 파일을 읽지 않음)"
  if busy paperbot-executor; then
    echo "!! paperbot-executor(주문 실행기)가 돌고 있습니다: paper3.db를 읽으므로 --yes 전에 직접 멈춰야 합니다 (sudo systemctl stop paperbot-executor)"
  fi
  echo "[옮기기 전에 새 백업] paperbot-backup.service를 한 번 돌려 $BACKUPS/<UTC 날짜>/에 멈춘 실행의 복사본을 만들고 확인합니다"
  echo "  (실패하면 아무것도 옮기지 않고 멈춤). 그 폴더를 $BACKUPS/<UTC 날짜>-before-reset-<UTC 시각>/<UTC 날짜>/로 한 벌 더 복사해 둡니다"
  echo "  (같은 날짜 폴더는 08:40 KST 밤 백업 때 새 실행으로 바뀜)"
  if offsite_on; then
    echo "  서버 밖 복사: paperbot-offsite.timer가 켜져 있어 paperbot-offsite.service도 한 번 돌립니다(몇 분~최대 1시간, 실패하면 경고만 하고 계속)"
  else
    echo "  서버 밖 복사: paperbot-offsite.timer가 켜져 있지 않아 건너뜁니다"
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
  if ! helper guard --lib "$DATA"; then
    echo "   (그래서 --yes는 거절됩니다)"
  fi
  echo "[코드] $REPO_DIR -> deploy/install.sh ($(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo '?'), $(git -C "$REPO_DIR" describe --tags --always 2>/dev/null || echo '?'))"
  if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "!! 저장소에 커밋 안 된 수정이 있어 install.sh가 멈춥니다"
  fi
  echo "실제로 하려면: sudo bash deploy/paperbot-reset.sh --yes   (개발자가 에이전트를 꺼 두라고 했을 때만 --yes --agents-off)"
  exit 0
fi

# ------------------------------------------------------------------------------------------------- the reset
if [ "$in_window" -eq 1 ]; then
  echo "08:30-09:40 KST is the nightly check / checkpoint window: run this after 09:40"; exit 1
fi
if busy paperbot-executor; then
  echo "paperbot-executor (the order executor) is running and reads paper3.db. Stop it yourself first:"
  echo "  sudo systemctl stop paperbot-executor"
  echo "then run this again, and start it after the reset (its paper account must be one of the 36 strategies on 15m/30m/1h/4h)."
  exit 1
fi
[ -x "$PY" ] || { echo "$PY not found: install the server first (deploy/install.sh)"; exit 1; }
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
  echo "the repository has uncommitted changes (install.sh would stop): deploy only committed code"; exit 1
fi
echo "== 0. check (nothing changed yet)"
if [ "$AGAIN" = --force-again ]; then
  echo "--force-again: 이미 재시작했는지 확인하지 않습니다"
elif ! helper guard --lib "$DATA"; then
  echo "아무것도 멈추거나 옮기지 않았습니다."
  exit 1
fi
helper plan --lib "$DATA" --etc "$ETC"

PHASE=none
RUNNING=""
OFFSITE_WARN=0
ARCH=""
MOVED=""
on_fail() {
  local line="$1"
  trap - ERR
  echo
  echo "!! 실패 (줄 $line, 단계 $PHASE)"
  case "$PHASE" in
    stopping|stopped|backup|installing|installed)
      echo "이전 실행은 그대로입니다(아무 파일도 옮기지 않음)."
      if [ "$PHASE" = backup ]; then
        echo "(새 백업이 끝나지 않아 멈췄습니다. 원인 보기: sudo journalctl -u paperbot-backup -n 50 --no-pager)"
      fi
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
      echo "새 실행 준비는 끝났습니다. 다시 켜기: sudo systemctl start$START_NOW"
      ;;
    *) echo "아무것도 바뀌지 않았습니다." ;;
  esac
  exit 1
}
trap 'on_fail $LINENO' ERR

echo "== 1. stop"
PHASE=stopping
STOP=""
for u in $SERVICES $TIMERS; do
  echo "  $u: $(state "$u")$(if enabled "$u"; then echo ", enabled"; fi)"
  if loaded "$u"; then STOP="$STOP $u"; fi
done
RUNNING="$(restart_set)"
split_start "$RUNNING"
# shellcheck disable=SC2086  # unit names, split on purpose
if [ -n "$STOP" ]; then "$SYSTEMCTL" stop $STOP; fi
if busy paperbot-agents.service; then "$SYSTEMCTL" stop paperbot-agents.service; fi
n=0
while jobs_now="$(for j in $JOBS; do if busy "$j"; then echo "$j"; fi; done)"; [ -n "$jobs_now" ]; do
  n=$((n+1)); [ "$n" -ge 120 ] && { echo "still running after 120 checks: $jobs_now"; false; }
  echo "waiting for a scheduled job to finish: $jobs_now ($n/120)"; sleep "$POLL_S"
done
PHASE=stopped
echo "stopped:${STOP:- (nothing installed)}"
echo "to start again in step 6:${START_NOW:- (nothing was running)}"
if [ -n "$HELD_BACK" ]; then echo "kept off after the reset:$HELD_BACK"; held_lines; fi
for u in $WRITERS; do
  if busy "$u"; then echo "$u is still $(state "$u")"; false; fi
done
open_now="$(holders)"
if [ -n "$open_now" ]; then
  echo "still open by a process:$open_now"
  command -v fuser >/dev/null 2>&1 && for f in $open_now; do fuser -v "$DATA/$f" || true; done
  false
fi
echo "no process has the run files open"

echo "== 2. fresh backup of the stopped run (before anything moves)"
PHASE=backup
t0=$(date +%s)
if ! "$SYSTEMCTL" start paperbot-backup.service; then
  echo "!! 새 백업(paperbot-backup.service)이 실패했습니다. 아무 파일도 옮기지 않고 여기서 멈춥니다."
  false
fi
res="$("$SYSTEMCTL" show -p Result --value paperbot-backup.service 2>/dev/null || true)"
if [ "$res" != success ]; then
  echo "!! 새 백업(paperbot-backup.service)의 결과가 '${res:-알 수 없음}'입니다(success가 아님). 아무 파일도 옮기지 않고 멈춥니다."
  false
fi
day="$BACKUPS/$(date -u +%Y%m%d)"
for f in $ARCHIVE_DBS; do
  [ -e "$DATA/$f" ] || continue
  if [ ! -f "$day/$f" ] || [ "$(stat -c %Y "$day/$f")" -lt "$t0" ]; then
    echo "!! 새 백업에 $f 복사본이 없습니다($day/$f 가 없거나 이번에 만든 것이 아님). 아무 파일도 옮기지 않고 멈춥니다."
    false
  fi
done
echo "backup ok: $day"
# the 08:40 KST nightly backup rewrites today's folder with the NEW run: keep this copy apart (offsite.py sends a
# folder named by its date: --from <kept folder> --date <date>)
DAYNAME="$(basename "$day")"
KEEP_BK="$BACKUPS/$DAYNAME-before-reset-$(date -u +%H%M%SZ)"
n=0
while [ -e "$KEEP_BK" ]; do n=$((n+1)); KEEP_BK="$BACKUPS/$DAYNAME-before-reset-$(date -u +%H%M%SZ)-$n"; done
install -d -m 750 "$KEEP_BK"
cp -a "$day" "$KEEP_BK/$DAYNAME"
chown -R "${RUN_USER:-root}:${RUN_USER:-root}" "$KEEP_BK"
for f in $ARCHIVE_DBS; do
  if [ -e "$DATA/$f" ] && ! cmp -s "$day/$f" "$KEEP_BK/$DAYNAME/$f"; then
    echo "!! 옮기기 전 백업을 $KEEP_BK 에 복사하지 못했습니다($f). 아무 파일도 옮기지 않고 멈춥니다."
    false
  fi
done
echo "pre-reset copy kept: $KEEP_BK/$DAYNAME"
RESEND="sudo systemd-run --wait --pipe --collect -p User=paperbot -p Group=paperbot -p WorkingDirectory=/opt/crypto-bot-research -p EnvironmentFile=/etc/paperbot/live.env /opt/paperbot/venv/bin/python -m paperbot.offsite send --from $KEEP_BK --date $DAYNAME"
if offsite_on; then
  echo "off-site copy (paperbot-offsite.service, up to an hour)"
  if "$SYSTEMCTL" start paperbot-offsite.service; then
    echo "off-site copy: sent"
  else
    echo "!! 경고: 서버 밖 복사(paperbot-offsite.service)가 실패했습니다. 서버 안 새 백업($day)은 만들어졌으므로 계속합니다."
    echo "   재시작이 끝난 뒤 원인 보기: sudo journalctl -u paperbot-offsite -n 50 --no-pager"
    echo "   다시 보내기(옮기기 전 복사본 $KEEP_BK/$DAYNAME; 같은 날짜 폴더 $day는 08:40 KST 밤 백업 때 새 실행으로 바뀌므로"
    echo "   sudo systemctl start paperbot-offsite.service는 그 전에만 같은 것을 보냄):"
    echo "     $RESEND"
    OFFSITE_WARN=1
  fi
else
  echo "off-site copy skipped (paperbot-offsite.timer is not enabled)"
fi

echo "== 3. install the pulled code"
PHASE=installing
PAPERBOT_RESETTING=1 bash "$INSTALL"
PHASE=installed
echo "(install.sh의 마지막 안내는 처음 설치용입니다. 이 스크립트가 이어서 진행합니다)"

echo "== 4. archive the old run (moved, not deleted)"
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
install -d -o "${RUN_USER:-root}" -g "${RUN_USER:-root}" -m 750 "$DATA/rehearsal" "$DATA/dscheck"
# the DeepSeek check's bar cache is not the run's: it goes back from the archived folder (final klines, regenerable)
for g in "$ARCH/dscheck/$DSCHECK_CACHE" "$ARCH/dscheck/$DSCHECK_CACHE-journal" "$ARCH/dscheck/$DSCHECK_CACHE-wal" \
         "$ARCH/dscheck/$DSCHECK_CACHE-shm"; do
  if [ -e "$g" ]; then mv "$g" "$DATA/dscheck/"; fi
done
PHASE=moved
echo "moved to $ARCH:${MOVED:- (nothing)}"

echo "== 5. agents' memory kept; run-bound cursors reset (backup first)"
helper apply --lib "$DATA" --archive "$ARCH"
PHASE=reset

echo "== 6. start the new run"
PHASE=starting
if [ -n "$HELD_BACK" ]; then
  # shellcheck disable=SC2086  # unit names, split on purpose
  "$SYSTEMCTL" disable $HELD_BACK
  echo "kept off (and not started at boot):$HELD_BACK"
fi
if [ -n "$START_NOW" ]; then
  # shellcheck disable=SC2086  # unit names, split on purpose
  "$SYSTEMCTL" start $START_NOW
  echo "started:$START_NOW"
else
  echo "nothing was running before; start the bot as in docs/server-setup-v4.md"
fi
trap - ERR
PHASE=finished

echo
echo "================ 요약 ================"
echo "보관(옮김, 지우지 않음): $ARCH"
echo " ${MOVED:- (없음)}"
echo "그대로 둠: agents3.db(시험 장부·메모·채점·회의 기록·제안 기록), inbox.db(두 분의 글·승인 기록·가격 알림),"
echo "  price_alerts.json, liq.db·flow.db·market.db·ghcoin(시장 기록), lab, failalert, exec, debate(토론방 기록),"
echo "  shadow200(딥시크 200 그림자 시험, 계속 돎), obsidian, /etc/paperbot, 백업"
echo "  agents3.db·inbox.db의 바꾸기 전 사본: $ARCH/agents3-before-reset.db, $ARCH/inbox-before-reset.db"
echo "초기화: 이전 paper3.db를 가리키던 에이전트 커서(위 5단계), 이전 실행의 열린 제안(닫음)"
echo "옮기기 전 새 백업: $KEEP_BK/$DAYNAME (따로 보관, 14일 뒤 다른 백업처럼 지워짐; $day는 08:40 KST 밤 백업 때 새 실행으로 바뀜)"
if [ "$OFFSITE_WARN" = 1 ]; then
  echo "!! 서버 밖 복사는 실패했습니다(위 경고). 옮기기 전 복사본을 다시 보내기:"
  echo "   $RESEND"
fi
if in_list "$AGENT_TIMER" "$HELD_BACK" || ! busy "$AGENT_TIMER"; then
  echo "!! $AGENTS_OFF_KO (paperbot-agents.timer 꺼짐$(if [ "$AGENTS_ON" != 1 ]; then echo ', --agents-off'; fi))."
  echo "   개발자가 '에이전트 v4 준비 끝'이라고 하면: sudo systemctl enable --now $AGENT_TIMER"
else
  echo "에이전트 회의(paperbot-agents.timer): 켜짐"
fi
echo "리셋 뒤 점검을 마치고 켤 타이머(지금 상태):"
for u in $AFTER_CHECK_TIMERS; do
  loaded "$u" || { echo "  $u: 설치 안 됨"; continue; }
  echo "  $u: 자동 시작 $("$SYSTEMCTL" is-enabled "$u" 2>/dev/null || true), 지금 $(state "$u")"
done
if busy paperbot-live3; then
  if ! helper start --paper-db "$DATA/paper3.db" --wait "$WAIT_S"; then
    echo "몇 분 뒤 시작 시각과 첫 판정일 확인:"
    echo "  cd /opt/crypto-bot-research && sudo -u paperbot $PY -m paperbot.resetrun start --paper-db $DATA/paper3.db"
  fi
  echo "5분 뒤 점검: cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after"
  echo "점검에 [고칠 것]이 없으면 켜기: sudo systemctl enable --now $AFTER_CHECK_TIMERS"
else
  echo "paperbot-live3 is not running: sudo journalctl -u paperbot-live3 -n 50 --no-pager"
fi
