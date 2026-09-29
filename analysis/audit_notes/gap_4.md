# gap_4 notes: coverage of the 31-set, the native FINGRAD engine, and the FOCUS5 rc1 bots

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/gap_4`

- Nothing under `/home/user/crypto-bot-research` was modified: `git status --short` is empty.
- No Astral tool was called.
- The code is a copy of `bt/` in `gap_4/bt` (unchanged), plus `gap_4/work/*`.
- Data is used through a symlink to the project `data/`.
- **Window:** 15m, in-sample only (2025-08-07 .. 2026-05-07). The stage-1 out-of-sample window stays sealed, because nothing passed.

## Bottom line

1. **What stage 1 actually covered.** Stage 1 ran 19 of the 31 FINGRAD strategies, on 15m only.
   - N14 and N21 produce 0 signals, so only 17 of 31 produced any trades.
   - None of the 31 was run on 5m. ALT5 runs live on 5m.
   - The excluded 12 (S1, S3, S4, N04, N05, N06, N11, N13, N15, N16, N19, N20) include 3 of the 4 live-audit positives (N11, N13, N19).
   - The handoff's "31개 매매법 … 통과 0개" (line 9) therefore overstates coverage.
2. **Filling the gap does not change the headline.** I ported all 12 from the prose spec, with the documented structural stops, and re-ran every tested strategy through the FINGRAD gate and a native-lite exit engine:
   - (B) 13 stage-1 exits, 12 new ports plus 4 reading variants: **0 of 208 pass**.
   - (C) Hard-cap gate (structural stop ≤ 0.6%) × 13 exits, over all 31-set strategies with signals plus variants: **0 of 416 pass**, max PF 0.909.
   - (D) Native-lite engine: structural SL, −30% net-ROE cap, net-ROE profit lock and CONFIRM_2 exits. Run × {no gate, 0.6%, cap-consistent gate} × {real 0.05%+0.02% cost, FINGRAD 0.02%+0.01% cost}: **0 of 194 pass**. With ≥100 trades the best is PF 0.918 (N13 variant, FINGRAD fee), falling to PF 0.64 at the real fee.
3. **The requested diff against `evaluate()` is impossible.**
   - `fingrad_bot/strategies/*.py` is not in either uploaded zip or anywhere on disk. The handoff §7 says the CORE4/ALT5/FOCUS5 zips stay with the user.
   - The prose spec does not pin down the signals: two careful independent ports agree at signal-level Jaccard 0.72 (N13), 0.79 (N19) and 0.82 (N11) under one ambiguous reading. They agree 1.00 for N19/N20/S4/N15 under the shared reading.
   - Bar-level agreement stays ≥ 99.8% even at Jaccard 0.72. A "≥99% equality" criterion must therefore be defined on signal events.
4. **The 7-day live-audit "positives" are what noise produces.**
   - At FINGRAD's own fee with the gate, all 28 trading strategies have negative 9-month expectancy.
   - Yet a median of 6 of them are positive in any 7-day window (IQR 4–8), and 84% of weeks have ≥ 4 positive strategies.
   - Choosing strategies (FOCUS5?) from a 7-day audit is selection on noise.
5. **FOCUS5 rc1 cannot be evaluated.** Its strategies, timeframe, symbols, fee setting, capital and PAPER-vs-LIVE status are not in the package. The conditional verdict is under the FOCUS5 section below. Ask the user (Korean text below).

## Files

| File | What |
|---|---|
| `work/critic_extra_ports.py`, `work/critic_rerun.py` | The critic's 6 ports and runner, re-run unchanged. Output: `critic_rerun_pooled.csv` / `critic_rerun_forward.csv` |
| `work/poc_fast.py` | numpy version of `fg.rolling_volume_profile_poc(full_series=True)`, with a parity test |
| `work/ports12.py` | My independent spec ports of all 12 excluded strategies, with structural stop, documented trailing and strategy-specific exit. Ambiguous readings are behind `variant` switches |
| `work/stops17.py` | Documented structural stops wrapped around the unchanged stage-1 signal functions for the 17 tested 31-set strategies with signals |
| `work/native.py` | Native-lite FINGRAD exit simulator |
| `work/agree.py` | Two-porter agreement (critic vs gap_4). Output: `work/agree.csv` |
| `work/run_gap4.py` | Parts A–D. Output: `work/out/parts_*.pkl` |
| `work/agg_gap4.py` | Aggregation. Output: `work/out/agg.txt`, `A_forward_pooled.csv`, `B_pooled.csv`, `C_pooled.csv`, `D_pooled.csv`, `gate_stats.csv` |
| `work/fwd_null.py` | Circular-shift null (same shift for all symbols), 1,000 reps, 177-member family. Output: `work/out/fwd_null.csv` |
| `work/weekly.py` | 7-day-window positive-share analysis of the native ledgers |
| `work/out/summary_table.csv` | One row per strategy across parts A–D |

**Runtime:** the full run took about 90 s in 2 processes; `fwd_null` about 110 s.

## 1. Coverage facts, with citations

**What the handoff and the earlier report say**

- Handoff line 36: "31개 중 표준지표 19개(S2·S5·S6·N01·N02·N03·N07·N08·N09·N10·N12·N14·N17·N18·N21·N22·N23·N24·N25 …) … 31개 중 근사식 12개는 원본이 없어 제외. N14·N21은 14개월 동안 신호 0건."
- The previous session's 31-set report (critic/doc_31set.txt) contradicts that exclusion reason:
  - Line 56: "31개 전부 코드로 재현 가능하다(REPRODUCIBLE_FROM_CODE 31/31)".
  - Line 3/6: "31개 전부 같은 신뢰 등급".
  - Lines 219–312 document every condition and stop for all 31.
- The report's own category counts are inconsistent. Line 56 says 표준 15 / 근사 14 / 모드 2. Its table (lines 62–216) gives 16 / 13 / 2. The excluded set is exactly the 12 RESEARCH_APPROX; N25 (근사식, FRIEND_SOURCE) was included.

**The code "original" exists in the package for the helpers**

- `bt/fg_indicators.py` is the verbatim `indicators.py`.
- It already holds every helper the 12 need: `chop_zone_proxy` L194, `klinger_oscillator` L444, `rolling_volume_profile_poc` L465, `mapped_rsi_bollinger` L529, `confirmed_pivot_low/high` L558/L573, `research_chop_zone` L608, `research_chop_regime` L621.
- What is missing is only the `strategies/*.py` wiring.
- `bt/strategies.py:8` claims the ports "reproduce fingrad_bot/strategies/*.py evaluate() logic". No test in the package checks that. `test_fg_fast.py` only checks indicator parity for supertrend, PSAR, HA, Aroon and CCI.

**What stage 1 actually ran**

- `results/summary_IS_15m_all5.csv` has 28 strategy names: 19 from the 31-set plus 9 V3.9/OBV.
- `results/summary_ALL_5m_v45g1.csv` has only V45_ANY, V45_EXACT_AMB, V45_EXACT_AMB_G1 and V39_15M_G1. **No 31-set strategy was ever run on 5m.** The report (line 43/49) shows the live engine runs both 5m (cap −20) and 15m (cap −30), and ALT5 runs on 5m.
- Handoff line 9 says "14개월 백테스트". The 15m grid ran on 9 months in-sample and the 5m grid on 4.6 months.

**Live-audit positives:** N19, N13, N08 and N11 (handoff line 26). Stage 1 tested only N08.

## 2. Critic re-run (reproduces)

`work/critic_rerun.py` (unchanged logic): **0 of 78 pass**, max PF 1.0705.

| Strategy | Result |
|---|---|
| N11 | T_sl1.5_tr2.5: 52 trades, PF 1.070, 2/5 symbols |
| N19 | F_sl2/tp1.5: 562 trades, PF 0.943, −0.029% |
| N13 | F_sl2/tp3: 696 trades, PF 0.822. Forward: 788 signals, fwd16 +0.111%, fwd64 +0.155% |
| N20 | Best PF 0.846 |
| S4 | Best PF 0.710 |
| N15 | 7 signals |

These match the task text.

## 3. Ports of the 12 (spec-based; NOT verified against FINGRAD code)

Spec source: `critic/doc_31set.txt` lines 219–312. Structural stops are as documented.

**Ambiguous readings, each tested as a variant**

- **Prior-trend window for patterns (N11, N13, S3).**
  - My primary reading: the 5 bars before bar 1, first vs last close. For N13 that is c[t-3] vs c[t-7].
  - The critic's reading (`~v1`): c[t-3] vs c[t-8].
- **N19 range exclusion.**
  - Primary: shift 3, i.e. bars t-36..t-3 (same as the critic).
  - `~v1`: shift 4.
- **N11 "5봉 저가" stop.**
  - Primary: lowest low of the 5 pattern bars.
  - `~stopbar5`: low of bar 5 only.
- **N06 ORB.** Uses the first bar of each UTC date. The breakout test uses the same day's level; the opening bar itself is excluded.
- **N16 divergence.** Uses consecutive confirmed price pivots (L3/R3), spaced 5–60 bars, compared on mapped RSI. **Lowest fidelity** of the 12.
- **N05 POC.** `poc_fast.poc_series` equals `fg.rolling_volume_profile_poc(full_series=True)` exactly: BTC and BCH, 2,901 of 2,901 windows each, max |diff| 0.0. It is 18× faster.

**Two-porter agreement (`agree.py`, 5 symbols, in-sample, bars ≥ warmup)**

| Strategy | Critic signals | gap_4 signals | Same | Jaccard | With the critic's reading |
|---|---|---|---|---|---|
| N11 | 52 | 48 | 45 | 0.818 | 1.000 |
| N13 | 788 | 801 | 666 | 0.722 | 0.974 (remaining diff: ATR bar reference) |
| N19 (the critic's reading, shift 3) | 764 | 764 | 764 | 1.000 | |
| N19 (`~v1`, shift 4) | 764 | 663 | 631 | 0.793 | |
| N20, S4, N15 | | | | 1.000 | |

- On BTC, bar-level agreement is ≥ 0.9984 in every case.
- **Conclusion:** the prose spec leaves 18–28% of pattern-strategy signals undetermined. Only the real `strategies/*.py` can settle it.

## 4. Results (15m in-sample, 5 symbols, stage-1 cost 0.05% + 0.02% slippage, funding 0.01%/8h unless stated)

### Sanity check

`stops17` wrapper plus the stage-1 engine versus the delivered `pooled_IS_15m_all5.csv`: 34 rows (17 strategies × {F_sl2/tp3, L50_sl20}). Δtrades is 0 and max |ΔPF| is 5.4e-15, so the wrapping is exact.

### A. Forward drift

Gross, no position overlap control, pooled. z is from the circular-shift null that keeps co-timing (`fwd_null.py`).

| Signal set | n | fwd16 | Null z16 | fwd64 | Null z64 |
|---|---|---|---|---|---|
| S5 (stage-1 best) | 324 | +0.103% | 1.31 | +0.090% | 0.53 |
| N13 (mine) | 801 | +0.098% | 1.83 | +0.093% | 0.97 |
| N13 ~v1 | 795 | +0.101% | 1.84 | +0.142% | |
| N13 (critic) | 788 | +0.111% | | +0.155% | |
| N13 gated ≤0.6% | 121 | +0.184% (naive t 2.35) | 1.53 | +0.414% (naive t 2.82, 5/5 symbols) | 1.62, p_one 0.050, **family p 0.99** |
| N16 gated | 427 | +0.148% (naive t 3.15) | 2.22, p_one 0.011, **family p 0.75** | +0.074% | |
| N09 (tested) | 1,796 | +0.083% | 2.32, family p 0.66 (the family's top z) | | |
| N20 (short only) | 5,589 | | | +0.169% (naive t 4.8) | 0.94: null mean +0.099% is the bear-market drift |

- **Family:** 59 members × 3 horizons = 177 tests. No member survives the family-wise max-z test.
- **"Only S5 exceeds +0.1% at 4h"** is true for the tested 28. N13 sits at +0.098/+0.101/+0.111% depending on the port, i.e. tied with S5 and within noise.
- **forward.py's per-symbol t overstates.** It ignores overlapping and co-timed signals. Example: N20's naive t is 4.8 against a null z of 0.94.

### B. 13 stage-1 exits, no gate (12 new ports plus 4 variants)

- **0 of 208 pass.** 7 combos have PF ≥ 1.0 and 2 have PF ≥ 1.2, but all of those have fewer than 100 trades.

| Group | Combo | Trades | PF | Net per trade | Symbols positive |
|---|---|---|---|---|---|
| Small n | S1 F_sl2/tp1.5 | 21 | 1.92 | | |
| Small n | N11 T_sl1.5_tr2.5 | 48 | 1.11 | | 3/5 |
| n ≥ 100 | N19~v1 F_sl2/tp2 | 484 | 0.993 | −0.004% | 3/5 |
| n ≥ 100 | N19 F_sl2/tp1.5 | 562 | 0.943 | | |
| n ≥ 100 | N16 F_sl2/tp3 | 1,148 | 0.905 | | |
| n ≥ 100 | N20 | 1,808 | 0.846 | | |
| n ≥ 100 | N05 | 714 | 0.844 | | |
| n ≥ 100 | N04 | 3,446 | 0.790 | | |
| n ≥ 100 | N13 | 709 | 0.780 | | |
| n ≥ 100 | N06 | 731 | 0.770 | | |
| n ≥ 100 | S3 | 859 | 0.727 | | |
| n ≥ 100 | S4 | 2,018 | 0.710 | | |

N15 has 7 trades.

### Gate statistics

Share of in-sample signals whose structural stop is 0 < d ≤ 0.6% of the signal close (`gate_stats.csv`).

| Share passing | Strategies |
|---|---|
| Under 10% | S1 0%, S2 3.6%, N02 4.4%, N25 6.6%, N04 6.9% |
| 10–25% | N11 10%, N13 15%, N23 19%, N19 23%, N18 23%, N22 22%, N03 22% |
| 25–60% | N24 30%, N16 30%, N09 31%, N10 35%, S5 41%, N06 41%, N20 44%, N01 46%, N12 48%, S6 52%, N17 53%, N07 53%, N08 57% |
| Over 60% | S4 65%, S3 77%, N05 85%, N15 100% |

- **Wrong-side stops:** 17 (S3 only).
- The gate is a hidden entry filter that removes most signals of the Supertrend-stop strategies. What the live bots traded is a very different subset from what stage 1 tested.

### C. Hard-cap gate × 13 stage-1 exits (all 31-set with signals, plus variants)

- **0 of 416 pass.** Max PF 0.909 (N09 F_sl2/tp2, 468 trades). No combo reaches PF 1.0.

| Strategy (gated) | Best PF | Trades | Exit |
|---|---|---|---|
| N19 | 0.845 | 128 | |
| N13 ~v1 | 0.770 | 118 | |
| N13 | 0.699 | 116 | |
| N11 | ≤ 0.88 | ≤ 17 | |

### D. Native-lite engine (`native.py`)

**What it models**
- Entry gate: wrong-side stop is blocked; stop beyond `gate` is blocked.
- Structural stop, fixed at entry.
- Documented trailing for S1, S4, N04, N05, N06 and N16, applied favourably only.
- Hard cap at net ROE −30% at 50x. The price distance is 0.46% at real cost and 0.54% at FINGRAD cost.
- Profit lock on net ROE: +13 → +10; ≥ +20 → floor(peak/5)×5−5. Peak through the previous bar.
- CONFIRM_2 opposite-signal and strategy-specific exits.
- Max hold 1,000 bars.

**What it does not model**
- 1m/5m stop confirmation and 0.25 s monitoring.
- One position per strategy across symbols, and confidence ranking.
- Noise-floor and spread gates.
- Trailing and specific exits for the 17 tested strategies (stop-only, "lite").

**Hand traces verified**
- LOCK short: peak net ROE 15.48 → protect 10 → lock 111,063.47. The price gapped through; filled at open 111,137.65 plus slippage, +6.5% ROE.
- CAP short: cap 112,350.58, filled at 112,373.05, −30.05% ROE.

**Results**

- **0 of 194 pass.** 1 combo has PF ≥ 1.0: S1, FINGRAD cost, no gate, 21 trades, PF 1.318.
- Best with ≥ 100 trades:

| Strategy | Cost | Gate | PF | Trades | Net per trade |
|---|---|---|---|---|---|
| N13~v1 | FINGRAD | 0.6 | 0.918 | 119 | −0.015% |
| N13 | FINGRAD | 0.6 | 0.844 | 118 | |
| S5 | FINGRAD | 0.6 | 0.837 | 127 | |
| N19 | FINGRAD | cap 0.54 | 0.878 | 100 | |

- **At real cost** the same combos fall to PF 0.64 (N13~v1), 0.60 (N13), 0.57 (S5) and 0.50 (N19).
- **Exit reasons** (`NATIVE_fg_gate0.6`, all strategies): LOCK 11,628, SL 9,511, CAP 1,416, UEX 45, OPP 42.
  - CONFIRM_2 almost never fires because the signals are one-bar events.
  - Most profitable exits are the +10 lock, i.e. about 0.2–0.3% price. This is the same small-win structure the handoff criticised for the stage-1 ladder.

**Live positives under native-lite with the gate**

| Strategy | FINGRAD cost 0.02% | Real cost 0.05% |
|---|---|---|
| N08 | PF 0.65, 134 trades | PF 0.40 |
| N11 | 5 trades | |
| N13 | PF 0.84, 118 trades | PF 0.60 |
| N19 | PF 0.75, 135 trades | PF 0.50 |

All four have negative net per trade at both fee levels.

### Weekly noise check (`weekly.py`, 37 full weeks, 28 trading strategies)

| Config | Positive strategies per week, median (IQR) | Weeks with ≥ 4 positive |
|---|---|---|
| NATIVE_fg_gate0.6 | 6 (4–8) | 84% |
| NATIVE_fg_gatecap0.54 | 6 (4–8) | 89% |
| NATIVE_real_gate0.6 | 3 (2–5) | 38% |

- All 28 strategies have negative in-sample mean net in every config.
- The four live positives have weekly-positive shares of 0.34–0.52 (N13 0.52, N19 0.45, N11 0.40, N08 0.34). They are the least negative, not positive.
- **"4 of 31 positive in 7 days" (live audit, 0.02% fee) is exactly the noise expectation.**

## 5. FOCUS5 rc1: what is known, what is not, verdict

**Known**
- Handoff line 21: "FOCUS5 rc1 봇 2대 가동 중이라고 함".
- Line 64: "rc1/C1 봇 현재 상태" is unanswered.
- Line 99: `FOCUS5_31_STRATEGY_FINAL_HANDOFF_20260929.zip` belongs to the 31-strategy project and is dated today. It is not in the package.
- The 31-set report says:
  - `TAKER_FEE_RATE = 0.0002` and `SLIPPAGE_RATE = 0.0001` (line 39/10).
  - `settings.py` forces 40% margin × 50x and hard caps −20/−30; other values give a startup error (line 41).
  - The 7-day audit lost −23.8% with fees at 53% of the loss (handoff line 26).
- No auditor found any FOCUS5 config (scratchpad grep).

**Unknown**
- Which strategies ("FOCUS5" could be 5 strategies or 5 symbols).
- Timeframe (5m and/or 15m).
- Symbols, fee setting, capital.
- PAPER vs LIVE (real money).
- P&L since start.

**Cost gap if rc1 uses the 0.0002 setting while the account pays Binance taker 0.05%**
- The per-trade understatement is 0.06% of notional in fees, or 0.08% with the slippage difference.
- At 40% × 50x (notional = 20× equity) that is **1.2–1.6% of equity per trade**.
- At the audit's 22 trades per ledger per week (2,728 / 124), that is about 26–35% of equity per week missing from the bot's P&L.
- This matches the report's 18% → 45% weekly fee drag.

**Verdict (conditional, since the config is unavailable)**
- Suppose rc1 runs any subset of the FINGRAD 31 on these symbols at 15m with the documented engine. Then every configuration tested here predicts a loss, including at the bot's own 0.02% fee.
  - B/C/D: 0 of 818 combos pass.
  - All 28 trading strategies have negative expectancy under native-lite at 0.02%.
- Any 7-day profit it shows is uninformative.
- **If rc1 trades real money, stop it (or cut it to minimum size) until the config is known. If it is PAPER, do not read its P&L as evidence.**
- 5m was not tested for any of the 31. The live ALT5 5m behaviour is untested here.

**Korean ask to relay to the user**

> 두 가지를 먼저 받아야 합니다. (1) `CORE4_WINDOWS_EASY_V3_3_1.zip`(또는 그 안의 `fingrad_bot/strategies/*.py`, `strategies/__init__.py`, `risk.py`, `exit_engine.py`, `stop_engine.py`, `settings.py`, `config/strategies.json`) — 지금 12개 전략은 보고서 문장만 보고 이식해서, 두 사람이 따로 이식하면 신호가 18~28% 달라집니다. (2) 지금 돌고 있는 FOCUS5 rc1 봇 2대의 설정: 어떤 전략·종목·봉(5분/15분), 실거래인지 PAPER인지, 수수료 설정값(TAKER_FEE_RATE), 투입 자본, 시작일과 거래 기록(CSV). 실돈이면 설정 확인 전까지 멈추거나 최소 금액으로 줄이는 걸 권합니다 — 이 분석에서 31개 중 어떤 것도 9개월 구간에서 수수료 0.02% 기준으로도 기대값이 양수가 아니었고, 7일 동안 양수였던 전략 4개는 우연으로 설명되는 수준입니다.

## 6. Caveats

- All 12 ports and every structural stop are **spec-based**. They are not verified against the FINGRAD code; the one-reading Jaccard ranges from 0.72 to 1.0 by strategy.
- N16 and N06 have the most interpretive freedom.
- Native-lite is bar-level:
  - **1m stop confirmation.** It can either save wick stops or overshoot the cap; the direction of the bias is unclear.
  - **Lock peak through the previous bar.** This is conservative for the lock.
  - **Per-symbol independent positions.** FINGRAD holds one position per strategy across symbols.
- The noise-floor gate multiplier is unknown and not modelled. It would remove even more signals.
- The data is Polygon spot, not Binance mark prices (same caveat as stage 1).
- Only the in-sample window was used. A future 5m 31-set test should use 5m bars ending ≤ 2026-05-07 (inside the already-inspected in-sample window), which Astral can serve with `limit+end`, to avoid touching the sealed out-of-sample window.
