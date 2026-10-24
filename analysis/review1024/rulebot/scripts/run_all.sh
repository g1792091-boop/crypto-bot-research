#!/usr/bin/env bash
# Rebuild the whole rule-bot review from one export zip (analysis/live1019/rb_export.py output).
#
#   bash analysis/review1024/rulebot/scripts/run_all.sh <export.zip> <new_empty_work_dir> [out_dir]
#
# <new_empty_work_dir>: a NEW folder outside the repository (e.g. under the session scratchpad); the zip is extracted
#   into <work>/data (data files only, never executed) and the intermediate tables go to <work>/base etc.
# [out_dir]: where tables/, facts*.json, daily_pnl.csv and REPORT_KO.md are written
#   (default: analysis/review1024/rulebot next to this script).
# Runs with the system python3 (pandas, numpy) from this scripts folder; about 25-30 minutes on 4 CPUs
# (most of it the variant replays).
set -euo pipefail
ZIP="$1"
WORK="$2"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
OUT="${3:-$(cd "$HERE/.." && pwd)}"
PROCS="${PROCS:-4}"
if [ -e "$WORK" ] && [ -n "$(ls -A "$WORK" 2>/dev/null)" ]; then
  echo "refused: $WORK exists and is not empty"; exit 1
fi
mkdir -p "$WORK" "$OUT/tables"
cd "$HERE"
python3 extract_zip.py "$ZIP" "$WORK/data"
python3 "$REPO/analysis/rulebot_1007/scripts/fiveyear_ref.py" --repo "$REPO" --out "$WORK/fiveyear_ref.csv" > "$WORK/fiveyear_ref.log"
python3 "$REPO/analysis/rulebot_1007/scripts/analyze.py" "$WORK/data" "$WORK/base" --repo "$REPO" \
  --ref "$WORK/fiveyear_ref.csv" --procs "$PROCS" > "$WORK/base.log" 2>&1
python3 randpool.py "$WORK/data" - "$WORK/randpool.csv" --repo "$REPO" --procs "$PROCS" > "$WORK/randpool.log" 2>&1
python3 varpool.py "$WORK/data" "$WORK/randpool.csv" synth "$WORK/varpool_synth.csv" --repo "$REPO" --procs "$PROCS" \
  > "$WORK/varpool_synth.log" 2>&1
python3 varpool.py "$WORK/data" "$WORK/base/replay_signals.csv" real "$WORK/varpool_real.csv" --repo "$REPO" \
  --procs "$PROCS" > "$WORK/varpool_real.log" 2>&1
python3 rb1024.py "$WORK/data" "$WORK/base" "$WORK/randpool.csv" "$HERE/../ref5y.csv" "$OUT"
python3 rb_extra.py "$WORK/data" "$WORK/base" "$WORK" "$OUT"
python3 make_report.py "$OUT" "$ZIP"
echo "done: $OUT/REPORT_KO.md"
