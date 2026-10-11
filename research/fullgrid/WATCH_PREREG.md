# Watch league: the forward check of the 38 watch picks (pre-registered)

Written 2026-10-11 before the league runs these accounts. Pinned by `WATCH_PREREG.sha256`. Changes go to
`DEVIATIONS.md` with the reason, never here.

Owners 2026-10-11: "보정된 커스텀값으로 오늘부터 새로 paper 봇을 돌리면 기본수치로 돌리고 있는 규칙봇과 비교분석도 되고
좋지 않을까" and "6개월 paper는 너무 길어".

## 0. What this is

* No pick passed the full grid (0 / 711, `ANALYSIS_KO.md`). The watch list is the reference-only selection of
  `ANALYSIS_KO.md` 8: the 16 strategies with at least 6 picks of which at least half passed every gate but the chance
  correction; per cell with such a pick, the passing pick of the best select rank (`diag/watch_sel.json`, 38 picks: 23
  core, 15 DeepSeek). It was chosen after seeing the test period and 2020, so only data after 2026-09-30 can check it.
* Paper only, in the 후보 리그 (`candleague/`, its own bot, dashboard and Telegram tag). The rule bot and its day-30
  verdict are untouched. Nothing here goes to real money; that stays the owners' decision after section 4.
* The list is fixed: no pick is added or swapped after the start. The owners may stop the league or drop a strategy;
  that is recorded in `DEVIATIONS.md` and the strategy stays in the record up to that day.

## 1. Accounts (candleague.candidates.accounts, `watch` list)

Per pick, all from the same signals and the same engine (paperbot PaperEngine, v4 settings, $5,000, six coins, one
position at a time, fees, slippage, funding, liquidation, bust below $10):

| account | numbers | exit | size |
|---|---|---|---|
| `cand` | the pick's | the pick's | live (best 50/40x at 50/40% margin, normal 30/20x at 30/20%) |
| `quarter` | the pick's | the pick's | live leverages, every margin fraction x 1/4 |
| `exitonly` | the cell's defaults | the pick's | live |
| `base` (one per cell) | the cell's defaults | the live exit (2 ATR stop, ladder 10%) | live |
| `flip` | the pick's signal times, side from a seeded coin | the pick's | live |

Time: replayed from 2026-10-01 00:00 UTC (the first day after the study's data), then live. Data: Binance public REST.

## 2. Unit

Mean P&L per closed trade as a fraction of the wallet before it, per account; a pool is the mean over all closed trades
of its accounts. Weekly sums are by UTC week from Monday. DeepSeek money stays out of every report (D11): its rows show
trade counts, win rates and pass / fail labels only.

## 3. What is checked and when

1. **Warning light (all the time).** Each core `cand` carries its forward band (`diag/watch_bands.json`: 10,000 bootstrap
   means of n of its own test-period trades, n = 10, 20, 30, 50, 100; the 5th percentile). Below it at the largest n
   reached -> one `[후보 리그]` notice. With 23 core picks about one is expected below by chance alone. Not a verdict.
2. **Per account (CONTRACT.md 2, unchanged).** From 30 closed trades: mean > 0, > its `base` over the same days, > its
   `flip` -> "기준 통과".
3. **C1, 2026-11-11 (one month after the start).** Core and DeepSeek pools separately:
   * **Stop** the pool when its `cand` pool mean is below both its `base` pool mean and its `flip` pool mean.
   * Otherwise it continues. Reported for each: the `cand`, `exitonly`, `base`, `flip` pool means and trade counts.
4. **C2, 2026-12-11, and again 2027-01-11 if C2 did not pass.** A pool passes when all hold:
   * `cand` pool mean > 0 with a one-sided week-block bootstrap p < 0.05 (2,000 resamples of UTC weeks of the pool's
     weekly sums, seed sha256 of "watch|" + pool name + date);
   * `cand` pool mean > `base` pool mean and > `flip` pool mean;
   * at least 300 closed `cand` trades in the pool.
   Reported with it, not deciding it: `cand` vs `exitonly` (the numbers' share of any difference, versus the exit's)
   and the `quarter` accounts' wallets and drawdowns next to the `cand` ones.
5. **Per strategy, from C2 on.** A strategy's picks pooled the same way, shown with the same three conditions and a
   Benjamini-Hochberg 10% over the 16 strategies. Only a strategy passing this and a passing pool can be proposed.

## 4. What follows

* A passing pool at C2 lets the owners consider real money for its passing strategies only, at 1/4 size or smaller,
  with an amount they can lose, the executor's limits on, and the testnet drill done. The decision is theirs.
* A pool that fails C2 twice ends: no real money from this list.
* The rule bot's day-30 verdict (early November) is read alongside C1; neither changes the other.

## 5. Seeds and files

Bootstrap seeds as `run._seed`. The checkpoint numbers are computed from the league's `trades.json` snapshot by a script
committed before C1 (`research/fullgrid/diag/watch_check.py`), which reads only that snapshot and this file's rules.
