# Trend hunt round 2, custom values (1번 트랙 2차, 커스텀값): pre-registration

(한국어 설명: `README_R2_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 개발자가 1차 결과를 보기 전에 해시로 고정하고,
그 뒤에는 고치지 않습니다. 나중에 고칠 수 있는 것은 코드가 이 글과 다를 때와 그대로는 돌릴 수 없는 단계뿐이며,
`research/hunt_r2/DEVIATIONS.md`에 날짜와 그때까지 본 것을 함께 적습니다. 규칙을 바꾸면 "2차 v2"(새 사전 등록, 시험 한 번
더)입니다.)

**Status: DRAFT design, written 2026-10-11 between about 22:40 and 23:50 UTC, revised after a three-lens review on
2026-10-12 between about 00:00 and 00:50 UTC (09:00-09:50 KST; section 18), before any output of round 1 (the trend
hunt, `research/hunt`) was seen, fetched or inferred by its authors or reviewers, and before any code of this study
existed. To be hashed at once (section 0.1).** After the design hash this text does not change. The code is written,
reviewed and pinned later (section 11); every later correction is an entry in `research/hunt_r2/DEVIATIONS.md` under
the rules of section 0.3. **No open question remains (section 16).**

Owners (2026-10-12, 07:40 KST), on the trend hunt: **"1번 트랙에서도 커스텀값을 찾아야지 왜 안찾는거야"**. Round 1 used
every entry at its default numbers on purpose and deferred custom values to a separate round with a plateau rule
(`PREREG_HUNT_WIDE.md` sections 0.1 and 14). This file is that round.

Section references: "H n" = `research/hunt/PREREG_HUNT.md` section n; "W n" = `research/hunt/PREREG_HUNT_WIDE.md`
section n (W R1-R24 and O1-O5 its reads); "T2 n" = `research/hiwr/PREREG_HIWR.md` (track 2) section n; "FG n" =
`research/fullgrid/PREREG.md` section n. Everything of H and W that this file does not change applies as written there.
Names: **track 1** = the trend hunt (round 1 = default numbers, running now; round 2 = this file, custom values);
**track 2** = the 70%-win-rate / drawdown-cap study (`research/hiwr`), a separate study.

## 0. What this is

* A **separate pre-registered study** (round 2 of track 1), judged as W 14 says: designed and selected on **2021-2023
  only**, confirmed **once** (version "hunt-r2 v1") on the test period 2024-01-01 .. 2026-10-01, every look counted in
  the program-wide ledger, forward paper data counted from the date of section 0.5.
* It searches **the numbers of the entries** (indicator lengths, multipliers, thresholds) of the round-1 candidate
  names, on the round-1 machine: a coarse lattice (½x, 1x, 2x of each number) at each name's best default slot, a
  plateau rule with a fixed-size neighbourhood, a step-down null hurdle that replays the whole search on no-skill
  entries, and a second test of whether the tuned numbers beat the textbook numbers. **The number of tries is not the
  guard; the hurdle and the test are** (0.4, 13).
* Research only: it touches nothing of the rule bot, the candidate league, round 1's pinned files or outputs, the full
  grid's pinned files, track 2, or any account.

### 0.1 Hash before round 1 is seen (timing)

* Round 1 (select and test of v1 and wide) has run on the owners' server since 2026-10-11 20:52 UTC at code commit
  0f18ecb (pin ca561234bd). Its verdict was expected about 22:52 UTC on that server's screen, which the owners hold.
  **This design must be fixed before the main session sees round 1's results; what the owners had seen at the hash is
  recorded.**
* Order: the main session writes this file's sha256 line (sha256sum format) as the first line of
  `research/hunt_r2/PREREG_HUNT_R2.sha256` (the **design hash**), commits this file, `README_R2_KO.md` and that line,
  and **pushes that commit to the remote before** it fetches, pulls or merges the hunt-results branch, opens the server
  screen, or reads or relays any message about round 1's results. The commit hash, **the remote's time for that push**
  (read from the remote, not from the local clock) and what the owners said they had seen of round 1 by then are
  written as the first entry of `research/hunt_r2/DEVIATIONS.md` (not into this file, so the design hash stays valid).
* This file states: **written, reviewed and hashed before any round-1 select, pick, test or read output (R22
  included) was seen, fetched or inferred by its authors and reviewers.** If anything from round 1 reached the main
  session before the hash push, that sentence is false for this hash: the main session writes what was seen, plainly,
  as the first entry of `DEVIATIONS.md` in the same commit, and that entry governs every later reading of this file.
* The owners may have seen round 1's verdict on their server screen before the hash. That cannot move this design:
  every choice is closed in this text (section 16), and no owner answer given after the hash changes it (0.3).

### 0.2 What the designers had seen

Seen, before writing this file:

* **The full grid's results** (`research/fullgrid`, ANALYSIS_KO.md and the per-strategy reports): its custom-value
  tables for the old six coins on 2021-2023 **and on 2024-01 .. 2026-09** (house exits, 1m, per-trade units), its 711
  picks and 0 passes, and the per-strategy grades.
* **The 38 F4 watch picks** (`research/fullgrid/diag/watch_sel.json`), kept because they were positive on 2024-2026 and
  2020 (W 3).
* **The loss autopsy** (`research/autopsy/LOSS_AUTOPSY.md`, select period only, plus the repo reports it quotes).
* **Track 2's select-period feasibility** (T2 22, 2021-2023 only) and its server guide (`research/hiwr/SERVER_KO.md`,
  times and costs only).
* **The owners' October live screens**: the rule bot's paper accounts, the candidate league and the demo lab in
  October 2026, as shown on their dashboards; any forward record of a hunt system shown on a dashboard before the hash
  is seen data (0.5).
* **Round 1's design, code and pinned inputs**: PREREG_HUNT.md, PREREG_HUNT_WIDE.md, hunt.py, entries_wide.py,
  reads_a.py, reads_o.py, the pin files, `data_manifest.json`, `data_check.json`, `bench_window.json` and the pinned
  `research/hunt/out/wide/parity.json` (signals only, W 8). A listing of `research/hunt/` on the development machine
  shows the folder `out`; one reviewer listed `research/hunt/out` at its top level only (one folder, `wide`). Nothing
  in it other than the pinned parity file is known to the authors or reviewers, and nothing in it was opened.
* **The review of section 18**: its findings and its toy simulations on synthetic numbers.

Not seen: **no round-1 select table, pick, batch, test result, control, read, R22 aggregate or server log**; no
trading outcome of any system on any bar from 2024-01-01 on for this design. No computation on real prices was made
for this design, except signal-function timing and event counts on one coin's practice-period bars (5m bars cut at
2024-01-01; signals only, seconds and counts printed; no position, no outcome). Lattice counts were computed from code
only, engine timings and the review's simulations on synthetic numbers only (sections 17, 18).

### 0.3 Run regardless of round 1; how this file changes

* **Round 2 runs whatever round 1 shows** (WIDE PASS or not, any pick, any read). Nothing in round 1's results starts,
  stops, shrinks or widens round 2.
* **No open question remains.** Every choice, including those the first draft left to the owners or to the code
  review, is closed in this text at the values of section 16.
* After the design hash, every `DEVIATIONS.md` entry is dated and states what of round 1 and of the forward record had
  been seen at that date. **Allowed entries:** (i) code fixes that make the code do what this text says, with the line
  of this file they restore; (ii) feasibility fixes: the smallest change that makes a step run that cannot run as
  written, with the line it changes; (iii) an engine fix inherited under the last bullet. **Not allowed:** any change
  to a selection, hurdle, null, test, tuning-family, lineup or ledger rule, and any choice informed by round-1 results.
  Such a change is **hunt-r2 v2**: a new pre-registration with its own confirm look in the ledger.
* **Owner answers.** An owner answer counts only if it was given before the owners had seen any round-1 output (server
  screen, pushed files, a relayed message). Since this text closes every question, no owner answer changes this
  design. The owners may at any time make the real-money rule of 10.2 stricter, never looser.
* **Blind code.** Round-2 code is written and reviewed by agents given no round-1 output (no select table, picks,
  batches, `test.json`, R4, R22 or O read file). The main session, which relays round 1's results to the owners after
  the hash, makes no round-2 choice (none is left) and passes no round-1 output to round 2's code agents. Round 1's
  private or sealed files (its `private.tgz`, R22's private file) are never opened by anyone working on round 2; code
  reads from them only what section 8 says, and from round 1's public files only what 4.1 and 5 allow after round 2's
  `test.json` is hashed.
* A bug fixed in the shared engine (`research/hunt/hunt.py`) through `research/hunt/DEVIATIONS.md` is inherited, and
  the fixed file's hash replaces that file's line in this study's own pin list (section 11).

### 0.4 Why round 1 had no custom values

* Round 1 used defaults on purpose (W 0.1, W 14): numbers chosen on the same data overfit unless guarded.
* The evidence is the full grid (FG 4-6): 1,015,563 number combinations x 84 exits on the old six coins. Its 379
  rule-bot picks with at least 100 test trades fell from a select-period **per-trade median** of **+2.47%** to
  **-0.25%** on 2024-2026 (`research/fullgrid/ANALYSIS_KO.md` section 4; the round-2 brief wrote this as "per month";
  the source is per trade), with **0 of 711 picks** passing the FDR correction and a select-to-test rank correlation of
  **0.22**. The full grid also chose by a plateau median, over a large grid, and it collapsed.
* So round 2 (i) searches each name's numbers on a coarse ½x / 1x / 2x lattice at one slot; (ii) chooses by a plateau
  median whose neighbourhood has a fixed size, so lattice corners get no free pass (4.2); (iii) keeps a name only when
  it beats, rank by rank with a stop at the first failure, the 95th percentile of the same search replayed 200 times on
  each of two no-skill nulls (4.3); (iv) tests the coarse peak itself, while a finer box only checks it (4.4); and (v)
  tests separately whether the tuned numbers beat the textbook numbers (7.2).
* **Fewer tries help only a little.** The best of round 2's 4,369 selectable systems carries about 3.6 standard
  deviations of pure-noise lift, against about 4.6 for the best of one full-grid cell (about 270,000 pairs) and about
  2.5 for the best of one name's 88 (expected maximum of independent normals; correlated systems give less). Winner's
  curse grows like the square root of 2 ln N, so round 2's top picks carry about 80% of the full grid's per-cell
  inflation in noise units. The hurdle and the test are the guard.

### 0.5 Forward-count date

Forward paper data counts as out of sample for round 2 from the later of: the design-hash date (0.1), and the date of
the last `DEVIATIONS.md` entry of type (ii) of 0.3 (entries of types (i) and (iii) restore this text or inherit an engine
fix and do not move it). The forward record before that date is shown beside the verdict as seen data.

### 0.6 Changes against round 1, argued here (all others: H and W as written)

1. Numbers are searched (sections 3-4); W 5's one-system-per-name walk becomes the staged selection of section 4.
2. F2_DEMARK and F6_VWAP_CROSS (no numbers) and F4 (the watch picks) are out (3.1).
3. No "no pick, fail" system: if selection takes nothing, nothing runs on test (4.3; differs from H 11.2 / W 5).
4. P2's month-block bootstrap uses **100,000** resamples instead of 10,000, and each control's p is the larger of the
   bootstrap p and the one-sided t_32 p (7.1).
5. Two clustered controls, (a-c) and (b-c), are added as seed-rank conditions of a PASS (7.1).
6. A second confirmatory family: the tuned pick against its own anchor default (7.2).
7. The program-wide ledger is a pinned module of this study with three dated prints in `test.json` (section 8).

## 1. Question

For each of the 85 round-1 candidate names that have numbers, run on the round-1 trend-hunt machine (H 2-10 with the
W 2 changes) at the timeframe and gate where its default numbers did best on 2021-2023 (its **anchor**):

1. Is there a setting of its numbers, chosen on 2021-2023 only by a plateau rule and kept only when it beats the same
   search replayed on no-skill entries, that grows one wallet after all costs on 2024-01 .. 2026-09 and beats the same
   machine fed with random entry times and with coin-flip sides (also with both clustered across coins), after
   correcting for testing up to ten at a time? (**R2 PASS**)
2. Does that tuned setting beat the same name's textbook (default) numbers at the same anchor on 2024-01 .. 2026-09,
   corrected the same way? (**TUNED BETTER**: the owners' own question.)

The two answers are reported separately. An R2 PASS alone does not show that tuning helped: a pick shares its entry,
timeframe and gate with its anchor default, so an edge of the default passes with it.

## 2. The machine (unchanged) and what is not searched

* **Unchanged, as H and W:** data and data identity (H 2; `research/hunt/data_manifest.json` checked at every select
  and test; the 1 GB disk stop), the 30 coins, old six / new 24 and the large group (H 3), bars and indicators (H 4,
  W 2: 15m, 30m, 1h, 4h UTC bins of the 5m bars), the 장세 label and G1 (H 6) and NONE (W 2), the event edge rule taken
  before the gate (W 3.2) and the 300-bar warm-up for F2-F3 events (W 3.1), entry fill, first stop D0 = 2 x ATR14 on
  15m/30m/1h and 1.5 x ATR14 on 4h (H 7.2, W 2), leverage and isolated margin (H 7.3), pyramiding with 3 adds (H 7.4),
  the chandelier at 3 x ATR14 of the system's timeframe (H 7.5, W 2), the order inside a 5m bar (H 7.6), the portfolio
  (H 8), costs and cost x2 (H 9), accounts ($5,000, compounding), monthly multiple, bust and metrics (H 10), r = 0.5%
  for selection and test (W 2), the periods (H 11).
* **Engine identity:** `research/hunt/hunt.py` and `research/hunt/entries_wide.py` are imported read-only. This
  study's own pin (section 11) lists **each file it depends on, with the sha256 round 1 pinned for it**, and the select
  and test steps check each one: hunt.py, entries_wide.py, `research/hunt/universe30.json`,
  `research/hunt/exchange30.json`, `research/hunt/data_manifest.json`, `paperbot/dash/tools/regime5y.py`,
  `research/fullgrid/memo.py`, `research/deepseek200/lib_c.py`, every file `hunt.signal_path_files("wide")` returns,
  and the pin files `research/fullgrid/PREREG.sha256` (run.py, grid.py, ds_defs.py), `research/entry_study/
  DEFS_BC.sha256` and `third_party/sweep/PREREG.sha256`. It **never hashes `research/hunt/PREREG_HUNT_WIDE.sha256`
  itself** (round 1 appends lines to it) and **never requires a file under `research/hunt/out/`**. An engine fix
  inherited under 0.3 replaces one line of this list.
* **Not searched:** exits, D0, adds, r, the 장세 label's numbers (ADX, EMA slope, ATR percentile), the gate rule,
  weekend and other noise filters (the loss autopsy's filters stay a separate later round; O1, O1b and O4 are reads
  here, sections 6 and 9), coins, timeframes or gates beyond the anchor (4.1), per-coin numbers, combining entries.

## 3. Search space: names, numbers, lattices

### 3.1 Names (85)

| family | names | numbers |
|---|---|---|
| **F1** | E1, E2, E3 (H 5) | new declarations (3.2); the default combo reproduces `entries_wide.hunt_raw` bit for bit |
| **F2** | the rule bot's 36 = `research/fullgrid/run.core_names()` | `run.params_of("core", name)`; defaults = `run.default_combo` |
| **F3** | 42 of the 44 DeepSeek definitions in `ds_defs.DEFS`: all except **F2_DEMARK and F6_VWAP_CROSS**, which have no numbers. The five ET-session names (F15_ASIA_BRK, F15_ASIA_SWEEP, F15_LON_BRK, F15_OPEN0930, F15_OPEN0000) run on 15m, 30m, 1h only (W 4) | `ds_defs.DEFS[name]` |
| **F5** | TURTLE20, TURTLE55, TSMOM7, TSMOM28 (W 3.3, `entries_wide.famous_raw`) | lengths in days (entry_days, exit_days; lookback_days), x bars per day of the timeframe as W 3.3 |

* **F4 (the 38 watch picks) stays out**: their numbers were kept after 2024-2026 was seen (W 3).
* Signal arrays for F2 and F3 come from the same functions W 3.1 calls, with the combo passed as keyword numbers,
  through round 2's own adapter (`grid_raw` clears the memo on every call, `entries_wide.py` line 400); F5 from
  `famous_raw(name, bars, combo)`; F1 from the new function of 3.2. Event rule W 3.2 for all. **Round 2 never passes a
  round-2 spec dict to round 1's spec-based signal path** (section 11).
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
defaults (and v1's neighbours, H 11.1, at their values), and an integration test checks that non-default combos reach
the engine intact (section 11).

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
* **One-step positions** of a coarse point x of a name with k numbers: for each number, the value one step down and the
  value one step up in that number's deduplicated coarse value list, the other numbers kept: **2k positions**. A
  position **exists** when that value exists, the combo passes `valid_r2` and it was not removed under 3.7. The
  existing positions are x's **coarse neighbours**.

### 3.5 Fine box (local, 9-step; a check, never the source of a tested number)

* For each number, the 9-step block of `grid.MULTS` (or `grid.NEUTRAL_F`) that holds the coarse peak's factor:
  lengths and multipliers {⅓, ½, ⅔} around ½x, {0.8, 1, 1.25} around 1x, {1.5, 2, 3} around 2x; threshold_neutral
  f in {0.25, 0.5, 0.75}, {0.9, 1, 1.1} or {1.25, 1.5, 2}. Values through `grid.values` as in 3.4; the box is the
  product, minus `valid_r2` failures and combos removed under 3.7.
* A value reached from more than one coarse factor (after rounding, e.g. orb_bars 2 at ½x and 1x) takes the factor
  nearest 1x in log distance.
* The box has at most 81 points (the centre is the coarse peak), so at most 80 new; over the 85 names the largest
  possible boxes total 4,032 points. **The box only checks the coarse peak (4.4); its points are never picks.**
* **One-step positions in the box:** as 3.4, one step down and up inside the number's 3-value block.

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
* **Tries.** Per name, **at most 88 systems can become its pick**: the 8 default systems (4 timeframes x 2 gates; 6 for
  the session names) + at most 80 new coarse points. Over the 85 names that is **4,369 selectable systems** (670 + 3,699).
  The box adds at most 80 check runs per taken name that can only remove it; with every box, the selection runs at most
  8,316 systems. The full grid tried 1,015,563 combos x 84 exits. Section 0.4 says why the count is not the guard.

### 3.7 Combos whose signal code raises

A combo whose signal function raises on any coin of a timeframe is removed from that (name, timeframe) before any
engine run, listed with the exception text in `picks.json`'s counts section, and treated as a position that does not
exist (3.4, 3.5) for neighbours, medians and boxes. The removal depends on signals only, never on an outcome, and the
nulls see the same removals. A default that raises stops the select step (a bug: round 1 ran every default).

## 4. Selection (2021-01-01 .. 2024-01-01 only)

The select step reads no 5m bar that opens at or after 2024-01-01 00:00 UTC: each coin's npz columns are decompressed
whole for the content check (H 2) and cut at 2024-01-01 before anything else uses them; of the manifest only what lies
before that date is carried (H 11, W 5). Positions open at the end are marked at the last 5m close (H 10).

### 4.0 Definitions

* **S** = mean monthly ln M over the 36 select months at base cost, r = 0.5%, one $5,000 account (W 5's score).
  **S2** = the same at cost x2 (H 9). **n** = positions opened. Bust as H 10.
* **W5-ok** = n >= 72, S > 0, S2 > 0 and no bust (W 5's eligibility).
* **Value of a one-step position** (3.4, 3.5): its S if it exists with n >= 72 (a busted neighbour keeps its own S);
  **min(S, 0)** if it exists with n < 72; **0** if it does not exist. The S2 value the same way with S2.
* **Lattice order** (for ties): the product order of the numbers in their declared order, each number's values
  ascending (as `grid.grid`); the box in the same order over its block values.

### 4.1 Stage 0: anchors (defaults only)

* Each name's default systems are recomputed by round-2 code: 8 per name (6 for the session names), **670 systems**
  (round 1's 686 candidates minus the 16 systems of F2_DEMARK and F6_VWAP_CROSS).
* **Anchor** of a name = its default system (timeframe, gate) with the highest S among those with n >= 72 and no bust;
  if none qualifies, the highest S overall. Ties as W 5 (higher median monthly multiple; then timeframe 15m < 30m < 1h <
  4h; then G1 before NONE).
* **Only the anchor slot is searched.** Numbers are searched at 1 of a name's 8 (timeframe, gate) slots; a setting
  that works only at another slot is not found (14). Searching all 8 would multiply the selectable systems by 8 (more
  than 700 per name) and the winner's curse with them; that is a separate later round if wanted.
* Round 2 never reads round 1's output to do this. An optional automated check may compare the Stage 0 rows with round
  1's `select.json` after round 2's `test.json` is hashed and print only "equal" or "not equal" per row; no person
  reads round 1's file for it.

### 4.2 Stage A: coarse plateau on the anchor

All coarse points of the name run on the anchor's timeframe and gate, base cost and cost x2.

* **P_c(x)** = the median of S(x) and the values of x's **2k one-step positions** (4.0): always 2k + 1 values, so the
  neighbourhood has a fixed size and a position outside the lattice counts as 0. **P_c2** = the same with S2. A point
  with e missing positions has P_c > 0 only if at most k - e of its 2k + 1 - e real values are <= 0: an all-edge
  corner needs itself and every existing neighbour positive.
* **Coarse-eligible x:** W5-ok, P_c(x) > 0, P_c2(x) > 0, at least half of x's existing coarse neighbours have n >= 72
  and no bust, and, for a name with **one or two numbers**, every existing coarse neighbour has S > 0 and S2 > 0.
* **Peak** = the coarse-eligible point with the highest P_c. Ties: higher P_c2, then higher S, then lattice order.
* A name is a **candidate** only if it has a peak, the peak is not the default (nor a default in effect), and
  P_c(peak) > P_c(default point) (computed the same way, whether or not the default is eligible).
* Candidates are ranked by P_c(peak), highest first. Ties: higher P_c2, then W 5's family order (F1 < F2 < F3 < F5),
  then name (ASCII).
* Model note (section 18): on pure noise the draft's median over existing neighbours picked all-edge corners at about
  twice their share; this rule picks them below their share (it leans toward settings near the textbook numbers). The
  nulls replay the same rule, so the hurdle stays fair either way.

### 4.3 The null hurdle (the main guard against the full grid's failure)

The full grid failed because the best of many tries on 2021-2023 is lucky. The hurdle measures that luck for **this
search**: the whole of Stage 0 and Stage A is replayed on entries that have no skill but keep the correlations across
systems and coins, and names go forward only while they beat both nulls rank by rank. Select period only, base cost
only (dropping the cost x2 conditions in the null lets more null points qualify, so the hurdle errs strict).

* **(b′) Shared coin flip**, **200 replicates**, i = 1..200. In replicate i, **one fair coin per signal-bar close time
  (ms), shared by every coin and every system** that has an event at that close (all names, timeframes, gates and
  combos): heads (the first byte of sha256("hunt-r2-null|b|<i>|<close_ms>") even) keeps the side, tails reverses it.
  The machine then takes or drops each event as H 8 says.
* **(a′) Common circular time shift**, **200 replicates**, i = 1..200. One shift in **whole weeks** per replicate:
  Δ_i = 7 x (9 + (the first 8 bytes of sha256("hunt-r2-null|a|<i>|<j>"), little-endian, mod 140)) days, j = 0 at
  first, so uniform over whole weeks in 63 .. 1,036 days (weekday and time of day kept). The same Δ_i applies to all
  coins and systems; each coin's gated events move **circularly inside that coin's own valid span** on the system's
  timeframe: s_c = its first and e_c its last signal-bar close in [2021-01-01, 2024-01-01) with a 장세 label,
  ATR14 > 0 and a fill bar (after the warm-up of W 3.1); L_c = e_c - s_c floored to whole weeks; an event at t moves to
  s_c + ((t - s_c + Δ_i) mod L_c). Side kept, **not re-gated**. Events landing on a bar without a 장세 label, without
  ATR14 > 0 or without a fill bar are dropped and counted. If more than 10% of the replicate's events (all systems and
  coins) are dropped, Δ_i is redrawn with j = 1, 2, ...; redraws are printed. Coins whose effective shift (Δ_i mod L_c)
  lies within 8 weeks of 0 or of L_c are listed per replicate.
* **Each replicate replays Stage 0 and Stage A with the same rules** (its own anchors, peaks, candidate test and
  ranking, the fixed-size P_c, the one-or-two-number rule, the default-in-effect rule and the removals of 3.7). A
  shortcut of Stage 0 (for example, reusing the real anchors) makes the hurdle lenient and is not allowed.
* **Rank-r null score** = the r-th highest candidate P_c in a replicate; 0 when the replicate has fewer than r
  candidates.
* **Step-down rule.** Walk the real candidates from rank 1. The candidate at rank r is **taken** only if every
  candidate at ranks 1 .. r - 1 was taken **and** its P_c(peak) is greater than the **95th percentile** (numpy linear)
  of the rank-r null scores in **both** nulls (200 each). **The walk stops at the first failure**; every lower-ranked
  candidate is labelled "not taken (below a failed rank)".
* **If no candidate is taken, round 2 fails at selection.** Nothing runs on the test period and no ledger hypothesis is
  added. This differs on purpose from H 11.2 / W 5's "no pick, fail" system: such a system can never pass or join the
  lineup, and running it would spend a look at 2024-2026 for nothing. The select-only reads of section 6 still run.
* **What the hurdle does (a model figure, not a property of the real data).** In the review's toy model (section 18;
  synthetic numbers, the real search exchangeable with the nulls, appendix A's numbers per name), a search with no skill
  anywhere takes at least one name in about **4-5% of runs** under this rule (about 10% at the 90th percentile), and
  three or more in 1-2%. The draft's rule (each rank on its own at the 75th percentile, no stop) took at least one name
  in 39-78% of such runs and 13-18 names on average. The hurdle removes most luck, not all; the test's controls and BH
  remove the rest.

### 4.4 Stage B: the box check (no refinement)

Taken names are checked in their order until **30 picks** exist or the list ends.

* The fine box (3.5) around the coarse peak runs on the anchor's timeframe and gate, base cost and cost x2.
* **The box must be a plateau:** the median S over all box points > 0, the median S2 > 0, and at least ⅔ of the box
  points have n >= 72 and no bust. A box that fails drops the name, labelled "spike between coarse points", and the
  next taken name moves up.
* **Pick = the coarse peak (the box centre).** The box never changes the tested numbers: picking the best box point
  would be the full grid's own rule (FG 6.1), unguarded by the hurdle.
* **Box best (a read, never tested):** P_f(y) = the median of S(y) and its 2k one-step box positions (4.0 values;
  outside the box counts 0). The box point with the highest P_f is printed in `picks.json`, labelled "box best, never
  tested, inflated by the within-box choice" (DeepSeek: numbers and labels only).
* Rank, batch and hurdle use the coarse peak's P_c only.

### 4.5 No internal walk-forward gate and no futility stop

The 2021-2023 period is not split into a choose part and a hold part for the decision: a 12-month hold with its own
gates costs more power than it saves (a "beats the default on 2023" gate is close to a coin flip when tuning is
neutral), and the null hurdle measures the luck of choosing directly. The walk-forward is a **read** (section 6:
selection lift on 2023, leave-one-year-out stability), printed before the test and choosing nothing. A futility stop
on the 2023 lift (no test when the median lift among taken names is <= 0) was considered and not adopted: when tuning
is neutral it would stop about half of all runs, including runs whose picks carry a real entry edge that R2 PASS
asks about, and the tuning family (7.2) answers the tuning question directly on the test period.

## 5. Picks, batches and the hash before any test bar

* **Batches:** picks 1-10 = **batch 1 (1군)**, 11-20 = **batch 2 (2군)**, 21-30 = **batch 3 (3군)**, in the order of
  4.3-4.4. K = the batch size, which may be under 10. Membership is fixed here and never re-ordered after a test result.
* `research/hunt_r2/out/picks.json` holds:
  - **every name** (the owners' "기본값 → 찾은 값" table, also when nothing is taken): family, name, anchor (timeframe,
    gate), the default numbers, the coarse-peak numbers (or "no peak"), P_c(peak) beside P_c(default), candidate yes /
    no, rank, the hurdle result (taken; failed (a′), (b′) or both; not taken below a failed rank), for taken
    names the box result and the box best (4.4), and labels;
  - each pick's system id, timeframe, gate, numbers, P_c, P_c2, rank, batch and labels;
  - the Stage 0 anchors; the counts per stage, the removals of 3.7 and the (a′) drop counts and redraws;
  - the rank-r null percentiles (q50, q75, q90, q95, both nulls) **only at ranks held by F1, F2 or F5 candidates or
    by no real candidate**; DeepSeek ranks' thresholds go to the private file (10.4).
  DeepSeek rows: numbers, ranks and labels only (10.4).
* **Its sha256 is appended to `PREREG_HUNT_R2.sha256` before any bar from 2024-01-01 on is read.** The test step
  refuses without that line, and nothing in `picks.json` changes after it.
* **Labels, never conditions:** "edge of the coarse lattice" (a number at the first or last value of its coarse list);
  "same numbers as an F4 watch pick"; "same numbers as a full-grid select pick" (those were seen on 2024-2026 under
  house exits); "old six not blind" (H 13 / W 13); "every coarse neighbour positive" (yes / no). Two labels that need
  round 1's output are added only on the results page after round 2's `test.json` is hashed, never in `picks.json`:
  "anchor default = round-1 system <id>" with that system's round-1 status, and "numbers also run on test in round 1's
  R22 (2)".

## 6. Select-only reads (between `picks.json` and `test.json`)

Written by their own pinned module after `picks.json` is hashed and **before `test.json` exists**, to
`research/hunt_r2/out/pretest_reads.json`, whose sha256 is appended to the pin before the test starts (W 7.3a's rule;
if the module is not ready, these items are computed after the verdict, labelled post hoc). They read select bars only
and choose nothing. **They run whether or not any name is taken.** DeepSeek rows: labels and ranks in public, every
money figure in the private file (10.4).

* **CSCV / PBO** over the **real Stage 0 and Stage A runs only** (the 4,369 selectable systems, base cost; no null run):
  12 blocks of 3 consecutive months, all 924 half / half splits; in each split **Stage 0 and Stage A are replayed on the
  in-sample half** with the same rules (position minimum 36 instead of 72); the replay's rank-1 candidate peak and its
  top-10 candidate peaks; their out-of-sample percentile among the 4,369 systems; PBO; the slope of out-of-sample on
  in-sample, as W R4 (2). The hurdle is not replayed (it would need the nulls per split).
* **Null summary:** per rank, the q50, q75, q90 and q95 of the rank-r null score in each null (public at the ranks of
  section 5 only); the count of null candidates per replicate; the (a′) drop shares, redraws and near-zero shifts;
  N_eff = the number n of independent draws from the null's pooled per-point P_c distribution whose expected maximum
  equals the null's mean rank-1 score.
* **Momentum comparison (c′):** one deterministic replay of Stage 0 and Stage A with every event's side set to the sign
  of its coin's 20-bar close-to-close return on the system's timeframe at the signal bar (a zero return drops the
  event), base cost. Per real candidate: the (c′) P_c of the same point at the same anchor, and the rank-r score of the
  (c′) search; labelled "no better than plain momentum at the same times" when the real P_c is not above the (c′)
  P_c of the same point. A read; it removes nothing (14).
* **Selection lift on 2023 (walk-forward read):** Stage 0 + A chosen on the 24 months of 2021-2022 (from the same runs'
  monthly ln M), measured on the 12 months of 2023: per name, H(peak) minus the median H over the name's coarse
  lattice, H = mean monthly ln M on 2023; the median over names and the share above 0.
* **Leave-one-year-out stability:** Stage 0 + A chosen on each pair of years; per name, how often the same peak or one
  of its coarse neighbours returns. In both 24-month reads the position minimum is 48 (2 a month) instead of 72.
* **Near-miss table:** names that failed exactly one condition (candidate rule, one null only, box plateau).
* **Spike ratio** S / P_c and S by year (2021, 2022, 2023) for each pick and each candidate.
* **Weekend map:** Stage A rerun on the real anchors under the O1 weekend-skip machine (W 7.4a); what it would have
  picked. Those systems are never tested here.
* **Four-timeframe weekend table (owners' decision (j)):** for every name, at its anchor gate, on each of its
  timeframes (4; 3 for the session names), its default numbers and its coarse-peak numbers (when it has a peak):
  "주말 포함" beside "주말 제외" (O1) and O1b (longs only skipped): S, median monthly multiple, positions, max drawdown,
  S2; plus aggregates over F1, F2 and F5 by timeframe. Select period only.
* **Select-only owner board:** for the **10 highest-ranked candidates (taken or not)**, their coarse peak beside their
  anchor default, on 2021-2023 only: the R1 goal board (W 7.3; headline cell, the size fixed on select, controls (a)
  and (b) seeds 1-100 at the headline cell), R24 at 20 / 30 / 40x (W 7.3; controls seeds 1-50), O1 / O1b weekend, and
  custom minus default (monthly d = ln M(peak) - ln M(default), its mean and a month-block 90% CI). Labelled
  **"고르는 기간 성적, 골라서 부풀려진 값, 시험 아님"**. Multiples only (owners (e)).

## 7. Test (one confirm look: hunt-r2 v1)

* Period: **2024-01-01 .. 2026-10-01** (33 months), H 11. **Each tested pick runs once** at r = 0.5%, base cost, plus
  its cost x2 run; its anchor default runs once at base cost and cost x2 as the comparator of 7.2. Nothing else of
  round 2 runs on test except the reads of section 9 after the verdict.

### 7.1 R2 PASS

* **Controls of W 6 / H 12:** (a) random times and (b) coin-flip sides, **1,000 seeds each**; seed = sha256 of
  ("hunt-r2", system id, control, period, r, seed number), parts joined as the hunt code joins them. d_m as H 12.
* **Clustered controls (new):** **(b-c)** one fair coin per signal-bar close of the pick, shared by all coins: heads
  keeps the side, tails reverses it for every event at that close (seed parts with control "bc", seeds 1-1,000);
  **(a-c)** the common circular shift of 4.3 (a′) over the test period: every whole-week shift from 4 weeks to
  ⌊(L - 28) / 7⌋ weeks (L = 1,004 days; 136 shifts), each once, all coins shifted by the same Δ inside each coin's own
  valid test span, time of day and side kept, not re-gated, drops counted.
* **Per pick:** **P0** at least 66 positions, a position open in at least 80% of test months, no bust; **P1** median
  monthly multiple >= 1.0 and mean monthly ln M > 0; **P3** the same two at cost x2; **P4** max drawdown < 50%;
  **seed-rank parts** for (a), (b) and (b-c): (1 + seeds with mean ln M >= the pick's) / 1,001 < 0.05; for (a-c):
  (1 + shifts with mean ln M >= the pick's) / 137 < 0.05.
* **p:** for x = a and b, p_x = the larger of (i) the one-sided month-block bootstrap p of mean d_m (resample the 33
  months with replacement **100,000 times**; p = (1 + resamples with mean d <= 0) / 100,001; seed parts as above with
  "boot") and (ii) the one-sided t_32 p of mean d_m (mean over its standard error, ddof 1). **p = max(p_a, p_b).**
  Argued change: the bootstrap floor falls from about 1e-4 to about 1e-5, as track 2 (T2 11), but a 33-month
  percentile bootstrap understates small p for near-normal months by 3-10x (section 18), so the t_32 p guards the tail
  the ledger needs. Round 1's rows keep their own p; the ledger print notes it.
* **BH per batch:** Benjamini-Hochberg at q = 0.10 over the K values of p of the batch (W 6). A pick without a defined p
  enters with p = 1.
* **A pick PASSES** = P0, P1, P3, P4, all four seed-rank parts, and a BH-significant p within its batch.
* **Batches:** batch 1 is tested; batch n + 1 only when **at least 5** picks of batch n PASS; untested members are
  listed as "untested" and never run on test.
* **R2 PASS** = at least one PASS. Reported beside v1 PASS, WIDE PASS and track 2, never merged with them.

### 7.2 Tuned against textbook numbers (second confirmatory family)

* For **every tested pick** (pass or fail): d_tune,m = ln M_m(pick) - ln M_m(its anchor default) per test month, both
  at r = 0.5%, base cost, one $5,000 account each. The anchor default is the same system round 1 ran (as a candidate,
  a pick or in R22 (1)), recomputed by round-2 code; its run is a comparator and is never a pass of anything.
* **p_tune** = the larger of the one-sided month-block bootstrap p of mean d_tune (100,000 resamples; seed parts with
  "tune") and the one-sided t_32 p. H0: mean d_tune <= 0.
* **BH per batch** at q = 0.10 over the tested picks' p_tune values (the same batches as 7.1).
* **TUNED BETTER** for a pick = BH-significant p_tune within its batch **and** mean d_tune at cost x2 > 0.
  **"Tuning beat the textbook numbers"** = at least one TUNED BETTER. Reported as its own verdict beside R2 PASS.
* **Label on every tested pick**, with the mean d_tune and its month-block 90% CI: **"tuning beat the textbook numbers"
  / "커스텀이 기본값을 이김"** (TUNED BETTER); **"worse than the textbook numbers" / "기본값보다 나쁨"** (the 90% CI lies
  below 0); otherwise **"not shown to beat the textbook numbers" / "기본값보다 낫다고 말할 만큼은 아님"**.
* Every p_tune enters the ledger (section 8).
* Long steps resume under the pin's hash (W 6, W 10).

## 8. Program-wide ledger

* The test step writes a **dated ledger snapshot** into `test.json` with **three prints**, each with a global BH at
  q = 0.10, Holm at 0.05 and its m:
  - **(A) tested:** every test-period hypothesis of the hunt program that has a p on the snapshot date: the v1 pick;
    every tested wide batch; every round-1 read that prints a p; track 2's tested picks; round 2's p and p_tune.
    Pre-registered picks that are hashed but not yet tested are **listed separately and not counted in m**.
  - **(A+) tested + full grid:** (A) plus the full grid's 711 test-period hypotheses (a custom-value search on these
    same entries over the same 33 months; p from its published results files where readable, else 1) and the 38 F4
    watch picks at p = 1.
  - **(L) live gate:** (A+) plus every confirm look whose pre-registration is hashed but not yet run, counted at its
    **maximum** number of hypotheses with p = 1 (so deciding early buys nothing).
  The line **"four studies share one 33-month period"** is printed with them.
* **p entered:** round-2 rows enter the p of 7.1 and the p_tune of 7.2 (each already the larger of bootstrap and
  t_32); other studies' rows enter their published p, with a note where the floor is 1e-4.
* **Inputs:** each study's public `test.json` and reads files, and the private DeepSeek p-values from round 1's
  `private.tgz` and track 2's private file (T2 13; W 11). The owners copy those private files to the round-2 server
  with one line given in the server guide before the test step; the code checks each file's sha256 against the hash
  printed in that study's public output and reads **only the p-value fields of its confirm rows** (never a read's or
  R22's per-system numbers). A missing or mismatched file gives p = 1 for its rows, listed "p not available". Nobody
  opens these files. DeepSeek rows show labels only in public.
* **Looks:** round 2's confirm look (its picks and their anchor-default comparators), and O1, O1b and O4 on round-2
  rows, each count as one look at the test period; they are printed beside m. R2-22 does not exist (9.6).
* The ledger changes no verdict of any study. It is built by this study's own pinned module (`ledger.py`) following
  T2 13's rule; when track 2's ledger code is pinned by then, a parity test against it on synthetic inputs is required.
* The same module recomputes the three prints on any later decision date; the live gate (10.2) uses print (L).

## 9. Reads after the verdict (never a pass)

### 9.1 Read guard

H 14 and W 7.1 apply as written: reads run only on ROWS, after `picks.json` is hashed; read code is listed in the pin
before `test.json` exists; outputs go to their own files (`research/hunt_r2/out/reads_*.json`); a read never changes
the picks, batches, P0-P4, p, p_tune, BH, PASS, TUNED BETTER, R2 PASS or the lineup; the code refuses to write
(ReadGuardError) when any file of the output folder or `picks.json` changed while a read ran; a read added after the
test is seen is post hoc, in `DEVIATIONS.md`. **The reads stop at 12 hours wall** (as track 2); what is unfinished is
listed and the rest is bundled as is.

**ROWS:** every tested pick (pass or fail); the batch-1 all-K basket (one wallet, H 8 caps shared, same-close order by
30-day quote volume then pick number, labelled "not a candidate"); the passing basket when at least two pass.

**Any rule or design choice taken from a test-period read** (weekend, timeframe, size, momentum, or any other) is
confirmed only on forward data after its fixing date (W 12), never on 2024-2026. Every later round's pre-registration
lists which of round 1's R22, the O reads and round 2's test-period reads its designers had seen.

### 9.2 Reads on ROWS

* **New 24 only** (W 7.0): a passing pick with new-24 test mean ln M <= 0 is labelled "carried by the old six".
* **Extra 2020** at r = 0.5% and 1%; the **r = 1% line** (P0-P4 and the seed-rank parts, controls rerun at 1%) and the
  **cost x2 line at 1%**.
* **Select-period controls**, seeds 1-200.
* **R1 goal board** (W 7.3) with the headline cell and the size fixed on select (W 7.1), multiples only.
* **R12 / R13 basics** (W 7.3), plus the correlation of monthly ln M with the anchor default's.
* **R14 forward band** and **R19 1m + mark fidelity** for passing picks only (W 7.3, 7.4); R14's output hashed before
  the paper bot uses it.
* **O4 momentum label** (W 7.4a): "momentum only" when a plain momentum entry at the pick's times did as well.

### 9.3 Weekend (owners' decision (j), W 0.1)

For every row, on that row's own timeframe: **"주말 포함 (시험한 기계, 판정 기준)"** beside **"주말 제외 (읽기)"** (O1:
first-unit entries whose signal bar closes from Saturday 00:00 to Monday 00:00 UTC skipped), plus **O1b** (longs only
skipped); select and test side by side: mean and median monthly ln M, win share, positions, max drawdown, cost x2 mean
ln M; controls (a) and (b), seeds 1-200, through the same weekend-skip machine; pick-minus-control d_m with a 90% CI;
the R1 headline shares (end and touch x2 and x5) at the size fixed on select. **This test-period read covers only the
timeframes of the tested picks** (one timeframe if every pick is 4h; none if selection stops); the four-timeframe table
is select-only (section 6). A weekend rule becomes a rule only through a later round, judged only on data after its
fixing date (W 12).

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

### 9.6 No sealed calibration read (R2-22 is not run)

The draft's R2-22 would have run every candidate's would-be pick on the test period to calibrate the selection method
on 2024-2026. Its only use would be to design later rounds, which W 14 forbids ("no bar from 2024-01-01 on enters its
design"). It is not run, and no system of round 2 other than the tested picks and their anchor defaults ever runs on
the test period.

## 10. Lineup, what a result means, D11

### 10.1 Lineup (W 12, unchanged)

**정식** = PASS. **참고** = round 1's rule (g): a tested pick with test mean monthly ln M > 0, median monthly multiple
>= 1, mean ln M above both controls' seed means, cost x2 mean ln M > 0, max drawdown < 50%, no bust, best month < 50% of
the total log gain. Everything else is excluded. Written to `test.json` as `lineup`. TUNED BETTER does not change the
lineup.

### 10.2 What a result means

| result | then |
|---|---|
| R2 PASS | each passing pick (정식) joins the forward paper bot beside round 1's lineup, r = 0.5% and 1%, $5,000 each; real money only after W 12's forward criteria and live-readiness gate, never before the mid-November 2026 review, and only if it also passes the **ledger's print (L)** (global BH at q = 0.10) on the decision date **and at every later recomputation while the live account runs**; otherwise it is labelled **"정식 (장부 미통과)"** and stays paper only. Round 1 and track 2 have no such condition; the owners may add it to them (a stricter money rule) |
| TUNED BETTER | recorded: on the test period, that pick's tuned numbers beat its textbook numbers after the batch correction. By itself it changes no lineup and no money rule |
| a pick fails | recorded with its numbers (DeepSeek: labels); 참고 or excluded by 10.1; never real money |
| no candidate taken, or every box fails | round 2 fails at selection; recorded with every select-period count and the select-only reads of section 6; nothing runs on test; no ledger hypothesis |
| R2 fail after the test | recorded; **no tuning on the test period**; a later version is a new pre-registration with one new look |

* The paper bot records round-2 picks (tested, any verdict) like every hunt system, recomputed from 2026-10-01; forward
  data counts only from the date of 0.5. It must load at least the longest lookback of the picked numbers plus 300 bars
  of each timeframe (picks use up to 2x the default; for example TURTLE55's entry channel at 2x on 15m is 110 days =
  10,560 bars). This is a huntbot change, made after the verdict and only for tested picks (section 12).
* Two to four studies share the test period; the report says so beside every verdict and never merges them.

### 10.3 A bug after the test

As H 15: fixed in `DEVIATIONS.md` with the line it breaks, the test rerun once, both results shown; the rerun's verdict
is the verdict.

### 10.4 DeepSeek money (D11)

As W 11: DeepSeek rows in repository files show counts, win shares, ranks, numbers (combos) and labels only. Their S,
S2, P_c, P_c2, P_f, the null thresholds at their ranks, ln M, multiples, drawdowns, p, p_tune, d_m, d_tune and every
money figure of the section 6 tables go only to a private file outside the repository whose sha256 is in the public
output. The writer refuses a float under a DeepSeek row.

## 11. Code, tests and pin (`research/hunt_r2/`)

* **Files** (names indicative; the pin lists what exists): `lattice.py` (F1 and F5 declarations, the order table,
  coarse and box builders, `counts.json`), `entries_r2.py` (the combo-taking F1 function; adapters to the full grid's
  signal functions and `famous_raw`), `store_r2.py` (the event store), `select_r2.py` (Stage 0, A, nulls, hurdle, box
  check, `picks.json`), `pretest_r2.py` (section 6), `confirm_r2.py` (section 7), `ledger.py` (section 8),
  `reads_r2.py` (section 9), `hunt_r2.py` (command line: `counts`, `bench`, `pinlist`, `selfcheck`, `select`,
  `pretest`, `test`, `reads`), tests under `tests/test_hunt_r2*.py`; the server kit `bootstrap_r2.sh`, `wait_go_r2.sh`
  and the owners' guide `SERVER_R2_KO.md`.
* **Written blind:** the code and its review are done by agents given no round-1 output (0.3).
* **Signal path (no spec dicts into round 1's path).** Round 2 never passes a round-2 spec dict to `hunt.entry_events`,
  `cached_events`, `system_signals`, `run_system`, `run_engine(spec)` or the reads' `signals()` / `control_signals()`:
  for kind "hunt" `entries_wide.events_on` uses only the first number of the combo (`entries_wide.py` line 429) and
  `hunt.cell_key` would cache the wrong events under the full combo. Round 2 builds its own signal dicts {tf, k, j,
  side} from its own events and calls `run_signals`, `run_engine([(sig, src)])`, `control_a`, `control_b`, `boot_p` and
  `rng_of` on them. **Integration test:** an E1 combo with vol_len = 40 and vol_mult = 2.5, and an E3 combo with
  slow = 200, give round 2's events (not `hunt_raw(channel)`'s) through every engine entry point round 2 uses.
* **Imports read-only** with the file-by-file pin of section 2; the select and test steps refuse on any mismatch.
* **Memo and caches:** the full grid's indicator memo (`memo.py`) and the DeepSeek `cache` are cleared once per coin x
  timeframe series, not per combo, through round 2's adapter. A test checks, on synthetic bars, that every name over a
  lattice sample gives identical events with the memo and cache kept across combos and with a fresh one per combo; a
  name that fails uses a fresh cache per combo.
* **Event store:** per (name, timeframe, combo) cell and coin, the **select-period** events before the gate as int32
  bar index, int8 side and an int8 G1 flag, in the private run folder (about 7-12 GB for the 15,121 coarse cells at the
  measured densities). Every null replicate reads it; signals are never recomputed per replicate. Box cells are added
  for taken names only. Test-period events are computed only for tested picks and their anchor defaults.
* **Synthetic parity tests** (no real price): the F1 function equals `hunt_raw` at the defaults; default combos of F2,
  F3 and F5 equal `entries_wide` events bit for bit; the round-1 engine digest (W 10) is unchanged; lattice and box
  builders against `grid.values` and `valid_r2`; the fixed-size P_c (outside = 0, n < 72 = min(S, 0)); null transforms
  ((b′) one flip per close shared across coins and systems; (a′) whole weeks, per-coin circular wrap, time of day and
  weekday kept, drop counts and redraws; (b-c), (a-c)); the step-down hurdle, ranking and box check on hand-made score
  tables; the default-in-effect, two-name and raising-combo rules; the t_32 / bootstrap p; the three ledger prints;
  the D11 writer; refusal without the pin, without the picks line, and before `test.json` for reads.
* **Work units** = (name, timeframe, coin) for signals and (replicate, name) for null replays, heaviest first (N05,
  V45, V39 at 15m), with resumable part files under the pin's hash; results do not depend on the worker count. Memory:
  up to about 0.7 GB of memo per worker, so 32 workers fit in 128 GB.
* **Bench:** `hunt_r2 bench` writes `bench_r2.json`: seconds per signal combo for the heaviest names on full-length
  synthetic series, and seconds per engine run on synthetic signals at the real densities (5-15 events per day per coin
  on 15m, scaled by timeframe), listed in the pin. If select extrapolates beyond 15 hours wall at 18 effective cores,
  the owners are told before renting; nothing is cut.
* **Pin:** `research/hunt_r2/PREREG_HUNT_R2.sha256`, first line the design hash (0.1); at the code pin, what
  `hunt_r2 pinlist` prints: this file, the code, tests and server kit, `counts.json`, `bench_r2.json`, and the
  read-only inputs of section 2, each by its own hash. Later lines: `picks.json`, `pretest_reads.json`, the reads
  modules (before `test.json`), `test.json`, R14's output.
* **Nothing runs on real prices on the development machine** (about 1.3 GB free). Select and test run from one fixed
  checkout of the pinned commit (W 15 Q15).

## 12. Compute plan (one Vultr vx1-g-32c-128g, 32 vCPU, about $1.2/h)

Effective cores: 18-27 (27 if the 32 vCPU behave as cores; nearer 18-22 for numba-bound work if they are SMT threads).
Engine runs cost 0.14-0.52 s per 36-month 30-coin run by event density (W 10's bench and the review's synthetic bench;
ungated 15m systems give 5-17 events per day per coin); 0.25-0.45 s is used as the average.

| step | estimate |
|---|---|
| setup, self-check, pin check | about 10-15 min |
| data download and check against `data_manifest.json` (30 coins, 5m, about 0.8 GB) | about 15-20 min |
| coarse signals and the event store, 15,121 cells x 30 coins | 19-34 CPU-h (measured per combo on one coin, scaled; N05_PSAR_POC at 15m about a fifth) |
| real Stage 0 + A (4,369 systems, base and cost x2) | about 8,700 runs, about 1 CPU-h |
| nulls: 400 replicates (200 per null) x about 4,370 runs, base only | about 1.75 million runs, 120-220 CPU-h |
| box checks (taken names; worst case all 85 at 15m) | at most about 14 CPU-h |
| **select in total** | **about 140-270 CPU-h; 5-15 h wall** |
| pretest reads (CSCV, (c′), weekend tables, owner board) | 2-4 CPU-h, under 30 min wall |
| test, batch 1 (10 picks x about 6,500 control runs + 10 anchor defaults) | 4-8 CPU-h, about 15-25 min wall |
| reads (section 9; R19 needs a 1m download of the traded coins) | 6-12 h wall (stops at 12 h) |
| **total on the server** | **about 13-29 h, about $16-35** (the disk about $1-2) |
| verdict (`test.json`) reached after | about 7-17 h; **the server stays until the reads end** |

* **Disk:** at least 50 GB; a 100 GB block-storage disk as track 2 (`hunt-r2-disk`), destroyed with the server.
* **Server kit:** `bootstrap_r2.sh` (install, self-check, pin check, data, select, picks hash, pretest, test, reads,
  bundle) and `wait_go_r2.sh` (waits for the code pin, as round 1's); `SERVER_R2_KO.md` gives the owners one line to
  paste and the line that copies the private files of section 8.

**Order (never two compute servers at once; the Vultr fee limit allows one 32 vCPU server):**

1. Design hash now (0.1).
2. Round 1 ends; its results are pushed; its server and disk are Destroyed.
3. **Track 2's whole run** (select, its test and its reads, one server): about 1-2.5 days, about $25-75
   (`research/hiwr/SERVER_KO.md`); that server is Destroyed. Track 2's code is ready first; round 2's code is written
   meanwhile.
4. Round 2's code is written, reviewed and pinned (about 2026-10-13 .. 10-15).
5. `hunt-r2-compute`: select, the picks hash, pretest reads, test, reads, push, Destroy. Round 2's verdict is expected
   about 2026-10-15 .. 10-17, its reads about a day later.
6. **The hunt paper bot (`hunt-judge`)** recomputes every system from 2026-10-01 whenever it is switched on
   (W 12), so switching it on after both compute servers are gone loses no record. If the owners want it earlier, it
   runs at 4 vCPU (enough in October, `docs/huntbot-ko.md`); a 32 vCPU `hunt-judge` beside a compute server is likely
   refused by the fee limit. Round-2 picks need longer lookbacks there (10.2).

## 13. Power, stated up front

Normal approximation of the month-block test over 33 test months; the chance that a lone true pick reaches the p it
needs: p <= 0.01 for BH in a batch of 10; for the ledger's global BH as a lone discovery, p <= 0.10 / m.

| annual information ratio of the pick against the controls | batch BH (p <= 0.01) | ledger m = 50 (0.002) | ledger m = 350 (2.9e-4) | ledger m = 1,061 (9.4e-5) |
|---|---|---|---|---|
| 0.3 | 3% | 1% | 0.2% | 0.1% |
| 0.5 | 7% | 2% | 0.4% | 0.2% |
| 0.75 | 14% | 5% | 1.4% | 0.6% |
| 1.0 | 25% | 11% | 3.7% | 1.9% |
| 1.5 | 56% | 35% | 17% | 11% |
| 2.0 | 84% | 67% | 45% | 34% |
| 2.5 | 97% | 90% | 76% | 66% |

* m = 350 is about where print (A) stands once track 2's picks are tested; m = 1,061 adds the full grid's 711 (print
  A+). Print (L) can be larger.
* Realistic after-cost trend edges are IR 0.3-1.0. There, a lone true pick passes its batch 3-25% of the time and the
  live-gate ledger almost never. **A pass needs a very strong, steady edge (IR about 2 or more).**
* These chances are upper bounds: they leave out the selection hurdle (a real but modest edge may not clear the 95th
  percentile), the box check, P0-P4, the four seed-rank parts and the t_32 guard, which all lower them.
* A smaller K after the hurdle loosens the batch threshold to 0.10 / K.
* **The most likely result is no pass, often decided at selection.** The autopsy found coin-flip direction at the
  defaults, and the full grid's custom values collapsed. With the step-down hurdle a search without skill reaches the
  test in about 4-5% of runs in the toy model (4.3).

## 14. Known limits and risks

* **Reuse of the test period.** 2024-01 .. 2026-09 has been looked at by the full grid, v1, wide (and its reads), track
  2 and now round 2: at least the fifth family of looks. The ledger prices the looks it knows (print A+ includes the
  full grid); it cannot price what people remember.
* **Close relatives.** Round-2 picks share their anchor's entry, timeframe and gate with a round-1 system; their test
  results are correlated with round 1's. That is why 7.2 tests tuned against textbook numbers directly.
* **Code written after round 1's results exist.** The rules are fixed here first and no question is left open; the
  code is written and reviewed blind (0.3, 11); review checks the code against this text; the forward-count date moves
  with any feasibility change (0.5).
* **Leakage in people's heads:** the full grid's old-six tables on 2024-2026 (labels in 5, "old six not blind").
* **The nulls are approximations.** (b′) keeps times and the clustering across coins but not the side's link to
  momentum; (a′) keeps each list's internal clustering, time of day and weekday but moves market states. Neither is
  exact; requiring both helps. **Momentum:** both nulls remove the link to plain momentum, so a momentum premium in
  2021-2023 lifts real names above both. That is accepted (a trend system may earn the momentum premium); the (c′)
  read prints each candidate against plain momentum before the test (6), and O4 labels it after.
* **The hurdle is a model-calibrated guard** (about 4-5% of pure-noise searches reach the test in the toy model); the
  test carries the rest.
* **Anchor lock-in:** numbers are searched only at the timeframe and gate where the default did best; a setting that
  works only elsewhere is not found (4.1).
* **Coarse steps** (½x, 1x, 2x) can miss a narrow optimum between them; that is intended (a narrow optimum is the kind
  that failed in the full grid). The plateau rule leans toward settings near the textbook numbers (4.2).
* **Lookbacks up to 2x** exceed the live bots' current data windows (10.2).
* **r = 0.5%** is far from the owners' x5-x100 goal; the goal board and R24 are reads, not the tested machine.
* **D11:** DeepSeek results in public files are labels, ranks and numbers only.

## 15. Not in this study

Exits, stop width, adds and r as choices; the 장세 label's numbers and other gates; weekend, FOMC/NFP and same-side
rules (reads only); new-information entries; per-coin numbers; combining entries; F4 numbers; numbers at slots other
than the anchor; coins outside the 30; timeframes other than 15m-4h; the AI judgment layer. Each is its own later round
under W 14.

## 16. Former open questions: all closed in this text

| # | question | closed at |
|---|---|---|
| 1 | Ledger before small live (owners) | yes: a round-2 정식 must also pass print (L) of the ledger on the decision date and at every later recomputation (10.2); the owners may only make this stricter |
| 2 | R2-22 sealed calibration read (owners) | no: not run (9.6) |
| 3 | Track 2 before round 2 (owners) | yes, as already decided (T2 Q15); an operational order that touches no rule (12) |
| 4 | Hurdle percentile (owners) | step-down at the 95th percentile of 200 replicates per null (4.3); the 75th rank-wise rule of the draft let most pure-noise searches through |
| 5 | (a′) shift unit | whole weeks, per-coin circular wrap, redraw above 10% dropped (4.3) |
| 6 | Default-in-effect hash | all 30 coins' gated select events at the anchor timeframe and gate (3.6) |
| 7 | A value reached from two coarse factors | the factor nearest 1x (3.5) |
| 8 | Memo or cache that cannot be shared | a fresh one per combo for that name (11) |
| 9 | A fourth batch | none; at most 30 picks |
| 10 | Select above the bench line | tell the owners, rent anyway, cut nothing; the line is 15 h wall at 18 effective cores (11) |

Owner choices that touch no rule (and so may be made at any time): approving the round-2 server rental (12), when
`hunt-judge` is switched on (12), and whether to add the ledger condition to round 1's and track 2's real money (10.2).

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
* 2026-10-12, about 00:00-00:50 UTC: the review and revision of section 18.
* Nothing of round 1's output was seen (0.2).

## 18. Review log (2026-10-12, before the hash)

Three reviewers (statistics, feasibility, owners) checked the first draft; a skeptic re-checked each finding. All 41
were considered; 39 are adopted in full or in part, 1 needed no change, 1 was a duplicate. Model checks used synthetic
numbers only (scratchpad `r2design/hurdle_sim.py`, `boot_sim.py`, `fix/sim_fix.py`, `fix/edge2.py`, `fix/power.py`):

* Hurdle: with the draft's rank-wise 75th-percentile rule, a no-skill search took at least one name in 39-78% of toy
  runs; with the step-down 95th-percentile rule, 200 replicates per null and the fixed-size P_c, in 4.2-4.5% (four
  parameter sets; 8.9-10% at the 90th).
* Plateau: on iid noise the draft's P_c put the argmax at an all-edge corner 37% of the time for 4 numbers (base 20%),
  63% for 2 (44%) and 83% for 1 (67%); the fixed-size P_c gives 3%, 35% and 67%.
* Bootstrap: for near-normal months a nominal 2.9e-4 / 1e-4 / 1e-5 percentile-bootstrap p is about 9.3e-4 / 4.5e-4 /
  1.0e-4 (`boot_sim.py`), hence the t_32 guard.
* Power and expected maxima: section 13 and 0.4 (`fix/power.py`).

| # | finding (lens) | status | where |
|---|---|---|---|
| 1 | Rank-wise hurdle lets noise through (stats, blocker) | adopted: step-down, 95th percentile, 200 per null; no-skill rate restated as a model figure | 4.3, 13, 14, README |
| 2 | Open questions closed after round 1 (stats, blocker) | adopted: every question closed here; later changes only code/feasibility, else v2; blind code; nobody on round 2 opens round 1's private files | 0.3, 16, 11 |
| 3 | Plateau median favours lattice edges (stats) | adopted: fixed-size neighbourhood (outside = 0) and the all-neighbours-positive rule for 1-2 numbers | 3.4, 4.0, 4.2 |
| 4 | Stage B picks the best of 80 box points unguarded (stats) | adopted: the pick is the coarse peak; the box is a check; box best is an untested read | 4.4, 3.5, 3.6 |
| 5 | Coin flips per coin, too narrow (stats) | adopted: (b′) one flip per close across coins; (b-c) and (a-c) seed ranks are PASS conditions | 4.3, 7.1 |
| 6 | Confirm look does not test tuning (stats) | adopted: second confirmatory family TUNED BETTER with BH and ledger entries | 1, 7.2, 10.2 |
| 7 | Ledger omits the full grid; live gate timing (stats) | adopted: prints A, A+ (711 + 38) and L (hashed-not-run at maximum, p = 1); gate must keep holding | 8, 10.2, 13 |
| 8 | Post-verdict test reads feed later designs (stats, split) | adopted after own check: R2-22 dropped; W 12 rule and the later-prereg disclosure written | 9.1, 9.3, 9.6 |
| 9 | Power and "few tries" overstated (stats) | adopted: m = 350 and 1,061 columns, IR 0.3-1.0 rows, expected-maximum figures | 0.4, 13, README |
| 10 | Bootstrap p not calibrated in the tail (stats) | adopted: p = larger of bootstrap and t_32, also for the ledger | 7.1, 7.2, 8 |
| 11 | n < 72 neighbours count 0 (stats) | adopted: min(S, 0) | 4.0 |
| 12 | (a′) few distinct draws, lenient at coin edges (stats) | adopted: whole weeks, 200 replicates, per-coin circular wrap, redraw above 10% dropped | 4.3 |
| 13 | No momentum benchmark in the hurdle (stats) | adopted in part: (c′) momentum replay printed before the test; not a hurdle condition, since a trend system may earn the momentum premium and the question is the tuned system's edge | 6, 14 |
| 14 | CSCV scope; futility stop (stats) | adopted in part: CSCV over real Stage 0/A with the Stage A rule replayed; futility stop not adopted (stops about half of neutral-tuning runs; 7.2 answers tuning on test) | 6, 4.5 |
| 15 | F1 combos lose numbers in round 1's spec path (feasibility) | adopted: no spec dicts into round 1's path; integration test | 3.1, 11 |
| 16 | Whole-file hash of the wide pin breaks (feasibility) | adopted: file-by-file pin; never the wide pin file, never `out/` | 2, 11 |
| 17 | Q1-Q10 closed after round 1 (feasibility) | adopted (same as 2) | 0.3, 16 |
| 18 | Compute optimistic (feasibility) | adopted and redone with the 400 replicates: select 140-270 CPU-h, 5-15 h; total 13-29 h | 12, README |
| 19 | Event store, disk, server kit missing (feasibility) | adopted | 11, 12 |
| 20 | Ledger inputs unreachable; m counts untested picks (feasibility) | adopted: owners copy the private files, sha256 checked; print A counts tested only, L counts the rest at p = 1 | 8 |
| 21 | Null thresholds at DeepSeek ranks public (feasibility) | adopted | 5, 6, 10.4 |
| 22 | No rule for a combo that raises (feasibility) | adopted | 3.7 |
| 23 | README misdescribes the box and power (feasibility) | adopted (README rewritten) | README |
| 24 | Hash timing rests on a local clock (feasibility) | adopted: push before fetching hunt-results; the remote's time recorded | 0.1 |
| 25 | Checks with no defect (feasibility) | no change; the memo note is written in 3.1 and 11 | - |
| 26 | Owners not covered by the hash rule (owners, blocker) | adopted: owner answers after seeing round 1 change nothing; what they saw is recorded; README asks | 0.1, 0.3, README |
| 27 | Old track 2 time, no result date (owners) | adopted: 1-2.5 days, $25-75; round 2 verdict about 10-15..10-17 | 12, README |
| 28 | `hunt-judge` at 32 vCPU blocks servers (owners) | adopted: switch on after the compute servers, or at 4 vCPU | 12, README |
| 29 | Stop at selection gives no owner reads (owners) | adopted: select-only owner board and four-timeframe weekend table always run | 6, README |
| 30 | Weekend read not on all four timeframes (owners) | adopted: four-timeframe table on 2021-2023; test-period read worded as picks' timeframes only | 6, 9.3, README |
| 31 | README overstates the fine search (owners) | adopted (and the box is now a check only) | README |
| 32 | README hides that 1 of 8 slots is searched (owners) | adopted: stated with its reason; other slots are a later round | 4.1, README |
| 33 | README does not explain track 2's million combos (owners) | adopted | README |
| 34 | Ledger money rule binds only round 2 (owners) | adopted: said plainly; owners may add it to the others | 10.2, README |
| 35 | Server rental not asked; cost row reads as an option (owners) | adopted: decision added; row relabelled; reads cap 12 h | 9.1, 12, README |
| 36 | Luck-filter description errors (owners) | adopted (README rewritten for the new rule) | README |
| 37 | "No better than textbook" label overclaims (owners) | adopted: three labels | 7.2 |
| 38 | R2-22 misdescribed; comparator looks not counted (owners) | adopted: R2-22 dropped; comparators counted as looks | 8, 9.6, README |
| 39 | "2차" and "2번 트랙" confused (owners) | adopted: names defined at the top | header, README |
| 40 | Pass chance "3번 중 2번" undefined (owners) | adopted: replaced by the IR table | 13, README |
| 41 | Deliverable and paper-bot change not stated (owners) | adopted: every name's default → peak table in `picks.json`; huntbot lookback change scheduled | 5, 10.2, README |

Rejected: none. Finding 17 duplicates 2; finding 25 reported no defect.

## Appendix A. The 85 names: numbers, kinds, defaults and coarse values

Kinds: len = length (bars; F5: days), mult = multiplier, abs = absolute threshold, neu = threshold with a neutral point.
Coarse values are listed in factor order ½x / 1x / 2x (f = 0.5 / 1 / 1.5 for neu); a missing value was dropped by
its bounds or merged by rounding. **coarse** = points after `valid_r2`; **box** = the largest fine box over every
possible coarse peak (a check only, 4.4); **tries** = the most systems the selection can run for the name (Stage 0 +
coarse - 1 + box - 1). The systems that can become the name's pick are Stage 0 + coarse - 1 (at most 88; 4,369 over
the 85 names). Code only; no data read.

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
