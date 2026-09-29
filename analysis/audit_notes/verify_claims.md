# Verifier notes: "claims" auditor (HANDOFF §2-§4)

Scratch: this dir. bt/ is a copy of the project bt/. The only change is in run.py: a `--slip` flag at lines 109 and 113.
Scripts are in work/. My rerun outputs are in results/: the 5m run at fee 0.01% with slip 0, and the single-path synthetic IS/ALL runs.
Inputs: the repro trades at scratchpad/repro/results, plus the delivered results/.

## CLM-1 Sept 5-13 single account (work/v_sept.py, work/v_sept_broad.py)
- V45_EXACT_AMB_G1 x L50_sl15 using portfolio.single_account(lev 50, margin 0.4). Net is shifted by 2*(0.0005-fee). This is valid because fees do not affect exit paths: engine.py:127-129 is the only place fees enter.
- UTC 09-05..09-13 inclusive: n=62. At 0.05%: WR 0.419, final 147.4. At 0.02%: final 274.1. At 0.01%: WR 0.452, final 336.5.
- Window from KST 09-05 00:00 to UTC 09-13 12:00: n=59. At 0.05%: WR 0.424, final 175.1. At 0.01%: WR 0.458, final 380.1, with 47 taken.
- Grid search: starts 09-04 00:00..09-05 23:00 UTC hourly, ends 09-12 12:00..09-14 23:00 hourly, 5 fees.
  - With n=59, the final equity range is 147.5-205.8 at 0.05% and 326-453 at 0.01%.
  - Searching all 52 strategy x exit combos, the only match for n~59 / WR~46% / final 370-390 is L50_sl15 at fee 0.01%. AMB and AMB_G1 are identical in this window.
- Verdict: the numbers are CONFIRMED.
  - Severity is lower than the auditor's "medium". Using the report's own 0.01% fee is the right like-for-like choice when cross-checking that report.
  - The defect is that the fee (and window) are not stated, and the 0.05% figure (about 175) is missing. The handoff's conclusion from this check is unchanged.

## CLM-2 V4.5 64-bar drift (work/v_fwd.py, v_fwd_robust.py, v_fwd_compl.py)
- forward.forward_stats reproduces forward_ALL_5m_v45.csv to 4.4e-16.
- AMB fwd64: n=1641, mean +0.1353%, naive pooled t 4.98.
  - Pooled day-clustered t is 2.29 (G=135).
  - Per symbol, day-clustered t: BTC 1.64, ETH 1.72, SOL 1.86.
  - Thinned (>=64 bars apart) t: 1.63, 1.80, 1.95.
  - Side-drift baseline is about 0 (below 0.005%).
  - Circular-shift placebo (sides and cluster structure kept, 3000 draws): mean 0.002%, sd 0.060%, one-sided p = 0.019, z 2.23.
- Signals in ANY but not AMB (n=7,427): +0.104%, clustered t 2.43. So the drift is a property of V4.5 signals in general, not of AM+B.
- V45_ANY as a whole: +0.110%, clustered t 2.55. Its thinned per-symbol t is weak (0.66/0.48/1.81).
- The auditor's 15m fwd64 comparison has the wrong horizon: 64 x 15m = 16h, against 5.3h for 5m. The fair comparison is 15m fwd32 (8h). There S6 is +0.139% and N17 is +0.137% (15,082 signals), so "유일한" still fails.
- fwd16 on 5m AMB is only +0.032% (clustered t 1.26).
- Verdict: PARTIALLY CONFIRMED, medium. It affects the "only faint signal" clause and the motivation for option B, not the 0-pass result.

## CLM-3 §2 fee delta arithmetic
- 1725+55 = 1780. 1780/56 = 31.79 per trade, which gives 31.79/0.0008 = 39.7k notional. At 100k notional the result would be -2,755. The arithmetic is correct.
- The 100k premise (5,000 x 40% x 50x) is the auditor's assumption. The RC2 sizing is not in the package.
- Back-solving notional from the report's own P&L (+1,724, 56 trades, 75% WR) depends on the assumed average win:
  - With the simulated ladder economics (LOCK net +0.139%, SL -0.341% at 0.01% fee), per trade is +0.019%, which implies about 159k notional.
  - With a win of 0.20% and a loss of 0.32%, it implies about 44k.
- So the data cannot tell 40k from 100k. Either way the candidate is negative at real fees, which supports the handoff. Verdict: PARTIALLY CONFIRMED, low.

## Minor findings: all re-derived
- CLM-4: 364 combos contain 900,334 trades. The 338 non-G1 combos contain 851,035. The summary file has 28 strategies, including N14/N21 with zero trades and no G1. The pooled file has 28 strategies (26 + 2 G1). CONFIRMED.
- CLM-5: pre-cost (exp_gross) range.
  - Best exit per strategy: -0.1147 (V39_SR) to +0.0551. tables_15m.md T1 itself prints -0.115.
  - All combos: -0.140 to +0.055. Per-strategy mean: -0.0895 to -0.0177.
  - Gross includes slippage: engine.py:64, 89, 114, 120, 126.
  - CONFIRMED.
- CLM-6: payoff 0.5 gives breakeven 66.7%, not 75%.
  - 15m pooled over trades: L15 payoff 0.662 (breakeven 60.2%, WR 33.0%); L20 payoff 0.579 (breakeven 63.3%, WR 39.0%).
  - 5m G1: L15 payoff 0.304 (breakeven 76.7%); L20 payoff 0.281 (breakeven 78.1%).
  - CONFIRMED.
- CLM-7: ATR14/close on 15m IS bars after warmup.
  - Pooled median 0.464%, mean 0.520%.
  - Per symbol: BTC 0.388, ETH 0.510, SOL 0.565, LTC 0.479, BCH 0.402.
  - 37% of bars have ATR below 0.4% (BTC 53%, BCH 49%).
  - CONFIRMED.
- CLM-8: V3.9 fwd16 values are S42 -0.009, S52 +0.003, AC1 +0.011; the others fall inside the stated range. CONFIRMED.
- CLM-9: synthetic, one symbol.
  - IS: gross -0.0399%, net -0.1418%. ALL: gross -0.0344%, net -0.1363%.
  - Expected slippage drag is 0.0348%, so gross plus drag is about 0.
  - With --tf 5m --synthetic, synth() makes 15-min bars while df15 is real data (run.py:116-132), so V4.5 was never random-walk tested.
  - Also: synth() always uses seed 7 (run.py:43, 117), so a 5-symbol synthetic run is one path copied 5 times.
  - CONFIRMED.
- CLM-10: first IS entry 2025-08-17 15:45 UTC, last entry 2026-05-08 00:00, 521 IS trades exit after the split. CONFIRMED.
- CLM-11:
  - (a) N14 has 2 signals, ETH 2026-09-04 12:45 and LTC 2026-09-13 05:30, both OOS. N21 has 0.
  - (b) run.py:136 sets max_hold 3000 for 5m. The realized maximum is 855.
  - (d) Charging TP exits the maker fee (net +0.0003 on TP exits) still gives 0/364; best S6 PF 0.9459, -0.039%.
  - (c) The 31-strategy split is ambiguous rather than contradictory, since the ranges allow 17+12+2.
  - CONFIRMED (c is weak).

## Confirmed-OK list: spot-checked, all hold
- Per-exit average PF: 0.773 ... 0.539, 0.381, 0.335. Ladder hold 3.23/2.61 bars, exp_net -0.157/-0.161%.
- V3.9 L15 0.304 on 4,073 trades, best 0.723. STC 0.299/0.720, G1 0.303/0.724.
- Subs best-exit PF: S42 0.770, S52 0.807, SR 0.715, D16 0.742, AC1 0.774.
- OBV S: 0.316/0.366, best 0.791.
- 5m G1 L15: PF 0.1992, 1,112 trades, WR 0.3957, 0/5 months. Best SL2/TP3 0.7955 (AMB 0.7988, ANY 0.7509). 0/39 pass.
- Fee 0.01% monthly sums: -14.82/-22.12/-24.94/-14.05/-19.20.
- Fee 0.01% with slip 0 (my own rerun): 0/39, best PF 1.065 (AMB SL2/TP3, 2/3 symbols). The ladder is negative every month: -9.59/-12.84/-11.80/-4.75/-7.52.
- Best PF at fee 0.01% with normal slippage: 0.983.
- Max pooled eq_L50: 0.006 (15m), 2.5e-11 (5m).

## Missed by the auditor
1. The V4.5 5m sample (2026-05-12/13..09-29) lies entirely inside the 15m OOS window (from 2026-05-08). The data used for V4.5 has no untouched holdout.
   - Option B ("지금 데이터로 가능") would be in-sample and would contradict §5 ("같은 데이터로 ... 사후 선택 금지").
   - The auditor's own suggestion to test on "the 15m OOS" does not work for V4.5.
   - Fresh 5m history before 2026-05 is available through Astral start/end queries.
2. Random walk, combos with at least 100 trades: max exp_gross is +0.058% (IS) and +0.093% (ALL). The real-data best, S6 at +0.055%, is no larger than the best combo on a single random path. There is no pre-cost edge.
3. "원래 청산은 7봉(35분) 안에 끝나": 7.05 is the mean. The median is 4, 25% of trades last more than 7 bars, and p90 is 15.
4. "50배는 어떤 청산으로도 자산 0" holds for the pooled combos. Per symbol, SOL N03 (41 trades) ends at 1.53x (F_sl1.0_tp1.5) and 1.31x at 50x. These are small-sample exceptions.
5. §2 says +1,725 and §4 says +1,724. This is trivial.
