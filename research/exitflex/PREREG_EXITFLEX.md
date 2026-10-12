# Flexible exits for the 23 core watch picks: pre-registration (exitflex v1)

(한국어 요약: `README_KO.md`.) This file is fixed before this study's own runs produce any number. It is pinned by
`PREREG_EXITFLEX.sha256` together with the code and inputs of section 13. Changes after the pin go to `DEVIATIONS.md`
in this folder, dated and with the reason, never into this file. Related select-period numbers from the hold-cost
replica may already have been seen by the main session; section 15 lists them and says what follows. Section 16 lists
what changed from the first draft and from the main session's design defaults, and why.

First draft 2026-10-12 01:41 UTC; revised 2026-10-12 (UTC) after two design reviews. Owners' request, about the 후보 리그
("커스텀값 봇"), where a SOL long had been held about 18 h at +43% ROE under a fixed 3R take-profit and a 4 ATR stop:
"익절구조를 과거 백테스트를 돌려서 좋게 잡은건 좋은데 포지션 보유시간이 길어지면 진입횟수에도 영향을 끼치잖아 ... 18시간씩
보유하고있으면 솔직히 좀 그래 예를들어 롱을 잡아서 +60%까지 갔다가 롱구조가 무너지거나 더이상 안오를꺼 같으면 빠르게
전량익절을 한다던지 ... 반대로 손절 부분도 마찬가지고 만약 손절을 -60%로 잡아놨고 롱을 잡아놨었는데 롱 구조가 무너지고
-40%까지 간상황에서 더 떨어질꺼 같은 판단이 들고 롱 구조가 무너졌다고 생각이되면 원래 손절가가 -60%지만 ... 빠르게 전량
손절을 한다던지". Earlier the same day: "유도리있게 나는 그런식으로 가고싶은데", "지금 나와 친구는 빠르게 매매법을
완성을 시켜서 성공을 시켜야하는데".

## 1. Questions

The 23 core picks keep their entries. Only the exit changes. The account holds one position at a time over six coins,
so a signal that arrives while a position is open is lost. The full-grid study never counted those lost signals: it
judged exits by the mean per-trade P&L with every signal counted (PREREG.md 5-6). None of its 84 exits leaves on a
structure break, an opposite signal, a time limit, a chandelier trail or a profit giveback, and none cuts a loss before
the hard stop.

* **Q-A (the owners' question).** If the account leaves earlier, and so is free for more of the pick's signals, does it
  grow faster per month than with the pick's current exit (E0)? The time stop F7 tests this directly: it reads only
  the clock. The random exits of section 6 are also reported against E0 as a second, descriptive answer.
* **Q-B.** Does an exit that reads the market do better than E0, and also better than a random exit with the same
  timing profile (section 6)? These exits are a structure break, a moving-average break, the opposite signal, a
  chandelier trail, a profit giveback, an early loss cut, a structure break after a gain, the owners' two-sided rule
  and a stall. Only a Q-B variant that beats its random exit may be described as reading the market. A passing F7
  shows only that shorter holds pay.

## 2. Data

* **Source**: Binance USD-M public archive (data.binance.vision). Files: 1m klines (last price), 1m mark-price klines and
  funding-rate history for BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT, LTCUSDT and BCHUSDT, months 2020-01 to 2026-09. These are
  the full-grid study's own 1m arrays, built by `research/fullgrid/data.py` (sha256 `6691424b…`, `build` step). Local
  copy: `fg1m/1m/<SYM>.npz` in the main session's scratchpad
  (`/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/fg1m`). Its build
  report `fg1m/build.json` (sha256 `824c9d1a…`) lists each coin file's sha256: BTC `cdb50d97…`, ETH `270ad01f…`, SOL
  `994e424a…`, DOGE `a92ff7d6…`, LTC `9b10e25e…`, BCH `fd6f2d41…`.
  * Before the select run these seven hashes are written to `research/exitflex/data_pin.json` and pinned (section 13).
    The runner refuses any other file.
  * `python3 research/fullgrid/data.py all --dir DIR` rebuilds the files from checksummed archive zips; the pin decides
    whether a rebuild is the same data.
* **First minutes**: BTC, ETH and BCH 2020-01-01 00:00, LTC 2020-01-09 08:09, DOGE 2020-07-10 09:00, SOL 2020-09-14
  07:00. The last minute of every coin opens 2026-09-30 23:59 UTC.
* **Loading** is `data.load`, unchanged (the "1m" path of the hold-cost replica `hc.py`, close shift 0). As `data.py`
  builds them:
  * zero-volume minutes are dropped;
  * a minute without a mark price takes the last-price bar;
  * each funding settlement is paid at the open of the minute of its calc time, or of the next minute present.
* **Chart bars** (15m, 30m, 1h, 4h) are UTC bins of the 1m bars, built by `run.build_frame` unchanged. A bin with minutes
  missing inside is kept as built. A bin with no minute does not exist.
* **Periods** are set by the signal bar's close (UTC). **Select**: [2021-01-01, 2024-01-01), 36 calendar months.
  **Confirm**: [2024-01-01, 2026-10-01), 33 months. A coin's first 300 chart bars are warm-up only (`run.period_ids`).
* **The select cut.** The select run loads the 1m arrays cut at 2024-01-01 00:00 UTC (minutes that open before it),
  writes them as their own data folder (section 13, caches) and builds every chart bar and indicator from them. No
  price, mark or funding bar from 2024-01-01 on enters any select-period number. Two static inputs are not price bars
  and are not cut: `paperbot/quality_edges.json` and `research/fullgrid/exchange.json` (Known limit 3). The confirm
  run loads the full arrays.
* **Bars and the stop-first rule.** The study, the league and this study all step on 1m bars. The order of high and
  low inside one minute is unknown, so a minute that touches both the stop and the take-profit counts as a stop (the
  kernel's rule). This rule only affects arms that have a take-profit: E0 and mode (a). It never affects mode (b).
  The number of such minutes is reported per arm (section 7). Rule exits happen at minute opens and do not depend on it.

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
* **Fill**: `kernel._entry_index(ts, close)` on the 1m bars, unchanged. That is the open of the minute that opens at the
  signal bar's close, or one minute later when the bin's last minute is missing (the study's and the league's rule),
  plus 0.02% slippage.
* **Offered signals**: every long and short signal of the period whose ATR14 is finite and > 0 and whose fill minute
  opens before the period's last minute.
  * They are sorted by (fill time, coin priority BTC, ETH, SOL, DOGE, LTC, BCH).
  * When both sides are true on one bar of one coin, both are offered, the long first (`run.per_trade` order, stable
    sort). The league's `chunk_signals` sends only the long in that case; the new league accounts of section 11 must
    follow this file instead.
  * The account sizes each signal at its own wallet and rejects a signal that no size fits, as the league's
    PaperEngine does. (`run.account_run` offered only the signals that live sizing could size at $5,000. Here every
    exit and every size gets the same offer.)
* Entries are therefore identical for E0 and every variant: the same signals in the same order, the same hard stop and
  the same sizing rule. What differs is what happens after the fill, and so which later signals find the account
  free.

## 4. Engine

* A new numba kernel, `research/exitflex/kernel_x.py` (`_trade_x`, `account_x`), copies `kernel._trade` and
  `kernel.account` (`research/fullgrid/kernel.py`, sha256 `a4995c15…`). It adds four things:
  * a rule check at check closes (section 5);
  * a placebo check (section 6);
  * a forced close at the period end;
  * a free fill minute after a rule or placebo exit (below).

  It takes the bar length as a parameter (close shift = 60,000 - bar_ms ms, as `hc.py`); this study runs it with 1m bars
  only (shift 0). With no rule, no placebo and the period end after the data end, it must reproduce the kernel exactly
  (test T1, section 13).
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
  * raw = the fill minute's open; fill = raw x (1 + side x 0.0002).
  * **R** = k x ATR14 of the signal bar, where k is the pick's stop.
  * Hard stop = raw - side x R. It never moves.
  * Take-profit at m R: raw + side x m x R.
  * Take-profit at net ROE v: fill x (1 + side x (v / lev + rt)), with rt = 0.0014 (`S[5]`, the round trip of taker
    plus slippage).
  * f = F / (qty x fill), the funding paid so far per unit of notional.
  * **Net ROE** at price P: ROE(P) = lev x (side x (P / fill - 1) - rt - f). This is the kernel's own best-ROE formula
    from the stepped lock.
  * **Net R** at price P: Rn(P) = (side x (P - fill) - fill x (rt + f)) / R. Net ROE = Rn x lev x R / fill, so Rn has
    the same sign as net ROE but does not depend on size or leverage. Rn at the hard stop is about -1. Example: when the
    hard stop is a -60% net ROE loss, +1R is about +60% net ROE.
  * Entry fee: qty x fill x taker. An exit at price X adds side x qty x (X - fill) - qty x X x fee to the wallet. The
    fee is maker at a take-profit limit and taker otherwise. A loss beyond the margin is a liquidation, and the margin
    is lost.
* **Inside one minute j after the entry minute e** (the kernel's order, with the new steps 0 and 6):
  0. **New: decision.** If a check is due at j (section 5.1), the rule decision and the placebo decision are computed
     here, from state frozen at the end of minute j - 1: the favourable extreme X and its time T_X over minutes
     e .. j - 1, the funding paid on minutes before j, and chart data closed at or before the check close. Nothing of
     minute j (its funding, open, high, low or mark) enters the decision.
  1. Funding settled at j's open on the mark open; the liquidation price is recomputed.
  2. The favourable extreme is updated with j's high (long) or low (short). This update is used only by decisions at
     later minutes and by the stepped lock.
  3. A mark open beyond liquidation: liquidation (LIQ).
  4. An open beyond the hard stop: exit at the open with slippage, taker (SL).
  5. An open beyond the take-profit: exit at the open, maker (TP).
  6. **New: execution.** If the position is still open and step 0 decided to exit, it exits at j's open with slippage
     and taker: RULE for a rule exit, RAND for a placebo exit. A forced period-end close due at j does the same (END).
  7. The minute's range. A low (long) or high (short) through the stop exits at the stop with slippage (SL). Otherwise a
     mark low or high through liquidation liquidates. Otherwise a range through the take-profit exits at the
     take-profit, maker (TP). The stepped lock, which no pick uses, is unchanged.

  The entry minute e gets the range checks for stop, liquidation and take-profit only: no gap check, no decision and no
  lock, as in the kernel. X starts at the fill price and includes minute e's high (long) or low (short), as the
  kernel's `mfe`.
* **Account** (as `kernel.account`): one position at a time over the six coins, with signals taken in the offered
  order.
  * A signal whose fill time is not after the open position's exit time is skipped.
  * Ties at one fill time go to coin priority, then long before short.
  * A rejected signal does not block. A bust below $10 ends the account.
  * **Addition: after a RULE or RAND exit at minute j, the account is free for signals that fill at the open of the same
    minute j** (exit first, then entries; in kernel terms busy_until = exit time - 1 ms). After any other exit the
    kernel's rule stands, including an SL, TP or LIQ at j's open when a rule was due at j.
  * The reason: a rule exit is decided at the check close, before that minute opens, so a bot can close and open at
    that open. An intrabar stop or take-profit happens after that open, while the old position still held the account.
  * Under F3 this means that the opposite signal which closed the position is entered at the same open when it ranks
    first and can be sized (a reversal). Entries and rule exits use the same helper (section 5.1), so they land on the
    same minute.
* **Period end**: a position still open at the open of the period's last minute is closed at that open, after steps
  1-5, with slippage and taker fee (END). The last minute is the coin's last minute opening before the period end:
  2023-12-31 23:59 or 2026-09-30 23:59 UTC when present. This applies to E0 and every variant alike. The study's
  account let such positions run on; here no bar after the period is read. A rule exit and END due at the same minute
  give the same price and are recorded as RULE.
* **E0**, the reference, is each pick's own exit (its take-profit and its k x ATR14 stop) through `kernel_x` with no
  rule.

## 5. Variants

### 5.1 Common to every variant

* **Check closes**: the closes of the pick's chart bars after the signal bar i0 (C0 + tf, C0 + 2 tf, ..., where C0 is
  i0's close).
  * Variants marked **q15** check on 15m closes after C0 for picks on 1h and 4h. They use 15m UTC bins of the 1m bars,
    and their levels still come from the pick's timeframe (5.2).
  * On picks of 15m and 30m a q15 variant checks on the pick's own closes and equals its base variant.
* **The check's minute**: a check at close C acts at minute j = `kernel._entry_index(ts, C)`, the same helper (and the
  same shift) that places entry fills. If j <= e, then j = e + 1. Several check closes that map to one minute j (minutes
  missing) make one check there, on the latest closed chart bar (5.4.2).
* **Check index k**: the first check made after the signal bar has k = 1, the next k = 2, and so on. A merged check
  counts once.
* At a check a rule may use only:
  * the chart bars closed at or before C: their OHLC, ATR14, EMA, the swings confirmed by then and the pick's signals
    of both sides;
  * X, the favourable extreme over minutes e .. j - 1 (the highest high since the fill for a long, the lowest low for a
    short), and T_X, the open time of the last minute in e .. j - 1 that raised X (the fill time when none did);
  * the funding paid on minutes before j.
* **Rc** = Rn at the check's chart close; **Rpk** = Rn(X). Prices are last prices, not mark prices, as in the study's
  signals and ATR.
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
  at bar i (its numbers, `run.signals`, the raw flag). It fires even when the same side's flag is also true at i.
* The opposite signal is offered to the account like any other signal. Under section 4's order it can reverse the
  position. When both flags are true at i, that bar's long is offered first (5.4.8).

**F4 chandelier trail**, m in {1.5, 2, 3}.
* Level = X - m x ATR14[i]. ATR14 is taken at the latest pick-timeframe bar i closed at or before the check close.
* Fires when the check close (the pick's close, or the 15m close for q15) < level. Active from the first check close.

**F5 profit giveback** ["+60%까지 갔다가 ... 빠르게 전량익절"], P in {1, 1.5, 2} R, g in {0.25, 0.5}.
* Armed from the first pick-timeframe check close with Rpk >= P, and stays armed.
* Fires at a check close (the arming one included) when it is armed and Rc <= (1 - g) x Rpk.
* Rpk uses the best price touched (1m extremes) after costs and funding, as the stepped lock does. Rc uses the check
  close. In net ROE the giveback fraction is the same (both sides scale by lev x R / fill). Example: with a -60% ROE
  stop, P = 1 and g = 0.5, once the best price reached about +60% net ROE, a close at or below about +30% closes the
  position at the next open.

**F6 early loss cut** ["-40%까지 간 상황에서 ... 빠르게 전량 손절"], w in {2, 3, 5}, loss depth d in {0, 0.5} R, mode (a)
only.
* F1's reference and break on the pick's timeframe, firing only when Rc < -d. The take-profit stays.
* d = 0 means any net loss after costs. At 50x the round-trip costs alone are about 7 points of ROE, so d = 0 can fire
  close to the entry price. d = 0.5 needs at least half the hard-stop distance in loss. The owners' example (-40% on a
  -60% stop) is about -0.67R.

**F7 time stop**, N in {12, 24, 48} chart bars.
* Fires at the first pick-timeframe check close at or after C0 + N x (timeframe length). Time is measured as time, so
  missing bins do not stretch it. Hold times are about N bars: on 15m 3, 6 or 12 h; on 30m 6, 12 or 24 h; on 1h 12, 24
  or 48 h; on 4h 2, 4 or 8 days.
* F7 has no placebo (section 6). It answers Q-A only.

**F8 structure break after a gain** ["+60%까지 갔다가 롱구조가 무너지거나"], w in {2, 3, 5}, P in {1, 2} R.
* Armed from the first pick-timeframe check close with Rpk >= P, and stays armed.
* Fires at a check close when it is armed and the close is < F1's reference (same reference, same update).

**F9 the owners' two-sided rule**, fixed w = 3, P = 1 R, d = 0.5 R; modes (a) and (b), and q15 in both modes.
* Fires at a check close when F8 (w = 3, P = 1) fires or F6 (w = 3, d = 0.5) fires.
* That is: after a gain of about the stop distance, close everything when the structure breaks; while at least half the
  stop distance in loss, close everything when the structure breaks.
* The q15 version makes all of these tests at 15m closes (the arm, the loss test and the break), against the
  pick-timeframe reference.

**F10 stall** ["더이상 안오를꺼 같으면"], N in {6, 12} pick bars.
* Fires at a pick-timeframe check close C when Rc > 0 and C - T_X >= N x (timeframe length): the trade is in profit and
  no minute has made a new favourable extreme for N bars.

### 5.3 The list (count)

| family | group | parameters | modes | variants |
|---|---|---|---|---|
| F1 | S | w = 2, 3, 5 | a, b | 6 |
| F1 q15 | S | w = 2, 3, 5 | a, b | 6 |
| F2 | M | n = 10, 20, 50 | a, b | 6 |
| F3 | O | none | a, b | 2 |
| F4 | C | m = 1.5, 2, 3 | a, b | 6 |
| F4 q15 | C | m = 1.5, 2, 3 | a, b | 6 |
| F5 | G | P = 1, 1.5, 2 x g = 0.25, 0.5 | a, b | 12 |
| F6 | S | w = 2, 3, 5 x d = 0, 0.5 | a | 6 |
| F7 | T | N = 12, 24, 48 | a, b | 6 |
| F8 | S | w = 2, 3, 5 x P = 1, 2 | a, b | 12 |
| F9 | S | fixed | a, b | 2 |
| F9 q15 | S | fixed | a, b | 2 |
| F10 | L | N = 6, 12 | a, b | 4 |
| **total** | | | | **76** |

Plus the reference E0.

* **Ids**: `F1.w3.a`, `F1.w3.b.q15`, `F2.n20.b`, `F3.a`, `F4.m1.5.a`, `F4.m2.b.q15`, `F5.P1.5.g25.a`, `F6.w2.d0`,
  `F6.w2.d0.5`, `F7.N24.b`, `F8.w3.P1.a`, `F9.a`, `F9.b.q15`, `F10.N6.a`.
* **Groups** (used in section 8 so that the two chosen variants are not near copies):
  * S, structure: F1, F1 q15, F6, F8, F9, F9 q15;
  * M, moving average: F2;
  * O, opposite signal: F3;
  * C, chandelier: F4, F4 q15;
  * G, giveback: F5;
  * T, time: F7;
  * L, stall: F10.
* **Canonical order**, used for ties, tables and seeds: the table's rows in order. Inside a row, parameters ascending in
  the order written (F5 by P then g, F6 by w then d, F8 by w then P), then mode a before b.
* **Parameter count**: the numeric parameters plus one for q15. Modes are not counted.
  * 0: F3.
  * 1: F1, F2, F4, F7, F10.
  * 2: F1 q15, F4 q15, F5, F6, F8.
  * 3: F9. 4: F9 q15.
* **Runs**:
  * Select: E0 plus 76 variants, x 23 picks x 2 sizes = 3,542 accounts. Placebos for the 70 variants outside F7:
    70 x 23 x 200 = 322,000 accounts at quarter size.
  * Confirm: at most (1 + 2) x 23 x 2 = 138 accounts, plus at most 2 x 23 x 200 = 9,200 placebo accounts.
  * Compute: everything runs on 1m bars. Before the select run, the runner times E0 and one placebo seed of `F1.w3.a`,
    `F5.P1.g50.b` and `F9.a` on 3 picks, and writes only times. If the projected wall time of the select placebos
    exceeds 48 h on the machine used, the select placebos drop from 200 seeds to 100 (the 95th percentile then comes
    from 100 pooled means). This is recorded in `DEVIATIONS.md` before the select run. The confirm keeps 200 seeds.

### 5.4 Edge cases

1. **Gaps.** A rule exit fills at the open of minute j, whatever that price is. Steps 3-5 come first at that open.
   * If the open is beyond the hard stop, the exit is recorded as SL. Beyond liquidation on the mark, it is LIQ. Beyond
     the take-profit, it is TP at the open, maker.
   * In these three cases minute j is not freed for entries (section 4), and the check counts in neither the numerator
     nor the denominator of the placebo hazard (section 6).
2. **Missing minutes.** A chart bin with no minute has no close and no check. When the minute of one check close comes
   after one or more further check closes, one check is made at that minute on the latest closed chart bar:
   * F1, F6, F8 and F9 update their reference with every bar in between;
   * F2's arm reads every bar in between;
   * F3 counts an opposite signal on any of those bars;
   * F4, F5 and F10 use X and T_X over every minute before j;
   * F7 uses time.
3. **A swing that does not exist yet.** F1, F6, F8 and F9 do nothing until a reference exists. The hard stop and, in mode
   (a), the take-profit keep working. An undefined EMA or ATR (NaN, impossible after the 300-bar warm-up with n <= 50)
   means no arm and no fire.
4. **A rule firing on the entry minute** cannot happen. The first check is the close after the signal bar (C0 + tf, or
   C0 + 15 min for q15), and a check minute at or before the entry minute moves to e + 1. The signal bar's own close is
   never a check. Only F1's starting reference and F2's arm read it.
5. **Fills beyond the hard stop**: see 1. Between checks the hard stop and the take-profit work on every minute as in
   the kernel.
6. **Same-minute stop and rule.** The rule exit is at minute j's open, before j's range, so in minute j the rule comes
   before a stop or take-profit touched later in j. A stop or take-profit touched in an earlier minute, before the check
   close, has already closed the position. At j's open the order is liquidation, stop gap, take-profit gap, then the
   rule (section 4).
7. **Funding at minute j** is paid by a position closed at j's open, because it was held over the funding instant (as in
   the kernel and PaperEngine). It is not part of the decision at j (step 0).
8. **Long and short on one bar of one coin.**
   * At entry the long is taken first (the offered order). The short on that same bar is not an F3 trigger for it,
     because F3 reads bars after i0.
   * At a later bar i with both flags true while a long is open, F3 fires (the short flag is true). After the exit,
     that bar's long is offered before its short, so the account re-enters long when the long can be sized: no
     reversal. While a short is open, the long flag fires F3 and the long is offered first: a reversal.
9. **After a bust** no signal is taken, as in the kernel.

## 6. Placebo

* **Purpose.** A rule that only shortens holds frees the account more often. A random exit with the same timing profile
  shortens holds in the same way. A Q-B rule must beat it to be described as reading the market. F7 has no placebo: it
  reads nothing by design, and a placebo with its timing profile would be F7 itself.
* **State at a check.** For a variant V and an open position at a check of V's schedule, the stratum is (a, s, z):
  * a, the age bucket of the check index k: {1}, {2}, {3-4}, {5-8}, {9-16}, {17-32}, {33-64}, {65 and more};
  * s = 1 when Rc >= 0, else 0;
  * z, V's precondition, computed on the position at hand:
    * F1, F1 q15, F6: a reference exists;
    * F2: armed;
    * F5, F8: armed (Rpk has reached P at a check);
    * F9, F9 q15: armed (Rpk has reached 1R at a check); the loss side is matched by s;
    * F3, F4, F4 q15, F10: z = 0 always.

  All of it uses the frozen state of step 0, so the placebo, like the rule, sees nothing of minute j.
* **Hazard.** For each variant V, pick p and period, from V's quarter-size account:
  h[a, s, z] = (exits recorded RULE at checks of stratum (a, s, z)) / (checks of stratum (a, s, z) at which a
  position was still open after steps 1-5 of the check's minute).
  * The denominator counts every check of V's schedule, armed or not, with a merged check counted once.
  * The numerator counts RULE exits, the RULE + END case included.
  * A check whose minute's open closed the position (LIQ, SL or TP at steps 3-5) counts in neither.
  * h = 0 where the denominator is 0.
* **Placebo account**: V's mode (the take-profit kept in (a), none in (b)), V's check schedule (q15 included), and the
  same hard stop, sizing, period-end close and free fill minute. Instead of V's rule, at each check it computes its
  own position's stratum and exits when u < h[a, s, z] (RAND). The draw u depends only on (seed, coin, check close
  time):
  * base = `run._seed("exitflex", "placebo", pick id, V, period, s)`, s = 0 .. 199;
  * key = coin index x 2^36 + close ms // 60,000;
  * u = (splitmix64(splitmix64(base) XOR key) >> 11) / 2^53, with the standard splitmix64 constants.
* **Placebo pooled mean** for seed s = the mean over the 23 picks of the placebo's M_p: its monthly log growth minus
  E0's, computed as in section 7.
* What it separates: a rule whose gain comes only from leaving at that age, in that profit state and after that
  precondition, should do no better than its placebo. A rule whose exit times carry information should. The match is
  on these three things only (Known limit 9).

## 7. Metrics

* The wallet is realised at exits (no mark-to-market). W_0 = $5,000 at the period start. W_m is the wallet after every
  trade that exited before the end of UTC calendar month m. g_m = ln(W_m / W_(m-1)). After a bust, the later g_m are
  0. The same rule holds for placebo accounts.
* **Primary metric** for pick p, variant V and the period: **M_p(V) = the mean over the period's months of
  [g_m(V) - g_m(E0)] at quarter size**, which equals [ln W_end(V) - ln W_end(E0)] / months. A pick with no offered
  signal in the period has M_p = 0.
* Pooled: M(V) = the mean over the 23 picks of M_p(V). The monthly pooled difference is D_m(V) = the mean over the 23
  picks of [g_m(V) - g_m(E0)]; M(V) is the mean of D_m(V) over the months.
* Reported beside it, deciding nothing, per pick and pooled, for E0, V and the placebo median:
  * the same metric at live size, and busts at live size;
  * trades entered (status 1) and trades closed;
  * signals skipped while a position was open (status 0) and signals rejected (status 2);
  * trades changed: V's trades with no E0 trade of the same (coin, side, fill minute, exit minute, exit reason),
    count and share;
  * entries made at the open of a rule-exit minute;
  * exit reasons (TP, SL, RULE, RAND, LIQ, END);
  * median and 90th-percentile hold (hours from fill to exit), and the share of trades held more than 18 h;
  * win share (closed trades with a wallet change > 0);
  * the maximum drawdown of the wallet at closes, busts and the final wallet multiple;
  * the minutes where the stop and the take-profit were both touched (decided stop-first), per arm;
  * the realised hazard table h;
  * the placebo's 5th, 50th and 95th percentiles.
* **Q-A, descriptive**: for every variant outside F7, the placebo's median pooled mean against E0 and the share of its
  seeds with a pooled mean > 0. This says whether leaving at random, with V's timing profile, beat E0.

## 8. Selection rule (select period only)

* A variant V is **eligible** when all of these hold:
  1. M(V) > 0.
  2. M_p(V) > 0 on at least 14 of the 23 picks (60%). A pick with no signal, or where V changed no trade, has
     M_p = 0 and does not count.
  3. Except F7: M(V) is above the 95th percentile (numpy's percentile, linear) of V's 200 placebo pooled means.
  4. The trades entered at quarter size, summed over the 23 picks, are >= E0's.
* **Chosen**: at most 2 eligible variants, in this order:
  1. the eligible variant with the highest median over the 23 picks of M_p(V);
  2. the eligible variant with the highest median from a different group (5.3).

  Ties go to fewer parameters, then to the canonical order. The rule is global: a chosen variant applies to all 23
  picks. There is no per-pick, per-coin, per-timeframe or per-side choice.
* **What a chosen variant may claim**, written into `select.json` and the Korean report:
  * outside F7: "beats E0 and beats a random exit with its timing profile";
  * F7: "beats E0 by holding less; no claim about reading the market".
* With no eligible variant the result is "none". The study ends there: nothing runs on the confirm period and nothing
  enters the ledger. The criteria are not relaxed and no variant is re-tuned on this result. A new idea is a new
  pre-registration with its own select step. The Q-A table is still reported.
* The chosen ids and every select-period number go to `out/select.json`. Its sha256 is appended to
  `PREREG_EXITFLEX.sha256`, committed and pushed before the confirm run. The runner refuses the confirm stage without
  it. A select rerun is possible only under section 14.

## 9. Confirm rule (2024-01-01 .. 2026-10-01, once)

* The confirm run covers E0 and each chosen V on the 23 picks' accounts, at quarter size (deciding) and live size
  (reported). For a chosen V outside F7 it also runs V's placebo: 200 seeds, with the hazard table that V realised in
  this period on each pick.
* **Test**: a one-sided circular moving-block bootstrap of the 33 monthly D_m(V), blocks of 3 consecutive calendar
  months, 2,000 resamples, seed `run._seed("exitflex", "confirm", V)`. p = (1 + resamples with mean <= 0) / 2,001.
  Holm at 0.05 runs over the chosen variants: with one, p < 0.05; with two, the smaller p < 0.025 and then the larger
  p < 0.05.
* Reported beside it, deciding nothing: the iid bootstrap p of the same series, and a 95% percentile interval for M(V)
  from the block bootstrap.
* **PASS** for V needs all three:
  1. V is Holm-significant.
  2. Except F7: M(V) is above the 95th percentile of V's 200 confirm-period placebo pooled means.
  3. The trades entered over the 23 picks at quarter size are >= E0's.
* A PASS carries the claim of section 8 and nothing more.
* A FAIL means this test did not show a gain. It does not show that there is none. The Korean report says so and gives
  the 95% interval.
* Q-A on confirm, descriptive and outside the ledger: for each chosen V outside F7, the placebo's median pooled mean
  against E0, with the block-bootstrap p of the placebo's seed-mean D_m.
* It runs once. Bugs are handled by section 14. No other cut (a pick, a coin, a side, a year, a size) is a pass.

## 10. Ledger

* Each chosen V is one test-period hypothesis in the program-wide ledger (`research/hunt/PREREG_HUNT_WIDE.md` R13 and
  section 14: a global BH at q = 0.10 and Holm at 0.05 over every test-period hypothesis of the program, printed as
  `research/hunt_r2/PREREG_HUNT_R2.md` section 8 defines). It enters with its block-bootstrap p from section 9.
* From the hash of this file until the confirm runs, the ledger's print counts this study at its maximum, 2
  hypotheses at p = 1. After the select step it counts the number chosen; with none chosen, it counts none. A confirm
  rerun under section 14 adds its p values as further looks.
* The Korean report's headline shows, next to PASS or FAIL, the ledger status of each chosen V (BH at q = 0.10 over the
  program). The ledger print changes no verdict of this study. The verdict carries the line "this confirm uses the same
  33 months as the full grid, the hunt (v1, wide, round 2) and track 2".

## 11. After

* **PASS**: once the owners say OK, the passing variants get new league accounts. The addition is recorded as a
  deviation in `research/fullgrid/DEVIATIONS.md` before it starts.
* **New accounts, per core pick**:
  * `<pick id>-f` (or `-f1` and `-f2` if two pass), labelled "같은 진입 · 유연한 청산": the pick's numbers, signals and
    hard stop with the variant's exit, at **quarter size** (every margin fraction x 1/4, leverages kept, as the league's
    `quarter` accounts). Quarter size decided the study, so it is the size that is judged.
  * `<pick id>-f0`: E0 at quarter size, started at the same moment in the same database. It is the same-day twin that
    `-f` is judged against. The existing `-q` account started 2026-10-01 and may be holding a position, so it is not a
    fair twin.
  * All start from $5,000 at the first chart close after the install.
* **Existing accounts** (`cand`, `quarter`, `exitonly`, `base` and `flip` of all 38 picks) do not change.
  WATCH_PREREG's checks, pools and dates do not change, and the new accounts are not part of them.
* **League changes, named before any code is written:**
  1. The new accounts run in their own league database: a second `League` with its own `meta.start_ms` (the install
     time) and its own fingerprint. Adding them neither resets nor replays the existing record, because
     `runner.fingerprint` covers every account of one database.
  2. Per-close rule inputs: for every rule account, the runner hands the engine every chart close of the held coin
     (close, ATR14, EMA(n), swing confirmations, both raw signal flags), plus the 15m closes for q15. Today
     `league.chunk_signals` sends only bars that carry a signal.
  3. Both sides are offered when both flags are true, long first, as in section 3.
  4. Step order: a PaperEngine subclass in `candleague/exits.py` overrides `step`:
     * funding;
     * if a rule exit is due at this minute and the open gaps past neither liquidation, the stop nor the take-profit,
       close as RULE;
     * then entries (`_handle_entries`);
     * then `_handle_exit`.

     A gapped open leaves the exit to `_handle_exit`, so entries at that minute stay blocked, as in `kernel_x`.
  5. Rule state (F1 reference, F2 arm, F5 and F8 arms, F7 deadline, X and T_X) is kept in the position's signal meta.
     `engine_state` and `restore_engine` save and restore it, and a restore checks it against a recomputation from
     the bars.
  6. End-to-end parity test, before the start: `League.advance` and `paramshadow.replay_day` against `kernel_x` on the
     same 1m bars, for every pick, over at least 60 days of archive data. Trade for trade: fill minute, exit minute,
     reason, leverage, P&L to 1e-9 of the wallet. One run restarts the engine in the middle of an open position.
     `tests/test_candleague_exits.py` is the model; an engine-level test alone is not enough.
* **Forward judgement**, on this study's metric:
  * For each pick, L_p = [ln W(-f) - ln W(-f0)] / months, over identical days, wallets realised at exits. Pooled
    L = the mean over the 23 picks.
  * Each week the dashboard and the Korean note show L, the number of picks ahead, and for `-f` and `-f0`: trades
    entered, signals skipped while holding, and the share of trades held more than 18 h.
  * **Judgement at day 90** after the start: "forward ahead" when L > 0 and the `-f` accounts entered at least as many
    trades as the `-f0` accounts; otherwise "forward not ahead". A 95% interval (bootstrap of weeks, blocks of 2 weeks)
    is shown beside it and decides nothing. The accounts keep running afterwards, reported at day 180.
  * CONTRACT.md section 2's per-trade rule is shown for the new accounts as information only. Per-trade means ignore
    hold time and missed entries, which is what this study measures.
* **FAIL or none**: the result is reported, in Korean for the owners, and not used. The league is unchanged.
* Real money is not decided by this study. That stays the owners' decision under the program's process.

## 12. What is not in scope, and known limits

* **Not in scope**:
  * a "판단" (judgement) exit by a person or an AI;
  * partial exits (the owners asked for 전량, the whole position);
  * combinations of families other than F9;
  * q15 versions of F2, F3, F5, F6, F8 and F10: on 1h and 4h picks these react only at the pick's own closes;
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
     confirm against the variants. If the main session read any hunt test-period result before the hash (the hunt's
     systems exit on a chandelier trail, on other entries), F4's confirm is not the program's first look at chandelier
     exits on 2024-2026 (section 15). The clean check is the league's forward record.
  2. **2021-2023 was used for both, and parts of it were looked at.** E0 was chosen on 2021-2023 (the plateau rule),
     which tilts the select step against the variants. The best of 76 variants on 2021-2023 also looks better there
     than it is (the winner's curse); the single confirm and Holm address that. The main session may have seen
     select-period account results of E0, its hold times, and the time stop and opposite-signal exit with the
     take-profit kept (section 15). The select step is therefore not a first look for F3.a and F7.N12/N24/N48.a, and
     the menu may have been shaped with that knowledge. The confirm and the forward record carry the weight.
  3. **Two static inputs are not cut at 2024-01-01.** The leverage group (`run.best_flags`) uses
     `paperbot/quality_edges.json`, whose quintile edges were fitted on 2021-08-01..2024-06-30, six confirm months
     included. `research/fullgrid/exchange.json` holds 2026 brackets and order-size rules. Both act on E0 and every
     variant alike. T3 cannot see them.
  4. The 1m stop-first rule touches only arms with a take-profit (section 2). The count is reported.
  5. **Power is limited.** There are 33 months, and the 23 picks are correlated (the same six coins, related
     strategies). The pooled monthly series counts each month once, so a real but small gain may not pass. No
     minimum detectable effect is computed; the 95% interval of section 9 stands in for it.
  6. Quarter size decides and the league judges at quarter size. Live size is reported only. At live size a few
     busts can reverse the order.
  7. A rule exit pays taker fee plus slippage, while a fixed take-profit pays the maker fee. That favours E0 slightly,
     as it would live.
  8. Wallets are realised at exits, so a position held across a month end counts in the month it closes.
  9. The placebo matches age, profit sign and V's precondition. A rule could still beat it through finer timing
     (for example, the hour of day) that carries no market information.

## 13. Reproducibility

* Code lives in `research/exitflex/`:
  * `data_x.py`: loading through `research/fullgrid/data.py` `load` (the `hc.py` "1m" path, shift 0), the cut and the
    cache rules below;
  * `kernel_x.py`;
  * `run_x.py`: the timing, select, confirm, audit and report stages;
  * `test_exitflex.py`.

  These are pinned in `PREREG_EXITFLEX.sha256` together with this file, `data_pin.json` and the sha256 of each input:

  | input | sha256 |
  |---|---|
  | `research/fullgrid/kernel.py` | `a4995c15…` |
  | `research/fullgrid/run.py` | `4e02df9c…` |
  | `research/fullgrid/sizing.py` | `3dc00c24…` |
  | `research/fullgrid/data.py` | `6691424b…` |
  | `research/fullgrid/exchange.json` | `176e234b…` |
  | `research/fullgrid/diag/watch_sel.json` | `f6902feb…` |
  | `paperbot/quality_edges.json` | `8b4fc48d…` |
  | `third_party/sweep/harness/vendor/fg_indicators.py` | `bf43c1b8…` |
  | `fg1m/build.json` | `824c9d1a…` |
  | the `param_defs` | `research/entry_study/DEFS_BC.sha256` |

  Repo HEAD when this revision was written: `eda4740`. Versions: Python 3.11, numpy 2.0.2, pandas 2.3.3, numba 0.60.0.
  The runner records the versions it runs with.
* **Caches.**
  * exitflex uses no disk cache it does not own. `hc.py`'s frame pickles (`frames_5m`, `frames_1m`) and signal cache
    (`cache/sig_*`) are not read. `run.FRAME_DIR` points into the stage's own folder.
  * exitflex's own disk caches live under `$WORK/<pin8>/<stage>/`, where `$WORK` is a folder outside the repo named in
    `data_pin.json`, `<pin8>` the first 8 hex digits of the pin, and `<stage>` one of `timing`, `select`, `confirm`,
    `t3-<cut>`. A stage deletes its folder before it starts. Cache keys include the pin hash and the cut time.
  * The cut arrays are written as their own data folder, `$WORK/<pin8>/cut-<cut time>/1m/<SYM>.npz`. Every `run.py`
    cache keyed by the data folder (`frame`, `best_flags`, `struct_levels`, `all_minutes`) therefore sees a different
    key for cut and full data.
  * Memory caches (those `lru_cache`s and the `run.M` memo) live only inside one process. Every stage, and each side
    of each T3 comparison, runs in its own fresh process.
* **Tests that must pass before any select run.** They print only pass or fail and counts of cases, never a
  performance figure.
  * **T1 parity.** With no rule, no placebo and the period end after the data end, `_trade_x` must equal
    `kernel._trade`: wallet change to 1e-9, exit index, reason and leverage. `account_x` must equal `kernel.account`:
    statuses, P&L, exit times, reasons, leverages and the final wallet. Test inputs:
    * synthetic 1m paths with gaps, missing minutes, funding and a mark price that differs from the last price, all 84
      kernel exits, both sides, both leverage groups, at scales 0.25 and 1;
    * the select-period signals of all 23 picks (cut arrays) under E0 at both sizes.
  * **T2 rule paths.** Hand-built paths for every family, both sides, check that:
    * the rule fires at the right check close and not before;
    * the exit fills at the check's minute (the entry helper) with slippage and taker, and never on the entry minute;
    * an entry and a rule exit decided at the same close land on the same minute, also when the bin's last minute is
      missing;
    * F1's starting reference and its upward-only ratchet work;
    * F2's arm works;
    * F3's reversal entry happens, and with both flags true a long re-enters long (5.4.8);
    * F4's level is right;
    * F5's and F8's arms and F5's giveback match hand-computed net R;
    * F6 fires only below -d;
    * F7's timing is right;
    * F9 fires on either side and not otherwise;
    * F10 fires only in profit after N bars without a new extreme;
    * a path where minute j's high (or low) alone would change F4's level, F5's or F8's arm or F10's stall leaves the
      decision at j unchanged;
    * the q15 mapping works, with 15m and 30m picks equal to the base variant;
    * missing minutes are handled;
    * a gap beyond the stop gives SL and does not free the minute;
    * the take-profit gap comes first and liquidation first of all;
    * funding is paid at the exit minute;
    * END closes;
    * only RULE and RAND free the fill minute.
  * **T3 causality of the inputs.** At each of these 21 cut times (UTC), the cut arrays and the full arrays must agree
    on the last 50 chart bars that close at or before the cut, for every pick's timeframe and for 15m:
    * cut times: the first day, 00:00, of every second month from 2021-02 to 2023-12 (18 cuts), 2022-06-15 13:37,
      2023-03-17 07:05 and 2024-01-01 00:00;
    * compared: every pick's signals (both sides) and leverage groups, ATR14, EMA(10, 20, 50), the swings (w = 2, 3, 5)
      with their confirmation bars, F1's reference series and the 15m bars;
    * each side of each cut runs in its own fresh process with its own cache folder;
    * it also asserts that the cut arrays hold no minute at or after the cut, and that the cut frames' last bar closes
      at or before the cut.

    Any difference stops the run.
  * **T4 placebo.**
    * With h = 0 everywhere the result equals the mode's base account. With h = 1 everywhere the exit comes at the
      first check.
    * The draws depend only on (seed, coin, time) and are reproducible.
    * Hand-computed hazard tables on built paths for F5 (unarmed checks counted in the denominator, only RULE in the
      numerator) and for F6 (loss-only exits), including a check whose minute gaps through the stop (counted in
      neither).
    * The placebo's own stratum uses the frozen state of step 0.
  * **T5 causality of the decisions.** For every family at its middle parameter, on synthetic paths and on 500 sampled
    (trade, check) pairs from the select-period cut arrays: change the OHLC and mark of minute j and of every later
    minute, and of every chart bar closing after the check close. The rule decision at j, the placebo stratum at j and
    every arm flag must stay identical. Only decisions are compared; no P&L is kept.
* Seeds use `run._seed`: the first 8 hex digits of the sha256 of the "|"-joined parts.
* **Order of work**:
  1. Code, tests and `data_pin.json`, then the pin, commit and push.
  2. The timing stage (times only), and the seed decision of 5.3 recorded if it applies.
  3. The select run, in a fresh process, writes `out/select.json`; the post-run audits of section 14 run; the hash is
     appended, then commit and push.
  4. The confirm run, once, in a fresh process, writes `out/confirm.json`; the audits run; then `out/REPORT_KO.md` and
     the ledger print.

  The runner prints the git commit and refuses to run on a hash mismatch.

## 14. Failure handling, bugs and looks

* **A look** is any performance figure (P&L, growth, wallet, win share, hold time, exit-reason count, trades entered or
  skipped per arm) written to a file or a screen that a person or an agent reads. Tests and audits print only pass or
  fail and counts of cases; the timing stage prints only times.
* **Tests.** If T1-T5 cannot pass without changing a rule of this file, nothing runs. The change is filed in
  `DEVIATIONS.md`, with the reason, before any run.
* **Crash and resume.** Each stage writes one result file per (pick, arm, size, seed block) under
  `out/<stage>/<pin8>/`, atomically. A resume computes only the missing files. Nothing is read, summarised or printed
  until every file of the stage exists; then the stage's summary runs once.
* **Zero-signal picks** have M_p = 0 and do not count as > 0. **Busts** follow section 7, for E0, variants and
  placebos alike.
* **Post-run audits**, run after the select run and after the confirm run whatever the outcome. They print pass or
  fail only.
  * A1: T1-T5 rerun at the run's commit.
  * A2: for every account, signals offered = entered + skipped + rejected + no fill + after bust.
  * A3: every RULE and RAND exit lies at the check minute of one of the position's checks, at that minute's open
    with slippage.
  * A4: every account's final wallet equals $5,000 plus the sum of its trades' wallet changes (to 1e-9 relative).
  * A5 (select only): no array loaded by the select process holds a minute at or after 2024-01-01.
  * A6: E0 through `kernel_x` equals `kernel.account` on the same signals and period end.
  * A7: each placebo's realised exit rate per stratum lies within a 99.9% binomial band around h.
* **A bug found by an audit or by T1-T5.** It is fixed and recorded in `DEVIATIONS.md` before the rerun's output is
  read, and the stage is rerun once.
  * Select stage: allowed once, before any confirm. The rerun's chosen set decides; both chosen sets are kept in
    `select.json`.
  * Confirm stage: the rerun decides. Both runs' p values enter the ledger as separate looks, and the Korean report
    leads with both results.
* **A bug found any other way after the confirm.**
  * After a FAIL or "none", it does not reopen the result. It is reported, and a fix is a new version with its own
    pre-registration and its own confirm look.
  * After a PASS, it is fixed and the confirm is rerun once; both results are shown and the rerun decides. A bug can
    take a pass away but cannot create one.

## 15. Before this file was fixed

* **The first draft** was written by a sub-session for the main session on 2026-10-12 (file time 01:41 UTC), before
  any exitflex code existed. It read code and pre-registration texts only:
  * `research/fullgrid/kernel.py`, `run.py` and `sizing.py`;
  * `PREREG.md`, `WATCH_PREREG.md` and `DEVIATIONS.md` of the full grid;
  * `candleague/CONTRACT.md` and the header of `candleague/exits.py`;
  * the step order of `paperbot/engine.py`;
  * the ledger passages of `research/hunt/PREREG_HUNT_WIDE.md` and `research/hunt_r2/PREREG_HUNT_R2.md` section 8;
  * the beginnings of `research/exitstyle` and `research/levstop`'s pre-registrations;
  * the source code of `hc.py`;
  * the names, timeframes and exits of the core rows of `watch_sel.json`;
  * the first and last bar dates and the gap counts of the six replica coins.
* **This revision** was written by another sub-session on 2026-10-12 (about 02:00 UTC). It read:
  * `research/fullgrid/kernel.py` (`structure_levels`, `_trade`, `_entry_index`, `account`);
  * the mode, cache and entry-shift lines of `hc.py`;
  * function and cache names of `research/fullgrid/run.py`, the header of `memo.py`, and the header and command line
    of `data.py`;
  * `fg1m/build.json` (coins, first and last minutes, minute and gap counts, sha256);
  * the header fields of `paperbot/quality_edges.json`;
  * `candleague/league.py` `chunk_signals`; function names in `candleague/runner.py`, `paperbot/engine.py` and
    `paperbot/paramshadow.py`; `candleague/CONTRACT.md` headings and its section 2 line;
  * the first lines of `research/exitstyle/PREREG_EXITSTYLE.md` (ladder against fixed take-profits on the rule bot,
    not related);
  * file names and file times only under `scratchpad/holdcost/`, `research/hunt*` and `research/autopsy`.

  Neither sub-session opened a P&L, growth, win share, account result, hold time or other performance figure of any
  period, a `holdcost` output, or a hunt or autopsy result. The two design reviews reported listing the output files by
  name only.
* **Outputs that exist and that the main session may have read.** It wrote them. Names and file times (UTC, 2026-10-12),
  as listed at about 01:56:

  | file under `scratchpad/holdcost/` | time | what it is (from file names and the reviews) |
  |---|---|---|
  | `validation_1m.json`, `validation_5m.json`, `val1m.log`, `val5m.log` | 01:36 | replica validation |
  | `grid_1m.json`, `grid_5m.json` | 01:37 | select-period results of the replica on these 23 picks |
  | `compare_5m_1m.json` | 01:37 | 5m against 1m comparison |
  | `out/hc84_rows_1m.json`, `out/hc84_rows_5m.json` | 01:42, 01:43 | account-level select-period rows of the 84 exits |
  | `out/parity_5m.json`, `out/parity_1m.json` | 01:44, 01:47 | parity checks |
  | `out/extras_5m.json` | 01:45 | `kx.py` / `study.py`: V1 time stop (H = 6, 12, 24, 48 chart bars from the fill, take-profit kept) and V2 opposite-signal exit, select period |
  | `out/hc84_split_1m.json` | 01:46 | split of the 84-exit results |
  | `out/check_forced_5m.json`, `out/check_forced_1m.json` | 01:47, 01:49 | forced-close checks |
  | `out/hc84.json` | 01:48 | 84-exit account results |
  | `out/extras_1m.json` | 01:49 | V1 and V2 on 1m |
  | `out/extras.json`, `out/blocked_ref_5m.json` | 01:52 | combined extras; blocked-signal reference |

  No hunt result file is in `research/hunt/` or `research/hunt_r2/` (by name: inputs, texts and `out/wide/parity.json`
  only). The hunt's compute server may have produced test-period results elsewhere. `research/autopsy/LOSS_AUTOPSY.md`
  holds select-period loss-cause tests; whether it covers early exits is not known to the drafters.
* **What follows, applied now** (the conservative reading). Unless the main session strikes a line of the table above
  before the hash, with the date, that file counts as read:
  * the select step is not a first look for **F3.a** (≈ V2) and **F7.N12.a, F7.N24.a, F7.N48.a** (≈ V1 with H = 12, 24,
    48). These variants are marked "seen on select" in `select.json` and the Korean report;
  * the select step is not blind for E0's hold cost (`grid_*`, `hc84*`);
  * F7's grid {12, 24, 48} matches V1's with H = 6 dropped. Whether that look led to dropping H = 6, or to any other
    family or grid choice in the design defaults, is for the main session to state before the hash. If it does not,
    the grid counts as possibly shaped by the look;
  * if any hunt test-period result was read, Known limit 1's chandelier sentence applies;
  * the families, grids and modes of section 5 are not changed after anyone reads these files. The changes of
    section 16 come from the two design reviews, which read no performance figure.
* **What the owners and the main session had seen**:
  * the full grid's per-trade results of the 84 exits on 2021-2023, 2024-2026 and 2020 (`ANALYSIS_KO.md`,
    `STRATEGIES_KO.md`, `STRATEGY_EVAL_KO.md`);
  * the league's live record from 2026-10-11, including the SOL trade that prompted this request;
  * whatever of the files above the main session read.
* **Definitions added while writing**, beyond the main session's design defaults (kept unless section 16 says
  otherwise):
  1. Every signal is offered to the account, not only those sized at $5,000 (section 3).
  2. Positions are closed at the period end (END), so the select step reads no price bar from 2024. The select run uses
     arrays cut at 2024-01-01, and tests T3 and T5 and audit A5 check it.
  3. Rule and placebo exits free their fill minute, so F3 can reverse (section 4).
  4. F1's starting reference is `kernel.structure_levels` at the signal bar, and it only moves up (section 5.2).
  5. F2 has an arm (section 5.2).
  6. F5's peak is the kernel's best value from 1m extremes after costs and funding, in net R; its current value is the
     check close.
  7. q15 means 15m triggers against the pick's timeframe levels, and equals the base variant on 15m and 30m picks.
  8. F7 is measured in time.
  9. The placebo's hazard table and its draw are defined in section 6.
  10. Ties use the parameter count and the canonical order.
  11. Decisions use only state frozen before the check's minute (step 0).

## 16. Changes from the first draft

Each change answers a review finding. Where it departs from the main session's design defaults (DD), the default is
named.

1. **Data: 1m instead of 5m (DD 9).** The study's own 1m arrays exist and are pinned by `fg1m/build.json`. The league
   runs on 1m, so a passing variant's backtest trades are the trades the league would make, and its parity test runs
   on the same bars. On 5m, E0's stop and take-profit paths and F4's and F5's extreme X would differ from the league.
   If compute is short, placebo seeds drop to 100 in select (5.3); 5m is not used anywhere, so E0, the variants and the
   placebos always share one bar size.
2. **Decision before the minute (clarifies DD 2).** Step 0 freezes the decision state before minute j, so step 2's
   update of the extreme with j's high cannot leak into F4, F5, F8 or F10. Tests T2 and T5 check it.
3. **One helper for fills and rule exits (DD 2).** Rule exits use `kernel._entry_index`, so an entry and a rule exit
   decided at the same close land on the same minute also when a bin's last minute is missing. X starts at the fill.
   The long-and-short and gap-SL cases are written out (5.4).
4. **F5 in net R instead of net ROE (DD 3).** Net ROE depends on leverage, and quarter size often picks a different
   leverage than live size. F5 would then fire at different prices in the deciding run and in a live-size account. Net
   R does not depend on size. With a -60% ROE stop, P = 1, 1.5 and 2 are about +60%, +90% and +120%.
5. **F6 with a loss depth (DD 3).** d = 0 alone can fire near the entry price on costs. d = 0.5 is closer to the
   owners' example.
6. **New F8, F9 (and F9 q15) and F10 (DD 3).** F8 is the owners' literal "+60% then the structure breaks". F9 is their
   two-sided rule as one variant, also at 15m on 1h and 4h picks for speed. F10 is the stall ("더이상 안오를꺼 같으면").
   Without them a FAIL of F1, F5 or F6 could be read as a verdict on the owners' own rule. No existing cell was dropped,
   so the menu of the design defaults stays inside this one.
7. **Placebo matched on age, profit sign and precondition (DD 4).** A constant hazard puts most random exits early and
   ignores the profit state, so a rule could beat it through the shape of its hold times alone. The denominator and
   numerator of h are now defined exactly (section 6).
8. **F7 has no placebo, and Q-A is reported (DD 4, 6, 7).** F7 is the owners' hypothesis itself ("long holds cost
   entries"). An age-matched placebo of F7 would be F7. F7 may pass on criteria 1, 2 and 4 with the narrower claim
   "beats E0 by holding less". The placebos' own result against E0 is reported as a second answer to the owners'
   question.
9. **Selection criteria (DD 6).** "Median > 0" followed from "> 0 on 14 of 23 picks", so it is replaced by pooled
   M(V) > 0. A new criterion requires trades entered >= E0's, so a variant cannot be chosen and then fail the confirm on
   entries alone. At most one variant per group, so two near copies (a q15 and its base, F6 and F1) do not split Holm.
10. **Confirm (DD 7).** The block bootstrap (3-month blocks) is the test, because exits shift P&L between months and
    regimes cluster. The iid p and a 95% interval are reported. The placebo gate is the 95th percentile, as in select;
    a median gate would pass a no-better-than-random rule half the time.
11. **League (DD 8).** The new accounts run at quarter size, the size that decided, next to a same-day E0 twin `-f0`
    at quarter size, in their own league database so nothing existing is reset or replayed. They are judged on log
    growth over identical days at day 90, not on CONTRACT.md's per-trade mean. The runner changes and an end-to-end
    parity test are named before any code.
12. **Caches and causality tests.** Cut arrays get their own data folder, stages run in fresh processes with their own
    cache folders, T3 runs at 21 cut times, and T5 checks decisions directly.
13. **Bugs, looks and failures.** Section 14 is new: what a look is, fixed post-run audits, which rerun decides, how a
    resume works, zero-signal picks and busts.
14. **Known limits.** Static inputs fitted on data past 2023 (`quality_edges.json`, `exchange.json`) are named, and
    the "no 2024 bar" sentence now covers price bars only. The stop-first sentence no longer claims the comparison is
    fair by construction. FAIL is not "no effect"; the ledger status goes into the Korean headline.
15. **Disclosure.** Section 15 replaces the placeholder with the file list, a conservative default and its
    consequences.

**Findings not adopted, and why:**

* Dropping weak cells (F2 n = 50, F4 m = 3) to save compute: not adopted. One review asked that the menu not be
  reshaped, and there is no ground other than numbers to call a cell weak. The compute fallback of 5.3 covers the
  cost instead.
* An eligibility cap on the share of trades held more than 18 h: reported, not a criterion. 18 h is 72 bars on 15m and
  4.5 bars on 4h, so one cap does not mean the same thing across picks. The entries criterion measures the cost of long
  holds directly.
* Requiring ledger BH significance before any league account is added: not adopted. The league accounts are paper,
  and their forward record is the program's clean test. The BH status is in the Korean headline, and the owners decide
  with it in view.
* q15 versions of F5, F6, F8 and F10: only F9 q15 was added (the owners' combined rule), to keep the count down. The
  others react at the pick's own closes, and README_KO says so.
* A live-size non-inferiority guard on PASS: not needed, because the league account now runs and is judged at quarter
  size. Live-size results and busts are reported.
* A paired placebo bootstrap inside Holm: not adopted. The 95th-percentile gate tests the same question without adding
  a ledger hypothesis.
