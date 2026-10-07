"""Write resume/lens2_sizing.json from the computed tables (numbers typed below were read from out/*.csv printed by
s1/s2b/s3/s4/s5/s6/s7; see 'evidence' fields for the file of each).
    python3 -I -B s9_write_json.py <workdir> <json_out>"""
import json
import os
import sys

W, OUTP = sys.argv[1], sys.argv[2]
O = os.path.join(W, "out")

findings = [
 dict(id="Z1",
      claim="The rule bot's 'margin = leverage % of equity' puts notional at L^2/100 x equity, so one stop-out costs "
            "L^2/100 x (stop% + about 0.12%) of the account: 5 to 15% at 20-40x in today's market, and 20x is the only "
            "level near the owners' 2-5% band. The 15% max-loss check, not the leverage choice, is what caps it.",
      evidence="s1_feas.py -> out/s1_feasibility.csv (loss at the stop with fees + exit slippage, size_position formula; "
               "parity with paperbot.sizing.size_position 7,200/7,200, t_parity.py). Median loss per stop-out, % equity, "
               "20/30/40/50x: 5y every signal of the 36 locked strategies 2021-08..2026-09 (n 1,140,789 at 15m) "
               "15m 4.5/10.1/18.0/28.1, 30m 6.3/14.1/25.1/39.2, 1h 8.9/20.0/35.6/55.6, 4h 18.0/40.6/72.2/112.8; live "
               "(v3b+v4 every submitted signal, 15m n 2,255, stop median 0.61%) 15m 2.9/6.6/11.7/18.3, 30m "
               "3.9/8.8/15.6/24.4, 1h 5.3/12.0/21.3/33.2. Realised live SL exits (s5_live.py -> out/s5_live_stopouts.csv): "
               "15m 30x median -6.8% of equity (n 307, worst -14.9%), 15m 40x -12.1% (n 38), 30m 30x -8.7% (n 175), "
               "1h 30x -10.2% (n 81), 4h 20x -9.7% (n 16). Round-trip taker+slippage (0.14% of notional) = 0.56/1.26/"
               "2.24/3.5% of equity per trade at 20/30/40/50x; live median fee+slip 0.9% of equity at 30x, 2.0% at 50x.",
      confidence="high",
      implication="The current rule-bot sizing and the '2-5% per stop' alternative are not variants of one rule: the rule "
                  "bot risks 2-5x more per stop at 30x and 4-9x more at 40-50x. Any AI trader built on 'margin = L%' "
                  "inherits 7-15% per stop-out."),
 dict(id="Z2",
      claim="Which leverage is executable is set by the stop distance, not by the AI. At 50x the liquidation is about "
            "1.6% away, so a 2 ATR stop plus the 1 ATR buffer must be under about 1.07%. Over 5 years 50x fits about "
            "half of 15m signals, a quarter of 30m, 8% of 1h and almost no 4h; 20x fits only 20% of 4h signals. Under "
            "the margin rule the 15% loss check also blocks most 40-50x trades, and LTC/BCH never get 50x.",
      evidence="out/s1_feasibility.csv, s1_feasibility_by_year.csv (inferred brackets of analyze.py, live settings: "
               "buffer max(1 ATR, 0.2%), max loss 15%). Executable share at exactly 20/30/40/50x, risk rule (2% per stop; "
               "only liq buffer + bracket + margin <= equity bind): 5y 15m 98/89/72/52%, 30m 93/72/45/25%, 1h "
               "79/43/19/8%, 4h 20/3.5/0.7/0.15%; live now 15m 100/100/99.6/96%, 30m 100/100/95/67%, 1h 100/98/61/36%, "
               "4h 100/43/0/0% (n 79). Margin rule, all checks: 5y 15m 98/81/36/7%, 30m 92/57/14/2%, 1h 77/27/4/0.4%, "
               "4h 19/1/0/0%; at 50x the 15% check passes only 8.9% of 5y 15m signals. A 'best' signal walking "
               "50->40->30->20 gets 50x 7%, 40x 28%, 30x 45%, 20x 17% (5y 15m). By year (15m, risk rule 50x): 2021 25%, "
               "2022 37%, 2023 66%, 2024 50%, 2025 50%, 2026 70%. By coin (5y 15m, risk rule 50x): BTC 84%, ETH 66%, "
               "BCH 48%, LTC 50%, DOGE 31%, SOL 31%; at 5% risk LTC/BCH fall to 30%/28% (bigger notional -> higher "
               "mmr bracket). Margin rule at 50x: LTC/BCH 0% (bracket allows 40x above $100k/$50k notional; 50x x 50% of "
               "$5,000 = $125k). minNotional: irrelevant at $5,000; exchangeInfo could not be fetched (proxy 403).",
      confidence="high",
      implication="'Confidence -> 50x' cannot be honoured on most 30m/1h signals or in any volatile week; the code, not the "
                  "AI, must choose the leverage from the stop. '4h only where 20x is executable' means about one 4h signal "
                  "in five over 5 years (all of them in today's quiet market)."),
 dict(id="Z3",
      claim="At the same stop and the same risk per stop, the leverage changes almost nothing about expected R. It "
            "changes the margin posted, the liquidation distance and, through the ROE-based ladder, the shape of the "
            "exits: more small wins and smaller losses at 50x, larger wins at 20x. It does not change fees per unit of "
            "risk.",
      evidence="s2_rerun.py (profiles._scan at fixed 10/20/30/40/50x; parity with lens/fiveyear fy36 v4n R at 30x/20x "
               "max abs diff 0.0) -> s2b_levR.py -> out/s2b_lev_R.csv, signals executable at 20x, paired, week-cluster "
               "bootstrap. 15m (n 1,115,360): mean R 20x -0.172, 30x -0.171, 40x -0.171, 50x -0.169 (50x-20x +0.003 "
               "[-0.001, +0.007]); cost 0.174R vs 0.170R; win rate 52% -> 57%, mean win +0.69R -> +0.38R, mean loss "
               "-1.12R -> -0.91R. 30m (n 531,987): -0.125 -> -0.118 (+0.007 [+0.003, +0.011]). 1h (n 226,400): -0.092 -> "
               "-0.080 (+0.012 [+0.006, +0.017]). 4h (n 14,127): -0.053 -> -0.035 (+0.018 [+0.005, +0.032]). Isolated "
               "margin under the risk rule is r/(L x (stop+cost)): 5y 15m median 3.7% of equity at 50x vs 9.2% at 20x "
               "(r = 2%), which caps a gap loss. Liquidation distance is about 1/L - mmr (BTC 50x 1.6%, 20x 4.6%). No "
               "gap liquidation in any executable 5y trade under the risk rule (s3_sequences.csv liq_gaps 0). The live "
               "d3 'lev10 +0.26R' what-if is not reproduced: 5y 10x vs 20x at 15m +0.004R [-0.003, +0.011].",
      confidence="high for mean R and costs; medium for tail (no mark-price or 1m data)",
      implication="With risk-per-stop sizing, 20-50x is mostly a margin and liquidation setting. Higher leverage posts "
                  "less margin, so it slightly lowers the worst-case loss as long as the stop sits inside the liquidation "
                  "buffer. If the exits are written in R or price terms instead of ROE, leverage stops changing the exits."),
 dict(id="Z4",
      claim="Under the current margin = L% rule, a one-position 15m+30m trader without proven edge most likely loses "
            "half its account by 12/31 at any leverage 20-50x. Even at zero net edge the chance of falling below 50% "
            "is 23% at 20x and 55-71% at 30-50x.",
      evidence="s3_traders.py -> out/s3_paths.csv, s6_summary.py -> out/s6_paths_summary.csv. 34 strategies (35 in the "
               "cache, N21 has no signals, one strategy < 30 trades), one position across six coins, every executable "
               "signal (median 3.8-4.3 trades/day at 15m+30m), outcomes = 5y house exit at the leverage used, 1,000 "
               "paths of circular 7-day blocks of 1,886 days. Mean over strategies of P(equity < 50% at any trade) to "
               "12/31 (76 days), M20/M30/M40/M50: edge = -cost 83/90/91/91% (median end x0.14/0.013/0.004/0.003); edge "
               "0 net 23/55/68/71%; edge +0.1R 1.0/8.3/16.6/19.7%. One month (30 days): -cost 58/81/84/85%, 0 net "
               "9.5/36/48/52%, +0.1R 0.6/6.4/13/16%. P(< 25%) to 12/31 at 0 net: 4/30/46/51%. 1h alone (about 0.9 "
               "trades/day) at 0 net: 18/30/32/32%. Live check: v3a (2.6 days, mostly 50x / 40% margin) 12.5% of 15m "
               "and 47% of 5m strategy accounts ended below 50% (out_real/account_stats.csv).",
      confidence="high (direction and size); exact percentages depend on the bootstrap and the imposed edges",
      implication="Do not give AI traders the rule bot's margin = L% sizing. Even a real +0.1R edge would carry a "
                  "1-in-12 (30x) to 1-in-5 (50x) chance of halving the account before 12/31."),
 dict(id="Z5",
      claim="With risk-per-stop sizing, ruin depends on edge x frequency, not on leverage. At zero net edge, 1-2% per "
            "stop is safe to 12/31 and 5% is not. If the edge is only what the rules show (gross 0, net -cost), 2% per "
            "stop loses half the account by 12/31 in about 65% of 15m+30m paths, and even 1% ends near x0.66.",
      evidence="out/s6_paths_summary.csv, policy K30 (requested 30x, walk down to 20x), 15m+30m, mean over 34 strategies, "
               "76 days: r = 1/2/3/5%: edge -cost P(<50%) 20/65/78/85% (median end x0.66/0.43/0.27/0.10), P(<25%) "
               "0/22/50/75%; edge 0 net 0/2.2/11/33% (P(<25%) 0/0/0.5/8.3%); edge +0.1R 0/0/0.1/1.6% (median end "
               "x1.35/1.78/2.31/3.67). One month: -cost 0/12/37/66%, 0 net 0/0.1/1.8/13.5%. Requested 50x instead of 30x "
               "changes P(<50%) at r 2%, 0 net from 2.2% to 1.7% (15m+30m), i.e. leverage does not matter. Thinned "
               "to about 2 trades/day (same 28 high-frequency strategies, s7_thin.py -> out/s7_thin_vs_full.csv), edge "
               "-cost r 2%: 7.5% vs 79% for the full sequence; r 3%: 45% vs 94%. 1h: -cost r2 0.6%, r5 28%; 4h ~0%.",
      confidence="medium-high",
      implication="Pick risk from the evidence on edge, not from the leverage wish. Today's evidence (cost lens: 15m/30m "
                  "gross edge about 0, cost 0.16-0.24R per trade) supports 1% per stop at most. 2% is defensible only "
                  "with fewer trades (the AI skipping) or a measured positive edge, and 5% is not defensible."),
 dict(id="Z6",
      claim="Without an edge, the loss comes from steady cost drag, not from bad luck. Expected loss per day = trades/day "
            "x cost (in R) x risk per stop. Sizing chooses how fast a cost-negative trader bleeds; no sizing makes it "
            "safe.",
      evidence="s3_sequences.csv / s6_sequences_summary.csv: 15m+30m K30 median 4.3 trades/day, mean cost 0.15R -> 0.64R "
               "per day; at r 1% that is -0.64% per day, x0.62 over 76 days compounded (bootstrap median x0.66). 15m alone "
               "3.6 trades/day x 0.166R; 30m 2.0 x 0.119R; 1h 0.93 x 0.091R; 4h 0.14 x 0.071R. Per-strategy drag in "
               "strategy_notes (0.0-0.9R/day).",
      confidence="high",
      implication="An AI trader at 15m needs to add more than the cost (0.15-0.17R per trade) before any size above 1% "
                  "makes sense. The sizing decision should come after a positive R-based track record, and the trader "
                  "should be scored in R, not in $ or ROE."),
 dict(id="Z7",
      claim="On the crash days, risk-per-stop sizing loses a few percent, while the margin rule loses tens of percent "
            "and a single slipped stop can take the whole 30-40% margin.",
      evidence="s4_crash.py -> out/s4_crash_summary.csv, s4_crash_traders_agg.csv, s4_crash_market.csv. Every signal of "
               "the 36 entered on the day or the 24 h before; nominal = engine fill, pessimistic = worst 5m print after "
               "the stop is crossed (upper bound). 2025-10-10 15m (n 1,156 at 20x): worst trade R -1.33 nominal / -3.98 "
               "pessimistic; worst single trade % equity: risk 2% at 20x -2.1% / -6.8%, at 50x -2.0% / -4.7%; margin "
               "30x -15% / -30% (whole margin), 40x -15% / -40%. One-position traders over the 48 h (32 strategies, "
               "15m): risk 2% worst -12% / -23%; margin 30x worst -48% / -85%, 35% of traders lose >= 25% (pessimistic). "
               "2022-11-08 15m: risk 2% worst -7% / -12%; margin 30x worst -46% / -69%, 21% lose >= 25%. 2022-06-13 "
               "15m margin 20x worst -37% / -50%. 2024-08-05 30m margin 20x worst -49% / -61%. 2021-05-19 (before the "
               "5y window; cache bars from 2021-01): ATR was so large that the margin rule fell to 20x (M30 traded 5 "
               "signals). Market: 2025-10-10 DOGE day low -66%, LTC -59% vs the open, largest 15m bar 22-23 ATR; "
               "2021-05-19 ETH/DOGE/BCH -59 to -69%.",
      confidence="medium (no 1m / mark-price data; pessimistic fills are a bound, nominal fills are optimistic)",
      implication="Size so that a 3-4R slipped stop is survivable: at 1-2% risk that is a 4-8% hit. Prefer the highest "
                  "leverage at which the stop still fits, because isolated margin then caps a disaster gap (r/L of notional)."),
 dict(id="Z8",
      claim="'Confidence -> risk %' is the better design, and only if confidence carries information. 'Confidence -> "
            "leverage' does nothing at a fixed risk per stop. Under the margin rule it scales risk with L^2 (6.25x from "
            "20x to 50x) and does worse than flat 30x when confidence is uninformative.",
      evidence="s3_traders.py confidence(): K30 trade sequences, same exits for every design, confidence 1-5 uniform per "
               "trade; null = independent of the outcome, info = E[R|c] shifted 0.05R per level (c5 +0.1R, c1 -0.1R, mean "
               "unchanged). out/s6_confidence_summary.csv, 15m+30m, 76 days, mean over 34 strategies, P(<50%) / median "
               "end: edge 0 net, null: margin 20-50x by confidence 64% / x0.58 vs flat 30x 55% / x0.77; risk 2-5% by "
               "confidence 18.6% / x0.94 vs flat 3.5% 16.7% / x0.94 vs flat 2% 2.2% / x0.99. info: risk 2-5% 9.9% / x1.18 "
               "vs flat 3.5% 16.9% / x0.94; margin 20-50x 54% / x0.97. edge -cost, null: risk 2-5% 81% vs flat 2% 65%; "
               "margin 20-50x 91%. edge +0.1R: risk 2-5% info 0.1% / x3.3, margin 20-50x info 9.6% / x18 (gamble).",
      confidence="medium (the confidence model is synthetic; there is no AI confidence data yet)",
      implication="Map confidence to a narrow risk band, never to leverage under margin = L%. Use flat risk until the "
                  "trader's own confidence-vs-R record shows it is informative (for example Spearman > 0 over 200+ "
                  "trades in the shadow account). With uninformative confidence a 2-5% band behaves like a flat 3.5%, "
                  "which is too much at zero edge."),
 dict(id="Z9",
      claim="Recommended rule: risk per stop decides size, and leverage is chosen by code as the highest of 50/40/30/20x "
            "at which the stop sits inside the liquidation buffer. This keeps the owners' 20-50x on every trade where "
            "it is safe and makes the leverage harmless.",
      evidence="Z1-Z8. Under this rule, at 1% per stop the 5y one-position 15m+30m trader has P(<50%) to 12/31 of 0% at "
               "0 net edge and 20% if the edge is only -cost (median x0.66); at 2% it is 2.2% and 65%. Leverage choice "
               "(K20 vs K50) moves these by up to about 9 points (-cost, r 2%: 60% vs 69%), only because more signals become executable at 50x (3.8 vs 4.6 trades/day), not because a single trade loses more.",
      confidence="medium-high (mechanics high; ruin numbers depend on the edge the AI actually adds)",
      implication="See report_section_md for the concrete rule. Evidence level: arithmetic and executability high (5y + "
                  "live, exact parity with the repo's sizing); ruin by bootstrap medium; benefit of confidence scaling "
                  "unknown until measured."),
 dict(id="Z10",
      claim="Brackets and liquidation used here are the ones analyze.py inferred from the live trades. They fit every "
            "live liquidation price exactly, but they only cover the notional sizes actually traded.",
      evidence="analyze.py INFERRED_BRACKETS, out_real/brackets_check.csv (1,980 trades without funding, max rel err "
               "1.2e-15): BTC/ETH mmr 0.4% flat; SOL 0.5% to $50k then 0.65%; DOGE 0.65% to $80k then 1%; BCH 0.5/1/1.25% "
               "at $10k/$100k with 40x above $100k; LTC 0.5/1/1.5% at $10k/$50k with 40x above $50k. Risk-rule notionals "
               "(about 2-5x equity) stay in the low tiers; margin-rule notionals at 40-50x ($80-125k on $5,000) hit "
               "the 40x caps. Binance exchangeInfo / leverageBracket could not be read here (proxy 403).",
      confidence="high for the paper accounts; medium for a real account",
      implication="Before real money, load the account's real leverageBracket and minNotional (paperbot/binance.py "
                  "already does) and rerun s1_feas.py with them."),
]

notes_all = json.load(open(os.path.join(O, "strategy_notes.json")))
notes = [n for n in notes_all if n["timeframe"] in ("15m+30m", "1h")]

files = [os.path.join(W, f) for f in ("common.py", "t_parity.py", "s1_feas.py", "s2_rerun.py", "s2b_levR.py",
                                      "s3_traders.py", "s4_crash.py", "s5_live.py", "s6_summary.py", "s7_thin.py",
                                      "s8_notes.py", "s9_write_json.py")]
files += [os.path.join(O, f) for f in ("s1_feasibility.csv", "s1_feasibility_by_year.csv", "s2b_lev_R.csv",
                                       "s3_paths.csv", "s3_sequences.csv", "s3_confidence.csv", "s6_paths_summary.csv",
                                       "s6_sequences_summary.csv", "s6_confidence_summary.csv", "s7_thin_vs_full.csv",
                                       "s4_crash_market.csv", "s4_crash_summary.csv", "s4_crash_traders.csv",
                                       "s4_crash_traders_agg.csv", "s5_live_stopouts.csv", "s5_live_by_coin.csv",
                                       "strategy_notes.json")]
files.append(os.path.join(O, "lev", "lev_{15m,30m,1h,4h}.pkl (5y per-signal outcomes at fixed 10-50x, both rules' liquidation, executability flags)"))

limits = [
 "Trade outcomes are the house exit (2 ATR stop + ROE ladder) on every executable signal, taken one position at a "
 "time. The AI will skip, exit early and switch timeframes, so its frequency and outcome shape will differ. The "
 "thin2 variant (about 2 trades/day) brackets the frequency effect.",
 "Edge scenarios shift every trade's R by a constant (net0: R - mean; -cost: gross R demeaned minus the trade's own "
 "cost; +0.1R). This keeps the 5-year shape and does not model an edge that changes win rate or tails.",
 "The bootstrap uses circular 7-day blocks of 1,886 calendar days (2021-08-01..2026-09-30). Regimes longer than a "
 "week are only partly kept, and the 34 strategies' ruin probabilities are not independent (same coins, same days). "
 "Ruin is checked at every trade. Drawdown peaks are taken at day starts, so intraday peaks are missed (max drawdown "
 "is slightly understated).",
 "The 5-year engine fills stops at the stop price unless a bar opens through it (optimistic in wicks) and uses trade "
 "price, not mark price, for liquidation. The crash-day pessimistic fill (worst 5m print) is an upper bound. No 1m "
 "data and no order-book depth for 2021-2025 crashes, and no exchange outages or API failures are modelled.",
 "2021-05-19 is before the 5-year window and is replayed from the cache's earlier bars (signals warm up from "
 "2021-01). 2022-11-08/09 are treated as two UTC days.",
 "Brackets are inferred from the live trades (exact there). minNotional and lot steps for real money could not be "
 "fetched (exchangeInfo proxy 403); qty steps were inferred from the live trades (BTC 0.001 = about $86).",
 "The confidence experiment is synthetic. There is no AI confidence data yet. 'info' assumes a linear 0.05R per "
 "level, which is an assumption and not a measurement.",
 "Fixed-fraction compounding with no daily loss cap or drawdown kill switch was simulated. A kill switch would cap "
 "ruin by construction but not change the expected drift.",
 "Funding is 0.01% per 8 h paid by both sides, as in the research. The live quiet market (15m stop median 0.61%) is "
 "narrower than the 5-year median (0.99%), so live executability is the optimistic end.",
]

report = r"""
## Lens 2 - Sizing: leverage 20-50x, risk per stop, drawdown and ruin

**Bottom line.** The rule bot's sizing ("margin = leverage % of equity") is not "20-50x with some risk". It puts
notional at L^2/100 x equity, so one stop-out costs **5-15% of the account at 20-40x** (live 15m 30x realised median
-6.8%, worst -15%). On the 5-year data a one-position 15m+30m trader under that rule halves its account before 12/31
in **55-71% of paths at zero net edge** (30-50x) and in **about 90%** if the edge is only what the rules show. Sizing by
**risk per stop** and letting code pick the leverage keeps the owners' 20-50x wherever the stop fits. At 1% per stop
the same trader has **0%** chance of halving at zero edge (20% if the edge is only -cost).

### 1. Loss per stop-out and executability
Median loss per stop-out, % of equity, by leverage (margin = L% rule):

| tf | stop median (5y / live) | 20x | 30x | 40x | 50x |
|---|---|---|---|---|---|
| 15m | 0.99% / 0.61% | 4.5 / 2.9 | 10.1 / 6.6 | 18.0 / 11.7 | 28.1 / 18.3 |
| 30m | 1.43% / 0.87% | 6.3 / 3.9 | 14.1 / 8.8 | 25.1 / 15.6 | 39.2 / 24.4 |
| 1h | 2.08% / 1.23% | 8.9 / 5.3 | 20.0 / 12.0 | 35.6 / 21.3 | 55.6 / 33.2 |
| 4h | 4.37% / 1.99% | 18.0 / 9.3 | 40.6 / 20.8 | 72.2 / 37.0 | 112.8 / 57.8 |

Share of signals where each leverage is executable (stop inside liquidation by max(1 ATR, 0.2%), bracket, and for the
margin rule the 15% max loss). Risk rule at 2% / margin rule, 5 years:

| tf | 20x | 30x | 40x | 50x | live now (risk rule) 20/30/40/50x |
|---|---|---|---|---|---|
| 15m | 98 / 98 | 89 / 81 | 72 / 36 | 52 / 7 | 100 / 100 / 99.6 / 96 |
| 30m | 93 / 92 | 72 / 57 | 45 / 14 | 25 / 2 | 100 / 100 / 95 / 67 |
| 1h | 79 / 77 | 43 / 27 | 19 / 4 | 8 / 0.4 | 100 / 98 / 61 / 36 |
| 4h | 20 / 19 | 3.5 / 1 | 0.7 / 0 | 0.15 / 0 | 100 / 43 / 0 / 0 |

50x needs a 2 ATR stop under about 1.07%. BTC qualifies most often (5y 15m 84%) and SOL/DOGE least (31%). Under the
margin rule LTC/BCH never get 50x (the bracket allows 40x above $50-100k notional). "4h only where 20x fits" means
about one 4h signal in five over 5 years.

### 2. Drawdown and ruin (5-year day-block bootstrap, one position, 15m+30m, mean of 34 strategies)
P(equity < 50% at any point) by 12/31 (76 days); one month in brackets:

| sizing | edge = -cost (what the rules show) | edge = 0 net | edge = +0.1R |
|---|---|---|---|
| risk 1% / stop | 20% (0%) | 0% (0%) | 0% (0%) |
| risk 2% | 65% (12%) | 2.2% (0.1%) | 0% (0%) |
| risk 3% | 78% (37%) | 11% (1.8%) | 0.1% (0%) |
| risk 5% | 85% (66%) | 33% (13.5%) | 1.6% (1.0%) |
| margin = L%, 20x | 83% (58%) | 23% (9.5%) | 1.0% (0.6%) |
| margin = L%, 30x | 90% (81%) | 55% (36%) | 8.3% (6.4%) |
| margin = L%, 40x | 91% (84%) | 68% (48%) | 17% (13%) |
| margin = L%, 50x | 91% (85%) | 71% (52%) | 20% (16%) |

Median 3.8-4.3 trades/day. Halving the frequency to about 2/day (the AI skipping) cuts the -cost, 2% ruin from 79% to
7.5% on the same strategies. With no edge the loss is a steady drift: trades/day x cost (0.15R) x risk. 1h is much
milder (0.9 trades/day: -cost, 2% -> 0.6%). 4h is about 0%, but few trades fit.

**Crash days** (every signal on the day and the 24 h before; nominal / pessimistic = worst 5m print): 2025-10-10 15m,
worst single trade at risk 2% -2.1% / -6.8% of equity (at 50x -4.7%, because isolated margin caps the loss), margin 30x
-15% / -30% (whole margin), 40x up to -40%. Worst one-position trader over 48 h: risk 2% -12% / -23%; margin 30x -48% /
-85%, and 35% of traders lose 25% or more. 2022-11-08: risk 2% worst -7% / -12%, margin 30x -46% / -69%.

### 3. What leverage does at the same risk per stop
Leverage does not change mean R (5y, paired, 50x vs 20x: 15m +0.003R [-0.001, +0.007], 30m +0.007, 1h +0.012) or fees
per unit of risk (15m cost 0.174R vs 0.170R). It changes only (a) the margin posted (15m, 2% risk: 3.7% of equity at 50x
vs 9.2% at 20x), (b) the liquidation distance (1.6% vs 4.6% on BTC), and (c) the exit shape through the ROE ladder
(15m win rate 52% -> 57%, mean win 0.69R -> 0.38R). "Confidence -> leverage" therefore does nothing at a fixed risk, and
under margin = L% it scales risk with L^2. In the synthetic test with **uninformative confidence**, 20-50x by
confidence did worse than flat 30x (0 net edge: ruin 64% vs 55%). 2-5% risk by confidence behaved like a flat 3.5%
(19% vs 17%; flat 2%: 2%). Confidence scaling helps only if confidence predicts R (+0.05R per level: 2-5% band 9.9% vs
flat 3.5% 16.9%).

### 4. Recommended sizing rule for the AI traders (evidence: mechanics high, ruin medium, confidence value unknown)
1. **Size by risk per stop:** qty = r x equity / (|entry - stop| + fees and slippage at the stop). Use **r = 1%** for
   15m/30m entries (at most 1.5% for 1h/4h) until the trader's own R record over 100+ trades is positive after costs.
   Then allow up to 2%. Never use 5%, and never use margin = L% of equity.
2. **Leverage chosen by code, 20-50x:** use the highest of 50/40/30/20x at which the stop sits inside the liquidation
   price by max(1 ATR, 0.2%), the exchange bracket allows it, and margin <= equity. The AI's confidence may only lower
   this cap. If not even 20x fits (most 4h, 21% of 1h), skip the trade, or use 10-19x with the same risk if the owners
   accept leverage below 20x. Leverage then never changes the loss at the stop. It only sets the margin, which keeps
   a disaster gap capped at r / (L x stop) of the account.
3. **Exits in R or price, not ROE,** so that the leverage does not quietly move the profit locks (today's ROE ladder
   arms its first lock at about 0.6R at 50x and 1.2R at 20x on today's typical 15m stop of 0.61%).
4. **Confidence -> risk only within a narrow band** (e.g. 0.75 / 1.0 / 1.25%), switched on only after the shadow
   account shows confidence vs R is positive (for example Spearman > 0, p < 0.05 over 200+ trades). Until then, keep
   risk flat.
5. **Guards:** halt the trader for the day after -3R, and review or halt it at -15% from its start. Score traders in R,
   not $ or ROE.
"""

out = dict(findings=findings, strategy_notes=notes, files=files, limits=limits, report_section_md=report.strip())
json.dump(out, open(OUTP, "w"), indent=1, ensure_ascii=False)
print("written", OUTP, len(findings), len(notes), len(files))
