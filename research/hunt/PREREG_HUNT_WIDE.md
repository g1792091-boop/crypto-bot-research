# Trend hunt wide (추세 사냥, 넓게): pre-registration addendum to PREREG_HUNT.md

(한국어 설명: `README_WIDE_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. `PREREG_HUNT.md`(v1)는 그대로 두고, 그
기계에 넣는 진입 신호만 넓힙니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면 `DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (KST), before any code of either hunt study existed in the repository and before
any hunt selection or test was run; reviewed and corrected the same day before the pin (section 16.2), still before any
hunt selection or test; extended the same day with the owners' decisions (a)-(h) and the panel review of 23 reads
(section 0.1, section 16.3), still before any hunt selection or test and before any trading outcome on a real price
period.** The open questions of section 15 are closed by the owners (or by the default written next to
each) before the file is pinned. Pinning = `PREREG_HUNT_WIDE.sha256` over this file, `PREREG_HUNT.md`
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

### 0.1 Owners' decisions of 2026-10-11 (binding; where each is written)

* **(a) More entries:** the four famous trend rules of `research/famous/famous.py` (turtle 20/10, turtle 55/20,
  time-series momentum 7 and 28 days) as family **F5**, per-coin events on 15m / 30m / 1h / 4h, G1 and NONE: 32
  systems. F1-F3 + F5 = **686 candidate systems**; F4 stays a select-only read (sections 3.3, 4).
* **(b) "10개 넘게 좋은게 나오면":** batched test. Batch 1 = positions 1-10 of the one-per-name walk; BH q = 0.10
  within each batch; if >= 5 of a batch PASS, the next 10 by select score are tested the same way; membership of every
  batch is fixed in `picks.json` at select time, before any test bar; labels 1군 / 2군 / 3군 (sections 5, 6).
* **(c) Controls:** 1,000 seeds each (was 100) (section 6; H 12).
* **(d) Exits:** the six exit cells (chandelier 2 / 3 / 4.5 ATR x pyramiding 3 adds / none) are **reads on the fixed
  picks, never selection choices** (R5; the panel rejected them as choices: winner's curse).
* **(e) Goal "결국엔 수익률":** owner-facing goal reads report multiples (x2, x5, x10 ...), not dollars; a dollar figure
  appears only as the fresh-wallet start ($1,000) or as an account size (R1, section 12).
* **(f) Leverage "20배·30배·40배 경우":** a rule-bot-style sizing read (R24, section 7.3).
* **(g) Paper lineup:** 정식 = research PASS; 참고 = a tested pick with test mean monthly ln M > 0, median monthly
  multiple >= 1, beating both controls' means, cost x2 mean ln M > 0, max drawdown < 50%, no bust and its best month
  < 50% of the total log gain; everything else is excluded from the paper lineup; real money only from 정식 after the
  forward criteria (section 12).
* **(h) F4 out of the test:** the 38 watch picks were chosen after 2024-2026 was seen: select-only read (section 3).
* **Deferred to round 2 (not in this addendum):** new-information entries, the loss-autopsy noise filters, custom
  values (section 14).

## 1. Question

Among all entries already coded in this repository whose numbers were not chosen on the test period (v1's three, the
rule bot's 36 and DeepSeek's 44 at their default numbers) and four famous trend rules (F5), each run through the one
trend-hunt machine of H 2-4 and H 6-10 on 15m, 30m, 1h and 4h bars, with the 추세장 gate or without it: do the systems
chosen on 2021-2023 (ten, then ten more only when at least five of the previous ten pass, at most thirty) grow one
wallet after all costs on 2024-01 .. 2026-09, and beat the same machine fed with random entry times and with coin-flip
sides, after correcting for testing ten at a time? (The 38 watch picks run through the same machine in the select
period as a read only; section 3.)

## 2. The machine (W1): what is unchanged, what differs

**Unchanged, as written in `PREREG_HUNT.md`:** H 2 (data, the 5m-vs-1m cross-check of the old six in
`research/hunt/data_check.json`, the data identity of `research/hunt/data_manifest.json` checked at every select and
test, funding, the 1 GB disk stop, storage), H 3 (the 30-coin universe, old six / new 24, the large group), H 4 (bars
and indicators), H 6 (the 장세 label and the G1 rule), H 7 (7.1 entry fill, 7.2 first stop and unit, 7.3 leverage and
isolated margin, 7.4 pyramiding, 7.5 chandelier exit, 7.6 order inside a 5m bar: a bar that reaches an add level adds
first and then checks the moved stop), H 8 (one wallet, one position per coin, 6 positions, 3 longs / 3 shorts in the
large group, total open risk <= 4%, same-close order by 30-day quote volume), H 9 (costs and cost x2), H 10 (accounts,
monthly multiple, bust, metrics), H 12 (controls (a) and (b), **1,000 seeds each**), and, inside section 6, H 13's P0,
P1, P3 and P4 (P3 = cost x2 median monthly multiple >= 1.0 and mean monthly ln M > 0).

**Differs (only these):**

* **Entries** (H 5): replaced by the five families of section 3 (F4 a select-only read).
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
* **Size**: r = **0.5%** for selection and test. r = 1% is a read (section 7); larger sizes are the R1 goal board and
  the R24 leverage read (section 7.3), never a rule.
* **Selection, test rule and reads**: sections 5-7 here replace H 11, H 13 and H 14 for this study (H 14's read guard
  covers both).

## 3. Entry families (W2)

Each family gives, per coin and timeframe, a long and a short event series. **Every family's own exits, take-profits,
stop rules, leverage groups and sizing are ignored**: only the entry bar and side are used, and the machine of section 2
does the rest.

| family | what | numbers |
|---|---|---|
| **F1** | E1 (Donchian 55 + volume), E2 (Bollinger squeeze release), E3 (ATR expansion), exactly H 5 | main number only (channel 55, window 120, threshold 1.5); no neighbours |
| **F2** | the rule bot's 36 strategies = `research/fullgrid/run.core_names()` (the full grid's core set; `research/entry_study/param_defs/<NAME>.py`, pinned by `DEFS_BC.sha256`) | defaults, `run.default_combo("core", name)` |
| **F3** | the 44 DeepSeek definitions = `run.ds_module().DEFS` (`research/fullgrid/ds_defs.py`) | defaults, `run.default_combo("ds", name)` |
| **F4** | the 38 watch picks = `research/fullgrid/diag/watch_sel.json` (sha256 f6902feb42a7993098b794d0968bdf54fc2c3dbc43c0a6a0d7c56b43af53de56), the file the candidate league was built from (`candleague.candidates watch --select`); its 38 (kind, name, timeframe, numbers) equal those in `candleague/data/candidates.json`. **Select-period read only: never a pick, never run on the test period, not part of the BH family or of WIDE PASS** (below) | each pick's own numbers (`combo`), on its own timeframe only; its `exit` field is ignored |
| **F5** | the four famous trend rules of `research/famous/famous.py` (`donchian`, `tsmom`): TURTLE20 (Donchian 20/10), TURTLE55 (Donchian 55/20), TSMOM7 and TSMOM28 (time-series momentum, weekly), as entry events (section 3.3); the rules' own exits are ignored | their famous.py numbers (days), converted to bars of each timeframe |

**Why F4 is a read only.** The 38 picks' numbers were fitted on the same select window (2021-2023) and then kept
because they were positive on the same test window (2024-01 .. 2026-09) and on 2020 (`research/fullgrid/WATCH_PREREG.md`
0; `research/fullgrid/ANALYSIS_KO.md`, the 16 strategies "positive in both periods"). Their test result here would
not be out of sample on any coin set: the new 24 coins trade in the same 2024-2026 market, move with the old six, and
the DeepSeek picks read BTC context. A leaked p-value would also loosen Benjamini-Hochberg for the other picks. So F4
systems are run in the select period (in the select table, labelled "read only: numbers chosen after the test period
was seen") and nowhere else; the forward candidate league already tests these numbers honestly. The picks, the BH
family and WIDE PASS come from F1-F3 only.

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
* **This differs from the design brief**, which took an entry on every bar where an array fires and the first bar only
  for arrays that are states. Kept on purpose (section 15 Q11): (i) control (a) draws, per coin and side, as many
  random bars as the pick has gated signals (H 12); counting the continuation bars of a run as signals would give the
  random control more entries than the pick can take (continuation bars mostly fall while the pick already holds that
  coin), most for the arrays with many continuation bars; (ii) one rule for all families, the rule v1 uses. What it
  costs: on the old six's real bars (parity check, section 8, signals only) the share of True bars that continue a run
  is 0 in 216 of the 353 F2-F4 cells, about 0.85 for N17_KC_RSI and 0.66 for N18_VWMA_MACD (states), and 0.06-0.40 for
  the mixed ones (F4_PULL about 0.31, F14_SMT and F2_DEMARK about 0.28, the F5_BOX family 0.12-0.23 (0.40 for the F4
  F5_BOX 4h pick), V45_AMB about 0.17, N19_FIB_CHOP about 0.11, OBV_S 0.06-0.09); those continuation bars are not
  entries.
* **The edge is taken before the gate** (as in v1, where H 5 defines the event and H 6 gates it). Under G1 a run of True
  bars that starts on a bar that is not 추세장 gives no entry, even when later bars of the run are 추세장; likewise a run
  whose first bar is lost to a cap, a coin that holds a position, a missing fill bar or a missing ATR gives no entry
  later in the run.
* This differs on purpose from the full grid, where every True bar was a separate trade (full grid PREREG 5).
* An event also needs ATR14 of the signal bar (D0, H 4). A bar with **both** a long and a short event on the same coin
  gives no entry (counted as "both sides", section 15 Q3).
* H 8 unchanged: an event on a coin that holds a position (either side) is ignored; several gated signals at the same
  close are taken by 30-day quote volume.

### 3.3 F5: the famous trend rules as events (`entries_wide.famous_raw`)

The rules of `research/famous/famous.py`, which ran on daily bars of the old six, are applied on each system's own
bars (15m, 30m, 1h, 4h, built as H 4). **Every length in days becomes days x bars per day of the timeframe** (96 on
15m, 48 on 30m, 24 on 1h, 6 on 4h), counted in bars of the coin's series (a bin with no 5m bar is no bar, so a gap
makes a lookback longer in time, as for every other entry).

* **TURTLE20 / TURTLE55** (`famous.donchian(d, n, m)` with n / m = 20 / 10 and 55 / 20 days): channels = the highest
  high and lowest low of the n (entry) and m (exit) bars before bar t (t excluded). The position (-1, 0, +1) is updated
  at each bar's close, in famous.py's order: a long exits when close < the m-bar low (a short when close > the m-bar
  high); then a flat or short position goes long when close > the n-bar high, else a flat or long one goes short when
  close < the n-bar low. Defined once both channels exist.
* **TSMOM7 / TSMOM28** (`famous.tsmom(d, lb)` with lb = 7 and 28 days): at each weekly rebalance bar, the bar whose
  close is Monday 00:00 UTC (the close of the UTC Sunday, famous.py's `weekly_mask` on daily bars), the position
  becomes sign(close[t] / close[t - lb bars] - 1) (0 when equal) and is held to the next rebalance; a rebalance with no
  defined return keeps the previous position (famous.py's forward fill); defined from the first rebalance with a
  defined return. A missing rebalance bar keeps the position one more week. On a gap-free series the decision moments
  and the sign are therefore the same on all four timeframes; the four F5 timeframes of one TSMOM rule differ in the
  stop, the chandelier and the gate label of their timeframe.
* **Event** (H 5 / 3.2): a long (short) event on bar t = the position is +1 (-1) on t and was not on t-1, with the
  position defined on both t and t-1. The rule's own exits only end a state, so a new event can follow; the hunt
  machine (H 7) exits the trade. A flip from long to short in one bar is a short event. No 300-bar warm-up (that is the
  full grid's convention for F2-F4); the definedness rule replaces it.
* Tested on synthetic bars only: the states equal famous.py's `donchian` and `tsmom` on daily bars, the events are the
  first bars of each state, TSMOM events fall only on Monday 00:00 closes, and no event changes when later bars change
  (`tests/test_hunt_entries.py`). F5 is new code, so it has no full-grid parity check (section 8).
* **Label (as F4's):** research/famous results of these rules on the old six (daily bars, 2021-2026) have been read by
  the owners and the main session; the new-24 read is shown next to any F5 pick (`note` in picks.json).

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
| F4 (select read only) | 38 picks (16 strategy names) | 38 | 2 | 76 |
| F5 | 4 | 4 x 4 = 16 | 2 | 32 |
| **total** | | **381** | | **762** (686 candidates F1-F3 + F5; 76 F4 reads) |

The brief counted (3 + 36 + 44) x 4 x 2 + 38 x 2 = 740; the generating rule above gives **730** before F5 because the
five session definitions have no 4h version (section 15 Q1); F5 adds 32. Of the 762, the **686 F1-F3 and F5 systems
are the candidates** for the picks; the 76 F4 systems are run in the select period as a read only (section 3). Tries
per strategy name stay 8 (6 for the five session names); no exit, stop-width, pyramid-depth, gate or size variant is a
system (they are reads, section 7).

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
**F5 names**: TURTLE20 TURTLE55 TSMOM7 TSMOM28.

**Strategy name** (for the one-per-name rule of section 5): E1, E2, E3 for F1; the core or DeepSeek name for F2-F3;
the F5 name. Distinct names among the candidates: 87.

## 5. Selection (W5)

* Period: **select 2021-01-01 .. 2024-01-01** by signal-bar close (H 11). The select step uses no 5m bar that opens at
  or after 2024-01-01 00:00 UTC: each coin's npz columns are decompressed whole (their content hash is checked, H 2)
  and cut at 2024-01-01 before anything else uses them, and of the manifest only what lies before that date is carried
  (a coin end or a missing funding month after it is not, so `select.json` holds nothing about 2024 or later). Positions
  still open at the end are marked at the last 5m close (H 10).
* Runs: every one of the 762 systems, **r = 0.5%**, one account (H 10: $5,000, compounding) at base costs and one at
  cost x2 (H 9). No neighbours and no plateau (H 11.1-11.2 do not apply). Each row of the select table carries the H 10
  metric set of its base run (the per-year, per-side and per-group splits and the 36 monthly ln M included; the daily
  equity path is kept for test runs only) and the cost x2 summary with its 36 monthly ln M (R4); DeepSeek rows as
  section 11.
* **Eligible** = all of: at least **72 positions**; mean monthly ln M **> 0**; **no bust**; mean monthly ln M at cost x2
  **> 0**.
* **Score** = mean monthly ln M of the base-cost run (36 months).
* **Order**: score, highest first. Ties: higher median monthly multiple; then family F1 < F2 < F3 < F4 < F5; then
  name (ASCII); then timeframe 15m < 30m < 1h < 4h; then G1 before NONE; then (F4) lower watch rank.
* **Picks and batches** (owners (b)): walk down the ordered eligible **F1-F3 and F5** systems and take a system when no
  system of the same strategy name is taken yet, until **30 names** are taken. So at most one system per strategy name
  (its best timeframe / gate). Positions 1-10 are **batch 1 (1군)**, 11-20 **batch 2 (2군)**, 21-30 **batch 3
  (3군)**; with fewer eligible names a batch holds what exists (K of a batch = its size). F4 rows are never taken
  (section 3), whatever their score. **Membership of every batch is fixed here**, before any test bar is read;
  batches are never re-ordered after a test result.
* **No eligible system**: the wide study fails at selection. As in H 11.2, the single highest-scoring F1-F3 system
  (eligibility ignored) is still run on the test period with its reads (section 7), labelled "no pick, fail"; no other
  system is.
* `research/hunt/out/wide/picks.json` (each pick's system id, family, name, timeframe, gate, numbers, pick number 1..n
  and batch number; the batches as lists of pick numbers; the batch size 10, the trigger 5 and the batch rule) is
  written, and its sha256 appended to `PREREG_HUNT_WIDE.sha256`, **before any test-period bar is read**. The test step
  refuses to start without that line, and the picks and batches do not change after it.

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
  **P1** median monthly multiple >= 1.0 and mean monthly ln M > 0; **P3** cost x2 median monthly multiple >= 1.0 and
  cost x2 mean monthly ln M > 0; **P4** max drawdown < 50%.
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
* Long steps resume: each finished entry cell of select and each finished pick of test is written to the private
  folder (outside the repository) under the pin's hash; a rerun under the same pin computes only what is missing and
  gives the same result (section 10).

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
* **Sizing read** for each passing pick and for the basket: **r = 2% and r = 5%**, the total open risk cap **and the
  margin budget** scaled by r / 0.5% (risk cap 16% / 40%; B = equity / 6 x 4 at 2%, x 10 at 5%), leverage as H 7.3
  (the smallest L meeting the bracket, the budget and liquidation >= 1.5 x D0, at most 20x), the free wallet still
  limiting every fill (cuts and skipped adds counted), everything else as here. With B unchanged the read would not
  take the bet it names: at r = 5% and D0 = 1% of the price the first unit was cut to about 0.8% of equity and no add
  found room (review, section 16.2). Even scaled, the brackets, the 20x cap and the wallet cut a tight-stop unit, so
  next to every figure the read reports **the bet actually taken**: the median (and quartiles) of the first unit's
  realized risk q x D0 / equity at entry, the share of first units cut (by liquidity, margin budget, free wallet) and
  the share of tried adds that filled. Reported: the **share of test months with M >= 2, >= 10 and >= 30**, the
  **worst month**, **bust** (and its month), and the full H 10 metric set. This is the honest answer to the owners'
  goal ($1,000 -> $30,000-50,000 fast, x30-x50): it shows how often a larger bet gave such months and how often it went
  bust, on data the choice never saw. It is not a pass and not a paper account (section 15 Q9).
* Also reported, never a pass: the controls in the select period for each pick; the gate diagnostics of H 14 for each
  pick **in the select period only** (the pick's entry and timeframe under the other gate is another of the 730
  systems, so section 6 keeps it off the test period; v1 keeps H 14 as written); the select table of all 730 systems
  (section 11 for DeepSeek rows); the count of "both sides" bars.
* In the "no pick, fail" case the one system's reads run as a pick's (they are that system at another size, universe
  or period, never another system); there is no sizing read or basket (no pick passes).

## 8. Parity (W8): the entries equal the full grid's, before the pin

* Coins: the old six (BTCUSDT ETHUSDT SOLUSDT DOGEUSDT LTCUSDT BCHUSDT). Systems' entries: every F2 and F3 strategy on
  every timeframe it has (144 + 171 = 315 cells) and the 38 F4 picks. **Signals only; no position, fill or outcome is
  computed.**
* Reference: the full grid's own path, `run.build_frame` on the full grid's 1m archive (`<fg1m>/1m/<SYM>.npz`)
  followed by the same calls as section 3.1. Adapter: section 3.1 on the 5m arrays of the hunt data, read exactly as
  select and test read them (H 2: duplicate, zero-volume, off-grid and non-finite rows dropped; the dropped counts are
  reported per coin), so the parity checks the bars the run computes its signals on.
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
* Output: `research/hunt/out/wide/parity.json` (counts and shares only), part of the pin (section 10). It records the
  sha256 of `entries_wide.py`, `parity_wide.py` and `hunt.py` it ran under; the pin check refuses unless it says pass,
  was run on the hunt 5m files (`--five`) on the old six, and its recorded code equals the pinned files.
* A first run on the full grid's 1m archive binned to 5m (the adapter alone, 2026-10-11, signals only) gave 348 of 353
  cells identical and 11 differing bars in 5 cells (F6_VWAP_CROSS 15m / 30m / 1h, F6_VWAP_FAIL 30m / 1h; at most
  0.011%): a last-bit difference in the daily VWAP's volume sum flips an exact `>=` tie. The pinned run is the one on
  the hunt files.

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
* `PREREG_HUNT_WIDE.sha256` lists exactly what `python -m research.hunt.hunt pinlist --study wide` prints: this file;
  `PREREG_HUNT.md`; `research/hunt/universe30.json`, `data_manifest.json` and `data_check.json` (H 2), the data builder
  `research/hunt/data_hunt.py` and every file under `research/hunt/data_build/` when they exist; `research/hunt/exchange30.json` when it exists (H 7.3); every
  Python file under `research/hunt/` that the command imports; the hunt tests under `tests/`;
  `research/hunt/out/wide/parity.json`; as read-only inputs checked by hash, `research/fullgrid/diag/watch_sel.json`,
  `research/fullgrid/PREREG.sha256` (whose own list must match), `research/entry_study/DEFS_BC.sha256` and
  `third_party/sweep/PREREG.sha256`; and **every repository Python file the signal code loads**, found by running each
  of the 365 entry cells once on a short synthetic series and listing the loaded modules (among them
  `research/deepseek200/lib_c.py`, whose helpers every DeepSeek definition calls, `research/fullgrid/memo.py`, which
  wraps the core definitions' indicators, `paperbot/dash/tools/regime5y.py`, `paperbot/sweepsig.py`, the vendored
  indicator code under `third_party/sweep/`, the 36 core definitions, and the paper-bot modules they import, read only).
  `select` and `test` repeat the scan and refuse a file that is not listed. Later, the picks line. Because rule-bot
  files are on that list, select and test run from one fixed checkout (a separate worktree at the pinned commit), so
  rule-bot commits made between the two steps do not stop the test.
* Outputs: `research/hunt/out/wide/` (select.json, picks.json, test.json with the reads inside it, parity.json and a
  Korean results page), each stamped with the git commit and the sha256 of the pin file it ran under, and with the
  content hash of every coin's data it read (H 2).
* Compute: systems are independent, so select splits by entry cell and test by pick x control seed; `--procs N` sets
  the worker count (at most 2 on the development machine; any number on a rented server). Results do not depend on N:
  seeds depend only on the parts written in section 6. No absolute path is written in the code. Progress is printed
  every minute. A worker that dies (out of memory, killed) is replaced and only its unfinished items are sent again
  (with fewer workers; after five rebuilds the step stops with a message instead of hanging). Finished entry cells
  (select) and picks (test) are kept under the private folder and reused by a rerun under the same pin.
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
  the old six, including 2024-2026, have been read by the owners and the main session. The default numbers were not
  chosen on that period, but what was seen can steer later choices; the new-24 read is shown next to every pick. It
  does not make a result clean: the new 24 coins trade in the same 2024-2026 market and move with the old six.
* **The 38 F4 picks were chosen after the full grid's test period and 2020 were seen** (WATCH_PREREG 0): their test here
  would be out of sample on no coin set, which is why F4 is a select-period read only (section 3).
* **Winner's curse.** The best of 730 select runs looks better on 2021-2023 than it is. Only the single test, the
  controls and BH over K speak to that.
* **Power.** 33 test months and BH over up to ten picks: a real but small edge may not pass.
* The universe is a 2026 list (H 3, H 18 Q2). The strategies were written for the old six; DeepSeek definitions that
  read BTC context get BTCUSDT's bars on every coin.
* The edge rule (3.2) makes state and mixed strategies enter less often than the full grid counted them, and under G1
  a run that starts outside 추세장 gives no entry.
* On 15m and 30m the first stop and the chandelier are tight relative to costs (5m fills, taker fees); this is part of
  what is tested, not a reason to change the costs.
* **Pyramiding is margin-limited on tight stops and in larger accounts (H 7.3 as written).** The leverage H 7.3 (ii)
  asks for is N4 / B = 24 x r / (D0 / P0), with N4 = 4 x q x P0 taken at P0, while the adds fill higher (long). With the
  fallback brackets at r = 0.5% and a $5,000 wallet: D0 / P0 = 0.3% leaves no room for any add (L = 10, the first unit
  is already cut to the budget); 0.5% leaves room for about 2.3 of the 3 adds (L = 20); 1% leaves 2.97, so the third
  add is cut. Whenever 0.12 / (D0 / P0) is a whole number of at most 20 (D0 = 1%, 2%, 4% of the price ...), L uses B
  exactly and the third add is always cut, so the "full units" stops of H 7.4 (P0 + 0.667 D0, P0 + 1.25 D0) do not hold
  exactly. Tight stops are typical of the new 15m and 30m systems, so selection compares timeframes under this
  asymmetry. N4 / B does not depend on the equity, but the bracket of N4 does: a compounding account crosses the
  $25,000 / $100,000 / $250,000 tiers and loses adds as it grows. Counted per run (adds skipped and cut by margin);
  a real bracket table (`exchange30.json`) changes the numbers; computing N4 at the planned add levels is section 15
  Q14.

## 14. Not in this study

Numbers other than the defaults and the 38 watch picks' numbers; combining entries inside one system (the basket is a
read); exits other than the chandelier; r above 0.5% as the rule; gates other than G1 and NONE; the AI judgment layer
(H 17); timeframes other than 15m, 30m, 1h, 4h.

## 15. Open questions (closed before the pin; default in brackets)

1. **730, not 740.** The five ET-session DeepSeek definitions exist only on 15m/30m/1h (`ds_defs.TFS_OF`); running them
   on 4h would use code the full grid never ran and cannot be parity-checked. [730; no 4h for those five]
2. **F4 is not out of sample on any coin set** (section 3, 13): the new 24 share the 2024-2026 market. [Closed in
   review: F4 is a select-period read only, never a pick, never in the BH family or WIDE PASS. The alternative of the
   draft (F4 eligible, labelled) is rejected because a leaked p would also loosen BH for the other picks. For F1-F3
   picks: "carried by the old six" stays a label, not a condition]
3. **Long and short event on the same bar and coin.** [No entry; counted]
4. **Mark price.** The new 5m files hold mark-price columns, but H 2 and H 7.6 check liquidation on last price and this
   study keeps the machine identical to v1. [Last price, as H 2; mark columns unread]
5. **K = 10, one per name.** [Keep]
6. **72 positions in 36 months** may exclude many 4h G1 systems. [Keep; the gate is not changed for it]
7. **Score = mean ln M**; the median is only a tie-break here (v1 uses a median-based plateau). [Keep]
8. **Sizing read**: with B = equity / 6 a 5% unit is cut to about 1% or less and loses its adds, so the read would not
   show what a 5% bet does. [B scaled with r (section 7); 20x cap and brackets unchanged; the realized unit risk, cut
   and add shares reported next to every figure. Alternative: B unchanged, the read labelled "requested 2% / 5%, taken
   about X%"]
9. **Paper accounts at 2% or 5%.** [None; the owners decide after reading the sizing read, labelled as such]
10. **Where it runs.** [The development machine at 2 processes if the measured time allows; otherwise a rented server
    started by the owners, same commit and pin]
11. **State arrays and the edge rule** (3.2). The design brief took every firing bar and the first bar only for state
    arrays; this addendum takes the first bar of every run for every family (reasons and costs in 3.2). [Edge rule for
    every family, taken before the gate. Alternative: the brief's rule with the state list fixed before the pin from
    the parity reference (N17_KC_RSI and N18_VWMA_MACD, pooled continuation share >= 0.5; next highest F4_PULL 0.31),
    accepting that control (a) then draws more random entries than the pick can take for the mixed arrays]
12. **A strategy x timeframe failing parity** after a fix attempt. [Removed before the pin, recorded here]
13. **No eligible system.** [As v1: the top F1-F3 system runs once with its reads, labelled "no pick, fail"]
14. **N4 at the planned add levels** (section 13). H 7.3 takes the planned full notional at P0 (N4 = 4 x q x P0), so
    the third add is often cut. Alternative for both studies, a change of H 7.3 before the pin: N4 = q x (4 x P0 + 6 x
    D0) for a long (the four planned fills P0, P0 + D0, P0 + 2 D0, P0 + 3 D0; short: 4 x P0 - 6 x D0) and the same in
    the per-unit budget check. [H 7.3 as written; the margin-limited adds counted and reported]
15. **Rule-bot files in the pin** (section 10). The signal code imports paper-bot modules, so they are hashed. [Run
    select and test from one fixed checkout of the pinned commit]

## 16. Before this file was fixed

### 16.1 At the first draft (2026-10-11)

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

### 16.2 Review before the pin (2026-10-11, KST evening)

Done after the code of section 10 had been drafted and tested on synthetic bars, and after the parity check of section
8 had run on the full grid's 1m archive (signals only). No select or test of either hunt study had run; no trading
outcome had been computed on any real price period; no 5m price of the 30 coins was opened for this review (the
download was still running). The reviewers read the code, this file, `PREREG_HUNT.md`, the full grid's watch-list
files and `manifest.json`'s coverage fields, and ran synthetic cases. Changes:

1. **F4 is a select-period read only** (sections 1, 3, 4, 5, 6, 13, Q2): the watch picks' numbers were kept because of
   this very test period and 2020; the picks, the BH family and WIDE PASS come from F1-F3.
2. **The sizing read takes the bet it names** (section 7, Q8): the margin budget is scaled with r, and the bet
   actually taken (realized unit risk, cut and add shares) is reported with the full H 10 set.
3. **Gate diagnostics in the select period only** for wide (section 7): the other gate is a non-pick system.
4. **3.2 states the deviation from the brief and the edge-before-gate effect** (Q11), with the continuation shares
   measured by the parity check.
5. **H 2 implemented as written**: the 5m-vs-1m cross-check (`datacheck` -> `data_check.json`), the data identity
   (`datapin` -> `data_manifest.json`, checked at every select and test), the 1 GB disk stop; select carries nothing
   of the manifest after its end, and missing funding months are those while the coin trades (section 5).
6. **The pin covers the whole signal path and checks the result files' content** (section 10): lib_c.py, memo.py,
   regime5y.py (now in the v1 pin too), the vendored code; parity.json must say pass on the hunt files under the
   pinned code; data_check.json must say pass for the pinned data.
7. **Parity reads the hunt files as the run does** (section 8: zero-volume and duplicate rows dropped).
8. **P3 includes mean ln M > 0 at cost x2** (section 6), as H 13 after its own review; the H 7.6 add-first order of H's
   review is in the code.
9. **Robust, resumable runs** (section 10): a dead worker no longer hangs a step; finished cells and picks are reused.
10. **Section 13**: pyramiding is margin-limited on tight stops and in larger accounts (with the arithmetic); Q14 (N4 at
    the planned add levels) and Q15 (one fixed checkout) added. Section 10's output list corrected (the reads are in
    test.json).

