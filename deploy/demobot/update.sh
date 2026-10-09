#!/usr/bin/env bash
# Demo lab bot update. First get the new code in the clone (the owner does this):
#   cd /root/demobot-src && git pull && sudo bash deploy/demobot/update.sh
# Copies the code paths again (the previous copy stays in /opt/demobot/app.old), refreshes the units and the venv,
# and restarts only the demo lab's units that were running (a unit that was off stays off). Same script as the
# install (install_demobot.sh --update), so the env file and the database are kept as they are.
set -euo pipefail
exec bash "$(cd "$(dirname "$0")" && pwd)/install_demobot.sh" --update
