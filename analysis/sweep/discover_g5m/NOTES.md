# Discover, 5m group (IS only): notes

Written 2026-09-29 by the Discover agent for the 5m timeframe. Every number below comes from code in
`lib/` that was run in this directory. The logs are in `logs/` and the raw outputs in `out/`.

## Scope and holdout discipline

- Timeframe: 5m. Registry: 37 strategies. Horizons H: 4, 16 and 64 bars. Coins: all 7. Split: IS only.
- `data/is` is a symlink to `sweep/data/is`. This directory has no `data/oos` or `data/final`, so the
  harness copy (`DATA_ROOT = discover_g5m/data`) cannot resolve an OOS or FINAL file.
- `load()` drops bars at or after 2024-07-01. Nothing was dropped, because the IS files end at
  2024-06-30 23:55. Every script also asserts `ts.max() < 2024-07-01`.
- No file under `sweep/data/oos`, `sweep/data/final`, `sweep/data/full` or `sweep/data/qa` was opened.
  I did not use the data agent's `ac1_quarterly.csv`, because it covers OOS quarters; I computed my own
  IS-only AC1 instead.
- Nothing under `/home/user/crypto-bot-research` was modified (`git status` is clean). No Astral tool was
  called.

## Pre-registration integrity

- `sha256sum -c sweep/PREREG.sha256` was run twice, before the run (11:44 UTC) and after it
  (about 12:12 UTC). Both times all 11 files were OK.
- PREREG.md sha256 = `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50`.
- `lib/sweep_lib.py` is a byte-identical copy (sha256 `2b20c3c1...cd543`), and so are
  `lib/run_gate_tf.py` (`8cec4d91...`), `lib/run_controls.py` and `lib/vendor/*`
  (`sha256sum -c VENDOR_SHA256.txt` gives all OK).
- **I found no bug and changed no library code.** No pre-registered rule, parameter, window,
  cost or threshold was touched.
- I added helper scripts. None of them changes a rule:
  - `lib/timed.py`: wall time and peak RSS.
  - `lib/postprocess.py`: concatenation and column aliases.
  - `lib/report.py`: descriptive tables.
  - `lib/realtiming_controls.py`: extra descriptive controls.
  - `lib/verify_cells.py`: independent recomputation.

## What was run

| step | command | wall | CPU user | peak RSS |
|---|---|---|---|---|
| gate, group A (18 strategies) | `run_gate_tf.py --tf 5m --split is --names $(groupA.txt)` | 636 s (signals 564, gate 70) | 367 s | 532 MB |
| gate, group B (19 strategies) | same, `groupB.txt` | 622 s (signals 539, gate 81) | 353 s | 531 MB |
| PREREG controls, iid+burst4, 200 reps, seed 1 | `run_controls.py --tf 5m --split is` | 487 s | 374 s | 510 MB |
| PREREG controls, voltimed+hourtimed, 200 reps, seed 2 | same | 512 s | 403 s | 543 MB |
| canary + reversal benchmark + AC1 | `realtiming_controls.py --canary` | 26 s | 12 s | 567 MB |
| sign-flip real-timing control, 6 reps (2 x 3) | `realtiming_controls.py --reps 6 --seed 11` | 314 s / 303 s | 146 s each | 686 MB |
| independent verification | `verify_cells.py` | 9.5 s | 8 s | 429 MB |

- Two processes ran at a time. The concurrent 15m/30m agent had two more, so wall time is about 1.7x CPU time.
- Total time from launch to last output was about 26 min.
- The groups were balanced on the harness's per-strategy timing (`groupA.txt`, `groupB.txt`). Shifts are
  keyed by (tf, H), so the two halves concatenate exactly.

**Strategies that failed to compute: none.** `compute_signals(strict=True)` raised nothing, and both
processes returned rc=0. The logs have no warnings.

**Zero or near-zero signal cells, as expected:**
- N21_ST_RSI_ADX has n = 0 at every H, so z and p are NaN.
- N14_ICHI_RSI has n = 3.
- Both are known structural cases and are not in the family, because n < 100.
- Family candidates at 5m: **105 of 111 cells**, i.e. 35 strategies x 3 H.

Signal counts n over all 7 coins at H=4:
- N17_KC_RSI 221k, N23_HA_ST 220k, N18_VWMA_MACD 202k, S2_ST_ROC 183k.
- At the low end: N15_KC_AO 136, S1_EMA_RSI_CHOP 256, N11_BREAKAWAY 774, N03_ADX_GC 2,162.

## Outputs

- `gate_cells.csv`: 111 rows, one per (strategy, H). It keeps all harness columns (`fwd`, `p`, `p_vn`,
  `z_vn`, `E_abs_r`, `prev_examined`, `n_<coin>`, `fwd_<coin>`, ...), which the Combine agent needs
  for `apply_gate`.
  - Added aliases: `fwd_pct`, `p_one_sided` (= p), `E_abs_rH` (= E_abs_r), `previously_examined`,
    `fwd_minus_mu_star`, `net_time_pct`, `fwd_pct_<coin>`.
  - Added labels: `family_candidate` (n >= 100 and finite p, p_vn), `sympos_ok`, `n_req_iid`,
    `n_req_burst4`, and `underpowered` (PREREG section 9: n < n_req_iid from the synthetic 5m control).
  - **Holm is NOT applied.**
- `top15_by_z.csv`, `top15_by_fwd_minus_mu.csv` (all cells) and `top15_by_fwd_minus_mu_family.csv`
  (n >= 100 only).
- `controls.csv`: the pre-registered `sweep_lib.controls` on the REAL IS 5m panel. It has 36 rows:
  3 H x 4 kinds x 3 n_target, with 200 reps each and B=600. Part a is iid and burst4 (seed 1); part b is
  voltimed and hourtimed (seed 2).
- `controls_signflip_realtiming_5m.csv`, `controls_canary_reversal_5m.csv` and `diag_ac1_is_5m.csv`:
  extra, descriptive controls.
- Intermediate files:
  - `out/signals_is_5m_sub*.npz`: signal caches for the Combine and exit stages. **Load BOTH files.**
  - `out/gate_is_5m_sub*.csv`
  - `out/timings_*`
  - `out/ctl_a|ctl_b/`
- `logs/report.txt` holds the full descriptive report.

## Results (5m, IS, 2021-08-01 .. 2024-06-30)

Constants per H (pooled over 7 coins; shifts n_min about 280.5k):

| H | cost_H | E\|r_H\| | mu* |
|---|---|---|---|
| 4 | 0.1404 % | 0.320 % | 0.1696 % |
| 16 | 0.1417 % | 0.633 % | 0.1993 % |
| 64 | 0.1467 % | 1.279 % | 0.2631 % |

**Headline: no 5m cell comes anywhere near the hurdle.**
- Of 105 family candidates, **0 have fwd >= mu\*** and **0 have fwd > cost_H**.
- 28 of 105 have fwd > 0. The median fwd is -0.0048 %.
- The best raw forward returns:

| H | best fwd | cell | hurdle mu* |
|---|---|---|---|
| 4 | 0.0070 % | N03_ADX_GC | 0.170 % |
| 16 | 0.0159 % | V45_AMB | 0.199 % |
| 64 | 0.0413 % | N17_KC_RSI | 0.263 % |

- The largest fwd/mu* ratio in the whole 5m table is 0.157.
- Under the pre-registered rule (condition 3, fwd >= mu*), **no 5m cell can survive the gate,
  whatever the Holm adjustment is**. The Combine agent's Holm step cannot change this for 5m.
- Statistical significance is weak as well:
  - The largest raw z is 2.82 (N20_EMA9_CHOP H4, p = 0.0024). The first Holm step at m about 666 needs
    z > 3.79.
  - Only 6 of 105 cells have raw p < 0.05. 23 have z < -1.645.
  - Mean z is -0.72. Many trend-type entries are significantly worse than random timing.

Top 15 cells by raw z. Flags: `[A]` approx port, `[P]` previously examined.

| # | cell | n | fwd % | net_time % | z | p | z_vn | fwd-mu* % | sym+ |
|---|---|---|---|---|---|---|---|---|---|
| 1 | N20_EMA9_CHOP H4 [A] (short-only) | 95,158 | 0.0043 | -0.136 | 2.82 | 0.0024 | -3.65 | -0.165 | 6/7 |
| 2 | N20_EMA9_CHOP H16 [A] | 95,158 | 0.0094 | -0.132 | 2.77 | 0.0028 | -1.28 | -0.190 | 7/7 |
| 3 | N17_KC_RSI H4 | 221,384 | 0.0053 | -0.135 | 1.91 | 0.028 | +25.24 | -0.164 | 4/7 |
| 4 | N17_KC_RSI H64 | 221,303 | 0.0413 | -0.105 | 1.74 | 0.041 | +9.92 | -0.222 | 5/7 |
| 5 | N25_DST_CCI H16 | 98,093 | 0.0091 | -0.133 | 1.70 | 0.044 | +2.00 | -0.190 | 6/7 |
| 6 | V39_ALL H16 | 66,845 | 0.0110 | -0.131 | 1.70 | 0.045 | -6.94 | -0.188 | 5/7 |
| 7 | S3_CMO_SANDWICH H16 [A] | 14,975 | 0.0142 | -0.128 | 1.60 | 0.055 | +1.72 | -0.185 | 6/7 |
| 8 | V45_AMB H4 [P] | 30,610 | 0.0058 | -0.135 | 1.54 | 0.062 | +7.44 | -0.164 | 5/7 |
| 9 | N17_KC_RSI H16 | 221,355 | 0.0139 | -0.128 | 1.52 | 0.064 | +17.43 | -0.185 | 4/7 |
| 10 | V45_AMB H16 [P] | 30,610 | 0.0159 | -0.126 | 1.50 | 0.066 | +4.92 | -0.183 | 6/7 |
| 11 | S3_CMO_SANDWICH H4 [A] | 14,975 | 0.0062 | -0.134 | 1.26 | 0.103 | +1.16 | -0.163 | 5/7 |
| 12 | N25_DST_CCI H64 | 98,071 | 0.0157 | -0.131 | 1.10 | 0.135 | -1.26 | -0.247 | 6/7 |
| 13 | V45_AMB H64 [P] | 30,604 | 0.0197 | -0.127 | 0.88 | 0.188 | +0.24 | -0.243 | 5/7 |
| 14 | OBV_S H4 | 25,300 | 0.0030 | -0.137 | 0.81 | 0.209 | -3.48 | -0.167 | 4/7 |
| 15 | OBV_B H64 | 66,927 | 0.0077 | -0.139 | 0.80 | 0.212 | +0.88 | -0.255 | 5/7 |

Top 15 by fwd - mu* (all cells):
- The top two are N14_ICHI_RSI H64 and H16, at +0.130 % and +0.120 %. Each has **n = 3**, is not in the
  family and means nothing.
- All the rest are H=4 cells, because mu* grows with H while fwd stays about 0. So fwd - mu* is about
  -mu*, and the ranking mostly reflects mu*:

| cell | fwd - mu* % |
|---|---|
| N03_ADX_GC H4 | -0.1625 |
| S3_CMO_SANDWICH H4 [A] | -0.1634 |
| N11_BREAKAWAY H4 [A] (n = 774) | -0.1636 |
| V45_AMB H4 [P] | -0.1637 |
| N17_KC_RSI H4 | -0.1643 |
| N20_EMA9_CHOP H4 [A] | -0.1653 |
| OBV_S H4 | -0.1666 |
| DOGE_L H4 [P] | -0.1673 |
| V39_ALL H4 | -0.1679 |
| N06_MACD_ORB H4 [A] | -0.1684 |
| S2_ST_ROC H4 | -0.1685 |
| N25_DST_CCI H4 | -0.1693 |
| N09_ALLIG_AROON H4 | -0.1704 |

- In the family-only list, positions 14 and 15 are N22_VORTEX_PSAR H4 (-0.1704) and N04_ST_KLINGER H4
  [A] (-0.1706).

Previously examined strategies at 5m IS: none comes close.
- V45_AMB: fwd 0.006 / 0.016 / 0.020 % at H 4 / 16 / 64; z 1.54 / 1.50 / 0.88.
- DOGE_L: fwd 0.002 / -0.026 / -0.030 %; z 0.18 / -2.14 / -1.13.
- DOGE_S: fwd -0.009 / -0.008 / -0.038 %; z -1.09 / -0.22 / -0.49.

Underpowered cells (PREREG section 9 label: n < n_req_iid from the synthetic 5m control, 281 / 737 / 1614
for H 4 / 16 / 64):
- S1_EMA_RSI_CHOP at every H (n = 256).
- N15_KC_AO at every H (n = 136).
- N11_BREAKAWAY H64 (n = 773).
- That is 7 of 105. Every other 5m cell has enough n to detect a 1.5 x mu* edge, so the 5m verdict is not a
  power problem.

## Controls on the real IS 5m panel

### (1) Pre-registered `controls()`: `controls.csv`

7,200 zero-edge replicates in total: 200 reps x 36 settings.

Zero-edge false positives:

| kind | raw null p<0.05 rate | raw z sd |
|---|---|---|
| iid | 0.025-0.080 | 0.97-1.05 |
| burst4 | 0.030-0.080 | 0.92-1.14 |
| hourtimed | 0.040-0.070 | 0.95-1.09 |
| **voltimed** | **0.165-0.220** | **1.75-2.31** |

- The voltimed raw null is worse on real 5m data than on the synthetic panel (synthetic z sd 1.52-1.98).
- The naive per-signal t on burst4 has a false-positive rate of 0.165-0.240. This confirms that overlap
  inflates the naive t.

Full raw gate (first Holm step at m = 666, fwd >= mu*, symbols rule, n >= 100):
- **36 of 7,200 false passes**: 35 voltimed and 1 burst4 (H16, n = 150).
- Raw p fell below 0.05/666 in 62 of 7,200 replicates.

Gate with A1 (`p_vn` also below the first Holm step): **0 of 7,200**.
- p_vn fell below 0.05/666 in 2 of 7,200 replicates. Both were burst4, and neither also passed the raw
  step, fwd >= mu* and the symbols rule.
- The vn z sd was 0.92-1.11 for all kinds.

Planted edge = 1.5 x mu* (power of the full gate with A1):
- iid, n = 2000: 1.00 / 1.00 / 0.995 at H = 4 / 16 / 64.
- iid, n = 500: 1.00 / 0.99 / 0.69.
- burst4, n = 2000: 1.00 / 0.985 / 0.69.

n needed so that MDE80 <= mu*, on the real panel:

| H | iid | burst4 |
|---|---|---|
| 4 | 216 | 580 |
| 16 | 588 | 2184 |
| 64 | 1315 | 5137 |

These are about 20 % below the synthetic figures, because the real E|r| is lower. The pre-registered
`underpowered` label still uses the synthetic n_req, as PREREG requires.

### (2) Sign-flip control with real strategy timing (extra, descriptive): `controls_signflip_realtiming_5m.csv`

Construction:
- Each strategy's actual 5m signal array is multiplied by a random ±1 per UTC day. The same multiplier
  applies to all 7 coins that day.
- This keeps the real timing, clustering, vol-timing and cross-coin alignment, while the expected edge is
  zero.
- 6 reps x 36 strategies x 3 H, with the same shifts. 630 cells have n >= 100.

Results:
- Raw z: mean -0.06, **sd 1.22**; P(p < 0.05) = 0.076.
- z_vn: mean 0.07, **sd 1.17**; P(p_vn < 0.05) = 0.097.
- 1 of 630 cells had raw p below 0.05/666: N18_VWMA_MACD H4, rep 0, z = 3.87 with z_vn 3.41. Its fwd was
  0.008 %, far below mu*.
- 0 of 630 had p_vn below 0.05/666.
- 0 passed the full raw rule, and 0 passed with A1.

Reading:
- With realistic strategy timing, the normal-approximation raw p is somewhat anti-conservative. A z sd of
  1.22 makes the one-sided tail at nominal z = 3.79 roughly P(N(0,1) > 3.11), about 9.4e-4. That is
  about 12x the nominal 7.5e-5.
- The vn test is also not perfectly calibrated here (sd 1.17).
- At 5m this does not matter, because the hurdle condition binds long before significance does. The
  Combine agent should keep it in mind for other TFs.
- Caveat: only 6 reps, and day-level sign flips can also carry real within-day predictability into the
  variance. So treat this as a harsh check, not an exact calibration.

### (3) Look-ahead canary, positive control: `controls_canary_reversal_5m.csv`

- CANARY_LOOKAHEAD (sign of close[t+1] - close[t]) run through the same gate gives:

| H | z | fwd | mu* |
|---|---|---|---|
| 4 | 324 | 0.156 % | 0.170 % |
| 16 | 178 | 0.156 % | 0.199 % |
| 64 | 90 | 0.154 % | 0.263 % |

- The gate sees a leaked edge immediately, so the positive control works.
- **Even a one-bar oracle does not clear mu\* at 5m.** Knowing the next 5m bar's direction is worth
  about 0.156 % per trade, and the realistic round trip plus hurdle is 0.17-0.26 %. This is the cost wall at
  5m in one number.

### (4) Why z_vn is extreme at 5m: bar-level mean reversion (descriptive)

- Lag-1 autocorrelation of 5m open-to-open log returns (IS, admissible bars) is negative on every coin:
  - BTC -0.046, XRP -0.042, SOL -0.036, ETH -0.029, DOGE -0.029, LTC -0.022, BCH -0.009.
  - Close-to-close gives -0.014 to -0.056.
- A 1-bar reversal benchmark (fade the bar that just closed; not in the registry or family) gives:
  - fwd = 0.0027 % at H4, i.e. 1.6 % of mu*.
  - raw z = 5.72.
  - **z_vn = +37.6**.
- The registry's z_vn values follow the same axis:
  - Trend or breakout entries, which enter in the direction of the last bar, are strongly negative:
    N23_HA_ST -35.0, N18 -25.7, S4 -25.7, S2 -18.3 at H4.
  - Fade or oversold entries are strongly positive: N17_KC_RSI +25.2, V45_AMB +7.4.
  - Raw fwd for all of them is within ±0.02 %.
- Over the 105 family cells, mean z_vn is -6.75 and its sd 8.25. This is a genuine property of 5m bars
  (bid/ask bounce and micro reversal in the aggregated spot feed), not a broken null. The sign-flip control
  shows z_vn sd of about 1.2 once the true edge is removed.
- Implication for A1 at 5m (and probably 15m):
  - `p_vn` screens out every trend-type entry.
  - It is almost automatically about 0 for fade-type entries.
  - So at these TFs it is not an independent "calibration" check. It is a direction-of-last-bar filter.
- This is harmless for decisions at 5m, where condition 3 (fwd >= mu*) fails everywhere. The Combine and
  Holdout agents should know it when reading p_vn at the faster TFs.

## Caveats

- The per-coin XRP data are thin in 2022-03..2023-07 (flagged by the data agent: 282 gaps in the 5m IS
  file) and were not masked, as protocol requires. BCH has 31 gaps. Positions are counted in bar indices
  across gaps (PREREG section 2).
- The normal-approximation p is used for decisions, as pre-registered. At 5m, `p_emp_all` (every admissible
  shift) agrees closely with `p` for the top cells: 0.0033 against 0.0024 for N20 H4.
- The top raw-z cell, N20_EMA9_CHOP, is an approximate spec-based port (short-only at 5m) with z_vn = -3.65.
  It is a negative-drift and vol-timed pattern, not a tradable edge (fwd 0.004 % against a 0.14 % cost).
- The sign-flip control has only 6 reps. The raw-null anti-conservatism it shows (sd about 1.2) is a
  real-data finding, but its size is uncertain (about ±0.05).
- The spot-proxy-for-perps limits and the fixed funding cost (PREREG section 10) apply unchanged.
