# Adversarial verification of the "engine" audit

Scratch dir: `verify_engine/`. Nothing under `/home/user/crypto-bot-research` was modified.
Heavy jobs ran at most 2 in parallel. No Astral tools were used.

## What I built independently (did not reuse the auditor's engine_v.py or cache)

| file | purpose |
|---|---|
| `bt/` | copy of the delivered code (used only for `run.py --synthetic`, analyze.pooled/apply_rule, forward_stats, portfolio.single_account) |
| `cache_sig.py` -> `cache/*.npz` | my own signal cache (15m: 28 strategies x 5 symbols; 5m: 3 V4.5 variants x 3 symbols) |
| `engine_x.py` | my own flag-switchable re-implementation of engine._simulate_one/run_backtest (flags: reentry, maker_tp, gap_tp, tp_through, tp_bp, ff) |
| `run_x.py` | grid runner + analyze.pooled/apply_rule; logs `log_*.txt`, pooled tables `out/pooled_*.csv` |
| `unit_checks.py` | synthetic-bar tests for re-entry, gap-beyond-TP, MAE liquidation, TP fee, same-bar ladder trigger+SL |
| `q2.py`, `q3.py`, `q3b.py` | maker-TP, MAE-liquidation, split crossing, gap-TP counts on the repro trades file |
| `fwd_check*.py` | forward-drift overlap / cluster / HAC / drift-adjusted checks |
| `sa_check*.py` | single-account 59-trade check |
| `mart.py` | 1-second GBM martingale test: engine at 15m/5m/1m/1s vs favourable-first |
| `real_res.py` | real 5m data, 12,000 RANDOM entries per ladder config, 15m-aggregated vs 5m vs ff (no strategy OOS evaluation) |
| `cost_sens.py` | pass count under lower-cost assumptions |

## Baseline reproduction
* engine_x with flags off: 15m pooled (364 rows) max |PF diff| 6.3e-15 vs repro `pooled_IS_15m_all5.csv`, identical pass column; 5m (39 rows) max |PF diff| 8e-15. So the variant numbers below are measured with an engine independent of the auditor's.

## Variant grid results (mine)
| variant | 15m trades | 15m PASS | 15m max PF | 5m PASS | 5m max PF |
|---|---|---|---|---|---|
| orig | 900,334 | 0 | 0.9283 | 0 | 0.7988 |
| reentry (i < next_free) | 948,123 (+47,789) | 0 | 0.9076 | 0 (66,911 trades) | 0.7891 |
| maker TP (post-hoc on trades) | 900,334 | 0 | 0.9459 | - | - |
| all (reentry+maker+gapTP) | 948,123 | 0 | 0.9247 | 0 | 0.8180 |
| TP trade-through 1bp | 898,852 | 0 | 0.9260 | - | - |
| favourable-first (ff) | 910,754 | 11 | 2.2178 | 0 (ladder max 0.493) | 0.7988 |
| ff + reentry + maker | 964,766 | 12 | 2.1881 | - | - |
Re-entry fix is neutral on average (mean PF 0.6303 -> 0.6300; 158 combos up, 175 down).
All of the auditor's variant numbers reproduce with my separate implementation.

## Per-finding checks
* ENG-3 (MAE liquidation): 65,827 L50 liquidation flags. 12,259 have pre-exit-bar MAE beyond 1.5%; 40,855 (62%) are stop exits (SL/TRAIL/LOCK) whose stop (sl_dist < 1.5%) filled above the liquidation price, where only the exit bar's later extension crossed it. Per-symbol eq_L50 median ~2e-12 -> 2e-10; combos above 0.01: 198 -> 244 of 1,820. Affects reporting only.
* ENG-4 (re-entry): unit test: signal on exit bar 4 skipped, entry taken from signal 5 (engine.py:149 vs comment :159).
* ENG-5 (maker TP): 222,328 TP exits (24.7% of all trades, 38.3% of FIXED). 0.03% per TP trade, 0.0074% per trade on average. Mean FIXED PF 0.698 -> 0.721.
* ENG-6 (pooled overlap): overlap fraction median 0.56 (trade-weighted 0.64); max concurrency is 5 in 308 of 364 combos.
* ENG-7: the only window with 59 trades and 27 wins is entries 2026-09-04 01:10 .. 09-12 22:45 UTC (not Sep 5-13). single_account(lev 50, 40%) gives 205.8. Sep 5-13 UTC gives n=62, WR 41.9%, 147.4. No tried setting gives 380: margin 30% gives 311, 40x gives 287, fee 0.01% gives 453. The busy_until equality overlap is 48 of 887 taken (AMB_G1 L50_sl15); a strict rule takes 842.
* ENG-9: 0 SL-booked FIXED trades had an exit-bar open beyond TP. Same-bar SL+TP ambiguity: 1,611 of 579,890 FIXED trades (0.28%); TP-first moves mean FIXED PF 0.698 -> 0.708, max unchanged.
* ENG-10: ladder float boundary confirmed (a price exactly at 12/21/31 ROE gives roe 11.9999999999998 and no lock). Split crossing: 502 enter before the split and exit after; 19 enter at or after it (521 total). TIME 68, EOD 0.
* ENG-11: numbers reproduce ONLY with `--window ALL`: gross -0.0344% (se 0.0011), net -0.1363%, pre-slip +0.0003%. With the default `--window IS`: gross -0.0399%, net -0.1418%, pre-slip -0.0051% (naive se 0.0014). The naive se is meaningless because all 390 combos share one path and the 5 symbols are identical copies (seed 7). Per-strategy pre-slip t ranges from -5.1 to +4.9 on the same path.
* ENG-1: martingale (mine, 1,900 entries, 0 cost):
  * sigma 0.28%, L50_sl15: 15m engine +0.0090%, 5m +0.0039%, 1m +0.0053%, 1s +0.0021%, ff +0.0581%. Paired 15m-1s is +0.0069 (se 0.0040); ff-1s is +0.056. Win rate 0.495 (15m) vs 0.555 (1s).
  * sigma 0.40%: 15m-1s -0.0021 (se 0.0055), ff-1s +0.124. Win rate 0.429 vs 0.548.
  * Expectancy equality is guaranteed by optional stopping on a martingale, so the test's real content is the size of the ff bias.
  * Real data, random entries (no strategy evaluation): L50_sl15 gross 15m -0.0319%, 5m -0.0298%, ff +0.0787%; paired 5m-15m +0.0021 (se 0.0012); PF at 0.14% cost 0.242 / 0.201 / 0.666. L50_sl20: paired +0.0012 (se 0.0014), PF 0.278 / 0.231 / 0.719.
* ENG-2: forward_stats reproduces forward_ALL_5m_v45.csv exactly (0 diff); 65-70% of AMB signals fall within 64 bars of the previous one.
  * Per symbol: naive t 2.79/2.91/3.05 -> cluster t 1.62/1.76/1.88, greedy-thin t 1.59/1.68/1.99, HAC (Bartlett, 64) 1.78/1.92/1.96.
  * BUT pooled over 3 symbols at 64 bars, V4.5 AMB drift-adjusted +0.134%: per-symbol clusters t 3.00, cross-symbol time clusters t 2.21.
  * 15m (5 symbols, 64 bars = 16h), per-symbol clusters / cross-symbol clusters: N09 +0.116% t 2.23/2.32, S6 +0.130% t 2.07/1.43, N17 +0.125% t 1.62/1.21.
  * The auditor compared per-symbol V4.5 t (about 1.7) with pooled 5-symbol 15m t (about 2.1-2.2), which is an inconsistent comparison. It also mixed horizons (5.3h vs 16h) and periods (May-Sep 2026 vs Aug 2025-May 2026).
  * At matched ~4-5h horizons: V4.5 t 3.07/2.44 (4h), N09 2.65/1.97 (4h), S6 2.39/1.83 (5.25h), N17 1.34/0.80.
  * So V4.5 is about as strong as N09 and stronger than S6/N17. "Only" is overstated because N09 is comparable. Under consistent treatment V4.5 is not weaker than the 15m candidates. With about 28x6 tests, t 2-3 is still consistent with noise. The drift is about equal to round-trip taker cost.

## Additional observations (not in the audit)
* 85% of ladder LOCK exits (77,702 of 91,753) fill at the next bar's OPEN, below the lock level, because the lock only becomes active one bar late. 13.4% of LOCK exits are gross losses and 28.2% are net losses; the median LOCK gross is +0.199%, not +0.22%. 58.8% of ladder trades reach MFE >= 0.24% (the +12 ROE trigger), yet the ladder win rate is 36%. The handoff's "실제 승률 40%" (actual win rate 40%) is therefore a property of the bar-close ladder; a tick-level ladder would win about 55-60% with the same negative expectancy. The "658 gap-through fills" in the confirmed-OK list counts only reason=='SL'; TRAIL has 5,656 more.
* Cost sensitivity (15m IS, post-hoc on trades): zero fee with slippage kept gives max PF 1.094 and 0 pass; maker 0.02%x2 with no slippage gives 1.064 and 0 pass; taker 0.01% with slippage gives 1.042 and 0 pass. Only at zero total cost does 1 combo pass (N08 L50_sl20, 238 trades, PF 1.205). The headline is robust to cost assumptions as well.
* The auditor's intrabar_5m.py evaluated all 28 15m strategies x 13 exits on post-split data (2026-05-14..09-29), which is the pre-registered OOS window. This does not change any verdict, but those OOS per-combo numbers have now been seen. They must not feed future selection.
* ETH 15m bad print 2025-12-13 23:15 (low 2760 vs about 3115, close unchanged) forces 69 long stop exits across combos (summed -21.4% price units over 105 trades exiting on that bar). It also inflates ETH ATR14 for a while afterwards. This is negligible per combo.
