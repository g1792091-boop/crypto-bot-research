## Lens: our 36 strategies at 15m and 30m (the AI entry timeframes)

**Bottom line.** None of the 72 cells (36 strategies x 15m/30m) shows a positive edge that survives multiple testing, and the live results agree with the 5-year backtest. The 15m/30m signals have about zero gross directional edge, so each trade loses roughly its cost: about 0.23R at 15m and 0.16R at 30m. No cell earns tier A. Four 30m cells are B, all with confidence intervals that include zero, and two of those four are short-only or short-heavy strategies that benefited from the falling market. Only two cells come out as "least bad" bases for an AI test: **N10_HA_PSAR (30m, plus 15m)** and **S4_BB_BBP (15m/30m)**. Both are experiments, not verified non-losers.

### How the cards were built
- **Every signal per cell.**
  - v3a: entered trades (real R) plus the nightly skipped shadows. Shadow ROE was converted to R as ROE / (leverage x stop_frac), with the leverage and stop taken from the repo's own `PaperEngine` on a fresh $5,000 tier-walk account.
  - The conversion was checked on 1,398 base rows: leverage matched the recorded fresh-account leverage in 100% of rows. On the 1,339 rows that equal real trades, the median difference between converted and actual R is 4e-16.
  - v3b and v4: the pipeline replay of every SUBMITTED signal, status TRADED. UNRESOLVED signals are marked to the last close only as a sensitivity.
- **Uncertainty.** Bootstrap over time clusters (run x 4h block), resampled within each run, B = 10,000, with fixed seeds. 1h blocks are reported for reference. BH correction is applied over the cells tested.
- **Other columns.**
  - Side-flip excess comes from the pipeline. A drift-adjusted version subtracts the run x tf x side mean of the other strategies' flips.
  - Account statistics, the coin-flip bootstrap, 5-year net return per notional (with t and IS/CF), and signals per day live vs 5-year.
  - Cost share, MFE/MAE, and a fixed-leverage replay.
- **Tier rules (fixed before reading results).**
  - A: n>=30, mean>0, CI lower bound >0, positive in every run with n>=5 (at least 2 runs), side-flip excess >0, and the 5-year result not negative.
  - D: n>=20, mean<0, 5-year negative (t<-2), and either negative in every run with n>=5 or CI upper bound <0.
  - B: n>=20, mean>0, positive in most runs.
  - C: everything else.

### Pooled 36 strategies (every signal, house exits)
| tf | run | n | mean R | 95% CI (4h clusters) | win % | net per notional | 5-year net per notional |
|---|---|---|---|---|---|---|---|
| 15m | v3a (50x tier walk) | 1,388 | -0.322 | -0.478..-0.174 | 53.0 | -0.151% | -0.142% |
| 15m | v3b | 350 | -0.365 | -0.446..-0.290 (5 clusters) | 48.0 | -0.236% | |
| 15m | v4 | 785 | -0.025 | -0.335..+0.363 | 55.4 | -0.038% | |
| 15m | all | 2,523 | **-0.235** | **-0.370..-0.081** | 53.0 | -0.127% | |
| 30m | v3a | 555 | -0.256 | -0.368..-0.149 | 57.8 | -0.227% | -0.149% |
| 30m | v3b | 176 | -0.232 | -0.285..-0.157 (5 clusters) | 58.5 | -0.223% | |
| 30m | v4 | 384 | -0.118 | -0.300..+0.105 | 59.6 | -0.085% | |
| 30m | all | 1,115 | **-0.205** | **-0.291..-0.111** | 58.6 | -0.177% | |

- **Later runs (v3b+v4) before costs.** Gross R before fees and slippage is +0.102R at 15m (CI -0.115..+0.393) and +0.008R at 30m (CI -0.117..+0.165). Fees+funding take 0.165R / 0.116R and slippage 0.066R / 0.046R.
- **The 5-year result is negative almost everywhere.** It is below zero in 69 of the 70 cells with signals (t<-2 in 65; IS and CF both negative in 67). The median 5-year gross per notional is -0.002%.
- **The live signal code reproduces the backtest.** Live vs 5-year signals per day: Spearman 0.979, ratio 0.95.

### Tiers
| tf | A | B | C | D |
|---|---|---|---|---|
| 15m | 0 | 0 | 23 | 13 |
| 30m | 0 | 4 (N10_HA_PSAR, S4_BB_BBP, N20_EMA9_CHOP, N24_DMI) | 23 | 9 |

- **BH-significantly negative (q<0.05), 13 cells:** DOGE@30m, N25_DST_CCI@15m, N04_ST_KLINGER@30m, N18_VWMA_MACD@30m, OBV_B@15m, N04_ST_KLINGER@15m, N20_EMA9_CHOP@15m, N12_ICHI_AO@30m, N17_KC_RSI@30m, N24_DMI@15m, N17_KC_RSI@15m, S2_ST_ROC@30m, V39_ALL@30m.
- **BH-significantly positive:** 0 of 52 tested.
- **Never fired live** (and at most about 0.1/day in 5 years): N14_ICHI_RSI, N15_KC_AO, N21_ST_RSI_ADX, S1_EMA_RSI_CHOP, at both timeframes.
- **Under about 1 signal/day:** N03_ADX_GC, N08_ICHI_WR, N11_BREAKAWAY, S5_DONCHIAN_MFI.

### Candidates (best evidence first)
| cell | every signal n / mean R [CI] | v3a / v3b / v4 | vs same-side peers | account n / mean R / PF / worst DD | side-flip | 5-year net per notional (t) | signals/day |
|---|---|---|---|---|---|---|---|
| N10_HA_PSAR@30m (B) | 49 / +0.088 [-0.09,+0.25] | +(25) +(13) -(11) | +0.29 [0.11,0.44], q 0.005 | 16 / +0.15 / 2.07 / 16% | -0.00 | -0.132% (-19.3) | 12.5 |
| N10_HA_PSAR@15m (C) | 109 / -0.04 [-0.25,+0.17] | -(65) +(15) +(29) | +0.20 [0.01,0.38] | 33 / -0.01 / 0.98 / 39% | +0.07 | -0.143% (-40.4) | 24.7 |
| S4_BB_BBP@15m (C) | 95 / +0.03 [-0.42,+0.62]; later +0.42 | -(56) -(5) +(34) | +0.14 | 22 / +0.23 / 1.87 / 15% | +0.39 (p 0.10) | -0.152% (-38.7) | 20.6 |
| S4_BB_BBP@30m (B) | 42 / +0.11 [-0.18,+0.41]; later -0.04 | +(29) -(2) +(11) | +0.20 | 14 / -0.08 / 0.73 / 18% | +0.03 | -0.139% (-18.8) | 9.8 |
| N13_3OUTSIDE@15m (C) | 23 / +0.12 [-0.22,+0.45] | -(13) +(8) +(2) | +0.39 [0.07,0.72] | 14 / +0.47 / 7.05 / 7% | +0.47 (p 0.09) | -0.141% (-19.7) | 6.2 |
| N20_EMA9_CHOP@30m (B, short-only) | 56 / +0.09 [-0.27,+0.46] | -(14) +(6) +(36) | +0.12 | 13 / -0.01 / 1.14 / 18% | +0.36 (p 0.02); drift-adjusted +0.06 | -0.156% (-25.8) | 13.5 |
| N24_DMI@30m (B, 89% short) | 44 / +0.01 [-0.29,+0.25] | -(11) +(12) +(21) | +0.03 | 19 / +0.10 / 1.26 / 18% | +0.29 (p 0.03); drift-adjusted +0.015 | -0.141% (-21.4) | 11.6 |

### Results do not carry over between runs
- **Absolute results.** Every-signal mean R in v3a vs v3b+v4 (33 cells): Spearman -0.13 (p 0.47). All 4 cells that were positive in v3a were negative later. No cell is positive in all three runs; 11 are negative in all three.
- **Relative results.** The same-side-relative measure does not carry over either (Spearman -0.07 to +0.13).
- **Account P&L vs every signal.** Spearman 0.72 across cells, but they are not interchangeable. For example, S2_ST_ROC@15m has an account result of +0.17R (n 39) and an every-signal result of -0.20R (n 236).
- **Sample needed.** Days of every-signal data needed for a +-0.1R interval: about 11-14 for the most active cells (N04_ST_KLINGER@15m, N10_HA_PSAR@30m), 30-60 for typical cells, and more than 100 for S4_BB_BBP@15m.

### Leverage under the house ROE ladder (fixed-leverage replay, v3b+v4, 1,891 signals)
| tf | 10x | 20x | 30x | 40x | 50x |
|---|---|---|---|---|---|
| 15m: R change vs the live rule (paired, n) | +0.162 (1,036) | +0.061 (1,085) | +0.018 (1,130) | -0.087 (926) | -0.404 (176) |
| 15m: share of signals that can be sized | 100% | 100% | 100% | 78% | 14% |
| 30m: R change vs the live rule | +0.019 | +0.061 | +0.005 | -0.001 | n/a |
| 30m: share of signals that can be sized | 100% | 100% | 99% | 33% | 0% |

50x is rejected because the loss at the stop exceeds 15% of equity, because the stop sits too close to liquidation, or (BCH/LTC) because of the inferred brackets.

### What this means for the AI-trader plan
1. **Do not expect any of the 36 at 15m/30m to supply an edge.** Each needs about +0.23R (15m) or +0.16R (30m) of value added by the AI just to break even. Treat any 15m/30m AI trader on these strategies as an experiment that must beat its own rule account on the same signals.
2. **If one or two such traders are funded,** use N10_HA_PSAR (30m entries, 15m secondary) and S4_BB_BBP (15m, to test AI exit management). Keep N13_3OUTSIDE@15m as a rule account to reconsider in November.
3. **Prefer 30m over 15m.** The cost share is 0.16R vs 0.23R, and win rates are similar.
4. **Make exits independent of leverage.** Define the coded exits in price, ATR or R units. With the current ROE ladder, raising leverage with confidence lowers R; and 50x at margin = leverage % can almost never be sized with a 2 ATR stop.
5. **Treat short-biased winners as regime bets.** N20_EMA9_CHOP and N24_DMI only look good because the market fell. Use them only with an explicit regime rule.
6. **Base the November promotion on every-signal replay with time-cluster CIs and criteria fixed in advance,** not on account P&L or leaderboard rank, which do not carry over between runs.
7. **Drop these from AI consideration:** the never-firing and under-1/day cells, and the BH-negative cells listed above.

Files: `cards_15_30.csv` (72 rows x 187 columns), `cards_15_30_per_run.csv`, `pooled_15_30.csv`, `levreplay_summary.csv`, `summary_stats.txt`, and the scripts `v3a_every_signal.py`, `cards.py`, `levreplay.py`, `summary_stats.py`, `gross_ci.py`, all in `scratchpad/lens/ours_15_30/`.