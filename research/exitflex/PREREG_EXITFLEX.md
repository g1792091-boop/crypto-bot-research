# Flexible exits for the 23 core watch picks: pre-registration (exitflex v1)

(한국어 요약: `README_KO.md`.) This file is fixed before any number of this study exists. It is pinned by
`PREREG_EXITFLEX.sha256` together with the code and inputs of section 13. Changes after the pin go to `DEVIATIONS.md`
in this folder, dated and with the reason, never into this file.

Written 2026-10-12 (KST). Owners' request, about the 후보 리그 ("커스텀값 봇"), where a SOL long had been held about 18 h
at +43% ROE under a fixed 3R take-profit and a 4 ATR stop:
"익절구조를 과거 백테스트를 돌려서 좋게 잡은건 좋은데 포지션 보유시간이 길어지면 진입횟수에도 영향을 끼치잖아 ... 18시간씩
보유하고있으면 솔직히 좀 그래 예를들어 롱을 잡아서 +60%까지 갔다가 롱구조가 무너지거나 더이상 안오를꺼 같으면 빠르게
전량익절을 한다던지 ... 반대로 손절 부분도 마찬가지고 만약 손절을 -60%로 잡아놨고 롱을 잡아놨었는데 롱 구조가 무너지고
-40%까지 간상황에서 더 떨어질꺼 같은 판단이 들고 롱 구조가 무너졌다고 생각이되면 원래 손절가가 -60%지만 ... 빠르게 전량
손절을 한다던지". Earlier the same day: "유도리있게 나는 그런식으로 가고싶은데", "지금 나와 친구는 빠르게 매매법을
완성을 시켜서 성공을 시켜야하는데".

## 1. Question

The 23 core picks keep their entries. If each one exits by a flexible rule instead of its current exit, does the
account grow faster per month? The rules (a structure break, a moving-average break, the opposite signal, a chandelier
trail, a profit giveback, an early loss cut or a time stop) are checked at chart-bar closes. The account holds one
position at a time over six coins, so a signal that arrives while a position is open is lost. The full-grid study
never counted those lost signals: it judged exits by the mean per-trade P&L with every signal counted (PREREG.md 5-6).
A rule must also do better than a random early exit at the same rate. Otherwise any gain could come from shorter holds
alone and not from reading the market.

## 2. Data

* Source: Binance USD-M public archive (data.binance.vision). Files: 5m klines (last price), 5m mark-price klines and
  funding-rate history for BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT, LTCUSDT and BCHUSDT. First bars: BTC, ETH and BCH
  2020-01-01, LTC 2020-01-09, DOGE 2020-07-10, SOL 2020-09-14. The last bar of every coin opens 2026-09-30 23:55 UTC.
  Local copy: the replica folder `coins30/{5m,funding}/<SYM>.npz` (manifest sha256 `62c638f9…`). Before the select run
  the sha256 of each of these twelve files is written to `research/exitflex/data_pin.json` and pinned (section 13).
  The runner refuses any other file.
* Loading follows the adapter of the hold-cost replica (`hc.py` `load_5m`, copied into this folder as `data_x.py`),
  which does what `research/fullgrid/data.py` does per minute. Zero-volume 5m bars are dropped. A bar without a mark
  price takes the last-price bar. Funding rows are de-duplicated by calc time (the last one is kept), and each is
  settled on the 5m bar whose open <= calc time < open + 5 min, or on the next available bar.
* Chart bars (15m, 30m, 1h, 4h) are UTC bins of the 5m bars, built by `run.build_frame` with the last-bin test on the 5m
  bar length (`hc.py` patch 2). A bin with bars missing inside is kept as built. A bin with no bar does not exist.
* Periods are set by the signal bar's close (UTC). **Select**: [2021-01-01, 2024-01-01), 36 calendar months.
  **Confirm**: [2024-01-01, 2026-10-01), 33 months. A coin's first 300 chart bars are warm-up only (`run.period_ids`).
* The select run loads the 5m arrays cut at 2024-01-01 00:00 UTC (bars that open before it) and builds every chart
  bar and indicator from them. No bar from 2024-01-01 on enters any select-period number. The confirm run loads the
  full arrays.
* Approximation: the study and the league run on 1m bars, and this study runs on 5m bars. The order of high and low
  inside a 5m bar is unknown, so a bar that touches both the stop and the take-profit counts as a stop (the kernel's
  rule). Fills and rule exits happen at 5m opens. E0 and every variant share this approximation, so the comparison is
  fair, but the numbers are not the study's or the league's numbers.

## 3. Entries

* **Picks**: the 23 rows of kind `core` in `research/fullgrid/diag/watch_sel.json` (sha256 `f6902feb…`). These are the
  league's core watch accounts, with ids as in `candleague/data/candidates.json`.

  | id | tf | take-profit | stop |
  |---|---|---|---|
  | core-DOGE-15m-1 | 15m | 3R | 4 ATR |
  | core-DOGE-30m-1 | 30m | 3R | 3 ATR |
  | core-DOGE-1h-1 | 1h | 3R | 4 ATR |
  | core-DOGE-4h-1 | 4h | 3R | 2 ATR |
  | core-N03_ADX_GC-15m-1 | 15m | 3R | 3 ATR |
  | core-N03_ADX_GC-30m-3 | 30m | 3R | 2 ATR |
  | core-N03_ADX_GC-1h-1 | 1h | 3R | 2 ATR |
  | core-N09_ALLIG_AROON-15m-3 | 15m | 3R | 4 ATR |
  | core-N09_ALLIG_AROON-30m-1 | 30m | 3R | 2.5 ATR |
  | core-N09_ALLIG_AROON-1h-1 | 1h | 3R | 4 ATR |
  | core-N09_ALLIG_AROON-4h-1 | 4h | 3R | 1.5 ATR |
  | core-N10_HA_PSAR-4h-1 | 4h | 3R | 2 ATR |
  | core-N13_3OUTSIDE-30m-1 | 30m | 3R | 2.5 ATR |
  | core-N13_3OUTSIDE-1h-1 | 1h | 3R | 4 ATR |
  | core-N19_FIB_CHOP-15m-1 | 15m | 3R | 4 ATR |
  | core-N19_FIB_CHOP-30m-1 | 30m | 3R | 3 ATR |
  | core-N19_FIB_CHOP-4h-1 | 4h | 3R | 3 ATR |
  | core-OBV_S-30m-2 | 30m | 3R | 4 ATR |
  | core-OBV_S-1h-3 | 1h | net ROE 50% | 4 ATR |
  | core-OBV_S-4h-1 | 4h | 3R | 1.5 ATR |
  | core-S4_BB_BBP-30m-1 | 30m | 2R | 2 ATR |
  | core-S4_BB_BBP-1h-2 | 1h | 3R | 2.5 ATR |
  | core-S4_BB_BBP-4h-1 | 4h | 3R | 1 ATR |

  Timeframes: 4 picks on 15m, 7 on 30m, 6 on 1h and 6 on 4h. No pick uses the stepped lock. No DeepSeek pick is
  included (owners' rule D11).
* **Signals**: `run.signals("core", name, sym, tf, combo)` with the pick's combo (the pinned `param_defs`), on the chart
  bars of section 2, for every coin. The leverage group comes from `run.best_flags`. ATR14 is `fg_indicators.atr(df, 14)`
  (Wilder) at the signal bar.
* **Fill**: at the open of the first 5m bar that opens at or after the signal bar's close (later only when bars are
  missing), plus 0.02% slippage. This is `kernel._entry_index` on the close shifted by 60,000 - 300,000 ms (`hc.py`
  item 4).
* **Offered signals**: every long and short signal of the period whose ATR14 is finite and > 0 and whose fill bar opens
  before the period's last 5m bar. They are sorted by (fill time, coin priority BTC, ETH, SOL, DOGE, LTC, BCH). On one
  bar of one coin the long comes before the short (`run.per_trade` order, stable sort). The account sizes each signal at
  its own wallet and rejects a signal that no size fits, as the league's PaperEngine does. (`run.account_run` offered
  only the signals that live sizing could size at $5,000. Here every exit and every size gets the same offer.)
* Entries are therefore identical for E0 and every variant: the same signals in the same order, the same hard stop and
  the same sizing rule. What differs is what happens after the fill, and so which later signals find the account
  free.

## 4. Engine

* A new numba kernel, `research/exitflex/kernel_x.py` (`_trade_x`, `account_x`), copies `kernel._trade` and
  `kernel.account` (`research/fullgrid/kernel.py`, sha256 `a4995c15…`) and adds three things: a rule check at chart
  closes (section 5), a forced close at the period end, and a free fill bar after a rule exit (below). With no rule,
  and with the period end after the data end, it must reproduce the kernel exactly (test T1, section 13).
* **Settings**: `config.v3_settings` through `kernel.settings_vector`, with every margin fraction times `scale`
  (`sizing.size_vector(scale)`). Scale 0.25 (quarter size) decides. Scale 1.0 (live size) is reported. Leverages stay
  as they are under quality_v1:
  * best: 50x at 50% margin, then 40x at 40%;
  * normal: 30x at 30%, then 20x at 20%;
  * margin fractions times `scale`.

  A candidate size must pass all of these:
  * the bracket's maximum leverage;
  * the stop lies inside the liquidation price by max(0.2% x fill, 1 x ATR14);
  * the stop loss, fees and slippage included, is <= 15% of the wallet.

  Brackets and order-size rules come from `research/fullgrid/exchange.json`. Costs and limits: $5,000 at the start of
  each period, taker 0.05%, slippage 0.02% each way, maker 0.02% on take-profit limits, funding, isolated-margin
  liquidation on the mark price, bust below $10.
* **Quantities** (as in the kernel). `side` is +1 for a long and -1 for a short.
  * raw = the fill bar's open; fill = raw x (1 + side x 0.0002).
  * **R** = k x ATR14 of the signal bar, where k is the pick's stop.
  * Hard stop = raw - side x R. It never moves.
  * Take-profit at m R: raw + side x m x R.
  * Take-profit at net ROE v: fill x (1 + side x (v / lev + rt)), with rt = 0.0014 (`S[5]`, the round trip of taker
    plus slippage).
  * **Net ROE** at price P, after funding F has been paid: ROE(P) = lev x (side x (P / fill - 1) - rt - F / (qty x
    fill)). This is the kernel's own best-ROE formula from the stepped lock.
  * Entry fee: qty x fill x taker. An exit at price X adds side x qty x (X - fill) - qty x X x fee to the wallet. The
    fee is maker at a take-profit limit and taker otherwise. A loss beyond the margin is a liquidation, and the margin
    is lost.
* **Inside one 5m bar j after the entry bar e** (the kernel's order, with the new step 6):
  1. Funding settled at j's open on the mark open; the liquidation price is recomputed.
  2. The favourable extreme is updated with j's high (long) or low (short).
  3. A mark open beyond liquidation: liquidation.
  4. An open beyond the hard stop: exit at the open with slippage, taker (SL).
  5. An open beyond the take-profit: exit at the open, maker (TP).
  6. **New**: a rule exit due at j (section 5) exits at the open with slippage and taker (RULE). A placebo exit
     (section 6) does the same (RAND). A forced period-end close due at j does the same (END).
  7. The bar's range. A low (long) or high (short) through the stop exits at the stop with slippage (SL). Otherwise a
     mark low or high through liquidation liquidates. Otherwise a range through the take-profit exits at the
     take-profit, maker (TP). The stepped lock, which no pick uses, is unchanged.

  The entry bar e gets the range checks for stop, liquidation and take-profit only: no gap check, no rule and no lock,
  as in the kernel.
* **Account** (as `kernel.account`): one position at a time over the six coins, with signals taken in the offered
  order. A signal whose fill time is not after the open position's exit time is skipped. Ties at one fill time go to
  coin priority. A rejected signal does not block. A bust below $10 ends the account.
  **Addition: after a RULE or RAND exit at bar j, the account is free for signals that fill at the open of the same
  bar j** (exit first, then entries; in kernel terms busy_until = exit time - 1 ms). After any other exit the kernel's
  rule stands. The reason: a rule exit is decided at the chart close, before that bar opens, so a bot can close and
  open at that open. An intrabar stop or take-profit happens after that open, when the old position still held the
  account. Under F3 this means that the opposite signal which closed the position is entered at the same open when it
  ranks first and can be sized (a reversal).
* **Period end**: a position still open at the open of the period's last 5m bar is closed at that open, after steps 1-5,
  with slippage and taker fee (END). The last bar is the coin's last bar opening before the period end: 2023-12-31
  23:55 or 2026-09-30 23:55 UTC. This applies to E0 and every variant alike. The study's account let such positions
  run on; here no bar after the period is read. A rule exit and END due at the same bar give the same price and are
  recorded as RULE.
* **E0**, the reference, is each pick's own exit (its take-profit and its k x ATR14 stop) through `kernel_x` with no
  rule.

## 5. Variants

### 5.1 Common to every variant

* **Check closes**: the closes of the pick's chart bars after the signal bar i0 (C0 + tf, C0 + 2 tf, ..., where C0 is
  i0's close). Variants marked **q15** check on 15m closes after C0 for picks on 1h and 4h. They use 15m UTC bins of the
  5m bars, and their levels still come from the pick's timeframe (5.2). On picks of 15m and 30m a q15 variant checks on
  the pick's own closes and equals its base variant.
* A rule that fires at check close C exits at the open of the first 5m bar j that opens at or after C (step 6 of
  section 4). If that bar is the entry bar, the exit moves to the next bar.
* At a check close C a rule may use only:
  * the chart bars closed at or before C: their OHLC, ATR14, EMA, the swings confirmed by then and the pick's signals;
  * the 5m bars before j: the favourable extreme X, the highest high since the fill for a long or the lowest low for a
    short (bars e .. j - 1);
  * the funding F paid before j.

  ROEc is the net ROE at the check close's price. ROEpk = ROE(X) is the kernel's best ROE. Prices are last prices, not
  mark prices, as in the study's signals and ATR.
* Every variant keeps the pick's hard stop, sizing and leverage (k x ATR14 of the signal bar) as the backstop. A rule
  never moves the hard stop.
* **Mode (a)**: the pick's own take-profit stays (3R for 21 picks, 2R for core-S4_BB_BBP-30m-1, net ROE 50% for
  core-OBV_S-1h-3). **Mode (b)**: no take-profit and no lock, so the rule, the hard stop, liquidation or the period end
  closes the trade.
* Each rule is written below for a long. The short is mirrored: high and low swap, above and below swap, max and min
  swap.

### 5.2 Families (owners' words in brackets)

**F1 structure break** ["롱 구조가 무너지면"], swing width w in {2, 3, 5}, active in profit and in loss.
* Swing low at chart bar p: l[p] < l[q] strictly for every q != p in [p - w, p + w], known at the close of bar p + w (as
  in `kernel.structure_levels`).
* Reference at entry: the highest swing low below c[i0] among the swings at p in [i0 - 300, i0 - w]. This is the second
  output of `kernel.structure_levels(h, l, c, w, 300)` at i0. If there is none, there is no reference yet.
* Update at every pick-timeframe close i > i0: if bar p = i - w is a swing low, and either there is no reference or
  l[p] > reference, then reference = l[p]. The reference only moves up, so higher lows raise it. A swing low confirmed
  at i lies below c[i] by construction.
* Fires at a check close whose close (the pick's close, or the 15m close for q15) is < reference. With no reference,
  it does not fire. For q15 the reference is the one current at the latest pick-timeframe bar closed at or before that
  15m close.

**F2 moving-average break**, n in {10, 20, 50}.
* EMA(n) of the pick-timeframe closes: `fg_indicators.ema` (span n, adjust=False, min_periods n).
* Armed at entry when c[i0] > EMA[i0]. Otherwise it is armed from the first check close i > i0 with c[i] > EMA[i].
* Fires at a check close i when the rule was armed before i and c[i] < EMA[i].
* Why the arm: several picks buy below their average (dip entries). Without it, a long bought below its EMA would be
  closed at the first close by construction. That would be a one-bar exit, not the break of a rise.

**F3 opposite signal**.
* Fires at a pick-timeframe check close i > i0 when the pick's own signal of the opposite side is true on the same coin
  at bar i (its numbers, `run.signals`).
* The opposite signal is offered to the account like any other signal. Under section 4's order it can reverse the
  position.

**F4 chandelier trail**, m in {1.5, 2, 3}.
* Level = X - m x ATR14[i]. ATR14 is taken at the latest pick-timeframe bar i closed at or before the check close.
* Fires when the check close (the pick's close, or the 15m close for q15) < level. Active from the first check close.

**F5 profit giveback** ["+60%까지 갔다가 ... 빠르게 전량익절"], P in {20%, 40%, 60%} net ROE, g in {0.25, 0.5}.
* Armed from the first pick-timeframe check close with ROEpk >= P, and stays armed.
* Fires at a check close (the arming one included) when it is armed and ROEc <= (1 - g) x ROEpk.
* ROEpk uses the best price touched (5m extremes) after costs and funding, as the stepped lock does. ROEc uses the
  check close. Example: with P = 60% and g = 0.5, once the best price reached +60% net ROE, a close at or below +30%
  closes the position at the next open.

**F6 early loss cut** ["-40%까지 간 상황에서 ... 빠르게 전량 손절"], w in {2, 3, 5}, mode (a) only.
* F1's reference and break on the pick's timeframe, firing only when ROEc < 0 at that close. The take-profit stays.

**F7 time stop**, N in {12, 24, 48} chart bars.
* Fires at the first pick-timeframe check close at or after C0 + N x (timeframe length). Time is measured as time, so
  missing bins do not stretch it. Hold times are about N bars: on 15m 3, 6 or 12 h; on 30m 6, 12 or 24 h; on 1h 12, 24
  or 48 h; on 4h 2, 4 or 8 days.

### 5.3 The list (count)

| family | parameters | modes | variants |
|---|---|---|---|
| F1 | w = 2, 3, 5 | a, b | 6 |
| F1 q15 | w = 2, 3, 5 | a, b | 6 |
| F2 | n = 10, 20, 50 | a, b | 6 |
| F3 | none | a, b | 2 |
| F4 | m = 1.5, 2, 3 | a, b | 6 |
| F4 q15 | m = 1.5, 2, 3 | a, b | 6 |
| F5 | P = 20, 40, 60% x g = 0.25, 0.5 | a, b | 12 |
| F6 | w = 2, 3, 5 | a | 3 |
| F7 | N = 12, 24, 48 | a, b | 6 |
| **total** | | | **53** |

Plus the reference E0. Ids follow this pattern: `F1.w3.a`, `F1.w3.b.q15`, `F2.n20.b`, `F3.a`, `F4.m1.5.a`,
`F4.m2.b.q15`, `F5.P40.g50.a`, `F6.w2`, `F7.N24.b`. **Canonical order**, used for ties, tables and seeds: the table's
rows in order; inside a row, parameters ascending (F5 by P, then g), then mode a before b. **Parameter count**: the
numeric parameters plus one for q15. So F3 has 0; F1, F2, F4, F6 and F7 have 1; F1 q15, F4 q15 and F5 have 2. Modes
are not counted.

Runs: in select, E0 plus 53 variants x 23 picks x 2 sizes = 2,484 accounts, plus 53 x 23 x 200 = 243,800 placebo
accounts at quarter size. In confirm, at most (1 + 2) x 23 x 2 = 138 accounts plus 2 x 23 x 200 = 9,200 placebo
accounts.

### 5.4 Edge cases

1. **Gaps.** A rule exit fills at the open of bar j, whatever that price is. Steps 3-5 come first at that open. If the
   open is beyond the hard stop, the exit is the same price recorded as SL. Beyond liquidation on the mark, it is a
   liquidation. Beyond the take-profit, it is TP at the open, maker.
2. **Missing bars.** A chart bin with no 5m bar has no close and no check. Sometimes the first 5m bar at or after a
   check close opens after one or more further check closes. Then one check is made at that bar on the latest closed
   chart bar:
   * F1 and F6 update their reference with every bar in between;
   * F3 counts an opposite signal on any of those bars;
   * F5's X uses every 5m bar before j;
   * F7 uses time.
3. **A swing that does not exist yet.** F1 and F6 do nothing until a reference exists. The hard stop and, in mode (a),
   the take-profit keep working. An undefined EMA or ATR (NaN, impossible after the 300-bar warm-up with n <= 50) means
   no arm and no fire.
4. **A rule firing on the entry bar** cannot happen. The first check is the close after the signal bar (C0 + tf, or
   C0 + 15 min for q15), and a fill bar equal to the entry bar moves to the next bar. The signal bar's own close is
   never a check. Only F1's starting reference and F2's arm read it.
5. **Fills beyond the hard stop**: see 1. Between check closes the hard stop and the take-profit work on every 5m bar as
   in the kernel.
6. **Same-bar stop and rule.** The rule exit is at bar j's open, before j's range, so in bar j the rule comes before a
   stop or take-profit touched later in j. A stop or take-profit touched in an earlier 5m bar, before the check close,
   has already closed the position. At j's open the order is liquidation, stop gap, take-profit gap, then the rule
   (section 4).
7. **Funding at bar j** is paid by a position closed at j's open, because it was held over the funding instant (as in
   the kernel and PaperEngine).
8. **Long and short on one bar of one coin.** The long is taken first (the offered order). The short on that same bar
   is not an F3 trigger, because F3 reads bars after i0.
9. **After a bust** no signal is taken, as in the kernel.

## 6. Placebo

* For each variant V, pick p and period, from V's quarter-size account: h = (positions closed by the rule) / (check
  closes at which V's rule was evaluated while a position was open, the firing ones included). h = 0 when there is no
  such check.
* **Placebo account**: V's mode (the take-profit kept in (a), none in (b)), V's check closes (q15 included), and the
  same hard stop, sizing, period-end close and free fill bar. Instead of V's rule, it exits at a check close when
  u < h. The draw u depends only on (seed, coin, check close time):
  * base = `run._seed("exitflex", "placebo", pick id, V, period, s)`, s = 0 .. 199;
  * key = coin index x 2^36 + close ms // 60,000;
  * u = (splitmix64(splitmix64(base) XOR key) >> 11) / 2^53, with the standard splitmix64 constants.
* Placebo pooled mean for seed s = the mean over the 23 picks of the placebo's M_p: its monthly log growth minus E0's,
  computed as in section 7.
* What it separates: a rule that only shortens holds, and frees the account more often, should do no better than its
  placebo. A rule that reads the market should.

## 7. Metrics

* The wallet is realised at exits (no mark-to-market). W_0 = $5,000 at the period start. W_m is the wallet after every
  trade that exited before the end of UTC calendar month m. g_m = ln(W_m / W_(m-1)). After a bust, the later g_m are
  0.
* **Primary metric** for pick p, variant V and the period: **M_p(V) = the mean over the period's months of
  [g_m(V) - g_m(E0)] at quarter size**, which equals [ln W_end(V) - ln W_end(E0)] / months.
* Pooled: M(V) = the mean over the 23 picks of M_p(V). The monthly pooled difference is D_m(V) = the mean over the 23
  picks of [g_m(V) - g_m(E0)].
* Reported beside it, deciding nothing, per pick and pooled, for E0, V and the placebo median:
  * the same metric at live size;
  * trades entered (status 1) and trades closed;
  * signals skipped while a position was open (status 0) and signals rejected (status 2);
  * entries made at the open of a rule-exit bar;
  * exit reasons (TP, SL, RULE, LIQ, END);
  * median and 90th-percentile hold (hours from fill to exit), and the share of trades held more than 18 h;
  * win share (closed trades with a wallet change > 0);
  * the maximum drawdown of the wallet at closes, busts and the final wallet multiple;
  * the realised hazard h;
  * the placebo's 5th, 50th and 95th percentiles.

## 8. Selection rule (select period only)

* A variant V is **eligible** when all three hold:
  1. The median over the 23 picks of M_p(V) is > 0.
  2. M_p(V) > 0 on at least 14 of the 23 picks (60%).
  3. M(V) is above the 95th percentile (numpy's percentile, linear) of V's 200 placebo pooled means.
* **Chosen**: at most 2 eligible variants, those with the highest median. Ties go to fewer parameters, then to the
  canonical order. The rule is global: the chosen variant applies to all 23 picks. There is no per-pick, per-coin,
  per-timeframe or per-side choice.
* With no eligible variant the result is "none". The study ends there: nothing runs on the confirm period and nothing
  enters the ledger. The criteria are not relaxed and no variant is re-tuned on this result. A new idea is a new
  pre-registration with its own select step.
* The chosen ids and every select-period number go to `out/select.json`. Its sha256 is appended to
  `PREREG_EXITFLEX.sha256`, committed and pushed before the confirm run. The runner refuses the confirm stage without
  it.

## 9. Confirm rule (2024-01-01 .. 2026-10-01, once)

* The confirm run covers E0 and each chosen V on the 23 picks' accounts, at quarter size (deciding) and live size
  (reported), and V's placebo: 200 seeds, with the h that V realised in this period on each pick.
* Bootstrap: 2,000 resamples, with replacement, of the 33 calendar months of D_m(V). p = (1 + resamples with
  mean <= 0) / 2,001, seed `run._seed("exitflex", "confirm", V)`. Holm at 0.05 runs over the chosen variants. With one,
  p < 0.05. With two, the smaller p < 0.025 and then the larger p < 0.05.
* **PASS** for V needs all three:
  1. V is Holm-significant.
  2. M(V) is above the median of V's 200 confirm-period placebo pooled means.
  3. The trades entered over the 23 picks at quarter size are >= E0's.
* It runs once. A bug found afterwards is fixed and recorded in `DEVIATIONS.md`, the confirm is rerun once, and both
  results are shown. No other cut (a pick, a coin, a side, a year, a size) is a pass.

## 10. Ledger

* Each chosen V is one test-period hypothesis in the program-wide ledger (`research/hunt/PREREG_HUNT_WIDE.md` R13 and
  section 14: a global BH at q = 0.10 and Holm at 0.05 over every test-period hypothesis of the program, printed as
  `research/hunt_r2/PREREG_HUNT_R2.md` section 8 defines). It enters with its bootstrap p from section 9.
* From the hash of this file until the confirm runs, the ledger's print (L) counts this study at its maximum, 2
  hypotheses at p = 1. After the select step it counts the number chosen; with none chosen, it counts none.
* The ledger print appears beside this study's verdict and changes none of it. The verdict carries the line "this
  confirm uses the same 33 months as the full grid, the hunt (v1, wide, round 2) and track 2".

## 11. After

* **PASS**: once the owners say OK, each passing variant gets one new account per core pick in the 후보 리그:
  `<pick id>-f` (or `-f1` and `-f2` if two pass), labelled "같은 진입 · 유연한 청산". It uses the pick's numbers,
  signals and hard stop with the variant's exit, at live size like `cand`, starting from $5,000 at its own start.
  * Existing accounts (`cand`, `quarter`, `exitonly`, `base` and `flip` of all 38 picks) do not change. WATCH_PREREG's
    checks, pools and dates do not change, and the new accounts are not part of them.
  * The addition is recorded as a deviation in `research/fullgrid/DEVIATIONS.md` before it starts.
  * Before it starts, the league's engine gets the rule as a PaperEngine subclass in `candleague/exits.py`. It closes a
    rule exit before that step's entries. A test shows trade-for-trade parity with `kernel_x` on the same bars, as
    `tests/test_candleague_exits.py` does for the 84 exits. The league runs on 1m bars: the check closes are its chart
    closes, and the exit fills at the next 1m open.
  * The account's forward record counts from its own start. It is judged by CONTRACT.md section 2's per-account rule,
    and shown next to `cand`, which has the same entries.
* **FAIL or none**: the result is reported, in Korean for the owners, and not used. The league is unchanged.
* Real money is not decided by this study. That stays the owners' decision under the program's process.

## 12. What is not in scope, and known limits

* **Not in scope**:
  * a "판단" (judgement) exit by a person or an AI;
  * partial exits (the owners asked for 전량, the whole position);
  * combinations of two families;
  * moving the hard stop (breakeven or lock);
  * changes to entries, numbers, timeframes, leverage or size rules;
  * per-pick, per-coin, per-side or per-regime choices;
  * DeepSeek picks (D11);
  * the rule bot and the league's existing accounts;
  * the hunt's systems and other coins;
  * rule exits by maker limit orders.
* **Known limits**:
  1. **2024-2026 is not blind.** The 23 picks were chosen after the full grid's 2024-2026 results had been seen
     (WATCH_PREREG 0), and E0 is part of each pick. On the confirm period E0 carries that selection, which tilts the
     confirm against the variants. None of these rules has been computed on any period, so the confirm is a first look
     for them, but it is not a clean out-of-sample test. The clean check is the league's forward record after any new
     account starts.
  2. **The 2021-2023 data was used for both.** E0 was also chosen on 2021-2023 (the plateau rule), which tilts the
     select step against the variants. The best of 53 variants on 2021-2023 also looks better there than it is (the
     winner's curse). The single confirm and Holm address that.
  3. 5m bars instead of 1m bars (section 2).
  4. **Power is limited.** There are 33 months, and the 23 picks are correlated (the same six coins, related
     strategies). The pooled monthly series counts each month once, so a real but small gain may not pass.
  5. Quarter size decides. At live size a few busts can reverse the order, so live size is reported beside it.
  6. A rule exit pays taker fee plus slippage, while a fixed take-profit pays the maker fee. That favours E0 slightly,
     as it would live.
  7. Wallets are realised at exits, so a position held across a month end counts in the month it closes.

## 13. Reproducibility

* Code lives in `research/exitflex/`:
  * `data_x.py`: the 5m adapter from `hc.py`;
  * `kernel_x.py`;
  * `run_x.py`: the select, confirm and report stages;
  * `test_exitflex.py`.

  These are pinned in `PREREG_EXITFLEX.sha256` together with this file, `data_pin.json` and the sha256 of each input:

  | input | sha256 |
  |---|---|
  | `research/fullgrid/kernel.py` | `a4995c15…` |
  | `run.py` | `4e02df9c…` |
  | `sizing.py` | `3dc00c24…` |
  | `exchange.json` | `176e234b…` |
  | `diag/watch_sel.json` | `f6902feb…` |
  | `third_party/sweep/harness/vendor/fg_indicators.py` | `bf43c1b8…` |
  | the `param_defs` | `research/entry_study/DEFS_BC.sha256` |

  Repo HEAD when this file was written: `7f7991cb`. Versions: Python 3.11, numpy 2.0.2, pandas 2.3.3, numba 0.60.0.
  The runner records the versions it runs with.
* **Tests that must pass before any select run.** They print only pass or fail and counts, never a performance figure.
  * **T1 parity.** With no rule and the period end after the data end, `_trade_x` must equal `kernel._trade`: wallet
    change to 1e-9, exit index, reason and leverage. `account_x` must equal `kernel.account`: statuses, P&L, exit times,
    reasons, leverages and the final wallet. Test inputs:
    * synthetic 5m paths with gaps, missing bars, funding and a mark price that differs from the last price, all 84
      kernel exits, both sides, both leverage groups, at scales 0.25 and 1;
    * the replica's select-period signals of all 23 picks under E0 at both sizes.
  * **T2 rule paths.** Hand-built paths for every family, both sides, check that:
    * the rule fires at the right check close and not before;
    * the exit fills at the next 5m open with slippage and taker, and never on the entry bar;
    * F1's starting reference and its upward-only ratchet work;
    * F2's arm works;
    * F3's reversal entry happens;
    * F4's level is right;
    * F5's arm and giveback match a hand-computed ROE;
    * F6 fires only in loss;
    * F7's timing is right;
    * the q15 mapping works, with 15m and 30m picks equal to the base variant;
    * missing bars are handled;
    * a gap beyond the stop gives SL;
    * the take-profit gap comes first and liquidation first of all;
    * funding is paid at the exit bar;
    * END closes;
    * only RULE and RAND free the fill bar.
  * **T3 causality.** On the cut arrays of the select run and on the full arrays, these must agree on every bar closing
    before 2024-01-01, with swings as known at each bar:
    * every pick's signals and leverage groups;
    * ATR14 and EMA(10, 20, 50);
    * the swings (w = 2, 3, 5);
    * the 15m bars.

    Any difference stops the run.
  * **T4 placebo.** With h = 0 the result equals the mode's base account. With h = 1 the exit comes at the first check.
    The draws depend only on (seed, coin, time) and are reproducible.
* Seeds use `run._seed`: the first 8 hex digits of the sha256 of the "|"-joined parts.
* Order of work:
  1. Code, tests and `data_pin.json`, then the pin, commit and push.
  2. The select run writes `out/select.json`; its hash is appended, then commit and push.
  3. The confirm run, once, writes `out/confirm.json`, then `out/REPORT_KO.md` and the ledger print.

  The runner prints the git commit and refuses to run on a hash mismatch.

## 14. Before this file was fixed

* A sub-session drafted this file for the main session on 2026-10-12, before any exitflex code existed. It read code
  and pre-registration texts only:
  * `research/fullgrid/kernel.py`, `run.py` and `sizing.py`;
  * `PREREG.md`, `WATCH_PREREG.md` and `DEVIATIONS.md` of the full grid;
  * `candleague/CONTRACT.md` and the header of `candleague/exits.py`;
  * the step order of `paperbot/engine.py`;
  * the ledger passages of `research/hunt/PREREG_HUNT_WIDE.md` and `research/hunt_r2/PREREG_HUNT_R2.md` section 8;
  * the beginnings of `research/exitstyle` and `research/levstop`'s pre-registrations;
  * the source code of `hc.py`;
  * the names, timeframes and exits of the core rows of `watch_sel.json`;
  * the first and last bar dates and the gap counts of the six replica coins.

  It opened no P&L, win share, account result, hold time or other performance figure of any period. It did not open
  `hc.py`'s outputs or the league's trades.
* No number of any of the 53 variants, or of E0 run through this kernel, exists anywhere when this is written.
* What the owners and the main session had seen:
  * the full grid's per-trade results of the 84 exits on 2021-2023, 2024-2026 and 2020 (`ANALYSIS_KO.md`,
    `STRATEGIES_KO.md`, `STRATEGY_EVAL_KO.md`);
  * the league's live record from 2026-10-11, including the SOL trade that prompted this request;
  * whatever results of the hunt program (whose systems exit on a chandelier trail, on other entries) and of the
    hold-cost replica (`hc.py`, select period only) had been read.

  **[To be completed by the main session before the hash: the hc.py outputs and hunt results it had read, by file and
  date, or "none".]**
* **Definitions added while writing**, beyond the main session's design defaults 1-9, which are kept:
  1. Every signal is offered to the account, not only those sized at $5,000 (section 3).
  2. Positions are closed at the period end (END), so the select step reads no 2024 bar. The select run uses arrays cut
     at 2024-01-01 and test T3 checks it.
  3. Rule and placebo exits free their fill bar, so F3 can reverse (section 4).
  4. F1's starting reference is `kernel.structure_levels` at the signal bar, and it only moves up (section 5.2).
  5. F2 has an arm (section 5.2).
  6. F5's peak is the kernel's best ROE from 5m extremes after costs and funding, and its current value is the check
     close.
  7. q15 means 15m triggers against the pick's timeframe levels, and equals the base variant on 15m and 30m picks.
  8. F7 is measured in time.
  9. The placebo's hazard (rule exits over checks while a position is open) and its draw are defined in section 6.
  10. Ties use the parameter count and the canonical order.
  11. Rule decisions use only bars before the fill bar.
