#!/bin/bash
# shellcheck disable=SC2329  # the check functions below are called through want()
# Reset rehearsal on COPIES (paper v4 restart, docs/server-setup-v4.md): runs deploy/paperbot-reset.sh --yes against
# consistent copies of the run's databases in a new folder under /var/lib/paperbot-rehearsal, never the real folder.
#
#     cd /root/crypto-bot-research && sudo bash deploy/rehearse-reset.sh [--agents-off]
#
# --agents-off is passed to the reset (rehearse exactly the command you will run: docs/server-setup-v4.md step 3).
# Safe while the bot runs: the copies are made with SQLite's backup API (as the services' user); the reset script gets
# a fake systemctl (it asks the real one only is-active / is-enabled / LoadState, and only logs stop, start, disable;
# starting paperbot-backup.service copies the rehearsal databases into the rehearsal's own backup folder), a stub in
# place of deploy/install.sh and the rehearsal folders for PAPERBOT_LIB / PAPERBOT_BACKUPS. Nothing on the server is
# stopped, installed, moved, sent or changed; /etc/paperbot is only read (the reset's plan warnings).
#
# Checks (exit 0 only when every one passes):
#   1. the reset finished (exit 0) and printed its summary;
#   2. the archive folder holds the old run's paper3.db and the before-reset copies of agents3.db and inbox.db;
#   3. every room of the agents3.db copy got the restart note with the paper v4 text;
#   4. the debate room and the Obsidian export were in the stop list (when installed here), the DeepSeek-200 shadow
#      test was not, the Obsidian export and the DeepSeek check were not started again, and the agents' tick was kept
#      off with --agents-off (without it: started again when it runs or is enabled here);
#   5. a paper3.db with the v4 accounts (config.v4_account_defs with the locked library's 36 names) made after the
#      reset passes launchcheck's account-set check: 331 accounts, no [고칠 것];
#   6. the rules documents (v3 and v4) match their .sha256 files, as launchcheck checks them after the start.
# The rehearsal folder stays for a look; it can be removed afterwards (it holds copies of the run's databases).
set -Eeuo pipefail

RESET_ARGS=""
for arg in "$@"; do
  case "$arg" in
    --agents-off) RESET_ARGS="$arg" ;;
    *) echo "usage: sudo bash deploy/rehearse-reset.sh [--agents-off]"; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${PAPERBOT_LIB:-/var/lib/paperbot}"
BASE="${REHEARSE_BASE:-/var/lib/paperbot-rehearsal}"
ETC="${PAPERBOT_ETC:-/etc/paperbot}"
PY="${PAPERBOT_PY:-/opt/paperbot/venv/bin/python}"
RUN_USER="${PAPERBOT_RESET_USER-paperbot}"
REAL_SYSTEMCTL="${REHEARSE_REAL_SYSTEMCTL:-systemctl}"   # asked read-only questions only
DBS="paper3 daily3 checkpoint agents3 inbox"
FILES="tradealerts.json evening-latest.json"

[ -x "$PY" ] || { echo "$PY not found"; exit 1; }
[ -f "$SRC/paper3.db" ] || { echo "$SRC/paper3.db not found: nothing to rehearse on"; exit 1; }
W="$BASE/$(date -u +%Y%m%dT%H%M%SZ)"
n=0
while [ -e "$W" ]; do n=$((n+1)); W="$BASE/$(date -u +%Y%m%dT%H%M%SZ)-$n"; done
own() { if [ -n "$RUN_USER" ]; then chown -R "$RUN_USER:$RUN_USER" "$@"; fi; }
as_user() { if [ -n "$RUN_USER" ]; then runuser -u "$RUN_USER" -- "$@"; else "$@"; fi; }
# root owns the folders root runs anything from ($W/stub: the fake systemctl and install.sh, executed by the reset
# as root); the services' user may enter $W (group) and owns only the copies ($W/lib) and the backups
install -d -m 750 "$BASE" "$W"
install -d -m 755 "$W/stub"
install -d -m 750 "$W/lib" "$W/backups"
if [ -n "$RUN_USER" ]; then chgrp "$RUN_USER" "$BASE" "$W"; fi
own "$W/lib" "$W/backups"
# commands run as the services' user from here (it cannot enter /root, where the repository usually is)
cd "$W"
echo "== 연습 폴더: $W (진짜 폴더 $SRC 는 읽기만 함)"

echo "== 1. 복사본 만들기 (SQLite backup API, 봇이 돌아도 안전)"
for db in $DBS; do
  [ -f "$SRC/$db.db" ] || { echo "  $db.db 없음(건너뜀)"; continue; }
  # shellcheck disable=SC2016  # the Python code is single-quoted on purpose
  as_user "$PY" -c '
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src, timeout=30)
d = sqlite3.connect(dst)
s.backup(d)
d.execute("PRAGMA journal_mode=DELETE")
assert d.execute("PRAGMA integrity_check").fetchone()[0] == "ok", dst
d.commit(); d.close(); s.close()
' "$SRC/$db.db" "$W/lib/$db.db"
  echo "  $db.db -> $W/lib/$db.db ($(du -sh "$W/lib/$db.db" | cut -f1))"
done
for f in $FILES; do
  if [ -f "$SRC/$f" ]; then cp -p "$SRC/$f" "$W/lib/$f"; fi
done
install -d -m 750 "$W/lib/checkpoint_bars" "$W/lib/rehearsal"
own "$W/lib"

# the fake systemctl: read-only questions go to the real one (a unit stopped here then reads "inactive" until it is
# started here again), stop / start / disable are only logged; starting the backup unit copies the rehearsal databases
# like paperbot-backup.sh
cat > "$W/stub/systemctl" <<STUB
#!/bin/bash
echo "\$*" >> "$W/stub/systemctl.log"
cmd="\$1"; shift
u="\${*: -1}"
case "\$cmd" in
  is-active)
    if grep -qx "\$u" "$W/stub/stopped" 2>/dev/null; then [ "\$1" = --quiet ] || echo inactive; exit 3; fi
    exec "$REAL_SYSTEMCTL" is-active "\$@" ;;
  is-enabled) exec "$REAL_SYSTEMCTL" is-enabled "\$@" ;;
  show)
    case "\$*" in
      *LoadState*) exec "$REAL_SYSTEMCTL" show "\$@" ;;
      *) echo success ;;
    esac ;;
  stop) for x in "\$@"; do echo "\$x" >> "$W/stub/stopped"; done ;;
  start)
    for x in "\$@"; do
      grep -vxF -- "\$x" "$W/stub/stopped" > "$W/stub/stopped.tmp"; cat "$W/stub/stopped.tmp" > "$W/stub/stopped"
      if [ "\$x" = paperbot-backup.service ]; then
        d="$W/backups/\$(date -u +%Y%m%d)"; mkdir -p "\$d"
        for db in $DBS; do [ -f "$W/lib/\$db.db" ] && cp "$W/lib/\$db.db" "\$d/\$db.db"; done
      fi
    done ;;
  *) ;;
esac
exit 0
STUB
# shellcheck disable=SC2016  # the stub prints the variable when it runs
printf '#!/bin/bash\necho "install.sh (연습: 설치 안 함) PAPERBOT_RESETTING=${PAPERBOT_RESETTING:-}"\n' > "$W/stub/install.sh"
chmod 755 "$W/stub/systemctl" "$W/stub/install.sh"
: > "$W/stub/stopped"

echo "== 2. 연습 리셋 (deploy/paperbot-reset.sh --yes${RESET_ARGS:+ $RESET_ARGS}, 복사본에)"
set +e
PAPERBOT_LIB="$W/lib" PAPERBOT_ETC="$ETC" PAPERBOT_PY="$PY" PAPERBOT_RESET_USER="$RUN_USER" \
  PAPERBOT_SYSTEMCTL="$W/stub/systemctl" PAPERBOT_INSTALL="$W/stub/install.sh" PAPERBOT_BACKUPS="$W/backups" \
  PAPERBOT_RESET_HM=1200 PAPERBOT_RESET_WAIT=0 PAPERBOT_RESET_POLL="${PAPERBOT_RESET_POLL:-10}" \
  bash "$REPO_DIR/deploy/paperbot-reset.sh" --yes ${RESET_ARGS:+"$RESET_ARGS"} > "$W/reset.out" 2>&1
rc=$?
set -e
sed 's/^/  | /' "$W/reset.out"

echo "== 3. 확인"
FAILS=0
want() {      # want "<what>" <command...>: [OK] when the command succeeds, else [실패]
  local msg="$1"
  shift
  if "$@"; then echo "[OK] $msg"; else echo "[실패] $msg"; FAILS=$((FAILS+1)); fi
}
arch="$(find "$W/lib/archive" -mindepth 1 -maxdepth 1 -type d -name 'run-*' 2>/dev/null | head -1 || true)"
archived() { [ -n "$arch" ] && [ -f "$arch/paper3.db" ] && [ -f "$arch/agents3-before-reset.db" ] && [ -f "$arch/inbox-before-reset.db" ]; }
moved() { [ ! -e "$W/lib/paper3.db" ]; }
stopped_unit() { grep -q "^stop .*\b$1\b" "$W/stub/systemctl.log"; }
not_stopped_shadow() { ! grep -q '^stop .*shadow200' "$W/stub/systemctl.log"; }
agents_kept_off() { ! grep -q '^start .*paperbot-agents\.timer' "$W/stub/systemctl.log"; }
agents_back() { grep -q '^start .*paperbot-agents\.timer' "$W/stub/systemctl.log"; }
after_check_kept_off() { ! grep -q -E '^start .*paperbot-(obsidian|dscheck)\.timer' "$W/stub/systemctl.log"; }
rooms_told() {
  # shellcheck disable=SC2016  # Python code
  as_user "$PY" -c '
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
rooms = c.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
told = c.execute("SELECT COUNT(DISTINCT room_id) FROM notes WHERE text LIKE ? AND text LIKE ?",
                 ("%처음부터 다시 시작함 (paper v4:%", "%331%")).fetchone()[0]
print(f"  방 {rooms}곳, v4 재시작 메모가 있는 방 {told}곳")
sys.exit(0 if rooms and told == rooms else 1)
' "$W/lib/agents3.db"
}
v4_accounts_pass() {
  # as root, from the repository (the code being rehearsed); the database it makes is a scratch copy
  # shellcheck disable=SC2016  # Python code
  (cd "$REPO_DIR" && "$PY" -c '
import sys, time
from paperbot import sweepsig
from paperbot.config import V4_VERSION, v4_account_defs
from paperbot.launchcheck import account_set_lines, read_paper_db
from paperbot.sigservice import strategy_names
from paperbot.store3 import Store3
path = sys.argv[1]
st = Store3(path)
now = int(time.time() * 1000)
for d in v4_account_defs(strategy_names(sweepsig.lib())):
    aid = d["strategy"] + "@" + d["timeframe"]
    st.add_account(aid, d["strategy"], d["timeframe"], d["kind"], now, V4_VERSION, None, d["data"])
st.close()
lines = account_set_lines(read_paper_db(path))
for s, t in lines:
    print(f"  [{s}] {t}")
sys.exit(0 if lines and all(s == "OK" for s, _ in lines) else 1)
' "$W/lib/paper3.db")
}
rules_hashed() {
  # shellcheck disable=SC2016  # Python code
  (cd "$REPO_DIR" && "$PY" -c '
import sys
from paperbot.launchcheck import rules_lines
lines = rules_lines(sys.argv[1])
for s, t in lines:
    print(f"  [{s}] {t}")
sys.exit(0 if all(s == "OK" for s, _ in lines) else 1)
' "$REPO_DIR")
}
want "규칙 문서(v3·v4)가 해시 파일과 같음 (launchcheck와 같은 점검)" rules_hashed
want "리셋 스크립트가 끝까지 감 (종료 코드 $rc)" [ "$rc" = 0 ]
want "요약이 나옴" grep -q "요약" "$W/reset.out"
want "보관 폴더에 이전 paper3.db와 agents3·inbox 사본이 있음 (${arch:-없음})" archived
want "paper3.db는 보관 폴더로 옮겨짐(새 실행 자리가 비었음)" moved
want "직원 기록(agents3.db 사본)의 모든 방에 paper v4 재시작 메모" rooms_told
for u in paperbot-debate paperbot-obsidian.timer; do
  if [ "$("$REAL_SYSTEMCTL" show -p LoadState --value "$u" 2>/dev/null || true)" = loaded ]; then
    want "$u 멈춤 목록에 있음" stopped_unit "$u"
  else
    echo "[참고] $u 는 이 서버에 설치돼 있지 않음(멈출 것 없음)"
  fi
done
want "딥시크 200 그림자 시험(shadow200)은 멈추지 않음" not_stopped_shadow
want "옵시디언 내보내기·딥시크 밤 재계산 타이머는 다시 켜지 않음(점검 뒤 두 분이 켬)" after_check_kept_off
if [ -n "$RESET_ARGS" ]; then
  want "에이전트 회의 타이머는 다시 켜지 않음(--agents-off)" agents_kept_off
elif "$REAL_SYSTEMCTL" is-active --quiet paperbot-agents.timer 2>/dev/null \
     || "$REAL_SYSTEMCTL" is-enabled --quiet paperbot-agents.timer 2>/dev/null; then
  want "에이전트 회의 타이머는 다시 켬(--agents-off 없음, 지금 켜져 있음)" agents_back
else
  echo "[참고] 에이전트 회의 타이머가 지금 꺼져 있어 리셋 뒤에도 꺼진 채입니다"
fi
if moved; then
  want "v4 계좌표로 만든 paper3.db가 launchcheck 계좌 점검 통과 (331개, [고칠 것] 없음)" v4_accounts_pass
else
  echo "[실패] 새 paper3.db 자리가 비지 않아 v4 계좌 점검을 건너뜀"; FAILS=$((FAILS+1))
fi
echo
if [ "$FAILS" = 0 ]; then
  echo "[OK] 연습 리셋 통과. 연습 폴더 $W 는 확인 뒤 지워도 됩니다(진짜 실행과 무관)."
  exit 0
fi
echo "[실패 $FAILS개] 위 [실패] 줄과 $W/reset.out 을 개발자에게 보내세요. 진짜 리셋은 하지 마세요."
exit 1
