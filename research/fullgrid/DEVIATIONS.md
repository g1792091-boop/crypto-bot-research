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
- Testing regimes.py on the rehearsal's output (fake leverage table, three cells): the first lines of its report
  showed the select-period mean of one rehearsal pick (N01_ST_EMA 4h #1) and of its cell's default. Select period
  only (where the picks are chosen anyway); no test or 2020 figure was seen, and nothing in the pinned run changed.
  The rehearsal also showed that no trade happens in the 급변장 regime: the entry check refuses a 2 ATR stop that lies
  beyond the liquidation price (e.g. S2_ST_ROC 4h BTC: 67 long signals in 급변장, 0 trades).
- Prepared before any result, not part of the pinned run (owners 2026-10-10: widen only where results point, add
  coins in a second run, study the bet size): edges.py (numbers at a range's end and the values a second run would
  add; an oscillator level on its end is left out), sizing.py (sizes = the live margins x 1/4 .. 2, leverages kept;
  the size is chosen on the select period as the fastest median month with at most 5% chance to end a month under
  half, the test period shows it; four-week months drawn from the period's weeks), and dump_exchange.py's research-
  only "extra" coins (XRP, BNB, ADA, LINK, AVAX, DOT; the bots keep their six).
- Owners 2026-10-10 evening: no extra coins ("코인 안늘려도돼"). dump_exchange.py is back to the six coins only; a
  second run, if any, widens numbers at a range's end on the same six coins.
- 2026-10-10 22:28 KST, the run at grid task 50 / 2322, no result seen: PHASE2_PREREG.md (sha256 in
  PHASE2_PREREG.sha256) fixes the checks done on the candidates afterwards (cost x2 / x3, years, coins and sides,
  the worst stretch, overlap with the rule bot and between candidates, role-split teams by market state, the forward
  band of the 후보 리그). They are new files and run on the candidates only; the pinned run, its selection and its pass
  rule are unchanged. Their smoke test used the cells' default numbers (live rule), whose 5-year figures were already
  known (docs/combo5y.md, docs/regime5y.md), not any pick of this run or of the rehearsal.
- 2026-10-10 22:52 KST, still before any result: PHASE2_AMEND_1.md runs the role-split team test (phase 2, section 7)
  on three market views (장세, 큰 흐름, 변동성) instead of one, with one BH family over all of them.
- 2026-10-11 KST, after the results (0 / 711 passed): no candidate, so phase 2 and the team test stop at "후보 없음"
  as pre-registered, and the 후보 리그 is not installed. Reference diagnostics written after seeing the results are in
  `diag/` and `ANALYSIS_KO.md` (costs x0 vs x1, chosen side vs the opposite side at the same entries, every bar
  without a strategy, market-state persistence on the default numbers and the picks). They explain the result and
  guide the next step; they change no verdict, and nothing they show is a candidate.
- 2026-10-11 KST, owners' idea: run the reference-only watch list (16 strategies, 38 picks, `diag/watch_sel.json`) as
  paper accounts in the 후보 리그, with 1/4-size and exit-only comparison accounts. The forward checks are fixed in
  `WATCH_PREREG.md` (sha256 in `WATCH_PREREG.sha256`) before the league runs them. Nothing in the pinned study changes;
  none of these picks is a candidate.
- 2026-10-11 KST, later the same day: the owners want to read the rule bot's mid-run results first, so the league is
  prepared but **not started**. If it starts after 2026-10-11, C1 and C2 move by the same number of days (C1 = start + 1
  month, C2 = start + 2 months, the repeat = start + 3 months). The replay still begins at 2026-10-01. Any change to the
  list is made before the start and recorded here.
- 2026-10-11 about 12:00 KST (03:00 UTC): the owners installed and started the 후보 리그 on the paper bot server
  (commit 71631467, the 38 picks of `WATCH_PREREG.md` unchanged). It started on 2026-10-11, so C1, C2 and the repeat keep
  their dates: 2026-11-11, 2026-12-11, 2027-01-11. The replay begins at 2026-10-01 as written.
- 2026-10-11 KST, owners on the league dashboard: "딥시크 쪽은 왜 금액없이야 똑같이 해야지". The 후보 리그 dashboard and its
  snapshots now show DeepSeek money like the core picks (wallet, mean per trade, equity line), as the rule bot's own
  dashboard does (`CANDLEAGUE_DS_MONEY` defaults to on; `0` hides it again). This changes WATCH_PREREG section 2's
  "DeepSeek money stays out of every report" for the league's screens only; the checks, their rules and their dates do
  not change. Files committed to the repository still carry no DeepSeek money figure.
- 2026-10-11 KST, before any checkpoint: `diag/watch_check.py` (WATCH_PREREG 5) is committed. Its reading of "at the
  checkpoint": the trades closed before 00:00 UTC of the checkpoint date (09:00 KST that day), so the numbers do not depend
  on when on that day it runs. It takes each trade's result from the snapshot's equity line (wallet after each closed
  trade), which keeps every trade (the trade list keeps the newest 200 only). The dashboard's 점검 진행 screen shows the
  same rules on the day's numbers as a preview (candleague/summary.py, the same functions).
- 2026-10-11 KST, before any checkpoint: the reading of WATCH_PREREG 3.5 ("the same three conditions and a
  Benjamini-Hochberg 10% over the 16 strategies") used by `diag/watch_check.py` and the dashboard. A strategy passes when
  its pooled `cand` trades meet C2's three conditions (mean > 0 with p < 0.05 on its own seed "watch|" + strategy name +
  date, mean > its `base` and > its `flip`, at least 300 closed `cand` trades) and it is among the BH 10% discoveries
  over all 16 strategies. A strategy under 300 trades stays in the family of 16 with p = 1 and cannot pass (the same as
  `run.py`'s family under its trade minimum), so the family size never shrinks. The strategy section is computed only
  when the snapshot carries both pools' money; otherwise the script says so instead of computing a smaller family. The
  script also refuses to give checkpoint numbers while the league has not processed past 00:00 UTC of the date.
- 2026-10-12 about 08:10 KST, owners on the league dashboard after the "설치 뒤 진입만" switch: "거래기록은 왜 안보이는거야?
  아니 커스텀값 봇 돌린 시점부터 원래 돌리고있었던 규칙봇 형식처럼 해야지 봇 돌린시점부터 거래 기록이랑 다 보이게". The
  league now starts at its install time instead of a replay from 2026-10-01: on its first run the new code (candleague
  VERSION 2) starts over from the install time recorded in the league database (meta.started_ms, 2026-10-11 about
  03:00 UTC, floored to 5 minutes), every account at $5,000 then, and catches up to now; every trade, balance, rank and
  day count is from that start on. This changes WATCH_PREREG section 1's "Time: replayed from 2026-10-01 00:00 UTC". The
  checkpoint dates do not change: the start is 2026-10-11, so C1 = start + 1 month = 2026-11-11, C2 = 2026-12-11, the
  repeat = 2027-01-11 (and the rule "trades closed before 00:00 UTC of the date" stays). The 2026-10-01 to 2026-10-11
  replay record (data after the study's, so out of sample, but replayed, not live) is kept only as a copy of the old
  database next to it (league_replay_from_1001_<UTC date>.db), not shown on the dashboard and not used by any checkpoint.
  What it costs: about 10 fewer days of forward record at C1 (about 31 days from the start instead of about 41 from
  10/01), so fewer trades toward the 300-trade condition at C2. No pick, account, rule, threshold or seed changes. The
  start is recorded once and kept: a later code change that starts the league over starts again from the same start.
