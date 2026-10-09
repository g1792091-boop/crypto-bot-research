# Deviations and interpretations (written 2026-10-09 before the study's results)

PREREG.md (sha256 94a311f0...) and PREREG_ADDENDUM_1.md (sha256 203f8cfb...) are not edited. The scripts check both
hashes. Below: what could not be done exactly as written (D) and how ambiguous points were resolved (I). Everything
here was fixed before the selection, test or account results were computed. Only smoke tests of the code (one coin,
default values, 2020) had been run.

## Deviations (D)

- **D1 EXTRA warm-up.** Bars start 2020-01-01 (BTC, ETH, BCH), 2020-01-06 (XRP), 2020-01-09 (LTC), 2020-07-10
  (DOGE) and 2020-09-14 (SOL). No bars exist before that, so the first 500 bars of each coin are warm-up and give
  no signal. EXTRA signals therefore start about 5 days (15m) or 10 days (30m) after each coin's first bar. The
  COVID window (2020-03) is not affected. DOGE is in EXTRA only from mid-July 2020. The PREREG mentions only SOL.
- **D2 XRP data holes.** The raw XRP monthly zips lack 2022-02-26..28 and 2022-04-01..02. The daily repair files
  that research/binance_data/build.py used for SOL and LTC on the same days are not in the offline folder. These
  5 days are real gaps for XRP (inside SEARCH).
- **D3 XRP brackets.** XRP was never traded live, so it has no fitted leverage brackets. The house sizer uses
  DOGE's fitted table for XRP. This only affects whether an XRP signal sizes at 30x or 20x (ladder steps) and the
  liquidation price.
- **D4 Zero-volume bars** are dropped in every source. research/binance_data/build.py did the same; the pre2021
  cache still held such bars.

## Interpretations (I)

- **I1 Main signal-level trades.** "Every signal is one trade". Signals that the house sizer cannot size at 30x or
  20x (about 3%) are still traded at the 20x ladder without liquidation, as precompute.py's all-signal
  sensitivity did. Trades that do not close before the data ends (last days of TEST) are left out and counted.
  Leverage for the ladder is the sizer's: 30x/30% first, then 20x/20% (the live "normal" group). Equity for sizing
  is 5,000, as in precompute.py.
- **I2 Periods.** A trade belongs to the period that holds its signal bar's open time. TEST ends at the data end
  (last bar 2026-09-29 23:45 UTC). Exits may run past the period end on the continuous bars.
- **I3 Indicators outside the strategies.** ATR14 (stop), ADX14 (CHOP) and the 4h EMA50 (HTF) are computed on the
  continuous series from each coin's first bar. For these Wilder/EMA recursions, 500 bars of warm-up and the
  continuous series agree to about 1e-15 relative. The strategy signals (Supertrend ratchet, Klinger, KST, ROC)
  are computed per period with exactly 500 bars of warm-up. The 4h bars are built from 15m. 4h bins with a data
  hole are kept; the last bin is kept only if complete. HTF uses the last 4h bar closed at or before the signal
  bar's close, with EMA50 = pine_ema (SMA-seeded). Long: 4h close > EMA50. Short: 4h close < EMA50. NaN means no
  trade.
- **I4 MAKER.** The limit is the signal bar's close. It fills when a 15m bar of the next signal-timeframe bar trades
  at or through it (long: low <= limit). The fill price is the limit, with no price improvement even when the bar
  opened through it. The stop is 2 ATR from the limit price. The ladder thresholds are unchanged, because the
  engine's ladder uses the taker round trip. Exit costs are taker + slippage. On the fill bar the favourable
  excursion is not credited and there is no gap-at-open exit. This is conservative: the bar's extremes are
  assumed to come after the fill. Unfilled signals are not traded. Their count is reported.
- **I5 STFLIP.** Exit at the close of the first signal-timeframe bar after entry whose Supertrend direction is
  against the position. This uses the combo's own ATR length and multiplier, on the per-period series. The 2 ATR
  stop is checked on 15m bars (no ladder). It wins when touched in or before the flip bar. Exit costs are taker +
  slippage. A trade with neither exit before the series end (period end + 4,000 bars) or the data end is left
  out and counted.
- **I6 TPSL.** The take-profit is the entry bar open +- tp x (k x ATR14). A 15m bar touching both stop and TP is
  counted as a stop. A stop gap fills at the open; a TP gives no favourable-gap credit. Every exit pays taker +
  slippage. R is in units of that setting's own stop (k ATR). R2 = R x k / 2 (units of the default 2 ATR stop) is
  added because a wider stop shrinks cost in R mechanically. Each of the 12 settings is its own variant with the
  same selection rule. "Best TPSL" is one more selection step (the setting whose top plateau pick has the best
  SEARCH score) and is reported as such. For the liquidation-gap check TPSL uses the main (2 ATR) sizer leverage.
- **I7 Selection.** Neighbours are all combos within +-1 step in every dimension at once (Moore neighbourhood, up
  to 3^d - 1 neighbours, clipped at the grid edge), plus the combo itself once. The score is the unweighted
  average of the combo means of mean net R over the neighbourhood combos with >= 1 SEARCH trade. The trade minimum
  (>= 200 pooled, >= 100 per coin) applies to the picked combo. Ties go to the lower combo index. The same rule
  is applied to every variant.
- **I8 Luck baseline.** Random bars are drawn uniformly among the SEARCH bars that have an outcome, without
  replacement within a coin and side. Each coin gets the same numbers of longs and shorts as the pick's closed
  trades (pooled picks: the per-coin counts; for MAKER the filled ones). Outcomes come from the pick's own variant table (main for the PREREG pass rule).
  50 random sets. "Best of grid size": draw G (= grid size: 343 / 735 / 588) of the 50 random means with
  replacement, take the max, 10,000 times; the threshold is the 95th percentile. Supplementary only: a normal
  approximation of the max of G independent random sets.
- **I9 Intervals.** Week-block bootstrap: Monday 00:00 UTC weeks of the signal bar, pooled over coins, 2,000
  resamples, percentile 95% interval of the pooled mean net R.
- **I10 Re-optimisation (ROLL5 26w / 4w, WEEKLY 26w).** The account is one position per coin (7 coins), in
  signal-level R with main exits. A new signal on a coin with an open position is skipped. Same-moment ties go
  in coin order BTC, ETH, SOL, DOGE, LTC, BCH, XRP. Candidates are scored with the same plateau score on the
  trades CLOSED in the trailing window [T - W, T). Trades are binned by exit time in 4-hour bins, and only bins
  that ended by T count, so the window lags T by under 4 hours. Eligibility is >= 200 trades pooled; when no
  combo is eligible, the default is used. ROLL5: re-pick after every 5 closed account trades; the new combo
  applies to signals after that moment, and open positions continue. WEEKLY: re-pick on Mondays 00:00 UTC. The
  comparison is a default-values account under the same rule over the same period (mean net R per trade,
  trades, total R). Signals before TEST/EXTRA are used only as trailing history: SEARCH for TEST. EXTRA has no
  earlier data, so it starts on the default until a window has eligible combos.
- **I11 Accounts.** The seed is 1,000 USD (addendum 1); results scale with the seed except for exchange minimums.
  Leverage L in {20, 30, 40, 50}. (a) Owner rule: margin = L% of the wallet at entry, notional = L x margin.
  (b) 1% risk: notional such that the loss at the stop (fees and slippage included) is 1% of the wallet, with
  margin = notional / L. One position per coin; a signal is skipped if the margins in use would exceed the wallet.
  Two check modes:
  - "house": the live sizing checks (bracket max leverage at that notional, stop inside liquidation by
    max(1 ATR, 0.2%), loss at the stop <= 15% of the wallet, min notional 5 USD). Failing signals are skipped.
  - "forced": no checks except margin. Liquidation is modelled (isolated margin: the margin is lost).

  The ladder runs at L. The liquidation price uses the coin's first bracket tier (exact up to that tier's
  notional cap; larger positions would liquidate somewhat earlier in reality). Ruin = wallet < 10% of the seed;
  trading stops there. Max drawdown is on the closed-trade wallet curve. Worst losing streak counts consecutive
  losing closed trades. Longest recovery is the longest time from a wallet peak to the next new peak (or to the
  period end). Each period (SEARCH, TEST, EXTRA) starts from the seed. With exchange minimums (addendum): the
  quantity is rounded down to the step and must reach the minimum notional. The values are assumed, not verified
  offline: BTC 0.001 / 100 USD, ETH 0.001 / 20, SOL 1 / 5, DOGE 1 / 5, LTC 0.001 / 20, BCH 0.001 / 20,
  XRP 0.1 / 5.
- **I12 Self-check.** lens2 custom_values (-0.1645 R over 94,310 trades) used the 20x ladder geometry for every
  signal, no liquidation, signal bars 2021-08-02..2026-09-28 (full weeks), 6 coins, trades closed within 4,096
  bars, and the signal cache computed from 2021-01. The main simulation here uses the sizer's leverage (mostly
  30x: the first lock comes at a smaller price move) and models liquidation gaps. The self-check reports both:
  this study's house exits, and a 20x-for-every-signal run on the same signals.
- **I13 Drawdown at signal level** is the largest fall of the cumulative net R of all signals of a combo in signal-
  time order (signal level, every signal a trade: an exposure-free measure, not an account drawdown).
- **I14 INTRABAR (addendum 1).** These rules were fixed in intrabar.py before any INTRABAR output was seen,
  except one smoke test (BTC 30m EXTRA) that was run after the code was written to check that it runs.
  - Forming bar at each 5m close before the bar's close: open = first 5m open, high/low = extremes so far,
    close = latest 5m close, volume = sum so far. A bar is evaluated only when all its 5m sub-bars exist.
  - Every indicator at the forming bar is one step of its recursion from the complete state of the previous
    bar: Supertrend loop body; true range, ROC and Klinger force by the locked formulas; RMA/EMA/SMA by
    value_full + alpha (or 1/length) x (forming input - complete input). Unit tests: (a) forming = complete bar
    reproduces the locked full-series signals and ATR14 exactly; (b) random partial bars match the locked code
    recomputed on the truncated series (signals equal, ATR within 1e-12).
  - Entry: the first 5m step where the side's signal is true and the previous complete bar's signal for that side
    was false; at the next 5m bar's open with entry slippage. One entry per bar per side.
  - Exits: house ladder at the sizer's leverage, checked on 5m bars, funding per 5m bar. The bar-close entries
    of the same values are re-simulated on the same 5m bars for the comparison. The main (15m-checked) numbers
    are shown next to them. Checking on 5m bars moves the ladder lock earlier than on 15m bars, so the two
    granularities are not mixed in one comparison.
  - Entry-price difference: kept intrabar entries against the bar-close entry of the same bar and side, in bps,
    positive = the intrabar entry price was better for the trade's side.
  - Combos: default, friend's, the 3 pooled picks (main variant), and each per-coin pick on its own coin.
- **I15 Account seed and minimums (addendum 1).** All account runs use the 1,000 USD seed, each with and without
  the exchange minimums of I11.

## Housekeeping (after the run)

- The scratch work folder held about 690 MB at the end. The large intermediates were deleted: bars, per-bar outcome
  tables and signal lists, about 480 MB. Every stage rebuilds them from the raw bar files (stages checkpoint per
  coin x timeframe x period). The small aggregates (stage-2 totals, detail, re-optimisation, account and
  INTRABAR files, under 200 MB) were kept in st_custom_work/.
