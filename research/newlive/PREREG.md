# 새 실거래봇 매매법 고르기 — 사전 등록 (2026-10-22)

Written 2026-10-22 (UTC) before any five-year run of any NEW candidate. Already seen before this file: the five-year
replay of the current 10 members (research/trendbot/fiveyear), the rule bot's live record 10/05..10/22 and the candidate
league's live record 10/13..10/22 (both under their own exits, not this structure). The classification
(`classify.json`) was made from the strategies' code without performance numbers. This file is committed before the
runs; its sha256 goes into the results.

## Owners' fixed design (10/22)

- Structure as `deploy/combo.trend.json`: trend-type strategies never enter, they judge (the 4 judges V39, S6, OBV,
  N12; vote ≥ 3, ADX ≥ 20, 끝물, hold 1h 2 / 4h 1); 30m entries follow the closed 1h judgment, 1h entries the closed
  4h judgment; entry checks, chase block, pullback 0.25 / 0.5 ATR, score rank, ONE position.
- Money and exits as the current live bot: BTC 40x / others 30x, margin 40 % of the wallet, stop −50 % net ROE, ladder
  11→10, 15→12, then every 5 %: reached − 3; REV and JUDGE before the first lock; no TIME exit.
- Pauses: weekend, macro ±30 min, Nasdaq open −30..+30 min.
- Only the MEMBERS change. Entries only by breakout (돌파), location (자리) and pullback (눌림) strategies; no
  range / sideways / mean-reversion (횡보·역추세) strategy (the owners' friend: "횡보는 넣으면 안됨").

## Candidates (fixed)

- Universe: every strategy whose primary class in `classify.json` is 돌파, 자리 or 눌림, on 30m and on 1h, with
  default numbers (label `NAME@tf`), plus every candidate-league pick (`candleague/data/candidates_owner.json`,
  sha256 7fc01e0307271f566c9cf452a391ef6128850b983d56ba229b1a3cef7b96d2b8, equal to the server's
  /etc/candleague/candidates.json of 10/22) of such a strategy on 30m or 1h, with its custom numbers
  (label `NAME@tf#<pick id>`).
- A member with primary class 돌파 gets the breakout entry check (trend early: ADX < 30 and rising), as the current
  config's `breakout` list does. `no_chase` true for every member. No side-only or other `when` condition.

## Data, engine, costs

As research/trendbot/fiveyear/PREREG.md (same 1m data, same signal functions, same engine order, same coin-flip method),
extended with the 2026-10 daily files. Costs: taker 0.05 % + slippage 0.02 % per side, real funding (paper). The
executors' own taker fees (Bybit 0.044 %, WOO X Pro 0.042 %) are shown as a sensitivity only.

Periods (by entry time, UTC): select 2021-01-01 .. 2024-12-31; confirm 2025-01-01 .. 2026-09-30; live 2026-10-01 .. the
last data day (information only). Wallet $1,000, margin 40 %, compounded: growth = Σ log(1 + 0.4 × ROE).

Measures per run and period: entries, entries per weekday, win % (net ROE > 0), mean net ROE, mean before-cost ROE,
payoff (mean winning net ROE ÷ |mean losing net ROE|), compounded growth (log and $1,000 →), worst drawdown of the
compounded wallet (trade-close basis), exit reasons, coin-flip percentile of the growth.

## Selection (on the select period only)

1. Solo run: each candidate is the ONLY member. A candidate PASSES when, in the select period, it has ≥ 40 entries,
   its mean before-cost ROE is > 0, and its growth is at or above the 90th percentile of its own coin-flip twin
   (200 draws, `numpy.random.default_rng(20261022)`).
2. Basket B1: the passing candidates, best select-period growth first, at most 12, one label per (strategy, tf) (the
   better select growth of default and custom). If none pass, there is no B1 and the report says so.
3. Basket B0 (the honest "best-looking" set, for the owners' ranking): the 10 candidates with the best select-period
   growth regardless of passing, one label per (strategy, tf).
4. Confirm ONCE on the confirm period: B1 (if any), B0 and the current 10 members (C0) as baskets in the same
   structure. For each: growth, mean ROE, before-cost ROE, win %, payoff, worst drawdown, entries per weekday, and the
   coin-flip band (1,000 draws, rng 20261022). Verdicts: "벌었다" = growth > 0; "지금보다 낫다" = growth > C0's;
   "운보다 낫다" = growth > its coin-flip 95th percentile. The live period is shown next to it, not judged.

Nothing is re-selected after the confirm period is seen. Every candidate's confirm and live numbers are shown in the
ranking table for information only (sorted by select-period growth).

## Also reported (information, not selection)

- Default vs custom numbers per (strategy, tf) where both exist, in each period.
- 30m vs 1h members as groups.
- The judges alone: for every closed 1h and 4h bar with a direction, the share of bars whose next 4 bars (same tf)
  closed in that direction, 2021..2026, against 50 %.
- The rule bot (10/05..10/22) and the league (10/13..10/22) live records under their own exits: per account entries,
  win %, payoff, mean ROE, return, worst drawdown; timeframe groups; custom (league "-ld") vs default (rule bot, same
  cell, same window) in net R.

## What would make the result wrong

The classification decides the universe; a strategy put in the wrong class is in or out by mistake (the class list is
committed first so it can be checked). With N candidates, about 10 % pass step 1 by luck alone (90th percentile);
the confirm period is the check against that.
