# Long-history performance of Astral strategy 5864 (DOGEUSD 5m, long only)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/t_history`.
Nothing under `/home/user/crypto-bot-research` was modified (`git status` is clean). No Astral calls were made; everything is local.

## 0. Bottom line

- Over 5.16 years (2021-08-03 to 2026-09-29, 2,214 trades, 1.18 per day), the strategy exactly as designed earns +0.0126% per trade before costs. The day-cluster 95% CI is -0.0061% to +0.0313% (t 1.32). Since the 2022-06 tick-safe start it is +0.0103% (t 1.02). From 2024 to 2026 it is essentially zero: +0.0017%, -0.0067% and +0.0064% per year.
- With realistic Binance taker costs it loses -0.128% per trade (CI -0.146% to -0.109%), and 1 of 62 months is positive. At 25% sizing it compounds to -50.7%.
- Even the best case (maker 0.02% on both sides, no slippage, no funding) loses -0.027% per trade (CI -0.046% to -0.009%). The CI excludes zero.
- The breakeven round-trip cost is 0.012% (CI -0.006% to +0.031%). That is about one eleventh of a realistic 0.14% round trip and below even a 0.04% maker/maker round trip.
- The 2026-09-13..28 Astral window (+0.373%, 55% win rate, 40 trades) is the 82nd percentile of 1,867 sliding 16-day windows at zero cost.
  - 45% of windows are positive at zero cost and 6.5% at realistic cost.
  - 25% of windows have a win rate of 55% or more.
  - 28% have an Astral-style Sharpe of 2.69 or more.
- Random entries with the same exit logic and the same number of entries per month have the same win rate or a higher one (47.5-48.5% vs 46.6%).
  - The real rule's mean excess over random entries is about +0.013% per trade: z 1.6-1.8, one-sided p 0.04-0.06 on the full history.
  - On the tick-safe period that falls to z 1.2-1.3 (p 0.09-0.11), and from 2024 it is z -0.1 (p 0.54).
  - Where the excess exists it is roughly one tenth of the cost.
- At 12.5x notional (25% margin x 50x):
  - Realistic costs ruin the account: equity falls below 50% by 2021-09-18 and below 1% by 2022-03.
  - Even at zero cost, the 10 liquidations (MAE of -1.5% or worse) turn a 2.65x final multiple into 0.79x, with a -94.5% maximum drawdown.

## 1. Data and set-up

- Data: `../data/dogeusd-5m-ohlcv.csv` (sha256 6d87c817...344bd, verified), sliced from the data agent's clean_from date of **2021-08-01**. That leaves 542,670 bars, ending 2026-09-29 09:15.
  - Indicators are computed from 2021-08-01, so the 660-bar warmup puts the first tradable bar at 2021-08-03 07:00.
  - The tick-safe subset (entries from 2022-06-01) is reported separately.
- Engine: an unmodified copy of the port, `doge_strategy.py`, with Astral conventions: `fill='on_close'`, `tsl_eval='astral'` (watermark from the high first, trigger on the low, fill at the bar close), and suppression of same-bar re-entry after a trailing-stop exit.
- Port checks (`check_repro.py`):
  - On this long file, the port reproduces the saved-window result exactly: 40 trades, PF 1.272255111704368, total 0.3729606%.
  - It also reproduces Astral run 4a: 135 trades, mean +0.014971%, identical entry timestamps.
  - The full-history run contains **exactly the same 40 trades** in 09-13..09-28 as Astral: same entries and exits, return differences of 0 (`out_luck.txt`). The longer indicator history does not change the window, because the seed has decayed.
  - **No port bug was found.** The module is byte-identical to `../port/doge_strategy.py`.
- Every signal after warmup is taken: 2,214 raw entry signals and 2,214 trades.

Cost models (`hist_lib.py: COSTS`), all additive per trade:

| scenario | per-trade cost |
|---|---|
| zero | 0 (Astral-equivalent) |
| realistic | fee 0.05% per side + slippage 0.02% per market fill (0.14% per round trip) + funding 0.01%/8h pro-rata. Event-based funding (charged at the 00/08/16 UTC stamps) gives the same mean, 0.00019% per trade. |
| best | maker 0.02% on both sides, no slippage, no funding (0.04% per round trip). This is a lower bound: trailing-stop exits are stop-market (taker) orders in reality. |

## 2. Main table, 2021-08-03 → 2026-09-29

n = 2,214 trades, 1.176 trades per day, 819 trade-days (clusters), 62 calendar months, every month with trades. Source: `out_analyze.txt` and `summary_costs.csv`.

| metric | zero cost | realistic | best-case |
|---|---|---|---|
| win rate | 46.57% | 32.52% | 43.41% |
| avg win / avg loss (payoff) | +0.305% / -0.250% (1.22) | +0.264% / -0.316% (0.83) | +0.286% / -0.267% (1.07) |
| profit factor (per-trade %) | 1.097 | 0.402 | 0.819 |
| mean gross %/trade [day-cluster 95% CI] | +0.0126 [-0.0061, +0.0313], t 1.32 | same | same |
| mean net %/trade [day-cluster 95% CI] | +0.0126 [-0.0061, +0.0313] | **-0.1276 [-0.1463, -0.1089]**, t -13.4 | **-0.0274 [-0.0461, -0.0087]**, t -2.87 |
| sum of per-trade net % (1x notional, simple sum) | +27.9 | -282.5 | -60.6 |
| compounded, 25% of equity per trade | **+7.12%** (about 1.3% a year) | **-50.70%** | -14.16% |
| max DD at 25% sizing (closed / incl. intratrade MAE) | -2.72% / -2.75% | -50.98% / -50.98% | -16.43% / -16.44% |
| months positive | 29/62 = 46.8% | **1/62 = 1.6%** | 16/62 = 25.8% |
| worst / best month (simple sum) | -4.44% / +8.37% | -11.41% / +2.06% | -5.76% / +6.57% |
| 12.5x notional, no liquidation: final equity multiple / max DD | 2.65x (peak 14.3x) / -89.3% | 2.6e-17 / -100% | 4.0e-5 / -99.998% |
| 12.5x notional with 50x liquidation: final / max DD | **0.789x** (peak 8.26x) / -94.5% | 8.5e-18 / -100% | 1.2e-5 / -99.999% |
| liquidations at 50x (MAE ≤ -1.5% up to the exit fill) | 10 (0.45%) | 10 | 10 |

Tick-safe subset, entries from 2022-06-01 (n = 1,862):

| metric | value |
|---|---|
| mean gross | +0.0103% [-0.0095, +0.0301], t 1.02 |
| mean net, realistic | -0.1299% [-0.1497, -0.1100] |
| mean net, best-case | -0.0297% [-0.0495, -0.0099] |
| months positive | 44.2% zero cost, 1.9% realistic, 23.1% best-case |
| compounded at 25% | +4.83% zero cost, -45.42% realistic |

Leverage timing (`out_extras.txt`):
- Realistic at 12.5x: equity falls below 50% on 2021-09-18, below 10% on 2021-11-08 (with liquidation) or 2022-01-13 (without), and below 1% on 2022-03-27/28.
- Zero cost with liquidation: equity first falls below 50% on 2026-04-26.
- Best-case: equity falls below 1% on 2024-04-28 (with liquidation) or 2024-07-17 (without).

The 10 liquidations are listed in `liquidations_50x.csv`: 2021-10-28, 2021-11-08, 2023-10-26, 2024-03-01, 2024-03-08 (x2), 2024-11-10, 2024-11-12, 2025-05-09 and 2025-09-09. All are trailing-stop exits after 1 bar, with MAE between -1.51% and -3.27%.
- In 2 of them the recorded gross loss is under half the MAE: 2021-11-08 (MAE -3.27%, gross -0.27%) and 2024-11-10 (MAE -1.70%, gross -0.75%). That is Astral's fill-at-close.
- None falls on the known bad bars. Clipping the 3 bad lows (2021-10-21 11:30/11:35, 2026-05-17 23:40) leaves every result unchanged to 1e-15.

## 3. Per year (net % sums are simple sums at 1x notional; `per_year.csv`)

| year | n | trades/day | mean gross % [95% CI], t | win (zero) | sum zero | sum realistic | sum best | compounded 25%, realistic |
|---|---|---|---|---|---|---|---|---|
| 2021 (08-03..) | 201 | 1.33 | +0.0779 [-0.004, +0.160], 1.90 | 53.2% | +15.66 | -12.51 | +7.62 | -3.09% |
| 2022 | 395 | 1.08 | +0.0130 [-0.049, +0.075], 0.41 | 40.8% | +5.15 | -50.22 | -10.65 | -11.83% |
| 2023 | 416 | 1.14 | +0.0178 [-0.012, +0.048], 1.18 | 47.1% | +7.41 | -50.92 | -9.23 | -11.97% |
| 2024 | 454 | 1.24 | +0.0017 [-0.039, +0.042], 0.08 | 48.9% | +0.76 | -62.87 | -17.40 | -14.57% |
| 2025 | 444 | 1.22 | -0.0067 [-0.040, +0.027], -0.40 | 47.5% | -2.99 | -65.23 | -20.75 | -15.06% |
| 2026 (..09-29) | 304 | 1.12 | +0.0064 [-0.035, +0.048], 0.31 | 44.1% | +1.94 | -40.69 | -10.23 | -9.68% |

- Most of the zero-cost profit comes from Aug–Dec 2021: +15.7 of +27.9. That is the coarse-tick period (4-decimal prices), which the data agent flags for trailing-stop work.
- Per-month table: `per_month.csv`, 62 months.

## 4. Where the profit comes from

- Exits: 1,907 trailing-stop exits (86%) and 307 signal exits.
- Holding time: median 1 bar, mean 1.82 bars. 59.3% of trades are held exactly one 5m bar.
- Mean gross by exit type:

  | exit type | trades | mean gross |
  |---|---|---|
  | stage-1 stop (0.35% distance) | 848 | -0.242% |
  | stage-2 stop | 470 | +0.096% |
  | stage-3 stop | 589 | +0.373% |
  | signal exit | 306 | -0.103% |

- Gross percentiles: p25 -0.215%, p50 -0.023%, p75 +0.205%. 32.8% of trades have |gross| < 0.14%, the round-trip cost.

## 5. Luck check: sliding 16-day windows (`luck.py`, `windows16d.csv`, `out_luck.txt`)

There are 1,867 windows, one starting each day at 00:00 UTC from 2021-08-04 to 2026-09-13. A window's return compounds 25% of equity over the trades entered inside it.

| percentile | 1 | 5 | 10 | 25 | 50 | 75 | 90 | 95 | 99 |
|---|---|---|---|---|---|---|---|---|---|
| zero cost, 16-day total % | -0.856 | -0.518 | -0.394 | -0.204 | **-0.033** | +0.213 | +0.544 | +0.952 | +1.714 |
| realistic % | -1.842 | -1.443 | -1.178 | -0.902 | -0.578 | -0.318 | -0.083 | +0.096 | +0.934 |
| best % | -1.109 | -0.728 | -0.600 | -0.384 | -0.181 | +0.027 | +0.317 | +0.611 | +1.491 |

Where the 2026-09-13..28 window falls:
- Zero cost: +0.3730%, the **82.4th percentile**. From 2022-06 on it is the 83.9th percentile.
- Realistic cost: the same window is -1.024%, the 16.6th percentile.
- Best-case: -0.028%, the 70.2nd percentile.
- Its 40 trades are the 97th percentile of trade counts (median window: 17).
- Its 55% win rate is the 74.8th percentile. **25.2% of all 16-day windows have a win rate of 55% or more.**
- Its mean of +0.0374% per trade is the 71.9th percentile.

Share of 16-day windows with a positive return:

| window set | zero cost | realistic | best-case |
|---|---|---|---|
| all 1,867 (overlapping) | 45.3% | 6.5% | 27.5% |
| 117 non-overlapping | 47.0% | 5.1% | 23.9% |
| from 2022-06 | 44.3% | 5.2% | — |

Astral-style Sharpe (daily returns of 25%-sized equity, annualised with √365.2425):
- Zero cost:
  - Full history: 0.58.
  - Median 16-day window: -0.66.
  - **Windows with Sharpe ≥ 2.69: 28.0%.**
  - Target window by my daily calculation: 2.61 (Astral reports 2.69 from 15 daily returns starting 09-13 07:00).
- Realistic cost:
  - Full history: -5.48.
  - Target window: -17.1.

## 6. Null check: random entries with the same exit logic (`outcomes.py`, `null_random.py`, `null_shift.py`, `null_subset.py`)

Method:
- `outcomes.py` precomputes, for **every** bar, the outcome of a long entered at that bar's close with the strategy's exit logic: Astral trailing stop with stages, plus the EMA63<EMA156 or CROSS_BELOW(K,D) signal exit.
- Check: for the 2,214 real entry bars, the precomputed gross, hold and MAE equal the simulator's trades (maximum difference 1e-16, holds identical). The same holds for the `ohl_stop` variant.
- Each replication draws the same number of entries per calendar month as the real strategy, without replacement, from the eligible bars. There are 5,000 replications per variant.
- Random trades may overlap in time; that does not change their per-trade outcomes.

Eligible-bar variants:
- A: regime bars (EMA63>EMA156 and close>EMA600).
- B: uniform over all bars.
- C: all entry filters except the K/D cross trigger.
- D: circular shift of the whole real entry set by a random offset of at least 7 days. This keeps the real clustering of trades.

Full history, Astral trailing-stop model, zero cost. The real rule's mean gross is +0.0126%, its win rate 46.57% and its PF 1.0975.

| null | null mean gross (sd) | real z | one-sided p (null ≥ real) | null win rate | real win-rate z |
|---|---|---|---|---|---|
| A regime (208,975 bars; population mean -0.0015%) | -0.0007% (0.0079) | 1.69 | 0.045 | 47.49% | -0.87 (p 0.81) |
| B uniform (542,009 bars; population mean -0.0002%) | +0.0012% (0.0073) | 1.56 | 0.059 | 48.45% | -1.75 (p 0.96) |
| C all filters except cross (15,815 bars) | -0.0007% (0.0073) | 1.81 | 0.036 | 46.60% | -0.03 (p 0.52) |
| D circular shift (clustering kept) | -0.0001% (0.0072) | 1.78 | 0.039 | — | — |

The same test on sub-periods (`out_null_subset.txt`):

| entries | n | real mean gross | z vs regime null (p) | z vs uniform null (p) |
|---|---|---|---|---|
| 2021-08..2022-05 | 352 | +0.0247% | 1.06 (p 0.15) | 1.10 (p 0.14) |
| 2022-06..2026-09 (tick-safe) | 1,862 | +0.0103% | 1.34 (p 0.093) | 1.21 (p 0.114) |
| 2024-01..2026-09 | 1,202 | -0.0002% | -0.11 (p 0.54) | -0.16 (p 0.57) |

Real minus regime-bar population, by year: 2021 +0.076%, 2022 +0.017%, 2023 +0.023%, 2024 -0.001%, 2025 -0.006%, 2026 +0.010%.

How to read this:
- The entry rule does **not** raise the win rate above random entries. The 46-48% win rate is set by the exit mechanics.
- It may add about +0.013% per trade in mean return. That is marginal (p 0.04-0.06, uncorrected for how the strategy was selected), comes mostly from 2021-2023, is gone from 2024, and is about one tenth of the 0.14% round-trip cost.
- A fifth variant, snapping circularly shifted entries onto the next regime bar, is biased because many entries pile onto the first bar of each regime. It appears in `out_null_shift.txt` but is not used.

## 7. Execution-model sensitivity (`sensitivity.py`, `sensitivity_exec.csv`), zero cost

Mean gross with day-cluster CI, full history:

| fill | trailing-stop model | mean gross % [CI] | t | from 2022-06 | realistic net |
|---|---|---|---|---|---|
| on_close | **astral** | +0.0126 [-0.006, +0.031] | 1.32 | +0.0103 | -0.127 |
| on_close | ohl_stop (fill at stop, 5m O→H→L) | +0.0495 [+0.029, +0.070] | 4.63 | +0.0393 | -0.091 |
| on_close | olh_stop | +0.0360 [+0.017, +0.055] | 3.76 | +0.0296 | -0.104 |
| on_close | close_only | +0.0169 [-0.011, +0.045] | 1.19 | +0.0183 | -0.123 |
| next_open | astral | +0.0211 [+0.003, +0.040] | 2.25 | +0.0174 | -0.119 |
| next_open | ohl_stop / olh_stop / close_only | +0.058 / +0.046 / +0.024 | — | — | -0.08 to -0.12 |

- The stop-price-fill 5m models look significant, but they are an artifact of the model. Under `ohl_stop`, **random entries earn +0.026% per trade** (uniform population mean +0.0264%; regime bars +0.0277%).
- The port agent found that walking the real 1m path turns the Astral-model +0.015% on 05-13..09-28 into -0.031% to 0.000%.
- The rule's excess over random entries under `ohl_stop`:
  - circular-shift null: z 3.0.
  - month-matched nulls: z 2.1-3.3.
  - The excess is again concentrated in 2021-2022 (by year: +0.108, +0.041, +0.019, -0.002, -0.005, +0.014).
- No execution variant survives realistic costs. The best is -0.08% per trade.

## 8. Breakeven cost and survival of winners (`out_analyze.txt`, `out_extras.txt`)

**Breakeven round-trip cost** (fees plus slippage, so net expectancy = 0):
- 0.0124% after pro-rata funding (day-cluster CI -0.006% to +0.031%).
- 0.0126% ignoring funding.
- Realistic taker is 0.14%. Maker/maker is 0.04%, which is above the upper CI bound.

**Astral's 40 trades (22 winners = 55%):**

| cost | winners still net-positive | net win rate | mean net | compounded at 25% |
|---|---|---|---|---|
| realistic | **14 of 22 (63.6%)** | 35.0% | -0.103% | -1.02% |
| best-case | 18 of 22 | 45.0% | -0.003% | -0.03% |

- 8 of the 22 winners were smaller than 0.14% gross: 0.004, 0.005, 0.028, 0.031, 0.057, 0.094, 0.107 and 0.121%.
- The 35% net win rate equals Astral's own 5/2 bps rerun (run 4c: 35.0%).

**Full history:** of 1,031 gross winners, 720 (69.8%) survive realistic costs and 961 (93.2%) survive best-case costs.

## 9. Caveats

- Everything uses the Astral 5m trailing-stop approximation (fill at the close after a touch). Over the full history this cannot be checked against 1m data; 1m DOGE data exists only from 2026-05-12. On the recent window the 1m walk was worse than the Astral model.
- The 50x liquidation rule is the task's simplification: MAE ≤ -1.5% on 5m highs and lows up to the exit fill, with the margin (25% of equity) lost plus entry-side costs. It ignores the mark-vs-last price difference, liquidation fees and tiered maintenance margin.
- Sub-5m wicks are invisible at 5m, so the liquidation count is a lower bound.
- Month/year "sum" figures are simple sums of per-trade % returns at 1x notional. Compounded figures use 25% of equity per trade.
- PF here is computed on per-trade % returns. Astral computes it on $ PnL; the two differ by under 0.001 on the 40-trade window.
- Random-entry p-values are one-sided and uncorrected for how the strategy was chosen. It was assembled from sub-strategies that looked good in a 7-day live audit, so the true evidence is weaker than the nominal p.
- Prices before 2022-06 are mostly 4-decimal, a tick of 0.03-0.17% of price, which affects trailing-stop fills. Aug 2021 to May 2022 supplies a disproportionate share of the zero-cost profit.
- Astral's own backtests are capped at 40,000 bars (about 139 days), so this 5-year evaluation can only be done with the port. The port was validated trade-for-trade on 175 Astral trades.

## 10. Files (all in this directory)

| file | content |
|---|---|
| `doge_strategy.py` | unmodified copy of the port |
| `hist_lib.py` | cost models, day-cluster CI, 25% and 12.5x equity and liquidation logic, metrics |
| `check_repro.py` | long file vs port and Astral windows (40/40, 135/135) |
| `run_sim.py` | full-history simulation; writes `trades_full_{astral,ohl_stop,olh_stop,close_only}.csv` and `df_full.pkl`, `ind_full.pkl`, `sig_full.pkl` |
| `analyze.py` → `out_analyze.txt`, `summary_costs.csv`, `per_year.csv`, `per_month.csv`, `liquidations_50x.csv` | main tables |
| `luck.py` → `out_luck.txt`, `windows16d.csv` | sliding 16-day windows |
| `outcomes.py` → `outcomes_astral.pkl`, `outcomes_ohl_stop.pkl` | per-bar trade outcomes |
| `null_random.py` → `out_null.txt` | month-matched random-entry nulls (A/B/C), 5,000 reps each |
| `null_shift.py` → `out_null_shift.txt` | circular-shift null and per-year excess |
| `null_subset.py` → `out_null_subset.txt` | nulls by sub-period |
| `extras.py` → `out_extras.txt` | Astral-40 winner survival, 16-day Sharpe distribution, 12.5x ruin timing, bad-bar clipping |
| `sensitivity.py` → `out_sensitivity.txt`, `sensitivity_exec.csv` | fill and trailing-stop model sensitivity |
| `out_ci_check.txt` | CI cross-check: week clusters [-0.0055, +0.0308], day-block bootstrap [-0.0053, +0.0315], P(mean ≤ 0) = 0.086 |
