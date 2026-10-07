## Lens: context filters — is there structure an AI could learn?

**Question.** The 36 core strategies (and the 44 DeepSeek definitions) have no direction edge: side-flip excess is -0.005 R over 1,989 signals. Could a human-like AI that reads the chart before entering ('only in trend regimes', 'not into resistance', 'trade with the move', 'skip the London session') add the missing edge?

**Short answer.** Not from these contexts.
- Live, across runs, nothing replicates beyond chance. A filter learned on one run either does nothing or loses money on the next.
- On 5 years of every-signal data (1.65M signals) the context effects are real but tiny: 0.01-0.06 R. The best learned context filter lifts the kept third by about +0.03-0.05 R.
- With the filter, no core strategy x tf (15m/30m) reaches break-even: all 64 filtered cells stay below 0.
- Paper data cannot detect effects of that size before 12/31.

### Data and method (scripts in `lens/context_filters/`)

**Unit.** One SUBMITTED signal, run alone, outcome in net R (`build_signals.py`):
- v3b and v4: the pipeline's replay (parity with live trades exact).
- v3a: the real trade if entered; otherwise the nightly skipped shadow, converted ROE to R with the repo's own sizing. The conversion matched the replay to 2e-16 on 1,696 v4 signals, and fresh-account leverage matched real trade leverage on 96.5% of v3a trades.

**Joins and coverage.** Context comes from signal_ctx (regime, HTF regime, ER, ADX/DI, EMA20 distance, trend age, box/range position, HTF box, S/R) plus stop %, KST session, coin, quality tier, and consensus/conflict among same-group signals at the same bar.

| run | kind | 15m signals with R | 30m signals with R |
|---|---|---|---|
| v3a (cut 10/05 08:30 KST) | core 36 | 1,387 | 555 |
| v3b | core 36 | 350 | 176 |
| v4 | core 36 | 785 | 384 |
| v4 | ds200 | 1,120 | 586 |

**Protocol.** Pre-registered in `out/prereg.json` before any outcome-by-context number:
- 22 features, 63 bucket-vs-rest contrasts per run x tf x kind.
- Within-run differences, pooled n-weighted across runs.
- Time-block bootstrap (2h main, 4h sensitivity), with t at df = sum(G-1).
- Discover on v3a and test on v3b+v4; discover on v4 and test on v3a+v3b.
- BH within each family.
- 'Replicated' requires out-of-sample BH q<0.05 at 2h, plus p<0.05 at 4h, plus the same sign.

### 1. Cross-run replication

| family | discovery testable | discovery p<0.05 (about 5% by chance) | carried and tested OOS | OOS one-sided p<0.05 | OOS BH q<0.05 | replicated |
|---|---|---|---|---|---|---|
| A: v3a to v3b+v4, core, 15m+30m | 115 | 28 | 28 | 3 | 0 | 0 |
| B: v4 to v3a+v3b, core, 15m+30m | 108 | 7 | 7 | 1 | 1 | 1 (15m Europe session) |
| T: v3a core to v4 DeepSeek | 115 | 28 | 26 | 2 | 1 | 1 (15m middle of HTF box; fails on core v3b+v4) |
| secondary 1h (A / B / T) | 50 / 46 / 50 | 7 / 3 / 7 | 7 / 3 / 6 | 0 | 0 | 0 |

**Omnibus check.** The correlation of all contrast effects, v3a vs v4, against a null from circular time shifts:
- 15m: +0.09 (p 0.51).
- 30m: -0.09 (p 0.68).
- Sign agreement 59% against a null of 50-53%.

**Robustness.** The pattern is the same with winsorized R, win rate and gross R (`out/robust_directional.csv`).

### 2. Power: what this sample can detect

Median 80%-power minimum detectable difference for one bucket contrast (`out/power_by_scope.csv`):

| scope | 15m MDE80 (R) | 30m MDE80 (R) | days for 0.10 R | days for 0.04 R (5-year size) |
|---|---|---|---|---|
| core, all runs (4.6 days) | 0.28 | 0.24 | 36 / 26 | about 224 / 165 |
| core, v4 only | 0.63 | 0.47 | | |
| ds200, v4 | 0.48 | 0.42 | | |
| with about 60-test correction | 0.41 | 0.35 | | |

Time clustering is the reason: the v4 15m design effect is 7.4 at 1h blocks, 12.6 at 2h and 19.4 at 4h. Even the mechanical cost effect (wide vs tight stop, about +0.15 R) reaches only p 0.10 / 0.07 live.

### 3. What the 5-year data says about the live candidates

Within strategy x year x side, KST-day clusters (`out5y/fiveyear_within_strategy.csv`; extraction in `fiveyear_ctx.py` reuses `research/strategy_profiles._scan` at the v4 'normal' 30x/20x rule).

| contrast | live pooled 15m (R) | 5-year 15m (R) | 5-year 30m (R) | years with the same sign |
|---|---|---|---|---|
| Europe session 16-21 KST | -0.415 | -0.039 | -0.021 | 6/6, 5/6 |
| ADX >= 30 | +0.234 | +0.028 | +0.021 | 5/6 |
| middle of HTF box | -0.298 | -0.030 | -0.013 | 5/6, 4/6 |
| DI in trade direction | +0.273 (+0.03 within side) | +0.048 | +0.051 | 6/6 |
| box far edge (with the move) | +0.325 (+0.03 within side) | +0.057 | +0.044 | 5/6 |
| consensus >= 4 strategies | +0.173 | +0.006 | +0.014 | 4-5/6 |
| wide stop (cost share), R | +0.174 | +0.163 | +0.102 | 6/6 |
| wide stop, money (ROE) | | +0.003 | +0.006 | |

Family hypotheses, 5-year:
- Trend strategies in high ER: +0.044 / +0.024 R.
- Revert strategies in low ER: about 0.
- Revert at the 'cheap edge': -0.24 R at 15m, the opposite of the prediction.

Live versions (H1-H6) all fail BH: the smallest q is 0.29, and H6 goes the wrong way. Trend regimes were almost absent live: v4 had 0 HTF trend signals.

### 4. Can a filter be learned?

| learned filter (ridge on bucket dummies) | top-third uplift (R) | 95% CI | kept-third mean R | test mean R |
|---|---|---|---|---|
| all features, v3a to v3b+v4 core | -0.371 | -0.611..-0.144 | -0.509 | -0.138 |
| all features, v3a to v4 ds200 | -0.480 | -0.749..-0.199 | -0.568 | -0.088 |
| chart only, v3a to v3b+v4 core | +0.166 (null p 0.005) | -0.142..0.476 | +0.028 | -0.138 |
| chart only, v4 to v3a+v3b core | +0.113 (null p 0.045) | -0.017..0.234 | -0.194 | -0.307 |
| chart only minus momentum features | +0.06 / +0.09 / +0.00 (null p 0.27 / 0.15 / 0.37) | | | |
| 5-year IS to CF, 15m | +0.051 | 0.039..0.064 | -0.122 | -0.173 |
| 5-year IS to CF, 30m | +0.032 | 0.019..0.046 | -0.087 | -0.119 |
| live filter applied to 5 years (15m, by year) | +0.03..+0.06 | | -0.11..-0.17 | |

- **With side, coin or session as inputs,** the filter learns the run's market direction and loses money out of sample. Longs were +0.69 R in v3a and -0.90 R in v4.
- **The chart-only transfer** comes from 'trade with the short-term move', which is worth about +0.04 R over 5 years.
- **The 5-year IS filter** is dominated by stop width, i.e. cost.
- **Per strategy** (`out5y/fiveyear_filter_by_strategy.csv`), all 64 core cells stay below 0 after filtering. The closest is 30m N07_ICHI_CMO at -0.032 +/- 0.027.

### 5. Other checks

- **Side-flip by context** (v3b+v4): 0 of 216 contexts change direction skill after BH. Where a context matters, it hits both directions.
- **Quality tier** (drives 50x 'best'): best vs rest is +0.008 R at 15m (p 0.92) and +0.07 R at 30m (p 0.33).
- **S/R flags are nearly constant:** level_before_lock is 1 in 85-97% of signals and support_before_stop in 96-100%. The median room to the next level is about 0.3 ATR.
- **Per-strategy live scan:** 25 tests, 1 BH survivor (N18_VWMA_MACD 15m, low ER worse, +1.07 R). Over 5 years the same contrast is +0.03 R.
- **Europe session** is the only strict live survivor. It rests on 5 evenings (4 of 5 negative) and is -0.04 R over 5 years.

### Implications for the AI-trader plan

1. **Context-reading AI is not a source of edge** for these strategies at 15m/30m. The upper bound from the recorded chart features is about +0.03-0.06 R on the kept signals, against 0.16-0.22 R of round-trip cost. Choose AI-trader strategies only where there is independent evidence of direction or exit edge. This lens provides none.
2. **Do not let the AI learn from its own recent days.** Live effects were inflated 10-35x relative to 5 years, and direction-of-the-week learning lost 0.37-0.48 R out of sample. Weekly custom-value tuning of entry filters on a week of shadow data will fit noise. Any filter must be pre-registered and validated on the 5-year data first.
3. **Do not scale leverage by AI confidence or the quality tier.** Neither predicts outcome, so 20-50x by confidence only adds variance and liquidation risk.
4. **The one defensible context rule is cost-aware.** Prefer 30m (and 1h) to 15m, and skip or downsize entries whose 2 ATR stop is under about 0.5% of price. It reduces drag in R. The money gain is small.
5. **Soft tie-breakers only:** with-the-move entries (DI or box position in the trade direction, about +0.05 R), avoiding the middle of the HTF box (-0.03 R), and the 16-21 KST session at 15m (-0.04 R).
6. **Validation reality.** To confirm a 0.04 R filter live would take about 165-224 days of all-strategy signals; even a 0.10 R filter needs about 26-36 days. Nothing filter-related can be verified on paper by 12/31.