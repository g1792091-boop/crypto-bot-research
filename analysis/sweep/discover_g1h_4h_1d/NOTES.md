# Discover gate: 1h + 4h + 1d (IS only)

Agent: Discover, TF group [1h, 4h, 1d]. Written 2026-09-29. Every number here comes from code in this
directory. Outputs are in this directory and `out/`; logs (with UTC start/end, wall time and exit code)
are in `logs/`.

## Protocol integrity

- `cd sweep && sha256sum -c PREREG.sha256`: all 11 files OK before the run (12:14 UTC) and after all
  runs (12:27 UTC).
  - PREREG.md sha256 = `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50`
  - sweep_lib.py sha256 = `2b20c3c155f31bbe3b51cc3b7b96a8b8c01226d6cf573cb601077d89f98cd543`
- Local copies are byte-identical to the harness: `sweep_lib.py`, `run_gate_tf.py` (`8cec4d91...`),
  `run_controls.py` (`5451cb5e...`), and all 8 `vendor/*.py` (checked with `cmp`).
- **No bug was found or fixed. No harness file was modified. No pre-registered rule changed.**
- Data read: only `sweep/data/is/` 1h/4h/1d files, through `sweep_lib.load(split="is")`, plus a
  direct read of the same IS files in `verify_cells.py`, which asserts max ts < 2024-07-01.
  - Last bar loaded: 2024-06-30 23:00 (1h), 20:00 (4h), 2024-06-30 (1d). `load()` dropped 0 bars
    (no bar >= 2024-07-01 exists in these files).
  - Every run used `--split is` (6 of 6 runner invocations; see logs). No OOS or FINAL file was opened.
  - `data/qa/*` was not read.
- Loaded panel: 0 gaps and 0 misaligned bars at 1h/4h/1d for all 7 coins (partial bins exist where
  the 5m feed has gaps; they are kept, as PREREG section 1 says). Starts: 2021-07-01 (BTC, ETH, XRP,
  LTC, BCH), 2021-08-01 (DOGE), 2021-10-01 (SOL). The XRP thin-feed window (2022-03..2023-07) was
  left in.
- No Astral tool was called. `/home/user/crypto-bot-research`: `git status --porcelain` is empty.
- Holm is NOT applied here (PREREG 4.3: the Combine agent applies it once over all 6 TFs).

## What was run (OMP_NUM_THREADS=1, at most 2 of my processes at a time)

| step | command | wall time |
|---|---|---|
| gate 1h | `run_gate_tf.py --tf 1h --split is` | 70 s (signals 64 s, gate 4 s) |
| gate 4h | `run_gate_tf.py --tf 4h --split is` | 21 s (signals 18 s, gate 2 s) |
| gate 1d | `run_gate_tf.py --tf 1d --split is` | 6 s (signals 4 s, gate < 1 s) |
| controls, real IS (PREREG section 9 style) | `run_controls.py --tf {1h,4h,1d} --split is --reps 200` (seed 1) | 167 s / 144 s / 103 s |
| extra A: timing-preserving random-sign control | `run_strategy_timing_controls.py` (4h, 1d: 200 reps; 1h: 40 reps; seed 7) | 229 s / 30 s / 176 s |
| extra B: more-rep zero-edge controls, long H | `controls_1d_tail.py` (1d H16/H64 1000 reps; 4h H64 500 reps; seed 2) | 56 s / 17 s |
| extra C: joint-tail check on 17 real cells, 500 reps each | `tail_check.py` (seed 99) + `tail_percentiles.py` | 20 s / 13 s / 46 s |
| independent recomputation of 8 cells | `verify_cells.py` | < 1 min |
| diagnostics | `strategy_summary.py`, `diag_vn.py` | < 1 min |

Total CPU for the pre-registered gate itself: about 97 s. Everything including extras: about 19 CPU-min.

Signal cost for all 37 strategies: 350 µs/bar at 1h (63.5 s, 181,176 bars), 400 µs/bar at 4h (18.1 s,
45,294 bars), 556 µs/bar at 1d (4.2 s, 7,549 bars). Slowest: N16_BBRSI (24.5 s at 1h), N05_PSAR_POC
(9.5 s), V39_ALL (8.5 s), V45_AMB (6.4 s).

**No strategy failed to compute.** `compute_signals(strict=True)` raised nothing, and the gate logs
contain no warnings or errors.

Structural zero or near-zero signal counts (properties of the strategies, not errors; totals over the
whole loaded series, including warm-up):

| strategy | 1h | 4h | 1d |
|---|---|---|---|
| DOGE_L / DOGE_S | 1,776 / 1,755 | 0 / 0 | 0 / 0 |
| N21_ST_RSI_ADX | 1 | 0 | 0 |
| N14_ICHI_RSI | 4 | 2 | 0 |
| N06_MACD_ORB | 2,440 | 684 | 0 |
| N15_KC_AO | 23 | 3 | 2 |
| S1_EMA_RSI_CHOP | 49 | 11 | 1 |
| N11_BREAKAWAY | 75 | 20 | 6 |

DOGE at 4h/1d and N06 at 1d are the structural zeros PREREG section 3 predicted.

## Outputs

- `gate_cells.csv`: 333 rows = 37 strategies x 3 TFs x H in {4, 16, 64}. It has the same columns as
  `discover_g15_30/gate_cells.csv`: every harness column under its harness name, so Combine can pass
  the concatenation straight to `sweep_lib.apply_gate`. Aliases requested by the task are included:
  - `fwd_pct`
  - `fwd_<coin>` / `fwd_pct_<coin>`, `n_<coin>`
  - `symbols_pos`, `n_coins_ge10`
  - `null_mean`, `null_sd`, `z`, `p_one_sided` (= `p`)
  - `cost_H`, `E_abs_rH`, `mu_star`, `net_time`
  - `fwd_minus_mu_star`
  - `previously_examined`, `approx`
  - A1 columns: `fwd_vn`, `z_vn`, `p_vn`
  - Descriptive: `p_emp600`, `p_emp_all`, `t_naive`
  - Labels: `family_candidate`, `sympos_ok`, `n_req_iid`/`n_req_burst4` (synthetic, per PREREG
    section 9), `underpowered`, and the indicative `p_lt_alpha_over_666` / `p_vn_lt_alpha_over_666`.
- Raw harness tables: `out/gate_is_{1h,4h,1d}.csv`. Signal caches for the exit stage:
  `out/signals_is_{1h,4h,1d}.npz`. Per-strategy timings: `out/timings_is_*.csv`.
- `controls.csv`: `sweep_lib.controls()` on the REAL IS panel (`data=is`, 200 reps, seed 1), plus the
  harness agent's synthetic rows for 1h/4h/1d (`data=synthetic`), for comparison.
  - Summaries: `controls_summary.csv`, `controls_n_required_real_is.csv`.
- `controls_strategy_timing.csv` and `controls_strategy_timing_summary.csv`: extra A (descriptive).
- `out/controls_extra_is_{1d,4h}_seed2.csv`: extra B (descriptive).
- `out/tail_check_{summary,reps}_{1h,4h,1d}.csv` and `out/tail_check_percentiles.csv`: extra C
  (descriptive).
- `out/verify_cells.csv`: independent recomputation.
- Tables:
  - `top15_by_z_n100.csv`, `top15_by_fwd_minus_mu_n100.csv`
  - `top15_by_z_all.csv`, `top15_by_fwd_minus_mu_all.csv`
  - `top15.txt`
  - `gate_summary_by_tf_H.csv`, `strategy_tf_summary.csv`
- Diagnostics: `out/diag_vn_momentum.csv`, `out/diag_autocorr_is.csv`.

## Results

### Headline: no 1h, 4h or 1d cell can pass the gate

- There are 222 family candidates (n >= 100, finite p and p_vn): 96 at 1h (32 strategies x 3 H),
  81 at 4h (27 x 3) and 45 at 1d (15 x 3).
- The smallest in-family raw p is 7.96e-4: N13_3OUTSIDE 4h H64, an approx port, z = 3.16.
  - Holm can reject a cell with p_i only if (m − #cells with smaller p) x p_i < 0.05. So m − k < 62.8
    would be needed.
  - As an indicative check only, I read the three Discover gate tables that exist at 12:28 UTC
    (5m 105, 15m/30m 201 and 1h/4h/1d 222 family cells, so m = 528). This cell has the smallest p of
    all 528, so its Holm-adjusted p would be about 528 x 7.96e-4 = 0.42.
  - **So `gate_pass` and `gate_pass_spec` are FALSE for every one of the 333 cells in this group**,
    whatever Combine's final m is.
- The A1 condition is also far away. The smallest max(p, p_vn) in the group is 0.0073 (N20_EMA9_CHOP 1h
  H64, whose fwd is also below mu\*).
- 15 of the 222 candidates have fwd >= mu\* (listed below). 45 have net_time > 0. 52 % have gross
  fwd > 0.
- 20 of 222 have p < 0.05, against 11.1 expected under the null. 8 have p_vn < 0.05, and 4 have both.
- **Because no cell survives, no exit stage is needed for 1h/4h/1d.**

Gate summary (family candidates; percentages per signal):

| tf | H | cells n>=100 | mu\* | E\|r_H\| | cost_H | fwd>=mu\* | net_time>0 | fwd>0 | p<0.05 | p_vn<0.05 | both | max z | underpowered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1h | 4 | 32 | 0.246 % | 1.107 % | 0.145 % | 1 | 1 | 12 | 2 | 2 | 0 | 2.36 | 5 |
| 1h | 16 | 32 | 0.368 % | 2.280 % | 0.160 % | 1 | 6 | 20 | 4 | 1 | 0 | 2.31 | 10 |
| 1h | 64 | 32 | 0.649 % | 4.711 % | 0.220 % | 1 | 8 | 22 | 5 | 1 | 1 | 2.64 | 17 |
| 4h | 4 | 27 | 0.367 % | 2.269 % | 0.160 % | 0 | 3 | 15 | 1 | 1 | 0 | 2.18 | 21 |
| 4h | 16 | 27 | 0.645 % | 4.674 % | 0.220 % | 1 | 4 | 12 | 1 | 1 | 1 | 2.59 | 21 |
| 4h | 64 | 27 | 1.363 % | 9.925 % | 0.460 % | 1 | 3 | 12 | 1 | 1 | 1 | 3.16 | 21 |
| 1d | 4 | 15 | 0.781 % | 5.720 % | 0.260 % | 3 | 10 | 10 | 3 | 0 | 0 | 2.19 | 15 |
| 1d | 16 | 15 | 1.738 % | 12.289 % | 0.620 % | 1 | 4 | 6 | 1 | 0 | 0 | 1.69 | 15 |
| 1d | 64 | 15 | 4.463 % | 26.404 % | 2.060 % | 6 | 6 | 7 | 2 | 1 | 1 | 1.96 | 15 |

The shift nulls use n_min = 23,311-23,371 (1h), 5,659-5,719 (4h) and 739-799 (1d; SOL is the shortest).
B = 600 in every cell.

### Top 15 by z (n >= 100)

"pe" = previously examined; "up" = underpowered (PREREG section 9 label). Full columns are in
`top15_by_z_n100.csv`.

| # | strategy | tf | H | n | fwd % | mu\* % | fwd−mu\* | z | p | z_vn | p_vn | sym+ | flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | N13_3OUTSIDE | 4h | 64 | 234 | 3.332 | 1.363 | +1.969 | 3.16 | 8.0e-4 | 2.06 | 0.020 | 6/7 | approx, up |
| 2 | DOGE_L | 1h | 64 | 1717 | 0.811 | 0.649 | +0.162 | 2.64 | 0.0042 | 0.15 | 0.44 | 7/7 | pe, up |
| 3 | N13_3OUTSIDE | 4h | 16 | 236 | 1.238 | 0.645 | +0.593 | 2.59 | 0.0048 | 2.13 | 0.017 | 7/7 | approx, up |
| 4 | N20_EMA9_CHOP | 1h | 64 | 7051 | 0.185 | 0.649 | −0.464 | 2.44 | 0.0072 | 2.59 | 0.0048 | 4/7 | approx |
| 5 | N05_PSAR_POC | 1h | 4 | 1365 | 0.114 | 0.246 | −0.132 | 2.36 | 0.0092 | −0.53 | 0.70 | 6/7 | approx |
| 6 | N07_ICHI_CMO | 1h | 16 | 2153 | 0.235 | 0.368 | −0.133 | 2.32 | 0.010 | −0.60 | 0.72 | 7/7 | |
| 7 | N12_ICHI_AO | 1h | 16 | 2440 | 0.222 | 0.368 | −0.145 | 2.23 | 0.013 | −1.21 | 0.89 | 6/7 | |
| 8 | N22_VORTEX_PSAR | 1h | 16 | 12731 | 0.083 | 0.368 | −0.284 | 2.22 | 0.013 | −0.00 | 0.50 | 6/7 | |
| 9 | V39_ALL | 1h | 64 | 5822 | 0.434 | 0.649 | −0.215 | 2.21 | 0.014 | 0.52 | 0.30 | 6/7 | |
| 10 | N02_ST_KST | 1d | 4 | 149 | 1.861 | 0.781 | +1.081 | 2.19 | 0.014 | 1.12 | 0.13 | 5/7 | up |
| 11 | N23_HA_ST | 1d | 4 | 650 | 1.067 | 0.781 | +0.287 | 2.18 | 0.014 | −0.23 | 0.59 | 6/7 | up |
| 12 | S4_BB_BBP | 4h | 4 | 1403 | 0.270 | 0.367 | −0.097 | 2.18 | 0.015 | −1.10 | 0.86 | 5/7 | approx, up |
| 13 | N18_VWMA_MACD | 1d | 4 | 461 | 1.632 | 0.781 | +0.852 | 2.10 | 0.018 | 0.18 | 0.43 | 6/7 | up |
| 14 | DOGE_S | 1h | 16 | 1707 | 0.187 | 0.368 | −0.180 | 2.05 | 0.020 | −1.25 | 0.89 | 5/7 | pe, up |
| 15 | N03_ADX_GC | 1h | 4 | 180 | 0.273 | 0.246 | +0.028 | 2.04 | 0.021 | −0.41 | 0.66 | 5/7 | up |

### Top 15 by fwd − mu\* (n >= 100)

These 15 are exactly the 15 family cells with fwd >= mu\*.

| # | strategy | tf | H | n | fwd % | mu\* % | fwd−mu\* | z | z_vn | sym+ | flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | N01_ST_EMA | 1d | 64 | 146 | 8.302 | 4.463 | +3.840 | 1.46 | 1.34 | 6/7 | up |
| 2 | N25_DST_CCI | 1d | 64 | 241 | 7.744 | 4.463 | +3.281 | 1.37 | 1.58 | 7/7 | up |
| 3 | N04_ST_KLINGER | 1d | 64 | 576 | 6.794 | 4.463 | +2.331 | 1.85 | 1.72 | 5/7 | approx, up |
| 4 | N13_3OUTSIDE | 4h | 64 | 234 | 3.332 | 1.363 | +1.969 | 3.16 | 2.06 | 6/7 | approx, up |
| 5 | S2_ST_ROC | 1d | 64 | 488 | 5.860 | 4.463 | +1.397 | 1.46 | 0.96 | 6/7 | up |
| 6 | N23_HA_ST | 1d | 64 | 612 | 5.799 | 4.463 | +1.336 | 1.96 | 1.19 | 6/7 | up |
| 7 | N02_ST_KST | 1d | 64 | 140 | 5.682 | 4.463 | +1.219 | 1.49 | 0.82 | 4/7 | up |
| 8 | N02_ST_KST | 1d | 4 | 149 | 1.861 | 0.781 | +1.081 | 2.19 | 1.12 | 5/7 | up |
| 9 | N18_VWMA_MACD | 1d | 4 | 461 | 1.632 | 0.781 | +0.852 | 2.10 | 0.18 | 6/7 | up |
| 10 | N13_3OUTSIDE | 4h | 16 | 236 | 1.238 | 0.645 | +0.593 | 2.59 | 2.13 | 7/7 | approx, up |
| 11 | N23_HA_ST | 1d | 16 | 642 | 2.126 | 1.738 | +0.388 | 1.69 | 0.68 | 6/7 | up |
| 12 | N23_HA_ST | 1d | 4 | 650 | 1.067 | 0.781 | +0.287 | 2.18 | −0.23 | 6/7 | up |
| 13 | DOGE_L | 1h | 64 | 1717 | 0.811 | 0.649 | +0.162 | 2.64 | 0.15 | 7/7 | pe, up |
| 14 | N03_ADX_GC | 1h | 16 | 180 | 0.430 | 0.368 | +0.062 | 1.48 | 0.54 | 4/7 | up |
| 15 | N03_ADX_GC | 1h | 4 | 180 | 0.273 | 0.246 | +0.028 | 2.04 | −0.41 | 5/7 | up |

What the fwd >= mu\* cells are:
- **1d H64 trend-followers** (N01, N25, N04, S2, N23, N02).
  - Their gains are long-side: fwd_long is +11 to +18 %, and fwd_short is negative for 5 of the 6.
  - They are concentrated in SOL (+19 to +36 % per signal for 5 of them) and BCH (+8 to +27 %), which
    rallied in 2023. XRP is negative in 5 of 6.
  - Signals are few and heavily overlapping: 140-612 signals in 39-64 "episodes" (runs of same-sign
    signals no more than H bars apart).
  - Their own timing-preserving zero-edge nulls put the observed z at p_rs = 0.09-0.23
    (`out/tail_check_percentiles.csv`). **This is the 2022-2024 trend regime seen through about 40-60
    independent bets, not evidence of an edge.**
- **N13_3OUTSIDE 4h H16/H64** (approx port, three-outside-bar pattern) is the most interesting cell in
  this group.
  - fwd is above mu\* at both H, sym+ is 7/7 and 6/7, and z_vn is 2.1 at both.
  - Its timing-preserving p_rs is 0.008 and 0.010, and p_emp_all is 0.0046 and 0.0024.
  - It is still far from the family threshold. Its p (7.96e-4) is 8.4 x the first Holm step for
    m = 528 (9.5e-5), and its p_vn (0.020) is 209 x that step. n is only about 235 (about 33 signals
    per coin in 3 years), and it is a spec-based approximation that cannot be checked against the
    source.
- **DOGE_L 1h H64** (previously examined, long only).
  - About 0.18 % of its 0.81 % fwd is the long-drift null mean.
  - Its z_vn is 0.15, so there is no timing edge in volatility-normalised terms. Its raw z of 2.64
    looks like vol and drift timing.

Outside the family (n < 100; reported, not eligible), the largest raw z values are:
- S5_DONCHIAN_MFI 4h H4: n = 70, z = 4.54, but z_vn = 0.50. This is a textbook breakout/vol-timing
  artefact, and only 2 coins have 10 or more signals.
- S1_EMA_RSI_CHOP 1d H16: n = 1.
- N13_3OUTSIDE 1d H4: n = 38, z = 3.62.
- N03_ADX_GC 1d H64: n = 5.

### Previously examined strategies (flag `prev_examined=True`)

- **V45_AMB**:
  - 1h: fwd 0.065 / 0.017 / −0.073 % at H4 / H16 / H64, all far below mu\*. z_vn is +3.17 at H4
    (counter-trend entries in a short-horizon reversal; see diagnostics), but the gross return is tiny.
  - 4h: negative at every H (−0.34 / −1.16 / −1.31 %), with 1-2 of 7 coins positive.
  - 1d: n = 23, outside the family.
- **DOGE_L / DOGE_S**:
  - 1h: see DOGE_L H64 above. DOGE_S is +0.08 / +0.19 / +0.27 %, below mu\* at every H.
  - 4h/1d: 0 signals (structural).

### Power: the three TFs differ

The per-cell MDE80 is computed from each cell's own null sd at the first Holm step with m = 666
(`controls_strategy_timing.csv`):

| tf | median MDE80/mu\* at H4 / H16 / H64 | family cells able to detect an edge < mu\* with 80 % power |
|---|---|---|
| 1h | 0.82 / 1.08 / 1.45 | 43 of 96 |
| 4h | 1.75 / 2.38 / 2.84 | 2 of 81 |
| 1d | 4.27 / 4.90 / 4.37 | 0 of 45 |

What this means for each TF:
- **1h:** "no survivor" is partly informative. For about half of the dense strategies, an edge of
  hurdle size would probably have been seen.
- **4h and 1d:** "no survivor" is almost purely a power statement. The median 1d cell could detect
  only an edge of about 4-5 x mu\* (about 20 % per signal at H64), so the data could not have shown a
  hurdle-sized edge at 1d. **It is not evidence that no edge exists at 4h/1d.**

n_req on the real IS panel (MDE80 <= mu\* at the first Holm step, `controls_n_required_real_is.csv`):

| | 1h H4 / H16 / H64 | 4h H4 / H16 / H64 | 1d H4 / H16 / H64 |
|---|---|---|---|
| iid | 1131 / 1973 / 2484 | 1944 / 2495 / 2517 | 2671 / 2483 / 1581 |
| burst4 | 3078 / 7235 / 9650 | 5435 / 9323 / 10149 | 8000 / 10056 / 6486 |

For comparison, the harness's synthetic iid values were 1313 / 2085 / 2700, 2347 / 2854 / 2331 and
2904 / 2964 / 2168, so the PREREG "underpowered" label is slightly conservative.

The 1d panel has only 6,114 / 6,030 / 5,694 admissible coin-bars at H4 / H16 / H64. A 1d strategy
would need to signal on roughly 25-45 % of all bars (iid-like) to reach n_req.

## Controls

### A. `sweep_lib.controls()` on the real IS panel (`controls.csv`; 200 reps per row, 36 rows per TF)

**Zero-edge calibration of the raw null**
- iid, burst4 and hourtimed: p<0.05 rate 0.047-0.067, z sd 0.87-1.28.
- voltimed: p<0.05 rate 0.121 (1h), 0.073 (4h) and 0.058 (1d); z sd 1.11-1.65 at 1h.
- **As at 15m/30m, the raw null is anti-conservative for vol-timed signals, strongest at 1h.**

**A1 (vn) null**
- p<0.05 rate 0.045-0.059, z sd 0.90-1.24.

**Full gate at the first Holm step (m = 666), zero-edge reps**

| tf | raw rule (`gate_pass_spec`) | with A1 (`gate_pass`) |
|---|---|---|
| 1h | 6 of 7,200 | 0 |
| 4h | 3 of 7,200 | 0 |
| 1d | 3 of 7,200 | **3 of 7,200** |

All three 1d A1 false passes are in the row 1d H64, burst4, n = 150 (3 of 200 reps). There, the raw
z sd is 1.28 and the vn z sd is 1.23.

**Planted edge of 1.5 x mu\* (gate including A1)**

| tf, H | iid n=500 | iid n=2000 | burst4 n=2000 |
|---|---|---|---|
| 1h H4 | 0.81 | 1.00 | 0.96 |
| 1h H16 | 0.37 | 0.99 | 0.44 |
| 1h H64 | 0.26 | 0.98 | 0.27 |
| 4h H4 | 0.36 | 1.00 | 0.63 |
| 4h H16 | 0.26 | 0.98 | 0.26 |
| 4h H64 | 0.24 | 0.99 | 0.28 |
| 1d H4 | 0.22 | 0.99 | 0.33 |
| 1d H16 | 0.30 | 0.98 | 0.26 |
| 1d H64 | 0.48 | 0.99 | 0.47 |

The harness's synthetic rows for 1h/4h/1d are included for comparison: 8 raw false passes and 0 with A1.

### B. Extra, descriptive: timing-preserving random-sign control on the real strategies

Design: each strategy's real signal timing is kept, and the direction is replaced by a random sign
per episode.

| tf | H | cells | reps | median raw z sd | median vn z sd | mean rate p<0.05 | mean rate p_vn<0.05 | mean rate both |
|---|---|---|---|---|---|---|---|---|
| 1h | 4 | 32 | 40 | 1.01 | 0.99 | 0.061 | 0.045 | 0.024 |
| 1h | 16 | 32 | 40 | 1.00 | 0.98 | 0.054 | 0.052 | 0.026 |
| 1h | 64 | 32 | 40 | 1.03 | 1.03 | 0.045 | 0.052 | 0.026 |
| 4h | 4 | 27 | 200 | 0.97 | 1.02 | 0.048 | 0.054 | 0.023 |
| 4h | 16 | 27 | 200 | 0.99 | 1.02 | 0.049 | 0.052 | 0.028 |
| 4h | 64 | 27 | 200 | 1.00 | 1.02 | 0.058 | 0.056 | 0.034 |
| 1d | 4 | 15 | 200 | 1.00 | 1.01 | 0.056 | 0.048 | 0.021 |
| 1d | 16 | 15 | 200 | 0.94 | 1.01 | 0.043 | 0.045 | 0.022 |
| **1d** | **64** | 15 | 200 | **1.35** | **1.26** | **0.112** | **0.094** | **0.071** |

- The 1h, 4h, 1d H4 and 1d H16 cells are roughly calibrated.
- Single sparse cells have inflated raw z sd: N03_ADX_GC 1h H4 1.81, S6_EMA_DMI_ADX 1h H4 1.48,
  N01_ST_EMA 4h H64 1.42.
- **1d H64 is not calibrated, for raw OR vn.**

### C. Extra, descriptive: more reps at long H, and the joint tail on real cells

More reps (seed 2, `out/controls_extra_is_*_seed2.csv`):
- 1d H64: A1 false passes 2/1000 (iid, n=150), 1/1000 (burst4, n=150), 0/1000 (iid, n=500) and
  0/1000 (burst4, n=500).
- 1d H16: 1/1000 (iid, n=500).
- 4h H64: 0/2000.
- Pooled with A: **1d H64 zero-edge cells pass the full A1 gate at the first Holm step about 6 times in
  6,400 (about 1e-3 per cell)**, against a nominal per-cell level below 7.5e-5.

Joint-tail check on the real near-hurdle cells (500 timing-preserving reps each, `out/tail_check_*`):
- At 1d H64, z and z_vn correlate 0.88-0.93 across reps, so A1 adds almost no independent
  protection there.
- Zero-edge fwd >= mu\* held in 12-30 % of reps, so the hurdle is weak there too.
- The full A1 rule false-passed:
  - S2_ST_ROC 1d H64: 3 of 500
  - N25_DST_CCI 1d H64: 1 of 500
  - N04_ST_KLINGER 1d H64: 1 of 500
- At 1h and 4h: 0 A1 false passes among the tested cells. The raw rule false-passed N03_ADX_GC 1h H4
  4/500, DOGE_L 1h H64 2/500 and N13_3OUTSIDE 4h H64 1/500.

**Message for Combine / Holdout / orchestrator (descriptive; no rule changes):**
- At 1d H64, the normal-approximation p and p_vn are heavy-tailed. The whole 1d panel has only about
  11-13 non-overlapping 64-day windows per coin (739-831 admissible bars), and the coins are strongly
  correlated.
- A 1d H64 cell that ever reached the Holm threshold should not be trusted on that basis. The rate is
  about 1e-3 per cell against a nominal 7.5e-5; with 15 such cells, about 1.5 % family-wise from these
  cells alone.
- No real 1d cell came near: the max 1d z is 2.19 and the max 1d H64 z is 1.96. **So this changes no
  decision in this sweep.**

### D. Independent recomputation (`verify_cells.py`, `out/verify_cells.csv`)

- 8 cells were recomputed from the raw IS CSVs with my own window logic, forward returns, realised
  volatility, self-normalised return, and brute-force `np.roll` null (the pre-registered shifts are
  the only thing taken from the harness).
- The cells span all 3 TFs, all 3 H, sparse and dense, and pe and approx.
- n, n_min, fwd, z, z_vn, p, null_sd, mu\* and E|r| match the harness to within 3e-12 (n exactly).

## Observations (descriptive; no rule is affected)

1. **The short-horizon reversal dominates z_vn at 1h.**
   - At 1h H4, the mean z_vn over 32 cells is −3.48 (sd 3.39), while the raw z sd is 1.28.
   - The Spearman correlation of momentum-ness with z_vn is −0.59 at 1h H4 and −0.40 at 4h H4.
   - Momentum entries are negative: N23_HA_ST −11.6, S4_BB_BBP −8.0, S2_ST_ROC −7.5. Counter-trend
     entries are positive: N17_KC_RSI +5.9, V45_AMB +3.2.
   - Lag-1 autocorrelation of open-to-open returns: −0.037 to +0.002 (1h) and −0.133 to −0.011 (1d).
   - The size in returns is far below cost: N17 1h H4 has fwd −0.012 %.
2. **Cross-TF consistency of z is weak.** For the same strategy and H, Spearman rho(z) is −0.02 to
   0.41 for 1h vs 4h, −0.05 to 0.26 for 4h vs 1d, and −0.41 to 0.21 for 1h vs 1d. rho(z_vn) is higher
   (up to 0.70), consistent with 1 above.
3. **Approx ports** (`approx=True`, 108 rows): N13_3OUTSIDE 4h and N04_ST_KLINGER 1d H64 appear among
   the fwd >= mu\* cells. Neither can be checked against the original source.
4. The 1d cells with fwd >= mu\* are almost all long-side trend exposure in 2022-2024. OOS will say
   whether any of that is timing and not regime.

## Caveats

- The IS window keeps the XRP thin-feed period (2022-03..2023-07) and the suspect single-bar spikes;
  nothing is clipped or masked (PREREG section 1).
  - XRP is the negative coin in most 1d trend cells.
  - At 1d, N19_FIB_CHOP fires 23 times on XRP against 2-7 on the other coins (feed artefact
    suspected; outside the family).
- Extras A-D and the diagnostics are this agent's additions. They are descriptive, not in PREREG, and
  change no decision. Their seeds (7, 2, 99) are independent of the gate seeds.
- The Holm statement above is a bound based on the three Discover tables present at 12:28 UTC, not the
  official Holm. The official one is Combine's, and the conclusion (0 survivors in 1h/4h/1d) does not
  depend on m.
- The gate n counts overlapping signals. The exit stage was not run, because there are no candidates.
- The 1h timing control used 40 reps per cell, so its z sd values are noisy (about ±0.11).

## Final integrity check

Run at 2026-09-29T12:27 UTC, after all runs:
- `cd sweep && sha256sum -c PREREG.sha256`: all 11 files OK. PREREG.md and sweep_lib.py hashes are as
  above, equal to the values before the run.
- The local copies (sweep_lib.py, run_gate_tf.py, run_controls.py, vendor/) are byte-identical to the
  harness.
- `/home/user/crypto-bot-research`: `git status --porcelain` has 0 lines.
