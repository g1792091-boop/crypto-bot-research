# DOGE investigation: DATA notes (2026-09-29)

Data dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/data`

- Machine-readable detail for every file is in `MANIFEST.json`: rows, first/last timestamp, sha256, gaps, missing ranges ≥1h, missing bars inside the strategy window, rows by source, and all 45 raw pull hashes.
- Every number below was produced by the scripts in `tools/` against the files listed here.

## Bottom line

**Clean DOGEUSD 5m history**
- Recommended start: **2021-08-01**. That gives **542,670 bars ≈ 5.16 years** to 2026-09-29T09:15, with 322 missing slots (0.059%).
- For tick-sensitive trailing-stop work, start at **2022-06-01**: 455,118 bars ≈ 4.33 years, same 322 missing slots.

**Before 2021-08-01 the data is unusable**
- Jan–Jun 2021 is corrupted by cross-venue mixing: in 2021Q2 the median bar range is 26.3%, with 5,113 open-vs-previous-close jumps above 2% and 3,129 three-percent spike-and-revert bars.
- Isolated bad wicks continue through July 2021.

**The strategy window is complete in the aggregated timeframes**
- For 2026-09-13..09-28, the DOGE 5m, 15m and 1h files are complete: 4608/4608, 1536/1536 and 384/384 bars.
- DOGE 1m is missing 15 of 23,040 minutes in that window. These are sporadic single no-trade minutes.

**Vendor problems that matter**
- One whole day (2026-04-22) is missing in every Astral crypto series.
- Recent bars keep being revised for hours. For ETH, bars about 36 hours old had changed between a 03:57 pull and a 09:40 pull.
- DOGE's own last-48h bars were identical across two pulls taken about 20 minutes apart. That is too short a gap to rule out the same revision problem.

## Final files

| file | rows | range (UTC, bar open) | missing slots | gap events | max gap | missing in 09-13..09-28 | sha256 (first 16) | clean_from |
|---|---|---|---|---|---|---|---|---|
| dogeusd-5m-ohlcv.csv | 603,677 | 2021-01-01T00:00 → 2026-09-29T09:15 | 371 (0.061%) | 68 | 1d 00:05 | 0 | 6d87c81730b546c9 | 2021-08-01 (tick: 2022-06-01) |
| dogeusd-15m-ohlcv.csv | 201,249 | 2021-01-01T00:00 → 2026-09-29T09:00 | 100 | 2 | 1d 00:15 | 0 | 3b3f7d3559f593ca | 2021-08-01 |
| dogeusd-1h-ohlcv.csv | 50,312 | 2021-01-01T00:00 → 2026-09-29T08:00 | 25 | 2 | 1d 01:00 | 0 | 031114e44b97df38 | 2021-08-01 |
| dogeusd-1m-ohlcv.csv | 40,000 | 2026-09-01T14:24 → 2026-09-29T09:29 | 26 | 25 | 3 min | 15 | 15ed2d6e322ea500 | file start |
| btcusd-5m-ohlcv.csv | 160,819 | 2025-03-19T00:00 → 2026-09-29T09:35 | 289 | 2 | 1d 00:05 | 0 | d167deed62f52ad1 | 2025-03-19 |
| ethusd-5m-ohlcv.csv | 160,817 | 2025-03-19T00:00 → 2026-09-29T09:25 | 289 | 2 | 1d 00:05 | 0 | 481d232c0a6c3a62 | 2025-03-19 |
| solusd-5m-ohlcv.csv | 160,527 | 2025-03-19T00:00 → 2026-09-29T09:25 | 579 | 5 | 1d 00:05 | 1 (09-14 23:35) | ed5e5d20c45e1a3c | 2025-03-26 if continuity needed |
| xrpusd-5m-ohlcv.csv | 160,527 | 2025-03-19T00:00 → 2026-09-29T09:25 | 579 | 5 | 1d 00:05 | 0 | a3ade09fd171dba1 | 2025-03-26 if continuity needed |
| ltcusd-5m-ohlcv.csv | 160,529 | 2025-03-19T00:00 → 2026-09-29T09:30 | 578 | 4 | 1d 00:05 | 0 | 41d13151c2d27380 | 2025-03-26 if continuity needed |
| bchusd-5m-ohlcv.csv | 160,545 | 2025-03-19T00:00 → 2026-09-29T09:35 | 563 | 173 | 1d 00:05 | 0 | e53248299f4bb18f | 2025-03-19 |

- Columns: `timestamp,open,high,low,close,volume`. Timestamps are UTC bar-open, formatted like `2026-05-13T05:10:00+0000`.
- Every file has 0 duplicates, 0 OHLC-inconsistent rows, 0 NaN and 0 bars with volume ≤ 0.
- Gaps of 1 hour or more:
  - All files: 2026-04-22 00:00–23:55 (288 bars).
  - SOL, XRP and LTC: also 2025-03-25 00:00–23:55 (288 bars). BTC, ETH and BCH have that day.
  - DOGE 5m: also 2026-09-29 06:00–07:05 (14 bars).
- QA tables: `qa_doge5m_quarterly.csv` and `qa_{btc,eth,sol,xrp,ltc,bch}5m_quarterly.csv`.
  - The DOGE table was computed before trimming to ≥2021-01-01, so its 2020Q4 row has 20 bars.
  - miss% is inflated for partial quarters (2025Q1, 2026Q3). The 2026Q2 figure of 1.10% is the real 04-22 gap.

## Method

**Pulling**
- Every pull used `astral_price_get(limit=40000, delivery="download")`, chained backwards through `end`. `start` and `end` were never used together.
- `end` is normally exclusive, but three DOGE seams came back with a 1-bar inclusive overlap. All three overlaps were byte-identical.
- Each artifact was downloaded with curl and its sha256 checked against the response (`tools/dl.sh`, `tools/dl2.sh`). All 45 are logged in `raw/sha256_verified.txt`, and all 45 still verify today.
- The presigned S3 URLs rotated between four credential sets, so `tools/url_tpl*.txt` holds one template for each.

**DOGE 5m**
- 16 pulls: `raw/doge5m_p01..p16.csv`.
  - p16 is `limit=3700`, which reaches 2020-12-31T22:20. That is below 2021-01-01, so Astral has DOGE history from before the requested start.
- Stitched by `tools/stitch.py`: 15 seams, 12 contiguous with a 5-minute step and 3 with a 1-bar identical overlap. The result was trimmed to ≥2021-01-01.

**DOGE 15m and 1h**
- Resampled from the 5m file by `tools/resample.py`.
  - Bins are open-labelled and left-closed.
  - Partial bins are kept: 68 of the 15m bins and 62 of the 1h bins hold fewer than 3 or 12 source bars.
  - A trailing incomplete bin is dropped.

**DOGE 1m**
- One pull of the last 40,000 bars: `raw/doge1m_p01.csv`.

**BTC, ETH and SOL**
- Built from the repo files `data/fresh/<sym>-5m-ohlcv.csv.gz` (up to 2026-05-11) and `data/<sym>-5m-ohlcv.csv` (from 2026-05-12/13, pulled around 03:57). Both sets matched their recorded sha256 values; I read them and did not modify them.
- Pulls I added:
  - A bridge pull for 2026-05-06..05-13, which closes the seam.
  - A tail pull.
  - A 2025-03-19 head pull.
  - An ETH bridge (`eth5m_bridge2`) for 2026-09-27 16:10 → 09-28 13:45.
  - A BTC recheck of the last 120 bars.
- Merge rule (`tools/merge_priority.py`): the first-listed source wins on a duplicate timestamp. For the last day or two, the newest pull is listed first.
- Rows by source, from `MANIFEST.json`:
  - **BTC:** fresh 120,000, stage1 39,966, bridge 350, head 383, recheck 120.
  - **ETH:** fresh 120,000, stage1 39,952, bridge 113, ext 109, head 383, bridge2 260.
  - **SOL:** fresh 120,000, stage1 40,000, bridge 349, ext 84, head 94.
- Every final row matches its source row exactly (with a 1e-12 float tolerance). 0 rows are unattributed.

**XRP, LTC and BCH**
- Four 40k pulls plus one head pull each. Every seam is contiguous with a 5-minute step and no overlap.

## Choosing the DOGE clean_from date

Per-quarter QA (`tools/qa.py`) was compared against the 2025–26 baseline. Definitions:
- **jump:** |open / previous close − 1|, counted only on contiguous bars.
- **spike:** |r1| and |r2| both above 3% with opposite signs.
- **wick>3%:** a wick larger than 3% of the close.

| quarter | jump>2% | p99 jump % | wick>3% | spikes 3% | median range % | median decimals |
|---|---|---|---|---|---|---|
| 2021Q1 | 449 | 4.69 | 920 | 278 | 0.633 | 8 |
| 2021Q2 | 5,113 | 162.97 | 8,680 | 3,129 | 26.336 | 7 |
| 2021Q3 | 1 | 0.185 | 20 | 4 | 0.435 | 4 |
| 2021Q4 | 7 | 0.159 | 34 | 5 | 0.382 | 4 |
| 2022Q2 | 2 | 0.248 | 25 | 1 | 0.431 | 4 |
| 2022Q3 | 0 | 0.131 | 2 | 0 | 0.302 | 5 |
| 2025Q4 (10-10 crash) | 5 | 0.180 | 19 | 2 | 0.299 | 5 |
| 2026Q1 | 0 | 0.176 | 6 | 0 | 0.288 | 5 |
| 2026Q2 | 0 | 0.160 | 1 | 0 | 0.228 | 5 |

**Why not earlier than 2021-08-01**
- Part of 2021Q1 is the real January pump, but a p99 bar range of 27% is not a real market.
- 2021Q2 is garbage: April has 917 jumps above 2%, May has 1,653, and 2021-06-01/02 have about 107.
- Isolated bad wicks that revert within one bar remain after the jumps stop:
  - June 2021: 267 of them, all on June 3–10.
  - July 2021: 10, including 07-17 19:20–19:45 (upper wicks of 10–20%), 07-20, 07-26, 07-30 and 07-31.
  - August 2021 onward: 0.

**Why 2022-06-01 for tick-sensitive work**
- Until 2022-05-31 about 87% of closes have 4 or fewer decimals.
- A 0.0001 tick is 0.03–0.17% of the DOGE price, which is comparable to the strategy's 0.20–0.35% trailing distances.
- From 2022-06 about 90% of closes have 5 or more decimals.

**Bad bars that remain inside the clean range**
- These could falsely trigger stops. Clip them or check them against 1m data.
  - 2021-10-21 11:30 and 11:35: lows of 0.176 and 0.150 while price was about 0.25 (−30% and −40%).
  - 2026-05-17 23:40: a low of 0.081 while price was about 0.109 (−24.6%).
- 2025-10-10/11: the crash is real, but the aggregated series shows open-vs-previous-close jumps of −41.8% and −18.4%.

## Consistency checks

**DOGE 5m resampled to 15m vs a direct 15m pull** (`raw/doge15m_p01.csv`, last 40,000 bars)
- Close is exact on every common bin. O/H/L are at least 99.99% exact. There are 21 volume mismatches.
- The differences sit only at bins where 5m bars are missing (2026-09-29 06:00–07:00) plus two isolated bins: 2026-05-13 11:45 (low) and 2026-07-21 22:30 (open and high).

**DOGE 1m resampled to 5m vs the 5m file**
- Close is exact on 99.862% of bins. 9 bins differ by more than 1bp (max 0.063%), and 50 volume values differ.
- 1m and 5m are close but not identical, so an intrabar replay from 1m will not reproduce 5m OHLC exactly.

**My 5m resampled to 15m vs the repo 15m files** (40,000 common bins each)
- **BCH:** close is 99.987% exact. The worst differences are in the last 72 hours.
- **LTC:** close is 99.972% exact.
- **BTC:** close is 99.492% exact, with 126 bins above 1bp (max 0.69%).
  - The BTC differences cluster at 2026-09-28 17:00 and on 2026-08-19 02:00–07:00.
  - Both come from repo files, so Astral's 5m and 15m endpoints are not perfectly consistent with each other.

## Vendor stability and revisions

This bears on the claim that Astral is good for monitoring.

**Old history is stable**
- Every overlap between historical pulls is byte-identical:
  - the DOGE seams;
  - BTC, ETH and SOL bridges vs the repo files, about 1,567 overlapping bars;
  - DOGE's re-pull at 09:40 vs its earlier pull: 596 common bars, OHLC 100% identical, volume 99.66% identical.

**The recent tail is not stable**
- **ETH:** the repo stage-1 file (pulled around 03:57) has a 19-hour hole from 2026-09-27 20:30 to 09-28 15:40, inside the backtest window. The 09:40 pull fills it completely.
  - On the 49 bars before the hole (09-27 16:10–20:25, which were about 36 hours old at 03:57), close matched on only 36.7% (max difference 0.063%) and volume on only 2%.
  - The pattern is open and high unchanged while close and volume change. That looks like late trades being added to bars after the fact.
- **BTC:** between a pull around 09:25 and one at 09:40, 14 bars that had been missing appeared (09-29 05:05–05:25 and 07:05–07:45), plus 2 new bars at the end. On the 104 common bars close matched on only 67.3% (max 0.13%) and volume on 54.8%.
- **DOGE:** 09-29 06:00–07:05 was still missing at 09:40 in the 5m series, although the 1m and 15m series have those bars.
- A live monitor built on Astral bars will see holes and restated closes and volumes for at least several hours. For ETH it was more than 30 hours. Backtests on bars less than about 2 days old are not reproducible.

## Astral usage

- 46 calls in total: 1 `astral_symbol_resolve` and 45 `astral_price_get`, all with `delivery=download`.
- 0 backtests.
- No deploy, order, save, share or delete tools were called.

## Scripts (`tools/`)

- `dl.sh` / `dl2.sh`: download and sha256 check.
- `stitch.py`: joins pulls and reports each seam (overlap, mismatches, step).
- `qa.py`: bar-level QA and per-period tables.
- `resample.py`: builds 15m and 1h from 5m.
- `compare.py`: cell-level comparison of two OHLCV files.
- `merge_priority.py`: merges files; the first-listed source wins on duplicates.
- `manifest.py`: builds `MANIFEST.json`, recomputing every number from the files.
