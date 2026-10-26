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
    systemctl is-active --quiet paperbot-executor-mexc 2>/dev/null && continue   # the MEXC executor runs: leave them
    systemctl is-active --quiet paperbot-executor-deepcoin 2>/dev/null && continue   # the DeepCoin executor runs: leave them
    systemctl is-active --quiet paperbot-executor-wooxpro2 2>/dev/null && continue   # the WOO X Pro 2 executor runs: leave them
    systemctl is-active --quiet paperbot-executor-toobit 2>/dev/null && continue   # the Toobit executor runs: leave them
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
# the custom-value shadow (paperbot/paramshadow.py): its bar cache, engine states, shadow trades and the summary the
# dashboard and the specialists read; the only folder that job writes
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/paramshadow
# the combined bot (paperbot/combo.py, docs/combo-bot-ko.md): its own paper database, the only folder it writes. 755 so
# the order executor (paperbot-exec, group paperbot) can read combo.db when it follows the combined account
install -d -o paperbot -g paperbot -m 755 /var/lib/paperbot/combo
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
UNITS="paperbot-live3 paperbot-dash paperbot-livedash paperbot-liq paperbot-ghcoin paperbot-tgtrades paperbot-agents.timer paperbot-combo paperbot-combo2 paperbot-combo-mexc paperbot-combo-vwap"
# the '친구 매매법' paper bot (owners 10-24): a running one is stopped and started again the same way
UNITS="$UNITS paperbot-combo-friend"
# the '숏5 하락장' paper bot (owners 10-25): a running one is stopped and started again the same way
UNITS="$UNITS paperbot-combo-short5"
# the '레인지 봇' paper bot (owners 10-26): a running one is stopped and started again the same way
UNITS="$UNITS paperbot-combo-range"
RUNNING=""
if [ "$REPO_DIR" != "$APP" ]; then
  # Scheduled jobs (nightly check, backups, checkpoint, monthly re-check) are not stopped for the swap:
  # wait for a running one to finish so it never reads a half-swapped tree.
  JOBS="paperbot-daily3.service paperbot-backup.service paperbot-checkpoint.service paperbot-labmonthly.service \
paperbot-offsite.service paperbot-rehearsal.service paperbot-obsidian.service paperbot-shadow200.service \
paperbot-dscheck.service paperbot-paramshadow.service"
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
# The fourth executor's own key file (WOO X Pro 2, owners 10-24, docs/friend-bot-ko.md): root only too, its template
# with every value empty (nothing secret is written here), so the owners' sudoedit fills a root-only file instead of
# creating one with an editor's default permissions. Its unit loads it INSTEAD of executor.env.
if [ ! -f /etc/paperbot/executor-wooxpro2.env ] && [ -f "$APP/deploy/executor-wooxpro2.env.example" ]; then
  install -o root -g root -m 600 "$APP/deploy/executor-wooxpro2.env.example" /etc/paperbot/executor-wooxpro2.env
fi
[ -f /etc/paperbot/executor-wooxpro2.env ] && chmod 600 /etc/paperbot/executor-wooxpro2.env && chown root:root /etc/paperbot/executor-wooxpro2.env
# The Toobit executor's own key file (owners 10-25, docs/toobit-ko.md): root only too, its template with every value empty
# (nothing secret is written here), so the owners' sudoedit fills a root-only file. Its unit loads it INSTEAD of executor.env.
if [ ! -f /etc/paperbot/executor-toobit.env ] && [ -f "$APP/deploy/executor-toobit.env.example" ]; then
  install -o root -g root -m 600 "$APP/deploy/executor-toobit.env.example" /etc/paperbot/executor-toobit.env
fi
[ -f /etc/paperbot/executor-toobit.env ] && chmod 600 /etc/paperbot/executor-toobit.env && chown root:root /etc/paperbot/executor-toobit.env

echo "== systemd units (installed, not started)"
for u in paperbot-live3.service paperbot-dash.service paperbot-livedash.service paperbot-daily3.service paperbot-daily3.timer \
         paperbot-backup.service paperbot-backup.timer paperbot-agents.service paperbot-agents.timer \
         paperbot-liq.service paperbot-labmonthly.service paperbot-labmonthly.timer \
         paperbot-checkpoint.service paperbot-checkpoint.timer paperbot-offsite.service paperbot-offsite.timer \
         paperbot-rehearsal.service paperbot-rehearsal.timer paperbot-obsidian.service paperbot-obsidian.timer \
         paperbot-shadow200.service paperbot-shadow200.timer \
         paperbot-dscheck.service paperbot-dscheck.timer \
         paperbot-paramshadow.service paperbot-paramshadow.timer \
         paperbot-failed@.service paperbot-debate.service \
         paperbot-ghcoin.service paperbot-tgtrades.service paperbot-combo.service paperbot-executor.service; do
  install -m 644 "$APP/deploy/$u" /etc/systemd/system/$u
done
# the second combined bot (its own config combo2.json and paper database: two bots of different types side by side,
# docs/live1019-start-ko.md): installed only, started by a person
install -m 644 "$APP/deploy/paperbot-combo2.service" /etc/systemd/system/paperbot-combo2.service
# the second LIVE paper bot (규칙봇 15 at -35%, its own config combo-mexc.json and database live15-mexc.db; the MEXC
# executor follows it, docs/live15-mexc-ko.md): installed only, started by a person. A running one is stopped for
# the code swap and started again like paperbot-combo (UNITS above).
install -m 644 "$APP/deploy/paperbot-combo-mexc.service" /etc/systemd/system/paperbot-combo-mexc.service
# the 'VWAP 개선판' paper bot (owners 10-23, its own config combo-vwap.json and database vwap.db; ONE live executor follows
# it once its config names vwap.db, docs/vwap-bot-ko.md): installed only, started by a person. A running one is stopped
# for the code swap and started again like paperbot-combo (UNITS above).
install -m 644 "$APP/deploy/paperbot-combo-vwap.service" /etc/systemd/system/paperbot-combo-vwap.service
# the '친구 매매법' paper bot (owners 10-24, its own config combo-friend.json and database friend.db; the second
# WOO X Pro executor follows it, docs/friend-bot-ko.md): installed only, started by a person. A running one is
# stopped for the code swap and started again like paperbot-combo (UNITS above).
install -m 644 "$APP/deploy/paperbot-combo-friend.service" /etc/systemd/system/paperbot-combo-friend.service
# the '숏5 하락장' paper bot (owners 10-25, its own config combo-short5.json and database short5.db; ONE live executor
# follows it once its config names short5.db, docs/short5-bot-ko.md): installed only, started by a person. A running one
# is stopped for the code swap and started again like paperbot-combo (UNITS above).
install -m 644 "$APP/deploy/paperbot-combo-short5.service" /etc/systemd/system/paperbot-combo-short5.service
# the '레인지 봇' paper bot (owners 10-26, its own config combo-range.json and database range.db; the WOO X Pro executor
# follows it once its config names range.db, docs/range-bot-ko.md): installed only, started by a person. A running one
# is stopped for the code swap and started again like paperbot-combo (UNITS above).
install -m 644 "$APP/deploy/paperbot-combo-range.service" /etc/systemd/system/paperbot-combo-range.service
# the shadow paper bots (그림자 페이퍼 봇, docs/live1019-start-ko.md): one template, one instance per
# deploy/combo.shadow-<name>.json; paper only, no Telegram, below the live paper bot. Installed only: never enabled,
# started or stopped here (not among the units stopped for the code swap). A running shadow keeps the previous code
# until a person restarts it, after the live paper bot runs again (the shadows then start one at a time).
install -m 644 "$APP/deploy/paperbot-combo-shadow@.service" "/etc/systemd/system/paperbot-combo-shadow@.service"
SHADOWS="$(systemctl list-units --plain --no-legend --state=active 'paperbot-combo-shadow@*.service' 2>/dev/null \
  | awk '{print $1}' | tr '\n' ' ' || true)"
if [ -n "${SHADOWS// /}" ]; then
  echo "그림자 페이퍼 봇이 이전 코드로 돌고 있습니다. 실제 페이퍼 봇이 다시 돈 뒤 다시 켜세요:"
  echo "  sudo systemctl restart ${SHADOWS% }"
fi
# the second executor (MEXC, its own config executor-mexc.json): installed only, never enabled or started here
install -m 644 "$APP/deploy/paperbot-executor-mexc.service" /etc/systemd/system/paperbot-executor-mexc.service
# the third executor (DeepCoin, owners 10-24, docs/deepcoin-ko.md: it follows the 'VWAP 개선판'): installed only, never
# enabled or started here. Like the other two executors' configs, /etc/paperbot/executor-deepcoin.json is never written
# here: the owners copy deploy/executor.live-deepcoin.json there themselves (the guide), so the live site, the checks and
# the messages keep showing two executors until they do.
install -m 644 "$APP/deploy/paperbot-executor-deepcoin.service" /etc/systemd/system/paperbot-executor-deepcoin.service
# the fourth executor (WOO X Pro 2, owners 10-24, docs/friend-bot-ko.md: a second WOO X Pro account follows the paper bot
# '친구 매매법'): installed only, never enabled or started here; /etc/paperbot/executor-wooxpro2.json is never written here
# (the owners copy deploy/executor.live-wooxpro2.json), so the site, the checks and the messages stay as they are until then.
install -m 644 "$APP/deploy/paperbot-executor-wooxpro2.service" /etc/systemd/system/paperbot-executor-wooxpro2.service
# the Toobit executor (owners 10-25, docs/toobit-ko.md: a $50 executor that will follow the rule bot's V3.9 1-hour paper
# account): installed only, never enabled or started here; /etc/paperbot/executor-toobit.json is never written here (the
# owners copy deploy/executor.live-toobit.json once the paper account and its exits are decided).
install -m 644 "$APP/deploy/paperbot-executor-toobit.service" /etc/systemd/system/paperbot-executor-toobit.service
# '믹스 30분 봇' (owners 10-25 night, docs/mixchop-ko.md): the second WOO X Pro account trades the 30m signal itself
# (paperbot/mixchop.py, keys from executor-wooxpro2.env; Conflicts= stops paperbot-executor-wooxpro2 when it starts), and
# its paper twin (no keys, no orders). Installed only, never enabled or started here; /etc/paperbot/mixchop.json and
# mixchop-paper.json are never written here (the owners copy deploy/mixchop.live.json / mixchop.paper.json).
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/mixchop-paper
install -m 644 "$APP/deploy/paperbot-mixchop.service" /etc/systemd/system/paperbot-mixchop.service
install -m 644 "$APP/deploy/paperbot-mixchop-paper.service" /etc/systemd/system/paperbot-mixchop-paper.service
# Until 10-24 this slot was Flipster's (paperbot-executor-flipster, installed by install.sh from 10-23, never started:
# its API opens only on request, so the owners switched to DeepCoin). Its unit file goes only while that unit is inactive
# and not enabled; a running or enabled one is left as it is (a person decides).
OLD_THIRD=/etc/systemd/system/paperbot-executor-flipster.service
if [ -f "$OLD_THIRD" ]; then
  if [ "$(systemctl is-active paperbot-executor-flipster 2>/dev/null || true)" = inactive ] && ! systemctl is-enabled --quiet paperbot-executor-flipster 2>/dev/null; then
    rm -f "$OLD_THIRD"
    echo "removed the unused paperbot-executor-flipster unit (never started; the third executor is paperbot-executor-deepcoin)"
  else
    echo "paperbot-executor-flipster was started or is enabled: left as it is (the third executor is paperbot-executor-deepcoin now)"
  fi
fi
systemctl daemon-reload
# The order executor is installed only: never enabled, started or restarted here (docs/live-safety.md).
if systemctl is-active --quiet paperbot-executor 2>/dev/null; then
  echo "paperbot-executor is running the previous code; restart it yourself when ready:"
  echo "  sudo systemctl restart paperbot-executor"
fi
if systemctl is-active --quiet paperbot-executor-mexc 2>/dev/null; then
  echo "paperbot-executor-mexc is running the previous code; restart it yourself when ready:"
  echo "  sudo systemctl restart paperbot-executor-mexc"
fi
if systemctl is-active --quiet paperbot-executor-deepcoin 2>/dev/null; then
  echo "paperbot-executor-deepcoin is running the previous code; restart it yourself when ready:"
  echo "  sudo systemctl restart paperbot-executor-deepcoin"
fi
if systemctl is-active --quiet paperbot-executor-wooxpro2 2>/dev/null; then
  echo "paperbot-executor-wooxpro2 is running the previous code; restart it yourself when ready:"
  echo "  sudo systemctl restart paperbot-executor-wooxpro2"
fi
if systemctl is-active --quiet paperbot-executor-toobit 2>/dev/null; then
  echo "paperbot-executor-toobit is running the previous code; restart it yourself when ready:"
  echo "  sudo systemctl restart paperbot-executor-toobit"
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
  # The custom-value shadow (커스텀값 그림자) is read-only (paper3.db opened read-only, public bars, no order, no account
  # change, no Telegram of its own; a failure warns through paperbot-failed@): its timer is switched on here.
  # Owners 10/21 night ("커스텀값봇 … 중지시켜도 괜찮지 않아?"): switched off with `systemctl mask --now
  # paperbot-paramshadow.timer` it stays off here (masked = the owners' choice; unmask to bring it back).
  if [ "$(systemctl is-enabled paperbot-paramshadow.timer 2>/dev/null)" = "masked" ]; then
    echo "커스텀값 그림자(paperbot-paramshadow)는 꺼 둔 상태(mask)라 켜지 않아요"
  else
    systemctl enable --now paperbot-paramshadow.timer >/dev/null 2>&1 || echo "paramshadow timer could not be enabled: sudo systemctl enable --now paperbot-paramshadow.timer"
  fi
fi
# 실거래 일일 점검 and 실시간 감시 (paperbot/livecheck.py; docs/live1019-start-ko.md "실거래 일일 점검과 알람"):
# read-only towards the paper bot and the executors (their databases opened read-only, executor.env never opened, no
# exchange account, no order); the morning check reads public Binance klines and sends one Telegram message at 09:10
# KST, the watcher (every minute) sends the live trades and a loud message once per new problem. Installed AND
# switched on here (their timers): with no executor running yet they only say what they see. Their real state is
# printed.
for u in paperbot-livecheck.service paperbot-livecheck.timer paperbot-livewatch.service paperbot-livewatch.timer; do
  install -m 644 "$APP/deploy/$u" /etc/systemd/system/$u
done
systemctl daemon-reload
for t in paperbot-livecheck.timer paperbot-livewatch.timer; do
  systemctl enable --now "$t" >/dev/null 2>&1 || echo "$t could not be enabled: sudo systemctl enable --now $t"
  echo "$t: 자동 시작 $(systemctl is-enabled "$t" 2>/dev/null || echo 알 수 없음), 지금 $(systemctl is-active "$t" 2>/dev/null || echo 알 수 없음)"
done
# The owners' private chats for the live messages (deploy/live-telegram.env.example): an owner makes the file; this
# script never creates it or touches its lines (an empty chat line would silence the live bots), only its permissions.
if [ -f /etc/paperbot/live-telegram.env ]; then
  chown root:paperbot /etc/paperbot/live-telegram.env && chmod 640 /etc/paperbot/live-telegram.env
fi
# 매매법 성적표와 개선 후보 장부 (paperbot/liveimprove.py; docs/live1019-start-ko.md 13): read-only towards the paper
# bot and the executors (their databases opened read-only, the executors' key file never opened, no exchange account,
# no order), one Telegram message every Monday at 09:30 KST, its own /var/lib/paperbot/liveimprove.db. It never changes
# a bot or a config (the owners decide). Installed AND switched on here (its timer). Its real state is printed.
for u in paperbot-liveimprove.service paperbot-liveimprove.timer; do
  install -m 644 "$APP/deploy/$u" /etc/systemd/system/$u
done
systemctl daemon-reload
systemctl enable --now paperbot-liveimprove.timer >/dev/null 2>&1 \
  || echo "paperbot-liveimprove.timer could not be enabled: sudo systemctl enable --now paperbot-liveimprove.timer"
echo "paperbot-liveimprove.timer: 자동 시작 $(systemctl is-enabled paperbot-liveimprove.timer 2>/dev/null || echo 알 수 없음), 지금 $(systemctl is-active paperbot-liveimprove.timer 2>/dev/null || echo 알 수 없음)"
# 실거래 분석 팀 (paperbot/liveteam.py; docs/live1019-start-ko.md 15): AI members on the owners' Claude plan, read-only
# towards the bots, no order. Installed OFF: never enabled or started here (it spends the owners' plan); the owners turn
# it on after about 20 live trades. Its real state is printed.
for u in paperbot-liveteam.service paperbot-liveteam.timer; do
  install -m 644 "$APP/deploy/$u" /etc/systemd/system/$u
done
systemctl daemon-reload
echo "paperbot-liveteam.timer (실거래 분석 팀): 자동 시작 $(systemctl is-enabled paperbot-liveteam.timer 2>/dev/null || echo 꺼짐), 지금 $(systemctl is-active paperbot-liveteam.timer 2>/dev/null || echo 꺼짐) · 켜기: sudo systemctl enable --now paperbot-liveteam.timer"
# 믹스 30분 봇 점검 (paperbot/mixcheck.py; docs/mixchop-ko.md 8장): the '믹스 30분 봇''s morning check (09:05 KST) and its
# loss cards (every 5 minutes): read-only towards the bot (its config, state file and log read as group paperbot; no
# exchange account, no key, no order), Telegram to the live bot's own chats, its own folder /var/lib/paperbot/mixcheck.
# Installed AND switched on here (their timers), like the live checks above. The bot itself (paperbot-mixchop) and its
# paper twin are never started, stopped or restarted here. Their real state is printed.
install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/mixcheck
for u in paperbot-mixcheck.service paperbot-mixcheck.timer paperbot-mixcheck-pass.service paperbot-mixcheck-pass.timer; do
  install -m 644 "$APP/deploy/$u" /etc/systemd/system/$u
done
systemctl daemon-reload
for t in paperbot-mixcheck.timer paperbot-mixcheck-pass.timer; do
  systemctl enable --now "$t" >/dev/null 2>&1 || echo "$t could not be enabled: sudo systemctl enable --now $t"
  echo "$t: 자동 시작 $(systemctl is-enabled "$t" 2>/dev/null || echo 알 수 없음), 지금 $(systemctl is-active "$t" 2>/dev/null || echo 알 수 없음)"
done
# The combined bot is installed only: started by a person after writing /etc/paperbot/combo.json (docs/combo-bot-ko.md).
if ! systemctl is-enabled --quiet paperbot-combo 2>/dev/null; then
  echo "합친 봇(paperbot-combo) 설치만 했습니다. 켜는 법: docs/combo-bot-ko.md"
fi
# The -35% paper bot for MEXC is installed only (docs/live15-mexc-ko.md): started by a person after writing
# /etc/paperbot/combo-mexc.json.
if ! systemctl is-enabled --quiet paperbot-combo-mexc 2>/dev/null; then
  echo "MEXC용 -35% 페이퍼 봇(paperbot-combo-mexc) 설치만 했습니다. 켜는 순서(MEXC 포지션이 없을 때): docs/live15-mexc-ko.md"
fi
# The 'VWAP 개선판' paper bot is installed only (docs/vwap-bot-ko.md): started by a person after writing
# /etc/paperbot/combo-vwap.json.
if ! systemctl is-enabled --quiet paperbot-combo-vwap 2>/dev/null; then
  echo "VWAP 개선판 페이퍼 봇(paperbot-combo-vwap) 설치만 했습니다. 켜는 순서: docs/vwap-bot-ko.md"
fi
# The '친구 매매법' paper bot is installed only (docs/friend-bot-ko.md): started by a person after writing
# /etc/paperbot/combo-friend.json.
if ! systemctl is-enabled --quiet paperbot-combo-friend 2>/dev/null; then
  echo "친구 매매법 페이퍼 봇(paperbot-combo-friend) 설치만 했습니다. 켜는 순서: docs/friend-bot-ko.md"
fi
# The '숏5 하락장' paper bot is installed only (docs/short5-bot-ko.md): started by a person after writing
# /etc/paperbot/combo-short5.json.
if ! systemctl is-enabled --quiet paperbot-combo-short5 2>/dev/null; then
  echo "숏5 하락장 페이퍼 봇(paperbot-combo-short5) 설치만 했습니다. 켜는 순서: docs/short5-bot-ko.md"
fi
# The '레인지 봇' paper bot is installed only (docs/range-bot-ko.md): started by a person after writing
# /etc/paperbot/combo-range.json.
if ! systemctl is-enabled --quiet paperbot-combo-range 2>/dev/null; then
  echo "레인지 봇 페이퍼 봇(paperbot-combo-range) 설치만 했습니다. 켜는 순서: docs/range-bot-ko.md"
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

# 실거래 대시보드 (paperbot-livedash, docs/livedash-ko.md; owners 10/19 "따로 실거래용 봇 대시보드 사이트"): read-only, the
# same password and DASH_HOST as the rule bot's dashboard (/etc/paperbot/dash.env), port 8093. Switched on here once the
# rule bot's dashboard is set up (paperbot-dash enabled: its password and DASH_HOST are in place), and (re)started with
# this code; otherwise installed only, with the one command. The firewall: Tailscale only, never the internet (the rule
# of deploy/candleague/firewall.sh: nothing to do when ufw already allows everything on tailscale0, else 8093/tcp on
# tailscale0 alone).
LIVEDASH_PORT=8093
if systemctl is-enabled --quiet paperbot-dash 2>/dev/null; then
  systemctl enable paperbot-livedash >/dev/null 2>&1 || echo "paperbot-livedash could not be enabled: sudo systemctl enable --now paperbot-livedash"
  systemctl restart paperbot-livedash || echo "paperbot-livedash did not start: sudo journalctl -u paperbot-livedash -n 50"
  DHOST="$(sed -n 's/^DASH_HOST=//p' /etc/paperbot/dash.env 2>/dev/null | tail -n 1 | tr -d "\"' " || true)"
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active' \
     && [[ "$DHOST" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    RULES="$(ufw status 2>/dev/null)"
    if printf '%s\n' "$RULES" | grep -Eq '^Anywhere on tailscale0[[:space:]]+ALLOW'; then
      echo "firewall: ufw already allows tailscale0 (as for 8080): 실거래 대시보드 $LIVEDASH_PORT is reachable over Tailscale too"
    elif printf '%s\n' "$RULES" | grep -Eq "^$LIVEDASH_PORT/tcp on tailscale0[[:space:]]+ALLOW"; then
      echo "firewall: $LIVEDASH_PORT/tcp on tailscale0 already allowed"
    else
      ufw allow in on tailscale0 to any port "$LIVEDASH_PORT" proto tcp comment 'paperbot livedash' >/dev/null
      echo "firewall: allowed $LIVEDASH_PORT/tcp on tailscale0 only (Tailscale devices, not the internet)"
    fi
  fi
  echo "실거래 대시보드(paperbot-livedash): 자동 시작 $(systemctl is-enabled paperbot-livedash 2>/dev/null || echo 알 수 없음), 지금 $(systemctl is-active paperbot-livedash 2>/dev/null || echo 알 수 없음) · 주소 http://${DHOST:-DASH_HOST}:$LIVEDASH_PORT"
else
  echo "실거래 대시보드(paperbot-livedash) 설치만 했습니다(규칙봇 대시보드가 아직 꺼져 있음). 켜기: sudo systemctl enable --now paperbot-livedash"
fi

cat <<'NEXT'

Done. A first install starts nothing. Continue with docs/server-setup-v3.md (step 4 on): keys and Telegram in
/etc/paperbot/*.env on the server only (never in chat), dashboard, Tailscale, agent login, lab data.
Then check before the start, and again 10-15 minutes after it:
  cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage before
  cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
The order executor (paperbot-executor) is installed but stays off (docs/live-safety.md).
NEXT
