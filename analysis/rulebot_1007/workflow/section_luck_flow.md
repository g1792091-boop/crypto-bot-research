## Lens: luck, market backdrop, coin flips, signal flow and entry frequency

All scripts and outputs are in `scratchpad/lens/luck_flow/`. Every number below comes from those scripts, run with `python3 -I`, or from `rb_analyze/out_real`. R = net pnl / risk at the 2 ATR house stop. CF = coin flip. "Excess" = what the strategy's side choice added over a side flip at the same moment. "Timing" = R minus a random-time entry on the same side, timeframe and run.

### 1. Market backdrop: direction dominated everything

| run | days | equal-weight 6 coins | per coin | 15m random-time short / long (R) | 30m | 1h | 4h |
|---|---|---|---|---|---|---|---|
| v3a (approx, no live_bars) | 2.6 | -0.12% | BTC +0.32, ETH -0.82, SOL -1.12, BCH +0.68, LTC +0.94, DOGE -0.70 | n/a | n/a | n/a | n/a |
| v3b | 0.7 | -0.91% | 5 of 6 down (LTC +0.26) | -0.033 / -0.328 | +0.035 / -0.351 | +0.089 / -0.315 | +0.250 / +0.301 (n 14) |
| v4 | 1.5 | -2.59% | all 6 down: DOGE -4.07, LTC -3.63, ETH -3.21, BCH -2.18, BTC -1.51, SOL -0.92 | +0.199 / -0.593 | +0.223 / -0.475 | +0.305 / -0.443 | +0.619 / -0.469 |

Sources: `market_backdrop.csv`; random-time sides from the exhaustive CF (`backdrop_R.csv`, `luck.py`). In v4 the short-minus-long gap at 15m was 0.30R (SOL) to 1.25R (ETH), which is 4-6x the round-trip cost (0.17R at 15m).

Long share of SUBMITTED signals (`tilt_kind_tf.csv`). Core 36: v3a 0.51-0.53 (4h 0.71), v3b 0.51-0.63, v4 15m 0.39 / 30m 0.54 / 1h 0.51 / 4h 0.30. DeepSeek v4: 0.47-0.50 (4h 0.69). Coin flips at 15m: 0.43.

**Splitting the side-flip excess into tilt and timing** (`excess_split_kind_run_tf.csv`):

| kind / run / tf | pairs | long share | excess | drift-neutral | tilt part |
|---|---|---|---|---|---|
| core v4 15m | 752 | 0.34 | +0.089 | -0.084 | +0.172 |
| core v3b 15m | 335 | 0.54 | -0.178 | -0.158 | -0.020 |
| core v4 30m | 371 | 0.49 | -0.013 | -0.017 | +0.004 |
| core v4 4h | 26 | 0.35 | +0.133 | -0.086 | +0.218 |
| ds200 v4 15m | 1107 | 0.47 | +0.073 | +0.049 | +0.024 |
| ds200 v4 30m | 578 | 0.51 | -0.028 | -0.023 | -0.005 |

The best "direction skill" cells are one-sided strategies that were short in a falling market:

| cell | long share | side-flip excess (p) | timing vs random-time same side |
|---|---|---|---|
| N20_EMA9_CHOP 15m+30m (short-only by construction, 5y long 0.00) | 0.00 | +0.310 (0.015) | -0.002 [-0.29, +0.37] |
| N20_EMA9_CHOP 1h | 0.00 | +0.444 (0.005) | -0.013 [-0.28, +0.12] |
| N24_DMI 15m+30m (5y long 0.15-0.21) | 0.09 | +0.217 (0.048) | -0.124 [-0.40, +0.12] |
| F14_SMT 1h | 0.05 | +0.364 (0.036) | -0.136 [-0.30, +0.05] |

N20 lost -0.78R per trade (n 17) in the flat v3a. The pipeline flags 8 accounts for direction luck (`direction_luck.csv`), for example N22_VORTEX_PSAR@15m v3b (6/6 short), N24_DMI@15m and @30m v3b, N20@15m v3b, F4_FAN@30m v4 and N04@30m v4.

### 2. Coin flips: why 15m was +0.10R and the others negative

| baseline (v3b+v4 unless noted) | 15m | 30m | 1h | 4h |
|---|---|---|---|---|
| live coin-flip accounts, all runs (n; 4h-cluster CI) | +0.099 (50) [-0.21, +0.38] | -0.300 (24) [-0.50, -0.09] | -0.170 (12) | -0.521 (5) |
| exhaustive CF, every bar x coin x side, leverage-mixed (n) | -0.188 (4516) [-0.27, -0.09] | -0.133 (2219) [-0.17, -0.08] | -0.081 (1100) [-0.14, -0.02] | +0.098 (110); +0.034 incl. open trades |
| exhaustive CF cost R / gross R | 0.167 / -0.021 | 0.116 / -0.017 | 0.085 / +0.004 | 0.048 / +0.146 |
| side flip at the strategies' own moments (pairs) | -0.151 (2194) | -0.131 (1114) | -0.137 (667) | +0.017 (79) |
| strategies' chosen side, replay | -0.111 | -0.156 | -0.139 | -0.006 |
| strategies' live trades, all runs (n) | -0.19 (630) | -0.15 (378) | -0.07 (212) | +0.14 (31) |

Sources: `coinflip_accounts.csv`, `cf_exhaustive_summary.csv`, `cf_side_by_run.csv`, `summary.md`.

Why the 15m coin flips were +0.10:
- **Noise.** By run: v3a -0.16 (n 23), v3b +0.23 (n 10), v4 +0.37 (n 17). The two best trades are 80% of the summed R. A 50-trade block bootstrap from the exhaustive 15m CF has mean -0.16 and 95% band [-0.45, +0.17]; P(>= +0.099) = 0.059 (`cf_luck_band_15m.csv`).
- **Market.** v4 15m coin-flip shorts made +0.59 (n 10), longs +0.06 (n 7).
- **Not leverage or exits.** In the exhaustive replay, 40-50x vs 30x at 15m gives -0.217 vs -0.180 (v4) and -0.165 vs -0.193 (v3b). The coin-flip accounts' mean MFE of 0.99R is above the exhaustive 0.76R, which is a draw effect.
- **The other timeframes are the same noise in the other direction:** 30m -0.30 against -0.13 expected.
- The random accounts even "passed" the side-flip direction test at 15m (excess +0.273, p 0.0145), though their side is random by construction.

**The timeframe gradient is the cost gradient.** Gross R is about 0 at every timeframe. Strategy R minus CF is about 0 at every timeframe.

**Baseline for the AI verdict:**
1. Paired side flip on the trader's own entries: same moment, exits, leverage and cost.
2. Same-side random-time CF, enumerated in full (every bar x coin of that timeframe and days; 9,128 replays took 8 s). This removes the market-direction bet (owners' MY_REVIEW item 3).
3. The unconditional CF only as the cost floor.

A trader should pass both 1 and 2 under a day-block test. Do not use the 3 live coin-flip accounts per timeframe as the baseline.

### 3. Luck concentration, clustering and effective sample size

**Profit concentration.** 167 profitable non-random account-runs; 90 (54%) turn negative without their best trade. Accounts with 5-9 trades: core 34% (median best-trade share 0.87, best-day share 1.12); DeepSeek 50% (1.01, 1.61). Coin flips: 10/15 (67%), median best-trade share 1.0 (`luck_conc_summary.csv`). Account P&L carries no skill signal.

**Entries cluster on the same coin and minute** (`cluster_entries.csv`):

| run / kind | trades | share sharing coin+minute | share with >= 5 others | mean cluster |
|---|---|---|---|---|
| v3a core | 1465 | 0.47 | 0.07 | 1.95 |
| v3b core | 241 | 0.66 | 0.17 | 2.63 |
| v4 core | 382 | 0.78 | 0.30 | 3.95 |
| v4 ds200 | 563 | 0.85 | 0.36 | 4.38 |

The largest cluster was 17 accounts entering BTC in the same minute.

**Design effects** (`neff_kind_tf.csv`, `neff_replay_kind_tf.csv`):
- Pooled trade R: 1.2-2.7, depending on the cluster used (coin-minute, minute or 4h block).
- Every-signal replay: core 15m 1,087 signals give n_eff ≈ 94; DeepSeek 15m 1,107 give ≈ 128; core 30m 536 give ≈ 148.
- A naive iid 5% test then has a false-pass rate of 12% at deff 2.0 and 16% at deff 2.7.

**Verdict power** (`mde_verdict.csv`). Per-trade sd is 1.36R at 15m and 0.95R at 30m. Within-account day clustering rho = 0.14. Minimum detectable effect at 80% power for one trader (deff 1.57):

| timeframe | trades | MDE vs zero | MDE vs side flip |
|---|---|---|---|
| 15m | 150 | 0.35R | 0.29R |
| 15m | 30 | 0.78R | 0.65R |
| 30m | 150 | 0.24R | 0.22R |

Plausible edges are 0.1R or less, so a one-month verdict mostly certifies luck.

### 4. Signal flow (`flow.csv` per strategy x tf, `flow_kind_tf.csv`, `zero_trade_accounts.csv`)

| kind / tf | SUBMITTED per account-day (v3a / v3b / v4) | entered | skipped, in position | skipped, lower score | rejected for sizing |
|---|---|---|---|---|---|
| core 15m | 16.7 / 15.5 / 15.9 | 22% / 33% / 22% | 71 / 55 / 70% | 7 / 12 / 9% | 0 |
| core 30m | 7.8 / 8.0 / 8.1 | 28 / 44 / 28% | 65 / 38 / 61% | 8 / 17 / 11% | 0 |
| core 1h | 3.4 / 4.7 / 5.3 | 32 / 48 / 30% | 58 / 35 / 55% | 7 / 17 / 15% | 2.5% / 0 / 0 |
| core 4h | 1.06 / 0.68 / 1.18 | 22 / 24 / 38% | 35 / 0 / 19% | 7 / 29 / 25% | 35% / 47% / 19% |
| ds200 v4 15m / 30m / 1h / 4h | 17.7 / 9.4 / 5.6 / 2.1 | 24 / 31 / 31 / 23% | 65 / 55 / 44 / 28% | 11 / 14 / 25 / 32% | 0 / 0 / 0 / 17.5% |

Sizing rejections are all "stop too close to liquidation" and happen at 4h; v3a was at the old 50x tier walk.

Live rates match the five-year rates (`rate_vs_5y.csv`): over 124 cells the median live/5y ratio is 1.10 and the log-rate correlation is 0.89. DeepSeek ratios of 1.4-2.8 are a definition difference: its five-year counts are trades at one position per coin, not raw signals.

**Zero-trade accounts:**

| run / kind | total | no signal | all rejected by sizing | open at end | record only |
|---|---|---|---|---|---|
| v3a core | 48 | 35 | 8 (all 4h) | 5 | 0 |
| v3b core | 64 | 55 | 4 | 4 | 1 |
| v4 core | 43 | 35 | 3 | 4 | 1 |
| v4 ds200 | 30 | 20 | 3 | 7 | 0 |

Accounts at 4h are about half of all zero-trade accounts.

**Persistent no-trade strategies** are silent by design, not bugs:
- N21_ST_RSI_ADX: 0 signals in 5 years at any timeframe.
- N14_ICHI_RSI: 2-4 signals in 5 years per timeframe.
- N15_KC_AO: 0.05 signals/day at 15m in the 5-year data.
- S1_EMA_RSI_CHOP: 0.095/day at 15m.
- N11_BREAKAWAY: 0.35/day at 15m.

### 5. AI trader = one strategy x (15m+30m), one position (`ai_trader_15m30m.csv`)

A rule-following simulation on the replay (v3b+v4) gives these trades per day:

| | median | 10-90% | reaching >= 1 trade/day |
|---|---|---|---|
| core | 5.0 (32 active strategies) | 1.9-8.6 | 29 of 36 |
| DeepSeek | 4.7 | 1.3-6.7 | 41 of 44 |

The five-year-rate analytic estimate agrees (for example N04: 9.5 simulated vs 9.7 analytic). The median trader is in a position about half the time; for N23, S2, OBV_B, N25, N04, N22, N10 and F16_FIB618 it is 78-97% of the time.

Calls per trader per month (median core / DeepSeek):

| design | core | DeepSeek | 30 traders | $ / month at Sonnet 5.5 |
|---|---|---|---|---|
| event-driven wakes | 443 | 399 | ~12,600 | $200-380 |
| + 4h scans | 534 | 471 | ~15,000 | $240-450 |
| + check at every 15m close while holding | 2,024 | 2,233 | ~63,000 | $1,000-1,900 |

Cost per call: $0.016 (8k of 10k input cached) to $0.030 (uncached), at $2 / $10 per MTok. Only the event-driven design fits $500.

### 6. Grades of the AI units (strategy x 15m+30m; `grades_15m30m.csv`)

Grade rules:
- **B:** beats both the side flip and the same-side random-time CF by >= 0.10R, in every run and timeframe with >= 8 signals.
- **D:** loses to both by >= 0.10R everywhere.
- **X:** under 1 AI trade/day both live and at the five-year rate.
- **?:** fewer than 15 pairs or fewer than 10 independent 1h moments.

| grade | units |
|---|---|
| B (8; none significant, min BH q 0.32) | N13_3OUTSIDE (the only one positive in both v3b and v4); F12_MSS, F12_MSS_DISP, F16_FIB500, F1_MOM_DIV, F1_RSI_DIV, F7_RF_TRIPLE, F9_IFVG (v4 only) |
| D (4) | N12_ICHI_AO, N18_VWMA_MACD, OBV_S, F4_PULL |
| X (7) | N11, N14, N15, N21, S1, F15_OPEN0930, F5_BOX_RSI |
| C (40) | the rest of the units with enough data |
| ? (21) | units with too little data |

Notable C units:
- N20 and N24: their edge is market direction (section 1).
- N17_KC_RSI: good timing within its side (+0.39 vs random-time longs, CI [0.05, 0.85]) but long in a falling market. This is the only unit whose timing CI excludes 0, before correcting for the 80 tests.

**Implication.** Every AI seat chosen from this data is an in-sample choice. Seat at most the B list as "watch". Fill the remaining seats on frequency and five-year evidence. Count each duplicate group once. Build both coin-flip baselines and the long-share report into the verdict before 10/17.