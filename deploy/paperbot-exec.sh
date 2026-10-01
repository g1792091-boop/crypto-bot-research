#!/bin/sh
# Run a testnet drill or an executor command by hand with the keys of /etc/paperbot/executor.env
# (root-only file), as the paperbot user, in the same sandbox as paperbot-executor.service.
#
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh testnet drill --symbol BTCUSDT --side long
#   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
#
# Only the modules paperbot.testnet and paperbot.executor can be run this way.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi
mod=${1:-}
case "$mod" in
  testnet|executor) shift ;;
  *) echo "usage: $0 testnet|executor <command> [options]"; exit 1 ;;
esac
if [ -t 0 ]; then io=--pty; else io=--pipe; fi
exec systemd-run --quiet --wait --collect $io --uid=paperbot --gid=paperbot \
  -p WorkingDirectory=/opt/crypto-bot-research -p EnvironmentFile=/etc/paperbot/executor.env \
  -p NoNewPrivileges=yes -p ProtectSystem=strict -p ReadWritePaths=/var/lib/paperbot \
  /opt/paperbot/venv/bin/python -m "paperbot.$mod" "$@"
