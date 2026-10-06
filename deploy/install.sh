#!/usr/bin/env bash
# Paper v3 server setup on a fresh Ubuntu 24.04 (docs/server-setup-v3.md).
#
#   sudo bash deploy/install.sh            # run from the cloned repository
#
# Does: system packages, firewall (SSH only), user "paperbot" and the order executor's own user "paperbot-exec",
# Python venv, directories, env-file templates (root:paperbot 640; executor.env root:root 600), systemd units
# (installed, NOT started).
# The 24-hour debate room (paperbot-debate: paid Anthropic API, docs/debate-room.md) is installed, never enabled or
# started here, and it is not among the services this script stops for the code swap.
# Does not: put any key or password anywhere, start trading, or open the dashboard to
# the internet. Safe to run again: to update, `git pull` then run it again. It refuses
# uncommitted changes, stops the running services only for the swap, and keeps the
# previous code in /opt/crypto-bot-research.old for a rollback.
# PAPERBOT_RESETTING=1 (set by deploy/paperbot-reset.sh for the v4 restart, docs/server-setup-v4.md): the Obsidian
# export, the DeepSeek-200 shadow test and the DeepSeek nightly recompute check are installed as usual but their timers
# are NOT switched on here (the reset stops them and checks the new run first); the script prints each one's real
# state (systemctl is-enabled / is-active: a timer enabled before stays enabled here, the reset decides) and points to
# docs/server-setup-v4.md for which to turn on after the reset checks. Without the variable everything is as before.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/crypto-bot-research
VENV=/opt/paperbot/venv

if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi

# Armed just before the services are stopped for the code swap (below) and cleared once they are started again: a
# failure in between (an error, Ctrl+C, a dropped SSH session) puts the previous code back if the swap was cut in half
# and starts again the units this script stopped, so a failed install never leaves the bot down.
restart_stopped() {
  rc=$?
  trap '' HUP INT TERM
  trap - EXIT
  [ "$rc" -eq 0 ] && return 0
  set +e
  if [ ! -d "$APP" ] && [ -d "$APP.old" ]; then
    mv "$APP.old" "$APP" && echo "put the previous code back in $APP"
  fi
  if [ -n "${RUNNING:-}" ]; then
    if systemctl start $RUNNING; then
      echo "install.sh stopped early (exit $rc); started again:$RUNNING. Send this screen to the developer before running it again."
    else
      echo "install.sh stopped early (exit $rc) and could not start again:$RUNNING -> sudo systemctl start$RUNNING"
    fi
  fi
}

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
# The 24-hour debate room's own user (docs/debate-room.md): primary group paperbot-debate, extra group paperbot, so it can
# READ the bot's databases, and /etc/paperbot/debate.env (root:paperbot-debate 640, below) is readable by it alone: user
# paperbot (agents, dashboard, live runner) is not in that group and never sees the paid API key.
getent group paperbot-debate >/dev/null || groupadd --system paperbot-debate
id paperbot-debate >/dev/null 2>&1 || useradd --system --gid paperbot-debate --groups paperbot --no-create-home \
  --home-dir /var/lib/paperbot/debate --shell /usr/sbin/nologin paperbot-debate
id -nG paperbot-debate | tr ' ' '\n' | grep -qx paperbot || usermod -a -G paperbot paperbot-debate
if [ "$(id -u paperbot-debate)" = "$(id -u paperbot)" ] || [ "$(id -u paperbot-debate)" = 0 ]; then
  echo "user paperbot-debate must be its own user (not paperbot, not root): sudo userdel paperbot-debate, then run this again"
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
# the debate room's only writable folder (debate.db): owner paperbot-debate, group paperbot reads it (the dashboard,
# user paperbot, shows it read-only; setgid keeps new files in group paperbot). Nothing else writes here.
install -d -o paperbot-debate -g paperbot -m 2750 /var/lib/paperbot/debate
chown -R paperbot-debate:paperbot /var/lib/paperbot/debate
chmod -R u+rwX,g+rX,g-w,o-rwx /var/lib/paperbot/debate
# GH Coin call recorder output (docs/ghcoin-recorder.md)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/ghcoin
# nightly Obsidian vault export (docs/obsidian-vault.md): the only folder that job writes
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/obsidian
# the failure alert's one-a-day stamps (deploy/paperbot-failed@.service)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/failalert
# the weekly checkpoint rehearsal's files and its own bar cache (deploy/paperbot-rehearsal.service)
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/rehearsal
# the DeepSeek-200 forward shadow test's database (docs: research/deepseek200/FORWARD_TEST_PLAN.md): the only folder that job writes
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/shadow200
# the DeepSeek nightly recompute check (paperbot/dscheck.py): its bar cache and its one-line summary for the 09:20 report;
# the only folder that job writes
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/dscheck
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
paperbot-offsite.service paperbot-rehearsal.service paperbot-obsidian.service paperbot-shadow200.service \
paperbot-dscheck.service"
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
  trap restart_stopped EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
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
# The debate room's paid API key: root:paperbot-debate 640 (never paperbot's group). Created from the template only when
# missing, with the two Telegram lines copied from agents.env (same bot and chat); an existing file is never overwritten
# and no value is printed. The key itself is typed by the owners with sudoedit (docs/debate-room.md).
if [ ! -f /etc/paperbot/debate.env ] && [ -f "$APP/deploy/debate.env.example" ]; then
  install -o root -g paperbot-debate -m 640 "$APP/deploy/debate.env.example" /etc/paperbot/debate.env
  if [ -f /etc/paperbot/agents.env ]; then
    for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_CRITICAL; do
      line="$(grep -E "^${k}=." /etc/paperbot/agents.env | tail -n 1 || true)"
      if [ -n "$line" ]; then
        sed -i "/^${k}=/d" /etc/paperbot/debate.env
        printf '%s\n' "$line" >> /etc/paperbot/debate.env
      fi
    done
    unset line
  fi
fi
[ -f /etc/paperbot/debate.env ] && chmod 640 /etc/paperbot/debate.env && chown root:paperbot-debate /etc/paperbot/debate.env
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
         paperbot-rehearsal.service paperbot-rehearsal.timer paperbot-obsidian.service paperbot-obsidian.timer \
         paperbot-shadow200.service paperbot-shadow200.timer \
         paperbot-dscheck.service paperbot-dscheck.timer \
         paperbot-failed@.service paperbot-debate.service \
         paperbot-ghcoin.service paperbot-tgtrades.service paperbot-executor.service; do
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
if [ "${PAPERBOT_RESETTING:-0}" = "1" ]; then
  # Called by the v4 reset (deploy/paperbot-reset.sh): it stopped these timers and checks the new run first. Installed
  # above, NOT switched on here (no enable, no start); a timer that is still enabled from before is left as it is and
  # the reset decides (it keeps the Obsidian export and the DeepSeek check off). Each one's REAL state is printed.
  echo "리셋 중: 아래 타이머는 설치만 했고 여기서 켜거나 끄지 않았습니다(지금 실제 상태):"
  for t in paperbot-obsidian.timer paperbot-shadow200.timer paperbot-dscheck.timer; do
    en="$(systemctl is-enabled "$t" 2>/dev/null || true)"
    ac="$(systemctl is-active "$t" 2>/dev/null || true)"
    echo "  $t: 자동 시작 ${en:-알 수 없음}, 지금 ${ac:-알 수 없음}"
  done
  echo "  어느 것을 언제 켤지: docs/server-setup-v4.md 5단계(리셋 뒤 점검 launchcheck --stage after를 마친 뒤)"
else
  # The Obsidian export is read-only and free (no key, no network, no order): its nightly timer is switched on here.
  systemctl enable --now paperbot-obsidian.timer >/dev/null 2>&1 || echo "obsidian timer could not be enabled: sudo systemctl enable --now paperbot-obsidian.timer"
  # The DeepSeek-200 shadow test is record-only (public bars, no key, no order, no account, its own database): its timer is switched on here.
  systemctl enable --now paperbot-shadow200.timer >/dev/null 2>&1 || echo "shadow200 timer could not be enabled: sudo systemctl enable --now paperbot-shadow200.timer"
  # The DeepSeek nightly recompute check is read-only (paper3.db opened read-only, public bars, no key, no order, no
  # Telegram of its own; a failure warns through paperbot-failed@): its timer is switched on here.
  systemctl enable --now paperbot-dscheck.timer >/dev/null 2>&1 || echo "dscheck timer could not be enabled: sudo systemctl enable --now paperbot-dscheck.timer"
fi
# The debate room is installed only: never enabled, started or restarted here (it spends the owners' own API money).
if systemctl is-active --quiet paperbot-debate 2>/dev/null; then
  echo "paperbot-debate is running the previous code; restart it yourself when ready:"
  echo "  sudo systemctl restart paperbot-debate"
elif ! systemctl is-enabled --quiet paperbot-debate 2>/dev/null; then
  echo "24-hour debate room installed but off (paid API); to set it up and turn it on: docs/debate-room.md"
fi
if [ -n "$RUNNING" ]; then
  systemctl start $RUNNING
  echo "restarted:$RUNNING (the bot resumes from its saved state; the start is logged in the runs table)"
fi
trap - EXIT HUP INT TERM

cat <<'NEXT'

Done. A first install starts nothing. Continue with docs/server-setup-v3.md (step 4 on): keys and Telegram in
/etc/paperbot/*.env on the server only (never in chat), dashboard, Tailscale, agent login, lab data.
Then check before the start, and again 10-15 minutes after it:
  cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage before
  cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
The order executor (paperbot-executor) is installed but stays off (docs/live-safety.md).
NEXT
