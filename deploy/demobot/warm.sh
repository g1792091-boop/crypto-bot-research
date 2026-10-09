#!/usr/bin/env bash
# Demo lab bot: the first fill (26 weeks of Binance history into /var/lib/demobot/demo.db, about 10-15 minutes).
#
#   sudo bash deploy/demobot/warm.sh
#
# Runs `python -m demobot warm` as user demobot in a temporary systemd unit (demobot-warm) with the engine's sandbox,
# priority and memory cap and the same env file, so a dropped SSH session does not stop it. Shows its log while it
# runs. Refuses while the engine or the hourly ranking runs. After a successful fill it runs the ranking once
# (demobot-rank.service, 2-4 minutes) so the ranking exists before the dashboard is opened.
# Then: sudo bash deploy/demobot/on.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
if [ ! -x /opt/demobot/venv/bin/python ] || [ ! -d /opt/demobot/app/demobot ]; then
  echo "먼저 설치하세요: sudo bash $HERE/install_demobot.sh"; exit 1
fi
if systemctl is-active --quiet demobot-live.service; then
  echo "엔진이 켜져 있습니다. 첫 채우기는 엔진을 끈 뒤에만 합니다: sudo bash $HERE/off.sh"; exit 1
fi
if systemctl is-active --quiet demobot-rank.timer || \
   [ "$(systemctl show -p ActiveState --value demobot-rank.service 2>/dev/null)" = activating ]; then
  echo "순위표(demobot-rank)가 켜져 있습니다. 첫 채우기는 끈 뒤에만 합니다: sudo bash $HERE/off.sh"; exit 1
fi
if systemctl is-active --quiet demobot-warm.service; then
  echo "이미 채우는 중입니다. 진행 보기: journalctl -u demobot-warm -f (Ctrl+C는 보기만 멈춥니다)"; exit 0
fi
systemctl reset-failed demobot-warm.service >/dev/null 2>&1 || true

echo "첫 채우기 시작 (10~15분). 접속이 끊겨도 서버에서 계속 돕니다."
echo "다시 접속했을 때 진행 보기: journalctl -u demobot-warm -f   (끝났는지: systemctl is-active demobot-warm → inactive)"
echo
journalctl -u demobot-warm.service -u demobot-rank.service -f -n 0 -o cat &
JPID=$!
trap 'kill "$JPID" 2>/dev/null || true' EXIT
set +e
systemd-run --unit=demobot-warm --description="demobot first fill" --collect --wait --quiet \
  --uid=demobot --gid=demobot \
  -p WorkingDirectory=/opt/demobot/app -p EnvironmentFile=/etc/demobot/demobot.env -p UMask=0027 \
  -p Nice=10 -p CPUWeight=20 -p MemoryHigh=900M -p MemoryMax=1200M \
  -p NoNewPrivileges=yes -p PrivateTmp=yes -p PrivateDevices=yes -p ProtectSystem=strict -p ProtectHome=yes \
  -p ReadWritePaths=/var/lib/demobot \
  -p "InaccessiblePaths=-/etc/paperbot -/var/lib/paperbot -/var/backups/paperbot" \
  -E OPENBLAS_NUM_THREADS=1 -E OMP_NUM_THREADS=1 -E MKL_NUM_THREADS=1 \
  -E PYTHONDONTWRITEBYTECODE=1 -E PYTHONUNBUFFERED=1 \
  /opt/demobot/venv/bin/python -m demobot warm
rc=$?
set -e
sleep 1
echo
if [ "$rc" -eq 0 ]; then
  echo "첫 채우기가 끝났습니다. 이어서 순위표를 한 번 만듭니다 (2~4분)."
  if systemctl start demobot-rank.service; then
    sleep 1
    echo
    echo "순위표도 만들었습니다. 이제 켜세요: sudo bash $HERE/on.sh"
  else
    sleep 1
    echo
    echo "순위표를 만들지 못했습니다 (첫 채우기는 끝났습니다). 그래도 켜세요: sudo bash $HERE/on.sh"
    echo "순위표는 켠 뒤 매시 7분에 다시 만들어집니다. 기록: journalctl -u demobot-rank -n 40 --no-pager"
  fi
else
  echo "첫 채우기가 실패했습니다 (exit $rc). 마지막 줄 보기: journalctl -u demobot-warm -n 40 --no-pager"
  echo "그 화면을 개발자에게 보내 주세요. (메모리 1.2 GB 제한에 걸렸으면 'oom'이 보입니다)"
fi
exit "$rc"
