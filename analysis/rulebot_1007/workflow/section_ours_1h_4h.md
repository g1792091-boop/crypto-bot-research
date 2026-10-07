## Our 36 strategies at 1h and 4h: rule accounts and the AI's view timeframes

**Scope and method.** We built one evidence card per strategy x timeframe for 1h and 4h (72 cells; file `lens/ours_1h_4h/cards_1h_4h.csv`, 120 columns). Each card combines six sources:

- **Account trades per run:** v3a, v3b and v4 (`account_stats.csv`).
- **Every-signal outcomes:** every submitted signal, not only the trades an account took.
  - v3a: entered trades, plus nightly skipped shadows converted to R with the rebuilt tier-walk leverage.
  - v3b and v4: every submitted signal replayed alone on live_bars.
  - The 95% CI is a cluster bootstrap over run x 4-hour blocks.
- **Side-flip test:** the strategy's chosen side against the opposite side at the same moments.
- **The old 5-year reference profiles:** tier-walk leverage, results in ROE.
- **A new 5-year every-signal simulation under today's live rules** (`fy_sim.py`). It covers 36 strategies x 6 coins x 15m/30m/1h/4h from 2021-08 to 2026-09, 2.07M signals, with quality_v1 leverage (30x, else 20x), the 2 ATR stop, the ROE ladder and real costs. Results are in R, split into IS (2021-08..2024-06) and CF (2024-07..2026-09). Standard errors are clustered by UTC day.
- **Practical fields:** signals per day, sizing rejections per coin, and cost as a share of the stop.

Two further 5-year studies test whether 15m/30m signals do better when they agree with the 1h/4h state, and how exit and leverage custom values change results. The same agreement test was then run on the three live runs as an out-of-sample check.

### 1. Is the edge at 1h/4h? No. The higher timeframes only lose less.

| tf | live every-signal mean R [95% CI] (n) | live accounts mean R (n) | 5-year net R [95% CI] | 5-year gross R [95% CI] | 5-year cost in R | live median cost in R |
|---|---|---|---|---|---|---|
| 15m | -0.235 [-0.373, -0.072] (2,529) | -0.190 (630) | -0.172 [-0.180, -0.165] | -0.003 [-0.009, +0.004] | 0.169 | 0.224 |
| 30m | -0.205 [-0.293, -0.109] (1,117) | -0.152 (378) | -0.126 [-0.133, -0.118] | -0.006 [-0.013, +0.001] | 0.120 | 0.158 |
| 1h | -0.091 [-0.219, +0.051] (580) | -0.073 (212) | -0.094 [-0.103, -0.086] | -0.005 [-0.014, +0.003] | 0.089 | 0.113 |
| 4h | +0.151 [-0.161, +0.456] (55) | +0.144 (31) | -0.051 [-0.073, -0.029] | +0.011 [-0.011, +0.033] | 0.062 | 0.070 |

Sources: `tf_summary_live.csv`, `tf_summary_5y.csv`, rb_analyze `kind_tf_summary` and `cost_by_tf`.

- **Gross R is zero at every timeframe.** The ranking 15m < 30m < 1h < 4h is the ranking of cost as a share of the stop. The signals are no better at higher timeframes.
- **The live 1h figure is not stable across runs:** v3a -0.008, v3b -0.373, v4 -0.052.
- **The live 4h mean is inflated by censoring** (trades still open at run end are left out). In v4, 26 traded signals average +0.198, but 11 more were still open at the end, marked at -0.207. Including them gives +0.078. In v3b, +0.301 becomes -0.008.
- **Direction skill is absent.** The side-flip test against a coin flip gives 1h excess -0.024R (338 pairs, p 0.64) and 4h +0.127R (28 pairs, 9 clusters, p 0.36). Of 20 testable cells, one has raw p < 0.05: N20_EMA9_CHOP 1h, BH q 0.52.

### 2. Tradability: 4h is mostly blocked, and 20-50x does not fit 1h/4h

Share of signals whose 2 ATR stop sits at least 1 ATR inside liquidation (`lev_feasibility.csv`):

| tf | 5y >=50x | 5y >=40x | 5y >=30x | 5y >=20x | live >=50x | live >=40x | live >=30x | live >=20x |
|---|---|---|---|---|---|---|---|---|
| 15m | 7.4% | 35.7% | 81.1% | 97.6% | 28.3% | 74.6% | 99.0% | 100% |
| 30m | 2.2% | 13.5% | 56.7% | 92.4% | 11.1% | 41.9% | 93.3% | 100% |
| 1h | 0.4% | 3.6% | 26.9% | 77.4% | 1.7% | 9.2% | 68.2% | 98.6% |
| 4h | 0% | 0% | 1.1% | 19.3% | 0% | 0% | 2.8% | 46.1% |

- **Live 4h rejections by coin.** In v3b and v4, all 39 BCH/DOGE/LTC 4h signals were rejected for "stop too close to liquidation". The 28 traded 4h signals were BTC 3, ETH 12 and SOL 13, all at 20x.
- **Five-year 4h sizable share at 20x by coin:** BTC 55%, ETH 26%, SOL 4%, DOGE 8%, LTC 13%, BCH 9%.
- **Account-level rejections for our 36:** v3a 4h 35, v3a 1h 8, v3b 4h 8, v4 4h 12.
- **Volume:** across all 36 strategies, 5 years produced 118 sized 1h signals and 7.2 sized 4h signals per day.
- **Implication for the AI design:** with a 2 ATR code stop, "20-50x by confidence" is mostly cut down by sizing. At 15m, 50x fits 7% of signals (5-year) to 28% (this quiet market). At 1h/4h nothing above 30x/20x fits.

### 3. Grades for the 72 cells

| grade | rule | 1h | 4h |
|---|---|---|---|
| A | 5-year net t >= 2 in IS and CF and live every-signal CI > 0 | 0 | 0 |
| B | 5-year gross t >= 2 in IS and CF, net > -0.05, live not contradicting | 0 | 0 (N23_HA_ST borderline) |
| C | no directional edge; net is about minus the cost | 26 | 21 |
| D | 5-year net t <= -2 with gross <= -0.02, or live CI < 0 | 6 | 2 |
| U | < 100 sized 5-year signals and < 10 live outcomes | 4 | 13 |

The 1h/4h cells with the strongest 5-year gross evidence (`cards_1h_4h.csv`):

| strategy | tf | 5y sized n | sized/day | net R (t) | gross R (t) | IS gross | CF gross | BH q (72 cells) | live every-signal n, R |
|---|---|---|---|---|---|---|---|---|---|
| N23_HA_ST | 4h | 1383 | 0.73 | +0.024 (1.08) | +0.086 (3.84) | +0.069 (t 2.00) | +0.103 (t 3.62) | 0.004 | 4, +0.287 |
| N22_VORTEX_PSAR | 4h | 945 | 0.50 | -0.002 (-0.06) | +0.061 (2.33) | +0.055 | +0.067 | 0.32 | 5, +0.188 |
| DOGE | 1h | 4157 | 2.20 | -0.056 (-3.72) | +0.023 (1.55) | +0.022 | +0.024 | 0.72 | 8, -0.407 (graded D) |
| N02_ST_KST | 4h | 353 | 0.19 | -0.010 (-0.27) | +0.052 (1.46) | +0.035 | +0.070 | 0.72 | 0 |
| N05_PSAR_POC | 1h | 1592 | 0.84 | -0.064 (-3.25) | +0.028 (1.44) | -0.001 | +0.061 | 0.72 | 3, +0.372 |
| N13_3OUTSIDE | 1h | 1789 | 0.95 | -0.061 (-3.01) | +0.029 (1.43) | +0.016 | +0.040 | 0.72 | 8, +0.232 |

Negative (D) cells:
- DOGE 1h and N04_ST_KLINGER 1h, on the live every-signal CI. N04_ST_KLINGER 1h: -0.233 [-0.41, -0.04], n 57.
- N17_KC_RSI at 1h and 4h. This mean-reversion strategy loses before costs: gross -0.048 (t -4.0) at 1h and -0.088 (t -2.9) at 4h, in both halves.
- N16_BBRSI 1h, S3_CMO_SANDWICH 1h, S5_DONCHIAN_MFI 1h and OBV_B 4h.

Silent cells: N14_ICHI_RSI, N15_KC_AO, N21_ST_RSI_ADX and S1_EMA_RSI_CHOP have almost no 1h/4h signals in 5 years.

### 4. Which strategies are better on 1h/4h than on 15m/30m?

- **5 years, net:** 44 of 66 strategy comparisons are significantly better at the higher timeframe after BH (`fy_tfcompare.csv`). This is the cost effect.
- **5 years, gross (cost added back):** only N23_HA_ST 4h is better: +0.086R against its pooled 15m/30m, t 3.86, BH q 0.007, IS +0.075, CF +0.095.
  - Runner-up: N22_VORTEX_PSAR 4h, +0.062 (t 2.35, q 0.43).
  - Worse at higher timeframes before costs: N17_KC_RSI, 1h -0.022 (t -2.34) and 4h -0.062 (t -2.08).
- **Live:** 9 of 35 cells show a positive higher-minus-lower difference with CI > 0, but 8 of them rest on 3-4 clusters and n <= 5 at the higher timeframe. The only well-clustered case is N25_DST_CCI 1h: -0.038 (n 31) against 15m -0.528 (n 116) and 30m -0.337 (n 55), consistent with lower cost. It is not corrected for multiple testing.

### 5. Does a 15m/30m signal do better when it agrees with 1h/4h? Slightly, and it still loses

**5-year test.** Each definition is pre-specified. The contrast is agree minus against within strategy x timeframe, with SE clustered by day. Each cell gives IS, then CF (t in brackets). Source: `fy_htf_pooled.csv`.

| state | 15m: agree - against | 30m: agree - against | 15m: agree - no state |
|---|---|---|---|
| market 1h regime (ctx htf_regime definition) | +0.079 (1.7) / +0.046 (0.8) | +0.100 (1.8) / -0.001 (0.0) | +0.069 / +0.064 |
| market 4h regime | +0.090 (2.0) / +0.067 (1.5) | +0.083 (1.3) / +0.050 (1.0) | +0.062 / +0.075 |
| market 1h EMA20 side | +0.024 (2.2) / +0.016 (1.2) | +0.020 (1.6) / +0.016 (1.2) | n/a |
| market 4h EMA20 side | +0.018 (1.5) / +0.016 (1.1) | +0.008 (0.6) / +0.025 (1.6) | n/a |
| market 4-bar momentum, 1h / 4h | -0.001 / +0.005; +0.018 / +0.015 | +0.011 / +0.006; +0.012 / +0.018 | ~0 |
| same strategy 1h signal in the last 4h | +0.013 (1.0) / +0.012 (0.9) | +0.011 (0.8) / +0.003 (0.2) | +0.013 / +0.012 |
| same strategy 4h signal in the last 16h | +0.027 (2.2) / +0.020 (1.3) | +0.011 (0.8) / +0.016 (0.9) | +0.018 / +0.016 |
| same strategy 1h position open | +0.030 (1.7) / +0.025 (1.4) | +0.032 (1.8) / +0.018 (0.9) | **-0.057 (-5.5) / -0.036 (-3.4)** |
| same strategy 4h position open | +0.053 (1.4) / +0.092 (2.6) | +0.040 (1.0) / +0.037 (0.9) | **-0.182 (-6.1) / -0.078 (-3.1)** |

- **Agreement helps a little and consistently.** 18 of 20 IS/CF pairs have the same sign. The size is +0.01 to +0.09R, and no definition reaches t > 2 in both halves.
- **The agree groups still lose.** At 15m, mean R when agreeing with the 4h regime is -0.110 (IS) and -0.100 (CF), and only about 3% of signals have a trend label at all. At 15m, agreeing with the same strategy's 4h signal gives -0.153 / -0.159.
- **The best combined case still loses.** Signals where at least 3 of 5 HTF states agree (exploratory score, 15% of signals; `fy_htf_score_buckets.csv`) score -0.132 / -0.149 at 15m and -0.111 / -0.096 at 30m.
- **Piling on is worse than a clean entry.** A same-direction 1h/4h position already open is worse than no HTF position, by -0.04 to -0.18R with t from -2.3 to -6.7, in both halves.
- **No strategy-specific HTF effect holds up.** With at least 30 signals in both the agree and against groups, 505 strategy x timeframe x definition cells were tested. BH leaves 2 in IS, and neither replicates in CF at t > 2. IS-versus-CF correlations of the per-strategy effects range from -0.66 to +0.36 (`fy_htf_by_strategy_min30.csv`).

**Live check (out of sample).** Sources: `live_htf_contrasts.csv` and `live_htf_groups.csv`.

| state | pooled agree - against [95% CI] | agree mean R | against mean R | v3a | v3b | v4 |
|---|---|---|---|---|---|---|
| ctx htf_regime | untestable: 56 of 3,646 signals had a trend label, v4 had 0 | | | | | |
| same strategy 1h signal | +0.23 [+0.005, +0.50] | -0.165 (576) | -0.372 (293) | +0.48 | +0.15 | +0.13 |
| same strategy 4h signal | +0.28 [-0.05, +0.56] | -0.001 (386) | -0.307 (226) | +0.62 | -0.56 | -0.31 |
| 1h rule-account position | +0.38 [-0.04, +0.86] | -0.057 (222) | -0.594 (141) | +0.45 | -0.65 | +1.05 |
| market 1h momentum (4h) | +0.15 [-0.08, +0.42] | -0.150 (1908) | -0.343 (1336) | +0.11 | +0.02 | +0.19 |
| market 4h momentum (16h) | +0.50 [+0.06, +1.00] | +0.007 (1290) | -0.547 (770) | +0.57 | n/a | +0.20 |

- **The signs mostly match the 5-year result, but the sizes are 5-20x larger.** The estimates flip between runs: the same-strategy 4h signal is negative in v3b and v4.
- **The agree groups are about zero or below in every run.** The one exception is 4h momentum in v4 (+0.303, n 376), which was 33% long in a falling market.
- **Conclusion:** live data cannot confirm or refute an effect of about 0.02R.

### 6. Custom values and exits at 1h/4h (5 years, paired on the same signals)

Each cell is the change in mean R versus base, with t in brackets. Source: `fy_exits.csv`; base reproduces fy_sim for 100% of signals.

| tf | lev10 | lock20 | lock30 | ladder in R units | tp1R | tp2R | time stop (64 bars) |
|---|---|---|---|---|---|---|---|
| 1h | +0.011 (2.3) | +0.003 (1.2) | +0.006 (1.4) | +0.002 (0.8) | -0.002 (-0.5) | +0.006 (0.6) | +0.000 |
| 4h | +0.009 (1.0) | +0.001 (0.1) | -0.004 (-0.4) | +0.006 (0.6) | -0.014 (-1.0) | +0.030 (1.1) | 0 |

- **No custom value creates an edge.** Base mean R is -0.094 at 1h and -0.051 at 4h, and the changes above are a few hundredths of R at most.
- **The nightly live what-ifs overstate the gains.** At 1h they showed lev10 +0.216R and lock30 +0.179R, built on pairs that are partly unresolved and biased. Five years support only about +0.01R from 10x leverage, which puts the ROE ladder further away in price.

### 7. What this means for the AI-trader plan

1. **Do not give any 1h/4h strategy an AI slot because of 1h/4h results.** No cell shows a live or 5-year edge. 1h/4h only lose less, because cost takes less of the stop.
2. **The AI's 1h/4h view is at best a small loss reducer.**
   - Vetoing entries against the 1h/4h state is worth about +0.02 to +0.08R relative, which is far below the 0.12-0.17R cost of 15m/30m.
   - Treating an already-open same-direction 1h/4h rule position as confirmation is harmful: it marks a late entry.
3. **Fix leverage by timeframe and by the stop rule before going live.**
   - 50x with a 2 ATR stop fits only 7-28% of 15m signals and almost no 30m/1h/4h signals.
   - 4h rule accounts are BTC/ETH accounts in practice.
4. **Keep 1h/4h as cost-free rule accounts. Watch one line: N23_HA_ST 4h.** It has a gross +0.09R that survives BH in both halves, but net is about 0, it trades about 0.7 times a day, and live n is 4.
   - N22_VORTEX_PSAR 4h is the runner-up.
   - N17_KC_RSI, N04_ST_KLINGER 1h and the other D cells can be ignored.
5. **Nothing at 1h/4h can be verified by 12/31.** Detecting ±0.05R needs about 1,500-1,700 trades per cell. November promotions from 1h/4h accounts would rest on noise.
