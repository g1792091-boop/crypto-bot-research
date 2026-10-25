"""Entry timing variants, market orders only (the owners: "지정가 그냥 하지마"). Each returns the bar index and the raw
price of a market entry, or None when the condition never came (the signal is skipped).

- now:      the bar opening at the signal bar's close; the paper trade's own ref_price when given (live fills ~30 s
            after the close), else that bar's open.
- wait:     the open of the bar ``min`` minutes after the close.
- pullback: wait until price trades ``x`` ATR against the signal from the reference price, within ``win`` minutes;
            then a market order at that level (or at the bar open when the bar opens beyond it). A market order on a
            touch fills near the level; slippage is added by the simulator as for every market fill.
- confirm:  the first candle of ``bar`` minutes (UTC-aligned from the close) that closes in the signal's direction,
            within ``win`` minutes; a market order at the next bar's open.
The stop is then 2 ATR from this new entry (the bot's rule: the stop distance is measured from the actual entry)."""
from __future__ import annotations

import numpy as np

MIN = 60_000


def entry(kind: str, p: dict, A: dict, bar_close: int, side: int, atr: float, ref: float | None, bar_ms: int):
    ts = A["ts"]
    e0 = int(np.searchsorted(ts, bar_close))
    if e0 >= len(ts):
        return None
    if kind == "now":
        return e0, (ref if ref is not None else float(A["o"][e0]))
    if kind == "wait":
        e = int(np.searchsorted(ts, bar_close + p["min"] * MIN))
        return (e, float(A["o"][e])) if e < len(ts) else None
    ref0 = ref if ref is not None else float(A["o"][e0])
    until = bar_close + p["win"] * MIN
    if kind == "pullback":
        level = ref0 - side * p["x"] * atr
        j = e0
        while j < len(ts) and ts[j] < until:
            if j > e0 and (A["o"][j] - level) * side <= 0:
                return j, float(A["o"][j])
            if (A["l"][j] <= level) if side > 0 else (A["h"][j] >= level):
                return j, float(level)
            j += 1
        return None
    if kind == "confirm":
        B = p["bar"] * MIN
        k = 0
        while bar_close + (k + 1) * B <= until:
            a, b = bar_close + k * B, bar_close + (k + 1) * B
            i0, i1 = int(np.searchsorted(ts, a)), int(np.searchsorted(ts, b))
            if i1 > i0:
                if side * (A["c"][i1 - 1] - A["o"][i0]) > 0:
                    return (i1, float(A["o"][i1])) if i1 < len(ts) else None
            k += 1
        return None
    raise ValueError(kind)
