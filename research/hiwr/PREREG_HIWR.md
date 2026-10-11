# Track 2, high win rate under an account drawdown cap (고승률 · 낙폭 한도): pre-registration

(한국어 설명: `README_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면
`DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (about 15:50 UTC). Not pinned.** No code for this study exists in the repository
yet. The only computations behind this draft are the practice-period feasibility runs of section 22. They used signals
whose bar closed before 2024-01-01 only. Nothing from 2024-01-01 on was read, computed or printed, and 2020 was not
used. Section 2 is the main session's reading of the owners' words. **It is an assumption the owners can correct**,
and so is every default of section 21. The open questions of section 21 are closed (by the owners, or by the default in
brackets) before the pin.

Pinning means `research/hiwr/PREREG_HIWR.sha256` over this file, the study's code and the files of section 17.3. The
code refuses `select` without a matching pin. It refuses the confirm stage until the picks' hash is appended to the pin
(section 10.6). After the pin nothing here changes; a change goes to `research/hiwr/DEVIATIONS.md` with its reason and
date.

**Owners' brief** (Korean, 2026-10-11, about 23:30 KST = 14:30 UTC). This is "track 2", run next to the trend hunt
(track 1, `research/hunt`), analysed separately and shown side by side, never merged:

> 15분봉은 낙폭 15% 이하로 잡아주고 30분봉은 낙폭 20%로 잡아주고 1시간봉은 30% 그리고 승률은 70% 이상 으로 잡을수
> 있게 5년치 백테스트를 돌리면서 보조지표 커스텀 값이나 진입 조건을 찾아줘 그리고 주말장 제외

> 2번은 수익률을 또 정해야 하니까 30배 9%에서12% 40배 12%에서15% 50배 15%에서18% 이렇게 기준 잡아서 과거 백테스트
> 해줄래?

They added at 14:20 UTC: "4시간봉도 주말 제외해주고".

Their overall goal is $1,000 → x5 .. x100 in a month. The agreed process for every study of the program:
1. The practice period 2021-2023 is free to use.
2. The confirm period 2024-01 .. 2026-09 is looked at once per version.
3. Then a paper bot.
4. Then small live money, by the owners' decision only.

## 1. Question

Take each strategy and timeframe (15m, 30m, 1h, 4h). Is there one setting, with weekend entries skipped, that passes
on data its choice never saw (the confirm period)? A setting is:
* the strategy's own indicator numbers;
* a take-profit inside the owners' ROE range at 30x, 40x or 50x;
* a stop wider than the take-profit;
* a taker or a maker take-profit order.

It passes when it does all four of these:
* (a) wins at least 70% of its trades after all costs;
* (b) keeps a $1,000 compounding account's maximum drawdown within the timeframe's cap, at a margin size fixed on the
  practice period;
* (c) has a positive mean net result per trade, also at double costs;
* (d) does better than the same exits fed with coin-flip sides and with random entry times.

Condition (d) is needed because (a) alone is no evidence. With a +0.30-0.40% take-profit and a wider stop, random
entries already win 60-80% of the time (section 15).

## 2. The owners' targets as read here (open for correction, section 21)

### 2.1 Take-profit

"30배 9%에서 12%" is read as a per-trade take-profit at an ROE of 9-12% on the isolated margin of a 30x position.
Likewise 40x is 12-15% and 50x is 15-18%. ROE = price move from the fill x leverage, **before fees**. That is the ROE
Binance shows on its position screen. In price terms:

| tier | owners' ROE range | TP steps used (low / mid / high) | price move from the fill |
|---|---|---|---|
| 30x | 9-12% | 9 / 10.5 / 12% | +0.30 / +0.35 / +0.40% |
| 40x | 12-15% | 12 / 13.5 / 15% | +0.30 / +0.3375 / +0.375% |
| 50x | 15-18% | 15 / 16.5 / 18% | +0.30 / +0.33 / +0.36% |

All three tiers ask for the same move of about 0.30-0.40% in price. Leverage does not change what happens to a trade
in price. For a fixed notional, the tier changes only three things:
* how far away the liquidation price is, and so which stops fit (7.4);
* the margin locked, and with it the most an isolated position can lose;
* the bracket tier.

So the tier is a margin label on one backtest plus a stop-room limit. Section 8.4 reports the margin % it implies.

**The "net" reading is not used unless the owners choose it (Q1).** It reads the ROE as after the 0.14% round-trip
cost, the way the rule bot's own `default_tp_roe` and the full grid's ROE take-profits are defined. The price move is
then ROE / L + 0.14%, i.e. +0.44 .. +0.54%. If the owners choose it before the pin, it replaces the price column above;
nothing else changes.

### 2.2 Drawdown

"낙폭" is read as the **account's** maximum drawdown (peak to trough of equity, 8.3), not the loss of one trade. The
caps:

| timeframe | 15m | 30m | 1h | 4h |
|---|---|---|---|---|
| cap | 15% | 20% | 30% | 30% |

The owners named no 4h cap; 30%, the same as 1h, is a default (Q2). The cap is met by choosing the margin per trade on
the practice period (8.4). It is not met by changing the strategy.

### 2.3 Win rate

A win is a trade whose net result after fees, slippage and funding is above 0. "70% 이상" means at least 70.0% of
trades.

### 2.4 Weekend

"주말장 제외" means no new entry when the signal bar closes at or after Saturday 00:00 UTC and before Monday 00:00 UTC.
In Korea that is Saturday 09:00 to Monday 09:00 KST. This holds on all four timeframes, 4h included (the owners at
14:20 UTC).
* A position opened before Saturday 00:00 UTC keeps its exits over the weekend (Q9).
* The with-weekend result is computed beside it, as a comparison only (R1).
* The clock is UTC, not KST (Q10). The paper bot's own weekday labels (`paperbot.breakdown`,
  `research/fullgrid/regimes.py`) use KST and are not used here.

### 2.5 "5년치"

"5 years" is the practice period plus the confirm period:
* practice period (SEL): 2021-01 .. 2023-12, 36 months;
* confirm period (TEST): 2024-01 .. 2026-09, 33 months;
* 2020: an extra read only (section 9).

### 2.6 "보조지표 커스텀 값이나 진입 조건"

* **Custom indicator numbers** are the full grid's values for every number of every strategy (6.2).
* **Entry conditions** are the owners' weekend rule and nothing else as a rule. The loss autopsy
  (`research/autopsy/LOSS_AUTOPSY.md` §2-4) found every other filter it tested on SEL useless or too small (6.4).

## 3. Data

* **Source.** The Binance USD-M public archive (data.binance.vision), every file checked against its `.CHECKSUM`. It
  holds monthly 1m klines, 1m markPriceKlines and fundingRate files for the 30 coins of section 4, from each coin's
  first archived month (2020-01 at the earliest). Days a monthly kline file lacks come from the daily files
  (checksummed; absent minutes only).
* **Build.** A copy of `research/fullgrid/data.py` with the symbol list taken from `research/hunt/universe30.json` and
  month bounds as arguments. The layout is the same:
  - int64 open time; float64 OHLC, quote volume and mark OHLC;
  - funding on its calc minute;
  - zero-volume minutes dropped;
  - a missing mark minute takes the last-price bar.
* **Two downloads, by construction.**
  - The **practice kit** downloads 2020-01 .. 2023-12 only.
  - The 2024-01 .. 2026-09 files are fetched by the separate **confirm stage**. It refuses to run until `picks.json`
    is hashed into the pin (10.6).
* **Identity.** Per coin and per array, a content sha256 computed by the hunt's method (`research/hunt/PREREG_HUNT.md`
  §2). They go to `research/hiwr/data_manifest_sel.json` (pinned) and later to `data_manifest_test.json` (appended at
  the confirm stage). Every stage recomputes the hashes of what it loads and stops on any difference.
* **Cross-checks before the pin.** Each one stops the pin when it fails.
  - (i) The six old coins' 1m bars before 2024-01-01 must equal the full grid's archive (`fg1m/1m/<SYM>.npz`) on every
    minute both have. They come from the same source. A mismatch beyond 1e-9 relative on more than 0.01% of minutes
    stops the pin.
  - (ii) All 30 coins' 1m bars, resampled to 5m before 2024-01-01, must match the hunt's pinned 5m data
    (`research/hunt/data_manifest.json`) within the hunt's tolerance (OHLC 1e-6 relative, volume 0.1%) on at least
    99.9% of the 5m bars. Where the hunt's 5m files are not on the machine, three random months per coin are rebuilt
    from the archive's 5m files and compared instead (seeded as in section 11).
* **Mark price.** Liquidation is checked on mark price (the full grid's kernel convention). Stops trigger on last
  price.

## 4. Universe and brackets

* **Coins.** The hunt's 30 coins (`research/hunt/universe30.json`; its rule and its biases are in `PREREG_HUNT.md` §3).
  They are the 2023 quote-volume top 30 among USD-M USDT perpetuals with history back to 2021-01. The list is static,
  and coin priority follows its order.
* **Spans.**
  - SAND starts 2021-01-25.
  - TOMO ends 2023-11-14, inside SEL.
  - Seven more end inside TEST: WAVES 2024-06, MATIC 2024-09, BLZ 2024-12, FTM 2025-01, EOS 2025-05, MKR 2025-09,
    STORJ 2026-08.
  - A coin's tradable span ends at its last bar with volume (7.6).
* **Brackets.** `research/hunt/exchange30.json`, a 2026-10-11 snapshot applied to 2021-2026 as an assumption. 22 coins
  have a real table.
* **The 8 coins that stopped trading.** Their table cannot be fetched any more. The hunt's 20x fallback table would
  shut them out at 30-50x and leave only coins still listed in 2026, which is survivorship in both periods. **They use a
  proxy table instead (Q3): the one SANDUSDT and COMPUSDT share in exchange30.json.** Its tiers start 75x up to $5,000
  notional (mmr 1.0%), then 50x up to $10,000 (1.5%), then 25x up to $50,000 (2.0%), and so on. Each proxy coin is
  labelled in every output. Minimum notional and quantity steps come from the exchange30.json specs; proxy coins use
  SANDUSDT's.
* **Notional cap per tier.** At tier L, a position's notional can reach the largest notionalCap among the tiers whose
  initialLeverage >= L: BTC and ETH $12M, the small alts $10,000, TRB $5,000. A larger planned notional is cut to that
  cap (counted).
* **Liquidation distance from the fill** (long, first tier, isolated, one-way):

| coins | first-tier mmr | 30x | 40x | 50x |
|---|---|---|---|---|
| BTC, ETH | 0.4% | 2.95% | 2.11% | 1.61% |
| DOGE | 0.65% | 2.70% | 1.86% | 1.36% |
| the 1.0%-mmr alts and the proxy coins | 1.0% | 2.36% | 1.52% | 1.01% |
| TRB (max 50x) | 1.5% | 1.86% | 1.02% | 0.51% |

  At 50x little stop room is left on most alts (7.4).
* **Groups.** Old six = BTC ETH SOL DOGE LTC BCH. New 24 = the rest; all eight coins that stopped trading are among
  them.

## 5. Bars and signals

* **Chart bars.** 15m, 30m, 1h and 4h bars are UTC bins of the 1m bars, built by `research/fullgrid/run.build_frame`
  (imported read-only). A signal is known at the signal bar's close, i.e. the end of its bin. The first 300 chart bars
  of each coin warm the indicators up and are never traded (`run.WARMUP_BARS`); indicators use every earlier bar.
* **Strategies.** The full grid's 80 definitions, unchanged and imported read-only:
  - core 36: `research/entry_study/param_defs`, checked against DEFS_BC.sha256 by `run.core_module`;
  - DeepSeek 44: `research/fullgrid/ds_defs.py`; the five ET-session definitions exist on 15m, 30m and 1h only.
* **Cells.** A cell is one strategy on one timeframe: 144 core + 171 DeepSeek = 315.
* **Candidates.** A candidate is a bar on which the definition's long (or short) array is true at the combo's numbers
  (`run.signals`). Every such bar is a candidate, long and short separately; this is the full grid's unit.
* **Weekend rule, all four timeframes.** A candidate whose signal-bar close t falls at or after Saturday 00:00 UTC and
  before Monday 00:00 UTC is dropped and counted as "weekend". Exactly: ((t - 1970-01-05T00:00Z) mod 7 days) >= 5 days.

## 6. Search space

### 6.1 Strategies and timeframes

The 315 cells of section 5.

### 6.2 Numbers

Every number of a definition takes the full grid's values (`research/fullgrid/grid.py`, pinned by its own study,
imported read-only):
* 9 steps from 1/3x to 3x of the default: lengths x (1/3, 1/2, 2/3, 0.8, 1, 1.25, 1.5, 2, 3), rounded and clipped;
* thresholds with a neutral point use f = 0.25 .. 2;
* every valid combination: 779,328 core + 236,235 DeepSeek = **1,015,563 combos**, defaults included.

The smaller 5-step subset is the alternative (Q4).

### 6.3 Exit configs per combo

Each combo is tried with 3 tiers x 3 TP steps (2.1) x 9 stops (7.3) x 2 TP fills (7.2) = 162 exit configs. That makes
about 164.5 million (combo, exit) pairs.

### 6.4 Entry conditions

* **The rule:** the weekend rule (5) only.
* **Not added as rules.** The autopsy's SEL tests found these useless or too small: higher-timeframe alignment,
  session or hour filters, a funding gate, dropping coins, consensus or crowding, anti-chase or lateness, a minimum stop
  distance, a side tilt, a refractory gap, BTC context, pullback-limit entries, a time stop, breakeven, and volatility
  level.
* **G1 (the 장세 gate)** waits for the regime-gate verdict (`research/regimegate`, judged on data to 10-31) and is not
  in v1.
* **The FOMC/NFP 120-minute blackout** (autopsy O2) is not in v1 (Q12).

### 6.5 Leverage tier

30x, 40x and 50x, isolated, one-way, with the house buffer for stop room (7.4).

## 7. One trade

### 7.1 Entry

* Market order at the open of the first 1m bar after the signal-bar close (`kernel._entry_index`).
* Reference price P0 = that open.
* Fill F = P0 x (1 + 0.0002) for a long, P0 x (1 - 0.0002) for a short.
* Taker fee 0.05% of the fill notional.

### 7.2 Take-profit

The level is T = F x (1 + t) for a long (F x (1 - t) for a short), where t is the TP step's price move. It is placed
at the fill.

* **Taker TP** (a take-profit-market order):
  - It triggers when the 1m high reaches T (low for a short).
  - It fills at T x (1 - 0.0002) for a long; when a minute opens beyond T, at that open x (1 - 0.0002).
  - Taker fee 0.05%. Round trip with the entry: 0.14% of notional.
* **Maker TP** (a resting reduce-only, post-only limit):
  - It fills only when price trades **through** T within the minute: the 1m high must be above T (below for a short),
    strictly.
  - It fills at T, or at a better open when a minute opens beyond T.
  - Maker fee 0.02%, no slippage. Round trip 0.09%.
  - This is the full grid kernel's limit rule (`research/fullgrid/PREREG.md` §5).
  - **It is optimistic.** Queue position is not modelled, and a pierce of one tick may not fill a resting order. R7
    reads pierce requirements of 0.01% and 0.02% and the share of maker exits whose pierce was under 0.02%. Live, the
    order must be post-only (GTX).
* Either TP can fill in the entry minute, on that minute's high or low after its open, as in the kernel.

### 7.3 Stop

* A stop-market order on last price, like the live executor's algo stop.
* Level S = P0 - D for a long (P0 + D for a short). D comes from the stop grid, two families:
  - ATR: **k x ATR14 of the signal bar, k in {1, 1.5, 2, 3}**;
  - price: **p x P0, p in {0.60, 0.75, 1.00, 1.25, 1.50}%**.
* ATR14 = `_vendor_fg().atr(frame, 14)`, as in the full grid.
* It fills at S x (1 - 0.0002) for a long when the 1m low touches S, or at a gapped open x (1 - 0.0002). Taker fee.
* **The stop must be wider than the take-profit.** A candidate whose stop distance from the fill, |F - S| / F, is not
  greater than t is skipped and counted as "stop inside TP". Only ATR stops on calm bars can hit this.

### 7.4 Stop room at the tier (isolated liquidation)

* Lq is the liquidation price at L for the planned notional, by Binance's isolated one-way formula with the mmr and cum
  of the tier that holds the notional (`kernel._liq`). It is checked on mark price.
* **House buffer.** At tier L a candidate is taken only when the stop lies inside liquidation by at least
  max(0.2% of F, 1 x ATR14): |F - S| + max(0.002 F, ATR14) <= |F - Lq|. This is the rule bot's own quality_v1
  condition.
* Otherwise the candidate is skipped and counted as "no stop room at L".
* The loose buffer (0.2% only) is a read (R3).
* In the trade list (8.1) the planned notional is that of the first tier. In the account (8.2) it is the account's
  notional.

### 7.5 Order of events inside one minute

Long shown; a short is the mirror. This is the order of the prototype and of the kernel.
1. The entry minute has no open checks.
2. From the next minute on, the open comes first:
   * mark open beyond Lq: liquidation;
   * open beyond S: stop at the open;
   * open beyond T: TP at the open.
3. Then, inside the minute:
   * stop touched: stop;
   * mark through Lq: liquidation;
   * TP touched (taker) or traded through (maker): TP.

So a minute that touches both S and T counts as a stop. A liquidation loses the whole isolated margin: the net result
is minus the margin minus the entry fee.

### 7.6 Funding, coin end, period end

* **Funding.** Every funding event while the position is open is charged on mark open x quantity at the calc minute
  (the kernel), and paid from or to the wallet. A long pays a positive rate.
* **Coin end.** A position still open at the coin's last bar with volume closes at that bar's close as a stop-market
  order (slippage plus taker fee).
* **Period end** (SEL: 2024-01-01 00:00 UTC; TEST: 2026-10-01 00:00 UTC).
  - In the trade list, a candidate not resolved before the period end is dropped and counted as "open at end".
  - The account marks such a position at the last 1m close before the period end and flags it.
  - No price at or after the period end is read.

### 7.7 Costs and the net result

* **Fees and slippage.**
  - Taker 0.05% on every market fill, plus 0.02% slippage against every market fill.
  - Maker 0.02% on maker TP fills.
  - Funding as charged.
* **Round trip:** 0.14% with a taker TP or a stop; 0.09% with a maker TP.
* **Cost x2:** taker 0.10%, slippage 0.04%, maker 0.04%; funding unchanged.
* **Net result r.** Per notional: the price return from F to the exit price, minus fees and funding per notional (the
  prototype's `trade_r`).
* **1R** is the loss at the stop level, costs included.

## 8. Two units: the trade list and the account

### 8.1 Trade list

The trade list is the unit for win rate, mean, cost x2, controls and p-values.
* It holds every candidate of a pair that sections 5 and 7 take, each traded alone.
* It is pooled over coins and sides, with no position limit (the full grid's unit).
* Win rate = the share of trades with r > 0. Mean = the mean of r, in % of notional.
* The mean is also reported in R (r / 1R) and in % of the wallet at f* (f* x r).

### 8.2 Account

The account is the unit for drawdown, size and monthly returns.
* It starts with $1,000 at the period start and compounds. Margin is isolated.
* **One position at a time over all coins.** Candidates are taken in time order of their fill minute; ties go by coin
  order (section 4), long before short. A candidate whose fill minute is not after the open position's exit minute is
  dropped (counted "busy", never queued).
* **Size.** The fixed fraction f is the size. Notional N = f x equity at the decision; this equals the wallet, because
  the account is flat at every decision.
  - Margin = N / L, so the margin % of the wallet is f / L.
  - N is cut to the tier's notional cap (section 4). A trade below the coin's minimum notional is skipped (counted).
  - The stop-room check (7.4) is redone at the tier that holds N.
* Quantity steps are ignored here; R12 reads them at live sizes.

### 8.3 Drawdown

* **Equity.** E = wallet + open P&L. While a position is open it is marked twice on every 1m bar: at the bar's close
  (E_close) and at the bar's adverse last-price extreme (E_adverse, the low for a long). Both are less the fee of a
  market exit at that price.
* **Peak(t)** = the maximum of the starting wallet, every E_close up to t, and every wallet value after a close.
* **Max DD** = the maximum over t of 1 - E_adverse(t) / Peak(t). The peak includes open-trade highs, because a trade
  can rise to just under T and then fall to its stop.
* The realized-only DD (closed trades only) is reported beside it.
* **Bust** = equity below 10% of the start. The account stops there.

### 8.4 Size f*, fixed on SEL

For a pair at its tier L, f* is the largest f that meets all three of these:
* (i) the SEL max DD (8.3) is at most the cap of its timeframe;
* (ii) the worst single SEL trade loses at most 15% of the equity before it. This is the paper rules' per-trade cap,
  `max_loss_frac` in paperbot `risk.py`;
* (iii) f <= L^2 / 100, i.e. the margin is at most L% of the wallet. That is the rule bot's own margin: f is at most 9,
  16 and 25 at 30x, 40x and 50x.

**Method.**
* The realized-only DD gives an upper bound on f*, because the realized DD is never larger than the mark-to-market DD.
  It only brackets the search.
* f* itself is found by bisection on the exact 1m mark-to-market DD, 40 steps, rounded down to 0.01.

**Reported:** f*, the margin % of the wallet (f* / L), and the notional as a multiple of the wallet, at the pick's tier.
R2 gives the same at the other tiers whose ROE range contains the TP price. **f* is fixed on SEL and never re-fitted on
TEST.**

### 8.5 Monthly return

* M_m = account equity at the end of UTC month m / equity at its start.
* Reported: mean monthly ln M, geometric monthly % = exp(mean ln M) - 1, median M, worst month.

## 9. Periods and data access

Periods are set by the signal-bar close, in UTC.

| period | span | months | role |
|---|---|---|---|
| **SEL** | 2021-01-01 .. 2024-01-01 | 36 | practice: search and choice |
| **TEST** | 2024-01-01 .. 2026-10-01 | 33 | the confirm period: one look for this version |
| **EXTRA** | 2020-01-01 .. 2021-01-01 | about 12 | a read only, computed in the test step after the picks are hashed |

**How `select` touches the data:**
* It loads the practice kit only.
* It cuts every 1m array at 2024-01-01 00:00 UTC, after the content check and before any other use.
* It builds the chart frames from the cut arrays.
* It drops bars closing before 2021-01-01 from every statistic; they are warm-up only.

`select.json` and `picks.json` hold no outcome of 2020 and nothing from 2024 on.

## 10. Selection on SEL

### 10.1 Pair

A pair is (cell, combo, tier, TP step, stop, TP fill). Its statistics come from the SEL trade list with the weekend
rule.

### 10.2 Basic tests B

* (i) n >= 150 trades;
* (ii) win rate >= 70.0%;
* (iii) mean r > 0;
* (iv) cost-x2 mean r > 0.

### 10.3 Eligible

A pair is eligible when all of (a) to (e) hold.
* **(a)** It passes B.
* **(b) Exit plateau.** Every existing exit neighbour also passes B. The exit neighbours are the TP one step up and
  one step down within the tier (three steps), and the stop one step narrower and one step wider within its family,
  with the same combo, tier and fill. The families are ordered as ATR 1, 1.5, 2, 3 and price 0.60, 0.75, 1.00, 1.25,
  1.50%.
* **(c) Number plateau.** At least half of the existing number neighbours pass B. A number neighbour moves one number
  one grid step up or down and keeps the others and the exit (`run.combo_neighbours`). A definition with no neighbour
  meets (c).
* **(d) Account.** f* (8.4) is above 0. At f*, the SEL account takes at least 100 trades and its mean monthly ln M is
  above 0.
* **(e) SEL coin-flip check** (an addition, Q11). The pair's SEL mean r is above the mean over coin-flip seeds 1-200
  (control (a) of section 11, run on SEL).

### 10.4 Plateau score

The plateau score is the median SEL mean r over the pair and all its existing neighbours of (b) and (c). A neighbour
with n < 150 counts as 0.

### 10.5 The pick

* **Per cell, the eligible pair with the highest plateau score.**
* Ties go to the higher SEL account mean monthly ln M at f*, then to grid order: combo index, tier 30 < 40 < 50, TP
  step, stop in the order listed, taker before maker.
* **At most K = 1 pick per cell** (Q5).
* A cell with no eligible pair has no pick; it is recorded with its counts.

### 10.6 Recording and the hash

* `select.json` holds, per cell, how many pairs pass each test and the pick or "none" (DeepSeek per section 18).
* `picks.json` holds each pick's full definition and its SEL f*.
* The sha256 of `picks.json` is appended to the pin before any TEST data is downloaded. The confirm stage refuses
  otherwise.
* **Pairs that are not picks are never run on TEST.**

## 11. Controls (1,000 seeds each, through the same exits)

Both controls use the pick's exit config, tier, buffer, weekend rule, costs, f* and period.

* **(a) Coin-flip sides.** The pick's candidates (same coins, same signal bars), each side decided by a fair coin.
  Sections 7 and 8 then decide which are taken.
* **(b) Random times.** Per coin and side, the same number of trades as the pick has on that coin and side. Their
  signal-bar closes are drawn uniformly, without replacement, from that coin's bars in the period that meet all of:
  - a weekday bar (the weekend rule);
  - ATR14 > 0;
  - a fill minute inside the period;
  - a trade of that side is takeable at the pick's exit and tier (stop wider than the TP, stop room, resolved before
    the period end).

  Per coin, long and short are drawn together without replacement; the first n_long drawn are long.
* **Seeds.** s = 1..1,000. RNG = numpy PCG64 seeded with the first 8 bytes (little-endian) of
  sha256("hiwr|<a or b>|<period>|<pick id>|<s>"). The pick id is
  "<strategy>|<tf>|<combo index>|L<tier>|TP<price>|<stop>|<fill>".
* **Per seed:** the trade-list mean r and win rate, and the account at f*.
* **p_a and p_b** = (1 + the number of seeds whose trade-list mean r is at least the pick's) / 1,001.

## 12. Test pass rule (TEST, each pick, once)

| | condition |
|---|---|
| **T0** | at least 100 trades in the TEST trade list |
| **T1** | win rate >= 70.0% after costs |
| **T2** | the account at the SEL f*, starting with $1,000 at 2024-01-01: max DD (8.3) within the cap, no bust |
| **T3** | mean r > 0 |
| **T4** | cost-x2 mean r > 0 |
| **T5** | beats both controls: p_a < 0.05 and p_b < 0.05 |
| **T6** | p = max(p_boot, p_a, p_b) passes Benjamini-Hochberg at q = 0.10 over all picks |

How T6 works:
* p_boot is the one-sided week-block bootstrap p of mean r > 0. Trades are grouped by the UTC week (starting Monday)
  of their signal-bar close. 10,000 resamples; p = (1 + resamples with mean <= 0) / 10,001; seeded as in section 11
  with "boot" in place of s.
* Core and DeepSeek picks form one family.
* A pick that fails T0 stays in the family with p = 1.
* Taking the largest of the three p-values is an intersection-union test: a pick passes only if it passes all three
  tests.

**PASS = T0 to T6.** The verdict is per pick. A cell without a pick has no verdict; it is reported as "no pick".

## 13. Program-wide ledger

* **One look.** This study's TEST step is one confirm look (version hiwr v1).
* **Every pick's p goes into the program-wide ledger** (`research/hunt/PREREG_HUNT_WIDE.md` R13): a global BH at
  q = 0.10 and Holm at 0.05 over every test-period hypothesis of the program. That covers the hunt v1 pick, the wide
  batches, the O1-O4 reads, every later round, and this study's picks. The ledger is printed beside this study's verdict.
* **Two tracks, one test period.** Track 1 and track 2 use the same 33 months, so the chance that at least one pick of
  either passes by luck is larger than for either alone. The results page says so beside both verdicts and never merges
  them into one "track 2 passed".
* **A v2** (any rule change) is a new pre-registration with one new confirm look, also in the ledger. Forward paper data
  counts for a version only from the day its pre-registration is hashed.

## 14. Reads (reported, never a pass)

| read | what |
|---|---|
| **R1 with weekends** | the same pick with weekend entries allowed and its own f* from SEL with weekends; the trade list and the account on SEL and TEST, beside every verdict (the comparison the owners asked for) |
| **R2 other tiers** | the pick's TP price, stop and fill at each other tier whose ROE range contains that price (stop room changes): trades, win rate, mean, f*, margin % |
| **R3 loose buffer** | 0.2% only, with the count of liquidations |
| **R4 other ROE reading** | net if gross is the rule (2.1) |
| **R5 coins** | old six alone, new 24 alone, the 22 still-listed coins alone, the 8 proxy coins alone. The label "carried by the old six" when the new-24 TEST mean r <= 0 |
| **R6 extra 2020** | the trade list and the account at f* |
| **R7 maker realism** | TP fills only with a pierce of δ = 0.01% and 0.02% beyond T; the share of maker TP exits whose pierce was under 0.02%; the taker version of a maker pick |
| **R8 goal board** | monthly multiples at f* by the month bootstrap of `research/fullgrid/sizing.py` (4 weekly blocks drawn, 10,000 draws): P(month >= x2, x5, x10, x100), median month; the 33-month compounding |
| **R9 DD bootstrap** | the 95th percentile of a week-block bootstrap max DD at f* (SEL and TEST), and the f that would meet the cap at that percentile |
| **R10 flat by Saturday** | open positions closed at Saturday 00:00 UTC |
| **R11 splits and counts** | per year, per side, per coin; hold times; liquidations; skipped candidates by reason (weekend, stop inside TP, no stop room, minimum notional, bracket cut, busy, open at end) |
| **R12 live sizes** | the effect of quantity steps at $100, $300 and $500 wallets |
| **R13 streaks** | the distribution of losing streaks (for `max_consecutive_losses` live) |
| **R14 forward band** | the 5th..95th percentile of TEST rolling windows of 50, 100 and 200 trades (win rate, mean r) and of 30-day account multiples. Computed once with the verdict, hashed before any paper account uses it |

**Read guard** (as `PREREG_HUNT.md` §14):
* Reads run only on the picks, after `test.json` and the verdict exist, and write to their own files.
* They never change a pick, T0-T6, the verdict or the paper lineup.
* A read added after TEST is seen goes to `DEVIATIONS.md`, marked post hoc.
* DeepSeek rows follow section 18.

## 15. Honest expectation (from the practice period, before any search)

These numbers come from the feasibility runs of section 22: SEL only, the 6 old coins, the 36 core strategies at
default numbers for the owners' TP grid, and a sample of the full grid's exits. They are SEL numbers and in sample.

### 15.1 Costs against the target

| TP price move | taker-TP round trip 0.14%, as a share of the TP | maker-TP round trip 0.09%, as a share of the TP |
|---|---|---|
| +0.30% | 47% | 30% |
| +0.35% | 40% | 26% |
| +0.40% | 35% | 22.5% |

### 15.2 Break-even win rate

Take a driftless path with TP distance a and stop distance b, ignoring gaps and funding:
* A random entry hits the TP first with probability p0 = b / (a + b).
* Break-even after costs is p* = (b + 0.14) / (a + b) with a taker TP, and (b + 0.14) / (a + b + 0.05) with a maker TP.

| TP a | stop b | random p0 | break-even, taker TP | break-even, maker TP | skill needed (taker / maker) |
|---|---|---|---|---|---|
| 0.30% | 0.6% | 66.7% | 82.2% | 77.9% | +15.6 / +11.2 pp |
| 0.30% | 1.0% | 76.9% | 87.7% | 84.4% | +10.8 / +7.5 pp |
| 0.30% | 1.5% | 83.3% | 91.1% | 88.6% | +7.8 / +5.3 pp |
| 0.40% | 1.0% | 71.4% | 81.4% | 78.6% | +10.0 / +7.2 pp |

The loss autopsy measured the rule bot's chosen side beating a coin flip in exactly 50.0% of trades.

### 15.3 What SEL showed

* **Random entry at every bar** through these exits wins about 60-80% of the time and still loses.
  - The mean per trade is about -0.10% of notional with a maker TP and -0.14% with a taker TP, on every timeframe and
    stop. That is exactly the cost.
  - Example, 1h, +0.35% maker TP, 1% stop: 73.2% wins against a break-even of 80.3%, -0.100% per trade (-0.088R).
* **The 36 at default numbers** (weekend skip, house buffer, 9,072 strategy-settings per timeframe). Settings passing
  B (150 trades, win rate 70%, mean > 0, cost x2 > 0):

| | 15m | 30m | 1h | 4h |
|---|---|---|---|---|
| strategies | 0 | 0 | 0 | 8, all S4_BB_BBP at 30x with a maker TP |
| each coin-flip seed alone | 0 | 0 | 0 | 0 |

  With weekends included, as a comparison, 1h has 1 (N06_MACD_ORB) and 4h has 2.
* **A win rate of 70% or more with at least 150 trades is about as common for coin flips:**

| | 15m | 30m | 1h | 4h |
|---|---|---|---|---|
| strategy settings | 2,108 | 2,632 | 2,566 | 316 |
| coin-flip seeds | 1,998-2,080 | 2,268-2,390 | 2,084-2,180 | 238-268 |

* **The full grid's own exits on sampled numbers** (3,705 combos x 84 exits; default numbers, the full grid's own SEL
  picks, and random numbers):
  - roe10 is the closest existing exit to the owners' range: a limit TP +0.34% from the fill at 50x, +0.39% at 40x,
    +0.47% at 30x.
  - Its median win rate is 67.0 / 71.4 / 74.5 / 77.6% on 15m / 30m / 1h / 4h, against 66.5 / 71.0 / 73.5 / 76.5% for
    coin-flip sides at the same moments.
  - Core pairs passing B with weekends skipped (default plus random numbers): 0 / 20 / 19 / 366. Coin flips: 0 / 0.7 /
    2.0 / 11.7 (mean of 3 seeds).
  - DeepSeek, counts only: 0 / 0 / 30 / 163 (coin flips 0 / 0.3 / 3.3 / 17).
* **Stop room decides most of the leverage question.** At 50x the liquidation price is only 1.6% away even for
  BTC/ETH. Share of bars skipped with a 1 ATR stop at 30 / 40 / 50x:

| | 30x | 40x | 50x |
|---|---|---|---|
| 15m | 8% | 20% | 36% |
| 1h | 41% | 69% | 85% |
| 4h | 89% | 97% | 99% |

  A 1.5% stop never fits at 50x. Because the price targets are the same band at every tier, 40x and 50x added nothing
  in SEL. On the 1.0%-mmr alts of the 30-coin universe the room is smaller still (section 4).
* **The weekend skip** changed the per-trade mean by only +0.002 to +0.006% of notional on 15m-1h, and was slightly
  worse on 4h.

### 15.4 What the drawdown caps do to size and to the monthly return

* **Medians over the settings above.** The margin that keeps the SEL drawdown inside the cap is 0.11-0.16% of the
  wallet on 15m, 0.3-0.6% on 30m, 1.2-2.7% on 1h and 3-5% on 4h. At that size the SEL monthly return is -0.45%,
  -0.61%, -0.92 to -0.96% and -0.82 to -0.92% respectively. For a losing setting, DD sizing only says how small to bet
  to lose slowly.
* **The best SEL accounts**, picked as the best of many on the same period, so flattering:
  - 4h S4_BB_BBP, 30x, 1 ATR stop, +0.35% maker TP: 159 trades, 84.9% wins, margin 44% of the wallet, +4.5% per month.
    That margin is above this file's ceiling of L% = 30% (8.4 iii). Coin-flip sides at the same moments made -0.84% per
    month; with a taker TP the pick made +2.3%.
  - 1h S5_DONCHIAN_MFI, 30x, 1% stop, +0.40% maker TP: margin 24.5%, +1.5% per month.
  - The best on 30m made +0.11% per month. On 15m every account lost.
* **Why the rule bot's own sizing breaks the caps.** The rule bot puts L% of the wallet as margin, so f = L^2 / 100. A
  stop then costs f x (b + 0.14%) of equity:

| | 30x, margin 30% | 40x, margin 40% | 50x, margin 50% |
|---|---|---|---|
| loss per stop, 0.6% stop | 6.7% | 11.8% | 18.5% (one stop breaks the 15% cap) |
| loss per stop, 1.0% stop | 10.3% | 18.2% | 28.5% |
| gain per win, 0.30% TP (taker / maker) | 1.4 / 1.9% | 2.6 / 3.4% | 4.0 / 5.25% |

  At a 25% loss rate, the chance of 3 losses in a row somewhere in 500 trades is about 96%. Sized like the rule bot,
  a 15m account breaks its 15% cap almost surely.

### 15.5 The goal arithmetic

* **Size under a 15% cap.** Take a 1% stop. The cap allows a five-loss streak (the expected worst streak in about
  1,000 trades at a 25% loss rate) at f of about 2.85, i.e. margin 9.5% at 30x.
* **One win and one loss at that size**, with a +0.30% maker TP: a win is +0.60% of equity and a loss is -3.25%.
* **Even at a 100% win rate**, x5 needs about 270 wins in a row.
* **At break-even + 2 pp** (86.4% wins) the mean is about +0.075% of equity per trade, so x5 needs about 2,200 trades.
* **The best SEL pace**, +1.5 to +4.5% per month, compounds to about x1.7 to x4.9 over 36 months. The goal of x5 to
  x100 in one month is about two orders of magnitude away. **x5 in a month does not fit a 15-30% drawdown cap** unless
  the edge is far larger than anything this program has measured.

### 15.6 What to expect from this study

* **SEL passers will exist, by chance.** About 164.5 million pairs are searched on SEL, so pairs passing every SEL
  condition will be found whether or not any edge exists. The full grid's 711 picks went from +2.47% per trade on its
  select period to -0.25% on its test period.
* **The most likely result** is no pass on 15m and 30m.
* **If there is a pass at all**, it will most likely be on 4h at 30x with a maker TP. Even then its practice-period
  pace at the cap is a few % per month.

## 16. What a result means, and after

| result | then |
|---|---|
| **PASS (정식)** | a paper account next to track 1 (below). No real money before the paper criteria and the live checklist; real money is the owners' decision only |
| **fail, but 참고** | T0 to T4 hold and the pick's mean r is above both controls' seed means (not necessarily significant): a paper account labelled 참고. Never real money |
| **fail** | recorded with every number (DeepSeek: labels, section 18). No tuning on TEST |
| **no pick** | the cell is recorded with its SEL counts |

Rules after the result:
* **Nothing is tuned after TEST is seen.**
* **A bug** (the code not doing what this file says) found after the test run is fixed in `DEVIATIONS.md`, citing the
  line it breaks. The test is rerun once, both results are shown, and the rerun's verdict is the verdict.
* **Any changed rule is a v2.** That covers the TP reading, grids, buffer, size rule, entry conditions and K. A v2 is
  designed and selected on 2021-2023 only and judged as section 13 says.

### 16.1 Paper accounts (next to track 1)

* **A new package**, not written yet; working name `hiwrbot/`. candleague, huntbot and research/hunt belong to other
  jobs and are not changed.
* **How it runs.**
  - It is a candleague-style 1m replay of public Binance prices, recomputed after every closed 1m bar. It holds no keys
    and has no order code.
  - Like the hunt paper bot, it records from 2026-10-01 00:00 UTC whatever day it starts.
  - It trades the coins of the 30 that still trade (22).
  - It runs on the track 1 paper server `hunt-judge` beside huntbot (Q16).
  - Its accounts are shown side by side with track 1, never merged.
  - huntbot itself is 5m-based and too coarse for a 0.3% TP against a 0.6-1.5% stop.
* **Accounts per pick**, $1,000 each:
  - main: f* at its tier, with the pick's fill;
  - coin-flip twin;
  - random-time twin (seed 1);
  - with-weekend twin;
  - half-size twin (f* / 2).

  An account that reaches its DD cap stops and is marked failed.
* **Forward criteria before any real money** (all must hold). Data count only from the day this file's pin and the
  picks' hash exist.
  - (a) At least 100 forward trades.
  - (b) A replay of the same days from the archive reproduces at least 99% of the paper trades (entry, exit kind, exit
    minute).
  - (c) The forward win rate is at least 70%, and the forward mean r lies inside the R14 band for the same trade count.
  - (d) The forward DD stays below the cap.
  - (e) The main account's mean r is above the coin-flip and random-time twins'. This one is a label: at n = 100 the
    standard error of the win rate is about 4 pp, so a month of paper can catch fill or cost bugs but cannot prove an
    edge of 2-5 pp.
* **Paper cannot test the maker fill.** It uses the same through-fill rule as the backtest.

### 16.2 Small live (the owners' decision only)

* **Size.** $100-500, as the owners said. At $100, BTC's quantity step of 0.001 gives a size error of about ±20%
  (R12).
* **What the executor already has** (`paperbot/executor.py`):
  - an exchange-side stop (algo order, last price, reduce-only, confirmed);
  - a reconcile about every 3 s;
  - the risk rules of `paperbot/risk.py`: kill file, daily loss, DD halt, loss-streak halt, leverage and notional caps,
    per-trade loss at most 15% of the live wallet;
  - restart safety (`docs/live-safety.md`).
* **Missing before live** (to build and review first):
  - a reduce-only, post-only LIMIT take-profit order path with reconciliation: re-place it if missing, cancel it on a
    stop, resize the stop after a partial fill, and handle a GTX reject by a fixed rule;
  - a source adapter for a league other than `paper3.db`.
* **Settings.**
  - `entry_source` "signal" (a latency of 1-2 s matters for a 0.3% TP), with TP and stop placed from the live fill.
  - `max_drawdown_pct` = the cap.
  - `max_consecutive_losses` from the TEST streak distribution (R13). The current Q6 value of 4 would trip at a 20-30%
    loss rate.
  - `max_leverage` = the pick's L.
  - `max_notional` about 1.1 x f* x wallet.
* **Measuring the maker fill.** Testnet cannot validate maker fills or slippage. Live measures them: the maker fill
  rate, and `livepnl`'s Q6 #4 cost ratio against the paper twin. Stop when either is worse than modelled.

## 17. Code, compute plan, reproducibility

### 17.1 Code (none written yet)

The code is written after the open questions are closed, then reviewed, then pinned. It lives in `research/hiwr/`:
* `data.py`: a copy of the full grid's `data.py` for the 30 symbols, with month bounds.
* `walk.py`: numba exit-event tables per coin and timeframe. One 1m pass finds the first event of every stop, every TP
  (both fills) and every liquidation level. It is taken from the scratch prototype.
* `acct.py`: trade-list statistics; the one-at-a-time account with brackets and caps; the 1m mark-to-market DD; the f*
  bisection.
* `hiwr.py`: the command line (`datapin`, `datacheck`, `select`, `test`, `report`, `reads`, `pinlist`).
* `bootstrap.sh` and `SERVER_KO.md`.

**Tests** (`tests/test_hiwr_*.py`):
* walk against an independent per-minute loop;
* the maker mode against `kernel._trade` with a TP_R limit at the same price;
* the liquidation price against `kernel._liq`;
* the weekend mask at its boundaries;
* the stop-inside-TP skip, stop room and the bracket cut;
* the account's busy rule;
* the mark-to-market DD on synthetic paths, and that f* falls as DD rises;
* the seeds and the bootstrap.

**Imported read-only from `research/fullgrid`:**
* from `run.py`: `frame`/`build_frame`, `core_module`, `default_combo`, `cell_grid`, `signals`, `ds_module`,
  `_vendor_fg().atr`, `run_pool`, `combo_neighbours`, `WARMUP_BARS`;
* `grid.py` and `memo.py`;
* from `kernel.py`: `_entry_index`, `_liq`, `_bracket`, `bracket_arrays`.

**No pinned file of another study is edited.** Three traps to avoid:
* `run.SYMBOLS` and `run.exchange()` know only the six coins, so hiwr passes its own symbol list and brackets.
* hiwr uses its own `FRAME_DIR` with SEL-cut frames, never `fgwork/frames`, which hold the full period.
* The full grid's `fgwork/outcomes/*.npz` are never read: they include 2020 and 2024 on, and use house sizing.

### 17.2 Storage layout

A per-coin, per-config stats file, as the full grid used, would come to about 190 GB at 30 coins. Instead:
* A task is a (cell, combo chunk); coins are the outer loop and combos the inner loop, so the memo still works per coin.
* Per pair, only float64 sums are stored: n, wins, sum r, sum r at cost x2, wins at cost x2. That is about 6-13 GB.
* Disk stays under 30 GB, and RAM is about 1.8 GB per worker.

### 17.3 Pin

The pin lists exactly what `python -m research.hiwr.hiwr pinlist` prints:
* this file and every `research/hiwr` module the command imports;
* the hiwr tests;
* every repository Python file the signal code loads, found by running each definition once on synthetic bars, as the
  hunt does;
* `research/fullgrid/{grid.py, ds_defs.py, kernel.py, run.py, memo.py, data.py, exchange.json}`, as their own pins
  hold them;
* `research/entry_study/DEFS_BC.sha256`;
* `research/hunt/universe30.json` and `research/hunt/exchange30.json`;
* `research/hiwr/data_manifest_sel.json` and `research/hiwr/data_check_sel.json`.

Later lines are appended in this order: `picks.json`, then `data_manifest_test.json`, then the reads modules (listed
before `test.json` exists).

### 17.4 Compute plan (Vultr)

The server recipe is the hunt's: CPU Optimized, 32 vCPU, Tokyo, Ubuntu 24.04, about $1 an hour, Destroy when done.

| step | estimate on 32 vCPU |
|---|---|
| 1m download and build, 30 coins, 2020-01 .. 2023-12 (about 3.5 GB of zips, about 4.9 GB of npz) | 25-35 min |
| exit-event tables, 4 timeframes x 30 coins | about 40 CPU-min; 2-3 min wall |
| signals of 1,015,563 combos on SEL-cut frames, plus per-pair trade-list sums over the 162 exit configs | about 175-200 CPU-h; 6-7 h wall |
| plateau, accounts and f* (1m mark-to-market) for pairs passing B; SEL coin-flip seeds 1-200 for those still eligible | under 1 h |
| **select, in total** | **about 8 h, about $8-10** |
| confirm stage, after the picks' hash: TEST 1m download (about 2.3 GB of zips), the picks only, 2 x 1,000 control seeds, the reads | about 1 h |
| with the 5-step subset instead (Q4) | about 25-40 CPU-h; 1-1.5 h wall for select |

**Basis for the estimates:**
* The scratch prototype ran on this shared 4-core box with one process, 6 coins, SEL and default numbers: 15m 1,243 s,
  30m 584 s, 1h 178 s, 4h 32 s.
* The full grid's own estimate was 70-80 CPU-h for 6 coins over 2020-2026.
* 30 coins give about 5.0 times the 6-coin SEL bars.

**Which server:**
* The code does not exist yet; the select run starts only after the pin.
* The hunt server (`hunt-compute`, running the pinned hunt with all CPUs since 2026-10-11 15:12 UTC) is not shared.
  Track 2 never touches `/root/hunt` and never runs beside the hunt.
* Option (a): after the hunt prints 끝. and its results are pushed, clone into `/root/hiwr` on the same server before it
  is Destroyed. This works only if hiwr is pinned by then.
* Option (b): a separate server, `hiwr-compute` [default].
* A server rented before the pin costs about $1 an hour while it waits. A wait_go-style line, as the hunt used, can
  start the run as soon as the pin lands.
* The confirm stage downloads its own data and can run later on any server.
* This dev box cannot hold the 30-coin 1m data (about 2 GB free, shared).

## 18. DeepSeek (D11)

* Rows of the 44 DeepSeek definitions in repository files show **counts, shares (win rates, pass shares) and labels
  only**: eligible or not, which condition failed, picked, T0-T6 pass or fail, PASS, 참고.
* Their other numbers (mean r, DD, f*, margin %, monthly returns, p-values) go only to a file outside the repository.
  Its sha256 is written in the repository output, so the selection and the test can be checked later without the
  figures being in the repository.
* Reads follow the same rule.

## 19. Known limits and what was already seen

* **SEL has been looked at closely.** The loss autopsy, the full grid's SEL selection and this study's feasibility runs
  all used it. The feasibility runs used default numbers on these exact TP and stop grids (section 22). The design (TP
  steps, stop grid, buffer, weekend rule) was made knowing those results. That is allowed in the practice period, but
  every SEL figure of a pick is in sample.
* **TEST is not blind on the old six.** The owners and the main session have read the full grid's results on
  2024-2026: its 711 picks and the default numbers under the house exits, including roe10, a fixed limit TP +0.34% to
  +0.47% from the fill at the house leverage. They have also seen the rule bot's and the candidate league's forward
  records from October 2026.
  - The new 24 have not been read on TEST at exits like these; the hunt's TEST run uses a trend machine on 5m bars.
  - R5 shows the new 24 alone.
* **Universe and brackets.**
  - The 2023 volume rank favours coins that moved in 2023. That flatters SEL; TEST stays point in time.
  - The bracket tables are a 2026 snapshot.
  - 8 coins use a proxy table (section 4).
* **Fills.**
  - Inside a minute the order of events is unknown, so the worst case is taken (a stop first).
  - The maker TP fills at its level without a queue (7.2, R7).
  - Liquidation is checked on mark price per minute; the stop triggers on last price.
* **Overlap.** Trade-list trades overlap (no position limit). The week-block bootstrap carries that dependence; the
  account does not overlap.
* **Win rate is not evidence by itself** (sections 1 and 15).
* **Power.** With about 100-300 TEST trades per pick, a win-rate edge of 2-5 pp is close to the noise (standard error
  2.5-4 pp).

## 20. Not in this study

* per-coin numbers;
* more than one position at a time (Q13);
* exits other than these: ladders, trailing stops, partial take-profits;
* maker entries;
* the G1 gate and the FOMC/NFP blackout as rules;
* timeframes other than the four, and coins outside the 30;
* an AI judgment layer;
* leverage other than 30x, 40x and 50x;
* the net ROE reading, unless the owners choose it (Q1).

## 21. Open questions for the owners (closed before the pin; default in brackets)

1. **ROE reading.** Gross (the ROE on Binance's position screen, before fees) or net (after the 0.14% round trip,
   which makes the TP +0.44% .. +0.54%)? [gross]
2. **4h drawdown cap.** The owners named 15m, 30m and 1h only. [30%, the same as 1h]
3. **The 8 coins that stopped trading.** Options: a proxy table (the SAND/COMP table); exclude them (survivorship);
   old six only. [proxy; the 22 still-listed coins and the old six as reads, R5]
4. **Numbers grid.** The full 9-step 1/3x..3x grid, as asked (about 8 h on 32 vCPU, about $8-10). Or the 5-step
   subset: lengths x (1/2, 2/3, 1, 1.5, 2), thresholds f = 0.5 .. 1.5. It has fewer values, so less selection luck, and
   takes about 1-1.5 h. [9-step]
5. **Picks per cell.** One, any tier; or one per tier, up to 3 per cell, which triples the multiple-testing load.
   [one]
6. **Stop-room buffer.** The house buffer max(0.2%, 1 ATR), or 0.2% only. The 0.2% buffer lets more trades fit at
   40x/50x and on 1h/4h, with more liquidation risk. [house; 0.2% as read R3]
7. **Size ceiling.** Margin at most L% of the wallet, and a single loss at most 15% of the wallet: the rule bot's and
   the paper rules' own limits. [yes]
8. **f* basis.** The SEL path itself, or the 95th percentile of a week-block bootstrap DD, which gives a smaller, safer
   size. [the SEL path; the bootstrap size shown in R9]
9. **Weekend.** Skip entries only, so a Friday position keeps running; or be flat by Saturday 00:00 UTC. [entries only;
   flat-by-Saturday as read R10]
10. **Weekend clock.** UTC Saturday 00:00 - Monday 00:00 (KST Saturday 09:00 - Monday 09:00), or KST Saturday 00:00 -
    Monday 00:00. [UTC]
11. **SEL coin-flip check as a selection condition** (10.3 e). An addition not in the brief. [yes]
12. **FOMC/NFP 120-minute blackout as an entry rule.** The calendar `research/hunt/macro_calendar.json` is still
    unverified. [no; at most a read once the calendar is verified]
13. **Positions at once.** One at a time, or up to 3 with a same-side cap. [one; 3 is not run]
14. **Starting wallet.** [$1,000, the owners' goal]
15. **Server.** A separate `hiwr-compute` server once the kit is pinned, or the hunt server after the hunt is done.
    [separate]
16. **Paper accounts on `hunt-judge` next to track 1.** [yes]
17. **Minimum trades.** 150 on SEL (100 in the account), 100 on TEST. [yes]
18. **TP steps.** Low, mid and high of each tier's range, or only the two ends. [low / mid / high]
19. **Stop grid.** ATR 1 / 1.5 / 2 / 3 and price 0.60 / 0.75 / 1.00 / 1.25 / 1.50%. [yes]
20. **Additions not in the brief**: the stop must be wider than the TP; the house buffer; one position at a time; the
    account minimum; the plateau rule; T6 as the largest of three p-values; mark-to-market DD; the 참고 rule. [keep]

## 22. Before this file was fixed

### 22.1 Feasibility on SEL (2026-10-11, scratch only, not in the repository)

**Hygiene.**
* Only signals whose bar closed before 2024-01-01 were used.
* The 1m data and the chart frames were cut at 2024-01-01 00:00 UTC before any calculation, and trades still open at
  the cut were dropped.
* 2020 was not used. Nothing from 2024-01-01 on was read, computed or printed.
* The full grid's stored outcome arrays were not used for any number. The pinned kernel was re-run, unedited, on the
  cut data. Its plumbing check against `kernel.outcomes` matched 74,396 values (largest difference 1.5e-8, no
  missing-value mismatches).

**Two parts:**
* (A) The full grid's 84 exits on a sample of 3,705 of the 1,015,563 combos: every default, every full-grid SEL pick,
  and 4 / 6 / 10 / 24 random number sets per cell on 15m / 30m / 1h / 4h. That makes 311,220 pairs.
* (B) The owners' TP grid at both readings. It covered the 36 core strategies at default numbers on 6 coins, with 7
  stops (1 / 1.5 / 2 / 3 ATR and 0.6 / 1.0 / 1.5%), 30x / 40x / 50x, taker and maker fills, house and loose buffers,
  with and without weekends, and three coin-flip seeds. Its accounts allowed margin up to 100% of the wallet.

**Parity of the new simulator:**
* against an independent minute-by-minute loop: 57,600 pairs, largest difference 9e-10;
* against the kernel's limit-TP rule: 7,992 pairs, largest difference 4e-9.

**Outputs and scripts** are in the session scratchpad: `hiwr/feas/` (tables), `hiwr/private/` (raw results and
DeepSeek figures), and `hiwr/work/` (`tpgrid.py`, `feasA.py`, `parity_a.py`, `parity_b.py`, `report_a.py`,
`report_b.py`, `headline.py`). Section 15 quotes them; DeepSeek appears there as counts only.

### 22.2 Design inventory (2026-10-11, no computation)

* **What it used:** code, docs, data manifests, timing lines of the prototype logs, and the SEL ATR levels (a price
  property, not an outcome).
* **It set:**
  - the tier as a margin label (2.1);
  - the break-even table (15.2);
  - the stop grid and the house buffer (7.3, 7.4);
  - the 30-coin data plan (sections 3 and 4);
  - the DD definition and the size rule (8.3, 8.4);
  - the compute estimate (17.4);
  - the path from paper to live (16).

### 22.3 This draft (2026-10-11, about 15:50 UTC)

* Written before any code of `research/hiwr` and before any 1m data of the new 24 coins was downloaded.
* The interpretation of section 2 is the main session's. The owners have not yet confirmed it.
