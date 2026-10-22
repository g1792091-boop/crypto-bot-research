#!/bin/bash
# Binance USD-M public data for the days after the verified 1m grid (fg1m ends 2026-09-30 23:59): daily 1m klines and
# daily 1m mark-price klines, 6 coins, 2026-10-01 .. LAST (default 2026-10-21), plus the monthly funding file of
# 2026-10 when Binance has published it (it appears only after the month ends; no daily funding files exist).
# Each archive in its own new folder; .CHECKSUM verified (sha256) before the folder is marked ok. A day that is not
# published yet (404) is reported as MISSING and skipped: the data end is the last day all six coins have both files.
# Run: bash download.sh [LAST_DAY]      (LAST_DAY like 2026-10-21)
set -u
BASE=/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/newlive/data
LAST=${1:-2026-10-21}
get() {   # url kind name
  local url=$1 kind=$2 name=$3 dir=$BASE/$2/$3
  if [ -f "$dir/$name.zip" ] && [ -f "$dir/ok" ]; then return 0; fi
  rm -rf "$dir"; mkdir -p "$dir"
  code=$(curl -sS --retry 3 -o "$dir/$name.zip" -w "%{http_code}" "$url") || { echo "FAIL $kind $name"; rm -rf "$dir"; return 1; }
  if [ "$code" != "200" ]; then echo "MISSING($code) $kind $name"; rm -rf "$dir"; return 1; fi
  code=$(curl -sS --retry 3 -o "$dir/$name.zip.CHECKSUM" -w "%{http_code}" "$url.CHECKSUM") || { echo "FAIL checksum $kind $name"; rm -rf "$dir"; return 1; }
  if [ "$code" != "200" ]; then echo "MISSING checksum($code) $kind $name"; rm -rf "$dir"; return 1; fi
  want=$(awk '{print $1}' "$dir/$name.zip.CHECKSUM"); got=$(sha256sum "$dir/$name.zip" | awk '{print $1}')
  if [ "$want" != "$got" ]; then echo "BADSUM $kind $name"; rm -rf "$dir"; return 1; fi
  touch "$dir/ok"
}
U=https://data.binance.vision/data/futures/um
days=$(python3 -I -c "import sys,datetime as d; a=d.date(2026,10,1); b=d.date.fromisoformat(sys.argv[1]); print(' '.join(str(a+d.timedelta(i)) for i in range((b-a).days+1)))" "$LAST")
for c in BTCUSDT ETHUSDT SOLUSDT DOGEUSDT LTCUSDT BCHUSDT; do
  for day in $days; do
    n=$c-1m-$day
    get $U/daily/klines/$c/1m/$n.zip klines $n &
    get $U/daily/markPriceKlines/$c/1m/$n.zip mark $n &
  done
  wait
  get $U/monthly/fundingRate/$c/$c-fundingRate-2026-10.zip funding $c-fundingRate-2026-10
  echo "done $c"
done
