#!/usr/bin/env bash
# Demo lab bot ("데모 랩") install on the rule bot's server (docs/demobot/INSTALL_KO.md).
#
#   sudo bash deploy/demobot/install_demobot.sh        # from the cloned repository (/root/demobot-src)
#   sudo bash deploy/demobot/update.sh                 # after `git pull`: the same, but on/off stays as it was
#
# Does (safe to run again): system user demobot, /var/lib/demobot (+ snap/), /etc/demobot, the env file from the
# template ONLY when it is missing (never printed), the venv /opt/demobot/venv, a copy of only the code paths the bot
# needs into /opt/demobot/app (staged in app.new, checked, then swapped; the previous copy stays in app.old), the two
# systemd units (the engine, the dashboard, the hourly ranking and its timer). Starts the engine and the ranking
# timer only when the database exists (otherwise it prints the first-fill command) and the dashboard only when its
# password and secret are set. If ufw is on and the dashboard listens on
# the Tailscale address, port 8090 is allowed on tailscale0 only (nothing, when tailscale0 is already allowed;
# firewall.sh, run again by on.sh once the address is set).
# Never touches the rule bot: none of its units, /etc/paperbot, /var/lib/paperbot, /opt/crypto-bot-research.
set -euo pipefail

MODE=install
case "${1:-}" in
  "") ;;
  --update) MODE=update ;;
  *) echo "usage: sudo bash $0 [--update]"; exit 2 ;;
esac

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$REPO_DIR/deploy/demobot"
APP=/opt/demobot/app
VENV=/opt/demobot/venv
LIB=/var/lib/demobot
SNAP=$LIB/snap
ETC=/etc/demobot
ENVF=$ETC/demobot.env
# optional private strategy plug-ins (CONTRACT.md 7.2): the folder is made here, the files in it are the owners'
# (written by a paste box from the developer); this script never reads, changes or removes them
PLUGINS=$ETC/plugins
# unit files installed; the units stopped for the code swap and started again (the ranking timer included, so no
# ranking pass starts on a half-swapped tree); a ranking pass already running is ended, not restarted (next hour)
UNIT_FILES="demobot-live.service demobot-dash.service demobot-rank.service demobot-rank.timer"
SWAP_UNITS="demobot-live.service demobot-dash.service demobot-rank.timer"
# the only paths copied from the repository (the rule bot's dashboard files are left out)
CODE_PATHS="demobot paperbot third_party/sweep research/entry_study/param_defs research/entry_study/DEFS_BC.sha256 \
research/st_custom/out/picks.csv research/st_custom/PREREG.md research/st_custom/PREREG.sha256"
PIP_PKGS="numpy pandas scipy fastapi uvicorn"

if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
if [ ! -d "$REPO_DIR/demobot" ] || [ ! -f "$HERE/demobot-live.service" ]; then
  echo "복제한 저장소 안에서 실행하세요 (예: sudo bash /root/demobot-src/deploy/demobot/install_demobot.sh)"; exit 1
fi
case "$REPO_DIR" in /opt/demobot*) echo "run it from the cloned repository, not from /opt/demobot"; exit 1 ;; esac

# The value of KEY in the env file (last assignment, surrounding quotes removed). Only read into variables here;
# the script never prints a token, a hash or a secret.
envval() {
  local v
  v="$(grep -E "^$1=" "$ENVF" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}
has() { [ -n "$(envval "$1")" ]; }
dash_ready() {
  local h s
  h="$(envval DEMOBOT_DASH_PASSWORD_HASH)"; s="$(envval DEMOBOT_DASH_SECRET)"
  [[ "$h" == pbkdf2\$* ]] && [ "${#s}" -ge 32 ] && has DEMOBOT_DASH_HOST && has DEMOBOT_DASH_PORT
}
is_tailscale_ip() { [[ "$1" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; }

if systemctl is-active --quiet demobot-warm.service 2>/dev/null; then
  echo "첫 채우기(demobot-warm)가 도는 중입니다. 끝난 뒤 다시 실행하세요: journalctl -u demobot-warm -f"; exit 1
fi

echo "== 확인 (python)"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "python3 3.10 이상이 필요합니다 (지금: $(python3 --version 2>&1 || echo 없음))"; exit 1
fi
if ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
  echo "python3-venv가 없습니다. 먼저: sudo apt-get install -y python3-venv"; exit 1
fi
FREE_MB="$(df -Pk /opt 2>/dev/null | awk 'NR == 2 { printf "%.0f", $4 / 1024 }')"
if [ "${FREE_MB:-0}" -lt 1024 ]; then
  echo "디스크 남은 공간이 ${FREE_MB:-?} MB입니다 (1 GB 이상 필요). 먼저 capacity_check.sh를 보세요."; exit 1
fi

echo "== code version"
COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
# shellcheck disable=SC2086  # CODE_PATHS is a list of paths
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no -- $CODE_PATHS deploy/demobot 2>/dev/null)" ]; then
  if [ "${ALLOW_DIRTY:-0}" != "1" ]; then
    echo "the repository has uncommitted changes in the demo lab's paths; deploy only committed code (or ALLOW_DIRTY=1)"
    exit 1
  fi
  DIRTY=true
else
  DIRTY=false
fi
echo "commit $COMMIT dirty=$DIRTY"

echo "== user and folders"
if ! id demobot >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$LIB" --no-create-home --shell /usr/sbin/nologin demobot
fi
if [ "$(id -u demobot)" = 0 ] || id -nG demobot | tr ' ' '\n' | grep -qx paperbot; then
  echo "user demobot must be its own user (not root, not in group paperbot); fix it, then run this again"; exit 1
fi
install -d -o root -g root -m 755 /opt/demobot
install -d -o demobot -g demobot -m 700 "$LIB"
install -d -o demobot -g demobot -m 750 "$SNAP"
install -d -o root -g demobot -m 750 "$ETC"
# only the folder itself (owner, mode); never the files inside. The engine and the ranking (user demobot) read it;
# the dashboard's unit hides all of /etc/demobot.
install -d -o root -g demobot -m 750 "$PLUGINS"

echo "== env file (template only when missing; values are never printed)"
if [ ! -f "$ENVF" ]; then
  install -o root -g demobot -m 640 "$HERE/demobot.env.example" "$ENVF"
  echo "made $ENVF from the template (empty values)"
else
  echo "$ENVF exists: kept as it is"
fi
chown root:demobot "$ENVF"
chmod 640 "$ENVF"
DB_PATH="$(envval DEMOBOT_DB)"; DB_PATH="${DB_PATH:-$LIB/demo.db}"
# decided now, before any new code runs (a check below must not make a fresh database count as filled)
if [ -f "$DB_PATH" ]; then DB_EXISTED=1; else DB_EXISTED=0; fi

echo "== python venv ($VENV)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
SPECS=()
for p in $PIP_PKGS; do
  # the repository's version range for the package (requirements.txt), else the bare name
  spec="$(grep -E "^${p}([<>=!~ ;]|$)" "$REPO_DIR/requirements.txt" 2>/dev/null | head -n 1 | tr -d ' ' || true)"
  SPECS+=("${spec:-$p}")
done
"$VENV/bin/pip" install -q --disable-pip-version-check "${SPECS[@]}"
# `python -m demobot ...` works from any folder (the services also run with WorkingDirectory=$APP)
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "$APP" > "$SITE/demobot-app.pth"

echo "== code (staged in $APP.new)"
for p in $CODE_PATHS; do
  [ -e "$REPO_DIR/$p" ] || { echo "missing in the repository: $p"; exit 1; }
done
rm -rf "$APP.new"
install -d -m 750 "$APP.new"
# shellcheck disable=SC2086
tar -C "$REPO_DIR" --exclude='__pycache__' --exclude='*.pyc' --exclude='paperbot/dash/static' \
  -cf - $CODE_PATHS | tar -C "$APP.new" -xf -
printf '{"commit": "%s", "dirty": %s, "source": "install_demobot.sh", "installed_at": "%s"}\n' \
  "$COMMIT" "$DIRTY" "$(date -u +%FT%TZ)" > "$APP.new/VERSION.json"
# compiled once here: the services cannot write into the code folder
"$VENV/bin/python" -m compileall -q "$APP.new" >/dev/null 2>&1 || true
chown -R root:demobot "$APP.new"
chmod -R u+rwX,g+rX,g-w,o-rwx "$APP.new"

echo "== selfcheck of the new code (before the swap; as user demobot)"
set +e
SC_OUT="$(cd "$APP.new" && runuser -u demobot -- env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$LIB" \
  PYTHONDONTWRITEBYTECODE=1 DEMOBOT_DB="$DB_PATH" DEMOBOT_SNAP="$SNAP" "$VENV/bin/python" -m demobot selfcheck 2>&1)"
SC_RC=$?
set -e
if [ "$SC_RC" -eq 0 ]; then
  echo "selfcheck ok"
elif printf '%s' "$SC_OUT" | grep -Eqi "unknown command|invalid choice|No module named demobot.__main__|cannot be directly executed"; then
  echo "selfcheck: this version has no selfcheck command yet (skipped)"
else
  printf '%s\n' "$SC_OUT" | tail -n 30
  rm -rf "$APP.new"
  echo "selfcheck failed (exit $SC_RC): nothing was changed. Send this screen to the developer."
  exit 1
fi

echo "== systemd units"
for u in $UNIT_FILES; do
  install -m 644 "$HERE/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload

# Armed just before the demo lab's units are stopped for the swap and cleared once they run again: a failure in
# between (an error, Ctrl+C, a dropped SSH session) puts the previous code back and starts them again.
RUNNING=""
restore() {
  rc=$?
  trap '' HUP INT TERM
  trap - EXIT
  [ "$rc" -eq 0 ] && return 0
  set +e
  if [ ! -d "$APP" ] && [ -d "$APP.old" ]; then
    mv "$APP.old" "$APP" && echo "put the previous code back in $APP"
  fi
  if [ -n "$RUNNING" ]; then
    # shellcheck disable=SC2086
    if systemctl start $RUNNING; then echo "started again:$RUNNING"; else echo "could not start:$RUNNING"; fi
  fi
  echo "설치가 중간에 멈췄습니다 (exit $rc). 이 화면을 개발자에게 보내 주세요."
}
for u in $SWAP_UNITS; do
  if systemctl is-active --quiet "$u" 2>/dev/null; then RUNNING="$RUNNING $u"; fi
done
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# shellcheck disable=SC2086
if [ -n "$RUNNING" ]; then systemctl stop $RUNNING; fi
# a oneshot pass reads "activating" while it runs (is-active alone would miss it)
case "$(systemctl show -p ActiveState --value demobot-rank.service 2>/dev/null)" in
  active|activating|deactivating|reloading) systemctl stop demobot-rank.service ;;
esac
rm -rf "$APP.old"
PREV=""
if [ -d "$APP" ]; then mv "$APP" "$APP.old"; PREV=1; fi
mv "$APP.new" "$APP"
# shellcheck disable=SC2086
if [ -n "$RUNNING" ]; then systemctl start $RUNNING; fi
trap - EXIT HUP INT TERM
echo "code swapped: $APP${PREV:+ (previous: $APP.old)}"

if [ "$MODE" = install ]; then
  # Each unit is enabled (started at boot) and started only once it can run: the engine after the first fill (a
  # reboot before it must not start the engine on an empty database), the dashboard once its password is set.
  # on.sh enables and starts them later.
  if [ "$DB_EXISTED" = 1 ]; then
    systemctl enable --quiet demobot-live.service demobot-rank.timer
    if ! systemctl is-active --quiet demobot-live.service; then
      systemctl start demobot-live.service || echo "엔진을 켜지 못했습니다: journalctl -u demobot-live -n 40 --no-pager"
    fi
    if ! systemctl is-active --quiet demobot-rank.timer; then
      systemctl start demobot-rank.timer || echo "순위표 타이머를 켜지 못했습니다: systemctl status demobot-rank.timer --no-pager"
    fi
  fi
  if dash_ready; then
    systemctl enable --quiet demobot-dash.service
    if ! systemctl is-active --quiet demobot-dash.service; then
      systemctl start demobot-dash.service || echo "대시보드를 켜지 못했습니다: journalctl -u demobot-dash -n 40 --no-pager"
    fi
  fi
fi

echo "== firewall"
HOST="$(envval DEMOBOT_DASH_HOST)"
PORT="$(envval DEMOBOT_DASH_PORT)"; PORT="${PORT:-8090}"
bash "$HERE/firewall.sh" || echo "firewall check failed (nothing else is affected): sudo bash $HERE/firewall.sh"

echo
echo "== 요약"
sleep 2
state() { if systemctl is-active --quiet "$1"; then echo "켜짐"; else echo "꺼짐"; fi; }
yn() { if has "$1"; then echo "있음"; else echo "비어 있음"; fi; }
echo "코드: $APP (commit ${COMMIT:0:12}${PREV:+; 이전 코드 $APP.old})"
echo "엔진 demobot-live: $(state demobot-live.service)"
echo "대시보드 demobot-dash: $(state demobot-dash.service)"
echo "순위표 demobot-rank.timer (매시 7분): $(state demobot-rank.timer)"
echo "텔레그램: 토큰 $(yn DEMOBOT_TG_TOKEN) · 방 번호 $(yn DEMOBOT_TG_CHAT)"
if dash_ready; then DASH_SET="있음"; else DASH_SET="비어 있음"; fi
if is_tailscale_ip "$HOST"; then WHERE="Tailscale을 켠 기기에서"; else WHERE="아직 Tailscale 주소가 아님: 3단계"; fi
echo "대시보드 비밀번호·비밀값: $DASH_SET · 주소 http://${HOST:-<DEMOBOT_DASH_HOST>}:$PORT ($WHERE)"
if [ -f "$DB_PATH" ]; then echo "데이터베이스: 있음 ($DB_PATH)"; else echo "데이터베이스: 아직 없음 (첫 채우기 전)"; fi
echo "규칙봇의 서비스·설정·데이터는 건드리지 않았습니다."
echo
echo "다음 할 일 (docs/demobot/INSTALL_KO.md):"
NEXT=0
if ! has DEMOBOT_TG_TOKEN || ! has DEMOBOT_TG_CHAT; then
  echo "  - 2단계 텔레그램: 토큰과 방 번호 넣기 (SUDO_EDITOR=nano sudoedit $ENVF)"; NEXT=1
fi
if ! dash_ready || ! is_tailscale_ip "$HOST"; then
  echo "  - 3단계 대시보드: 비밀번호·비밀값·Tailscale 주소 넣기"; NEXT=1
fi
if [ ! -f "$DB_PATH" ]; then
  echo "  - 4단계 첫 채우기 (10~15분): sudo bash $HERE/warm.sh"
  echo "    끝나면 켜기: sudo bash $HERE/on.sh"; NEXT=1
elif [ "$MODE" = install ] && { ! systemctl is-active --quiet demobot-live.service || \
     ! systemctl is-active --quiet demobot-rank.timer || \
     { dash_ready && ! systemctl is-active --quiet demobot-dash.service; }; }; then
  echo "  - 켜기: sudo bash $HERE/on.sh (설정 파일을 바꾼 뒤에도 이것으로 다시 읽힘)"; NEXT=1
fi
if [ "$NEXT" = 0 ]; then
  echo "  - 없음. 대시보드: http://$HOST:$PORT"
fi
