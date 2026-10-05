"""Chart view for DS_F13_FVG_PD (DeepSeek-200 F13_FVG_PD, F13 프리미엄/디스카운트): its lines and entry conditions.

Rule: F9_FVG kept only on the right side of the swing range. A bullish fair value gap (low[t] > high[t-2], at
least 0.5 x ATR(14) wide) is a long zone [high[t-2], low[t]] for 50 bars; the first bar whose low reaches its top
decides it: a close at or above the gap's middle is the signal, anything else ends the zone. Bearish gap symmetric.
The long is kept only when the close is below the middle of the last confirmed swing high and low (discount), the
short only above it (premium). The chart draws the newest live gap of each side (from the gap bar to its first
touch), the swing high, swing low and their middle, and where the close sits in that range.

Same rules as research/deepseek200/lib_c.py ``entries()`` (PREREG_DEEPSEEK200.md sections 4 and 5; the live signal is
paperbot/dssig.py), written again with numpy and the vendored fg.atr (Wilder ATR 14); lib_c is not imported here.

Checked against the locked signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded contained: sys.path and the warnings filters restored). Bars: Binance USDT-M, the live
DeepSeek windows (config.DS_WINDOW_5M closed 5m bars, resampled by dssig.frame) at 24 bar closes from 2021-06 to
2026-09 per series, plus the full 2021-01..2026-09 series. "signals" = lib_c signals in the full series.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 767, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 756, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 174, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 212, "SOL30m_long_recall": 1, "SOL30m_long_precision": 1, "SOL30m_long_signals": 375, "SOL30m_short_recall": 1, "SOL30m_short_precision": 1, "SOL30m_short_signals": 432, "DOGE4h_long_recall": 1, "DOGE4h_long_precision": 1, "DOGE4h_long_signals": 52, "DOGE4h_short_recall": 1, "DOGE4h_short_precision": 1, "DOGE4h_short_signals": 46}
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
import fg_indicators as fg

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


def _atr(h, l, c):
    """fg.atr(df, 14), Wilder, as lib_c; computed on a plain frame of the bars so nothing in df.attrs reaches pandas."""
    if not len(c):
        return np.zeros(0)
    return _f(fg.atr(pd.DataFrame({"high": h, "low": l, "close": c}), 14))


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


EXP = 50            # gap zone life in bars
FVG_MIN_ATR = 0.5


def _fvg(n, h, l, c, atr):
    """{+1: bullish, -1: bearish} -> (first touch of a live gap on the bar, ... closing on the right side of that gap's
    middle, top and bottom of the newest live gap). A gap ends at its first touch."""
    out = {}
    gaps = {1: [], -1: []}
    if n >= 3:
        with np.errstate(invalid="ignore"):
            up = (l[2:] > h[:-2]) & ((l[2:] - h[:-2]) >= FVG_MIN_ATR * atr[2:])
            dn = (h[2:] < l[:-2]) & ((l[:-2] - h[2:]) >= FVG_MIN_ATR * atr[2:])
        gaps = {1: [(int(b), float(h[b - 2]), float(l[b])) for b in np.flatnonzero(up) + 2],
                -1: [(int(b), float(h[b]), float(l[b - 2])) for b in np.flatnonzero(dn) + 2]}
    for d, zs in gaps.items():
        touch, mid_ok = np.zeros(n, bool), np.zeros(n, bool)
        top, bot = np.full(n, np.nan), np.full(n, np.nan)
        for b, lo, hi in zs:
            s0, s1 = b + 1, min(n, b + 1 + EXP)
            if not (np.isfinite(lo) and np.isfinite(hi)):
                continue
            if s0 >= n:                                 # born on the last bar: drawn there (as history shows it later)
                top[b], bot[b] = hi, lo
                continue
            hit = (l[s0:s1] <= hi) if d > 0 else (h[s0:s1] >= lo)
            end = s1 - 1
            if hit.any():
                end = s = s0 + int(hit.argmax())
                touch[s] = True
                m = (lo + hi) / 2
                mid_ok[s] |= bool(c[s] >= m) if d > 0 else bool(c[s] <= m)
            top[b:end + 1], bot[b:end + 1] = hi, lo     # newer gaps are drawn over older ones
        out[d] = (touch, mid_ok, top, bot)
    return out


def view_DS_F13_FVG_PD(df, tf):
    h, l, c = (_f(df[k]) for k in ("high", "low", "close"))
    n = len(c)
    S = _structure(h, l, c)
    atr = _atr(h, l, c)
    G = _fvg(n, h, l, c, atr)
    (t_l, m_l, top_l, bot_l), (t_s, m_s, top_s, bot_s) = G[1], G[-1]
    disc, prem, eq, pos = _pd(c, S)
    long = [
        ("상승 갭(FVG)에 처음 닿음", t_l),
        ("종가가 갭 중간 이상", m_l),
        ("할인 구간(스윙 범위 아래 절반)", disc),
    ]
    short = [
        ("하락 갭(FVG)에 처음 닿음", t_s),
        ("종가가 갭 중간 이하", m_s),
        ("프리미엄 구간(스윙 범위 위 절반)", prem),
    ]
    return {
        "overlays": [
            {"name": "마지막 스윙 고점", "values": S["hi"]},
            {"name": "균형가(스윙 범위 50%)", "values": eq},
            {"name": "마지막 스윙 저점", "values": S["lo"]},
            {"name": "상승 갭 위", "values": top_l},
            {"name": "상승 갭 아래", "values": bot_l},
            {"name": "하락 갭 위", "values": top_s},
            {"name": "하락 갭 아래", "values": bot_s},
        ],
        "panes": [_pd_pane(pos)],
        "long": [(k, np.asarray(v, bool)) for k, v in long],
        "short": [(k, np.asarray(v, bool)) for k, v in short],
    }
