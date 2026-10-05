# Reel 5m BB(20,2) + MA200 strategy: results on 5 years of data

Run on 2026-10-05 after the PREREG was committed (ef31879). Code and PREREG sha256 are in `out/summary.json`.

## Verdict

**H1 fails. 0 candidates out of 40 configurations.**

H1 is the reel exactly as shown: 5m, SMA200 filter, close below the lower band, long only, swing-low stop, upper-band target.

| Period | Trades | Win rate | Net per trade | Gross per trade (before costs) |
|---|---|---|---|---|
| 1 (2021-08 to 2024-07) | 19,959 | 33.9% | -0.123% | +0.011% |
| 2 (2024-07 to 2026-09) | 15,899 | 31.7% | -0.127% | +0.007% |
| 3 (2020-01 to 2021-08) | 9,261 | 35.0% | -0.133% | +0.001% |

- Before costs the strategy is almost exactly break-even (+0.001% to +0.011% per trade).
- Costs are about 0.13% per trade, so every period loses about 0.12-0.13% per trade.
- 64-67% of trades hit the stop. The median stop is only 0.27-0.32% away, so costs are large relative to the move.
- Every timeframe (5m, 15m, 30m, 1h, 4h) and every variant (EMA200, wick breach, long + short) is negative in periods 1 and 2.

## Liquidation before the stop

At 30x, 5 of 15,899 period-2 trades would have been liquidated before the stop; at 50x, 63.

## Consequence

The live v4 reel account still runs, by the owners' decision, as a forward test against its own 5m coin flips.
The 5-year result is the prior: expect it to lose about 0.12% per trade after costs.
