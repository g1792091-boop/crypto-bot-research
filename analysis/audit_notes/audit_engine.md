# Engine mechanics audit — bt/engine.py (+ run.py / analyze.py / portfolio.py / forward.py)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/audit_engine`
Nothing under `/home/user/crypto-bot-research` was modified. The original code was copied to `./bt` and left unmodified.

## Files produced
| file | purpose |
|---|---|
| `test_engine_audit.py` / `.log` | 17 synthetic-bar unit tests, one per mechanic/bug claimed |
| `cache_signals.py`, `cache/*.npz` | signals computed exactly as run.py does (same fns, same both->long rule) |
| `engine_v.py` | variant of `_simulate_one`/`run_backtest` with switchable fixes; flags off == original (verified to 1e-11) |
| `run_variants.py`, `out/pooled_{15m,5m}_<variant>.csv`, `out/trades_*.pkl` | full-grid reruns per variant + analyze.pooled/apply_rule |
| `martingale_fine.py`, `mfine_*.log`, `out/martingale_fine_*.csv` | 1-second Brownian martingale calibration of intrabar bias |
| `martingale_test.py`, `martingale.log`, `dbg_mart.py` | first (coarse, 1-min linear path) martingale attempt — flawed by construction, see §7 |
| `intrabar_5m.py`, `intrabar_5m.log`, `out/intrabar_5m*.{pkl,csv}` | real-data check: 15m-engine entries re-simulated on 5m sub-bars |
| `results/*synth*` , `synth_run.log` | handoff's `run.py --synthetic` random-walk check |
| `out/per_symbol_eq_maefix_15m.csv`, `out/pooled_vs_single_account_15m.csv` | leverage/portfolio re-computations |

## 0. Reproduction of the variant engine
`engine_v` with no flags vs the orchestrator's reproduction (`repro/results/pooled_IS_15m_all5.csv`, `pooled_ALL_5m_v45g1.csv`):
364 x 40 and 52 x 40 tables, max abs diff 3.4e-11 / 1.1e-11 (float summation order), `pass` column identical.
So every delta below is caused only by the flag being tested.

## 1. Mechanics verified correct (with evidence)
* **Entry timing**: signal bar i, entry at `o[i+1]*(1+side*slip)` (engine.py:63-64, 156). Test `t_entry_timing`: signal bar 2 -> entry_idx 3, px 101.0202 = 101*1.0002.
* **Entry-bar intrabar use**: bar e's full high/low is used after entering at its open (engine.py:66, 76). This is correct because the whole bar range happens after the open. The only open issue is ordering *within* a bar (see §3).
* **SL gap-through**: `fill=min(open, sl_px)` then minus slippage (engine.py:88-89). Test: open 97 below SL 99.02 -> exit 96.9806 = 97*(1-0.0002). Real data: 658 of 479,306 SL exits (0.14%) filled at a worse open; mean extra loss 0.147%.
* **TP limit fill**: `fill=max(open,tp_px)`, no slippage (engine.py:92-93). This is correct for a resting limit.
* **TRAIL/LADDER stop is set from the peak up to the previous bar** (engine.py:97-106). Test `t_trail_prev_peak`: bar-1 high 105 -> stop 103.5 active from bar 2, exit 103.4793. This is a legitimate, non-anticipating "stop updated at every bar close" rule (§3 shows it is unbiased on a martingale).
* **ladder_lock** (engine.py:48-58) matches the documented rule exactly: peak ROE 11.9 -> none; 12 -> 11; 15.9 -> 11; 16 -> 15; 21 -> 20; 25.9 -> 20; 26 -> 25; 31 -> 30; 36 -> 35; 41.5 -> 40. So "every +5 lock = trigger-1" means triggers at 26, 31, 36 ... with locks 25, 30, 35 ..., and that is what the code does. The short side mirrors correctly (test `t_ladder_short_mirror`: short peak 16.5% ROE -> LOCK exit at 14.00% gross ROE = 15 - 1 ROE point of slippage).
* **Lock vs SL labels**: for LADDER, `lock_px` is always on the profit side of entry, so it can never equal `sl_px`. The 'SL' vs 'LOCK' labels are therefore exact. (TRAIL labels have float noise, see §4.)
* **TIME/EOD**: `last=min(n-1, e+max_hold-1)`. TIME is used when max_hold is reached and EOD at the data end (test `t_time_eod`). In the IS run there are 68 TIME exits and 0 EOD.
* **Short side**: entry `o*(1-slip)`, stop `max(open, st)*(1+slip)`, MAE/MFE signs are all correct (engine.py:64, 113-114, 124-125).
* **leverage_layer arithmetic** (engine.py:169-183): `growth = 1 + 0.4*max(-1, L*net)`, liquidation => -1. Test: 1.2*0.92*0.6 = 0.6624. At L50, notional = 0.4*50 = 20x equity. That matches the user's "seed 30-40% as margin at 50x" at the 40% end. It models **isolated** margin (loss capped at the margin). With 0.3-1.1% stops, cross margin would give the same results because cross liquidation (~5% adverse) is never reached.
* **summarize**: PF = sum(net>0)/|sum(net<=0)| on equal-notional per-trade price returns, payoff = avg_win/|avg_loss|. This is standard and consistent with the pass rule (analyze.py:38-43).
* **Handoff numbers re-derived from the pooled table**: S6 F_sl2.0_tp3.0 PF 0.928, 835 trades, -0.052%/trade. Exit-mode mean PF: 0.773 (F2/3), 0.539 (T1.5), 0.381 (L50 sl20), 0.335 (L50 sl15). Ladder avg hold 2.6/3.2 bars, -0.16%/trade. 5m V45_EXACT_AMB_G1 L50_sl15: PF 0.199, 1,112 trades, 39.6% WR. All match.

## 2. Bugs / deviations found, each quantified (15m IS grid 364 combos; 5m V4.5 39 combos)
| id | issue | where | unit test | real-data size | bias | verdict change? |
|---|---|---|---|---|---|---|
| B1 | re-entry: `if i <= next_free` skips a signal on the exit bar; the comment says it is allowed | engine.py:149 vs :159 | `t_reentry_on_exit_bar` | full-grid rerun with `<`: +47,789 trades (+5.3%; +8% for ladders; N17 +24.5%). Mean dPF -0.0004 (range -0.037..+0.037), best PF 0.928 -> 0.908, PASS 0. 5m: +1,751 trades, best 0.799 -> 0.789, PASS 0 | neutral/slightly better (fix lowers the best PF) | no |
| B2 | fee on TP (limit) exits charged 2x taker (0.10%) instead of taker+maker (0.07%) | engine.py:127 | `t_fee_tp` | 222,328 TP exits = 38.3% of FIXED trades; 0.03% per TP = 0.0115% per FIXED trade on average. Mean dPF +0.0156 (max +0.040), best PF 0.928 -> 0.946, PASS 0. 5m best 0.799 -> 0.828 | worse than reality | no |
| B3 | if a bar OPENS beyond TP and later touches SL, SL priority books a loss although the TP limit filled at the open | engine.py:86 | `t_gap_beyond_tp_then_sl` | **0 trades changed** on 15m and 5m (the case never occurs in this data) | worse | no |
| B4 | MAE used for liquidation includes the exit bar's extreme *after* the stop filled -> spurious liquidations | engine.py:122-125, 176 | `t_mae_exit_bar_liq` (growth 0.600 vs correct 0.916) | L50 liquidation flags 65,827 -> 23,409 (42,418 = 64.4% spurious); L20 1,526 -> 382; L10 278 -> 99; L5 37 -> 0; ladder exits 1,061/1,191 -> 0. Per-symbol eq_L50 median 2e-12 -> 2.5e-10, max 1.53 -> 1.71 (SOL N03, 41 trades); single-account L50 max 0.0079 -> 0.0146 | worse (only eq_L*, not PF/pass) | no ("50x -> equity ~0" still holds) |
| B5 | analyze.pooled compounds all symbols' trades sequentially by entry_ts as one 40%-margin ledger, although trades overlap in time | analyze.py:22-23 -> engine.py:212-216 | — | median 50.1% (max 91.2%) of pooled trades enter while another symbol's trade is still open. Proper single-account (portfolio.single_account) L50 max 0.0079, L10 max 0.603; pooled eq_L10 >1: 0; single-account L10 >1: 0 | unclear (meaningless number) | no |
| B6 | portfolio.single_account allows an entry at `entry_ts == busy_until` (exit_ts is the exit bar's OPEN time, and the exit happens inside that bar) -> up to 1 bar of overlap | portfolio.py:22 | `t_portfolio_overlap` | Sep-5..13 V45 G1 L50_sl15: 2 of ~50 taken trades; strict version 1000 -> 175.7 vs 147.4 | unclear | no |
| B7 | TP "touch = fill" (a limit order at the exact high may not fill) | engine.py:82 | — | 4.4% of TP exits overshoot TP by < 1 bp, 19.6% by < 5 bp. Requiring a 1 bp trade-through: FIXED mean dPF -0.0072 (min -0.061), best 0.926, PASS 0 | better | no |
| B8 | TRAIL label uses an absolute price tolerance of 1e-12; with trail==sl on bar 0 (T_sl1.5_tr1.5), float noise labels SL exits as TRAIL | engine.py:115 | `t_trail_label_float` (200/2000 mislabelled) | 65 of 3,187 entry-bar stop-outs (2.0%) mislabelled; PnL identical | none (label only) | no |
| B9 | funding by bar count, so trades spanning data gaps are under-charged; funding charged to both sides | engine.py:128 | `t_funding_gap` | 564 trades (0.063%) span a gap, mean undercharge 0.011% (max 0.030%); mean funding per trade 0.0032% | tiny | no |
| B10 | IS trades may exit after the split, using OOS bars | run.py:86 / engine.py:65 | — | 521 of 900,334 (0.06%); last exit 2026-05-10 16:30 | tiny | no |
| B11 | a liquidated trade loses exactly the margin; the entry fee (1% of equity at 20x notional) is ignored, and the liquidation distance ignores fees | engine.py:173-178 | — | at most 1 pp of equity per liquidation, and the liquidation distance shifts by <= 0.05% price | better (tiny) | no |
| B12 | ladder_lock float boundary: a peak exactly at +12% ROE computes as 11.999999999999789 -> no lock | engine.py:53 | `t_ladder_float_boundary` | needs an exact-tick touch; practically irrelevant | — | no |
| B13 | stale entries after data gaps (entry more than 1 bar after the signal) | run_backtest | — | 95 trades, all BCH, <= 45 min delay | tiny | no |
| B14 | same-bar SL/TP: SL priority (engine.py:86) | — | `t_same_bar_sl_tp` | 1,611 FIXED trades (0.28%) had TP also inside the SL exit bar; if all were TP-first the swing is +2,753 pct-pts vs total FIXED net -94,767 pct-pts (2.9%). Real 5m re-sim of the same entries: FIXED PF +0.001..+0.005 | worse (small) | no |

**All three "real" fixes combined (B1+B2+B3)**: 948,123 trades, PASS 0, best PF 0.925 (S6 F_sl2.0_tp3.0). 5m: PASS 0, best 0.818.

## 3. Intrabar ordering: the one assumption that *can* flip results, and what the evidence says
The engine assumes an adverse-first stop update: the TRAIL/LADDER stop comes from the previous bar's peak, and SL beats TP within a bar.
The opposite "favourable-first" assumption (`fav_first`: stop from the peak *including* the current bar; TP before SL) gives this:
* 15m IS: **PASS 11 (ff alone) / 12 (ff + fixes)**, best PF 2.19-2.22 (S5 L50_sl20, 322 trades). All passes are L50 ladder exits. Ladder mean PF 0.335/0.381 -> 1.024/1.058, mean exp_net -0.161 -> +0.002%.
* 5m V4.5: still PASS 0 (ladder mean PF 0.224 -> 0.446, max 0.50).

So the ladder verdict depends on intrabar modelling. The evidence shows that favourable-first is **not a valid bound**, while the engine's convention is sound:
1. **Martingale calibration** (`martingale_fine.py`; 1-second geometric-martingale path, 1,900 random entries, zero costs; bars at 15m/5m/1m/1s built from it; the true expectancy is 0):
   * sigma15 0.28% (ATR 0.44%): L50_sl15 gross per trade: 15m engine -0.0037%, 5m -0.0017%, 1m -0.0016%, **1s -0.0003% (se 0.0064)**, **15m favourable-first +0.0486%**. L50_sl20: -0.0075 / -0.0049 / -0.0046 / -0.0033 (se 0.0074) / ff +0.0481.
   * sigma15 0.40%: L50_sl15 15m +0.0034 vs 1s +0.0037 (se 0.0065), ff +0.1274; L50_sl20 15m +0.0056 vs 1s +0.0045, ff +0.1213.
   * FIXED exits are identical at all resolutions (SL and TP are >= 2.5 ATR apart and never both touched in one Gaussian bar). TRAIL differs by <= 0.003%, while ff for T_sl1.5_tr1.5 gives -0.106/-0.134 (ff is not even one-signed).
   * Interpretation: the engine's stop, fixed at bar open, is a non-anticipating rule, so its expectancy equals the tick-updated ladder's (both are 0 on a martingale). Favourable-first uses the bar's high to set a stop that the same bar's low then hits, which is anticipation and biases it by +0.05 to +0.13% per trade. What the bar engine *does* distort is the ladder's win rate: 47.6% (15m) vs 54.3% (1s) at sigma 0.28, and 42.5% vs 54.6% at sigma 0.40. So the handoff's "actual win rate 40%" diagnosis is resolution-dependent, but the expectancy is not.
2. **Real-data sub-bar check** (`intrabar_5m.py`): the same entries the 15m engine takes (all 28 15m strategies, BTC/ETH/SOL, 2026-05-14..09-29, where 5m data exists; this is post-split data, used only for the resolution delta and not for strategy selection) were re-simulated on 5m sub-bars:
   * L50_sl15 (n=27,948): exp_net -0.1703% (15m) -> -0.1658% (5m); PF 0.268 -> 0.238; ff 0.773.
   * L50_sl20 (n=26,556): -0.1636 -> -0.1587; PF 0.313 -> 0.280; ff 0.839.
   * FIXED: PF shift +0.001..+0.005, 99.9% same win/loss sign. TRAIL: -0.002..-0.003.
   * Combos with PF >= 1.2 and n >= 100: 0 (15m), 0 (5m), 0 (ff) of 377.
   * So on real data the finer resolution moves the ladder by +0.005%/trade in expectancy and **slightly lowers** its PF. That is nowhere near the +0.13% favourable-first uplift.
   * Side result: 15m bars vs 5m bars aggregated to 15m: BTC opens match exactly in only 98.75% of bars (max rel diff 0.18%; close max 0.69%). ETH/SOL match >= 99.9%. That is a data-consistency point for the data lens.
3. **Implication for the handoff's option C (1-minute re-validation)**: low expected value. Theory says bar-level and tick-level ladders have equal expectancy, and the real 15m->5m step moved nothing that matters.

## 4. Handoff random-walk sanity check (run.py --synthetic, window ALL, 1 symbol)
302,287 trades, 28 strategies x 13 exits: **exp_gross -0.0344% (se 0.0011), exp_net -0.1363%** (the handoff says -0.03% / -0.13%, confirmed). With slippage added back, gross = **+0.0003% (se 0.0011)**, so there is no look-ahead signature at pooled level. Per-exit gross ranges -0.020% (L50_sl15) to -0.047% (T2.5). Per-strategy gross ranges -0.128% (N08) to +0.049% (N03), which is noise on a single series.
Caveats: `synth()` (run.py:43-55) draws high/low as independent noise around the close, not as a real path, and all "symbols" use the same seed (7). The check detects signal look-ahead but cannot detect intrabar-ordering bias; §3 covers that.

## 5. Portfolio cross-check in the handoff ("Sep 5-13: 59 trades, 46%, 1000 -> 380")
No delivered script calls portfolio.py. With the delivered 5m trades (V45_EXACT_AMB_G1, L50_sl15) and `single_account(lev=50)`:
* UTC [09-04, 09-13): 59 trades, 45.8% WR, **1000 -> 205.8** (count and WR match the handoff; the equity does not)
* UTC [09-05, 09-14): 62 trades, 41.9%, 1000 -> 147.4; [09-05, 09-13): 56, 44.6%, 208.8
* 380 is only approached with a 0.02%/side fee (372.2), or with L50_sl20 in KST [09-04, 09-13) (54 trades, 378.8)
=> the 380 figure is not reproducible from the delivered code. The reproducible value is worse. Either way it is a loss, so no conclusion changes.

## 6. Forward-drift ("only faint signal") check (forward.py:32)
forward.py computes t-stats as if the 64-bar windows were independent, but 65-70% of V4.5 AM+B signals come < 64 bars after the previous one.
* V45_EXACT_AMB 5m: naive t 2.79/2.91/3.05 (BTC/ETH/SOL) -> **cluster-robust t 1.63/1.76/1.88**; thinned to non-overlapping (n=209/202/215): t 1.63/1.80/1.95. The mean drift is unchanged (0.09/0.14/0.18%).
* The delivered forward_ALL_5m_v45.csv reproduces exactly with forward_stats (max diff 4e-16), but no delivered script writes it.
* 15m strategies with comparable market-drift-adjusted 64-bar (16h) excess and overlap-robust t: N09 +0.116% (cluster t 2.24, 5/5 symbols positive), S6 +0.130% (t 2.08), N17 +0.125% (naive t 5.35 -> cluster t 1.60). => the claim that "V4.5 AM+B is the *only* faint signal" is not supported. Several candidates are equally faint, and none survives multiple-testing scrutiny (28+ strategies x 6 horizons).

## 7. Things I got wrong along the way (for transparency)
* My first martingale test (`martingale_test.py`) built 15m bars from 1-minute points with linear interpolation. The ladder then showed +0.057% gross (9 se) even on the "1m path". The cause: a piecewise-linear path is not a martingale at the ladder's 0.02% (1 ROE point) lock-trigger spacing, so fills "at the level" profit from within-step drift. I replaced it with the 1-second version (§3). The coarse test's ladder numbers should not be used.
* Favourable-first (`ff`) is not an upper bound (it is not one-signed for TRAIL). It is an anticipating alternative, useful only to show how sensitive the results are.

## 8. Not covered / out of lens
* There is no signal-based exit or reversal mode in the 13-exit grid, although several strategies (SuperTrend/PSAR flips) are designed as always-in reversal systems. The exit-independent forward table (§6) is the only coverage: 16h drift <= 0.13% excess with t <= 2.2, below the 0.14% round-trip cost.
* The "net ROE" ladder variant from the old V3.9 project (triggers shifted by the fee ROE) is not modelled; only the gross-ROE ladder is.
* 0.02% slippage on stop-market fills during crashes (e.g. LTC 2025-10-10 21:15: 37 trades exited on that bar; ETH 2025-12-13 23:15 bad print: 105 trades exited on that bar, 63 of them SL) is probably optimistic for real crash fills and pessimistic for bad prints. This is data lens.
* V39_15M_G1 in the 5m run is the 15m strategy function applied to 5m bars (run.py:134-135); it is excluded from the 0/39 count.
