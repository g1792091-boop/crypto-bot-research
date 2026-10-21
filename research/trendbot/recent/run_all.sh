#!/bin/bash
# All variants of RESULTS_KO.md, then the report. Usage: bash run_all.sh ROOT
# Needs ROOT/cache (download.sh + parse.py). Inputs kept here: signals.csv.gz = the member signals of the 10-21 replay
# (signals.py, 5,055 rows); config_1021_replay.json = the config that replay ran with (deploy/combo.trend.json at
# faf63c7: time_bars 4, no us_open_pre_min). A1..B2 read the repo's deploy/combo.trend.json (b270569: no TIME exit,
# Nasdaq 22:00~23:00 KST).
set -eu
ROOT=${1:?ROOT}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$ROOT/out"
SIM="python3 -I $HERE/sim.py $ROOT"
SIG="--signals $HERE/signals.csv.gz"
$SIM A0 $SIG --config "$HERE/config_1021_replay.json" > "$ROOT/out/A0.log" 2>&1 &
$SIM A1 $SIG > "$ROOT/out/A1.log" 2>&1 &
$SIM A2 $SIG --time-bars 4 > "$ROOT/out/A2.log" 2>&1 &
$SIM A3 $SIG --entry now > "$ROOT/out/A3.log" 2>&1 &
wait
$SIM A4 $SIG --vote-min 4 > "$ROOT/out/A4.log" 2>&1 &
$SIM B1 $SIG --entry limit > "$ROOT/out/B1.log" 2>&1 &
$SIM B2 $SIG --entry limit --lock-maker > "$ROOT/out/B2.log" 2>&1 &
wait
python3 -I "$HERE/report.py" "$ROOT" "$HERE" A0 A1 A2 A3 A4 B1 B2
