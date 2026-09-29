# Sweep data: 7 coins, 5m to 1w, with IS/OOS/final splits

Written by the DATA agent on 2026-09-29. Every number here comes from scripts in `tools/`, and their outputs are in `qa/`, `work/` and `MANIFEST.json`. No bar was clipped, edited or removed. Suspect bars are only listed, in `suspects.csv`.

## Layout

| path | contents |
|---|---|
| `full/<sym>-<tf>.csv` | Whole stitched series. BTC/ETH/SOL/XRP/LTC/BCH start 2021-05-27..30. DOGE starts 2021-01-01. All end 2026-09-29 ~09:30 UTC. This includes bars before `clean_from`. |
| `is/<sym>-<tf>.csv` | From `clean_from` up to 2024-07-01 00:00 UTC (exclusive). **The only split Discover and Combine may read.** |
| `oos/<sym>-<tf>.csv` | 2024-01-01 up to 2025-08-07 00:00 UTC (exclusive). Holdout agent only. |
| `final/<sym>-<tf>.csv` | 2025-02-01 to the end of the data. Holdout agent only. |
| `suspects.csv` | 492 suspect single-bar reverting spikes. Nothing is clipped. |
| `MANIFEST.json` | Per file: rows, first, last, sha256, gaps, partial bins, clean_from. Also contains the raw-pull hashes, seams and cross-check results. |
| `qa/` | Monthly QA tables, liquidity tables, lag-1 autocorrelation, degraded windows, seam jumps, cross-check output. |
| `raw/` | The 64 Astral artifacts, each sha256-verified (`raw/sha256_verified.txt`). |
| `work/` | Stitched raw 5m series, stitch/seam reports and build summaries. |
| `tools/` | All scripts used. |

- `<sym>` is one of: btcusd ethusd solusd xrpusd ltcusd bchusd dogeusd.
- `<tf>` is one of: 5m 15m 30m 1h 2h 4h 1d 1w.
- Columns are `ts,open,high,low,close,volume`.
- `ts` is the bar open time in UTC, formatted ISO `YYYY-MM-DDTHH:MM:SSZ`.

## Provenance

**Astral usage**
- 64 `astral_price_get` calls in total. No other Astral tools were used.
  - 60 were the 5m chain: 6 coins × 10 pulls, each `limit=40000`, `delivery=download`, with `end` set to the first timestamp of the previous pull.
  - 4 were cross-check pulls, described below.
- `start` and `end` were never used together.
- All 64 artifacts matched the sha256 reported by Astral.

**Coverage**
- Pulls p01..p10 cover 2021-05-27/30 to 2025-03-18 23:55.
- From 2025-03-19 00:00 onward, the 5m data comes from the existing doge dataset (`scratchpad/doge/data/<sym>usd-5m-ohlcv.csv`). All 7 files match the sha256 values in that dataset's MANIFEST.
  - Those files combine Astral pulls with verbatim repository files, as documented in the doge MANIFEST.
- DOGE 5m (2021-01-01 onward) is taken entirely from the doge dataset.

**Seams (`work/stitch_*.json`)**
- 10 seams per coin. Every one is contiguous: the step is exactly 5 minutes, or there is a 1-bar overlap.
- Only the p10/p09 seams overlap, by 1 bar. Those overlap bars are identical in OHLC and volume. There are 0 mismatching cells over 6 overlap bars.
- The other seams have no overlap, so they could not be compared value-for-value. As a substitute I checked open-vs-previous-close across each seam (`qa/seam_jumps.json`):
  - The largest is ETH at 2025-03-19 00:00: 0.308%, which is the 99.9th percentile of all contiguous bars. That open (1937.2) is inside the previous bar's range (1931.0–1938.0).
  - All other seams are ≤0.114%.
- 0 duplicates, 0 misaligned timestamps, 0 OHLC-inconsistent rows, 0 NaN, 0 volume≤0 in any coin.

## clean_from

| coin | clean_from | reason |
|---|---|---|
| BTC, ETH, LTC, BCH | 2021-07-01 | Earliest allowed date. June 2021 has elevated opens away from the previous close (BTC: 29 jumps >0.5%). From July 2021 there are no gaps and no OHLC errors. |
| XRP | 2021-07-01 | Structurally clean, **but see the degraded window below.** |
| SOL | **2021-10-01** | Repeated round-number bad-print up-wicks from Jun to Sep 2021 (see below). June 2021 also has 134 gap events and 202 flat bars. |
| DOGE | **2021-08-01** | Inherited from the doge dataset: cross-venue mixing until 2021-06, and bad wicks through July. |

SOL bad-print up-wicks, Jun–Sep 2021:

| bar (UTC) | high | previous close | excursion |
|---|---|---|---|
| 2021-08-18 11:15 | 114.000 | 73.784 | +54.5% |
| 2021-09-06 20:25 | 199.000 | — | +23.1% |
| 2021-07-07 09:45 | 40.000 | — | +14.3% |
| 2021-06-28 07:50 | 39.020 | — | +20.1% |

SOL suspects per month: 5 in 2021-08, 7 in 2021-09, then 2–3 per month.

## Degraded windows (not excluded; `qa/degraded_ranges.json`)

**XRP, 2022-03-01 to 2023-07-31**

This window covers 17 of XRP's 36 IS months.

| XRP period | gap events | missing slots | flat bars | median USD volume per 5m bar |
|---|---|---|---|---|
| 2022-03-01 .. 2023-07-31 | 282 | 292 | 813 | 7,064 |
| 2021-07 .. 2022-02 | 0 | — | 0 | 81,953 |
| 2023-08 .. 2024-06 | 0 | — | 0 | 80,819 |
| BTC, same window (reference) | — | — | — | 1,378,797 |

- The recovery at 2023-08 matches XRP's return to US venues.
- The data is not corrupted:
  - 0 OHLC errors.
  - Lag-1 autocorrelation of 5m returns is −0.03 to −0.07 per quarter, the same range as BTC (`qa/ac1_quarterly.csv`).
- However, in this window:
  - Volume-based features shift regime about 11×.
  - 5m/15m microstructure comes from few trades.
  - IS 1h has 252 partial bins and IS 1d has 122 partial bins.
- Treat XRP intraday results from this window with caution.

**BCH, OOS/final only**

| BCH period | gap events | missing slots | flat bars | other |
|---|---|---|---|---|
| 2024-09 | 329 | 571 | 331 | 1h gap ending 2024-09-16 06:30 |
| 2025-10-01 .. 2026-05-31 | 168 | 556 (288 of which are 2026-04-22) | 227 | median USD volume per 5m bar 9,122, vs 18,416 in 2024-01..08 |

**SOL, 2021-06:** 134 gap events and 202 flat bars. This is before `clean_from`.

## Known data defects (all verified here)

1. **2026-04-22 is missing in every 5m series (288 bars).** The direct Astral 1d pulls for BTC and DOGE do contain a 2026-04-22 bar. So this is a gap in the 5m feed, and my 1d, 4h, 2h, … files lack that day. This affects the final split only.
2. **2025-03-25 is missing in SOL, XRP and LTC 5m** (a whole day, 288 bars). This comes from the doge-dataset files and is in the OOS and final splits.
3. **DOGE 5m is missing 2026-09-29 06:00–07:05** (14 bars). The direct 1h pull has a 06:00 bar.
4. **The last ~2 days (2026-09-27..29) are provisional.**
   - The 11:13 UTC re-pulls differ from the stitched data.
   - DOGE 1h: 21 bars with price mismatches, all on 09-27/28. The largest close difference is 1.04%, at 2026-09-28 15:00.
   - BTC 1d on 2026-09-27: close differs by 0.28%.
5. IS gap totals, in 5m slots:

| coin | missing 5m slots in IS |
|---|---|
| BTC | 0 |
| ETH | 0 |
| DOGE | 1 |
| LTC | 1 |
| SOL | 4 |
| BCH | 45 (31 events, longest 25 min) |
| XRP | 292 (282 events, longest 15 min) |

   No other gaps in IS are longer than 25 minutes.

## suspects.csv

**Definition.** A bar t is flagged when all three conditions hold:
- **Size:** range ÷ previous close is more than 8× the rolling median range. The median is taken over the previous 288 bars, excluding bar t, with at least 72 bars and a floor of 5 bp.
- **Full reversion:** the maximum excursion E from the previous close is retraced.
  - `wick`: within the bar, meaning |close − prev_close| ≤ 0.25·E.
  - `close`: by the next bar's close, meaning |next_close − prev_close| ≤ 0.25·E.
- **Isolation:** the neighbouring bar ranges are below 4× the median, and the bars are contiguous.

**Counts**

| coin | total | IS | OOS | final | excursion ≥5% |
|---|---|---|---|---|---|
| BTC | 57 | 44 | 17 | 9 | 2 |
| ETH | 46 | 35 | 12 | 10 | 3 |
| SOL | 70 | 35 | 21 | 14 | 26 |
| XRP | 84 | 64 | 17 | 17 | 15 |
| LTC | 56 | 36 | 14 | 18 | 16 |
| BCH | 119 | 49 | 33 | 55 | 13 |
| DOGE | 60 | 33 | 16 | 12 | 19 |

- 492 rows in total; the per-split columns overlap.
- Columns `after_clean_from` and `splits` give each row's membership.
- Largest excursions:

| coin | bar (UTC) | excursion | note |
|---|---|---|---|
| SOL | 2021-08-18 11:15 | +54.5% | |
| SOL | 2022-11-10 19:35 | −27.1% | FTX week; may be real |
| DOGE | 2026-05-17 23:40 | −25.7% | known bad low |
| SOL | 2021-09-06 20:25 | +23.1% | |
| LTC | 2022-10-12 06:25 | +21.3% | |
| ETH | 2025-12-13 23:20 | −11.3% | low 2760 vs 3112.7 |

- I cannot tell a real flash wick from a bad print without a second source. The list is deliberately inclusive.
- **Limitation:** a single-bar rule misses bad prints that span two bars. Example: DOGE 2021-10-21 11:30/11:35, which is documented in the doge dataset but is not in this file.

## Resampling

- Bins are UTC, open-labelled and left-closed.
- Aggregation: O = first, H = max, L = min, C = last, V = sum, over the available 5m bars.
- Bins with zero bars are dropped. Bins with some bars missing are kept; their counts are in `partial_bins` in the MANIFEST.
- Only bins lying entirely inside a split window are kept. This means:
  - No leading partial week. For example, the first IS 1w bin is 2021-07-05, and SOL's is 2021-10-04.
  - No trailing week that crosses a boundary. The last OOS 1w bin is 2025-07-28, because the week starting 2025-08-04 extends past 2025-08-06.
  - No bar leaks across a split boundary. `build.py` asserts that every IS bin ends at or before 2024-07-01; all 56 IS files pass.
- 1w bins start Monday 00:00 UTC.
- The in-progress last bin of the open-ended windows is dropped. For example, the last final 1h bin is 2026-09-29 08:00.
- Independent check: the weekly bars for 2023-01-02..2023-02-27 were recomputed with a pandas period groupby. The maximum OHLC difference was 0, and the volume difference was 3e-11.

## Cross-check against direct Astral pulls (`qa/xcheck.txt`)

| pull | window | common bars | result |
|---|---|---|---|
| BTC 1h, end=2024-07-01, limit 3000 | 2024-02-27..2024-06-30 (IS) | 3000/3000 | O/H/L/C 100% exact; volume max relative difference 5e-16. |
| DOGE 1h, latest 3000 | 2026-05-27..2026-09-29 | 2997 (+1 only in Astral: 09-29 06:00) | O/H/L/C exact 99.67/99.83/99.83/99.80%; all 21 price-mismatch bars on 2026-09-27..28 (revision); volume exact 98.87%. |
| BTC 1d, latest 2000 | 2021-05-31..2026-09-28 | 1946 (+1 only in Astral: 2026-04-22) | High 100% exact. 3 bars with price mismatch (2026-08-19 0.022%, 2026-08-26 0.034%, 2026-09-27 0.28%). Volume mismatch on 6 days. |
| DOGE 1d, latest 2000 | 2021-04-09..2026-09-28 | 1998 (+1 only in Astral: 2026-04-22) | O/H/L 100% exact; close exact 99.95% (1 mismatch, 2024-06-16, 0.13%); volume exact 99.6%. |

The resampled 1h and 1d files agree with Astral's own aggregation, apart from recent revisions and the 2026-04-22 5m hole.

## Caveats

- Seam validation is weak. There is overlap at only 1 seam per coin, so the other 9 seams per coin rest on continuity statistics, not value comparison.
- 2025-03-19 onward is inherited from the doge dataset and was not re-pulled here. Its internal re-checks are documented there.
- Some suspects may be real market events. Some bad prints may be missed if they are multi-bar or below 8× the median range.
- The final split ends with ~2 days of provisional bars.
- The call count (64) is from my own tally across a context compaction. The raw/ directory holds exactly 64 verified artifacts, which is consistent with that count.

## Reproduce

Paths are relative to this directory.

1. Stitch each coin (btc eth sol xrp ltc bch):
   ```
   python3 tools/stitch.py work/<c>usd-5m-stitched-raw.csv 5 raw/<c>5m_p*.csv ../../doge/data/<c>usd-5m-ohlcv.csv
   ```
2. Run the monthly QA:
   ```
   python3 tools/qa.py work/<c>usd-5m-stitched-raw.csv 5 M qa/qa_<c>_monthly.csv
   ```
3. Run the liquidity, autocorrelation and suspect scripts:
   ```
   python3 tools/monthly_liq.py <c>
   python3 tools/ac1.py
   python3 tools/suspects.py <out> btc eth sol xrp ltc bch doge
   ```
4. Build the output files for each coin:
   ```
   python3 tools/build.py <c> <clean_from>
   ```
5. Run the cross-check:
   ```
   python3 tools/xcheck.py full/<sym>-<tf>.csv raw/<x>_xcheck.csv
   ```
6. Write the MANIFEST:
   ```
   python3 tools/manifest_build.py
   ```
