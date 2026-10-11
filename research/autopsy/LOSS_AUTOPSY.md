# Loss autopsy: synthesis (select period only)

Scope. The 36 rule-bot core strategies, default numbers, six coins, 15m/30m/1h/4h. Every new number comes from signals whose signal-bar close is in **SEL = 2021-01-01 .. 2024-01-01**. Each finding was re-derived by an independent check (the "skeptic" folders under `scratchpad/autopsy/`). Numbers taken from earlier repo reports are marked with their period: TEST = 2024-01..2026-09, X20 = 2020, 5Y = 2021-03/08..2026-09 (includes TEST), LIVE = Oct-2026 paper runs. Units: "%/trade" = % of a $5,000 wallet per trade at the house normal size (about 7x notional). "R" = per unit of risk; at the hunt's r = 0.5%, 0.1R = 0.05% of equity. DeepSeek appears only as counts and shares (D11).

The early-entry study (`scratchpad/earlyentry/tables.md`, SEL, trend class) has finished, and it agrees with this autopsy (section 4).

---

## 0. Bottom line

1. Four causes explain the loss. (1) The entries have no direction skill. (2) Costs at the house notional are the whole loss. (3) The house sizing leads to ruin. (4) The ROE ladder exit is tight. The trend-hunt machine already fixes (2)-(4). No rule can fix (1).
2. Every other problem that survived verification is small: at most about 0.1-0.3%/trade at house size on the affected trades, at most about 0.05R averaged. Stacked together they are still an in-sample upper bound: house 15m goes from -1.04 to -0.92%/trade. **No set of filters turns a losing strategy into a winning one.**
3. Only three new items are worth pre-registering, plus one extra control:
   - a weekend option
   - an FOMC/NFP blackout
   - a same-side risk limit
   - a momentum-at-the-pick's-times control

   All are machine-level (the same for every system) and are **reads on the fixed picks**, not selection rules. One optional search-space change (drop 15m) is for the owners to decide.
4. Expectations must come down. Several "good" SEL numbers came from the calm subset that house sizing could take. 4h tp3R|4 is +0.23R on 908 sized signals but +0.01R on all 41,103.

---

## 1. Ranked real problems (confirmed or clearly supported)

| # | Problem | Size (SEL unless marked) | Grade | Fix | Already in the hunt? |
|---|---|---|---|---|---|
| 1 | **No direction skill.** The chosen side is a coin flip. The small skill the trend class shows equals plain 20-bar momentum on the same bars. | House side skill +0.008%/trade [-0.03, +0.05]; the chosen side beats the flip in 50.0% of trades; gross before costs +0.003R. Trend skill +0.052 vs mom20 on the same bars +0.051 (diff +0.001 [-0.04, +0.04]). Same picture in TEST/X20/5Y/LIVE (earlier reports). | strong, replicated | none by rule (section 3) | n/a. R6 (e), random-time momentum side, exists as a read; see O4. |
| 2 | **Costs at the house notional are the whole loss.** | Cost 1.08 / 0.92 / 0.77 / 0.62 %/trade (0.158 / 0.114 / 0.088 / 0.065R) for 15m / 30m / 1h / 4h, against gross +0.04 / -0.02 / +0.02 / +0.28. Strategies whose gross covers cost: 0/34, 0/34, 3/33, 7/26. | strong (known B) | Fixed-risk sizing (loss per trade 6-19x smaller at the same R); fewer, longer-bar trades | **Yes**: H 7.2-7.3 (r = 0.5%, lev ≤ 20), v1 on 1h/4h. Hunt-wide's 15m/30m still pay 0.11-0.16R (O6). |
| 3 | **House sizing leads to ruin.** | SEL house accounts bust 30/34 (15m), 28/34 (30m), 24/34 (1h); random placebo the same. 5Y (incl. TEST): 91/144 cells bust under the v4 rule vs 15/144 at 0.5% risk. | strong, structural | fixed-risk sizing | **Yes**: H 7.2-7.3, H 8 total open risk ≤ 4% |
| 4 | **ROE ladder exit**: small winners, needs about 73% wins. | Lock exits median +0.43R; win 64.8% vs break-even 72.8%; net -0.135R/trade. Chandelier k5 -0.107R (random -0.114R). The gain over the ladder is the same for random entries, so it is market structure. | strong | ATR trailing, no TP | **Yes**: H 7.5 chandelier 3 ATR. R5 reads 2 / 4.5 ATR and D0 ×1.5 (= 3 ATR on 15m-1h). |
| 5 | **Same-side exposure across correlated coins** (risk, not the mean) | Same-side pair outcome correlation +0.46..+0.51 (random-time same-side pairs 0.45-0.50, so the market's own co-movement). 5-6 coins on one side all lose 13.5% vs 0.5% if independent. The 5th percentile of a cluster's sum is -55% of one wallet. Cross-coin part of daily SD 1.25x; mean unchanged. | strong | same-side risk limit + stress line | **Partly**: H 8 = 6 positions, 3L/3S in the large group only, 4% total. Six same-side positions ≈ 1.7 independent bets. New **O3**. |
| 6 | **Inflated SEL expectations** (house sizing refuses volatile bars, so earlier tables describe a calm subset) | Refused at 2 ATR: 6.5 / 15.7 / 35.7 / 86.4%; at 4 ATR: 23 / 46 / 73 / 98%. 4h tp3R\|4 sized +0.232R (908 signals, 778 in 2023) vs all signals +0.010R [-0.09, +0.11]. 1h +0.052 vs +0.028R. G1 gate at 1h: sized +0.149R vs all signals +0.074R [-0.05, +0.21]; 15m +0.071 [+0.00, +0.15]. | strong (refusals match the tables exactly) | read all-signal, size-free numbers | **Yes**: hunt sizing takes almost everything. The prior expectations quoted in the design must be restated (section 2.1). |
| 7 | **Weekend entries in the trend/momentum direction** (Sat-Sun UTC) | Trend class at house exit: weekend -1.18 vs weekday -0.85%/trade. DiD -0.33 vs a side-mix control; -0.20 (p = .008) after matching on with/against the 20-bar move. A plain 20-bar-momentum rule on all bars shows -0.29 / -0.40 / -0.31 (15m / 30m / 1h); no effect at 4h. Far-target exits: mostly weekend **longs**. Chandelier at 1h/4h: -0.04..-0.07R, not significant. Skip effect, core house: 15m -1.04 → -0.99, 1h -0.75 → -0.70. | confirmed; about half is a market property | weekend skip, 15m-1h | **No**. New **O1** (read). |
| 8 | **Trend entries in the 2h before FOMC** (NFP weaker) | FOMC, live size: 15m -3.07, 30m -3.19, 1h -2.67 %/trade (diff about -2). 21/24 events negative. Shifted placebo calendars give no effect. NFP comes mostly from 2023 and is absent at 1h; CPI/PCE none. The "other" class is also hit. No effect at 4 ATR + 3R. Affects about 1% of trades, so about +0.01%/trade on average. | confirmed (FOMC) | 120-min blackout | **No**. New **O2** (read). |
| 9 | **N17_KC_RSI bets against continuation** (not the whole reversion class) | Side skill -0.26 / -0.33 / -0.35 %/trade (15m / 30m / 1h; BH-significant at 15m/30m); -0.057R vs flip. Without N17 the reversion class is -0.004 [-0.07, +0.07]. The flipped version still loses at house size (-0.58%). | confirmed for N17 only | none; let selection drop it | Selection (eligibility) almost surely drops it. Label it (**O5**). |
| 10 | **Repeat firing of state arrays** (N17, N18) | First bar only: +0.027%/trade pooled, +0.086 reversion, +0.07 N18 (house). | confirmed, small | first bar only | **Yes**: W 3.2 edge rule + H 8 one position per coin |
| 11 | **Funding on long holds** | Size-free tp3R\|4: longs pay 0.039 / 0.074R per trade at 1h / 4h (2021: 0.083 / 0.150R). On the house-sizable subset 0.031 / 0.046R. All bars the same, so a market property. | confirmed | charge it; report by side | **Yes**: H 2 / H 7.6 charge it; R9 reports funding by side and year |

House rule bot only (not the hunt):

| Problem | Size (SEL) | Fix | Status |
|---|---|---|---|
| "Best" tier (40-50x on strength quintile ≥ 4) adds cost, no gross | Flagged 15m trades -0.29%/trade; pooled live sizing vs all-normal -0.067 (15m) | drop the tier | **Second check unfinished** (only the flag share, 23-24%, reproduced) |
| Ladder lock exits are stop-market (taker + slippage) | A fixed 10%-ROE limit TP beats the ladder by +0.20%/trade; random and flip gain the same (fee mechanics) | swap the ladder for a fixed limit TP | confirmed. No timeframe turns positive (best 4h -0.22). |
| Alt reversion trades against a BTC 4h move > 1.5% | Reversion DiD -0.24%/trade; mostly 2021Q3-2022Q3; 2023 raw sign flips | for a future reversion module only: "alt's own dip AND BTC against" | confirmed, regime-dependent |

---

## 2. Fixes

### 2.1 Already covered by the trend-hunt machine (PREREG_HUNT / PREREG_HUNT_WIDE)

| Problem | Hunt part that covers it |
|---|---|
| Costs per wallet, ruin, liquidation, best tier | H 7.2 risk unit (r = 0.5%), H 7.3 leverage ≤ 20 and liquidation ≥ 1.5 × D0, H 8 total open risk ≤ 4% |
| Tight ROE exit | H 7.5 chandelier 3 × ATR14, no TP. R5 reads 2 / 4.5 ATR, adds 0/3, and D0 ×0.75 / ×1.5. This covers the autopsy's "k5 arm" and "3 ATR first stop, cost-only arm"; nothing new is needed. |
| Repeat firing | W 3.2 edge rule (True on t, False on t-1) + H 8 (one position per coin) |
| G1 expectations | G1 and NONE are separate systems (W 2). R6 (c) gated random times. R20 G1-dir. The design's G1 rationale cites the sized-subset gate numbers: restate them as about +0.07R at 15m-1h and +0.03..0.08R at 4h, all-signal SEL, with CIs mostly including 0. |
| Funding by side | H 2 / H 7.6 charge it; R9 cost anatomy has funding by side and year |
| Fill timing | H 7.1 next 5m open; R9 fills at the 2nd/4th 5m bar (the SEL drift is < 1 bp, negligible) |
| Selection luck / SEL flattery | R4 (CSCV/PBO, null of the max with (a)/(b) twins), R22 sealed post-verdict read, BH per batch |
| Momentum explains the pick | R6 (e) random-time momentum side (read). Sharpened by O4. |
| All open positions stopped at once | R10 instant loss if every open position gaps 5/10/20% through its stop. O3 adds a same-side version. |

### 2.2 New pre-registrable options (machine-level, numbers fixed before the pin)

None of these chooses a system or changes P0-P4, BH, PASS or the lineup. O1-O3 are run as **one extra machine cell plus each part alone** (four cells, R5 style) on the fixed picks: select and test, controls (a)/(b) seeds 1-200 through the same changed machine. Each line reports pick-minus-control mean d_m beside the base cell. An option becomes a rule only through a v2 with its own forward test. One confirm look per option on 2024-01..2026-10, entered in the program ledger (R13).

**O1. Weekend skip** (READ)
- Rule: no first-unit entry when the signal bar's close (UTC) is ≥ Saturday 00:00 and < Monday 00:00, on 15m, 30m and 1h systems. 4h is unchanged; SEL shows no effect there, and skipping weekends made core 4h worse (-0.354 → -0.424). Adds, stops, chandelier and exits are unchanged. Skipped events are counted ("weekend") and not queued.
- Variant O1b: the same rule for **longs only**. SEL's far-target gap is long-driven; a long/short asymmetry may be 2021-23 drift, so it is a separate line.
- Numbers: calendar only, no tuning. The "Sat/Sun 00-13 UTC only" variant is **not** registered: US and late hours were bad too.
- SEL expectation: about +0.01..+0.03R per trade averaged at 15m/30m, about 0 at 1h/4h under the chandelier. It drops about a quarter of entries (core kept 74-76%).
- Why a read and not a rule: the effect is small, about half is a market property, the chandelier gap at the hunt's 1h/4h is not significant, and it skips a quarter of trades. If the pick has an edge, that costs growth.

**O2. Macro blackout** (READ)
- Rule: no first-unit entry when the signal bar closes in [T − 120 min, T] (the bar closing exactly at T included), for T = an FOMC statement time or an NFP release time.
- Calendar: official dates from federalreserve.gov and bls.gov for 2021-01..2026-09, written to a pinned file (sha256 in the pin) before the select step. The repo's `data/macro_events.csv` covers Oct-Dec 2026 only; the SEL check used dates from memory, cross-checked against BTC 1m spikes.
- CPI/PCE are excluded (no effect in SEL). Variant: FOMC only, since NFP is weak and mostly 2023. The 60-min version is **not** registered: the whole 2h window was bad for FOMC.
- SEL expectation: ≤ 1% of entries, average ≤ +0.005R. It is risk control, not a fix.

**O3. Same-side risk limit + stress line** (READ in v1; proposed as a RULE for any goal-mode or real-money size, r ≥ 2%)
- Rule: in addition to H 8, an entry or add is taken only if the open risk of all positions on that side, **across all 30 coins** (not just the large group), stays ≤ **half of the total open-risk cap** after it.
  - Machine A at r = 0.5%: 2% of equity, i.e. 4 full units.
  - Machine B: min(2r, 30%).
- Stress line, every 5m close: the sum over same-side open positions of the loss to the current stop, plus a 5% and a 10% gap. Report the max as a share of equity, with its date.
- SEL expectation: the mean is unchanged or slightly lower in strong trend months under wide exits (crowded trades were the better ones there); daily volatility about -10%; the cluster tail is cut.
- Why not a selection rule at r = 0.5%: it trades mean for tail exactly in the trending months the hunt lives on, and 6 × 0.5% is survivable. At goal-mode sizes a correlated cluster stop is a bust path.

**O4. Momentum control at the pick's own times + label** (READ)
- (f) = the pick's gated signal times and coins, with side = sign(close[t] − close[t−20]) of the signal bar (0 → no entry, counted), through the same machine. It is deterministic: one run.
- Report pick − (f) monthly ln M and the share of the pick's sides equal to (f)'s. This separates direction from timing; R6 (e) moves both.
- Pre-registered label: a pick with test mean d_m ≤ 0 against (e) **or** (f) is labelled "momentum only: a plain momentum entry did as well". Its money then comes from market trend plus the machine, and a simple trend bot (F5) is the honest product.
- It is not a pass rule. The owners may choose to make it one before the pin; that lowers power.

**O5. N17 label, no flipped system** (LABEL)
- In the select table, mark N17_KC_RSI as "anti-momentum entry (SEL; also on the 5Y anti-edge list, which saw TEST months)".
- Do **not** add a flipped-N17 system. It would not be blind: RULEBOT_ANALYSIS §4-3 used 2024-26. No reversion-class exclusion either: the other four reversion strategies are side-neutral.

**O6. Drop 15m from the hunt-wide candidates** (owners' choice; a search-space change before the pin, so selection-level)
- In SEL, at 15m the best exit's gross is +0.017R against a cost of 0.158R at a 2 ATR stop. 0/34 core cells are positive under k5 at 15m, and 2/34 at 30m.
- Dropping 15m removes 174 of 686 candidates (F1 6, F2 72, F3 88, F5 8 → 512). That lowers the select-luck load (R4 null of the max) and keeps batch slots for 30m-4h.
- Owners' decision (a) put 15m/30m in. If 15m stays, nothing breaks: eligibility at cost ×2 filters most 15m systems.
- Recommendation: drop 15m, keep 30m.

### 2.3 Considered and not recommended

| Idea | Why not (SEL) |
|---|---|
| 4-bar refractory gap after the edge rule | ≤ +0.02%/trade. The definition is ambiguous (chained debounce vs refractory gives different results). Under the wide exit it flips sign in 2023. |
| Delayed entry k = 2..8 bars | Real-minus-flip +0.10..+0.13 pooled under tp3R\|4 (earlyentry agrees), but half to two thirds is market structure and the 1h/4h residual is not significant. At most a read for a 15m/30m pick. |
| Pullback-limit entry (0.5 ATR) | Worse: earlyentry ladder\|2 pullback minus immediate -0.14 [-0.20, -0.09]; real minus flip -0.08 [-0.12, -0.05]. |
| "Stop too tight" / wider first stop as an entry fix | After a 2 ATR stop, the share later reaching +6 ATR is 38.3% real / 38.0% flip / 35.8% random. A wider stop helps only via cost per R; earlyentry ladder\|4 minus ladder\|2 per notional = -0.00. R5 already reads D0 ×1.5. |
| Anti-chase / lateness filters | Hurt the per-trade mean, and do the same to random bars. |
| Minimum stop D0/P0 ≥ 1.4% | 15m +0.05R, still negative; all bars gain the same; nothing at 1h/4h. |
| Long-only, short-only, side tilt | Drift flips by period: random 1h 4ATR+3R long/short SEL -1.19/+1.08, TEST +0.42/-0.36, X20 +3.84/-3.81 (earlier reports). |
| Drift-neutral month-baseline decomposition | Rejected by verification: the month baseline includes the pre-signal run-up. If such a diagnostic is used at all, it needs a forward-only baseline. |
| Reversion-class exclusion / reversion exit swap | Only N17 is anti-skill; the deficit appears under every exit, so it is not an exit mismatch. |
| BTC-context filter in the hunt | Reversion only; a 2021-22 regime effect. |
| Session/hour-12 filter, HTF EMA alignment, funding gate, coin drops, consensus/crowding filters | 15m-only with no mechanism; or market momentum (R20 G1-dir already reads it); or IC far below costs; or equal to random baselines. |
| Time stop, breakeven, per-strategy exit choice | Already rejected (7.5 / LIVE); per-strategy exits lose out of sample. |

### 2.4 House rule bot (v4 paper), if it is kept

1. Fixed-risk sizing at 0.5%: 5Y busts 91/144 → 15/144.
2. Drop the best tier: about +0.07%/trade at 15m; second check unfinished.
3. A fixed 10%-ROE limit TP instead of the stop-market ladder: +0.20%/trade.

None turns any timeframe positive.

---

## 3. What no rule can fix, and what it implies

- **No direction skill** (strong, every period). Signals add nothing beyond momentum on the same bars. The hunt can only make money from machine × market: small fixed risk, riding rare large trends, with momentum-direction entries. Its honest benchmark is random-time and momentum-side entries through the same machine ((a), (b), R6 (e), O4 (f)). If the pick ≈ (e)/(f), the product is a plain trend/momentum bot, and it works only while the market trends.
- **Market drift flips by period**, so no side tilt is safe. Per-side results in TEST will move with that period's drift, not with skill.
- **Coins co-move** (same-side pair correlation ≈ 0.5 for any entries). This can be capped (O3), not removed. Six same-side positions ≈ 1.7 independent bets.
- **Cost per R ∝ 1/stop%** is arithmetic: only fewer, longer-bar trades and smaller notional per R reduce it.
- **SEL flatters what is chosen on it.** Earlier: 4h tp3R\|4 +2.20% SEL → -0.47% TEST; parameter picks +2.47% → -0.25%; the sized subset adds a further layer. Expect the hunt's test numbers below its select numbers. R4's null of the max sizes this.
- **Small effects do not add up to profit.** The in-sample stack of every surviving context filter moves house 15m from -1.04 to -0.92%/trade (keeping 58% of trades). The "fix the problems one by one" route can trim losses by ≤ 0.1%/trade per item. It cannot create the edge the owners need.
- One open positive, labelled uncertain: at 1h, real signals gained about twice what random entries gained from trailing (k3 +0.375 vs +0.159%/trade). This is significant with month-grouped random draws (p ≈ .006) but not with week grouping, and borderline after 12 tests. The hunt's 1h chandelier systems will show whether it holds.

---

## 4. Checked and not a cause (SEL, with controls)

| Suspect | Result |
|---|---|
| Entry too early (MAE first) | Stopped at -2 ATR, later +6 ATR: 38.3 / 38.0 / 35.8% (real / flip / random). Earlyentry: after a 2 ATR stop, a tp3R\|4 win 13% vs flip 12%. |
| Entry too late / chasing | At the same prior-move bucket, outcome = random; skip filters hurt random equally. |
| Fill gap / latency | Fill = signal close (−0.005 bp); 1-5 min drift < 1 bp. |
| Clustering (first of a run) | Look-ahead by construction. |
| Crowding (many strategies agree) | = momentum on the same bars, plus cost in R. |
| Stop too tight | +2R before -1R: 32.5 real vs 32.3 random; adverse excursion of winners the same. |
| TP too small | Continuation after lock exits: real = random. Unrealisable upper bound only. |
| Win/loss asymmetry, exit reasons, give-back, hold time | Symptoms; identical for random/flip. |
| Higher-tf misalignment, funding extremes, regime detail, volatility level, coin concentration, one-position blocking, liquidation | Explained by the same-bucket random control, or ≈ 0. |

---

## 5. Corrections from verification (first-pass claims that changed)

- **Reversion "fights drift through trend exits": rejected.** It is N17 alone. The deficit appears under every exit, and about 80% of it is bar timing, not month drift.
- **"Drift riding, not timing": rejected.** The month baseline included the pre-signal run-up; tilt halves (0.33 → 0.15) when the 3 pre-signal days are removed. Kept: the structural ~54% short bias, and no side-tilt rule.
- **Weekend:** not strategy-specific; about half is generic weekend weakness of momentum-direction entries. "Weekend US hours normal" is wrong. 4h has no effect. The far-target gap is long-driven. The chandelier at 1h/4h is not significant.
- **FOMC:** the window includes the bar closing at the release; the "other" class is also hit; NFP is mostly 2023; 60 min is too short.
- **Same-side:** the cross-coin daily SD ratio is 1.25x, not 1.6x. The cap's variance cut depends on how coin priority is randomised.
- **Chandelier:** the claim's "coin flip" control was the opposite side. The 1h skill question is open, not answered with "none".
- **Limit TP:** really a swap to a fixed TP; its best timeframe is 4h (-0.22), not 1h.
- **G1:** the sized-subset "artifact" is real only at 4h (98 trades). Counting 모름 as blocked moves 4h to +0.026R.
- **Funding ≥ trading costs:** holds only for the unsized all-signal population. On the house's own trades it is below cost.
- **Risk sizing vs house:** the "-0.70 to -1.04" comparison holds at 15m only. The loss cut is 6-19x at the same exit.
- **Repeat firing:** also N18 (trend class); the wide-exit gain flips in 2023.
- **Period hygiene:** a few first-pass runs let 0.2-2% of trades resolve on post-2024 prices. After force-closing at 2024-01-01, nothing changes (largest: risk-sized 4h tp3R\|4 +0.010 → +0.030R).

---

## 6. 한국어 요약 (사장님들께)

2021~2023년 데이터만 가지고, 의심되는 원인 40여 개를 하나씩 시험했습니다. 시험할 때마다 "아무 때나 들어간 경우"와 "방향을 동전으로 정한 경우"를 같이 돌려 비교했습니다. 결과마다 다른 사람이 따로 코드를 짜서 다시 확인했습니다.

**문제 순위표**

| 순위 | 원인 | 얼마나 큰가 | 고치는 방법 | 새 봇(추세 사냥) 시험에 이미 들어갔나 |
|---|---|---|---|---|
| 1 | 방향을 맞히는 실력이 없음. 조금 맞는 것도 그냥 '최근 오른 쪽'을 따라간 것 | 전략이 고른 방향이 반대 방향을 이긴 비율 50.0% (동전과 같음) | 규칙으로는 못 고침 | 해당 없음. 대신 '아무 때나 진입'과 '최근 방향 따라 진입'을 같은 기계로 돌려 비교함 |
| 2 | 수수료와 슬리피지가 손실의 전부 (지갑의 약 7배 크기로 매매) | 거래 1번에 지갑의 0.6~1.1%. 수수료 빼기 전 수익은 거의 0 | 한 번에 잃는 돈을 지갑의 0.5%로 고정, 1시간·4시간 봉 위주 | 들어감 |
| 3 | 레버리지 크기 규칙 때문에 계좌가 터짐 | 15분봉 계좌 34개 중 30개가 3년 안에 파산 | 위 0.5% 고정 크기 | 들어감 |
| 4 | 익절 사다리가 너무 좁음 | 이긴 거래 평균 +0.43R. 본전에 필요한 승률 73%, 실제 65% | 따라가는 손절(샹들리에), 익절 없음 | 들어감 (단, 아무 때나 진입해도 똑같이 좋아짐. 실력이 아님) |
| 5 | 여러 코인이 같은 방향으로 한꺼번에 손절됨 | 5~6개 코인이 같은 방향이면 전부 손실인 경우 13.5% (따로 움직이면 0.5%) | 같은 방향 위험 합계를 지갑의 2%까지로 제한 | 일부만 (큰 코인만 롱 3·숏 3). 새 옵션 |
| 6 | 예전의 좋은 숫자가 착시였음 (조용한 2023년 거래만 계산에 들어감) | 4시간봉 '거래당 +2.2%' → 전체 신호로 보면 거의 0 | 모든 신호를 같은 위험으로 계산 | 들어감. 기대치는 낮춰야 함 |
| 7 | 주말(토·일) 추세 방향 진입이 더 나쁨 | 그 거래만 0.1~0.3% 더 나쁨. 4시간봉은 해당 없음. 절반은 시장 성질 | 토·일 신규 진입 안 함 (15분~1시간봉) | 안 들어감 → 새 옵션 (참고 계산) |
| 8 | FOMC 발표 2시간 전 진입이 크게 흔들림 | 그 거래만 약 2% 더 손실. 하지만 전체 거래의 1% | 발표 2시간 전 신규 진입 금지 | 안 들어감 → 새 옵션 (참고 계산) |
| 9 | N17_KC_RSI 전략 하나가 반대로 베팅 | 거래당 방향 손해 약 0.3% | 뒤집지 않음. 선발에서 자연히 빠짐 | 선발 규칙이 걸러냄 + 표시 |
| 10 | 같은 신호로 여러 봉 연속 재진입 | 거래당 +0.03% 정도 | 첫 봉만 진입 | 들어감 |
| 11 | 롱을 오래 들고 있으면 펀딩비 | 롱 1건당 0.04~0.07R (2021년 강세장 0.15R) | 계산에 넣고 롱·숏 따로 보고 | 들어감 |

원인이 아니었던 것: 너무 일찍 들어감, 너무 늦게 들어감(추격), 손절이 좁음, 익절이 작음, 시간대, 큰 추세 반대 방향, 특정 코인. 모두 '아무 때나 진입'해도 똑같이 나와서, 전략의 문제가 아니라 시장의 성질이었습니다.

**바뀌는 것**
1. 큰 문제 4개 중 3개(비용, 크기, 좁은 익절)는 새 추세 사냥 봇에 이미 고쳐져 있습니다. 다만 이건 손실을 줄이는 것이지, 돈을 벌게 해 주는 것은 아닙니다.
2. 1번(방향 실력 없음)은 어떤 규칙으로도 못 고칩니다. 새 봇이 돈을 번다면 '큰 추세를 오래 타는 방식' 덕분이어야 합니다. 그래서 시험에서 '아무 때나 진입'과 '최근 방향 따라 진입'을 이겨야만 인정합니다.
3. 작은 문제들(주말, FOMC, 같은 방향 몰림)은 하나하나가 거래당 0.1% 안팎이라, 다 합쳐도 손실을 이익으로 바꾸지 못합니다. 그래서 '수정 묶음' 하나로 미리 적어 두고 2024~2026년 데이터로 딱 한 번 확인합니다. 결과가 좋아도 바로 규칙이 되지 않고, 다음 버전과 모의 매매를 거칩니다.
4. 추천(선택): 15분봉은 비용이 벌 수 있는 몫의 약 9배라서, 새 봇 후보에서 빼는 것이 낫습니다.
5. 예전에 좋아 보였던 숫자 상당수는 조용한 시기만 본 착시였습니다. 시험 결과는 그보다 낮게 나올 것을 각오해야 합니다.
