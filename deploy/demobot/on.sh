#!/usr/bin/env bash
# Demo lab bot on: enable and (re)start the engine, the dashboard and the hourly ranking timer, so they also come
# back after a reboot. Running it again restarts them, so they re-read /etc/demobot/demobot.env (after a change there).
# When no ranking exists yet, one ranking pass is started at once (2-4 minutes, in the background).
#   sudo bash deploy/demobot/on.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENVF=/etc/demobot/demobot.env
if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
# a value of the env file, read into a variable only (never printed)
val() { grep -E "^$1=" "$ENVF" 2>/dev/null | tail -n 1 | cut -d= -f2- | sed -e "s/^['\"]//" -e "s/['\"]\$//" || true; }
DB="$(val DEMOBOT_DB)"; DB="${DB:-/var/lib/demobot/demo.db}"
SNAP="$(val DEMOBOT_SNAP)"; SNAP="${SNAP:-/var/lib/demobot/snap}"
if systemctl is-active --quiet demobot-warm.service; then
  echo "첫 채우기가 아직 도는 중입니다. 끝난 뒤 다시 실행하세요 (보기: journalctl -u demobot-warm -f)"; exit 1
fi
if [ ! -f "$DB" ]; then echo "아직 첫 채우기를 하지 않았습니다: sudo bash $HERE/warm.sh"; exit 1; fi
UNITS="demobot-live.service demobot-rank.timer"
H="$(val DEMOBOT_DASH_PASSWORD_HASH)"; S="$(val DEMOBOT_DASH_SECRET)"
if [[ "$H" == pbkdf2\$* ]] && [ "${#S}" -ge 32 ]; then
  UNITS="$UNITS demobot-dash.service"
else
  echo "대시보드 비밀번호·비밀값이 비어 있어 대시보드는 켜지 않습니다 (docs/demobot/INSTALL_KO.md 3단계)"
fi
if [[ "$UNITS" == *dash* ]]; then
  bash "$HERE/firewall.sh" || echo "firewall check failed: sudo bash $HERE/firewall.sh"
fi
# shellcheck disable=SC2086
systemctl enable --quiet $UNITS && systemctl restart $UNITS
if [ ! -f "$SNAP/rank_meta.json" ]; then
  systemctl start --no-block demobot-rank.service
  echo "순위표가 아직 없어 지금 한 번 만듭니다 (2~4분, 뒤에서 돎). 그다음은 매시 7분."
fi
PLUG="$(val DEMOBOT_PLUGINS)"; PLUG="${PLUG:-/etc/demobot/plugins}"
N_PLUG="$(find "$PLUG" -maxdepth 1 -type f -name '*.py' 2>/dev/null | wc -l)"
if [ "$N_PLUG" -gt 0 ]; then echo "비공개 매매법 파일 ${N_PLUG}개를 읽습니다 ($PLUG)"; fi
sleep 3
for u in demobot-live.service demobot-dash.service demobot-rank.timer; do
  echo "$u: $(systemctl is-active "$u" || true)"
done
