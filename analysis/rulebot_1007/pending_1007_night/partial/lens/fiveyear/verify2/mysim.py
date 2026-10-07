"""Independent house-exit simulator (written from paperbot/engine.py + ladder.py semantics, not from profiles._scan).

Per signal: entry at next bar open (+slippage), stop0 = raw open -/+ 2 ATR(signal bar), ladder locks on net ROE (best
price incl. the current bar, applied from the next bar), gap at open -> exit at open, intrabar stop -> exit at stop,
mark liq -> -margin.  Funding: constant 0.01%/8h accrued per bar (as the 5-year studies).  Leverage/liq from the repo's
sizing.size_position with paper-v4 settings, group 'normal' (or 'best'), $5,000 equity.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
REPO = '/home/user/crypto-bot-research'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import numpy as np  # noqa: E402

from paperbot.config import v3_settings  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402
from paperbot.margin import Brackets  # noqa: E402

S4 = v3_settings()
BR = Brackets.example()
SLIP, FEE = S4.slippage_frac, S4.taker_fee
RT = 2 * (FEE + SLIP)
TFMIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
F8 = 0.0001


def lev_for(side, raw, atr, group="normal", equity=5000.0):
    fill = raw * (1 + side * SLIP)
    d = size_position(S4, equity, side, fill, raw - side * 2.0 * atr, group, BR, atr=atr, min_notional=5.0)
    if not d.ok:
        return 0, math.nan
    return d.leverage, d.liq_price


def lock_for(best):
    ft = 0.10 + 0.02
    if not best >= ft - 1e-12:
        return None
    return 0.10 + 0.05 * math.floor((best - ft) / 0.05 + 1e-9)


def sim_one(o, h, l, c, i, side, atr, lev, liq, tf, maxbars=20000):
    """Returns (ret_per_notional_net, gross_move, stop_frac, held, reason)."""
    n = len(o)
    if i + 1 >= n:
        return None
    raw = o[i + 1]
    fill = raw * (1 + side * SLIP)
    stop0 = raw - side * 2.0 * atr
    stop = stop0
    stop_frac = abs(fill - stop0) / fill
    fb = F8 * TFMIN[tf] / 480.0
    best = fill
    locked = None
    for k, j in enumerate(range(i + 1, min(n, i + 1 + maxbars))):
        fund = fb * (k + 1)
        if k > 0:
            if (o[j] - liq) * side <= 0:
                return -1.0 / lev, side * (liq / raw - 1), stop_frac, k + 1, "LIQ"
            if (o[j] - stop) * side <= 0:
                ex_raw = o[j]
                ex = ex_raw * (1 - side * SLIP)
                ret = side * (ex / fill - 1) - FEE - FEE * ex / fill - fund
                return max(ret, -1.0 / lev), side * (ex_raw / raw - 1), stop_frac, k + 1, "GAP"
        hit = (l[j] <= stop) if side > 0 else (h[j] >= stop)
        if hit:
            ex = stop * (1 - side * SLIP)
            if side * (ex - fill) / fill < -1.0 / lev:      # beyond margin -> liquidated
                return -1.0 / lev, side * (stop / raw - 1), stop_frac, k + 1, "LIQ"
            ret = side * (ex / fill - 1) - FEE - FEE * ex / fill - fund
            return ret, side * (stop / raw - 1), stop_frac, k + 1, ("LOCK" if locked is not None else "SL")
        hl = (l[j] <= liq) if side > 0 else (h[j] >= liq)
        if hl:
            return -1.0 / lev, side * (liq / raw - 1), stop_frac, k + 1, "LIQ"
        best = max(best, h[j]) if side > 0 else min(best, l[j])
        broe = lev * (side * (best / fill - 1) - RT - fund)
        lk = lock_for(broe)
        if lk is not None and (locked is None or lk > locked + 1e-12):
            px = fill * (1 + side * (lk / lev + RT + fund))
            stop = max(stop, px) if side > 0 else min(stop, px)
            locked = lk
    return None   # unresolved
