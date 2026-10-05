"""Chart views of the 36 strategies for the dashboard's strategy tab.

Each ``view_<NAME>(df, tf)`` in ``strategy_view_defs/<NAME>.py`` returns the indicator lines the
strategy's locked code uses (same parameters) and its entry conditions as boolean arrays,
with plain Korean names. They were written and checked against the locked signals
(recall and precision of AND(conditions) vs the signal, see docs/strategy-views.md).

The view module imports the vendored indicator code, so it is loaded only after
``sweepsig.lib()`` has verified the locked files and put them on the path.

``render`` turns one view into what the chart draws: the last ``tail`` bars of every line
as {time, value} points and the conditions on the last closed bar.

Paper v4: the 44 DeepSeek-200 definitions and the reel have their views too (strategy_view_defs/v4_views.py maps a
strategy id to its module: "F9_FVG" -> DS_F9_FVG.view_DS_F9_FVG, "REEL_H1" -> REEL_H1.view_REEL_H1). They are NOT in
``views()``, which stays the 36 (NAMES: tests, the research prior and the monthly re-check read it as "the 36").
``views()`` loads the v4 registry as well; each v4 module is imported on first use (``v4_view``), and a module that is
not written yet or fails to import is skipped (tried again once its file changes), never an error. ``get_view`` /
``has_view`` / ``all_views`` cover both. ``render`` passes ``df.attrs["symbol"]`` on and hands ``df.attrs["btc"]``
(BTC's bars of the same timeframe; or the ``symbol`` / ``btc`` arguments) to a view that takes a ``btc`` argument
(DS_F14_SMT); a frame is never left in attrs, where it breaks the other views' pandas calls.
"""

from __future__ import annotations

import importlib
import inspect
import math
import os
import sys
from typing import Callable, Optional

import numpy as np
import pandas as pd

from . import sweepsig

_VIEWS: Optional[dict[str, Callable]] = None
DEFS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_view_defs")
_V4_REGISTRY: Optional[dict[str, str]] = None      # strategy id -> module name (strategy_view_defs/v4_views.py)
_V4: dict[str, Callable] = {}                       # v4 views imported so far
_V4_BROKEN: dict[str, tuple[int, str]] = {}         # module -> (file mtime_ns, error) of a module that failed to import


def views() -> dict[str, Callable]:
    """The 36 locked strategies' views (NAMES). Also loads the v4 registry (``v4_registry``); the v4 views
    themselves are imported on first use and are not in this dict (``get_view`` / ``all_views``)."""
    global _VIEWS
    if _VIEWS is None:
        sweepsig.lib()
        from .strategy_view_defs import NAMES
        _VIEWS = {n: getattr(importlib.import_module(f"{__package__}.strategy_view_defs.{n}"), f"view_{n}")
                  for n in NAMES}
        v4_registry()
    return _VIEWS


def v4_registry() -> dict[str, str]:
    """{strategy id: module name} of the v4 views (44 DeepSeek ids + REEL_H1); {} when the registry itself cannot be
    imported (not cached then: the next call tries again)."""
    global _V4_REGISTRY
    if _V4_REGISTRY is None:
        try:
            from .strategy_view_defs.v4_views import V4_VIEWS
        except Exception:  # noqa: BLE001  (a v4 problem never takes the 36's views down)
            return {}
        _V4_REGISTRY = dict(V4_VIEWS)
    return _V4_REGISTRY


def v4_view(name: str) -> Optional[Callable]:
    """The v4 view of ``name`` (``view_<module>`` of its module), imported now if needed; None when ``name`` is no v4
    strategy, its module is not written yet, or the module fails to import (remembered until its file changes)."""
    fn = _V4.get(name)
    if fn is not None:
        return fn
    mod = v4_registry().get(name)
    if mod is None:
        return None
    try:
        mtime = os.stat(os.path.join(DEFS_DIR, mod + ".py")).st_mtime_ns
    except OSError:
        return None                                   # not written yet
    if mod in _V4_BROKEN and _V4_BROKEN[mod][0] == mtime:
        return None
    full = f"{__package__}.strategy_view_defs.{mod}"
    try:
        sweepsig.lib()                                # the vendored indicator code the views import
        if full in sys.modules and mod in _V4_BROKEN:
            del sys.modules[full]
        fn = getattr(importlib.import_module(full), f"view_{mod}")
        if not callable(fn):
            raise TypeError(f"view_{mod} is not callable")
    except Exception as exc:  # noqa: BLE001  (a module still being written: skip it)
        sys.modules.pop(full, None)
        _V4_BROKEN[mod] = (mtime, f"{type(exc).__name__}: {exc}"[:300])
        return None
    _V4_BROKEN.pop(mod, None)
    _V4[name] = fn
    return fn


def v4_views() -> dict[str, Callable]:
    """Every v4 view that loads now, in registry order (missing or broken modules left out)."""
    out = {}
    for name in v4_registry():
        fn = v4_view(name)
        if fn is not None:
            out[name] = fn
    return out


def v4_missing() -> dict[str, str]:
    """{strategy id: why it has no view} for the v4 strategies whose view does not load now."""
    out = {}
    for name, mod in v4_registry().items():
        if v4_view(name) is None:
            out[name] = _V4_BROKEN[mod][1] if mod in _V4_BROKEN else f"{mod}.py not written yet"
    return out


def get_view(name: str) -> Optional[Callable]:
    """The view of one of the 36 or of a v4 strategy; None when there is none (yet)."""
    fn = views().get(name)
    return fn if fn is not None else v4_view(name)


def has_view(name: str) -> bool:
    return get_view(name) is not None


def all_views() -> dict[str, Callable]:
    """The 36 and every v4 view that loads now."""
    return {**views(), **v4_views()}


def _takes_btc(fn: Callable) -> bool:
    """True when a view has a ``btc`` parameter (DS_F14_SMT: BTCUSDT bars of the same timeframe)."""
    try:
        return "btc" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _points(times: np.ndarray, values, tail: int, breaks: bool = False) -> list[dict]:
    """{time, value} of the last ``tail`` bars, NaN bars left out. ``breaks`` (a v4 zone / level / stop line that
    exists only while it is live): the first NaN bar after a run of values becomes a time-only point ({time}, a
    lightweight-charts whitespace point), so the chart ends the line there and draws each zone as its own piece
    instead of a diagonal from one zone to the next. No time-only point before the first value or after the last."""
    v = np.asarray(values, dtype=float)[-tail:]
    t = times[-tail:]
    if not breaks:
        return [{"time": int(a), "value": float(b)} for a, b in zip(t, v) if math.isfinite(b)]
    out: list[dict] = []
    for a, b in zip(t, v):
        if math.isfinite(b):
            out.append({"time": int(a), "value": float(b)})
        elif out and "value" in out[-1]:
            out.append({"time": int(a)})
    if out and "value" not in out[-1]:
        out.pop()
    return out


STEP_SHARE = 0.5    # a v4 line whose consecutive values are equal this often is a level (drawn as steps;
                    # a moving line such as an average or a band is almost never equal bar to bar)


def _is_step(values) -> bool:
    """True for a level / zone line: at least 10 pairs of consecutive finite values, STEP_SHARE of them equal (a swing
    level, a gap's top or bottom, a range high): the chart draws it with steps, so a new level starts with a vertical
    jump, never a diagonal."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return False
    both = np.isfinite(v[1:]) & np.isfinite(v[:-1])
    k = int(both.sum())
    return k >= 10 and float((v[1:][both] == v[:-1][both]).sum()) >= STEP_SHARE * k


def _line(times: np.ndarray, o: dict, tail: int, v4: bool) -> dict:
    """One drawn line. The 36's: {name, data} (NaN bars left out, as before). A v4 line also carries ``breaks`` (False
    for a line the view marks "join": the zigzag and pivot lines, joined across their empty bars) and ``step``."""
    if not v4:
        return {"name": o["name"], "data": _points(times, o["values"], tail)}
    brk = not o.get("join")
    return {"name": o["name"], "data": _points(times, o["values"], tail, breaks=brk), "breaks": brk,
            "step": bool(brk and _is_step(np.asarray(o["values"], dtype=float)[-tail:]))}


def _last(flag) -> bool:
    a = np.asarray(flag, dtype=bool)
    return bool(a[-1]) if len(a) else False


def render(name: str, df: pd.DataFrame, tf: str, tail: int = 500, symbol: Optional[str] = None,
           btc: Optional[pd.DataFrame] = None) -> dict:
    """``df``: closed bars only (ts, open, high, low, close, volume), oldest first. ``df.attrs["symbol"]`` (or
    ``symbol``) stays in the view's attrs; ``df.attrs["btc"]`` (or ``btc``: BTCUSDT bars of the same timeframe with
    their own ts) goes to a view with a ``btc`` argument (DS_F14_SMT) and is left out of attrs. KeyError when
    ``name`` has no view."""
    fn = get_view(name)
    if fn is None:
        raise KeyError(name)
    sym = symbol if symbol is not None else df.attrs.get("symbol")
    if btc is None:
        btc = df.attrs.get("btc")
    df = df.reset_index(drop=True)
    # A frame in attrs breaks pandas operations of most views (pd.concat compares the attrs of its inputs), so BTC's
    # bars never stay in attrs: a view that reads them (DS_F14_SMT) takes them as its ``btc`` argument.
    df.attrs.pop("btc", None)
    if sym is not None:
        df.attrs["symbol"] = sym
    df.attrs["tf"] = tf
    v = fn(df, tf, btc=btc) if (btc is not None and _takes_btc(fn)) else fn(df, tf)
    v4 = name not in views() and name in v4_registry()     # the 36's lines keep their old shape
    ts = pd.to_datetime(df["ts"], utc=True)
    times = (ts.astype("int64") // 10**9).to_numpy()
    span_ms = int((ts.iloc[-1] - ts.iloc[-2]).total_seconds() * 1000) if len(ts) > 1 else 0
    return {
        "strategy": name, "timeframe": tf,
        "bar_close": int(times[-1]) * 1000 + span_ms if len(times) else None,
        "overlays": [_line(times, o, tail, v4) for o in v.get("overlays", [])],
        "panes": [{"name": p["name"], "levels": list(p.get("levels", [])),
                   "series": [_line(times, s, tail, v4) for s in p["series"]]}
                  for p in v.get("panes", [])],
        "conditions": {side: [{"name": n, "on": _last(arr)} for n, arr in v.get(side, [])]
                       for side in ("long", "short")},
    }
