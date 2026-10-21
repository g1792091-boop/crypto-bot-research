#!/bin/bash
# Download Binance USD-M futures 1m klines for the 6 coins: monthly 2026-05..2026-09, daily 2026-10-01..2026-10-20
# (the replay needs 300 closed 4h bars before 2026-06-28 for the trend judge, and 7 days of 1h for the chase block).
# Each archive goes into its own new folder under $ROOT/data/; its .CHECKSUM is verified (sha256).
# Usage: bash download.sh ROOT [MONTHS]   (ROOT: a scratch folder; parse.py reads ROOT/data and writes ROOT/cache)
#   MONTHS default "05 06 07 08 09" (sim.py); signals.py needs "02 03 04 05 06 07 08 09"
set -u
ROOT=${1:?ROOT}
MONTHS=${2:-"05 06 07 08 09"}
BASE=$ROOT/data
COINS="BTCUSDT ETHUSDT SOLUSDT DOGEUSDT LTCUSDT BCHUSDT"
get() {  # url name
  local url=$1 name=$2 dir=$BASE/$2
  if [ -f "$dir/$name.zip" ] && [ -f "$dir/ok" ]; then return 0; fi
  rm -rf "$dir"; mkdir -p "$dir"
  curl -sS --retry 3 -o "$dir/$name.zip" "$url" || { echo "FAIL $name"; return 1; }
  curl -sS --retry 3 -o "$dir/$name.zip.CHECKSUM" "$url.CHECKSUM" || { echo "FAIL checksum $name"; return 1; }
  want=$(awk '{print $1}' "$dir/$name.zip.CHECKSUM"); got=$(sha256sum "$dir/$name.zip" | awk '{print $1}')
  if [ "$want" != "$got" ]; then echo "BADSUM $name"; return 1; fi
  touch "$dir/ok"
}
for c in $COINS; do
  for m in $MONTHS; do
    n=$c-1m-2026-$m
    get https://data.binance.vision/data/futures/um/monthly/klines/$c/1m/$n.zip $n &
  done
  wait
  for d in $(seq -w 1 20); do
    n=$c-1m-2026-10-$d
    get https://data.binance.vision/data/futures/um/daily/klines/$c/1m/$n.zip $n &
  done
  wait
  echo "done $c"
done
