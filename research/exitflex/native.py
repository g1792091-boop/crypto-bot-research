"""exitflex F11: the strategy's own exit, eight CORE strategies (research/exitflex/PREREG_EXITFLEX.md, Appendix A.1-A.8,
common rules C1-C8 of A.0).

    native_arrays(name, df, tf, combo) -> {
        "comp_long":  [(kind, array), ...],   # kind 'state' or 'event'; one array value per chart bar of ``df``
        "comp_short": [(kind, array), ...],
        "lvl_long", "lvl_short":  float arrays, the per-signal invalidation level, indexed by the signal bar, NaN elsewhere
        "tgt_long", "tgt_short":  float arrays, the per-signal native target, indexed by the signal bar, NaN elsewhere
        "names_long", "names_short": [str, ...]  (extra, for tests and reports: one label per component)
    }

What the arrays mean (Appendix A.0, rules C1-C8; the kernel side is kernel_x.py, not this file)
* A long position exits (RULE) at a pick close i > i0 when any of its components fires: a 'state' component fires where
  it is true once it has been false at some pick close in [i0, i - 1] (C3); an 'event' component fires where it is true on
  a bar after i0. The level array, when present, is one more state component: the close is beyond the level (below it for
  a long, above it for a short), armed at i0 when the close is not beyond it. The short side mirrors. Nothing here
  decides when a check happens (C1) and there is no confirmation bar (C2).
* ``lvl_*`` / ``tgt_*`` are fixed at the signal bar i0 from bars <= i0 and never move (C5). A NaN level or target means
  none (C7). A target is used only when it lies beyond the fill (C6, the kernel's TP_STRUCT rule); that test is the
  kernel's, not this file's.
* Only N13_3OUTSIDE and N19_FIB_CHOP have a level; only they have a target. For the other six strategies the four
  level / target arrays are all NaN (none).

The strategy module is ``run.core_module(name)`` (hash-checked against DEFS_BC.sha256, memo-installed), the same object
``run.signals`` uses, and only that module's own indicator functions are called (Appendix A, "Core code"). The frame is
the pick's chart frame (``run.frame`` / ``run.build_frame``: columns ts, open, high, low, close, volume).

DECISIONS (Appendix A is followed literally; where it is ambiguous, the reading closest to the strategy's own code)
D1  Component arrays are float64 with 1.0 = true, 0.0 = false and NaN = unknown, not bool. Reason: rule C7 says that a
    NaN input at a bar means the component neither fires nor arms there, and a bool array cannot say "does not arm"
    (False arms a state component under C3). kernel_x.register_f11 and data_x._tri take exactly this ("booleans, or floats
    with NaN for 'neither fires nor arms'"). ``as_bool(array)`` is the plain boolean view (NaN -> False) and equals
    the boolean formulas written in Appendix A (for example N09's ``fin & ~long_state``, where the Appendix's fin guard
    gives False at a non-finite bar and C7 adds that such a bar does not arm). A bar is unknown for a component when any
    input series of that component is not finite there:
        DOGE    state: ema_fast, ema_slow; event: K, D and their values one bar earlier
        N03     EMA leg: both EMAs; ADX leg: ADX
        N09     lips, teeth, jaw, Aroon up and down (the Appendix's ``fin``)
        N10     PSAR leg: the direction; candle leg: HA open, high, low, close and the wick tolerance
        N13     none (the event is a boolean flag)
        N19     the slope
        OBV_S   OBV and its SMA
        S4      mean-line leg: close and the Bollinger middle; power leg: the bull-bear power
    Warm-up bars are unknown for the same reason; no signal can lie there, so nothing changes in practice.
D2  A level test is not in the component list: the level is the ``lvl_*`` array (kernel_x treats "the close is beyond the
    level" as one more state component of that position, armed at i0 when the close is not beyond it). Appendix A.5 and A.6
    list the level test first among the components; it is carried by the level array here. A strategy without a level or target gets
    all-NaN float arrays (never None), so every key has len(df) entries.
D3  Which bars carry a level: the bars where the strategy's own entry flag of that side is true, taken from the strategy
    module's ``signals`` (= ``run.signals`` core branch: ``np.asarray(lo, bool)`` of the same call). A signal bar whose
    level or target is not finite gets NaN (C7).
D4  N13_3OUTSIDE: the breakout masks are recomputed with the module's own helpers (``_sh``, ``_roll``, ``shift_bool``,
    ``fg.atr``, ``FIRST_LAG``, ``LAGS``) exactly as ``M.signals`` does inline, and native_arrays raises if their OR
    (short & ~long) differs from ``M.signals`` at any bar (Appendix A.5, T6). Per signal the lag is the one whose mask is
    true; lag 1 wins when both are (the later assignment of ports12.n13's loop over LAGS = (2, 1)). PH = ph3[i0 - lag],
    PL = pl3[i0 - lag]. Long: level PL, target PH + (PH - PL). Short: level PH, target PL - (PH - PL), NaN when <= 0.
    The two masks cannot both be true for one side (a pattern at j and at j - 1 would need bar j - 2 to be both bearish and
    bullish), so "lag 1 wins" is a safeguard; it is kept because Appendix A.5 states it.
D5  N19_FIB_CHOP: hh, ll, line_l, line_s, atr, base and slope are the module's own expressions (Appendix A.6). Long: level
    line_l[i0], target hh[i0]; short: level line_s[i0], target ll[i0]. No level or target where R = hh - ll <= 0 (A.6 edge
    cases). As a guard native_arrays also re-derives the module's entry from these arrays and raises on any difference
    (this adds no output; it protects against a wrong copy of the module's expressions).
D6  DOGE: the K / D cross uses the locked convention ``doge_strategy.DEFAULT['cross']`` ('le'). native_arrays asserts
    that (state | event) equals the source's ``long_exit`` (``short_exit``) bar for bar (Appendix A.1). The event
    component is unknown where K, D or their previous values are not finite.
D7  N09_ALLIG_AROON: ``fin`` = lips, teeth, jaw, Aroon up and Aroon down all finite; the component is 1.0 / 0.0 where fin
    (``~long_state`` / ``~short_state``) and NaN elsewhere (see D1).
D8  N10_HA_PSAR: ``tol``, ``body_min`` and ``body_max`` are built as in ``M.signals``; the wick test is ``<=`` as in the
    entry. The PSAR leg is unknown where ``pdir`` is NaN (bar 0), the candle leg where any Heikin-Ashi value is NaN.
D9  Frame handling: modules that call ``df.reset_index(drop=True)`` (N13, N19, S4) are given the reset frame; for the
    others the frame is used as it comes (positional arrays either way). An empty frame returns empty arrays. ``combo``
    None means the module's default combo. The chart frames start where the study's frames start; HA open, PSAR and the
    EMAs depend on the first bar, as the entries do (A.4), so the league computes them on the same frames.
D10 ``run`` is imported from research/fullgrid/run.py under the module name ``run`` (as data_x.fg() does), so that
    ``run.core_module`` and the memo are the objects the study uses.
D11 No new tunable number is added anywhere; the only constants are the Appendix's (the measured-move projection 1 x the
    pattern height of N13).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FG = os.path.join(ROOT, "research", "fullgrid")

STATE, EVENT = "state", "event"

CORE = ("DOGE", "N03_ADX_GC", "N09_ALLIG_AROON", "N10_HA_PSAR", "N13_3OUTSIDE", "N19_FIB_CHOP", "OBV_S", "S4_BB_BBP")

# kinds and labels of the components of each strategy (long, short), in the order of Appendix A; ``level`` / ``target``:
# whether the strategy has a per-signal invalidation level / native target.
SPEC = {
    "DOGE": {"long": ((STATE, "ema_fast < ema_slow"), (EVENT, "StochRSI K crosses below D")),
             "short": ((STATE, "ema_fast > ema_slow"), (EVENT, "StochRSI K crosses above D")),
             "level": False, "target": False},
    "N03_ADX_GC": {"long": ((STATE, "ema_fast < ema_slow"), (STATE, "ADX < adx_level")),
                   "short": ((STATE, "ema_fast > ema_slow"), (STATE, "ADX < adx_level")),
                   "level": False, "target": False},
    "N09_ALLIG_AROON": {"long": ((STATE, "not (lips > teeth, lips > jaw, up >= down)"),),
                        "short": ((STATE, "not (lips < teeth, lips < jaw, down >= up)"),),
                        "level": False, "target": False},
    "N10_HA_PSAR": {"long": ((STATE, "PSAR direction down"), (STATE, "strong red HA candle, no upper wick")),
                    "short": ((STATE, "PSAR direction up"), (STATE, "strong green HA candle, no lower wick")),
                    "level": False, "target": False},
    "N13_3OUTSIDE": {"long": ((EVENT, "own short signal"),), "short": ((EVENT, "own long signal"),),
                     "level": True, "target": True},
    "N19_FIB_CHOP": {"long": ((STATE, "slope <= -slope_thr"),), "short": ((STATE, "slope >= slope_thr"),),
                     "level": True, "target": True},
    "OBV_S": {"long": ((STATE, "OBV < SMA(OBV)"),), "short": ((STATE, "OBV > SMA(OBV)"),),
              "level": False, "target": False},
    "S4_BB_BBP": {"long": ((STATE, "close < Bollinger mid"), (STATE, "bull-bear power < 0")),
                  "short": ((STATE, "close > Bollinger mid"), (STATE, "bull-bear power > 0")),
                  "level": False, "target": False},
}


# ------------------------------------------------------------------ the study's modules
_FGR: dict = {}


def fg():
    """research/fullgrid/run.py as module ``run`` (the name sizing.py and data_x.fg() use)."""
    if "run" not in _FGR:
        if FG not in sys.path:
            sys.path.insert(0, FG)
        import run as R  # noqa: E402
        if not os.path.abspath(R.__file__).startswith(FG):
            raise RuntimeError("module 'run' is not research/fullgrid/run.py")
        _FGR["run"] = R
    return _FGR["run"]


def strategy_module(name: str):
    """``run.core_module(name)``: the hash-checked param_defs module, memo-installed."""
    if name not in CORE:
        raise KeyError(f"native.py defines the own exit of {CORE}, not {name!r}")
    return fg().core_module(name)


# ------------------------------------------------------------------ small helpers
def _tri(truth, valid) -> np.ndarray:
    """float64 component values: 1.0 where ``truth`` and ``valid``, 0.0 where not ``truth`` and ``valid``, NaN where not ``valid``
    (rule C7: a NaN input means the component neither fires nor arms there)."""
    t = np.asarray(truth, dtype=bool)
    v = np.asarray(valid, dtype=bool)
    return np.where(v, t.astype(np.float64), np.nan)


def as_bool(a) -> np.ndarray:
    """The plain boolean view of a component array: True only where the value is 1.0 (NaN -> False)."""
    a = np.asarray(a)
    if a.dtype == bool:
        return a
    with np.errstate(invalid="ignore"):
        return np.asarray(a == 1.0, dtype=bool)


def _fin(*arrs) -> np.ndarray:
    """True where every array is finite."""
    ok = np.ones(len(arrs[0]), dtype=bool)
    for a in arrs:
        ok &= np.isfinite(np.asarray(a, dtype=float))
    return ok


def _f(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _prev(x: np.ndarray) -> np.ndarray:
    """x shifted by one bar, NaN at bar 0."""
    out = np.full(len(x), np.nan)
    out[1:] = x[:-1]
    return out


def _at_signals(flag, values) -> np.ndarray:
    """``values`` where ``flag`` and finite, NaN elsewhere (per-signal arrays, C5 / C7)."""
    v = _f(values)
    return np.where(np.asarray(flag, dtype=bool) & np.isfinite(v), v, np.nan)


def _nan(n: int) -> np.ndarray:
    return np.full(n, np.nan)


def _out(name: str, n: int, comp_long, comp_short, lvl_long=None, lvl_short=None, tgt_long=None, tgt_short=None) -> dict:
    spec = SPEC[name]
    for side, comps in (("long", comp_long), ("short", comp_short)):
        kinds = tuple(k for k, _ in comps)
        if kinds != tuple(k for k, _ in spec[side]):
            raise AssertionError(f"{name}: {side} component kinds {kinds} differ from SPEC")
        for _k, arr in comps:
            if len(arr) != n or arr.dtype != np.float64:
                raise AssertionError(f"{name}: a component array is not float64 of len(df)")
    return {
        "comp_long": list(comp_long), "comp_short": list(comp_short),
        "lvl_long": _nan(n) if lvl_long is None else lvl_long, "lvl_short": _nan(n) if lvl_short is None else lvl_short,
        "tgt_long": _nan(n) if tgt_long is None else tgt_long, "tgt_short": _nan(n) if tgt_short is None else tgt_short,
        "names_long": [lab for _k, lab in spec["long"]], "names_short": [lab for _k, lab in spec["short"]],
    }


def _entry_flags(M, df, tf: str, combo: dict) -> tuple:
    """The strategy's own entry flags: what ``run.signals`` returns for the core strategies (``np.asarray(lo, bool)``)."""
    lo, sh = M.signals(df, tf, **combo)
    return np.asarray(lo, bool), np.asarray(sh, bool)


# ------------------------------------------------------------------ A.1 DOGE
def _doge(M, df, tf, combo, n):
    p = M.doge_params(tf, **combo)
    d = M._frame(df)
    ind = M.ds.compute_indicators(d, p)
    sig = M.ds.compute_signals(d, ind, p)
    cross = M.ds.DEFAULT["cross"]                                  # the locked 'le' convention
    ef, es = _f(ind["ema_fast"]), _f(ind["ema_slow"])
    K, D = ind["K"], ind["D"]
    xb = np.asarray(M.ds.cross_below(K, D, cross), dtype=bool)
    xa = np.asarray(M.ds.cross_above(K, D, cross), dtype=bool)
    Kn, Dn = _f(K), _f(D)
    v_state = _fin(ef, es)
    v_event = _fin(Kn, Dn, _prev(Kn), _prev(Dn))
    with np.errstate(invalid="ignore"):
        c_long = [(STATE, _tri(ef < es, v_state)), (EVENT, _tri(xb, v_event))]
        c_short = [(STATE, _tri(ef > es, v_state)), (EVENT, _tri(xa, v_event))]
    # Appendix A.1: (state | event) == the source's own exit, bar for bar
    if not np.array_equal(as_bool(c_long[0][1]) | as_bool(c_long[1][1]), np.asarray(sig["long_exit"], dtype=bool)):
        raise AssertionError("DOGE: long components differ from doge_strategy long_exit")
    if not np.array_equal(as_bool(c_short[0][1]) | as_bool(c_short[1][1]), np.asarray(sig["short_exit"], dtype=bool)):
        raise AssertionError("DOGE: short components differ from doge_strategy short_exit")
    return _out("DOGE", n, c_long, c_short)


# ------------------------------------------------------------------ A.2 N03_ADX_GC
def _n03(M, df, tf, combo, n):
    p = M._resolve(combo)
    ef = _f(M.fg.ema(df["close"], p["ema_fast"]))
    es = _f(M.fg.ema(df["close"], p["ema_slow"]))
    _pdi, _mdi, adx = M.fg.dmi_adx(df, p["adx_len"], p["adx_len"])
    adx = _f(adx)
    v_ema, v_adx = _fin(ef, es), _fin(adx)
    with np.errstate(invalid="ignore"):
        weak = adx < p["adx_level"]
        c_long = [(STATE, _tri(ef < es, v_ema)), (STATE, _tri(weak, v_adx))]
        c_short = [(STATE, _tri(ef > es, v_ema)), (STATE, _tri(weak, v_adx))]
    return _out("N03_ADX_GC", n, c_long, c_short)


# ------------------------------------------------------------------ A.3 N09_ALLIG_AROON
def _n09(M, df, tf, combo, n):
    p = M._resolve(combo)
    close = df["close"]
    lips, teeth, jaw = M.fg.sma(close, p["lips_len"]), M.fg.sma(close, p["teeth_len"]), M.fg.sma(close, p["jaw_len"])
    up, down = M.fg_fast.aroon(df, p["aroon_len"])
    long_state = M.gt(lips, teeth) & M.gt(lips, jaw) & M.ge(up - down, 0)
    short_state = M.lt(lips, teeth) & M.lt(lips, jaw) & M.ge(down - up, 0)
    fin = _fin(lips, teeth, jaw, up, down)
    c_long = [(STATE, _tri(~long_state, fin))]
    c_short = [(STATE, _tri(~short_state, fin))]
    return _out("N09_ALLIG_AROON", n, c_long, c_short)


# ------------------------------------------------------------------ A.4 N10_HA_PSAR
def _n10(M, df, tf, combo, n):
    p = M._resolve(combo)
    ha = M.fg_fast.heikin_ashi(df)
    _psar, pdir = M.fg_fast.parabolic_sar(df, p["sar_af_start"], p["sar_af_step"], p["sar_af_max"])
    tol = (ha["ha_high"] - ha["ha_low"]).abs() * p["wick_tol"]
    body_min = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    body_max = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    v_psar = _fin(pdir)
    v_ha = _fin(ha["ha_close"], ha["ha_open"], ha["ha_high"], ha["ha_low"], tol)
    red_strong = M.lt(ha["ha_close"], ha["ha_open"]) & M.le((ha["ha_high"] - body_max).abs(), tol)
    green_strong = M.gt(ha["ha_close"], ha["ha_open"]) & M.le((body_min - ha["ha_low"]).abs(), tol)
    c_long = [(STATE, _tri(M.lt(pdir, 0), v_psar)), (STATE, _tri(red_strong, v_ha))]
    c_short = [(STATE, _tri(M.gt(pdir, 0), v_psar)), (STATE, _tri(green_strong, v_ha))]
    return _out("N10_HA_PSAR", n, c_long, c_short)


# ------------------------------------------------------------------ A.5 N13_3OUTSIDE
def _n13_masks(M, d, p) -> dict:
    """What ``M.signals`` computes inline, with the module's helpers: the long / short breakout masks and, per signal bar,
    the pattern's 3-bar high and low (lag 1 wins when both lags are true)."""
    o, h, l, c = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    a = M.fg.atr(d, p["atr_len"]).to_numpy(dtype=float)
    b = c - o
    last, first = M._sh(c, M.FIRST_LAG + 1), M._sh(c, M.FIRST_LAG + p["prior_n"])
    B1, B2, B3 = M._sh(b, 2), M._sh(b, 1), b
    O1, C1, O2, C2 = M._sh(o, 2), M._sh(c, 2), M._sh(o, 1), M._sh(c, 1)
    em = p["engulf_min"]
    with np.errstate(invalid="ignore"):
        upp, dnp = last > first, last < first
        bull = dnp & (B1 < 0) & (B2 > 0) & (B2 >= em * a) & (O2 <= C1) & (C2 >= O1) & (B3 > 0) & (c > C2)
        bear = upp & (B1 > 0) & (B2 < 0) & (-B2 >= em * a) & (O2 >= C1) & (C2 <= O1) & (B3 < 0) & (c < C2)
    ph3, pl3 = M._roll(h, 3, "max"), M._roll(l, 3, "min")
    nn = len(c)
    long = np.zeros(nn, dtype=bool)
    short = np.zeros(nn, dtype=bool)
    ph_l, pl_l = _nan(nn), _nan(nn)           # pattern high / low of the long breakout at each bar
    ph_s, pl_s = _nan(nn), _nan(nn)
    c1 = M._sh(c, 1)
    for lag in M.LAGS:                        # (2, 1): the later lag overwrites, so lag 1 wins when both are true
        pb, pbr = M.shift_bool(bull, lag), M.shift_bool(bear, lag)
        PH, PL = M._sh(ph3, lag), M._sh(pl3, lag)
        with np.errstate(invalid="ignore"):
            lk = pb & (c > PH) & (c1 <= PH)
            sk = pbr & (c < PL) & (c1 >= PL)
        long |= lk
        short |= sk
        ph_l, pl_l = np.where(lk, PH, ph_l), np.where(lk, PL, pl_l)
        ph_s, pl_s = np.where(sk, PH, ph_s), np.where(sk, PL, pl_s)
    short = short & ~long
    return {"long": long, "short": short, "ph_l": ph_l, "pl_l": pl_l, "ph_s": ph_s, "pl_s": pl_s}


def _n13(M, df, tf, combo, n):
    p = M._resolve(combo)
    d = df.reset_index(drop=True)
    mk = _n13_masks(M, d, p)
    sig_l, sig_s = _entry_flags(M, d, tf, combo)
    if not (np.array_equal(mk["long"], sig_l) and np.array_equal(mk["short"], sig_s)):
        raise AssertionError("N13_3OUTSIDE: the re-derived breakout masks differ from run.signals")
    lvl_long = _at_signals(sig_l, mk["pl_l"])
    tgt_long = _at_signals(sig_l, mk["ph_l"] + (mk["ph_l"] - mk["pl_l"]))
    lvl_short = _at_signals(sig_s, mk["ph_s"])
    t_s = mk["pl_s"] - (mk["ph_s"] - mk["pl_s"])
    with np.errstate(invalid="ignore"):
        t_s = np.where(t_s > 0, t_s, np.nan)       # a short target at or below zero is none
    tgt_short = _at_signals(sig_s, t_s)
    ones = np.ones(n, dtype=bool)
    c_long = [(EVENT, _tri(sig_s, ones))]
    c_short = [(EVENT, _tri(sig_l, ones))]
    return _out("N13_3OUTSIDE", n, c_long, c_short, lvl_long, lvl_short, tgt_long, tgt_short)


# ------------------------------------------------------------------ A.6 N19_FIB_CHOP
def _n19(M, df, tf, combo, n):
    p = M._resolve(combo)
    d = df.reset_index(drop=True)
    h, l = M._f(d["high"]), M._f(d["low"])
    nlen = p["range_len"]
    hh = M._sh(pd.Series(h).rolling(nlen, min_periods=nlen).max().to_numpy(), M.RANGE_LAG)
    ll = M._sh(pd.Series(l).rolling(nlen, min_periods=nlen).min().to_numpy(), M.RANGE_LAG)
    R = hh - ll
    f = p["fib_level"]
    line_l = ll + (1.0 - f) * R
    line_s = ll + f * R
    atr_s = M.fg.atr(d, M.ATR_LEN)
    base = M.fg.ema(d["close"], M.CHOP_EMA)
    slope = M._f((base - base.shift(M.SLOPE_LAG)) / atr_s.replace(0, np.nan))
    sig_l, sig_s = _entry_flags(M, d, tf, combo)
    # guard: the module's entry from these very arrays (a wrong copy of its expressions would show here)
    o, c = M._f(d["open"]), M._f(d["close"])
    a = M._f(atr_s)
    t, thr = p["touch_atr"], p["slope_thr"]
    with np.errstate(invalid="ignore"):
        e_long = (l <= line_l + t * a) & (c > line_l) & (c > o) & (slope >= thr)
        e_short = (h >= line_s - t * a) & (c < line_s) & (c < o) & (slope <= -thr)
    e_short = e_short & ~e_long
    if not (np.array_equal(e_long, sig_l) and np.array_equal(e_short, sig_s)):
        raise AssertionError("N19_FIB_CHOP: the re-derived entry differs from run.signals")
    with np.errstate(invalid="ignore"):
        has = R > 0                                   # R <= 0: no level and no target
    lvl_long = _at_signals(sig_l & has, line_l)
    tgt_long = _at_signals(sig_l & has, hh)
    lvl_short = _at_signals(sig_s & has, line_s)
    tgt_short = _at_signals(sig_s & has, ll)
    with np.errstate(invalid="ignore"):
        v = _fin(slope)
        c_long = [(STATE, _tri(slope <= -thr, v))]
        c_short = [(STATE, _tri(slope >= thr, v))]
    return _out("N19_FIB_CHOP", n, c_long, c_short, lvl_long, lvl_short, tgt_long, tgt_short)


# ------------------------------------------------------------------ A.7 OBV_S
def _obv(M, df, tf, combo, n):
    p = M._resolve(combo)
    o = M.pi.obv(M._f(df["close"]), M._f(df["volume"]))
    ma = M.pi.pine_sma(o, p["obv_ma_len"])
    v = _fin(o, ma)
    with np.errstate(invalid="ignore"):
        c_long = [(STATE, _tri(o < ma, v))]
        c_short = [(STATE, _tri(o > ma, v))]
    return _out("OBV_S", n, c_long, c_short)


# ------------------------------------------------------------------ A.8 S4_BB_BBP
def _s4(M, df, tf, combo, n):
    p = M._resolve(combo)
    d = df.reset_index(drop=True)
    close = d["close"]
    _up, mid, _lo, _bw = M.fg.bollinger_bands(close, p["bb_len"], p["bb_mult"])
    _bu, _be, bbp = M.fg.bull_bear_power(d, M.BBP_LEN)
    v_mid, v_bbp = _fin(close, mid), _fin(bbp)
    c_long = [(STATE, _tri(M.lt(close, mid), v_mid)), (STATE, _tri(M.lt(bbp, 0.0), v_bbp))]
    c_short = [(STATE, _tri(M.gt(close, mid), v_mid)), (STATE, _tri(M.gt(bbp, 0.0), v_bbp))]
    return _out("S4_BB_BBP", n, c_long, c_short)


_IMPL = {"DOGE": _doge, "N03_ADX_GC": _n03, "N09_ALLIG_AROON": _n09, "N10_HA_PSAR": _n10, "N13_3OUTSIDE": _n13,
         "N19_FIB_CHOP": _n19, "OBV_S": _obv, "S4_BB_BBP": _s4}


def native_arrays(name: str, df: pd.DataFrame, tf: str, combo: dict | None = None) -> dict:
    """The own-exit arrays of the core strategy ``name`` on the chart frame ``df`` of timeframe ``tf`` with the pick's
    ``combo`` (module docstring). Every array has len(df) entries; everything at bar i reads bars <= i only."""
    M = strategy_module(name)
    combo = dict(combo or {})
    n = len(df)
    if n == 0:
        return _out(name, 0, [(k, np.zeros(0)) for k, _ in SPEC[name]["long"]],
                    [(k, np.zeros(0)) for k, _ in SPEC[name]["short"]])
    return _IMPL[name](M, df, tf, combo, n)
