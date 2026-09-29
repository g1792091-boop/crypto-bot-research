# Gap-fill check #5: can Option C (1m exit-model validation) be closed?

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/gap_5`

Nothing under `/home/user/crypto-bot-research` was modified. `git status --short` is empty; `bt/` was copied into `gap_5/bt` and `data/` is a symlink. No Astral tool was called. The 1m CSVs were copied from `critic/data1m`.

## 0. Bottom line

- **The critic's c_1m.py result reproduces exactly.** My re-run output is byte-identical to `critic/work/c_1m_trades.csv`; the script takes 3.3 s, not about 1 min.
  - V45_EXACT_AMB_G1 L50_sl15, n=202: net per trade is −0.1699% at 5m and −0.1703% at 1m. Paired difference −0.0004 ± 0.0083%. PF 0.221 → 0.202. Win rate 42.1% → 43.6%. At a 0.01% fee the win rate is 48.5%.
  - V45_ANY L50_sl15, n=818: −0.1675% → −0.1682%.
- **Two small overstatements.**
  - "Resampled 1m reproduces the 5m results exactly" is true for 3,404 of 3,433 trades. 29 trades differ, one of them flipping LOCK→SL. The worst summary effect is −0.001%/trade (V45_ANY L50_sl20). The cause is that Astral's 1m and 5m/15m snapshots disagree on 2026-09-25..28 (§2).
  - "Fixed SL/TP exits are identical" holds for the 5m V4.5 entries. It does not hold exactly for 15m entries: there 1m improves fixed exits by +0.0005 to +0.0103%/trade, because the engine's SL-first rule on bars that touch both SL and TP gets resolved.
- **New: bounding the sub-minute path.** I re-simulated every trade under three intrabar assumptions: PESS (= engine), DET (a lock exit that is certain given the bar's high and close), and OPT (favourable extreme first).
  - For the V4.5 ladder, the 1m band is PESS −0.1703% / DET −0.1541% / OPT −0.1491% per trade, with PF 0.20 / 0.27 / 0.28.
  - OPT gives the maximum win rate any tick path can produce from these 1m prices: 50.5% at 0.05% fee, 57.6% at 0.01% fee with 0 slippage.
  - **No tick path can produce the report's 75% or a positive expectancy at the real fee.**
- **RC2 window (Sep 5–13), handoff-style single account.**
  - The handoff's "59 trades, 46%, 1,000 → 380" reproduces exactly: entries 2026-09-04 07:00Z to 09-13 08:00Z, **fee 0.01%**, slippage 0.02%, 5m bars.
  - The same window on 1m gives 415 (PESS), 495 (DET) and 506 (OPT).
  - At 0.01% fee **and zero slippage**, the 1m best case is 999 (−0.1%), with a 61.7% win rate over 47 taken trades.
  - The report says 2,725 (+172%) with a 75% win rate over 56 trades.
  - Resolution, fee and slippage together close about 620 of the 2,345-point gap. The rest must come from data (spot vs Binance mark/last), the symbol set (the report adds LTC/BCH), and the report's post-hoc choice of this candidate on this same 7.7-day window.
- **15m extension** (30 strategies, BTC/ETH/SOL, September trades from an ALL-window run; 50,896 trade × exit rows).
  - Pooled, 1m minus 15m (PESS) is +0.0057 ± 0.0025 (L50_sl15), +0.0078 ± 0.0028 (L50_sl20), +0.0009 ± 0.0024 (T1.5), −0.0019 ± 0.0021 (T2.5), and +0.0005 to +0.0103 for the 9 fixed exits. By family: F +0.0053, L +0.0067, T −0.0003.
  - **The "< 0.01%/trade" condition therefore holds pooled, but not per combo.**
    - Pooled over the 4 named strategies, L50 is +0.015 to +0.018 (± 0.010 to 0.012).
    - S6 L50_sl15/sl20 is +0.083 ± 0.026 and +0.099 ± 0.030.
    - 89 of 312 combos with n≥30 have |d| > 0.01.
  - The direction is almost always 1m ≥ bar: the 15m engine is slightly pessimistic.
- **The verdict cannot flip.** Making any of the 364 15m-IS combos pass (PF≥1.2 and exp>0) needs a uniform shift of at least **+0.133%/trade** (L50 at least 0.140, S6 L50 0.197). The 52 5m combos need at least +0.145.
  - The largest 1m-vs-bar correction I measured is +0.099, for S6 L50_sl20 with n=59.
  - The pooled corrections are 0.006 to 0.018.
  - The whole 1m path band (OPT − PESS) adds only 0.02 to 0.03 on top.
- **Nuance: the pooled null result hides per-trade changes.** About 30% of L50 trades change by more than 0.01% of price, and about 21% by more than 0.05%, but the changes cancel. Stage 1's bar model is right on average, not trade by trade.
- **Nuance: 1m data were needed for 15m L50.** The 15m-bar path ambiguity for L50 (r15 OPT − PESS) is **+0.11 to +0.14%/trade**, which is close to the 0.14 needed to matter. 1m data shrink it to about 0.03. So C was informative. It is now effectively done, for BTC/ETH/SOL on Astral spot data.
- **Recommendation.** Mark C as done in the handoff (proposed text in §8), but do not claim that bar resolution was "irrelevant" in general. C cannot test spot vs mark, the LTC/BCH symbol set, or the report's selection bias. Only the symbol set is testable with Astral: LTC/BCH 1m, 2 price_get calls.

## 1. Inputs verified

- **1m files**, sha256:
  - btc c539f04e…
  - eth 3af8cd2b…
  - sol 95190ce6…
  - These match the critic's notes.
  - Each file has 40,000 rows covering 2026-08-31 17:21 → 2026-09-28 12:00Z, with 0 gaps, 0 duplicates, 0 OHLC violations, 0 flat bars and 0 zero-volume bars (`work/check_1m_data.py`).
  - The claim that `price_get` truncates to 5,000 bars when given start+end was **not** re-verified; that would need an Astral call, which my task did not authorise.
- **Repo copy.** `critic/bt` and my `gap_5/bt` are identical to `/home/user/crypto-bot-research/bt`.
- **My 15m ALL-window run** (`run.py --window ALL --tf 15m --symbols BTCUSD,ETHUSD,SOLUSD --tag gap5_3sym`, 3m47s) matches the repro IS ledger exactly for all 526,730 BTC/ETH/SOL trades with entry before the split. Max |Δnet| = 0.

## 2. 1m vs delivered 5m/15m consistency (`work/check_1m_data.py`, `work/check_1m_diff_sign.py`, inline script)

- **Complete buckets.**
  - The 1m→5m resample matches the delivered 5m file for 7,999/7,809/7,998 complete buckets (BTC/ETH/SOL).
  - The 1m→15m resample matches for 2,666 buckets per symbol.
- **Before 2026-09-25**, only 1–2 bars per symbol and timeframe differ at all: the partial first bucket on 08-31 and one ETH 15m bar on 09-22.
- **From 09-25 to 09-28**, 30–90% of bars per day differ.
  - The 1m series almost always has a lower high or a higher low than the 5m/15m file.
  - The mean |diff| is 0.013–0.04%, with a maximum of 0.28% (ETH).
  - The likely cause is a data snapshot or revision difference.
- **Effect on c_1m.py.**
  - With the critic's window (exit ≤ 09-27 12:00), 29/3,433 trades differ between orig and r5.
  - Restricting to entries before 09-24 12:00 gives orig==r5 in 99.4–100% of trades.
  - The paired m1−r5 differences on that subset are the same as on the full sample (§4).
- **Direction:** neutral. **Changes the conclusion:** no.

## 3. Method: three intrabar-path models (`work/sim_modes.py`, `work/sim_vec.py`)

- **PESS**
  - Identical to `engine._simulate_one`: adverse extreme first, and a stop raised by bar j is only live from bar j+1 (engine.py:96-116).
  - Validated at 0 mismatches over 5,850 random trades × 13 exits on 5m, 15m and 1m data (`validate_sim.py`).
  - The vectorised version matches the loop version and the engine over 3,120 trades per mode (`validate_vec.py`).
- **DET**
  - PESS, plus one case that no finer path can dispute: bar j's high raises the stop to S′ > S, the low does not reach S, and the close is beyond S′. The price must then have crossed S′ after the high, so the exit is at S′ minus slippage.
  - The engine instead fills at the next bar's open, which is about close_j and worse.
- **OPT**
  - Favourable extreme first: the stop is raised by the bar's own extreme before the adverse extreme is tested, and TP comes before SL.
  - For the ladder, the OPT win rate is a hard upper bound over all intrabar paths consistent with the bars. An OPT loss means the SL was hit before the +12% ROE trigger in every path.
  - For the mean it is a best-case scenario, not a strict bound.

## 4. 5m V4.5 entries on 1m (`work/c_1m_ext.py`, `work/summ_5m.py`)

These are the same trades as c_1m.py, for 3 strategies × 13 exits: 13,143 trade × exit rows. Output is in `out/c_1m_ext_summary_*.csv`.

| combo | n | 5m (r5) | 1m PESS | d (1m−5m) | 1m DET−PESS | 1m OPT−PESS | 5m OPT−PESS | PF 5m / 1m / 1m-OPT | WR 5m / 1m / 1m-OPT |
|---|---|---|---|---|---|---|---|---|---|
| AMB_G1 L50_sl15 | 202 | −0.1699 | −0.1703 | −0.0004±0.0083 | +0.0162 | +0.0212 | +0.0465 | 0.221/0.202/0.284 | 42.1/43.6/50.5 |
| AMB_G1 L50_sl20 | 186 | −0.1407 | −0.1405 | +0.0002±0.0086 | +0.0213 | +0.0236 | +0.0504 | 0.293/0.279/0.387 | 52.2/54.8/63.4 |
| AMB_G1 T1.5 | 212 | −0.1768 | −0.1853 | −0.0085±0.0125 | 0 | −0.0021 | −0.0274 | 0.270/0.233/0.224 | |
| ANY L50_sl15 | 818 | −0.1675 | −0.1682 | −0.0007±0.0035 | +0.0177 | +0.0156 | +0.0389 | 0.239/0.211/0.271 | 40.8/44.0/50.2 |
| ANY L50_sl20 | 708 | −0.1447 | −0.1463 | −0.0016±0.0039 | +0.0227 | +0.0176 | +0.0412 | 0.310/0.276/0.350 | |
| all 27 fixed combos | | | | −0.0001 to +0.0030 | 0 | 0 | 0 to +0.0031 | | |

- **Across all 39 combos, |d| ≤ 0.0085%/trade.** The condition holds for every combo.
- **Per-symbol d** (AMB_G1 L50_sl15): BTC −0.0099 ± 0.0074, ETH +0.0061 ± 0.0140, SOL +0.0004 ± 0.0183. The pre-09-24 subset gives −0.0003 ± 0.0089.
- **Per-trade view** (AMB_G1 L50_sl15): 62/202 trades change by more than 0.01% of price (28 better, 34 worse) and 43 by more than 0.05%. Only 2 trades move SL→LOCK. The median LOCK exit is 9.8% gross ROE at 1m PESS and 10.0% at OPT.
- **Fully sequential re-run** (`work/seq_1m.py`: signals regenerated from `strategies.v45_exact_amb_g1`, exits on 1m, per-symbol one position, engine next-free rule).
  - This reproduces n=202 and −0.1699/−0.1703, so fixing the entries changes nothing.
  - `out/seq_1m_V45_EXACT_AMB_G1_summary.csv` has the full table.

### RC2 window (report's Sep 5–13), AMB_G1 L50_sl15, BTC/ETH/SOL, `portfolio.single_account` 50x/40%

- **Reconstructing the handoff's window.** I searched hour-granular windows (`work/sep513_fee.py`). The handoff's 59/46%/380 is reproduced only at fee 0.01% (net + 0.0008) with entries in [2026-09-04 07:00Z, 2026-09-13 08:00Z): 59 trades, 45.76% win rate, 47 taken, final 380.15.
- **So the handoff's "−62%" is already at the report's 0.01% fee, but keeps 0.02% slippage.**

| fee / slip | 5m PESS (handoff) | 1m PESS | 1m DET | 1m OPT | 5m OPT |
|---|---|---|---|---|---|
| 0.05 / 0.02 | 175 | 195 | 233 | 238 | 241 |
| 0.01 / 0.02 | **380** | 415 | 495 | 506 | 521 |
| 0.01 / 0 | 728 | 682 | 999 | 999 | 1,163 |
| report | | | | | **2,725 (56 trades, 75%)** |

- **Per-symbol win rate** (59 trades): 45.8% (5m), 47.5% (1m) and 49.2% (1m OPT) at fee 0.01/slip 0.02; 57.6% at fee 0.01/slip 0.
- **Single-account win rate** at the 1m best case: 61.7% over 47 taken trades.
- **Full 1m window** (entries 08-31 → 09-27), single account at real costs: 1,000 → 4.9 (PESS) or 10.3 (OPT).

## 5. 15m strategies on 1m (`work/c_1m_15m.py`, `work/summ_15m.py`, `out/summ_15m.log`)

- **Trades.** These are the September trades (entry ≥ first complete 15m bucket, exit ≤ 1m end − 1 day) of the 15m ALL run, re-simulated on complete 1m→15m buckets (r15) and on 1m bars.
- **max_hold.** 1,000 bars at 15m, 15,000 bars at 1m. There are no TIME or EOD exits.
- **orig vs r15.** The mean |d| is ≤ 0.0006%/trade.

**Four named strategies, per combo (n; d = 1m−15m PESS ± se):**

| strategy | L50_sl15 | L50_sl20 | T_sl1.5_tr1.5 | T_sl1.5_tr2.5 |
|---|---|---|---|---|
| S5 Donchian/MFI | n=13, −0.054 ± 0.052 | n=13, −0.025 ± 0.061 | n=13, 0.000 | n=13, +0.067 ± 0.067 |
| S6 EMA/DMI/ADX | n=63, +0.083 ± 0.026 | n=59, +0.099 ± 0.030 | n=52, +0.020 ± 0.030 | n=43, +0.001 |
| V39_15M | n=218, +0.0005 ± 0.014 | n=211, +0.0085 ± 0.015 | n=193, +0.0025 ± 0.013 | n=141, −0.0115 ± 0.015 |
| OBV_S | n=94, +0.014 ± 0.017 | n=92, −0.005 ± 0.024 | n=83, −0.003 ± 0.019 | n=64, +0.005 ± 0.003 |
| **4 pooled** | n=388, +0.0154 ± 0.0099 | n=375, +0.0183 ± 0.0115 | n=341, +0.0036 ± 0.0099 | n=261, −0.0015 ± 0.0088 |
| **all 30 pooled** | n=5,426, +0.0057 ± 0.0025 | n=5,161, +0.0078 ± 0.0028 | n=4,541, +0.0009 ± 0.0024 | n=3,304, −0.0019 ± 0.0021 |

- **Path bands for 15m L50 (all pooled).**
  - r15 OPT − PESS is +0.112 (sl15) and +0.121 (sl20).
  - m1 OPT − PESS is +0.026 and +0.029.
  - The PF at 15m PESS / 1m PESS / 1m OPT is 0.275 / 0.222 / 0.325 (sl15).
- **Fixed exits.**
  - m1 − r15 is +0.0005 to +0.0103 (F_sl2.0_tp1.5 +0.0103 ± 0.0027; F_sl2.0_tp2.0 +0.0100 ± 0.0028).
  - m1 OPT − PESS is 0, so there are no ambiguous 1m bars.
- **Combos with n≥30** (312 of them):
  - max |d| is 0.099;
  - 89 have |d| > 0.01;
  - 156 have a 95% CI upper bound on |d| above 0.01.
- **Pooled, the condition holds; per combo it does not.** The magnitudes are still irrelevant for the verdict (§6).

## 6. Could resolution change the headline? (`work/required_shift.py`, `out/required_shift.csv`)

This is the smallest uniform per-trade shift δ that would make a pooled combo pass (PF ≥ 1.2 and exp > 0).

- **15m IS, 364 combos with n ≥ 100.**
  - The minimum is 0.133% (N08 F_sl1.5_tp1.5). Median by family: F 0.233, L 0.188 (min 0.140), T 0.242 (min 0.170).
  - S6 F_sl2.0_tp3.0 (the handoff's best) needs 0.176. S6 L50 needs 0.197.
- **5m, 52 combos** (including V39_15M_G1): the minimum is 0.145, and L50 needs at least 0.177.
- **Measured 1m corrections** are 0.006–0.018 pooled, at most 0.099 per combo, and at most about 0.03 more for any sub-minute path. **They cannot flip any verdict.**

## 7. Claim-by-claim verdict on the gap statement

| claim | verdict |
|---|---|
| resampled 1m reproduces delivered 5m results exactly | Almost. 29/3,433 trades differ, from snapshot drift on 09-25..28. Summary effect ≤ 0.001%/trade. |
| AMB_G1 L50_sl15 n=202, d = −0.0004 ± 0.0083, PF 0.22→0.20, WR 42.1→43.6, 48.5% at 0.01% fee | Confirmed exactly. |
| V45_ANY L50_sl15 n=818, −0.1675 → −0.1682 | Confirmed. |
| Fixed SL/TP identical | True for the 5m entries. For 15m entries, 1m is +0.0005..+0.0103 better. |
| Resolution doesn't explain the report | Confirmed, and strengthened. Even the tick-best-case 1m bound with 0.01% fee and 0 slippage gives about −0.1% on RC2, against +172%. |
| "data, fee and symbol set remain" | Fee is **not** a remaining explanation: the handoff's −62% is already at 0.01%. Slippage (0.02%) is. Add post-hoc selection of the candidate on the same window. |
| c_1m.py takes ~1 min | It takes 3.3 s. |
| price_get start+end truncates to 5,000 | Not verified (no Astral call authorised). |

## 8. Proposed handoff edit (not applied: the repo is read-only for this audit)

> **C. 1분봉 청산 검증: 완료(2026-09-29).** BTC/ETH/SOL Astral 1분봉(2026-08-31~09-28, 40,000봉)으로 같은 진입을 다시 청산했다.
> - V4.5 AM+B+G1 L50_sl15: 5분 −0.170% → 1분 −0.170%/거래(차이 −0.0004 ± 0.008).
> - 봉 안 경로를 가장 유리하게 가정해도 −0.149%, 승률 상한은 50.5%다(수수료 0.01%·슬리피지 0이면 57.6%).
> - 15분 30개 전략 합산 차이 +0.001~+0.010%/거래로, 통과에 필요한 최소 +0.13%/거래의 1/10 이하다.
> - 9/5~13 창에서 1분·최선 경로·수수료 0.01%·슬리피지 0으로도 1,000 → 999(보고서 2,725).
> - 봉 해상도는 차이를 설명하지 못한다. 남은 설명은 데이터(현물 vs 선물 Mark), 종목 구성(LTC/BCH), 같은 7.7일로 후보를 고른 사후 선별이다.
> - LTC/BCH 1분봉 2개를 받으면 종목 구성 가설만은 확인할 수 있다.

## 9. Files

- `work/c_1m_orig.py` is the critic's script, copied. `work/c_1m_rerun.py` is identical except for the output name.
- `work/check_1m_data.py`, `work/check_1m_diff_sign.py`: data QA.
- `work/sim_modes.py` (loop), `work/sim_vec.py` (vectorised), `work/validate_sim.py`, `work/validate_vec.py`.
- `work/c_1m_ext.py` + `work/summ_5m.py`: 5m entries, 3 modes × 2 slippage settings.
- `work/seq_1m.py`: sequential re-run plus single account, RC2 window.
- `work/sep513_5m.py`, `work/sep513_search.py`, `work/sep513_fee.py`: reconstruction of the handoff's 59/46%/380.
- `work/c_1m_15m.py` + `work/summ_15m.py`: the 15m extension.
- `work/required_shift.py`: δ needed to pass.
- `results/trades_ALL_15m_gap5_3sym.csv` (216 MB) is regenerable with `cd bt && python3 run.py --window ALL --tf 15m --symbols BTCUSD,ETHUSD,SOLUSD --tag gap5_3sym`.
- All tables are in `out/`.
