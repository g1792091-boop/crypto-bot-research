#!/usr/bin/env bash
# 추세 사냥 dashboard and the firewall (called by install_huntbot.sh and setup_env.sh; safe to run again).
# Only when ufw is on and HUNTBOT_DASH_HOST is this server's Tailscale address (100.64.0.0/10): if ufw already allows
# everything on tailscale0, nothing changes; otherwise the dashboard port is allowed on tailscale0 only (never the
# internet). The dashboard listens on the Tailscale address only, so it is never reachable from the internet anyway.
set -euo pipefail
ENVF=/etc/huntbot/huntbot.env
if [ "$(id -u)" -ne 0 ]; then echo "sudo로 실행하세요: sudo bash $0"; exit 1; fi
val() { grep -E "^$1=" "$ENVF" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "\"' " || true; }
HOST="$(val HUNTBOT_DASH_HOST)"
PORT="$(val HUNTBOT_DASH_PORT)"; PORT="${PORT:-8092}"
if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then echo "firewall: HUNTBOT_DASH_PORT is not a number: nothing changed."; exit 0; fi
if ! command -v ufw >/dev/null 2>&1 || ! ufw status 2>/dev/null | grep -q '^Status: active'; then
  echo "firewall: ufw is not active: nothing changed (the dashboard listens on the Tailscale address only)."; exit 0
fi
if ! [[ "$HOST" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
  echo "firewall: the dashboard does not listen on a Tailscale address (${HOST:-not set}): nothing changed."; exit 0
fi
RULES="$(ufw status 2>/dev/null)"
if printf '%s\n' "$RULES" | grep -Eq '^Anywhere on tailscale0[[:space:]]+ALLOW'; then
  echo "firewall: ufw already allows tailscale0; port $PORT is reachable over Tailscale. Nothing changed."
elif printf '%s\n' "$RULES" | grep -Eq "^$PORT/tcp on tailscale0[[:space:]]+ALLOW"; then
  echo "firewall: $PORT/tcp on tailscale0 already allowed. Nothing changed."
else
  ufw allow in on tailscale0 to any port "$PORT" proto tcp comment 'huntbot dashboard' >/dev/null
  echo "firewall: allowed $PORT/tcp on tailscale0 only (Tailscale devices, not the internet)."
fi
