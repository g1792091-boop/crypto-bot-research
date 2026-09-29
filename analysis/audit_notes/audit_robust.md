# audit_robust: cost and engine sensitivity of the stage-1 "no edge" verdict

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/audit_robust`
Nothing under `/home/user/crypto-bot-research` was modified. No Astral tools were used.
At most 2 heavy python processes ran at once.

## 0. Setup and validation

- `bt/` copied here. The data dir is a symlink to the project data.
- `bt/engine2.py` is a copy of `engine.py` with opt-in switches. **With every switch at its default it produces the same ledgers as engine.py**: 104 of 104 ledgers were identical, checked on BTC and SOL × 4 strategies × 13 exits.
  - `fee_exit_maker` sets the fee on FIXED-TP limit exits.
  - `reentry_fix` changes `i <= next_free` to `i < next_free` (engine.py:149 vs the comment at engine.py:159).
  - `tp_first` handles a bar where SL and TP are both touched: the exit is the TP unless the bar gapped through the SL.
  - `peak_incl_current` lets a trail or ladder stop be raised by the current bar's extreme, filling at the raised stop (path: favourable extreme first).
  - `intrabar_tv` uses the TradingView broker-emulator path: the extreme nearer the open is visited first.
  - `intrabar_prob` sends the price to the favourable extreme first with probability d_adv/(d_fav+d_adv).
- `bt/robust_run.py` caches signals once, then runs the 13 exits for each variant. It pools with `analyze.pooled` and applies `analyze.apply_rule`, exactly as analyze.py does.
- **15m IS isolation.** The 15m frame is truncated at 2026-05-08 00:00 UTC before any indicator or exit is computed, so no bar of the sealed holdout is ever read.
  - The signal counts match the reproduction for 150 of 150 symbol×strategy pairs. This also shows the indicators are causal at the split.
  - The truncated `base` run reproduces the delivered pooled file: 0 pass, max PF 0.9283 against 0.928259. Max |ΔPF| is 0.00225 and 19 rows have a different trade count.
  - The original pipeline leaks a little. 19 "IS" trades enter on the first OOS bar (2026-05-08 00:00), because `run_backtest` bounds only the signal bar. 521 IS trades exit on OOS bars. The effect on the verdict is negligible.
- 5m uses the full window (ALL), as in the handoff. The V4.5 15m filter uses the 15m bars of the same period, which is the calendar period of the 15m holdout. So the 5m result does not test out of sample what the 15m holdout would.

Variants (all fields not listed are CostCfg defaults: taker 0.05%, slip 0.02%, funding 0.01%/8h):

| variant | fees | slippage | funding | re-entry | intrabar |
|---|---|---|---|---|---|
| base | 0.05/0.05 | 0.02% | 0.01%/8h | engine (<=) | pess (engine.py) |
| zero | 0 | 0 | 0 | <= | pess |
| real | taker 0.045, TP maker 0.018 | 0.005% BTC/ETH, 0.01% others | 0.01%/8h | <= | pess |
| reent / zero_reent / real_reent | as base/zero/real | | | fixed (<) | pess |
| zero_tpfirst | 0 | 0 | 0 | <= | FIXED: TP first |
| zero_peakcur | 0 | 0 | 0 | <= | trail/ladder: current-bar peak |
| opt | 0 | 0 | 0 | < | tp_first + current-bar peak |
| real_opt | real | real | real | < | tp_first + current-bar peak |
| tv / zero_tv / real_tv | base / 0 / real | | | <= / <= / < | TradingView path |

The implied all-in cost per trade is the zero-cost expectancy minus the costed expectancy, averaged over combos:
- base: 0.1385% (15m) and 0.1366% (5m). This matches the handoff's 0.14%.
- real: 0.1001% (15m) and 0.0959% (5m).
- In the real variant the mean fee is 0.0832%. Funding is about 0.003% per trade, which is negligible.

## 1. Summary table: 15m IS, 5 symbols, 364 combos

| variant | PASS | PASS non-ladder | #PF>=1 | max PF | max PF non-ladder | median exp_net % | mean PF fixed / trail / ladder |
|---|---|---|---|---|---|---|---|
| base | 0 | 0 | 0 | 0.928 | 0.928 | -0.163 | 0.698 / 0.598 / 0.358 |
| **zero** | **2** | 1 | 67 | 1.254 | 1.206 | -0.024 | 0.954 / 0.891 / 0.898 |
| **real** | **0** | 0 | 0 | 0.991 | 0.991 | -0.125 | 0.767 / 0.654 / 0.448 |
| reent | 0 | 0 | 0 | 0.908 | 0.908 | -0.162 | 0.698 / 0.597 / 0.358 |
| zero_reent | 1 | 0 | 63 | 1.239 | 1.185 | -0.024 | |
| real_reent | 0 | 0 | 0 | 0.970 | 0.970 | -0.125 | |
| zero_tpfirst | 2 | 1 | 81 | 1.254 | 1.221 | -0.019 | 0.968 / 0.891 / 0.898 |
| zero_peakcur | 57 | 1 | 112 | 4.295 | 1.206 | -0.022 | 0.954 / 0.628 / 2.195 |
| opt | 56 | 0 | 123 | 4.202 | 1.219 | -0.015 | 0.968 / 0.628 / 2.199 |
| real_opt | 26 | 0 | 52 | 2.508 | 0.971 | -0.112 | 0.779 / 0.442 / 1.262 |
| tv | 3 | 0 | 6 | 1.450 | 0.928 | -0.152 | 0.701 / 0.631 / 0.834 |
| zero_tv | 57 | 1 | 125 | 2.752 | 1.206 | -0.015 | 0.959 / 0.940 / 1.830 |
| real_tv | 7 | 0 | 24 | 1.662 | 0.970 | -0.114 | 0.771 / 0.689 / 1.030 |

## 2. Summary table: 5m V4.5, BTC/ETH/SOL, 39 combos (the rule needs 3 of 3 symbols positive)

| variant | PASS | #PF>=1 | max PF | max PF non-ladder | median exp_net % | mean PF fixed / trail / ladder |
|---|---|---|---|---|---|---|
| base | 0 | 0 | 0.799 | 0.799 | -0.133 | 0.636 / 0.463 / 0.224 |
| **zero** | **0** | 24 | 1.147 | 1.147 | +0.007 | 1.063 / 0.907 / 0.878 |
| **real** | **0** | 0 | 0.899 | 0.899 | -0.088 | 0.750 / 0.542 / 0.332 |
| reent / real_reent | 0 / 0 | 0 | 0.789 / 0.892 | | | |
| opt | 6 (all L50) | 28 | 1.415 | 1.141 | +0.021 | 1.064 / 0.701 / 1.333 |
| zero_tv | 4 (all L50) | 30 | 1.404 | 1.147 | +0.019 | 1.063 / 0.902 / 1.313 |
| real_tv / real_opt / tv | 0 | 0 | 0.892 / 0.892 / 0.799 | | | |

## 3. (a) ZERO cost: top 10 by PF

15m IS:

| strategy | exit | trades | PF | exp_net % | symbols_pos | months_pos/10 | pass |
|---|---|---|---|---|---|---|---|
| N08_ICHI_WR | L50_sl20 | 238 | 1.254 | +0.037 | 4 | 8 | Y |
| N08_ICHI_WR | F_sl1.5_tp1.5 | 231 | 1.206 | +0.066 | 5 | 6 | Y |
| N03_ADX_GC | F_sl1.0_tp1.5 | 161 | 1.147 | +0.046 | 2 | 7 | |
| N03_ADX_GC | F_sl1.5_tp1.5 | 161 | 1.140 | +0.054 | 3 | 6 | |
| S6_EMA_DMI_ADX | F_sl2.0_tp3.0 | 835 | 1.137 | +0.088 | 4 | 6 | |
| S6_EMA_DMI_ADX | F_sl1.5_tp3.0 | 862 | 1.135 | +0.073 | 3 | 6 | |
| N03_ADX_GC | F_sl2.0_tp1.5 | 161 | 1.126 | +0.055 | 3 | 6 | |
| N08_ICHI_WR | F_sl2.0_tp1.5 | 229 | 1.118 | +0.045 | 3 | 6 | |
| S5_DONCHIAN_MFI | L50_sl15 | 317 | 1.104 | +0.018 | 3 | 6 | |
| N12_ICHI_AO | F_sl2.0_tp2.0 | 1422 | 1.085 | +0.041 | 3 | 5 | |

5m (top 5): the best is V45_ANY F_sl2.0_tp1.5 (2474 trades, PF 1.147, +0.035%, 3/3 symbols, 4/5 months). Next are V45_EXACT_AMB_G1 F_sl2.0_tp1.5 at 1.138 (2/3 symbols), V45_EXACT_AMB F_sl2.0_tp3.0 at 1.137 (692 trades, +0.048%, 3/3, 3/5 months), EXACT_AMB_G1 F_sl2.0_tp3.0 at 1.136, and EXACT_AMB F_sl2.0_tp1.5 at 1.135. No 5m combo passes even at zero cost.

**Cost margin** (`results/margin_15m.csv`). A flat per-trade cost c is subtracted from every zero-cost trade, and bisection finds the largest c at which the combo still passes the rule:
- N08_ICHI_WR L50_sl20 passes only while c <= 0.0072%.
- N08_ICHI_WR F_sl1.5_tp1.5 passes only while c <= 0.0018%.
- Every other combo fails even at c = 0.
- Pass counts are 2 at c=0 and 0 at c=0.05%, 0.10% and 0.14%.
- The cheapest realistic all-in cost is 0.081–0.128% (real variant). The survivors therefore need about 10–40x lower costs than exist.
- 5m: 0 pass even at c=0. The best needs a rebate of 0.012%.

## 4. (b) Realistic-best cost: top 10

15m:
- S6_EMA_DMI_ADX F_sl2.0_tp3.0: 835 trades, PF 0.991, -0.006%, 2/5 symbols, 5/10 months.
- S6 F_sl1.5_tp3.0: 0.965.
- N03 F_sl2.0_tp1.5: 0.946 (161 trades, 1/5 symbols).
- N03 F_sl1.5_tp1.5: 0.933.
- S6 F_sl2.0_tp2.0: 0.925.
- S5 F_sl2.0_tp2.0: 0.922.
- N08 F_sl1.5_tp1.5: 0.918.
- N08 F_sl2.0_tp3.0: 0.915.
- N12 F_sl2.0_tp2.0: 0.898.
- S6 F_sl1.5_tp2.0: 0.898.
- No combo reaches PF 1. The best is 0.21 PF short of 1.2 and has only 2 of 5 symbols positive.

5m:
- V45_EXACT_AMB F_sl2.0_tp3.0: 694 trades, PF 0.899, -0.042%, 1/3 symbols, 1/5 months.
- The G1 version: 0.897.
- EXACT_AMB F_sl1.5_tp3.0: 0.846.
- EXACT_AMB_G1 F_sl2.0_tp2.0: 0.843.
- V45_ANY F_sl2.0_tp3.0: 0.838.
- 0 of 39 pass.

## 5. (c) Re-entry fix (`i < next_free`)

- 15m: trades rise from 900,315 to 948,099 (+5.3%). Pass stays at 0. Max PF moves 0.928 → 0.908 (base) and 0.991 → 0.970 (real). Median ΔPF is 0.0000. 157 of 364 combos improve.
- 5m: trades +2.7%. Pass stays at 0. Max PF 0.799 → 0.789.
- The bug slightly *helps* the reported results, because skipping signals on the exit bar removes some whipsaw re-entries. It is immaterial to the verdict.

## 6. (d) Long-only vs short-only, from the reproduction file trades_IS_15m_all5.csv (900,334 trades)

- Long-only subset: 0 of 364 pass. 1 combo has PF >= 1 (N03_ADX_GC F_sl2.0_tp1.5 long: 83 trades, PF 1.145). 11 combos have exp_gross > 0.
- Short-only subset: 0 of 364 pass. 2 combos have PF >= 1 (S5 F_sl2.0_tp2.0 short PF 1.037; N03 F_sl1.5_tp3.0 short PF 1.010). 45 combos have exp_gross > 0.
- Across all trades:
  - Long: mean net -0.171%, gross -0.068%, win rate 35.9%.
  - Short: mean net -0.163%, gross -0.060%, win rate 36.2%.
  - Short beats long in 228 of 364 combos. Median PF is 0.627 for long and 0.687 for short.
- Market over the IS window (bar 1000 → last IS bar):

  | symbol | start | end | change | drift per bar |
  |---|---|---|---|---|
  | BTC | 117,639 | 80,005 | -32.0% | -0.15 bp |
  | ETH | | | -48.6% | -0.27 bp |
  | SOL | | | -53.9% | -0.31 bp |
  | LTC | | | -53.7% | -0.31 bp |
  | BCH | | | -23.1% | -0.11 bp |

  Over the mean hold of about 10 bars, this drift is worth only 0.01–0.03% per trade. The observed short advantage (0.008% gross) is consistent with that. **There is no directional story. Both sides lose before fees.**
- Zero-cost engine re-run: long -0.033% and short -0.023% per trade.
- 5m (May–Sep 2026, market up: BTC +6.0%, ETH +19.7%, SOL +34.6%), zero cost:
  - Long +0.042% and short -0.037%. On V45_EXACT_AMB FIXED exits: long +0.085%, short -0.040%.
  - The 64-bar forward return, however, is positive for both sides. EXACT_AMB shorts return +0.065%, +0.120% and +0.069% at h=64, so the V4.5 drift is not just long beta.

## 7. (e) Pre-cost expectancy over all 364 combos

True pre-cost expectancy (fee, slippage and funding all 0), in % per trade:

| min | 5% | 25% | 50% | 75% | 95% | max |
|---|---|---|---|---|---|---|
| -0.108 | -0.068 | -0.041 | -0.024 | -0.007 | +0.025 | **+0.088** |

The max is S6_EMA_DMI_ADX F_sl2.0_tp3.0.

- Combos above 0: 67. Above 0.05%: 5. Above 0.10%: **0**. Above 0.14%: **0**.
- The handoff's "비용 전 기대값" is `exp_gross_pct` (engine.py:199). That number still includes 0.02% slippage per market fill, which is about 0.03–0.04% per trade.
  - Its best-exit range is -0.115..+0.055. The true pre-cost range is -0.025..+0.088.
  - The mislabel makes pre-cost look about 0.03% worse. It does not change anything, because no combo clears even the realistic 0.10%.
- Mean pre-cost by exit, best to worst:
  - F_sl2.0_tp1.5 -0.0015
  - F_sl2.0_tp2.0 -0.010
  - F_sl1.5_tp1.5 -0.011
  - L50_sl20 -0.015
  - L50_sl15 -0.019
  - …
  - T_sl1.5_tr1.5 -0.039
  - T_sl1.5_tr2.5 -0.040
  - At zero cost the 50x ladder sits in the middle of the pack. Its last-place rank under base costs comes from costs, because its holds are short and its outcomes small.
- 5m pre-cost: max +0.048% (EXACT_AMB F_sl2.0_tp3.0). 24 of 39 combos are above 0. None is above 0.05%.

## 8. Signal-destroying null (random circular shift of each strategy's signal arrays per symbol)

`bt/null_run.py` keeps each strategy's signal count, clustering and long/short mix, but destroys the alignment with price. It was run with the same engine and cost variant as the real signals. Output is in `results/null_*.csv`. Comparison script: `bt/null_compare.py`, log `null_compare.log`.

| tf / variant | real PASS | null PASS per rep (mean) | real max PF | null max PF range | real vs null, mean exp of non-ladder combos |
|---|---|---|---|---|---|
| 15m zero (10 reps) | 2 | 0,2,9,6,1,14,1,2,8,16 (5.9) | 1.254 | 1.14–1.64 | -0.024 vs -0.014 (real WORSE) |
| 15m real (10) | 0 | 0,1,0,0,0,0,2,0,1,0 (0.4) | 0.991 | 0.94–1.49 | -0.123 vs -0.114 (real worse) |
| 15m tv (10) | 3 | all 0 | 1.450 | 0.93–1.18 | ladder: -0.035 vs -0.047 |
| 15m real_tv (10) | 7 | 0,2,1,2,1,0,1,1,0,0 (0.8) | 1.662 | 1.16–1.36 | ladder: +0.005 vs -0.008 |
| 5m zero (40) | 0 | all 0 | 1.147 | 0.98–1.19 | **+0.012 vs -0.020 (real better)** |
| 5m real (40) | 0 | all 0 | 0.899 | 0.71–0.90 | -0.082 vs -0.115 (real better) |
| 5m zero_tv (40) | 4 | mean 5.2 | 1.404 | 1.31–1.55 | ladder: +0.041 vs +0.043 (same) |
| 5m opt (40) | 6 | mean 5.5 | 1.415 | 1.32–1.56 | ladder: +0.043 vs +0.046 (same) |

What the null shows:

- **15m has no pre-cost edge at all.**
  - At zero cost the real signals are no better than time-shifted copies. They have 67 combos with PF >= 1 against a null mean of 98.9 (range 78–115).
  - Only 8 of 364 combos beat all 10 null reps. About 33 would do so by chance.
  - The two zero-cost "passes" sit at the null's 30th percentile.
- **5m V4.5 does have a small genuine pre-cost signal.** Real beats null by about +0.03% per trade on non-ladder exits, and 9–10 of 39 combos beat all 40 reps against about 1 expected by chance. That is roughly 1/3 of the realistic cost.
- **The pre-registered rule has a non-trivial false-positive rate at 364 combos.** Random-shift signals passed in 3 of 10 reps at realistic cost and in 9 of 10 reps at zero cost. A single future "pass" (for example in option A, 1h/4h) would not by itself be evidence of an edge. A null or a multiple-testing correction should be part of the rule.

## 9. The intrabar-path assumption and the 50x ladder: the only choice that flips passes

Every pass in opt, real_opt, tv, zero_tv, real_tv, zero_peakcur and the 5m opt/zero_tv runs is an L50 ladder exit. The one exception is N08 F_sl1.5_tp1.5, which already passes at zero cost. FIXED exits are insensitive: `zero_tpfirst` changes nothing, because ATR-scaled SL and TP are rarely both touched in one bar.

The ladder is sensitive because its levels are tiny compared with a 15m bar. The SL is 0.3/0.4% of price, the first trigger is +0.24%, and each lock sits only 0.02% below its trigger. A 15m bar has a median range of about 0.45–0.56%.

**Martingale calibration** (`bt/synth_calib.py`, logs `synth_calib_*.log`):
- The price path is a driftless geometric random walk with 180 or 600 ticks per 15m bar and a 15m sd of 0.35%. It is aggregated to OHLC.
- 2,500 random entries are made, at zero cost.
- The truth is computed on the tick path with point bars, where the engine is exact.
- By optional stopping, the true expectancy of any rule is 0.

L50 ladder, % per trade:

| setting | ladder | pess | tv | opt | prob | tick truth (± se) |
|---|---|---|---|---|---|---|
| SUB=600 | L50_sl15 | +0.007 | +0.101 | +0.097 | +0.097 | +0.001 ± 0.006 |
| SUB=600 | L50_sl20 | +0.012 | +0.118 | +0.102 | +0.113 | +0.009 ± 0.007 |
| SUB=180 | L50_sl15 | +0.012 | +0.093 | +0.084 | +0.089 | -0.006 ± 0.006 |
| SUB=180 | L50_sl20 | +0.009 | +0.100 | +0.086 | +0.100 | -0.007 ± 0.007 |
| SUB=180, sd x1.3 | L50_sl15 | +0.012 | +0.138 | +0.148 | +0.129 | -0.008 |
| SUB=180, sd x1.3 | L50_sl20 | +0.012 | +0.148 | +0.137 | +0.135 | -0.010 |

- Every intrabar model that raises the lock inside the bar manufactures +0.08 to +0.15% per trade from pure noise, and the bias grows with bar range. It assumes a monotone move to the bar extreme and misses the 0.02% micro-dips that trigger the tight locks earlier.
- The engine's pess choice updates stops only at bar close. That is a causal, implementable rule, with fills at real path prices, so it is unbiased on a martingale. It sits within +0.003..+0.018% of tick truth.
- FIXED exits are identical in all bar modes. TRAIL 1.5 under opt is actually worse (-0.11%). So opt is "favourable extreme first", not a universal upper bound.

**Why real signals beat the null under tv but not under pess** (`bt/tv_diag.py`, 6 strategies × 5 symbols, L50_sl20, 5 null shifts):
- Real-signal entry bars are about 30% larger: mean range 0.720% against 0.557% (median 0.565% against 0.450%). The signals fire after volatility expansions.
- Under tv, 63% of real ladder trades close inside the entry bar, against 50% for null trades.
- Real minus null mean net is +0.053% per trade under tv but only +0.006% under pess.
- The synthetic 1.3x-volatility run raises the tv bias by +0.045..+0.05%. That covers the whole tv "advantage".
- On 5m under opt and zero_tv, random shifts pass as often as the real signals (5.2–5.5 per rep against 4–6).
- **Conclusion: the tv/opt ladder passes are an artifact of the engine and of volatility selection. They are not an edge.**

What this does change in the handoff's story:
- Under pess, the ladder is a *bar-close-updated* ladder. The live bots update the ladder in real time, which is a different rule.
- The handoff reads the ladder's low win rate ("실제 40%, 본전 승률 75% 필요") and its last place among exits ("PF 0.34–0.38") as structural. In fact both are partly properties of the bar-close rule and of costs.
  - Under tv, the V4.5 G1 L50 win rate is 53–64% (the original report claimed 75%).
  - At zero cost under pess, the ladder is mid-pack (mean PF 0.898, against 0.954 for fixed exits).
- Pre-cost, the real-time ladder is still worth about 0 on a martingale. With about 0.10–0.14% of cost per 2–9-bar trade, it needs a signal edge that the null says the 15m set does not have and 5m V4.5 has only at about 0.03%.
- So "the ladder is closed" stands, but for the cost/zero-edge reason, not the "win rate 40%" reason. Option C (1m validation) is the only way to measure the real-time ladder directly.

## 10. The V4.5 64-bar forward drift, calibrated by the null

Method (`bt/fwd_side.py`, `fwd_all_null.log`): the same convention as forward.py (entry open[i+1], exit open[i+1+64]), compared with 500 random circular shifts.

| strategy | symbol | mean | naive t | null z | p |
|---|---|---|---|---|---|
| V45_EXACT_AMB | BTC | +0.090% | 2.79 | 1.43 | 0.068 |
| V45_EXACT_AMB | ETH | +0.142% | 2.94 | 1.36 | 0.074 |
| V45_EXACT_AMB | SOL | +0.178% | 3.05 | 1.72 | 0.038 |
| V45_ANY | BTC | | 5.53 | 1.62 | |
| V45_ANY | ETH | | 3.82 | 1.10 | |
| V45_ANY | SOL | | 6.89 | 2.36 | |

- The handoff's numbers (+0.09/+0.14/+0.18, t 2.8–3.1) reproduce exactly.
- The naive t overstates significance by about 2x, because 64-bar forward windows overlap and signals cluster.
- A Fisher combination gives p ≈ 0.009 for EXACT_AMB, but that treats the symbols as independent, which they are not (same calendar period).
- "Faint signal" is the right wording. Calling it t≈3 is not.

## 11. Verdict for this lens

"0 of 364 (15m) and 0 of 39 (5m) pass" is **robust to costs and to the re-entry bug**, and it holds under every intrabar model that does not use look-ahead.

- **Cost margin.** With zero fees, zero slippage and zero funding, 2 of 364 pass. Both sit inside the random-shift null (null mean 5.9 passes), and both die at a flat cost of 0.002–0.007% per trade. Realistic-best costs are about 0.10%. No combo has a pre-cost expectancy above 0.088% (15m) or 0.048% (5m).
- **Engine choices.**
  - The re-entry fix and TP-first ordering change nothing.
  - The one flip comes from optimistic or TradingView intrabar paths for the 50x ladder: 3–7 passes with costs, up to 57 without. The martingale calibration and the null show these are pure artifacts, worth about +0.1% per trade.
  - The handoff's pessimistic engine is the unbiased one here.
- **Outstanding.** Only a tick- or 1m-level test can price the *real-time* ladder. Given the martingale result and the absent 15m edge, it cannot plausibly turn positive after ~0.1% of costs.

## Files
- Code: `bt/engine2.py`, `bt/robust_run.py`, `bt/null_run.py`, `bt/null_compare.py`, `bt/gross_margin.py`, `bt/side_split.py`, `bt/synth_calib.py`, `bt/tv_diag.py`, `bt/fwd_side.py`, `bt/tables.py`.
- Results: `results/pooled_{15m,5m}_<variant>.csv`, `results/trades_*.pkl`, `results/null_*.csv`, `results/margin_*.csv`, `results/synth_calib_*.csv`, `results/pooled_15m_repro_{long,short}only.csv`.
- Logs: `tables.log`, `null_compare.log`, `gross_margin_{15m,5m}.log`, `side_split.log`, `synth_calib_*.log`, `tv_diag.log`, `fwd_side.log`, `fwd_all_null.log`.
