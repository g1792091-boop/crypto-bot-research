# DOGEUSD strategy 5864: port and replication of Astral's backtest

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/port`
Nothing under `/home/user/crypto-bot-research` was modified.

## 1. Deliverable

`doge_strategy.py`, a port of Astral saved strategy 5864 (working copy 38275 was created by `astral_backtest_start`).

```python
import doge_strategy as ds
df  = ds.load_ohlcv('dogeusd-5m-last40k.csv')            # 5m, bars labelled by OPEN time
w   = df.loc['2026-09-11 00:00':'2026-09-28 23:55']      # slice = Astral backtest start (indicators start here!)
tr  = ds.simulate(w, params=None, side='long', costs=None, fill='on_close', tsl_eval='astral', warmup_bars=660)
ds.summarize(tr, sizing=0.25, col='net')                 # per-trade stats plus 25%-sized equity
ds.astral_metrics(tr, w, col='net', start_ts='2026-09-13 07:00')   # Astral's own metric definitions
```
- `params` is a dict that overrides `ds.DEFAULT`. It covers all lengths and thresholds (`ema_fast/slow/trend/short`, `stoch_rsi_len`, `stoch_len`, `k_smooth`, `d_smooth`, `rsi_len`, `chop_len`, `spread_min`, `chop_max`, `k_max`, `rsi_min`, `tsl_stages`, `use_tsl`, `use_signal_exit`) and the conventions listed in section 3.
- `side`: `'long'`, `'short'` or `'both'`. Short is the exact mirror: EMA63<EMA156, close<EMA600, spread<-0.15, CHOP<61.8, CROSS_BELOW(K,D), K>55, RSI26<48, close<EMA21. It exits on EMA63>EMA156 or CROSS_ABOVE(K,D), with a mirrored trailing stop. `'both'` holds one position at a time. A reversal on the bar of a signal exit is allowed. A new entry on the bar of a TSL exit is not.
- `costs`: `dict(fee_side, slip_side, funding_8h, maker_exit, maker_fee, model)`. The default `model='additive'` computes net = gross - fees - slippage - funding x hours/8. `model='astral'` reproduces Astral's commission and slippage arithmetic exactly (`ds.ASTRAL_5_2`).
- `fill`: `'on_close'` (Astral) or `'next_open'`.
- `tsl_eval`:
  - `'astral'`: exact Astral behaviour.
  - `'ohl_stop'` (alias `'intrabar_pess'`): path O->H->L with the fill at the stop price.
  - `'olh_stop'` (alias `'intrabar_opt'`): path O->L->H->C with the fill at the stop price.
  - `'close_only'`.
  - `'sub1m'`: walks the real 1m bars. It needs `df_1m`. `params['sub1m_path']` sets the per-minute path.
- Output columns: `signal_ts, entry_ts, exit_ts, side, entry_px, exit_px, gross, net, reason (tsl/signal/eod), tsl_stage, hold_bars, mfe, mae, stop_px, watermark`.
- One simulation over 40k bars takes about 0.01 s after the indicators are computed, or about 0.3 s with indicator computation. `ind=` and `sig=` can be passed to reuse them.

## 2. Data

| file | content | sha256 (verified vs Astral artifact) |
|---|---|---|
| `dogeusd-5m-last40k.csv` | DOGEUSD 5m, 40,000 bars, 2026-05-13 11:55 .. 2026-09-29 09:15 UTC | 5b463ca192d98b5b5d26dc401f09ab62287e4cf4130a8d2147f95c4f36ed0cf5 |
| `dogeusd-1m-last40k.csv` (= `m1/dogeusd-1m-p1.csv`) | 1m, 2026-09-01 14:15 .. 09-29 09:22 | 41f71a3ef81109375707d1da70d57c4c1d2251e260152f8cb1d7065df5cf7e36 |
| `m1/dogeusd-1m-p2..p5.csv` | 1m pages chained with `end=`: p2 08-04..09-01, p3 07-06..08-04, p4 06-09..07-06, p5 05-12..06-09 | 893f6bdc..., 156ff255..., aeb80272..., 6574927f... |
| `dogeusd-1m-merged.csv` | 200,000 1m bars, 2026-05-12 05:13 .. 09-29 09:22, no duplicates | 19f19b84b04e2f64dd9bfe7b6eeaa8811452cf2f56906ddc5c532bf3a1ffc9e1 |

QA results:
- 5m: 0 duplicates, 1 gap of 10 minutes, 0 OHLC violations, 6 open-vs-previous-close jumps above 0.5% (max 1.2%).
- 1m: gaps of 2 to 4 minutes (about 1.7k), which are minutes with no trades. 0 OHLC violations.
- Aggregating 1m into 5m reproduces the 5m bars (open/high/low/close exact in 99.7/99.9/99.9/99.8% of 39,888 bars) only with the bars labelled by open time. The close-time labelling matches about 1% of bars.
- All 135 Astral fills in the long run equal our 5m closes exactly.

## 3. Astral conventions found

Sources: the backtest JSON artifacts (`astral/backtest-*.json`, which include the trade list, orders and `debug.order_events` with every trailing-stop event) plus a grid of 360 convention combinations (`replicate.py`, `replicate_grid_{short,long}.csv`).

| item | Astral behaviour | how established |
|---|---|---|
| Indicator history | Indicators start at the backtest `start` bar. No earlier history is loaded. Trades are allowed from bar 660 (`warmup_bars_required=660` = 1.1 x 600). Results therefore depend on the chosen start date. | `backtest_period.raw_data_start == requested start`, `warmup_end` = start + 660 bars |
| Bar timestamps | Bars are labelled by open time. The "on_close" fill is the close of that labelled bar. | fills == `close[ts]` for 135/135 trades; 1m aggregation check |
| EMA | Seeded with the first value: y0=x0, alpha=2/(n+1), same as pandas `ewm(adjust=False)`. Not SMA-seeded and not adjust=True. | Two discriminating Astral runs. bt_2c4454a8cbfedd1b (09-14..09-18): Astral 10 trades starting 09-17 05:30, PF 1.545316, TR +0.16367%. The first-value seed gives exactly this (10 trades, PF 1.545316, TR 0.001637). SMA seed gives 9 trades and adjust=True gives 11. bt_26cb74321cf335eb (07-15 18:00..07-20): Astral 1 trade at 07-18 03:05 with return -0.26746%. First-value seed gives the same. SMA seed gives 0 trades and adjust=True gives 4. |
| RSI | Wilder smoothing (alpha=1/n). Rejected: EMA-alpha RSI (83/135 trades match) and Cutler SMA RSI (15/135). TA-Lib SMA-seeded Wilder, first-value Wilder and ewm(adjust=True) with alpha=1/n all give identical trades, because the seed has decayed by bar 660. Default: TA-Lib style. | grid |
| ATR (inside CHOP) | Simple moving average of true range, not Wilder. Wilder ATR matches only 119/135 and 37/40 trades. | grid |
| MIN/MAX | The rolling window includes the current bar. Excluding it gives 114/135. | grid |
| CROSS_ABOVE(a,b) | a[t]>b[t] and a[t-1]<=b[t-1]. The strict `<` variant gives identical trades (ties never occur). | grid |
| Stage boundary (>= vs >) | Not identifiable; trades are identical either way. | grid |
| Trailing stop timing | Active from the bar after the entry fill (`active_from` = entry bar + 5m). The initial stop is entry x (1-0.0035). | order_events |
| Trailing stop path | Coarse path `["open","high","low"]`. The watermark is raised with the bar high before the low is checked. The stage comes from the watermark's favourable % vs entry: <0.25% gives distance 0.35% of entry; 0.25-0.375% gives 0.20%; >=0.375% gives 0.20%. Stop = watermark - distance, tighten-only. It triggers if low <= stop. | order_events; our stop level, watermark and stage equal Astral's for all 103 TSL exits (max relative difference 1.3e-15) |
| TSL fill price | The close of the trigger bar (`price_source: strategy_bar_close_after_target_touch`), not the stop price. Astral itself flags this with warning `PROTECTION_COARSE_APPROXIMATION` and `execution_ambiguity: no_sub_bar_attempt_timing`. | order_events |
| Same-bar re-entry | Suppressed after a protective exit (`same_bar_new_exposure_policy: suppress_after_protection_exit`). It never binds in these samples. After a signal exit, a same-side re-entry is logically impossible. | protection_execution |
| Costs (`commission_bps=c`, `slippage_bps=s`) | Shares = 25% x equity / close. The buy fills at close x (1+s) and the sell at close x (1-s). Commission = c x filled notional on each side. Trade Return = PnL / (entry fill x shares). 5/2 bps costs 0.1400% per trade on average (range 0.1392-0.1422%). | Cost runs: entry px ratio 1.0002, exit 0.9998, fee/notional 0.0005 exactly; our `model='astral'` matches Astral's average trade return and total return to 1e-16 |
| Metrics | win_rate = share of trade Return > 0. profit_factor = $ wins / $ losses. total_return compounds 25% sizing. max_drawdown is mark-to-market on 5m closes from `warmup_end`. Sharpe uses 15 daily returns, annualised over 365.2425 days. | `ds.astral_metrics` reproduces all of these |

## 4. Replication results

Script: `compare_port.py`. Output: `out_compare_port.txt`.

| Astral run | window | costs | trades port / Astral / matched (entry and exit ts) | exit reason agree | metrics |
|---|---|---|---|---|---|
| saved strategy 5864 (bt_04f9194b71287a45) | 09-11..09-28 | 0/0 | 40 / 40 | - | port vs saved: PF 1.272255111704368 vs 1.272255111704374; TR 0.003729606221016 vs 0.003729606221016; avg 0.000374190478279 vs same; maxDD -0.004127721540989 vs same; win rate 0.55 vs 0.55; expectancy $9.3240. Exact to 1e-15. |
| bt_4d7868c2f1791cc6 (rerun of 5864) | 09-11..09-28 | 0/0 | 40/40/40 | 100% | Astral TR 0.0037306 and PF 1.272346. The tiny difference from the saved run comes from a vendor revision of the 09-27 12:00 and 12:20 bars between runs: entry 0.09822 vs our 0.09824, exit 0.098129 vs 0.098149. The price of one trade differs by 2e-4 relative. |
| bt_eabbc51538b849c6 (4a) | 05-13 03:05..09-28 (history capped at 40,000 bars) | 0/0 | 135/135/135 | 100% | Identical to 6 or more decimals: n 135, win rate 0.481481, PF 1.128783, avg 0.000150, TR 0.005008, maxDD -0.008103. Maximum return difference per trade 2e-16. |
| bt_4f34e72413d4b066 (4b) | same | 5/2 bps | 135/135/135 | 100% | Identical: win rate 0.274074, PF 0.385821, avg -0.001250, TR -0.041384, DD -0.041384 |
| bt_f27f67940a55d5ea (4c) | 09-11..09-28 | 5/2 bps | 40/40/40 | 100% | win rate 0.35 vs 0.35, PF 0.525248 vs 0.525272, TR -0.010228 vs -0.010227. The difference is the same 09-27 vendor revision; this run also had a different 09-27 12:20 bar. |
| bt_2c4454a8cbfedd1b | 09-14..09-18 | 0/0 | 10 vs 10 | - | PF 1.545316 vs 1.545316, TR 0.001637 vs 0.0016367 (EMA-seed test) |
| bt_26cb74321cf335eb | 07-15 18:00..07-20 | 0/0 | 1 vs 1 | - | avg -0.002675 vs -0.0026746 (EMA-seed test) |

Trade-level match rate: 100% on every run, 175 of 175 distinct trades across the two main windows. Every price matches except one trade affected by the vendor revision.

## 5. Astral's own numbers (task step 4)

| run | window | comm/slip bps | trades | win rate | PF | total return (25% sizing) | avg trade return | max DD | Sharpe |
|---|---|---|---|---|---|---|---|---|---|
| saved 5864 | 09-11..09-28 (metrics from 09-13 07:00) | 0/0 | 40 | 55.0% | 1.2723 | +0.3730% | +0.0374% | -0.413% | 2.69 |
| 4(a) bt_eabbc51538b849c6 | 05-13 03:05..09-28 (the requested 05-13 00:00 start was capped to 40,000 bars) | 0/0 | 135 | 48.15% | 1.1288 | +0.5008% | +0.0150% | -0.810% | 0.65 |
| 4(b) bt_4f34e72413d4b066 | same | 5/2 | 135 | 27.41% | 0.3858 | -4.138% | -0.1250% | -4.138% | -6.05 |
| 4(c) bt_f27f67940a55d5ea | 09-11..09-28 | 5/2 | 40 | 35.0% | 0.5253 | -1.023% | -0.1026% | -1.028% | -17.96 |

## 6. Port on the long window (task step 5)

Settings: `fill='on_close'`, zero cost, `tsl_eval='astral'`. The port gives 135 trades, identical to Astral 4(a) (see section 4). This validates the port on 135 trades and 5 months, including 103 trailing-stop exits whose stop level, watermark and stage all match.

## 7. Findings the replication exposed (evidence, not opinion)

1. The edge is small and statistically indistinguishable from zero before costs.
   - Long window, Astral conventions: mean gross +0.0150%/trade, standard error 0.0319%, t = +0.47 (n=135).
   - Original window: +0.0374%/trade, standard error 0.0625%, t = +0.60 (n=40).
   - The 55% win rate on 40 trades has a 95% binomial CI of 38.5% to 70.7%. On 135 trades the win rate is 48.1% (CI 39.5% to 56.9%).
2. This is a sub-15-minute scalper.
   - Median holding time is 1 bar (5 minutes). The mean is 1.7 bars (40 trades) or 2.0 bars (135 trades).
   - 36 of 40 and 103 of 135 exits are trailing-stop exits.
   - Stage-1 stops (74 of 135) average -0.195%. Signal exits (32) average -0.108%. Profits come from the 26 trades that reach the 0.375% stage.
3. Astral's trailing-stop model is coarse, and on this data the coarse model inflates results (`sub1m_check.py`, output in `sub1m_check.csv`).
   - For the same entries, walking the actual 1m bars inside each 5m bar changes the long-only results as follows:

     | window | Astral model | 1m walk, O->H->L per minute, fill at stop | 1m walk, O->L->H per minute |
     |---|---|---|---|
     | long window | +0.0150% | -0.0309% (t -1.74, PF 0.705) | 0.0000% |
     | original window | +0.0374% | -0.0577% (win rate 45%, PF 0.563) | -0.0087% |

   - The mechanism: Astral credits the bar's high to the watermark before the low touches the stop, and then fills at the bar close. When the real 1m sequence had the low first, the stop fired earlier at a worse level.
   - The 5m stop-fill variants (`ohl_stop` +0.027%, `olh_stop` +0.037%) are even more favourable, so they are no safer.
4. Costs overwhelm the gross effect.
   - Astral 5/2 bps: -0.125%/trade, win rate 27%.
   - The port with Binance-like costs (0.05% taker/side, 0.015% slip/side, 0.01%/8h funding): long window -0.115%/trade with the Astral TSL model and -0.13% to -0.16% with the 1m walk.
5. Shorts (port only, Astral conventions, long window):
   - short-only: 165 trades, win rate 38.8%, gross -0.0316%/trade (t -1.44), PF 0.733.
   - both sides: 300 trades, win rate 43.0%, gross -0.0107%/trade, PF 0.909.
   - With the 1m walk: short -0.052% (t -3.26), both -0.043% (t -3.58).
   - Adding shorts did not raise the win rate or the profit in this sample.
   - These are single-sample, in-sample numbers. Other agents should do the proper evaluation.
6. Platform caveats relevant to the claim that Astral is a good analysis platform:
   - Indicators restart at each backtest start date, so the first days after warmup depend on the start date.
   - Vendor bars were revised between runs minutes apart (09-27 12:00 and 12:20). The same saved strategy gave total return 0.0037296 in one run and 0.0037306 in the next.
   - The trailing stop fills at the bar close after a touch, and Astral labels this itself as a coarse approximation (warning severity "info").
   - The default costs are 0/0.
   - The Sharpe of 2.69 comes from 15 daily returns.

## 8. Other files

| file | purpose |
|---|---|
| `extract_astral.py` | Astral JSON to `astral/backtest-<id>_trades.csv` (trade list plus exit reason, stage, stop level, watermark) |
| `astral/backtest-*.json` | full Astral results: bt_4d7868c2f1791cc6 (sha 7d94b45e...), bt_eabbc51538b849c6 (ca34761a...), bt_4f34e72413d4b066 (5882d51b...), bt_f27f67940a55d5ea (9d05efa6...) |
| `astral/events_short.txt` | readable trailing-stop and order event log for the 09-11..09-28 run |
| `replicate.py`, `replicate_grid_short.csv`, `replicate_grid_long.csv` | 360-combination convention grid versus Astral trades |
| `find_discrim.py` | search for start dates where the EMA-seed variants give different trades (used to design the two EMA-seed runs) |
| `compare_port.py`, `out_compare_port.txt` | trade-level and metric comparison against the 4 main Astral runs |
| `verify_tsl.py`, `out_verify_tsl.txt` | stop, watermark and stage equality; rejected alternatives |
| `sanity_sides.py`, `out_sanity_sides.txt` | rule-consistency check of every trade (0 violations and 0 overlaps for long, short and both, with on_close and next_open) |
| `sub1m_check.py`, `sub1m_check.csv` | TSL model sensitivity including 1m path walks and Binance-like costs |
| `port_trades_0911_0928.csv`, `port_trades_long_0513_0928.csv` | port trade lists (Astral conventions, zero cost) |

## 9. Caveats

- RSI seeding variant, stage boundary and CROSS tie rule are not identifiable from Astral's output. They never change a trade after the 660-bar warmup, so the port is exact for all practical purposes. The default is TA-Lib-style Wilder RSI.
- The `sub1m` walk needs 1m data (available 2026-05-12..09-29). 1651 of about 39.9k 5m bars have fewer than 5 one-minute bars, because minutes without trades are missing. The true intra-minute order is unknown, which is why both per-minute paths are reported as a bracket.
- `next_open` is our own convention. Astral cannot run it with this spec, so it is unvalidated against Astral, but it passed the rule-consistency checks.
- Additive cost model: net = gross - 2x(fee+slip) - funding. It differs from Astral's multiplicative arithmetic by about 1e-5 per trade; use `model='astral'` for exact Astral costs.
