# Pine v6 port audit — V3.9 / OBV / V4.5 (stage-1 backtest)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/audit_pine`
(`bt/` = untouched copy of `/home/user/crypto-bot-research/bt`, `data` -> symlink to project data, `results/` = my outputs,
`venv/` = scratch venv with TA-Lib 0.8.1 for reference values; system python3 / pandas 2.3.3 used for everything that
touches the strategy code, exactly as the orchestrator's reproduction.)

Nothing under `/home/user/crypto-bot-research` was modified. No Astral tools were used.

## 0. Sources of truth (the Pine files are not in the package)

1. **TradingView Pine v6 built-in semantics.** Numeric reference = TA-Lib (Wilder RMA and SMA-seeded EMA, identical to
   `ta.rma`/`ta.ema`/`ta.rsi`/`ta.atr`/`ta.dmi` after seeding), plus independent line-by-line re-implementations of the
   public Pine sources: KivancOzbilgic "SuperTrend", TradingView `ta.supertrend` (docs `pine_supertrend`),
   shayankm "STC Indicator – A Better MACD [SHK]" (v4, `var`/`nz` semantics), TradingView built-in "Chop Zone"
   (with Pine `math.round` = round-half-up).
2. **The earlier source-derived report** that the previous Claude session wrote *while it had the Pine files*
   (handoff §2.3, artifact `https://claude.ai/artifact/BTbPemKPBxQjiZEvX2htiX`; read read-only through the Claude Docs
   connector; plain-text copy: `prev_v45_report.txt`, raw XML: `prev_v45_report.xml`; 18,452 chars, read 100 %).
   It quotes the Pine conditions (with line numbers for V3.9: 155-159, 350-351, 441-444, 602) and two verbatim OBV code
   blocks. It is a *summary*, so it is a secondary source; details it omits cannot be verified here.

## 1. Tests run and exact results

### T1 primitives vs TA-Lib (`t1_primitives.py`, `results/t1_primitives.txt`)
BTC/ETH/BCH 15m, SOL 5m, all 40,000 bars:
- `pine_ema` 12/26/34/50: first finite index = TA-Lib's (length-1, SMA seed, i.e. Pine `ta.ema`), max rel diff vs TA-Lib
  on ALL bars <= 2.3e-15; vs pandas `ewm(adjust=False)` = 0 after 1,000 bars.
- `pine_rma(tr)` 10/14/20 vs Wilder ewm and vs `talib.ATR`: <= 2e-15 rel after warm-up.
- `pine_rsi(14)` vs `talib.RSI`: max abs 7e-14 on ALL bars.
- MACD hist 12/26/9: <= 5e-11 abs. DMI/ADX 14/16/20: +DI, -DI, ADX <= 1.1e-13 abs.
- Stoch 14/4/2 K and D vs `talib.STOCH` (SMA): <= 2.2e-12. AO/AC vs SMA reference: <= 1.7e-9 (BTC price scale).
- OBV vs `talib.OBV`: constant offset = volume[0] (TA-Lib seeds with vol[0], port with 0) -> irrelevant for
  OBV-vs-SMA comparisons and crosses (translation invariant). 0 NaN and 0 zero volumes in all files.

### T2 composites vs independent Pine re-implementations (`t2_composites.py`, `results/t2_composites.csv`)
All 8 files, after 1,000-bar warm-up:
- `exchange_supertrend` direction vs KivancOzbilgic SuperTrend (flip vs previous bands `up1`/`dn1`, band ratchet on
  `close[1]`): **0 mismatches** for 10x3, 10x6, 14x3, 14x6 on every file.
- vs TradingView built-in `ta.supertrend` (flip vs current band): differs on 0.000–0.123 % of bars (worst SOL 5m 14x3:
  583 vs 581 flips). Immaterial.
- `stc` vs shayankm reference: max |diff| <= 3.6e-7 (STC is 0..100).
- `chop_angle` vs TV Chop Zone with Pine rounding: **0 mismatches**; exact .5 rounding ties (where `np.round` banker's
  rounding would differ from Pine) = 0.

### T3 look-ahead truncation test (`t3_truncation.py`, `results/t3_truncation_15m.csv`, `results/t3_truncation_5m.csv`)
For each generator: 200 t per symbol (100 uniform in [1000, n), 100 drawn from full-data signal bars). Signal
recomputed on data available at the close of bar t (V4.5: 5m frame `[:t+1]` AND 15m frame restricted to 15m bars whose
close <= the 5m bar's close). Compared at t and over the whole prefix s <= t (every sub-signal array).
see section 3.

### T4 15m->5m mapping (`t4_mapping.py`, `results/t4_mapping.txt`)
- Port mapping (strategies.py:603-605) vs a direct emulation of Pine `request.security(..,"15", f()[1],
  lookahead_on)` ("HTF bar containing the chart bar, then previous HTF bar"): **0 index mismatches** on all 40,000 5m
  bars for BTC, ETH, SOL (includes the ETH 1,160-min gap on 2026-09-28 and other 5m gaps).
- Concrete: 5m bar 07-01 00:00/00:05/00:10 -> 15m bar 06-30 23:45-00:00; 5m 00:15 -> 15m 00:00-00:15;
  5m 06-30 23:55 -> 15m 23:30-23:45. (5m open − used 15m open) is 15/20/25 min for 1/3 each.
  => used 15m bar is always COMPLETED before the 5m bar opens; it is exactly Pine, not one bar more delayed.
  (It is one 15m bar older than strictly necessary on the 3rd 5m bar of each 15m bar — that is what V4.5's Pine does;
  V3.9's Pine uses a `time_close == time_close("15")` switch to avoid this, per the source report.)
- Label consistency: 15m file == 5m file resampled with OPEN labels for 98.5–100 % of bars (BTC open 98.8 %, close
  98.5 %; ETH/SOL >= 99.95 %); shifting the 5m labels by ±5 min gives 0.1–4 % equality. Both frames are open-labelled,
  so the `+15m` close computation is right and cannot leak.
- Docstring inconsistency: strategies.py:586-588 says "closed at or before the 5m bar's CLOSE"; the code (600-605)
  correctly uses "<= 5m bar OPEN". Cosmetic.

### T5 V3.9 state machine (`t5_v39_variants.py`, `results/t5_v39_*.csv`, `results/t5_v39.txt`)
Independent re-implementation written from the source report's description (cross memory: golden cross arms
`K<=50 or D<=50`, dead cross clears, >4 bars expires, both>50 clears; fire = commonLongBase & armed & K>D &
(K<=50 or D<=50); memory consumed only by a final signal; cooldown `bar_index - lastLongSignalBar > 2`; D16 =
`ta.crossover(+DI16,-DI16)` on the bar; AC1 = ST10/3 + direction-neutral anti-chop (no ADX cap) + first bar of
AC<0-rising run + AO<0 falling; STC off and no MTF filter on a 15m chart).
- vs port `v39_signals`: **0 mismatches** in S42/S52/SR/D16/AC1/ALL, long and short, all 5 symbols, STC off and on.
- Reproduces delivered `forward_IS_all5.csv` V39_15M exactly (4,312 signals, fwd16 −0.0347 %, fwd64 −0.0710 %).
- Sensitivity of pooled IS forward return (signal-weighted, 5 symbols):

| variant | signals | fwd4 % | fwd16 % | fwd64 % | symbols fwd16<0 |
|---|---|---|---|---|---|
| base (= port) | 4312 | +0.0030 | −0.0347 | −0.0710 | 3/5 |
| memory 3 | 4311 | +0.0032 | −0.0345 | −0.0699 | 3 |
| memory 5 | 4315 | +0.0029 | −0.0346 | −0.0695 | 3 |
| no memory | 3718 | +0.0100 | −0.0248 | −0.0489 | 3 |
| cooldown >= 2 | 4659 | −0.0016 | −0.0317 | −0.0624 | 3 |
| cooldown 0 | 5146 | −0.0030 | −0.0251 | −0.0574 | 3 |
| expire before arm | 4312 | same as base | | | |
| clear all memories on fire | 4312 | same as base | | | |
| STC on 75/25 | 4089 | −0.0026 | −0.0375 | −0.0767 | 4 |
| anti-chop held 3 bars | 2977 | −0.0076 | −0.0569 | −0.0691 | 4 |
| chop threshold 5° | 4170 | +0.0052 | −0.0398 | −0.0811 | 3 |
| TV `ta.supertrend` flip | 4312 | same as base | | | |

No plausible reading of the state machine makes V3.9's 4h/16h forward return positive.
- Entry context (`t7_v39_context_g1.py`): V3.9_15M signed return over the 64 bars BEFORE the signal = **+1.98 %**
  (S42 +2.57 %, SR +2.71 %, D16 +2.14 %), over the prior 16 bars ≈ 0, then fwd64 −0.071 %. The signals really are
  "enter a pause inside a 16-hour move that has already happened" -> the handoff's "late trend chaser" description is a
  property of the strategy, not of the port. (AC1 is the exception: pre64 +0.68 %, fwd64 +0.042 %.)

### T6 V4.5 AM+B forward drift vs alignment (`t6_v45_mapping_sensitivity.py`, `results/t6_v45.txt`)
- Reproduces delivered `forward_ALL_5m_v45.csv` (BTC 563 signals, fwd64 +0.0902 %, t 2.79; ETH 550, +0.1403 %,
  t 2.91; SOL 528, +0.1781 %, t 3.05).
- Pooled fwd64 by 15m alignment: PINE (port) +0.1353 % (n 1,641); TIMELY (close<=5m close, still causal) +0.1405 %;
  DELAY+1 +0.1560 %; LEAK (uses the unfinished containing 15m bar, deliberate look-ahead) +0.1422 %.
  => the drift does not come from the 15m alignment; it is not a look-ahead artifact.
- Statistics: pooled naive t = 4.98, but signals overlap (64-bar horizon) and are correlated across BTC/ETH/SOL.
  Day-clustered t (135 days) = **2.60** (PINE). Selected post hoc as the best of many (3 V4.5 generators × 6 horizons,
  plus 28 15m strategies × 6 horizons) -> treat as a hypothesis, not a finding.
- Entry context: signed return over the 16 bars before the signal = −0.46 % (V4.5 AM+B is a pullback entry against the
  5m move, with the confirmed-15m trend).

### T7 G1 on 15m signals (`t7_v39_context_g1.py`, `results/t7.txt`)
The policy text (source report: "G1: 최근 확정 5분봉 3개 ... ATR14") defines G1 on the last 3 CONFIRMED 5m bars.
`apply_g1` (strategies.py:708-723) is applied to the chart frame, so for V39_15M_G1 / OBV_S_G1 it uses 3 × 15m bars
and a 15m ATR14. On BTC/ETH/SOL in the 5m-data period:
V39_15M blocked 26/415, 25/441, 33/455 (port) vs 43, 44, 72 (5m-bar G1); decisions agree 92 %, 92 %, 88 %.
OBV_S: 24/184, 24/199, 28/165 vs 17, 26, 27; agree 90 %, 89 %, 86 %.
For V4.5 (5m chart) the port matches the spec.

### Misc
- Static scan: no `shift(-k)`, `center=True`, `bfill`, `np.roll` or reversed windows in pine_indicators.py,
  strategies.py, fg_fast.py.
- Zero-range edge cases (where the port returns 0 but Pine returns na: stoch-RSI range, chop 30-bar range; price stoch
  9/11/14/15 returns NaN like Pine) occur **0 times** after warm-up in all 8 files.
- Signals within 50 bars after a >60-min data gap (IS): V39_15M 8/4,312, OBV_S 6/1,571, OBV_B 10/4,250.
- Distance to the pass rule (delivered pooled files): best exit per family — OBV_B PF 0.835, V39_S52 0.807, OBV_S 0.791,
  V39_AC1 0.774, V39_15M 0.723 (gross exp −0.10 %/trade), V45_EXACT_AMB 0.799 (gross +0.018 %, net −0.087 %).
  Every V3.9/OBV strategy has NEGATIVE gross expectancy at its best exit; the port discrepancies found touch <=0.12 % of
  bars (SuperTrend flavour), 0 bars (edge cases) or 8–14 % of G1 decisions on a filter that removes <=16 % of signals.

## 2. Findings (ranked by potential to flip the headline)
See section 4.

## 3. Truncation results

| symbol | generator | t tested | t on signal bars | full-data signals | mismatch at t | mismatch over prefix | True values compared |
|---|---|---|---|---|---|---|---|
| BTCUSD | V39_ALL(all subs) | 200 | 107 | 1321 | 0 | 0 | 371,310 |
| BTCUSD | V39_STC(all subs) | 200 | 105 | 1275 | 0 | 0 | 379,276 |
| BTCUSD | V39_15M_G1 | 200 | 102 | 1239 | 0 | 0 | 126,944 |
| BTCUSD | OBV_S | 200 | 102 | 516 | 0 | 0 | 52,462 |
| BTCUSD | OBV_S_G1 | 200 | 100 | 453 | 0 | 0 | 45,295 |
| BTCUSD | OBV_B | 200 | 100 | 1381 | 0 | 0 | 146,971 |
| ETHUSD | V39_ALL(all subs) | 200 | 102 | 1381 | 0 | 0 | 407,534 |
| ETHUSD | OBV_S | 200 | 101 | 526 | 0 | 0 | 54,440 |
| ETHUSD | OBV_B | 200 | 103 | 1350 | 0 | 0 | 135,971 |
| SOLUSD | V39_ALL(all subs) | 200 | 103 | 1349 | 0 | 0 | 390,268 |
| SOLUSD | V39_STC(all subs) | 200 | 104 | 1292 | 0 | 0 | 399,841 |
| SOLUSD | V39_15M_G1 | 200 | 103 | 1237 | 0 | 0 | 134,794 |
| SOLUSD | OBV_S | 200 | 101 | 493 | 0 | 0 | 52,558 |
| SOLUSD | OBV_S_G1 | 200 | 100 | 418 | 0 | 0 | 44,373 |
| SOLUSD | OBV_B | 200 | 105 | 1336 | 0 | 0 | 147,782 |
| LTCUSD | V39_ALL(all subs) | 200 | 105 | 1279 | 0 | 0 | 353,048 |
| LTCUSD | OBV_S | 200 | 102 | 469 | 0 | 0 | 50,585 |
| LTCUSD | OBV_B | 200 | 102 | 1333 | 0 | 0 | 143,343 |
| BCHUSD | V39_ALL(all subs) | 200 | 103 | 1202 | 0 | 0 | 348,777 |
| BCHUSD | OBV_S | 200 | 102 | 469 | 0 | 0 | 48,011 |
| BCHUSD | OBV_B | 200 | 103 | 1208 | 0 | 0 | 126,308 |
| BTCUSD | V45_signals(AMIX/ASAME/B/C) | 200 | 114 | 3020 | 0 | 0 | 467,058 |
| BTCUSD | V45_EXACT_AMB | 200 | 103 | 563 | 0 | 0 | 59,061 |
| BTCUSD | V45_EXACT_AMB_G1 | 200 | 100 | 557 | 0 | 0 | 55,583 |
| ETHUSD | V45_signals(AMIX/ASAME/B/C) | 200 | 110 | 2981 | 0 | 0 | 447,214 |
| ETHUSD | V45_EXACT_AMB | 200 | 100 | 550 | 0 | 0 | 54,536 |
| ETHUSD | V45_EXACT_AMB_G1 | 200 | 105 | 545 | 0 | 0 | 54,194 |
| SOLUSD | V45_signals(AMIX/ASAME/B/C) | 200 | 107 | 3067 | 0 | 0 | 481,129 |
| SOLUSD | V45_EXACT_AMB | 200 | 101 | 528 | 0 | 0 | 56,889 |
| SOLUSD | V45_EXACT_AMB_G1 | 200 | 101 | 518 | 0 | 0 | 52,483 |

**Total: 6,000 truncation points (3,096 on signal bars), 0 mismatches at t, 0 mismatches on any prefix bar, 5,688,038 True signal values compared.** No look-ahead in V3.9 (all subs, STC on/off, G1), OBV S/B (+G1), V4.5 (AMIX/ASAME/B/C, exact AM+B, +G1).

## 4. Findings, ranked by potential to change the headline

Headline under test: 0/364 15m combos and 0/39 5m V4.5 combos pass; 5m/15m scalping with 50x + fixed-ROE ladder does not
work; the only faint signal is V4.5 exact AM+B 64-bar drift.

**Bottom line for this lens: I found no port defect that biases results in either direction by a material amount.**
Built-ins match TradingView semantics to float precision, the composites match the public Pine scripts exactly,
there is no look-ahead anywhere (6,000 truncation points), the 15m->5m mapping equals Pine `f()[1]`+`lookahead_on`
bar-for-bar, and an independent V3.9 state machine written from the Pine-derived spec reproduces the port exactly.
V3.9's negative forward drift and V4.5's positive one both survive every ambiguity variant I could construct.

PINE-1 (medium, process) No bar-level validation against TradingView/Pine output ever happened. The earlier
source report's own plan was "port 1:1, diff against a TradingView signal export, do not proceed unless 100 %".
Stage 1 skipped that. The only empirical cross-check in the handoff (09-05..09-13: report 56 trades vs repro 59) is not
like-for-like: the report used 5 symbols in one shared single-position account, the repro 3 symbols (104 raw
V45_EXACT_AMB_G1 signals in that window: BTC 26, ETH 49, SOL 29). Residual risk = details of the 1,040/588/294-line
Pine files that the prose summary omits. Bias unclear. Unlikely to change the headline: an omitted detail would have
to add >0.1 %/trade of gross edge to strategies whose best-exit gross expectancy is <= −0.014 % (V3.9/OBV) or
+0.018 % (V4.5), while all 11 V3.9 ambiguity variants keep fwd64 within −0.049..−0.081 %.
Fix: export 1–2 weeks of TradingView signal labels (Binance perp charts) and diff bar-by-bar.

PINE-2 (low) G1 on 15m signals uses 3 x 15m bars + 15m ATR14 (strategies.py:708-723 via v39_all_g1/obv_s_g1,
726-742) whereas the policy text defines G1 on the last 3 confirmed 5m bars. Measured on BTC/ETH/SOL (5m period):
V39_15M blocked 6–7 % (port) vs 10–16 % (5m G1), decisions agree 88–92 %; OBV_S agree 86–90 %.
Bias unclear. Cannot flip: G1 variants' best PF 0.72 (V39) / 0.79 (OBV_S) with negative gross expectancy.

PINE-3 (low, coverage) V3.9 was ported only in its 15m-chart mode (STC gate off, no 15m reference) — correct for
the "15M::" candidates B/C — but the 5m-chart mode (STC 75/25 gate + confirmed-15m 4-trend filter with the
time_close switch) was never ported or tested, although it produced 101 of the 175 RC2 V3.9 trades (−1,281.77).
The 5m grid row "V39_15M_G1" runs 15m-chart logic on 5m bars (neither Pine mode); it is correctly excluded from the
final 5m tables. The headline statement about V3.9 should read "V3.9 in 15m-chart mode". Bias unclear; no flip
expected (that mode lost money in RC2 and the handoff never claimed it was tested).

PINE-4 (low, statistics of the "faint signal") V4.5 AM+B 64-bar drift is NOT a port artifact (truncation clean;
+0.135 % Pine alignment vs +0.141 % timely, +0.156 % one-bar-stale, +0.142 % leaky), but its strength is overstated:
the per-symbol t 2.8–3.1 ignore overlapping 64-bar windows and BTC/ETH/SOL co-movement; pooled day-clustered t = 2.60
(naive 4.98), and it is the best of roughly 200 strategy x horizon cells examined. Makes results look better (for the
faint-signal claim only). Does not change "0 pass". Fix: test it on 5m history never used (Astral returns 5m bars
before 2026-05-13, e.g. 2025-06..2026-05, per the orchestrator) before building option B around it.

PINE-5 (info) Edge-case semantics that differ from Pine but never fire on this data (0 occurrences after warm-up in
all 8 files): stoch-RSI zero range -> 0 instead of na (pine_indicators.py:276); Chop span on zero range -> 0 (146);
`np.round` banker's rounding vs Pine round-half-up (151; 0 exact ties); `_recursive_ma` carries the last value over NaN
inputs (42); DMI bar-0/`fixnan` (199-217, warm-up only); OBV bar 0 = 0 (290-295, constant offset); OBV
volume-readiness gate (`trendReady/breakReady`) not ported (strategies.py:534-577; data has 0 NaN / 0 zero volumes).
Cosmetic: v45_signals docstring (strategies.py:586-588) says "closed at or before the 5m bar's close" while the code
(600-605) correctly uses "<= 5m bar open"; unused parameter `adx_max_for_c` (strategies.py:374). Neutral.

PINE-6 (info, data feed) Signals are computed on Polygon-aggregated spot OHLCV, not the Binance USDT-M perp feed
the Pine scripts ran on (OBV is the most exposed because its crosses depend on volume). Signal-level agreement with the
live bots is therefore not expected even with a perfect port. Bias unclear; not a port defect.

## 5. What is confirmed correct (see also structured output)
- `pine_ema`/`pine_rma` seeding (SMA of first `length`), RSI, MACD, DMI/ADX, Stoch K/D, AO/AC, OBV (to offset).
- SuperTrend = Kivanc "exchange" form (0 mismatches); TV built-in differs on <=0.12 % bars and gives identical V3.9 stats.
- STC = shayankm; Chop Zone = TradingView (formula, sign: EMA rising -> positive, rounding).
- Pine crossover/crossunder with na -> false.
- V3.9: memory 4, cooldown >2, arm/disarm order, both-above/below resets, AC1 path, STC-off/no-MTF on 15m chart
  (docstring claim confirmed by the source report, Pine lines 350-351 / 441-444).
- OBV S/B conditions equal the verbatim Pine blocks quoted in the source report (STC 70/30 strict, trendMa 30,
  breakMa 9 on 15m, AC>0 / AC>0 & rising, 3 stochastics 11/15/9 with K=SMA4, D=SMA3).
- V4.5 AMIX/ASAME/B/C, exact AM+B = B & !C, STC 75/25 inclusive on 5m and confirmed 15m, S33/S43/SR(14/14/5/3).
- No look-ahead; 15m->5m mapping = Pine exactly; 5m/15m files are consistently open-labelled.
