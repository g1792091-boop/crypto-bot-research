"""Indicator memo for the full-grid study: the locked vendor indicator functions (pine_indicators, fg_indicators,
fg_fast, poc_fast) are pure functions of their inputs, and a grid calls them with the same inputs thousands of times
(a 4-number grid changes one number at a time). ``install()`` wraps every public function of those modules, and the
same functions where a parameter-definition module imported them by name, with a bounded cache keyed by the
function, a fingerprint of each array argument and the other arguments. A hit returns a copy of the stored result,
so a caller that edits its result in place cannot change the cache. The cache holds at most FULLGRID_MEMO_MB (700 MB)
per process, least recently used first out. Nothing is cached across series: ``clear()`` between series.

tests/test_fullgrid_memo.py checks that every parameter definition gives identical signals with and without the memo
over a grid sample.
"""

from __future__ import annotations

import functools
import os
import types
from collections import OrderedDict

import numpy as np
import pandas as pd

VENDOR = ("pine_indicators", "fg_indicators", "fg_fast", "poc_fast")
MAX_BYTES = int(os.environ.get("FULLGRID_MEMO_MB", "700")) * 1_000_000    # per process
_CACHE: "OrderedDict" = OrderedDict()
_SIZE = [0]
_W: dict = {}
STATS = {"hit": 0, "miss": 0}


def clear() -> None:
    _CACHE.clear()
    _SIZE[0] = 0


def _nbytes(r) -> int:
    if isinstance(r, np.ndarray):
        return r.nbytes
    if isinstance(r, pd.Series):
        return r.to_numpy().nbytes
    if isinstance(r, pd.DataFrame):
        return int(r.memory_usage(index=False).sum())
    if isinstance(r, (tuple, list)):
        return sum(_nbytes(x) for x in r)
    if isinstance(r, dict):
        return sum(_nbytes(x) for x in r.values())
    return 64


def _weights(n: int) -> np.ndarray:
    w = _W.get(n)
    if w is None:
        w = np.random.default_rng(n).uniform(0.5, 1.5, n)
        _W[n] = w
    return w


def _fp_array(a: np.ndarray):
    a = np.asarray(a)
    if a.dtype == object:
        raise TypeError("object array")
    if a.dtype.kind not in "fiub":
        return ("arr", a.shape, str(a.dtype), a.tobytes())
    x = a.astype(float, copy=False).ravel()
    fin = np.isfinite(x)
    xz = np.where(fin, x, 0.0)
    nonfin = np.flatnonzero(~fin)
    # elementwise, not a BLAS dot: a threaded BLAS call costs milliseconds when many workers share the CPUs
    return ("arr", a.shape, str(a.dtype), float(xz.sum()), float(np.multiply(xz, _weights(len(xz))).sum()),
            tuple(x[:4].tolist()), tuple(x[-4:].tolist()), len(nonfin), hash(nonfin.tobytes()),
            hash(np.isnan(x[~fin]).tobytes()) if len(nonfin) else 0)


def _fp(v):
    if isinstance(v, pd.DataFrame):
        return ("df", tuple(v.columns), tuple(_fp_array(v[c].to_numpy()) if v[c].dtype.kind in "fiub" else
                                                (c, hash(pd.util.hash_pandas_object(v[c], index=False).values.tobytes()))
                                                for c in v.columns), _fp_index(v.index))
    if isinstance(v, pd.Series):
        return ("ser", _fp_array(v.to_numpy()), _fp_index(v.index), v.name if isinstance(v.name, (str, int)) else None)
    if isinstance(v, np.ndarray):
        return _fp_array(v)
    if isinstance(v, (list, tuple)):
        return (type(v).__name__,) + tuple(_fp(x) for x in v)
    if isinstance(v, dict):
        return ("dict",) + tuple(sorted((k, _fp(x)) for k, x in v.items()))
    if v is None or isinstance(v, (bool, int, float, str, np.integer, np.floating)):
        return v
    raise TypeError(f"unhashable argument {type(v).__name__}")


def _fp_index(ix):
    if isinstance(ix, pd.RangeIndex):
        return ("range", ix.start, ix.stop, ix.step)
    return ("index", len(ix), hash(pd.util.hash_pandas_object(pd.Series(ix), index=False).values.tobytes()))


def _copy(r):
    if isinstance(r, (pd.Series, pd.DataFrame, np.ndarray)):
        return r.copy()
    if isinstance(r, tuple):
        return tuple(_copy(x) for x in r)
    if isinstance(r, list):
        return [_copy(x) for x in r]
    if isinstance(r, dict):
        return {k: _copy(x) for k, x in r.items()}
    return r


def wrap(fn):
    if getattr(fn, "_fullgrid_memo", False):
        return fn

    @functools.wraps(fn)
    def w(*args, **kwargs):
        try:
            key = (fn.__module__, fn.__qualname__, tuple(_fp(a) for a in args),
                   tuple(sorted((k, _fp(v)) for k, v in kwargs.items())))
            hash(key)
        except TypeError:
            return fn(*args, **kwargs)
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            STATS["hit"] += 1
            return _copy(hit)
        STATS["miss"] += 1
        r = fn(*args, **kwargs)
        kept = _copy(r)
        _CACHE[key] = kept
        _SIZE[0] += _nbytes(kept)
        while _SIZE[0] > MAX_BYTES and len(_CACHE) > 1:
            _k, old = _CACHE.popitem(last=False)
            _SIZE[0] -= _nbytes(old)
        return r
    w._fullgrid_memo = True
    w._fullgrid_orig = fn
    return w


def install(modules: list) -> int:
    """Wrap the vendor modules' functions (looked up by name at call time) and the copies the given modules imported
    by name. Returns the number of functions wrapped."""
    import sys
    n = 0
    vend = [sys.modules[m] for m in VENDOR if m in sys.modules]
    for vm in vend:
        for name, f in list(vars(vm).items()):
            if isinstance(f, types.FunctionType) and f.__module__ == vm.__name__ and not name.startswith("__"):
                setattr(vm, name, wrap(f))
                n += 1
    for m in list(modules) + [sys.modules[k] for k in ("strategies", "doge_strategy", "ports12") if k in sys.modules]:
        for name, f in list(vars(m).items()):
            if isinstance(f, types.FunctionType) and f.__module__ in VENDOR:
                setattr(m, name, getattr(sys.modules[f.__module__], f.__name__, wrap(f)))
                n += 1
    return n
