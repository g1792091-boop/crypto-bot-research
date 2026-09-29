# Test of the claim "allowing shorts would raise win rate and profit" (Astral strategy 5864, DOGEUSD 5m)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/t_short`
Nothing under `/home/user/crypto-bot-research` was modified. No Astral tools were called in this step: all numbers come from the validated port (`doge_strategy.py`, an unmodified copy with sha256 800660e7...) run on the DATA agent's DOGE 5m file.

## 0. Verdict

**No. Adding shorts does not raise the win rate or the profit.**

- **Full clean history** (2022-06-01..2026-09-28, 4.3 years, Astral conventions):

  | variant | win rate, zero cost | win rate, real cost | gross per trade | net per trade, real cost |
  |---|---|---|---|---|
  | long only | 46.4% | 32.0% | +0.0104% | −0.130% |
  | short only | 45.3% | 31.3% | +0.0031% (t 0.38) | −0.137% |
  | long+short | 45.8% | 31.6% | +0.0066% | −0.134% |

  - At zero cost, the shorts add +6.0% of summed trade return over 4.3 years. That comes from a stream whose mean is statistically zero (95% CI −0.013..+0.019%/trade).
  - At realistic cost (0.05% taker + 0.02% slippage per side + 0.01%/8h funding), adding shorts roughly doubles the loss. At 25% sizing the result goes from −45.4% (long only) to −72.1% (long+short).
- **The friend's window** (2026-09-13..28):
  - 20 short trades would have fired, with 5 wins (25%) and gross −0.122%/trade (sum −2.44%).
  - The win rate would fall from 55% to 45%.
  - Astral-style total return would fall from +0.373% to −0.239% at zero cost, and from −1.02% to −2.32% with costs.
  - The short result sits at the 5th percentile of all 16-day windows since 2022-06.
- **Mechanism:** the long side's result is mostly the calendar trend. Across months, the correlation with DOGE buy-and-hold is r=+0.55 (p=2.6e-5). The short side does not even pick up the downtrend (r=+0.11, wrong sign, n.s.). Neither side beats random entries made in the same regime with the same exits (long excess +0.010%/trade, t 1.24; short +0.006%, t 0.77).
  - The one hint of timing skill appears only when there is already a strong 7-day trend in the trade's direction: +0.055%/trade, t 2.7. It is a post-hoc subgroup, mostly on the long side, and 2.5× smaller than the 0.14% round-trip cost.

## 1. Setup

- **Data:** `../data/dogeusd-5m-ohlcv.csv` (Polygon-aggregated USD spot via Astral).
  - Main sample: 2022-06-01 00:00..2026-09-28 23:55, 455,020 bars. This is the tick-clean start from the DATA agent.
  - Alternative sample: 2021-08-01 onward, 542,572 bars.
- **Conventions:** Astral's, as replicated trade-for-trade by the PORT agent.
  - Fills are on the signal bar's close.
  - Astral coarse trailing stop: O→H→L, the watermark is raised by the high first, and the fill is at the bar close.
  - Warmup is 660 bars and indicators are seeded at the slice start.
  - Check: the saved 5864 window was reproduced on this data file (40 trades, PF 1.272255111704368, TR 0.0037296).
- **Sides:**
  - `short` is the exact mirror: EMA63<EMA156, C<EMA600, spread<−0.15, CHOP<61.8, CROSS_BELOW(K,D), K>55, RSI26<48, C<EMA21. It exits on EMA63>EMA156 or CROSS_ABOVE(K,D), with a mirrored 0.35/0.20/0.20% trailing stop.
  - `both` holds one position at a time. In practice `both` is exactly the union of the long-only and short-only trade lists (1861/1861 and 1957/1957 identical). The regimes are mutually exclusive, and a long is always closed by the EMA-cross or K/D-cross exit before a short can trigger.
- **Rule-consistency** (`check_misc.py`):
  - 0 entry-rule violations out of 1861 long and 1957 short trades, checked by an independent vectorised re-derivation of the conditions.
  - 0 trailing-stop exits without a touch, and 0 overlapping positions.
  - Every signal bar was traded.
- **Costs:**
  - `real` = fee 0.05% + slippage 0.02% per side + funding 0.01%/8h pro-rata, all charged as a cost to both sides. That is 0.14% per round trip plus about 0.0002% funding, since the median hold is 1 bar.
  - Astral 5/2 bps gives practically the same result.
- **CIs:** a t-interval assuming independent trades, and a month-clustered interval (CR1). The win-rate CI is Wilson.

## 2. Standard summary, main sample (2022-06..2026-09). Returns per trade, % of notional.

Source: `out_main.txt`, `summary_table.csv`.

| side | cost | n | WR [95% CI] | avg win | avg loss | payoff | PF | mean/trade [95% CI] | t (month-cl) | Σ trade ret | total @25% | maxDD @25% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| long | 0 | 1861 | 46.4% [44.2, 48.7] | +0.294% | −0.240% | 1.22 | 1.082 | +0.0104% [−0.0070, +0.0278] | +1.17 (+1.20) | +19.3% | +4.86% | −2.71% |
| short | 0 | 1957 | 45.3% [43.1, 47.5] | +0.277% | −0.230% | 1.21 | 1.025 | +0.0031% [−0.0128, +0.0189] | +0.38 (+0.42) | +6.0% | +1.44% | −3.02% |
| both | 0 | 3818 | 45.8% [44.3, 47.4] | +0.285% | −0.235% | 1.21 | 1.053 | +0.0066% [−0.0051, +0.0184] | +1.11 (+1.14) | +25.3% | +6.37% | −3.67% |
| long | real | 1861 | 32.0% [29.9, 34.1] | +0.253% | −0.310% | 0.82 | 0.384 | −0.1298% [−0.147, −0.112] | −14.6 | −241.6% | −45.4% | −45.4% |
| short | real | 1957 | 31.3% [29.3, 33.4] | +0.229% | −0.304% | 0.75 | 0.343 | −0.1371% [−0.153, −0.121] | −17.0 | −268.4% | −48.9% | −49.0% |
| both | real | 3818 | 31.6% [30.2, 33.1] | +0.241% | −0.307% | 0.79 | 0.363 | −0.1336% [−0.145, −0.122] | −22.3 | −509.9% | −72.1% | −72.1% |

- **Hold time:** the median hold is 1 bar (5 minutes) for every variant. 85% of long exits and 81% of short exits are trailing-stop exits.
- **Break-even round-trip cost** (the gross mean): long 0.0104%, short 0.0031%, both 0.0066%. A realistic round trip costs 0.12–0.14%.

### Per year, zero cost (`per_year_main.csv`)

| year | long n / WR / mean / Σ | short n / WR / mean / Σ | both WR / Σ |
|---|---|---|---|
| 2022 (Jun–Dec) | 243 / 41.6% / +0.050% / +12.2% | 269 / 48.7% / +0.016% / +4.3% | 45.3% / +16.5% |
| 2023 | 416 / 47.1% / +0.018% / +7.4% | 362 / 40.6% / −0.015% / −5.5% | 44.1% / +1.9% |
| 2024 | 454 / 48.9% / +0.002% / +0.8% | 438 / 47.0% / +0.007% / +3.1% | 48.0% / +3.8% |
| 2025 | 444 / 47.5% / −0.007% / −3.0% | 526 / 50.8% / +0.024% / +12.6% | 49.3% / +9.6% |
| 2026 (Jan–Sep) | 304 / 44.1% / +0.006% / +1.9% | 362 / 37.3% / −0.023% / −8.4% | 40.4% / −6.5% |

- **Win rate:** adding shorts raised it in 2 of 5 years (2022, 2025) and lowered it in 3 (2023, 2024, 2026).
- **Zero-cost profit:** adding shorts raised it in 3 of 5 years and lowered it in 2.
- **No year** has any |t| > 1.61 on either side.

### Per year, real cost

| side | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| long, mean/trade | −0.090% | −0.122% | −0.139% | −0.147% | −0.134% |
| short, mean/trade | −0.124% | −0.155% | −0.133% | −0.116% | −0.164% |
| both, Σ trade return | −55% | −107% | −121% | −126% | −100% |

- Every year is negative on every side.

### Alternative sample from 2021-08-01 (`out_alt.txt`; prices tick-coarse until 2022-05)

| side | n | WR | gross/trade (t) | real/trade |
|---|---|---|---|---|
| long | 2214 | 46.6% | +0.0126% (t 1.52) | −0.128% |
| short | 2347 | 45.1% | +0.0057% (t 0.76) | −0.135% |
| both | 4561 | 45.8% | +0.0091% (t 1.62) | −0.131% |

At 25% sizing with real cost: −50.7% long only, −77.6% long+short.

### Sensitivity (zero cost, gross, main sample)

| setting | long | short | both |
|---|---|---|---|
| Astral model | +0.0104% | +0.0031% | +0.0066% |
| next_open fill | +0.0175% | +0.0055% | +0.0113% |
| `ohl_stop` | +0.039% | +0.012% | +0.026% |
| `olh_stop` | +0.030% | +0.012% | +0.021% |

- `ohl_stop` and `olh_stop` are 5m stop-fill paths, which the PORT agent showed are optimistic against the real 1m path.
- In every setting the short side is weaker than the long side, and every value is far below 0.14%.

**Real 1m path check, 2026-05-13..09-28** (`out_extra.txt`, gross):

| path | long | short | both |
|---|---|---|---|
| Astral | +0.015% | −0.032% | −0.010% |
| 1m walk O→H→L | −0.030% | −0.052% (t −3.26) | −0.042% (t −3.53) |
| 1m walk O→L→H | +0.001% | −0.019% | −0.010% |

## 3. The friend's window, 2026-09-13 07:00..09-28 (`out_window.txt`, `window_short_trades_astral_exact.csv`)

- **DOGE move:** +11.2% from close to close (0.08445 → 0.09390). The low was 0.07825 (09-15/16) and the high 0.10595.
- **Time in each trend state:** 43.4% of bars were in the long-trend state and 32.1% in the short-trend state.
- **Raw entry signals:** 40 long and 20 short. Every signal became a trade.
- The Astral-exact run (indicators from 09-11) and the long-history-warmed run give the same 40 long and 20 short trades.

| side | cost | n | WR | payoff | PF (Astral $) | mean/trade [95% CI] | Σ | total @25% | maxDD |
|---|---|---|---|---|---|---|---|---|---|
| long | 0 | 40 | 55.0% | 1.04 | 1.272 | +0.0374% [−0.089, +0.164] | +1.50% | +0.373% | −0.41% |
| short | 0 | 20 | 25.0% | 1.13 | 0.378 | −0.1222% [−0.294, +0.049] | −2.44% | −0.610% | −0.73% |
| both | 0 | 60 | 45.0% | 1.10 | 0.898 | −0.0158% | −0.95% | −0.239% | −0.78% |
| long | Astral 5/2 | 40 | 35.0% | 0.98 | 0.525 | −0.1026% | −4.10% | −1.023% | −1.04% |
| short | Astral 5/2 | 20 | 20.0% | 0.58 | 0.146 | −0.2623% | −5.25% | −1.304% | −1.30% |
| both | Astral 5/2 | 60 | 30.0% | 0.86 | 0.368 | −0.1558% | −9.35% | −2.314% | −2.31% |

The real-cost rows equal the Astral 5/2 rows to within 0.0002%.

- **When the shorts fired:**
  - 13 of the 20 shorts fired during the 09-13..09-16 down-leg and still lost 0.21% in total.
  - The other 7 fired against the 09-20..09-28 rally and lost 2.24%. The largest loss was on 09-28 00:35 (−1.14% in 2 bars).
- **1m-path check:** the shorts are −0.102%/trade on either 1m path, and both sides combined are −0.040% to −0.073%/trade.
- **Rolling 16-day windows** (1563 daily-start windows since 2022-06; `rolling16d.csv`):

  | percentile of the friend's window | among all windows | among windows where DOGE rose >10% |
  |---|---|---|
  | long total | 84th | 64th |
  | long win rate | 76th | 73rd |
  | short total | 5th | 4th |

  - 24% of all 16-day windows show a long win rate of at least 55%.
  - Combining both sides gave a higher win rate than long-only in 49.9% of windows and a higher sum in 50.6%. That is a coin flip.

## 4. Mechanism: regime (`out_regime.txt`, `regime_month.csv`, `regime_q.csv`)

**Monthly, 52 months.** Correlation of each series with the month's DOGE buy-and-hold return:

| series | Pearson r | p | Spearman ρ |
|---|---|---|---|
| long trade count | +0.60 | | +0.77 |
| long Σ return | +0.55 | 2.6e-5 | +0.47 |
| long mean/trade | +0.52 | 8.7e-5 | |
| long win rate | +0.22 | 0.11 | |
| short trade count | −0.37 | | |
| short Σ return | +0.11 | 0.45 | |
| short mean/trade | +0.12 | 0.40 | |
| short win rate | +0.04 | | |

- The correlation between the long Σ and the short Σ is +0.03.
- **Quarterly (18 quarters):** long Σ has Spearman +0.71 (p 0.0009). Short Σ has Pearson +0.28 (n.s.).

**Trades grouped by the sign of their month's buy-and-hold:**

| side | up months | down months |
|---|---|---|
| long | n 1129, WR 48.8%, +0.031%/trade (t 2.6) | n 732, WR 42.8%, −0.022% (month-cl t −2.4) |
| short | n 832, +0.000% | n 1125, +0.005% (t 0.45) |

- For the long side in months where DOGE rose more than 10%: +0.037%/trade. In months where it fell more than 10%: −0.020%.
- The short side makes nothing in either kind of month. In the two big crash quarters it was +7.0% (2025Q4) and −5.6% (2024Q2).

**Random entries in the same regime, with the same exits** (`precompute_outcomes.py`, `random_entry_null.csv`):
- Method:
  - A single trade was precomputed for every bar and both sides, with the strategy's own exits.
  - This reproduces the port's return for all 3818 actual trades (max |diff| 1e-16).
  - The null for each trade is the mean outcome of regime bars in the same calendar month.
  - A Monte Carlo draw of one random regime bar per trade was repeated 5000 times.
- Results:

  | regime null | long excess | short excess |
  |---|---|---|
  | N2 (trend filters + CHOP) | +0.0104%/trade (t_cl 1.24, MC p 0.12) | +0.0055% (t 0.77, p 0.26) |
  | N3 (every filter except the K/D cross) | +0.0106% (t 1.48, p 0.10) | +0.0060% (t 0.92, p 0.23) |

- Random entries have a higher win rate than the signal (long: null 48.1% vs actual 46.4%; short: 46.7% vs 45.3%).
- Monthly N2-random-entry outcome vs buy-and-hold: long +0.53 (the same as the actual long, +0.52). Short −0.33, meaning random short entries do benefit from down months. The actual short side is +0.12, so it does not.

**Per-trade OLS** (pooled long and short, side-signed trend variable, month-clustered):

| trend variable | slope | t | constant |
|---|---|---|---|
| month buy-and-hold | +0.00036 %/% | 2.17 | +0.005% (t 0.81) |
| prior 7-day return (ex-ante) | +0.0027 %/% | 3.15 | −0.007% (t −1.28) |
| local drift, 12h before and after the trade | +0.0049 | 1.23 | |

- Stacked with the N2 random bars and controlling for local drift and the month's buy-and-hold, the signal dummy is +0.0095% (t 1.67).

**Follow-up on the prior 7-day return** (`out_prior7d.txt`, `out_prior7d_null.txt`):
- Only the top quintile (signed prior 7-day return ≥ +12.8%) is positive: n 763, WR 51.4%, +0.0555% (t 2.74).
  - Random N2 entries in the same month and bin make +0.0007%, so the excess is +0.055% (t_cl 2.70).
  - By side: long +0.072% (t 2.33), short +0.035% (t 0.97).
  - The effect appears in both halves: top-quintile mean +0.065% (2022-06..2024-06) and +0.050% (2024-07..2026-09).
  - The other quintiles have excesses between −0.010% and +0.002%.
- After a 0.14% round trip even this bin is −0.085%/trade. The trades with signed prior-7d above +20% (9% of trades) make only +0.093% gross.
- It is a post-hoc subgroup found after one of four regressions was significant.

**Exit-independent forward returns** after signal bars, minus same-month N2 bars:
- No horizon is significant: 1, 3, 6, 12, 48 and 288 bars.
- The largest are long h=3 at +0.020% (t 1.51) and short h=12 at +0.035% (t 1.70).

## 5. Answer to "is there directional skill beyond riding the trend?"

- **Unconditionally, no.** Neither side beats random entries with the same exits in the same regime, the same month and the same state filters (t ≤ 1.5).
- **The long side's month-to-month results are mostly the month's trend.** r=+0.55, and the same correlation holds for random regime entries.
- **The short side does not even harvest downtrends.**
- **The only positive pocket needs a strong existing 7-day trend in the trade's direction.** That is by definition trend-conditional, it is a post-hoc subgroup, and it is 2.5× too small to pay taker costs.
- **So adding the mirrored short side does not raise the win rate and does not raise profit:**
  - It adds a zero-mean gross stream (+0.003%/trade).
  - After costs it is a −0.137%/trade stream that doubles the number of losing trades.
  - In the friend's own window it would have turned +0.373% into −0.239% at zero cost.

## 6. Caveats

- **Prices:** these are Polygon-aggregated spot USD prices, not Binance USDT-M perp prices.
  - Shorting needs the perp, which adds basis and funding.
  - Funding is charged here as a cost to both sides. In up-trends shorts usually receive funding, but at about 10-minute holds funding is worth less than 0.001%/trade either way.
- **No Astral check of the short side:** the short and both variants are not validated against Astral. Spec 5864 has allow_shorts=false, and building a short variant would need Astral tools not allowed here. The long side matches Astral 175/175 trades (PORT agent).
- **Trailing-stop model:** all main numbers use Astral's coarse trailing-stop model. The 1m walk, available only for 2026-05..09, makes every side worse, and the short side most of all.
- **Indicator seeding:** indicators are seeded at 2022-06-01. The first days after warmup could differ from a run seeded earlier. In the friend's window the two seedings give identical trades.
- **Missing bars:** the 322 missing 5m slots are treated positionally, as Astral does.
- **Rolling windows:** the 16-day windows overlap, so they are descriptive only.
- **Month-clustered SEs:** they use 52 clusters.
- **In-sample:** everything here is in-sample for a rule someone else designed. No parameter was tuned in this step.

## 7. Files

| file | content |
|---|---|
| `doge_strategy.py` | Unmodified copy of the port. No port bug was found; independent re-implementations reproduced every trade return. |
| `common.py` | Loaders, cost presets, `std_summary` (WR with Wilson CI, payoff, PF, mean with t-CI and month-clustered CI), `per_period` |
| `run_main.py` → `out_main.txt`, `out_alt.txt`, `trades_{main,alt}_{long,short,both}_{zero,real}.csv` | Step 1 simulations plus sensitivity |
| `make_tables.py` → `summary_table.csv`, `per_year_main.csv` | Tables |
| `run_window.py` → `out_window.txt`, `window_short_trades_astral_exact.csv` | The friend's window |
| `precompute_outcomes.py` → `outcomes_main.npz`, `out_precompute.txt` | Per-bar single-trade outcomes, both sides, verified against the port |
| `run_regime.py` → `out_regime.txt`, `regime_month.csv`, `regime_q.csv`, `random_entry_null.csv` | Regime correlations, random-entry null, OLS, forward returns |
| `run_extra.py` → `out_extra.txt`, `rolling16d.csv` | 1m-path check and rolling 16-day windows |
| `check_misc.py` → `out_misc.txt` | Rule consistency, window percentiles, quarterly table |
| `check_prior7d.py`, `check_prior7d_null.py` → `out_prior7d.txt`, `out_prior7d_null.txt` | Prior-7-day trend follow-up |
