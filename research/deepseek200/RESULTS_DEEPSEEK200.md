# DeepSeek 200 B-class strategies: results on 5 years of data

Run on 2026-10-05, after the PREREG was committed (commit 31baa17).
Code sha256 and PREREG sha256 are in `out/summary.json`. Nothing was changed after seeing results.

## Verdict

**0 candidates out of 342 configurations.** No strategy passed the pre-registered gauntlet.

| Gate | Passed |
|---|---|
| Stage 1 (period 1) | 2 |
| Stage 2 (period 2) | 0 |
| Stage 3 (period 3) | 0 |
| BH FDR 10% over all 342 | 0 |
| Candidate / weak candidate | 0 / 0 |

## Why

Mean net result per trade, by timeframe (all periods negative):

| TF | Net per trade, period 1 | Net per trade, period 2 | Gross per trade (before costs), period 1 |
|---|---|---|---|
| 15m | -0.149% | -0.144% | -0.045% |
| 30m | -0.162% | -0.152% | -0.055% |
| 1h | -0.176% | -0.159% | -0.060% |
| 4h | -0.183% | -0.199% | -0.020% |

Gross is already negative before costs. The strategies as defined carry no edge.
Costs (about 0.10-0.16% per trade) then make every timeframe lose.

## Near misses

- The only two configurations that passed stage 1 were 4h F1_RSI_DIV (X2 exit) and 4h F10_M2022 (X5 exit). Both failed stage 2.
- 12 of 342 configurations have a positive pooled net mean. With 342 tests, about that many are expected by luck. The best of them have 139 to 884 trades and are negative in period 3.
- Families F4 (EMA pullback) and F1 (divergence) lose least, but still lose.

## Limits

- Exits tested were ATR stop plus trailing or take-profit, not the live ladder.
- Rare signals (F5_BOX_RSI, F10_M2022) have too few trades for a strong statement. That is a power limit, not proof of no edge.
- Rules were coded from text descriptions. A different reading of a discretionary rule could behave differently.
- 5m timeframe and 1-minute strategies were not tested.

## Consequence

No new paper accounts are proposed from this list. The ledger records 342 more failed trials.
Raw outputs: `out/results.csv`, `per_family.csv`, `per_tf.csv`, `near_miss.csv`, `data_manifest.json`.
