# Trend hunt v1 (추세 사냥): pre-registration

(한국어 설명: `README_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면
`DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (KST), before any data for this study was downloaded and before any code for it
existed.** The open questions of section 18 are closed by the owners (or by the default written next to each) before
the file is pinned. Pinning = `PREREG_HUNT.sha256` over this file and the study's code (section 16); the code refuses
the `select` and `test` steps without a matching pin. After the pin nothing here changes; a change goes to
`DEVIATIONS.md` with its reason and date.

Owners' brief (2026-10-11): a "trend hunt" system, 스캐너 → 장세 문지기 → 진입·첫 손절 → 불타기 → 추적 손절 청산, on
many coins, tested before the mid-November 2026 review ("11월 중순까지는 성공시키고 싶어 ... 일단 계획을 그렇게 잡아보자").

## 1. Question

On a fixed 30-coin universe, does one rule-based trend-following system (breakout-type entry, regime gate, ATR first
stop, pyramiding with the open risk held at one unit, chandelier trailing exit, portfolio limits) grow one wallet after
all costs on data its choice never saw, and does it beat the same machine fed with random entry times and with
coin-flip sides?

## 2. Data

* Binance USD-M public archive (data.binance.vision), checksum-verified (`.CHECKSUM` files):
  `data/futures/um/monthly/klines/<SYM>/5m/<SYM>-5m-YYYY-MM.zip` and
  `data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-YYYY-MM.zip`, every month from the coin's first
  archived month (2020-01 at the earliest) to 2026-09. Daily files are not used: the last period ends 2026-10-01 00:00
  UTC and open positions are marked there (section 10).
* 5m bars: duplicate open times dropped (last kept), zero-volume bars dropped. Volume = the quote-asset volume column.
* **Mark price is not downloaded** (disk: about 3.4 GB free on the machine). Liquidation is checked on last-price 5m
  bars, which wick at least as far as mark price, so this errs toward more liquidations (section 7.6).
* Funding: each archived funding event (its `calc_time` and rate) applies to every position open at that time; the
  price is the close of the 5m bar ending at that time. A missing month of funding is 0 and is counted in the output.
* Cross-check: for the current six coins, the 5m bars must match the full grid's 1m archive
  (`fg1m/1m/<SYM>.npz`) resampled to 5m (OHLC within 1e-6 relative; volume within 0.1%) on every bar both have; a
  mismatch on more than 0.1% of bars stops the run.
* Storage: converted per-coin arrays outside the repository (the scratchpad folder of the `coins30` download job, or
  `hunt5m/`), about 0.5 GB for 30 coins; each zip is deleted after conversion. Whoever downloads, the checks of this
  section run on the files the study reads, and their sha256 list is written next to the results. Downloads at most 2 at a time. The run stops if free disk falls under 1 GB.

## 3. Universe

* **The 30 coins chosen by the rule in the scratchpad file `coins30/UNIVERSE.md`** (written by another agent the same
  day). This file adopts that rule as written when this file is pinned; the resulting list is copied into
  `research/hunt/universe30.json` with the UNIVERSE.md sha256, and that json is part of the pin. One static list for
  every period. A coin with no data in a month simply has no bars there.
* **Old six** = BTCUSDT ETHUSDT SOLUSDT DOGEUSDT LTCUSDT BCHUSDT (`paperbot/config.V3_SYMBOLS`). **New 24** = the other
  24 of the 30. (If the rule does not contain all six, the "new" read is the coins outside the six, whatever their
  number, and this is recorded.)
* **Large group** (for the direction cap, section 8): at the start of each UTC calendar month, the 10 coins of the 30
  with the largest quote volume over the previous 30 days of 5m bars (point in time; a coin with fewer than 30 days of
  bars is not large). A position keeps the group it had when it opened.
* Known bias (section 18, Q2): a list fixed in 2026 holds coins that survived and grew; delisted coins are absent.

## 4. Bars

* Signal bars: **1h** and **4h**, UTC bins (4h at 00, 04, ... 20 UTC) of the 5m bars; a bin with no 5m bar is no bar.
  Open = first 5m open, high / low = extremes, close = last 5m close, volume = sum.
* A signal is known at the signal bar's close. Everything after the signal (fills, stops, adds, funding, marks) runs on
  the 5m bars that follow.
* Indicators (all on the signal timeframe, causal, value at bar t uses bars up to t):
  ATR14 and ATR100 = Wilder's average of the true range (the method of `paperbot/dash/tools/regime5y.adx_atr`);
  Bollinger(20, 2) = SMA20 of close +/- 2 x the population standard deviation of the same 20 closes, bandwidth =
  (upper - lower) / SMA20. A bar where a needed value is undefined gives no signal.

## 5. Entries (three, each long and short)

Each entry is an **event**: its full condition is true on bar t and was false on bar t-1 (per side). A coin can have
at most one position (section 8), so an event on a coin that already holds a position is ignored, whichever side.

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
  exactly as `research/fullgrid/regimes.coin_states` computes 장세: 급변장 = ATR14% in the top 20% of the trailing 365
  days (at least 180 days of history), else 추세장 = ADX14 >= 25 and |EMA50 slope over 10 bars| >= 0.5 ATR, else
  횡보장 = ADX14 < 20, else 보통; 모름 = not enough history.
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
= P0 x (1 + 0.0002) for a long (1 - 0.0002 short); taker fee 0.05% of the fill notional.

### 7.2 First stop and unit
* R distance D0 = **2 x ATR14 (1h systems) / 1.5 x ATR14 (4h systems)** of the signal bar. First stop S0 = P0 - D0
  (long) / P0 + D0 (short).
* Unit risk U = r x equity, equity marked to market at the entry (wallet balance plus open positions at the last 5m
  close), **r = 0.5% and r = 1%** (two accounts, everything else equal). Unit quantity q = U / D0. Risk is measured on
  price distance from reference prices; fees, slippage and funding are extra (the worst case of a unit is about
  1 U + costs + gap).
* Cuts (each counted in the output): liquidity, q x P0 <= 0.1% of the coin's quote volume over the previous 288 5m bars;
  margin (7.3). A unit below the exchange minimum notional after a cut is not placed.

### 7.3 Leverage and isolated margin
Leverage only reaches the size; it never sets it. Each position has a margin budget B = equity at its first entry / 6.
Its leverage L (an integer, set at the first entry, kept) is the smallest L in 1..20 with:
(i) L allowed by the coin's bracket at the planned full notional N4 = 4 x q x P0; (ii) N4 / L <= B; (iii) 1/L - mmr
>= 1.5 x D0 / P0 (liquidation at least 1.5 times as far as the first stop; mmr = the bracket's maintenance margin rate
at N4). If no L meets all three, L = the largest L <= 20 meeting (i) and (iii); the first unit is cut only if it alone
does not fit B at L, and each add takes q or what is left of B at L. An entry or add whose margin exceeds the free
wallet balance is cut to fit or skipped. Brackets and minimum notional: `research/hunt/exchange30.json` (section 18,
Q3); a coin missing there uses the fallback table: 20x up to $25,000 notional (mmr 2.5%), 10x up to $100,000 (5%), 5x up
to $250,000 (10%), 3x up to $1,000,000 (12.5%), 1x above (25%); minimum notional $5. Quantity steps are ignored.

### 7.4 Pyramiding (불타기)
* Three add levels, each tried once, in order. Long: level 1 = P0 + D0; level n+1 = the reference price of add n (its
  level, or the gapped open it filled at; a skipped add counts as filled at its level) + D0. Short mirror.
* An add is a stop-market order of quantity q (the first unit's quantity, so the same dollars per R), reference price =
  the level, or the 5m open when the open is already beyond it; slippage 0.02% and taker 0.05% as 7.1.
* **On each add the one stop of the whole position moves** to the tighter of the current stop and
  S_req = (sum of q_i x ref_i - U) / sum of q_i (long; short mirror: (sum q_i ref_i + U) / sum q_i), so that the
  position's open risk sum q_i x (ref_i - stop) stays <= U. With full units: after add 1 the stop is at P0, after add
  2 at P0 + 0.667 D0, after add 3 at P0 + 1.25 D0. Stops never loosen.
* An add is skipped (and counted) when the portfolio risk cap (section 8) would be exceeded after it, or margin /
  minimum notional does not allow it.

### 7.5 Exit: chandelier trailing stop, nothing else
* At each signal-bar close after the entry: chandelier = highest high of the signal bars since the entry bar (the
  entry bar included once complete) - 3 x ATR14 (the latest completed signal bar), long; lowest low + 3 x ATR14,
  short. The stop becomes the tighter of the current stop and the chandelier, from the next 5m bar.
* No take-profit, no time stop, no exit on an opposite signal. The whole position exits at the stop (stop-market:
  the stop price, or the 5m open when the open is already beyond it; slippage 0.02% against, taker 0.05%).

### 7.6 Order of events inside one 5m bar (long; short mirror)
1. Open beyond the liquidation price: liquidated, the position's whole isolated margin is lost.
2. Open at or below the stop: exit at the open.
3. **Low touches the stop: exit at the stop, and no add fills in this bar even if the high also crossed an add level
   (the stop counts first).**
4. Else each add level the bar reaches fills in order (at the open if the open is beyond it). After each fill the stop
   moves (7.4); if the bar's low reaches the moved stop, the position exits there in the same bar (the add is taken
   to have come first: the worse order).
5. Funding at its timestamp; the chandelier update at a signal-bar close applies from the next bar.

## 8. Portfolio: one wallet

* One wallet per account, compounding. One position per coin (one-way mode); a new event on a coin with a position is
  ignored.
* At most **6 open positions**. Among coins of the large group (section 3), at most **3 longs and at most 3 shorts**.
* **Total open risk <= 4% of equity**: open risk of a position = max(0, sum q_i x (ref_i - stop)) (long; mirror for
  short); an entry or add is taken only if the total after it stays within 4%. (At r = 0.5% six positions hold at most
  3%, so this cap binds only at r = 1%.)
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
  close) and the months after it are reported as bust.
* Reported for every run: median, quartiles and mean of ln M; share of months with M >= 2, >= 10, >= 30 and with
  M < 0.9; worst month; max drawdown (peak to trough of marked equity at 5m closes); bust; end multiple; positions opened
  per month, adds per month, share of positions reaching each add level; per position: P&L in U, win share, the share
  of total profit from the top 10% of positions; skipped or cut entries and adds by reason; time at each cap; per year,
  per side, per group (old six / new 24, as contribution inside the 30-coin run).

## 11. Periods and the choice

Periods by the signal bar's close (UTC): **select** 2021-01-01 .. 2024-01-01 (36 months), **test** 2024-01-01 ..
2026-10-01 (33 months), **extra** 2020-01-01 .. 2021-01-01 (in practice from about 2020-07: the 장세 label needs 180
days of history, and the archive starts in 2020-01). Indicators and labels use all earlier bars as warm-up.

11.1 **Runs in select**: the 6 systems at r = 0.5% with the main number at its value and at its two neighbours
(E1 channel 44 / 69; E2 window 96 / 150; E3 threshold 1.4 / 1.625, i.e. 1 + 0.5 x 0.8 and 1 + 0.5 x 1.25), and the 6
systems at r = 1% (main value only).

11.2 **Eligible**: at r = 0.5%, main value: at least 72 positions (2 a month), mean monthly ln M > 0, no bust.
**Plateau score** = the median of the three select-period median monthly multiples (main value and both neighbours; a
neighbour that busts counts 0). **The pick = the eligible system with the highest plateau score** (ties: higher median
of the three mean ln M; then the order of section 5). Exactly one pick. No eligible system: v1 fails at selection; the
highest-scoring system is still run on the test period, labelled "no pick, fail".

11.3 The pick is written to `research/hunt/out/pick.json` and its sha256 appended to `PREREG_HUNT.sha256` before any
test-period bar is read. The test period runs once. **The other five systems are not run on the test period in v1.**

## 12. Controls (100 seeds each, same machine)

Both controls use exactly sections 7 to 10 (sizing, leverage, pyramiding, chandelier, portfolio, costs), the pick's
timeframe, r and period. Seed = sha256 of ("hunt", control, period, r, seed number).

* **(a) Random times.** For each coin and side, the same number of signals as the pick's gated signals in that period,
  at signal-bar closes drawn uniformly without replacement from that coin's bars in the period whose 장세 label is
  known (not 모름) and whose ATR14 is defined. Not gated (the gate is part of what is tested).
* **(b) Coin-flip sides.** The pick's gated signals at the same coins and times, each side drawn by a fair coin.

For each control: d_m = ln M_m(pick) - mean over the 100 seeds of ln M_m(control seed), per test month.

## 13. Pass rules for v1 (test period, the pick, r = 0.5%, all must hold)

* **P0** at least 66 positions (2 a month) and a position open in at least 80% of the test months; no bust.
* **P1** median monthly multiple >= 1.0 after all costs, **and** mean monthly ln M > 0.
* **P2** beats **both** controls: for (a) and for (b) separately, (i) mean of d_m > 0 with a one-sided month-block
  bootstrap p < 0.05 (resample the 33 months with replacement 10,000 times; p = (1 + resamples with mean d <= 0) /
  10,001; seed as section 12 with "boot"), and (ii) the pick's mean monthly ln M is above at least 96 of the 100 seeds'
  ((1 + seeds >= pick) / 101 < 0.05).
* **P3** cost x2: median monthly multiple >= 1.0.
* **P4** max drawdown < 50%.

**v1 PASS** = P0 to P4. The r = 1% account is reported with the same five checks as a separate line ("1% also
passes": yes / no); it is not needed for v1 PASS. One hypothesis, one test: no multiple-testing correction applies.

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
| v1 PASS | **forward paper bot from about 2026-10-20** on the 30 coins: the pick exactly as here, both sizes, $5,000 each, on the paper bot server (fapi reachable there), nothing else changed. **No real money before the mid-November 2026 review**; real money after it is the owners' decision only |
| v1 fail (any P) | recorded as a fail with every number. No tuning on the test period. The owners may still run the pick as a paper shadow labelled "v1 failed"; it is not a candidate |
| no pick | as fail |

* **Nothing is tuned after the test period is seen.** A bug found after the test run is fixed in `DEVIATIONS.md`; the
  test is rerun once and both results are shown. Any changed rule (gate, entries, numbers, exits, sizes) is a v2: it
  needs its own pre-registration and is judged only on data after its fixing date (the test period is spent).
* The mid-November review sees about 3.5 weeks of forward data: a handful of trends at most. It checks that the paper
  bot followed these rules (a replay of the same days from the archive reproduces its positions), that its forward
  multiple lies inside the 5th..95th percentile of the test period's rolling windows of the same length (one start per
  UTC day), and that nothing broke. It cannot prove
  the system makes money; it can show that it does not behave as tested.
* Every result, pass or fail, goes into `research/hunt/RESULTS_KO.md` and the owners' summary.

## 16. Code, compute, reproducibility

* Code (to be written after this draft, before the pin): `research/hunt/data_hunt.py` (download, checksum, convert,
  cross-check), `research/hunt/hunt.py` (bars, indicators, label, entries, the position and portfolio simulator,
  select, test, controls, report), `tests/test_hunt.py` on synthetic bars (intrabar order 7.6, the add-stop formula,
  caps, leverage choice, funding sign, event definitions, the bootstrap). Reuses `regime5y` read-only. Touches nothing
  of the rule bot, the full grid's pinned files or the candidate league.
* Commands: `hunt.py select`, `hunt.py test`, `hunt.py report`; outputs in `research/hunt/out/` (select.json,
  pick.json, test.json, RESULTS_KO.md), each with the git commit and the pin it ran under.
* Compute: at most 2 processes; select is 24 accounts + diagnostics, test is the pick, 200 control accounts, the cost
  x2 and reads. Disk under 2 GB in total (section 2).

## 17. Not in v1

* **An AI judgment layer** (the AI looks at each signal like a person and takes or skips it, even against the rule).
  It cannot be tested honestly on 2020-2026: the model may remember those prices, and nothing stops hindsight. It can
  only be tested forward, as a shadow beside the paper bot from 2026-10-20 (same signals; "AI take" and "AI skip"
  paths both tracked), with the owners' go and its API cost. It is not part of the v1 pass and does not change v1.
* Per-coin numbers, a second entry per system, partial take-profits, limit (maker) orders, risk above 1%, regimes
  other than G1 as the rule, and other timeframes.
* The AI bot design (`docs/aibot/DECISIONS_KO.md`) forbids pyramiding; this is a separate system and changes nothing
  there.

## 18. Open questions (closed before the pin; default in brackets)

1. **Gate.** G1 (추세장 only) is used because the regime-gate file exists. It likely starves E2 and E3 (section 6).
   Alternatives: 추세장 or 급변장; "not 횡보장". [G1 as written; the others as diagnostics only]
2. **Universe.** UNIVERSE.md was not written yet. A list chosen with 2026 information favours coins that later grew
   (look-ahead in select). [Accept and label; prefer a point-in-time rule if UNIVERSE.md offers one]
3. **Brackets for 30 coins.** `leverageBracket` needs a key: the owners run a 30-symbol version of
   `research/fullgrid/dump_exchange.py` on the paper bot server. [Fallback table of 7.3, flagged per coin]
4. **Median month.** A trend system usually has many small losing months and a few large ones; median >= 1.0 can fail
   a system that grows. P1 also requires mean ln M > 0. [Keep both, as the brief asks]
5. **x10 / x30 months.** At 0.5-1% risk per unit, a x2 month needs roughly +140 U at 0.5% or +70 U at 1%; x10 and x30
   are reported for honesty but are practically out of reach. A risk size that could reach them is a separate study of
   bust risk. [Report only]
6. **Mark price** not downloaded (disk). [Last price, conservative]
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
