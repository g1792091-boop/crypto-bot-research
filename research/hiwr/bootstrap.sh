#!/usr/bin/env bash
# 2번 트랙(고승률 · 낙폭 한도)을 빌린 계산 서버에서 돌립니다 (research/hiwr/SERVER_KO.md).
# 바이낸스 공개 가격 자료만 씁니다: 거래소 키·AI 키 없음. 규칙봇·데모봇·후보 리그, 추세 사냥 서버(/root/hunt)와 관계없음.
#
#   HIWR_GO=<커밋> bash bootstrap.sh   설치 → 자체 점검 → 고정 확인 → 연습 기간 자료 받기 → 자료 확인 → 고르기
#                                      → 고른 것 고정 확인 → 확인 기간 시험 → 참고 분석 → 결과 묶기 (tmux 안에서 돌리세요).
#                                      첫 실행에는 검토를 마친 커밋(HIWR_GO)이 꼭 있어야 하고, 코드가 그 커밋이 아니면 멈춥니다.
#   bash bootstrap.sh status           지금 단계와 남은 시간(어림)
#   bash bootstrap.sh push             결과를 GitHub(브랜치 hiwr-results)로 보냄. 올리기가 되면 토큰을 다시 묻지 않음
#   bash bootstrap.sh update <커밋>    개발자가 고친 커밋으로 코드를 바꿈 (계산 시작 전에만: 6/10 전)
#
# 모든 단계는 이미 끝난 것을 건너뜁니다: 멈추거나 재부팅된 뒤 같은 명령이 이어서 합니다. 첫 실행의 설정은
# $BASE/settings.env 에 남아 다시 시작해도 같습니다. 확인 기간(2024-01 ~ 2026-09) 자료는 고른 것(picks.json)의 sha256이
# 고정 파일에 붙은 뒤 'hiwr test' 안에서만 받습니다. 딥시크 돈 숫자(D11)는 저장소 밖 $BASE/private 에만 있고
# results.tgz 에는 들어가지 않습니다.
#
# Rehearsal (no install, no download, no push, no git change): every stand-in comes from an env file that is read only
# with --dry-run:
#   HIWR_DRYENV=<file> bash bootstrap.sh --dry-run [run|status|idle|update <commit>|push]
# The file sets HIWR_BASE and HIWR_REPO (scratch folders) and any of: HIWR_PY, HIWR_CMD (the hiwr command line),
# HIWR_DATA_CMD (data.py), HIWR_HELPER_STUB + HIWR_HELPER_STUB_SUBS (helper sub-commands to replace), HIWR_PIN_REL,
# HIWR_SELFCHECK_TESTS, HIWR_TMUX (e.g. "tmux -L rehearsal"), HIWR_RETRY_SLEEP, HIWR_READS_HOURS, HIWR_GO.
set -uo pipefail

MODE=run
DRYRUN=${DRYRUN:-0}
ARG=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRYRUN=1 ;;
    run|status|push|update|idle) MODE=$a ;;
    *) if [ "$MODE" = update ] && [ -z "$ARG" ]; then ARG=$a
       else echo "사용법: bash bootstrap.sh [run|status|push|update <커밋>] [--dry-run]"; exit 2; fi ;;
  esac
done
if [ "$DRYRUN" = 1 ] && [ -n "${HIWR_DRYENV:-}" ]; then
  # shellcheck source=/dev/null
  . "$HIWR_DRYENV" || { echo "연습 설정 파일을 읽지 못했습니다: $HIWR_DRYENV"; exit 2; }
fi

BASE=${HIWR_BASE:-/root/hiwr}
case "$BASE" in
  /root/hunt|/root/hunt/*) echo "2번 트랙은 추세 사냥 폴더(/root/hunt)를 쓰지 않습니다: HIWR_BASE=$BASE"; exit 2 ;;
esac
if [ "$DRYRUN" != 1 ] && [ -d /root/hunt ]; then
  echo "이 서버에는 추세 사냥 폴더(/root/hunt)가 있습니다. 2번 트랙은 추세 사냥 서버를 Destroy한 뒤 새 서버에서 돌립니다."
  echo "이 화면을 개발자에게 보내 주세요."
  exit 1
fi
mkdir -p "$BASE"
# Settings of the first run are kept, so a restart (which passes no environment) runs with the same choices.
SETTINGS=$BASE/settings.env
PERSIST="HIWR_GO HIWR_WORKERS HIWR_PROCS HIWR_ELIG HIWR_READS_HOURS"
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

REPO=${HIWR_REPO:-$BASE/crypto-bot-research}
KIT=$BASE/kit_sel                    # the practice kit: 2020-01 .. 2023-12 only (data.KIT_SEL)
KIT_TEST=$BASE/kit_test              # the confirm kit: made by 'hiwr test' after the picks line (10.6)
WORK=$BASE/work
PRIV=$BASE/private                   # DeepSeek figures and other private files (D11), never packed into results.tgz
VENV=$BASE/venv
LOG=$BASE/run.log
GO=${HIWR_GO:-}
WORKERS=${HIWR_WORKERS:-16}          # download threads
ELIG=${HIWR_ELIG:-all}
READS_HOURS=${HIWR_READS_HOURS:-12}
RSLEEP=${HIWR_RETRY_SLEEP:-30}
PIN_REL=${HIWR_PIN_REL:-research/hiwr/PREREG_HIWR.sha256}
PICKS_REL=research/hiwr/picks.json
OUT=research/hiwr/out
TESTS=${HIWR_SELFCHECK_TESTS:-tests/test_hiwr_core.py tests/test_hiwr_data.py tests/test_hiwr_cli.py tests/test_hiwr_reads.py tests/test_fullgrid_kernel.py tests/test_fullgrid_run.py tests/test_fullgrid_memo.py}
if [ "$DRYRUN" = 1 ]; then PY=${HIWR_PY:-python3}; else PY=${HIWR_PY:-$VENV/bin/python}; fi
if [ -n "${HIWR_CMD:-}" ]; then read -r -a HIWR <<<"$HIWR_CMD"; else HIWR=("$PY" -m research.hiwr.hiwr); fi
if [ -n "${HIWR_DATA_CMD:-}" ]; then read -r -a DATA <<<"$HIWR_DATA_CMD"; else DATA=("$PY" -m research.hiwr.data); fi
STUBS=()
[ -n "${HIWR_HELPER_STUB:-}" ] && read -r -a STUBS <<<"$HIWR_HELPER_STUB"
case "$ELIG" in all|lazy) ;; *) echo "HIWR_ELIG는 all 또는 lazy: $ELIG"; exit 2 ;; esac
NCPU=$(env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc)    # nproc obeys OMP_NUM_THREADS, set to 1 below
SELF=$REPO/research/hiwr/bootstrap.sh
NST=10
TM=${HIWR_TMUX:-tmux}
if [ "$DRYRUN" = 1 ]; then RUNCMD="HIWR_DRYENV=${HIWR_DRYENV:-} bash $SELF --dry-run"; else RUNCMD="bash $SELF"; fi
RESTART="$RUNCMD idle && { $TM respawn-pane -k -t hiwr \"$RUNCMD; bash\" 2>/dev/null || $TM new -d -s hiwr \"$RUNCMD; bash\"; [ -n \"\$TMUX\" ] || $TM attach -t hiwr; }"

say() { echo "[$(date -u '+%m-%d %H:%M UTC')] $*" | tee -a "$LOG"; }
sub() { say "  · $*"; }
warn() {                     # something skipped that does not stop the run (listed again at the end)
  say "  · 참고: $*"
  grep -qxF "$*" "$BASE/WARNINGS" 2>/dev/null || echo "$*" >> "$BASE/WARNINGS"
}
computed() {                 # anything computed on this server: stage 6 started, or select ran here
  grep -qE '^([6-9]|10)\|' "$BASE/STAGES" 2>/dev/null && return 0
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
die_retry() {                # a stop that a later restart can get past (network, apt lock)
  say "멈춤: $*"
  say "몇 분 뒤 아래 한 줄 전체를 붙여 넣으면 이어서 합니다 (끝난 것은 건너뜁니다):"
  echo "$RESTART" | tee -a "$LOG"
  say "같은 멈춤이 두 번 나오면 이 화면을 그대로 복사해 개발자에게 보내 주세요."
  computed && keep_server
  exit 1
}

# ------------------------------------------------------------------ time estimates (32 vCPU basis, see SERVER_KO)
# Measured 2026-10-12 on SEL-cut data of the old six (3 coins, 2 processes), scaled to 30 coins: the select grid is about
# 430 CPU-hours (15m 222, 30m 118, 1h 64, 4h 20); x1.3 margin. Its wall time is the larger of that spread over the
# workers and the longest single task: with whole-cell tasks (about 390 tasks) the longest is N01_ST_EMA 15m, about 33 h
# (x1.3 = 43 h); with combo chunks (over 1,000 tasks) it is a few hours.
picks_n() { cat "$BASE/PICKS_N" 2>/dev/null; }
grid_total() { grep -oE "\[grid\] [0-9]+ of [0-9]+ tasks" "$LOG" 2>/dev/null | tail -1 | awk '{print $4}'; }
select_est() {
  local t par lp
  t=$(grid_total)
  par=$(( 560 * 60 / NCPU ))
  if [ -z "$t" ] || [ "$t" -lt 1000 ]; then lp=2580; elif [ "$t" -lt 3000 ]; then lp=330; else lp=120; fi
  [ "$par" -gt "$lp" ] && lp=$par
  echo $(( lp + 100 ))       # + frames, tables, eligibility and the picks
}
reads_est() {
  local p cap; p=$(picks_n); cap=$(awk -v h="$READS_HOURS" 'BEGIN{printf "%d", h * 60}')
  if [ -z "$p" ]; then echo 120; return; fi
  [ "$p" = 0 ] && { echo 0; return; }
  p=$(( p * 6 + 10 )); [ "$p" -gt "$cap" ] && p=$cap
  echo "$p"
}
est_min() {
  case $1 in
    1) echo 6 ;; 2) echo 10 ;; 3) echo 3 ;; 4) echo 35 ;; 5) echo 10 ;;
    6) select_est ;;
    7) echo 1 ;;
    8) if [ "$(picks_n)" = 0 ]; then echo 0; else echo 90; fi ;;
    9) reads_est ;;
    10) echo 3 ;;
    *) echo 0 ;;
  esac
}
left_from() { local s=0 k; for k in $(seq "$1" "$NST"); do s=$(( s + $(est_min "$k") )); done; echo "$s"; }
hm() { local m=$1; if [ "$m" -ge 120 ]; then echo "약 $(( m / 60 ))시간 $(( m % 60 ))분"; else echo "약 ${m}분"; fi; }

stage() {                    # stage <n> <name>
  local now; now=$(date +%s)
  echo "$1|$2|$now" > "$BASE/STAGE"
  echo "$1|$2|$now" >> "$BASE/STAGES"
  say "$1/$NST $2  (남은 시간 $(hm "$(left_from "$1")"), 어림)"
}

running() {                  # the run's own process (RUNNING holds its pid), or a step it left behind
  local p; p=$(cat "$BASE/RUNNING" 2>/dev/null)
  if [ -n "$p" ] && kill -0 "$p" 2>/dev/null && grep -qa "hiwr/bootstrap.sh" "/proc/$p/cmdline" 2>/dev/null; then
    return 0
  fi
  [ "$DRYRUN" = 1 ] && return 1
  pgrep -f "[r]esearch\.hiwr\.(hiwr|data)|[t]ests/test_(hiwr|fullgrid)" >/dev/null
}

status() {
  if [ -f "$BASE/DONE" ]; then
    echo "끝났습니다. 결과: $BASE/results.tgz  (보내기: bash $SELF push)"
    if [ -s "$BASE/WARNINGS" ]; then echo "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS"; fi
    return
  fi
  if ! running; then
    echo "지금 돌고 있지 않습니다. 마지막 기록:"
    grep -E "멈춤|\] ([0-9]|10)/$NST " "$LOG" 2>/dev/null | tail -3
    echo "이어서 하려면 아래 한 줄 전체를 붙여 넣으세요:"
    echo "$RESTART"
    return
  fi
  local n=0 name="설치 중" t0 el left last
  t0=$(date +%s)
  [ -f "$BASE/STAGE" ] && IFS='|' read -r n name t0 < "$BASE/STAGE"
  el=$(( ($(date +%s) - t0) / 60 ))
  left=$(( $(est_min "$n") - el )); [ "$left" -lt 1 ] && left=1
  [ "$n" -lt "$NST" ] && left=$(( left + $(left_from $(( n + 1 ))) ))
  echo "진행 중: $n/$NST $name (이 단계 ${el}분째)"
  echo "  남은 시간: $(hm "$left") (어림, CPU ${NCPU}개 기준; 길게 잡은 값)"
  last=$(grep -F "  · " "$LOG" 2>/dev/null | tail -1)
  [ -n "$last" ] && echo "  지금: ${last#*· }"
  case "$n" in
    4|8) last=$(grep -oE "\[(monthly|gap-fill days)\] [0-9]+/[0-9]+ files" "$LOG" 2>/dev/null | tail -1)
         [ -n "$last" ] && echo "  자료: $last" ;;
    6) last=$(grep -oE "\[grid [0-9]+/[0-9]+ " "$LOG" 2>/dev/null | tail -1 | tr -d '[]' | awk '{print $2}')
       [ -n "$last" ] && echo "  고르기 작업: ${last} 끝 (무거운 작업이 먼저 시작해서 끝 무렵에 몰려 끝납니다)"
       grep -q "\[eligibility\]" "$LOG" 2>/dev/null && echo "  고르기: 계좌·동전 비교 단계(마지막 부분)" ;;
  esac
  case "$n" in
    6) echo "  6/$NST 고르기는 이 연구에서 가장 깁니다(하루 이상일 수 있음). 남은 시간이 그대로여도 정상이니 다시 시작하지 마세요." ;;
    9) echo "  9/$NST 참고 분석은 최대 ${READS_HOURS}시간 걸릴 수 있습니다. 판정은 이미 끝났고, 정상이니 다시 시작하지 마세요." ;;
  esac
}

push() {
  [ "$DRYRUN" = 1 ] && [ -z "${HIWR_PUSH_REHEARSAL:-}" ] && { echo "연습 모드에서는 보내지 않습니다."; return 1; }
  [ -f "$BASE/results.tgz" ] || die "결과 파일이 아직 없습니다."
  cd "$REPO" || exit 1
  git config user.email "hiwr@localhost"; git config user.name "hiwr server"
  git config credential.helper store
  # commit in a separate worktree, so the run's checkout stays on the go commit (a later restart checks it)
  local br=hiwr-results wt=$BASE/push_wt rc br2
  if [ ! -d "$wt" ]; then
    git worktree prune
    if git rev-parse -q --verify "refs/heads/$br" >/dev/null; then
      git worktree add "$wt" "$br" >>"$LOG" 2>&1 || die "올리기 준비 실패 (git worktree)"
    else
      git worktree add -b "$br" "$wt" HEAD >>"$LOG" 2>&1 || die "올리기 준비 실패 (git worktree)"
    fi
  fi
  cd "$wt" || exit 1
  rm -rf research/hiwr/results
  tar xzf "$BASE/results.tgz" -C research/hiwr || die "결과 풀기 실패"            # -> research/hiwr/results/
  git add -f research/hiwr/results
  git commit -q -m "Track 2 (hiwr v1): select, test and reads results ($(hostname), $(date -u +%F))" \
    || say "새로 올릴 변경이 없습니다 (이미 커밋됨)"
  echo "GitHub 아이디와, 비밀번호 자리에 쓰기 토큰(Contents: Read and write)을 넣으세요. (올리기가 되면 다시 묻지 않습니다)"
  git push -u origin "$br" 2>&1 | tee "$BASE/push.out"; rc=${PIPESTATUS[0]}
  if [ "$rc" = 0 ]; then say "보냈습니다: 브랜치 $br"; return 0; fi
  if grep -qiE "rejected|non-fast-forward|fetch first" "$BASE/push.out"; then
    br2="hiwr-results-$(date -u +%Y%m%d-%H%M)"
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
  [ -f "$BASE/DONE" ] && { echo "이미 끝났습니다. 바꿀 것 없습니다 (결과: $BASE/results.tgz, 보내기: bash $SELF push)"; return 1; }
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
  HIWR_GO=$want
  case " $GIVEN " in *" HIWR_GO "*) ;; *) GIVEN="$GIVEN HIWR_GO" ;; esac
  save_settings
  rm -f "$BASE/CHECKED"
  echo "코드를 ${want:0:10} 으로 바꿨습니다. (다시 시작 줄이 같이 있었다면 더 붙여 넣을 것 없음. 아니면 아래 한 줄:)"
  echo "$RESTART"
}

case "$MODE" in
  status) status; exit 0 ;;
  push) push; exit $? ;;
  update) update "$ARG"; exit $? ;;
  idle) running && { echo "이미 돌고 있습니다. 다시 시작할 필요 없습니다. 진행 보기: bash $SELF status"; exit 1; }
        exit 0 ;;              # the printed restart line starts with this guard: a paste during a run changes nothing
esac

for k in 1 2 3 4 5; do running || break; sleep 2; done      # a restart: let the old run finish dying
running && { echo "이미 돌고 있습니다. 화면 보기: $TM attach -t hiwr   (진행: bash $SELF status)"; exit 1; }
if [ -f "$BASE/DONE" ]; then
  echo "이미 끝났습니다: $BASE/results.tgz  (보내기: bash $SELF push; 처음부터 다시 묶으려면 rm $BASE/DONE)"
  exit 0
fi
echo $$ > "$BASE/RUNNING"
rm -f "$BASE/WARNINGS"                       # every stage that warns re-runs on a resume, so it warns again
echo "0|run start|$(date +%s)" >> "$BASE/STAGES"
[ "$DRYRUN" = 1 ] && say "연습 모드 (DRYRUN): 설치·자료 받기·보내기·git은 하지 않습니다"

# ------------------------------------------------------------------ helper (Python, run from the repository)
helper() {                   # helper <pincheck|build|verify|picks|stamp> args...
  if [ "${#STUBS[@]}" -gt 0 ] && [[ " ${HIWR_HELPER_STUB_SUBS:-} " == *" $1 "* ]]; then
    "${STUBS[@]}" "$@"
    return
  fi
  "$PY" - "$@" <<'PYEOF'
import glob, hashlib, json, os, platform, subprocess, sys, time
sys.path.insert(0, os.getcwd())
sub, args = sys.argv[1], sys.argv[2:]
PIN_REL = os.environ.get("HIWR_PIN_REL") or "research/hiwr/PREREG_HIWR.sha256"
MAN_REL = "research/hiwr/data_manifest_sel.json"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


if sub == "pincheck":                    # the code's own check (17.3): every pinned file, the required list, data check
    from research.hiwr import hiwr as H
    H.PIN_REL = PIN_REL
    try:
        print("pin ok", args[0], H.check_pin(args[0]))
    except H.PinError as e:
        print("refused:", e)
        sys.exit(2)
elif sub == "build":                     # data.build, one coin per process (the same build.json as data.build)
    import functools
    import multiprocessing as mp
    from research.hiwr import data as D
    kit, procs = args[0], int(args[1])
    only = os.environ.get("HIWR_HELPER_SYMBOLS")          # rehearsal only: a few coins
    syms = tuple(only.split(",")) if only else D.SYMBOLS
    first, last = D.KIT_SEL
    man = D._manifest(kit)
    if list(man.get("months", [])) != [first, last]:
        print(f"PROBLEM {kit}/manifest.json holds months {man.get('months')}, not {first} .. {last}")
        sys.exit(1)
    one = functools.partial(D.build_symbol, kit, man=man, first=first, last=last)
    with mp.get_context("fork").Pool(max(1, procs)) as pool:
        reps = pool.map(one, syms, chunksize=1)
    rep = {"months": [first, last], "symbols": reps, "gap_days": len(man.get("gap_days", [])),
           "missing_files": len(man["missing"])}
    rep["problems"] = [p for r in rep["symbols"] for p in r["problems"]]
    D._save_json(os.path.join(kit, "build.json"), rep)
    for r in reps:
        if r["minutes"]:
            print(f"{r['symbol']}: {r['minutes']:,} minutes {r['first']} .. {r['last']}{' (ended)' if r['ended'] else ''}")
    for p in rep["problems"]:
        print("PROBLEM", p)
elif sub == "verify":                    # the kit against the pinned practice-kit manifest, every array re-hashed
    from research.hiwr import data as D
    kit, out = args
    pinned = json.load(open(MAN_REL))
    mine = D.manifest(kit)
    end = D.PERIODS["SEL"][1]
    bad = []
    if list(mine["months"]) != list(pinned["months"]):
        bad.append(f"months {mine['months']} != {pinned['months']}")
    only_pin = sorted(set(pinned["coins"]) - set(mine["coins"]))
    only_mine = sorted(set(mine["coins"]) - set(pinned["coins"]))
    if only_pin or only_mine:
        bad.append(f"coins missing here {only_pin}, extra here {only_mine}")
    same = 0
    for s, want in pinned["coins"].items():
        got = mine["coins"].get(s)
        if got is None:
            continue
        diff = sorted(k for k in want if want[k] != got.get(k))
        if not diff:
            try:
                a = D.load_kit(kit, s, None, want=want["content_sha256"])
                if len(a["ts"]) and int(a["ts"][-1]) >= end:
                    diff.append("a minute at or after 2024-01-01")
                del a
            except D.DataMismatch as e:
                diff.append(str(e))
        if diff:
            bad.append(f"{s}: {', '.join(diff)}")
        else:
            same += 1
    build_same = sha(os.path.join(kit, "build.json")) == pinned.get("build_sha256")
    doc = {"what": "practice kit on this server against research/hiwr/data_manifest_sel.json (pinned)",
           "coins_pinned": len(pinned["coins"]), "coins_identical": same, "problems": bad,
           "build_json_identical": build_same, "pinned_manifest_sha256": sha(MAN_REL),
           "written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    json.dump(doc, open(out, "w"), indent=1)
    print(f"VERIFY coins {same}/{len(pinned['coins'])} identical (every array re-hashed), "
          f"build.json {'identical' if build_same else 'differs (not a stop: the arrays decide)'}"
          + (f"; PROBLEMS {len(bad)}: {'; '.join(bad[:3])}" if bad else ""))
    sys.exit(1 if bad else 0)
elif sub == "picks":                     # the picks line (10.6): picks.json's sha256 is the pin's last picks line
    doc = json.load(open("research/hiwr/picks.json"))
    h = sha("research/hiwr/picks.json")
    lines = [ln.rstrip("\n").split("  ", 1) for ln in open(PIN_REL) if ln.strip()]
    pl = [x[0] for x in lines if len(x) == 2 and x[1].strip() == "research/hiwr/picks.json"]
    ok = bool(pl) and pl[-1] == h
    tfs = {}
    for p in doc["picks"]:
        tfs[p["tf"]] = tfs.get(p["tf"], 0) + 1
    ds = sum(1 for p in doc["picks"] if p.get("kind") == "ds")
    print(f"PICKS n={len(doc['picks'])} sha256={h} pinned={'yes' if ok else 'no'} deepseek={ds} "
          f"by_tf={','.join(f'{k}:{v}' for k, v in sorted(tfs.items()))}")
    sys.exit(0 if ok else 1)
elif sub == "stamp":
    out, base, priv, ncpu, procs, dry = args
    def git(*a):
        try:
            return subprocess.run(["git", *a], capture_output=True, text=True, timeout=60).stdout.strip()
        except Exception:
            return None
    pats = ["research/hiwr/*.py", "research/hiwr/*.sh", "research/hiwr/*.md", "research/hiwr/*.json",
            "research/hiwr/*.sha256", "research/hiwr/GO_COMMIT", "research/fullgrid/grid.py",
            "research/fullgrid/ds_defs.py", "research/fullgrid/kernel.py", "research/fullgrid/run.py",
            "research/fullgrid/memo.py", "research/fullgrid/data.py", "research/fullgrid/exchange.json",
            "research/entry_study/DEFS_BC.sha256", "research/hunt/universe30.json", "research/hunt/exchange30.json",
            "tests/test_hiwr_*.py", "tests/test_fullgrid_kernel.py", "tests/test_fullgrid_run.py",
            "tests/test_fullgrid_memo.py", PIN_REL]
    files = sorted({p for pat in pats for p in glob.glob(pat) if os.path.isfile(p)})
    stages = []
    try:
        rows = [ln.rstrip("\n").split("|") for ln in open(os.path.join(base, "STAGES")) if ln.strip()]
        for i, (n, name, t) in enumerate(rows):
            t1 = int(rows[i + 1][2]) if i + 1 < len(rows) else int(time.time())
            stages.append({"stage": int(n), "name": name,
                           "start_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(t))),
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
        mem = [ln for ln in open("/proc/meminfo") if ln.startswith("MemTotal")][0].split()[1] + " kB"
    except Exception:
        pass
    settings = {}
    try:
        settings = dict(ln.rstrip("\n").split("=", 1) for ln in open(os.path.join(base, "settings.env")) if "=" in ln)
    except Exception:
        pass
    priv_files = {}
    for p in sorted(glob.glob(os.path.join(priv, "**", "*"), recursive=True)):
        if os.path.isfile(p):
            priv_files[os.path.relpath(p, priv)] = sha(p)          # names and sha256 only: the figures stay off (D11)
    stamp = {"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "dry_run": dry == "1",
             "git": {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                     "status_porcelain": git("status", "--porcelain")},
             "settings": settings, "files_sha256": {p: sha(p) for p in files}, "python": sys.version,
             "packages": vers, "machine": {"nproc": int(ncpu), "procs_used": int(procs), "mem": mem,
                                           "platform": platform.platform()},
             "stages": stages, "private_files_sha256": priv_files,
             "private_note": "DeepSeek figures (D11) stay in the private folder on the server (private.tgz), not here"}
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
    die_fix "어느 커밋을 돌릴지 정해지지 않았습니다 (HIWR_GO=${GO:-없음}). SERVER_KO의 한 줄을 그대로 쓰세요."
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
  # the versions the hiwr code, the full grid and the hunt were built and tested with
  "$VENV/bin/pip" install -q "numpy==2.0.2" "pandas==2.3.3" "numba==0.60.0" "scipy>=1.11" "pytest>=8" >>"$LOG" 2>&1 \
    || die_retry "패키지 설치 실패 (인터넷)"
  "$PY" -c "import numba, numpy, pandas; print('numpy', numpy.__version__, 'pandas', pandas.__version__, 'numba', numba.__version__)" \
    >>"$LOG" 2>&1 || die "numba를 불러오지 못했습니다"
  touch "$BASE/INSTALLED"
fi
FREEG=$(df -BG --output=avail "$BASE" | tail -1 | tr -dc '0-9')
MEMG=$(free -g | awk '/Mem/{print $2}')
say "코드 ${HEAD:0:10}, CPU ${NCPU}개, 메모리 ${MEMG}GB, 디스크 여유 ${FREEG}GB"
[ "$DRYRUN" = 1 ] || [ "${FREEG:-0}" -ge 60 ] || [ -f "$BASE/SEL_VERIFIED" ] \
  || die "디스크 여유가 60GB보다 적습니다(${FREEG}GB). 서버를 Destroy하고 디스크 100GB로 다시 만드세요."
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
PROCS=$NCPU
[ "${MEMG:-0}" -ge 2 ] && [ $(( MEMG / 2 )) -lt "$PROCS" ] && PROCS=$(( MEMG / 2 ))   # about 2 GB per worker at most
[ -n "${HIWR_PROCS:-}" ] && PROCS=$HIWR_PROCS
[ "$PROCS" -lt 1 ] && PROCS=1
BPROCS=$(( PROCS < 8 ? PROCS : 8 ))      # the data build: one coin per process, pandas reads 48 month files each

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
picks_pinned() { grep -q "  $PICKS_REL\$" "$PIN_REL" 2>/dev/null; }
pin_check() {                # pin_check <select|test>: the code's own check_pin
  local out rc
  out=$(helper pincheck "$1" 2>&1); rc=$?
  echo "$out" >> "$LOG"
  [ "$rc" = 0 ] || die_fix "고정 확인 거부: $(echo "$out" | tail -1)"
}

stage 3 "고정 파일 확인 (사전 등록·코드·연습 기간 자료 기준이 고정된 그대로인지)"
[ -f "$PIN_REL" ] || die_fix "$PIN_REL 가 없습니다: 2번 트랙이 아직 고정되지 않았습니다"
for f in research/hiwr/data_manifest_sel.json research/hiwr/data_check_sel.json; do
  grep -q "  $f\$" "$PIN_REL" || die_fix "고정 파일에 $f 줄이 없습니다 (연습 기간 자료 기준은 고정 전에 있어야 합니다)"
done
if picks_pinned && [ ! -f "$BASE/SELECT_RAN" ]; then
  die_fix "고정 파일에 이미 고른 것(picks) 줄이 있습니다. 이 서버에서 고르기 전이므로 있으면 안 됩니다 (받은 커밋 확인)"
fi
step="select"; picks_pinned && step="test"
pin_check "$step"
sub "고정 일치 (다음 단계: $step)"
for f in research/hunt/out/v1/test.json research/hunt/out/wide/test.json; do
  [ -f "$f" ] || warn "프로그램 전체 장부: 추세 사냥 결과 $f 가 이 코드에 없어 장부에 '없음'으로 적힙니다 (판정과는 관계없음)"
done
LEDGER_ARGS=()
[ -f "$BASE/ledger_extra.json" ] && LEDGER_ARGS+=(--ledger-extra "$BASE/ledger_extra.json")
[ -f "$BASE/hunt_private_test.json" ] && LEDGER_ARGS+=(--hunt-private "$BASE/hunt_private_test.json")

# ------------------------------------------------------------------ 4 practice-kit download (2020-01 .. 2023-12 only)
stage 4 "연습 기간 자료 받기 (30개 코인 1분봉·마크 가격·펀딩, 2020-01 ~ 2023-12만)"
if [ -f "$BASE/SEL_DOWNLOADED" ]; then
  sub "건너뜀: 이미 받았습니다"
elif [ "$DRYRUN" = 1 ] && [ -z "${HIWR_DATA_CMD:-}" ]; then
  sub "연습: 받기 건너뜀 (주어진 폴더: $KIT)"; touch "$BASE/SEL_DOWNLOADED"
else
  mkdir -p "$KIT"
  for k in 1 2 3; do
    if "${DATA[@]}" download --dir "$KIT" --first 2020-01 --last 2023-12 --procs "$WORKERS" >>"$LOG" 2>&1; then
      touch "$BASE/SEL_DOWNLOADED"; break
    fi
    grep -qE "^disk: " <(tail -5 "$LOG") && die "디스크가 모자랍니다 ($(grep -E '^disk: ' "$LOG" | tail -1))"
    [ "$k" -lt 3 ] && { say "  받기가 다 끝나지 않아 빠진 것만 이어서 다시 합니다 (${k}/3)"; sleep "$RSLEEP"; }
  done
  [ -f "$BASE/SEL_DOWNLOADED" ] \
    || die_retry "자료 받기가 세 번 해도 끝나지 않았습니다 ($(grep -E 'download failed' "$LOG" | tail -1 | cut -c1-160))"
fi
late=$(find "$KIT/raw" -type f -name '*-202[4-9]-*' 2>/dev/null | head -3 | tr '\n' ' ')
[ -z "$late" ] || die_fix "연습 기간 자료 폴더에 2024년 이후 파일이 있습니다: $late"
[ -e "$KIT_TEST" ] && [ ! -f "$BASE/PICKS_N" ] && die_fix "고르기 전인데 확인 기간 자료 폴더($KIT_TEST)가 있습니다"

# ------------------------------------------------------------------ 5 build and identity against the pinned manifest
stage 5 "받은 자료가 고정된 자료 기준과 같은지 확인 (코인마다 배열마다 sha256, 하나라도 다르면 멈춤)"
if [ -f "$BASE/SEL_VERIFIED" ]; then
  sub "건너뜀: 이미 확인했습니다"
else
  helper build "$KIT" "$BPROCS" >>"$LOG" 2>&1 || die_fix "자료 만들기 실패 (tail -50 $LOG)"
  pr=$(grep -E '^PROBLEM ' "$LOG" | tail -5 | sed 's/^PROBLEM //' | tr '\n' ' ')
  [ -n "$pr" ] && warn "자료 만들기에서 알린 것 (고정 기준과 같으면 그대로 진행): $pr"
  helper verify "$KIT" "$BASE/verify_sel.json" >>"$LOG" 2>&1 \
    || die_fix "받은 자료가 고정된 자료 기준과 다릅니다 ($(grep -E '^VERIFY' "$LOG" | tail -1 | cut -c1-200)). 계산하지 않습니다"
  touch "$BASE/SEL_VERIFIED"
fi
sub "$(grep -E '^VERIFY' "$LOG" | tail -1)"

# ------------------------------------------------------------------ 6 select (SEL only; the long step)
run_select() {
  "${HIWR[@]}" select --kit "$KIT" --work "$WORK" --private "$PRIV" --procs "$1" --eligibility "$ELIG" >>"$LOG" 2>&1
}
stage 6 "고르기 (연습 기간 2021~2023만: 조합 약 100만 개 × 청산 162가지, 작업 ${PROCS}개 동시에)"
if picks_pinned; then
  [ -s "$OUT/select.json" ] || warn "고른 것은 고정돼 있는데 select.json이 없습니다"
  sub "건너뜀: 고르기 (이미 끝나 고정됨)"
else
  touch "$BASE/SELECT_RAN"
  mkdir -p "$PRIV"
  sub "고르기 시작 (하루 이상 걸릴 수 있습니다; 진행: bash $SELF status)"
  if ! run_select "$PROCS"; then
    tail -40 "$LOG" | grep -q "REFUSED" && die_fix "고르기 거부: $(grep -E 'REFUSED' "$LOG" | tail -1 | cut -c1-200)"
    if tail -40 "$LOG" | grep -qE "tasks missing|workers keep dying"; then
      half=$(( PROCS > 2 ? PROCS / 2 : 1 ))
      sub "고르기 작업 일부가 끝나지 않아 한 번 더 이어서 합니다 (끝난 작업은 건너뜀, 작업 ${half}개)"
      run_select "$half" || die "고르기 실패 (run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
    else
      die "고르기 실패 (run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
    fi
  fi
  picks_pinned || die "고르기는 끝났는데 고른 것이 고정 파일에 없습니다"
fi

# ------------------------------------------------------------------ 7 the picks line (before any TEST byte)
stage 7 "고른 것 고정 확인 (picks.json의 sha256이 고정 파일 끝에 붙었는지; 이 뒤에만 확인 기간 자료를 받음)"
line=$(helper picks 2>>"$LOG") || die "고른 것과 고정 파일 줄이 맞지 않습니다: $line"
echo "$line" | tee -a "$LOG" > "$BASE/picks_line.txt"
P=$(sed -n 's/.*PICKS n=\([0-9]*\).*/\1/p' <<<"$line")
[ -n "$P" ] || die "고른 것 수를 읽지 못했습니다: $line"
echo "$P" > "$BASE/PICKS_N"
mkdir -p "$BASE/picks_backup"
cp "$PICKS_REL" "$PIN_REL" "$BASE/picks_backup/" 2>/dev/null
[ -f "$OUT/select.json" ] && cp "$OUT/select.json" "$BASE/picks_backup/"
sub "고른 것 ${P}개 ($(sed -n 's/.*by_tf=\([^ ]*\).*/\1/p' <<<"$line")), picks.json sha256 $(sed -n 's/.*sha256=\([0-9a-f]\{16\}\).*/\1/p' <<<"$line")…, 고정 파일과 일치"

# ------------------------------------------------------------------ 8 test (TEST once; its own download after the guards)
stage 8 "확인 기간 시험 (2024-01 ~ 2026-09, 고른 것만, 한 번만; 확인 기간 자료는 이 단계 안에서 받음)"
if [ "$P" = 0 ]; then
  warn "고른 것이 없어 확인 기간 시험을 하지 않았습니다 (확인 기간 자료도 받지 않음)"
elif [ -s "$OUT/test.json" ]; then
  sub "건너뜀: 시험 (이미 끝남)"
else
  for k in 1 2 3; do
    rc=0
    "${HIWR[@]}" test --kit "$KIT" --kit-test "$KIT_TEST" --work "$WORK" --private "$PRIV" --procs "$PROCS" \
      --no-reads "${LEDGER_ARGS[@]}" >>"$LOG" 2>&1 || rc=$?
    [ -s "$OUT/test.json" ] && break
    tail -40 "$LOG" | grep -qE "REFUSED|test.json exists" \
      && die "시험 거부: $(grep -E 'REFUSED|test.json exists' "$LOG" | tail -1 | cut -c1-200)"
    if [ "$k" -lt 3 ] && tail -40 "$LOG" | grep -qiE "download failed|urlopen error|timed out|connection (reset|refused|aborted)|temporary failure"; then
      say "  확인 기간 자료 받기가 끊겨 빠진 것만 이어서 다시 합니다 (${k}/3)"; sleep "$RSLEEP"; continue
    fi
    die "시험 실패 (종료 코드 $rc; run.log 마지막 부분을 보내 주세요: tail -50 $LOG)"
  done
  [ -s "$OUT/test.json" ] || die_retry "확인 기간 자료 받기가 세 번 해도 끝나지 않았습니다"
  sub "$(grep -E 'test done:' "$LOG" | tail -1 | sed 's/^\[hiwr [0-9:]*\] //')"
fi

# ------------------------------------------------------------------ 9 reads (never a pass; bounded in time)
reads_stage() {
  local out=$OUT/reads.json tried=$BASE/READS_TRIED rc=0 to
  [ "$P" = 0 ] && { sub "고른 것이 없어 참고 분석도 없습니다"; return 0; }
  [ -s "$OUT/test.json" ] || { warn "참고 분석: 시험 결과가 없어 건너뜀"; return 0; }
  [ -s "$out" ] && { sub "건너뜀: 참고 분석 (이미 끝남)"; return 0; }
  if [ "$(cat "$tried" 2>/dev/null)" = "$HEAD" ]; then
    warn "참고 분석은 이 코드로 이미 한 번 해 봤고 끝나지 않아 또 하지 않습니다 (개발자에게 보내 주세요)"
    return 0
  fi
  sub "참고 분석: 고른 것 ${P}개를 차례로 (최대 ${READS_HOURS}시간)"
  timeout "${READS_HOURS}h" "${HIWR[@]}" reads --kit "$KIT" --kit-test "$KIT_TEST" --work "$WORK" --private "$PRIV" \
    --procs "$PROCS" >>"$LOG" 2>&1 &
  to=$!                      # timeout runs the read in its own process group: pass a pane kill or Ctrl+C on to it
  trap 'kill -TERM "$to" 2>/dev/null; exit 1' HUP INT TERM
  wait "$to" || rc=$?
  trap - HUP INT TERM
  echo "$HEAD" > "$tried"    # after the call: a kill of the whole run leaves the one try for the next restart
  if [ "$rc" = 124 ]; then
    warn "참고 분석이 ${READS_HOURS}시간 안에 끝나지 않아 멈췄습니다 (판정은 그대로, 나머지는 그대로 묶습니다)"
  elif [ "$rc" != 0 ]; then
    warn "참고 분석 실패 (종료 코드 $rc, run.log의 [reads] 줄 참고; 판정은 그대로)"
  fi
  [ -s "$out" ] || warn "참고 분석 결과(reads.json)가 없습니다"
  return 0
}
stage 9 "참고 분석 (주말 포함·다른 레버리지·수수료 전 ROE 등; 통과 기준이 아님)"
reads_stage

# ------------------------------------------------------------------ 10 report and pack
pack() {
  local R=$BASE/results f
  rm -rf "$R"
  mkdir -p "$R/hiwr" "$R/pins" "$R/data" "$R/stamps" || return 1
  [ -d "$OUT" ] && cp -r "$OUT" "$R/hiwr/"
  [ -f "$PICKS_REL" ] && cp "$PICKS_REL" "$R/hiwr/"
  cp "$PIN_REL" "$R/pins/" || return 1
  for f in research/hiwr/data_manifest_sel.json research/hiwr/data_check_sel.json research/hiwr/data_manifest_test.json \
           "$BASE/verify_sel.json" "$BASE/picks_line.txt"; do
    [ -f "$f" ] && cp "$f" "$R/data/"
  done
  [ -f "$KIT/build.json" ] && cp "$KIT/build.json" "$R/data/kit_sel_build.json"
  [ -f "$KIT/manifest.json" ] && cp "$KIT/manifest.json" "$R/data/kit_sel_files.json"
  [ -f "$KIT_TEST/build.json" ] && cp "$KIT_TEST/build.json" "$R/data/kit_test_build.json"
  [ -f "$KIT_TEST/manifest.json" ] && cp "$KIT_TEST/manifest.json" "$R/data/kit_test_files.json"
  [ -f "$KIT_TEST/hiwr_test_kit.json" ] && cp "$KIT_TEST/hiwr_test_kit.json" "$R/data/"
  helper stamp "$R/stamps/code_stamp.json" "$BASE" "$PRIV" "$NCPU" "$PROCS" "$DRYRUN" >>"$LOG" 2>&1 || return 1
  grep -v -E "\[(monthly|gap-fill days)\] [0-9]+/[0-9]+ files" "$LOG" > "$R/run.log"
  [ -s "$BASE/WARNINGS" ] && cp "$BASE/WARNINGS" "$R/WARNINGS.txt"
  {
    echo "# 2번 트랙 결과 묶음 (bootstrap.sh $(date -u '+%Y-%m-%d %H:%M UTC'), 커밋 ${HEAD:0:10})"
    echo
    if [ "$P" = 0 ]; then echo "* 고른 것 0개: 확인 기간 시험은 하지 않았습니다 (확인 기간 자료도 받지 않음)"
    else echo "* 고른 것 ${P}개: $(cat "$BASE/picks_line.txt" 2>/dev/null)"; fi
    if [ -s "$BASE/WARNINGS" ]; then echo "* 건너뛰거나 빠진 것이 있습니다: WARNINGS.txt"; else echo "* 건너뛴 것 없음"; fi
    echo
    echo "* hiwr/out: select.json(고르기), test.json(판정), ledger.json(프로그램 전체 장부), reads.json(참고 분석), RESULTS_KO.md"
    echo "* hiwr/picks.json: 고른 것 (딥시크는 이름만, D11)"
    echo "* pins/$(basename "$PIN_REL"): 고정 파일 (고르기 뒤 picks 줄, 시험 전 확인 기간 자료·참고 분석 줄이 붙은 것)"
    echo "* data: 고정된 연습 기간 자료 기준, 이 서버 자료와의 비교(verify_sel.json), 두 자료의 build·파일 목록"
    echo "* stamps/code_stamp.json: 커밋, 설정, 파일 sha256, 패키지 버전, 단계별 시간, 비공개 파일 sha256(내용 없음)"
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
stage 10 "결과 페이지·결과 묶기"
"${HIWR[@]}" report --private "$PRIV" >>"$LOG" 2>&1 || warn "결과 페이지(RESULTS_KO.md) 쓰기 실패"
pack || die "결과 묶기 실패 (tail -50 $LOG)"
rm -f "$BASE/RUNNING"
touch "$BASE/DONE"
say "끝. 결과 $(du -h "$BASE/results.tgz" | cut -f1): $BASE/results.tgz"
if [ -s "$BASE/WARNINGS" ]; then say "참고(건너뛴 것):"; sed 's/^/  - /' "$BASE/WARNINGS" | tee -a "$LOG"; fi
say "보내기: bash $SELF push   (그다음 Vultr에서 서버 Destroy, 디스크 hiwr-disk도 삭제)"
