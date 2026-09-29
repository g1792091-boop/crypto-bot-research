# Adversarial verification of the "pine" audit (V3.9 / OBV / V4.5 port)

Scratch: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/verify_pine`
(`bt/` = copy of project bt/, plus my `bt/strategies_mtf.py`; `data` -> project data symlink; outputs in `results/`).
Nothing under `/home/user/crypto-bot-research` was modified (`git status --short` empty). No Astral tools used.
Max 2 concurrent python processes.

## What I re-derived independently (not re-using the auditor's code)

| script | what | result |
|---|---|---|
| `ref.py` | my own bar-by-bar Pine emulations (ta.sma/ema/rma/atr/rsi/stoch/dmi(fixnan, tr(false))/crossover/obv(ta.cum), Kivanc ST, TV ta.supertrend, shayankm STC, TV Chop Zone w/ half-up round, Stoch RSI, AO/AC) | reference only |
| `v1_primitives.py` → `results/v1_primitives.csv` | port vs ref on BTC 15m, ETH 5m, BCH 15m, SOL 5m | EMA/ATR/RSI/MACD/Stoch/StochRSI/AC: <=3e-13 abs on ALL bars; +DI/-DI/ADX: 0 diff after warm-up (port starts 1 bar earlier: bar-0 DM/TR handling); OBV identical incl. bar0=0 (Pine ta.cum); STC = shayankm (<=2e-11); Chop angle 0 mismatches; ST 10x3/10x6/14x3/14x6 = Kivanc 0 mismatches; vs TV ta.supertrend 0/0/1/48 bars (max 0.123% SOL 5m 14x3). EMA with docs-style src seed differs only in warm-up (STC up to 100 pts early, 0 after 1000 bars). BCH AO: 1 sign flip at a ~0 value (4.5e-13 float noise). |
| `v2_truncation.py` → `results/v2_truncation_*.csv` | look-ahead truncation, own seed (2026) and sampling (signal bars, random, right after data gaps, 3 positions inside a 15m bar); whole prefix compared | 15m: 115 points (65 on signal bars), 638,915 True values, **0 mismatches** (V39 STC off/on all subs, V39 G1, OBV_S(+G1), OBV_B). 5m V4.5 (all components, exact AM+B, +G1): 127 points (81 on signals), two 15m cuts: "15m close <= 5m close" and the stricter "15m close <= 5m OPEN": **0 mismatches** both. |
| `v3_mapping.py` → `results/v3_mapping.txt` | port mapping vs strict Pine HTF-index emulation (current HTF bar = last 15m bar with open <= T; value = previous HTF bar) + label check | SOL 0 diffs; BTC 6, ETH 9 of 40,000 5m bars differ, all inside 15m periods that exist in the 5m file but are missing from the 15m file (BTC 2, ETH 3 periods). There the port uses the latest COMPLETED 15m bar (lag 15-25 min), the strict emulation one bar older. Elsewhere lag = 15/20/25 min exactly = Pine f()[1]+lookahead_on, never one bar more delayed. 0 V4.5 signals on the differing bars. Labels: 5m resampled with open labels equals the 15m file on 98.5-100% (close), +/-5 min shift 0.1-4%. |
| `v4_forward.py` → `results/v4_forward.log` | V4.5 drift | reproduces BTC 563/+0.0902%/t2.79, ETH 550/+0.1403%/t2.91, SOL 528/+0.1781%/t3.05; pooled 1,641 +0.1353% naive t 4.98. TIMELY +0.1405%, LEAK +0.1422%, TV-ST identical (0 change). **Cluster-robust day-clustered t = 2.30** (UTC or KST days; CR0/CR1); the auditor's 2.60 = t over 135 daily means (different estimator). **Not AM+B-specific**: V45_ANY +0.110% (n 9,068, clustered t 2.56), AMIX-only +0.122%, C-only +0.133%; baseline "side = confirmed-15m ST14/6 dir on every 5m bar" +0.037% (clustered t 0.89). AM+B long +0.187% vs short +0.085%; unconditional long 64-bar drift in the period +0.015/+0.039/+0.060% (BTC/ETH/SOL). Pre-16-bar signed return -0.46% (pullback entry). Raw AMB_G1 signals 2026-09-05..09-13 17:00: BTC 26, ETH 49, SOL 29. |
| `v5_modes.py` + `bt/strategies_mtf.py` → `results/v5_modes.log` | Pine modes never run in stage 1 (exit-free, 5m period, BTC/ETH/SOL) | V3.9 5m-chart mode (STC gate + confirmed-15m 4-trend filter inside the final-signal condition, time_close switch = last 15m close <= 5m close; patch sanity-checked: all-true mask == port): n 1,835, fwd4 +0.002%, fwd16 -0.010%, fwd64 +0.028% (per-symbol t64 0.3-0.8), pre64 +1.32%. OBV_S 5m: n 1,592, fwd4 -0.005%, fwd64 +0.059%. OBV_B 5m (breakMa 11): n 3,651, fwd64 +0.026%. All far below 0.10-0.14% round-trip cost. |
| `v6_v39_g1.py` → `results/v6_v39_g1.log` | V39 context; G1 on 3x15m (port) vs 3x5m (policy) | V39_15M IS: n 4,312, fwd16 -0.0347%, fwd64 -0.0710%, pre16 -0.009%, **pre64 +1.983%** (exact match to auditor). G1: V39 port blocks 25/403, 23/427, 33/439 vs 5m-G1 41/44/70; agree 91.6/91.8/88.4%. OBV_S 24/181, 24/197, 26/155 vs 17/26/27; agree 89.5/88.8/86.5%. |
| `v7_misc.py` → `results/v7_misc.log` | clustering variants, cross-file consistency, gaps | see above; BTC 15m file vs 5m-resampled close differ on 1.52% of bars (median 1.4 bp, max 69 bp), ETH/SOL 0.05-0.06%; signals within 50 bars after >60-min gap: V39 8/4,312, OBV_S 6/1,571, OBV_B 10/4,250. |
| pandas on delivered pooled files | distance to pass rule | best-exit gross exp V3.9/OBV all <= -0.0138%/trade (OBV_B PF 0.835 best); V45_EXACT_AMB SL2/TP3 PF 0.799, gross +0.0178%, net -0.0866%; pass 0/364 and 0/39. |

## Verdicts

- **PINE-1 (port never diffed vs TradingView)**: partially confirmed; downgrade to low for the stage-1 conclusion.
  True: no TV signal-export diff was done, and the earlier source report made it a gate. Also true: 56 vs 59 is not
  like-for-like (5-symbol shared account on Binance Mark data at 0.01% fee vs 3 symbols on Polygon spot at 0.05%).
  Win rates 75% vs 46% actually show trade-level disagreement.
  Over-stated: the port was written in the same chat that held the genuine Pine sources (handoff §2.3/§7;
  pine_indicators.py:3-4). It is the *audit* that rests on a prose summary, not the port. The auditor's
  "independent" V3.9 (t5_v39_variants.py) follows the port's statement order almost line for line, so its 0 mismatches
  show agreement with the auditor's reading of the report, not with Pine.
  Missed corroboration: the REAL Pine scripts running live in RC2 (7.72 d) lost money on all three: V3.9 -747.65
  (175), V4.5 -419.06 (363), OBV -1,547.14 (911), even at a 0.01% fee. So port infidelity cannot be hiding a
  profitable edge. Still do the TV export diff before any bot/PAPER work.
- **PINE-2 (G1 on 15m bars)**: confirmed, low. My numbers reproduce the auditor's to within window-boundary noise.
  The port blocks roughly half as many V3.9 signals as a 5m-bar G1 would. It cannot flip anything: G1 variants have
  negative gross expectancy at every exit.
- **PINE-3 (V3.9 5m-chart mode never ported)**: confirmed, low. Quantified with a reconstruction: +0.028% fwd64,
  -0.010% fwd16, entries after a +1.3% prior move. No edge. The OBV 5m-chart mode (part of candidate O) was also never
  run; the auditor missed it. Its drift is +0.026 to +0.059%, which cannot flip anything.
- **PINE-4 (V4.5 drift significance)**: partially confirmed. Real and look-ahead-free (TIMELY, LEAK and TV-ST all
  about the same). Significance is overstated, even more than the auditor says: the cluster-robust t is 2.30, not
  2.60. Contrary to the "best of ~198 cells" framing, it is not a lone lucky cell and it is not specific to AM+B: every
  V4.5 path shows +0.11 to +0.13%, including C, which AM+B excludes. It is a family-level "5m pullback inside the
  confirmed-15m SuperTrend direction" effect and is long-heavy. The handoff's wording "the only faint signal is V4.5
  *exact AM+B*" should become "V4.5-family pullback entries". Magnitude is about one round-trip cost; the headline
  holds.
- **PINE-5 (edge cases, cosmetic)**: confirmed, info. 0 occurrences in my tests.
- **PINE-6 (spot vs perp feed)**: confirmed, info. The two Polygon files also disagree with each other (BTC 15m vs
  5m-resampled close differs on 1.52% of bars; max 69 bp), whereas TradingView derives both timeframes from one feed.

## Items in the auditor's confirmed-OK list that are slightly off
- "Mapping 0 index mismatches including gaps": 6 (BTC) and 9 (ETH) bars differ from a strict HTF-index emulation
  where the 15m file lacks a bar. The port is causal there, and no signal falls on those bars. Immaterial.
- "Lag 15/20/25 min always": 3 BTC and 6 ETH bars have a 30-40 min lag, right after the missing 15m bars.
- "day-clustered t = 2.60": 2.60 is the t over 135 daily means. The cluster-robust day-clustered t is 2.30.

## Bottom line
Nothing in this lens changes "0/364 and 0/39 pass". No look-ahead (independently re-tested, including a stricter
15m cut). Primitives match Pine semantics to float precision against my own emulations. The V3.9 negative drift and
late-entry pattern reproduce exactly. The untested Pine modes (V3.9 5m, OBV 5m) show sub-cost drift. Only one thing
needs rewording: the "faint signal" is a V4.5-family effect with cluster-robust t of about 2.3 over one 4.5-month
period, not an AM+B-specific edge.
