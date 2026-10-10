#!/usr/bin/env bash
# 후보 리그 (candidate league) settings in one go, after install_candleague.sh (docs/candleague-ko.md "설치"):
#
#   sudo bash deploy/candleague/setup_env.sh                  # Telegram, dashboard address / secret / password
#   sudo bash deploy/candleague/setup_env.sh --new-password   # only to change the dashboard password later
#
# 1. Telegram: when the league has none yet, the demo lab bot's token and chats (/etc/demobot/demobot.env) are copied
#    in on this server (every league message starts with [후보 리그]); no new key, nothing pasted anywhere.
# 2. Dashboard: the server's Tailscale address, a random secret, and a password typed twice (stored only as a hash).
# Values go only into /etc/candleague/candleague.env (root:candleague 640) and are never printed (the Tailscale
# address is printed: it is the dashboard's address). Then the firewall check (Tailscale only) and a restart of the
# league's own services. Never touches the rule bot or the demo lab (their env file is only read).
set -euo pipefail
ENVF=/etc/candleague/candleague.env
DEMO=/etc/demobot/demobot.env
VENV=/opt/candleague/venv
APP=/opt/candleague/app
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
if [ ! -f "$ENVF" ] || [ ! -x "$VENV/bin/python" ] || [ ! -d "$APP/candleague" ]; then
  echo "먼저 설치하세요: sudo bash $HERE/install_candleague.sh"; exit 1
fi

get() {   # get KEY FILE: the value without surrounding quotes ("" when missing)
  local v
  v="$(grep -E "^$1=" "$2" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}
put() {   # put KEY VALUE: replace (or add) the KEY line; the value travels in the environment, never on a command line
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
  chown root:candleague "$ENVF"
  chmod 640 "$ENVF"
}

if [ "${1:-}" != "--new-password" ]; then
  echo "== 1. 텔레그램"
  if [ -n "$(get CANDLEAGUE_TG_TOKEN "$ENVF")" ] && [ -n "$(get CANDLEAGUE_TG_CHAT "$ENVF")" ]; then
    echo "이미 채워져 있습니다 (그대로 둡니다)"
  elif [ -n "$(get DEMOBOT_TG_TOKEN "$DEMO")" ] && [ -n "$(get DEMOBOT_TG_CHAT "$DEMO")" ]; then
    put CANDLEAGUE_TG_TOKEN "$(get DEMOBOT_TG_TOKEN "$DEMO")"
    put CANDLEAGUE_TG_CHAT "$(get DEMOBOT_TG_CHAT "$DEMO")"
    echo "데모 랩 봇의 토큰과 받는 사람을 이 서버 안에서 옮겨 넣었습니다 (값은 화면에 나오지 않습니다)."
    echo "후보 리그 메시지는 같은 대화방에 [후보 리그]로 시작해서 옵니다."
  else
    echo "데모 랩 봇 설정을 찾지 못했습니다. 텔레그램 없이도 리그와 대시보드는 돕니다."
    echo "나중에 넣으려면: SUDO_EDITOR=nano sudoedit $ENVF  (CANDLEAGUE_TG_TOKEN, CANDLEAGUE_TG_CHAT)"
  fi

  echo "== 2. 대시보드 주소 (Tailscale)"
  HOST="$(get CANDLEAGUE_DASH_HOST "$ENVF")"
  if [ -z "$HOST" ]; then
    HOST="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
    [ -n "$HOST" ] || HOST="$(get DEMOBOT_DASH_HOST "$DEMO")"
    if [ -n "$HOST" ]; then
      put CANDLEAGUE_DASH_HOST "$HOST"
      echo "주소 $HOST"
    else
      echo "Tailscale 주소를 찾지 못했습니다 (tailscale ip -4 가 비어 있음). Tailscale을 켠 뒤 다시 실행하세요."
    fi
  else
    echo "주소 $HOST (그대로)"
  fi

  echo "== 3. 대시보드 비밀값"
  S="$(get CANDLEAGUE_DASH_SECRET "$ENVF")"
  if [ "${#S}" -ge 32 ]; then
    echo "이미 있습니다 (그대로)"
  else
    put CANDLEAGUE_DASH_SECRET "$("$VENV/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
    echo "새로 만들었습니다 (화면에 나오지 않습니다)"
  fi
fi

echo "== 4. 대시보드 비밀번호"
H="$(get CANDLEAGUE_DASH_PASSWORD_HASH "$ENVF")"
if [[ "$H" == pbkdf2\$* ]] && [ "${1:-}" != "--new-password" ]; then
  echo "이미 있습니다 (바꾸려면: sudo bash $0 --new-password)"
else
  echo "대시보드에 들어갈 때 쓸 비밀번호를 두 번 입력하세요 (화면에 보이지 않는 게 정상, 채팅에 쓰지 마세요)."
  H="$(cd "$APP" && "$VENV/bin/python" -B -m candleague.dash hash)" || H=""
  if [[ "$H" != pbkdf2\$* ]]; then echo "비밀번호를 정하지 못했습니다. 같은 명령을 다시 실행하세요."; exit 1; fi
  put CANDLEAGUE_DASH_PASSWORD_HASH "$H"
  echo "저장했습니다 (해시로만)"
fi

echo "== 5. 방화벽 (Tailscale에만, 인터넷에는 열지 않음)"
bash "$HERE/firewall.sh" || echo "방화벽 점검이 실패했습니다 (다른 것은 영향 없음): sudo bash $HERE/firewall.sh"

echo "== 6. 다시 켜기 (후보 리그 서비스만)"
systemctl enable --quiet candleague-dash.service
systemctl restart candleague-dash.service || echo "대시보드를 켜지 못했습니다: journalctl -u candleague-dash -n 40 --no-pager"
if systemctl is-enabled --quiet candleague-live.service 2>/dev/null; then
  systemctl restart candleague-live.service || echo "엔진을 다시 켜지 못했습니다: journalctl -u candleague-live -n 40 --no-pager"
fi
PORT="$(get CANDLEAGUE_DASH_PORT "$ENVF")"
echo "대시보드: http://$(get CANDLEAGUE_DASH_HOST "$ENVF"):${PORT:-8091}  (Tailscale을 켠 PC·휴대폰에서)"
echo "끝."
