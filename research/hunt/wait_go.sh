#!/usr/bin/env bash
# Wait on the compute server until the developer publishes the pinned commit, then run bootstrap.sh at that commit.
#
# Owners 2026-10-11 23:14 KST: they create the server and paste one line before they sleep; the pin comes later.
# The developer pushes research/hunt/GO_COMMIT (one line: the full 40-hex commit of the pin) to the branch. This script
# polls the branch every 2 minutes, and when that file names a commit that is on the branch it checks the commit out and
# runs bootstrap.sh with HUNT_GO set to it (the same safety checks as the hand-pasted line: bootstrap stops if the code
# is not that commit, if the pins do not match, or if the data differ). ALTPUMP=0: the alt pump study already ran and
# its run-once guard would refuse a second run.
#
# Run it from a copy outside the clone (the checkout replaces the clone's files while this script runs):
#   cp /root/hunt/crypto-bot-research/research/hunt/wait_go.sh /root/hunt/wait_go.sh && bash /root/hunt/wait_go.sh
#
# WAIT_HOURS (default 14): give up after this long with a message; the server then sits idle until Destroy.

set -u
REPO=${HUNT_REPO:-/root/hunt/crypto-bot-research}
BR=${HUNT_BRANCH:-claude/keen-pasteur-wav02u}
MARK=research/hunt/GO_COMMIT
POLL=${WAIT_POLL:-120}
deadline=$(( $(date +%s) + ${WAIT_HOURS:-14} * 3600 ))

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
    echo "${WAIT_HOURS:-14}시간 동안 고정된 커밋이 오지 않았습니다. 개발자에게 이 화면을 보내 주세요 (서버는 Destroy해도 잃는 것 없음)."
    exit 1
  fi
  echo "$(date -u +%H:%M) UTC 아직 고정 전입니다. 기다리는 중..."
  sleep "$POLL"
done

echo "고정된 커밋 ${c:0:10} 이 왔습니다. 계산을 시작합니다."
git -C "$REPO" checkout -q "$c" || { echo "그 커밋으로 바꾸지 못했습니다: $c (이 화면을 개발자에게 보내 주세요)"; exit 1; }
HUNT_GO=$c ALTPUMP=0 exec bash "$REPO/research/hunt/bootstrap.sh"
