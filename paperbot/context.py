"""Chart situation at a signal, from confirmed bars only (regime judge v1).

All thresholds are initial values fixed before looking at results. They are
calibrated only against human labels, never tuned to improve P&L.

Regime labels over the last N bars:
    box        clear upper/lower boundaries: >= 2 distinct touches of each
               edge zone, low efficiency ratio, flat regression slope
    chop       low efficiency ratio but no clean boundaries
    trend_up / trend_down   high efficiency ratio and a slope in one direction
    unknown    none of the above, or too few bars
Boundaries use the 95th/5th percentile of highs/lows to ignore single wicks.
Random-walk scaling (ER ~ 1/sqrt(N)) sets the ER thresholds; this is an
approximation, not an external standard.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from .models import Bar

# Default regime window per timeframe.
REGIME_N = {"1m": 60, "5m": 72, "15m": 64, "30m": 48, "1h": 48, "4h": 42, "1d": 30}
# Higher timeframe used for "counter-trend" and "higher-timeframe box wall".
HTF = {"1m": "15m", "5m": "30m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d", "1d": None}


def _quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def atr(bars: Sequence[Bar], n: int = 14) -> Optional[float]:
    """Wilder ATR over the given bars."""
    if len(bars) < n + 1:
        return None
    trs = []
    for prev, b in zip(bars[:-1], bars[1:]):
        trs.append(max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def ema(values: Sequence[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out = []
    e = values[0]
    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _slope(closes: list[float]) -> float:
    n = len(closes)
    xm = (n - 1) / 2
    ym = sum(closes) / n
    num = sum((i - xm) * (c - ym) for i, c in enumerate(closes))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


def _touches(values: list[float], inside, leave) -> int:
    """Count separate entries into a zone; must leave by ``leave`` to re-count."""
    count, in_zone = 0, False
    for v in values:
        if inside(v):
            if not in_zone:
                count += 1
                in_zone = True
        elif leave(v):
            in_zone = False
    return count


def regime(bars: Sequence[Bar], n: int) -> dict:
    if len(bars) < n:
        return {"label": "unknown", "reason": f"need {n} bars, have {len(bars)}"}
    w = list(bars[-n:])
    highs = [b.high for b in w]
    lows = [b.low for b in w]
    closes = [b.close for b in w]
    hi, lo = _quantile(highs, 0.95), _quantile(lows, 0.05)
    width = hi - lo
    if width <= 0:
        return {"label": "unknown", "reason": "zero range"}
    path = sum(abs(b - a) for a, b in zip(closes[:-1], closes[1:]))
    er = abs(closes[-1] - closes[0]) / path if path else 0.0
    slope_norm = abs(_slope(closes) * n) / width
    zone = 0.15 * width
    t_hi = _touches(highs, lambda v: v >= hi - zone, lambda v: v < hi - zone - 0.3 * width)
    t_lo = _touches(lows, lambda v: v <= lo + zone, lambda v: v > lo + zone + 0.3 * width)
    root = math.sqrt(n)
    if er >= 2.5 / root and slope_norm > 0.3:
        label = "trend_up" if closes[-1] > closes[0] else "trend_down"
    elif er <= 1.5 / root and slope_norm <= 0.3 and t_hi >= 2 and t_lo >= 2:
        label = "box"
    elif er <= 1.5 / root:
        label = "chop"
    else:
        label = "unknown"
    return {"label": label, "hi": hi, "lo": lo, "width": width, "er": er,
            "slope_norm": slope_norm, "touches_hi": t_hi, "touches_lo": t_lo}


def entry_context(tf: str, tf_bars: Sequence[Bar], htf_bars: Sequence[Bar] = (),
                  n: Optional[int] = None) -> dict:
    """Snapshot for a signal on the last bar of ``tf_bars``."""
    n = n or REGIME_N.get(tf, 60)
    ctx: dict = {"tf": tf, "htf": HTF.get(tf)}
    if not tf_bars:
        return ctx
    last = tf_bars[-1]
    reg = regime(tf_bars, n)
    ctx["regime"] = reg["label"]
    ctx["er"] = reg.get("er")
    if reg["label"] != "unknown" or "hi" in reg:
        width = reg.get("width")
        if width:
            ctx["box_hi"], ctx["box_lo"] = reg["hi"], reg["lo"]
            ctx["box_pos"] = (last.close - reg["lo"]) / width
    a = atr(tf_bars)
    ctx["atr"] = a
    closes = [b.close for b in tf_bars]
    if len(closes) >= 20 and a:
        e = ema(closes, 20)
        ctx["ema20_dist_atr"] = (last.close - e[-1]) / a
        # Bars since close last crossed EMA20.
        side_now = closes[-1] >= e[-1]
        age = 0
        for c, ev in zip(reversed(closes), reversed(e)):
            if (c >= ev) != side_now:
                break
            age += 1
        ctx["trend_age"] = age
    window = tf_bars[-n:]
    rh = max(b.high for b in window)
    rl = min(b.low for b in window)
    ctx["range_pct"] = (last.close - rl) / (rh - rl) if rh > rl else None
    if htf_bars:
        hreg = regime(htf_bars, REGIME_N.get(ctx["htf"] or "", 30))
        ctx["htf_regime"] = hreg["label"]
        if "width" in hreg and hreg["width"]:
            ctx["htf_box_pos"] = (last.close - hreg["lo"]) / hreg["width"]
    return ctx
