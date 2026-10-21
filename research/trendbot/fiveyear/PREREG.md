# 추세판단 봇 5년 점검 — 사전 등록 (C: 잠금 간격·배수 vs 비용)

Written 2026-10-21 (UTC), before any five-year run of any variant (C or D) was made. The only results seen so far
are the checks listed under "Checks done before this file" (the 2026-06-28..10-20 replay that was already known, and
engine/indicator equality tests). This file is committed before the runs; its sha256 goes into results.json.

## Data and code (fixed)

- 1m bars: Binance USD-M, 6 coins, 2020-01 .. 2026-09-30 (`fg1m/1m/<COIN>.npz`, sha256 checked against
  `fg1m/build.json`: all 6 equal). Mark prices and funding events from the same files. Missing (zero-volume) minutes =
  flat bar at the previous close.
- Rules: `deploy/combo.trend.json` at commit b270569 (time_bars null, us_open pre 30 + post 30, macro ±30, no weekend,
  10 members, vote 3, ADX 20 / 40 끝물, hold 1h 2 / 4h 1, pullback 0.25 / 0.5 ATR, BTC 40x / others 30x, margin 40 %,
  net stop −50 % ROE, ladder 11→10, 15→12, then every 5 %: reached − 3, REV and JUDGE before the first lock).
- Member signals: computed once on the full series with the rule bot's library functions (sweep_lib.compute_signals,
  dssig.entries_frame). On 2026-07-01..10-21 they equal the live trailing-window signals 4,917 / 4,917 (100 %).
- Trend judge and entry-bar values: trendjudge.vote_arrays on the full series; equal to the live 300-bar frames on
  2,400 sampled 1h and 2,400 sampled 4h bars (votes, raw, dir, vote-4 raw: 100 %; ADX within 1e-7 relative).
- Engine: `engine5y.py` (event-driven, minute order of the live engine). Checks done before this file:
  the 2026-06-28..10-21 replay with that replay's rules gives the same 92 entries, the same exit reasons and the same
  ROE (max difference 2e-16) as the earlier minute-by-minute replay (89 in the KST 7/1..10/20 window);
  120 random positions 2021-2026 (leverage 10-40x, both ladders, stop −35/−50 %, 58 with funding, 60 with a
  supervisor exit) are identical to the repo's own `TrendEngine` (exit minute, reason, ROE within 1e-8);
  the array chase check equals `combo.chase_check` on 1,800 random cases.
- Costs: taker 0.05 % per side (what the paper bot charges), slippage 0.02 % per side, real funding on the mark open;
  maker 0.02 % (repo: `config.Settings.maker_fee`). Stop first inside a 1m bar; a new lock applies from the next bar;
  no lock on the entry bar.
- Macro calendar: FOMC + NFP 2020-2026 from `research/hunt/macro_calendar.json` (repo's historical calendar) plus
  `data/macro_events.csv`. CPI / PCE before 2026-10 are not in the repo (not blocked). NYSE holidays only 2026-27 in
  the repo (earlier holidays are treated as open days: a 1-hour entry pause on ~9 extra days a year).

## Run and money

- One continuous run per variant: member signals with bar close 2021-01-01 00:00 UTC .. 2026-10-01 00:00 UTC,
  wallet $1,000 at the start, records (for the score) start empty. A position opened before 2026-10-01 may close on
  October bars (2026-10-01..20 daily files, checksums verified; no funding / mark files for October).
- Per trade: ROE = net P&L / initial margin (fees, slippage, funding in). Margin = 40 % of the wallet at entry, so the
  wallet after a trade = wallet × (1 + 0.4 × ROE) (exactly the engine's wallet). Compounded wallet growth of a period =
  Σ log(1 + 0.4 × ROE) over the trades ENTERED in that period (reported also as final / start).

## Coin-flip twin (every variant)

Same entries (minute, coin, member, entry price) as the variant's own run, side drawn at random (+1 / −1, p = ½,
independent), 1,000 draws, `numpy.random.default_rng(20261021)`. Each entry's outcome for the other side is simulated
with the same engine; the supervisor (JUDGE, TIME) and REV events follow the bot's judged direction (as the live twin's
JUDGE does: "봇이 진입할 때 본 추세가 뒤집힐 때 같이 닫힘"). Band = 5 % / 50 % / 95 % of the draws' growth (and of
mean ROE, win %). Overlapping twin trades are compounded in entry order (an approximation).

## C. Variants (8, including the current rules) — fixed now

| id | leverage | stop (net ROE) | ladder |
|---|---|---|---|
| C0 | BTC 40x / others 30x | −50 % | first lock 10 % at 11 %, 12 % at 15 %, then every 5 %: reached − 3 (current) |
| C1 | 20x all coins | −50 % | current |
| C2 | 10x all coins | −50 % | current |
| C3 | BTC 40x / others 30x | −50 % | first lock 20 % at 21 %, 22 % at 25 %, then every 5 %: reached − 3 |
| C4 | BTC 40x / others 30x | −50 % | first lock 30 % at 31 %, 32 % at 35 %, then every 5 %: reached − 3 |
| C5 | BTC 40x / others 30x | −35 % | current |
| C6 | 20x all coins | −50 % | first lock 20 % (as C3) |
| C7 | 20x all coins | −35 % | first lock 20 % (as C3) |

Everything else as the current rules (entries, judge, supervisor, no TIME). Ladder numbers in the config's terms:
C3/C6/C7 `first_lock 0.20, trigger_gap 0.01, next_trigger 0.25, next_gap 0.03, step 0.05`; C4 `first_lock 0.30,
trigger_gap 0.01, next_trigger 0.35, next_gap 0.03, step 0.05`.

**Selection metric:** compounded wallet growth Σ log(1 + 0.4 × ROE) of the trades entered 2021-01-01 .. 2024-12-31
(the selection window), costs and funding in. The variant with the highest value is selected (no tie rule needed;
if two are within 1e-9, the one listed first).

**Confirmation, once:** the selected variant on the trades entered 2025-01-01 .. 2026-09-30.
- "Better than the current rules" = its confirm-window growth > C0's confirm-window growth.
- "Better than luck" = its confirm-window growth > the 95th percentile of its own coin-flip twin in that window.
Both are reported as yes / no. If C0 is selected, only the second applies. No variant is added, dropped or tuned after
any result is seen; the confirm window is computed once.

## D. Five-year check (descriptive, not a selection)

The current rules (= C0) on 2021-01 .. 2026-09: per year, per half-year, per coin, per member: entries per weekday
(KST Mon-Fri), win %, mean net ROE, before-cost ROE (entry and exit at the reference prices, same leverage), cost
split (slippage, taker fee, funding), exit mix, wallet path, worst drawdown (on trade closes), and the coin-flip band.
Plus, on the same years, four shadow runs (each a full run of its own):
- D1 TIME 4 entry bars (as the rules before 10-21 night);
- D2 entry at once (at the signal minute's open, no pullback wait);
- D3 vote 4 of 4 (judgment, hold and the supervisor's JUDGE all with 4 votes);
- D4 maker entry: a resting limit at the pullback level from the signal's next minute to the entry bar's
  second-to-last minute, filled at the level only when a 1m bar trades THROUGH it (low < level for a long, high > level
  for a short), maker 0.02 %, no entry slippage, entry checks at the fill minute, stop first inside the fill minute,
  the fill minute's range not used for the ladder; exits as the current rules (taker + slippage).
A cost sensitivity of C0 with the executors' documented taker fees (바이비트 0.044 %, WOO X Pro 0.042 %) is
reported as well (descriptive).
