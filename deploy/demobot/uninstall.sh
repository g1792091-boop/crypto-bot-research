#!/usr/bin/env bash
# Demo lab bot removal: stops and removes its units (engine, dashboard, hourly ranking and its timer), its firewall rule (only the one the install added) and
# /opt/demobot (code and venv). Keeps the database (/var/lib/demobot) and the env file (/etc/demobot) unless --purge.
#   sudo bash deploy/demobot/uninstall.sh            # keeps the data
#   sudo bash deploy/demobot/uninstall.sh --purge    # also deletes the data, the env file and user demobot
# The rule bot is not touched.
set -euo pipefail
PURGE=0
YES=0
for a in "$@"; do
  case "$a" in
    --purge) PURGE=1 ;;
    --yes) YES=1 ;;
    *) echo "usage: sudo bash $0 [--purge [--yes]]"; exit 2 ;;
  esac
done
if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
if [ "$PURGE" = 1 ] && [ "$YES" != 1 ]; then
  if [ -t 0 ]; then
    read -r -p "데모 랩의 데이터·설정·사용자까지 모두 지웁니다. 계속하려면 yes 입력: " ans
    [ "$ans" = yes ] || { echo "취소했습니다. 아무것도 지우지 않았습니다."; exit 1; }
  else
    echo "--purge는 확인이 필요합니다: sudo bash $0 --purge --yes"; exit 1
  fi
fi
PORT="$(grep -E '^DEMOBOT_DASH_PORT=' /etc/demobot/demobot.env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "\"' " || true)"
PORT="${PORT:-8090}"

systemctl stop demobot-warm.service 2>/dev/null || true
systemctl disable --now --quiet demobot-live.service demobot-dash.service demobot-rank.timer 2>/dev/null || true
systemctl stop demobot-rank.service 2>/dev/null || true
rm -f /etc/systemd/system/demobot-live.service /etc/systemd/system/demobot-dash.service \
  /etc/systemd/system/demobot-rank.service /etc/systemd/system/demobot-rank.timer
systemctl daemon-reload
systemctl reset-failed demobot-live.service demobot-dash.service demobot-rank.service demobot-rank.timer \
  demobot-warm.service 2>/dev/null || true
echo "서비스 지움: demobot-live, demobot-dash, demobot-rank (+ 타이머)"

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -Eq "^$PORT/tcp on tailscale0[[:space:]]+ALLOW"; then
  ufw delete allow in on tailscale0 to any port "$PORT" proto tcp >/dev/null && echo "방화벽 규칙 지움: $PORT/tcp on tailscale0"
fi

rm -rf /opt/demobot
echo "코드·venv 지움: /opt/demobot"

if [ "$PURGE" = 1 ]; then
  rm -rf /var/lib/demobot /etc/demobot
  if id demobot >/dev/null 2>&1; then userdel demobot || echo "사용자 demobot을 지우지 못했습니다: sudo userdel demobot"; fi
  if getent group demobot >/dev/null 2>&1; then groupdel demobot || echo "그룹 demobot을 지우지 못했습니다: sudo groupdel demobot"; fi
  echo "데이터·설정·사용자 지움: /var/lib/demobot, /etc/demobot, demobot"
else
  echo "남겨 둠: /var/lib/demobot (데이터), /etc/demobot (설정). 모두 지우려면: sudo bash $0 --purge"
fi
echo "규칙봇은 건드리지 않았습니다."
