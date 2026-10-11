# Trend hunt round 2, custom values (추세 사냥 2차, 커스텀값): pre-registration

(한국어 설명: `README_R2_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 1차 결과를 보기 전에 해시로 고정하고, 그 뒤에는
고치지 않습니다. 바꿀 일이 생기면 `research/hunt_r2/DEVIATIONS.md`에 날짜와 그때까지 본 것을 함께 적습니다.)

**Status: DRAFT design, written 2026-10-11 between about 22:40 and 23:50 UTC (2026-10-12 07:40-08:50 KST), before any
output of round 1 (the trend hunt, `research/hunt`) was seen, fetched or inferred by its authors, and before any code of
this study existed. To be hashed at once (section 0.1).** After the design hash this text does not change. The code is
written, reviewed and pinned later (section 11); every later correction, and the closing of each open question of
section 16, is an entry in `research/hunt_r2/DEVIATIONS.md` under the rules of section 0.3.

Owners (2026-10-12, 07:40 KST), on the trend hunt: **"1번 트랙에서도 커스텀값을 찾아야지 왜 안찾는거야"**. Round 1 used
every entry at its default numbers on purpose and deferred custom values to a separate round with a plateau rule
(`PREREG_HUNT_WIDE.md` sections 0.1 and 14). This file is that round.

Section references: "H n" = `research/hunt/PREREG_HUNT.md` section n; "W n" = `research/hunt/PREREG_HUNT_WIDE.md`
section n (W R1-R24 and O1-O5 its reads); "T2 n" = `research/hiwr/PREREG_HIWR.md` (track 2) section n; "FG n" =
`research/fullgrid/PREREG.md` section n. Everything of H and W that this file does not change applies as written there.

## 0. What this is

* A **separate pre-registered study** (round 2 of track 1), judged as W 14 says: designed and selected on **2021-2023
  only**, confirmed **once** (version "hunt-r2 v1") on the test period 2024-01-01 .. 2026-10-01, every look counted in
  the program-wide ledger, forward paper data counted from the date of section 0.5.
* It searches **the numbers of the entries** (indicator lengths, multipliers, thresholds) of the round-1 candidate
  names, on the round-1 machine, with few tries per name, plateau checks, and a null of the search's own luck.
* Research only: it touches nothing of the rule bot, the candidate league, round 1's pinned files or outputs, the full
  grid's pinned files, track 2, or any account.

### 0.1 Hash before round 1 is seen (timing)

* Round 1 (select and test of v1 and wide) has run on the owners' server since 2026-10-11 20:52 UTC at code commit
  0f18ecb (pin ca561234bd). Its verdict was expected about two hours later. **This design must be fixed before anyone
  sees round 1's results.**
* Order: the main session writes this file's sha256 line (sha256sum format) as the first line of
  `research/hunt_r2/PREREG_HUNT_R2.sha256` (the **design hash**) and commits this file, `README_R2_KO.md` and that line
  **before** it pulls the hunt-results branch, opens the server screen, or reads or relays any message about round 1.
  The commit hash and its UTC time are then written as the first entry of `research/hunt_r2/DEVIATIONS.md` (not into
  this file, so the design hash stays valid).
* This file states: **written and hashed before any round-1 select, pick, test or read output (R22 included) was seen,
  fetched or inferred.** If anything from round 1 reached the main session before the hash commit, that sentence is
  false for this hash: the main session writes what was seen, plainly, as the first entry of `DEVIATIONS.md` in the
  same commit, and that entry governs every later reading of this file.

### 0.2 What the designers had seen

Seen, before writing this file:

* **The full grid's results** (`research/fullgrid`, ANALYSIS_KO.md and the per-strategy reports): its custom-value
  tables for the old six coins on 2021-2023 **and on 2024-01 .. 2026-09** (house exits, 1m, per-trade units), its 711
  picks and 0 passes, and the per-strategy grades.
* **The 38 F4 watch picks** (`research/fullgrid/diag/watch_sel.json`), kept because they were positive on 2024-2026 and
  2020 (W 3).
* **The loss autopsy** (`research/autopsy/LOSS_AUTOPSY.md`, select period only, plus the repo reports it quotes).
* **Track 2's select-period feasibility** (T2 22, 2021-2023 only).
* **The owners' October live screens**: the rule bot's paper accounts, the candidate league and the demo lab in
  October 2026, as shown on their dashboards; any forward record of a hunt system shown on a dashboard before the hash
  is seen data (0.5).
* **Round 1's design, code and pinned inputs**: PREREG_HUNT.md, PREREG_HUNT_WIDE.md, hunt.py, entries_wide.py,
  reads_a.py, reads_o.py, the pin files, `data_manifest.json`, `data_check.json`, `bench_window.json` and the pinned
  `research/hunt/out/wide/parity.json` (signals only, W 8). A listing of `research/hunt/` on the development machine
  shows the folder `out`; nothing inside it other than the pinned parity file is known to the authors, and nothing in
  it was listed or opened.

Not seen: **no round-1 select table, pick, batch, test result, control, read, R22 aggregate or server log**; no
trading outcome of any system on any bar from 2024-01-01 on for this design. No computation on real prices was made
for this design, except signal-function timing on one coin's practice-period bars (5m bars cut at 2024-01-01; signals
only, seconds printed; no position, no outcome). Lattice counts were computed from code only, engine timings on
synthetic bars only (section 17).

### 0.3 Run regardless of round 1; how this file changes

* **Round 2 runs whatever round 1 shows** (WIDE PASS or not, any pick, any read). Nothing in round 1's results starts,
  stops, shrinks or widens round 2.
* After the design hash, a rule changes only through `research/hunt_r2/DEVIATIONS.md`, each entry dated and stating
  what of round 1 and of the forward record had been seen at that date. **Allowed entries:** (i) bug or feasibility
  fixes (the code not doing what this file says, or a step that cannot run as written), with the line of this file
  they restore or the smallest change that makes the step run; (ii) choices this file leaves open (section 16), closed
  by the owners or at the written default. **Never allowed:** a choice informed by round-1 results (which names, which
  timeframes, which numbers, which thresholds).
* A bug fixed in the shared engine (`research/hunt/hunt.py`) through `research/hunt/DEVIATIONS.md` is inherited, and
  the inherited file's hash replaces round 1's pin line in this study's check (section 11).

### 0.4 Why round 1 had no custom values

* Round 1 used defaults on purpose (W 0.1, W 14): numbers chosen on the same data overfit unless guarded.
* The evidence is the full grid (FG 4-6): 1,015,563 number combinations x 84 exits on the old six coins. Its 379
  rule-bot picks with at least 100 test trades fell from a select-period **per-trade median** of **+2.47%** to
  **-0.25%** on 2024-2026 (`research/fullgrid/ANALYSIS_KO.md` section 4; the round-2 brief wrote this as "per month";
  the source is per trade), with **0 of 711 picks** passing the FDR correction and a select-to-test rank correlation of
  **0.22**. The full grid also chose by a plateau median, over a large grid, and it collapsed.
* So round 2 searches custom values with **few tries per name** (at most 168), **plateau checks** at two scales, and a
  **null of the whole search's own luck** (section 4.3), and it stops before the test if nothing beats that null.

### 0.5 Forward-count date

Forward paper data counts as out of sample for round 2 from the later of: the design-hash date (0.1), and the date of
the last `DEVIATIONS.md` entry that changes a rule (an entry that only restores this text, or closes an open question at
its written default, does not move it). The forward record before that date is shown beside the verdict as seen data.

### 0.6 Changes against round 1, argued here (all others: H and W as written)

1. Numbers are searched (sections 3-4); W 5's one-system-per-name walk becomes the staged selection of section 4.
2. F2_DEMARK and F6_VWAP_CROSS (no numbers) and F4 (the watch picks) are out (3.1).
3. No "no pick, fail" system: if selection takes nothing, nothing runs on test (4.3; differs from H 11.2 / W 5).
4. P2's month-block bootstrap uses **100,000** resamples instead of 10,000 (section 7).
5. The program-wide ledger is a pinned module of this study with a dated snapshot in `test.json` (section 8).

## 1. Question

For each of the 85 round-1 candidate names that have numbers, run on the round-1 trend-hunt machine (H 2-10 with the
W 2 changes) at the timeframe and gate where its default numbers did best on 2021-2023: is there a setting of its
numbers, chosen on 2021-2023 only by a plateau rule and kept only when it beats the same search run on no-skill
entries, that grows one wallet after all costs on 2024-01 .. 2026-09 and beats the same machine fed with random entry
times and with coin-flip sides, after correcting for testing up to ten at a time?

## 2. The machine (unchanged) and what is not searched

* **Unchanged, as H and W:** data and data identity (H 2; `research/hunt/data_manifest.json` checked at every select
  and test; the 1 GB disk stop), the 30 coins, old six / new 24 and the large group (H 3), bars and indicators (H 4,
  W 2: 15m, 30m, 1h, 4h UTC bins of the 5m bars), the 장세 label and G1 (H 6) and NONE (W 2), the event edge rule taken
  before the gate (W 3.2) and the 300-bar warm-up for F2-F3 events (W 3.1), entry fill, first stop D0 = 2 x ATR14 on
  15m/30m/1h and 1.5 x ATR14 on 4h (H 7.2, W 2), leverage and isolated margin (H 7.3), pyramiding with 3 adds (H 7.4),
  the chandelier at 3 x ATR14 of the system's timeframe (H 7.5, W 2), the order inside a 5m bar (H 7.6), the portfolio
  (H 8), costs and cost x2 (H 9), accounts ($5,000, compounding), monthly multiple, bust and metrics (H 10), r = 0.5%
  for selection and test (W 2), the periods (H 11).
* **Engine identity:** `research/hunt/hunt.py` and `research/hunt/entries_wide.py` are imported read-only; their sha256
  must equal round 1's pin lines (`PREREG_HUNT_WIDE.sha256`), or the line of a later engine fix inherited under 0.3.
  The full grid's signal code is imported read-only as W 3.1: `run.py`, `grid.py` and `ds_defs.py` under the full
  grid's pin (`research/fullgrid/PREREG.sha256`), the core definitions under `DEFS_BC.sha256`, and `memo.py`,
  `research/deepseek200/lib_c.py` and the other loaded files with the hashes round 1's wide pin lists for them.
* **Not searched:** exits, D0, adds, r, the 장세 label's numbers (ADX, EMA slope, ATR percentile), the gate rule,
  weekend and other noise filters (the loss autopsy's filters stay a separate later round; O1, O1b and O4 are reads
  here, section 9), coins, timeframes or gates beyond the anchor (4.1), per-coin numbers, combining entries.

## 3. Search space: names, numbers, lattices

### 3.1 Names (85)

| family | names | numbers |
|---|---|---|
| **F1** | E1, E2, E3 (H 5) | new declarations (3.2); the default combo reproduces `entries_wide.hunt_raw` bit for bit |
| **F2** | the rule bot's 36 = `research/fullgrid/run.core_names()` | `run.params_of("core", name)`; defaults = `run.default_combo` |
| **F3** | 42 of the 44 DeepSeek definitions in `ds_defs.DEFS`: all except **F2_DEMARK and F6_VWAP_CROSS**, which have no numbers. The five ET-session names (F15_ASIA_BRK, F15_ASIA_SWEEP, F15_LON_BRK, F15_OPEN0930, F15_OPEN0000) run on 15m, 30m, 1h only (W 4) | `ds_defs.DEFS[name]` |
| **F5** | TURTLE20, TURTLE55, TSMOM7, TSMOM28 (W 3.3, `entries_wide.famous_raw`) | lengths in days (entry_days, exit_days; lookback_days), x bars per day of the timeframe as W 3.3 |

* **F4 (the 38 watch picks) stays out**: their numbers were kept after 2024-2026 was seen (W 3).
* Signal arrays for F2 and F3 come from the same functions W 3.1 calls, with the combo passed as keyword numbers; F5
  from `famous_raw(name, bars, combo)`; F1 from the new function of 3.2. Event rule W 3.2 for all.
* The appendix lists every name's numbers, kinds, defaults and coarse values.

### 3.2 F1 declarations (new; the defaults are H 5's constants)

| name | number (kind) | default | notes |
|---|---|---|---|
| E1 | channel (length) | 55 | Donchian lookback |
| | vol_len (length) | 20 | mean quote-volume window |
| | vol_mult (threshold_neutral, neutral 1, bounds 1..inf) | 2.0 | volume test qv >= vol_mult x mean |
| E2 | window (length) | 120 | squeeze percentile window |
| | pct (threshold_abs, bounds 0..100) | 20 | the squeeze percentile (the same kind as S4_BB_BBP's sq_pct) |
| | bb_len (length) | 20 | Bollinger length |
| | bb_k (mult) | 2.0 | Bollinger width |
| E3 | threshold (threshold_neutral, neutral 1, bounds 1..inf) | 1.5 | ATR ratio level |
| | fast (length) | 14 | fast ATR |
| | slow (length) | 100 | slow ATR |
| | side_len (length) | 20 | side = sign(close[t] - close[t - side_len]) |

A new function takes the combo; a synthetic test checks that it equals `entries_wide.hunt_raw` bit for bit at the
defaults (and v1's neighbours, H 11.1, at their values).

### 3.3 Validity

`valid_r2(name, combo)` = `research/fullgrid/grid.valid(name, combo)` **and** these strict order rules, which
`grid.valid` lacks (`grid.py` lines 75-83 cover only the SAR caps and the two bodies):

| names | rule |
|---|---|
| N01_ST_EMA, N03_ADX_GC | ema_fast < ema_slow |
| N06_MACD_ORB, N18_VWMA_MACD | macd_fast < macd_slow |
| N07_ICHI_CMO | tenkan_len < kijun_len < senkou_b_len |
| N08_ICHI_WR, N12_ICHI_AO, N14_ICHI_RSI | tenkan_len < kijun_len |
| N12_ICHI_AO | ao_fast_len < ao_slow_len |
| N15_KC_AO, OBV_B | ao_fast < ao_slow |
| N09_ALLIG_AROON | lips_len < teeth_len < jaw_len |
| F4_PULL | ema_fast < ema_mid < ema_slow |
| F4_PULL_RSI | ema_fast < ema_slow |
| E3 | fast < slow |
| TURTLE20, TURTLE55 | exit_days < entry_days |

The table is closed at the design hash; it lives in `lattice.py`, which the pin lists. Every default satisfies it.

### 3.4 Coarse lattice (½x, 1x, 2x)

* Each number takes the values at `grid.MULTS` indices 1, 4, 7 (factors ½, 1, 2); a threshold_neutral number takes
  f = 0.5, 1, 1.5 of `grid.NEUTRAL_F` (neutral + f x (default - neutral)). Each value passes through `grid.values`' own
  rounding (half up, at least 2), clipping (declared upper bounds of lengths; neutral thresholds clipped to their range)
  and dropping (multipliers and absolute thresholds outside their bounds are dropped, so some numbers have only ½x and
  1x). Values are deduplicated; the lattice is their product, minus combos that fail `valid_r2`.
* **Counts, from code only** (no data read): **3,784 coarse points over the 85 names, of which 85 are the defaults, so
  3,699 new**; the order rules remove 166 of the 3,950 points `grid.valid` alone keeps. Over every timeframe of every
  name the coarse lattice has 15,121 (name, timeframe, combo) cells. A test asserts that every coarse value is a value
  of `grid.values()` for that number. `counts.json` (per name: values, coarse points, largest box) is written by
  `lattice.py` and pinned before any data is read.
* **Coarse neighbours** of a point: the existing lattice points that differ from it in exactly one number by one step
  in that number's deduplicated coarse value list.

### 3.5 Fine box (local, 9-step)

* For each number, the 9-step block of `grid.MULTS` (or `grid.NEUTRAL_F`) that holds the coarse peak's factor:
  lengths and multipliers {⅓, ½, ⅔} around ½x, {0.8, 1, 1.25} around 1x, {1.5, 2, 3} around 2x; threshold_neutral
  f in {0.25, 0.5, 0.75}, {0.9, 1, 1.1} or {1.25, 1.5, 2}. Values through `grid.values` as in 3.4; the box is the
  product, minus `valid_r2` failures.
* A value reached from more than one coarse factor (after rounding, e.g. orb_bars 2 at ½x and 1x) takes the factor
  nearest 1x in log distance.
* The box has at most 81 points (the centre is the coarse peak), so at most 80 new; over the 85 names the largest
  possible boxes total 4,032 points. The reachable range is ⅓x .. 3x, the full grid's range, but only around a peak
  that already won on the coarse lattice.
* **Fine neighbours** of a box point: the box points that differ from it in exactly one number by one step of the
  9-step block.

### 3.6 Systems, identity, tries

* System id: `R2:<family>:<name>:<tf>:<gate>:<combo sha>`, combo sha = the first 12 hex digits of the sha256 of the
  combo as canonical JSON (sorted keys, lists kept, floats as `repr`).
* **Default in effect:** a combo whose gated select-period event list (all 30 coins: coin, signal-bar close, side) on
  the same timeframe and gate hashes equal to its default's takes the default's identity: it is counted as the default
  and can never be a peak or a pick. Two non-default combos with equal event lists stay separate points (labelled).
* **One system, two names:** an identical system (same family code, same numbers in bars, same timeframe and gate)
  reached under two names belongs to the name whose default is nearer in log distance; on a tie, to the earlier name
  (so TSMOM 14 days belongs to TSMOM7). In the other name's lattice it still counts as a neighbour value for medians
  but can never be that name's peak or pick.
* **Tries per name, at most 168:** the 8 default systems (4 timeframes x 2 gates; 6 for the session names) + at most
  80 new coarse points + at most 80 new box points. A one-number name has at most 12 (10 for the session names). Over
  the 85 names the selection can try at most 8,316 systems; the full grid tried 1,015,563 combos x 84 exits.

## 4. Selection (2021-01-01 .. 2024-01-01 only)

The select step reads no 5m bar that opens at or after 2024-01-01 00:00 UTC: each coin's npz columns are decompressed
whole for the content check (H 2) and cut at 2024-01-01 before anything else uses them; of the manifest only what lies
before that date is carried (H 11, W 5). Positions open at the end are marked at the last 5m close (H 10).

### 4.0 Definitions

* **S** = mean monthly ln M over the 36 select months at base cost, r = 0.5%, one $5,000 account (W 5's score).
  **S2** = the same at cost x2 (H 9). **n** = positions opened. Bust as H 10.
* **W5-ok** = n >= 72, S > 0, S2 > 0 and no bust (W 5's eligibility).
* **Lattice order** (for ties): the product order of the numbers in their declared order, each number's values
  ascending (as `grid.grid`); the box in the same order over its block values.

### 4.1 Stage 0: anchors (defaults only)

* Each name's default systems are recomputed by round-2 code: 8 per name (6 for the session names), **670 systems**
  (round 1's 686 candidates minus the 16 systems of F2_DEMARK and F6_VWAP_CROSS).
* **Anchor** of a name = its default system (timeframe, gate) with the highest S among those with n >= 72 and no bust;
  if none qualifies, the highest S overall. Ties as W 5 (higher median monthly multiple; then timeframe 15m < 30m < 1h <
  4h; then G1 before NONE).
* Round 2 never reads round 1's output to do this. An optional automated check may compare the Stage 0 rows with round
  1's `select.json` after the design hash and print only "equal" or "not equal" per row; no person reads round 1's file
  for it.

### 4.2 Stage A: coarse plateau on the anchor

All coarse points of the name run on the anchor's timeframe and gate, base cost and cost x2.

* **P_c(x)** = the median of S over x and its existing coarse neighbours (3.4). A neighbour with n < 72 counts as 0; a
  busted neighbour keeps its own S. **P_c2** = the same with S2. A point without neighbours has P_c = S.
* **Coarse-eligible x:** W5-ok, P_c(x) > 0, P_c2(x) > 0, and at least half of x's existing neighbours have n >= 72 and
  no bust.
* **Peak** = the coarse-eligible point with the highest P_c. Ties: higher P_c2, then higher S, then lattice order.
* A name is a **candidate** only if it has a peak, the peak is not the default (nor a default in effect), and
  P_c(peak) > P_c(default point) (computed the same way, whether or not the default is eligible).
* Candidates are ranked by P_c(peak), highest first. Ties: higher P_c2, then W 5's family order (F1 < F2 < F3 < F5),
  then name (ASCII).

### 4.3 The null hurdle (the main guard against the full grid's failure)

The full grid failed because the best of many tries on 2021-2023 is lucky. The hurdle measures that luck for **this
search**: the whole of Stage 0 and Stage A is replayed on entries that have no skill but keep the correlations across
systems, and a name goes forward only if it beats both nulls at its rank. Select period only, base cost only (dropping
the cost x2 conditions in the null lets more null points qualify, so the hurdle errs strict).

* **(b′) Shared coin flip**, 100 replicates. In replicate i one fair coin per (coin, signal-bar close in ms): heads
  (the first byte of sha256("hunt-r2-null|b|<i>|<SYM>|<close_ms>") even) keeps the side, tails reverses it, for
  **every** system that has an event on that coin at that close (all names, timeframes, gates and combos). The machine
  then takes or drops each event as H 8 says.
* **(a′) Common circular time shift**, 100 replicates. One whole-day shift per replicate, Δ_i = 60 + (the first 8 bytes
  of sha256("hunt-r2-null|a|<i>"), little-endian, mod 976) days, so uniform in 60 .. 1,035 days. The same Δ_i applies
  to all coins and systems: each gated event list is shifted by Δ_i inside the select period
  [2021-01-01, 2024-01-01), wrapped at its end, time of day kept, side kept, **not re-gated**. Events landing on a bar
  without a 장세 label, without ATR14 > 0, or without a fill bar inside the period (a coin's start, end or gap) are
  dropped and counted per replicate.
* **Each replicate replays Stage 0 and Stage A with the same rules** (its own anchors, peaks, candidate test and
  ranking, with the default-in-effect rule). A shortcut of Stage 0 (for example, reusing the real anchors) makes the
  hurdle lenient and is not allowed.
* **Rank-r null score** = the r-th highest candidate P_c in a replicate; 0 when the replicate has fewer than r
  candidates.
* **The real candidate at rank r is taken only if its P_c(peak) is greater than the 75th percentile (numpy linear) of
  the rank-r null scores in BOTH nulls.** Failing candidates are dropped; taken names keep their order.
* **If no candidate is taken, round 2 fails at selection.** Nothing runs on the test period and no ledger hypothesis is
  added. This differs on purpose from H 11.2 / W 5's "no pick, fail" system: such a system can never pass or join the
  lineup, and running it would spend a look at 2024-2026 for nothing.
* What the hurdle can and cannot do: a search on pure noise still clears a 75th percentile at its top rank in roughly
  15-25% of runs (the two nulls are correlated), so the hurdle removes most, not all, luck; the test's controls and BH
  remove the rest. It is the hurdle the full grid did not have.

### 4.4 Stage B: local refinement

Taken names are refined in their order until **30 picks** exist or the list ends.

* The fine box (3.5) around the coarse peak runs on the anchor's timeframe and gate, base cost and cost x2.
* **The box must be a plateau:** the median S over all box points > 0 and the median S2 > 0, and at least ⅔ of the box
  points have n >= 72 and no bust. A box that fails drops the name, labelled "spike between coarse points", and the
  next taken name moves up.
* **P_f(y)** = the median of S over y and its in-box fine neighbours (n < 72 counts as 0; a bust keeps its S).
  **P_f2** the same with S2.
* **Pick** = the W5-ok, non-default box point (nor a default in effect) with the highest P_f. Ties: the box centre,
  then higher P_f2, then lattice order. The centre is W5-ok and non-default, so a passing box always has a pick.
* **Rank and hurdle use P_c of the centre**, so refinement cannot raise a name's rank. The pick's own S is printed
  marked "inflated by the within-box choice".
* For R2-22 only (section 9.6), Stage B's pick rule (without the box plateau test) is also run, on select only and in
  the select step, for every candidate that failed the hurdle, every taken name beyond the 30th and every name whose
  box failed; this gives each candidate name a **would-be pick**. Would-be picks are never candidates.

### 4.5 No internal walk-forward gate

The 2021-2023 period is not split into a choose part and a hold part for the decision: a 12-month hold with its own
gates costs more power than it saves (a "beats the default on 2023" gate is close to a coin flip when tuning is
neutral), and the null hurdle measures the luck of choosing directly. The walk-forward is a **read** (section 6:
selection lift on 2023, leave-one-year-out stability), printed before the test and choosing nothing.

## 5. Picks, batches and the hash before any test bar

* **Batches:** picks 1-10 = **batch 1 (1군)**, 11-20 = **batch 2 (2군)**, 21-30 = **batch 3 (3군)**, in the order of
  4.3-4.4. K = the batch size, which may be under 10. Membership is fixed here and never re-ordered after a test result.
* `research/hunt_r2/out/picks.json` holds each pick's system id, family, name, timeframe, gate, numbers, P_c, P_c2,
  P_f, P_f2, rank, batch and labels; the candidate list with each one's null comparisons (passed / failed in (a′) and
  (b′)) and the rank-r null percentiles; the Stage 0 anchors; the counts per stage; the would-be picks of 4.4 in a
  separate section labelled "never candidates". DeepSeek rows: section 10.4.
* **Its sha256 is appended to `PREREG_HUNT_R2.sha256` before any bar from 2024-01-01 on is read.** The test step
  refuses without that line, and nothing in `picks.json` changes after it.
* **Labels, never conditions:** "edge of range" (a number at ⅓x or 3x of its default); "same numbers as an F4 watch
  pick"; "same numbers as a full-grid select pick" (those were seen on 2024-2026 under house exits); "numbers also run
  on test in round 1's sealed R22 (2)" (round 1 ran each round-1 pick's one-step `grid.values` neighbours on test, W 6
  and R22; their aggregates are public; round 2 never opens R22's private file); "old six not blind" (H 13 / W 13);
  "every coarse neighbour positive" (yes / no); "anchor default = round-1 system <id>" (that system's round-1 status
  is added from round 1's public files in the results page after round 2's verdict, not in `picks.json`).

## 6. Select-only reads (between `picks.json` and `test.json`)

Written by their own pinned module after `picks.json` is hashed and **before `test.json` exists**, to
`research/hunt_r2/out/pretest_reads.json`, whose sha256 is appended to the pin before the test starts (W 7.3a's rule;
if the module is not ready, these items are computed after the verdict, labelled post hoc). They read select bars only
and choose nothing.

* **CSCV / PBO** over every system round 2 ran on select (12 blocks of 3 consecutive months, all 924 half / half
  splits; the IS-best and the IS one-per-name top 10 by mean ln M; their OOS percentile; PBO; the slope of OOS on IS),
  as W R4 (2).
* **Null summary:** per rank, the q50, q75 and q90 of the rank-r null score in each null; the count of null candidates
  per replicate; the (a′) drop counts; N_eff = the number n of independent draws from the null's pooled per-point P_c
  distribution whose expected maximum equals the null's mean rank-1 score.
* **Selection lift on 2023 (walk-forward read):** Stage 0 + A chosen on the 24 months of 2021-2022 (from the same runs'
  monthly ln M), measured on the 12 months of 2023: per name, H(peak) minus the median H over the name's coarse
  lattice, H = mean monthly ln M on 2023; the median over names and the share above 0.
* **Leave-one-year-out stability:** Stage 0 + A chosen on each pair of years; per name, how often the same peak or one
  of its coarse neighbours returns. In both 24-month reads the position minimum is 48 (2 a month) instead of 72.
* **Near-miss table:** names that failed exactly one condition (candidate rule, one null only, box plateau).
* **Spike ratio** S / P_c and S by year (2021, 2022, 2023) for each pick.
* **Weekend map:** Stage A rerun on the real anchors under the O1 weekend-skip machine (W 7.4a); what it would have
  picked. Those systems are never tested here.
* Public numbers for F1, F2 and F5 rows; DeepSeek labels and ranks only (10.4).

## 7. Test (one confirm look: hunt-r2 v1)

* Period: **2024-01-01 .. 2026-10-01** (33 months), H 11. **Each tested pick runs once** at r = 0.5%, base cost, plus
  its cost x2 run. Nothing else of round 2 runs on test except the reads of section 9 after the verdict.
* **Controls**, exactly W 6 / H 12: (a) random times and (b) coin-flip sides, **1,000 seeds each**; seed = sha256 of
  ("hunt-r2", system id, control, period, r, seed number), parts joined as the hunt code joins them. d_m as H 12.
* **Per pick:** **P0** at least 66 positions, a position open in at least 80% of test months, no bust; **P1** median
  monthly multiple >= 1.0 and mean monthly ln M > 0; **P3** the same two at cost x2; **P4** max drawdown < 50%;
  **seed-rank parts** for (a) and (b) separately, (1 + seeds with mean ln M >= the pick's) / 1,001 < 0.05.
* **p:** p_a and p_b = the one-sided month-block bootstrap p of mean d_m (resample the 33 months with replacement
  **100,000 times**; p = (1 + resamples with mean d <= 0) / 100,001; seed parts as above with "boot"); **p = max(p_a,
  p_b)**. Argued change: the floor falls from about 1e-4 to about 1e-5, as track 2 (T2 11). The program-wide ledger can
  pass 350 hypotheses once track 2's picks are in; Holm at 0.05 then needs p <= 0.05 / m (1.4e-4 at m = 350, 1.0e-4
  at m = 500, less beyond), which round 1's floor of 1 / 10,001 meets barely or never. Round 1's rows keep their 1e-4
  floor; the ledger print notes it.
* **BH per batch:** Benjamini-Hochberg at q = 0.10 over the K values of p of the batch (W 6). A pick without a defined p
  enters with p = 1.
* **A pick PASSES** = P0, P1, P3, P4, both seed-rank parts, and a BH-significant p within its batch.
* **Batches:** batch 1 is tested; batch n + 1 only when **at least 5** picks of batch n PASS; untested members are
  listed as "untested" and never run on test.
* **R2 PASS** = at least one PASS. Reported beside v1 PASS, WIDE PASS and track 2, never merged with them.
* Long steps resume under the pin's hash (W 6, W 10).

## 8. Program-wide ledger

* The test step writes a **dated ledger snapshot** into `test.json`: every test-period hypothesis known at that moment
  (the v1 pick; every tested wide batch; every round-1 read that prints a p; track 2's picks; round 2's picks), with a
  global BH at q = 0.10 and Holm at 0.05, m, and the line **"four studies share one 33-month period; the full grid's
  711 test-period hypotheses (old six, house exits) are not in the ledger"**.
* Inputs: each study's public `test.json` and reads files, and the private DeepSeek p-values from each study's private
  file (T2 13; W 11), read by path. A p that is not available enters with p = 1 and is listed "p not available"; m
  counts it. DeepSeek rows show labels only in public.
* O1, O1b and O4 on round-2 rows each count as one look at the test period, as in round 1; they print no p, so they add
  no hypothesis. The number of looks is printed beside m.
* The ledger changes no verdict of any study. It is built by this study's own pinned module (`ledger.py`) following
  T2 13's rule; when track 2's ledger code is pinned by then, a parity test against it on synthetic inputs is required.
* The same module recomputes the snapshot on any later decision date (owner decision 16.1).

## 9. Reads after the verdict (never a pass)

### 9.1 Read guard

H 14 and W 7.1 apply as written: reads run only on ROWS, after `picks.json` is hashed; read code is listed in the pin
before `test.json` exists; outputs go to their own files (`research/hunt_r2/out/reads_*.json`); a read never changes
the picks, batches, P0-P4, p, BH, PASS, R2 PASS or the lineup; the code refuses to write (ReadGuardError) when any file
of the output folder or `picks.json` changed while a read ran; a read added after the test is seen is post hoc, in
`DEVIATIONS.md`.

**ROWS:** every tested pick (pass or fail); the batch-1 all-K basket (one wallet, H 8 caps shared, same-close order by
30-day quote volume then pick number, labelled "not a candidate"); the passing basket when at least two pass.

### 9.2 Reads on ROWS

* **New 24 only** (W 7.0): a passing pick with new-24 test mean ln M <= 0 is labelled "carried by the old six".
* **Extra 2020** at r = 0.5% and 1%; the **r = 1% line** (P0-P4 and both seed-rank parts, controls rerun at 1%) and the
  **cost x2 line at 1%**.
* **Select-period controls**, seeds 1-200.
* **R1 goal board** (W 7.3) with the headline cell and the size fixed on select (W 7.1), multiples only.
* **R12 / R13 basics** (W 7.3), plus the correlation of monthly ln M with the anchor default's.
* **R14 forward band** and **R19 1m + mark fidelity** for passing picks only (W 7.3, 7.4); R14's output hashed before
  the paper bot uses it.
* **O4 momentum label** (W 7.4a): "momentum only" when a plain momentum entry at the pick's times did as well.
* **Clustered coin flip (b-c)** beside (b): one fair coin per signal-bar close shared by all coins (seed parts with
  control "bc", seeds 1-1,000); mean d_m with a month-block 90% CI and the seed rank; **no p printed**.
* **Custom minus default** (the question the owners asked): the anchor default runs once on test as a comparator (the
  same system as round 1's R22 (1) ran, recomputed by round-2 code); per pick, monthly d = ln M(pick) - ln M(anchor
  default), its mean and a month-block 90% CI, labelled **"tuning helped"** when the CI lies above 0 and **"no better
  than the textbook numbers"** otherwise. No p, no ledger entry.

### 9.3 Weekend (owners' decision (j), W 0.1)

For every row, whatever its timeframe (so all four timeframes are covered; the autopsy's 4h result is reported, not
presumed): **"주말 포함 (시험한 기계, 판정 기준)"** beside **"주말 제외 (읽기)"** (O1: first-unit entries whose signal bar
closes from Saturday 00:00 to Monday 00:00 UTC skipped), plus **O1b** (longs only skipped); select and test side by
side: mean and median monthly ln M, win share, positions, max drawdown, cost x2 mean ln M; controls (a) and (b), seeds
1-200, through the same weekend-skip machine; pick-minus-control d_m with a 90% CI; the R1 headline shares (end and
touch x2 and x5) at the size fixed on select. A weekend rule becomes a rule only through a later round.

### 9.4 20 / 30 / 40x (owners' decision (f))

R24 as round 1 (W 7.3): the rule bot's sizing (v3 tiers, walk 40 -> 30 -> 20, its three checks), fresh $1,000;
calendar months and rolling 30-day windows, select beside test; shares of windows ending at and touching x2, x5, x10,
x20, x30, x50, x100; liquidations and skips by reason; controls seeds 1-100; also under the weekend skip; multiples
only, labelled **"규칙봇식 크기 읽기, 시험한 기계 아님, 통과 기준 아님"**.

### 9.5 Goal board

R1 as round 1 (W 7.3): calendar months (headline) and rolling 30-day windows, sizes r = 0.5-20% on machines A and B,
shares ending at and touching x2..x100, bust share, controls (a) and (b), Clopper-Pearson and block-bootstrap
intervals; the headline cell (test months in which a fresh $1,000 at goal-mode r = 5% touched x5) and the size fixed on
select. Multiples only (owners (e)).

### 9.6 Sealed calibration (R2-22; owner decision 16.2, default yes)

After `test.json` and the verdict are written and hashed, every candidate's would-be pick (hurdle passers and failers,
4.4) runs once on test at base cost. Public, F1, F2 and F5 rows only: the Spearman correlation of P_c against test
mean ln M, and test mean ln M of hurdle passers against failers (median and share above 0). Per-system numbers go only
to a private file whose sha256 is in the repository. Nothing in this read can become a candidate, a paper account or a
rule.

## 10. Lineup, what a result means, D11

### 10.1 Lineup (W 12, unchanged)

**정식** = PASS. **참고** = round 1's rule (g): a tested pick with test mean monthly ln M > 0, median monthly multiple
>= 1, mean ln M above both controls' seed means, cost x2 mean ln M > 0, max drawdown < 50%, no bust, best month < 50% of
the total log gain. Everything else is excluded. Written to `test.json` as `lineup`.

### 10.2 What a result means

| result | then |
|---|---|
| R2 PASS | each passing pick (정식) joins the forward paper bot beside round 1's lineup, r = 0.5% and 1%, $5,000 each; real money only after W 12's forward criteria and live-readiness gate, never before the mid-November 2026 review, and (owner decision 16.1) only if it also passes the ledger's global BH at q = 0.10 on the decision date; otherwise it is labelled **"정식 (장부 미통과)"** and stays paper only |
| a pick fails | recorded with its numbers (DeepSeek: labels); 참고 or excluded by 10.1; never real money |
| no candidate taken, or every box fails | round 2 fails at selection; recorded with every select-period count; nothing runs on test; no ledger hypothesis |
| R2 fail after the test | recorded; **no tuning on the test period**; a later version is a new pre-registration with one new look |

* The paper bot records round-2 picks (tested, any verdict) like every hunt system, recomputed from 2026-10-01; forward
  data counts only from the date of 0.5. It must load at least the longest lookback of the picked numbers plus 300 bars
  of each timeframe (lookbacks up to 3x exceed the bots' current windows; for example TURTLE55's entry channel at 3x on
  15m is 15,840 bars).
* Two to four studies share the test period; the report says so beside every verdict and never merges them.

### 10.3 A bug after the test

As H 15: fixed in `DEVIATIONS.md` with the line it breaks, the test rerun once, both results shown; the rerun's verdict
is the verdict.

### 10.4 DeepSeek money (D11)

As W 11: DeepSeek rows in repository files show counts, win shares, ranks, pick numbers and labels only. Their S, S2,
P_c, P_c2, P_f, the null thresholds at their ranks, ln M, multiples, drawdowns, p-values and d_m go only to a private
file outside the repository whose sha256 is in the public output. The writer refuses a float under a DeepSeek row.

## 11. Code, tests and pin (`research/hunt_r2/`)

* **Files** (names indicative; the pin lists what exists): `lattice.py` (F1 and F5 declarations, the order table,
  coarse and box builders, `counts.json`), `entries_r2.py` (the combo-taking F1 function; adapters to the full grid's
  signal functions and `famous_raw`), `select_r2.py` (Stage 0, A, nulls, hurdle, Stage B, `picks.json`), `pretest_r2.py`
  (section 6), `confirm_r2.py` (section 7), `ledger.py` (section 8), `reads_r2.py` (section 9), `hunt_r2.py` (command
  line: `counts`, `bench`, `pinlist`, `select`, `pretest`, `test`, `reads`), tests under `tests/test_hunt_r2*.py`.
* **Imports read-only:** `research/hunt` (hunt.py, entries_wide.py) with hashes equal to round 1's pin lines (or an
  inherited fix, 0.3), and `research/fullgrid` under its pin; the select and test steps refuse otherwise.
* **Memo and caches:** the full grid's indicator memo (`memo.py`) and the DeepSeek `cache` are cleared once per coin x
  timeframe series, not per combo. A test checks, on synthetic bars, that every name over a lattice sample gives
  identical events with the memo and cache kept across combos and with a fresh one per combo; a name that fails uses a
  fresh cache per combo.
* **Synthetic parity tests** (no real price): the F1 function equals `hunt_raw` at the defaults; default combos of F2,
  F3 and F5 equal `entries_wide` events bit for bit; the round-1 engine digest (W 10) is unchanged; lattice and box
  builders against `grid.values` and `valid_r2`; null transforms (one flip per coin and close across systems, wrap,
  time of day kept, drop counts); hurdle, ranking and refinement logic on hand-made score tables; the default-in-effect
  and two-name rules; the D11 writer; refusal without the pin, without the picks line, and before `test.json` for
  reads.
* **Work units** = (name, timeframe, coin) for signals and (replicate, name) for null replays, heaviest first (N05,
  V45, V39 at 15m), with resumable part files under the pin's hash; results do not depend on the worker count.
* **Bench:** `hunt_r2 bench` on synthetic bars writes `bench_r2.json` (seconds per signal combo per series and per
  engine run, by timeframe), listed in the pin. If select extrapolates beyond 8 hours wall on the server, the owners
  are told before renting; nothing is cut.
* **Pin:** `research/hunt_r2/PREREG_HUNT_R2.sha256`, first line the design hash (0.1); at the code pin, what
  `hunt_r2 pinlist` prints: this file, the code and tests, `counts.json`, `bench_r2.json`, and as read-only inputs
  checked by hash `research/hunt/PREREG_HUNT_WIDE.sha256` (whose listed files must match),
  `research/fullgrid/PREREG.sha256`, `research/entry_study/DEFS_BC.sha256`, `third_party/sweep/PREREG.sha256`,
  `research/hunt/data_manifest.json` and every repository Python file the signal code loads (found as W 10 finds it).
  Later lines: `picks.json`, `pretest_reads.json`, the reads modules (before `test.json`), `test.json`, R14's output.
* **Nothing runs on real prices on the development machine** (about 1.6 GB free). Select and test run from one fixed
  checkout of the pinned commit (W 15 Q15).

## 12. Compute plan (one Vultr vx1-g-32c-128g, 32 vCPU, about $1.2/h, about 27 effective cores)

| step | estimate |
|---|---|
| coarse signals, all 15,121 (name, timeframe, combo) cells x 30 coins | 6-24 CPU-h (signal timing x lattice size; N05_PSAR_POC at 15m about a fifth of it) |
| real Stage 0 + A (base and cost x2) | about 9,000 engine runs, under 1 CPU-h |
| nulls: 200 replicates x about 4,400 runs (670 defaults + the replicate's anchor lattices, base only) | about 880,000 runs, 41-51 CPU-h at 0.17-0.21 s per 36-month 30-coin run (up to 100 with a 2x margin for busy NONE systems) |
| Stage B (taken names and would-be picks, signals + runs) | at most 11 CPU-h |
| **select in total** | **55-82 CPU-h (at most about 140); 2-5 h wall** |
| test, batch 1 (10 picks x 4,400 control runs, as W 10) | 2-3 CPU-h, about 6 minutes wall |
| reads (section 9; R19 needs a 1m download of the traded coins) | 6-15 h wall |
| **total on the server** | **about 9-20 h, about $11-25** |
| verdict path only (select, pretest, test) | about 3-6 h, about $4-7 |

**Order (never two servers at once; the Vultr fee limit allows one 32 vCPU server):**

1. Design hash now (0.1).
2. Round 1 ends; its results are pushed; its server is Destroyed.
3. Track 2's select runs on its own server (about 8-9 h, T2 17.4); that server is Destroyed.
4. Round 2's code is written, reviewed and pinned (about 2026-10-13 .. 10-15).
5. `hunt-r2-compute`: select, the picks hash, pretest reads, test, reads, push, Destroy.
6. Track 2's confirm look runs whenever its picks are hashed, on its own server, never beside another.

## 13. Power, stated up front

For a lone true pick in a batch of 10 (BH needs p <= 0.10 x 1 / 10 = 0.01), and in a ledger of m = 50 (global BH for a
lone discovery needs p <= 0.002), with 33 test months and a normal approximation of the month-block test:

| annual information ratio of the pick against the controls | chance to pass batch BH | chance to pass the ledger at m = 50 |
|---|---|---|
| 1.0 | 25% | 11% |
| 1.5 | 56% | 35% |
| 2.0 | 84% | 67% |
| 2.5 | 97% | 90% |

* The other pass conditions (both controls, seed ranks, P0-P4) lower these numbers.
* If track 2 adds hundreds of hypotheses, the ledger needs an information ratio of about 2 or more.
* A smaller K after the hurdle loosens the batch threshold to 0.10 / K.
* **The most likely result is no pass.** The autopsy found coin-flip direction at the defaults, and the full grid's
  custom values collapsed. The design makes a no-pass result cheap (often decided before the test) and lets a strong
  edge through.

## 14. Known limits and risks

* **Reuse of the test period.** 2024-01 .. 2026-09 has been looked at by the full grid, v1, wide (and its reads), track
  2 and now round 2: at least the fifth family of looks. The ledger prices the looks it knows; it cannot price what
  people remember.
* **Close relatives.** Round-2 picks share their anchor's entry, timeframe and gate with a round-1 system; their test
  results are correlated with round 1's.
* **Code written after round 1's results exist.** The rules are fixed here first; the code follows them; review checks
  the code against this text, and the forward-count date moves with any rule change (0.5).
* **Leakage in people's heads:** the full grid's old-six tables on 2024-2026 (labels in 5, "old six not blind").
* **The null is an approximation.** (b′) keeps times and clustering but not the side's link to momentum; (a′) keeps
  each list's internal clustering and time of day but moves weekdays and market states. Neither is exact; requiring
  both helps.
* **The hurdle is lenient by design** (about 15-25% of pure-noise searches clear it at rank 1); the test carries the
  rest.
* **Anchor lock-in:** numbers are searched only at the timeframe and gate where the default did best; a setting that
  works only elsewhere is not found.
* **Coarse steps** (½x, 1x, 2x) can miss a narrow optimum between them; that is intended (a narrow optimum is the kind
  that failed in the full grid).
* **Lookbacks up to 3x** exceed the live bots' current data windows (10.2).
* **r = 0.5%** is far from the owners' x5-x100 goal; the goal board and R24 are reads, not the tested machine.
* **D11:** DeepSeek results in public files are labels and ranks only.

## 15. Not in this study

Exits, stop width, adds and r as choices; the 장세 label's numbers and other gates; weekend, FOMC/NFP and same-side
rules (reads only); new-information entries; per-coin numbers; combining entries; F4 numbers; coins outside the 30;
timeframes other than 15m-4h; the AI judgment layer. Each is its own later round under W 14.

## 16. Open questions (closed before the code pin; default in brackets)

Owners:

1. **Ledger before small live:** a round-2 정식 must also pass the ledger's global BH at q = 0.10 on the decision date,
   or it is "정식 (장부 미통과)" and paper only. [yes]
2. **R2-22 sealed calibration read** (9.6). [yes]
3. **Track 2 runs before round 2** (12). [yes, as already decided]
4. **Hurdle at the 75th percentile of both nulls** (4.3); the alternative is the 90th, stricter, fewer names. [keep the
   75th]

Technical (the main session closes them at the code review, recorded in `DEVIATIONS.md`):

5. (a′) shift in whole days (weekday mix moves) or whole weeks (keeps weekdays). [whole days, as written]
6. The default-in-effect hash covers all 30 coins' gated select events at the anchor timeframe and gate. [as written]
7. A value reached from two coarse factors takes the factor nearest 1x (3.5). [as written]
8. A name whose DeepSeek cache or memo cannot be shared across combos uses a fresh one per combo (11). [as written]
9. A fourth batch. [none; at most 30 picks]
10. If the bench (11) puts select above 8 hours wall: tell the owners, rent anyway, cut nothing. [as written]

## 17. Before this file was fixed

* 2026-10-11, about 22:40-23:20 UTC: three designs for round 2 were written by separate agents (a broad 9-step grid
  with a one-step-cube plateau; a 5-step lattice with a ±1 box and a 2021-22 / 2023 split; a staged design anchored on
  the defaults with a coarse lattice, a null of the whole search and a local refinement). A judge scored them on
  protection against false passes, power, fidelity to the owners' process, compute and clarity, chose the staged
  design and grafted parts of the other two (100,000 resamples, the default-in-effect rule, run-regardless,
  labels instead of exclusions, resumable units, the bench rule, order rules, the 2023 lift and leave-one-year-out
  reads, the near-miss table, custom minus default, the owner wording).
* Facts checked for it from files and code only: the full-grid figure is per trade (0.4); `grid.valid` has no
  fast < slow rules; the lattice counts of 3.4-3.6 (`lattice.py`'s planned rule run on the definitions, no data); round
  1's `N_BOOT = 10_000` (`hunt.py` line 100); R22 (1) and (2) run round-1 candidates and pick neighbours on test (W 6).
* Timings: signal-function seconds per coarse combo on one coin's practice-period bars (5m cut at 2024-01-01, signals
  only, no outcome) and on synthetic bars; engine seconds per run on synthetic bars (round 1's 0.15-0.21 s per
  33-36-month 30-coin run, W 10, and 0.14-0.52 s at 1 signal per 2 to per 0.1 days per coin). No trading outcome was
  computed on any real price period for this design.
* Nothing of round 1's output was seen (0.2).

## Appendix A. The 85 names: numbers, kinds, defaults and coarse values

Kinds: len = length (bars; F5: days), mult = multiplier, abs = absolute threshold, neu = threshold with a neutral point.
Coarse values are listed in factor order ½x / 1x / 2x (f = 0.5 / 1 / 1.5 for neu); a missing value was dropped by
its bounds or merged by rounding. **coarse** = points after `valid_r2`; **box** = the largest fine box over every
possible coarse peak; **tries** = the most systems the selection can try for the name (Stage 0 + coarse - 1 + box -
1). Code only; no data read.

| fam | name | tf | numbers: default: coarse values | coarse | box | tries |
|---|---|---|---|---|---|---|
| F1 | E1 | 4 | channel (len) 55: 28 / 55 / 110; vol_len (len) 20: 10 / 20 / 40; vol_mult (neu) 2: 1.5 / 2 / 2.5 | 27 | 27 | 60 |
| F1 | E2 | 4 | window (len) 120: 60 / 120 / 240; pct (abs) 20: 10 / 20 / 40; bb_len (len) 20: 10 / 20 / 40; bb_k (mult) 2: 1 / 2 / 4 | 81 | 81 | 168 |
| F1 | E3 | 4 | threshold (neu) 1.5: 1.25 / 1.5 / 1.75; fast (len) 14: 7 / 14 / 28; slow (len) 100: 50 / 100 / 200; side_len (len) 20: 10 / 20 / 40 | 81 | 81 | 168 |
| F2 | DOGE | 4 | ema_slow (len) 156: 78 / 156 / 312; stoch_len (len) 70: 35 / 70 / 140; spread_min (abs) 0.15: 0.075 / 0.15 / 0.3; chop_max (abs) 61.8: 30.9 / 61.8 | 54 | 81 | 141 |
| F2 | N01_ST_EMA | 4 | ema_fast (len) 5: 3 / 5 / 10; ema_slow (len) 20: 10 / 20 / 40; st_atr_len (len) 10: 5 / 10 / 20; st_mult (mult) 6: 3 / 6 / 12 | 72 | 81 | 159 |
| F2 | N02_ST_KST | 4 | st_atr_len (len) 10: 5 / 10 / 20; st_mult (mult) 6: 3 / 6 / 12; kst_roc_lens (len) (10,15,20,30): (5,8,10,15) / (10,15,20,30) / (20,30,40,60); kst_signal_len (len) 9: 5 / 9 / 18 | 81 | 81 | 168 |
| F2 | N03_ADX_GC | 4 | ema_fast (len) 50: 25 / 50 / 100; ema_slow (len) 200: 100 / 200 / 400; adx_len (len) 14: 7 / 14 / 28; adx_level (abs) 25: 12.5 / 25 / 50 | 72 | 81 | 159 |
| F2 | N04_ST_KLINGER | 4 | st_atr_len (len) 10: 5 / 10 / 20; st_mult (mult) 6: 3 / 6 / 12; kvo_lens (len) (34,55): (17,28) / (34,55) / (68,110); kvo_signal_len (len) 13: 7 / 13 / 26 | 81 | 81 | 168 |
| F2 | N05_PSAR_POC | 4 | poc_lookback (len) 100: 50 / 100 / 200; poc_tol (abs) 0.2: 0.1 / 0.2 / 0.4; pierce_frac (abs) 0.5: 0.25 / 0.5 / 1; sar_af (mult) 0.02: 0.01 / 0.02 / 0.04 | 81 | 81 | 168 |
| F2 | N06_MACD_ORB | 4 | macd_fast (len) 12: 6 / 12 / 24; macd_slow (len) 26: 13 / 26 / 52; macd_signal (len) 9: 5 / 9 / 18; ext_cap (mult) 1.5: 0.75 / 1.5 / 3 | 72 | 81 | 159 |
| F2 | N07_ICHI_CMO | 4 | tenkan_len (len) 9: 5 / 9 / 18; kijun_len (len) 26: 13 / 26 / 52; senkou_b_len (len) 52: 26 / 52 / 104; cmo_len (len) 14: 7 / 14 / 28 | 45 | 81 | 132 |
| F2 | N08_ICHI_WR | 4 | tenkan_len (len) 9: 5 / 9 / 18; kijun_len (len) 26: 13 / 26 / 52; wr_len (len) 14: 7 / 14 / 28; wr_oversold (neu) -80: -65 / -80 / -95 | 72 | 81 | 159 |
| F2 | N09_ALLIG_AROON | 4 | lips_len (len) 5: 3 / 5 / 10; teeth_len (len) 8: 4 / 8 / 16; jaw_len (len) 13: 7 / 13 / 26; aroon_len (len) 25: 13 / 25 / 50 | 30 | 72 | 108 |
| F2 | N10_HA_PSAR | 4 | sar_af_start (mult) 0.02: 0.01 / 0.02 / 0.04; sar_af_step (mult) 0.02: 0.01 / 0.02 / 0.04; sar_af_max (mult) 0.2: 0.1 / 0.2 / 0.4; wick_tol (abs) 0.02: 0.01 / 0.02 / 0.04 | 81 | 81 | 168 |
| F2 | N11_BREAKAWAY | 4 | big_body (abs) 0.8: 0.4 / 0.8; small_body (abs) 0.4: 0.2 / 0.4 / 0.8; gap_tol (abs) 0.05: 0.025 / 0.05 / 0.1; prior_n (len) 5: 3 / 5 / 10 | 27 | 81 | 114 |
| F2 | N12_ICHI_AO | 4 | tenkan_len (len) 9: 5 / 9 / 18; kijun_len (len) 26: 13 / 26 / 52; ao_fast_len (len) 5: 3 / 5 / 10; ao_slow_len (len) 34: 17 / 34 / 68 | 72 | 81 | 159 |
| F2 | N13_3OUTSIDE | 4 | engulf_min (abs) 0.5: 0.25 / 0.5 / 1; prior_n (len) 5: 3 / 5 / 10; atr_len (len) 14: 7 / 14 / 28 | 27 | 27 | 60 |
| F2 | N14_ICHI_RSI | 4 | tenkan_len (len) 9: 5 / 9 / 18; kijun_len (len) 26: 13 / 26 / 52; rsi_len (len) 14: 7 / 14 / 28; rsi_oversold (neu) 30: 40 / 30 / 20 | 72 | 81 | 159 |
| F2 | N15_KC_AO | 4 | kc_len (len) 20: 10 / 20 / 40; kc_mult (mult) 2: 1 / 2 / 4; ao_fast (len) 5: 3 / 5 / 10; ao_slow (len) 34: 17 / 34 / 68 | 81 | 81 | 168 |
| F2 | N16_BBRSI | 4 | bb_len (len) 20: 10 / 20 / 40; rsi_len (len) 14: 7 / 14 / 28; map_scale (mult) 2: 1 / 2 / 4; pivot_len (len) 3: 2 / 3 / 6 | 81 | 81 | 168 |
| F2 | N17_KC_RSI | 4 | kc_len (len) 20: 10 / 20 / 40; kc_mult (mult) 2: 1 / 2 / 4; rsi_len (len) 14: 7 / 14 / 28; rsi_level (neu) 30: 40 / 30 / 20 | 81 | 81 | 168 |
| F2 | N18_VWMA_MACD | 4 | vwma_len (len) 20: 10 / 20 / 40; macd_fast (len) 12: 6 / 12 / 24; macd_slow (len) 26: 13 / 26 / 52; macd_signal (len) 9: 5 / 9 / 18 | 72 | 81 | 159 |
| F2 | N19_FIB_CHOP | 4 | range_len (len) 34: 17 / 34 / 68; fib_level (mult) 0.5: 0.25 / 0.5 / 1; touch_atr (mult) 0.2: 0.1 / 0.2 / 0.4; slope_thr (abs) 0.2: 0.1 / 0.2 / 0.4 | 81 | 81 | 168 |
| F2 | N20_EMA9_CHOP | 4 | ema_len (len) 9: 5 / 9 / 18; adx_len (len) 14: 7 / 14 / 28; adx_thr (abs) 20: 10 / 20 / 40 | 27 | 27 | 60 |
| F2 | N21_ST_RSI_ADX | 4 | st_mult (mult) 6: 3 / 6 / 12; adx_len (len) 14: 7 / 14 / 28; adx_level (abs) 25: 12.5 / 25 / 50; rsi_level (neu) 30: 40 / 30 / 20 | 81 | 81 | 168 |
| F2 | N22_VORTEX_PSAR | 4 | vi_len (len) 14: 7 / 14 / 28; psar_start (mult) 0.02: 0.01 / 0.02 / 0.04; psar_step (mult) 0.02: 0.01 / 0.02 / 0.04; psar_max (mult) 0.2: 0.1 / 0.2 / 0.4 | 81 | 81 | 168 |
| F2 | N23_HA_ST | 4 | st_atr_len (len) 10: 5 / 10 / 20; st_mult (mult) 6: 3 / 6 / 12; wick_tol (abs) 0.02: 0.01 / 0.02 / 0.04 | 27 | 27 | 60 |
| F2 | N24_DMI | 4 | di_len (len) 14: 7 / 14 / 28; adx_len (len) 14: 7 / 14 / 28; adx_long_min (abs) 25: 12.5 / 25 / 50; adx_short_max (abs) 25: 12.5 / 25 / 50 | 81 | 81 | 168 |
| F2 | N25_DST_CCI | 4 | cci_len (len) 20: 10 / 20 / 40; cci_level (neu) 100: 50 / 100 / 150; st_fast_mult (mult) 6: 3 / 6 / 12; st_slow_mult (mult) 6: 3 / 6 / 12 | 81 | 81 | 168 |
| F2 | OBV_B | 4 | break_len (len) 9: 5 / 9 / 18; ao_fast (len) 5: 3 / 5 / 10; ao_slow (len) 34: 17 / 34 / 68; ac_len (len) 5: 3 / 5 / 10 | 81 | 81 | 168 |
| F2 | OBV_S | 4 | obv_ma_len (len) 30: 15 / 30 / 60; stc_level (neu) 70: 60 / 70 / 80; stoch_k_smooth (len) 4: 2 / 4 / 8; ao_slow_len (len) 34: 17 / 34 / 68 | 81 | 81 | 168 |
| F2 | S1_EMA_RSI_CHOP | 4 | ema_slow (len) 20: 10 / 20 / 40; rsi_len (len) 14: 7 / 14 / 28; rsi_level (neu) 30: 40 / 30 / 20; chop_len (len) 34: 17 / 34 / 68 | 81 | 81 | 168 |
| F2 | S2_ST_ROC | 4 | st_atr_len (len) 10: 5 / 10 / 20; st_mult (mult) 6: 3 / 6 / 12; roc_len (len) 9: 5 / 9 / 18 | 27 | 27 | 60 |
| F2 | S3_CMO_SANDWICH | 4 | cmo_len (len) 14: 7 / 14 / 28; body_min (mult) 0.08: 0.04 / 0.08 / 0.16; match_tol (mult) 0.3: 0.15 / 0.3 / 0.6; prior_n (len) 5: 3 / 5 / 10 | 81 | 81 | 168 |
| F2 | S4_BB_BBP | 4 | bb_len (len) 20: 10 / 20 / 40; bb_mult (mult) 2: 1 / 2 / 4; sq_lookback (len) 100: 50 / 100 / 200; sq_pct (abs) 0.2: 0.1 / 0.2 / 0.4 | 81 | 81 | 168 |
| F2 | S5_DONCHIAN_MFI | 4 | dc_len (len) 20: 10 / 20 / 40; mfi_len (len) 14: 7 / 14 / 28; mfi_level (neu) 30: 40 / 30 / 20; sync (len) 3: 2 / 3 / 6 | 81 | 81 | 168 |
| F2 | S6_EMA_DMI_ADX | 4 | ema_len (len) 20: 10 / 20 / 40; di_len (len) 14: 7 / 14 / 28; adx_len (len) 14: 7 / 14 / 28; adx_min (abs) 25: 12.5 / 25 / 50 | 81 | 81 | 168 |
| F2 | V39_ALL | 4 | st_mult (mult) 3: 1.5 / 3 / 6; dmi_len (len) 20: 10 / 20 / 40; dmi_gap (abs) 2: 1 / 2 / 4; stoch_len (len) 14: 7 / 14 / 28 | 81 | 81 | 168 |
| F2 | V45_AMB | 4 | st_mult_main (mult) 6: 3 / 6 / 12; st_mult_strict (mult) 3: 1.5 / 3 / 6; htf_st_mult (mult) 6: 3 / 6 / 12; stoch_len (len) 14: 7 / 14 / 28 | 81 | 81 | 168 |
| F3 | F1_RSI_DIV | 4 | swing_k (len) 3: 2 / 3 / 6; div_max_bars (len) 60: 30 / 60 / 120; rsi_len (len) 14: 7 / 14 / 28 | 27 | 27 | 60 |
| F3 | F1_MOM_DIV | 4 | swing_k (len) 3: 2 / 3 / 6; div_max_bars (len) 60: 30 / 60 / 120; mom_len (len) 10: 5 / 10 / 20 | 27 | 27 | 60 |
| F3 | F1_PVT_DIV | 4 | swing_k (len) 3: 2 / 3 / 6; div_max_bars (len) 60: 30 / 60 / 120 | 9 | 9 | 24 |
| F3 | F2_DEMARK | - | no numbers: out of round 2 | - | - | - |
| F3 | F3_BOS | 4 | swing_k (len) 3: 2 / 3 / 6 | 3 | 3 | 12 |
| F3 | F3_BOS_ZONE | 4 | swing_k (len) 3: 2 / 3 / 6; zone_life (len) 50: 25 / 50 / 100; ema_len (len) 200: 100 / 200 / 400 | 27 | 27 | 60 |
| F3 | F3_HHHL | 4 | swing_k (len) 3: 2 / 3 / 6 | 3 | 3 | 12 |
| F3 | F4_PULL | 4 | ema_fast (len) 9: 5 / 9 / 18; ema_mid (len) 50: 25 / 50 / 100; ema_slow (len) 200: 100 / 200 / 400 | 24 | 27 | 57 |
| F3 | F4_PULL_RSI | 4 | ema_fast (len) 20: 10 / 20 / 40; ema_slow (len) 50: 25 / 50 / 100; rsi_len (len) 14: 7 / 14 / 28; rsi_level (neu) 40: 45 / 40 / 35 | 72 | 81 | 159 |
| F3 | F4_FAN | 4 | fan_lens (len) (8,13,21,34,55): (4,7,11,17,28) / (8,13,21,34,55) / (16,26,42,68,110) | 3 | 3 | 12 |
| F3 | F5_BOX | 4 | box_len (len) 48: 24 / 48 / 96; adx_max (abs) 20: 10 / 20 / 40; edge (mult) 0.15: 0.075 / 0.15 / 0.3; width_atr (mult) 3: 1.5 / 3 / 6 | 81 | 81 | 168 |
| F3 | F5_BOX_RSI | 4 | box_len (len) 48: 24 / 48 / 96; adx_max (abs) 20: 10 / 20 / 40; edge (mult) 0.15: 0.075 / 0.15 / 0.3; rsi_level (neu) 30: 40 / 30 / 20 | 81 | 81 | 168 |
| F3 | F5_BOX_HTF | 4 | box_len (len) 48: 24 / 48 / 96; adx_max (abs) 20: 10 / 20 / 40; edge (mult) 0.15: 0.075 / 0.15 / 0.3; width_atr (mult) 3: 1.5 / 3 / 6 | 81 | 81 | 168 |
| F3 | F6_VWAP_CROSS | - | no numbers: out of round 2 | - | - | - |
| F3 | F6_VWAP_FAIL | 4 | fail_bars (len) 10: 5 / 10 / 20 | 3 | 3 | 12 |
| F3 | F7_RF_TRIPLE | 4 | rf_period (len) 100: 50 / 100 / 200; rf_mult (mult) 3: 1.5 / 3 / 6 | 9 | 9 | 24 |
| F3 | F7_RF_ONLY | 4 | rf_period (len) 100: 50 / 100 / 200; rf_mult (mult) 3: 1.5 / 3 / 6 | 9 | 9 | 24 |
| F3 | F8_VWICK | 4 | body_frac (mult) 0.7: 0.35 / 0.7; body_atr (mult) 1.3: 0.65 / 1.3 / 2.6; zone_life (len) 50: 25 / 50 / 100 | 18 | 27 | 51 |
| F3 | F9_FVG | 4 | fvg_min_atr (mult) 0.5: 0.25 / 0.5 / 1; zone_life (len) 50: 25 / 50 / 100 | 9 | 9 | 24 |
| F3 | F9_IFVG | 4 | fvg_min_atr (mult) 0.5: 0.25 / 0.5 / 1; zone_life (len) 50: 25 / 50 / 100 | 9 | 9 | 24 |
| F3 | F9_OB | 4 | zone_life (len) 50: 25 / 50 / 100 | 3 | 3 | 12 |
| F3 | F9_BREAKER | 4 | zone_life (len) 50: 25 / 50 / 100 | 3 | 3 | 12 |
| F3 | F10_M2022 | 4 | swing_k (len) 3: 2 / 3 / 6; disp_atr (mult) 1.2: 0.6 / 1.2 / 2.4; sweep_bars (len) 20: 10 / 20 / 40; fvg_min_atr (mult) 0.5: 0.25 / 0.5 / 1 | 81 | 81 | 168 |
| F3 | F10_OTE | 4 | swing_k (len) 3: 2 / 3 / 6; leg_atr (mult) 3: 1.5 / 3 / 6; leg_max_bars (len) 30: 15 / 30 / 60 | 27 | 27 | 60 |
| F3 | F11_TSOUP | 4 | tsoup_len (len) 20: 10 / 20 / 40; min_age (len) 4: 2 / 4 / 8 | 9 | 9 | 24 |
| F3 | F11_RAID | 4 | swing_k (len) 3: 2 / 3 / 6 | 3 | 3 | 12 |
| F3 | F11_PO3 | 4 | po3_range_h (len) 8: 4 / 8 / 16; po3_rev_bars (len) 3: 2 / 3 / 6 | 9 | 9 | 24 |
| F3 | F12_MSS | 4 | swing_k (len) 3: 2 / 3 / 6 | 3 | 3 | 12 |
| F3 | F12_MSS_DISP | 4 | swing_k (len) 3: 2 / 3 / 6; disp_atr (mult) 1.2: 0.6 / 1.2 / 2.4 | 9 | 9 | 24 |
| F3 | F13_FVG_PD | 4 | swing_k (len) 3: 2 / 3 / 6; fvg_min_atr (mult) 0.5: 0.25 / 0.5 / 1; zone_life (len) 50: 25 / 50 / 100 | 27 | 27 | 60 |
| F3 | F13_RAID_PD | 4 | swing_k (len) 3: 2 / 3 / 6 | 3 | 3 | 12 |
| F3 | F14_SMT | 4 | smt_len (len) 20: 10 / 20 / 40 | 3 | 3 | 12 |
| F3 | F15_ASIA_BRK | 3 (no 4h) | asia_win_h (len) 8: 4 / 8 / 16 | 3 | 3 | 10 |
| F3 | F15_ASIA_SWEEP | 3 (no 4h) | asia_win_h (len) 8: 4 / 8 / 16 | 3 | 3 | 10 |
| F3 | F15_LON_BRK | 3 (no 4h) | lon_win_h (len) 7: 4 / 7 / 14 | 3 | 3 | 10 |
| F3 | F15_OPEN0930 | 3 (no 4h) | judge_min (len) 60: 30 / 60 / 120 | 3 | 3 | 10 |
| F3 | F15_OPEN0000 | 3 (no 4h) | judge_min (len) 60: 30 / 60 / 120 | 3 | 3 | 10 |
| F3 | F15_ORB | 4 | orb_bars (len) 2: 2 / 4 | 2 | 3 | 11 |
| F3 | F16_FIB382 | 4 | swing_k (len) 3: 2 / 3 / 6; leg_atr (mult) 3: 1.5 / 3 / 6; leg_max_bars (len) 30: 15 / 30 / 60; zone_life (len) 50: 25 / 50 / 100 | 81 | 81 | 168 |
| F3 | F16_FIB500 | 4 | swing_k (len) 3: 2 / 3 / 6; leg_atr (mult) 3: 1.5 / 3 / 6; leg_max_bars (len) 30: 15 / 30 / 60; zone_life (len) 50: 25 / 50 / 100 | 81 | 81 | 168 |
| F3 | F16_FIB618 | 4 | swing_k (len) 3: 2 / 3 / 6; leg_atr (mult) 3: 1.5 / 3 / 6; leg_max_bars (len) 30: 15 / 30 / 60; zone_life (len) 50: 25 / 50 / 100 | 81 | 81 | 168 |
| F3 | F16_FIB764 | 4 | swing_k (len) 3: 2 / 3 / 6; leg_atr (mult) 3: 1.5 / 3 / 6; leg_max_bars (len) 30: 15 / 30 / 60; zone_life (len) 50: 25 / 50 / 100 | 81 | 81 | 168 |
| F3 | F17_Z | 4 | z_len (len) 20: 10 / 20 / 40; z_level (abs) 2: 1 / 2 / 4 | 9 | 9 | 24 |
| F3 | F17_Z_HL | 4 | z_len (len) 20: 10 / 20 / 40; z_level (abs) 2: 1 / 2 / 4; hl_len (len) 100: 50 / 100 / 200; half_life (len) 20: 10 / 20 / 40 | 81 | 81 | 168 |
| F5 | TURTLE20 | 4 | entry_days (len) 20: 10 / 20 / 40; exit_days (len) 10: 5 / 10 / 20 | 6 | 9 | 21 |
| F5 | TURTLE55 | 4 | entry_days (len) 55: 28 / 55 / 110; exit_days (len) 20: 10 / 20 / 40 | 8 | 9 | 23 |
| F5 | TSMOM7 | 4 | lookback_days (len) 7: 4 / 7 / 14 | 3 | 3 | 12 |
| F5 | TSMOM28 | 4 | lookback_days (len) 28: 14 / 28 / 56 | 3 | 3 | 12 |
| | **total (85 names)** | | | **3,784** | **4,032** | **8,316** |
