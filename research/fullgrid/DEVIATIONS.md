# Full-grid study: notes and deviations (not pinned; appended, never edited)

## 2026-10-10, before the run
- Timing and smoke runs on the real Binance data in the development sandbox used the example bracket table, not
  exchange.json, and wrote results to scratch folders that were deleted. Numbers read: only the select-period line in
  PREREG section 10 and, from the end-to-end smoke run (cells S2_ST_ROC 4h and F17_Z 4h only), the counts printed by
  the stages: "6 picks from 2 cells" and "0 of 6 picks pass". No mean, p-value or account figure of any period was
  looked at.
- Self-check on a fresh clone from GitHub with Python 3.12.3, numpy 2.0.2, pandas 2.3.3, numba 0.60.0 (the server's
  versions): 40 passed, 4 skipped (real-bar parity tests that need local bar files); preflight clean (315 cells,
  84 exits, 2,322 grid tasks).
- Smoke run memory: grid workers peaked at about 1.2 GB; outcome tables for 6 coins x 4 timeframes x 84 exits take
  about 4 GB on disk.
- Second code review before the run (no wrong calculation found). Changes, all before any server run, PREREG re-pinned:
  the structure take-profit level must lie beyond the fill price, not the entry reference price (a level between the
  two would only take a loss; PREREG section wording updated, engine-parity test now covers that case); the bootstrap
  seed wording now names the exit (the code always included it); DeepSeek win rates are hidden with the other money
  figures (D11); the grid statistics are summed per period in one pass (same numbers, checked against the old formula
  on random data with gaps); DeepSeek tasks no longer load the unused "best" outcome table. Server script: a restart
  counts the study's own files toward the 60 GB disk floor, a second copy cannot start while one runs, and the
  progress line now covers the outcomes step too.
- Phase 2 prepared before any result (research/fullgrid/regimes.py, not part of the pinned run): each pick and its
  cell's default broken down by market state on the select period only (weekend/weekday in KST as
  paperbot.breakdown; trend and volatility exactly as demobot.regime). The test period stays sealed for checking any
  market-specific rule it suggests. Server script: the compute server may start before the leverage table is in;
  it fetches only that file before the compute step (the code stays the self-checked commit).
- A full rehearsal of bootstrap.sh in the sandbox (real data, the server's package versions, a stand-in GitHub,
  three cells) found that the script ran ONE worker on any server: it exported OMP_NUM_THREADS=1 before asking
  nproc for the CPU count, and GNU nproc obeys that variable. Fixed before any server run (the count is read first).
