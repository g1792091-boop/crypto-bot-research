#!/usr/bin/env bash
# GH Quant 서버 업데이트 — 새 코드를 받고 다시 시작 (설정 · 기록은 그대로)
#   sudo bash /opt/gh-quant/deploy/update.sh
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/gh-quant}"
RUN_USER="$(stat -c %U "$APP_DIR")"
[ "$(id -u)" -eq 0 ] || { echo "sudo 로 실행하세요"; exit 1; }
chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR"
g() { sudo -u "$RUN_USER" git -C "$APP_DIR" "$@"; }
BRANCH="${BRANCH:-$(g rev-parse --abbrev-ref HEAD)}"
g fetch -q origin "$BRANCH"
g checkout -q -B "$BRANCH" "origin/$BRANCH"
grep -v '^pytest' "$APP_DIR/backend/requirements.txt" > /tmp/gh-quant-req.txt
sudo -u "$RUN_USER" "$APP_DIR/venv/bin/pip" install -q -r /tmp/gh-quant-req.txt
systemctl restart gh-quant
sleep 3
systemctl is-active -q gh-quant && echo "업데이트 끝: $(g log --oneline -1)" || journalctl -u gh-quant -n 30 --no-pager
