## Exits, stop width, leverage and the profit-lock ladder: which custom values help

### Summary

The house exit is not why 15m and 30m lose money. On every signal, the result before costs is about zero, and the round-trip cost (0.17R at 15m, 0.12R at 30m) is the loss. Here 1R = the planned loss at the 2 ATR stop.

The reported gains for 10x leverage (+0.26R) and a later first lock at 30% ROE (+0.14R) are not robust custom values. Both work by arming the profit lock later. That paid in one trending window and lost in the next run: at 15m, +0.46R in v3a, -0.23R in v3b, +0.17R in v4. The nightly shadow tables also understate the wide exits, because they drop trades that were still open.

Choosing a different exit per strategy from recent data lost 0.02-0.21R per trade out-of-sample.

What survives across runs:
- Fixed 1-2R take-profits are worse than the house ladder at 15m.
- Time stops do not help.
- A 2.5-3 ATR stop is worse than 2 ATR at the same size.
- Breakeven helps only from +1R.
- Raising the lock only at bar close is slightly better at 15m/30m.
- At 1h the house ladder is clearly too tight. This is the only change consistent across 3 live runs and the 5-year study.

Leverage changes R only through the profit-lock ladder. As size, 40-50x is either refused by the 15% loss cap or risks 12-25% of equity per stop.

Recommendation: exits and stops must be computed in price/R terms and must not depend on leverage. Freeze one exit per strategy family for the whole test. Run the candidate exits as shadows.

### Data and method

- **What was simulated.** Every submitted signal of the house-exit accounts (36 core strategies, DeepSeek, coin flips) at 15m/30m/1h/4h in v3b and v4: 4,748 signals, each run alone through the repo's own `PaperEngine` on the 1m `live_bars`. 39 exits, plus the same signal with the side flipped (a coin flip at the same moment): 362,592 runs.
- **Horizon.** v3b's bars were extended with v4's bars, so v3b signals have at least 36 h. Positions open at 10/07 15:40 KST are marked to market with exit costs (status OPEN_END). Every exit is therefore evaluated on the same set of signals.
- **Validation.**
  - The base matches the rb_analyze replay exactly: 4,236 signals, max |dROE| 2.2e-16.
  - Every resolved nightly shadow row on v4 trades is reproduced exactly: 18 variants, median |dROE| 0.
  - Files: `validate.txt`, `validate_vs_d3.csv`.
- **Units.** R is in units of the base 2 ATR stop: pnl / (qty × |entry − base stop|). "pe" = pnl as % of a fresh $5,000 account; an entry refused by sizing counts as 0.
- **Statistics.** CIs are cluster bootstraps over 1 h blocks of signal time (all coins together), with 4 h blocks as a check. BH correction across the pooled variant × timeframe tests.
- **v3a.** It has no live_bars, so it is shown only from the nightly shadows. Those cover entered trades only, drop unresolved rows, and the base was mostly 50x.
- **Exit names used below.**
  - `geoL`: the house ladder computed as if leverage were L, at the real size.
  - `RLa_b`: R ladder; lock +b R once the best excursion (MFE) reaches +a R, then raise in steps.
  - `_bar`: the lock is raised only when the strategy's bar closes.
  - `be1_*`: breakeven at +1R.
  - `timestop`: market exit after N bars if the lock never armed.
  - `time_neg`: exit at N bars if losing.
  - `max2x`: hard exit after 2N bars.
  - `stopwk`: stop at k ATR.
  - `tpkR`: fixed take-profit at k R, no ladder.

### 1. Is the house exit the loss source? No.

Every signal, v3b + v4 pooled (`exitlab_paired.csv`, `exitlab_base_levels.csv`):

| tf | n | net R | gross R | cost R | win % | avg win R | avg loss R | payoff | breakeven win % | mean R over the 34 exits (range) | best exit in hindsight v3b / v4 | flipped side net R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15m | 2,477 | -0.106 | +0.062 | 0.168 | 52.6 | +0.87 | -1.19 | 0.73 | 57.8 | -0.225 (tp1.5R) to +0.059 (RL2_1) | be0.5_tp1 -0.289 / RL2_1 +0.200 | -0.193 |
| 30m | 1,277 | -0.147 | -0.030 | 0.117 | 57.6 | +0.56 | -1.10 | 0.51 | 66.4 | -0.222 (tp2R) to -0.043 (RL1.5_1_bar) | geo50 -0.159 / RL1.5_1_bar +0.030 | -0.103 |
| 1h | 780 | -0.136 | -0.053 | 0.083 | 61.0 | +0.41 | -0.99 | 0.41 | 70.7 | -0.171 (timestop) to +0.180 (be1_tp3) | tp3R +0.070 / be1_tp3 +0.269 | -0.121 |
| 4h | 112 | -0.044 | +0.001 | 0.046 | 56.2 | +0.50 | -0.74 | 0.67 | 59.8 | (mostly open, marked) | n/a | +0.037 |

- **A stop-out costs about 1.19R at 15m, not 1R.** The extra is costs plus stop slippage.
- **The ladder's winners are small, and smallest on higher timeframes:** +0.87R at 15m, +0.41R at 1h. Breakeven therefore needs 58-71% winners.
- **Even the best exit in hindsight loses in v3b at 15m/30m.** The best exit flips between "tight" (v3b) and "wide" (v4).
- **No exit has a positive expectation without edge.** Under no edge every exit has expected gross R ≈ 0, and the coin-flip side loses about as much.

### 2. Why the ROE ladder rewarded 10x and a 30% first lock

The ladder locks net ROE. Its first trigger is at a price move of 0.12/L + 0.14%, so it shrinks with leverage L and ignores volatility (ATR). In R of the live 2 ATR stop (`lev_risk.csv`, medians over v3b+v4 signals):

| tf | median stop | trigger R at 10x / 20x / 30x / 50x | first lock at 30x | trail gap after arming at 30x |
|---|---|---|---|---|
| 15m | 0.62% | 2.16 / 1.19 / 0.87 / 0.61 | 0.76R | 0.11-0.38R |
| 30m | 0.89% | 1.51 / 0.84 / 0.61 / 0.43 | 0.53R | 0.08-0.26R |
| 1h | 1.25% | 1.07 / 0.59 / 0.43 / 0.30 | 0.38R | 0.05-0.19R |
| 4h (20x) | 2.02% | 0.67 / 0.37 / 0.27 / 0.19 | 0.32R at 20x | 0.05-0.17R at 20x |

- **Costs eat the high-leverage trigger.** The 0.14% round trip is 37% of the 50x trigger distance and 10% of the 10x one.
- **At high leverage the ladder is a very tight trail.** Once armed it follows the price within 0.1-0.4R on 15m and within 0.05-0.2R on 1h.
- **lev10 and lock30 are the same lever: arm later.** In R, `lev10` equals `geo10` and `lev20m20` equals `geo20` in every run and timeframe; at 10-30x leverage acts only through this geometry. `lock30` at 30x arms at about 2R on 15m.
- **The sign depends on the run** (difference vs the house exit, R):

| tf | variant | v3a (shadows, base mostly 50x) | v3b (re-run) | v4 (re-run) | pooled v3b+v4 [95% CI] | BH q | flipped side |
|---|---|---|---|---|---|---|---|
| 15m | lev10 = geo10 | +0.460 (n 296) | -0.230 | +0.167 | +0.101 [-0.075, 0.286] | 0.47 | +0.180 |
| 15m | lock30 | +0.210 | -0.233 | +0.008 | -0.031 [-0.148, 0.086] | 0.73 | +0.073 |
| 30m | lev10 = geo10 | +0.367 | -0.045 | +0.075 | +0.056 [-0.088, 0.195] | 0.57 | +0.219 |
| 30m | lock30 | +0.184 | -0.042 | +0.017 | +0.007 [-0.096, 0.102] | 0.92 | +0.123 |
| 1h | lev10 = geo10 | +0.298 | +0.145 | +0.132 | +0.134 [0.001, 0.272] | 0.21 | +0.223 |
| 1h | lock30 | +0.249 | -0.032 | +0.000 | -0.004 [-0.101, 0.087] | 0.94 | +0.091 |

- **Where the headline came from.** The "+0.26R" was the nightly shadow pool, which is dominated by v3a (about 1,300 of 1,462 pairs, 717 of them at 5m). v3a was a swinging market (coins ran 3-8% up and down inside the window) with a 50x base.
- **pe gains of low leverage are mostly smaller bets.** lev10's pnl-on-equity gain (+2.07% / +1.77% / +0.61% per trade at 15m in v3a / v3b / v4) is mainly a 2× instead of 9× notional on losing trades. Per 15m signal, pooled: house -0.84% of equity, lev10 -0.04%; `geo10` at house size -0.16%.

**The nightly shadows are biased against wide exits** (`d3_bias_v4.csv`). The same v4 trades, re-run to the end of the bars:

| variant / tf | shadow pairs (unresolved dropped) | all trades re-run | bias |
|---|---|---|---|
| lev10 15m | -0.213 | -0.009 | -0.20 |
| lev10 30m | -0.160 | +0.071 | -0.23 |
| lev10 1h | -0.043 | +0.124 | -0.17 |
| tp3R 30m | -0.463 | +0.072 | -0.53 |
| tp3R 1h | -0.480 | +0.402 | -0.88 |
| lock30 30m | -0.116 | +0.026 | -0.14 |

The dropped rows were the wide variant's big winners (+2.13R vs base for lev10 at 15m).

### 3. All variants per run and timeframe

Difference vs the house exit, R in base-stop units. v3a is from the nightly shadows (biased against wide exits); v3b and v4 are from the re-run. Full table: `master_variant_tf.csv`; v3a/v4 shadow CIs: `d3_paired_by_run_tf.csv`.

**15m** (n v3b 407, v4 2,070)

| variant | v3a | v3b | v4 | pooled [CI] | q | flipped | pe v3b / v4 (% equity) |
|---|---|---|---|---|---|---|---|
| tp1R | n/a | -0.004 | -0.126 | -0.106 [-0.228, -0.003] | 0.22 | -0.067 | -0.01 / -0.46 |
| tp1.5R | n/a | -0.112 | -0.121 | -0.120 [-0.212, -0.035] | 0.19 | -0.017 | -0.88 / -0.36 |
| tp2R | n/a | -0.240 | -0.086 | -0.111 [-0.207, -0.010] | 0.21 | +0.019 | -1.70 / -0.05 |
| tp3R | n/a | -0.293 | -0.053 | -0.092 [-0.264, 0.084] | 0.48 | +0.040 | -2.05 / +0.23 |
| ladder_cap2R | n/a | 0.000 | -0.098 | -0.082 [-0.170, -0.012] | 0.21 | -0.045 | 0 / -0.29 |
| be1_tp2 | n/a | -0.152 | -0.012 | -0.035 [-0.111, 0.039] | 0.53 | +0.056 | -1.13 / +0.28 |
| geo20_bar | n/a | -0.056 | +0.078 | +0.056 [-0.064, 0.207] | 0.56 | +0.091 | -0.36 / +0.54 |
| RL1_0.5_bar | n/a | -0.074 | +0.165 | +0.125 [0.014, 0.267] | 0.21 | +0.181 | -0.51 / +1.04 |
| RL1.5_1_bar | n/a | -0.233 | +0.210 | +0.137 [-0.041, 0.334] | 0.41 | +0.193 | -1.67 / +1.33 |
| base_bar | n/a | -0.030 | +0.055 | +0.041 [-0.001, 0.095] | 0.29 | +0.026 | -0.23 / +0.26 |
| lock15 | +0.082 | -0.023 | -0.028 | -0.027 [-0.075, 0.017] | 0.47 | +0.011 | -0.10 / -0.11 |
| timestop | -0.088 | +0.037 | -0.061 | -0.045 [-0.100, -0.004] | 0.24 | +0.001 | +0.27 / -0.31 |
| stopw1.5 | n/a | +0.054 | -0.006 | +0.004 [-0.035, 0.037] | 0.90 | +0.004 | +0.35 / -0.05 |
| stopw3 | n/a | -0.037 | -0.053 | -0.051 [-0.097, -0.001] | 0.21 | +0.001 | -0.20 / -0.38 |
| lev40m40 | n/a | -0.015 | -0.105 | -0.094 [-0.197, -0.004] | 0.21 | -0.069 | -0.23 / -1.02 |

**30m** (n v3b 204, v4 1,073)

| variant | v3a | v3b | v4 | pooled [CI] | q |
|---|---|---|---|---|---|
| tp1R | n/a | +0.006 | -0.070 | -0.058 [-0.110, -0.008] | 0.19 |
| tp1.5R | n/a | -0.109 | -0.047 | -0.057 [-0.154, 0.031] | 0.45 |
| tp2R | n/a | -0.170 | -0.057 | -0.075 [-0.220, 0.066] | 0.48 |
| geo20_bar | n/a | +0.068 | +0.057 | +0.059 [-0.027, 0.150] | 0.44 |
| RL1_0.5_bar | n/a | -0.111 | +0.118 | +0.081 [-0.050, 0.218] | 0.45 |
| RL1.5_1_bar | n/a | -0.181 | +0.158 | +0.104 [-0.050, 0.259] | 0.44 |
| lock15 | +0.049 | +0.071 | -0.016 | -0.002 [-0.050, 0.040] | 0.94 |
| timestop | -0.007 | +0.040 | -0.022 | -0.012 [-0.064, 0.030] | 0.73 |
| stopw3 | n/a | -0.056 | -0.040 | -0.043 [-0.093, 0.008] | 0.31 |
| lev40m40 | n/a | +0.099 (n 47) | -0.088 | -0.069 [-0.168, 0.017] | 0.38 |

**1h** (n v3b 119, v4 661)

| variant | v3b | v4 | pooled [CI] |
|---|---|---|---|
| geo10 | +0.145 | +0.132 | +0.134 [0.001, 0.272] |
| RL2_1 | +0.263 | +0.218 | +0.225 [0.023, 0.437] |
| RL1_0.5_bar | -0.043 | +0.213 | +0.174 [0.024, 0.327] |
| tp3R | +0.449 | +0.270 | +0.298 [0.079, 0.532] |
| timestop | +0.020 | -0.046 | -0.036 [-0.069, -0.007] |

**4h.** n is 5 in v3b and 107 in v4, and most wide-exit trades were still open and marked at the data end. Every exit without the ladder was worse by 0.14-0.24R in v4, which is the opposite of the 5-year result. Not usable.

### 4. Regimes and exit tuning

- **Wide exits win and lose in streaks.** For 15m+30m signals, the wide exit `geo10` minus the house exit in successive 6 h blocks from 10/05 00:00 UTC was -0.17, -0.10, -0.22, -0.20, -0.48, -0.17, then +0.64, +0.69, +0.39R.
- **The streaks persist block to block.** Lag-1 autocorrelation is +0.61 (`regime_blocks_6h_autocorr.csv`).
- **The same pattern appears on coin-flip entries,** so it comes from the price path, not from the signals.
- **A simple trend measure barely tracks it** (efficiency ratio, correlation 0.15 over 9 blocks).

Per-strategy exit tuning, out of sample (`tuning_oos_summary.csv`):

| split | menu | cells | in-sample gain (R) | out-of-sample gain vs house [CI over cells] | cells where the pick beat house |
|---|---|---|---|---|---|
| v3b -> v4 (core 36) | all exits | 31 | +0.34 | -0.023 [-0.132, 0.075] | 39% |
| v4 first half -> second half | all exits | 67 | +0.29 | -0.092 [-0.190, 0.010] | 33% |
| v4 second half -> first half | all exits | 67 | +0.88 | -0.210 [-0.288, -0.126] | 22% |
| v3b -> v4 | 5 AI-candidate exits | 31 | +0.09 | +0.037 [-0.029, 0.110] | 32% |
| v4 first half -> second half | 5 AI-candidate exits | 67 | +0.11 | -0.075 [-0.177, 0.038] | 21% |
| v4 second half -> first half | 5 AI-candidate exits | 67 | +0.64 | -0.164 [-0.226, -0.106] | 19% |

### 5. Five-year priors (repo studies, read-only)

- **Ladder geometry** (`research/levstop`, fixed-leverage arms, the same signals entered by every arm, 2 ATR stop; signal-weighted bps per notional vs the 30x arm; cells better than 30x out of 36):

| tf | 10x | 20x | 40x | 50x | 50x liquidation share |
|---|---|---|---|---|---|
| 15m | +0.09 (22) | +0.03 (19) | -0.50 | -1.63 | 5% |
| 30m | -0.01 (20) | +0.26 (24) | -1.37 | -3.50 | 11% |
| 1h | +1.76 (28) | +1.08 (29) | -2.43 | -4.95 | 19% |
| 4h | +5.76 (26) | +2.73 (22) | -2.04 | -4.60 | 34% |

  At 15m/30m, 10-30x geometry is equivalent over 5 years. Wider geometry helps at 1h/4h. 40-50x is worse everywhere, partly through liquidations.

- **Stop width at 30x** (bps per notional, 1.5 / 2 / 2.5 / 3 ATR): 15m -14.09 / -14.24 / -14.57 / -15.04; 30m -14.67 / -15.33 / -16.18 / -17.19; 1h -15.94 / -17.45 / -18.91 / -20.06. Wider is worse at a fixed leverage.
- **Fixed take-profit vs ladder** (`research/exitstyle`): none passed the pre-registered rule. Difference in % of equity per trade, all / period 1 / period 2:
  - 15m: tp1R +0.015 / +0.015 / +0.016; tp2R +0.025 / -0.005 / +0.063.
  - 30m: tp1R -0.042; tp1.5R -0.029.
  - 1h: tp1R -0.025; tp2R +0.059.
  - ladder + 2R cap at 15m: +0.014 (8 cells better, 0 worse).
- **Not tested over 5 years:** R ladders, breakeven, bar-close updates, time stops.

### 6. Leverage 20-50x as size (margin = leverage % of equity)

From `lev_risk.csv`:

| tf | 20x | 30x | 40x | 50x |
|---|---|---|---|---|
| notional / equity | 4× | 9× | 16× | 25× |
| 15m loss per stop (median) | 3.0% | 6.7% | 11.8% | 18.5% |
| 15m share passing the 15% cap + liquidation buffer | 100% | 100% | 84% | 18% |
| 30m loss per stop | 4.0% | 9.1% | 16.1% | 25.2% |
| 30m pass share | 100% | 99% | 37% | 0% |
| 1h loss per stop | 5.5% | 12.3% | 21.9% | 34.3% |
| 1h pass share | 100% | 81% | 1% | 0% |
| 15m drawdown after 7 straight stop-outs | 19% | 38% | 59% | 76% |

### 7. Recommended code-computed exits for 15m/30m AI traders (20-50x)

1. **Initial stop: 2 × ATR14 of the entry timeframe** from the reference price, stop-market, never widened by the AI. Evidence: medium.
   - Over 5 years, 1.5-2 ATR is best per notional.
   - Live, 2.5-3 ATR was worse in both runs at the same size (15m stopw3 -0.051 [-0.097, -0.001]).
   - 1.5 ATR is no better (+0.004R at 15m) and raises cost per R under risk sizing (0.224 vs 0.168R).
2. **Profit protection that does not depend on leverage, raised only at the strategy-bar close and effective from the next minute.** Evidence for the ladder choice: low (neither option differs reliably from the house exit). Evidence for bar-close updates: low-medium (+0.02 to +0.04R at 15m/30m, CI excludes 0 pooled, q ≈ 0.09).
   - **Default (the AI design's choice):** the house ladder at fixed 20x price geometry. Arm at +0.74% (12%/20 + 0.14%), lock +0.64%, then steps of 0.25% of price. At the median stop that is about 1.2R / 1.03R at 15m and 0.84R / 0.72R at 30m.
     - Live vs the house exit: +0.056 (15m) and +0.059 (30m, the same sign in both runs).
     - 5-year: equivalent to 30x.
   - **Shadow candidate:** R ladder `RL1_0.5_bar` (arm at MFE ≥ +1R, lock +0.5R, +0.5R per +0.5R). It is volatility-normalized and equal across coins.
     - Live: +0.125 [0.014, 0.267] at 15m, but v3b -0.074 and v4 +0.165.
     - Adopt it only if a pre-registered 5-year test passes.
3. **No fixed 1-2R take-profit as the code exit.** Evidence: medium against.
   - 15m tp1.5R -0.120 [-0.212, -0.035] and tp2R -0.111 [-0.207, -0.010], negative in both runs.
   - A 1R target needs a 63% hit rate; the strategies hit 49.3%.
4. **Breakeven only after MFE ≥ +1R, to the net-zero price including costs.** Evidence: low-medium. It adds +0.05 to +0.08R to target exits in both runs at 15m. Breakeven at +0.5R hurt in v4 (-0.143).
5. **No time stop.** Evidence: medium against. 15m -0.045 [-0.100, -0.004]; 1h -0.036 [-0.069, -0.007]; negative in 2 of 3 runs. A 2N-bar max hold is neutral (-0.017R) and acceptable only as a safety cap.
6. **Leverage must not touch the exit.**
   - With margin = leverage %, keep a 15m/30m stop-out at about 7% of equity or less (30x at 15m, 20-30x at 30m).
   - Scale confidence through risk per stop, not through the ladder, and keep the fixed-risk twin.
   - 40-50x adds risk without any evidence that confidence predicts R. 40x geometry was -0.094R at 15m, and 50x is refused for 82% (15m) and 100% (30m) of signals.
   - Evidence: high on the arithmetic, medium on R.
7. **Freeze exits for the whole test; tune only in shadow; adopt only through a multi-period pre-registered test.** Evidence: high (out-of-sample loss of per-cell tuning, section 4).
8. **For the 1h/4h rule accounts:** widen the ladder to at least 10-20x geometry, or use an R ladder arming at 1.5-2R. Run it as a pre-registered shadow first. Evidence: medium (1h geo10 positive in v3a, v3b and v4, and 28/36 cells over 5 years).

### 8. Strategy × timeframe through the exit lens

`strategy_tf_exits.csv` covers 60 cells with at least 25 every-signal entries.

- **No cell is significantly positive after BH** (best q 0.72).
- **Two cells are significantly negative:** F4_PULL 15m -0.59 (q 0.05) and N18_VWMA_MACD 30m -0.74 (q 0.004).
- **Exit choice moves a cell a lot:** a median of 0.53R, up to 1.22R. 43 cells are positive under some exit but only 18 under the house exit, so cells that are "positive under the right exit" are unproven.
- **Positive under all 34 exits (exit-robust sign):**
  - N17_KC_RSI 15m: n 153, +0.16 [-0.11, 0.42], both runs positive, spread 0.16R.
  - N20_EMA9_CHOP 30m: n 43, +0.26 [-0.11, 0.67].
  - F6_VWAP_CROSS 1h: n 43, v4 only.
- **Negative under every exit:** 17 cells, e.g. N22_VORTEX_PSAR, OBV_B, N25_DST_CCI and N18_VWMA_MACD at 15m; N04_ST_KLINGER and S2_ST_ROC at all timeframes.

### What the data cannot tell

- The long-run value of any 15m/30m exit. Live effects flip with 12-24 h regimes, and the new candidates have no 5-year test.
- Anything about v3a beyond the biased nightly shadows (no live_bars).
- 4h, and partly 1h, results beyond the 10/07 data end (marked positions).
- Account-level effects: how exit length changes trades per day and cost drag in one-position accounts.
- How discretionary AI exits will behave.

Treat these numbers as evidence about structure (cost, leverage coupling, overfitting risk), not as tuned values.