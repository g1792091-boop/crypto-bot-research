# Harness and pre-registration notes

Written by the harness agent on 2026-09-29. Every number below comes from code in this
directory, and the raw outputs are in `out/`. No gate statistic was computed on real IS, OOS
or FINAL sweep data.

The pre-registered rules are in `../PREREG.md`, and their hashes are in `../PREREG.sha256`.

## Files

| file | role |
|---|---|
| `sweep_lib.py` | The harness: `load`, `REGISTRY` (37), `compute_signals`, `gate`, `apply_gate`, `exits`, `select_exits`, `holdout_confirm`, `persistence`, `controls`, `truncation_test`, synthetic data. |
| `vendor/` | Byte-identical copies of `bt/{engine,strategies,fg_indicators,fg_fast,pine_indicators}.py`, `gap_4/{ports12,poc_fast}.py` and `doge/port/doge_strategy.py`. Hashes are in `vendor/VENDOR_SHA256.txt`; they are the same as the originals. |
| `run_gate_tf.py` | Discover runner for one TF: signals (cached `.npz`) and the gate table CSV. |
| `run_controls.py` | Planted-drift and zero-edge controls, on a synthetic panel (default) or a real panel. |
| `selftest.py` | Synthetic-only unit, equivalence and truncation tests. Result: 52/52 PASS (`out/selftest.log`, `out/selftest_results.csv`). |
| `smoke_real.py` | Truncation, runtime and exit-timing smoke on real BTC 15m bars from 2025-08-07 onward (FINAL window, BTC only). |
| `out/` | All outputs. `ctl_try/` holds the trial controls quoted in PREREG §4.2. `synth_gate/` is an end-to-end synthetic gate run. |

## Timeline (UTC, from file mtimes)

1. The library was developed and tested on synthetic data only. `sweep_lib.py` was last
   modified at 11:19:19.
2. `PREREG.md` was written at 11:23:23. A snapshot hash was taken at 11:23:36
   (`out/prereg_presmoke.sha256`).
3. The first read of real bars (BTC 15m from 2025-08-07, smoke) happened after 11:23:36. The
   outputs are `truncation_real_btc15m.csv` (11:31) and `timing_signals.csv` (11:32).
4. A metadata-only check of `load()` on the real IS files (1d/4h, 7 coins) printed row counts,
   first/last timestamps, gaps, misalignment and dropped rows. It printed no prices, returns,
   signals or statistics.
5. After the snapshot, neither `PREREG.md` nor `sweep_lib.py` changed. The final hashes
   equal the snapshot hashes.
6. At about 11:41, `run_gate_tf.py` was fixed. It is a runner and holds no rules.
   - Bug 1: two `--names` subsets wrote the same `gate_*_sub.csv`.
   - Bug 2: the cache tag used Python's per-process randomised `hash()`.
   - After the fix, each subset output equals the corresponding rows of a full run, including
     NaN positions (checked on `synthroot/`, the synthetic data root).
7. At 11:43:34, `../PREREG.sha256` was written. It covers `PREREG.md`, `sweep_lib.py`,
   `run_gate_tf.py` and the 8 vendor files. Check it with `cd sweep && sha256sum -c PREREG.sha256`.

**PREREG.md sha256 = `16a4e23d90c9b7605ec291d7bf936e03f505c8de50b0bd57ec859943a7a89d50`**
**sweep_lib.py sha256 = `2b20c3c155f31bbe3b51cc3b7b96a8b8c01226d6cf573cb601077d89f98cd543`**

## Verification results

**Equivalence**
- The generalised V4.5 at 5m->15m is bit-identical to `strategies.v45_exact_amb`, and to all 8
  of its sub-signals (synthetic 5m with gaps).
- DOGE at 5m equals the port's DEFAULT signals.
- The DOGE lengths per TF equal the table printed by `t_robust/run_tf.py` for 15m/30m/1h.

**HTF mapping**
- For every TF, each chart bar uses the last HTF bar with close <= the chart bar's open, and
  the next HTF bar closes after that open.
- 1w bins start on Monday.

**Null implementation**
- The FFT circular-correlation null equals a brute-force `np.roll` to 1e-12.
- The sparse gather path equals the FFT path.
- Shifts lie in [H+1, n_min-H-1].
- The fwd and rn definitions are checked by hand.
- Holm is checked against a hand computation.

**Engine**
- A TIME exit holds H bars and exits at close[e+H-1].
- Gross, cost and funding match their formulas.

**Look-ahead: synthetic data**
- 6,394 registry checks over 37 strategies x 6 TFs (1,983 of them cut exactly at a signal bar).
  0 failures.
- Every check compares the full prefix 0..t, not only bar t.
- V4.5 is tested in 4 modes: HTF resampled from the truncated chart; an explicit HTF frame
  truncated to bars closed by open[t]; and the mapped HTF components in both variants.

**Look-ahead: real BTC 15m from 2025-08-07**
- Resampled to 15m/30m/1h/4h/1d: 1,851 checks, 0 failures.
- There are no real 5m bars in this smoke, so 5m is covered by synthetic data only.

**Canaries (they must fail)**
- The `close[t+1]` look-ahead was caught in 158/158 checks.
- The V4.5 "current HTF bar" leak was caught by the explicit-frame component check in
  144/144 synthetic and 49/60 real checks.
- At the final-signal level the V4.5 leak is caught rarely (7/131), and never in
  resample-from-truncated-chart mode, because V4.5 fires rarely and STC saturates. This is
  why the component-level check exists.

**Never fired in any test data**
- N14_ICHI_RSI and N21_ST_RSI_ADX, both known to be near-zero. Their truncation checks only
  show that no spurious signals appear.
- Their building blocks are exercised by strategies that do fire: the Ichimoku family through
  N07/N08/N12; RSI/ADX/supertrend_v2 through N23, N24 and S6.

**Structural zero-signal cells** (these are properties of the strategies, not bugs)
- DOGE_L/S at 4h and 1d: the stochastic RSI with length 2 degenerates. At 4h there were at
  most 2 synthetic signals.
- N06_MACD_ORB at 1d: every bar is the day's first bar.

## Calibration and power (synthetic 7-coin IS-length panels)

Files: `out/controls_synthetic_<tf>.csv`, `out/controls_calibration_summary.csv`,
`out/controls_power_summary.csv`, `out/controls_n_required.csv`.

Setup:
- Reps: 100 at 5m, 200 elsewhere, for each (H, kind, n_target).
- Signal kinds: iid; burst4 (clustered runs of 4 bars); voltimed (probability proportional to
  the recent realised variance); hourtimed (probability proportional to the intraday volatility
  pattern).

Zero-edge false positives:

| | raw shift-null p<0.05 rate | raw z sd | full raw gate false passes | A1 (vn) p<0.05 | vn z sd | gate with A1 false passes |
|---|---|---|---|---|---|---|
| iid, all TFs | 0.043-0.064 | 0.98-1.06 | 0 | 0.048-0.058 | 1.00-1.07 | 0 |
| burst4, all TFs | 0.040-0.068 | 0.97-1.06 | 1 (30m) | 0.042-0.061 | 0.98-1.05 | 0 |
| voltimed 5m / 15m / 30m / 1h / 4h / 1d | 0.164 / 0.114 / 0.112 / 0.108 / 0.101 / 0.066 | 1.74 / 1.32 / 1.36 / 1.33 / 1.30 / 1.04 | 8/900, 3/1800, 6/1800, 1/1800, 7/1800, 0 | 0.043-0.057 | 0.98-1.03 | 0 |
| hourtimed 5m / 15m | 0.080 / 0.068 | 1.14 / 1.11 | 0 / 3 of 1800 | 0.043 / 0.050 | 0.99 | 0 |
| naive per-signal t (burst4) | 0.16-0.19 false-positive rate at nominal 0.05 | | | | | |

What this shows:
- The common-shift null correctly handles clustered or overlapping signals, where the naive t
  is badly inflated.
- The raw null is anti-conservative when signal timing follows volatility.
- Amendment A1 (self-normalised forward return) fixes that. It had 0 false passes in all
  39,600 zero-edge replicates of the full runs. The raw gate had 29 false passes in the same
  replicates: 25 voltimed, 3 hourtimed, 1 burst4.
- Planted-drift power barely changed with A1. In the full runs, `power_gate_and_vn` equals
  `power_gate` in 180 of 216 rows; the mean loss is 0.003 and the max loss 0.08.

**Power** (planted edge = 1.5 x mu*, full gate with the first Holm step, m = 666):

- iid signals, n = 2000: power 0.96-1.00 at every TF and H.
- iid signals, n = 500: 0.19-0.35 at 4h/1d and 0.24-1.0 at 5m-1h.
- iid signals, n = 150: 0.005-0.14 at 30m-1d; 0.38 at 15m H=4; 0.91 at 5m H=4.
- Clustered (burst4) signals need about 2.7-4.1x the n (`n_req` ratio).

n needed so that MDE80 <= mu* (`n_req`, iid / burst4):

| TF | H=4 | H=16 | H=64 |
|---|---|---|---|
| 5m | 281 / 759 | 737 / 2724 | 1614 / 6300 |
| 15m | 593 / 1621 | 1293 / 4761 | 2069 / 8042 |
| 30m | 878 / 2416 | 1700 / 6235 | 2346 / 9066 |
| 1h | 1313 / 3616 | 2085 / 7648 | 2700 / 10476 |
| 4h | 2347 / 6358 | 2854 / 10368 | 2331 / 8904 |
| 1d | 2904 / 8699 | 2964 / 12030 | 2168 / 8868 |

The real IS panel has 1d admissible bars from 2022-01-17 only (200-bar warm-up):
- 895 per coin for BTC/ETH/XRP/LTC/BCH.
- 803 for SOL (clean from 2021-10-01).
- 864 for DOGE.
- About 6,100 coin-bars in total.

So at 1d, a strategy needs a signal on roughly 1 bar in 2 to 1 bar in 3 to have power at the
hurdle. **A "no survivor" result at 4h/1d is mainly a power statement, not evidence of "no
edge".**

These synthetic E|r_H| values are close to real crypto but not identical. The Discover agents
can rerun `run_controls.py --split is --tf <tf>` on the real panel to get exact numbers.

## Deviation from the orchestrator's fixed PREREG text: needs the orchestrator's attention

The pre-registered decision column is `gate_pass = gate_pass_spec AND p_vn_holm < 0.05`
(amendment A1). OOS confirmation also requires `p_vn < 0.05`.

- The orchestrator's verbatim rule is computed as `gate_pass_spec`, which is descriptive only.
- A1 is strictly more conservative, and it was decided and documented before any real-data
  run, on the evidence above.
- If the orchestrator rejects A1, the verbatim rule is still available. That choice must then
  be made before the IS results are read.

Other choices the harness agent had to make where the template was silent (all are in PREREG):
- The ATR and trailing exits are capped at max_hold = 4H.
- The exit null uses shifts in [4H+1, n_min-4H-1].
- The exit max-statistic is studentised (z per exit, standardised by its own null mean and
  sd).
- "Highest net" in exit selection means the highest mean net per trade; ties go to TIME_H,
  then to the smaller H.
- The symbols rule is read literally as "4 of 7 OR 60 % of coins with >= 10 signals".
- The forward window must lie inside the split window.
- Positions are counted in bar indices, including across gaps.

## Runtime (measured) and recommended Discover grouping

Signal generation for all 37 strategies (`out/timing_signals.csv`, one core, OMP_NUM_THREADS=1):

- Per bar: 274 µs at 5m (synthetic 5m), 295 at 15m, 274 at 30m, 332 at 1h, 344 at 4h, 622 at
  1d (per-call overhead).
- The slowest strategies are N16_BBRSI (about 105 µs/bar, from the pivot loops with `iloc`),
  N05_PSAR_POC (about 40), V39_ALL (about 40) and V45_AMB (28-50).

IS coin-bars (7 coins; SOL from 2021-10-01, DOGE from 2021-08-01):

| TF | coin-bars |
|---|---|
| 5m | about 2.17 M |
| 15m | 725 k |
| 30m | 362 k |
| 1h | 181 k |
| 4h | 45 k |
| 1d | 7.5 k |

Estimated IS gate time, one process:

| TF | minutes |
|---|---|
| 5m | about 12-14 (signals about 10, gate about 2, plus about 1 to load) |
| 15m | about 4 |
| 30m | about 2 |
| 1h | about 1 |
| 4h + 1d | under 1 |

The FFT gate step itself (37 x 3 H x 7 coins, B=600 plus the all-shift null) was measured at
108 s at 5m, on a synthetic IS-length panel with 37 fake signal sets, with a peak RSS of 543
MB. So add about 2 min at 5m, and less at the other TFs.

Optional controls on the real panel take about 7 min at 5m (100 reps) and 2-5 min at the other
TFs.

**Exit stage** (`out/timing_exits.csv`):
- One pass of 5 exits over 1 coin and 40k bars at 15m takes 0.07-0.18 s for 340-2550 trades.
  That is about 14 µs per trade-exit.
- One (strategy, tf, H) combo with B=300 over 7 coins and the full IS is therefore bounded,
  for frequent strategies, by roughly: 5m 50 min, 15m 17 min, 30m 8 min, 1h 4 min, 4h/1d
  under 1 min.
- Only gate survivors enter this stage.

**Recommendation.** The whole IS gate is small, about 20 CPU-min in total, so grouping barely
matters.
- The default groups [5m], [15m, 30m], [1h, 4h, 1d] work.
- A more balanced split for 2 agents with at most 2 processes each is:
  - Agent A: [5m], with the strategies split over 2 processes (`--names`), about 7 min each.
  `--names` subsets write `gate_is_5m_sub<md5-8>.csv` (distinct per subset). The two halves' gate rows are independent
  and can simply be concatenated, because shifts are keyed by (tf, H), not by strategy.
  - Agent B: [15m, 30m] in one process and [1h, 4h, 1d] in the other.
- Budget the exit stage separately. Run the exits for 5m survivors two at a time.
- Always set `OMP_NUM_THREADS=1`. numpy's FFT/BLAS otherwise uses more than one core per
  process.

## How to use it (Discover / Combine / Holdout)

```bash
cd sweep/harness && export OMP_NUM_THREADS=1
python3 run_gate_tf.py --tf 5m --out ../discover_A          # -> gate_is_5m.csv + signals_is_5m.npz
python3 run_gate_tf.py --tf 5m --out ../discover_A --names S2_ST_ROC,N16_BBRSI   # subset -> gate_is_5m_sub<md5 of names>.csv
```

```python
import sys; sys.path.insert(0, 'sweep/harness'); import sweep_lib as L, pandas as pd
cells = L.apply_gate(pd.concat([pd.read_csv(f) for f in all_six_tf_tables]))  # Holm ONCE over all TFs
surv = cells[cells.gate_pass]                                   # decision column (A1 included)
panel = L.load_panel(tf, 'is'); sigs = L.load_signals('.../signals_is_<tf>.npz')
ex = L.exits(tf, strategy, H, panel, sigs, split='is')          # 5 exits + B=300 null + p_max
carried = L.select_exits(pd.concat(all_exit_tables))
# Holdout agent only:
g_oos = L.gate(tf, 'oos'); ex_oos = L.exits(tf, strategy, H, L.load_panel(tf, 'oos'), sigs_oos, split='oos', B=300)
L.holdout_confirm(ex_oos[ex_oos.exit == chosen].iloc[0].to_dict(), g_oos[(g_oos.strategy == s) & (g_oos.H == H)].iloc[0].to_dict())
L.persistence(cells_is, cells_oos)
```

Things to watch:
- `load(tf, sym, split)` drops every bar at or after the split's window end, so an IS load can
  never return one. For OOS it reads `oos/` (from 2024-01-01), and signals start 2024-07-01.
- The gate's `n` counts every admissible signal (overlapping ones included). The exit stage
  holds one position per coin.
- V4.5 resamples its HTF from the chart bars by default. It does not use the data agent's
  `2h`/`1w` files; their weekly anchor is not verified, and this harness uses Monday-based
  weeks.
- `compute_signals(strict=True)` raises on any strategy error. Do not silently drop
  strategies.
- `p_emp600` cannot go below 1/601, so the Holm decisions use the normal-approximation `p`
  and `p_vn`, as pre-registered.
- On synthetic data with persistent trends (the OHLCV generator), the empirical-shift p was
  much larger than the normal p for trend strategies: 0.009 against 0.0002 for N23 at 4h
  H=64 in `out/synth_gate`. There, shifts shorter than the regime length keep part of the
  edge, which makes the null conservative under the alternative. On real data, compare
  `p_emp_all` with `p` for any survivor.

## Limitations of this harness (beyond PREREG §10)

- The look-ahead tests are empirical. They cover every entry at every TF, and cut at signal
  bars, at the bar before a signal and at HTF boundaries. They are not a proof. N14/N21 never
  fired.
- There were no real 5m bars in any smoke test (not allowed). 5m is verified on synthetic
  data only.
- The synthetic vol-clustering and intraday seasonality are moderate. Real data may be harsher
  for the raw null. That is why A1 is in the decision rule, and why a real-panel control run
  is recommended.
- The exit-stage null has the same vol-timing weakness as the raw gate null. It is not
  self-normalised; see PREREG §10.
