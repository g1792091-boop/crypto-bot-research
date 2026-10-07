## Lens: AI headroom — what human-like discretion could add (early exits, skips, switching, events)

### Bottom line
- **Exits: there is headroom on paper, but the simple discretionary rules did not capture it.** None of the 9 pre-declared rules passed the out-of-sample test (positive in both v3b and v4, and BH q < 0.05). The best was core 30m: cut at -0.5R (CUT05) gained +0.043R per signal, and exit-if-no-progress rules NP4 / NP8 gained +0.032 / +0.021R. These were positive in both runs but not significant, against a base of -0.146R. At 15m, every capture rule was negative or mixed.
- **Early profit-taking and breakeven moves, as a human trader would do them, cost R at 15m**: BE05 -0.06 to -0.08R, TP1 -0.06 to -0.10R. A 15m trader would need more than 45% precision on breakeven calls; the rule achieved 36%.
- **Switching cost about one extra round trip each time**, in every policy and both runs: core -$54 to -$102 per switch, DeepSeek -$28 to -$67, against about $63 for a round trip at 30x with margin = 30% of equity.
- **Missed or late entries perform like on-time ones.** They add trades at the same negative base value, each paying full cost.
- **Leverage changes the exits.** The ladder locks a fixed ROE, so higher leverage locks at a smaller price move. On the same signals, 40x vs 30x lost 0.10-0.14R. At 15m/30m, sizes above 30x are mostly rejected (stop too close to liquidation, or loss at stop above the 15% cap).
- **Headroom belongs to the timeframe, not the strategy.** Per-strategy headroom does not replicate across runs (Spearman about 0), and it is largest where entries were worst. Rank AI potential by timeframe, and choose strategies on entry evidence.

### Method (all numbers from code in `lens/ai_upside/`)
- **Every-signal replay.** Each SUBMITTED signal of v3b and v4 (4,748; reel and 5m excluded) runs alone through the repo's `PaperEngine` on 1m live_bars, with the run's own leverage rule, inferred funding and the inferred brackets. The base reproduces `replay_signals.csv` exactly (R difference 0.0 on 4,236 traded and 410 open-at-end signals).
- **Discretionary proxies.** Each rule is an engine subclass; `engine.py` is unchanged. Rules and tests were written in `PREREG.md` before any run. Already seen beforehand: the summary.md d3 variants (disclosed in PREREG.md).
- **Account-level switching.** Each account's own signal stream is re-simulated. The base reproduces all 366 accounts' trade counts and closed pnl (max difference $1.2e-10).
- **Uncertainty.** Clusters are run x bar close floored to max(timeframe, 1h). Tests use a sign-flip with one sign per cluster plus a cluster bootstrap; BH correction across rule x group cells.

### 1. Giveback and dead entries (every signal, base rules, v3b+v4)

"Gave back" = the trade reached +0.5R and still stopped out. "Dead losers" = losers whose MFE never passed +0.2R. The breakeven, dead-cut, total and exit-at-MFE columns are hindsight upper bounds in R per trade: perfect breakeven on losers that saw +0.5R, cutting dead losers at -0.5R, their sum, and exiting exactly at MFE.

| kind | tf | n | mean R | reach +0.5R | gave back +0.5R→SL | dead / losers | breakeven bound | dead-cut bound | total bound | exit-at-MFE bound |
|---|---|---|---|---|---|---|---|---|---|---|
| core | 15m | 1252 | -0.128 | 59.7% | 10.6% | 45.1% | 0.132 | 0.103 | **0.243** | 0.807 |
| core | 30m | 639 | -0.146 | 53.2% | 4.7% | 45.1% | 0.055 | 0.081 | **0.146** | 0.639 |
| core | 1h | 406 | -0.141 | 40.4% | 1.5% | 50.6% | 0.017 | 0.089 | **0.116** | 0.595 |
| core | 4h | 42 | +0.068 | 21.4% | 0% | 65.0% | 0 | 0.024 | 0.024 | 0.479 |
| ds200 | 15m | 1172 | -0.077 | 65.1% | 14.8% | 47.6% | 0.183 | 0.115 | **0.307** | 0.895 |
| ds200 | 30m | 620 | -0.142 | 55.6% | 5.5% | 54.9% | 0.065 | 0.116 | **0.192** | 0.724 |
| ds200 | 1h | 368 | -0.125 | 44.0% | 1.6% | 62.9% | 0.020 | 0.104 | 0.135 | 0.557 |

Source: `giveback_kind_tf.csv`.

- **Real trades, all three runs:** core 15m gave back +0.5R→SL in 8.3% of trades (n=630); DeepSeek 15m 17.4% (n=259).
- **Reached +1R but exited on the first 10% ROE rung:** v3a 15m 9.5% (50x tier walk), v3b 6.8%, v4 8.6%, DeepSeek 15m 15.1%. These trades kept +0.60..+0.80R of an MFE of 1.12..1.68R (`giveback_first_rung.csv`).
- **+1R then SL is almost absent (0-1.7%)** because the ROE ladder arms at about 0.86R (15m), 0.61R (30m) and 0.44R (1h) at 30x (`ladder_geometry.csv`).

### 2. Timing (bars of the signal's timeframe; `time_to_mfe_stop.csv`)

| kind | tf | reach +0.3R / median bars | reach +0.5R / median bars | reach +1R / median bars | median bars to SL | median bars, dead SL | SL trades peaked ≤ 2 bars |
|---|---|---|---|---|---|---|---|
| core | 15m | 73% / 1.3 | 60% / 2.8 | 23% / 5.7 | 5.9 | 3.7 | 62% |
| core | 30m | 71% / 1.4 | 53% / 3.0 | 8% / 2.8 | 5.9 | 4.1 | 63% |
| core | 1h | 70% / 1.5 | 38% / 3.1 | 8% / 3.0 | 5.0 | 3.7 | 77% |
| ds200 | 15m | 72% / 1.5 | 65% / 3.3 | 31% / 5.7 | 6.9 | 3.5 | 58% |
| ds200 | 30m | 68% / 1.4 | 56% / 2.6 | 15% / 3.3 | 5.1 | 3.2 | 70% |

Median MAE before reaching +0.5R is -0.26R. A 15m AI gets about 3-4 bar closes before a dead trade stops out.

### 3. Pre-declared discretionary-proxy rules: paired difference vs base (R per signal; `rules_stats.csv`)

| rule | core 15m (v3b / v4) | core 30m (v3b / v4) | core 1h (v3b / v4) | ds200 15m | ds200 30m | ds200 1h |
|---|---|---|---|---|---|---|
| BE05 breakeven after +0.5R | -0.058 (+0.076 / -0.120) | +0.012 (+0.015 / +0.010) | +0.005 (+0.011 / +0.002) | -0.082 | -0.020 | +0.012 |
| BE10 breakeven after +1R | -0.012 | 0 | 0 | -0.002 | 0 | 0 |
| NP4 no +0.3R in 4 bars → exit | +0.000 (+0.031 / -0.014) | **+0.032 (+0.053 / +0.022)** | -0.003 | -0.022 | -0.004 | -0.004 |
| NP8 no +0.3R in 8 bars → exit | -0.024 | **+0.021 (+0.031 / +0.016)** | -0.008 | -0.031 | -0.002 | +0.000 |
| TP1 take-profit at +1R (ladder kept) | -0.063 (+0.027 / -0.104) | -0.020 | +0.004 (both +) | -0.095 | -0.045 | +0.010 |
| PART1 half off at +1R | -0.031 | -0.010 | +0.002 | -0.048 | -0.022 | +0.005 |
| CUT05 hard stop at -0.5R | -0.011 (+0.119 / -0.070) | **+0.043 (+0.082 / +0.025)**, CI -0.02..+0.10 | +0.034 (+0.163 / -0.018) | -0.017 | +0.044 | +0.032 |
| OPP exit on own opposite signal | -0.006 | +0.008 (both +), p 0.035 | -0.006 | -0.045 | -0.006 | -0.005 |
| OPPH same, same or higher tf | -0.022 | -0.006 | -0.006 | **-0.061 (q 0.029)** | -0.016 | -0.004 |

- Base mean R for these groups: core 15m -0.128, 30m -0.146, 1h -0.141; DeepSeek 15m -0.077, 30m -0.142, 1h -0.125. DeepSeek columns are v4 only.
- No cell passes the pre-registered test. The only BH-significant cell is a loss: DeepSeek 15m, exit on own opposite signal at the same or a higher tf.
- Pooled 15m across kinds, exit on own opposite signal: same tf -0.025R, same-or-higher tf -0.041R, both p 0.004 (v4-driven).
- Excluding open-at-end trades changes nothing material (core 30m CUT05 becomes +0.054).

**Why the rules fail (`rule_tradeoff.csv`).**
- Core 15m BE05 saved 138 trades (+1.24R each) and killed 245 (-0.99R each). Break-even needs 44.6% of changed trades to be saved; actual 36.0%.
- TP1 at 15m: needs 74.2%, actual 58.3%.
- CUT05 at 15m: needs 74.6%, actual 73.6%. At 30m: needs 69.1%, actual 74.6%, so it helps a little.

### 4. What the AI sees at its decision points: hold minus exit-now (R; `disposition.csv`, `exit_now_by_state.csv`)

| state | bars after entry | tf | n | hold - exit (95% CI) | v3b | v4 |
|---|---|---|---|---|---|---|
| winning ≥ +0.3R | 2 | 15m | 334 | +0.187 (-0.07..+0.40) | +0.183 | +0.187 |
| winning ≥ +0.3R | 2 | 30m | 101 | +0.033 | -0.027 | +0.041 |
| deep loser ≤ -0.5R | 4 | 15m | 202 | +0.122 (-0.09..+0.40) | -0.154 | +0.166 |
| deep loser ≤ -0.5R | 4 | 30m | 74 | **-0.220 (-0.32..-0.08)** | -0.242 | -0.216 |
| deep loser ≤ -0.5R | 4 | 1h | 58 | **-0.287 (-0.38..-0.19)** | -0.351 | -0.272 |

- **Holding winners beats taking early profit at 15m.** That is the opposite of the human disposition habit.
- **At 30m/1h, cutting trades that are deep under water after 4 bars helped in both runs and both kinds.** This was found after the fact, in a scan with BH q 0.32, so it is a candidate for a code shadow, not a confirmed rule.
- **No other state cell is BH-significant**, and the 15m all-state value flips sign between runs (v3b -0.17, v4 +0.22). Whether early exits help is set by the run's regime, not by a repeatable state rule.

### 5. Switching (account-level re-simulation; `switch_summary.csv`, `skipped_vs_held.csv`)

| policy | core 15m $/switch (n) | core 30m | core 1h | core by run (v3b / v4) | ds200 all tf | mean R of the closed-early trades |
|---|---|---|---|---|---|---|
| switch on every new signal | -54 (590) | -73 (257) | -102 (140) | -50 / -71 | -38 (940) | -0.21 |
| switch only when under water | -64 (388) | -86 (175) | -119 (105) | -37 / -91 | -40 (644) | -0.33 |
| switch only stale trades (≥ 4 bars, never +0.3R) | -66 (62) | -60 (35) | -96 (15) | +69 (17) / -96 (97) | +3 (122) | -0.46 |
| switch on same-coin reversal | -267 (17) | +238 (6) | -778 (3) | -444 / -85 | -98 (58) | -0.56 |

- **Signal-level check:** switching to the skipped signal changed equity by -2.07% per instance for core (n=1,296, CI -2.69..-1.45); by -2.68% when the held trade was under water (n=691); DeepSeek -0.67% (n=1,219).
- **v3a nightly skipped shadows:** signals skipped while in position averaged ROE -0.079, against -0.037 for entered trades (15m).

### 6. Late entries and leverage (`late_lev_summary.csv`, `lev_pairs.csv`)

- **Missed signal entered 1 bar late:** core 15m -0.026R (v3b +0.047 / v4 -0.059), core 30m -0.045, core 1h +0.043, DeepSeek 15m -0.082 (CI -0.159..-0.008). Four bars late: core 15m -0.115, DeepSeek 15m -0.151.
- **Same signals at fixed leverage (margin = leverage %):**
  - 30x vs 20x: -0.026 (core 15m), -0.045 (30m), -0.046 (1h).
  - 40x vs 30x: -0.104 (core 15m), -0.109 (DeepSeek 15m), -0.135 (DeepSeek 30m).
  - Feasibility: 40x rejected 276 of 1,252 core 15m signals; 50x was possible for only 179; at 30m/1h, 40x+ is almost never possible.
  - Loss at the stop: at 15m it is 6.9% of equity at 30x and 19.1% at 50x.

### 7. Events and big-move hours (`events_*.csv`)

- **Scheduled events:** only one macro event fell inside the runs, NFP 10/02 21:30 KST (v3a).
  - Trades entered within 2h of it: -0.09R (n=163). Trades held through the release: +0.48R (n=37). Other v3a trades: -0.45R.
- **Big-move hours:** the top decile of the 6-coin 1h return. In v4 these were 4 hours on 10/07 (3 down).
  - Entries in a big-move hour: +0.31R (core, n=253). In the hour after: +0.19R. Other hours: -0.14R.
  - v3b: -0.23 / -0.41 / -0.33.
- **Positions open at the end of a big-move hour:**
  - Against the move: holding was worse than exiting by 0.13-0.36R.
  - With the move: holding was better by 0.15-0.78R.
  - Only 3-5 clusters, so this is an anecdote.

### 8. Skip headroom from cross-strategy agreement (`agreement.csv`)

Signals counted only in the 15 min before entry, which the AI can see. Conflict minus agree:
- core 15m -0.02R (CI -0.31..+0.24)
- core 30m -0.15R (CI -0.38..+0.07)
- core 1h +0.05R
- DeepSeek 15m -0.16R (CI -0.52..+0.17)

v3b shows no difference. A version that also counts signals up to 15 min after entry inflates the 15m effect to -0.13R; it leaks the future and shows how easily an AI evaluation can find a false skip edge.

### 9. Ranking

**By timeframe:**
1. **30m:** small but consistent exit improvements, about +0.03-0.05R per signal, or roughly +0.1-0.16R per account-day at 2.3-3.8 trades/day. The base loses about 0.4-0.55R per day.
2. **1h:** similar, through the loss-cut, but it is planned as a rule account.
3. **15m:** the most hindsight room (0.24-0.31R) and nothing that captures it. Costs are 0.22R per round trip; early profit-taking and breakeven moves are harmful.
4. **4h:** too few signals.

**By strategy:** the per-cell grades in strategy_notes are descriptive only.
- Hindsight headroom does not replicate between runs: Spearman -0.07 at 15m and +0.24 at 30m (v3b vs v4); -0.31 and -0.52 (v3a trades vs v4 signals).
- Rule gains correlate with the cell's base R at -0.52 to -0.87.
- The core cells whose base was ≥ 0 in both runs (N10_HA_PSAR@15m, N17_KC_RSI@15m, N20_EMA9_CHOP@30m, N24_DMI@30m) have little exit headroom (0.08-0.27R) and no rule gain in both runs.
- The cells with the most "capturable" headroom (N12_ICHI_AO@15m, N18_VWMA_MACD@30m, F4_PULL, F16_FIB382, F8_VWICK, F11_TSOUP) are the ones whose entries lost.

### 10. Implications for the AI design
1. **Choose AI strategies and timeframes on entry and skip evidence (other lenses), not on exit headroom.** Prefer 30m over 15m for AI traders.
2. **Keep exits in code (the ladder).** Shadow-test two rules as code before any AI is credited with them:
   - 30m/1h: exit if ≤ -0.5R after 4 bars.
   - 30m: CUT05.
3. **Give the AI three explicit restrictions:**
   - At 15m, no early profit-taking or breakeven moves below the ladder's first rung.
   - No switching unless the expected gain exceeds one round trip (about 0.22R at 15m, about 1.3% of equity at 30x).
   - No exits or reversals on the strategy's own opposite signal.
4. **Define the code exits in R, not ROE,** so that 20-50x leverage by confidence does not silently tighten them. Expect 40-50x to be infeasible for most 15m/30m signals under the 2 ATR stop and the 15% cap.
5. **Measure every AI action against paired twin code accounts.** The headroom here is a hindsight ceiling, not an expected value.