#!/usr/bin/env bash
# V3.9 1h study, one command, from one rule-bot export zip (analysis/live1019/rb_export.py output).
#
#   bash analysis/v39_1h/run_all.sh <export.zip> <new_empty_work_dir> [out_dir]
#
# How the owners make a new export (server, read-only, about a minute):
#   sudo -i
#   nice -n 19 python3 /root/rb_export.py        # -> /root/paperbot_export_<date>.zip
# (if /root/rb_export.py is missing, paste analysis/live1019/rb_export.py there first).
#
# <new_empty_work_dir>: a NEW folder outside the repository (e.g. the session scratchpad). The zip is extracted there
#   with extract_zip.py (data files only, never executed) and pruned to what the study reads.
# [out_dir]: default analysis/v39_1h/out. Writes window/ (27-trade study), fiveyear/, extras/, TABLES_KO.md, facts.json.
# Env: BARS_CACHE=<dir> reuses public klines already fetched (default <work>/bars, ~190 MB of 5m bars);
#      COMPARE_CUT_MS=<ms> also reruns the window study as of that time into <out>/window_cut (e.g. an older export's
#      end, to compare the runs); SIMS (default 20000) Monte Carlo months.
# Needs python3 with numpy, pandas, numba, scipy (the repository's usual research setup); about 3-4 minutes.
set -euo pipefail
ZIP="$1"
WORK="$2"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="${3:-$HERE/out}"
BARS="${BARS_CACHE:-$WORK/bars}"
if [ -e "$WORK" ] && [ -n "$(ls -A "$WORK" 2>/dev/null)" ]; then
  echo "refused: $WORK exists and is not empty"; exit 1
fi
mkdir -p "$WORK" "$OUT" "$BARS"
basename "$ZIP" > "$OUT/source.txt"
cd "$WORK"
python3 -I "$REPO/analysis/review1024/rulebot/scripts/extract_zip.py" "$ZIP" "$WORK/export"
read -r START_MS END_MS FIRST_DAY LAST_DAY < <(python3 -I "$HERE/prune_export.py" "$WORK/export")
echo "export bars: $FIRST_DAY .. $LAST_DAY (UTC)"
YESTERDAY="$(python3 -I -c 'import datetime as d; print(d.datetime.now(d.timezone.utc).date() - d.timedelta(days=1))')"
python3 -I "$HERE/fetch_bars.py" five --cache "$BARS" --last-day "$YESTERDAY"
MIN_ARGS=()
if [[ "$LAST_DAY" < "$YESTERDAY" || "$LAST_DAY" == "$YESTERDAY" ]]; then
  # 1m bars after the export's end, when the public archive already has those days (hours after the last exits)
  if python3 -I "$HERE/fetch_bars.py" minute --cache "$WORK/minute" --from "$LAST_DAY" --to "$YESTERDAY"; then
    MIN_ARGS=(--minute-dir "$WORK/minute/1m")
  fi
fi
FG_ARGS=()
if git -C "$REPO" show origin/fullgrid-results-20261010-1602:research/fullgrid/results/default_by_exit.npz \
     > "$WORK/fg_default_by_exit.npz" 2>/dev/null && \
   git -C "$REPO" show origin/fullgrid-results-20261010-1602:research/fullgrid/results/grids.json \
     > "$WORK/fg_grids.json" 2>/dev/null; then
  FG_ARGS=(--fullgrid "$WORK/fg_default_by_exit.npz" --fullgrid-exits "$WORK/fg_grids.json")
else
  echo "note: full-grid results branch not found; 5-year table without the full-grid's own numbers"
fi
python3 -I "$HERE/window.py" "$WORK/export" "$BARS/5m" "$OUT/window" ${MIN_ARGS[@]+"${MIN_ARGS[@]}"}
if [ -n "${COMPARE_CUT_MS:-}" ]; then
  python3 -I "$HERE/window.py" "$WORK/export" "$BARS/5m" "$OUT/window_cut" --cut-ms "$COMPARE_CUT_MS"
fi
python3 -I "$HERE/fiveyear.py" "$BARS/5m" "$OUT/fiveyear" ${FG_ARGS[@]+"${FG_ARGS[@]}"} --paper-start-ms "$START_MS"
python3 -I "$HERE/extras.py" "$WORK/export" "$BARS/5m" "$OUT/extras" --shadows "$WORK/export/current/v39_shadows.csv" \
  --sims "${SIMS:-20000}"
python3 -I "$HERE/summary.py" "$OUT"
echo "done: $OUT/TABLES_KO.md (the report text is analysis/v39_1h/REPORT_KO.md)"
