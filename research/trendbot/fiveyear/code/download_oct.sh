#!/bin/bash
# Binance USD-M 1m klines, daily 2026-10-01..2026-10-20, 6 coins (only for the 7/1-10/20 signal agreement check and the
# replay cross-check against the earlier 89-entry run). Each archive in its own folder; .CHECKSUM verified (sha256).
set -u
BASE=/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/fiveyear/octdata
get() {
  local url=$1 name=$2 dir=$BASE/$2
  if [ -f "$dir/$name.zip" ] && [ -f "$dir/ok" ]; then return 0; fi
  rm -rf "$dir"; mkdir -p "$dir"
  curl -sS --retry 3 -o "$dir/$name.zip" "$url" || { echo "FAIL $name"; return 1; }
  curl -sS --retry 3 -o "$dir/$name.zip.CHECKSUM" "$url.CHECKSUM" || { echo "FAIL checksum $name"; return 1; }
  want=$(awk '{print $1}' "$dir/$name.zip.CHECKSUM"); got=$(sha256sum "$dir/$name.zip" | awk '{print $1}')
  if [ "$want" != "$got" ]; then echo "BADSUM $name"; return 1; fi
  touch "$dir/ok"
}
for c in BTCUSDT ETHUSDT SOLUSDT DOGEUSDT LTCUSDT BCHUSDT; do
  for d in $(seq -w 1 20); do
    n=$c-1m-2026-10-$d
    get https://data.binance.vision/data/futures/um/daily/klines/$c/1m/$n.zip $n &
  done
  wait
  echo "done $c"
done
