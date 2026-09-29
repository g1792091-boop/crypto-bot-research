# Strategy 5864 (DOGEUSD 5m, long only): execution realism and sizing

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/t_exec`

Nothing under `/home/user/crypto-bot-research` was modified (`git status` is clean). No Astral calls were made; all work is local. Binance public market data (`fapi.binance.com`, `api.binance.com`, `data.binance.vision`) is blocked by the container proxy with a 403 on CONNECT, so no Binance-perp comparison was possible.

## 0. Bottom line

1. **The trailing stop is tighter than one bar's noise.**
   - DOGE 5m ATR14 (Wilder) median is 0.352% of price over 2021-08..2026-09, and 0.383% at the strategy's 2,214 entry bars.
   - The stage-1 stop (0.35%) is 0.91 ATR. The stage-2/3 stop (0.20%) is 0.52 ATR.
   - In 50.5% of trades the very next 5m bar's range alone is at least 0.35%.
   - So the modelled order of prices inside a bar decides a large share of the outcomes. Astral and a resting stop order differ by more than 0.01% on 74.5% of trades, and by more than 0.10% on 34%.
2. **With a real resting stop order the full-history gross edge is exactly zero.**
   - The stop order is re-placed at each 5m close from the previous bars' watermark and filled at the stop. This model is exact on 5m OHLC and is the 5m model closest to the 1m truth.
   - Result: -0.0000% per trade (day-cluster 95% CI -0.017% to +0.017%, n=2,214).
   - Astral's semantics give +0.0126% on the same entries (paired difference +0.0126%, t 2.4).
3. **On the most recent month, re-simulated on 1m bars, Astral's model overstates.**
   - 48 trades, 08-29..09-28, compared with a 1m resting-stop model:

     | window | Astral model | 1m truth | overstatement per trade |
     |---|---|---|---|
     | last month (48 trades) | +0.0227% | -0.0149% | +0.038% (t 0.84) |
     | friend's 40-trade window | +0.0374% | -0.0133% | +0.051% |
     | 4.5 months (143 trades) | — | — | +0.021% (t 1.2) |

   - None of these is individually significant.
   - Under the 1m truth, the friend's window has a 42.5% win rate, PF 0.90 and a -0.13% total at 25% sizing, instead of 55%, 1.27 and +0.37%.
4. **Astral's rule is not an edge-manufacturing bug; the stop-price-fill 5m models are.**
   - Astral fills at the bar close after a touch. That is a legitimate bar-close stopping rule.
   - On random entries it is nearly unbiased: -0.0009% vs the 1m truth on 40k recent bars, and +0.0007% ± 0.0006% on 400k zero-edge Monte Carlo paths.
   - The 5m "fill at the stop" models with an assumed intrabar order do manufacture edge: +0.025% to +0.030% per trade on random entries, t 14 to 38.
   - Astral's overstatement on this strategy is modest and specific to these entries. It is still in the flattering direction, and it roughly doubles the apparent per-trade result.
5. **Fill timing is second-order.**
   - Next-open fills are +0.0085% per trade better than on_close fills (t 6.3). All of it comes from the entry price: the consolidated feed's next open is on average 0.0085% below the signal-bar close, which looks like last-trade bounce.
   - Slippage of 0.015% per side costs -0.030% per trade and wipes that out.
6. **Costs dominate.**
   - The breakeven round-trip cost is 0.012% (Astral model, CI -0.006% to +0.031%) or 0.0085% (realistic bot).
   - At VIP0 taker costs (0.10% + 0.03% slippage = 0.13%) the net is -0.118% to -0.122% per trade, and 1 of 62 months is positive.
   - Even maker/maker (0.04%, which a stop exit cannot actually achieve) is -0.028% to -0.032% per trade, with a CI that excludes zero.
7. **Leverage multiplies the fee drag.** At 25% margin:

   | leverage | fee drag per trade (% of equity) | costs alone, equity multiple per year |
   |---|---|---|
   | 1x | 0.0325% | 0.87 |
   | 5x | 0.1625% | 0.50 |
   | 10x | 0.325% | 0.25 |
   | 20x | 0.65% | 0.06 |
   | 50x | 1.625% | 0.0009 |

   - The per-year multiples assume 430 trades a year.
   - Realistic ledger (bot fills plus taker costs) over 5.16 years: 1x 0.51, 5x 0.034, 10x 0.0011, 20x 9e-7, 50x 2e-16. There are no liquidations, because a resting stop caps the MAE at -0.377%.
   - Friend's window with costs: 1x -1.1%, 10x -10.4%, 50x -44.4%. Zero cost at 50x shows +15.0%, which is what Astral would suggest.

## 1. Engine

- `exec_lib.py` is an independent exit engine. Entry and exit *signals* come from the validated port (`doge_strategy.py`, a byte-identical copy of `../port/doge_strategy.py`, sha256 800660e7...).
- Validation (`validate.py` → `out_validate.txt`): my engine reproduces the port trade-for-trade.
  - Full history 2021-08..2026-09, on_close and next_open, models astral / ohl_stop / olh_stop / close_only: 2,214 trades each, identical entry and exit timestamps, maximum |Δgross| 2e-16.
  - Saved window 09-11..09-28: 40 trades, PF 1.272255111704368 and total 0.3729606%, which is Astral's own saved result.
  - Long Astral window 05-13..09-28 with the 1m walk: 135 trades, identical to the port's `sub1m` in all three paths.
- Data:
  - `../data/dogeusd-5m-ohlcv.csv` (sha256 6d87c817..., from 2021-08-01; 542,670 bars). Indicators are cached in `cache_2021-08-01.pkl`.
  - `../port/dogeusd-1m-merged.csv` (200,000 1m bars, 2026-05-12..09-29).
  - 1m aggregated to 5m matches the 5m file on O/H/L/C for 99.7/99.9/99.9/99.8% of 40,031 bars in 05-13..09-28. In the last month the match is 98.8/99.5/99.5/99.1% (vendor revisions). 1,651 5m bars have fewer than five 1m rows (minutes with no trades).

### TSL models (long; stop = watermark - distance(stage) x entry, tighten only)

| id | meaning | exact for |
|---|---|---|
| `astral` | 5m O→H→L. The watermark is raised by the bar high first, it triggers if low <= stop, and it **fills at the bar close**. | Astral (validated) |
| `astral_nx` | Astral's rule run by a bot: the same decision at the 5m close, with a market fill at the next open. | a bar-close bot |
| `opt` | "Optimistic ordering": favourable extreme first (O→H→L), fill at the stop (or at the open on a gap). Same as the port's `ohl_stop`. | nothing (assumed path) |
| `pess` | "Pessimistic ordering", continuous trailing: adverse extreme first against the stop from **previous bars' watermark**, fill at the stop. Then the high tightens the stop and the close is checked. Same as the port's `olh_stop`. | nothing (assumed path) |
| `prev` | **Resting STOP_MARKET re-placed at each 5m close** (watermark from previous bars' highs, no intrabar tightening). Triggers if open <= stop (fill at the open) or low <= stop (fill at the stop). | exact on 5m OHLC for a bot that updates its stop once per bar |
| `close` / `close_nx` | Bar-close-only evaluation: watermark from closes, trigger on the close, fill at the close or at the next open. | a bar-close bot |
| `m1_prev` | Resting stop re-placed every **1m** close, walked on real 1m bars. Path-independent at 1m. **Used as the 1m truth.** | a bot updating each minute |
| `m1_pess` / `m1_opt` | Continuous trailing per 1m bar with adverse-first / favourable-first ordering (a bracket). | — |

Signal exits are always evaluated on 5m closes.

The MAE is measured **up to the fill**: stop fills do not include post-fill prices, while close fills include the whole bar.

## 2. Task (1): trailing-stop semantics

### 2.1 ATR (`part1_atr.py` → `atr_stats.csv`, `out_part1_atr.txt`)

| period | bars | ATR14 Wilder median % | mean % | IQR % | median bar range % | entries | ATR at entries % | 0.35% / ATR | 0.20% / ATR |
|---|---|---|---|---|---|---|---|---|---|
| full 2021-08..2026-09 | 542,656 | **0.352** | 0.419 | 0.255–0.497 | 0.321 | 2,214 | **0.383** | **0.91** | **0.52** |
| tick-safe 2022-06.. | 455,118 | 0.337 | 0.402 | 0.242–0.480 | 0.308 | 1,862 | 0.368 | 0.95 | 0.54 |
| 2026 | 77,857 | 0.268 | 0.305 | 0.201–0.365 | 0.245 | 304 | 0.322 | 1.09 | 0.62 |
| last month 08-29.. | 9,026 | 0.306 | 0.329 | 0.227–0.388 | 0.273 | 48 | 0.388 | 0.90 | 0.52 |
| Astral window 09-13 07:00..09-28 | 4,524 | 0.323 | 0.360 | 0.239–0.426 | 0.293 | 40 | 0.394 | 0.89 | 0.51 |

- 50.5% of all bars have ATR ≥ 0.35%, and 87.8% have ATR ≥ 0.20%.
- The next bar after entry has a median range of 0.353%. It is at least 0.35% in 50.5% of trades and at least 0.55% in 24.5%.

### 2.2 Full history, strategy re-simulated per 5m model (on_close, zero cost; `models_5m_fullhistory.csv`)

| model | n | mean gross %/trade [day-cluster 95% CI] | t | win | PF | TSL exits |
|---|---|---|---|---|---|---|
| **astral** | 2,214 | **+0.0126** [-0.0061, +0.0313] | 1.32 | 46.6% | 1.10 | 86% |
| astral_nx | 2,214 | +0.0109 [-0.0075, +0.0294] | 1.16 | 46.4% | 1.08 | 86% |
| opt (favourable-first) | 2,214 | +0.0495 [+0.0285, +0.0704] | 4.63 | 49.8% | 1.47 | 86% |
| pess (adverse-first, continuous) | 2,214 | +0.0360 [+0.0173, +0.0547] | 3.76 | 46.8% | 1.28 | 85% |
| **prev (resting stop order)** | 2,214 | **-0.0000** [-0.0166, +0.0165] | -0.00 | 42.6% | 1.00 | 84% |
| close (bar-close only) | 2,214 | +0.0169 [-0.0109, +0.0446] | 1.19 | 38.4% | 1.09 | 61% |
| close_nx | 2,214 | +0.0188 [-0.0091, +0.0466] | 1.32 | 38.5% | 1.10 | 61% |

- Tick-safe period (from 2022-06): astral +0.0103%, prev -0.0016%.
- Same entries, paired differences vs `prev` (`fullhistory_same_entries_5m.csv`):

  | model | Δ vs prev | t |
  |---|---|---|
  | astral | +0.0126 | 2.4 |
  | opt | +0.0495 | 6.7 |
  | pess | +0.0360 | 14.0 |
  | close | +0.0169 | 1.5 |

- Disagreement, Astral vs prev (`out_disagreement.txt`): |Δ| > 0.01% on 74.5% of trades, |Δ| > 0.10% on 34.1%, a different exit bar on 49.8%, and a mean |Δ| of 0.117% per trade.
- Astral's 1,907 TSL fills at the bar close sit above the stop level 52.4% of the time. Relative to the stop level, the close averages -0.043% (median +0.010%).

### 2.3 Same entries on 1m bars (`part1_models.py` → `fixed_entries_5m_vs_1m.csv`, `per_trade_last_month.csv`, `out_part1_models.txt`)

- Entries are the Astral-model signal bars. Each exit is re-simulated independently.
- Δ = 5m model minus the 1m truth, per trade, with day-cluster t. MAD = mean |Δ|.

**Most recent month, 2026-08-29..09-28, 48 trades.** Truths: m1_prev -0.0149%, m1_pess -0.0111%, m1_opt -0.0514% per trade.

| 5m model | mean | Δ vs m1_prev (t) | MAD vs m1_prev | Δ vs m1_pess | Δ vs m1_opt |
|---|---|---|---|---|---|
| astral | +0.0227 | **+0.0376** (0.84) | 0.151 | +0.0338 | +0.0741 |
| astral_nx | +0.0249 | +0.0399 (0.93) | 0.151 | +0.0361 | +0.0764 |
| opt | +0.0393 | +0.0542 (0.88) | 0.106 | +0.0504 | +0.0907 |
| pess | +0.0447 | +0.0596 (1.64) | 0.099 | +0.0558 | +0.0962 |
| **prev** | +0.0089 | **+0.0239** (1.10) | **0.086** | +0.0200 | +0.0604 |
| close | +0.0790 | +0.0939 (1.90) | 0.301 | +0.0901 | +0.1305 |
| close_nx | +0.0772 | +0.0921 (1.90) | 0.299 | +0.0883 | +0.1286 |

**Friend's window, entries 09-13 07:00..09-28, 40 trades.** Truths: m1_prev -0.0133%, m1_pess -0.0087%, m1_opt -0.0577%.

| 5m model | Δ vs m1_prev |
|---|---|
| astral | **+0.0507** |
| prev | +0.0300 |
| opt | +0.0714 |
| pess | +0.0710 |
| close | +0.1335 |

- Largest single gap: the 09-21 18:10 trade, Astral +1.115% vs 1m +0.191%.
- Example 09-18 08:55 (entry 0.08481):
  - In the trigger bar 09:05, the low of 0.08479 printed in the first minute and the high of 0.085429 in the last minute.
  - Astral raises the stop to 0.08526 using that high, sees low < stop, and books the close 0.085357, i.e. +0.645%.
  - A 1m stop books +0.414%.

**Longer 1m period, 2026-05-13..09-28, 143 trades.**

| model | mean | Δ vs m1_prev (t) | MAD |
|---|---|---|---|
| astral | +0.0153 | +0.0214 (1.19) | 0.101 |
| prev | +0.0070 | +0.0131 (1.32) | 0.061 |
| opt | +0.0241 | +0.0302 | 0.062 |
| pess | +0.0360 | +0.0421 (2.69) | 0.057 |
| close | +0.0425 | +0.0486 | 0.213 |

1m truths: m1_prev -0.0062, m1_pess +0.0008, m1_opt -0.0300. Re-simulating the strategy with 1m exits (`resim_1mperiod.csv`) gives the same numbers, because the trade sets coincide.

**Which 5m model is closest to the 1m truth? `prev`, the resting stop from previous bars' watermark.**
- It has the smallest bias on the strategy's entries: +0.024% last month and +0.013% over 4.5 months.
- It has zero bias on random entries (next table).
- It has the lowest per-trade MAD (0.06–0.09%).

**Does Astral over- or under-state? It overstates on this strategy's trades.**

| comparison | overstatement per trade |
|---|---|
| vs 1m truth, last month | +0.038% |
| vs 1m truth, 4.5 months | +0.021% |
| vs 1m truth, friend's window | +0.051% |
| vs the exact 5m stop-order model, full history | +0.013% (t 2.4) |

Its per-trade tracking error is 0.10–0.15%.

### 2.4 Is the gap structural? Random entries and a zero-edge Monte Carlo

**All-bar entries, 1m period** (`part1_allbars.py` → `allbars_model_bias.csv`): every 5m bar in 05-13..09-28 is used as a long entry with the same exits (n=40,031).

| model | Δ vs m1_prev (t) |
|---|---|
| astral | -0.0009 (-0.97) |
| opt | -0.0002 |
| prev | +0.0000 |
| pess | **+0.0141 (10.3)** |
| close | -0.0043 |
| m1_pess | +0.0048 |
| m1_opt | -0.0087 |

Regime bars only (n=14,813): astral -0.0043, prev 0.0000, pess +0.0211.

**Every 4th bar, full history** (`allbars_fullhistory_5m.csv`, n=135,490), Δ vs prev:

| model | Δ vs prev (t) |
|---|---|
| astral | +0.0036 (5.1) |
| astral_nx | +0.0014 |
| opt | **+0.0303 (13.6)** |
| pess | **+0.0253 (38)** |
| close | +0.0018 |

- In 2021-08..2022-05 (coarse ticks) astral is +0.0099. In 2026 it is -0.0023.

**Zero-edge Monte Carlo** (`mc_gbm.py` → `mc_gbm_model_bias.csv`):
- Setup: 400k martingale paths at 1-s resolution. Per-path volatility is drawn from the real ATR at the 2,214 entries (median σ_5m 0.24%). Staged TSL, time exit after 12 bars.
- The true expectation of any implementable rule is 0, and the check confirms it: `cont_1s_fill_at_price` +0.0001%, `prev_fill_at_price` +0.0000%, `m1_prev_fill_at_price` -0.0000%.
- Results:

  | model | mean per trade |
  |---|---|
  | astral | +0.0007% ± 0.0006 (unbiased) |
  | close | +0.0013% ± 0.0011 |
  | m1_astral | +0.0000 |

- Fill-at-stop models carry a 1-s overshoot of about +0.008–0.010%. Net of it:

  | model | bias |
  |---|---|
  | opt | ≈ -0.005 |
  | pess | ≈ +0.022 |
  | m1_opt | ≈ -0.037 |
  | m1_pess | ≈ +0.003 |
  | m1_prev | ≈ +0.000 |

- Continuous trailing vs m1_prev: -0.001%, so under Brownian motion m1_prev is a good proxy for true continuous trailing.
- GBM ignores real microstructure (for example, the real m1_opt minus m1_prev gap is -0.009%, not GBM's -0.037%). It is a sanity check only.

Interpretation:
- Astral's fill-at-close-after-touch is an honest, if different, bar-close exit rule.
- The favourable-first and adverse-first stop-price-fill 5m models, and the per-minute favourable-first model, carry systematic biases of ±0.02–0.04% per trade.
- The overstatement of Astral vs real stops on *this strategy's* entries (+0.013% to +0.05%) is larger than on random entries, and noisy. It is not a general platform bias.

## 3. Task (2): fill timing (`part2_fill.py` → `fill_timing_full.csv`, `fill_timing_paired.csv`, `fill_timing_1m.csv`)

**The feed itself:**
- The consolidated feed's 5m open differs from the previous close in 79.5% of bars, with a mean |gap| of 0.028%.
- At the 2,214 entry signal bars, the next open is on average **0.0085% below** the signal close (median 0). Over all bars the mean is -0.0023%.

**Same signal bars, exit model fixed, next_open minus on_close per trade:**

| exit model | Δ per trade (t) | entry-price effect |
|---|---|---|
| Astral exits | **+0.0085%** (6.3) | +0.0085% |
| stop-order exits | +0.0087% (4.6) | +0.0085% |

- The entry-price effect is the whole difference.
- In the window, next open is +0.008% with Astral exits and +0.006% with stop orders.

**Strategy re-simulated, full history, zero fees:**

| config | fills | TSL model | mean %/trade | t | win |
|---|---|---|---|---|---|
| A (= Astral) | on_close | astral | +0.0126 | 1.32 | 46.6% |
| B | next_open | astral (fill at trigger-bar close) | +0.0211 | 2.25 | 47.8% |
| C | next_open | astral rule, stop exit at next open | +0.0195 | 2.10 | 47.5% |
| D | on_close | stop orders | -0.0000 | -0.00 | 42.6% |
| **E (realistic bot)** | **next_open** | **stop orders** | **+0.0087** | 1.05 | 43.9% |

**Adding slippage** (entry and exit fill; a stop exit is a market order after the trigger):
- 0.015% per side costs -0.030% per trade, so E becomes -0.0213%.
- 0.02% per side costs -0.040%, so E becomes -0.0313%.

**About 60 s latency** (fill at the close of the first 1m bar after the signal close; 1m period, 143–144 trades). m1_prev per trade:

| fill | mean |
|---|---|
| on_close | -0.0062% |
| next_open | +0.0049% |
| lat1m | -0.0057% |

Standard errors are about 0.02–0.03%.

**Reading:**
- The "better" next open is a feature of the consolidated last-trade series, which bounces after an up-close.
- On one venue a market buy pays the ask whatever the last print was. Treat the fill-timing effect as about 0 ± 0.01% per trade, and model the real cost as spread plus slippage.

## 4. Task (3): cost curve (`part3_costs.py` → `cost_curve.csv` (0–0.20% in 0.01% steps), `cost_points.csv`)

- Full clean history, 2,214 long trades, 2021-08-03..2026-09-29.
- Funding of 0.01%/8h is charged pro-rata on top. The mean hold is 8–12 minutes, so funding averages about 0.0002% per trade.

**Breakeven round-trip cost, i.e. the mean gross per trade [day-cluster 95% CI]:**

| ledger | breakeven |
|---|---|
| A, Astral execution | **0.0124%** [-0.0062, +0.0311] |
| E, realistic bot (next open plus resting stop orders) | **0.0085%** [-0.0078, +0.0248] |
| D, on_close plus stop orders | -0.0003% |

**Marked points:**

| cost point | RT % | A mean net % [CI] | A PF / win | E mean net % [CI] | E PF / win | 25%-sizing total A / E | months positive A / E |
|---|---|---|---|---|---|---|---|
| maker/maker 0.02+0.02, no slip (**not reachable**: 84–86% of exits are stop-market = taker) | 0.040 | -0.028 [-0.046, -0.009] | 0.82 / 43.4% | -0.032 [-0.048, -0.015] | 0.79 / 41.6% | -14.2% / -16.1% | 26% / 32% |
| maker entry + taker stop exit + 0.015% slip | 0.085 | -0.073 | 0.59 / 38.1% | -0.077 | 0.57 / 34.4% | -33.2% / -34.6% | 13% / 3% |
| VIP0 taker with BNB (0.045%x2) + 0.015%x2 slip | 0.120 | -0.108 | 0.46 / 34.7% | -0.112 | 0.45 / 30.3% | -44.9% / -46.1% | 3% / 2% |
| **VIP0 taker 0.05%x2 + 0.015%x2 slip** | **0.130** | **-0.118** [-0.136, -0.099] | 0.43 / 34.0% | **-0.122** [-0.138, -0.105] | 0.42 / 28.9% | -47.9% / -49.0% | 1.6% / 1.6% |
| VIP0 taker + 0.02%x2 slip (= Astral 5/2 bps) | 0.140 | -0.128 | 0.40 / 32.5% | -0.132 | 0.39 / 27.8% | -50.7% / -51.8% | 1.6% / 1.6% |

- The breakeven sits at about 1/10 of the realistic round trip (0.12–0.14%).
- With costs, net expectancy is linear in the round-trip cost (slope -1).

## 5. Task (4): sizing and leverage (`part4_leverage.py` → `leverage_accounts.csv`, `fee_drag.csv`)

**Setup:**
- One account. Each trade posts 25% of current equity as isolated margin, with notional = 25% x L of equity.
- Liquidation happens if the MAE up to the exit fill is at least 1/L - 0.5%, i.e. 19.5 / 9.5 / 4.5 / 1.5% for 5 / 10 / 20 / 50x. A liquidation loses the margin plus the entry fee and slippage.
- Costs: 0.05% fee + 0.015% slippage per side, plus funding. 430 trades a year.

**Fee drag per trade (% of equity) = 0.25 x L x 0.13%:**

| leverage | 1x | 5x | 10x | 20x | 50x |
|---|---|---|---|---|---|
| per trade | 0.0325% | 0.1625% | 0.325% | 0.65% | 1.625% |
| per year, simple sum | 14% | 70% | 140% | 280% | 699% |
| equity multiple per year from costs alone | 0.87 | 0.50 | 0.25 | 0.060 | 0.00087 |

The gross edge needed per unit of notional is 0.13% at every leverage. Leverage does not change the breakeven; it multiplies the fees and the variance.

**Final equity (start 1.0), max drawdown (closed-trade) and liquidations:**

| ledger | period | 1x | 5x | 10x | 20x | 50x |
|---|---|---|---|---|---|---|
| A0: Astral trades, zero cost (what Astral shows) | full 5.16 y | 1.071, -2.7% | 1.381, -13.1% | 1.811, -25.4% | 2.673, -48.4% | **0.789, -94.5%, 10 liq.** |
| A: Astral trades + taker costs | full | 0.521, -48.2% | 0.0375, -96.4% | 0.00133 | 1.4e-6 | 1.4e-16, 10 liq. |
| **E: bot (next_open + stop orders) + taker costs** | full | **0.510, -49.0%** | **0.0337, -96.6%** | **0.00108, -99.9%** | **9.4e-7** | **1.8e-16, 0 liq.** |
| A0 | window 09-13..28 (40 tr.) | 1.0037, -0.41% | 1.018, -2.1% | 1.036, -4.1% | 1.070, -8.0% | **1.150, -19.2%** |
| A | window | 0.9907, -0.95% | 0.954, -4.7% | 0.910, -9.2% | 0.824, -17.9% | 0.598, -40.5% |
| **E** | window | **0.9893, -1.18%** | **0.947, -5.8%** | **0.896, -11.3%** | **0.800, -21.5%** | **0.556, -46.6%** |

**First date equity falls below 50%, ledger E:** 50x 2021-09-15 (6 weeks after the start), 20x 2021-11-08, 10x 2022-03-27, 5x 2022-08-13, 1x never.

**Liquidations:**
- The 10 liquidations at 50x under Astral semantics are an artefact of the fill at the trigger-bar close: the price is allowed to run to -1.5% or beyond before the exit.
- A resting stop order caps the MAE up to the fill at -0.377% (gap opens), so ledger E has 0 liquidations at every leverage.
- Real-world caveats: stop-market fills in fast markets can be worse than 0.015%, Binance liquidates on mark price, and neither is visible in 5m spot OHLC.

## 6. Task (5): Astral vs a Binance USDT-M perp bot. Concrete differences

Sources: the port agent's Astral JSONs (`../port/astral/backtest-*.json`), the replication, and the measurements above.

| # | Astral (strategy 5864 as backtested) | Binance USDT-M perp bot | measured / verified effect |
|---|---|---|---|
| 1 | **Price feed:** `DOGEUSD`; `market_data_disclosure.crypto_market_scope = "consolidated"`, `price_kind = "ohlcv"`, `source = "canonical_history_adapter"`, capability `massive/xas/crypto/configured-realtime-1` (Massive, formerly Polygon), spot USD across venues | `DOGEUSDT` perpetual on one venue. Stops trigger on last or mark price (`workingType`); liquidation uses mark price; there is a spot–perp basis | Not measurable here: Binance endpoints are blocked from this container. In the feed, 79.5% of 5m bars open away from the previous close (mean 0.028%), a sign of multi-venue last-trade prints |
| 2 | **Costs:** `commission_bps 0`, `slippage_bps 0` by default | taker 0.05%/side (0.045% with BNB), maker 0.02%, spread and slippage about 0.01–0.02% per market fill | Gross breakeven is 0.012% round trip vs a real 0.12–0.14%. Astral's own 5/2 bps rerun: 40 trades, win rate 35%, PF 0.53, -1.02% (port agent) |
| 3 | **Fill timing:** `fill_price_mode on_close`, i.e. the entry fills at the close of the very bar whose close produced the signal | The order can only be sent after the close. It fills at about the next open plus latency, and pays the spread | +0.0085%/trade in favour of the next open in this feed (bounce); ±0.01% noise with 60 s latency; slippage -0.03%/trade |
| 4 | **TSL:** watermark raised with the trigger bar's **high before** the low is checked; exit at the **bar close** (`price_source = strategy_bar_close_after_target_touch`, `execution_model_version = strategy-bar-on-close-1`). Astral flags this itself: warning `PROTECTION_COARSE_APPROXIMATION` (severity "info"), `execution_ambiguity = no_sub_bar_attempt_timing`, modelled as a market order with `time_in_force DAY` | A resting STOP_MARKET fills at about the stop minus slippage when it is touched. A native `TRAILING_STOP_MARKET` has one callback rate, so the staged 0.35%→0.20% distances need bot-side cancel/replace | Astral overstates vs real stops: +0.013%/trade (full history, t 2.4), +0.038% (last month vs 1m), +0.051% (window vs 1m). Per-trade tracking error 0.10–0.15%. 55% win rate vs 42.5% (1m) in the window |
| 5 | **Direction and product:** `allow_shorts false`; spot; no leverage, margin, liquidation or funding (no funding field anywhere in the result JSON) | Longs and shorts, 1–125x, isolated or cross margin, liquidation, funding every 8h | Funding here is about 0.0002%/trade (holds of 8–12 min). Leverage turns fees into 0.16–1.6% of equity per trade (section 5). The port agent's short side was worse than the long side |
| 6 | **Indicator history:** indicators restart at the backtest `start` (`raw_data_start = start`), with 660 warmup bars; results depend on the start date | Continuous history | Port agent: shown with two discriminating runs |
| 7 | **History cap:** at most 40,000 bars per backtest (5m about 4.6 months; the 05-13 run was capped at 05-13 03:05) | n/a | The 5-year evaluation had to be done off-platform: 2,214 trades, gross +0.013% (t 1.3) |
| 8 | **Data revisions and gaps:** recent bars are revised for hours. The DOGE 09-27 12:00/12:20 bars changed between two runs minutes apart (total 0.0037296 → 0.0037306). ETH bars 36 h old changed. The whole of 2026-04-22 is missing in every series | The exchange's own trades are final | For monitoring, a live signal computed on first prints may not be the one a later backtest shows |
| 9 | **Metrics and sample:** Sharpe 2.69 from 15 daily returns, annualised by √365.2425 | — | Sharpe SE ≈ 4.96, so the 95% CI is about -7.0 to +12.4. Win rate 55% on 40 trades has a CI of 38.5–70.7%. Expectancy $9.32/trade on $25k notional = 0.037%, vs $32.5 for one taker round trip |
| 10 | **Sizing:** 25% of equity; fractional quantities (for example 296,148.178 DOGE); no lot size or minimum notional | Quantity step and minimum notional per symbol | Negligible at this size |

Astral's arithmetic is correct: the port reproduces every metric to 1e-15. The differences are in *what* is simulated, not in how it is counted.

## 7. Port observations

- **No port bug** affects the Astral replication.
- **Caveat on the port's `mae` column:** it takes bar extremes including the exit bar's full low, even when the model fills at the stop, so it counts prices after the fill.
  - For `astral` (fill at close) this is correct.
  - For `ohl_stop` / `olh_stop` it produces 10 trades with MAE ≤ -1.5% over the full history, versus 0 when the MAE is measured up to the fill (`out_port_mae_check.txt`).
  - Any 50x liquidation analysis on stop-fill models that uses the port's `mae` would therefore show 10 false liquidations. `exec_lib.py` measures the MAE up to the fill.
- **Naming:** the port aliases `intrabar_pess` = O→H→L (favourable-first) and `intrabar_opt` = O→L→H. In P&L terms both are optimistic relative to a resting stop order (+0.050% and +0.036% vs 0.000% over the full history). "Pessimistic" in the port refers to trigger frequency, not P&L.
- The port's `sub1m` falls back to 5m `ohl_stop` for 5m bars with no 1m rows; `exec_lib` uses the same model on 5m. This made no difference on the validated 135 trades.

## 8. Caveats

- The "1m truth" is itself a bar model. `m1_prev` is exact for a bot that re-places its stop each minute. Continuous trailing lies between `m1_opt` and `m1_pess` (GBM suggests near `m1_prev`). Tick data would be needed for more.
- Sample sizes are small: 48 trades in the last month and 143 in the 1m period. Individual Δ's have t of about 1.
- The gaps between Astral and 5m stop orders on random entries differ by period (+0.010% in coarse-tick 2021–22, -0.002% in 2026).
- No Binance data: the spot-consolidated vs perp-last/mark difference, real stop slippage and mark-price liquidation are **unmeasured**. The 0.015%/side slippage is an assumption.
- Fill at the stop (the `prev`, `opt` and `pess` models) ignores stop-market overshoot. Slippage is charged separately as a cost.
- Leverage accounts assume trades never overlap (true: one position at a time), 25% margin, no cross-margin interaction and no ADL.
- The `lat1m` fill uses the 1m close of the first minute. With a stop order, the resting stop is also checked in that minute.

## 9. Files

| file | content |
|---|---|
| `exec_lib.py` | engine: TSL models, fill modes, 1m walk, MAE up to fill, `run_strategy`, `run_fixed`, `stats` (day-cluster SE) |
| `doge_strategy.py` | copy of the port (unmodified) |
| `validate.py`, `out_validate.txt` | trade-for-trade validation vs the port |
| `part1_atr.py`, `atr_stats.csv`, `out_part1_atr.txt` | ATR statistics |
| `part1_models.py`, `models_5m_fullhistory.csv`, `fixed_entries_5m_vs_1m.csv`, `resim_1mperiod.csv`, `per_trade_last_month.csv`, `out_part1_models.txt`, `trades_full_<model>_onclose.csv`, `trades_1mperiod_<model>_onclose.csv` | 5m model comparison, same entries on 1m |
| `part1_allbars.py`, `allbars_model_bias.csv`, `fullhistory_same_entries_5m.csv`, `out_part1_allbars.txt` | random-entry bias (1m period) and paired full history |
| `part1_allbars_full.py`, `allbars_fullhistory_5m.csv`, `out_part1_allbars_full.txt` | random-entry bias, full history |
| `mc_gbm.py`, `mc_gbm_model_bias.csv`, `out_mc_gbm.txt` | zero-edge Monte Carlo |
| `out_disagreement.txt` | per-trade disagreement, Astral vs other models |
| `window_table.py`, `window_40_trades_by_model.csv`, `out_window_table.txt` | friend's 40 trades under each model, gross and net |
| `part2_fill.py`, `fill_timing_*.csv`, `out_part2_fill.txt`, `trades_full_{astral,astral_nx,prev}_{on_close,next_open}.csv` | fill timing |
| `part3_costs.py`, `cost_curve.csv`, `cost_points.csv`, `out_part3_costs.txt` | cost curve |
| `part4_leverage.py`, `leverage_accounts.csv`, `fee_drag.csv`, `out_part4_leverage.txt` | leverage accounts |
| `out_port_mae_check.txt` | port `mae` vs MAE up to fill |
| `cache_2021-08-01.pkl` | cached 5m data, indicators and signals (67 MB; safe to delete) |
