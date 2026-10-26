# Nasdaq-open / time exits for the three live bots — pre-registration

Written 2026-10-26 (UTC) before any arm of this study was run. Nothing in the bots changes; this is analysis only.
The only numbers seen before this file are the ones already published by the earlier studies that the parity checks
below reproduce (V3.9 study, 레인지 봇 FINAL_KO.md / hunt.json F1, 추세판단 봇 recent replay RESULTS_KO.md A1). This file
is committed before the runs; its sha256 goes into the commit message and into results.json.

Owners (10-26): "a position enters at 1 pm, goes sideways for hours, then the Nasdaq cash open (09:30 New York) flips the
trend — shouldn't there be a rule?"

## Arms (the same seven for every bot)

Clock: **M** = every 5-minute bar whose open is 09:25 America/New_York (zoneinfo, DST-aware), Monday-Friday New York
date, not a NYSE full-day holiday of `paperbot/sessions.py NYSE_HOLIDAYS` (it lists 2026-2027 only; 2020-2025 holidays
are treated as open days). The decision is taken at the close of that bar (09:30:00 New York), after that bar's own
exit checks (stop / take-profit / lock / liquidation) and lock step. "First lock reached" = the bot's first ladder lock is
armed by then (V3.9 Toobit plan: best net ROE >= 20 %; 추세판단 봇: >= 11 %); for the 레인지 봇 (fixed take-profit, no
ladder) a position still open has by definition not reached its take-profit. "Net ROE" = the engine's own lock measure:
lev x (side x (price / fill - 1) - round-trip cost - funding paid / notional); "net break-even price" = the price where
that is 0 (the engine's lock price at a 0 % lock).

- **A0** now: each bot as live (as close as the replay machinery gets; limits below).
- **A1** 개장 전 정리: at M, a position that has not reached its first lock is closed at that 5m bar's close (market:
  that bot's taker fee + slippage).
- **A2** 개장 전 본전: at M, a position whose net ROE at that bar's close is above 0 gets its stop raised to the net
  break-even price (never lowered; a locked position is left alone since its stop is already higher); a position at or
  below 0 is left alone. The raised stop applies from the next bar, like a ladder lock. It is not a lock: the bot's
  "before the first lock" rules (추세판단 봇 JUDGE / REV, time arms) still see the position as unlocked.
- **A3 / A4 / A5** 시간 정리: close at the first 5m close >= 4 / 8 / 12 hours after entry if the first lock has not been
  reached by then (market, that bot's taker + slippage).
- **A6** = A2 + A1 for losers: at M, an unlocked position with net ROE > 0 gets the break-even stop (A2), one with net
  ROE <= 0 is closed (A1).
- An arm acts at every M while the position stays open (a position held over two openings is checked twice).

## Periods and the decision metric (fixed now)

- Months are KST calendar months, a trade belongs to the month (and period) of its entry (KST).
- choose = 2021-01 .. 2023-12 (36 months), check = 2024-01 .. 2026-09 (33 months), recent = 2026-10 (to the data end,
  reference only, no decision).
- One continuous one-position run per arm from 2021-01-01 00:00 KST to the data end (2026-10-24 23:55 UTC); a position
  still open at the data end is marked at the last close (market costs).
- Each calendar month starts fresh from $50, equity floor off: month multiple = product over the month's trades of
  (1 + net P&L / wallet before). Every trade is sized as a fraction of the wallet (margin 40 %), so this equals a $50
  wallet compounded within the month (order-size rounding aside: V3.9 trades are sized on a $50 wallet with the Toobit
  order steps the study assumed); a month without trades is x1.
- **Decision metric: the median month multiple of the period; tie (equal to 1e-12) -> total log growth Σ log(1 + net
  P&L / wallet before) of the period's trades.** An arm **helps** only if it beats A0 on this metric in BOTH choose and
  check. Several arms may help; no arm is tuned, added or dropped after a result is seen.
- Also reported per arm and period: trades, win rate (net P&L > 0), mean net % of equity per trade, months up
  (multiple > 1), worst month, total log growth, how many positions the arm touched (A1 / A3-5: closed by the arm; A2:
  stop raised at least once; A6: either).

## The bots and their machinery

### 1. V3.9 -> 투비트 (Toobit)
- Machinery: analysis/v39_1h (fiveyear.Five's data path on 5m bars: features.v39_signals on 1h bars made from the 5m
  bars, sim.trade's engine rules). The kernel is copied into research/opentime with the arm hooks; parity check below.
- Plan (docs/toobit-ko.md "두 분이 정한 계획", owners1025g/h `PLAN` = V("B", first_lock 0.17, gap 0.03, step 0.05,
  next_trigger 0.25, next_gap 0.03, stop_atr 2.5, BTC 40x / others 30x, margin 40 %)): ladder 20 -> 17, 25 -> 22,
  30 -> 27, then every +5 the lock 3 under; stop distance = paper stop (2 ATR of the signal's 1h ATR14, as % of the
  reference price) x 1.25, **from the own fill**; costs taker 0.06 % + slippage 0.02 % per side (round trip 0.16 %);
  no fixed take-profit; one position over the six coins, signals in time order (same close: BTC, ETH, SOL, DOGE, LTC,
  BCH), a signal while a position is open is skipped; entry = market at the signal bar's close (the next 5m open);
  liquidation guard: skip when 2.5 ATR / price >= 1 / leverage - 0.5 %; entry block when a US release is within ±30 min
  of the entry minute (FOMC + NFP from research/hunt/macro_calendar.json 2020-2026 plus data/macro_events.csv; CPI / PCE
  before 2026-10 are not in the repo); no Nasdaq block, no weekend block; Binance brackets for liquidation (mark =
  last price); Toobit order steps "A" of analysis/v39_1h/extras.py, min notional $5; funding from the 5m files.
- Not modelled (limits): the live bot follows the PAPER account's entries (V39_ALL@1h, its own exits and sizing; the
  live skips a paper entry while it still holds) and the paper's fast exit on a reverse signal before the live's first
  lock; here the live plan trades the V3.9 1h signals directly (as owners1025c/h did).

### 2. 레인지 봇 -> WOO X Pro
- Machinery: analysis/f7tp10_1026/hunt.py `run` with F1 = dict(H.BASE, commit=True, btc=True, k=0.20, wait_h=1)
  (F7_RF_TRIPLE 1h 80 / 9.0, coin + BTC 1h supertrend 10/3 filter, 0.2 ATR pullback up to 1 h, entry at the next 5m open,
  fixed take-profit net ROE +10 %, stop net ROE -50 %, BTC 40x / others 30x, margin 40 %, weekend / macro / Nasdaq-open
  ±30 min blocks at the signal, liquidation check, one signal at a time). The position function sim.run_position is
  replaced by a copy with the arm hooks (parity below). Its costs: taker 0.05 % + slippage 0.02 % per side, take-profit
  at its price with the maker fee 0.02 % (the study's own). Entry blocks are recomputed over the whole range with the
  same functions (hunt_prep.blocks only covered 2024-12 on).
- Work arrays: hunt_prep.py's per-coin arrays and trendcols.py's st1h, rebuilt from the same 5m files.
- The earlier "시간 청산" test (FINAL_KO.md §10, REPORT_KO.md §16, levers.py): a time exit after 1/2/3/4/6/8/12/24 h at
  the 5m open, tested only on the two live windows (10/06-10/25 and 10/13-10/25), on the structure before the final one
  (no pullback entry, no BTC filter). This study differs: the final structure (F1), 2021-2026 with a choose / check
  split, month multiples, and the clock arms A1 / A2 / A6 were never tested.

### 3. 추세판단 봇 -> Bybit
- Searched: research/trendbot/fiveyear/code/engine5y.py (5-year, 10/21 design, needs the 2020-2026 1m grid, not on this
  machine), analysis/review1024/roles/livebot/lb_core.py (5-year, 10/22 design with 18 members, its 1m data layer is not
  on this machine), analysis/review1024/sweep1025 (Sweep 2: single-member cells with simplified judges, not the bot).
  No multi-year replay of the current 12-member bot exists. So, as instructed, the existing 7/1-10/20 replay is used:
  research/trendbot/recent/sim.py (the script whose A0 equals data/trend_replay_0701_1020.json), copied with the arm
  hooks, on Binance 1m bars 2026-05 .. 10-20 (download.sh / parse.py, checksums verified), its signals.csv.gz (the 10/21
  design's 10 members), config deploy/combo.trend.json at b270569 = that replay's "A1 지금 규칙" (exits as live: stop net
  ROE -50 %, ladder 11 -> 10, 15 -> 12, then +5 (reached - 3), JUDGE and REV before the first lock, no TIME; Nasdaq
  22:00-23:00 KST, weekend and macro blocks). Costs: taker 0.05 % + slippage 0.02 % per side, no funding, macro block only
  for the October dates of data/macro_events.csv (the tool's own assumptions).
- Two entry modes, both reported: "now" (market at the signal minute, the current bot's 10/22 entry style) is the main
  one; "pullback" (0.25 / 0.5 ATR wait, the replay's own A1, parity) second.
- Window: entries 2026-07-01 .. 10-20 KST (months 07, 08, 09 inside the check period, 10 = recent). There is no choose
  period, so the "helps" rule cannot be applied: the trend bot gets numbers and a descriptive reading only, no verdict.
  Its members, entry style and judge differ from the live 12-member bot; exits are the live ones.

## Diagnostics (descriptive, no choosing), on each bot's A0
- (a) Positions still open and not at their first lock at an M (the first such M of the position): the share that later
  reached the first lock (레인지 봇: the take-profit), the share that ended at the stop, other exits; next to the same
  shares for all positions; split also by net ROE at that moment (> 0 / <= 0).
- (b) The same for positions still open and unlocked at the first 5m close >= 4 / 8 / 12 h after entry.
- (c) A0's losing trades (net P&L < 0) split by whether the exit was the stop hit inside 09:30-11:00 New York (90 min
  after the open, weekday, non-holiday) or not: count, share, sum of the losses in % of equity; next to the share of
  the positions' held time (5m bars; trend: minutes) that fell inside that window.

## Parity checks (machinery, before the arms; a failure is fixed in the implementation, not in the arms)
1. V3.9: the copied kernel with no arm and the stop measured from the reference price equals analysis/v39_1h/sim.trade
   (run_one) for every 2021-2026 signal taken alone on $50 (exit bar, reason, P&L to 1e-9).
2. 레인지 봇: the copied position function with no arm equals sim.run_position on every A0 trade; hunt.run F1 with the
   recomputed blocks gives the study's published F1 numbers (rule-bot window 38-0 x6.239, league 23-0 x3.046, October
   40-1 x5.533, 2025-01..2026-09 months: 4 up, median x0.665, win 77.4 %).
3. 추세판단 봇: the copied replay with no arm, pullback mode, gives RESULTS_KO.md A1 (78 entries in the window, 70 %
   wins, mean net ROE -3.1 %, $1,000 -> $234).

## Honest limits known in advance
5m bars instead of 1m for V3.9 and the 레인지 봇 (stop first inside a bar; the M decision at the 5m close); the trend
bot only 3.5 months of one market with another member set; NYSE holidays only 2026-2027; CPI / PCE missing from the
macro block before 2026-10; V3.9's paper-following and fast exit not modelled; wallet multiples only (no dollars).

## Addendum 1 (2026-10-26, before any arm of the 4th bot is run): VWAP 개선판 -> 딥코인 (DeepCoin)

The owners asked for every live bot ("총 돌아가는 실거래 매매봇들 각각"), so a fourth section is added with the same arms,
the same periods, the same decision metric and the same "helps" rule as above. Nothing above changes. This addendum is
committed before any VWAP arm (A0 included) is run; the V3.9 parity check (above, check 1) was the only thing run so far
(9,813 signals, 0 differences).

### 4. VWAP 개선판 (paper `deploy/combo.vwap.json`) -> 딥코인 executor (`deploy/executor.live-deepcoin.json`)
- Simulator: research/vwap30/code, the chain of vwmonth2.paper_trades (the live bot's own 5-year paper trades, the band
  of docs/vwap-bot-ko.md 9장): vwfix2.rows_tf (VWAP 복귀 실패 30m, prio 0) and vwadd.sig_job / rows_of (S3_CMO_SANDWICH 1h,
  prio 1), vwadd.time_ok + gates, vwacct._take (one position), leverage min(30, 0.5 / (2 ATR % + 0.14 %)) (the loss cap
  "shrink": a stop costs at most 20 % of the wallet at margin 40 %), margin 40 %. Its exit (vwfix2.outcomes_tf "base":
  stop 2 ATR of the signal bar, the rule bot's ladder 12 -> 10 then every +5 on net ROE at 30x, 96-bar cap closed at
  market, taker 0.05 % + slippage 0.02 % per side = DeepCoin's net_costs, funding) is copied with the arm hooks;
  parity: with no arm it must equal outcomes_tf "base" on every signal.
- Data: the simulator reads a 1m grid (fg1m) that is not on this machine. It is fed the same 5m files expanded to
  minutes (each 5m bar = one minute with its open / high / low / close / volume, then four flat minutes at its close;
  funding on the first minute; mark = last price; gaps filled flat as nlcommon.load_grid does) — 5m resolution, as for
  V3.9 and the 레인지 봇 (the method of analysis/f7tp10_1026/livepar.py). The trend-judge arrays (research/newlive
  judge_all.py -> trendbot/fiveyear judge5y.job) are rebuilt from that grid. Bars of 30m / 1h / 4h made from it equal the
  5m-built bars exactly. Its macro block is its own (data/macro_events.csv only, i.e. 2026-10 on); weekend and Nasdaq-open
  blocks as the bot.
- Arms at this resolution: M = the minute 09:29 New York (the last minute of the 09:25 5m bar), decided at its close.
  "First lock reached" = the ladder's first lock armed by then (best net ROE >= 12 %). Net ROE and break-even in the
  simulator's terms (return - round-trip cost - funding paid; break-even = the return where that is 0). Time arms: the
  close of minute 60 x N - 1 after the entry minute (entries sit on 30m / 1h closes, so this is the 5m close at entry +
  N h). The 96-bar cap stays (30m: 48 h, 1h: 96 h). All seven arms are possible.
- One-position chain from 2020-03-01 (the simulator's start); trades counted from 2021-01 KST like the other bots.
- Primary (as live): the executor copies a paper entry only while the paper's last 20 closed trades won >= 75 %
  (signal_light_n 20, min_win 0.75; fewer than 20: copied), on that arm's own paper sequence (the rule would be in the
  bot). Wallet return of a copied trade = 0.4 x leverage x net return; a trade not copied is 0. The decision uses this.
  Secondary (reported): the paper bot itself (every trade, no light).
- Not modelled (limits): the executor's own ladder on its own fill and its following of the paper's hold-limit exit
  only before its own first lock (the simulator keeps one account, the paper's); the simulator's ladder is computed at
  30x even when the leverage was shrunk.
- Diagnostics (a)-(c) as above on its A0 (primary and paper).
