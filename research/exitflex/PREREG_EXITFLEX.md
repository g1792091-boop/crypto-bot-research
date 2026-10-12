# Flexible exits for the 38 league watch picks: pre-registration (exitflex v1)

(한국어 요약: `README_KO.md`.) This file is fixed before this study's own runs produce any number. It is pinned by
`PREREG_EXITFLEX.sha256` together with the code and inputs of section 13. Changes after the pin go to `DEVIATIONS.md`
in this folder, dated and with the reason, never into this file. Select-period numbers of E0 on the core picks have been
seen by the main session; section 15 lists them and says what follows. Section 16 lists what changed in each revision
and why. Appendix A writes out each strategy's own exit (family F11).

First draft 2026-10-12 01:41 UTC; revised 2026-10-12 (UTC) after two design reviews; revised again 2026-10-12 (about
02:40 UTC) after the owners' four later messages below; revised a third time 2026-10-12 after two reviews of the second
revision (section 16.3). Owners' first request, about the 후보 리그 ("커스텀값 봇"),
where a SOL long had been held about 18 h at +43% ROE under a fixed 3R take-profit and a 4 ATR stop:
"익절구조를 과거 백테스트를 돌려서 좋게 잡은건 좋은데 포지션 보유시간이 길어지면 진입횟수에도 영향을 끼치잖아 ... 18시간씩
보유하고있으면 솔직히 좀 그래 예를들어 롱을 잡아서 +60%까지 갔다가 롱구조가 무너지거나 더이상 안오를꺼 같으면 빠르게
전량익절을 한다던지 ... 반대로 손절 부분도 마찬가지고 만약 손절을 -60%로 잡아놨고 롱을 잡아놨었는데 롱 구조가 무너지고
-40%까지 간상황에서 더 떨어질꺼 같은 판단이 들고 롱 구조가 무너졌다고 생각이되면 원래 손절가가 -60%지만 ... 빠르게 전량
손절을 한다던지". Earlier the same day: "유도리있게 나는 그런식으로 가고싶은데", "지금 나와 친구는 빠르게 매매법을
완성을 시켜서 성공을 시켜야하는데".

**Owners' later messages, 2026-10-12** (verbatim; at that time all 7 open positions of the league used a fixed 3R
take-profit and had been held 16-18 h):

1. "익절구조를 과거 백테스트를 돌려서 좋게 잡은건 좋은데 포지션 보유시간이 길어지면 진입횟수에도 영향을 끼치잖아 ...
   예를들어 롱을 잡아서 +60%까지 갔다가 롱구조가 무너지거나 더이상 안오를꺼 같으면 빠르게 전량익절을 한다던지 ... 반대로
   손절 부분도 ... 롱 구조가 무너지고 -40%까지 간상황에서 ... 원래 손절가가 -60%지만 ... 빠르게 전량 손절을 한다던지"
2. "지금 돌아가고 있는봇 중지하고 깔끔하게 다시 돌리고 싶어서"
3. "그렇다고 너무 빠른 손절구조를 원하는것도 아니야 ... 수익을 43%까지 크게 먹고있는건 좋은데 나와 친구의 계획은
   빠른시간내에 많은돈을 벌기를 원하는건데 ... 포지션을 막 16시간 이렇게 보유하고 있으니까 다른 새로운 좋은 진입기회를
   놓친다고 해야되나? 스윙 느낌이 나잖아 ... 우린 단타느낌을 원하는건데"
4. "왜 7개 전부다 고정익절이냐고 매매법이 다 다른데 익절구간도 다를꺼 아니야"

**What the main session promised them** (in Korean, before this revision), and where this file carries it out:

* (a) nine kinds of exit: structure break, moving-average break, opposite signal, chandelier trail, profit giveback,
  early loss cut, time stop, stall, and each strategy's own exit. They are numbered F1-F11 because F8 and F9 combine
  the structure break with a gain or a loss; the time stop has a bar-count form (F7) and a clock-hour form (F7h).
  Section 5 and Appendix A.
* (b) as given: "the hard stop stays as a backstop, early cuts only on a confirmed structure break at a bar close".
  Every variant keeps the hard stop unmoved and decides every early exit at a bar close (sections 4 and 5.1). Not
  every variant's early loss cut is a structure break: F2, F3, F4, F4 q15, F7, F7h and F11 can also cut a loss on a
  moving average, an opposite signal, a trail, the clock or a strategy's non-structure condition. Section 5.3 sorts
  every variant by what it can cut a loss on; the select report shows that category on every row (8.2); and the
  default of 8.4 takes only variants that cut a loss before the hard stop on a structure break at a loss of at least
  0.5R, or not at all before a gain. Variants outside that set can be run only when the owners choose them by name.
* (c) a select-period (2021-2023) table by hold time in hours and by entries, from which the owners choose; then one
  confirm on 2024-2026. Sections 8 and 9. The table lists every variant, choosable or not (8.2).
* (d) all 38 league picks, DeepSeek included, DeepSeek shown without money. Section 3.
* (e) after a PASS and their OK, the league is stopped and restarted cleanly from the new install time, with, per
  pick, a new-exit account and a current-exit account side by side plus a coin-flip account; the old record kept as a
  backup; a checkpoint one month after the restart. Section 11.
* (f) if nothing passes, they are told plainly and decide with us. Sections 8.6 and 11.1.

## 1. Questions

The 38 picks keep their entries. Only the exit changes. The account holds one position at a time over six coins, so a
signal that arrives while a position is open is lost. The full-grid study never counted those lost signals: it judged
exits by the mean per-trade P&L with every signal counted (PREREG.md 5-6). None of its 84 exits leaves on a structure
break, an opposite signal, a time limit, a chandelier trail, a profit giveback or the strategy's own exit signal, and
none cuts a loss before the hard stop.

The picks form two **pools**, as in WATCH_PREREG: **core** (23 picks) and **DeepSeek** (15 picks). Every question is
asked, decided and reported per pool. DeepSeek results follow the owners' rule D11 (section 3).

* **Q-A (the owners' question).** If the account leaves earlier, and so is free for more of the pick's signals, does it
  grow faster per month than with the pick's current exit (E0)? The time stops F7 (in chart bars) and F7h (in clock
  hours) test this directly: they read only the clock. The random exits of section 6 are also reported against E0 as
  a second, descriptive answer.
* **Q-B.** Does an exit that reads the market do better than E0, and also better than a random exit with the same
  timing profile (section 6)? These exits are a structure break, a moving-average break, the opposite signal, a
  chandelier trail, a profit giveback, an early loss cut, a structure break after a gain, the owners' two-sided rule,
  a stall and each strategy's own exit. Only a Q-B variant that beats its random exit may be described as reading the
  market. A passing F7 or F7h shows only that shorter holds pay.
* **Hold time comes first in every table.** The owners want a day-trading feel ("단타"), not swing holds. A shorter
  hold pays only when the extra entries earn more than their costs (section 7 gives the engine's cost of one round
  trip). The study decides on account growth. Hold hours and entries lead every table so that the owners choose with
  them in view (section 8).
* **Naming.** F1 to F11 in this file are exit families. Several DeepSeek strategies have names that also start with F
  (F1_PVT_DIV, F5_BOX, F7_RF_ONLY, F7_RF_TRIPLE, F9_FVG, F10_OTE, F11_TSOUP, F12_MSS_DISP). These are lib_c's names and
  have nothing to do with the families. A strategy is always written with its full name.

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
  * DeepSeek signals of a coin other than BTC receive BTC's chart bars of the same timeframe as context (`run.signals`).
  * F7_RF_TRIPLE reads a higher-timeframe frame (4h for its 1h pick, 1d for its 4h pick), resampled from the chart bars,
    and takes the last higher-timeframe bar closed at or before the chart bar's close (`search.htf_series`).
* **Periods** are set by the signal bar's close (UTC). **Select**: [2021-01-01, 2024-01-01), 36 calendar months.
  **Confirm**: [2024-01-01, 2026-10-01), 33 months. A coin's first 300 chart bars are warm-up only (`run.period_ids`).
* **The select cut.** The select run loads the 1m arrays cut at 2024-01-01 00:00 UTC (minutes that open before it),
  writes them as their own data folder (section 13, caches) and builds every chart bar, higher-timeframe bar and
  indicator from them. No price, mark or funding bar from 2024-01-01 on enters any select-period number. Two static
  inputs are not price bars and are not cut: `paperbot/quality_edges.json` and `research/fullgrid/exchange.json` (Known
  limit 3). The confirm run loads the full arrays.
* **Bars and the stop-first rule.** The study, the league and this study all step on 1m bars. The order of high and
  low inside one minute is unknown, so a minute that touches both the stop and the take-profit counts as a stop (the
  kernel's rule). This rule only affects arms that have a take-profit: E0, every mode (a), and F11.b on the picks whose
  own exit has a target (Appendix A). The number of such minutes is reported per arm (section 7). Rule exits happen at
  minute opens and do not depend on it.

## 3. Entries

* **Picks**: the 38 rows of `research/fullgrid/diag/watch_sel.json` (sha256 `f6902feb…`), as carried into
  `candleague/data/candidates.json` (sha256 `dd627ec0…`; this study reads its fields `id`, `kind`, `name`, `tf`, `exit`
  and `combo`, never `source`). They are the league's watch picks with the league's ids.

  **Core pool** (kind `core`, 23 picks):

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

  Core timeframes: 4 picks on 15m, 7 on 30m, 6 on 1h and 6 on 4h.

  **DeepSeek pool** (kind `ds`, 15 picks):

  | id | tf | take-profit | stop |
  |---|---|---|---|
  | ds-F10_OTE-1h-1 | 1h | 3R | 4 ATR |
  | ds-F10_OTE-4h-1 | 4h | 3R | 3 ATR |
  | ds-F11_TSOUP-4h-1 | 4h | 3R | 1.5 ATR |
  | ds-F12_MSS_DISP-1h-1 | 1h | 3R | 4 ATR |
  | ds-F12_MSS_DISP-4h-1 | 4h | 3R | 1 ATR |
  | ds-F1_PVT_DIV-1h-1 | 1h | 3R | 2 ATR |
  | ds-F5_BOX-15m-1 | 15m | 3R | 3 ATR |
  | ds-F5_BOX-4h-1 | 4h | 3R | 4 ATR |
  | ds-F7_RF_ONLY-30m-1 | 30m | 3R | 4 ATR |
  | ds-F7_RF_ONLY-1h-3 | 1h | 3R | 4 ATR |
  | ds-F7_RF_ONLY-4h-1 | 4h | 3R | 3 ATR |
  | ds-F7_RF_TRIPLE-1h-1 | 1h | 3R | 4 ATR |
  | ds-F7_RF_TRIPLE-4h-1 | 4h | 3R | 3 ATR |
  | ds-F9_FVG-1h-1 | 1h | 3R | 4 ATR |
  | ds-F9_FVG-4h-1 | 4h | 3R | 2 ATR |

  DeepSeek timeframes: 1 pick on 15m, 1 on 30m, 6 on 1h and 7 on 4h. No pick of either pool uses the stepped lock.
* **D11 (owners' rule), for DeepSeek.** DeepSeek picks are computed exactly like the core picks. No DeepSeek money figure
  appears in any committed file or owner report of this study: no P&L, wallet, growth, log growth or difference of log
  growth, drawdown in money or multiples, or interval of any of these.
  * DeepSeek rows show trade counts (offered, entered, skipped, rejected, closed), win shares, hold times, exit-reason
    counts (LIQ included) and pass / fail labels, nothing else.
  * Private, like money: DeepSeek p values of any test (they rank money differences), busts and bust counts, final
    wallet multiples, and any rank of DeepSeek variants by a money figure. The confirm's Holm label and the ledger's
    BH label of a DeepSeek pair are labels and may be shown; its p value is not (sections 9 and 10).
  * The DeepSeek money figures and p values that the gates, the placebo gate, the confirm test and the ledger need are
    written only to `$WORK/<pin8>/ds_private/` outside the repository (section 13), read only by the runner and the
    ledger print. This includes the per-account result files of DeepSeek picks
    (`$WORK/<pin8>/ds_private/results/<stage>/`). Their sha256 values are committed with `select.json` and
    `confirm.json`. No person or agent opens them.
  * The league dashboard's own DeepSeek money setting (research/fullgrid/DEVIATIONS.md, 2026-10-11) is outside this
    file. This study's notes, weekly notes, checkpoint reports and committed files carry no DeepSeek money figure.
* **Signals**: `run.signals(data_dir, kind, name, sym, tf, combo)` with the pick's combo, on the chart bars of section 2,
  for every coin.
  * Core: the pick's `param_defs` module (`run.core_module`, hash-checked against `DEFS_BC.sha256`).
  * DeepSeek: `ds_defs.signals` with BTC's frame as context for the other coins. `ds_defs` sets both sides false on a
    bar where both would be true, so a DeepSeek bar never carries both flags.
  * Leverage group: core from `run.best_flags`; DeepSeek always "normal", as in the study (`run.trade_table`) and the
    league.
  * ATR14 is `fg_indicators.atr(df, 14)` (Wilder) at the signal bar, for both pools.
* **Fill**: `kernel._entry_index(ts, close)` on the 1m bars, unchanged. That is the open of the minute that opens at the
  signal bar's close, or one minute later when the bin's last minute is missing (the study's and the league's rule),
  plus 0.02% slippage.
* **Offered signals**: every long and short signal of the period whose ATR14 is finite and > 0 and whose fill minute
  opens before the period's last minute.
  * They are sorted by (fill time, coin priority BTC, ETH, SOL, DOGE, LTC, BCH).
  * No pick can carry both a long and a short flag on one bar of one coin: the seven core `param_defs` other than DOGE
    end with `short &= ~long`, DOGE's own sides are cleaned the same way (`short_entry & ~long`) and its EMA conditions
    exclude each other, and `ds_defs` drops a bar where both would be true. The runner and the league assert that no
    offered bar carries both flags; the order "long first" above is a guard only, not a case that occurs.
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
  * **Native target** (F11.b only, Appendix A): a take-profit limit at a price level fixed at the signal bar, used only
    when (level - fill) x side > 0, otherwise there is none (the kernel's TP_STRUCT rule without the lock).
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
  5. An open beyond the take-profit (fixed or native): exit at the open, maker (TP).
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
  * Under F3 (and F11 where a strategy's own exit is its opposite signal) this means that the opposite signal which
    closed the position is entered at the same open when it ranks first and can be sized (a reversal). Entries and rule
    exits use the same helper (section 5.1), so they land on the same minute.
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
  * the chart bars closed at or before C: their OHLC, ATR14, EMA, the swings confirmed by then, the pick's signals of
    both sides, and the strategy's own indicator arrays named in Appendix A (higher-timeframe values only from
    higher-timeframe bars closed at or before C);
  * X, the favourable extreme over minutes e .. j - 1 (the highest high since the fill for a long, the lowest low for a
    short), and T_X, the open time of the last minute in e .. j - 1 that raised X (the fill time when none did);
  * the funding paid on minutes before j;
  * for F11, price levels fixed at the signal bar from bars <= i0 (Appendix A).
* **Rc** = Rn at the check's chart close; **Rpk** = Rn(X). Prices are last prices, not mark prices, as in the study's
  signals and ATR.
* Every variant keeps the pick's hard stop, sizing and leverage (k x ATR14 of the signal bar) as the backstop. A rule
  never moves the hard stop. Every early exit is decided at a bar close and executed at the next minute's open; no rule
  acts inside a bar.
* **Mode (a)**: the pick's own take-profit stays (3R for 21 core picks and all 15 DeepSeek picks, 2R for
  core-S4_BB_BBP-30m-1, net ROE 50% for core-OBV_S-1h-3). **Mode (b)**: no fixed take-profit and no lock, so the rule,
  the hard stop, liquidation or the period end closes the trade. The one exception is F11.b, which keeps the strategy's
  own target where Appendix A defines one.
* Each rule of F1-F10 is written below for a long. The short is mirrored: high and low swap, above and below swap, max
  and min swap. F11's short side is written out per strategy in Appendix A.

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
  at bar i (its numbers, `run.signals`, the raw flag).
* The opposite signal is offered to the account like any other signal. Under section 4's order it can reverse the
  position (5.4.8).

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
  or 48 h; on 4h 2, 4 or 8 days. On the 4h picks the shortest F7 is therefore 2 days; F7h below caps holds in hours.
* F7 has no placebo (section 6). It answers Q-A only.

**F7h clock-time stop** ["포지션을 막 16시간 이렇게 보유하고 있으니까 ... 스윙 느낌", "단타"], H in {4, 8, 16} hours.
* Fires at the first pick-timeframe check close at or after C0 + H hours. Chart bins are UTC bins and C0 is a bin
  close, so C0 + H is itself a close of every pick timeframe (15m, 30m, 1h, 4h); when that bin is missing, the next
  close that exists acts. No 15m schedule is needed.
* In chart bars this is 4H on 15m, 2H on 30m, H on 1h and H / 4 on 4h (1, 2 or 4 bars). The hold is at most about H
  hours on every pick, whatever its timeframe; the hard stop and, in mode (a), the take-profit can end it sooner.
* Group T with F7, so F7 and F7h cannot both be chosen in one pool. No placebo; Q-A only; the claim of F7 (8.5).

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

**F11 the strategy's own exit** ["매매법이 다 다른데 익절구간도 다를꺼 아니야"], one definition per strategy, no
parameter; modes (a) and (b).
* Each of the 16 strategies has its own invalidation, and some have their own target, read from the strategy's own
  entry logic, its source exit where one exists in the repository, or its pattern. Appendix A writes each one out,
  with the common rules C1-C8 (A.0).
* **Invalidation**: at a pick-timeframe check close, the position closes (RULE) when the strategy's own reason for the
  trade is gone, for example the EMA cross undone (N03_ADX_GC), the OBV back under its average (OBV_S), a close below
  the swing low the impulse started from (F10_OTE). Checks are only at the pick's own closes (no q15).
* **F11.a**: the invalidation plus the pick's own take-profit (as every mode (a)).
* **F11.b**: the invalidation plus the strategy's own target where it has one (a take-profit limit at a level fixed at
  the signal bar: N13_3OUTSIDE, N19_FIB_CHOP, F10_OTE, F11_TSOUP, F12_MSS_DISP, F1_PVT_DIV, F5_BOX, F9_FVG); for the
  other eight strategies no take-profit.
* The rule is global: F11 is one variant for all picks of a pool. What differs per strategy is fixed in Appendix A and
  is not chosen on any number.
* On the three F7_RF_ONLY picks the strategy's own exit is its opposite signal, so F11.a equals F3.a and F11.b equals
  F3.b there; the select report marks both pairs (Known limit 11).

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
| F7h | T | H = 4, 8, 16 hours | a, b | 6 |
| F8 | S | w = 2, 3, 5 x P = 1, 2 | a, b | 12 |
| F9 | S | fixed | a, b | 2 |
| F9 q15 | S | fixed | a, b | 2 |
| F10 | L | N = 6, 12 | a, b | 4 |
| F11 | N | one definition per strategy (Appendix A) | a, b | 2 |
| **total** | | | | **84** |

Plus the reference E0. Every variant runs on every pick of both pools.

* **Ids**: `F1.w3.a`, `F1.w3.b.q15`, `F2.n20.b`, `F3.a`, `F4.m1.5.a`, `F4.m2.b.q15`, `F5.P1.5.g25.a`, `F6.w2.d0`,
  `F6.w2.d0.5`, `F7.N24.b`, `F7h.H8.a`, `F8.w3.P1.a`, `F9.a`, `F9.b.q15`, `F10.N6.a`, `F11.a`, `F11.b`.
* **Groups** (used in section 8 so that two variants chosen in one pool are not near copies):
  * S, structure: F1, F1 q15, F6, F8, F9, F9 q15;
  * M, moving average: F2;
  * O, opposite signal: F3;
  * C, chandelier: F4, F4 q15;
  * G, giveback: F5;
  * T, time: F7, F7h;
  * L, stall: F10;
  * N, the strategy's own exit: F11.
* **Canonical order**, used for ties, tables and seeds: the table's rows in order. Inside a row, parameters ascending in
  the order written (F5 by P then g, F6 by w then d, F8 by w then P), then mode a before b.
* **Parameter count**: the numeric parameters plus one for q15. Modes are not counted.
  * 0: F3, F11.
  * 1: F1, F2, F4, F7, F7h, F10.
  * 2: F1 q15, F4 q15, F5, F6, F8.
  * 3: F9. 4: F9 q15.
* **What each variant can cut a loss on** before the hard stop (promise (b); shown on every row of the select report,
  8.2). Four categories:
  * **L0, no early loss cut before a gain**: F5 and F8 act only after Rpk has reached +P R (a later exit can still
    land below the fill after a fall), F10 only while Rc > 0.
  * **L1, structure break at a loss of at least 0.5R**: F6.w*.d0.5, F9, F9 q15 (F9 and F9 q15 also have F8's leg after
    a gain).
  * **L2, structure break at any loss**: F1, F1 q15, F6.w*.d0. They keep promise (b) as worded, but they can cut a
    loss close to the entry price, which owners' message 3 ("너무 빠른 손절구조를 원하는것도 아니야") warns against.
  * **L3, not only a structure break**: F2 (moving average), F3 (opposite signal), F4 and F4 q15 (chandelier trail;
    m = 1.5 on a 4 ATR stop can cut near -0.4R), F7 and F7h (the clock), F11 (each strategy's own invalidation, which
    for DOGE, N03_ADX_GC, N09_ALLIG_AROON, N10_HA_PSAR, OBV_S, S4_BB_BBP and the two range-filter strategies is not a
    structure level; Appendix A).
  * The **default set D** of 8.4 is L0 and L1: F5 (12), F6.w*.d0.5 (3), F8 (12), F9 (2), F9 q15 (2), F10 (4); 35
    variants. L2 and L3 variants run only when the owners name them.
* **Runs**:
  * Select, step 1: E0 plus 84 variants, x 38 picks x 2 sizes = 6,460 accounts.
  * Select, step 2 (placebos, section 6): only for the (variant, pool) pairs outside F7 and F7h that pass gates 1, 2
    and 4 of 8.1 in step 1. At most 72 variants x 23 core picks x 200 seeds = 331,200 and 72 x 15 x 200 = 216,000
    DeepSeek placebo accounts, 547,200 in all, at quarter size.
  * Confirm: at most (1 + 2) x 38 x 2 = 228 accounts (E0 and up to two chosen variants per pool), plus at most
    2 x 38 x 200 = 15,200 placebo accounts.
* **Compute and the seed count (fixed now).**
  * Everything runs on 1m bars. Step 1 is cheap; step 2 is the cost.
  * Before the select run the runner's timing stage runs, in one process on the select-period cut arrays, E0 and one
    placebo seed of each of the 72 variants outside F7 and F7h on one pick, `core-DOGE-15m-1` (a 15m pick: the most check
    closes per hold). Each placebo uses the hazard table of its variant's own account on that pick, which is computed
    and discarded. The stage writes only seconds.
  * Projected step-2 wall time = (the sum of the 72 one-seed times) x 38 picks x 200 seeds / 4 CPUs. This is the worst
    case (every variant reaching step 2 on every pick, every pick as costly as a 15m pick).
  * If the projection is more than 8 hours, the select placebos use 100 seeds (s = 0 .. 99) instead of 200, and the
    95th percentile comes from 100 pooled means. Otherwise 200. The confirm always uses 200.
  * The seconds, the projection and the resulting seed count go to `out/timing.json`, committed before the select run.
    Applying this rule is not a deviation.

### 5.4 Edge cases

1. **Gaps.** A rule exit fills at the open of minute j, whatever that price is. Steps 3-5 come first at that open.
   * If the open is beyond the hard stop, the exit is recorded as SL. Beyond liquidation on the mark, it is LIQ. Beyond
     the take-profit (fixed or native), it is TP at the open, maker.
   * In these three cases minute j is not freed for entries (section 4), and the check counts in neither the numerator
     nor the denominator of the placebo hazard (section 6).
2. **Missing minutes.** A chart bin with no minute has no close and no check. When the minute of one check close comes
   after one or more further check closes, one check is made at that minute on the latest closed chart bar:
   * F1, F6, F8 and F9 update their reference with every bar in between;
   * F2's arm reads every bar in between;
   * F3 counts an opposite signal on any of those bars;
   * F4, F5 and F10 use X and T_X over every minute before j;
   * F7 and F7h use time;
   * F11 walks the bars in between in time order, arming and testing each component; the check fires if any bar fires
     (A.0, rule C4).
3. **A swing that does not exist yet.** F1, F6, F8 and F9 do nothing until a reference exists. The hard stop and, in mode
   (a), the take-profit keep working. An undefined EMA or ATR (NaN, impossible after the 300-bar warm-up with n <= 50)
   means no arm and no fire. For F11, a NaN input means that component neither fires nor arms at that bar, and a NaN
   level or target means none (rule C7).
4. **A rule firing on the entry minute** cannot happen. The first check is the close after the signal bar (C0 + tf, or
   C0 + 15 min for q15), and a check minute at or before the entry minute moves to e + 1. The signal bar's own close is
   never a check. Only F1's starting reference, F2's arm and F11's arms and fixed levels read it.
5. **Fills beyond the hard stop**: see 1. Between checks the hard stop and the take-profit work on every minute as in
   the kernel.
6. **Same-minute stop and rule.** The rule exit is at minute j's open, before j's range, so in minute j the rule comes
   before a stop or take-profit touched later in j. A stop or take-profit touched in an earlier minute, before the check
   close, has already closed the position. At j's open the order is liquidation, stop gap, take-profit gap, then the
   rule (section 4).
7. **Funding at minute j** is paid by a position closed at j's open, because it was held over the funding instant (as in
   the kernel and PaperEngine). It is not part of the decision at j (step 0).
8. **Reversals and both-flag bars.** No pick carries both flags on one bar (section 3), so a bar that fires F3 carries
   only the opposite side's signal. After the RULE exit that signal is offered at the freed minute and, when it ranks
   first and can be sized, the position reverses. The same holds for F11 where a strategy's own exit includes its
   opposite signal (N13_3OUTSIDE, F7_RF_ONLY). A both-flag bar would stop the run (the assertion of section 3).
9. **After a bust** no signal is taken, as in the kernel.
10. **F11 levels and targets** are per position, fixed at the signal bar i0 from bars <= i0, and never move (rule C5).
    A native target at or behind the fill is no target (rule C6); then the invalidation, the hard stop and the period
    end act alone.

## 6. Placebo

* **Purpose.** A rule that only shortens holds frees the account more often. A random exit with the same timing profile
  shortens holds in the same way. A Q-B rule must beat it to be described as reading the market. F7 and F7h have no
  placebo: they read nothing by design, and a placebo with their timing profile would be the time stop itself.
* **State at a check.** For a variant V and an open position at a check of V's schedule, the stratum is (a, s, z):
  * a, the age bucket of the check index k: {1}, {2}, {3-4}, {5-8}, {9-16}, {17-32}, {33-64}, {65 and more};
  * s = 1 when Rc >= 0, else 0;
  * z, V's precondition (z = 1 when V could fire at this check on some close, else 0), computed on the position at
    hand, with Rc taken at the check's own close (the 15m close for q15):
    * F1, F1 q15: a reference exists;
    * F6.w*.d: a reference exists and Rc < -d (for d = 0 this adds nothing to s);
    * F2: armed;
    * F5: armed (Rpk has reached P at a check);
    * F8: armed and a reference exists;
    * F9, F9 q15: a reference exists and (armed, with Rpk having reached 1R at a check, or Rc < -0.5R);
    * F11: the position has a finite invalidation level, or its side has a component that is armed or is an event
      component (rule C3); the constant-false flags lx = sx = False of the five level-only DeepSeek strategies count
      as no component. For F12_MSS_DISP, z = 1 only while a live, not yet broken swing low (long) or swing high
      (short) exists in the strategy's structure at that close (A.11), since its flags can fire only then. For the
      other strategies z is 1 at every check by construction (each has a component armed at i0 or a finite level;
      Appendix A edge cases), so the placebo matches age and profit sign only (Known limit 9);
    * F3, F4, F4 q15, F10: z = 0 always.

  All of it uses the frozen state of step 0, so the placebo, like the rule, sees nothing of minute j.
* **Hazard.** For each variant V, pick p and period, from V's quarter-size account:
  h[a, s, z] = (exits recorded RULE at checks of stratum (a, s, z)) / (checks of stratum (a, s, z) at which a
  position was still open after steps 1-5 of the check's minute).
  * The denominator counts every check of V's schedule, armed or not, with a merged check counted once.
  * The numerator counts RULE exits, the RULE + END case included.
  * A check whose minute's open closed the position (LIQ, SL or TP at steps 3-5) counts in neither.
  * h = 0 where the denominator is 0.
* **Placebo account**: V's mode (the pick's take-profit kept in (a); in (b) none, except F11.b, which keeps the
  strategy's own target), V's check schedule (q15 included), and the same hard stop, sizing, period-end close and free
  fill minute. Instead of V's rule, at each check it computes its own position's stratum and exits when u < h[a, s, z]
  (RAND). The draw u depends only on (V, period, seed, coin, check close time), not on the pick, so two picks that
  hold the same coin at the same check close draw the same u (this carries part of the cross-pick correlation that V's
  own exits have; Known limit 9):
  * base = `run._seed("exitflex", "placebo", V, period, s)`, s = 0 .. 199 (0 .. 99 under the rule of 5.3);
  * key = coin index x 2^36 + close ms // 60,000;
  * u = (splitmix64(splitmix64(base) XOR key) >> 11) / 2^53, with the standard splitmix64 constants.
* **Placebo pooled mean** for seed s and pool P = the mean over the pool's picks of the placebo's M_p: its monthly log
  growth minus E0's, computed as in section 7.
* **Two steps** (select only). Step 1 runs E0 and every variant on every pick. Step 2 runs the placebo of V in pool P
  only when V is outside F7 and F7h and passes gates 1, 2 and 4 of 8.1 in P. This gives exactly the eligible set that
  running every placebo would give: a variant is eligible only if all its gates pass, and gate 3 is the only one that
  needs a placebo. The hazard table comes from V's own step-1 account on each pick, and a placebo's draws depend only
  on (V, period, seed, coin, time), so a placebo's result does not depend on which other placebos run. What differs
  from a full run is only the gate-3 count: gate 3 is not computed for a pair that failed gate 1, 2 or 4, and the
  report counts gate failures in that order (8.2).
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
* Pooled, per pool P: M_P(V) = the mean over the pool's picks of M_p(V). The monthly pooled difference is D_m^P(V) =
  the mean over the pool's picks of [g_m(V) - g_m(E0)]; M_P(V) is the mean of D_m^P(V) over the months.
* **Hold time and entries, reported first** for E0, V and the placebo median, per pick and pooled per pool, at quarter
  size (and at live size beside):
  * median and 90th-percentile hold (hours from fill to exit), and the shares of trades held more than 4 h, 8 h and
    18 h, over all closed trades of the pool's accounts together;
  * trades entered (status 1) and trades closed; signals skipped while a position was open (status 0) and signals
    rejected (status 2);
  * entries made at the open of a rule-exit minute.
* Reported beside it, deciding nothing, per pick and pooled, for E0, V and the placebo median:
  * the same metric at live size, and busts at live size;
  * trades changed: V's trades with no E0 trade of the same (coin, side, fill minute, exit minute, exit reason),
    count and share;
  * exit reasons (TP, SL, RULE, RAND, LIQ, END);
  * win share (closed trades with a wallet change > 0);
  * the maximum drawdown of the wallet at closes, busts and the final wallet multiple;
  * the minutes where the stop and the take-profit were both touched (decided stop-first), per arm;
  * the realised hazard table h;
  * the placebo's 5th, 50th and 95th percentiles.
* **What a round trip costs** (the engine's own figures, `config.v3_settings`; written here so that the reports can
  print them next to hold times):
  * at market on both sides (exits RULE, RAND, SL, END): taker 0.05% plus slippage 0.02% on each side, 0.14% of the
    position's notional (`rt` = `S[5]` = 0.0014);
  * with a take-profit limit (TP): 0.05% + 0.02% at entry and 0.02% maker at exit, 0.09%;
  * as a share of margin, these are times the leverage: at 30x, 4.2% (2.7% at a limit); at 20x, 2.8%; at 40x, 5.6%;
    at 50x, 7.0%;
  * as a share of the wallet: the notional is the margin fraction times the leverage times the wallet, so one market
    round trip costs, at live size, about 3.5% of the wallet at 50x / 50% margin (notional 25 x the wallet), 2.24% at
    40x / 40% (16 x), 1.26% at 30x / 30% (9 x) and 0.56% at 20x / 20% (4 x); at quarter size a quarter of each:
    0.88%, 0.56%, 0.32% and 0.14%. Core picks in the best group use the 50x and 40x brackets; DeepSeek picks are always
    "normal" (30x, then 20x). Funding comes on top.
  * A variant that holds shorter makes more round trips. It grows the account faster only when its extra entries earn
    more than these costs.
* **Q-A, descriptive**: for every (variant, pool) pair that reached step 2 of the placebo, the placebo's median pooled
  mean against E0 and the share of its seeds with a pooled mean > 0. This says whether leaving at random, with V's
  timing profile, beat E0. Pairs that did not reach step 2 have no Q-A row.
* **DeepSeek (D11)**: every money-based figure above (M_p, M_P, D_m, g_m, wallets, drawdowns, multiples, busts,
  placebo percentiles and Q-A of the DeepSeek pool) is computed into `$WORK/<pin8>/ds_private/` only (section 3).
  DeepSeek rows in committed files and reports carry hold times, counts, win shares, exit reasons (LIQ included) and
  labels.

## 8. Select step (select period only): eligibility, the report, the owners' choice

### 8.1 Eligible variants, per pool

A variant V is **eligible in pool P** when all of these hold on the pool's picks:
1. M_P(V) > 0.
2. M_p(V) > 0 on at least 60% of the pool's picks: 14 of the 23 core picks, 9 of the 15 DeepSeek picks. A pick with no
   signal, or where V changed no trade, has M_p = 0 and does not count.
3. Except F7 and F7h: M_P(V) is above the 95th percentile (numpy's percentile, linear) of V's placebo pooled means in
   P.
4. The trades entered at quarter size, summed over the pool's picks, are >= E0's.

The gates are filters: only eligible variants can be shown as choosable, chosen or confirmed. They are not relaxed after
any number is seen.

### 8.2 The select report

The runner writes `out/select.json` and the Korean report `out/SELECT_KO.md`. For each pool, the report shows:
* first, E0's row: median hold hours, the shares of trades held over 4 h, 8 h and 18 h, trades entered, signals
  skipped while holding, win share;
* then **every one of the 84 variants**: the choosable (eligible) ones first, then the others marked "선택 불가", each
  part in canonical order, with, in this column order:
  1. id, plain Korean name, group, parameter count;
  2. median hold in hours and the shares of trades held over 4 h, 8 h and 18 h;
  3. trades entered against E0's (both counts and the change in percent), and signals skipped while holding;
  4. what it can cut a loss on before the hard stop: its category L0-L3 (5.3), and whether it is in the default set D;
  5. a pass or fail mark for each gate of 8.1 (gate 3: "안 돌림" when the pair failed gate 1, 2 or 4 and so never
     reached step 2; "해당 없음" for F7 and F7h), and the label "선택 가능" or "선택 불가";
  6. core, choosable rows only: M_P(V), the pooled quarter-size monthly log growth difference against E0, also written
     as a percent per month (100 x (e^M - 1)); and, reported only, the same at live size. No growth figure on a core
     row marked "선택 불가". DeepSeek rows: no money figure of any kind (D11);
  7. win share;
  8. choosable rows: the claim it may carry (8.5); "= F3.a" on F11.a and "= F3.b" on F11.b for the F7_RF_ONLY picks;
     and a mark on the variants the default of 8.4 would take in that pool (the default ranks by hold hours, so the
     mark carries no money figure in either pool);
* the number of variants failing the gates per pool, counted in sequence: gate 1; gate 2 among those passing 1; gate
  4 among those passing 1 and 2; gate 3 among those that reached step 2. No figure of a failing variant beyond the
  columns above.
* for the core pool, the Q-A rows of section 7 (DeepSeek Q-A stays private).

No confirm-period figure exists when the report is written. The main session sends the report to the owners and asks
for one answer per pool: up to two choosable ids from different groups, or "없음" (none). It does not recommend a
variant; it explains the columns and the default rule when asked.

### 8.3 The owners' choice

* Per pool, the owners choose **at most 2 choosable variants, from different groups**, or "없음". Each chosen variant is
  one global rule for all picks of that pool: no per-pick, per-coin, per-timeframe or per-side choice. Variants of
  categories L2 and L3 (5.3) can be chosen; the report shows that they cut losses on more than a deep structure break.
* They may choose the same variant for both pools, only if it is choosable in both. It then counts as one choice in
  each pool.
* **Deadline.** A pool's deadline is 48 h after the report's sending time (8.7). When a message is unclear, the main
  session may ask back, quoting the options; each question it sends moves the deadline of the pools it concerns to at
  least 24 h after that question was sent. An answer counts only when received before its pool's deadline.
* **No answer.** A pool with no answer (ids or "없음") before its deadline takes the default of 8.4. An explicit "없음"
  stays none; the default never fills it. Once `choice.json` is hashed, a later message is quoted in the confirm report
  and changes nothing.
* **Freeze.** From the sending of `SELECT_KO.md` until `choice.json` is hashed and pushed, no 2024-2026 result of any
  exit is sent to the owners or opened by the main session: no hunt test-period read (PREREG_HUNT_WIDE, round 2), no
  ledger print, no track-2 result, no full-grid extract and no other file that shows 2024-2026 trades or accounts by
  exit. Questions about such material are answered after the hash. A breach is written into `DEVIATIONS.md` with what
  was sent or opened, and the confirm report names it in its headline.
* **`out/choice.json`** holds: the report's sending time (UTC and KST, equal to `sent.json`); every owner message about
  the choice, verbatim (Korean) with its time; every question the main session sent, verbatim with its time; per pool
  the answer (ids or "없음"), the deadline that applied and whether the default was used; and the list of 2024-2026
  material the owners had received before the report was sent (at least the full grid's per-trade results of the 84
  exits in `ANALYSIS_KO.md`, `STRATEGIES_KO.md` and `STRATEGY_EVAL_KO.md`, and any hunt or ledger result sent to
  them).
* The sha256 of `choice.json` is appended to `PREREG_EXITFLEX.sha256`, committed and pushed **before the confirm**,
  once every pool has an answer or its deadline has passed. The runner refuses the confirm stage without it, and
  checks: each chosen id is choosable in its pool according to `select.json`; a pool has at most 2, from different
  groups; the send time equals `sent.json`; a pool marked "default used" has no answer timed before its deadline; and
  the default's ids equal what 8.4 gives on `select.json`.
* A choice is final once hashed. A select rerun changes it only as section 14 says. No confirm-period number is
  computed before the hash.

### 8.4 The default

Applied only to a pool that got no answer before its deadline (8.3):
* The candidates are the variants choosable in that pool **and** in the default set D (5.3: categories L0 and L1,
  which cut a loss before the hard stop only on a structure break at a loss of at least 0.5R, or not at all before a
  gain). Variants of L2 and L3 are never taken by default.
* First: the candidate with the shortest median hold in hours (quarter size, over all closed trades of the pool's
  accounts, as in section 7). Second: the candidate with the shortest median hold among those of a different group
  from the first. At most 2. Ties go to fewer parameters, then to the canonical order. No candidate: "none" for that
  pool.
* Why hold time and not growth: every choosable variant already beats E0 on pooled growth, on 60% of the picks and on
  its placebo (gates 1-3), and does not lose entries (gate 4); the owners' stated aim is a shorter hold (message 3);
  a ranking by hold uses no money figure, so the same rule serves the DeepSeek pool under D11; and it does not pick
  the variant whose 2021-2023 growth is most inflated by chance (the winner's curse of Known limit 2).
* The confirm report says, for each chosen pair, whether it is also what the default would have taken.

### 8.5 What a chosen variant may claim

Written into `select.json` and the Korean report:
* outside F7 and F7h: "beats E0 and beats a random exit with its timing profile" (for F11: "the strategy's own exit
  beats E0 and a random exit with its timing profile");
* F7 and F7h: "beats E0 by holding less; no claim about reading the market".

### 8.6 No eligible variant

With no choosable variant in a pool the result for that pool is "none". The owners still get the full table of 8.2
(hold hours, entries and gate marks of all 84 variants), so they can see where each variant fell short and decide with
the main session (promise (f)). With none in both pools, or "없음" or no variant in either, the study ends: nothing
runs on the confirm period and nothing enters the ledger. The owners are told plainly. The criteria are not relaxed
and no variant is re-tuned on this result. A new idea is a new pre-registration with its own select step.

### 8.7 Files

Every select-period figure of the core pool and every label and count of both pools go to `out/select.json`. The
DeepSeek money figures go to `$WORK/<pin8>/ds_private/select_ds.json`, whose sha256 is written into `select.json`. The
sha256 of `select.json`, of `SELECT_KO.md` and of `timing.json` are appended to `PREREG_EXITFLEX.sha256`, committed
and pushed before the report goes to the owners, so the menu they see is the one that was hashed. Right after sending,
and before reading any answer, the main session writes the sending time (UTC and KST) and the channel to
`out/sent.json`, appends its sha256, commits and pushes it. A select rerun is possible only under section 14.

## 9. Confirm rule (2024-01-01 .. 2026-10-01, once)

* The confirm run covers E0 and each chosen V on its pool's picks, at quarter size (deciding) and live size (reported).
  For a chosen V outside F7 and F7h it also runs V's placebo in that pool: 200 seeds, with the hazard table that V
  realised in this period on each pick.
* **Tests**: one per chosen (V, pool) pair, at most 4. Each is a one-sided circular moving-block bootstrap of the 33
  monthly D_m^P(V), blocks of 3 consecutive calendar months, 2,000 resamples, seed
  `run._seed("exitflex", "confirm", V, pool)`. p = (1 + resamples with mean <= 0) / 2,001.
* **Holm at 0.05 over all chosen (V, pool) pairs**: with k pairs, sort the p values ascending; the i-th smallest is
  significant when it and every smaller one satisfy p_(j) < 0.05 / (k - j + 1). With one pair, p < 0.05.
  DeepSeek p values enter Holm from `ds_private/` and are not written to any committed file (D11); a core pair's Holm
  label can depend on how DeepSeek p values rank, which is a label, not a figure.
* Reported beside it, deciding nothing: the iid bootstrap p of the same series, and a 95% percentile interval for
  M_P(V) from the block bootstrap (core only; for DeepSeek neither p, the interval nor M is shown, D11).
* **PASS** for (V, P) needs all three:
  1. (V, P) is Holm-significant.
  2. Except F7 and F7h: M_P(V) is above the 95th percentile of V's 200 confirm-period placebo pooled means in P.
  3. The trades entered over the pool's picks at quarter size are >= E0's.
* A PASS carries the claim of 8.5 and nothing more.
* A FAIL means this test did not show a gain. It does not show that there is none. The Korean report says so and, for
  core, gives the 95% interval.
* **The confirm report** (`out/REPORT_KO.md`) leads, per pool, with hold hours (median, shares over 4 h, 8 h, 18 h)
  and entries against E0, then PASS or FAIL, then for core M_P(V), p and the interval. DeepSeek rows: PASS or FAIL,
  the Holm and ledger labels, hold hours, entries, trade counts, win share. For each chosen pair it says whether the
  owners chose it or the default did, and whether it is also what the default would have taken (8.4); and it lists
  any freeze breach (8.3) and any owner message received after `choice.json` was hashed.
* Q-A on confirm, descriptive and outside the ledger: for each chosen V outside F7 and F7h, the placebo's median pooled
  mean against E0 (core), with the block-bootstrap p of the placebo's seed-mean D_m.
* It runs once. Bugs are handled by section 14. No other cut (a pick, a coin, a side, a year, a size) is a pass.
* Files: `out/confirm.json` (core figures and p values; DeepSeek labels, counts, win shares and hold times),
  `$WORK/<pin8>/ds_private/confirm_ds.json` (DeepSeek money figures and p values; its sha256 in `confirm.json`).

## 10. Ledger

* Each chosen (V, pool) pair is one test-period hypothesis in the program-wide ledger
  (`research/hunt/PREREG_HUNT_WIDE.md` R13 and section 14: a global BH at q = 0.10 and Holm at 0.05 over every
  test-period hypothesis of the program, printed as `research/hunt_r2/PREREG_HUNT_R2.md` section 8 defines). It enters
  with its block-bootstrap p from section 9. A DeepSeek pair's p is read by the ledger print from
  `ds_private/confirm_ds.json` and enters the BH and Holm computations; the print shows for that pair its BH and Holm
  labels only, never its p (D11). If the ledger print cannot omit a p, the DeepSeek pair's row is printed to the
  private folder and the committed print carries the labels only.
* From the hash of this file until `choice.json` is hashed, the ledger's print counts this study at its maximum, 4
  hypotheses at p = 1. After the choice it counts the number of chosen pairs; with none chosen, it counts none. A
  confirm rerun under section 14 adds its p values as further looks.
* The Korean report's headline shows, next to PASS or FAIL, the ledger status of each chosen pair (BH at q = 0.10 over
  the program). The ledger print changes no verdict of this study. The verdict carries the line "this confirm uses the
  same 33 months as the full grid, the hunt (v1, wide, round 2) and track 2".

## 11. After the confirm: the league restart

### 11.1 What happens on each outcome

* **PASS in at least one pool.** The Korean report goes to the owners. With their OK (their message verbatim, with its
  time, written into `research/fullgrid/DEVIATIONS.md` before the restart), the current league (the WATCH_PREREG run,
  started 2026-10-11) is stopped and a fresh league starts at the new install time (11.2-11.4). Without their OK
  nothing changes.
* **Which new exit runs.** Per pool, the passing variant. If two variants passed in one pool, the league runs one of
  them: the owners name it; with no answer within 48 h of the confirm report, the one with the smaller confirm p (for
  DeepSeek the runner compares the private p values and prints only the id). The choice is recorded in the same
  DEVIATIONS entry. A pool with no PASS runs its current exit only (11.2).
* **FAIL in both pools, or "none" (8.6).** Nothing new is deployed. The owners are told plainly, in Korean, with the
  core 95% intervals and the DeepSeek labels. They decide with the main session whether the league restarts with the
  current exits only, and with which accounts, or keeps running as it is. The decision is recorded in
  `research/fullgrid/DEVIATIONS.md`. This study ends there.

### 11.2 Accounts of the restarted league

Per pick of a pool with a PASS, five accounts:

| account | exit | size | side |
|---|---|---|---|
| `<id>-n` | the pool's new exit | live | the pick's |
| `<id>-nq` | the pool's new exit | quarter | the pick's |
| `<id>-e` | E0 (the pick's current exit) | live | the pick's |
| `<id>-eq` | E0 | quarter | the pick's |
| `<id>-nflip` | the pool's new exit | quarter | a seeded coin at the pick's signal times |

* Per pick of a pool with no PASS: `<id>-e`, `<id>-eq` and `<id>-eflip` (E0, live size, seeded coin, as the current
  league's `flip`). So 38 x 5 = 190 accounts only when both pools pass; 23 x 5 + 15 x 3 = 160 when only core passes;
  15 x 5 + 23 x 3 = 144 when only DeepSeek passes.
* Quarter size is every margin fraction x 1/4 with leverages kept, as the current `quarter` accounts and section 4.
* **The coin flip `-nflip`** takes the pick's signal times, its side from `league.flip_side(account id, signal close)`,
  and the pool's new exit with the same exit kinds as `-nq`: the same rule, the same mode, the same kind of
  take-profit. It runs at quarter size because C1 and C2 compare it with `-nq`.
  * For F11, let s be the strategy's side at the signal bar, side' the flip's side and f' the flip's fill. When side'
    = s, the flip uses the strategy's own level and target unchanged. When side' = -s, it uses the bar components of
    its own side under rule C3 (a state component that is true at i0 waits until it has been false at a close), and a
    level and target mirrored around its own fill at the distances the strategy's trade has at that signal:
    inv' = f' - side' x |f' - inv| and tgt' = f' + side' x (tgt - f') x s, the target only when (tgt - f') x s > 0.
    A NaN level or target gives none (C7). So a flipped trade on the five level-only DeepSeek strategies (F10_OTE,
    F11_TSOUP, F1_PVT_DIV, F5_BOX, F9_FVG) has an invalidation and, under F11.b, a target, like the strategy's own
    trades, instead of holding to the hard stop. Appendix A.0.
  * The flip's timing still differs from `-nq`'s under F11, because its own side's state components can start true
    and wait under C3 (Known limit 14). Its hold hours are reported beside `-nq`'s (11.5).
* All accounts start from $5,000 at the first chart close after the install, with the engine settings of section 4
  (quality_v1 sizing; leverage group core from the live strength rule, DeepSeek "normal", as the current league). No
  bar carries both flags (section 3) and the league asserts it, so `-e` and `-eq` are the exact twins of the study's
  E0.

### 11.3 The old record and the start

* Before the restart the current database and its start file are copied, unchanged, next to it
  (`league_watch_<start MMDD>_to_<stop UTC date>.db` and its `_start.json`) and into the off-site backup. They are kept
  read-only. The dashboard may show them as an archive.
* The restarted league uses a new database file with its own `meta.start_ms` = the new install time, floored to 5
  minutes, and its own start file. `runner.league_start`'s rule that a start-over keeps the recorded start is set aside
  for this one restart: the old start file moves with the copy, so it cannot be picked up. This is recorded as a
  deviation in `research/fullgrid/DEVIATIONS.md` at the restart, with the time, the commit and the owners' OK.
* `runner.league_start` uses an explicit `CANDLEAGUE_START` before "now" for a fresh database. The restart steps
  therefore unset `CANDLEAGUE_START` in the shell and remove it from the service's environment file before the first
  pass. After the first pass, `meta.start_ms` is checked against the install time floored to 5 minutes; a mismatch
  stops the league before any trade is shown.
* **Dates move.** The restart replaces WATCH_PREREG's checkpoints of 2026-11-11 and 2026-12-11 on this league with the
  restart's own checks at install + 30 and + 61 days (11.5). Any real-money step that waits for a forward checkpoint
  therefore waits for those later dates.
* WATCH_PREREG's checks (C1 2026-11-11, C2 2026-12-11, repeat 2027-01-11) need its `cand`, `base` and `flip` accounts on
  the current league. A league stopped before its C1 gives them no checkpoint; its record up to the stop is reported
  once, as reference, deciding nothing. The restarted league has no `base` or `exitonly` accounts. Whether
  WATCH_PREREG's own question (does a pick earn forward; its section 4, the path to real money) continues on the
  restarted league's E0 accounts, and how, is decided by the main session and the owners and recorded in
  `research/fullgrid/DEVIATIONS.md` before the restart. This file does not decide it.

### 11.4 League changes

Part of this exists as a draft written from the first revision of this file (core only, a separate league):
`candleague/rulex.py` (`RuleMixin`, `RuleEngine`, `RuleLadderEngine`, `make_engine`, `chunk_rule`, `accounts`,
`pick_list`, `register_f11`, `audit_restored`), `runner.make_rule_league` and `tests/test_candleague_rulex.py`, with
its own `rule_league.db` and accounts `-f`, `-f-live`, `-f-flip`, `-f0` and `-f0-live`. The study side is
`research/exitflex/kernel_x.py`. Before the restart, the league code must carry the following, and the parity test of
item 13 must pass. Each item is a change to the draft where the draft differs.

1. **Database and accounts.** A fresh database and start (11.3) for the restarted league itself, not a side
   `rule_league.db`. The accounts and ids of 11.2 (`-n`, `-nq`, `-e`, `-eq`, `-nflip`, `-eflip`) replace the draft's
   `-f` family. `runner.fingerprint` covers every account of the new database.
2. **Both pools.** The draft's `pick_list` refuses every DeepSeek pick ("DeepSeek never gets rule accounts, D11"); that
   refusal is removed. D11 governs what is shown, not what runs: DeepSeek rule accounts run like the current league's
   DeepSeek accounts, and their money is hidden as section 3 and the dashboard setting say.
3. **Per-close rule inputs** (`chunk_rule`): for every account whose exit has a rule (`-n`, `-nq`, `-nflip`), every
   chart close of every coin: close, ATR14, EMA(n), swing confirmations, both raw signal flags, the strategy's own
   component booleans of both sides (Appendix A), plus the 15m closes for q15. `league.chunk_signals` today sends only
   bars that carry a signal.
4. **F11 as Appendix A defines it**, not the draft's plug-in. The draft fires F11 on any true per-bar
   `long_exit` / `short_exit` flag, has no arming, no per-position level test, and a target only when the rule carries
   `use_target`. Run as it is, it would fire at the first check on an N03_ADX_GC long entered after an EMA whipsaw
   (rule C3 forbids that), and it cannot express the level tests of N13_3OUTSIDE, N19_FIB_CHOP and five DeepSeek
   strategies. Required: each component carries its kind (state or event) with C3 arming from i0; per-position levels
   and targets, fixed at i0, travel in the signal's meta (`meta['native_inv']`, `meta['native_tgt']`) and the level
   is tested at every close; F11.a and F11.b are the mode (5.2, rule C8), not a `use_target` flag; flipped positions follow
   11.2; the arrays come from `research/exitflex/native.py` and `native_ds.py`, the same code the study runs.
5. **Guard**: the league asserts that no offered bar carries both flags (section 3).
6. **Step order** stays in `RuleMixin.step` (`candleague/rulex.py`): funding; then, if a rule exit is due at this
   minute and the open gaps past neither liquidation, the stop nor the take-profit, close as RULE; then entries
   (`_handle_entries`); then `_handle_exit`. A gapped open leaves the exit to `_handle_exit`, so entries at that minute
   stay blocked, as in `kernel_x`.
7. **Rule state** (F1 reference, F2 arm, F5, F8 and F9 arms, F7 and F7h deadlines, F11 component arms and fixed
   levels, X and T_X) is kept in the position's signal meta (`meta['rx']`). `engine_state` and `restore_engine` save
   and restore it, and `audit_restored` checks it against a recomputation from the bars.
8. **Native target**: the LadderTP-style `tp_price` assignment, set only when the level lies beyond `entry_price`,
   without the lock.
9. **No new entry from a time.** Per pool, a field `no_entry_from_ms` on the `-n`, `-nq` and `-nflip` accounts of that
   pool, empty by default. It is part of the account definition, so `runner.fingerprint` covers it and a start-over
   reproduces it. It is set only from the output of the committed C1 script (11.5). From that time the account takes
   no new entry; an open position closes by its own rules. A test: a start-over after the field is set gives the same
   trades as the run that set it.
10. **Counters.** A table `acct_day` (account, UTC day, signals offered, entered, skipped while holding, rejected,
    trades closed), written in the same database commit as each chunk. Today `paramshadow.replay_day` clears
    `e.outcomes` at every step, so skipped and rejected signals are not kept.
11. **Daily marks.** At every 00:00 UTC, per account: the realised wallet and, when a position is open, its mark value:
    the last 1m close (last price) of the held coin before 00:00, less the taker fee and slippage of a market exit,
    after the funding the position had paid by then. Table `acct_mark`, written in the same commit. C1, C2 and the
    weekly notes read it.
12. **Snapshot.** Per account, hold-time aggregates over every closed trade since the start (count, median hold hours,
    shares held over 4 h, 8 h and 18 h) and the counters of item 10 are added to the snapshot. The last-200 trade list
    (`runner.LAST_TRADES`) is not used for any check.
13. **End-to-end parity test, before the start**: `League.advance` and `paramshadow.replay_day` against `kernel_x` on
    the same 1m bars, for every pick of both pools and every account kind of 11.2 (`-nflip` under F11.a and F11.b
    included), over at least 60 days of archive data before 2026-10-01. Trade for trade: fill minute, exit minute,
    reason, leverage, P&L to 1e-9 of the wallet. One run restarts the engine in the middle of an open position.
    * The DeepSeek signals and the native arrays computed from the league's `chart_frame` window must equal the
      study's from the full history at every bar used (the range filter, Heikin-Ashi open, PSAR and higher-timeframe
      Heikin-Ashi recursions depend on where the series starts). Where they differ, the window (`chart_frame`,
      `sigservice.window_5m`) is lengthened for that strategy until they match at every bar used, and the test reruns.
    * The league's live minutes keep zero-volume minutes, which `data.py` drops. For the restarted accounts the league
      drops them before the engine, as `data.py` does. The test includes a coin whose bin-last minute is missing or has
      zero volume while the other coins trade, and checks that fills and rule exits land on the minute `kernel_x`
      uses.
    * The league engine also runs T2's hand-built paths (section 13) for every family and every F11 strategy, from
      shared fixtures, because 60 days of archive may never reach the rare branches (N03_ADX_GC's EMA leg after a
      whipsaw, merged checks over missing bins, a gap at a rule minute, a native target behind the fill, a restore with
      queued chart records).
    * The league does not start until the test passes. `tests/test_candleague_exits.py` is the model; an engine-level
      test alone is not enough. The test prints pass or fail and counts only.
14. **Check data.** The check script of 11.5 runs on the league server and reads the league database (`trades`,
    `acct_day`, `acct_mark`) for both pools, whatever `CANDLEAGUE_DS_MONEY` is set to. It prints DeepSeek labels,
    counts, win shares and hold hours only; any DeepSeek money figure it needs stays in a private folder on the server.

### 11.5 Forward checks (pre-registered here)

* Days count from the restart's install time. All accounts start together, so every comparison is over identical days.
* **Check times**: C1 at 00:00 UTC of the install's UTC date + 30 days; C2 at + 61 days; the repeat at + 92 days.
* **Wallet at a time T**: W_T is the daily mark of 11.4 item 11 at T: the realised wallet plus, for a position open at
  T, its mark value net of the costs of a market exit. Marking matters because E0 holds longer and so is more often
  caught open at a check. The realised-only wallet is reported beside.
* For an account, G = ln(W_T / 5,000) / months, months = days / (365.25 / 12). A pool's G for a role (`-nq`, `-eq`,
  `-nflip`, ...) is the mean of G over the pool's picks: the **pooled monthly log growth**.
* **C1** (install + 30 days). In each pool where a new exit runs: if G(`-nq`) < G(`-eq`) and G(`-nq`) < G(`-nflip`),
  the new exit **stops** in that pool: the committed C1 script writes `no_entry_from_ms` = the C1 time on that pool's
  `-n`, `-nq` and `-nflip` accounts (11.4 item 9); open positions close by their own rules; the record is kept. The E0
  accounts continue. A pool stopped at C1 is "not shown ahead" and has no C2. Otherwise the new exit continues.
* **C2** (install + 61 days). The new exit is **shown ahead** in a pool when all four hold:
  1. G(`-nq`) > G(`-eq`), with a one-sided exact sign-flip test p < 0.03 on the weekly differences:
     * weeks are UTC weeks from Monday 00:00; the part-week from the install to the first Monday is merged into the
       first full week, and the part-week from the last Monday to the check time into the last full week;
     * d_w = the mean over the pool's picks of [ln W_w(`-nq`) - ln W_(w-1)(`-nq`)] - [ln W_w(`-eq`) -
       ln W_(w-1)(`-eq`)], with W at the week boundaries as above and W = 5,000 at the install;
     * p = the share of the 2^n sign patterns e (e_w = +1 or -1) whose mean of e_w x d_w is >= the observed mean of
       d_w, all patterns counted (n is about 9 at C2 and 13 at the repeat); above n = 20, 20,000 random patterns with
       seed `run._seed("exitflex", "league", pool, check date)` and p = (1 + count) / 20,001.
  2. G(`-nq`) > G(`-nflip`).
  3. At least 150 closed trades of the pool's `-nq` accounts.
  4. G(`-nq`) > 0: the new exit's quarter-size accounts grew, not only lost less than E0.

  If it does not pass, C2 is repeated once at install + 92 days, with the same rules on all days from the restart and
  p < 0.02 in condition 1. The two looks split 0.05 between them, so per pool the chance that an exit no better than E0
  is shown ahead at either look is at most about 5%; over the two pools together it is at most about 10% (Known limit
  12). A pool that passes neither is "not shown ahead": this study does not propose its new exit for real money, and
  whether its accounts keep running is the owners' decision.
* **What "shown ahead" means.** The new exit beat E0 and its own coin flip over these days, by a margin a sign-flip test
  does not put down to chance, and its quarter-size accounts grew. It does not by itself replace E0 in the league or
  start any real-money step (11.6); that follows the program's process and the WATCH-style decision made before the
  restart (11.3).
* **Reported beside, deciding nothing**: the live-size accounts (`-n` against `-e`; wallets, drawdowns and busts for
  core only); the per-trade line in the spirit of CONTRACT.md section 2, for core only: the mean per trade, as a
  fraction of the wallet, of `-nq` and `-eq`, each against 0 and against `-nflip`'s (all three at quarter size; there
  is no `base`); for every role: trades entered, signals skipped while holding and rejected (11.4 item 10), median hold
  hours and the shares held over 4 h, 8 h and 18 h, win share; `-nflip`'s hold hours next to `-nq`'s; the
  realised-only wallets next to the marked ones.
* **Weekly**: the dashboard and the Korean note show these per pool, hold hours and entries first. DeepSeek weekly
  lines carry labels, counts, win shares and hold hours only.
* **DeepSeek pool**: C1 and C2 are computed the same way from the server database (11.4 item 14) and shown as labels
  (stop or continue; shown ahead or not), with trade counts, win shares and hold hours only (D11).
* The checks are computed by a script committed before C1, which reads only the league database tables named in 11.4
  (`trades`, `acct_day`, `acct_mark`) and this file's rules (as WATCH_PREREG 5).

### 11.6 Real money

Real money is not decided by this study. That stays the owners' decision under the program's process.

## 12. What is not in scope, and known limits

* **Not in scope**:
  * a "판단" (judgement) exit by a person or an AI;
  * partial exits (the owners asked for 전량, the whole position);
  * combinations of families other than F9;
  * q15 versions of F2, F3, F5, F6, F8, F10 and F11: on 1h and 4h picks these react only at the pick's own closes.
    Inside one 4h bar only F1 q15, F4 q15 and F9 q15 can react; on a 4h pick F7h.H4 caps a hold at one bar;
  * a per-strategy choice among families (each strategy's own exit is F11, one global variant);
  * F11 with both the strategy's target and the pick's R take-profit (F11.a uses only the pick's, F11.b only the
    strategy's);
  * moving the hard stop (breakeven or lock), and intrabar moving stops (the trailing stops of the DOGE and S4_BB_BBP
    sources);
  * changes to entries, numbers, timeframes, leverage or size rules;
  * per-pick, per-coin, per-side or per-regime choices;
  * DeepSeek money figures in any committed file or owner report (D11);
  * the rule bot;
  * the hunt's systems and other coins;
  * rule exits by maker limit orders.
* **Known limits**:
  1. **2024-2026 is not blind.** The 38 picks were chosen after the full grid's 2024-2026 results had been seen
     (WATCH_PREREG 0), and E0 is part of each pick. On the confirm period E0 carries that selection, which tilts the
     confirm against the variants. The main session states that it opened no hunt result (section 15), so F4's confirm
     is not knowingly a second look at chandelier exits on 2024-2026. The clean check is the league's forward record.
  2. **2021-2023 was used for both, parts of it were looked at, and the owners' choice is not blind to 2024-2026.** E0
     was chosen on 2021-2023 (the plateau rule), which tilts the select step against the variants. The best of 84
     variants on 2021-2023 also looks better there than it is (the winner's curse); the single confirm and Holm address
     that, and Holm counts the pairs chosen, not the menu. The owners choose by hand, and a hand choice can carry what
     its maker knows of 2024-2026, which an automatic rule cannot: the owners have seen the full grid's 2024-2026
     per-trade results of the 84 exits, including short against long take-profits, which says something about hold
     length on the confirm period. So a chosen variant's confirm is not a clean out-of-sample test of the choice. Three
     things limit this: the freeze of 8.3 (no new 2024-2026 exit result reaches the owners or the main session
     between the report and the hash), the list in `choice.json` of the 2024-2026 material the owners already had,
     and the confirm report's line saying whether each chosen pair is also what the hold-ranked default would have
     taken. The league's forward record is the clean check. The main session saw select-period account results of E0
     on the 23 core picks at live size (section 15), not of any variant.
  3. **Two static inputs are not cut at 2024-01-01.** The core leverage group (`run.best_flags`) uses
     `paperbot/quality_edges.json`, whose quintile edges were fitted on 2021-08-01..2024-06-30, six confirm months
     included; DeepSeek picks are always "normal" and do not use it. `research/fullgrid/exchange.json` holds 2026
     brackets and order-size rules. Both act on E0 and every variant alike. T3 cannot see them.
  4. The 1m stop-first rule touches only arms with a take-profit (section 2). The count is reported.
  5. **Power is limited.** There are 33 months. The core pool has 23 picks and the DeepSeek pool 15, and the picks of a
     pool are correlated (the same six coins, related strategies). The pooled monthly series counts each month once, so
     a real but small gain may not pass, more so in the DeepSeek pool. No minimum detectable effect is computed; the
     95% interval of section 9 stands in for it (core).
  6. Quarter size decides and the league judges at quarter size. Live size is reported only. At live size a few
     busts can reverse the order.
  7. A rule exit pays taker fee plus slippage, while a fixed take-profit pays the maker fee. That favours E0 slightly,
     as it would live.
  8. Wallets are realised at exits in the study, so a position held across a month end counts in the month it closes.
     (The league's checks mark open positions, 11.5.)
  9. The placebo matches age, profit sign and V's precondition. A rule could still beat it through finer timing
     (for example, the hour of day) that carries no market information. For F3, F4, F10 and F11 (except F12_MSS_DISP's
     live-level test) it matches age and profit sign only; for N03_ADX_GC and N10_HA_PSAR it does not see which of
     their legs is armed. The placebo's draws are shared by picks that hold the same coin at the same check close, but
     not across coins, while one market move can fire V on several coins at once; the placebo's pooled mean may
     therefore still spread a little less than V's would under the null, which makes gate 3 slightly easier to pass.
  10. **Each strategy's own exit is a reading.** For N03_ADX_GC, N09_ALLIG_AROON, N10_HA_PSAR, OBV_S, N19_FIB_CHOP and
      the eight DeepSeek strategies no exit by the strategy's author exists in the repository; their exits were derived
      from the entry logic and the pattern (Appendix A). DOGE and S4_BB_BBP use their source's own signal exit, and
      N13_3OUTSIDE its port's opposite signal plus its pattern level. The readings were written from code before any
      number of them was computed. Another reading could do better or worse. FINGRAD's two-close confirmation is not
      used (rule C2). The core drafter listed what it opened and disclosed one grep print (section 15). The DeepSeek
      drafter cited only code but gave no explicit statement that it saw no performance figure: for the eight DeepSeek
      readings, blindness is **not stated**.
  11. F11.a equals F3.a and F11.b equals F3.b on the three F7_RF_ONLY picks. The select report marks both pairs; they
      are not counted twice in any pick table.
  12. **League checks.** Each pool's C2 splits 0.05 over its two looks (0.03, then 0.02) with an exact sign-flip test on
      about 9, then 13 weekly differences, so a false "shown ahead" in one pool is at most about 5%, and in at least one
      of the two pools at most about 10%. With so few weeks only a large difference can pass; a real but modest gain
      will often not.
  13. **The restart ends WATCH_PREREG's checks on the current league** (11.3). Its forward record so far is short and
      is kept as a backup.
  14. **The F11 coin flip is not timing-matched.** A flipped position uses its own side's components under rule C3, and
      a state component of that side is often true at i0 (DOGE's EMA leg, the range filter's direction, OBV against its
      average), so it waits for a false close before it can fire, while the strategy's own trade can fire from the first
      check. Mirrored levels and targets (11.2) remove the worst case, a flip with no exit but the hard stop. Under
      F11 the comparison of `-nq` with `-nflip` in C1 and C2 is therefore a check of direction with a somewhat
      different hold profile; `-nflip`'s hold hours are reported beside `-nq`'s.
  15. **Bar-close checks on 4h picks.** Apart from F1 q15, F4 q15 and F9 q15, no rule reacts inside a 4h bar; on the
      13 picks on 4h (6 core, 7 DeepSeek), only F7h caps a hold below 2 days (at 4, 8 or 16 h).

## 13. Reproducibility

* Code lives in `research/exitflex/`:
  * `data_x.py`: loading through `research/fullgrid/data.py` `load` (the `hc.py` "1m" path, shift 0), the cut and the
    cache rules below;
  * `kernel_x.py`;
  * `native.py` (the eight core strategies' own exits) and `native_ds.py` (the eight DeepSeek strategies'), Appendix A;
  * `run_x.py`: the timing, select (steps 1 and 2), confirm, audit and report stages;
  * `test_exitflex.py`;
  * any helper module the coder adds (for example `metrics.py`, `placebo.py`).

  **Code must match this revision before the pin.** The modules already in the folder were written against earlier
  revisions. Before the pin: `kernel_x.py` carries F7h (82 rule variants + the 2 F11 variants = 84) and the F11
  mechanics of Appendix A (component kinds, C3 arming from i0, per-position levels and targets); `placebo.py` uses the
  seed base without the pick id and the strata z of section 6; `metrics.py` drops its header line "this study runs
  the core pool only", applies the gates per pool (14 of 23, 9 of 15), replaces `choose_variants`' "median_Mp" ranking
  with the default of 8.4 (set D, shortest pooled median hold, ties by parameter count then canonical order, at most
  2 from different groups, per pool, only for a pool with no answer) and gives `claim_of` the F7h and F11 wording of
  8.5. T7 below checks this. The league side (`candleague/rulex.py` and its test) is not pinned here; it must meet
  11.4 and its parity test before the restart.

  Every `.py` file in `research/exitflex/` is pinned in `PREREG_EXITFLEX.sha256` together with this file,
  `data_pin.json` and the sha256 of each input:

  | input | sha256 |
  |---|---|
  | `research/fullgrid/kernel.py` | `a4995c15…` |
  | `research/fullgrid/run.py` | `4e02df9c…` |
  | `research/fullgrid/sizing.py` | `3dc00c24…` |
  | `research/fullgrid/data.py` | `6691424b…` |
  | `research/fullgrid/ds_defs.py` | `40a752cc…` |
  | `research/deepseek200/lib_c.py` | `3210c602…` |
  | `research/library/lib.py` | `5c3e1083…` |
  | `research/search/search.py` | `06920240…` |
  | `research/fullgrid/exchange.json` | `176e234b…` |
  | `research/fullgrid/diag/watch_sel.json` | `f6902feb…` |
  | `candleague/data/candidates.json` | `dd627ec0…` |
  | `paperbot/quality_edges.json` | `8b4fc48d…` |
  | `third_party/sweep/harness/vendor/fg_indicators.py` | `bf43c1b8…` |
  | `third_party/sweep/harness/vendor/pine_indicators.py` | `938c9545…` |
  | `fg1m/build.json` | `824c9d1a…` |
  | the `param_defs` | `research/entry_study/DEFS_BC.sha256` |

  The runner also records the sha256 of every module file it loads from `research/library`, `research/search` and
  `third_party/sweep/harness/vendor` at the select run, and the confirm stage refuses on any difference. Repo HEAD when
  this revision was written: `20ae99e`. Versions: Python 3.11, numpy 2.0.2, pandas 2.3.3, numba 0.60.0. The runner
  records the versions it runs with.
* **Caches.**
  * exitflex uses no disk cache it does not own. `hc.py`'s frame pickles (`frames_5m`, `frames_1m`) and signal cache
    (`cache/sig_*`) are not read. `run.FRAME_DIR` points into the stage's own folder.
  * exitflex's own disk caches live under `$WORK/<pin8>/<stage>/`, where `$WORK` is a folder outside the repo named in
    `data_pin.json`, `<pin8>` the first 8 hex digits of the pin, and `<stage>` one of `timing`, `select`, `confirm`,
    `t3-<cut>`. A stage deletes its folder before it starts. Cache keys include the pin hash and the cut time.
  * The cut arrays are written as their own data folder, `$WORK/<pin8>/cut-<cut time>/1m/<SYM>.npz`. Every `run.py`
    cache keyed by the data folder (`frame`, `best_flags`, `struct_levels`, `all_minutes`) therefore sees a different
    key for cut and full data. The `ds_defs` cache dicts are per process and per series.
  * Memory caches (those `lru_cache`s, the `run.M` memo and `run._DS_CACHE`) live only inside one process. Every
    stage, and each side of each T3 comparison, runs in its own fresh process.
  * Per-account result files of the core picks live under `$WORK/<pin8>/results/<stage>/`; those of the DeepSeek picks,
    and every DeepSeek money figure and p value, under `$WORK/<pin8>/ds_private/` (its `results/<stage>/` included);
    all outside the repository, never committed. Only `timing.json`, `select.json`, `SELECT_KO.md`, `sent.json`,
    `choice.json` (and `choice_r2.json` under section 14), `confirm.json` and `REPORT_KO.md` go into
    `research/exitflex/out/`.
* **Tests that must pass before any select run.** They print only pass or fail and counts of cases, never a
  performance figure.
  * **T1 parity.** With no rule, no placebo and the period end after the data end, `_trade_x` must equal
    `kernel._trade`: wallet change to 1e-9, exit index, reason and leverage. `account_x` must equal `kernel.account`:
    statuses, P&L, exit times, reasons, leverages and the final wallet. Test inputs:
    * synthetic 1m paths with gaps, missing minutes, funding and a mark price that differs from the last price, all 84
      kernel exits, both sides, both leverage groups, at scales 0.25 and 1;
    * the select-period signals of all 38 picks (cut arrays) under E0 at both sizes.
  * **T2 rule paths.** Hand-built paths for every family, both sides, check that:
    * the rule fires at the right check close and not before;
    * the exit fills at the check's minute (the entry helper) with slippage and taker, and never on the entry minute;
    * an entry and a rule exit decided at the same close land on the same minute, also when the bin's last minute is
      missing;
    * F1's starting reference and its upward-only ratchet work;
    * F2's arm works;
    * F3's reversal entry happens (5.4.8), and a built bar with both flags set stops the run (section 3);
    * F4's level is right;
    * F5's and F8's arms and F5's giveback match hand-computed net R;
    * F6 fires only below -d;
    * F7's timing is right; F7h fires at the first close at or after C0 + H hours on 15m, 30m, 1h and 4h picks,
      including when that bin is missing;
    * F9 fires on either side and not otherwise;
    * F10 fires only in profit after N bars without a new extreme;
    * F11, for each of the 16 strategies and both sides: each component fires at the right close and not before, the
      arm of rule C3 works (including N03_ADX_GC's EMA leg after a whipsaw and N10_HA_PSAR's candle leg true at i0),
      levels and targets are fixed at i0, a target at or behind the fill is no target, merged checks fire on any bar,
      and F11.a keeps the pick's take-profit while F11.b uses the strategy's target or none;
    * F11 coin-flip positions (11.2), under F11.a and F11.b: a flipped trade on a level-only DeepSeek strategy gets the
      mirrored level and target and fires on them; a flipped trade whose own-side state component is true at i0 waits
      under C3; a flip on the strategy's own side equals the strategy's trade;
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
    * compared: every pick's signals (both sides, both pools) and core leverage groups, ATR14, EMA(10, 20, 50), the
      swings (w = 2, 3, 5) with their confirmation bars, F1's reference series, the 15m bars, and every F11 array of
      Appendix A (components of both sides, levels and targets at the signal bars);
    * each side of each cut runs in its own fresh process with its own cache folder;
    * it also asserts that the cut arrays hold no minute at or after the cut, and that the cut frames' last bar closes
      at or before the cut.

    Any difference stops the run.
  * **T4 placebo.**
    * With h = 0 everywhere the result equals the mode's base account. With h = 1 everywhere the exit comes at the
      first check.
    * The draws depend only on (V, period, seed, coin, time) and are reproducible. Two picks with identical inputs
      (the same coin, signals and hazard table, different ids) give identical placebo exits.
    * Hand-computed hazard tables on built paths for F5 (unarmed checks counted in the denominator, only RULE in the
      numerator) and for F6 (loss-only exits), including a check whose minute gaps through the stop (counted in
      neither).
    * The strata z of section 6 on built paths: F6.d0.5 and F9 (z = 1 only below -0.5R with a reference, or for F9
      after the arm), F8 (armed and a reference), F11 for F12_MSS_DISP (z = 0 while no live swing level exists) and
      for a level-only DeepSeek strategy with a NaN level (z = 0).
    * The placebo's own stratum uses the frozen state of step 0.
    * F11.b's placebo keeps the native target.
    * Two steps: on a small built case, running every placebo and running only those of step 2 give the same
      eligible set.
  * **T5 causality of the decisions.** For every family at its middle parameter, and F11 in both modes for every
    strategy, on synthetic paths and on 500 sampled (trade, check) pairs per pool from the select-period cut arrays:
    change the OHLC and mark of minute j and of every later minute, and of every chart bar closing after the check
    close. The rule decision at j, the placebo stratum at j and every arm flag must stay identical. Only decisions are
    compared; no P&L is kept.
  * **T6 native parity.** `native.py`, where it re-derives an entry (N13_3OUTSIDE), and `native_ds.py` reproduce
    `run.signals` bar for bar; DOGE's components reproduce the source's `long_exit` and `short_exit`; every final
    DeepSeek signal bar receives its levels (Appendix A).
  * **T7 selection logic**, on synthetic `select.json`-shaped inputs with no real figure:
    * the gates per pool (14 of 23 core picks, 9 of 15 DeepSeek picks; a zero M_p does not count), F7 and F7h exempt
      from gate 3, and the gate-failure counts in sequence (8.2);
    * the default of 8.4 per pool: only set D, shortest pooled median hold first, ties by parameter count then
      canonical order, the second from a different group, "none" when no candidate; applied only to a pool with no
      answer before its deadline; an explicit "없음" stays none;
    * the group rule (at most 2 per pool, different groups; one variant may serve both pools when choosable in both);
    * the validation of `choice.json` and `choice_r2.json` (8.3, 14): unknown or unchoosable ids, three ids, two ids of
      one group, a "default used" flag with an answer timed before the deadline, a send time that differs from
      `sent.json`, a default that differs from 8.4's output, and a swapped id that was still choosable after a rerun
      are each refused;
    * a D11 whitelist: a synthetic `select.json`, `confirm.json`, `SELECT_KO.md` and `REPORT_KO.md` with a DeepSeek
      money figure or p value planted in any DeepSeek row are refused; the allowed fields pass;
    * `claim_of` gives the 8.5 wording for F7, F7h, F11 and the rest.
* Seeds use `run._seed`: the first 8 hex digits of the sha256 of the "|"-joined parts.
* **Order of work**:
  1. Code, tests and `data_pin.json`, then the pin, commit and push.
  2. The timing stage (seconds only), the seed count of 5.3, `out/timing.json`, commit and push.
  3. The select run, in fresh processes: step 1, then step 2. It writes `out/select.json` and `out/SELECT_KO.md`; the
     post-run audits of section 14 run; the hashes of `select.json`, `SELECT_KO.md` and `timing.json` are appended,
     then commit and push. The main session sends the report to the owners, then writes, hashes, commits and pushes
     `out/sent.json` before reading any answer (8.7). The freeze of 8.3 starts.
  4. The owners' answers per pool (or the default for a pool with none by its deadline), `out/choice.json`, its hash
     appended, commit and push. The freeze ends.
  5. The confirm run, once, in a fresh process, writes `out/confirm.json`; the audits run; then `out/REPORT_KO.md` and
     the ledger print.
  6. After a PASS and the owners' OK: the league changes of 11.4 with their parity test, the DEVIATIONS entry, the
     restart, then C1 and C2 (11.5).

  The runner prints the git commit and refuses to run on a hash mismatch.

## 14. Failure handling, bugs and looks

* **A look** is any performance figure (P&L, growth, wallet, win share, hold time, exit-reason count, trades entered or
  skipped per arm) written to a file or a screen that a person or an agent reads. Tests and audits print only pass or
  fail and counts of cases; the timing stage prints only times. DeepSeek money figures are never a look: nobody reads
  them (section 3).
* **Tests.** If T1-T7 cannot pass without changing a rule of this file, nothing runs. The change is filed in
  `DEVIATIONS.md`, with the reason, before any run.
* **Crash and resume.** Each stage writes one result file per (pick, arm, size, seed block) under
  `$WORK/<pin8>/results/<stage>/` (DeepSeek picks: `$WORK/<pin8>/ds_private/results/<stage>/`), atomically. A resume computes only the missing files. Nothing is read, summarised or
  printed until every file of the stage exists; then the stage's summary runs once. Step 2 of the select stage starts
  only when every step-1 file exists, and the runner passes it only the gate flags and the hazard tables of step 1;
  nothing of step 1 is printed before step 2 ends.
* **Zero-signal picks** have M_p = 0 and do not count as > 0. **Busts** follow section 7, for E0, variants and
  placebos alike.
* **Post-run audits**, run after the select run and after the confirm run whatever the outcome. They print pass or
  fail only.
  * A1: T1-T7 rerun at the run's commit.
  * A2: for every account, signals offered = entered + skipped + rejected + no fill + after bust.
  * A3: every RULE and RAND exit lies at the check minute of one of the position's checks, at that minute's open
    with slippage.
  * A4: every account's final wallet equals $5,000 plus the sum of its trades' wallet changes (to 1e-9 relative).
  * A5 (select only): no array loaded by the select process holds a minute at or after 2024-01-01.
  * A6: E0 through `kernel_x` equals `kernel.account` on the same signals and period end.
  * A7: each placebo's realised exit rate per stratum lies within a 99.9% binomial band around h.
  * A8: no committed file of this study holds a DeepSeek money figure or p value: every DeepSeek row of `select.json`,
    `confirm.json`, `SELECT_KO.md` and `REPORT_KO.md` carries only the allowed fields (counts, win shares, hold times,
    exit reasons, labels).
* **A bug found by an audit or by T1-T7.** It is fixed and recorded in `DEVIATIONS.md` before the rerun's output is
  read, and the stage is rerun once.
  * Select stage: allowed once, before any confirm. The rerun's eligible sets decide; both reports are kept, and the
    rerun's `select.json` and `SELECT_KO.md` are hashed and sent as in 8.7. If `choice.json` was already hashed, the
    rerun voids a chosen id only when it is no longer choosable in its pool. A chosen id that is still choosable stands
    and cannot be swapped or dropped; a pool answered "없음" stays none. For each voided id the owners may name a
    replacement from the rerun's choosable set (the group rule of 8.3 applies with the ids that stand) or "없음", under
    the deadline, freeze and default rules of 8.3 and 8.4 with a new 48 h clock from the rerun report's sending. This
    goes to `out/choice_r2.json`, hashed, committed and pushed before the confirm. Before `choice.json` is hashed, the
    choice simply proceeds on the rerun's report with a new clock.
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
* **The first revision** was written by another sub-session on 2026-10-12 (about 02:00 UTC). It read:
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
* **The native-exit definitions (Appendix A)** were drafted by two agents for the main session on 2026-10-12.
  * The core drafter read code and pre-registration text only: the 8 `param_defs`; vendor `strategies.py`,
    `ports12.py`, `doge_strategy.py`, `fg_fast.py`, `fg_indicators.py`, `pine_indicators.py`;
    `kernel.structure_levels` and the `_trade` header; `run.py` `build_frame`, `frame`, `signals`, `best_flags`,
    `core_module`; the `memo.py` header; the `candleague/exits.py` header and `LadderTP`;
    `third_party/sweep/PREREG.md` lines 48-90; the combo and exit fields of `candidates.json`; the text fields of
    `strategies_ko.json`; `PREREG_EXITFLEX.md`; `README_KO.md`. Its disclosure, as given: "while searching the repo for
    the OBV Pine source, one grep printed six lines from result files: research/binance_data/RESULTS_BINANCE.md:150,
    research/entry_study/RESULTS_ENTRY_BC.md:204 and :207, research/fullgrid/STRATEGY_EVAL_KO.md:1329,
    research/fullgrid/ANALYSIS_KO.md:191 and :341. They are about OBV_B and the entry study; ANALYSIS_KO:191 names
    strategy/timeframe cells, including N10 4h, N13 1h, N19 15m/30m, without a number. None of these lines was used for
    any choice here."
  * The DeepSeek drafter's text cites only code (`ds_defs.py`, `lib_c.py`, `search.htf_series`) and states no other
    reading. It gave no explicit statement of what it opened or that it saw no performance figure, so for the eight
    DeepSeek readings blindness is **not stated** (Known limit 10). A review of the second revision checked Appendix A
    against the code (`ds_defs.structure` and `prev_hi`, the zone table's kill-after-touch, N13's lag order, N19's
    lines, DOGE's `long_exit`, `htf_series`) and found no look-ahead.
* **This revision** (second, about 02:40 UTC) was written by a further sub-session. It read: this file and
  `README_KO.md`; `research/fullgrid/WATCH_PREREG.md`; `candleague/CONTRACT.md`; `candleague/league.py`;
  `candleague/exits.py`; function names and the start-handling lines of `candleague/runner.py`; the account roles of
  `candleague/candidates.py`; `research/fullgrid/DEVIATIONS.md` lines 51-109 (the league entries); `run.signals`,
  `run.best_flags` and `run.ds_module`; the header, `signals` and module loading of `ds_defs.py`; `lib_c.env`,
  `lib_c.htf_value` and `search.htf_series`; the fee lines of `paperbot/config.py` and `kernel.py`; the fields `id`,
  `kind`, `name`, `tf`, `exit`, `combo` and `variants` of `candidates.json`; the Korean names in `strategies_ko.json`;
  sha256 values of the inputs of section 13; file names and times in `research/exitflex/` (`kernel_x.py`, `data_x.py`,
  `metrics.py`, `placebo.py` and `test_exitflex.py` appeared there from 02:31 UTC, written by another session; this
  drafter did not open them).
  * **Disclosure.** By mistake, one command printed the `source` field of the first row of `candidates.json`
    (core-DOGE-15m-1): the full-grid study's select- and test-period trade counts of that pick, its test-period mean
    P&L per trade and the band values of its forward warning light. These are the full grid's per-trade figures of E0,
    already seen by earlier sessions and the owners (WATCH_PREREG 3.1). No choice in this file was made with them: the
    scope, the families, the native definitions and the rules of this revision come from the main session's task text,
    written before that print. No other performance figure was opened.
* **The third revision** (2026-10-12, after two reviews of the second revision) was written by a further sub-session.
  It read: this file and `README_KO.md` in full; the two reviews' findings; `candleague/rulex.py` (its header,
  function list and the F11 plug-in, `pick_list` and record lines); the F11 lines and docstring of
  `research/exitflex/kernel_x.py`; the header and function names of `research/exitflex/metrics.py`; F11 lines of
  `data_x.py`; the flip, `tp_struct`, `LAST_TRADES`, `CANDLEAGUE_START` and `CANDLEAGUE_DS_MONEY` lines of
  `candleague/league.py` and `candleague/runner.py`; the `outcomes.clear` line of `paperbot/paramshadow.py`; the
  `short &= ~long` lines of the eight core `param_defs`; the C1, C2 and pool-mean lines of
  `research/fullgrid/WATCH_PREREG.md`; `git log` and `git status` names. It opened no performance figure of any period,
  no `holdcost` output, no hunt, autopsy or league result, and no DeepSeek money figure.
* **Main session's statement**, inserted verbatim (line breaks added only):

  ```text
  Main session, 2026-10-12: opened only the console logs
  /tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/holdcost/val5m.log and
  val1m.log of hc.py's validation run (select period, E0 only: per-pick trade counts, per-trade means and live-size
  account multiples for the 23 core picks, compared with the study's own numbers) and the 'basket' select line of
  research/fullgrid/diag/combo_sum.json (E0 basket at live size). It did not open grid_*.json, hc84*,
  compare_5m_1m.json, parity_*, extras*, check_forced*, blocked_ref_5m or any other holdcost output, nor any hunt
  result (only the hunt server's progress lines). The grids of F3, F5 and F7 were written by the main session as
  design defaults before any extras file existed; H = 6 was left out by the main session's own choice, not from any
  number. The hold-cost workflow that produced those outputs was stopped before its results were returned and will be
  resumed only after this file is hashed. Earlier sessions saw the full-grid study's select- and test-period results
  of E0 (the watch list was chosen after the test period; WATCH_PREREG 0).
  ```

* **Outputs under `scratchpad/holdcost/`** (names and file times UTC, 2026-10-12, as listed at about 01:56), with their
  status under the statement above. The first revision's default, "unless the main session strikes a line, that file
  counts as read", is **struck for every file marked "not opened"**:

  | file under `scratchpad/holdcost/` | time | what it is (from file names and the reviews) | status |
  |---|---|---|---|
  | `val1m.log`, `val5m.log` | 01:36 | console logs of the replica validation | **opened** (select period, E0 only, 23 core picks) |
  | `validation_1m.json`, `validation_5m.json` | 01:36 | replica validation | not opened (struck) |
  | `grid_1m.json`, `grid_5m.json` | 01:37 | select-period results of the replica on the 23 core picks | not opened (struck) |
  | `compare_5m_1m.json` | 01:37 | 5m against 1m comparison | not opened (struck) |
  | `out/hc84_rows_1m.json`, `out/hc84_rows_5m.json` | 01:42, 01:43 | account-level select-period rows of the 84 exits | not opened (struck) |
  | `out/parity_5m.json`, `out/parity_1m.json` | 01:44, 01:47 | parity checks | not opened (struck) |
  | `out/extras_5m.json` | 01:45 | `kx.py` / `study.py`: V1 time stop (H = 6, 12, 24, 48 chart bars from the fill, take-profit kept) and V2 opposite-signal exit, select period | not opened (struck) |
  | `out/hc84_split_1m.json` | 01:46 | split of the 84-exit results | not opened (struck) |
  | `out/check_forced_5m.json`, `out/check_forced_1m.json` | 01:47, 01:49 | forced-close checks | not opened (struck) |
  | `out/hc84.json` | 01:48 | 84-exit account results | not opened (struck) |
  | `out/extras_1m.json` | 01:49 | V1 and V2 on 1m | not opened (struck) |
  | `out/extras.json`, `out/blocked_ref_5m.json` | 01:52 | combined extras; blocked-signal reference | not opened (struck) |

  Also opened by the main session: the 'basket' select line of `research/fullgrid/diag/combo_sum.json` (E0 basket at
  live size). No hunt result file is in `research/hunt/` or `research/hunt_r2/` (by name: inputs, texts and
  `out/wide/parity.json` only), and the main session states it opened no hunt result. `research/autopsy/LOSS_AUTOPSY.md`
  holds select-period loss-cause tests; whether it covers early exits is not known to the drafters.
* **What follows, applied now**:
  * The first revision's "seen on select" marks on **F3.a** and **F7.N12.a, F7.N24.a, F7.N48.a** are dropped: the
    extras files were not opened, and the grids of F3, F5 and F7 (and the omission of H = 6) were set before any extras
    file existed, not from a number.
  * The select step is **not blind for E0 on the core pool**: per-pick select-period trade counts, per-trade means and
    live-size account multiples, and the E0 basket at live size, were seen. They show the size of E0's select-period
    growth at live size and nothing of any variant. The deciding size is quarter. Nothing of the DeepSeek pool was
    seen from `holdcost`.
  * Known limit 1's chandelier sentence does not apply (no hunt result opened).
  * The hold-cost workflow resumes only after this file is hashed. Its outputs are select-period numbers; reading them
    later changes no rule of this file. The families, grids and modes of section 5 and Appendix A are not changed after
    anyone reads them.
* **What the owners and the main session had seen**:
  * the full grid's per-trade results of the 84 exits on 2021-2023, 2024-2026 and 2020 (`ANALYSIS_KO.md`,
    `STRATEGIES_KO.md`, `STRATEGY_EVAL_KO.md`), DeepSeek without money for the owners;
  * the league's live record from 2026-10-11, including the SOL trade that prompted this request and the 7 open
    positions held 16-18 h under a fixed 3R take-profit;
  * the files the main session names in its statement.
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
  12. F11's common rules C1-C8 and its per-strategy readings (Appendix A).
  13. F7h's hours {4, 8, 16} (taken from a review of the second revision, from the owners' "16시간" and "단타", not from
      any number), the loss-cut categories L0-L3, the default set D and the hold-ranked default (section 16.3).

## 16. Changes

### 16.1 First revision (after two design reviews)

Each change answers a review finding. Where it departs from the main session's design defaults (DD), the default is
named.

1. **Data: 1m instead of 5m (DD 9).** The study's own 1m arrays exist and are pinned by `fg1m/build.json`. The league
   runs on 1m, so a passing variant's backtest trades are the trades the league would make, and its parity test runs
   on the same bars. On 5m, E0's stop and take-profit paths and F4's and F5's extreme X would differ from the league.
   5m is not used anywhere, so E0, the variants and the placebos always share one bar size.
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
11. **League (DD 8).** Quarter-size accounts next to a same-day E0 twin in their own database, judged on log growth at
    day 90. *Superseded by 16.2 item 7.*
12. **Caches and causality tests.** Cut arrays get their own data folder, stages run in fresh processes with their own
    cache folders, T3 runs at 21 cut times, and T5 checks decisions directly.
13. **Bugs, looks and failures.** Section 14 is new: what a look is, fixed post-run audits, which rerun decides, how a
    resume works, zero-signal picks and busts.
14. **Known limits.** Static inputs fitted on data past 2023 (`quality_edges.json`, `exchange.json`) are named, and
    the "no 2024 bar" sentence now covers price bars only. The stop-first sentence no longer claims the comparison is
    fair by construction. FAIL is not "no effect"; the ledger status goes into the Korean headline.
15. **Disclosure.** Section 15 replaces the placeholder with the file list, a conservative default and its
    consequences.

**Findings of the first revision not adopted, and why** (still standing):

* Dropping weak cells (F2 n = 50, F4 m = 3) to save compute: not adopted. One review asked that the menu not be
  reshaped, and there is no ground other than numbers to call a cell weak. The two-step placebo and the seed rule of
  5.3 cover the cost instead.
* An eligibility cap on the share of trades held more than 18 h: reported, not a criterion. 18 h is 72 bars on 15m and
  4.5 bars on 4h, so one cap does not mean the same thing across picks. The entries criterion measures the cost of long
  holds directly, and the owners now see the hold shares when they choose (8.2).
* Requiring ledger BH significance before any league account is added: not adopted. The league accounts are paper,
  and their forward record is the program's clean test. The BH status is in the Korean headline, and the owners decide
  with it in view.
* q15 versions of F5, F6, F8 and F10: only F9 q15 was added (the owners' combined rule), to keep the count down. The
  others react at the pick's own closes, and README_KO says so.
* A live-size non-inferiority guard on PASS: not needed, because the league's new-exit accounts are judged at quarter
  size. Live-size results and busts are reported.
* A paired placebo bootstrap inside Holm: not adopted. The 95th-percentile gate tests the same question without adding
  a ledger hypothesis.

### 16.2 Second revision (owners' messages of 2026-10-12 and the main session's promises)

1. **Scope: all 38 picks in two pools** (promise (d)). The 15 DeepSeek picks join the 23 core picks. Every gate, test,
   report and league check runs per pool, as WATCH_PREREG does. DeepSeek uses the "normal" leverage group, as the
   study and the league. D11 is written out (section 3): DeepSeek money is computed but kept outside the repository;
   DeepSeek rows show counts, win shares, hold times and labels. Gate 2 becomes 60% of the pool's picks (14 of 23, 9 of
   15).
2. **New family F11, each strategy's own exit** (owners' message 4, promise (a)). One definition per strategy, written
   out in Appendix A from two drafters' readings of the code, in mode (a) (the pick's take-profit kept) and mode (b)
   (the strategy's own target where it has one, else none). Group N, no parameter, no q15. Its placebo uses the same
   stratum rule with z = 0 (section 6). Variants: 76 + 2 = **78**. New code `native.py` and `native_ds.py`, and tests
   T2, T3, T5 and T6 cover it.
3. **The owners choose** (promise (c), replacing the automatic "highest median" rule of 8). The four select gates stay
   as filters. The select report shows every eligible variant per pool with hold hours first. The owners choose at
   most two per pool from different groups, or one rule for both pools; their message is recorded verbatim with its
   time in `choice.json`, hashed before the confirm. Without a choice within 48 h the default takes the top eligible
   variant by pooled M_P per pool, then the top from another group. The default uses the pooled metric because it is
   the table's headline figure; gate 2 still guards against a pooled mean carried by a few picks.
4. **Holm over every chosen (variant, pool) pair**, at most 4. The ledger counts this study at 4 until the choice.
5. **Hold time first** (owners' message 3, "단타"). Reports lead with median hold hours and the shares of trades held
   over 4 h, 8 h and 18 h, and with entries against E0. Section 7 writes out the engine's cost of a round trip, so the
   reports and README_KO can say that shorter holds win only when the extra entries earn more than these costs.
6. **What each variant can cut a loss on** (promise (b)) is listed (5.3) and shown in the select report. Every early
   exit is decided at a bar close; the hard stop never moves.
7. **The league restarts** (owners' message 2, promise (e)), replacing the separate `-f`/`-f0` database and the day-90
   judgement. After a PASS and the owners' OK the current league stops, its database is kept as a backup, and a fresh
   league starts from the new install time with five accounts per pick (new exit at live and quarter size, E0 at live
   and quarter size, a coin flip with the new exit at quarter size), 190 in all. C1 (one month) and C2 (two months,
   repeat at three) are pre-registered in 11.5. The effect on WATCH_PREREG's checks is named (11.3).
8. **Nothing passes** (promise (f)): nothing new is deployed, the owners are told plainly, and they decide with the main
   session whether to restart with the current exits only (11.1).
9. **Two-step placebo and a fixed seed rule** (speed). Placebos run only for (variant, pool) pairs that pass the other
   gates, which gives the same eligible set (section 6, test T4). 200 seeds, or 100 when the worst-case projection from
   a timing run on one pick exceeds 8 hours on 4 CPUs (5.3). This replaces the 48 h rule on three picks. Q-A is now
   reported only for the pairs that reach step 2.
10. **Disclosure** (section 15): the main session's statement is inserted verbatim; the "counts as read" default is
    struck for every file it names as unopened; the "seen on select" marks on F3.a, F7.N12.a, F7.N24.a and F7.N48.a
    are dropped; the select
    step is stated as not blind for E0 on the core pool. This revision's own disclosure (one printed `source` field)
    and the native drafters' disclosures are added.
11. **Files**: per-account results and DeepSeek money stay outside the repository; audit A8 checks that no committed
    file holds a DeepSeek money figure. A select rerun after the owners' choice keeps their choice where still eligible.
12. **Naming note** (section 1): the families F1-F11 are not the DeepSeek strategies named F1_PVT_DIV ... F12_MSS_DISP.

### 16.3 Third revision (two reviews of the second revision)

Each change answers a finding. Items 3, 7, 9 and 11 of 16.2 are changed by the items below where they differ.

1. **Promise (b) quoted as given, and the default limited to it** (front matter, 5.3, 8.2, 8.4). The second revision
   had reworded the promise as "a confirmed condition", while its default ranked every eligible variant by growth and
   could deploy a moving-average, opposite-signal, trail, clock or non-structure F11 loss cut that the owners never
   chose. Now the promise is quoted, 5.3 sorts every variant into L0-L3 by what it can cut a loss on, the report shows
   the category on every row, and the default takes only set D (L0 and L1: F5, F6.d0.5, F8, F9, F9 q15, F10). F1, F1
   q15 and F6.d0 (structure break at any loss) are left out of D because they can cut close to the entry, which message
   3 warns against; this is stricter than either review asked (one kept F1 and F6, the other dropped only F6.d0),
   because F1.a cuts a loss exactly when F6.d0 does.
2. **The default ranks by hold time, not growth** (8.4). Every choosable variant already beats E0 on growth and
   entries; the owners asked for shorter holds; a hold ranking needs no money figure, so the DeepSeek default no
   longer ranks by private growth (the second revision's mark leaked that rank, D11); and it avoids picking the variant
   whose 2021-2023 growth is most inflated by chance. Ties and the group rule are unchanged.
3. **When the default fires** (8.3, 8.7). One answer per pool with "없음" allowed; the default fills only a pool with no
   answer by its deadline, never an explicit "없음"; a clarifying question moves the deadline to at least 24 h after it;
   an answer counts only before the deadline, and later messages change nothing; the send time is committed in
   `sent.json` before any answer is read; `SELECT_KO.md` is hashed with `select.json` before sending; the runner checks
   `choice.json` against these.
4. **Freeze on 2024-2026 material** (8.3, Known limit 2). A hand choice can carry knowledge of the confirm period. From
   the report's sending until the choice is hashed, no 2024-2026 exit result (hunt test reads, ledger prints, track 2,
   full-grid extracts) reaches the owners or the main session; `choice.json` lists what the owners already had; the
   confirm report says whether each chosen pair is what the default would have taken. Known limit 2 is rewritten: the
   choice is not "a selection on select-period data like the automatic rule".
5. **Every variant on the select table** (8.2, 8.6). Choosable rows first, then the rest marked "선택 불가", all with
   hold hours, entries, loss-cut category and per-gate marks; growth only on choosable core rows; DeepSeek no money.
   So the owners see F9 and F11 even when they fail, and promise (f) has something to decide with. Gate failures are
   counted in sequence (1, 2, 4, then 3 among step-2 pairs), since gate 3 is not computed for the others.
6. **New F7h, a clock-hour time stop** (5.2, 5.3, 12). F7 counts chart bars, so its shortest stop on a 4h pick was
   2 days and nothing capped holds in hours. F7h fires at the first pick close at or after C0 + 4, 8 or 16 hours (a 4h
   pick: 1, 2 or 4 bars), modes a and b, group T with F7, no placebo, the F7 claim. C0 + H is always a pick close, so
   no 15m schedule is needed (the review proposed 15m checks). Variants: 78 + 6 = **84**; 72 still reach the placebo
   step, so step 2's size is unchanged. Known limit 15 says plainly what still cannot react inside a 4h bar.
7. **Placebo draws shared across picks** (6, T4, Known limit 9). The seed base drops the pick id, so picks that hold
   the same coin at the same check close draw the same u. Independent draws per pick made the placebo's pooled mean
   too narrow, so gate 3 was too easy. The remaining mismatch (no sharing across coins) is named.
8. **Placebo strata** (6, T4, Known limit 9): F6.d0.5 and F9 get z = 1 only where they can fire (below -0.5R with a
   reference, or after F9's arm); F8 needs a reference too; F11's z is "some component or level can fire", with
   F12_MSS_DISP's live swing level; the claim that F11's precondition is constant is corrected.
9. **The F11 coin flip** (11.2, A.0, T2, 11.4, Known limit 14). A flipped position on a level-only DeepSeek strategy
   had no rule exit at all and, under F11.b, no take-profit, so `-nflip` was pushed down by construction and C1's stop
   test could hardly hold. Now a flip on the other side gets the level and target mirrored around its own fill at the
   strategy's distances, keeps its own side's components under C3, and uses the same exit kinds as `-nq`. The
   remaining timing difference is a known limit, and `-nflip`'s hold hours are reported.
10. **C2 test and conditions** (11.5, Known limit 12). The week bootstrap on about 9 weeks was anti-conservative; it is
    replaced by an exact sign-flip test over all 2^n patterns, part-weeks merged into their neighbours, and 0.05 split
    over the two looks (0.03, 0.02). A fourth condition, G(`-nq`) > 0, stops "shown ahead" (renamed from "passes") for
    an exit that only lost less than E0. What "shown ahead" means is written out.
11. **C1 and C2 decidable** (11.5, 11.4). Check times are install + 30, 61 and 92 days at 00:00 UTC; wallets are marked
    to market net of exit costs (realised beside); a pool stopped at C1 has no C2; the stop is a fingerprinted
    `no_entry_from_ms` field set only by the committed C1 script, so a start-over reproduces it.
12. **League code named, with its deltas** (11.4, 13, 15). `candleague/rulex.py` already exists from the first
    revision (core only, `rule_league.db`, `-f` accounts, DeepSeek refused, F11 as a plain per-bar flag). 11.4 now says
    what must change: the restarted database and 11.2's ids, both pools, F11 with component kinds, C3 arming and
    per-position levels and targets, the step override staying in `RuleMixin`; plus counters (`acct_day`), daily marks
    (`acct_mark`), full-period hold aggregates in the snapshot, the check data source on the server, and the parity
    test's remedy (lengthen the window), a zero-volume or missing bin-last minute case, and T2's hand paths run through
    the league engine. "Named before any code is written" is dropped.
13. **D11 tightened** (3, 7, 9, 10, 13, 14). DeepSeek p values, busts and per-account result files are private; the
    confirm file and the ledger print carry DeepSeek Holm and BH labels only; DeepSeek weekly notes carry labels,
    counts, win shares and hold hours; A8 no longer allows DeepSeek p values. If the ledger print cannot omit a p, the
    DeepSeek row goes to the private folder.
14. **Code before the pin** (13). `metrics.py` (its "core pool only" header, `choose_variants`' median ranking,
    `claim_of`), `kernel_x.py` (F7h) and `placebo.py` (seed, strata) must follow this revision; new test T7 covers the
    gates per pool, the default, the group rule, `choice.json` validation and a D11 field whitelist.
15. **Select rerun after a hashed choice** (14): only ids no longer choosable are voided; standing ids cannot be
    swapped; replacements go to `choice_r2.json`, hashed before the confirm.
16. **Smaller fixes.** Both-flag bars cannot occur (all core `param_defs` end with `short &= ~long`, `ds_defs` drops
    them), so the both-sides rule is an assertion (3, 5.4.8, 11.2, 11.4, T2). F11.a = F3.a is marked beside F11.b =
    F3.b on the F7_RF_ONLY picks. Round-trip cost per bracket as a share of the wallet (7). The per-trade line compares
    `-nq` and `-eq` with `-nflip`, all at quarter size (11.5). Account counts when one pool passes (11.2).
    `CANDLEAGUE_START` is unset at the restart and `meta.start_ms` checked (11.3); the date shift of the first forward
    checks is stated (11.3). A.1's StochRSI wording and A.11's trailing level (it can also move down) are corrected.
    Section 15 records this revision's reading and the DeepSeek drafter's missing blindness statement.

**Findings of the reviews of the second revision not adopted, and why:**

* "Give flips the F3 opposite-signal exit" (one alternative offered): not adopted. Mirrored levels keep the flip on the
  same exit kinds as `-nq`, which 11.5 now requires; F3 would make the flip a different exit.
* "No default: ask again" (one alternative offered): not adopted. The owners want speed; a default restricted to set D
  and ranked by hold keeps promise (b) and message 3 and needs no money figure.
* "Split alpha across the two pools as well": not done. Each pool is decided for itself, as in WATCH_PREREG; the
  combined chance of a false "shown ahead" in at least one pool (about 10%) is stated in Known limit 12 and README_KO.
* "Check F7h at 15m closes": not needed; C0 + H hours is always a pick-timeframe close (item 6).
* "Get the DeepSeek drafter's explicit statement" (one alternative offered): this sub-session cannot obtain it; the
  readings are marked "blindness not stated" instead. The main session may still obtain and insert it before the hash.

## Appendix A. Each strategy's own exit (family F11)

### A.0 Common rules and code (all 16 strategies)

* **C1 Checks.** Only the pick's own chart closes after the signal bar i0, acted on at minute j =
  `kernel._entry_index(ts, C)` as in 5.1, using the step-0 frozen state. The exit is at j's open with slippage and
  taker, reason RULE. The k x ATR14 hard stop, liquidation and the period-end close are unchanged as the backstop.
* **C2 No extra confirmation.** A condition fires at the first check close where it holds. FINGRAD's CONFIRM_2
  (`ports12.py` header: "true on 2 consecutive closes, >= 2 bars held") is not adopted, for four reasons: fingrad_bot's
  code is not in the repo, so it cannot be checked; it is undefined for event exits (N13's source exit is an event that
  cannot hold on two consecutive closes); it adds a full bar of delay (4 h on 4h picks); and it adds a number.
* **C3 Arming per component.** A state component (including a level test, "the close is beyond a level") is armed once
  it is false at some pick close in [i0, i - 1], and then fires at a check close where it is true. Event components
  need no arm and count only on bars after i0.
* **C4 Merged checks** (5.4.2): walk the merged pick bars in time order, arming and testing; the check fires if any bar
  fires.
* **C5 Per-signal levels and targets** (levels: N13_3OUTSIDE, N19_FIB_CHOP and five DeepSeek strategies; targets: the
  eight strategies named in 5.2 under F11.b) are fixed at i0 from bars <= i0 and never move. F12_MSS_DISP's trailing
  swing level is not a per-signal level: it is the strategy's own structure engine, read through its per-bar flags.
* **C6 Target.** A take-profit limit at the level, used only when (level - fill) x side > 0, else none (the kernel's
  TP_STRUCT rule). It pays the maker fee and fills at the open on a gap; a minute touching both the stop and the target
  counts as the stop. Only F11.b uses it.
* **C7 NaN.** A NaN input at a bar means that component neither fires nor arms there; a NaN level or target means none.
* **C8 Modes.** F11.a = the invalidation + the pick's own take-profit, comparable to the other families' mode (a).
  F11.b = the invalidation + the strategy's own target; target "none" gives the invalidation alone, with no
  take-profit.
* **Core code**: `research/exitflex/native.py`, `native_arrays(name, df, tf, combo)` returns {`comp_long`, `comp_short`:
  lists of (kind in 'state' / 'event', bool array of len(df)); `lvl_long`, `lvl_short`, `tgt_long`, `tgt_short`: float
  arrays indexed by signal bar, NaN elsewhere}. It takes the strategy module from `run.core_module(name)` (hash-checked
  against `DEFS_BC.sha256`, memo-installed) and the frame from `run.frame(data_dir, sym, tf)`, the same objects
  `run.signals` uses, and calls only that module's indicator functions. The `param_defs` files are not edited.
* **DeepSeek code**: `research/exitflex/native_ds.py`, `native(df, tf, name, combo, ctx, coin)` returns `lx`, `sx`
  (per-bar booleans, len(df)), `inv_l`, `inv_s` (per-signal invalidation level indexed by signal bar, NaN where unused)
  and `tgt_l`, `tgt_s` (per-signal target, NaN = none). Per-signal levels are needed because a zone rule belongs to the
  trade's own zone, not to the bar. The function calls `D.signals(df, tf, name, ctx=ctx, coin=coin, cache=cache,
  **combo)` with a cache dict it owns, asserts the result equals `run.signals` on the same `run.frame`, and then reads
  the blocks the entry built from that cache through `X = D._Series(df, tf, ctx, coin, cache)` and
  `p = D._resolve(name, combo)`.
  * Under C1-C8, `lx` (`sx`) is one component and the invalidation level one level test. Both are false at every
    signal bar of their own side by construction (edge cases below; `native_ds` asserts it for the strategy's own
    side; the assertion does not apply to a coin-flip position on the other side, which C3 governs), so C3 arms them
    at once. The
    rule then reads: a long exits as RULE at a check when `lx` is true, or the close is below `inv_l[i0]`, at any chart
    bar closed since the previous check (a short: `sx`, or the close above `inv_s[i0]`). This matches 5.4.2.
* **kernel_x** gets, per position, the component arrays sliced from i0, the pick's close array for the level tests, and
  the level and target at i0.
* **Coin-flip accounts** (11.2): a position whose side equals the strategy's side at that bar is treated exactly as
  the strategy's trade. A position on the other side (side' = -s, fill f') uses the bar components of its own side
  under C3, so a state component that is true at i0 waits until it has been false at a close; and a level and target
  mirrored around its own fill at the distances the strategy's trade has at that signal: inv' = f' - side' x |f' -
  inv|, tgt' = f' + side' x (tgt - f') x s, the target only when (tgt - f') x s > 0. A NaN level or target gives none
  (C7). F11.a keeps the pick's own take-profit for the flip, as for every account in mode (a).
* **League** (11.4, `candleague/rulex.py`): the per-close inputs add the strategy's component booleans of the held
  coin (both sides) with their kinds; levels and targets go in the signal's meta (`meta['native_inv']`,
  `meta['native_tgt']`), mirrored for flips as above; the target uses the LadderTP-style `tp_price` assignment (set
  only when beyond `entry_price`), without the lock; DeepSeek arrays come from the same `chart_frame` the signal used.
* **Tests**: T2 hand paths per strategy and side; T3 native arrays, levels and targets cut against full; T5
  perturbation after the check close; T6 parity with `run.signals` where an entry is re-derived (N13_3OUTSIDE and all
  DeepSeek strategies) and with DOGE's source exit.

### A.1 DOGE (도지 봇): core-DOGE-15m-1, -30m-1, -1h-1, -4h-1

* **Entry** (for reference). Source: `third_party/sweep/harness/vendor/doge_strategy.py` `compute_signals` (a port of
  the friend's Astral strategy); lengths are 5m base lengths scaled to the chart timeframe by `doge_params`. Long: EMA
  fast > EMA slow, close > EMA trend, (fast - slow) / slow x 100 > spread_min, CHOP < chop_max, StochRSI K crosses
  above D with K < 45, RSI > 52, close > EMA short. Short mirrors (fast < slow, close < trend, spread < -spread_min, K
  crosses below D with K > 55, RSI < 48, close < EMA short).
* **Invalidation**: the strategy's own signal exit, unchanged from the source (`doge_strategy.compute_signals`:
  long_exit = (EMA fast < EMA slow) | (K crosses below D); short_exit = (EMA fast > EMA slow) | (K crosses above D);
  the source bot ran with use_signal_exit=True). Long: at a pick close i > i0, fire when ema_fast[i] < ema_slow[i] (the
  trend leg is lost) or StochRSI K crosses below D at bar i (K[i] < D[i] and K[i-1] >= D[i-1], the locked 'le' cross).
  The K/D cross has no level condition: any bearish cross counts, as in the source. Short mirrored: ema_fast >
  ema_slow, or K crosses above D.
* **Target**: none. The source had no take-profit; its other exit was a trailing stop at fixed fractions of the entry
  price (0.35% then 0.20%, tuned for DOGE on 5m bars). That is an intrabar moving stop plus new numbers, so it is not
  used. Exit = invalidation, hard stop, period end.
* **Inputs from the combo**: ema_slow and stoch_len (5m base lengths, scaled by the strategy's own `doge_params` rule;
  ema_fast 63, stoch_rsi_len 70, k_smooth 4, d_smooth 3 are locked strategy constants scaled the same way). Scaled
  lengths the exit uses (EMA fast / slow; StochRSI rsi / stoch / k / d), computed from the locked code only:
  core-DOGE-15m-1 21/26, 23/35/2/2; core-DOGE-30m-1 11/13, 12/6/2/2; core-DOGE-1h-1 5/13, 6/9/2/2; core-DOGE-4h-1 2/7,
  2/4/2/2. spread_min and chop_max are entry filters, not used by the exit.
* **New fixed numbers**: none. The locked cross convention 'le' of `doge_strategy` is reused.
* **No look-ahead**: EMA (ewm adjust=False), Wilder RSI, rolling min / max that include the current bar, rolling-mean K
  and D, and the source's forward-fill only read bars <= i, so long_exit[i] and short_exit[i] are known at bar i's
  close. The K/D cross at i reads bars i and i-1. No swing is used, so no confirmation lag is needed.
* **Code**: `M = run.core_module('DOGE')`; `p = M.doge_params(tf, **combo)`; `d = M._frame(df)`;
  `ind = M.ds.compute_indicators(d, p)`; `sig = M.ds.compute_signals(d, ind, p)`. Long components: state
  `ind['ema_fast'] < ind['ema_slow']`; event `M.ds.cross_below(ind['K'], ind['D'], 'le')`. Short: state ema_fast >
  ema_slow; event `M.ds.cross_above(K, D, 'le')`. Assert (state | event) == `sig['long_exit']` (resp.
  `sig['short_exit']`) bar for bar.
* **Edge cases**: both legs are false at i0 by the entry rule (fast > slow, and K has just crossed above D), so the
  state leg is armed at once and nothing can fire on the signal bar; the first possible exit is the close of i0 + 1.
  long_exit and long_entry cannot be true on the same bar. A short entry on a bar implies the long exit there: after
  the RULE exit that minute is free and the short can be entered (a reversal, section 4). On 4h the StochRSI lengths
  are at or near their floor of 2 (rsi 2, stoch 4, k 2, d 2), so K/D crosses are frequent there by construction (this follows
  from the lengths, not from data): expect short holds on core-DOGE-4h-1. With no target, a winner closes only on the
  invalidation, the hard stop or the period end (F11.b).
* **Korean**: 도지 봇 친구분 원래 청산 규칙 그대로입니다. 롱이면 빠른 EMA가 느린 EMA 아래로 내려가거나 스토캐스틱RSI K선이
  D선 아래로 꺾인 봉이 마감하면 바로 전량 청산하고, 정해진 익절가는 없습니다.

### A.2 N03_ADX_GC (ADX·골든크로스): core-N03_ADX_GC-15m-1, -30m-3, -1h-1

* **Entry** (for reference): EMA(ema_fast) crosses above EMA(ema_slow) and ADX(adx_len) crosses above adx_level, both
  within the last 3 bars, one of them on the signal bar, with ADX >= adx_level now. Short mirrors with the death cross
  (the ADX test is the same for both sides). Source: `strategies.n03_adx_golden_cross`, an exact FINGRAD port.
* **Invalidation**: derived from the entry's two persistent states (no source exit survives in the repo). Long: at a
  pick close i > i0, fire when EMA(ema_fast)[i] < EMA(ema_slow)[i] (the golden cross is undone: death-cross state) or
  ADX[i] < adx_level (the trend strength the entry required is gone). Short: EMA fast > EMA slow, or ADX < adx_level.
  Considered and not adopted: a +DI / -DI cross (DI is not part of the entry), and "ADX turns down" (needs a lookback
  number).
* **Target**: none (trend strategy). Exit = invalidation, hard stop, period end.
* **Inputs from the combo**: ema_fast, ema_slow, adx_len (DI length and ADX smoothing together, as in the entry),
  adx_level. core-N03_ADX_GC-15m-1: 100 / 160, ADX 5, level 75. core-N03_ADX_GC-30m-3: 17 / 200, ADX 21, level 12.5.
  core-N03_ADX_GC-1h-1: 33 / 250, ADX 5, level 50.
* **New fixed numbers**: none.
* **No look-ahead**: EMA (ewm adjust=False) and Wilder DMI / ADX (rma recursions over high / low differences and true
  range) read only bars <= i, so both legs at i are known at bar i's close. No swing is used.
* **Code**: `M = run.core_module('N03_ADX_GC')`; `p = M._resolve(combo)`; `ef = M.fg.ema(df['close'], p['ema_fast'])`;
  `es = M.fg.ema(df['close'], p['ema_slow'])`; `_, _, adx = M.fg.dmi_adx(df, p['adx_len'], p['adx_len'])`, the same
  calls as `M.signals`. Long components (both state): ef < es; adx < p['adx_level']. Short components (both state):
  ef > es; adx < p['adx_level']. numpy comparisons under errstate, so NaN gives False.
* **Edge cases**: EMA whipsaw: the entry accepts a golden cross within 3 bars that may already have reversed (the module
  notes that both sides can hold after a whipsaw), so ef < es can be true at i0. Under C3 the EMA leg then waits until
  ef > es has held at a close, so it cannot fire at the first check by construction. The ADX leg is armed at i0
  because ADX >= level is required there. Speed follows from the lengths (no data): with ADX length 5 and a high level
  (15m: 75, 1h: 50) the ADX leg can fire within a few bars; on 30m (ADX 21, level 12.5), and for the EMA legs (100/160,
  17/200, 33/250), firing is slow, so F11.b holds on 30m can be long (swing-like). ADX is direction-free: the same test
  closes longs and shorts. With no target, a winner closes only on the invalidation, the hard stop or the period end.
* **Korean**: 롱이면 골든크로스가 풀리거나(빠른 EMA가 느린 EMA 아래로 마감) ADX가 기준값 아래로 떨어져 추세 힘이 빠지면
  바로 전량 청산합니다. 정해진 익절가는 없습니다.

### A.3 N09_ALLIG_AROON (앨리게이터·아룬): core-N09_ALLIG_AROON-15m-3, -30m-1, -1h-1, -4h-1

* **Entry** (for reference): the lips SMA moves above both the teeth and jaw SMAs (the alligator wakes up) and Aroon
  (aroon_len) up crosses above down, both within 2 bars, one of them on the signal bar; on the signal bar lips > teeth,
  lips > jaw and Aroon up >= down (long_state). Short mirrors. Source: `strategies.n09_alligator_aroon`, an exact
  FINGRAD port.
* **Invalidation**: the exact negation of the entry's own long_state (no source exit survives in the repo). Long: at a
  pick close i > i0, fire when lips[i] <= teeth[i] or lips[i] <= jaw[i] (lips no longer above both: the alligator's
  mouth closes), or Aroon down[i] > Aroon up[i]. Short: lips >= teeth or lips >= jaw, or Aroon up > Aroon down.
* **Target**: none (trend strategy). Exit = invalidation, hard stop, period end.
* **Inputs from the combo**: lips_len, teeth_len, jaw_len, aroon_len. core-N09_ALLIG_AROON-15m-3: 15 / 6 / 26, Aroon
  75. -30m-1: 8 / 24 / 20, Aroon 75. -1h-1: 8 / 10 / 13, Aroon 75. -4h-1: 8 / 16 / 20, Aroon 13.
* **New fixed numbers**: none.
* **No look-ahead**: the SMAs are trailing windows ending at bar i. Aroon (`fg_fast.aroon`) uses the sliding window of
  aroon_len bars ending at i. Both are known at bar i's close. No swing is used.
* **Code**: `M = run.core_module('N09_ALLIG_AROON')`; `p = M._resolve(combo)`; `close = df['close']`;
  `lips, teeth, jaw = M.fg.sma(close, p['lips_len']), M.fg.sma(close, p['teeth_len']), M.fg.sma(close, p['jaw_len'])`;
  `up, down = M.fg_fast.aroon(df, p['aroon_len'])`. `long_state = M.gt(lips, teeth) & M.gt(lips, jaw) &
  M.ge(up - down, 0)`; `short_state = M.lt(lips, teeth) & M.lt(lips, jaw) & M.ge(down - up, 0)`. `fin` = all five
  series finite. Long component (state) = fin & ~long_state; short component (state) = fin & ~short_state. The fin
  guard is needed because ~ of a NaN comparison is True.
* **Edge cases**: long_state holds at i0 by the entry rule, so the arm is immediate and nothing can fire at i0. up ==
  down does not fire (the entry's own >= 0). Combo quirk: on core-N09_ALLIG_AROON-15m-3 the "lips" length (15) is
  longer than the "teeth" length (6), so "lips above teeth" means the 6-bar average sits below the 15-bar one (a dip
  inside a rise). The exit then also fires when the 6-bar average recovers above the 15-bar one, which can be on
  strength. This is what the pick's own state means; it is kept, not repaired, as the `param_defs` file keeps its own
  quirks. With no target, a winner closes only on the invalidation, the hard stop or the period end.
* **Korean**: 롱이면 입술선이 이빨선·턱선 둘 다의 위에 있던 상태가 깨지거나, 아룬 하락선이 상승선보다 올라가면 바로 전량
  청산합니다. 정해진 익절가는 없습니다.

### A.4 N10_HA_PSAR (하이킨아시·PSAR): core-N10_HA_PSAR-4h-1

* **Entry** (for reference): Heikin-Ashi turns green within 2 bars, and the signal bar's HA candle has no lower wick
  (within wick_tol x HA range); PSAR(sar_af_start, sar_af_step, sar_af_max) is below the close in an up state or has
  just flipped up; the trigger is the green turn or the PSAR flip. Short mirrors (red turn, no upper wick, PSAR above).
  Source: `strategies.n10_heikin_psar`, an exact FINGRAD port.
* **Invalidation**: the mirror of the entry's two parts (no source exit survives in the repo). Long: at a pick close
  i > i0, fire when the PSAR direction is down at bar i (pdir[i] < 0: the SAR was hit during the bar and now sits above
  price; PSAR is a stop-and-reverse system by design), or bar i closes a strong red Heikin-Ashi candle: ha_close <
  ha_open with no upper wick within the pick's tolerance (|ha_high - max(ha_open, ha_close)| <= wick_tol x |ha_high -
  ha_low|), the mirror of the strong green candle the long entry needs. Short: pdir[i] > 0, or a green HA candle with
  no lower wick. A plain colour flip (any red HA candle) was considered and not adopted: one red HA candle is a normal
  pullback bar inside a trend, and the entry itself asks for the strong, wickless form.
* **Target**: none (trend strategy). Exit = invalidation, hard stop, period end.
* **Inputs from the combo**: sar_af_start, sar_af_step, sar_af_max, wick_tol. core-N10_HA_PSAR-4h-1: 0.016, 0.06,
  0.1333, 0.06.
* **New fixed numbers**: none (the candle leg reuses the combo's wick_tol).
* **No look-ahead**: `fg_fast.parabolic_sar` is a forward recursion: the SAR for bar i is set from bars <= i - 1, and the
  flip at i uses low[i] (long) or high[i] (short), so pdir[i] is known at bar i's close. HA close uses bar i's OHLC;
  HA open is a recursion over earlier HA bars; HA high / low use bar i. No swing is used. PSAR and HA open depend on
  the frame's first bar (as the entry does). The cut frame starts at the same bar (T3); in the league the influence of
  the first bar fades (HA open halves it every bar, PSAR forgets it after two flips), so the league computes these on
  the same frames as its signals (11.4 item 7).
* **Code**: `M = run.core_module('N10_HA_PSAR')`; `p = M._resolve(combo)`; `ha = M.fg_fast.heikin_ashi(df)`;
  `psar, pdir = M.fg_fast.parabolic_sar(df, p['sar_af_start'], p['sar_af_step'], p['sar_af_max'])`;
  `tol = (ha['ha_high'] - ha['ha_low']).abs() * p['wick_tol']`; body_min / body_max as in `M.signals`. Long components
  (both state): `M.lt(pdir, 0)`; `M.lt(ha['ha_close'], ha['ha_open']) & M.le((ha['ha_high'] - body_max).abs(), tol)`.
  Short components: `M.gt(pdir, 0)`; `M.gt(ha['ha_close'], ha['ha_open']) & M.le((body_min - ha['ha_low']).abs(),
  tol)`.
* **Edge cases**: pdir > 0 at i0 by construction (in a down state the SAR is at or above the bar's high, so psar < close
  cannot hold), so the PSAR leg is armed at once. The candle leg can rarely be true at i0 (a red HA candle with neither
  wick); C3 then waits for a close where it is false. The PSAR flip happens intrabar at the SAR level but is acted on
  only at the bar close, so this exit can come up to one 4h bar later than a stop order at the SAR would; the hard stop
  still works every minute. With no target, a winner closes only on the invalidation, the hard stop or the period end.
* **Korean**: 롱이면 PSAR 점이 가격 위로 뒤집히거나, 위꼬리 없는 강한 하이킨아시 음봉이 마감하면 바로 전량 청산합니다.
  정해진 익절가는 없습니다.

### A.5 N13_3OUTSIDE (쓰리 아웃사이드): core-N13_3OUTSIDE-30m-1, -1h-1

* **Entry** (for reference): Three Outside Up after a prior decline (close[j-3] < close[j-2-prior_n]): a bearish bar,
  then a bullish bar with body >= engulf_min x ATR(atr_len) engulfing it, then a bullish bar closing higher (bars j-2,
  j-1, j). The signal is the first close above the pattern's 3-bar high PH, 1 or 2 bars after j (c > PH and the
  previous close <= PH). Short mirrors: Three Outside Down after a rise, then a close below the pattern's 3-bar low.
  Source: `ports12.n13`, a FINGRAD spec port.
* **Invalidation**: long: at a pick close i > i0, fire when close[i] < PL, or when the pick's own short signal
  (`run.signals`) is true at bar i. PL is the low of the three pattern bars the entry broke out of, fixed at i0: PL =
  min(low[j-2 .. j]), j = i0 - lag. A close below it means the bullish pattern has failed; it is the source port's
  structural stop level (stopL = PL - 0.1 ATR) used as a close test. The short signal is the source port's own exit:
  `ports12.n13` sets exL = S. Short: close[i] > PH of the bear pattern (max(high[j-2 .. j])), or the pick's own long
  signal.
* **Target**: the measured move of the pattern the entry broke out of. Long: PH + (PH - PL); short: PL - (PH - PL),
  with PH and PL from the same pattern bars as the invalidation, fixed at i0. Considered and not adopted: the top of
  the prior decline (the highest high of bars j-2-prior_n .. j-3, the window the strategy's prior-direction test
  reads), because with prior_n 2-3 that window is a few bars and the breakout close is often already above it; and the
  nearest confirmed swing high, which needs a swing width, a new number.
* **Inputs from the combo**: engulf_min, prior_n, atr_len. They decide which bars form the pattern, hence PH, PL, the
  target and the opposite signal. core-N13_3OUTSIDE-30m-1: 1.0, 3, 9. core-N13_3OUTSIDE-1h-1: 0.625, 2, 28. Locked: the
  3-bar pattern and the breakout lags (2, 1).
* **New fixed numbers**: one, the measured-move projection of 1 x the pattern height. The reason it is unavoidable: the
  invalidation lies below the entry, so without a target this exit would never take a profit and a winner would be
  held until it fell back through PL. The pattern defines no level above the breakout, and one pattern height is the
  textbook breakout target; the value is fixed, not tuned. The source port's 0.1 ATR stop buffer is not used, because a
  close test needs no wick buffer.
* **No look-ahead**: the pattern bars are j-2 .. j with j = i0 - lag <= i0 - 1, so PH, PL and the target are known at
  i0's close. close[i] < PL is read at bar i's close. The opposite flag at bar i comes from `M.signals`, which uses only
  shifts and trailing rolling windows (the sweep's truncation tests passed for it). Rolling 3-bar extremes, not swings,
  are used, so no confirmation lag is needed.
* **Code**: `M = run.core_module('N13_3OUTSIDE')`; `p = M._resolve(combo)`. Recompute what `M.signals` computes inline,
  with `M._sh`, `M._roll`, `M.shift_bool`, `M.fg.atr(df, p['atr_len'])`, `M.FIRST_LAG`, `M.LAGS`: bull, bear, `ph3 =
  M._roll(h, 3, 'max')`, `pl3 = M._roll(l, 3, 'min')`, and for each lag the long and short breakout masks. Assert the OR
  of those masks (short & ~long) equals `run.signals` bar for bar. Per long signal at i0: the lag is the one whose mask
  is true, and lag 1 wins when both are (the source port's stop-assignment order). PH = ph3[i0 - lag], PL =
  pl3[i0 - lag]; lvl_long[i0] = PL (fire when close < lvl); tgt_long[i0] = PH + (PH - PL). Short: lvl_short[i0] = PH of
  the bear pattern (fire when close > lvl); tgt_short[i0] = PL - (PH - PL), set to NaN if <= 0. Components: long =
  [level test, event: `run.signals` short flag]; short = [level test, event: `run.signals` long flag].
* **Edge cases**: PL < c[i0] by construction (c > PH >= PL), so the level leg is armed at once and cannot fire at i0.
  The opposite flag cannot be true at i0 (short &= ~long) and counts only on bars after i0. If PL lies beyond the hard
  stop, the hard stop comes first and the level adds nothing. If the signal close or the fill is already at or beyond
  the target (a breakout bar longer than the pattern), there is no target (C6) and the trade exits on invalidation,
  stop or period end. The target can be closer than the round-trip cost; it is kept, so a target hit can be a small net
  loss, as with the kernel's structure take-profit. The opposite signal can reverse the position at the freed minute
  (section 4), as under F3.
* **Korean**: 롱이면 패턴 3봉의 최저가 아래로 마감하거나 반대 패턴(쓰리 아웃사이드 다운) 신호가 나오면 바로 전량 청산합니다.
  익절은 패턴 최고가에서 패턴 높이만큼 더 오른 가격에서 합니다.

### A.6 N19_FIB_CHOP (피보나치·초피): core-N19_FIB_CHOP-15m-1, -30m-1, -4h-1

* **Entry** (for reference): in a rising chop zone (slope = (EMA34[i] - EMA34[i-3]) / ATR14[i] >= slope_thr), the bar's
  low comes within touch_atr x ATR14 of the retracement line L = hh - fib_level x R of the range_len-bar high / low
  range ending 3 bars ago (R = hh - ll), and the bar closes above the line as a bullish candle: a pullback buy inside a
  trend. Short mirrors with the line ll + fib_level x R, a falling zone and a bearish close below. Source: `ports12.n19`,
  a FINGRAD spec port (the port has no exit, only a structural stop).
* **Invalidation**: long: at a pick close i > i0, fire when close[i] < L0, or when slope[i] <= -slope_thr. L0 is the
  retracement line the entry used, fixed at i0 (L0 = ll[i0] + (1 - fib_level) x (hh[i0] - ll[i0])); a close below it
  means the bounce failed. slope <= -slope_thr is the strategy's own short-side zone (the chop zone turns red): the trend
  the pullback relied on has turned. Short: close[i] > ll[i0] + fib_level x R0, or slope[i] >= slope_thr. Considered
  and not adopted: slope < slope_thr (merely weakening), which would fire on most pauses (thr 0.6 on 15m / 30m); and
  the port's structural stop min(hh - 0.618 R, 5-bar low) - 0.1 ATR, which adds three source constants the combo study
  never varied.
* **Target**: the top of the range the pullback was measured from, fixed at i0: long hh[i0] (the 0% retracement, a
  retest of the prior high); short ll[i0].
* **Inputs from the combo**: range_len, fib_level, slope_thr (touch_atr is an entry tolerance, not used).
  core-N19_FIB_CHOP-15m-1: 51, 0.25, 0.6. -30m-1: 11, 0.3333, 0.6. -4h-1: 102, 0.1667, 0.1333. Locked strategy
  constants: range lag 3, EMA 34, slope lag 3, ATR 14.
* **New fixed numbers**: none.
* **No look-ahead**: hh and ll are rolling extremes over range_len bars ending 3 bars before i0 (RANGE_LAG), so L0, R0
  and the target are known at i0's close and never move. slope[i] reads EMA34 at i and i-3 and ATR14 at i, all
  trailing. No swing is used.
* **Code**: `M = run.core_module('N19_FIB_CHOP')`; `p = M._resolve(combo)`; `df = df.reset_index(drop=True)`;
  `h, l = M._f(df['high']), M._f(df['low'])`; `n = p['range_len']`; `hh = M._sh(pd.Series(h).rolling(n,
  min_periods=n).max().to_numpy(), M.RANGE_LAG)`; ll likewise with min; R = hh - ll; f = p['fib_level']; line_l = ll +
  (1 - f) x R; line_s = ll + f x R; `atr_s = M.fg.atr(df, M.ATR_LEN)`; `base = M.fg.ema(df['close'], M.CHOP_EMA)`;
  `slope = M._f((base - base.shift(M.SLOPE_LAG)) / atr_s.replace(0, np.nan))`. These are the same expressions as
  `M.signals`. Per signal: lvl_long[i0] = line_l[i0], tgt_long[i0] = hh[i0]; lvl_short[i0] = line_s[i0], tgt_short[i0]
  = ll[i0]. Components: long = [level test close < lvl, state slope <= -slope_thr]; short = [level test close > lvl,
  state slope >= slope_thr].
* **Edge cases**: c[i0] > L0 by the entry rule, so the level leg is armed at once. slope >= slope_thr at i0, so the
  slope leg cannot be true there. The entry bar's low may lie well below the line (only the close must be above it), so
  price often trades around the line just after entry. A single close below it fires (the pullback failed), so this leg
  is likely the fastest; that follows from the rule, not from data. If the signal bar or the 3 excluded bars rose to or
  above hh[i0], the target is at or behind the fill: no target (C6). If R <= 0 there is no level or target, but then no
  signal can fire either. The target can be closer than the round-trip cost; it is kept.
* **Korean**: 롱이면 진입 때 쓴 되돌림 선 아래로 다시 마감하거나 초피 기울기가 아래쪽(빨강)으로 바뀌면 바로 전량 청산합니다.
  익절은 그 범위의 최고점, 즉 눌림이 시작된 고점에서 합니다.

### A.7 OBV_S (OBV 추세형): core-OBV_S-30m-2, -1h-3, -4h-1

* **Entry** (for reference): long when any of three stochastics (raw 11, 15, 9; K smoothed by stoch_k_smooth, D by 3)
  crosses up, AC (AO 5 / ao_slow_len, AC length 5) > 0, STC(12, 26, 50) < stc_level, and OBV > SMA(OBV, obv_ma_len).
  Short mirrors (dead cross, AC < 0, STC > 100 - stc_level, OBV below its SMA). Source: `strategies.obv_s` (the OBV
  V1.2 Pine path); no source exit is in the repo.
* **Invalidation**: long: at a pick close i > i0, fire when OBV[i] < SMA(OBV, obv_ma_len)[i]: OBV closes back below its
  own average, so the volume trend the entry required is gone. Short: OBV > its SMA. The stochastic cross, AC and the
  STC cap are timing and room-to-run filters, not exit conditions: AC changes sign every few bars, and STC above its cap
  only says the move is extended.
* **Target**: none (trend strategy). Exit = invalidation, hard stop, period end.
* **Inputs from the combo**: obv_ma_len. core-OBV_S-30m-2: 15. core-OBV_S-1h-3: 38. core-OBV_S-4h-1: 38. stc_level,
  stoch_k_smooth and ao_slow_len are entry filters, not used by the exit.
* **New fixed numbers**: none.
* **No look-ahead**: OBV (`pi.obv`) is a cumulative sum over bars <= i, and its SMA is a trailing window ending at i, so
  the test is known at bar i's close. OBV - SMA(OBV) does not depend on the cumulative sum's starting constant, so the
  league and the study agree once the window is filled. No swing is used.
* **Code**: `M = run.core_module('OBV_S')`; `p = M._resolve(combo)`; `o = M.pi.obv(M._f(df['close']),
  M._f(df['volume']))`; `ma = M.pi.pine_sma(o, p['obv_ma_len'])`, the same calls as `M.signals`. Long component
  (state): o < ma; short component (state): o > ma, both under errstate, NaN gives False.
* **Edge cases**: OBV > SMA at i0 by the entry rule, so the arm is immediate. OBV == SMA does not fire. OBV adds a whole
  bar's volume with the sign of the close change, so one large opposite bar can cross the average; that is the
  strategy's own reading. The volume of bins with minutes missing is what `build_frame` sums, as for the entry. With no
  target, a winner closes only on the invalidation, the hard stop or the period end.
* **Korean**: 롱이면 OBV(거래량 누적선)가 자기 평균선 아래로 다시 내려가 마감하면 바로 전량 청산합니다. 정해진 익절가는
  없습니다.

### A.8 S4_BB_BBP (볼린저 스퀴즈·BBP): core-S4_BB_BBP-30m-1, -1h-2, -4h-1

* **Entry** (for reference): a Bollinger squeeze (bandwidth <= its sq_pct rolling quantile over sq_lookback bars) on
  any of the 5 previous bars, then the first close above the upper band (bb_len, bb_mult) with bull-bear power (EMA 13)
  > 0. Short mirrors (first close below the lower band, power < 0). Source: `ports12.s4`, a FINGRAD spec port.
* **Invalidation**: the source port's own exit, unchanged (`ports12.s4`: exL = close < mid | bbp < 0; exS = close > mid
  | bbp > 0). Long: at a pick close i > i0, fire when close[i] < the Bollinger middle band SMA(close, bb_len)[i] (the
  breakout fell back to the mean), or when bull-bear power[i] < 0 (high + low - 2 x EMA13(close) < 0: the bar's
  midpoint is below EMA13 and sellers lead). Short: close > mid, or power > 0.
* **Target**: none. A squeeze breakout has no level of its own where it is fulfilled. The source port's other exit, a
  trailing stop at the 3-bar low - 0.1 ATR, is an intrabar moving stop (out of scope, section 12, and a close-based
  version would add numbers), so it is not used. Exit = invalidation, hard stop, period end.
* **Inputs from the combo**: bb_len (mid = SMA(close, bb_len)). core-S4_BB_BBP-30m-1: 25. -1h-2: 40. -4h-1: 25. bb_mult
  does not move the mid; sq_lookback and sq_pct are entry filters. The power length 13 is the strategy's locked
  constant (BBP_LEN).
* **New fixed numbers**: none.
* **No look-ahead**: the SMA mid is a trailing window ending at i. Bull-bear power uses EMA13 (ewm adjust=False) and bar
  i's high / low. Both are known at bar i's close. No swing is used.
* **Code**: `M = run.core_module('S4_BB_BBP')`; `p = M._resolve(combo)`; `df = df.reset_index(drop=True)`;
  `close = df['close']`; `_up, mid, _lo, _bw = M.fg.bollinger_bands(close, p['bb_len'], p['bb_mult'])`;
  `_bu, _be, bbp = M.fg.bull_bear_power(df, M.BBP_LEN)`, the same calls as `M.signals`. Long components (state):
  `M.lt(close, mid)`; `M.lt(bbp, 0.0)`. Short components (state): `M.gt(close, mid)`; `M.gt(bbp, 0.0)`.
* **Edge cases**: at i0, close > upper band > mid (bb_mult > 0) and power > 0, so both legs are false and armed at once.
  With bb_mult 4 (30m, 1h) and 3 (4h) the upper band is far above the mid, so the mid leg is a deep-retracement test and
  the power leg (bar midpoint below EMA13) will usually fire first; that follows from the band width, not from data.
  The source applied this exit with FINGRAD's CONFIRM_2, which is not adopted (C2). With no target, a winner closes when
  momentum fades (power < 0) or on the hard stop or the period end.
* **Korean**: 롱이면 종가가 볼린저 가운데 선 아래로 내려가거나 불·베어 파워가 마이너스로 바뀐 봉이 마감하면 바로 전량
  청산합니다. 정해진 익절가는 없습니다.

### A.9 F10_OTE (ICT OTE, ICT 최적 진입 62~79%): ds-F10_OTE-1h-1, ds-F10_OTE-4h-1

* **Entry** (for reference): picks ds-F10_OTE-1h-1 (swing_k 3, leg_atr 3.75, leg_max_bars 30; exit tp3R|4) and
  ds-F10_OTE-4h-1 (swing_k 3, leg_atr 1.5, leg_max_bars 15; tp3R|3). `ds_defs.impulse_legs`: an up leg is born at bar t
  when a swing high is confirmed (pivot p = t - swing_k, H = high[p]) and the last confirmed swing low (L =
  S['lo'][t] at q = S['lo_idx'][t]) lies at most leg_max_bars before p, with H - L >= leg_atr x ATR14[t]. Zone = the OTE
  band [H - 0.79 (H - L), H - 0.62 (H - L)], life 50 bars, kill = any high > H at or before the touch. Long at the first
  bar s in t+1 .. t+50 whose low reaches the 62% level, when no kill came first and the close is above the 79% level
  (zone_table conf 'edge'). Short mirrored on a down leg: swing low confirmed, last swing high H, band Lw + 0.62 .. 0.79
  x (H - Lw), kill = a low < Lw, close below the 79% level.
* **Invalidation**: long: a chart close below L, the swing low the impulse leg started from (the 100% retracement of the
  leg that produced the signal). Short: a close above H, the swing high the down leg started from. The level is fixed
  at the signal bar and never moves. Reason: OTE buys a 62-79% pullback of an intact impulse, and the leg stays intact
  until its origin is taken out, so a close below that origin breaks the swing the entry relied on. The band's own
  lower edge (79%) was not used: a close between 79% and 100% still leaves the leg intact, and that cut would be tighter
  than the owners asked for.
* **Target**: long: H, the swing high at the top of the leg (the 0% level, the prior swing extreme that ICT targets
  first). Short: L, the leg's swing low. Fixed at the signal bar. Used as a take-profit limit (maker) only when it lies
  beyond the fill.
* **Inputs from the combo**: swing_k (the pivots and the structure that give H, L and the leg's confirm bar t); leg_atr
  and leg_max_bars (which legs exist, and so which leg fired). The 0.62 / 0.79 band and zone life 50 are lib_c's fixed
  numbers of this definition, not combo keys.
* **New fixed numbers**: none. Tie rule (not a number): when several legs fire on the same bar and side, the most
  recently confirmed leg (largest t) gives L and H.
* **No look-ahead**: H is the high of pivot p and is known only at t = p + swing_k, when `pivots_conf` confirms it. L is
  the last swing low confirmed at or before t (`structure()` is a single forward pass). The signal bar is s >= t + 1, so
  both levels are known at s's close. The zone table's touch and kill tests read bars t+1 .. s only. The exit then reads
  only the closes of bars after s, each at its own close.
* **Code**: key = (swing_k, leg_atr, leg_max_bars); `t, H, Lw, d = X.legs(*key)`. `T = X.table(('ote',) + key, build,
  50)` is a cache hit and returns the same table object the entry used; build is copied from `_f10_ote` only as the
  fallback. Rows m = T['ft'] < 50 give s = T['s'][m], zi = T['zi'][m], up = T['up'][m]. zi indexes the legs arrays,
  because build makes the zone set from `X.legs(*key)` in that order. For each bar of the final long array, zi* = the
  up row at s with the largest t[zi]; inv_l[s] = Lw[zi*] and tgt_l[s] = H[zi*]. For shorts, inv_s[s] = H[zi*] and
  tgt_s[s] = Lw[zi*]. lx = sx = False (this exit uses levels only). Test: the final signals are a subset of the
  recovered (s, side) rows, and the difference is only bars where `ds_defs` dropped a both-side signal.
* **Edge cases**: every signal comes from a row, so a missing row is a bug; assert on it. Several legs on one bar: use
  the largest t. Target at or behind the fill: on the signal bar every high is <= H (a higher high kills the zone), so
  only a gapped fill above H can cause this; then there is no target, and the invalidation and hard stop act alone (the
  TP_STRUCT rule). Invalidation on the entry bar cannot happen (c[s] > 79% level > L), and that bar is never checked
  (the first check is the close of s + 1). A fill that gaps below L fires at the first check close if that close is
  still below L. If L lies beyond the hard stop, the hard stop acts first. On the 4h pick the minimum leg is 1.5 ATR, so
  L can be as close as about 0.3 ATR below an entry at the 79% level. That early cut still needs a full close below the
  swing low, and the 3 ATR hard stop is unchanged.
* **Korean**: 롱이면 큰 상승이 시작된 저점(스윙 저점) 아래로 봉이 마감하면 바로 전량 청산하고, 그 상승의 꼭대기(스윙 고점)에
  닿으면 익절합니다. 숏은 반대이고, 원래 손절선은 안전장치로 그대로 둡니다.

### A.10 F11_TSOUP (터틀 수프, 가짜 돌파 역매매): ds-F11_TSOUP-4h-1

* **Entry** (for reference): pick ds-F11_TSOUP-4h-1 (tsoup_len 30, min_age 2; tp3R|1.5). Long when the bar's low breaks
  Lw = X.lmin1(30)[s] (the lowest low of bars s-30 .. s-1), the close is back above Lw, and that prior low is at least
  min_age bars old (age_lo >= 2). Short mirrored with Hw = X.hmax1(30)[s]: high above Hw, close back below it, age_hi >=
  2. This fades a false breakout.
* **Invalidation**: long: a chart close below the signal bar's own low l[s], the extreme of the false breakout. Short: a
  close above h[s]. Fixed at the signal bar. Reason: the trade says the break below the old low failed, so a close
  beyond the extreme of that break means the break was real after all. This is Raschke's original stop level (just
  beyond the reversal bar's extreme), taken here on a close only. The tighter reading, a close back below Lw, was not
  used: it can fire on a retest of the old low, which the setup expects, and the owners asked for cuts that are not too
  tight.
* **Target**: long and short: the middle of the range the signal used, (Hw[s] + Lw[s]) / 2, with Hw and Lw over bars
  s-30 .. s-1. Reason: a failed breakout says price goes back into the range, and the range's equilibrium is where that
  is fulfilled. The opposite extreme (Hw for a long) was the other choice that needs no number. It would turn a
  short-term reversal into a crossing of a 30-bar range (5 days on 4h), which is the swing feel the owners want to
  avoid.
* **Inputs from the combo**: tsoup_len (the window of Lw and Hw, and so of the middle). min_age is used by the entry
  only.
* **New fixed numbers**: no tunable number. Listed for honesty: the middle is the range's equilibrium (H + L) / 2, a
  fixed 0.5. The DeepSeek library uses the same midpoint itself (pd_zone's eq, FVG conf_mid).
* **No look-ahead**: Lw and Hw are rolling(tsoup_len).min / max().shift(1), so they use bars s-30 .. s-1 only. l[s] and
  h[s] belong to the signal bar and are known at its close. The exit reads only the closes of bars after s.
* **Code**: with the same cache, `Lw = X.lmin1(p['tsoup_len'])` and `Hw = X.hmax1(p['tsoup_len'])` are the cached
  arrays the entry used. For each long signal bar s, inv_l[s] = X.l[s] and tgt_l[s] = (Hw[s] + Lw[s]) / 2. For each
  short, inv_s[s] = X.h[s] and tgt_s[s] = the same middle. lx = sx = False.
* **Edge cases**: target at or behind the fill: a big reversal bar can close above the middle, or the fill can gap past
  it; then there is no target, and the invalidation and hard stop act alone. A NaN Lw or Hw cannot occur on a signal
  bar, because the entry needs Lw finite (assert). Invalidation on the entry bar cannot happen (l[s] < Lw < c[s]), and
  that bar is never checked. The sweep low can be nearer or farther than the 1.5 ATR hard stop; whichever is reached
  first acts (the rule at a close, the stop intrabar). The hard stop is unchanged.
* **Korean**: 롱이면 가짜 하락 돌파를 만든 봉의 저가 아래로 봉이 마감하면(진짜 돌파였다는 뜻) 전량 청산하고, 직전 30봉 박스의
  가운데 가격에 닿으면 익절합니다. 숏은 반대입니다.

### A.11 F12_MSS_DISP (구조 전환·변위, 변위 구조 전환 MSS): ds-F12_MSS_DISP-1h-1, ds-F12_MSS_DISP-4h-1

* **Entry** (for reference): picks ds-F12_MSS_DISP-1h-1 (swing_k 2, disp_atr 1.8; tp3R|4) and ds-F12_MSS_DISP-4h-1
  (swing_k 5, disp_atr 0.96; tp3R|1). `ds_defs.structure(swing_k)` tracks the last confirmed swing high and low (each
  usable once until broken) and a state: +1 after a bullish break, -1 after a bearish one. Long = mss_up (the state was
  -1 and the close crosses above the last confirmed, not yet broken swing high) on a bar with body c - o >= disp_atr x
  ATR14 (X.mss_disp). Short mirrored: mss_dn with o - c >= disp_atr x ATR14.
* **Invalidation**: long: the strategy's own structure turns bearish again, i.e. S['bos_dn'] or S['mss_dn'] at a chart
  close (a close below the last confirmed, not yet broken swing low). The entry sets the state to +1, so the first such
  bar after it is always an mss_dn. The level trails: each newly confirmed swing low replaces it, so higher lows raise
  it, and a newly confirmed lower swing low lowers it. Short: S['bos_up'] or
  S['mss_up']. Reason: the trade says the structure shifted up, so the same engine saying it
  shifted back down means the reason is gone. This needs no displacement, so it fires more often than the opposite
  signal (mss_dn with a big body) and is not the F3 exit.
* **Target**: long: S['prev_hi'][s], the swing high confirmed before the one the MSS broke. In a downtrend this is the
  higher high one step back, the buy-side liquidity ICT targets after a shift. Short: S['prev_lo'][s]. Fixed at the
  signal bar, and used only when it lies beyond the fill; otherwise there is no target.
* **Inputs from the combo**: swing_k (pivots, structure state, the trailing swing levels, prev_hi and prev_lo).
  disp_atr is used by the entry only.
* **New fixed numbers**: none.
* **No look-ahead**: `pivots_conf` marks a swing at bar t = p + swing_k: 2 bars later on the 1h pick, 5 on the 4h pick.
  `structure()` is one forward pass, so lo_lvl, the state and the bos / mss flags at bar i use bars <= i only.
  prev_hi[s] was set at or before s. The flags are read at closes after s.
* **Code**: `S = X.S(p['swing_k'])`, cached by the entry under ('S', k). lx = S['bos_dn'] | S['mss_dn'] and sx =
  S['bos_up'] | S['mss_up']. tgt_l[s] = S['prev_hi'][s] and tgt_s[s] = S['prev_lo'][s]. There are no invalidation
  levels. These are global per-bar arrays: the entry itself is a global structure event, so the state after it is the
  trade's state.
* **Edge cases**: if prev_hi is NaN (fewer than two swing highs) or at or behind the fill, there is no target; the exit
  is the structure flip or the hard stop. Invalidation on the entry bar cannot happen (mss_up requires an up break
  without a down break), and that bar is never checked. If the swing low before the shift was already broken (lo_bos
  false), there is no live level until the next swing low is confirmed, swing_k bars after it forms; until then only the
  hard stop and the target act, as the engine itself defines. On the 4h pick (swing_k 5), a swing low is confirmed 20 h
  after it forms, so the trailing level reacts late. Its 1 ATR hard stop will usually sit closer than the protective
  low. Holds can be long on 4h when no target is in reach, and the owners will see that in the hours table.
* **Korean**: 롱이면 매매법의 구조가 다시 하락으로 바뀌면(최근 확인된 스윙 저점 아래로 봉 마감) 바로 전량 청산하고, 깨뜨린
  고점 바로 전의 스윙 고점에 닿으면 익절합니다. 새 스윙 저점이 확인될 때마다 청산 기준이 그 저점으로 바뀝니다(보통은
  올라가지만 내려갈 수도 있습니다).

### A.12 F1_PVT_DIV (PVT 다이버전스): ds-F1_PVT_DIV-1h-1

* **Entry** (for reference): pick ds-F1_PVT_DIV-1h-1 (swing_k 9, div_max_bars 75; tp3R|2). PVT = cumsum(volume x (c /
  c[-1] - 1)). The entry needs two consecutive confirmed swing lows at pivots a < b (strictly lower than the 9 bars on
  each side), with b - a <= 75, l[b] < l[a] and PVT[b] > PVT[a] (a bullish divergence). Long fires at b + 9, the bar
  that confirms the second low. Short mirrored on two consecutive swing highs: h[b] > h[a] and PVT[b] < PVT[a].
* **Invalidation**: long: a chart close below l[b], the second (divergence) low. Short: a close above h[b]. Fixed at the
  signal bar. Reason: the divergence says selling dried up at that low, so a close below it makes a new lower low and
  voids the pattern. PVT is not used by the exit: a PVT drop below PVT[b] while price holds can come from a single
  volume bar, and traders invalidate divergences on price.
* **Target**: long: the highest high between the two lows, max(h[a .. b]), the bounce peak where the second sell-off
  began (the classic divergence target). Short: the lowest low between the two swing highs, min(l[a .. b]). Fixed at
  the signal bar.
* **Inputs from the combo**: swing_k (which pivots exist, and the confirm lag) and div_max_bars (which pairs count).
  Together they decide the pair (a, b) behind each signal, and both levels come from that pair.
* **New fixed numbers**: none.
* **No look-ahead**: pivot b is confirmed at b + swing_k (9 bars later), and that bar is the signal bar; a < b. l[b],
  h[b] and the max / min over bars a .. b all lie at or before the signal bar. The exit reads later closes only. PVT's
  cumulative starting point does not matter, because the exit does not use PVT.
* **Code**: P and Q = the cached ('pividx', k) pair from `X.piv(k)`, where Q holds the swing-low pivots and P the
  swing-high pivots. ind = the cached ('pvt',) array. Recompute ok over the consecutive pairs exactly as `_div` does.
  For each ok low pair (a, b), s = b + k, inv_l[s] = X.l[b] and tgt_l[s] = X.h[a:b+1].max(). For each ok high pair,
  inv_s[s] = X.h[b] and tgt_s[s] = X.l[a:b+1].min(). Each b is the second pivot of at most one pair, so each signal bar
  has one pair. Assert that every final signal bar received its levels. lx = sx = False.
* **Edge cases**: with swing_k 9 the entry comes 9 bars after the low, so price may already be above the in-between
  peak. Then the target is at or behind the fill: no target, and the invalidation and hard stop act alone. Invalidation
  on the entry bar cannot happen (bars b+1 .. b+9 all have lows above l[b], so c[s] > l[b]), and that bar is never
  checked. If l[b] is beyond the 2 ATR hard stop, the stop acts first. A later, lower swing low does not move the
  level, which stays fixed. A bar that is both a long and a short pair end is dropped by `ds_defs`, so it carries no
  signal.
* **Korean**: 롱이면 다이버전스의 두 번째 저점 아래로 봉이 마감하면 전량 청산하고, 두 저점 사이에서 가장 높았던 가격에 닿으면
  익절합니다. 숏은 반대입니다.

### A.13 F5_BOX (박스권 양 끝 반전): ds-F5_BOX-15m-1, ds-F5_BOX-4h-1

* **Entry** (for reference): picks ds-F5_BOX-15m-1 (box_len 72, adx_max 16, edge 0.12, width_atr 9; tp3R|3) and
  ds-F5_BOX-4h-1 (box_len 48, adx_max 60, edge 0.45, width_atr 1.5; tp3R|4). Box: hi = the highest high and lo = the
  lowest low of the previous box_len bars (X.hmax1 and X.lmin1). The box is valid when ADX14 < adx_max and hi - lo >=
  width_atr x ATR14. Long when pos = (c - lo) / (hi - lo) is in [0, edge] and the bar is bullish (c > o). Short when pos
  is in [1 - edge, 1] and the bar is bearish.
* **Invalidation**: long: a chart close below lo, the box low fixed at the signal bar, because the floor the trade
  bought has broken and the range has become a breakdown. Short: a close above hi. The box does not roll during the
  trade. An ADX rise above adx_max was not used: ADX has no direction and also rises during a move toward the target.
* **Target**: long: the opposite edge of the box, hi, fixed at the signal bar. Short: lo. A range trade is fulfilled at
  the other side of the range.
* **Inputs from the combo**: box_len (both edges). adx_max, edge and width_atr gate the entry only.
* **New fixed numbers**: none.
* **No look-ahead**: hi and lo are rolling(box_len).max / min().shift(1), so they use bars s - box_len .. s - 1 and are
  known before s closes. The exit reads only the closes of bars after s.
* **Code**: `hi = X.hmax1(p['box_len'])` and `lo = X.lmin1(p['box_len'])`, the cached arrays the entry used. For each
  long signal bar s, inv_l[s] = lo[s] and tgt_l[s] = hi[s]. For each short, inv_s[s] = hi[s] and tgt_s[s] = lo[s].
  lx = sx = False.
* **Edge cases**: since edge <= 0.5, the signal close is in the near half of the box, so only a fill that gaps past the
  far edge can put the target at or behind it; then there is no target. Invalidation on the entry bar cannot happen
  (pos >= 0 means c >= lo), and that bar is never checked. On the 4h pick, adx_max 60 and a minimum width of 1.5 ATR
  allow narrow boxes, so the floor and the target can both be close to the entry. Its edge 0.45 also lets entries sit
  near the middle. The target stays the far edge, not the opposite entry band. On the 15m pick the box is at least 9 ATR
  wide, so the floor is at most 0.12 x width below the entry close and the target at least 0.88 x width above it. A hard
  stop closer than the floor acts first.
* **Korean**: 롱이면 진입할 때의 박스 바닥 아래로 봉이 마감하면 전량 청산하고, 박스 천장에 닿으면 익절합니다. 숏은 반대이고,
  박스는 진입 때 것으로 고정합니다.

### A.14 F7_RF_ONLY (레인지 필터 방향 전환): ds-F7_RF_ONLY-30m-1, -1h-3, -4h-1

* **Entry** (for reference): picks ds-F7_RF_ONLY-30m-1 (rf_period 80, rf_mult 9.0; tp3R|4), ds-F7_RF_ONLY-1h-3
  (rf_period 67, rf_mult 2.4; tp3R|4) and ds-F7_RF_ONLY-4h-1 (rf_period 33, rf_mult 1.0; tp3R|3).
  `ds_defs.range_filter_dir`: the range r = rf_mult x EMA(span 2 x rf_period - 1) of EMA(span rf_period) of |close
  change|. The filter f steps up to c - r when c - r > f and down to c + r when c + r < f. The direction is the sign of
  its last step. Long on the bar where the direction turns from -1 to +1, short where it turns from +1 to -1.
* **Invalidation**: long: the range-filter direction is -1 at a chart close, i.e. the filter stepped down because a
  close fell below f - r. Short: the direction is +1. For this strategy that is exactly its own opposite signal: the
  direction stays +1 until it turns, so the first -1 bar is a short signal bar. The strategy's own exit is therefore the
  opposite-signal exit (F3) without a take-profit (mode b): stop and reverse, the way the Range Filter is traded.
* **Target**: none (a trend-following filter; the exit is the direction turn alone).
* **Inputs from the combo**: rf_period, rf_mult.
* **New fixed numbers**: none.
* **No look-ahead**: `range_filter_dir` is a forward recursion over closes (EWMs with adjust=False, then the filter
  step), so the direction at bar i uses closes <= i only.
* **Code**: `rf = D._rf_dir(X, p)`, cached by the entry under ('rf', rf_period, rf_mult). lx = (rf == -1) and sx =
  (rf == 1). There are no levels.
* **Edge cases**: this exit is identical to F3 for these three picks: F11.a = F3.a (both keep the pick's 3R) and
  F11.b = F3.b. The select table marks both pairs as the same rule, so they are not counted as two (Known limit 11). On the entry bar rf == 1, so it cannot fire there,
  and that bar is never checked anyway. The 30m pick's rf_mult 9 makes turns rare, so holds can be long and swing-like;
  the owners will see that in the hours table, and no number is added to speed it up. The recursion depends on where
  the series starts, so the league's `chart_frame` window must give the same direction as the study's full history.
  The entry parity already requires this, because the exit reads the same array (11.4 item 7).
* **Korean**: 레인지 필터 방향이 반대로 바뀌면(= 반대 신호) 바로 전량 청산합니다. 목표가는 없고, 방향이 유지되는 동안 계속
  들고 갑니다.

### A.15 F7_RF_TRIPLE (레인지 필터 3중 일치: 레인지 필터 + 하이킨아시 + 상위 봉 하이킨아시): ds-F7_RF_TRIPLE-1h-1, -4h-1

* **Entry** (for reference): picks ds-F7_RF_TRIPLE-1h-1 (rf_period 80, rf_mult 9.0; tp3R|4) and ds-F7_RF_TRIPLE-4h-1
  (rf_period 50, rf_mult 4.5; tp3R|3). Long on the first bar of a run where all three agree up: the range-filter
  direction is +1, the chart Heikin-Ashi candle is up (heikin_bull == 1), and the higher-timeframe Heikin-Ashi candle is
  up (4h for the 1h pick, 1d for the 4h pick; `htf_value` takes the last HTF bar closed at or before the chart close).
  Short: all three point down (rf -1, HA 0, HTF HA 0), first bar of the run.
* **Invalidation**: long: any of the three turns down at a chart close, i.e. rf == -1, or the chart HA == 0 (a red
  Heikin-Ashi candle), or the HTF HA == 0. Short: rf == +1, or HA == 1, or HTF HA == 1. Reason: the entry is the moment
  the three agree, and the strategy itself signals again each time agreement returns, so the end of agreement ends the
  reason for the trade. A flat HA candle (0.5) or a missing HTF value (NaN, warm-up only) does not fire, because nothing
  has turned.
* **Target**: none (trend agreement; the exit is the invalidation alone).
* **Inputs from the combo**: rf_period, rf_mult (the filter). The chart and HTF Heikin-Ashi have no numbers, and HTF_OF
  is lib_c's fixed map.
* **New fixed numbers**: none.
* **No look-ahead**: rf is a forward recursion, as in F7_RF_ONLY. heikin_bull uses the HA close (o + h + l + c) / 4 and
  an HA-open recursion over earlier bars only. The HTF HA comes from `search.htf_series`, which takes the last
  higher-timeframe bar whose close is at or before the chart bar's close (searchsorted side='right' minus 1). An HTF
  candle that is still forming is never used, and the value changes only at chart closes that are also HTF closes.
* **Code**: `rf = D._rf_dir(X, p)`; `ha = X.get(('ha',), ...)` and `hha = X.get(('hha',), ...)` are the arrays
  `_f7_triple` cached. lx = (rf == -1) | (ha == 0) | (hha == 0) and sx = (rf == 1) | (ha == 1) | (hha == 1). There are
  no levels. This is not F3: the opposite signal needs all three down at the first agreement, which is much rarer.
* **Edge cases**: this is the fastest reading of the strategy: one red HA candle on the chart timeframe ends the trade,
  and the strategy re-enters at the next first agreement, paying a round trip each time. Two slower readings were
  considered and not chosen: exit only when the RF turns, or only when the HTF HA turns. They were rejected because the
  strategy's own state treats all three as the reason. The owners' hours and entries table will show the cost. On the
  entry bar all three agree, so the rule cannot fire there, and that bar is never checked. The HA and HTF HA recursions
  depend on the series start, as the RF does, so the league window must match the study as it must for the entries.
* **Korean**: 레인지 필터, 하이킨아시 캔들, 상위 봉 하이킨아시 셋 중 하나라도 반대로 바뀌면 바로 전량 청산합니다. 목표가는
  없고, 셋이 다시 맞으면 매매법이 새로 진입합니다.

### A.16 F9_FVG (FVG 되돌림, FVG 가격 틈 되돌림): ds-F9_FVG-1h-1, ds-F9_FVG-4h-1

* **Entry** (for reference): picks ds-F9_FVG-1h-1 (fvg_min_atr 1.0, zone_life 40; tp3R|4) and ds-F9_FVG-4h-1
  (fvg_min_atr 0.1667, zone_life 75; tp3R|2). A bullish FVG is born at bar b when l[b] > h[b-2] by at least
  fvg_min_atr x ATR14[b]; its zone is [lo, hi] = [h[b-2], l[b]]. Long at the first bar s in b+1 .. b+zone_life whose
  low touches the zone top (l[s] <= hi), when that bar closes at or above the zone middle (conf 'mid'). Bearish FVG
  mirrored: zone [h[b], l[b-2]], short at the first touch (h[s] >= lo) with a close at or below the middle.
* **Invalidation**: long: a chart close below the gap's bottom, lo = h[b-2]. Short: a close above the gap's top, hi =
  l[b-2]. Fixed at the signal bar. Reason: the gap is the support the trade buys, and a close through its far side is
  the family's own inversion rule (`flip_zones` turns such a gap into an opposite iFVG zone), so the gap has failed. The
  gap middle, the entry's own confirm level, was not used: it is tighter and still inside the gap.
* **Target**: long: the swing high the gap's move made before price came back, max(h[b-1 .. s-1]), from the
  displacement candle through the bar before the touch. Short: min(l[b-1 .. s-1]). Fixed at the signal bar.
* **Inputs from the combo**: fvg_min_atr (which gaps exist) and zone_life (which touches fire). Together they identify
  the zone behind each signal.
* **New fixed numbers**: none. Tie rule (not a number): when several gaps fire on the same bar and side, the most
  recently born one (largest b) gives the levels.
* **No look-ahead**: a gap at b needs only bars b-2 .. b and ATR14[b]. The touch bar is s > b, and the zone table's
  touch test reads bars b+1 .. s only. The target uses bars b-1 .. s-1, and the invalidation level is h[b-2] (l[b-2]
  for a short). Everything is known at s's close, and the exit reads later closes only.
* **Code**: with the same cache, `Z = X.fvgz(p['fvg_min_atr'])` gives (b, lo, hi, d, kill). `T = X.table(('fvgtab',
  fvg_min_atr), build, zone_life)` is a cache hit and returns the same table the entry used, built with
  `zone_table(..., 'mid')`. Rows m = T['ft'] < zone_life give s = T['s'][m], zi = T['zi'][m], up = T['up'][m], and zi
  indexes Z. For each final long signal bar s, zi* = the up row at s with the largest b[zi]; inv_l[s] = lo[zi*] and
  tgt_l[s] = X.h[b*-1 : s].max(). For each short, inv_s[s] = hi[zi*] and tgt_s[s] = X.l[b*-1 : s].min(). lx = sx =
  False. Assert that the recovered rows reproduce the signal arrays, except bars `ds_defs` dropped as both-side.
* **Edge cases**: s >= b + 1, so the target window b-1 .. s-1 holds at least two bars. Bars b+1 .. s-1 never touched the
  gap, so they sit above it and the long target is above the gap. A touch bar that rallies through the prior high puts
  the close or fill at or above the target; then there is no target, and the invalidation and hard stop act alone.
  Invalidation on the entry bar cannot happen (c[s] >= middle > lo), and that bar is never checked. The 4h pick's gaps
  can be as small as 1/6 ATR, so the gap bottom can be very close to the entry. The cut still needs a full close
  through it, and the 2 ATR hard stop is unchanged. When several gaps fire at once, the largest b is used.
* **Korean**: 롱이면 가격 틈(FVG)의 아래 끝 밑으로 봉이 마감하면(틈이 무너짐) 전량 청산하고, 틈이 생긴 뒤 되돌아오기 전에 만든
  고점에 닿으면 익절합니다. 숏은 반대입니다.
