"""Chart views of the 36 strategies for the dashboard's strategy tab.

Each ``view_<NAME>(df, tf)`` in ``strategy_view_defs/<NAME>.py`` returns the indicator lines the
strategy's locked code uses (same parameters) and its entry conditions as boolean arrays,
with plain Korean names. They were written and checked against the locked signals
(recall and precision of AND(conditions) vs the signal, see docs/strategy-views.md).

The view module imports the vendored indicator code, so it is loaded only after
``sweepsig.lib()`` has verified the locked files and put them on the path.

``render`` turns one view into what the chart draws: the last ``tail`` bars of every line
as {time, value} points and the conditions on the last closed bar.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np
import pandas as pd

from . import sweepsig

_VIEWS: Optional[dict[str, Callable]] = None


def views() -> dict[str, Callable]:
    global _VIEWS
    if _VIEWS is None:
        sweepsig.lib()
        import importlib
        from .strategy_view_defs import NAMES
        _VIEWS = {n: getattr(importlib.import_module(f"{__package__}.strategy_view_defs.{n}"), f"view_{n}")
                  for n in NAMES}
    return _VIEWS


def _points(times: np.ndarray, values, tail: int) -> list[dict]:
    v = np.asarray(values, dtype=float)[-tail:]
    t = times[-tail:]
    return [{"time": int(a), "value": float(b)} for a, b in zip(t, v) if math.isfinite(b)]


def _last(flag) -> bool:
    a = np.asarray(flag, dtype=bool)
    return bool(a[-1]) if len(a) else False


def render(name: str, df: pd.DataFrame, tf: str, tail: int = 500) -> dict:
    """``df``: closed bars only (ts, open, high, low, close, volume), oldest first."""
    fn = views()[name]
    df = df.reset_index(drop=True)
    df.attrs["tf"] = tf
    v = fn(df, tf)
    ts = pd.to_datetime(df["ts"], utc=True)
    times = (ts.astype("int64") // 10**9).to_numpy()
    span_ms = int((ts.iloc[-1] - ts.iloc[-2]).total_seconds() * 1000) if len(ts) > 1 else 0
    return {
        "strategy": name, "timeframe": tf,
        "bar_close": int(times[-1]) * 1000 + span_ms if len(times) else None,
        "overlays": [{"name": o["name"], "data": _points(times, o["values"], tail)} for o in v.get("overlays", [])],
        "panes": [{"name": p["name"], "levels": list(p.get("levels", [])),
                   "series": [{"name": s["name"], "data": _points(times, s["values"], tail)} for s in p["series"]]}
                  for p in v.get("panes", [])],
        "conditions": {side: [{"name": n, "on": _last(arr)} for n, arr in v.get(side, [])]
                       for side in ("long", "short")},
    }
