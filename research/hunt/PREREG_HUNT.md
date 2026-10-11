# Trend hunt v1 (추세 사냥): pre-registration

(한국어 설명: `README_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면
`DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (KST), before any data for this study was downloaded and before any code for it
existed. Reviewed and corrected the same day, before the pin, after the 30-coin data had been built and the code
drafted; no trading outcome had been computed on any period (section 19.2 lists every change).** The open questions of
section 18 are closed by the owners (or by the default written next to each) before the file is pinned. Pinning =
`PREREG_HUNT.sha256` over this file, the study's code and the files of section 16; the code refuses the `select` and
`test` steps without a matching pin. After the pin nothing here changes; a change goes to `DEVIATIONS.md` with its
reason and date.

Owners' brief (2026-10-11): a "trend hunt" system, 스캐너 → 장세 문지기 → 진입·첫 손절 → 불타기 → 추적 손절 청산, on
many coins, tested before the mid-November 2026 review ("11월 중순까지는 성공시키고 싶어 ... 일단 계획을 그렇게 잡아보자").

## 1. Question

On a fixed 30-coin universe, does one rule-based trend-following system (breakout-type entry, regime gate, ATR first
stop, pyramiding with the open risk held at one unit, chandelier trailing exit, portfolio limits) grow one wallet after
all costs on data its choice never saw, and does it beat the same machine fed with random entry times and with
coin-flip sides?

## 2. Data

* Binance USD-M public archive (data.binance.vision), every file checked against its `.CHECKSUM` (sha256): the monthly
  `data/futures/um/monthly/klines/<SYM>/5m/`, `markPriceKlines/<SYM>/5m/` and `fundingRate/<SYM>/` files from the
  coin's first archived month (2020-01 at the earliest) to 2026-09. Where a monthly file lacks whole days, those days
  come from the official daily files of the same archive (checksum-verified; only absent bars are added). Built by the
  `coins30` data job on 2026-10-11 (6,657 monthly and 298 daily files) into one file per coin, `5m/<SYM>.npz` (open
  time, OHLC, base and quote volume, mark-price OHLC) and `funding/<SYM>.npz`, plus `manifest.json` (coverage, gaps,
  the last bar with volume, each file's sha256). The last period ends 2026-10-01 00:00 UTC; open positions are marked
  there (section 10).
* 5m bars as the study reads them: duplicate open times dropped (last kept), off-grid or non-finite rows dropped,
  **zero-volume bars dropped**; each count is reported. Volume = the quote-asset volume column.
* **Coin end.** A coin's tradable span ends at its `last_nonzero_volume_bar` in the manifest. After it the archive can
  hold flat zero-volume bars and funding rows (8 of the 30 coins, section 3); none of them is read as trading. A
  position still open on that coin is closed at the close of that last bar like a stop-market exit (slippage and taker
  of 7.5), counted as "coin end". Nothing fills on a coin after its end.
* **Mark price is in the files but not read.** Liquidation is checked on last-price 5m bars, which wick at least as far
  as mark price, so this errs toward more liquidations (section 7.6). The wide addendum does the same.
* Funding: each archived funding event (its `calc_time`, put on the 5m grid, and its rate) applies to every position
  open at that time. It is charged after the 5m bar that ends at `calc_time`, on that bar's close, and paid from or to
  the wallet (not the isolated margin). A long pays when the rate is positive, a short receives it. A missing month of
  funding while a coin trades counts as 0 and is reported (the manifest shows none).
* **Cross-check, before the pin:** for the current six coins, the 5m bars must match the full grid's 1m archive
  (`fg1m/1m/<SYM>.npz`) resampled to 5m (OHLC within 1e-6 relative; volume within 0.1%) on every bar both have; a
  mismatch on more than 0.1% of the bars of any of the six stops the pin. The data job compared BTC closes only
  (99.997% equal); the full check (six coins, open, high, low, close and volume) still has to run. Its per-coin counts
  go into `research/hunt/data_check.json`, which the pin lists.
* **Identity of the data.** The npz files stay outside the repository (about 0.55 GB). Before the pin, `manifest.json`
  is copied to `research/hunt/data_manifest.json` and the data job's scripts (`c30.py`, `c30_fill.py`,
  `write_universe_md.py`, `universe_addendum.py`) to `research/hunt/data_build/`; the pin lists them. Because a zip's
  bytes change with its write time, identity is checked on content: `data_manifest.json` also holds, per coin, the
  sha256 of the arrays the study reads (5m: ts, o, h, l, c, v, qv; funding: ts, rate; in that order, as stored), taken
  once from the built files before the pin. `select` and `test` recompute them and stop on any difference, so a run on
  another machine either copies the files or rebuilds them with the pinned scripts and must reproduce the same content.
  Downloads at most 2 at a time. The run stops if free disk falls under 1 GB.

## 3. Universe

* **The 30 coins of the scratchpad file `coins30/UNIVERSE.md`**, fixed 2026-10-11 08:48 UTC before any result (sha256
  of its `universe.json`: `dbe0ed018308fb4b75ce7847641ae4903a9d21a1c66a23fc3e5aa6b456cba352`). Rule: Binance USD-M
  USDT symbols without `_` (900 of 1,056) whose first monthly 5m file is 2021-01 or earlier (87); stablecoin, fiat and
  index products removed (DEFIUSDT; 86 left); ranked by 2023 quote volume summed from the monthly 1d files; the top 30,
  with the six current coins required (all six are inside the top 30, so the rule's fallback did not act). The list:
  BTCUSDT ETHUSDT SOLUSDT XRPUSDT DOGEUSDT BNBUSDT LTCUSDT MATICUSDT BCHUSDT LINKUSDT AVAXUSDT ADAUSDT TRBUSDT FILUSDT
  FTMUSDT ETCUSDT DOTUSDT NEARUSDT EOSUSDT CRVUSDT SANDUSDT ATOMUSDT TOMOUSDT AXSUSDT STORJUSDT MKRUSDT BLZUSDT COMPUSDT
  RUNEUSDT WAVESUSDT. It is copied into `research/hunt/universe30.json` with the sha256 of `UNIVERSE.md` and
  `universe.json`, and that json is part of the pin. One static list for every period. Successor tickers (POL, S, VIC,
  ...) are not spliced in.
* **Eight coins stop trading inside the data** (last bar with volume): TOMO 2023-11-14, WAVES 2024-06-11, MATIC
  2024-09-04, BLZ 2024-12-23, FTM 2025-01-06, EOS 2025-05-21, MKR 2025-09-08, STORJ 2026-08-26. Each ends as in
  section 2 (coin end). Coins trading: 29 on 2021-01-01, 30 from 2021-07, 29 on 2024-01-01, 26 on 2025-01-01, 23 on
  2026-01-01, 22 at the end.
* **No coin listed after 2021-01 is in the universe** (the history rule). The study says nothing about newly listed
  coins, where many 2024-2026 trends happened, and the forward paper bot (section 15) does not trade them either.
* **When a coin can give a gated signal.** The 장세 label needs 180 days of the coin's own bars (section 6), so a coin
  can pass the gate only from about its first bar + 180 days: 12 coins by 2021-01-01 (BTC ETH XRP BNB LTC BCH LINK ADA
  ETC EOS ATOM COMP), DOGE from 2021-01-06, the others between 2021-02 and 2021-05 (AXS last, 2021-05-19), SAND from
  2021-07-24. Control (a) draws only from bars with a known label (section 12), so it follows the same ramp.
* **Old six** = BTCUSDT ETHUSDT SOLUSDT DOGEUSDT LTCUSDT BCHUSDT (`paperbot/config.V3_SYMBOLS`). **New 24** = the other
  24 of the 30 (all eight coins that stop trading are among them).
* **Large group** (for the direction cap, section 8): at the start of each UTC calendar month, the 10 coins of the 30
  with the largest quote volume over the previous 30 days of 5m bars (point in time; a coin with fewer than 30 days of
  bars is not large). A position keeps the group it had when it opened.
* **Known biases** (section 18, Q2). For the **test period** the list is point in time: it uses listing dates up to
  2021-01 and 2023 volumes only, all known before 2024-01-01, and it keeps the coins that later stopped, so the test
  has no survivorship from the list. For the **select period** the 2023 volume rank uses select-period information:
  coins that traded heavily in 2023, often because they moved (TRB's 2023 squeeze), are favoured. That flatters the
  select results and the pick, not the test.

## 4. Bars

* Signal bars: **1h** and **4h**, UTC bins (4h at 00, 04, ... 20 UTC) of the 5m bars; a bin with no 5m bar is no bar;
  a coin's first and last bins are dropped when the data start or end inside them.
  Open = first 5m open, high / low = extremes, close = last 5m close, volume = sum.
* A signal is known at the signal bar's close (the end of its bin). Everything after the signal (fills, stops, adds,
  funding, marks) runs on the 5m bars that follow.
* Indicators (all on the signal timeframe, causal, value at bar t uses bars up to t):
  ATR14 and ATR100 = Wilder's average of the true range (the method of `paperbot/dash/tools/regime5y.adx_atr`);
  Bollinger(20, 2) = SMA20 of close +/- 2 x the population standard deviation of the same 20 closes, bandwidth =
  (upper - lower) / SMA20. A bar where a needed value is undefined gives no signal.

## 5. Entries (three, each long and short)

Each entry is an **event**: its full condition is true on bar t and was false on bar t-1 (per side), and every value
the condition needs is defined on both bars (so the first bar with all values defined never gives an event). A coin can
have at most one position (section 8), so an event on a coin that already holds a position is ignored, whichever side.

| | name | long event on bar t (short = mirror) | main number (plateau, 11.2) |
|---|---|---|---|
| **E1** | Donchian 55 + volume | close[t] > highest high of bars t-55..t-1, and volume[t] >= 2 x mean volume of bars t-20..t-1 | channel 55 |
| **E2** | Bollinger squeeze release | bandwidth[t-1] <= the 20th percentile (numpy linear) of bandwidth over bars t-120..t-1, and close[t] > upper band[t] while close[t-1] <= upper band[t-1] | window 120 |
| **E3** | volatility expansion | ATR14[t] / ATR100[t] >= 1.5 while the ratio[t-1] < 1.5; side = sign of close[t] - close[t-20] (long if > 0, short if < 0, none if 0) | threshold 1.5 |

Short mirrors: E1 close below the lowest low of t-55..t-1 with the same volume test; E2 close below the lower band with
the squeeze on t-1 and close[t-1] >= lower band[t-1]; E3 as in the table.

**Systems**: entry x timeframe = 6 (E1-1h, E1-4h, E2-1h, E2-4h, E3-1h, E3-4h). One system uses one entry on one
timeframe; entries are not combined.

## 6. Gate (장세 문지기)

* Label: `paperbot.dash.tools.regime5y.regimes(high, low, close, TF_MIN[tf])["code"]` on the coin's own signal bars,
  exactly as `research/fullgrid/regimes.coin_states` computes 장세: 급변장 = ATR14% at or above the 80th percentile of
  the trailing 365 days of bars, this bar included (at least 180 days of bars), else 추세장 = ADX14 >= 25 and |EMA50
  slope over 10 bars| >= 0.5 ATR, else 횡보장 = ADX14 < 20, else 보통; 모름 = any input undefined (in practice the
  first 180 days of a coin).
* **Rule: an event passes only when the signal bar's label is 추세장.** This is G1 for the trend class as written in
  `research/regimegate/PREREG_REGIMEGATE.md` section 4 (all three entries enter with the move: trend class): 급변장,
  횡보장, 보통 and 모름 are blocked. The rule is copied here so that a later change to the regime-gate file does not
  change this study. The label does not check that the EMA50 slope points the same way as the trade (section 18, Q11).
* Expected side effect, stated before any count: a squeeze (E2) usually comes with a low ADX and a volatility jump (E3)
  often lands in the top 20% of ATR% (급변장, decided first), so G1 may block most E2 and E3 events. The trade minimum of
  section 11 removes a starved system; the gate is not changed for it.
* A **gated signal** = an event that passes the gate. Controls (section 12) are built from gated signals.

## 7. One position: size, leverage, pyramiding, exits

### 7.1 Entry fill
Market order at the open of the first 5m bar after the signal bar's close. Reference price P0 = that open; fill price
= P0 x (1 + 0.0002) for a long (1 - 0.0002 short); taker fee 0.05% of the fill notional. The decision (caps, equity,
free wallet) uses the state at the previous 5m close.

### 7.2 First stop and unit
* R distance D0 = **2 x ATR14 (1h systems) / 1.5 x ATR14 (4h systems)** of the signal bar. First stop S0 = P0 - D0
  (long) / P0 + D0 (short).
* Unit risk U = r x equity, equity marked to market at the previous 5m close (wallet balance plus open positions at
  that close), **r = 0.5% and r = 1%** (two accounts, everything else equal). Unit quantity q = U / D0. Risk is
  measured on price distance from reference prices; fees, slippage and funding are extra (the worst case of a unit is
  about 1 U + costs + gap).
* Cuts (each counted in the output): liquidity, q x P0 <= 0.1% of the coin's quote volume over the 288 5m bars before
  the fill bar; margin and free wallet (7.3). A unit below the coin's minimum notional after its cuts is not placed.
  After a cut, q is the cut quantity (the adds use it, 7.4) and U stays r x equity (the stop rule of 7.4 uses that U).

### 7.3 Leverage and isolated margin
Leverage only reaches the size; it never sets it. Each position has a margin budget B = equity at its first entry / 6.
Its leverage L (an integer, set at the first entry, kept) is the smallest L in 1..20 with:
(i) L allowed by the coin's bracket at the planned full notional N4 = 4 x q x P0; (ii) N4 / L <= B; (iii) 1/L - mmr
>= 1.5 x D0 / P0 (liquidation at least 1.5 times as far as the first stop; mmr = the bracket's maintenance margin rate
at N4). If no L meets all three, L = the largest L <= 20 meeting (i) and (iii); if none meets (i) and (iii), the entry
is skipped (counted "leverage"). The first unit is cut only if it alone does not fit B at L, and each add takes q or
what is left of B at L. Margin of a fill = its notional / L. An entry or add whose margin plus taker fee exceeds the
free wallet balance (wallet minus all isolated margins) is cut to fit or skipped.
Liquidation price (Binance isolated, one-way), recomputed after each fill: long (cost - M - cum) / (Q x (1 - mmr)),
short (cost + M + cum) / (Q x (1 + mmr)), with Q the position quantity, cost the sum of fill notionals, M the isolated
margin, and mmr and cum of the bracket that holds the cost. A liquidation loses the whole isolated margin.
Brackets and minimum notional: `research/hunt/exchange30.json`, in the format of `research/fullgrid/exchange.json`,
fixed before the pin and listed in it. It holds at least the six current coins copied from
`research/fullgrid/exchange.json` (fetched 2026-10-10), plus whatever the owners' 30-symbol dump on the paper bot server
adds (section 18, Q3). That dump can only cover coins still listed: the eight coins that stopped trading always use the
fallback. A coin missing from the file uses the fallback table: 20x up to $25,000 notional (mmr 2.5%), 10x up to
$100,000 (5%), 5x up to $250,000 (10%), 3x up to $1,000,000 (12.5%), 1x above (25%); minimum notional $5. The fallback
is an approximation, not a verified lower bound: some small alts' real first tier stops at $5,000. The leverage that
(ii) asks for is N4 / B = 24 x r / (D0 / P0): for a small alt with D0 / P0 of 2-4% that is 3x-6x at r = 0.5% and
6x-12x at r = 1%, so at the start wallet only the r = 1% account on the calmer alts could be cut by a tighter real
table (its last add first). Every bracket table is a 2026 snapshot applied to 2020-2026. The per-coin source
(exchange30 or fallback) and the leverage and margin cuts per coin are reported. Quantity steps are ignored.

### 7.4 Pyramiding (불타기)
* Three add levels, each tried once, in order. Long: level 1 = P0 + D0; level n+1 = the reference price of add n (its
  level, or the gapped open it filled at; a skipped add counts as filled at its level) + D0. Short mirror.
* An add is a stop-market order of quantity q (the first unit's quantity after its cuts, so the same dollars per R),
  reference price = the level, or the 5m open when the open is already beyond it; slippage 0.02% and taker 0.05% as 7.1.
* **On each add the one stop of the whole position moves** to the tighter of the current stop and
  S_req = (sum of q_i x ref_i - U) / sum of q_i (long; short mirror: (sum q_i ref_i + U) / sum q_i), so that the
  position's open risk sum q_i x (ref_i - stop) stays <= U. With full units: after add 1 the stop is at P0, after add
  2 at P0 + 0.667 D0, after add 3 at P0 + 1.25 D0. Stops never loosen.
* An add is skipped (and counted) when the portfolio risk cap (section 8) would be exceeded after it, or margin /
  minimum notional does not allow it. A skipped add moves nothing.

### 7.5 Exit: chandelier trailing stop, nothing else
* At each signal-bar close after the entry: chandelier = highest high of the signal bars from the bar that holds the
  entry fill (the signal bar itself not included) through the latest completed signal bar - 3 x ATR14 of that latest
  completed bar, long; lowest low + 3 x ATR14, short. The first update is at the close of the bar that holds the fill.
  The stop becomes the tighter of the current stop and the chandelier, from the next 5m bar.
* No take-profit, no time stop, no exit on an opposite signal. The whole position exits at the stop (stop-market:
  the stop price, or the 5m open when the open is already beyond it; slippage 0.02% against, taker 0.05%). The only
  other exits are liquidation (7.6), coin end (section 2) and bust (section 10).

### 7.6 Order of events inside one 5m bar (long; short mirror)
Where the bar's path is unknown, the order that is worse for the account is taken.
1. Open at or below the liquidation price: liquidated, the position's whole isolated margin is lost.
2. Open at or below the stop: exit at the open.
3. The bar's high does not reach the next untried add level and its low reaches the stop: exit at the stop.
4. The bar's high reaches the next untried add level: each add level the bar reaches fills in order (at the open if the
   open is beyond it). After each fill the stop moves (7.4) and the liquidation price is recomputed. Then, if the bar's
   low reaches the stop (moved or not), the position exits there in the same bar. **The add is taken to have come
   first, also when the low had already reached the old stop**: filling first and exiting at the moved stop never loses
   less than exiting at the old stop without the add.
5. When the liquidation price lies above the stop (possible only after a gapped add or a fallback leverage), it takes
   the stop's place in steps 3 and 4: the low reaching it liquidates the position (whole isolated margin lost).
6. Funding at its timestamp (section 2); the chandelier update at a signal-bar close applies from the next bar.

## 8. Portfolio: one wallet

* One wallet per account, compounding. One position per coin (one-way mode); a new event on a coin with a position is
  ignored.
* At most **6 open positions**. Among coins of the large group (section 3), at most **3 longs and at most 3 shorts**.
* **Total open risk <= 4% of equity**: open risk of a position = max(0, sum q_i x (ref_i - stop)) (long; mirror for
  short); an entry or add is taken only if the total after it stays within 4% of the equity at the previous 5m close.
  (At r = 0.5% six positions hold at most 6 x 0.5% of the equity at their entries, so the cap binds at r = 0.5% only
  after a drawdown of more than a quarter from those entries; it binds mainly at r = 1%.)
* Several gated signals at the same signal-bar close: taken in order of the previous 30 days' quote volume, largest
  first; a signal blocked by a limit is dropped, never queued.

## 9. Costs

Taker 0.05% on every fill (entries, adds, exits) + slippage 0.02% against on every fill + funding. Maker 0.02% would
apply to limit orders; v1 uses none. **Cost x2** read: taker 0.10% and slippage 0.04%, funding unchanged.

## 10. Accounts and metrics

* Each run = one continuous account per system, size r and period: $5,000 at the period start, flat, compounding,
  positions opened only on signals closing inside the period; at the period end every open position is marked at the
  last 5m close and flagged (no prices after the period end are read).
* **Monthly multiple** M_m = equity at the end of UTC calendar month m / equity at its start, equity marked to market at
  the 5m closes. A month without positions has M = 1.0.
* **Bust** = marked equity < 10% of the period-start wallet at any 5m close; the account stops (positions closed at that
  close) and the months after it are reported as bust (M = 1, flagged).
* Reported for every run: median, quartiles and mean of ln M; share of months with M >= 2, >= 10, >= 30 and with
  M < 0.9; worst month; max drawdown (peak to trough of marked equity at 5m closes); bust; end multiple; positions opened
  per month, adds per month, share of positions reaching each add level; per position: P&L in U, win share, the share
  of total profit from the top 10% of positions; skipped or cut entries and adds by reason; coin-end closes;
  liquidations; time at each cap; per year, per side, per group (old six / new 24, as contribution inside the 30-coin
  run).

## 11. Periods and the choice

Periods by the signal bar's close (UTC): **select** 2021-01-01 .. 2024-01-01 (36 months), **test** 2024-01-01 ..
2026-10-01 (33 months), **extra** 2020-01-01 .. 2021-01-01 (in practice 2020-07 .. 2020-12 on 3 to 12 coins: the 장세
label needs 180 days of history, and the archive starts in 2020-01). Indicators and labels use all earlier bars as
warm-up. The select step loads no 5m bar that opens at or after 2024-01-01 00:00 UTC.

11.1 **Runs in select**: the 6 systems at r = 0.5% with the main number at its value and at its two neighbours
(E1 channel 44 / 69; E2 window 96 / 150; E3 threshold 1.4 / 1.625, i.e. 1 + 0.5 x 0.8 and 1 + 0.5 x 1.25), and the 6
systems at r = 1% (main value only).

11.2 **Eligible**: at r = 0.5%, main value: at least 72 positions (2 a month), mean monthly ln M > 0, no bust.
**Plateau score** = the median of the three select-period median monthly multiples (main value and both neighbours; a
neighbour that busts counts 0). **The pick = the eligible system with the highest plateau score** (ties: higher median
of the three mean ln M; then the order of section 5). Exactly one pick. No eligible system: v1 fails at selection; the
highest-scoring system is still run on the test period, labelled "no pick, fail".

11.3 The pick is written to `research/hunt/out/v1/pick.json` and its sha256 appended to `PREREG_HUNT.sha256` before
any test-period bar is read. The test period runs once. **The other five systems are not run on the test period in
v1.**

## 12. Controls (100 seeds each, same machine)

Both controls use exactly sections 7 to 10 (sizing, leverage, pyramiding, chandelier, portfolio, costs), the pick's
timeframe, r and period. Seed number s = 1..100. RNG = numpy PCG64 seeded with the first 8 bytes (little-endian) of
sha256 of the parts joined by "|": ("hunt", control, period, r, s), r written with Python's `%g` (for example
`hunt|a|test|0.005|17`).

* **(a) Random times.** For each coin and side, the same number of signals as the pick's gated signals on that coin and
  side in that period, at signal-bar closes drawn uniformly without replacement from that coin's bars whose close is in
  the period and before the coin end, whose 장세 label is known (not 모름), whose ATR14 is > 0 and that have a fill bar
  inside the period. Per coin the long and short draws are made together without replacement (the first n_long drawn
  are long), so one bar is never both. Not gated (the gate is part of what is tested).
* **(b) Coin-flip sides.** The pick's gated signals at the same coins and times, each side drawn by a fair coin.

For each control: d_m = ln M_m(pick) - mean over the 100 seeds of ln M_m(control seed), per test month.

## 13. Pass rules for v1 (test period, the pick, r = 0.5%, all must hold)

* **P0** at least 66 positions (2 a month) and a position open in at least 80% of the test months; no bust.
* **P1** median monthly multiple >= 1.0 after all costs, **and** mean monthly ln M > 0.
* **P2** beats **both** controls: for (a) and for (b) separately, (i) mean of d_m > 0 with a one-sided month-block
  bootstrap p < 0.05 (resample the 33 months with replacement 10,000 times; p = (1 + resamples with mean d <= 0) /
  10,001; seed as section 12 with "boot" in place of s), and (ii) the pick's mean monthly ln M is above at least 96 of
  the 100 seeds' ((1 + seeds >= pick) / 101 < 0.05).
* **P3** cost x2: median monthly multiple >= 1.0 **and** mean monthly ln M > 0 (the same two tests as P1).
* **P4** max drawdown < 50%.

**v1 PASS** = P0 to P4. The r = 1% account is reported with the same five checks as a separate line ("1% also
passes": yes / no); it is not needed for v1 PASS. Inside v1 one system is tested once, so no multiple-testing
correction applies inside v1. The wide addendum (`PREREG_HUNT_WIDE.md`) tests up to ten more systems on the same 33
months, so the chance that at least one hunt system passes by luck is above 5%; the results page says so next to both
verdicts, and the two verdicts are never merged into one "the hunt passed".

## 14. Reads that are reported, never a pass

* **New 24**: the pick on the 24-coin universe alone (same rules; large group = the top 10 of the 24), select and test.
  If v1 passes but the new-24 test mean ln M <= 0, the result is labelled "carried by the old six".
* **Extra 2020**: the pick at both sizes.
* **Gate diagnostics** for the pick, select and test: no gate; 추세장 or 급변장. They cannot replace v1's gate; a gate
  change is a v2 with its own forward-only test.
* The r = 1% line, the cost x2 line at r = 1%, and the controls in the select period.

## 15. What a result means, and after

| result | then |
|---|---|
| v1 PASS | **forward paper bot from about 2026-10-20** on the coins of the 30 that still trade (22 at 2026-09-30; never a coin outside the 30, no new listings): the pick exactly as here, both sizes, $5,000 each, on the paper bot server (fapi reachable there), nothing else changed. **No real money before the mid-November 2026 review**; real money after it is the owners' decision only |
| v1 fail (any P) | recorded as a fail with every number. No tuning on the test period. The owners may still run the pick as a paper shadow labelled "v1 failed"; it is not a candidate |
| no pick | as fail |

* **Nothing is tuned after the test period is seen.** A bug found after the test run (the code not doing what this file
  says) is fixed in `DEVIATIONS.md`, with the line of this file it breaks; the test is rerun once and both results are
  shown. **The rerun's verdict is the verdict**, whichever way it goes; a fix that changes a rule rather than the code's
  agreement with this file is not a bug fix. Any changed rule (gate, entries, numbers, exits, sizes) is a v2: it needs
  its own pre-registration and is judged only on data after its fixing date (the test period is spent).
* The mid-November review sees about 3.5 weeks of forward data: a handful of trends at most. It checks that the paper
  bot followed these rules (a replay of the same days from the archive reproduces its positions), that its forward
  multiple lies inside the 5th..95th percentile of the test period's rolling windows of the same length (one start per
  UTC day), and that nothing broke. It cannot prove the system makes money; it can show that it does not behave as
  tested.
* Every result, pass or fail, goes into `research/hunt/RESULTS_KO.md` and the owners' summary.

## 16. Code, compute, reproducibility

* Code (drafted after this file's first version, work in progress, not pinned): `research/hunt/hunt.py` (loading,
  coin ends, brackets, the position and portfolio simulator, select, test, controls, bootstrap, report; it also serves
  the wide addendum), `research/hunt/entries_wide.py` (signal bars, indicators, label, the E1-E3 events),
  `tests/test_hunt.py` and `tests/test_hunt_entries.py` on synthetic bars (intrabar order 7.6, the add-stop formula,
  caps, leverage choice, liquidation price, funding sign, coin end, event definitions, seeds, the bootstrap). Reuses
  `regime5y` read-only. Touches nothing of the rule bot, the full grid's pinned files or the candidate league.
* Pinned with this file: the code above, `research/hunt/universe30.json`, `research/hunt/exchange30.json`,
  `research/hunt/data_manifest.json`, `research/hunt/data_check.json` and `research/hunt/data_build/` (section 2).
* Commands: `hunt.py select --study v1`, `hunt.py test --study v1`, `hunt.py report --study v1`; outputs in
  `research/hunt/out/v1/` (select.json, pick.json, test.json, RESULTS_KO.md), each with the git commit and the pin it
  ran under, and the content sha256 of every coin's data it read (section 2).
* Compute: at most 2 processes; select is 24 accounts + diagnostics, test is the pick, 200 control accounts, the cost
  x2 and reads. Disk under 2 GB in total (section 2).

## 17. Not in v1

* **An AI judgment layer** (the AI looks at each signal like a person and takes or skips it, even against the rule).
  It cannot be tested honestly on 2020-2026: the model may remember those prices, and nothing stops hindsight. A replay
  on masked past charts (coin names, dates and price levels hidden) would reduce that memory but not remove it (famous
  crashes and pumps keep their shape); at most it is a cheap pre-check, never proof. The real test is forward, as a
  shadow beside the paper bot from 2026-10-20 (same signals; "AI take" and "AI skip" paths both tracked), with the
  owners' go and its API cost. It is not part of the v1 pass and does not change v1.
* Per-coin numbers, a second entry per system, partial take-profits, limit (maker) orders, risk above 1%, regimes
  other than G1 as the rule, other timeframes, and coins listed after 2021-01.
* The AI bot design (`docs/aibot/DECISIONS_KO.md`) forbids pyramiding; this is a separate system and changes nothing
  there.

## 18. Open questions (closed before the pin; default in brackets)

1. **Gate.** G1 (추세장 only) is used because the regime-gate file exists. It likely starves E2 and E3 (section 6).
   Alternatives: 추세장 or 급변장; "not 횡보장". [G1 as written; the others as diagnostics only]
2. **Universe.** Resolved by `UNIVERSE.md` (section 3): point in time for the test period (2023 volume, history to
   2021-01, dead coins kept); for the select period the 2023 volume rank is look-ahead that favours coins that moved in
   2023. [Accept and label]
3. **Brackets for 30 coins.** `leverageBracket` needs a key: the owners run a 30-symbol version of
   `research/fullgrid/dump_exchange.py` on the paper bot server; it can return only the 22 coins still listed.
   [exchange30.json = the six from `research/fullgrid/exchange.json` + the dump if it arrives before the pin; fallback
   table of 7.3 for every other coin, flagged per coin]
4. **Median month.** A trend system usually has many small losing months and a few large ones; median >= 1.0 can fail
   a system that grows. P1 and P3 also require mean ln M > 0. [Keep both, as the brief asks]
5. **x10 / x30 months.** At 0.5-1% risk per unit, a x2 month needs roughly +140 U at 0.5% or +70 U at 1%; x10 and x30
   are reported for honesty but are practically out of reach. A risk size that could reach them is a separate study of
   bust risk. [Report only]
6. **Mark price** is in the files but not read (section 2). [Last price, conservative; identical in the wide addendum]
7. **Power.** One pick, 33 test months: a real but small edge may not reach p < 0.05. [Accept]
8. **Forward length.** 3.5 weeks to mid-November cannot confirm a trend system (section 15). [Accept; the review checks
   behaviour, not proof]
9. **Additions not in the brief**: events as first crossings; margin budget equity / 6; liquidation >= 1.5 x the stop
   distance; the 0.1%-of-volume liquidity cap; entry order by liquidity; fixed add levels tried once; the moved-stop
   check in the add bar; the large group by 30-day volume; P0 and the seed-rank part of P2. [Keep]
10. **AI judgment** as a forward-only shadow (section 17). [Owners decide separately; not in v1]
11. **Trend direction.** 추세장 does not require the EMA50 slope to agree with the trade side. [G1 as written]
12. **October 2026** is outside the test (no full month). [Accept]

## 19. Before this file was fixed

### 19.1 At the first draft (2026-10-11, about 08:40 UTC)

* Nothing for this study was computed: no hunt code, no price data of the 24 new coins downloaded or looked at. One
  archive listing (file names and sizes of BTCUSDT 5m monthly klines: 81 files 2020-01 .. 2026-09, about 0.4 MB each)
  was read to size the download.
* Related work on the old six exists and was not opened for this file: `research/famous` (daily Turtle Donchian 20/10
  and 55/20), the rule bot's `S5_DONCHIAN_MFI` and squeeze-type strategies in the full grid's reports. A text search
  showed one row of `research/fullgrid/ANALYSIS_KO.md` for S5_DONCHIAN_MFI (a different entry under the house exit);
  it was not used. The owners and the main session have read some of these results, so the old six are not blind;
  that is one reason for the new-24 read.
* The entries, stops, adds, exit and limits come from the owners' brief and textbook trend-following values (55-bar
  channel, Bollinger 20/2, 3 ATR chandelier), not from any run on these coins.

### 19.2 Review before the pin (2026-10-11, about 10:00 UTC)

Done after the `coins30` data job (download, checksums, coverage counts, the last bar with volume per coin; no trading
outcome on any period, per its report) and after the code of section 16 had been drafted (work-in-progress commits
labelled "no results"). No pin file and no `research/hunt/out/` existed. The reviewer read `UNIVERSE.md`,
`universe.json` (rank order and flags), `manifest.json` (coverage fields only), `research/fullgrid/exchange.json`
(brackets) and the code, and computed nothing from prices. Changes:

1. Section 2: the data as actually built (daily-file fills, mark-price columns present but unread, zero-volume tails),
   the coin-end rule, funding timing as coded, the cross-check still to run on all six coins, and the data identity
   (manifest and build scripts into the repository, a content-hash check at run time).
2. Section 3: the real rule and list; the eight coins that stop; no coin listed after 2021-01; when each coin can pass
   the gate; the bias statement corrected (the list is point in time for the test period, look-ahead only in select).
3. Section 5: an event needs every value defined on t and t-1. Section 4: incomplete first and last bins dropped.
4. Section 7.3: no leverage meeting (i) and (iii) skips the entry; liquidation formula; exchange30.json content (the six
   from the full grid's file; the dead coins can only use the fallback); the fallback described as an approximation.
5. Section 7.5: the chandelier's extreme starts at the bar that holds the fill (the draft's "entry bar" was ambiguous).
6. **Section 7.6: a 5m bar that reaches both an add level and the stop now takes the add first** (the draft let the
   stop count first, which loses less than add-then-moved-stop whenever the stop had already been tightened, against
   the worse-order rule the draft used in its own step 4). Intrabar liquidation inside the stop written out.
7. Section 8: the risk-cap note corrected (U is fixed at each entry's equity).
8. Section 12: the exact seed encoding and the control (a) pool. Section 11.3 / 16: output folder `out/v1/`.
9. **Section 13: P3 also requires mean ln M > 0 at cost x2**; the multiple-testing sentence now names the wide
   addendum's shared test period.
10. Section 15: forward bot on the coins still trading, no new listings; after a bug fix the rerun's verdict counts.
11. Section 17: masked-chart replay named as a weak pre-check only. Section 18: Q2, Q3, Q6 updated.
