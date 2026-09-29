# Adversarial verification of the "stats" audit (STAT-1 .. STAT-12)

Scratch: `verify_stats/` (`bt/` = copy of the project bt/; only change: `strategies.v45_signals` exposes extra
`X_*` keys for the intermediate states; the existing keys are unchanged, and the reproduction below matches to 4.4e-16).
Nothing under /home/user/crypto-bot-research was modified. No Astral tools were used.
I wrote all statistics code from scratch (`bt/vlib.py`) and did not import the auditor's `fstats`/`evstats`.
My circular-shift null shifts in bar-index space with a common k across symbols. The auditor shifts in minutes,
so agreement between the two is a real cross-check.

## Scripts and what they verify
| script | checks |
|---|---|
| `bt/v_sig5.py` | rebuilds the 5m V4.5 signals and parent states; reproduces `results/forward_ALL_5m_v45.csv` (9/9 rows, max diff 4.4e-16) |
| `bt/v_stats5.py 64 V45_EXACT_AMB` | naive t, day/week cluster t, non-overlap subsample, calendar-time NW, day bootstrap, iid null, shift null, calibration |
| `bt/v_parent.py` | per-symbol shift null, parent-state means, subset check, conditional null, delayed entry |
| `bt/v_incr.py` | day-bootstrap tests of each filter layer's increment |
| `bt/v_trend15.py` | 15m ST(14,6)+STC state on 15m bars, IS vs OOS, monthly, Welch test IS vs OOS months |
| `bt/v_sig15.py`, `bt/v_s5.py` | all 15m signals; S5 and peer strategies |
| `bt/v_mc.py 2000` | Westfall-Young family null (bar-index shift) for 15m (168 tests) and 5m (18 tests) |
| `bt/v_trades.py` | 364 combos from the repro trades: day/week-cluster t, VIF, sd, power, PF identity |
| `bt/v_ruleoc.py` | operating characteristic of the pass rule, including the low-n combos |
| `bt/v_calib_sim.py` | size of naive/day/week-cluster t on synthetic paths with the real V4.5 signal timings |

## Results

### STAT-1 (naive t with overlapping windows): CONFIRMED
- Per-symbol N 563/550/528; means 0.0902/0.1403/0.1781%; naive t 2.79/2.91/3.05. Pooled 1641, mean 0.1353%, median 0.1013%, naive t 4.98.
- Clustering: median gap 17/15/25 bars; 68/70/65% of gaps are <=64; 16-17% are consecutive; mean number of neighbours within 64 bars is 2.93/3.46/2.71.
  90-92% of signals have another symbol's signal within +-320 minutes.
- Pooled corrected statistics:
  - day-cluster t 2.30 (135 days); week-cluster t 2.38 (20 weeks)
  - non-overlap subsample N 626, mean 0.149%, day-cluster t 2.18
  - calendar-time NW t: lag 64 2.41, lag 288 2.21, lag 864 2.17
  - day bootstrap t 2.33, p2 0.018
- Shift null (mine, 2000 draws): z 1.68, p1 0.031. The naive t has null sd 2.66 and size 44% (auditor: 2.81 and 40.7%).
  The day-cluster t has null sd 1.24 and size 7.2%.
- Per symbol: day-cluster t 1.64/1.73/1.87; shift z 1.24/1.24/1.58, p1 0.095/0.096/0.054.
- Beta baseline +0.0009%. The iid null is too liberal (z 4.60).
- Caveat on magnitude: the handoff quoted only the per-symbol t 2.8-3.1, never the pooled 4.98. Against what was
  quoted, the overstatement is about 1.6-2.3x, not 3x.

### STAT-2 (multiplicity): CONFIRMED (the exact numbers depend on the implementation)
- 15m family, 168 tests: null max |naive t| median 6.04 (95th pct 12.26), observed 7.80; null max |z| median 2.70 (95th pct 3.68).
  - Raw p2<0.05 in 10/168 (auditor 7; 8.4 expected). Min BH q 0.42 (auditor 0.84).
  - The observed max is S5@8 with z 3.14 and FWER p 0.20 (auditor 2.83 and 0.38).
- 5m family, 18 tests: null max |z| median 1.55 (95th pct 2.62). V45_EXACT_AMB@64 has z 1.62 and FWER p 0.457 (auditor 0.365).
  - 5 of the 18 raw p<0.05, all positive. These are highly correlated tests of one underlying state.
  - Min BH q 0.18.
- Combined 186 tests: V4.5@64 FWER p 1.0. This framing is overly punitive because the 15m-IS tests are on different data.
  The relevant family is the 5m family.

### STAT-3 (drift belongs to the parent state): CONFIRMED (the wording is slightly loose)
- Every V45_EXACT_AMB bar is inside OPPCHOP (0 exceptions on all 6 symbol-side combinations).
- 64-bar means: F15RAW 0.0366% (day-boot t 0.90), F15 0.0867% (2.10), OPP 0.1119%, OPPCHOP 0.1168% (2.05), V45 0.1353% (2.29).
- Increments (day-bootstrap):
  - STC filter +0.050% (t 1.90)
  - OPPCHOP over F15 +0.030% (t 0.95)
  - V45 over OPPCHOP +0.018% (t 0.66)
  - V45 over F15 +0.049% (t 1.17)
- Conditional iid-subset null: z 0.54. Delaying entry by 0/1/3/6/12 bars gives 0.135/0.138/0.139/0.143/0.138%.
- Correction: the drift is essentially that of the 15m ST(14,6)+STC state. Plain 15m ST direction ("generic trend")
  is only +0.037% (t 0.9).

### STAT-4 (regime dependence): PARTIALLY CONFIRMED
- The numbers reproduce exactly:
  - IS: 5 symbols -0.0429% (N 77,583); BTC/ETH/SOL -0.0184%
  - OOS: 5 symbols +0.0937% (N 42,292); BTC/ETH/SOL +0.0755%
  - naive t -7.75 / +14.74
  - the monthly table is identical
- Significance:
  - IS 5 symbols: day-cluster t -1.22, shift z -0.99
  - IS BTC/ETH/SOL: day-cluster t -0.46, shift z -0.41, i.e. zero, not "lost money" (BTC IS +0.001%)
  - OOS 5 symbols: day-cluster t 2.31, shift z 1.93, p1 0.018
  - OOS BTC/ETH/SOL: day-cluster t 1.98, shift z 1.55, p1 0.041
- Monthly Welch test of OOS vs IS: 5 symbols t 2.21 (p 0.052); BTC/ETH/SOL t 1.50 (p 0.16).
- Correct statement: the mechanism shows no positive drift over the prior 9 months (zero for the V4.5 symbols) and a
  positive drift in the discovery window. Regime dependence is suggested, not established.

### STAT-5 (S5): CONFIRMED
- N 324; mean 0.1029%; median -0.0168%; hit 49.4%.
- naive t 1.12; day-cluster t 0.88; shift z 1.18 (p 0.12).
- Excluding the top 1 signal the mean is 0.062%; excluding the top 5 it is -0.003%. The largest outlier (LTC long 2025-11-07 +13.3%) is a real, volume-backed rally, not a bad print.
- Peers: S5@8 +0.179% (shift z 3.05-3.14, but the family max, FWER 0.2-0.38); N09@16 +0.083% (z 2.28); S6@32 +0.139% (z 2.48); N17@32 +0.137% (day-cluster t 1.63).

### STAT-6 (holdout contamination): CONFIRMED
- 5m: 0 of 40,000 bars before 2026-05-08 for BTC/ETH/SOL. 15m before/after split: BTC 26168/13832, ETH 26169/13831, SOL 26166/13834, LTC 26187/13813, BCH 26170/13830.
- summary_ALL_5m_v45g1 has 39 rows each for V45_EXACT_AMB, V45_ANY, V45_EXACT_AMB_G1 and V39_15M_G1.
- 277 days is 79,776 5m bars. MDE arithmetic checks: shift SE 0.0785%/1641 signals.
- Addition (missed by the auditor): the previous projects' paper/live audits also fall inside the 15m OOS window: the 31-strategy
  7-day audit 2026-08-26..09-02, the V4.5/V3.9/OBV RC2 7.72 days and the Sep 5-13 report. So the 15m OOS is sealed only for this code.

### STAT-7 (pass rule): CONFIRMED, WITH AN ADDITION
- P(pass | 0 edge, n=100) is 18-21% for the combos tested.
- At true mean +0.05%: S6 7%, N24 5%, N18 31%, V39 ladder 100%.
- Implied expectancy at PF=1.2: 0.029% (L50_sl15), 0.031% (L50_sl20), 0.118% (F_sl2.0_tp3.0).
- Addition: 52/364 combos (N03, N08, S5, V39_D16) have only 160-~450 trades. At their actual n, P(pass | 0 edge) is
  N03 13%, N08 9-11%, S5 7-14%. The auditor's "0-0.6% at actual n" holds only for the large-n combos.
  Under a global zero-edge null the rule would give about 5 false passes.

### STAT-8 (power): CONFIRMED
- sd quantiles 0.39/0.77/0.95/1.17/1.31%. n for +0.05% is 2,813 (IQR 1,836-4,307); for +0.10% it is 703.
- MDE 0.265% at n=100 and 0.092% at n=835. S6 in the OOS: about 441 trades, MDE 0.20%.
- Addition: with the measured day-cluster VIF of 1.57, the required n for +0.05% is about 4,400. The auditor's power numbers are about 1.6x optimistic.

### Minor findings
- STAT-9: confirmed. The best combo is S6 SL2/TP3 at -0.052% (day-cluster t -0.88). Its CI is selection-biased because it is the maximum of 364.
- STAT-10: confirmed.
  - V3.9 at 16 bars: shift z between -1.41 and +0.12; day-cluster t between -1.75 and +0.26.
  - The handoff's range "-0.035..-0.121%" leaves out S42 -0.009, S52 +0.003 and AC1 +0.011.
  - V45_ANY naive t is 5.54/3.74/6.98, pooled 9.39.
- STAT-11: confirmed. The identity mean = E|x|(PF-1)/(PF+1) holds with max error 1.9e-16. 0/364 combos have PF>=1 or exp>0. eq_L5<1 for all 364.
- STAT-12: partially confirmed. On synthetic paths with the real signal timings (iid / 1-day / 7-day block bootstrap of the real returns):
  - the day-cluster t has sd 1.07/1.09/1.11 and size 7.2/6.5/5.8%
  - the week-cluster t has sd 1.11-1.14
  - the naive t has sd 1.78-2.36 and size 27-44%

  So the estimator itself is only mildly oversized. The 1.24-1.32 inflation under the real-path shift null is specific
  to this path (the V-shaped trend regimes). An honest range for the pooled V4.5 evidence is z of about 1.7-2.1
  (one-sided p about 0.02-0.045, two-sided about 0.04-0.09), and it still fails multiplicity.

### The auditor's "confirmed OK" list
All items re-checked OK:
- forward_ALL_5m_v45.csv reproduces.
- The handoff numbers are correct.
- S5 324 / 0.103% is correct.
- V4.5 statistics: median 0.101%, winsorised 0.133%, positive in all 5 months, longs 0.187% and shorts 0.085%.
- Beta baseline 0.0009%.
- 5m to 15m aggregation under the open label matches 98.5-100% (close label 0.1-3%), so there is no look-ahead in the mapping.
- 0/364 and 0/39 pass, with 342/364 day-cluster t < -1.96. Maximum 5m PF 0.80, maximum exp -0.087%.
- No OOS file exists.
- VIF 1.57 is correct.

## Bottom line
The auditor's core conclusions hold under independent code. The V4.5 64-bar drift is weak evidence:
- single-test z of about 1.7-2.1
- per symbol not significant
- not significant after multiplicity within the 5m family (FWER 0.37-0.46)
- not attributable to the V4.5 trigger

The headline "0 pass" does not depend on the rule, because every combo has negative net expectancy.

Overstatements to correct:
- "~3x" applies only to the pooled t, which the handoff never quoted.
- "lost money in IS" is zero for BTC/ETH/SOL (t -0.46).
- "HAC 1.3-1.4x too small" is specific to this path; the estimator alone is about 1.1x.
- "0-0.6% at actual n" ignores the 52 low-n combos, which have 7-14% false-pass rates.
