"""Chart view for DS_F3_BOS_ZONE (DeepSeek-200 F3_BOS_ZONE, F3 구조 돌파·공급수요): its lines and entry conditions.

Rule: every up structure break (BOS or MSS; the first break of a series only sets the structure) makes a demand
zone = [low, high] of the last confirmed swing-low bar at the break. It lives 50 bars and dies on a close below its
low. The first bar that touches it (low <= zone top) and closes as a reversal candle (close > open, close > previous
high, close > EMA200, close >= zone low) is the long signal; a touch without that candle does not end the zone (the
PREREG's 'wait' rule for this definition only). Short: down break, supply zone = [low, high] of the last swing-high
bar, dies on a close above its top; touch high >= zone low; close < open, close < previous low, close < EMA200,
close <= zone top. Several zones can be alive at once: a zone condition holds when one zone meets it. The chart draws
the newest live zone of each side as its top and bottom lines (from the break bar to the bar it ends), and EMA200.

Same rules as research/deepseek200/lib_c.py ``entries()`` (PREREG_DEEPSEEK200.md sections 4 and 5; the live signal is
paperbot/dssig.py), written again with numpy and the vendored pine_ema (EMA200); lib_c is not imported here.

Checked against the locked signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded contained: sys.path and the warnings filters restored). Bars: Binance USDT-M, the live
DeepSeek windows (config.DS_WINDOW_5M closed 5m bars, resampled by dssig.frame) at 24 bar closes from 2021-06 to
2026-09 per series, plus the full 2021-01..2026-09 series. "signals" = lib_c signals in the full series.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 1184, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 1104, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 309, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 260, "SOL30m_long_recall": 1, "SOL30m_long_precision": 1, "SOL30m_long_signals": 564, "SOL30m_short_recall": 1, "SOL30m_short_precision": 1, "SOL30m_short_signals": 568, "DOGE4h_long_recall": 1, "DOGE4h_long_precision": 1, "DOGE4h_long_signals": 52, "DOGE4h_short_recall": 1, "DOGE4h_short_precision": 1, "DOGE4h_short_signals": 78}
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
import pine_indicators as pi

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


def _breaks(c, S):
    """(up, down): the bar's close breaks the still-unbroken last swing high (low) and not the other level as well
    (a close beyond both, possible only when the levels cross, counts as neither)."""
    with np.errstate(invalid="ignore"):
        up = S["arm_hi"] & (c > S["hi"])
        dn = S["arm_lo"] & (c < S["lo"])
    return up & ~dn, dn & ~up


EXP = 50            # zone life in bars after the break bar


def _zones(n, o, h, l, c, e200, S):
    """{+1: demand, -1: supply} -> (a live zone not closed through on the bar, ... that the bar touches, top and bottom
    of the newest live zone). A zone ends at the first close through it or at its signal (one per zone)."""
    up, dn = _breaks(c, S)
    with np.errstate(invalid="ignore"):
        rev = {1: (c > o) & (c > _prev(h)) & (c > e200), -1: (c < o) & (c < _prev(l)) & (c < e200)}
    out = {}
    for d, ev, idx in ((1, up & (S["before"] != 0), S["lo_idx"]), (-1, dn & (S["before"] != 0), S["hi_idx"])):
        live, touch = np.zeros(n, bool), np.zeros(n, bool)
        top, bot = np.full(n, np.nan), np.full(n, np.nan)
        for b in np.flatnonzero(ev):
            k = int(idx[b])
            lo, hi = (float(l[k]), float(h[k])) if k >= 0 else (np.nan, np.nan)
            if not (np.isfinite(lo) and np.isfinite(hi)):
                continue
            end = min(n - 1, b + EXP)
            for s in range(b + 1, min(n, b + 1 + EXP)):
                if (c[s] < lo) if d > 0 else (c[s] > hi):
                    end = s                      # closed through the zone: gone
                    break
                live[s] = True
                if (l[s] <= hi) if d > 0 else (h[s] >= lo):
                    touch[s] = True
                    if rev[d][s]:
                        end = s                  # the signal
                        break
            top[b:end + 1], bot[b:end + 1] = hi, lo     # newer zones are drawn over older ones
        out[d] = (live, touch, top, bot)
    return out


def view_DS_F3_BOS_ZONE(df, tf):
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    n = len(c)
    S = _structure(h, l, c)
    e200 = _f(pi.pine_ema(c, 200)) if n else np.zeros(0)
    Z = _zones(n, o, h, l, c, e200, S)
    (live_l, touch_l, top_l, bot_l), (live_s, touch_s, top_s, bot_s) = Z[1], Z[-1]
    hp, lp = _prev(h), _prev(l)
    with np.errstate(invalid="ignore"):
        long = [
            ("살아 있는 수요 존 있음(돌파 후 50봉 안)", live_l),
            ("저가가 수요 존에 닿음", touch_l),
            ("양봉 마감", c > o),
            ("직전 봉 고가 위로 마감", c > hp),
            ("종가가 EMA200 위", c > e200),
        ]
        short = [
            ("살아 있는 공급 존 있음(돌파 후 50봉 안)", live_s),
            ("고가가 공급 존에 닿음", touch_s),
            ("음봉 마감", c < o),
            ("직전 봉 저가 아래로 마감", c < lp),
            ("종가가 EMA200 아래", c < e200),
        ]
    return {
        "overlays": [
            {"name": "수요 존 위", "values": top_l},
            {"name": "수요 존 아래", "values": bot_l},
            {"name": "공급 존 위", "values": top_s},
            {"name": "공급 존 아래", "values": bot_s},
            {"name": "EMA200", "values": e200},
        ],
        "panes": [],
        "long": [(k, np.asarray(v, bool)) for k, v in long],
        "short": [(k, np.asarray(v, bool)) for k, v in short],
    }
