# Flexible exits for the 38 league watch picks: pre-registration (exitflex v1)

**Status.** Pin commit: see the commit message of the commit that adds `PREREG_EXITFLEX.sha256`. That commit hashes this
file; the pin time (UTC and KST) is written in its message and not in this file.

(한국어 요약: `README_KO.md`.) This file is fixed before this study's own runs produce any number. It is pinned by
`PREREG_EXITFLEX.sha256` together with the code and inputs of section 13. Changes after the pin go to `DEVIATIONS.md`
in this folder, dated and with the reason, never into this file. Select-period numbers of E0 on the core picks have been
seen by the main session, and so have the round-1 trend-hunt results (the dated addendum in section 15, which changes
Known limit 1); section 15 lists what was seen and says what follows. Section 16 lists what changed in each revision
and why (16.5: the alignment with the code as built, made just before the pin; 16.6: the stepped-lock family F13 and the final
items; 16.7: the eighth pass, after a dry run on a scratch pin). Appendix A writes out each strategy's own
exit (family F11). Section 17, after Appendix A, is the main session's checklist of what must hold before this file is
hashed, with what is already true ticked and what is still open listed.

First draft 2026-10-12 01:41 UTC; revised 2026-10-12 (UTC) after two design reviews; revised again 2026-10-12 (about
02:40 UTC) after the owners' four later messages below; revised a third time 2026-10-12 after two reviews of the second
revision (section 16.3); revised a fourth time 2026-10-12 (after about 12:20 KST) for the main session's decisions and
the owners' three latest messages below (section 16.4); revised a fifth time 2026-10-12 after two reviews of the fourth
revision (section 16.4, items 9 on); aligned with the code as built, just before the pin (section 16.5); then, still before the
hash, the owners' stepped-lock request (messages 8 and 9 below) added as family F13 and the last pin-blockers closed (section
16.6); then a dry run on a scratch pin and, after the owners' evening messages (message 10 below), the eighth pass (section
16.7). Owners' first request, about the 후보 리그 ("커스텀값 봇"),
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

**Owners' latest messages, 2026-10-12** (after the third revision; verbatim):

5. "딥시크 금액 알려주고 청산방식 9가지를 동시에 다 적용하는방식이 제일 좋은 청산방식 아니야?" (They ask for the
   DeepSeek money figures, and whether applying all the exit kinds at once is the best exit. Sections 1, 3 and 5.2,
   family F12.)
6. "60% 간 뒤 구조가 깨지면 익절 / −40%에서 구조가 깨지면 손절 - 60%랑 -40%는 예를든거지 고정 익절 고정 손절을 하라는말은
   아니야 유도리있게" (Their numbers were examples, not fixed values. Section 1.)
7. "기준은 정확히 못정하겠어 장에 따라 다르잖아 솔직히" (They cannot fix a hold-time target; it depends on the market.
   Section 7, hold hours by market state.)

**Owners' messages of the afternoon of 2026-10-12** (after the fifth pass and the alignment; verbatim, two messages):

8. "잠금 수익 최소 10%로 해주고 12%되면 10%잠금 계단식익절로 무슨말인지 알지?" (They mean the rule bot's own stepped profit lock,
   `paperbot/ladder.py` `LadderSpec`: first lock 0.10, step 0.05, trigger gap 0.02, so a best net ROE of 12% locks 10%. Only the
   10% start; no 5% or 20% start. They had noticed that the 38 picks use fixed 3R, 2R and net-ROE take-profits, that none uses
   this lock, and that the list of this study did not have it. Sections 1 and 5.2, family F13.)
9. "12%되면 10% 20%면 15% 30%면 25% 이런식 무슨느낌인지 알지?" (The same lock in their words. The engine's ladder gives exactly
   their examples: a best net ROE of 12% locks 10%; 20% lies in [17%, 22%) and locks 15%; 30% lies in [27%, 32%) and locks 25%.
   The triggers are 12%, 17%, 22%, 27%, 32% ... and the locks 10%, 15%, 20%, 25%, 30% ... in 5% steps, without end.)

**Owners' messages of the evening of 2026-10-12** (verbatim; four messages given as one item; sent between about 17:30 and
19:00 KST, the times approximate because the chat carries no timestamps):

10. (a) "코인별로도 백테스트 분석해줘야지 아니 이번에 커스텀값봇 매매법 청산 백테스트 다시 할꺼잖아 추가로 분석하면 좋을 부분들
    없어? 엄청 많을꺼 같은데 내 목표 수익률 매매법을 위해 좀 노력좀 해주라 이왕 백테스트 돌리는 김에 분석하면 좋을부분들 싹 다
    넣어서 제대로 과거 백테스트 분석 해보자" (b) "진짜 이제 마지막으로 물어본다 잘생각해 이제 안물어볼꺼야 진짜 진짜 마지막으로
    백테스트 작업전에 내 목표를 위해 추가하면 좋을 분석부분들 있으면 마지막으로 추가작업해줘 없으면 말고" (c) "3개는 먼저 넣고
    2개는 2단계로 가고 1개는 다른 방식으로 확인하는게 맞는방법이야? 궁금해서" (d) "1차 작업때 기본수치 작업도 같이 해야 커스텀값
    수치랑 비교할수있지않을까? 2차때 한다고 듣긴 들었는데 1차때 하는게 맞지 않나?" (They ask, before the backtest runs, for every
    further analysis that serves their target return, per coin among others; ask whether splitting the additions into three now, two
    in a second stage and one checked another way is right; and ask for the default numbers to be run in the first stage, beside the
    custom values, so that the two can be compared. Section 16.7 item 4: the extra reads and the twin accounts, in a separate file.
    These messages carry no DeepSeek figure.)

**What the main session promised them** (in Korean, before this revision), and where this file carries it out:

* (a) nine kinds of exit: structure break, moving-average break, opposite signal, chandelier trail, profit giveback,
  early loss cut, time stop, stall, and each strategy's own exit. They are numbered F1-F11 because F8 and F9 combine
  the structure break with a gain or a loss; the time stop has a bar-count form (F7) and a clock-hour form (F7h). F12
  applies the nine at once (message 5). Section 5 and Appendix A.
* (b) as given: "the hard stop stays as a backstop, early cuts only on a confirmed structure break at a bar close".
  Every variant keeps the hard stop unmoved and decides every early exit at a bar close (sections 4 and 5.1). Not
  every variant's early loss cut is a structure break: F2, F3, F4, F4 q15, F7, F7h, F11 and F12 can also cut a loss on a
  moving average, an opposite signal, a trail, the clock or a strategy's non-structure condition. Section 5.3 sorts
  every variant by what it can cut a loss on; the select report shows that category on every row (8.2); and the
  default of 8.4 takes only variants that cut a loss before the hard stop on a structure break at a loss deeper than
  0.5R (Rc < -0.5), or not at all before a gain (F13, the stepped lock of 5.2, cuts nothing before a gain; it is the one exit
  that acts inside a minute, as a price-level stop, and not at a bar close). Variants outside that set can be run only when
  the owners choose them by name.
* (c) a select-period (2021-2023) table by hold time in hours and by entries, from which the owners choose; then one
  confirm on 2024-2026. Sections 8 and 9. The table lists every variant, choosable or not (8.2).
* (d) all 38 league picks, DeepSeek included, DeepSeek shown without money in every committed file and committed
  report. The owners' request of 2026-10-12 ("딥시크 금액 알려주고") is met by a private report outside the repository
  (section 3).
* (e) after a PASS and their OK, the league is stopped and restarted cleanly from the new install time, with, per
  pick, a new-exit account and a current-exit account side by side plus a coin-flip account; the old record kept as a
  backup; a checkpoint one month after the restart. Section 11.
* (f) if nothing passes, they are told plainly and decide with us. Sections 8.6 and 11.1.
* (g) hold hours overall and by market state at entry as information columns, because the owners cannot fix one
  hold-time target ("장에 따라 다르잖아", message 7). Sections 7, 8.2 and 9. They decide nothing.
* (h) the owners' stepped lock (messages 8 and 9): the rule bot's own profit lock, 12% -> 10%, 17% -> 15%, 22% -> 20% ..., as
  family F13 in two variants (the pick's own take-profit kept, or the lock alone). Sections 1, 5.2 and 5.3. F12 does not
  contain it.

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
* **Q-C (the owners' question of message 5): is applying all nine kinds of exit at once the best exit?** F12 (5.2)
  closes the position at the first trigger of nine components. It is a candidate like every other variant: same
  gates, same placebo, same choice and same single confirm. Stacking is not assumed to help. We expect F12 to leave
  very early on small wobbles, because the first of nine triggers ends the trade and any one of them, a close below the
  last swing low, below the 20-bar average or 2 ATR under the peak, is enough. That expectation comes from how the rule
  is built, not from any number; the table decides. The answer is the table: F12.a and F12.b stand in the select table
  beside the single rules, hold hours and entries first, and for core a reader may compare their pooled growth with the
  single rules' rows (descriptive: the select period ranks 88 rows, so the best row is flattered by chance, Known limit
  2). A pass of F12 shows that F12 beat E0 and its own placebo; it does not make F12 "the best exit", and this study
  does not claim that. F12 cuts a loss on any structure break, so it is outside the default set D (5.3). Nor are all
  nine rules at work on every pick: F6 never moves F12's exit, and F10 can act only on the 13 picks of 15m and 30m, so
  on the other 25 picks (1h and 4h) at most seven of the nine can end a trade and on the 13 at most eight (5.2, Known
  limit 17). Q-C is therefore answered for this one fixed combination only.
* **Q-D (the owners' stepped lock, messages 8 and 9): does the rule bot's own profit lock beat the pick's current exit?** F13
  (5.2) keeps the pick's hard stop and adds the engine's stepped lock: once the best price has reached +12% net ROE the stop
  never lies below +10%; at +17% it lies at +15%, at +22% at +20%, and so on in 5% steps. F13.a keeps the pick's own fixed
  take-profit as well; F13.b has no fixed take-profit, the lock alone (the rule bot's own exit). It is a candidate like every
  other variant: same gates (except the placebo gate, which it does not have, section 6), same choice by the owners, same
  single confirm. It reads no chart structure. It is none of the nine kinds the owners named before, and **F12 does not contain
  F13** (5.2): F12 has no lock.
* **No fixed percent anywhere (owners' message 6).** The "+60%" and "-40%" in the owners' first request were examples,
  and the "+60% ROE ... -40% ROE" figures in this file are always examples of R, never rule values. No rule of this
  study except F13 fires on a fixed percent of price or of ROE. Every threshold is read per trade: R (the net R of the trade's own
  stop distance, which is k x ATR14 of its own signal bar, section 4), an ATR multiple (F4), a count of bars or hours
  (F7, F7h, F10), the trade's own swing structure (F1, F6, F8, F9) or a level fixed at that trade's signal bar (F11).
  The fixed percents left are not thresholds chosen for this study: the net ROE 50% take-profit of core-OBV_S-1h-3, which is
  part of that pick's E0 and stays in mode (a), and the stepped lock of F13 (12%, 17%, 22% ... net ROE locking 10%, 15%, 20% ...),
  which the owners asked for by name (messages 8 and 9) and which is the rule bot's own ladder in `paperbot/ladder.py`, fixed
  before this study and tuned on no result; F13 has one ladder and no grid. The grids are checked for arms like this:
  * **Arm in R**: F5 (P = 1, 1.5, 2 R; 12 variants), F8 (P = 1, 2 R; 12), F6.d0.5 (a loss deeper than 0.5R; 3), F9 and
    F9 q15 (P = 1R and d = 0.5R; 4).
  * **No arm** (the rule adapts to each trade with no threshold): F1 and F1 q15 (a structure break at any profit or any
    loss; 12 variants), F6.d0 (any net loss after costs; 3) and F10 (any profit, no R value; 4). F2, F3, F4, F7, F7h
    and F11 have no profit or loss arm at all.
  * F1 is the no-arm structure break on both sides; F8 is F1 with an arm on the profit side, F6.d0.5 with an arm on the
    loss side, F9 with both. F5 and F8 have **no no-arm cell**: their smallest arm is 1R, and a giveback from any
    profit (F5 with P = 0) is not in the grid, so it is not tested (Known limit 16). The count of variants is not
    changed for it.
  * **Fixed percent of net ROE, no grid**: F13 (the engine's lock, 2 variants). It is not in R: the lock fires at the same net
    ROE whatever the stop distance, as the rule bot does, so at another leverage it sits at another price (Known limit 19).
* **Hold time comes first in every table.** The owners want a day-trading feel ("단타"), not swing holds. A shorter
  hold pays only when the extra entries earn more than their costs (section 7 gives the engine's cost of one round
  trip). The study decides on account growth. Hold hours and entries lead every table so that the owners choose with
  them in view (section 8). The owners cannot fix one hold-time target because it depends on the market (message 7), so
  the reports also show hold hours by market state at entry (section 7). That split is information: not a gate, not a
  default, not a choice per state.
* **Naming.** F1 to F12 in this file are exit families. Several DeepSeek strategies have names that also start with F
  (F1_PVT_DIV, F5_BOX, F7_RF_ONLY, F7_RF_TRIPLE, F9_FVG, F10_OTE, F11_TSOUP, F12_MSS_DISP). These are lib_c's names and
  have nothing to do with the families, F12 (all at once) and F12_MSS_DISP (a DeepSeek strategy) included. A strategy
  is always written with its full name.

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
  kernel's rule). This rule only affects arms that have a take-profit: E0, every mode (a) (F12.a included), and F11.b
  and F12.b on the picks whose own exit has a target (Appendix A). The number of such minutes is reported per arm
  (section 7). Rule exits happen at
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
  appears in any committed file or committed report of this study (`select.json`, `SELECT_KO.md`, `confirm.json`,
  `REPORT_KO.md`, `sent.json`, `choice.json`, the `_r2` files of a rerun, the ledger print, the weekly notes, the league
  checks, this folder's `DEVIATIONS.md` and every entry this study writes into `research/fullgrid/DEVIATIONS.md`), in
  any Telegram message about this study's results, or in any agent packet or note to another session: no P&L, wallet,
  growth, log growth or difference of log growth, drawdown in money or multiples, or interval of any of these. The
  one exception is the private owner report below. (The league's own screens are a separate matter, below.)
  * DeepSeek rows show trade counts (offered, entered, skipped, rejected, closed), win shares, hold times (overall and
    by market state, section 7), exit-reason counts (LIQ included), for F12 the component counts of 5.2 (in total and
    split by the pick's timeframe) and pass / fail labels, nothing else.
  * Private, like money: DeepSeek p values of any test (they rank money differences), busts and bust counts, final
    wallet multiples, and any rank of DeepSeek variants by a money figure. The confirm's Holm label and the ledger's
    BH label of a DeepSeek pair are labels and may be shown; its p value is not (sections 9 and 10). Busts and final
    wallet multiples reach the owners only through the private owner report below, never a p value.
  * The DeepSeek money figures and p values that the gates, the placebo gate, the confirm test and the ledger need are
    written only to `$WORK/<pin8>/ds_private/` outside the repository (section 13), read only by the runner, the
    ledger print, the owner-report writer and, for `ds_private/results/select/` only, the modules of the extra reads of
    16.7 item 4 (as a program; the DeepSeek money they compute goes only to the private extra report below). This
    includes the per-account result files of DeepSeek picks (`$WORK/<pin8>/ds_private/results/<stage>/`). Their sha256
    values are committed with `select.json` and
    `confirm.json`. No person or agent opens them (`select_ds.json`, `confirm_ds.json`, `results/`); the owner
    reports below are the only DeepSeek money files that anyone opens.
  * **Owners' relaxation of D11, 2026-10-12, limited to one private report per step** (and one more, for the extra reads of
    16.7 item 4, at the select step: the last sub-bullet). The owners asked to see the
    DeepSeek money ("딥시크 금액 알려주고"). The select step and the confirm step each write one **private owner
    report**: `$WORK/<pin8>/ds_private/owner_report_select.md` and `owner_report_confirm.md` (a select or confirm rerun
    of section 14 writes `owner_report_select_r2.md` or `owner_report_confirm_r2.md` next to them). It holds the
    DeepSeek wallet and growth figures: per DeepSeek variant the pooled monthly log growth difference against E0,
    also as a percent per month, at quarter size and, reported only, at live size; E0's own growth; the median over
    the pool's picks of the final wallet multiple and of the maximum drawdown; busts. The confirm report holds the same
    for E0 and the chosen DeepSeek variants and the 95% interval of M_P(V) of each chosen DeepSeek pair (section 9).
    The select report applies the row rule of 8.2 item 6: money only on choosable rows, none on a row marked
    "선택 불가". Rows follow the committed table's order; the report ranks nothing by money. It holds no p value.
    **The confirm interval is shown knowingly.** It comes from the same block bootstrap as the test, so a lower bound
    above 0 is a coarse stand-in for a one-sided p below about 0.025, and the owners will read it that way. The rule "no
    p value" bars the number p, not this reading.
    * **Where it is shown.** "The conversation" means the chat between the owners and the main session, and nothing
      else. The report is never shown over Telegram, e-mail or any other channel that is logged, synced or forwarded to
      another agent. The main session shows the file there and does nothing else with it: it never commits or pushes it
      and never copies it into a committed file, `out/`, a Telegram message, a dashboard, an agent packet or a note to
      another session. For the select step it is shown in the same turn as, or before, the sending of `SELECT_KO.md`
      that starts the owners' 48 h clock (8.3), so the clock never runs before the owners can see the money. The time
      it was shown goes to `sent.json` (8.7).
    * **The owners' words, the main session's questions, and redaction.** The owners will have read the private report
      before they answer, and may quote a figure from it (the monthly growth of one DeepSeek variant, say, with "take
      it"). Before any owner message, or any question of the main session, that concerns the DeepSeek pool is written
      into a committed file (`choice.json`, `choice_r2.json`, `sent.json`, `REPORT_KO.md`, either `DEVIATIONS.md`, a
      weekly note), every DeepSeek money figure in it, whether a percent, a multiple, a drawdown, a bust or a p value, is
      replaced by the marker `[딥시크 금액 삭제]`. The rest of the message stays verbatim, with its time. The sha256 of
      the unredacted text goes to `$WORK/<pin8>/ds_private/owner_messages.json` (outside the repository, never opened),
      so that the chat transcript can show that only figures were replaced. The main session's own questions quote no
      figure; they name variants by id. The last line of every private report (Korean) asks the owners to name variants by id and not by
      figure. The redaction replaces figures only; it never changes an id, a choice, a time or a deadline. Audit A8 and
      test T7 check the files for what is left (14).
    * The sha256 of the file is committed (field `ds_owner_report_sha256` of `select.json` and `confirm.json`), not the
      file. It is written before the report is hashed and sent (8.7), so the main session can check that the file it
      shows is the file the runner wrote (audit A8).
    * Every rule stays as it was. The gates, the placebo gate and the confirm test compute from `ds_private/` as
      before, the default of 8.4 uses hold hours and no DeepSeek money, and the ledger keeps DeepSeek labels only. The
      owners' view of the report therefore cannot change what any rule does. It can change what the owners choose, as
      the core growth column can.
    * The relaxation covers these two reports and the extra report of the next sub-bullet. It does not reach the weekly
      notes or the league's checkpoint reports, which keep DeepSeek as labels, counts, win shares and hold hours (section
      11.5).
    * **Extension for the extra reads (16.7 item 4; eighth pass).** The extra reads and twins of 16.7 item 4 show no
      DeepSeek money figure or p value in any committed file or sent message. Because the owners asked to see the DeepSeek
      money privately, the DeepSeek money of the extra reads and twins goes only to a third private report,
      `$WORK/<pin8>/ds_private/owner_report_extra.md`, under every rule above: it is shown only in the chat with the owners,
      in the same turn as or before the sending of `SELECT_KO.md`, and is never committed or copied anywhere (above); it
      holds no p value; it shows money only for E0, the house exit and the variants choosable in their pool (the row rule
      of 8.2 item 6; 16.7 item 4), on the picks and on their twins; owners' words that quote it are redacted as above;
      before it is shown it passes the checks that A8 makes on a stage's
      private report (outside the repository and not tracked by git, no p value, the last line asking the owners to name
      variants by id; 14); and its sha256 goes to `sent.json` (`ds_owner_report_extra_sha256`, 8.7), because `select.json`
      is hashed before the extra report exists. This is an explicit extension of the owners' relaxation, not a change of
      any rule: it changes no gate, test, default or choice.
  * **The league's own screens.** On the owners' request of 2026-10-11 ("딥시크 쪽은 왜 금액없이야 똑같이 해야지";
    `research/fullgrid/DEVIATIONS.md`) the league's dashboard, its snapshots and its Telegram notices show DeepSeek
    money, and `CANDLEAGUE_DS_MONEY` is on by default. That is the league's own setting. This study neither changes it
    nor relies on it: the restarted league's screens follow the same setting (the owners can switch it off with
    `CANDLEAGUE_DS_MONEY=0`), and D11 as written above governs what this study writes and sends. The check script, the
    weekly notes and the checkpoint reports of 11.5 may read the league database but print DeepSeek as labels, counts,
    win shares and hold hours only. The private owner reports cover the 2021-2023 and 2024-2026 backtests, never the
    league's live record.
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
  7. The minute's range. A low (long) or high (short) through the stop exits at the stop with slippage (SL, or LOCK once a
     lock has raised the stop). Otherwise a mark low or high through liquidation liquidates. Otherwise a range through the
     take-profit exits at the take-profit, maker (TP). Otherwise the stepped lock steps up from the minute's best price, to
     apply from the next minute. The lock is the kernel's, unchanged; no pick uses it, and only F13 switches it on (5.2).

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
  acts inside a bar. The one exception is F13 (5.2): the engine's stepped lock is not a rule decided at a bar close but an
  intrabar stop at a price level that follows the best price and only tightens; the hard stop stands below it until it does.
* **Mode (a)**: the pick's own take-profit stays (3R for 21 core picks and all 15 DeepSeek picks, 2R for
  core-S4_BB_BBP-30m-1, net ROE 50% for core-OBV_S-1h-3). **Mode (b)**: no fixed take-profit and no lock, so the rule,
  the hard stop, liquidation or the period end closes the trade. The exceptions are F11.b and F12.b, which keep the
  strategy's own target where Appendix A defines one, and F13.b, which has no fixed take-profit but is the stepped lock
  itself (there the lock, the hard stop, liquidation or the period end closes the trade).
* Each rule of F1-F10 is written below for a long. The short is mirrored: high and low swap, above and below swap, max
  and min swap. F11's short side is written out per strategy in Appendix A. F12 stacks F1, F2, F3, F4, F5, F6, F7h, F10
  and F11 and adds no rule of its own; F13 is not one of them and F12 has no lock.

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
  close to the entry price. d = 0.5 needs a loss deeper than half the hard-stop distance. The owners' example (-40% on
  a -60% stop) is about -0.67R.

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
* That is: after a gain of about the stop distance, close everything when the structure breaks; while the loss is
  deeper than half the stop distance, close everything when the structure breaks.
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

**F12 all at once** ["청산방식 9가지를 동시에 다 적용하는방식", message 5], group A, modes (a) and (b), no parameter to
choose, no q15.
* **Rule.** At every check close of the pick's own timeframe (5.1), nine components are tested on the same frozen state
  of step 0: F1 structure break, F2 EMA break (armed), F3 opposite signal, F4 chandelier trail, F5 profit giveback,
  F6 early loss cut, F7h clock-hour stop, F10 stall and F11 the strategy's own exit. Each is exactly the rule written
  above, with its own arm, reference and state, at the value below. No component reads another's result. The first check
  at which any component fires closes the whole position: one RULE exit at that check's minute (section 4). Nothing
  is voted, averaged or ranked. F8 and F9 are not components: F8 is F1 behind an arm, and F1 already fires with and
  without a gain.
* **Values, fixed now at the middle of each component's own grid in 5.2** (no number is tuned on any result and none is
  chosen again):

  | component | grid in 5.2 | F12 value | how it was taken |
  |---|---|---|---|
  | F1 structure break | w = 2, 3, 5 | w = 3 | middle |
  | F2 EMA break | n = 10, 20, 50 | n = 20 | middle |
  | F3 opposite signal | none | none | none |
  | F4 chandelier | m = 1.5, 2, 3 | m = 2 | middle |
  | F5 giveback | P = 1, 1.5, 2 R; g = 0.25, 0.5 | P = 1.5 R, g = 0.5 | middle; larger of two |
  | F6 early loss cut | w = 2, 3, 5; d = 0, 0.5 R | w = 3 (the same swing reference as F1), d = 0.5 R | middle; larger of two |
  | F7h clock-hour stop | H = 4, 8, 16 hours | H = 8 hours | middle |
  | F10 stall | N = 6, 12 pick bars | N = 12 bars | larger of two |
  | F11 own exit | one definition per strategy | Appendix A, unchanged | none |

  A grid of two values has no middle, so F12 takes its larger value. That value lies on the grid, so every component
  runs a path that its own family also runs, and it is the less trigger-happy of the two (a deeper giveback is needed,
  a deeper loss, more bars of stall). Resulting thresholds, for a long: close under the last swing low confirmed with
  3 bars on each side (F1); close under the EMA 20 once the close has been above it (F2); the pick's own short signal
  (F3); close
  under the best price since entry minus 2 x ATR14 (F4); a close at or under half the peak after the peak reached
  +1.5R (F5); a structure break at a loss deeper than 0.5R (F6); the first pick close at or after 8 hours (F7h);
  12 bars without a new extreme while in profit (F10); the strategy's own invalidation (F11). Shorts mirror.
* **Modes.** F12.a keeps the pick's own take-profit (as every mode (a)); its F11 component is the invalidation of
  F11.a. F12.b has no fixed take-profit; its F11 component is F11.b, whose native target stays where Appendix A
  defines one. The hard stop stays in both. F7h at 8 hours caps every F12 hold at about 8 hours on every pick, in both
  modes.
* **Checks** only at the pick's own closes. F12 has no 15m checks and no q15 version, because F2, F3, F5, F7h, F10 and
  F11 have none (section 12). Merged checks (5.4.2): every component follows its own merged-check rule there, and F12
  fires when any component fires.
* **One exit, every reason recorded.** Two or more components can fire at the same check, on the same bar or on
  different bars merged into one check. The exit is still one: one price, one fee, one minute. The first trigger in time
  wins; among triggers at one check no order changes the trade, so none is defined. `tr_reason` is RULE and a second
  field, `tr_comp`, records **every** component that fired at that check as a bit mask (F1 = 1, F2 = 2, F3 = 4,
  F4 = 8, F5 = 16, F6 = 32, F7h = 64, F10 = 128, F11 = 256). The reports print component names in bit order. The select
  and confirm reports give for F12, per component, the number of exits where it fired and where it fired alone, in total
  and split by the pick's timeframe (15m, 30m, 1h, 4h) (counts, also for DeepSeek).
* **Stops come first.** As for every rule, a liquidation, hard stop or take-profit that happens before the check's
  minute has already closed the trade, and at the check's minute the order is liquidation, stop gap, take-profit gap,
  then the rule (5.4.6). F3's reversal at the freed minute works as under F3 (5.4.8).
* **F6 adds no exit time.** F6 at w = 3 fires only where F1 at w = 3 fires (the same reference and update), at a loss
  deeper than 0.5R, so it never moves F12's exit. It stays so that F12 holds all nine kinds the owners named, and so that
  the reason code says when the break came at a deep loss.
* **Which legs can act, by timeframe.** F7h at 8 hours ends every F12 hold at about 8 hours, so a component that needs a
  longer hold never fires. F10 at N = 12 bars needs 12 bars without a new extreme (a check close at least 12 bars after
  T_X, and T_X is not before the fill): 3 h on a 15m pick and 6 h on a 30m pick, but 12 h on a 1h pick and 48 h on a 4h
  pick, which is later than the 8-hour clock, so F7h closes first (a gap of missing bins around the clock check could in
  theory move the clock check later; the clock check is then the first close that exists). F10 can therefore fire only
  on the 13 picks of 15m and 30m (core 4 + 7, DeepSeek 1 + 1) and never on the 25 picks of 1h and 4h (core 6 + 6,
  DeepSeek 6 + 7). With F6 adding nothing, **at most seven** components can ever move the exit on a 1h or 4h pick (F1,
  F2, F3, F4, F5, F7h, F11) and **at most eight** on a 15m or 30m pick (those and F10). F12 is "all nine at once" in its
  rule, not in what it does on each pick. The reports split the component counts by pick timeframe so that the owners
  see which legs acted where, and the claim of 8.5 says it.
* **What we expect, not a result.** The first of nine triggers ends the trade, and F1, F2, F4 and F11 can each fire on
  an ordinary pullback, so we expect F12 to leave early on small wobbles, to make many round trips, and in mode (a) to
  cut some trades that would have reached the take-profit. Whether the extra entries pay for the costs of section 7 is
  what the table shows. F12 is not in the default set D (5.3) because it cuts a loss on any structure break.

**F13 stepped lock** ["잠금 수익 최소 10%로 해주고 12%되면 10%잠금 계단식익절", "12%되면 10% 20%면 15% 30%면 25%", messages 8 and 9], group P, modes
(a) and (b), no parameter to choose, no q15, no check at a chart close, no chart data.
* **Rule: the engine's own stepped lock** (`paperbot/ladder.py` `LadderSpec`; the kernel's `TP_RULES` row "ladder"; the arguments
  `ladder=True, first_lock=0.10, step=0.05, trigger_gap=0.02` of `kernel._trade` and `_trade_x`). The best net ROE of the open
  position is the one of the favourable extreme X (section 4: the highest high since the fill for a long, the lowest low for a
  short, **including the minute just played**). When it reaches a trigger, the stop moves to the price that locks the matching
  net ROE:

  | best net ROE reaches | the stop locks net ROE |
  |---|---|
  | 12% | 10% |
  | 17% | 15% |
  | 22% | 20% |
  | 27% | 25% |
  | 32% | 30% |
  | ... in steps of 5%, without end | ... |

  In the engine's words: the first lock is 10%, each further lock is 5% higher, and a lock arms when the best net ROE is at
  least the lock + 2% (the trigger gap). The lock for a best net ROE b is 10% + 5% x n with n = floor((b - 12%) / 5%) once b >= 12%,
  and none below 12% (`LadderSpec.lock_for`, written with a 1e-12 and a 1e-9 tolerance on the two comparisons, as the kernel has
  them). The owners' examples are this ladder: a best of 20% locks 15%, a best of 30% locks 25%.
* **Net ROE and the locked price.** The kernel's own formulas of section 4: net ROE(P) = lev x (side x (P / fill - 1) - rt - f)
  with the funding share f paid so far, after taker fees and slippage (rt = 0.0014) on isolated margin; the locked stop price for a
  lock L is fill x (1 + side x (L / lev + rt + f)) (`paperbot/ladder.py` `roe_price`). Both use the leverage the account got at the
  entry, so at another size (another leverage tier) the same net ROE is another price (Known limit 19).
* **When it acts.** At the end of every minute j after the entry minute, once the stop, liquidation and take-profit of that
  minute have been checked (section 4, step 7), the best net ROE including minute j's extreme is computed; if it arms a higher
  lock than the one held, the stop becomes the tighter of the held stop and the locked price. **The new stop applies from minute
  j + 1.** The order of the high and the low inside a minute is unknown, so the conservative reading is that the low (for a long) came
  first and met the old stop (`paperbot/ladder.py` states the same). It only tightens: a lock is never lowered, and a lock already
  set is not recomputed when funding is paid later (it moves only when a higher step arms). The entry minute gives no lock step, as
  in the kernel. A hit of the stop exits at the stop price with slippage, taker, recorded **LOCK** once a lock has been raised and SL
  before; an open beyond the stop (a gap) exits at the open with slippage (5.4 item 12).
* **Modes.** F13.a keeps the pick's own fixed take-profit (3R, 2R or net ROE 50%) **and** adds the lock. F13.b has no fixed
  take-profit: the lock alone, which is the rule bot's own exit (the full grid's "ladder|k" on the pick's stop). The pick's hard
  stop (k x ATR14) stays in both and works until a lock replaces it with a tighter stop. A pick that already had a lock would get
  the 10% lock in place of its own (no pick has one, section 3).
* **Everything else is the pick's.** Entries, sizing, leverage, the fill minute, liquidation, funding, the period-end close and the
  free fill minute after an exit are as for E0: a LOCK exit, like a stop, does not free its minute (only RULE and RAND do, section 4).
* **No decision, no check.** F13 reads no chart bar, no indicator, no signal and no check schedule: `rp` is E0's vector (family 0, which reads
  nothing from it; its only non-zero entry is F12's component mask, which family 0 never reads) and the
  variant differs from E0 only in the exit arguments of `kernel_x.exit_of_pick` (the same function that gives mode (b) its
  arguments). The parity with `kernel._trade` for the same arguments is test T1.
* **Not part of F12.** F12's nine components are F1, F2, F3, F4, F5, F6, F7h, F10 and F11 (above); F13 is not a tenth. F12.a keeps
  the pick's take-profit and has no lock, F12.b has neither. No variant of F1-F12 adds the lock.
* **Category.** Group P (profit protection: its own group, so that the owners can choose it with a variant of any other group).
  Loss class L0 (5.3): the lock exists only after the best price has reached +12% net ROE, so it cuts nothing before a gain; the
  trade it ends lies at or above +10% net ROE less the slippage of a stop (about 0.6 points of ROE at 30x, 1 point at 50x), or at a gapped open,
  which can lie anywhere (the same remark as for F5 and F8). It is in the default set D (8.4). **No placebo** (section 6).
* **What we expect, not a result.** The lock turns a pullback of a trade that has reached +12% into an exit near +10% and so
  shortens such holds; in mode (a) it can also end a trade that would have gone on to its take-profit after a pullback; in mode
  (b) a trade that never reaches +12% is held to the hard stop or the period end, as E0's trades that reach neither target are.
  Whether this pays for the entries it frees and the take-profits it gives up is what the table shows.

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
| F12 | A | all nine at once, values fixed in 5.2 | a, b | 2 |
| F13 | P | none (the engine's stepped lock, fixed in 5.2) | a, b | 2 |
| **total** | | | | **88** |

Plus the reference E0. Every variant runs on every pick of both pools. (The 88 are the 82 of F1-F10, the 2 of F11, the 2 of
F12 and the 2 of F13.)

* **Ids**: `F1.w3.a`, `F1.w3.b.q15`, `F2.n20.b`, `F3.a`, `F4.m1.5.a`, `F4.m2.b.q15`, `F5.P1.5.g25.a`, `F6.w2.d0`,
  `F6.w2.d0.5`, `F7.N24.b`, `F7h.H8.a`, `F8.w3.P1.a`, `F9.a`, `F9.b.q15`, `F10.N6.a`, `F11.a`, `F11.b`, `F12.a`,
  `F12.b`, `F13.a`, `F13.b`.
* **Groups** (used in section 8 so that two variants chosen in one pool are not near copies):
  * S, structure: F1, F1 q15, F6, F8, F9, F9 q15;
  * M, moving average: F2;
  * O, opposite signal: F3;
  * C, chandelier: F4, F4 q15;
  * G, giveback: F5;
  * T, time: F7, F7h;
  * L, stall: F10;
  * N, the strategy's own exit: F11;
  * A, all at once: F12 (its own group, so the owners can choose F12 with a variant of any other group, and so that
    F12, which holds an F7h leg, is not counted as a time stop);
  * P, profit protection, the stepped lock: F13 (its own group: it is not a structure, moving-average, giveback or time rule, so
    the owners can choose it together with a variant of any other group, F5's giveback and F12 included).
* **Canonical order**, used for ties, tables and seeds: the table's rows in order. Inside a row, parameters ascending in
  the order written (F5 by P then g, F6 by w then d, F8 by w then P), then mode a before b.
* **Parameter count**: the numeric parameters plus one for q15. Modes are not counted.
  * 0: F3, F11, F13 (the lock's three numbers are the engine's, not parameters of this study).
  * 1: F1, F2, F4, F7, F7h, F10.
  * 2: F1 q15, F4 q15, F5, F6, F8.
  * 3: F9. 4: F9 q15.
  * 8: F12 (its fixed numbers, counted as for F9: w, n, m, P, g, d, H, N; F6's w is F1's w).
* **What each variant can cut a loss on** before the hard stop (promise (b); shown on every row of the select report,
  8.2). Four categories:
  * **L0, no early loss cut before a gain**: F5 and F8 act only after Rpk has reached +P R (a later exit can still
    land below the fill after a fall), F10 only while Rc > 0, F13 only after the best price has reached +12% net ROE (5.2).
  * **L1, structure break at a loss deeper than 0.5R (Rc < -0.5)**: F6.w*.d0.5, F9, F9 q15 (F9 and F9 q15 also have
    F8's leg after a gain).
  * **L2, structure break at any loss**: F1, F1 q15, F6.w*.d0. They keep promise (b) as worded, but they can cut a
    loss close to the entry price, which owners' message 3 ("너무 빠른 손절구조를 원하는것도 아니야") warns against.
  * **L3, not only a structure break**: F2 (moving average), F3 (opposite signal), F4 and F4 q15 (chandelier trail;
    m = 1.5 on a 4 ATR stop can cut near -0.4R), F7 and F7h (the clock), F11 (each strategy's own invalidation, which
    for DOGE, N03_ADX_GC, N09_ALLIG_AROON, N10_HA_PSAR, OBV_S, S4_BB_BBP and the two range-filter strategies is not a
    structure level; Appendix A), and F12 (all of these at once: it includes F1 at any loss, F2, F3, F4, F7h and F11).
  * The **default set D** of 8.4 is L0 and L1: F5 (12), F6.w*.d0.5 (3), F8 (12), F9 (2), F9 q15 (2), F10 (4), F13 (2); 37
    variants (35 before F13 was added, 16.6). L2 and L3 variants, F12 included, run only when the owners name them.
* **Runs** (E0 and 88 variants = 89 arms):
  * Select, step 1: E0 plus 88 variants, x 38 picks x 2 sizes = 89 x 38 x 2 = 6,764 accounts.
  * Select, step 2 (placebos, section 6): only for the (variant, pool) pairs outside F7, F7h and F13 that pass gates 1, 2
    and 4 of 8.1 in step 1. At most 74 variants (88 less the 12 of F7 and F7h and the 2 of F13; F12 has a placebo) x 23 core
    picks x 200 seeds = 340,400 and 74 x 15 x 200 = 222,000 DeepSeek placebo accounts, 562,400 in all, at quarter size.
  * Confirm: at most (1 + 2) x 38 x 2 = 228 accounts (E0 and up to two chosen variants per pool), plus at most
    2 x 38 x 200 = 15,200 placebo accounts. (Unchanged by F12 and F13: a chosen F12 or F13 is one of the two, and F13 has no
    placebo.)
* **Compute and the seed count (fixed now).**
  * Everything runs on 1m bars. Step 1 is cheap; step 2 is the cost.
  * Before the select run the runner's timing stage runs, in one process on the select-period cut arrays, E0 and one
    placebo seed of each of the 74 variants outside F7, F7h and F13 on one pick, `core-DOGE-15m-1` (a 15m pick: the most check
    closes per hold). Each placebo uses the hazard table of its variant's own account on that pick, which is computed
    and discarded. The stage writes only seconds.
  * Projected step-2 wall time = (the sum of the 74 one-seed times) x 38 picks x 200 seeds / 4 CPUs. This is the worst
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
     (A.0, rule C4);
   * F12 applies the rule of each of its nine components as listed here, and fires when any of them fires.
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
   opposite signal (N13_3OUTSIDE, F7_RF_ONLY), and for F12, whose F3 and F11 components are such exits. A both-flag bar
   would stop the run (the assertion of section 3).
9. **After a bust** no signal is taken, as in the kernel.
10. **F11 levels and targets** are per position, fixed at the signal bar i0 from bars <= i0, and never move (rule C5).
    A native target at or behind the fill is no target (rule C6); then the invalidation, the hard stop and the period
    end act alone.
11. **F12, several components at one check.** All nine components are tested on the frozen state of step 0 and none
    depends on another's result. When two or more fire at one check, whether on the same bar or on different bars
    merged into one check (item 2), there is one exit: the same minute, price, fee and reason RULE as if one had fired,
    and `tr_comp` records every component that fired (5.2). A component that fires at a check where a gap beyond the
    stop, take-profit or liquidation applies is subject to item 1 like any rule. F7h and the hard stop on the same
    minute: item 6 applies. A bar that fires F3 and F11 of a reversing strategy at once gives one exit and one
    reversal entry (item 8).
12. **F13, the stepped lock** (5.2). The lock changes only the stop price, so every case is one of the kernel's own, in its order
    (section 4, steps 3-7):
    * **A lock and the pick's take-profit in the same minute (mode a).** The order is stop, liquidation, take-profit, then the
      lock. A minute that touches the take-profit exits at the take-profit (maker, TP) and raises no lock: the position is gone. A
      minute that touches both the stop (the hard stop or a lock raised earlier) and the take-profit counts as a stop (the
      kernel's stop-first rule; it is added to the number of minutes where stop and take-profit were both touched, section 7). A
      minute that raises the lock and touches neither leaves the new stop to the next minute.
    * **Lock, then stop: the kernel's order.** A lock raised at the end of minute j is in force from minute j + 1. In minute j
      itself the earlier stop is the stop, even if that minute's low (long) lies below the new lock price: the minute does not exit
      by the lock it has just raised. At j + 1 an open at or beyond the new stop exits at that open with slippage (taker, LOCK, and
      the minute is not freed for entries); otherwise a range through the stop exits at the stop price with slippage.
    * **Mode b has no take-profit.** Nothing is touched on the way up; the hard stop, the lock, liquidation or the period end (END)
      closes the trade. A trade that never reaches +12% net ROE is held to the hard stop or END, as in E0.
    * **A gap.** At a minute's open the order is liquidation (mark), then the stop (hard stop or lock) gap, then the take-profit
      gap (mode a), as in section 4; a gapped open beyond a lock exits at the open, which can lie below the locked price and even
      below the fill.
    * **Funding.** The net ROE includes the funding paid before the minute (f of 5.2). A lock set earlier keeps its price. Funding
      paid at the exit minute is paid by a position closed at that minute's open, as in item 7.
    * **The entry minute** gives no lock step (as in the kernel); its range checks the hard stop only.
    * **Size.** The lock is in net ROE, and the leverage can differ between the quarter-size and the live-size account of one
      signal (sizing picks the tier that fits), so the two can lock at different prices (Known limit 19).
    * **A short** is the mirror image: lows and highs swap, the lock lies below the entry reference, and the best price is the
      lowest low.

## 6. Placebo

* **Purpose.** A rule that only shortens holds frees the account more often. A random exit with the same timing profile
  shortens holds in the same way. A Q-B rule must beat it to be described as reading the market. F7 and F7h have no
  placebo: they read nothing by design, and a placebo with their timing profile would be the time stop itself. F13 has none
  either: it makes no decision at a chart close but is an intrabar stop at a price that follows the best price (5.2), so it has no
  check schedule, no check index and no frozen state to match, and it reads no chart, so there is nothing for a random exit to be
  separated from; it is judged on growth, entries and the single confirm. F12 does
  have one: although it holds an F7h leg, eight of its nine components read the market, and Q-C asks whether stacking
  them does more than leaving at random with F12's timing profile. So that the comparison is not one of clocks, the F12
  placebo carries F12's own 8-hour clock exactly (below): the clock is the same and only the exits before it are random.
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
    * F12, the family (the general rule: any component with a precondition is armed or has its reference): z = 1 when at least one
      of these holds at the check, else 0: a swing reference exists (F1 and F6 share it), F2 is armed, F5 is armed, or
      F11's z above is 1. F3, F4, F7h and F10 set no precondition (as above, z = 0 for them alone), so a check where
      only they could fire has z = 0. F6's own precondition (a reference exists and Rc < -d) adds nothing: F6 fires only
      where F1 fires, and F1's precondition, a reference, is in the list already. Because F11's z is 1 at nearly every
      check, F12's z is 1 at nearly every check and its placebo matches age and profit sign only (Known limit 9);
    * F3, F4, F4 q15, F10: z = 0 always.
    * F13: no placebo and so no stratum; where a table needs a value, z = 0, as for F7 and F7h. The reason is stated here: its exit
      is an intrabar price-level stop (5.2), not a decision at a chart close, so there is no check, no check index k and no frozen
      state to stratify.

  All of it uses the frozen state of step 0, so the placebo, like the rule, sees nothing of minute j.
* **Hazard.** For each variant V, pick p and period, from V's quarter-size account:
  h[a, s, z] = (exits recorded RULE at checks of stratum (a, s, z)) / (checks of stratum (a, s, z) at which a
  position was still open after steps 1-5 of the check's minute).
  * The denominator counts every check of V's schedule, armed or not, with a merged check counted once.
  * The numerator counts RULE exits, the RULE + END case included.
  * A check whose minute's open closed the position (LIQ, SL or TP at steps 3-5) counts in neither.
  * h = 0 where the denominator is 0.
  * **F12 only: the clock check.** F12 contains F7h at 8 hours (5.2), so no F12 position is held past its **clock
    check**, the first pick-timeframe check at which F12's F7h component fires (the first pick close at or after
    C0 + 8 hours; a merged check is the clock check when any close merged into it is at or after that time). Ages above
    it hold no F12 position. A table over age buckets alone would leave them at h = 0, and would spread the clock exits
    over the whole bucket that holds the clock check (a 15m pick: k = 32 inside the bucket 17-32; a 30m pick: k = 16
    inside 9-16; a 1h pick: k = 8 inside 5-8; a 4h pick: k = 2, a bucket of its own). The placebo would then leave at
    about 1/16, 1/8 or 1/4 per check inside the bucket and run on, after the clock, for days. That is not F12's timing.
    So for F12 the clock check is taken out of the table: the denominator counts only the checks before the clock check,
    and the numerator only the RULE exits at those checks; every exit at the clock check, whichever components fired
    with F7h, lies outside the table. **The F12 placebo exits with probability 1 at its clock check** and, before it, at
    u < h[a, s, z] as any placebo does. Its holds therefore never exceed F12's and its clock is F12's. (On a 4h pick only
    the stratum at k = 1 has a hazard.) Why this choice and not another is in 16.4.
* **Placebo account**: V's mode (the pick's take-profit kept in (a); in (b) none, except F11.b and F12.b, which keep
  the strategy's own target), V's check schedule (q15 included), and the same hard stop, sizing, period-end close and free
  fill minute. Instead of V's rule, at each check it computes its own position's stratum and exits when u < h[a, s, z]
  (RAND; for F12 also with probability 1 at its clock check, above). The draw u depends only on (V, period, seed, coin,
  check close time), not on the pick, so two picks that
  hold the same coin at the same check close draw the same u (this carries part of the cross-pick correlation that V's
  own exits have; Known limit 9):
  * base = `run._seed("exitflex", "placebo", V, period, s)`, s = 0 .. 199 (0 .. 99 under the rule of 5.3);
  * key = coin index x 2^36 + close ms // 60,000, where the coin index is the position in the coin priority order of
    section 3 (BTC 0, ETH 1, SOL 2, DOGE 3, LTC 4, BCH 5), not alphabetical, and the close is the close time of the
    latest closed chart bar of the check (the 15m bar for q15; for a merged check, the latest of the merged bars), in
    milliseconds;
  * u = (splitmix64(splitmix64(base) XOR key) >> 11) / 2^53, with the standard splitmix64 constants.
* **Placebo pooled mean** for seed s and pool P = the mean over the pool's picks of the placebo's M_p: its monthly log
  growth minus E0's, computed as in section 7.
* **Two steps** (select only). Step 1 runs E0 and every variant on every pick. Step 2 runs the placebo of V in pool P
  only when V is outside F7, F7h and F13 and passes gates 1, 2 and 4 of 8.1 in P. This gives exactly the eligible set that
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
* **Hold time and entries, reported first** for E0 and V, **pooled per pool**, at quarter size (and at live size
  beside). **As built**, the committed `select.json` and `confirm.json` carry these pooled numbers only, in every row:
  no per-pick table of hold, entries, skipped or rejected signals is committed by this file's runner (the extra reads of
  16.7 item 4 may commit select-period split tables under the limits stated there). The per-pick numbers exist only
  in the per-account result files (`$WORK/<pin8>/results/<stage>/`, DeepSeek picks under `ds_private/results/<stage>/`),
  which nobody opens (sections 3 and 14; the modules of the extra reads read the select stage's files as a program, 16.7
  item 4). The one per-pick number in a committed file of this file's runner is M_p of each core pick on a
  choosable core row of `select.json` (field `Mp`, the input of gate 2); DeepSeek rows have none.
  * median and 90th-percentile hold (hours from fill to exit), and the shares of trades held more than 4 h, 8 h and
    18 h, over all closed trades of the pool's accounts together (the json's `hold` holds all five; the Korean tables
    print the median and the three shares);
  * trades entered (status 1) and trades closed; signals skipped while a position was open (status 0) and signals
    rejected (status 2), each summed over the pool's picks;
  * entries made at the open of a rule-exit minute;
  * for the placebo, `select.json` gives (core, choosable rows) the 5th, 50th and 95th percentiles of the pooled
    monthly growth difference and the median number of trades entered over the seeds. The placebo's hold statistics per
    seed stay in its result files.
* **Hold hours by market state at entry** (message 7; descriptive; a column of information, not a gate, not in the
  default of 8.4, not a placebo stratum, not a choice per state):
  * **State.** The label "장세" of `research/fullgrid/regimes.py`, which takes it from
    `paperbot/dash/tools/regime5y.py` (`regimes`, `label_codes`; docs/regime5y.md). **The pinned code is the
    definition**: the label is `regime5y.regimes(high, low, close, tf_min)["code"]` at the signal bar, and the sentences
    below only summarise it. It is computed on the chart of the **traded coin** (the coin of the signal; in a pick name
    such as `core-DOGE-15m-1` the coin is a strategy name, and the pick trades all six coins) at the pick's timeframe,
    at the signal bar whose close is the entry. The module's thresholds are used, none changed: **급변장** when ATR%
    (ATR14 / close, where ATR14 is the module's own `adx_atr`, Wilder smoothing seeded from the first bars, and not
    `fg_indicators.atr`, which gives R) is at or above the 0.80 quantile (pandas rolling quantile, linear) of its own
    trailing window of round(365 x 1440 / tf_min) bars, this bar included, with at least round(180 x 1440 / tf_min)
    valid bars in the window (a bar count, not calendar days: bins missing inside the window shorten it in time);
    otherwise **추세장** when ADX14 >= 25 and |EMA50 slope over 10 bars| >= 0.5 ATR14; otherwise **횡보장** when
    ADX14 < 20; otherwise **보통**. Where an input is missing the label is **모름**, reported as a fifth column: a coin
    with fewer than 180 days of history (SOL until about mid-March 2021 and DOGE until about 6 January 2021, counted
    from the first minutes of section 2; the ATR% history also starts only at the first valid ATR bar). (The docstring
    of `regimes.py` writes the slope without the absolute value; the code and docs/regime5y.md use it, and the code is
    followed.)
  * **No look-ahead.** Every value of `regimes` at bar t uses bars 0..t only. A trade's label is the value at its signal
    bar; the fill is the open of the next minute, so no bar after the signal bar enters the label. The same trade has
    the same label under E0 and every variant. The select report labels select-period trades from the select-cut
    arrays only; the confirm report labels confirm-period trades from the full arrays, with the same code.
  * **Table.** Per pool, for E0 and each variant, at quarter size, over all closed trades of the pool's accounts
    together, per state: the number of trades, the median hold in hours and the shares held over 4 h, 8 h and 18 h.
    A cell with fewer than 100 trades is marked 건수 적음 (the caution of `regimes.py`) and is not hidden. A state can
    have few or no entered trades (`regimes.py` notes that 급변장 had none in the full grid because the engine refuses an
    entry whose stop is not inside the liquidation price); the count is shown and an empty cell stays empty.
  * No growth or money figure is in this table, for either pool, so DeepSeek rows are allowed in it (counts and hold
    hours only). It sits in a second table after the main one (8.2) and has no weight in any gate. It answers the
    owners' remark that the hold they want "depends on the market"; it cannot create a rule per market state (section
    12): a rule for one state is a new pre-registration.
  * Where it is produced is in section 13 (code) and tested by T8.
* Reported beside it, deciding nothing, **pooled per pool** (as built, see above), for E0 and V:
  * the same metric at live size, and busts at live size (core, choosable rows: the `live` field; for every row the
    live-size hold, entries, skipped and rejected counts);
  * trades changed: V's trades with no E0 trade of the same (coin, side, fill minute, exit minute, exit reason),
    count and share;
  * exit reasons (TP, SL, LOCK, RULE, RAND, LIQ, END; LOCK is a stop hit after the stepped lock of F13 raised it); for F12 also, per component, the exits where it fired and where it
    fired alone (`tr_comp`, 5.2), in total and split by the pick's timeframe;
  * win share (closed trades with a wallet change > 0);
  * the maximum drawdown of the wallet at closes, busts and the final wallet multiple: per account, in the result
    files. The committed files carry the median over the pool's picks: `select.json` for E0 only (core:
    `max_dd_median`, `final_multiple_median`), `confirm.json` for each core pair (same fields); a variant's drawdown and
    final multiple in the select period are in no committed file. For DeepSeek they are in the private owner reports
    (section 3);
  * the minutes where the stop (a lock raised by F13 is the stop) and the take-profit were both touched (decided stop-first), per arm;
  * the realised hazard table h (summed over the pool's picks);
  * the placebo's 5th, 50th and 95th percentiles (above).
* **What a round trip costs** (the engine's own figures, `config.v3_settings`; written here so that the reports can
  print them next to hold times):
  * at market on both sides (exits RULE, RAND, SL, LOCK, END): taker 0.05% plus slippage 0.02% on each side, 0.14% of the
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
  DeepSeek rows in committed files and committed reports carry hold times (overall and by market state), counts, win
  shares, exit reasons (LIQ included; for F12 the component counts of 5.2) and labels. The owners' private report
  (section 3) is the one place where the DeepSeek M_P, its live-size version, wallet multiples, drawdowns and busts are
  shown, and only to the owners.

## 8. Select step (select period only): eligibility, the report, the owners' choice

### 8.1 Eligible variants, per pool

A variant V is **eligible in pool P** when all of these hold on the pool's picks:
1. M_P(V) > 0.
2. M_p(V) > 0 on at least 60% of the pool's picks: 14 of the 23 core picks, 9 of the 15 DeepSeek picks. A pick with no
   signal, or where V changed no trade, has M_p = 0 and does not count.
3. Except F7, F7h and F13 (they have no placebo, section 6): M_P(V) is above the 95th percentile (numpy's percentile, linear) of V's placebo pooled means in
   P.
4. The trades entered at quarter size, summed over the pool's picks, are >= E0's.

The gates are filters: only eligible variants can be shown as choosable, chosen or confirmed. They are not relaxed after
any number is seen. F12.a and F12.b are judged on the same four gates as every other variant; F12 has a placebo (6),
with F12's own 8-hour clock, so gate 3 applies to it. F13.a and F13.b are judged on gates 1, 2 and 4; gate 3 does not apply to
them (no placebo), exactly as for F7 and F7h, and the report marks it "해당 없음".

### 8.2 The select report

The runner writes `out/select.json` and the Korean report `out/SELECT_KO.md`. For each pool (core and DeepSeek, each
with its own table), hold hours and entries come before any growth figure, in the table and in the report's text.
**As built, every row of `select.json` and every row of the table is a pool row**: hold hours, entries, skipped and
rejected signals, win share, exit reasons and the other counts are summed over the pool's picks. There is no per-pick
table of hold, entries or counts in `select.json` or `SELECT_KO.md`; those numbers stay in the per-account result
files, which nobody opens (section 7, which also names the one per-pick number, M_p on choosable core rows). The report
shows:
* first, E0's row: median hold hours, the shares of trades held over 4 h, 8 h and 18 h, trades entered, signals
  skipped while holding, win share;
* then **every one of the 88 variants**: the choosable (eligible) ones first, then the others marked "선택 불가", each
  part in canonical order, with, in this column order (growth is column 6, after hold hours and entries):
  1. id, plain Korean name, group, parameter count;
  2. **hold**: median hold in hours and the shares of trades held over 4 h, 8 h and 18 h (quarter size, over all closed
     trades of the pool's accounts together, as in section 7);
  3. **entries**: trades entered against E0's (both counts and the change in percent), and signals skipped while
     holding, E0's skipped count beside it;
  4. what it can cut a loss on before the hard stop: its category L0-L3 (5.3), and whether it is in the default set D;
  5. a pass or fail mark for each gate of 8.1 (gate 3: "안 돌림" when the pair failed gate 1, 2 or 4 and so never
     reached step 2; "해당 없음" for F7, F7h and F13), and the label "선택 가능" or "선택 불가";
  6. core, choosable rows only: M_P(V), the pooled quarter-size monthly log growth difference against E0, also written
     as a percent per month (100 x (e^M - 1)); and, reported only, the same at live size. No growth figure on a core
     row marked "선택 불가". DeepSeek rows: no money figure of any kind (D11);
  7. win share;
  8. choosable rows: the claim it may carry (8.5); "= F3.a" on F11.a and "= F3.b" on F11.b for the F7_RF_ONLY picks;
     and a mark on the variants the default of 8.4 would take in that pool (the default ranks by hold hours, so the
     mark carries no money figure in either pool);
* **a second table per pool, directly after the first**, with no growth column: hold hours by market state at entry
  (section 7) for E0 and each of the 88 variants, in the same order, per state (추세장, 횡보장, 급변장, 보통, 모름) the
  number of trades, the median hold in hours and the shares held over 4 h, 8 h and 18 h; cells under 100 trades marked
  건수 적음. Select-period trades only. It is information (section 7), and the report says so in one line;
* for F12 rows, the exits by component (5.2) as counts, in total and split by the pick's timeframe;
* for F13 rows, nothing extra: the row is read like any other. It shows the plain Korean name "규칙봇 계단 잠금(12%→10%,
  17%→15%, 22%→20%...)", group P, 0 parameters, category L0, "in the default set D: yes", gate 3 "해당 없음", the claim of 8.5
  on a choosable row. Its exit reasons in `select.json` (section 7) show LOCK beside TP and SL (mode b has no TP);
* the number of variants failing the gates per pool, counted in sequence: gate 1; gate 2 among those passing 1; gate
  4 among those passing 1 and 2; gate 3 among those that reached step 2. No figure of a failing variant beyond the
  columns above and the second table (which splits column 2 by market state).
* for the core pool, the Q-A rows of section 7 (DeepSeek Q-A stays private).

DeepSeek tables in `SELECT_KO.md` carry no money (columns 1-5, 7, 8, the second table and the counts). The owners'
request to see the DeepSeek money is met by the private owner report of section 3, which is written with the select
run, whose sha256 is in `select.json`, and which the main session shows in the chat with the owners, in the same turn
as or before it sends `SELECT_KO.md` and never over a logged channel (section 3, 8.7).

No confirm-period figure exists when the report is written. The main session sends the report to the owners and asks
for one answer per pool: up to two choosable ids (the id column of the table) from different groups, or "없음"
(none). It does not recommend a variant; it explains the columns and the default rule when asked. The report's last
line asks the owners to name variants by id and not by any figure (section 3).

### 8.3 The owners' choice

* Per pool, the owners choose **at most 2 choosable variants, from different groups**, or "없음". Each chosen variant is
  one global rule for all picks of that pool: no per-pick, per-coin, per-timeframe or per-side choice. Variants of
  categories L2 and L3 (5.3) can be chosen; the report shows that they cut losses on more than a deep structure break.
* They may choose the same variant for both pools, only if it is choosable in both. It then counts as one choice in
  each pool.
* **Deadline.** A pool's deadline is 48 h after the sending time of `SELECT_KO.md` (8.7); the private DeepSeek report
  was shown at or before that time (section 3). When a message is unclear, the main session may ask back, quoting the
  options by id and quoting no DeepSeek figure (section 3); each question it sends moves the deadline of the pools it
  concerns to at least 24 h after that question was sent. An answer counts only when received before its pool's
  deadline.
* **No answer.** A pool with no answer (ids or "없음") before its deadline takes the default of 8.4. An explicit "없음"
  stays none; the default never fills it. Once `choice.json` is hashed, a later message is quoted in the confirm report
  and changes nothing.
* **Freeze.** From the sending of `SELECT_KO.md` until `choice.json` is hashed and pushed, no 2024-2026 result of any
  exit is sent to the owners or opened by the main session: no hunt test-period read (PREREG_HUNT_WIDE, round 2), no
  ledger print, no track-2 result, no full-grid extract and no other file that shows 2024-2026 trades or accounts by
  exit. Questions about such material are answered after the hash. A breach is written into `DEVIATIONS.md` with what
  was sent or opened, and the confirm report names it in its headline. The freeze covers the hunt's test-period
  results (round 1 and round 2) and track 2 in full. The main session therefore times the select report around the
  hunt: it sends the report at a time when no hunt, track-2 or ledger test-period result is due or needed before the
  hash, or it leaves those outputs unread until the hash; it does not stop the hunt's run. The plan is written into
  `sent.json` (field `freeze_note`). The private DeepSeek owner report holds select-period money only, so it is not
  2024-2026 material.
* **`out/choice.json`** holds: the report's sending time (UTC and KST, equal to `sent.json`); every owner message about
  the choice, verbatim (Korean) with its time; every question the main session sent, verbatim with its time; per pool
  the answer (ids or "없음"), the deadline that applied and whether the default was used; and the list of 2024-2026
  material the owners had received before the report was sent (at least the full grid's per-trade results of the 84
  exits in `ANALYSIS_KO.md`, `STRATEGIES_KO.md` and `STRATEGY_EVAL_KO.md`, and any hunt or ledger result sent to
  them). "Verbatim" has one exception: every DeepSeek money figure in a message or question is replaced by the marker
  `[딥시크 금액 삭제]` before it is written (section 3; the questions quote none, and the unredacted text's sha256 is in
  `ds_private/owner_messages.json`). Audit A8 runs on the file before it is committed (14).
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
  which cut a loss before the hard stop only on a structure break at a loss deeper than 0.5R, or not at all before a
  gain). The set has 37 variants: the 35 of F5, F6.d0.5, F8, F9, F9 q15 and F10, and the 2 of F13, which is L0 (the lock
  cuts nothing before a gain, 5.3). Variants of L2 and L3 are never taken by default; F12 (L3, group A) is never taken by
  default. The default uses hold hours and no money figure, DeepSeek included, and the owners' view of the private report
  (section 3) does not change it.
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
* outside F7, F7h and F13: "beats E0 and beats a random exit with its timing profile" (for F11: "the strategy's own exit
  beats E0 and a random exit with its timing profile"; for F12: "this fixed combination of the nine exits, of which at
  most seven can end a trade on a 1h or 4h pick and at most eight on a 15m or 30m pick (F6 never moves the exit, F10
  acts only on 15m and 30m picks), beats E0 and a random exit with the same 8-hour clock and timing profile". No claim
  that stacking beats a single rule, that all nine act on every pick, or that F12 is the best exit);
* F7 and F7h: "beats E0 by holding less; no claim about reading the market".
* F13: "closes by the engine's stepped profit lock: after +12% net ROE it never gives back below +10%, except by the slippage of a
  stop and at a gapped open, which can lie anywhere; it reads no structure and makes no claim beyond that" (the clause after the
  comma is the limit of 5.2, "Category": the stop of the next minute fills a little lower, and the minute that arms the lock is
  not protected, because the new stop applies from the next minute). There is no random-exit claim, because F13 has no placebo gate (section 6): a PASS shows that
  F13 beat E0's growth over the 33 months (the Holm test of 9) and kept the entries, and the claim says no more. The Korean
  report prints the same sentence in Korean (12% -> 10%, 17% -> 15%, 22% -> 20% ...).

### 8.6 No eligible variant

With no choosable variant in a pool the result for that pool is "none". The owners still get the full table of 8.2
(hold hours, entries and gate marks of all 88 variants), so they can see where each variant fell short and decide with
the main session (promise (f)). With none in both pools, or "없음" or no variant in either, the study ends: nothing
runs on the confirm period and nothing enters the ledger. The owners are told plainly. The criteria are not relaxed
and no variant is re-tuned on this result. A new idea is a new pre-registration with its own select step.

### 8.7 Files

The growth figures of the choosable core rows and every pooled label and count of both pools (hold hours by market
state included) go to `out/select.json`. The growth figures of the core rows marked "선택 불가" are not in it: the
runner writes them to `$WORK/<pin8>/results/select/core_not_choosable.json` (with `SELECT_TABLE.csv` and `run_info.json`,
the commit and versions of the run, beside it), outside the repository and not opened. The DeepSeek money figures go
to `$WORK/<pin8>/ds_private/select_ds.json`, whose sha256 is written into `select.json`. The private DeepSeek owner
report (section 3) is written to `$WORK/<pin8>/ds_private/owner_report_select.md` in the same run, and its sha256 is
written into `select.json` (`ds_owner_report_sha256`); the file itself is never committed. The sha256 of `timing.json`
was appended to `PREREG_EXITFLEX.sha256` before the select run (the select stage refuses without it, 13); the sha256 of
`select.json` and of `SELECT_KO.md` are appended, committed and pushed before the report goes to the owners, so the
menu they see is the one that was hashed. Before showing the private report, the main session checks that its
sha256 equals the committed one. It shows the private report in the chat with the owners (section 3), in the same turn
as or before it sends `SELECT_KO.md` by its channel, and with it the private extra report (section 3) and the extra reads
and twins of 16.7 item 4; the 48 h clock of 8.3 starts at that sending. Right after sending,
and before reading any answer, the main session writes the sending time (UTC and KST), the channel, the time at which
the private report was shown (`ds_report_shown_utc`, `ds_report_shown_kst`; the place is the chat and nothing else),
the freeze note of 8.3, and for 16.7 item 4 `extra_note` (the commits O7 and O8 of section 17, each with its hash and UTC
time, and the UTC time and HEAD of the select stage's `[pin ok]` line), `extra_shown_utc` (when the extra reads and twins
were sent and the private extra report shown) and `ds_owner_report_extra_sha256` (the sha256 of the private extra
report, section 3) to `out/sent.json`, runs audit A8 on it, appends its sha256, commits and pushes it. A select
rerun is possible only under section 14; it writes `select_r2.json`, `SELECT_KO_r2.md` and `sent_r2.json` to `out/`
and, privately, `select_ds_r2.json` and `owner_report_select_r2.md`, with its own `ds_owner_report_sha256` field in
`select_r2.json`, under the same rules.

## 9. Confirm rule (2024-01-01 .. 2026-10-01, once)

* The confirm run covers E0 and each chosen V on its pool's picks, at quarter size (deciding) and live size (reported).
  For a chosen V outside F7, F7h and F13 it also runs V's placebo in that pool: 200 seeds, with the hazard table that V
  realised in this period on each pick.
* **Tests**: one per chosen (V, pool) pair, at most 4. Each is a one-sided circular moving-block bootstrap of the 33
  monthly D_m^P(V), blocks of 3 consecutive calendar months, 2,000 resamples, seed
  `run._seed("exitflex", "confirm", V, pool)`. p = (1 + resamples with mean <= 0) / 2,001.
* **Holm at 0.05 over all chosen (V, pool) pairs**: with k pairs, sort the p values ascending; the i-th smallest is
  significant when it and every smaller one satisfy p_(j) < 0.05 / (k - j + 1). With one pair, p < 0.05.
  DeepSeek p values enter Holm from `ds_private/` and are not written to any committed file (D11); a core pair's Holm
  label can depend on how DeepSeek p values rank, which is a label, not a figure.
* Reported beside it, deciding nothing: the iid bootstrap p of the same series, and a 95% percentile interval for
  M_P(V) from the block bootstrap (core only; for DeepSeek neither p, the interval nor M is shown in any committed
  file, D11; M and the interval, not p, are in the private owner report of section 3).
* **PASS** for (V, P) needs all three:
  1. (V, P) is Holm-significant.
  2. Except F7, F7h and F13: M_P(V) is above the 95th percentile of V's 200 confirm-period placebo pooled means in P.
  3. The trades entered over the pool's picks at quarter size are >= E0's.
* A PASS carries the claim of 8.5 and nothing more.
* A FAIL means this test did not show a gain. It does not show that there is none. The Korean report says so and, for
  core, gives the 95% interval.
* **The confirm report** (`out/REPORT_KO.md`) leads, per pool, with hold hours (median, shares over 4 h, 8 h, 18 h)
  and entries against E0, then PASS or FAIL, then for core M_P(V), p and the interval. DeepSeek rows: PASS or FAIL,
  the Holm and ledger labels, hold hours, entries, trade counts, win share. For each chosen pair it says whether the
  owners chose it or the default did, and whether it is also what the default would have taken (8.4); and it lists
  any freeze breach (8.3) and any owner message received after `choice.json` was hashed (with every DeepSeek money
  figure replaced by the marker of section 3). After the PASS or FAIL block it
  gives, per pool, the hold hours by market state at entry (section 7) for E0 and each chosen V: confirm-period trades,
  labelled from the full arrays with the same code, information only and no part of PASS or FAIL. For a chosen F12 it
  gives the exits by component (5.2), in total and split by the pick's timeframe.
* Q-A on confirm, descriptive and outside the ledger: for each chosen V outside F7, F7h and F13, the placebo's median pooled
  mean against E0 (core), with the block-bootstrap p of the placebo's seed-mean D_m.
* It runs once. Bugs are handled by section 14. No other cut (a pick, a coin, a side, a year, a size, a market state)
  is a pass.
* Files: `out/confirm.json` (core figures and p values; DeepSeek labels, counts, win shares and hold times, also by
  market state), `$WORK/<pin8>/ds_private/confirm_ds.json` (DeepSeek money figures and p values; its sha256 in
  `confirm.json`), and the private DeepSeek owner report `$WORK/<pin8>/ds_private/owner_report_confirm.md` (section 3;
  its sha256 in `confirm.json` as `ds_owner_report_sha256`; never committed; the main session shows it to the owners in
  the chat, section 3). A confirm rerun (section 14) writes `confirm_r2.json` and `REPORT_KO_r2.md` to `out/` and,
  privately, `confirm_ds_r2.json` and `owner_report_confirm_r2.md`, with its own `ds_owner_report_sha256` field. Audit
  A8 runs on `REPORT_KO.md` (and `REPORT_KO_r2.md`) and on the ledger print after they are written and before they are
  committed (14).

## 10. Ledger

* Each chosen (V, pool) pair is one test-period hypothesis in the program-wide ledger
  (`research/hunt/PREREG_HUNT_WIDE.md` R13 and section 14: a global BH at q = 0.10 and Holm at 0.05 over every
  test-period hypothesis of the program, printed as `research/hunt_r2/PREREG_HUNT_R2.md` section 8 defines). It enters
  with its block-bootstrap p from section 9. A DeepSeek pair's p is read by the ledger print from
  `ds_private/confirm_ds.json` and enters the BH and Holm computations; the print shows for that pair its BH and Holm
  labels only, never its p (D11). If the ledger print cannot omit a p, the DeepSeek pair's row is printed to the
  private folder and the committed print carries the labels only. The ledger keeps DeepSeek as labels only, and the
  private owner reports of section 3 are not an input to it.
* From the hash of this file until `choice.json` is hashed, the ledger's print counts this study at its maximum, 4
  hypotheses at p = 1. After the choice it counts the number of chosen pairs; with none chosen, it counts none. A
  confirm rerun under section 14 adds its p values as further looks.
* The Korean report's headline shows, next to PASS or FAIL, the ledger status of each chosen pair (BH at q = 0.10 over
  the program). The ledger print changes no verdict of this study. The verdict carries the line "this confirm uses the
  same 33 months as the full grid, the hunt (v1, wide, round 2) and track 2".

## 11. After the confirm: the league restart

### 11.1 What happens on each outcome

* **PASS in at least one pool.** The Korean report goes to the owners. With their OK (their message verbatim except for
  the redaction of section 3, with its time, written into `research/fullgrid/DEVIATIONS.md` before the restart, after
  audit A8 has run on the entry), the current league (the WATCH_PREREG run,
  started 2026-10-11) is stopped and a fresh league starts at the new install time (11.2-11.4). Without their OK
  nothing changes. **As built, the switch is the field `enabled` of the rules file** `candleague/data/rules.json`
  (another path in `CANDLEAGUE_RULES`): `"enabled": true` is the owners' OK, and a file with `"enabled": false` (or no
  file) makes the league create no rule account and run its candidate accounts as before, so committing the file
  starts nothing. The file names, per pool, the passing rule or null (`"pools": {"core": "F9.a", "ds": null}`), may
  list the picks, and holds the field `no_entry_from_ms` per pool (11.4 item 9). The file does not exist yet.
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
  15 x 5 + 23 x 3 = 144 when only DeepSeek passes. These counts were recomputed from the code (`rulex.accounts` on
  the 38 picks of `candidates.json`, with a new exit in both pools, in core only and in DeepSeek only: 190, 160, 144).
  With a new exit in neither pool (the owners restart the league with the current exits only, 11.1) the same function
  gives 38 x 3 = 114 accounts. The accounts of both pools are in one league, one database, no side league.
* Quarter size is every margin fraction x 1/4 with leverages kept, as the current `quarter` accounts and section 4.
* **The coin flip `-nflip`** takes the pick's signal times, its side from `league.flip_side(account id, signal close)`,
  and the pool's new exit with the same exit kinds as `-nq`: the same rule, the same mode, the same kind of
  take-profit. It runs at quarter size because C1 and C2 compare it with `-nq`. Under F12 the flip runs the same nine
  components at the same values; its F3 is the pick's signal of the side opposite to the flip's side, and its F11 part
  follows the F11 rules below. Under F13 it runs the same exit as `-nq` (the pick's take-profit and the stepped lock, or the lock
  alone), on the plain engine of that exit (with the C1 gate of 11.4 item 9), with the flip's side, the pick's stop distance and the engine's lock.
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
  for this one restart: the old start file moves with the copy, so it cannot be picked up. **As built, no code switch
  does this**: `league_start` keeps a start that the database or its start file records, so the restart gives the
  engine a database path that records none (the old `league.db` and its start file copied and moved away, or
  `CANDLEAGUE_DB` pointing to a new file), and the guard below refuses a start that is not the install time. This is
  recorded as a deviation in `research/fullgrid/DEVIATIONS.md` at the restart, with the time, the commit and the
  owners' OK. The copy of the old database made by `python -m candleague backup` is named
  `<stem>_from_<MMDD>_<UTC date>.db` (MMDD: its start), not with the name above; a copy made by hand may use either.
* `runner.league_start` uses an explicit `CANDLEAGUE_START` before "now" for a fresh database. The restart steps
  therefore unset `CANDLEAGUE_START` in the shell and remove it from the service's environment file before the first
  pass. **As built, the start is checked before the first pass, not after it**: the restart script writes down the
  install time and gives it to the engine as `CANDLEAGUE_EXPECT_START` (or `--expect-start`, with its time zone or in
  epoch ms). `League.__init__` compares the league's start (the recorded one, or the one it is about to record) with
  that time floored to 5 minutes (`runner.check_expected_start`) before it copies, deletes or writes anything, and a
  mismatch raises `StartMismatch`: the engine exits with the reason in Korean, before any trade is shown. The
  `backup` command (the install script's step) runs the same check when it is given the time; the install script does
  not pass it yet (restart to-do, 11.4). Without `CANDLEAGUE_EXPECT_START` a fresh database starts at "now" and says so
  in the log with a warning.
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

**As built (2026-10-12, before the pin).** The league code is in the repository and is not pinned here. It is
`candleague/rulex.py` (`parse_rule`, `load_config`, `accounts`, `load_accounts`, `RuleMixin`, `RuleEngine`,
`RuleLadderEngine`, `make_engine`, `chunk_rule`, `replay_day`, `audit_restored`, `register_native`,
`load_native_provider`, `forward_check`, `public_view`, `checks_main`), `candleague/runner.py` (`league_accounts`,
`check_expected_start`, the tables `acct_day` and `acct_mark`, `hold_stats`), `candleague/exits.py` (the 84 exit rules, unchanged,
and `lock_exit`, which builds the F13 exit from a pick's own exit name) and the tests `tests/test_candleague_rulex.py`,
`tests/test_candleague_exits.py` and `tests/test_exitflex_league_parity.py`; the study side is
`research/exitflex/kernel_x.py`. The first draft's names are gone. There is **no side league**: no `rule_league.db`
(`rulex.DB_NAME` stays in the module as history and no file of that name is created), no `-f`, `-f-live`, `-f-flip`,
`-f0`, `-f0-live` accounts and no `runner.make_rule_league`; the draft's `register_f11` is `register_native`. The
restarted league is the league itself: `runner.main` takes the accounts of `rulex.accounts` instead of the candidate
accounts when the rules file is enabled (11.1), in the database given by `--db`. The 14 items below are the contract.
The table after them gives the status of each item as built (read from the code and the tests, not run on real data),
and the list after the table is what is still to do at the restart. The parity test of item 13 must pass before the
league starts.

1. **Database and accounts.** A fresh database and start (11.3) for the restarted league itself, not a side
   `rule_league.db`. The accounts and ids of 11.2 (`-n`, `-nq`, `-e`, `-eq`, `-nflip`, `-eflip`) replace the first
   draft's `-f` family. `runner.fingerprint` covers every account of the new database.
2. **Both pools.** The first draft's `pick_list` refused every DeepSeek pick ("DeepSeek never gets rule accounts,
   D11"); that refusal is removed. D11 governs what is shown, not what runs: DeepSeek rule accounts run like the
   current league's DeepSeek accounts, and their money on the league's own screens follows the league's dashboard
   setting (section 3); this study's committed notes and reports carry none.
3. **Per-close rule inputs** (`chunk_rule`): for every account whose exit has a rule (`-n`, `-nq`, `-nflip`), every
   chart close of every coin: close, ATR14, EMA(n), swing confirmations, both raw signal flags, the strategy's own
   component booleans of both sides (Appendix A), plus the 15m closes for q15. `league.chunk_signals` today sends only
   bars that carry a signal.
4. **F11 as Appendix A defines it**, not the first draft's plug-in. The first draft fired F11 on any true per-bar
   `long_exit` / `short_exit` flag, had no arming, no per-position level test, and a target only when the rule carried
   `use_target`. Run as it was, it would have fired at the first check on an N03_ADX_GC long entered after an EMA
   whipsaw (rule C3 forbids that), and it could not express the level tests of N13_3OUTSIDE, N19_FIB_CHOP and five
   DeepSeek strategies. Required: each component carries its kind (state or event) with C3 arming from i0;
   per-position levels and targets, fixed at i0, travel in the signal's meta (`meta['native_inv']`,
   `meta['native_tgt']`) and the level is tested at every close; F11.a and F11.b are the mode (5.2, rule C8), not a
   `use_target` flag; flipped positions follow 11.2; the arrays come from `research/exitflex/native.py` and
   `native_ds.py`, the same code the study runs.
5. **Guard**: the league asserts that no offered bar carries both flags (section 3).
6. **Step order** stays in `RuleMixin.step` (`candleague/rulex.py`): funding; then, if a rule exit is due at this
   minute and the open gaps past neither liquidation, the stop nor the take-profit, close as RULE; then entries
   (`_handle_entries`); then `_handle_exit`. A gapped open leaves the exit to `_handle_exit`, so entries at that minute
   stay blocked, as in `kernel_x`.
7. **Rule state** (F1 reference, F2 arm, F5, F8 and F9 arms, F7 and F7h deadlines, F11 component arms and fixed
   levels, X and T_X) is kept in the position's signal meta (`meta['rx']`). `engine_state` and `restore_engine` save
   and restore it, and `audit_restored` checks it against a recomputation from the bars. If F12 is the pool's new exit,
   the state of all nine of its components (items 3 and 7 together) is kept, and the engine records every component
   that fired (`tr_comp`, 5.2) next to the RULE reason.
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
    the same 1m bars, for every pick of both pools and every account kind of 11.2 (`-nflip` under F11.a, F11.b, F12.a
    and F12.b included), over at least 60 days of archive data before 2026-10-01. Trade for trade: fill minute, exit minute,
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

**Status of the 14 items as built** (2026-10-12; read from the code and its tests, nothing run on real data):

| item | status |
|---|---|
| 1 database and accounts | built. `rulex.accounts` makes `-n`, `-nq`, `-e`, `-eq`, `-nflip` (`-e`, `-eq`, `-eflip` in a pool without a new exit); `runner.fingerprint` covers each account, its rule, `RULEX_VERSION`, for F11 and F12 the hash of `native.py` and `native_ds.py`, and `no_entry_from_ms`; the start is the install time (11.3) |
| 2 both pools | built. `pick_list` has no DeepSeek refusal |
| 3 per-close rule inputs | built. `chunk_rule` hands every rule account one `RuleClose` per chart close of every coin (15m closes for q15) |
| 4 F11 as Appendix A | built. Component kinds, C3 arming, levels and targets in `meta['native_inv']` and `meta['native_tgt']`, flips mirrored (`flip_levels`); the arrays come from `native.py` and `native_ds.py` through `load_native_provider` |
| 5 guard | built. `chunk_rule` stops with `BothFlags` when a bar carries both flags |
| 6 step order | built in `RuleMixin.step` |
| 7 rule state | built. `meta['rx']` is saved and restored with the engine state and recomputed by `audit_restored`; F12 keeps all nine components and `rx['comp']`. F13 keeps no rule state: its stop and `lock_roe` are part of the engine state, and `audit_restored` skips it |
| 8 native target | built. `tp_price` is set only beyond `entry_price`, without the lock |
| 9 no new entry from a time | built. The field `no_entry_from_ms` per pool of the rules file goes onto the pool's `-n`, `-nq` and `-nflip` accounts and into the fingerprint. The C1 command **prints** the value (11.5) and does not edit the rules file: it is copied into `rules.json` by hand (restart to-do), and the changed fingerprint starts the league over from the same recorded start, with a copy of the old record first |
| 10 counters | built. Table `acct_day`, written in the chunk's commit |
| 11 daily marks | built. Table `acct_mark`, written at every 00:00 UTC in the same commit |
| 12 snapshot | built. Per account `hold_stats` (count, median hold, shares over 4 h, 8 h and 18 h) over every closed trade since the start, and the `acct_day` counts; the checks do not use `LAST_TRADES` |
| 13 end-to-end parity | built on **synthetic data only**: `tests/test_exitflex_league_parity.py` (six coins, 62 days of 1m bars of which the first 52 are warm-up and the last 10 judged; missing minutes, halts, gaps, a restart in the middle of open positions; F1-F10 with F7h in both modes and q15, F11 and F12 through a synthetic native provider, coin-flip accounts, negative controls; F13.a and F13.b at both sizes and as coin flips, with restarts in the middle of positions whose lock is raised and a negative control for a restore that forgets the lock). **Open**: the run over at least 60 days of archive data before 2026-10-01 with the real arrays of `native.py` and `native_ds.py`, and the window-length check of the sub-bullets above |
| 14 check data | built. `forward_check` reads `trades`, `acct_day` and `acct_mark`; `public_view` keeps DeepSeek to labels, counts, win shares and hold hours; the command is `python -m candleague.rulex checks` with `c1`, `c2` or `repeat` (11.5) |

**F13 (16.6) in the league.** F13 adds no account and changes no id or count: `-n`, `-nq` and `-nflip` run `candleague.exits.lock_exit` of the
pick's own exit (`rulex.exit_name`) on the plain engine of that exit, built by `rulex.make_engine` as `LockEngine` / `LockLadderEngine`
(the `RuleMixin` gate and no rule, so that `no_entry_from_ms` of 11.4 item 9 stops their new entries like every other account of the new exit;
seventh pass); `rulex.chunk_rule` hands them signals with the pick's stop distance and no chart record; the twins are untouched; the fingerprint carries the rule and the lock's numbers
(`rulex.code_version`). The parity test of item 13 covers F13 (above).

**Restart to-do.** All of this is done at restart time, after the owners' OK. None of it is pinned here, and none of it
changes a rule of this file.

* The owners' OK, verbatim except the redaction of section 3, and the restart's deviation entry go into
  `research/fullgrid/DEVIATIONS.md` (11.1, 11.3), with audit A8 run on the entry first.
* **Rules file.** Write `candleague/data/rules.json` with the passing rule per pool (null for a pool with no PASS) and
  `"enabled": true`, and commit it. The install script refuses uncommitted changes in the league's paths.
* **Pin file.** `PREREG_EXITFLEX.sha256` lists none of the league side (`candleague/rulex.py`, `runner.py`,
  `rules.json`, the parity test). At the restart the main session records their sha256 and the commit in the deviation
  entry, and the parity test is run on exactly those files.
* **Old record.** Stop the engine; copy the old database and its start file next to them and move the originals out of
  the way, or point `CANDLEAGUE_DB` to a new file (11.3). `python -m candleague backup` makes the database copy when
  the code would start the league over (its fingerprint differs from the database's); a copy by hand is as good.
* **Environment file** (`/etc/candleague/candleague.env`, read by `candleague-live.service`): remove `CANDLEAGUE_START`;
  set `CANDLEAGUE_EXPECT_START` to the install time the restart script wrote down; set `CANDLEAGUE_RULES` only when the
  rules file is not at its default path; leave `CANDLEAGUE_DS_MONEY` as it is (section 3).
* **Install script** (`deploy/candleague/install_candleague.sh`). Its `CODE_PATHS` lists neither
  `research/exitflex/native.py` and `native_ds.py`, which `rulex.load_native_provider` imports when a pool's new exit is
  F11 or F12, nor `research/fullgrid/run.py`, which both modules import when they run (`fg()`), nor what `run.py`
  itself imports. Add the paths the league server needs and run the parity test with them. Its `backup` step runs under
  `env -i` and passes only `CANDLEAGUE_DB`, `CANDLEAGUE_CANDIDATES` and `CANDLEAGUE_START`: pass
  `CANDLEAGUE_EXPECT_START` (and `CANDLEAGUE_RULES` when it is not the default path) so that the step also checks the
  start (11.3).
* **Unit file** (`deploy/candleague/candleague-live.service`). The settings above come from its environment file, so it
  needs no new line for them. Check its caps (`CPUQuota=30%`, `MemoryMax=1300M`) against the account count of 11.2 (up
  to 190) in the rehearsal, and keep `ReadWritePaths` covering the new database path.
* **Parity test on archive data** (item 13, the open part).
* **After C1** (11.5): copy the printed `no_entry_from_ms` into `rules.json` for each stopped pool, commit it, and let
  the engine start over from the recorded start (the old record is copied first). C2 and the repeat are run from the
  same command with `--skip` for a pool already shown ahead.

### 11.5 Forward checks (pre-registered here)

* Days count from the restart's install time. All accounts start together, so every comparison is over identical days.
* **Check times**: C1 at 00:00 UTC of the install's UTC date + 30 days; C2 at + 61 days; the repeat at + 92 days.
* **Wallet at a time T**: W_T is the daily mark of 11.4 item 11 at T: the realised wallet plus, for a position open at
  T, its mark value net of the costs of a market exit. Marking matters because E0 holds longer and so is more often
  caught open at a check. The realised-only wallet is reported beside.
* For an account, G = ln(W_T / 5,000) / months, months = days / (365.25 / 12). A pool's G for a role (`-nq`, `-eq`,
  `-nflip`, ...) is the mean of G over the pool's picks: the **pooled monthly log growth**.
* **C1** (install + 30 days). In each pool where a new exit runs: if G(`-nq`) < G(`-eq`) and G(`-nq`) < G(`-nflip`),
  the new exit **stops** in that pool: the committed C1 script gives `no_entry_from_ms` = the C1 time for that pool's
  `-n`, `-nq` and `-nflip` accounts (11.4 item 9; as built it prints the value and the main session copies it into the
  rules file); open positions close by their own rules; the record is kept. The E0
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
* **Weekly**: the Korean note shows these per pool, hold hours and entries first, and the dashboard shows them in its
  own layout. The Korean note's DeepSeek lines carry labels, counts, win shares and hold hours only; the dashboard's
  own DeepSeek money setting is the league's, not this study's (section 3).
* **DeepSeek pool**: C1 and C2 are computed the same way from the server database (11.4 item 14) and shown as labels
  (stop or continue; shown ahead or not), with trade counts, win shares and hold hours only (D11).
* The checks are computed by a script committed before C1, which reads only the league database tables named in 11.4
  (`trades`, `acct_day`, `acct_mark`) and this file's rules (as WATCH_PREREG 5). **As built** the script is
  `python -m candleague.rulex checks c1|c2|repeat --db <league database> --install <install time, with its time zone
  or in epoch ms> [--rules F] [--candidates F] [--private DIR] [--skip core,ds]`. It opens the database read-only and
  prints the Korean text of the check (per pool: the label, then hold hours and entries per role, for core the growth
  figures, then the conditions); for DeepSeek it prints labels, counts, win shares and hold hours only (D11); the full report, DeepSeek money included, is written
  only to `--private`, a folder outside the repository. A pool with a `no_entry_from_ms` in the rules file counts as
  stopped at C1 and has no C2; `--skip` names the pools that were shown ahead at C2 and are not asked again at the
  repeat. The C1 run also prints the `no_entry_from_ms` line for the pools it stops. It edits no file.

### 11.6 Real money

Real money is not decided by this study. That stays the owners' decision under the program's process.

## 12. What is not in scope, and known limits

* **Not in scope**:
  * a "판단" (judgement) exit by a person or an AI;
  * partial exits (the owners asked for 전량, the whole position);
  * combinations of families other than F9 and F12 (F12 is the owners' "all at once", at the one fixed set of values of
    5.2; no other mix, no F12 with other values, no F12 with F8, F9 or the q15 versions); F13 is the lock alone (b) or the lock
    with the pick's own take-profit (a), combined with no rule of any other family, and is not part of F12;
  * q15 versions of F2, F3, F5, F6, F8, F10, F11 and F12: on 1h and 4h picks these react only at the pick's own closes.
    Inside one 4h bar only F1 q15, F4 q15 and F9 q15 can react; on a 4h pick F7h.H4 caps a hold at one bar;
  * a per-strategy choice among families (each strategy's own exit is F11, one global variant);
  * F11 with both the strategy's target and the pick's R take-profit (F11.a uses only the pick's, F11.b only the
    strategy's);
  * moving the hard stop (breakeven or lock), and intrabar moving stops (the trailing stops of the DOGE and S4_BB_BBP
    sources), except F13, the engine's own stepped lock that the owners asked for by name (5.2); no other lock (a start at
    5% or at 20%, other steps or gaps, a breakeven stop) is in the study;
  * changes to entries, numbers, timeframes, leverage or size rules (the default-number and coin-flip twins of 16.7 item 4
    are information, not variants);
  * per-pick, per-coin, per-side or per-regime choices (the hold hours by market state of section 7 are information
    and choose nothing);
  * a fixed percent of price or ROE as a trigger anywhere, except the engine's stepped lock of F13 (section 1);
  * DeepSeek money figures in any committed file or committed report (D11); the owners' private reports of section 3
    are the one exception;
  * the rule bot;
  * the hunt's systems and other coins;
  * rule exits by maker limit orders.
* **Known limits**:
  1. **2024-2026 is not blind.** The 38 picks were chosen after the full grid's 2024-2026 results had been seen
     (WATCH_PREREG 0), and E0 is part of each pick. On the confirm period E0 carries that selection, which tilts the
     confirm against the variants. The main session's statement in section 15 says that it opened no hunt result, which
     would have made F4's confirm not knowingly a second look at chandelier exits on 2024-2026. That no longer holds:
     the dated addendum in section 15 (2026-10-12 ~06:38 UTC, before the hash) says that the round-1 trend-hunt results
     were then opened and that they contain test-period (2024-01..2026-09) outcomes of chandelier-exit trend systems.
     F4's confirm (and the chandelier leg of F12) is therefore knowingly a second look at chandelier exits on
     2024-2026. No hunt number was used for any choice in this study: the variant menu, F4 included, is in git history
     before those results existed, **except F13** (the stepped lock, 16.6): F13 was added after the hunt read (it first
     appears in git at about 07:51 UTC, the hunt results having been opened from about 06:38 UTC), at the owners' request
     (their messages 8 and 9), and its numbers are the rule bot's own ladder, `paperbot/ladder.py`; no hunt number was
     used for it. The owners are told so in the select report (section 17, item 4a). The clean check
     is the league's forward record.
  2. **2021-2023 was used for both, parts of it were looked at, and the owners' choice is not blind to 2024-2026.** E0
     was chosen on 2021-2023 (the plateau rule), which tilts the select step against the variants. The best of 88
     variants on 2021-2023 also looks better there than it is (the winner's curse); the single confirm and Holm address
     that, and Holm counts the pairs chosen, not the menu. The owners choose by hand, and a hand choice can carry what
     its maker knows of 2024-2026, which an automatic rule cannot: the owners have seen the full grid's 2024-2026
     per-trade results of the 84 exits, including short against long take-profits, which says something about hold
     length on the confirm period. So a chosen variant's confirm is not a clean out-of-sample test of the choice. Three
     things limit this: the freeze of 8.3 (no new 2024-2026 exit result reaches the owners or the main session
     between the report and the hash), the list in `choice.json` of the 2024-2026 material the owners already had,
     and the confirm report's line saying whether each chosen pair is also what the hold-ranked default would have
     taken. The league's forward record is the clean check. The main session saw select-period account results of E0
     on the 23 core picks at live size and E0's offered and entered counts at quarter size on core-DOGE-15m-1 (section
     15, 16.7 item 1), not any figure of a variant. The extra reads and twins of 16.7 item 4 show the owners many more
     select-period cuts before they choose; this widens what a hand choice can fit on 2021-2023 and changes no gate or
     test.
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
     For the family F12, z is 1 at nearly every check (F11's z is), so its placebo matches age and profit sign only,
     and only before the clock. F12's clock leg (F7h at 8 hours) fires at one exact age per pick and no F12 position is
     held past it. A placebo matched on age buckets alone would spread those clock exits over the whole bucket that
     holds the clock check and, with an empty table above it, let about a third of its positions run on for days. That
     is the case on 25 of the 38 picks (15m 5, 30m 8, 1h 12; the 4h picks have the clock at k = 2, a bucket of their
     own). Section 6 therefore gives the F12 placebo the same clock and builds its table from the checks before it, so
     on every pick its holds end no later than F12's. What it still lacks is the finer timing of F12's market
     components.
  10. **Each strategy's own exit is a reading.** For N03_ADX_GC, N09_ALLIG_AROON, N10_HA_PSAR, OBV_S, N19_FIB_CHOP and
      the eight DeepSeek strategies no exit by the strategy's author exists in the repository; their exits were derived
      from the entry logic and the pattern (Appendix A). DOGE and S4_BB_BBP use their source's own signal exit, and
      N13_3OUTSIDE its port's opposite signal plus its pattern level. The readings were written from code before any
      number of them was computed. Another reading could do better or worse. FINGRAD's two-close confirmation is not
      used (rule C2). The core drafter listed what it opened and disclosed one grep print (section 15). The DeepSeek
      drafter cited only code but gave no explicit statement that it saw no performance figure: for the eight DeepSeek
      readings, blindness is **not stated**.
  11. F11.a equals F3.a and F11.b equals F3.b on the three F7_RF_ONLY picks. The select report marks both pairs (the
      DeepSeek rows of F11 carry "= F3.a" / "= F3.b"); this file commits no per-pick table (section 7); the extra reads
      of 16.7 item 4 mark both pairs wherever they show one.
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
  15. **Bar-close checks on 4h picks.** Apart from F1 q15, F4 q15, F9 q15 and F13 (the lock is an intrabar stop), no rule
      reacts inside a 4h bar; on the 13 picks on 4h (6 core, 7 DeepSeek), only F7h (at 4, 8 or 16 h) and F12 (through its 8 h
      F7h leg) cap a hold below 2 days; F13 does not cap holds (a trade that never reaches +12% net ROE is held to the hard stop,
      END or, in mode a, the take-profit).
  16. **No giveback without an arm is tested.** Every F5 and F8 cell has an arm of at least 1R (section 1); a giveback
      from any profit (F5 with P = 0) is not in the grid and the study cannot say what it would do. F1 is the only
      structure break with no arm, and F10 the only stall with no R arm. Adding a cell would change the counts and is a
      new pre-registration.
  17. **F12 is one fixed reading of "all at once", and not all nine legs can act on every pick.** Its values are the
      grid middles (the larger value for two-value grids), fixed before any number (5.2). Other values, or another way to
      combine the nine, could do better or worse and are not tested. A pass of F12 shows only that this F12 passed. Its
      F6 leg never moves the exit (5.2), and its F10 leg (12 bars) cannot fire before the 8-hour clock on a 1h pick
      (12 h) or a 4h pick (48 h), that is on 25 of the 38 picks. So on those 25 picks at most seven legs (F1, F2, F3,
      F4, F5, F7h, F11) can end a trade, and on the other 13 (15m and 30m) at most eight. F12 is "all nine at once" in
      its rule, not in what it does on each pick. The legs that can act can fire on an ordinary pullback, so F12 can
      leave early on small wobbles (Q-C).
  18. **The market state is the state at entry.** The market can change during a hold, and a trade is counted in the
      state of its signal bar for its whole hold. The split is descriptive: with five states, 88 variants and two
      pools it contains many cells, some with few trades (marked 건수 적음), and a difference between states can be
      chance. 모름 collects the trades of a coin with less than 180 days of history (SOL until about mid-March 2021,
      DOGE until about 6 January 2021). The split chooses nothing, and "the hold depends on the market" is not tested as
      a claim.
  19. **F13 is the engine's ladder, in net ROE, and not tuned.** (a) Its numbers (a lock arms at +12%, +17%, +22% ... net ROE and
      locks +10%, +15%, +20% ...) are the rule bot's own, `paperbot/ladder.py`, asked for by name; the study tests this one ladder,
      not other starts (5% or 20%), steps or gaps, and a pass does not show that 10% / 5% / 2% is the best ladder. (b) Net ROE
      depends on the leverage, and the quarter-size and the live-size account of one signal can get different leverage tiers (5.2),
      so at one price the two can hold different locks, which is how the live rule bot works; the deciding quarter size is the one
      the league judges. (c) The lock arms on the minute's best price (a high for a long, 1m last prices, not mark prices), so one
      wick of one minute arms it; the new stop applies from the next minute, and the order of high and low inside a minute is
      unknown (the low is taken first): a case where the true order differs is not seen. (d) The lock sits 2% of ROE under the best
      price, a tight margin for a 1m world: a trade can leave on noise (which is also what the rule bot does). (e) F13.b has no cap
      on holds and no take-profit, so a trade that never reaches +12% can be held for days; the hold columns show it. (f) F13.a on
      a trade whose own take-profit lies below +12% net ROE (a take-profit of a few R when the ATR is very small) hits the
      take-profit before the lock can arm; nothing special is done for it. (g) A pass of F13 is a pass of this exit on these 38
      picks; it says nothing about the 5% lock or about an exit that reads structure. (h) F13 is "not tuned" in its numbers (the engine's own),
      not in its history: F13.b is the full grid's row "ladder|k" on the pick's stop, and F13.a on a 2R pick is the row "ladder_tp2R|k",
      and those rows are among the 84 exits on which E0 was chosen on 2021-2023 (Known limit 2) and whose 2024-2026 per-trade results the
      owners have seen. The plateau selection of E0 therefore tilts F13.b's select result against it, and F13.b's confirm is not independent
      of the grid. No number changes; the owners read F13's table with this in mind (README_KO says it in one line).

## 13. Reproducibility

* Code lives in `research/exitflex/` (nine `.py` files, all pinned; the modules of the extra reads of 16.7 item 4 lie in
  `research/exitflex/extra/`, are pinned by `PREREG_EXITFLEX_EXTRA.sha256` and are not this file's code):
  * `data_x.py`: loading through `research/fullgrid/data.py` `load` (the `hc.py` "1m" path, shift 0), the cut and the
    cache rules below; the offered-signal table (`offered`) with the market-state code of each signal bar (below);
  * `kernel_x.py`: the engine, the 88 variants including F7h, F12 and F13 (the module lists the 82 of F1-F10, adds the 2 of
    F11 and the 2 of F12 once the F11 provider of `native.py` and `native_ds.py` is registered, which the runner does, and the
    2 of F13, which need no provider: F13 is only the exit arguments of `exit_of_pick`, `rp` is E0's vector (family 0) and no chart
    array is read);
  * `native.py` (the eight core strategies' own exits) and `native_ds.py` (the eight DeepSeek strategies'), Appendix A;
  * `runner_x.py`: the stages as command-line steps (`make-pin`, `pin-lines`, `make-cut`, `timing`, `select`,
    `report`, `choice`, `confirm`, `confirm-report`, `check`, `audit`, `audit-file`; `t3-side` is internal), the private
    owner reports and the pins (earlier drafts of this file wrote `run_x.py`; the file is `runner_x.py`);
  * `metrics.py` and `placebo.py`, the helper modules;
  * `test_exitflex.py` (T1-T8 and the runner's stages, on synthetic data) and `test_native.py` (the native modules of
    Appendix A; see the tests below for its real-bar tests).

  **Where the market-state columns are produced (section 7).**
  * `data_x.py`, `offered`: for each offered signal, the regime code at its signal bar, from
    `paperbot.dash.tools.regime5y.regimes(high, low, close, TF_MIN[tf])["code"]` on the pick's own chart arrays of that
    coin (the cut arrays in the select run, the full arrays in the confirm run), added as a column `state` (int8:
    UNKNOWN 0, TREND 1, RANGE 2, SHOCK 3, NORMAL 4) next to `atr`. The module's thresholds are asserted equal to the
    values of section 7 at import.
  * `kernel_x.py`: the result carries `tr_state`, the `state` of each closed trade's signal, next to `hold_h`'s inputs
    (`tr_fill`, `tr_exit`).
  * `metrics.py`: `summarize` keeps `tr_state` with `hold_h`; a new function `hold_by_state(hold_h, tr_state)` returns,
    per state, the count, median hold and the shares over 4 h, 8 h and 18 h (`hold_stats` per state); `pool_summary`
    adds `hold_by_state` and `hold_by_state_e0` beside `hold` and `hold_e0`, from all closed trades of the pool's
    accounts at quarter size.
  * `runner_x.py`: `variant_row` and `build_select_summary` carry it into `select.json`, `select_report_ko` prints the
    second table of 8.2, `finish_confirm` and the confirm report do the same for 9. The private owner reports are
    written by one function of `runner_x.py` from `ds_private/` files, with their sha256 written into `select.json` and
    `confirm.json`.
  * The code does not import `research/fullgrid/regimes.py` (it needs the whole `run`/`demobot` machinery); that file
    is pinned as the definition of the labels, and T8 checks the labels against `regime5y` directly.

  **Code and this revision.** The code in the folder follows this revision; section 17, part B, lists what is checked.
  In short: `kernel_x.py` carries the 88 variants (the 82 of F1-F10, the 2 of F11, the 2 of F12, the 2 of F13; F7h; the F11 mechanics
  of Appendix A, component kinds, C3 arming from i0, per-position levels and targets; F12 with a component mask for
  tests, `tr_comp` and `tr_state`, and the F12 placebo clock of section 6); `placebo.py` uses the seed base without the
  pick id, the coin index and check close of the key in section 6, the strata z of section 6 including F12's, and F12's
  clock (a hazard table without the clock check, a certain exit at it); `metrics.py` applies the gates per pool (14 of
  23, 9 of 15), the default of 8.4 (set D, shortest pooled median hold, ties by parameter count then canonical order,
  at most 2 from different groups, per pool, only for a pool with no answer; set D of 37), the F7h, F11, F12 and F13
  wording of 8.5, groups A and P, the loss class L0 of F13 and `hold_by_state`; `runner_x.py` treats F7, F7h and F13 as
  families without the placebo gate and prints the fixed hunt-read line of 17 item 4a at the top of the select and the
  confirm report. T7 and T8 below check this. The runner refuses to build the menu without the native
  modules (it would be fewer than 88 variants), and the confirm refuses a `select.json` that was not made with the
  complete menu. The league side (`candleague/rulex.py`, `candleague/exits.py`, `candleague/runner.py` and their tests) is
  not pinned here; it must meet 11.4 and its parity test before the restart.

  **What is pinned, as built.** `PREREG_EXITFLEX.sha256` has one line `<sha256>  <path from the repo root>` per file.
  The files are the constant `REQUIRED_PINS` of `runner_x.py`, plus every `.py` file at the top level of
  `research/exitflex/` that it does not already name (`os.listdir`, not a recursive search, so `research/exitflex/extra/`
  is not included), and `python research/exitflex/runner_x.py pin-lines` prints exactly those lines (35 now; 36
  once `make-pin` has written `data_pin.json`). The runner refuses every stage after `make-pin` unless each is listed
  and still has its hash. The pin file does not list itself or `README_KO.md` (which is not pinned), and its later
  lines are the stage files of the stages as built (below).
  * In `research/exitflex/`: this file, `data_pin.json`, and all nine `.py` files: `data_x.py`, `kernel_x.py`,
    `placebo.py`, `metrics.py`, `runner_x.py`, `test_exitflex.py`, `native.py`, `native_ds.py` (all in
    `REQUIRED_PINS`) and `test_native.py` (named by the rule for the folder's `.py` files). Their hashes are those of
    the pin commit and are in the pin file, not in this table.
  * The inputs, 25 files in `REQUIRED_PINS`, with the beginning of their sha256 as computed on 2026-10-12 (recomputed
    at the hashing commit, section 17):

  | input | sha256 |
  |---|---|
  | `research/fullgrid/kernel.py` | `a4995c15…` |
  | `research/fullgrid/run.py` | `4e02df9c…` |
  | `research/fullgrid/sizing.py` | `3dc00c24…` |
  | `research/fullgrid/data.py` | `6691424b…` |
  | `research/fullgrid/ds_defs.py` | `40a752cc…` |
  | `research/fullgrid/grid.py` (grid code that `run.py` loads) | `522cfb2e…` |
  | `research/fullgrid/memo.py` (grid code that `run.py` loads) | `30b5a25d…` |
  | `research/deepseek200/lib_c.py` | `3210c602…` |
  | `research/library/lib.py` | `5c3e1083…` |
  | `research/search/search.py` | `06920240…` |
  | `research/fullgrid/exchange.json` | `176e234b…` |
  | `research/fullgrid/diag/watch_sel.json` | `f6902feb…` |
  | `candleague/data/candidates.json` | `dd627ec0…` |
  | `paperbot/quality_edges.json` | `8b4fc48d…` |
  | `third_party/sweep/harness/vendor/fg_indicators.py` | `bf43c1b8…` |
  | `third_party/sweep/harness/vendor/pine_indicators.py` | `938c9545…` |
  | `paperbot/dash/tools/regime5y.py` (the market-state labels, section 7) | `b055a412…` |
  | `research/fullgrid/regimes.py` (the definition the labels follow) | `934578ba…` |
  | `paperbot/config.py` (settings) | `a5b64e3c…` |
  | `paperbot/ladder.py` (settings) | `6bd36810…` |
  | `paperbot/margin.py` (brackets) | `005db5e7…` |
  | `paperbot/levrule.py` (the leverage group) | `79b77d5f…` |
  | `paperbot/entry_marks.py` (the leverage group) | `01b2d918…` |
  | `paperbot/sweepsig.py` (the leverage group) | `422fd374…` |
  | `research/entry_study/DEFS_BC.sha256` (the file that hashes the `param_defs`) | `185dbcf8…` |

  Eight rows, `grid.py`, `memo.py`, `config.py`, `ladder.py`, `margin.py`, `levrule.py`, `entry_marks.py` and
  `sweepsig.py`, hold numbers that fix every account but lie outside the other files (the grid code that `run.py`
  loads, the settings, the brackets, the leverage group). They and the two regime files were added to the pin list
  after the first revisions (the regime files in the fourth, the eight in 16.5). `fg1m/build.json` (`824c9d1a…`) and the
  six coin files (section 2) are pinned through `data_pin.json`, not as lines of their own: the runner checks them
  against it at every stage with a data check.

  The runner also records the sha256 of every module file it loads from `research/library`, `research/search` and
  `third_party/sweep/harness/vendor` at the select run (all their `.py` files, a superset), and the confirm stage
  refuses on any difference; it also writes into `select.json` the engine fingerprint (the settings vectors of both
  sizes and the digest of the bracket arrays) and the confirm refuses on a difference there. Repo HEAD: the parent of the
  commit that adds `PREREG_EXITFLEX.sha256` (see `git log`); the repo is auto-committed, so this file names no commit hash.
  Versions: Python 3.11, numpy 2.0.2, pandas 2.3.3, numba 0.60.0. The runner records the versions it runs with.
* **The stages as built** (`python research/exitflex/runner_x.py --help` lists them; the order of work below runs them in
  this order).
  * `make-pin --data-dir DIR --work DIR [--out F]` writes `data_pin.json` (the absolute data and work folders, the sha256
    of `build.json` and of each of the six coin files). It needs no pin file, and it **refuses to overwrite** a
    `data_pin.json` that is already listed in `PREREG_EXITFLEX.sha256`.
  * `pin-lines` prints the lines for the pin file (above). It prints hashes of code and inputs only. The main session
    writes `PREREG_EXITFLEX.sha256` from its output.
  * **The gate.** Every stage after `make-pin` (`make-cut`, `timing`, `select`, `report`, `choice`, `confirm`, `check`,
    `audit`) first refuses unless: `data_pin.json` exists; the pin file exists and every file it lists has its hash
    ("hash mismatch"); every file of `REQUIRED_PINS` is listed ("not pinned"); every `.py` file at the top level of
    `research/exitflex/` is listed ("not pinned (code of this folder)"; its subfolders are not searched); and, for every
    stage except `report` and `choice`, `build.json` and the
    coin files still match `data_pin.json`. It then prints `[pin ok]` with the git commit and `<pin8>`. `confirm-report`
    and `audit-file` run no gate: they only rewrite or read committed files.
  * **`make-cut` is a separate step.** In its own process it reads the full pinned arrays once and writes the select
    cut data folder `$WORK/<pin8>/cut-202401010000/1m/<SYM>.npz` with `cut.json` (the pin hash, the cut time and a digest
    of every array), then verifies the digests and that no array holds a minute at or after 2024-01-01 00:00 UTC. The
    `select` and `timing` processes **only open and verify** that folder (`open_cut`: digests, no minute at or after
    the cut); when it is missing they start `make-cut` as a child process and open its result. No select or timing
    process loads a full array (audit A5).
  * `timing` writes `out/timing.json` (5.3: seconds, the projection, the seed count). Its hash is appended to the pin
    file before `select` can run.
  * `select [--procs N]` needs the gate and `timing.json` listed in the pin file with its present hash. It **refuses**
    when `out/select.json` or `out/SELECT_KO.md` exists or is listed in the pin file: it runs once. It refuses without
    the native modules (the menu would be fewer than 88 variants). Step 2 starts only when every step-1 file exists, and
    the summary runs once when every file exists. `select --rerun` (section 14) needs `select.json`, no `confirm.json`, no
    `select_r2.json` or `SELECT_KO_r2.md` (existing or pinned), and an entry naming `select_r2` in this folder's
    `DEVIATIONS.md`, written before the rerun; it writes the `_r2` files.
  * `report` is **read-only**. It rewrites `select.json` and `SELECT_KO.md` from the finished result files, computes
    nothing, loads no market data, and refuses when any result file is missing, when `timing.json` is not pinned, or
    when `select.json` or `SELECT_KO.md` is already listed in the pin file (a pinned report changes only by a section 14
    rerun).
  * `choice --input F [--now-utc T] [--rerun]` needs `select.json`, `SELECT_KO.md`, `timing.json` and `sent.json`, each
    listed in the pin file with its present hash (with `--rerun`: the `_r2` set and `choice.json`). It **refuses when
    `choice.json` is already listed in the pin file** (`choice_r2.json` for a rerun: a choice is final once hashed, 8.3);
    when `select.json` was made under another pin; when a pool has no answer and its deadline has not passed; and when
    the document does not validate (8.3: choosable ids, at most 2 from different groups, the send time equal to
    `sent.json`, the private report shown at or before the sending, the default's ids, the list of 2024-2026 material
    naming `ANALYSIS_KO.md`, `STRATEGIES_KO.md` and `STRATEGY_EVAL_KO.md`) or the free-text tripwire (A8) still finds a
    DeepSeek money figure after the redaction.
  * `confirm [--procs N] [--rerun]` needs the gate and `select.json`, `SELECT_KO.md`, `timing.json`, `sent.json` and
    `choice.json` listed in the pin file with their present hashes (and the `_r2` set when `choice_r2.json` exists). It
    **refuses**: when `select.json` was not made with the complete menu of 88 variants; when the choice does not
    validate; when `confirm.json` exists (it runs once; `--rerun` needs `confirm.json`, no `confirm_r2.json` and an entry
    naming `confirm_r2` in `DEVIATIONS.md`); when no variant was chosen in either pool; **when a module file changed**
    since the select run (the sha256 of every `.py` file of `research/library`, `research/search` and the vendor
    folder, recorded in `select.json`; checked before anything is loaded and again before and after the accounts are
    computed); and **when the engine fingerprint changed** (the settings vectors of both sizes and the digest of the
    bracket, quantity-step and minimum-notional arrays, which come from `paperbot/config.py`, `margin.py` and
    `exchange.json`; a `select.json` without it is refused).
  * `confirm-report [--extra-messages F]` rewrites `out/REPORT_KO.md` from `confirm.json` without any recomputation.
  * `check [--which t1,t3,t5,t8]` runs the real-data parts of T1, T3, T5 and T8 (pass or fail and counts only);
    `audit --stage select|confirm` runs A1-A9 (pass or fail); `audit-file --path F [--path F2 ...] [--after MARK]` runs
    A8 and A9 on files before they are sent or committed (section 14).
  * The pin file grows as the stages finish: `timing.json` (before `select`), then `select.json` and `SELECT_KO.md`,
    then `sent.json`, then `choice.json` (and the `_r2` files of a rerun). The runner never writes it.
* **Caches.**
  * exitflex uses no disk cache it does not own. `hc.py`'s frame pickles (`frames_5m`, `frames_1m`) and signal cache
    (`cache/sig_*`) are not read. `run.FRAME_DIR` points into the stage's own folder.
  * exitflex's own disk caches live under `$WORK/<pin8>/<stage>/`, where `$WORK` is a folder outside the repo named in
    `data_pin.json`, `<pin8>` the first 8 hex digits of the pin, and `<stage>` one of `timing`, `select`, `select_r2`,
    `check`, `confirm`, `confirm_r2`, `t3-<cut>`. **The pin is the sha256 of the file `data_pin.json`**
    (`data_x.pin_sha`) and nothing else. `PREREG_EXITFLEX.sha256` grows after the pin (timing.json, select.json,
    SELECT_KO.md, sent.json, choice.json) and is not the pin, so `<pin8>` and the `ds_private` folder do not move between
    stages. A stage deletes its own cache folder before it starts. Cache keys include the pin hash and the cut time.
  * The cut arrays are written as their own data folder, `$WORK/<pin8>/cut-<cut time>/1m/<SYM>.npz`. Every `run.py`
    cache keyed by the data folder (`frame`, `best_flags`, `struct_levels`, `all_minutes`) therefore sees a different
    key for cut and full data. The `ds_defs` cache dicts are per process and per series.
  * Memory caches (those `lru_cache`s, the `run.M` memo and `run._DS_CACHE`) live only inside one process. Every
    stage, and each side of each T3 comparison, runs in its own fresh process.
  * Per-account result files of the core picks live under `$WORK/<pin8>/results/<stage>/`; those of the DeepSeek picks,
    and every DeepSeek money figure and p value, under `$WORK/<pin8>/ds_private/` (its `results/<stage>/` included);
    the private owner reports `owner_report_select.md` and `owner_report_confirm.md` (section 3) lie there too, and so
    do the `_r2` files of a rerun, `owner_messages.json` (section 3) and the private extra report `owner_report_extra.md`
    of the extra reads (section 3, 16.7 item 4); all outside the repository, never committed.
    Only `timing.json`, `select.json`, `SELECT_KO.md`, `sent.json`, `choice.json`, `confirm.json` and `REPORT_KO.md` go
    into `research/exitflex/out/` and, under section 14, `select_r2.json`, `SELECT_KO_r2.md`, `sent_r2.json`,
    `choice_r2.json`, `confirm_r2.json` and `REPORT_KO_r2.md`.
* **Tests that must pass before any select run.** They print only pass or fail and counts of cases, never a
  performance figure.
  * **Where they live, as built.** T1-T8 and the runner's stages are in `research/exitflex/test_exitflex.py` (synthetic
    data only); audit A1 reruns that file and no other. The native modules' tests (T2, T3, T5 and T6 for Appendix A) are
    in `research/exitflex/test_native.py`. Its real-bar tests compare booleans on the select-period 1m arrays of the folder
    named by `EXITFLEX_FG1M` and are **skipped** when the folder is missing; a skip is not a pass, so at the pin the file
    is run with `EXITFLEX_REQUIRE_REAL=1` (a missing folder then fails the run) and the summary must say 0 skipped. The
    league's parity test is `tests/test_exitflex_league_parity.py` (11.4 item 13), on synthetic data; it is not pinned and
    A1 does not run it. It runs F13.a and F13.b at both sizes and as coin flips against the study's kernel, with restarts in
    the middle of positions whose lock is raised, and `tests/test_candleague_exits.py` and `tests/test_candleague_rulex.py`
    cover the exit names and the engine of F13 on the league side.
  * **T1 parity.** With no rule, no placebo and the period end after the data end, `_trade_x` must equal
    `kernel._trade`: wallet change to 1e-9, exit index, reason and leverage. `account_x` must equal `kernel.account`:
    statuses, P&L, exit times, reasons, leverages and the final wallet. Test inputs:
    * synthetic 1m paths with gaps, missing minutes, funding and a mark price that differs from the last price, all 84
      kernel exits, both sides, both leverage groups, at scales 0.25 and 1;
    * the same for the F13 exit arguments of `exit_of_pick` (the pick's stop, its take-profit or none, the lock 10% / 5% /
      2%) on every fourth of the 84 pick exits in both modes: `account_x` equals `kernel.account` run with the same arguments,
      with LOCK, SL and TP exits all occurring; and F13.b equals the full grid's "ladder|k" rule and F13.a on a 2R pick its
      "ladder_tp2R|k" rule, account for account;
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
    * F12, F12.a and F12.b, both sides, with the fixed values of 5.2:
      * each of the nine components alone, with the other eight silent on the path, closes the position at its own
        check, with the right reason set in `tr_comp`;
      * **first trigger wins**: on a path where component A would fire at check 3 and component B at check 5, the exit
        is at check 3, `tr_comp` holds A (and any other component that fired at check 3) and not B;
      * **ties**: with two, three and all nine components firing at one check (same bar), there is one exit, at the
        same minute, price and fee as one component alone, `tr_reason` is RULE and `tr_comp` holds every component
        that fired; the same when the components fire on different bars merged into one check by a missing bin;
      * F6 never fires without F1 (the `tr_comp` bit of F6 implies the bit of F1) and never changes the exit time;
      * single-component parity: with a component mask that switches on one component only, F12 equals the family
        variant at the F12 value trade for trade (F1.w3, F2.n20, F3, F4.m2, F5.P1.5.g50, F7h.H8, F10.N12, F11; F6 has
        no mode (b) family and is checked by hand paths) in the mode of the test;
      * F12.a keeps the pick's take-profit and F12.b has none, with F12.b keeping the native target where Appendix A
        defines one; the hard stop, liquidation, a gap at the check minute and END behave as in 5.4.1 and 5.4.6;
      * F7h at 8 hours ends a hold that no other component ended, on 15m, 30m, 1h and 4h picks;
      * an F3 reversal under F12 enters the reversing signal at the freed minute (5.4.8);
    * a path where minute j's high (or low) alone would change F4's level, F5's or F8's arm or F10's stall leaves the
      decision at j unchanged;
    * the q15 mapping works, with 15m and 30m picks equal to the base variant;
    * missing minutes are handled;
    * a gap beyond the stop gives SL and does not free the minute;
    * the take-profit gap comes first and liquidation first of all;
    * funding is paid at the exit minute;
    * END closes;
    * only RULE and RAND free the fill minute;
    * F13, F13.a and F13.b, both sides, with the expected prices written with the engine's own `paperbot/ladder.py` and not with
      the kernel's formulas:
      * the lock arms at 12% net ROE and the position leaves at the 10% price when the price falls back, steps to 15% at 17%,
        20% at 22%, 25% at 27%, 30% at 32% and on (a best price inside each band, seven bands, two pick exits: a 3R pick and
        a net-ROE 50% pick), as a LOCK at the next minute that touches the stop, with slippage, taker; E0 on the same path has
        no lock and no such exit; a best price just under 12% leaves the hard stop alone;
      * the lock is raised by the best price of a minute (a wick) and applies from the next minute: a wick that arms it with the
        same minute's low under the new lock does not exit in that minute, the next open under the lock exits at the open;
      * the same minute that reaches the hard stop and the arming price exits by the hard stop (SL, not LOCK);
      * the lock and the pick's take-profit: a minute that touches the take-profit exits there (TP, maker) and raises no lock; a
        minute that touches both the take-profit and a raised lock stop exits at the stop and is counted as 'both'; mode b has no
        take-profit and ends at the lock or END; a climb through 3R (or net ROE 50%) exits at the take-profit in mode a;
      * funding paid before the lock moves the arming and the locked price by its share of the notional;
      * the exit arguments of every one of the 84 pick exits in both modes (the pick's stop and take-profit, the lock, no
        take-profit in b), and `rp` equal to E0's vector (family 0);
      * a differential test of the numba kernel against a plain-Python reference that writes the lock with
        `paperbot/ladder.py`, on random worlds of 15m and 1h picks;
  * **T3 causality of the inputs.** At each of these 21 cut times (UTC), the cut arrays and the full arrays must agree
    on the last 50 chart bars that close at or before the cut, for every pick's timeframe and for 15m:
    * cut times: the first day, 00:00, of every second month from 2021-02 to 2023-12 (18 cuts), 2022-06-15 13:37,
      2023-03-17 07:05 and 2024-01-01 00:00;
    * compared: every pick's signals (both sides, both pools) and core leverage groups, ATR14, EMA(10, 20, 50), the
      swings (w = 2, 3, 5) with their confirmation bars, F1's reference series, the 15m bars, every F11 array of
      Appendix A (components of both sides, levels and targets at the signal bars), and the market-state code of
      section 7 (`regimes` code, ADX14, EMA50 slope, ATR% and its threshold) at every bar and at every signal bar;
    * each side of each cut runs in its own fresh process with its own cache folder;
    * it also asserts that the cut arrays hold no minute at or after the cut, and that the cut frames' last bar closes
      at or before the cut.

    Any difference stops the run.
  * **T4 placebo.**
    * With h = 0 everywhere the result equals the mode's base account (for F12: the account with F12's clock leg alone,
      F7h.H8 in the mode, F12.b keeping the native target). With h = 1 everywhere the exit comes at the first check.
    * The draws depend only on (V, period, seed, coin, time) and are reproducible. Two picks with identical inputs
      (the same coin, signals and hazard table, different ids) give identical placebo exits. The key is checked on a
      hand-computed example: the coin index is the position in the priority order (BTC 0, ETH 1, SOL 2, DOGE 3, LTC 4,
      BCH 5), the time is the close of the latest closed chart bar of the check (the 15m bar for q15).
    * Hand-computed hazard tables on built paths for F5 (unarmed checks counted in the denominator, only RULE in the
      numerator) and for F6 (loss-only exits), including a check whose minute gaps through the stop (counted in
      neither).
    * The strata z of section 6 on built paths: F6.d0.5 and F9 (z = 1 only below -0.5R with a reference, or for F9
      after the arm), F8 (armed and a reference), F11 for F12_MSS_DISP (z = 0 while no live swing level exists) and
      for a level-only DeepSeek strategy with a NaN level (z = 0).
    * The placebo's own stratum uses the frozen state of step 0.
    * F11.b's placebo keeps the native target, and so does F12.b's.
    * F12's stratum z (section 6) on built paths: z = 0 when no swing reference exists, F2 and F5 are unarmed and F11's z
      is 0; z = 1 when any one of the four holds alone; a check where only F3, F4, F7h or F10 could fire has z = 0.
      F12's hazard table counts RULE exits whichever component fired (the denominator counts every check of its
      schedule before the clock check, the numerator every RULE exit at those checks, a gapped check in neither), and a
      placebo exit carries no `tr_comp`.
    * **F12's clock** (section 6), on built paths of a 15m, a 30m, a 1h and a 4h pick, in both modes: the clock check
      (k = 32, 16, 8 and 2) and every later check are in neither the numerator nor the denominator of the table; the
      F12 placebo exits with probability 1 at its clock check, also when the clock bin is missing (the next close that
      exists acts) and when the clock falls in a merged check; no F12 placebo position is held past its clock check;
      the longest hold of the F12 placebo does not exceed that of F12 on the same path.
    * Two steps: on a small built case, running every placebo and running only those of step 2 give the same
      eligible set (F12 included, F7, F7h and F13 excluded).
    * **F13 has no placebo**: `has_placebo` is false for both variants, a placebo run of F13 is refused, a step-2 pair is never
      made for F13 even when its gates 1, 2 and 4 pass (the synthetic runner case forces them open), its gate 3 reads "해당
      없음", and the eligibility path is the one of F7 and F7h (no gate 3), with the reason stated in section 6.
  * **T5 causality of the decisions.** For every family at its middle parameter, F12 in both modes at its fixed
    values, and F11 in both modes for every strategy, on synthetic paths and, with `check` on the select-period cut arrays,
    on at least 500 sampled (trade, check) pairs per pool (`T5_PER_POOL`): for each pick and each of the 18 variants of
    `MIDDLE_VARIANTS`, offered signals are drawn at random until `per` = ceil(500 / (the pool's picks x 18)) drawn trades
    with a check are found (2 in both pools), at most 20 x `per` draws (`T5_DRAW_CAP`); a drawn signal whose trade has no
    check (it ends before its first check, or no size fits it) gives no pair, and a drawn trade with a check gives one pair
    per mode checked: two for a variant with a placebo (its rule run and its placebo run), one for F7 and F7h. The nominal
    ceilings are 1,564 pairs in core and 1,020 in DeepSeek (68 per pick: 16 variants with a placebo x 2 trades x 2 pairs,
    plus F7 and F7h x 2 trades x 1 pair). `check` passes T5 only when each pool has at least 500 pairs and none failed;
    fewer is a failure (14). With T5, `check` refuses to run without the native modules, so F11 and F12 are always in the
    list. For each pair: change the OHLC and mark of minute j and of every later minute, and of every chart bar closing
    after the check close. The rule decision at j (for F12 the decision and the `tr_comp` set), the
    placebo stratum at j and every arm flag must stay identical. Only decisions are compared; no P&L is kept. **F13** has no
    decision and no check; its causality is that the stop in force at minute j depends only on minutes before j: on sampled
    trades of F13.a and F13.b, replacing every minute from the exit minute x + 1 on leaves the trade identical (minute,
    reason, price, wallet change), and replacing every minute from x on never lets the trade end before x. **This is tested
    on synthetic paths only** (`test_exitflex.py`): the real-data `check` T5 samples (trade, check) pairs, a trade without a
    check cannot be sampled, so F13 is not in its list (`MIDDLE_VARIANTS`, 18 variants); the quota per pick and variant (2 drawn trades with a check) is the same as with F13 in the list.
  * **T6 native parity.** `native.py`, where it re-derives an entry (N13_3OUTSIDE), and `native_ds.py` reproduce
    `run.signals` bar for bar; DOGE's components reproduce the source's `long_exit` and `short_exit`; every final
    DeepSeek signal bar receives its levels (Appendix A). F12's F11 component reads the same arrays, levels and
    targets as F11 (the same objects): with the other eight components switched off, F12.a equals F11.a and F12.b equals
    F11.b trade for trade on sampled picks of all 16 strategies.
  * **T7 selection logic**, on synthetic `select.json`-shaped inputs with no real figure:
    * the gates per pool (14 of 23 core picks, 9 of 15 DeepSeek picks; a zero M_p does not count), F7, F7h and F13
      exempt from gate 3, and the gate-failure counts in sequence (8.2);
    * the default of 8.4 per pool: only set D, shortest pooled median hold first, ties by parameter count then
      canonical order, the second from a different group, "none" when no candidate; applied only to a pool with no
      answer before its deadline; an explicit "없음" stays none;
    * the group rule (at most 2 per pool, different groups; one variant may serve both pools when choosable in both);
    * the validation of `choice.json` and `choice_r2.json` (8.3, 14): unknown or unchoosable ids, three ids, two ids of
      one group, a "default used" flag with an answer timed before the deadline, a send time that differs from
      `sent.json`, a default that differs from 8.4's output, and a swapped id that was still choosable after a rerun
      are each refused;
    * a D11 whitelist: a synthetic `select.json`, `confirm.json`, `SELECT_KO.md` and `REPORT_KO.md` with a DeepSeek
      money figure or p value planted in any DeepSeek row are refused; the allowed fields pass (hold hours by market
      state and F12 component counts included); a synthetic private owner report written anywhere but
      `$WORK/<pin8>/ds_private/` (or inside the repository) is refused, one under `ds_private/` passes, its sha256 is
      the one written into the json, and it holds no p value and, in the select report, no money on a "선택 불가" row;
    * **the free-text tripwire and the redaction** (section 3, A8), on synthetic files: a `choice.json`,
      `choice_r2.json`, `sent.json`, DEVIATIONS entry, `REPORT_KO.md` prose line and ledger print in which an owner
      message or a main-session question quotes a DeepSeek figure next to a `ds-` id, 딥시크 or DeepSeek (a percent, a
      multiple such as `3배` or `3x`, a drawdown, a bust, a growth figure, a p value) are refused; the same text with
      the figure replaced by `[딥시크 금액 삭제]` passes, and so do an id alone, a core figure, and a hold hour or count
      in a DeepSeek row; the redaction function replaces figures only, leaves ids, times, hold hours and counts as they
      were, and writes the sha256 of the unredacted text to `ds_private/owner_messages.json`;
    * the 88 variants and their groups: group A holds F12 alone, group P holds F13 alone (two variants, 0 parameters, L0),
      F12 is outside set D, the default never returns F12, F12 (not F7, F7h, F13) reaches step 2 of the placebo, F13 is in
      set D and can be the default (it is ranked by hold hours like any other member, and a second pick must come from another
      group), the order of the variants is 1 to 88 with F13 last, and the counts of 5.3 (88 variants, 74 with a placebo, 37 in
      D, 35 outside F13);
    * `claim_of` gives the 8.5 wording for F7, F7h, F11, F12, F13 and the rest (F13: "closes by the engine's stepped profit
      lock: after +12% net ROE it never gives back below +10%, except by the slippage of a stop and at a gapped open, which can lie
      anywhere; it reads no structure and makes no claim beyond that");
    * the select report and the confirm report carry the fixed hunt-read line (17 item 4a): `SELECT_KO.md` and `REPORT_KO.md`
      hold `HUNT_READ_KO` of `runner_x.py` near the top, it passes audit A8 and carries no number of any result;
  * **T8 market-state labels** (section 7), on built paths and on the select-period cut arrays, printing counts only:
    * **causality**: for at least 500 sampled offered signals per pool (ceil(500 / the pool's picks) per pick: 506 core,
      510 DeepSeek; `check` passes T8 only with at least 500 per pool and none failed) and for built series, replace the
      OHLCV of every chart bar after the signal bar and every 1m minute from the entry minute on by other values (random
      and extreme); the
      label of the signal must not change. The label from arrays truncated at the signal bar equals the label from the
      full arrays. (T3 adds the cut against full comparison.)
    * **definition**: the label equals `regime5y.regimes(...)["code"]` at the signal bar on the pick's own chart, maps
      to 추세장 / 횡보장 / 급변장 / 보통 / 모름 as `regime5y.RKO` does, and the constants read from the module equal
      those of section 7 (14, 50, 10, 25, 20, 0.5, 0.80, 365, 180); the precedence 급변장 > 추세장 > 횡보장 > 보통 holds on
      built bars where two conditions are true; a coin with less than 180 days of history gets 모름.
    * **bookkeeping**: every closed trade has exactly one label; the per-state counts sum to the pool's closed trades;
      E0 and V give the same label to the same signal; `hold_by_state` equals hand-computed medians and shares on a
      built set, including an empty state (count 0, no median) and a state under 100 trades (marked); the labels
      enter no gate, no default, no placebo stratum (changing every label leaves the gates, the default and the
      placebo draws unchanged).
* Seeds use `run._seed`: the first 8 hex digits of the sha256 of the "|"-joined parts.
* **Order of work**:
  1. Code and tests (T1-T8, the native tests with `EXITFLEX_REQUIRE_REAL=1`, the league parity test); `make-pin`
     writes `data_pin.json`; `pin-lines` prints the lines; the main session writes `PREREG_EXITFLEX.sha256` from them,
     then commit and push: the pin commit, whose message carries the pin time (the status line at the top of this file
     points to it).
  2. `check` (the real-data parts of T1, T3, T5 and T8; pass or fail and counts; T5 and T8 need at least 500 per pool,
     and a failure stops the work, 14), then `make-cut` (the cut data folder, in its own process), then the timing stage
     (seconds only), the seed count of 5.3, `out/timing.json`; the hash of `timing.json` is appended to the pin file (the
     select stage refuses without it), commit and push. Then `research/exitflex/PREREG_EXITFLEX_EXTRA.md` (the
     definitions of every extra read and twin of 16.7 item 4) and a first `research/exitflex/PREREG_EXITFLEX_EXTRA.sha256`
     that lists it are committed and pushed (17, O7); the select stage is not started before that push.
  3. The select run, in fresh processes: step 1, then step 2. Its console shows the `[pin ok]` line (the HEAD it runs
     on) and progress only; the lines of step 2 give the count done and the seconds, and nothing of step 1's gates (14).
     It writes `out/select.json` and `out/SELECT_KO.md` and the private owner report
     `$WORK/<pin8>/ds_private/owner_report_select.md`. During or after the run, and before any output of the select stage
     is opened (`select.json`, `SELECT_KO.md`, any per-account result file, the private DeepSeek report), the modules and
     tests of the extra reads in `research/exitflex/extra/` are committed and pushed with `PREREG_EXITFLEX_EXTRA.sha256`
     extended to list them (16.7 item 4; 17, O8). The post-run audits of section 14 run after that push, so a line that
     A8 flags is read only after it; the hashes of `select.json` and `SELECT_KO.md` are appended, then commit and push.
     The extra reads and twins of 16.7 item 4 then run, and each of their outputs that is committed or sent passes
     `audit-file` first. The main session checks the private report's sha256 against `select.json`, shows the private
     report and the private extra report (section 3) in the chat with the owners and sends the extra reads and twins,
     in the same turn as or before it sends `SELECT_KO.md` (never over a logged channel, section 3), then writes
     `out/sent.json` (sending time, channel, the time the private report was shown, freeze note, `extra_note`,
     `extra_shown_utc`, `ds_owner_report_extra_sha256`), runs audit A8 on it, and hashes, commits and pushes it before
     reading any answer (8.7). The freeze of 8.3 starts.
  4. The owners' answers per pool (or the default for a pool with none by its deadline), with every DeepSeek money
     figure in them replaced by the marker of section 3, `out/choice.json`, audit A8 on it, its hash appended, commit
     and push. The freeze ends.
  5. The confirm run, once, in a fresh process, writes `out/confirm.json` and the private owner report
     `owner_report_confirm.md`; the audits run; then `out/REPORT_KO.md` and the ledger print are written, **and audits A8
     and A9 run again on them** (and on every redacted owner message the report quotes) before they are committed; the
     main session shows the private report to the owners in the chat.
  6. After a PASS and the owners' OK: the league changes of 11.4 with their parity test, the DEVIATIONS entry (audit A8
     on it before it is committed), the restart, then C1 and C2 (11.5).

  The runner prints the git commit (`[pin ok] commit ... pin ...`) and refuses to run on a hash mismatch; the other
  refusals of each stage are listed under "The stages as built" above.

## 14. Failure handling, bugs and looks

* **A look** is any performance figure (P&L, growth, wallet, win share, hold time, exit-reason count, trades entered or
  skipped per arm) written to a file or a screen that a person or an agent reads. Tests and audits print only pass or
  fail and counts of cases; the timing stage prints only times. DeepSeek money figures are a look only through the two
  private owner reports of section 3 (the main session and the owners read them); nobody reads the other files of
  `ds_private/` (section 3). Hold hours by market state are figures like any hold time: they are looks once the
  report is written.
* **Tests.** If T1-T8 cannot pass without changing a rule of this file, nothing runs. The change is filed in
  `DEVIATIONS.md`, with the reason, before any run.
* **Crash and resume.** Each stage writes one result file per (pick, arm, size, seed block) under
  `$WORK/<pin8>/results/<stage>/` (DeepSeek picks: `$WORK/<pin8>/ds_private/results/<stage>/`), atomically. A resume computes only the missing files. Nothing is read, summarised or
  printed until every file of the stage exists; then the stage's summary runs once. Step 2 of the select stage starts
  only when every step-1 file exists, and the runner passes it only the gate flags and the hazard tables of step 1;
  nothing of step 1 is printed before step 2 ends. This holds as built since the eighth pass (16.7 item 4): the progress
  lines of the placebo steps (`select step 2`, `confirm placebos`) give only the count of picks done and the seconds;
  every pick gets a task, and one whose pool has no step-2 pair makes no file. Before, each line named its pick and its
  number of new placebo files, which showed how many variants of its pool had passed gates 1, 2 and 4. The seconds show
  how long the step has run, which grows with the number of pairs it has; they name no pick, variant or count.
* **Zero-signal picks** have M_p = 0 and do not count as > 0. **Busts** follow section 7, for E0, variants and
  placebos alike.
* **Post-run audits.** They print pass or fail only. A1-A7 run after the select run and after the confirm run,
  whatever the outcome. **A8 and A9 also run on each file that reaches the owners or the repository, after it is
  written and before it is sent or committed**: after the select run (`select.json`, `SELECT_KO.md`, the private owner
  report), after `sent.json`, after `choice.json` (and `choice_r2.json`), after the confirm run (`confirm.json`, the
  private owner report), after `REPORT_KO.md` and the ledger print are written (the confirm report is the main
  DeepSeek-carrying committed file of the confirm stage, so the audit has to read it and not only the json), after the
  files of a rerun, after each entry this study writes into a `DEVIATIONS.md`, and on each output of the extra reads of
  16.7 item 4 that is committed or sent (through `audit-file`; their private extra report gets the checks of A8 (3),
  section 3). A file that fails is not sent or committed; the main session fixes the text (the redaction of section 3)
  and the audit runs again.
  * A1: T1-T8 rerun at the run's commit (as built, `audit` reruns `test_exitflex.py`; `test_native.py` is run by hand at
    the pin, 13).
  * A2: for every account, signals offered = entered + skipped + rejected + no fill + after bust.
  * A3: every RULE and RAND exit lies at the check minute of one of the position's checks, at that minute's open
    with slippage.
  * A4: every account's final wallet equals $5,000 plus the sum of its trades' wallet changes (to 1e-9 relative).
  * A5 (select only): no array loaded by the select process holds a minute at or after 2024-01-01.
  * A6: E0 through `kernel_x` equals `kernel.account` on the same signals and period end.
  * A7: each placebo's realised exit rate per stratum lies within a 99.9% binomial band around h (for F12 over the checks
    before its clock check; and no F12 placebo position is held past its clock check).
  * A8: no committed or sent file of this study holds a DeepSeek money figure or p value. Scope: `select.json`,
    `confirm.json`, `sent.json`, `choice.json`, the `_r2` files of a rerun (`select_r2.json`, `SELECT_KO_r2.md`,
    `sent_r2.json`, `choice_r2.json`, `confirm_r2.json`, `REPORT_KO_r2.md`), `SELECT_KO.md`, `REPORT_KO.md`, the ledger
    print, this folder's `DEVIATIONS.md`, the entries of this study in `research/fullgrid/DEVIATIONS.md`, and the weekly
    notes. (1) Every DeepSeek row of the tables carries only the allowed fields (counts, win shares, hold times overall
    and by market state, exit reasons, F12 component counts, labels). (2) **Free text** (owner messages, main-session
    questions, the freeze note, DEVIATIONS entries, the prose of the reports outside their tables): a line that holds a
    `ds-` id, 딥시크 or DeepSeek and also a number followed by `%`, `퍼센트`, `percent`, `배`, `x` or `×`, or a money
    word (성장, 낙폭, 파산, 수익, 손실, 지갑, growth, drawdown, bust, wallet, multiple, p값, p-value) and a digit, is
    flagged, and the file fails unless the figure has been replaced by `[딥시크 금액 삭제]`. A percent that is a win share
    or a share of trades held over 4 h, 8 h or 18 h is an allowed field and is not flagged (the pattern lists those
    words). The pattern is a tripwire, not a proof; the main session reads each flagged line. (3) The private owner
    report of the stage exists at `$WORK/<pin8>/ds_private/owner_report_<stage>.md` (`_r2` for a rerun), its sha256
    equals `ds_owner_report_sha256` in
    the stage's json, it lies outside the repository (`git ls-files` lists no `owner_report_*` file and no committed
    file contains a line of it), it holds no p value, and its last line asks the owners to name variants by id.
  * A9: the market-state columns are consistent: every closed trade has exactly one state; per pool and arm the state
    counts sum to the closed trades; E0 and each variant give the same label to the same signal; no label differs from
    a recomputation of `regime5y.regimes` on the stage's arrays at the signal bar. On the report files A9 also checks
    that the state tables printed in `SELECT_KO.md` and `REPORT_KO.md` equal the json's counts.
* **A bug found by an audit or by T1-T8.** It is fixed and recorded in `DEVIATIONS.md` before the rerun's output is
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
* **A bug found any other way before the confirm** (for example by the extra reads of 16.7 item 4) is handled as a bug
  found by an audit (above): it is fixed and recorded in `DEVIATIONS.md` before the rerun's output is read, and the select
  stage is rerun once under the same rules.
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
* **The fourth revision** (2026-10-12, after the main session's decisions of about 12:20 KST and the owners' three
  latest messages) was written by a further sub-session, under the rules that it edits only this file and
  `README_KO.md`, edits no code, commits and pushes nothing, and opens no performance figure. It read: this file and
  `README_KO.md` in full; `research/fullgrid/regimes.py` in full; `paperbot/dash/tools/regime5y.py` lines 1-215 (header,
  constants, `rma`, `adx_atr`, `ema`, `vol_threshold`, `indicators`, `label_codes`, `regimes`, then `windows`,
  `period_windows`, `bounds_for`, `window_pnl` and the start of `summary`); `docs/regime5y.md` lines 1-60 (the regime definitions and the account design, not its results section);
  `research/exitflex/metrics.py` lines 1-35 and 105-200 (header, constants, `hold_stats`, `pool_of`, `pooled_series`,
  `pool_summary`, `eligibility`, `choose_variants`, `claim_of`) and its function list; `research/exitflex/runner_x.py`
  lines 1-72 (header, constants, the required-pin list) and its function and class names; the variant-class lines of
  `research/exitflex/kernel_x.py` (the `_VARIANTS` assertion and slots) and the column names of
  `research/exitflex/data_x.py` `offered`; `git status` and `git log -1` names; the sha256 of `regime5y.py` and
  `regimes.py`. It did not open `regimes.json` or `regimes_KO.md` (outputs of `regimes.py`),
  `paperbot/dash/data/regime5y.json`, the `holdcost` outputs, `out/` files, `diag/*.json`, `STRATEGIES_KO.md`,
  `STRATEGY_EVAL_KO.md`, `ANALYSIS_KO.md`, any hunt, autopsy, league or track-2 result, or any DeepSeek money figure,
  and it opened no performance figure of any period.
* **The fifth revision** (2026-10-12, after two reviews of the fourth revision) was written by a further sub-session
  under the same rules (it edits only this file and `README_KO.md`, edits no code, commits and pushes nothing, and
  opens no performance figure). It read: this file and `README_KO.md` in full; the two reviews' findings;
  `research/exitflex/placebo.py` in full; `draw_u` and the stratum lines of `research/exitflex/kernel_x.py` (lines
  120-140 and 405-445); the lines of `research/exitflex/runner_x.py` that name the `_r2` files, `ds_owner_report_sha256`
  and the owner-report audit (a grep by name); `pin8` and `pin_sha` in `research/exitflex/data_x.py`; the lines of
  `paperbot/dash/tools/regime5y.py` that name its window, its constants and `adx_atr` (a grep);
  `research/fullgrid/DEVIATIONS.md` lines 60-82 (league entries, among them the 2026-10-11 DeepSeek-money entry), the
  `CANDLEAGUE_DS_MONEY` lines of `candleague/notify.py` and lines 111-112 of `docs/candleague-ko.md`. It opened no
  performance figure of any period, no `holdcost` output, no hunt, autopsy, league or track-2 result, no `out/` file
  and no DeepSeek money figure.
* **The sixth pass** (2026-10-12, afternoon, after the owners' stepped-lock request; section 16.6) was written by a further
  sub-session under these rules: it edits only the study folder's `.py` files, this file, `README_KO.md`,
  `candleague/rulex.py`, `candleague/exits.py` (adding rules only) and three test files; it commits and pushes nothing, creates no
  `data_pin.json` and runs none of `make-pin`, `make-cut`, `select`, `timing` and `confirm`; it prints and saves no
  performance figure of any real period (its tests use synthetic data and print pass or fail). It read: this file and
  `README_KO.md`; `paperbot/ladder.py` in full; `paperbot/engine.py` (`_try_enter`, `_handle_exit`, `_raise_lock`, the
  state functions); `paperbot/sizing.py` (`tp_from_roe`); `research/fullgrid/kernel.py` (`TP_RULES`, `_trade`, `outcomes`,
  `account`); `research/exitflex/kernel_x.py`, `data_x.py` (`chart`), `metrics.py`, `placebo.py`, `runner_x.py` (the rows,
  the reports, the counts) and `test_exitflex.py`; `candleague/exits.py`, `rulex.py` (its accounts, engine, `chunk_rule`,
  `audit_restored`), the league's `runner.py` and `league.py` by name, `tests/test_candleague_exits.py`,
  `test_candleague_rulex.py`, `test_exitflex_league_parity.py` and `tests/test_fullgrid_kernel.py`'s helpers. It opened no
  performance figure of any period, no `holdcost`, hunt, autopsy, league or track-2 result, no `out/` file and no DeepSeek
  money figure. It did not touch the main session's statement or the dated addendum below it.
* **The seventh pass** (2026-10-12, afternoon, after two reviews of the sixth pass; section 16.6 items 11-22) was written by a further
  sub-session under the rules of the sixth: it edits only the study folder's `.py` files, this file, `README_KO.md`,
  `candleague/rulex.py`, `candleague/exits.py` (adding rules only; it changed none), `candleague/runner.py` and `league.py` only if needed
  (it changed neither) and the three test files; it commits and pushes nothing, creates no `data_pin.json` and runs none of `make-pin`,
  `make-cut`, `select`, `timing` and `confirm`; it prints and saves no performance figure of any real period (its tests use synthetic data
  and print pass or fail; `test_native.py`, run with `EXITFLEX_REQUIRE_REAL=1`, compares booleans). It read: the two review reports as given
  in its task text (findings only); this file and `README_KO.md`; `research/exitflex/metrics.py`, `runner_x.py` (`HUNT_READ_KO`, the claim
  tables, `MIDDLE_VARIANTS`, `causality_pair`, `check_t5`) and the parts of `test_exitflex.py` it changed; `candleague/exits.py`,
  `candleague/rulex.py` (`RuleMixin`, `make_engine`, `accounts`, `chunk_rule`), the lines of the league's `runner.py` that set `rx_seen`, and
  the three test files; the commit times of `git log` for the study folder (times only). It opened no performance figure of any period, no
  `holdcost`, hunt, autopsy, league or track-2 result, no `out/` file and no DeepSeek money figure. It did not touch the main session's
  statement or the dated addendum below it.
* **The eighth pass** (2026-10-12, by the main session; 16.7) ran, in a scratch git worktree of `fe7a34f` (`scratchpad/exdry`,
  work folder `scratchpad/exdry_work`) on a scratch pin that was never committed, `make-pin`, `pin-lines`, `check` (T1, T5, T8, T3
  on the real arrays), `make-cut` and `timing` (hashes, pass or fail, counts of cases, seconds), and one probe that printed E0's
  offered signals (1,542) and entered trades (92) at quarter size on core-DOGE-15m-1 in the select period (a look under 14, E0
  only); that worktree and its work folder were deleted on 2026-10-12. With this pass's code (`fd070f8`) it ran `check` for T5 and
  T8 once more, in a second scratch worktree (`scratchpad/ext5`) on a scratch pin that is not committed (counts only; 16.7 item
  2). It edited `runner_x.py` (`check_t5`, `check_t8`, `stage_check`, `run_tasks`, `select_plan`, `finish_confirm`), `metrics.py`
  (`summarize`), `test_exitflex.py` and this file. It opened no per-account result file, no figure of any variant, no `out/` file
  of a real run and no DeepSeek money figure. The fixes of this file after two reviews of the pass's draft (16.7 as it stands)
  were written by a further sub-session under the rules that it edits only this file and `README_KO.md`, edits no code, commits
  and pushes nothing and runs no stage. It read: the two review reports as given in its task text and in its working files
  (findings only); this file and `README_KO.md`; `git diff fe7a34f` of the study folder's code; in `runner_x.py` `gate_pin`,
  `pin_lines`, `real_config`'s refusal lines, `run_tasks`, `select_plan`, `finish_confirm`, `MIDDLE_VARIANTS`, `check_t5`,
  `check_t8`, `stage_check`, `audit_a8_file`, `audit_a9_file`, the stage A8 audit, `A8_SCOPE`, the `progress` lines and the lines
  that read `sent.json`; the names of `metrics.py`'s D11 whitelists; the commit times of `git log` for the study folder; `git
  worktree list`; and file names only in the scratchpad (`exdry_*.log`, `ext5`, `ext5_work`) and `git status` of `ext5`. It opened
  no log, no performance figure of any period, no `holdcost`, hunt, autopsy, league or track-2 result, no `out/` file and no
  DeepSeek money figure. It did not touch the main session's statement or the dated addendum below it.
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

* **Addendum to the main session's statement** (dated; the statement above is unchanged), inserted verbatim (line breaks
  added only):

  ```text
  Addendum, 2026-10-12 ~06:38 UTC (15:38 KST), before the hash: the round-1 trend-hunt results (branch hunt-results,
  pushed 06:32 UTC) were opened. The main session read hunt/wide/RESULTS_KO.md (the wide verdict table: 13 picks, 10
  tested in group 1, none passed), results/README_KO.md and the tail of run.log. Verification sub-agents then read the
  other result files (v1, wide test and select, reads_a, reads_o, fidelity, parity, data and pin manifests) between
  about 06:40 and 07:30 UTC; their summaries were seen by the main session. No hunt number was used for any choice in
  this study. The variant menu, including the chandelier family F4 (a chandelier trail was in the first draft committed
  as eda4740 at 2026-10-12T01:48Z, 4 h before the results existed), is in git history before these results existed.
  The round-1 results contain test-period (2024-01..2026-09) outcomes of chandelier-exit trend systems; Known limit 1's
  chandelier sentence therefore applies and the owners are told so in the select report.
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
  `out/wide/parity.json` only), and the main session stated, at the time of its statement, that it opened no hunt
  result (the addendum above changes that, for the round-1 results). `research/autopsy/LOSS_AUTOPSY.md`
  holds select-period loss-cause tests; whether it covers early exits is not known to the drafters.
* **What follows, applied now**:
  * The first revision's "seen on select" marks on **F3.a** and **F7.N12.a, F7.N24.a, F7.N48.a** are dropped: the
    extras files were not opened, and the grids of F3, F5 and F7 (and the omission of H = 6) were set before any extras
    file existed, not from a number.
  * The select step is **not blind for E0 on the core pool**: per-pick select-period trade counts, per-trade means and
    live-size account multiples, and the E0 basket at live size, were seen. They show the size of E0's select-period
    growth at live size and nothing of any variant. The eighth pass's probe added E0's offered and entered counts at
    quarter size on core-DOGE-15m-1 (16.7 item 1), which show how often E0 entered on that pick and nothing of any
    variant. The deciding size is quarter. Nothing of the DeepSeek pool was seen from `holdcost`.
  * At the time of the statement, Known limit 1's chandelier sentence did not apply (no hunt result opened). **It applies
    from the addendum above** (the round-1 hunt results were opened before the hash); Known limit 1 is rewritten to say so
    and the owners are told in the select report.
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
  14. F12 (section 5.2): the rule for the two-value grids (the larger value), the reading that F6 adds no exit time, the
      bit mask `tr_comp`, group A with parameter count 8, z for the placebo, and "no q15 version". The nine components
      and the middle values are the main session's instruction; these choices are the drafter's.
  15. The reading of "no fixed percent" (section 1): which cells have an arm and which have none, and that F5 and F8 have
      no no-arm cell.
  16. The market-state columns (section 7): the fifth column 모름, the mark 건수 적음 under 100 trades, quarter size
      only, the choice to follow `label_codes` where the docstring of `regimes.py` omits the absolute value of the slope.
  17. The private owner reports (section 3): which figures they hold (no p value; the confirm adds the interval), the
      row rule copied from 8.2 item 6, the `_r2` file names, `ds_owner_report_sha256`, the `freeze_note` field.
  18. The F12 placebo's clock (section 6): a hazard table over the checks before the clock check and a certain exit at
      it, in place of a table over all checks; Known limits 9 and 17, T4 and 16.4 follow.
  19. The redaction of owner words and questions and its marker `[딥시크 금액 삭제]`, `ds_private/owner_messages.json`,
      the place and time at which the private report is shown (`ds_report_shown_utc`, `ds_report_shown_kst` in
      `sent.json`), A8's free-text tripwire and the points at which A8 and A9 run (sections 3, 8.3, 8.7, 13, 14).
  20. The reading of the dashboard (section 3): the league's own screens follow the league's DeepSeek-money setting;
      this study's files carry no DeepSeek money.
  21. "Deeper than 0.5R" (Rc < -0.5, a strict inequality) for F6.d0.5, F9 and category L1, and the `_r2` file names of
      a confirm rerun.
  22. The 8-hour clock of F12 as the reason F10 cannot act on a 1h or 4h pick, and the counts of legs that can act
      (seven or eight, section 5.2).
  23. F13 (sections 5.2-5.4 and 6): the reading that the owners' two messages are the engine's ladder (their 20% -> 15% and 30% ->
      25% are what it gives), only the 10% start; the reading of "the pick's own take-profit kept" as mode a and "the lock alone" as
      mode b; the group P and the parameter count 0; the loss class L0 and membership of the default set D; no placebo, with the
      reason stated; the order of lock, stop and take-profit inside a minute (the kernel's); the claim wording of 8.5; the
      statement that F12 does not contain F13.

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

### 16.4 Final additions (fourth revision: the main session's decisions of about 12:20 KST and the owners' messages 5-7; fifth pass: items 9 on)

1. **New family F12, "all at once"** (1 Q-C, 5.2, 5.3, 6, 7, 8, 9, 12, 13, 14; message 5). The first trigger wins among
   F1, F2, F3, F4, F5, F6, F7h, F10 and F11, with the hard stop kept; every component at the middle of its own grid
   (the larger value for a two-value grid), listed in a table in 5.2; modes a and b; pick-timeframe checks only; own
   group A; outside the default set D (it cuts a loss on any structure break; category L3); placebo by the general
   stratified rule (z = 1 when any component with a precondition is armed or has its reference); one exit when several
   components fire at one check, with every component recorded in `tr_comp`. Tests T2, T4, T5, T6, T7 cover it.
   Counts: variants 84 + 2 = **86** (E0 plus 86 = 87 arms); select step 1 87 x 38 x 2 = **6,612** accounts (was 6,460);
   variants with a placebo 72 + 2 = **74**; step-2 placebo accounts 74 x 23 x 200 = 340,400 and 74 x 15 x 200 = 222,000,
   **562,400** in all (was 547,200); the timing stage and its projection use the 74; the confirm is unchanged (228
   accounts, 15,200 placebo accounts); the default set D stays 35 variants. "84" in this file still means the full
   grid's 84 exits where it says so.
2. **No fixed percent** (1, 12, Known limit 16; message 6). The owners' +60% and -40% were examples. The file states
   that no rule fires on a fixed percent, that arms are in R of the trade's own stop distance, and which cells have an
   arm (F5, F8, F6.d0.5, F9) and which have none (F1, F6.d0, F10; the others have no profit or loss arm). F5 and F8 have
   no no-arm cell; none was added, so the counts are unchanged, and Known limit 16 says the gap is untested.
3. **Hold hours by market state at entry** (7, 8.2, 9, 12 and Known limit 18, 13, 14 A9, T3, T8; message 7). The
   labels of `research/fullgrid/regimes.py` (via `regime5y`), taken at the signal bar with no bar after it, per pool and
   variant: count, median hold and the shares over 4 h, 8 h and 18 h in a second table, select-period trades in the
   select report and confirm-period trades in the confirm report. Information only. Section 13 says where the code
   produces it; T8 tests the labels (causality, definition, bookkeeping); `regime5y.py` and `regimes.py` join the pins.
4. **The hold-hours table of 8.2** now says outright that hold hours (median and the shares over 4 h, 8 h and 18 h) and
   entries against E0 with skipped signals come before the growth column, per pool, for E0 and all 86 variants.
5. **Private DeepSeek owner reports** (3, 7, 8.2, 8.7, 9, 10, 12, 13, 14 A8; the owners' "딥시크 금액 알려주고").
   An owners' relaxation of D11, limited to one private report per step outside the repository, shown by the main
   session in the chat only, with its sha256 committed in `select.json` and `confirm.json`. Committed files and
   committed reports, the ledger, weekly notes and league checks keep DeepSeek as labels, counts, win shares and hold
   hours. The default of 8.4 uses no DeepSeek money; the gates and the confirm test compute as before; nothing the
   owners see changes what a rule does.
6. **The main session's decisions recorded, not reopened**: the stricter default set D and the hold-based default of
   8.4 are accepted; the freeze of 8.3 is accepted, hunt test-period results and track 2 included, and the main
   session times the select report around the hunt (8.3, `sent.json` `freeze_note`).
7. **Consistency pass** over the whole file: variant counts and run counts (above); F1-F11 became F1-F12 in the promises
   and the naming note (the name clash with the DeepSeek strategy F12_MSS_DISP is stated); `run_x.py` became
   `runner_x.py` (the file in the folder); T1-T7 became T1-T8 in 14; A1 and A8 reworded and A9 added; "DeepSeek money
   figures are never a look" corrected (the owner reports are looks); 5.4.2 and 5.4.8 name F12 and 5.4.11 is new;
   section 12's not-in-scope lines and Known limits 2, 9 and 15 updated and 16-18 added; the stop-first sentence of
   section 2, the mode sentence of 5.1, the claims of 8.5 and the files of 8.7 and 9 name F12 and the owner reports; the
   pin table gains the two regime files and the repo-HEAD sentence names this revision; 11.2 and 11.4 items 7 and 13 name
   F12; the order of work names the private reports.
8. **Section 15** gains this revision's reading list and definitions 14-17 (the main session's statement is unchanged).
   **Section 17** is new: the checklist before the hash.

**Not done, and why:**

* F12 with q15 checks, with F8 or F9 as components, or at other values: the owners asked for the nine kinds at once,
  and a second F12 at other values would be a tuned variant. Not done (section 12).
* A no-arm F5 cell (giveback from any profit): the grids were fixed before this revision and the owners did not ask for
  it by name; named as Known limit 16.
* A choice, gate, default or placebo stratum by market state: the owners' remark was that the hold they want depends on
  the market; the columns inform them, and a per-state rule is a new pre-registration.
* DeepSeek p values in the owner report: the owners asked for the money; p values stay private (3).
* Reopening decisions (1) and (2) of the main session: not reopened.

**Choices of this revision that the main session may change before the hash** (each is stated in the text it touches):

* the larger value for a two-value grid in F12 (g = 0.5, d = 0.5 R, N = 12 bars; 5.2);
* the instruction that "every gate still uses no DeepSeek money": in this file the DeepSeek gates 1-3 and the confirm
  test still compute from the private DeepSeek money files as before (D11 had always said so), and only the default of
  8.4 is money-free; the text says the owners' view cannot change what a rule does (3);
* the private reports hold no p value and, in the select report, show money only on choosable rows (3);
* 건수 적음 under 100 trades for the state cells, and quarter size only (7).
* (fifth pass) the F12 placebo carries F12's clock (6, item 11 below); the league dashboard follows the league's own
  DeepSeek-money setting (3, item 21 below). **Both were confirmed by the main session on 2026-10-12** (section 17 items 6
  and 7; 16.6 item 6).

**Fifth pass (two reviews of the fourth revision; items 9 on).** Each item answers a finding. All blockers and majors
are fixed; the cheap minors are fixed; what was not done is listed after the items. The list of what must still be done
before the hash is section 17.

9. **Redaction of the owners' words and of the main session's questions** (3, 8.3, 9, 11.1, 13 T7 and order of work, 14
   A8). The blocker: 8.3 required every owner message and every main-session question verbatim, and 9 and 11.1 wrote
   the owners' words into `REPORT_KO.md` and a `DEVIATIONS.md` entry, while the owners will have just read the private
   DeepSeek report and may quote a figure from it (the monthly growth of one DeepSeek variant, say, with "take it");
   A8 and T7 scanned only four files, so nothing would have caught it. Now every DeepSeek money figure in such a
   message is replaced by `[딥시크 금액 삭제]` before it is written to any committed file, the rest stays verbatim, the sha256 of the unredacted text goes to a
   private file, the main session's questions quote no figure and name variants by id, and the last line of every
   private report asks the owners to do the same. A8 scans `choice.json`, `choice_r2.json`, `sent.json`, the other `_r2`
   files, the ledger print, both `DEVIATIONS.md` files and the weekly notes, with a free-text tripwire; T7 tests the
   tripwire and the redaction.
10. **The audits run at the report stage** (13 order of work, 14). A8 and A9 run on each file after it is written and
    before it is sent or committed, `REPORT_KO.md`, the ledger print, the rerun files and the `DEVIATIONS.md` entries
    included. Step 5 of the order of work had run the audits before the report existed.
11. **The F12 placebo carries F12's 8-hour clock** (6, 8.1, 8.5, 12 Known limits 9 and 17, T4). F7h at 8 hours stops
    every F12 hold, but the age-bucket hazard did not know it: on 25 of the 38 picks (15m 5, 30m 8, 1h 12) the clock
    check is the top check of an age bucket, the buckets above it hold no F12 position (h = 0), the placebo left at
    about 1/16, 1/8 or 1/4 per check inside the bucket, and about a third of its positions then ran on for days. Three
    remedies were offered: (a) give the placebo the same clock and build the table from the checks before it; (b) set
    h = 1 above F12's cap; (c) drop the F12 placebo and treat F12 like F7 and F7h. **(a) is adopted**: the clock check
    leaves the table, and the placebo exits with probability 1 at it, so its holds never exceed F12's and Q-C's
    comparison (stacking against random leaving, with the same clock) stays. (b) was not adopted because it still
    spreads the clock exits over the bucket and ends the placebo one check after the clock, not at it. (c) was not
    adopted because it drops the second half of Q-C. **The main session confirmed option (a) on 2026-10-12** (section 17 item 6;
    16.6 item 6): the text, the code and the tests stand as they are.
12. **Which F12 legs can act** (1 Q-C, 5.2, 8.5, 12 Known limit 17). F6 never moves the exit and F10 at 12 bars cannot
    fire before the 8-hour clock on a 1h pick (12 h) or a 4h pick (48 h): at most seven legs can end a trade on 25 of
    the 38 picks and at most eight on the other 13. "The other eight can each fire" is gone; Q-C, the claim of 8.5 and
    Known limit 17 say it, and the F12 component counts are split by pick timeframe in the reports.
13. **The market-state definition is worded as the code** (7, Known limit 18). The pinned `regime5y.regimes(...)["code"]`
    is the definition and the prose only summarises it; the coin is the traded coin; the window is a bar count,
    round(365 x 1440 / tf_min); ATR is the module's own `adx_atr`; 모름 also covers DOGE until about 6 January 2021.
14. **The pin** (13): the sha256 of `data_pin.json`; `<pin8>` its first 8 hex digits; `PREREG_EXITFLEX.sha256` is not
    the pin, because it grows after it.
15. **How the private report is delivered and when the clock starts** (3, 8.2, 8.3, 8.7, 13): "the conversation" is the
    chat with the main session and nothing that is logged, synced or forwarded; the report is shown in the same turn
    as, or before, the sending of `SELECT_KO.md`, which starts the 48 h clock; `sent.json` records when it was shown.
16. **The confirm interval of a DeepSeek pair** (3) is kept and named as a coarse stand-in for a one-sided p; README_KO
    lists it.
17. **Stale statements** (17): the "asserts 76 today" clause is deleted, and the places where "84" means the full grid's
    exits now include 8.3 and 12.
18. **The placebo key and F12's z** (6, T4): the coin index is the position in the priority order and the key time is the
    close of the latest closed chart bar of the check; F6's precondition adds nothing to F12's z.
19. **D11 lists and rerun names** (3, 13, 14): the F12 component counts (split by timeframe) are allowed fields; the
    rerun files (`select_r2.json`, `SELECT_KO_r2.md`, `sent_r2.json`, `confirm_r2.json`, `REPORT_KO_r2.md`, and privately
    `owner_report_<stage>_r2.md`, `select_ds_r2.json`, `confirm_ds_r2.json`) are named, with the same
    `ds_owner_report_sha256` field.
20. **Loss depth wording** (front matter, 1, 5.2, 5.3, 8.4): "a loss deeper than 0.5R (Rc < -0.5)" replaces "at least
    0.5R" for F6.d0.5, F9 and category L1, because those rules fire on a strict inequality. The sentence that "the list
    order orders the label shown" is replaced by "the reports print component names in bit order".
21. **The league's own screens** (3, 11.4 item 2, 11.5). The earlier text promised no DeepSeek money on the weekly
    dashboard, which has been false since the owners' request of 2026-10-11 (`CANDLEAGUE_DS_MONEY` is on by default).
    Now the league's dashboard, snapshots and Telegram notices follow that setting, which this study neither changes nor
    relies on, and D11 governs what this study writes and sends: committed files, reports, weekly notes, checkpoint
    reports and the check script's printout.
22. **Appendix A.1's Korean line** said the friend's exit rule was kept "as it was"; it uses the signal exit only and
    not the trailing stop. The line says so now.
23. **README_KO** was rewritten for the owners: a "what you must do" box (answer by id, the 계열 rule, `.a` and `.b`,
    a sample reply, the 48 h clock, what "없음" and no answer mean), why quarter size decides and what live size is,
    the chance flattering of the best of 86 rows, what the restart costs and a rough calendar, the warning on mode
    (b), which F12 legs can act, the corrected DOGE, dashboard, interval and disclosure sentences, the limits that were
    missing (static inputs, stop-first, taker against maker, both pools "없음" ends the study), and less internal detail.

**Not done, and why (fifth pass):**

* Moving the appendix of README_KO to its own file: this pass may edit only two files. The appendix stays, with its
  intro corrected.
* Asking the owners whether the restarted league's dashboard should hide DeepSeek money: the text now says the dashboard
  follows the league's setting; whether to ask is the main session's decision (section 17).
* Dropping the confirm interval from the DeepSeek private report: not done; it is kept and named for what it is (item
  16).
* The free-text tripwire of A8 is a pattern, not a proof; it cannot find a figure written in words. The redaction is
  the main session's duty at run time (section 17, item 20), and the audit is the second line.
* Nothing in the reviews' "consistent" list (counts, hashes, cross-references, F12's tie rule) was changed.

### 16.5 Pin-time alignment

Made on 2026-10-12 (UTC), after the code was built and before the pin, by a sub-session that edited only this file and
`README_KO.md`, committed and pushed nothing, ran no stage on real data and opened no performance figure. It read
`runner_x.py`, `data_x.py`, `kernel_x.py`, `placebo.py`, `metrics.py`, `native.py`, `native_ds.py`, both test files of
the folder, `tests/test_exitflex_league_parity.py` and the headers and relevant functions of `candleague/rulex.py` and
`candleague/runner.py`; ran `runner_x.py pin-lines` and `--help`; and ran the tests on synthetic data (156 passed in
`test_exitflex.py`; 288 passed and 83 skipped in `test_native.py`, run without the 1m folder so that its real-bar tests
skip; 380 passed in `tests/test_candleague_rulex.py` plus `tests/test_exitflex_league_parity.py`). No rule that decides
a result (the engine, the variants, the placebo, the gates, the default, the confirm test) was changed; every item below
makes the text say what the code does or how the study is run. The main session's statement in section 15 is unchanged.

1. **Section 13: the pins, `make-pin`, `make-cut`, the stage chain.** The pinned-files paragraph and the table now
   match `REQUIRED_PINS` of `runner_x.py` and what `pin-lines` prints: this file, `data_pin.json`, all nine `.py` files
   of `research/exitflex/` (`test_native.py` through the rule for the folder's `.py` files, the other eight in
   `REQUIRED_PINS`), and 25 inputs. The table gains eight inputs that fix every account and were not listed
   (`research/fullgrid/grid.py`, `memo.py`, `paperbot/config.py`, `ladder.py`, `margin.py`, `levrule.py`,
   `entry_marks.py`, `sweepsig.py`) and the file `research/entry_study/DEFS_BC.sha256` as a row of its own;
   `fg1m/build.json` and the coin files are said to be pinned through `data_pin.json`. The pin file has 35 lines now and
   36 once `make-pin` has written `data_pin.json`; it does not list itself or `README_KO.md`. New "The stages as built":
   `make-pin` (and its refusal to overwrite a pinned `data_pin.json`), `pin-lines`, the gate every later stage passes,
   `make-cut` as a separate step (the select and timing processes only open and verify the cut folder, and start
   `make-cut` as a child process when it is missing), and for `timing`, `select`, `report`, `choice`, `confirm`,
   `confirm-report`, `check`, `audit` and `audit-file` the stage order and each refusal as built (report is read-only;
   `--rerun` needs a `DEVIATIONS.md` entry naming `select_r2` or `confirm_r2`; `choice` refuses when `choice.json` is
   pinned; `confirm` refuses on a changed module hash or engine fingerprint, on an incomplete menu, on an existing
   `confirm.json`). The paragraph "Code must match this revision before the pin" became "Code and this revision". The
   tests paragraph says where the tests live (A1 reruns `test_exitflex.py` only; `test_native.py`'s real-bar tests skip
   without the 1m folder and need `EXITFLEX_REQUIRE_REAL=1` at the pin; the league parity test is separate). The cache
   stage list gains `check`; the order of work gains `make-pin`, `pin-lines`, `make-cut`, and puts the `timing.json` hash
   before the select run (8.7 follows).
2. **Sections 7, 8.2, 8.7, Known limit 11: pooled rows, not per-pick tables.** The sentences that promised hold time,
   entries, skipped and rejected signals "per pick and pooled", and the live-size, changed-trade, reason, win-share,
   drawdown, hazard and placebo lines "per pick", now say what `select.json` and `confirm.json` carry: pooled numbers per
   pool in every row; per-pick numbers only in the per-account result files, which nobody opens. The one per-pick
   number in a committed file is M_p of each core pick on a choosable core row (`Mp`). A variant's drawdown and final
   multiple are in no committed select file (E0's median is in `select.json`, the core pairs' medians in
   `confirm.json`); the placebo's hold statistics per seed stay in its result files. 8.7 now says that the growth of the
   "선택 불가" core rows goes to `results/select/core_not_choosable.json`, outside the repository, not into
   `select.json`. Known limit 11 no longer speaks of a "pick table".
3. **Section 11: the league restart as built.** 11.1 names the `enabled` field of `candleague/data/rules.json` as the
   switch. 11.2 gives the account counts recomputed from `rulex.accounts` on the 38 picks: 190 with a new exit in both
   pools (`-n`, `-nq`, `-e`, `-eq`, `-nflip` per pick), 160 core only, 144 DeepSeek only, 114 with neither; one league,
   one database, no side league. 11.3 says that the start is guarded by `CANDLEAGUE_EXPECT_START` before anything is
   written (the text said "after the first pass"), that no code switch sets aside the kept start (the old database and
   start file are moved away), and the name of the database copy `candleague backup` makes. 11.4: the "draft" paragraph
   is replaced by what is built (module and function names, the first draft's `rule_league.db`, `-f` accounts and
   `register_f11` gone), the items say "first draft" where they described it, a status table gives each of the 14 items
   as built (item 13 built on synthetic data only, the archive run open; item 9: the C1 command prints
   `no_entry_from_ms` and does not edit the rules file), and a **restart to-do** list names the pin-file, install-script,
   unit-file, environment-file and backup-environment changes that are made at restart time and are not pinned here.
   11.5 names the command `python -m candleague.rulex checks c1|c2|repeat` and says that C1's output is copied into the
   rules file by hand.
4. **Section 15: the hunt read.** A dated addendum (2026-10-12 ~06:38 UTC, 15:38 KST) stands below the main session's
   statement, verbatim as given to this sub-session; the statement block itself is unchanged. Known limit 1 is rewritten
   (the chandelier sentence applies; F4's confirm and F12's chandelier leg are knowingly a second look at chandelier
   exits on 2024-2026; no hunt number was used for any choice; the owners are told in the select report); two sentences
   of section 15 outside the block that said "no hunt result opened" now say "at the time of the statement"; the front
   matter names the addendum; README_KO's disclosure carries it. `runner_x.py`'s `select_report_ko` has no line for it:
   17 item 4a.
5. **Status and calendar.** A status line at the top of this file reads: pin commit, see the commit message of the commit
   that adds `PREREG_EXITFLEX.sha256` (no placeholder; no "draft" or "under review" wording was left that would be false
   at the hash; the first-draft and revision history lines stay as history). README_KO's calendar of days and dates is
   replaced by hours: rule fixed, calculation about 8 hours, results table, the owners' choice, one confirm, new bot
   start; the 8 is the limit of the timing rule of 5.3 (above 8 hours projected, the placebos run 100 seeds instead of
   200), no new measurement.
6. **Section 17.** Every item that is now true is ticked, partly true items are marked and point to the list "Open for
   the main session" (O1-O6: the text decisions 4a, 6 and 7, the pin time, the tests on the files to be pinned, `make-pin`,
   the pin file and the pin commit, then `check`, `make-cut`, `timing` and the `timing.json` hash). Item 1's grep text
   names 16.5; item 9 is rewritten for the hours; item 10 says that `variants()` returns 86 (the module holds 82 and
   adds 4 when the F11 provider is registered); item 15 gains the built `make-cut` step and the refusals; new item 4a.
7. **Counts and grep sanity.** The code gives 86 variants, 87 arms, 6,612 step-1 accounts, 74 with a placebo, 35 in D,
   340,400 + 222,000 = 562,400 placebo accounts at most. `grep -n "84 variants\|E0 plus 84\|6,460\|547,200"` prints
   lines of 16.4, 16.5 and 17 item 1 only; "76", "78" and "72" appear only in history lines or mean something else; "6,004"
   appears nowhere; the other "84" are the full grid's 84 exits.

**Found while aligning and left as it is:** the install script's `CODE_PATHS` and `backup` environment (11.4, restart
to-do); the parity test over 60 days of archive data (11.4 item 13); `select_report_ko` without a hunt line (17 item
4a); the C1 command that prints rather than writes `no_entry_from_ms` (11.4 item 9, restart to-do). The addendum of
section 15 says that verification sub-agents read files "between about 06:40 and 07:30 UTC"; this sub-session's
machine clock read 07:14-07:28 UTC while it worked, i.e. before the 07:30 of that sentence, which may be an estimate. The
sentence is the main session's own wording and is not edited here; the main session may check it before the hash.

### 16.6 F13 and final items

Made on 2026-10-12 (UTC, afternoon), after the owners' two messages 8 and 9 and before the hash, by a sub-session working under the
rules of section 15 (the sixth pass): it edited the study folder's `.py` files, this file, `README_KO.md`, `candleague/rulex.py`,
`candleague/exits.py` (rules added; the 84 existing names and what they do are byte-identical, which a test checks by a sha256 of
`EXITS`, `TP_RULES`, `STOPS`, `LIVE_EXIT`, `TP_KO`, every `exit_ko` and every `spec` computed on the commit before) and three test
files; it committed and pushed nothing, created no `data_pin.json` and ran none of `make-pin`, `make-cut`, `select`, `timing` and
`confirm`. It printed and saved no performance figure of any real period (the tests use synthetic data and print pass or fail;
`test_native.py` was run with `EXITFLEX_REQUIRE_REAL=1`, whose real-bar tests compare booleans only). Every change, in order:

1. **New family F13, the stepped lock** (1 Q-D, 5.1, 5.2, 5.3, 5.4 item 12, 6, 7, 8, 9, 12 and Known limit 19, 13, 15 definition 23).
   The rule bot's own `LadderSpec` (first lock 0.10, step 0.05, trigger gap 0.02; best net ROE 12% -> lock 10%, 17% -> 15%,
   22% -> 20% ...), two variants: F13.a (the pick's own fixed take-profit kept and the lock added) and F13.b (no fixed
   take-profit, the lock alone: the rule bot's exit). The pick's hard stop stays in both. The lock is the kernel's: net ROE after
   costs on isolated margin, applied from the next minute, only tightening. Only the 10% start (no 5% or 20% start). In
   `kernel_x.py` it is the exit arguments of `exit_of_pick` `(stop_atr, tp kind or TP_NONE, tp value, True, 0.10, 0.05, 0.02)`
   with `rp` E0's vector (family 0; see 5.2); the constants are asserted equal to the kernel's "ladder" row. Group P; parameter count 0; loss class
   L0 (it can cut only after a gain); in the default set D; **no placebo** (its exit is an intrabar price-level stop, not a decision
   at a chart close; it is treated like F7 and F7h in eligibility, with the reason stated in 6 and z = 0 where a table needs a
   value); the claim of 8.5 is the one the owners were promised in words, with the limit of 5.2 added in the seventh pass (item 12
   below): "closes by the engine's stepped profit lock: after +12% net ROE it never gives back below +10%, except by the slippage of a
   stop and at a gapped open, which can lie anywhere; it reads no structure and makes no claim beyond that". **F12 does not contain
   F13** (5.2, 1 Q-D, 12).
2. **Counts recomputed** from the code (`kernel_x.variants()` with the F11 provider registered): **88 variants** (was 86: 82 of
   F1-F10, 2 of F11, 2 of F12, 2 of F13), **89 arms** (was 87), step-1 accounts 89 x 38 x 2 = **6,764** (was 6,612), variants with
   a placebo **74** (unchanged: F13 has none), placebo accounts 340,400 + 222,000 = **562,400** (unchanged), confirm 228 accounts
   and 15,200 placebo accounts (unchanged), the default set D **37** variants (was 35). The places that carried the old numbers
   (5.3, 8.2, 8.6, 12 Known limit 2 and 18, 13, 16.4 and 16.5 as history, 17 and README_KO) read the new ones; 16.4 and 16.5
   keep their numbers because they describe those revisions.
3. **The stepped lock is the one fixed percent of the study** (1, 12): the sentences "no rule fires on a fixed percent" now say
   "except F13", Not in scope lists the lock as an exception, and Known limit 19 states what F13 is not (not tuned, not other
   starts, not size-free, wick-sensitive, no cap on holds in mode b).
4. **League side** (11.2, 11.4): `candleague/exits.py` gains `LOCK`, `lock_exit` ("tp3R|4" -> "lock+tp3R|4", "roe50|4" -> "lock+roe50|4",
   "tp2R|2" -> the existing "ladder_tp2R|2", mode b "ladder|k"), `known`, `exit_ko` and `spec` for the "lock+" names, and `LadderTP`
   takes a net-ROE take-profit (`roe`, the engine's `tp_from_roe` on the fill and the leverage). `candleague/rulex.py` gains the family F13
   (`LOCK_FAMILIES`, `lock_ids`, `exit_name`): the accounts `-n`, `-nq` and `-nflip` run the lock exit on the plain engine, nothing
   else changes, the account ids and counts are as before (190, 160, 144, 114), `chunk_rule` hands them no chart record, `audit_restored`
   skips them, the fingerprint carries the rule and the lock's numbers, `ids --all` lists 88. `runner.py` and `league.py` needed no change.
5. **Tests.** `test_exitflex.py`: the reference simulator gains the lock written with `paperbot/ladder.py`; T1 for the F13 exit arguments
   (every fourth pick exit, both modes, both sizes, both worlds) and for F13.b = "ladder|k" and F13.a on 2R = "ladder_tp2R"; T2 hand paths
   (the bands 12 -> 10 through 42 -> 40, two pick exits, both sides; wick; same-minute stop; lock and take-profit; funding; mode b; no lock
   below 12%) and a differential test against the reference; T4 (no placebo, a refused placebo run, gate 3 not applicable, never a step-2
   pair); T5 (the stop in force at minute j depends only on earlier minutes); T7 (group P, L0, set D 37, order 1-88, the claim, the default can
   take F13); the registry and runner tests read 88 / 74 / 37. `test_candleague_exits.py`: the 84 rules byte-identical, `lock_exit`, kernel
   parity for the lock exits (including the net-ROE take-profit), a restart in the middle of a locked position. `test_candleague_rulex.py`:
   the F13 ids, accounts (ids and counts unchanged), engines, a hand path, a restart, `chunk_rule` without records, the league end to end.
   `test_exitflex_league_parity.py`: F13.a and F13.b at both sizes and as coin flips against the study's kernel in every combination, restarts
   in positions whose lock is raised, and a negative control for a restore that forgets the lock.
6. **The pin-blockers of section 17 closed.** (4a) `select_report_ko` and `confirm_report_ko` of `runner_x.py` carry a fixed line, `HUNT_READ_KO`,
   telling the owners that the round-1 hunt results (with test-period outcomes of chandelier-exit trend systems) were opened by the main
   session before the hash and what the addendum of section 15 says; a test checks it in `SELECT_KO.md` and `REPORT_KO.md` and that it passes
   audit A8; the sixth pass did not change Known limit 1 (the seventh pass adds the F13 exception to it, to 17 item 4a, to `HUNT_READ_KO` and to README_KO: item 11 below). (6) The main session **confirmed option (a)** for the F12 placebo on 2026-10-12 (16.4 item 11,
   section 17 item 6). (7) The main session **confirmed** that the league's dashboard, snapshots and Telegram notices follow the league's own
   DeepSeek-money setting and that this study's files carry none (3, 11.4 item 2, 11.5; section 17 item 7); the owners are not asked.
7. **The "Repo HEAD" sentence of 13** now reads: the parent of the commit that adds `PREREG_EXITFLEX.sha256` (see `git log`); the repo is
   auto-committed. It stays true whatever commits come before the pin commit.
8. **Section 17 and README_KO.** The items are updated to the numbers above (1, 5, 10, 12, 16), items 4a, 6 and 7 are ticked, the list O1 says
   that the text is final except for `README_KO.md`. README_KO names 13번, the 88 variants, the stepped lock in plain Korean ("규칙봇 계단 잠금:
   12%→10%, 17%→15%, 22%→20%..."), its claim, that 12번 does not contain it, the exception to "no fixed percent", and the hunt-read line.
9. **Not changed.** The main session's statement in section 15 and the dated addendum below it are byte-identical (a `git diff` shows no
   change inside those two blocks). No rule that decides a result of E0 or of a variant of F1-F12 was changed; no pinned input of the table in
   section 13 (`paperbot/ladder.py`, `research/fullgrid/kernel.py` ...) was edited, and `pin-lines` was recomputed for the changed files of the
   folder only.

10. **Test results of this pass** (working tree, 2026-10-12, synthetic data; counts only): `test_exitflex.py` 211 passed;
   `test_native.py` with `EXITFLEX_REQUIRE_REAL=1` 371 passed, 0 skipped; `tests/test_exitflex_league_parity.py` 291 passed;
   `tests/test_candleague_*.py` 335 passed. `runner_x.py pin-lines` prints 35 lines; the 25 first-8-hex entries of the table in
   13 are unchanged (none of the 25 input files was edited). The stale-number greps of 17 item 1 print history lines only.
   The restarts of the parity test that sit in locked positions are put one millisecond before the exit minute of a lock exit
   (the study stamps a minute by its open, the league's bars by their close); the negative control for a restore that forgets
   the raised lock fails the comparison there, which restarts five minutes earlier did not.

**The seventh pass: fixes after two reviews of the sixth pass** (2026-10-12, the same afternoon, before the hash; a further sub-session under the
rules of section 15 with the limits of the sixth: it committed and pushed nothing, created no `data_pin.json`, ran none of `make-pin`, `make-cut`,
`select`, `timing` and `confirm`, and printed and saved no performance figure of any real period). Items 11-20 are its changes, item 21 its test
results and item 22 what it did not take.

11. **The disclosure is exact about F13.** The sixth pass said that the exit menu was in git before the hunt results existed; that is false for
    the two F13 variants. F13 first appears in git at about 07:51 UTC, the hunt results having been opened from about 06:38 UTC. Known limit 1, 17
    item 4a, `HUNT_READ_KO` of `runner_x.py` (the line at the top of `SELECT_KO.md` and `REPORT_KO.md`) and README_KO's disclosure bullet now say:
    the menu was in git before the results existed **except F13**, which was added after the hunt read at the owners' request (their messages 8
    and 9) from the rule bot's own ladder, `paperbot/ladder.py`, and no hunt number was used for it. The test of `HUNT_READ_KO` checks the new
    clause. The dated addendum of section 15 (the main session's own words, byte-identical) says that "the variant menu ... is in git history before
    these results existed"; read it together with this item: it predates F13 and is not edited.
12. **The F13 claim carries the limit of 5.2.** "Never gives back below +10%" overstated what 5.2 itself says: the exit lies at or above +10% less the
    slippage of a stop (about 0.6 points of ROE at 30x, 1 point at 50x), or at a gapped open, which can lie anywhere, and the minute that arms the
    lock is unprotected because the new stop applies from the next minute. The owners' words are kept and one clause is added (8.5, T7 in 13, item 1
    above): "... except by the slippage of a stop and at a gapped open, which can lie anywhere ...". `metrics.CLAIM_F13`, `runner_x.CLAIM_KO["f13"]`
    (in Korean: "손절이 체결될 때의 미끄러짐과, 다음 봉이 잠금선 아래에서 갭으로 시작하는 경우는 예외"), README_KO and the T7 test string changed
    together. A main session that prefers the owners' words alone takes that clause out of these places; nothing else depends on it.
13. **`rp` of F13 is E0's vector** (family 0), not "the zero vector": `rp_vector()` holds F12's component mask (511) in its last entry, which
    family 0 never reads. 5.2, 13, T1, item 1 above and 17 item 10 say so. The test asserted equality with `rp_vector()` already; no code changed.
14. **T5 and F13** (13): F13.a and F13.b were in the real-data T5 list (`MIDDLE_VARIANTS`), but `causality_pair` skips a trade without a check, which is
    every F13 trade, so every F13 sample was dropped. They are taken out of the list (18 variants; the sample per pick and variant, 2, is the same), and
    T5 says that F13's causality is checked on synthetic paths only. A test pins the list.
15. **No gate 3 for F13**, wording: T7 ("F7, F7h and F13 exempt from gate 3"), 17 item 11 and the docstrings of `metrics.eligibility`,
    `metrics.gate_failure_counts` and `metrics.confirm_verdict` named only F7 and F7h; F13 is added. The parameter `is_f7` of `eligibility` and
    `confirm_verdict` is renamed `no_gate3` (every caller passes it by position). The behaviour was right already (`runner_x.no_placebo_gate`).
16. **F13 and the C1 stop** (the league; a review probe found that an F13 pool stopped by C1 went on opening trades). `rulex.make_engine` returned
    the plain engine of the lock exit for F13, without the `RuleMixin` gate that refuses a new entry from `no_entry_from_ms` (11.4 item 9), and it
    never set the field, although `accounts()` puts it on the `-n`, `-nq` and `-nflip` accounts and the fingerprint covers it. F13 accounts are now
    `LockEngine` (exits on a `PaperEngine`) or `LockLadderEngine` (exits on `LadderTP`): the `RuleMixin` classes with `rx_rule` None, so `step` and
    `submit` are the plain engine's, with `rx_no_entry_from` set from the account. `candleague/exits.py` is unchanged. Tests in
    `tests/test_candleague_rulex.py`: the engines of the F13 accounts (class, settings, policy, take-profit fields against `exits.make_engine`), an
    F13 version of the "no new entry from a time" test (both modes, both sides: refused at the stop time, an entry before it closes by its lock, a
    later signal refused, a control without the field) and of the start-over test (league, F13.a, three days); both fail without the fix (mutation
    check). The parity test still passes: the gate refuses only entries at or after the stop time. Account ids, counts and the fingerprint are unchanged.
17. **The lock + net-ROE take-profit is now in the league parity.** In the 30m "roe50|4" combination F13.a has one take-profit exit per size, which did
    not carry the price of the lock's net-ROE take-profit (a mutation of `tp_from_roe` in `exits.LadderTP` passed all 291 tests of the file). The
    parity test gets a combination "30m-roe20" ("roe20|2", F13.a and F13.b, E0) in which F13.a closes eight to ten trades per size at the take-profit,
    most of them after the lock was raised, and a test that counts them and compares each with the study; the same mutation now fails two tests of the file.
18. **Known limit 19 (h)** and README_KO: F13.b is the full grid's row "ladder|k" and F13.a on a 2R pick is "ladder_tp2R|k"; those rows are among the 84
    exits on which E0 was chosen and whose 2024-2026 per-trade results the owners saw. The select result of F13.b is tilted against it by E0's plateau
    selection, and its confirm is not independent of the grid. No number changes.
19. **Provenance of 17 items 6 and 7.** The two decisions are ticked "CONFIRMED on 2026-10-12" on the strength of the main session's brief of that day,
    which the sixth pass could not check elsewhere; item 7 says so and asks the main session to read items 6 and 7 against its own decisions before the
    hash. They are not changed in substance.
20. **Noted, not changed.** The sixth pass changed the `metrics.loss_class` docstring from "at least 0.5R" to "deeper than 0.5R" (it agrees with
    15 definition 21, a strict inequality; no code changed). `git diff` of the study folder against the commit before the sixth pass also shows
    `research/hunt/POWER_R1_KO.md` and `RESULTS_R1_SELECT_KO.md`: they came from other auto-commits, not from this build.
21. **Test results of the seventh pass** (working tree, 2026-10-12, synthetic data; counts only): `test_exitflex.py` 212 passed (was 211; one test
    added); `EXITFLEX_REQUIRE_REAL=1 test_native.py` 371 passed, 0 skipped; `tests/test_exitflex_league_parity.py` 295 passed (was 291: the combination
    "30m-roe20" and its test); `tests/test_candleague_*.py` 340 passed (was 335: five tests added to `test_candleague_rulex.py`, 134 now, with
    `test_candleague_exits.py` at 32). `runner_x.py pin-lines` prints 35 lines; the 25 first-8-hex entries of the table in 13 are unchanged (none of the
    25 input files was edited).
22. **Not taken.** Nothing in the two reviews was rejected. Where a review left a choice (the claim wording, the T5 list), item 12 and item 14 say what was
    chosen and why.

**Not done, and why (sixth pass):**

* A 5% or 20% lock start, other steps or trigger gaps, a lock on the structure rules, F13 inside F12, a tenth component of F12, a q15
  version, a placebo for F13: the owners asked for the 10% start only (messages 8 and 9) and F12 was fixed before this request; each of
  the others would be a new pre-registration (12).
* A change of any pinned input or of the engine's ladder: F13 uses the engine's numbers as they are.
* The parity test of the league over 60 days of archive data, `make-pin`, the pin file and the pin commit: unchanged open items (section
  17, part F).

### 16.7 Eighth pass (2026-10-12, by the main session, after a dry run)

1. **Dry run.** In a scratch git worktree of commit `fe7a34f` with a scratch pin (a `data_pin.json` and a 36-line pin file that were never
   committed; the work folder in the session scratchpad), `make-pin` printed `build.json` 824c9d1a and the six coin hashes of section 2,
   and `pin-lines` printed 36 lines. `check` gave: T1 pass on all 38 picks; T5 core 750 pairs, 0 failed, and DeepSeek 285 pairs, 0 failed;
   T8 core 506 and DeepSeek 510 signals, 0 failed; T3 pass at all 21 cut times (about 55 minutes). `make-cut` passed its digest check
   and `timing` ran (E0 about 0.01 s on the timing pick; the projected step 2 lies far under 8 hours, so 200 seeds). Only pass or fail,
   counts and seconds were printed. To explain a timing of 0.00 s, one probe printed, for the timing pick only, its number of offered
   signals (1,542) and of entered trades (92) in the select period, and the seconds of one account; no P&L, wallet, growth or other
   result figure was printed or kept, and no other pick was probed. The scratch worktree and its work folder are deleted before the pin.
2. **T5 sampling (code).** The DeepSeek pool reached 285 pairs, not the 500 of the T5 bullet in 13: a drawn trade with no check (it ends
   before its first check, or no size fits it) gives no pair, and one round of `per` draws per pick and variant was not enough.
   `check_t5` now draws, for each pick and variant, until `per` pairs are found, at most 20 x `per` draws (`T5_DRAW_CAP`); `check`
   passes only with at least 500 pairs per pool and none failed (before, more than 0 sufficed, against the 500 of 13). T8 likewise needs
   at least 500 signals per pool. A test is added (`test_t5_draws_go_on_until_each_pick_and_variant_has_its_pairs_and_stop_at_the_cap`).
3. **Two saved fields (code).** `metrics.summarize` also keeps `tr_lev` and `tr_xpx`, the leverage and the exit price of every entered
   trade, in the order of the other `tr_` arrays, for the extra reads of item 4. No decision, table, gate or number of this file reads
   them. The summary test is extended.
4. **Extra reads and twin accounts, in a separate file.** The owners asked on 2026-10-12 for every analysis that helps them (per coin,
   weekday and weekend and session, market state, their goal and risk, the exit mechanics, robustness, timeframe and character, funding,
   sizing, baskets, loss clustering, ROE per trade, figures, the hindsight ceiling, forward bands and sample sizes), and for the
   default-number versions of the 38 picks and the coin flip to be seen **before** they choose. These are defined in
   `research/exitflex/PREREG_EXITFLEX_EXTRA.md`, with their code in their own modules and their own pin file
   (`PREREG_EXITFLEX_EXTRA.sha256`). That file and its pin are committed **before any output of the select stage is opened**
   (`select.json`, `SELECT_KO.md`, any per-account result file, the private DeepSeek report); the select stage prints progress only.
   Its commit time and the select files' times are listed in it. The extra file:
   * defines **reads** that are descriptive only: they choose nothing and change no gate, placebo, Holm, default, ledger, report or
     choice rule of this file; per-coin, per-side, per-session and per-state choices stay out of scope (12);
   * defines **twin accounts** for each pick: the **default-number twin** (the cell's default combo; under E0, which is the pick's own
     exit as in the league's `exitonly` account, under the house exit `ladder|2` as in the league's `base` account, and under the 88
     variants) and the **coin-flip twin** (the pick's numbers and signal times, the side from a seeded coin as the league's flip), select
     period only, no placebo, no gate, not choosable, shown next to the select table before the owners choose;
   * uses this file's pinned kernel, data and cut unchanged and opens no minute of 2024-2026; DeepSeek figures follow D11.
   This file's select report and its rules are unchanged. The owners are told that the extra reads and the twins were defined after this
   file was hashed and are information only.
5. **Test results of the eighth pass** (working tree, 2026-10-12, synthetic data and the real 1m folder for `test_native.py`; counts only):
   see section 17, item 10.

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
* **Korean**: 친구분 원래 청산 중 신호 청산(빠른 EMA가 느린 EMA 아래로, 또는 스토캐스틱RSI K가 D 아래로)만 씁니다. 롱이면
  그런 봉이 마감하면 바로 전량 청산합니다. 원래 있던 따라 올라가는 손절(트레일링)은 봉 안에서 움직이는 규칙이라 이번에는
  쓰지 않습니다. 정해진 익절가는 없습니다.

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

## 17. Before the hash: checklist

For the main session and the coders. This file is hashed, and the pin commit made, only when every line of parts A and B
below is true; parts C and D are the pin itself. Each line is checked by a command, a test or a read. Names of functions
and fields are those of this file (section 13 is the contract); if the coder used other names, section 13 is edited
first. Items marked (5th) were added or changed by the fifth pass (16.4, items 9 on), items marked (6th) by the sixth pass (16.6:
F13 and the final items), items marked (7th) by the seventh pass (16.6 items 11-22: fixes after two reviews). **Marks (16.5, 2026-10-12; updated in 16.6):**
`[x]` true now; `[~]` true in part, the rest being in the list "Open for the main session" at the end of this section;
`[ ]` open. Everything marked true was checked on the working tree by a read, a grep or a test on synthetic data. No
stage was run on real market data: the real-data checks are open items.

**A. Text** (the main session)

1. [x] (6th) The counts read 88 variants, 89 arms, 6,764 step-1 accounts, 74 placebo variants, 340,400 + 222,000 = 562,400
   placebo accounts (5.3) and 37 variants in the default set D. They were recomputed from the code: `kernel_x.variants()` with
   the F11 provider registered gives 88 variants (74 with a placebo, 37 in the default set D). `grep -n "84 variants\|E0 plus
   84\|6,460\|547,200" PREREG_EXITFLEX.md` prints only lines of 16.4, 16.5 and this item, and `grep -n "86 variants\|87 arms\|
   6,612\|35 variants\|35 in D" PREREG_EXITFLEX.md` prints only history lines (16.4, 16.5, 16.6 "was" remarks, and this item).
   The other "84" in the file are the full grid's 84 exits or the kernel's (sections 1, 8.3, 12, 13 T1, 15, 16); "76", "78"
   and "72" appear only in history lines (16.2-16.4, section 15) or mean something else (18 h as 72 bars, F5_BOX's `box_len`,
   a line range in section 15); "6,004" appears nowhere.
2. [x] `grep -n "run_x\|T1-T7\|F1-F11" PREREG_EXITFLEX.md` prints only explanatory and history lines (promise (a), the
   file name note in section 13, sections 16 and 17).
3. [x] Section 15 carries the fourth and fifth revisions' reading lists, and the main session's statement in it is
   unchanged (`git diff` shows no change inside that block). The dated addendum (2026-10-12 ~06:38 UTC) stands below the
   block and does not touch it.
4. [x] The DeepSeek drafter's blindness is still **not stated** (Known limit 10, section 15, README_KO). If the main
   session obtains an explicit statement, it goes into all three places in one edit before the hash; otherwise nothing
   changes.
4a. [x] (6th) **The select report and the hunt read.** The addendum in section 15 and Known limit 1 say that the owners are
   told, in the select report, that the main session read round-1 hunt results with test-period outcomes of chandelier-exit
   trend systems. `select_report_ko` and `confirm_report_ko` in `runner_x.py` now print a fixed line for it, `HUNT_READ_KO`, at
   the top of `SELECT_KO.md` and of `REPORT_KO.md` (the first option of the earlier text: a code change, `test_exitflex.py`
   rerun, pin lines recomputed). It says what the addendum says (the time, what was opened, that test-period outcomes of
   chandelier-exit trend systems are in it, that no hunt number was used for any choice, that the exit menu was in git before
   the results existed **except F13**, which was added after the hunt read at the owners' request from the rule bot's own
   ladder, with no hunt number used for it) and carries no number of any result. A test checks that the line is in both reports and passes audit
   A8. Known limit 1 (with its F13 exception, seventh pass) says "in the select report". README_KO's disclosure line says the same.
5. [x] (6th) `README_KO.md` agrees with sections 1, 3, 5.2, 7 and 8 (it is not pinned): 88 variants; number 12 and which of
   its legs can act; number 13, the stepped lock (12% -> 10%, 17% -> 15%, 22% -> 20% ...), its claim and that 12 does not contain it; no fixed percent; the market-state table; the private DeepSeek report with its confirm interval and
   the redaction of figures in the owners' words; the answer format (id, 계열, `.a` and `.b`, a sample reply); the
   dashboard sentence; quarter size against live size; the winner's curse; the restart cost; the pooled tables (it
   promises no per-pick table); the hunt read in its disclosure; the schedule in hours. (5th, rechecked in 16.5)
6. [x] **Main session's decision, F12's placebo: CONFIRMED on 2026-10-12, option (a).** Section 6 gives the F12 placebo F12's
   own clock (16.4 item 11), and the code and its tests are built that way. Options (b) h = 1 above F12's cap and (c) no
   F12 placebo are not taken; nothing in 6, 8.1, 8.5, Known limits 9 and 17, T4, 5.3's placebo counts or the code changes.
7. [x] **Main session's decision, the league dashboard: CONFIRMED on 2026-10-12** (as recorded by the sixth pass from the main session's brief
   of that day; the sub-session could not check it elsewhere, so the main session reads this item and item 6 against its own decisions before the hash). The league's dashboard, snapshots and
   Telegram notices follow the league's own DeepSeek-money setting (on by default since 2026-10-11) and this study's files
   carry none (3, 11.4 item 2, 11.5). The owners are not asked; 3, 11.4 item 2, 11.5 and README_KO stand as written. The
   setting itself is not changed by this file.
8. [x] The Korean line of A.1 and README_KO's DOGE bullet agree: only the signal exit is used, not the trailing stop.
   (5th; read again in 16.5)
9. [x] README_KO's schedule is in hours, not days (16.5): "규칙 고정 → 계산 약 8시간 → 결과 표 → 두 분 선택 → 한 번 확인 → 새
   봇 시작", with the 8 hours taken from the timing rule of 5.3 (no new measurement). It has no calendar dates. At the pin
   the main session may add the real clock times, and after the timing stage it may replace the 8 by the projected
   hours of `out/timing.json` (seconds and hours only). (5th)

**B. Code in `research/exitflex/`** (the coders; all pinned)

10. [x] (6th) `kernel_x.py`: `variants()` returns the 88 ids of 5.3 (`_VARIANTS` holds the 82 of F1-F10 and asserts it; the 2
    of F11 and the 2 of F12 are added when the F11 provider is registered, which the runner does and requires; the 2 of F13,
    which need no provider, come last; F13 is the exit arguments of `exit_of_pick` with the lock `F13_LOCK`, asserted equal to
    the kernel's "ladder" row, `rp` E0's vector (family 0), group P, no placebo); F7h; the
    F11 mechanics of Appendix A; F12 as in 5.2 (nine components at the table's values, one RULE exit at the first firing
    check, `tr_comp` bit mask, a component mask for tests, pick-close checks only, F12.b keeps the native target); the
    result carries `tr_state`. (5th) **The F12 placebo clock (6):** in a placebo run of F12 the position exits at its
    clock check, the first pick close at or after C0 + 8 hours (a merged check counts when any merged close is at or after
    it), with probability 1 and no draw; the hazard numerator and denominator it returns exclude the clock check and every
    later one. (5th) The result also gives what the runner needs to split F12's component counts by the pick's
    timeframe.
11. [x] `placebo.py`: seed base without the pick id; (5th) key = coin index (the position in `SYMBOLS`, which is the
    priority order BTC, ETH, SOL, DOGE, LTC, BCH) x 2^36 + the millisecond close of the latest closed chart bar of the
    check // 60,000, as the code has it today (T4 pins it on a hand-computed example); strata z of section 6 including
    F12's (F6 adds nothing); no placebo for F7, F7h and F13; F11.b and F12.b keep the native target; (5th) the F12 clock of
    item 10 in the table builder and the runner.
12. [x] `metrics.py`: no "core pool only" header; gates per pool (14 of 23, 9 of 15); `choose_variants` replaced by the
    default of 8.4 (set D of 37 variants, shortest pooled median hold, ties by parameter count then canonical order, at
    most 2 from different groups, only for a pool with no answer, F12 never); groups A and P; (6th) F13 is loss class L0
    and in the set D (37 variants); `claim_of` for F7, F7h, F11, F12 and F13 with the F12 wording of 8.5 (5th) and the F13
    wording; `hold_by_state` used by `pool_summary`.
13. [x] `data_x.py`: `offered` has the `state` column from `regime5y.regimes`; the module's constants are asserted equal
    to section 7's.
14. [~] `native.py` and `native_ds.py` exist and follow Appendix A. Their synthetic tests pass (`test_native.py`, run
    without the 1m folder: 288 passed, 83 skipped); the 83 skipped are the real-bar tests (O3). (6th) Run again in the
   working tree on 2026-10-12 with the 1m folder and `EXITFLEX_REQUIRE_REAL=1`: 371 passed, 0 skipped (booleans only, no
   figure printed); (7th) again after the seventh pass's changes: 371 passed, 0 skipped; the pass at the pin commit is still O3.
15. [x] `runner_x.py`: the required pins include `native.py`, `native_ds.py`, `paperbot/dash/tools/regime5y.py` and
    `research/fullgrid/regimes.py` (and, as built, the eight further inputs of section 13); the second table of 8.2 and
    the F12 component counts, in total and split by pick timeframe (5th), are printed; the private owner reports are
    written under `ds_private/` with `ds_owner_report_sha256` in `select.json` and `confirm.json` (and the `_r2` files,
    5th) and a last line asking the owners to name variants by id (5th); the seed rule of 5.3 counts the 74; audits A1-A9
    with **A8 as rewritten in 14 (5th)**: the file scope (including `sent.json`, `choice.json`, the `_r2` files, the
    ledger print and the `DEVIATIONS.md` entries), the free-text tripwire (`audit_text` or the coder's name) and the
    marker `[딥시크 금액 삭제]`; **A8 and A9 callable on each file before it is sent or committed** (select, sent, choice,
    confirm, report and ledger print, rerun files, DEVIATIONS entries) so that the order of work of 13 can run them
    (5th): `audit-file`; a redaction helper that replaces DeepSeek money figures in an owner message or question by the
    marker and writes the sha256 of the unredacted text to `ds_private/owner_messages.json` (5th); `sent.json` carries
    `ds_report_shown_utc` and `ds_report_shown_kst` and the choice validation reads `sent.json` as 8.3 says (5th); the
    names `confirm_r2.json`, `REPORT_KO_r2.md`, `owner_report_confirm_r2.md` and `confirm_ds_r2.json` for a confirm
    rerun (5th); it prints the git commit and refuses a hash mismatch; the `make-cut` step, the stage chain and the
    refusals of 13 ("The stages as built").
16. [~] `test_exitflex.py` has T1-T8 and all pass at the pin commit: T2 (F12: each component alone, first trigger wins,
    ties, F6 within F1, single-component parity, modes), T3 (with the regime codes), T4 (F12 strata; **F12's clock and
    the key example, 5th**), T5 (F12), T6 (F12 equals F11 with the other eight off), T7 (gates per pool, the default,
    the group rule, `choice.json` checks, the D11 whitelist with the owner-report rules, **the free-text tripwire and
    the redaction, 5th**, the 88 / 74 / 37 counts, `claim_of`, F13 (6th)) and T8 (state labels). They print pass or fail and
    counts only. In the working tree on 2026-10-12: (6th) 211 passed (was 156; synthetic data, about 2.3 minutes); (7th) 212 passed. The pass
    "at the pin commit" is O3. The league side, which is not pinned: (7th) `tests/test_candleague_rulex.py` (134 tests) and
    `tests/test_exitflex_league_parity.py` (295 tests) gave 429 passed in the working tree (6th: 420 of 129 + 291), `tests/test_candleague_*.py`
    as a whole 340 passed (6th: 335), `tests/test_candleague_exits.py` among them with the 84 rules byte-identical.

**C. Pins to compute** (the main session; this is the pin commit itself)

17. [~] `runner_x.py make-pin` has written `data_pin.json` (the seven data hashes and the `$WORK` path). The pin is the
    sha256 of that file and `<pin8>` its first 8 hex digits (13, 5th). The full sha256 of every input in the table of
    section 13 and of every `.py` in the folder and of this file is computed at the pin commit and agrees with the
    abbreviated values in the table. `PREREG_EXITFLEX.sha256` is created and committed and pushed together with the
    files it lists. The "Repo HEAD" sentence of section 13 reads "the parent of the commit that adds `PREREG_EXITFLEX.sha256` (see
    `git log`)" and needs no edit at the pin (16.6 item 7). The machine runs Python 3.11,
    numpy 2.0.2, pandas 2.3.3, numba 0.60.0. **True now:** the 25 inputs of the table agree with `pin-lines` (the
    abbreviated values were compared on 2026-10-12), `fg1m/build.json` has `824c9d1a…`, and the machine runs Python
    3.11.15, numpy 2.0.2, pandas 2.3.3, numba 0.60.0. **Open:** `make-pin`, the pin file and the commit (O4, O5).

**D. The pin time** (the main session)

18. [ ] The main session has chosen the pin time (UTC and KST) and writes it in the pin commit message (the status line
    at the top of this file points to it). It is after items 1-17 are true; before the hold-cost workflow resumes
    (section 15); and such that the select report, about 8 hours of calculation (5.3) plus the audits and commits later,
    does not fall in a window where a hunt (round 1 or 2), track-2 or ledger test-period result is due or needed
    before the choice is hashed (8.3 freeze).
19. [x] No output of this study exists yet: `out/` does not exist in the folder, so there is no `timing.json`,
    `select.json` or `confirm.json`. Changes after the pin go to `DEVIATIONS.md` only.

**E. Duties at run time** (not before the hash; listed so that the main session has them in one place; no box) (5th)

20. The private DeepSeek report is shown only in the chat with the owners, in the same turn as or before `SELECT_KO.md`
    is sent, and the time is written to `sent.json`. Every owner message or question about the DeepSeek pool has its
    money figures replaced by `[딥시크 금액 삭제]` before it is written to a committed file; the main session's own
    questions quote no figure; A8 and A9 run before every commit and every send of a file listed in 14.

**F. Open for the main session** (16.5; in this order)

* **O1. Finish the text. Done in 16.6 (2026-10-12, sixth and seventh pass):** items 4a, 6 and 7 are decided and ticked (the main session reads 6 and 7
  against its own decisions, 16.6 item 19) and the "Repo HEAD" sentence is written; only item 4 (the DeepSeek drafter's blindness statement) would still change the text, and only if a statement
  arrives. After this the file is final: its sha256 is the first line of `pin-lines`, so it is not edited again before the
  pin commit. `README_KO.md` is not pinned and can still change.
* **O2. Choose the pin time** (item 18), UTC and KST.
* **O3. Run the tests on the files that will be pinned:** `python -m pytest -q research/exitflex/test_exitflex.py`
  (T1-T8), and `EXITFLEX_REQUIRE_REAL=1 python -m pytest -q research/exitflex/test_native.py` with `EXITFLEX_FG1M`
  pointing at the 1m folder (0 skipped), which closes items 14 and 16. They print pass or fail and counts only.
* **O4. `python research/exitflex/runner_x.py make-pin --data-dir <fg1m folder> --work <$WORK folder>`**, which writes
  `data_pin.json`; compare the printed `build.json` and coin hashes with section 2.
* **O5. The pin file and the pin commit.** `python research/exitflex/runner_x.py pin-lines` prints 36 lines (35 plus
  `data_pin.json`); write them to `research/exitflex/PREREG_EXITFLEX.sha256`; commit and push the file together with
  every file it lists, with the pin time (O2) in the commit message. This commit is what the status line at the top
  of this file points to.
* **O6. After the pin commit, before the select run:** `python research/exitflex/runner_x.py check` (the real-data parts
  of T1, T3, T5 and T8; pass or fail), `make-cut`, then `timing` (seconds only, `out/timing.json`), append the sha256
  of `out/timing.json` to the pin file, commit and push. The select run (13, order of work, step 3) follows.
* Not before the pin: the owners' choice and the confirm (13), and everything in the restart to-do of 11.4.
