#!/usr/bin/env bash
# 추세 사냥(v1 + 넓게) · 알트 급등 연구 · 1분봉 정밀 재확인을 빌린 계산 서버에서 돌립니다 (research/hunt/SERVER_KO.md).
# 바이낸스 공개 가격 자료만 씁니다: 거래소 키·AI 키 없음, 규칙봇·데모봇·후보 리그와 관계없음.
#
#   HUNT_GO=<커밋> bash bootstrap.sh   설치 → 자체 점검 → 고정 확인 → 자료 받기 → 자료 확인 → 추세 사냥 → 알트 급등
#                                      → 정밀 재확인 → 결과 묶기 (tmux 안에서 돌리세요). 첫 실행에는 검토를 마친
#                                      커밋(HUNT_GO)이 꼭 있어야 하고, 코드가 그 커밋이 아니면 멈춥니다.
#   bash bootstrap.sh status           지금 단계와 남은 시간(어림)
#   bash bootstrap.sh push             결과를 GitHub(브랜치 hunt-results)로 보냄. 올리기가 되면 토큰을 다시 묻지 않음
#   bash bootstrap.sh update <커밋>    개발자가 고친 커밋으로 코드를 바꿈 (계산 시작 전에만: 6/9 전, 고른 것 없음)
#
# 모든 단계는 이미 끝난 것을 건너뜁니다: 멈추거나 재부팅된 뒤 같은 명령이 이어서 합니다. 첫 실행의 설정
# (HUNT_GO, ALTPUMP, HUNT_WORKERS, HUNT_PROCS, HUNT_FID_FROM/TO)은 $BASE/settings.env 에 남아 다시 시작해도 같습니다.
# 딥시크 돈 숫자(D11)는 저장소 밖 $BASE/private 에만 있고 results.tgz 에는 들어가지 않습니다.
#
# 연습(가짜 자료, 설치·받기·보내기·git 없음):
#   DRYRUN=1 HUNT_BASE=<빈 폴더> HUNT_REPO=<코드 사본> HUNT_DATA=<5m 자료 폴더> [HUNT_FID=<1m 폴더>] [HUNT_PY=python3] \
#     [HUNT_CMD=..] [ALTPUMP_CMD=..] [HUNT_SELFCHECK_TESTS=..] [HUNT_RETRY_SLEEP=0] bash bootstrap.sh --dry-run
set -uo pipefail

MODE=run
DRYRUN=${DRYRUN:-0}
ARG=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRYRUN=1 ;;
    run|status|push|update) MODE=$a ;;
    *) if [ "$MODE" = update ] && [ -z "$ARG" ]; then ARG=$a
       else echo "사용법: bash bootstrap.sh [run|status|push|update <커밋>] [--dry-run]"; exit 2; fi ;;
  esac
done

BASE=${HUNT_BASE:-/root/hunt}
mkdir -p "$BASE"
# Settings of the first run are kept, so a restart (which passes no environment) runs with the same choices.
SETTINGS=$BASE/settings.env
PERSIST="HUNT_GO ALTPUMP HUNT_WORKERS HUNT_PROCS HUNT_FID_FROM HUNT_FID_TO"
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

REPO=${HUNT_REPO:-$BASE/crypto-bot-research}
DATA=${HUNT_DATA:-$BASE/data5m}
FID=${HUNT_FID:-$BASE/fid1m}
PRIV=${HUNT_PRIVATE:-$BASE/private}
VENV=$BASE/venv
LOG=$BASE/run.log
REF=${HUNT_DATA_REF:-research/hunt/data_manifest.json}       # the hunt's pinned data identity (hunt datapin, H 2)
REF_ALL=${HUNT_DATA_REF_ALL:-research/hunt/data_ref_5m.json} # every 5m key incl. mark price (data_hunt refman)
FID_FROM=${HUNT_FID_FROM:-2024-01}
FID_TO=${HUNT_FID_TO:-2026-09}
WORKERS=${HUNT_WORKERS:-8}
ALTPUMP=${ALTPUMP:-1}
GO=${HUNT_GO:-}
RSLEEP=${HUNT_RETRY_SLEEP:-30}
TESTS=${HUNT_SELFCHECK_TESTS:-tests/test_hunt.py tests/test_hunt_entries.py tests/test_data_hunt.py tests/test_altpump.py}
if [ "$DRYRUN" = 1 ]; then PY=${HUNT_PY:-python3}; else PY=${HUNT_PY:-$VENV/bin/python}; fi
if [ -n "${HUNT_CMD:-}" ]; then read -r -a HUNT <<<"$HUNT_CMD"; else HUNT=("$PY" -m research.hunt.hunt); fi
if [ -n "${ALTPUMP_CMD:-}" ]; then read -r -a AP <<<"$ALTPUMP_CMD"; else AP=("$PY" research/altpump/altpump.py); fi
if [ -n "${READS_O_CMD:-}" ]; then read -r -a READS_O <<<"$READS_O_CMD"; else READS_O=("$PY" -m research.hunt.reads_o); fi
AP_OUT=$REPO/research/altpump/out
NCPU=$(env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc)    # nproc obeys OMP_NUM_THREADS, set to 1 below
SELF=$REPO/research/hunt/bootstrap.sh
NST=9
RESTART="tmux kill-session -t hunt 2>/dev/null; tmux new -s hunt \"bash $SELF; bash\""
[ "$DRYRUN" = 1 ] && RESTART="DRYRUN=1 HUNT_BASE=$BASE HUNT_REPO=$REPO HUNT_DATA=$DATA bash $SELF --dry-run"

say() { echo "[$(date -u '+%m-%d %H:%M UTC')] $*" | tee -a "$LOG"; }
sub() { say "  · $*"; }
warn() {                     # something skipped that does not stop the run (listed again at the end)
  say "  · 참고: $*"
  grep -qxF "$*" "$BASE/WARNINGS" 2>/dev/null || echo "$*" >> "$BASE/WARNINGS"
}
computed() {                 # anything computed on this server: stage 6 started, or a select ran here
  grep -qE '^[6-9]\|' "$BASE/STAGES" 2>/dev/null && return 0
  compgen -G "$BASE/SELECT_RAN_*" >/dev/null
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
  say "개발자가 고쳤다고 하면: 개발자가 준 줄(bash $SELF update <커밋>)을 붙여 넣고, 그다음 이 줄로 이어서 합니다:"
  say "  $RESTART"
  exit 1
}
die_retry() {                # a stop that a later restart can get past (network, apt lock)
  say "멈춤: $*"
  say "몇 분 뒤 이 줄을 붙여 넣으면 이어서 합니다 (끝난 것은 건너뜁니다):"
  say "  $RESTART"
  say "같은 멈춤이 두 번 나오면 이 화면을 그대로 복사해 개발자에게 보내 주세요."
  computed && keep_server
  exit 1
}

ap_files_total() { local p=$AP_OUT/pass2_plan.json; if [ -f "$p" ]; then grep -c '"url"' "$p"; else echo 0; fi; }
ap_files_left() {
  local n c; n=$(ap_files_total)
  c=$(find "$AP_OUT/pass2_cache" -name '*.npz' 2>/dev/null | wc -l)
  echo $(( n > c ? n - c : 0 ))
}
# minutes per stage on a 32 vCPU server (stage 6 shrinks with more CPUs; downloads do not). Stage 7: the alt pump's
# second pass fetches its 5m files 2 at a time (PREREG_ALTPUMP 15), about 200 files a minute.
est_min() {
  case $1 in
    1) echo 4 ;; 2) echo 4 ;; 3) echo 1 ;; 4) echo 15 ;; 5) echo 2 ;;
    6) echo $(( 15 + (20 + 420) * 32 / NCPU )) ;;     # select + test (about 35 min) + reads_a (4-9 h on 32 vCPU)
    7) echo $(( 10 + $(ap_files_left) / 200 )) ;; 8) echo $(( 30 + 120 * 32 / NCPU )) ;;   # fidelity + reads_o (1.5-5 h)
    9) echo 1 ;;
    *) echo 0 ;;
  esac
}
left_from() { local s=0 k; for k in $(seq "$1" "$NST"); do s=$(( s + $(est_min "$k") )); done; echo "$s"; }

stage() {                    # stage <n> <name>
  local now; now=$(date +%s)
  echo "$1|$2|$now" > "$BASE/STAGE"
  echo "$1|$2|$now" >> "$BASE/STAGES"
  say "$1/$NST $2  (남은 시간 약 $(left_from "$1")분, 어림)"
}

running() {                  # the run's own process (RUNNING holds its pid), or a step it left behind
  local p; p=$(cat "$BASE/RUNNING" 2>/dev/null)
  if [ -n "$p" ] && kill -0 "$p" 2>/dev/null && grep -qa "hunt/bootstrap.sh" "/proc/$p/cmdline" 2>/dev/null; then
    return 0
  fi
  [ "$DRYRUN" = 1 ] && return 1
  pgrep -f "[r]esearch\.hunt\.(hunt|data_hunt)|[a]ltpump/altpump\.py|[t]ests/test_(hunt|data_hunt|altpump)" >/dev/null
}

incomplete_msg() {
  echo "거의 끝: 결과는 묶었지만 알트 급등 5분봉 2차 확인이 끝나지 않았습니다 ($(cat "$BASE/AP_PASS2_INCOMPLETE" 2>/dev/null))."
  echo "  1) 몇 분 뒤 이 줄을 한 번 더 붙여 넣으세요 (빠진 파일만 다시 받습니다): $RESTART"
  echo "  2) 같은 말이 또 나오면: 결과를 보내고(bash $SELF push) 이 화면을 개발자에게 보내 주세요."
  echo "     개발자가 'Destroy 해도 된다'고 할 때까지 서버를 두세요 (시간당 약 \$1)."
}

status() {
  if [ -f "$BASE/DONE" ]; then
    echo "끝났습니다. 결과: $BASE/results.tgz  (보내기: bash $SELF push)"
    if [ -s "$BASE/WARNINGS" ]; then echo "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS"; fi
    return
  fi
  if ! running; then
    if [ -f "$BASE/AP_PASS2_INCOMPLETE" ] && [ -f "$BASE/results.tgz" ]; then incomplete_msg; return; fi
    echo "지금 돌고 있지 않습니다. 마지막 기록:"
    grep -E "멈춤|\] [0-9]/$NST " "$LOG" 2>/dev/null | tail -3
    echo "이어서 하려면: $RESTART"
    return
  fi
  local n=0 name="설치 중" t0 el left t
  t0=$(date +%s)
  [ -f "$BASE/STAGE" ] && IFS='|' read -r n name t0 < "$BASE/STAGE"
  el=$(( ($(date +%s) - t0) / 60 ))
  left=$(( $(est_min "$n") - el )); [ "$left" -lt 1 ] && left=1
  [ "$n" -lt "$NST" ] && left=$(( left + $(left_from $(( n + 1 ))) ))
  echo "진행 중: $n/$NST $name (이 단계 ${el}분째)"
  echo "  남은 시간: 약 ${left}분 (어림, CPU ${NCPU}개 기준; 처음 몇 분은 들쭉날쭉)"
  local last; last=$(grep -F "  · " "$LOG" 2>/dev/null | tail -1)
  [ -n "$last" ] && echo "  지금: ${last#*· }"
  case "$n" in
    4|8) last=$(grep -oE "\[data [0-9]+/[0-9]+\].*" "$LOG" 2>/dev/null | tail -1)
         [ -n "$last" ] && echo "  자료: $last" ;;
    7) t=$(ap_files_total)
       [ "$t" -gt 0 ] && echo "  알트 급등 2차 자료: $(( t - $(ap_files_left) ))/$t 파일" ;;
  esac
}

push() {
  [ "$DRYRUN" = 1 ] && { echo "연습 모드에서는 보내지 않습니다."; return 1; }
  [ -f "$BASE/results.tgz" ] || die "결과 파일이 아직 없습니다."
  cd "$REPO" || exit 1
  git config user.email "hunt@localhost"; git config user.name "hunt server"
  git config credential.helper store
  # commit in a separate worktree, so the run's checkout stays on the go commit (a later restart checks it)
  local br=hunt-results wt=$BASE/push_wt rc br2
  if [ ! -d "$wt" ]; then
    git worktree prune
    if git rev-parse -q --verify "refs/heads/$br" >/dev/null; then
      git worktree add "$wt" "$br" >>"$LOG" 2>&1 || die "올리기 준비 실패 (git worktree)"
    else
      git worktree add -b "$br" "$wt" HEAD >>"$LOG" 2>&1 || die "올리기 준비 실패 (git worktree)"
    fi
  fi
  cd "$wt" || exit 1
  rm -rf research/hunt/results
  tar xzf "$BASE/results.tgz" -C research/hunt || die "결과 풀기 실패"            # -> research/hunt/results/
  git add -f research/hunt/results
  git commit -q -m "Hunt v1 + wide, alt pump, fidelity: results ($(hostname), $(date -u +%F))" \
    || say "새로 올릴 변경이 없습니다 (이미 커밋됨)"
  echo "GitHub 아이디와, 비밀번호 자리에 쓰기 토큰(Contents: Read and write)을 넣으세요. (올리기가 되면 다시 묻지 않습니다)"
  git push -u origin "$br" 2>&1 | tee "$BASE/push.out"; rc=${PIPESTATUS[0]}
  if [ "$rc" = 0 ]; then say "보냈습니다: 브랜치 $br"; return 0; fi
  if grep -qiE "rejected|non-fast-forward|fetch first" "$BASE/push.out"; then
    br2="hunt-results-$(date -u +%Y%m%d-%H%M)"
    say "GitHub에 같은 이름의 브랜치($br)가 이미 있어 $br2 로 보냅니다"
    git push -u origin "HEAD:refs/heads/$br2" 2>&1 | tee "$BASE/push.out"; rc=${PIPESTATUS[0]}
    if [ "$rc" = 0 ]; then say "보냈습니다: 브랜치 $br2"; return 0; fi
  fi
  if grep -qiE "authentication failed|invalid username|could not read username|password authentication|permission to .* denied|error: 40[13]" "$BASE/push.out"; then
    die "올리기 실패: 토큰이 틀렸거나 권한이 없습니다. 토큰(저장소 crypto-bot-research, Contents: Read and write)을 확인하고 같은 push 줄을 다시 실행하세요 (아이디·토큰을 다시 묻습니다)."
  fi
  die "올리기 실패: 인터넷 문제일 수 있습니다. 잠시 뒤 같은 push 줄을 다시 실행하세요. 계속 안 되면 SERVER_KO 4번의 (나) 파일로 받기를 쓰세요."
}

update() {                   # update <commit>: the developer's fix, only while nothing has been computed
  local want=$1
  [[ $want =~ ^[0-9a-f]{7,40}$ ]] || { echo "사용법: bash $SELF update <커밋 번호 (개발자가 준 것)>"; return 2; }
  if running; then echo "지금 돌고 있습니다. 먼저 멈추세요: tmux kill-session -t hunt"; return 1; fi
  if computed; then
    echo "이미 계산을 시작해서(6/9 이후) 코드를 바꾸지 않습니다. 이 화면을 개발자에게 보내 주세요."; return 1
  fi
  if [ "$DRYRUN" = 1 ]; then
    echo "연습: git 내려받기·바꾸기는 건너뜀"
  else
    git -C "$REPO" fetch -q origin || { echo "코드 내려받기 실패 (인터넷). 잠시 뒤 같은 줄을 다시 붙여 넣으세요."; return 1; }
    git -C "$REPO" checkout -q "$want" || { echo "그 커밋으로 바꾸지 못했습니다: $want (이 화면을 개발자에게 보내 주세요)"; return 1; }
  fi
  HUNT_GO=$want
  case " $GIVEN " in *" HUNT_GO "*) ;; *) GIVEN="$GIVEN HUNT_GO" ;; esac
  save_settings
  rm -f "$BASE/CHECKED"
  echo "코드를 ${want:0:10} 으로 바꿨습니다. 이제 이 줄을 붙여 넣으세요:"
  echo "  $RESTART"
}

case "$MODE" in
  status) status; exit 0 ;;
  push) push; exit $? ;;
  update) update "$ARG"; exit $? ;;
esac

for k in 1 2 3 4 5; do running || break; sleep 2; done      # a restart: let the old run finish dying
running && { echo "이미 돌고 있습니다. 화면 보기: tmux attach -t hunt   (진행: bash $SELF status)"; exit 1; }
if [ -f "$BASE/DONE" ]; then
  echo "이미 끝났습니다: $BASE/results.tgz  (보내기: bash $SELF push; 처음부터 다시 묶으려면 rm $BASE/DONE)"
  exit 0
fi
echo $$ > "$BASE/RUNNING"
rm -f "$BASE/WARNINGS"                       # every stage that warns re-runs on a resume, so it warns again
echo "0|run start|$(date +%s)" >> "$BASE/STAGES"
[ "$DRYRUN" = 1 ] && say "연습 모드 (DRYRUN): 설치·자료 받기·보내기·git은 하지 않습니다"

# ------------------------------------------------------------------ the go commit (before anything else)
cd "$REPO" || die "코드 폴더가 없습니다: $REPO"
HEAD=$(git rev-parse HEAD 2>/dev/null || echo nogit)
if [ "$DRYRUN" != 1 ] || [ -n "$GO" ]; then
  if [ "$DRYRUN" != 1 ] && ! [[ $GO =~ ^[0-9a-f]{7,40}$ ]]; then
    die_fix "어느 커밋을 돌릴지 정해지지 않았습니다 (HUNT_GO=${GO:-없음}). SERVER_KO의 한 줄을 개발자가 준 그대로 쓰세요."
  fi
  case "$HEAD" in
    "$GO"*) ;;
    *) die_fix "코드(${HEAD:0:10})가 검토를 마친 커밋(${GO})과 다릅니다. 계산하지 않습니다." ;;
  esac
fi
save_settings

# ------------------------------------------------------------------ 1 install
stage 1 "설치 (파이썬 패키지)"
export DEBIAN_FRONTEND=noninteractive
if [ "$DRYRUN" = 1 ]; then
  sub "연습: 설치 건너뜀 (파이썬: $PY)"
elif [ ! -f "$BASE/INSTALLED" ]; then
  ok=""
  for k in $(seq 1 20); do
    if apt-get update -y >>"$LOG" 2>&1 && apt-get install -y python3-venv python3-pip git tmux >>"$LOG" 2>&1; then
      ok=1; break
    fi
    say "다른 설치(자동 업데이트)가 끝나기를 기다립니다 (${k}/20)"; sleep 30
  done
  [ -n "$ok" ] || die_retry "apt 설치가 10분 넘게 막혀 있습니다 (새 서버의 자동 업데이트)."
  rm -rf "$VENV"
  python3 -m venv "$VENV" || die_retry "venv 만들기 실패"
  "$VENV/bin/pip" install -q --upgrade pip >>"$LOG" 2>&1
  # the versions the coins30 data, the hunt and the alt pump code were built and tested with
  "$VENV/bin/pip" install -q "numpy==2.0.2" "pandas==2.3.3" "numba==0.60.0" "scipy>=1.11" "pytest>=8" >>"$LOG" 2>&1 \
    || die_retry "패키지 설치 실패 (인터넷)"
  "$PY" -c "import numba, numpy, pandas; print('numpy', numpy.__version__, 'pandas', pandas.__version__, 'numba', numba.__version__)" \
    >>"$LOG" 2>&1 || die "numba를 불러오지 못했습니다"
  touch "$BASE/INSTALLED"
fi
FREEG=$(df -BG --output=avail "$BASE" | tail -1 | tr -dc '0-9')
MEMG=$(free -g | awk '/Mem/{print $2}')
say "코드 ${HEAD:0:10}, CPU ${NCPU}개, 메모리 ${MEMG}GB, 디스크 여유 ${FREEG}GB"
[ "$DRYRUN" = 1 ] || [ "${FREEG:-0}" -ge 20 ] || [ -f "$DATA/COMPLETE" ] \
  || die "디스크 여유가 20GB보다 적습니다(${FREEG}GB). 서버를 Destroy하고 더 큰 서버로 다시 하세요."

# ------------------------------------------------------------------ 2 self-check
stage 2 "자체 점검 (시험 코드, 몇 분 동안 조용한 게 정상)"
KEY="$HEAD|$TESTS"
if [ "$(cat "$BASE/CHECKED" 2>/dev/null)" != "$KEY" ]; then
  read -r -a TL <<<"$TESTS"
  "$PY" -m pytest -q -x -p no:cacheprovider "${TL[@]}" >>"$LOG" 2>&1 \
    || die_fix "자체 점검 실패 (run.log 마지막 부분도 보내 주세요: tail -50 $LOG)"
  echo "$KEY" > "$BASE/CHECKED"
  sub "자체 점검 통과: $(grep -E '[0-9]+ passed' "$LOG" | tail -1)"
else
  sub "건너뜀: 이 코드로 이미 통과"
fi

# ------------------------------------------------------------------ 3 pins (refuse before any download)
picks_rel() { if [ "$1" = v1 ]; then echo research/hunt/out/v1/pick.json; else echo research/hunt/out/wide/picks.json; fi; }
pin_rel() { if [ "$1" = v1 ]; then echo research/hunt/PREREG_HUNT.sha256; else echo research/hunt/PREREG_HUNT_WIDE.sha256; fi; }
picks_pinned() { grep -q "  $(picks_rel "$1")\$" "$(pin_rel "$1")" 2>/dev/null; }
AP_PIN=research/altpump/PREREG_ALTPUMP.sha256
ap_pinned() { grep -q "  research/altpump/out/pick.json\$" "$AP_PIN" 2>/dev/null; }

pin_check() {                # pin_check <hunt|altpump> <study or -> <step>: the code's own check
  local out rc
  out=$("$PY" - "$@" 2>&1 <<'PYEOF'
import sys
which, study, step = sys.argv[1:4]
if which == "hunt":
    from research.hunt import hunt as M
    check = lambda: M.check_pin(study, step)
else:
    from research.altpump import altpump as M
    check = lambda: M.check_pin(step)
try:
    print("pin ok", which, study, step, check())
except M.PinError as e:
    print("refused:", e)
    sys.exit(2)
PYEOF
)
  rc=$?
  echo "$out" >> "$LOG"
  local what=$2; [ "$1" = altpump ] && what="알트 급등"
  [ "$rc" = 0 ] || die_fix "$what 고정 확인 거부: $(echo "$out" | tail -1)"
}

ap_data_check() {            # the alt pump's daily file against the sha256 its pinned prereg states (section 2)
  local f=data/universe/klines_1d.csv.gz want got
  want=$(grep -F "klines_1d.csv.gz" research/altpump/PREREG_ALTPUMP.md 2>/dev/null | grep -oE '[0-9a-f]{64}' | head -1)
  [ -n "$want" ] || die_fix "알트 급등 사전 등록에서 일봉 자료($f)의 sha256을 찾지 못했습니다"
  [ -f "$f" ] || die_fix "알트 급등 일봉 자료가 없습니다: $f"
  got=$(sha256sum "$f" | cut -d' ' -f1)
  [ "$got" = "$want" ] || die_fix "알트 급등 일봉 자료가 사전 등록의 sha256과 다릅니다 ($f)"
}

stage 3 "고정 파일 확인 (사전 등록·코드·자료 기준이 고정된 그대로인지)"
[ -f "$REF" ] || die_fix "자료 기준 파일이 없습니다: $REF"
[ -f "$REF_ALL" ] || die_fix "마크 가격까지 비교할 자료 기준 파일이 없습니다: $REF_ALL (data_hunt refman)"
for st in v1 wide; do
  pf=$(pin_rel "$st")
  [ -f "$pf" ] || die_fix "$pf 가 없습니다: 연구가 아직 고정되지 않았습니다"
  grep -q "  $REF\$" "$pf" || die_fix "$pf 에 자료 기준 파일($REF)이 들어 있지 않습니다"
  if picks_pinned "$st" && [ ! -f "$BASE/SELECT_RAN_$st" ]; then
    die_fix "$pf 에 이미 고른 것(picks) 줄이 있습니다. 이 서버에서 고르기 전이므로 있으면 안 됩니다 (받은 커밋 확인)"
  fi
  step="select"; picks_pinned "$st" && step="test"
  pin_check hunt "$st" "$step"
  sub "$st 고정 일치 (다음 단계: $step)"
done
if [ "$ALTPUMP" = 1 ]; then
  [ -f "$AP_PIN" ] || die_fix "$AP_PIN 이 없습니다: 알트 급등 연구가 아직 고정되지 않았습니다"
  if ap_pinned && [ ! -f "$BASE/SELECT_RAN_altpump" ]; then
    die_fix "$AP_PIN 에 이미 고른 것(pick) 줄이 있습니다. 이 서버에서 고르기 전이므로 있으면 안 됩니다"
  fi
  ap_data_check
  step="select"; ap_pinned && step="test"
  pin_check altpump - "$step"
  sub "알트 급등 고정 일치 (다음 단계: $step, 일봉 자료 sha256 일치)"
fi

# ------------------------------------------------------------------ 4 download 5m
stage 4 "바이낸스 공개 자료 받기 (30개 코인, 2020-01 ~ 2026-09, 5분봉·마크 가격·펀딩)"
if [ "$DRYRUN" = 1 ]; then
  sub "연습: 받기 건너뜀, 주어진 자료 사용: $DATA"
elif [ -f "$DATA/COMPLETE" ]; then
  sub "건너뜀: 이미 받았습니다"
else
  for k in 1 2 3; do
    "$PY" -m research.hunt.data_hunt download --kind 5m --out "$DATA" --workers "$WORKERS" >>"$LOG" 2>&1 && break
    [ -f "$DATA/COMPLETE" ] && break
    [ "$k" -lt 3 ] && { say "  받기가 다 끝나지 않아 빠진 것만 이어서 다시 합니다 (${k}/3)"; sleep "$RSLEEP"; }
  done
  if [ ! -f "$DATA/COMPLETE" ]; then
    pr=$("$PY" -m research.hunt.data_hunt problems --data "$DATA" 2>&1); echo "$pr" >> "$LOG"
    die_retry "자료 받기가 세 번 해도 끝나지 않았습니다: $(grep -E '^(PROBLEM|NOT BUILT)' <<<"$pr" | head -3 | tr '\n' ' ')"
  fi
fi
[ -f "$DATA/COMPLETE" ] || die_fix "자료 폴더가 완성되지 않았습니다: $DATA (COMPLETE 없음)"

# ------------------------------------------------------------------ 5 verify against the pinned references
stage 5 "받은 자료가 고정된 자료와 같은지 확인 (가격·거래량·펀딩·마크 가격, 숫자 하나라도 다르면 멈춤)"
"$PY" -m research.hunt.data_hunt verify --data "$DATA" --ref "$REF" --report "$BASE/verify_5m.json" >>"$LOG" 2>&1 \
  || die_fix "받은 자료가 고정된 자료와 다릅니다 ($(grep -E '^VERIFY' "$LOG" | tail -1)). 계산하지 않습니다"
sub "사냥이 읽는 값: $(grep -E '^VERIFY' "$LOG" | tail -1)"
"$PY" -m research.hunt.data_hunt verify --data "$DATA" --ref "$REF_ALL" --report "$BASE/verify_5m_allkeys.json" \
  >>"$LOG" 2>&1 || die_fix "받은 자료(마크 가격 포함)가 고정된 자료와 다릅니다 ($(grep -E '^VERIFY' "$LOG" | tail -1)). 계산하지 않습니다"
sub "모든 값(마크 가격 포함): $(grep -E '^VERIFY' "$LOG" | tail -1)"

# ------------------------------------------------------------------ 6 hunt: both selects before either test
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
PROCS=$NCPU
[ "${MEMG:-0}" -ge 1 ] && [ "$MEMG" -lt "$PROCS" ] && PROCS=$MEMG       # about 1 GB per worker at most
[ -n "${HUNT_PROCS:-}" ] && PROCS=$HUNT_PROCS
[ "$PROCS" -lt 1 ] && PROCS=1
mkdir -p "$PRIV"

hunt_select() {
  local st=$1
  if picks_pinned "$st"; then
    [ -s "research/hunt/out/$st/select.json" ] || warn "$st: 고른 것은 고정돼 있는데 select.json이 없습니다"
    sub "건너뜀: $st 고르기 (이미 끝나 고정됨)"; return 0
  fi
  touch "$BASE/SELECT_RAN_$st"
  sub "$st 고르기 (2021-01 ~ 2023-12)"
  "${HUNT[@]}" select --study "$st" --data "$DATA" --procs "$PROCS" --private "$PRIV" >>"$LOG" 2>&1 \
    || die "$st 고르기 실패 (run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
  picks_pinned "$st" || die "$st 고르기는 끝났는데 고른 것이 고정 파일에 없습니다"
}
hunt_test() {
  local st=$1 out=research/hunt/out/$1/test.json
  if [ -s "$out" ]; then sub "건너뜀: $st 시험 (이미 끝남)"; return 0; fi
  picks_pinned "$st" || die "$st 시험 전에 고르기가 고정돼 있어야 합니다"
  sub "$st 시험 (2024-01 ~ 2026-09, 한 번만)"
  "${HUNT[@]}" test --study "$st" --data "$DATA" --procs "$PROCS" --private "$PRIV" >>"$LOG" 2>&1 \
    || die "$st 시험 실패 (run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
  [ -s "$out" ] || die "$st 시험은 끝났는데 결과 파일($out)이 없습니다"
  TEST_RAN_HERE="$TEST_RAN_HERE $st"
}
ensure_reads_a() {           # reads_a (R1 goal board, R24 20/30/40x, continuous accounts) runs inside `hunt test --study wide`;
  local out=research/hunt/out/wide/reads_a.json   # a restart after test.json skips that step, so run the hook again
  [ -s research/hunt/out/wide/test.json ] || return 0
  [ -s "$out" ] && return 0
  case " $TEST_RAN_HERE " in
    *" wide "*) warn "목표판·20/30/40배 표(reads_a)가 시험 안에서 실패했습니다 (run.log의 [reads] 줄 참고; 같은 코드로 다시 해도 같으니 개발자에게 보내 주세요)"
                return 0 ;;
  esac
  sub "목표판·20/30/40배 표 (reads_a): 시험은 이미 끝났는데 파일이 없어 이어서 계산합니다 (몇 시간)"
  "${HUNT[@]}" reads --study wide --data "$DATA" --procs "$PROCS" --private "$PRIV" >>"$LOG" 2>&1 \
    || warn "목표판·20/30/40배 표(reads_a) 이어서 계산 실패 (run.log의 [reads] 줄 참고, 다른 결과는 그대로 묶습니다)"
  [ -s "$out" ] || warn "목표판·20/30/40배 표(reads_a.json)가 없습니다 (run.log의 [reads] 줄 참고)"
}

stage 6 "추세 사냥 계산 (v1·넓게 고르기 → 두 시험, 작업 ${PROCS}개 동시에)"
hunt_select v1
hunt_select wide
TEST_RAN_HERE=""
hunt_test v1
hunt_test wide
ensure_reads_a
for st in v1 wide; do
  "${HUNT[@]}" report --study "$st" >>"$LOG" 2>&1 || warn "$st 결과 페이지(RESULTS_KO.md) 쓰기 실패"
done

# ------------------------------------------------------------------ 7 alt pump
ap_incomplete() {            # the second pass did not finish: no verdict yet (PREREG_ALTPUMP 13, 15)
  echo "$1" > "$BASE/AP_PASS2_INCOMPLETE"
  warn "알트 급등: 5분봉 2차 확인이 끝나지 않음 ($1) → 1차 통과(PASS)는 아직 결과가 아닙니다 (미완성)"
}
ap_pass2() {
  local k
  rm -f "$BASE/AP_PASS2_INCOMPLETE"
  if [ -f "$BASE/AP_PASS2_DONE" ] || [ -s "$AP_OUT/pass2.json" ]; then
    [ -f "$BASE/AP_PASS2_DONE" ] || echo ran > "$BASE/AP_PASS2_DONE"
    sub "건너뜀: 알트 급등 5분봉 2차 확인 (이미 끝남)"; return 0
  fi
  sub "알트 급등 5분봉 2차 확인 (1차 통과가 있을 때만 자료를 받고 계산)"
  "${AP[@]}" pass2 plan >>"$LOG" 2>&1 || { ap_incomplete "2차 확인 계획(pass2 plan) 실패"; return 0; }
  local why="pass2 run 실패 (run.log 참고)" miss
  for k in 1 2 3 4; do
    [ "$(ap_files_total)" -gt 0 ] && sub "알트 급등 2차 자료 받기: $(ap_files_left)개 남음 (한 번에 2개씩, ${k}/4)"
    "${AP[@]}" pass2 fetch >>"$LOG" 2>&1         # files already in the cache are not fetched again
    if "${AP[@]}" pass2 run >>"$LOG" 2>&1; then
      if [ -s "$AP_OUT/pass2.json" ]; then echo ran > "$BASE/AP_PASS2_DONE"; else echo none > "$BASE/AP_PASS2_DONE"; fi
      return 0
    fi
    miss=$(tail -20 "$LOG" | grep -oE "[0-9]+ symbol-months with daily bars have no 5m klines" | tail -1)
    [ -n "$miss" ] || { why="pass2 run 실패 (run.log 마지막 부분 참고)"; break; }   # a retry does not help
    why="네 번 받아도 5분봉 파일이 빠짐: $miss"
    [ "$k" -lt 4 ] && { sub "빠진 5분봉 파일이 있어 다시 받습니다"; sleep $(( RSLEEP * 2 )); }
  done
  ap_incomplete "$why"
}

stage 7 "알트 급등 연구 (고르기 → 시험 → 목표판 → 5분봉 2차 확인 → 요약)"
rm -f "$BASE/AP_PASS2_INCOMPLETE"
if [ "$ALTPUMP" != 1 ]; then
  warn "알트 급등 연구는 이번에 돌리지 않았습니다 (ALTPUMP=0)"
else
  if ap_pinned; then sub "건너뜀: 알트 급등 고르기 (이미 끝나 고정됨)"
  else
    touch "$BASE/SELECT_RAN_altpump"
    sub "알트 급등 고르기"
    "${AP[@]}" select >>"$LOG" 2>&1 || die "알트 급등 고르기 실패 (tail -50 $LOG)"
    ap_pinned || die "알트 급등 고르기는 끝났는데 고른 것이 고정 파일에 없습니다"
  fi
  if [ -s "$AP_OUT/test.json" ]; then sub "건너뜀: 알트 급등 시험 (이미 끝남)"
  else
    sub "알트 급등 시험"
    "${AP[@]}" test >>"$LOG" 2>&1 || die "알트 급등 시험 실패 (tail -50 $LOG)"
  fi
  if [ -s "$AP_OUT/board.json" ]; then sub "건너뜀: 알트 급등 목표판 (이미 끝남)"
  else
    sub "알트 급등 목표판"
    "${AP[@]}" board >>"$LOG" 2>&1 || warn "알트 급등 목표판 실패 (통과 판정과는 관계없음)"
  fi
  ap_pass2
  "${AP[@]}" report >>"$LOG" 2>&1 || warn "알트 급등 요약(report.txt) 쓰기 실패"
fi

# ------------------------------------------------------------------ 8 fidelity (never stops the pack)
fidelity() {
  local help coins="" st c n pr rc
  help=$("${HUNT[@]}" --help 2>&1)
  if ! grep -qE "\{[a-z0-9_,]*fidelity[a-z0-9_,]*\}" <<<"$help"; then
    warn "정밀 재확인 명령(hunt fidelity)이 이 코드에 아직 없어 건너뛰었습니다"
    return 0
  fi
  if grep -q -- "--list-coins" <<<"$help"; then  # test.json keeps coins_traded for DeepSeek picks too (labels only)
    for st in v1 wide; do
      c=$("${HUNT[@]}" fidelity --study "$st" --list-coins --data "$DATA" --private "$PRIV" 2>>"$LOG") \
        || { warn "$st: 거래한 코인 목록을 못 받아 30개 코인 전부를 받습니다"; coins=""; break; }
      coins="$coins $c"
    done
  fi
  coins=$(tr ' ' '\n' <<<"$coins" | grep -E '^[A-Z0-9]+USDT$' | sort -u | tr '\n' ' ' | sed 's/ *$//')
  if [ -z "${coins// /}" ]; then               # no list: every coin of the universe
    coins=$("$PY" -m research.hunt.data_hunt symbols 2>>"$LOG" | head -1) \
      || { warn "코인 목록 실패: 정밀 재확인 건너뜀"; return 0; }
  fi
  n=$(wc -w <<<"$coins")
  sub "1분봉 받을 코인 ${n}개: $coins"
  if [ "$DRYRUN" = 1 ]; then
    sub "연습: 1분봉 받기 건너뜀 (주어진 폴더: $FID)"
  elif [ -f "$FID/COMPLETE" ] && [ "$(cat "$BASE/FID_COINS" 2>/dev/null)" = "$coins" ]; then
    sub "건너뜀: 1분봉 이미 받음"
  else
    echo "$coins" > "$BASE/FID_COINS"
    for k in 1 2 3; do
      "$PY" -m research.hunt.data_hunt download --kind fidelity --out "$FID" --symbols "$(tr ' ' ',' <<<"$coins")" \
        --from "$FID_FROM" --to "$FID_TO" --workers "$WORKERS" >>"$LOG" 2>&1 && break
      [ "$k" -lt 3 ] && sleep "$RSLEEP"
    done
  fi
  if [ ! -f "$FID/COMPLETE" ]; then
    pr=$("$PY" -m research.hunt.data_hunt problems --data "$FID" 2>&1); rc=$?
    echo "$pr" >> "$LOG"
    if [ "$rc" != 1 ]; then
      warn "1분봉 받기가 끝나지 않아(받지 못한 코인 있음) 정밀 재확인을 건너뛰었습니다"; return 0
    fi
    warn "정밀 재확인: 1분봉 자료에서 세 번 받아도 안 된 파일 (그 부분은 빠진 채 계산, 볼 때 감안): $(grep '^PROBLEM' <<<"$pr" | sed 's/^PROBLEM //' | tr '\n' ' ' | sed 's/ *$//')"
  fi
  local fidarg=()
  grep -q -- "--fid" <<<"$help" && fidarg=(--fid "$FID")
  for st in v1 wide; do
    if [ -s "research/hunt/out/$st/fidelity.json" ]; then sub "건너뜀: $st 정밀 재확인 (이미 끝남)"; continue; fi
    sub "$st 정밀 재확인 (1분봉·마크 가격)"
    HUNT_FID="$FID" "${HUNT[@]}" fidelity --study "$st" --data "$DATA" "${fidarg[@]}" --procs "$PROCS" \
      --private "$PRIV" >>"$LOG" 2>&1 || warn "$st 정밀 재확인 실패 (다른 결과는 그대로 묶습니다)"
  done
}
owner_reads() {              # PREREG_HUNT_WIDE 7.4a (O1 weekend version on all four timeframes, O1b, O2, O4, O5), pinned before the test
  local out=research/hunt/out/wide/reads_o.json
  if [ -s "$out" ]; then sub "건너뜀: 추가 분석 (이미 끝남)"; return 0; fi
  [ -f research/hunt/reads_o.py ] || { warn "추가 분석(주말 뺀 버전 등): reads_o.py 없음"; return 0; }
  [ -s research/hunt/out/wide/test.json ] || { warn "추가 분석(주말 뺀 버전 등): 넓게 시험 결과가 없어 건너뜀"; return 0; }
  sub "추가 분석: 주말 뺀 버전(4개 봉)·롱만·FOMC/고용지표 시간 피하기·모멘텀 비교 (7.4a)"
  timeout "${HUNT_READS_O_HOURS:-5}h" "${READS_O[@]}" --study wide --data "$DATA" --private "$PRIV" --procs "$PROCS" \
    >>"$LOG" 2>&1 || warn "추가 분석(주말 뺀 버전 등)이 끝나지 않음 (run.log 참고, 다른 결과는 그대로 묶습니다)"
}

stage 8 "정밀 재확인 (고른 것이 거래한 코인만 1분봉·마크 가격으로 다시) + 추가 분석 (주말 뺀 버전 등)"
fidelity || warn "정밀 재확인 단계에서 예상 못 한 오류 (다른 결과는 그대로 묶습니다)"
owner_reads

# ------------------------------------------------------------------ 9 pack
ap_line() {
  if [ "$ALTPUMP" != 1 ]; then echo "알트 급등: 이번에 돌리지 않음 (ALTPUMP=0)"
  elif [ -f "$BASE/AP_PASS2_INCOMPLETE" ]; then
    echo "알트 급등: **5분봉 2차 확인 없음 → 1차 통과(PASS)는 결과가 아닙니다 (미완성, PREREG_ALTPUMP 13·15)**: $(cat "$BASE/AP_PASS2_INCOMPLETE")"
  elif [ "$(cat "$BASE/AP_PASS2_DONE" 2>/dev/null)" = ran ]; then echo "알트 급등: 5분봉 2차 확인까지 끝 (altpump/pass2.json)"
  else echo "알트 급등: 1차에서 통과한 것이 없어 5분봉 2차 확인이 필요 없었음"
  fi
}
pack() {
  local R=$BASE/results
  rm -rf "$R"
  mkdir -p "$R/hunt" "$R/altpump" "$R/pins" "$R/data" "$R/stamps" || return 1
  for st in v1 wide; do [ -d "research/hunt/out/$st" ] && cp -r "research/hunt/out/$st" "$R/hunt/"; done
  [ -d "$AP_OUT" ] && tar cf - --exclude=./pass2_cache -C "$AP_OUT" . | tar xf - -C "$R/altpump"
  cp research/hunt/PREREG_HUNT.sha256 research/hunt/PREREG_HUNT_WIDE.sha256 "$R/pins/" || return 1
  [ -f "$AP_PIN" ] && cp "$AP_PIN" "$R/pins/"
  cp "$DATA/manifest.json" "$R/data/manifest_5m.json" || return 1
  cp "$BASE/verify_5m.json" "$BASE/verify_5m_allkeys.json" "$REF" "$REF_ALL" "$R/data/" || return 1
  [ -f "$FID/manifest.json" ] && cp "$FID/manifest.json" "$R/data/manifest_fidelity_1m.json"
  "$PY" - "$R/stamps/code_stamp.json" "$BASE" "$PRIV" "$NCPU" "$PROCS" "$DRYRUN" <<'PYEOF' >>"$LOG" 2>&1 || return 1
import glob, hashlib, json, os, platform, subprocess, sys, time
out, base, priv, ncpu, procs, dry = sys.argv[1:7]
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
def git(*a):
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return None
pats = ["research/hunt/*.py", "research/hunt/*.sh", "research/hunt/*.md", "research/hunt/*.sha256",
        "research/hunt/*.json", "research/altpump/*.py", "research/altpump/*.md", "research/altpump/*.sha256",
        "data/universe/*", "tests/test_hunt*.py", "tests/test_data_hunt.py", "tests/test_altpump.py"]
files = sorted({p for pat in pats for p in glob.glob(pat) if os.path.isfile(p)})
stages = []
try:
    rows = [l.rstrip("\n").split("|") for l in open(os.path.join(base, "STAGES")) if l.strip()]
    for i, (n, name, t) in enumerate(rows):
        t1 = int(rows[i + 1][2]) if i + 1 < len(rows) else int(time.time())
        stages.append({"stage": int(n), "name": name, "start_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(t))),
                       "minutes": round((t1 - int(t)) / 60, 1)})
except Exception as e:
    stages = [f"unreadable: {e!r}"]
vers = {}
for m in ("numpy", "pandas", "numba", "scipy", "pytest"):
    try:
        vers[m] = __import__(m).__version__
    except Exception:
        vers[m] = None
mem = None
try:
    mem = [l for l in open("/proc/meminfo") if l.startswith("MemTotal")][0].split()[1] + " kB"
except Exception:
    pass
settings = {}
try:
    settings = dict(l.rstrip("\n").split("=", 1) for l in open(os.path.join(base, "settings.env")) if "=" in l)
except Exception:
    pass
priv_files = {}
for p in sorted(glob.glob(os.path.join(priv, "**", "*"), recursive=True)):
    if os.path.isfile(p):
        priv_files[os.path.relpath(p, priv)] = sha(p)          # names and sha256 only: the figures stay off (D11)
stamp = {"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "dry_run": dry == "1",
         "git": {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                 "status_porcelain": git("status", "--porcelain")},
         "settings": settings, "files_sha256": {p: sha(p) for p in files}, "python": sys.version, "packages": vers,
         "machine": {"nproc": int(ncpu), "procs_used": int(procs), "mem": mem, "platform": platform.platform()},
         "stages": stages, "private_files_sha256": priv_files,
         "private_note": "DeepSeek money figures (D11) stay in the private folder on the server (private.tgz), not here"}
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(stamp, open(out, "w"), indent=1)
print("stamp written", out)
PYEOF
  grep -v -E "\[data [0-9]+/[0-9]+\]|: [0-9]+/[0-9]+ files, free " "$LOG" > "$R/run.log"
  [ -s "$BASE/WARNINGS" ] && cp "$BASE/WARNINGS" "$R/WARNINGS.txt"
  {
    echo "# 결과 묶음 (bootstrap.sh $(date -u '+%Y-%m-%d %H:%M UTC'), 커밋 ${HEAD:0:10})"
    echo
    echo "* $(ap_line)"
    if [ -s "$BASE/WARNINGS" ]; then echo "* 건너뛰거나 빠진 것이 있습니다: WARNINGS.txt"; else echo "* 건너뛴 것 없음"; fi
    echo
    echo "* hunt/v1, hunt/wide: 추세 사냥 출력 (select, pick(s), test, RESULTS_KO.md, fidelity가 있으면 fidelity.json)"
    echo "* hunt/wide/reads_o.json: 추가 분석 (주말 뺀 버전 4개 봉, 롱만, FOMC/고용지표 시간, 모멘텀 비교; 7.4a)"
    echo "* altpump: 알트 급등 출력 (pass2_cache 제외)"
    echo "* pins: 고정 파일 (고르기 뒤 picks 줄이 붙은 것)"
    echo "* data: 받은 자료 목록(manifest), 고정 기준 두 개와의 비교(verify_5m.json, verify_5m_allkeys.json), 1분봉 목록"
    echo "* stamps/code_stamp.json: 코드 커밋, 설정, 파일 sha256, 패키지 버전, 단계별 시간, 비공개 파일 sha256(내용 없음)"
    echo "* run.log, WARNINGS.txt(건너뛴 것)"
    echo
    echo "딥시크 돈 숫자(D11)는 여기 없습니다: 서버의 $PRIV (private.tgz)에만 있습니다."
  } > "$R/README_KO.md"
  case "$PRIV" in "$R"|"$R"/*) return 1 ;; esac
  tar czf "$BASE/results.tgz" -C "$BASE" results || return 1
  if [ -d "$PRIV" ] && [ -n "$(ls -A "$PRIV" 2>/dev/null)" ]; then
    tar czf "$BASE/private.tgz" -C "$(dirname "$PRIV")" "$(basename "$PRIV")" || return 1
  fi
  return 0
}
stage 9 "결과 묶기"
pack || die "결과 묶기 실패 (tail -50 $LOG)"
rm -f "$BASE/RUNNING"
if [ -f "$BASE/AP_PASS2_INCOMPLETE" ]; then
  incomplete_msg | while IFS= read -r line; do say "$line"; done
  exit 1
fi
touch "$BASE/DONE"
say "끝. 결과 $(du -h "$BASE/results.tgz" | cut -f1): $BASE/results.tgz"
if [ -s "$BASE/WARNINGS" ]; then say "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS" | tee -a "$LOG"; fi
say "보내기: bash $SELF push   (그다음 Vultr에서 서버 Destroy)"
