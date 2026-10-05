"""Chart view for DS_F10_M2022 (DeepSeek-200 F10_M2022, research/deepseek200/PREREG_DEEPSEEK200.md section 5):
what a trader draws for it and its entry conditions, worded for the owners.

ICT 2022 model: a liquidity raid (swing low pierced, close back above), then within 20 bars a displacement
market-structure shift (MSS bar with body >= 1.2 ATR), and an FVG born on that MSS bar or the next one. Only that FVG
is traded, as in F9_FVG (first touch, close beyond the half line). The checklist reads one FVG per bar (a qualifying
one first); the chart draws that FVG box and the last confirmed swing high / low (the raid and MSS levels).

Checked against the research signal (lib_c.entries of research/deepseek200/lib_c.py, loaded by path inside
entry_marks._contained(), so sys.path and the warnings filters are restored): AND of the long (short) conditions
equals the F10_M2022 long (short) signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1}
Series: the full Binance USDT-M bar files 2021-01..2026-09 (BTC 15m 201,398 bars, ETH 1h 50,351, SOL 4h
12,588, DOGE 30m 100,701; signals checked: long 466, short 450) and 12 live-service frames
built from 5m bars as paperbot.dssig.frame does (config.DS_WINDOW_5M; BTC 15m, ETH 1h, LTC 4h, BCH 30m at
three end dates each; signals checked: long 49, short 57): recall = precision = 1 on all
24 live-frame sides too, 0 differing bars. tests/test_strategy_views_ds_f9_f11.py repeats the check.
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import fg_indicators as fg

_EXP = 50          # a zone waits 50 bars after the bar that made it (PREREG section 4)

_SW = 3            # swing pivot: 3 bars on each side, known 3 bars later (PREREG section 4)


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _atr(df):
    """ATR14 exactly as lib_c reads it (fg.atr, Wilder); an empty frame gives an empty array."""
    if len(df) == 0:
        return np.zeros(0)
    return fg.atr(df, 14).to_numpy(dtype=float)


def _focus(h, l, c, zones, d, confirm, nflags=0):
    """Zones of one side, read bar by bar exactly as lib_c.resolve_zones reads them.

    ``zones``: (birth, lo, hi, kill, flags) with ``nflags`` flags each. A zone waits on bars birth+1 .. birth+50
    until its first touch (long: low <= hi, short: high >= lo); a bar beyond its kill line (long: high > kill,
    short: low < kill) at or before that touch ends it; the touch bar gives the signal when ``confirm(t, lo, hi)``
    and every flag hold. A zone gives at most one signal and is used up by its first touch.

    Every checklist line is read from ONE zone per bar (the focus): a zone that gives the signal on this bar if there
    is one, else the one with the most flags, a touched one, the one nearest to price, the newest. So AND of the lines
    equals "some zone gives the signal on this bar" (lib_c's signal before the same-bar long/short rule)."""
    n = len(c)
    best = [None] * n
    for b, lo, hi, kill, flags in zones:
        s0, s1 = b + 1, min(n, b + 1 + _EXP)
        if s0 >= n or not (np.isfinite(lo) and np.isfinite(hi)):
            continue
        with np.errstate(invalid="ignore"):
            tch = (l[s0:s1] <= hi) if d > 0 else (h[s0:s1] >= lo)
            if kill == kill:
                kil = (h[s0:s1] > kill) if d > 0 else (l[s0:s1] < kill)
            else:
                kil = np.zeros(s1 - s0, bool)
        last = s1 - 1
        t_touch = s0 + int(tch.argmax()) if tch.any() else -1
        t_kill = s0 + int(kil.argmax()) if kil.any() else -1
        if t_touch >= 0:
            last = min(last, t_touch)
        if t_kill >= 0:
            last = min(last, t_kill)
        near = hi if d > 0 else -lo
        fl = tuple(bool(x) for x in flags)
        for t in range(s0, last + 1):
            touched = t == t_touch
            kept = t != t_kill
            ok = bool(confirm(t, lo, hi))
            key = (touched and kept and ok and all(fl),) + fl + (touched, near, b)
            if best[t] is None or key > best[t][0]:
                best[t] = (key, touched, kept, ok, lo, hi, kill, fl)
    out = {k: np.zeros(n, bool) for k in ("on", "touch", "kept", "conf", "sig")}
    out.update({k: np.full(n, np.nan) for k in ("lo", "hi", "kill")})
    out["flags"] = np.zeros((nflags, n), bool)
    for t, z in enumerate(best):
        if z is None:
            continue
        key, touched, kept, ok, lo, hi, kill, fl = z
        out["on"][t], out["touch"][t], out["kept"][t], out["conf"][t], out["sig"][t] = True, touched, kept, ok, key[0]
        out["lo"][t], out["hi"][t], out["kill"][t] = lo, hi, kill
        for i, x in enumerate(fl):
            out["flags"][i, t] = x
    out["mid"] = (out["lo"] + out["hi"]) / 2
    return out


def _box(name, z):
    """The focus zone as a box: its top, bottom and half line (blank while no zone waits)."""
    return [{"name": f"{name} 상단", "values": z["hi"]},
            {"name": f"{name} 하단", "values": z["lo"]},
            {"name": f"{name} 절반", "values": z["mid"]}]


def _fvg(h, l, atr):
    """lib_c.fvg_zones: bullish FVG at bar b = low[b] > high[b-2] by at least 0.5 ATR(b), zone [high[b-2], low[b]];
    bearish = high[b] < low[b-2] by at least 0.5 ATR(b), zone [high[b], low[b-2]]. Born at b."""
    n = len(h)
    if n < 3:
        return [], []
    with np.errstate(invalid="ignore"):
        u = (l[2:] > h[:-2]) & ((l[2:] - h[:-2]) >= 0.5 * atr[2:])
        w = (h[2:] < l[:-2]) & ((l[:-2] - h[2:]) >= 0.5 * atr[2:])
    up = [(int(b), float(h[b - 2]), float(l[b])) for b in np.flatnonzero(u) + 2]
    dn = [(int(b), float(h[b]), float(l[b - 2])) for b in np.flatnonzero(w) + 2]
    return up, dn


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


def _structure(h, l, c):
    """lib_c.structure, one causal pass: last confirmed swing levels, BOS / MSS breaks, liquidity raids. Also the
    raid state each bar is checked with (a swing level not pierced yet) for the checklist and the chart."""
    n = len(c)
    ph, pl = _pivots(h, l)
    nan = float("nan")
    hi_a, lo_a = np.full(n, nan), np.full(n, nan)
    hi_i, lo_i = np.full(n, -1), np.full(n, -1)
    mss_up, mss_dn = np.zeros(n, bool), np.zeros(n, bool)
    raid_long, raid_short = np.zeros(n, bool), np.zeros(n, bool)
    hi_open, lo_open = np.zeros(n, bool), np.zeros(n, bool)
    hl, ll, cl = np.asarray(h, float).tolist(), np.asarray(l, float).tolist(), np.asarray(c, float).tolist()
    phc, plc = ph.tolist(), pl.tolist()
    hi_lvl = lo_lvl = nan
    hi_idx = lo_idx = -1
    hi_bos = lo_bos = hi_raid = lo_raid = False
    state = 0
    for t in range(n):
        if phc[t]:
            hi_lvl, hi_idx = hl[t - _SW], t - _SW
            hi_bos = hi_raid = True
        if plc[t]:
            lo_lvl, lo_idx = ll[t - _SW], t - _SW
            lo_bos = lo_raid = True
        hi_a[t], lo_a[t], hi_i[t], lo_i[t] = hi_lvl, lo_lvl, hi_idx, lo_idx
        ct = cl[t]
        up = hi_bos and ct > hi_lvl
        dn = lo_bos and ct < lo_lvl
        if up and not dn:
            if state == -1:
                mss_up[t] = True
            state = 1
            hi_bos = False
        elif dn and not up:
            if state == 1:
                mss_dn[t] = True
            state = -1
            lo_bos = False
        hi_open[t], lo_open[t] = hi_raid, lo_raid
        if hi_raid and hl[t] > hi_lvl:
            hi_raid = False
            if ct < hi_lvl:
                raid_short[t] = True
        if lo_raid and ll[t] < lo_lvl:
            lo_raid = False
            if ct > lo_lvl:
                raid_long[t] = True
    return dict(ph_conf=ph, pl_conf=pl, hi=hi_a, lo=lo_a, hi_idx=hi_i, lo_idx=lo_i, mss_up=mss_up, mss_dn=mss_dn,
                raid_long=raid_long, raid_short=raid_short, hi_open=hi_open, lo_open=lo_open)


def _any_in(cs, a, b):
    """lib_c's any_in: any True in [a, b] of the array whose cumulative sum is ``cs``."""
    a = max(a, 0)
    return (cs[b] - (cs[a - 1] if a > 0 else 0)) > 0 if b >= a else False


def _story(b, disp, cs):
    """(sweep before the shift, displacement shift) of the FVG born at b: a displacement MSS bar m in {b-1, b}, and a
    raid of the same side in m-20 .. m-1 for such an m (the first flag implies the second)."""
    ms = [m for m in (b - 1, b) if m >= 0 and disp[m]]
    return (any(_any_in(cs, m - 20, m - 1) for m in ms), bool(ms))


def view_DS_F10_M2022(df, tf):
    """F10_M2022: raid -> displacement MSS within 20 bars -> FVG on the MSS bar or the next -> first touch of that
    FVG, close beyond its half line. Exact."""
    o, h, l, c = _cols(df)
    atr = _atr(df)
    st = _structure(h, l, c)
    with np.errstate(invalid="ignore"):
        du = st["mss_up"] & ((c - o) >= 1.2 * atr)
        dd = st["mss_dn"] & ((o - c) >= 1.2 * atr)
    cl, cs = np.cumsum(st["raid_long"]), np.cumsum(st["raid_short"])
    up, dn = _fvg(h, l, atr)
    L = _focus(h, l, c, [(b, lo, hi, np.nan, _story(b, du, cl)) for b, lo, hi in up], 1,
               lambda t, lo, hi: c[t] >= (lo + hi) / 2, nflags=2)
    S = _focus(h, l, c, [(b, lo, hi, np.nan, _story(b, dd, cs)) for b, lo, hi in dn], -1,
               lambda t, lo, hi: c[t] <= (lo + hi) / 2, nflags=2)
    return {
        "overlays": [
            {"name": "상승 FVG 상단", "values": L["hi"]},
            {"name": "상승 FVG 하단", "values": L["lo"]},
            {"name": "하락 FVG 상단", "values": S["hi"]},
            {"name": "하락 FVG 하단", "values": S["lo"]},
            {"name": "최근 스윙 고점", "values": st["hi"]},
            {"name": "최근 스윙 저점", "values": st["lo"]},
        ],
        "panes": [],
        "long": [
            ("상승 FVG 대기 중(50봉 안)", L["on"]),
            ("FVG가 강한 양봉(몸통 ≥ ATR×1.2)으로 흐름을 위로 바꾼 봉이나 그 다음 봉에서 생김", L["flags"][1]),
            ("전환 전 20봉 안에 스윙 저점 찌르고 회복", L["flags"][0]),
            ("저가가 FVG에 처음 닿음", L["touch"]),
            ("종가가 FVG 절반 이상", L["conf"]),
            ("같은 봉 숏 신호 없음", ~S["sig"]),
        ],
        "short": [
            ("하락 FVG 대기 중(50봉 안)", S["on"]),
            ("FVG가 강한 음봉(몸통 ≥ ATR×1.2)으로 흐름을 아래로 바꾼 봉이나 그 다음 봉에서 생김", S["flags"][1]),
            ("전환 전 20봉 안에 스윙 고점 찌르고 복귀", S["flags"][0]),
            ("고가가 FVG에 처음 닿음", S["touch"]),
            ("종가가 FVG 절반 이하", S["conf"]),
            ("같은 봉 롱 신호 없음", ~L["sig"]),
        ],
    }
