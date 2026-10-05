#!/usr/bin/env bash
# Dashboard-only update (paper v4): copy paperbot/dash/ from this checkout into the installed tree and restart ONLY
# the dashboard. The bot, the trade alerts, the agents and every scheduled job keep running, and the 30-day
# experiment is not touched (no trading file changes; the script refuses when any other file differs).
#
#   cd /root/crypto-bot-research && git pull && sudo bash deploy/update-dash.sh            # update
#   cd /root/crypto-bot-research && sudo bash deploy/update-dash.sh --rollback              # back to the previous dashboard
#
# What it does: 1) refuses uncommitted changes; 2) compares this checkout with the installed tree file by file and
# refuses when anything outside paperbot/dash/, docs/ or tests/ differs (that needs the full procedure); 3) copies
# paperbot/dash/ next to the installed one, swaps it in (the old one stays as paperbot/dash.old), records the commit
# in DASH_VERSION.json; 4) restarts paperbot-dash and checks it answers; if it does not, swaps the old one back.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="${PAPERBOT_APP:-/opt/crypto-bot-research}"
PY="${PAPERBOT_PY:-python3}"
SYSTEMCTL="${PAPERBOT_SYSTEMCTL:-systemctl}"
WAIT_S="${PAPERBOT_DASH_WAIT_S:-30}"
GROUP="${PAPERBOT_GROUP:-paperbot}"

[ "$(id -u)" = 0 ] || { echo "sudo로 실행하세요: sudo bash deploy/update-dash.sh"; exit 1; }
[ -d "$APP/paperbot/dash" ] || { echo "$APP/paperbot/dash 가 없습니다: 전체 설치(install.sh)가 먼저입니다"; exit 1; }

check_up() {
  # active, and the login page answers on DASH_HOST:8080 (any HTTP answer counts; no password is sent)
  local host="" n=0
  if [ -r /etc/paperbot/dash.env ]; then
    host="$(sed -n 's/^DASH_HOST=//p' /etc/paperbot/dash.env | tail -1 | tr -d '"'"'"' ')"
  fi
  while [ "$n" -lt "$WAIT_S" ]; do
    if "$SYSTEMCTL" is-active --quiet paperbot-dash; then
      if [ -z "$host" ] || ! command -v curl >/dev/null 2>&1; then return 0; fi
      if curl -s -o /dev/null -m 3 "http://$host:8080/login"; then return 0; fi
    fi
    n=$((n+1)); sleep 1
  done
  return 1
}

if [ "${1:-}" = "--rollback" ]; then
  [ -d "$APP/paperbot/dash.old" ] || { echo "되돌릴 이전 대시보드(dash.old)가 없습니다"; exit 1; }
  mv "$APP/paperbot/dash" "$APP/paperbot/dash.bad"
  mv "$APP/paperbot/dash.old" "$APP/paperbot/dash"
  rm -rf "$APP/paperbot/dash.bad"
  "$SYSTEMCTL" restart paperbot-dash
  if check_up; then
    echo "이전 대시보드로 되돌렸습니다 (봇은 계속 돌고 있음)"
  else
    echo "대시보드가 응답하지 않습니다: sudo journalctl -u paperbot-dash -n 50"; exit 1
  fi
  exit 0
fi
[ -z "${1:-}" ] || { echo "사용법: sudo bash deploy/update-dash.sh [--rollback]"; exit 1; }

if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  echo "저장소에 커밋하지 않은 변경이 있습니다: 커밋된 코드만 올립니다"; exit 1
fi
COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"

echo "== 바뀐 파일 확인 (대시보드 밖이 바뀌었으면 멈춤)"
"$PY" - "$REPO_DIR" "$APP" <<'PYEOF'
import hashlib, os, sys
repo, app = sys.argv[1], sys.argv[2]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}
SKIP_FILES = {"VERSION.json", "DASH_VERSION.json"}
ALLOWED = ("paperbot/dash/", "paperbot/dash.old/", "docs/", "tests/")
def files(root, other):
    """{relative path: fingerprint}. A file whose size and mtime equal the other tree's copy (install.sh copies with
    cp -a, which keeps mtimes) is not read; any other file is hashed, so a big research folder costs nothing."""
    out = {}
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for n in names:
            if n in SKIP_FILES or n.endswith((".pyc", ".pyo")):
                continue
            p = os.path.join(d, n)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            st, q = os.stat(p), os.path.join(other, rel)
            try:
                so = os.stat(q)
                if so.st_size == st.st_size and so.st_mtime_ns == st.st_mtime_ns:
                    out[rel] = f"same:{st.st_size}"
                    continue
            except OSError:
                pass
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = h.hexdigest()
    return out
a, b = files(repo, app), files(app, repo)
diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
bad = [k for k in diff if not k.startswith(ALLOWED)]
dash = [k for k in diff if k.startswith("paperbot/dash/")]
if bad:
    print("대시보드 밖의 파일이 설치본과 다릅니다. 이 업데이트로는 올릴 수 없습니다 (전체 절차 필요):")
    for k in bad[:20]:
        print("  " + k)
    if len(bad) > 20:
        print(f"  … 외 {len(bad) - 20}개")
    sys.exit(2)
print(f"대시보드 파일 {len(dash)}개가 바뀜, 그 밖은 같음")
PYEOF

echo "== 대시보드 파일 교체 (봇은 그대로)"
rm -rf "$APP/paperbot/dash.new"
cp -a "$REPO_DIR/paperbot/dash" "$APP/paperbot/dash.new"
find "$APP/paperbot/dash.new" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R "root:$GROUP" "$APP/paperbot/dash.new"
chmod -R g+rX,o-rwx "$APP/paperbot/dash.new"
rm -rf "$APP/paperbot/dash.old"
mv "$APP/paperbot/dash" "$APP/paperbot/dash.old"
mv "$APP/paperbot/dash.new" "$APP/paperbot/dash"
printf '{"commit": "%s", "source": "update-dash.sh", "installed_at": "%s"}\n' "$COMMIT" "$(date -u +%FT%TZ)" \
  > "$APP/DASH_VERSION.json"
chown "root:$GROUP" "$APP/DASH_VERSION.json"; chmod 640 "$APP/DASH_VERSION.json"

echo "== 대시보드만 다시 시작"
"$SYSTEMCTL" restart paperbot-dash
if check_up; then
  echo "대시보드 업데이트 완료: $COMMIT (봇·알림·에이전트는 멈추지 않았습니다)"
else
  echo "새 대시보드가 응답하지 않아 이전 것으로 되돌립니다"
  mv "$APP/paperbot/dash" "$APP/paperbot/dash.bad"
  mv "$APP/paperbot/dash.old" "$APP/paperbot/dash"
  rm -rf "$APP/paperbot/dash.bad" "$APP/DASH_VERSION.json"
  "$SYSTEMCTL" restart paperbot-dash
  echo "되돌림. 원인: sudo journalctl -u paperbot-dash -n 50"
  exit 1
fi
