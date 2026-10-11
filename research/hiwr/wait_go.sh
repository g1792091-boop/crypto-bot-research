#!/usr/bin/env bash
# Wait on the track 2 compute server until the developer publishes the pinned commit, then run bootstrap.sh at it.
#
# The owners create a new server only after the hunt server is Destroyed (Q15), paste one line from SERVER_KO.md and may
# leave. The developer pushes research/hiwr/GO_COMMIT (one line: the full 40-hex commit of the pin) to the branch. This
# script polls the branch every 2 minutes; when that file names a commit that is on the branch, it checks the commit out
# and runs bootstrap.sh with HIWR_GO set to it (the same safety checks as a hand-pasted line: bootstrap stops if the code
# is not that commit, if the pins do not match, or if the data differ). If GO_COMMIT is already there, it starts at once.
#
# Run it from a copy outside the clone (the checkout replaces the clone's files while this script runs):
#   cp /root/hiwr/crypto-bot-research/research/hiwr/wait_go.sh /root/hiwr/wait_go.sh && bash /root/hiwr/wait_go.sh
#
# WAIT_HOURS (default 12): give up after this long with a message; the server then sits idle until Destroy.
# Rehearsal: HIWR_REPO (a scratch clone), HIWR_BRANCH, WAIT_POLL (seconds), WAIT_HOURS, HIWR_WAIT_EXEC (a command run in
# place of bootstrap.sh; it gets HIWR_GO in its environment).

set -u
REPO=${HIWR_REPO:-/root/hiwr/crypto-bot-research}
BR=${HIWR_BRANCH:-claude/keen-pasteur-wav02u}
MARK=research/hiwr/GO_COMMIT
POLL=${WAIT_POLL:-120}
deadline=$(( $(date +%s) + ${WAIT_HOURS:-12} * 3600 ))

case "$REPO" in
  /root/hunt|/root/hunt/*) echo "2번 트랙은 추세 사냥 폴더(/root/hunt)를 쓰지 않습니다: $REPO"; exit 1 ;;
esac
if [ -z "${HIWR_WAIT_EXEC:-}" ] && [ -d /root/hunt ]; then
  echo "이 서버에는 추세 사냥 폴더(/root/hunt)가 있습니다. 2번 트랙은 추세 사냥 서버를 Destroy한 뒤 새 서버에서 돌립니다."
  echo "이 화면을 개발자에게 보내 주세요."
  exit 1
fi
[ -d "$REPO/.git" ] || { echo "코드 폴더가 없습니다: $REPO (SERVER_KO의 한 줄을 그대로 붙여 넣으세요)"; exit 1; }
echo "고정된 커밋을 기다립니다. 2분마다 확인합니다. 이 창은 닫아도 됩니다 (Ctrl+B 다음 D)."
c=""
while :; do
  if git -C "$REPO" fetch -q origin "$BR" 2>/dev/null; then
    c=$(git -C "$REPO" show "origin/$BR:$MARK" 2>/dev/null | tr -d '[:space:]')
    if [[ $c =~ ^[0-9a-f]{40}$ ]] && git -C "$REPO" cat-file -e "$c^{commit}" 2>/dev/null \
        && git -C "$REPO" merge-base --is-ancestor "$c" "origin/$BR"; then
      break
    fi
  else
    echo "$(date -u +%H:%M) UTC 인터넷 확인 실패, 잠시 뒤 다시 시도합니다"
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "${WAIT_HOURS:-12}시간 동안 고정된 커밋이 오지 않았습니다. 개발자에게 이 화면을 보내 주세요 (서버는 Destroy해도 잃는 것 없음)."
    exit 1
  fi
  echo "$(date -u +%H:%M) UTC 아직 고정 전입니다. 기다리는 중..."
  sleep "$POLL"
done

echo "고정된 커밋 ${c:0:10} 이 왔습니다. 계산을 시작합니다."
git -C "$REPO" checkout -q "$c" || { echo "그 커밋으로 바꾸지 못했습니다: $c (이 화면을 개발자에게 보내 주세요)"; exit 1; }
if [ -n "${HIWR_WAIT_EXEC:-}" ]; then
  export HIWR_GO=$c
  read -r -a EX <<<"$HIWR_WAIT_EXEC"
  exec "${EX[@]}"
fi
HIWR_GO=$c exec bash "$REPO/research/hiwr/bootstrap.sh"
