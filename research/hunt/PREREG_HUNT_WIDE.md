# Trend hunt wide (추세 사냥, 넓게): pre-registration addendum to PREREG_HUNT.md

(한국어 설명: `README_WIDE_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. `PREREG_HUNT.md`(v1)는 그대로 두고, 그
기계에 넣는 진입 신호만 넓힙니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면 `DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (KST), before any code of either hunt study existed in the repository and before
any hunt selection or test was run; reviewed and corrected the same day before the pin (section 16.2), still before any
hunt selection or test; extended the same day with the owners' decisions (a)-(h) and the panel review of 23 reads
(section 0.1, section 16.3), still before any hunt selection or test and before any trading outcome on a real price
period; switched to float64 data the same day after the parity check failed on float32 ties (section 16.5).** The
open questions of section 15 are closed by the owners (or by the default written next to each) before the file is
pinned. Pinning = `PREREG_HUNT_WIDE.sha256` over this file, `PREREG_HUNT.md`
and the files of section 10; the code refuses the wide `select` and `test` steps without a matching pin. After the pin
nothing here changes; a change goes to `research/hunt/DEVIATIONS.md` with its reason and date.

Owners (2026-10-11), on the v1 draft with its three entries: **"왜 3가지 신호밖에 없어?"** and, the same day, "하 너무
복잡해 어떻게 해야 1달동안 성공의 매매법을 위해 제대로된 작업을 빠르게 할수 있다는거야? 결론이 뭐야". There is no good
reason to stop at three when about 80 strategies' entries are already coded and pinned. This addendum feeds **every
coded entry** into the same hunt machine, on four timeframes, with and without the gate, and tests its picks ten at a
time (at most thirty, in batches of ten: sections 5 and 6).
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
* **(i) 15m stays** (about 23:20 KST, after the loss autopsy recommended dropping it): the candidates are unchanged.
* **(j) "주말 뺀 버전이랑 주말 포함한 버전도 둘다"** (about 23:50 KST): the study is reported both with weekends (the
  tested machine) and without them, on all four timeframes, plus the autopsy's other machine-level options (7.4a).
* **Deferred to round 2 (not in this addendum):** new-information entries, the loss-autopsy noise filters, custom
  values (section 14: each its own pre-registered study, designed and selected on 2021-2023 only, confirmed once per
  version on the test period 2024-01-01 .. 2026-10-01, every look in the program-wide ledger, plus forward paper data
  counted from the day its pre-registration is hashed).

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
was seen") and nowhere else, not even in the sealed post-verdict read R22; the forward candidate league already tests
these numbers honestly. The picks, the BH family, WIDE PASS and the 'no pick, fail' system come from F1-F3 and F5 only
(the 686 candidate systems).

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
* **No eligible system**: the wide study fails at selection. As in H 11.2, the single highest-scoring F1-F3 or F5 system
  (eligibility ignored; F4 never) is still run on the test period with its reads (section 7), labelled "no pick, fail";
  no other system is.
* `research/hunt/out/wide/picks.json` (each pick's system id, family, name, timeframe, gate, numbers, pick number 1..n
  and batch number; the batches as lists of pick numbers; the batch size 10, the trigger 5 and the batch rule) is
  written, and its sha256 appended to `PREREG_HUNT_WIDE.sha256`, **before any test-period bar is read**. The test step
  refuses to start without that line, and the picks and batches do not change after it.

## 6. Test (W6)

* Period: **test 2024-01-01 .. 2026-10-01** (33 months), H 11. **Each tested pick runs once**, r = 0.5%, base costs,
  plus its cost x2 run. Systems that are not tested picks are never run on the test period (except the sealed R22 read
  after the verdict, below).
* **Batches** (owners (b)): batch 1 is tested. When **at least 5** of the picks of batch n PASS, batch n + 1 is tested
  the same way (its own controls, its own BH); otherwise no later batch is tested and its members are listed as
  "untested" (never run on test). Labels: 1군, 2군, 3군. With the 'no pick, fail' system (section 5) there is one
  batch of one and no later batch.
* **Controls** for each tested pick: (a) random times and (b) coin-flip sides, **1,000 seeds each, exactly H 12** (the
  pick's timeframe, gate, r and period; (a) draws per coin and side the pick's number of gated signals from bars with a
  known 장세 label and a defined ATR14, not gated; (b) the pick's gated signals with fair-coin sides). Seed = sha256 of
  ("hunt-wide", system id, control, period, r, seed number), the parts joined as the v1 code joins its seed parts.
  d_m = ln M_m(pick) - the mean over the 1,000 seeds, per control as H 12. (In the test period every coin is past its
  180-day label history and its 300-bar warm-up, so the (a) pool is the same set of bars for G1 and NONE picks.)
* **Per pick, as H 13:** **P0** at least 66 positions, a position open in at least 80% of the test months, no bust;
  **P1** median monthly multiple >= 1.0 and mean monthly ln M > 0; **P3** cost x2 median monthly multiple >= 1.0 and
  cost x2 mean monthly ln M > 0; **P4** max drawdown < 50%.
* **P2, split:** p_a and p_b = the one-sided month-block bootstrap p of mean d_m for control (a) and for (b), as H 13
  (10,000 resamples of the 33 months; p = (1 + resamples with mean d <= 0) / 10,001; seed as above with "boot" in place
  of the seed number). **p = max(p_a, p_b).** **Seed-rank part**, for (a) and for (b) separately: (1 + seeds whose mean
  monthly ln M >= the pick's) / 1,001 < 0.05.
* **Multiple testing, per batch**: Benjamini-Hochberg at **q = 0.10** over the K values of p of the batch (sort
  ascending p_(1) <= ... <= p_(K); k* = the largest k with p_(k) <= 0.10 x k / K; every pick with p <= p_(k*) is
  BH-significant; none if no such k). Every member stays in its batch's family whatever else it fails; a pick without a
  defined p (for example a bust before any full month) enters with p = 1. The program-level ledger (R13: a global BH at
  q = 0.10 and Holm at 0.05 over every test-period hypothesis of both studies) is printed beside the verdicts and
  changes none of them.
* **A pick PASSES** = P0, P1, P3, P4, both seed-rank parts, and a BH-significant p within its batch.
* **WIDE PASS** = at least one PASS in any tested batch.
* v1 runs unchanged and separately (H 11-13, its own pick and seeds). If v1's pick is also a wide pick, it is run in
  each study with that study's seeds; the two results are reported separately and neither counts for the other.
* Long steps resume: each finished entry cell of select and each finished pick of test is written to the private
  folder (outside the repository) under the pin's hash; a rerun under the same pin computes only what is missing and
  gives the same result (section 10).
* **Sealed post-verdict read (R22, panel amendment):** after `test.json` and the verdict are written and their sha256
  appended to the pin, every one of the **686 candidate systems** (F1-F3 and F5, untested batch members included;
  **never an F4 system**) runs once on test at base cost, and each pick's entry neighbours run on test, for R22. This is
  the single sealed exception to "systems that are not tested picks are never run on the test period". Per-system
  numbers go only to a sealed private file whose sha256 is in the repository; only R22's aggregates are public. No
  system that is not a pick can become a candidate, a paper account or the basis of a v2 from this read.
* **Paper lineup** (owners (g), written to `test.json` as `lineup` in the test step, labels only for DeepSeek): see
  section 12.

## 7. Reads (W7): reported, never a pass

### 7.0 Reads of the test step (for each tested pick unless stated; test period unless stated)

* **New 24 only**: the pick on the 24 new coins alone (same rules; large group = the top 10 of the 24), select and test.
  A passing pick with new-24 test mean ln M <= 0 is labelled **"carried by the old six"** (H 14).
* **Extra 2020** (H 11): r = 0.5% and r = 1%.
* **r = 1% line**: P0-P4 and both seed-rank parts at r = 1% (controls rerun at r = 1%, 1,000 seeds, seed parts as
  section 6 with r = 1%), shown as "1% also passes: yes / no"; and the **cost x2 line at r = 1%**.
* **One-wallet basket** of all passing picks (when at least two pass, any batches): one wallet, r = 0.5% per unit, H 8's
  caps shared by all of them (one position per coin across all picks, 6 positions, 3 / 3 in the large group, 4% total
  open risk). Same-close order: 30-day quote volume (H 8), then pick number. Select and test.
* The controls in the select period for each pick (**seeds 1-200**); the gate diagnostics of H 14 for each pick **in
  the select period only** (the pick's entry and timeframe under the other gate is another of the 762 systems, so
  section 6 keeps it off the test period; v1 keeps H 14 as written); the select table of all 762 systems (section 11
  for DeepSeek rows); the count of "both sides" bars.
* The sizing read of the first draft (r = 2% / 5%, passing picks only) is **replaced by the R1 goal board** (7.3),
  which covers every tested pick, both machines and fresh wallets.
* In the "no pick, fail" case the one system's reads run as a pick's (they are that system at another size, universe
  or period, never another system).

### 7.1 Read guard and read discipline (panel; also H 14)

1. Every read R1-R24 runs only on **ROWS**, after `picks.json` is hashed: every tested wide pick (pass or fail, every
   tested batch), the v1 pick (or v1's 'no pick, fail' system), the wide 'no pick, fail' system when that is what ran,
   the all-K basket of batch 1 (one wallet, H 8 caps shared, same-close order by 30-day quote volume then pick number,
   labelled "not a candidate") and the passing basket when >= 2 pass. Members of untested batches are never run on
   test. Nothing enters the select table, except the select-only R4 and the R5 machine map, which choose nothing.
   **Named exceptions** (each chooses nothing and is labelled): R4 (select runs of the 686 candidates; part (3)'s null
   picks run on test as controls, not systems, after the verdict), the R5 machine map (select only),
   R22 (the sealed post-verdict read: the 686 candidates, untested batch members included, and the picks' entry
   neighbours on test; never F4), R2 (d) (oracle entries, labelled HINDSIGHT CEILING) and R3 (hold baselines, not
   systems). F4 systems run nowhere but the select table (section 3).
2. Reads never change the picks, the batches, P0-P4, the seed-rank parts, p, BH, PASS, WIDE PASS or v1 PASS, the
   2군 / 3군 trigger, the R14 band, the lineup, or what goes to the paper bot. The code writes reads only after
   `test.json` and the verdict exist, to their own files (`out/<study>/reads_*.json`, `fidelity.json`), and refuses to
   write (ReadGuardError) when any file of the study's output folder or `picks.json` changed while a read ran.
3. Read names and parameters (windows, sizes, both machines, crash dates, cost multipliers, Y, seed subsets, the
   headline cell, the select-fixed size rule, the R14 band lengths) are written here before the pin. **Read code is
   hashed into the pin before any read output exists**: a reads module (`research/hunt/reads_a.py`, later ones alike)
   runs only when its file is listed in the pin file with a matching sha256, and each read output says whether that
   line predates `test.json` (`reads_line_predates_test_json`), judged against the reads lines in the pin at the
   **first** test start for these picks (kept once in the private folder, never overwritten; also in `test.json` as
   `reads_pinned_at_test`), so a line appended after an interrupted test had written any part is never called earlier.
   A fixed reads module is appended again; its older line stays in the pin and is reported as superseded (the read is
   then post hoc, rule 5); no other pinned file may be superseded.
4. One fixed risk sheet per row is printed, whatever it shows.
5. A read added after the test is seen goes to `DEVIATIONS.md`, marked post hoc.
6. Paper accounts at goal sizes exist only by the owners' explicit decision, labelled "goal-size paper, not tested"
   (Q9).
7. The research pass rules stay exactly as written.

**Named before the pin:**

* **HEADLINE CELL**: per row, the share of **test calendar months** in which a **fresh account (start $1,000) at
  goal-mode (machine B) r = 5% touched x5** (marked equity at any 5m close >= 5 x its start), with its Clopper-Pearson
  95% interval, beside the control (a) and (b) shares (calendar months pooled over seeds 1-1,000) and the bust share.
* **SIZE FIXED ON SELECT**: per row, the (machine, r) cell with the highest mean ln(window multiple) over select
  calendar months among the cells with bust share <= 5% (ties: lower r). Its test row is printed as "size fixed before
  the test". Any size read off the test board is labelled "forward-only evidence".
* **Seed subsets**: the pass uses seeds 1-1,000; each read uses the lowest-numbered subset named in it (1-200 or
  1-100; R1 rolling windows 1-100, or 1-50 when one 30-day window run takes more than 0.03 s, measured on synthetic bars
  before the run by `hunt.py benchwin` and written to `research/hunt/bench_window.json`, which counts only when it is
  listed in the pin with a matching sha256; without it the subset is 1-100. No read times a run on the study's data.
  Measured 2026-10-11: 0.0097 s per 30-day window, so seeds 1-100).
* **Goal reads report multiples** (owners (e)): x2, x5, x10, x20, x30, x50, x100 of the window's start.

### 7.2 Reads interface (code)

`research/hunt/hunt.py` builds one context (`reads_context`) and calls `run(ctx)` of each reads module after
`test.json` is written (`run_reads_hooks`; again later with `python -m research.hunt.hunt reads --study S`). The context
gives the ROWS, the tested picks with their lineup labels, the period bounds, the engine (`run(what, start, end, r,
cost, start_wallet, overrides, path="day"|"5m", close_end, d0_scale, syms)` -> metrics, 5m or daily marked equity,
peak, trades), the pinned control draws of any seed (`control_signals`, sliced per window, no new draw), the seed
subsets, the headline cell, the size rule, the live gate, and an output dict and a private dict. Engine read options
(off by default; at default parameters the engine is bit-identical to the reviewed one, a test checks a seeded case
against the reviewed code's digest): the per-5m equity path and peak, close-at-end, N4 = (1 + adds) x q x P0, the
goal-mode bracket rule, the rule bot's sizing with its tier walk and checks (R24), 1m bars and liquidation on mark
price (R19). The context also carries the pinned synthetic window timing (`window_seconds`, 7.1) and the judge's
per-call cost (`--judge-usd-per-call`, R15; recorded in the read, absent = counts only). The hook
writes the public output to `out/<study>/<module>.json` and the private one outside the repository (D11; a float under
a DeepSeek row in the public output is refused).

### 7.3 Phase A reads (computed right after the verdict on the fixed ROWS: `reads_a.py` and hunt.py)

* **R1 goal board** (`reads_a.py`). Rows: ROWS (7.1). Periods: test (headline), select (labelled "chosen here"), extra
  2020 (from the first day with a known 장세 label). Windows: (i) UTC calendar months (headline); (ii) rolling 30-day
  windows [d, d + 30 days), one per UTC start day d with d + 30 <= period end (975 in test, 1,066 in select, about 155
  in extra: labels start about 2020-06-29, after the 180-day 장세 history). Each window is a fresh account: **$1,000**,
  flat, only signals whose signal bar closes inside the window, indicators and labels from full history; the large group
  is the calendar month's (H 3), not recomputed at the window start; positions open at the window end are closed at the
  last 5m close with slippage and taker (headline) and also shown marked; bust = marked equity < $100 at any 5m close
  (the account stops). Sizes r = 0.5, 1, 2, 5, 10, 20%. **Machine A** (as written, panel): H 7-8, B = equity / 6,
  LEV_MAX 20, total open-risk cap 4% x r / 0.5% (so at higher r the margin budget and the brackets cut the unit; the
  realised risk is printed next to the nominal r). **Machine B** (goal-mode, r >= 5% only, caps of PREREG_ALTPUMP 7):
  cap = min(4r, 60%), n_max = floor(cap / r) (5% -> 20% and 4 positions; 10% -> 40% and 4; 20% -> 60% and 3) as the
  position cap and the margin divisor, leverage up to the coin's bracket maximum (fallback 20), H 7.3 (iii) kept, the
  bracket looked up at the first unit's notional q x P0, an add past that tier's cap skipped and counted "bracket";
  labelled "goal-mode machine, not the tested machine". Columns per (row, period, window set, machine, r): share of
  windows ending >= x2, x5, x10, x20, x30, x50, x100; share touching each level at any 5m close; bust share; median,
  worst and best window; median days to the first touch of x2 and of x5; median give-back (peak - end) / peak among
  windows that touched x5; median number of positions that made 80% of the gain in windows ending >= x5; realised risk:
  effective r = r x median(q1 x D0 / U), p90 of q1 x D0 / U, share of first units cut by reason, share of positions
  filling add 1, 2 and 3, median leverage (max gross notional / equity is not computed in Phase A: R10). Honesty:
  calendar shares with exact Clopper-Pearson 95% intervals (0 of 33 still allows up to 10.6%); rolling shares with a
  moving-block bootstrap 90% CI (blocks of 30 start days, 2,000 resamples, seed parts (tag, "goalboard", row, period,
  machine, r, "boot")) and the line "overlapping windows: about 33 (test) / 36 (select) independent months". Controls on
  the same board: (a) and (b) through the same machine on the pinned W 6 draws (full-period sets sliced per window, no
  new draw; extra 2020 has no W 6 draws, so its controls are drawn over the extra period with the W 6 seed parts and
  period "extra"); calendar months pooled over seeds 1-1,000, rolling windows seeds 1-100 (1-50 under the 0.03 s rule);
  per cell the pick's share, the pooled control share, the 5-95% range of per-seed shares, and pick minus control with a
  block-bootstrap 90% CI. Altpump's coin-flip goal-50x baseline (about 1% of months) is quoted for scale. The touch
  columns are descriptive and create no stop-at-target rule.
* **R24 leverage read** (owners (f), `reads_a.py`, engine `PR_FIXLEV`): the R1 board at **L = 20, 30, 40** with the
  rule bot's sizing (`paperbot/sizing.py`, v3 quality tiers, `paperbot/config.py`), checked by the engine at each entry
  on the planned unit at the equity of the previous 5m close (one sequential run per window): the candidates are L,
  then each lower tier down to 20x (40: 40, 30, 20; 30: 30, 20; 20: 20); for a candidate L', margin = L'% of equity
  and notional = L' x margin, isolated; it is taken when (1) the bracket allows L' at that notional, (2) the first stop
  lies inside the liquidation price by at least max(0.2% of the fill, 1 ATR14) and (3) the loss at the first stop, fill
  and exit slippage and taker both ways, is at most 15% of equity; the first candidate that passes is used, else the
  entry is skipped and counted by the lowest tier's reason (bracket, liquidation buffer, loss). A larger L's candidates
  include the smaller one's, so the leverage used never falls as L rises. The liquidity and free-wallet cuts after the
  check keep L. No adds, no open-risk cap, at most floor(100 / L) positions, the hunt stop and chandelier.
  Reported: liquidations, skips by reason, the leverage used, and the wallet loss per first stop over the row's test
  signals, both at L itself (capped at the isolated margin plus fees; the share of stops beyond the liquidation price
  shown) and under the rule bot's walk at a fresh $1,000. Controls (a) / (b): calendar months seeds 1-100; rolling
  windows the R1 subset (1-100, or 1-50 under the 0.03 s rule). Labelled "rule-bot sizing read, not the tested
  machine". On a coin without real brackets (the fallback table: 20x up to $25,000) 30x and 40x are never allowed, so
  those cells run at 20x, and no tier passes once 20x needs more than $25,000 (equity above $6,250).
* **Continuous-account reads** (owners, `reads_a.py`): best trough-to-peak run-up inside any 30 days and its dates,
  geometric mean monthly return, whole-period multiple, max drawdown and the longest time to recover, at r = 0.5% and
  1% (the tested $5,000 accounts) and at the size fixed on select (fresh $1,000).
* **R12 / R13 basics** (`reads_a.py`): profit share of the top 10% of positions, of positions >= 10R and of the top
  month (largest monthly ln M / sum of monthly ln M); signal overlap (same coin and side within one bar of the longer
  timeframe), time overlap on 5m steps and the correlation of monthly ln M across the tested picks and the v1 pick.
* **R15 signal rate and burst size** (counts only, D11-safe; `reads_a.py`): for each pick and for the union of all
  tested picks plus the v1 pick, select and test: events per day, gated (G) and gate-blocked (N) counted separately
  (mean, p50, p95, max day); events at a single signal close (max, p99) and per hour (p99); the share of closes with
  more than 10, 20 and 30 events; events taken vs dropped by coin_has_position, six_positions, large_group_direction and
  risk_cap (the drops by reason as run totals: the engine counts skips per run, not per candidate; candidates and
  positions by month and year). Daily and monthly call counts x a per-call cost entered as a parameter
  (`--judge-usd-per-call`, recorded in the read; without it R15 reports counts only), compared with the owners' caps
  (commit ca7a302).
* **R19 1m + mark fidelity** (`hunt.py fidelity`, on the rented server's 1m set of the coins the tested picks traded,
  `data_hunt.py --kind fidelity`): every tested pick rerun with the same engine on 1m last-price bars and on 1m last +
  1m mark-price bars (liquidation checked on the mark bar; a stop the last price reaches while the liquidation price
  lies beyond it exits first), signals, ATR, labels and D0 from the study's 5m bars, coins without 1m bars on their 5m
  bars (flagged); also the median control (a) and (b) seed of each pick by mean ln M. Reported: the change from 5m to
  1m + mark in mean ln M, median M, end multiple, max drawdown, positions, liquidations and adds filled. The panel's
  extension (the R1 headline cell for every row, the tightest R5 cells, every 15m pick, next to R9's ambiguous-bar
  count) runs through the same 1m market in a reads module. The R1 headline numbers are called final only after this
  check.
* **R23 October 2026** (`hunt.py october --data-oct DIR`): before the pin, the data.binance.vision daily files for
  2026-10-01 .. 2026-10-10 of the 30 coins (5m klines and 5m mark-price klines) are listed with the sha256 of their
  bytes in `research/hunt/october_files.json` (`hunt.py octlist --data-oct DIR`: each zip checked against its
  `.CHECKSUM`, none opened), which `pinlist` then lists (2026-10-11: 560 of the 600 exist and are listed; the archive
  has no files for those days of the 5m klines of EOSUSDT, MATICUSDT and TOMOUSDT and the mark klines of TOMOUSDT);
  they are downloaded and checksummed only, never opened before
  `picks.json` and `test.json` exist. `october` refuses unless that list is in the pin with a matching sha256, and stops
  at any zip missing from the list, differing from it or without its `.CHECKSUM`. The loader puts them into the 5m npz
  layout (funding from daily files when present, else 0 and counted). Every tested pick
  and the v1 pick run on 2026-10-01 .. 2026-10-11 with all earlier bars as warm-up: fresh $1,000 at r = 0.5%; controls
  (a) and (b), seeds 1-200 drawn in that window (seed parts with period "october"); each 10-day multiple as a
  percentile of the test period's fresh-wallet rolling 10-day windows (one per start day). Printed: "the owners watched
  October live; no choice in either study used it; one 10-day draw cannot show an edge". It never swaps or re-ranks a
  pick; it is extended day by day until the paper bot starts and doubles as its replay check. (The R1 ladder in
  October runs in a reads module.)

### 7.3a Between `picks.json` and `test.json` (R4 select parts, R22 (2) select spike ratio)

R4 (1), (2), (4) and the select replicates of (3), and R22 (2)'s select spike ratio, read only select bars and choose
nothing. They are computed by their own pinned module after `picks.json` is hashed and **before `test.json` exists**,
written to `research/hunt/out/wide/pretest_reads.json` (DeepSeek rows as section 11), and that file's sha256 is appended
to the pin before the test step starts. The test step records in `test.json` (`pretest_reads`) whether that line was in
the pin, with a matching file, when the test started. If it was not (that module is not built when this is written),
these items are computed after the verdict, labelled **post hoc** and recorded in `DEVIATIONS.md`; the test step does
not wait for them and nothing of the verdict depends on them. R4 (3)'s runs of the null picks on the test period are
Phase B (after the verdict) in every case.

### 7.4 Phase B reads (computed after the verdict on the fixed ROWS by a separate module with its own pin line; they never choose anything)

Each reads (a) and (b) through the same changed machine on the pinned W 6 draws (R1 convention) unless stated; seeds as
named; DeepSeek rows per D11; old six and new 24 reported separately where a coin split is named.

* **R2 hindsight ceiling and monthly trend supply.** Every table labelled HINDSIGHT CEILING; never a pass, a system or
  an argument for a size. A single-position ride kernel = H 7.1-7.6 for one position alone (first stop, adds, the row
  timeframe's chandelier on 5m bars, costs, funding; no portfolio caps, no margin cuts) returning R = net P&L / U.
  (c) Oracle side: each gated signal of the row takes the side whose ride ends with more R, then the normal portfolio
  run. (d) Oracle time: per coin and calendar month, the single 1h signal close (ATR14 defined, no gate) and side whose
  ride gives the most R, truncated at the month end (closed at the last 5m close with exit costs); all 30 coins'
  oracle entries in one wallet with the normal caps. Trend supply per month: the best and 5th-best oracle ride R across
  the 30 coins and the number of coins with a ride >= 10R. The R1 board on calendar months only (test, select, extra)
  for (c) and (d) at every r on both machines, and per row the pick's headline share next to (d)'s. Fixed reading: if
  (d)'s headline share is itself small, the report says the machine, not the entry search, limits the goal.
* **R3 leveraged-hold baseline.** A simple hold path, not the engine, on R1's windows (calendar and rolling; test,
  select, extra), fresh $1,000: (i) BTCUSDT long and (ii) short, each at 2 / 3 / 5 / 10 / 20x isolated with the whole
  $1,000 as margin; (iii) equal-weight long of the window-start month's 10 large-group coins, $100 margin each, at
  3 / 5 / 10x; (iv) HINDSIGHT: the coin of the 30 with the best window return held long and the worst held short, at
  5 / 10x. Entry at the window's first 5m open with 0.02% slippage and 0.05% taker; liquidation on the 5m last-price
  low / high with the H 7.3 isolated formula and the bracket mmr at the entry notional (whole margin lost); funding as
  H 2; exit at the window's last 5m close with costs. R1's end and touch shares, liquidation share, median and worst
  window. Printed: "reference bets; the leverage with the best share is not advice".
* **R4 selection-luck calibration (select parts between `picks.json` and `test.json`, 7.3a; part (3)'s test runs
  after the verdict).** Changes nothing. Systems = the **686 candidates** (F1-F3 and F5); F4 rows are never part of
  (2)-(4) (section 3). (1) select.json stores each system's 36 monthly ln M at base cost and at cost x2 (DeepSeek rows
  in the private file). (2) CSCV / PBO: 12 blocks of 3 consecutive months, all 924 half / half splits; per split the
  OOS percentile of the IS-best system and the mean OOS percentile of the IS one-per-name top 10; PBO (share of splits
  with the IS-best below the OOS median) and the slope of OOS on IS score. (3) Null of the max: 200 replicates with
  control (a) twins and 200 with (b) twins (every candidate replaced by its twin: (a) random pool bars with the
  system's per-coin and per-side select gated-signal counts; (b) its gated signals with fair-coin sides); seed parts
  ("hunt-wide-null", system id, control, "select", "0.005", i); each twin at base cost and cost x2, then the exact W 5
  eligibility, order, one-per-name rule and K; null distributions of the 1st and 10th pick's score and of the number
  of eligible systems and names; each real pick's percentile against the null at its rank; deflated score = score -
  null mean at that rank; after the verdict, each replicate's null picks run once on test as controls (the mean
  select-to-test drop with no edge; this part reads test bars). (4) Goal-score check: every candidate's touch-x5 share
  of select calendar months at goal-mode r = 5% (machine B); its Spearman correlation with the W 5 score and how many
  of the official top 10 are in the goal-score top 10 (one per name). No goal-score list is ever run on test. Public
  numbers cover F1, F2 and F5 rows; the all-rows version is private (D11).
* **R5 machine sensitivity on the fixed picks (the six exit cells, owners (d)), plus a select-only machine map.** On
  ROWS, select and test, on the r = 0.5% continuous account and on R1 calendar months at goal-mode r = 5%. Cells:
  chandelier **2 / 3 / 4.5 ATR x adds 3 / 0** (the planned six; PR_CHAND and PR_NADDS); "off-virtual" at 3 ATR (no
  quantity added, but at each add level the stop moves exactly as if a full unit had filled there; virtual adds skip
  the risk-cap and margin checks); adds 5 at 3 ATR; D0 x0.75 and x1.5 of the timeframe's value (15m-1h: 1.5 and 3 ATR;
  4h: 1.125 and 2.25 ATR). Every cell's leverage uses N4 = (1 + adds) x q x P0. Controls seeds 1-200 through each
  cell's machine. Per cell: mean ln M, median M, pick minus control mean ln M with a month-block bootstrap 90% CI, end
  multiple, max drawdown, positions, adds per position, exit-source shares and the R1 headline columns.
  Decompositions: "on" minus "off-virtual" = what the pyramided size earned; "off-virtual" minus "off-plain" = what the
  tighter stop did. A row is "fragile" when the base cell is the only cell with pick minus control > 0. Machine map
  (select only, chooses nothing): all 762 systems at the six exit cells, base cost and cost x2; share eligible and median
  score per cell; Spearman correlation of scores between cells. An exit, stop-width or pyramid-depth variant can become
  the rule only through a v2 with its own forward test; the paper bot uses the base machine whatever this shows.
* **R6 extra controls.** 1,000 seeds each in test and 200 in select; seed parts as W 6 with control names "c", "d",
  "e"; per control mean d_m, its month-block bootstrap p ("boot" seed) and the seed rank; never a pass. (c) Gated
  random times (G1 rows; for NONE rows it equals (a)): per coin and side the row's number of gated signals, without
  replacement from the coin's (a)-pool bars labelled 추세장. (d) Coin shuffle: the row's gated signal times and sides,
  each signal's coin drawn uniformly from the coins with ATR14 > 0 on the same-timeframe bar closing then and a fill
  bar; D0 from the drawn coin; two draws of one coin at one close resolved by H 8. (e) Momentum-side random times: (a)'s
  draws with side = sign(close[t] - close[t - 20]) of the drawn bar (0 = no signal, counted). Shown beside (a) and (b).
* **R7 entry-vs-exit attribution ladder.** Per row, select and test. (1) Entry only: for every gated event the
  side-adjusted move from P0 to the close of signal bar j + h, h = 1, 2, 4, 8, 16, 32, 64, 128, 256, in D0 units, minus
  a round trip of 2 x (taker + slippage) x P0 / D0; MFE and MAE within h in D0 units (5m highs / lows); the same for
  controls (a), (b), (c), (e), seeds 1-200, with month-cluster bootstrap 90% CIs; no portfolio, no exit. (2) Exit swap
  in the hunt engine on the same events and caps: a fixed take-profit at 1R, 2R or 3R (PR_TP; the whole position exits
  at P0 +/- k x D0 with taker and slippage, the stop stays at D0, no adds, no chandelier, the stop first when both are
  touched in one 5m bar); the chandelier with no adds; the full machine; each with controls. (3) Old house exit, old six
  only: the row's gated events on the six coins fed to research/fullgrid/kernel.account (2 ATR stop, stepped lock,
  quality_v1 leverage, one position at a time, 1m + mark), select and test. (4) Machine-alone line: control (a)'s
  absolute mean ln M at base. One table per row: machine alone -> + timing (pick - a) -> + direction (pick - b) -> TP
  exits / chandelier no adds / full machine / old house exit. Any exit change taken from it is a v2.
* **R8 concentration ladder.** On the R1 board (calendar and rolling, test and select) at goal-mode r = 5% and 10%,
  open-risk cap fixed at the goal-mode value: n_max = 1, 2, 3, 4 with B = equity / n_max. Rows: each pick alone, the
  all-K basket, the passing basket, and the all-K basket restricted to BTCUSDT only, to the old six and to the new 24.
  At r = 0.5% on machine A: max positions 4, 8 and 10 with B_DIV = max positions, only for a pick that spent > 10% of
  test time at the six-position cap or lost > 10% of its gated signals to six_positions (else labelled "cap not
  binding"). Controls seeds 1-100. R1 columns plus the mean number of open positions on the days that made each window
  ending >= x5.
* **R9 cost, fill, mark-price and crash stress.** Per row at r = 0.5% and at the R1 headline cell, test and select, old
  six and new 24 separately. Costs: cost x3 (taker 0.15%, slippage 0.06%); taker x1.5 and x3 alone; funding x2 and x3
  alone; a best case at taker 0.045%; impact per fill: slippage = 0.02% + Y x sigma_d x sqrt(fill notional / the coin's
  mean daily quote volume over the previous 30 days), sigma_d = std of the previous 30 daily log returns, Y = 0.5 and
  1.0; cost x2 and x4 for every R1 cell reaching >= x20 in a test window. Cost anatomy: fees, slippage and funding as
  shares of gross price P&L; funding by side, by year and for the top 5 coins; the worst 30-day funding drain as a share
  of equity. Stop fills: 25% of the trigger 5m bar's range beyond the stop; worst case at the bar's low (long) / high
  (short); extra slippage +0.1 / +0.3 / +1.0% on stop and liquidation exits. Mark price: the 5m mark columns; liquidation
  on mark; separately, stops triggered on mark (workingType MARK_PRICE); also on control seeds 1-100. Losses: per-
  position loss in U (max; share beyond 1.25U, 2U, 3U); stop_gap_open count; worst portfolio 5m bar. Crash days (UTC,
  fixed from memory, not data): 2021-05-19, 2021-12-04, 2022-05-09..12, 2022-06-13, 2022-11-08..10, 2023-03-10..11,
  2024-04-13, 2024-08-05, 2025-02-03, 2025-04-07, 2025-10-10..11; plus, per period, the 10 hours with the largest
  absolute median 1h return of the 30 coins; per day / hour: positions open, P&L in U and in % of equity at each R1 r,
  liquidations, loss beyond 1U. Bust anatomy of every R1 bust window at r >= 2%: liquidation, stop gapped at the open,
  stop cluster (>= 3 positions stopped within 1 h), or funding. Entry timing: fills at the open of the 2nd and the 4th
  5m bar after the signal close. Ambiguous bars: 5m bars where the stop and an add level, or two add levels, were
  touched and settled by H 7.6. No trigger type, cost or date list is changed after the results are seen.
* **R10 exposure, margin and liquidation-distance ledger.** Engine aggregates at each 5m close with no effect on
  decisions (a test asserts equity and records bit-identical with the ledger on and off): open positions (max, time
  histogram 0..n_max); gross notional / equity (max, p95); net long and net short notional / equity (max); sum of
  isolated margins / equity (max); minimum free wallet / equity; minimum over open positions of liquidation distance /
  current stop distance; the instant loss if every open position gapped 5%, 10% or 20% through its stop at once (max as
  a share of equity, with its date). Per position: leverage distribution, fallback-leverage flag, bracket tier,
  realised first-unit risk / U. Every row at r = 0.5% and 1% and at the R1 sizes on both machines.
* **R11 position and month anatomy.** Engine: per-position running 5m MFE / MAE and each add's reference price and
  quantity (decision path bit-identical). Per position: MFE and MAE in R, exit R, give-back, 5m steps to +1R, holding
  time, costs in R, P&L of the first unit vs adds 1-3. Per row: winner / loser distributions, share of losers that never
  reached +1R, give-back of the top 10%, cost per position in R by timeframe, R percentiles, longest losing streak in
  positions and months, time in market, mean open risk, mean gross exposure. Splits: per coin, per half-year, large vs
  small group, the signal bar's 장세 label, BTC month state (monthly return tercile with select cut points; above or
  below its 200-day MA), add level reached, exit source. A month-level regression of ln M on BTC's monthly return,
  |BTC return| and the equal-weight 30-coin index return (alpha, betas, Newey-West t, 3 lags), with BTC-hold and
  equal-weight-hold rows scaled to the row's monthly volatility. Best and worst: 5 best and 5 worst calendar months and
  rolling windows at r = 0.5% and goal-mode r = 5% with the positions that made them, BTC's and the median coin's
  return, the control medians and p95 and R2's trend supply; "market months" = test months where at least half of the
  rows and the (a) median are in their own top quartile. Drawdowns from day_eq: longest underwater stretch, time to
  recover from the max drawdown, worst rolling 7 / 30 / 90-day multiple, most consecutive losing months, number of
  drawdowns deeper than 20%, 30%, 50%. Descriptive: any rule drawn from it is a v2.
* **R12 (beyond the Phase A basics) profit concentration and fragility.** Per row, select and test, r = 0.5%: mean ln M
  and median M after dropping the best 1, 2, 3 months; leave-one-coin-out re-simulations (30 runs) and a
  leave-best-coin-out run; re-runs with the signals of the best 1, 3, 5 positions removed; Herfindahl index of net P&L
  across coins and months; "fragile" when dropping the best month or coin flips the sign of mean ln M. Downtime: 5% and
  10% of gated signals dropped at random, 100 seeds each (seed parts ("hunt-wide", "drop", id, fraction, seed)).
  Alternative p-values for P2 beside the pinned p: stationary bootstrap (mean block 3 months, 10,000), sign-flip
  permutation of d_m (10,000), month-clustered bootstrap of position R-multiples. Labels only.
* **R13 (beyond the Phase A basics) pick overlap, BTC beta, effective number of bets, program ledger.** Daily and
  monthly correlation matrices (checks.py corr_daily), bad-day overlap on the worst 5% of days, each pick's beta to
  BTC's daily return and its mean ln M in BTC-up / flat / down month terciles (select cut points) with the long / short
  split, the effective number of independent picks (Li-Ji eigenvalue method on monthly ln M correlations). Program
  ledger: every test-period hypothesis of the program (the v1 pick, every tested batch, F5 picks, any read that prints a
  p, and every confirm look of a later round, section 14) with a global BH at q = 0.10 and Holm at 0.05, printed next
  to the pinned per-batch verdicts with the line that two studies share one test period. DeepSeek rows: labels and
  ranks only in public.
* **R14 forward band and golden ledger.** Computed once, right after the verdict, and never recomputed: its module is
  listed in the pin before `test.json` exists (read guard 3; a later line makes R14 post hoc) and its output's sha256 is
  appended to the pin before the paper bot starts or any forward comparison uses the band (the panel had R14 inside
  the test step; it is not built when this is written, so it is a separate pinned module with this order). For every
  passing pick, the v1 pick (H 15 allows a "v1 failed" shadow) and the passing basket: the 5 / 25 / 50 / 75 / 95
  percentiles of the multiple of fresh $5,000 accounts over rolling windows of 21, 25, 30, 40, 45 and 50 days (one
  start per UTC day in test), at r = 0.5% and 1%. The mid-November review (H 15, W 12 and live gate (f)) takes the
  forward record's multiple over its first N days from 2026-10-01 00:00 UTC, N = the longest of 40, 45 and 50 days
  the record has reached on the review date (to 2026-11-10, 11-15, 11-20), and compares it with the N-day band; the
  21-, 25- and 30-day bands serve a look at the record's first weeks the same way and decide nothing. Golden ledger:
  for each passing
  pick, every signal, fill, D0, stop path, add, exit and funding cash flow of the last 90 test days (the paper bot's
  parity reference).
* **R16 context split of the goal board.** For every R1 window, labels known at its start: BTCUSDT's previous-30-day
  return tercile; its 30-day realised volatility tercile; the share of the 30 coins whose 1h 장세 label at the start is
  추세장 (terciles); the mean funding rate of the 30 coins over the previous 3 days (terciles); cut points from select
  windows applied unchanged to test and extra; a hindsight label shown separately (BTC's return during the window).
  R1's end and touch shares for x2 and x5 and the bust share, pick vs (a) / (b) per bucket at r = 0.5% and goal-mode
  r = 5%, block-bootstrap CIs, select and test side by side. A bucket is a candidate signal only if it stands out in
  both periods; any sizing rule from it is a v2.
* **R17 capacity ladder.** Per row at r = 0.5% and goal-mode r = 5%, test and select: starting wallets $1k, $5k, $25k,
  $100k, $500k, each with the fixed 0.02% slippage and with R9's impact model at Y = 0.5 and 1.0: share of units cut by
  the 0.1%-of-volume cap, bracket tier reached, mean ln M, the R1 goal shares, the starting equity at which the median
  month falls to half its $5k value; in test windows reaching >= x20, the equity at which the first liquidity or
  bracket cut started to bind.
* **R18 real exchange rules.** Before the pin, `research/hunt/exchange30.json` from the paper server (H 18 Q3) and the
  public exchangeInfo of the 30 symbols (MIN_NOTIONAL, LOT_SIZE and MARKET_LOT_SIZE stepSize and maxQty). Read: every
  unit rounded down to stepSize, units under the real minimum notional rejected, market orders above MARKET_LOT_SIZE
  maxQty split (each part with its own slippage), at $1,000 and $100,000 starting wallets and the R1 sizes; per coin the
  rejected, rounded and split units and which coins use the fallback table. Label: "brackets and filters are 2026
  values applied to 2020-2026".
* **R20 extra gate diagnostics.** Per row, select and test, beside H 14's NONE and TS: G1-dir (추세장 and the sign of
  the 10-bar EMA50 slope equals the trade side, H 18 Q11), BTC-trend (BTCUSDT's own label on the same-timeframe bar
  closing at the signal close is 추세장) and not-횡보장; controls seeds 1-200 under each gate. No new selection gate; a
  gate adopted later is a v2.
* **R21 survivorship reads without new data.** Per row, select and test: (1) no entries in each coin's first 90 days
  after its first archived bar; (2) the 3 coins with the largest buy-and-hold multiple over 2021-01-01 .. 2026-10-01
  removed (hindsight sensitivity, labelled); (3) a point-in-time universe in which, each calendar month, only the 20 of
  the 30 coins with the largest previous-30-day quote volume can open positions. Mean ln M, median M, the R1 headline
  cell and pick minus (a) / (b). Labels only.
* **R22 sealed post-verdict read** (section 6 amendment). (1) Every one of the **686 candidate systems** (F1-F3 and
  F5, untested batch members included; **never an F4 system**: section 3) once on test at base cost (r = 0.5%,
  continuous account). Public, with the R4 rule for D11: the Spearman correlation of select vs test score and test mean
  ln M by select-score decile over the F1, F2 and F5 rows (all candidate rows private); the picks' percentile (a rank)
  among the candidate systems; and the count and share of systems with test mean ln M > 0 among select-eligible vs
  non-eligible candidates. Per-system test numbers only in a sealed private file whose sha256 is in the repository. (2)
  Entry neighbours: for each numeric parameter of each pick the next lower and next higher value from
  research/fullgrid/grid.values(), one at a time (F1: H 11.1's neighbours); in select, spike ratio = pick score /
  median neighbour score, written before the test per 7.3a (else post hoc); on test aggregates only. Nothing in this
  read can become a candidate, a paper account or the basis of a v2.

### 7.4a Owners' late additions after the loss autopsy (2026-10-11, about 23:20-23:50 KST, before the pin)

Reads only, in the Phase B module with its own pin line (7.4); none of them chooses a system or changes picks, P0-P4,
p, BH, PASS or the lineup. Source of O1-O5: `research/autopsy/LOSS_AUTOPSY.md` section 2.2 (select period only). The
owners kept 15m in the candidates (O6 of the autopsy declined) and asked that the study be analysed **both with and
without weekends, on all four timeframes**.

* **O1 weekend version.** Weekend = the signal bar closes (UTC) at or after Saturday 00:00 and before Monday 00:00. The
  fixed ROWS run through the same machine with every first-unit entry whose signal bar closes in the weekend skipped
  (counted as "weekend", not queued); adds, stops, chandelier and exits unchanged. All four timeframes (the autopsy saw
  no weekend effect at 4h and a slightly worse core 4h without weekends, so 4h is reported, not presumed). Reported
  beside the base (weekend included) with the same summary for each row: mean and median monthly ln M, win share,
  positions, max drawdown, cost x2 mean ln M, controls (a) / (b) seeds 1-200 drawn through the same changed machine
  (their weekend draws skipped the same way), pick-minus-control mean d_m, and the R1 headline shares (end and touch
  >= x2 and >= x5) at the size fixed on select; select and test side by side. **O1b**: the same with only longs skipped.
  Plus a select-period-only map: the section 5 walk rerun with the weekend-skip machine on select (what it would have
  picked); those systems are not run on test here; a later round confirms any such pick once (section 14, program
  ledger).
* **O2 macro blackout.** As O1, skipping first-unit entries whose signal bar closes in [T - 120 min, T] (the bar closing
  at T included), T = an FOMC statement time or a US nonfarm payrolls release time; variant: FOMC only. The official
  dates 2020-2026 (federalreserve.gov, bls.gov) are written to `research/hunt/macro_calendar.json` and its line is
  appended to the pin before the read runs (dates only; no outcome is read to make it).
* **O3 same-side risk cap and stress line.** As O1, with one more limit: an entry or add is taken only if the open risk
  of all positions on that side, across all coins, stays at or below half the total open-risk cap after it (machine A
  at r = 0.5%: 2% of equity; machine B: min(2r, 30%)). Stress line at every 5m close: the sum over same-side open
  positions of the loss to the current stop, plus a 5% and a 10% gap; its maximum as a share of equity, with the date.
* **O4 momentum control at the pick's own times.** (f) = the pick's gated signal times and coins with side = sign(close
  of the signal bar minus the close 20 bars before) (0: no entry, counted), through the same machine (one deterministic
  run). Reported: pick minus (f) monthly ln M and the share of the pick's sides equal to (f)'s. Pre-registered label: a
  pick whose test mean d_m against R6 (e) or against (f) is <= 0 is labelled "momentum only: a plain momentum entry did
  as well".
* **O5 label.** N17_KC_RSI rows carry "anti-momentum entry (select period; also on the 5-year anti-edge list, which saw
  test months)" in the select table; no flipped system is added.

Each of O1-O4 counts as one confirm look in the program-wide ledger (section 6); any of them becomes a rule only
through a later round with its own pre-registration (section 14).

### 7.5 Not added (panel, rejected; recorded so that none comes back after the results)

Exit variants as selection choices (762 -> 4,572 systems, 8 -> 48 tries per name; R5 answers it on the fixed picks); a
plateau score over chandelier widths as the W 5 score; a goal-scored shadow pick list run on test (R4 (4) shows the
question on select only); partial take-profit; time stop and breakeven move; 1-2 adds and other add spacings; a
slot-by-risk max-positions rule; flipped intrabar order as an optimistic bracket (R19 settles the 5m ambiguity, R9
counts it); stops and adds delayed one bar; risk-cap neighbours at r = 0.5%; a graveyard universe of delisted symbols
(R21 sizes the bias); OHLC spread estimators; a separate whole-wallet goal regime (R8's n_max = 1 rung); loosening any
pass rule toward goal metrics.

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
  sha256 of `entries_wide.py`, `parity_wide.py` and `hunt.py` it ran under and, per old-six coin, the H 2 content hash
  of the 5m file it read (`five_counts`); the pin check refuses unless it says pass, was run on the hunt 5m files
  (`--five`) on the old six with the content hashes of `data_manifest.json`, and its recorded code equals the pinned
  files.
* A first run on the full grid's 1m archive binned to 5m (the adapter alone, 2026-10-11, signals only) gave 348 of 353
  cells identical and 11 differing bars in 5 cells (F6_VWAP_CROSS 15m / 30m / 1h, F6_VWAP_FAIL 30m / 1h; at most
  0.011%): a last-bit difference in the daily VWAP's volume sum flips an exact `>=` tie. The pinned run is the one on
  the hunt files.
* A run on the hunt files as first built (float32 storage, and float32 coin arrays in `hunt.Coin`; 2026-10-11, signals
  only) **failed**: 19 strategy x timeframe cells above the 1% unexcused limit (worst N08_ICHI_WR 4h, 3.4%). Rounding
  to float32 flips exact ties in path-dependent indicators (PSAR, ADX / DMI, Klinger, DeMark, Ichimoku); bars binned in
  float64 from the full grid's 1m archive matched except the VWAP ties above. No mismatch was excused and no cell was
  dropped: the 5m files and the engine's coin arrays became float64 and the data was rebuilt from the archive before
  the pin (section 16.5); the pinned `parity.json` is the run on the float64 files.
* The run on the float64 hunt files (2026-10-11, signals only; the pinned `parity.json`) **passed**: 234 of 353 cells
  identical; the largest share F2:N19_FIB_CHOP 1h at 0.19%, all of it excused (bars where the 5m and 1m archives
  differ); the largest unexcused share F3:F14_SMT 30m at 0.07%. Unexcused differences are in 10 cells, each under
  0.1%: F14_SMT 15m / 30m / 1h (from 2023-11-10: it reads BTCUSDT's bars as context, and BTC's bars differ beyond
  tolerance that day, while the excuse window looks only at the traded coin's own bars), the VWAP ties above, and one
  volume-sum tie each in V45_AMB 15m and OBV_S r2 30m.
* F1 and F5 are this study's own code with no full-grid version: they are checked on synthetic bars (H 5 read bar by
  bar; famous.py's `donchian` and `tsmom` equality; no look-ahead), not by the parity run. `parity.json` records the
  sha256 of `entries_wide.py`, so it is rerun after the F5 addition.

## 9. Data (W9)

* The H 2 data of the 30 coins: per coin a 5m array file `<data>/5m/<SYM>.npz` with keys `ts` (int64 open time, ms) and
  `o h l c v qv mo mh ml mc` (**float64**; `v` base volume, `qv` quote volume, `m*` mark price), kept float64 in the
  engine's coin arrays (prices, volumes and mark OHLC; no float32 step anywhere, H 2 and section 16.5);
  funding in `<data>/funding/`; the universe from `<data>/UNIVERSE.md` and `manifest.json` (copied into
  `research/hunt/universe30.json` as H 3). The mark-price columns are not read by select or test (H 2: liquidation on
  last-price bars; section 15 Q4); only reads after the verdict read mark prices (R19 on 1m bars, R9 on 5m bars).
* After the verdict only: the 1m fidelity set (`<dir>/1m/<SYM>.npz`, same keys, `data_hunt.py download --kind
  fidelity`, the coins the tested picks traded; its content hashes are written into `fidelity.json`) and the October
  daily archive zips (R23; their sha256 listed in `research/hunt/october_files.json`, which is in the pin, before they
  are opened).
* The download is still running when this is written. No code waits on it: every path is given by `--data`, and a
  coin whose file is missing stops `select` and `test` (the universe is fixed) but not the tests on synthetic bars.
* Parity (section 8) also reads the full grid's 1m archive of the old six, given by its own path argument.
* Nothing of the price data is copied into the repository. Cached signal arrays, if any, live under the data or a
  scratch directory, never in the repository.

## 10. Code, command, pin, compute (W10)

* Command: `python -m research.hunt.hunt {select,test,report} --study {v1,wide} [--procs N] [--data DIR]`. `select`
  and `test` refuse to run unless the study's pin file (`PREREG_HUNT.sha256` for v1, `PREREG_HUNT_WIDE.sha256` for wide)
  matches every file it lists; `test` also needs the picks line (section 5). After the test: `reads --study S` (the
  reads hook again; a reads module runs only when its file is listed in the pin, 7.1), `fidelity --study S --data1m
  DIR` (R19; `--list-coins` prints the coins the tested picks traded, for the 1m download) and `october --study S
  --data-oct DIR` (R23). Each refuses before `test.json` exists and writes only its own output file. Before the pin:
  `octlist --data-oct DIR` (R23's file list) and `benchwin` (7.1's synthetic window timing).
* `PREREG_HUNT_WIDE.sha256` lists exactly what `python -m research.hunt.hunt pinlist --study wide` prints: this file;
  `PREREG_HUNT.md`; `research/hunt/universe30.json`, `data_manifest.json` and `data_check.json` (H 2), the data builder
  `research/hunt/data_hunt.py` and every file under `research/hunt/data_build/` when they exist;
  `research/hunt/exchange30.json` (H 7.3), `research/hunt/october_files.json` (R23) and
  `research/hunt/bench_window.json` (7.1) when they exist; every
  Python file under `research/hunt/` that the command imports; the hunt tests under `tests/`;
  `research/hunt/out/wide/parity.json`; as read-only inputs checked by hash, `research/fullgrid/diag/watch_sel.json`,
  `research/fullgrid/PREREG.sha256` (whose own list must match), `research/entry_study/DEFS_BC.sha256` and
  `third_party/sweep/PREREG.sha256`; and **every repository Python file the signal code loads**, found by running each
  of the 381 entry cells once on a short synthetic series and listing the loaded modules (among them
  `research/deepseek200/lib_c.py`, whose helpers every DeepSeek definition calls, `research/fullgrid/memo.py`, which
  wraps the core definitions' indicators, `paperbot/dash/tools/regime5y.py`, `paperbot/sweepsig.py`, the vendored
  indicator code under `third_party/sweep/`, the 36 core definitions, and the paper-bot modules they import, read only).
  `select` and `test` repeat the scan and refuse a file that is not listed. Later, the picks line. Because rule-bot
  files are on that list, select and test run from one fixed checkout (a separate worktree at the pinned commit), so
  rule-bot commits made between the two steps do not stop the test.
* Outputs: `research/hunt/out/wide/` (select.json, picks.json, test.json with the section 7.0 reads, the batches, the
  lineup and the live-gate spec inside it, the reads files `reads_a.json`, `fidelity.json`, `reads_october.json`,
  parity.json and a Korean results page), each stamped with the git commit and the sha256 of the pin file it ran under,
  and with the content hash of every coin's data it read (H 2).
* Compute: systems are independent, so select splits by entry cell and test by pick x control seed; `--procs N` sets
  the worker count (at most 2 on the development machine; any number on a rented server). Results do not depend on N:
  seeds depend only on the parts written in section 6. No absolute path is written in the code. Progress is printed
  every minute. A worker that dies (out of memory, killed) is replaced and only its unfinished items are sent again
  (with fewer workers; after five rebuilds the step stops with a message instead of hanging). Finished entry cells
  (select) and picks (test) are kept under the private folder and reused by a rerun under the same pin.
* Tests on synthetic bars only (the event edge rule, the F5 events against famous.py, the 15m/30m D0 and chandelier,
  the selection order, one-per-name rule and batches, BH per batch and the batch trigger, the lineup rule, the live
  gate, the size rule, the read guard and the D11 check of reads, the engine read options bit-identical at default
  parameters against the reviewed engine's digest, the 1m bar length, the daily-archive loader and its pinned list,
  R24's tier walk and checks against a Python mirror, the superseded reads line, the first-test-start record, refusal
  without a pin),
  in addition to v1's (H 16).
* Run time is measured on synthetic bars once the code exists and written in `DEVIATIONS.md` before the run; if select
  plus test would take more than about a day at 2 processes, the run goes to a rented server (section 15 Q10).
  Measured 2026-10-11 for the 1,000 seeds (synthetic, 30 coins, 33 months, shared 4-core machine): one control run
  0.15 s (4h) to 0.21 s (15m); 4,400 control runs per pick (2 x 1,000 at 0.5%, 2 x 1,000 at 1%, 2 x 200 in select),
  about 11-16 CPU-minutes per pick; a batch of 10 about 1.1-1.6 h at 2 processes here, about 5 minutes on 32 vCPU.

## 11. Reporting and DeepSeek money (D11)

* Core and F1 rows: every number of H 10 and sections 5-7.
* **DeepSeek rows (F3, and F4 picks of DeepSeek strategies) in repository files show counts, win shares, ranks / pick
  numbers and labels only** (eligible or not and which condition failed, picked, P0-P4 / seed-rank / BH pass or fail,
  PASS, bust yes / no, "carried by the old six"). Their other numbers (ln M, multiples, drawdowns, P&L, p-values, d_m)
  are written only to a file outside the repository whose sha256 is written in the repository output, so the selection
  and the test can be checked later without the figures being in the repository.
* Every result, pass or fail, goes into the results page and the owners' summary, next to v1's.
* Reads files follow the same rule: the hook writes a reads module's public output only when no float stands under a
  DeepSeek pick or a row containing one (except win shares); the figures go to the private file whose sha256 is in the
  public file.

## 12. What a result means, and after

| result | then |
|---|---|
| WIDE PASS | each passing pick (정식) goes to the **forward paper bot** (below) **beside the v1 pick**, exactly as here, r = 0.5% and r = 1%, $5,000 each; plus the one-wallet basket when two or more pass. Nothing else changed. **No real money before the mid-November 2026 review**; after it, real money is the owners' decision only, for 정식 picks only, after the forward criteria and the live-readiness gate below |
| a pick fails | recorded as a fail with its numbers (DeepSeek: labels). Not a candidate. It may run as a paper account labelled 참고 when it meets the lineup rule below; never real money |
| WIDE fail (no pick passes, or no eligible system) | recorded. **No tuning on the test period**; systems that are not picks are never run on it |

* **Paper lineup (owners (g)), computed in the test step and written to `test.json` as `lineup` (also for the v1 pick):**
  **정식** = research PASS. **참고** = a tested pick (not the "no pick, fail" system) with test mean monthly ln M > 0,
  median monthly multiple >= 1, mean d_m > 0 against both controls (its mean ln M above both controls' seed means), cost
  x2 mean ln M > 0, max drawdown < 50%, no bust, and its best month < 50% of the total log gain (sum of monthly ln M).
  Every other tested pick is **excluded** from the paper lineup (the failing conditions are listed). 참고 accounts are
  paper only and labelled; **real money only from 정식**, after the forward criteria (H 15: the replay reproduces the
  positions; the forward multiple inside the R14 band) and the live-readiness gate.
* **Forward paper bot** (`huntbot`, owners' guide `docs/huntbot-ko.md`; the same for both studies, H 15): it runs on its
  **own new server, `hunt-judge`**, not on the rule bot's paper server (public Binance prices only; no key, no order
  code). The owners switch it on when good strategies exist (a 정식 or 참고 account in a `lineup`). Whatever day it is
  switched on, it records **every** system of both studies from **2026-10-01 00:00 UTC** on the coins of the 30 that
  still trade (22 at 2026-09-30; never a coin outside the 30, no new listings; a coin that stops trading ends as H 2),
  one $5,000 wallet per system at r = 0.5%, recomputed from 2026-10-01 after every 5m bar with this study's own engine
  (`hunt.py`). The lineup accounts (정식 and 참고, read from `test.json`'s `lineup`) are shown first and sent to
  Telegram; the other systems are recorded only and become nothing from this study (a later round may use them only as
  section 14 says). Goal-size paper accounts only as 7.1 rule 6. **Real money only from 정식, never before the
  mid-November 2026 review.**
* **Live-readiness gate (risk 12), separate from the research PASS**, evaluated on the test period at whatever size the
  owners propose for real money (`evaluate_live_gate`; the spec is in `test.json`): (a) no liquidation under R9's
  mark-price read; (b) worst single-position loss <= 3U with R9's 25%-of-range stop fill; (c) worst rolling 30-day
  fresh-wallet multiple >= 0.70; (d) R10's instant loss if every open stop gaps 10% <= 25% of equity at every 5m close;
  (e) mean ln M > 0 under R9's impact model with Y = 1.0 at the live starting equity and at 10x it; (f) forward paper:
  the replay reproduces >= 99% of positions (H 15) and the forward multiple lies inside the R14 band (5th..95th
  percentile, over the record's first N days as R14 says); (g) if the AI
  judge is used, R15's p95 events per day <= the owners' daily call cap. A size that fails any item is labelled "not
  live-ready at this size". The research verdict is untouched and real money stays the owners' decision.
* Owner-facing goal numbers are multiples (owners (e)).
* Nothing is tuned after the test period is seen. A bug found after the test is fixed in `DEVIATIONS.md`, the test
  rerun once, both results shown. Any changed rule (entries, numbers, gate, exits, size, K, batches, scores) is a new
  study with its own pre-registration. A later round designed and selected on 2021-2023 only is judged as section 14
  says (one confirm per version on the test period 2024-01-01 .. 2026-10-01, every look in the program-wide ledger,
  plus forward paper data counted from the day its pre-registration is hashed);
  a change taken from a test-period figure (a read of section 7 on test, for example R5, R7, R16 or R20) is judged
  only on data after its fixing date.
* **Two studies, one test period.** v1 and wide each have their own pass; the chance that at least one of the two
  passes by luck is larger than either alone. The report says this next to the two verdicts.
* The mid-November review checks the paper bot as H 15 (it followed the rules; its forward multiple lies inside the
  test period's rolling-window range: R14's band of 40, 45 or 50 days, the record's first N days; nothing broke).
  About six weeks of forward record (from 2026-10-01; the owners watched its first days live, R23) cannot prove a
  trend system.

## 13. Known limits (stated before any result)

* **The old six are not blind.** The full grid's results for F2/F3 at default numbers (with the rule bot's exits) on
  the old six, including 2024-2026, have been read by the owners and the main session. The default numbers were not
  chosen on that period, but what was seen can steer later choices; the new-24 read is shown next to every pick. It
  does not make a result clean: the new 24 coins trade in the same 2024-2026 market and move with the old six.
* **The 38 F4 picks were chosen after the full grid's test period and 2020 were seen** (WATCH_PREREG 0): their test here
  would be out of sample on no coin set, which is why F4 is a select-period read only (section 3).
* **Winner's curse.** The best of 762 select runs looks better on 2021-2023 than it is. Only the single test, the
  controls and BH over each batch speak to that; R4 measures it on select.
* **Power.** 33 test months and BH over up to ten picks per batch: a real but small edge may not pass. A later batch
  opens only after >= 5 passes, so the extra tests cost little when batch 1 shows no common edge; the program-level
  ledger (R13) is printed beside the verdicts.
* **F5 is not blind either.** The famous rules' daily results on the old six (research/famous) have been read; their
  intraday adaptation (lengths in bars, the weekly TSMOM decision at the Monday 00:00 close) was fixed here without
  any run on these coins. The four timeframes of one TSMOM rule share their decision moments.
* The universe is a 2026 list (H 3, H 18 Q2). The strategies were written for the old six; DeepSeek definitions that
  read BTC context get BTCUSDT's bars on every coin.
* The edge rule (3.2) makes state and mixed strategies enter less often than the full grid counted them, and under G1
  a run that starts outside 추세장 gives no entry.
* On 15m and 30m the first stop and the chandelier are tight relative to costs (5m fills, taker fees); this is part of
  what is tested, not a reason to change the costs.
* **Pyramiding is margin-limited on tight stops and in larger accounts (H 7.3 as written).** The leverage H 7.3 (ii)
  asks for is N4 / B = 24 x r / (D0 / P0), with N4 = 4 x q x P0 taken at P0, while the adds fill higher (long). With the
  fallback brackets at r = 0.5% and a $5,000 wallet: at or below D0 / P0 = 0.4% N4 reaches the $25,000 tier and L = 10,
  so at most a third of one add finds room (none at 0.3%, where the first unit takes the whole budget); 0.5% leaves room
  for about 2.3 of the 3 adds (L = 20); 1% leaves about 2.94, so the third add is cut. At r = 1% the tier is reached at
  or below 0.8%, and at or below 0.5% the first unit itself is cut to B. Whenever N4 / B = 0.12 / (D0 / P0) at r = 0.5%
  (0.24 / (D0 / P0) at r = 1%) is a whole number of at most 20 (at r = 0.5%: D0 = 1%, 2%, 4% of the price ...), L uses B
  exactly and the third add is always cut, so the "full units" stops of H 7.4 (P0 + 0.667 D0, P0 + 1.25 D0) do not hold
  exactly. Tight stops are typical of the new 15m and 30m systems, so selection compares timeframes under this
  asymmetry. N4 / B does not depend on the equity, but the bracket of N4 does: a compounding account crosses the
  $25,000 / $100,000 / $250,000 tiers and loses adds as it grows. Counted per run (adds skipped and cut by margin);
  a real bracket table (`exchange30.json`) changes the numbers; computing N4 at the planned add levels is section 15
  Q14.

## 14. Not in this study

Numbers other than the defaults and the 38 watch picks' numbers; combining entries inside one system (the basket is a
read); exits other than the chandelier (the six exit cells are R5 reads); r above 0.5% as the rule; gates other than G1
and NONE; the AI judgment layer (H 17); timeframes other than 15m, 30m, 1h, 4h. **Deferred to round 2** (owners
2026-10-11; not added now): new-information entries, the loss-autopsy noise filters and custom values (with a plateau
rule).

**How every later round is judged (owners' agreed process, 2026-10-11).** Each later round (new-information entries,
loss-autopsy noise filters, custom values with a plateau rule, and any later version of them) is **its own
pre-registered study**: it is designed and selected on **2021-2023 only** (no bar from 2024-01-01 on enters its design
or its choice), then **confirmed once per version on the test period 2024-01-01 .. 2026-10-01** (2024-01 .. 2026-09)
with its rules, picks and pass fixed and
hashed before that look; a new version is a new pre-registration and gets one new confirm look, never a rerun of an old
one. **Every confirm look of every version counts in the program-wide ledger** (R13: a global BH at q = 0.10 and Holm
at 0.05 over every test-period hypothesis of the program, this study's and v1's included), printed beside each round's
verdict, so repeated looks at the same 2024-2026 months are paid for. **Forward paper data** (the paper bot records
every system from 2026-10-01, section 12) is added to each round's verdict as the out-of-sample check, **counted only
from the day the round's pre-registration is hashed**: the record before that day was on the paper bot's dashboard
while the round was designed, so it is shown beside the verdict as seen data, never as out-of-sample. Each round's
pre-registration states what of this study's test results and of the forward record (screens, systems, dates) its
designers had seen.

## 15. Open questions (closed before the pin; default in brackets)

1. **730, not 740.** The five ET-session DeepSeek definitions exist only on 15m/30m/1h (`ds_defs.TFS_OF`); running them
   on 4h would use code the full grid never ran and cannot be parity-checked. [730; no 4h for those five]
2. **F4 is not out of sample on any coin set** (section 3, 13): the new 24 share the 2024-2026 market. [Closed in
   review: F4 is a select-period read only, never a pick, never in the BH family or WIDE PASS, never run on test (R22
   included). The alternative of the draft (F4 eligible, labelled) is rejected because a leaked p would also loosen BH
   for the other picks. For F1-F3 and F5 picks: "carried by the old six" stays a label, not a condition]
3. **Long and short event on the same bar and coin.** [No entry; counted]
4. **Mark price.** The new 5m files hold mark-price columns, but H 2 and H 7.6 check liquidation on last price and this
   study keeps the machine identical to v1. [Last price, as H 2; mark columns unread]
5. **K = 10, one per name.** [Keep, in batches (owners (b)): batch 1 = positions 1-10; later batches of 10 only after
   >= 5 passes; membership fixed at select]
6. **72 positions in 36 months** may exclude many 4h G1 systems. [Keep; the gate is not changed for it]
7. **Score = mean ln M**; the median is only a tie-break here (v1 uses a median-based plateau). [Keep]
8. **Sizing read**: replaced by the R1 goal board (section 7.3). Machine A is the tested machine with the open-risk cap
   scaled by r / 0.5% and B = equity / 6 as written (panel: at higher r the margin budget and the brackets cut the
   unit, and the realised risk is printed next to the nominal r); machine B is the goal-mode machine. Alternative: B
   also scaled by r / 0.5% on machine A (the first draft's sizing read; one line in `reads_a.cell_overrides`, which
   follows the default). [Panel: B = equity / 6 on machine A]
9. **Paper accounts at 2% or 5%.** [None; the owners decide after reading the goal board, labelled "goal-size paper,
   not tested"]
10. **Where it runs.** [The development machine at 2 processes if the measured time allows; otherwise a rented server
    started by the owners, same commit and pin]
11. **State arrays and the edge rule** (3.2). The design brief took every firing bar and the first bar only for state
    arrays; this addendum takes the first bar of every run for every family (reasons and costs in 3.2). [Edge rule for
    every family, taken before the gate. Alternative: the brief's rule with the state list fixed before the pin from
    the parity reference (N17_KC_RSI and N18_VWMA_MACD, pooled continuation share >= 0.5; next highest F4_PULL 0.31),
    accepting that control (a) then draws more random entries than the pick can take for the mixed arrays]
12. **A strategy x timeframe failing parity** after a fix attempt. [Removed before the pin, recorded here]
13. **No eligible system.** [As v1: the top F1-F3 or F5 system runs once with its reads, labelled "no pick, fail"]
14. **N4 at the planned add levels** (section 13). H 7.3 takes the planned full notional at P0 (N4 = 4 x q x P0), so
    the third add is often cut. Alternative for both studies, a change of H 7.3 before the pin: N4 = q x (4 x P0 + 6 x
    D0) for a long (the four planned fills P0, P0 + D0, P0 + 2 D0, P0 + 3 D0; short: 4 x P0 - 6 x D0) and the same in
    the per-unit budget check. [H 7.3 as written; the margin-limited adds counted and reported]
15. **Rule-bot files in the pin** (section 10). The signal code imports paper-bot modules, so they are hashed. [Run
    select and test from one fixed checkout of the pinned commit]
16. **F5 on intraday bars** (section 3.3). famous.py's daily rules become bar-count lookbacks (days x bars per day);
    TSMOM keeps its weekly decision at the close of the UTC Sunday, so its four timeframes share decision moments.
    Alternative: TSMOM's sign checked at every bar's close (many more flips on 15m). [Weekly, as famous.py]
17. **Number of batches.** [3 (30 names), as the panel; a fourth would need >= 5 passes in batch 3]
18. **The 참고 tier** (owners (g)). [Paper only, labelled; never real money; never a research pass]

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

### 16.3 Owners' decisions and panel review (2026-10-11, before the pin)

Done after the engine review (105 tests) and before any select or test of either study; no trading outcome had been
computed on any real price period. The panel's 23 reads, its pass-rule changes and its rejected items were read in
full; the owners' decisions (a)-(h) are binding (section 0.1). Changes:

1. **F5** (owners (a)): the four famous trend rules as events (3.3), 32 systems; 762 systems, 686 candidates, 87
   strategy names (sections 1, 3, 4).
2. **Batches** (owners (b)): one-per-name walk to 30 names, batches of 10 fixed in `picks.json` at select, BH per
   batch, the next batch only after >= 5 passes, labels 1군 / 2군 / 3군 (sections 5, 6).
3. **Controls with 1,000 seeds** (owners (c); H 12); select-period controls seeds 1-200.
4. **Reads** (owners (d), (e), (f); panel): the read guard and discipline, the headline cell, the select-fixed size
   rule, seed subsets (7.1); the reads interface (7.2); Phase A reads incl. R1, the R24 leverage read, R19 and R23
   (7.3); Phase B specs R2-R22 (7.4); the rejected items (7.5). The first draft's sizing read is replaced by R1.
5. **Paper lineup** (owners (g)) and the **live-readiness gate** (section 12); goal numbers as multiples (owners (e)).
6. **W 6 amendment** for the sealed post-verdict read R22 (section 6).
7. **F4** stays a select-only read (owners (h), unchanged).
8. Engine read options added to `hunt.py`, all off by default and bit-identical at default parameters (tested against
   the reviewed engine's digest): per-5m equity path and peak, close at the end, N4 = (1 + adds) x q x P0, the
   goal-mode bracket rule, fixed leverage with margin = L%, 1m bars and liquidation on mark. Commands `reads`,
   `fidelity`, `october`.
9. Deferred to round 2: new-information entries, autopsy noise filters, custom values (section 14).

### 16.4 Phase-A review (2026-10-11, before the pin)

Done after the Phase-A reads module (`reads_a.py`) and the core changes of 16.3 were drafted and tested on synthetic
bars only; no select or test of either study had run and no trading outcome had been computed on any real price period.
Three reviewers (leak, math, docs) read the code and this file. Changes:

1. **F4 never runs on test, R22 included**: R22 (1) and R4 (2)-(4) cover the 686 candidates (F1-F3 and F5); R22's
   public aggregates that carry ln M use F1, F2 and F5 rows only (sections 3, 6, 7.4, Q2). 16.2 #1 ("come from F1-F3")
   is superseded: the picks, the BH family, WIDE PASS and the 'no pick, fail' system come from F1-F3 and F5 (sections 3,
   5, Q13; the code's CHOICES say the same).
2. **7.1 rule 1 names its exceptions** (R4, the R5 machine map, R22, R2 (d), R3). **Rule 3**: the reads lines are judged
   against the first test start for these picks (kept once in the private folder); a fixed reads module is appended
   again and its older line is reported as superseded. **R14** is listed in the pin before `test.json` and its output
   before the paper bot starts.
3. **7.3a**: R4's select parts and R22 (2)'s select spike ratio come between `picks.json` and `test.json` from a pinned
   file, or are post hoc; `test.json` records which (`pretest_reads`).
4. **Machine A of R1 follows 7.3 and Q8's default** (B = equity / 6, only the open-risk cap scaled); 16.2 #2 ("the
   margin budget is scaled with r") is superseded for R1, which replaced the sizing read. The retired sizing read's
   code is removed.
5. **R24 copies the rule bot**: the tier walk 40 -> 30 -> 20 (the old rule lowered L to the bracket maximum at L's own
   notional, so 40x could run at less leverage than 20x) and its third check (loss at the stop <= 15% of equity), both
   in the engine at entry time (one sequential run instead of a fixed point; synthetic 30 coins, one 30-day window:
   3-4 ms per L cell vs 9 ms for machine A at r = 0.5%); the wallet-loss table is capped at the isolated margin.
6. **The 0.03 s rule** reads only a pinned synthetic timing (`benchwin` -> `bench_window.json`), never times real data;
   the judge's per-call cost is a recorded parameter (`--judge-usd-per-call`); columns the engine does not export are
   marked "not computed in Phase A".
7. **R23**: the October zips are listed in `october_files.json` (`octlist`), pinned; `october` refuses anything else.
8. **Headline cell as a multiple** (touched x5), owners (e). Extra-2020 rolling windows: about 155. Section 13's add
   arithmetic corrected (0.4% tier edge at r = 0.5%, 0.8% at r = 1%; 1% leaves about 2.94 adds).

### 16.5 Float64 data, the paper bot, later rounds (2026-10-11, before the pin)

Done before any select or test of either study; no trading outcome had been computed on any real price period (the
parity run below is signals only). Changes:

1. **Float64** (sections 8, 9; H 2): the parity check on the float32 hunt files failed on exact ties (19 cells over the
   1% limit) and the live bots trade float64 exchange prices, so the 5m files and the engine's coin arrays (prices,
   volumes, mark OHLC) are float64, the data rebuilt from the Binance archive and every pin input (`data_manifest.json`,
   `data_check.json`, `parity.json`, `bench_window.json`) rerun on it before the pin; no difference excused, no cell
   dropped.
2. **Paper bot** (section 12; H 15): its own server `hunt-judge` (not the rule bot's paper server), switched on by the
   owners when good strategies exist, recording every system from 2026-10-01 on the coins still trading (22 at
   2026-09-30); its lineup from `test.json`'s `lineup`; real money only from 정식, never before the mid-November review.
3. **Later rounds** (sections 0.1, 12, 14, R13): the owners' process of 2026-10-11 (each round its own pre-registered
   study, designed and selected on 2021-2023 only, confirmed once per version on the test period 2024-01-01 ..
   2026-10-01, every confirm look in the program-wide ledger, plus forward paper data counted only from the day its
   pre-registration is hashed) replaces "forward data only".
4. **Review before the pin** (sections 7.1, 7.3, 7.4, 8, 12, 14): `parity.json` records each old-six coin's 5m content
   hash and the pin compares it with `data_manifest.json` (parity rerun under the final code); the float64 parity
   result, the benchwin figure and the October file count written in; R14 gets 40-, 45- and 50-day bands, since the
   forward record now starts 2026-10-01 and the 21-30-day lengths of the earlier plan no longer match the review; the
   confirm window is written as the test period; forward data counts for a later round only from its hash date, since
   the dashboard shows the record from 2026-10-01 to anyone designing it.
