#!/bin/bash
# usage: dl.sh <outname> <sha256> <url>   -> downloads into sweep/data/raw and verifies sha256
set -e
RAW=/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/raw
out="$RAW/$1"; exp="$2"; url="$3"
curl -sS --fail -o "$out" "$url"
got=$(sha256sum "$out" | cut -d' ' -f1)
if [ "$got" != "$exp" ]; then echo "SHA MISMATCH $1 got=$got exp=$exp"; exit 2; fi
echo "$1 $got OK rows=$(($(wc -l < "$out")-1)) first=$(sed -n 2p "$out" | cut -d, -f1) last=$(tail -1 "$out" | cut -d, -f1)"
echo "$1 $got" >> "$RAW/sha256_verified.txt"
