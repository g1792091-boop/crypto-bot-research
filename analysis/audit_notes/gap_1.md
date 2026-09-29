# GAP-FILL CHECK #1: pre-registered out-of-sample test of Option B (V4.5 slow maker variant)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/gap_1`
Nothing under `/home/user/crypto-bot-research` was modified (data read only via symlinks in `data_is/`).
Only Astral tool used: `astral_price_get` (read-only), 15 calls, all `limit=40000` + `end` (never start+end), `delivery=download`.

## Bottom line

**Option B fails its one pre-registered out-of-sample test decisively. No reasonable choice of window or exit variant changes that.**

| | In-sample (discovery, 2026-05-13..09-29) | Out-of-sample (2025-03-20..2026-05-12, never seen) |
|---|---|---|
| trades (1 pos/symbol) | 618 | 1,936 |
| net per trade (primary: maker entry, limit exit + taker fallback, no stop) | **+0.1046%** | **-0.0481%** |
| PF | 1.290 | 0.913 |
| symbols positive | 3/3 | **0/3** (BTC -0.022, ETH -0.054, SOL -0.066 %/trade) |
| common-shift null mean / SD | -0.0382 / 0.0703 | -0.0443 / 0.0492 |
| z vs null, p = (1+k)/301 | 2.03, p = 0.020 | **-0.08, p = 0.518** (155/300 null reps >= real) |
| null reps that pass the rule | 2.7% | 0.0% |
| rule verdict | would PASS | **FAIL on every clause** |
| cost-free fwd64 drift, all signals | +0.1353% (BTC +0.090, ETH +0.140, SOL +0.178; t 2.8-3.0) | **-0.0319%** (BTC +0.008, ETH -0.045, SOL -0.058; t 0.31 / -1.10 / -1.36) |

- The critic's own `b_null.py`, run once on the new files, agrees: maker exit z = -0.07, p = 0.53; taker exit z = +0.03, p = 0.47 (`out/OOS_b_null_stdout.txt`).
- The handoff's "only faint signal" (V4.5 exact AM+B 64-bar drift) does not replicate. The whole horizon profile is flat out of sample: fwd1..fwd32 are all within +-0.007%, and fwd64 is -0.032% (`out/fwd_is_oos.txt`).

## Pre-registration (done before any out-of-sample byte was fetched)

- `PREREG.md`, written at 2026-09-29 08:05Z. `PREREG.sha256` froze the hashes of PREREG.md and of every script. The first Astral call was at 08:05:14Z, and `sha256sum -c PREREG.sha256` passed again just before the run.
- **Contamination check before fetching.** `find` over every auditor's scratch dir showed that no one in this session held 5m data before 2026-05-12. The existing files start 2025-08-07 (15m), 2026-05-12/13 (5m) and 2026-08-31 (1m).
- **Primary rule (the only configuration that decides):**
  - Entry: `strategies.v45_exact_amb`. Maker limit at c[i], valid bars i+1..i+3, fills on trade-through at the limit or at a better gap open.
  - Exit: scheduled at o[i+65]. Limit at that open, valid 3 bars on trade-through; otherwise taker at o[ex+3] with 0.02% slippage.
  - **No stop** (chosen before the run).
  - Costs: maker 0.02%, taker 0.05%, no funding. This is the same cost model as the in-sample number being replicated.
  - One position per symbol, 1000-bar warm-up.
  - PASS requires all of: pooled PF >= 1.2, n >= 100, mean > 0, 3/3 symbols positive, and p < 0.05 against a common circular-shift null (300 reps, seed 20260929).
- **Validation on in-sample data before freezing** (`out/IS_validation_result.json`). The script reproduces the earlier numbers exactly:
  - `critic/work/limit_fill2.csv`: limit_fallback 618 trades / +0.10458% / PF 1.2900; taker +0.05705 / 1.1491; maker-at-open +0.10708 / 1.2985; 6-ATR 621 / +0.0875 / 1.2333.
  - The delivered `results/forward_ALL_5m_v45.csv` fwd64 values.
- `b_null_oos.py` is the critic's `b_null.py` with two changes only: the data path comes from an env var, and the hard-coded rolled length 39000 becomes M. On the in-sample data it reproduces the critic exactly (z 2.01, p 0.023, pass rate 3.7%; taker z 2.08, p 0.013).

## Data (all sha-verified against the Astral artifact sha256; `data_oos/raw/SHA_EXPECTED.txt`)

| pull | call | bars | range (bar open, UTC) |
|---|---|---|---|
| 5m p1 x3 | limit 40000, end 2026-05-12T00:00Z | 40,000 each | 2025-12-23 02:35 .. 2026-05-11 23:55 |
| 5m p2 x3 | limit 40000, end 2025-12-23T02:35Z | 40,000 each | 2025-08-06 05:15 .. 2025-12-23 02:30 |
| 5m p3 x3 | limit 40000, end 2025-08-06T05:15Z | 40,000 each | 2025-03-20 07:55 .. 2025-08-06 05:10 (SOL from 2025-03-19 07:50) |
| 15m q1 x3 | limit 40000, end 2026-05-12T00:00Z | 40,000 each | 2025-03-20 07:45 .. 2026-05-11 23:45 (SOL from 03-19) |
| 15m q2 x3 | limit 40000, end = q1 start | 40,000 each | 2024-01-28 .. 2025-03-20 (warm-up) |

- `end` is exclusive: the last bar returned opens 5 minutes before `end`. So seams have no overlap, and they are continuous (5-minute step across both seams).
- Gates (`data_oos/gates.json`):
  - G1: 15/15 sha OK.
  - G3: the 5m data resampled to open-labelled 15m equals the 15m pull on **100.00%** of the 39,997-39,998 complete buckets per symbol, including volume.
  - G4: the fetched 15m data is **identical** to the delivered 15m files on all 26,550-26,553 common bars, so there has been no vendor revision.
  - G5: every 5m bar is before 2026-05-12.
- Gaps:
  - All three 5m series have the 1,445-minute hole at 2026-04-21 23:55 (the same outage as in the 15m files).
  - SOL also has a 1-day hole on 2025-03-24/25.
  - There are two 10-minute holes.
  - No flat bars.
- **By-product (in-sample data quality).** In the delivered in-sample files, BTC 5m resampled to 15m matches the BTC 15m file on only 98.35% of bars:
  - 220 mismatching bars, 192 of them in Aug 2026 and 28 in Sep 2026, with a median |diff| of 0.014%.
  - ETH and SOL match 99.94%, with mismatches only in the last week.
  - So the IS 5m and 15m exports come from slightly different vendor snapshots. The impact on V4.5 in-sample signals is probably negligible, and the out-of-sample files have no such inconsistency. See `out/is_5m15m_consistency.txt`.

## Secondary results (pre-registered, non-decisive), all out of sample

| variant | n | net %/trade | PF | symbols + |
|---|---|---|---|---|
| taker exit | 1936 | -0.0925 | 0.840 | 0/3 |
| maker exit at open (optimistic) | 1936 | -0.0425 | 0.923 | 0/3 |
| primary + 6-ATR(5m) stop | 1947 | -0.0453 | 0.916 | 0/3 |
| primary + funding 0.01%/8h | 1936 | -0.0548 | 0.902 | 0/3 |

- Mechanics behave the same as in-sample: entry fill rate is 99.06% (IS 98.66%), exit maker fill is 98.3% (IS 99.0%), and the maker-minus-taker gap is 0.050% (IS 0.048%). **The mechanics are not the binding constraint; the absence of edge is.**
- Per pull (pre-registered split):
  - p3 (Mar-Aug 2025): -0.093%, PF 0.84, 0/3.
  - p2 (Aug-Dec 2025): -0.087%, PF 0.86, 1/3.
  - p1 (Dec 2025-May 2026, adjacent to IS): +0.031%, PF 1.07, t 0.59, 2/3.
  - **First 9.2 months (the task's own plan, p1+p2): -0.026%, PF 0.95, 2/3.** It fails too, so fetching 13.9 months instead of 9 does not drive the verdict.
- 7 of 15 months are positive.
- Signal rate is 367 per 30 days, against 355 per 30 days in-sample. The long share is 0.46 (IS 0.49).

## Post-hoc descriptives (labelled as such; they do not change the pre-registered verdict)

- **Where the in-sample edge came from.** It was entirely on the long side: longs +0.240%/trade (t 3.24, PF 1.73, n 304), shorts -0.026% (n 314). Out of sample: longs -0.052%, shorts -0.045%.
- **Excluding the Apr-2025 tariff-crash months** (2025-03/04, -0.40%/trade over 157 trades): -0.013%, PF 0.975, 1/3. Still a fail.
- **Effect size.** In-sample excess over the null is +0.143% (SD 0.070). Out-of-sample excess is -0.004% (SD 0.049).
  - Out of sample rejects the full in-sample excess at z = 2.98 and half of it at z = 1.53.
  - The one-sided 95% upper bound on out-of-sample excess is +0.077%, which is a net of **+0.033%/trade at best**. That is below the roughly +0.07%/trade that PF 1.2 requires.
  - Inverse-variance pooled IS+OOS excess: +0.044 +- 0.040 (z = 1.10).
  - IS-vs-OOS difference: z = 1.71. This fits the in-sample result being a post-scan ~2-sigma fluctuation (the horizon and variant were chosen after looking).
- **In-sample t-stats were overstated.** The null SD of the mean (0.0703) is 1.45x the iid SE (1.206%/sqrt(618) = 0.0485), a design effect of 2.1. The handoff's "t 2.8-3.1" per symbol corresponds to an effective t of about 2 at the pooled level.

## Power (pre-fetch; `work/power2.py`: bootstrap of IS trades plus clustering variance matched to the IS null SD)

- The task's power figures (65% at 4.5 months, 89% at 9 months, 42% at 9 months with half the effect) are for the **null-test clause only**. I reproduce them: 66%, 90%, 42%.
- Full-rule power is lower, because PF >= 1.2 binds:

| sample | IS effect | 3/4 effect | 1/2 effect | zero (false pass) |
|---|---|---|---|---|
| 4.5 mo | 0.60 | 0.39 | 0.22 | 0.037 |
| 9.2 mo | 0.70 | 0.43 | 0.19 | 0.008 |
| 13.9 mo | 0.76 | 0.44 | 0.15 | 0.001 |

- Even so, the observed result (z = -0.08, mean below the null mean) is not a power failure. It lies about 3 null SDs below the in-sample effect.

## Deviations from the task text (all decided before fetching and written in PREREG.md)

1. I fetched 3 x 40,000 5m bars (13.9 months) instead of about 9 months, for more power. The 9.2-month split is reported and also fails.
2. I fetched 15m fresh (2 pulls) instead of using the existing files. They start 2025-08-07, which is too late for the 5m data from Mar 2025. The fetched 15m is byte-for-byte equal in OHLC to the delivered files on the overlap.
3. The p-value is (1+k)/(R+1) rather than k/R. With k = 155 this makes no practical difference.
4. `b_null.py` changed only in its data path and its rolled-length constant.

## Caveats

- The out-of-sample window is earlier in time than the in-sample window (a backward holdout). The regimes differ: the 2025 bull run, the Apr-2025 and Oct-10-2025 crashes, and the Feb-2026 drawdown.
  - The segment adjacent to in-sample (p1) is also below the rule (PF 1.07, t 0.59).
  - A true forward test would need live or paper data after 2026-09-29.
- Everything here uses Polygon-aggregated spot data, not the Binance USDT-M perp. Maker queue position, post-only rejects and basis are not modelled. All of these would make results worse, not better.
- The maker exit fill at o[ex] on trade-through is mildly optimistic, but it barely matters (only 1-1.7% fall back to taker).

## Files

- `PREREG.md`, `PREREG.sha256`: the frozen rule and hashes.
- `work/prereg_b.py`: primary and secondary. `work/b_null_oos.py`. `work/stitch_check.py`: stitching and gates. `work/power2.py`. `work/post_splits.py`. `work/fwd_oos.py`.
- `data_oos/raw/*`: 15 sha-verified pulls. `data_oos/*-ohlcv.csv`: stitched files. `data_oos/gates.json`.
- `out/OOS_primary_result.json`, `out/OOS_primary_primary_trades.csv`, `out/OOS_primary_null.csv`, `out/OOS_primary_stdout.txt`.
- `out/OOS_b_null_stdout.txt`, `out/post_splits.txt`, `out/fwd_is_oos.txt`, `out/is_5m15m_consistency.txt`.
- `out/IS_validation_*`: the same script on the in-sample data.
