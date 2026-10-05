"""Chart view for DS_F12_MSS_DISP (DeepSeek-200 F12_MSS_DISP, F12 구조 전환 MSS): its lines and entry conditions.

Rule: F12_MSS whose break bar is a displacement candle: the long needs close - open >= 1.2 x ATR(14), the short
open - close >= 1.2 x ATR(14). The chart shows the last swing high and low, the swing points joined as a zigzag, the
structure state and the candle body in ATR units.

Same rules as research/deepseek200/lib_c.py ``entries()`` (PREREG_DEEPSEEK200.md sections 4 and 5; the live signal is
paperbot/dssig.py), written again with numpy and the vendored fg.atr (Wilder ATR 14); lib_c is not imported here.

Checked against the locked signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded contained: sys.path and the warnings filters restored). Bars: Binance USDT-M, the live
DeepSeek windows (config.DS_WINDOW_5M closed 5m bars, resampled by dssig.frame) at 24 bar closes from 2021-06 to
2026-09 per series, plus the full 2021-01..2026-09 series. "signals" = lib_c signals in the full series.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 1028, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 1121, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 309, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 329, "SOL30m_long_recall": 1, "SOL30m_long_precision": 1, "SOL30m_long_signals": 530, "SOL30m_short_recall": 1, "SOL30m_short_precision": 1, "SOL30m_short_signals": 493, "DOGE4h_long_recall": 1, "DOGE4h_long_precision": 1, "DOGE4h_long_signals": 68, "DOGE4h_short_recall": 1, "DOGE4h_short_precision": 1, "DOGE4h_short_signals": 56}
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


def _breaks(c, S):
    """(up, down): the bar's close breaks the still-unbroken last swing high (low) and not the other level as well
    (a close beyond both, possible only when the levels cross, counts as neither)."""
    with np.errstate(invalid="ignore"):
        up = S["arm_hi"] & (c > S["hi"])
        dn = S["arm_lo"] & (c < S["lo"])
    return up & ~dn, dn & ~up


def _raw_breaks(c, S):
    """(up, down) before the 'not both' rule: the close beyond the still-unbroken last swing high (low). The close
    condition shown is 'beyond this level and not beyond the other unbroken one', so its AND with the 'unbroken'
    condition is exactly ``_breaks``."""
    with np.errstate(invalid="ignore"):
        return S["arm_hi"] & (c > S["hi"]), S["arm_lo"] & (c < S["lo"])


def _zigzag(h, l, ph, pl):
    """Swing points joined in time order: the high of each swing high, the low of each swing low, drawn on the swing
    bar itself (known 3 bars later). A bar that is both takes the kind opposite to the previous point."""
    n = len(h)
    z = np.full(n, np.nan)
    last = 0
    for t in np.flatnonzero(ph | pl):
        p = t - SW
        if ph[t] and pl[t]:
            z[p], last = (l[p], -1) if last > 0 else (h[p], 1)
        elif ph[t]:
            z[p], last = h[p], 1
        else:
            z[p], last = l[p], -1
    return z


def _struct_lines(h, l, S):
    return [
        {"name": "마지막 스윙 고점", "values": S["hi"]},
        {"name": "마지막 스윙 저점", "values": S["lo"]},
        {"name": "스윙 지그재그", "values": _zigzag(h, l, S["ph"], S["pl"]), "join": True},
    ]


def _flow_pane(S):
    return {"name": "구조 흐름", "levels": [0],
            "series": [{"name": "흐름(+1 오름세 / -1 내림세)", "values": S["after"].astype(float)}]}


def view_DS_F12_MSS_DISP(df, tf):
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    S = _structure(h, l, c)
    up, dn = _raw_breaks(c, S)                 # raw: the AND below equals _breaks
    atr = _atr(h, l, c)
    with np.errstate(invalid="ignore", divide="ignore"):
        body = np.where(atr > 0, (c - o) / atr, np.nan)
        long = [
            ("흐름이 내림세였음(마지막 돌파가 아래)", S["before"] == -1),
            ("종가로 아직 안 넘은 스윙 고점 있음", S["arm_hi"]),
            ("종가가 스윙 고점 위로 마감", (c > S["hi"]) & ~dn),
            ("강한 양봉(몸통 ≥ ATR×1.2)", (c - o) >= 1.2 * atr),
        ]
        short = [
            ("흐름이 오름세였음(마지막 돌파가 위)", S["before"] == 1),
            ("종가로 아직 안 넘은 스윙 저점 있음", S["arm_lo"]),
            ("종가가 스윙 저점 아래로 마감", (c < S["lo"]) & ~up),
            ("강한 음봉(몸통 ≥ ATR×1.2)", (o - c) >= 1.2 * atr),
        ]
    return {
        "overlays": _struct_lines(h, l, S),
        "panes": [
            _flow_pane(S),
            {"name": "몸통 크기(ATR 배수)", "series": [{"name": "몸통÷ATR(+양봉 / -음봉)", "values": body}],
             "levels": [1.2, -1.2]},
        ],
        "long": [(k, np.asarray(v, bool)) for k, v in long],
        "short": [(k, np.asarray(v, bool)) for k, v in short],
    }
