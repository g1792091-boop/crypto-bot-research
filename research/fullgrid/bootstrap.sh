#!/usr/bin/env bash
# Full-grid custom-value study on a rented compute server (research/fullgrid/SERVER_KO.md).
# Public price data only: no exchange key, nothing of the paper bot or the demo bot.
#
#   bash bootstrap.sh          install, self-check, download, compute, report, pack (run it inside tmux)
#   bash bootstrap.sh status   one line: where it is and how long is left
#   bash bootstrap.sh push     send the results to GitHub (branch fullgrid-results), asks for a token once
#
# Every step skips what is already done, so after a stop or a reboot the same command continues.
set -uo pipefail
BASE=/root/fg
REPO=$BASE/crypto-bot-research
DATA=$BASE/data
OUT=$BASE/out
VENV=$BASE/venv
LOG=$BASE/run.log
PY=$VENV/bin/python
mkdir -p "$BASE"

say() { echo "[$(date -u '+%m-%d %H:%M UTC')] $*" | tee -a "$LOG"; }
die() { say "멈춤: $*"; say "이 화면을 그대로 복사해 개발자에게 보내 주세요."; exit 1; }

RESTART="tmux kill-session -t fg 2>/dev/null; tmux new -s fg \"bash $REPO/research/fullgrid/bootstrap.sh; bash\""

running() {          # the run's own process (RUNNING holds its pid), or a step it left behind
  local p; p=$(cat "$BASE/RUNNING" 2>/dev/null)
  { [ -n "$p" ] && kill -0 "$p" 2>/dev/null && grep -qa bootstrap.sh "/proc/$p/cmdline" 2>/dev/null; } \
    || pgrep -f "[f]ullgrid/(run|data)\.py|[t]ests/test_fullgrid" >/dev/null
}

status() {
  if [ -f "$BASE/DONE" ]; then
    echo "끝났습니다. 결과: $BASE/results.tgz  (보내기: bash $REPO/research/fullgrid/bootstrap.sh push)"; return
  fi
  if ! running; then
    echo "지금 돌고 있지 않습니다. 마지막 기록:"; grep -E "멈춤|\] [0-9]/6" "$LOG" 2>/dev/null | tail -3
    echo "이어서 하려면: $RESTART"
    return
  fi
  local step; step=$(grep -E "\] [0-9]/6 " "$LOG" 2>/dev/null | tail -1)
  echo "진행 중: ${step:-설치 중}"
  tail -1 "$LOG" 2>/dev/null | grep -q "exchange.json)를 기다립니다" && echo "  지금은 레버리지 구간 표를 기다리는 중입니다 (0번)."
  case "$step" in
    *"4/6"*) local last; last=$(grep -E '^\[(outcomes|grid) [0-9]+/' "$LOG" 2>/dev/null | tail -1)
             [ -n "$last" ] && echo "  ${last%%: *}" ;;
  esac
}

push() {
  [ -f "$BASE/results.tgz" ] || die "결과 파일이 아직 없습니다."
  cd "$REPO" || exit 1
  git config user.email "fullgrid@localhost"; git config user.name "fullgrid server"
  git config credential.helper store
  local br="fullgrid-results-$(date -u +%Y%m%d-%H%M)"
  git checkout -q -b "$br"
  mkdir -p research/fullgrid/results
  tar xzf "$BASE/results.tgz" -C research/fullgrid/results
  git add -f research/fullgrid/results
  git commit -q -m "Full-grid study results ($(hostname), $(date -u +%F))"
  echo "GitHub 아이디와, 비밀번호 자리에 쓰기 토큰(Contents: Read and write)을 넣으세요."
  git push -u origin "$br" && say "보냈습니다: 브랜치 $br" || die "올리기 실패"
}

case "${1:-run}" in
  run) shift || true ;;
  status) status; exit 0 ;;
  push) push; exit 0 ;;
  *) echo "사용법: bash bootstrap.sh [run|status|push]"; exit 2 ;;
esac

for k in 1 2 3 4 5; do running || break; sleep 2; done      # a restart: let the old run finish dying
running && { echo "이미 돌고 있습니다. 화면 보기: tmux attach -t fg"; exit 1; }
echo $$ > "$BASE/RUNNING"

say "1/6 설치 (파이썬 패키지)"
export DEBIAN_FRONTEND=noninteractive
if [ ! -f "$BASE/INSTALLED" ]; then
  ok=""
  for k in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if apt-get update -y >>"$LOG" 2>&1 && apt-get install -y python3-venv python3-pip git tmux >>"$LOG" 2>&1; then
      ok=1; break
    fi
    say "다른 설치(자동 업데이트)가 끝나기를 기다립니다 (${k}/20)"; sleep 30
  done
  [ -n "$ok" ] || die "apt 설치가 10분 넘게 막혀 있습니다. 몇 분 뒤 같은 명령을 다시 실행하세요."
  rm -rf "$VENV"
  python3 -m venv "$VENV" || die "venv 만들기 실패"
  "$VENV/bin/pip" install -q --upgrade pip >>"$LOG" 2>&1
  "$VENV/bin/pip" install -q "numpy==2.0.2" "pandas==2.3.3" "scipy>=1.11" "numba==0.60.0" "pytest>=8" >>"$LOG" 2>&1 \
    || die "패키지 설치 실패"
  "$PY" -c "import numba, numpy, pandas; print('numba', numba.__version__)" >>"$LOG" 2>&1 || die "numba를 불러오지 못했습니다"
  touch "$BASE/INSTALLED"
fi
cd "$REPO" || die "코드 폴더가 없습니다: $REPO"
FREEG=$(df -BG --output=avail "$BASE" | tail -1 | tr -dc '0-9')
USEDG=$(du -s -BG "$DATA" "$OUT" 2>/dev/null | awk '{s += $1} END {print s + 0}')    # this study's own files so far
say "코드 $(git rev-parse --short HEAD), CPU $(nproc)개, 메모리 $(free -g | awk '/Mem/{print $2}')GB, 디스크 여유 ${FREEG}GB (이미 받은 것 ${USEDG}GB)"
[ $(( ${FREEG:-0} + USEDG )) -ge 60 ] || [ -f "$BASE/DONE" ] || die "디스크 여유가 60GB보다 적습니다(${FREEG}GB). 더 큰 서버를 쓰세요."

say "2/6 자체 점검 (계산 엔진 = 규칙봇 엔진, 딥시크 기본값 = 지금 딥시크 신호)"
HEAD=$(git rev-parse HEAD)
if [ "$(cat "$BASE/CHECKED" 2>/dev/null)" != "$HEAD" ]; then
  "$PY" -m pytest -q -x tests/test_fullgrid_kernel.py tests/test_fullgrid_ds_defs.py tests/test_fullgrid_memo.py \
    tests/test_fullgrid_run.py >>"$LOG" 2>&1 || die "자체 점검 실패 (run.log 마지막 부분을 보내 주세요)"
  echo "$HEAD" > "$BASE/CHECKED"
fi

say "3/6 바이낸스 공개 자료 받기 (2020-01 ~ 2026-09, 1분봉·마크 가격·펀딩, 약 10~20분)"
if [ ! -f "$DATA/build.json" ]; then
  "$PY" research/fullgrid/data.py all --dir "$DATA" --procs 16 >>"$LOG" 2>&1 || die "자료 받기 실패"
fi

EX=research/fullgrid/exchange.json
if [ ! -f "$EX" ]; then           # only this file is fetched: the code stays the commit the self-check passed
  BR=$(git rev-parse --abbrev-ref HEAD)
  say "레버리지 구간 표(exchange.json)를 기다립니다. 규칙봇 서버에서 0번을 해서 채팅에 붙여 주세요. 개발자가 올리면 1분 안에 저절로 이어 갑니다."
  for k in $(seq 1 360); do
    git fetch -q origin "$BR" 2>/dev/null && git checkout -q FETCH_HEAD -- "$EX" 2>/dev/null && break
    sleep 60
  done
  [ -f "$EX" ] || die "6시간 동안 레버리지 구간 표가 오지 않았습니다. 0번을 한 뒤 다시 시작하세요: $RESTART"
  say "레버리지 구간 표 받음 ($(cut -c1-40 "$EX"))"
fi

export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
MEMG=$(free -g | awk '/Mem/{print $2}')
PROCS=$(nproc); BYMEM=$(( MEMG * 10 / 18 ))            # about 1.8 GB per worker at the peak
[ "$BYMEM" -lt "$PROCS" ] && PROCS=$BYMEM; [ "$PROCS" -lt 1 ] && PROCS=1
say "4/6 계산 (모든 조합, 작업 ${PROCS}개 동시에)"
"$PY" research/fullgrid/run.py outcomes --data "$DATA" --out "$OUT" --procs "$PROCS" \
  --exchange research/fullgrid/exchange.json >>"$LOG" 2>&1 || die "거래 결과표 계산 실패"
"$PY" research/fullgrid/run.py grid --data "$DATA" --out "$OUT" --procs "$PROCS" >>"$LOG" 2>&1 \
  || say "조합 계산: 실패한 작업이 있어 한 번 더 합니다"
"$PY" research/fullgrid/run.py grid --data "$DATA" --out "$OUT" --procs "$PROCS" >>"$LOG" 2>&1 \
  || die "조합 계산 실패 (두 번째에도 빠진 작업이 있음)"

say "5/6 고르기 → 시험 기간 확인 → 보고서"
"$PY" research/fullgrid/run.py select --out "$OUT" >>"$LOG" 2>&1 || die "고르기 실패"
"$PY" research/fullgrid/run.py confirm --data "$DATA" --out "$OUT" --procs "$PROCS" \
  --exchange research/fullgrid/exchange.json >>"$LOG" 2>&1 || die "확인 실패"
"$PY" research/fullgrid/run.py report --out "$OUT" >>"$LOG" 2>&1 || die "보고서 실패"

say "6/6 결과 묶기"
"$PY" research/fullgrid/run.py pack --out "$OUT" >>"$LOG" 2>&1 || die "결과 묶기 실패"
cp "$DATA/build.json" "$OUT/results/data_build.json" 2>/dev/null
grep -v -E "^\[grid [0-9]+/" "$LOG" > "$OUT/results/run.log" 2>/dev/null      # without the per-task progress lines
tar czf "$BASE/results.tgz" -C "$OUT" results >>"$LOG" 2>&1 || die "결과 묶기 실패"
touch "$BASE/DONE"; rm -f "$BASE/RUNNING"
say "끝. 결과 $(du -h "$BASE/results.tgz" | cut -f1): $BASE/results.tgz"
say "보내기: bash $REPO/research/fullgrid/bootstrap.sh push   (그다음 Vultr에서 서버 Destroy)"
head -40 "$OUT/results/RESULTS_KO.md" 2>/dev/null
