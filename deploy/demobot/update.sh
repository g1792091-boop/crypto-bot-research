#!/usr/bin/env bash
# Demo lab bot update. First get the new code in the clone (the owner does this):
#   cd /root/demobot-src && git pull && sudo bash deploy/demobot/update.sh
# Copies the code paths again (the previous copy stays in /opt/demobot/app.old), refreshes the units and the venv,
# and restarts only the demo lab's units that were running (a unit that was off stays off), so the engine and the
# dashboard run the new code. Units new in this version (round 3: the nightly backup and the outside watch timers) are
# installed and switched on when the engine is on; the env file gets empty lines for the new optional keys. Same
# script as the install (install_demobot.sh --update), so the env file's values and the database are kept as they are.
set -euo pipefail
exec bash "$(cd "$(dirname "$0")" && pwd)/install_demobot.sh" --update
