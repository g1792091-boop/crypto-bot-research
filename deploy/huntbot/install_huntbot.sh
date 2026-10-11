#!/usr/bin/env bash
# 추세 사냥 모의 봇 (huntbot) install on its own new server (docs/huntbot-ko.md): Vultr Tokyo, Ubuntu 24.04,
# hostname hunt-judge. Paper only: public Binance bars, no exchange key, no order code.
#
#   bash /root/huntbot-src/deploy/huntbot/install_huntbot.sh        (as root, from a clone checked out at the commit)
#
# Safe to run again (an update = git fetch + checkout of the new commit, then the same command). What it does:
#  1. packages (python3-venv, git, sqlite3), the system user huntbot, /opt/huntbot (code, venv), /var/lib/huntbot
#     (data: store.db, events.db, run.db, snap/, private/), /etc/huntbot (the env file from the template ONLY when it
#     is missing; values are never printed);
#  2. the venv with the backtest's own versions (numpy 2.0.2, pandas 2.3.3, numba 0.60.0: the same numbers as the hunt
#     run), scipy, fastapi, uvicorn;
#  3. the code of the checked-out COMMIT (git archive: exactly what is committed, never the working tree) for the paths
#     the bot needs, staged in app.new, checked as user huntbot (the hunt engine API, the full grid's pins, every entry
#     cell once on synthetic bars, numba compiled), then swapped (the previous copy stays in app.old);
#  4. the systemd units huntbot-feed (bars; its first passes download the history from 2025-01-01, ~30-40 minutes),
#     huntbot-run (the replay runner), huntbot-dash (the dashboard, only once its password and address are set:
#     setup_env.sh), and the firewall check (dashboard on Tailscale only).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$REPO_DIR/deploy/huntbot"
APP=/opt/huntbot/app
VENV=/opt/huntbot/venv
LIB=/var/lib/huntbot
ETC=/etc/huntbot
ENVF=$ETC/huntbot.env
UNITS="huntbot-feed.service huntbot-run.service huntbot-dash.service"
# the only paths copied from the repository (the hunt engine and every module its entry definitions load). Of the rule
# bot only the files the hunt's signal path loads (research/hunt/hunt.py signal_path_files("wide"); the 장세 label
# and its imports): never its exchange, testnet, live or executor code (tests/test_huntbot_install.py checks the list)
PAPERBOT_FILES="paperbot/__init__.py paperbot/config.py paperbot/dash/__init__.py paperbot/dash/tools/__init__.py \
paperbot/dash/tools/regime5y.py paperbot/engine.py paperbot/entry_marks.py paperbot/ladder.py paperbot/levrule.py \
paperbot/margin.py paperbot/models.py paperbot/notify.py paperbot/policy.py paperbot/sizing.py paperbot/sweepsig.py"
CODE_PATHS="huntbot research/hunt research/fullgrid research/entry_study research/deepseek200 \
research/library research/search research/famous third_party/sweep $PAPERBOT_FILES"
DROP="research/entry_study/out research/entry_study/out_binance research/famous/out research/fullgrid/dump_exchange.py \
research/hunt/dump_exchange30.py"
# no file of the copy may hold an order path or an exchange key name (paper only)
ORDER_RE='/fapi/v1/order|/fapi/v2/account|X-MBX-APIKEY|api_secret|BINANCE_API_KEY'
APT_LOCK="-o DPkg::Lock::Timeout=600"     # a new server's unattended-upgrades holds the apt lock for a few minutes
PIP_PKGS="numpy==2.0.2 pandas==2.3.3 numba==0.60.0 scipy>=1.11 fastapi>=0.110 uvicorn>=0.29"

if [ "$(id -u)" -ne 0 ]; then echo "root로 실행하세요: sudo bash $0"; exit 1; fi
if [ ! -f "$REPO_DIR/huntbot/runner.py" ] || [ ! -f "$HERE/huntbot-run.service" ]; then
  echo "복제한 저장소 안에서 실행하세요 (예: bash /root/huntbot-src/deploy/huntbot/install_huntbot.sh)"; exit 1
fi
case "$REPO_DIR" in /opt/huntbot*) echo "run it from the cloned repository, not from /opt/huntbot"; exit 1 ;; esac

envval() {
  local v
  v="$(grep -E "^$1=" "$ENVF" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}
dash_ready() {
  local h s
  h="$(envval HUNTBOT_DASH_PASSWORD_HASH)"; s="$(envval HUNTBOT_DASH_SECRET)"
  [ -n "$(envval HUNTBOT_DASH_HOST)" ] && { [ "$(envval HUNTBOT_DASH_OPEN)" = "1" ] || { [[ "$h" == pbkdf2\$* ]] && [ "${#s}" -ge 32 ]; }; }
}

echo "== 1. 꾸러미 (python3-venv, git, sqlite3)"
if ! python3 -c 'import ensurepip, venv' 2>/dev/null || ! command -v git >/dev/null || ! command -v sqlite3 >/dev/null; then
  # shellcheck disable=SC2086
  apt-get $APT_LOCK update -y -q >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get $APT_LOCK install -y -q python3-venv git sqlite3 >/dev/null
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "python3 3.10 이상이 필요합니다 (지금: $(python3 --version 2>&1))"; exit 1
fi
FREE_GB="$(df -Pk / | awk 'NR == 2 { printf "%.0f", $4 / 1048576 }')"
if [ "${FREE_GB:-0}" -lt 5 ]; then echo "디스크 남은 공간이 ${FREE_GB} GB입니다 (5 GB 이상 필요)."; exit 1; fi

echo "== code version"
COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD)"
for p in $CODE_PATHS; do
  git -C "$REPO_DIR" cat-file -e "$COMMIT:$p" 2>/dev/null || { echo "커밋 $COMMIT 에 없습니다: $p"; exit 1; }
done
echo "commit $COMMIT"

echo "== user and folders"
if ! id huntbot >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$LIB" --no-create-home --shell /usr/sbin/nologin huntbot
fi
if [ "$(id -u huntbot)" = 0 ]; then echo "user huntbot must not be root"; exit 1; fi
install -d -o root -g root -m 755 /opt/huntbot
install -d -o huntbot -g huntbot -m 750 "$LIB" "$LIB/snap" "$LIB/numba"
install -d -o huntbot -g huntbot -m 700 "$LIB/private"
install -d -o root -g huntbot -m 750 "$ETC"

echo "== env file (template only when missing; values are never printed)"
if [ ! -f "$ENVF" ]; then
  install -o root -g huntbot -m 640 "$HERE/huntbot.env.example" "$ENVF"
  echo "made $ENVF from the template (empty values: sudo bash $HERE/setup_env.sh fills them)"
else
  echo "$ENVF exists: kept as it is"
fi
chown root:huntbot "$ENVF"
chmod 640 "$ENVF"

echo "== python venv ($VENV)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
# shellcheck disable=SC2086
"$VENV/bin/pip" install -q --disable-pip-version-check $PIP_PKGS
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "$APP" > "$SITE/huntbot-app.pth"

echo "== code of commit ${COMMIT:0:12} (staged in $APP.new)"
rm -rf "$APP.new"
install -d -m 755 "$APP.new"
# shellcheck disable=SC2086
git -C "$REPO_DIR" archive --format=tar "$COMMIT" -- $CODE_PATHS | tar -C "$APP.new" -xf -
for d in $DROP; do rm -rf "${APP:?}.new/$d"; done
if grep -rlE "$ORDER_RE" --include='*.py' --include='*.js' --include='*.sh' "$APP.new" >/dev/null 2>&1; then
  grep -rlE "$ORDER_RE" --include='*.py' --include='*.js' --include='*.sh' "$APP.new" | sed "s|$APP.new/||" | head -n 5
  rm -rf "$APP.new"
  echo "주문·키 코드가 복사본에 있습니다 (위 파일): 설치를 멈춥니다. 개발자에게 알려 주세요."; exit 1
fi
printf '{"commit": "%s", "source": "install_huntbot.sh", "installed_at": "%s"}\n' "$COMMIT" "$(date -u +%FT%TZ)" \
  > "$APP.new/VERSION.json"
chown -R root:huntbot "$APP.new"
chmod -R u+rwX,g+rX,g-w,o-rwx "$APP.new"
"$VENV/bin/python" -m compileall -q "$APP.new/huntbot" "$APP.new/research/hunt" >/dev/null

echo "== selfcheck of the new code (as user huntbot, before the swap; a minute or two)"
set +e
SC_OUT="$(cd "$APP.new" && runuser -u huntbot -- env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$LIB" \
  PYTHONPATH="$APP.new" PYTHONDONTWRITEBYTECODE=1 NUMBA_CACHE_DIR="$LIB/numba" HUNTBOT_DATA="$LIB" \
  "$VENV/bin/python" -c '
import sys, time
t = time.time()
from huntbot import runner as R, systems as S, config as C
bad = R.engine_api_problems()
if bad:
    sys.exit("hunt.py lacks: " + ", ".join(bad))
from research.hunt import hunt as H
H._compile_probe()                                  # numba compiled once into the cache
R.EW.fullgrid_pins()                                # the full grid pinned files match
systems, aliases = S.system_list()
cells = S.cells_of(systems)
print(len(systems), "systems,", len(cells), "cells,", len(aliases), "v1 aliases")
H.signal_path_files("wide")                         # every entry cell once on synthetic bars: every module loads
u = C.load_universe()
print("universe:", len(u["symbols"]), "coins from", u["source"])
print("selfcheck ok in %.0fs" % (time.time() - t))
' 2>&1)"
SC_RC=$?
set -e
printf '%s\n' "$SC_OUT" | tail -n 12
if [ "$SC_RC" -ne 0 ]; then
  rm -rf "$APP.new"
  echo "selfcheck failed (exit $SC_RC): nothing was changed. 이 화면을 개발자에게 보내 주세요."; exit 1
fi

echo "== systemd units"
for u in $UNITS; do install -m 644 "$HERE/$u" "/etc/systemd/system/$u"; done
systemctl daemon-reload
RUNNING=""
for u in $UNITS; do
  if systemctl is-active --quiet "$u" 2>/dev/null; then RUNNING="$RUNNING $u"; fi
done
# shellcheck disable=SC2086
if [ -n "$RUNNING" ]; then systemctl stop $RUNNING; fi
rm -rf "$APP.old"
[ -d "$APP" ] && mv "$APP" "$APP.old"
mv "$APP.new" "$APP"
echo "code swapped: $APP (commit ${COMMIT:0:12})"

systemctl enable --quiet huntbot-feed.service huntbot-run.service
systemctl restart huntbot-feed.service || echo "자료 수집을 켜지 못했습니다: journalctl -u huntbot-feed -n 40 --no-pager"
systemctl restart huntbot-run.service || echo "엔진을 켜지 못했습니다: journalctl -u huntbot-run -n 40 --no-pager"
echo "자료 수집: 켜짐 (처음에는 2025-01-01부터의 5분봉을 받느라 30~40분 걸립니다: journalctl -u huntbot-feed -f)"
echo "엔진: 켜짐 (자료가 다 모이면 10/01부터 계산을 시작합니다: journalctl -u huntbot-run -f)"

echo "== firewall (dashboard on Tailscale only)"
bash "$HERE/firewall.sh" || echo "firewall check failed (nothing else is affected): bash $HERE/firewall.sh"
if dash_ready; then
  systemctl enable --quiet huntbot-dash.service
  systemctl restart huntbot-dash.service || echo "대시보드를 켜지 못했습니다: journalctl -u huntbot-dash -n 40 --no-pager"
  echo "대시보드: http://$(envval HUNTBOT_DASH_HOST):$(envval HUNTBOT_DASH_PORT | sed 's/^$/8092/')"
else
  echo "대시보드: 아직 비밀번호·주소가 없어 켜지 않았습니다. 다음 명령 하나로 채웁니다 (텔레그램도 함께):"
  echo "  bash $HERE/setup_env.sh"
fi
echo "끝."
