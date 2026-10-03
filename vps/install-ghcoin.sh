#!/usr/bin/env bash
# GH Coin 을 우분투 VPS 에서 24시간 돌리는 설치 스크립트 (Ubuntu 24.04, root 로 실행)
#
#   사용:  sudo bash install-ghcoin.sh '<구글 드라이브 공유 링크>'
#          (zip 을 서버에 직접 올렸으면)  sudo GHCOIN_ZIP=/root/crypto-bot-research.zip bash install-ghcoin.sh
#
# 하는 일
#   1. 가상 화면(XFCE 데스크톱) + Chrome 설치 — GH Coin 은 브라우저 창 안에서 돌아가는 앱이라 화면이 필요함
#   2. 드라이브의 zip 에서 앱 코드만 꺼내(약 30MB) 실행기를 빌드
#   3. 서비스 5개 등록 — 재부팅·충돌 시 자동으로 다시 켜짐
#        ghcoin-vnc(가상 화면) · ghcoin-desktop(XFCE) · ghcoin-server(앱 실행기) · ghcoin-chrome(앱 창) · ghcoin-novnc(웹 원격화면)
#   4. 방화벽: SSH 와 Tailscale 안쪽만 허용 → 화면 주소(8080 · 6080)는 Tailscale 로만 열림
#   5. Tailscale 설치·로그인
#   6. 실시간 화면(:8080, 비밀번호 로그인) — add-dashboard.sh. 봇 화면을 내 브라우저가 직접 그려서 선명함.
#      원격화면(noVNC :6080)은 비상용으로만 남는다.
#
# 다시 실행해도 안전함(이미 한 단계는 건너뜀). 비밀번호는 처음 만든 것을 유지.
set -euo pipefail

LINK="${1:-}"
ZIP_SHA256="${GHCOIN_ZIP_SHA256:-9eea1b6212f31bc5ab32a28031cb6038e32c4fbd14b7fe722b40d008d49460b1}"
GO_VER="1.24.7"
APP_USER="ghcoin"            # 화면 · Chrome(봇) 을 돌리는 계정
APP_HOME="/home/$APP_USER"
SRV_USER="ghcoin-srv"        # 앱 실행기(127.0.0.1:17860) 를 돌리는 계정
SRV_HOME="/home/$SRV_USER"
APP_DIR="/opt/ghcoin"
APP_PORT=17860
VNC_PORT=5901
NOVNC_PORT=6080
SCREEN="1600x900"
SRC_IN_ZIP="crypto-bot-research/crypto-bot-research"   # zip 안의 최신 코드 폴더

say(){ printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "root 로 실행하세요:  sudo bash $0 '<구글 드라이브 링크>'"
. /etc/os-release
[ "${VERSION_ID:-}" = "24.04" ] || echo "주의: Ubuntu 24.04 기준 스크립트입니다 (지금: ${PRETTY_NAME:-?})"
export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------- 0. 기본 설정
say "기본 설정 (시간대 · 스왑)"
timedatectl set-timezone Asia/Seoul 2>/dev/null || true
if ! swapon --show | grep -q .; then           # 메모리가 잠깐 몰려도 봇이 죽지 않게 2GB 여유
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo 'vm.swappiness=10' > /etc/sysctl.d/90-ghcoin-swap.conf && sysctl -q -p /etc/sysctl.d/90-ghcoin-swap.conf
fi

# ---------------------------------------------------------------- 1. 패키지
say "패키지 설치 (데스크톱 · 가상 화면 · 웹 원격화면 · 한글 글꼴) — 3~5분"
# 새 서버는 처음 몇 분 동안 자동 업데이트가 돌아서 설치가 막힐 수 있다 → 끝날 때까지 기다렸다가 진행
for i in $(seq 1 60); do apt-get update -qq 2>/dev/null && break; echo "  자동 업데이트가 끝나길 기다리는 중... ($i)"; sleep 10; done
apt-get install -y -qq -o DPkg::Lock::Timeout=900 --no-install-recommends \
  xfce4 xfce4-terminal dbus-x11 xfonts-base at-spi2-core \
  tigervnc-standalone-server tigervnc-tools novnc websockify \
  fonts-noto-cjk fonts-noto-color-emoji xdg-utils \
  curl ca-certificates unzip python3 ufw cron earlyoom >/dev/null
# 화면 잠금이 걸리면 원격화면에서 풀 수 없으므로 잠금 프로그램은 빼 둔다
apt-get purge -y -qq xfce4-screensaver light-locker >/dev/null 2>&1 || true

if ! command -v google-chrome >/dev/null; then
  say "Google Chrome 설치"
  curl -fsSL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y -qq -o DPkg::Lock::Timeout=900 /tmp/chrome.deb >/dev/null
  rm -f /tmp/chrome.deb
fi

# ---------------------------------------------------------------- 2. 실행 계정
id "$APP_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$APP_USER"   # root 가 아닌 전용 계정으로 돌린다
# 실행기는 따로 된 계정으로: 혹시 무엇이 실행기를 통해 파일에 닿아도 Chrome 저장소(키)는 못 읽게
id "$SRV_USER" >/dev/null 2>&1 || useradd -m -s /usr/sbin/nologin "$SRV_USER"
chmod 700 "$APP_HOME"

# ---------------------------------------------------------------- 3. 앱 코드 받기 · 빌드
say "GH Coin 코드 받기"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
ZIP="${GHCOIN_ZIP:-}"
if [ -z "$ZIP" ]; then
  ID=""
  if [[ "$LINK" =~ /d/([A-Za-z0-9_-]{20,}) ]]; then ID="${BASH_REMATCH[1]}"
  elif [[ "$LINK" =~ [?\&]id=([A-Za-z0-9_-]{20,}) ]]; then ID="${BASH_REMATCH[1]}"
  elif [[ "$LINK" =~ ^[A-Za-z0-9_-]{20,}$ ]]; then ID="$LINK"
  fi
  [ -n "$ID" ] || die "구글 드라이브 공유 링크를 같이 넣어 주세요:  sudo bash $0 'https://drive.google.com/file/d/.../view'"
  ZIP="$WORK/src.zip"
  echo "  2GB 정도라 1~3분 걸립니다..."
  curl -fL --retry 3 -sS -o "$ZIP" "https://drive.usercontent.google.com/download?id=$ID&export=download&confirm=t"
fi
[ -f "$ZIP" ] || die "zip 파일이 없습니다: $ZIP"
if ! unzip -tqq "$ZIP" >/dev/null 2>&1; then
  die "받은 파일이 zip 이 아닙니다. 드라이브 공유가 '링크가 있는 모든 사용자'인지 확인하세요."
fi
if [ "${GHCOIN_SKIP_SHA:-0}" != 1 ]; then
  echo "  파일 확인 중..."
  [ "$(sha256sum "$ZIP" | cut -d' ' -f1)" = "$ZIP_SHA256" ] \
    || die "zip 내용이 확인한 파일과 다릅니다(새 버전?). 그래도 진행하려면 GHCOIN_SKIP_SHA=1 을 붙여 다시 실행하세요."
fi
unzip -qq "$ZIP" "$SRC_IN_ZIP/index.html" "$SRC_IN_ZIP/nuri-ai/*" "$SRC_IN_ZIP/gh-coin/*" \
  "$SRC_IN_ZIP/arch-ai/*" "$SRC_IN_ZIP/launcher/*" -d "$WORK/x"
if [ -z "${GHCOIN_ZIP:-}" ]; then rm -f "$ZIP"; fi   # 내려받은 2GB 는 바로 지운다
SRC="$WORK/x/$SRC_IN_ZIP"

say "실행기 빌드 (Go $GO_VER, 빌드 후 삭제) — 1~2분"
GOROOT_DIR="$WORK/go"
mkdir -p "$GOROOT_DIR"
curl -fsSL "https://go.dev/dl/go${GO_VER}.linux-amd64.tar.gz" | tar -C "$WORK" -xz
L="$SRC/launcher"
rm -rf "$L/site" && mkdir -p "$L/site"
cp "$SRC/index.html" "$L/site/"
cp -r "$SRC/nuri-ai" "$SRC/arch-ai" "$SRC/gh-coin" "$L/site/"
rm -f "$L"/site/*/README.md
rm -f "$L/site/arch-ai/app.html"   # 쓰지 않는 페이지인데 외부(CDN) 코드를 불러오므로 뺀다

# VPS 보안 강화: 서버용 빌드에만 아래 파일을 더한다 (앱 코드 · PC 용 exe 는 그대로)
#   AI 직원이 서버에서 명령어 실행 ✗ · 사무실 폴더 밖 파일 ✗ · 앱 코드 바꿔치기 ✗ · 외부 주소로 접속 ✗ · 내부 주소로 중계 ✗
cat > "$L/vps_harden.go" <<'GOEOF'
package main

// VPS 전용 보안 강화 — install-ghcoin.sh 가 서버용으로 빌드할 때만 넣는 파일 (원본 앱 코드는 그대로)
//  1. AI 가 서버에서 명령어를 실행하는 기능(/__nuri/code/exec) 끔
//  2. 파일 읽기·쓰기는 사무실 폴더 안에서만 (다른 폴더 열기·고르기 금지)
//  3. AI 가 고친 앱 파일로 바꿔치기(app-patches) 끔
//  4. 접속 주소(Host)가 127.0.0.1 · localhost 가 아니면 거절 (DNS 리바인딩 방지)
//  5. API 중계가 서버 내부 주소(127.0.0.1 · 사설 · Tailscale IP)로 가는 것 금지

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"strings"
	"syscall"
	"time"
)

const vpsHardened = true

func init() {
	proxyClient.Transport = &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: (&net.Dialer{
			Timeout: 15 * time.Second,
			Control: func(network, address string, c syscall.RawConn) error {
				host, _, err := net.SplitHostPort(address)
				if err != nil {
					return err
				}
				if !isPublicIP(net.ParseIP(host)) {
					return errors.New("서버 내부 주소로는 중계하지 않습니다")
				}
				return nil
			},
		}).DialContext,
		TLSHandshakeTimeout: 15 * time.Second,
		IdleConnTimeout:     90 * time.Second,
	}
}

func vpsDeny(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusForbidden)
	json.NewEncoder(w).Encode(map[string]any{"ok": false, "error": msg})
}

func vpsGuard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host := r.Host
		if h, _, err := net.SplitHostPort(host); err == nil {
			host = h
		}
		if host != "127.0.0.1" && host != "localhost" {
			http.Error(w, "forbidden host", http.StatusForbidden)
			return
		}
		p := r.URL.Path
		if strings.HasPrefix(p, "/__nuri/code/") {
			switch strings.TrimPrefix(p, "/__nuri/code/") {
			case "exec", "pick", "open":
				vpsDeny(w, "이 서버(VPS)에서는 보안을 위해 꺼 둔 기능입니다 (명령 실행 · 폴더 바꾸기)")
				return
			}
			if r.Method == http.MethodPost { // 모든 파일 작업을 사무실 폴더 안으로 고정
				body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 20<<20))
				if err != nil {
					http.Error(w, "too large", http.StatusRequestEntityTooLarge)
					return
				}
				var in map[string]any
				if json.Unmarshal(body, &in) != nil || in == nil {
					in = map[string]any{}
				}
				in["ws"] = "office"
				nb, _ := json.Marshal(in)
				r.Body = io.NopCloser(bytes.NewReader(nb))
				r.ContentLength = int64(len(nb))
			}
		}
		if strings.HasPrefix(p, "/__nuri/override") && r.Method != http.MethodGet && r.Method != http.MethodHead {
			vpsDeny(w, "이 서버(VPS)에서는 앱 코드 고치기를 꺼 두었습니다")
			return
		}
		next.ServeHTTP(w, r)
	})
}
GOEOF
sed -i 's#srv := &http.Server{Handler: mux}#srv := \&http.Server{Handler: vpsGuard(mux)}#' "$L/main.go"
sed -i 's/^func overridesEnabled() bool {\r\?$/func overridesEnabled() bool {\n\tif vpsHardened {\n\t\treturn false\n\t}/' "$L/override.go"
grep -q 'vpsGuard(mux)' "$L/main.go" && grep -q 'if vpsHardened' "$L/override.go" \
  || die "보안 강화 패치를 넣지 못했습니다 (앱 코드 구조가 바뀐 것 같습니다). 화면을 캡처해서 보내 주세요."
mkdir -p "$APP_DIR"
( cd "$L" && GOPATH="$WORK/gopath" GOCACHE="$WORK/gocache" GOFLAGS=-modcacherw GOTOOLCHAIN=local CGO_ENABLED=0 \
    "$GOROOT_DIR/bin/go" build -trimpath \
    -ldflags "-s -w -X main.startPath=/gh-coin/ -X 'main.appName=GH Coin'" -o "$APP_DIR/ghcoin.new" . )
mv -f "$APP_DIR/ghcoin.new" "$APP_DIR/ghcoin"
chmod 755 "$APP_DIR/ghcoin"

# ---------------------------------------------------------------- 4. 웹 원격화면 비밀번호 · 첫 화면
say "웹 원격화면 설정"
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$APP_HOME/.vnc"
PASSFILE=/root/ghcoin-원격화면-비밀번호.txt
if [ ! -s "$APP_HOME/.vnc/passwd" ] || [ ! -s "$PASSFILE" ]; then
  # 원격화면 비밀번호는 8글자까지만 쓰임 (헷갈리는 0/O/1/l/I 제외)
  VNCPASS=$(python3 -c "import secrets; a='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'; print(''.join(secrets.choice(a) for _ in range(8)))")
  printf '%s\n' "$VNCPASS" | vncpasswd -f > "$APP_HOME/.vnc/passwd"
  printf '%s\n' "$VNCPASS" > "$PASSFILE"; chmod 600 "$PASSFILE"
fi
chown "$APP_USER:$APP_USER" "$APP_HOME/.vnc/passwd"; chmod 600 "$APP_HOME/.vnc/passwd"
VNCPASS=$(cat "$PASSFILE")

# XFCE 첫 실행 때 뜨는 '패널 설정' 질문 창이 화면을 가리지 않게 기본 패널을 미리 깔아 둔다
XFCONF="$APP_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
if [ ! -f "$XFCONF/xfce4-panel.xml" ] && [ -f /etc/xdg/xfce4/panel/default.xml ]; then
  install -d -o "$APP_USER" -g "$APP_USER" "$APP_HOME/.config" "$APP_HOME/.config/xfce4" "$APP_HOME/.config/xfce4/xfconf" "$XFCONF"
  install -o "$APP_USER" -g "$APP_USER" -m 644 /etc/xdg/xfce4/panel/default.xml "$XFCONF/xfce4-panel.xml"
fi

rm -rf "$APP_DIR/novnc" && cp -r /usr/share/novnc "$APP_DIR/novnc"
cat > "$APP_DIR/novnc/index.html" <<'EOF'
<!doctype html><meta charset="utf-8"><title>GH Coin</title>
<script>location.replace("vnc.html?autoconnect=1&resize=scale&reconnect=1&reconnect_delay=3000");</script>
EOF

# ---------------------------------------------------------------- 5. 서비스
say "서비스 등록 (재부팅·충돌 시 자동 재시작)"
cat > /etc/systemd/system/ghcoin-vnc.service <<EOF
[Unit]
Description=GH Coin 가상 화면 (VNC :1, 이 서버 안에서만)
After=network.target

[Service]
User=$APP_USER
ExecStartPre=-/bin/rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
ExecStart=/usr/bin/Xtigervnc :1 -geometry $SCREEN -depth 24 -rfbport $VNC_PORT -localhost -rfbauth $APP_HOME/.vnc/passwd -SecurityTypes VncAuth -AlwaysShared -desktop "GH Coin" -s 0
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/ghcoin-desktop.service <<EOF
[Unit]
Description=GH Coin 데스크톱 (XFCE)
Requires=ghcoin-vnc.service
After=ghcoin-vnc.service

[Service]
User=$APP_USER
Environment=DISPLAY=:1 HOME=$APP_HOME
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/dbus-launch --exit-with-session /usr/bin/startxfce4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/ghcoin-server.service <<EOF
[Unit]
Description=GH Coin 앱 실행기 (127.0.0.1:$APP_PORT, 이 서버 안에서만)
After=network-online.target
Wants=network-online.target

[Service]
User=$SRV_USER
Environment=HOME=$SRV_HOME NURI_NO_BROWSER=1 NURI_IDLE_EXIT=87600h NURI_FIRST_WAIT=87600h
WorkingDirectory=$SRV_HOME
ExecStart=$APP_DIR/ghcoin
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# 앱 창: 창을 닫거나 Chrome 이 죽어도 10초 뒤 다시 열림.
# 백그라운드 절약 옵션을 꺼서 아무도 화면을 안 봐도 봇 타이머가 느려지지 않게 한다.
# 웹 대시보드(add-dashboard.sh)를 이미 켰으면 읽기 통로(127.0.0.1:9222)를 그대로 유지한다 (다시 실행해도 대시보드가 끊기지 않게).
CDP_FLAG=""
if [ -f /etc/systemd/system/ghcoin-dash.service ] || grep -qs -- "--remote-debugging-port=" /etc/systemd/system/ghcoin-chrome.service; then
  CDP_FLAG="--remote-debugging-port=9222 "
fi
cat > /etc/systemd/system/ghcoin-chrome.service <<EOF
[Unit]
Description=GH Coin 앱 창 (Chrome)
Requires=ghcoin-vnc.service
After=ghcoin-desktop.service ghcoin-server.service

[Service]
User=$APP_USER
Environment=DISPLAY=:1 HOME=$APP_HOME
ExecStartPre=/bin/sleep 6
ExecStart=/usr/bin/google-chrome ${CDP_FLAG}--app=http://127.0.0.1:$APP_PORT/gh-coin/ --user-data-dir=$APP_HOME/.config/ghcoin-chrome --no-first-run --no-default-browser-check --password-store=basic --start-maximized --disable-session-crashed-bubble --hide-crash-restore-bubble --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --disable-features=IntensiveWakeUpThrottling,CalculateNativeWinOcclusion
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/ghcoin-novnc.service <<EOF
[Unit]
Description=GH Coin 웹 원격화면 (noVNC :$NOVNC_PORT, Tailscale 로만 접속)
Requires=ghcoin-vnc.service
After=ghcoin-vnc.service

[Service]
User=$APP_USER
ExecStart=/usr/bin/websockify --web=$APP_DIR/novnc $NOVNC_PORT 127.0.0.1:$VNC_PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Chrome 정책: 봇 탭을 절대 잠재우지 않기 (메모리 절약 모드 · 백그라운드 타이머 느리게 하기 끄기)
#              + 화면을 가리는 팝업 끄기 (번역 · 비밀번호 저장 · 알림 권한)
install -d /etc/opt/chrome/policies/managed
cat > /etc/opt/chrome/policies/managed/ghcoin.json <<EOF
{
  "IntensiveWakeUpThrottlingEnabled": false,
  "HighEfficiencyModeEnabled": false,
  "TabDiscardingExceptions": ["http://127.0.0.1:$APP_PORT"],
  "TranslateEnabled": false,
  "PasswordManagerEnabled": false,
  "DefaultNotificationsSetting": 2,
  "BrowserSignin": 0,
  "DefaultBrowserSettingEnabled": false,
  "PromotionalTabsEnabled": false,
  "MetricsReportingEnabled": false
}
EOF

# 메모리가 바닥나면 서버 전체가 멈추기 전에 Chrome 만 정리 → 서비스가 10초 뒤 다시 켬
cat > /etc/default/earlyoom <<'EOF'
EARLYOOM_ARGS="-r 3600 -m 5 -s 10 --prefer (^|/)(chrome)$ --avoid (^|/)(Xtigervnc|xfce4-session|sshd|ghcoin|websockify|tailscaled|systemd)$"
EOF
systemctl enable -q earlyoom
systemctl restart earlyoom

# 하루 한 번(새벽 5시 15분) 앱 창을 새로 띄워 오래 켜 둘 때 쌓이는 메모리를 비운다 (설정·기록은 그대로)
cat > /etc/systemd/system/ghcoin-chrome-restart.service <<'EOF'
[Unit]
Description=GH Coin 앱 창 새로 띄우기

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart ghcoin-chrome.service
EOF
cat > /etc/systemd/system/ghcoin-chrome-restart.timer <<'EOF'
[Unit]
Description=GH Coin 앱 창 매일 05:15 새로 띄우기

[Timer]
OnCalendar=*-*-* 05:15:00

[Install]
WantedBy=timers.target
EOF

# 5분마다 메모리 기록 → ghcoin-status 에서 추세를 본다 (최근 2000줄만 보관)
cat > /usr/local/bin/ghcoin-memlog <<'EOF'
#!/usr/bin/env bash
f=/var/log/ghcoin-mem.log
avail=$(free -m | awk 'NR==2{print $7}'); swap=$(free -m | awk 'NR==3{print $3}')
chrome=$(ps -C chrome -o rss= 2>/dev/null | awk '{s+=$1} END {print int(s/1024)}')
echo "$(date '+%F %T') 남은메모리=${avail}MB 스왑사용=${swap}MB 크롬=${chrome}MB 부하=$(cut -d' ' -f1 /proc/loadavg)" >> "$f"
tail -n 2000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
EOF
chmod 755 /usr/local/bin/ghcoin-memlog
echo '*/5 * * * * root /usr/local/bin/ghcoin-memlog' > /etc/cron.d/ghcoin-memlog

# 상태 확인 명령:  ghcoin-status
cat > /usr/local/bin/ghcoin-status <<'EOF'
#!/usr/bin/env bash
echo "== 서비스 (전부 active 여야 정상)"
for s in ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-novnc ghcoin-dash; do
  [ "$s" = ghcoin-dash ] && [ ! -f /etc/systemd/system/ghcoin-dash.service ] && continue
  printf '  %-16s %s\n' "$s" "$(systemctl is-active "$s")"
done
echo "== 메모리 (available 이 500Mi 밑으로 자주 내려가면 사양 올리기)"
free -h | sed 's/^/  /'
echo "== 최근 메모리 기록 (5분 간격)"
if [ -s /var/log/ghcoin-mem.log ]; then tail -n 6 /var/log/ghcoin-mem.log | sed 's/^/  /'; else echo "  (아직 없음)"; fi
echo "== 디스크"
df -h / | sed 's/^/  /'
echo "== 주소 (Tailscale 켜고 열기)"
ip4=$(tailscale ip -4 2>/dev/null | head -1)
[ -f /etc/systemd/system/ghcoin-dash.service ] && echo "  실시간 화면(로그인)  http://${ip4:-<tailscale IP>}:8080/"
echo "  비상용 원격화면      http://${ip4:-<tailscale IP>}:6080/"
EOF
chmod 755 /usr/local/bin/ghcoin-status

systemctl daemon-reload
systemctl enable -q ghcoin-vnc ghcoin-desktop ghcoin-server ghcoin-chrome ghcoin-novnc ghcoin-chrome-restart.timer
systemctl start ghcoin-chrome-restart.timer
systemctl restart ghcoin-vnc ghcoin-server ghcoin-novnc
systemctl restart ghcoin-desktop
systemctl restart ghcoin-chrome

# ---------------------------------------------------------------- 6. 방화벽
say "방화벽: SSH 와 Tailscale 만 허용"
ufw allow OpenSSH >/dev/null
ufw allow in on tailscale0 >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw --force enable >/dev/null

# ---------------------------------------------------------------- 7. Tailscale
if ! command -v tailscale >/dev/null; then
  say "Tailscale 설치"
  curl -fsSL https://tailscale.com/install.sh | sh >/dev/null
fi
if ! tailscale ip -4 >/dev/null 2>&1; then
  say "Tailscale 로그인 — 아래에 나오는 주소를 열어서 다른 봇 서버와 같은 계정으로 로그인하세요"
  tailscale up
fi
TSIP=$(tailscale ip -4 2>/dev/null | head -1 || true)

# ---------------------------------------------------------------- 8. 실시간 화면 + 요약 (:8080, 비밀번호 로그인)
DASH_OK=""
if [ "${GHCOIN_NO_DASH:-0}" != 1 ]; then
  say "실시간 화면(:8080) 설치"
  DREV="${GHCOIN_REV:-claude/vigilant-shannon-irq1vg}"
  if [ -n "${GHCOIN_DASH_SRC:-}" ] && [ -f "$GHCOIN_DASH_SRC/../add-dashboard.sh" ]; then   # 파일을 직접 올렸으면
    cp "$GHCOIN_DASH_SRC/../add-dashboard.sh" "$WORK/add-dashboard.sh"
  else
    curl -fsSL -o "$WORK/add-dashboard.sh" "https://raw.githubusercontent.com/g1792091-boop/crypto-bot-research/$DREV/vps/add-dashboard.sh" || true
  fi
  if [ -s "$WORK/add-dashboard.sh" ] && GHCOIN_REV="$DREV" bash "$WORK/add-dashboard.sh"; then
    DASH_OK=1
  else
    echo "  (실시간 화면 설치는 실패했지만 봇은 정상입니다 — 위 화면을 캡처해서 보내 주세요. 그동안은 원격화면 :6080 으로 보세요)"
  fi
fi
DASHPASS=$(cat "/root/ghcoin-대시보드-비밀번호.txt" 2>/dev/null || true)

sleep 5
say "완료!"
ghcoin-status
if [ -n "$DASH_OK" ]; then
cat <<EOF

  ┌───────────────────────────────────────────────────────────────┐
    GH Coin 화면:       Tailscale 켜고 →  http://${TSIP:-<tailscale IP>}:8080/
    로그인 비밀번호:    ${DASHPASS:-(sudo cat /root/ghcoin-대시보드-비밀번호.txt)}
      (잊어버리면:  sudo cat /root/ghcoin-대시보드-비밀번호.txt)
    상태 확인:          ghcoin-status
  └───────────────────────────────────────────────────────────────┘
  * 이 주소 하나로 봇 화면을 그대로 보고, 누르기 · 키 입력 · 설정 · 실거래 승인까지 합니다.
  * 비상용 원격화면(noVNC): http://${TSIP:-<tailscale IP>}:$NOVNC_PORT/  비밀번호 $VNCPASS  (sudo cat $PASSFILE)
EOF
else
cat <<EOF

  ┌───────────────────────────────────────────────────────────────┐
    원격화면:           Tailscale 켜고 →  http://${TSIP:-<tailscale IP>}:$NOVNC_PORT/
    원격화면 비밀번호:  $VNCPASS
      (잊어버리면:  sudo cat $PASSFILE)
    상태 확인:          ghcoin-status
  └───────────────────────────────────────────────────────────────┘
EOF
fi
cat <<EOF
  * 이 서버용 빌드는 AI 직원의 명령어 실행 · 앱 코드 고치기를 꺼 두었습니다 (키 보호).
  * 앱 창은 닫아도 10초 뒤 다시 열립니다. 봇 탭이 죽거나 멈추면 3분 뒤 자동으로 다시 띄웁니다.
  * 서버가 재부팅돼도 자동으로 켜집니다.
  * 매일 새벽 5:15 에 앱 창을 새로 띄워 메모리를 비웁니다 (설정·기록은 그대로).
  * AI 키 · 거래소 키는 그 화면 안의 GH Coin 에 처음 한 번 넣어 주세요.
  * 다 설치됐으면 구글 드라이브 공유를 다시 '제한됨'으로 바꿔도 됩니다.
EOF
