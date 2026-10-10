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

status() {
  if [ -f "$BASE/DONE" ]; then
    echo "끝났습니다. 결과: $BASE/results.tgz  (보내기: bash $REPO/research/fullgrid/bootstrap.sh push)"; return
  fi
  [ -x "$PY" ] || { echo "아직 설치 중입니다."; tail -2 "$LOG" 2>/dev/null; return; }
  local last; last=$(grep -E '^\[grid [0-9]+/' "$LOG" 2>/dev/null | tail -1)
  if [ -n "$last" ]; then echo "계산 중: $last" | cut -c1-160; else tail -1 "$LOG" 2>/dev/null; fi
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
  status) status; exit 0 ;;
  push) push; exit 0 ;;
  run) ;;
  *) echo "사용법: bash bootstrap.sh [run|status|push]"; exit 2 ;;
esac

say "1/6 설치 (파이썬 패키지)"
export DEBIAN_FRONTEND=noninteractive
if [ ! -x "$PY" ]; then
  for k in 1 2 3 4 5 6 7 8 9 10; do
    apt-get update -y >>"$LOG" 2>&1 && apt-get install -y python3-venv python3-pip git tmux >>"$LOG" 2>&1 && break
    say "다른 설치가 끝나기를 기다립니다 (${k}/10)"; sleep 30
  done
  python3 -m venv "$VENV" || die "venv 만들기 실패"
  "$VENV/bin/pip" install -q --upgrade pip >>"$LOG" 2>&1
  "$VENV/bin/pip" install -q "numpy==2.0.2" "pandas==2.3.3" "scipy>=1.11" "numba==0.60.0" "pytest>=8" >>"$LOG" 2>&1 \
    || die "패키지 설치 실패"
fi
cd "$REPO" || die "코드 폴더가 없습니다: $REPO"
[ -f research/fullgrid/exchange.json ] || die "research/fullgrid/exchange.json(레버리지 구간 표)이 저장소에 아직 없습니다."
say "코드 $(git rev-parse --short HEAD), CPU $(nproc)개, 메모리 $(free -g | awk '/Mem/{print $2}')GB"

say "2/6 자체 점검 (계산 엔진 = 규칙봇 엔진, 딥시크 기본값 = 지금 딥시크 신호)"
if [ ! -f "$BASE/CHECKED" ]; then
  "$PY" -m pytest -q -x tests/test_fullgrid_kernel.py tests/test_fullgrid_ds_defs.py tests/test_fullgrid_memo.py \
    tests/test_fullgrid_run.py >>"$LOG" 2>&1 || die "자체 점검 실패 (run.log 마지막 부분을 보내 주세요)"
  touch "$BASE/CHECKED"
fi

say "3/6 바이낸스 공개 자료 받기 (2020-01 ~ 2026-09, 1분봉·마크 가격·펀딩, 약 10~20분)"
if [ ! -f "$DATA/build.json" ]; then
  "$PY" research/fullgrid/data.py all --dir "$DATA" --procs 16 >>"$LOG" 2>&1 || die "자료 받기 실패"
fi

PROCS=$(( $(nproc) ))
say "4/6 계산 (모든 조합, 작업 ${PROCS}개 동시에)"
"$PY" research/fullgrid/run.py outcomes --data "$DATA" --out "$OUT" --procs "$PROCS" \
  --exchange research/fullgrid/exchange.json >>"$LOG" 2>&1 || die "거래 결과표 계산 실패"
"$PY" research/fullgrid/run.py grid --data "$DATA" --out "$OUT" --procs "$PROCS" >>"$LOG" 2>&1 || die "조합 계산 실패"
"$PY" research/fullgrid/run.py grid --data "$DATA" --out "$OUT" --procs "$PROCS" >>"$LOG" 2>&1 || die "조합 계산 실패"

say "5/6 고르기 → 시험 기간 확인 → 보고서"
"$PY" research/fullgrid/run.py select --out "$OUT" >>"$LOG" 2>&1 || die "고르기 실패"
"$PY" research/fullgrid/run.py confirm --data "$DATA" --out "$OUT" --procs "$PROCS" \
  --exchange research/fullgrid/exchange.json >>"$LOG" 2>&1 || die "확인 실패"
"$PY" research/fullgrid/run.py report --out "$OUT" >>"$LOG" 2>&1 || die "보고서 실패"

say "6/6 결과 묶기"
"$PY" research/fullgrid/run.py pack --out "$OUT" >>"$LOG" 2>&1 || die "결과 묶기 실패"
tar czf "$BASE/results.tgz" -C "$OUT" results >>"$LOG" 2>&1 || die "결과 묶기 실패"
cp "$LOG" "$OUT/results/run.log" 2>/dev/null
touch "$BASE/DONE"
say "끝. 결과 $(du -h "$BASE/results.tgz" | cut -f1): $BASE/results.tgz"
say "보내기: bash $REPO/research/fullgrid/bootstrap.sh push   (그다음 Vultr에서 서버 Destroy)"
head -40 "$OUT/results/RESULTS_KO.md" 2>/dev/null
