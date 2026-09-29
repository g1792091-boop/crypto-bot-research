# Completeness critic: notes

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/critic`

Nothing under `/home/user/crypto-bot-research` was modified (`git status --short` is empty). The only Astral tool used was the read-only `astral_price_get`, called 4 times (listed at the end).

## What I read

- **The handoff**, `HANDOFF_FOR_CLAUDE_CODE.md`, all 105 lines.
- **All of `bt/run.py`, `analyze.py`, `portfolio.py`, `forward.py` and `engine.py`**, plus the parts of `strategies.py` and `fg_indicators.py` I needed.
- **The two earlier-session documents the handoff links to**, read-only through the Claude Docs connector, with their text extracted in full:
  - The 31-strategy code report (artifact 46br7PTC1MtZoe78PAgGNF, docs id 19139c21-…). Local text copy: `doc_31set.txt`.
  - The user-facing stage-1 results report (artifact JJDDW6tFh3nXQg1ZEiAud1, docs id 8c128787-…). Local text copy: `doc_stage1.txt`. None of the 7 auditors had read this one.

## Facts from the earlier reports that the auditors did not use

1. **All 31 strategies are reproducible from code.** The 31-strategy report says `REPRODUCIBLE_FROM_CODE 31/31`, "31개 조건식은 전부 확보됐다" and "31개 전부 같은 신뢰 등급이다" (the "original" of all 31 is an Instagram image).
   - The handoff nevertheless excludes 12 of them because "원본이 없어" (no original exists). That reason contradicts the report.
   - The excluded 12 are S1, S3, S4, N04, N05, N06, N11, N13, N15, N16, N19 and N20.
   - They include 3 of the 4 strategies that were positive in the 7-day live audit (N19, N13, N11). N08, the fourth, was tested.
2. **Two port parameters are faithful to the source, not porting slips.**
   - N01's Supertrend(10, 6) is described in the source as "친구 지정 Supertrend 10/6". This supports PORT-1.
   - N24's long/short asymmetry is labelled "원문 비대칭", i.e. deliberate in the original. This supports reading PORT-2 as a design choice, not a port bug.
3. **The FINGRAD live engine differs from the stage-1 grid in ways stage 1 did not model.**
   - Each strategy supplies its own structural stop.
   - Hard-cap entry gate: signals whose structural stop is wider than about 0.4% (5m) or 0.6% (15m) are never traded (STRUCTURE_STOP_BEYOND_HARD_CAP).
   - Profit lock is based on NET ROE: +13 → +10, then floor(peak/5)×5−5.
   - Strategy-specific exits and opposite-signal exits (CONFIRM_2).
   - The earlier report itself recommended running the gate-free signals first and the native engine second. Stage 1 did only the first. ENG-12 flags the missing net-ROE ladder and reversal exit but not the gate or the structural stops.
4. **The results report makes claims the handoff does not repeat, and nobody had checked them.**
   - "이 구조는 어떤 신호를 넣어도 이길 수 없다": see Gap 2. It is roughly right for the ladder.
   - For option B: "비용을 0.04%로 낮추고 5시간을 버티면 거래당 +0.1% 안팎이 남을 수 있다". See Gap 1. In-sample it reproduces as +0.107%.
   - For option A: "4.6년(2022~2026)". The last 40,000 1h bars include the months already inspected (DATA-6).
   - Option C is meant to explain the report's Sep 5–13 +172% against the stage-1 −62%. See Gap 5: bar resolution does not explain it.

## Gap 1: Option B's premise holds in-sample; one pre-registered out-of-sample test decides it

Scripts: `work/limit_fill.py`, `work/limit_fill2.py`, `work/b_null.py`. Outputs: `work/limit_fill.csv`, `work/limit_fill2.csv`.

Data and setup: V45_EXACT_AMB signals on BTC/ETH/SOL 5m, the delivered data (i.e. in-sample; these numbers are an upper bound). The entry is a limit order at the signal-bar close, and a fill requires the price to trade through the limit.

**Fills and adverse selection**

| Limit placement | Valid for | Fill rate | Filled trades' market-entry drift | All signals' drift |
|---|---|---|---|---|
| At signal close | 3 bars | 98.7% | +0.1346% | +0.1357% |
| 10 bp better | 3 bars | 74% | lower | +0.1357% |

- At the signal close there is no measurable adverse selection.
- At 10 bp better, fills fall to 74% and the unfilled signals are the ones that ran away.

**Net result per trade: 64-bar time exit, one position per symbol, 618 trades**

| Exit variant | Net per trade | PF | Symbols positive | Months positive |
|---|---|---|---|---|
| Maker exit | +0.107% | 1.30 | 3/3 | 5/5 |
| Exit limit with taker fallback | +0.105% | 1.29 | | |
| Taker exit | +0.057% | 1.15 | | |
| Maker exit + 2-ATR(5m) stop | +0.015% | 1.04 | | |
| Maker exit + 4-ATR stop | +0.081% | 1.21 | | |
| Maker exit + 6-ATR stop | +0.090% | 1.24 | | |
| Market entry + 2-ATR stop (reference) | −0.077% | 0.80 | | |
| Random-entry null, maker/maker | −0.03% | 0.92 | | |

- About 50% of trades hit the 2-ATR stop. B's own spec says "ATR 손절" without a width, and the width decides the result.
- With the maker exit this variant **would pass the pre-registered rule in-sample** (PF ≥ 1.2, ≥ 100 trades, net > 0, 3/3 symbols).

**Null test** (`b_null.py`): a circular time shift, the same shift for all three symbols, 300 reps.

| Exit | z | One-sided p | Null reps that also pass the rule |
|---|---|---|---|
| Maker | 2.01 | 0.023 | 3.7% |
| Taker | 2.08 | 0.013 | 0.3% |

With independent shifts per symbol p was 0.003, but that null destroys cross-symbol co-timing, so it is too lenient. The horizon and variant were chosen after the forward scan, so this is a post-hoc z≈2. It agrees with STAT-1/STAT-12.

**Sizing and power**

- Per-trade σ = 1.20%. At the in-sample mean the Kelly notional leverage is 7.3x. Half-Kelly at a true edge of +0.05% is 1.7x notional. B's "3~5배" at 40% margin is 1.2–2x notional, which is consistent.
- Trade rate is about 134 per 30 days across 3 symbols.
- Power of an out-of-sample test, using the null SD of the mean of 0.071% per 4.5 months:

| Fresh 5m data | Assumed true effect | Power |
|---|---|---|
| 4.5 months | in-sample effect (+0.14% over null) | ≈65% |
| 9 months | in-sample effect | ≈89% |
| 4.5 months | half the in-sample effect | ≈26% |
| 9 months | half the in-sample effect | ≈42% |

**Data-fetch trap.** `astral_price_get` with start+end silently returns only the LAST 5,000 bars (`requested_limit 5000, has_more true`); BTC 1m returned 2026-09-25 00:41 → 09-28 12:00. Using `limit=40000` plus `end` does return 40,000 bars.

**Bias direction and effect on the headline.** The handoff calls B "지금 데이터로 가능". That would be an in-sample test (STAT-6 already says so), so it biases toward looking better. The headline "0 pass" covered only taker-cost ATR, trail and ladder exits, so it is not contradicted. The ordering of next steps is affected: B is the cheapest decisive experiment.

**Prior evidence against B.** STAT-4 found the parent 15m ST+STC state had about zero drift over the 15m IS window for BTC/ETH/SOL. B may well fail out of sample.

## Gap 2: No positive control; the 13-exit grid is blind to slow edges and the ladder cannot monetise even strong fast edges

Scripts: `work/posctrl.py`, `work/posctrl2.py`. Output: `work/posctrl2.csv`.

Setup: oracle signals planted on the real 5m BTC/ETH/SOL data, 1,800 random bars per symbol. The side equals the sign of the k-bar forward return with probability q, and is random otherwise. The stage-1 engine, costs and pooled rule are used unchanged.

| Oracle | Forward drift | L50_sl15 PF | L50_sl20 PF | F_sl2/tp3 PF | 64-bar time exit PF | Passes rule |
|---|---|---|---|---|---|---|
| k=64, q=0.3 | fwd64 +0.23% (1.7× V4.5's +0.135%) | 0.25 | 0.29 | 1.02 | 1.10 | 0 |
| k=64, q=0.5 | fwd64 +0.44% | 0.26 | 0.32 | 1.12 | 2.06 | time exit only |
| k=6, q=0.8 | fwd6 +0.197% | 0.53 | 0.67 | 1.17 | 1.21 | time exit only |
| k=3, q=0.8 | fwd3 +0.146% | 0.56 | 0.69 | 1.08 | | 0 |

- In the k=6 row, 80% of entries are on the right side of the next 30 minutes.

What this means:

- **"0 of 364 / 0 of 39 pass" is weak evidence against slow (5–16 h) drift edges below about 0.3–0.4% per signal.** The grid would have missed them.
- The exit-independent forward table is the right instrument for slow edges, and there the evidence is a post-hoc z≈2 (STAT).
- The results report's "이 구조는 어떤 신호를 넣어도 이길 수 없다" is roughly correct for the 50x ladder at taker cost: even a 30-minute oracle with 80% accuracy gives PF < 0.7.
- Option A as written ("같은 28개 × 13청산") inherits the blind spot. It also still includes the ladder, which §5 of the handoff says to discard, and it has no time exits.
- Bias direction: the grid makes slow edges look worse. This does not change "0 pass". It does change what "0 pass" proves.

## Gap 3: The leverage and target decision is not quantified (Kelly)

Script: `work/kelly.py`. Output: `work/kelly.csv`.

Method: use the empirical per-trade shapes from the reproduced ledgers, shift the mean to a hypothetical net edge μ, and compute:
- the Kelly notional leverage μ/(σ²+μ²);
- growth at the user's 40% margin × 50x (20x notional);
- a 30-day bootstrap.

| Ledger | σ per trade | Kelly notional at μ = 0.05 / 0.10 / 0.20% | Median 30-day multiple at 20x notional, μ = 0.2% |
|---|---|---|---|
| S6 F_sl2/tp3 | 1.52% | 2.2 / 4.3 / 8.5x | 0.013 |
| S2 F_sl2/tp2 | 1.22% | 3.4 / 6.7 / 13x | ≈0 |
| N17 F_sl1/tp1.5 | 0.86% | 6.8 / 13.5 / 26x | 0.20 |
| V45 AMB_G1 F_sl2/tp3 | 0.83% | 7.3 / 14.5 / 27.7x | 25.9 |
| V45 AMB_G1 L50_sl15 (ladder) | 0.25% | 76 / 136 / 193x | ×20 would be reached |
| N17 L50_sl20 (ladder) | 0.43% | 27 / 51 / 89x | |

Net edge needed per trade for a median ×20 in 30 days at 40%×50x:

| Exit family | Required net edge | Best observed |
|---|---|---|
| Ladder | 0.07–0.13% | −0.16% |
| ATR exits | 0.20–0.76% | −0.05 to −0.18% |

- Gap 2 shows that the ladder's shape only helps if the signal is oracle-grade.
- **Implication:** whatever A or B finds would have to be sized at about 1–5x notional, which is incompatible with the 50–60x / 30–40% plan and with the ×20-per-month target. The handoff leaves "목표 재설정" open. It should be settled with these numbers before A or B.
- Caveat: pooling trade rates across symbols assumes concurrent 40%-margin positions, which is over-allocation (ENG-6). That makes these numbers optimistic.

## Gap 4: Coverage. 12 of 31 strategies untested, the native FINGRAD engine not replicated, and live bots

Scripts: `work/extra_ports.py` (spec-based APPROXIMATE ports written from the 31-strategy report, not checked against the FINGRAD source) and `work/run_extra.py`. Outputs: `work/extra_pooled.csv`, `work/extra_forward.csv`.

Six of the excluded strategies, 15m IS, 5 symbols, 13 exits: **0 of 78 pass**.

| Strategy | Best exit | Trades | PF | Net per trade | Symbols positive | fwd16 | fwd64 |
|---|---|---|---|---|---|---|---|
| N11 | trail2.5 | 52 | 1.07 (n<100, fails) | | 2 | −0.338% | |
| N13 | SL2/TP3 | 696 | 0.82 | | | +0.111% (788 signals) | |
| N19 | SL2/TP1.5 | 562 | 0.94 | −0.029% | 1 | | −0.223% |
| N20 (short-only) | | | 0.85 | | | | +0.169% (bear market) |
| S4 | | | 0.71 | | | | |
| N15 | | 7 signals | | | | | |

- The results largely support the headline.
- The handoff's "4시간 뒤 +0.1% 넘는 건 S5뿐" holds only for the tested 28: untested N13 is +0.111% at 16 bars.
- Still untested: S1, S3, N04, N05 and N06, which need the POC, Klinger, chop-proxy and ORB helpers (all present in `fg_indicators.py`), plus N16.
- The handoff says "FOCUS5 rc1 봇 2대 가동 중" and lists rc1/C1 status as unanswered. Nobody has established which strategies, fee setting (the code uses TAKER_FEE_RATE = 0.0002) or capital those bots run. If they are live, that matters more than any backtest.

## Gap 5: Option C can be closed now

Script: `work/c_1m.py`. Output: `work/c_1m_trades.csv`. Data: `data1m/` (sha-verified).

Method: the same 5m V4.5 entries from the reproduced ledger, Sep 2026 (entries 2026-08-31 17:31 to 2026-09-27), re-simulated on Astral 1m bars with the same engine rules applied per 1-minute bar.

- The 1m bars resampled to 5m reproduce the delivered 5m-file results exactly (orig = r5 for all exits), so the comparison is apples to apples.
- The 1m files have 0 gaps. ETH's 1160-minute gap on 2026-09-28 in the 5m file is filled here.

| Strategy / exit | n | Net per trade 5m → 1m | Paired difference | PF 5m → 1m | Win rate 5m → 1m |
|---|---|---|---|---|---|
| AMB_G1 L50_sl15 | 202 | −0.1699 → −0.1703% | −0.0004 ± 0.0083% | 0.221 → 0.202 | 42.1 → 43.6% |
| AMB_G1 L50_sl20 | 186 | −0.1407 → −0.1405% | | 0.293 → 0.279 | |
| V45_ANY L50_sl15 | 818 | −0.1675 → −0.1682% | | 0.239 → 0.211 | |

- At a 0.01% fee the 1m win rate for AMB_G1 L50_sl15 is still only 48.5%, against the report's 75%. Bar resolution does not explain the Sep 5–13 discrepancy; the remaining candidates are data (spot vs mark), fee and the symbol set.
- Fixed SL/TP results are identical at 1m.
- This agrees with ENG-1/ROB-2, now on real 1m data rather than a synthetic martingale or 15m → 5m.
- Recommendation: drop C as a stage.

## Gap 6: Option A cannot run as documented, and its protocol is undefined

- `python3 run.py --tf 1h` raises `ValueError: invalid literal for int() with base 10: '1h'` at run.py:110, verified in my copy. `--tf 60m` would need files named `*-60m-ohlcv.csv`.
- forward.py:44 hard-codes the `-15m-` file names.
- max_hold and warmup are counted in bars: 1,000 bars is about 41.7 days at 1h and 167 days at 4h.
- V4.5 needs 5m plus a confirmed 15m frame, and V3.9 has 15m/5m chart modes. "Same 28 on 1h" silently changes the meaning of these Pine strategies.
- The price_get tf enum is 1m/5m/15m/30m/1h/1d, so there is no 4h; resample from 1h.
- Fresh 1h data needs `limit=40000, end=2025-08-06T23:00Z` (demonstrated for 1m: limit+end is honoured). The default last-40,000 pull re-includes the inspected 14 months (DATA-6).
- A family-wise null and a minimum trade count or t requirement (ROB-5/STAT-7) must be fixed before the pull.

## Other small observations

- Delivered results reproduce: the Sep 1m-resampled 5m bars equal the 5m file for these trades.
- Astral 1m history is continuous; the 40,000-bar limit applies per request (confirmed).
- The results report's "15분 1 ATR 중앙값 0.54%" was already corrected by CLM-7 (median 0.464%).

## Astral calls (read-only price_get)

1. BTCUSD 1m, start 2026-09-01, end 2026-09-28T12:00, download: returned only the last 5,000 bars (the truncation trap above). sha ada4c3b0…
2. BTCUSD 1m, limit 40000, end 2026-09-28T12:00Z: 2026-08-31 17:21 → 09-28 12:00. sha c539f04e… (verified)
3. ETHUSD 1m, same window. sha 3af8cd2b… (verified)
4. SOLUSD 1m, same window. sha 95190ce6… (verified)
