# Discover gate: 15m + 30m (IS only)

Agent: Discover, TF group [15m, 30m]. Written 2026-09-29. Every number here comes from code in this
directory. Outputs are in this directory and `out/`, logs are in `logs/`.

## Protocol integrity

- `sha256sum -c ../PREREG.sha256` gave all 11 files OK before the run (11:45 UTC) and after it
  (see the final check at the end of this file).
- PREREG.md sha256 = `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50`.
- The copies used here are byte-identical to the harness:
  - `sweep_lib.py` sha256 = `2b20c3c155f31bbe3b51cc3b7b96a8b8c01226d6cf573cb601077d89f98cd543`.
  - `run_gate_tf.py` = `8cec4d91...`, `run_controls.py` = `5451cb5e...`.
  - All 8 `vendor/*.py` files match `harness/vendor`.
- **No bug was fixed and no harness file was modified.** No pre-registered rule changed.
- Data read: only `sweep/data/is/` (15m and 30m, 7 coins), through `sweep_lib.load(split="is")`.
  - The last bar loaded is 2024-06-30 23:45 (15m) and 23:30 (30m). No bar at or after 2024-07-01 was read.
  - No OOS or FINAL file was opened.
  - `data/qa/*` was not read, because it may summarise post-IS bars.
- Gaps: BCH 15m has 3 gaps. There are none elsewhere, and 0 bars are misaligned. The XRP thin-feed
  window (2022-03..2023-07) was left in, as the data agent flagged and PREREG §1 requires.
- No Astral tool was called.

## What was run (OMP_NUM_THREADS=1, at most 2 processes at a time)

| step | command | wall time |
|---|---|---|
| gate 15m | `run_gate_tf.py --tf 15m --split is` | 268 s (signals 250 s, gate 17 s) |
| gate 30m | `run_gate_tf.py --tf 30m --split is` | 161 s (signals 143 s, gate 17 s) |
| controls, real IS 15m | `run_controls.py --tf 15m --split is --reps 200` | 346 s |
| controls, real IS 30m | `run_controls.py --tf 30m --split is --reps 200` | 211 s |
| extra: timing-preserving random-sign control | `run_strategy_timing_controls.py --tf {15m,30m} --reps 40` | 482 s + 381 s |
| extra: joint-tail check, 8 cells x 500 reps | `tail_check.py` | 217 s + 283 s |
| independent recomputation of 5 cells | `verify_cells.py` | < 1 min |
| diagnostic: momentum vs z_vn | `diag_vn.py` | < 1 min |

- Signal cost: 341 µs/bar at 15m and 392 µs/bar at 30m, for all 37 strategies.
- The slowest strategies at 15m / 30m:
  - N16_BBRSI: 99 s / 54 s
  - N05_PSAR_POC: 35 s / 19 s
  - V39_ALL: 34 s / 21 s
  - V45_AMB: 26 s / 16 s
- **No strategy failed to compute.** `compute_signals(strict=True)` raised nothing, and the logs contain no warnings.
- Structural zero or near-zero signal counts (these are not errors):
  - N21_ST_RSI_ADX: 0 signals at both TFs.
  - N14_ICHI_RSI: 2 (15m) and 5 (30m).
  - N15_KC_AO: 72 / 50.
  - S1_EMA_RSI_CHOP: 111 / 70.

## Outputs

- `gate_cells.csv`: 222 rows, one per cell (37 strategies x 2 TFs x H in {4, 16, 64}).
  - It keeps every harness column under its harness name, so Combine can pass it straight to
    `sweep_lib.apply_gate`. The raw harness tables `out/gate_is_15m.csv` and `out/gate_is_30m.csv`
    are also there.
  - Aliases requested by the task:
    - `fwd_pct`
    - `fwd_<coin>` and `fwd_pct_<coin>`
    - `n_<coin>`
    - `p_one_sided` (= `p`)
    - `E_abs_rH`
    - `previously_examined`
    - `fwd_minus_mu_star`
  - Added labels:
    - `family_candidate`: n >= 100 and finite p and p_vn.
    - `underpowered`: n < n_req_iid(tf, H), from `harness/out/controls_n_required.csv` per PREREG §9.
    - `p_lt_alpha_over_666` and `p_vn_lt_alpha_over_666`: indicative only.
  - **Holm is NOT applied.** The Combine agent does that over all 6 TFs.
- `out/signals_is_15m.npz` and `out/signals_is_30m.npz`: cached signals for the Combine exit stage.
- `controls.csv`: `sweep_lib.controls()` on the REAL IS panel (`data=is`, 200 reps, seed 1), plus
  the harness agent's synthetic-panel rows for 15m/30m (`data=synthetic`) for comparison.
  - Summaries: `controls_summary.csv` and `controls_n_required_real_is.csv`.
- `controls_strategy_timing.csv` and `controls_strategy_timing_summary.csv`: the extra
  timing-preserving control. It is descriptive and never used for a decision.
- `out/tail_check_{summary,reps}_{15m,30m}.csv`: joint-tail check, descriptive.
- Tables:
  - `top15_by_z_n100.csv`
  - `top15_by_fwd_minus_mu_n100.csv`
  - `top15_by_*_all.csv`
  - `top15.txt`
  - `gate_summary_by_tf_H.csv`
  - `strategy_tf_summary.csv`
- Diagnostics: `out/diag_vn_momentum.csv` and `out/diag_autocorr_is.csv`.

## Results

### Headline: no 15m or 30m cell can survive the gate, whatever Holm does

- The family candidates are 201 cells: 102 at 15m (34 strategies x 3 H) and 99 at 30m (33 x 3).
- **None has fwd >= mu\*.** Rule 4.4(3) fails in all 201 cells, so `gate_pass` and
  `gate_pass_spec` are FALSE for every 15m/30m cell, regardless of the family size m.
- The closest cell is N03_ADX_GC 30m H4: n=337, fwd 0.104 % against mu\* 0.213 %, so
  fwd − mu\* = −0.109 pct-points. It is labelled underpowered.
- Only 1 of the 201 cells has a positive gross forward return after cost (`net_time > 0`):
  - V45_AMB 30m H64 (previously examined): fwd 0.289 % against cost_H 0.180 %, so net +0.109 %.
  - It is still 0.19 pct-points below mu\* (0.478 %).
  - Raw z = 1.64 (p = 0.050), p_vn = 0.16, p_emp_all = 0.049.
- 81 of the 201 cells have gross fwd > 0 (40 %). This is no better than chance before costs.
- Raw p:
  - The smallest is 0.0094 (N17_KC_RSI 15m H4, z = 2.35).
  - The Holm first step at m <= 666 needs p < 7.5e-5 (z > 3.79). **0 cells** reach it.
  - Only 5 of the 201 cells have p < 0.05. That is 2.5 %, fewer than the 5 % expected under the null.
- Because nothing survives, **no exit stage is needed for 15m/30m.**

Gate summary (family candidates; percentages are per signal):

| tf | H | cells n>=100 | mu\* | E\|r_H\| | cost_H | fwd>=mu\* | net_time>0 | fwd>0 | p<0.05 | p_vn<0.05 | max z |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 15m | 4 | 34 | 0.191 % | 0.552 % | 0.141 % | 0 | 0 | 15 | 1 | 3 | 2.35 |
| 15m | 16 | 34 | 0.246 % | 1.106 % | 0.145 % | 0 | 0 | 16 | 1 | 4 | 1.86 |
| 15m | 64 | 34 | 0.367 % | 2.278 % | 0.160 % | 0 | 0 | 12 | 2 | 1 | 2.05 |
| 30m | 4 | 33 | 0.213 % | 0.777 % | 0.143 % | 0 | 0 | 9 | 0 | 3 | 1.44 |
| 30m | 16 | 33 | 0.294 % | 1.578 % | 0.150 % | 0 | 0 | 12 | 0 | 3 | 1.59 |
| 30m | 64 | 33 | 0.478 % | 3.279 % | 0.180 % | 0 | 1 | 17 | 1 | 1 | 1.68 |

Across the 201 candidates, cells with p_vn < 7.5e-5: 8. Cells with both p and p_vn below it: 0.

### Top 15 by z (n >= 100)

Full columns are in `top15_by_z_n100.csv`. "pe" = previously examined.

| strategy | tf | H | n | fwd % | mu\* % | fwd−mu\* | z | p | z_vn | p_vn | sym+ | flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N17_KC_RSI | 15m | 4 | 81718 | 0.0197 | 0.191 | −0.172 | 2.35 | 0.0094 | 15.03 | 2e-51 | 6/7 | |
| N13_3OUTSIDE | 15m | 64 | 5109 | 0.109 | 0.367 | −0.259 | 2.05 | 0.020 | 0.40 | 0.35 | 6/7 | approx |
| S3_CMO_SANDWICH | 15m | 16 | 5277 | 0.046 | 0.246 | −0.200 | 1.86 | 0.032 | 2.19 | 0.014 | 5/7 | approx |
| N20_EMA9_CHOP | 15m | 64 | 31255 | 0.019 | 0.367 | −0.348 | 1.73 | 0.042 | 1.55 | 0.061 | 4/7 | approx |
| N05_PSAR_POC | 30m | 64 | 2748 | 0.170 | 0.478 | −0.308 | 1.68 | 0.047 | 1.00 | 0.16 | 5/7 | approx |
| V45_AMB | 30m | 64 | 4291 | 0.289 | 0.478 | −0.190 | 1.64 | 0.050 | 1.00 | 0.16 | 6/7 | pe |
| V45_AMB | 30m | 16 | 4295 | 0.102 | 0.294 | −0.192 | 1.59 | 0.056 | 3.78 | 7.7e-5 | 6/7 | pe |
| N20_EMA9_CHOP | 30m | 64 | 14707 | 0.040 | 0.478 | −0.439 | 1.56 | 0.059 | 1.30 | 0.097 | 4/7 | approx |
| N25_DST_CCI | 30m | 64 | 15622 | 0.140 | 0.478 | −0.339 | 1.53 | 0.063 | −0.19 | 0.58 | 6/7 | |
| N08_ICHI_WR | 30m | 4 | 587 | 0.084 | 0.213 | −0.129 | 1.44 | 0.075 | 1.72 | 0.043 | 6/7 | underpowered |
| N17_KC_RSI | 15m | 16 | 81701 | 0.039 | 0.246 | −0.207 | 1.37 | 0.085 | 7.57 | 2e-14 | 6/7 | |
| N03_ADX_GC | 30m | 4 | 337 | 0.104 | 0.213 | −0.109 | 1.37 | 0.085 | −1.94 | 0.97 | 4/7 | underpowered |
| S3_CMO_SANDWICH | 30m | 16 | 2687 | 0.067 | 0.294 | −0.226 | 1.33 | 0.091 | 2.07 | 0.019 | 6/7 | approx |
| N01_ST_EMA | 30m | 64 | 10421 | 0.131 | 0.478 | −0.347 | 1.24 | 0.108 | −2.37 | 0.99 | 5/7 | |
| N22_VORTEX_PSAR | 15m | 4 | 51620 | 0.006 | 0.191 | −0.185 | 1.23 | 0.109 | −8.91 | 1.0 | 4/7 | |

### Top 15 by fwd − mu\* (n >= 100)

Every value is negative. The list is dominated by H=4, where the hurdle is smallest.

1. N03_ADX_GC 30m H4: −0.109 (n=337, underpowered)
2. N08_ICHI_WR 30m H4: −0.129 (n=587, underpowered)
3. N03_ADX_GC 30m H16: −0.156 (n=337, underpowered)
4. N03_ADX_GC 15m H4: −0.162
5. N17_KC_RSI 15m H4: −0.172
6. N13_3OUTSIDE 15m H4: −0.178 (approx)
7. N09_ALLIG_AROON 15m H4: −0.183
8. DOGE_S 15m H4: −0.184 (pe)
9. V45_AMB 15m H4: −0.184 (pe)
10. N12_ICHI_AO 15m H4: −0.184
11. N07_ICHI_CMO 15m H4: −0.184
12. N10_HA_PSAR 15m H4: −0.185
13. N22_VORTEX_PSAR 15m H4: −0.185
14. N06_MACD_ORB 30m H4: −0.185 (approx)
15. N18_VWMA_MACD 15m H4: −0.188

Values are in pct-points; see `top15_by_fwd_minus_mu_n100.csv`. Most of these cells have fwd close
to 0, so fwd − mu\* ≈ −mu\*.

Outside the family (n < 100), the only cells with fwd >= mu\* are N14_ICHI_RSI 15m H64 (n=2) and
30m H4 (n=5). They are noise and not eligible.

S1_EMA_RSI_CHOP 30m (n=70, approx) shows fwd −1.3 % to −2.1 % with z = −8. It is outside the family.
The tail check below shows that the raw z of this sparse strategy is heavy-tailed, so that z
means little.

### Power

- The real-IS n_req (iid, MDE80 <= mu\*) is slightly below the synthetic values the harness used:

  | TF | H=4 | H=16 | H=64 |
  |---|---|---|---|
  | 15m | 494 | 1144 | 1976 |
  | 30m | 776 | 1538 | 2294 |

  The synthetic values are 593, 1293, 2069, 878, 1700 and 2346 in the same order. So the PREREG
  label errs slightly toward calling cells underpowered.
- For burst4 (clustered) signals, n_req is 1336 / 4143 / 7723 at 15m and 2105 / 5726 / 9020 at 30m.
- Per-cell MDE80 from each cell's own null sd, at m = 666 (`controls_strategy_timing.csv`):
  - The median MDE80/mu\* is 0.27 / 0.46 / 0.64 at 15m and 0.46 / 0.71 / 0.96 at 30m, for
    H = 4 / 16 / 64.
  - 163 of the 201 cells could detect an edge smaller than the hurdle with 80 % power.
- **So at 15m/30m, "no survivor" is mostly an informative negative, not only a power statement.**
  For most dense strategies, an edge of hurdle size would have been seen. The exceptions are the
  sparse strategies, which are underpowered: N03, N08, N11, S1, N15 and S5.

## Controls

### A. `sweep_lib.controls()` on the real IS panel (`controls.csv`)

Setup: 200 reps for each H x kind x n_target, with random zero-edge signals on real returns.

**Zero-edge calibration, raw null**
- iid, burst4 and hourtimed: p<0.05 rate 0.046-0.054; z sd 0.87-1.11.
- voltimed:
  - p<0.05 rate 0.155 (15m) and 0.132 (30m).
  - z sd 1.39-1.78 (15m) and 1.25-1.73 (30m).
  - **The raw null is anti-conservative on real data too**, as the harness found on synthetic data.

**A1 (vn) null**
- p<0.05 rate 0.043-0.057.
- z sd 0.85-1.09 for every kind.

**Full gate at the first Holm step (m = 666)**
- The raw rule false-passed 9 of 7,200 (15m) and 10 of 7,200 (30m) zero-edge replicates, all voltimed.
  The largest rate was 3.0 %, at 30m H4 voltimed n=150.
- **With A1: 0 of 14,400.**

**Planted edge of 1.5 x mu\* (gate including A1)**

| TF, H | iid n=500 | burst4 n=2000 |
|---|---|---|
| 15m H4 | 0.995 | 1.000 |
| 15m H16 | 0.82 | 0.84 |
| 15m H64 | 0.435 | 0.43 |
| 30m H4 | 0.975 | 0.99 |
| 30m H16 | 0.57 | 0.63 |
| 30m H64 | 0.295 | 0.27 |

- The harness synthetic rows for 15m/30m, included for comparison, agree: 13 raw false passes and
  0 with A1.

### B. Extra, descriptive: timing-preserving random-sign control on the real strategies

Design:
- Each strategy's real signal timing and clustering is kept.
- The direction is replaced by a random sign per "episode": a run of same-sign signals whose
  consecutive signal bars are <= H bars apart.
- 40 reps per family cell: 201 cells, 8,040 reps.

Results:
- Median z sd is 0.99-1.04 (raw) and 0.97-1.04 (vn).
- The mean p<0.05 rate is 0.051-0.068 (raw) and 0.052-0.064 (vn).
- So the common-shift null is roughly calibrated for the real timing of dense strategies.

Exceptions: sparse breakout/event strategies have an inflated raw z sd.
- S1_EMA_RSI_CHOP: 1.64-1.77
- N11_BREAKAWAY: 1.37-1.46
- N03_ADX_GC 30m H4: 1.41
- S6_EMA_DMI_ADX: 1.36-1.40
- In these cells the vn z sd stays at 0.93-1.37.
- Raw z maxima under zero edge reached 4.84 (S1 15m H16) and 4.83 (N11 15m H4), above the Holm
  first step.

### C. Extra, descriptive: joint-tail check

Setup: 8 cells x 500 reps (`out/tail_check_*`), with zero-edge signals on real timing.

- The verbatim rule (`gate_pass_spec`: z > 3.79, fwd >= mu\*, symbols, n) **false-passed 14 of
  4,000**:

  | cell | false passes | raw z sd |
  |---|---|---|
  | S1_EMA_RSI_CHOP 15m H4 | 8/500 | 1.83 |
  | S1_EMA_RSI_CHOP 15m H16 | 4/500 | 1.56 |
  | N11_BREAKAWAY 15m H4 | 1/500 | 1.30 |
  | N03_ADX_GC 30m H4 | 1/500 | 1.58 |

- In sparse cells, fwd >= mu\* held by chance in 10-15 % of zero-edge reps. So the hurdle gives
  sparse cells almost no protection.
- **With A1: 0 of 4,000.** No replicate had both z and z_vn above 3.79. The correlation of z and
  z_vn across reps is 0.59-0.80.
- The single N18_VWMA_MACD 30m H16 outlier from B (raw 4.43, vn 4.31 in 40 reps) did not recur
  in 500 reps: z sd 1.02, max 2.51.
- **This is real-data evidence that supports amendment A1.** Without it, sparse vol-timed
  strategies (these exist at every TF, and they dominate at 4h/1d) can produce spurious raw-rule
  survivors.

## Observations for the Combine and Holdout agents (descriptive; no rule is affected)

1. **z_vn is very dispersed across real strategies**, while raw z is not:
   - At 15m H4, the z_vn sd is 6.5 and it ranges from −22.5 to +15.0. The raw z sd is 1.33.
   - This is not a broken null; control B shows vn is calibrated under zero directional
     information.
   - It is a real, small, very consistent **short-horizon reversal**:
     - The IS lag-1 autocorrelation of open-to-open returns is −0.004 to −0.043 (lag 2: down to −0.037).
     - The Spearman correlation of the signal's "momentum-ness" (mean d·sign(close_t − close_{t−H}))
       with z_vn is −0.47 to −0.76.
     - Momentum-following entries have strongly negative z_vn (N23_HA_ST −22.5, S4_BB_BBP −16.0,
       N18_VWMA_MACD −15.4).
     - The one clearly anti-momentum entry, N17_KC_RSI, has z_vn +15.0.
   - The bounded vn statistic removes fat tails, so it measures this tiny effect very precisely.
     Its size in returns is far below cost: N17 has fwd 0.020 % against mu\* 0.191 %.
   - **Caution: p_vn does not test expected return.** N17_KC_RSI 30m H16 has negative raw fwd
     (−0.045 %) and still p_vn = 1.9e-6. A1 is valid only as an ADDITIONAL filter, as
     pre-registered.
   - Part of the reversal may be an artefact of the aggregated multi-venue feed (bounce). It may be
     weaker on Binance perps.
   - Expect larger |z_vn| at 5m.
2. **Cross-TF consistency is weak.** For the same strategy and H, the Spearman correlation of z
   between 15m and 30m is 0.37 over 99 cells.
3. **V45_AMB and DOGE_L/S are previously examined** (flag set).
   - V45_AMB 30m H64 is the only positive net-of-cost cell in this group.
   - DOGE_L is negative at both TFs: fwd −0.030 % (15m H4) and −0.035 % (30m H4).
   - DOGE_S is close to 0.
4. The 12 approx ports are flagged `approx=True`, 72 rows. None is near the hurdle.

## Caveats

- The IS window includes the XRP thin-feed period (2022-03..2023-07) and 492 suspect single-bar
  spikes, which are unclipped. Per-coin fwd is reported, but nothing is masked. This follows the
  data agent's decision and PREREG §1.
- Controls B and C, and the momentum diagnostic, are extras by this agent. They are descriptive,
  are not in PREREG, and are never used for a decision. Their seeds (7 and 99) are independent
  of the pre-registered gate seeds.
- The `p_lt_alpha_over_666` columns are indicative only. Holm over the full 6-TF family is the
  Combine agent's job.
- The gate `n` counts overlapping signals. The exit stage (one position per coin) was not run,
  because there are no candidates.

## Final integrity check

See the end of the agent report: `sha256sum -c PREREG.sha256` was run after all steps.

Result at 2026-09-29T12:12:42 UTC, after all runs:
- `cd sweep && sha256sum -c PREREG.sha256`: all 11 files OK.
  - PREREG.md = `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50`
  - sweep_lib.py = `2b20c3c155f31bbe3b51cc3b7b96a8b8c01226d6cf573cb601077d89f98cd543`
  - Both equal the values before the run.
- The local copies (sweep_lib.py, run_gate_tf.py, run_controls.py, vendor/) are still byte-identical.
- `/home/user/crypto-bot-research` shows `git status` clean (0 lines).
