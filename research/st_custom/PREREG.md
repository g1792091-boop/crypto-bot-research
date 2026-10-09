# Supertrend custom-value search: pre-registration (written 2026-10-09, before any result)

Owner request (friend's plan): find low-noise custom values for the Supertrend strategies on 15m/30m over 1-5 years
of past charts, per coin too, include the LUNA and COVID crashes, re-optimise every 5 trades in demo, compare 20/30/40/50x
with their best take-profit/stop, pick the lowest-drawdown profitable setting, then demo it in a separate bot.
This study does the search and checks whether the picked values hold up on data the search did not see.

## Data
Binance USD-M futures 15m bars (data.binance.vision). Coins: BTC, ETH, SOL, DOGE, LTC, BCH, XRP. 30m built from 15m.
- SEARCH: 2021-01-01 .. 2023-12-31 (contains LUNA 2022-05 and FTX 2022-11)
- TEST:   2024-01-01 .. 2026-09-29
- EXTRA:  2020-01-01 .. 2020-12-31 (contains COVID 2020-03; SOL from 2020-09)
Indicators get 500 bars of warm-up before each period start.

## Strategies and grid (locked signal code: research/entry_study/param_defs/*.signals(df, tf, **overrides))
- S2_ST_ROC: st_atr_len {5,7,8,10,12,14,20} x st_mult {1.5,2,2.5,3,4,5,6} x roc_len {5,9,14,21,28,37,50} (343)
- N02_ST_KST: st_atr_len x st_mult (as above) x KST lengths scaled {0.5,0.75,1,1.5,2} x kst_signal_len {5,9,13} (735)
- N04_ST_KLINGER: st_atr_len x st_mult x Klinger (34,55) scaled {0.5,0.75,1,1.5} x kvo_signal_len {7,13,21} (588)
Defaults (10, 6.0, ...) and the friend's values (S2: 8, 3, ROC 37; N04: 8, 3, Klinger default) are in the grid.
Timeframes: 15m and 30m.

## Trade simulation (main)
Entry at the next bar's open after the signal bar close. House exits: stop 2 x ATR14 of the signal bar, paperbot ladder
(config.v3_settings), checked on 15m bars. Costs: taker 0.05% + slippage 0.02% per side, funding 0.01% per 8 h.
Unit: R = net P&L / (entry risk to the initial stop). Every signal is one trade (signal level).

## Variants (each reported separately, same SEARCH -> TEST rule)
- MAKER: limit entry at the signal bar close, valid for one bar of the signal timeframe; fill if price trades at/through it;
  entry fee 0.02%, no slippage on entry; unfilled signals are not traded.
- STFLIP: same 2 ATR initial stop, but exit at the bar close when the strategy's own Supertrend direction flips against
  the position (no ladder).
- HTF: trade only if the 4h close is on the trade's side of the 4h EMA50.
- CHOP: trade only if ADX14 on the signal timeframe >= 20.
- TPSL: fixed take-profit {1, 1.5, 2, 3} R x stop {1.5, 2, 3} ATR (no ladder).

## Selection (SEARCH only)
Per strategy x timeframe, pooled over coins: among combos with >= 200 SEARCH trades, score = mean net R of the combo and
its grid neighbours (+-1 step in every dimension, the combo itself counted once). Pick the top 3 by score ("plateau
picks"). Per coin: same with >= 100 trades, top 1 per coin.

## Luck baseline
For each strategy x timeframe, 50 random signal sets with the same number of signals and long/short mix as each picked
combo, placed at random bars in SEARCH; record the best-of-grid-size random mean net R (max over as many random sets as
there are grid combos, by resampling). A pick is "beats luck" if its SEARCH mean net R exceeds the 95th percentile of
the random best.

## Re-optimisation simulation
ROLL5: after every 5 trades of the account, re-pick the best plateau combo on the trailing 26 weeks (and on the trailing
4 weeks), apply to the next trades. WEEKLY: re-pick every Monday 00:00 UTC on the trailing 26 weeks. Compare with the
default values over the same trades (TEST and EXTRA).

## Accounts (for the picks, default and friend values)
One position per coin per account; 20x, 30x, 40x, 50x with the owner rule margin = leverage% of equity, and with 1% risk
per stop. Report final equity, max drawdown, worst losing streak, longest recovery, and ruin (equity < 10% of start).

## Pass rule for "worth demo trading" (all required)
1. TEST mean net R > 0 and EXTRA mean net R > 0 (week-block bootstrap 95% interval reported).
2. Better than the default values on TEST and on EXTRA.
3. Beats luck in SEARCH (above).
4. The plateau neighbours' TEST mean net R > 0 on average.
The friend's values are reported even if they fail. Win rate is reported but is not a pass criterion.

## Reported regardless
Per period (incl. 2020-03, 2022-05, 2022-11 windows), per coin, per timeframe: trades, win rate, gross R, cost R,
net R, max drawdown; SEARCH vs TEST change of every pick (shrinkage).
