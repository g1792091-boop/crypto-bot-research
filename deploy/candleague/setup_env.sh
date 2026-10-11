#!/usr/bin/env bash
# 후보 리그 (candidate league) settings in one go, after install_candleague.sh (docs/candleague-ko.md "설치"):
#
#   sudo bash deploy/candleague/setup_env.sh                  # Telegram, dashboard address / secret / password
#   sudo bash deploy/candleague/setup_env.sh --new-password   # only to change the dashboard password later
#   sudo bash deploy/candleague/setup_env.sh --own-telegram   # the league's own Telegram bot and chat (then as above)
#
# 1. Telegram: when the league has none yet, the demo lab bot's token and chats (/etc/demobot/demobot.env) are copied
#    in on this server (every league message starts with [후보 리그]); no new key, nothing pasted anywhere.
#    --own-telegram: a separate chat instead. The owners make a new bot with @BotFather, type its token here (hidden,
#    on this server only; never in a chat), press Start on the bot or add it to a group; the chats are found with the
#    new bot's getUpdates (the demo lab bot polls its own updates, so its token is never used for this), a test
#    message goes to each, and token + chats replace the league's Telegram settings.
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

tg_api() {   # tg_api METHOD [JSON_PARAMS]: the token travels in the environment (TK), never on a command line or screen
  M="$1" P="${2:-{\}}" "$VENV/bin/python" - <<'PY'
import json, os, sys, urllib.error, urllib.parse, urllib.request
tk, m, p = os.environ["TK"], os.environ["M"], json.loads(os.environ["P"])
data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in p.items()}).encode()
try:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{tk}/{m}", data, timeout=20) as r:
        print(r.read().decode())
except urllib.error.HTTPError as exc:          # str(exc) holds no URL, so the token never reaches the screen
    print(json.dumps({"ok": False, "error": f"HTTP {exc.code}"}))
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"ok": False, "error": type(exc).__name__}))
PY
}

own_telegram() {
  echo "== 1. 텔레그램 (후보 리그 전용 대화방)"
  echo "휴대폰 텔레그램에서 @BotFather → /newbot → 이름과 아이디(끝이 bot)를 정하면 토큰이 나옵니다."
  echo "그 토큰을 아래에 붙여 넣으세요. 화면에 안 보이는 게 정상입니다. 이 채팅 말고 다른 곳(채팅·메모)에는 붙이지 마세요."
  read -rs -p "새 봇 토큰: " TK; echo
  export TK
  local me
  me="$(tg_api getMe | "$VENV/bin/python" -c 'import json,sys; d=json.load(sys.stdin); print(d["result"]["username"] if d.get("ok") else "")')"
  if [ -z "$me" ]; then echo "토큰이 맞지 않습니다(텔레그램이 거절). 다시 실행하세요: sudo bash $0 --own-telegram"; unset TK; exit 1; fi
  echo "봇 확인: @$me"
  echo "이제 휴대폰에서 @$me 를 열고 '시작'(START)을 누르세요."
  echo "친구분도 받으려면: 친구분도 @$me 에서 '시작'을 누르거나, 두 분이 있는 그룹을 만들어 @$me 를 넣으세요."
  local ids="" tries=0 found
  while [ -z "$ids" ] && [ "$tries" -lt 3 ]; do
    read -r -p "다 했으면 엔터를 누르세요..." _
    tries=$((tries + 1))
    found="$(tg_api getUpdates '{"allowed_updates": ["message", "my_chat_member"]}' | "$VENV/bin/python" -c '
import json, sys
d = json.load(sys.stdin)
chats = {}
for u in d.get("result", []) if d.get("ok") else []:
    for k in ("message", "my_chat_member"):
        c = (u.get(k) or {}).get("chat")
        if c:
            chats[c["id"]] = c
names = []
for c in list(chats.values())[:4]:
    if c.get("type") == "private":
        names.append("개인 대화: " + (c.get("first_name") or "") + " " + (c.get("last_name") or ""))
    else:
        names.append("그룹: " + (c.get("title") or ""))
for i, n in enumerate(names, 1):
    print(f"  {i}. {n.strip()}", file=sys.stderr)
print(",".join(str(i) for i in list(chats)[:4]))
')"
    ids="$found"
    [ -n "$ids" ] || echo "아직 찾지 못했습니다. @$me 에서 '시작'을 눌렀는지(그룹이면 봇을 넣었는지) 확인하세요."
  done
  if [ -z "$ids" ]; then echo "대화방을 찾지 못해 바꾸지 않았습니다. 다시 실행하세요: sudo bash $0 --own-telegram"; unset TK; exit 1; fi
  read -r -p "위 대화방으로 후보 리그 알림을 받을까요? (y/n) " yn
  if [ "$yn" != "y" ] && [ "$yn" != "Y" ]; then echo "바꾸지 않았습니다."; unset TK; exit 1; fi
  local ok=0 chat
  IFS=',' read -ra arr <<< "$ids"
  for chat in "${arr[@]}"; do
    if tg_api sendMessage "{\"chat_id\": \"$chat\", \"text\": \"[후보 리그] 이 대화방으로 후보 리그 알림이 옵니다 (아침 9시 요약, 파산, 예상보다 아래, 멈춤). 종이 매매, 실제 돈 아님.\"}" \
        | grep -q '"ok": *true'; then ok=$((ok + 1)); fi
  done
  put CANDLEAGUE_TG_TOKEN "$TK"
  put CANDLEAGUE_TG_CHAT "$ids"
  unset TK
  echo "저장했습니다 (값은 화면에 나오지 않습니다). 시험 메시지 ${ok}/${#arr[@]}개 보냄 - 텔레그램을 확인하세요."
}

if [ "${1:-}" = "--own-telegram" ]; then
  own_telegram
fi

if [ "${1:-}" != "--new-password" ]; then
  [ "${1:-}" = "--own-telegram" ] || echo "== 1. 텔레그램"
  if [ "${1:-}" = "--own-telegram" ]; then
    :
  elif [ -n "$(get CANDLEAGUE_TG_TOKEN "$ENVF")" ] && [ -n "$(get CANDLEAGUE_TG_CHAT "$ENVF")" ]; then
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
