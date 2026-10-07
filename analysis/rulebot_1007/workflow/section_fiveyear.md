## Live vs 5-year reconciliation

**Bottom line.** All 36 core strategies and all 44 DeepSeek definitions were run over 5 years through the live house exit at paper-v4 leverage. **None of them makes money on any timeframe.** Their gross edge (before costs) is about zero everywhere, so the net result is simply minus the trading cost. The cost in R is set by how small the 2 ATR stop is relative to price, which makes 15m the worst timeframe and 4h the least bad.

The 4.8 days of live data sit inside the 5-year range for windows of the same length on every timeframe, and live signal counts match the 5-year definitions. Per-cell live rankings carry no information: they disagree with the 5-year results, and with each other from one live run to the next.

For the AI bot this means the rule signal is a moment to look at the chart, not a direction with an edge. At today's low volatility, an AI trader must add about **+0.22R per trade at 15m, +0.16R at 30m, +0.11R at 1h and +0.04R at 4h** just to break even.

Strategy names starting with F are DeepSeek (DS) definitions. All work files are in `scratchpad/lens/fiveyear/`.

### How it was compared

**5-year rerun** (scripts `fy36_rerun.py` and `fyds_rerun.py`)
- Every signal from 2021-08-01 to 2026-09-30 on 6 coins, Binance USD-M bars.
- Entry at the next bar's open plus 0.02% slippage; 2 x ATR14 stop; the paper-v3 ladder (`profiles._scan`, imported read-only); taker fee 0.05% each way; funding 0.01% per 8h.
- Leverage follows the paper-v4 "normal" group: 30x with 30% margin, falling back to 20x with 20%, at $5,000 equity, with all sizing checks. This is what about 90% of live v4 trades used.
- 8.1M signals in total. DeepSeek entries come from `lib_c.entries` with the same house exit, because the live ds200 accounts use house exits, not the PREREG exits.
- Parity check: a tier-walk mode reproduces `profiles.json` mean ROE in all 175 cells (largest difference 1e-8; `fy36_parity.csv`).

**Units**
- R = net pnl / (qty x |fill - 2 ATR stop|), the same definition as `trades_enriched` and `replay_signals`.
- ret = ROE / leverage (return per unit notional).
- "gross" = before fees, slippage and funding.

**Live samples** (script `live_cells.py`)
- v3b + v4: every-signal replay (TRADED), 2,078 core and 2,087 DS signals.
- v3a: entered trades plus nightly skipped shadows, 6,673 core signals. The skipped shadows only have ROE, so their leverage was rebuilt with the repo's own sizing. It matches 98.1% of v3a trades whose account equity was near $5,000.
- Standard errors are cluster-robust: run x 1h bucket for live, ISO week for the 5 years.

**Window test** (script `fy_compare.py`)
- 4,000 random contiguous 5-year windows with the live run lengths: 0.70 d + 1.50 d (v3b + v4) and 2.61 d (v3a).
- Real history keeps the clustering of signals, which a day-block bootstrap would break.
- "Matched" means windows whose mean stop size is within ±15% of the live mean stop size.

### 1. Per timeframe (`fy_tf_summary.csv`, `fy_tf_windows.csv`, `fy_freq_tf.csv`)

Column notes:
- **Signals/day** = all 5-year signals; "enterable" = signals that pass v4 sizing.
- **Freq ratio** = live signals per day / 5-year signals per day.
- **Net at today's stop size** = 5-year mean R of signals whose stop size falls within the live p10..p90 range.
- **Live R** = every-signal mean R (n, standard error). The 4h core figure falls to +0.068 when the 14 still-open signals are counted at mark price.
- **Window pct** = where the live mean falls among the 5-year windows; "matched" uses only stop-size-matched windows.
- **Stop-size pct** = where the live stop size falls among the 5-year windows.

| kind | tf | 5y signals/day (enterable) | freq ratio | 5y net R (t) | IS / CF | gross R | cost R | 5y net R at today's stop size | live R v3b+v4 (n, se) | live R v3a (n) | window pct v3b+v4 / v3a | matched pct | live stop-size pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| core | 5m | 1787 (1781) | 1.04 | -0.307 (-40) | -0.302 / -0.313 | +0.005 | 0.311 | -0.385 | — | -0.642 (4470) | — / 0.024 | 0.11 (v3a) | 0.06 |
| core | 15m | 605 (592) | 0.97 | -0.172 (-32) | -0.171 / -0.173 | +0.001 | 0.173 | -0.223 | -0.130 (1135, 0.098) | -0.321 (1394) | 0.64 / 0.08 | 0.89 / 0.34 | 0.04 |
| core | 30m | 304 (283) | 0.94 | -0.125 (-27) | -0.130 / -0.119 | -0.001 | 0.124 | -0.160 | -0.154 (560, 0.066) | -0.257 (557) | 0.38 / 0.07 | 0.67 / 0.20 | 0.04 |
| core | 1h | 153 (120) | 0.99 | -0.094 (-19) | -0.097 / -0.089 | 0.000 | 0.094 | -0.109 | -0.144 (355, 0.076) | -0.008 (225) | 0.32 / 0.77 | 0.52 / 0.84 | 0.03 |
| core | 4h | 37 (7.3) | 1.01 | -0.051 (-3.9) | -0.042 / -0.060 | +0.022 | 0.072 | -0.040 | +0.206 (28, 0.311) | +0.095 (27) | 0.81 / 0.74 | 0.83 / 0.79 | 0.23 |
| DS | 15m | 724 (709) | 1.08 | -0.177 (-41) | -0.175 / -0.179 | -0.004 | 0.173 | -0.236 | -0.065 (1120, 0.073) | — | 0.945 | 0.995 (p 0.009) | 0.02 |
| DS | 30m | 401 (373) | 1.03 | -0.128 (-38) | -0.130 / -0.125 | -0.004 | 0.124 | -0.169 | -0.132 (586, 0.062) | — | 0.46 | 0.87 | 0.02 |
| DS | 1h | 232 (184) | 1.05 | -0.099 (-29) | -0.102 / -0.095 | -0.006 | 0.093 | -0.120 | -0.112 (330, 0.057) | — | 0.43 | 0.64 | 0.02 |
| DS | 4h | 65 (12.8) | 1.29 | -0.066 (-7.5) | -0.068 / -0.064 | +0.006 | 0.072 | -0.078 | -0.122 (51, 0.198) | — | 0.38 | 0.37 | 0.15 |

How to read this table:
- The gross edge is between -0.006 and +0.022R everywhere, and both 5-year halves agree. Net R is therefore just the cost.
- Live is inside the 5-year window range everywhere except v3a 5m (percentile 0.024, p 0.049), which the quiet market explains (matched p 0.21).
- DS 15m was better than the quiet-market expectation (matched percentile 0.995, p 0.009). After correcting for the 13 timeframe-level tests (BH), q is about 0.12, so this is not significant.
- At cell level, no cell survives BH correction (q < 0.05) among 244 v3b+v4 and 164 v3a tested cells. Raw p < 0.05 in 20 of 244 and 15 of 164.
- Live signal counts match: cell-level log frequencies correlate 0.91 and 92% of cells are within 0.5–2x.

### 2. Cost depends on stop size; gross does not (`fy_volbucket.csv`)

Core 15m over 5 years, by stop-size quintile:

| quintile | stop size (% of price) | net R | gross R | cost R | win % |
|---|---|---|---|---|---|
| 1 | 0.06–0.63 | -0.331 | +0.004 | 0.335 | 42.6 |
| 2 | 0.63–0.86 | -0.185 | +0.008 | 0.194 | 54.0 |
| 3 | 0.86–1.10 | -0.151 | -0.004 | 0.147 | 58.3 |
| 4 | 1.10–1.47 | -0.112 | +0.001 | 0.113 | 61.9 |
| 5 | 1.47–3.02 | -0.079 | -0.002 | 0.077 | 64.4 |

The live 15m median stop is 0.63%, right at the quintile 1/2 boundary. At 1h, quintile 1 (stop 1.27% or less) gives net -0.148R and quintile 5 gives -0.069R; the live 1h median stop is 1.23%. The pattern holds at every timeframe and for both kinds: gross is about 0 in every quintile, and only the cost changes.

### 3. Does live agree with the 5 years, cell by cell?

- **Sign.** The 5-year mean is negative in every cell with live n ≥ 10. Live is positive in 11 of 49 core cells. That matches the 10.4 expected if the 5-year mean at today's stop size were the truth and live noise equalled its cluster SE. In DS, 26 of 68 cells are positive against 16.2 expected; the excess is a good 1.5 days at 15m. The z-score (live minus 5-year, over live SE) has sd 1.23 (core) and 1.29 (DS). |z| > 2 in 3 of 49 and 4 of 68 cells.
- **Rank (Spearman, cells with live n ≥ 10).**
  - 5-year vs live: core -0.10 (49 cells, permutation p 0.52); 15m+30m -0.15 (p 0.38); 1h+4h +0.03; DS -0.11 (68 cells, p 0.38).
  - Live v3a vs live v3b+v4 on the same cells: -0.11 (41 cells, p 0.48). The live runs do not even agree with each other.
- **Inside the 5 years (IS 2021-24 → CF 2024-26).** Net-R rank persistence: core 15m +0.42 (p 0.018), 30m +0.33 (p 0.066), 1h -0.09; DS 15m +0.61 (p < 0.001), 30m +0.35 (p 0.018), 4h +0.52 (p 0.023). Gross-R persistence is weaker: core 15m +0.28 (p 0.12), DS 15m +0.48 (p 0.002). The persistent part mostly reflects cost structure (which strategies fire when stops are wide). The differences between cells are only about 0.01–0.03R gross. Only one cell with at least 200 signals in each half is net-positive in both halves: N23_HA_ST@4h.
- **Significant gross edge** (BH over 307 cells with n ≥ 200): two cells.
  - DS F16_FIB382@15m: gross +0.026R (t 4.0, q 0.009), but net -0.142R.
  - N23_HA_ST@4h: gross +0.099R (t 3.7, q 0.017).

### 4. 5-year best vs live, and live best vs 5-year (`fy_top_lists.csv`)

| cell | live v3b+v4 R (n) | live v3a R (n) | 5y net R | 5y gross R |
|---|---|---|---|---|
| S4_BB_BBP@15m | +0.42 (39) | -0.25 (56) | -0.202 | -0.013 |
| N20_EMA9_CHOP@30m | +0.26 (42) | -0.42 (14) | -0.150 | -0.011 |
| N20_EMA9_CHOP@1h | +0.29 ±0.10 (17) | -0.82 (5) | -0.097 | +0.007 |
| N17_KC_RSI@15m | +0.11 (109) | -0.55 (161) | -0.160 | -0.021 (t -3.4) |
| N01_ST_EMA@15m | +0.16 (30) | -0.47 (42) | -0.173 | +0.011 |
| F1_RSI_DIV@15m (DS) | +0.45 (18) | — | -0.183 | -0.015 |
| N18_VWMA_MACD@30m (live worst) | -0.79 (39; window p 0.007, q 0.24) | -0.03 (43) | -0.113 | +0.012 |

The cells that are least bad over 5 years at 1h/4h have essentially no live data: N23_HA_ST@4h, N02_ST_KST@4h, N09_ALLIG_AROON@4h and N03_ADX_GC@1h have live n of 0–1. All 3 of N23's v3b/v4 signals were DOGE signals, and v4 sizing rejected them (stop too close to the liquidation price).

### 5. Leverage and exits

From `research/levstop`: fixed leverage, 2 ATR stop, every 5-year signal (`fy_levstop_arms.csv`).

| tf | leverage | return per notional | equity change per trade | liquidated share | busted accounts / 70 |
|---|---|---|---|---|---|
| 15m | 10x | -0.141% | -0.28% | 0.004% | 47 |
| 15m | 30x | -0.142% | -1.28% | 0.48% | 61 |
| 15m | 50x | -0.159% | -3.18% | 4.8% | 64 |
| 1h | 10x | -0.157% | -0.31% | 0.04% | 12 |
| 1h | 30x | -0.174% | -1.57% | 4.7% | 57 |
| 1h | 50x | -0.224% | -4.48% | 19.2% | 62 |
| 4h | 30x | -0.242% | -2.18% | 17.9% | 47 |
| 4h | 50x | -0.288% | -5.76% | 33.9% | 57 |

- Leverage multiplies the loss but not the per-notional result. With no edge, 30x/30% at 15m halves equity in about 54 trades; 50x/50% does it in about 19 (`fy_equity_drain.csv`).
- In `research/exitstyle`, changing the exit style (ladder, fixed TP at 1R–3R, ladder with a 2R cap) moves results by at most about 0.06% of equity per trade, and none passes its pre-registered rule.
- The 5-year data does not support the live "lev10 +0.26R" what-if: at 15m, 10x and 30x give the same return per notional.

### 6. DeepSeek and reel

- **DeepSeek, house vs pre-registered exits** (`fy_ds_prereg_vs_house.csv`). Mean net % per trade, house / X5_TRAIL2 / X2_SL15_TP3:
  - 15m: -0.149 / -0.151 / -0.142
  - 30m: -0.152 / -0.167 / -0.147
  - 1h: -0.160 / -0.175 / -0.159
  - 4h: -0.189 / -0.211 / -0.172

  At 15m the cell rankings agree across exits (Spearman 0.47 and 0.70). No DS cell is positive in both 5-year halves at 15m/30m/1h. The two PREREG stage-1 passes (F5_BOX@4h with X2, F13_FVG_PD@4h with X5) failed stage 2.
- **Reel 5m** (`fy_reel.csv`).
  - 5 years: 19.0 trades/day, net -0.125% per trade, gross before costs +0.011% (IS) / +0.007% (CF), net -0.55R per trade.
  - Live: 18.0 signals/day; 13 trades at -0.46R; all 27 signals (including skipped shadows) average -0.156% per trade, at percentile 0.44 of the 5-year 1.5-day windows.
  - Live is exactly what the 5-year study predicted. Drop it as an AI candidate.

### 7. Combined grade (`fiveyear_vs_live.csv`, 351 cells)

**5-year class** (house exits, v4 normal leverage):

| class | meaning |
|---|---|
| P | net mean R > 0 in both halves |
| Z+ | not P; net t > -2; gross > 0 |
| Z- | not P; net t > -2; gross ≤ 0 |
| N+ | net t ≤ -2; gross > 0 |
| NN | net t ≤ -2; gross ≤ 0 |
| thin | fewer than 30 sized signals |

**Live class** (every-signal sample: v3b+v4 for 15m..4h, v3a for 5m):

| class | meaning |
|---|---|
| L++ | mean - 2 SE > 0 |
| L+ | mean > 0 |
| L- | mean ≤ 0 |
| L-- | mean + 2 SE < 0 |
| L_thin | n < 15 |

**Grade rules:**

| grade | combinations |
|---|---|
| A | P with L+/L++ |
| B | P with L-/thin; Z+ with L+/L++ |
| C | P with L--; Z+ with L-/thin; N+ with L+/L++; Z- with L+/L++ |
| D | Z+ with L--; Z- with L-/thin; N+ with L-/thin; NN with L+/L++ |
| F | N+ with L--; Z- with L--; NN with L-/L--/thin |

| kind | tf | B | C | D | F | thin |
|---|---|---|---|---|---|---|
| core | 5m | 0 | 0 | 3 | 31 | 2 |
| core | 15m | 0 | 3 | 19 | 12 | 2 |
| core | 30m | 0 | 3 | 18 | 13 | 2 |
| core | 1h | 1 | 5 | 19 | 8 | 3 |
| core | 4h | 1 | 18 | 3 | 5 | 9 |
| DS | 15m | 0 | 3 | 19 | 22 | 0 |
| DS | 30m | 0 | 2 | 14 | 28 | 0 |
| DS | 1h | 0 | 2 | 18 | 24 | 0 |
| DS | 4h | 1 | 18 | 4 | 15 | 1 |

There is no A anywhere. Most C grades at 4h come from low statistical power, not from positive evidence.

### 8. Strongest combined candidates (`fy_candidates.csv`)

These are the best of a losing set. All of them lose money over 5 years.

**15m/30m**: 5-year net loss after costs, gross ≥ 0, live ≥ 0, and at least 9 enterable signals/day.

| cell | 5y net R (t) | 5y gross R (IS / CF) | 5y net R at today's stop size | enterable signals/day | live n, R ± SE |
|---|---|---|---|---|---|
| DS F7_RF_TRIPLE@30m | -0.108 (-16) | +0.012 (+0.013 / +0.012), t 2.0 | -0.138 | 30.4 | 40, +0.08 ± 0.32 |
| N24_DMI@30m | -0.125 (-13) | +0.005 (-0.002 / +0.013) | -0.148 | 10.7 | 33, +0.07 ± 0.16 |
| DS F12_MSS@30m | -0.122 (-16) | +0.003 | -0.147 | 9.3 | 15, +0.35 ± 0.33 |
| DS F9_IFVG@15m | -0.157 (-20) | +0.016 (+0.006 / +0.026), t 2.55 | -0.216 | 11.9 | 26, +0.06 ± 0.20 |
| N01_ST_EMA@15m | -0.173 (-18) | +0.011 (+0.008 / +0.016) | -0.227 | 17.1 | 30, +0.16 ± 0.47 (v3a -0.47) |
| N10_HA_PSAR@15m | -0.174 (-27) | +0.002 | -0.212 | 24.0 | 44, +0.07 ± 0.22 (v3a -0.13) |
| DS F7_RF_TRIPLE@15m | -0.162 (-26) | +0.006 | -0.222 | 63.2 | 84, +0.07 ± 0.21 |
| DS F6_VWAP_CROSS@15m | -0.174 (-34) | +0.005 | -0.225 | 59.2 | 85, +0.04 ± 0.24 |

The strongest 5-year gross edges at 15m, though graded D because live is negative or thin: F16_FIB382 (+0.026, q 0.009; live -0.40, n 18), F16_FIB500 (+0.022), N02_ST_KST (+0.019, t 2.4).

**1h/4h**

| cell | grade | 5y net R | 5y gross R | enterable signals/day | live |
|---|---|---|---|---|---|
| N23_HA_ST@4h | B | +0.027 (t 0.98; IS +0.011 / CF +0.042; last 12 months +0.059) | +0.099 (t 3.7, q 0.017) | 0.75 | v3a 4 trades +0.29; 3 v4 signals rejected by sizing |
| N22_VORTEX_PSAR@4h | C | -0.009 | +0.064 (t 2.4, both halves) | 0.5 | 4 signals, +0.51 |
| N02_ST_KST@4h | C | +0.010 | +0.081 (t 2.1) | 0.2 | 0 |
| S2_ST_ROC@4h | C | -0.027 | +0.048 | 0.7 | 1 |
| N24_DMI@1h | C | -0.078 | +0.018 | 4.6 | 19, +0.06 ± 0.18 |
| N20_EMA9_CHOP@1h | C | -0.097 | +0.007 | 4.7 | 17, +0.29 ± 0.10 (v3a -0.82, n 5) |
| DS F6_VWAP_CROSS@1h | C | -0.091 | +0.004 | 20.7 | 34, +0.15 ± 0.13 |
| DS F2_DEMARK@4h | C | -0.037 | +0.035 | 1.3 | 9, +0.25 |
| DS F15_ORB@4h | C | -0.031 | +0.041 | 0.9 | 1 |

### 9. What this means for the AI traders

1. **Do not choose strategies from live P&L.** The live best cells flip sign between runs and are clearly negative over 5 years. If AI traders must be assigned, use the 15m/30m list above. Their direction content is at least not negative and they give the AI many chances to skip.
2. **Judge each AI trader against its own strategy at the same moments.** Compare the AI's decisions with the replay of the same rule signals, with cluster-robust SEs. At today's stop sizes the null hypothesis is about -0.15 to -0.23R per trade at 15m/30m. Detecting a +0.2R improvement needs about 110–280 independent trades.
3. **Keep leverage at 20–30x with the current sizing checks** until the AI shows an edge. Higher leverage only multiplies the loss to equity. Never use 50x with 2 ATR stops on 1h/4h.
4. **Exit and custom-value tuning will not create the missing edge.** Expect at most about 0.05R from it.
5. **Keep 4h as cost-free rule accounts and judge them on 5-year-sized samples.** Consider giving one AI trader 1h entries, where the cost hurdle is about half that of 15m.
