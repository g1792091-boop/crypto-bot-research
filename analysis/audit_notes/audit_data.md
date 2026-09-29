# Data-quality / provenance / history audit — stage-1 crypto backtest

Lens: data quality, provenance, history availability. Nothing under /home/user/crypto-bot-research was modified.
All scripts and outputs are in this directory (audit_data/). Repro trade ledgers used:
`../repro/results/trades_IS_15m_all5.csv` (900,334 trades) and `../repro/results/trades_ALL_5m_v45g1.csv` (95,982 trades).
Astral: only `astral_price_get` was used, 56 calls, all `delivery=inline`, all small windows (raw bars stored in
`astral/calls.jsonl`, summary in `astral/astral_samples_summary.csv`).

## Bottom line

* Data cleaning does **not** change the headline. With outlier wicks clipped (two variants) and the full grids re-run,
  the pass count stays 0/364 (15m) and 0/52 (5m incl. V39_15M_G1; 0/39 for V4.5 only). Max pooled 15m PF moves
  0.928 -> 0.921 (suspect-only clip) / 0.890 (clip every flagged bar). No combo reaches PF 1.0 in any variant.
* Outlier wicks on net **flatter** the results slightly (trades that exit on flagged bars sum to +902 pct-points net,
  mostly TP fills on spikes) and **inflate liquidation counts** (25-44% of the L10 liquidations are due to flagged
  bars; a single ETH bad print on 2025-12-13 23:15 alone liquidates 69 of 278 L10 trades).
* Spot (Polygon aggregate, USD) vs Binance USDT-M perp is a real limitation for 0.22-0.40% ladder exits: a +-2/5/10 bp
  change in intrabar wick size moves ladder PF by roughly x0.85-1.2 / x0.65-1.5 / x0.3-2.2. But even the most optimistic
  perturbation (wicks 10 bp narrower on both sides) leaves every combo below PF 1.0 (15m max 0.991, 5m max 0.905).
* Gaps are handled by bar index (max_hold, funding, ATR, indicators). Affects 0.06-0.07% of trades; removing all
  gap-affected trades leaves max PF 0.926 (15m) / 0.803 (5m).
* Astral history is much longer than "40,000 bars": 1h/15m/5m exist back to ~2013-12 (BTC/LTC), 2015-08 (ETH),
  2017-08 (BCH), 2021-02 (SOL). But pre-2020 bars are corrupted by cross-venue mixing (open vs prev close jumps of
  ~4% on consecutive bars in 2019). Samples become consistent from ~2020-04 (BTC/ETH), ~2020-07 (LTC/BCH), ~2021-06
  (SOL, still noisier than 2025-26). Truly unseen clean history before the stage-1 window: ~5.3 yr (BTC/ETH),
  ~5.1 yr (LTC/BCH), ~4.2 yr (SOL).

## (1) Suspicious bars in the 8 CSVs  — `qa_bars.py`, `classify_flags.py`

Raw integrity (read from the CSV text before any sorting): 0 duplicate timestamps, 0 non-monotonic steps, 0 NaN,
0 OHLC-inconsistent bars (high < body or low > body), 0 zero-volume bars, 0 open-vs-prev-close jumps > 3 ATR outside
gaps. All files 40,000 rows. Open vs previous close: median 0.0007-0.016% (15m), p99 0.11-0.20% -> feed is internally
continuous in 2025-26.

Flag definitions (ATR = Wilder ATR14 of the PREVIOUS bar):
LW/UW = wick beyond body > 4 ATR with |close-open| < 1 ATR; LSP/HSP = low (high) beyond both neighbours' lows (highs)
by > 3 ATR. Each flag then classified: IDIOSYNCRATIC if own wick% >= 4x the median same-bar wick of the other symbols
and no other symbol has a same-direction wick >= 2 ATR (i.e. not a market-wide move); "exaggerated" if co-moving but
own wick >= 4x others' median and >= 10 ATR. SUSPECT = idiosyncratic or exaggerated.

| file | gaps (missing bars) | max gap | flagged wick bars | idiosyncratic/suspect | zero-range |
|---|---|---|---|---|---|
| BTC 15m | 2 (97) | 1455 min | 11 | 4 / 4 | 0 |
| ETH 15m | 3 (98) | 1455 | 12 | 6 / 7 | 0 |
| SOL 15m | 2 (97) | 1455 | 16 | 6 / 6 | 0 |
| LTC 15m | 3 (118) | 1455 | 18 | 7 / 7 | 0 |
| BCH 15m | 16 (113) | 1455 | 42 | 31 / 31 | 27 flat OHLC |
| BTC 5m | 0 | 5 | 4 | 0 / 0 | 0 |
| ETH 5m | 4 (238) | 1160 | 6 | 0 / 1 | 0 |
| SOL 5m | 1 (1) | 10 | 8 | 6 / 6 | 0 |

Full lists: `qa_gaps.csv`, `qa_flags.csv`, `qa_flags_classified.csv`. Most important bars:

* ETH 15m 2025-12-13 23:15 (5m 23:20): low 2760.00 vs body ~3114 (-11.4%, 38 ATR); other symbols' same-bar wick
  median 0.08%. Re-queried Astral 5m today: still there, single 5m bar with 1,673 ETH volume vs ~100-300 around it.
  Round-number print on a Saturday -> probable bad / thin-venue print.
* ETH 15m 2026-05-17 23:30 (5m 23:40): low 1914.69 (-9.7% wick, 34 ATR on 15m, 45 ATR on 5m) while BTC -0.8%, SOL
  -1.3% in the same bar -> real dip, exaggerated ~8x on ETH. Present in both 5m and 15m files.
* SOL 2026-08-23 04:30 (5m 04:40): high 102.11 vs ~93 (+9.1% upper wick; others 0.1%). Still in Astral today.
* SOL 2026-05-18 06:00/06:05 low 81.29 (-4%, others 0.4%). SOL 2025-11-06 16:30 low 147.68 (-4.5%, others 0.4%).
* BTC idiosyncratic lows: 2025-08-15 04:30 (-2.1%), 2026-01-06 12:00 (-1.9%), 2026-01-25 08:30 (-2.05%); high
  2026-04-28 03:45 (+1.3%). Not verifiable offline; could be genuine BTC-only moves.
* LTC 2025-10-10 21:15 low 54.95 from ~114 (-34%): market-wide crash (BTC -8%, others' median wick -11%). Astral 5m
  today: 21:15 low 72.53, 21:20 low 54.947, and 5m opens 9.4% / 7.6% away from the previous 5m close (21:25, 21:30)
  -> during the crash the aggregate is a mixture of venues trading at very different prices. The magnitude on
  Binance LTCUSDT (last or mark) is unknown.
* BCH: 31 idiosyncratic wicks (e.g. 2026-01-10 21:45 high 686.80, +5.4%, 14.7 ATR; 2026-04-27 12:45 +15.8 ATR;
  2026-09-16 17:30 low 204.25, -4.8%, 10.9 ATR), plus 27 flat bars (median volume 0.07 BCH) clustered on
  2025-10-25, 2025-11-17, 2025-12-21, 2026-01-01, 2026-01-04, 2026-05-08, the same days as most BCH 30-45 min gaps
  -> the aggregate falls back to a single thin venue on those days. BCH is still not the worst symbol (PF over all
  combos: BCH 0.647 vs BTC 0.574); excluding BCH, max pooled PF is 0.914.

Gaps (all listed in `qa_gaps.csv`):
* 2026-04-21 23:45 -> 2026-04-23 00:00 (1455 min, the whole UTC day 2026-04-22) in all five 15m files. Price moves
  across the gap: BTC +2.43%, ETH +2.03%, SOL +0.98%, LTC -0.14%, BCH +2.63%. **Astral now returns BTC 15m bars for
  2026-04-22** (queried 12:00-12:45) -> vendor backfilled after the pull. A re-download would fill it.
* ETH 5m 2026-09-27 20:25 -> 2026-09-28 15:45 (1160 min). Astral now returns ETH 5m for 2026-09-28 00:00 -> also
  backfilled. LTC 15m 2026-09-28 17:00 -> 22:30 (330 min) is in the same "last 1-2 days incomplete" pattern.
* 1-bar gaps: 2025-08-08 ~09:30 in all 15m files, ETH 15m 2026-06-16 19:45, SOL 5m 2026-09-14 23:35, BCH 12 more.

Cross-pull consistency (5m resampled to 15m vs the 15m file, 13,33x overlapping bars, `qa_xframe*.csv`):
SOL 100% identical opens, ETH 99.98%, BTC 98.75%. BTC mismatches are whole days: 2026-08-19 (96 bars; open/close up
to 17.6 bp apart; the 5m file carries ~4x less volume, e.g. 0.28-3.7 BTC per 5 min) and 2026-08-26 (96 bars; the 15m
file is the thin one), plus the last 1-2 days (2026-09-28/29, up to 69 bp close diff, 56 bp high diff; 15m bar
2026-09-28 17:00 has 22.8 BTC vs 369 BTC in the 5m file -> provisional bars at pull time).
Re-query today: BTC 5m 2026-08-19 10:00/10:05 now has volume 3.37/10.95 (file: 0.86/0.28) and low 64330 (file:
64347.5) -> **the vendor revises history; the CSVs are an unreproducible snapshot** (the sha256 file is the only
anchor). 184 of 95,982 5m trades were entered on BTC 2026-08-19 (net -23.4 pct-points).

Other provenance notes:
* `data/expected_sha256.txt` lists 10 hashes incl. `ltcusd-5m` and `bchusd-5m`, whose files do not exist (the
  handoff says those downloads failed). Those two hashes cannot be checked.
* `results/forward_ALL_5m_v45.csv` has no driver script in bt/ (forward.py only reads 15m). I reproduced it exactly
  with `forward.forward_stats` on 5m data (`fwd5m_check.py`: 9 rows, max |diff| 8e-17, identical signal counts).
* The 15m files start at different times (05:00-10:15 on 2025-08-07) because each is "last 40,000 bars" and gap
  counts differ.
* Daily-volume screen (`qa_thin_days.csv`): many days at < 30% of the 21-day median volume. Most are weekends, but
  ETH/SOL/LTC 2025-11-12 and 2026-01-04 (ratios 0.12-0.18) look like venue drop-outs.

## (2) Trade impact of the flagged bars — `trade_impact.py`, `make_clean.py`, `run_clean.sh`, `compare_clean.py`

Join: trades.symbol + exit_ts vs flagged bar timestamps (and span test: any flagged bar in [entry_ts, exit_ts]).

15m (900,334 trades; pooled net sum of all trades -150,274 pct-points):
* All flagged bars: 4,447 trades (0.49%) exit on a flagged bar (TP 2,089, SL 1,992, TRAIL 323, LOCK 43); their net
  sum is **+901.9** pct-points. 5,379 trades have a flagged bar in their span (net +1,858.8).
* Suspect bars only: 2,491 trades exit on one (SL 1,234, TP 1,020), net +23.5; span 2,893, net +498.5.
* Liquidations with MAE recomputed on clipped bars (exit unchanged): L5 37 -> 37; L10 278 -> 198 (all) / 209
  (suspect); L20 1,526 -> 1,342 / 1,436; L50 65,827 -> 64,572 / 64,957. L5's 37 are all LTC 2025-10-10
  21:15-21:45; L10's biggest cluster is ETH 2025-12-13 23:15 (69 trades).
* Top-10 combos by PF with trades removed: S6_EMA_DMI_ADX F_sl2.0_tp3.0 0.928 -> 0.919 (drop exit-on-flag or span,
  all flags) / 0.925 (suspect); N08_ICHI_WR F_sl2.0_tp3.0 0.862 -> 0.840; OBV_B F_sl2.0_tp3.0 0.835 -> 0.834.
  Max PF over 364 combos after dropping span trades: 0.919. PF >= 1.0: 0.
* Full re-run of both grids on clipped data (wick capped at 1 ATR beyond the body; signals, ATR and exits all
  recomputed): 15m pass 0/364 in both variants; max PF 0.921 (suspect) / 0.890 (allflag); mean PF change
  +0.0005 / +0.0012; per-exit-family mean PF unchanged to 2 decimals (ladder L50_sl15 0.335 -> 0.335, L50_sl20
  0.381 -> 0.381). L10 liquidations 278 -> 209 / 155; L50 65,827 -> 64,916 / 64,486.
  5m: pass 0/52; max PF 0.799 -> 0.798 / 0.797; L50 liquidations 623 -> 611 / 604.
* V4.5 exact AM+B 64-bar forward drift (`fwd5m_check.py`): BTC +0.090% (no 64-bar window contains a gap or flagged
  bar), ETH +0.140% -> +0.128% without flagged windows (t 2.69), SOL +0.178% -> +0.175% (t 2.99). Not a data artefact.

Bias: outlier wicks make PF/expectancy look slightly BETTER (spike TP fills) and leverage-layer equity look WORSE
(spurious liquidations). Neither changes the headline.

## (3) Engine treatment of gaps — `gap_impact.py`

Code facts:
* `engine.py:65` `last = min(n - 1, e + cost.max_hold - 1)` -> max_hold counted in bars, not time.
* `engine.py:128` `funding = funding_8h * (hold * bar_minutes / 480)` -> funding from bar count (and charged
  continuously rather than at 00/08/16 UTC; unbiased on average for short holds).
* `fg_indicators.py:22-36` true_range uses the previous close -> the first bar after a gap carries the whole gap
  move into ATR and every indicator; no gap reset anywhere. `run.py:34-38` only counts gaps (attrs) and does nothing.
* `forward.py:27-29` horizons are in bars.

Numbers:
* ATR at the first post-gap bar (2026-04-23 00:00): BTC x1.42, ETH x1.27, SOL x1.10, LTC x1.02, BCH x1.56; still
  x1.06-1.30 ten bars later -> stops/targets of entries in the next ~10-20 bars are wider than intended.
* Trades whose wall-clock span exceeds their bar count (span a gap): 15m 564 / 900,334 (0.063%), net +133.3
  pct-points, missing funding 6.2 pct-points in total (~0.011% per such trade); max wall/bar ratio 49 (a 2-bar trade
  spanning 24 h). 5m: 71 / 95,982 (0.074%), net -32.0.
* Signals on the first post-gap bar: BTC 39 trades (net -17.9), BCH 39 (-19.3); within 30 bars after the gap:
  BTC 192 (-61.3), BCH 204 (-70.8), SOL 230 (-36.9).
* Removing every gap-affected trade (span a gap, or signal within -1..+30 bars of a >= 2 h gap): max 15m PF 0.926,
  max 5m PF 0.803 (V45_EXACT_AMB F_sl2.0_tp3.0 0.799 -> 0.803). No combo reaches 1.0.
* A trade open through the missing day is treated as if the price jumped from the last close to the next open
  (fill at open when the gap jumps past the stop). In reality the intraday path of 2026-04-22 would have triggered
  stops/targets differently. Direction unknown; 201 trades in total.

## (4) Aggregated spot vs Binance USDT-M perp (limitation; Binance/Bybit/OKX/Coinbase/Kraken are all blocked here)

What differs:
* Price source: Polygon USD aggregate across venues (not USDT, not Binance). Binance STOP_MARKET triggers on the
  perp last price by default (workingType CONTRACT_PRICE) or on mark price; liquidation uses mark price (index of
  spot venues plus a smoothed basis). The aggregate's high/low is the extreme across its venues. The mark price is an
  instant-by-instant weighted index, which damps single-venue spikes. So the engine's liquidation test (aggregate
  MAE, `engine.py:176`) likely **overstates** liquidations in stress (ETH 2025-12-13, LTC 2025-10-10), while
  SL/lock fills should use perp last-price wicks. Those can be larger (liquidation cascades on the perp) or smaller
  (no thin-venue prints) than the aggregate's.
* Basis: perp - spot premium is typically a few bp and changes by ~1-5 bp over the 30-100 min holds of the ladder
  exits. It can reach tens of bp in fast markets. USD vs USDT level offset (~<=0.1%) cancels in returns.
* Volume: OBV/MFI/VWMA strategies (OBV_S/B, S5, N18) use Polygon spot volume. That volume is a variable venue
  subset (x4 day-level differences between two pulls of the same BTC day) and has a different profile from Binance
  perp volume. So signals on the real bot would differ. The direction of the effect is unknown.

Sensitivity (`wick_sensitivity.py`): signals and ATR from the original bars, exit simulation on bars whose wicks are
shrunk (-) or widened (+) by delta x close on both sides. delta=0 reproduces the original family means exactly.

| exit (pooled mean PF over strategies) | -10bp | -5bp | -2bp | 0 | +2bp | +5bp | +10bp |
|---|---|---|---|---|---|---|---|
| 15m L50_sl15 (SL 0.30%) | 0.553 | 0.437 | 0.376 | 0.335 | 0.302 | 0.249 | 0.173 |
| 15m L50_sl20 (SL 0.40%) | 0.574 | 0.469 | 0.413 | 0.381 | 0.346 | 0.298 | 0.233 |
| 15m F_sl2.0_tp3.0 | 0.799 | 0.792 | 0.781 | 0.773 | 0.768 | 0.756 | 0.741 |
| 15m T_sl1.5_tr2.5 | 0.817 | 0.744 | 0.695 | 0.657 | 0.615 | 0.568 | 0.487 |
| 5m L50_sl15 | 0.444 | 0.308 | 0.242 | 0.201 | 0.174 | 0.130 | 0.064 |
| 5m L50_sl20 | 0.490 | 0.368 | 0.286 | 0.247 | 0.222 | 0.165 | 0.099 |
| 5m F_sl2.0_tp3.0 | 0.839 | 0.799 | 0.787 | 0.782 | 0.755 | 0.752 | 0.688 |
| 5m T_sl1.5_tr2.5 | 0.859 | 0.752 | 0.662 | 0.591 | 0.496 | 0.394 | 0.260 |

Max single-combo PF: 15m 0.991 at -10 bp (S6 F_sl2.0_tp3.0), 5m 0.905 at -10 bp (V45_EXACT_AMB_G1 T_sl1.5_tr2.5).
Combos with PF >= 1.0 (>=100 trades): 0 at every delta. Ladder and trailing results are very sensitive to bar-level
wick precision (a +-5 bp shift is x0.65-1.5 on ladder PF). Absolute ladder numbers therefore carry large model/data
error, but the sign of the conclusion does not. Option C (1-minute re-check) would narrow this. It cannot turn
PF 0.2-0.4 into >= 1.2.

## (5) Astral history availability — 56 read-only `astral_price_get` calls

Mechanics seen in the responses: start/end windows return `"limit":5000` (default) with `tier_limit 40000`, and
`history_mode "full"`. So the 40,000 cap is per request and history is not limited to 40,000 bars. Windows longer
than 5,000 bars probably need paging or `end`+`limit` lookback requests (not tested with large windows). The 5m bars
for 2020-07-01 00:00-00:55 aggregate exactly to the 1h bar (same O/H/L/C) -> all timeframes come from one trade tape
and share the same start dates. 5m exists for BTC 2019-01-02 and 15m for 2020-07-01, so the per-timeframe history
equals the 1h history.

Continuity metric per sampled window: median |open / previous close - 1| (2025-26 baseline from our 15m files
resampled to 1h: median of 10-bar windows 0.006% BTC/ETH, 0.010% SOL, 0.016% LTC/BCH; p90 0.015-0.036%).

| symbol | earliest bar found | bad / suspect samples | first consistent sample | usable clean history before 2025-08-07 |
|---|---|---|---|---|
| BTCUSD | 1d 2013-12-01 exists (2013-07 empty); 1h 2014-01-01 (~1 BTC/h) | 5m 2019-01-02 bars span 3800-3980 with closes alternating 3821/3975/3816/3965; 1h 2019-07 0.23%, 2019-10 0.21%, 2020-01 0.096% (40% of steps > 0.3%) | 2020-04-01 0.026%, 2020-07 0.024%, 2021-07 0.004%, 2022-01 0.005%, 2023-01 0.013%, 2024-01 0.003% (2021-01-04 crash day 0.12%) | ~2020-04 -> 2025-08-06 = 5.35 yr ~ 46,900 1h / 11,700 4h bars |
| ETHUSD | 1d 2015-08-07 (launch; first bars 3.0 -> 0.15) | 1h 2019-01 1.96% (closes alternating 139/145), 2020-01 0.37% (80% > 0.3%) | 2020-02-20 0.044%, 2020-04 0.008%, 2020-07 0.013%, 2022-01 0.002%, 2024-01 0.005% | ~2020-04 -> 2025-08-06 = 5.35 yr |
| LTCUSD | 1d 2014-01-01 exists (2013-07 empty) | 1h 2019-01 3.92% (31.5/32.9 alternating) | 2020-07 0.024%, 2022-01 0.030%, 2024-01 0.013% (2020-01..06 not sampled) | ~2020-07 -> 2025-08-06 = 5.1 yr ~ 44,700 1h bars |
| BCHUSD | 1d 2017-08-01 (first bar open 600000, garbage) | 1h 2019-01 0.13% (20% > 0.3%) | 2020-07 0.013%, 2022-01 0.034%, 2024-01 0.021% | ~2020-07 -> 2025-08-06 = 5.1 yr (thin venue set; expect flat bars / spikes as in 2025-26) |
| SOLUSD | 1d 2021-02-25 (2021-01 empty; first day o 24.6 l 13.8) | 1h 2021-07 0.060% (~6x the 2025-26 median) | 2022-07 0.029%, 2024-01 0.026% (still ~2.5x 2025-26) | ~2021-06 -> 2025-08-06 = 4.2 yr ~ 36,600 1h bars, noisier |

These are 11-12-bar spot checks (1-2 per year). They establish the regime change (2019 -> 2020) but not bar-level
cleanliness. Any new pull must be screened with `qa_bars.py`-style checks before use.

Implications for the next stage:
* Option A (1h/4h): pulling "the last 40,000 1h bars" (~2022-03 -> 2026-09) would put 14 already-inspected months
  (2025-08-07 -> 2026-09-29) into the sample. Truly unseen and reasonably clean: 2020-04 -> 2025-08-06 (BTC/ETH),
  2020-07 -> (LTC/BCH), 2021-06 -> (SOL). A split like selection 2020-04..2023-12 / holdout 2024-01..2025-08-06, with
  2025-08..2026-09 as a non-independent third look, is feasible.
* Option B (V4.5 slow, 5m + 15m): V4.5 was only ever evaluated on 5m 2026-05-12 -> 2026-09-29. 5m data from ~2020-04
  (BTC/ETH) to 2026-05-11 (~6.1 yr, ~640k bars per symbol, i.e. ~16 requests of 40,000) is unseen for V4.5 and is the
  proper holdout for the "64-bar drift" hypothesis. Its 15m confirmation frame for 2025-08..2026-05 was used for other
  strategies' selection, not for V4.5.
* Before any rerun: re-download the 2026-04-22 day and the 2026-09-27/28 ETH window (now backfilled). Record the pull
  time, because the vendor revises bars (BTC 2026-08-19).

## Files
qa_bars.py / qa_summary.csv / qa_flags.csv / qa_gaps.csv / qa_xframe*.csv, classify_flags.py /
qa_flags_classified.csv, make_clean.py / clean_log.csv / clean_{suspect,allflag}/ (full re-runs), compare_clean.py /
compare_clean_{15m,5m}.csv, trade_impact.py / trade_impact.log / trade_impact_*.csv, gap_impact.py / gap_impact.log,
wick_sensitivity.py / wick_sensitivity_{15m,5m}.csv, fwd5m_check.py, volume_days.py / qa_thin_days.csv,
astral/calls.jsonl, astral/astral_samples_summary.csv.
