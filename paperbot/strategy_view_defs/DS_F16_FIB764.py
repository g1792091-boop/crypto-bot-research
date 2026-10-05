"""Chart view for DS_F16_FIB764 (DeepSeek-200 F16_FIB764, research/deepseek200/PREREG_DEEPSEEK200.md section 5):
what a trader draws for it and its entry conditions, worded for the owners.

Fibonacci 76.4% retracement: an impulse leg (a swing high confirmed with the last confirmed swing low at most 30 bars
before it and at least 3 ATR below it; down legs mirrored) waits 50 bars for a pull-back to its 76.4% line
(long: R = H - 0.764 x (H - L); short: R = L + 0.764 x (H - L)). The first bar whose low (short: high) reaches R
gives the signal when no bar up to and including it went beyond the leg's end (long: high > H; short: low < L) and
it closes on the trend side of R (long: close > R). The chart draws the leg the checklist reads: its high, its low
and the 76.4% line, and a pane with how deep the close has pulled back into that leg (0% = the leg's end, 100% = its
start; blank on the bar that breaks the leg's end).

Checked against the research signal (lib_c.entries of research/deepseek200/lib_c.py, loaded by path inside
entry_marks._contained(), so sys.path and the warnings filters are restored): AND of the long (short) conditions
equals the F16_FIB764 long (short) signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1}
Series: the full Binance USDT-M bar files 2021-01..2026-09 (BTC 15m 201,398 bars, ETH 1h 50,351, SOL 4h
12,588, DOGE 30m 100,701; signals checked: long 3,386, short 3,342) and 12 live-service frames
built from 5m bars as paperbot.dssig.frame does (config.DS_WINDOW_5M; BTC 15m, ETH 1h, LTC 4h, BCH 30m at
three end dates each; signals checked: long 382, short 379): recall = precision = 1 on all
24 live-frame sides too, 0 differing bars. tests/test_strategy_views_ds_f16_f17.py repeats the check.
The same-bar long/short rule took out no bar of these series; the last line of each side
carries it.
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import fg_indicators as fg

_F = 0.764                       # PREREG F16 table (lib_c.FIB["F16_FIB764"])
_PCT = "76.4%"
_EXP = 50                      # a zone waits 50 bars after the bar that made it (PREREG section 4)
_SW = 3                        # swing pivot: 3 bars on each side, known 3 bars later (PREREG section 4)
_LEG_ATR, _LEG_BARS = 3.0, 30  # impulse leg: at least 3 ATR14, at most 30 bars (lib_c.ZONE_ATR_LEG, LEG_MAX_BARS)


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _atr(df):
    """ATR14 exactly as lib_c reads it (fg.atr, Wilder); an empty frame gives an empty array."""
    if len(df) == 0:
        return np.zeros(0)
    return fg.atr(df, 14).to_numpy(dtype=float)


def _pivots(h, l, k=_SW):
    """lib_c.pivots_conf: True at bar t when the swing high / low of bar t-3 is confirmed (strictly above / below the
    3 bars on each side)."""
    n = len(h)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    if n >= 2 * k + 1:
        wh = sliding_window_view(np.asarray(h, float), 2 * k + 1)
        wl = sliding_window_view(np.asarray(l, float), 2 * k + 1)
        with np.errstate(invalid="ignore"):
            okh = (wh[:, k] > wh[:, :k].max(1)) & (wh[:, k] > wh[:, k + 1:].max(1))
            okl = (wl[:, k] < wl[:, :k].min(1)) & (wl[:, k] < wl[:, k + 1:].min(1))
        ph[2 * k:] = okh
        pl[2 * k:] = okl
    return ph, pl


def _last_swing(conf, src):
    """lib_c.structure's "last confirmed swing" at each bar: (level, bar) of the newest swing confirmed at or before
    it (the swing bar is 3 bars before its confirmation; level = that bar's high / low); NaN / -1 before the first."""
    n = len(src)
    idx = np.maximum.accumulate(np.where(conf, np.arange(n) - _SW, -1)) if n else np.zeros(0, int)
    lvl = np.where(idx >= 0, src[np.clip(idx, 0, None)], np.nan) if n else np.zeros(0)
    return lvl, idx


def _legs(h, l, atr):
    """lib_c.impulse_legs: (confirm bar, H, L, dir). Up leg: a swing high confirmed at t paired with the last
    confirmed swing low (at most 30 bars before the swing high, range >= 3 ATR14 of bar t); down leg mirrored."""
    ph, pl = _pivots(h, l)
    lo, lo_i = _last_swing(pl, l)
    hi, hi_i = _last_swing(ph, h)
    legs = []
    with np.errstate(invalid="ignore"):
        for t in np.flatnonzero(ph):
            p, q = t - _SW, lo_i[t]
            H, Lw = h[p], lo[t]
            if q >= 0 and p - q <= _LEG_BARS and H - Lw >= _LEG_ATR * atr[t]:
                legs.append((int(t), float(H), float(Lw), 1))
        for t in np.flatnonzero(pl):
            p, q = t - _SW, hi_i[t]
            Lw, H = l[p], hi[t]
            if q >= 0 and p - q <= _LEG_BARS and H - Lw >= _LEG_ATR * atr[t]:
                legs.append((int(t), float(H), float(Lw), -1))
    return legs


def _focus(h, l, c, legs, d):
    """The 76.4% lines of one side's legs, read bar by bar exactly as lib_c.resolve_zones reads them.

    A line R (lo = hi = R, as lib_c builds the zone) waits on bars birth+1 .. birth+50 until its first touch (long:
    low <= R, short: high >= R); a bar beyond the leg's end (long: high > H, short: low < L) at or before that touch
    ends it; the touch bar gives the signal when it closes on the trend side of R (long: close > R). A line gives at
    most one signal and is used up by its first touch.

    Every checklist line is read from ONE leg per bar (the focus): a leg that gives the signal on this bar if there is
    one, else a touched one, the one nearest to price, the newest. So AND of the lines equals "some leg gives the
    signal on this bar" (lib_c's signal before the same-bar long/short rule)."""
    n = len(c)
    best = [None] * n
    for b, H, Lw, dd in legs:
        if dd != d:
            continue
        r = H - _F * (H - Lw) if d > 0 else Lw + _F * (H - Lw)     # the same float arithmetic as lib_c
        kill = H if d > 0 else Lw
        s0, s1 = b + 1, min(n, b + 1 + _EXP)
        if s0 >= n or not np.isfinite(r):
            continue
        with np.errstate(invalid="ignore"):
            tch = (l[s0:s1] <= r) if d > 0 else (h[s0:s1] >= r)
            kil = (h[s0:s1] > kill) if d > 0 else (l[s0:s1] < kill)
        t_touch = s0 + int(tch.argmax()) if tch.any() else -1
        t_kill = s0 + int(kil.argmax()) if kil.any() else -1
        last = s1 - 1
        if t_touch >= 0:
            last = min(last, t_touch)
        if t_kill >= 0:
            last = min(last, t_kill)
        near = r if d > 0 else -r
        for t in range(s0, last + 1):
            touched = t == t_touch
            kept = t != t_kill
            ok = bool(c[t] > r) if d > 0 else bool(c[t] < r)
            key = (touched and kept and ok, touched, near, b)
            if best[t] is None or key > best[t][0]:
                best[t] = (key, touched, kept, ok, r, H, Lw)
    out = {k: np.zeros(n, bool) for k in ("on", "touch", "kept", "conf", "sig")}
    out.update({k: np.full(n, np.nan) for k in ("r", "H", "L")})
    for t, z in enumerate(best):
        if z is None:
            continue
        key, touched, kept, ok, r, H, Lw = z
        out["on"][t], out["touch"][t], out["kept"][t], out["conf"][t], out["sig"][t] = True, touched, kept, ok, key[0]
        out["r"][t], out["H"][t], out["L"][t] = r, H, Lw
    return out


def view_DS_F16_FIB764(df, tf):
    """F16_FIB764: first touch of the 76.4% retracement of a 3-ATR impulse leg, leg end not broken, close on the trend
    side of the line. Exact."""
    _o, h, l, c = _cols(df)
    legs = _legs(h, l, _atr(df))
    L = _focus(h, l, c, legs, 1)
    S = _focus(h, l, c, legs, -1)
    with np.errstate(invalid="ignore", divide="ignore"):             # blank on the bar that breaks the leg's end
        depth_l = np.where(L["kept"], (L["H"] - c) / (L["H"] - L["L"]) * 100.0, np.nan)
        depth_s = np.where(S["kept"], (c - S["L"]) / (S["H"] - S["L"]) * 100.0, np.nan)
    return {
        "overlays": [
            {"name": "상승 구간 고점(넘으면 무효)", "values": L["H"]},
            {"name": f"롱 {_PCT} 되돌림선", "values": L["r"]},
            {"name": "상승 구간 시작 저점", "values": L["L"]},
            {"name": "하락 구간 저점(깨면 무효)", "values": S["L"]},
            {"name": f"숏 {_PCT} 되돌림선", "values": S["r"]},
            {"name": "하락 구간 시작 고점", "values": S["H"]},
        ],
        "panes": [
            {"name": "되돌림 깊이(%)",
             "series": [{"name": "상승 구간에서 내려온 정도", "values": depth_l},
                        {"name": "하락 구간에서 올라온 정도", "values": depth_s}],
             "levels": [0, round(_F * 100, 1), 100]},
        ],
        "long": [
            ("큰 상승(ATR 3배 이상, 30봉 안) 뒤 되돌림 대기 중", L["on"]),
            (f"저가가 {_PCT} 되돌림선에 처음 닿음", L["touch"]),
            ("고가가 상승 구간 고점을 아직 안 넘음", L["kept"]),
            (f"종가가 {_PCT} 선 위에서 마감", L["conf"]),
            ("같은 봉 숏 신호 없음", ~S["sig"]),
        ],
        "short": [
            ("큰 하락(ATR 3배 이상, 30봉 안) 뒤 되돌림 대기 중", S["on"]),
            (f"고가가 {_PCT} 되돌림선에 처음 닿음", S["touch"]),
            ("저가가 하락 구간 저점을 아직 안 깸", S["kept"]),
            (f"종가가 {_PCT} 선 아래에서 마감", S["conf"]),
            ("같은 봉 롱 신호 없음", ~L["sig"]),
        ],
    }
