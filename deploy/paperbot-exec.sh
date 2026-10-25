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
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh flipster drill --confirm-order REAL_ORDER  (Flipster, owners 10-23)
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh deepcoin drill --confirm-order REAL_ORDER  (DeepCoin, owners 10-24)
#
# --keys wooxpro2 first: the keys of /etc/paperbot/executor-wooxpro2.env INSTEAD (the second WOO X Pro account, owners
# 10-24, docs/friend-bot-ko.md; its unit paperbot-executor-wooxpro2 loads that file instead of executor.env):
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh --keys wooxpro2 wooxpro check
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh --keys wooxpro2 wooxpro drill --confirm-order REAL_ORDER
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh --keys wooxpro2 executor preflight --config /etc/paperbot/executor-wooxpro2.json
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh --keys wooxpro2 mixchop check --config /etc/paperbot/mixchop.json
#   ('믹스 30분 봇', owners 10-25, docs/mixchop-ko.md: reads only)
#
# Only the modules paperbot.testnet, paperbot.executor, paperbot.bybit, paperbot.mexc, paperbot.wooxpro,
# paperbot.flipster, paperbot.deepcoin and paperbot.mixchop can be run this way.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi
if ! id paperbot-exec >/dev/null 2>&1 || [ "$(id -u paperbot-exec)" = "$(id -u paperbot)" ]; then
  echo "user paperbot-exec is missing: run sudo bash deploy/install.sh first"; exit 1
fi
keys=EnvironmentFile=/etc/paperbot/executor.env
hide=""
if [ "${1:-}" = "--keys" ]; then
  case "${2:-}" in
    wooxpro2) keys=EnvironmentFile=/etc/paperbot/executor-wooxpro2.env; hide=" -/etc/paperbot/executor.env"; shift 2 ;;
    *) echo "usage: $0 [--keys wooxpro2] testnet|executor|bybit|mexc|wooxpro|flipster|deepcoin|mixchop <command> [options]"; exit 1 ;;
  esac
  if [ ! -f "${keys#EnvironmentFile=}" ]; then
    echo "${keys#EnvironmentFile=} is missing: run sudo bash deploy/install.sh first (docs/friend-bot-ko.md)"; exit 1
  fi
fi
mod=${1:-}
case "$mod" in
  testnet|executor) shift ;;
  bybit|mexc|wooxpro|flipster) shift ;;
  deepcoin) shift ;;
  mixchop) shift ;;
  *) echo "usage: $0 testnet|executor|bybit|mexc|wooxpro|flipster|deepcoin|mixchop <command> [options]"; exit 1 ;;
esac
if [ -t 0 ]; then io=--pty; else io=--pipe; fi
exec systemd-run --quiet --wait --collect $io --uid=paperbot-exec --gid=paperbot \
  -p WorkingDirectory=/opt/crypto-bot-research -p "$keys" -p UMask=0027 \
  -p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectSystem=strict -p ProtectHome=yes \
  -p ReadWritePaths=/var/lib/paperbot/exec -p "InaccessiblePaths=-/etc/paperbot/agents.env -/etc/paperbot/dash.env$hide" \
  -p LimitCORE=0 \
  /opt/paperbot/venv/bin/python -m "paperbot.$mod" "$@"
