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
