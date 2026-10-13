"""The owner-exit league's own-structure arrays for six CORE strategies that research/exitflex/native.py does not cover
(owners' decision 2026-10-13): N02_ST_KST, N04_ST_KLINGER, N07_ICHI_CMO, N12_ICHI_AO, N21_ST_RSI_ADX, N23_HA_ST.

    native_arrays(name, df, tf, combo=None, expect=None) -> the same dict as research/exitflex/native.native_arrays:
        "comp_long" / "comp_short": [(kind, float64 array), ...]   kind 'state' or 'event', one value per chart bar,
                                                                   1.0 true, 0.0 false, NaN unknown (rule C7: neither fires nor arms)
        "lvl_long", "lvl_short", "tgt_long", "tgt_short": all-NaN arrays (these strategies have no own stop or target level:
                                                                   no -iv / -ot accounts for them)
        "names_long", "names_short": one label per component.

This file is NOT part of the pre-registered study (research/exitflex stays untouched): it is the league's own addition, and
``candleague.rulex.native_hash`` includes it, so a change here restarts the league. The rules C1-C8 of native.py's docstring apply
unchanged (a long closes when ANY of its components fires; a 'state' fires where it is true once it has been false at a check
since the entry, an 'event' fires on a bar after the entry; shorts are the mirror).

Where the strategy's own entry says "the structure is intact" (a long: Supertrend up, trend lines in the long order ...), the
structure is BROKEN when the part that the entry needed turns against the trade. Per strategy (long; shorts mirrored):

    N02_ST_KST      Supertrend direction down (state)                  OR  KST crosses below its signal line (event)
    N04_ST_KLINGER  Supertrend direction down (state)                  OR  Klinger crosses below its signal line (event)
    N07_ICHI_CMO    Tenkan below Kijun (state) OR close below the cloud (state) OR CMO below 0 (state)
    N12_ICHI_AO     Tenkan below Kijun (state) OR close below the cloud (state) OR AO below 0 (state)
    N21_ST_RSI_ADX  Supertrend direction down (state)                  OR  RSI crosses back below the oversold level (event)
    N23_HA_ST       Heikin-Ashi candle bearish (state)                 OR  Supertrend direction down (state)

N21 is a counter-trend rebound: the entry is "Supertrend still up, RSI below 30 and turning up, ADX falling under 25". Its structure
breaks when the trend filter turns (Supertrend down) or when the rebound fails: RSI, after having left the oversold zone, is back
under the level (an event: a cross below the level on a bar after the entry bar). The short side is the mirror around 100 - level.

The strategy module is ``run.core_module(name)`` (hash-checked, the object ``run.signals`` uses), and only its own indicator
functions are called with the pick's own combo (``M._resolve(combo)``): nothing of a signal formula is re-implemented. Everything at
bar i reads bars <= i only (Supertrend, KST, Klinger, Ichimoku with the cloud displaced forward, CMO, AO, RSI and Heikin-Ashi are
all causal), which tests/test_candleague_native_more.py checks by cutting the future off.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FG = os.path.join(ROOT, "research", "fullgrid")

STATE, EVENT = "state", "event"
NAMES = ("N02_ST_KST", "N04_ST_KLINGER", "N07_ICHI_CMO", "N12_ICHI_AO", "N21_ST_RSI_ADX", "N23_HA_ST")

SPEC = {
    "N02_ST_KST": {"long": ((STATE, "Supertrend direction down"), (EVENT, "KST crosses below its signal")),
                   "short": ((STATE, "Supertrend direction up"), (EVENT, "KST crosses above its signal"))},
    "N04_ST_KLINGER": {"long": ((STATE, "Supertrend direction down"), (EVENT, "Klinger crosses below its signal")),
                       "short": ((STATE, "Supertrend direction up"), (EVENT, "Klinger crosses above its signal"))},
    "N07_ICHI_CMO": {"long": ((STATE, "Tenkan < Kijun"), (STATE, "close < cloud"), (STATE, "CMO < 0")),
                     "short": ((STATE, "Tenkan > Kijun"), (STATE, "close > cloud"), (STATE, "CMO > 0"))},
    "N12_ICHI_AO": {"long": ((STATE, "Tenkan < Kijun"), (STATE, "close < cloud"), (STATE, "AO < 0")),
                    "short": ((STATE, "Tenkan > Kijun"), (STATE, "close > cloud"), (STATE, "AO > 0"))},
    "N21_ST_RSI_ADX": {"long": ((STATE, "Supertrend direction down"), (EVENT, "RSI crosses back below the oversold level")),
                       "short": ((STATE, "Supertrend direction up"), (EVENT, "RSI crosses back above the overbought level"))},
    "N23_HA_ST": {"long": ((STATE, "Heikin-Ashi candle bearish"), (STATE, "Supertrend direction down")),
                  "short": ((STATE, "Heikin-Ashi candle bullish"), (STATE, "Supertrend direction up"))},
}


# ------------------------------------------------------------------ the study's modules
_FGR: dict = {}


def fg():
    """research/fullgrid/run.py as module ``run`` (the name native.py and sizing.py use)."""
    if "run" not in _FGR:
        if FG not in sys.path:
            sys.path.insert(0, FG)
        import run as R  # noqa: E402
        if not os.path.abspath(R.__file__).startswith(FG):
            raise RuntimeError("module 'run' is not research/fullgrid/run.py")
        _FGR["run"] = R
    return _FGR["run"]


def strategy_module(name: str):
    if name not in NAMES:
        raise KeyError(f"native_more.py defines the own structure of {NAMES}, not {name!r}")
    return fg().core_module(name)


# ------------------------------------------------------------------ small helpers (shared with native_more_ds.py)
def tri(truth, valid) -> np.ndarray:
    """float64 component values: 1.0 where ``truth`` and ``valid``, 0.0 where valid and not ``truth``, NaN where not ``valid``."""
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


def fin(*arrs) -> np.ndarray:
    """True where every array is finite."""
    ok = np.ones(len(arrs[0]), dtype=bool)
    for a in arrs:
        ok &= np.isfinite(np.asarray(a, dtype=float))
    return ok


def f(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def prev(x) -> np.ndarray:
    """x shifted by one bar, NaN at bar 0."""
    x = f(x)
    out = np.full(len(x), np.nan)
    out[1:] = x[:-1]
    return out


def out_dict(spec: dict, n: int, comp_long, comp_short) -> dict:
    """The result dict; refuses components that do not match ``spec`` (kinds, float64, one value per bar)."""
    for side, comps in (("long", comp_long), ("short", comp_short)):
        if tuple(k for k, _ in comps) != tuple(k for k, _ in spec[side]):
            raise AssertionError(f"{side} component kinds differ from SPEC")
        for _k, arr in comps:
            if len(arr) != n or arr.dtype != np.float64:
                raise AssertionError("a component array is not float64 of len(df)")
    nan = lambda: np.full(n, np.nan)  # noqa: E731
    return {"comp_long": list(comp_long), "comp_short": list(comp_short),
            "lvl_long": nan(), "lvl_short": nan(), "tgt_long": nan(), "tgt_short": nan(),
            "names_long": [lab for _k, lab in spec["long"]], "names_short": [lab for _k, lab in spec["short"]]}


# ------------------------------------------------------------------ the six definitions
def _dir_states(direction):
    d = f(direction)
    v = fin(d)
    with np.errstate(invalid="ignore"):
        return tri(d < 0, v), tri(d > 0, v)          # (Supertrend down, Supertrend up)


def _cross_events(M, a, b):
    """(a crosses below b, a crosses above b) with the module's own cross functions; unknown where an input (or its previous value) is not finite."""
    af, bf = f(a), f(b)
    v = fin(af, prev(af), bf, prev(bf))
    return tri(M.cross_below(a, b), v), tri(M.cross_above(a, b), v)


def _n02(M, d, tf, combo, n):
    p = M._resolve(combo)
    _line, direction, _u, _l = M.fg_fast.supertrend(d, p["st_atr_len"], p["st_mult"])
    kline, ksig = M.fg.kst(d["close"], p["kst_roc_lens"], M._KST_SMA, p["kst_signal_len"])
    st_dn, st_up = _dir_states(direction)
    k_dn, k_up = _cross_events(M, kline, ksig)
    return [(STATE, st_dn), (EVENT, k_dn)], [(STATE, st_up), (EVENT, k_up)]


def _n04(M, d, tf, combo, n):
    p = M._resolve(combo)
    _line, direction, _u, _l = M.fg_fast.supertrend(d, p["st_atr_len"], p["st_mult"])
    fast, slow = p["kvo_lens"]
    kl, ks = M.fg.klinger_oscillator(d, fast, slow, p["kvo_signal_len"])
    st_dn, st_up = _dir_states(direction)
    k_dn, k_up = _cross_events(M, kl, ks)
    return [(STATE, st_dn), (EVENT, k_dn)], [(STATE, st_up), (EVENT, k_up)]


def _ichi(M, d, p, span_b_len, mom):
    tenkan, kijun, span_a, span_b = M.fg.ichimoku(d, p["tenkan_len"], p["kijun_len"], span_b_len, M._DISPLACEMENT)
    close = f(d["close"])
    tk, ki, sa, sb, m = f(tenkan), f(kijun), f(span_a), f(span_b), f(mom)
    v_tk, v_cl, v_m = fin(tk, ki), fin(close, sa, sb), fin(m)
    with np.errstate(invalid="ignore"):
        top, bot = np.fmax(sa, sb), np.fmin(sa, sb)
        lvl = M._LEVEL
        c_long = [(STATE, tri(tk < ki, v_tk)), (STATE, tri(close < bot, v_cl)), (STATE, tri(m < lvl, v_m))]
        c_short = [(STATE, tri(tk > ki, v_tk)), (STATE, tri(close > top, v_cl)), (STATE, tri(m > lvl, v_m))]
    return c_long, c_short


def _n07(M, d, tf, combo, n):
    p = M._resolve(combo)
    return _ichi(M, d, p, p["senkou_b_len"], M.fg.cmo(d["close"], p["cmo_len"]))


def _n12(M, d, tf, combo, n):
    p = M._resolve(combo)
    return _ichi(M, d, p, M._SPAN_B, M.fg.awesome_oscillator(d, p["ao_fast_len"], p["ao_slow_len"]))


def _n21(M, d, tf, combo, n):
    p = M._resolve(combo)
    _line, direction, _u, _l = M.fg_fast.supertrend(d, M.ST_ATR_LEN, p["st_mult"])
    r = M.fg.rsi(d["close"], M.RSI_LEN)
    st_dn, st_up = _dir_states(direction)
    rf_ = f(r)
    v = fin(rf_, prev(rf_))
    # the rebound failed: RSI, back above the level some bar after the dip, is under it again (a cross below the long level);
    # the short mirror is 100 - level, as the entry's
    below = M.cross_below(r, p["rsi_level"])
    import strategies as ST                          # the vendored locked module the strategy modules import their cross functions from
    above = ST.cross_above(r, 100.0 - p["rsi_level"])
    return [(STATE, st_dn), (EVENT, tri(below, v))], [(STATE, st_up), (EVENT, tri(above, v))]


def _n23(M, d, tf, combo, n):
    p = M._resolve(combo)
    ha = M.fg_fast.heikin_ashi(d)
    _line, direction, _u, _l = M.fg_fast.supertrend(d, p["st_atr_len"], p["st_mult"])
    hc, ho = f(ha["ha_close"]), f(ha["ha_open"])
    v = fin(hc, ho)
    st_dn, st_up = _dir_states(direction)
    with np.errstate(invalid="ignore"):
        return [(STATE, tri(hc < ho, v)), (STATE, st_dn)], [(STATE, tri(hc > ho, v)), (STATE, st_up)]


_IMPL = {"N02_ST_KST": _n02, "N04_ST_KLINGER": _n04, "N07_ICHI_CMO": _n07, "N12_ICHI_AO": _n12, "N21_ST_RSI_ADX": _n21, "N23_HA_ST": _n23}


def native_arrays(name: str, df: pd.DataFrame, tf: str, combo: dict | None = None, expect=None) -> dict:
    """The own-structure arrays of the core strategy ``name`` on the chart frame ``df`` of timeframe ``tf`` with the pick's ``combo``.
    ``expect`` = (long, short) as returned by ``run.signals`` on the same frame: asserted equal to the module's own ``signals``."""
    M = strategy_module(name)
    combo = dict(combo or {})
    n = len(df)
    d = df.reset_index(drop=True)
    if expect is not None:
        el, es = np.asarray(expect[0], dtype=bool), np.asarray(expect[1], dtype=bool)
        if el.shape != (n,) or es.shape != (n,):
            raise AssertionError(f"{name}: expect has the wrong length")
        if n:
            lo, sh = M.signals(d, tf, **combo)
            if not (np.array_equal(np.asarray(lo, bool), el) and np.array_equal(np.asarray(sh, bool), es)):
                raise AssertionError(f"{name}: the module's entry flags differ from run.signals (expect)")
    if n == 0:
        z = lambda side: [(k, np.zeros(0)) for k, _ in SPEC[name][side]]  # noqa: E731
        return out_dict(SPEC[name], 0, z("long"), z("short"))
    comp_long, comp_short = _IMPL[name](M, d, tf, combo, n)
    return out_dict(SPEC[name], n, comp_long, comp_short)
