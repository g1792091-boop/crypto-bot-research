# Task B: the user's new money-management rules, simulated with planted edges on real IS paths

Dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sizing/sim`.
Only `sweep/data/is/<sym>-<tf>.csv` was read (bars < 2024-07-01). Nothing under `sweep/` or
`/home/user/crypto-bot-research` was modified. No Astral calls. At most 2 of my processes ran at once.
Every number below comes from the scripts in this directory (outputs under `out/`).

User rules under test: (R1) margin >= 20 % of equity, "adaptive"; (R2) leverage >= 20x (was 50x), "adaptive";
(R3) take-profit >= +10 % ROE (= 10 %/L price move: 0.5 % at 20x, 0.2 % at 50x).

## 0. Bottom line

1. **The cost wall comes first, and no sizing rule gets past it.** With realistic Binance costs (about 0.14-0.18 % of
   notional per trade, funding included), even 1x notional (P0) or the recommended volatility-targeted rule (P6) only
   grows in median over 1 year when the *planted gross drift* is at least **0.15-0.44 %/trade** (0.23-0.31 % for P6).
   The best edges ever measured in this project are +0.135 % gross (B in-sample, which failed OOS at −0.032 %),
   about +0.09 % gross (stage-1 best 15m, net −0.05 %) and +0.013 % gross (DOGE). At D = 0.10 % **every** policy loses in
   median over 1 year on every timeframe (P0 1-year median ×0.16-0.86, P6h ×0.17-0.996). The per-trade growth
   condition (median > 1) hardly depends on how often the bot trades; P(ruin) and the speed of losses do.
2. **The user's minimum (P3: 20 % margin × 20x = 4x notional, TP +10 % ROE) needs 0.19 % (5m), 0.28-0.29 % (15m),
   0.69-0.71 % (1h), 0.62-0.67 % (4h) and about 2.0 % (1d, exits resolved on 5m sub-bars) of planted drift** (no
   stop, or a stop at half the liquidation distance; a 1.5 ATR stop needs more: 0.29 / 0.43 / 0.86 / 0.58 %). That
   is 1.4-5x the best in-sample edge on 5m-4h. A strategy that clears it would have to show, in a realistic-cost
   backtest with these exits, a realised gross move of about +0.12-0.15 % and a net of +0.013-0.033 % per trade per
   unit notional. No OOS-validated strategy here has a net above 0. At zero edge P3 loses 0.38-0.68 % of equity **per trade**. On 15m that is a 30-day
   median of ×0.61, P(30-day loss) 0.89 and P(ruin within 1 year) ≈ 1.00.
3. **The user's upper style (P4: 40 % × 50x = 20x notional, TP 0.2 % price) fails at every planted edge tested on
   every timeframe** (up to 0.40 % on 5m, 0.60 % on 15m, 1.5 % on 1h/4h, 3 % on 1d). On 15m the 30-day median is
   ×0.01-0.11 across D = 0-0.40 %. Without a stop, 5-23 % of trades are liquidated at zero edge, and each
   liquidation costs 40 % of equity.
4. **"Adaptive inside [20x, 50x] and [20 %, 40 %]" (P5) does not escape the floors.** On 5m/15m it picks ~42-48x and
   behaves like P4 (fails at every edge); on 4h/1d the floors bind and it *is* P3. Even a *perfect* confidence
   signal that puts 40 % margin exactly on the trades carrying the edge and 20 % on the rest (P5c, an unattainable
   upper bound) does not make it work on 15m (1-year median ×0.04 at D = 0.40 %).
5. **The +10 % ROE take-profit is the second problem.** At 20-50x it is a 0.2-0.5 % price target. It keeps only
   4-64 % of the planted drift for P3 and 0-28 % for P4 (a pure time exit keeps ~100 %, a 1.5 ATR stop ~70-100 %),
   and on 1h-1d it produces the classic "high win rate, negative expectancy" profile. On 1d with 5m sub-bar exits
   at zero edge, P4 (40 % × 50x) wins 90 % of trades, and its **30-day median is ×1.07 with a median 30-day max
   drawdown of 0 %**. Yet its 1-year median is ×0.094, P(equity < 50 % within 1 year) = 0.94 and P(ruin) = 0.58.
   P3 shows the same profile: 91 % wins, 30-day median ×1.05, 1-year median ×0.70, P(<50 %) 0.40. A 15-day backtest
   or a 2-week live run cannot see this.
6. **Kelly check.** On the reference exit (1.5 ATR stop + time exit), the growth-optimal notional reaches the user's
   4x floor only at planted drift >= 0.24 % (5m), 0.34 % (15m), ~3 % (1d), and never on 1h/4h (exact Kelly is capped
   at 2.95-3.75x there by the worst trade). P4's 20x notional is above full Kelly at every tested edge on every timeframe.
7. **What to adopt instead (only after a strategy passes a pre-registered OOS test):** size from risk, not from
   leverage — risk 0.25-0.5 % of equity (max 1 %) to a validated stop, notional = risk / (stop distance + round-trip
   cost), hard cap on notional and on monthly cost, leverage chosen afterwards (<= 10x, liquidation >= 2x the stop
   distance away), daily/weekly loss limits and a drawdown kill switch. Details in section 7. Today, with no
   strategy that passes OOS, the correct size is **0**.

## 1. Design (fixed before looking at results; choices documented)

- **Data**: sweep IS bars for BTC, ETH, SOL, XRP, DOGE, LTC, BCH; signal bars in [2021-08-01, 2024-07-01), forward
  paths entirely before 2024-07-01, no data gaps inside a path (1,065 calendar days). Timeframes 5m, 15m, 1h, 4h, 1d.
- **Account**: one position at a time across all 7 coins (base case). A signal that arrives while a position is open is
  skipped; the next position may open on a signal bar at or after the exit bar. Concurrent positions were not
  simulated; they would add exposure (gap_3 found concurrent Kelly 0.26-0.92x the per-trade Kelly).
- **Entries**: random signal bars (Bernoulli per bar on the union time grid, coin uniform among the coins with an
  admissible bar). Attempted rate / holding horizon H: 5m 8/day, H=16 (80 min); 15m 4.5/day, H=16 (4 h); 1h 1.5/day,
  H=16 (16 h); 4h 3/week, H=4 (16 h); 1d 1.5/week, H=4 (4 days). Taken trades per 30 days: see the setup table.
- **Planted edge**: with probability q the side is the sign of the H-bar forward return r_H = close[t+H]/open[t+1] − 1,
  otherwise a coin flip (direction accuracy (1+q)/2). q is set per coin as D / E_c|r_H| so the mean signed H-bar drift
  equals the target D on every coin. D grid: 0, 0.025, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30, 0.40, 0.60, 0.80, 1.0,
  1.25, 1.5, 2.0, 2.5, 3.0 %, truncated where q would exceed 1 on some coin (5m max 0.40, 15m 0.60, 1h/4h 1.5, 1d 3.0).
  Check: the realised drift on taken trades matched D (e.g. 15m, D=0.10 → 0.098-0.103 %; D=0.40 → 0.400-0.414 %).
  On 1h/4h it runs 0.015-0.025 % low and on 1d ±0.04 % because of common-random-number noise; treat min-edge values
  as ±0.03 % (±0.05 % on 1d).
- **Execution and costs** (Binance USDT-M, isolated margin): market entry at open[t+1] with taker 0.05 % + slippage
  0.02 %; TP = resting limit, maker 0.02 %, no slippage, filled at the target or at a better open; stop = taker +
  slippage, filled at the stop or at a worse open (gaps); time exit at close[t+H], taker + slippage; funding 0.01 %
  per 8 h pro rata, charged as a cost. Round trip 0.09 % (TP) or 0.14 % (stop/time) plus funding.
- **Liquidation**: when the adverse move from entry, measured on bar high/low, reaches d_liq = 1/L − 0.5 % (MMR). The
  whole isolated margin M is lost, plus the entry fee and funding. Inside a bar: bullish bar O→L→H→C, bearish
  O→H→L→C; opens that gap through a level fill at the open.
- **Stops**: (A) none (liquidation only), (B) 1.5 × ATR14 (Wilder, % of close at the signal bar), (C) 0.5 × d_liq.
  If a stop sits beyond d_liq, liquidation comes first. Plus the time exit at H.
- **Sizing policies** (M = margin as a fraction of equity, L = leverage, notional N = M·L):
  - P0: M 100 %, L 1 (1x). P1: 25 % × 5 (1.25x). P2: 25 % × 10 (2.5x). P3 (user minimum): 20 % × 20 (4x).
    P4 (user upper style): 40 % × 50 (20x).
  - P5 (user-adaptive, inside the user's bounds): L = clip(floor(1/(3·ATR% + 0.5 %)), 20, 50), i.e. keep liquidation
    >= 3 ATR away when the floor allows; M = clip(6 % / (L·ATR%), 20 %, 40 %), i.e. a 1-ATR adverse move costs 6 % of
    equity, clipped to 20-40 %. Mean L / M / N realised: 5m 48x / 34 % / 16.6x; 15m 42x / 27 % / 11.8x; 1h 28x / 22 % /
    6.3x; 4h 21x / 20 % / 4.2x; 1d 20x / 20 % / 4.0x.
  - P5c: P5's leverage, margin 40 % on exactly the trades that carry the planted information (the oracle draws) and
    20 % on the others. A perfect "chart confidence" signal; an upper bound, not something a real strategy has.
  - P6 (recommended shape): risk r = 1 % of equity to a 1.5 ATR stop: N = r / (1.5·ATR% + 0.14 %), capped at 3x;
    L = min(10, floor(1/(3·ATR% + 0.5 %))) so liquidation is >= 2x the stop distance away; M = N/L. No TP, time exit
    at H. P6h: the same with r = 0.5 %. P6|B|10: P6 with the user's +10 % ROE TP at P6's leverage.
  - TP for P0-P5 = +10 % ROE (10 %/L price). P3/P4/P5 were also run with +30 % and +100 % ROE.
- **Runs**: 100 random entry streams (seeds) per TF over the whole IS span; per-trade equity returns compound
  (fractional sizing). Distributions: moving-block bootstrap of days (blocks of 10 days, drawn from any seed, circular
  inside the seed), 6,000 paths of 30 days and 6,000 paths of 365 days, the same draws for every policy and edge.
  "Ruin" = equity < 10 % at any trade exit; "P(<50 %)" likewise; max drawdown uses trade-exit equity.
- **Verification**: the vectorised exit engine was compared with an independently written per-trade loop on 32,000
  trade × policy × side × ordering cases: 0 mismatches (`verify_outcomes.py`). The lock-step one-position-at-a-time
  selection and the daily aggregation were compared with a sequential loop: identical trade counts, liquidation counts,
  final log equity, min equity and max drawdown (max abs diff 1.1e-5 in log equity, float32 storage;
  `verify_chain.py`).

SETUP_TABLE

## 2. Results by timeframe (base case)

Each cell: 30-day median multiple / P(30-day loss) / P(equity < 50 % within 1 year) / P(ruin: equity < 10 % within 1 year).

MAIN_TABLES

**1d note.** The 1d rows above use the bar-colour intrabar rule, which is too pessimistic for tight-TP policies on
daily bars (section 6). With exits resolved on 5m sub-bars, at zero edge: P3 1d has a 1-year median of x0.70 (not
x0.53) and P(<50 % within 1 year) of 0.40, and P4 1d has x0.094 and 0.94. The verdict is the same. 15m-4h are
affected much less (P3 minimum edges with sub-bars are within 0.1 % of base: 15m 0.28-0.42 vs 0.28-0.43, 1h 0.64-0.84
vs 0.69-0.86, 4h 0.55-0.61 vs 0.58-0.67).

## 3. Minimum edge for the user's rules

Criterion: median 1-year multiple > 1 AND P(ruin within 1 year) < 10 %. D* is the planted gross drift per trade at
horizon H (linear interpolation on the D grid; it must hold at every larger D tested).

MIN_EDGE_TABLE

What a realistic-cost backtest of the same strategy would have to show per trade at D* (realised gross move and net
per unit notional, both in %):

REALISED_TABLE

Reading: for P3 with the +10 % ROE TP, the *realised* net needed is small (+0.013 to +0.033 %/trade on 5m-4h),
because the tight TP keeps each trade's variance low. But producing that realised net needs 0.19-0.71 % of planted
drift, because the TP throws most of the drift away (next table). P4 never gets there.

CAPTURE_KELLY

## 4. The observed edges of this project on this scale

| source | per trade | where it sits |
|---|---|---|
| B (V4.5 64-bar drift), in-sample, post hoc | +0.135 % gross drift, +0.105 % net (maker) | column D = 0.10-0.15 |
| B, pre-registered OOS | −0.032 % drift, −0.048 % net | below D = 0 |
| stage-1 best 15m combo (S6), best of 364 | −0.052 % net ≈ +0.09 % gross | column D ≈ 0.10 (selection-biased upward) |
| DOGE friend strategy, 5 years | +0.013 % gross, −0.13 % net | column D ≈ 0 |

At D = 0.10 % (base case), the 30-day and 1-year median multiples are as follows. No policy on any timeframe has a
1-year median above 1 at this edge. That holds in the base, sub-bar, mark-price and front-loaded runs (0 of 168-210
cells each). Only with optimistic maker entries do the 1x-2.5x no-stop policies on 5m/15m reach x1.02-1.17.

OBS_TABLE

So at the best edge ever seen (and that one failed OOS), the user's minimum loses 91-99.5 % in a year on 5m-1h and
46-48 % on 4h/1d; P4 is gone within weeks; the only policies that keep most of the money are the small ones on the
slower timeframes, and they also lose, slowly.

## 5. How fast it goes wrong when the edge is not there (the base case in this project)

KILL_TABLE

- At zero edge, P4 hits −20 % from peak in a median of 2 days (5m/15m), 5 days (1h), 14-15 days (4h/1d); a −20 % kill
  switch fires only after one liquidation has already cost 40 %, so equity at the stop is ~0.60-0.65, not 0.80.
- P3 hits −20 % in 6-9 days (5m/15m), 11-18 days (1h), 30-73 days (4h/1d).
- P6 at 5m hits −20 % in 12 days at zero edge: 187 trades/month × 1.7x notional × 0.15 % cost ≈ −48 %/month. Even a
  "correct" risk-per-trade rule needs a cost budget on high-frequency timeframes (section 7).

## 6. Sensitivities

SENS_TABLE

SENS_TEXT

## 7. Recommended adaptive sizing rule (to use only after a strategy passes a pre-registered OOS test)

None of this creates an edge. Its job is to (a) never let a single trade or a single bad week decide the account,
(b) adapt size to the chart in the one way that is measurably right (volatility), and (c) stop quickly when the live
edge turns out smaller than the backtest, which is the normal case in this project.

**Gate.** Trade only a strategy that passed a pre-registered OOS test with realistic costs. Size from the *lower*
80 % confidence bound of its OOS net mean per trade (mu_lo), not from the backtest mean. If mu_lo <= 0, size = 0.

**1. Risk per trade R (fraction of equity lost if the stop is hit, costs included).**
- First 100 live trades (and at least 1 month): R = 0.25 %.
- After that, if the live net mean per trade is >= 0 and not significantly below the OOS mean: R = 0.5 % (P6h).
- Hard maximum R = 1 % (P6). Never raise R after a loss streak; raise by at most 1.5x per step, and only after
  >= 200 live trades with live mean >= half the OOS mean and drawdown inside expectations.

**2. Notional from volatility (the measurable "chart-adaptive" part).**
- N = R / (stop distance + round-trip cost), with stop distance = the strategy's validated stop (for example
  1.5 x ATR14 of the trading timeframe) and round-trip cost = 0.14 % + expected funding.
- When the chart is calm (small ATR) the position is larger; when it is violent the position is smaller, with the
  same money at risk. In the simulation this gave mean notional 1.73x / 1.13x / 0.60x / 0.30x / 0.12x of equity on
  5m / 15m / 1h / 4h / 1d at R = 1 % (half that at R = 0.5 %).
- Caps: N <= 0.5 x mu_lo / sigma^2 (half-Kelly from the OOS lower bound; sigma^2 = variance of net return per unit
  notional); N <= 2x equity per position; total N over all open positions <= 3x; one position per coin.
- Cost budget: trades per month x N x 0.15 % (what you lose per month if the edge is actually zero) <= 3 % of equity
  during the first live phase. Measured examples: P6 on 5m (187 trades/month x 1.73x) burns ~48 %/month at zero edge
  and hit −20 % from peak in a median of 12 days; P6h on 15m (91 x 0.56x) burns ~7.7 %/month. High-frequency
  timeframes therefore need a much smaller N than the risk formula alone gives, or fewer trades.

**3. Leverage and margin come last.**
- Isolated margin. Leverage only decides how much margin is parked on the exchange; it does not change P&L as long as
  the position is not liquidated (per-trade equity return = N x net move, whatever M and L are).
- Choose L so that the liquidation distance is at least 2x the stop distance: L <= 1 / (2 x stop + 0.5 %), and L <= 10.
- The user's "at least 20 % of the seed" can be kept: set M = 20 % and L = N / 0.20. With the R = 0.5 % sizing above
  that is about 4x on 5m, 3x on 15m and 1.5x on 1h (P6h mean notional 0.87x / 0.56x / 0.30x). On 4h and 1d the
  notional (0.15x / 0.06x) is below 20 % of equity, so use M = N and L = 1 there.
  The "at least 20x" floor cannot be kept: it forces N >= 4x, which is above the growth-optimal notional for every
  edge below 0.24-0.34 %/trade on 5m/15m and for every tested edge on 1h/4h (section 3).

Example outputs of steps 2-3 for typical chart states (`rule_examples.py`; stop = 1.5 ATR, round trip 0.14 %, N capped at 2x):

RULE_EXAMPLES

**4. Confidence scaling, only if it is validated.**
- Allowed only if, in OOS data, the net edge rises monotonically across signal-strength buckets (for example terciles,
  each with >= 100 OOS trades) and the top bucket's lower bound is > 0. Then multiply R by 0.5 / 1.0 / 1.5 for the
  low / middle / top bucket, still capped at R = 1 %.
- Without that evidence, no confidence scaling. Even a perfect confidence signal inside the user's bounds (P5c) did
  not make 20-50x work.

**5. Regime brake.** Halve R when the trading-timeframe ATR% is above its trailing 1-year 90th percentile, or after a
>= 8 % daily BTC move, or around scheduled high-impact events (gaps, stop slippage, liquidation cascades; not
simulated here).

**6. Exits in price terms.** Take-profit and stop come from the validated strategy in ATR/price units, not in ROE.
+10 % ROE is a 0.5 % price move at 20x and 0.2 % at 50x; it kept 4-64 % of the planted edge and on 1h-1d produced a
90 % win rate with a negative expectancy.

**7. Loss limits.**
- Daily: after a realised loss of 3R (1.5 % of equity at R = 0.5 %) or 3 consecutive stop-outs, no new entries until
  the next UTC day.
- Weekly: −6R, pause until the next week.
- Drawdown ladder from the equity peak: −10 % halve R; −15 % quarter R; −20 % kill switch.

**8. Kill switch (any one: flatten, stop the bot, review; restart only after >= 1 month / 100 trades of paper
trading that matches expectations).**
- Equity −20 % from peak. With R-based sizing this stops at about 0.80 of the peak (measured: median equity when it
  fired 0.79-0.83 for P6/P6h at zero edge). With P4-style sizing it stops at about 0.60-0.65, because one liquidation already costs
  40 %.
- Edge decay: every 50 live trades, if the cumulative live net per trade is below the OOS mean minus 2 standard
  errors (or a one-sided CUSUM on live trade returns crosses its limit).
- Execution: mean slippage over the last 30 fills > 2x the model (0.02 %), a fee tier different from the model, any
  rejected or missing exchange-side stop order.
- Technical: position/order state mismatch with the exchange, repeated API errors, market data older than a few bars.
  The stop must be an exchange-side reduce-only order placed together with the entry.

**What this delivers if an edge exists.** At a planted drift of 0.40 %/trade (3x the best in-sample edge ever seen
here) P6 gives a 15m 30-day median of x1.07 and P6h x1.04, with P(ruin within 1 year) = 0. On 1h-1d it is x1.00-1.01 per
month. That is what good looks like; ×20 a month is not on this scale (gap_3: it needs an annual Sharpe of ~8.5).

## 8. Caveats

- Spot aggregate bars (Polygon) stand in for Binance perp last/mark prices. Liquidation uses the mark price on Binance,
  which is smoother than single-venue spot wicks; the `mark` sensitivity bounds this. (A first attempt that clipped
  every local high/low to its neighbours was discarded: it used the next bar to decide whether a low was "real",
  which suppressed stop-outs at local bottoms and made stop-based policies look profitable at zero edge, a look-ahead
  artefact. Its outputs are kept in `out/wick_robust_DISCARDED/` and are not used anywhere.) Liquidation fees beyond the lost
  margin, ADL, and funding extremes are not modelled.
- The planted edge is a stylised oracle on the H-bar sign. A real signal's time profile may differ (the `front` run
  plants it on the first quarter of the horizon). The result is about sizing and exits given an edge of a stated
  size; it is not evidence that any such edge exists.
- The 1-year and 30-day distributions reuse the 2021-08 to 2024-06 market (a bear market, a recovery and several
  crashes: 2021-09-07, 2021-12-04, 2022-05, 2022-11 FTX, 2023-08-17, 2024-04-13). Other regimes can be better or
  worse.
- One position at a time. Several concurrent positions at 20 % margin each would multiply every loss number here.
- The adaptive rules P5/P6 are one concrete choice each; other formulas inside the same bounds give the same
  qualitative result because the bounds, not the formula, set the notional (P5's floors bind on 4h/1d; its 50x cap
  binds on 5m/15m).

## 9. Files

- `simlib.py` (panel, exits, policies, lock-step selection), `run_sim.py`, `boot.py`, `report.py`, `report2.py`,
  `summary.py`, `sens_table.py`, `killswitch.py`, `stats_panel.py`, `verify_outcomes.py`, `verify_chain.py`,
  `rule_examples.py`, `build_notes.py` (fills `NOTES_template.md` + `sens_text.md` into this file), `run_all.sh`,
  `run_rest.sh`, `run_front.sh`, `run_maker.sh`, `run_mark.sh`, `run_sub.sh`.
- `out/<tag>/<tf>_metrics.csv`: every TF × edge × policy cell (trade stats, IS-span, 30-day and 1-year distributions).
- `out/<tag>/<tf>_kelly.csv`, `out/<tag>/min_edge.csv`, `out/<tag>/min_edge_table.txt`, `out/<tag>/tables.txt`,
  `out/base/summary.md`, `out/min_edge_realised_base.md`, `out/sens_table.md`, `out/killswitch.csv`.
- Tags: `base` (100 seeds), `sub`, `mark`, `adv`, `fav`, `front`, `maker` (60 seeds each). To save disk, the daily
  equity arrays (`*_daily.npy`, `*_dmin.npy`) are kept only for `base`; the other tags keep metrics, stats and meta.
  Everything is deterministic (fixed seeds) and can be regenerated with `run_sim.py` + `boot.py`.
