# verify_robust: adversarial check of the "robust" auditor

Scratch: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/verify_robust`

Rules followed:
- Nothing under /home/user/crypto-bot-research was modified.
- No Astral tools were used.
- At most 2 python processes ran at a time.
- 15m statistics were computed only on frames truncated at 2026-05-08 00:00 UTC. The one exception is reading the reproduction's IS ledger, which contains 521 exits after the split. That ledger is the delivered IS run.

## Method (independent of the auditor's code)

**Engine.**
- `bt/veng.py` is a numba re-implementation of engine.py (not a copy of the auditor's engine2.py). It has these switches:
  - cost (fee in / out / TP, slippage, funding)
  - `reentry_fix` (`i < next_free`)
  - `intrabar`: 0 = pess (engine.py); 1 = opt (favourable extreme first, stop raised inside the bar, FIXED TP-first unless the bar gaps through the SL); 2 = TradingView (the extreme nearer the open is visited first).
- `bt/vgrid.py` runs the grid and pools the results. Its `pool()` equals `analyze.pooled` + `apply_rule`: max |dPF| is 2e-16 on S6 and N08.

**Signals.**
- `bt/sigcache.py`: 15m signals are computed on truncated frames. 5m uses the full window, with the full df15 as in run.py.

**Validation against the reproduction ledger `repro/results/trades_IS_15m_all5.csv`.**
- 899,772 trades that exit before the truncated end matched 1:1 on (symbol, strategy, exit, signal_idx). There were 0 left-only and 0 right-only trades.
- entry_idx, exit_idx, side and reason: 0 mismatches.
- |d gross|, |d net|, |d mae| and |d mfe|: 1e-16 or less.
- My truncated base grid has 900,315 trades against 900,334. The difference is the 19 trades that entered on the first OOS bar.
- Pooled: 0 pass, max PF 0.9282590 (delivered 0.9282590), max |dPF| 0.00225, 19 rows with different trade counts.

## Variant results (my runs)

15m IS, 364 combos:

| variant | trades | PASS | pass non-ladder | #PF>=1 | max PF | max PF non-ladder | median exp | mean PF F / T / L |
|---|---|---|---|---|---|---|---|---|
| base | 900315 | 0 | 0 | 0 | 0.928 | 0.928 | -0.163 | 0.698 / 0.598 / 0.358 |
| zero | 894027 | 2 | 1 | 67 | 1.254 | 1.206 | -0.024 | 0.954 / 0.891 / 0.898 |
| real | 896408 | 0 | 0 | 0 | 0.991 | 0.991 | -0.125 | 0.767 / 0.654 / 0.448 |
| reent | 948099 | 0 | 0 | 0 | 0.908 | 0.908 | -0.162 | 0.698 / 0.597 / 0.358 |
| zero_reent | 941972 | 1 | 0 | 63 | 1.239 | 1.185 | -0.024 | |
| real_reent | 944239 | 0 | 0 | 0 | 0.970 | 0.970 | -0.125 | |
| opt (zero cost) | 905013 | 57 | 1 | 126 | 4.295 | 1.221 | -0.014 | 0.968 / 0.628 / 2.195 |
| base_opt | 910735 | 11 | 0 | 23 | 2.218 | 0.928 | | |
| real_opt | 907185 | 26 | 0 | 53 | 2.538 | 0.991 | | |
| tv | 906960 | 3 | 0 | 6 | 1.450 | 0.928 | | 0.701 / 0.631 / 0.834 |
| zero_tv | 901121 | 57 | 1 | 125 | 2.752 | 1.206 | | |
| real_tv | 903373 | 7 | 0 | 24 | 1.664 | 0.991 | | 0.771 / 0.690 / 1.029 |

5m V4.5, 39 combos (3 of 3 symbols required):
- base 0 pass (max PF 0.799), zero 0 (1.147), real 0 (0.899).
- reent / zero_reent / real_reent: 0 each.
- opt 6, all L50 (max 1.408). zero_tv 4, all L50. real_tv / real_opt / tv / base_opt: 0.

These agree with the auditor's tables to the reported digits. The auditor's opt and real_tv runs also used `reentry_fix`, which explains 56 vs 57 passes and 0.892 vs 0.899.

**Costs.**
- Implied all-in cost (zero-cost exp minus costed exp, averaged over combos):
  - base: 0.1385% (15m) and 0.1366% (5m)
  - real: 0.1001% (15m, range 0.081–0.128) and 0.0959% (5m)
- In the real variant, the fee is 0.063% on TP exits and 0.090% on all other exits. Funding is 0.0032% per trade.
- In the zero variant, net == gross everywhere.

**Cost margin of the two zero-cost passers** (flat cost c, bisection):
- N08_ICHI_WR L50_sl20 passes while c <= 0.00719%.
- N08 F_sl1.5_tp1.5 passes while c <= 0.00182%.
- Pass counts at c = 0.05%, 0.10% and 0.14% are 0.

**Pre-cost expectancy (zero variant), all 364 combos**, in % per trade:

| min | 5% | 25% | 50% | 75% | 95% | max |
|---|---|---|---|---|---|---|
| -0.108 | -0.068 | -0.041 | -0.024 | -0.007 | +0.025 | +0.088 (S6 F_sl2.0_tp3.0) |

- Above 0: 67 combos. Above 0.05%: 5. Above 0.10%: 0.
- 5m max is +0.048%. 24 of 39 are above 0 and none above 0.05%.
- Delivered `exp_gross_pct` minus the true pre-cost value averages -0.035% (range -0.054..-0.012). This is the slippage that stays inside "gross" (ROB-7).
- Mean pre-cost exp by exit ranks L50_sl20 4th and L50_sl15 5th of 13. **Mean PF ranks them 10th and 12th of 13 even at zero cost.**

**Long / short split** (reproduction ledger):

| side | pass | PF>=1 | mean net | mean gross | WR | median PF |
|---|---|---|---|---|---|---|
| long | 0 | 1 | -0.171 | -0.068 | 0.359 | 0.627 |
| short | 0 | 2 | -0.163 | -0.060 | 0.362 | 0.687 |

- IS drift per bar: BTC -0.15bp, ETH -0.27, SOL -0.31, LTC -0.31, BCH -0.10.
- Close changes from bar 1000 to the last IS bar: BTC 117,726 → 80,005 (-32%), ETH -49%, SOL -54%, LTC -54%, BCH -23%.

**Leakage.**
- 19 IS trades enter at 2026-05-08 00:00.
- 521 IS trades exit at or after the split. The latest exit is 2026-05-10 16:30.

**Re-entry fix, 15m.**
- Trades rise 5.3%. Mean dPF is -0.0004, median 0. 157 of 364 combos improve. Pass counts: 0→0 (base), 2→1 (zero), 0→0 (real).
- 5m: trades +2.7%, pass 0 in every variant.

**TP-first effect on FIXED exits** (zero cost):
- 15m: mean PF 0.954→0.968, mean exp -0.0207→-0.0150.
- 5m: no effect.

## Random circular-shift null

Built with my own seeds, using a 10–90% shift of the post-warmup segment for each (symbol, strategy). Script: `bt/vnull.py`.

| tf / cost | reps | real PASS | null passes/rep | reps with ≥1 pass | real max PF vs null max-PF range | combos beating all reps (expected) | mean exp: real vs null |
|---|---|---|---|---|---|---|---|
| 15m zero | 20 | 2 | 4.0 | 14 (70%) | 1.254 vs 1.157–2.086 (exceeded in 10/20) | 7 (17.3) | non-ladder -0.024 vs -0.016 |
| 15m real | 30 | 0 | 0.30 | **5 (17%, 95% CI 6–35%)** | 0.991 vs 0.905–1.659 | 9 (11.7) | -0.123 vs -0.115 |
| 15m real_tv | 20 | 7 | 0.80 | 8 | | 24 (17.3) | ladder +0.0045 vs -0.0077 |
| 5m zero | 60 | 0 | 0.05 | 3 (5%) | | 9 (0.6) | non-ladder +0.0116 vs -0.0203 |
| 5m real | 60 | 0 | 0 | 0 | | | |
| 5m opt | 60 | 6 | 5.63 | | | | ladder +0.041 vs +0.043 |
| 5m zero_tv | 60 | 4 | 5.43 | | | | ladder +0.041 vs +0.042 |

- Every 15m real-cost null pass came from N03_ADX_GC (about 155 trades) or N08_ICHI_WR (about 230 trades).
- 5m FIXED exits at zero cost, real minus null, z by strategy: V45_ANY 1.99, EXACT_AMB 2.13, EXACT_AMB_G1 2.06. The three strategies are nested, so this is about one test.
- At zero cost, N08 L50_sl20 (PF 1.254) beats 20/20 of **its own** null reps, and N08 F_sl1.5_tp1.5 beats 19/20. Yet the family-wise max-PF null exceeds 1.254 in 10/20 reps. A per-combo 95th-percentile test, which is the auditor's "minimum" fix, would therefore pass what the family-wise test calls noise.

## V4.5 64-bar forward drift (1000 circular shifts)

Script: `bt/vfwd.py`, log `fwd_null.log`.

| strategy | symbol | mean | naive t | null z | p |
|---|---|---|---|---|---|
| EXACT_AMB | BTC | +0.0902% | 2.79 | 1.35 | 0.091 |
| EXACT_AMB | ETH | +0.1403% | 2.91 | 1.32 | 0.084 |
| EXACT_AMB | SOL | +0.1781% | 3.05 | 1.53 | 0.061 |

- These equal the delivered forward_ALL_5m_v45.csv. The auditor's ETH figures, 0.1416% and t 2.94, are slightly off.
- Long and short both have positive means: long 0.12 / 0.16 / 0.27, short 0.065 / 0.12 / 0.069.
- Over the 5m window: BTC +6.0%, ETH +19.6%, SOL +34.7%.

## Synthetic martingale ladder calibration

Script: `bt/vsynth.py`. Setup: driftless log random walk, 4000 random entries, zero cost. The truth is the same engine run on the tick path, with the stop updated every tick, i.e. the real-time ladder.

| setting | exit | pess | opt | tv | tick truth | paired bias vs tick (pess / opt / tv) | WR pess / tv / tick |
|---|---|---|---|---|---|---|---|
| SUB=600, sd 0.35% | L50_sl15 | +0.012 | +0.095 | +0.104 | +0.0065 | +0.006 / +0.089 / +0.098 | 0.467 / 0.568 / 0.565 |
| SUB=600, sd 0.35% | L50_sl20 | +0.014 | +0.098 | +0.115 | +0.009 | +0.005 / +0.089 / +0.106 | 0.526 / 0.636 / 0.634 |
| SUB=180, sd 0.35% | L50_sl15 | | | | | +0.007 / +0.088 / +0.098 | |
| SUB=180, sd 0.35% | L50_sl20 | | | | | +0.006 / +0.088 / +0.106 | |
| SUB=180, sd x1.3 | L50_sl15 | | | | | **+0.022** / +0.158 / +0.150 | |
| SUB=180, sd x1.3 | L50_sl20 | | | | | **+0.022** / +0.149 / +0.159 | |

- FIXED exits are identical in all bar modes.
- TRAIL 1.5 under opt: -0.10%.
- pess vs tick is always slightly *positive*. This is discretization overshoot: the bar engine fills at the stop level, while the tick path fills beyond it. So pess does not hide an edge. It is within about 0.01% at base vol and about 0.02% with higher vol or coarser ticks.
- On noise, the tv model reproduces the real-time win rate but overstates the expectancy by about 0.1%.

## Why real signals beat the null under tv

Scripts: `vtvdiag*.py`, zero cost, L50 exits.

**All 28 strategies pooled** (5 null reps):
- Real entry bars are only about 5% larger than null bars: mean range 0.56% vs 0.54%.
- Real minus null under tv: +0.005%. Under pess: -0.005%.

**8 selected strategies** (N08, N09, N12, N17, OBV_S, S5, S6, V39), 8 reps:
- Entry-bar range is about 19% larger on average: N17 +40%, S5 +58%, S6 +26%, N09 +19%.
- Real minus null: +0.043 (tv) vs +0.007 (pess).

**6 strategies, 20-bin range match plus bar-shape match** (open position, body sign):
- Real minus null under tv goes +0.0505 → +0.022 (range only) → +0.014 (range and shape).
- Under pess: +0.007 → +0.001.

**So about 70% of the tv advantage is explained by entry-bar size and shape, not all of it.** The residual is about 0.014% per trade. That is noise-sized and far below both the tv bias (about 0.1%) and costs.

## Win-rate decomposition (ROB-3)

5m V45_EXACT_AMB_G1 L50_sl15, win rate by variant:

| cost | pess | tv |
|---|---|---|
| zero | 0.548 | 0.582 |
| base | 0.396 | 0.533 |

- Under pess, 16% of trades are "small wins" (0 < gross < 0.14%). In these, the lock was armed at bar close and then filled at the next bar's open, below the lock (lock-exit gross quartiles 0.114 / 0.188 / 0.22%). Costs turn them into losses.
- So most of the 40% vs 55% gap comes from costs acting on the bar-close fill mechanics. The rest (about 3–14pp) comes from the intrabar path.
- 15m V39_15M L50_sl20: zero 0.535, base 0.407, zero_tv 0.636, tv 0.605, real_tv 0.624 (PF 0.976).

## TP fill-on-touch (not covered by the auditor)

- For 226,137 TP exits in the 15m real ledger, the bar's favourable extreme exceeded the TP by less than 1bp in 4.4% of cases, less than 2bp in 8.7%, and less than 5bp in 19.6%.
- A trade-through requirement for limit fills would lower FIXED results. This is an optimistic bias, so it does not threaten the headline.

## Verdict on the auditor

The headline "0/364 and 0/39 pass; no edge robust to costs and engine choices" is confirmed independently. Corrections:

- **ROB-5.** The realistic-cost family-wise false-positive rate is about 17% (5/30; 20% when pooled with the auditor's 3/10), not "about 30%". The recommended per-combo test is insufficient; use the family-wise max statistic.
- **ROB-2.** The explanation "only because the bars are 30% larger" is about 70% right. Pooled over all strategies, bars are only 5% larger.
- **ROB-3.** "Mid-pack" holds only by expectancy; by PF the ladder is still 10th and 12th of 13 at zero cost. The 40% win rate is mostly costs acting on small bar-close lock fills. This is an explanatory issue and does not bias the results.
- **pess vs tick.** The pess engine is within 0.01–0.02% of tick truth, and slightly optimistic.
- **Null pass counts.** Mine are 5m zero-cost 3/60 reps with a pass (the auditor said 0), and 15m zero-cost null mean 4.0 per rep (the auditor said 5.9). Both are sampling noise.
