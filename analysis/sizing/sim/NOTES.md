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

### Setup per TF (measured)

| TF | H (bars) | hold cap | signals/day tried | trades/30d taken (P0 A / P3 A / P4 A) | E\|r_H\| pooled | median ATR% (BTC..DOGE range) | q at D=0.10% (min-max over coins) | P5 mean L / M / notional | P6 mean L / M / notional |
|---|---|---|---|---|---|---|---|---|---|
| 5m | 16 | 1.33 h | 8.00 | 170 / 188 / 211 | 0.64% | 0.24-0.42% | 0.115-0.235 | 48.0x / 34% / 16.6x | 10.0x / 17.3% / 1.73x |
| 15m | 16 | 4 h | 4.50 | 79 / 102 / 120 | 1.11% | 0.40-0.74% | 0.066-0.134 | 42.1x / 27% / 11.8x | 10.0x / 11.3% / 1.13x |
| 1h | 16 | 16 h | 1.50 | 23 / 37 / 43 | 2.29% | 0.81-1.52% | 0.032-0.063 | 28.3x / 22% / 6.3x | 9.9x / 6.0% / 0.60x |
| 4h | 4 | 16 h | 0.43 | 11 / 12 / 13 | 2.29% | 1.64-3.16% | 0.032-0.062 | 20.7x / 20% / 4.2x | 9.4x / 3.2% / 0.30x |
| 1d | 4 | 96 h | 0.21 | 4 / 6 / 6 | 5.83% | 4.35-8.15% | 0.012-0.024 | 20.0x / 20% / 4.0x | 5.1x / 2.3% / 0.12x |

## 2. Results by timeframe (base case)

Each cell: 30-day median multiple / P(30-day loss) / P(equity < 50 % within 1 year) / P(ruin: equity < 10 % within 1 year).

### 5m: 30-day median multiple / P(30-day loss) / P(equity < 50% within 1y) / P(ruin < 10% within 1y)

TP = +10% ROE (price 10%/L) for P0-P5; P6 has no TP. Last two columns at D = 0.10%.

| policy | D=0.00% | D=0.10% | D=0.20% | D=0.40% | liq % of trades | 30d max DD (median) |
|---|---|---|---|---|---|---|
| P0 1x, 1.5ATR stop | 0.75 / 0.99 / 1.00 / 1.00 | 0.86 / 0.90 / 1.00 / 0.14 | 0.97 / 0.59 / 0.23 / 0.00 | 1.25 / 0.04 / 0.00 / 0.00 | 0.0 | 18% |
| P1 25%x5, 1.5ATR stop | 0.71 / 0.99 / 1.00 / 1.00 | 0.83 / 0.91 / 1.00 / 0.47 | 0.97 / 0.58 / 0.30 / 0.00 | 1.32 / 0.03 / 0.00 / 0.00 | 0.0 | 21% |
| P2 25%x10, 1.5ATR stop | 0.51 / 1.00 / 1.00 / 1.00 | 0.68 / 0.94 / 1.00 / 1.00 | 0.91 / 0.66 / 0.81 / 0.09 | 1.62 / 0.02 / 0.00 / 0.00 | 0.0 | 37% |
| P3 20%x20, no stop | 0.40 / 0.99 / 1.00 / 1.00 | 0.65 / 0.86 / 1.00 / 0.99 | 1.07 / 0.42 / 0.42 / 0.03 | 3.02 / 0.00 / 0.00 / 0.00 | 0.5 | 46% |
| P3 20%x20, stop 0.5 d_liq | 0.40 / 0.99 / 1.00 / 1.00 | 0.65 / 0.88 / 1.00 / 0.99 | 1.07 / 0.42 / 0.37 / 0.02 | 2.93 / 0.00 / 0.00 / 0.00 | 0.0 | 45% |
| P4 40%x50, no stop | 0.00 / 1.00 / 1.00 / 1.00 | 0.01 / 1.00 / 1.00 / 1.00 | 0.04 / 0.98 / 1.00 / 1.00 | 0.99 / 0.51 / 0.90 / 0.72 | 4.4 | 99% |
| P4 40%x50, stop 0.5 d_liq | 0.01 / 1.00 / 1.00 / 1.00 | 0.02 / 1.00 / 1.00 / 1.00 | 0.07 / 1.00 / 1.00 / 1.00 | 0.75 / 0.62 / 0.97 / 0.86 | 0.0 | 98% |
| P5 adaptive 20-40%, 20-50x, no stop | 0.01 / 1.00 / 1.00 / 1.00 | 0.03 / 1.00 / 1.00 / 1.00 | 0.11 / 0.97 / 1.00 / 1.00 | 1.71 / 0.30 / 0.48 / 0.12 | 4.0 | 98% |
| P5 adaptive, stop 0.5 d_liq | 0.02 / 1.00 / 1.00 / 1.00 | 0.05 / 1.00 / 1.00 / 1.00 | 0.15 / 0.99 / 1.00 / 1.00 | 1.22 / 0.40 / 0.60 / 0.17 | 0.0 | 95% |
| P5c perfect-confidence margin, stop 0.5 d_liq | 0.12 / 1.00 / 1.00 / 1.00 | 0.25 / 0.99 / 1.00 / 1.00 | 0.54 / 0.85 / 1.00 / 1.00 | 2.55 / 0.08 / 0.08 / 0.00 | 0.0 | 78% |
| P6 risk 1% to 1.5ATR stop, <=10x | 0.61 / 1.00 / 1.00 / 1.00 | 0.74 / 0.96 / 1.00 / 0.99 | 0.90 / 0.74 / 0.89 / 0.04 | 1.31 / 0.06 / 0.00 / 0.00 | 0.0 | 29% |
| P6h risk 0.5% | 0.78 / 1.00 / 1.00 / 0.99 | 0.86 / 0.95 / 1.00 / 0.03 | 0.95 / 0.73 / 0.46 / 0.00 | 1.15 / 0.06 / 0.00 / 0.00 | 0.0 | 16% |

### 15m: 30-day median multiple / P(30-day loss) / P(equity < 50% within 1y) / P(ruin < 10% within 1y)

TP = +10% ROE (price 10%/L) for P0-P5; P6 has no TP. Last two columns at D = 0.10%.

| policy | D=0.00% | D=0.10% | D=0.20% | D=0.40% | liq % of trades | 30d max DD (median) |
|---|---|---|---|---|---|---|
| P0 1x, 1.5ATR stop | 0.86 / 0.88 / 1.00 / 0.18 | 0.91 / 0.76 / 0.85 / 0.00 | 0.97 / 0.58 / 0.29 / 0.00 | 1.10 / 0.24 / 0.00 / 0.00 | 0.0 | 16% |
| P1 25%x5, 1.5ATR stop | 0.84 / 0.89 / 1.00 / 0.39 | 0.91 / 0.75 / 0.90 / 0.02 | 0.98 / 0.57 / 0.34 / 0.00 | 1.12 / 0.20 / 0.00 / 0.00 | 0.0 | 17% |
| P2 25%x10, 1.5ATR stop | 0.71 / 0.93 / 1.00 / 0.99 | 0.81 / 0.82 / 1.00 / 0.72 | 0.91 / 0.66 / 0.85 / 0.14 | 1.15 / 0.28 / 0.03 / 0.00 | 0.0 | 29% |
| P3 20%x20, no stop | 0.61 / 0.89 / 1.00 / 1.00 | 0.72 / 0.79 / 1.00 / 0.92 | 0.87 / 0.64 / 0.91 / 0.47 | 1.26 / 0.28 / 0.14 / 0.00 | 1.8 | 42% |
| P3 20%x20, stop 0.5 d_liq | 0.63 / 0.91 / 1.00 / 1.00 | 0.74 / 0.81 / 1.00 / 0.91 | 0.88 / 0.65 / 0.91 / 0.39 | 1.24 / 0.27 / 0.08 / 0.00 | 0.0 | 39% |
| P4 40%x50, no stop | 0.01 / 1.00 / 1.00 / 1.00 | 0.02 / 0.99 / 1.00 / 1.00 | 0.04 / 0.99 / 1.00 / 1.00 | 0.11 / 0.95 / 1.00 / 1.00 | 8.0 | 98% |
| P4 40%x50, stop 0.5 d_liq | 0.06 / 1.00 / 1.00 / 1.00 | 0.08 / 1.00 / 1.00 / 1.00 | 0.10 / 0.99 / 1.00 / 1.00 | 0.18 / 0.98 / 1.00 / 1.00 | 0.0 | 93% |
| P5 adaptive 20-40%, 20-50x, no stop | 0.13 / 0.99 / 1.00 / 1.00 | 0.19 / 0.97 / 1.00 / 1.00 | 0.26 / 0.95 / 1.00 / 1.00 | 0.51 / 0.80 / 1.00 / 0.99 | 6.5 | 85% |
| P5 adaptive, stop 0.5 d_liq | 0.22 / 0.99 / 1.00 / 1.00 | 0.28 / 0.99 / 1.00 / 1.00 | 0.34 / 0.97 / 1.00 / 1.00 | 0.53 / 0.88 / 1.00 / 1.00 | 0.0 | 77% |
| P5c perfect-confidence margin, stop 0.5 d_liq | 0.36 / 0.99 / 1.00 / 1.00 | 0.43 / 0.97 / 1.00 / 1.00 | 0.52 / 0.91 / 1.00 / 1.00 | 0.78 / 0.69 / 0.97 / 0.79 | 0.0 | 63% |
| P6 risk 1% to 1.5ATR stop, <=10x | 0.84 / 0.92 / 1.00 / 0.24 | 0.90 / 0.82 / 0.94 / 0.00 | 0.96 / 0.65 / 0.45 / 0.00 | 1.07 / 0.28 / 0.00 / 0.00 | 0.0 | 16% |
| P6h risk 0.5% | 0.92 / 0.91 / 0.93 / 0.00 | 0.95 / 0.81 / 0.40 / 0.00 | 0.98 / 0.64 / 0.02 / 0.00 | 1.04 / 0.27 / 0.00 / 0.00 | 0.0 | 8% |

### 1h: 30-day median multiple / P(30-day loss) / P(equity < 50% within 1y) / P(ruin < 10% within 1y)

TP = +10% ROE (price 10%/L) for P0-P5; P6 has no TP. Last two columns at D = 0.10%.

| policy | D=0.00% | D=0.10% | D=0.20% | D=0.40% | liq % of trades | 30d max DD (median) |
|---|---|---|---|---|---|---|
| P0 1x, 1.5ATR stop | 0.94 / 0.67 / 0.63 / 0.00 | 0.96 / 0.62 / 0.45 / 0.00 | 0.98 / 0.57 / 0.27 / 0.00 | 1.01 / 0.46 / 0.07 / 0.00 | 0.0 | 13% |
| P1 25%x5, 1.5ATR stop | 0.95 / 0.67 / 0.60 / 0.00 | 0.96 / 0.61 / 0.42 / 0.00 | 0.98 / 0.55 / 0.26 / 0.00 | 1.02 / 0.44 / 0.06 / 0.00 | 0.0 | 13% |
| P2 25%x10, 1.5ATR stop | 0.90 / 0.69 / 0.88 / 0.11 | 0.92 / 0.65 / 0.79 / 0.06 | 0.95 / 0.61 / 0.67 / 0.02 | 0.99 / 0.52 / 0.39 / 0.00 | 0.0 | 20% |
| P3 20%x20, no stop | 0.80 / 0.74 / 0.98 / 0.73 | 0.83 / 0.70 / 0.97 / 0.62 | 0.87 / 0.67 / 0.94 / 0.48 | 0.93 / 0.59 / 0.82 / 0.24 | 5.7 | 34% |
| P3 20%x20, stop 0.5 d_liq | 0.85 / 0.75 / 0.97 / 0.49 | 0.87 / 0.71 / 0.95 / 0.36 | 0.89 / 0.68 / 0.91 / 0.24 | 0.94 / 0.60 / 0.75 / 0.09 | 0.0 | 27% |
| P4 40%x50, no stop | 0.21 / 0.94 / 1.00 / 1.00 | 0.22 / 0.94 / 1.00 / 1.00 | 0.24 / 0.93 / 1.00 / 1.00 | 0.26 / 0.92 / 1.00 / 1.00 | 10.5 | 84% |
| P4 40%x50, stop 0.5 d_liq | 0.36 / 0.97 / 1.00 / 1.00 | 0.37 / 0.96 / 1.00 / 1.00 | 0.38 / 0.96 / 1.00 / 1.00 | 0.40 / 0.95 / 1.00 / 1.00 | 0.0 | 68% |
| P5 adaptive 20-40%, 20-50x, no stop | 0.68 / 0.80 / 1.00 / 0.97 | 0.71 / 0.78 / 1.00 / 0.94 | 0.74 / 0.76 / 1.00 / 0.90 | 0.80 / 0.70 / 0.98 / 0.77 | 8.0 | 44% |
| P5 adaptive, stop 0.5 d_liq | 0.77 / 0.82 / 1.00 / 0.86 | 0.79 / 0.79 / 1.00 / 0.79 | 0.81 / 0.77 / 0.99 / 0.72 | 0.85 / 0.73 / 0.97 / 0.54 | 0.0 | 33% |
| P5c perfect-confidence margin, stop 0.5 d_liq | 0.80 / 0.81 / 1.00 / 0.79 | 0.82 / 0.77 / 0.99 / 0.67 | 0.84 / 0.73 / 0.97 / 0.56 | 0.89 / 0.65 / 0.91 / 0.34 | 0.0 | 31% |
| P6 risk 1% to 1.5ATR stop, <=10x | 0.97 / 0.68 / 0.09 / 0.00 | 0.98 / 0.63 / 0.03 / 0.00 | 0.99 / 0.57 / 0.01 / 0.00 | 1.01 / 0.46 / 0.00 / 0.00 | 0.0 | 7% |
| P6h risk 0.5% | 0.98 / 0.68 / 0.00 / 0.00 | 0.99 / 0.62 / 0.00 / 0.00 | 0.99 / 0.57 / 0.00 / 0.00 | 1.00 / 0.46 / 0.00 / 0.00 | 0.0 | 3% |

### 4h: 30-day median multiple / P(30-day loss) / P(equity < 50% within 1y) / P(ruin < 10% within 1y)

TP = +10% ROE (price 10%/L) for P0-P5; P6 has no TP. Last two columns at D = 0.10%.

| policy | D=0.00% | D=0.10% | D=0.20% | D=0.40% | liq % of trades | 30d max DD (median) |
|---|---|---|---|---|---|---|
| P0 1x, 1.5ATR stop | 0.98 / 0.60 / 0.19 / 0.00 | 0.99 / 0.56 / 0.11 / 0.00 | 1.00 / 0.52 / 0.06 / 0.00 | 1.01 / 0.44 / 0.01 / 0.00 | 0.0 | 8% |
| P1 25%x5, 1.5ATR stop | 0.99 / 0.56 / 0.14 / 0.00 | 0.99 / 0.52 / 0.08 / 0.00 | 1.00 / 0.48 / 0.04 / 0.00 | 1.02 / 0.41 / 0.01 / 0.00 | 0.0 | 8% |
| P2 25%x10, 1.5ATR stop | 0.98 / 0.57 / 0.45 / 0.00 | 0.99 / 0.54 / 0.36 / 0.00 | 1.00 / 0.51 / 0.27 / 0.00 | 1.02 / 0.44 / 0.15 / 0.00 | 0.1 | 12% |
| P3 20%x20, no stop | 0.96 / 0.58 / 0.67 / 0.04 | 0.97 / 0.56 / 0.61 / 0.02 | 0.98 / 0.54 / 0.54 / 0.02 | 1.00 / 0.50 / 0.41 / 0.01 | 5.2 | 18% |
| P3 20%x20, stop 0.5 d_liq | 0.96 / 0.61 / 0.57 / 0.00 | 0.97 / 0.59 / 0.50 / 0.00 | 0.97 / 0.57 / 0.43 / 0.00 | 0.99 / 0.53 / 0.29 / 0.00 | 0.0 | 13% |
| P4 40%x50, no stop | 0.68 / 0.79 / 1.00 / 0.99 | 0.68 / 0.78 / 1.00 / 0.99 | 0.69 / 0.78 / 1.00 / 0.99 | 0.70 / 0.76 / 1.00 / 0.99 | 11.7 | 42% |
| P4 40%x50, stop 0.5 d_liq | 0.68 / 0.89 / 1.00 / 0.99 | 0.67 / 0.89 / 1.00 / 1.00 | 0.67 / 0.88 / 1.00 / 0.99 | 0.68 / 0.88 / 1.00 / 0.99 | 0.0 | 39% |
| P5 adaptive 20-40%, 20-50x, no stop | 0.95 / 0.59 / 0.70 / 0.04 | 0.97 / 0.57 / 0.64 / 0.03 | 0.98 / 0.54 / 0.57 / 0.02 | 1.00 / 0.51 / 0.43 / 0.01 | 5.4 | 19% |
| P5 adaptive, stop 0.5 d_liq | 0.96 / 0.61 / 0.59 / 0.00 | 0.96 / 0.59 / 0.52 / 0.00 | 0.97 / 0.57 / 0.45 / 0.00 | 0.99 / 0.53 / 0.32 / 0.00 | 0.0 | 13% |
| P5c perfect-confidence margin, stop 0.5 d_liq | 0.96 / 0.61 / 0.59 / 0.00 | 0.97 / 0.58 / 0.48 / 0.00 | 0.98 / 0.54 / 0.40 / 0.00 | 1.01 / 0.47 / 0.24 / 0.00 | 0.0 | 13% |
| P6 risk 1% to 1.5ATR stop, <=10x | 0.99 / 0.61 / 0.00 / 0.00 | 1.00 / 0.57 / 0.00 / 0.00 | 1.00 / 0.52 / 0.00 / 0.00 | 1.00 / 0.44 / 0.00 / 0.00 | 0.0 | 2% |
| P6h risk 0.5% | 1.00 / 0.61 / 0.00 / 0.00 | 1.00 / 0.57 / 0.00 / 0.00 | 1.00 / 0.52 / 0.00 / 0.00 | 1.00 / 0.44 / 0.00 / 0.00 | 0.0 | 1% |

### 1d: 30-day median multiple / P(30-day loss) / P(equity < 50% within 1y) / P(ruin < 10% within 1y)

TP = +10% ROE (price 10%/L) for P0-P5; P6 has no TP. Last two columns at D = 0.10%.

| policy | D=0.00% | D=0.10% | D=0.20% | D=0.40% | liq % of trades | 30d max DD (median) |
|---|---|---|---|---|---|---|
| P0 1x, 1.5ATR stop | 0.99 / 0.55 / 0.23 / 0.00 | 0.99 / 0.53 / 0.20 / 0.00 | 0.99 / 0.52 / 0.17 / 0.00 | 1.00 / 0.50 / 0.13 / 0.00 | 0.0 | 9% |
| P1 25%x5, 1.5ATR stop | 1.01 / 0.48 / 0.14 / 0.00 | 1.01 / 0.48 / 0.13 / 0.00 | 1.01 / 0.47 / 0.12 / 0.00 | 1.01 / 0.46 / 0.10 / 0.00 | 0.1 | 7% |
| P2 25%x10, 1.5ATR stop | 1.04 / 0.46 / 0.40 / 0.01 | 1.04 / 0.45 / 0.38 / 0.01 | 1.04 / 0.45 / 0.36 / 0.00 | 1.04 / 0.43 / 0.33 / 0.00 | 3.5 | 6% |
| P3 20%x20, no stop | 1.03 / 0.47 / 0.57 / 0.01 | 1.03 / 0.47 / 0.56 / 0.01 | 1.03 / 0.46 / 0.55 / 0.01 | 1.04 / 0.46 / 0.54 / 0.01 | 9.7 | 0% |
| P3 20%x20, stop 0.5 d_liq | 0.96 / 0.66 / 0.59 / 0.00 | 0.96 / 0.66 / 0.58 / 0.00 | 0.96 / 0.65 / 0.58 / 0.00 | 0.96 / 0.65 / 0.57 / 0.00 | 0.0 | 10% |
| P4 40%x50, no stop | 0.61 / 0.76 / 1.00 / 1.00 | 0.61 / 0.76 / 1.00 / 1.00 | 0.61 / 0.76 / 1.00 / 1.00 | 0.61 / 0.76 / 1.00 / 1.00 | 22.6 | 42% |
| P4 40%x50, stop 0.5 d_liq | 0.70 / 0.90 / 1.00 / 1.00 | 0.70 / 0.90 / 1.00 / 1.00 | 0.70 / 0.90 / 1.00 / 1.00 | 0.70 / 0.91 / 1.00 / 1.00 | 0.0 | 33% |
| P5 adaptive 20-40%, 20-50x, no stop | 1.03 / 0.47 / 0.57 / 0.01 | 1.03 / 0.47 / 0.56 / 0.01 | 1.03 / 0.46 / 0.55 / 0.01 | 1.04 / 0.46 / 0.54 / 0.01 | 9.7 | 0% |
| P5 adaptive, stop 0.5 d_liq | 0.96 / 0.66 / 0.59 / 0.00 | 0.96 / 0.66 / 0.58 / 0.00 | 0.96 / 0.65 / 0.58 / 0.00 | 0.96 / 0.65 / 0.57 / 0.00 | 0.0 | 10% |
| P5c perfect-confidence margin, stop 0.5 d_liq | 0.96 / 0.66 / 0.59 / 0.00 | 0.96 / 0.65 / 0.59 / 0.00 | 0.96 / 0.65 / 0.59 / 0.00 | 0.96 / 0.63 / 0.60 / 0.00 | 0.0 | 10% |
| P6 risk 1% to 1.5ATR stop, <=10x | 1.00 / 0.55 / 0.00 / 0.00 | 1.00 / 0.53 / 0.00 / 0.00 | 1.00 / 0.52 / 0.00 / 0.00 | 1.00 / 0.50 / 0.00 / 0.00 | 0.0 | 1% |
| P6h risk 0.5% | 1.00 / 0.55 / 0.00 / 0.00 | 1.00 / 0.53 / 0.00 / 0.00 | 1.00 / 0.52 / 0.00 / 0.00 | 1.00 / 0.50 / 0.00 / 0.00 | 0.0 | 1% |

### Whole IS span (2021-08 to 2024-06, ~35 months, one path per seed): median final multiple across seeds [share of seeds ruined]

| policy | TF | D=0.00% | D=0.10% | D=0.20% | D=0.40% |
|---|---|---|---|---|---|
| P0 1x | 5m | 3.98e-05 [1.00] | 0.00479 [1.00] | 0.518 [0.03] | 5.13e+03 [0.00] |
| P0 1x | 15m | 0.00449 [1.00] | 0.0453 [0.81] | 0.448 [0.04] | 39.3 [0.00] |
| P0 1x | 1h | 0.128 [0.45] | 0.258 [0.17] | 0.49 [0.06] | 1.96 [0.00] |
| P0 1x | 4h | 0.439 [0.02] | 0.645 [0.00] | 0.877 [0.00] | 1.77 [0.00] |
| P0 1x | 1d | 0.514 [0.03] | 0.579 [0.02] | 0.677 [0.02] | 0.903 [0.01] |
| P3 20%x20 | 5m | 2.15e-15 [1.00] | 1.45e-07 [1.00] | 8.84 [0.07] | 1.09e+17 [0.00] |
| P3 20%x20 | 15m | 1.39e-08 [1.00] | 6.76e-06 [1.00] | 0.00468 [0.94] | 1.82e+03 [0.00] |
| P3 20%x20 | 1h | 0.000285 [1.00] | 0.000764 [1.00] | 0.00345 [0.96] | 0.0364 [0.78] |
| P3 20%x20 | 4h | 0.106 [0.55] | 0.154 [0.42] | 0.227 [0.34] | 0.464 [0.16] |
| P3 20%x20 | 1d | 0.129 [0.46] | 0.13 [0.44] | 0.149 [0.42] | 0.154 [0.38] |
| P4 40%x50 | 5m | 8.05e-103 [1.00] | 1.02e-77 [1.00] | 2.96e-53 [1.00] | 0.00298 [0.95] |
| P4 40%x50 | 15m | 1.52e-67 [1.00] | 2.72e-60 [1.00] | 5.37e-53 [1.00] | 6.24e-37 [1.00] |
| P4 40%x50 | 1h | 9e-27 [1.00] | 5.09e-26 [1.00] | 7e-25 [1.00] | 2.62e-23 [1.00] |
| P4 40%x50 | 4h | 6.14e-10 [1.00] | 1.04e-09 [1.00] | 2.31e-09 [1.00] | 8.99e-09 [1.00] |
| P4 40%x50 | 1d | 2.22e-11 [1.00] | 3.21e-11 [1.00] | 2.59e-11 [1.00] | 2.32e-11 [1.00] |
| P5 adaptive | 5m | 1.39e-77 [1.00] | 3.65e-57 [1.00] | 1.11e-35 [1.00] | 1.02e+07 [0.05] |
| P5 adaptive | 15m | 3.07e-32 [1.00] | 4.11e-27 [1.00] | 5.21e-22 [1.00] | 6.45e-12 [1.00] |
| P5 adaptive | 1h | 5.57e-07 [1.00] | 2.71e-06 [1.00] | 9.08e-06 [1.00] | 0.000113 [1.00] |
| P5 adaptive | 4h | 0.0926 [0.56] | 0.139 [0.47] | 0.201 [0.36] | 0.4 [0.19] |
| P5 adaptive | 1d | 0.129 [0.46] | 0.13 [0.44] | 0.149 [0.42] | 0.154 [0.38] |
| P6 1% risk | 5m | 2.5e-08 [1.00] | 2.74e-05 [1.00] | 0.025 [0.90] | 1.52e+04 [0.00] |
| P6 1% risk | 15m | 0.00287 [1.00] | 0.026 [0.99] | 0.204 [0.17] | 13.9 [0.00] |
| P6 1% risk | 1h | 0.38 [0.01] | 0.528 [0.00] | 0.738 [0.00] | 1.49 [0.00] |
| P6 1% risk | 4h | 0.816 [0.00] | 0.906 [0.00] | 0.987 [0.00] | 1.17 [0.00] |
| P6 1% risk | 1d | 0.945 [0.00] | 0.961 [0.00] | 0.976 [0.00] | 1 [0.00] |
| P6h 0.5% risk | 5m | 0.000163 [1.00] | 0.00545 [1.00] | 0.167 [0.14] | 133 [0.00] |
| P6h 0.5% risk | 15m | 0.0565 [0.95] | 0.171 [0.07] | 0.478 [0.00] | 3.97 [0.00] |
| P6h 0.5% risk | 1h | 0.629 [0.00] | 0.743 [0.00] | 0.877 [0.00] | 1.25 [0.00] |
| P6h 0.5% risk | 4h | 0.906 [0.00] | 0.954 [0.00] | 0.997 [0.00] | 1.09 [0.00] |
| P6h 0.5% risk | 1d | 0.973 [0.00] | 0.981 [0.00] | 0.989 [0.00] | 1 [0.00] |

**1d note.** The 1d rows above use the bar-colour intrabar rule, which is too pessimistic for tight-TP policies on
daily bars (section 6). With exits resolved on 5m sub-bars, at zero edge: P3 1d has a 1-year median of x0.70 (not
x0.53) and P(<50 % within 1 year) of 0.40, and P4 1d has x0.094 and 0.94. The verdict is the same. 15m-4h are
affected much less (P3 minimum edges with sub-bars are within 0.1 % of base: 15m 0.28-0.42 vs 0.28-0.43, 1h 0.64-0.84
vs 0.69-0.86, 4h 0.55-0.61 vs 0.58-0.67).

## 3. Minimum edge for the user's rules

Criterion: median 1-year multiple > 1 AND P(ruin within 1 year) < 10 %. D* is the planted gross drift per trade at
horizon H (linear interpolation on the D grid; it must hold at every larger D tested).

### Minimum planted gross drift per trade (%, at horizon H) for median 1-year multiple > 1 AND P(ruin within 1y) < 10%

'>X' = not reached up to the largest feasible planted drift X (q <= 1 on every coin).

| policy | 5m | 15m | 1h | 4h | 1d |
|---|---|---|---|---|---|
| P0 1x, no stop (time exit) | 0.15 | 0.16 | 0.21 | 0.21 | 0.44 |
| P0 1x, 1.5ATR stop | 0.22 | 0.24 | 0.30 | 0.24 | 0.41 |
| P2 25%x10, stop 0.5 d_liq | 0.15 | 0.18 | 0.32 | 0.34 | 1.56 |
| P3 20%x20 TP10 no stop | 0.19 | 0.29 | 0.69 | 0.62 | >3.00 |
| P3 TP10 1.5ATR stop | 0.29 | 0.43 | 0.86 | 0.58 | >3.00 |
| P3 TP10 stop 0.5 d_liq | 0.19 | 0.28 | 0.71 | 0.67 | >3.00 |
| P3 TP30 1.5ATR stop | 0.28 | 0.29 | 0.44 | 0.42 | 2.04 |
| P3 TP100 1.5ATR stop | 0.28 | 0.31 | 0.54 | 0.42 | 1.72 |
| P4 40%x50 TP10 no stop | >0.40 | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP10 1.5ATR | >0.40 | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP10 stop 0.5 d_liq | >0.40 | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP100 1.5ATR | 0.40 | >0.60 | >1.50 | >1.50 | >3.00 |
| P5 adaptive TP10 no stop | >0.40 | >0.60 | 1.07 | 0.64 | >3.00 |
| P5 TP10 1.5ATR | >0.40 | >0.60 | 1.23 | 0.60 | >3.00 |
| P5 TP10 stop 0.5 d_liq | >0.40 | >0.60 | 1.25 | 0.70 | >3.00 |
| P5 TP100 1.5ATR | 0.38 | 0.53 | 0.66 | 0.42 | 1.72 |
| P5c perfect confidence, stop 0.5 d_liq | 0.32 | >0.60 | 0.91 | 0.44 | >3.00 |
| P6 risk 1%, <=10x | 0.25 | 0.27 | 0.30 | 0.23 | 0.31 |
| P6h risk 0.5%, <=10x | 0.25 | 0.27 | 0.28 | 0.23 | 0.29 |

What a realistic-cost backtest of the same strategy would have to show per trade at D* (realised gross move and net
per unit notional, both in %):

#### tag=base: min planted drift D* (%) -> realised gross / net per unit notional (%) per trade at D*
| policy | 5m | 15m | 1h | 4h | 1d |
|---|---|---|---|---|---|
| P0 1x 1.5ATR | 0.22 -> +0.146 / +0.005 | 0.24 -> +0.154 / +0.010 | 0.30 -> +0.195 / +0.042 | 0.24 -> +0.213 / +0.056 | 0.41 -> +0.462 / +0.230 |
| P3 20%x20 TP10 no stop | 0.19 -> +0.129 / +0.013 | 0.29 -> +0.134 / +0.022 | 0.69 -> +0.153 / +0.033 | 0.62 -> +0.149 / +0.027 | >3.00 |
| P3 TP10 stop .5dliq | 0.19 -> +0.126 / +0.012 | 0.28 -> +0.119 / +0.013 | 0.71 -> +0.120 / +0.018 | 0.67 -> +0.121 / +0.015 | >3.00 |
| P3 TP100 1.5ATR | 0.28 -> +0.193 / +0.052 | 0.31 -> +0.205 / +0.062 | 0.54 -> +0.353 / +0.201 | 0.42 -> +0.340 / +0.161 | 1.72 -> +0.759 / +0.419 |
| P4 40%x50 TP10 | >0.40 | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP100 1.5ATR | 0.40 -> +0.265 / +0.125 | >0.60 | >1.50 | >1.50 | >3.00 |
| P5 TP10 no stop | >0.40 | >0.60 | 1.07 -> +0.164 / +0.045 | 0.64 -> +0.150 / +0.028 | >3.00 |
| P5 TP10 stop .5dliq | >0.40 | >0.60 | 1.25 -> +0.121 / +0.022 | 0.70 -> +0.120 / +0.015 | >3.00 |
| P5 TP100 1.5ATR | 0.38 -> +0.264 / +0.126 | 0.53 -> +0.351 / +0.214 | 0.66 -> +0.414 / +0.266 | 0.42 -> +0.340 / +0.162 | 1.72 -> +0.759 / +0.419 |
| P6 1% risk | 0.25 -> +0.172 / +0.030 | 0.27 -> +0.173 / +0.029 | 0.30 -> +0.176 / +0.021 | 0.23 -> +0.180 / +0.021 | 0.31 -> +0.319 / +0.068 |
| P6h 0.5% risk | 0.25 -> +0.170 / +0.029 | 0.27 -> +0.169 / +0.025 | 0.28 -> +0.167 / +0.012 | 0.23 -> +0.174 / +0.016 | 0.29 -> +0.301 / +0.050 |

Reading: for P3 with the +10 % ROE TP, the *realised* net needed is small (+0.013 to +0.033 %/trade on 5m-4h),
because the tight TP keeps each trade's variance low. But producing that realised net needs 0.19-0.71 % of planted
drift, because the TP throws most of the drift away (next table). P4 never gets there.

### Edge capture (slope of realised gross move per trade vs planted drift, edges <= 0.40%) and liquidation share at D=0

| policy | 5m | 15m | 1h | 4h | 1d |
|---|---|---|---|---|---|
| P0 time exit | 1.01 (liq 0.0%) | 1.01 (liq 0.0%) | 1.03 (liq 0.0%) | 0.99 (liq 0.0%) | 1.07 (liq 0.1%) |
| P0 1.5ATR stop | 0.72 (liq 0.0%) | 0.71 (liq 0.0%) | 0.71 (liq 0.0%) | 0.93 (liq 0.0%) | 0.98 (liq 0.0%) |
| P3 TP10 (0.5% price) | 0.64 (liq 0.6%) | 0.41 (liq 2.0%) | 0.20 (liq 5.9%) | 0.19 (liq 5.4%) | 0.04 (liq 9.7%) |
| P3 TP100 (5% price) | 0.71 (liq 0.0%) | 0.70 (liq 0.1%) | 0.67 (liq 1.5%) | 0.85 (liq 7.5%) | 0.49 (liq 43.5%) |
| P4 TP10 (0.2% price) | 0.28 (liq 5.1%) | 0.14 (liq 8.6%) | 0.04 (liq 10.7%) | 0.04 (liq 11.9%) | -0.00 (liq 22.6%) |
| P5 TP10 | 0.31 (liq 4.6%) | 0.20 (liq 7.0%) | 0.14 (liq 8.3%) | 0.18 (liq 5.6%) | 0.04 (liq 9.7%) |
| P6 | 0.71 (liq 0.0%) | 0.70 (liq 0.0%) | 0.71 (liq 0.0%) | 0.93 (liq 0.0%) | 1.03 (liq 0.0%) |

### Growth-optimal (full Kelly) notional for the reference exit (1.5 ATR stop + time exit, cross margin, realistic costs)

Planted drift at which full Kelly notional reaches 1x / 4x (= P3's floor, M 20% x L 20) / 8x (P3 = half Kelly) / 20x (P4). 'never' = not reached at any feasible planted drift (exact Kelly is also capped at 1/|worst trade|).

| TF | net mean per trade at D=0 | Kelly N at D=0.10% | Kelly N at D=0.20% | Kelly N at D=0.40% | D for N*=1x | D for N*=4x | D for N*=8x | D for N*=20x | Kelly cap (1/worst) |
|---|---|---|---|---|---|---|---|---|---|
| 5m | -0.149% | 0.00 | 0.00 | 9.00 | 0.21 | 0.24 | 0.29 | never | 9.00 |
| 15m | -0.157% | 0.00 | 0.00 | 6.00 | 0.24 | 0.34 | never | never | 6.25 |
| 1h | -0.171% | 0.00 | 0.00 | 1.50 | 0.35 | never | never | never | 3.75 |
| 4h | -0.173% | 0.00 | 0.20 | 2.00 | 0.29 | never | never | never | 2.95 |
| 1d | -0.177% | 0.00 | 0.05 | 0.45 | 0.69 | 3.00 | never | never | 4.00 |

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

| policy | 5m: 30d / 1y | 15m: 30d / 1y | 1h: 30d / 1y | 4h: 30d / 1y | 1d: 30d / 1y |
|---|---|---|---|---|---|
| P0 1x, time exit | x0.921 / x0.388 | x0.954 / x0.585 | x0.975 / x0.717 | x0.992 / x0.863 | x0.993 / x0.85 |
| P0 1x, 1.5ATR stop | x0.858 / x0.16 | x0.914 / x0.347 | x0.959 / x0.618 | x0.986 / x0.838 | x0.989 / x0.862 |
| P3 20%x20 (user minimum) | x0.651 / x0.00457 | x0.723 / x0.0173 | x0.833 / x0.0887 | x0.969 / x0.519 | x1.03 / x0.537 |
| P4 40%x50 (user style) | x0.00764 / x5.13e-27 | x0.0229 / x4.11e-21 | x0.224 / x2.33e-09 | x0.677 / x0.000927 | x0.608 / x0.000241 |
| P5 user-adaptive | x0.0277 / x7.11e-20 | x0.189 / x9.21e-10 | x0.708 / x0.0113 | x0.966 / x0.494 | x1.03 / x0.537 |
| P6 1 % risk | x0.744 / x0.028 | x0.899 / x0.284 | x0.977 / x0.789 | x0.996 / x0.957 | x0.999 / x0.991 |
| P6h 0.5 % risk | x0.863 / x0.17 | x0.95 / x0.543 | x0.989 / x0.894 | x0.998 / x0.979 | x0.999 / x0.996 |

So at the best edge ever seen (and that one failed OOS), the user's minimum loses 91-99.5 % in a year on 5m-1h and
46-48 % on 4h/1d; P4 is gone within weeks; the only policies that keep most of the money are the small ones on the
slower timeframes, and they also lose, slowly.

## 5. How fast it goes wrong when the edge is not there (the base case in this project)

At zero planted edge: P(−20 % from peak within 30 days) / median days to −20 % / median equity when a −20 % kill switch fires.

| policy | 5m | 15m | 1h | 4h | 1d |
|---|---|---|---|---|---|
| P0 1x | 0.84 / 21 d / 0.80 | 0.46 / 32 d / 0.81 | 0.22 / 53 d / 0.84 | 0.05 / 108 d / 0.85 | 0.11 / 89 d / 0.87 |
| P3 20%x20 | 1.00 / 6 d / 0.78 | 0.97 / 8 d / 0.80 | 0.88 / 11 d / 0.84 | 0.50 / 30 d / 0.86 | 0.45 / 34 d / 0.87 |
| P4 40%x50 | 1.00 / 2 d / 0.63 | 1.00 / 2 d / 0.63 | 0.99 / 5 d / 0.65 | 0.80 / 14 d / 0.65 | 0.76 / 15 d / 0.60 |
| P5 adaptive | 1.00 / 2 d / 0.69 | 1.00 / 3 d / 0.76 | 0.96 / 7 d / 0.83 | 0.51 / 29 d / 0.86 | 0.45 / 34 d / 0.87 |
| P6 1 % risk | 0.99 / 12 d / 0.79 | 0.46 / 32 d / 0.80 | 0.00 / 139 d / 0.83 | 0.00 / - / 0.80 | 0.00 / - / - |
| P6h 0.5 % risk | 0.71 / 26 d / 0.80 | 0.00 / 71 d / 0.80 | 0.00 / 351 d / 0.81 | 0.00 / - / - | 0.00 / - / - |

- At zero edge, P4 hits −20 % from peak in a median of 2 days (5m/15m), 5 days (1h), 14-15 days (4h/1d); a −20 % kill
  switch fires only after one liquidation has already cost 40 %, so equity at the stop is ~0.60-0.65, not 0.80.
- P3 hits −20 % in 6-9 days (5m/15m), 11-18 days (1h), 30-73 days (4h/1d).
- P6 at 5m hits −20 % in 12 days at zero edge: 187 trades/month × 1.7x notional × 0.15 % cost ≈ −48 %/month. Even a
  "correct" risk-per-trade rule needs a cost budget on high-frequency timeframes (section 7).

## 6. Sensitivities

Cell = D* planted drift (%) for median 1y > 1 and P(ruin 1y) < 10%; in brackets the realised gross move per trade (%) at D*.

- base: base (raw wicks, O-L-H-C/O-H-L-C by bar colour, taker entry, edge at H)
- sub: exits resolved on the 5m bars inside each TF bar (15m/1h/4h/1d); the preferred check of intrabar order
- mark: liquidation checked on a de-spiked price (wick parts > 0.5 ATR beyond the neighbouring bars removed; mark-price proxy); stops/TPs on raw bars
- adv: adverse move first inside every bar
- fav: favourable move first inside every bar
- front: edge planted at H/4 bars (front-loaded; 1 bar on 4h/1d)
- maker: maker (limit) entry 0.02 %, always filled

| policy | variant | 5m | 15m | 1h | 4h | 1d |
|---|---|---|---|---|---|---|
| P0 1x 1.5ATR | base | 0.22 (+0.15) | 0.24 (+0.15) | 0.30 (+0.20) | 0.24 (+0.21) | 0.41 (+0.46) |
| P0 1x 1.5ATR | sub | - | 0.23 (+0.16) | 0.29 (+0.19) | 0.23 (+0.21) | 0.34 (+0.45) |
| P0 1x 1.5ATR | mark | - | 0.23 (+0.16) | 0.29 (+0.19) | 0.23 (+0.21) | 0.34 (+0.47) |
| P0 1x 1.5ATR | adv | - | 0.23 (+0.16) | 0.29 (+0.19) | 0.24 (+0.21) | 0.36 (+0.47) |
| P0 1x 1.5ATR | fav | - | 0.23 (+0.16) | 0.29 (+0.19) | 0.22 (+0.21) | 0.33 (+0.47) |
| P0 1x 1.5ATR | front | 0.16 (+0.15) | 0.18 (+0.16) | 0.21 (+0.19) | 0.23 (+0.21) | 0.30 (+0.47) |
| P0 1x 1.5ATR | maker | 0.14 (+0.10) | 0.16 (+0.11) | 0.22 (+0.14) | 0.18 (+0.16) | - |
| P3 20%x20 TP10 no stop | base | 0.19 (+0.13) | 0.29 (+0.13) | 0.69 (+0.15) | 0.62 (+0.15) | >3.00 |
| P3 20%x20 TP10 no stop | sub | - | 0.29 (+0.13) | 0.64 (+0.15) | 0.61 (+0.15) | 2.04 (+0.16) |
| P3 20%x20 TP10 no stop | mark | - | 0.28 (+0.14) | 0.53 (+0.15) | 0.50 (+0.15) | >3.00 |
| P3 20%x20 TP10 no stop | adv | - | 0.29 (+0.13) | 0.71 (+0.15) | 1.02 (+0.15) | >3.00 |
| P3 20%x20 TP10 no stop | fav | - | 0.29 (+0.13) | 0.63 (+0.15) | 0.54 (+0.15) | 0.94 (+0.18) |
| P3 20%x20 TP10 no stop | front | 0.14 (+0.13) | 0.18 (+0.14) | 0.31 (+0.15) | 0.32 (+0.15) | 1.94 (+0.18) |
| P3 20%x20 TP10 no stop | maker | 0.13 (+0.09) | 0.18 (+0.09) | 0.43 (+0.11) | 0.40 (+0.11) | - |
| P3 TP10 stop .5dliq | base | 0.19 (+0.13) | 0.28 (+0.12) | 0.71 (+0.12) | 0.67 (+0.12) | >3.00 |
| P3 TP10 stop .5dliq | sub | - | 0.28 (+0.12) | 0.68 (+0.12) | 0.57 (+0.12) | 2.04 (+0.12) |
| P3 TP10 stop .5dliq | mark | - | 0.28 (+0.12) | 0.69 (+0.12) | 0.68 (+0.12) | >3.00 |
| P3 TP10 stop .5dliq | adv | - | 0.30 (+0.12) | 0.90 (+0.12) | >1.50 | >3.00 |
| P3 TP10 stop .5dliq | fav | - | 0.28 (+0.12) | 0.62 (+0.12) | 0.36 (+0.12) | 0.00 (+0.22) |
| P3 TP10 stop .5dliq | front | 0.14 (+0.13) | 0.16 (+0.12) | 0.26 (+0.12) | 0.30 (+0.12) | >2.00 |
| P3 TP10 stop .5dliq | maker | 0.12 (+0.08) | 0.16 (+0.07) | 0.37 (+0.07) | 0.35 (+0.08) | - |
| P4 40%x50 TP10 no stop | base | >0.40 | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 40%x50 TP10 no stop | sub | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 40%x50 TP10 no stop | mark | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 40%x50 TP10 no stop | adv | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 40%x50 TP10 no stop | fav | - | >0.60 | >1.50 | >1.50 | 2.36 (+0.15) |
| P4 40%x50 TP10 no stop | front | >0.20 | >0.30 | >0.60 | >0.60 | >2.00 |
| P4 40%x50 TP10 no stop | maker | 0.38 (+0.11) | >0.60 | >1.50 | >1.50 | - |
| P4 TP100 1.5ATR | base | 0.40 (+0.26) | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP100 1.5ATR | sub | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP100 1.5ATR | mark | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP100 1.5ATR | adv | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP100 1.5ATR | fav | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P4 TP100 1.5ATR | front | >0.20 | >0.30 | >0.60 | >0.60 | >2.00 |
| P4 TP100 1.5ATR | maker | 0.32 (+0.22) | >0.60 | >1.50 | >1.50 | - |
| P5 TP10 no stop | base | >0.40 | >0.60 | 1.07 (+0.16) | 0.64 (+0.15) | >3.00 |
| P5 TP10 no stop | sub | - | >0.60 | 1.02 (+0.16) | 0.63 (+0.15) | 2.04 (+0.16) |
| P5 TP10 no stop | mark | - | >0.60 | 0.85 (+0.16) | 0.53 (+0.15) | >3.00 |
| P5 TP10 no stop | adv | - | >0.60 | 1.12 (+0.16) | 1.04 (+0.15) | >3.00 |
| P5 TP10 no stop | fav | - | >0.60 | 1.00 (+0.16) | 0.57 (+0.15) | 0.94 (+0.18) |
| P5 TP10 no stop | front | >0.20 | >0.30 | 0.46 (+0.17) | 0.33 (+0.15) | 1.94 (+0.18) |
| P5 TP10 no stop | maker | 0.29 (+0.10) | 0.55 (+0.13) | 0.75 (+0.12) | 0.41 (+0.11) | - |
| P5 TP10 stop .5dliq | base | >0.40 | >0.60 | 1.25 (+0.12) | 0.70 (+0.12) | >3.00 |
| P5 TP10 stop .5dliq | sub | - | >0.60 | 1.23 (+0.12) | 0.60 (+0.12) | 2.04 (+0.12) |
| P5 TP10 stop .5dliq | mark | - | >0.60 | 1.25 (+0.12) | 0.71 (+0.12) | >3.00 |
| P5 TP10 stop .5dliq | adv | - | >0.60 | >1.50 | >1.50 | >3.00 |
| P5 TP10 stop .5dliq | fav | - | >0.60 | 1.11 (+0.12) | 0.38 (+0.12) | 0.00 (+0.22) |
| P5 TP10 stop .5dliq | front | >0.20 | 0.29 (+0.13) | 0.36 (+0.12) | 0.31 (+0.12) | >2.00 |
| P5 TP10 stop .5dliq | maker | 0.28 (+0.08) | 0.43 (+0.07) | 0.61 (+0.07) | 0.36 (+0.07) | - |
| P6 1% risk | base | 0.25 (+0.17) | 0.27 (+0.17) | 0.30 (+0.18) | 0.23 (+0.18) | 0.31 (+0.32) |
| P6 1% risk | sub | - | 0.27 (+0.17) | 0.28 (+0.17) | 0.23 (+0.17) | 0.26 (+0.29) |
| P6 1% risk | mark | - | 0.27 (+0.17) | 0.27 (+0.17) | 0.23 (+0.17) | 0.25 (+0.29) |
| P6 1% risk | adv | - | 0.27 (+0.17) | 0.27 (+0.17) | 0.23 (+0.17) | 0.25 (+0.29) |
| P6 1% risk | fav | - | 0.27 (+0.17) | 0.27 (+0.17) | 0.23 (+0.17) | 0.25 (+0.29) |
| P6 1% risk | front | 0.19 (+0.17) | 0.21 (+0.17) | 0.21 (+0.17) | 0.22 (+0.17) | 0.20 (+0.28) |
| P6 1% risk | maker | 0.17 (+0.11) | 0.19 (+0.12) | 0.19 (+0.11) | 0.17 (+0.11) | - |
| P6h 0.5% risk | base | 0.25 (+0.17) | 0.27 (+0.17) | 0.28 (+0.17) | 0.23 (+0.17) | 0.29 (+0.30) |
| P6h 0.5% risk | sub | - | 0.27 (+0.17) | 0.27 (+0.16) | 0.22 (+0.16) | 0.24 (+0.28) |
| P6h 0.5% risk | mark | - | 0.27 (+0.17) | 0.26 (+0.16) | 0.22 (+0.16) | 0.24 (+0.28) |
| P6h 0.5% risk | adv | - | 0.27 (+0.17) | 0.26 (+0.16) | 0.22 (+0.16) | 0.24 (+0.28) |
| P6h 0.5% risk | fav | - | 0.27 (+0.17) | 0.26 (+0.16) | 0.22 (+0.16) | 0.24 (+0.28) |
| P6h 0.5% risk | front | 0.19 (+0.17) | 0.20 (+0.17) | 0.20 (+0.17) | 0.22 (+0.16) | 0.20 (+0.27) |
| P6h 0.5% risk | maker | 0.17 (+0.11) | 0.18 (+0.11) | 0.18 (+0.11) | 0.16 (+0.11) | - |

- **Intrabar order: 5m sub-bars (`sub`) are the reference.** Resolving every exit on the 5m bars inside the trade
  barely changes 15m-4h: P3's minimum edge is 0.29 % (base 0.29) on 15m, 0.64-0.84 % (base 0.69-0.86) on 1h and
  0.55-0.61 % (base 0.58-0.67) on 4h. On **1d** it matters, because a daily bar usually touches both a 0.2-0.5 % TP and
  the stop or liquidation level. The bar-colour rule was too pessimistic there. With sub-bars, P3 needs about **2.0 %**
  (base: not reached up to 3 %). P4's 1d liquidation share drops from 22.6 % to 9.8 %. The verdict does not change:
  - P3 at zero edge: 1-year median x0.70 (base x0.53), P(<50 % within 1 year) 0.40.
  - P4 at zero edge: 1-year median x0.094, P(<50 %) 0.94, P(ruin) 0.58.
  - Both look fine month to month. The 30-day median is x1.05 for P3 and x1.07 for P4, with a median 30-day max
    drawdown of 0 % and a 90 % win rate.
  - `adv` (adverse first in every bar) and `fav` (favourable first) bracket the answer. `fav` cannot happen on daily
    bars: it books a TP whenever a bar touches both levels. It is the only variant in which P3/P4 with a stop look
    profitable at zero edge on 1d.
- **Mark-price proxy for liquidation (`mark`).** Wick parts sticking out more than 0.5 ATR beyond the neighbouring bars
  are removed for the liquidation check only. This touches 3.5-6 % of bars.
  - Liquidation shares fall only slightly: P3 2.0 → 1.6 % (15m), 5.9 → 5.1 % (1h), 5.4 → 4.7 % (4h); P4 22.6 → 22.1 % (1d).
  - P3's minimum edge moves 0.69 → 0.53 % (1h) and 0.62 → 0.50 % (4h); 15m is unchanged (0.28 %). P4 still fails
    everywhere.
  - So the liquidations come from real moves, not from spikes in the spot data.
- **Front-loaded edge (`front`).** Here the whole planted drift arrives in the first quarter of the holding period
  (H/4 bars; 1 bar on 4h/1d). This is the case most favourable to a tight TP. Minimum planted drift:
  - P3: 0.14-0.32 % on 5m-4h, 1.9 % on 1d (bar-colour rule).
  - P5: 0.29 % on 15m with a stop (not reached without one), 0.36-0.46 % on 1h, 0.27-0.33 % on 4h; not reached on 5m.
  - P4: not reached anywhere.
  - In realised terms the requirement matches the base case. With its own exits, P3 must show a realised gross move of
    about +0.12-0.15 % and a net of +0.013-0.033 % per trade per unit notional.
- **Maker entries (`maker`, optimistic: every limit entry fills).** Cutting the entry cost from 0.07 % to 0.02 % lowers
  every requirement by 0.05-0.3 %:
  - P3: 0.12-0.13 % (5m), 0.16-0.18 % (15m), 0.38-0.43 % (1h), 0.30-0.40 % (4h).
  - P6: 0.16-0.19 %.
  - P4 becomes feasible only on 5m (0.30-0.39 %).
  - At D = 0.10 %, the 1x-2.5x no-stop policies on 5m/15m now grow slightly (1-year median x1.02-1.17). Nothing at 4x
    notional or more does.
  - All of these are still above every OOS-validated edge in this project; none of those is above 0.

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

| chart state | stop distance | N at R=0.5 % | N at R=1 % | max L (liq >= 2x stop, <= 10x) | L if M = 20 % (R=0.5 %) | 1-ATR adverse move costs (R=0.5 %) |
|---|---|---|---|---|---|---|
| 5m, calm (ATR 0.25 %) | 0.38 % | 0.97x | 1.94x | 10x | 4.9x | 0.24 % of equity |
| 15m BTC typical (ATR 0.40 %) | 0.60 % | 0.68x | 1.35x | 10x | 3.4x | 0.27 % of equity |
| 15m SOL typical (ATR 0.74 %) | 1.11 % | 0.40x | 0.80x | 10x | 2.0x | 0.30 % of equity |
| 1h typical (ATR 1.0 %) | 1.50 % | 0.30x | 0.61x | 10x | 1.5x | 0.30 % of equity |
| 4h typical / 15m in a crash (ATR 2.0 %) | 3.00 % | 0.16x | 0.32x | 10x | 1x with M = N | 0.32 % of equity |
| 1d typical (ATR 5.0 %) | 7.50 % | 0.07x | 0.13x | 6x | 1x with M = N | 0.33 % of equity |

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
