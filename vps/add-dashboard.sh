#!/usr/bin/env bash
# 이미 install-ghcoin.sh 로 설치한 서버에 GH Coin 실시간 화면 + 요약(:8080)을 추가/업데이트한다 (root 로 실행)
#
#   사용:  sudo bash add-dashboard.sh                  (처음이면 로그인 비밀번호를 만들어 마지막에 보여 줌)
#          sudo bash add-dashboard.sh --new-password   (비밀번호 새로 만들기 → 기존 로그인은 모두 풀림)
#          (파일을 직접 올렸으면)  sudo GHCOIN_DASH_SRC=/root/vps/dashboard bash add-dashboard.sh
#
# 하는 일
#   1. 앱 창(Chrome)에 '이 서버 안에서만' 열리는 통로(DevTools 9222, 127.0.0.1)를 켠다
#      + 방화벽 규칙으로 그 통로는 ghcoin 계정(Chrome · 대시보드)만 쓸 수 있게 막는다
#   2. ghcoin-dash 서비스 (:8080, Tailscale 로만 · 비밀번호 로그인)
#        /         실시간 화면: 봇 화면을 내 브라우저가 직접 그림 (그림 전송이 아니라 선명 · 부드러움) + 누르기 · 입력 · 승인
#        /summary  요약: 숫자 · 표 (보기 전용, 휴대폰용)
#   3. 로그인 비밀번호: 처음 한 번 만들어 /root/ghcoin-대시보드-비밀번호.txt 에 저장 (해시는 /etc/ghcoin/dash-password.hash)
# 앱(친구 코드)은 전혀 바꾸지 않는다. 다시 실행해도 안전함 (앱 창은 통로를 처음 켤 때만 다시 띄움 · 비밀번호는 그대로).
set -euo pipefail

BRANCH="${GHCOIN_BRANCH:-claude/vigilant-shannon-irq1vg}"
REV="${GHCOIN_REV:-$BRANCH}"     # 커밋 해시를 넣으면 그 커밋에서 받는다
RAW="https://raw.githubusercontent.com/g1792091-boop/crypto-bot-research/$REV/vps/dashboard"
LOCAL_SRC="${GHCOIN_DASH_SRC:-}"  # 이 폴더에서 복사 (내려받지 않음 · 내용 확인은 똑같이)
APP_USER="ghcoin"
DASH_DIR="/opt/ghcoin/dashboard"
DASH_PORT=8080
CDP_PORT=9222
PW_DIR="/etc/ghcoin"
PW_HASH="$PW_DIR/dash-password.hash"
PW_FILE="/root/ghcoin-대시보드-비밀번호.txt"
NEWPASS_ARG=""
[ "${1:-}" = "--new-password" ] && NEWPASS_ARG=1
FILES="ghcoin_dash.py mirror.py auth.py collector.js recorder.js live.html live.js live.css login.html summary.html
       vendor/rrweb-record.min.js vendor/rrweb-replay.min.js vendor/rrweb-replay.css vendor/LICENSE.rrweb vendor/SOURCES.txt"
# 받은 파일이 아래 값과 하나라도 다르면 설치하지 않는다 (이 파일들은 Chrome 통로 = 키 · 주문에 닿는 코드).
# vps/dashboard 파일을 고치면 같이 바꿀 것:  cd vps/dashboard && sha256sum <위 FILES>
declare -A SHA=(
  [ghcoin_dash.py]=d89fea01769da02b0b94c88127ab62c67832fec2781d6bbb908531c0226e2f17
  [mirror.py]=5963894d4c430f1f3af79a5c858fa64c26ccd4590de0110a982696bf2bbd0028
  [auth.py]=f9a8c7aa65d73f62104a04a596376f559db9319af6ee4f55956fe1d7e2dcac3a
  [collector.js]=6c365900e5c7f1adafd67818f0943b6c167abde1264dfd741624cb73b74a9264
  [recorder.js]=3321a854f697155fbf1dd9f5ce510c6f5f86331b0bd0d18fa3d29eee54336bc6
  [live.html]=097ec17a19564ada2be9b078004caaf72bd3e75c4de6f1bc7dff40cfe89f35e8
  [live.js]=6cdf6412ab33f7efebefc6706fba10e505315066ae8d76582de93137ea08db58
  [live.css]=bcc0561b3607ccd051e4e3166e4061a9cfcb08dda9d548888d4dd6a24be96350
  [login.html]=1afadd954c38efad575bf7be19c19921412f452f92e51a6c5230da128425efef
  [summary.html]=9c3440b38b85d6d2c453644f1aa84fed569f4c0048317307a82e96672a5985b4
  [vendor/rrweb-record.min.js]=fde9a5c5c38fc23c9f8d6429b4e74c8996156e1632f132693b68e32509dc92f0
  [vendor/rrweb-replay.min.js]=4ab2043bf8b77f5051c2b912f92feec7c22b9556718b04dddab8fdc09d8acce9
  [vendor/rrweb-replay.css]=64d720c3a8966a3764822abf7b14f78135c90ce09dcfae4286e50f06d9e01545
  [vendor/LICENSE.rrweb]=e49e62397b603438476e0d6b5ca3b6e6d4f23a80594e596aff29ac04fa3e1b1c
  [vendor/SOURCES.txt]=0e70db66851919d01afb7bb00a23a62fe991662ab2251f2cbcf7a3e15bc87ca0
)

say(){ printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "root 로 실행하세요:  sudo bash $0"
[ -f /etc/systemd/system/ghcoin-chrome.service ] || die "먼저 install-ghcoin.sh 로 GH Coin 을 설치하세요"
id "$APP_USER" >/dev/null 2>&1 || die "$APP_USER 계정이 없습니다 — 먼저 install-ghcoin.sh 로 설치하세요"
export DEBIAN_FRONTEND=noninteractive

say "필요한 패키지"
# fonts-nanum: 봇 화면의 사무실 · 채팅 글꼴(NanumGothicCoding) — 실시간 화면이 같은 글꼴 파일을 보는 쪽에 보내 줄바꿈이 똑같아짐
FONT_NEW=""
[ -f /usr/share/fonts/truetype/nanum/NanumGothicCoding.ttf ] || FONT_NEW=1
apt-get install -y -qq -o DPkg::Lock::Timeout=900 --no-install-recommends python3 python3-websocket curl iptables fonts-nanum fonts-nanum-coding >/dev/null

say "대시보드 파일 받기 (내용 확인)"
install -d -m 755 "$DASH_DIR" "$DASH_DIR/vendor"
for f in $FILES; do
  if [ -n "$LOCAL_SRC" ]; then
    cp -f "$LOCAL_SRC/$f" "$DASH_DIR/$f.new"
  else
    curl -fsSL -o "$DASH_DIR/$f.new" "$RAW/$f"
  fi
  if ! echo "${SHA[$f]}  $DASH_DIR/$f.new" | sha256sum -c --status -; then
    find "$DASH_DIR" -name '*.new' -delete
    die "$f 내용이 확인한 파일과 다릅니다 (새 버전이면 add-dashboard.sh 도 새로 받아서 다시 실행하세요)"
  fi
done
for f in $FILES; do mv -f "$DASH_DIR/$f.new" "$DASH_DIR/$f"; done   # 모두 확인된 뒤에만 바꿈
rm -rf "$DASH_DIR/index.html" "$DASH_DIR/__pycache__"                 # 예전(보기 전용) 대시보드의 첫 화면 파일 · 캐시
chmod 755 "$DASH_DIR/vendor"
chmod 644 "$DASH_DIR"/*.* "$DASH_DIR"/vendor/*

say "로그인 비밀번호"
# 실시간 화면은 봇을 조작할 수 있으므로(실거래 승인 포함) Tailscale 안에서도 비밀번호가 필요하다.
# 해시(scrypt)는 /etc/ghcoin (root:ghcoin 640, 대시보드만 읽음), 비밀번호 글자는 root 만 읽는 파일에.
install -d -m 755 "$PW_DIR"
NEWPASS=""
if [ -n "$NEWPASS_ARG" ] || [ ! -s "$PW_HASH" ]; then
  # 12글자 (헷갈리는 0/O/1/l/I 제외)
  DASHPASS=$(python3 -c "import secrets; a='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'; print(''.join(secrets.choice(a) for _ in range(12)))")
  ( umask 077
    printf '%s\n' "$DASHPASS" | python3 -B "$DASH_DIR/ghcoin_dash.py" --make-password-hash > "$PW_HASH.new" ) \
    || { rm -f "$PW_HASH.new"; die "비밀번호를 만들지 못했습니다"; }
  chown "root:$APP_USER" "$PW_HASH.new"; chmod 640 "$PW_HASH.new"
  ( umask 077; printf '%s\n' "$DASHPASS" > "$PW_FILE.new" ); chmod 600 "$PW_FILE.new"
  mv -f "$PW_HASH.new" "$PW_HASH"; mv -f "$PW_FILE.new" "$PW_FILE"
  NEWPASS=1
  echo "  새 비밀번호를 만들었습니다 (맨 아래 '완료' 상자에 보임)"
else
  chown "root:$APP_USER" "$PW_HASH"; chmod 640 "$PW_HASH"
  echo "  이미 있는 비밀번호를 그대로 씁니다 (새로 만들기:  sudo bash add-dashboard.sh --new-password)"
fi
DASHPASS=$(cat "$PW_FILE" 2>/dev/null || echo "(글자 파일 없음 — sudo bash add-dashboard.sh --new-password 로 새로 만드세요)")

say "통로 보호: 127.0.0.1:$CDP_PORT 은 $APP_USER 계정만 접속 가능"
# 이 서버의 다른 계정(실행기 ghcoin-srv 등)이 9222 로 봇 페이지에 붙어 키를 읽거나 주문하지 못하게 한다.
# 규칙은 OUTPUT 맨 앞에 넣는다 (ufw 의 'loopback 전부 허용' 보다 먼저 걸려야 함). 재부팅하면 이 서비스가 다시 넣음.
cat > /etc/systemd/system/ghcoin-cdp-guard.service <<EOF
[Unit]
Description=GH Coin DevTools 통로 보호 (127.0.0.1:$CDP_PORT 은 $APP_USER 계정만)
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
  || die "통로 보호 규칙을 넣지 못했습니다:  journalctl -u ghcoin-cdp-guard -n 20"

say "앱 창에 DevTools 통로 켜기 (127.0.0.1:$CDP_PORT, 서버 안에서만)"
UNIT=/etc/systemd/system/ghcoin-chrome.service
CHG=""
if ! grep -q -- "--remote-debugging-port=" "$UNIT"; then
  sed -i "s#^ExecStart=/usr/bin/google-chrome #ExecStart=/usr/bin/google-chrome --remote-debugging-port=$CDP_PORT #" "$UNIT"
  CHG=1
fi
grep -q -- "--remote-debugging-port=$CDP_PORT" "$UNIT" || die "앱 창 설정을 바꾸지 못했습니다: $UNIT"

cat > /etc/systemd/system/ghcoin-dash.service <<EOF
[Unit]
Description=GH Coin 실시간 화면 + 요약 (:$DASH_PORT, Tailscale 로만 · 비밀번호 로그인)
After=ghcoin-chrome.service ghcoin-cdp-guard.service
Wants=ghcoin-chrome.service ghcoin-cdp-guard.service

[Service]
User=$APP_USER
# MALLOC_*: 화면 사진(수 MB)을 보내고 버린 메모리가 스레드마다 쌓여 남지 않게 (glibc)
Environment=GHCOIN_DASH_PORT=$DASH_PORT GHCOIN_DASH_BIND=0.0.0.0 GHCOIN_CDP=http://127.0.0.1:$CDP_PORT GHCOIN_DASH_PWFILE=$PW_HASH PYTHONDONTWRITEBYTECODE=1 MALLOC_ARENA_MAX=2 MALLOC_MMAP_THRESHOLD_=131072
ExecStart=/usr/bin/python3 $DASH_DIR/ghcoin_dash.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
# /home 은 통째로 가림 (/home/$APP_USER 에는 키가 든 Chrome 저장소가 있고, 대시보드는 쓸 일이 없음)
ProtectHome=tmpfs
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
# 접속이 몰려도 서버 메모리를 다 먹지 못하게 (넘치면 대시보드만 죽고 다시 켜짐 — 봇 Chrome 은 그대로)
MemoryMax=256M
TasksMax=96
LimitNOFILE=1024
OOMScoreAdjust=500
# CPU 는 봇(Chrome)이 먼저
CPUWeight=50
Nice=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
if [ -n "$CHG" ]; then
  say "앱 창 다시 띄우기 (통로를 처음 켤 때 한 번만)"
  systemctl restart ghcoin-chrome
fi
systemctl enable -q ghcoin-dash
systemctl restart ghcoin-dash

# ghcoin-status 에 대시보드도 표시 (예전 install-ghcoin.sh 로 만든 것만 고침)
if [ -f /usr/local/bin/ghcoin-status ] && ! grep -q ghcoin-dash /usr/local/bin/ghcoin-status; then
  sed -i 's/for s in ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-novnc; do/for s in ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-dash; do/' /usr/local/bin/ghcoin-status
fi
# 예전 원격화면(noVNC :6080)은 없앤다 — 화면은 :8080 하나로
if [ -f /etc/systemd/system/ghcoin-novnc.service ]; then
  systemctl disable --now ghcoin-novnc >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/ghcoin-novnc.service
  systemctl daemon-reload
fi
rm -rf /opt/ghcoin/novnc /root/ghcoin-원격화면-비밀번호.txt
if [ -f /usr/local/bin/ghcoin-status ]; then
  sed -i 's/ ghcoin-novnc//; /6080/d' /usr/local/bin/ghcoin-status
fi

# 봇 탭이 죽거나('Aw, Snap' — 메모리 정리로 탭만 죽은 경우 포함) 멈춘 채로 3분이 넘으면 앱 창을 다시 띄운다
# (대시보드가 보는 상태로 판단 · 다시 띄운 뒤 10분은 기다림 · 기록은 journalctl -t ghcoin-watchdog)
cat > /usr/local/bin/ghcoin-watchdog <<'EOF'
#!/usr/bin/env bash
S=/run/ghcoin-watchdog; mkdir -p "$S"
st=$(curl -fsS -m 5 http://127.0.0.1:8080/healthz 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
case "$st" in
  crashed|no_app|stuck|no_chrome|no_page) ;;
  *) rm -f "$S/bad_since"; exit 0 ;;
esac
now=$(date +%s)
[ -f "$S/bad_since" ] || echo "$now" > "$S/bad_since"
since=$(cat "$S/bad_since"); last=$(cat "$S/last_restart" 2>/dev/null || echo 0)
if [ $((now - since)) -ge 180 ] && [ $((now - last)) -ge 600 ]; then
  logger -t ghcoin-watchdog "봇 상태 '$st' 가 $((now - since))초 계속됨 → 앱 창 다시 띄움"
  systemctl restart ghcoin-chrome
  echo "$now" > "$S/last_restart"; rm -f "$S/bad_since"
fi
EOF
chmod 755 /usr/local/bin/ghcoin-watchdog
cat > /etc/systemd/system/ghcoin-watchdog.service <<'EOF'
[Unit]
Description=GH Coin 봇 탭 감시 (죽거나 멈추면 앱 창 다시 띄움)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ghcoin-watchdog
EOF
cat > /etc/systemd/system/ghcoin-watchdog.timer <<'EOF'
[Unit]
Description=GH Coin 봇 탭 감시 (1분마다)

[Timer]
OnBootSec=3min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable -q ghcoin-watchdog.timer
systemctl restart ghcoin-watchdog.timer

say "확인 중 (최대 60초)"
ok=""
for i in $(seq 1 30); do
  if runuser -u "$APP_USER" -- curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$CDP_PORT/json/version" 2>/dev/null; then ok=1; break; fi
  sleep 2
done
if [ -n "$ok" ]; then
  # 다른 계정은 막혀야 정상
  if runuser -u nobody -- curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$CDP_PORT/json/version" 2>/dev/null; then
    die "통로 보호가 동작하지 않습니다 (다른 계정도 9222 에 접속됨). 화면을 캡처해서 보내 주세요."
  fi
else
  echo "  (앱 창의 통로가 아직 안 열렸습니다 — Chrome 이 켜지는 중이면 1분 안에 대시보드가 저절로 붙습니다)"
fi
ok=""
for i in $(seq 1 30); do
  if curl -fsS -m 3 "http://127.0.0.1:$DASH_PORT/healthz" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ -n "$ok" ] || { journalctl -u ghcoin-dash -n 30 --no-pager || true; die "대시보드가 아직 안 켜졌습니다. 위 기록을 캡처해서 보내 주세요."; }
# 비밀번호 없이 열면 로그인 화면으로 넘어가야 정상
code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:$DASH_PORT/" || true)
[ "$code" = 303 ] || die "실시간 화면이 로그인을 요구하지 않습니다 (응답 $code). 화면을 캡처해서 보내 주세요."

TSIP=$(tailscale ip -4 2>/dev/null | head -1 || true)
say "완료!"
cat <<EOF

  ┌───────────────────────────────────────────────────────────────┐
    GH Coin 화면:      Tailscale 켜고 →  http://${TSIP:-<tailscale IP>}:$DASH_PORT/
    로그인 비밀번호:   $DASHPASS$([ -n "$NEWPASS" ] && echo "  (새로 만듦)")
      (잊어버리면:  sudo cat $PW_FILE)
  └───────────────────────────────────────────────────────────────┘
  * 봇 화면을 그대로 보고 누르기 · 입력 · 키 넣기 · 실거래 승인까지 이 주소에서 합니다.
  * 숫자만 빠르게 보기(휴대폰):  http://${TSIP:-<tailscale IP>}:$DASH_PORT/summary
  * Tailscale Funnel 로 :$DASH_PORT 을 인터넷에 열지 마세요.
EOF
if [ -n "$FONT_NEW" ] && [ -z "$CHG" ]; then
  echo "  * 새 글꼴(나눔고딕코딩)은 봇 앱 창을 다시 띄운 뒤 쓰입니다 (매일 05:15 자동 · 바로 하려면  sudo systemctl restart ghcoin-chrome)"
fi
