# Verifier notes: test "exec" (execution realism and sizing), strategy 5864, DOGEUSD 5m

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/v_exec`

No Astral calls. Nothing under `/home/user/crypto-bot-research` was touched. At most one heavy process ran at a time.

## Independent reproduction

- `my_sim.py` is my own implementation, written from the spec with my own loops. It covers:
  - EMA seeded with the first value.
  - Wilder RSI with an SMA seed.
  - StochRSI K and D.
  - CHOP with ATR taken as the SMA of true range.
  - The signals.
  - Two exit models: `astral` and `prev`, each with `on_close` and `next_open` fills.
- Full history 2021-08-01..2026-09-29, 542,670 bars:
  - The long-entry signal bars are identical to the port's on every bar.
  - 14 exit-signal bars differ. All are exact K==D ties that break differently at 1e-12. No trade is affected.
- Ledger comparison (`cmp_ledgers.py`): trade-for-trade identical to the tester's ledgers.
  - Covers astral/on_close, prev/on_close, prev/next_open and astral/next_open: 2,214 trades each, identical entry and exit timestamps, max |Δgross| = 0.
  - My next_open MAE differs from theirs by up to 0.09%. My code leaves the next-open exit price out of MAE; theirs is more correct.
- Look-ahead (`trunc_test.py`):
  - 15 truncation points (8 entry bars, 7 random), from a 2025-06 start. The port's indicators and signals at t are identical whether computed on df[:t+1] or on the full data (max |Δ| = 0).
  - My causal loop implementation also reproduces all 2,214 entries.
  - Conclusion: no look-ahead.
- 20 trades checked by hand against raw 5m bars (`dump20.py`): 10 Astral-model and 10 resting-stop (prev) trades.
  - I recomputed the stop, watermark, stage and fill arithmetic for each one. All 20 agree.
  - Examples:
    - ASTRAL #170: wm 0.1759, fav 0.457%, stage 2, stop 0.1755498. Low 0.1750 triggers, fill at close 0.1754, +0.1713%.
    - PREV #635: stage-1 stop 0.08752226 hit, +0.1743%.
    - PREV #247: gap-open fill at 0.1555.
  - Several Astral wins come from a bar whose open equals its low, so the low printed first. Example: ASTRAL #1868, 2025-11-10 11:10. Astral still raises the stop with the high before checking the low.

## Headline numbers re-derived with my own code

| item | tester | verifier |
|---|---|---|
| ATR14 Wilder median % (full / entries) | 0.352 / 0.383 | 0.3522 / 0.3829 |
| 0.35% / ATR, 0.20% / ATR | 0.91 / 0.52 | 0.914 / 0.522 |
| next-bar range ≥ 0.35% | 50.5% | 50.54% |
| astral vs prev: \|Δ\| > 0.01% / > 0.10% / different exit bar / mean \|Δ\| | 74.5 / 34.1 / 49.8% / 0.117 | 74.48 / 34.10 / 49.77% / 0.1170 |
| full history astral / prev (on_close) mean gross | +0.0126 / -0.0000 | +0.01261 / -0.00003 |
| paired astral − prev (day-cluster t) | +0.0126 (2.4) | +0.0126 (2.42) |
| E (next_open + prev) | +0.0087 | +0.00868 |
| next open vs signal close at entries | -0.0085% | -0.0085% (median 0) |
| next_open − on_close, Astral exits / stop exits | +0.0085 (t 6.3) / +0.0087 (4.6) | +0.0085 (6.35) / +0.0087 (4.64) |
| 1m period on_close / next_open / lat1m (m1_prev) | -0.0062 / +0.0049 / -0.0057 | -0.0062 / +0.0049 / -0.0057 |
| last month (48 trades): astral − m1_prev | +0.0376 (t 0.84) | +0.0376 (t 0.84) |
| window (40 trades): astral − m1_prev | +0.0507 | +0.0507 (t 1.03) |
| 1m period (143 trades): astral − m1_prev | +0.0214 (t 1.19) | +0.0214 (t 1.19) |
| window, m1_prev win rate / PF / total at 25% sizing | 42.5% / 0.90 / -0.134% | 42.5% / 0.899 / -0.134% |
| MAD vs m1_prev, last month: prev / astral | 0.086 / 0.151 | 0.086 / 0.151 |
| random entries, 1m period (40,031): astral / prev − m1_prev | -0.0009 / 0.0000 | -0.0009 (t -0.97) / +0.0000 (t 0.03) |
| breakeven RT: A / E | 0.0124 / 0.0085 | 0.0124 / 0.0085 |
| net at 0.13%: A / E | -0.1176 [-0.136, -0.099] / -0.1215 | -0.1176 [-0.1363, -0.0989] / -0.1215 [-0.1378, -0.1052] |
| months positive at 0.13% (A / E) | 1 / 62 | 1 / 62, 1 / 62 |
| maker/maker 0.04%: A / E | -0.028 / -0.032 | -0.0276 [-0.0463, -0.0089] / -0.0315 [-0.0478, -0.0152] |
| 25%-sizing total at 0.13%: A / E | -47.9 / -49.0% | -47.9 / -49.0% |
| leverage, E full, 1x..50x | 0.510 / 0.0337 / 0.00108 / 9.4e-7 / 1.8e-16 | 0.5099 / 0.03373 / 0.001078 / 9.41e-7 / 1.84e-16 |
| first below 50% (E): 50x / 20x / 10x / 5x | 09-15-21 / 11-08-21 / 03-27-22 / 08-13-22 | identical |
| A0 zero cost, 50x | 0.789, 10 liquidations, DD -94.5% | 0.7893, 10 liquidations, -94.5% |
| window E, 1x..50x | -1.07 / -5.3 / -10.4 / -20.0 / -44.4% | -1.07 / -5.28 / -10.37 / -19.99 / -44.41% |
| window A0 50x / A 50x | +15.0% / -40.2% | +15.0% / -40.2% |
| fee drag per trade and equity multiple per year | 0.0325..1.625%; 0.87..0.00087 | same (430.2 trades/yr) |
| E MAE min | -0.377% | -0.3767% |
| port MAE ≤ -1.5% (ohl_stop / olh_stop / astral) vs to-fill | 10 / 10 / 10 vs 0 / 0 / 10 | 10 / 10 / 10 vs 0 / 0 / 10 |
| Sharpe inputs | 15 daily returns | JSON: daily_returns = 15, sharpe 2.6913. Lo iid SE = 4.96 |

## New checks (not in the tester's report)

1. **The Astral − resting-stop gap on strategy entries depends on the period** (`my_*` ledgers):

   | year | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
   |---|---|---|---|---|---|---|
   | Δ (t) | +0.013 (0.7) | **+0.047 (3.5)** | +0.011 (1.3) | +0.013 (0.9) | **-0.015 (-1.5)** | +0.009 (1.2) |

   - The full-history t of 2.4 comes mostly from 2022.
   - From 2023-03 the gap is +0.0037% (t 0.62). It is the same when the tester's own `exec_lib` is re-run with indicators restarted on 2023-03-01 (`rerun_slice.py`: 1,511 trades, astral +0.0018%, prev -0.0019%, Δ +0.0037%, t 0.62).
2. **Within the 1m period, the gap is positive in every month** (disjoint months, `my_1m.py`):

   | month | May | Jun | Jul | Aug | Sep |
   |---|---|---|---|---|---|
   | astral − m1_prev | +0.0086 | +0.0084 | +0.0087 | +0.0242 | +0.0356 |

   - The tester's three windows (4.5 months, last month, 40-trade window) are nested, so they are not independent evidence. The monthly split is.
3. **The 1m-vs-5m vendor revisions do not drive the result.**
   - Control: run Astral's rule on 5m bars rebuilt from the 1m file.
   - Results are identical to the 5m file for all three windows. In the 127 bars inside last-month trades, O/H/L/C match 100 / 98.4 / 100 / 96.9%.
4. **Random entries, full history, every 3rd bar** (a different slice from the tester's every 4th; n = 180,570; `my_random.py`). Δ vs prev per trade:

   | model | overall (t) | by year |
   |---|---|---|
   | astral | +0.0057 (9.4) | 2021 +0.012, 2022 +0.007, 2023 +0.006, 2024 +0.011, 2025 +0.001, 2026 -0.001 |
   | opt | +0.0269 (13.1) | +0.0016 (2023, t 0.8) up to +0.058 (2024) |
   | pess | +0.0243 (37.9) | +0.011..+0.037, every year t > 13 |

   - So Astral's close-fill rule does earn a small, statistically clear premium over resting stops on real 2021-24 data. It is about 0 only in 2025-26.
5. **Own zero-drift Monte Carlo** (`my_mc.py`: 5-s steps, 12 bars, σ_5m ∈ {0.15, 0.24, 0.35}%, 100-200k paths):

   | model | raw bias |
   |---|---|
   | astral | +0.0009 ± 0.0010 |
   | m1_astral | +0.0011 |
   | fill at the actual price | +0.0007 |
   | prev | +0.017 |
   | m1_prev | +0.019 |
   | opt | -0.033 |
   | pess | +0.032 |
   | m1_opt | -0.023 |

   - Discretisation overshoot of a fill-at-stop rule at 5-s steps is +0.019.
   - Net of overshoot: prev ≈ 0, opt ≈ -0.05, pess ≈ +0.013, m1_opt ≈ -0.04.
   - Astral ≈ 0 is robust, and theory requires it: the exit is decided at the bar close from that bar's H and L and fills at that close, which is a stopping time.
   - Opt's MC bias differs from the tester's (≈ -0.005) because it depends on the σ mix.
6. **Astral's TSL rule can be run by a bar-close bot.**
   - astral_nx, which fills at the next open, gives +0.0109% over the full history (tester) and +0.0249% in the last month (tester), against Astral's +0.0126 / +0.0227.
   - Config B (next-open entry with Astral's TSL) gives +0.0211% [+0.0027, +0.0395]. Config C gives +0.0195% (t 2.1).
   - So the "overstatement" is relative to a resting-stop implementation, not relative to anything a bot can do.
   - The best implementable gross is about 0.02% per trade, roughly 1/6 of a 0.12-0.14% round trip. Config B nets -0.109% per trade at 0.13%, with 2 of 62 months positive.
   - A bar-close bot carries the intrabar MAE seen in the 10 Astral 50x liquidations (-1.5% to -3.3%). For it, those liquidations are not an artefact.
7. **The 10 A-ledger liquidations** (entries 2021-10-28 to 2025-09-09) are all 1-bar crashes of -1.5% to -3.3%. The resting-stop ledger fills every one of them at exactly -0.35%, which assumes no stop slippage in a crash bar.
   - The 2021-11-08 07:50 bar has MAE -3.27% but closes at -0.27%. This looks like a bad consolidated-feed wick.
8. **XRP 5m 2022-06.., same rules** (tester's engine): 501 trades, astral -0.003%, prev -0.013%. No edge on another coin either.

## Files

- `my_sim.py`: independent indicators, signals and exits.
- `my_trades_{astral,prev}_{on_close,next_open}.csv`, `my_le.npy`, `my_lx.npy`
- `cmp_ledgers.py`: trade-for-trade comparison with the tester.
- `trunc_test.py`: look-ahead truncation test and signal equality.
- `dump20.py`: 20 trades for hand checking.
- `my_atr.py`: ATR and disagreement statistics.
- `my_1m.py`, `my_1mperiod_same_entries.csv`: 1m resting-stop truth, vendor-revision control and monthly split.
- `my_1m_random.py`: random entries vs the 1m truth.
- `my_lat.py`: fill timing on 1m (on_close / next_open / lat1m).
- `my_cost_lev.py`: fill timing, cost curve, leverage accounts.
- `my_random.py`, `my_random_every3.csv`: random-entry model bias by year.
- `my_mc.py`: zero-drift MC.
- `f9_check.py`: port MAE caveat.
- `rerun_slice.py`: tester's `exec_lib` re-run on DOGE from a 2023-03 start and on XRP.
- `exec_lib_tester.py`, `doge_strategy.py`: unmodified copies.
