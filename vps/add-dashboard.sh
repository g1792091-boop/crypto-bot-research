#!/usr/bin/env bash
# 이미 install-ghcoin.sh 로 설치한 서버에 GH Coin 웹 대시보드(:8080)를 추가/업데이트한다 (root 로 실행)
#
#   사용:  sudo bash add-dashboard.sh
#
# 하는 일
#   1. 앱 창(Chrome)에 '이 서버 안에서만' 열리는 읽기 통로(DevTools 9222, 127.0.0.1)를 켠다
#      + 방화벽 규칙으로 그 통로는 ghcoin 계정(Chrome · 대시보드)만 쓸 수 있게 막는다
#   2. ghcoin-dash 서비스: 그 통로로 봇 상태를 몇 초마다 읽어서 웹 대시보드로 보여 준다 (보기 전용, 키는 절대 안 내보냄)
#   3. 대시보드는 Tailscale 로만 열림 (방화벽은 설치 때 이미 SSH · Tailscale 만 허용 + 대시보드도 Tailscale 주소만 받음)
# 앱(친구 코드)은 전혀 바꾸지 않는다. 다시 실행해도 안전함 (앱 창은 읽기 통로를 처음 켤 때만 다시 띄움).
set -euo pipefail

BRANCH="${GHCOIN_BRANCH:-claude/vigilant-shannon-irq1vg}"
REV="${GHCOIN_REV:-$BRANCH}"     # 커밋 해시를 넣으면 그 커밋에서 받는다
RAW="https://raw.githubusercontent.com/g1792091-boop/crypto-bot-research/$REV/vps/dashboard"
APP_USER="ghcoin"
DASH_DIR="/opt/ghcoin/dashboard"
DASH_PORT=8080
CDP_PORT=9222
FILES="ghcoin_dash.py collector.js index.html"
# 받은 파일이 아래 값과 하나라도 다르면 설치하지 않는다 (이 파일들은 Chrome 읽기 통로 = 키·주문에 닿는 코드).
# vps/dashboard 파일을 고치면 같이 바꿀 것:  sha256sum vps/dashboard/ghcoin_dash.py vps/dashboard/collector.js vps/dashboard/index.html
declare -A SHA=(
  [ghcoin_dash.py]=__SHA_ghcoin_dash_py__
  [collector.js]=__SHA_collector_js__
  [index.html]=__SHA_index_html__
)

say(){ printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "root 로 실행하세요:  sudo bash $0"
[ -f /etc/systemd/system/ghcoin-chrome.service ] || die "먼저 install-ghcoin.sh 로 GH Coin 을 설치하세요"
id "$APP_USER" >/dev/null 2>&1 || die "$APP_USER 계정이 없습니다 — 먼저 install-ghcoin.sh 로 설치하세요"
export DEBIAN_FRONTEND=noninteractive

say "필요한 패키지"
apt-get install -y -qq -o DPkg::Lock::Timeout=900 --no-install-recommends python3 python3-websocket curl iptables >/dev/null

say "대시보드 파일 받기 (내용 확인)"
install -d -m 755 "$DASH_DIR"
for f in $FILES; do
  curl -fsSL -o "$DASH_DIR/$f.new" "$RAW/$f"
  if ! echo "${SHA[$f]}  $DASH_DIR/$f.new" | sha256sum -c --status -; then
    rm -f "$DASH_DIR"/*.new
    die "$f 내용이 확인한 파일과 다릅니다 (새 버전이면 add-dashboard.sh 도 새로 받아서 다시 실행하세요)"
  fi
done
for f in $FILES; do mv -f "$DASH_DIR/$f.new" "$DASH_DIR/$f"; done   # 셋 다 확인된 뒤에만 바꿈
chmod 644 "$DASH_DIR"/*

say "읽기 통로 보호: 127.0.0.1:$CDP_PORT 은 $APP_USER 계정만 접속 가능"
# 이 서버의 다른 계정(실행기 ghcoin-srv 등)이 9222 로 봇 페이지에 붙어 키를 읽거나 주문하지 못하게 한다.
# 규칙은 OUTPUT 맨 앞에 넣는다 (ufw 의 'loopback 전부 허용' 보다 먼저 걸려야 함). 재부팅하면 이 서비스가 다시 넣음.
cat > /etc/systemd/system/ghcoin-cdp-guard.service <<EOF
[Unit]
Description=GH Coin 읽기 통로 보호 (127.0.0.1:$CDP_PORT 은 $APP_USER 계정만)
After=ufw.service
Before=ghcoin-chrome.service ghcoin-dash.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'iptables -C OUTPUT -o lo -p tcp --dport $CDP_PORT -m owner ! --uid-owner $APP_USER -j REJECT --reject-with tcp-reset 2>/dev/null || iptables -I OUTPUT 1 -o lo -p tcp --dport $CDP_PORT -m owner ! --uid-owner $APP_USER -j REJECT --reject-with tcp-reset'
ExecStart=-/bin/sh -c 'ip6tables -C OUTPUT -o lo -p tcp --dport $CDP_PORT -m owner ! --uid-owner $APP_USER -j REJECT --reject-with tcp-reset 2>/dev/null || ip6tables -I OUTPUT 1 -o lo -p tcp --dport $CDP_PORT -m owner ! --uid-owner $APP_USER -j REJECT --reject-with tcp-reset'

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q ghcoin-cdp-guard
systemctl restart ghcoin-cdp-guard
iptables -C OUTPUT -o lo -p tcp --dport $CDP_PORT -m owner ! --uid-owner $APP_USER -j REJECT --reject-with tcp-reset \
  || die "읽기 통로 보호 규칙을 넣지 못했습니다:  journalctl -u ghcoin-cdp-guard -n 20"

say "앱 창에 읽기 통로 켜기 (127.0.0.1:$CDP_PORT, 서버 안에서만)"
UNIT=/etc/systemd/system/ghcoin-chrome.service
CHG=""
if ! grep -q -- "--remote-debugging-port=" "$UNIT"; then
  sed -i "s#^ExecStart=/usr/bin/google-chrome #ExecStart=/usr/bin/google-chrome --remote-debugging-port=$CDP_PORT #" "$UNIT"
  CHG=1
fi
grep -q -- "--remote-debugging-port=$CDP_PORT" "$UNIT" || die "앱 창 설정을 바꾸지 못했습니다: $UNIT"

cat > /etc/systemd/system/ghcoin-dash.service <<EOF
[Unit]
Description=GH Coin 웹 대시보드 (:$DASH_PORT, Tailscale 로만 접속 · 보기 전용)
After=ghcoin-chrome.service ghcoin-cdp-guard.service
Wants=ghcoin-chrome.service ghcoin-cdp-guard.service

[Service]
User=$APP_USER
Environment=GHCOIN_DASH_PORT=$DASH_PORT GHCOIN_DASH_BIND=0.0.0.0 GHCOIN_CDP=http://127.0.0.1:$CDP_PORT
ExecStart=/usr/bin/python3 $DASH_DIR/ghcoin_dash.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
# /home 은 통째로 가림 (/home/$APP_USER 에는 키가 든 Chrome 저장소가 있고, 대시보드는 쓸 일이 없음)
ProtectHome=tmpfs
PrivateTmp=true
# 접속이 몰려도 서버 메모리를 다 먹지 못하게 (넘치면 대시보드만 죽고 다시 켜짐 — 봇 Chrome 은 그대로)
MemoryMax=256M
TasksMax=96
LimitNOFILE=1024
OOMScoreAdjust=500

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
if [ -n "$CHG" ]; then
  say "앱 창 다시 띄우기 (읽기 통로를 처음 켤 때 한 번만)"
  systemctl restart ghcoin-chrome
fi
systemctl enable -q ghcoin-dash
systemctl restart ghcoin-dash

# ghcoin-status 에 대시보드도 표시 (예전 install-ghcoin.sh 로 만든 것만 고침)
if [ -f /usr/local/bin/ghcoin-status ] && ! grep -q ghcoin-dash /usr/local/bin/ghcoin-status; then
  sed -i 's/for s in ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-novnc; do/for s in ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-novnc ghcoin-dash; do/' /usr/local/bin/ghcoin-status
  sed -i 's#^echo "== 웹 원격화면 주소"#echo "== 주소 (대시보드 :8080 · 원격화면 :6080)"#' /usr/local/bin/ghcoin-status
fi

say "확인 중 (최대 60초)"
ok=""
for i in $(seq 1 30); do
  if runuser -u "$APP_USER" -- curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$CDP_PORT/json/version" 2>/dev/null; then ok=1; break; fi
  sleep 2
done
if [ -n "$ok" ]; then
  # 다른 계정은 막혀야 정상
  if runuser -u nobody -- curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$CDP_PORT/json/version" 2>/dev/null; then
    die "읽기 통로 보호가 동작하지 않습니다 (다른 계정도 9222 에 접속됨). 화면을 캡처해서 보내 주세요."
  fi
else
  echo "  (앱 창의 읽기 통로가 아직 안 열렸습니다 — Chrome 이 켜지는 중이면 1분 안에 대시보드가 저절로 붙습니다)"
fi
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
    (설정·키 입력·실거래 승인은 원격화면 →  http://${TSIP:-<tailscale IP>}:6080/)
  └───────────────────────────────────────────────────────────────┘
  * Tailscale Funnel / serve 로 :$DASH_PORT 을 밖에 열지 마세요 (대시보드에는 로그인이 없습니다).
EOF
