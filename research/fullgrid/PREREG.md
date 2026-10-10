# Full-grid custom-value study: pre-registration

(한국어 설명: `DESIGN_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면
`DEVIATIONS.md`에 따로 적습니다.)

Written 2026-10-10, before any grid result. Owners' request: as many custom values per strategy as possible, quickly, for
the rule bot's 36 strategies and the 44 DeepSeek definitions ("딥시크 매매법들도 같이"), with the take-profit and
stop-loss rules as well ("익절 손절 기준도 같이", "최대한 많은 경우"). The design (DESIGN_KO.md: range, criteria) was
shown to the owners on 2026-10-10 and they went ahead, adding DeepSeek and the exit rules and allowing a large server.

## 1. Question
For each strategy x timeframe ("cell"), is there a combination of the strategy's own numbers and an exit rule (stop
width, take-profit) that beats the current numbers with the current exit on data the choice never saw, by more than
luck, under the rule bot's exact v4 trading rules otherwise?

## 2. Data (`data.py`)
Binance USD-M public archive (data.binance.vision): 1m klines, 1m mark-price klines, funding rates, monthly files
2020-01 .. 2026-09 (checksummed), daily files for days the monthly klines lack (gap fill). Coins: BTCUSDT, ETHUSDT,
SOLUSDT, DOGEUSDT, LTCUSDT, BCHUSDT (config.V3_SYMBOLS). Zero-volume minutes dropped; a missing mark minute takes the
last-price bar; funding on the minute of its calc time. Chart bars (15m, 30m, 1h, 4h) are UTC bins of the 1m bars
(`run.build_frame`).

## 3. Strategies
- **Core 36**: `research/entry_study/param_defs/<NAME>.py` (pinned by `research/entry_study/DEFS_BC.sha256`,
  file sha256 185dbcf8…), defaults = the live locked signals. Timeframes 15m, 30m, 1h, 4h.
- **DeepSeek 44**: `research/fullgrid/ds_defs.py`, defaults = `research/deepseek200/lib_c.py` (sha256 3210c602…)
  `entries()` bar for bar (tests/test_fullgrid_ds_defs.py; also checked on all 6 coins x 4 timeframes, full series).
  Timeframes as lib_c (the five ET-session definitions: 15m, 30m, 1h).

## 4. Grid (`grid.py`)
Every number of a definition takes 9 values (fewer after rounding / clipping): lengths x (1/3, 1/2, 2/3, 0.8, 1, 1.25,
1.5, 2, 3) rounded half up, at least 2, clipped to a declared upper bound; multipliers and absolute thresholds the same
factors, values outside the declared bounds dropped; thresholds with a neutral point: neutral + f x (default - neutral),
f in (0.25, 0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 2), clipped, never at the neutral point. Every combination (product),
minus combinations that break a rule's own order (`grid.valid`). Core: 779,328 combinations over the 4 timeframes
(`RANGES_KO.md`); DeepSeek: 236,235. Total 1,015,563 (the default of every cell included). Each combination is
tried with all 84 exit variants of section 5: 85,307,292 (numbers, exit) pairs.

## 5. Trades (`kernel.py`, `run.py`)
- Rules = `paperbot.engine.PaperEngine` with `config.v3_settings()` (the live v4 rules), on 1m bars, exactly as
  `paperbot/paramshadow.py` replays the live account (tests/test_fullgrid_kernel.py requires identical trades for every
  exit variant): fill at the open of the minute after the signal bar's close (+0.02% slippage), taker 0.05% both ways,
  funding, isolated-margin liquidation on mark price, quality_v1 sizing (best: 50x/50%, 40x/40%, then 30x/30%, 20x/20%;
  normal: 30x/30%, 20x/20%; stop inside liquidation by max(0.2%, 1 ATR); stop loss <= 15% of the wallet).
- Exit variants (`kernel.EXITS`, 84 = 6 stops x 14 take-profit rules `kernel.TP_RULES`): stop k x ATR14 of the signal
  bar from the entry reference price, k in (1, 1.5, 2, 2.5, 3, 4) (sizing uses that stop); take-profit rule:
  the stepped lock starting at 10% net ROE (12% -> 10%, +5% steps; the live rule), at 5% (7% -> 5%) or at 20%
  (22% -> 20%); a fixed take-profit at net ROE 10%, 20%, 30% or 50% (the engine's own tp_mode "fixed",
  policy.tp_from_roe on the fill and the leverage); a fixed take-profit at 1R, 1.5R, 2R or 3R (R = k x ATR14 from the
  entry reference price); the 10% lock plus a 2R take-profit; or the 10% lock plus a structure take-profit: the
  nearest confirmed swing high above (long) / swing low below (short) the signal bar's close among the swings of the
  last 300 bars, swings of 3 or 10 bars on each side (`kernel.structure_levels`, known k bars after the swing), used
  only when it lies beyond the fill price (entry reference price plus slippage). A take-profit is a limit: it fills only when price
  trades through it, at it or a better gapped open, maker fee 0.02%; a minute touching both stop and take-profit is a
  stop. The live exit is k = 2 with the 10% lock (variant 0). Owners 2026-10-10: "어떤 매매법은 짧게 10%씩 먹고 나오면
  좋은 매매법도 있을꺼고 어떤 매매법은 길게 수익 먹으면 좋은 매매법도 있을꺼고 손절 방식도 마찬가지", "구조 익절로도
  해보고".
- Leverage group: core strategies "best" when the signal bar's strength (`research/entry_study/strength_defs`, default
  numbers) scores >= 4 against `paperbot/quality_edges.json` (levrule.quality_group, as live); DeepSeek always "normal"
  (as live, config "ds200").
- Brackets and order-size rules: `research/fullgrid/exchange.json` (Binance leverageBracket + exchangeInfo, fetched once
  on the paper bot server before the run; its date is in the file).
- Unit: one trade = one signal alone on a $5,000 wallet; result = wallet change / $5,000 ("per-trade P&L"). A signal
  the sizing rejects, or still open at the end of the data, is not a trade. Every signal counts (no position limit) in
  sections 6.1-6.3.

## 6. Periods and pass rule
Periods by the signal bar's close (UTC): **select** 2021-01-01 .. 2024-01-01, **test** 2024-01-01 .. 2026-10-01,
**extra** 2020-01-01 .. 2021-01-01. The first 300 chart bars of each coin's series are warm-up only. Trades are pooled
over the six coins.

6.1 **Select** (select period only), per cell, over (numbers, exit) pairs with >= 150 trades. Plateau score = median
of the pair's mean per-trade P&L and its neighbours' (one number one step up or down with the same exit; or the next
narrower / wider stop with the same take-profit rule and numbers; a neighbour with fewer than 150 trades counts as 0;
a neighbour outside the grid does not count). The default (live numbers, live exit) has its plateau computed the same
way (0 if it has < 150 trades). Picks: the top 3 pairs by plateau among those with plateau > 0 and plateau > the
default's (ties: higher select mean, then grid order, then exit order). At most 3 per cell.

6.2 **Test**: >= 100 test trades; mean > 0; mean > the default's test mean (live numbers, live exit; same cell, same
period); one-sided
week-block bootstrap p (all coins' trades of a UTC week together, 2,000 resamples, p = (1 + resamples with mean <= 0) /
2,001, seed = sha256 of the cell, row, exit and period) passing Benjamini-Hochberg at FDR 10% over ALL picks (core and DeepSeek
one family; a pick with < 100 test trades stays in the family with p = 1 and cannot pass).

6.3 **Extra**: >= 20 trades in 2020 and mean > 0.

6.4 A pick passing 6.2 and 6.3 is a **candidate**. For each candidate (with its exit) and its cell's default (live
exit): the real account
(`kernel.account`: $5,000, one position at a time over the six coins, coin priority BTC, ETH, SOL, DOGE, LTC, BCH,
compounding, bust below $10) over 2021-01 .. 2026-09 and over the test period alone; reported, not a pass condition.

6.5 No candidate -> reported as "none". The criteria are not relaxed afterwards. No other cut of the results (per coin,
per side, other periods) is a candidate.

## 7. After
Candidates are never used for real money directly. They go to the live custom-value shadow and the demo lab; only
results after the choice (>= 28 days and >= 20 trades) count. The 10/19 $100 trial does not use them. A change of the
live rule bot's numbers needs the owners' decision after the 30-day verdict, as a new account.

## 8. Not in this study
Per-coin choices, leverage rule variants, exits other than the 84 of section 5, and market-regime-specific numbers
(weekend / weekday, trend / range): a later study on this one's candidates. The DeepSeek money figures follow the
owners' D11 (counts only) in the report until they decide otherwise (`report.DS_MONEY`).

## 9. Reproducibility
The runner prints the git commit; `PREREG.sha256` pins this file, `grid.py`, `ds_defs.py`, `kernel.py`, `run.py`.

## 10. Before this file was fixed
Timing runs on BTC 15m with the example bracket table (not exchange.json): S2_ST_ROC and N04_ST_KLINGER first chunks
(only S2_ST_ROC's select-period min / max / default mean were printed: -1.26% / -0.88% / -0.99% per trade), and a
benchmark of the first 150 combinations of every core cell and every DeepSeek 15m cell on BTC (statistics written to a
scratch folder, not read). No test- or extra-period number was looked at. The exit variants (section 5) were added at the owners' request the
same day, before any run of the full grid.
