# Adversarial verification of test "short" (t_short)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/v_short`

- No Astral tools were called. `astral_backtest_start` only accepts start, end, capital, commission_bps and slippage_bps overrides; there is no `allow_shorts` override. So Astral's own short behaviour cannot be tested with the allowed tools.
- Nothing under /home/user/crypto-bot-research was touched.
- The port (`doge_strategy.py`, sha256 800660e7...) was copied here unmodified. No port bug was found.

## Verdict

The tester's conclusion holds: allowing shorts does not raise the win rate. After realistic costs it makes the result much worse. Every headline number was reproduced exactly by an independent re-implementation.

Corrections and additions:

1. **Zero-cost profit.** The short stream's mean is slightly positive, though not significantly. So at zero cost, adding shorts did raise in-sample total profit:
   - 2022-06..2026-09, 25% sizing: +4.86% → +6.37%.
   - 2021-08..2026-09: +7.12% → +10.67%.
   - The claim "shorts don't raise profit" holds per trade, and after costs. It does not hold for zero-cost totals.
2. **The half-sample ranking flips.** In 2024-07..2026-09, with its own seeding:
   - Short beats long per trade: +0.0063% vs −0.0006%.
   - Adding shorts raises zero-cost total from −0.19% to +1.50%.
   - Win rate is still lower: 46.0% vs 46.9%.
   - All of these numbers are statistically zero.
3. **The post-hoc "prior 7-day ≥ +12.8%" pocket (F6) fails a holdout.** In 2021-08..2022-05, which was not used to find it, it gives n=181, WR 42.5%, −0.0024%/trade (t −0.06).
4. **F8 overstates the 1m result.** Under the per-minute adverse-first ordering, the 1m walk makes the short side better than Astral's coarse model: −0.0186% vs −0.0316%. The both-sides result is unchanged (−0.0096% vs −0.0099%). Only the favourable-first ordering gives −0.052%.
5. **Short-side intrabar order is an unvalidated assumption.** The port mirrors the favourable-first path for shorts. A literal O→H→L path applied to a short checks the adverse high first, and that gives WR 39.4% (vs 45.3%) and +0.0063%/trade (vs +0.0031%). The win-rate conclusion gets stronger; the mean stays zero.
6. **The short side's "wrong sign" versus monthly buy&hold (r=+0.11) is noise.** Excluding the 3 most extreme months gives r=−0.03.

## What was checked, and results

| check | script / output | result |
|---|---|---|
| Independent re-implementation, written without importing the port: lfilter EMA, loop Wilder RSI, sliding-window min/max, own trade loop | `indep_sim.py`, `cmp_main.py` | long 1861/1861, short 1957/1957 and both 3818/3818 trades have identical entry and exit; max \|Δgross\| 1e-16. WR 46.43 / 45.27 / 45.84%; mean +0.0104 / +0.0031 / +0.0066%; t +1.17 / +0.38 / +1.11; PF 1.0824 / 1.0251 / 1.0535. Real cost: −0.1298 / −0.1371 / −0.1336%, total@25% −45.39 / −48.92 / −72.10%. The per-year table is identical. Both = union(long, short) holds exactly. |
| Look-ahead truncation test | `trunc_test.py` | 25 cut points: indicators on data[:k+1] equal the full-sample values (diff 0). The signal prefix has 0 mismatches. 5 cuts × 2 sides (8,690 trades) give identical trade lists. Port vs independent indicators agree to 1.9e-12. |
| 20 trades checked by hand against raw CSV rows, parsed with the csv module | `hand20.py` | 20/20 correct: 10 long, 10 short (4 from the friend's window), 8 conditions each, and the stop arithmetic bar by bar. Example: short 2026-09-28 00:35 @0.09636. Stop is 0.0966473 after the 00:40 low 0.09631. The 00:45 high 0.0975 triggers it, and the fill at close 0.09746 gives −1.1416%. |
| Friend's window (indicators from 09-11, 660-bar warmup) | `window_slices.py` | 40 long / 20 short signals. Short: WR 25%, −0.1222%/trade, sum −2.44%, total@25% −0.610%. Both: WR 45%, total −0.239%. At a 0.14% round trip: −1.023% (long) and −2.313% (both). Seeding from 2022-06 gives the same 20 shorts. On the 1m walk: −0.1020% / −0.1034%. DOGE moved −6.04% from 09-13 07:00 to 09-16 08:00, then +18.34%. |
| Short-order sensitivity (adverse first) | `window_slices.py` | Main: WR 39.4%, +0.0063% (t 0.60). Window: −0.0985%/trade. |
| Other slices, each with its own seeding | `window_slices.py` | 2021-08..2022-05: long 47.4% / +0.0247%, short 44.4% / +0.0190%. 2022-06..2024-06: long 45.9% / +0.0228%, short 44.4% / −0.0010%. 2024-07..2026-09: long 46.9% / −0.0006%, short 46.0% / +0.0063%. 2021-08..2026-09: long +0.0126%, short +0.0057%, both +0.0091% (total@25% +7.12 / +3.31 / +10.67%). |
| Regime correlations, 52 months | `regime_check.py` | long_sum r=+0.548 (p 2.6e-5); short_sum r=+0.106 (p 0.45); short_n r=−0.373. Excluding the 3 most extreme months: long r=+0.451, short r=−0.030. Up/down months: long +0.0314 / −0.0220; short +0.0003 / +0.0051. |
| Random-entry null | `regime_check.py`, `last_checks.py` | The tester's per-bar outcome file matches my own walker on 2×2000 random bars (diff 0). Same-month N2 null: long excess +0.0104% (t_cl 1.24), short +0.0055% (t_cl 0.77). With a finer same-week null: long +0.0082% (t_cl 0.97), short +0.0037% (t_cl 0.52). Short forward-return excess: h=12 bars +0.035% (t_cl 1.70); all other horizons below 0.6. |
| Prior 7-day quintiles | `regime_check.py`, `extra_checks.py` | Top quintile (≥+12.79%): n=763, WR 51.4%, +0.0555%. Holdout 2021-08..2022-05: −0.0024% (t −0.06, n=181). |
| Rolling 16-day windows | `extra_checks.py` | 1563 windows; 24.4% have long WR ≥55%. Friend's window percentiles: long WR 75.6, long sum 84.0, short sum 4.9. Adding shorts raised WR in 49.9% of windows. Non-overlapping (98 blocks): 21.4% and 49.0%. |
| Independent 1m walk, 2026-05-13..09-28 | `walk1m.py` | Favourable first: long −0.0300%, short −0.0519% (t −3.26), both −0.0418%. Adverse first: long +0.0008%, short −0.0186%, both −0.0096%. |
| Cross-asset, 2025-03-19..2026-09-28 | `extra_checks.py` | Short WR is below long WR on BTC, SOL, XRP and DOGE, and above it on ETH (46.8 vs 42.7%). No asset has a significantly positive short mean; XRP short is −0.0345% (t −2.56). |
| Costs | `cmp_main.py` | Real − gross = 0.1402%/trade: a 0.14% round trip plus about 0.0002% funding. There is no double counting. Break-even round trip = gross mean. |

## Files
- `indep_sim.py`: independent simulator (long/short/both, `short_order` option).
- `cmp_main.py`: main-sample comparison and per-year table; writes `my_main_{long,short,both}.csv`.
- `trunc_test.py`: look-ahead truncation tests.
- `hand20.py`: 20-trade hand check.
- `window_slices.py`: friend's window, short-order sensitivity, other slices; writes `my_window_short.csv`.
- `regime_check.py`: regime correlations, null check, prior-7d quintiles.
- `walk1m.py`: independent 1m walk.
- `extra_checks.py`: rolling windows, prior-7d holdout, cross-asset.
- `last_checks.py`: window seeding, window 1m walk, forward returns.
