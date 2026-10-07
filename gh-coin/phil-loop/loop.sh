#!/usr/bin/env bash
# GH Coin 자기개선 루프 실행기 (Git Bash · macOS · Linux) — Windows PowerShell 은 loop.ps1 을 쓰세요.
#   사용법: ./loop.sh [사이클 수=1] [간격 분=60]
#   안전: 실거래 옵션은 없습니다. 루프는 strategy/ · journal/ 만 고칠 수 있고, 보호 파일을 고치면 되돌립니다.
set -uo pipefail
cd "$(dirname "$0")"
LOCK=".loop.pid"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then echo "이미 실행 중(pid $(cat "$LOCK"))" >&2; exit 1; fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT
CYCLES="${1:-1}"; SLEEP_MIN="${2:-60}"
PROTECTED=(core/ CYCLE.md CLAUDE.md loop.ps1 loop.sh .gitignore)
for i in $(seq 1 "$CYCLES"); do
  echo "=== 사이클 $i/$CYCLES $(date -u +%FT%TZ) ==="
  claude -p "$(cat CYCLE.md)" --permission-mode acceptEdits \
    --allowedTools "Read" "Glob" "Grep" "Edit" "Write" "Bash(node core/score.mjs*)" "Bash(node core/apply.mjs*)" \
      "Bash(git add:*)" "Bash(git commit:*)" "Bash(git log:*)" "Bash(git diff:*)" "Bash(git status:*)" "Bash(git rev-parse:*)" \
    || echo "사이클 $i 실패 — 다음으로"
  if ! git diff --quiet HEAD -- "${PROTECTED[@]}"; then echo "경고: 보호 파일 변경 — 되돌림" >&2; git checkout -- "${PROTECTED[@]}"; fi
  if git log --oneline -3 --name-only | grep -qE '^(core/|CYCLE\.md|CLAUDE\.md|loop\.ps1|loop\.sh|\.gitignore)'; then echo "경고: 최근 커밋에 보호 파일 변경 — 직접 확인(git log -3 --stat)" >&2; fi
  echo "--- 채점 ---"; node core/score.mjs | head -3
  [ "$i" -lt "$CYCLES" ] && sleep $((SLEEP_MIN * 60))
done
