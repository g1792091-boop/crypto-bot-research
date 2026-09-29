#!/bin/bash
# usage: dl2.sh <outname> <sha256> <expid> <fname> <amzdate> <sig> ; tries each saved credential template
D=/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/tools
for t in $D/url_tpl*.txt; do
  url=$(sed -e "s/EXPID/$3/" -e "s/FNAME/$4/g" -e "s/AMZDATE/$5/" -e "s/SIG/$6/" $t | tr -d '\n')
  if $D/dl.sh "$1" "$2" "$url" 2>/dev/null; then exit 0; fi
done
echo "FAILED all templates for $1"; exit 1
