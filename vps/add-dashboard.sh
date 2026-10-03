#!/usr/bin/env bash
# 이미 install-ghcoin.sh 로 설치한 서버에 GH Coin 웹 대시보드(:8080)를 추가/업데이트한다 (root 로 실행)
#
#   사용:  sudo bash add-dashboard.sh
#
# 하는 일
#   1. 앱 창(Chrome)에 '이 서버 안에서만' 열리는 읽기 통로(DevTools 9222, 127.0.0.1)를 켠다
#   2. ghcoin-dash 서비스: 그 통로로 봇 상태를 몇 초마다 읽어서 웹 대시보드로 보여 준다 (보기 전용, 키는 절대 안 내보냄)
#   3. 대시보드는 Tailscale 로만 열림 (방화벽은 설치 때 이미 SSH · Tailscale 만 허용)
# 앱(친구 코드)은 전혀 바꾸지 않는다. 다시 실행해도 안전함.
set -euo pipefail

BRANCH="${GHCOIN_BRANCH:-claude/vigilant-shannon-irq1vg}"
RAW="https://raw.githubusercontent.com/g1792091-boop/crypto-bot-research/$BRANCH/vps/dashboard"
APP_USER="ghcoin"
DASH_DIR="/opt/ghcoin/dashboard"
DASH_PORT=8080
CDP_PORT=9222

say(){ printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "root 로 실행하세요:  sudo bash $0"
[ -f /etc/systemd/system/ghcoin-chrome.service ] || die "먼저 install-ghcoin.sh 로 GH Coin 을 설치하세요"
export DEBIAN_FRONTEND=noninteractive

say "필요한 패키지"
apt-get install -y -qq -o DPkg::Lock::Timeout=900 --no-install-recommends python3 python3-websocket curl >/dev/null

say "대시보드 파일 받기"
install -d -m 755 "$DASH_DIR"
for f in ghcoin_dash.py collector.js index.html; do
  curl -fsSL -o "$DASH_DIR/$f.new" "$RAW/$f"
  mv -f "$DASH_DIR/$f.new" "$DASH_DIR/$f"
done
chmod 644 "$DASH_DIR"/*

say "앱 창에 읽기 통로 켜기 (127.0.0.1:$CDP_PORT, 서버 안에서만)"
UNIT=/etc/systemd/system/ghcoin-chrome.service
if ! grep -q -- "--remote-debugging-port=" "$UNIT"; then
  sed -i "s#^ExecStart=/usr/bin/google-chrome #ExecStart=/usr/bin/google-chrome --remote-debugging-port=$CDP_PORT #" "$UNIT"
fi
grep -q -- "--remote-debugging-port=$CDP_PORT" "$UNIT" || die "앱 창 설정을 바꾸지 못했습니다: $UNIT"

cat > /etc/systemd/system/ghcoin-dash.service <<EOF
[Unit]
Description=GH Coin 웹 대시보드 (:$DASH_PORT, Tailscale 로만 접속 · 보기 전용)
After=ghcoin-chrome.service
Wants=ghcoin-chrome.service

[Service]
User=$APP_USER
Environment=GHCOIN_DASH_PORT=$DASH_PORT GHCOIN_DASH_BIND=0.0.0.0 GHCOIN_CDP=http://127.0.0.1:$CDP_PORT
ExecStart=/usr/bin/python3 $DASH_DIR/ghcoin_dash.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl restart ghcoin-chrome
systemctl enable -q ghcoin-dash
systemctl restart ghcoin-dash

# ghcoin-status 에 대시보드도 표시
if [ -f /usr/local/bin/ghcoin-status ] && ! grep -q ghcoin-dash /usr/local/bin/ghcoin-status; then
  sed -i 's/for s in ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-novnc; do/for s in ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-novnc ghcoin-dash; do/' /usr/local/bin/ghcoin-status
  sed -i 's#^echo "== 웹 원격화면 주소"#echo "== 주소 (대시보드 :8080 · 원격화면 :6080)"#' /usr/local/bin/ghcoin-status
fi

say "확인 중 (최대 60초)"
ok=""
for i in $(seq 1 30); do
  if curl -fsS -m 3 "http://127.0.0.1:$DASH_PORT/healthz" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ -n "$ok" ] || { journalctl -u ghcoin-dash -n 30 --no-pager || true; die "대시보드가 아직 안 켜졌습니다. 위 기록을 캡처해서 보내 주세요."; }

TSIP=$(tailscale ip -4 2>/dev/null | head -1 || true)
say "완료!"
cat <<EOF

  ┌───────────────────────────────────────────────────────────────┐
    GH Coin 대시보드:  Tailscale 켜고 →  http://${TSIP:-<tailscale IP>}:$DASH_PORT/
    (설정·키 입력이 필요할 때만 원격화면 →  http://${TSIP:-<tailscale IP>}:6080/)
  └───────────────────────────────────────────────────────────────┘
EOF
