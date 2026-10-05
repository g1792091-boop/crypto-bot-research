"""Chart view for DS_F13_RAID_PD (DeepSeek-200 F13_RAID_PD, F13 프리미엄/디스카운트): its lines and entry conditions.

Rule: F11_RAID kept only on the right side of the swing range. The last confirmed swing low, the first time a
low goes below it (once per level; a new swing low is a new level), is a long signal when the same bar closes back
above it; the swing high gives the short the same way. The long is kept only when the close is below the middle of
the last confirmed swing high and low (discount), the short only above it (premium). The chart draws the swing high,
swing low and their middle, and where the close sits in that range.

Same rules as research/deepseek200/lib_c.py ``entries()`` (PREREG_DEEPSEEK200.md sections 4 and 5; the live signal is
paperbot/dssig.py), written again with numpy; lib_c is not imported here.

Checked against the locked signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded contained: sys.path and the warnings filters restored). Bars: Binance USDT-M, the live
DeepSeek windows (config.DS_WINDOW_5M closed 5m bars, resampled by dssig.frame) at 24 bar closes from 2021-06 to
2026-09 per series, plus the full 2021-01..2026-09 series. "signals" = lib_c signals in the full series.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 4157, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 4347, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 1102, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 1132, "SOL30m_long_recall": 1, "SOL30m_long_precision": 1, "SOL30m_long_signals": 2107, "SOL30m_short_recall": 1, "SOL30m_short_precision": 1, "SOL30m_short_signals": 2116, "DOGE4h_long_recall": 1, "DOGE4h_long_precision": 1, "DOGE4h_long_signals": 304, "DOGE4h_short_recall": 1, "DOGE4h_short_precision": 1, "DOGE4h_short_signals": 270}
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


def _pd(c, S):
    """(discount, premium, equilibrium, position of the close in the swing range 0..1) from the last confirmed swing
    high and low, only while the swing low is below the swing high."""
    hi, lo = S["hi"], S["lo"]
    with np.errstate(invalid="ignore", divide="ignore"):
        ok = lo < hi
        eq = (hi + lo) / 2
        pos = np.where(ok, (c - lo) / (hi - lo), np.nan)
        return ok & (c < eq), ok & (c > eq), eq, pos


def _pd_pane(pos):
    return {"name": "스윙 범위 안 위치", "series": [{"name": "위치(0 저점 · 0.5 균형가 · 1 고점)", "values": pos}],
            "levels": [0, 0.5, 1]}


def view_DS_F13_RAID_PD(df, tf):
    h, l, c = (_f(df[k]) for k in ("high", "low", "close"))
    S = _structure(h, l, c)
    disc, prem, eq, pos = _pd(c, S)
    with np.errstate(invalid="ignore"):
        long = [
            ("아직 아무 봉도 찌르지 않은 스윙 저점 있음", S["raid_lo"]),
            ("저가가 스윙 저점 아래로 찌름", l < S["lo"]),
            ("종가는 스윙 저점 위로 회복", c > S["lo"]),
            ("할인 구간(스윙 범위 아래 절반)", disc),
        ]
        short = [
            ("아직 아무 봉도 찌르지 않은 스윙 고점 있음", S["raid_hi"]),
            ("고가가 스윙 고점 위로 찌름", h > S["hi"]),
            ("종가는 스윙 고점 아래로 복귀", c < S["hi"]),
            ("프리미엄 구간(스윙 범위 위 절반)", prem),
        ]
    return {
        "overlays": [
            {"name": "마지막 스윙 고점", "values": S["hi"]},
            {"name": "균형가(스윙 범위 50%)", "values": eq},
            {"name": "마지막 스윙 저점", "values": S["lo"]},
        ],
        "panes": [_pd_pane(pos)],
        "long": [(k, np.asarray(v, bool)) for k, v in long],
        "short": [(k, np.asarray(v, bool)) for k, v in short],
    }
