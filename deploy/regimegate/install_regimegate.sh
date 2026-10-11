#!/usr/bin/env bash
# 장세 문지기 밤 계산 (paperbot/regimegate.py, docs/regime-gate-ko.md) on the rule bot's server.
#
#   sudo bash deploy/regimegate/install_regimegate.sh          # from a clone of this repository (e.g. /root/regimegate-src)
#
# Safe to run again (an update = git pull, then the same command). Needs the rule bot's own install first (user
# paperbot, the venv /opt/paperbot/venv, /var/lib/paperbot) and the pinned rules (research/regimegate/
# PREREG_REGIMEGATE.sha256 committed). Copies only the code paths the job needs into /opt/paperbot-regimegate/app
# (staged in app.new, compiled, checked as user paperbot with `python -m paperbot.regimegate selfcheck`, then swapped;
# the previous copy stays in app.old), makes /var/lib/paperbot/regimegate, installs the unit and the nightly timer
# (01:40 UTC = 10:40 KST, after the custom-value shadow) and starts the first run in the background.
# Never touches the rule bot: none of its units, not its code tree (/opt/crypto-bot-research) and it never edits
# deploy/install.sh. No restart, nothing in a runinfo hash set: the 30-day window is not affected.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$REPO_DIR/deploy/regimegate"
BASE=/opt/paperbot-regimegate
APP=$BASE/app
VENV=/opt/paperbot/venv
OUT=/var/lib/paperbot/regimegate
SVC=paperbot-regimegate.service
UNITS="paperbot-regimegate.service paperbot-regimegate.timer"
# the only paths copied from the repository: the job, the replay and engine code (paperbot), the locked signal library
# and definitions, the pinned gate files and the label code they name, and what gate.py imports read-only
CODE_PATHS="paperbot third_party/sweep research/entry_study/param_defs research/entry_study/strength_defs \
research/entry_study/sr.py research/entry_study/DEFS_BC.sha256 research/deepseek200/lib_c.py research/library \
research/regimegate/PREREG_REGIMEGATE.md research/regimegate/PREREG_REGIMEGATE.sha256 research/regimegate/gate.py \
research/regimegate/style_map.json research/fullgrid/run.py research/fullgrid/data.py research/fullgrid/grid.py \
research/fullgrid/kernel.py research/fullgrid/memo.py research/fullgrid/ds_defs.py research/fullgrid/regimes.py \
research/fullgrid/exchange.json demobot/__init__.py demobot/regime.py demobot/accounts.py demobot/exits.py \
demobot/grid.py demobot/store.py"

if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
if [ ! -f "$REPO_DIR/paperbot/regimegate.py" ] || [ ! -f "$HERE/$SVC" ]; then
  echo "복제한 저장소 안에서 실행하세요 (예: sudo bash /root/regimegate-src/deploy/regimegate/install_regimegate.sh)"; exit 1
fi
case "$REPO_DIR" in /opt/paperbot-regimegate*|/opt/crypto-bot-research*)
  echo "run it from a separate clone of the repository, not from $REPO_DIR"; exit 1 ;; esac

echo "== 확인 (규칙봇 설치, 규칙 고정 파일)"
if ! id paperbot >/dev/null 2>&1 || [ ! -x "$VENV/bin/python" ] || [ ! -d /var/lib/paperbot ]; then
  echo "규칙봇 설치(사용자 paperbot, $VENV, /var/lib/paperbot)가 먼저 있어야 합니다."; exit 1
fi
if [ ! -f "$REPO_DIR/research/regimegate/PREREG_REGIMEGATE.sha256" ]; then
  echo "규칙 고정 파일(research/regimegate/PREREG_REGIMEGATE.sha256)이 아직 없습니다."
  echo "개발자가 규칙을 고정해 올린 뒤 git pull 하고 다시 실행하세요. 아무것도 바꾸지 않았습니다."; exit 1
fi
# a pin made by hand on the server (untracked) is not the committed one: the status check below skips untracked files
if git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
   && ! git -C "$REPO_DIR" ls-files --error-unmatch research/regimegate/PREREG_REGIMEGATE.sha256 >/dev/null 2>&1; then
  echo "규칙 고정 파일(research/regimegate/PREREG_REGIMEGATE.sha256)이 커밋된 파일이 아닙니다."
  echo "개발자가 규칙을 고정해 올린 뒤 git pull 하고 다시 실행하세요. 아무것도 바꾸지 않았습니다."; exit 1
fi
for p in $CODE_PATHS; do
  [ -e "$REPO_DIR/$p" ] || { echo "저장소에 없습니다: $p (git pull 후 다시 실행하세요)"; exit 1; }
done
# shellcheck disable=SC2086
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no -- $CODE_PATHS deploy/regimegate 2>/dev/null)" ]; then
  echo "the repository has uncommitted changes in the job's paths; deploy only committed code"; exit 1
fi
COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
echo "commit $COMMIT"

echo "== folders"
install -d -o root -g root -m 755 "$BASE"
install -d -o paperbot -g paperbot -m 750 "$OUT"

echo "== code (staged in $APP.new)"
rm -rf "$APP.new"
install -d -m 750 "$APP.new"
# shellcheck disable=SC2086
tar -C "$REPO_DIR" --exclude='__pycache__' --exclude='*.pyc' --exclude='paperbot/dash/static' \
  --exclude='paperbot/obsidian_vault' -cf - $CODE_PATHS | tar -C "$APP.new" -xf -
printf '{"commit": "%s", "source": "install_regimegate.sh", "installed_at": "%s"}\n' "$COMMIT" \
  "$(date -u +%FT%TZ)" > "$APP.new/VERSION.json"
"$VENV/bin/python" -m compileall -q "$APP.new" >/dev/null 2>&1 || true
if ! CL_OUT="$("$VENV/bin/python" -m compileall -q -f "$APP.new/paperbot/regimegate.py" "$APP.new/research/regimegate/gate.py" 2>&1)"; then
  printf '%s\n' "$CL_OUT" | tail -n 20
  rm -rf "$APP.new"
  echo "selfcheck failed (the job does not compile): nothing was changed. 이 화면을 개발자에게 보내 주세요."; exit 1
fi
chown -R root:paperbot "$APP.new"
chmod -R u+rwX,g+rX,g-w,o-rwx "$APP.new"

echo "== selfcheck of the new code (before the swap; as user paperbot)"
set +e
SC_OUT="$(cd "$APP.new" && runuser -u paperbot -- env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$OUT" \
  PYTHONPATH="$APP.new" PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  "$VENV/bin/python" -m paperbot.regimegate selfcheck 2>&1)"
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

# a night already running reads the old copy: wait for it (at most 60 min) before the swap
n=0
while case "$(systemctl show -p ActiveState --value "$SVC" 2>/dev/null)" in
        active|activating|deactivating|reloading) true ;; *) false ;; esac; do
  n=$((n+1)); [ "$n" -ge 120 ] && { echo "the regime-gate job is still running after 60 min; run this script again later"; exit 1; }
  echo "waiting for the running regime-gate job to finish ($n/120)"; sleep 30
done
rm -rf "$APP.old"
[ -d "$APP" ] && mv "$APP" "$APP.old"
mv "$APP.new" "$APP"
echo "code swapped: $APP"

systemctl enable --quiet --now paperbot-regimegate.timer \
  || echo "타이머를 켜지 못했습니다: sudo systemctl enable --now paperbot-regimegate.timer"
systemctl start --no-block "$SVC" || echo "첫 계산을 시작하지 못했습니다: sudo systemctl start $SVC"
echo "타이머: 매일 10:40 (한국 시간). 첫 계산은 지금 뒤에서 시작했습니다 (처음에는 15~30분: 5분봉 약 430일치를 받습니다)."
echo "진행: sudo journalctl -u paperbot-regimegate -f"
echo "결과 한 줄: cat $OUT/last.txt"
echo "자세히: cd $APP && sudo -u paperbot $VENV/bin/python -m paperbot.regimegate show"
echo "끝."
