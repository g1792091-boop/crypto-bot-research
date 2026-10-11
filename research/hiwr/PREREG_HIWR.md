# Track 2, high win rate under an account drawdown cap (고승률 · 낙폭 한도): pre-registration

(한국어 설명: `README_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면
`DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (about 15:50 UTC), revised about 16:40 UTC after two reviews (section 22.4) and
about 21:30 UTC after the owners' answers (section 22.5). Not pinned.** No code for this study exists in the repository
yet. The only computations behind this draft are the practice-period feasibility runs and re-runs of section 22. They
used signals whose bar closed before 2024-01-01 only. Nothing from 2024-01-01 on was read, computed or printed, and 2020
was not used.

**All questions are closed** (section 21, a decision log since 2026-10-12 KST). The owners answered three: the ROE is
read after fees (Q1), the 4h cap is 30% (Q2), and track 2 runs on its own server after the hunt server is Destroyed
(Q15). Every other question closed at its default. The status stays DRAFT until the code is written, reviewed and
pinned.

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
* a take-profit inside the owners' ROE range at 30x, 40x or 50x, read after fees (2.1);
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

## 2. The owners' targets (confirmed 2026-10-12, section 21)

### 2.1 Take-profit: ROE after fees (Q1)

"30배 9%에서 12%" is a per-trade take-profit at an ROE of 9-12% on the isolated margin of a 30x position. Likewise 40x
is 12-15% and 50x is 15-18%. **The ROE is read after fees** (owners, 2026-10-12: "1번은 수수료 뺀후고"). This is how
the rule bot's own `default_tp_roe` and the full grid's ROE take-profits are defined. The TP price move from the fill
is the ROE step divided by the leverage plus the round-trip cost of 7.7:
* **taker TP:** t = ROE / L + 0.14%;
* **maker TP:** t = ROE / L + 0.09%.

| tier | owners' ROE range (after fees) | TP steps used (low / mid / high) | taker TP: price move from the fill | maker TP: price move from the fill |
|---|---|---|---|---|
| 30x | 9-12% | 9 / 10.5 / 12% | +0.44 / +0.49 / +0.54% | +0.39 / +0.44 / +0.49% |
| 40x | 12-15% | 12 / 13.5 / 15% | +0.44 / +0.4775 / +0.515% | +0.39 / +0.4275 / +0.465% |
| 50x | 15-18% | 15 / 16.5 / 18% | +0.44 / +0.47 / +0.50% | +0.39 / +0.42 / +0.45% |

* A TP exit then keeps the step's ROE. The 0.14% and 0.09% include the entry slippage, which the fill F already
  contains. So a TP exit nets about 0.02% of notional more than the step, before funding (0.6 / 0.8 / 1.0 ROE points
  at 30 / 40 / 50x). The rule keeps the owners' formula as given.
* Funding is not in the target, because it is not known at the fill. It is charged as it falls (7.6).
* A 1% stop costs about 34% ROE at 30x, 46% at 40x and 57% at 50x ((1.0 + 0.14) x L).
* **The gross reading** (ROE before fees, as on Binance's position screen; price move = ROE / L, +0.30 .. +0.40%) is
  a comparison only (R4). It was the draft's default before the owners answered.

All three tiers ask for about the same move in price: +0.44-0.54% with a taker TP, +0.39-0.49% with a maker TP.
Leverage does not change what happens to a trade in price. For a fixed notional, the tier changes only three things:
* how far away the liquidation price is, and so which stops fit (7.4);
* the margin locked, and with it the most an isolated position can lose;
* the bracket tier.

So the tier is a margin label on one backtest plus a stop-room limit. Section 8.4 reports the margin % it implies.

### 2.2 Drawdown

"낙폭" is read as the **account's** maximum drawdown (peak to trough of equity, 8.3), not the loss of one trade. The
caps:

| timeframe | 15m | 30m | 1h | 4h |
|---|---|---|---|---|
| cap | 15% | 20% | 30% | 30% |

The owners named 15m, 30m and 1h in the brief and confirmed 30% for 4h on 2026-10-12 ("4시간봉 낙폭 30% 맞고", Q2).
The cap is met by choosing the margin per trade on the practice period (8.4). It is not met by changing the strategy.

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

| coins (first-tier mmr from exchange30.json) | first-tier mmr | 30x | 40x | 50x |
|---|---|---|---|---|
| BTC, ETH | 0.4% | 2.95% | 2.11% | 1.61% |
| SOL, XRP, BNB, LTC, BCH, LINK, AVAX, ADA, ETC (9) | 0.5% | 2.85% | 2.01% | 1.51% |
| ATOM | 0.6% | 2.75% | 1.91% | 1.41% |
| DOGE, DOT, CRV | 0.65% | 2.70% | 1.86% | 1.36% |
| FIL, NEAR, SAND, AXS, COMP, RUNE and the 8 proxy coins (14) | 1.0% | 2.36% | 1.52% | 1.01% |
| TRB (max 50x) | 1.5% | 1.86% | 1.02% | 0.51% |

  Distance = 1 - (1 - 1/L) / (1 - mmr) for a long (7.4, cum 0). At 50x little stop room is left on most alts (7.4).
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

The smaller 5-step subset is not used (Q4).

### 6.3 Exit configs per combo

Each combo is tried with 3 tiers x 3 TP steps (2.1) x 9 stops (7.3) x 2 TP fills (7.2) = 162 exit configs. That makes
about 164.5 million (combo, exit) pairs. The TP price of a step depends on the fill (2.1): at the same ROE step a taker
TP lies 0.05% further from the fill than a maker TP.

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

The level is T = F x (1 + t) for a long (F x (1 - t) for a short), where t is the TP step's price move for that fill
(2.1): ROE / L + 0.14% for a taker TP, ROE / L + 0.09% for a maker TP. It is placed at the fill.

* **Taker TP** (a take-profit-market order):
  - It triggers when the 1m high reaches T (low for a short).
  - It fills at T x (1 - 0.0002) for a long; when a minute opens beyond T, at that open x (1 - 0.0002).
  - Taker fee 0.05%. Round trip with the entry: 0.14% of notional.
* **Maker TP** (a resting reduce-only, post-only limit):
  - It fills only when price trades **through** T within the minute: the 1m high must be above T (below for a short),
    strictly; or when a minute opens beyond T.
  - It always fills **at T**. A resting limit is matched at its own price, so a minute that opens beyond T still fills
    it at T. (The full grid kernel and PaperEngine fill a limit at a better gapped open; this study does not. Otherwise
    it is the kernel's limit rule, `research/fullgrid/PREREG.md` §5.)
  - Maker fee 0.02%, no slippage. Round trip 0.09%.
  - **It is optimistic.** Queue position is not modelled, and a pierce of one tick may not fill a resting order. R7
    reads pierce requirements of 0.01% and 0.02%, the share of maker exits whose pierce was under 0.02%, and the share
    of TP fills inside the entry minute (where a post-only order placed after the fill may be late or rejected). Live,
    the order must be post-only (GTX).
* Either TP can fill in the entry minute, on that minute's high or low after its open, as in the kernel.

### 7.3 Stop

* A stop-market order on last price, like the live executor's algo stop.
* Level S = P0 - D for a long (P0 + D for a short). D comes from the stop grid, two families:
  - ATR: **k x ATR14 of the signal bar, k in {1, 1.5, 2, 3}**;
  - price: **p x P0, p in {0.60, 0.75, 1.00, 1.25, 1.50}%**.
* ATR14 = `_vendor_fg().atr(frame, 14)`, as in the full grid.
* It fills at S x (1 - 0.0002) for a long when the 1m low touches S, or at a gapped open x (1 - 0.0002). Taker fee.
* **The stop must be wider than the take-profit.** A candidate whose stop distance from the fill, |F - S| / F, is not
  greater than t is skipped and counted as "stop inside TP". Only ATR stops on calm bars can hit this: the narrowest
  price stop (0.60%, about 0.62% from the fill) is wider than the widest TP (+0.54%).

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
* **Round trip:** 0.14% with a taker TP or a stop; 0.09% with a maker TP. These are the costs the ROE reading adds to
  the TP price (2.1). They stay fixed in the TP price when costs are doubled for the cost-x2 test.
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
  (E_close) and at the bar's adverse last-price extreme (E_adverse, the low for a long). Both are less the slippage and
  fee of a market exit at that price.
* **Peak(t)** = the maximum of the starting wallet, every E_close before t, and every wallet value after a close. A
  minute's adverse extreme is measured against the peak of the closes before that minute (the close is the minute's
  last price, so its own close cannot come before its extreme).
* **Exit minute.** Its adverse extreme counts only when the exit is a TP filled inside the minute (worst case: the dip
  came first). A stop or liquidation counts at its fill; an exit on the open has no further mark.
* **Max DD** = the maximum over t of 1 - E_adverse(t) / Peak(t), together with 1 - wallet / Peak after every close. The
  peak includes open-trade highs, because a trade can rise to just under T and then fall to its stop.
* The realized-only DD (closed trades only) is reported beside it. It is never larger than the mark-to-market DD.
* **Bust** = equity below 10% of the start. The account stops there.

### 8.4 Size f*, fixed on SEL

For a pair at its tier L, **f* (the registered size)** is the largest f that meets all four of these:
* (i) the SEL path's max DD (8.3) is at most the cap of its timeframe;
* (i') the 95th percentile of the SEL week-block bootstrap max DD (below) is at most the cap (Q8);
* (ii) the worst single SEL account trade loses at most 15% of the equity before it. This is the paper rules' per-trade
  cap, `max_loss_frac` in paperbot `risk.py`;
* (iii) f <= L^2 / 100, i.e. the margin is at most L% of the wallet. That is the rule bot's own margin: f is at most 9,
  16 and 25 at 30x, 40x and 50x.

**f_path** is the same without (i'): the size at which the SEL path itself touches the cap. It is reported beside f*
(R9) and is the Q8 alternative.

**Why (i').** If the size is fitted so that the SEL path sits exactly at the cap, a genuine edge that does not change
between the periods still breaks the cap on TEST about half the time, because the TEST path is a new draw of the same
luck (iid simulation, `review_stats/t2_sim.py`: 0.45-0.49; 0.29 when the 30x ceiling binds). T2 would then mostly test
drawdown-path luck. At the bootstrap 95% size the breach is about 0.10. The SEL re-run shows the same: at f_path,
13-45% of the resampled SEL paths of the eight net-reading 4h B-passers break the cap (15.4).

**The bootstrap.** The pair's SEL account trades (8.2, taken at the SEL path) are grouped by the UTC week (Monday) of
their fill minute; SEL has 157 such weeks, empty ones included. A resample draws 157 weeks with replacement and runs
their trades in draw order. 10,000 resamples, the same draws for every f, seeded as in section 11 with "f95" in place of
s. Each resample recomputes the 1m mark-to-market DD (8.3) from each trade's own minute marks.

**Method.**
* The realized-only DD gives an upper bound on f_path, because the realized DD is never larger than the mark-to-market
  DD. It only brackets the search.
* f_path and f* are found by bisection on the exact 1m mark-to-market DD (and, for f*, its bootstrap 95th percentile),
  40 steps, rounded down to 0.01.

**Reported:** f*, the margin % of the wallet (f* / L), and the notional as a multiple of the wallet, at the pick's tier;
f_path the same; the share of bootstrap paths over the cap at each. R2 gives the same at the other tiers whose ROE range
contains the TP price. **f* and f_path are fixed on SEL and never re-fitted on TEST.** Wherever this file says f*, it
means the registered size.

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
  - **Thinned neighbours (Q21).** A neighbour has the pair's own candidates; it can only have fewer trades because more
    of them are skipped (no stop room, stop inside TP, open at end). On 1h and 4h a wider ATR stop loses most of its
    trades to the stop-room skip (4h 30x, 1 ATR: 88.5% skipped; 1.5 ATR: 94.6%), so the strict rule would test stop
    room, not robustness. Therefore a neighbour with 50 <= n < 150 must pass B(iii) and B(iv) only (mean > 0, cost-x2
    mean > 0), and a neighbour with n < 50 counts as not existing.
* **(c) Number plateau.** At least half of the existing number neighbours pass B. A number neighbour moves one number
  one grid step up or down and keeps the others and the exit (`run.combo_neighbours`). A definition with no neighbour
  meets (c).
* **(d) Account.** f* (8.4) is above 0. At f*, the SEL account takes at least 100 trades and its mean monthly ln M is
  above 0.
* **(e) SEL coin-flip check** (an addition, Q11). The pair's SEL mean r is above the 95th percentile of coin-flip seeds
  1-200 (control (a) of section 11, flipped per signal bar as there, run on SEL). A check against the seeds' mean would
  remove nothing: coin-flip means sit near minus the cost (about -0.10%), and (a) already asks for mean > 0 and
  cost-x2 mean > 0. Every B-passer of the feasibility beat its coin-flip mean, and the 8 net-reading B-passers of the
  re-run (15.3) were also above the 95th percentile of 200 such seeds.

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

## 11. Controls (100,000 seeds each, through the same exits)

Both controls use the pick's exit config, tier, buffer, weekend rule, costs, f* and period. **Both keep the pick's
clustering.** A pick's candidates bunch on the same signal bar across correlated coins (SEL feasibility: 59.9% of the 4h
S4_BB_BBP candidates share their bar and side with another coin). Randomizing each candidate on its own makes the null
too narrow: the coin-flip null SD was 1.10x (S4_BB_BBP 4h) and 1.19x (S5_DONCHIAN_MFI 1h) larger with flips shared per
signal bar, and S5's p moved from 0.0012 to 0.0025 (`feas/B_control_clustering.csv`). With 30 coins the groups grow.

* **(a) Coin-flip sides.** The pick's candidates (same coins, same signal bars). One fair coin per group of candidates
  that share a signal-bar close and an original side: heads keeps the group's side, tails reverses it for every member.
  Sections 7 and 8 then decide which are taken.
* **(b) Random times.** The pick's trades are grouped into clusters by signal-bar close; a cluster is its set of
  (coin, side). Each cluster is moved to a signal-bar close t' drawn uniformly, without replacement across the seed's
  clusters, from the period's weekday bars at which every member is takeable: its coin has a bar with ATR14 > 0 and a
  fill minute inside the period, and a trade of its side passes the pick's exit and tier rules there (stop wider than
  the TP, stop room, resolved before the period end). When fewer than 20 such bars exist for a cluster, t' is drawn
  from the bars where at least one member is takeable and the others are dropped for that draw (counted and reported).
* **Seeds.** s = 1..100,000. RNG = numpy PCG64 seeded with the first 8 bytes (little-endian) of
  sha256("hiwr|<a or b>|<period>|<pick id>|<s>"). The pick id is
  "<strategy>|<tf>|<combo index>|L<tier>|TP<price>|<stop>|<fill>".
* **Per seed:** the trade-list mean r and win rate. Seeds 1..1,000 also run the account at f* (reported, not part of p).
* **p_a and p_b** = (1 + the number of seeds whose trade-list mean r is at least the pick's) / 100,001. The floor is
  about 1.0e-5.
* **Why 100,000.** With 1,000 seeds the floor 1/1,001 makes T6 impossible for a lone true pick once the family has more
  than about 100 picks (BH at q = 0.10 needs p <= 0.10 / m), and K = 1 allows up to 315. With 100,000 a lone pick can
  pass for any m up to 10,000, and the ledger's Holm at 0.05 (13) can reject for a family of up to 5,000. A seed costs
  only a sum over precomputed outcomes: (a) needs both sides' outcome of every candidate, (b) the outcome of every
  takeable bar per coin and side, one walk each.

## 12. Test pass rule (TEST, each pick, once)

| | condition |
|---|---|
| **T0** | at least 100 trades in the TEST trade list |
| **T1** | win rate >= 70.0% after costs |
| **T2** | the account at the SEL f* (the registered size of 8.4), starting with $1,000 at 2024-01-01: max DD (8.3) within the cap, no bust |
| **T3** | mean r > 0 |
| **T4** | cost-x2 mean r > 0 |
| **T5** | beats both controls: p_a < 0.05 and p_b < 0.05 |
| **T6** | p = max(p_boot, p_a, p_b) passes Benjamini-Hochberg at q = 0.10 over all picks |

How T6 works:
* p_boot is the one-sided week-block bootstrap p of mean r > 0. Trades are grouped by the UTC week (starting Monday)
  of their signal-bar close. 100,000 resamples; p = (1 + resamples with mean <= 0) / 100,001; seeded as in section 11
  with "boot" in place of s. Its floor, like p_a's and p_b's, is about 1.0e-5 (section 11, why 100,000).
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
  - DeepSeek picks (D11, section 18) enter the ledger's BH and Holm computation with their p-values, but the repository
    ledger shows only their pass or fail labels. Their p-values go to the private file of section 18, whose sha256 is
    printed. This is how the hunt handles them (`PREREG_HUNT_WIDE.md` §11).
  - The p floor is about 1.0e-5 (section 11), so Holm at 0.05 can reject a hypothesis of this study while the ledger
    holds up to 5,000.
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
| **R4 gross ROE reading** | the pick with the TP at the gross reading (ROE before fees, price move ROE / L, 2.1), its own f* from SEL; the trade list and the account on SEL and TEST |
| **R5 coins** | old six alone, new 24 alone, the 22 still-listed coins alone, the 8 proxy coins alone. The label "carried by the old six" when the new-24 TEST mean r <= 0 |
| **R6 extra 2020** | the trade list and the account at f* |
| **R7 maker realism** | TP fills only with a pierce of δ = 0.01% and 0.02% beyond T; the share of maker TP exits whose pierce was under 0.02%; the share of TP fills inside the entry minute, and the result when those trades must wait for a later minute; the taker version of a maker pick at the same ROE step (TP 0.05% further; the SEL net-reading passers fail cost x2 with a taker TP, 15.3) |
| **R8 goal board** | monthly multiples at f* by the month bootstrap of `research/fullgrid/sizing.py` (4 weekly blocks drawn, 10,000 draws): P(month >= x2, x5, x10, x100), median month; the 33-month compounding |
| **R9 DD bootstrap** | the 95th percentile of the week-block bootstrap max DD (8.4) and the share of paths over the cap, at f* and at f_path, on SEL and on TEST; the TEST account at f_path (the Q8 alternative) |
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

These numbers come from the feasibility runs and the review re-runs of section 22: SEL only, the 6 old coins, the 36
core strategies at default numbers for the owners' TP grid, and a sample of the full grid's exits. They are SEL numbers
and in sample. Where the feasibility differs from this design (closed-trade DD, no size ceiling, no stop-inside-TP skip,
7 of the 9 stops, a maker fill at a better gapped open, one cost for the net reading), section 22.1 says so and the
figures below say which basis they use.

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
* **The 36 at default numbers, per TP reading** (house buffer; 4,536 strategy-settings per reading and timeframe:
  36 x 3 tiers x 3 TP steps x 7 stops x 2 fills). Settings passing B (150 trades, win rate 70%, mean > 0, cost x2 > 0):

| reading | weekends | 15m | 30m | 1h | 4h |
|---|---|---|---|---|---|
| **gross (the rule, 2.1)** | **skipped (the rule)** | **0** | **0** | **0** | **2: S4_BB_BBP, 30x, maker +0.40%, 1 ATR and 1% stops** |
| gross | included (comparison) | 0 | 0 | 0 | 0 |
| net as run (Q1 alternative) | skipped | 0 | 0 | 0 | 6, all S4_BB_BBP 30x maker |
| net as run | included | 0 | 0 | 1 (N06_MACD_ORB 40x maker) | 2 (S4_BB_BBP 30x maker) |
| each coin-flip seed alone | any row | 0 | 0 | 0 | 0 |

  - The net rows were run with +0.14% for both fills. With the corrected maker targets (2.1: ROE / L + 0.09%), the
    0.44% and 0.49% maker settings match the 10.5% and 12% steps at 30x, the 0.54% ones (and N06's 0.515% at 40x) lie
    above the owners' range, and +0.39% was not run. So 4 of the 6 net passers sit on a corrected net target.
  - The first draft of this file quoted "8 on 4h, and with weekends 1 on 1h and 2 on 4h"; that pooled both readings.
* **At default numbers the registered selection finds 0 eligible pairs on every timeframe.** Both gross passers fail
  the exit plateau (10.3 b): their +0.35% TP neighbour fails cost x2 (-0.025% with the 1 ATR stop, -0.037% with 1%).
  The 1 ATR pair's wider neighbour, 1.5 ATR, has 83 trades and a cost-x2 mean of -0.050%, so it fails even under Q21's
  relaxed rule.
* **The pass rests on the maker fee.** With a taker TP both gross passers fail cost x2 (-0.067% and -0.083% per trade).
  Filling the maker TP exactly at T instead of a better gapped open changed nothing (identical to four decimals), and
  neither did a required pierce of 0.01% or 0.02%, although 11-13% and 20-25% of their TP exits pierced by less. 6 of
  133 and 8 of 261 TP fills came inside the entry minute (R7).
* **The entries add a little win rate, far less than needed.** Gross reading, weekend skip, house buffer:

| | 15m | 30m | 1h | 4h |
|---|---|---|---|---|
| strategy-settings with win rate >= 70% and >= 150 trades | 1,570 | 1,882 | 1,686 | 204 |
| the same for each coin-flip seed | 1,528-1,582 | 1,684-1,764 | 1,468-1,530 | 172-186 |
| median win rate, 30x maker settings: strategies minus coin flips at the same moments | +0.2 pp | +0.8 pp | +1.5 pp | +1.7 pp |

  On 30m-4h the strategies have 7-19% more 70% settings than every seed, so the entries carry a small real effect. The
  break-even needs 5-16 pp over a random entry (15.2).
* **The full grid's own exits on sampled numbers** (3,705 combos x 84 exits; default numbers, the full grid's own SEL
  picks, and random numbers; core, default plus random numbers, weekend skip, pairs with >= 150 trades):
  - roe10 is the closest existing exit to the owners' range: a limit TP at net ROE 10% on the house leverage, +0.34%
    from the fill at 50x, +0.39% at 40x, +0.47% at 30x and +0.64% at 20x.
  - roe10's median win rate is 68.5 / 72.6 / 75.2 / 76.8% on 15m / 30m / 1h / 4h, against 68.4 / 72.3 / 74.1 / 74.6%
    for coin-flip sides at the same moments.
  - roe10 pairs passing B: 0 / 5 / 4 / 77. Coin flips: 0 / 0.3 / 0.3 / 4.0 (mean of 3 seeds).
  - All 84 exits together: 0 / 20 / 19 / 366, coin flips 0 / 0.7 / 2.0 / 11.7. Most are roe20 (0 / 7 / 9 / 139) and
    the ladders (ladder20 0 / 4 / 2 / 56, ladder 0 / 2 / 1 / 28), far outside +0.30-0.40% (`feas/A_pass4_by_exit.csv`).
  - DeepSeek, all 84 exits, counts only: 0 / 0 / 30 / 163 (coin flips 0 / 0.3 / 3.3 / 17).
* **Stop room decides most of the leverage question.** At 50x the liquidation price is only 1.6% away even for
  BTC/ETH. Share of bars skipped with a 1 ATR stop at 30 / 40 / 50x (weekend skip):

| | 30x | 40x | 50x |
|---|---|---|---|
| 15m | 8% | 20% | 36% |
| 1h | 41% | 68% | 85% |
| 4h | 89% | 97% | 99% |

  A 1.5% stop never fits at 50x. Because the price targets are the same band at every tier, 40x and 50x added nothing
  in SEL. On the 1.0%-mmr coins of the 30-coin universe the room is smaller still (section 4).
* **Stop inside the TP.** The feasibility did not apply 7.3's rule that the stop be wider than the TP. Share of SEL
  long bars that fit at 30x but whose 1 ATR stop is not wider than the TP: 15m 12 / 18 / 25% at TP 0.30 / 0.35 / 0.40%;
  30m 4.4-10.6%; 1h 1.3-3.9%; 4h 0 (1.5 ATR: 15m 4.4-10.1%). So the 15m and 30m ATR-stop win rates and 70% counts above
  include trades this design skips.
* **The weekend skip** changed the per-trade mean by only +0.002 to +0.006% of notional on 15m-1h, and was slightly
  worse on 4h.

### 15.4 What the drawdown caps do to size and to the monthly return

* **Medians over the settings above** (closed-trade DD, margin allowed up to 100%, so these are upper bounds: the
  registered size uses the mark-to-market DD and the bootstrap rule of 8.4, which only make it smaller). The margin
  that keeps the SEL drawdown inside the cap is 0.11-0.16% of the wallet on 15m, 0.3-0.6% on 30m, 1.2-2.7% on 1h and
  2.4-5.1% on 4h. Nearly all of these settings lose; for them the monthly return at that size says nothing new. A
  setting that loses steadily, sized so that its 36-month drawdown equals the cap, loses about the cap over SEL by
  construction: (1 - cap)^(1/36) - 1 = -0.45%, -0.62% and -0.99% a month at 15%, 20% and 30%.
* **The two gross B-passers** (4h S4_BB_BBP, 30x, maker +0.40%, house buffer, weekend skip; 6 coins, in sample, the
  best of many, and both fail the exit plateau above), sized three ways (`feas/B_accounts_sizes.csv`):

| stop | trade list | account | closed-trade DD (the feasibility's basis) | mark-to-market DD, SEL path (f_path) | registered f* (8.4) |
|---|---|---|---|---|---|
| 1 ATR | 159 trades, 83.7% wins, +0.098% / trade, cost x2 +0.016% | 116 trades | margin 30.2%, +3.56% / month | margin 26.5%, +3.16% / month (x3.06 in 36 months) | margin 20.5%, +2.49% / month (x2.42) |
| 1% | 314 trades, 83.1% wins, +0.082% / trade, cost x2 +0.0002% | 231 trades | margin 21.3%, +4.08% / month | margin 20.2%, +3.89% / month (x3.96) | margin 11.9%, +2.36% / month (x2.32) |

  - At f_path, 24% (1 ATR) and 49% (1%) of the week-block resampled SEL paths break the 30% cap; at f*, 5%.
  - At the 8.4 (iii) ceiling (f = 9, margin 30%) the 1 ATR account's mark-to-market DD is 33.4%, above the cap (its
    closed-trade DD is 29.8%).
  - Coin-flip sides at the same moments made -0.88% and -0.35% a month (feasibility basis).
* **Two accounts quoted in the first draft fail B** and are kept here only so the change is visible:
  - 4h S4_BB_BBP, 1 ATR, maker +0.35% (cost x2 -0.025%). The draft's "+4.5% a month at 44% margin" was closed-trade DD
    with no ceiling; under this file's rules it is margin 30% (the ceiling), +3.16% a month, and at f* 21.5%, +2.32%.
  - 1h S5_DONCHIAN_MFI, 1%, maker +0.40% (cost x2 -0.056%). Closed-trade 24.5%, +1.49% a month; mark-to-market 22.7%,
    +1.40%; f* 10.4%, +0.71%. A quarter of its TP fills (30 of 122) came inside the entry minute.
  - The best on 30m made +0.11% a month (closed-trade basis); on 15m every account lost.
* **Why the rule bot's own sizing breaks the caps.** The rule bot puts L% of the wallet as margin, so f = L^2 / 100. A
  stop then costs f x (b + 0.14%) of equity:

| | 30x, margin 30% | 40x, margin 40% | 50x, margin 50% |
|---|---|---|---|
| loss per stop, 0.6% stop | 6.7% | 11.8% | 18.5% (one stop breaks the 15% cap) |
| loss per stop, 1.0% stop | 10.3% | 18.2% | 28.5% |
| gain per win, 0.30% TP (taker / maker) | 1.4 / 1.9% | 2.6 / 3.4% | 4.0 / 5.25% |

  At a 25% loss rate, the chance of 3 losses in a row somewhere in 500 trades is about 99.8%. Sized like the rule bot,
  a 15m account breaks its 15% cap almost surely.

### 15.5 The goal arithmetic

* **Size under a 15% cap.** Take a 1% stop. The cap allows a five-loss streak (the expected worst streak in about
  1,000 trades at a 25% loss rate) at f of about 2.85, i.e. margin 9.5% at 30x.
* **One win and one loss at that size**, with a +0.30% maker TP: a win is +0.60% of equity and a loss is -3.25%.
* **Even at a 100% win rate**, x5 needs about 270 wins in a row.
* **At break-even + 2 pp** (86.4% wins) the mean is about +0.075% of equity per trade, so x5 needs about 2,200 trades.
* **The best SEL pace** is that of the only gross B-passer, which still fails the exit plateau: +2.4 to +2.5% a month
  at the registered size, about x2.3-2.4 over 36 months (x3.1-4.0 at the SEL-path size; +3.6 to +4.1% a month on the
  feasibility's closed-trade basis). The goal of x5 to x100 in one month is about two orders of magnitude away. **x5 in
  a month does not fit a 15-30% drawdown cap** unless the edge is far larger than anything this program has measured.

### 15.6 What to expect from this study

* **SEL passers will exist, by chance.** About 164.5 million pairs are searched on SEL, so pairs passing every SEL
  condition will be found whether or not any edge exists. The full grid's picks, chosen on this same practice period,
  are the example: their select-period mean was +2.47% per trade, in sample; section 19 says how they fared later.
* **At default numbers the registered rules pick nothing** (15.3). Picks will come from other numbers, where the
  selection luck is largest.
* **The most likely result** is no pass on 15m and 30m.
* **If there is a pass at all**, it will most likely be on 4h at 30x with a maker TP. Even then its practice-period
  pace at the registered size is about 2-3% a month.

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
  - huntbot itself is 5m-based and too coarse for a 0.4-0.5% TP against a 0.6-1.5% stop.
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
* the maker mode against `kernel._trade` with a TP_R limit at the same price, on every trade whose TP exit is not on a
  gapped open (there the kernel fills at the open and hiwr at T, 7.2; those trades are counted and must differ only in
  the exit price);
* the liquidation price against `kernel._liq`;
* the weekend mask at its boundaries;
* the stop-inside-TP skip, stop room and the bracket cut;
* the account's busy rule;
* the mark-to-market DD on synthetic paths (the exit-minute rule and the peak-before-the-minute rule of 8.3), that the
  realized DD never exceeds it, and that f_path and f* fall as DD rises;
* the week-block bootstrap of 8.4 against a slow per-path loop;
* the control groups of section 11 (joint flips per bar and side; clusters moved whole), the seeds and the bootstrap.

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
| plateau, accounts, f_path and f* (1m mark-to-market, 10,000 bootstrap paths per bisection step) for pairs passing B; SEL coin-flip seeds 1-200 for those still eligible | about 1 h |
| **select, in total** | **about 8-9 h, about $8-10** |
| confirm stage, after the picks' hash: TEST 1m download (about 2.3 GB of zips), the picks only, 2 x 100,000 control seeds (sums over precomputed outcomes; 1,000 with accounts), the reads | about 1 h |

**Basis for the estimates:**
* The scratch prototype ran on this shared 4-core box with one process, 6 coins, SEL and default numbers: 15m 1,243 s,
  30m 584 s, 1h 178 s, 4h 32 s.
* The full grid's own estimate was 70-80 CPU-h for 6 coins over 2020-2026.
* 30 coins give about 5.0 times the 6-coin SEL bars.

**Which server (Q15, decided 2026-10-12).** Track 2 runs on its **own server, after the hunt server is gone**. The
owners: "32 vcpu로 두대를 못돌리는거야? 그러면 따로 돌려야지". Vultr's monthly fee limit already refused a 64 vCPU server,
so two 32 vCPU servers at once would likely be refused too. The order:
1. The code is written, reviewed and pinned (the kit). Nothing of track 2 runs before that.
2. The hunt (track 1) finishes on `hunt-compute`, its results are pushed, and the owners Destroy that server. Track 2
   never touches `/root/hunt` and never runs beside the hunt.
3. The owners create a new server, `hiwr-compute`, with the same recipe (32 vCPU), and paste one line from
   `research/hiwr/SERVER_KO.md`. Like the hunt's `wait_go.sh`, that line clones the branch, waits until the pinned
   commit is published on it, checks the pins, and starts `select`. If the pin is already published, it starts at once.
4. After `select` the results are pushed and the server is Destroyed.

Notes:
* The confirm stage downloads its own data. It needs the picks' hash in the pin (10.6) and can run later on any server.
* A server rented while it waits costs about $1 an hour (Vultr bills a stopped server too), so it is created only after
  step 2.
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
  all used it. The feasibility runs used default numbers on the owners' TP steps and 7 of the 9 stops (no 0.75% and
  1.25%), without the stop-inside-TP skip (section 22.1); the net-reading re-run (22.5) used all 9 stops and the skip.
  The design (TP steps, stop grid, buffer, weekend rule, size rule) was made knowing those results. That is allowed in
  the practice period, but every SEL figure of a pick is in sample.
* **TEST is not blind on the old six.** The owners and the main session have read the full grid's results on
  2024-2026: its 711 picks and the default numbers under the house exits, including roe10, a fixed limit TP +0.34% to
  +0.64% from the fill at the house leverage. They know that the full grid's SEL picks did not hold up on its confirm
  period (`research/fullgrid/STRATEGY_EVAL_KO.md`); this file quotes no number of it. They have also seen the rule
  bot's and the candidate league's forward records from October 2026.
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
* **Overlap.** Trade-list trades overlap (no position limit) and bunch on the same bar across coins. The week-block
  bootstrap carries that dependence for p_boot; the two controls keep it by flipping and moving whole bar groups
  (section 11); the account does not overlap.
* **Drawdown luck.** A TEST drawdown is one new path. Even at the bootstrap size f* (8.4) a genuine edge that does not
  change breaks the cap on TEST about 10% of the time (Q8).
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
* the gross ROE reading as a rule (it is read R4 only, Q1).

## 21. Decision log (all closed 2026-10-12 KST)

The owners answered Q1, Q2 and Q15 on the morning of 2026-10-12 KST, in Korean (quoted). They had been told that every
other question closes at its default unless they answer; they did not object, so those closed at their defaults.
Earlier decisions stay as they were: weekends excluded on all four timeframes, 4h included (with weekends only as a
comparison, R1); caps 15m 15%, 30m 20%, 1h 30%; win rate at least 70% after costs; SEL 2021-2023 for the search and
TEST 2024-01 .. 2026-09 looked at once.

| Q | question | decision | by |
|---|---|---|---|
| 1 | ROE reading | **net, after fees**: TP price move = ROE / L + 0.14% (taker TP) or + 0.09% (maker TP), 2.1. Gross is read R4 only | owners: "1번은 수수료 뺀후고" |
| 2 | 4h drawdown cap | **30%**, the same as 1h (2.2) | owners: "4시간봉 낙폭 30% 맞고" |
| 3 | the 8 coins that stopped trading | proxy table (SAND/COMP, section 4); the 22 still-listed coins and the old six as reads (R5) | default |
| 4 | numbers grid | full 9-step grid, 1/3x .. 3x (6.2); the 5-step subset is not run | default |
| 5 | picks per cell | one, any tier (10.5) | default |
| 6 | stop-room buffer | house, max(0.2%, 1 ATR) (7.4); 0.2% only as read R3 | default |
| 7 | size ceiling | margin at most L% of the wallet, one loss at most 15% of the wallet (8.4) | default |
| 8 | f* basis | bootstrap 95% (8.4); f_path shown beside it (R9) | default |
| 9 | weekend | entries only skipped; flat by Saturday as read R10 | default |
| 10 | weekend clock | UTC Saturday 00:00 - Monday 00:00 (KST Saturday 09:00 - Monday 09:00) | default |
| 11 | SEL coin-flip check as a selection condition | yes, above the 95th percentile of 200 seeds (10.3 e) | default |
| 12 | FOMC/NFP blackout as an entry rule | no; at most a read once the calendar is verified | default |
| 13 | positions at once | one | default |
| 14 | starting wallet | $1,000 | default |
| 15 | server | **a separate 32 vCPU server, created after the hunt server has finished and been Destroyed** (17.4). Vultr's monthly fee limit refused a 64 vCPU server, so two 32 vCPU servers at once would likely be refused too | owners: "32 vcpu로 두대를 못돌리는거야? 그러면 따로 돌려야지" |
| 16 | paper accounts | on `hunt-judge` next to track 1 (16.1) | default |
| 17 | minimum trades | 150 on SEL (100 in the account), 100 on TEST | default |
| 18 | TP steps | low / mid / high of each tier's range | default |
| 19 | stop grid | ATR 1 / 1.5 / 2 / 3 and price 0.60 / 0.75 / 1.00 / 1.25 / 1.50% | default |
| 20 | additions not in the brief | kept: stop wider than the TP, house buffer, one position at a time, the account minimum, the plateau rule, T6 as the largest of three p-values, mark-to-market DD, the bootstrap size, the maker TP filled at T, controls that keep bar groups together, 100,000 control seeds, the 참고 rule | default |
| 21 | exit plateau with thinned neighbours | relaxed (10.3 b): 50-149 trades need mean > 0 and cost-x2 mean > 0; below 50 the neighbour counts as missing | default |

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

**Where the feasibility differs from this design** (each one is labelled where section 15 quotes it):
* Its accounts were sized on the closed-trade DD (`tpgrid.acct_dd`), with no ceiling (ii) or (iii) and no bootstrap
  rule. Its margins and monthly paces are therefore upper bounds of 8.4's; 22.4 re-sizes the passers.
* It did not skip a stop that is not wider than the TP (7.3): 12-25% of the 15m 1 ATR candidates that fit at 30x, 4-11%
  on 30m, 1-4% on 1h, none on 4h.
* It used 7 of the 9 stops (no 0.75% and 1.25%).
* Its maker TP filled at a better open when a minute opened beyond T (7.2 now fills at T; no effect on the passers).
* Its net reading added 0.14% for both fills (2.1 now adds 0.09% for a maker TP).

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
* The interpretation of section 2 was the main session's. The owners answered on 2026-10-12 (22.5).

### 22.4 Review fixes (2026-10-11, about 16:40 UTC, SEL only)

Two reviews (statistics; feasibility) re-derived the feasibility numbers independently on SEL and matched them to four
decimals. Their confirmed findings changed this file:
* **Counts per TP reading** (15.3): the first draft pooled the gross and net readings. Gross with weekends skipped:
  0 / 0 / 0 / 2; with weekends: 0 everywhere. Recounted from the stored SEL results (`fix/counts.py`,
  `feas/B_counts_by_reading.csv`, `feas/A_pass4_by_exit.csv`).
* **Exit plateau**: both gross passers fail it, so 0 eligible pairs at default numbers. Q21 relaxes the rule for
  neighbours thinned by skips; the passers still fail.
* **Sizing**: 8.3 made exact (exit minute, peak before the minute); 8.4 now registers the bootstrap-95% size f* (Q8),
  because a size fitted to the SEL path breaks the cap on TEST about half the time for an unchanged edge. The passers
  were re-sized under 8.3 and 8.4 (`fix/acct_fix.py`, `feas/B_accounts_sizes.csv`): the closed-trade figures were
  reproduced exactly, and the registered pace is +2.4-2.5% a month instead of the draft's quoted +1.5 to +4.5%.
* **Controls** (11): flips and time draws keep bar groups together (`feas/B_control_clustering.csv`); 100,000 seeds
  and 100,000 bootstrap resamples so that T6 and the ledger's Holm can reject at all.
* **10.3 (e)** now asks for the 95th percentile of the SEL coin-flip seeds; against their mean it removed nothing.
* **7.2**: the maker TP fills at T. **2.1**: the net reading adds 0.09% for a maker TP. **4**: the liquidation table
  covers all 30 coins. **13**: DeepSeek p-values stay private in the ledger. **15.6**: no confirm-period number of
  another study is quoted. **15.4**: the mechanical monthly returns are replaced by one sentence; the streak chance is
  99.8%; the 1h 40x skip share is 68%; the 4h margin medians are 2.4-5.1%.
* Re-runs: `fix/acct_fix.py` (S4_BB_BBP 4h and S5_DONCHIAN_MFI 1h at default numbers, 6 coins, data cut at 2024-01-01
  on load, unresolved trades dropped), `review_stats/t2_sim.py` (synthetic), `review_feas/stopinside.py` (bar ATR
  only). All in the session scratchpad `hiwr/`.

### 22.5 Owners' answers and the net-reading re-run (2026-10-11, about 21:30 UTC = 2026-10-12 06:30 KST, SEL only)

**Decisions.** The owners answered three questions on the morning of 2026-10-12 KST: Q1 net ROE ("1번은 수수료
뺀후고"), Q2 4h cap 30% ("4시간봉 낙폭 30% 맞고"), Q15 a separate server after the hunt server is Destroyed ("32 vcpu로
두대를 못돌리는거야? 그러면 따로 돌려야지"). All other questions closed at their defaults (section 21). Changed with them:
2.1 (the net price table per tier and TP fill; gross becomes read R4), 2.2, 6.2, 6.3, 7.2, 7.3, 7.7, 8.4, 10.3 (e), R4,
R7, 15 (net numbers), 16.1, 17.4 (server plan; the paragraph on a server the owners had created is removed), 19, 20,
21 (a decision log) and the status line. The status stays DRAFT: no code exists yet.

**Why a re-run.** The feasibility's net rows (22.1) priced the maker TP at ROE / L + 0.14%, not the registered + 0.09%,
used 7 of the 9 stops and did not skip a stop inside the TP. Their counts were 0 / 0 / 0 / 6 (15m / 30m / 1h / 4h) with
weekends skipped and 0 / 0 / 1 / 2 with weekends, and they could not say whether a net passer meets the exit plateau.
So part B was re-run under the registered net rules before the counts were quoted.

**The re-run** (session scratchpad `hiwrbuild/`: `netgrid.py`, `ana.py`, `acct_net.py`, `pierce.py`; outputs in
`hiwrbuild/out/`).
* Hygiene: the 1m arrays of the 6 old coins were cut at 2024-01-01 00:00 UTC right after loading, and the chart frames
  were built from the cut arrays (no stored frame or outcome of the full grid was read). Signal-bar closes 2021-01-01 ..
  2024-01-01; 2020 bars were indicator warm-up only; trades not resolved by the cut were dropped. Nothing from
  2024-01-01 on was read, computed or printed.
* Rules: the 36 core strategies at default numbers; 30x / 40x / 50x; TP steps at the net reading (taker + 0.14%, maker
  + 0.09%) and at the gross reading for comparison; all 9 stops; the stop-inside-TP skip (7.3); the maker TP filled at
  T (7.2); the house buffer; with and without weekends; three coin-flip seeds; cost x2 with the TP price unchanged.
* Parity with the feasibility code: on every setting both runs share and where no stop-inside-TP skip applies, the
  taker results are identical (trade counts and sums of r); the maker sums differ by at most 0.003 in total, from the
  fill at T on a gapped open. The account script (`acct_net.py`, built on the review's independent minute loop)
  reproduced the 8 passers' trade lists exactly.
* Results: section 15 (counts, plateau, coin-flip check, maker realism, sizes).

