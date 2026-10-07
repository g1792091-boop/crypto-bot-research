# Resume notes: rule-bot deep analysis (paused 2026-10-07 10:30 UTC)

The owners paused this work ("보류"). This file tells a later session how to continue without redoing finished work. Owner-facing status: `STATUS_KO.md`.

## What the analysis is for
The owners want a detailed, verified analysis of the paper rule bot's live results (v3a, v3b, v4) to choose which strategies get a dedicated Claude AI trader. AI-trader plan: about 30 Sonnet traders, one strategy each, entries on 15m/30m only (views 1h/4h), 20-50x leverage, about $500/month, start target 10/17. Design docs: `docs/aibot/`. Nothing gets built before the owners say "좋아".

## State
- Export: `data/paperbot_export_20261007_0641.zip`, made by `scripts/rb_export.py` on the server (read-only). Runs: `run-20261005T014624Z` = v3a, `run-20261005T183457Z` = v3b, `current` = v4.
- Pipeline: `scripts/analyze.py <extracted_export> <out_dir>`, about 30 s. Run it with `python3 -I`, from a working directory where the repo is importable; it imports the repo engine read-only. Outputs: `out_real/summary.md` and `out_real/tables.tar.gz`. Replay parity with the live engine is exact on 1,234 closed trades.
- Workflow: `workflow/rulebot-deep-analysis.js`.
  - Finished: all 9 lenses (`ours_15_30`, `ours_1h_4h`, `deepseek`, `exits`, `costs`, `context_filters`, `ai_upside`, `luck_flow`, `fiveyear`) and 4 verifications (`ours_15_30`, `ours_1h_4h`, `deepseek`, `exits`).
  - Not run: verification of `costs`, `context_filters`, `ai_upside`, `luck_flow`, `fiveyear`; the three selection proposals and the judge; the completeness critic and gap fillers; the Korean report writer (`docs/aibot/RULEBOT_ANALYSIS_KO.md` was the planned path) and the fact-check pass.
  - Every finished step's full structured result is in `workflow/results_by_step.json`, keyed `lens:<key>` / `verify:<key>`. The raw journal is `workflow/journal.jsonl`. Lens report sections are in `workflow/section_<key>.md`.
- Lens work folders were in the session scratchpad (`.../scratchpad/lens/<key>/`). Scripts and notes are saved under `lens/<key>/`, small data outputs in `lens_outputs.tar.gz`. Files over 2 MB and pickles were not saved (`MANIFEST_EXCLUDED.txt`); lens scripts regenerate them. Paths inside findings still point to the old scratchpad location.

## How to continue
Cross-session workflow cache resume is not possible. Write a continuation workflow:
1. Load `workflow/results_by_step.json`.
2. Run the 5 missing verifications with the same verify prompt and schema as in the original script. Extract `lens_outputs.tar.gz` and the export first, and point agents to the new paths.
3. Build the digest exactly as the original script does.
4. Run select (3 philosophies) → judge → critic → gap fillers → writer → fact-check.

Machine note: 4 CPUs, so the workflow ran 2 agents at a time; the lenses took about 2.5 h.

## Verified headline so far (details in results_by_step.json)
- **Live:** gross R is about 0 at every timeframe; losses equal costs. The round-trip cost is about 0.24R at 15m and about 0.16R at 30m in the current quiet market.
- **5-year:** 69/70 cells at 15m/30m are negative.
- **Direction skill:** none detectable (side-flip test).
- **Rankings:** do not persist across runs. Account P&L reflects only 9-64% of signals.
- **1h/4h:** no direction edge. 20-50x is not executable under the house sizing. N23_HA_ST 4h is the only 5-year gross edge and is about zero net.
- **DeepSeek:** no 15m/30m candidate. About 35 distinct streams. results.csv is right and RESULTS_DEEPSEEK200.md misnames the stage-1 passers.
- **Exits:** cost dominates. The lev10/lock30 gains are regime geometry. Choosing an exit in-sample loses out-of-sample, which argues against weekly per-strategy tuning. Fixed TP at 1-2R is worse at 15m. Keep the 2 ATR stop. Breakeven at +1R helps at 15m. A wider ladder is consistent at 1h. 20-50x with margin = leverage% means 3-18.5% of equity per 15m stop-out.
