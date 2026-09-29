# gap_2: positive control for the stage-1 pipeline (time exits, ladder, detection thresholds)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/gap_2`
(`bt/` is an unmodified copy of `/home/user/crypto-bot-research/bt`; `data` is a symlink to the project data. Nothing under /home/user/crypto-bot-research was modified.)

The question: can the stage-1 pipeline ever say PASS when a real edge exists? What edge size does each exit family need before it passes the pre-registered rule? Rule: pooled PF ≥ 1.2, ≥100 trades, net expectancy > 0, ≥3 symbols positive (`bt/analyze.py:16,38-43`).

## Files

| file | what |
|---|---|
| `work/posctrl2.py` | critic's script, copied unchanged |
| `work/posctrl2.csv` | rerun output, byte-identical to `critic/work/posctrl2.csv` |
| `work/posctrl3.py` | extended positive control (5m/15m/1h; sign + drift oracles; 13 stage-1 exits + TIME16/TIME64; forward drift + circular-shift null) |
| `work/analytic.py` → `out/analytic.csv` | analytic TIME-exit threshold μ* = cost_H + 0.091·E\|r_H\| |
| `work/aggregate.py` → `out/aggregate.txt`, `out/agg_cells.csv`, `out/agg_thresholds.csv` | seed-averaged pass rates and PF=1.2 crossings |
| `work/final_table.py` → `out/final_thresholds.csv` | the main threshold table (below) |
| `out/sign_{5m,15m,1h}.csv`, `out/drift_{5m,15m,1h}.csv` | raw grid: one row per (tf, oracle, k, dial, seed, exit) |
| `out/neg_{5m,15m,1h}.csv` | zero-edge negative control (30/30/60 seeds) |
| `work/k6check.py` → `out/k6q08.csv` | critic row 3 (k=6, q=0.8) over 8 seeds |
| `work/real_time.py` → `out/real_time_gate.csv` (+ trades) | TIME16/TIME64 and shift-null forward-drift gate on the REAL stage-1 strategies |
| `work/shift_time_pf.py` → `out/shift_time_pf.csv` | circular-shift null for the TIME64 PF of S6, N03, V45_EXACT_AMB |

Run times: posctrl2 14.6 s. Each posctrl3 cell takes 2–5 s. The full grid is 240 sign + 288 drift cells at 4 seeds, run as 2 processes for about 25 min.

## 0. Critic's posctrl2 table: reproduced, three caveats

`python3 work/posctrl2.py` gives `posctrl2.csv` equal to the critic's file (`DataFrame.equals` True, max abs diff 0). Every number in the task's table matches the CSV. For example, k=64 q=0.3: fwd64 0.2313%, L50 PF 0.248/0.294, SL2/TP3 1.016, TIME64 1.100, 0 passes. And k=64 q=0.5: 0.4416%, 0.259/0.319, 1.122, 2.061, TIME64 only.

Caveats:

1. **q is not the hit rate.** side = oracle with probability q, otherwise a coin flip, so P(correct) = (1+q)/2. Measured on BTC 5m: q=0.8 gives 0.893 at k=6 and 0.901 at k=64. The row "30-minute direction right 80% of the time" is actually right about 90% of the time. That makes the ladder result stronger.
2. **Single seed.** Row 3 (k=6, q=0.8) over 8 seeds with the critic's density of 4.5%:

   | exit | PF mean | PF range | pass rate |
   |---|---|---|---|
   | TIME64 | 1.145 | 1.045–1.211 | 1/8 |
   | SL2/TP3 | 1.167 | — | 3/8 |
   | L50 | 0.53 / 0.69 | — | 0/16 |

   "Time exit only passes" is a seed artifact. For a 30-minute edge the bracket exit is the better detector. The ladder conclusion holds.
3. **Off-by-one in TIME exits.** posctrl2 used max_hold=65, and the task suggests max_hold=H+1. The engine exits at `c[e+max_hold-1]` (`engine.py:65,117-120`). Since c[t−1] ≈ o[t] (median |o[t]/c[t−1]−1| is 0.00002–0.016% across the 8 files), max_hold=H ends at o[e+H]. That is exactly forward.py's endpoint `o[idx+1+hz]` (`forward.py:98-99`). I used max_hold=H. The impact is trivial.

"The grid has no time exit" is confirmed. `engine.py:220-229` defines 9 FIXED + 2 TRAIL + 2 LADDER exits. The only time stop is max_hold: 1000 bars for 15m (`engine.py:44`) and 3000 bars for 5m (`run.py:143`), i.e. about 10 days.

## 1. Design of the extended positive control (posctrl3.py)

- **Data and windows, same as stage 1.**
  - 5m: BTC/ETH/SOL, window ALL, max_hold 3000.
  - 15m: 5 symbols, window IS (before 2026-05-08, about 25k bars), max_hold 1000.
  - 1h: the 5 × 15m files resampled (open first / high max / low min / close last). That gives about 10,000 bars (14 months), window ALL, max_hold 1000.
- **Signals.** Random bars at 3% density (stage-1 15m strategies: median 1.8%, mean 3.2% of bars). Single position per symbol through the unchanged `run_backtest`, so overlapping signals are skipped exactly as in stage 1.
- **Oracle "sign"** (as posctrl2): side = sign(o[i+1+k]/o[i+1]−1) with probability q, otherwise random. q ∈ {0, .05, .1, .15, .2, .3, .4, .5, .6, .8}. Its drift profile is a linear ramp to k and then flat.
- **Oracle "drift"** (new, additive, no look-ahead selection): random bars, random side. A log-price ramp of +μ in the side direction is added to the real OHLC over the k bars after entry and then held. ATR is recomputed. μ ∈ {0, .05, .1, .15, .2, .3, .4, .6, .8, 1.2, 1.6, 2.4}%.
- **k.** k ∈ {16, 64} bars, with 4 seeds per cell.
- **Exits.** All 13 stage-1 exits unchanged, plus TIME16 and TIME64. These are `ExitCfg(mode="FIXED", sl_atr=1e4, tp_atr=1e4)` with `CostCfg.max_hold=H`. The TIME rows show avg hold exactly 16.000 / 64.000, so SL/TP never trigger.
- **Costs** are the stage-1 defaults: 0.05% taker × 2, 0.02% slippage × 2 market fills, funding 0.01%/8h. Round trip is 0.14% plus funding(H). For 1h, H=64 that is 0.22%.
- **Forward drift** on all oracle signals at H=16/64. The circular-shift null shifts each symbol's signal train, keeping sides, by a random offset inside the window: B=300 in the grid, B=1000 for the real strategies. It reports z and a one-sided p.

## 2. Null calibration (zero edge)

| tf | seeds | P(any of 15 exits passes) | TIME64 PF mean ± sd (trades) | fwd z mean / sd |
|---|---|---|---|---|
| 5m | 30 | 0.000 | 0.715 ± 0.072 (1205) | 0.17/0.97 (H16), 0.31/1.09 (H64) |
| 15m IS | 30 | 0.000 | 0.857 ± 0.073 (1294) | −0.04/1.16, 0.03/0.89 |
| 1h (14 mo) | 60 | **0.017** (TIME64 only) | 0.899 ± 0.117 (461) | 0.27/1.12, 0.21/1.02 |

The shift-null z is well calibrated. On short 1h samples the rule has a real false-pass rate: TIME64 PF 1.2 is only +2.6 sd from its zero-edge mean. One more zero-edge 1h pass appeared in the grid (sign k=16 seed 0: TIME64, 472 trades, PF 1.214, net +0.35%/trade, 4/5 symbols positive).

## 3. Main result: smallest planted drift that passes the rule (≥50% of seeds), % per signal at horizon k

| tf | horizon | cost_H | shift-null gate z≥3.2 | TIME_H analytic μ* | TIME_H sim | stage-1 grid (any of 13) | FIXED9 | TRAIL2 | L50 ladders |
|---|---|---|---|---|---|---|---|---|---|
| 5m | 16 bars = 1.3 h | 0.142 | 0.045–0.055 | 0.18 | 0.19–0.20 | 0.20–0.30 | 0.20–0.30 | 0.30 / never ≤0.32 (sign) | **1.60** (drift) / never ≤0.32 (sign) |
| 5m | 64 bars = 5.3 h | 0.147 | 0.08–0.11 | 0.22 | 0.25–0.28 | 0.40–0.59 | 0.40–0.59 | 0.59 / never ≤0.65 | never ≤2.43 |
| 15m | 16 bars = 4 h | 0.145 | 0.10 | 0.23 | 0.26–0.32 | 0.35–0.40 | 0.35–0.40 | 0.40–0.53 | never ≤2.40 |
| 15m | 64 bars = 16 h | 0.160 | 0.15–0.19 | 0.33 | 0.30–0.43 | **0.76–0.79** | 0.76–1.23 | 0.79–1.53 | never ≤2.43 |
| 1h | 16 bars = 16 h | 0.160 | 0.27–0.28 | 0.33 | 0.35–0.38 | 0.35–0.53 | 0.35–0.53 | 0.60–0.74 | never ≤2.40 |
| 1h | 64 bars = 64 h | 0.220 | 0.58–0.66 | 0.57 | ~0.55–0.68 (\*) | **1.08–1.53** | 1.53–1.63 | 1.08–1.53 | never ≤3.03 |

(\*) The 1h drift k=64 cell is noisy: pass rates by μ were 0.75 at 0.30%, 0 at 0.34%, 0.5 at 0.66%, 0.5 at 0.73%, and 1.0 at 1.08%. The seed-averaged PF=1.2 crossing is 0.68%. SE(mean) for 1h TIME64 with about 460 trades is ≈0.24%/trade.

The ratio of the grid's threshold to the matched time exit's is 1.0–1.5× for 16-bar edges and **1.6–3.7× for 64-bar edges** (`final_thresholds.csv`, column `grid_over_time`).

The analytic formula μ* = cost_H + 0.091·E|r_H| comes from PF = (E|r|+m)/(E|r|−m), with E|r_H| from the data. It predicts the simulated matched-time-exit threshold within about ±0.05 percentage points in every cell. **The rule's absolute-drift bar grows with the horizon:** a 64-hour edge on 1h needs ≥0.57%/trade even with a perfect exit.

**Capture ratio** is (gross(μ) − gross(0)) / planted drift, taking the best exit in each family at μ = 0.6% and 1.2% (`out/capture_ratio.csv`):

- 64-bar drift:
  - FIXED9 0.25–0.44
  - TRAIL2 0.29–0.66
  - L50 0.02–0.08
  - TIME16 0.23–0.35
  - TIME64 0.95–1.25
- 16-bar drift:
  - FIXED9 0.60–0.80
  - TRAIL2 0.60–1.06
  - L50 0.03–0.22
  - TIME16 0.90–1.00

This matches optional stopping: capture ≈ E[min(τ,H)]/H. Average holds are FIXED9 8–18 bars, TRAIL2 14–28, and L50 5–6 bars on 5m, 2.3–2.9 on 15m, **1.6–1.8 on 1h**.

## 4. Real stage-1 strategies with the missing time exits (real_time.py)

- **0 of 62 combos pass** (31 strategies with signals × TIME16/TIME64). The headline "0 pass" is robust to the blind spot.
- The grid had 0/364 combos with net > 0; the best was S6 SL2/TP3 at PF 0.928, −0.052%/trade. With TIME64, three strategies turn net positive:

  | strategy | TIME64 PF | net %/trade | trades | symbols positive |
  |---|---|---|---|---|
  | S6_EMA_DMI_ADX | 1.097 | +0.091 | 645 | 3/5 |
  | N03_ADX_GC | 1.089 | +0.096 | 146 | 3/5 |
  | S5_DONCHIAN_MFI | 1.018 | +0.018 | 272 | — |

- Across the 31 strategies, the best time exit beats the best grid exit for 16 of them.
- Shift null on the TIME64 PF (B=200):
  - S6: p=0.025 (null PF 0.855 ± 0.103, null pass rate 0.5%)
  - N03: p=0.17 (null PF 0.90 ± 0.215, **null pass rate 7.5%** with only 146 trades)
  - V45_EXACT_AMB: PF 0.998, net −0.001% on 621 trades, p=0.005 (null PF 0.70 ± 0.09)
  - These are post-hoc results among 62 new combos, so none is significant after multiplicity correction.
- Exit-independent forward drift against the shift null (pooled over symbols, B=1000):
  - V45_ANY: z16 2.98 (p 0.004), z64 2.60 (p 0.003), fwd64 0.110%
  - V45_EXACT_AMB: z64 2.43 (p 0.015), fwd64 0.136%, 1,640 signals, 3/3 symbols positive
  - V45_EXACT_AMB_G1: z64 2.39
  - N09_ALLIG_AROON: z16 2.72, z64 2.11
  - S6: z64 2.02
  - Every other strategy is < 1.6. Bonferroni over 62 tests needs p < 0.0008, and the minimum observed is 0.003, so **nothing is significant**.
- "V4.5 AM+B is the only faint signal" is not unique under a shift null: V45_ANY, N09 and S6 are as strong or stronger. The handoff's per-symbol t of 2.8–3.1 (naive, with overlapping windows) would pool to about 5. The overlap-aware shift-null z is 2.43.
- My fwd64 for V45_EXACT_AMB is 0.136% on 1,640 signals, matching the handoff's +0.135% on 1,641 signals in `forward_ALL_5m_v45.csv`. My S5 fwd16 is 0.103% on 324 signals, also matching the handoff.
- **V4.5 cannot be monetised at taker cost by any exit:**
  - fwd64 is 0.136%, below the 5m cost_64 of 0.147%, which in turn is below the TIME64 detection threshold of 0.22–0.28%.
  - With the matched TIME64 exit the result is PF 0.998, net −0.001%.

## 5. What this means for the headline and for Option A

- The headline is **unchanged**. "0/364 and 0/39" strongly rejects fast taker-cost scalping. The blind spot for slow edges is real, but the forward table and the explicit time exits show no hidden slow edge large enough to pass.
- The critic's "barely constrains multi-hour drift below ~0.3–0.4%" is accurate for 5m (5.3 h). It **understates the 15m case**: the 15m grid had 0 passes in 4 seeds for 16-hour drifts of 0.57–0.59% and reached ≥50% only at 0.76–0.79%, which is about 5× the cost_64 of 0.16%.
- Handoff inconsistency: §5 line 56 says fixed-ROE stops and the ladder are discarded. §8 line 105 (and §5 line 61, "같은 28개") asks to run "같은 28개 전략 × 13개 청산", which includes the two L50 ladders. On 1h the ladder holds 1.6–1.8 bars, has zero-edge PF 0.41–0.45, and never passed even at a planted 3.0% drift or a 90%-accurate oracle. It is a dead detector.

### Proposed redesign of A (pre-register before pulling any 1h data)

1. **Positive and negative controls first.** On the new 1h (and 4h) files, run posctrl3-style planted-edge and zero-edge controls. Record the detection thresholds and the false-pass rate for the exact data length. The 14-month numbers above should roughly halve in SE with 4.6 years; that is an extrapolation, not measured.
2. **Gate 0: exit-independent.**
   - Compute pooled fwdH for H ∈ {4, 16, 64} bars on IS.
   - Use a circular-shift null (B ≥ 2000) with Holm correction over strategies × H × tf. For about 26 × 3 × 2 tests that needs z ≈ 3.4.
   - Add an economic hurdle: fwdH ≥ μ*_H = cost_H + 0.09·E|r_H|. On 1h that is ≈0.33% at 16 h and ≈0.57% at 64 h. Below it, no exit can pass PF ≥ 1.2 at taker cost, whatever the exit.
3. **Exit stage for survivors only.** Use a TIME_H exit matched to the gate horizon, plus a few wide ATR brackets or trails. Drop both L50 ladders and the 1-ATR brackets (lowest capture). Do not re-search exits on IS.
4. **Multiplicity at the exit stage.** Apply a shift-null to each surviving combo's PF/net; a low trade count can give ~7.5% false passes. Then open OOS.
5. **Leverage only afterwards,** once a price-level edge survives OOS.

## 6. Limitations

- Oracles are uniform-random in time. Real signals cluster, which means fewer independent trades and a flatter pass-probability curve. The PF crossings are unaffected.
- The drift oracle is a linear ramp held permanently. Edges that are hump-shaped, mean-reverting or concentrated in particular volatility regimes could favour brackets or trails differently.
- With 4 seeds, pass-rate resolution is 0.25. The dial grid is coarse, so thresholds are grid values and are cross-checked by the PF=1.2 interpolation and the analytic formula.
- 1h is a 14-month resample of the 15m files, not Astral 1h. No data was pulled (per the task, before any data pull).
- The 5m rule with 3 symbols requires 3/3 symbols positive (`analyze.py:16`), which is stricter than 3/5.
