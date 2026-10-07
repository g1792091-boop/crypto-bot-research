## Costs, slippage and execution: can 15m/30m survive costs?

**Short answer.** No: not with these signals, and not without a large new edge. At 15m and 30m the rule bot's losses are almost exactly its round-trip costs. Before costs the signals earn about zero, both in October's live paper data and in five years of history.

To break even, an AI trader would have to add a gross edge of about **10-19 bp of price per round trip**. At today's (unusually quiet) volatility that is **+0.16 to +0.29 R per trade at 15m** and **+0.11 to +0.22 R at 30m**. Maker entries lower this to about +0.10-0.17 R and +0.07-0.13 R, but only if fills are not adversely selected, and they are.

For scale: the best pre-cost edge any core strategy showed over five years is about +0.02 R, and the strategies' choice of long or short adds about 0 over a coin flip.

All numbers below come from scripts in `scratchpad/lens/costs/` (outputs in `out/`). R = net pnl / (qty x |fill - initial stop|), as in the pipeline.

### 1. Where the 15m/30m losses go (live trades, all runs)

`c01_decompose.py` -> `out/c01_decomp_by_tf.csv`. The identity R = gross_ref - entry slip - exit slip - fees - funding is checked per trade (max error 1e-12).

| group | tf | n | median stop % | net R | gross R (before costs) | cost R | of which fees | entry slip | exit slip | funding | liquidations |
|---|---|---|---|---|---|---|---|---|---|---|---|
| core36 | 5m | 837 | 0.31 | -0.597 | -0.021 | 0.577 | 0.411 | 0.082 | 0.082 | 0.001 | 0 |
| core36 | 15m | 630 | 0.64 | -0.190 | +0.072 | 0.262 | 0.187 | 0.038 | 0.038 | 0.000 | 0 |
| core36 | 30m | 378 | 0.90 | -0.152 | +0.024 | 0.176 | 0.126 | 0.025 | 0.025 | 0.000 | 0 |
| core36 | 1h | 212 | 1.25 | -0.073 | +0.042 | 0.115 | 0.083 | 0.017 | 0.017 | 0.000 | 0 |
| core36 | 4h | 31 | 2.02 | +0.144 | +0.209 | 0.065 | 0.046 | 0.009 | 0.009 | 0.000 | 0 |
| ds200 | 15m | 259 | 0.61 | -0.288 | -0.043 | 0.245 | 0.175 | 0.035 | 0.035 | 0.001 | 0 |
| ds200 | 30m | 181 | 0.84 | -0.126 | +0.045 | 0.171 | 0.122 | 0.025 | 0.025 | 0.000 | 0 |
| ds200 | 1h | 103 | 1.14 | -0.128 | -0.005 | 0.124 | 0.088 | 0.018 | 0.018 | 0.000 | 0 |

**Every signal, not only those a one-position account took** (`c02_replay.py`, the repo's own engine on live_bars, v3b+v4). Parity: 4,236/4,236 resolved signals match the pipeline's replay R to 1e-9. Accounting is in `c05_breakeven_by_tf.csv`; the CI is a cluster bootstrap with clusters = run x bar close floored to max(tf, 1h).

| core36 + ds200 | n (clusters) | stop % | net R | gross R [95% CI] | paper cost | real taker cost | real + BNB | maker entry + taker stop | maker both legs |
|---|---|---|---|---|---|---|---|---|---|
| 15m | 2,424 (54) | 0.62 | -0.103 | +0.132 [+0.001, +0.286] | 0.236 | 0.215 | 0.198 | 0.136 | 0.067 |
| 30m | 1,259 (53) | 0.89 | -0.144 | +0.020 [-0.072, +0.113] | 0.163 | 0.148 | 0.136 | 0.094 | 0.047 |
| 1h | 774 (53) | 1.24 | -0.134 | -0.017 [-0.113, +0.074] | 0.116 | 0.104 | 0.096 | 0.067 | 0.033 |
| 4h | 109 (11) | 2.02 | -0.042 | +0.022 [-0.192, +0.340] | 0.064 | 0.048 | 0.043 | 0.033 | 0.019 |
| coin flips 15m | 53 (32) | 0.63 | +0.018 | +0.257 [+0.031, +0.479] | 0.238 | | | | |

The small positive gross at 15m is not skill. The coin flips earned more, and both sides of the same signals net about -0.15 R in the pipeline's side-flip test. It is what tight ladder locks plus a wide stop earn in a quiet, ranging market.

### 2. Why a stop-loss costs -1.23 R instead of -1 R

`out/c01_sl_decomposition_by_tf.csv` (core36 + ds200 SL exits). 99.5-100% of SL exits fill exactly at stop - 2 bp; 1m bars almost never gap through the initial stop.

| tf | n | mean SL R | fees | exit slip | gap | funding | median stop % |
|---|---|---|---|---|---|---|---|
| 5m | 497 | -1.573 | 0.476 | 0.095 | 0.001 | 0.001 | 0.27 |
| 15m | 417 | -1.235 | 0.194 | 0.039 | 0.000 | 0.001 | 0.58 |
| 30m | 220 | -1.157 | 0.130 | 0.026 | 0.000 | 0.001 | 0.83 |
| 1h | 101 | -1.108 | 0.088 | 0.018 | 0.000 | 0.002 | 1.16 |
| 4h | 14 | -1.058 | 0.046 | 0.009 | 0.000 | 0.002 | 2.26 |

The overshoot is (12 bp fees + 2 bp exit slip) / stop %. The 2 bp entry slip sits inside the 1 R unit, because R is measured from the fill and the stop is placed from the reference price.

**Lock exits leak too** (`out/c01_lock_gap_by_tf.csv`). In 37% of LOCK exits the next 1m bar opens beyond the newly raised lock, because the ladder raises the stop after the bar, from its high. That costs 6.5 bp (15m), 8.0 bp (30m) and 8.9 bp (1h) per lock exit, or 0.115 / 0.090 / 0.076 R. At 30x the ladder's 2% ROE trigger gap is only about 6.7 bp of price, about one minute of noise (median 1m range 3.3-7.1 bp). On lock winners, costs eat about a quarter of the gross: 15m 0.24 of 0.92 R, 30m 0.17 of 0.68 R.

### 3. Five years: the loss is the round trip, in every regime

`c07_5y_regime.py` uses the repo's `research/levstop` `outcomes` -> `strategy_profiles._scan`, fixed 30x, 2 ATR stop, paper ladder, taker 5 bp + 2 bp slip + funding. The signal cache is verified identical to `labdata_reference.json` (18/18). The opposite side at the same bar is the coin flip. CIs are week-block bootstraps.

| tf | signals | median stop % | net bp/notional [CI] | gross bp | gross R [CI] | cost R | side choice vs coin flip, R [CI] |
|---|---|---|---|---|---|---|---|
| 15m | 1,140,655 | 0.97 | -14.24 [-14.75, -13.71] | +0.04 | +0.0013 [-0.0052, +0.0082] | 0.176 | +0.0031 [-0.0020, +0.0084] |
| 30m | 573,097 | 1.41 | -15.33 [-16.08, -14.65] | -0.91 | -0.0017 [-0.0079, +0.0050] | 0.120 | +0.0011 [-0.0041, +0.0068] |
| 1h | 287,925 | 2.06 | -17.45 [-18.63, -16.30] | -2.82 | -0.0055 [-0.0122, +0.0013] | 0.083 | +0.0023 [-0.0029, +0.0077] |

At 15m the net is -13.5 to -15.1 bp in every year from 2021 to 2026, -13.6 (DOGE) to -14.9 bp (BTC) on every coin, and -13.7 to -14.7 bp in every volatility quintile. At 30m the quintiles run from -14.1 (quietest, 0.72% stop) to -17.8 bp (most volatile, 2.68%).

No regime, coin or year carries a pre-cost edge. Trading only high-volatility periods lowers the cost in R units, but the per-notional loss stays the same. `levstop.json` agrees: -14.4 / -14.4 / -14.5 / -14.9 / -15.7 bp per notional at fixed 10x / 20x / 30x / 40x / 50x, and the liquidated share rises from 0.01% to 4.1%. DeepSeek's own five-year files show **negative** gross: median about -5 bp at 15m and about -6.5 bp at 30m, against a 10.4-10.7 bp cost.

### 4. The current market is quiet: costs in R are about 1.7x normal

`c06_vol_regime.py` -> `c06_live_vs_5y_stop.csv`.

| tf | live median stop % | 5y median stop % | live percentile in 5y | paper cost R live | paper cost R at 5y median |
|---|---|---|---|---|---|
| 15m | 0.620 | 1.035 | 17.8 | 0.226 | 0.135 |
| 30m | 0.886 | 1.496 | 16.1 | 0.158 | 0.094 |
| 1h | 1.244 | 2.174 | 13.5 | 0.113 | 0.064 |
| 4h | 2.016 | 4.593 | 3.8 | 0.069 | 0.030 |

The median 15m stop by year was 1.60% (2021), 1.15%, 0.79%, 1.00%, 0.99% and 0.76% (2026).

### 5. Real execution vs paper, by coin

`c03_exec_real.py`. The paper reference price is already the ask (long) or bid (short), so the spread is in paper. The real extra cost is the order-book walk at the paper size (about $45k), plus the real stop-market slip.

| coin | tick (bp) | entry book walk bp (n) | SL real slip bp (n) | real taker round trip bp | maker entry + taker stop bp | v4 stop $ paper - real |
|---|---|---|---|---|---|---|
| BTC | 0.01 | 0.011 (666) | 0.09 (57) | 10.1 | 7.1 | paper dearer by $836 |
| ETH | 0.04 | 0.030 (541) | 0.17 (28) | 10.2 | 7.1 | paper dearer by $525 |
| SOL | 0.83 | 0.066 (527) | 0.93 (44) | 11.0 | 7.1 | paper dearer by $512 |
| DOGE | 1.06 | 0.660 (366) | 1.74 (17) | 12.4 | 7.7 | paper dearer by $206 |
| LTC | 1.44 | 2.689 (514) | 3.34 (26) | 16.0 | 8.9 | paper cheaper by $444 |
| BCH | 0.32 | 4.402 (456) | 4.91 (42) | 19.3 | 11.6 | paper cheaper by $1,016 |

Paper's 14 bp is right on average. Replaying every signal with per-coin real costs on the same path changes core36 by +0.000 R at 15m [-0.044, +0.045] and +0.020 R at 30m. But paper flatters BCH and LTC, whose books are thin at 20-125k notional.

### 6. Break-even: the AI's required gross edge per trade

`c10_needed_edge.py`: needed R = round-trip bp / stop bp - max(five-year gross R, 0). Each cell shows the live-volatility figure first and the five-year-median-volatility figure second.

| tf | coin | real taker (live / 5y vol) | maker entry + taker stop (live / 5y) | paper 14 bp (live / 5y) |
|---|---|---|---|---|
| 15m | SOL | 0.155 / 0.075 | 0.098 / 0.046 | 0.199 / 0.098 |
| 15m | DOGE | 0.160 / 0.096 | 0.096 / 0.057 | 0.181 / 0.109 |
| 15m | LTC | 0.212 / 0.151 | 0.118 / 0.084 | 0.186 / 0.132 |
| 15m | BTC | 0.215 / 0.145 | 0.151 / 0.102 | 0.298 / 0.201 |
| 15m | ETH | 0.218 / 0.110 | 0.152 / 0.077 | 0.299 / 0.152 |
| 15m | BCH | 0.292 / 0.172 | 0.172 / 0.100 | 0.210 / 0.123 |
| 30m | DOGE | 0.114 / 0.069 | 0.070 / 0.042 | 0.129 / 0.078 |
| 30m | SOL | 0.116 / 0.055 | 0.074 / 0.035 | 0.148 / 0.070 |
| 30m | LTC | 0.149 / 0.105 | 0.083 / 0.058 | 0.130 / 0.092 |
| 30m | ETH | 0.150 / 0.076 | 0.105 / 0.053 | 0.206 / 0.105 |
| 30m | BTC | 0.151 / 0.100 | 0.106 / 0.070 | 0.209 / 0.139 |
| 30m | BCH | 0.216 / 0.124 | 0.130 / 0.075 | 0.157 / 0.090 |

General grid (`c05_breakeven_grid.csv`, required R = cost bp / stop bp), selected rows:

| stop % | paper 14 bp | real BTC 10.1 | real SOL 11.0 | real BCH 19.3 | maker entry (BTC) 7.1 | maker both 4 |
|---|---|---|---|---|---|---|
| 0.4% | 0.350 | 0.253 | 0.275 | 0.483 | 0.177 | 0.100 |
| 0.6% | 0.233 | 0.168 | 0.183 | 0.322 | 0.118 | 0.067 |
| 0.8% | 0.175 | 0.126 | 0.137 | 0.241 | 0.089 | 0.050 |
| 1.0% | 0.140 | 0.101 | 0.110 | 0.193 | 0.071 | 0.040 |
| 1.5% | 0.093 | 0.067 | 0.073 | 0.129 | 0.047 | 0.027 |
| 2.0% | 0.070 | 0.051 | 0.055 | 0.097 | 0.035 | 0.020 |

### 7. Levers that do not close the gap

**Maker / limit entries: adverse selection eats most of the saving.**

My replay (`c04_scenarios.csv`) and the nightly d3 limit shadow (`c08_limit_d3.csv`):

| | core36 15m | core36 30m | ds200 15m | ds200 30m |
|---|---|---|---|---|
| upper bound: maker fee, same fill and path | +0.065 | +0.061 | +0.060 | +0.052 |
| touch limit: fill rate / missed signals' market R / net vs market | 87.5% / +0.283 / +0.017 | 89.8% / +0.336 / +0.021 | 89.3% / +0.323 / +0.020 | 88.2% / +0.293 / +0.018 |
| 0.25 ATR limit, stop kept: fill / net [CI] | 62.9% / +0.006 [-0.114, +0.114] | 59.6% / +0.089 [+0.006, +0.173] | 66.7% / +0.014 | 61.3% / +0.011 |
| d3 limit shadow (v4): fill / missed winners share / net vs market [CI] | 68% / 63% / +0.097 [-0.009, +0.198] | 63% / 74% / +0.097 [+0.010, +0.199] | 69% / 67% / +0.015 | 62% / 80% / +0.007 |

After limit entries, net per signal is still -0.08 to -0.14 R. The five-year maker study found the same: +3 to +8 bp per trade, still negative.

**Wider stops** (same leverage, base-R units, `c04_scenarios.csv`): core 15m w25 -0.029, w30 -0.058 [-0.114, +0.006]; 30m -0.020 / -0.044; ds200 15m w30 -0.062 [-0.118, -0.003]. In own-R units (risk-based sizing) nothing changes: 15m -0.126/-0.125 vs -0.128. Five years at 30x: -1.30% to -1.36% of equity per trade going from 2 to 3 ATR. The dollar cost depends on notional, not on stop width.

**BNB fee discount** (4.5 bp taker): +0.016 R (15m), +0.031 R (30m).

**Coin restriction** to SOL/DOGE (plus BTC/ETH at a small notional): saves about 0.04-0.12 R vs including BCH.

**Fixing the lock gap**: up to about 0.05 R/trade (upper bound).

Stacked, these levers might cut the 15m bill from about 0.23 R to about 0.12-0.15 R. They cannot make a zero-gross signal positive.

### 8. Leverage turns the fixed 14 bp into equity drag

`c05_ai_leverage_cost.csv`. Cost per round trip as % of equity = 14 bp x leverage x margin share.

| leverage | margin = leverage % (quality rule) | per trade, paper | per trade, real BTC | 3 trades/day, paper | margin fixed at 20% |
|---|---|---|---|---|---|
| 20x | 20% | 0.56% | 0.40% | 1.68% | 0.56% |
| 30x | 30% | 1.26% | 0.91% | 3.78% | 0.84% |
| 40x | 40% | 2.24% | 1.62% | 6.72% | 1.12% |
| 50x | 50% | 3.50% | 2.53% | 10.50% | 1.40% |

The break-even price move (about 10-19 bp) does not depend on leverage, but the equity drag grows with leverage x margin. 50x/50% costs 6.25 times more per trade than 20x/20%.

### 9. Cost-lens grades of the strategies (`c09_strategy_cost_grades.csv`)

A = five-year gross covers the cost. B = small positive five-year gross in both periods. C = coin flip before costs. D = negative before costs.

| | 15m | 30m |
|---|---|---|
| core36 | A 0, B 1 (N02_ST_KST), C 23, D 5 | A 0, B 2 (N07_ICHI_CMO, N12_ICHI_AO), C 24, D 6 |
| ds200 | B 0, C 4, D 40 | B 0, C 6, D 35 |

The B cells earn +1.8 to +2.9 bp before costs (13-21% of one round trip). With 108 core cells, about 3 such cells are expected by chance.

Several live "winners" lose before costs over five years: N17_KC_RSI 15m (live gross +0.35 R [+0.06, +0.62], five-year -0.020 R [-0.031, -0.008]); N20_EMA9_CHOP 30m (+0.42 vs -0.011, both periods negative); OBV_S 30m (+0.74, n=8, vs -0.012); S4_BB_BBP 15m (+0.67 vs -0.013).

### 10. What this means for the AI traders

1. **Timeframe.** Prefer 30m to 15m: the cost per R is about 30% lower and the needed edge is 0.11-0.15 R instead of 0.16-0.22 R on the good coins. Keep 1h/4h as cost-free rule accounts; they are cheap per R but have no five-year gross either.
2. **Coins.** SOL and DOGE are cheapest per R. Use BTC/ETH at a small notional. Avoid BCH and LTC at a large notional.
3. **Strategy base.** Only N07_ICHI_CMO 30m, N12_ICHI_AO 30m and N02_ST_KST 15m bring any pre-cost edge, and it is tiny. D-graded strategies and DeepSeek definitions are poor bases whatever their October results.
4. **Leverage.** Do not scale to 40-50x on 'confidence' until the AI's gross edge is measured at 14 bp or more per round trip against a timing-matched coin flip. Every 50x/50% trade costs 3.5% of equity up front.
5. **Human-like behaviour.** Every switch or re-entry costs another 0.16-0.30 R at 15m. Make 'skip' the default and cap the trade count.
6. **Exit code.** Place the exchange stop the moment a lock arms (the 1m lock gap leaks 0.09-0.11 R per lock exit). Budget each stop at -(1 + cost/stop) R.
7. **Verification.** Detecting a +0.15 R gross improvement needs about 1,000 trades at 30m (SD 0.91 R, design effect 3.6) and about 4,400 at 15m. Pool the AI traders, log the opposite-side shadow for every AI entry, and judge them in gross bp per round trip.