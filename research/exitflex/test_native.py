"""Tests of native.py (the eight CORE strategies' own exits, PREREG_EXITFLEX.md Appendix A.1-A.8) and of native_ds.py (the eight
DeepSeek strategies', A.9-A.16): rules C1-C8 of A.0, tests T2 / T3 / T5 / T6 of section 13. One file for both modules.

    python -m pytest -q research/exitflex/test_native.py                 # everything
    python -m pytest -q research/exitflex/test_native.py -k test_core_   # native.py only
    python -m pytest -q research/exitflex/test_native.py -k test_ds_     # native_ds.py only

Core tests are named ``test_core_*`` and DeepSeek tests ``test_ds_*``. They print nothing but pass / fail and counts of cases.
They use synthetic bars and hand-built paths; the real-data tests compare booleans only (the strategy modules' own flags and
exits against the arrays of native.py / native_ds.py on the select-period bars of one to three coins, 2021-2023, cut before
2024-01-01 as the study cuts) and print no outcome statistic of any kind. No profit, loss, win share, hold time or trade
outcome is computed anywhere: a "first exit bar" is the index of the first chart close at which an exit condition holds on a
hand-built path, not a trade result.

REAL DATA. The real-bar tests read the study's 1m arrays from ``EXITFLEX_FG1M`` (default: this session's scratchpad folder
``fg1m``). If the folder is missing they are SKIPPED, and a skip is not a pass: at the pin and at the A1 rerun set
``EXITFLEX_REQUIRE_REAL=1`` so that a missing folder FAILS the run instead, and check that the summary line says 0 skipped.

Layout, core part
  harness     frames from OHLC lists, the mirror image of a frame, seeded random walks, independent reference indicators
              (EMA, SMA, Wilder RMA, Aroon, OBV, Heikin-Ashi written here from the textbook, not taken from the modules) and
              ``walk`` / ``first_fire``: a plain reference of rules C3 (arming), C4 (merged checks) and C7 (NaN) that runs on
              the arrays native.py returns.
  rule        the reference itself on hand-written arrays (C3 / C4 / C7, level test, event).
  structure   keys, kinds, dtypes, lengths, the DOGE scaled lengths of Appendix A.1, no new number in native.py.
  formula     every component of every strategy and side against a literal re-statement of its Appendix A code line, on
              random frames (the 23 picks' combos, the default combos and a few off-grid ones).
  hand paths  per strategy and side: a built path on which the invalidation flips at a known bar; C3 arming (N03 whipsaw,
              N10 candle leg true at i0), event rule, merged checks, NaN, levels and targets (N13, N19), no target behind
              the fill.
  causality   changing bars after i, or cutting the frame at i + 1, leaves components, levels and targets at <= i unchanged
              (every strategy, both sides).
  parity      DOGE: (state | event) == the source's long_exit / short_exit; N13: the re-derived masks == run.signals;
              synthetic and real select-period bars. ``expect=`` of native_arrays (the runner passes run.signals).

Layout, DeepSeek part (after the banner "native_ds.py")
  harness      synthetic frames, hand-built bars, a mirror (long <-> short) transform, the rule of A.0 on one signal.
  interface    the six arrays, access by name, refusal of other names, the ``expect`` check, the picks' combos, the z flags'
               attributes (pickle, copy, defaults).
  hand paths   one per strategy and side (a side is the mirror of the other): levels, targets, the first exit bar.
  z flags      F12_MSS_DISP's "live swing level" flags z_l / z_s (PREREG 6, DECISIONS 14 of native_ds): a hand-derived path,
               an independent replay of the engine, the flags vs the engine's bos / mss flags, True everywhere for the others.
  oracles      plain-Python re-derivations of A.9, A.12, A.16 (zones, pivots, ties), A.10, A.13 levels, A.14 and A.15 inputs.
  properties   own side false at its signal bars, levels on every signal bar and only there, mirror symmetry, causality
               (prefix and perturbed future, z included), F7_RF_ONLY = the opposite-signal exit (Known limit 11).
  real data    the 15 picks on the select period: equality with run.signals, levels everywhere, causality.
  -O           the safeguards survive ``python -O`` (explicit raises, not bare asserts): a subprocess check.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import pickle
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import native as N  # noqa: E402

R = N.fg()                      # research/fullgrid/run.py as module 'run'
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
T0 = int(pd.Timestamp("2021-01-04", tz="UTC").value // 1_000_000)
CUT_MS = int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000)
DATA_DIR = os.environ.get("EXITFLEX_FG1M",
                          "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/fg1m")
REQUIRE_REAL = os.environ.get("EXITFLEX_REQUIRE_REAL", "") not in ("", "0")


def skip_or_fail(why: str) -> None:
    """A real-data test cannot run: skip it, or (``EXITFLEX_REQUIRE_REAL=1``, the pin and the A1 rerun) fail, so that a missing data
    folder can never read as a pass."""
    if REQUIRE_REAL:
        pytest.fail(f"EXITFLEX_REQUIRE_REAL is set and the real-data test cannot run: {why}")
    pytest.skip(why)


# the 23 core picks: (id, strategy, timeframe, combo), as in candleague/data/candidates.json (id, name, tf and combo only)
PICKS = [
    ("core-DOGE-15m-1", "DOGE", "15m", {"ema_slow": 78, "stoch_len": 105, "spread_min": 0.3, "chop_max": 92.7}),
    ("core-DOGE-30m-1", "DOGE", "30m", {"ema_slow": 78, "stoch_len": 35, "spread_min": 0.225, "chop_max": 77.25}),
    ("core-DOGE-1h-1", "DOGE", "1h", {"ema_slow": 156, "stoch_len": 105, "spread_min": 0.075, "chop_max": 30.9}),
    ("core-DOGE-4h-1", "DOGE", "4h", {"ema_slow": 312, "stoch_len": 210, "spread_min": 0.1, "chop_max": 92.7}),
    ("core-N03_ADX_GC-15m-1", "N03_ADX_GC", "15m", {"ema_fast": 100, "ema_slow": 160, "adx_len": 5, "adx_level": 75.0}),
    ("core-N03_ADX_GC-30m-3", "N03_ADX_GC", "30m", {"ema_fast": 17, "ema_slow": 200, "adx_len": 21, "adx_level": 12.5}),
    ("core-N03_ADX_GC-1h-1", "N03_ADX_GC", "1h", {"ema_fast": 33, "ema_slow": 250, "adx_len": 5, "adx_level": 50.0}),
    ("core-N09_ALLIG_AROON-15m-3", "N09_ALLIG_AROON", "15m", {"lips_len": 15, "teeth_len": 6, "jaw_len": 26, "aroon_len": 75}),
    ("core-N09_ALLIG_AROON-30m-1", "N09_ALLIG_AROON", "30m", {"lips_len": 8, "teeth_len": 24, "jaw_len": 20, "aroon_len": 75}),
    ("core-N09_ALLIG_AROON-1h-1", "N09_ALLIG_AROON", "1h", {"lips_len": 8, "teeth_len": 10, "jaw_len": 13, "aroon_len": 75}),
    ("core-N09_ALLIG_AROON-4h-1", "N09_ALLIG_AROON", "4h", {"lips_len": 8, "teeth_len": 16, "jaw_len": 20, "aroon_len": 13}),
    ("core-N10_HA_PSAR-4h-1", "N10_HA_PSAR", "4h",
     {"sar_af_start": 0.016, "sar_af_step": 0.06, "sar_af_max": 0.133333333333, "wick_tol": 0.06}),
    ("core-N13_3OUTSIDE-30m-1", "N13_3OUTSIDE", "30m", {"engulf_min": 1.0, "prior_n": 3, "atr_len": 9}),
    ("core-N13_3OUTSIDE-1h-1", "N13_3OUTSIDE", "1h", {"engulf_min": 0.625, "prior_n": 2, "atr_len": 28}),
    ("core-N19_FIB_CHOP-15m-1", "N19_FIB_CHOP", "15m",
     {"range_len": 51, "fib_level": 0.25, "touch_atr": 0.066666666667, "slope_thr": 0.6}),
    ("core-N19_FIB_CHOP-30m-1", "N19_FIB_CHOP", "30m",
     {"range_len": 11, "fib_level": 0.333333333333, "touch_atr": 0.1, "slope_thr": 0.6}),
    ("core-N19_FIB_CHOP-4h-1", "N19_FIB_CHOP", "4h",
     {"range_len": 102, "fib_level": 0.166666666667, "touch_atr": 0.4, "slope_thr": 0.133333333333}),
    ("core-OBV_S-30m-2", "OBV_S", "30m", {"obv_ma_len": 15, "stc_level": 55.0, "stoch_k_smooth": 2, "ao_slow_len": 102}),
    ("core-OBV_S-1h-3", "OBV_S", "1h", {"obv_ma_len": 38, "stc_level": 72.0, "stoch_k_smooth": 6, "ao_slow_len": 51}),
    ("core-OBV_S-4h-1", "OBV_S", "4h", {"obv_ma_len": 38, "stc_level": 60.0, "stoch_k_smooth": 2, "ao_slow_len": 43}),
    ("core-S4_BB_BBP-30m-1", "S4_BB_BBP", "30m", {"bb_len": 25, "bb_mult": 4.0, "sq_lookback": 80, "sq_pct": 0.6}),
    ("core-S4_BB_BBP-1h-2", "S4_BB_BBP", "1h", {"bb_len": 40, "bb_mult": 4.0, "sq_lookback": 33, "sq_pct": 0.3}),
    ("core-S4_BB_BBP-4h-1", "S4_BB_BBP", "4h", {"bb_len": 25, "bb_mult": 3.0, "sq_lookback": 150, "sq_pct": 0.16}),
]
PICK_IDS = [p[0] for p in PICKS]
NAMES = N.CORE
SIDES = ("long", "short")
SIDE_SIGN = {"long": 1, "short": -1}

# combos that make the signal-bearing strategies (N13, N19) fire often on short random walks, for the causality tests
LOOSE = {
    "N13_3OUTSIDE": {"engulf_min": 0.1, "prior_n": 2, "atr_len": 5},
    "N19_FIB_CHOP": {"range_len": 8, "fib_level": 0.5, "touch_atr": 1.0, "slope_thr": 0.05},
}
# small-length combos for hand paths (all lengths are free numbers of the pick's combo, not new numbers)
SMALL = {
    "DOGE": {"ema_slow": 336, "stoch_len": 144, "spread_min": 0.15, "chop_max": 61.8},          # on 4h: EMA 2 / 7, StochRSI 2/3/2/2
    "N03_ADX_GC": {"ema_fast": 3, "ema_slow": 8, "adx_len": 3, "adx_level": 20.0},
    "N09_ALLIG_AROON": {"lips_len": 3, "teeth_len": 5, "jaw_len": 8, "aroon_len": 5},
    "N10_HA_PSAR": {"sar_af_start": 0.02, "sar_af_step": 0.02, "sar_af_max": 0.2, "wick_tol": 0.02},
    "N13_3OUTSIDE": {"engulf_min": 0.2, "prior_n": 2, "atr_len": 3},
    "N19_FIB_CHOP": {"range_len": 6, "fib_level": 0.5, "touch_atr": 0.5, "slope_thr": 0.1},
    "OBV_S": {"obv_ma_len": 5, "stc_level": 70.0, "stoch_k_smooth": 4, "ao_slow_len": 34},
    "S4_BB_BBP": {"bb_len": 5, "bb_mult": 2.0, "sq_lookback": 100, "sq_pct": 0.2},
}


# ====================================================================================================== harness
def frame_ohlc(o, h, l, c, v=None, tf="1h"):
    """A chart frame (columns ts, open, high, low, close, volume; UTC bins of ``tf``) from OHLC lists."""
    n = len(c)
    ts = pd.to_datetime(T0 + np.arange(n, dtype=np.int64) * TF_MS[tf], unit="ms", utc=True)
    vol = np.full(n, 100.0) if v is None else np.asarray(v, dtype=float)
    return pd.DataFrame({"ts": ts, "open": np.asarray(o, float), "high": np.asarray(h, float), "low": np.asarray(l, float),
                         "close": np.asarray(c, float), "volume": vol})


def path_frame(c, wick=0.3, lower=None, upper=None, v=None, tf="1h", o=None):
    """Bars from a close path: open = previous close (bar 0: its own close), high = max(o, c) + wick, low = min(o, c) - wick;
    ``lower`` / ``upper`` (per-bar arrays) replace the wick below / above."""
    c = np.asarray(c, dtype=float)
    o = np.r_[c[0], c[:-1]] if o is None else np.asarray(o, dtype=float)
    up = np.full(len(c), wick) if upper is None else np.asarray(upper, float)
    lw = np.full(len(c), wick) if lower is None else np.asarray(lower, float)
    return frame_ohlc(o, np.maximum(o, c) + up, np.minimum(o, c) - lw, c, v, tf)


def mirror(df: pd.DataFrame, K: float) -> pd.DataFrame:
    """The mirror image of a frame about the price K (open, close -> K - x; high <-> K - low). Every long condition of the
    original is the short condition of the mirror image, with the same bars (volume is kept)."""
    d = df.copy()
    d["open"], d["close"] = K - df["open"], K - df["close"]
    d["high"], d["low"] = K - df["low"], K - df["high"]
    return d


def rand_frame(seed: int, n: int = 600, tf: str = "1h", sigma: float = 0.01, price0: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = price0 * np.exp(np.cumsum(rng.normal(0, sigma, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, sigma / 4, n))
    span = np.abs(rng.normal(0, sigma / 2, n))
    h = np.maximum(o, c) * (1 + span)
    l = np.minimum(o, c) * (1 - span)
    return frame_ohlc(o, h, l, c, rng.uniform(1, 5, n), tf)


def cont_frame(df: pd.DataFrame, i: int, seed: int) -> pd.DataFrame:
    """``df`` with every bar after i replaced by another random walk (wilder, with other volume) that starts at close[i]."""
    n = len(df)
    tail = rand_frame(seed, n - i - 1, sigma=0.03, price0=float(df["close"].iloc[i]))
    out = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        out.loc[out.index[i + 1:], col] = tail[col].to_numpy() * (3.0 if col == "volume" else 1.0)
    return out


def same(a, b) -> bool:
    return bool(np.array_equal(np.asarray(a, float), np.asarray(b, float), equal_nan=True))


def arrays_of(r: dict) -> dict:
    """Every array of a native_arrays result under a flat name."""
    out = {}
    for side in SIDES:
        for k, (kind, arr) in enumerate(r["comp_" + side]):
            out[f"comp_{side}{k}_{kind}"] = arr
    for key in ("lvl_long", "lvl_short", "tgt_long", "tgt_short"):
        out[key] = r[key]
    return out


# ---- independent reference indicators (textbook; the modules' functions are not used here)
def ref_ema(x, n, minp=0):
    """EMA with alpha = 2 / (n + 1), seeded with the first value; NaN until ``minp`` bars (pandas ewm adjust=False)."""
    a = 2.0 / (n + 1)
    y = np.full(len(x), np.nan)
    s = None
    for i, v in enumerate(x):
        s = v if s is None else a * v + (1 - a) * s
        if i + 1 >= minp:
            y[i] = s
    return y


def ref_sma(x, n):
    y = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        y[i] = float(np.mean(x[i - n + 1:i + 1]))
    return y


def ref_rma(x, n):
    """Wilder's moving average (alpha = 1 / n), seeded with the first value, NaN until n bars."""
    a = 1.0 / n
    y = np.full(len(x), np.nan)
    s = None
    for i, v in enumerate(x):
        s = v if s is None else a * v + (1 - a) * s
        if i + 1 >= n:
            y[i] = s
    return y


def ref_atr(h, l, c, n):
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return ref_rma(tr, n)


def ref_aroon(h, l, n):
    """Aroon up / down: 100 x (n - bars since the highest high / lowest low of the last n bars, the most recent on ties) / n."""
    up = np.full(len(h), np.nan)
    dn = np.full(len(h), np.nan)
    for i in range(n - 1, len(h)):
        wh, wl = h[i - n + 1:i + 1][::-1], l[i - n + 1:i + 1][::-1]       # index 0 = the latest bar
        up[i] = 100.0 * (n - int(np.argmax(wh))) / n
        dn[i] = 100.0 * (n - int(np.argmin(wl))) / n
    return up, dn


def ref_obv(c, v):
    o = np.zeros(len(c))
    for i in range(1, len(c)):
        o[i] = o[i - 1] + (v[i] if c[i] > c[i - 1] else -v[i] if c[i] < c[i - 1] else 0.0)
    return o


def ref_ha(o, h, l, c):
    hc = (o + h + l + c) / 4.0
    ho = np.empty(len(c))
    ho[0] = (o[0] + c[0]) / 2.0
    for i in range(1, len(c)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2.0
    return ho, hc, np.maximum.reduce([h, ho, hc]), np.minimum.reduce([l, ho, hc])


def first_true(mask, start):
    """First index > start where mask is true (None when none)."""
    idx = np.flatnonzero(np.asarray(mask, bool))
    idx = idx[idx > start]
    return int(idx[0]) if len(idx) else None


# ---- the reference of rules C3 / C4 / C7 on the arrays native.py returns
def walk(side: int, comps, lvl0: float, close, i0: int, groups=None) -> list:
    """For each check (a list of chart-bar indices, walked in time order; default one check per bar after i0): did the rule
    fire there? ``comps`` = [(kind, array)], ``lvl0`` = the position's invalidation level (NaN none), ``close`` = the pick's
    closes. C3: a state component (and the level test) is armed once it is false at a pick close in [i0, i - 1] (the level
    test: the close is not beyond the level); it fires where it is true and armed. An event fires where it is true on a bar
    after i0. C4: a merged check walks its bars in time order, arming and testing each, and fires if any bar fires. C7: a NaN
    value neither fires nor arms; a NaN level means none."""
    n = len(close)
    if groups is None:
        groups = [[i] for i in range(i0 + 1, n)]
    armed = [kind == "state" and arr[i0] == 0.0 for kind, arr in comps]
    has_lvl = bool(np.isfinite(lvl0))
    armed_lvl = bool(has_lvl and np.isfinite(close[i0]) and side * (lvl0 - close[i0]) <= 0)
    out = []
    for g in groups:
        fired = False
        for i in g:
            for k, (kind, arr) in enumerate(comps):
                v = arr[i]
                if np.isnan(v):
                    continue
                if kind == "event":
                    fired |= v == 1.0
                elif v == 1.0:
                    fired |= armed[k]
                else:
                    armed[k] = True
            if has_lvl and np.isfinite(close[i]):
                if side * (lvl0 - close[i]) > 0:
                    fired |= armed_lvl
                else:
                    armed_lvl = True
        out.append(bool(fired))
    return out


def first_fire(r: dict, side: str, i0: int, close, groups=None, lvl0=None):
    """The first check at which the rule of ``side`` fires on the result ``r`` of native_arrays: the bar index (per-bar
    checks) or the index of the check in ``groups``; None when it never fires. ``lvl0`` overrides the level at i0."""
    s = SIDE_SIGN[side]
    lv = r["lvl_" + side][i0] if lvl0 is None else lvl0
    comps = r["comp_" + side]
    res = walk(s, comps, lv, np.asarray(close, float), i0, groups)
    if groups is None:
        bars = list(range(i0 + 1, len(close)))
        return next((b for b, f in zip(bars, res) if f), None)
    return next((k for k, f in enumerate(res) if f), None)


def comp_first(r: dict, side: str, k: int, start: int):
    """The first bar after ``start`` where component k of ``side`` is true (its own value, without arming)."""
    return first_true(N.as_bool(r["comp_" + side][k][1]), start)


def target_in_use(tgt, fill, side) -> bool:
    """Rule C6 (the kernel's TP_STRUCT rule): a native target is a take-profit only when it lies beyond the fill; NaN is none."""
    return bool(np.isfinite(tgt) and (tgt - fill) * side > 0)


# ====================================================================================================== rule (the reference)
def _arr(*v):
    return np.array(v, dtype=float)


def test_core_rule_state_armed_by_a_false_close_at_i0():
    # a state component false at i0 is armed at once and fires at the first later true close
    st = _arr(0, 0, 1, 1)
    assert walk(1, [("state", st)], np.nan, np.ones(4), 0) == [False, True, True]


def test_core_rule_state_true_at_i0_waits_for_a_false_close():
    st = _arr(1, 1, 1, 0, 1, 1)                       # true at i0 and after: not armed until bar 3 is false
    assert walk(1, [("state", st)], np.nan, np.ones(6), 0) == [False, False, False, True, True]
    assert walk(1, [("state", _arr(1, 1, 1, 1))], np.nan, np.ones(4), 0) == [False, False, False]      # never false: never fires


def test_core_rule_event_counts_only_after_i0():
    ev = _arr(1, 0, 0, 1, 0)
    assert walk(1, [("event", ev)], np.nan, np.ones(5), 0) == [False, False, True, False]      # i0 itself is not a check


def test_core_rule_nan_neither_fires_nor_arms():
    st = _arr(1, np.nan, 1, 1)                        # true at i0, unknown, true: a NaN would arm if it were read as false
    assert walk(1, [("state", st)], np.nan, np.ones(4), 0) == [False, False, False]
    assert walk(1, [("state", np.where(np.isnan(st), 0.0, st))], np.nan, np.ones(4), 0) == [False, True, True]
    assert walk(1, [("event", _arr(0, np.nan, np.nan, 1))], np.nan, np.ones(4), 0) == [False, False, True]
    assert walk(1, [("state", _arr(0, np.nan, 1))], np.nan, np.ones(3), 0) == [False, True]      # armed at i0, NaN skipped


def test_core_rule_level_test_long_and_short():
    close = _arr(10, 11, 9.5, 12, 8)
    # long: fires where the close is below the level once armed at i0 (close not beyond it)
    assert walk(1, [], 9.0, close, 0) == [False, False, False, True]
    assert walk(-1, [], 12.5, -close + 22, 0) == [False, False, False, True]       # mirrored closes 12,11,12.5,10,14: short fires at 14
    assert walk(-1, [], 12.0, _arr(11, 12.5, 11, 13), 0) == [True, False, True]
    # a level that is already beyond at i0 is armed only by a close on the right side
    assert walk(1, [], 10.5, _arr(10, 10, 11, 10), 0) == [False, False, True]
    assert walk(1, [], np.nan, _arr(10, 1, 1), 0) == [False, False]                    # a NaN level is none
    assert walk(1, [], 9.0, _arr(10, np.nan, 12, 8), 0) == [False, False, True]        # a NaN close is skipped


def test_core_rule_merged_check_fires_on_any_bar():
    st = _arr(0, 1, 0, 1, 0)
    # bars 1 and 2 in one check: true at 1 (armed) fires although bar 2 is false
    assert walk(1, [("state", st)], np.nan, np.ones(5), 0, [[1, 2], [3, 4]]) == [True, True]
    st2 = _arr(1, 1, 0, 1, 1)                          # unarmed at i0; bar 2 arms, bar 3 fires: both in one merged check
    assert walk(1, [("state", st2)], np.nan, np.ones(5), 0, [[1], [2, 3], [4]]) == [False, True, True]
    assert walk(1, [("state", st2)], np.nan, np.ones(5), 0, [[1], [2], [3], [4]]) == [False, False, True, True]
    assert walk(1, [("event", _arr(0, 0, 1, 0))], np.nan, np.ones(4), 0, [[1, 2], [3]]) == [True, False]


# ====================================================================================================== structure
@pytest.mark.parametrize("pid,name,tf,combo", PICKS, ids=PICK_IDS)
def test_core_structure_of_every_pick(pid, name, tf, combo):
    df = rand_frame(11, 400, tf)
    r = N.native_arrays(name, df, tf, combo)
    n = len(df)
    spec = N.SPEC[name]
    assert set(r) >= {"comp_long", "comp_short", "lvl_long", "lvl_short", "tgt_long", "tgt_short"}
    for side in SIDES:
        comps = r["comp_" + side]
        assert [k for k, _ in comps] == [k for k, _ in spec[side]]
        assert len(comps) <= 6                                                # kernel_x.NC
        assert len(r["names_" + side]) == len(comps)
        for kind, arr in comps:
            assert kind in ("state", "event")
            assert isinstance(arr, np.ndarray) and arr.dtype == np.float64 and len(arr) == n
            assert set(np.unique(arr[np.isfinite(arr)])) <= {0.0, 1.0}
            assert N.as_bool(arr).dtype == bool and not N.as_bool(arr)[np.isnan(arr)].any()
    for key in ("lvl_long", "lvl_short", "tgt_long", "tgt_short"):
        assert r[key].dtype == np.float64 and len(r[key]) == n
    if not spec["level"]:
        assert all(np.isnan(r[k]).all() for k in ("lvl_long", "lvl_short"))
    if not spec["target"]:
        assert all(np.isnan(r[k]).all() for k in ("tgt_long", "tgt_short"))


# the kinds of Appendix A.1-A.8 (written here from the Appendix text, not read from native.SPEC): per side, in order; the level
# test of N13_3OUTSIDE and N19_FIB_CHOP is the level array, not a component
APPENDIX_KINDS = {
    "DOGE": ("state", "event"),             # A.1: ema_fast < ema_slow; K crosses below D (mirror: > ; above)
    "N03_ADX_GC": ("state", "state"),       # A.2: EMA leg; ADX < adx_level
    "N09_ALLIG_AROON": ("state",),          # A.3: fin & ~long_state
    "N10_HA_PSAR": ("state", "state"),      # A.4: PSAR direction; strong HA candle
    "N13_3OUTSIDE": ("event",),             # A.5: the opposite run.signals flag (+ the level)
    "N19_FIB_CHOP": ("state",),             # A.6: slope <= -slope_thr (+ the level)
    "OBV_S": ("state",),                    # A.7
    "S4_BB_BBP": ("state", "state"),        # A.8: close vs mid; bull-bear power
}
APPENDIX_LEVEL_AND_TARGET = {"N13_3OUTSIDE", "N19_FIB_CHOP"}


@pytest.mark.parametrize("name", NAMES)
def test_core_kinds_levels_and_targets_follow_appendix_a(name):
    assert set(APPENDIX_KINDS) == set(NAMES) == set(N.SPEC)
    df = rand_frame(13, 1500, "1h", sigma=0.012)
    combo = LOOSE.get(name, SMALL[name])
    r = N.native_arrays(name, df, "1h", combo)
    for side in SIDES:
        assert tuple(k for k, _ in r["comp_" + side]) == APPENDIX_KINDS[name]
    has = name in APPENDIX_LEVEL_AND_TARGET
    for key in ("lvl_long", "lvl_short", "tgt_long", "tgt_short"):
        assert bool(np.isfinite(r[key]).any()) == has, key                     # signals exist on this frame for N13 and N19


@pytest.mark.parametrize("name", NAMES)
def test_core_empty_and_tiny_frames(name):
    for n in (0, 1, 2, 5, 30):
        df = rand_frame(3, max(n, 1), "1h").iloc[:n]
        r = N.native_arrays(name, df, "1h", {})
        assert all(len(a) == n for a in arrays_of(r).values())


def test_core_unknown_strategy_is_refused():
    with pytest.raises(KeyError):
        N.native_arrays("V39_ALL", rand_frame(1, 50), "1h", {})


def test_core_default_combo_equals_empty_combo():
    df = rand_frame(5, 300)
    for name in NAMES:
        a = arrays_of(N.native_arrays(name, df, "1h", None))
        b = arrays_of(N.native_arrays(name, df, "1h", R.default_combo("core", name)))
        assert all(same(a[k], b[k]) for k in a)


def test_core_doge_scaled_lengths_match_appendix_a1():
    M = R.core_module("DOGE")
    want = {"15m": (21, 26, 23, 35, 2, 2), "30m": (11, 13, 12, 6, 2, 2), "1h": (5, 13, 6, 9, 2, 2), "4h": (2, 7, 2, 4, 2, 2)}
    for pid, name, tf, combo in PICKS:
        if name == "DOGE":
            p = M.doge_params(tf, **combo)
            assert (p["ema_fast"], p["ema_slow"], p["stoch_rsi_len"], p["stoch_len"], p["k_smooth"], p["d_smooth"]) == want[tf]


def test_core_native_py_adds_no_number_and_reads_no_future():
    src = open(os.path.join(HERE, "native.py")).read()
    tree = ast.parse(src)
    doc_ids = set()
    for node in ast.walk(tree):                                   # docstrings are not code
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                doc_ids.add(id(body[0].value))
    nums = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool) and id(n) not in doc_ids}
    # the only numbers: counts, shifts of the module's own helpers (2 and 1 bars, a 3-bar pattern window), the mirror 1 - f
    # and zero tests. Nothing else (no threshold, no length) may appear.
    assert nums <= {0, 1, 2, 3}, sorted(nums)
    for bad in ("shift(-", "center=True", "bfill", "[::-1]", "iloc[-", ".shift(-"):
        assert bad not in src, bad


# ====================================================================================================== formula
def _lit(M, name, df, tf, combo):
    """Appendix A's 'Code' line of each strategy written out literally (explicit loops / numpy, not native.py's helpers):
    {(side, k): (kind, bool truth array, finite-inputs array)}. NaN handling is the Appendix's boolean formula."""
    n = len(df)
    out = {}
    if name == "DOGE":
        p = M.doge_params(tf, **combo)
        d = M._frame(df)
        ind = M.ds.compute_indicators(d, p)
        ef, es = ind["ema_fast"].to_numpy(float), ind["ema_slow"].to_numpy(float)
        K, D = ind["K"].to_numpy(float), ind["D"].to_numpy(float)
        xb, xa = np.zeros(n, bool), np.zeros(n, bool)
        for i in range(1, n):
            xb[i] = bool(K[i] < D[i] and K[i - 1] >= D[i - 1])                     # the locked 'le' crosses
            xa[i] = bool(K[i] > D[i] and K[i - 1] <= D[i - 1])
        okE = np.isfinite(ef) & np.isfinite(es)
        okK = np.zeros(n, bool)
        for i in range(1, n):
            okK[i] = bool(np.isfinite([K[i], D[i], K[i - 1], D[i - 1]]).all())
        out[("long", 0)] = ("state", np.array([bool(a < b) for a, b in zip(ef, es)]), okE)
        out[("long", 1)] = ("event", xb, okK)
        out[("short", 0)] = ("state", np.array([bool(a > b) for a, b in zip(ef, es)]), okE)
        out[("short", 1)] = ("event", xa, okK)
    elif name == "N03_ADX_GC":
        p = M._resolve(combo)
        ef, es = np.asarray(M.fg.ema(df["close"], p["ema_fast"]), float), np.asarray(M.fg.ema(df["close"], p["ema_slow"]), float)
        _a, _b, adx = M.fg.dmi_adx(df, p["adx_len"], p["adx_len"])
        adx = np.asarray(adx, float)
        okE, okA = np.isfinite(ef) & np.isfinite(es), np.isfinite(adx)
        with np.errstate(invalid="ignore"):
            out[("long", 0)] = ("state", ef < es, okE)
            out[("long", 1)] = ("state", adx < p["adx_level"], okA)
            out[("short", 0)] = ("state", ef > es, okE)
            out[("short", 1)] = ("state", adx < p["adx_level"], okA)
    elif name == "N09_ALLIG_AROON":
        p = M._resolve(combo)
        cl = df["close"].to_numpy(float)
        lips, teeth, jaw = ref_sma(cl, p["lips_len"]), ref_sma(cl, p["teeth_len"]), ref_sma(cl, p["jaw_len"])
        up, dn = ref_aroon(df["high"].to_numpy(float), df["low"].to_numpy(float), p["aroon_len"])
        fin = np.isfinite(lips) & np.isfinite(teeth) & np.isfinite(jaw) & np.isfinite(up) & np.isfinite(dn)
        with np.errstate(invalid="ignore"):
            long_state = (lips > teeth) & (lips > jaw) & ((up - dn) >= 0)
            short_state = (lips < teeth) & (lips < jaw) & ((dn - up) >= 0)
        out[("long", 0)] = ("state", fin & ~long_state, fin)
        out[("short", 0)] = ("state", fin & ~short_state, fin)
    elif name == "N10_HA_PSAR":
        p = M._resolve(combo)
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        ho, hc, hh, hl = ref_ha(o, h, l, c)
        _ps, pdir = M.fg_fast.parabolic_sar(df, p["sar_af_start"], p["sar_af_step"], p["sar_af_max"])
        pdir = np.asarray(pdir, float)
        tol = np.abs(hh - hl) * p["wick_tol"]
        bmax, bmin = np.maximum(ho, hc), np.minimum(ho, hc)
        okP = np.isfinite(pdir)
        okH = np.ones(n, bool)
        with np.errstate(invalid="ignore"):
            out[("long", 0)] = ("state", pdir < 0, okP)
            out[("long", 1)] = ("state", (hc < ho) & (np.abs(hh - bmax) <= tol), okH)
            out[("short", 0)] = ("state", pdir > 0, okP)
            out[("short", 1)] = ("state", (hc > ho) & (np.abs(bmin - hl) <= tol), okH)
    elif name == "OBV_S":
        p = M._resolve(combo)
        o = ref_obv(df["close"].to_numpy(float), df["volume"].to_numpy(float))
        ma = ref_sma(o, p["obv_ma_len"])
        ok = np.isfinite(ma)
        with np.errstate(invalid="ignore"):
            out[("long", 0)] = ("state", o < ma, ok)
            out[("short", 0)] = ("state", o > ma, ok)
    elif name == "S4_BB_BBP":
        p = M._resolve(combo)
        c = df["close"].to_numpy(float)
        mid = ref_sma(c, p["bb_len"])
        ema13 = ref_ema(c, M.BBP_LEN, M.BBP_LEN)
        bbp = df["high"].to_numpy(float) + df["low"].to_numpy(float) - 2.0 * ema13
        okM, okB = np.isfinite(mid), np.isfinite(bbp)
        with np.errstate(invalid="ignore"):
            out[("long", 0)] = ("state", c < mid, okM)
            out[("long", 1)] = ("state", bbp < 0.0, okB)
            out[("short", 0)] = ("state", c > mid, okM)
            out[("short", 1)] = ("state", bbp > 0.0, okB)
    return out


def _formula_cases():
    cases = []
    for pid, name, tf, combo in PICKS:
        if name not in ("N13_3OUTSIDE", "N19_FIB_CHOP"):                      # their events / levels have their own tests
            cases.append((pid, name, tf, combo))
    for name in NAMES:
        if name in ("N13_3OUTSIDE", "N19_FIB_CHOP"):
            continue
        cases.append((f"default-{name}", name, "1h", R.default_combo("core", name)))
        cases.append((f"small-{name}", name, "4h", SMALL[name]))
    return cases


@pytest.mark.parametrize("cid,name,tf,combo", _formula_cases(), ids=[c[0] for c in _formula_cases()])
def test_core_components_equal_the_appendix_formulas(cid, name, tf, combo):
    M = R.core_module(name)
    for seed in (21, 22):
        df = rand_frame(seed, 700, tf, sigma=0.012)
        r = N.native_arrays(name, df, tf, combo)
        lit = _lit(M, name, df, tf, combo)
        assert set(lit) == {(s, k) for s in SIDES for k in range(len(r["comp_" + s]))}
        for (side, k), (kind, truth, ok) in lit.items():
            rk, arr = r["comp_" + side][k]
            assert rk == kind
            # Appendix boolean formula, with NaN -> False for the comparison and unknown (NaN) where an input is not finite
            assert np.array_equal(np.isnan(arr), ~ok), (side, k)
            assert np.array_equal(N.as_bool(arr), truth & ok), (side, k)


# ---- N13 / N19 against literal re-statements
def _n13_lit(M, df, combo):
    """The pattern, breakout and per-signal PH / PL of A.5 with plain loops: (long flags, short flags, {i0: (lag, PH, PL)})."""
    p = M._resolve(combo)
    d = df.reset_index(drop=True)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    a = np.asarray(M.fg.atr(d, p["atr_len"]), float)
    bull, bear = np.zeros(n, bool), np.zeros(n, bool)
    for j in range(3, n):
        if j - 2 - p["prior_n"] < 0 or np.isnan(a[j]):
            continue
        B1, B2, B3 = c[j - 2] - o[j - 2], c[j - 1] - o[j - 1], c[j] - o[j]
        dn = c[j - 3] < c[j - 2 - p["prior_n"]]
        up = c[j - 3] > c[j - 2 - p["prior_n"]]
        bull[j] = dn and B1 < 0 and B2 > 0 and B2 >= p["engulf_min"] * a[j] and o[j - 1] <= c[j - 2] and c[j - 1] >= o[j - 2] \
            and B3 > 0 and c[j] > c[j - 1]
        bear[j] = up and B1 > 0 and B2 < 0 and -B2 >= p["engulf_min"] * a[j] and o[j - 1] >= c[j - 2] and c[j - 1] <= o[j - 2] \
            and B3 < 0 and c[j] < c[j - 1]
    long, short, info_l, info_s = np.zeros(n, bool), np.zeros(n, bool), {}, {}
    for i in range(n):
        for lag in (1, 2):                                        # lag 1 first: it wins when both hold
            j = i - lag
            if j < 2 or i < 1:
                continue
            PH, PL = float(np.max(h[j - 2:j + 1])), float(np.min(l[j - 2:j + 1]))
            if bull[j] and c[i] > PH and c[i - 1] <= PH and i not in info_l:
                long[i] = True
                info_l[i] = (lag, PH, PL)
            if bear[j] and c[i] < PL and c[i - 1] >= PL and i not in info_s:
                short[i] = True
                info_s[i] = (lag, PH, PL)
    both = long & short
    short &= ~long
    for i in np.flatnonzero(both):
        info_s.pop(int(i), None)
    return long, short, info_l, info_s


def test_core_n13_levels_targets_and_events_on_random_walks():
    M = R.core_module("N13_3OUTSIDE")
    combo = LOOSE["N13_3OUTSIDE"]
    nl = ns = 0
    for seed in range(40, 46):
        df = rand_frame(seed, 1500, "1h", sigma=0.01)
        r = N.native_arrays("N13_3OUTSIDE", df, "1h", combo)
        long, short, il, is_ = _n13_lit(M, df, combo)
        lo, sh = M.signals(df, "1h", **combo)
        assert np.array_equal(long, lo) and np.array_equal(short, sh)          # the literal pattern == the module
        assert np.array_equal(N.as_bool(r["comp_long"][0][1]), sh) and np.array_equal(N.as_bool(r["comp_short"][0][1]), lo)
        assert [k for k, _ in r["comp_long"]] == ["event"]
        lvl_l, tgt_l, lvl_s, tgt_s = r["lvl_long"], r["tgt_long"], r["lvl_short"], r["tgt_short"]
        assert np.array_equal(np.isfinite(lvl_l), lo) and np.array_equal(np.isfinite(tgt_l), lo)
        assert np.array_equal(np.isfinite(lvl_s), sh)
        for i, (lag, PH, PL) in il.items():
            assert lvl_l[i] == PL and tgt_l[i] == PH + (PH - PL) and PL < PH
            assert lvl_l[i] < df["close"].iloc[i]                       # PL < c[i0]: the level leg is armed at once
        for i, (lag, PH, PL) in is_.items():
            assert lvl_s[i] == PH and lvl_s[i] > df["close"].iloc[i]
            t = PL - (PH - PL)
            assert (tgt_s[i] == t) if t > 0 else np.isnan(tgt_s[i])
        nl, ns = nl + len(il), ns + len(is_)
    assert nl >= 10 and ns >= 10                                           # the case is not vacuous


def test_core_n19_levels_and_targets_on_random_walks():
    M = R.core_module("N19_FIB_CHOP")
    nl = ns = 0
    for combo in (LOOSE["N19_FIB_CHOP"], dict(LOOSE["N19_FIB_CHOP"], fib_level=0.25), dict(LOOSE["N19_FIB_CHOP"], fib_level=0.7)):
        p = M._resolve(combo)
        for seed in range(50, 54):
            df = rand_frame(seed, 1200, "30m", sigma=0.01)
            r = N.native_arrays("N19_FIB_CHOP", df, "30m", combo)
            lo, sh = M.signals(df, "30m", **combo)
            h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
            n = len(df)
            for i in range(n):
                if lo[i] or sh[i]:
                    w = slice(i - 3 - p["range_len"] + 1, i - 3 + 1)               # range_len bars ending 3 bars before i0
                    hh, ll = float(np.max(h[w])), float(np.min(l[w]))
                    R_ = hh - ll
                    f = p["fib_level"]
                    if lo[i]:
                        assert r["lvl_long"][i] == pytest.approx(hh - f * R_, rel=1e-12, abs=1e-12)
                        assert r["tgt_long"][i] == hh
                        assert r["lvl_long"][i] < df["close"].iloc[i]                  # armed at once
                        nl += 1
                    else:
                        assert r["lvl_short"][i] == pytest.approx(ll + f * R_, rel=1e-12, abs=1e-12)
                        assert r["tgt_short"][i] == ll
                        assert r["lvl_short"][i] > df["close"].iloc[i]
                        ns += 1
            assert np.array_equal(np.isfinite(r["lvl_long"]), lo) and np.array_equal(np.isfinite(r["tgt_long"]), lo)
            assert np.array_equal(np.isfinite(r["lvl_short"]), sh) and np.array_equal(np.isfinite(r["tgt_short"]), sh)
    assert nl >= 10 and ns >= 10


# ====================================================================================================== hand paths
# ---------------------------------------------------------------- A.1 DOGE
def _doge_expect(df, combo, tf, side):
    """(state flip bars, event bars) from independent EMAs and a scan of the module's own K / D (scalar crosses, 'le')."""
    M = R.core_module("DOGE")
    p = M.doge_params(tf, **combo)
    c = df["close"].to_numpy(float)
    ef, es = ref_ema(c, p["ema_fast"]), ref_ema(c, p["ema_slow"])
    ind = M.ds.compute_indicators(M._frame(df), p)
    K, D = ind["K"].to_numpy(float), ind["D"].to_numpy(float)
    n = len(c)
    if side == "long":
        st = (ef < es)
        ev = np.array([i > 0 and K[i] < D[i] and K[i - 1] >= D[i - 1] for i in range(n)])
    else:
        st = (ef > es)
        ev = np.array([i > 0 and K[i] > D[i] and K[i - 1] <= D[i - 1] for i in range(n)])
    return st, ev


@pytest.mark.parametrize("side", SIDES)
def test_core_doge_hand_state_leg_flips_after_the_turn(side):
    t = np.arange(71)
    c = np.where(t <= 39, 100.0 + t, 139.0 - 2.0 * (t - 39))                   # up to bar 39, then down 2 per bar
    df = path_frame(c, tf="4h")
    df = df if side == "long" else mirror(df, 300.0)
    r = N.native_arrays("DOGE", df, "4h", SMALL["DOGE"])
    st, ev = _doge_expect(df, SMALL["DOGE"], "4h", side)
    i0 = 35
    assert not st[i0]                                                          # the state leg is false at i0: armed at once
    bs, be = first_true(st, i0), first_true(ev, i0)
    assert 40 < bs <= 43                                                       # the fast EMA (span 2) turns within two bars
    assert comp_first(r, side, 0, i0) == bs and comp_first(r, side, 1, i0) == be
    expected = min(x for x in (bs, be) if x is not None)                       # whichever leg is true first (the K / D cross
    assert expected <= bs                                                      # of the mirror image can come a bar earlier)
    close = df["close"]
    assert first_fire(r, side, i0, close) == expected
    assert first_fire(r, side, 39, close) == expected
    if side == "long":
        assert be is None and expected == bs                                   # a clean ramp-down has no cross: the state leg alone


@pytest.mark.parametrize("side", SIDES)
def test_core_doge_hand_event_leg_alone(side):
    t = np.arange(60)
    c = 100.0 + 1.0 * t + 2.0 * np.sin(2 * np.pi * t / 6.0)                    # a steady rise with a 6-bar wave
    df = path_frame(c, tf="4h")
    df = df if side == "long" else mirror(df, 300.0)                           # the short side sees the mirror image
    r = N.native_arrays("DOGE", df, "4h", SMALL["DOGE"])
    st, ev = _doge_expect(df, SMALL["DOGE"], "4h", side)
    evb = np.flatnonzero(ev)
    assert len(evb) >= 6
    assert np.array_equal(np.flatnonzero(N.as_bool(r["comp_" + side][1][1])), evb)
    assert not st.any()                                                        # the trend legs hold: the state leg is silent
    i0 = int(evb[1]) - 2
    close = df["close"]
    assert first_fire(r, side, i0, close) == evb[1]                           # the first event after i0
    assert first_fire(r, side, int(evb[1]), close) == evb[2]                  # an event on i0 itself is not a check
    assert first_fire(r, side, int(evb[1]) - 1, close) == evb[1]


def test_core_doge_hand_state_true_at_i0_never_armed_by_a_trend_that_never_turns():
    # a short held in a rising market: ef > es (the short's invalidation) is true on every bar, so under C3 it is never armed
    # and never fires; the K / D event (no arm needed) is the only way out
    t = np.arange(60)
    c = 100.0 + 1.0 * t + 2.0 * np.sin(2 * np.pi * t / 6.0)
    df = path_frame(c, tf="4h")
    r = N.native_arrays("DOGE", df, "4h", SMALL["DOGE"])
    st, ev = _doge_expect(df, SMALL["DOGE"], "4h", "short")
    assert st[1:].all() and np.array_equal(N.as_bool(r["comp_short"][0][1])[1:], st[1:])
    i0 = 20
    assert not any(walk(-1, [r["comp_short"][0]], np.nan, df["close"].to_numpy(float), i0))
    evb = np.flatnonzero(ev)
    assert first_fire(r, "short", i0, df["close"]) == first_true(ev, i0) and first_true(ev, i0) is not None
    assert len(evb) >= 6


# ---------------------------------------------------------------- A.2 N03_ADX_GC
def _n03_path():
    t = np.arange(75)
    c = np.where(t <= 29, 100.0 + t,
        np.where(t <= 37, 129.0 - 4.0 * (t - 29),
        np.where(t <= 47, 97.0 + 4.0 * (t - 37), 137.0 - 4.0 * (t - 47))))
    return c


@pytest.mark.parametrize("side", SIDES)
def test_core_n03_hand_ema_whipsaw_waits_for_a_false_close(side):
    combo = dict(SMALL["N03_ADX_GC"], adx_level=0.001)                         # the ADX leg is silent: ADX is never below 0.001
    c = _n03_path()
    df = path_frame(c)
    df = df if side == "long" else mirror(df, 300.0)
    cl = df["close"].to_numpy(float)
    ef, es = ref_ema(cl, 3, 3), ref_ema(cl, 8, 8)
    r = N.native_arrays("N03_ADX_GC", df, "1h", combo)
    bad = (ef < es) if side == "long" else (ef > es)                          # the EMA leg's own truth value (golden cross undone)
    i0 = int(np.flatnonzero(bad)[0]) + 3                                       # inside the first whipsaw dip
    assert bad[i0] and bad[i0 + 1]                                             # true at i0 and at the first check
    good = first_true(~bad & np.isfinite(ef) & np.isfinite(es), i0)           # the recovery: the false close that arms the leg
    b2 = first_true(bad, good)                                                 # the second undoing
    assert 37 < good <= 44 and 47 < b2 <= 52
    assert np.array_equal(N.as_bool(r["comp_" + side][0][1]), bad & np.isfinite(ef) & np.isfinite(es))
    assert not N.as_bool(r["comp_" + side][1][1]).any()                        # ADX leg silent
    # without arming the leg would fire at the very first check; under C3 it fires at the second undoing
    assert first_fire(r, side, i0, df["close"]) == b2
    assert comp_first(r, side, 0, i0) == i0 + 1


@pytest.mark.parametrize("side", SIDES)
def test_core_n03_hand_adx_leg_alone(side):
    combo = dict(SMALL["N03_ADX_GC"], adx_level=60.0)
    t = np.arange(70)
    # a clean ramp (ADX at 100) up to bar 34, then a wobbling plateau with an upward drift: the fast EMA stays above the slow
    # one while ADX falls under the level
    steps = [+2.0, -1.0, +1.5, -1.5, +2.5, -1.0, +1.0, -2.0]
    st = np.array([steps[(i - 35) % len(steps)] for i in range(70)])
    c = 100.0 + 2.0 * np.minimum(t, 34) + np.cumsum(np.where(t > 34, st, 0.0))
    df = path_frame(c)
    df = df if side == "long" else mirror(df, 400.0)
    r = N.native_arrays("N03_ADX_GC", df, "1h", combo)
    M = R.core_module("N03_ADX_GC")
    _a, _b, adx = M.fg.dmi_adx(df, 3, 3)
    adx = np.asarray(adx, float)
    cl = df["close"].to_numpy(float)
    ef, es = ref_ema(cl, 3, 3), ref_ema(cl, 8, 8)
    i0 = 33
    assert adx[i0] >= 60.0                                                     # the entry needs ADX >= level: leg armed at once
    b = first_true(adx < 60.0, i0)
    assert b is not None and 35 < b < 50
    trend_ok = (ef > es) if side == "long" else (ef < es)
    assert trend_ok[i0:].all()                                                 # the EMA leg never fires on this path
    assert comp_first(r, side, 1, i0) == b and first_fire(r, side, i0, df["close"]) == b
    assert not N.as_bool(r["comp_" + side][0][1])[i0:].any()


# ---------------------------------------------------------------- A.3 N09_ALLIG_AROON
def _n09_state(df, combo, side):
    cl, h, l = (df[k].to_numpy(float) for k in ("close", "high", "low"))
    lips, teeth, jaw = ref_sma(cl, combo["lips_len"]), ref_sma(cl, combo["teeth_len"]), ref_sma(cl, combo["jaw_len"])
    up, dn = ref_aroon(h, l, combo["aroon_len"])
    fin = np.isfinite(lips) & np.isfinite(teeth) & np.isfinite(jaw) & np.isfinite(up) & np.isfinite(dn)
    if side == "long":
        ok = (lips > teeth) & (lips > jaw) & (up >= dn)
    else:
        ok = (lips < teeth) & (lips < jaw) & (dn >= up)
    return fin & ~ok, lips, teeth, jaw, up, dn


@pytest.mark.parametrize("side", SIDES)
def test_core_n09_hand_alligator_mouth_closes_after_the_turn(side):
    t = np.arange(60)
    c = np.where(t <= 29, 100.0 + t, 129.0 - 2.0 * (t - 29))
    df = path_frame(c)
    df = df if side == "long" else mirror(df, 300.0)
    r = N.native_arrays("N09_ALLIG_AROON", df, "1h", SMALL["N09_ALLIG_AROON"])
    bad, lips, teeth, jaw, up, dn = _n09_state(df, SMALL["N09_ALLIG_AROON"], side)
    i0 = 25
    assert not bad[i0] and np.isfinite(lips[i0])                               # long_state holds at i0: armed at once
    b = first_true(bad, i0)
    assert 29 < b <= 33                                                        # within a few bars of the turn at bar 30
    assert np.array_equal(N.as_bool(r["comp_" + side][0][1]), bad)
    assert first_fire(r, side, i0, df["close"]) == b


@pytest.mark.parametrize("side", SIDES)
def test_core_n09_hand_aroon_leg_alone(side):
    b = 28
    t = np.arange(40)
    c = 100.0 + t
    upper, lower = np.full(40, 0.3), np.full(40, 0.3)
    upper[b - 3] = 50.0                                                        # a high spike 3 bars before b
    lower[b] = 50.0                                                            # a low spike on bar b
    df = path_frame(c, upper=upper, lower=lower)
    df = df if side == "long" else mirror(df, 300.0)
    r = N.native_arrays("N09_ALLIG_AROON", df, "1h", SMALL["N09_ALLIG_AROON"])
    bad, lips, teeth, jaw, up, dn = _n09_state(df, SMALL["N09_ALLIG_AROON"], side)
    if side == "long":
        assert lips[b] > teeth[b] and lips[b] > jaw[b]                          # the averages are still in order at b
        assert dn[b] > up[b] and up[b - 1] >= dn[b - 1]                         # Aroon alone turns at b
    else:
        assert lips[b] < teeth[b] and lips[b] < jaw[b]
        assert up[b] > dn[b] and dn[b - 1] >= up[b - 1]
    i0 = 20
    assert first_true(bad, i0) == b
    assert first_fire(r, side, i0, df["close"]) == b


# ---------------------------------------------------------------- A.4 N10_HA_PSAR
def _n10_rise(n0=30):
    c = 100.0 + 2.0 * np.arange(n0)
    o = np.r_[c[0], c[:-1]]
    return o, c + 0.2, o - 8.0, c


@pytest.mark.parametrize("side", SIDES)
def test_core_n10_hand_candle_leg_alone(side):
    o, h, l, c = _n10_rise()
    P = c[-1]
    # bar 30: a gap down 5 below the last close, no upper wick (the high is the open), and three lower; its low is above
    # the last two lows, so PSAR cannot flip on it (SAR <= min(low[i-1], low[i-2]) and a flip needs low[i] < SAR)
    o, h, l, c = (np.r_[x, v] for x, v in ((o, P - 5), (h, P - 5), (l, P - 8), (c, P - 8)))
    assert l[30] >= min(l[28], l[29])
    df = frame_ohlc(o, h, l, c, tf="4h")
    df = df if side == "long" else mirror(df, 300.0)               # the short side sees the mirror image of the same path
    combo = SMALL["N10_HA_PSAR"]
    r = N.native_arrays("N10_HA_PSAR", df, "4h", combo)
    ho, hc, hh, hl = ref_ha(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    tol = np.abs(hh - hl) * combo["wick_tol"]
    if side == "long":
        strong = (hc < ho) & (np.abs(hh - np.maximum(ho, hc)) <= tol)        # red, no upper wick
    else:
        strong = (hc > ho) & (np.abs(np.minimum(ho, hc) - hl) <= tol)        # green, no lower wick
    assert np.flatnonzero(strong).tolist() == [30]                             # a clean rise has green HA candles: only bar 30
    assert not N.as_bool(r["comp_" + side][0][1]).any()                        # the PSAR leg never fires
    assert np.array_equal(N.as_bool(r["comp_" + side][1][1]), strong)
    assert first_fire(r, side, 25, df["close"]) == 30


def test_core_n10_hand_candle_leg_true_at_i0_waits_under_c3():
    # the candle leg is true at i0 (bar 30) and again at bar 31 (a second strong red HA candle): not armed, so bar 31 must not
    # fire. Bars 32 and 33 bounce (no strong red candle): the leg is false there and arms. Bar 34 is a strong red candle again
    # and fires. Every low is above the two before it, so PSAR never flips (that leg stays silent).
    o, h, l, c = _n10_rise()
    P = c[-1]
    rows = [(P - 5, P - 5, P - 8, P - 8),            # 30: gap down, no upper wick
            (P - 6, P - 6, P - 8.5, P - 8.5),        # 31: again
            (P - 8, P - 4, P - 8.2, P - 4),          # 32: bounce
            (P - 4, P - 1, P - 4.2, P - 1),          # 33: bounce
            (P - 4.6, P - 4.6, P - 7.8, P - 7.8)]    # 34: gap down below the HA open, no upper wick
    for x in rows:
        o, h, l, c = (np.r_[a, v] for a, v in zip((o, h, l, c), x))
    df = frame_ohlc(o, h, l, c, tf="4h")
    r = N.native_arrays("N10_HA_PSAR", df, "4h", SMALL["N10_HA_PSAR"])
    ho, hc, hh, hl = ref_ha(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    tol = np.abs(hh - hl) * 0.02
    strong = (hc < ho) & (np.abs(hh - np.maximum(ho, hc)) <= tol)
    assert np.flatnonzero(strong).tolist() == [30, 31, 34]
    assert np.array_equal(N.as_bool(r["comp_long"][1][1]), strong)
    assert not N.as_bool(r["comp_long"][0][1]).any()                           # PSAR never flips on this path
    close = df["close"]
    # i0 = 30: true at i0 -> unarmed; bar 31 does not fire; bar 32 (false) arms; bar 34 fires
    assert comp_first(r, "long", 1, 30) == 31
    assert first_fire(r, "long", 30, close) == 34
    # i0 = 29 (candle leg false at i0): armed at once, fires at the first strong candle, bar 30
    assert first_fire(r, "long", 29, close) == 30
    # i0 = 31: true at i0, bar 32 arms, bar 34 fires
    assert first_fire(r, "long", 31, close) == 34


@pytest.mark.parametrize("side", SIDES)
def test_core_n10_hand_psar_flip_leg(side):
    o, h, l, c = _n10_rise()
    P = c[-1]
    o, h, l, c = (np.r_[x, v] for x, v in ((o, P), (h, P), (l, P - 40.0), (c, P - 40.0)))     # bar 30: a crash through the SAR
    df = frame_ohlc(o, h, l, c, tf="4h")
    df = df if side == "long" else mirror(df, 300.0)
    r = N.native_arrays("N10_HA_PSAR", df, "4h", SMALL["N10_HA_PSAR"])
    pl = N.as_bool(r["comp_" + side][0][1])
    assert np.flatnonzero(pl).tolist() == [30]                                 # direction against the position on the crash bar only
    assert np.isnan(r["comp_" + side][0][1][0]) and np.isfinite(r["comp_" + side][0][1][1:]).all()      # bar 0 has no direction: unknown
    assert first_fire(r, side, 25, df["close"]) == 30
    # the same frame seen by the other side (a position against the trend): its PSAR leg is true on bars 1..29 and false on the crash bar
    other = "short" if side == "long" else "long"
    po = N.as_bool(r["comp_" + other][0][1])
    assert po[1:30].all() and not po[30]
    assert not any(walk(SIDE_SIGN[other], [r["comp_" + other][0]], np.nan, df["close"].to_numpy(float), 25))     # true at i0: never armed


# ---------------------------------------------------------------- A.5 N13_3OUTSIDE
N13_ROWS = [
    (110, 110.3, 107.7, 108), (108, 108.3, 105.7, 106), (106, 106.3, 103.7, 104), (104, 104.3, 101.7, 102),
    (102, 102.3, 99.7, 100),                                                   # 0-4: the prior decline
    (100, 100.2, 97.8, 98), (97.5, 101.2, 97.3, 101), (101, 103.2, 100.8, 103),   # 5-7: Three Outside Up (j = 7)
    (103, 104.6, 102.9, 104.5),                                                # 8: first close above PH = 103.2 (lag 1)
    (104.5, 106.7, 104.3, 106.5), (106.5, 108.7, 106.3, 108.5), (108.5, 110.7, 108.3, 110.5),       # 9-11: the rally
    (110.5, 112.7, 110.3, 112.5), (113, 113.2, 109.8, 110), (110, 110.2, 107.3, 107.5),          # 12-14: Three Outside Down
    (107.5, 107.6, 106.4, 106.5),                                              # 15: first close below PL = 107.3 (lag 1)
]


def _n13_df(rows=N13_ROWS):
    a = np.array(rows, dtype=float)
    return frame_ohlc(a[:, 0], a[:, 1], a[:, 2], a[:, 3])


def test_core_n13_hand_pattern_levels_and_targets():
    df = _n13_df()
    M = R.core_module("N13_3OUTSIDE")
    lo, sh = M.signals(df, "1h", **SMALL["N13_3OUTSIDE"])
    assert np.flatnonzero(lo).tolist() == [8] and np.flatnonzero(sh).tolist() == [15]
    r = N.native_arrays("N13_3OUTSIDE", df, "1h", SMALL["N13_3OUTSIDE"])
    # long signal at 8: pattern bars 5-7, PH = 103.2, PL = 97.3 -> level PL, target PH + (PH - PL)
    assert np.flatnonzero(np.isfinite(r["lvl_long"])).tolist() == [8] and np.flatnonzero(np.isfinite(r["tgt_long"])).tolist() == [8]
    assert r["lvl_long"][8] == 97.3 and r["tgt_long"][8] == pytest.approx(103.2 + (103.2 - 97.3))
    # short signal at 15: pattern bars 12-14, PH = 113.2, PL = 107.3 -> level PH, target PL - (PH - PL)
    assert np.flatnonzero(np.isfinite(r["lvl_short"])).tolist() == [15]
    assert r["lvl_short"][15] == 113.2 and r["tgt_short"][15] == pytest.approx(107.3 - (113.2 - 107.3))


def test_core_n13_hand_long_fires_on_the_opposite_pattern_before_the_level():
    df = _n13_df()
    r = N.native_arrays("N13_3OUTSIDE", df, "1h", SMALL["N13_3OUTSIDE"])
    close = df["close"].to_numpy(float)
    assert (close[9:15] > 97.3).all()                                          # no close under PL: the level leg is silent
    assert first_fire(r, "long", 8, close) == 15                               # the own short signal at bar 15 (event)
    assert first_fire(r, "long", 8, close, groups=[[9, 10], [11, 12], [13, 14, 15]]) == 2     # a merged check with bar 15 fires
    assert first_fire(r, "long", 8, close, groups=[[9, 10, 11, 12, 13, 14], [15]]) == 1
    # the level moves nothing: it is a number fixed at the signal bar
    assert r["lvl_long"][8] == 97.3 and np.isnan(r["lvl_long"][9:]).all()


def test_core_n13_hand_long_level_leg_and_its_arm():
    rows = list(N13_ROWS[:9]) + [(104.5, 106.7, 104.3, 106.5), (106.5, 106.6, 98.0, 99.0), (99.0, 99.1, 96.9, 97.0),
                                 (97.0, 98.0, 96.0, 98.0)]
    df = _n13_df(rows)
    r = N.native_arrays("N13_3OUTSIDE", df, "1h", SMALL["N13_3OUTSIDE"])
    close = df["close"].to_numpy(float)
    assert r["lvl_long"][8] == 97.3
    assert first_fire(r, "long", 8, close) == 11                               # close 97.0 < 97.3 (99.0 > 97.3 does not fire)
    # lag-2 breakout: bar 8 stays inside PH, bar 9 is the first close above it
    rows2 = list(N13_ROWS[:8]) + [(103, 103.15, 102.9, 103.1), (103.1, 104.6, 103.0, 104.5)]
    df2 = _n13_df(rows2)
    lo, sh = R.core_module("N13_3OUTSIDE").signals(df2, "1h", **SMALL["N13_3OUTSIDE"])
    assert np.flatnonzero(lo).tolist() == [9]
    r2 = N.native_arrays("N13_3OUTSIDE", df2, "1h", SMALL["N13_3OUTSIDE"])
    assert r2["lvl_long"][9] == 97.3 and r2["tgt_long"][9] == pytest.approx(109.1)   # PH, PL of the pattern 2 bars back


def test_core_n13_hand_mirror_image_is_the_short_side():
    df = _n13_df()
    K = 200.0
    dm = mirror(df, K)
    r, rm = N.native_arrays("N13_3OUTSIDE", df, "1h", SMALL["N13_3OUTSIDE"]), N.native_arrays("N13_3OUTSIDE", dm, "1h", SMALL["N13_3OUTSIDE"])
    # the mirror image of Three Outside Up (bar 8) is Three Outside Down: a short signal at bar 8; the mirror of the
    # Down pattern (bar 15) is an Up pattern: a long signal at bar 15
    assert np.flatnonzero(np.isfinite(rm["lvl_short"])).tolist() == [8] and np.flatnonzero(np.isfinite(rm["lvl_long"])).tolist() == [15]
    assert rm["lvl_short"][8] == pytest.approx(K - r["lvl_long"][8]) and rm["tgt_short"][8] == pytest.approx(K - r["tgt_long"][8])
    assert rm["lvl_long"][15] == pytest.approx(K - r["lvl_short"][15]) and rm["tgt_long"][15] == pytest.approx(K - r["tgt_short"][15])
    close = dm["close"].to_numpy(float)
    assert first_fire(rm, "short", 8, close) == 15                              # the own long signal (event)
    assert (close[9:15] < rm["lvl_short"][8]).all()                             # the level leg (close above PH) stays silent


def test_core_n13_hand_short_target_at_or_below_zero_is_none():
    # a rise (bars 0-4), then Three Outside Down with a tall pattern (PH = 2.2, PL = 1.0), then the break below PL
    rows = [(0.5, 0.52, 0.48, 0.5), (0.6, 0.62, 0.58, 0.6), (0.7, 0.72, 0.68, 0.7), (0.8, 0.82, 0.78, 0.8), (0.9, 0.92, 0.88, 0.9),
            (1.2, 2.1, 1.15, 2.0),                       # j-2: tall bullish bar
            (2.1, 2.2, 1.05, 1.1),                       # j-1: bearish, opens at or above the last close, closes at or below the first open
            (1.1, 1.12, 1.0, 1.02),                      # j: bearish, closes below the previous close
            (1.02, 1.03, 0.9, 0.95)]                     # j + 1: first close below PL = 1.0
    df = _n13_df(rows)
    combo = {"engulf_min": 0.1, "prior_n": 2, "atr_len": 3}
    lo, sh = R.core_module("N13_3OUTSIDE").signals(df, "1h", **combo)
    assert np.flatnonzero(sh).tolist() == [8] and not lo.any()
    r = N.native_arrays("N13_3OUTSIDE", df, "1h", combo)
    assert r["lvl_short"][8] == 2.2                                            # PH
    assert 1.0 - (2.2 - 1.0) < 0 and np.isnan(r["tgt_short"][8])               # PL - (PH - PL) < 0: no target
    assert np.isnan(r["tgt_short"]).all() and not target_in_use(r["tgt_short"][8], 0.95, -1)


def test_core_n13_hand_target_behind_the_fill_is_none_c6():
    # the breakout bar is longer than the pattern is tall: the close (110) is already above PH + (PH - PL) = 109.1
    rows = list(N13_ROWS[:8]) + [(103, 110.2, 102.9, 110.0)]
    df = _n13_df(rows)
    lo, _sh = R.core_module("N13_3OUTSIDE").signals(df, "1h", **SMALL["N13_3OUTSIDE"])
    assert np.flatnonzero(lo).tolist() == [8]
    r = N.native_arrays("N13_3OUTSIDE", df, "1h", SMALL["N13_3OUTSIDE"])
    assert r["tgt_long"][8] == pytest.approx(109.1) and r["lvl_long"][8] == 97.3     # the arrays hold the number ...
    assert not target_in_use(r["tgt_long"][8], 110.0, +1)                            # ... C6 (the kernel's TP_STRUCT rule) drops it
    # in the normal case (bar 8 closes at 104.5) the target is beyond the fill and is used
    r0 = N.native_arrays("N13_3OUTSIDE", _n13_df(), "1h", SMALL["N13_3OUTSIDE"])
    assert target_in_use(r0["tgt_long"][8], 104.5, +1)


def test_core_target_rule_c6():
    assert target_in_use(110.0, 100.0, +1) and not target_in_use(100.0, 100.0, +1) and not target_in_use(99.0, 100.0, +1)
    assert target_in_use(90.0, 100.0, -1) and not target_in_use(100.0, 100.0, -1) and not target_in_use(110.0, 100.0, -1)
    assert not target_in_use(np.nan, 100.0, +1) and not target_in_use(np.nan, 100.0, -1)


def test_core_n13_hand_nan_in_the_pattern_gives_no_level_and_no_target_c7():
    # a NaN low inside the pattern makes PL unknown: the breakout (it needs PH only) is still the module's signal, but the
    # level and the target are none; the opposite-pattern event still works
    rows = [list(x) for x in N13_ROWS]
    rows[6][2] = np.nan                                                        # bar 6 (j - 1): low unknown
    df = _n13_df(rows)
    lo, sh = R.core_module("N13_3OUTSIDE").signals(df, "1h", **SMALL["N13_3OUTSIDE"])
    assert np.flatnonzero(lo).tolist() == [8]
    r = N.native_arrays("N13_3OUTSIDE", df, "1h", SMALL["N13_3OUTSIDE"])
    assert np.isnan(r["lvl_long"]).all() and np.isnan(r["tgt_long"]).all()
    assert np.flatnonzero(sh).tolist() == [15]
    assert first_fire(r, "long", 8, df["close"].to_numpy(float)) == 15         # no level: only the own short signal can end the long


# ---------------------------------------------------------------- A.6 N19_FIB_CHOP
def _n19_ramp(fib, extra=()):
    """A +1 per bar ramp of 50 bars, then a hammer at bar 50 (a deep lower wick, closes up): the pullback buy of the entry."""
    c = 100.0 + np.arange(50.0)
    o = np.r_[c[0], c[:-1]]
    h, l = c + 0.3, o - 0.3
    rows = [(o[i], h[i], l[i], c[i]) for i in range(50)]
    rows.append((149.0, 150.8, 142.0, 150.5))                                  # bar 50
    rows.extend(extra)
    a = np.array(rows, dtype=float)
    return frame_ohlc(a[:, 0], a[:, 1], a[:, 2], a[:, 3], tf="30m"), dict(SMALL["N19_FIB_CHOP"], fib_level=fib)


@pytest.mark.parametrize("fib", [0.5, 0.25])
def test_core_n19_hand_hammer_levels_and_targets(fib):
    df, combo = _n19_ramp(fib)
    M = R.core_module("N19_FIB_CHOP")
    lo, sh = M.signals(df, "30m", **combo)
    assert np.flatnonzero(lo).tolist() == [50] and not sh.any()
    r = N.native_arrays("N19_FIB_CHOP", df, "30m", combo)
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    hh, ll = h[42:48].max(), l[42:48].min()                                    # 6 bars ending 3 bars before bar 50
    assert (hh, ll) == (pytest.approx(147.3), pytest.approx(140.7))
    assert r["lvl_long"][50] == pytest.approx(hh - fib * (hh - ll)) and r["tgt_long"][50] == hh
    assert np.flatnonzero(np.isfinite(r["lvl_long"])).tolist() == [50] and np.flatnonzero(np.isfinite(r["tgt_long"])).tolist() == [50]
    assert r["lvl_long"][50] < df["close"].iloc[50] < 150.8                     # armed at once
    assert not target_in_use(r["tgt_long"][50], df["close"].iloc[50], +1)      # hh = 147.3 is behind the fill: no target (C6)
    assert not np.isfinite(r["lvl_short"]).any() and not np.isfinite(r["tgt_short"]).any()


@pytest.mark.parametrize("fib", [0.5, 0.25])
def test_core_n19_hand_mirror_image_is_the_short_side(fib):
    df, combo = _n19_ramp(fib)
    K = 300.0
    dm = mirror(df, K)
    r, rm = N.native_arrays("N19_FIB_CHOP", df, "30m", combo), N.native_arrays("N19_FIB_CHOP", dm, "30m", combo)
    assert np.flatnonzero(np.isfinite(rm["lvl_short"])).tolist() == [50]
    assert rm["lvl_short"][50] == pytest.approx(K - r["lvl_long"][50]) and rm["tgt_short"][50] == pytest.approx(K - r["tgt_long"][50])
    assert rm["lvl_short"][50] > dm["close"].iloc[50]


@pytest.mark.parametrize("side", SIDES)
def test_core_n19_hand_level_leg_fires_on_the_first_close_beyond_the_line(side):
    fib = 0.5
    extra = [(150.5, 151.9, 150.4, 151.5), (151.5, 152.9, 151.4, 152.5), (152.5, 153.9, 152.4, 153.5),
             (153.5, 153.6, 144.2, 144.5),            # 54: closes at 144.5, above the line 144.0: no fire
             (144.5, 144.6, 143.0, 143.9)]            # 55: closes at 143.9, below 144.0: fires
    df, combo = _n19_ramp(fib, extra)
    df = df if side == "long" else mirror(df, 300.0)
    r = N.native_arrays("N19_FIB_CHOP", df, "30m", combo)
    lvl = r["lvl_" + side][50]
    assert lvl == pytest.approx(144.0 if side == "long" else 300.0 - 144.0)
    close = df["close"].to_numpy(float)
    # the slope leg is silent here (the EMA is still rising), so the level leg decides
    assert not N.as_bool(r["comp_" + side][0][1])[51:].any()
    assert first_fire(r, side, 50, close) == 55
    # C5: the level is fixed at i0 -- bars after it change nothing; a different continuation leaves the arrays at <= 50 as they are
    extra2 = [(150.5, 150.6, 100.0, 101.0)]
    df2, _ = _n19_ramp(fib, extra2)
    df2 = df2 if side == "long" else mirror(df2, 300.0)
    r2 = N.native_arrays("N19_FIB_CHOP", df2, "30m", combo)
    assert r2["lvl_" + side][50] == lvl and r2["tgt_" + side][50] == r["tgt_" + side][50]
    assert first_fire(r2, side, 50, df2["close"].to_numpy(float)) == 51


@pytest.mark.parametrize("side", SIDES)
def test_core_n19_hand_slope_leg_after_the_trend_turns(side):
    t = np.arange(110)
    c = np.where(t <= 59, 100.0 + t, 159.0 - 2.0 * (t - 59))
    df = path_frame(c, tf="30m")
    df = df if side == "long" else mirror(df, 300.0)
    combo = SMALL["N19_FIB_CHOP"]
    r = N.native_arrays("N19_FIB_CHOP", df, "30m", combo)
    o, h, l, cl = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    base = ref_ema(cl, 34, 34)
    atr = ref_atr(h, l, cl, 14)
    slope = np.full(len(cl), np.nan)
    for i in range(3, len(cl)):
        slope[i] = (base[i] - base[i - 3]) / atr[i]
    thr = combo["slope_thr"]
    bad = (slope <= -thr) if side == "long" else (slope >= thr)
    i0 = 55
    assert (slope[i0] >= thr) if side == "long" else (slope[i0] <= -thr)       # the entry's own zone: the leg is false at i0
    b = first_true(bad, i0)
    assert b is not None and 60 < b < 100
    assert np.array_equal(N.as_bool(r["comp_" + side][0][1]), bad & np.isfinite(slope))
    assert first_fire(r, side, i0, df["close"], lvl0=np.nan) == b
    assert [k for k, _ in r["comp_" + side]] == ["state"]


# ---------------------------------------------------------------- A.7 OBV_S
@pytest.mark.parametrize("side", SIDES)
def test_core_obv_hand_flip_below_its_average(side):
    t = np.arange(45)
    c = np.where(t <= 24, 100.0 + t, 124.0 - (t - 24))
    vol = np.where(t <= 24, 10.0, 40.0)
    df = path_frame(c, v=vol)
    df = df if side == "long" else mirror(df, 300.0)
    r = N.native_arrays("OBV_S", df, "1h", SMALL["OBV_S"])
    o = ref_obv(df["close"].to_numpy(float), vol)
    ma = ref_sma(o, 5)
    bad = (o < ma) if side == "long" else (o > ma)
    i0 = 20
    assert not bad[i0]                                                         # OBV above its average at i0: armed at once
    b = first_true(bad, i0)
    assert b == 25                                                             # the first falling bar adds -40 to a +10 climb
    assert np.array_equal(N.as_bool(r["comp_" + side][0][1]), bad & np.isfinite(ma))
    assert first_fire(r, side, i0, df["close"]) == b
    # OBV == its average does not fire (strict): flat volume-less bars keep OBV constant, the average catches up exactly
    flat = path_frame(np.full(20, 100.0) + np.where(np.arange(20) == 0, 0.0, 0.0), v=np.full(20, 5.0))
    rf = N.native_arrays("OBV_S", flat, "1h", SMALL["OBV_S"])
    assert not N.as_bool(rf["comp_long"][0][1]).any() and not N.as_bool(rf["comp_short"][0][1]).any()


# ---------------------------------------------------------------- A.8 S4_BB_BBP
def _s4_refs(df, combo):
    c = df["close"].to_numpy(float)
    mid = ref_sma(c, combo["bb_len"])
    bbp = df["high"].to_numpy(float) + df["low"].to_numpy(float) - 2.0 * ref_ema(c, 13, 13)
    return c, mid, bbp


@pytest.mark.parametrize("side", SIDES)
def test_core_s4_hand_both_legs_after_the_turn(side):
    t = np.arange(60)
    c = np.where(t <= 29, 100.0 + t, 129.0 - 3.0 * (t - 29))
    df = path_frame(c)
    df = df if side == "long" else mirror(df, 300.0)
    combo = SMALL["S4_BB_BBP"]
    r = N.native_arrays("S4_BB_BBP", df, "1h", combo)
    cl, mid, bbp = _s4_refs(df, combo)
    if side == "long":
        leg1, leg2 = cl < mid, bbp < 0
    else:
        leg1, leg2 = cl > mid, bbp > 0
    i0 = 25
    assert not leg1[i0] and not leg2[i0]                                       # both legs false at i0: armed at once
    b1, b2 = first_true(leg1, i0), first_true(leg2, i0)
    assert b1 == 30 and b1 < b2                                                # the mean-line leg first, the power leg later
    assert comp_first(r, side, 0, i0) == b1 and comp_first(r, side, 1, i0) == b2
    assert first_fire(r, side, i0, df["close"]) == b1
    assert [k for k, _ in r["comp_" + side]] == ["state", "state"]


@pytest.mark.parametrize("side", SIDES)
def test_core_s4_hand_power_leg_alone(side):
    b = 32
    c = 100.0 + np.arange(45.0)
    lower = np.full(45, 0.3)
    lower[b] = 100.0                                                           # a deep lower wick: the bar's midpoint falls under EMA13
    df = path_frame(c, lower=lower)
    df = df if side == "long" else mirror(df, 300.0)
    combo = SMALL["S4_BB_BBP"]
    r = N.native_arrays("S4_BB_BBP", df, "1h", combo)
    cl, mid, bbp = _s4_refs(df, combo)
    if side == "long":
        assert cl[b] > mid[b] and bbp[b] < 0 and (bbp[20:b] > 0).all()
    else:
        assert cl[b] < mid[b] and bbp[b] > 0 and (bbp[20:b] < 0).all()
    assert first_fire(r, side, 25, df["close"]) == b
    assert comp_first(r, side, 1, 25) == b and comp_first(r, side, 0, 25) is None      # the mean-line leg never fires


@pytest.mark.parametrize("side", SIDES)
def test_core_s4_hand_mean_leg_alone(side):
    b = 32
    c = 100.0 + np.arange(45.0)
    c[b:] = c[b - 1] - 6.0 + np.arange(45 - b) * 1.0                           # bar b closes 6 under the last close, then climbs again
    upper = np.full(45, 0.3)
    upper[b] = 100.0                                                           # a huge upper wick keeps the midpoint above EMA13
    df = path_frame(c, upper=upper)
    df = df if side == "long" else mirror(df, 300.0)
    combo = SMALL["S4_BB_BBP"]
    r = N.native_arrays("S4_BB_BBP", df, "1h", combo)
    cl, mid, bbp = _s4_refs(df, combo)
    if side == "long":
        assert cl[b] < mid[b] and bbp[b] > 0
    else:
        assert cl[b] > mid[b] and bbp[b] < 0
    assert first_fire(r, side, 25, df["close"]) == b
    assert comp_first(r, side, 0, 25) == b


def test_core_s4_hand_merged_checks_and_nan_unknown():
    # merged checks (C4) with the two legs on a built path: leg 1 true at bar 30, leg 2 true from bar 33 on
    t = np.arange(60)
    c = np.where(t <= 29, 100.0 + t, 129.0 - 3.0 * (t - 29))
    df = path_frame(c)
    r = N.native_arrays("S4_BB_BBP", df, "1h", SMALL["S4_BB_BBP"])
    close = df["close"].to_numpy(float)
    assert first_fire(r, "long", 25, close, groups=[[26, 27], [28, 29, 30], [31, 32]]) == 1
    assert first_fire(r, "long", 25, close, groups=[[26, 27, 28, 29], [30, 31]]) == 1
    # NaN (C7): a NaN close makes the mean-line leg unknown for the 5 windows holding it, the power leg stays known
    bnan = 36
    dfn = path_frame(c)
    dfn.loc[bnan, "close"] = np.nan
    rn = N.native_arrays("S4_BB_BBP", dfn, "1h", SMALL["S4_BB_BBP"])
    leg1 = rn["comp_long"][0][1]
    assert np.isnan(leg1[bnan:bnan + 5]).all() and np.isfinite(leg1[bnan + 5:]).all() and np.isfinite(leg1[bnan - 1])
    assert np.isfinite(rn["comp_long"][1][1][bnan + 1:]).all()
    # i0 = 32: leg 1 is true at 32..35 (falling path) so it is not armed; the NaN window must not arm it -> it never fires,
    # which is what a bool False at the NaN bars (an arm) would get wrong
    walked = walk(1, [rn["comp_long"][0]], np.nan, dfn["close"].to_numpy(float), 32)
    assert not any(walked)
    as_bools = [("state", N.as_bool(rn["comp_long"][0][1]).astype(float))]
    assert any(walk(1, as_bools, np.nan, dfn["close"].to_numpy(float), 32))


# ====================================================================================================== hygiene
@pytest.mark.parametrize("name", NAMES)
def test_core_input_untouched_repeatable_and_index_free(name):
    tf = "30m"
    combo = LOOSE.get(name, SMALL[name])
    df = rand_frame(7, 500, tf, sigma=0.012)
    before = df.copy()
    a = arrays_of(N.native_arrays(name, df, tf, combo))
    pd.testing.assert_frame_equal(df, before)                                  # the frame is not modified
    R.M.clear()                                                                # the indicator memo is only a cache
    b = arrays_of(N.native_arrays(name, df, tf, combo))
    assert all(same(a[k], b[k]) for k in a)
    c = arrays_of(N.native_arrays(name, df, tf, combo))
    assert all(same(a[k], c[k]) for k in a)
    # a frame cut out of a longer one keeps its old index labels: the arrays are positional and do not depend on them
    sl = df.iloc[120:].copy()
    d1 = arrays_of(N.native_arrays(name, sl, tf, combo))
    d2 = arrays_of(N.native_arrays(name, sl.reset_index(drop=True), tf, combo))
    assert all(same(d1[k], d2[k]) for k in d1)


# ====================================================================================================== causality
def _equal_prefix(a: dict, b: dict, i: int) -> list:
    return [k for k in a if not same(a[k][:i + 1], b[k][:i + 1])]


CAUSAL_COMBOS = {name: [(f"pick{k}", tf, combo) for k, (pid, nm, tf, combo) in enumerate(PICKS) if nm == name]
                 for name in NAMES}
for _nm in ("N13_3OUTSIDE", "N19_FIB_CHOP"):
    CAUSAL_COMBOS[_nm].append(("loose", "30m", LOOSE[_nm]))
for _nm in NAMES:
    CAUSAL_COMBOS[_nm].append(("small", "4h", SMALL[_nm]))
    CAUSAL_COMBOS[_nm].append(("default", "1h", R.default_combo("core", _nm)))


@pytest.mark.parametrize("name", NAMES)
def test_core_causality_changing_later_bars_changes_nothing_before(name):
    """T5-style: for random frames, replace every bar after i by another path; components, levels and targets at <= i are
    identical (every strategy, both sides, all pick combos). The perturbation must change something after i."""
    n_signal_bars = n_changed = n_cases = 0
    for label, tf, combo in CAUSAL_COMBOS[name]:
        for seed in (61, 62):
            df = rand_frame(seed, 420, tf, sigma=0.012)
            base = arrays_of(N.native_arrays(name, df, tf, combo))
            for i in (150, 260, 330):
                other = cont_frame(df, i, seed * 1000 + i)
                got = arrays_of(N.native_arrays(name, other, tf, combo))
                assert _equal_prefix(base, got, i) == [], (name, label, seed, i)
                n_cases += 1
                n_changed += any(not same(base[k][i + 1:], got[k][i + 1:]) for k in base)
                n_signal_bars += int(np.isfinite(base["lvl_long"][:i + 1]).sum() + np.isfinite(base["lvl_short"][:i + 1]).sum())
    assert n_changed >= n_cases // 2                                            # the perturbations really changed the later bars
    if name in ("N13_3OUTSIDE", "N19_FIB_CHOP"):
        assert n_signal_bars >= 5                                              # levels and targets were really compared


@pytest.mark.parametrize("name", NAMES)
def test_core_causality_cutting_the_frame_changes_nothing_before(name):
    """T3-style on synthetic frames: native_arrays on df[:k] equals native_arrays on df at every bar < k."""
    for label, tf, combo in CAUSAL_COMBOS[name]:
        df = rand_frame(71, 420, tf, sigma=0.012)
        full = arrays_of(N.native_arrays(name, df, tf, combo))
        for k in (120, 241, 333):
            cut = arrays_of(N.native_arrays(name, df.iloc[:k].copy(), tf, combo))
            assert [key for key in full if not same(full[key][:k], cut[key])] == [], (name, label, k)


# ====================================================================================================== parity (synthetic)
DOGE_PICKS = [p for p in PICKS if p[1] == "DOGE"]


@pytest.mark.parametrize("pid,name,tf,combo", DOGE_PICKS, ids=[p[0] for p in DOGE_PICKS])
def test_core_doge_components_equal_the_source_exit_on_synthetic_bars(pid, name, tf, combo):
    M = R.core_module("DOGE")
    for seed in (81, 82, 83):
        df = rand_frame(seed, 2500, tf, sigma=0.01)
        r = N.native_arrays("DOGE", df, tf, combo)
        p = M.doge_params(tf, **combo)
        d = M._frame(df)
        ind = M.ds.compute_indicators(d, p)
        sig = M.ds.compute_signals(d, ind, p)
        lx = N.as_bool(r["comp_long"][0][1]) | N.as_bool(r["comp_long"][1][1])
        sx = N.as_bool(r["comp_short"][0][1]) | N.as_bool(r["comp_short"][1][1])
        assert np.array_equal(lx, sig["long_exit"].to_numpy(bool)) and np.array_equal(sx, sig["short_exit"].to_numpy(bool))
        assert lx.sum() > 0 and sx.sum() > 0
        # the components themselves, by name: ema_fast < ema_slow, and the 'le' K / D cross
        assert np.array_equal(N.as_bool(r["comp_long"][0][1]), (ind["ema_fast"] < ind["ema_slow"]).to_numpy(bool))
        assert np.array_equal(N.as_bool(r["comp_long"][1][1]), M.ds.cross_below(ind["K"], ind["D"], "le"))
        assert np.array_equal(N.as_bool(r["comp_short"][1][1]), M.ds.cross_above(ind["K"], ind["D"], "le"))
        # an entry is never also an exit of its own side (A.1 edge cases); a short entry on a bar implies the long exit there
        assert not (sig["long_entry"].to_numpy(bool) & lx).any() and not (sig["short_entry"].to_numpy(bool) & sx).any()
        assert not (sig["short_entry"].to_numpy(bool) & ~lx).any()


@pytest.mark.parametrize("pid,name,tf,combo", [p for p in PICKS if p[1] == "N13_3OUTSIDE"], ids=["30m", "1h"])
def test_core_n13_masks_equal_run_signals_on_synthetic_bars(pid, name, tf, combo):
    M = R.core_module("N13_3OUTSIDE")
    for combo_i in (combo, LOOSE["N13_3OUTSIDE"], R.default_combo("core", "N13_3OUTSIDE")):
        for seed in (91, 92):
            df = rand_frame(seed, 3000, tf, sigma=0.012)
            r = N.native_arrays("N13_3OUTSIDE", df, tf, combo_i)                 # raises if the masks differ from M.signals
            lo, sh = (np.asarray(x, bool) for x in M.signals(df, tf, **combo_i))
            assert np.array_equal(N.as_bool(r["comp_long"][0][1]), sh) and np.array_equal(N.as_bool(r["comp_short"][0][1]), lo)
            assert np.array_equal(np.isfinite(r["lvl_long"]), lo) and np.array_equal(np.isfinite(r["lvl_short"]), sh)


# ====================================================================================================== expect, safeguards
@pytest.mark.parametrize("pid,name,tf,combo", [next(p for p in PICKS if p[1] == nm) for nm in NAMES], ids=list(NAMES))
def test_core_expect_is_checked_against_the_modules_entry_flags(pid, name, tf, combo):
    """native_arrays(expect=(long, short)): what the runner passes (run.signals on the same frame) is asserted equal to the module's
    own entry flags, for all eight strategies (D12). A wrong flag or a wrong length raises."""
    M = R.core_module(name)
    for cb in [combo] + ([LOOSE[name]] if name in LOOSE else []):
        df = rand_frame(21, 900, tf, sigma=0.012)
        lo, sh = (np.asarray(x, bool) for x in M.signals(df, tf, **cb))
        ref = arrays_of(N.native_arrays(name, df, tf, cb))
        got = arrays_of(N.native_arrays(name, df, tf, cb, expect=(lo, sh)))
        assert ref.keys() == got.keys() and all(same(ref[k], got[k]) for k in ref)
        for bad in ((~lo, sh), (lo, ~sh)):
            with pytest.raises(AssertionError):
                N.native_arrays(name, df, tf, cb, expect=bad)
        with pytest.raises(AssertionError):
            N.native_arrays(name, df, tf, cb, expect=(lo[:-1], sh[:-1]))
    N.native_arrays(name, df.iloc[:0], tf, combo, expect=(np.zeros(0, bool), np.zeros(0, bool)))       # an empty frame is fine


@pytest.mark.parametrize("mod", ("native.py", "native_ds.py"))
def test_core_the_native_modules_have_no_bare_assert_statements(mod):
    """A bare ``assert`` is removed by ``python -O``; every safeguard of the two modules is an explicit raise."""
    with open(os.path.join(HERE, mod)) as fh:
        tree = ast.parse(fh.read())
    assert [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assert)] == []


def test_core_require_real_turns_a_skip_into_a_failure(monkeypatch):
    """EXITFLEX_REQUIRE_REAL (the pin and the A1 rerun): a real-data test that cannot run FAILS instead of being skipped."""
    me = sys.modules[__name__]
    monkeypatch.setattr(me, "REQUIRE_REAL", False)
    with pytest.raises(pytest.skip.Exception):
        skip_or_fail("no data")
    monkeypatch.setattr(me, "REQUIRE_REAL", True)
    with pytest.raises(pytest.fail.Exception):
        skip_or_fail("no data")


# ====================================================================================================== real select-period bars
@pytest.fixture(scope="module")
def real():
    """Real 1m bars cut before 2024-01-01 (arrays at or after the cut are dropped as soon as they are read), chart frames from
    run.build_frame (through run.frame, so that run.signals sees the same objects). Only booleans leave this module."""
    if not os.path.isdir(os.path.join(DATA_DIR, "1m")):
        skip_or_fail("the study's 1m arrays are not on this machine")
    if R.FRAME_DIR[0] is not None:
        skip_or_fail("run.FRAME_DIR is set: frames would come from another stage's pickles")
    cache = {}

    def cut_data(d, sym):
        if sym not in cache:
            with np.load(os.path.join(d, "1m", f"{sym}.npz")) as z:
                n = int(np.searchsorted(z["ts"], CUT_MS, "left"))
                while len(cache) >= 2:                  # at most two coins in memory (the DeepSeek tests alternate BTC / DOGE)
                    cache.pop(next(iter(cache)))
                cache[sym] = {k: z[k][:n].copy() for k in ("ts", "o", "h", "l", "c", "v")}
            assert cache[sym]["ts"][-1] < CUT_MS
        return cache[sym]

    mp = pytest.MonkeyPatch()
    mp.setattr(R, "minute_data", cut_data)
    R.frame.cache_clear()

    class Real:
        dir = DATA_DIR                                  # what the DeepSeek tests pass to R.frame / R.signals

        def frame(self, sym, tf):
            df, close_ms = R.frame(DATA_DIR, sym, tf)
            assert int(close_ms[-1]) <= CUT_MS and df["ts"].iloc[-1] < pd.Timestamp("2024-01-01", tz="UTC")
            return df

        def signals(self, name, sym, tf, combo):
            return R.signals(DATA_DIR, "core", name, sym, tf, combo)

    yield Real()
    mp.undo()
    R.frame.cache_clear()
    R.minute_data.cache_clear()


@pytest.mark.parametrize("pid,name,tf,combo", DOGE_PICKS, ids=[p[0] for p in DOGE_PICKS])
@pytest.mark.parametrize("sym", ["DOGEUSDT", "BTCUSDT"])
def test_core_doge_components_equal_the_source_exit_on_real_select_bars(real, pid, name, tf, combo, sym):
    M = R.core_module("DOGE")
    df = real.frame(sym, tf)
    r = N.native_arrays("DOGE", df, tf, combo)
    p = M.doge_params(tf, **combo)
    d = M._frame(df)
    ind = M.ds.compute_indicators(d, p)
    sig = M.ds.compute_signals(d, ind, p)
    lx = N.as_bool(r["comp_long"][0][1]) | N.as_bool(r["comp_long"][1][1])
    sx = N.as_bool(r["comp_short"][0][1]) | N.as_bool(r["comp_short"][1][1])
    assert np.array_equal(lx, sig["long_exit"].to_numpy(bool)) and np.array_equal(sx, sig["short_exit"].to_numpy(bool))
    # and the study's own entry flags (run.signals) keep the Appendix edge case: an entry bar is not an exit of its side
    lo, sh = real.signals("DOGE", sym, tf, combo)
    le, se = sig["long_entry"].to_numpy(bool), sig["short_entry"].to_numpy(bool)
    assert np.array_equal(lo, le) and np.array_equal(sh, se & ~le)
    assert not (lo & lx).any() and not (sh & sx).any()


@pytest.mark.parametrize("pid,name,tf,combo", [p for p in PICKS if p[1] == "N13_3OUTSIDE"], ids=["30m", "1h"])
@pytest.mark.parametrize("sym", ["DOGEUSDT", "BTCUSDT", "ETHUSDT"])
def test_core_n13_masks_equal_run_signals_on_real_select_bars(real, pid, name, tf, combo, sym):
    df = real.frame(sym, tf)
    r = N.native_arrays("N13_3OUTSIDE", df, tf, combo)                          # raises if the masks differ from the module's
    lo, sh = real.signals("N13_3OUTSIDE", sym, tf, combo)                       # run.signals
    assert np.array_equal(N.as_bool(r["comp_long"][0][1]), sh) and np.array_equal(N.as_bool(r["comp_short"][0][1]), lo)
    assert np.array_equal(np.isfinite(r["lvl_long"]), lo) and np.array_equal(np.isfinite(r["tgt_long"]), lo)
    assert np.array_equal(np.isfinite(r["lvl_short"]), sh)
    cl = df["close"].to_numpy(float)
    assert (r["lvl_long"][lo] < cl[lo]).all() and (r["lvl_short"][sh] > cl[sh]).all()      # both level legs armed at once
    assert (r["tgt_long"][lo] > r["lvl_long"][lo]).all()                                   # PH + (PH - PL) > PL
    fin = np.isfinite(r["tgt_short"])
    assert (r["tgt_short"][fin] > 0).all() and (fin | ~sh | (r["lvl_short"] > 0)).all()    # a short target is positive or none


@pytest.mark.parametrize("pid,name,tf,combo", PICKS, ids=PICK_IDS)
def test_core_every_pick_on_real_select_bars_runs_and_is_armed_at_the_signal(real, pid, name, tf, combo):
    df = real.frame("DOGEUSDT", tf)
    lo, sh = real.signals(name, "DOGEUSDT", tf, combo)
    r = N.native_arrays(name, df, tf, combo, expect=(lo, sh))                   # the runner passes run.signals: asserted equal
    n = len(df)
    assert all(len(a) == n for a in arrays_of(r).values())
    cl = df["close"].to_numpy(float)
    spec = N.SPEC[name]
    for side, flag in (("long", lo), ("short", sh)):
        if not flag.any():
            continue
        # Appendix 'edge cases': at the signal bar of its own side, every state component of that side is armed at once,
        # except N03's EMA leg (whipsaw) and N10's candle leg (rare) -- these two may be true there; all others are false
        for k, (kind, arr) in enumerate(r["comp_" + side]):
            tolerated = (name == "N03_ADX_GC" and k == 0) or (name == "N10_HA_PSAR" and k == 1)
            if kind == "state" and not tolerated:
                assert not N.as_bool(arr)[flag].any(), (name, side, k)
        if spec["level"]:
            lv = r["lvl_" + side]
            assert np.isfinite(lv[flag]).all()
            assert (SIDE_SIGN[side] * (lv[flag] - cl[flag]) < 0).all()          # the close is not beyond the level at the signal bar


def test_core_real_prefix_equals_full_on_select_bars(real):
    """T3 on real bars (booleans): the last 50 bars before a cut are the same from the cut frame and from the full frame."""
    for pid, name, tf, combo in PICKS:
        if tf not in ("1h", "4h"):
            continue
        df = real.frame("DOGEUSDT", tf)
        k = len(df) * 3 // 5
        full = arrays_of(N.native_arrays(name, df, tf, combo))
        cut = arrays_of(N.native_arrays(name, df.iloc[:k].copy(), tf, combo))
        assert all(same(full[key][k - 50:k], cut[key][k - 50:k]) for key in full), pid


# ====================================================================================================================
# ====================================================================================================================
#                                                  native_ds.py
# ====================================================================================================================
# ====================================================================================================================

import native_ds as ND  # noqa: E402

D = ND.ds_module()
FGI = D.C.env()["fg"]                      # the vendor indicators ds_defs uses (ATR14 here)
AXIS = 400.0                                  # the mirror axis: price' = AXIS - price
START = pd.Timestamp("2022-01-03", tz="UTC").value // 10 ** 6      # a Monday 00:00 UTC, aligned to every timeframe
CANDIDATES = os.path.join(ROOT, "candleague", "data", "candidates.json")


# ====================================================================================================== harness
def mkdf(bars, tf="1h", v=None, start_ms=START):
    """A chart frame (the layout run.build_frame gives) from (open, high, low, close) rows."""
    a = np.array(bars, float)
    o, h, l, c = a.T
    assert (h >= np.maximum(o, c)).all() and (l <= np.minimum(o, c)).all(), "inconsistent hand-built bar"
    n = len(c)
    ms = start_ms + np.arange(n, dtype=np.int64) * TF_MS[tf]
    df = pd.DataFrame({"ts": pd.to_datetime(ms, unit="ms", utc=True), "open": o, "high": h, "low": l, "close": c,
                       "volume": np.ones(n) if v is None else np.asarray(v, float)})
    df.attrs["tf"] = tf
    return df


def ds_mirror(df, axis=AXIS):
    """The same bars upside down: long entries become short entries (and conversely) for a strategy that is symmetric."""
    out = df.copy()
    out["open"], out["high"], out["low"], out["close"] = axis - df["open"], axis - df["low"], axis - df["high"], axis - df["close"]
    out.attrs["tf"] = df.attrs["tf"]
    return out


def filler(n, base=100.0, amp=1.0, seed=0):
    """Quiet oscillation around ``base`` (range about 2), open = previous close, with a little noise so that no two bars tie."""
    rng = np.random.default_rng(seed)
    cl = base + amp * np.sin(np.arange(n) * 0.9) + rng.normal(0, 0.05, n)
    out, prev = [], base
    for c in cl:
        out.append((prev, max(prev, c) + 0.5 + abs(rng.normal(0, 0.03)), min(prev, c) - 0.5 - abs(rng.normal(0, 0.03)), c))
        prev = c
    return out


def saw(n, seed=1):
    """A sawtooth between 94 and 106 (period 8): a range with a known floor (about 93) and ceiling (about 107)."""
    rng = np.random.default_rng(seed)
    pat = np.array([100, 103, 106, 103, 100, 97, 94, 97], float)
    out, prev = [], 100.0
    for i in range(n):
        c = pat[i % 8] + rng.normal(0, 0.02)
        out.append((prev, max(prev, c) + 1 + abs(rng.normal(0, 0.02)), min(prev, c) - 1 - abs(rng.normal(0, 0.02)), c))
        prev = c
    return out


def zig(points, p0=100.0, spread=0.3, wick=0.6):
    """Waypoints [(bars, target price), ...]: closes move linearly, open = previous close, high / low = the extremes of open
    and close widened by ``spread``; the last bar of a segment that turns gets an extra ``wick`` so it is a strict pivot."""
    out, prev = [], p0
    for si, (n, tgt) in enumerate(points):
        nxt = points[si + 1][1] if si + 1 < len(points) else None
        for k in range(1, n + 1):
            c = prev + (tgt - prev) * k / n
            o = out[-1][3] if out else p0
            h, l = max(o, c) + spread, min(o, c) - spread
            if k == n and nxt is not None:
                if tgt > prev and nxt < tgt:
                    h += wick
                if tgt < prev and nxt > tgt:
                    l -= wick
            out.append((o, h, l, c))
        prev = tgt
    return out


def rand_df(seed, n, tf="1h", vol=0.01, trend=0.0006, seg=180, scale=100.0):
    """A seeded random walk with drifting regimes (so ranges, trends and reversals all occur)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-1.0, 1.0, 0.0], size=n // seg + 1), seg)[:n] * trend
    c = scale * np.exp(np.cumsum(rng.normal(0, vol, n) + drift))
    o = np.r_[scale, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    ms = START + np.arange(n, dtype=np.int64) * TF_MS[tf]
    df = pd.DataFrame({"ts": pd.to_datetime(ms, unit="ms", utc=True), "open": o, "high": h, "low": l, "close": c,
                       "volume": rng.uniform(1, 5, n)})
    df.attrs["tf"] = tf
    return df


def perturb_after(df, i, seed):
    """The same frame up to and including bar i; every bar after it replaced by a different random walk (other volatility,
    other volume) that starts at bar i's close."""
    n = len(df)
    out = df.copy()
    if i >= n - 1:
        return out
    tail = rand_df(seed, n - i - 1, df.attrs["tf"], vol=0.03, trend=0.002, seg=40, scale=1.0)
    k = float(df["close"].iloc[i])
    for col in ("open", "high", "low", "close"):
        out.iloc[i + 1:, out.columns.get_loc(col)] = tail[col].to_numpy() * k
    out.iloc[i + 1:, out.columns.get_loc("volume")] = tail["volume"].to_numpy() * 7.0
    out.attrs["tf"] = df.attrs["tf"]
    return out


def prefix(df, i):
    out = df.iloc[:i + 1].reset_index(drop=True).copy()
    out.attrs["tf"] = df.attrs["tf"]
    return out


def sig(df, tf, name, combo, ctx=None, coin="BTCUSD"):
    """(long, short) from a fresh ds_defs call (its own cache), the reference the tests compare with."""
    lg, sh = D.signals(df, tf, name, ctx=ctx, coin=coin, cache={}, **combo)
    return np.asarray(lg, bool), np.asarray(sh, bool)


def calc(df, tf, name, combo, ctx=None, coin="BTCUSD"):
    return ND.native(df, tf, name, combo, ctx, coin)


def ds_same(a, b):
    return np.array_equal(np.asarray(a), np.asarray(b), equal_nan=True)


def first_exit(res, df, i0, side):
    """The rule of A.0 on the signal bar i0 of ``side`` (+1 long, -1 short): the own-side component and the level test are
    both false at i0 (``native`` asserts it), so rule C3 arms them at once; the exit is the first chart close after i0 at which
    the component is true or the close is beyond the level (below inv_l, above inv_s). None when there is none."""
    comp = res.lx if side > 0 else res.sx
    lvl = res.inv_l[i0] if side > 0 else res.inv_s[i0]
    c = df["close"].to_numpy()
    for j in range(i0 + 1, len(c)):
        if comp[j]:
            return j
        if np.isfinite(lvl) and ((c[j] < lvl) if side > 0 else (c[j] > lvl)):
            return j
    return None


def first_true_after(x, i0):
    nz = np.flatnonzero(np.asarray(x, bool)[i0 + 1:])
    return int(nz[0]) + i0 + 1 if len(nz) else None


def fin(x):
    return np.isfinite(x)


# the strategies, a dense combination of each (many signals on a random walk) and the timeframe it is tried on
DENSE = {
    "F10_OTE": ("1h", dict(swing_k=2, leg_atr=1.0, leg_max_bars=30)),
    "F11_TSOUP": ("4h", dict(tsoup_len=10, min_age=2)),
    "F12_MSS_DISP": ("1h", dict(swing_k=2, disp_atr=0.3)),
    "F1_PVT_DIV": ("1h", dict(swing_k=3, div_max_bars=40)),
    "F5_BOX": ("1h", dict(box_len=20, adx_max=40.0, edge=0.3, width_atr=1.0)),
    "F7_RF_ONLY": ("1h", dict(rf_period=10, rf_mult=1.5)),
    "F7_RF_TRIPLE": ("1h", dict(rf_period=10, rf_mult=1.5)),
    "F9_FVG": ("1h", dict(fvg_min_atr=0.3, zone_life=30)),
}
LEVEL_ONLY = ("F10_OTE", "F11_TSOUP", "F1_PVT_DIV", "F5_BOX", "F9_FVG")
SYMMETRIC = tuple(n for n in DENSE if n != "F1_PVT_DIV")     # PVT is built from price ratios: not an exact mirror


# the 15 picks as Appendix A writes them (the combos), against candidates.json
APPENDIX_A = {
    "ds-F10_OTE-1h-1": ("F10_OTE", "1h", dict(swing_k=3, leg_atr=3.75, leg_max_bars=30)),
    "ds-F10_OTE-4h-1": ("F10_OTE", "4h", dict(swing_k=3, leg_atr=1.5, leg_max_bars=15)),
    "ds-F11_TSOUP-4h-1": ("F11_TSOUP", "4h", dict(tsoup_len=30, min_age=2)),
    "ds-F12_MSS_DISP-1h-1": ("F12_MSS_DISP", "1h", dict(swing_k=2, disp_atr=1.8)),
    "ds-F12_MSS_DISP-4h-1": ("F12_MSS_DISP", "4h", dict(swing_k=5, disp_atr=0.96)),
    "ds-F1_PVT_DIV-1h-1": ("F1_PVT_DIV", "1h", dict(swing_k=9, div_max_bars=75)),
    "ds-F5_BOX-15m-1": ("F5_BOX", "15m", dict(box_len=72, adx_max=16.0, edge=0.12, width_atr=9.0)),
    "ds-F5_BOX-4h-1": ("F5_BOX", "4h", dict(box_len=48, adx_max=60.0, edge=0.45, width_atr=1.5)),
    "ds-F7_RF_ONLY-30m-1": ("F7_RF_ONLY", "30m", dict(rf_period=80, rf_mult=9.0)),
    "ds-F7_RF_ONLY-1h-3": ("F7_RF_ONLY", "1h", dict(rf_period=67, rf_mult=2.4)),
    "ds-F7_RF_ONLY-4h-1": ("F7_RF_ONLY", "4h", dict(rf_period=33, rf_mult=1.0)),
    "ds-F7_RF_TRIPLE-1h-1": ("F7_RF_TRIPLE", "1h", dict(rf_period=80, rf_mult=9.0)),
    "ds-F7_RF_TRIPLE-4h-1": ("F7_RF_TRIPLE", "4h", dict(rf_period=50, rf_mult=4.5)),
    "ds-F9_FVG-1h-1": ("F9_FVG", "1h", dict(fvg_min_atr=1.0, zone_life=40)),
    "ds-F9_FVG-4h-1": ("F9_FVG", "4h", dict(fvg_min_atr=0.1667, zone_life=75)),
}


def ds_picks():
    with open(CANDIDATES) as fh:
        rows = json.load(fh)["candidates"]
    return [r for r in rows if r["kind"] == "ds"]


# ====================================================================================================== interface
def test_ds_the_eight_strategies_of_appendix_a():
    assert tuple(sorted(ND.NAMES)) == tuple(sorted({v[0] for v in APPENDIX_A.values()}))
    assert len(ND.NAMES) == 8 and set(ND.NAMES) == set(ND._BUILD)


def test_ds_picks_are_the_fifteen_of_appendix_a():
    rows = ds_picks()
    assert sorted(r["id"] for r in rows) == sorted(APPENDIX_A)
    for r in rows:
        name, tf, combo = APPENDIX_A[r["id"]]
        assert (r["name"], r["tf"]) == (name, tf)
        assert set(r["combo"]) == set(combo)
        for k, v in combo.items():
            assert abs(float(r["combo"][k]) - v) < 1e-3 * max(1.0, abs(v)), (r["id"], k)


@pytest.mark.parametrize("name", ND.NAMES)
def test_ds_result_arrays(name):
    tf, combo = DENSE[name]
    df = rand_df(3, 900, tf)
    before = df.copy()
    r = calc(df, tf, name, combo)
    n = len(df)
    assert isinstance(r, tuple) and len(r) == 6
    lx, sx, inv_l, inv_s, tgt_l, tgt_s = r                        # the order of A.0, as the runner's glue unpacks it
    for a in (lx, sx):
        assert a.dtype == bool and a.shape == (n,)
    for a in (inv_l, inv_s, tgt_l, tgt_s):
        assert a.dtype == np.float64 and a.shape == (n,)
    for k, a in zip(("lx", "sx", "inv_l", "inv_s", "tgt_l", "tgt_s"), r):
        assert r[k] is a and getattr(r, k) is a and r.get(k) is a      # also readable by name, as a dict
    assert tuple(r.keys()) == ("lx", "sx", "inv_l", "inv_s", "tgt_l", "tgt_s")
    assert dict(r).keys() == set(r.keys()) and r.get("zz") is None
    with pytest.raises(KeyError):
        r["zz"]
    r3 = pickle.loads(pickle.dumps(r))                              # worker processes may pass it around
    assert isinstance(r3, ND.NativeDS) and all(ds_same(a, b) for a, b in zip(r, r3))
    assert df.equals(before)                                       # the input frame is not changed
    r2 = calc(df, tf, name, combo)                                 # nothing is kept between calls
    assert all(ds_same(a, b) for a, b in zip(r, r2))


def test_ds_other_names_are_refused():
    df = rand_df(1, 300, "1h")
    for bad in ("F3_BOS", "F16_FIB618", "N13_3OUTSIDE", "DOGE", ""):
        with pytest.raises(ValueError):
            ND.native(df, "1h", bad, {}, None, "BTCUSD")


@pytest.mark.parametrize("name", ND.NAMES)
def test_ds_expect_is_checked_against_run_signals_style_arrays(name):
    tf, combo = DENSE[name]
    df = rand_df(4, 900, tf)
    lg, sh = sig(df, tf, name, combo)
    r = ND.native(df, tf, name, combo, None, "BTCUSD", expect=(lg, sh))        # equal: passes
    assert all(ds_same(a, b) for a, b in zip(r, calc(df, tf, name, combo)))
    for bad_l, bad_s in ((~lg, sh), (lg, ~sh)):
        with pytest.raises(AssertionError):
            ND.native(df, tf, name, combo, None, "BTCUSD", expect=(bad_l, bad_s))


# ====================================================================================================== hand paths
def path_box():
    """A sawtooth range (floor about 93, ceiling about 107), then a bullish bar in the bottom 20% of the box (bar 60), then
    a close below the floor (bar 63)."""
    b = saw(60)
    seq = [(94.0, 96.5, 93.5, 95.5),          # 60: signal bar, pos = (95.5 - 92.97) / 14.06 = 0.18 <= edge 0.2
           (95.5, 97.0, 95.0, 96.5),          # 61
           (96.5, 96.8, 94.5, 95.0),          # 62: still above the floor
           (95.0, 95.2, 92.0, 92.5)]          # 63: closes below the floor 92.97
    return mkdf(b + seq)


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f5_box(side):
    combo = dict(box_len=10, adx_max=100.0, edge=0.2, width_atr=0.5)
    df = path_box() if side > 0 else ds_mirror(path_box())
    lg, sh = sig(df, "1h", "F5_BOX", combo)
    s = 60
    assert (lg if side > 0 else sh)[s] and not (sh if side > 0 else lg)[s]
    r = calc(df, "1h", "F5_BOX", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    hi, lo = h[s - 10:s].max(), l[s - 10:s].min()                   # the box of the previous 10 bars, by hand
    if side > 0:
        assert abs(lo - 92.97) < 0.1 and abs(hi - 107.03) < 0.1       # the design, checked
        assert (r.inv_l[s], r.tgt_l[s]) == (lo, hi) and not fin(r.inv_s).any() and not fin(r.tgt_s).any()
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (hi, lo) and not fin(r.inv_l).any() and not fin(r.tgt_l).any()
    assert not r.lx.any() and not r.sx.any()                       # a level-only strategy
    assert first_exit(r, df, s, side) == 63                        # not at 61 or 62, at the first close beyond the floor


def path_tsoup():
    b = filler(50)
    last = b[-1][3]
    seq = [(last, 100.8, 98.0, 99.0),          # 50
           (99.0, 99.5, 97.0, 98.0),           # 51
           (98.0, 98.5, 92.5, 93.5),           # 52: the lowest low of the window (92.5), age 4 at the signal bar
           (93.5, 96.0, 93.0, 95.5),           # 53
           (95.5, 98.0, 95.0, 97.5),           # 54
           (97.5, 99.0, 96.5, 98.0),           # 55
           (98.0, 98.2, 90.0, 94.0),           # 56: signal bar, low 90.0 < 92.5, close 94.0 back above it
           (94.0, 95.0, 92.0, 94.5),           # 57: close above the sweep low
           (94.5, 94.6, 89.0, 89.5)]           # 58: close below 90.0
    return mkdf(b + seq, tf="4h")


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f11_tsoup(side):
    combo = dict(tsoup_len=10, min_age=2)
    df = path_tsoup() if side > 0 else ds_mirror(path_tsoup())
    lg, sh = sig(df, "4h", "F11_TSOUP", combo)
    s = 56
    assert (lg if side > 0 else sh)[s] and not (sh if side > 0 else lg)[s]
    r = calc(df, "4h", "F11_TSOUP", combo, )
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    mid = (h[s - 10:s].max() + l[s - 10:s].min()) / 2               # the middle of the 10 bars before the signal bar
    if side > 0:
        assert abs(df["low"][s] - 90.0) < 1e-9 and abs(l[s - 10:s].min() - 92.5) < 1e-9
        assert (r.inv_l[s], r.tgt_l[s]) == (l[s], mid)
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (h[s], mid)
    assert not r.lx.any() and not r.sx.any()
    assert first_exit(r, df, s, side) == 58                        # a close beyond the sweep extreme, not the earlier retest


def path_mss(single_high=False):
    if single_high:         # only one swing high before the break: no "swing high before the one broken"
        pts = [(8, 100.0), (6, 90.0), (4, 93.0), (6, 86.0), (4, 96.0), (3, 99.0)]
    else:
        pts = [(8, 100.0), (6, 90.0), (4, 96.0), (6, 86.0), (4, 93.0), (4, 88.0), (4, 97.0), (4, 101.0), (4, 94.0),
               (3, 98.0), (5, 90.0)]
    return mkdf(zig(pts))


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f12_mss_disp(side):
    combo = dict(swing_k=2, disp_atr=0.5)
    base = path_mss()
    df = base if side > 0 else ds_mirror(base)
    lg, sh = sig(df, "1h", "F12_MSS_DISP", combo)
    s = 34                                      # closes 90.25, 92.5, 94.75, 97: the third is the first above the swing high 93.9
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F12_MSS_DISP", combo)
    h, l, c = (base[k].to_numpy() for k in ("high", "low", "close"))
    # target: the swing high before the one the MSS broke = the bar-17 turn (96 + spread 0.3 + wick 0.6)
    assert abs(h[17] - 96.9) < 1e-9
    assert not fin(r.inv_l).any() and not fin(r.inv_s).any()            # no invalidation level: the structure flag is the exit
    if side > 0:
        assert r.tgt_l[s] == h[17]
    else:
        assert r.tgt_s[s] == AXIS - h[17]
    # the exit: the structure turns back. The swing low of bar 43 is confirmed at bar 45 (swing_k 2); the first close below
    # its low afterwards is the exit (bar 50). Nothing fires between the signal bar and then.
    pivot_low = l[43]
    j = next(j for j in range(45, len(c)) if c[j] < pivot_low)     # from the bar that confirms the pivot (45)
    assert j == 50
    comp = r.lx if side > 0 else r.sx
    other = r.sx if side > 0 else r.lx
    assert not comp[s:j].any() and comp[j]
    assert first_exit(r, df, s, side) == j
    # the other side's flag, bos / mss in the signal's direction, is what a position on the other side would exit on
    assert other[s]                                                  # true at the signal bar itself (the MSS)


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f12_no_target_when_there_is_no_earlier_swing_high(side):
    combo = dict(swing_k=2, disp_atr=0.5)
    df = path_mss(single_high=True)
    df = df if side > 0 else ds_mirror(df)
    lg, sh = sig(df, "1h", "F12_MSS_DISP", combo)
    s = 27
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F12_MSS_DISP", combo)
    assert np.isnan(r.tgt_l[s]) and np.isnan(r.tgt_s[s])            # NaN = none (C7): the hard stop and the structure act


# ---------------------------------------------------------------- the z flags (PREREG 6; native_ds DECISIONS 14)
def engine_latches(df, k):
    """(live swing low, live swing high) per bar from a test-owned copy of the loop of ``ds_defs.structure`` on the raw bars (the
    pivots from the library, then the engine's latches ``lo_bos`` / ``hi_bos``, each recorded after the bar's own confirmation
    and before its break test). Independent of ``native_ds.live_swing``, which replays them from the arrays the engine exports."""
    h, l, c = (df[x].to_numpy(float) for x in ("high", "low", "close"))
    ph, pl = D.C.pivots_conf(h, l, k)
    n = len(c)
    hi_lvl = lo_lvl = np.nan
    hi_bos = lo_bos = False
    z_l, z_s = np.zeros(n, bool), np.zeros(n, bool)
    for t in range(n):
        if ph[t]:
            hi_lvl, hi_bos = h[t - k], True
        if pl[t]:
            lo_lvl, lo_bos = l[t - k], True
        z_l[t], z_s[t] = lo_bos, hi_bos
        up = hi_bos and c[t] > hi_lvl
        dn = lo_bos and c[t] < lo_lvl
        if up and not dn:
            hi_bos = False
        elif dn and not up:
            lo_bos = False
    return z_l, z_s


@pytest.mark.parametrize("side", (1, -1))
def test_ds_f12_z_hand_path_a_live_level_exists_between_its_confirmation_and_its_break(side):
    """path_mss, swing_k 2, derived by hand. Swing lows turn at bars 13, 23, 31, 43 (confirmed 2 bars later: 15, 25, 33, 45); the
    first leg is flat, so the first swing high is the turn at 17 (confirmed 19); the others turn at 27, 39, 46 (confirmed 29, 41, 48);
    bar 35 is not a turn (the rise goes on).
    Long side, z_l (a live swing low): none before bar 15; the low of bar 13 (89.1) is broken by the close of bar 22 (87.67), which
    is the FIRST break of the series (state 0: no bos / mss flag); nothing is live at 23 and 24; the low of bar 23 is confirmed at 25
    and stays live (the next ones, 87.1 and 93.1, are confirmed at 33 and 45); the close of bar 50 (91.6) breaks 93.1 (mss_dn, the
    exit of the long entered by the MSS at bar 34); nothing is live at bar 51.
    z_s (a live swing high): none before 19; the high of bar 27 (93.9, in force from 29) is broken by the close of bar 34 (94.75,
    the MSS = the entry); nothing is live at 35 to 40; the high of bar 39 is confirmed at 41 and is never broken."""
    combo = dict(swing_k=2, disp_atr=0.5)
    base = path_mss()
    df = base if side > 0 else ds_mirror(base)
    r = calc(df, "1h", "F12_MSS_DISP", combo)
    no_low = sorted(set(range(0, 15)) | {23, 24, 51})
    no_high = sorted(set(range(0, 19)) | set(range(35, 41)))
    zl, zs = (r.z_l, r.z_s) if side > 0 else (r.z_s, r.z_l)               # the mirror turns lows into highs
    fl, fs = (r.lx, r.sx) if side > 0 else (r.sx, r.lx)
    assert np.flatnonzero(~zl).tolist() == no_low
    assert np.flatnonzero(~zs).tolist() == no_high
    assert r.z_l.dtype == bool and r.z_s.dtype == bool and len(r.z_l) == len(df)
    # the flags can be true only where z is: the break of bar 50 (exit of the long), the MSS of bar 34 (the short side's flag)
    assert np.flatnonzero(fl).tolist() == [50] and not fl[22] and zl[22]             # bar 22: the state-0 break has no flag
    assert 34 in np.flatnonzero(fs).tolist() and zs[34]
    assert not (fl & ~zl).any() and not (fs & ~zs).any()
    # a shortcut "latch = confirmation | (previous latch and not a flagged break)" misses the state-0 break of bar 22: bars 23 and 24
    # would stay live although the level is broken (the reason live_swing replays the engine's rule instead)
    S = D.structure(base["open"].to_numpy(), base["high"].to_numpy(), base["low"].to_numpy(), base["close"].to_numpy(), 2)
    naive = np.zeros(len(base), bool)
    for t in range(len(base)):
        naive[t] = S["pl_conf"][t] or (t > 0 and naive[t - 1] and not (S["bos_dn"][t - 1] or S["mss_dn"][t - 1]))
    assert naive[23] and naive[24] and not naive[:15].any()


@pytest.mark.parametrize("k", (2, 3, 5))
@pytest.mark.parametrize("seed", (1, 2, 3))
def test_ds_f12_z_equals_an_independent_replay_of_the_engine(k, seed):
    tf = "1h"
    df = rand_df(seed, 2500, tf, vol=0.012)
    r = calc(df, tf, "F12_MSS_DISP", dict(swing_k=k, disp_atr=0.3))
    z_l, z_s = engine_latches(df, k)
    assert ds_same(r.z_l, z_l) and ds_same(r.z_s, z_s)
    assert z_l.any() and (~z_l).sum() > k and z_s.any() and (~z_s).sum() > k       # both values occur on both sides
    assert r.lx.any() and r.sx.any()
    assert not (r.lx & ~r.z_l).any() and not (r.sx & ~r.z_s).any()                # a flag is true only where z is
    # the warm-up: no swing is confirmed before bar 2k, so nothing is live before it
    assert not r.z_l[:2 * k].any() and not r.z_s[:2 * k].any()


@pytest.mark.parametrize("name", ND.NAMES)
def test_ds_z_flags_are_attributes_not_tuple_elements(name):
    tf, combo = DENSE[name]
    df = rand_df(3, 900, tf)
    r = calc(df, tf, name, combo)
    n = len(df)
    for z in (r.z_l, r.z_s):
        assert z.dtype == bool and z.shape == (n,)
    assert len(r) == 6 and tuple(r.keys()) == ("lx", "sx", "inv_l", "inv_s", "tgt_l", "tgt_s")       # the unpacking of A.0 is unchanged
    assert r["z_l"] is r.z_l and r.get("z_s") is r.z_s and r.get("z_x", 7) == 7
    for clone in (pickle.loads(pickle.dumps(r)), copy.copy(r), copy.deepcopy(r)):
        assert isinstance(clone, ND.NativeDS) and ds_same(clone.z_l, r.z_l) and ds_same(clone.z_s, r.z_s)
        assert all(ds_same(a, b) for a, b in zip(r, clone))
    assert ND.NativeDS._make(tuple(r)).z_l is None                    # a bare six-array tuple: None = "True everywhere" for normalize_f11
    if name != "F12_MSS_DISP":                                         # every other strategy can fire at every bar (DECISIONS 14)
        assert r.z_l.all() and r.z_s.all()
    r.z_l[:] = False                                                   # fresh arrays: changing a result does not touch the next call
    r.z_s[:] = False
    r2 = calc(df, tf, name, combo)
    assert r2.z_l.any() and r2.z_s.any()


def path_pvt():
    b = filler(40)
    last = b[-1][3]
    seq = [(last, 100.5, 98.6, 99.0),      # 40
           (99.0, 99.2, 98.2, 98.5),       # 41
           (98.5, 98.7, 96.8, 97.0),       # 42: first swing low a (low 96.8)
           (97.0, 98.5, 96.9, 98.0),       # 43
           (98.0, 99.2, 97.9, 99.0),       # 44
           (99.0, 101.2, 98.9, 101.0),     # 45: the rally has big volume
           (101.0, 103.2, 100.9, 103.0),   # 46
           (103.0, 105.2, 102.9, 105.0),   # 47
           (105.0, 107.2, 104.9, 107.0),   # 48
           (107.0, 108.5, 106.5, 107.5),   # 49: highest high between the lows (108.5)
           (107.5, 107.6, 105.4, 105.5),   # 50: the decline has tiny volume
           (105.5, 105.6, 103.4, 103.5),   # 51
           (103.5, 103.6, 101.4, 101.5),   # 52
           (101.5, 101.6, 99.4, 99.5),     # 53
           (99.5, 99.6, 97.4, 97.5),       # 54
           (97.5, 97.6, 95.5, 96.5),       # 55: second swing low b (low 95.5 < 96.8), PVT higher: bullish divergence
           (96.5, 98.0, 96.0, 97.5),       # 56
           (97.5, 99.0, 97.0, 98.5),       # 57: b + 2 = the bar that confirms the pivot = the signal bar
           (98.5, 99.0, 97.5, 98.0),       # 58
           (98.0, 98.5, 96.0, 96.5),       # 59: still above l[b]
           (96.5, 96.7, 94.5, 95.0)]       # 60: close below l[b] = 95.5
    v = np.ones(len(b) + len(seq))
    v[45:50] = 100.0
    return b + seq, v


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f1_pvt_div(side):
    combo = dict(swing_k=2, div_max_bars=30)
    bars, v = path_pvt()
    df = mkdf(bars, v=v)
    df = df if side > 0 else ds_mirror(df)
    lg, sh = sig(df, "1h", "F1_PVT_DIV", combo)
    s = 57
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F1_PVT_DIV", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    if side > 0:
        assert (r.inv_l[s], r.tgt_l[s]) == (l[55], h[42:56].max()) and l[55] == 95.5 and h[42:56].max() == 108.5
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (h[55], l[42:56].min())
    assert not r.lx.any() and not r.sx.any()
    assert first_exit(r, df, s, side) == 60


def path_fvg():
    b = filler(50)
    last = b[-1][3]
    seq = [(last, 101.0, 99.5, 100.5),        # 50: b - 2, high 101.0
           (100.5, 108.5, 100.4, 108.0),      # 51: the displacement bar
           (108.0, 110.0, 104.0, 109.0),      # 52: b, low 104.0 > 101.0: a gap of 3 (zone [101, 104], middle 102.5)
           (109.0, 112.0, 108.0, 111.0),      # 53
           (111.0, 113.5, 109.0, 112.0),      # 54: the highest high before the touch (113.5)
           (112.0, 112.5, 108.5, 109.0),      # 55
           (108.0, 108.5, 103.5, 105.0),      # 56: s: low 103.5 <= 104.0 touches, close 105.0 >= 102.5
           (105.0, 105.5, 102.0, 102.5),      # 57: above the gap bottom
           (102.5, 102.6, 100.0, 100.5)]      # 58: close below the gap bottom 101.0
    return mkdf(b + seq)


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f9_fvg(side):
    combo = dict(fvg_min_atr=0.5, zone_life=10)
    df = path_fvg()
    df = df if side > 0 else ds_mirror(df)
    lg, sh = sig(df, "1h", "F9_FVG", combo)
    s = 56
    assert (lg if side > 0 else sh)[s] and (lg | sh).sum() == 1
    r = calc(df, "1h", "F9_FVG", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    if side > 0:
        assert (r.inv_l[s], r.tgt_l[s]) == (101.0, 113.5) == (h[50], h[51:56].max())
    else:                    # short: the gap's top is l[b-2] of the mirrored bars; the target is the lowest low b-1 .. s-1
        assert (r.inv_s[s], r.tgt_s[s]) == (l[50], l[51:56].min()) and r.inv_s[s] == AXIS - 101.0
    assert first_exit(r, df, s, side) == 58


def test_ds_hand_f9_fvg_two_gaps_the_latest_one_gives_the_levels():
    b = filler(50)
    last = b[-1][3]
    seq = [(last, 101.0, 99.5, 100.5),      # 50
           (100.5, 108.5, 100.4, 108.0),    # 51
           (108.0, 110.0, 104.0, 109.0),    # 52: b1, zone [101, 104]
           (109.0, 112.0, 108.0, 111.5),    # 53
           (111.5, 119.0, 109.5, 118.5),    # 54
           (118.5, 121.0, 115.0, 120.0),    # 55: b2, zone [112, 115]
           (120.0, 122.0, 117.0, 121.0),    # 56
           (121.0, 121.5, 116.5, 117.0),    # 57
           (117.0, 117.5, 103.5, 114.0),    # 58: touches both tops, closes above both middles
           (114.0, 114.5, 110.0, 111.0),    # 59: close 111.0 is below the later gap's bottom 112.0 (the older gap's 101.0 is far)
           (111.0, 111.5, 108.0, 108.5)]    # 60
    combo = dict(fvg_min_atr=0.5, zone_life=10)
    for side in (1, -1):
        df = mkdf(b + seq)
        df = df if side > 0 else ds_mirror(df)
        atr = FGI.atr(df, 14).to_numpy(float)
        Z = D.fvg_zones(df["high"].to_numpy(), df["low"].to_numpy(), atr, 0.5)
        assert sorted(Z[0].tolist()) == [52, 55]                      # the design: exactly these two gaps
        lg, sh = sig(df, "1h", "F9_FVG", combo)
        assert (lg if side > 0 else sh)[58] and (lg | sh).sum() == 1
        r = calc(df, "1h", "F9_FVG", combo)
        if side > 0:
            assert r.inv_l[58] == 112.0 and r.tgt_l[58] == 122.0      # b2 = 55: h[53], max(h[54:58]); not the older gap's 101
        else:
            assert r.inv_s[58] == AXIS - 112.0 and r.tgt_s[58] == AXIS - 122.0
        assert first_exit(r, df, 58, side) == 59                    # the close under 112 (the older gap's 101 is not reached)


def path_ote():
    b = filler(40)
    last = b[-1][3]
    seq = [(last, 100.5, 98.6, 99.0),      # 40
           (99.0, 99.2, 97.0, 97.5),       # 41
           (97.5, 97.8, 95.0, 96.0),       # 42: swing low, L = 95.0 (confirmed at 44)
           (96.0, 99.0, 95.9, 98.5),       # 43
           (98.5, 102.0, 98.0, 101.5),     # 44
           (101.5, 105.0, 101.0, 104.5),   # 45
           (104.5, 108.0, 104.0, 107.5),   # 46
           (107.5, 110.0, 107.0, 109.5),   # 47
           (109.5, 111.0, 109.0, 110.5),   # 48
           (110.5, 112.0, 110.0, 111.0),   # 49: swing high, H = 112.0
           (111.0, 111.5, 109.5, 110.0),   # 50
           (110.0, 110.5, 108.0, 108.5),   # 51: confirms the swing high: the leg is born (t = 51), H - L = 17
           (108.5, 108.8, 104.5, 105.0),   # 52
           (105.0, 105.2, 104.0, 104.5),   # 53: low 104.0 above the 62% level 101.46: no touch yet
           (104.5, 104.8, 101.0, 102.0),   # 54: s: low 101.0 <= 101.46, close 102.0 > the 79% level 98.57
           (102.0, 102.2, 98.0, 98.5),     # 55
           (98.5, 98.6, 95.5, 96.0),       # 56: above L
           (96.0, 96.2, 94.0, 94.5)]       # 57: close below L = 95.0
    return mkdf(b + seq)


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f10_ote(side):
    combo = dict(swing_k=2, leg_atr=2.0, leg_max_bars=30)
    base = path_ote()
    df = base if side > 0 else ds_mirror(base)
    atr = FGI.atr(base, 14).to_numpy(float)
    assert 17.0 >= 2.0 * atr[51]                                   # the design: the leg is at least 2 ATR long
    lg, sh = sig(df, "1h", "F10_OTE", combo)
    s = 54
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F10_OTE", combo)
    if side > 0:
        assert (r.inv_l[s], r.tgt_l[s]) == (95.0, 112.0)             # L = the swing low the leg started from, H = its top
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (AXIS - 95.0, AXIS - 112.0)
    assert not r.lx.any() and not r.sx.any()
    assert first_exit(r, df, s, side) == 57                        # 56 closes at 96.0, above 95.0


# ====================================================================================================== oracles
def atr14(df):
    return FGI.atr(df, 14).to_numpy(float)


def pivots(x, k, high):
    """Strict swing highs (or lows) by definition: x[p] beyond the k bars on each side."""
    n = len(x)
    out = []
    for p in range(k, n - k):
        nb = [x[q] for q in range(p - k, p + k + 1) if q != p]
        if (x[p] > max(nb)) if high else (x[p] < min(nb)):
            out.append(p)
    return out


def ote_rows(df, k, leg_atr, leg_max, life=50):
    """(s, side, t, H, L) of every zone that fires, from the text of A.9, in plain loops."""
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    n, atr = len(c), atr14(df)
    ph, pl = pivots(h, k, True), pivots(l, k, False)
    rows = []
    for up in (True, False):
        for p in (ph if up else pl):
            t = p + k
            prior = [q for q in (pl if up else ph) if q + k <= t]             # the last swing confirmed at or before t
            if not prior:
                continue
            q = prior[-1]
            if up:
                H, L = h[p], l[q]
                if not (p - q <= leg_max and H - L >= leg_atr * atr[t]):
                    continue
                rg = H - L
                for s in range(t + 1, min(t + life, n - 1) + 1):
                    if l[s] <= H - 0.62 * rg:                                   # the first touch of the band
                        if not any(h[x] > H for x in range(t + 1, s + 1)) and c[s] > H - 0.79 * rg:
                            rows.append((s, 1, t, H, L))
                        break
            else:
                Lw, H = l[p], h[q]
                if not (p - q <= leg_max and H - Lw >= leg_atr * atr[t]):
                    continue
                rg = H - Lw
                for s in range(t + 1, min(t + life, n - 1) + 1):
                    if h[s] >= Lw + 0.62 * rg:
                        if not any(l[x] < Lw for x in range(t + 1, s + 1)) and c[s] < Lw + 0.79 * rg:
                            rows.append((s, -1, t, H, Lw))
                        break
    return rows


@pytest.mark.parametrize("seed", (1, 2, 3, 5))
def test_ds_oracle_f10_ote_rows_levels_and_the_tie_rule(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    k, la, lm = 2, 1.0, 30
    rows = ote_rows(df, k, la, lm)
    by = {}
    for s, side, t, H, L in rows:
        by.setdefault((s, side), []).append((t, H, L))
    r = calc(df, "1h", "F10_OTE", dict(swing_k=k, leg_atr=la, leg_max_bars=lm))
    lg, sh = sig(df, "1h", "F10_OTE", dict(swing_k=k, leg_atr=la, leg_max_bars=lm))
    raw_l = np.zeros(len(df), bool)
    raw_s = np.zeros(len(df), bool)
    for s, side in by:
        (raw_l if side > 0 else raw_s)[s] = True
    assert ds_same(lg, raw_l & ~raw_s) and ds_same(sh, raw_s & ~raw_l)         # the entry is the rows of A.9 (A.9's test)
    for (s, side), lst in by.items():
        if not ((lg if side > 0 else sh)[s]):
            continue
        t, H, L = max(lst)                                               # the most recently confirmed leg (largest t)
        got = (r.inv_l[s], r.tgt_l[s]) if side > 0 else (r.inv_s[s], r.tgt_s[s])
        assert got == ((L, H) if side > 0 else (H, L))
    assert ds_same(fin(r.inv_l), lg) and ds_same(fin(r.tgt_l), lg) and ds_same(fin(r.inv_s), sh) and ds_same(fin(r.tgt_s), sh)


def fvg_rows(df, x, life):
    """(s, side, b, lo, hi) of every gap whose first touch confirms (close beyond the middle), from the text of A.16."""
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    n, atr = len(c), atr14(df)
    rows = []
    for b in range(2, n):
        up = l[b] > h[b - 2] and (l[b] - h[b - 2]) >= x * atr[b]
        dn = h[b] < l[b - 2] and (l[b - 2] - h[b]) >= x * atr[b]
        if not (up or dn):
            continue
        lo, hi = (h[b - 2], l[b]) if up else (h[b], l[b - 2])
        for s in range(b + 1, min(b + life, n - 1) + 1):
            if (l[s] <= hi) if up else (h[s] >= lo):                  # the first touch decides, whatever the close is
                if (c[s] >= (lo + hi) / 2) if up else (c[s] <= (lo + hi) / 2):
                    rows.append((s, 1 if up else -1, b, lo, hi))
                break
    return rows


FVG_ORACLE = (0.1, 100)           # fvg_min_atr, zone_life: many small gaps that live long, so that several fire on one bar


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_ds_oracle_f9_fvg_rows_levels_and_the_tie_rule(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    x, life = FVG_ORACLE
    rows = fvg_rows(df, x, life)
    by = {}
    for s, side, b, lo, hi in rows:
        by.setdefault((s, side), []).append((b, lo, hi))
    combo = dict(fvg_min_atr=x, zone_life=life)
    r = calc(df, "1h", "F9_FVG", combo)
    lg, sh = sig(df, "1h", "F9_FVG", combo)
    raw_l = np.zeros(len(df), bool)
    raw_s = np.zeros(len(df), bool)
    for s, side in by:
        (raw_l if side > 0 else raw_s)[s] = True
    assert ds_same(lg, raw_l & ~raw_s) and ds_same(sh, raw_s & ~raw_l)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    for (s, side), lst in by.items():
        if not ((lg if side > 0 else sh)[s]):
            continue
        b, lo, hi = max(lst)                                              # the most recently born gap (largest b)
        if side > 0:
            assert (r.inv_l[s], r.tgt_l[s]) == (lo, h[b - 1:s].max())
        else:
            assert (r.inv_s[s], r.tgt_s[s]) == (hi, l[b - 1:s].min())
    assert ds_same(fin(r.inv_l), lg) and ds_same(fin(r.tgt_l), lg) and ds_same(fin(r.inv_s), sh) and ds_same(fin(r.tgt_s), sh)


def test_ds_the_tie_rules_are_exercised_by_these_series():
    """Bars where several zones fire on one side with different levels (so that "the largest t / b" decides something): the
    OTE and FVG oracle series above contain plenty of them (a count of bars, not a result)."""
    n_ote = n_fvg = 0
    for seed in (1, 2, 3, 5):
        by = {}
        for s, side, t, H, L in ote_rows(rand_df(seed, 2500, "1h", vol=0.012), 2, 1.0, 30):
            by.setdefault((s, side), []).append((t, H, L))
        n_ote += sum(len(v) > 1 and len({(H, L) for _t, H, L in v}) > 1 and (s, -side) not in by for (s, side), v in by.items())
    for seed in (1, 2, 3):
        by = {}
        for s, side, b, lo, hi in fvg_rows(rand_df(seed, 2500, "1h", vol=0.012), *FVG_ORACLE):
            by.setdefault((s, side), []).append((b, lo, hi))
        n_fvg += sum(len(v) > 1 and len({(lo, hi) for _b, lo, hi in v}) > 1 and (s, -side) not in by for (s, side), v in by.items())
    assert n_ote >= 5 and n_fvg >= 5


def pvt_pairs(df, k, mx):
    """(side, a, b) of every ok pair of consecutive swing pivots, from the text of A.12, in plain loops."""
    h, l, c, v = (df[x].to_numpy() for x in ("high", "low", "close", "volume"))
    pvt = np.cumsum([0.0] + [v[i] * (c[i] / c[i - 1] - 1) for i in range(1, len(c))])
    out = []
    pl, ph = pivots(l, k, False), pivots(h, k, True)
    for a, b in zip(pl[:-1], pl[1:]):
        if b - a <= mx and l[b] < l[a] and pvt[b] > pvt[a]:
            out.append((1, a, b))
    for a, b in zip(ph[:-1], ph[1:]):
        if b - a <= mx and h[b] > h[a] and pvt[b] < pvt[a]:
            out.append((-1, a, b))
    return out


@pytest.mark.parametrize("seed", (1, 2, 3, 4))
def test_ds_oracle_f1_pvt_div_pairs_and_levels(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    k, mx = 3, 40
    pairs = pvt_pairs(df, k, mx)
    combo = dict(swing_k=k, div_max_bars=mx)
    r = calc(df, "1h", "F1_PVT_DIV", combo)
    lg, sh = sig(df, "1h", "F1_PVT_DIV", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    raw_l = np.zeros(len(df), bool)
    raw_s = np.zeros(len(df), bool)
    for side, a, b in pairs:
        (raw_l if side > 0 else raw_s)[b + k] = True
    assert ds_same(lg, raw_l & ~raw_s) and ds_same(sh, raw_s & ~raw_l)
    seen = 0
    for side, a, b in pairs:
        s = b + k
        if side > 0 and lg[s]:
            assert (r.inv_l[s], r.tgt_l[s]) == (l[b], h[a:b + 1].max())
            seen += 1
        if side < 0 and sh[s]:
            assert (r.inv_s[s], r.tgt_s[s]) == (h[b], l[a:b + 1].min())
            seen += 1
    assert seen >= 10
    assert ds_same(fin(r.inv_l), lg) and ds_same(fin(r.tgt_l), lg) and ds_same(fin(r.inv_s), sh) and ds_same(fin(r.tgt_s), sh)


@pytest.mark.parametrize("seed", (1, 2))
def test_ds_oracle_f11_tsoup_entry_and_levels(seed):
    df = rand_df(seed, 2500, "4h", vol=0.012)
    w, age = 10, 2
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    n = len(c)
    exp_l, exp_s = np.zeros(n, bool), np.zeros(n, bool)
    for s in range(w, n):
        Lw, Hw = l[s - w:s].min(), h[s - w:s].max()
        age_lo = s - (s - w + int(np.argmin(l[s - w:s])))
        age_hi = s - (s - w + int(np.argmax(h[s - w:s])))
        exp_l[s] = l[s] < Lw and c[s] > Lw and age_lo >= age
        exp_s[s] = h[s] > Hw and c[s] < Hw and age_hi >= age
    both = exp_l & exp_s
    exp_l, exp_s = exp_l & ~both, exp_s & ~both
    combo = dict(tsoup_len=w, min_age=age)
    lg, sh = sig(df, "4h", "F11_TSOUP", combo)
    assert ds_same(lg, exp_l) and ds_same(sh, exp_s)
    r = calc(df, "4h", "F11_TSOUP", combo)
    for s in np.flatnonzero(lg):
        assert (r.inv_l[s], r.tgt_l[s]) == (l[s], (h[s - w:s].max() + l[s - w:s].min()) / 2)
    for s in np.flatnonzero(sh):
        assert (r.inv_s[s], r.tgt_s[s]) == (h[s], (h[s - w:s].max() + l[s - w:s].min()) / 2)
    assert lg.sum() >= 20 and sh.sum() >= 20
    assert ds_same(fin(r.inv_l), lg) and ds_same(fin(r.tgt_l), lg) and ds_same(fin(r.inv_s), sh) and ds_same(fin(r.tgt_s), sh)


@pytest.mark.parametrize("seed", (1, 2))
def test_ds_oracle_f5_box_levels(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    combo = dict(box_len=20, adx_max=40.0, edge=0.3, width_atr=1.0)
    lg, sh = sig(df, "1h", "F5_BOX", combo)
    r = calc(df, "1h", "F5_BOX", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    assert lg.sum() >= 10 and sh.sum() >= 10
    for s in np.flatnonzero(lg):
        assert (r.inv_l[s], r.tgt_l[s]) == (l[s - 20:s].min(), h[s - 20:s].max())
    for s in np.flatnonzero(sh):
        assert (r.inv_s[s], r.tgt_s[s]) == (h[s - 20:s].max(), l[s - 20:s].min())
    assert ds_same(fin(r.inv_l), lg) and ds_same(fin(r.tgt_l), lg) and ds_same(fin(r.inv_s), sh) and ds_same(fin(r.tgt_s), sh)


def rf_dir_ref(c, period, mult):
    """The range filter of A.14 in plain loops: r = mult x EMA(2p - 1) of EMA(p) of |close change|; the filter steps up to
    c - r when c - r > f and down to c + r when c + r < f; the direction is the sign of its last step."""
    c = np.asarray(c, float)
    a1, a2 = 2.0 / (period + 1), 2.0 / (2 * period - 1 + 1)
    e1 = e2 = 0.0
    f, dr = c[0], 0
    out = np.zeros(len(c))
    for i in range(len(c)):
        d = abs(c[i] - c[i - 1]) if i else 0.0
        e1 = d if i == 0 else a1 * d + (1 - a1) * e1
        e2 = e1 if i == 0 else a2 * e1 + (1 - a2) * e2
        if i == 0:
            continue
        r = mult * e2
        nf = c[i] - r if c[i] - r > f else (c[i] + r if c[i] + r < f else f)
        dr = 1 if nf > f else (-1 if nf < f else dr)
        f = nf
        out[i] = dr
    return out


def ha_ref(o, h, l, c):
    """Heikin-Ashi candle colour: 1 up, 0 down, 0.5 flat (HA close (o+h+l+c)/4; HA open = mean of the previous HA open and close)."""
    n = len(c)
    hac = (o + h + l + c) / 4
    hao = np.zeros(n)
    hao[0] = (o[0] + c[0]) / 2
    for i in range(1, n):
        hao[i] = (hao[i - 1] + hac[i - 1]) / 2
    return np.where(hac > hao, 1.0, np.where(hac < hao, 0.0, 0.5))


def hha_ref(df, ratio):
    """The higher-timeframe Heikin-Ashi colour at each chart bar: the last HTF bar (``ratio`` chart bars, aligned to the first
    bar) that has closed at or before the chart bar's close; NaN before the first one has."""
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    m = len(c) // ratio + (len(c) % ratio > 0)
    ho = np.array([o[k * ratio] for k in range(m)])
    hh = np.array([h[k * ratio:(k + 1) * ratio].max() for k in range(m)])
    hl = np.array([l[k * ratio:(k + 1) * ratio].min() for k in range(m)])
    hc = np.array([c[min((k + 1) * ratio, len(c)) - 1] for k in range(m)])
    col = ha_ref(ho, hh, hl, hc)
    out = np.full(len(c), np.nan)
    for i in range(len(c)):
        j = (i + 1) // ratio - 1                      # HTF bar j closes after (j + 1) x ratio chart bars
        if j >= 0:
            out[i] = col[j]
    return out


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_ds_oracle_f7_rf_only(seed):
    df = rand_df(seed, 1500, "1h", vol=0.01)
    combo = dict(rf_period=10, rf_mult=1.5)
    rf = rf_dir_ref(df["close"].to_numpy(), 10, 1.5)
    assert ds_same(rf, D.range_filter_dir(df["close"].to_numpy(), 10, 1.5))      # the library's filter is the text's filter
    r = calc(df, "1h", "F7_RF_ONLY", combo)
    assert ds_same(r.lx, rf == -1) and ds_same(r.sx, rf == 1)
    assert not fin(r.inv_l).any() and not fin(r.inv_s).any() and not fin(r.tgt_l).any() and not fin(r.tgt_s).any()
    lg, sh = sig(df, "1h", "F7_RF_ONLY", combo)
    prev = np.r_[0.0, rf[:-1]]
    assert ds_same(lg, (rf == 1) & (prev == -1)) and ds_same(sh, (rf == -1) & (prev == 1))     # the entry is the direction turn


@pytest.mark.parametrize("tf,ratio,seed", (("1h", 4, 1), ("1h", 4, 2), ("4h", 6, 3)))
def test_ds_oracle_f7_rf_triple(tf, ratio, seed):
    df = rand_df(seed, 1500, tf, vol=0.01)
    combo = dict(rf_period=10, rf_mult=1.5)
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    rf, ha, hha = rf_dir_ref(c, 10, 1.5), ha_ref(o, h, l, c), hha_ref(df, ratio)
    assert np.isnan(hha[:ratio - 1]).all() and not np.isnan(hha[ratio - 1:]).any()
    r = calc(df, tf, "F7_RF_TRIPLE", combo)
    with np.errstate(invalid="ignore"):
        exp_l = (rf == -1) | (ha == 0) | (hha == 0)                # a NaN or a flat 0.5 compares False: it does not fire
        exp_s = (rf == 1) | (ha == 1) | (hha == 1)
    assert ds_same(r.lx, exp_l) and ds_same(r.sx, exp_s)
    assert not fin(r.inv_l).any() and not fin(r.tgt_l).any() and not fin(r.inv_s).any() and not fin(r.tgt_s).any()
    lg, sh = sig(df, tf, "F7_RF_TRIPLE", combo)
    up, dn = (rf == 1) & (ha == 1) & (hha == 1), (rf == -1) & (ha == 0) & (hha == 0)
    assert ds_same(lg, up & ~np.r_[False, up[:-1]]) and ds_same(sh, dn & ~np.r_[False, dn[:-1]])       # first bar of a run
    for s in np.flatnonzero(lg):                  # the first end is never later than the opposite signal
        j = first_true_after(r.lx, s)
        if j is not None:
            assert j <= (first_true_after(sh, s) or 10 ** 9)


def test_ds_f7_rf_triple_each_of_the_three_inputs_can_end_a_trade_alone():
    """The OR of A.15 is exercised: across series there are long entries whose first exit is caused by the range filter alone,
    by the chart Heikin-Ashi alone, and by the higher-timeframe Heikin-Ashi alone (and the same for shorts)."""
    seen = {1: set(), -1: set()}
    for seed in range(1, 9):
        df = rand_df(seed, 1500, "1h", vol=0.01)
        o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
        rf, ha, hha = rf_dir_ref(c, 10, 1.5), ha_ref(o, h, l, c), hha_ref(df, 4)
        r = calc(df, "1h", "F7_RF_TRIPLE", dict(rf_period=10, rf_mult=1.5))
        lg, sh = sig(df, "1h", "F7_RF_TRIPLE", dict(rf_period=10, rf_mult=1.5))
        for side, mine, comp, turned in ((1, lg, r.lx, (rf == -1, ha == 0, hha == 0)),
                                         (-1, sh, r.sx, (rf == 1, ha == 1, hha == 1))):
            for s in np.flatnonzero(mine):
                j = first_true_after(comp, s)
                if j is not None:
                    flags = tuple(bool(t[j]) for t in turned)
                    if sum(flags) == 1:
                        seen[side].add(flags.index(True))
    assert seen[1] == {0, 1, 2} and seen[-1] == {0, 1, 2}


def test_ds_f7_rf_triple_a_missing_higher_timeframe_value_does_not_fire():
    df = rand_df(5, 60, "1h", vol=0.01)
    r = calc(df, "1h", "F7_RF_TRIPLE", dict(rf_period=10, rf_mult=1.5))
    c, o, h, l = (df[x].to_numpy() for x in ("close", "open", "high", "low"))
    rf, ha = rf_dir_ref(c, 10, 1.5), ha_ref(o, h, l, c)
    assert ds_same(r.lx[:3], ((rf == -1) | (ha == 0))[:3])             # bars 0-2: no 4h bar has closed yet (NaN): only rf and ha count
    assert ds_same(r.sx[:3], ((rf == 1) | (ha == 1))[:3])


def path_rf(side=1):
    """100 down to 80, up to 120, down to 90, up to 110 in 25-bar legs."""
    pts = [(25, 80.0), (25, 120.0), (25, 90.0), (25, 110.0)]
    out, prev = [], 100.0
    for n, tgt in pts:
        for k in range(1, n + 1):
            c = prev + (tgt - prev) * k / n
            o = out[-1][3] if out else 100.0
            out.append((o, max(o, c) + 0.4, min(o, c) - 0.4, c))
        prev = tgt
    return mkdf(out)


@pytest.mark.parametrize("side", (1, -1))
def test_ds_hand_f7_rf_only_the_exit_is_the_opposite_signal(side):
    combo = dict(rf_period=5, rf_mult=1.5)
    df = path_rf() if side > 0 else ds_mirror(path_rf())
    r = calc(df, "1h", "F7_RF_ONLY", combo)
    lg, sh = sig(df, "1h", "F7_RF_ONLY", combo)
    mine, opp = (lg, sh) if side > 0 else (sh, lg)
    assert mine.sum() >= 1 and opp.sum() >= 1
    n_exits = 0
    for s in np.flatnonzero(mine):
        j = first_exit(r, df, s, side)
        assert j == first_true_after(opp, s) and (j is None or opp[j])
        n_exits += j is not None
    assert n_exits >= 1
    rf = rf_dir_ref(df["close"].to_numpy(), 5, 1.5)
    assert ds_same(r.lx, rf == -1) and ds_same(r.sx, rf == 1)


# ====================================================================================================== properties
@pytest.mark.parametrize("name", ND.NAMES)
@pytest.mark.parametrize("seed", (1, 2))
def test_ds_every_signal_bar_has_its_levels_and_the_own_side_is_quiet(name, seed):
    tf, combo = DENSE[name]
    df = rand_df(seed, 2500, tf, vol=0.012)
    lg, sh = sig(df, tf, name, combo)
    ND.native(df, tf, name, combo, None, "BTCUSD", expect=(lg, sh))           # T6: the asserted equality with ds_defs signals
    r = calc(df, tf, name, combo)
    assert lg.sum() >= 3 and sh.sum() >= 3
    assert not r.lx[lg].any() and not r.sx[sh].any()                             # A.0: false at their own signal bars
    if name in LEVEL_ONLY:
        for arr, sg in ((r.inv_l, lg), (r.tgt_l, lg), (r.inv_s, sh), (r.tgt_s, sh)):
            assert ds_same(fin(arr), sg)                                          # a level and a target on every signal bar, only there
        assert not r.lx.any() and not r.sx.any()
        # the invalidation is on the losing side of the signal bar's close, except where the entry makes it impossible (A.9-A.16)
        c = df["close"].to_numpy()
        assert (c[lg] >= r.inv_l[lg]).all() and (c[sh] <= r.inv_s[sh]).all()
    elif name == "F12_MSS_DISP":
        assert not fin(r.inv_l).any() and not fin(r.inv_s).any()
        assert ((~fin(r.tgt_l)) | lg).all() and ((~fin(r.tgt_s)) | sh).all()
    else:
        for arr in (r.inv_l, r.inv_s, r.tgt_l, r.tgt_s):
            assert not fin(arr).any()


@pytest.mark.parametrize("name", ND.NAMES)
def test_ds_other_side_component_at_a_signal_bar(name):
    """A.0 coin-flip note: a position on the other side uses its own side's component under rule C3. For the range-filter
    strategies that component is already true at the strategy's own signal bar, so a flipped position must wait."""
    tf, combo = DENSE[name]
    df = rand_df(2, 2500, tf, vol=0.012)
    lg, sh = sig(df, tf, name, combo)
    r = calc(df, tf, name, combo)
    if name in ("F7_RF_ONLY", "F7_RF_TRIPLE"):
        assert r.sx[lg].all() and r.lx[sh].all()
    if name in LEVEL_ONLY:
        assert not r.sx[lg].any() and not r.lx[sh].any()


@pytest.mark.parametrize("name", SYMMETRIC)
def test_ds_mirror_symmetry(name):
    """Turning the bars upside down turns every long into a short with the mirrored levels, targets and components."""
    tf, combo = DENSE[name]
    df = rand_df(3, 2000, tf, vol=0.012)
    mdf = ds_mirror(df)
    lg, sh = sig(df, tf, name, combo)
    mlg, msh = sig(mdf, tf, name, combo)
    assert ds_same(lg, msh) and ds_same(sh, mlg) and lg.sum() >= 3
    r, mr = calc(df, tf, name, combo), calc(mdf, tf, name, combo)
    assert ds_same(r.lx, mr.sx) and ds_same(r.sx, mr.lx)
    assert ds_same(r.z_l, mr.z_s) and ds_same(r.z_s, mr.z_l)                    # the live-level flags mirror too
    for a, b in ((r.inv_l, mr.inv_s), (r.inv_s, mr.inv_l), (r.tgt_l, mr.tgt_s), (r.tgt_s, mr.tgt_l)):
        assert ds_same(fin(a), fin(b))
        assert np.allclose(AXIS - a[fin(a)], b[fin(b)], rtol=0, atol=1e-9)


def cut_points(df, tf, name, combo, n_signal=4):
    lg, sh = sig(df, tf, name, combo)
    sigs = np.flatnonzero(lg | sh)
    pick = sigs[np.linspace(0, len(sigs) - 1, n_signal).astype(int)] if len(sigs) else np.array([], int)
    return sorted({int(i) for i in pick if i >= 100} | {len(df) // 3, len(df) // 2, len(df) - 5})


def arrs(r):
    """The six arrays of A.0 and the two z flags of a native_ds result."""
    return [*r, r.z_l, r.z_s]


def upto(r, i):
    return [a[:i + 1] for a in arrs(r)]


@pytest.mark.parametrize("name", ND.NAMES)
def test_ds_causality_prefix_and_perturbed_future(name):
    """T3 / T5: the arrays at bars <= i do not change when the bars after i are cut off or replaced by other prices and volumes."""
    tf, combo = DENSE[name]
    df = rand_df(7, 1800, tf, vol=0.012)
    full = calc(df, tf, name, combo)
    for i in cut_points(df, tf, name, combo):
        cut = calc(prefix(df, i), tf, name, combo)
        assert all(ds_same(a, b) for a, b in zip(upto(full, i), upto(cut, i))), (name, i, "prefix")
        for seed in (11, 12):
            pert = calc(perturb_after(df, i, seed), tf, name, combo)
            assert all(ds_same(a, b) for a, b in zip(upto(full, i), upto(pert, i))), (name, i, seed, "perturbed")


@pytest.mark.parametrize("tf,combo", (("1h", dict(rf_period=10, rf_mult=1.5)), ("4h", dict(rf_period=8, rf_mult=1.2))))
def test_ds_causality_of_the_higher_timeframe_inputs_of_f7_rf_triple(tf, combo):
    """Cutting at every chart bar of one higher-timeframe bar and the bar after it: the HTF colour is taken only from closed bars."""
    df = rand_df(9, 900, tf, vol=0.012)
    full = calc(df, tf, "F7_RF_TRIPLE", combo)
    for i in range(300, 330):
        cut = calc(prefix(df, i), tf, "F7_RF_TRIPLE", combo)
        assert all(ds_same(a, b) for a, b in zip(upto(full, i), upto(cut, i))), i


def test_ds_f7_rf_only_is_the_opposite_signal_exit():
    """Known limit 11: for F7_RF_ONLY the strategy's own exit (F11) is its opposite signal (F3): the first bar after a signal at
    which the own-side component is true is the first opposite signal, and there are no levels or targets, so F11.a = F3.a
    (both keep the pick's take-profit) and F11.b = F3.b (neither has one)."""
    n_checked = 0
    for seed, (tf, combo) in ((1, ("1h", dict(rf_period=10, rf_mult=1.5))), (2, ("30m", dict(rf_period=6, rf_mult=1.0))),
                              (3, ("4h", dict(rf_period=33, rf_mult=1.0)))):
        df = rand_df(seed, 2500, tf, vol=0.012)
        lg, sh = sig(df, tf, "F7_RF_ONLY", combo)
        r = calc(df, tf, "F7_RF_ONLY", combo)
        assert not fin(r.inv_l).any() and not fin(r.inv_s).any() and not fin(r.tgt_l).any() and not fin(r.tgt_s).any()
        for side, mine, opp in ((1, lg, sh), (-1, sh, lg)):
            for s in np.flatnonzero(mine):
                assert first_exit(r, df, s, side) == first_true_after(opp, s)
                n_checked += 1
    assert n_checked >= 100


def test_ds_f7_rf_triple_is_not_the_opposite_signal_exit():
    """A.15: one turned input ends the trade, long before all three have turned (which is the opposite signal)."""
    df = rand_df(1, 2500, "1h", vol=0.012)
    combo = dict(rf_period=10, rf_mult=1.5)
    lg, sh = sig(df, "1h", "F7_RF_TRIPLE", combo)
    r = calc(df, "1h", "F7_RF_TRIPLE", combo)
    earlier = later = 0
    for s in np.flatnonzero(lg):
        j, o = first_true_after(r.lx, s), first_true_after(sh, s)
        if j is not None and o is not None:
            assert j <= o
            earlier += j < o
            later += j > o
    assert earlier >= 10 and later == 0


# ====================================================================================================== python -O
_DASH_O_SCRIPT = r"""
import sys
if __debug__:
    print("NOT-DASH-O")
    sys.exit(3)
import numpy as np, pandas as pd
sys.path[:0] = [%(here)r, %(root)r]
import native, native_ds
rng = np.random.default_rng(5)
n = 700
c = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
o = np.r_[c[0], c[:-1]]
h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
ts = pd.to_datetime(1640995200000 + np.arange(n) * 3600000, unit="ms", utc=True)
df = pd.DataFrame(dict(ts=ts, open=o, high=h, low=l, close=c, volume=rng.uniform(1, 5, n)))
df.attrs["tf"] = "1h"
D = native_ds.ds_module()
combo = dict(swing_k=2, disp_atr=0.3)
lg, sh = (np.asarray(x, bool) for x in D.signals(df, "1h", "F12_MSS_DISP", ctx=None, coin="BTCUSD", cache={}, **combo))
r = native_ds.native(df, "1h", "F12_MSS_DISP", combo, None, "BTCUSD", expect=(lg, sh))
assert_ok = r.z_l.any() and lg.any()
if not assert_ok:
    print("VACUOUS")
    sys.exit(4)
for bad in ((~lg, sh), (lg, ~sh)):
    try:
        native_ds.native(df, "1h", "F12_MSS_DISP", combo, None, "BTCUSD", expect=bad)
    except AssertionError:
        print("DS-RAISED")
    else:
        print("DS-SILENT")
try:
    native_ds._need(False, "x")
except AssertionError:
    print("NEED-RAISED")
M = native.strategy_module("OBV_S")
cb = dict(obv_ma_len=5)
lo, sh2 = (np.asarray(x, bool) for x in M.signals(df, "1h", **cb))
native.native_arrays("OBV_S", df, "1h", cb, expect=(lo, sh2))
try:
    native.native_arrays("OBV_S", df, "1h", cb, expect=(~lo, sh2))
except AssertionError:
    print("CORE-RAISED")
else:
    print("CORE-SILENT")
"""


def test_ds_safeguards_survive_python_dash_O():
    """Under ``python -O`` a bare assert disappears; the explicit raises of the two modules (``expect``, the recovery checks) must not."""
    out = subprocess.run([sys.executable, "-O", "-c", _DASH_O_SCRIPT % dict(here=HERE, root=ROOT)], capture_output=True, text=True,
                         timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    lines = out.stdout.split()
    assert lines.count("DS-RAISED") == 2 and "DS-SILENT" not in lines
    assert "NEED-RAISED" in lines and "CORE-RAISED" in lines and "CORE-SILENT" not in lines


# ====================================================================================================== real data (select period)
def real_inputs(real, sym, tf):
    """(chart frame, ctx, coin) of the select-period bars; ``real`` is the module's ``real`` fixture."""
    df, close_ms = R.frame(real.dir, sym, tf)
    assert close_ms.max() <= CUT_MS                                          # no chart bar closes after the cut
    ctx = None if sym == "BTCUSDT" else {"BTCUSD": R.frame(real.dir, "BTCUSDT", tf)[0]}
    return df, ctx, sym[:-1]


DS_PICKS = ds_picks() if os.path.exists(CANDIDATES) else []


@pytest.mark.parametrize("pick", DS_PICKS, ids=[p["id"] for p in DS_PICKS])
@pytest.mark.parametrize("sym", ("BTCUSDT", "DOGEUSDT"))
def test_ds_real_parity_with_run_signals_levels_and_quiet_own_side(real, pick, sym):
    """T6: native_ds reproduces run.signals bar for bar on the select-period bars (its own call is asserted equal), every
    final signal bar of a level strategy has its levels, the own side is quiet at its signal bars. Booleans only."""
    name, tf, combo = pick["name"], pick["tf"], pick["combo"]
    df, ctx, coin = real_inputs(real, sym, tf)
    lg, sh = R.signals(real.dir, "ds", name, sym, tf, combo)
    r = ND.native(df, tf, name, combo, ctx, coin, expect=(lg, sh))
    assert not r.lx[lg].any() and not r.sx[sh].any()
    if name in LEVEL_ONLY:
        for arr, sg in ((r.inv_l, lg), (r.tgt_l, lg), (r.inv_s, sh), (r.tgt_s, sh)):
            assert ds_same(fin(arr), sg)
    elif name == "F12_MSS_DISP":
        assert not fin(r.inv_l).any() and not fin(r.inv_s).any()
        assert ((~fin(r.tgt_l)) | lg).all() and ((~fin(r.tgt_s)) | sh).all()
        zl, zs = engine_latches(df, D._resolve(name, combo)["swing_k"])           # the live-level flags, replayed from the raw bars
        assert ds_same(r.z_l, zl) and ds_same(r.z_s, zs)
        assert not (r.lx & ~r.z_l).any() and not (r.sx & ~r.z_s).any()
    else:
        assert not any(fin(a).any() for a in (r.inv_l, r.inv_s, r.tgt_l, r.tgt_s))
    if name == "F7_RF_ONLY":                                                   # Known limit 11 on the real picks
        for side, mine, opp in ((1, lg, sh), (-1, sh, lg)):
            for s in np.flatnonzero(mine)[:200]:
                assert first_exit(r, df, s, side) == first_true_after(opp, s)


@pytest.mark.parametrize("pick", DS_PICKS, ids=[p["id"] for p in DS_PICKS])
def test_ds_real_causality(real, pick):
    """T3 / T5 on real select-period bars (BTC): cutting the frame, or replacing the bars after a cut with other prices, leaves
    the arrays at and before the cut unchanged."""
    name, tf, combo = pick["name"], pick["tf"], pick["combo"]
    df, ctx, coin = real_inputs(real, "BTCUSDT", tf)
    n = len(df)
    full = ND.native(df, tf, name, combo, ctx, coin)
    lg, sh = sig(df, tf, name, combo, ctx, coin)
    sigs = np.flatnonzero(lg | sh)
    cuts = {int(n * 0.45), int(n * 0.8)}
    if len(sigs):
        cuts |= {int(sigs[len(sigs) // 2]), int(sigs[-1])}
    for i in sorted(cuts):
        cut = ND.native(prefix(df, i), tf, name, combo, ctx_cut(ctx, i), coin)
        assert all(ds_same(a, b) for a, b in zip(upto(full, i), upto(cut, i))), (pick["id"], i, "prefix")
    i = int(sigs[len(sigs) // 2]) if len(sigs) else n // 2
    pert = ND.native(perturb_after(df, i, 5), tf, name, combo, ctx, coin)
    assert all(ds_same(a, b) for a, b in zip(upto(full, i), upto(pert, i))), (pick["id"], i, "perturbed")


def ctx_cut(ctx, i):
    return None if ctx is None else {"BTCUSD": prefix(ctx["BTCUSD"], i)}
