# Verifier notes: test "history" (DOGE 5m long-only, 2021-08-01..2026-09-29)

Scratch dir: this folder. No Astral calls. Nothing under /home/user/crypto-bot-research was touched.
Data: ../data/dogeusd-5m-ohlcv.csv (sha256 6d87c817...bd, verified), sliced from 2021-08-01 (542,670 bars).

## Scripts (all run; outputs quoted below)
- indep_sim.py: independent re-implementation of the strategy. It shares no code with the port: its own EMA, Wilder RSI, StochRSI, SMA-ATR CHOP and state machine.
- run_indep.py: full-history run, then a trade-by-trade comparison with t_history/trades_full_astral.csv. Writes my_trades_full.csv.
- trunc_test.py: look-ahead test of the port. It truncates at 6 random cut points and also perturbs the future.
- spot20.py: 20 random trades rebuilt by hand from the raw bars, with entry conditions and the step-by-step stop.
- stats_indep.py: 3 cost scenarios with my own CR1 day-cluster CI and a day-block bootstrap, plus per-year figures, months, 12.5x leverage and liquidation, breakeven and winner survival.
- luck_indep.py: 16-day windows and 16-day Sharpe.
- null_indep.py (+ stats_helpers.py): my own per-bar outcomes, a month-matched random-entry null (2,000 reps), and the rule's excess over random with a day-cluster t.
- exec_variants.py, nextopen_null.py, nextopen_periods.py: stop-price fill, next-open fill, and a random-entry null under next-open.
- slice_rerun.py: the port re-run on fresh slices, with indicators re-seeded.
- tick_round.py: OHLC rounded to 5 decimals (DOGEUSDT perp tick).

## Results
- Independent sim vs tester: 2214/2214 trades, same entries and exits. Max |gross diff| is 1e-16. Mean +0.012614%, win 46.567%, PF 1.09745.
- Look-ahead: none. At all 6 cuts the indicator diff is 0, with 0 signal mismatches, and the trades closed before each cut are identical. Adding 1% noise to bars at or after T changes 0 signals before T.
- Spot-check: 20/20 trades match by hand. Examples: #63 2021-09-15 14:50 (4-decimal tick): wm 0.2430, fav 0.248% (<0.25), stop 0.242152, low 0.2420 touches, exit at close 0.2429 = +0.206%. #155: stop touched at fav 0.44%, exit at close = 0.000% (a stop fill would give +0.24%).
- Costs, full history (zero / realistic / best):
  - win: 46.57 / 32.52 / 43.41%
  - PF: 1.0975 / 0.4021 / 0.8190
  - mean %: +0.0126 [-0.0061, +0.0313] t 1.32 / -0.1276 [-0.1463, -0.1089] / -0.0274 [-0.0461, -0.0087]
  - day-block bootstrap for zero cost: [-0.0055, +0.0323], P(mean<=0) 0.084
  - compounded at 25%: +7.12 / -50.70 / -14.16%
  - max DD at 25% (closed): -2.72 / -50.98 / -16.43%
  - months positive: 29 / 1 / 16 of 62
- Per year, gross mean %:
  - 2021 +0.0779 (t 1.90), 2022 +0.0130, 2023 +0.0178, 2024 +0.0017, 2025 -0.0067, 2026 +0.0064
  - from 2022-06: +0.0103 (t 1.02); from 2024: -0.0002 (t -0.02)
  - Aug–Dec 2021 sum is +15.66 of +27.93. Aug 2021–May 2022 sum is only +8.71, because Jan–May 2022 was -6.95.
- Fresh-slice port re-runs, gross:
  - 2022-06..: 1861 trades, +0.0104%
  - 2023..: 1617 trades, +0.0044% (t 0.48)
  - 2024..: 1194 trades, +0.0003%
  - 2021-08..2023: 1012 trades, +0.0279% (t 1.74)
  - All entries are common with the full run.
- Tick rounding to 5 decimals: +0.0131% (t 1.37); from 2024 +0.0019%.
- Breakeven round trip: 0.0124%. Winners: 1031, of which 720 survive realistic and 961 survive best. Astral 40: 22 winners, 14 survive realistic (net win 35%), 18 survive best.
- 12.5x:
  - zero cost, no liquidation: final 2.652x, peak 14.25x, DD -89.31%
  - zero cost, with liquidation: 10 liquidations, final 0.7893x, peak 8.26x, DD -94.51%
  - realistic, with liquidation: below 50% on 2021-09-18, below 10% on 2021-11-08, below 1% on 2022-03-27
- 16-day windows (1,867):
  - zero-cost percentiles: p5 -0.518, p25 -0.204, p50 -0.033, p75 +0.213, p95 +0.952
  - target window +0.373% ranks at the 82.4th percentile
  - share positive: zero 45.3%, realistic 6.5%, best 27.5%
  - win rate >= 55% in 25.2% of windows; Sharpe (sqrt365) >= 2.69 in 27.96%; target Sharpe 2.61
  - target n = 40 is the 97th percentile of trade counts
  - Note: a return of +0.373% or more occurs in 17.6% of windows, not "about a quarter".
- Random-entry null (my own outcomes, 2,000 reps):
  - regime: z 1.74, p 0.040, null win 47.47%
  - uniform: z 1.54, p 0.060, null win 48.44%
  - 2022-06..: z 1.30 / 1.27; 2024..: z -0.11 / -0.17
  - Rule excess over the same-month regime population: +0.0133%/trade, but with a day-cluster SE t is 1.40 (weaker than the iid-null z).
- Execution variants (own code):
  - ohl_stop: +0.0495% (t 4.63); population of all bars +0.0264%, regime +0.0277%
  - next_open + Astral TSL: +0.0211% [+0.0027, +0.0396] (t 2.25)
  - Under next_open the rule beats random entries: z 2.51 regime, 2.38 uniform (p 0.006 / 0.015). About 0.006% of that is the close->next-open gap at entry bars: -0.0085% vs -0.0023% for all bars.
  - next_open by period: 2021-08..2022-05 +0.041% (t 1.46); 2022-06.. +0.017% (t 1.77); 2024.. +0.008% (t 0.70). Realistic net under next_open: -0.119%.
- Venue check (Binance DOGEUSDT perp from data.binance.vision) was blocked by the egress proxy (403), so it was not done.
