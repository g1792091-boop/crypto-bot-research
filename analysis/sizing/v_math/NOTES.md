# Adversarial verification of TASK A (constraint math)

Scope: I independently recomputed the headline numbers of `sizing/math` with my own code. Scripts are in `v_math/work/`, and their stdout is in `v_math/out/`.

- **Data read:** only `sweep/data/is/<sym>-<tf>.csv` (IS, bars before 2024-07-01).
- **Not touched:** OOS/final data were never read, the repo was not modified, and there were no Astral calls.
- **Load:** one light Python process at a time.

## What I re-implemented (different code paths from the author)

- **`v1_basic.py`: closed forms, ATR and moves.**
  - Liquidation distance, the exact isolated formula, TP distance, fee share of the TP, fee drag and liquidation loss.
  - ATR via pandas ewm (alpha = 1/14) and |close-to-close| moves.
  - ATR-adaptive L and the share of bars where 20x keeps liquidation at least 3 ATR away.
- **`v2_sim.py`: zero-edge bracket.**
  - A loop-based first-passage search with expanding windows. The author used sparse-table binary lifting.
  - Funding is counted by the 00/08/16 UTC settlement stamps crossed. The author pro-rated it.
  - The se is a cluster bootstrap over coin × week. The author used an analytic clustered se.
  - Runs: 5m own-bar and 1h own-bar at 20x and 50x; 1h entries on 5m paths; 1d (00 UTC, official file) own-bar and on 5m; 4h own-bar.
- **`v3_drift.py`: drift-injection break-even at 20x and 50x.**
  - The drift is applied by elapsed time. The author applied it by bar count.
  - Different random entries from the author's.
- **`v4_misc.py`: remaining checks.**
  - MAE liquidation odds, using pandas rolling.
  - The zero-edge baseline by entry hour (00/06/12/18 UTC, 5m paths, 20x).
  - A stop at 0.5×d_liq.
  - The binomial 100-trade medians, P(equity < 50%), and the Kelly and E[log] thresholds.
- **`v5_bm.py`: closed-form break-even IR** for Brownian motion with drift (homoskedastic).
- **`v6_localvol.py`: break-even IR when the injected drift scales with local vol** (trailing 1-day sd, known at entry).

## Results versus the author

| quantity | author | verifier |
|---|---|---|
| d_liq 5/20/50x | 19.5/4.5/1.5% | same |
| TP 20/50x | 0.5/0.2% | same |
| fee drag 20%×20x, 40%×50x (% equity) | 0.56, 2.80 | 0.56, 2.80 |
| fee share of TP | 0.014·L | same |
| liq loss 20%×20x (% equity) | 20.3 | 20.28 |
| median ATR14 5m/15m/30m/1h/4h/1d | .303/.533/.763/1.101/2.329/6.129 | .303/.533/.763/1.101/2.329/6.139 |
| BTC ATR 4h / 1d | 1.663/4.424 | 1.663/4.424 |
| liq/ATR, TP/ATR at 1d 20x | 0.73, 0.08 | 0.733, 0.0815 |
| share of bars with 20x ≥ 3 ATR: 4h / 1d | 16% / 0% | 16.1% / 0.0% |
| median L = 1/(3ATR + 0.5%) | 71/48/36/26/13/5.3 | 71.0/47.6/35.9/26.3/13.4/5.29 |
| 5m 20x: P(TP), E[ROE] | 0.900, −3.81% | 0.9002, −3.81% (bootstrap se 0.20 at 35k entries) |
| 5m 50x: P(TP), E[ROE] | 0.884, −9.40% | 0.8838, −9.45% |
| 1h own-bar 20x adv/fav E[ROE] | −4.1 / −3.7 | −3.90 / −3.58 |
| 1h own-bar 50x adv/fav E[ROE] | −14.0 / −8.1 | −14.00 / −8.17 |
| 1h entries on 5m paths, 20x / 50x | −3.81 / −8.90 | −3.65 / −8.94 |
| 4h own-bar 20x adv/fav; ends in entry bar | −5.5 / −3.0; 68.9% | −5.50 / −2.95; 68.9% |
| 1d own-bar 20x: ambiguous; adv/fav | 17.5%; −21.1 / −2.1 (4 anchors) | 17.85%; −20.3 / −0.9 (00 UTC only) |
| 1d 20x on 5m paths | −3.35 (4 anchors) | 00/06/12/18 UTC: −2.26/−3.81/−2.99/−4.26, mean −3.33 |
| net TP ROE / liq ROE at 20x | +7.07 / −101.9 | +7.07 / −101.9 |
| P(liq) holding 1 daily bar, 20x / 50x | 22.2% / 63.4% | 22.23% / 63.39% |
| P(liq) holding 16 bars, 4h 20x / 1h 20x | 42.0% / 15.9% | 41.99% / 15.95% |
| break-even P(TP): 20x / 50x | 0.935 / 0.972 | 0.9351 / 0.9724 |
| injected-drift break-even IR: 20x / 50x | 3.7 / 62.8 | 4.07 and 4.09 (two samples) / 63.5 |
| P(TP) at injected break-even: 20x / 50x | 0.9348 / 0.972 | 0.9347 / 0.9720 |
| Kelly P for M = 20% @20x, full / half | 0.948 / 0.962 | 0.9483 / 0.9616 |
| Kelly P for M = 40% @20x, full / half | 0.962 / 0.988 | 0.9616 / 0.9880 |
| Kelly f at the free p (20x) | −0.53 | −0.528 |
| E[log] ≥ 0 P: 20% / 40% @20x | 0.942 / 0.950 | 0.942 / 0.949 |
| median multiple after 100 trades, 20% / 40% @20x | 0.36 / 0.065 | 0.362 / 0.0655 |
| median multiple after 100 trades, 20% / 40% @50x | 0.13 / 0.008 | 0.131 / 0.0078 |
| P(equity < 50%): 20% / 40% @20x | 68% / 88% | 67.7% / 88.2% |
| P(equity < 50%) at 50x | 98–99.8% | 98.0% / 99.8% |
| median at break-even, 20% / 40% @20x | 0.95 / 0.59 | 0.954 / 0.595 |
| stop at 0.5×d_liq, 20x: P(TP), E[ROE] | 0.819, −2.85% | 0.823, −2.64% (sampling, se ≈ 0.2) |
| maker TP gain, 20x / 50x | +0.9 / +2.2 pp | +0.90 / +2.21 pp (analytic) |

## Error checks

- **ROE vs price.** Correct. TP = 10%/L in price, and ROE = L × price return.
- **Leverage double-counting.** None. Equity change = M × ROE, and notional = M × L.
- **Fees on margin instead of notional.** No. Fees in ROE = L × 0.07% per fill, i.e. charged on notional.
- **Planted-edge oracle.** This task has none. The drift injection uses only the time elapsed since entry, so there is no look-ahead.
- **Standard errors.** No bootstrap is used. The analytic clustered se (0.16 at 80k) is consistent with my cluster bootstrap (0.20 at 35k ≈ 0.13 at 80k).

## Corrections and missed points

1. **The required IR of 3.7 at 20x is the most lenient measure, and it is sampling-noisy.**
   - My samples give 4.07–4.09 under the author's own definition (constant drift, pooled σ).
   - A drift that scales with local vol needs an IR of about 6.1.
   - Homoskedastic Brownian motion (closed form) needs 7.5.
   - The cause is heteroskedasticity: long trades happen in quiet periods, where a constant drift is worth more.
   - This strengthens the conclusion.
2. **The zero-edge baseline depends on entry timing.**
   - At 20x on 5m paths, daily entries give P(TP) 0.914 at 00 UTC and 0.896 at 18 UTC. E[ROE] is −2.26% at 00 UTC and −4.26% at 18 UTC, with se about 0.26.
   - The stated "−3.2 to −3.8% at 20x" holds only for pooled samples. Every subset is still negative.
   - A time-of-day entry rule could show about +1.4 pp of "free" P(TP), which is still far below the +3.5 pp needed.
3. **The caveat about the exact liquidation formula is misquoted.** "(1/L − MMR)/(1 ± MMR) differs by < 0.01 pp" is wrong. The difference is 0.023 pp at 20x, 0.098 pp at 5x and 0.0075 pp at 50x. The effect on results is negligible.
4. **Funding is charged on top of a full-margin liquidation** (−101.9% at 20x includes about 0.5% of funding). In isolated mode, funding comes out of the position margin, so the loss is capped at margin plus fees. The model is conservative by about 0.05 pp of E[ROE], which is negligible.
5. **The compatibility labels are internally inconsistent.**
   - "15m fails from 40x" contradicts the author's own fee criterion, under which every TF fails from 25x.
   - The "5m–30m at 20–24x" zone is too wide for 30m. P(liq within 16 bars) on 30m is:

     | L | P(liq, 16 bars) |
     |---|---|
     | 20x | 8.0% |
     | 21x | 9.0% |
     | 22x | 9.96% |
     | 23x | 11.0% |
     | 24x | 12.0% |

     So 30m passes the author's 10% criterion only up to about 22x.
6. **The median at break-even edge for 40%×20x (0.595) is knife-edge.** P(losses ≤ 6) is 0.526. With 7 losses the multiple would be 0.34.
7. **4h/1d wording.** "A daily signal cannot influence the outcome" is too absolute. Direction is still chosen by the signal, but the bracket resolves on a 0.5% move within hours, so a daily-scale edge has almost no time to act.
8. **Observed edges.** ANALYSIS_KO §5 says all observed edges are ≤ 0, but the same section cites one IS-positive ledger (B IS, +0.105%/trade). "All ≤ 0" applies out of sample.
9. **TP interpretation.** The TP is taken as gross ROE as Binance displays it. If the user means net ROE, the TP distance at 20x is about 0.64%. The conclusions do not change.
10. **Not re-verified:** the neutralisation of suspect bars. I did not read `sweep/data/suspects.csv` because it was outside the permitted read set.
