"""Chart view for DS_F9_IFVG (DeepSeek-200 F9_IFVG, research/deepseek200/PREREG_DEEPSEEK200.md section 5):
what a trader draws for it and its entry conditions, worded for the owners.

Inverted FVG: an up FVG that a close breaks below within 50 bars becomes resistance (short box, born on that
close); a down FVG closed above becomes support (long box). The first touch of the flipped box gives the signal when
it closes on the box's far half. The chart draws the flipped box the checklist reads.

Checked against the research signal (lib_c.entries of research/deepseek200/lib_c.py, loaded by path inside
entry_marks._contained(), so sys.path and the warnings filters are restored): AND of the long (short) conditions
equals the F9_IFVG long (short) signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1}
Series: the full Binance USDT-M bar files 2021-01..2026-09 (BTC 15m 201,398 bars, ETH 1h 50,351, SOL 4h
12,588, DOGE 30m 100,701; signals checked: long 3,710, short 3,739) and 12 live-service frames
built from 5m bars as paperbot.dssig.frame does (config.DS_WINDOW_5M; BTC 15m, ETH 1h, LTC 4h, BCH 30m at
three end dates each; signals checked: long 438, short 424): recall = precision = 1 on all
24 live-frame sides too, 0 differing bars. tests/test_strategy_views_ds_f9_f11.py repeats the check.
"""

import numpy as np
import fg_indicators as fg

_EXP = 50          # a zone waits 50 bars after the bar that made it (PREREG section 4)


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


def _flip(c, zones, d):
    """lib_c.flip_zones: a zone of side ``d`` whose first close beyond its far edge within 50 bars (long zone: close <
    lo; short zone: close > hi) turns into a zone of the other side born on that bar (same lo, hi)."""
    n = len(c)
    out = []
    for b, lo, hi in zones:
        s0, s1 = b + 1, min(n, b + 1 + _EXP)
        if s0 >= n:
            continue
        with np.errstate(invalid="ignore"):
            m = (c[s0:s1] < lo) if d > 0 else (c[s0:s1] > hi)
        if m.any():
            out.append((s0 + int(m.argmax()), lo, hi))
    return out


def view_DS_F9_IFVG(df, tf):
    """F9_IFVG: first touch of a flipped (inverted) FVG box, close beyond its half line. Exact."""
    o, h, l, c = _cols(df)
    up, dn = _fvg(h, l, _atr(df))
    lz, sz = _flip(c, dn, -1), _flip(c, up, 1)
    L = _focus(h, l, c, [(b, lo, hi, np.nan, ()) for b, lo, hi in lz], 1, lambda t, lo, hi: c[t] >= (lo + hi) / 2)
    S = _focus(h, l, c, [(b, lo, hi, np.nan, ()) for b, lo, hi in sz], -1, lambda t, lo, hi: c[t] <= (lo + hi) / 2)
    return {
        "overlays": _box("지지로 바뀐 FVG", L) + _box("저항으로 바뀐 FVG", S),
        "panes": [],
        "long": [
            ("위로 뚫린 하락 FVG(이제 지지) 대기 중", L["on"]),
            ("저가가 그 존에 처음 닿음", L["touch"]),
            ("종가가 존 절반 이상", L["conf"]),
            ("같은 봉 숏 신호 없음", ~S["sig"]),
        ],
        "short": [
            ("아래로 뚫린 상승 FVG(이제 저항) 대기 중", S["on"]),
            ("고가가 그 존에 처음 닿음", S["touch"]),
            ("종가가 존 절반 이하", S["conf"]),
            ("같은 봉 롱 신호 없음", ~L["sig"]),
        ],
    }
