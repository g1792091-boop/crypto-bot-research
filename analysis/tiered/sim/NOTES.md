# Tiered leverage (20x/30x/50x) vs a risk-based policy: planted-edge simulation on real IS paths

Dir: `scratchpad/tiered/sim`. Every number below comes from `run.py` -> `mc.py` -> `report.py` (tables are pasted verbatim from
`out/tables.md`). Data: `sweep/data/is/<coin>-<tf>.csv` only, signal window 2021-08-01 .. 2024-06-30. Nothing under oos/ or final/ was read.
The sizing workflow in `scratchpad/sizing` was only read, never modified.

## TL;DR

Base case: exits resolved on 5m sub-bars, adverse-first inside a bar, stop 1.5 ATR, TP +10% ROE, 64-bar time exit, $1,000 start, 5,000 paths.

1. **The user's tiered rule loses money in every scenario S0-S4 on every timeframe.** Median equity after 12 months:
   5m **$0** | 15m **$0-1** | 1h **$8-31** | 4h **$237-294**. P(equity < $500 at 12 months) is 100% on 5m/15m, 99-100% on 1h and 71-78% on 4h.
   After 1 month the median is already $245-431 (5m), $413-571 (15m), $704-789 (1h) and $943-960 (4h).
2. **The main cause is fees.** The tiered rule trades 6.6x equity notional on average, so every round trip costs **0.81-0.85% of equity**
   (2.4-2.8% on a "perfect" 50x x 40% trade). At 12-158 trades a month, fees take 68-98% of the starting $1,000 within the year and
   account for **89-98% of the money lost** (median path). Liquidations add 0.1-0.5 a month in the base setup, and up to 2.0-2.5 a month on 1h/4h with the wide-TP variant (TP = max(10% ROE, 2 x stop)).
3. **The planted edges S1-S4 (+0.05% / +0.10% average drift) are smaller than one round trip of costs (0.12-0.14% of notional plus funding),**
   and the exits keep only about half of the drift (for example, tiered keeps +0.05% of a +0.10% drift). So no sizing rule can profit from them.
   The recommended risk-based policy also loses at S0-S4, but slowly on 1h/4h: 12-month median **$669-845 on 1h** and **$955-983 on 4h**, with P(<$500) of 0-8%
   and about 0.01 liquidations a month. On 5m/15m it also bleeds out through fees: $2-46 and $115-395.
4. **Making the score predictive (S3/S4) barely helps the tiered rule.** On 4h, S3 vs S1 gives $256 vs $257 and S4 vs S2 gives $294 vs $284. The reason is structural:
   a +10% ROE TP at 50x is a **0.2% price move**, so a "perfect" trade caps its upside at 0.2% while it risks 1.5 ATR or liquidation.
   With the top-decile drift at +0.31-0.33% (S4), tiered 50x trades keep only **+0.05-0.08%** of it. The recommended 10x trade keeps +0.22-0.25% of the same drift.
   5-9% of "perfect" trades are liquidated on 1h/4h.
5. **Minimum average edge needed (base, uniform edge)** for 12-month median > $1,000 and P(12m end < $500) < 20%:

   | TF | user tiered | flat 20x x 20% | always 50x x 40% | recommended (risk 1%/2%, <=10x) |
   |---|---|---|---|---|
   | 5m | not reached up to +0.30% (81% direction hit-rate) | +0.25% (hit 76%) | never | +0.25% (hit 76%) |
   | 15m | +0.40% (hit 81%) | +0.25% (hit 69%) | never | +0.25% (hit 69%) |
   | 1h | +0.50% (hit 77%) | +0.30% (hit 66%) | never | +0.25% (hit 64%) |
   | 4h | +0.80% (hit 76%) | +0.50% (hit 66%) | never | +0.20% (hit 57%) |

   The drift is measured at the edge horizon h_e (5m: 10 bars, 15m: 6, 1h: 3, 4h: 2 bars). The hit-rate is the share of trades that point the same way as the h_e-bar move.
   With the edge **concentrated** in the top-10% score (3x), the tiered rule **never** meets the criterion inside the feasible range, even when the top-10% trades have
   perfect foresight (100% hit). The recommended policy meets it at +0.20% on 1h and on 4h.
   For scale, every real strategy tested so far in this project showed **no** edge after costs (S0).
6. Direct answer to "is the tiered 20/30/50x rule OK?": **No.** It needs a direction hit-rate of about 76-81% (at the h_e horizon) just to be likely to preserve capital.
   That is far beyond anything measured in this project. If an edge ever appears, the recommended risk-based policy meets the same criterion with 1.6-4x less edge.
   Always-50x x 40% goes to ~$0 in every scenario on every TF.

## What was simulated (method)

* **Entries.** Candidates are drawn per TF across 7 coins (BTC ETH SOL XRP DOGE LTC BCH). At each bar of a global time grid, a Bernoulli trial fires with rate
  5m 6/day, 15m 4/day, 1h 1.5/day, 4h 3/week, and a uniformly random admissible coin is picked. There is one account and one position at a time:
  a candidate is taken only if the previous trade has exited, at or before the bar the new signal is formed on. Entry is at the open of the next bar.
  There are 48 independent candidate streams (seeds) per TF over 2021-08 .. 2024-06 (1,065 days).
* **Setup score.** s ~ U(0,1), independent of everything else. Tiers: s >= 0.9 = perfect (50x, 40% margin, notional 20x equity);
  0.7-0.9 = good (30x x 30% = 9x); otherwise normal (20x x 20% = 4x). References: flat 20x x 20% and always 50x x 40%.
* **Planted edge (oracle).** Side = sign of the forward move r_he (entry open to close of bar t+h_e) with probability (1+q)/2, otherwise random.
  q_coin = D / E|r_he|_coin, so E[side * r_he] = D on every coin. h_e was **measured, not chosen**: it is the mean holding time, in TF bars, of the user's normal trade
  (20x, 1.5 ATR stop, TP 10% ROE, adverse-first) on random entries. That gives 5m 10, 15m 6, 1h 3, 4h 2 bars.
  Concentrated (S3/S4): top-10% score trades get q = 3q-bar, the other 90% get 0.778q-bar, so the average is unchanged.
  The calibration table below shows that the realised drift matches the targets within seed noise.
  Feasibility: q <= 1 on every coin. The concentrated grid stops where the top-decile q reaches 1 on BTC (5m 0.10%, 15m 0.15%, 1h 0.20%, 4h 0.30%).
* **Exits.** Stop = 1.5 x ATR14 of the chart TF (variant 1.0 ATR). TP = +10% ROE = 10%/L price move (variant max(10%/L, 2 x stop)). Time exit at the close of TF bar 64.
  Isolated-margin liquidation at an adverse move of 1/L - 0.5%. If the stop lies beyond that, liquidation comes first and the loss = full margin + entry fee + funding.
  Gaps through a stop fill at the open (worse). Gaps through the TP fill at the open. **Base: the exit path is resolved on the 5m sub-bars inside each 15m/1h/4h bar**
  (the TF bars were checked to be exact aggregates of the 5m bars). Inside a 5m bar where both TP and stop/liquidation are touched, the adverse one goes first (base),
  with favourable-first also reported. Resolving on the chart-TF bars only is kept as a sensitivity. On 4h it moves the tiered 12m median from $13 (adverse) to $294 (favourable).
  The 5m-resolved answer is $237-245, which is why it is the base.
* **Costs (on notional).** Taker 0.05% on every fill. Slippage 0.02% on market fills (entry, stop, time exit). The TP rests at its price (taker fee charged, no slippage).
  Funding 0.01% per 8 h is charged as a cost regardless of side. Round trip = 0.14% (stop/time) or 0.12% (TP) plus funding.
* **Recommended policy.** Stop 1.5 ATR (1.0 ATR in that variant). Risk 1% of equity (2% when score is top-10%). Notional = risk / stop distance, capped at 10x equity.
  Isolated leverage 10x, so liquidation is 9.5% away and practically never binds. Same TP variants as the user rule (10% ROE at 10x = 1% move, or max(1%, 2 x stop)).
  Note: the realised loss at the stop is the risk plus fees (on 5m about 1.36% instead of 1%).
* **Monte Carlo.** All sizing is a fraction of current equity, so trade returns compound multiplicatively. Per seed, trade log-returns are bucketed by exit day.
  Each of 5,000 paths of 365 days is built by stationary block bootstrap of simulated days: blocks of consecutive days with mean length 20 days,
  each block starting at a random (seed, day). All cases within a TF share the same bootstrap indices (paired comparison).
  Reported: equity quantiles at 30 / 91 / 365 days; P(<$500) and P(<$100) at the end and "ever" (the minimum over trade exits);
  liquidations per month; fees in $ = sum over days of (day's cost as a fraction of equity) x equity at the start of that day.

## Caveats (honest limits)

* The edges are **synthetic**. S0 is the only scenario consistent with everything measured so far. S1-S4 show what would happen if an edge existed, not that one exists.
* The planted drift is defined at the fixed horizon h_e. Exits at other times capture only part of it (see the "captured gross" column). A signal whose edge lives at a different horizon would be captured differently.
* 5m bars still carry intrabar-order ambiguity. Adverse-first vs favourable-first changes the base results by only a few % (see the tables).
* With random directions, the 5m-resolved 1h/4h runs show a small *positive* gross per trade (+0.01% to +0.05%). This comes from a near TP limit and a far stop combined with 5m wicks
  (a wick that touches the TP counts as filled). It is an optimistic element and slightly favours the tight-TP (high-leverage) trades.
* Prices are the project's USD spot-style series (last trade). Binance liquidates on **mark price**, which ignores some wicks. Stops trigger on last or mark price depending on the setting.
  Wick-driven liquidations may be somewhat overstated for 50x, and wick TP fills overstated.
* Not modelled: exchange minimum notional (a $3 account cannot trade), the maintenance-margin tiers above small notional, ADL, partial fills, funding sign (funding is charged as a cost always),
  and maker rebates on the TP.
* The bootstrap resamples one market history (2021-08 .. 2024-06: bull, bear and recovery). The p10/p90 bands reflect that history, not every possible market.
* "Ever below $500" uses equity at trade exits only. Intra-trade mark-to-market dips are not included, so it is a lower bound.
* The fee column is approximate: it ignores compounding inside a day.

## Files

* `lib.py`: data loading (IS only), ATR (Wilder), panel/candidates, 5m sub-bar paths, vectorised exit resolution, one-position chase.
* `verify_exits.py`: 9 hand-built paths (TP, stop, liquidation-first, gaps, adverse/favourable, short, time exit, cost/liquidation arithmetic). All pass.
* `explore.py`: first look (E|r_h|, ATR, hold times, liquidation-first shares) -> `out/explore_*.json`.
* `run.py --tf X --seeds 48 [--fine 1 --tag _fine --he N]`: simulation -> `out/<tf>[_fine].npz` + meta. `run_all.sh` / `run_fine.sh` are the exact commands used.
* `mc.py`: bootstrap -> `out/metrics.csv` (2,152 rows: every TF x resolution x scenario x policy x exit x order) and `out/calibration.csv`.
* `report.py`: produces `out/tables.md` and `out/min_edge.csv`.
* Runtime (wall): TF-bar runs 10 s + 23 s + 43 s + 59 s. 5m-resolved runs 91 s (4h) + 102 s (1h) + 83 s (15m). Monte Carlo 130 s. Total about 9 minutes of compute.

## Tables (generated)

### Setup per TF (all measured by code)

| TF | edge horizon h_e (bars) | E\|r_he\| per coin (min-max) | candidates/day | tiered S0 trades/month taken | mean hold (bars) tiered S0 | q at +0.05% / +0.10% (mean over coins) | direction hit-rate at +0.05% / +0.10% |
|---|---|---|---|---|---|---|---|
| 5m | 10 | 0.34-0.69% | 6.00 | 158 | 8.7 | 0.103 / 0.207 | 55.2% / 60.3% |
| 15m | 6 | 0.45-0.93% | 4.00 | 103 | 5.3 | 0.077 / 0.153 | 53.8% / 57.7% |
| 1h | 3 | 0.65-1.32% | 1.50 | 41 | 2.9 | 0.054 / 0.108 | 52.7% / 55.4% |
| 4h | 2 | 1.08-2.21% | 0.43 | 12 | 1.7 | 0.032 / 0.065 | 51.6% / 53.2% |

### Edge calibration check (target = planted mean drift side*r_he; realised = mean over all candidates, averaged over seeds)

| TF | scenario | target avg | realised avg (all cand.) | realised top-10% | realised other 90% | taken trades, tiered base: drift top / rest | captured gross per trade at actual exit: tiered / flat20 / max50 / rec |
|---|---|---|---|---|---|---|---|
| 5m | S0 | 0.000% | +0.001% | +0.000% | +0.001% | -0.001% / +0.001% | +0.000% / +0.000% / +0.000% / -0.003% |
| 5m | S1 | 0.050% | +0.052% | +0.049% | +0.052% | +0.049% / +0.053% | +0.026% / +0.028% / +0.014% / +0.034% |
| 5m | S2 | 0.100% | +0.102% | +0.099% | +0.102% | +0.100% / +0.105% | +0.050% / +0.056% / +0.027% / +0.071% |
| 5m | S3 | 0.050% | +0.052% | +0.150% | +0.041% | +0.152% / +0.042% | +0.023% / +0.029% / +0.014% / +0.034% |
| 5m | S4 | 0.100% | +0.102% | +0.302% | +0.080% | +0.312% / +0.082% | +0.046% / +0.057% / +0.027% / +0.071% |
| 15m | S0 | 0.000% | -0.002% | +0.003% | -0.002% | +0.006% / -0.001% | +0.007% / +0.006% / +0.007% / +0.001% |
| 15m | S1 | 0.050% | +0.050% | +0.050% | +0.050% | +0.056% / +0.053% | +0.030% / +0.032% / +0.018% / +0.040% |
| 15m | S2 | 0.100% | +0.100% | +0.104% | +0.099% | +0.112% / +0.104% | +0.053% / +0.059% / +0.029% / +0.079% |
| 15m | S3 | 0.050% | +0.049% | +0.149% | +0.038% | +0.159% / +0.041% | +0.027% / +0.032% / +0.018% / +0.040% |
| 15m | S4 | 0.100% | +0.100% | +0.306% | +0.077% | +0.321% / +0.081% | +0.047% / +0.059% / +0.029% / +0.078% |
| 1h | S0 | 0.000% | +0.003% | +0.023% | +0.001% | +0.022% / -0.000% | +0.015% / +0.019% / +0.012% / +0.016% |
| 1h | S1 | 0.050% | +0.052% | +0.079% | +0.049% | +0.078% / +0.049% | +0.036% / +0.042% / +0.021% / +0.052% |
| 1h | S2 | 0.100% | +0.104% | +0.135% | +0.101% | +0.138% / +0.102% | +0.054% / +0.063% / +0.029% / +0.087% |
| 1h | S3 | 0.050% | +0.053% | +0.179% | +0.039% | +0.183% / +0.039% | +0.033% / +0.041% / +0.020% / +0.050% |
| 1h | S4 | 0.100% | +0.103% | +0.320% | +0.079% | +0.331% / +0.081% | +0.050% / +0.063% / +0.028% / +0.087% |
| 4h | S0 | 0.000% | +0.012% | -0.011% | +0.016% | -0.012% / +0.017% | +0.043% / +0.047% / +0.038% / +0.055% |
| 4h | S1 | 0.050% | +0.052% | +0.018% | +0.056% | +0.019% / +0.058% | +0.053% / +0.059% / +0.042% / +0.079% |
| 4h | S2 | 0.100% | +0.098% | +0.068% | +0.101% | +0.064% / +0.102% | +0.064% / +0.071% / +0.044% / +0.102% |
| 4h | S3 | 0.050% | +0.054% | +0.112% | +0.048% | +0.111% / +0.049% | +0.051% / +0.058% / +0.041% / +0.078% |
| 4h | S4 | 0.100% | +0.100% | +0.268% | +0.082% | +0.257% / +0.084% | +0.062% / +0.074% / +0.045% / +0.105% |

### HEADLINE (ADVERSE-first (conservative, base)): stop 1.5 ATR, TP +10% ROE, 64-bar time exit, from $1,000, 5,000 bootstrap paths

P(<$500) = end-of-12-month equity below $500 / ever below $500 at any trade exit within 12 months.

| TF | scenario | USER TIERED: 1m median | 12m median | P(<$500) end / ever | liq / month | RECOMMENDED: 1m median | 12m median | P(<$500) end / ever | liq / month |
|---|---|---|---|---|---|---|---|---|---|
| 5m | S0 no edge | $245 | $0 | 100% / 100% | 0.1 | $596 | $2 | 100% / 100% | 0.00 |
| 5m | S1 +0.05% uniform | $309 | $0 | 100% / 100% | 0.1 | $668 | $8 | 100% / 100% | 0.00 |
| 5m | S2 +0.10% uniform | $388 | $0 | 100% / 100% | 0.1 | $744 | $29 | 100% / 100% | 0.00 |
| 5m | S3 +0.05% concentrated | $324 | $0 | 100% / 100% | 0.1 | $680 | $9 | 100% / 100% | 0.00 |
| 5m | S4 +0.10% concentrated | $431 | $0 | 100% / 100% | 0.1 | $779 | $46 | 100% / 100% | 0.00 |
| 15m | S0 no edge | $413 | $0 | 100% / 100% | 0.2 | $838 | $115 | 100% / 100% | 0.00 |
| 15m | S1 +0.05% uniform | $469 | $0 | 100% / 100% | 0.2 | $875 | $195 | 99% / 99% | 0.00 |
| 15m | S2 +0.10% uniform | $539 | $0 | 100% / 100% | 0.2 | $917 | $328 | 83% / 88% | 0.00 |
| 15m | S3 +0.05% concentrated | $484 | $0 | 100% / 100% | 0.2 | $883 | $210 | 97% / 99% | 0.00 |
| 15m | S4 +0.10% concentrated | $571 | $1 | 100% / 100% | 0.2 | $930 | $395 | 70% / 78% | 0.00 |
| 1h | S0 no edge | $704 | $8 | 100% / 100% | 0.4 | $969 | $669 | 8% / 10% | 0.01 |
| 1h | S1 +0.05% uniform | $743 | $15 | 100% / 100% | 0.4 | $975 | $737 | 3% / 4% | 0.01 |
| 1h | S2 +0.10% uniform | $777 | $25 | 99% / 100% | 0.4 | $983 | $813 | 0.7% / 1.0% | 0.01 |
| 1h | S3 +0.05% concentrated | $752 | $17 | 100% / 100% | 0.4 | $977 | $746 | 2% / 3% | 0.01 |
| 1h | S4 +0.10% concentrated | $789 | $31 | 99% / 100% | 0.4 | $986 | $845 | 0.4% / 0.6% | 0.01 |
| 4h | S0 no edge | $943 | $237 | 78% / 86% | 0.5 | $998 | $955 | 0% / 0% | 0.01 |
| 4h | S1 +0.05% uniform | $952 | $257 | 75% / 84% | 0.5 | $998 | $966 | 0% / 0% | 0.01 |
| 4h | S2 +0.10% uniform | $959 | $284 | 72% / 82% | 0.4 | $999 | $976 | 0% / 0% | 0.01 |
| 4h | S3 +0.05% concentrated | $949 | $256 | 75% / 84% | 0.5 | $998 | $968 | 0% / 0% | 0.01 |
| 4h | S4 +0.10% concentrated | $960 | $294 | 71% / 81% | 0.4 | $1,000 | $983 | 0% / 0% | 0.01 |

### HEADLINE (FAVOURABLE-first (optimistic)): stop 1.5 ATR, TP +10% ROE, 64-bar time exit, from $1,000, 5,000 bootstrap paths

P(<$500) = end-of-12-month equity below $500 / ever below $500 at any trade exit within 12 months.

| TF | scenario | USER TIERED: 1m median | 12m median | P(<$500) end / ever | liq / month | RECOMMENDED: 1m median | 12m median | P(<$500) end / ever | liq / month |
|---|---|---|---|---|---|---|---|---|---|
| 5m | S0 no edge | $253 | $0 | 100% / 100% | 0.1 | $597 | $2 | 100% / 100% | 0.00 |
| 5m | S1 +0.05% uniform | $321 | $0 | 100% / 100% | 0.1 | $671 | $8 | 100% / 100% | 0.00 |
| 5m | S2 +0.10% uniform | $403 | $0 | 100% / 100% | 0.1 | $746 | $30 | 100% / 100% | 0.00 |
| 5m | S3 +0.05% concentrated | $337 | $0 | 100% / 100% | 0.1 | $682 | $10 | 100% / 100% | 0.00 |
| 5m | S4 +0.10% concentrated | $448 | $0 | 100% / 100% | 0.0 | $780 | $48 | 100% / 100% | 0.00 |
| 15m | S0 no edge | $421 | $0 | 100% / 100% | 0.2 | $839 | $118 | 100% / 100% | 0.00 |
| 15m | S1 +0.05% uniform | $481 | $0 | 100% / 100% | 0.2 | $876 | $199 | 99% / 99% | 0.00 |
| 15m | S2 +0.10% uniform | $551 | $0 | 100% / 100% | 0.2 | $917 | $334 | 82% / 87% | 0.00 |
| 15m | S3 +0.05% concentrated | $496 | $0 | 100% / 100% | 0.2 | $884 | $213 | 97% / 98% | 0.00 |
| 15m | S4 +0.10% concentrated | $583 | $1 | 100% / 100% | 0.1 | $932 | $402 | 69% / 77% | 0.00 |
| 1h | S0 no edge | $709 | $9 | 100% / 100% | 0.4 | $969 | $672 | 7% / 9% | 0.01 |
| 1h | S1 +0.05% uniform | $748 | $17 | 100% / 100% | 0.4 | $976 | $741 | 3% / 3% | 0.01 |
| 1h | S2 +0.10% uniform | $782 | $28 | 99% / 100% | 0.4 | $984 | $818 | 0.6% / 1.0% | 0.01 |
| 1h | S3 +0.05% concentrated | $758 | $19 | 100% / 100% | 0.4 | $978 | $750 | 2% / 3% | 0.01 |
| 1h | S4 +0.10% concentrated | $795 | $35 | 99% / 100% | 0.3 | $987 | $849 | 0.3% / 0.5% | 0.01 |
| 4h | S0 no edge | $946 | $245 | 77% / 85% | 0.5 | $998 | $955 | 0% / 0% | 0.01 |
| 4h | S1 +0.05% uniform | $954 | $266 | 74% / 83% | 0.4 | $998 | $966 | 0% / 0% | 0.01 |
| 4h | S2 +0.10% uniform | $961 | $294 | 72% / 81% | 0.4 | $999 | $976 | 0% / 0% | 0.01 |
| 4h | S3 +0.05% concentrated | $952 | $264 | 75% / 84% | 0.4 | $999 | $968 | 0% / 0% | 0.01 |
| 4h | S4 +0.10% concentrated | $962 | $302 | 71% / 80% | 0.4 | $1,000 | $984 | 0% / 0% | 0.01 |

### Reference sizing rules (adverse-first, stop 1.5 ATR, TP +10% ROE): 12m median / P(end<$500) / P(ever<$100) / liq per month

| TF | scenario | tiered | flat 20x x 20% | always 50x x 40% | recommended |
|---|---|---|---|---|---|
| 5m | S0 | $0 / 100% / 100% / 0.1 | $0 / 100% / 100% / 0.0 | $0 / 100% / 100% / 0.6 | $2 / 100% / 100% / 0.0 |
| 5m | S1 | $0 / 100% / 100% / 0.1 | $0 / 100% / 100% / 0.0 | $0 / 100% / 100% / 0.6 | $8 / 100% / 100% / 0.0 |
| 5m | S2 | $0 / 100% / 100% / 0.1 | $3 / 100% / 100% / 0.0 | $0 / 100% / 100% / 0.6 | $29 / 100% / 95% / 0.0 |
| 5m | S3 | $0 / 100% / 100% / 0.1 | $0 / 100% / 100% / 0.0 | $0 / 100% / 100% / 0.6 | $9 / 100% / 100% / 0.0 |
| 5m | S4 | $0 / 100% / 100% / 0.1 | $3 / 100% / 100% / 0.0 | $0 / 100% / 100% / 0.6 | $46 / 100% / 85% / 0.0 |
| 15m | S0 | $0 / 100% / 100% / 0.2 | $2 / 100% / 100% / 0.0 | $0 / 100% / 100% / 1.6 | $115 / 100% / 41% / 0.0 |
| 15m | S1 | $0 / 100% / 100% / 0.2 | $6 / 100% / 100% / 0.0 | $0 / 100% / 100% / 1.5 | $195 / 99% / 8% / 0.0 |
| 15m | S2 | $0 / 100% / 100% / 0.2 | $22 / 100% / 96% / 0.0 | $0 / 100% / 100% / 1.4 | $328 / 83% / 0.5% / 0.0 |
| 15m | S3 | $0 / 100% / 100% / 0.2 | $6 / 100% / 100% / 0.0 | $0 / 100% / 100% / 1.5 | $210 / 97% / 5% / 0.0 |
| 15m | S4 | $1 / 100% / 100% / 0.2 | $22 / 100% / 96% / 0.0 | $0 / 100% / 100% / 1.5 | $395 / 70% / 0.2% / 0.0 |
| 1h | S0 | $8 / 100% / 98% / 0.4 | $83 / 98% / 64% / 0.1 | $0 / 100% / 100% / 2.9 | $669 / 8% / 0% / 0.0 |
| 1h | S1 | $15 / 100% / 94% / 0.4 | $131 / 95% / 43% / 0.1 | $0 / 100% / 100% / 2.8 | $737 / 3% / 0% / 0.0 |
| 1h | S2 | $25 / 99% / 89% / 0.4 | $200 / 86% / 26% / 0.1 | $0 / 100% / 100% / 2.7 | $813 / 0.7% / 0% / 0.0 |
| 1h | S3 | $17 / 100% / 93% / 0.4 | $130 / 95% / 43% / 0.1 | $0 / 100% / 100% / 2.8 | $746 / 2% / 0% / 0.0 |
| 1h | S4 | $31 / 99% / 86% / 0.4 | $201 / 86% / 26% / 0.1 | $0 / 100% / 100% / 2.7 | $845 / 0.4% / 0% / 0.0 |
| 4h | S0 | $237 / 78% / 25% / 0.5 | $502 / 50% / 2% / 0.3 | $4 / 100% / 97% / 1.2 | $955 / 0% / 0% / 0.0 |
| 4h | S1 | $257 / 75% / 22% / 0.5 | $541 / 45% / 1% / 0.3 | $5 / 100% / 97% / 1.2 | $966 / 0% / 0% / 0.0 |
| 4h | S2 | $284 / 72% / 20% / 0.4 | $579 / 41% / 1% / 0.3 | $5 / 100% / 96% / 1.2 | $976 / 0% / 0% / 0.0 |
| 4h | S3 | $256 / 75% / 22% / 0.5 | $537 / 46% / 2% / 0.3 | $5 / 100% / 97% / 1.2 | $968 / 0% / 0% / 0.0 |
| 4h | S4 | $294 / 71% / 19% / 0.4 | $589 / 40% / 1% / 0.3 | $5 / 100% / 96% / 1.1 | $983 / 0% / 0% / 0.0 |

### Distribution detail (adverse-first, stop 1.5 ATR, TP +10% ROE): median [p10 - p90] at 1m / 3m / 12m; P(<$100) end/ever at 12m

| TF | scenario | policy | 1 month | 3 months | 12 months | P(<$100) 12m end / ever |
|---|---|---|---|---|---|---|
| 5m | S0 | tiered | $245 [$129 - $420] | $14 [$4 - $37] | $0 [$0 - $0] | 100% / 100% |
| 5m | S0 | rec | $596 [$446 - $785] | $210 [$125 - $341] | $2 [$1 - $5] | 100% / 100% |
| 5m | S1 | tiered | $309 [$166 - $527] | $27 [$9 - $75] | $0 [$0 - $0] | 100% / 100% |
| 5m | S1 | rec | $668 [$501 - $879] | $298 [$175 - $483] | $8 [$3 - $21] | 100% / 100% |
| 5m | S2 | tiered | $388 [$211 - $648] | $55 [$20 - $147] | $0 [$0 - $0] | 100% / 100% |
| 5m | S2 | rec | $744 [$556 - $985] | $413 [$246 - $678] | $29 [$10 - $79] | 94% / 95% |
| 5m | S3 | tiered | $324 [$179 - $545] | $32 [$11 - $84] | $0 [$0 - $0] | 100% / 100% |
| 5m | S3 | rec | $680 [$506 - $899] | $312 [$184 - $513] | $9 [$3 - $26] | 100% / 100% |
| 5m | S4 | tiered | $431 [$247 - $693] | $76 [$30 - $186] | $0 [$0 - $0] | 100% / 100% |
| 5m | S4 | rec | $779 [$576 - $1,033] | $467 [$273 - $775] | $46 [$16 - $135] | 82% / 85% |
| 15m | S0 | tiered | $413 [$207 - $710] | $60 [$19 - $171] | $0 [$0 - $0] | 100% / 100% |
| 15m | S0 | rec | $838 [$711 - $983] | $584 [$439 - $764] | $115 [$64 - $202] | 37% / 41% |
| 15m | S1 | tiered | $469 [$243 - $811] | $92 [$31 - $253] | $0 [$0 - $0] | 100% / 100% |
| 15m | S1 | rec | $875 [$746 - $1,027] | $662 [$506 - $875] | $195 [$109 - $341] | 7% / 8% |
| 15m | S2 | tiered | $539 [$285 - $913] | $142 [$48 - $373] | $0 [$0 - $2] | 100% / 100% |
| 15m | S2 | rec | $917 [$775 - $1,074] | $757 [$572 - $998] | $328 [$184 - $578] | 0.4% / 0.5% |
| 15m | S3 | tiered | $484 [$253 - $819] | $99 [$35 - $264] | $0 [$0 - $1] | 100% / 100% |
| 15m | S3 | rec | $883 [$749 - $1,036] | $677 [$515 - $894] | $210 [$120 - $373] | 4% / 5% |
| 15m | S4 | tiered | $571 [$314 - $931] | $166 [$60 - $418] | $1 [$0 - $5] | 100% / 100% |
| 15m | S4 | rec | $930 [$790 - $1,091] | $795 [$599 - $1,047] | $395 [$224 - $698] | 0.2% / 0.2% |
| 1h | S0 | tiered | $704 [$378 - $1,109] | $311 [$113 - $737] | $8 [$1 - $48] | 97% / 98% |
| 1h | S0 | rec | $969 [$898 - $1,039] | $905 [$796 - $1,020] | $669 [$515 - $849] | 0% / 0% |
| 1h | S1 | tiered | $743 [$399 - $1,142] | $360 [$132 - $829] | $15 [$2 - $82] | 92% / 94% |
| 1h | S1 | rec | $975 [$907 - $1,047] | $927 [$817 - $1,046] | $737 [$573 - $937] | 0% / 0% |
| 1h | S2 | tiered | $777 [$429 - $1,177] | $415 [$155 - $938] | $25 [$4 - $139] | 85% / 89% |
| 1h | S2 | rec | $983 [$916 - $1,055] | $950 [$840 - $1,072] | $813 [$635 - $1,039] | 0% / 0% |
| 1h | S3 | tiered | $752 [$403 - $1,143] | $374 [$137 - $851] | $17 [$2 - $91] | 91% / 93% |
| 1h | S3 | rec | $977 [$909 - $1,049] | $931 [$822 - $1,051] | $746 [$580 - $956] | 0% / 0% |
| 1h | S4 | tiered | $789 [$445 - $1,183] | $432 [$165 - $970] | $31 [$4 - $161] | 82% / 86% |
| 1h | S4 | rec | $986 [$920 - $1,060] | $957 [$847 - $1,084] | $845 [$660 - $1,074] | 0% / 0% |
| 4h | S0 | tiered | $943 [$593 - $1,198] | $741 [$351 - $1,267] | $237 [$58 - $781] | 21% / 25% |
| 4h | S0 | rec | $998 [$968 - $1,021] | $990 [$943 - $1,035] | $955 [$867 - $1,044] | 0% / 0% |
| 4h | S1 | tiered | $952 [$600 - $1,202] | $753 [$361 - $1,282] | $257 [$64 - $835] | 19% / 22% |
| 4h | S1 | rec | $998 [$969 - $1,022] | $992 [$945 - $1,038] | $966 [$877 - $1,055] | 0% / 0% |
| 4h | S2 | tiered | $959 [$607 - $1,206] | $774 [$370 - $1,304] | $284 [$71 - $918] | 16% / 20% |
| 4h | S2 | rec | $999 [$970 - $1,023] | $995 [$948 - $1,041] | $976 [$887 - $1,066] | 0% / 0% |
| 4h | S3 | tiered | $949 [$600 - $1,201] | $752 [$361 - $1,284] | $256 [$64 - $833] | 18% / 22% |
| 4h | S3 | rec | $998 [$970 - $1,022] | $993 [$946 - $1,038] | $968 [$879 - $1,057] | 0% / 0% |
| 4h | S4 | tiered | $960 [$611 - $1,206] | $779 [$375 - $1,307] | $294 [$75 - $929] | 15% / 19% |
| 4h | S4 | rec | $1,000 [$971 - $1,023] | $997 [$951 - $1,042] | $983 [$895 - $1,074] | 0% / 0% |

### Exit variants: 12m median / P(end<$500) / liq per month, tiered vs recommended (A = adverse-first, F = favourable-first)

| TF | scenario | exit | tiered A | tiered F | rec A | rec F |
|---|---|---|---|---|---|---|
| 5m | S0 | 1.5 ATR, TP 10% ROE | $0 / 100% / 0.1 | $0 / 100% / 0.1 | $2 / 100% / 0.0 | $2 / 100% / 0.0 |
| 5m | S0 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.3 | $0 / 100% / 0.3 | $2 / 100% / 0.0 | $2 / 100% / 0.0 |
| 5m | S0 | 1.0 ATR, TP 10% ROE | $0 / 100% / 0.0 | $0 / 100% / 0.0 | $0 / 100% / 0.0 | $0 / 100% / 0.0 |
| 5m | S0 | 1.0 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.1 | $0 / 100% / 0.1 | $0 / 100% / 0.0 | $0 / 100% / 0.0 |
| 5m | S2 | 1.5 ATR, TP 10% ROE | $0 / 100% / 0.1 | $0 / 100% / 0.1 | $29 / 100% / 0.0 | $30 / 100% / 0.0 |
| 5m | S2 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.3 | $0 / 100% / 0.3 | $31 / 100% / 0.0 | $32 / 100% / 0.0 |
| 5m | S2 | 1.0 ATR, TP 10% ROE | $0 / 100% / 0.0 | $0 / 100% / 0.0 | $1 / 100% / 0.0 | $1 / 100% / 0.0 |
| 5m | S2 | 1.0 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.1 | $0 / 100% / 0.1 | $1 / 100% / 0.0 | $1 / 100% / 0.0 |
| 5m | S4 | 1.5 ATR, TP 10% ROE | $0 / 100% / 0.1 | $0 / 100% / 0.0 | $46 / 100% / 0.0 | $48 / 100% / 0.0 |
| 5m | S4 | 1.5 ATR, TP max(10% ROE, 2x stop) | $1 / 98% / 0.2 | $1 / 98% / 0.2 | $51 / 100% / 0.0 | $52 / 100% / 0.0 |
| 5m | S4 | 1.0 ATR, TP 10% ROE | $0 / 100% / 0.0 | $0 / 100% / 0.0 | $2 / 100% / 0.0 | $2 / 100% / 0.0 |
| 5m | S4 | 1.0 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.1 | $0 / 100% / 0.1 | $2 / 100% / 0.0 | $2 / 100% / 0.0 |
| 15m | S0 | 1.5 ATR, TP 10% ROE | $0 / 100% / 0.2 | $0 / 100% / 0.2 | $115 / 100% / 0.0 | $118 / 100% / 0.0 |
| 15m | S0 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.9 | $0 / 100% / 0.9 | $128 / 100% / 0.0 | $129 / 100% / 0.0 |
| 15m | S0 | 1.0 ATR, TP 10% ROE | $0 / 100% / 0.1 | $0 / 100% / 0.1 | $23 / 100% / 0.0 | $24 / 100% / 0.0 |
| 15m | S0 | 1.0 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.3 | $0 / 100% / 0.3 | $23 / 100% / 0.0 | $24 / 100% / 0.0 |
| 15m | S2 | 1.5 ATR, TP 10% ROE | $0 / 100% / 0.2 | $0 / 100% / 0.2 | $328 / 83% / 0.0 | $334 / 82% / 0.0 |
| 15m | S2 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.8 | $0 / 100% / 0.8 | $347 / 76% / 0.0 | $351 / 75% / 0.0 |
| 15m | S2 | 1.0 ATR, TP 10% ROE | $0 / 100% / 0.1 | $0 / 100% / 0.0 | $97 / 100% / 0.0 | $100 / 100% / 0.0 |
| 15m | S2 | 1.0 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.3 | $0 / 100% / 0.3 | $103 / 99% / 0.0 | $106 / 99% / 0.0 |
| 15m | S4 | 1.5 ATR, TP 10% ROE | $1 / 100% / 0.2 | $1 / 100% / 0.1 | $395 / 70% / 0.0 | $402 / 69% / 0.0 |
| 15m | S4 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 99% / 0.8 | $0 / 99% / 0.8 | $405 / 66% / 0.0 | $411 / 65% / 0.0 |
| 15m | S4 | 1.0 ATR, TP 10% ROE | $0 / 100% / 0.1 | $0 / 100% / 0.0 | $125 / 99% / 0.0 | $128 / 99% / 0.0 |
| 15m | S4 | 1.0 ATR, TP max(10% ROE, 2x stop) | $1 / 98% / 0.3 | $1 / 98% / 0.3 | $135 / 98% / 0.0 | $140 / 98% / 0.0 |
| 1h | S0 | 1.5 ATR, TP 10% ROE | $8 / 100% / 0.4 | $9 / 100% / 0.4 | $669 / 8% / 0.0 | $672 / 7% / 0.0 |
| 1h | S0 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 2.0 | $0 / 100% / 2.0 | $667 / 14% / 0.0 | $667 / 14% / 0.0 |
| 1h | S0 | 1.0 ATR, TP 10% ROE | $11 / 100% / 0.2 | $13 / 100% / 0.1 | $506 / 48% / 0.0 | $510 / 47% / 0.0 |
| 1h | S0 | 1.0 ATR, TP max(10% ROE, 2x stop) | $0 / 100% / 0.9 | $0 / 100% / 0.9 | $482 / 54% / 0.0 | $484 / 54% / 0.0 |
| 1h | S2 | 1.5 ATR, TP 10% ROE | $25 / 99% / 0.4 | $28 / 99% / 0.4 | $813 / 0.7% / 0.0 | $818 / 0.6% / 0.0 |
| 1h | S2 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 99% / 2.0 | $0 / 99% / 2.0 | $809 / 4% / 0.0 | $810 / 4% / 0.0 |
| 1h | S2 | 1.0 ATR, TP 10% ROE | $30 / 100% / 0.1 | $34 / 99% / 0.1 | $681 / 12% / 0.0 | $686 / 11% / 0.0 |
| 1h | S2 | 1.0 ATR, TP max(10% ROE, 2x stop) | $1 / 99% / 0.9 | $1 / 99% / 0.9 | $662 / 20% / 0.0 | $665 / 20% / 0.0 |
| 1h | S4 | 1.5 ATR, TP 10% ROE | $31 / 99% / 0.4 | $35 / 99% / 0.3 | $845 / 0.4% / 0.0 | $849 / 0.3% / 0.0 |
| 1h | S4 | 1.5 ATR, TP max(10% ROE, 2x stop) | $0 / 99% / 1.9 | $0 / 99% / 1.9 | $840 / 3% / 0.0 | $840 / 3% / 0.0 |
| 1h | S4 | 1.0 ATR, TP 10% ROE | $35 / 99% / 0.1 | $41 / 99% / 0.1 | $718 / 8% / 0.0 | $722 / 8% / 0.0 |
| 1h | S4 | 1.0 ATR, TP max(10% ROE, 2x stop) | $1 / 97% / 0.8 | $1 / 97% / 0.8 | $697 / 16% / 0.0 | $701 / 15% / 0.0 |
| 4h | S0 | 1.5 ATR, TP 10% ROE | $237 / 78% / 0.5 | $245 / 77% / 0.5 | $955 / 0% / 0.0 | $955 / 0% / 0.0 |
| 4h | S0 | 1.5 ATR, TP max(10% ROE, 2x stop) | $1 / 99% / 2.5 | $1 / 99% / 2.5 | $920 / 0% / 0.1 | $920 / 0% / 0.1 |
| 4h | S0 | 1.0 ATR, TP 10% ROE | $295 / 73% / 0.2 | $308 / 72% / 0.2 | $931 / 0% / 0.0 | $932 / 0% / 0.0 |
| 4h | S0 | 1.0 ATR, TP max(10% ROE, 2x stop) | $2 / 98% / 1.4 | $2 / 98% / 1.4 | $880 / 0.1% / 0.0 | $881 / 0.1% / 0.0 |
| 4h | S2 | 1.5 ATR, TP 10% ROE | $284 / 72% / 0.4 | $294 / 72% / 0.4 | $976 / 0% / 0.0 | $976 / 0% / 0.0 |
| 4h | S2 | 1.5 ATR, TP max(10% ROE, 2x stop) | $1 / 98% / 2.5 | $1 / 98% / 2.5 | $936 / 0% / 0.1 | $936 / 0% / 0.1 |
| 4h | S2 | 1.0 ATR, TP 10% ROE | $344 / 66% / 0.2 | $355 / 65% / 0.2 | $961 / 0% / 0.0 | $963 / 0% / 0.0 |
| 4h | S2 | 1.0 ATR, TP max(10% ROE, 2x stop) | $3 / 97% / 1.4 | $3 / 97% / 1.4 | $920 / 0.0% / 0.0 | $920 / 0.0% / 0.0 |
| 4h | S4 | 1.5 ATR, TP 10% ROE | $294 / 71% / 0.4 | $302 / 71% / 0.4 | $983 / 0% / 0.0 | $984 / 0% / 0.0 |
| 4h | S4 | 1.5 ATR, TP max(10% ROE, 2x stop) | $1 / 98% / 2.4 | $1 / 98% / 2.4 | $942 / 0% / 0.1 | $942 / 0% / 0.1 |
| 4h | S4 | 1.0 ATR, TP 10% ROE | $358 / 65% / 0.2 | $370 / 64% / 0.2 | $968 / 0% / 0.0 | $970 / 0% / 0.0 |
| 4h | S4 | 1.0 ATR, TP max(10% ROE, 2x stop) | $4 / 97% / 1.4 | $4 / 97% / 1.4 | $924 / 0% / 0.0 | $925 / 0% / 0.0 |

### Costs and trade mechanics (S0, adverse-first, stop 1.5 ATR, TP +10% ROE)

| TF | policy | trades/month | mean notional (x equity) | cost per trade (% of equity) | fees paid in 12m, median path ($, from $1,000 start) | fees / (1000 - 12m median equity) | exits TP / stop / liq / time | liq rate normal / good / perfect | win rate |
|---|---|---|---|---|---|---|---|---|---|
| 5m | tiered | 158 | 6.58 | 0.85% | $983 (98%) | 98% | 52% / 47% / 0.1% / 0.9% | 0.0% / 0.0% / 0.4% | 53% |
| 5m | flat20 | 155 | 4.00 | 0.53% | $984 (98%) | 98% | 48% / 51% / 0.0% / 1% | 0.0% / 0.0% / 0% | 49% |
| 5m | max50 | 171 | 20.00 | 2.53% | $1,016 (102%) | 102% | 69% / 30% / 0.4% / 0.1% | 0.4% / 0.3% / 0.4% | 69% |
| 5m | rec | 139 | 2.59 | 0.36% | $956 (96%) | 96% | 31% / 64% / 0% / 5% | 0% / 0% / 0% | 34% |
| 15m | tiered | 103 | 6.60 | 0.84% | $982 (98%) | 98% | 66% / 34% / 0.2% / 0.2% | 0.0% / 0.2% / 2% | 66% |
| 15m | flat20 | 101 | 4.00 | 0.52% | $1,017 (102%) | 102% | 62% / 37% / 0.0% / 0.3% | 0.0% / 0.0% / 0.1% | 62% |
| 15m | max50 | 113 | 20.00 | 2.48% | $969 (97%) | 97% | 80% / 19% / 1% / 0.0% | 1% / 1% / 2% | 80% |
| 15m | rec | 87 | 1.45 | 0.20% | $851 (85%) | 96% | 46% / 53% / 0.0% / 1% | 0% / 0.0% / 0% | 46% |
| 1h | tiered | 41 | 6.57 | 0.82% | $902 (90%) | 91% | 79% / 20% / 1% / 0.0% | 0.3% / 1% / 6% | 79% |
| 1h | flat20 | 40 | 4.00 | 0.51% | $936 (94%) | 102% | 77% / 23% / 0.3% / 0.0% | 0.3% / 0.2% / 0.3% | 77% |
| 1h | max50 | 44 | 20.00 | 2.38% | $762 (76%) | 76% | 87% / 6% / 7% / 0% | 7% / 7% / 6% | 87% |
| 1h | rec | 36 | 0.71 | 0.10% | $337 (34%) | 102% | 63% / 37% / 0.0% / 0.1% | 0.0% / 0.0% / 0.0% | 63% |
| 4h | tiered | 12 | 6.61 | 0.81% | $682 (68%) | 89% | 88% / 8% / 4% / 0% | 2% / 6% / 9% | 88% |
| 4h | flat20 | 12 | 4.00 | 0.51% | $556 (56%) | 112% | 87% / 11% / 2% / 0% | 2% / 2% / 2% | 87% |
| 4h | max50 | 13 | 20.00 | 2.34% | $764 (76%) | 77% | 90% / 0.3% / 9% / 0% | 9% / 9% / 9% | 90% |
| 4h | rec | 11 | 0.34 | 0.05% | $64 (6%) | 142% | 78% / 22% / 0.1% / 0% | 0.1% / 0.1% / 0% | 78% |

### Minimum average planted drift (at h_e) for: 12m median > $1,000 AND P(12m end < $500) < 20%

Grid search over planted average drift; value = smallest grid point from which the criterion holds at every larger feasible grid point. '> X' = not met up to X, the largest feasible drift (q <= 1 on every coin; concentrated: top-decile q <= 1). Hit-rate = share of trades whose direction matches the sign of the h_e-bar move, (1+q)/2 averaged over coins. Stop 1.5 ATR, TP +10% ROE.  Also shown: the criterion with 'ever below $500' instead of 'end below $500'.

| TF | edge structure | order | tiered | flat 20x20% | max 50x40% | recommended | tiered (ever<$500 < 20%) | rec (ever<$500 < 20%) |
|---|---|---|---|---|---|---|---|---|
| 5m | uniform (score useless) | adv | > 0.300% | 0.250% (hit 75.9%; captured +0.142%) | > 0.300% | 0.250% (hit 75.9%; captured +0.185%) | > 0.300% | 0.300% (hit 81.0%; captured +0.224%) |
| 5m | uniform (score useless) | fav | > 0.300% | 0.250% (hit 75.9%; captured +0.144%) | > 0.300% | 0.250% (hit 75.9%; captured +0.186%) | > 0.300% | 0.300% (hit 81.0%; captured +0.226%) |
| 5m | concentrated (top-10% = 3x) | adv | > 0.100% | > 0.100% | > 0.100% | > 0.100% | > 0.100% | > 0.100% |
| 5m | concentrated (top-10% = 3x) | fav | > 0.100% | > 0.100% | > 0.100% | > 0.100% | > 0.100% | > 0.100% |
| 15m | uniform (score useless) | adv | 0.400% (hit 80.7%; captured +0.192%) | 0.250% (hit 69.2%; captured +0.138%) | > 0.400% | 0.250% (hit 69.2%; captured +0.195%) | 0.400% (hit 80.7%; captured +0.192%) | 0.250% (hit 69.2%; captured +0.195%) |
| 15m | uniform (score useless) | fav | 0.400% (hit 80.7%; captured +0.195%) | 0.250% (hit 69.2%; captured +0.140%) | > 0.400% | 0.250% (hit 69.2%; captured +0.196%) | 0.400% (hit 80.7%; captured +0.195%) | 0.250% (hit 69.2%; captured +0.196%) |
| 15m | concentrated (top-10% = 3x) | adv | > 0.150% | > 0.150% | > 0.150% | > 0.150% | > 0.150% | > 0.150% |
| 15m | concentrated (top-10% = 3x) | fav | > 0.150% | > 0.150% | > 0.150% | > 0.150% | > 0.150% | > 0.150% |
| 1h | uniform (score useless) | adv | 0.500% (hit 76.9%; captured +0.206%) | 0.300% (hit 66.2%; captured +0.148%) | > 0.600% | 0.250% (hit 63.5%; captured +0.190%) | 0.600% (hit 82.3%; captured +0.245%) | 0.250% (hit 63.5%; captured +0.190%) |
| 1h | uniform (score useless) | fav | 0.500% (hit 76.9%; captured +0.207%) | 0.300% (hit 66.2%; captured +0.149%) | > 0.600% | 0.250% (hit 63.5%; captured +0.192%) | 0.600% (hit 82.3%; captured +0.247%) | 0.250% (hit 63.5%; captured +0.192%) |
| 1h | concentrated (top-10% = 3x) | adv | > 0.200% | > 0.200% | > 0.200% | 0.200% (hit 82%/58%; captured +0.153%) | > 0.200% | 0.200% (hit 82%/58%; captured +0.153%) |
| 1h | concentrated (top-10% = 3x) | fav | > 0.200% | > 0.200% | > 0.200% | 0.200% (hit 82%/58%; captured +0.154%) | > 0.200% | 0.200% (hit 82%/58%; captured +0.154%) |
| 4h | uniform (score useless) | adv | 0.800% (hit 75.9%; captured +0.227%) | 0.500% (hit 66.2%; captured +0.177%) | > 1.000% | 0.200% (hit 56.5%; captured +0.151%) | 1.000% (hit 82.4%; captured +0.276%) | 0.200% (hit 56.5%; captured +0.151%) |
| 4h | uniform (score useless) | fav | 0.800% (hit 75.9%; captured +0.229%) | 0.500% (hit 66.2%; captured +0.178%) | > 1.000% | 0.200% (hit 56.5%; captured +0.151%) | 1.000% (hit 82.4%; captured +0.277%) | 0.200% (hit 56.5%; captured +0.151%) |
| 4h | concentrated (top-10% = 3x) | adv | > 0.300% | > 0.300% | > 0.300% | 0.200% (hit 69%/55%; captured +0.155%) | > 0.300% | 0.200% (hit 69%/55%; captured +0.155%) |
| 4h | concentrated (top-10% = 3x) | fav | > 0.300% | > 0.300% | > 0.300% | 0.200% (hit 69%/55%; captured +0.155%) | > 0.300% | 0.200% (hit 69%/55%; captured +0.155%) |

### Edge sweep (adverse-first, stop 1.5 ATR, TP +10% ROE): 12m median / P(end<$500)


5m, uniform:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% | 0.125% | 0.150% | 0.200% | 0.250% | 0.300% |
|---|---|---|---|---|---|---|---|---|---|---|
| tiered | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $3 / 100% | $51 / 94% | $941 / 32% |
| flat20 | $0 / 100% | $0 / 100% | $0 / 100% | $1 / 100% | $3 / 100% | $8 / 100% | $23 / 100% | $201 / 83% | $1,834 / 10% | $16k / 0.0% |
| max50 | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% |
| rec | $2 / 100% | $4 / 100% | $8 / 100% | $15 / 100% | $29 / 100% | $55 / 100% | $110 / 97% | $418 / 58% | $1,652 / 9% | $6,183 / 0.3% |

5m, concentrated:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% |
|---|---|---|---|---|---|
| tiered | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% |
| flat20 | $0 / 100% | $0 / 100% | $0 / 100% | $1 / 100% | $3 / 100% |
| max50 | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% |
| rec | $2 / 100% | $4 / 100% | $9 / 100% | $20 / 100% | $46 / 100% |

15m, uniform:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% | 0.125% | 0.150% | 0.200% | 0.250% | 0.300% | 0.400% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tiered | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $1 / 100% | $2 / 100% | $11 / 100% | $60 / 93% | $343 / 60% | $10k / 2% |
| flat20 | $2 / 100% | $3 / 100% | $6 / 100% | $11 / 100% | $22 / 100% | $43 / 100% | $83 / 97% | $297 / 70% | $1,135 / 20% | $4,348 / 1% | $57k / 0% |
| max50 | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% |
| rec | $115 / 100% | $150 / 100% | $195 / 99% | $253 / 94% | $328 / 83% | $424 / 65% | $540 / 43% | $894 / 10% | $1,514 / 1% | $2,555 / 0.0% | $6,789 / 0% |

15m, concentrated:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% | 0.125% | 0.150% |
|---|---|---|---|---|---|---|---|
| tiered | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $1 / 100% | $2 / 100% | $5 / 100% |
| flat20 | $2 / 100% | $3 / 100% | $6 / 100% | $11 / 100% | $22 / 100% | $43 / 100% | $81 / 97% |
| max50 | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% |
| rec | $115 / 100% | $157 / 100% | $210 / 97% | $291 / 89% | $395 / 70% | $536 / 44% | $716 / 23% |

1h, uniform:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% | 0.125% | 0.150% | 0.200% | 0.250% | 0.300% | 0.400% | 0.500% | 0.600% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tiered | $8 / 100% | $11 / 100% | $15 / 100% | $20 / 100% | $25 / 99% | $33 / 98% | $44 / 97% | $75 / 92% | $134 / 85% | $237 / 73% | $709 / 39% | $2,221 / 11% | $7,523 / 1% |
| flat20 | $83 / 98% | $105 / 97% | $131 / 95% | $166 / 91% | $200 / 86% | $249 / 80% | $306 / 72% | $472 / 53% | $743 / 32% | $1,135 / 16% | $2,730 / 2% | $6,921 / 0.0% | $18k / 0% |
| max50 | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $4 / 98% |
| rec | $669 / 8% | $698 / 5% | $737 / 3% | $776 / 1% | $813 / 0.7% | $855 / 0.3% | $897 / 0.2% | $989 / 0.1% | $1,095 / 0.0% | $1,212 / 0% | $1,485 / 0% | $1,839 / 0% | $2,300 / 0% |

1h, concentrated:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% | 0.125% | 0.150% | 0.200% |
|---|---|---|---|---|---|---|---|---|
| tiered | $8 / 100% | $12 / 100% | $17 / 100% | $23 / 99% | $31 / 99% | $42 / 98% | $56 / 96% | $102 / 90% |
| flat20 | $83 / 98% | $102 / 97% | $130 / 95% | $162 / 91% | $201 / 86% | $239 / 80% | $299 / 72% | $440 / 56% |
| max50 | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% | $0 / 100% |
| rec | $669 / 8% | $703 / 4% | $746 / 2% | $796 / 0.8% | $845 / 0.4% | $892 / 0.1% | $947 / 0.1% | $1,051 / 0.0% |

4h, uniform:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% | 0.125% | 0.150% | 0.200% | 0.250% | 0.300% | 0.400% | 0.500% | 0.600% | 0.800% | 1.000% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tiered | $237 / 78% | $247 / 77% | $257 / 75% | $271 / 74% | $284 / 72% | $300 / 70% | $311 / 69% | $341 / 66% | $378 / 62% | $428 / 57% | $516 / 49% | $645 / 38% | $808 / 30% | $1,272 / 14% | $2,056 / 5% |
| flat20 | $502 / 50% | $518 / 48% | $541 / 45% | $562 / 43% | $579 / 41% | $615 / 38% | $630 / 36% | $686 / 31% | $744 / 27% | $811 / 22% | $965 / 16% | $1,151 / 10% | $1,364 / 5% | $1,998 / 0.9% | $2,931 / 0.0% |
| max50 | $4 / 100% | $5 / 100% | $5 / 100% | $5 / 100% | $5 / 100% | $6 / 100% | $6 / 100% | $8 / 99% | $9 / 99% | $11 / 99% | $16 / 98% | $23 / 97% | $33 / 96% | $67 / 91% | $133 / 82% |
| rec | $955 / 0% | $960 / 0% | $966 / 0% | $971 / 0% | $976 / 0% | $983 / 0% | $989 / 0% | $1,000 / 0% | $1,014 / 0% | $1,025 / 0% | $1,052 / 0% | $1,080 / 0% | $1,104 / 0% | $1,166 / 0% | $1,233 / 0% |

4h, concentrated:

| planted drift | 0.000% | 0.025% | 0.050% | 0.075% | 0.100% | 0.125% | 0.150% | 0.200% | 0.250% | 0.300% |
|---|---|---|---|---|---|---|---|---|---|---|
| tiered | $237 / 78% | $246 / 77% | $256 / 75% | $277 / 73% | $294 / 71% | $310 / 69% | $333 / 67% | $377 / 62% | $426 / 58% | $489 / 51% |
| flat20 | $502 / 50% | $518 / 48% | $537 / 46% | $563 / 43% | $589 / 40% | $614 / 38% | $646 / 35% | $691 / 30% | $755 / 26% | $829 / 21% |
| max50 | $4 / 100% | $4 / 100% | $5 / 100% | $5 / 100% | $5 / 100% | $6 / 100% | $7 / 100% | $8 / 99% | $9 / 99% | $11 / 99% |
| rec | $955 / 0% | $960 / 0% | $968 / 0% | $976 / 0% | $983 / 0% | $989 / 0% | $999 / 0% | $1,013 / 0% | $1,026 / 0% | $1,042 / 0% |

### Sensitivity to intrabar path assumptions (stop 1.5 ATR, TP +10% ROE): 12m median / P(end<$500) / liq per month

'TF bars' = exits resolved on the chart-TF OHLC bars; '5m sub-bars' = resolved on the 5m bars inside them (base). A = adverse-first, F = favourable-first inside a bar.

| TF | scenario | policy | TF bars A | TF bars F | 5m sub-bars A (BASE) | 5m sub-bars F |
|---|---|---|---|---|---|---|
| 15m | S0 | tiered | $0 / 100% / 0.3 | $0 / 100% / 0.2 | $0 / 100% / 0.2 | $0 / 100% / 0.2 |
| 15m | S0 | flat20 | $1 / 100% / 0.0 | $2 / 100% / 0.0 | $2 / 100% / 0.0 | $2 / 100% / 0.0 |
| 15m | S0 | max50 | $0 / 100% / 2.1 | $0 / 100% / 1.4 | $0 / 100% / 1.6 | $0 / 100% / 1.4 |
| 15m | S0 | rec | $113 / 100% / 0.0 | $120 / 100% / 0.0 | $115 / 100% / 0.0 | $118 / 100% / 0.0 |
| 15m | S2 | tiered | $0 / 100% / 0.3 | $1 / 100% / 0.2 | $0 / 100% / 0.2 | $0 / 100% / 0.2 |
| 15m | S2 | flat20 | $18 / 100% / 0.0 | $28 / 100% / 0.0 | $22 / 100% / 0.0 | $25 / 100% / 0.0 |
| 15m | S2 | max50 | $0 / 100% / 1.9 | $0 / 100% / 1.2 | $0 / 100% / 1.4 | $0 / 100% / 1.3 |
| 15m | S2 | rec | $323 / 84% / 0.0 | $343 / 80% / 0.0 | $328 / 83% / 0.0 | $334 / 82% / 0.0 |
| 15m | S4 | tiered | $0 / 100% / 0.2 | $1 / 100% / 0.1 | $1 / 100% / 0.2 | $1 / 100% / 0.1 |
| 15m | S4 | flat20 | $18 / 100% / 0.0 | $28 / 100% / 0.0 | $22 / 100% / 0.0 | $24 / 100% / 0.0 |
| 15m | S4 | max50 | $0 / 100% / 2.0 | $0 / 100% / 1.2 | $0 / 100% / 1.5 | $0 / 100% / 1.3 |
| 15m | S4 | rec | $389 / 71% / 0.0 | $415 / 66% / 0.0 | $395 / 70% / 0.0 | $402 / 69% / 0.0 |
| 1h | S0 | tiered | $1 / 100% / 0.7 | $12 / 100% / 0.4 | $8 / 100% / 0.4 | $9 / 100% / 0.4 |
| 1h | S0 | flat20 | $48 / 100% / 0.2 | $99 / 98% / 0.1 | $83 / 98% / 0.1 | $85 / 98% / 0.1 |
| 1h | S0 | max50 | $0 / 100% / 4.8 | $0 / 100% / 2.6 | $0 / 100% / 2.9 | $0 / 100% / 2.8 |
| 1h | S0 | rec | $647 / 10% / 0.0 | $686 / 6% / 0.0 | $669 / 8% / 0.0 | $672 / 7% / 0.0 |
| 1h | S2 | tiered | $3 / 100% / 0.6 | $38 / 98% / 0.3 | $25 / 99% / 0.4 | $28 / 99% / 0.4 |
| 1h | S2 | flat20 | $119 / 95% / 0.1 | $243 / 81% / 0.1 | $200 / 86% / 0.1 | $207 / 86% / 0.1 |
| 1h | S2 | max50 | $0 / 100% / 4.5 | $0 / 100% / 2.4 | $0 / 100% / 2.7 | $0 / 100% / 2.6 |
| 1h | S2 | rec | $798 / 0.8% / 0.0 | $845 / 0.4% / 0.0 | $813 / 0.7% / 0.0 | $818 / 0.6% / 0.0 |
| 1h | S4 | tiered | $5 / 100% / 0.6 | $44 / 98% / 0.3 | $31 / 99% / 0.4 | $35 / 99% / 0.3 |
| 1h | S4 | flat20 | $119 / 95% / 0.1 | $240 / 81% / 0.1 | $201 / 86% / 0.1 | $206 / 86% / 0.1 |
| 1h | S4 | max50 | $0 / 100% / 4.5 | $0 / 100% / 2.4 | $0 / 100% / 2.7 | $0 / 100% / 2.6 |
| 1h | S4 | rec | $825 / 0.6% / 0.0 | $872 / 0.3% / 0.0 | $845 / 0.4% / 0.0 | $849 / 0.3% / 0.0 |
| 4h | S0 | tiered | $13 / 100% / 1.0 | $294 / 70% / 0.4 | $237 / 78% / 0.5 | $245 / 77% / 0.5 |
| 4h | S0 | flat20 | $207 / 88% / 0.5 | $525 / 47% / 0.3 | $502 / 50% / 0.3 | $507 / 49% / 0.3 |
| 4h | S0 | max50 | $0 / 100% / 3.7 | $18 / 98% / 0.9 | $4 / 100% / 1.2 | $5 / 100% / 1.2 |
| 4h | S0 | rec | $935 / 0% / 0.0 | $962 / 0% / 0.0 | $955 / 0% / 0.0 | $955 / 0% / 0.0 |
| 4h | S2 | tiered | $17 / 100% / 1.0 | $356 / 63% / 0.4 | $284 / 72% / 0.4 | $294 / 72% / 0.4 |
| 4h | S2 | flat20 | $244 / 83% / 0.5 | $611 / 38% / 0.2 | $579 / 41% / 0.3 | $585 / 41% / 0.3 |
| 4h | S2 | max50 | $0 / 100% / 3.6 | $25 / 97% / 0.9 | $5 / 100% / 1.2 | $6 / 100% / 1.1 |
| 4h | S2 | rec | $954 / 0% / 0.0 | $981 / 0% / 0.0 | $976 / 0% / 0.0 | $976 / 0% / 0.0 |
| 4h | S4 | tiered | $19 / 100% / 0.9 | $364 / 62% / 0.4 | $294 / 71% / 0.4 | $302 / 71% / 0.4 |
| 4h | S4 | flat20 | $248 / 82% / 0.5 | $627 / 37% / 0.2 | $589 / 40% / 0.3 | $593 / 39% / 0.3 |
| 4h | S4 | max50 | $0 / 100% / 3.6 | $25 / 97% / 0.9 | $5 / 100% / 1.1 | $7 / 100% / 1.1 |
| 4h | S4 | rec | $961 / 0% / 0.0 | $990 / 0% / 0.0 | $983 / 0% / 0.0 | $984 / 0% / 0.0 |
