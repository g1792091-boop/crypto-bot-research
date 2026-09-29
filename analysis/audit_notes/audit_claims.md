# Audit: claim-by-claim check of HANDOFF_FOR_CLAUDE_CODE.md (§3-§4, plus §2 items 2-3 arithmetic)

Scratch dir: /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/audit_claims
- bt/ = copy of project bt/. The only change is in run.py: a `--slip` CLI arg, passed to CostCfg(slip_side=...). Defaults are the same as the original.
- data -> symlink to /home/user/crypto-bot-research/data (read-only use)
- results/ = my reruns: 5m fee 0.0001 (tag fee01), 5m fee 0.0001 + slip 0 (tag fee01_slip0), synthetic summaries synthIS / synthALL (their trade files were deleted after analysis to save space)
- work/ = scripts (sept.py, sept2.py, sept3.py, fwd_robust.py), logs, forward_5m_recomputed.csv, trades15.pkl (column subset of the repro 15m trades)
- Base reproduction: ../repro/results (byte-identical to the delivered pooled/forward/5m summary; established by the orchestrator)

Status legend: EXACT = matches to the stated precision. APPROX = close, or matches only under one reading. MISMATCH = the number or statement is wrong. UNVERIFIABLE = the source is not in the package.

## Claim table

| # | Claim (handoff) | Source | Recomputed | Status |
|---|---|---|---|---|
| 1 | 28전략 × 13청산 = 364조합, 851,035거래 | §4 | 364 rows in pooled_IS_15m_all5.csv = 26 strategies with signals + 2 G1 variants, x 13 exits. Those 364 combos hold **900,334** trades. 851,035 is the count for the 338 non-G1 combos only (summary_IS_15m_all5.csv trades sum). The G1 combos add 49,299. | MISMATCH (labelling: the combo count and the trade count describe different sets) |
| 2 | 통과 0개 | §4 | pass.sum()=0 of 364 | EXACT |
| 3 | 최고 S6 SL2/TP3 PF 0.93, 835건, 비용 후 −0.052%/거래 | §4 | PF 0.9283, 835, −0.0518%. Rank 1 of 364 | EXACT |
| 4 | 비용 전 기대값 28개 전부 −0.10%~+0.06% | §4 | Best exit per strategy (T1 rows): **−0.115% (V39_SR) .. +0.055% (S6)**. All 364 combos: −0.140 .. +0.055. Mean over the 13 exits per strategy: −0.090 .. −0.018. Only 93.4% of combos fall inside [−0.10, +0.06]. No reading gives −0.10 as the lower bound. Also, "비용 전" (exp_gross) is after slippage (0.02%/side); it is only before fee and funding. | MISMATCH (lower bound; the upper bound is right) |
| 5 | 청산 방식 평균 PF: SL2/TP3 0.77 … 트레일1.5 0.54, L50 sl20 0.38, sl15 0.34 (꼴찌) | §4 | 0.773 / 0.539 / 0.381 / 0.335; L50_sl15 is last | EXACT (the "28 strategies" include the 2 G1 variants, which are near-duplicates of V39_15M and OBV_S) |
| 6 | 원래 방식 평균 보유 2.6~3.2봉, 거래당 −0.16% | §4 | hold 2.605 / 3.233; exp_net −0.161 / −0.157 | EXACT |
| 7 | V3.9 15분 전체 원래 청산 PF 0.30 (4,073건), 최고 청산 PF 0.72 | §4 | L50_sl15 PF 0.304, 4,073; (L50_sl20 0.351, 3,959, not mentioned); best F_sl2.0_tp3.0 0.723 | EXACT (sl15 only) |
| 8 | STC 변형·G1 변형 동일 | §4 | STC 0.299 (3,858) / 0.345 / best 0.720. G1 0.303 (3,724) / 0.349 / best 0.724 (best exit is SL2/TP1.5, not SL2/TP3) | EXACT |
| 9 | 서브 5개 전부 PF 0.71~0.81 | §4 | best-exit PF: S52 0.807, AC1 0.77, S42 0.77, D16 0.74, SR 0.71. Their ladder PFs are about 0.30-0.35 | EXACT (best-exit reading) |
| 10 | OBV S 원래 청산 PF 0.32~0.37, 최고 0.79 | §4 | 0.316 / 0.366 / best 0.791 | EXACT |
| 11 | V4.5 AM+B+G1 5m 원래 청산 PF 0.20, 1,112건, 승률 39.6%, 5개월 전부 손실 | §4 | PF 0.199, 1,112, WR 0.3957, months_pos 0/5 | EXACT |
| 12 | 수수료 0.01% 재계산 월별 가격% 합: 5월 −14.8, 6월 −22.1, 7월 −24.9, 8월 −14.1, 9월 −19.2 | §4 | Rerun `run.py --tf 5m --window ALL --fee 0.0001` gives −14.82, −22.12, −24.94, −14.05, −19.20 (by entry month, UTC). The trade path is identical to the 0.05% run and net shifts by exactly +0.0008. With **fee 0.01% and slippage 0**: −9.59, −12.84, −11.80, −4.75, −7.52 (total −46.5% vs −95.1%). Still negative in all 5 months. | EXACT |
| 13 | 최고 V4.5 청산 SL2/TP3 PF 0.80 | §4 | G1 0.795, AMB 0.799, ANY 0.751 | EXACT |
| 14 | 통과 0/39 | §4 | 0/39. Still 0/39 at fee 0.01% (best PF 0.98). Still 0/39 at fee 0.01% + slip 0 (best PF 1.06, V45_EXACT_AMB SL2/TP3, +0.024%/trade, 2/3 symbols) | EXACT |
| 15 | 9월 5~13일: 3종목 59건, 승률 46%, 단일계좌 50배·40% 복리 1,000→380 | §4 | Exactly reproduced (59 trades, WR 45.8%, final 380.1) only with **fee 0.01%** (the report's assumption, which the handoff does not state), a start anywhere from 2026-09-04 07:00 to 09-05 07:00 UTC (e.g. KST 09-05 00:00) and an end (exclusive) from 09-13 08:00 to 14:00 UTC. **Same window at the real 0.05% fee: 59 trades, WR 42.4%, 1,000→175.** Calendar UTC 09-05..09-13 inclusive: 62 trades, WR 41.9%, →147 (0.05%) or WR 45.2%, →337 (0.01%). 47 of the 59 trades are taken by the single account. | APPROX (the fee is unstated. Under the real fee the result is about 2x worse) |
| 16 | 16봉 뒤 +0.1% 넘는 건 S5(324건, +0.103%)뿐 | §4 | S5 324, +0.103; next N09 +0.083 | EXACT |
| 17 | V3.9 계열은 음수(−0.035~−0.121%) | §4 | Only 5 of 8 V3.9 variants are in that range (15M −0.035, G1 −0.036, STC −0.038, SR −0.054, D16 −0.121). S42 −0.009, S52 +0.003 and AC1 +0.011 are about zero or positive | MISMATCH (minor) |
| 18 | V4.5 정확 AM+B만 64봉 뒤 +0.135% (BTC +0.09, ETH +0.14, SOL +0.18; t 2.8~3.1; 양수 57%) | §4 | 0.1353; 0.090/0.140/0.178; t 2.79/2.91/3.05 (G1: 2.82/2.99/3.06); hit 0.566. The file is not produced by any script in bt/, but forward.forward_stats reproduces it (max diff 4e-16). **But** (a) the t values are naive: 64-bar windows overlap and signals cluster. Day-clustered t is 1.62/1.69/1.84 per symbol, pooled 2.24. Thinned (≥64 bars apart) t is 1.63/1.80/1.95. (b) The effect is not unique to AM+B: V45_ANY gives +0.110% (n=9,068; naive t 5.5/3.7/7.0; day-clustered pooled t 2.51). At 64 bars several 15m strategies are also above +0.1% (N08 0.230, N03 0.208, S6 0.136, N09 0.120, N17 0.119 with per-symbol t up to 4.46 on LTC). | Numbers EXACT. "only / t≈3" framing is a MISMATCH (overstated) |
| 19 | 왕복 비용(0.10~0.14%)과 같은 크기; 원래 청산은 7봉(35분) 안에 끝남 | §4 | 0.135 − 0.14 = −0.005. Ladder hold: mean 7.05 bars, median 4, 75% ≤7 bars, 0.9% ≥64 bars | EXACT (7 bars is the mean) |
| 20 | 왕복 비용 0.14% | §4 | 2×0.05 + 2×0.02 = 0.14 (funding is extra) | EXACT |
| 21 | 15분봉 1 ATR 중앙값 0.54% | §4 | Median ATR14/close, 15m IS, pooled 5 symbols: **0.464%** (BTC 0.388, ETH 0.510, SOL 0.565, LTC 0.479, BCH 0.402). At trade entries: 0.463%. The mean is 0.52 and the median of per-symbol means is 0.55, so 0.54 looks like a mean, not a median | MISMATCH |
| 22 | 50배 −20% = 가격 0.4% (1 ATR보다 작아) | §4 | 20/50 = 0.4%, correct. It is below the pooled median ATR of 0.46%, but it is about equal to the BTC (0.39) and BCH (0.40) medians. 37% of IS bars have ATR < 0.4% | EXACT arithmetic, APPROX comparison |
| 23 | 계단 +11% = 가격 0.22% | §4 | 11/50 = 0.22%. The realized LOCK exit is gross about +0.20% (after exit slip) and net about +0.095% (median) | EXACT |
| 24 | 손익비 0.5, 본전 승률 75% 필요, 실제 40% | §4 | Internally inconsistent: payoff 0.5 gives breakeven 1/(1+0.5) = **66.7%**, not 75%. Actual net payoff: 15m L50_sl15 0.66 → BE 60%, WR 33%. 15m L50_sl20 0.58 → BE 63%, WR 39%. 5m V4.5 G1 L50_sl15 0.30 → BE 77%, WR 39.6%. L50_sl20 0.28 → BE 78%, WR 46.5%. The "75%" fits the 5m V4.5 payoff (~0.3), not 0.5 | MISMATCH (numbers mixed from two tests. The conclusion that WR is far below breakeven holds in every case) |
| 25 | 랜덤워크 비용 전 −0.03%, 비용 후 −0.13% | §3 | synthetic (seed 7): IS window gross −0.040, net −0.142. ALL window gross −0.034, net −0.136. The expected slippage drag is −0.035, so there is no edge before slippage | APPROX (net −0.136 rounds to −0.14). Only 15m strategies were tested; the V4.5 5m+15m mapping has no random-walk test |
| 26 | N14·N21 14개월 동안 신호 0건 | §3 | N21: 0. N14: **2 signals** over the full 14 months (ETH 2026-09-04 12:45, LTC 2026-09-13 05:30), both out-of-sample. 0 in IS | MISMATCH (trivial) |
| 27 | 15분 앞 9개월 (2025-08-07~2026-05-07) | §3 | The 1,000-bar warmup means the first IS entry is 2025-08-17 15:45 and the last is 2026-05-08 00:00 (about 8.7 months). 521 of 900,334 IS trades exit after the split (negligible leakage) | APPROX |
| 28 | 5분 2026-05-13~09-29 | §3 | ETH 5m starts 2026-05-12 09:20. The first 5m entry after warmup is 05-15 21:25 (ETH) / 05-16 (BTC, SOL) | APPROX |
| 29 | 최대 보유 1,000봉 | §3 | True for 15m. For 5m, run.py sets `cost.max_hold = 3000` (the same 250 h wall-clock). No 5m trade reached it (max 855) | APPROX |
| 30 | TP는 지정가 (cost: taker 0.05%/편도) | §3 | The engine charges 2× taker on every trade, including TP limit fills. Charging maker 0.02% on TP exits: 15m pass is still 0/364, best S6 PF 0.946, exp −0.039%, no combo with exp > 0 | consistent with the stated cost. Conservative (small WORSE bias). Does not change the conclusion |
| 31 | 50배는 어떤 청산으로도 자산 0 | §5 | Pooled max eq_L50: 0.006 (15m), 2.5e-11 (5m). The only exception is per-symbol SOL N03 (41 trades, 1.53) | EXACT for pooled |
| 32 | §0 "14개월 백테스트" | §0 | The reported 15m numbers use the IS window only (effective 2025-08-17..2026-05-08, about 8.7 months). The 5m numbers use about 4.5 months. OOS was never opened, which is correct protocol, but "14개월" overstates | MISMATCH (framing) |
| 33 | §2-3: V45_AMB_G1_SL15 +1,725 → ≈ −55 (fee 0.01→0.05) | §2 | Δ = 1,780 over 56 trades = 31.8 USDT per trade = 0.0008 × notional, so the implied **average notional is ≈39.7k USDT/trade** (7.9× the 5,000 USDT policy). At 5,000 × 40% × 50x = 100k notional, Δ = 4,480 and the result would be **≈ −2,755**. At 40k notional (e.g. 20x, or ~16% margin at 50x) the result is −67, close to the handoff's figure | UNVERIFIABLE (source not in package). Consistent only with ~40k notional |
| 34 | §2-3: V39_F15_G1_SL20 +696 → ≈ −181 | §2 | Δ = 877. It implies about 27 trades at 40k notional, or about 11 at 100k. The trade count is not given | UNVERIFIABLE |
| 35 | §2-2: 124장부 | §2 | 31 strategies × 4 symbols (CORE4) = 124 | internally consistent |
| 36 | §2-2 "표준 15~19 / 근사 12~14 / 모드선택 2" vs §3 "표준 19, 근사 12 제외" | §2/§3 | 19 + 12 + 2 = 33 ≠ 31 | MISMATCH (internal, minor) |
| 37 | +1,725 (§2) vs +1,724 (§4) | §2/§4 | rounding | trivial |

## Robustness and sensitivity numbers (for the headline)
- 5m V4.5 at the report's own fee of 0.01%: 0/39 pass, best PF 0.98.
- 5m V4.5 at fee 0.01% with zero slippage: 0/39 pass. Best is V45_EXACT_AMB SL2/TP3, PF 1.06, +0.024%/trade, 2/3 symbols positive. So even under near-zero costs nothing reaches PF 1.2. With 0.01% fee and 0 slippage, the ladder exits (L50_sl15/sl20) are still PF 0.69/0.80, with 0/5 months positive.
- 15m with maker fee on TP exits: 0/364 pass, best PF 0.946.
- Real 15m mean exp_gross over 364 combos: −0.058% (trade-weighted −0.064%). The random walk gives −0.035..−0.040%, so real signals are on average slightly worse than noise after slippage.
- The single-account 50x Sept check under the real 0.05% fee is 1,000→147..175, not 380.
- V39_15M_G1 was also run on 5m (it is in summary_ALL_5m_v45g1.csv) but the handoff does not report it: 0/13 pass, best PF 0.705, ladder PF 0.215/0.263. This is consistent with the conclusion.
- Ladder exits on 15m: 35% (sl15) / 23% (sl20) of trades exit on the entry bar. The intrabar-order assumption (SL first) drives a lot of the ladder result, which supports proposal C (1m check).

## Commands run (key)
- `cd bt && python3 run.py --window ALL --tf 5m --symbols BTCUSD,ETHUSD,SOLUSD --fee 0.0001 --tag fee01`
- `... --fee 0.0001 --slip 0 --tag fee01_slip0` (my added arg)
- `python3 run.py --synthetic --symbols BTCUSD --window IS --tag synthIS` and `--window ALL --tag synthALL`
- work/sept.py, sept2.py, sept3.py: window/fee/timezone search for the Sept single-account check (uses portfolio.single_account logic)
- work/fwd_robust.py: clustered/thinned t and placebo for the 64-bar forward drift
- Inline pandas scripts for the pooled/T2/ATR/payoff checks (outputs quoted above)
