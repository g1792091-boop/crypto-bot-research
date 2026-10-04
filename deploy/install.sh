#!/usr/bin/env bash
# Paper v3 server setup on a fresh Ubuntu 24.04 (docs/server-setup-v3.md).
#
#   sudo bash deploy/install.sh            # run from the cloned repository
#
# Does: system packages, firewall (SSH only), user "paperbot" and the order executor's own user "paperbot-exec",
# Python venv, directories, env-file templates (root:paperbot 640; executor.env root:root 600), systemd units
# (installed, NOT started).
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
# A new server runs cloud-init and its first automatic updates for a few minutes: wait for them
# instead of failing on "Could not get lock".
command -v cloud-init >/dev/null && cloud-init status --wait >/dev/null 2>&1 || true
n=0
until apt-get -o DPkg::Lock::Timeout=60 update -q; do
  n=$((n+1)); [ "$n" -ge 60 ] && { echo "apt is still busy after 10 minutes; run this script again later"; exit 1; }
  echo "apt is busy (automatic updates); waiting 10 s ($n/60)"; sleep 10
done
DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -yq python3 python3-venv python3-pip \
  git sqlite3 ufw fail2ban unattended-upgrades chrony zstd openssl psmisc nodejs

echo "== firewall: SSH in, everything else closed"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
systemctl enable --now fail2ban chrony

echo "== user and directories"
id paperbot >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/paperbot --shell /usr/sbin/nologin paperbot
# The order executor and the testnet drill run as their own user, never as paperbot: the agent rooms, the
# dashboard and the other services run as paperbot, and a process can read /proc/<pid>/environ (the order keys
# systemd passes in) of a process of its own user only (docs/live-safety.md 1-9). Primary group paperbot: it reads
# the code, paper3.db and executor.json, and the nightly backup (paperbot) reads its databases.
id paperbot-exec >/dev/null 2>&1 || useradd --system --gid paperbot --no-create-home --home-dir /var/lib/paperbot/exec \
  --shell /usr/sbin/nologin paperbot-exec
[ "$(id -gn paperbot-exec)" = paperbot ] || usermod --gid paperbot paperbot-exec
if [ "$(id -u paperbot-exec)" = "$(id -u paperbot)" ] || [ "$(id -u paperbot-exec)" = 0 ]; then
  echo "user paperbot-exec must be its own user (not paperbot, not root): sudo userdel paperbot-exec, then run this again"
  exit 1
fi
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot /var/backups/paperbot
# 5-year test caches for the agent rooms (python -m paperbot.agents.labdata build --out /var/lib/paperbot/lab;
# same build as the research, checked file by file against paperbot/agents/labdata_reference.json)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/lab
# the order executor's databases (testnet and, later, mainnet): its user's only writable folder. Group paperbot
# reads them (the nightly backup) but cannot change them; the agents and the dashboard cannot see the folder at all.
# Files left by an earlier install (when the executor still ran as paperbot) move to paperbot-exec.
install -d -o paperbot-exec -g paperbot -m 750 /var/lib/paperbot/exec
chown -R paperbot-exec:paperbot /var/lib/paperbot/exec
chmod -R u+rwX,g+rX,g-w,o-rwx /var/lib/paperbot/exec
# A database the earlier code left in WAL format (it never switched back on a clean stop) has no -wal/-shm once the
# executor stopped, and the nightly backup (paperbot: may read this folder, no longer write it) cannot open such a
# file read-only ("attempt to write a readonly database"). While the executor is off, its own user switches each one
# back to rollback mode; the current code does that itself on every clean stop. A running executor keeps its
# -wal/-shm, which the backup can read.
if ! systemctl is-active --quiet paperbot-executor 2>/dev/null; then
  for db in /var/lib/paperbot/exec/*.db; do
    [ -f "$db" ] || continue
    runuser -u paperbot-exec -- sqlite3 "$db" 'PRAGMA journal_mode=DELETE;' >/dev/null \
      || echo "could not switch $db to rollback mode: the nightly backup may fail to read it until the executor was started and stopped once"
  done
fi
# GH Coin call recorder output (docs/ghcoin-recorder.md)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/ghcoin
# the failure alert's one-a-day stamps (deploy/paperbot-failed@.service)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/failalert
# the weekly checkpoint rehearsal's files and its own bar cache (deploy/paperbot-rehearsal.service)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/rehearsal
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
# `python -m paperbot...` works from any folder (the services also run with WorkingDirectory=$APP)
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "$APP" > "$SITE/paperbot-app.pth"

echo "== code"
# Copy to a staging folder first, then swap while the services are stopped, so a
# running bot never reads a half-copied tree. The previous code stays in $APP.old.
# The agents timer is paused too, so no agent pass starts on a half-copied tree.
UNITS="paperbot-live3 paperbot-dash paperbot-liq paperbot-ghcoin paperbot-tgtrades paperbot-agents.timer"
RUNNING=""
if [ "$REPO_DIR" != "$APP" ]; then
  # Scheduled jobs (nightly check, backups, checkpoint, monthly re-check) are not stopped for the swap:
  # wait for a running one to finish so it never reads a half-swapped tree.
  JOBS="paperbot-daily3.service paperbot-backup.service paperbot-checkpoint.service paperbot-labmonthly.service \
paperbot-offsite.service paperbot-rehearsal.service"
  n=0
  # A oneshot job reports "activating" (not "active") while it runs, so is-active alone never waits for it.
  while busy="$(for j in $JOBS; do case "$(systemctl show -p ActiveState --value "$j" 2>/dev/null)" in
                  active|activating|deactivating|reloading) echo "$j" ;; esac; done)"; [ -n "$busy" ]; do
    n=$((n+1)); [ "$n" -ge 120 ] && { echo "still running after 60 min: $busy; run this script again later"; exit 1; }
    echo "waiting for a scheduled job to finish: $busy ($n/120)"; sleep 30
  done
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
  # A pass already running (up to 100 min) loads prompts and modules as it goes: end it before the
  # swap so it never mixes two versions or finds the tree missing. It is not restarted: the next timer
  # pass fails its interrupted meeting and tries it once more.
  if systemctl is-active --quiet paperbot-agents.service 2>/dev/null; then
    systemctl stop paperbot-agents.service
  fi
  rm -rf "$APP.old"
  [ -d "$APP" ] && mv "$APP" "$APP.old"
  mv "$APP.new" "$APP"
fi

echo "== GH Coin code for the call recorder (pinned commit, read-only copy in /opt/ghcoin)"
# Only the four files the recorder imports, from the commit in deploy/ghcoin.commit of the branch
# claude/eloquent-johnson-nnt7gh. A failed fetch only skips the recorder (launchcheck reports it).
GHC="$(tr -d '[:space:]' < "$APP/deploy/ghcoin.commit" 2>/dev/null || true)"
if [ -n "$GHC" ] && { git -C "$REPO_DIR" cat-file -e "$GHC^{commit}" 2>/dev/null \
     || git -C "$REPO_DIR" fetch -q origin claude/eloquent-johnson-nnt7gh; } \
   && git -C "$REPO_DIR" cat-file -e "$GHC^{commit}" 2>/dev/null; then
  rm -rf /opt/ghcoin.new && mkdir -p /opt/ghcoin.new
  git -C "$REPO_DIR" archive "$GHC" gh-coin/combo.js gh-coin/lib/patterns.js gh-coin/lib/ta_rating.js \
    nuri-ai/terminal/ind.js | tar -x -C /opt/ghcoin.new
  echo '{"type": "module"}' > /opt/ghcoin.new/package.json
  echo "$GHC" > /opt/ghcoin.new/COMMIT
  chown -R root:paperbot /opt/ghcoin.new && chmod -R g+rX,o-rwx /opt/ghcoin.new
  rm -rf /opt/ghcoin && mv /opt/ghcoin.new /opt/ghcoin
  echo "GH Coin $GHC"
else
  echo "GH Coin commit ${GHC:-?} not available: the call recorder (paperbot-ghcoin) will not start"
fi

echo "== env files (empty templates; fill them on the server only)"
for f in live dash agents; do
  if [ ! -f /etc/paperbot/$f.env ] && [ -f "$APP/deploy/$f.env.example" ]; then
    install -o root -g paperbot -m 640 "$APP/deploy/$f.env.example" /etc/paperbot/$f.env
  fi
  [ -f /etc/paperbot/$f.env ] && chmod 640 /etc/paperbot/$f.env && chown root:paperbot /etc/paperbot/$f.env
done
# The executor's order keys: root only. systemd reads the file for paperbot-executor.service (and the drill wrapper
# deploy/paperbot-exec.sh) before it drops to the paperbot-exec user; the agents and the dashboard cannot open the
# file, and as another user (paperbot) they cannot read the keys from the executor's /proc/<pid>/environ either.
if [ ! -f /etc/paperbot/executor.env ] && [ -f "$APP/deploy/executor.env.example" ]; then
  install -o root -g root -m 600 "$APP/deploy/executor.env.example" /etc/paperbot/executor.env
fi
[ -f /etc/paperbot/executor.env ] && chmod 600 /etc/paperbot/executor.env && chown root:root /etc/paperbot/executor.env

echo "== systemd units (installed, not started)"
for u in paperbot-live3.service paperbot-dash.service paperbot-daily3.service paperbot-daily3.timer \
         paperbot-backup.service paperbot-backup.timer paperbot-agents.service paperbot-agents.timer \
         paperbot-liq.service paperbot-labmonthly.service paperbot-labmonthly.timer \
         paperbot-checkpoint.service paperbot-checkpoint.timer paperbot-offsite.service paperbot-offsite.timer \
         paperbot-rehearsal.service paperbot-rehearsal.timer \
         paperbot-failed@.service paperbot-ghcoin.service paperbot-tgtrades.service paperbot-executor.service; do
  install -m 644 "$APP/deploy/$u" /etc/systemd/system/$u
done
systemctl daemon-reload
# The order executor is installed only: never enabled, started or restarted here (docs/live-safety.md).
if systemctl is-active --quiet paperbot-executor 2>/dev/null; then
  echo "paperbot-executor is running the previous code; restart it yourself when ready:"
  echo "  sudo systemctl restart paperbot-executor"
fi
# New timers are installed, never enabled here (docs/server-setup-v3.md 11 and 13-5 name the one-time command).
if ! systemctl is-enabled --quiet paperbot-rehearsal.timer 2>/dev/null; then
  echo "weekly checkpoint rehearsal installed but off; to turn it on once: sudo systemctl enable --now paperbot-rehearsal.timer"
fi
if [ -n "$RUNNING" ]; then
  systemctl start $RUNNING
  echo "restarted:$RUNNING (the bot resumes from its saved state; the start is logged in the runs table)"
fi

cat <<'NEXT'

Done. A first install starts nothing. Continue with docs/server-setup-v3.md (step 4 on): keys and Telegram in
/etc/paperbot/*.env on the server only (never in chat), dashboard, Tailscale, agent login, lab data.
Then check before the start, and again 10-15 minutes after it:
  cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage before
  cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
The order executor (paperbot-executor) is installed but stays off (docs/live-safety.md).
NEXT
