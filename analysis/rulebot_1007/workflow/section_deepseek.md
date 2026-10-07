## DeepSeek 44 definitions (ds200, paper v4): evidence cards and AI-trader verdict

**Question.** Which of the 44 DeepSeek definitions (171 accounts at 15m/30m/1h/4h; the F15 ET-session definitions run only at 15m/30m/1h) deserve a dedicated AI trader that enters on 15m/30m signals?

**Answer.** None, on the evidence. Keep all 44 as cost-free rule accounts. If the owners want DeepSeek represented anyway, give at most one or two exploratory family traders (F6 VWAP, then F9 FVG), outside the 12/31 candidate set.

### Data and method
- **Accounts.** v4 ds200 trades: `trades_enriched.csv` / `account_stats.csv`. 563 trades, -$37,091, mean R -0.201. 141 of 171 accounts traded; 20 had no signal; 7 had positions still open at the end. Median 3 trades per account.
- **Every-signal replay.** All 2,286 SUBMITTED ds200 signals were run alone through the repo engine on `live_bars` (`replay_signals.csv`): 2,087 traded, 140 still open (marked to the last close in a sensitivity), 59 rejected by sizing (all 4h). The replay matches the real trades exactly.
- **Uncertainty.** Cluster-robust t intervals with G-1 df. Clusters are the signal bar floored to max(tf, 1h), with 4h blocks as a sensitivity. BH at 10% runs over the 61 *testable* cells (>=10 replayed trades and >=8 clusters).
- **Direction checks.** Side-balanced R is the mean of the long and short means. R vs peers is R minus the mean R of other strategies' signals with the same tf, side and 4h block. The half split is at the run midpoint, 10/06 21:37 KST.
- **Side-flip.** From the pipeline, plus a drift-neutral version (`sideflip_drift.py`).
- **5-year.** `research/deepseek200/out/results.csv`: both PREREG exits, periods 1/2/3, gross, stage flags. The live signal code hash (lib_c.py 3210c602...) equals the 5-year code hash.
- **Duplicates.** Signal-level overlap of every definition pair at the same tf, and the same definition across tfs (`dup_pairs_ds.csv`).
- **Extra replay.** Every ds200 signal at fixed 10/20/30/40/50x with margin = leverage % (`levreplay.py`). Parity at 30x is exact on 1,996 signals.
- **Outputs.** `cards_deepseek.csv` (171 rows, 194 columns) with grades A/W/C/D/X/N from `grade.py` (rules in its docstring). Family tables: `family_tf.csv`, `family_verdict.csv`.

### 1. Timeframe level: the costs decide
| tf | replayed n | mean R [95% cluster CI] | 4h-block CI | gross R | fees+funding R | slippage R | net %/trade (notional) | median stop % | 5y net P1 / P2 (%/trade) | 5y gross P1 |
|---|---|---|---|---|---|---|---|---|---|---|
| 15m | 1120 | **-0.065** [-0.21, +0.08] | [-0.36, +0.23] | +0.18 | 0.177 | 0.071 | -0.061 | 0.60 | -0.151 / -0.141 | -0.047 |
| 30m | 586 | **-0.132** [-0.26, -0.01] | [-0.28, +0.02] | +0.04 | 0.122 | 0.049 | -0.115 | 0.85 | -0.160 / -0.149 | -0.053 |
| 1h | 330 | -0.112 [-0.23, +0.00] | [-0.19, -0.03] | +0.01 | 0.086 | 0.034 | -0.150 | 1.23 | -0.193 / -0.170 | -0.078 |
| 4h | 51 | -0.122 [-0.59, +0.35] | same | -0.05 | 0.049 | 0.019 | -0.233 | 1.96 | -0.242 / -0.154 | -0.079 |

- In this window the 15m signals were gross-positive, but 0.25R of costs per trade turned them negative.
- In the 5-year, the gross before costs is already negative at every tf.
- The live net % per trade has the same size as the 5-year net (about -0.15%).
- For reference, the core 36 in the same run had replay mean R of 15m -0.025 and 30m -0.118. Side-balanced: ds200 15m -0.09 vs core -0.16.

### 2. Why the per-definition live ranking cannot be used
The v4 window is one directional move.

| ds200 replay, mean R (n) | first half: longs | first half: shorts | second half: longs | second half: shorts |
|---|---|---|---|---|
| 15m | -0.37 (296) | -0.20 (350) | -0.86 (234) | **+1.27 (240)** |
| 30m | -0.17 (172) | -0.30 (166) | -0.90 (124) | **+0.91 (124)** |

- **Long share explains the result.** Across the 51 testable 15m/30m cells, long share vs mean R has Spearman -0.45 (p 0.0008).
- **The ranking flips between halves.** Cell mean R in the first half vs the second half: Spearman **-0.59** at 15m (p<0.001) and -0.41 at 30m.
- **Account PnL is noisier still.** Account vs replay mean R: Spearman 0.42 (15m), 0.65 (30m). 52 accounts were profitable, and 27 of them lose the profit without their best trade.
- **Examples.** F12_MSS@15m is 3rd on the leaderboard (+$1,229, 4 trades) but its replay is -0.10R (n24). F3_HHHL@15m account is -$1,715, but its replay is +0.20R (n41); that +0.20R is itself only shorts in the drop (side-balanced -0.15).

### 3. Multiple testing and the 5-year line
- **Live.** 0 of 61 testable cells have BH q<=0.10 for mean R>0. The lowest raw p is 0.137 (F16_FIB500@15m +0.29R, n13).
- **Significantly negative after BH:** F4_PULL@15m -0.59R (CI [-0.95,-0.23], q 0.035; both sides negative) and F4_PULL@30m -1.00R (q 0.0001; 20/20 longs during the drop).
- **5-year.** All 88 definition x tf cells at 15m/30m are negative under both exits. The best are F15_OPEN0930 (-0.083% at 15m, -0.076% at 30m).
- **The only positive 5-year means** are 9 rare 1h/4h cells: F4_PULL_RSI@4h +0.334%, F1_PVT_DIV@4h +0.265%, F5_BOX_RSI@1h +0.139%, F1_RSI_DIV@4h +0.104%, F10_M2022@4h +0.101%, F1_MOM_DIV@4h +0.088%, F12_MSS_DISP@4h +0.084%, F4_PULL@4h +0.031%, F5_BOX@1h +0.010%. None passed the gates.
- **The 5-year ranking itself does not persist.** Period-1 vs period-2 Spearman across definitions: 15m -0.14, 30m -0.15. Live vs 5-year: 15m +0.02, 30m +0.33 (n.s.).
- **Side-flip.** 15m excess +0.073R (p 0.024), but drift-neutral +0.049R (p 0.08). 30m -0.028 (drift-neutral -0.023). All timeframes +0.032 (drift-neutral +0.028, p 0.17).

**Stage-1 disagreement (reported, not resolved).** Both versions agree on stage 2 = 0, BH = 0 and candidates = 0, and all four rows are 4h.

| source | named stage-1 rows | their numbers (P1 / P2 / P3 %/trade) |
|---|---|---|
| `results.csv` (also `per_family.csv`) | 4h F5_BOX X2; 4h F13_FVG_PD X5 | +0.057/-0.413/+0.859; +0.202/-0.532/+0.617 |
| `RESULTS_DEEPSEEK200.md` | 4h F1_RSI_DIV X2; 4h F10_M2022 X5 | +0.045/+0.183/+0.456; +0.058/+0.155/+0.027 |

In results.csv, the md's two rows carry all3_positive=True and stage1=False. Their own fields: F1_RSI_DIV period-1 second half is -0.33%; F10_M2022 has 2 of 6 coins positive. `near_miss.csv` lists them as all_three_periods_positive.

### 4. Families at 15m/30m (unique signals, cluster CI)
| family | 15m n / mean R [CI] | 30m n / mean R [CI] | 15m drift-neutral side-flip | 5y 15m P1/P2/P3 (%) | unique sig/day 15m | verdict |
|---|---|---|---|---|---|---|
| F1 divergence | 38 / +0.24 [-0.44,+0.93] | 14 / +0.07 | +0.28 | -0.141/-0.159/-0.206 | 25 | C; 5-year support only at 4h (rule account) |
| F2 DeMark | 34 / -0.12 | 27 / -0.10 | +0.22 | -0.167/-0.129/-0.251 | 23 | C |
| F3 structure | 78 / +0.06 | 38 / -0.21 | -0.06 | -0.169/-0.154/-0.163 | 52 | C (HHHL positive only via shorts) |
| F4 EMA pullback | 82 / **-0.34** [-0.73,+0.05] | 38 / **-0.48** [-0.90,-0.05] | -0.21 | -0.135/-0.131/-0.129 | 55 | D at 15m/30m (F4_PULL) |
| F5 box | 10 / +0.08 | 4 / +0.04 | +0.26 | -0.128/-0.162/-0.080 | 7 | too rare; keep F5_BOX only |
| F6 VWAP | 114 / +0.08 [-0.45,+0.61] | 86 / -0.13 | +0.14 | -0.142/-0.119/-0.096 | 76 | C; exploratory option 1 |
| F7 range filter | 90 / +0.06 | 44 / +0.16 | +0.18 | -0.161/-0.132/-0.213 | 60 | C (side-balanced negative) |
| F8 virgin wick | 15 / -0.32 | 5 / -0.14 | -0.14 | -0.144/-0.131/-0.111 | 10 | C |
| F9 FVG/OB | 108 / -0.01 [-0.36,+0.35] | 42 / -0.07 | +0.13 | -0.156/-0.132/-0.175 | 72 | C; F9_IFVG@15m = W; exploratory option 2 |
| F10 ICT | 26 / -0.10 | 15 / -0.30 | +0.07 | -0.165/-0.124/-0.115 | 17 | C |
| F11 sweep | 45 / -0.15 | 28 / -0.25 | -0.03 | -0.145/-0.154/-0.195 | 30 | D/C |
| F12 MSS | 24 / -0.10 | 15 / +0.35 [-0.38,+1.08] | +0.22 | -0.171/-0.149/-0.227 | 16 | D at 15m, C at 30m |
| F13 prem/disc | 43 / -0.07 | 19 / -0.35 | +0.05 | -0.134/-0.157/-0.126 | 29 | merged into F9/F11 |
| F14 SMT | 112 / -0.14 [-0.44,+0.17] | 39 / -0.29 | -0.03 | -0.105/-0.161/-0.012 | 74 | C at 15m, D at 30m |
| F15 sessions | 43 / -0.06 | 39 / +0.08 | +0.03 | -0.160/-0.154/-0.167 | 29 | daily events; untestable in 1.5 days |
| F16 Fibonacci | 49 / -0.19 | 33 / -0.03 | -0.04 | -0.166/-0.118/-0.140 | 33 | C/D |
| F17 Z-score | 50 / -0.21 | 26 / -0.07 | -0.02 | -0.131/-0.151/-0.123 | 33 | C |

### 5. Duplicates: keep the parent
| merged (child) | kept | live evidence |
|---|---|---|
| F5_BOX_HTF | F5_BOX | identical at 15m (10/10) and 30m (4/4) |
| F13_RAID_PD, F11_TSOUP | F11_RAID | 36/38 at 15m, identical at 1h/4h; TSOUP 22/25 shared at 15m |
| F17_Z_HL | F17_Z | 47/50 at 15m, identical at 1h/4h |
| F12_MSS_DISP | F12_MSS | 12/12 at 15m inside MSS |
| F13_FVG_PD, F10_M2022 | F9_FVG | 9/9 and 3/3 inside FVG at 15m |
| F16_FIB618 | F10_OTE | 14/14 at 15m, identical at 4h |
| F7_RF_ONLY | F7_RF_TRIPLE | 75% shared at 15m/30m |
| F15_OPEN0000@30m/1h | F15_OPEN0000@15m | the same 12 signals at all three tfs (only the stop differs) |
| F15_OPEN0930@30m | F15_OPEN0930@15m | identical 6/6 |

The 44 definitions are about 35 distinct streams. The three F1 divergences overlap 60-80% and should be one trader if any. Child filters are not reliably better in the 5-year, so expose them to the AI as context, not as traders.

### 6. Grades (`cards_deepseek.csv`)
| tf | A | W | C | D | X | N |
|---|---|---|---|---|---|---|
| 15m | 0 | 1 (F9_IFVG) | 26 | 6 | 8 | 3 |
| 30m | 0 | 0 | 23 | 7 | 8 | 6 |
| 1h | 0 | 1 (F6_VWAP_CROSS) | 16 | 5 | 5 | 17 |
| 4h | 0 | 0 | 4 | 0 | 0 | 35 |

- **W cells.** Both are thin: F9_IFVG@15m +0.06R (n26, CI [-0.38,+0.49]); F6_VWAP_CROSS@1h +0.15R (n34, CI [-0.13,+0.43]).
- **Near-W at 15m/30m** (all W conditions except a 5-year rank just below the median): F16_FIB500@15m, F12_MSS@30m, F9_BREAKER@30m.

### 7. Exits and leverage (house rules)
| tf | entered share at 10/20/30/40/50x | mean R at 10x / 20x / 30x / 40x (incl. marked) | 10x vs 30x, longs | 10x vs 30x, shorts |
|---|---|---|---|---|
| 15m | 100/100/100/90/21% | +0.03 / -0.07 / -0.08 / -0.20 | -0.89 vs -0.55 | +0.84 vs +0.35 |
| 30m | 100/100/99.7/40/0% | -0.04 / -0.12 / -0.14 / -0.23 | -0.82 vs -0.45 | +0.74 vs +0.17 |
| 1h | 100/100/83/0/0% | +0.02 / -0.08 / -0.14 / n/a | | |

- **Mechanism.** The ROE ladder's first lock triggers at +12% ROE, which is 0.12/L of price: about 0.9R at 15m at 30x, about 2.2R at 10x. Higher leverage therefore means an earlier profit lock. In this trending window a later lock was better, also side-balanced (+0.08R at 15m, +0.10R at 30m).
- **Feasibility.** With margin = leverage %, 50x cannot take most 15m signals or any 30m DeepSeek signal (rejections: loss above 15% of equity, bracket, liquidation buffer).
- **Nightly d3 what-ifs** (biased, resolved pairs only): tp1R +0.08R and stopw3 +0.05R at 15m; lock30 -0.17R; tp2R -0.08R; tp3R -0.26R.
- **Limit entry** (0.25 ATR, 10/06 only): fills 65% / 58%. Fills are the would-be losers and misses the runaway winners. Net per signal: +0.015R at 15m, +0.008R at 30m.

### 8. What this means for the AI plan
1. **No DeepSeek AI trader in the judged cohort.** The AI would need to add about +0.25R/trade at 15m (+0.17R at 30m) just to cover costs. No rule-level evidence (live replay, side-flip, 5-year) shows a starting edge.
2. **If there is an exploratory slot**, use one family trader with deduplicated streams, Sonnet only: F6 VWAP first, then F9 FVG/IFVG/OB/Breaker. Never F4, the F11/F13 raids, F14_SMT, F16 or F17.
3. **Keep the 4h F1 divergence group, F4_PULL_RSI@4h, F10_M2022@4h and F5_BOX_RSI@1h as rule accounts.** They are the only places the 5-year leaves room, and they fire 0 to 0.7 times per day.
4. **Exits in price/R, not ROE.** Confidence should scale risk per stop (design 4-3), not leverage. Otherwise "50x when confident" silently means "take profit sooner", and most 15m/30m signals cannot be sized at 50x anyway.
5. **Evaluate on every-signal shadow books and paired AI-vs-rule R on the same signals.** At this noise level (sd 1.0-1.4R per trade, median per-cell MDE about 0.7R now), +0.1R per cell needs about 900-1,400 signals (about 80 days). Only effects of about 0.2R or more can be seen by the November promotion.

### What the data cannot tell
Whether any definition has an edge in another regime. Whether AI discretion adds value. Whether the "later lock" effect generalises. Which stage-1 list in the 5-year documents is the intended one.