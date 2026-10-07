# PREREG: does walk-forward custom-value search beat default values out of sample?

Written 2026-10-07 before any outcome (R) of any custom value was computed. Only signal parity checks
(default signals == locked caches) and run-time probes were run before this file. SHA-256 of this file is
stored in PREREG.sha256 next to it; the analysis script checks it and refuses to run if it changed.
Changes after this point go into an "Amendments" section at the end, with the reason, and are reported.

## 1. Question
The owners' idea: run each strategy with default values, keep searching for per-strategy custom values
(indicator periods / thresholds, entry filters, stop width, exit style) that "reduce noise", and adopt them
over time. Test: on 5 years of Binance USDT-M futures bars, does a walk-forward search (choose the best
combination on a trailing window, apply it to the next week / month) beat the default values out of sample,
in net R per trade after house costs? Which adoption gate keeps real improvements and rejects noise?

## 2. Data and code (read-only reuse)
- Bars: Binance USDT-M futures, 6 coins (BTC ETH SOL DOGE LTC BCH), 15m / 30m / 1h, from the scratchpad
  binance cache (`binance/signals/sig_<tf>_<COIN>.npz`: ts, o, h, l, c, v, atr = ATR14 of the locked code).
- Default signals of the 36-strategy set: the locked cache columns `s__<name>`. Custom indicator values: the
  hash-locked parameter re-implementations `research/entry_study/param_defs/<name>.py` (each file checked
  against `DEFS_BC.sha256`, whose own hash is pinned at 185dbcf8...). With no override they reproduce the
  cache bar for bar (checked again in the run; any mismatch aborts).
- DeepSeek definitions (F6_VWAP_CROSS, F5_BOX, F9_FVG): small parameterised copies of
  `research/deepseek200/lib_c.py` code in my folder; with default values they must reproduce
  `lib_c.entries` bar for bar on every coin x tf (checked in the run; mismatch aborts).
- Signal bars from 2021-02-01 00:00 UTC (January 2021 is indicator warm-up) to the end of the cache
  (2026-09-29). Entry = next bar open. Trades that do not close within 4096 bars or before the data end are
  dropped (reported).

## 3. Strategies and timeframes (36 cells = 12 strategies x 15m, 30m, 1h)
| strategy | family (filter type) | why |
|---|---|---|
| S2_ST_ROC | trend | required; Supertrend + ROC |
| N23_HA_ST | trend | required; Heikin-Ashi + Supertrend |
| N24_DMI | trend | DMI/ADX trend |
| N10_HA_PSAR | trend (mixed profile) | required; HA + PSAR |
| S4_BB_BBP | trend (squeeze breakout) | required; breakout family |
| N06_MACD_ORB | trend (range breakout) | breakout family |
| OBV_B | trend (volume breakout) | volume family |
| F6_VWAP_CROSS | trend (volume / VWAP) | required; volume family (DeepSeek) |
| F9_FVG | trend (ICT pullback) | structure / ICT family (DeepSeek) |
| N17_KC_RSI | mean reversion | required; Keltner + RSI |
| N16_BBRSI | mean reversion | Bollinger + RSI |
| F5_BOX | mean reversion (structure: box edges) | structure family (DeepSeek) |

## 4. Custom-value space (fixed now)
Combination = P (indicator values) x F (context filter) x S (stop) x X (exit) = 5 x 5 x 3 x 3 = 225 per cell.

### P: indicator values (default P0 + four one-at-a-time changes, x0.75 / x1.25 of the default, rounding as
param_defs.variant_value: length -> round half up, min 2; mult / threshold_abs -> m x default;
threshold_neutral -> neutral + m x (default - neutral))
| strategy | P1, P2 | P3, P4 |
|---|---|---|
| S2_ST_ROC | st_mult x0.75 / x1.25 | roc_len x0.75 / x1.25 |
| N23_HA_ST | st_atr_len x0.75 / x1.25 | st_mult x0.75 / x1.25 |
| N24_DMI | di_len x0.75 / x1.25 | adx_len x0.75 / x1.25 |
| N10_HA_PSAR | sar_af_start x0.75 / x1.25 | sar_af_max x0.75 / x1.25 |
| S4_BB_BBP | bb_len x0.75 / x1.25 | sq_pct x0.75 / x1.25 |
| N06_MACD_ORB | macd_fast and macd_slow together x0.75 / x1.25 | ext_cap x0.75 / x1.25 |
| OBV_B | break_len x0.75 / x1.25 | ao_slow x0.75 / x1.25 |
| N17_KC_RSI | kc_mult x0.75 / x1.25 | rsi_level x0.75 / x1.25 (neutral 50) |
| N16_BBRSI | bb_len x0.75 / x1.25 | rsi_len x0.75 / x1.25 |
| F6_VWAP_CROSS | P1 weekly anchor (Monday 00:00 UTC) instead of daily; P2 volume confirm (bar volume > SMA20 volume) | cross buffer: close beyond VWAP by >= 0.10 ATR / >= 0.25 ATR |
| F5_BOX | box length 48 -> 36 / 60 | ADX ceiling 20 -> 15 / 25 |
| F9_FVG | min gap 0.5 ATR -> 0.375 / 0.625 | zone life 50 bars -> 38 / 62 |

### F: context filter (one at a time, or none). Computed at the signal bar close, causal.
- F0 none (default).
- F1 htf: higher timeframe (15m -> 1h, 30m -> 2h, 1h -> 4h, as lib_c.HTF_OF; built by resampling the
  cell's own bars, only HTF bars closed at or before the signal bar's close) close vs its EMA50 agrees with
  the side (long: HTF close > EMA50; short: <).
- F2 adx: ADX14 (fg.dmi_adx 14/14) on the cell's tf. trend family: ADX >= 20. mean-reversion family: ADX < 25.
- F3 box: position in the prior 48-bar high-low range, pos = (close - min low[t-48..t-1]) / (max high - min low).
  trend family: long pos >= 0.5, short pos <= 0.5. mean-reversion family: long pos <= 0.3, short pos >= 0.7.
- F4 session: signal bar opens 07:00-20:59 UTC (London + New York; 16:00-05:59 KST).

### S: initial stop 1.5 / 2.0 (default) / 2.5 x ATR14 of the signal bar, from the raw entry (next bar open).
### X: exit style
- X0 house (default): the house ROE ladder at 20x geometry (paperbot ladder: lock net ROE 10% when best net
  ROE >= 12%, then +5% steps; ROE = 20 x (price return - round-trip cost - funding)). Lock applies from the
  next bar. No take-profit. (exitstyle.scan logic with lev = 20; liquidation not modelled.)
- X1 R-ladder: when the best favourable excursion reaches 1.0 R (R = stop distance) the stop moves to +0.5 R;
  every further 0.5 R of excursion moves it up 0.5 R. From the next bar. No take-profit.
- X2 fixed 1.5 R take-profit, stop moved to break-even (the fill price) from the bar after the excursion first
  reaches 1.0 R.
Common: stop or lock touched -> exit at that level, or at the bar open if the bar opens beyond it; take-profit
filled at its price (no favourable-gap credit); a bar that touches both stop and take-profit is a stop.
Levels are measured from the raw entry (next bar open) like exitstyle.

Default combination = (P0, F0, S 2.0, X0).

## 5. Costs and the metric
- House costs (rules_bt / paperbot config): taker fee 0.05% per side, slippage 0.02% per side (entry fill =
  open x (1 + side x 0.0002), exit fill likewise against the trade), funding 0.01% per 8 h paid on every bar held.
- R = net P&L / (qty x |fill - initial stop|). Primary metric: OOS net R per trade (trade-weighted mean).
- Secondary: net return per notional per trade (%, = R x stop distance %), to separate the cost-in-R channel of
  wide stops from real improvement; cost R per trade.
- Every signal is a trade (no one-position limit); coins pooled within a cell.

## 6. Walk-forward
- Weeks start Monday 00:00 UTC. OOS starts 2021-08-02 (26 weeks after the first signal) and ends with the last
  full week in the data. A "month" = 4 weeks; windows: 1 w, 4 w (1 m), 13 w (3 m), 26 w (6 m).
- Decision time T: training trades = signals at or after T - W whose exit time is before T (causal).
  The chosen combination is applied to signals in [T, T + step). Steps: weekly re-tune (1 w) and monthly
  re-tune (4 w). 8 schemes = 2 steps x 4 windows.
- Naive search (the "keep searching" idea): pick the combination with the highest training mean R among those
  with >= 10 training trades (ties -> default first, then lower index). No combination qualifies -> default.
- Restricted searches (which kind of custom value matters): the same naive search over P only (F0, S2.0, X0),
  F only, S only, X only.
- Random benchmark: the mean OOS R of all 225 combinations (what a random pick would give).
- Adoption gates (switch from default to the candidate only for that step; otherwise default). Candidate = the
  highest training mean among combinations with n >= N_min. Adopt only if all hold:
  g1 n_cand >= N_min; g2 training improvement over default >= delta R; g3 the improvement is > 0 in both halves of
  the training window (split at T - W/2, by signal time), with >= N_min/4 candidate trades in each half;
  g4 z = improvement / sqrt(var_c/n_c + var_d/n_d) >= z_min.
  Grid: N_min in {30, 100, 300}, delta in {0.05, 0.15, 0.30} R, z_min in {0, 2}; g3 always on. 18 gates x 8 schemes.

## 7. Statistics
- Uncertainty: day-cluster bootstrap (UTC day of the signal bar), B = 1000, paired (the same days resampled for
  the selected stream and the default stream), 95% percentile CI of the difference in pooled mean R per trade.
  Pooled over cells: days resampled jointly across cells.
- One-sided bootstrap p (difference <= 0) per cell; Benjamini-Hochberg at 10% over the 36 cells within a scheme.
- Noise rate: share of decision steps where the selected combination differs from the default and its OOS mean
  in the applied period is <= the default's (both with >= 1 trade).
- Persistence: per cell, improvement of every combination over default in half A (signals 2021-08-02 ..
  2024-06-30) and half B (2024-07-01 .. end); Spearman correlation across the 225 combinations; mean half-B
  improvement of the half-A top 10; per dimension level (each P, F, S, X level vs its default with the other
  dimensions at default) sign agreement across halves.
- Time to confirm: trades needed to detect a true improvement of 0.05 / 0.10 / 0.20 R with one-sided alpha 5%,
  power 80%: n = ((1.645 + 0.842) x sd_R / delta)^2 x design effect (day clustering, measured), converted to
  weeks with each cell's default trades per week (and per single coin / per one-position trader as a note).

## 8. Decision rules (fixed now)
- "Walk-forward custom-value search beats defaults" for a scheme only if: pooled OOS improvement in net R per
  trade > 0 with the 95% day-cluster CI above 0, AND > 0 in both OOS halves (A and B as above), AND positive in
  >= 60% of the 36 cells. Same rule for the per-dimension searches.
- A gate "keeps real improvements" only if, over the steps where it switched, the pooled OOS improvement is > 0
  with the 95% CI above 0 and it switched in >= 5% of the cell-steps. Among passing gates the recommendation is
  the one with the largest total OOS R gained (improvement x switched trades). If none passes: recommend that the
  bot keeps default values live and runs the search only in a shadow account, with the strictest gate as a filter
  of what it is allowed to propose.
- Expected (stated before results): the 5-year studies found no parameter change with an edge (entry_study C)
  and exit styles moving results by <= ~0.06% of equity; wider stops lower cost in R mechanically. I expect
  the naive search to lose to defaults or tie, and wide stops / filters to show small mechanical gains in R.
