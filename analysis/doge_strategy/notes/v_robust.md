# v_robust: adversarial verification of the t_robust results (strategy 5864)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/v_robust`

- I made no Astral calls.
- `/home/user/crypto-bot-research` is untouched (`git status` clean).
- Every run used a single process, and the total compute was under 2 minutes.

## What I did

| script | output | purpose |
|---|---|---|
| `indep.py` | – | Independent re-implementation of the strategy. It is written from the rule text plus the PORT agent's inferred conventions and does not import the port. Its EMA/Wilder recursions use lfilter, and it has its own CHOP, StochRSI, cross and simulator loop. |
| `v1_headline.py` | `out_v1.txt`, `v1_coins_trades.csv` | Friend window; DOGE 5y; 7 coins × 3 sides; pooled results. Trade lists are compared to the tester's CSVs. |
| `v2_lookahead.py` | `out_v2.txt` | Truncation test at 6 random cuts, a future-perturbation test (bars after the cut ×1.5), and a resample truncation test. |
| `v3_spot.py` | `out_v3.txt` | By-hand check of 20 random trades. Pure-Python scalar loops over the raw CSV rebuild every entry condition and the full trailing-stop walk. |
| `v4_slices.py` | `out_v4.txt` | The tester's code (port copy + `robust_lib`) on different slices: coins over the last 12 months and 2025-03..12 (re-seeded), DOGE by year and by thirds, other start dates, next-open fill, and cost variants. |
| `v5_sens.py` | `out_v5.txt` | Part 3 statistics recomputed from the CSVs; the cloud factor matrix regenerated from the seed; 14 sets re-run with `indep.py`; RSI26 binding check. |
| `v6_tf.py` | `out_v6.txt` | Part 2 with my own resampler and my own 5m walk (all 18 long cells). |
| `v7_1m.py` | `out_v7.txt` | F4: 5m stop models compared with my own 1m walk on 2026-05-13..09-28, the only window with 1m data. |
| `v8_misc.py` | `out_v8.txt` | Friend window per coin and side; OAT invariances; F5 R²; F6/F7 subgroups; F3 best-cost cells; 2021 concentration. |
| `v9_nextopen.py` | `out_v9.txt` | Why a next-open fill raises gross. |
| `v10_boot.py` | `out_v10.txt` | Day-block bootstrap and week-cluster t. |

## Reproduction results

**Friend window.** `indep.py` gives n 40, win rate 0.550, $PF 1.272255, average trade 0.03742%, total return +0.37296%. This equals Astral.

**DOGE 5y.** 2,214 of 2,214 trades are identical to the tester's (maximum |gross difference| 1e-16).

| metric | value |
|---|---|
| gross per trade | +0.01261% |
| t (naive / day-cluster) | 1.52 / 1.32 |
| PF | 1.0975 |
| net (real cost) | -0.12758% |
| compounded at 25% sizing | -50.7% |

| subset | n | gross per trade | day-cluster t |
|---|---|---|---|
| first half | 1,100 | +0.0280% | 1.84 |
| second half | 1,114 | -0.0026% | – |
| entries ≥ 2022-06-01 | 1,862 | +0.0103% | – |

**7 coins × 3 sides.** Every trade list is identical to the tester's (21 of 21 cells, all "both"). Every table number matches. The pooled results match too:

| side | gross per trade | day-cluster t |
|---|---|---|
| long | -0.0065% | -1.09 |
| short | -0.0125% | -2.15 |
| both | -0.0095% | -2.22 |

**Timeframes.** All 18 long cells of Part 2 match exactly on n, gross and day-cluster t, including the walk5 models.

**Sensitivity.**
- 14 of 14 re-runs match. The one flagged "DIFF" is a 0-trade window, which gives PF inf in my code and NaN in the tester's.
- The cloud factors equal `default_rng(20260929).uniform(0.8, 1.2, (300, 18))`, so the draws were not cherry-picked.

**Look-ahead.**
- Across 6 cuts: 0 indicator differences, 0 signal differences, and identical closed trades.
- Scaling every bar after the cut by 1.5 changes nothing up to the cut.
- Completed 1h bins are unchanged by truncation.

**By-hand check.** 20 of 20 trades match on entry conditions, exit bar, exit reason, stop level and gross.

**Inference.**
- DOGE 5y: day-bootstrap 95% CI for gross is [-0.0055, +0.0323]% per trade; week-cluster t is 1.37.
- 7 coins pooled, both sides: CI [-0.0175, -0.0015]%.

## Corrections and nuances found

1. **F2, shorts.** Pooled, adding shorts is worse, but it is not worse on every coin. Over the 18-month window:
   - Gross per trade rose when shorts were added on DOGE (-0.0029 → +0.0025) and ETH (-0.0076 → -0.0040).
   - Win rate rose on ETH (42.9 → 44.6%) and BCH (40.6 → 41.5%).
   - On DOGE over 5 years, the short side alone is +0.0057% (t_c 0.72) and both sides +0.0091% (t_c 1.47).
   - After costs, adding shorts is worse on every coin in total, because the trade count roughly doubles (DOGE compounded -21.3% → -39.3%).
2. **F4, stop model.**
   - The "t ≈ 4" false edges come from both 5m fill-at-stop orderings: O→H→L gives t 4.63 and O→L→H gives t 3.76.
   - Astral's fill-at-close model shows t 1.32 on the 5y history. That is not "apparently significant", although it is optimistic compared with 1m data.
   - The claim that this is an artifact rests on a single 4.5-month 1m window with 135 trades. My own 1m walk reproduces it: 5m O→H→L +0.0267%, O→L→H +0.0372%, Astral +0.0150%, versus 1m walks -0.0309% and 0.0000%.
3. **F6, the early edge.** The first half's +0.028% is concentrated in Aug–Dec 2021: 201 trades at +0.078% (t_c 1.90). This is the coarse-tick era right after the corrupted Jan–Jul 2021 data.
   - First half excluding 2021: +0.017% (t_c 1.04).
   - Backtest started at 2022-01-01: +0.0060% (t_c 0.63).
   - 95% of parameter sets have H2 < H1, so the decline is common to all sets (a change of regime).
   - Restricted to sets with ≥500 trades, the half-to-half Spearman is +0.061 (p 0.30). That is still null.
4. **F8, the stage-2/3 distance.** Moving the stage-2/3 distance does change the friend's window at +15% and +30%: win rate 52.5%, PF 1.2408, total +0.332%. Only the -15% and -30% moves leave it unchanged. The `tsl_wm2` no-op is confirmed. The RSI26 minimum among bars meeting every other entry condition is 44.93: 0 bars fall in (36.4, 44.2] and 886 in (44.2, 52].
5. **F1 and summary.** The real-cost range of the cells is -0.1331 to -0.1745%, not -0.136 to -0.175% (DOGE short is -0.1331%).
6. **F3.** 36 of the 42 cells are higher-timeframe cells; the other 6 are 5m. The max-t 0.88 best-cost cell is the 5m O→H→L cell, not a higher timeframe.
7. **F7.** The friend-window PF is not entirely uninformative about the 5y gross: Spearman is +0.32 (p 3e-8), and P(5y gross > 0) is 0.73 for sets with window PF > 1 versus 0.50 for the rest. Part of this comes by construction, because the window lies inside the 5y sample. The magnitude is tiny: the top 10% average +0.0051% versus +0.0043% for the rest. No set is net positive after costs.
8. **Not in the tester's report: next-open fill.** With a next-open fill, DOGE 5y gross rises to +0.0211% (t_c 2.25), still -0.119% net. Most of the gain is a feed microstructure effect: at the 2,214 signal bars, open[t+1] is below close[t] by -0.0085% on average (t -8.6). The rest comes from the coarse stop model on the fill bar: 54% of trades exit on the fill bar under the Astral stop model. This is not tradable edge.
9. **Cost robustness.**
   - With Binance BNB taker 0.045% plus 0.01% slippage and no funding (0.11% round trip), DOGE 5y is -0.097% per trade and every coin cell is between -0.103 and -0.145%.
   - The DOGE 5y break-even round-trip cost equals the gross, +0.0126%, which is below the maker-only round trip of 0.04%.
   - Pro-rata funding averages 0.0002% per trade and is negligible.
