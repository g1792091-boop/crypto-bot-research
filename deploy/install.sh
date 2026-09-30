#!/usr/bin/env bash
# Paper v3 server setup on a fresh Ubuntu 24.04 (docs/server-setup-v3.md).
#
#   sudo bash deploy/install.sh            # run from the cloned repository
#
# Does: system packages, firewall (SSH only), user "paperbot", Python venv,
# directories, env-file templates (chmod 600), systemd units (installed, NOT started).
# Does not: put any key or password anywhere, start trading, or open the dashboard to
# the internet. Safe to run again: to update, `git pull` then run it again. It refuses
# uncommitted changes, stops the running services only for the swap, and keeps the
# previous code in /opt/crypto-bot-research.old for a rollback.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/crypto-bot-research
VENV=/opt/paperbot/venv

if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi

echo "== packages"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -yq python3 python3-venv python3-pip git sqlite3 ufw \
  fail2ban unattended-upgrades chrony

echo "== firewall: SSH in, everything else closed"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
systemctl enable --now fail2ban chrony

echo "== user and directories"
id paperbot >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/paperbot --shell /usr/sbin/nologin paperbot
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot /var/backups/paperbot
# 5-year test caches for the agent rooms (python -m paperbot.agents.labdata build --out /var/lib/paperbot/lab)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/lab
install -d -o root -g paperbot -m 750 /etc/paperbot

echo "== code version"
# Every start of the bot records this commit in the runs table (paperbot/runinfo.py).
COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
TAG="$(git -C "$REPO_DIR" describe --tags --exact-match 2>/dev/null || true)"
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  if [ "${ALLOW_DIRTY:-0}" != "1" ]; then
    echo "the repository has uncommitted changes; deploy only committed code (or ALLOW_DIRTY=1)"; exit 1
  fi
  DIRTY=true
else
  DIRTY=false
fi
echo "commit $COMMIT ${TAG:+(tag $TAG)} dirty=$DIRTY"

echo "== python"
install -d -m 755 /opt/paperbot
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

echo "== code"
# Copy to a staging folder first, then swap while the services are stopped, so a
# running bot never reads a half-copied tree. The previous code stays in $APP.old.
# The agents timer is paused too, so no agent pass starts on a half-copied tree.
UNITS="paperbot-live3 paperbot-dash paperbot-agents.timer"
RUNNING=""
if [ "$REPO_DIR" != "$APP" ]; then
  rm -rf "$APP.new"
  cp -a "$REPO_DIR" "$APP.new"
  printf '{"commit": "%s", "tag": %s, "dirty": %s, "source": "install.sh", "installed_at": "%s"}\n' \
    "$COMMIT" "$( [ -n "$TAG" ] && echo "\"$TAG\"" || echo null )" "$DIRTY" "$(date -u +%FT%TZ)" \
    > "$APP.new/VERSION.json"
  chown -R root:paperbot "$APP.new"
  chmod -R g+rX,o-rwx "$APP.new"
  for u in $UNITS; do
    systemctl is-active --quiet "$u" 2>/dev/null && RUNNING="$RUNNING $u"
  done
  [ -n "$RUNNING" ] && systemctl stop $RUNNING
  rm -rf "$APP.old"
  [ -d "$APP" ] && mv "$APP" "$APP.old"
  mv "$APP.new" "$APP"
fi

echo "== env files (empty templates; fill them on the server only)"
for f in live dash agents; do
  if [ ! -f /etc/paperbot/$f.env ] && [ -f "$APP/deploy/$f.env.example" ]; then
    install -o root -g paperbot -m 640 "$APP/deploy/$f.env.example" /etc/paperbot/$f.env
  fi
  [ -f /etc/paperbot/$f.env ] && chmod 640 /etc/paperbot/$f.env && chown root:paperbot /etc/paperbot/$f.env
done

echo "== systemd units (installed, not started)"
for u in paperbot-live3.service paperbot-dash.service paperbot-daily3.service paperbot-daily3.timer \
         paperbot-backup.service paperbot-backup.timer paperbot-agents.service paperbot-agents.timer; do
  install -m 644 "$APP/deploy/$u" /etc/systemd/system/$u
done
systemctl daemon-reload
if [ -n "$RUNNING" ]; then
  systemctl start $RUNNING
  echo "restarted:$RUNNING (the bot resumes from its saved state; the start is logged in the runs table)"
fi

cat <<'NEXT'

Done. Next (docs/server-setup-v3.md):
  1. sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live check     # Binance reachable?
  2. edit /etc/paperbot/live.env   (read-only Binance key, Telegram)  -- on the server, never in chat
  3. edit /etc/paperbot/dash.env   (python -m paperbot.dash hash; openssl rand -hex 32)
  4. sudo systemctl enable --now paperbot-live3 paperbot-dash paperbot-daily3.timer paperbot-backup.timer
  5. agent rooms (optional, docs/agent-rooms.md): install Claude Code for the paperbot user, fill
     /etc/paperbot/agents.env, try one pass with --dry-run, then
     sudo systemctl enable --now paperbot-agents.timer
NEXT
