# Trend hunt wide (추세 사냥, 넓게): pre-registration addendum to PREREG_HUNT.md

(한국어 설명: `README_WIDE_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. `PREREG_HUNT.md`(v1)는 그대로 두고, 그
기계에 넣는 진입 신호만 넓힙니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면 `DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (KST), before any code of either hunt study existed in the repository and before
any hunt selection or test was run.** The open questions of section 15 are closed by the owners (or by the default
written next to each) before the file is pinned. Pinning = `PREREG_HUNT_WIDE.sha256` over this file, `PREREG_HUNT.md`
and the files of section 10; the code refuses the wide `select` and `test` steps without a matching pin. After the pin
nothing here changes; a change goes to `research/hunt/DEVIATIONS.md` with its reason and date.

Owners (2026-10-11), on the v1 draft with its three entries: **"왜 3가지 신호밖에 없어?"** and, the same day, "하 너무
복잡해 어떻게 해야 1달동안 성공의 매매법을 위해 제대로된 작업을 빠르게 할수 있다는거야? 결론이 뭐야". There is no good
reason to stop at three when about 80 strategies' entries are already coded and pinned. This addendum feeds **every
coded entry** into the same hunt machine, on four timeframes, with and without the gate, and picks at most ten for one
test.
Compute cost is not a constraint (a rented many-core server is allowed).

## 0. What this is

* An **addendum**, not a replacement. v1 (`PREREG_HUNT.md`: E1-E3, 1h/4h, G1, one pick) runs **unchanged and
  separately**. Neither study changes the other's systems, pick, seeds or pass. Both are reported side by side.
* Section numbers written "H n" refer to `PREREG_HUNT.md` section n. Everything not written here is exactly as there.
* Like v1, this is research only: it touches nothing of the rule bot, the candidate league, the full grid's pinned
  files or any account.

## 1. Question

Among all entries already coded in this repository (v1's three, the rule bot's 36, DeepSeek's 44, the 38 watch picks),
each run through the one trend-hunt machine of H 2-4 and H 6-10 on 15m, 30m, 1h and 4h bars, with the 추세장 gate or
without it: do the at most ten systems chosen on 2021-2023 grow one wallet after all costs on 2024-01 .. 2026-09, and
beat the same machine fed with random entry times and with coin-flip sides, after correcting for testing ten?

## 2. The machine (W1): what is unchanged, what differs

**Unchanged, as written in `PREREG_HUNT.md`:** H 2 (data, checks, funding, storage), H 3 (the 30-coin universe, old six
/ new 24, the large group), H 4 (bars and indicators), H 6 (the 장세 label and the G1 rule), H 7 (7.1 entry fill,
7.2 first stop and unit, 7.3 leverage and isolated margin, 7.4 pyramiding, 7.5 chandelier exit, 7.6 order inside a 5m
bar), H 8 (one wallet, one position per coin, 6 positions, 3 longs / 3 shorts in the large group, total open risk
<= 4%, same-close order by 30-day quote volume), H 9 (costs and cost x2), H 10 (accounts, monthly multiple, bust,
metrics), H 12 (controls (a) and (b), 100 seeds each).

**Differs (only these):**

* **Entries** (H 5): replaced by the four families of section 3.
* **Timeframes** (H 4): 15m and 30m are added. Bins are UTC (15m at :00 :15 :30 :45; 30m at :00 :30), built from the
  5m bars exactly as H 4 builds 1h and 4h. The 장세 label on 15m and 30m uses `regime5y.TF_MIN` (15 and 30 minutes),
  which already has them.
* **First stop** (H 7.2): D0 = **2 x ATR14 for 15m, 30m and 1h systems**; 1.5 x ATR14 for 4h systems (unchanged).
  ATR14 of the signal bar, on the system's own timeframe.
* **Chandelier** (H 7.5): highest high (long) / lowest low (short) of the system's own signal bars since entry, -/+
  **3 x ATR14 of the system's timeframe**, updated at each close of that timeframe (so a 15m system updates every
  15 minutes). Unchanged otherwise.
* **Gate** (H 6): two variants per entry, **G1** (an event passes only on a 추세장 signal bar, H 6 as written) and
  **NONE** (every event passes). For NONE, "gated signal" in H 8 and H 12 means every event.
* **Size**: r = **0.5%** for selection and test. r = 1%, 2% and 5% are reads only (section 7).
* **Selection, test rule and reads**: sections 5-7 here replace H 11, H 13 and H 14 for this study.

## 3. Entry families (W2)

Each family gives, per coin and timeframe, a long and a short event series. **Every family's own exits, take-profits,
stop rules, leverage groups and sizing are ignored**: only the entry bar and side are used, and the machine of section 2
does the rest.

| family | what | numbers |
|---|---|---|
| **F1** | E1 (Donchian 55 + volume), E2 (Bollinger squeeze release), E3 (ATR expansion), exactly H 5 | main number only (channel 55, window 120, threshold 1.5); no neighbours |
| **F2** | the rule bot's 36 strategies = `research/fullgrid/run.core_names()` (the full grid's core set; `research/entry_study/param_defs/<NAME>.py`, pinned by `DEFS_BC.sha256`) | defaults, `run.default_combo("core", name)` |
| **F3** | the 44 DeepSeek definitions = `run.ds_module().DEFS` (`research/fullgrid/ds_defs.py`) | defaults, `run.default_combo("ds", name)` |
| **F4** | the 38 watch picks = `research/fullgrid/diag/watch_sel.json` (sha256 f6902feb42a7993098b794d0968bdf54fc2c3dbc43c0a6a0d7c56b43af53de56), the file the candidate league was built from (`candleague.candidates watch --select`); its 38 (kind, name, timeframe, numbers) equal those in `candleague/data/candidates.json` | each pick's own numbers (`combo`), on its own timeframe only; its `exit` field is ignored |

### 3.1 Signal arrays (F2-F4)

The arrays are produced by the **same functions the full grid's kernel consumed**, called the way `run.signals` calls
them, imported read-only:

* core: `run.core_module(name).signals(df, tf, **combo)`; DeepSeek: `run.ds_module().signals(df, tf, name, ctx=ctx,
  coin=coin, cache=cache, **combo)`; each output converted as `run.signals` converts it (`np.asarray(x, bool)`).
* `df` = the coin's bars of that timeframe as a DataFrame with exactly the columns, dtypes and `attrs["tf"]` of
  `run.build_frame`: `ts` (bin open, UTC), `open`, `high`, `low`, `close`, `volume` (float64). It is built from the 5m
  bars of H 4 instead of the 1m bars. **`volume` here is the base-asset volume** (the 5m arrays' `v`, the full grid's
  column), not the quote volume that E1, the liquidity cut and the large group use (H 2).
* `ctx` = `{"BTCUSD": BTCUSDT's df of the same timeframe}` for every coin except BTCUSDT, `None` for BTCUSDT;
  `coin` = the symbol without its final "T" (e.g. "XRPUSD"); a fresh `cache` and `run.M.clear()` for each coin x
  timeframe series, as `run.signals` does.
* Before any signal is computed, the full grid's pinned files must match `research/fullgrid/PREREG.sha256`, and every
  core definition loads only through `run.core_module` (which refuses a file that does not match `DEFS_BC.sha256`).
* The full grid's warm-up applies: a bar among the coin's first 300 bars of that timeframe (`run.WARMUP_BARS`) gives no
  F2-F4 event.

### 3.2 Event rule (all families)

* **A long event on bar t = the long array is True on bar t and False on bar t-1** (the previous bar of the same coin
  and timeframe series; the first bar of a series gives none). Short the same with the short array. This is H 5's event
  definition applied to every array.
* Why the edge: some arrays are **states** (True for many bars in a row) rather than one-bar events. Taking every True
  bar would re-enter a state strategy on the bar after each chandelier exit. With the edge rule a state strategy enters
  once when its state turns on and again only after it turns off and on. For an array that is already an event the
  rule changes nothing (except two True bars in a row, where only the first counts). Which arrays are states was looked
  at on synthetic bars only (section 16); on the old six's real bars it is reported by the parity check (section 8).
* This differs on purpose from the full grid, where every True bar was a separate trade (full grid PREREG 5).
* An event also needs ATR14 of the signal bar (D0, H 4). A bar with **both** a long and a short event on the same coin
  gives no entry (counted as "both sides", section 15 Q3).
* H 8 unchanged: an event on a coin that holds a position (either side) is ignored; several gated signals at the same
  close are taken by 30-day quote volume.

## 4. Systems (W3, W4)

A **system** = (entry, timeframe, gate). Its id: `F<n>:<name>:<tf>:<gate>` (F4 ids carry the pick's watch rank as
written in `watch_sel.json`, `F4:<name>:<tf>:<gate>:r<rank>`). Timeframes: F1 and F2 on 15m, 30m, 1h, 4h; F3 on the
timeframes of `ds_defs.TFS_OF[name]` (all four, except the five ET-session definitions F15_ASIA_BRK, F15_ASIA_SWEEP,
F15_LON_BRK, F15_OPEN0930, F15_OPEN0000, which are defined on 15m, 30m and 1h only: full grid PREREG 3); F4 on its
pick's timeframe. Gates: G1 and NONE for every one.

| family | entries | cells (entry x timeframe) | x gates | systems |
|---|---|---|---|---|
| F1 | 3 | 3 x 4 = 12 | 2 | 24 |
| F2 | 36 | 36 x 4 = 144 | 2 | 288 |
| F3 | 44 | 39 x 4 + 5 x 3 = 171 | 2 | 342 |
| F4 | 38 picks (16 strategy names) | 38 | 2 | 76 |
| **total** | | **365** | | **730** |

The brief counted (3 + 36 + 44) x 4 x 2 + 38 x 2 = 740; the generating rule above gives **730** because the five
session definitions have no 4h version (section 15 Q1).

**F1 names**: E1 E2 E3.
**F2 names** (36): DOGE N01_ST_EMA N02_ST_KST N03_ADX_GC N04_ST_KLINGER N05_PSAR_POC N06_MACD_ORB N07_ICHI_CMO
N08_ICHI_WR N09_ALLIG_AROON N10_HA_PSAR N11_BREAKAWAY N12_ICHI_AO N13_3OUTSIDE N14_ICHI_RSI N15_KC_AO N16_BBRSI
N17_KC_RSI N18_VWMA_MACD N19_FIB_CHOP N20_EMA9_CHOP N21_ST_RSI_ADX N22_VORTEX_PSAR N23_HA_ST N24_DMI N25_DST_CCI OBV_B
OBV_S S1_EMA_RSI_CHOP S2_ST_ROC S3_CMO_SANDWICH S4_BB_BBP S5_DONCHIAN_MFI S6_EMA_DMI_ADX V39_ALL V45_AMB.
**F3 names** (44): F1_RSI_DIV F1_MOM_DIV F1_PVT_DIV F2_DEMARK F3_BOS F3_BOS_ZONE F3_HHHL F4_PULL F4_PULL_RSI F4_FAN
F5_BOX F5_BOX_RSI F5_BOX_HTF F6_VWAP_CROSS F6_VWAP_FAIL F7_RF_TRIPLE F7_RF_ONLY F8_VWICK F9_FVG F9_IFVG F9_OB
F9_BREAKER F10_M2022 F10_OTE F11_TSOUP F11_RAID F11_PO3 F12_MSS F12_MSS_DISP F13_FVG_PD F13_RAID_PD F14_SMT
F15_ASIA_BRK F15_ASIA_SWEEP F15_LON_BRK F15_OPEN0930 F15_OPEN0000 F15_ORB F16_FIB382 F16_FIB500 F16_FIB618 F16_FIB764
F17_Z F17_Z_HL.
**F4 picks** (38, name: timeframes): DOGE 15m 30m 1h 4h; N03_ADX_GC 15m 30m 1h; N09_ALLIG_AROON 15m 30m 1h 4h;
N10_HA_PSAR 4h; N13_3OUTSIDE 30m 1h; N19_FIB_CHOP 15m 30m 4h; OBV_S 30m 1h 4h; S4_BB_BBP 30m 1h 4h (23 core);
F10_OTE 1h 4h; F11_TSOUP 4h; F12_MSS_DISP 1h 4h; F1_PVT_DIV 1h; F5_BOX 15m 4h; F7_RF_ONLY 30m 1h 4h; F7_RF_TRIPLE 1h 4h;
F9_FVG 1h 4h (15 DeepSeek). None of the 38 has its strategy's default numbers, so no F4 system repeats an F2/F3 one.

**Strategy name** (for the one-per-name rule of section 5): E1, E2, E3 for F1; the core or DeepSeek name for F2-F4. An
F4 pick counts under its strategy's name (F4 DOGE 15m and F2 DOGE 1h share the name DOGE). Distinct names: 83.

## 5. Selection (W5)

* Period: **select 2021-01-01 .. 2024-01-01** by signal-bar close (H 11). The select step loads no 5m bar that opens at
  or after 2024-01-01 00:00 UTC; positions still open there are marked at the last 5m close (H 10).
* Runs: every one of the 730 systems, **r = 0.5%**, one account (H 10: $5,000, compounding) at base costs and one at
  cost x2 (H 9). No neighbours and no plateau (H 11.1-11.2 do not apply).
* **Eligible** = all of: at least **72 positions**; mean monthly ln M **> 0**; **no bust**; mean monthly ln M at cost x2
  **> 0**.
* **Score** = mean monthly ln M of the base-cost run (36 months).
* **Order**: score, highest first. Ties: higher median monthly multiple; then family F1 < F2 < F3 < F4; then name
  (ASCII); then timeframe 15m < 30m < 1h < 4h; then G1 before NONE; then (F4) lower watch rank.
* **Picks**: walk down the ordered eligible systems and take a system when no system of the same strategy name is taken
  yet, until **K = 10** are taken. So at most one system per strategy name (its best timeframe / gate / F4 pick).
  Fewer than 10 eligible names -> every eligible name's best system; K is then that number.
* **No eligible system**: the wide study fails at selection. As in H 11.2, the single highest-scoring system (any,
  eligibility ignored) is still run on the test period, labelled "no pick, fail"; nothing else is.
* `research/hunt/out/wide/picks.json` (each pick's system id, family, name, timeframe, gate, numbers and pick number
  1..K) is written, and its sha256 appended to `PREREG_HUNT_WIDE.sha256`, **before any test-period bar is read**. The
  test step refuses to start without that line, and the picks do not change after it.

## 6. Test (W6)

* Period: **test 2024-01-01 .. 2026-10-01** (33 months), H 11. **Each pick runs once**, r = 0.5%, base costs, plus its
  cost x2 run. Systems that are not picks are never run on the test period.
* **Controls** for each pick: (a) random times and (b) coin-flip sides, **100 seeds each, exactly H 12** (the pick's
  timeframe, gate, r and period; (a) draws per coin and side the pick's number of gated signals from bars with a known
  장세 label and a defined ATR14, not gated; (b) the pick's gated signals with fair-coin sides). Seed = sha256 of
  ("hunt-wide", system id, control, period, r, seed number), the parts joined as the v1 code joins its seed parts.
  d_m per control as H 12. (In the test period every coin is past its 180-day label history and its 300-bar warm-up,
  so the (a) pool is the same set of bars for G1 and NONE picks.)
* **Per pick, as H 13:** **P0** at least 66 positions, a position open in at least 80% of the test months, no bust;
  **P1** median monthly multiple >= 1.0 and mean monthly ln M > 0; **P3** cost x2 median monthly multiple >= 1.0;
  **P4** max drawdown < 50%.
* **P2, split:** p_a and p_b = the one-sided month-block bootstrap p of mean d_m for control (a) and for (b), as H 13
  (10,000 resamples of the 33 months; p = (1 + resamples with mean d <= 0) / 10,001; seed as above with "boot" in place
  of the seed number). **p = max(p_a, p_b).** **Seed-rank part**, for (a) and for (b) separately: (1 + seeds whose mean
  monthly ln M >= the pick's) / 101 < 0.05.
* **Multiple testing**: Benjamini-Hochberg at **q = 0.10** over the K values of p (sort ascending p_(1) <= ... <=
  p_(K); k* = the largest k with p_(k) <= 0.10 x k / K; every pick with p <= p_(k*) is BH-significant; none if no such
  k). Every pick stays in the family whatever else it fails; a pick without a defined p (for example a bust before any
  full month) enters with p = 1.
* **A pick PASSES** = P0, P1, P3, P4, both seed-rank parts, and a BH-significant p.
* **WIDE PASS** = at least one pick passes.
* v1 runs unchanged and separately (H 11-13, its own pick and seeds). If v1's pick is also a wide pick, it is run in
  each study with that study's seeds; the two results are reported separately and neither counts for the other.

## 7. Reads (W7): reported, never a pass

For each pick unless stated (test period unless stated):

* **New 24 only**: the pick on the 24 new coins alone (same rules; large group = the top 10 of the 24), select and test.
  A passing pick with new-24 test mean ln M <= 0 is labelled **"carried by the old six"** (H 14).
* **Extra 2020** (H 11): r = 0.5% and r = 1%.
* **r = 1% line**: P0-P4 and both seed-rank parts at r = 1% (controls rerun at r = 1%, seeds as section 6 with
  r = 1%), shown as "1% also passes: yes / no"; and the **cost x2 line at r = 1%**.
* **One-wallet basket** of all passing picks (when at least two pass): one wallet, r = 0.5% per unit, H 8's caps
  shared by all of them (one position per coin across all picks, 6 positions, 3 / 3 in the large group, 4% total open
  risk). Same-close order: 30-day quote volume (H 8), then pick number. Select and test.
* **Sizing read** for each passing pick and for the basket: **r = 2% and r = 5%**, the total open risk cap scaled by
  r / 0.5% (16% at r = 2%, 40% at r = 5%), leverage as H 7.3 with its 20x cap and the margin budget B = equity / 6
  unchanged (cuts and skipped adds counted), everything else as here. Reported: the **share of test months with
  M >= 2, >= 10 and >= 30**, the **worst month**, **bust** (and its month), and the H 10 metric set. This is the honest
  answer to the owners' goal ($1,000 -> $30,000-50,000 fast, x30-x50): it shows how often a larger bet gave such months
  and how often it went bust, on data the choice never saw. It is not a pass and not a paper account (section 15 Q9).
* Also reported, never a pass: the controls in the select period for each pick; the gate diagnostics of H 14 for each
  pick; the select table of all 730 systems (section 11 for DeepSeek rows); the count of "both sides" bars.

## 8. Parity (W8): the entries equal the full grid's, before the pin

* Coins: the old six (BTCUSDT ETHUSDT SOLUSDT DOGEUSDT LTCUSDT BCHUSDT). Systems' entries: every F2 and F3 strategy on
  every timeframe it has (144 + 171 = 315 cells) and the 38 F4 picks. **Signals only; no position, fill or outcome is
  computed.**
* Reference: the full grid's own path, `run.build_frame` on the full grid's 1m archive (`<fg1m>/1m/<SYM>.npz`)
  followed by the same calls as section 3.1. Adapter: section 3.1 on the 5m arrays of the hunt data.
* Compared on the bars both series have (same bin open time), after both series' first 300 bars; per strategy x
  timeframe x side, for the raw boolean arrays and for the edge events of 3.2.
* **Mismatch share** = bars where the two differ / bars where either is True. A mismatch at bar t is **excused** when
  the two bar series differ beyond H 2's tolerance (OHLC 1e-6 relative, volume 0.1%) on any bar t-299 .. t (5m-vs-1m
  bar building); both the raw and the unexcused share are reported.
* **Fail** = an unexcused mismatch share above **1%** on any strategy x timeframe (either side, raw or event). A fail is
  fixed in the adapter before the pin and the fix written in section 16. A strategy x timeframe that cannot be made to
  pass is removed from the study before the pin, with its reason, and the counts of section 4 are corrected here.
* Also reported per cell: the share of True bars that are not edge events (0 = the array is already an event), for the
  reference array.
* Output: `research/hunt/out/wide/parity.json` (counts and shares only), part of the pin (section 10).

## 9. Data (W9)

* The H 2 data of the 30 coins: per coin a 5m array file `<data>/5m/<SYM>.npz` with keys `ts` (int64 open time, ms) and
  `o h l c v qv mo mh ml mc` (float32; `v` base volume, `qv` quote volume, `m*` mark price), cast to float64 at load;
  funding in `<data>/funding/`; the universe from `<data>/UNIVERSE.md` and `manifest.json` (copied into
  `research/hunt/universe30.json` as H 3). The mark-price columns are not read (H 2: liquidation on last-price bars;
  section 15 Q4).
* The download is still running when this is written. No code waits on it: every path is given by `--data`, and a
  coin whose file is missing stops `select` and `test` (the universe is fixed) but not the tests on synthetic bars.
* Parity (section 8) also reads the full grid's 1m archive of the old six, given by its own path argument.
* Nothing of the price data is copied into the repository. Cached signal arrays, if any, live under the data or a
  scratch directory, never in the repository.

## 10. Code, command, pin, compute (W10)

* Command: `python -m research.hunt.hunt {select,test,report} --study {v1,wide} [--procs N] [--data DIR]`. `select`
  and `test` refuse to run unless the study's pin file (`PREREG_HUNT.sha256` for v1, `PREREG_HUNT_WIDE.sha256` for wide)
  matches every file it lists; `test` also needs the picks line (section 5).
* `PREREG_HUNT_WIDE.sha256` lists: this file; `PREREG_HUNT.md`; `research/hunt/universe30.json`;
  `research/hunt/exchange30.json` when it exists (H 7.3); every Python file under `research/hunt/` that the command
  imports; the hunt tests under `tests/`; `research/hunt/out/wide/parity.json`; and, as read-only inputs checked by
  hash, `research/fullgrid/diag/watch_sel.json`, `research/fullgrid/PREREG.sha256` (whose own list must match),
  `research/entry_study/DEFS_BC.sha256` and `paperbot/dash/tools/regime5y.py`. Later, the picks line.
* Outputs: `research/hunt/out/wide/` (select.json, picks.json, test.json, reads.json, parity.json and a Korean results
  page), each stamped with the git commit and the sha256 of the pin file it ran under.
* Compute: systems are independent, so select splits by system and test by pick x control seed; `--procs N` sets the
  worker count (at most 2 on the development machine; any number on a rented server). Results do not depend on N:
  seeds depend only on the parts written in section 6. No absolute path is written in the code.
* Tests on synthetic bars only (the event edge rule, the 15m/30m D0 and chandelier, the selection order and
  one-per-name rule, BH, the scaled risk cap of the sizing read, refusal without a pin), in addition to v1's (H 16).
* Run time is measured on synthetic bars once the code exists and written in `DEVIATIONS.md` before the run; if select
  plus test would take more than about a day at 2 processes, the run goes to a rented server (section 15 Q10).

## 11. Reporting and DeepSeek money (D11)

* Core and F1 rows: every number of H 10 and sections 5-7.
* **DeepSeek rows (F3, and F4 picks of DeepSeek strategies) in repository files show counts, win shares, ranks / pick
  numbers and labels only** (eligible or not and which condition failed, picked, P0-P4 / seed-rank / BH pass or fail,
  PASS, bust yes / no, "carried by the old six"). Their other numbers (ln M, multiples, drawdowns, P&L, p-values, d_m)
  are written only to a file outside the repository whose sha256 is written in the repository output, so the selection
  and the test can be checked later without the figures being in the repository.
* Every result, pass or fail, goes into the results page and the owners' summary, next to v1's.

## 12. What a result means, and after

| result | then |
|---|---|
| WIDE PASS | **forward paper bot from about 2026-10-20** on the 30 coins, **beside the v1 pick**: each passing pick exactly as here, r = 0.5% and r = 1%, $5,000 each; plus the one-wallet basket when two or more pass. Nothing else changed. **No real money before the mid-November 2026 review**; after it, real money is the owners' decision only |
| a pick fails | recorded as a fail with its numbers (DeepSeek: labels). Not a candidate |
| WIDE fail (no pick passes, or no eligible system) | recorded. **No tuning on the test period**; systems that are not picks are never run on it |

* Nothing is tuned after the test period is seen. A bug found after the test is fixed in `DEVIATIONS.md`, the test
  rerun once, both results shown. Any changed rule (entries, numbers, gate, exits, size, K, scores) is a new study with
  its own pre-registration, judged only on data after its fixing date.
* **Two studies, one test period.** v1 and wide each have their own pass; the chance that at least one of the two
  passes by luck is larger than either alone. The report says this next to the two verdicts.
* The mid-November review checks the paper bot as H 15 (it followed the rules; its forward multiple lies inside the
  test period's rolling-window range; nothing broke). About 3.5 weeks of forward data cannot prove a trend system.

## 13. Known limits (stated before any result)

* **The old six are not blind.** The full grid's results for F2/F3 at default numbers (with the rule bot's exits) on
  the old six, including 2024-2026, have been read by the owners and the main session. **The 38 F4 picks were chosen
  after the full grid's test period and 2020 were seen** (WATCH_PREREG 0), so an F4 pick's test on the old six is not
  out of sample. The new-24 read is the cleaner check and is shown next to every pick (section 15 Q2).
* **Winner's curse.** The best of 730 select runs looks better on 2021-2023 than it is. Only the single test, the
  controls and BH over K speak to that.
* **Power.** 33 test months and BH over up to ten picks: a real but small edge may not pass.
* The universe is a 2026 list (H 3, H 18 Q2). The strategies were written for the old six; DeepSeek definitions that
  read BTC context get BTCUSDT's bars on every coin.
* The edge rule (3.2) makes state strategies enter less often than the full grid counted them.
* On 15m and 30m the first stop and the chandelier are tight relative to costs (5m fills, taker fees); this is part of
  what is tested, not a reason to change the costs.

## 14. Not in this study

Numbers other than the defaults and the 38 watch picks' numbers; combining entries inside one system (the basket is a
read); exits other than the chandelier; r above 0.5% as the rule; gates other than G1 and NONE; the AI judgment layer
(H 17); timeframes other than 15m, 30m, 1h, 4h.

## 15. Open questions (closed before the pin; default in brackets)

1. **730, not 740.** The five ET-session DeepSeek definitions exist only on 15m/30m/1h (`ds_defs.TFS_OF`); running them
   on 4h would use code the full grid never ran and cannot be parity-checked. [730; no 4h for those five]
2. **F4 on the old six is not out of sample** (section 13). Alternative: an F4 pick (or every pick) passes only if its
   new-24 test mean ln M > 0 as well. [Label only, as designed: "carried by the old six" and "numbers chosen after the
   test was seen" shown next to the verdict]
3. **Long and short event on the same bar and coin.** [No entry; counted]
4. **Mark price.** The new 5m files hold mark-price columns, but H 2 and H 7.6 check liquidation on last price and this
   study keeps the machine identical to v1. [Last price, as H 2; mark columns unread]
5. **K = 10, one per name.** [Keep]
6. **72 positions in 36 months** may exclude many 4h G1 systems. [Keep; the gate is not changed for it]
7. **Score = mean ln M**; the median is only a tie-break here (v1 uses a median-based plateau). [Keep]
8. **Sizing read**: the margin budget equity / 6 and 20x will cut 5% units; the read reports those cuts rather than
   loosening them. [Keep]
9. **Paper accounts at 2% or 5%.** [None; the owners decide after reading the sizing read, labelled as such]
10. **Where it runs.** [The development machine at 2 processes if the measured time allows; otherwise a rented server
    started by the owners, same commit and pin]
11. **State arrays and the edge rule** (3.2). [Edge rule for every family]
12. **A strategy x timeframe failing parity** after a fix attempt. [Removed before the pin, recorded here]
13. **No eligible system.** [As v1: the top system runs once, labelled "no pick, fail"]

## 16. Before this file was fixed

* When this draft was written `research/hunt/` held only `PREREG_HUNT.md` and `README_KO.md` (both drafts under review,
  read only). No hunt code had run; no selection, test or account of either hunt study exists.
* No price of the 30 coins was opened: only the key names and dtypes of one 5m file (`BTCUSDT.npz`) and of one file of
  the full grid's 1m archive (`BTCUSDT.npz`), for the loader. `UNIVERSE.md` was read (its rule and list; 2023 volume
  only).
* Read for the entry lists: `research/fullgrid/run.py` (core_names, default_combo, signals, build_frame, WARMUP_BARS),
  the names and timeframes of `ds_defs.py`, the 38 rows of `watch_sel.json` (kind, name, timeframe, numbers; checked:
  38 distinct cells, none at its default numbers, the same 38 as `candleague/data/candidates.json`). Printing the first
  row of `candidates.json` showed that pick's stored full-grid test mean and forward band (DOGE 15m, the rule bot's
  exits); nothing of it is used here. The full grid's pinned files were checked against `PREREG.sha256` (all match).
* One synthetic check, no real price: each F2/F3 strategy at default numbers on one seeded random 1h series of 6,000
  bars, counting True bars and edge events (no position, no outcome). 64 of the 80 arrays were pure events; 5 nearly
  (at most 1.4% of True bars not edges: N16_BBRSI, F8_VWICK, F9_FVG, F9_IFVG, F9_BREAKER); 8 state-like (N17_KC_RSI,
  N18_VWMA_MACD, N19_FIB_CHOP, OBV_S, F2_DEMARK, F4_PULL, F5_BOX, F14_SMT); 3 gave no signal on that series
  (N14_ICHI_RSI, N15_KC_AO, N21_ST_RSI_ADX). This only motivated the uniform edge rule of 3.2.
* The owners and the main session have read the full grid's results on the old six, the watch list and its selection,
  and the per-strategy reports (section 13).
* The wide design (families, timeframes, gates, K, score, BH, reads) was set by the main session the same day in answer
  to the owners' question, before any hunt run.
