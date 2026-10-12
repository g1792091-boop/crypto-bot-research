#!/usr/bin/env bash
# 1번 트랙 2차(커스텀값)를 빌린 계산 서버에서 돌립니다 (research/hunt_r2/SERVER_R2_KO.md, PREREG_HUNT_R2.md 11-12).
# 바이낸스 공개 가격 자료만 씁니다: 거래소 키·AI 키 없음. 규칙봇·데모봇·후보 리그, 1차(/root/hunt)·2번 트랙(/root/hiwr)
# 서버와 관계없음.
#
#   HUNT_R2_GO=<커밋> bash bootstrap_r2.sh   설치 → 자체 점검 → 고정 확인 → 자료 받기 → 자료 확인 → 고르기 → 고른 것
#                                            고정 확인 → 시험 전 표 → 시험(판정) → 참고 분석 → 결과 묶기 (tmux 안에서).
#                                            코드가 검토를 마친 커밋(HUNT_R2_GO)이 아니면 멈춥니다. 아직 커밋이 없으면
#                                            (고정 전) wait_go_r2.sh 로 넘어가 고정된 커밋을 기다립니다.
#   bash bootstrap_r2.sh status              지금 단계와 남은 시간(어림)
#   bash bootstrap_r2.sh push                결과를 GitHub(브랜치 hunt-r2-results)로 보냄 (토큰은 한 번만 물음)
#   bash bootstrap_r2.sh update <커밋>       개발자가 고친 커밋으로 바꿈 (계산 시작 전에만: 6/11 전)
#   bash bootstrap_r2.sh idle                돌고 있으면 "이미 돌고 있습니다"로 끝남 (다시 시작 줄의 앞부분)
#
# 모든 단계는 끝난 것을 건너뜁니다: 멈추거나 재부팅된 뒤 같은 줄이 이어서 합니다(고르기·시험의 작업 조각, 참고 분석의
# 끝난 모듈은 다시 계산하지 않음). 첫 실행의 설정은 $BASE/settings.env 에 남습니다. 딥시크 돈 숫자(D11)와 사건 저장소는
# 저장소 밖 $BASE/private 에만 있고 results.tgz 에는 들어가지 않습니다. 장부(PREREG 8)에 쓰는 1차·2번 트랙의 비공개 p 파일은
# 두 분이 PC에서 /root 로 보낸 *.tgz 에서 필요한 두 파일만 꺼냅니다(아무도 열어 보지 않음; 코드는 sha256이 맞을 때만 p 칸만 읽음).
#
# Rehearsal (no install, no download, no real push, no git change in the real repository): every stand-in comes from an
# env file read only with --dry-run:
#   HUNT_R2_DRYENV=<file> bash bootstrap_r2.sh --dry-run [run|status|idle|update <commit>|push]
# The file sets HUNT_R2_BASE, HUNT_R2_REPO (scratch) and any of: HUNT_R2_PY, HUNT_R2_CMD (the hunt_r2 command line),
# HUNT_R2_DATA_CMD (data_hunt), HUNT_R2_DATA, HUNT_R2_SELFCHECK_TESTS, HUNT_R2_TMUX (e.g. "tmux -L r2reh"),
# HUNT_R2_RETRY_SLEEP, HUNT_R2_READS_HOURS, HUNT_R2_INBOX, HUNT_R2_GO, HUNT_R2_DRY_WAIT (no go commit: hand over to
# wait_go_r2.sh as a real run does), HUNT_R2_PUSH_REHEARSAL (push to the scratch clone's origin).
set -uo pipefail

MODE=run
DRYRUN=${DRYRUN:-0}
ARG=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRYRUN=1 ;;
    run|status|push|update|idle) MODE=$a ;;
    *) if [ "$MODE" = update ] && [ -z "$ARG" ]; then ARG=$a
       else echo "사용법: bash bootstrap_r2.sh [run|status|push|update <커밋>|idle] [--dry-run]"; exit 2; fi ;;
  esac
done
if [ "$DRYRUN" = 1 ] && [ -n "${HUNT_R2_DRYENV:-}" ]; then
  # shellcheck source=/dev/null
  . "$HUNT_R2_DRYENV" || { echo "연습 설정 파일을 읽지 못했습니다: $HUNT_R2_DRYENV"; exit 2; }
fi

BASE=${HUNT_R2_BASE:-/root/hunt_r2}
case "$BASE" in
  /root/hunt|/root/hunt/*|/root/hiwr|/root/hiwr/*) echo "2차는 1차·2번 트랙 폴더를 쓰지 않습니다: HUNT_R2_BASE=$BASE"; exit 2 ;;
esac
if [ "$DRYRUN" != 1 ] && { [ -d /root/hunt ] || [ -d /root/hiwr ]; }; then
  echo "이 서버에는 1차(/root/hunt) 또는 2번 트랙(/root/hiwr) 폴더가 있습니다. 2차는 그 서버를 Destroy한 뒤 새 서버에서 돌립니다."
  echo "이 화면을 개발자에게 보내 주세요."
  exit 1
fi
mkdir -p "$BASE"
# Settings of the first run are kept, so a restart (which passes no environment) runs with the same choices.
SETTINGS=$BASE/settings.env
PERSIST="HUNT_R2_GO HUNT_R2_WORKERS HUNT_R2_PROCS"
GIVEN=""
for v in $PERSIST; do
  if [ -z "${!v:-}" ]; then
    s=$(sed -n "s/^$v=//p" "$SETTINGS" 2>/dev/null | tail -1)
    [ -n "$s" ] && printf -v "$v" '%s' "$s"
  fi
  if [ -n "${!v:-}" ]; then
    [[ ${!v} =~ ^[A-Za-z0-9._-]+$ ]] || { echo "설정 값이 이상합니다: $v=${!v}"; exit 2; }
    GIVEN="$GIVEN $v"
  fi
done
save_settings() {
  local v
  { for v in $GIVEN; do echo "$v=${!v}"; done; } > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
}

REPO=${HUNT_R2_REPO:-$BASE/crypto-bot-research}
DATA=${HUNT_R2_DATA:-$BASE/data5m}
PRIV=$BASE/private                    # event store, resumable parts, private JSON (D11); never in results.tgz
LPUB=$BASE/ledger_public              # other studies' public outputs under their repository paths (PREREG 8)
LPRIV=$BASE/ledger_private            # the two private p files taken out of the owners' *.tgz (PREREG 8)
INBOX=${HUNT_R2_INBOX:-/root}         # where the owners' scp line puts those *.tgz
VENV=$BASE/venv
LOG=$BASE/run.log
GO=${HUNT_R2_GO:-}
WORKERS=${HUNT_R2_WORKERS:-8}         # download threads
RSLEEP=${HUNT_R2_RETRY_SLEEP:-30}
READS_HOURS=12                        # PREREG 9.1: the reads stop at 12 hours wall
[ "$DRYRUN" = 1 ] && READS_HOURS=${HUNT_R2_READS_HOURS:-12}
PIN_REL=research/hunt_r2/PREREG_HUNT_R2.sha256
OUT=research/hunt_r2/out
PICKS_REL=$OUT/picks.json
PRETEST_REL=$OUT/pretest_reads.json
TEST_REL=$OUT/test.json
REF=research/hunt/data_manifest.json      # the hunt's pinned data identity (H 2), in round 2's pin (PREREG 2)
REF_ALL=research/hunt/data_ref_5m.json    # every 5m key incl. mark price (a check only: round 2 reads REF's arrays)
R1_BRANCH=${HUNT_R2_R1_BRANCH:-hunt-results}
T2_BRANCH=${HUNT_R2_T2_BRANCH:-hiwr-results}
FG_BRANCH=${HUNT_R2_FG_BRANCH:-fullgrid-results-20261010-1602}
if [ "$DRYRUN" = 1 ]; then PY=${HUNT_R2_PY:-python3}; else PY=${HUNT_R2_PY:-$VENV/bin/python}; fi
if [ -n "${HUNT_R2_CMD:-}" ]; then read -r -a R2 <<<"$HUNT_R2_CMD"; else R2=("$PY" -m research.hunt_r2.hunt_r2); fi
if [ -n "${HUNT_R2_DATA_CMD:-}" ]; then read -r -a DH <<<"$HUNT_R2_DATA_CMD"; else DH=("$PY" -m research.hunt.data_hunt); fi
NCPU=$(env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc)    # nproc obeys OMP_NUM_THREADS, set to 1 below
SELF=$REPO/research/hunt_r2/bootstrap_r2.sh
NST=11
TM=${HUNT_R2_TMUX:-tmux}
SES=hunt-r2
if [ "$DRYRUN" = 1 ]; then RUNCMD="HUNT_R2_DRYENV=${HUNT_R2_DRYENV:-} bash $SELF --dry-run"; else RUNCMD="bash $SELF"; fi
RESTART="$RUNCMD idle && { $TM respawn-pane -k -t $SES \"$RUNCMD; bash\" 2>/dev/null || $TM new -d -s $SES \"$RUNCMD; bash\"; [ -n \"\$TMUX\" ] || $TM attach -t $SES; }"

say() { echo "[$(date -u '+%m-%d %H:%M UTC')] $*" | tee -a "$LOG"; }
sub() { say "  · $*"; }
warn() {                     # something skipped that does not stop the run (listed again at the end)
  say "  · 참고: $*"
  grep -qxF "$*" "$BASE/WARNINGS" 2>/dev/null || echo "$*" >> "$BASE/WARNINGS"
}
computed() {                 # anything computed on this server: stage 6 started, or select ran here
  grep -qE '^([6-9]|1[01])\|' "$BASE/STAGES" 2>/dev/null && return 0
  [ -f "$BASE/SELECT_RAN" ]
}
keep_server() { say "계산한 것이 이 서버에 있으니, 개발자 답이 올 때까지 서버를 지우지(Destroy) 마세요."; }
die() {                      # a stop: send the screen
  say "멈춤: $*"
  say "이 화면을 그대로 복사해 개발자에게 보내 주세요."
  computed && keep_server
  exit 1
}
die_fix() {                  # a stop only the developer can fix (code, pins, the pinned data)
  say "멈춤: $*"
  say "이 화면을 그대로 복사해 개발자에게 보내 주세요."
  if computed; then keep_server; exit 1; fi
  say "아직 계산 전이라, 바로 못 고치면 서버를 Destroy해도 잃는 것이 없습니다."
  say "개발자가 고쳤다고 하면: 개발자가 준 줄(bash $SELF update <커밋>)을 붙여 넣고, 그다음 아래 한 줄 전체로 이어서 합니다:"
  echo "$RESTART" | tee -a "$LOG"
  exit 1
}
die_retry() {                # a stop that a later restart can get past (network, apt lock, workers that kept dying)
  say "멈춤: $*"
  say "몇 분 뒤 아래 한 줄 전체를 붙여 넣으면 이어서 합니다 (끝난 것은 건너뜁니다):"
  echo "$RESTART" | tee -a "$LOG"
  say "같은 멈춤이 두 번 나오면 이 화면을 그대로 복사해 개발자에게 보내 주세요."
  computed && keep_server
  exit 1
}

# ------------------------------------------------------------------ time estimates (see SERVER_R2_KO "걸리는 시간")
# CPU-minutes measured 2026-10-12 (research/hunt_r2/SERVER_R2_KO.md, basis there) and spread over EFF = 70% of the
# vCPUs (18-27 effective cores of 32 if they are SMT threads), rounded up. The select step prints "[<part>] done/n done,
# <s>s" every minute; status turns the running part's own pace into its remaining time and adds the parts after it.
SEL_PARTS="event store (name, timeframe, coin)|(a′) event histograms|real Stage 0 + A|null (b′) units|null (a′) units|box store|box checks"
SEL_CPU_MIN="1500 10 90 4500 4500 30 30"     # per part, the conservative end (null CPU at 0.33 s per engine run)
EFF=$(( NCPU * 7 / 10 )); [ "$EFF" -lt 1 ] && EFF=1
cpu_wall() { echo $(( ($1 + EFF - 1) / EFF )); }          # CPU-minutes -> wall minutes on this server
picks_b1() { cat "$BASE/PICKS_B1" 2>/dev/null; }
sel_plan_from() {            # wall minutes of select parts i.. (0-based) plus the serial parts (load, shifts, picks)
  local i=$1 k=0 s=0 c
  for c in $SEL_CPU_MIN; do
    [ "$k" -ge "$i" ] && s=$(( s + $(cpu_wall "$c") ))
    k=$(( k + 1 ))
  done
  echo $(( s + 10 ))
}
est_min() {
  case $1 in
    1) echo 6 ;; 2) echo 8 ;; 3) echo 2 ;; 4) echo 20 ;; 5) echo 6 ;;
    6) sel_plan_from 0 ;;
    7) echo 1 ;;
    8) echo $(( 15 + $(cpu_wall 240) )) ;;                       # pretest: CSCV / shifts in one process + 2-4 CPU-h
    9) local b; b=$(picks_b1); [ "$b" = 0 ] && { echo 2; return; }
       echo $(( 5 + ${b:-10} * $(cpu_wall 60) )) ;;              # per tested pick about 3,150 runs (<= 60 CPU-min)
    10) local b; b=$(picks_b1); [ "$b" = 0 ] && { echo 0; return; }
        local m=$(( ( ${b:-10} + 2 ) * $(cpu_wall 1300) )) cap=$(( READS_HOURS * 60 ))
        [ "$m" -gt "$cap" ] && m=$cap; echo "$m" ;;               # rows x about 21 CPU-h, capped at the wall
    11) echo 4 ;;
    *) echo 0 ;;
  esac
}
left_from() { local s=0 k; for k in $(seq "$1" "$NST"); do s=$(( s + $(est_min "$k") )); done; echo "$s"; }
hm() { local m=$1; if [ "$m" -ge 120 ]; then echo "약 $(( m / 60 ))시간 $(( m % 60 ))분"; else echo "약 ${m}분"; fi; }
last_prog() {                # the last "[part] done/n done, Xs" line the current stage wrote to the log
  local pos; pos=$(cat "$BASE/STAGE_POS" 2>/dev/null); pos=${pos:-0}
  tail -c +$(( pos + 1 )) "$LOG" 2>/dev/null | grep -aoE '^\[[^]]+\] [0-9]+/[0-9]+ done, [0-9]+s' | tail -1
}
sel_left() {                 # select: the running part's remaining time at its own pace + the planned later parts
  local p label dn n sec i=0 k part left
  p=$(last_prog)
  [ -n "$p" ] || { est_min 6; return; }
  label=$(sed -E 's/^\[([^]]+)\].*/\1/' <<<"$p")
  dn=$(sed -E 's/^\[[^]]+\] ([0-9]+)\/.*/\1/' <<<"$p")
  n=$(sed -E 's/^\[[^]]+\] [0-9]+\/([0-9]+) .*/\1/' <<<"$p")
  sec=$(sed -E 's/.* ([0-9]+)s$/\1/' <<<"$p")
  k=-1
  while IFS= read -r part; do
    [ "$part" = "$label" ] && k=$i
    i=$(( i + 1 ))
  done < <(tr '|' '\n' <<<"$SEL_PARTS")
  [ "$k" -lt 0 ] && { est_min 6; return; }
  if [ "$dn" -ge "$n" ]; then left=0
  elif [ "$dn" -gt 0 ]; then left=$(( sec * (n - dn) / dn / 60 + 1 ))
  else left=$(cpu_wall "$(cut -d' ' -f$(( k + 1 )) <<<"$SEL_CPU_MIN")"); fi
  echo $(( left + $(sel_plan_from $(( k + 1 ))) ))
}
ko_part() {
  case "$1" in
    "event store (name, timeframe, coin)") echo "사건 저장(신호 계산)" ;;
    "(a′) event histograms") echo "가짜 탐색 (a′) 준비" ;;
    "real Stage 0 + A") echo "실제 탐색 (기준 자리 + 거친 격자)" ;;
    "null (b′) units") echo "가짜 탐색 (b′) 동전 200번" ;;
    "null (a′) units") echo "가짜 탐색 (a′) 시간 밀기 200번" ;;
    "box store"|"box checks") echo "상자 확인" ;;
    *) echo "$1" ;;
  esac
}

stage() {                    # stage <n> <name>
  local now; now=$(date +%s)
  echo "$1|$2|$now" > "$BASE/STAGE"
  echo "$1|$2|$now" >> "$BASE/STAGES"
  { wc -c < "$LOG" || echo 0; } 2>/dev/null | tr -dc '0-9' > "$BASE/STAGE_POS"
  say "$1/$NST $2  (남은 시간 $(hm "$(left_from "$1")"), 어림)"
}

waiting() {                  # wait_go_r2.sh polling for the go commit (WAITING holds its pid)
  local p; p=$(cat "$BASE/WAITING" 2>/dev/null)
  [ -n "$p" ] && [ "$p" != "$$" ] && kill -0 "$p" 2>/dev/null && grep -qa "wait_go_r2.sh" "/proc/$p/cmdline" 2>/dev/null
}
running() {                  # the run's own process (RUNNING holds its pid), the waiter, or a step the run left behind
  local p; p=$(cat "$BASE/RUNNING" 2>/dev/null)
  if [ -n "$p" ] && [ "$p" != "$$" ] && kill -0 "$p" 2>/dev/null && grep -qa "hunt_r2/bootstrap_r2.sh" "/proc/$p/cmdline" 2>/dev/null; then
    return 0
  fi
  waiting && return 0
  [ "$DRYRUN" = 1 ] && return 1
  pgrep -f "[r]esearch\.hunt_r2\.hunt_r2|[r]esearch\.hunt\.data_hunt|[t]ests/test_(hunt|data_hunt|altpump)" >/dev/null
}
WAIT_MSG="고정된 커밋을 기다리는 중입니다 (2분마다 확인). 고정되면 알아서 시작하니 아무것도 붙여 넣지 않아도 됩니다."

inbox_line() {               # what the owners' scp line has put in the inbox (names and sizes only; nothing opened)
  local n=0 f
  for f in "$INBOX"/*.tgz "$INBOX"/*.tar.gz; do [ -f "$f" ] && n=$(( n + 1 )); done
  if [ "$n" = 0 ]; then echo "장부용 비공개 파일(.tgz): 아직 없음 (SERVER_R2_KO 2-C의 줄, 시험 전까지)"
  else echo "장부용 비공개 파일(.tgz) ${n}개 받음 (시험 전에 확인합니다)"; fi
}

status() {
  if [ -f "$BASE/DONE" ]; then
    echo "끝났습니다. 결과: $BASE/results.tgz  (보내기: bash $SELF push)"
    [ -s "$BASE/verdict_line.txt" ] && echo "  $(cat "$BASE/verdict_line.txt")"
    if [ -s "$BASE/WARNINGS" ]; then echo "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS"; fi
    return
  fi
  if waiting; then
    echo "$WAIT_MSG"
    echo "  $(inbox_line)"
    return
  fi
  if ! running; then
    if [ -z "$GO" ] && [ ! -f "$BASE/STAGE" ]; then
      echo "아직 고정 전인데 기다리기가 멈춰 있습니다 (재부팅 등). 아래 한 줄 전체를 붙여 넣으면 다시 기다립니다:"
      echo "$RESTART"
      return
    fi
    echo "지금 돌고 있지 않습니다. 마지막 기록:"
    grep -aE "멈춤|\] ([0-9]|1[01])/$NST " "$LOG" 2>/dev/null | tail -3
    echo "이어서 하려면 아래 한 줄 전체를 붙여 넣으세요:"
    echo "$RESTART"
    return
  fi
  local n=0 name="설치 중" t0 el left last p
  t0=$(date +%s)
  [ -f "$BASE/STAGE" ] && IFS='|' read -r n name t0 < "$BASE/STAGE"
  el=$(( ($(date +%s) - t0) / 60 ))
  if [ "$n" = 6 ]; then left=$(sel_left)
  else left=$(( $(est_min "$n") - el )); fi
  [ "$left" -lt 1 ] && left=1
  [ "$n" -lt "$NST" ] && left=$(( left + $(left_from $(( n + 1 ))) ))
  echo "진행 중: $n/$NST $name (이 단계 ${el}분째)"
  echo "  남은 시간: $(hm "$left") (어림, CPU ${NCPU}개 기준; 길게 잡은 값)"
  last=$(grep -aF "  · " "$LOG" 2>/dev/null | tail -1)
  [ -n "$last" ] && echo "  지금: ${last#*· }"
  case "$n" in
    4) last=$(grep -aoE "\[data [0-9]+/[0-9]+\].*" "$LOG" 2>/dev/null | tail -1)
       [ -n "$last" ] && echo "  자료: ${last:0:120}" ;;
    6|8|9|10) p=$(last_prog)
       if [ -n "$p" ]; then
         echo "  작업: $(ko_part "$(sed -E 's/^\[([^]]+)\].*/\1/' <<<"$p")") $(sed -E 's/^\[[^]]+\] ([0-9]+\/[0-9]+) done.*/\1/' <<<"$p") 끝"
       fi ;;
  esac
  case "$n" in
    6) echo "  6/$NST 고르기가 가장 깁니다(5~15시간). 무거운 작업이 먼저 돌아 처음 몇 분의 남은 시간은 길게 나옵니다."
       echo "  남은 시간이 그대로여도 정상이니 다시 시작하지 마세요."
       echo "  $(inbox_line)" ;;
    8|9) echo "  $(inbox_line)" ;;
    10) echo "  10/$NST 참고 분석은 최대 ${READS_HOURS}시간입니다. 판정은 이미 끝났고(test.json), 정상이니 다시 시작하지 마세요." ;;
  esac
}

push() {
  [ "$DRYRUN" = 1 ] && [ -z "${HUNT_R2_PUSH_REHEARSAL:-}" ] && { echo "연습 모드에서는 보내지 않습니다."; return 1; }
  [ -f "$BASE/results.tgz" ] || die "결과 파일이 아직 없습니다."
  cd "$REPO" || exit 1
  git config user.email "hunt-r2@localhost"; git config user.name "hunt-r2 server"
  git config credential.helper store
  # commit in a separate worktree, so the run's checkout stays on the go commit (a later restart checks it)
  local br=hunt-r2-results wt=$BASE/push_wt rc br2
  if [ ! -d "$wt" ]; then
    git worktree prune
    if git rev-parse -q --verify "refs/heads/$br" >/dev/null; then
      git worktree add "$wt" "$br" >>"$LOG" 2>&1 || die "올리기 준비 실패 (git worktree)"
    else
      git worktree add -b "$br" "$wt" HEAD >>"$LOG" 2>&1 || die "올리기 준비 실패 (git worktree)"
    fi
  fi
  cd "$wt" || exit 1
  rm -rf research/hunt_r2/results
  tar xzf "$BASE/results.tgz" -C research/hunt_r2 || die "결과 풀기 실패"            # -> research/hunt_r2/results/
  git add -f research/hunt_r2/results
  git commit -q -m "Hunt round 2 (hunt-r2 v1): select, pretest, test and reads results ($(hostname), $(date -u +%F))" \
    || say "새로 올릴 변경이 없습니다 (이미 커밋됨)"
  echo "GitHub 아이디와, 비밀번호 자리에 쓰기 토큰(Contents: Read and write)을 넣으세요. (올리기가 되면 다시 묻지 않습니다)"
  git push -u origin "$br" 2>&1 | tee "$BASE/push.out"; rc=${PIPESTATUS[0]}
  if [ "$rc" = 0 ]; then say "보냈습니다: 브랜치 $br"; return 0; fi
  if grep -qiE "rejected|non-fast-forward|fetch first" "$BASE/push.out"; then
    br2="hunt-r2-results-$(date -u +%Y%m%d-%H%M)"
    say "GitHub에 같은 이름의 브랜치($br)가 이미 있어 $br2 로 보냅니다"
    git push -u origin "HEAD:refs/heads/$br2" 2>&1 | tee "$BASE/push.out"; rc=${PIPESTATUS[0]}
    if [ "$rc" = 0 ]; then say "보냈습니다: 브랜치 $br2"; return 0; fi
  fi
  if grep -qiE "authentication failed|invalid username|could not read username|password authentication|permission to .* denied|error: 40[13]" "$BASE/push.out"; then
    die "올리기 실패: 토큰이 틀렸거나 권한이 없습니다. 토큰(저장소 crypto-bot-research, Contents: Read and write)을 확인하고 같은 push 줄을 다시 실행하세요 (아이디·토큰을 다시 묻습니다)."
  fi
  die "올리기 실패: 인터넷 문제일 수 있습니다. 잠시 뒤 같은 push 줄을 다시 실행하세요. 계속 안 되면 SERVER_R2_KO 4번의 (나) 파일로 받기를 쓰세요."
}

update() {                   # update <commit>: the developer's fix, only while nothing has been computed
  local want=$1
  [[ $want =~ ^[0-9a-f]{7,40}$ ]] || { echo "사용법: bash $SELF update <커밋 번호 (개발자가 준 것)>"; return 2; }
  [ -f "$BASE/DONE" ] && { echo "이미 끝났습니다. 바꿀 것 없습니다 (결과: $BASE/results.tgz, 보내기: bash $SELF push)"; return 1; }
  if waiting; then echo "$WAIT_MSG (코드는 고정된 커밋이 오면 그것으로 바뀝니다)"; return 1; fi
  if running; then echo "이미 돌고 있습니다. 다시 붙여 넣을 필요 없습니다. 진행 보기: bash $SELF status"; return 1; fi
  if computed; then
    echo "이미 계산을 시작해서(6/$NST 이후) 코드를 바꾸지 않습니다. 이 화면을 개발자에게 보내 주세요."; return 1
  fi
  if [ "$DRYRUN" = 1 ]; then
    echo "연습: git 내려받기·바꾸기는 건너뜀"
  else
    git -C "$REPO" fetch -q origin || { echo "코드 내려받기 실패 (인터넷). 잠시 뒤 같은 줄을 다시 붙여 넣으세요."; return 1; }
    git -C "$REPO" checkout -q "$want" || { echo "그 커밋으로 바꾸지 못했습니다: $want (이 화면을 개발자에게 보내 주세요)"; return 1; }
  fi
  HUNT_R2_GO=$want
  case " $GIVEN " in *" HUNT_R2_GO "*) ;; *) GIVEN="$GIVEN HUNT_R2_GO" ;; esac
  save_settings
  rm -f "$BASE/CHECKED"
  echo "코드를 ${want:0:10} 으로 바꿨습니다. (다시 시작 줄이 같이 있었다면 더 붙여 넣을 것 없음. 아니면 아래 한 줄:)"
  echo "$RESTART"
}

case "$MODE" in
  status) status; exit 0 ;;
  push) push; exit $? ;;
  update) update "$ARG"; exit $? ;;
  idle) waiting && { echo "$WAIT_MSG"; exit 1; }
        running && { echo "이미 돌고 있습니다. 다시 시작할 필요 없습니다. 진행 보기: bash $SELF status"; exit 1; }
        exit 0 ;;              # the printed restart line starts with this guard: a paste during a run changes nothing
esac

for k in 1 2 3 4 5; do running || break; sleep 2; done      # a restart: let the old run finish dying
waiting && { echo "$WAIT_MSG"; exit 1; }
running && { echo "이미 돌고 있습니다. 화면 보기: $TM attach -t $SES   (진행: bash $SELF status)"; exit 1; }
if [ -f "$BASE/DONE" ]; then
  echo "이미 끝났습니다: $BASE/results.tgz  (보내기: bash $SELF push; 처음부터 다시 묶으려면 rm $BASE/DONE)"
  exit 0
fi
# No go commit yet (the restart line after a reboot during the wait, or the waiter's hours ran out): wait again.
if [ -z "$GO" ] && { [ "$DRYRUN" != 1 ] || [ -n "${HUNT_R2_DRY_WAIT:-}" ]; }; then
  WAITER=$BASE/wait_go_r2.sh
  cp -f "$REPO/research/hunt_r2/wait_go_r2.sh" "$WAITER" 2>/dev/null || [ -f "$WAITER" ] \
    || { echo "기다리기 스크립트가 없습니다 ($REPO/research/hunt_r2/wait_go_r2.sh). 이 화면을 개발자에게 보내 주세요."; exit 1; }
  echo "아직 고정 전입니다. $WAIT_MSG"
  export HUNT_R2_REPO="$REPO" HUNT_R2_BASE="$BASE"
  exec bash "$WAITER"
fi
echo $$ > "$BASE/RUNNING"
rm -f "$BASE/WARNINGS"                       # every stage that warns re-runs on a resume, so it warns again
echo "0|run start|$(date +%s)" >> "$BASE/STAGES"
[ "$DRYRUN" = 1 ] && say "연습 모드 (DRYRUN): 설치·자료 받기·보내기는 하지 않습니다"

# ------------------------------------------------------------------ helper (Python, run from the repository)
helper() {                   # helper <pincheck|picks|ledgercheck|verdict|stamp> args...
  "$PY" - "$@" <<'PYEOF'
import glob, hashlib, json, os, platform, subprocess, sys, time
sys.path.insert(0, os.getcwd())
sub, args = sys.argv[1], sys.argv[2:]
PIN_REL = "research/hunt_r2/PREREG_HUNT_R2.sha256"
OUT = "research/hunt_r2/out"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pin_last(rel):
    rows = [ln.rstrip("\n").split("  ", 1) for ln in open(PIN_REL) if ln.strip()]
    hs = [x[0] for x in rows if len(x) == 2 and x[1].strip() == rel]
    return hs[-1] if hs else None


if sub == "pincheck":                    # the code's own check (PREREG 11, pin_r2.check_pin)
    from research.hunt_r2 import pin_r2 as PN
    try:
        r = PN.check_pin(args[0])
        print(f"pin ok {args[0]}: {r['files']} lines, pin sha256 {r['pin_sha256'][:16]}")
    except Exception as e:  # noqa: BLE001
        print(f"refused: {e}"[:2000])
        sys.exit(2)
elif sub == "pinned":                    # pinned <rel>: the file exists and its sha256 is its last pin line
    rel = args[0]
    sys.exit(0 if os.path.exists(rel) and pin_last(rel) == sha(rel) else 1)
elif sub == "picks":                     # the picks line (5): picks.json's sha256 is the pin's last picks line
    rel = f"{OUT}/picks.json"
    doc = json.load(open(rel))
    h = sha(rel)
    ok = pin_last(rel) == h
    picks = doc.get("picks") or []
    b = doc.get("batches") or []
    b1 = len(b[0]) if b else 0
    tfs = {}
    for p in picks:
        tfs[p.get("tf") or (p.get("anchor") or {}).get("tf")] = tfs.get(p.get("tf") or (p.get("anchor") or {}).get("tf"), 0) + 1
    sc = doc.get("stage_counts") or {}
    print(f"PICKS n={len(picks)} batch1={b1} sha256={h} pinned={'yes' if ok else 'no'} candidates={sc.get('candidates')} "
          f"taken={sc.get('taken')} boxes_failed={sc.get('boxes_failed')} by_tf="
          f"{','.join(f'{k}:{v}' for k, v in sorted(tfs.items(), key=lambda kv: str(kv[0])))}")
    sys.exit(0 if ok else 1)
elif sub == "ledgercheck":               # ledgercheck <public root> <private dir>: sha256 only, nothing opened
    pub, priv = args
    for label, prel, fname in (("1차 넓게(wide)", "research/hunt/out/wide/test.json", "wide_test_private.json"),
                               ("2번 트랙", "research/hiwr/out/test.json", "test_private.json")):
        pp = os.path.join(pub, prel)
        fp = os.path.join(priv, fname)
        want = None
        if os.path.exists(pp):
            try:
                want = json.load(open(pp)).get("private_sha256")
            except Exception:  # noqa: BLE001
                want = None
        if not os.path.exists(pp):
            st = "공개 결과 없음 (장부에 '없음')"
        elif not os.path.exists(fp):
            st = "비공개 파일 없음 → 딥시크 줄 p = 1"
        elif want and sha(fp) == want:
            st = "비공개 파일 sha256 일치"
        else:
            st = "비공개 파일 sha256 다름 → 딥시크 줄 p = 1"
        print(f"LEDGER {label}: {st}")
elif sub == "verdict":                   # one public line of test.json (counts and yes / no only)
    doc = json.load(open(f"{OUT}/test.json"))
    v = doc.get("verdict") or {}
    if not doc.get("test_data_read", True):
        print("판정: 고르기에서 끝 (고른 것 없음, 시험 기간 자료는 읽지 않음)")
    else:
        print(f"판정: R2 PASS {'예' if v.get('r2_pass') else '아니오'} (통과 {len(v.get('passing') or [])}개), "
              f"커스텀이 기본값을 이김(TUNED BETTER) {'예' if v.get('tuning_beat_textbook') else '아니오'}")
elif sub == "stamp":
    out, base, priv, ncpu, procs, dry = args
    def git(*a):
        try:
            return subprocess.run(["git", *a], capture_output=True, text=True, timeout=60).stdout.strip()
        except Exception:  # noqa: BLE001
            return None
    pats = ["research/hunt_r2/*.py", "research/hunt_r2/*.sh", "research/hunt_r2/*.md", "research/hunt_r2/*.json",
            "research/hunt_r2/*.sha256", "research/hunt_r2/GO_COMMIT", "research/hunt/hunt.py",
            "research/hunt/entries_wide.py", "research/hunt/reads_a.py", "research/hunt/reads_o.py",
            "research/hunt/data_hunt.py", "research/hunt/*.json", "tests/test_hunt_r2*.py"]
    files = sorted({p for pat in pats for p in glob.glob(pat) if os.path.isfile(p)})
    stages = []
    try:
        rows = [ln.rstrip("\n").split("|") for ln in open(os.path.join(base, "STAGES")) if ln.strip()]
        for i, (n, name, t) in enumerate(rows):
            t1 = int(rows[i + 1][2]) if i + 1 < len(rows) else int(time.time())
            stages.append({"stage": int(n), "name": name,
                           "start_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(t))),
                           "minutes": round((t1 - int(t)) / 60, 1)})
    except Exception as e:  # noqa: BLE001
        stages = [f"unreadable: {e!r}"]
    vers = {}
    for m in ("numpy", "pandas", "numba", "scipy", "pytest"):
        try:
            vers[m] = __import__(m).__version__
        except Exception:  # noqa: BLE001
            vers[m] = None
    mem = None
    try:
        mem = [ln for ln in open("/proc/meminfo") if ln.startswith("MemTotal")][0].split()[1] + " kB"
    except Exception:  # noqa: BLE001
        pass
    settings = {}
    try:
        settings = dict(ln.rstrip("\n").split("=", 1) for ln in open(os.path.join(base, "settings.env")) if "=" in ln)
    except Exception:  # noqa: BLE001
        pass
    priv_files = {}
    for p in sorted(glob.glob(os.path.join(priv, "*"))):
        if os.path.isfile(p):
            priv_files[os.path.relpath(p, priv)] = sha(p)          # names and sha256 only: the figures stay off (D11)
    stamp = {"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "dry_run": dry == "1",
             "git": {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                     "status_porcelain": git("status", "--porcelain")},
             "settings": settings, "files_sha256": {p: sha(p) for p in files}, "python": sys.version,
             "packages": vers, "machine": {"nproc": int(ncpu), "procs_used": int(procs), "mem": mem,
                                           "platform": platform.platform()},
             "stages": stages, "private_files_sha256": priv_files,
             "private_note": "DeepSeek figures (D11) and the event store stay in the private folder on the server "
                             "(private.tgz holds its top-level files only), not here"}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(stamp, open(out, "w"), indent=1)
    print("stamp written", out)
else:
    print("unknown helper", sub)
    sys.exit(2)
PYEOF
}

# ------------------------------------------------------------------ the go commit (before anything else)
cd "$REPO" || die "코드 폴더가 없습니다: $REPO"
HEAD=$(git rev-parse HEAD 2>/dev/null || echo nogit)
if [ "$DRYRUN" != 1 ] || [ -n "$GO" ]; then
  if ! [[ $GO =~ ^[0-9a-f]{7,40}$ ]]; then
    die_fix "커밋 번호가 이상합니다 (HUNT_R2_GO=${GO:-없음})."
  fi
  case "$HEAD" in
    "$GO"*) ;;
    *) die_fix "코드(${HEAD:0:10})가 검토를 마친 커밋(${GO})과 다릅니다. 계산하지 않습니다." ;;
  esac
fi
save_settings

# ------------------------------------------------------------------ 1 install
stage 1 "설치 (파이썬 3.12 + numpy 2.0.2, pandas 2.3.3, numba 0.60.0)"
export DEBIAN_FRONTEND=noninteractive
if [ "$DRYRUN" = 1 ]; then
  sub "연습: 설치 건너뜀 (파이썬: $PY)"
elif [ ! -f "$BASE/INSTALLED" ]; then
  ok=""
  for k in $(seq 1 20); do
    if apt-get -o DPkg::Lock::Timeout=60 update -y >>"$LOG" 2>&1 \
       && apt-get -o DPkg::Lock::Timeout=60 install -y python3-venv python3-pip git tmux >>"$LOG" 2>&1; then
      ok=1; break
    fi
    say "다른 설치(자동 업데이트)가 끝나기를 기다립니다 (${k}/20)"; sleep 30
  done
  [ -n "$ok" ] || die_retry "apt 설치가 30분 넘게 막혀 있습니다 (새 서버의 자동 업데이트)."
  rm -rf "$VENV"
  python3 -m venv "$VENV" || die_retry "venv 만들기 실패"
  "$VENV/bin/pip" install -q --upgrade pip >>"$LOG" 2>&1
  # the versions the coins30 data, the hunt and round 2 were built and tested with
  "$VENV/bin/pip" install -q "numpy==2.0.2" "pandas==2.3.3" "numba==0.60.0" "scipy>=1.11" "pytest>=8" >>"$LOG" 2>&1 \
    || die_retry "패키지 설치 실패 (인터넷)"
  "$PY" -c "import sys, numba, numpy, pandas, scipy; print('python', sys.version.split()[0], 'numpy', numpy.__version__, 'pandas', pandas.__version__, 'numba', numba.__version__, 'scipy', scipy.__version__)" \
    >>"$LOG" 2>&1 || die "numba를 불러오지 못했습니다"
  touch "$BASE/INSTALLED"
fi
FREEG=$(df -BG --output=avail "$BASE" | tail -1 | tr -dc '0-9')
MEMG=$(free -g | awk '/Mem/{print $2}')
say "코드 ${HEAD:0:10}, CPU ${NCPU}개, 메모리 ${MEMG}GB, 디스크 여유 ${FREEG}GB"
[ "$DRYRUN" = 1 ] || [ "${FREEG:-0}" -ge 40 ] || [ -f "$BASE/DATA_VERIFIED" ] \
  || die "디스크 여유가 40GB보다 적습니다(${FREEG}GB). 서버를 Destroy하고 디스크 100GB로 다시 만드세요."
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
PROCS=$NCPU
[ "${MEMG:-0}" -ge 2 ] && [ $(( MEMG / 2 )) -lt "$PROCS" ] && PROCS=$(( MEMG / 2 ))   # about 2 GB per worker at most
[ -n "${HUNT_R2_PROCS:-}" ] && PROCS=$HUNT_R2_PROCS
[ "$PROCS" -lt 1 ] && PROCS=1
HALF=$(( PROCS > 2 ? PROCS / 2 : 1 ))

# ------------------------------------------------------------------ 2 self-check
stage 2 "자체 점검 (2차 시험 코드 + 1차 시험 코드, 몇 분 동안 조용한 게 정상)"
KEY="$HEAD|${HUNT_R2_SELFCHECK_TESTS:-selfcheck}"
if [ "$(cat "$BASE/CHECKED" 2>/dev/null)" != "$KEY" ]; then
  if [ -n "${HUNT_R2_SELFCHECK_TESTS:-}" ]; then
    read -r -a TL <<<"$HUNT_R2_SELFCHECK_TESTS"
    "$PY" -m pytest -q -x -p no:cacheprovider "${TL[@]}" >>"$LOG" 2>&1
  else
    "${R2[@]}" selfcheck >>"$LOG" 2>&1
  fi || die_fix "자체 점검 실패 (run.log 마지막 부분도 보내 주세요: tail -50 $LOG)"
  echo "$KEY" > "$BASE/CHECKED"
  sub "자체 점검 통과: $(grep -aE '[0-9]+ passed' "$LOG" | tail -1)"
else
  sub "건너뜀: 이 코드로 이미 통과"
fi

# ------------------------------------------------------------------ 3 pins (refuse before any download)
pinned() { helper pinned "$1" 2>>"$LOG"; }
pin_check() {                # pin_check <select|pretest|test|reads>: the code's own check_pin
  local out rc
  out=$(helper pincheck "$1" 2>&1); rc=$?
  echo "$out" >> "$LOG"
  [ "$rc" = 0 ] || die_fix "고정 확인 거부 ($1): $(echo "$out" | tail -1 | cut -c1-400)"
}
stage 3 "고정 확인 (설계 해시 첫 줄, 2차 코드·시험·서버 키트, 1차 엔진 파일이 1차 고정값 그대로인지)"
[ -f "$PIN_REL" ] || die_fix "$PIN_REL 가 없습니다: 2차가 아직 고정되지 않았습니다"
[ -f "$REF" ] || die_fix "자료 기준 파일이 없습니다: $REF"
if grep -q "  $PICKS_REL\$" "$PIN_REL" && [ ! -f "$BASE/SELECT_RAN" ]; then
  die_fix "고정 파일에 이미 고른 것(picks) 줄이 있습니다. 이 서버에서 고르기 전이므로 있으면 안 됩니다 (받은 커밋 확인)"
fi
if pinned "$TEST_REL"; then step="reads"; elif pinned "$PICKS_REL"; then step="test"; else step="select"; fi
pin_check "$step"
sub "고정 일치 (다음 단계: $step; $(tail -1 "$LOG" | cut -c1-120))"

# ------------------------------------------------------------------ 4 download 5m (2020-01 .. 2026-09, as round 1)
stage 4 "바이낸스 공개 자료 받기 (30개 코인 5분봉·마크 가격·펀딩, 2020-01 ~ 2026-09; 1차와 같은 자료)"
if [ -f "$DATA/COMPLETE" ]; then
  sub "건너뜀: 이미 받았습니다 ($DATA)"
elif [ "$DRYRUN" = 1 ] && [ -z "${HUNT_R2_DATA_CMD:-}" ]; then
  die_fix "연습: 자료 폴더에 COMPLETE가 없습니다 ($DATA)"
else
  for k in 1 2 3; do
    "${DH[@]}" download --kind 5m --out "$DATA" --workers "$WORKERS" >>"$LOG" 2>&1 && break
    [ -f "$DATA/COMPLETE" ] && break
    [ "$k" -lt 3 ] && { say "  받기가 다 끝나지 않아 빠진 것만 이어서 다시 합니다 (${k}/3)"; sleep "$RSLEEP"; }
  done
  if [ ! -f "$DATA/COMPLETE" ]; then
    pr=$("${DH[@]}" problems --data "$DATA" 2>&1); echo "$pr" >> "$LOG"
    die_retry "자료 받기가 세 번 해도 끝나지 않았습니다: $(grep -E '^(PROBLEM|NOT BUILT)' <<<"$pr" | head -3 | tr '\n' ' ')"
  fi
fi
[ -f "$DATA/COMPLETE" ] || die_fix "자료 폴더가 완성되지 않았습니다: $DATA (COMPLETE 없음)"

# ------------------------------------------------------------------ 5 verify against the pinned reference
stage 5 "받은 자료가 고정된 자료와 같은지 확인 (2차가 읽는 값이 숫자 하나라도 다르면 멈춤)"
if [ -f "$BASE/DATA_VERIFIED" ]; then
  sub "건너뜀: 이미 확인했습니다"
else
  "${DH[@]}" verify --data "$DATA" --ref "$REF" --report "$BASE/verify_5m.json" >>"$LOG" 2>&1 \
    || die_fix "받은 자료가 고정된 자료와 다릅니다 ($(grep -aE '^VERIFY' "$LOG" | tail -1 | cut -c1-200)). 계산하지 않습니다"
  touch "$BASE/DATA_VERIFIED"
  if [ -f "$REF_ALL" ]; then        # mark price and every other key: a check, not a stop (round 2 reads REF's arrays)
    "${DH[@]}" verify --data "$DATA" --ref "$REF_ALL" --report "$BASE/verify_5m_allkeys.json" >>"$LOG" 2>&1 \
      || echo "ALLKEYS differ" > "$BASE/ALLKEYS_DIFFER"
  fi
fi
sub "2차가 읽는 값: $(grep -aE '^VERIFY' "$LOG" | head -1 | cut -c1-160)"
[ -f "$BASE/ALLKEYS_DIFFER" ] && warn "마크 가격 등 2차가 읽지 않는 열이 1차 기준과 다릅니다 (verify_5m_allkeys.json; 판정과는 관계없음)"

# ------------------------------------------------------------------ 6 select (2021-2023 only; the long step)
run_select() {
  "${R2[@]}" select --data "$DATA" --private "$PRIV" --procs "$1" >>"$LOG" 2>&1
}
stage 6 "고르기 (2021~2023만: 85개 이름의 숫자, 가짜 탐색 400번 포함, 작업 ${PROCS}개 동시에)"
if pinned "$PICKS_REL"; then
  sub "건너뜀: 고르기 (이미 끝나 고정됨)"
else
  touch "$BASE/SELECT_RAN"
  mkdir -p "$PRIV"
  sub "고르기 시작 (5~15시간; 진행: bash $SELF status)"
  if ! run_select "$PROCS"; then
    tail -40 "$LOG" | grep -q "^refused:" && die_fix "고르기 거부: $(grep -a '^refused:' "$LOG" | tail -1 | cut -c1-300)"
    if tail -40 "$LOG" | grep -qE "workers keep dying|a worker died|MemoryError|Killed"; then
      sub "고르기 작업 일부가 끝나지 않아 한 번 더 이어서 합니다 (끝난 조각은 건너뜀, 작업 ${HALF}개)"
      run_select "$HALF" || die_retry "고르기가 두 번 끝나지 않았습니다 (메모리?; tail -50 $LOG)"
    else
      die "고르기 실패 (run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
    fi
  fi
  pinned "$PICKS_REL" || die "고르기는 끝났는데 고른 것(picks.json)이 고정 파일에 없습니다"
fi

# ------------------------------------------------------------------ 7 the picks line (before any test bar)
stage 7 "고른 것 고정 확인 (picks.json의 sha256이 고정 파일 끝에 붙었는지; 이 뒤에만 시험 기간을 읽음)"
line=$(helper picks 2>>"$LOG") || die "고른 것과 고정 파일 줄이 맞지 않습니다: $line"
echo "$line" | tee -a "$LOG" > "$BASE/picks_line.txt"
P=$(sed -n 's/.*PICKS n=\([0-9]*\).*/\1/p' <<<"$line")
B1=$(sed -n 's/.*batch1=\([0-9]*\).*/\1/p' <<<"$line")
[ -n "$P" ] && [ -n "$B1" ] || die "고른 것 수를 읽지 못했습니다: $line"
echo "$B1" > "$BASE/PICKS_B1"
mkdir -p "$BASE/picks_backup"
cp "$PICKS_REL" "$PIN_REL" "$BASE/picks_backup/" 2>/dev/null
if [ "$P" = 0 ]; then
  sub "고른 것 0개: 2차는 고르기에서 끝납니다 (시험 기간 자료는 읽지 않음; 시험 전 표와 장부만 씀)"
else
  sub "고른 것 ${P}개, 1군 ${B1}개 ($(sed -n 's/.*\(candidates=[^ ]*\) \(taken=[^ ]*\) \(boxes_failed=[^ ]*\).*/\1 \2 \3/p' <<<"$line"))"
fi

# ------------------------------------------------------------------ 8 select-only reads (before test.json)
run_pretest() { "${R2[@]}" pretest --data "$DATA" --private "$PRIV" --procs "$1" >>"$LOG" 2>&1; }
stage 8 "시험 전 표 (2021~2023만: CSCV, 모멘텀 비교, 주말 표, 두 분용 표; 고르는 데 쓰지 않음)"
if pinned "$PRETEST_REL"; then
  sub "건너뜀: 시험 전 표 (이미 끝나 고정됨)"
elif [ -s "$TEST_REL" ]; then
  warn "시험 전 표가 시험 뒤로 밀렸습니다 (나중에 계산하면 '사후'로 표시)"
else
  if [ -f "$PRETEST_REL" ]; then                 # written but its line not appended (stopped between the two)
    mv "$PRETEST_REL" "$BASE/pretest_reads.unpinned.$(date +%s).json"
    sub "고정 줄이 없는 시험 전 표를 치우고 다시 계산합니다"
  fi
  if ! run_pretest "$PROCS"; then
    if tail -40 "$LOG" | grep -qE "workers keep dying|a worker died|MemoryError|Killed"; then
      [ -f "$PRETEST_REL" ] && ! pinned "$PRETEST_REL" && mv "$PRETEST_REL" "$BASE/pretest_reads.unpinned.$(date +%s).json"
      sub "시험 전 표를 작업 ${HALF}개로 한 번 더 합니다"
      run_pretest "$HALF" || warn "시험 전 표 실패 (판정과는 관계없음; 나중에 계산하면 '사후'; tail -50 $LOG)"
    else
      warn "시험 전 표 실패 (판정과는 관계없음; 나중에 계산하면 '사후'; run.log의 마지막 부분 참고)"
    fi
  fi
  pinned "$PRETEST_REL" && sub "시험 전 표 고정됨 (pretest_reads.json)"
fi

# ------------------------------------------------------------------ 9 test (one look) with the ledger inputs
src_from_ref() {             # src_from_ref <ref> <suffix> -> the shortest path in the ref ending with /<suffix>
  git -C "$REPO" ls-tree -r --name-only "$1" 2>/dev/null | awk -v s="/$2" 'length($0) >= length(s) && substr($0, length($0) - length(s) + 1) == s { print length($0) "\t" $0 }' \
    | sort -n | head -1 | cut -f2
}
fetch_branch() {             # fetch_branch <name>: the exact branch, else the newest "<name>-*"; prints the ref
  local b=$1 c
  if git -C "$REPO" fetch -q origin "+refs/heads/$b:refs/remotes/origin/$b" >>"$LOG" 2>&1; then echo "origin/$b"; return 0; fi
  c=$(git -C "$REPO" ls-remote --heads origin "$b-*" 2>>"$LOG" | awk '{print $2}' | sed 's#^refs/heads/##' | sort | tail -1)
  [ -n "$c" ] && git -C "$REPO" fetch -q origin "+refs/heads/$c:refs/remotes/origin/$c" >>"$LOG" 2>&1 && echo "origin/$c"
}
put_public() {               # put_public <dest under LPUB> <suffix> <ref or ""> <checkout paths...>
  local dst=$1 suf=$2 ref=$3 p src
  shift 3
  mkdir -p "$(dirname "$LPUB/$dst")"
  for p in "$@"; do
    if [ -f "$REPO/$p" ]; then
      cp "$REPO/$p" "$LPUB/$dst" && echo "$dst <- checkout:$p $(sha256sum "$LPUB/$dst" | cut -c1-16)" >> "$BASE/ledger_inputs.txt"
      return 0
    fi
  done
  [ -n "$ref" ] || { echo "$dst <- none" >> "$BASE/ledger_inputs.txt"; return 1; }
  src=$(src_from_ref "$ref" "$suf")
  if [ -n "$src" ] && git -C "$REPO" show "$ref:$src" > "$LPUB/$dst.tmp" 2>>"$LOG"; then
    mv "$LPUB/$dst.tmp" "$LPUB/$dst"
    echo "$dst <- $ref:$src $(sha256sum "$LPUB/$dst" | cut -c1-16)" >> "$BASE/ledger_inputs.txt"
    return 0
  fi
  rm -f "$LPUB/$dst.tmp"
  echo "$dst <- none ($ref)" >> "$BASE/ledger_inputs.txt"
  return 1
}
ledger_inputs() {            # PREREG 8: the other studies' public outputs, the full grid's confirm.json, the owners' files
  local r1="" t2="" fg="" k f list m want
  rm -rf "$LPUB"; mkdir -p "$LPUB" "$LPRIV"
  : > "$BASE/ledger_inputs.txt"
  for k in 1 2 3; do
    [ -n "$r1" ] || r1=$(fetch_branch "$R1_BRANCH")
    [ -n "$t2" ] || t2=$(fetch_branch "$T2_BRANCH")
    [ -n "$fg" ] || fg=$(fetch_branch "$FG_BRANCH")
    [ -n "$r1" ] && [ -n "$t2" ] && [ -n "$fg" ] && break
    [ "$k" -lt 3 ] && sleep "$RSLEEP"
  done
  echo "refs: round 1 ${r1:-none}, track 2 ${t2:-none}, full grid ${fg:-none}" >> "$BASE/ledger_inputs.txt"
  put_public research/hunt/out/v1/test.json hunt/v1/test.json "$r1" research/hunt/out/v1/test.json \
    research/hunt/results/hunt/v1/test.json || warn "장부: 1차 v1 시험 결과를 찾지 못했습니다 (장부에는 '아직 안 돈 시험'으로 셈)"
  put_public research/hunt/out/wide/test.json hunt/wide/test.json "$r1" research/hunt/out/wide/test.json \
    research/hunt/results/hunt/wide/test.json || warn "장부: 1차 넓게(wide) 시험 결과를 찾지 못했습니다 (장부에는 '아직 안 돈 시험'으로 셈)"
  put_public research/hunt/out/wide/reads_o.json hunt/wide/reads_o.json "$r1" research/hunt/out/wide/reads_o.json \
    research/hunt/results/hunt/wide/reads_o.json || warn "장부: 1차 추가 분석(reads_o.json)이 없습니다 (O4 줄은 최대 개수, p = 1)"
  put_public research/hiwr/out/test.json hiwr/out/test.json "$t2" research/hiwr/out/test.json \
    research/hiwr/results/hiwr/out/test.json || warn "장부: 2번 트랙 시험 결과를 찾지 못했습니다 (장부에는 '아직 안 돈 시험'으로 셈)"
  put_public research/hiwr/picks.json hiwr/picks.json "$t2" research/hiwr/picks.json research/hiwr/results/hiwr/picks.json \
    || true
  if put_public fullgrid_confirm.json fullgrid/results/confirm.json "$fg" research/fullgrid/results/confirm.json; then
    FG_ARGS=(--fullgrid-confirm "$LPUB/fullgrid_confirm.json")
  else
    FG_ARGS=()
    warn "장부: 풀그리드 confirm.json을 받지 못했습니다 (711줄은 p = 1)"
  fi
  # the owners' private files (8): only the two p files are taken out of their *.tgz; nobody opens them
  for f in "$INBOX"/*.tgz "$INBOX"/*.tar.gz; do
    [ -f "$f" ] || continue
    case "$f" in "$BASE"/*) continue ;; esac
    list=$(tar -tzf "$f" 2>>"$LOG") || { warn "장부: 풀 수 없는 파일 $(basename "$f")"; continue; }
    for want in wide_test_private.json test_private.json; do
      m=$(printf '%s\n' "$list" | awk -F/ -v w="$want" '$NF == w { print NF "\t" $0 }' | sort -n | head -1 | cut -f2)
      [ -n "$m" ] || continue
      if tar -xzf "$f" -O "$m" > "$LPRIV/$want.tmp" 2>>"$LOG"; then
        mv "$LPRIV/$want.tmp" "$LPRIV/$want"
        echo "private $want <- $(basename "$f"):$m" >> "$BASE/ledger_inputs.txt"
      else
        rm -f "$LPRIV/$want.tmp"
      fi
    done
  done
  helper ledgercheck "$LPUB" "$LPRIV" 2>>"$LOG" | while IFS= read -r l; do sub "$l"; done
}
run_test() {
  "${R2[@]}" test --data "$DATA" --private "$PRIV" --procs "$1" --no-reads --ledger-private "$LPRIV" \
    --ledger-public "$LPUB" "${FG_ARGS[@]}" >>"$LOG" 2>&1
}
stage 9 "시험 (2024-01 ~ 2026-09, 1군부터, 한 번만) + 프로그램 전체 장부"
FG_ARGS=()
if pinned "$TEST_REL"; then
  sub "건너뜀: 시험 (이미 끝나 고정됨)"
else
  if [ -f "$TEST_REL" ]; then                    # written but its line not appended: the parts give the same result
    mv "$TEST_REL" "$BASE/test.unpinned.$(date +%s).json"
    warn "고정 줄이 없는 test.json을 치우고 다시 씁니다 (조각 파일에서 같은 결과; 치운 파일: $BASE/test.unpinned.*.json)"
  fi
  ledger_inputs
  if ! run_test "$PROCS"; then
    tail -40 "$LOG" | grep -q "^refused:" && die "시험 거부: $(grep -a '^refused:' "$LOG" | tail -1 | cut -c1-300)"
    if tail -40 "$LOG" | grep -qE "workers keep dying|a worker died|MemoryError|Killed"; then
      [ -f "$TEST_REL" ] && ! pinned "$TEST_REL" && mv "$TEST_REL" "$BASE/test.unpinned.$(date +%s).json"
      sub "시험 작업 일부가 끝나지 않아 한 번 더 이어서 합니다 (끝난 픽은 건너뜀, 작업 ${HALF}개)"
      run_test "$HALF" || die_retry "시험이 두 번 끝나지 않았습니다 (메모리?; tail -50 $LOG)"
    else
      die "시험 실패 (run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
    fi
  fi
  pinned "$TEST_REL" || die "시험은 끝났는데 test.json이 고정 파일에 없습니다"
fi
vline=$(helper verdict 2>>"$LOG") && { echo "$vline" > "$BASE/verdict_line.txt"; sub "$vline"; }

# ------------------------------------------------------------------ 10 reads (never a pass; 12 hours wall over restarts)
stop_tree() {                # stop_tree <pid>: the step and its pool workers (forked children)
  pkill -TERM -P "$1" 2>/dev/null; kill -TERM "$1" 2>/dev/null
}
reads_once() {               # reads_once <procs>: one reads run within the wall left; 0 done, 1 failed, 124 wall
  local procs=$1 used left rc=0 to t0 timed=""
  used=$(cat "$BASE/READS_USED_S" 2>/dev/null || echo 0)
  left=$(( READS_HOURS * 3600 - used ))
  [ "$left" -le 60 ] && return 124
  sub "참고 분석 (r=1%·대조 → 주말 → 목표판 순서; 끝난 모듈은 건너뜀; ${READS_HOURS}시간 중 $(( left / 60 ))분 남음, 작업 ${procs}개)"
  "${R2[@]}" reads --data "$DATA" --private "$PRIV" --procs "$procs" >>"$LOG" 2>&1 &
  to=$!
  t0=$(date +%s)
  trap 'stop_tree "$to"; exit 1' HUP INT TERM      # a pane kill or Ctrl+C stops the read with the run
  while kill -0 "$to" 2>/dev/null; do              # the wall counts running time only, over restarts
    echo $(( used + $(date +%s) - t0 )) > "$BASE/READS_USED_S"
    if [ $(( used + $(date +%s) - t0 )) -ge $(( READS_HOURS * 3600 )) ]; then
      timed=1; stop_tree "$to"; sleep 5; pkill -KILL -P "$to" 2>/dev/null; kill -KILL "$to" 2>/dev/null
      break
    fi
    sleep 20
  done
  wait "$to" || rc=$?
  trap - HUP INT TERM
  echo $(( used + $(date +%s) - t0 )) > "$BASE/READS_USED_S"
  [ -n "$timed" ] && return 124
  [ "$rc" = 0 ] && return 0
  return 1
}
reads_stage() {
  local rc=0 f
  if [ "$P" = 0 ]; then sub "고른 것이 없어 참고 분석도 없습니다 (9.1: 행이 없음)"; return 0; fi
  if [ -f "$BASE/READS_DONE" ]; then sub "건너뜀: 참고 분석 (이미 끝남)"; return 0; fi
  reads_once "$PROCS" || rc=$?
  if [ "$rc" = 1 ] && tail -60 "$LOG" | grep -qE "workers keep dying|a worker died|MemoryError|Killed"; then
    sub "참고 분석 작업 일부가 끝나지 않아 작업 ${HALF}개로 한 번 더 합니다 (끝난 모듈은 건너뜀)"
    rc=0; reads_once "$HALF" || rc=$?
  fi
  case "$rc" in
    0) ;;
    124) warn "참고 분석이 ${READS_HOURS}시간에 닿아 멈췄습니다 (판정은 그대로; 끝난 모듈만 묶음)" ;;
    *) warn "참고 분석 실패 (run.log의 [reads r2] 줄 참고; 판정은 그대로, 끝난 모듈만 묶음)" ;;
  esac
  touch "$BASE/READS_DONE"   # one try per run: a kill of the whole run (pane, reboot) leaves this unset and resumes
  for f in reads_rows.json reads_weekend.json reads_goal.json; do
    [ -s "$OUT/$f" ] || warn "참고 분석 $f 없음 (시간 또는 실패; run.log 참고)"
  done
  return 0
}
stage 10 "참고 분석 (고른 것들의 r = 1%·고르는 기간 대조·주말 포함/제외·목표판·20/30/40배; 통과 기준이 아님, 최대 ${READS_HOURS}시간)"
reads_stage

# ------------------------------------------------------------------ 11 report and pack
pack() {
  local R=$BASE/results f
  rm -rf "$R"
  mkdir -p "$R/hunt_r2" "$R/pins" "$R/data" "$R/stamps" "$R/ledger" || return 1
  [ -d "$OUT" ] && cp -r "$OUT" "$R/hunt_r2/"
  cp "$PIN_REL" "$R/pins/" || return 1
  for f in "$REF" "$BASE/verify_5m.json" "$BASE/verify_5m_allkeys.json" "$BASE/picks_line.txt"; do
    [ -f "$f" ] && cp "$f" "$R/data/"
  done
  [ -f "$DATA/manifest.json" ] && cp "$DATA/manifest.json" "$R/data/manifest_5m.json"
  [ -f "$BASE/ledger_inputs.txt" ] && cp "$BASE/ledger_inputs.txt" "$R/ledger/"
  helper stamp "$R/stamps/code_stamp.json" "$BASE" "$PRIV" "$NCPU" "$PROCS" "$DRYRUN" >>"$LOG" 2>&1 || return 1
  grep -av -E "\[data [0-9]+/[0-9]+\]|: [0-9]+/[0-9]+ files, free " "$LOG" > "$R/run.log"
  [ -s "$BASE/WARNINGS" ] && cp "$BASE/WARNINGS" "$R/WARNINGS.txt"
  {
    echo "# 1번 트랙 2차 결과 묶음 (bootstrap_r2.sh $(date -u '+%Y-%m-%d %H:%M UTC'), 커밋 ${HEAD:0:10})"
    echo
    echo "* $(cat "$BASE/verdict_line.txt" 2>/dev/null || echo '판정 줄 없음')"
    echo "* 고른 것: $(cat "$BASE/picks_line.txt" 2>/dev/null)"
    if [ -s "$BASE/WARNINGS" ]; then echo "* 건너뛰거나 빠진 것이 있습니다: WARNINGS.txt"; else echo "* 건너뛴 것 없음"; fi
    echo
    echo "* hunt_r2/out: picks.json(고르기), pretest_reads.json(시험 전 표), test.json(판정 + 장부), reads_*.json(참고 분석), RESULTS_R2_KO.md"
    echo "* pins/PREREG_HUNT_R2.sha256: 고정 파일 (picks, pretest_reads, test 줄이 붙은 것)"
    echo "* data: 받은 자료 목록과 고정 기준 비교(verify_5m.json), 고른 것 줄"
    echo "* ledger/ledger_inputs.txt: 장부가 읽은 다른 연구의 공개 파일 출처와 sha256 (비공개 파일은 이름만)"
    echo "* stamps/code_stamp.json: 커밋, 설정, 파일 sha256, 패키지 버전, 단계별 시간, 비공개 파일 sha256(내용 없음)"
    echo "* run.log, WARNINGS.txt(건너뛴 것)"
    echo
    echo "딥시크 돈 숫자(D11)와 사건 저장소는 여기 없습니다: 서버의 $PRIV 에만 있고, private.tgz 에는 그 폴더의 맨 위 파일만 담습니다."
  } > "$R/README_KO.md"
  case "$PRIV" in "$R"|"$R"/*) return 1 ;; esac
  tar czf "$BASE/results.tgz" -C "$BASE" results || return 1
  if [ -d "$PRIV" ] && [ -n "$(find "$PRIV" -maxdepth 1 -type f -print -quit 2>/dev/null)" ]; then
    (cd "$BASE" && find private -maxdepth 1 -type f -print0 | tar czf "$BASE/private.tgz" --null -T -) || return 1
  fi
  return 0
}
stage 11 "결과 페이지·결과 묶기"
"${R2[@]}" report --private "$PRIV" >>"$LOG" 2>&1 || warn "결과 페이지(RESULTS_R2_KO.md) 쓰기 실패"
pack || die "결과 묶기 실패 (tail -50 $LOG)"
rm -f "$BASE/RUNNING"
touch "$BASE/DONE"
say "끝. 결과 $(du -h "$BASE/results.tgz" | cut -f1): $BASE/results.tgz"
[ -s "$BASE/verdict_line.txt" ] && say "$(cat "$BASE/verdict_line.txt")"
if [ -s "$BASE/WARNINGS" ]; then say "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS" | tee -a "$LOG"; fi
say "보내기: bash $SELF push   (그다음 Vultr에서 서버 Destroy, 디스크 hunt-r2-disk도 삭제)"
