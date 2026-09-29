# PREREG: strategy x timeframe sweep (Binance USDT-M futures proxy)

Written 2026-09-29 by the harness agent. At the time of writing, no analysis step had read any
bar of the IS, OOS or FINAL sweep data (`sweep/data/{is,oos,final}` was still empty).
The harness was developed on synthetic data only. This file and `harness/sweep_lib.py` are
hashed into `sweep/PREREG.sha256`. The rules below are fixed. Code bugs found later may be
fixed only under section 11.

Units: all returns are fractions (0.0014 = 0.14 %). "bar t" is the bar that opens at `ts[t]`
(UTC, open-labelled).

## 1. Universe and data

- Coins (7): BTCUSD, ETHUSD, SOLUSD, XRPUSD, DOGEUSD, LTCUSD, BCHUSD. These are Astral/Polygon
  aggregated USD spot series, used as a proxy for Binance USDT-M perpetuals. Perp-spot basis and
  real funding are therefore not modelled.
- Chart timeframes (6): 5m, 15m, 30m, 1h, 4h, 1d. All are built from 5m bars by standard OHLCV
  aggregation: UTC, open-labelled, left-closed bins; open=first, high=max, low=min,
  close=last, volume=sum; bins with zero 5m bars are dropped; partial bins are kept. The
  higher frames for V4.5 (2h, 1w) are aggregated the same way. 1w bins start Monday 00:00 UTC.
- Files: `sweep/data/<split>/<sym>-<tf>.csv` (see `sweep_lib.load`). Each coin starts at the
  clean date recorded by the data agent. Corrupted early history (before about 2021-07/08,
  from cross-venue mixing) is excluded by the data agent before any gate run. The start date
  is taken as given and is not changed after results are seen.
- `load()` drops every bar at or after the split's window end. An IS load therefore never
  returns a bar at or after 2024-07-01.

## 2. Windows, warm-up, admissible signal bars

| split | signal-bar window (bar open time) | warm-up bars in file from |
|---|---|---|
| IS (discovery) | [2021-08-01, 2024-07-01) | 2021-07-01 (or the coin's clean date) |
| OOS (holdout) | [2024-07-01, 2025-08-07) | 2024-01-01 |
| FINAL (descriptive only) | [2025-08-07, 2026-09-29 23:59] | as delivered |

Warm-up: the first `warmup_bars(tf)` bars of each coin's loaded series are never signal bars.
This is max(300 bars, 30 days): 5m 8640, 15m 2880, 30m 1440, 1h 720, 4h 300, 1d 200 bars.
Indicators are computed on the whole loaded series from its first bar.

Bar t is an admissible signal bar for horizon H iff all three hold: `ts[t]` is inside the
window; `t >= warmup_bars(tf)`; and bar `t+1+H` exists in the loaded (window-truncated) data,
so the whole forward path stays inside the window. For the exit stage, H=0 is used (an entry
bar must exist). Positions are bar indices: a data gap makes H bars span more wall time.
This is accepted and not corrected.

## 3. Strategies (37 registry entries; code frozen)

A signal on bar t is known at bar t's close. Entry is at bar t+1's open. If a long and a short
signal fire on the same bar, the short is dropped. Parameters are chart-bar parameters and are
NOT rescaled across timeframes, except for the DOGE strategy (see below).

- (a) 19 exact FINGRAD ports (`strategies.CANDIDATES_15M`): S2_ST_ROC, S5_DONCHIAN_MFI,
  S6_EMA_DMI_ADX, N01_ST_EMA, N02_ST_KST, N03_ADX_GC, N07_ICHI_CMO, N08_ICHI_WR,
  N09_ALLIG_AROON, N10_HA_PSAR, N12_ICHI_AO, N14_ICHI_RSI, N17_KC_RSI, N18_VWMA_MACD,
  N21_ST_RSI_ADX, N22_VORTEX_PSAR, N23_HA_ST, N24_DMI, N25_DST_CCI. N14 and N21 are known to
  produce almost no signals.
- (b) 12 approximate, spec-based ports (`ports12.PORTS12`, variant 0; long/short = pack
  `L`/`S`), flagged `approx=True` in every output: S1_EMA_RSI_CHOP, S3_CMO_SANDWICH, S4_BB_BBP,
  N04_ST_KLINGER, N05_PSAR_POC, N06_MACD_ORB, N11_BREAKAWAY, N13_3OUTSIDE, N15_KC_AO, N16_BBRSI,
  N19_FIB_CHOP, N20_EMA9_CHOP. Their structural stops and exits are NOT used.
- (c) V39_ALL (`strategies.v39_all`, single-timeframe chart logic as ported, STC gate off),
  OBV_S, OBV_B.
- (d) V45_AMB: V4.5 exact AM+B (`B & ~C`) on the chart timeframe. Its confirmed higher frame
  is the next timeframe: 5m->15m, 15m->1h, 30m->2h, 1h->4h, 4h->1d, 1d->1w. The HTF value used
  on chart bar t is that of the last HTF bar whose close time (bin open + HTF length) is at or
  before bar t's OPEN time. At 5m this is bit-identical to `strategies.v45_exact_amb`
  (self-test).
- (e) DOGE_L and DOGE_S: entry signals of the friend's DOGE strategy (`doge_strategy.py`
  compute_indicators/compute_signals, Astral-matching defaults). DOGE_L is the long side and
  DOGE_S is the mirrored short side. Both run on all 7 coins. Lengths are divided by
  (tf minutes / 5), rounded half up, minimum 2, as in `t_robust/run_tf.py`.
  The resulting lengths (ema_fast/slow/trend/short, stochRSI rsi/stoch/k/d, rsi, chop) are:
  5m 63/156/600/21/70/70/4/3/26/14; 15m 21/52/200/7/23/23/2/2/9/5;
  30m 11/26/100/4/12/12/2/2/4/2; 1h 5/13/50/2/6/6/2/2/2/2; 4h 2/3/13/2/2/2/2/2/2/2;
  1d all 2. At 4h and 1d the stochastic RSI degenerates and signals are structurally almost
  impossible. The friend's trailing-stop and signal exits are not used; only the entries are
  tested under the common protocol.

Look-ahead: every entry passed truncation tests at every timeframe. The prefix computed on
`df[:t+1]` matched the full computation on all bars 0..t. For V4.5 this includes an HTF frame
truncated to bars closed by bar t's open, plus a component-level check of the mapped HTF
series. Canaries with deliberate look-ahead were detected. Results are in
`harness/out/truncation_*.csv`.

Known structural zero-signal cells: N06_MACD_ORB at 1d (range = first bar of the day), and
DOGE_L/DOGE_S at 4h and 1d. V45_AMB at 1d needs about 80 weekly bars before the HTF STC
exists, so its first signals come late in IS. These cells enter the family only if n >= 100.

## 4. Gate (IS, exit-independent)

### 4.1 Statistics per cell (strategy, tf, H), H in {4, 16, 64} chart bars

- `d_c[t]` = +1 for a long signal, -1 for a short signal, 0 otherwise, on admissible bars of
  coin c.
- Forward return: `r_c,H[t] = open[t+1+H] / open[t+1] - 1`.
- `fwd` = sum over c,t of `d*r`, divided by `n = sum |d|`. This is the pooled signed mean
  over all signals of all coins; overlapping signals all count.
- Per-coin `fwd_c` and `n_c`. `n_long`/`n_short` and `fwd_long`/`fwd_short` are descriptive.
- Common-shift null: let `N_c` be the number of admissible positions of coin c. Coins with
  `N_c < 2H+4` are excluded, and `n_min = min_c N_c`. Draw B=600 integer shifts
  `k ~ U{H+1, ..., n_min-H-1}` with `numpy.random.default_rng([20260929, tf_minutes, H, H])`.
  The same shifts are used for every strategy at that (tf, H) and are applied to all coins.
  Each coin's `d` is rolled circularly inside its own admissible segment by k, and `fwd` is
  recomputed. From the resulting null: `null_mean`, `null_sd` (ddof=1),
  `z = (fwd - null_mean) / null_sd`, and the one-sided `p = 1 - Phi(z)`.
- `cost_H = 0.0014 + 0.0001 * H * tf_minutes / 480`. `E|r_H|` is the mean of `|r_c,H[t]|` over
  ALL admissible (c, t), pooled. `mu*_H = cost_H + 0.091 * E|r_H|`.
- `net_time = fwd - cost_H`; `fwd_minus_hurdle = fwd - mu*_H`.
- `symbols_pos` = number of coins with `fwd_c > 0` among the `n_coins_ge10` coins with
  `n_c >= 10`.

### 4.2 Amendment A1 (added by the harness agent before any real-data run; strictly more conservative)

On synthetic 7-coin panels with stochastic volatility, the common-shift null of the raw `fwd`
is calibrated for iid signals, for clustered signals (bursts of 4 bars) and for intraday
seasonality. It is **anti-conservative for zero-edge signals whose timing follows recent
volatility**: the sd of z is 1.23 (1h) and 1.24 (4h) instead of 1, and the rate of p < 0.05 is
0.103 and 0.093. The full raw gate (Holm first step + fwd >= mu* + symbols) passed
pure-noise signals in 1 of 360 (1h) and 3 of 1800 (4h) replicates, against a nominal rate
below 1e-4.
Source files: `harness/out/ctl_try/controls_synthetic_{1h,4h}.csv`; the full runs are
`harness/out/controls_synthetic_*.csv`. Breakout-type strategies fire preferentially in
high-volatility periods, so the raw test alone is not trusted.

A1 adds a self-normalised copy of the same test:
`rn_c,H[t] = ln(1 + r_c,H[t]) / RV`, where `RV = sqrt(sum_{j=t+1..t+H} ln(open[j+1]/open[j])^2)`
is the realised volatility inside the same forward window (`rn = 0` if `RV = 0`).
`fwd_vn`, `z_vn` and `p_vn` are computed with the identical shifts. On the 1h synthetic
panel, `z_vn` had sd 0.98-1.04 for all four zero-edge signal types (iid, burst4, voltimed,
hourtimed) and no zero-edge replicate passed. Mean planted-drift power of the full gate was
0.448 without A1 and 0.445 with A1.

### 4.3 Family and multiplicity

The family is every cell (all 37 strategies x 6 TFs x 3 H) with `n >= 100` and finite `p` and
`p_vn`. With `m = |family|`, Holm's step-down procedure is applied to `p`, giving `p_holm`,
and separately to `p_vn`, giving `p_vn_holm`, over the whole family at once. Cells with
n < 100 are reported but are not in the family.

### 4.4 Survival rule (decision column `gate_pass`)

A cell survives iff ALL of the following hold:
1. `p_holm < 0.05`
2. `p_vn_holm < 0.05` (A1)
3. `fwd >= mu*_H`
4. `symbols_pos >= 4`, OR (`n_coins_ge10 >= 1` and `symbols_pos >= 0.6 * n_coins_ge10`)
5. `n >= 100`

`gate_pass_spec` (the rule without A1, exactly as specified by the orchestrator) is reported
next to it, as a descriptive column only. Implementation: `sweep_lib.apply_gate`.

### 4.5 Descriptive only (never used for decisions)

`p_emp600` is the empirical p from the 600 shifts; its minimum is 1/601, so it cannot reach
Holm levels. `p_emp_all` is the empirical p over all admissible shifts. `t_naive` is the naive
per-signal t, which is inflated by overlap. Also descriptive: `fwd_long`, `fwd_short`,
`net_time`, and the per-coin values.

## 5. Exit stage (IS, gate survivors only)

For every surviving cell (strategy, tf, H):

- Engine: `harness/vendor/engine.py`, a byte-identical copy of `bt/engine.py` (sha256 in
  `harness/vendor/VENDOR_SHA256.txt`). Its conventions:
  - Market entry at the open of t+1, plus slippage.
  - The SL is a stop-market order filled at the stop, or at the open if the bar gaps through
    it, minus slippage.
  - The TP is a limit order filled at the target, or at a better open, with no slippage.
  - If SL and TP are both touched in one bar, the SL is taken first.
  - The trailing stop moves from the previous bar's peak.
  - A time exit fills at the close of bar `e+max_hold-1`, minus slippage.
  - Costs: fee 0.05 % per side on both sides, slippage 0.02 % per market fill, and funding
    0.01 % per 8 h pro rata over `hold * tf_minutes`, charged as a cost to both sides.
  - ATR is `fg.atr(df, 14)` at the signal bar.
  - One position per coin: signals while in a position are ignored, and a signal on the exit
    bar is allowed.
- Eligible entries are signal bars in `[lo, N-1)`, with `lo` as in section 2. Data are
  truncated at the window end; a trade still open at the last loaded bar exits there (`EOD`).
- The five exits (`sweep_lib.exit_set`):
  1. TIME_H: FIXED, sl = tp = 1e4 ATR (never hit), max_hold = H.
  2. ATR_SL2_TP3: FIXED, sl 2 ATR, tp 3 ATR, max_hold = 4H.
  3. ATR_SL3_TP6: FIXED, sl 3 ATR, tp 6 ATR, max_hold = 4H.
  4. TRAIL_SL3_TR3: TRAIL, initial stop 3 ATR, trail 3 ATR from the peak, max_hold = 4H.
  5. TIME_H_SL3: FIXED, sl 3 ATR, no tp, max_hold = H.
- Pooled over coins:
  - `trades`
  - `PF` = sum of positive net / |sum of negative net|
  - `exp_net` = mean net per trade
  - `sum_net`
  - `symbols_pos` = coins whose sum of net is > 0
  - `months_pos` = calendar months (by entry) whose sum of net is > 0
- Null: B=300 common shifts `k ~ U{4H+1, ..., n_min-4H-1}` with
  `default_rng([20260929, tf_minutes, H, 4H])`. Here `n_min` is the minimum over coins of the
  length of `[lo, N-1)`, and coins with a length at or below `8H+4` are excluded. For every
  shift, each coin's signal array is rolled inside `[lo, N-1)` and all 5 exits are re-run, which
  gives a null `exp_net` for each exit. With `z_e = (exp_net_e - mean_e) / sd_e` and
  `M_b = max_e z_e,b`, the studentised max-statistic p is
  `p_max_e = (1 + #{b : M_b >= z_e}) / (B + 1)`.
- An exit combo PASSES iff PF >= 1.2, exp_net > 0, trades >= 100, symbols_pos >= 4 (of 7), and
  p_max < 0.05.
- Selection: for each (strategy, tf) with at least one surviving H, take the single passing
  (H, exit) combo with the highest `exp_net`. Ties go to TIME_H, then to the smaller H. That
  combo is carried to OOS. If no combo passes, nothing is carried
  (`sweep_lib.select_exits`).

## 6. Holdout (OOS, 2024-07-01 .. 2025-08-06; one look; no re-selection, no parameter change)

A carried combo is CONFIRMED iff all four hold on OOS:
1. Pooled `exp_net > 0` at realistic cost.
2. `PF >= 1.1`.
3. Its gate cell (strategy, tf, H) on OOS has one-sided shift-null `p < 0.05` AND
   `p_vn < 0.05` (A1). These are raw p values, not multiplicity-adjusted.
4. `symbols_pos >= 4` of 7.

OOS uses the same code, windows (section 2), shifts rule and costs. CONFIRMED combos are only
candidates for a forward paper test. They are never traded live on this evidence.
Implementation: `sweep_lib.holdout_confirm`.

## 7. Descriptive outputs (not decisions)

1. The full IS gate table: all cells, including n < 100, with `approx` and `prev_examined`
   flags.
2. OOS persistence: the Spearman correlation of IS vs OOS `fwd - mu*` over all cells with
   finite values in both. Also reported on the subset with n >= 100 in both. And the OOS
   values of the top 10 IS cells by z (`sweep_lib.persistence`).
3. FINAL window (2025-08-07 .. 2026-09-29) values for carried combos: gate statistics and
   exit statistics with the same code. The FINAL window has already been partly seen (see
   section 8), so it confirms nothing.

## 8. Previously examined items (flagged `prev_examined=True`)

- DOGE_L and DOGE_S: the DOGE strategy was analysed on all DOGE history, including IS and OOS.
  It was also analysed on the 7 coins from 2025-03-19, which overlaps the last months of OOS
  and FINAL.
- V45_AMB: V4.5 exact AM+B was examined on BTC/ETH/SOL 5m from 2025-03, which overlaps the
  end of OOS and FINAL.
- FINAL window: the 15m FINGRAD 19/31 sets, V3.9 and OBV were examined on 15m data from
  2025-08-07 onward in stage 1, gap_1..gap_5 and the critic runs.
- Everything else is unseen in IS and OOS at every timeframe.

## 9. Power and false-pass calibration (synthetic, before real data)

`harness/out/controls_synthetic_<tf>.csv` holds the results of `sweep_lib.controls`, run on
IS-length synthetic 7-coin panels. The planted-drift oracle shifts every signal's H-bar
forward return by +1.5 * mu*_H. The table gives detection power, false-pass rates, and
MDE80 / mu*: the edge needed for 80 % power at the first Holm step, relative to the hurdle.
Two cases:

- If the combined count of all cells is far below the MDE, a "no survivor" result means the
  data could not have shown an edge of hurdle size. It does not show the absence of an edge.
- In all outputs, a cell is labelled "underpowered" when its `n` is below
  `n_req(tf, H) = 2000 * (mde80_over_mu at n_target=2000, kind=iid)^2`, taken from the
  synthetic control of its tf and H. This is optimistic: clustered signals need more.

The Discover agents may run the same controls on the real IS panel as a check. This does not
change any rule.

## 10. Known limitations (accepted in advance)

- Spot proxy for perps: no basis. Funding is a fixed cost (0.01 %/8 h), whereas real funding
  can be received or paid and varies strongly.
- The normal approximation in the extreme tail. Holm with m of about 600 needs p below about
  8e-5 (z > 3.8), which no empirical null with B=600 can check. A1 reduces, but does not
  eliminate, tail risk.
- Anti-conservatism of the exit-stage shift null for volatility-timed strategies. It is
  mitigated by A1 at the gate and by the PF/net conditions.
- Signals overlap and one position per coin is a different sample from the gate's
  all-signals sample.
- At 1d, IS has about 880 admissible bars per coin (fewer for H=64), so power is low
  (section 9).
- V39 and OBV are applied with their 15m-chart settings to every timeframe, as specified.
  V4.5 uses a generalised HTF, which is not the author's original 5m/15m-only design.
- The engine takes the SL first inside a bar and fills the TP at the limit. Stops are
  evaluated on chart-TF bars; there is no intrabar path.
- Missing bars (the whole day 2026-04-22 in FINAL; other gaps) are not filled. Recent bars may
  be revised by the vendor.

## 11. Execution protocol

- Discover agents: compute the IS gate table for their TF group
  (`harness/run_gate_tf.py` or `sweep_lib.gate`), then run `exits()` only for the survivors
  after the Combine step. They read only `sweep/data/is/`.
- Combine: concatenate all 6 TF tables, apply `apply_gate` once over the whole family,
  run exits for survivors, and select carried combos. Reads only `is/`.
- Holdout agent: the only reader of `oos/` and `final/`. It evaluates the carried combos, the
  full OOS gate table for persistence, and the FINAL values.
- Seeds: `SEED = 20260929`, with the rng keys given above. `B_GATE = 600`, `B_EXIT = 300`.
- Bug policy: if a harness bug is found after IS results exist, it is fixed and logged in
  `harness/NOTES.md` with before/after numbers. Every affected result is re-run and both
  versions are reported. The rules in this file never change after real data are seen. No
  strategy parameter, exit parameter, window, cost or threshold is changed after results
  are seen.
- The harness agent's smoke tests read only
  `/home/user/crypto-bot-research/data/btcusd-15m-ohlcv.csv` bars >= 2025-08-07 (FINAL
  window, BTC only) and synthetic data, to measure runtime and to run look-ahead tests. No
  gate decision is computed from them.
