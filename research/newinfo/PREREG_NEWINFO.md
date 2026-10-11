# New-information batch: pre-registration

(한국어 설명: `README_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면
`DEVIATIONS_NEWINFO.md`에 따로 적습니다.)

Written 2026-10-11, before any result of these rules: no signal of the seven definitions below has been computed on
real data. Owners' agreement of 2026-10-11, item (A): a pre-registered backtest of seven strategies that use
information, or a use of it, the 80 strategies of the full grid (research/fullgrid) do not have: crowd positioning,
funding, open interest and cross-coin strength (none of the 80 uses them); a fade toward the daily VWAP (two DeepSeek
definitions of the full grid, the F6 pair, use the same daily VWAP but follow its crosses); volume spikes (some of the
80 use volume, none a spike rule). Owners' words: friend: "추세장 횡보장 매매법을 찾아서 ...
추세장이면 추세장 매매법을 사용 ... 횡보장이면 진입 금지"; owner: "횡보장에서도 발라먹고 추세장에서도 발라먹는 매매법",
with the goal of growing a small amount fast. Item (B) of the same agreement, the regime-gate ("장세 문지기") shadow
judged by 2026-10-31, is registered separately and changes nothing here.

## 1. Question
For each rule x timeframe ("cell"), is there a combination of the rule's numbers and one of six exits that, chosen on
the select period, earns on the test period under the paper engine's v4 rules (research/fullgrid/kernel.py), beats the
same signal times with coin-flip sides and the same sides taken at random times, survives a multiple-test correction
over the whole batch, still earns at twice the cost and earns in an extra period before the select period (2020; for
the two metrics rules BTC alone, 2020-09 .. 2021-11)?

## 2. Data and timing
2.1 **Price.** The full grid's 1m archive (research/fullgrid/data.py: Binance USD-M 1m last and mark price, funding,
2020-01 .. 2026-09; BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT, LTCUSDT, BCHUSDT). Each coin's `1m/<SYMBOL>.npz` must match
the sha256 in `data_build.json` of the full-grid results pack (fullgrid-results-20261010-1602) before anything runs; a
mismatch stops the study. Chart bars: the full grid's frames (`run.frame`, UTC bins of the 1m bars) for 30m, 1h, 4h;
daily bars (D05 only) the same way over UTC days.

2.2 **Funding.** Settlements (calc time, rate, interval) from the same archive's monthly fundingRate files (verified
against their .CHECKSUM by data.py), 2020-01 .. 2026-09 (LTC from 2020-01-09, DOGE from 2020-07-10, SOL from
2020-09-13). Interval = the file's `funding_interval_hours` (every monthly file of the six coins has that column,
checked 2026-10-11: 8 hours everywhere except SOL's 99 settlements at 2 hours and 2 at 4 hours; a file without it stops
the study). Every calc time lies within the first second of its minute (checked), so flooring to the minute moves none
by more than a second. Rates are compared as 8-hour equivalents, f8 = rate x 8 / interval hours. Neutral rate: 0.0001
(0.01% per 8 hours, the exchange's interest component).

2.3 **Metrics (5 minutes).** `data/orderflow/<coin>_metrics_5m.csv.gz` (sha256 in data/orderflow/MANIFEST.json), plus
the archive's daily metrics files of 2026-09-29 and 2026-09-30 (not yet published when that folder was made; the study
downloads them from data.binance.vision, checks the published .CHECKSUM and records their sha256). First day in the
archive (checked 2026-10-11 by HTTP status only; the review repeated it: BTC 2020-08-31 404 and 2020-09-01 200, the
other five 2021-11-30 404 and 2021-12-01 200, ETH 2020-09-01 and 2021-06-01 404; the 2026-09-29 and -30 files and
their .CHECKSUM 200): BTC 2020-09-01; ETH, SOL, DOGE, LTC, BCH 2021-12-01. Columns used: `count_long_short_ratio` (the
long/short ratio of all accounts, "crowd") and `sum_open_interest` (open interest in coins, not USD, so a price move
alone does not change it). Stamps are on the 5-minute marks from 00:00 UTC. A repeated stamp keeps the last row; a
non-positive or non-numeric value is missing. Known holes (coverage only, all six coins alike):
`count_long_short_ratio` from 2021-12-30 14:30 to 2022-01-19 13:20 and from 2024-02-16 13:30 to 2024-02-17 00:00;
`sum_open_interest` from 2022-03-07 15:25 to 2022-03-08 01:10 and from 2024-02-16 13:30 to 2024-02-17 00:00. Their
effect follows from 2.4's rules; nothing is filled.

2.4 **Timing (no look-ahead).** A signal of the chart bar closing at T uses only:
- prices and volumes of bars closing at or before T (the bar's own OHLCV is known at T);
- a 5-minute metrics row stamped t only when t + 5 min <= T: the bar's value is the row with the latest such t, and is
  missing when that t < T - 30 min;
- a funding settlement from its calc time floored to the minute (the minute the 1m archive pays it on): the bar
  closing at T sees the settlements whose floored calc time is <= T (every calc time is within its minute's first
  second, 2.2). The settled rate is the last value of the estimated rate the exchange shows live, so a bot can know it
  at the settlement. A position filled at that minute does not pay it (kernel.py: no funding on the entry minute);
- for the daily VWAP, 1m bars with open < T;
- other coins' bars closing at or before T;
- a higher-timeframe bar only once it has closed (its close <= T).

Trailing statistics use samples at the bar closes of the cell's own timeframe (the funding statistics of D04 and D05
use settlements instead, section 3). A window of D days is the
N = D x bars-per-day samples ending at T (ranks include T; means and standard deviations for a z exclude T) and needs at
least 0.9 N non-missing samples, else the value is missing and there is no signal. Rank = (a + (e + 1) / 2) / n, with
a window samples below the value, e equal to it (itself included) and n non-missing samples: pandas `rank(pct=True)`,
ties averaged.

Entry, as the full grid: the fill is at the open of the minute after the signal bar's last minute, +0.02% slippage
(kernel.py `_entry_index`).

2.5 **Outcome tables reused.** The per-bar outcome tables of the full grid's outcomes stage
(`OUT/outcomes/<tf>_<SYMBOL>.npz`, run.py stage 1: every chart bar as a signal, each side, alone, all 84 exit variants,
$5,000 wallet, research/fullgrid/exchange.json brackets) give the trades of sections 6.1-6.3, read from `pnl_normal`.
Before use: kernel.py's and run.py's sha256 equal the ones pinned in research/fullgrid/PREREG.sha256;
research/fullgrid/exchange.json has sha256 176e234b3f84a96eecd2a0ea4e6b3e1ffbb3a40bf7fa77dbd994e33144413ffa (the file
of commit f1e824f, the full grid's run); paperbot/config.py is unchanged since that commit (`git diff f1e824f --
paperbot/config.py` empty), so `kernel.settings_vector()`, which every recomputation below uses, is the one the tables
were made with; every table's `close` equals its frame's close times; 300 random (bar, side, exit) entries per table
among section 4's exits (seed `run._seed("newinfo", "verify", table name)`) recomputed with `kernel.outcomes` equal the
stored values (float32; NaN where NaN). A failed file check stops the study until `DEVIATIONS_NEWINFO.md` explains it;
a table failing only the recomputation is rebuilt with `run.py outcomes` before anything else. The sha256 of every
table read is printed.

## 3. Rules
Common: bar i of a coin's chart closing at T; O, H, L, C, V of the bar; ATR = ATR14 (`fg_indicators.atr`, as the
exits); EMA_n = `fg_indicators.ema` (no value before n bars); green = C > O, red = C < O. An **episode** is a run of
consecutive bars on which one side's condition holds (a missing value ends it); "once per episode" = only the first
qualifying bar of an episode signals. The first 300 chart bars of each coin are warm-up only (as the full grid). Every
grid is the full product of its values (no invalid combination); the value in bold is the catalog's proposal or the
earlier test's value (a reference only: there is no default to beat). Grid order: parameters as listed, values ascending (off before on), first parameter outermost;
neighbours (6.1) = one step in one parameter.

| ID | idea | information | timeframes | combinations |
|---|---|---|---|---|
| H3A_CROWD_FADE | crowd long/short extreme -> the other side | metrics (account ratio) | 1h, 4h | 18 |
| D04_FUNDING_FADE | funding extreme -> the other side | funding | 1h, 4h | 18 |
| D05_FUNDING_TREND | trend pullback, only while funding is not yet crowded that way | funding, price | 1h, 4h | 27 |
| D06_OI_DIVERGENCE | new high / low while open interest falls -> fade | metrics (open interest) | 1h, 4h | 27 |
| D08_CROSS_COIN | strongest of six coins long, weakest short | other coins' prices | 1h, 4h | 18 |
| D10_VWAP_REVERT | stretched from the daily VWAP, turning back -> toward it | intraday VWAP | 30m, 1h | 27 |
| D01_VOL_SPIKE | volume spike -> the candle's direction | volume | 1h, 4h | 18 |

Sources: docs/aibot/STRATEGY_CATALOG_KO.md rows 82 and 85-91 (D01, D04, D05, D06, D08, D10), research/orderflow and
research/maker (H3A), research/library lib.py `VO2_VOL_SPIKE` (D01). 153 combinations, each on two timeframes:
14 cells, 1,836 (numbers, exit) pairs in all.

**3.1 H3A_CROWD_FADE.** x = `count_long_short_ratio` at T; r = its rank in a window of `window_d` days. Short when
r >= 1 - q, long when r <= q; once per episode. With `confirm` on, the signal is instead the first bar of the episode
whose candle goes against the crowd (red for a short, green for a long); none if the episode ends first.
Grid: q (0.02, **0.05**, 0.10); window_d (14, **30**, 60); confirm (**off**, on). 18.

**3.2 D04_FUNDING_FADE.** At each settlement s: r = the rank of its f8 among the f8 of the settlements with calc time in
(s - lookback_d days, s], s included (at least 2.7 x lookback_d settlements, else none). Short when r >= 1 - q and
f8 > 0.0001; long when r <= q and f8 < 0.0001. Signal bar: `confirm` off: the first bar closing at or after the floored
calc time; `confirm` on: the bar after that one, which must close in the trade's direction (green for a long, red for a
short), else no signal. At most one signal per settlement; two settlements on one signal bar: the later one.
(With confirm off the 1h and 4h cells share signal times and differ in ATR, so in stop distance.)
Grid: q (0.025, **0.05**, 0.10); lookback_d (45, **90**, 180); confirm (**off**, on). 18.

**3.3 D05_FUNDING_TREND.** Trend up at bar i: C_i > EMA_n(C)_i and the last closed higher-timeframe bar (4h for the 1h
cell, UTC day for the 4h cell) closes above its own EMA_n; trend down: both below; n = `trend_ema`. Trigger: long when
the trend is up and C_{i-1} <= EMA_m_{i-1} and C_i > EMA_m_i (m = `trigger_ema`, the pullback ends); short mirrored.
Crowd filter: f = the f8 of the latest settlement seen at T; P_k = the k-th percentile (numpy, linear) of the f8 of the
settlements with calc time in (T - 90 days, T] (at least 243, else no signal). Long only when f <= P_fund_pct; short
only when f >= P_(100 - fund_pct). Every trigger bar that passes signals. (The daily EMA_300 has no value before 300
days, so the 4h cell's 2020 signals with trend_ema 300 start in late October 2020 for BTC, later for SOL and DOGE.)
Grid: trend_ema (100, **200**, 300); trigger_ema (10, **20**, 40); fund_pct (30, **50**, 70). 27.

**3.4 D06_OI_DIVERGENCE.** W = `window_h` / bar hours (bars). OI(T) = `sum_open_interest` at T (2.4);
d_i = ln(OI(T) / OI(T - window_h)), both present. z_i = (d_i - mean) / std (pandas std, ddof 1) of the d of the
`z_lookback_d` days of bars before i. New high: C_i > max(H of the W bars before i); new low: C_i < min(L of those
bars). Short when new high and z_i < -oi_z (price up while positions close: short covering, not new buyers); long when
new low and z_i < -oi_z; once per episode.
Grid: window_h (12, **24**, 48); oi_z (0.5, **1.0**, 1.5); z_lookback_d (15, **30**, 60). 27.

**3.5 D08_CROSS_COIN.** Ranking times: bar closes T where T / bar length is divisible by `rebalance_bars` (UTC-aligned,
the same times on every coin). Each coin past its warm-up bars (section 3) with bars closing at T and at
T - `rank_bars` x bar length: ret = C_T / C_(T - rank_bars) - 1; at least 4 such coins, else no signal; ties go to the
coin order BTC, ETH, SOL, DOGE, LTC, BCH. Long the coin with the highest ret, short the one with the lowest among the
other coins (never the same coin). With `abs_filter` on, the long only when its ret > 0 and the short only when its
ret < 0. Each ranking time gives new signals; a position from an earlier ranking time is not closed by it (the exit
decides, section 4).
Grid: rank_bars (12, **24**, 48); rebalance_bars (3, **6**, 12); abs_filter (**off**, on). 18.

**3.6 D10_VWAP_REVERT.** VWAP_i = sum(typical x volume) / sum(volume) over the 1m bars of the UTC day of bar i's open,
from 00:00 to T (typical = (h + l + c) / 3 of each minute). Bar j is stretched down when C_j <= VWAP_j - dist_atr x
ATR_j, up when C_j >= VWAP_j + dist_atr x ATR_j. Long at bar i when one of the `lookback_bars` bars before i, opened on
the same UTC day as bar i, was stretched down, bar i is green and C_i < VWAP_i; short mirrored (stretched up, red,
C_i > VWAP_i); once per episode. A bar closing within `skip_h` hours of its day's start (T - day start <= skip_h) never
signals. Timeframes 30m and 1h: a daily VWAP needs intraday bars (a 4h chart has six a day). The catalog's VWAP target
and swing stop are not used; the exits are section 4's, as for every rule.
Grid: dist_atr (1.5, **2**, 3); skip_h (1, **2**, 4); lookback_bars (1, **3**, 6). 27.

**3.7 D01_VOL_SPIKE.** V_i > vol_mult x mean(V of the `vol_len` bars before i) (library `VO2_VOL_SPIKE`: the volume
average shifted by one bar); long when bar i is green, short when red. With `ema_filter` on, the long only when
C_i > EMA_200_i and the short only when C_i < EMA_200_i. Every qualifying bar signals (as the library rule).
Grid: vol_mult (2, **3**, 4); vol_len (10, **20**, 40); ema_filter (**off**, on). 18.

## 4. Exits and sizing
- **Exits** (kernel.EXITS names; their rules as PREREG.md 5), in this order: `ladder|2` (the rule bot's live exit:
  2 ATR stop, stepped lock from 10% net ROE), `tp2R|2`, `tp3R|1.5`, `tp3R|2`, `tp3R|3`, `tp3R|4` (stop k x ATR14 of the
  signal bar from the entry reference; take-profit a limit at 2R or 3R, maker fee; a minute touching both is a stop).
  Exit neighbours for 6.1: tp3R|1.5 - tp3R|2 - tp3R|3 - tp3R|4; ladder|2 and tp2R|2 have none. No other exit of
  kernel.EXITS is computed or used anywhere in sections 6.1-6.3.
- **Size**: quality_v1 "normal" for every signal (30x at 30% margin, else 20x at 20%; stop inside liquidation by
  max(0.2%, 1 ATR); stop loss with fees and slippage <= 15% of the wallet; else the signal is not a trade). No strength
  score: the "best" tier needs strength definitions these rules do not have (the DeepSeek strategies were sized the same
  way in the full grid).
- **Quarter size** (reported, never deciding): the same leverages with every margin fraction x 1/4 (WATCH_PREREG.md 1
  `quarter`; settings vector entries 11, 13, 15, 17), trades recomputed with `kernel.outcomes`.

## 5. Unit
As PREREG.md 5: one trade = one signal alone on a $5,000 wallet; per-trade P&L = wallet change / $5,000. A signal the
sizing rejects, or still open at the end of the data, is not a trade. Every signal counts (no position limit) in
6.1-6.3; trades are pooled over the six coins.

## 6. Periods and pass rule
Periods by the signal bar's close (UTC):

| rules | select | test | extra |
|---|---|---|---|
| D01, D04, D05, D08, D10 | 2021-01-01 .. 2024-01-01 | 2024-01-01 .. 2026-10-01 | 2020-01-01 .. 2021-01-01 |
| H3A, D06 (metrics) | 2021-12-01 .. 2024-01-01 | 2024-01-01 .. 2026-10-01 | BTC only, 2020-09-01 .. 2021-12-01 |

H3A and D06 need the 5-minute metrics, which the archive has for five of the six coins only from 2021-12-01: their
select period starts at the first full month of data for all six coins. Their trailing windows fill from each
coin's first metrics day, so roughly the first 2 to 8 weeks of data give no signal; and the account ratio's hole of
2021-12-30 .. 2022-01-19 (2.3) leaves H3A almost without signals until about February (14-day window) to mid-March 2022
(60-day window) on every coin, BTC included. Their extra period is BTC's earlier metrics (from 2020-09-01, windows
filled from that day): one coin instead of six, so a weaker check than the others'; the report says so next to them.

**6.1 Select** (select period only), per cell, over the (numbers, exit) pairs with >= 150 trades. Plateau score =
median of the pair's mean per-trade P&L and its neighbours' (one number one step up or down with the same exit; or the
next narrower / wider stop with the same take-profit rule among section 4's exits, same numbers; a neighbour with fewer
than 150 trades counts as 0; a neighbour outside the grid does not count), as PREREG.md 6.1. run.plateau_scores'
exit neighbours run over all 84 exits (tp3R|2's wider neighbour there is tp3R|2.5), so it is not called as is: the same
rule is applied with section 4's neighbours.
Picks: the top 3 pairs by plateau among those with plateau > 0 (ties: higher select mean, then grid order, then
section 4's exit order). There is no live default, so no default comparison. At most 3 picks per cell, 42 in all.
Pick id = "rule|tf|row|exit".

**6.2 Test.** All of:
- a. >= 100 test trades;
- b. mean > 0;
- c. mean > the coin-flip mean and mean > the same-side mean.
  Coin-flip mean: the pick's test-period signals with the side drawn by a coin, seeds s = 0 .. 9: long
  when `int(sha256("newinfo-flip|<s>|<pick id>|<coin>|<signal close ms>")[:8], 16)` is even, else short; P&L from the
  same outcome table, exit and size (a flipped signal the sizing rejects is not a trade); the mean over the 10 seeds of
  each seed's mean per trade. It tests the side at the pick's times.
  Same-side mean: for each of the pick's test trades, the mean P&L of every test-period bar of the same coin and
  timeframe taken on the same side with the pick's exit (that outcome table's `pnl_normal`, warm-up bars left out, NaN =
  not a trade, left out); the same-side mean is the average of these values over the pick's test trades. It is what
  the pick's sides on its coins earn on average at random bar closes, so a rule that is mostly long (or short) does
  not pass on the market's drift over the test period alone;
- d. one-sided week-block bootstrap p (run.boot_mean_p: all coins' trades of a UTC week from Monday together, 2,000
  resamples, p = (1 + resamples with mean <= 0) / 2,001, seed `run._seed("newinfo", rule, tf, row, exit, "test")`)
  passing Benjamini-Hochberg at FDR 10% over ALL picks of this batch (one family; a pick with < 100 test trades stays in
  it with p = 1 and cannot pass);
- e. cost twice: the test mean > 0 with the taker fee, the maker fee, the slippage fraction and the ladder's round-trip
  cost each x 2 (PHASE2_PREREG.md 1; settings vector entries 0, 1, 5, 19; funding stays), the pick's test trades
  recomputed with `kernel.outcomes` (a signal the sizing rejects at x2 is not a trade).

**6.3 Extra**: >= 20 trades in the rule's extra period (the table above; BTC only for H3A and D06) and mean > 0.

**6.4** A pick passing 6.2 and 6.3 is a **candidate**.

**6.5** No candidate -> reported as "none". The criteria are not relaxed afterwards. No other cut of the results (per
coin, side, market state, period, size) is a candidate. These rules are not searched again with other numbers on these
periods.

## 7. Reported with the result (never deciding)
For every pick (marked 참고용 when it is not a candidate):
- select / test / extra: trades, mean, win share, sum, at normal and at quarter size; the test p; each coin-flip seed's
  mean; the same-side mean and the pick's share of long trades; the test mean at cost x2 and x3.
- The account (kernel.account as PREREG.md 6.4: $5,000, one position at a time over the six coins, coin priority BTC,
  ETH, SOL, DOGE, LTC, BCH, compounding, bust below $10) from the rule's select start to 2026-10-01 and over the test
  period alone, at normal and quarter size: final wallet, maximum drawdown at closes, worst calendar month,
  liquidations, bust yes / no.
- By market state (the 장세 labels of PHASE2_PREREG.md 7, regimes.py: 급변장 / 추세장 / 횡보장 / 보통 on the strategy's
  own chart at the signal bar), test period: trades and mean per state. A reference only: no state-filtered rule is a
  candidate here (6.5), and the regime gate (B) is pinned before this batch has results, so these figures cannot change
  its rules.
- Per coin, per side, per calendar year: trades and mean.
Per cell: pairs with >= 150 select trades, pairs with plateau > 0, the best plateau.
Files: OUT/select.json, OUT/confirm.json, OUT/RESULTS_KO.md (Korean).

## 8. After
- Candidates never trade real money directly and never enter the rule bot (paperbot's trading path is not touched).
  They go to a forward paper shadow (a `newinfo` pool in the 후보 리그 or a shadow of its own; same engine and v4
  settings), with per candidate, as WATCH_PREREG.md 1: `cand` (its numbers and exit, normal size), `quarter`, and
  `flip` (its signal times, coin-flip sides). There is no `base` or `exitonly` (no live default exists). Where it runs,
  its start date and the dates of C1, C2 and C2's repeats are written to `DEVIATIONS_NEWINFO.md` before its first
  replay; no forward trade of a candidate is looked at before that.
- Forward data: from 2026-10-01 00:00 UTC (the first day after the study's data), replayed, then live, with the timing
  of 2.4. The exchange's REST history of the metrics series covers only the last 30 days, so the shadow keeps its own
  metrics history, seeded from the daily archive; a day whose live values differ from the archive's later daily file
  is logged. Live rows are put on the archive's stamps (the offset between the REST timestamp and the archive's
  `create_time` for the same row is measured on the first day both exist and recorded) before 2.4's 5-minute rule is
  applied, so forward and backtest use the same timing.
- Checks as WATCH_PREREG.md 3, the batch's candidates as one pool: the warning band from each candidate's test-period
  trades (n = 10, 20, 30, 50, 100; 5th percentile); per account from 30 closed trades: mean > 0 and > its `flip`;
  **C1**, one month after the shadow starts: the pool stops when its `cand` mean is below its `flip` mean; **C2**, two
  months after the start: the pool passes when the `cand` pool mean is > 0 with a one-sided week-block bootstrap
  p < 0.05 (2,000 resamples of the pool's weekly sums, seed sha256 of "newinfo|" + date), > the `flip` pool mean and
  above the same-side pool mean (6.2c on the forward days: every forward bar of the trade's coin and timeframe on its
  side with its exit, `kernel.outcomes` on the forward 1m data, averaged over the pool's closed `cand` trades), and
  there are >= 100 closed `cand` trades; with fewer trades C2 is repeated monthly, at most until four months after the
  start, after which the pool ends without a verdict. Trades count when closed before 00:00 UTC of the check date.
- A pool passing C2 lets the owners consider real money for its candidates only, at 1/4 size or smaller, with an
  amount they can lose, the executor's limits on and the testnet drill done. The decision is theirs. The 10/19 $100
  trial does not use these candidates.
- **DeepSeek** is not involved: no DeepSeek definition, code, model or money figure is part of this batch or its
  report. D10 is defined here on its own (a fade toward the VWAP); the DeepSeek F6 VWAP family (crosses, followed in the
  break's direction) is mentioned only by its label: it failed the DeepSeek 5-year gate.

## 9. Not in this study
D02 (daily time-series momentum, research/famous), D03 (already in the shadow league), D07 (no public liquidation
history), D09 (range breakout: tested as the famous turtle rules and S5_DONCHIAN_MFI), the other order-flow series
(top-trader ratio, taker ratio, premium index), limit (maker) entries (research/maker), per-coin choices, exits other
than section 4's, leverage variants, market-state-specific rules.

## 10. Reproducibility
The runner prints the git commit and the sha256 of its code files, of the outcome tables it reads and of the metrics
files. `PREREG_NEWINFO.sha256` pins this file; the code files (research/newinfo/) are added to it after review and
before any run on real data beyond the smoke slice. Smoke runs on real data: prices and funding of 2020-01-01 ..
2020-01-03 only (inside every rule's 300-bar warm-up, so no signal and no outcome of a real period can appear), no
number of them reported; the metrics code is tried on synthetic data only. Tests before the run, on synthetic data:
(1) cutting the data at any time X leaves every signal of a bar closing at or before X unchanged, for every rule and
timeframe; (2) a metrics row is never used before its stamp + 5 minutes, a settlement never before its floored calc
time, a higher-timeframe bar never before its close; (3) every grid has exactly the size in section 3; (4) on synthetic
outcome tables, the plateau with section 4's neighbours, the coin-flip and same-side means and the BH family equal a
direct computation. The run uses at most 2 CPU cores.

## 11. Before this file was fixed (what was already known)
- No signal of these seven definitions has been computed on real data. The data were looked at only for coverage: the
  first and last available metrics days (data/orderflow/MANIFEST.json and HTTP status), the funding interval hours per
  coin, column names and the outcome tables' array shapes. The review of 2026-10-11 added, also coverage only: the
  holes of the two metrics columns (2.3), the funding files' interval column and calc-time seconds (2.2), the sha256 of
  the archive files and of exchange.json (2.1, 2.5).
- Earlier related tests whose results the authors had seen (other engines, costs, exits and periods; per trade at 1x):
  - research/orderflow (2026-09-30; 70 combinations, 0 passed; select 2021-08 .. 2024-06, check 2024-07 .. 2026-09):
    the funding fade lost in both periods; the open-interest rules lost in select and were near zero on check; the
    crowd fade H3A was the only rule positive in both periods (+0.037% / +0.034%, p = 0.33).
  - research/maker round 2 (same periods): H3A with a limit entry, +0.23% / +0.18% (p = 0.01; not locked: too weak for
    the number of tests, bust at 20x).
  - research/library (select 2021-08 .. 2024-06, check 2024-07 .. 2026-09, third period 2020-01 .. 2021-07): the 4h
    volume spike in candle direction was positive in all three of its periods (+0.09% / +0.41% / +1.79% without
    filter), long and short inconsistent, unusable at 20x.
  - research/famous (2021-08 .. 2026-09): daily cross-coin rotation and long/short lost on check.
  - The full grid (2026-10-10): 0 of 711 picks passed; 4h carried the least cost; the 38 watch picks (chosen after the
    test period) mostly use tp3R exits with wide stops. That informed section 4's exits, so the exit list itself was
    chosen with knowledge of this test period; both controls of 6.2c use the pick's exit, so an exit that earns at any
    side or time does not make a pick pass by itself.
- H3A and D01 are in this batch partly because of those positive numbers. H3A's select and test periods lie inside
  the periods research/orderflow and research/maker had already shown, and so do the last four months of its BTC extra
  period (2021-08 .. 2021-11); D01's select, test and extra (2020) periods all overlap research/library's three
  periods. D04, D06 and D08 had related rules seen losing over 2021-08 .. 2026-09. A pass of H3A or D01 is weaker
  evidence than a pass of a rule nobody had looked at; the report says so next to them.
- The test period 2024-01 .. 2026-09 has also been used by the full grid (711 picks) and the studies above, so the
  correction of 6.2d covers this batch only, not the searching done on that period before. For every rule here, only
  the forward check (section 8) is clean evidence.
