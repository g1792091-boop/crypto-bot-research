#!/usr/bin/env bash
# 추세 사냥(v1 + 넓게) · 알트 급등 연구 · 1분봉 정밀 재확인을 빌린 계산 서버에서 돌립니다 (research/hunt/SERVER_KO.md).
# 바이낸스 공개 가격 자료만 씁니다: 거래소 키·AI 키 없음, 규칙봇·데모봇·후보 리그와 관계없음.
#
#   bash bootstrap.sh          설치 → 자체 점검 → 고정 확인 → 자료 받기 → 자료 확인 → 추세 사냥 → 알트 급등
#                              → 정밀 재확인 → 결과 묶기 (tmux 안에서 돌리세요)
#   bash bootstrap.sh status   지금 단계와 남은 시간(어림)
#   bash bootstrap.sh push     결과를 GitHub(브랜치 hunt-results)로 보냄. 토큰은 한 번만 물어봄
#
# 모든 단계는 이미 끝난 것을 건너뜁니다: 멈추거나 재부팅된 뒤 같은 명령이 이어서 합니다.
# 딥시크 돈 숫자(D11)는 저장소 밖 $BASE/private 에만 있고 results.tgz 에는 들어가지 않습니다.
#
# 연습(가짜 자료, 설치·받기·보내기 없음):
#   DRYRUN=1 HUNT_BASE=<빈 폴더> HUNT_REPO=<코드 사본> HUNT_DATA=<5m 자료 폴더> [HUNT_FID=<1m 폴더>] \
#     [HUNT_PY=python3] [HUNT_CMD=..] [ALTPUMP_CMD=..] [HUNT_SELFCHECK_TESTS=..] bash bootstrap.sh --dry-run
set -uo pipefail

MODE=run
DRYRUN=${DRYRUN:-0}
for a in "$@"; do
  case "$a" in
    --dry-run) DRYRUN=1 ;;
    run|status|push) MODE=$a ;;
    *) echo "사용법: bash bootstrap.sh [run|status|push] [--dry-run]"; exit 2 ;;
  esac
done

BASE=${HUNT_BASE:-/root/hunt}
REPO=${HUNT_REPO:-$BASE/crypto-bot-research}
DATA=${HUNT_DATA:-$BASE/data5m}
FID=${HUNT_FID:-$BASE/fid1m}
PRIV=${HUNT_PRIVATE:-$BASE/private}
VENV=$BASE/venv
LOG=$BASE/run.log
REF=${HUNT_DATA_REF:-research/hunt/data_ref_5m.json}     # the pinned array-content reference of the 5m data
FID_FROM=${HUNT_FID_FROM:-2024-01}
FID_TO=${HUNT_FID_TO:-2026-09}
WORKERS=${HUNT_WORKERS:-8}
ALTPUMP=${ALTPUMP:-1}
TESTS=${HUNT_SELFCHECK_TESTS:-tests/test_hunt.py tests/test_hunt_entries.py tests/test_data_hunt.py tests/test_altpump.py}
if [ "$DRYRUN" = 1 ]; then PY=${HUNT_PY:-python3}; else PY=${HUNT_PY:-$VENV/bin/python}; fi
if [ -n "${HUNT_CMD:-}" ]; then read -r -a HUNT <<<"$HUNT_CMD"; else HUNT=("$PY" -m research.hunt.hunt); fi
if [ -n "${ALTPUMP_CMD:-}" ]; then read -r -a AP <<<"$ALTPUMP_CMD"; else AP=("$PY" research/altpump/altpump.py); fi
NCPU=$(env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc)    # nproc obeys OMP_NUM_THREADS, set to 1 below
SELF=$REPO/research/hunt/bootstrap.sh
NST=9
RESTART="tmux kill-session -t hunt 2>/dev/null; tmux new -s hunt \"bash $SELF; bash\""
[ "$DRYRUN" = 1 ] && RESTART="DRYRUN=1 HUNT_BASE=$BASE HUNT_REPO=$REPO HUNT_DATA=$DATA bash $SELF --dry-run"
mkdir -p "$BASE"

say() { echo "[$(date -u '+%m-%d %H:%M UTC')] $*" | tee -a "$LOG"; }
die() { say "멈춤: $*"; say "이 화면을 그대로 복사해 개발자에게 보내 주세요."; exit 1; }
sub() { say "  · $*"; }
warn() {                     # something skipped that does not stop the run (listed again at the end)
  say "  · 참고: $*"
  grep -qxF "$*" "$BASE/WARNINGS" 2>/dev/null || echo "$*" >> "$BASE/WARNINGS"
}

# minutes per stage on a 32 vCPU server (stage 6 shrinks with more CPUs; downloads do not)
est_min() {
  case $1 in
    1) echo 4 ;; 2) echo 4 ;; 3) echo 1 ;; 4) echo 15 ;; 5) echo 1 ;;
    6) echo $(( 15 + 20 * 32 / NCPU )) ;; 7) echo 10 ;; 8) echo 30 ;; 9) echo 1 ;; *) echo 0 ;;
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

status() {
  if [ -f "$BASE/DONE" ]; then
    echo "끝났습니다. 결과: $BASE/results.tgz  (보내기: bash $SELF push)"
    if [ -s "$BASE/WARNINGS" ]; then echo "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS"; fi
    return
  fi
  if ! running; then
    echo "지금 돌고 있지 않습니다. 마지막 기록:"
    grep -E "멈춤|\] [0-9]/$NST " "$LOG" 2>/dev/null | tail -3
    echo "이어서 하려면: $RESTART"
    return
  fi
  local n=0 name="설치 중" t0 el left
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
  esac
}

push() {
  [ "$DRYRUN" = 1 ] && { echo "연습 모드에서는 보내지 않습니다."; return 1; }
  [ -f "$BASE/results.tgz" ] || die "결과 파일이 아직 없습니다."
  cd "$REPO" || exit 1
  git config user.email "hunt@localhost"; git config user.name "hunt server"
  git config credential.helper store
  local br=hunt-results
  if git rev-parse -q --verify "refs/heads/$br" >/dev/null; then
    git checkout -q "$br" || die "브랜치 $br 로 바꾸지 못했습니다"
  else
    git checkout -q -b "$br" || die "브랜치 $br 를 만들지 못했습니다"
  fi
  rm -rf research/hunt/results
  tar xzf "$BASE/results.tgz" -C research/hunt || die "결과 풀기 실패"            # -> research/hunt/results/
  git add -f research/hunt/results
  git commit -q -m "Hunt v1 + wide, alt pump, fidelity: results ($(hostname), $(date -u +%F))" \
    || say "새로 올릴 변경이 없습니다 (이미 커밋됨)"
  echo "GitHub 아이디와, 비밀번호 자리에 쓰기 토큰(Contents: Read and write)을 넣으세요. (한 번만 묻습니다)"
  if git push -u origin "$br"; then say "보냈습니다: 브랜치 $br"; return 0; fi
  local br2; br2="hunt-results-$(date -u +%Y%m%d-%H%M)"
  say "같은 이름의 브랜치가 이미 있어 $br2 로 보냅니다"
  git push -u origin "HEAD:refs/heads/$br2" && { say "보냈습니다: 브랜치 $br2"; return 0; }
  die "올리기 실패 (토큰 권한이 Contents: Read and write 인지 확인)"
}

case "$MODE" in
  status) status; exit 0 ;;
  push) push; exit $? ;;
esac

for k in 1 2 3 4 5; do running || break; sleep 2; done      # a restart: let the old run finish dying
running && { echo "이미 돌고 있습니다. 화면 보기: tmux attach -t hunt   (진행: bash $SELF status)"; exit 1; }
if [ -f "$BASE/DONE" ]; then
  echo "이미 끝났습니다: $BASE/results.tgz  (보내기: bash $SELF push; 처음부터 다시 묶으려면 rm $BASE/DONE)"
  exit 0
fi
echo $$ > "$BASE/RUNNING"
[ "$DRYRUN" = 1 ] && say "연습 모드 (DRYRUN): 설치·자료 받기·보내기는 하지 않습니다"

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
  [ -n "$ok" ] || die "apt 설치가 10분 넘게 막혀 있습니다. 몇 분 뒤 같은 명령을 다시 실행하세요."
  rm -rf "$VENV"
  python3 -m venv "$VENV" || die "venv 만들기 실패"
  "$VENV/bin/pip" install -q --upgrade pip >>"$LOG" 2>&1
  # the versions the coins30 data, the hunt and the alt pump code were built and tested with
  "$VENV/bin/pip" install -q "numpy==2.0.2" "pandas==2.3.3" "numba==0.60.0" "scipy>=1.11" "pytest>=8" >>"$LOG" 2>&1 \
    || die "패키지 설치 실패"
  "$PY" -c "import numba, numpy, pandas; print('numpy', numpy.__version__, 'pandas', pandas.__version__, 'numba', numba.__version__)" \
    >>"$LOG" 2>&1 || die "numba를 불러오지 못했습니다"
  touch "$BASE/INSTALLED"
fi
cd "$REPO" || die "코드 폴더가 없습니다: $REPO"
HEAD=$(git rev-parse HEAD 2>/dev/null || echo nogit)
FREEG=$(df -BG --output=avail "$BASE" | tail -1 | tr -dc '0-9')
MEMG=$(free -g | awk '/Mem/{print $2}')
say "코드 ${HEAD:0:10}, CPU ${NCPU}개, 메모리 ${MEMG}GB, 디스크 여유 ${FREEG}GB"
[ "$DRYRUN" = 1 ] || [ "${FREEG:-0}" -ge 20 ] || [ -f "$DATA/COMPLETE" ] \
  || die "디스크 여유가 20GB보다 적습니다(${FREEG}GB). 더 큰 서버를 쓰세요."

# ------------------------------------------------------------------ 2 self-check
stage 2 "자체 점검 (시험 코드, 몇 분 동안 조용한 게 정상)"
KEY="$HEAD|$TESTS"
if [ "$(cat "$BASE/CHECKED" 2>/dev/null)" != "$KEY" ]; then
  read -r -a TL <<<"$TESTS"
  "$PY" -m pytest -q -x -p no:cacheprovider "${TL[@]}" >>"$LOG" 2>&1 \
    || die "자체 점검 실패 (run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
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
  [ "$rc" = 0 ] || die "$what 고정 확인 거부: $(echo "$out" | tail -1)"
}

stage 3 "고정 파일 확인 (사전 등록·코드·자료 기준이 고정된 그대로인지)"
for st in v1 wide; do
  pf=$(pin_rel "$st")
  [ -f "$pf" ] || die "$pf 가 없습니다: 연구가 아직 고정되지 않았습니다 (개발자가 고정한 뒤 다시 실행)"
  grep -q "  $REF\$" "$pf" || die "$pf 에 자료 기준 파일($REF)이 들어 있지 않습니다"
  step="select"; picks_pinned "$st" && step="test"
  pin_check hunt "$st" "$step"
  sub "$st 고정 일치 (다음 단계: $step)"
done
[ -f "$REF" ] || die "자료 기준 파일이 없습니다: $REF"
if [ "$ALTPUMP" = 1 ]; then
  [ -f "$AP_PIN" ] || die "$AP_PIN 이 없습니다: 알트 급등 연구가 아직 고정되지 않았습니다 (빼고 돌리려면 ALTPUMP=0)"
  step="select"; ap_pinned && step="test"
  pin_check altpump - "$step"
  sub "알트 급등 고정 일치 (다음 단계: $step)"
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
    say "  받기가 다 끝나지 않아 이어서 다시 합니다 (${k}/3)"; sleep 30
  done
  [ -f "$DATA/COMPLETE" ] || die "자료 받기 실패 (세 번 해도 빠진 코인이 있습니다)"
fi

# ------------------------------------------------------------------ 5 verify against the pinned reference
stage 5 "받은 자료가 고정된 자료와 같은지 확인 (숫자 하나라도 다르면 멈춤)"
"$PY" -m research.hunt.data_hunt verify --data "$DATA" --ref "$REF" --report "$BASE/verify_5m.json" >>"$LOG" 2>&1 \
  || die "받은 자료가 고정된 자료와 다릅니다 ($(grep -E '^VERIFY' "$LOG" | tail -1)). 계산하지 않습니다"
sub "$(grep -E '^VERIFY' "$LOG" | tail -1)"

# ------------------------------------------------------------------ 6 hunt: both selects before either test
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
PROCS=$NCPU
[ "${MEMG:-0}" -ge 1 ] && [ "$MEMG" -lt "$PROCS" ] && PROCS=$MEMG       # about 1 GB per worker at most
[ -n "${HUNT_PROCS:-}" ] && PROCS=$HUNT_PROCS
[ "$PROCS" -lt 1 ] && PROCS=1
mkdir -p "$PRIV"

hunt_select() {
  local st=$1
  if picks_pinned "$st"; then sub "건너뜀: $st 고르기 (이미 끝나 고정됨)"; return 0; fi
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
}

stage 6 "추세 사냥 계산 (v1·넓게 고르기 → 두 시험, 작업 ${PROCS}개 동시에)"
hunt_select v1
hunt_select wide
hunt_test v1
hunt_test wide
for st in v1 wide; do
  "${HUNT[@]}" report --study "$st" >>"$LOG" 2>&1 || warn "$st 결과 페이지(RESULTS_KO.md) 쓰기 실패"
done

# ------------------------------------------------------------------ 7 alt pump
stage 7 "알트 급등 연구 (고르기 → 시험 → 목표판 → 5분봉 2차 확인 → 요약)"
if [ "$ALTPUMP" != 1 ]; then
  warn "알트 급등 연구는 이번에 돌리지 않았습니다 (ALTPUMP=0)"
else
  if ap_pinned; then sub "건너뜀: 알트 급등 고르기 (이미 끝나 고정됨)"
  else
    sub "알트 급등 고르기"
    "${AP[@]}" select >>"$LOG" 2>&1 || die "알트 급등 고르기 실패 (tail -50 $LOG)"
    ap_pinned || die "알트 급등 고르기는 끝났는데 고른 것이 고정 파일에 없습니다"
  fi
  if [ -s research/altpump/out/test.json ]; then sub "건너뜀: 알트 급등 시험 (이미 끝남)"
  else
    sub "알트 급등 시험"
    "${AP[@]}" test >>"$LOG" 2>&1 || die "알트 급등 시험 실패 (tail -50 $LOG)"
  fi
  if [ -s research/altpump/out/board.json ]; then sub "건너뜀: 알트 급등 목표판 (이미 끝남)"
  else
    sub "알트 급등 목표판"
    "${AP[@]}" board >>"$LOG" 2>&1 || warn "알트 급등 목표판 실패 (통과 판정과는 관계없음)"
  fi
  if [ -f "$BASE/AP_PASS2_DONE" ]; then sub "건너뜀: 알트 급등 5분봉 2차 확인 (이미 끝남)"
  else
    sub "알트 급등 5분봉 2차 확인 (통과한 것이 있을 때만 받고 계산)"
    if "${AP[@]}" pass2 plan >>"$LOG" 2>&1 && "${AP[@]}" pass2 fetch >>"$LOG" 2>&1 \
        && "${AP[@]}" pass2 run >>"$LOG" 2>&1; then
      touch "$BASE/AP_PASS2_DONE"
    else
      warn "알트 급등 5분봉 2차 확인 실패 (1차 결과는 그대로 묶습니다)"
    fi
  fi
  "${AP[@]}" report >>"$LOG" 2>&1 || warn "알트 급등 요약(report.txt) 쓰기 실패"
fi

# ------------------------------------------------------------------ 8 fidelity (never stops the pack)
fidelity() {
  local help coins="" st c n
  help=$("${HUNT[@]}" --help 2>&1)
  if ! grep -qE "\{[a-z0-9_,]*fidelity[a-z0-9_,]*\}" <<<"$help"; then
    warn "정밀 재확인 명령(hunt fidelity)이 이 코드에 아직 없어 건너뛰었습니다"
    return 0
  fi
  if grep -q -- "--list-coins" <<<"$help"; then
    for st in v1 wide; do
      c=$("${HUNT[@]}" fidelity --study "$st" --list-coins --data "$DATA" --private "$PRIV" 2>>"$LOG") \
        || { warn "$st: 거래한 코인 목록을 못 받아 전체 코인을 씁니다"; coins=""; break; }
      coins="$coins $c"
    done
  fi
  coins=$(tr ' ' '\n' <<<"$coins" | grep -E '^[A-Z0-9]+USDT$' | sort -u | tr '\n' ' ')
  if [ -z "${coins// /}" ]; then
    coins=$("$PY" -m research.hunt.data_hunt coins --tests research/hunt/out/v1/test.json \
            research/hunt/out/wide/test.json 2>>"$LOG") || { warn "코인 목록 실패: 정밀 재확인 건너뜀"; return 0; }
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
      sleep 30
    done
    [ -f "$FID/COMPLETE" ] || { warn "1분봉 받기가 끝나지 않아 정밀 재확인을 건너뛰었습니다"; return 0; }
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
stage 8 "정밀 재확인 (고른 것이 거래한 코인만 1분봉·마크 가격으로 다시)"
fidelity || warn "정밀 재확인 단계에서 예상 못 한 오류 (다른 결과는 그대로 묶습니다)"

# ------------------------------------------------------------------ 9 pack
pack() {
  local R=$BASE/results
  rm -rf "$R"
  mkdir -p "$R/hunt" "$R/altpump" "$R/pins" "$R/data" "$R/stamps" || return 1
  for st in v1 wide; do [ -d "research/hunt/out/$st" ] && cp -r "research/hunt/out/$st" "$R/hunt/"; done
  [ -d research/altpump/out ] && tar cf - --exclude=./pass2_cache -C research/altpump/out . | tar xf - -C "$R/altpump"
  cp research/hunt/PREREG_HUNT.sha256 research/hunt/PREREG_HUNT_WIDE.sha256 "$R/pins/" || return 1
  [ -f "$AP_PIN" ] && cp "$AP_PIN" "$R/pins/"
  cp "$DATA/manifest.json" "$R/data/manifest_5m.json" || return 1
  cp "$BASE/verify_5m.json" "$REF" "$R/data/" || return 1
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
        "tests/test_hunt*.py", "tests/test_data_hunt.py", "tests/test_altpump.py"]
files = sorted({p for pat in pats for p in glob.glob(pat)})
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
priv_files = {}
for p in sorted(glob.glob(os.path.join(priv, "**", "*"), recursive=True)):
    if os.path.isfile(p):
        priv_files[os.path.relpath(p, priv)] = sha(p)          # names and sha256 only: the figures stay off (D11)
stamp = {"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "dry_run": dry == "1",
         "git": {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                 "status_porcelain": git("status", "--porcelain")},
         "files_sha256": {p: sha(p) for p in files}, "python": sys.version, "packages": vers,
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
    echo "# 결과 묶음 (bootstrap.sh $(date -u '+%Y-%m-%d %H:%M UTC'))"
    echo
    echo "* hunt/v1, hunt/wide: 추세 사냥 출력 (select, pick(s), test, RESULTS_KO.md, fidelity가 있으면 fidelity.json)"
    echo "* altpump: 알트 급등 출력 (pass2_cache 제외)"
    echo "* pins: 고정 파일 (고르기 뒤 picks 줄이 붙은 것)"
    echo "* data: 받은 자료 목록(manifest), 고정 기준과의 비교(verify_5m.json), 1분봉 목록"
    echo "* stamps/code_stamp.json: 코드 커밋, 파일 sha256, 패키지 버전, 단계별 시간, 비공개 파일 sha256(내용 없음)"
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
touch "$BASE/DONE"; rm -f "$BASE/RUNNING"
say "끝. 결과 $(du -h "$BASE/results.tgz" | cut -f1): $BASE/results.tgz"
if [ -s "$BASE/WARNINGS" ]; then say "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS" | tee -a "$LOG"; fi
say "보내기: bash $SELF push   (그다음 Vultr에서 서버 Destroy)"
