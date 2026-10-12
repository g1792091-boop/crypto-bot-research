#!/usr/bin/env bash
# 후보 리그 (candidate league) install on the rule bot's server (docs/candleague-ko.md, candleague/CONTRACT.md 3).
#
#   sudo bash deploy/candleague/install_candleague.sh          # from a clone of this repository (/root/candleague-src)
#
# Safe to run again (an update = git pull, then the same command): system user candleague, /var/lib/candleague
# (+ snap/), /etc/candleague, the env file from the template ONLY when it is missing (never printed), the venv
# /opt/candleague/venv, a copy of only the code paths the league needs into /opt/candleague/app (staged in app.new,
# checked as the candleague user, then swapped; the previous copy stays in app.old), the systemd units (engine,
# dashboard, the 10-minute watch). Starts the engine and the watch only when a checked candidate list is in the code
# (candleague/data/candidates.json) and the dashboard only when its password, secret and address are set
# (deploy/candleague/setup_env.sh fills them, with Telegram); the dashboard port opens on Tailscale only (firewall.sh).
# Never touches the rule bot or the demo lab: none of their units or folders.
# When the new code starts the league over (another candidate list or calculation; 2026-10-12: the league now starts at
# its install time instead of a replay from 10/01), the whole old league.db is copied next to it first, with the engine
# stopped (also when it was crash-looping), before the code swap (e.g.
# /var/lib/candleague/league_replay_from_1001_20261012.db; the engine finds that copy and does not copy again), and the
# start it will use is printed ("새 시작: 10/11 12:00 KST"); if the copy fails, nothing is swapped. Never shown on the
# dashboard. app.old (the previous copy) is NOT a way back past 2026-10-12: code from before that starts the league
# over from 10/01 again without a copy (the start itself survives in league_start.json).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$REPO_DIR/deploy/candleague"
APP=/opt/candleague/app
VENV=/opt/candleague/venv
LIB=/var/lib/candleague
SNAP=$LIB/snap
ETC=/etc/candleague
ENVF=$ETC/candleague.env
UNITS="candleague-live.service candleague-dash.service candleague-watch.service candleague-watch.timer"
# the only paths copied from the repository
CODE_PATHS="candleague paperbot third_party/sweep research/entry_study/param_defs research/entry_study/strength_defs \
research/entry_study/sr.py research/entry_study/DEFS_BC.sha256 research/deepseek200/lib_c.py research/library \
research/search research/fullgrid/ds_defs.py research/fullgrid/exchange.json"
PIP_PKGS="numpy pandas scipy fastapi uvicorn"

if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
if [ ! -d "$REPO_DIR/candleague" ] || [ ! -f "$HERE/candleague-live.service" ]; then
  echo "복제한 저장소 안에서 실행하세요 (예: sudo bash /root/candleague-src/deploy/candleague/install_candleague.sh)"; exit 1
fi
case "$REPO_DIR" in /opt/candleague*) echo "run it from the cloned repository, not from /opt/candleague"; exit 1 ;; esac

envval() {
  local v
  v="$(grep -E "^$1=" "$ENVF" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}
dash_ready() {
  local h s
  h="$(envval CANDLEAGUE_DASH_PASSWORD_HASH)"; s="$(envval CANDLEAGUE_DASH_SECRET)"
  [[ "$h" == pbkdf2\$* ]] && [ "${#s}" -ge 32 ] && [ -n "$(envval CANDLEAGUE_DASH_HOST)" ]
}

echo "== 확인 (python, 디스크, 메모리)"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "python3 3.10 이상이 필요합니다 (지금: $(python3 --version 2>&1 || echo 없음))"; exit 1
fi
if ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
  echo "python3-venv가 없습니다. 먼저: sudo apt-get install -y python3-venv"; exit 1
fi
FREE_MB="$(df -Pk /opt 2>/dev/null | awk 'NR == 2 { printf "%.0f", $4 / 1024 }')"
if [ "${FREE_MB:-0}" -lt 1024 ]; then echo "디스크 남은 공간이 ${FREE_MB:-?} MB입니다 (1 GB 이상 필요)."; exit 1; fi
AVAIL_MB="$(awk '/MemAvailable/ { printf "%.0f", $2 / 1024 }' /proc/meminfo)"
echo "남은 메모리 ${AVAIL_MB} MB (후보 리그는 최대 1.3 GB + 대시보드 0.3 GB까지만 쓰도록 묶여 있습니다)"
if [ "${AVAIL_MB:-0}" -lt 2000 ] && [ "${FORCE:-0}" != "1" ]; then
  echo "남은 메모리가 2 GB보다 적습니다. 규칙봇 30일 판정에 영향이 없도록 여기서 멈춥니다."
  echo "작은 서버를 따로 쓰거나, 개발자와 상의한 뒤 FORCE=1 로 다시 실행하세요."; exit 1
fi

echo "== code version"
COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
for p in $CODE_PATHS; do
  [ -e "$REPO_DIR/$p" ] || { echo "저장소에 없습니다: $p (git pull 후 다시 실행하세요)"; exit 1; }
done
# shellcheck disable=SC2086
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no -- $CODE_PATHS deploy/candleague 2>/dev/null)" ]; then
  echo "the repository has uncommitted changes in the league's paths; deploy only committed code"; exit 1
fi
echo "commit $COMMIT"

echo "== user and folders"
if ! id candleague >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$LIB" --no-create-home --shell /usr/sbin/nologin candleague
fi
if [ "$(id -u candleague)" = 0 ] || id -nG candleague | tr ' ' '\n' | grep -qxE 'paperbot|demobot'; then
  echo "user candleague must be its own user (not root, not in group paperbot or demobot)"; exit 1
fi
install -d -o root -g root -m 755 /opt/candleague
install -d -o candleague -g candleague -m 750 "$LIB"
install -d -o candleague -g candleague -m 750 "$SNAP"
install -d -o root -g candleague -m 750 "$ETC"

echo "== env file (template only when missing; values are never printed)"
if [ ! -f "$ENVF" ]; then
  install -o root -g candleague -m 640 "$HERE/candleague.env.example" "$ENVF"
  echo "made $ENVF from the template (empty values)"
else
  echo "$ENVF exists: kept as it is"
  # owners 2026-10-11 ("딥시크 쪽은 왜 금액없이야 똑같이 해야지"): the old template's hidden DeepSeek money becomes shown,
  # once; a 0 written after this (marked file) stays 0
  if grep -qx 'CANDLEAGUE_DS_MONEY=0' "$ENVF" && ! grep -q '^# ds-money-shown-2026-10-11' "$ENVF"; then
    sed -i 's/^CANDLEAGUE_DS_MONEY=0$/CANDLEAGUE_DS_MONEY=1/' "$ENVF"
    printf '%s\n' '# ds-money-shown-2026-10-11 (두 분 요청으로 딥시크 금액 보이기로 바꿈; 숨기려면 위 값을 0으로)' >> "$ENVF"
    echo "딥시크 금액: 보이기로 바꿨습니다 (두 분 요청, 숨기려면 CANDLEAGUE_DS_MONEY=0)"
  fi
fi
chown root:candleague "$ENVF"
chmod 640 "$ENVF"

echo "== python venv ($VENV)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
SPECS=()
for p in $PIP_PKGS; do
  spec="$(grep -E "^${p}([<>=!~ ;]|$)" "$REPO_DIR/requirements.txt" 2>/dev/null | head -n 1 | tr -d ' ' || true)"
  SPECS+=("${spec:-$p}")
done
"$VENV/bin/pip" install -q --disable-pip-version-check "${SPECS[@]}"
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "$APP" > "$SITE/candleague-app.pth"

echo "== code (staged in $APP.new)"
rm -rf "$APP.new"
install -d -m 750 "$APP.new"
# shellcheck disable=SC2086
tar -C "$REPO_DIR" --exclude='__pycache__' --exclude='*.pyc' --exclude='paperbot/dash/static' -cf - $CODE_PATHS \
  | tar -C "$APP.new" -xf -
printf '{"commit": "%s", "source": "install_candleague.sh", "installed_at": "%s"}\n' "$COMMIT" \
  "$(date -u +%FT%TZ)" > "$APP.new/VERSION.json"
"$VENV/bin/python" -m compileall -q "$APP.new" >/dev/null 2>&1 || true
# the league's own code must compile (a module imported only later, e.g. the checkpoint one, would otherwise fail on its day)
if ! CL_OUT="$("$VENV/bin/python" -m compileall -q -f "$APP.new/candleague" 2>&1)"; then
  printf '%s\n' "$CL_OUT" | tail -n 20
  rm -rf "$APP.new"
  echo "selfcheck failed (the league code does not compile): nothing was changed. 이 화면을 개발자에게 보내 주세요."; exit 1
fi
chown -R root:candleague "$APP.new"
chmod -R u+rwX,g+rX,g-w,o-rwx "$APP.new"

echo "== selfcheck of the new code (before the swap; as user candleague)"
CANDS=0
[ -f "$APP.new/candleague/data/candidates.json" ] && CANDS=1
set +e
SC_OUT="$(cd "$APP.new" && runuser -u candleague -- env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$LIB" \
  PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -c '
import sys
from paperbot import sweepsig
sweepsig.lib()                                     # the locked signal library loads (hash-checked)
from candleague import candidates, checkpoint, dash, league, notify, runner, summary, watch
from paperbot.config import V3_SYMBOLS
runner.load_exchange(runner.EXCHANGE_FILE, V3_SYMBOLS)   # the leverage table and order-size rules of the study
print(len(candidates.ds_defs().DEFS), "DeepSeek definitions load")
if sys.argv[1] == "1":
    c = candidates.load()
    print(f"{len(c)} candidates ok")
print("selfcheck ok")
' "$CANDS" 2>&1)"
SC_RC=$?
set -e
printf '%s\n' "$SC_OUT" | tail -n 20
if [ "$SC_RC" -ne 0 ]; then
  rm -rf "$APP.new"
  echo "selfcheck failed (exit $SC_RC): nothing was changed. 이 화면을 개발자에게 보내 주세요."; exit 1
fi

echo "== systemd units"
for u in $UNITS; do install -m 644 "$HERE/$u" "/etc/systemd/system/$u"; done
systemctl daemon-reload

# what to bring back if this update stops before the swap: every unit that is running OR waiting to restart (a
# crash-looping engine is "activating", not "active")
RUNNING=""
for u in $UNITS; do
  case "$(systemctl is-active "$u" 2>/dev/null || true)" in active|activating|reloading) RUNNING="$RUNNING $u" ;; esac
done
# stop the engine and the watch whatever their state: stopping also cancels a pending automatic restart, so the old
# engine cannot start again (and write more) while its record is copied and the code is swapped
# shellcheck disable=SC2086
systemctl stop candleague-live.service candleague-watch.timer candleague-watch.service $RUNNING 2>/dev/null || true
if systemctl is-active --quiet candleague-live.service 2>/dev/null; then
  rm -rf "$APP.new"
  # shellcheck disable=SC2086
  [ -n "$RUNNING" ] && systemctl start $RUNNING 2>/dev/null || true
  echo "엔진을 멈추지 못해 바꾸지 않았습니다. 이 화면을 개발자에게 보내 주세요: systemctl status candleague-live --no-pager"; exit 1
fi

echo "== league record (copied before a start-over; the engine is stopped)"
LEAGUE_DB="$(envval CANDLEAGUE_DB)"; LEAGUE_DB="${LEAGUE_DB:-$LIB/league.db}"
CAND_FILE="$(envval CANDLEAGUE_CANDIDATES)"
START_VAL="$(envval CANDLEAGUE_START)"
if [ -f "$LEAGUE_DB" ] && [ "$CANDS" = 1 ]; then
  set +e
  BK_OUT="$(cd "$APP.new" && runuser -u candleague -- env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$LIB" \
    PYTHONDONTWRITEBYTECODE=1 CANDLEAGUE_DB="$LEAGUE_DB" ${CAND_FILE:+CANDLEAGUE_CANDIDATES="$CAND_FILE"} \
    ${START_VAL:+CANDLEAGUE_START="$START_VAL"} "$VENV/bin/python" -m candleague backup 2>&1)"
  BK_RC=$?
  set -e
  printf '%s\n' "$BK_OUT" | tail -n 8
  if [ "$BK_RC" -ne 0 ]; then
    # like the selfcheck: nothing swapped, the old engine back as it was
    rm -rf "$APP.new"
    # shellcheck disable=SC2086
    [ -n "$RUNNING" ] && systemctl start $RUNNING 2>/dev/null || true
    echo "기록 복사 단계가 실패해 아무것도 바꾸지 않았습니다 (exit $BK_RC, 이유는 위 줄; 이전 코드가 그대로 돕니다). 이 화면을 개발자에게 보내 주세요."; exit 1
  fi
else
  echo "기록 없음 또는 후보 목록 없음: 복사할 것 없음"
fi
rm -rf "$APP.old"
[ -d "$APP" ] && mv "$APP" "$APP.old"
mv "$APP.new" "$APP"
echo "code swapped: $APP"

if [ "$CANDS" = 1 ]; then
  systemctl enable --quiet candleague-live.service
  systemctl restart candleague-live.service || echo "엔진을 켜지 못했습니다: journalctl -u candleague-live -n 40 --no-pager"
  systemctl enable --quiet --now candleague-watch.timer || echo "감시 타이머를 켜지 못했습니다: systemctl status candleague-watch.timer"
  echo "엔진: 켜짐 (켠 때부터 계산합니다. 새로 시작한 때는 처음 시작 시각부터 지금까지 따라잡느라 몇 분~수십 분: journalctl -u candleague-live -f)"
  echo "감시: 10분마다 (엔진이 1시간 넘게 멈추면 텔레그램으로 [후보 리그] 알림)"
else
  echo "엔진: 후보 목록(candleague/data/candidates.json)이 아직 없어 켜지 않았습니다. 후보가 정해지면 git pull 후 다시 실행하세요."
fi
echo "== firewall (dashboard on Tailscale only)"
bash "$HERE/firewall.sh" || echo "firewall check failed (nothing else is affected): sudo bash $HERE/firewall.sh"
if dash_ready; then
  systemctl enable --quiet candleague-dash.service
  systemctl restart candleague-dash.service || echo "대시보드를 켜지 못했습니다: journalctl -u candleague-dash -n 40 --no-pager"
  echo "대시보드: http://$(envval CANDLEAGUE_DASH_HOST):$(envval CANDLEAGUE_DASH_PORT || echo 8091)"
else
  echo "대시보드: 비밀번호·비밀값·주소가 아직 없어 켜지 않았습니다. 다음 명령 하나로 채웁니다 (텔레그램도 함께):"
  echo "  sudo bash $HERE/setup_env.sh"
fi
echo "끝."
