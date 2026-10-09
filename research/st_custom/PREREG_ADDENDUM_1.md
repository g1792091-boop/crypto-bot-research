# Addendum 1 (written 2026-10-09 before any result; owner request): intrabar entry comparison

INTRABAR variant, run for: the default values, the friend's values (S2 8/3/ROC 37, N04 8/3), and every pick from the
SEARCH selection (pooled picks; per-coin picks optional if time allows). Timeframes 15m and 30m, all 7 coins,
SEARCH / TEST / EXTRA periods.

Rule: inside each signal-timeframe bar, at every 5m close before the bar's own close (15m: after minutes 5 and 10;
30m: after minutes 5..25), rebuild the forming bar from the 5m bars so far (open = bar open, high/low so far,
close = latest 5m close, volume so far), keep all earlier bars complete, and evaluate the strategy's signal for the
forming bar. The first time the signal is true inside a bar (and it was not already true for the previous complete bar),
enter at the next 5m open. Stop = 2 x ATR14 computed with the forming bar as the last bar. Exits and costs as the main
simulation (house ladder, taker 0.05% + slippage 0.02% per side, funding). One intrabar entry per bar per side.
Record whether the signal still holds at the bar's actual close (kept) or not (vanished).

Implementation must reproduce the full-bar value exactly when the forming bar equals the complete bar (unit test).
Data: 5m bars (scratchpad/binance/bars/<coin>usd-5m.csv.gz, data/pre2021/<coin>usd-5m.csv.gz; XRP 5m to be built
from Binance raw files if missing, else XRP is reported as not available for this variant).

Reported: trades, share vanished, win rate, gross R, cost R, net R, entry-price difference vs bar-close entry (bps),
versus the bar-close entry of the same values, per period. Demo account seed for account simulations: 1,000 USD
(owner); also report results at this seed with Binance minimum order sizes where known.
Pass/fail rules of PREREG.md are unchanged; INTRABAR is reported as a comparison, not a new pass route.
