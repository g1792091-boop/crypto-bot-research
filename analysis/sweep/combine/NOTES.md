# Combine + IS exit stage: NOTES

Agent: Combine (2026-09-29, 12:32-12:45 UTC). IS data only. Every number below comes from the scripts in
this directory; logs are in `logs/`.

## 0. Integrity

- `sha256sum -c PREREG.sha256`: 11/11 OK before the run (12:32 UTC) and after it (12:40:59 UTC).
  PREREG.md sha256 = `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50`.
- `lib/sweep_lib.py` is an unmodified copy (sha256 `2b20c3c1...cd543`, same as the harness).
  `lib/vendor/` is byte-identical to `harness/vendor/` (`diff -rq`). No bug was found and nothing was fixed,
  so no pre-registered rule changed.
- Holdout discipline:
  - `data/` contains only a symlink `is -> sweep/data/is`, and every script sets `SWEEP_DATA` to it.
  - Bars were loaded only for the descriptive extras (section 4). The last bars loaded were 1h 2024-06-30 23:00,
    4h 2024-06-30 20:00 and 1d 2024-06-30, all asserted < 2024-07-01.
  - No `oos/`, `final/` or `data/qa` file was read. No Astral tool was called.
  - `/home/user/crypto-bot-research`: `git status --porcelain` is empty.

## 1. Combine (PREREG 4.3/4.4, `combine_gate.py`, `verify_holm.py`)

- Inputs are the 7 raw harness tables `discover_*/out/gate_is_*.csv`:
  - 5m: 2 strategy subsets;
  - 15m and 30m: 1 table each;
  - 1h, 4h and 1d: 1 table each.
- The 7 tables hold 666 rows = 37 strategies x 6 TF x 3 H, with no duplicates and no missing or extra cells. No
  Discover group failed.
- Cross-check against the Discover agents' assembled `gate_cells.csv` (n, fwd, z, p, p_vn, z_vn, mu*, cost_H,
  symbols_pos, n_coins_ge10, net_time): max abs diff 4.4e-16, with 0 NaN mismatches.
- The 5m subsets share n_min, mu* and E|r| for each H, so their shift nulls are identical.
- `sweep_lib.apply_gate` was applied once over all 666 rows.
  - The family (n >= 100 with finite p and p_vn) has m = 528 cells: 5m 105, 15m 102, 30m 99, 1h 96, 4h 81, 1d 45.
  - The 138 cells outside it all have n < 100.
  - The Discover notes used m = 666 as a reference only. The real m is 528, so the Holm first step is p < 9.47e-5
    (z > 3.73).
- **gate_pass survivors: 0. gate_pass_spec survivors (orchestrator rule without A1, descriptive): 0.**
  - Smallest raw p in the family: 7.96e-4 (N13_3OUTSIDE 4h H64, an approximate port), giving p_holm = 0.420. It
    would need m <= 62 to pass Holm step 1, so the verdict does not depend on m.
  - Conditions met in the family:
    - c1 p_holm < 0.05: 0
    - c2 p_vn_holm < 0.05: 15
    - c3 fwd >= mu*: 15
    - c4 symbols: 220
    - c3 & c4: 15
    - c1 & c3: 0
  - The 15 c2 cells are all fade-type or V45 entries at 5m-1h: N17_KC_RSI, V45_AMB, N25 15m H4. Their z_vn values
    (up to 25) come from bar-level mean reversion, as the Discover agents documented. Their fwd runs from -15 % to +35 % of mu*, and 3 of them have
    fwd < 0.
- An independent Holm implementation matches `apply_gate` (max diff 1e-16) and gives the same 0 / 0 decision.

## 2. IS exit stage (PREREG 5)

No cell survived the gate, so **no pre-registered exit run was made, no combo was selected, and
`carried.json` has `"carried": []`**. `carried.json` also lists, for information only, the 15 family cells with
fwd >= mu* that failed Holm. They are explicitly marked NOT carried. Their OOS values will appear anyway in the
PREREG 7.2 persistence table the Holdout agent computes, so no protocol change is needed to see them.

## 3. Descriptive IS table (PREREG 7.1): `is_table.md`, `is_table.csv`, `is_table_long.csv`, `is_counts.csv`

- Each cell shows the best H: `fwd% / z / (fwd-mu*)% / net_time% H CODE`.
  - Best H is the H with the largest fwd - mu* among cells with n >= 100. If no H has n >= 100, it is taken from
    the cells with n > 0, and the code is `n<100`.
  - This is a post-hoc maximum over 3 H, so it is biased upward.
- `[any-H: ...]` flags a stronger code at another H.
- `(up)` marks cells underpowered under PREREG 9, where n < the synthetic iid n_req from
  `harness/out/controls_n_required.csv`.

Headline counts (family = 528 cells with n >= 100; "all" = 633 cells with n > 0):

| | family | all n>0 |
|---|---|---|
| fwd > 0 before costs | 225 (42.6 %) | 273 |
| z > 2 nominal | 19 | 23 |
| fwd > cost_H | 46 | - |
| fwd >= mu* | 15 | 52 (37 of the extra are n<100 cells, mostly 1d/4h with n of 1-99) |
| raw p < 0.05 | 31 (expected by chance: 26.4) | - |
| Holm-significant p / p_vn | 0 / 15 | - |
| gate_pass / gate_pass_spec | 0 / 0 | - |

By TF (family):

| TF | fwd>0 | z>2 | fwd>cost | fwd>=mu* |
|---|---|---|---|---|
| 5m | 28/105 | 2 | 0 | 0 |
| 15m | 43/102 | 2 | 0 | 0 |
| 30m | 38/99 | 0 | 1 | 0 |
| 1h | 54/96 | 9 | 15 | 3 |
| 4h | 39/81 | 3 | 10 | 2 |
| 1d | 23/45 | 3 | 20 | 10 |

The family z distribution (`out/diag_zdist.csv`) has mean -0.20, sd 1.26 and max 3.16.
- Expected count of z > 2: 12 if z ~ N(0,1), or 29 with sd 1.25, which is the real-timing null sd the Discover
  agents measured. Observed: 19. Nominal p < 0.05: 31 observed against 26.4 expected.
- So the family as a whole looks like noise.
- The one mild excess is at 1h: mean z +0.27, 9 cells with z > 2 (2.2-5.3 expected) and 11 with p < 0.05 (4.8
  expected). But the cells are strongly correlated (the same strategy across 3 H, and many trend-followers), and
  only 3 of those 1h cells reach mu*.
- 5m has mean z -0.72: trend entries time worse than random there.

Per TF:
- **5m / 15m / 30m:** no cell even beats plain cost. The largest fwd/mu* is 0.16 at 5m, 0.40 at 15m and 0.60 at
  30m. At these TFs power at the hurdle is good for dense strategies (Discover), so this null is informative.
- **1h:** 3 cells clear mu*:
  - DOGE_L H64: fwd 0.81 % vs mu* 0.65 %, z 2.64, previously examined;
  - N03_ADX_GC H4 and H16: n 180, z 2.04 and 1.48, underpowered.
  - None is close to Holm.
- **4h:** N13_3OUTSIDE (approximate port) H16 and H64 are the strongest cells in the sweep: z 2.59 / 3.16, p_vn
  0.017 / 0.020, n 236 / 234, underpowered.
- **1d:** 10 cells clear mu*, mostly H64 trend-followers (S2, N01, N02, N04, N23, N25) plus 1d H4 N02/N18/N23. All
  are underpowered (n 140-650, overlapping), with max z 2.19.

## 4. Extras: descriptive only, NOT pre-registered, decide nothing

### 4a. Exit stage on the 15 near-miss cells (`run_exits_descriptive.py`, `out/exits_descriptive_nearmiss_*.csv`)

- `sweep_lib.exits()` was run unchanged: 5 exits, B = 300, studentised max-stat p.
- Signals were recomputed from `data/is` and are bit-identical to the Discover caches `signals_is_{1h,4h,1d}.npz`
  (0 mismatches).
- 14 of 75 exit rows, in 6 of the 15 cells, meet the exit-pass criteria. The exit-criteria column is renamed
  `exit_criteria_met_DESCRIPTIVE`, and `carry_eligible` is False for every row:
  - N13_3OUTSIDE 4h H16: 4 exits (e.g. TIME_H: 224 trades, PF 1.60, +1.07 %/trade, 6/7 coins, p_max 0.013);
  - N13_3OUTSIDE 4h H64: 4 exits;
  - N02_ST_KST 1d H4 (TIME_H, TIME_H_SL3);
  - N18_VWMA_MACD 1d H4 (TIME_H, TIME_H_SL3);
  - N23_HA_ST 1d H16 (TIME_H);
  - N03_ADX_GC 1h H4 (ATR_SL2_TP3, p_max 0.0498).
- DOGE_L 1h H64 fails every exit (best is TIME_H at PF 1.15 with p_max 0.096; the ATR and trail exits are negative).
- At 1d, the ATR and trailing exits lose money in almost every cell; only the pure time exits hold up.
- **These cannot count as evidence, for two reasons:**
  - The 15 cells were chosen out of 528 because their IS forward return was already above the hurdle. TIME_H is
    essentially the non-overlapping version of the same gate statistic, so this counts the same IS returns twice.
  - The exit p_max is adjusted neither for the 528-cell selection nor with A1.

### 4b. N13_3OUTSIDE 4h anatomy (`diag_n13_4h.py`, `logs/diag_n13_4h.log`)

- Long and short are both positive (H16: +1.49 % long, +0.89 % short). At H16 all 7 coins have fwd_c > 0.
- The median signal return is positive (+1.0 %), but the 10 best signals account for 54 % of the sum.
- By half-year, the H16 means are +2.9 %, +0.1 %, +0.0 %, +1.2 %, +1.9 % and +1.8 %. They are flat through 2022.
- Signal bars have 1.35x the coin's median range, so the signals are vol-timed. That is the regime where the raw
  null is known to be anti-conservative, and z_vn is only 2.1.
- It is a spec-based approximate port, not the author's exact code.
- It is the most "alive" non-significant cell. Under the protocol it can only be followed up as a new,
  separately pre-registered hypothesis, and its OOS value will appear descriptively in PREREG 7.2.

## 5. Caveats

- "No survivor" at 4h and 1d is mostly a power statement: 63/81 and 45/45 family cells are underpowered by the
  optimistic iid n_req. At 5m-30m it is informative. At 1h it is partly informative.
- The best-H columns in the table are upward-biased post-hoc maxima. The `n<100` cells show huge, meaningless
  numbers (e.g. S1 1d +90 % on n < 100).
- Degraded data were kept as PREREG requires: the thin XRP feed from 2022-03 to 2023-07, BCH gaps, and unclipped
  suspect spikes.
- Gate n counts overlapping signals, while the exit stage holds one position per coin. The spot proxy and fixed
  funding caveats of PREREG 10 apply.
- `carried.json` holds an informational near-miss list in addition to the empty `carried` list. Consumers should
  read only `carried`.
