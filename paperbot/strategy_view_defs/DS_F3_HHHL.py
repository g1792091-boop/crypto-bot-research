"""Chart view for DS_F3_HHHL (DeepSeek-200 F3_HHHL, F3 구조 돌파·공급수요): its lines and entry conditions.

Rule: on the bar that confirms a swing low (3 bars after it), long when the new low is above the previous swing
low (higher low) and the last swing high is above the one before it (higher high). On the bar that confirms a swing
high, short when the new high is below the previous one (lower high) and the last swing low is below the one before
it (lower low). The chart joins the swing highs and, separately, the swing lows, so the rising or falling steps are
visible.

Same rules as research/deepseek200/lib_c.py ``entries()`` (PREREG_DEEPSEEK200.md sections 4 and 5; the live signal is
paperbot/dssig.py), written again with numpy; lib_c is not imported here.

Checked against the locked signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded contained: sys.path and the warnings filters restored). Bars: Binance USDT-M, the live
DeepSeek windows (config.DS_WINDOW_5M closed 5m bars, resampled by dssig.frame) at 24 bar closes from 2021-06 to
2026-09 per series, plus the full 2021-01..2026-09 series. "signals" = lib_c signals in the full series.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 5810, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 5470, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 1487, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 1345, "SOL30m_long_recall": 1, "SOL30m_long_precision": 1, "SOL30m_long_signals": 2794, "SOL30m_short_recall": 1, "SOL30m_short_precision": 1, "SOL30m_short_signals": 2732, "DOGE4h_long_recall": 1, "DOGE4h_long_precision": 1, "DOGE4h_long_signals": 341, "DOGE4h_short_recall": 1, "DOGE4h_short_precision": 1, "DOGE4h_short_signals": 362}
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

SW = 3              # swing pivot: 3 bars on each side, known 3 bars later (PREREG section 4)


def _f(x):
    """float ndarray; NaN kept."""
    if isinstance(x, pd.Series):
        x = x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _prev(x, k=1):
    x = _f(x)
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _pivots(h, l):
    """(ph, pl): True at bar t when the swing high (low) of bar t-3 is confirmed: its high strictly above (low strictly
    below) the 3 bars on each side."""
    n = len(h)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    if n >= 2 * SW + 1:
        wh = sliding_window_view(h, 2 * SW + 1)
        wl = sliding_window_view(l, 2 * SW + 1)
        with np.errstate(invalid="ignore"):
            ph[2 * SW:] = (wh[:, SW] > wh[:, :SW].max(1)) & (wh[:, SW] > wh[:, SW + 1:].max(1))
            pl[2 * SW:] = (wl[:, SW] < wl[:, :SW].min(1)) & (wl[:, SW] < wl[:, SW + 1:].min(1))
    return ph, pl


def _structure(h, l, c):
    """The PREREG section 4 structure state in one pass. Per bar t, after the swings confirmed at t: the last and the
    previous confirmed swing levels (hi, lo, prev_hi, prev_lo) and the bar of the last ones (hi_idx, lo_idx); whether
    the last level can still be broken by a close (arm_hi, arm_lo: one break per level) or swept by a wick (raid_hi,
    raid_lo: one sweep per level); the structure before and after bar t (+1 up, -1 down, 0 no break yet)."""
    n = len(c)
    ph, pl = _pivots(h, l)
    hl, ll, cl, phl, pll = h.tolist(), l.tolist(), c.tolist(), ph.tolist(), pl.tolist()
    nan = float("nan")
    hi, lo, phi, plo = ([nan] * n for _ in range(4))
    hidx, lidx, before, after = ([0] * n for _ in range(4))
    arm_hi, arm_lo, raid_hi, raid_lo = ([False] * n for _ in range(4))
    h_lvl = l_lvl = h_prev = l_prev = nan
    h_i = l_i = -1
    a_hi = a_lo = r_hi = r_lo = False
    state = 0
    for t in range(n):
        if phl[t]:
            h_prev, h_lvl, h_i = h_lvl, hl[t - SW], t - SW
            a_hi = r_hi = True
        if pll[t]:
            l_prev, l_lvl, l_i = l_lvl, ll[t - SW], t - SW
            a_lo = r_lo = True
        hi[t], lo[t], phi[t], plo[t], hidx[t], lidx[t] = h_lvl, l_lvl, h_prev, l_prev, h_i, l_i
        arm_hi[t], arm_lo[t], raid_hi[t], raid_lo[t], before[t] = a_hi, a_lo, r_hi, r_lo, state
        up = a_hi and cl[t] > h_lvl
        dn = a_lo and cl[t] < l_lvl
        if up and not dn:          # both on one bar (crossed levels): neither counts, nothing changes
            state, a_hi = 1, False
        elif dn and not up:
            state, a_lo = -1, False
        if r_hi and hl[t] > h_lvl:
            r_hi = False
        if r_lo and ll[t] < l_lvl:
            r_lo = False
        after[t] = state
    out = {"ph": ph, "pl": pl}
    out.update({k: np.asarray(v, dtype=float) for k, v in (("hi", hi), ("lo", lo), ("prev_hi", phi), ("prev_lo", plo))})
    out.update({k: np.asarray(v, dtype=np.int64) for k, v in (("hi_idx", hidx), ("lo_idx", lidx), ("before", before),
                                                                ("after", after))})
    out.update({k: np.asarray(v, dtype=bool) for k, v in (("arm_hi", arm_hi), ("arm_lo", arm_lo), ("raid_hi", raid_hi),
                                                            ("raid_lo", raid_lo))})
    return out


def _swing_points(x, conf):
    """x of each swing bar, drawn on the swing bar itself (known 3 bars later); NaN elsewhere."""
    z = np.full(len(x), np.nan)
    p = np.flatnonzero(conf) - SW
    z[p] = x[p]
    return z


def view_DS_F3_HHHL(df, tf):
    h, l, c = (_f(df[k]) for k in ("high", "low", "close"))
    S = _structure(h, l, c)
    with np.errstate(invalid="ignore"):
        long = [
            ("방금 스윙 저점 확정(3봉 전 저점)", S["pl"]),
            ("저점이 높아짐(새 저점 > 직전 저점)", S["lo"] > S["prev_lo"]),
            ("고점도 높아짐(마지막 고점 > 직전 고점)", S["hi"] > S["prev_hi"]),
        ]
        short = [
            ("방금 스윙 고점 확정(3봉 전 고점)", S["ph"]),
            ("고점이 낮아짐(새 고점 < 직전 고점)", S["hi"] < S["prev_hi"]),
            ("저점도 낮아짐(마지막 저점 < 직전 저점)", S["lo"] < S["prev_lo"]),
        ]
    return {
        "overlays": [
            {"name": "스윙 고점 잇기", "values": _swing_points(h, S["ph"]), "join": True},
            {"name": "스윙 저점 잇기", "values": _swing_points(l, S["pl"]), "join": True},
        ],
        "panes": [],
        "long": [(k, np.asarray(v, bool)) for k, v in long],
        "short": [(k, np.asarray(v, bool)) for k, v in short],
    }
