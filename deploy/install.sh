#!/usr/bin/env bash
# GH Quant — 리눅스 서버(오라클 클라우드 무료 서버 등)에 설치해서 24시간 돌리기
#
#   curl -fsSL https://raw.githubusercontent.com/g1792091-boop/crypto-bot-research/claude/sweet-pascal-t82h6j/deploy/install.sh | sudo bash
#
# 하는 일: 파이썬 설치 → 코드 받기 → 설정(접속 비밀번호 · AI 키) → 서비스 등록(꺼져도 자동 재시작 · 서버 재부팅 때 자동 시작)
#          → (선택) Tailscale 로 안전하게 접속 또는 방화벽 포트 열기
# 다시 실행해도 됩니다 (코드만 새로 받고 설정은 그대로).
# 묻지 않고 설치: APP_PASSWORD=… NVIDIA_API_KEY=… USE_TAILSCALE=n 을 앞에 붙여 sudo -E bash install.sh
set -euo pipefail

REPO="${REPO:-https://github.com/g1792091-boop/crypto-bot-research.git}"
BRANCH="${BRANCH:-claude/sweet-pascal-t82h6j}"
APP_DIR="${APP_DIR:-/opt/gh-quant}"          # 코드
DATA_DIR="${DATA_DIR:-/opt/gh-quant-data}"   # 설정 파일 · 기록 (업데이트해도 남음)
PORT="${PORT:-8000}"
RUN_USER="${SUDO_USER:-${RUN_USER:-$(id -un)}}"
SERVICE=gh-quant

say() { printf '\n\033[1;33m▶ %s\033[0m\n' "$*"; }
ask() { local q="$1" def="${2:-}" a=""; { read -r -p "$q" a </dev/tty; } 2>/dev/null || true; echo "${a:-$def}"; }

[ "$(id -u)" -eq 0 ] || { echo "sudo 로 실행하세요: curl ... | sudo bash"; exit 1; }
command -v apt-get >/dev/null || { echo "Ubuntu/Debian 용 스크립트입니다 (오라클 클라우드에서 Ubuntu 이미지를 고르세요)."; exit 1; }

say "1/6 필요한 프로그램 설치 (python3 · git)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates >/dev/null

# 메모리가 1GB 인 무료 서버(E2.1.Micro)는 스왑이 있어야 안정적
if [ "$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)" -lt 2000 ] && ! swapon --show | grep -q .; then
  say "메모리가 작아 스왑 2GB 를 만듭니다"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "2/6 코드 받기 ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR"
  sudo -u "$RUN_USER" git -C "$APP_DIR" fetch -q origin "$BRANCH"
  sudo -u "$RUN_USER" git -C "$APP_DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
else
  git clone -q -b "$BRANCH" --depth 50 "$REPO" "$APP_DIR"
fi
mkdir -p "$DATA_DIR/state"
chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR" "$DATA_DIR"

say "3/6 파이썬 패키지 설치"
sudo -u "$RUN_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$RUN_USER" "$APP_DIR/venv/bin/pip" install -q --upgrade pip
grep -v '^pytest' "$APP_DIR/backend/requirements.txt" > /tmp/gh-quant-req.txt
sudo -u "$RUN_USER" "$APP_DIR/venv/bin/pip" install -q -r /tmp/gh-quant-req.txt

say "4/6 설정"
SETTINGS="$DATA_DIR/settings.txt"
if [ ! -f "$SETTINGS" ] || ! grep -q '^APP_PASSWORD=.\+' "$SETTINGS"; then
  echo "브라우저로 들어갈 때 쓸 접속 비밀번호를 정하세요 (8자 이상 권장, 다른 사람이 못 들어오게)."
  PW="${APP_PASSWORD:-}"
  while [ -z "$PW" ]; do
    read -r -s -p "  접속 비밀번호: " PW </dev/tty; echo
    read -r -s -p "  한 번 더: " PW2 </dev/tty; echo
    [ -n "$PW" ] && [ "$PW" = "$PW2" ] && break
    PW=""; echo "  비어 있거나 서로 다릅니다. 다시 입력하세요."
  done
  NV="${NVIDIA_API_KEY:-$(ask "  NVIDIA API 키 (nvapi-…, 무료 · 없으면 Enter): ")}"
  GM="${GEMINI_API_KEY:-$(ask "  Gemini API 키 (AIza…, 무료 · 없으면 Enter): ")}"
  cat > "$SETTINGS" <<EOF
# GH Quant 서버 설정 — 고친 뒤: sudo systemctl restart $SERVICE
APP_PASSWORD=$PW
HOST=0.0.0.0
PORT=$PORT
NVIDIA_API_KEY=$NV
NVIDIA_MODEL=
NVIDIA_FAST_MODEL=
GEMINI_API_KEY=$GM
ANTHROPIC_API_KEY=
LLM_PROVIDER=auto
COINGLASS_API_KEY=
DATA_SOURCE=auto
EOF
  chown "$RUN_USER":"$RUN_USER" "$SETTINGS"; chmod 600 "$SETTINGS"
else
  echo "  기존 설정을 그대로 씁니다: $SETTINGS"
  PORT=$(grep -oP '^PORT=\K[0-9]+' "$SETTINGS" || echo "$PORT")
fi

say "5/6 서비스 등록 (24시간 · 꺼지면 5초 뒤 자동 재시작 · 재부팅 때 자동 시작)"
cat > /etc/systemd/system/$SERVICE.service <<EOF
[Unit]
Description=GH Quant (24시간 분석 · 모의 매매)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR/backend
Environment=SETTINGS_FILE=$SETTINGS
Environment=STATE_DIR=$DATA_DIR/state
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/venv/bin/python launcher.py --server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q $SERVICE
systemctl restart $SERVICE
sleep 4
systemctl is-active -q $SERVICE && echo "  실행 중" || { echo "  시작 실패 — 로그:"; journalctl -u $SERVICE -n 30 --no-pager; exit 1; }

say "6/6 접속 방법"
TS="${USE_TAILSCALE:-$(ask "  Tailscale 로 접속할까요? (권장: 포트를 열지 않고 내 폰·PC 에서만 암호화 접속) [Y/n]: " "y")}"
if [[ "$TS" =~ ^[Yy] ]]; then
  command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
  echo "  아래에 나오는 주소를 열어 Tailscale 에 로그인하세요 (폰·PC 에도 같은 계정으로 Tailscale 앱 설치)."
  tailscale up
  TIP=$(tailscale ip -4 2>/dev/null | head -1)
  URL="http://$TIP:$PORT"
else
  # 오라클 우분투 이미지는 iptables 가 기본으로 막아 둔다 → 이 포트만 연다
  N=$(iptables -L INPUT --line-numbers -n 2>/dev/null | awk '/REJECT/{print $1; exit}')
  if [ -n "$N" ]; then
    iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null || iptables -I INPUT "$N" -p tcp --dport "$PORT" -j ACCEPT
    command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true
  fi
  command -v ufw >/dev/null && ufw status | grep -q active && ufw allow "$PORT/tcp" >/dev/null || true
  PIP=$(curl -fsS --max-time 5 https://api.ipify.org || echo "<서버 공인 IP>")
  URL="http://$PIP:$PORT"
  echo "  ⚠ 오라클 콘솔에서도 포트를 열어야 합니다: 인스턴스 → 서브넷 → 보안 목록 → 수신 규칙 추가 (TCP $PORT, 소스 0.0.0.0/0)"
  echo "  ⚠ http 는 암호화되지 않습니다. 가능하면 Tailscale 방식을 쓰세요."
fi

cat <<EOF

────────────────────────────────────────────────────────
 설치 끝 — GH Quant 가 24시간 돌고 있습니다.
 접속 주소 : $URL   (아이디는 아무거나, 비밀번호는 방금 정한 것)
 설정 파일 : $SETTINGS   (고친 뒤 sudo systemctl restart $SERVICE)
 상태 보기 : sudo systemctl status $SERVICE
 로그 보기 : journalctl -u $SERVICE -f
 업데이트  : sudo bash $APP_DIR/deploy/update.sh
────────────────────────────────────────────────────────
EOF
