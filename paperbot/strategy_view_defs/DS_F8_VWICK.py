"""Chart view for DS_F8_VWICK (DeepSeek-200 F8_VWICK, F8 처녀 꼬리 POI): its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md sections 4 and 5, F8): a big-body candle k has |C - O| >= 0.7 x (H - L) and
|C - O| >= 1.3 x ATR14[k] (fg.atr). A green one leaves a long level at its low L[k] (the wick end), a red one a short
level at its high H[k]. The level waits on bars k+1 .. k+50 for its first touch (long: L[s] <= L[k]; short:
H[s] >= H[k]); untouched until then is what "virgin" means. The touch bar gives the signal when its close holds the
level (long: C[s] > L[k]; short: C[s] < H[k]); otherwise the level is used up without a signal. One signal per level.
A bar where both sides fire gives neither (lib_c drops both).

The chart draws, on every bar, the waiting long level the checklist reads (a level that gives the signal on this bar
if there is one, else a touched one, else the nearest to price, else the newest) and the same for short, so the line
is the nearest untouched wick end below (above) price.

Same rules as research/deepseek200/lib_c.py ``entries()`` / ``resolve_zones()`` (the live signal is
paperbot/dssig.py), written again with numpy and the vendored fg_indicators; lib_c is not imported here.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 2,145 / short 1,975; live frames long 3,376 / short 2,944; 0 differing
bars. "signals" = lib_c signals of that series (live: summed over its 24 frames).
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 1167, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 1103, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 306, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 303, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_long_signals": 83, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "SOL4h_short_signals": 73, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_long_signals": 589, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "DOGE30m_short_signals": 496, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_long_signals": 808, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "BTC15m_live_short_signals": 768, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_long_signals": 440, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "ETH1h_live_short_signals": 430, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_long_signals": 401, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "LTC4h_live_short_signals": 307, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_long_signals": 440, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "BCH30m_live_short_signals": 348, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_long_signals": 465, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "SOL1h_live_short_signals": 374, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_long_signals": 822, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1, "DOGE15m_live_short_signals": 717}
tests/test_strategy_views_ds_f1_f8.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import fg_indicators as fg

EXP = 50            # a level waits 50 bars after its candle (PREREG section 4)
BODY_RANGE = 0.7    # body at least 70% of the candle's range
BODY_ATR = 1.3      # body at least 1.3 ATR14


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _atr(df):
    """ATR14 exactly as lib_c reads it (fg.atr, Wilder); an empty frame gives an empty array."""
    if len(df) == 0:
        return np.zeros(0)
    return fg.atr(df, 14).to_numpy(dtype=float)


def _levels(o, h, l, c, atr):
    """(long, short): [(candle bar k, level)] of the big-body candles, as lib_c builds the F8 zones."""
    with np.errstate(invalid="ignore"):
        body, rng = np.abs(c - o), h - l
        big = (rng > 0) & (body >= BODY_RANGE * rng) & (body >= BODY_ATR * atr)
    up = [(int(k), float(l[k])) for k in np.flatnonzero(big & (c > o))]
    dn = [(int(k), float(h[k])) for k in np.flatnonzero(big & (c < o))]
    return up, dn


def _focus(h, l, c, levels, d):
    """Levels of one side read bar by bar exactly as lib_c.resolve_zones reads them (lo = hi = level, no kill line).

    A level waits on bars k+1 .. k+50 up to and including its first touch (long: low <= level, short: high >= level);
    the touch bar gives the signal when the close holds the level (long: close > level, short: close < level). Every
    checklist line is read from ONE level per bar: one that gives the signal on this bar if there is one, else a touched
    one, else the nearest to price, else the newest. So AND of the lines equals "some level gives the signal on this
    bar" (lib_c's signal before the same-bar long/short rule)."""
    n = len(c)
    best = [None] * n
    for k, x in levels:
        s0, s1 = k + 1, min(n, k + 1 + EXP)
        if s0 >= n or not np.isfinite(x):
            continue
        with np.errstate(invalid="ignore"):
            tch = (l[s0:s1] <= x) if d > 0 else (h[s0:s1] >= x)
        t_touch = s0 + int(tch.argmax()) if tch.any() else -1
        last = t_touch if t_touch >= 0 else s1 - 1
        near = x if d > 0 else -x
        for t in range(s0, last + 1):
            touched = t == t_touch
            with np.errstate(invalid="ignore"):
                ok = bool(c[t] > x) if d > 0 else bool(c[t] < x)
            key = (touched and ok, touched, near, k)
            if best[t] is None or key > best[t][0]:
                best[t] = (key, touched, ok, x)
    out = {kk: np.zeros(n, bool) for kk in ("on", "touch", "conf", "sig")}
    out["level"] = np.full(n, np.nan)
    for t, z in enumerate(best):
        if z is None:
            continue
        key, touched, ok, x = z
        out["on"][t], out["touch"][t], out["conf"][t], out["sig"][t], out["level"][t] = True, touched, ok, key[0], x
    return out


def view_DS_F8_VWICK(df, tf):
    """F8_VWICK: first touch of a big candle's untouched wick end, with the close holding it. Exact."""
    o, h, l, c = _cols(df)
    up, dn = _levels(o, h, l, c, _atr(df))
    L = _focus(h, l, c, up, 1)
    S = _focus(h, l, c, dn, -1)
    return {
        "overlays": [
            {"name": "숏 대기 꼬리 끝(장대 음봉 고가)", "values": S["level"]},
            {"name": "롱 대기 꼬리 끝(장대 양봉 저가)", "values": L["level"]},
        ],
        "panes": [],
        "long": [
            ("장대 양봉 꼬리 끝이 안 닿은 채 대기(50봉 안)", L["on"]),
            ("저가가 꼬리 끝에 처음 닿음", L["touch"]),
            ("종가는 꼬리 끝 위에서 마감", L["conf"]),
            ("같은 봉 숏 신호 없음", ~S["sig"]),
        ],
        "short": [
            ("장대 음봉 꼬리 끝이 안 닿은 채 대기(50봉 안)", S["on"]),
            ("고가가 꼬리 끝에 처음 닿음", S["touch"]),
            ("종가는 꼬리 끝 아래에서 마감", S["conf"]),
            ("같은 봉 롱 신호 없음", ~L["sig"]),
        ],
    }
