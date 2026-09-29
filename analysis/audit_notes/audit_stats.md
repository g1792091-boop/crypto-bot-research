# Statistical inference / methodology audit of stage-1 handoff

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/audit_stats`
(`bt/` = copy of the project's bt/ plus audit scripts; `data` = symlink to the project data; `results/` = audit outputs).
Nothing under /home/user/crypto-bot-research was modified. No Astral tools were used.

The only code change to the copied package is in `bt/strategies.py` (v45_signals). It adds extra dict keys for the
intermediate filters (F15_*, OPP_*, OPPCHOP_*) used as baselines. Existing outputs are unchanged, and the
reproduction below was run with this copy.

## 0. Reproduction of forward_ALL_5m_v45.csv (not produced by any script in the package)
`bt/repro_fwd5.py`: 5m + 15m via `run.load_csv`, `strategies.v45_exact_amb / v45_exact_amb_g1 / v45_any`,
window ALL, `forward.forward_stats` (warmup 1000).
Result: all 9 rows x 20 numeric columns match. Max abs diff 4.4e-16 (`results/forward_ALL_5m_v45_repro.csv`).
V45_EXACT_AMB 64-bar: BTC 563 sig +0.0902% t 2.79, ETH 550 +0.1403% t 2.91, SOL 528 +0.1781% t 3.05.
Pooled: 1641 signals, +0.1353%, hit 56.6%.

## 1. V4.5 exact AM+B, 64 x 5m forward drift: corrected inference

### Why the handoff t is invalid
forward.py:30 computes `t = mean/(std/sqrt(n))`, which assumes independent observations. The 64-bar windows overlap heavily:
- median gap between signals is 15-25 bars and 65-70% of gaps are <= 64 bars (16-17% are consecutive bars)
- on average 2.7-3.5 other signals of the same symbol fall within +-64 bars (max 8-12)
- BTC, ETH and SOL signals are also co-timed, so pooling across symbols adds further dependence
  (`bt/ctx.py`).

### Corrected numbers (`bt/v45_stats.py`, `results/v45_stats_hz64.csv`)
| statistic (hz=64) | BTC | ETH | SOL | POOLED |
|---|---|---|---|---|
| mean % | 0.090 | 0.140 | 0.178 | 0.135 |
| naive t (handoff) | 2.79 | 2.91 | 3.05 | 4.98 |
| Conley/Bartlett HAC in time, bw = 65 bars (cross-symbol pairs included) | 1.78 | 1.92 | 1.96 | 2.54 |
| Conley bw = 130 bars | 1.69 | 1.84 | 1.90 | 2.38 |
| Newey-West on time-ordered signal series, lag = max #signals within 64 bars (8/7/7; pooled 19) | 1.70 | 1.75 | 1.94 | 2.37 |
| calendar-time exposure-weighted (bar level), NW lag 64 | 1.68 | 1.83 | 1.82 | 2.40 |
| non-overlapping subsample (greedy gap >= 64), N | 209 | 202 | 215 | 626 |
|   its mean % / t | 0.091 / 1.63 | 0.156 / 1.80 | 0.199 / 1.95 | 0.149 / 2.42 (cross-sym HAC) |
| day-block bootstrap t (p two-sided) | 1.65 (0.099) | 1.72 (0.086) | 1.87 (0.064) | 2.33 (0.019) |
| 7-day moving-block bootstrap t (p) | 1.58 (0.115) | 1.73 (0.083) | 2.09 (0.035) | 2.21 (0.024) |
| random-entry null, iid bars, same count & side mix, 2000 draws: p one-sided | 0.014 | 0.006 | 0.001 | 0.0005 |
| circular time-shift null (keeps clustering, side sequence, cross-symbol co-timing), 2000 draws: z / p one-sided | 1.25 / 0.094 | 1.30 / 0.094 | 1.52 / 0.055 | 1.65 / 0.037 |
| beta/drift baseline (long_share x mkt mean 64-bar - short_share x mkt mean) % | -0.001 | -0.000 | +0.004 | +0.001 |

The iid random-entry null is too liberal because it scatters entries uniformly and destroys clustering.
The circular-shift null is the honest one.

Calibration (`bt/calibrate.py v45`, 1000 circular-shift draws of the whole pooled signal set):
- naive t: null sd 2.81, P(|t|>1.96) = **40.7%** (nominal 5%)
- Conley bw 1H: null sd 1.39, size 9.1%. Conley 4H: 1.31, 7.2%. Day-cluster: 1.32, 7.2%. Week-cluster: 1.38, 9.1%
- calibrated z of observed: 1.68-1.78, empirical one-sided p 0.023-0.033

So even the HAC t-values are about 1.3-1.4x too large here, because side persistence meets multi-day trends and
volatility clustering.
**Honest single-test evidence: z ~ 1.7, one-sided p ~ 0.02-0.04 (two-sided ~0.05-0.07). Per symbol: z ~ 1.3-1.5, not significant.**

### Robustness of the point estimate (`bt/v45_robust.py`)
- median +0.101%, winsorised(1/99) +0.133%, excluding top 10: +0.104%. **Not outlier-driven.**
- by month: May +0.041 (n=169), Jun +0.232, Jul +0.070, Aug +0.165, Sep +0.117. All positive.
- long +0.187% (815), short +0.085% (826)
- naive sign test p = 9e-8. This is meaningless for the same overlap reason (the 57% hit rate is over-counted).
- entry delayed by 1 or 3 extra 5m bars: +0.138% / +0.139%. The trigger timing does not matter.

### The drift is not V4.5-specific (`bt/v45_stats.py` BASE_* rows, `bt/v45_robust.py`)
64-bar signed forward means, pooled BTC/ETH/SOL, same window:
- every bar in the 15m ST(14,6) direction with the STC filter (V4.5's `f15_long/short`), N=43,339: **+0.087%**
- plus the 5m main/strong ST disagreement (OPP), N=18,607: **+0.112%**
- plus the chop filter (OPPCHOP = parent state of B), N=15,882: **+0.117%**
- V4.5 exact AM+B (subset of OPPCHOP): +0.135%
- raw 15m ST direction without STC: +0.037%

Conditional null: random subsets of OPPCHOP bars with the same per-symbol count and long count (iid, so the sd is a lower bound).
Null mean 0.120%, sd 0.028%, observed z = 0.55, p = 0.29.
**The V4.5 trigger (stoch cross + weak MACD + not-C) adds ~0.015% over its parent trend-pullback state, which is indistinguishable from 0.**
The "faint signal" is a generic 15m-trend / time-series-momentum exposure.

### The underlying mechanism is regime-specific (`bt/trend15_replication.py`, `bt/monthly_trend.py`)
The same 15m ST(14,6)+STC state was evaluated on 15m bars. Horizon 21 x 15m (5.25h, the same clock time as 64 x 5m).
- 15m IS window (2025-08-07..2026-05-07), never used for V4.5: 5 symbols **-0.043%** (N 77,583, Conley t -1.45),
  BTC/ETH/SOL -0.018% (t -0.54)
- 15m OOS window (2026-05-08..09-29): 5 symbols **+0.094%** (Conley t 2.86, shift p 0.028), BTC/ETH/SOL +0.076%
- monthly (5-symbol mean): 2025-08 +0.135, 09 -0.004, 10 -0.070, 11 -0.138, 12 -0.216, 2026-01 +0.113,
  02 -0.076, 03 +0.036, 04 -0.100 | 05 +0.074, 06 +0.250, 07 -0.009, 08 +0.040, 09 +0.118
- naive t for the same state swings from -7.7 (IS) to +14.7 (OOS). This again shows naive t is meaningless here.

Market context (5m files): BTC opened 81,153 (2026-05-13) and fell to ~58k (low 57,718 on 2026-07-01, about -28%).
It then rallied to 87,447 (2026-09-21, about +50%) and closed at 82,945 (+2.2% net).
ETH 2,281 -> low 1,505 (06-06) -> 2,657 (+16.5%). SOL 95.4 -> 60.1 (06-06) -> 116.6 (+22.2%).
Two strong directional legs favour trend-state exposure. Net beta is ~0 because the side mix is ~50/50.
BTC over the 15m IS: 115,027 -> 80,005 (-30%), but choppy.

### V45_ANY (not mentioned in handoff)
Naive t 5.5 / 3.7 / 7.0 per symbol at 64 bars (pooled 9.4). Mean #neighbours within 64 bars is 11.5 and VIF is 5.4 per symbol, 10.8 pooled.
Conley t pooled 2.85, shift-null z 1.86. In the 5m family scan ANY looks more significant than EXACT_AMB at every horizon;
all horizons have raw p about 0.01-0.05.

## 2. S5 (15m IS, 324 signals, 4h = 16 bars, +0.103%) (`bt/s5_stats.py`, `results/s5_stats.csv`, `bt/calibrate.py s5`)
- pooled naive t 1.12 (the handoff never reported a t), Conley 0.91, NW 0.98, day-bootstrap t 0.88 (p 0.38), shift-null z 1.17 (p 0.13).
  Calibrated z ~0.9, one-sided p ~0.19
- hit rate 49.4%, median **-0.017%**. Per symbol: BTC -0.076, ETH +0.263, SOL +0.039, LTC +0.375, BCH +0.003
- driven by outliers: without the single best signal (LTC long 2025-11-07, +13.3% in 4h) the mean is +0.062%. Without the top 5 it is -0.003%.
  At 64 bars the top contributor is the LTC short on 2025-10-10 15:15 (+21.8%, the Oct-10 crash)
- the "> +0.1%" label depends on picking the 16-bar horizon: S5 is +0.179% at 8 bars (raw shift z 2.83 = the family max),
  +0.068% at 32 and +0.090% at 64. At 16 bars N09_ALLIG_AROON has more evidence (+0.083%, Conley t 1.95, shift p 0.017),
  and at 32/64 bars N17, S6, N08, N03 and N09 all exceed +0.1%
- N17_KC_RSI (15,082 signals) has naive t 7.8 at 32 bars, but Conley t is 1.7 and shift p 0.068 (VIF ~21)
- the V3.9 "negative = late chasing" claim: shift z -0.99 to -1.46 at 16 bars, p 0.14-0.31. **Not supported statistically.**

## 3. Multiple comparisons (`bt/mc.py`, `bt/mc_analyze.py`, `results/mc_*_tests.csv`)
Null: 2000 circular time shifts. Each draw applies ONE shift to every strategy and symbol, which preserves the clustering,
the side sequences and the cross-strategy and cross-symbol correlation.
The max-T (Westfall-Young) is taken on shift-standardised pooled means.
- 15m IS family: 28 strategies with signals x 6 horizons = 168 pooled tests (840 per-symbol)
  - null max |naive pooled t|: median **6.37**, 95th pct 13.2. Observed max 7.80
  - null max |naive per-symbol t|: median 5.74, 95th pct 9.08. Observed max 6.24
  - per-test null sd of the naive t: median 1.31, up to 6.1
  - null max |z|: median 2.70, 95th pct 3.66. Observed max 2.83 (S5 at 8 bars), FWER p 0.38
  - raw two-sided p<0.05: 7 of 168 (8.4 expected under the global null). Min BH q = 0.84. **The scan is consistent with pure noise.**
- 5m V4.5 family: 3 variants x 6 horizons = 18 pooled tests
  - null max |z|: median 1.55, 95th pct 2.65. Observed max 2.15 (V45_ANY at 32)
  - V45_EXACT_AMB at 64: z 1.74, raw one-sided p 0.032, **FWER p 0.365**, BH q 0.147
- combined 186 tests (the whole forward scan that produced "the only faint signal"): null max |z| median 2.72, 95th pct 3.73.
  V45_EXACT_AMB at 64 has FWER p 0.999 and S5 at 16 has 1.000
- as a Bonferroni cross-check, 186 independent two-sided tests need |z| >= 3.64. No test comes close.

## 4. Holdout contamination
- The 15m split is 2026-05-08 (run.py:20). All 40,000 5m bars of BTC/ETH/SOL are >= 2026-05-12, so 100% of the 5m data lies in the 15m OOS window.
- The 15m OOS has already been viewed through: (a) V4.5 13-exit backtests; (b) the V4.5 forward scan, where the drift was discovered;
  (c) V39_15M_G1 run on 5m bars in summary_ALL_5m_v45g1.csv (39 rows), i.e. a 15m-family strategy evaluated in the OOS period;
  (d) the Sep 5-13 cross-check, which is inside the OOS. In addition V4.5 uses 15m ST/STC values computed from OOS 15m bars.
- The 28 x 13 15m grid itself was never run on 15m OOS bars. No OOS file exists, so the 15m OOS is still formally sealed for
  those 28 strategies, but regime knowledge (V-shaped trend) has leaked.
- **Any "option B" (V4.5 slow variant) test on the current 5m data is fully in-sample.** Its expected edge was estimated on it.
- Clean data remaining for V4.5-type hypotheses:
  - on disk: 15m 2025-08-07..2026-05-07 (26,166-26,187 bars/symbol), never used for V4.5, but used for the 28-strategy selection.
    CAVEAT: this audit has now looked at the 15m ST+STC trend state there (it was negative), so that mechanism is no longer blind on it
  - not on disk: 5m bars before 2026-05-12. Astral start/end queries reportedly return BTCUSD 5m at 2025-06-01.
    2025-08-07..2026-05-11 is about 277 days = about 79,800 5m bars/symbol (2 requests of 40k), and data before 2025-08-07 is completely unseen
- Power of a clean replication: the pooled circular-shift SE of the mean is 0.081% for 1641 signals (4.5 months).
  With about 9 months (about 3,300 signals) the SE is about 0.057%, so the MDE (80% power, one-sided 5%) is about 0.14%/signal.
  That is only powered to confirm an effect as large as the (winner's-curse-inflated) observed one.
  With the Conley SE the MDE is about 0.09%. The 15m OOS (13,830 bars) is also low-powered: S6 SL2/TP3 would get about 440 trades, MDE about 0.20%/trade.

## 5. Power and the pass rule (`bt/power.py`, `bt/rule_oc.py`, `results/power_combos.csv`, `results/rule_oc.csv`)
- per-trade sd of net across the 364 combos: median 0.95%, IQR 0.77-1.17%. ATR exits 0.71-1.44%, ladder exits 0.34-0.39%
- trades needed for 80% power, alpha 0.05 two-sided:
  - +0.05%/trade: median **2,813** (IQR 1,836-4,307)
  - +0.10%/trade: median 703
- MDE at n=100 is 0.27%/trade. At n=835 (the best combo) it is 0.09%
- the actual combos: 0/364 have net expectancy > 0 and 0/364 have PF >= 1. With day-clustered t, **342/364 are significantly negative**,
  0 significantly positive, max t -0.85. Best: S6 SL2/TP3 -0.052% (t -0.88; 95% CI about -0.17%..+0.064%),
  so a small positive edge cannot be excluded for the top few.
  eq_L5 < 1 for all 364 combos, and eq_L50 max is 0.006
- operating characteristic of the rule (bootstrapped trades within symbol, net shifted to a true mean):
  - n = 100: P(pass | true mean 0) = 20-23% for every combo tested. With 364 combos this is far too loose;
    it only did no harm because every combo was strongly negative
  - actual n (835-4,106), true mean 0: P(pass) 0-0.6%
  - true mean +0.05%: P(pass) = 7% (S6), 5% (N24), 31% (N18), **100% (V39 ladder)**
  - true mean +0.10%: 30% (S6), 91% (N24), 100% (N18, ladder)
  So the rule is loose at small n and strict for wide ATR exits at large n, and it is inconsistent across exit designs.

## 6. PF vs expectancy
- identity: mean = E|x| * (PF-1)/(PF+1) (verified, max err 1e-16), so PF > 1 <=> expectancy > 0. For the sign they are equivalent.
- PF 1.2 therefore means an exit-dependent expectancy bar: **0.029-0.031% for the L50 ladders and 0.118% for SL2/TP3** (median over strategies).
  At n=100 a PF-1.2 edge has t of only about 0.8. At typical n (about 2,000-2,900) it has t of about 3.0-4.5.
- PF on unlevered returns is invariant to leverage except for liquidations and compounding. Those only hurt negative-expectancy combos,
  so the metric choice cannot change the headline.
- Recommended primary metric: net expectancy per trade with a day-clustered or HAC SE (all symbols together), plus an a-priori minimum economic
  effect (e.g. >= +0.03-0.05% after costs), multiplicity control (Westfall-Young / BH, or a deflated Sharpe) and a powered OOS.
  Secondary: account-level log growth at the intended leverage, including liquidation. PF should be descriptive only.

## Other small items
- forward.py includes signals up to the IS end whose forward windows extend up to 64 bars into the OOS (a few signals). Negligible.
- The 15m file timestamps are bar OPEN. 5m bars aggregated to 15m match the 15m OHLC exactly (98.5-100% exact close matches)
  under the open-label convention, and they do not match under a close-label hypothesis. **No label look-ahead in the V4.5 15m->5m mapping.**
- Costs vs drift: the round-trip taker cost is 0.14% plus 0.007% funding over 5.3h, so the +0.135% gross drift is about -0.01% net with taker fills.
  With maker 0.02%/side it would be about +0.09% net *if the drift were real*. The evidence above says it is regime-dependent and not specific to V4.5.
