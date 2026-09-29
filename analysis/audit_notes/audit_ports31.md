# Audit: FINGRAD 31-set strategy ports (19 strategies, bt/strategies.py:90-368)

Scratch dir: /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/audit_ports31
Code under test: an unmodified copy of /home/user/crypto-bot-research/bt in ./bt. Data is symlinked. `git status` of the project is clean.
Reference libraries: TA-Lib 0.8.1 (wheel) and `ta` 0.11.0 (pure-python sdist, extracted into ./pylib). pandas-ta is not on PyPI here.
The original FINGRAD strategies/*.py evaluate() code is NOT in the package (checked both zips), so "faithful vs bug" questions about strategy logic cannot be settled. Everything below comes from code I ran on the delivered data.

## Bottom line
- **No look-ahead** in any of the 19 ports or their 36 component indicator series (truncation test, 0 mismatches).
- Indicators match TA-Lib, `ta`, or my own references to 1e-10 or better. The exceptions are three convention differences: Aroon uses a 25-bar window (standard is 26), PSAR is Wilder-style rather than TradingView-style, and the Ichimoku cloud is offset 26 (TradingView uses 25). There is also float-tie noise in MFI. None matters for P&L.
- Real logic issues:
  - **N24**: the short side needs ADX <= 25 while the long side needs ADX >= 25. 83% of its signals are shorts. It is the only material asymmetry in a mirror test.
  - **N21**: structurally impossible. RSI never leaves [30.4, 68.4] on any of 3,249 ADX-cross-below-25 bars.
  - **N14**: near-impossible by design. There are 27 co-occurrences where 634 would be expected under independence.
  - **Supertrend multiplier**: 6 strategies hard-code Supertrend(10, **6.0**). This cannot be checked against the original, and it is the parameter with the largest effect.
- **Every "fix" I tried still fails the pre-registered rule**:
  - The best was N01 with ST(10,3): PF 0.898, gross +0.038%/trade, net −0.069%.
  - The only PF > 1 was N21_W12: 30 trades, t = 1.12. Random entries matched to its trade count reach that PF 15% of the time.
  - Running the 19 ports on 5m also gives 0 of 221 combos.
- **The headline conclusion stands** for the 31-set ports: 0 pass, and no port defect hides an edge large enough to cover a round-trip cost of about 0.14%.

## 1. Look-ahead
### 1a. Truncation test (trunc_test.py → out/trunc_strategies.json, out/trunc_indicators.json)
- Setup: BTC 15m, 40,000 bars.
- For each strategy I used 249-289 cut points t: 250 uniform random t, plus up to 20 t where the strategy fires, plus up to 20 t on the bar before a signal.
- I recomputed signals on `df.iloc[:t+1]` and compared **every prefix bar 0..t**, not only bar t, with the full-data signals.
- Result: **0 mismatches at t and 0 prefix mismatches for all 19 strategies.**
  - Signal-true prefix bars compared: S2 482,267; N17 618,510; N18 506,714; N25 250,334; S5 9,679, etc.
  - N14 and N21 have no signals, but their conjunct indicators were compared below.
- Indicator level: 36 series at 50 cut points, exact float equality (NaN-aware), **0 mismatches**. The series were:
  - ST(10,6) direction and line; ST(20,6) direction
  - PSAR value and direction; the 4 Heikin-Ashi columns
  - Aroon up/down; CCI
  - Tenkan, Kijun, span A, span B; Donchian upper/lower
  - MFI, RSI, CMO, W%R, AO
  - +DI, −DI, ADX; KST and its signal; VWMA; Vortex +/−; MACD line and signal
  - ATR, ROC9, EMA20
- Runtime: 3m25s.

### 1b. Static scan
- No `shift(-k)`, `center=True`, `bfill` or backward fill in strategies.py, fg_indicators.py or fg_fast.py.
- `[::-1]` appears only inside trailing windows: fg_indicators.py:305,309 and fg_fast.py:139-140.
- Ichimoku spans use `shift(+displacement)`, i.e. the past (fg_indicators.py:343-344).
- Donchian uses `shift(1)` with `shift_previous=True` (fg_indicators.py:128-130; S5 calls it at strategies.py:104).
- PSAR, Supertrend and Heikin-Ashi recursions use only bars i, i-1 and i-2 (fg_fast.py:28-52, 82-107, 121-122).

### 1c. Limited-history seeding (window_seed.py → out/window_seed.csv)
- Question: a live bot fed only W klines re-seeds the recursive indicators. Do its signals differ from the port's full-history signals?
- Test: 150 random t, last 20 bars of each window.
  - W ≥ 500: 0 mismatches for all 19 strategies.
  - W = 300: N03 2, N25 2 (all others 0).
  - W = 150: S2 68, N23 38, N25 35, N01 27, N02 20 (all others ≤ 6).
- Full-history computation is therefore equivalent unless the live bot used fewer than about 300 bars.

## 2. Indicator correctness (ind_check.py → out/indicator_check_<SYM>.csv, out/ind_check_<SYM>.log)
All figures are after a 1000-bar warm-up (the engine's warmup), BTC 15m. The other four symbols give the same picture unless noted.

| indicator | reference | max abs diff | note |
|---|---|---|---|
| RSI14 | talib.RSI | 7e-14 | flag diffs at 30/70: 0 |
| ATR14 / ATR10 | talib.ATR | 9e-13 | |
| EMA20 / EMA200 | talib.EMA | 6e-11 / 0.063 (values ~78,500) | seed difference, decays |
| MACD line / hist | talib.MACD | 9e-11 / 5e-11 | |
| ROC9 | talib.ROC | 0 | |
| +DI / −DI / ADX14 | talib and ta.ADXIndicator | 3.6e-14 / 3.6e-14 / 8.5e-14 | flag at 25: 0 |
| CCI20 (fg_fast) | talib.CCI | 2e-10 | flag at ±100: 0 |
| MFI14 | talib.MFI | BTC 1.2e-11; ETH 6.2, SOL 10.5, LTC 10.1, BCH 19.8 | float ties, see below |
| Williams %R14 | talib.WILLR | 1.4e-14 | |
| CMO14 | own Chande sum-based | 0 | talib.CMO uses Wilder smoothing (different definition): 6,706 sign flips. FINGRAD = Chande/TradingView |
| Aroon 25 (fg_fast) | talib.AROON | **100** (oscillator sign differs on 1,053/39,000 bars; 932-1,125 across symbols) | FINGRAD window = 25 bars; standard (TA-Lib, TradingView) = length+1 = 26. My own 26-bar version with latest-tie rule equals TA-Lib exactly (0). FINGRAD range is 4..100 |
| Vortex+ / − | ta.VortexIndicator | 0 | |
| KST / signal | ta.KSTIndicator | 4e-14 | |
| VWMA20 | own sum(cv)/sum(v) | 0 | |
| Tenkan, Kijun, span A/B (shift 26) | ta.IchimokuIndicator | 0 | |
| Cloud A−B | TradingView visual offset displacement−1 = 25 | cloud colour differs on 1,094 bars (2.8%; 1,040-1,194 across symbols) | FINGRAD shows a cloud 1 bar older. Not look-ahead |
| Donchian 20 (previous bars) | ta.DonchianChannel.shift(1) | 0 | |
| AO 5/34 | ta.AwesomeOscillator | 0 | |
| Heikin-Ashi (fg_fast) | own | 0 | |
| Supertrend (10,6), (20,6), (10,3) | own TradingView `ta.supertrend` port (Pine RMA ATR) | line 1.5e-11; **direction disagreement 0/39,000 on all 5 symbols** | |
| PSAR (fg_fast) | talib.SAR | psar<close disagrees on 117 bars (ETH 185, SOL 218, LTC 252, BCH 112) of 39,000 | Wilder-style, like TA-Lib |
| PSAR (fg_fast) | own Pine `ta.sar` port (from TradingView reference code) | direction disagrees on 1,330/39,000 (3.4%); others 1,021-1,482 | Pine checks reversal before clamping to low[1]/low[2]; FINGRAD clamps first (Wilder). My Pine port is not validated against real TradingView output |

**MFI tie noise.** On SOL, 96 bars have an exactly zero typical-price change and 35 more have about 1e-15, which is float rounding of a true tie. FINGRAD counts those 35 as positive or negative flow; TA-Lib's C arithmetic rounds them differently. With a 1e-12 tie tolerance, my reference matches TA-Lib to 3.8e-11. Flag differences at 30/70 are at most 18 bars out of 39,000 per symbol. Negligible.

**Tuple order.** All tuple unpackings are in the correct order:
- `dmi_adx` returns (plus, minus, adx); used at strategies.py:120 and :171.
- `adx_dmi` returns (adx, plus, minus); used at :308 and :346.
- The ichimoku, macd, vortex, kst, donchian and supertrend returns are also used in the right order.

## 3. Logic review
### Mirror symmetry test (mirror_test.py → out/mirror_test.csv)
- Transform: P' = K − P with K = 3·max(high); high' = K − low, low' = K − high.
- A direction-symmetric port must satisfy long(mirror) = short(orig) and short(mirror) = long(orig).
- Results, BTC and SOL:
  - **N24: 1,622 (BTC) / 1,607 (SOL) mismatches, i.e. every signal.**
  - N02: 16-38. This is expected, because KST is built from ratio-based ROC and so is not an exact mirror.
  - N18: exactly 28/28 on both symbols. This is the long-priority mask, see below.
  - Everything else: 0 on BTC and ≤ 10 float-tie bars on SOL.

### N24_DMI (strategies.py:345-351)
- The rule is `long = ADX>=25 & +DI crosses above −DI`, `short = ADX<=25 & −DI crosses above +DI`.
- 81% of −DI up-crosses happen with ADX ≤ 25 (BTC 1,320 of 1,622).
- IS signals: 907 long vs 4,347 short (82.7% short).
- The pooled trade long-share is 0.316 in the delivered results.
- This is either a port bug or a quirk carried over from the ChatGPT original; it cannot be verified.
- Counterfactuals (IS, 5 symbols, 13 exits, same engine and rule):

| variant | best exit | trades | best PF | gross/trade | net/trade | mean PF (13 exits) | pass |
|---|---|---|---|---|---|---|---|
| N24 as delivered | F_sl2.0_tp3.0 | 2,436 | 0.819 | −0.019% | −0.126% | 0.646 | 0 |
| symmetric (ADX≥25 both sides) | F_sl2.0_tp3.0 | 1,147 | 0.899 | +0.033% | −0.074% | 0.674 | 0 (1/5 symbols positive) |
| long side only | F_sl2.0_tp3.0 | 813 | 0.788 | −0.060% | −0.167% | 0.621 | 0 |

### N25_DST_CCI (strategies.py:354-368)
- `c_up` (CCI crosses above −100) and `c_down` (CCI crosses below +100) co-occur **0 times** on all 5 symbols. They are mathematically exclusive.
- As a result, N25 is identical (`np.array_equal`, all 5 symbols) to `long = c_up & ~agree_down`, `short = c_down & ~agree_up`. The `~trend_*` / `~range_*` masks are dead code.
- The logic is coherent:
  - When the two Supertrends disagree ("range mode"), it trades both CCI directions.
  - When they agree, it trades only with the trend.
  - About 1,057-1,138 `c_up` events per symbol are blocked by `agree_down`.
- Not a bug.

### N17 / N18 / N22-N25 `short & ~long` and N21 `long & ~short`
- Raw long and short both firing:
  - N17: 0-1 bars per symbol.
  - N18: 28-41 bars per symbol; in IS that is 113 of 6,066 raw shorts (1.9%) dropped. This explains the 28/28 mirror mismatches.
  - N22-N25: 0 bars.
- N21 gives short priority while the others give long priority. That suggests the if/elif order was transcribed deliberately from each original.
- run.py:84-86 applies long priority again. No material effect.

### synchronized() "previous window" leg (strategies.py:49-56) → sticky signals in N17 and N18
- N17: 84% of signal bars immediately follow another signal bar (IS: 15,082 signal bars but only 2,300 episodes). On BTC, 368 long bars fire only through the "prev" leg.
- N18: 67% of signal bars are repeats (11,716 bars, 3,817 episodes).
- In the engine, a repeated signal re-enters immediately after an exit.
- Fresh-only counterfactual: N17 best PF 0.813 → 0.848; N18 0.751 → 0.747. 0 pass.
- `recent()` matches the original helper `fg.occurred_recently` (fg_indicators.py:233-237: the last `bars` bars including the current one).

### Other observations
- N09 uses an "Alligator" of SMA(close) 5/8/13 without SMMA, median price or displacement (strategies.py:239). A standard Williams Alligator (SMMA(hl2) 13/8/5 shifted 8/5/3 into the past) gives PF 0.822 vs 0.818.
- The Ichimoku family uses cloud colour (span A > B), not price-vs-cloud. That is a design choice.
- S5 mixes an "MFI crosses up 30" event with a Donchian breakout. That is a design choice; 324 IS signals.

## 4. Why N14 and N21 produce zero signals (zero_sig.py → out/zero_signal_decomposition.csv)
Counts are over bars [1000, 40000) on 5 symbols (195,000 bar-evaluations).

### N14_ICHI_RSI (strategies.py:184-215)
- **Rule.** A long needs:
  - RSI(14) < 30 on the signal bar,
  - a Tenkan/Kijun up-cross within the last 3 bars,
  - an RSI "hook up" within 3 bars,
  - a green cloud.
- **Base rates.** There are 5,144 TK up-crosses and 8,018 bars with RSI < 30.
- **Co-occurrence.** A recent TK up-cross together with RSI < 30 happens on only **27 bars**. Under independence 634 would be expected, so the pair is suppressed 23-fold.
- **Why they rarely coincide.** Both conditions are functions of the same recent price path. A TK up-cross means the 9-bar midrange is above the 26-bar midrange, which follows a rise; RSI < 30 follows a fall.
- **RSI just after a TK up-cross.**
  - The lowest RSI in the 3 bars starting at a TK up-cross is 22.3-27.4 per symbol.
  - Its 1st percentile is 32-35.
- **Full rule.**
  - 0 signals in IS.
  - 2 signals over the full 14 months, both OOS: ETH long 2026-09-04 12:45 UTC and LTC short 2026-09-13 05:30 UTC. The handoff's "0 signals in 14 months" is therefore slightly inaccurate; it is 0 in the IS window.
- **Attempted fix.** A variant like N08 (RSI crosses 30, state RSI > 30) gives 1 IS signal. **Near-impossible by design, not a typo.**

### N21_ST_RSI_ADX (strategies.py:304-314)
- Needs a **same-bar** triple conjunction: ADX crosses below 25 (3,249 events), an RSI hook in the extreme zone (1,930 up / 1,646 down), and the ST(10,6) direction.
- At all 3,249 ADX-cross-down bars, RSI lies in **[30.4, 68.4]** (p5 40.6-42.4, p95 58.3-60.3). Co-occurrence with RSI < 30 or > 70 is 0.
- Even under independence the expected count is only 1.4 long + 2.1 short.
- Mechanism: ADX falling through 25 needs balanced directional movement (DX low), while RSI < 30 needs a strong one-directional close series. Both are Wilder-14 smoothed, so they are mutually exclusive in practice. **Structurally impossible as coded.**
- Relaxations (IS): windows of 3 / 6 / 12 bars give 0 / 7 / 106 signals.
  - W12 → 30 trades, best-of-13 PF 1.549 (F_sl2.0_tp3.0, mean net +0.289%, t = 1.12). The other 12 exits range 0.21-1.34.
  - Placebo: random entries matched to W12's episode count per symbol (median 29 trades), 200 draws. Best-of-13 PF median 1.013, p90 1.77; **15% of draws reach ≥ 1.549**, so this is noise.
  - An "ADX < 25 state" variant gives 25 signals, PF 0.907.
  - No relaxation reaches the 100-trade minimum.
- Consequence: "28 strategies" really means 26 testable ones.

## 5. Supertrend multiplier 6.0 (strategies.py:91, 148, 158, 305, 329, 355-356)
- Six ports hard-code ST(10, 6.0), and ST(20, 6.0) for N25's slow line. The FINGRAD library default is 3.0 (fg_indicators.py:136; fg_fast.py:14, 62). This cannot be checked against the original.
- The ST(10,6) ports have **significantly negative** 64-bar forward drift in IS (t is inflated by overlapping windows):

| strategy | fwd64 (t), ST 6.0 | fwd64 (t), ST 3.0 | best PF, 6.0 | best PF, 3.0 | gross/trade at best exit, 3.0 |
|---|---|---|---|---|---|
| S2 | −0.107% (−4.1) | +0.040% (1.6) | 0.722 | 0.769 | −0.069% |
| N01 | −0.132% (−3.1) | +0.069% (1.6) | 0.738 | **0.898** | +0.038% |
| N02 | −0.054% (−1.1) | +0.112% (2.2) | 0.745 | 0.811 | +0.013% |
| N23 | −0.133% (−5.4) | +0.014% (0.6) | 0.746 | 0.823 | −0.027% |
| N25 | −0.121% (−3.5) | +0.004% (0.1) | 0.739 | 0.765 | −0.060% |

- Pass count with ST 3.0: **0**. This is the largest single sensitivity in the port, and it still cannot close the gap to about 0.14% round-trip cost.

## 6. Other convention variants (variants.py → out/variants_all.csv, out/variants_extra.csv)
Best PF by variant, IS, pooled over 5 symbols, all 0 pass:

| strategy | as delivered | variant |
|---|---|---|
| N09 | 0.818 | standard Aroon26: 0.774; Williams Alligator: 0.822 |
| N10 | 0.790 | TA-Lib SAR: 0.791; Pine SAR: 0.791 |
| N22 | 0.812 | TA-Lib SAR: 0.811; Pine SAR: 0.810 |
| N07 | 0.778 | Ichimoku offset 25: 0.772 |
| N08 | 0.862 | Ichimoku offset 25: 0.843 |
| N12 | 0.821 | Ichimoku offset 25: 0.794 |

Harness check: running the delivered code through my variant harness reproduces the delivered pooled numbers exactly (N24 2,436 trades / PF 0.819; S2 4,322 / 0.722; N09 1,449 / 0.818).

## 7. Signal frequency (freq.py → out/signal_frequency.csv)
- The IS window after warm-up covers 1,316.1 symbol-days.
- Signals per symbol-day:
  - N03 0.12, S5 0.25, N08 0.18, S6 0.86, N07 1.15, N12 1.28, N09 1.37
  - N01 2.9, N02 2.5, N10 3.2, N24 4.0, N25 4.4
  - N22 7.1, S2 8.5, N18 8.9 (2.9 episodes), N23 9.4, N17 11.5 (1.75 episodes)
- Trades per symbol-day at L50_sl20: 0.12-7.8. The FINGRAD live audit ran 2,728 trades / 124 ledgers / 7 days = 3.14 per ledger-day. The port's frequencies are plausible.

## 8. Supplementary: the 19 ports on 5m (BTC/ETH/SOL, 4.6 months)
- Ran the unchanged run.py with `--tf 5m --strategies <19 ports>` → out/pooled_ALL_5m_ports19.csv.
- 17 × 13 = 221 combos, **0 pass**. Best is S6 at PF 0.808 (676 trades). The highest gross expectancy in any combo is +0.015%/trade; mean PF is 0.485.
- N14 and N21 are also 0 on 5m.
- The timeframe choice does not hide an edge.

## 9. Side observation on forward drift (delivered forward_IS_all5.csv, recomputed)
- The handoff mentions only 4h (fwd16) drift, where S5 is +0.103%.
- At 64 bars (16h), several 31-set ports show drift similar in size to V4.5's "only faint signal":
  - N08 +0.230% (244 signals, t 1.25)
  - N03 +0.208% (161)
  - S6 +0.136%
  - N09 +0.120% (t 1.9)
  - N17 +0.119% (t 5.1, inflated by 84% repeats; fresh-only +0.101%, t 1.6)
- Adjusting for market drift barely changes these (N17 +0.125%, N09 +0.116%).
- Considering multiple testing (17 × 6 horizons), all are at or below cost and not robust. This does not change the conclusion, but V4.5's drift is not unique.

## 10. Issues ranked by potential to hide a real edge
1. **Supertrend multiplier 6.0 in 6 ports** (unverifiable parameter).
   - Effect: best PF rises 0.03-0.16 and fwd64 drift moves from significantly negative to about 0.
   - Bias: makes results look WORSE if the original used 3.0. Conclusion changes: no; best is 0.898.
2. **N24 short-side ADX ≤ 25 asymmetry.**
   - Effect: PF 0.819 → 0.899 with the symmetric rule.
   - Bias: WORSE. Conclusion changes: no.
3. **N21 structurally impossible (same-bar triple).**
   - Status: strategy untestable; the windowed fix PF 1.55 on 30 trades is noise (placebo p ≈ 0.15), and every variant stays under 100 trades.
   - Bias: unclear. Conclusion changes: no.
4. **N14 near-impossible by design.**
   - Status: 0 IS signals; even the corrected RSI-cross version gives 1.
   - Bias: unclear. Conclusion changes: no.
5. **Sticky synchronized() in N17/N18.**
   - Effect: PF +0.035 / −0.004. Conclusion changes: no.
6. **Minor conventions**: Aroon 25-bar window, Wilder vs Pine PSAR, Ichimoku offset 26 vs 25, SMA Alligator.
   - Effect: |ΔPF| ≤ 0.044, mostly negative after the "fix". Conclusion changes: no.
7. **Informational**:
   - MFI float ties (≤ 18 flag bars).
   - N25 dead masks.
   - N18 long priority drops 1.9% of shorts.
   - The handoff says N14 had 0 signals in 14 months; it is 2 (OOS).
   - 64-bar drift of some ports is comparable to V4.5's.

## Scripts
Each script writes to ./out:

| script | purpose |
|---|---|
| common.py | loader |
| trunc_test.py | look-ahead truncation test |
| ind_check.py `<SYM>` | indicator cross-check |
| zero_sig.py | N14/N21 decomposition |
| logic_checks.py | N25/N17/N18/N24 logic checks |
| mirror_test.py | long/short mirror test |
| window_seed.py | limited-history seeding |
| variants.py `[names] [tag]` | counterfactual variants |
| placebo_n21b.py | N21_W12 placebo test |
| freq.py | signal frequency |
| bt/run.py `--tf 5m ...` | 5m run; output in ./results/summary_ALL_5m_ports19.csv (the 150MB trades file was deleted after pooling) |
