# Adversarial verification of the strategy x timeframe sweep

Verifier agent, 2026-09-29, 13:06-13:27 UTC. Every number below comes from code in this directory (`*.py`).
Logs are in `logs/` and tables in `out/`. I wrote my own minimal code; it does not re-run the agents' scripts.
I read only `sweep/data/is/` bars. For the Holdout claims I read the Holdout agent's derived gate tables in
`holdout/out/*.csv` (statistics, not bars). I did not read any OOS or FINAL bar, because nothing was carried, so
PREREG section 6 never triggers and holdout discipline reserves those files for the Holdout agent.

## 0. Integrity
- PREREG.md sha256 `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50`.
  `sha256sum -c PREREG.sha256` gave 11/11 OK at 13:06:55 UTC (before) and at 13:26:25 UTC (after).
- `lib/sweep_lib.py` is an unmodified copy (sha `2b20c3c1...cd543`), and `lib/vendor/` is byte-identical to
  `harness/vendor/`. The vendor strategies.py, engine.py and ports12.py have the same sha256 as the originals in
  /home/user/crypto-bot-research.
- Every agent's copy of sweep_lib.py, run_gate_tf.py and vendor/ is byte-identical to the harness.
- No bug was found and nothing was fixed, so no rule changed.
- 0 files under sweep/data were modified after PREREG.sha256. /home/user/crypto-bot-research is git-clean.
  No Astral call was made.

## 1. Check 1: rules applied as written (`check1_holm.py`, `logs/check1.log`). Verdict: CONFIRMED
- I concatenated the 7 raw Discover tables into 666 cells: 0 duplicates, 37 strategies x 6 TF x 3 H.
- p = 1 - Phi(z) matches to 2e-16, and the same holds for p_vn. cost_H and mu* recomputed from the formula match to
  1e-16. symbols_pos and n_coins_ge10 recomputed from the per-coin columns: 0 mismatches.
- Family: m = 528 (5m 105, 15m 102, 30m 99, 1h 96, 4h 81, 1d 45). I wrote my own Holm.
  - The Holm first step needs p < 9.47e-5.
  - The minimum p is 7.96e-4 (N13_3OUTSIDE 4h H64), giving p_holm 0.420. It would need m <= 62.
  - Only 1 family cell has p < 0.05/37, and 0 have p < 0.05/100.
  - Even Holm within the 4h TF alone (m = 81, threshold 6.2e-4) fails.
- Survivors: gate_pass 0 and gate_pass_spec 0. My p_holm matches Combine to 6e-17. carried = [] is correct.
- Condition counts: c1 = 0, c2 = 15, c3 = 15, c4 = 220.
- Without any multiplicity correction (raw p < .05, p_vn < .05, fwd >= mu*, symbols), 3 cells would pass:
  N13 4h H16, N13 4h H64 and N04_ST_KLINGER 1d H64.
- The per-TF table (fwd > 0, z > 2, fwd > cost, fwd >= mu*, max fwd/mu*) reproduces Combine exactly
  (`logs/check1b_tf_table.log`).

## 2. Check 2: independent recompute of cells (`indep.py`, `check2_cells.py`, `logs/check2.log`). Verdict: CONFIRMED
- 19 cells were recomputed: 12 random (2 per TF, rng 424242) plus N13 4h H16/H64, DOGE_L 1h H64, V45_AMB 15m H64,
  1h H16 and 1d H64, and N04 1d H64. There are no carried combos, so none could be added.
- Everything is my own code: CSV loader, window/warm-up logic, forward returns, RV, hurdle and shift null. I did
  not use sweep_lib. The signals come from the ORIGINAL vendor functions, called directly.
  - V45_AMB: the HTF bars are built from the 5m data by my own resampler and passed to the original
    `strategies.v45_exact_amb`, with the HTF timestamps shifted so that its hard-coded "+15 min" lands on the true
    HTF close. This is an independent route to the generalised mapping.
  - DOGE_L: my own length scaling.
- Result: max abs difference versus the harness is 0 for n and every per-coin n; about 1e-16 for fwd and every
  per-coin fwd; 3e-15 for z; 5e-12 for z_vn; 1e-16 for mu*; 0 for symbols_pos.
- An independent null (B = 2000, different seed) gives nearly the same z. N13 4h H64 has z 2.99 against the
  harness's 3.16; its empirical p is 0.0035 against a normal-approximation p of 0.0008, so the normal tail is
  somewhat optimistic.

## 3. Check 3: look-ahead (`check3_lookahead.py`, `out/check3_lookahead.csv`). Verdict: CONFIRMED (no leak)
- Truncation test on the harness's own registry functions. Signals on df[:t+1] were compared with the full series
  on all bars <= t, at 365 truncation points (half of them at signal bars): 0 failures. Cells tested:
  - V45_AMB 15m->1h (BTC, SOL) and 1h->4h (ETH, DOGE)
  - 31-set ports at 4h: N13_3OUTSIDE (BTC, BCH), S2_ST_ROC (ETH), N11_BREAKAWAY (SOL)
  - DOGE_L 1h and N23_HA_ST 1d
- HTF mapping, checked with my own code (15m->1h, 1h->4h, 4h->1d, 1d->1w): on 100% of chart bars the HTF bar used
  is exactly the previous completed HTF bin. 0 bars use the containing, unfinished bin.
- The "current-HTF" leak changes signals on 73, 18 and 7 bars at 15m, 1h and 4h, so the test has teeth. At 1d it
  changes 0 bars, because V45 is almost silent there. Weekly bins are Monday-labelled.
- Resampler:
  - Every 15m/30m/1h/4h/1d IS file equals my own floor-groupby aggregation of the 5m bars. OHLC difference is 0,
    and 0 bins contain a 5m bar outside [T, T + len).
  - The harness `resample_ohlcv` (the V45 HTF path; 1h, 2h, 4h, 1d and 1w W-MON) equals my aggregation with 0
    label mismatches, and weekly labels are Monday.
  - Partial bins exist where 5m bars are missing: XRP 252 (1h) and BCH 25 (1h). This is as disclosed and does not
    leak.

## 4. Check 4: holdout discipline. Verdict: CONFIRMED (limit: file access times are not informative)
- A grep of all Discover and Combine code and logs finds no reference to data/oos or data/final, and every logged
  run uses `--split is`.
- discover_g5m and combine expose only a `data/is` symlink. The other Discover scripts set `SWEEP_DATA` to
  sweep/data with split "is". Several scripts assert max ts < 2024-07-01.
- No CSV output of Discover or Combine contains a timestamp at or after 2024-07.
- Limit: `relatime` means file atime cannot prove the OOS/FINAL files were never opened. The evidence is the code,
  the logs and the outputs.

## 5. Check 5: breaking a CONFIRMED combo. Verdict: N/A, nothing was confirmed
Descriptive IS-only stress of the best near-misses (`check5_break_nearmiss.py`):
- **N13_3OUTSIDE 4h (approximate port).**
  - Within IS it survives leave-one-coin-out (fwd/mu* 1.62-2.19 at H16), a one-bar-late fill (1.79) and an extra
    0.10% RT cost.
  - It is concentrated: at H64 the top-10 signals give 72% of the total, and at H16, 2022 has fwd 0.06%.
  - Out of sample it faded: OOS fwd/mu* 1.03/1.13 with z < 1.2 and p_vn >= 0.24; FINAL -0.62/-1.20.
- **DOGE_L 1h H64 (previously examined).** Excluding the best month gives fwd/mu* 1.00, and excluding the best 3
  gives 0.59. Its median signal is -0.18% and z_vn is 0.15.
- Across the 15 near-miss cells (from the Holdout tables): 4 clear the hurdle in OOS, and 0 of those have both
  p < .05 and p_vn < .05. 0 clear it in FINAL.

## 6. Check 6: controls and power. Verdict: false-pass OK with A1; power ADEQUATE at 5m-30m, PARTIAL at 1h, INADEQUATE at 4h, NIL at 1d
Two independent views.

**(a) Analytic power from each family cell's real null sd** (`check6_power.py`, `out/check6_power_realnull.csv`).
- To pass Holm step 1 with 80% power, a per-signal edge must be at least (3.73 + 0.84) x null_sd.
- Share of cells in which a hurdle-sized edge is detectable with at least 80% power:
  5m 94%, 15m 86%, 30m 77%, 1h 48%, 4h 2.5%, 1d 0%.
- Median MDE80/mu*: 5m 0.19, 15m 0.45, 30m 0.69, 1h 1.04, 4h 2.27, 1d 4.31.
- At 1d the median MDE80 is 3.3% per signal at H4, 8.4% at H16 and 19.2% at H64.
- At 1d H64 there are only about 12 non-overlapping windows per coin, and the coins are highly correlated.

**(b) Own simulation on the real IS panel** (`check6_controls.py`; 1d and 4h 300 reps, 1h 200 reps).
- Signal types: iid, vol-timed, and the real timing of S2/N13/N23 with random signs. The edge is planted at the
  signal bars.
- Zero-edge false passes under A1: 0 in every cell at 1h, 4h and 1d.
- Raw rule without A1: vol-timed false-passes 1-2 of 300 at 4h, which is about 30-70x the nominal 1e-4. Vol-timed
  raw z sd is 1.43-1.75 at 1h and 1.23-1.46 at 4h. Sparse real timing gives raw z sd up to 1.61 (N13 at 1d H4).
- Power at a planted edge of 1.5 x mu*:
  - 1h: 0.80-1.00 for n >= 1,100.
  - 4h: 0.84-0.93 for iid n = 1,200; 0.997-1.00 for dense real timing (n about 4,000); 0.03-0.10 for N13's own
    timing (n about 236).
  - 1d: 0.05-0.18 at iid n = 230; 0.30-0.61 for the densest real timing (n about 500-650); 0 for N13 timing
    (n = 38).
- At exactly 1 x mu*, power is capped at about 50% by the fwd >= mu* condition.
- Conclusion: at 4h for typical sparse strategies, and at 1d for all of them, the gate could not detect a
  hurdle-sized edge. "No survivor" there is not evidence of no edge.

**(c) Would a forward paper test fix this?** (`logs/check7_papertest_power.log`)
- Even as a single pre-registered test (m = 1), a 6-12 month paper test of the near-miss cells only detects edges
  of 1.5-4.9 x the hurdle. Example: N13 4h H16 needs 2.7% per signal at 6 months against a 0.65% hurdle.
- A short paper test at 1h-1d therefore tests execution, not edge.

## 7. Additional findings (not in the agents' reports, or understated there)
- **A1 is not a neutral calibration fix on real data.**
  - z_vn tests the direction of the vol-normalised return. At 5m-1h that is dominated by bar-level mean reversion:
    z_vn has mean -6.75 and sd 8.25 at 5m, and mean -1.91 and sd 2.61 at 1h. corr(z, z_vn) is only 0.36-0.58
    below 1d.
  - As a result, A1 vetoes right-skewed trend entries. 10 of 11 1h cells with raw z > 1.645 have p_vn >= .05, and
    all 3 1h cells with fwd >= mu* fail A1 (DOGE_L 1h H64: z 2.64, z_vn 0.15). At 1d, 9 of 10 hurdle-clearing cells
    fail A1.
  - It changed nothing in this sweep, because gate_pass_spec is also 0. It would matter for PREREG 6.3 and for
    future protocols. The harness's statement that A1 has "nearly identical power" holds only on the symmetric
    synthetic panels.
- **The n >= 100 rule excluded S5_DONCHIAN_MFI 4h H4** (n = 70, z = 4.54, which exceeds the Holm z of 3.73).
  Harmless: only 2 coins have 10 or more signals, z_vn is 0.50, and it is negative in OOS (n = 22).
- **Holdout table claims reproduce** from their CSVs (`check_holdout_tables.py`):
  - OOS family 486, 30 cells with z > 2, and one own-family Holm cell (N20 5m H4, p_holm 0.021, p_vn 0.135).
  - Spearman 0.335 and z-Spearman 0.035.
  - Minor: the within-(TF, H) mean z-Spearman is 0.063 with 12 of 18 groups positive. The Holdout's 0.02 / 9 of 18
    was computed on fwd - mu*.
  - Only 3 cells have z > 0 and fwd > cost in all three windows, and all 3 are below the hurdle in all windows.

## 8. Verdict per claim
| claim | verdict |
|---|---|
| 0 gate survivors; carried = [] (m = 528, min p_holm 0.42) | CONFIRMED |
| 5m/15m/30m: nothing beats the hurdle, power adequate, so a real negative | CONFIRMED (for these 37 rules at chart-bar parameters and fixed-horizon entries) |
| 1h: partly informative | CONFIRMED (48% of cells had power at the hurdle) |
| 4h/1d "no survivor" is mostly a power statement | CONFIRMED, and stronger than stated: 1d has 0% power at the hurdle, and 4h only 2.5% of cells |
| No look-ahead (V45 HTF mapping, ports, resampler) | CONFIRMED |
| Holdout discipline in Discover/Combine | CONFIRMED (code/log evidence; atime not usable) |
| A1 is strictly more conservative, with nearly identical power | Conservative: CONFIRMED. Nearly identical power: NOT on real data; it vetoes skewed trend entries at 5m-1h |
| Raw null anti-conservative for vol-timed/sparse signals | CONFIRMED (independent controls) |
| Near-misses faded OOS/FINAL; persistence is weak | CONFIRMED |
| "1h is the most stable TF" | WEAK: median fwd/mu* +0.04 is 4% of the hurdle, which is noise-level, not stability |
| "Next step: a separately pre-registered paper test at 1h-4h" | QUALIFIED: 6-12 months of paper trading has no power to detect hurdle-sized edges (needs 1.5-4.9x) |

## 9. Corrected bottom line
- No strategy x timeframe combination has evidence of a tradable edge after realistic Binance taker costs. The
  pipeline that produced that verdict is correct, rule-faithful and free of look-ahead.
- At 5m, 15m and 30m the negative is informative: the entries carry essentially zero gross forward return
  (best 0.04%, 0.15% and 0.29% per signal against a hurdle of 0.17-0.48%), and the gate had power.
- At 4h and 1d the sweep says nothing either way: a hurdle-sized edge would have been missed almost surely.
- Nothing supports running a live bot.
- If the user still wants to pursue 4h/1d, a paper test of months will not answer the question. What would help is
  a single pre-registered hypothesis (m = 1) tested on a longer or wider untouched sample (more coins or history),
  and accepting a multi-year horizon.
