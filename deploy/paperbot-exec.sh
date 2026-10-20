#!/bin/sh
# Run a testnet drill or an executor command by hand with the keys of /etc/paperbot/executor.env
# (root-only file), as the executor's own user paperbot-exec (never paperbot: the agents and the dashboard run as
# paperbot and could read the keys from /proc/<pid>/environ of a paperbot process), in the same sandbox as
# paperbot-executor.service.
#
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh testnet drill --symbol BTCUSDT --side long
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh bybit drill --symbol BTCUSDT --side long   (Bybit testnet)
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mexc drill          (MEXC mainnet: reads + settings only)
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mexc drill --confirm-order REAL_ORDER   (+ one tiny order)
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh wooxpro drill --confirm-order REAL_ORDER  (WOO X Pro, owners 10-20)
#
# Only the modules paperbot.testnet, paperbot.executor, paperbot.bybit, paperbot.mexc and paperbot.wooxpro can be run
# this way.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi
if ! id paperbot-exec >/dev/null 2>&1 || [ "$(id -u paperbot-exec)" = "$(id -u paperbot)" ]; then
  echo "user paperbot-exec is missing: run sudo bash deploy/install.sh first"; exit 1
fi
mod=${1:-}
case "$mod" in
  testnet|executor) shift ;;
  bybit|mexc|wooxpro) shift ;;
  *) echo "usage: $0 testnet|executor|bybit|mexc|wooxpro <command> [options]"; exit 1 ;;
esac
if [ -t 0 ]; then io=--pty; else io=--pipe; fi
exec systemd-run --quiet --wait --collect $io --uid=paperbot-exec --gid=paperbot \
  -p WorkingDirectory=/opt/crypto-bot-research -p EnvironmentFile=/etc/paperbot/executor.env -p UMask=0027 \
  -p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectSystem=strict -p ProtectHome=yes \
  -p ReadWritePaths=/var/lib/paperbot/exec -p "InaccessiblePaths=-/etc/paperbot/agents.env -/etc/paperbot/dash.env" \
  -p LimitCORE=0 \
  /opt/paperbot/venv/bin/python -m "paperbot.$mod" "$@"
