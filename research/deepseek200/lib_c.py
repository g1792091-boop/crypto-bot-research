"""Deepseek-200 new-family test (research/deepseek200/PREREG_DEEPSEEK200.md): 44 definitions of 17 families.

    python3 research/deepseek200/lib_c.py selftest
    python3 research/deepseek200/lib_c.py count
    python3 research/deepseek200/lib_c.py estimate
    python3 research/deepseek200/lib_c.py run --bars <BINANCE_DIR>/bars [--pre data/pre2021] [--out research/deepseek200/out]
                                              [--procs 4] [--tfs 15m,30m,1h,4h] [--n-boot 2000]

Every signal generator uses only closed bars (the signal at bar t is known at t's close; entry is the open of
bar t+1 in the locked engine). Swing pivots use 3 bars on each side and are known 3 bars later. Nothing in
this file reads real data unless ``run`` is called. Engine, exits, costs, gauntlet (config_rows / select):
imported from research/library/lib.py and the backtest session's locked engine, not copied.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import time
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")

# ------------------------------------------------------------------ fixed parameters (PREREG sections 4, 5, 7)
TFS = ("15m", "30m", "1h", "4h")
SESSION_TFS = ("15m", "30m", "1h")
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
EXIT_NAMES = ("X5_TRAIL2", "X2_SL15_TP3")
MAX_HOLD = 48
SW = 3                 # swing pivot: 3 bars each side, known 3 bars later
EXP = 50               # zone life in bars
FVG_MIN_ATR = 0.5
ZONE_ATR_LEG = 3.0     # impulse leg size (x ATR) and max length (bars)
LEG_MAX_BARS = 30
SEED = 20261005
ORB_BARS = 2          # opening range = first N bars of the UTC day (PREREG F15_ORB)
PO3_RANGE_MIN, PO3_WINDOW_END, PO3_REVERSAL_BARS = 8 * 60, 20 * 60, 3   # PREREG F11_PO3
PERIODS = {  # split label -> (start, end) UTC, signal bar times; 'pre' lives in the data/pre2021 series
    "is": ("2021-08-01", "2024-07-01"),
    "oos": ("2024-07-01", "2026-09-30"),
    "pre": ("2020-01-01", "2021-08-01"),
}

# (id, family, tfs). Order is the order of the PREREG.
_ALL4, _SES = TFS, SESSION_TFS
DEFS = [
    ("F1_RSI_DIV", "F1", _ALL4), ("F1_MOM_DIV", "F1", _ALL4), ("F1_PVT_DIV", "F1", _ALL4),
    ("F2_DEMARK", "F2", _ALL4),
    ("F3_BOS", "F3", _ALL4), ("F3_BOS_ZONE", "F3", _ALL4), ("F3_HHHL", "F3", _ALL4),
    ("F4_PULL", "F4", _ALL4), ("F4_PULL_RSI", "F4", _ALL4), ("F4_FAN", "F4", _ALL4),
    ("F5_BOX", "F5", _ALL4), ("F5_BOX_RSI", "F5", _ALL4), ("F5_BOX_HTF", "F5", _ALL4),
    ("F6_VWAP_CROSS", "F6", _ALL4), ("F6_VWAP_FAIL", "F6", _ALL4),
    ("F7_RF_TRIPLE", "F7", _ALL4), ("F7_RF_ONLY", "F7", _ALL4),
    ("F8_VWICK", "F8", _ALL4),
    ("F9_FVG", "F9", _ALL4), ("F9_IFVG", "F9", _ALL4), ("F9_OB", "F9", _ALL4), ("F9_BREAKER", "F9", _ALL4),
    ("F10_M2022", "F10", _ALL4), ("F10_OTE", "F10", _ALL4),
    ("F11_TSOUP", "F11", _ALL4), ("F11_RAID", "F11", _ALL4), ("F11_PO3", "F11", _ALL4),
    ("F12_MSS", "F12", _ALL4), ("F12_MSS_DISP", "F12", _ALL4),
    ("F13_FVG_PD", "F13", _ALL4), ("F13_RAID_PD", "F13", _ALL4),
    ("F14_SMT", "F14", _ALL4),
    ("F15_ASIA_BRK", "F15", _SES), ("F15_ASIA_SWEEP", "F15", _SES), ("F15_LON_BRK", "F15", _SES),
    ("F15_OPEN0930", "F15", _SES), ("F15_OPEN0000", "F15", _SES), ("F15_ORB", "F15", _ALL4),
    ("F16_FIB382", "F16", _ALL4), ("F16_FIB500", "F16", _ALL4), ("F16_FIB618", "F16", _ALL4),
    ("F16_FIB764", "F16", _ALL4),
    ("F17_Z", "F17", _ALL4), ("F17_Z_HL", "F17", _ALL4),
]
DEF_IDS = [d[0] for d in DEFS]
FAMILY = {d[0]: d[1] for d in DEFS}
FIB = {"F16_FIB382": 0.382, "F16_FIB500": 0.500, "F16_FIB618": 0.618, "F16_FIB764": 0.764}
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
HTF_OF = {"15m": "1h", "30m": "2h", "1h": "4h", "4h": "1d"}


def config_list() -> list[tuple[str, str, str]]:
    """Every (timeframe, definition, exit): the N configurations of the PREREG."""
    return [(tf, d, x) for tf in TFS for d, _f, tfs in DEFS if tf in tfs for x in EXIT_NAMES]


# ------------------------------------------------------------------ environment (library lib, locked engine)
_ENV: dict = {}


def env() -> dict:
    if not _ENV:
        sys.path.insert(0, os.path.join(ROOT, "research", "search"))
        spec = importlib.util.spec_from_file_location("research_library_lib", os.path.join(ROOT, "research", "library", "lib.py"))
        lib = importlib.util.module_from_spec(spec)
        sys.modules["research_library_lib"] = lib
        spec.loader.exec_module(lib)
        L = lib.SR.lib()
        import fg_indicators as fg
        import pine_indicators as pi
        _ENV.update(lib=lib, SR=lib.SR, L=L, fg=fg, pi=pi)
    return _ENV


# ------------------------------------------------------------------ small helpers
def _prev(x: np.ndarray, k: int = 1) -> np.ndarray:
    x = np.asarray(x, float)
    return np.r_[np.full(k, np.nan), x[:-k]]


def _prevb(x: np.ndarray, k: int = 1) -> np.ndarray:
    return np.r_[np.zeros(k, bool), np.asarray(x, bool)[:-k]]


def _cross_up(a, b) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    with np.errstate(invalid="ignore"):
        return (a > b) & (_prev(a) <= _prev(b))


def _cross_dn(a, b) -> np.ndarray:
    return _cross_up(np.asarray(b, float), np.asarray(a, float))


def _first_event(x: np.ndarray) -> np.ndarray:
    """True only on the first bar of each run of True."""
    x = np.asarray(x, bool)
    return x & ~_prevb(x)


# ------------------------------------------------------------------ swing pivots and structure
def pivots_conf(h: np.ndarray, l: np.ndarray, k: int = SW) -> tuple[np.ndarray, np.ndarray]:
    """(ph_conf, pl_conf): True at bar t when the swing high/low of bar t-k is confirmed (known at t's close).
    A swing high has a high strictly above the k bars on each side; swing low symmetric."""
    n = len(h)
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    if n >= 2 * k + 1:
        wh = sliding_window_view(np.asarray(h, float), 2 * k + 1)
        wl = sliding_window_view(np.asarray(l, float), 2 * k + 1)
        with np.errstate(invalid="ignore"):
            okh = (wh[:, k] > wh[:, :k].max(1)) & (wh[:, k] > wh[:, k + 1:].max(1))
            okl = (wl[:, k] < wl[:, :k].min(1)) & (wl[:, k] < wl[:, k + 1:].min(1))
        ph[2 * k:] = okh          # window j centres on bar j+k, confirmed at j+2k
        pl[2 * k:] = okl
    return ph, pl


def structure(o, h, l, c) -> dict:
    """One causal pass: confirmed swing levels, BOS/MSS events, liquidity raids (PREREG section 4)."""
    n = len(c)
    ph_conf, pl_conf = pivots_conf(h, l)
    nan = float("nan")
    hi_a, lo_a, phi_a, plo_a = (np.full(n, nan) for _ in range(4))
    hi_i, lo_i = np.full(n, -1), np.full(n, -1)
    bos_up, bos_dn, mss_up, mss_dn = (np.zeros(n, bool) for _ in range(4))
    raid_long, raid_short = np.zeros(n, bool), np.zeros(n, bool)
    dem_lo, dem_hi, sup_lo, sup_hi = (np.full(n, nan) for _ in range(4))
    hl, ll, ol, cl = np.asarray(h, float).tolist(), np.asarray(l, float).tolist(), np.asarray(o, float).tolist(), np.asarray(c, float).tolist()
    phc, plc = ph_conf.tolist(), pl_conf.tolist()
    hi_lvl = lo_lvl = prev_hi = prev_lo = nan
    hi_idx = lo_idx = -1
    hi_bos = lo_bos = hi_raid = lo_raid = False
    state = 0
    for t in range(n):
        if phc[t]:
            p = t - SW
            prev_hi, hi_lvl, hi_idx = hi_lvl, hl[p], p
            hi_bos = hi_raid = True
        if plc[t]:
            p = t - SW
            prev_lo, lo_lvl, lo_idx = lo_lvl, ll[p], p
            lo_bos = lo_raid = True
        hi_a[t], lo_a[t], phi_a[t], plo_a[t], hi_i[t], lo_i[t] = hi_lvl, lo_lvl, prev_hi, prev_lo, hi_idx, lo_idx
        ct = cl[t]
        up = hi_bos and ct > hi_lvl
        dn = lo_bos and ct < lo_lvl
        if up and not dn:
            if state == 1:
                bos_up[t] = True
            elif state == -1:
                mss_up[t] = True
            state = 1
            hi_bos = False
            if lo_idx >= 0:
                dem_lo[t], dem_hi[t] = ll[lo_idx], hl[lo_idx]
        elif dn and not up:
            if state == -1:
                bos_dn[t] = True
            elif state == 1:
                mss_dn[t] = True
            state = -1
            lo_bos = False
            if hi_idx >= 0:
                sup_lo[t], sup_hi[t] = ll[hi_idx], hl[hi_idx]
        if hi_raid and hl[t] > hi_lvl:
            hi_raid = False
            if ct < hi_lvl:
                raid_short[t] = True
        if lo_raid and ll[t] < lo_lvl:
            lo_raid = False
            if ct > lo_lvl:
                raid_long[t] = True
    return dict(ph_conf=ph_conf, pl_conf=pl_conf, hi=hi_a, lo=lo_a, prev_hi=phi_a, prev_lo=plo_a, hi_idx=hi_i, lo_idx=lo_i,
                bos_up=bos_up, bos_dn=bos_dn, mss_up=mss_up, mss_dn=mss_dn, raid_long=raid_long, raid_short=raid_short,
                dem_lo=dem_lo, dem_hi=dem_hi, sup_lo=sup_lo, sup_hi=sup_hi)


# ------------------------------------------------------------------ zones
def _resolve_wait(n, c, h, l, zones, confirm):
    """'Wait' variant (F3_BOS_ZONE only): the zone stays alive for EXP bars until a close beyond its far side (long:
    close < lo; short: close > hi); the first bar that touches the zone AND satisfies confirm gives the signal."""
    long_s, short_s = np.zeros(n, bool), np.zeros(n, bool)
    for b, lo, hi, d, _kill in zones:
        if not (np.isfinite(lo) and np.isfinite(hi)):
            continue
        for s in range(b + 1, min(n, b + 1 + EXP)):
            if d > 0:
                if c[s] < lo:
                    break
                if l[s] <= hi and confirm(s, lo, hi, 1):
                    long_s[s] = True
                    break
            else:
                if c[s] > hi:
                    break
                if h[s] >= lo and confirm(s, lo, hi, -1):
                    short_s[s] = True
                    break
    return long_s, short_s


def resolve_zones(n: int, h, l, zones: list, confirm) -> tuple[np.ndarray, np.ndarray]:
    """zones: (birth, lo, hi, dir, kill). The first bar s in birth+1..birth+EXP with low<=hi (long) / high>=lo (short)
    is the first touch; a bar with high>kill (long) / low<kill (short) at or before it kills the zone. If
    confirm(s, lo, hi, dir) the signal is on bar s. One signal per zone at most."""
    long_s, short_s = np.zeros(n, bool), np.zeros(n, bool)
    for b, lo, hi, d, kill in zones:
        s0, s1 = b + 1, min(n, b + 1 + EXP)
        if s0 >= n or not (np.isfinite(lo) and np.isfinite(hi)):
            continue
        if d > 0:
            touch = l[s0:s1] <= hi
            if not touch.any():
                continue
            ft = int(touch.argmax())
            if kill == kill and (h[s0:s0 + ft + 1] > kill).any():
                continue
            if confirm(s0 + ft, lo, hi, 1):
                long_s[s0 + ft] = True
        else:
            touch = h[s0:s1] >= lo
            if not touch.any():
                continue
            ft = int(touch.argmax())
            if kill == kill and (l[s0:s0 + ft + 1] < kill).any():
                continue
            if confirm(s0 + ft, lo, hi, -1):
                short_s[s0 + ft] = True
    return long_s, short_s


def fvg_zones(h, l, atr) -> list:
    """Bullish FVG: low[t] > high[t-2]; bearish: high[t] < low[t-2]; both at least 0.5 ATR(t) wide. Born at t."""
    n = len(h)
    zones = []
    if n < 3:
        return zones
    with np.errstate(invalid="ignore"):
        up = (l[2:] > h[:-2]) & ((l[2:] - h[:-2]) >= FVG_MIN_ATR * atr[2:])
        dn = (h[2:] < l[:-2]) & ((l[:-2] - h[2:]) >= FVG_MIN_ATR * atr[2:])
    for b in (np.flatnonzero(up) + 2):
        zones.append((int(b), float(h[b - 2]), float(l[b]), 1, float("nan")))
    for b in (np.flatnonzero(dn) + 2):
        zones.append((int(b), float(h[b]), float(l[b - 2]), -1, float("nan")))
    return zones


def ob_zones(o, h, l, c) -> list:
    """Bullish OB: bar k bearish, close[k+1] > high[k], low[k+2] > high[k]; zone [low[k], high[k]], born k+2.
    Bearish OB: bar k bullish, close[k+1] < low[k], high[k+2] < low[k]."""
    n = len(c)
    zones = []
    if n < 3:
        return zones
    with np.errstate(invalid="ignore"):
        up = (c[:-2] < o[:-2]) & (c[1:-1] > h[:-2]) & (l[2:] > h[:-2])
        dn = (c[:-2] > o[:-2]) & (c[1:-1] < l[:-2]) & (h[2:] < l[:-2])
    for k in np.flatnonzero(up):
        zones.append((int(k) + 2, float(l[k]), float(h[k]), 1, float("nan")))
    for k in np.flatnonzero(dn):
        zones.append((int(k) + 2, float(l[k]), float(h[k]), -1, float("nan")))
    return zones


def flip_zones(c, zones: list) -> list:
    """Inversion (iFVG) / breaker: a long zone whose first close below lo within EXP bars after birth becomes a short
    zone born at that bar (same lo, hi); a short zone closed above hi becomes a long zone."""
    n = len(c)
    out = []
    for b, lo, hi, d, _k in zones:
        s0, s1 = b + 1, min(n, b + 1 + EXP)
        if s0 >= n:
            continue
        if d > 0:
            m = c[s0:s1] < lo
            if m.any():
                out.append((s0 + int(m.argmax()), lo, hi, -1, float("nan")))
        else:
            m = c[s0:s1] > hi
            if m.any():
                out.append((s0 + int(m.argmax()), lo, hi, 1, float("nan")))
    return out


def impulse_legs(S: dict, h, l, atr) -> list:
    """(confirm bar, H, L, dir): up leg when a swing high is confirmed and the last confirmed swing low is at most
    LEG_MAX_BARS earlier and the range is >= 3 ATR; down leg symmetric."""
    legs = []
    for t in np.flatnonzero(S["ph_conf"]):
        p, q = t - SW, S["lo_idx"][t]
        H, Lw = h[p], S["lo"][t]
        if q >= 0 and p - q <= LEG_MAX_BARS and H - Lw >= ZONE_ATR_LEG * atr[t]:
            legs.append((int(t), float(H), float(Lw), 1))
    for t in np.flatnonzero(S["pl_conf"]):
        p, q = t - SW, S["hi_idx"][t]
        Lw, H = l[p], S["hi"][t]
        if q >= 0 and p - q <= LEG_MAX_BARS and H - Lw >= ZONE_ATR_LEG * atr[t]:
            legs.append((int(t), float(H), float(Lw), -1))
    return legs


# ------------------------------------------------------------------ ET sessions (PREREG section 4)
def _nth_sunday(year: int, month: int, nth: int) -> dt.date:
    d = dt.date(year, month, 1)
    first = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    return first + dt.timedelta(days=7 * (nth - 1))


def et_offset_minutes(ts: np.ndarray) -> np.ndarray:
    """UTC offset of US Eastern time in minutes (-240 EDT / -300 EST). DST: second Sunday of March 07:00 UTC up to
    the first Sunday of November 06:00 UTC (US rule since 2007). ``ts`` is datetime64[ns] UTC."""
    ts = np.asarray(ts, "datetime64[ns]")
    out = np.full(len(ts), -300, np.int64)
    years = np.unique(ts.astype("datetime64[Y]").astype(int) + 1970)
    for y in years:
        a = np.datetime64(_nth_sunday(int(y), 3, 2).isoformat() + "T07:00", "ns")
        b = np.datetime64(_nth_sunday(int(y), 11, 1).isoformat() + "T06:00", "ns")
        out[(ts >= a) & (ts < b)] = -240
    return out


def et_wall(ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(ET date as days since 1970-01-01, minute of day) of the wall clock at each UTC bar open."""
    ts = np.asarray(ts, "datetime64[ns]")
    wall = ts + (et_offset_minutes(ts) * 60 * 10**9).astype("timedelta64[ns]")
    day = wall.astype("datetime64[D]").astype(np.int64)
    mins = ((wall - wall.astype("datetime64[D]").astype("datetime64[ns]")) // np.timedelta64(1, "m")).astype(np.int64)
    return day, mins


def _blocks(day: np.ndarray) -> list[tuple[int, int, int]]:
    """(day, start, end) for each run of equal ET dates (wall dates never go backwards)."""
    if len(day) == 0:
        return []
    cut = np.flatnonzero(np.diff(day) != 0) + 1
    st = np.r_[0, cut]
    en = np.r_[cut, len(day)]
    return [(int(day[a]), int(a), int(b)) for a, b in zip(st, en)]


def session_signals(ts, o, h, l, c, tfm: int) -> dict:
    """The five F15 definitions on one series (15m / 30m / 1h bars). Returns {id: (long, short)}."""
    n = len(c)
    day, mins = et_wall(ts)
    blocks = _blocks(day)
    out = {k: (np.zeros(n, bool), np.zeros(n, bool)) for k in
           ("F15_ASIA_BRK", "F15_ASIA_SWEEP", "F15_LON_BRK", "F15_OPEN0930", "F15_OPEN0000")}
    # Asia range of ET date D = bars 20:00-24:00 ET of D-1 (needs exactly 4h/tfm bars)
    ev = mins >= 20 * 60
    asia = {}
    if ev.any():
        g = pd.DataFrame({"d": day[ev] + 1, "h": h[ev], "l": l[ev]}).groupby("d").agg(hi=("h", "max"), lo=("l", "min"), cnt=("h", "size"))
        full = g[g["cnt"] == 240 // tfm]
        asia = dict(zip(full.index.tolist(), zip(full["hi"].tolist(), full["lo"].tolist())))
    for d, a, b in blocks:
        m = mins[a:b]
        hh, ll, cc, oo = h[a:b], l[a:b], c[a:b], o[a:b]
        if d in asia:
            ahi, alo = asia[d]
            win = (m >= 0) & (m < 8 * 60)
            iu = np.flatnonzero(win & (cc > ahi))
            idn = np.flatnonzero(win & (cc < alo))
            first_u = iu[0] if len(iu) else 10**9
            first_d = idn[0] if len(idn) else 10**9
            if first_u < first_d:
                out["F15_ASIA_BRK"][0][a + first_u] = True
            elif first_d < first_u:
                out["F15_ASIA_BRK"][1][a + first_d] = True
            su = np.flatnonzero(win & (hh > ahi) & (cc < ahi))   # short: swept the high and closed back below
            sd = np.flatnonzero(win & (ll < alo) & (cc > alo))   # long: swept the low and closed back above
            first_su = su[0] if len(su) else 10**9
            first_sd = sd[0] if len(sd) else 10**9
            if first_su < first_sd:
                out["F15_ASIA_SWEEP"][1][a + first_su] = True
            elif first_sd < first_su:
                out["F15_ASIA_SWEEP"][0][a + first_sd] = True
        # London range 02:00-05:00 ET of D, exactly 3h/tfm bars; breakout window 05:00-12:00 ET
        lr = (m >= 120) & (m < 300)
        if lr.sum() == 180 // tfm:
            lhi, llo = hh[lr].max(), ll[lr].min()
            win = (m >= 300) & (m < 720)
            iu = np.flatnonzero(win & (cc > lhi))
            idn = np.flatnonzero(win & (cc < llo))
            first_u = iu[0] if len(iu) else 10**9
            first_d = idn[0] if len(idn) else 10**9
            if first_u < first_d:
                out["F15_LON_BRK"][0][a + first_u] = True
            elif first_d < first_u:
                out["F15_LON_BRK"][1][a + first_d] = True
        # open bias: reference bar contains T_ref, judged on the first bar closing at or after T_ref + 60 min
        for name, tref in (("F15_OPEN0930", 9 * 60 + 30), ("F15_OPEN0000", 0)):
            r = np.flatnonzero((m <= tref) & (tref < m + tfm))
            if not len(r):
                continue
            r0 = int(r[0])
            cand = np.flatnonzero((np.arange(len(m)) >= r0) & (m + tfm >= tref + 60))
            if not len(cand):
                continue
            s0 = int(cand[0])
            if m[s0] - m[r0] != (s0 - r0) * tfm:       # a bar is missing between reference and judging bar
                continue
            if cc[s0] > oo[r0]:
                out[name][0][a + s0] = True
            elif cc[s0] < oo[r0]:
                out[name][1][a + s0] = True
    return out


def utc_day_signals(ts, h, l, c, tfm: int) -> dict:
    """UTC-day definitions on every timeframe: F11_PO3 (sweep of the 00:00-08:00 range, then back inside) and
    F15_ORB (breakout of the range of the first ORB_BARS bars of the day). Returns {id: (long, short)}."""
    n = len(c)
    ts = np.asarray(ts, "datetime64[ns]")
    dayd = ts.astype("datetime64[D]")
    day = dayd.astype(np.int64)
    mins = ((ts - dayd.astype("datetime64[ns]")) // np.timedelta64(1, "m")).astype(np.int64)
    out = {k: (np.zeros(n, bool), np.zeros(n, bool)) for k in ("F11_PO3", "F15_ORB")}
    nr = PO3_RANGE_MIN // tfm
    for _d, a, b in _blocks(day):
        m, hh, ll, cc = mins[a:b], h[a:b], l[a:b], c[a:b]
        m_len = len(m)
        # opening range breakout
        if m_len > ORB_BARS and np.array_equal(m[:ORB_BARS], np.arange(ORB_BARS) * tfm):
            oh, ol = hh[:ORB_BARS].max(), ll[:ORB_BARS].min()
            after = np.arange(m_len) >= ORB_BARS
            iu = np.flatnonzero(after & (cc > oh))
            idn = np.flatnonzero(after & (cc < ol))
            fu = iu[0] if len(iu) else 10**9
            fd = idn[0] if len(idn) else 10**9
            if fu < fd:
                out["F15_ORB"][0][a + fu] = True
            elif fd < fu:
                out["F15_ORB"][1][a + fd] = True
        # Power of 3: sweep of one side of the accumulation range, then a close back inside within 3 bars
        if m_len >= nr and np.array_equal(m[:nr], np.arange(nr) * tfm):
            rh, rl = hh[:nr].max(), ll[:nr].min()
            cands = []
            for k in np.flatnonzero((m >= PO3_RANGE_MIN) & (m < PO3_WINDOW_END)):
                up, dn = hh[k] > rh, ll[k] < rl
                if up == dn:
                    continue
                for t in range(k, min(k + PO3_REVERSAL_BARS + 1, m_len)):
                    if m[t] - m[k] != (t - k) * tfm:
                        break
                    if rl <= cc[t] <= rh:
                        cands.append((t, -1 if up else 1))
                        break
            if cands:
                tmin = min(t for t, _s in cands)
                sides = {sd for t, sd in cands if t == tmin}
                if len(sides) == 1:
                    (sd,) = sides
                    out["F11_PO3"][0 if sd > 0 else 1][a + tmin] = True
    return out


# ------------------------------------------------------------------ other building blocks
def heikin_bull(o, h, l, c) -> np.ndarray:
    """1.0 where the Heikin-Ashi bar is up, 0.0 down, 0.5 flat."""
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    hac = (o + h + l + c) / 4
    hao = np.empty(len(c))
    if len(c):
        hao[0] = (o[0] + c[0]) / 2
        a, b = hao, hac.tolist()
        prev = a[0]
        for i in range(1, len(c)):
            prev = (prev + b[i - 1]) / 2
            a[i] = prev
    return np.where(hac > hao, 1.0, np.where(hac < hao, 0.0, 0.5))


def range_filter_dir(c) -> np.ndarray:
    """DonovanWall Range Filter direction (+1 / -1 / 0 before the first move); sampling period 100, multiplier 3."""
    c = np.asarray(c, float)
    d = pd.Series(c).diff().abs().fillna(0.0)
    avr = d.ewm(span=100, adjust=False).mean()
    rng = (3.0 * avr.ewm(span=199, adjust=False).mean()).to_numpy().tolist()
    x = c.tolist()
    out = np.zeros(len(c))
    if not len(c):
        return out
    f, dr = x[0], 0
    for i in range(1, len(c)):
        xi, ri = x[i], rng[i]
        if xi - ri > f:
            nf = xi - ri
        elif xi + ri < f:
            nf = xi + ri
        else:
            nf = f
        if nf > f:
            dr = 1
        elif nf < f:
            dr = -1
        f = nf
        out[i] = dr
    return out


def daily_vwap(ts, h, l, c, v) -> tuple[np.ndarray, np.ndarray]:
    """(VWAP anchored at 00:00 UTC each day including the current bar, UTC day number)."""
    day = np.asarray(ts, "datetime64[ns]").astype("datetime64[D]").astype(np.int64)
    tp = (h + l + c) / 3
    g = pd.DataFrame({"d": day, "pv": tp * v, "v": v}).groupby("d")
    cpv, cv = g["pv"].cumsum().to_numpy(), g["v"].cumsum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(cv > 0, cpv / cv, np.nan)
    return vw, day


def demark_levels(ts, o, h, l, c) -> tuple[np.ndarray, np.ndarray]:
    """(S1, R1) from the previous UTC calendar day's bars (NaN when that day has no bars)."""
    n = len(c)
    day = np.asarray(ts, "datetime64[ns]").astype("datetime64[D]").astype(np.int64)
    ud, first = np.unique(day, return_index=True)
    last = np.r_[first[1:], n] - 1
    do, dc = o[first], c[last]
    dh, dl = np.maximum.reduceat(h, first), np.minimum.reduceat(l, first)
    x = np.where(dc < do, dh + 2 * dl + dc, np.where(dc > do, 2 * dh + dl + dc, dh + dl + 2 * dc))
    s1, r1 = x / 2 - dh, x / 2 - dl
    ps1, pr1 = np.full(len(ud), np.nan), np.full(len(ud), np.nan)
    ok = np.r_[False, np.diff(ud) == 1]
    ps1[1:] = np.where(ok[1:], s1[:-1], np.nan)
    pr1[1:] = np.where(ok[1:], r1[:-1], np.nan)
    inv = np.searchsorted(ud, day)
    return ps1[inv], pr1[inv]


def htf_value(df: pd.DataFrame, tf: str, fn) -> np.ndarray:
    """Value of fn(higher-timeframe frame) on the last higher-timeframe bar closed at or before each bar's close."""
    E = env()
    df.attrs["tf"] = tf
    return E["SR"].htf_series(E["L"], df, HTF_OF[tf], fn)


# ------------------------------------------------------------------ the entries
def entries(df: pd.DataFrame, tf: str, ctx: dict | None = None, coin: str = "") -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{definition id: (long, short)} boolean arrays for the definitions that apply to ``tf``.
    ``ctx['BTCUSD']`` (a bar frame of BTC on the same timeframe) is needed for F14_SMT."""
    E = env()
    fg, pi = E["fg"], E["pi"]
    df.attrs["tf"] = tf
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    n = len(c)
    atr = fg.atr(df, 14).to_numpy(float)
    E200 = pi.pine_ema(c, 200)
    rsi14 = pi.pine_rsi(c, 14)
    R: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    z = np.zeros(n, bool)

    def put(name, lg, sh):
        if tf in dict((d[0], d[2]) for d in DEFS)[name]:
            R[name] = (np.asarray(lg, bool).copy(), np.asarray(sh, bool).copy())

    with np.errstate(invalid="ignore", divide="ignore"):
        S = structure(o, h, l, c)
        # ---------------- F1 divergences
        mom = c - _prev(c, 10)
        pvt = np.cumsum(np.nan_to_num(v * (c / _prev(c) - 1)))
        for name, ind in (("F1_RSI_DIV", rsi14), ("F1_MOM_DIV", mom), ("F1_PVT_DIV", pvt)):
            lg, sh = np.zeros(n, bool), np.zeros(n, bool)
            P = np.flatnonzero(S["ph_conf"]) - SW
            if len(P) > 1:
                a, b = P[:-1], P[1:]
                ok = ((b - a) <= 60) & (h[b] > h[a]) & (ind[b] < ind[a])
                sh[b[ok] + SW] = True
            Q = np.flatnonzero(S["pl_conf"]) - SW
            if len(Q) > 1:
                a, b = Q[:-1], Q[1:]
                ok = ((b - a) <= 60) & (l[b] < l[a]) & (ind[b] > ind[a])
                lg[b[ok] + SW] = True
            put(name, lg, sh)
        # ---------------- F2 DeMark
        s1, r1 = demark_levels(ts, o, h, l, c)
        put("F2_DEMARK", (l <= s1) & (c > s1), (h >= r1) & (c < r1))
        # ---------------- F3 structure
        put("F3_BOS", S["bos_up"], S["bos_dn"])
        e_up, e_dn = S["bos_up"] | S["mss_up"], S["bos_dn"] | S["mss_dn"]
        zl = [(int(b), float(S["dem_lo"][b]), float(S["dem_hi"][b]), 1, float("nan")) for b in np.flatnonzero(e_up)]
        zs = [(int(b), float(S["sup_lo"][b]), float(S["sup_hi"][b]), -1, float("nan")) for b in np.flatnonzero(e_dn)]

        def conf3(s, lo, hi, d):
            if s < 1:
                return False
            if d > 0:
                return bool(c[s] > o[s] and c[s] > h[s - 1] and c[s] > E200[s] and c[s] >= lo)
            return bool(c[s] < o[s] and c[s] < l[s - 1] and c[s] < E200[s] and c[s] <= hi)
        lg, sh = _resolve_wait(n, c, h, l, zl + zs, conf3)
        put("F3_BOS_ZONE", lg, sh)
        put("F3_HHHL", S["pl_conf"] & (S["lo"] > S["prev_lo"]) & (S["hi"] > S["prev_hi"]),
            S["ph_conf"] & (S["hi"] < S["prev_hi"]) & (S["lo"] < S["prev_lo"]))
        # ---------------- F4 EMA
        e9, e20, e50 = pi.pine_ema(c, 9), pi.pine_ema(c, 20), pi.pine_ema(c, 50)
        al_up = _prevb((e9 > e50) & (e50 > E200))
        al_dn = _prevb((e9 < e50) & (e50 < E200))
        put("F4_PULL", al_up & (l <= e50) & (c > e50), al_dn & (h >= e50) & (c < e50))
        r_prev = _prev(rsi14)
        put("F4_PULL_RSI", _prevb(e20 > e50) & (c > e50) & (r_prev <= 40) & (rsi14 > 40),
            _prevb(e20 < e50) & (c < e50) & (r_prev >= 60) & (rsi14 < 60))
        em = [pi.pine_ema(c, k) for k in (8, 13, 21, 34, 55)]
        fan_up = (em[0] > em[1]) & (em[1] > em[2]) & (em[2] > em[3]) & (em[3] > em[4])
        fan_dn = (em[0] < em[1]) & (em[1] < em[2]) & (em[2] < em[3]) & (em[3] < em[4])
        put("F4_FAN", _first_event(fan_up), _first_event(fan_dn))
        # ---------------- F5 box
        hi48 = pd.Series(h).rolling(48).max().shift(1).to_numpy()
        lo48 = pd.Series(l).rolling(48).min().shift(1).to_numpy()
        width = hi48 - lo48
        adx = fg.dmi_adx(df, 14, 14)[2].to_numpy(float)
        valid = (adx < 20) & (width >= 3 * atr)
        pos = (c - lo48) / width
        box_l = valid & (pos >= 0) & (pos <= 0.15) & (c > o)
        box_s = valid & (pos >= 0.85) & (pos <= 1) & (c < o)
        put("F5_BOX", box_l, box_s)
        put("F5_BOX_RSI", valid & (pos >= 0) & (pos <= 0.15) & (rsi14 < 30), valid & (pos >= 0.85) & (pos <= 1) & (rsi14 > 70))
        if "F5_BOX_HTF" in [d[0] for d in DEFS if tf in d[2]]:
            hadx = htf_value(df, tf, lambda dh: fg.dmi_adx(dh, 14, 14)[2].to_numpy(float))
            put("F5_BOX_HTF", box_l & (hadx < 20), box_s & (hadx < 20))
        # ---------------- F6 VWAP
        vw, vday = daily_vwap(ts, h, l, c, v)
        same = np.r_[False, vday[1:] == vday[:-1]]
        put("F6_VWAP_CROSS", same & (_prev(c) <= _prev(vw)) & (c > vw), same & (_prev(c) >= _prev(vw)) & (c < vw))
        lg, sh = np.zeros(n, bool), np.zeros(n, bool)
        down_x = np.flatnonzero(same & (_prev(c) >= _prev(vw)) & (c < vw))
        up_x = np.flatnonzero(same & (_prev(c) <= _prev(vw)) & (c > vw))
        for k in down_x:
            e = min(n, k + 11)
            sd = vday[k + 1:e] == vday[k]
            cand = sd & (h[k + 1:e] >= vw[k + 1:e]) & (c[k + 1:e] < vw[k + 1:e]) & (c[k + 1:e] < o[k + 1:e])
            kill = sd & (c[k + 1:e] > vw[k + 1:e])
            ic = int(cand.argmax()) if cand.any() else 10**9
            ik = int(kill.argmax()) if kill.any() else 10**9
            if ic < ik:
                sh[k + 1 + ic] = True
        for k in up_x:
            e = min(n, k + 11)
            sd = vday[k + 1:e] == vday[k]
            cand = sd & (l[k + 1:e] <= vw[k + 1:e]) & (c[k + 1:e] > vw[k + 1:e]) & (c[k + 1:e] > o[k + 1:e])
            kill = sd & (c[k + 1:e] < vw[k + 1:e])
            ic = int(cand.argmax()) if cand.any() else 10**9
            ik = int(kill.argmax()) if kill.any() else 10**9
            if ic < ik:
                lg[k + 1 + ic] = True
        put("F6_VWAP_FAIL", lg, sh)
        # ---------------- F7 Range Filter
        rf = range_filter_dir(c)
        put("F7_RF_ONLY", (rf == 1) & (_prev(rf) == -1), (rf == -1) & (_prev(rf) == 1))
        ha = heikin_bull(o, h, l, c)
        hha = htf_value(df, tf, lambda dh: heikin_bull(dh["open"].to_numpy(float), dh["high"].to_numpy(float),
                                                          dh["low"].to_numpy(float), dh["close"].to_numpy(float)))
        all_up = (rf == 1) & (ha == 1) & (hha == 1)
        all_dn = (rf == -1) & (ha == 0) & (hha == 0)
        put("F7_RF_TRIPLE", _first_event(all_up), _first_event(all_dn))
        # ---------------- F8 virgin wick
        body, rngb = np.abs(c - o), h - l
        big = (rngb > 0) & (body >= 0.7 * rngb) & (body >= 1.3 * atr)
        zb = [(int(k), float(l[k]), float(l[k]), 1, float("nan")) for k in np.flatnonzero(big & (c > o))]
        zb += [(int(k), float(h[k]), float(h[k]), -1, float("nan")) for k in np.flatnonzero(big & (c < o))]

        def conf8(s, lo, hi, d):
            return bool(c[s] > lo) if d > 0 else bool(c[s] < hi)
        lg, sh = resolve_zones(n, h, l, zb, conf8)
        put("F8_VWICK", lg, sh)
        # ---------------- F9 FVG / OB
        fz = fvg_zones(h, l, atr)

        def conf_mid(s, lo, hi, d):
            m = (lo + hi) / 2
            return bool(c[s] >= m) if d > 0 else bool(c[s] <= m)
        fvg_l, fvg_s = resolve_zones(n, h, l, fz, conf_mid)
        put("F9_FVG", fvg_l, fvg_s)
        lg, sh = resolve_zones(n, h, l, flip_zones(c, fz), conf_mid)
        put("F9_IFVG", lg, sh)
        oz = ob_zones(o, h, l, c)
        lg, sh = resolve_zones(n, h, l, oz, conf_mid)
        put("F9_OB", lg, sh)
        lg, sh = resolve_zones(n, h, l, flip_zones(c, oz), conf_mid)
        put("F9_BREAKER", lg, sh)
        # ---------------- F11 / F12
        L20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
        H20 = pd.Series(h).rolling(20).max().shift(1).to_numpy()
        age_lo, age_hi = np.full(n, -1.0), np.full(n, -1.0)
        if n > 20:
            wl = sliding_window_view(l, 20)[:n - 20]
            wh = sliding_window_view(h, 20)[:n - 20]
            idx = np.arange(20, n)
            age_lo[20:] = idx - (np.arange(n - 20) + wl.argmin(1))
            age_hi[20:] = idx - (np.arange(n - 20) + wh.argmax(1))
        put("F11_TSOUP", (l < L20) & (c > L20) & (age_lo >= 4), (h > H20) & (c < H20) & (age_hi >= 4))
        put("F11_RAID", S["raid_long"], S["raid_short"])
        put("F12_MSS", S["mss_up"], S["mss_dn"])
        disp_up, disp_dn = (c - o) >= 1.2 * atr, (o - c) >= 1.2 * atr
        mss_du, mss_dd = S["mss_up"] & disp_up, S["mss_dn"] & disp_dn
        put("F12_MSS_DISP", mss_du, mss_dd)
        # ---------------- F10 2022 model: sweep (<=20 bars before) -> displacement MSS (bar b-1 or b) -> FVG retest
        cs_l, cs_s = np.cumsum(S["raid_long"]), np.cumsum(S["raid_short"])

        def any_in(cs, a, b):          # any True in [a, b]
            a = max(a, 0)
            return (cs[b] - (cs[a - 1] if a > 0 else 0)) > 0 if b >= a else False
        zm = []
        for b, lo, hi, d, kill in fz:
            for m in (b - 1, b):
                if m < 0:
                    continue
                if d > 0 and mss_du[m] and any_in(cs_l, m - 20, m - 1):
                    zm.append((b, lo, hi, d, kill))
                    break
                if d < 0 and mss_dd[m] and any_in(cs_s, m - 20, m - 1):
                    zm.append((b, lo, hi, d, kill))
                    break
        lg, sh = resolve_zones(n, h, l, zm, conf_mid)
        put("F10_M2022", lg, sh)
        # ---------------- F13 premium / discount filter on F9_FVG and F11_RAID
        eq = (S["hi"] + S["lo"]) / 2
        okr = S["lo"] < S["hi"]
        disc, prem = okr & (c < eq), okr & (c > eq)
        put("F13_FVG_PD", fvg_l & disc, fvg_s & prem)
        put("F13_RAID_PD", S["raid_long"] & disc, S["raid_short"] & prem)
        # ---------------- F16 / F10 OTE
        legs = impulse_legs(S, h, l, atr)
        for name, f in FIB.items():
            zz = []
            for b, H, Lw, d in legs:
                if d > 0:
                    r = H - f * (H - Lw)
                    zz.append((b, r, r, 1, H))
                else:
                    r = Lw + f * (H - Lw)
                    zz.append((b, r, r, -1, Lw))

            def conf_lvl(s, lo, hi, d):
                return bool(c[s] > lo) if d > 0 else bool(c[s] < lo)
            lg, sh = resolve_zones(n, h, l, zz, conf_lvl)
            put(name, lg, sh)
        zo = []
        for b, H, Lw, d in legs:
            if d > 0:
                zo.append((b, H - 0.79 * (H - Lw), H - 0.62 * (H - Lw), 1, H))
            else:
                zo.append((b, Lw + 0.62 * (H - Lw), Lw + 0.79 * (H - Lw), -1, Lw))

        def conf_ote(s, lo, hi, d):
            return bool(c[s] > lo) if d > 0 else bool(c[s] < hi)
        lg, sh = resolve_zones(n, h, l, zo, conf_ote)
        put("F10_OTE", lg, sh)
        # ---------------- F14 SMT (BTC reference)
        lg, sh = np.zeros(n, bool), np.zeros(n, bool)
        btc = (ctx or {}).get("BTCUSD")
        if btc is not None and coin != "BTCUSD":
            bts = pd.to_datetime(btc["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
            bh, bl = btc["high"].to_numpy(float), btc["low"].to_numpy(float)
            bmax = pd.Series(bh).rolling(20).max().shift(1).to_numpy()
            bmin = pd.Series(bl).rolling(20).min().shift(1).to_numpy()
            new_hi_b, new_lo_b = bh > bmax, bl < bmin
            j = np.searchsorted(bts, ts)
            okj = (j < len(bts)) & (bts[np.minimum(j, len(bts) - 1)] == ts)
            jj = np.minimum(j, len(bts) - 1)
            nh, nl = okj & new_hi_b[jj], okj & new_lo_b[jj]
            xmax = pd.Series(h).rolling(20).max().shift(1).to_numpy()
            xmin = pd.Series(l).rolling(20).min().shift(1).to_numpy()
            sh = nh & (h <= xmax)
            lg = nl & (l >= xmin)
        put("F14_SMT", lg, sh)
        # ---------------- F15 sessions (15m / 30m / 1h only)
        if tf in SESSION_TFS:
            for name, (lg, sh) in session_signals(ts, o, h, l, c, TF_MIN[tf]).items():
                put(name, lg, sh)
        for name, (lg, sh) in utc_day_signals(ts, h, l, c, TF_MIN[tf]).items():
            put(name, lg, sh)
        # ---------------- F17 z-score
        sma = pd.Series(c).rolling(20).mean()
        sd = pd.Series(c).rolling(20).std(ddof=0)
        zsc = ((pd.Series(c) - sma) / sd).to_numpy()
        zl_, zs_ = (zsc < -2) & (_prev(zsc) >= -2), (zsc > 2) & (_prev(zsc) <= 2)
        put("F17_Z", zl_, zs_)
        x = pd.Series(np.log(c))
        xl = x.shift(1)
        phi = (x.rolling(100).cov(xl) / xl.rolling(100).var()).to_numpy()
        gate = phi <= 2.0 ** (-1 / 20)
        put("F17_Z_HL", zl_ & gate, zs_ & gate)
    out = {}
    for k in DEF_IDS:
        if k not in R:
            continue
        lg, sh = R[k]
        both = lg & sh
        out[k] = (lg & ~both, sh & ~both)
    return out


# ------------------------------------------------------------------ data
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_series(bars_dir: str, pre_dir: str, tf: str, coin: str, manifest: dict | None = None):
    """(main series 2021-01..2026-09-29, pre series 2020-01..2021-08-10). Binance USDT-M futures bars both."""
    E = env()
    L, lib = E["L"], E["lib"]
    stem = coin.lower()
    p = os.path.join(bars_dir, f"{stem}-{tf}.csv.gz")
    main = L.read_ohlcv(p)
    main = main[main["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    main.attrs["tf"] = tf
    if manifest is not None:
        manifest[os.path.basename(p)] = _sha256(p)
    src = "15m" if tf == "30m" else tf
    pp = os.path.join(pre_dir, f"{stem}-{src}.csv.gz")
    pre = pd.read_csv(pp)
    pre["ts"] = pd.to_datetime(pre["ts"], utc=True)
    pre = pre.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    pre = pre[pre["ts"] < lib.PRE[1] + pd.Timedelta(days=10)].reset_index(drop=True)
    if tf == "30m":
        pre = L.resample_ohlcv(pre, "30m")
    pre.attrs["tf"] = tf
    if manifest is not None:
        manifest["pre2021/" + os.path.basename(pp)] = _sha256(pp)
    return main, pre


def window_idx(L, df: pd.DataFrame, tf: str, start: str, end: str) -> tuple[int, int]:
    ts = L._utc_ns(df["ts"])
    lo = max(int(np.searchsorted(ts, np.datetime64(pd.Timestamp(start).tz_localize(None), "ns"))), L.warmup_bars(tf))
    hi = int(np.searchsorted(ts, np.datetime64(pd.Timestamp(end).tz_localize(None), "ns"))) - (MAX_HOLD + 1)
    return lo, max(lo, hi)


def exit_cfgs():
    E = env()
    lib, L = E["lib"], E["L"]
    by = {x[0]: x for x in lib.EXITS}
    return [(nm, L.ExitCfg(name=nm, mode=by[nm][1], sl_atr=by[nm][2], tp_atr=by[nm][3] if by[nm][3] else 1e4, trail_atr=by[nm][4]), MAX_HOLD)
            for nm in EXIT_NAMES]


def run_series(df: pd.DataFrame, tf: str, coin: str, splits: list[str], ctx: dict | None, only: set | None = None) -> pd.DataFrame:
    """Backtest every definition x exit on one series over the listed splits (labels in PERIODS)."""
    E = env()
    L, fg = E["L"], E["fg"]
    df.attrs["tf"] = tf
    atr = fg.atr(df, 14).to_numpy(float)
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy()
    sig = entries(df, tf, ctx, coin)
    wins = {s: window_idx(L, df, tf, *PERIODS[s]) for s in splits}
    parts = []
    for name, (lg, sh) in sig.items():
        if only is not None and name not in only:
            continue
        for xname, cfg, mh in exit_cfgs():
            for s, (lo, hi) in wins.items():
                if hi <= lo:
                    continue
                t = L.run_backtest(df, atr, lg, sh, cfg, L._cost(tf, mh), lo, hi)
                if len(t):
                    parts.append(pd.DataFrame({
                        "net": t["net"].to_numpy(np.float64), "gross": t["gross"].to_numpy(np.float32),
                        "mae": t["mae"].to_numpy(np.float32), "sl_dist": t["sl_dist"].to_numpy(np.float32),
                        "hold": t["hold"].to_numpy(np.int16), "side": t["side"].to_numpy(np.int8),
                        "entry_ts": ts[t["entry_idx"].to_numpy(int)], "exit_ts": ts[t["exit_idx"].to_numpy(int)],
                        "symbol": coin, "entry": name, "exit": xname, "split": s, "tf": tf}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _task(args):
    bars_dir, pre_dir, tf, coin = args
    man: dict = {}
    main, pre = load_series(bars_dir, pre_dir, tf, coin, man)
    ctx_main, ctx_pre = None, None
    if coin != "BTCUSD":
        bm, bp = load_series(bars_dir, pre_dir, tf, "BTCUSD", None)
        ctx_main, ctx_pre = {"BTCUSD": bm}, {"BTCUSD": bp}
    a = run_series(main, tf, coin, ["is", "oos"], ctx_main)
    b = run_series(pre, tf, coin, ["pre"], ctx_pre)
    return pd.concat([a, b], ignore_index=True), man, (len(main), len(pre))


# ------------------------------------------------------------------ statistics and gauntlet
def week_index(entry_ts) -> np.ndarray:
    days = np.asarray(entry_ts, "datetime64[ns]").astype("datetime64[D]").astype(np.int64)
    return (days + 3) // 7                      # Monday-based week number (1970-01-01 was a Thursday)


def _seed(tf: str, e: str, x: str, tag: str) -> int:
    return int(hashlib.sha256(f"{SEED}|{tf}|{e}|{x}|{tag}".encode()).hexdigest()[:8], 16)


def extra_rows(tt: pd.DataFrame, n_boot: int) -> list[dict]:
    """Per configuration: library gauntlet columns (lib.config_rows) + p12 (1st+2nd period, day-clustered), week-block
    bootstrap p, long/short means, gross / cost context."""
    E = env()
    lib, SR = E["lib"], E["SR"]
    from paperbot.agents.newlab import boot_mean_p
    tt = tt.copy()
    tt["symbol"] = tt["symbol"].astype(str)         # F14 has no BTC trades: unused categories break lib.coin_mdd
    rows = lib.config_rows(tt)
    key = {(r["tf"], r["entry"], r["exit"]): r for r in rows}
    for (tf, e, x), g in tt.groupby(["tf", "entry", "exit"], observed=True):
        r = key[(tf, e, x)]
        g12 = g[g["split"].isin(["is", "oos"])]
        net12 = g12["net"].to_numpy()
        day12 = pd.to_datetime(g12["entry_ts"]).dt.floor("D").to_numpy()
        r["p12"] = SR.mean_test(net12, day12)[1] if len(g12) >= 20 else 1.0
        r["n12"] = len(g12)
        r["mean12_pct"] = 100 * net12.mean() if len(net12) else np.nan
        r["boot_p12"] = boot_mean_p(week_index(g12["entry_ts"].to_numpy()), net12, n_boot, _seed(tf, e, x, "12")) if len(net12) else 1.0
        gp = g[g["split"] == "pre"]
        r["boot_p3"] = boot_mean_p(week_index(gp["entry_ts"].to_numpy()), gp["net"].to_numpy(), n_boot, _seed(tf, e, x, "3")) if len(gp) else 1.0
        for pre, sel in (("is_", g["split"] == "is"), ("cf_", g["split"] == "oos"), ("pre_", g["split"] == "pre")):
            gg = g[sel]
            r[f"{pre}long_mean_pct"] = 100 * gg.loc[gg["side"] > 0, "net"].mean()
            r[f"{pre}short_mean_pct"] = 100 * gg.loc[gg["side"] < 0, "net"].mean()
            r[f"{pre}gross_mean_pct"] = 100 * gg["gross"].astype(float).mean()
            r[f"{pre}cost_mean_pct"] = 100 * (gg["gross"].astype(float) - gg["net"]).mean()
            r[f"{pre}hold_mean"] = gg["hold"].astype(float).mean()
    return rows


def finish(rows: list[dict]) -> pd.DataFrame:
    """Join to the full configuration list (N rows), run the library stages and the PREREG decision rule."""
    E = env()
    lib, SR = E["lib"], E["SR"]
    t = pd.DataFrame(rows)
    full = pd.DataFrame(config_list(), columns=["tf", "entry", "exit"])
    full["family"] = full["entry"].map(FAMILY)
    t = full.merge(t, on=["tf", "entry", "exit"], how="left")
    for col in ("is_n", "cf_n", "pre_n", "n12"):
        t[col] = t[col].fillna(0)
    for col in ("is_p", "cf_p", "pre_p", "p12", "boot_p12", "boot_p3"):
        t[col] = t[col].fillna(1.0)
    t = lib.select(t)
    t["stage3_20x"] = t["stage3"] & t["x20_ok"]
    t["bh12"] = SR.bh(t["p12"].to_numpy(float), 0.10)
    t["candidate"] = t["stage3"] & t["bh12"]
    t["weak_candidate"] = t["stage3"] & ~t["bh12"]
    t["candidate_20x"] = t["candidate"] & t["x20_ok"]
    m = max(int(t["stage2"].sum()), 1)
    t["stage3_bonf"] = t["stage3"] & (t["pre_p"] < 0.05 / m)
    t["all3_positive"] = (t["is_mean_pct"] > 0) & (t["cf_mean_pct"] > 0) & (t["pre_mean_pct"] > 0)
    return t


def report(t: pd.DataFrame, out: str) -> dict:
    os.makedirs(out, exist_ok=True)
    t.to_csv(os.path.join(out, "results.csv"), index=False)
    # near misses: stage-1 top-30 failing exactly one stage-2 condition / stage-2 survivors failing exactly one stage-3 condition
    top = t[t["stage1_top"]].copy()
    k2 = max(int(t.attrs.get("top_k", 30)), 1)
    c2 = pd.DataFrame({"mean": top["cf_mean_pct"] > 0, "pf": top["cf_pf"] > 1, "coins": top["cf_coins_pos"] >= 4, "p": top["cf_p"] < 0.05 / k2})
    top["stage2_fails"] = (~c2).sum(axis=1)
    top["stage2_failed"] = c2.apply(lambda r: ",".join(k for k in c2.columns if not r[k]), axis=1)
    s2 = t[t["stage2"]].copy()
    if len(s2):
        c3 = pd.DataFrame({"mean": s2["pre_mean_pct"] > 0, "pf": s2["pre_pf"] > 1, "coins": (s2["pre_coins_pos"] >= 3) & (s2["pre_coins_pos"] > s2["pre_coins_n"] / 2), "p": s2["pre_p"] < 0.05})
        s2["stage3_fails"] = (~c3).sum(axis=1)
        s2["stage3_failed"] = c3.apply(lambda r: ",".join(k for k in c3.columns if not r[k]), axis=1)
    near = pd.concat([top[top["stage2_fails"].between(1, 1)].assign(kind="stage2_one_miss"),
                      s2[s2["stage3_fails"].between(1, 1)].assign(kind="stage3_one_miss") if len(s2) else None,
                      t[t["all3_positive"]].assign(kind="all_three_periods_positive")], ignore_index=True)
    near.to_csv(os.path.join(out, "near_miss.csv"), index=False)
    fam = t.groupby("family").agg(configs=("entry", "size"), stage1=("stage1", "sum"), stage1_top=("stage1_top", "sum"), stage2=("stage2", "sum"),
                                  stage3=("stage3", "sum"), bh12=("bh12", "sum"), candidate=("candidate", "sum"),
                                  all3_positive=("all3_positive", "sum"), is_mean_pct=("is_mean_pct", "mean"),
                                  cf_mean_pct=("cf_mean_pct", "mean"), pre_mean_pct=("pre_mean_pct", "mean"))
    fam.to_csv(os.path.join(out, "per_family.csv"))
    tfo = t.groupby("tf").agg(configs=("entry", "size"), is_n=("is_n", "sum"), cf_n=("cf_n", "sum"), pre_n=("pre_n", "sum"),
                              is_mean_pct=("is_mean_pct", "mean"), cf_mean_pct=("cf_mean_pct", "mean"), pre_mean_pct=("pre_mean_pct", "mean"),
                              is_gross_pct=("is_gross_mean_pct", "mean"), cf_gross_pct=("cf_gross_mean_pct", "mean"),
                              is_cost_pct=("is_cost_mean_pct", "mean"), cf_cost_pct=("cf_cost_mean_pct", "mean"),
                              is_hold=("is_hold_mean", "mean"), cf_hold=("cf_hold_mean", "mean"),
                              is_pos=("is_mean_pct", lambda s: int((s > 0).sum())), cf_pos=("cf_mean_pct", lambda s: int((s > 0).sum())),
                              pre_pos=("pre_mean_pct", lambda s: int((s > 0).sum())), all3_positive=("all3_positive", "sum"),
                              stage1=("stage1", "sum"), stage2=("stage2", "sum"), stage3=("stage3", "sum"), candidate=("candidate", "sum"))
    tfo.to_csv(os.path.join(out, "per_tf.csv"))
    summary = {"configs": len(t), "stage1": int(t["stage1"].sum()), "stage1_top": int(t["stage1_top"].sum()), "stage2": int(t["stage2"].sum()),
               "stage3": int(t["stage3"].sum()), "stage3_bonferroni": int(t["stage3_bonf"].sum()), "bh12_all": int(t["bh12"].sum()),
               "candidate": int(t["candidate"].sum()), "weak_candidate": int(t["weak_candidate"].sum()),
               "candidate_20x": int(t["candidate_20x"].sum()), "all_three_periods_positive": int(t["all3_positive"].sum())}
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    return summary


def run(bars: str, pre: str, out: str, procs: int, tfs: tuple, n_boot: int) -> None:
    t0 = time.time()
    rows, manifest = [], {}
    for tf in tfs:
        tasks = [(bars, pre, tf, coin) for coin in COINS]
        with Pool(procs) as pool:
            res = pool.map(_task, tasks)
        parts = [r[0] for r in res if len(r[0])]
        for r in res:
            manifest.update(r[1])
        tt = pd.concat(parts, ignore_index=True)
        for col in ("symbol", "entry", "exit", "split", "tf"):
            tt[col] = tt[col].astype("category")
        rows.extend(extra_rows(tt, n_boot))
        print(f"{tf}: {len(tt)} trades, {len(rows)} configs so far, {time.time() - t0:.0f}s", flush=True)
        del tt, parts
    t = finish(rows)
    summary = report(t, out)
    summary["seconds"] = round(time.time() - t0)
    summary["bars_dir"], summary["n_boot"] = bars, n_boot
    summary["code_sha256"] = {os.path.basename(__file__): _sha256(__file__)}
    pr = os.path.join(HERE, "PREREG_DEEPSEEK200.md")
    summary["prereg_sha256"] = _sha256(pr)
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    with open(os.path.join(out, "data_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(json.dumps(summary))


# ------------------------------------------------------------------ synthetic data (self-test only)
def synth(n: int = 9000, tf: str = "1h", seed: int = 0, start: str = "2021-01-01", vol: float = 0.006) -> pd.DataFrame:
    """Random walk with volatility clusters, trending / ranging regimes and occasional big candles. Synthetic only."""
    rng = np.random.default_rng(seed)
    tfm = TF_MIN[tf]
    ts = pd.date_range(start, periods=n, freq=f"{tfm}min", tz="UTC")
    regime = np.repeat(rng.choice([-1, 0, 0, 1], size=n // 150 + 1), 150)[:n]
    sig = vol * np.exp(np.repeat(rng.normal(0, 0.4, n // 80 + 1), 80)[:n])
    ret = rng.normal(0, 1, n) * sig + regime * 0.12 * sig
    jump = rng.random(n) < 0.02
    ret[jump] *= 4
    c = 100 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.0005, n))
    hi = np.maximum(o, c) * (1 + rng.uniform(0, 1, n) * sig * 0.8)
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 1, n) * sig * 0.8)
    return pd.DataFrame({"ts": ts, "open": o, "high": hi, "low": lo, "close": c, "volume": rng.lognormal(0, 1, n) * 100})


def synth_panel(n: int, tf: str, seed: int = 0) -> dict:
    return {coin: synth(n, tf, seed + i, vol=0.006 + 0.001 * i) for i, coin in enumerate(COINS)}


def lookahead_check(tf: str = "1h", n: int = 5000, cuts=(0.4, 0.66, 0.92), seed: int = 5) -> None:
    """Signals at bar t must be identical when bars after t are removed or replaced by junk."""
    df = synth(n, tf, seed)
    btc = synth(n, tf, seed + 100)
    full = entries(df, tf, {"BTCUSD": btc}, "ETHUSD")
    rng = np.random.default_rng(1)
    for cut in [int(n * f) for f in cuts]:
        d2 = df.iloc[:cut].copy()
        b2 = btc.iloc[:cut].copy()
        e2 = entries(d2, tf, {"BTCUSD": b2}, "ETHUSD")
        d3, b3 = df.copy(), btc.copy()
        for x in (d3, b3):
            for k in ("open", "high", "low", "close"):
                x.loc[x.index[cut:], k] = x[k].to_numpy()[cut:] * rng.uniform(0.5, 1.5, len(x) - cut)
            x.loc[x.index[cut:], "volume"] = rng.lognormal(0, 1, len(x) - cut) * 100
        e3 = entries(d3, tf, {"BTCUSD": b3}, "ETHUSD")
        for k in full:
            for side in (0, 1):
                assert np.array_equal(full[k][side][:cut], e2[k][side][:cut]), f"lookahead (removed) {k} {tf} cut={cut}"
                assert np.array_equal(full[k][side][:cut], e3[k][side][:cut]), f"lookahead (changed) {k} {tf} cut={cut}"


def selftest() -> None:
    assert len(DEFS) == 44 and len(set(DEF_IDS)) == 44
    assert len(config_list()) == 342, len(config_list())
    for tf in TFS:
        lookahead_check(tf, n=5000 if tf != "15m" else 4200)
    df = synth(20000, "1h", 11)
    btc = synth(20000, "1h", 12)
    e = entries(df, "1h", {"BTCUSD": btc}, "ETHUSD")
    assert set(e) == set(DEF_IDS), set(DEF_IDS) ^ set(e)
    silent = [k for k, (lg, sh) in e.items() if not (lg.any() or sh.any())]
    print("signals per definition (1h synthetic 20000 bars):", {k: int(lg.sum() + sh.sum()) for k, (lg, sh) in e.items()})
    assert not silent, silent
    e2 = entries(df, "1h", {"BTCUSD": btc}, "ETHUSD")
    for k in e:
        assert np.array_equal(e[k][0], e2[k][0]) and np.array_equal(e[k][1], e2[k][1]), f"nondeterministic {k}"
        assert e[k][0].dtype == bool and not (e[k][0] & e[k][1]).any()
    print("selftest ok")


def estimate(n: int = 6000) -> dict:
    """Time the pipeline on synthetic bars and extrapolate to the full run (6 coins x 4 timeframes x 2 series)."""
    E = env()
    L = E["L"]
    res = {}
    # real bar counts per coin: main series 2021-01-01..2026-09-29, pre series 2020-01-01..2021-08-10
    days_main, days_pre = 2098, 588
    for tf in TFS:
        df = synth(n, tf, 3)
        btc = synth(n, tf, 4)
        t0 = time.time()
        sig = entries(df, tf, {"BTCUSD": btc}, "ETHUSD")
        t_sig = time.time() - t0
        df.attrs["tf"] = tf
        t0 = time.time()
        tr = []
        atr = E["fg"].atr(df, 14).to_numpy(float)
        ncfg = 0
        for name, (lg, sh) in sig.items():
            for xname, cfg, mh in exit_cfgs():
                tr.append(L.run_backtest(df, atr, lg, sh, cfg, L._cost(tf, mh), 400, n - 60))
                ncfg += 1
        t_eng = time.time() - t0
        bars_coin = (days_main + days_pre) * 1440 / TF_MIN[tf]
        ntr = sum(len(x) for x in tr)
        res[tf] = dict(sig_s_per_bar=t_sig / n, eng_s_per_bar=t_eng / n, trades_per_bar=ntr / n, bars_per_coin=bars_coin,
                       cpu_s_signals=6 * bars_coin * t_sig / n, cpu_s_engine=6 * bars_coin * t_eng / n)
    tot = sum(r["cpu_s_signals"] + r["cpu_s_engine"] for r in res.values())
    res["total_cpu_seconds_before_stats"] = tot
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selftest":
        selftest()
    elif cmd == "count":
        print(len(DEFS), "definitions;", len(config_list()), "configurations")
    elif cmd == "estimate":
        print(json.dumps(estimate(), indent=1))
    elif cmd == "run":
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("--bars", required=True)
        ap.add_argument("--pre", default=os.path.join(ROOT, "data", "pre2021"))
        ap.add_argument("--out", default=os.path.join(HERE, "out"))
        ap.add_argument("--procs", type=int, default=4)
        ap.add_argument("--tfs", default=",".join(TFS))
        ap.add_argument("--n-boot", type=int, default=2000)
        a = ap.parse_args()
        run(a.bars, a.pre, a.out, a.procs, tuple(a.tfs.split(",")), a.n_boot)
    else:
        print(__doc__)
