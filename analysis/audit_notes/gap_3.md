# GAP-FILL CHECK #3: leverage and ×20 target, quantified with Kelly

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/gap_3`

- Nothing under `/home/user/crypto-bot-research` was modified; `git status --short` is empty. `bt/` was copied here and run with `PYTHONDONTWRITEBYTECODE=1`.
- No Astral tool was used.
- Inputs:
  - The orchestrator's reproduced ledgers (`repro/results/trades_IS_15m_all5.csv`, `trades_ALL_5m_v45g1.csv`).
  - Gap-1's pre-registered Option-B trade vectors (`gap_1/out/IS_validation_primary_trades.csv` with 618 trades, `gap_1/out/OOS_primary_primary_trades.csv` with 1,936 trades) plus the 5m bars they came from.

## Bottom line (for the target / leverage reset, before A or B)

1. **The ×20/month target is unreachable with any edge seen here.** In shape-free form:
   - A median ×20 in 30 days requires an annualised Sharpe of **8.48 at full Kelly** and **9.79 at half Kelly**. This follows from growth = (c − c²/2)·SR² per unit time.
   - Realised daily-portfolio Sharpes of the candidates:
     - All negative (−0.97 … −24) except B in-sample: +2.53 ± 3.22, which is post-hoc.
     - B out-of-sample: −0.97 ± 1.84.
   - With an excellent real edge (annual SR 2), the half-Kelly median is **×1.13 per month**. At SR 1 it is ×1.03, and at SR 3 ×1.33.
2. **50x is itself a problem, independent of the sign of the edge.**
   - The only positive-expectancy ledger in the project is B in-sample (+0.105%/trade, which failed OOS). Run through the delivered `portfolio.single_account` at 40% margin × 50x it goes **1000 → 0.62**: 33 liquidations in 180 taken trades, and the account is gone. At 40% × 5x the same ledger goes 1000 → 2,069.
   - Mechanism: at 50x isolated margin, a position is liquidated at MAE ≤ −1.5% **whatever the margin size**.
     - 14.9% of B's IS trades and 24.8% of its OOS trades reach that.
     - Liquidation turns trades that would have ended around −1.40 … −1.51% into −2.0%, and kills the 8–12% of them that would have recovered to a profit.
     - At a true +0.05% edge the mean payoff becomes −0.032% (IS shape) or −0.071% (OOS shape), so Kelly at 50x is 0.
   - Liquidation shares for B-OOS at other leverages:

     | Leverage | 5x | 10x | 15x | 20x | 25x | 33x | 50x | 60x |
     |---|---|---|---|---|---|---|---|---|
     | Liquidated | 0% | 0.15% | 0.93% | 2.3% | 4.0% | 9.1% | 24.8% | 33.2% |

   - So any half-Kelly position has to be built with **≤ 10x leverage and a bigger margin**, not "tiny margin at 50x".
3. **Sizing that any plausible edge supports is about 1–8x notional (half-Kelly 0.5–4x), and 0 today.**
   - At each candidate's point estimate, Kelly is 0 for every ledger except B in-sample.
   - B out-of-sample:
     - μ = −0.048%, day-cluster 95% CI [−0.143, +0.043], σ = 1.585%.
     - Even at the CI upper bound, Kelly is 1.69x notional, so half-Kelly is 0.84x: **17% margin at 5x**.
     - 30-day median ×1.02 (p5 0.84, p95 1.24). At 40%×50x the median is ×0.013 and P(< ½) = 92%.
4. **The critic's numbers are right in direction, but its code inherits the MAE exit-bar liquidation artefact** (ENG-3 / audit_engine B4). Corrected:
   - The required edge for ×20 at 40%×50x is 0.10–0.61%/trade for ATR-type exits (critic: 0.20–0.76%).
   - For the high-frequency ladders it is 0.040–0.083% (critic: 0.07–0.13%).
   - The S6 +0.2% median at 20x is 0.19–0.50 (critic: 0.013).
   - All of these remain far above the observed −0.05% to −0.20%.
5. **"20x notional is above Kelly for any plausible edge" is false for ladder shapes.**
   - The ladder's σ is only 0.25–0.43%, so its Kelly is 32–83x at a mean-shifted +0.05%.
   - For the ladder the binding constraint is not sizing but edge feasibility:
     - The maximum net per trade even at a 100% win rate is 0.11% (V45 L50_sl15), 0.27% (N17 L50_sl20) or 0.22% (N08 L50_sl20).
     - Break-even needs a win rate of 62–76%; observed is 35–45%.
     - ×20 needs 69% (N17, 445 trades/30d) to 94% (V45 original, 196 trades/30d).
     - An 80%-accurate 15–30-minute oracle reaches only 53–59% WR on these exits (critic `posctrl2.csv`).

## Method

Scripts are in `work/`. Outputs are in `out/`. Total runtime is about 20 s.

| file | what |
|---|---|
| `work/kelly_orig.py` | critic's `kelly.py`, unchanged; rerun here → `out/kelly.csv` **identical** to `critic/work/kelly.csv` (max abs diff 0.0) |
| `work/build_b.py` | attaches entry/exit ts, MAE (bars fill_j..exit_j inclusive, the same convention as engine.py:122-124), MFE to Gap-1's B vectors; re-derives each fill price from the bars (max rel. deviation **0**) → `out/B_IS_ledger.csv`, `out/B_OOS_ledger.csv` |
| `work/gap3_kelly.py` | main analysis → `out/gap3_kelly.csv`, `gap3_30d_dist.csv`, `gap3_required_edge.csv`, `gap3_concurrent.csv`, stdout `out/gap3_stdout.txt` |
| `work/gap3_tilt.py` | win-rate tilt model; B MAE tail; solver check; delivered `portfolio.single_account` at 50x/5x → `out/gap3_tilt.csv`, `out/gap3_tilt_stdout.txt` |
| `work/gap3_sharpe.py` | Sharpe needed for ×20/month vs realised daily-portfolio Sharpe → `out/gap3_sharpe_stdout.txt` |

Definitions:

- **y**: net return per trade, as a fraction of notional. For stage-1 ledgers this is after the 0.05% taker fee ×2, 0.02% slippage per market fill and funding. For B it is maker 0.02% ×2 with a limit exit that falls back to taker.
- **Mean-shift scenario**: y − ȳ + μ. This is the critic's method. For ladders it is unphysical; see the tilt model.
- **Tilt scenario**: winners and losers keep their empirical sizes, and the win probability p is changed to hit μ.
- **Kelly notional**:
  - 2nd-order form: μ/(σ²+μ²).
  - Exact form: argmax_f mean log(1+f·y), under cross margin, so f < 1/|min y|.
  - Also computed on the isolated-margin payoff at the implementation leverage L: y_L = liquidated ? −1/L : max(y, −1/L), with liquidation when MAE ≤ −(1/L − 0.5%).
- **Liquidation flag, corrected.**
  - The engine flag is `mae <= -liq_dist`. It counts the exit bar's extreme *after* a stop inside the liquidation distance has already filled.
  - Corrected rule: a trade is not liquidated if `reason ∈ {SL, TRAIL, LOCK}` and `sl_dist < liq_dist` and `gross > -liq_dist`.
  - Effect at 50x: S6 22.2% → 11.6%, S2 17.9% → 9.7%, N17 F 8.5% → 1.0%, N17 L 3.6% → 0%, V45 F 1.7% → 0.3%.
  - B has no stop, so its flag is the raw flag, which is real.
- **User sizing**: margin 40%, 50x isolated. Per trade, equity × (1 + 0.4·max(−1, 50y)), or × 0.6 if liquidated. This is the same as engine.py:169-183.
- **Trade rates**:
  - Pooled: all per-symbol ledgers together, as in the critic's script.
  - Single account: one position at a time across symbols. The selection rule reproduces the delivered `portfolio.single_account` `taken` count for every ledger (asserted).
- **CIs**: iid t, plus a calendar-day cluster bootstrap on entry day (5,000 reps). The cluster version captures cross-symbol co-timing; design effect 1.16–2.02.
- **30-day distribution**: iid bootstrap of n₃₀ trades from the single-account (or pooled) subset, 20,000 sims.
  - Concurrent version: Kelly on daily-aggregated portfolio P&L, then a bootstrap of 30 days.
- **Required edge**: the minimum μ (bisection) such that n₃₀ · E[log growth] ≥ ln 20. Checked against the bootstrap median:

  | Ledger | Bootstrap median at μ_req |
  |---|---|
  | S6 | 19.67 |
  | V45 F | 20.04 |
  | V45 L | 20.00 |
  | N17 L | 19.55 |
  | B-OOS | 21.33 |

## Candidate table (empirical)

`gap3_kelly.csv`, scenario `emp`. μ, CIs and σ are % per trade. Liq% columns are the share of trades liquidated.

| candidate | n | trades/30d pooled / single | μ | 95% CI day-cluster | 95% CI iid | σ | WR | liq% 50x (fixed / raw) | liq% 5x |
|---|---|---|---|---|---|---|---|---|---|
| S6 F_sl2/tp3 (best 15m) | 835 | 95 / 52 | −0.052 | [−0.165, +0.067] | [−0.155, +0.052] | 1.52 | 0.43 | 11.6 / 22.2 | 0 |
| S2 F_sl2/tp2 | 4322 | 491 / 154 | −0.177 | [−0.226, −0.126] | | 1.22 | 0.47 | 9.7 / 17.9 | 0 |
| N17 F_sl1/tp1.5 | 4493 | 513 / 280 | −0.147 | [−0.181, −0.112] | | 0.86 | 0.38 | 1.0 / 8.5 | 0 |
| N08 T_sl1.5/tr2.5 (best trail) | 229 | 26 / 23 | −0.105 | [−0.273, +0.081] | | 1.23 | 0.27 | 1.3 / 4.4 | 0 |
| N08 L50_sl20 (best ladder) | 238 | 27 / 26 | −0.111 | [−0.163, −0.058] | | 0.37 | 0.45 | 0 / 1.7 | 0 |
| N17 L50_sl20 | 5665 | 646 / 445 | −0.159 | [−0.173, −0.143] | | 0.43 | 0.38 | 0 / 3.6 | 0 |
| V45 AMB F_sl2/tp3 (best 5m) | 701 | 155 / 88 | −0.087 | [−0.169, +0.002] | | 0.83 | 0.42 | 0.3 / 1.7 | 0 |
| V45 AMB_G1 F_sl2/tp3 | 695 | 153 / 88 | −0.088 | [−0.170, −0.000] | | 0.83 | 0.42 | 0.3 / 1.7 | 0 |
| V45 AMB_G1 L50_sl15 (user's original) | 1112 | 246 / 196 | −0.166 | [−0.182, −0.150] | | 0.25 | 0.40 | 0 / 0 | 0 |
| **B in-sample** (post-hoc) | 618 | 136 / 69 | **+0.105** | [−0.031, +0.240] | [+0.010, +0.200] | 1.21 | 0.53 | 14.9 / 14.9 | 0 |
| **B out-of-sample** (pre-registered) | 1936 | 140 / 71 | **−0.048** | [−0.143, +0.043] | [−0.119, +0.023] | **1.59** | 0.49 | 24.8 / 24.8 | 0 |

Notes on the table:

- The single-account subset mean differs from the pooled mean: S6 −0.108, B-IS +0.132, B-OOS −0.046.
- The out-of-sample B shape is riskier than the in-sample shape:
  - σ is 1.59% against 1.21%.
  - The worst MAE is −13.4% against −6.65%.
  - The 1st-percentile MAE is −6.1% against −3.6%.
- So any Kelly computed on an in-sample shape is optimistic.

## Kelly and implied margin

Exact Kelly, notional as a multiple of equity (`gap3_kelly.csv`).

| candidate | Kelly at emp μ | at CI-hi μ | at μ = +0.05% | at +0.10% | at +0.20% | half-K at +0.05%: margin at 5x / at 50x (50x-iso Kelly) | 20x ÷ Kelly at +0.05% / +0.10% |
|---|---|---|---|---|---|---|---|
| S6 F_sl2/tp3 | 0 | 2.93 | 2.18 | 4.42 | 9.06 | 21.8% / 0.07% (0.07) | 9.2 / 4.5 |
| S2 F_sl2/tp2 | 0 | 0 | 3.36 | 6.60 | 9.75† | 33.6% / 0 (0.0) | 6.0 / 3.0 |
| N17 F_sl1/tp1.5 | 0 | 0 | 6.95 | 11.8† | 12.8† | 69.5% / 6.5% (6.49) | 2.9 / 1.7 |
| N08 T_sl1.5/tr2.5 | 0 | 6.40 | 3.70 | 8.28 | 20.8 | 37.0% / 0.9% (0.93) | 5.4 / 2.4 |
| V45 AMB F_sl2/tp3 | 0 | 0.27 | 7.47 | 15.4 | 33.2 | 74.7% / 6.3% (6.32) | 2.7 / 1.3 |
| V45 AMB_G1 F_sl2/tp3 | 0 | 0 | 7.56 | 15.6 | 33.6 | 75.6% / 6.4% | 2.6 / 1.3 |
| N08 L50_sl20 | 0 | 0 | 38.0 | 81.0 | 201 | 380% / 38% | 0.53 / 0.25 |
| N17 L50_sl20 | 0 | 0 | 31.8 | 73.7 | 216 | 318% / 32% | 0.63 / 0.27 |
| V45 AMB_G1 L50_sl15 | 0 | 0 | 83.4 | 191 | 846 | 834% / 83% | 0.24 / 0.10 |
| B in-sample shape | 7.57 | 16.3 | 3.55 | 7.23 | 14.1 | 35.5% / **0 (0.0)** | 5.6 / 2.8 |
| B out-of-sample shape | 0 | 1.69 | 1.97 | 3.82 | 6.68 | 19.7% / **0 (0.0)** | 10.2 / 5.2 |

Notes on the Kelly table:

- † marks a boundary solution. Under cross margin, exact Kelly is capped at 1/|worst trade|, so it sits below the 2nd-order value: N17 F at +0.2% is 12.8 against 25.9, and S2 is 9.75 against 13.1.
- For fat-tailed shapes the critic's 2nd-order formula overstates Kelly.
- The critic's ranges are confirmed:
  - ATR shapes: 2.2–7.3x at +0.05% and 4.3–14.5x at +0.10% (2nd-order). Exact values are 2.2–7.6x and 4.4–15.6x.
  - B IS shape: half-Kelly at +0.05% = 1.72x (2nd-order) or 1.78x (exact). On the B OOS shape it is 0.98x.
- Ladder Kelly values (32–846x) come from mean-shifting a σ = 0.25–0.43% distribution by 0.2–0.37%. That moves nearly every trade to a win, which is physically impossible for a ladder whose wins are capped by its locks.
  - Under the tilt model, ladder Kelly is 28–110x at +0.05%, but +0.05% needs WR 69–87%.
  - These Kelly values also rest on a thin in-sample left tail: no gap through a 0.3–0.4% stop in 4.5–9 months of 5m/15m spot bars, and no perp liquidation-cascade slippage.
  - They are not a basis for sizing.
- Concurrency across symbols (`gap3_concurrent.csv`): the per-position Kelly under concurrent trading is **0.26–0.92× the per-trade Kelly**.

  | Candidate | Concurrent ÷ per-trade Kelly |
  |---|---|
  | S6 | 0.74–0.77 |
  | S2 | 0.51–0.58 |
  | N17 F | 0.28–0.36 |
  | N08 | 0.85–0.92 |
  | V45 F | 0.40–0.54 |
  | V45 L | 0.36–0.66 |
  | N17 L | 0.26–0.40 |
  | B | 0.49–0.58 |

  - Half-Kelly per position has to be cut again when 3–5 symbols run at once.
  - Maximum concurrency is 3 (5m) or 5 (15m).

## 30-day distributions: half-Kelly (implemented at 5x) vs 40% × 50x

Single account (`gap3_30d_dist.csv`). Each cell is median [p5, p95] of the 30-day equity multiple.

| candidate | μ scenario | half-K notional | half-K median [p5, p95] | 40%×50x median [p5, p95] | 40%×50x P(<½) | 40%×50x P(≥×20) |
|---|---|---|---|---|---|---|
| S6 F_sl2/tp3 | emp | 0 | 1 | 0.026 [0.001, 0.75] | 0.93 | 0.001 |
| S6 F_sl2/tp3 | CI-hi +0.067% | 1.66 | 1.04 [0.79, 1.38] | 0.14 [0.005, 4.1] | 0.73 | 0.007 |
| S6 F_sl2/tp3 | +0.20% | 5.17 | 1.48 [0.63, 3.54] | 0.50 [0.018, 14.0] | 0.50 | 0.034 |
| V45 AMB F_sl2/tp3 | emp | 0 | 1 | 0.040 [0.003, 0.55] | 0.94 | 0.000 |
| V45 AMB F_sl2/tp3 | +0.05% | 3.82 | 1.13 [0.70, 1.85] | 0.75 [0.064, 8.8] | 0.39 | 0.015 |
| V45 AMB F_sl2/tp3 | +0.10% | 7.91 | 1.65 [0.64, 4.5] | 1.78 [0.16, 21.7] | 0.19 | 0.056 |
| V45 AMB_G1 L50_sl15 (original) | emp | 0 | 1 | **0.0009** [0.0003, 0.003] | 1.00 | 0 |
| V45 AMB_G1 L50_sl15 | +0.05%\* | 42 | 20.1 | 5.46 [1.76, 17.4] | 0.000 | 0.03 |
| N17 L50_sl20 | emp | 0 | 1 | 4e−9 | 1.00 | 0 |
| N17 L50_sl20 | +0.05%\* | 17.4 | 16.4 | 21.0 [1.5, 317] | 0.01 | 0.51 |
| **B in-sample** | emp (+0.132% single-acct) | 4.41 | **1.34 [0.65, 2.83]** | **0.21 [0.006, 7.3]** | 0.66 | 0.018 |
| B in-sample | +0.05% | 1.64 | 1.04 [0.79, 1.38] | 0.080 [0.002, 2.6] | 0.81 | 0.004 |
| **B out-of-sample** | emp | 0 | **1 (do not trade)** | **0.006 [0.0001, 0.35]** | 0.96 | 0.000 |
| B out-of-sample | CI-hi +0.043% | 0.96 | 1.02 [0.84, 1.24] | 0.013 [0.0002, 0.90] | 0.92 | 0.002 |
| B out-of-sample | +0.10% | 2.19 | 1.13 [0.72, 1.76] | 0.025 [0.0003, 1.7] | 0.88 | 0.003 |

\* The ladder rows at +0.05% are not attainable: they need WR 69–87% against 35–40% observed.

Pooled rates (the critic's convention) are more optimistic. For example, V45 F at +0.2% has a 40%×50x median of 48.7 pooled against 10.4 single-account.

## Required net edge per trade for a median ×20 in 30 days

`gap3_required_edge.csv` and `gap3_tilt.csv`. All values are % per trade except the WR column.

| candidate | 40%×50x single (liq fixed) | 40%×50x pooled (liq fixed) | critic kelly.py (pooled, raw liq) | full Kelly, any leverage, single | analytic √(2ln20/n)·σ, single | tilt: WR needed at 40%×50x (observed WR) | observed μ |
|---|---|---|---|---|---|---|---|
| S6 F_sl2/tp3 | 0.612 | 0.490 | 0.758 | 0.464 | 0.485 | 0.65 (0.41) | −0.052 |
| S2 F_sl2/tp2 | 0.323 | 0.275 | 0.452 | 0.232 | 0.233 | 0.68 (0.48) | −0.177 |
| N17 F_sl1/tp1.5 | 0.116 | 0.102 | 0.250 | 0.110 | 0.114 | 0.56 (0.36) | −0.147 |
| N08 T_sl1.5/tr2.5 | 0.835 | 0.754 | 0.839 | 0.423 | 0.593 | 0.83 (0.26) | −0.105 |
| N08 L50_sl20 | 0.622 | 0.592 | 0.644 | 0.164 | 0.177 | unreachable even at WR 100% | −0.111 |
| N17 L50_sl20 | 0.049 | 0.040 | 0.126 | 0.045 | 0.048 | 0.69 (0.35) | −0.159 |
| V45 AMB F_sl2/tp3 | 0.237 | 0.171 | 0.191 | 0.204 | 0.214 | 0.63 (0.40) | −0.087 |
| V45 AMB_G1 L50_sl15 | 0.083 | 0.068 | 0.068 | 0.043 | 0.044 | **0.94** (0.38) | −0.166 |
| B in-sample shape | 0.549 | 0.431 | 0.431 | 0.383 | 0.370 | 0.72 (0.54) | +0.105 (IS) |
| B out-of-sample shape | 0.824 | 0.663 | 0.663 | 0.494 | 0.432 | 0.78 (0.50) | −0.048 |

Sensitivity of the single-account 40%×50x requirement to the user's range of settings (30–40% margin, 50–60x):

| setting | S6 | V45 F | V45 L | B-OOS |
|---|---|---|---|---|
| 30% × 50x | 0.665 | 0.279 | 0.107 | 0.815 |
| 40% × 60x | 0.839 | 0.238 | 0.072 | 0.989 |

## Findings (bias direction / effect on the headline)

- **G3-1, high.** The ×20/month target needs an annual Sharpe of at least 8.5 (full Kelly) or 9.8 (half Kelly), which amounts to 0.04–0.83%/trade net depending on shape and trade rate.
  - Every observed net edge is −0.05% to −0.20%, and B-OOS is −0.048%.
  - Bias: neutral. Headline: strengthened. It settles the open "목표 재설정" (target reset).
- **G3-2, high.** 50x is destructive even with a positive edge.
  - B in-sample goes 1000 → 0.62 at 40%×50x and → 2,069 at 40%×5x (delivered `single_account`).
  - Wick liquidation at MAE ≤ −1.5% hits 15–25% of B trades, so Kelly at 50x is 0 for B's shape at edges up to +0.10%.
  - The implication: leverage must drop to ≤ 10x whatever A or B finds.
  - Headline: not changed (it strengthens "50x → 0"), but it changes the framing. The handoff's "50x → equity 0" was edge-driven; this shows it is also leverage-driven.
- **G3-3, medium.** The critic's kelly.py uses the raw engine liquidation flag, which carries the MAE exit-bar artefact. That makes 20x look *worse* than the engine's own stop logic implies:
  - S6 at +0.2% goes from 0.013 to 0.19 (pooled) or 0.50 (single account).
  - Required ATR edges go from 0.20–0.76% to 0.10–0.61%.
  - Required ladder edges go from 0.07–0.13% to 0.04–0.08%.
  - Conclusion unchanged.
- **G3-4, medium.** "20x is above Kelly for any plausible edge" is false for ladder shapes, where 20x is 0.1–0.6× Kelly under mean shift.
  - For ladders the constraint is feasibility instead: maximum μ at WR 100% is 0.11–0.27%, break-even WR is 62–76%, ×20 needs WR 69–94%, and an 80% oracle reaches 53–59% WR.
  - The critic's framing is wrong in mechanism for the ladder, but its conclusion is right.
- **G3-5, medium.** Pooled trade rates look *better* than one account allows.
  - The single-account rate is 31–95% of the pooled rate. Required μ is 10–40% higher single-account. Concurrent-position Kelly is 0.26–0.92× the per-trade Kelly.
- **G3-6, medium.** The deliverable itself, the sizing table: 0 today; at most about 1–3x notional if a pre-registered OOS test ever passes.
  - B-OOS at its CI upper bound: half-Kelly 0.84x notional (17% margin at 5x), 30-day median ×1.02.
- **G3-7, low.** In-sample shapes understate tails. B's σ is 1.21% IS against 1.59% OOS, and its worst MAE −6.65% against −13.4%. For fat-tailed shapes the 2nd-order Kelly also overstates the exact Kelly. Kelly from IS shapes is biased *better*.

## Caveats

- Everything uses Polygon spot bars, not Binance perp last or mark prices. Liquidation on the perp uses the mark price, so wick liquidations on spot may be somewhat overstated or understated. Liquidation fees are ignored (audit_engine B11).
- The iid bootstrap over trades ignores serial correlation; the concurrent daily version partly covers it.
- 30-day medians use the ledger's average trade rate. Real months vary; B-OOS monthly means ranged from −0.40% to +0.22%/trade.
- The mean-shift and tilt models are hypothetical edges placed on empirical shapes. They say what sizing *would* be right if an edge existed. They are not evidence that one exists.
