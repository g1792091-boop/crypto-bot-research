# Descriptive trade statistics (not a gate)

Added after the sweep to answer "what do win rate, payoff, profit factor and drawdown look like?".
Nothing here selects or re-judges anything; the pre-registered verdict (0 of 528 pass) stands.

- `trade_stats.py <tf>`: runs the sweep's cached signals (is/oos/final) through the sweep engine
  (`harness/vendor/engine.py`, same costs: taker 0.05%/side, slippage 0.02%/market fill, funding 0.01%/8h)
  with two exits: TIME_H (H = 16 bars) and ATR_SL2_TP3 (stop 2 ATR, target 3 ATR, max 64 bars).
  One position per coin, 1x notional. Longs and shorts both traded. Per-split table: `trade_stats_<tf>.csv`.
- `pool.py`: pools the three windows (2021-08 .. 2026-09) per strategy x TF x exit -> `pooled_5y.csv`
  (win rate, avg win/loss, payoff, PF gross/net, expectancy gross/net, long vs short, max drawdown of the
  cumulative 1x trade P&L, positive years). "gross" = before fees and funding but after slippage.
  The per-trade dumps (`trades_<tf>.csv.gz`, 5m ~90 MB) were not committed.
- `random_baseline.py <tf> <target trades> <seeds>`: random +/-1 entries at a similar rate, same engine,
  exits and costs, same 5 years -> `random_all.csv`.

Result (ATR_SL2_TP3, median over strategies vs random entries): win rate 38-40% vs 38-41%, PF after costs
5m 0.71 vs 0.71, 15m 0.81 vs 0.82, 30m 0.85 vs 0.85, 1h 0.87 vs 0.90, 4h 0.90 vs 0.90, 1d 0.82 vs 0.92.
The strategies trade like random entries; the loss per trade is the cost. On 1d with TIME_H, random LONG
entries earn +0.71%/trade (2021-2026 market drift) while random shorts lose -1.76%, which is why some 1d
trend strategies show PF 1.2-1.37 over 5 years; the random-entry PF 95th percentile there is 1.33 (max 1.71).
