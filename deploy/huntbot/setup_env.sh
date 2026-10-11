#!/usr/bin/env bash
# 추세 사냥 모의 봇 settings in one go, after install_huntbot.sh (docs/huntbot-ko.md):
#
#   bash deploy/huntbot/setup_env.sh                  Tailscale (installed and logged in when missing), dashboard
#                                                     address / secret / password, Telegram
#   bash deploy/huntbot/setup_env.sh --new-password   only change the dashboard password (and turn it back on)
#   bash deploy/huntbot/setup_env.sh --no-password    the dashboard without a password (Tailscale address only)
#   bash deploy/huntbot/setup_env.sh --telegram       only (re)enter the Telegram token and chats
#
# Values go only into /etc/huntbot/huntbot.env (root:huntbot 640) and are never printed (the Tailscale address is
# printed: it is the dashboard's address). The token and the password are typed hidden, on this server only.
set -euo pipefail
ENVF=/etc/huntbot/huntbot.env
VENV=/opt/huntbot/venv
APP=/opt/huntbot/app
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then echo "root로 실행하세요: sudo bash $0"; exit 1; fi
if [ ! -f "$ENVF" ] || [ ! -x "$VENV/bin/python" ] || [ ! -d "$APP/huntbot" ]; then
  echo "먼저 설치하세요: bash $HERE/install_huntbot.sh"; exit 1
fi

get() {
  local v
  v="$(grep -E "^$1=" "$ENVF" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}
put() {   # put KEY VALUE: the value travels in the environment, never on a command line
  K="$1" V="$2" F="$ENVF" "$VENV/bin/python" - <<'PY'
import os
k, v, f = os.environ["K"], os.environ["V"], os.environ["F"]
new = f"{k}='{v}'" if "$" in v else f"{k}={v}"
out, done = [], False
for line in open(f).read().splitlines():
    if line.startswith(k + "="):
        if not done:
            out.append(new)
            done = True
        continue
    out.append(line)
if not done:
    out.append(new)
tmp = f + ".new"
with open(tmp, "w") as fh:
    fh.write("\n".join(out) + "\n")
os.chmod(tmp, 0o640)
os.replace(tmp, f)
PY
  chown root:huntbot "$ENVF"
  chmod 640 "$ENVF"
}

telegram() {
  echo "== 텔레그램"
  echo "규칙봇·후보 리그에서 쓰는 봇 토큰을 그대로 써도 됩니다 (메시지 첫 줄에 '추세 사냥'이 붙습니다)."
  echo "토큰을 붙여 넣으세요. 화면에 안 보이는 게 정상입니다. 건너뛰려면 그냥 엔터."
  read -rs -p "봇 토큰: " TK; echo
  if [ -z "$TK" ]; then echo "텔레그램은 건너뜁니다 (나중에: bash $0 --telegram)"; return 0; fi
  read -r -p "받을 대화방 번호 (쉼표로 최대 4개, 예: 123456789,-1001234567890): " CH
  CH="$(printf '%s' "$CH" | tr -d ' ')"
  if ! [[ "$CH" =~ ^-?[0-9]+(,-?[0-9]+){0,3}$ ]]; then echo "번호 모양이 아닙니다. 다시: bash $0 --telegram"; unset TK; return 1; fi
  OK="$(TK="$TK" CH="$CH" "$VENV/bin/python" - <<'PY'
import json, os, urllib.parse, urllib.request
tk, chats = os.environ["TK"], os.environ["CH"].split(",")
ok = 0
for c in chats:
    body = urllib.parse.urlencode({"chat_id": c, "text": "📋 추세 사냥\n\n이 대화방으로 추세 사냥 모의 봇 알림이 옵니다 (라인업 진입·청산, 아침 9시 요약). 종이 매매, 실제 돈 아님.",
                                   "disable_notification": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{tk}/sendMessage", body, timeout=20) as r:
            ok += json.load(r).get("ok") is True
    except Exception:
        pass
print(ok)
PY
)"
  put HUNTBOT_TG_TOKEN "$TK"
  put HUNTBOT_TG_CHAT "$CH"
  unset TK
  echo "저장했습니다 (값은 화면에 나오지 않습니다). 시험 메시지 ${OK}개 보냄 - 텔레그램을 확인하세요."
}

tailscale_addr() {
  local a b d
  IFS=. read -r a b _ d <<< "$1"
  [[ "$a" == 100 && "$b" =~ ^[0-9]+$ && "$b" -ge 64 && "$b" -le 127 && -n "$d" ]]
}

if [ "${1:-}" = "--telegram" ]; then
  telegram
  systemctl restart huntbot-run.service || true
  exit 0
fi

if [ "${1:-}" = "--no-password" ]; then
  HOST="$(get HUNTBOT_DASH_HOST)"
  if ! tailscale_addr "$HOST"; then echo "대시보드 주소($HOST)가 Tailscale 주소가 아닙니다. 먼저: bash $0"; exit 1; fi
  put HUNTBOT_DASH_OPEN 1
  systemctl enable --quiet huntbot-dash.service
  systemctl restart huntbot-dash.service || echo "대시보드를 켜지 못했습니다: journalctl -u huntbot-dash -n 40 --no-pager"
  echo "이제 비밀번호 없이 열립니다: http://$HOST:$(get HUNTBOT_DASH_PORT | sed 's/^$/8092/') (Tailscale 기기에서만)"
  exit 0
fi

if [ "${1:-}" != "--new-password" ]; then
  echo "== 1. Tailscale (대시보드는 Tailscale 주소에서만 열립니다)"
  if ! command -v tailscale >/dev/null 2>&1; then
    echo "Tailscale을 설치합니다..."
    curl -fsSL https://tailscale.com/install.sh | sh >/dev/null
  fi
  if ! tailscale ip -4 >/dev/null 2>&1 || [ -z "$(tailscale ip -4 2>/dev/null | head -n 1)" ]; then
    echo "아래에 나오는 주소(https://login.tailscale.com/...)를 휴대폰이나 PC에서 열고, 규칙봇 서버와 같은 계정으로 승인하세요."
    tailscale up --hostname=hunt-judge
  fi
  HOST="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
  if [ -z "$HOST" ]; then echo "Tailscale 주소를 찾지 못했습니다. 'tailscale up' 뒤에 다시 실행하세요."; exit 1; fi
  put HUNTBOT_DASH_HOST "$HOST"
  echo "주소 $HOST"

  echo "== 2. 대시보드 비밀값"
  S="$(get HUNTBOT_DASH_SECRET)"
  if [ "${#S}" -ge 32 ]; then echo "이미 있습니다 (그대로)"; else
    put HUNTBOT_DASH_SECRET "$("$VENV/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
    echo "새로 만들었습니다 (화면에 나오지 않습니다)"
  fi
fi

echo "== 3. 대시보드 비밀번호"
H="$(get HUNTBOT_DASH_PASSWORD_HASH)"
if [[ "$H" == pbkdf2\$* ]] && [ "${1:-}" != "--new-password" ]; then
  echo "이미 있습니다 (바꾸려면: bash $0 --new-password)"
else
  echo "대시보드에 들어갈 때 쓸 비밀번호를 두 번 입력하세요 (화면에 보이지 않는 게 정상, 채팅에 쓰지 마세요)."
  H="$(cd "$APP" && "$VENV/bin/python" -B -m huntbot dash hash)" || H=""
  if [[ "$H" != pbkdf2\$* ]]; then echo "비밀번호를 정하지 못했습니다. 같은 명령을 다시 실행하세요."; exit 1; fi
  put HUNTBOT_DASH_PASSWORD_HASH "$H"
  put HUNTBOT_DASH_OPEN 0
  echo "저장했습니다 (해시로만)"
fi

if [ "${1:-}" != "--new-password" ] && [ -z "$(get HUNTBOT_TG_TOKEN)" ]; then
  telegram || true
fi

echo "== 4. 방화벽 (Tailscale에만)"
bash "$HERE/firewall.sh" || echo "방화벽 점검이 실패했습니다 (다른 것은 영향 없음): bash $HERE/firewall.sh"

echo "== 5. 다시 켜기"
systemctl enable --quiet huntbot-dash.service
systemctl restart huntbot-dash.service || echo "대시보드를 켜지 못했습니다: journalctl -u huntbot-dash -n 40 --no-pager"
systemctl restart huntbot-run.service || echo "엔진을 다시 켜지 못했습니다: journalctl -u huntbot-run -n 40 --no-pager"
echo "대시보드: http://$(get HUNTBOT_DASH_HOST):$(get HUNTBOT_DASH_PORT | sed 's/^$/8092/')  (Tailscale을 켠 PC·휴대폰에서)"
echo "끝."
