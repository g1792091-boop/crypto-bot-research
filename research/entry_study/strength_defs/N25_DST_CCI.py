"""Entry-strength numbers for N25_DST_CCI (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n25_double_supertrend_cci, no timeframe
scaling; checked chart view paperbot/strategy_view_defs/N25_DST_CCI.py):
  fast_up = supertrend_v2(10, 6) up, slow_up = supertrend_v2(20, 6) up, CCI = fg_fast.cci(df, 20)
  trend mode (both supertrends agree) or range mode (they disagree)
  long  = CCI crosses above -100 on this bar & NOT (both supertrends down)
  short = CCI crosses below +100 on this bar & NOT (both supertrends up)
(the locked trend / range combination reduces to this; the two CCI crosses cannot share a bar.)

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only (CCI is a trailing 20-bar window, the supertrends are
forward recursions, the dip depth looks only at bars before i).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from paperbot import sweepsig  # noqa: E402

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path
import fg_fast  # noqa: E402
from strategies import _b, ge, gt, le  # noqa: E402

NAME = "N25_DST_CCI"
CCI_LEVEL = 100.0

FEATURES = [
    {"name": "cci_cross_size", "label_ko": "CCI가 ±100을 넘어온 폭", "unit": "CCI 포인트",
     "higher_is_stronger": True,
     "why": "Size of the CCI(20) cross that triggers the entry, on the signal bar: CCI + 100 for "
            "longs (crossed up through -100), 100 - CCI for shorts (crossed down through +100)."},
    {"name": "cci_dip_depth", "label_ko": "직전 CCI 과매도·과매수 깊이", "unit": "CCI 포인트",
     "higher_is_stronger": True,
     "why": "How far CCI(20) went past the level in the run of bars just before the cross: "
            "-100 - min(CCI) over the unbroken CCI <= -100 run ending on the previous bar for longs, "
            "max(CCI) - 100 over the CCI >= +100 run for shorts (NaN when the previous bar is not in such a run)."},
    {"name": "st_agree_count", "label_ko": "같은 방향 슈퍼트렌드 수", "unit": "개 (0~2)",
     "higher_is_stronger": True,
     "why": "How many of the two supertrends (10, 6) and (20, 6) point the trade way: 2 = the rule's "
            "trend mode (both agree), 1 = its range mode (they disagree); the rule needs at least 1."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    x[~np.isfinite(x)] = np.nan
    return x


def _prev_run_extreme(x: np.ndarray, inside: np.ndarray, how: str) -> np.ndarray:
    """At bar i: min (how='min') or max (how='max') of x over the unbroken run of ``inside`` bars that
    ends on bar i-1; NaN when bar i-1 is not inside. Uses bars < i only."""
    n = len(x)
    out = np.full(n, np.nan)
    if n < 2:
        return out
    inside = np.asarray(inside, dtype=bool)
    grp = np.cumsum(~inside)                      # every bar of one run shares an id
    s = pd.Series(np.where(inside, x, np.nan))
    g = s.groupby(grp)
    run = (g.cummin() if how == "min" else g.cummax()).to_numpy(dtype=float)
    out[1:] = np.where(inside[:-1], run[:-1], np.nan)
    return out


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    _l1, d_fast, _u1, _lo1 = fg_fast.supertrend(df, 10, 6.0)   # supertrend_v2 = (line, direction > 0)
    _l2, d_slow, _u2, _lo2 = fg_fast.supertrend(df, 20, 6.0)
    d_fast, d_slow = _arr(d_fast), _arr(d_slow)
    fast_up, slow_up = _b(gt(d_fast, 0)), _b(gt(d_slow, 0))
    undefined = ~(np.isfinite(d_fast) & np.isfinite(d_slow))   # supertrend warm-up: NaN, not "down"
    c = _arr(fg_fast.cci(df, 20))
    below = le(c, -CCI_LEVEL)                    # NaN -> False
    above = ge(c, CCI_LEVEL)
    dip_long = -CCI_LEVEL - _prev_run_extreme(c, below, "min")
    dip_short = _prev_run_extreme(c, above, "max") - CCI_LEVEL
    agree_long = np.where(undefined, np.nan, fast_up.astype(float) + slow_up.astype(float))
    agree_short = np.where(undefined, np.nan, (~fast_up).astype(float) + (~slow_up).astype(float))
    return {
        "cci_cross_size": (_finite(c + CCI_LEVEL), _finite(CCI_LEVEL - c)),
        "cci_dip_depth": (_finite(dip_long), _finite(dip_short)),
        "st_agree_count": (agree_long, agree_short),
    }
