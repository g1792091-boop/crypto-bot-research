# Holdout (OOS + FINAL): NOTES

Agent: Holdout, 2026-09-29, 12:42-13:03 UTC. I am the only agent that read `sweep/data/oos/` and `sweep/data/final/`.
Every number below comes from the scripts in this directory. Logs are in `logs/` and tables in `out/`.

## 0. Integrity

- **PREREG hash.** `cd sweep && sha256sum -c PREREG.sha256` gave 11/11 OK at 12:42:04 UTC (before any bar was read;
  the output was printed to the console, not saved) and again at 13:02:33 UTC (`logs/prereg_check_after.log`).
  PREREG.md sha256 = `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50` (unchanged).
- **Library.** `lib/sweep_lib.py` (sha256 `2b20c3c1...cd543`) and `lib/run_gate_tf.py` (`8cec4d91...`) are unmodified
  copies. `lib/vendor/` is byte-identical to `harness/vendor/` (`diff -rq`).
- **No bug fixes, so no rule changed.**
- **Data access.**
  - `data/` holds only the symlinks `oos` and `final`, and every script sets `SWEEP_DATA` to it.
  - `load()` dropped 0 bars at the window end (the files already end before the window end).
  - 0 files under `sweep/data` were modified.
  - No Astral tool was called.
  - `/home/user/crypto-bot-research` is git-clean.
- **Signal caches.** Signals recomputed by `exits_holdout.py` equal the gate-run caches bit for bit (every "cache check" OK).
- **Combine decision re-checked independently** (`recheck_is_gate.py`, `logs/recheck_is_gate.log`).
  - I re-applied `apply_gate` to the 7 raw Discover tables and got 666 cells.
  - The family has m = 528; gate_pass = 0 and gate_pass_spec = 0.
  - The minimum p is 7.96e-4, with p_holm 0.420.
  - The difference from Combine's p_holm is 5.6e-17.

## 1. PREREG 6: holdout confirmation of carried combos

**`combine/carried.json` has `"carried": []`. There is nothing to confirm, so the result is 0 CONFIRMED and 0 FAILED.**
No cell passed the IS gate (Holm-adjusted over m = 528), so no exit combo was selected and PREREG 6 was not
triggered. The 15 "near-miss" cells in carried.json are marked NOT carried and were not tested as confirmations.

The windows used are exactly those of PREREG 2:
- **OOS:** signals in [2024-07-01, 2025-08-07); warm-up bars from 2024-01-01. At 1d the 200-bar warm-up pushes the
  first admissible signal to 2024-07-19.
- **FINAL:** signals in [2025-08-07, 2026-09-30); files start 2025-02-01. The first 1d signal is on 2025-08-20/21.
  The last bars are 2026-09-29 09:35 (5m) and 2026-09-28 (1d).

## 2. PREREG 7.2: OOS gate table and persistence (descriptive)

I ran the same code (`lib/run_gate_tf.py --split oos`, B = 600, identical rng keys) for all 37 x 6 x 3 = 666 cells:
0 missing, 0 duplicates (`logs/assemble.log`). FINAL was run the same way.

Full tables:
- `out/gate_all_oos_applied.csv` and `out/gate_all_final_applied.csv`. Each has `apply_gate` applied over its own
  split's n >= 100 family; these columns are descriptive only and renamed `*_DESCRIPTIVE_own_family`.
- `out/cells_is_oos_final_long.csv` is the merged IS/OOS/FINAL table.

### 2a. Split-level counts (`out/counts_by_split.csv`; each split's own n >= 100 family)

| split | family | fwd>0 | z>2 (exp. N(0,1)) | p<.05 (exp.) | p<.05 & p_vn<.05 | fwd>cost | fwd>=mu* | fwd>=mu* & p<.05 & p_vn<.05 | z mean / sd | min p | Holm-sig p / p_vn |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IS | 528 | 225 | 19 (12.0) | 31 (26.4) | 9 | 46 | 15 | 3 | -0.20 / 1.26 | 7.96e-4 | 0 / 15 |
| OOS | 486 | 294 | 30 (11.1) | 46 (24.3) | 5 | 78 | 27 | **0** | +0.34 / 1.07 | 4.34e-5 | 1 / 3 |
| FINAL | 493 | 241 | 7 (11.2) | 17 (24.7) | 3 | 40 | 8 | 2 | -0.05 / 0.88 | 2.49e-3 | 0 / 5 |

**The OOS excess of nominal hits is mostly a 5m artefact.**
- 19 of the 30 OOS z > 2 cells and 23 of the 46 p < .05 cells are at 5m.
- 10 of those 19 have NEGATIVE z_vn. This is the vol-timing pattern the harness showed is anti-conservative for
  the raw null, and A1 exists to catch it.
- Only 5 OOS cells have both p and p_vn < .05, and none of them reaches fwd >= mu*.

**The one Holm-significant OOS cell (own family, descriptive) is N20_EMA9_CHOP 5m H4.**
- It is short-only, with n = 34,510, z 3.92 and p_holm 0.021.
- It fails A1 (p_vn 0.135).
- Its gross is 0.0089 % per signal against mu* 0.171 % and cost 0.140 %, which is 5 % of the hurdle.
- As a trade (`out/exits_descriptive_oos_5m.csv`) it is ruinous: TIME_H gives PF 0.43, -0.134 %/trade and 0/7 coins
  positive over 26,888 trades. FINAL is the same: PF 0.32, 0/7 coins.

**The Holm-significant p_vn cells are the fade-type N17_KC_RSI (5m/15m) and, in FINAL, V45_AMB 5m.** This is the
same pattern the Discover and Combine agents documented in IS. Their fwd is tiny or negative (at most 0.03 % against
a hurdle of 0.16-0.20 %), so this is bar-level mean reversion in the normalised return, not a tradable edge.

### 2b. Spearman of IS vs OOS (fwd - mu*) (`out/persistence_spearman.csv`, `out/persistence_summary.json`)

| subset | statistic | cells | Spearman | p |
|---|---|---|---|---|
| verbatim `sweep_lib.persistence` (all common finite) | fwd - mu* | 612 | **0.335** | 1.5e-17 |
| n >= 100 in both | fwd - mu* | 486 | 0.463 | 3.9e-27 |
| n >= 100 in both | z (scale-free) | 486 | 0.035 | 0.43 |
| n >= 100 in both | fwd / mu* | 486 | 0.073 | 0.11 |
| n >= 100 in both | net_time | 486 | 0.037 | 0.41 |
| IS vs FINAL, n >= 100 in both | z | 493 | 0.067 | 0.14 |
| OOS vs FINAL, n >= 100 in both | z | 483 | 0.019 | 0.67 |

**The pre-registered Spearman is mostly mechanical, so do not read it as persistence.**
- mu* rises with TF and H in every period, and the median cell has fwd of about 0. So fwd - mu* is roughly -mu*, and
  it ranks the same way in IS and OOS whatever the strategies do.
- I tested this with a stratified permutation that shuffles OOS values within each (TF, H) stratum and keeps only
  that structure (B = 5000, seed `[20260929, 72]`).
  - All cells: null mean 0.268 (95 % 0.192 to 0.345), observed 0.335, p = 0.043.
  - n >= 100 in both: null 0.398 (0.348 to 0.451), observed 0.463, p = 0.009.
- The residual (+0.06 to +0.07 over the structural null) is not consistent inside strata:
  - The mean within-(TF, H) Spearman is 0.022 (median 0.029), and only 9 of 18 strata are positive.
  - 15m H4 is -0.49 (p 0.004) and 15m H16 is -0.36.
- The scale-free z correlation is 0.035 (stratified-perm p = 0.075).

**Conclusion: IS rankings carry at most a weak and inconsistent signal into OOS, and essentially none into FINAL.**

### 2c. Top-10 IS cells by z and their OOS values

The verbatim `persistence()` list (`out/persistence_verbatim_top10.csv`) includes n < 100 cells, e.g. S5 4h H4
(n 70), N13 1d H4 (n 38) and N03 1d H64 (n 5). Those numbers are meaningless. The family version (n >= 100 in IS) is
`out/persistence_family_top10_by_is_z.csv`:

| IS rank | cell | IS n / z / fwd/mu* | OOS n / fwd/mu* / z / p_vn / coins+ | FINAL fwd/mu* / z |
|---|---|---|---|---|
| 1 | N13_3OUTSIDE 4h H64 (approx) | 234 / 3.16 / 2.44 | 106 / 1.13 / 1.15 / 0.32 / 4 | -1.20 / -1.30 |
| 2 | N20_EMA9_CHOP 5m H4 (approx) | 95158 / 2.82 / 0.03 | 34510 / 0.05 / 3.92 / 0.13 / 6 | 0.03 / 1.64 |
| 3 | N20_EMA9_CHOP 5m H16 (approx) | 95158 / 2.77 / 0.05 | 34495 / 0.04 / 2.53 / 0.14 / 4 | 0.08 / 1.74 |
| 4 | DOGE_L 1h H64 (prev. examined) | 1717 / 2.64 / 1.25 | 709 / 1.50 / 0.80 / 0.60 / 7 | -0.16 / 0.34 |
| 5 | N13_3OUTSIDE 4h H16 (approx) | 236 / 2.59 / 1.92 | 108 / 1.03 / 0.97 / 0.24 / 4 | -0.62 / -0.47 |
| 6 | N20_EMA9_CHOP 1h H64 | 7051 / 2.44 / 0.29 | 2524 / -0.67 / 0.62 / 0.46 / 1 | 0.48 / 0.23 |
| 7 | N05_PSAR_POC 1h H4 | 1365 / 2.36 / 0.46 | 587 / 0.18 / 0.58 / 0.40 / 5 | 0.11 / 0.38 |
| 8 | N17_KC_RSI 15m H4 | 81718 / 2.35 / 0.10 | 30859 / 0.08 / 1.10 / 1e-8 / 6 | -0.06 / -0.88 |
| 9 | N07_ICHI_CMO 1h H16 | 2153 / 2.31 / 0.64 | 752 / 0.23 / 0.31 / 0.75 / 4 | -0.31 / -0.64 |
| 10 | N12_ICHI_AO 1h H16 | 2440 / 2.23 / 0.60 | 906 / 0.09 / 0.12 / 0.83 / 3 | -0.12 / -0.27 |

- All 10 keep a positive OOS z; the base rate in the OOS family is 61 %. The cells are correlated: N20 5m and
  N13 4h each appear twice.
- Only 1 of them is significant in OOS (N20 5m), and it is 5 % of the hurdle.
- In FINAL, only 5 of 10 have z > 0.
- 3 of 10 clear the hurdle in OOS: N13 4h H64, N13 4h H16 and DOGE_L 1h H64. All three have OOS z <= 1.15, and all
  three have negative gross fwd in FINAL.
- Among the 15 near-miss cells, N18 1d H4 (not in the top 10) is the 4th cell that clears the hurdle in OOS. It has
  z 0.67 there and fwd -0.14 % in FINAL.

### 2d. Share of IS "sig" cells that stay positive (`out/persistence_sig_share.csv`; family cells)

| IS definition | cells | OOS fwd>0 (base) | OOS z>0 (base) | OOS p<.05 | OOS fwd>=mu* | FINAL fwd>0 (base) | FINAL z>0 | FINAL fwd>=mu* |
|---|---|---|---|---|---|---|---|---|
| IS p < 0.05 | 31 | 21 = 68 % (59 %) | 24 = 77 % (61 %) | 6 | 4 | 13 = 42 % (49 %) | 12 = 39 % | 0 |
| IS z > 2 | 19 | 15 = 79 % (58 %) | 16 = 84 % (61 %) | 3 | 4 | 7 = 37 % (50 %) | 8 = 42 % | 0 |
| IS fwd >= mu* (15 near-miss) | 15 | 6 = 40 % (60 %) | 6 = 40 % | 0 | 4 | 5 = 33 % (50 %) | 2 = 13 % | 0 |
| IS p < .05 & p_vn < .05 | 9 | 5 = 56 % (59 %) | 6 = 67 % | 2 | 2 | 3 = 33 % | 3 = 33 % | 0 |

- Fisher exact tests (IS-sig vs rest, OOS fwd > 0, descriptive; cells are not independent) give p = 0.21 (p < .05
  definition) and 0.056 (z > 2 definition).
- In FINAL every IS-sig group does WORSE than the base rate.
- The 15 cells that cleared the hurdle in IS stayed positive in OOS less often than the average cell (40 % vs 60 %),
  and 0 of them cleared the hurdle in FINAL.

## 3. PREREG 7.3: FINAL values (descriptive; the FINAL window was partly seen before)

- **Carried combos:** none, so there is nothing to report.
- **Top-5 IS cells:** `out/final_top5_gate.csv` (gate IS/OOS/FINAL) and `out/final_top5_exits.csv` (exits in
  IS/OOS/FINAL).
  - (A) is the family top-5 by z.
  - (B) is the `persistence()` top-5, which adds S5 4h H4, N13 1d H4 and N03 1d H64 (n < 100, and 0 FINAL signals
    for N03).

| cell | FINAL n | fwd | mu* | fwd/mu* | z | p_vn | coins+ | best FINAL exit (trades, PF, net/trade, coins+) |
|---|---|---|---|---|---|---|---|---|
| N13_3OUTSIDE 4h H64 | 115 | -1.40 % | 1.16 % | -1.20 | -1.30 | 0.94 | 1/7 | all 5 exits lose. Best: ATR_SL2_TP3, 104 tr, PF 0.81, -0.53 %, 2/7. TIME_H: PF 0.48, -2.69 % |
| N20_EMA9_CHOP 5m H4 | 38229 | +0.005 % | 0.164 % | 0.03 | 1.64 | 0.85 | 7/7 | all 5 lose, 0/7 coins each. Best: ATR_SL3_TP6, PF 0.57, -0.135 %. TIME_H: 29,449 tr, PF 0.32, -0.138 % |
| N20_EMA9_CHOP 5m H16 | 38229 | +0.016 % | 0.188 % | 0.08 | 1.74 | 0.55 | 7/7 | all 5 lose. Best: ATR_SL3_TP6, 9,507 tr, PF 0.76, -0.123 %, 0/7 |
| DOGE_L 1h H64 (prev. ex.) | 664 | -0.09 % | 0.57 % | -0.16 | 0.34 | 0.70 | 2/7 | Best: ATR_SL3_TP6, 400 tr, PF 1.01, +0.02 %, 4/7. TIME_H: PF 0.80, -0.47 %, 1/7 |
| N13_3OUTSIDE 4h H16 | 117 | -0.36 % | 0.57 % | -0.62 | -0.47 | 0.74 | 2/7 | all 5 lose. Best: TRAIL_SL3_TR3, PF 0.71, -0.65 %, 1/7. TIME_H: PF 0.66, -0.71 %, 0/7 |

## 4. Timeframe comparison (`out/tf_summary.csv`, `out/tf_h_summary_common.csv`, `out/oos_table_isbestH_counts.csv`)

Cells with n >= 100 in that split:

| TF | median fwd - mu* (%) IS / OOS / FINAL | median fwd/mu* IS / OOS / FINAL | share fwd > cost IS / OOS / FINAL | mean z IS / OOS / FINAL |
|---|---|---|---|---|
| 5m | -0.206 / -0.192 / -0.184 | -0.03 / +0.03 / +0.01 | 0 % / 1 % / 2 % | -0.72 / +0.61 / +0.21 |
| 15m | -0.254 / -0.234 / -0.223 | -0.03 / +0.04 / -0.00 | 0 % / 3 % / 1 % | -0.38 / +0.41 / -0.03 |
| 30m | -0.319 / -0.259 / -0.270 | -0.03 / +0.04 / -0.04 | 1 % / 13 % / 4 % | -0.34 / +0.37 / -0.16 |
| 1h | -0.338 / -0.343 / -0.318 | +0.04 / +0.04 / -0.00 | 16 % / 13 % / 10 % | +0.27 / +0.14 / -0.03 |
| 4h | -0.721 / -0.381 / -0.644 | -0.02 / +0.38 / -0.12 | 12 % / 53 % / 21 % | +0.08 / +0.31 / -0.26 |
| 1d | -1.172 / -2.247 / -1.340 | +0.17 / -0.43 / +0.09 | 44 % / 40 % / 28 % | +0.27 / -0.33 / -0.23 |

How to read this:
- **Raw median fwd - mu* is "least bad" at 5m in every window, but only because the 5m hurdle is the smallest.**
  The median 5m strategy has gross of about 0 (-0.005 % IS, +0.005 % OOS), so its fwd - mu* is simply -mu*. The raw
  number ranks timeframes by hurdle size, not by strategy quality.
- **Hurdle-normalised, no timeframe's median strategy captures even 5 % of the hurdle in all three windows.**
  - 1h is the only TF with a non-negative median in both IS and OOS (+0.04 / +0.04), but it is -0.00 in FINAL.
  - 4h looked best in OOS (median 0.38; 53 % of cells beat cost; 18 cells >= mu*) and reversed in FINAL
    (-0.12; mean z -0.26).
- **Cost feasibility: 1h to 1d are the only timeframes where a meaningful share of strategies beats even the raw
  cost.** At 5m and 15m it is 0-3 % of cells in every window, so costs dominate there.

**OOS 4h was a trending-regime effect, not a persistent edge.**
- Drift decomposition (`out/drift_vs_timing_by_tf.csv`): in the 18 OOS 4h cells with fwd >= mu*, drift
  (null_mean) is a median of only 6 % of fwd, and 12 cells have fwd - null_mean >= mu*.
- So OOS 4h trend entries did time the 2024-07..2025-08 trend.
- In FINAL (2025-08..2026-09) market drift was negative (pooled 4h H64 forward return -1.03 % vs +2.93 % in OOS;
  `out/market_drift_oos_final.csv`), and the same group has mean z -0.26.

**Long-only cells that clear the hurdle in OOS partly ride the bull drift.**
- DOGE_L 1h H64: OOS fwd 1.02 %, of which null_mean (random-timed long entries) is 0.63 %. The timing part is 0.40 %
  (z 0.80). In FINAL: -0.09 %.

**Strategy x TF view with the IS-chosen H** (`oos_table.md`, `out/oos_table_isbestH_long.csv`):
- OOS fwd/mu* >= 1 at the IS-chosen H: 0 of 33 (5m), 0 of 33 (15m), 1 of 32 (30m), 1 of 31 (1h), 3 of 27 (4h) and
  1 of 6 (1d).
- Median OOS ratio: +0.03, +0.03, +0.02, -0.07, +0.07 and -1.31.
- The IS 1d H64 trend-followers (S2, N01, N02, N04, N23, N25) all had negative OOS forward returns: ratios -1.2 to -4.4.

## 5. Descriptive what-if (NOT the protocol; `whatif_carry.py`, `out/whatif_hypothetical_carry.csv`)

Suppose the Holm gate had been ignored, and the Combine agent's descriptive IS exit runs on the 15 near-miss cells had
been fed to `select_exits`. Five combos would then have been "carried":
- N02_ST_KST 1d H4 TIME_H
- N03_ADX_GC 1h H4 ATR_SL2_TP3
- N13_3OUTSIDE 4h H64 TIME_H_SL3
- N18_VWMA_MACD 1d H4 TIME_H
- N23_HA_ST 1d H16 TIME_H

`holdout_confirm` on OOS gives **0 of 5 confirmed**, and FINAL also gives 0 of 5.

| combo | OOS trades / PF / net per trade / coins+ / gate p / p_vn | FINAL trades / PF / net per trade / coins+ |
|---|---|---|
| N13 4h H64 TIME_H_SL3 | 87 / 1.30 / +1.27 % / 3 / 0.12 / 0.32 (fails coins + p) | 88 / 0.39 / -2.61 % / 0 (1 of 14 months positive) |
| N18 1d H4 TIME_H | 88 / 1.37 / +0.95 % / 4 / 0.25 / 0.54 (fails p) | 89 / 0.78 / -0.67 % / 3 |
| N02 1d H4 TIME_H | 70 / 0.72 / -1.00 % / 2 | 75 / 0.75 / -0.68 % / 2 |
| N23 1d H16 TIME_H | 120 / 0.88 / -0.87 % / 3 | 129 / 0.94 / -0.25 % / 3 |
| N03 1h H4 ATR_SL2_TP3 | 68 / 0.99 / -0.01 % / 5 | 72 / 0.98 / -0.02 % / 3 |

The two combos that were positive in OOS (N13 4h, N18 1d) were negative in FINAL, and N13 lost heavily there.

Exit-stage limitation: at 1d H64 the exit stage cannot run on OOS or FINAL. PREREG 5 excludes coins whose window is at
most 8H+4 = 516 bars, and OOS 1d has about 383. Those rows have 0 trades by rule; this is not a bug.

## 6. Bottom line

1. **No (strategy, timeframe) survives.** The pre-registered protocol produced no candidate at the IS gate
   (0 of 528), so the holdout had nothing to confirm.
   - Every descriptive angle agrees: OOS persistence, FINAL, and the what-if that ignores the gate.
   - The best-looking IS cells either did not repeat in OOS (all OOS z <= 1.15 for the cells that cleared the
     hurdle) or repeated only as a statistically detectable but economically worthless timing tilt (N20_EMA9_CHOP 5m,
     about 1 bp gross against 14 bp cost).
   - All of them were negative or flat in FINAL.
2. **Which timeframe is least bad.**
   - None has a median strategy near the hurdle.
   - 5m, 15m and 30m are a firm negative, with good power: gross is about 0 against 0.14 % round-trip cost, and 0-3 %
     of cells beat cost in any window.
   - 1h is the most stable: median ratio about +0.04 in IS and OOS, about 0 in FINAL. That is still only a few
     percent of the hurdle.
   - 4h was best in OOS but reversed in FINAL.
   - 1d is too underpowered to say anything: OOS has 20 family cells, and the exit stage cannot evaluate H64.
   - If this project continues, the only defensible direction is 1h-4h, and only as NEW, separately pre-registered
     hypotheses tested forward on paper. Nothing in this sweep justifies a live bot.
3. **Previously examined strategies.**
   - The friend's DOGE strategy (DOGE_L/S): at its native 5m the IS/OOS/FINAL fwd/mu* is +0.01 / +0.02 / -0.01.
     Its best cell (1h H64) cleared the hurdle in IS and OOS mostly through long-side market drift (OOS timing
     z 0.80), then went to -0.16 in FINAL.
   - V4.5 (V45_AMB): no timeframe near the hurdle in any window.

## 7. Caveats

- **Power.** OOS is about 13 months, so its power is roughly a third of IS per cell. Examples of the OOS one-sided
  MDE80 (2.49 x null_sd, `out/focus_cells_is_oos_final.csv`): N13 4h H64 2.9 % against its IS fwd of 3.3 %;
  DOGE_L 1h H64 1.24 %. So an OOS "not significant" for the 4h/1d cells is weak evidence by itself. The FINAL
  reversal is what makes the negative conclusion firmer.
- **Spot proxy for perps.** Funding is fixed at 0.01 %/8h, and there is no basis. The data defects are the known
  ones: 2025-03-25 missing for SOL/XRP/LTC; BCH OOS/FINAL gaps; 2026-04-22 missing everywhere; the last 2 days
  provisional. All are unfilled, as pre-registered.
- **FINAL was partly seen before** (15m FINGRAD/V39/OBV from 2025-08-07, DOGE and V4.5 from 2025-03). It is
  descriptive only.
- **What is not pre-registered.** The stratified-permutation benchmark, within-stratum Spearman, drift decomposition,
  per-split Holm, sig-share Fisher tests and the what-if are my own descriptive additions. None of them changes a rule
  or a decision.
- **Two OOS/FINAL tables use their own family** (m = 486 OOS, m = 493 FINAL): the Holm columns in
  `gate_all_{oos,final}_applied.csv`. They are labelled `*_DESCRIPTIVE_own_family`.
- **N20_EMA9_CHOP has n_long = 0 at every TF and in every split** (IS, OOS and FINAL; `out/cells_is_oos_final_long.csv`).
  The frozen approximate port only produces shorts; Discover g5m already noted "short-only". I did not investigate
  the port, because the code is frozen. Its OOS/FINAL "timing" is short-side only.

## Files

- **Scripts:** `recheck_is_gate.py`, `assemble.py`, `persistence_holdout.py`, `exits_holdout.py`, `whatif_carry.py`,
  `build_oos_table.py`, `drift_decomp.py`, `counts_by_split.py`, `final_top5.py`, `run_timed.sh`, `chain1.sh`,
  `chain2.sh`, `chain_exits.sh`, `groupA.txt`, `groupB.txt` (the 5m strategy split, copied from discover_g5m).
- **Gate outputs:** `out/gate_{oos,final}_*.csv` (raw harness tables), `out/signals_{oos,final}_*.npz`,
  `out/timings_*.csv`, `out/gate_all_{oos,final}_applied.csv`, `out/cells_is_oos_final_long.csv`.
- **Persistence:** `out/persistence_*.csv|json`, `out/nearmiss15_is_oos_final.csv`,
  `out/persistence_merged_cells.csv`.
- **TF summaries:** `out/tf_summary.csv`, `out/tf_h_summary_common.csv`, `out/counts_by_split.csv`,
  `out/drift_vs_timing_by_tf.csv`, `out/market_drift_oos_final.csv`, `out/focus_cells_is_oos_final.csv`.
- **Exits:** `out/exits_descriptive_{oos,final}_{1h_4h_1d,5m}.csv`, `out/whatif_hypothetical_carry.csv`,
  `out/final_top5_{gate,exits}.csv`.
- **Table:** `oos_table.md` (strategy x TF, IS-chosen H evaluated in OOS/FINAL), `out/oos_table_isbestH_long.csv`,
  `out/oos_table_isbestH_counts.csv`.
- **Logs:** `logs/` (gate_*, exits_*, assemble, persistence, whatif_carry, counts_by_split, drift_decomp,
  final_top5, build_oos_table, meta_check, recheck_is_gate, prereg_check_after).
- **Runtime:** OOS gate 5m 179-189 s per half, 15m 123 s, 30m 64 s, 1h 32 s, 4h 10 s, 1d 3 s. FINAL is similar.
  Descriptive exits took 111 s (OOS 1h/4h/1d) plus 23 s (5m, observed only).
