"""DeepSeek-200 entries with every number a parameter, for the full-grid study (research/fullgrid, DESIGN_KO.md).

    long, short = signals(df, tf, "F16_FIB618", ctx, coin, cache, swing_k=4, zone_life=75)

``DEFS[name]`` lists the parameters of a definition (PARAMS entries as in research/entry_study/param_defs/*.py; a
'length' with a list default is scaled as a whole, like N02_ST_KST's kst_roc_lens). With no override,
``signals(df, tf, name, ctx, coin)`` equals ``lib_c.entries(df, tf, ctx, coin)[name]`` bar for bar
(tests/test_fullgrid_ds_defs.py: synthetic series on 15m / 30m / 1h / 4h and the Binance bars).

research/deepseek200/lib_c.py is loaded by path and never changed. Its helpers without numbers are reused
(_prev, _prevb, _first_event, pivots_conf, ob_zones, heikin_bull, daily_vwap, demark_levels, et_wall, _blocks,
htf_value); the ones with numbers are copied here with the number as an argument. The zone resolvers, flip_zones,
F6_VWAP_FAIL, F11_PO3 and F15_ORB are vectorized (zones x window matrices); each gives the lib_c loop's result exactly.

Fixed as in lib_c (not parameters): ATR 14, ADX 14/14 (signal and higher timeframe), RSI 14 of F5_BOX_RSI, E200
outside F3_BOS_ZONE, width 3 ATR of F5_BOX_RSI, the ET clock times, the Asia range 20:00-24:00 ET of D-1 and the
London range 02:00-05:00 ET, the OTE band 0.62-0.79, the FIB levels, PO3's window end 20:00 UTC, zone life 50 of
F10_M2022 and F10_OTE.

``cache``: one dict per (df, tf, coin, ctx), passed to every call on that series. It holds building blocks keyed by
the numbers they depend on (structure per swing_k, EMA / RSI per length, zones per their numbers, session blocks per
window, ...), so a call does only the work its overridden values change. A zone set is resolved once into a table
that answers every zone life up to HORIZON bars (first touch / confirm, first kill and flip offsets within H bars are
those within any shorter life that still reaches them), so a zone_life override costs O(zones). Results are the
same with or without the cache. It only grows: drop it between definitions to bound memory on long series.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LIB_C = os.path.join(ROOT, "research", "deepseek200", "lib_c.py")
_MODULE = "_fullgrid_ds_lib_c"          # private name: never the research / dssig / shadow200 module object


def _load_lib_c():
    """lib_c.py loaded from its file (as paperbot/shadow200.py does); one module object per process."""
    mod = sys.modules.get(_MODULE)
    if mod is None:
        spec = importlib.util.spec_from_file_location(_MODULE, LIB_C)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(_MODULE, None)
            raise
    return mod


C = _load_lib_c()
_prev, _prevb, _first_event = C._prev, C._prevb, C._first_event
_W = "research/deepseek200/lib_c.py"
_NAN = float("nan")
_CELLS = 1 << 21                        # matrix cells per chunk (zones x window) in the vectorized loops
HORIZON = 150                           # zone tables of a kept cache cover lives up to this (3 x EXP, the grid's top)


# ------------------------------------------------------------------ parameters
def _p(name, default, kind, where, neutral=None, bounds=None) -> dict:
    d = {"name": name, "default": default, "kind": kind, "neutral": neutral}
    if bounds is not None:
        d["bounds"] = bounds
    d["where"] = f"{_W}:{where}"
    return d


def _swing_k():
    return _p("swing_k", 3, "length", "SW = 3 (pivots_conf k; structure / F1 / impulse_legs offset t - SW)")


def _zone_life():
    return _p("zone_life", 50, "length", "EXP = 50 (zone life in bars: resolve_zones, _resolve_wait, flip_zones)")


def _fvg_min_atr():
    return _p("fvg_min_atr", 0.5, "mult", "FVG_MIN_ATR = 0.5 (fvg_zones: gap >= x ATR14)")


def _disp_atr():
    return _p("disp_atr", 1.2, "mult", "entries F12 (displacement: |c - o| >= 1.2 * atr, same side as the MSS)")


def _leg_atr():
    return _p("leg_atr", 3.0, "mult", "ZONE_ATR_LEG = 3.0 (impulse_legs: H - L >= x ATR14)")


def _leg_max_bars():
    return _p("leg_max_bars", 30, "length", "LEG_MAX_BARS = 30 (impulse_legs: opposite swing at most x bars earlier)")


def _div_max_bars():
    return _p("div_max_bars", 60, "length", "entries F1 ((b - a) <= 60: bars between the two pivots)")


def _rsi_len(where):
    return _p("rsi_len", 14, "length", f"entries {where} (rsi14 = pine_rsi(c, 14))")


def _box():
    return [_p("box_len", 48, "length", "entries F5 (rolling(48).max/min().shift(1) of high / low)"),
            _p("adx_max", 20.0, "threshold_abs", "entries F5 (adx < 20)", bounds=(0.0, 100.0))]


def _edge():
    return _p("edge", 0.15, "mult", "entries F5 (long pos <= 0.15, short pos >= 1 - 0.15)", bounds=(0.0, 0.5))


def _width_atr():
    return _p("width_atr", 3.0, "mult", "entries F5 (width >= 3 * atr)")


def _rf():
    return [_p("rf_period", 100, "length", "range_filter_dir (ewm span 100, second span 2 * 100 - 1 = 199)"),
            _p("rf_mult", 3.0, "mult", "range_filter_dir (3.0 * smoothed range)")]


def _legs():
    return [_swing_k(), _leg_atr(), _leg_max_bars()]


def _z():
    return [_p("z_len", 20, "length", "entries F17 (rolling(20) mean and std of close)"),
            _p("z_level", 2.0, "threshold_abs", "entries F17 (long: z crosses below -2, short: above +2)")]


DEFS: dict[str, list[dict]] = {
    "F1_RSI_DIV": [_swing_k(), _div_max_bars(), _rsi_len("F1")],
    "F1_MOM_DIV": [_swing_k(), _div_max_bars(), _p("mom_len", 10, "length", "entries F1 (mom = c - _prev(c, 10))")],
    "F1_PVT_DIV": [_swing_k(), _div_max_bars()],
    "F2_DEMARK": [],
    "F3_BOS": [_swing_k()],
    "F3_BOS_ZONE": [_swing_k(), _zone_life(), _p("ema_len", 200, "length", "entries F3 conf3 (E200 = pine_ema(c, 200))")],
    "F3_HHHL": [_swing_k()],
    "F4_PULL": [_p("ema_fast", 9, "length", "entries F4_PULL (e9)"), _p("ema_mid", 50, "length", "entries F4_PULL (e50)"),
                _p("ema_slow", 200, "length", "entries F4_PULL (E200)")],
    "F4_PULL_RSI": [_p("ema_fast", 20, "length", "entries F4_PULL_RSI (e20)"),
                    _p("ema_slow", 50, "length", "entries F4_PULL_RSI (e50)"), _rsi_len("F4_PULL_RSI"),
                    _p("rsi_level", 40.0, "threshold_neutral", "entries F4_PULL_RSI (long crosses up 40; short crosses "
                       "down the mirror 100 - level = 60)", neutral=50.0, bounds=(0.0, 100.0))],
    "F4_FAN": [_p("fan_lens", [8, 13, 21, 34, 55], "length", "entries F4_FAN (pine_ema lengths (8, 13, 21, 34, 55); "
                  "each element scaled)")],
    "F5_BOX": _box() + [_edge(), _width_atr()],
    "F5_BOX_RSI": _box() + [_edge(), _p("rsi_level", 30.0, "threshold_neutral", "entries F5_BOX_RSI (rsi14 < 30; short "
                                        "rsi14 > the mirror 100 - level = 70)", neutral=50.0, bounds=(0.0, 100.0))],
    "F5_BOX_HTF": _box() + [_edge(), _width_atr()],
    "F6_VWAP_CROSS": [],
    "F6_VWAP_FAIL": [_p("fail_bars", 10, "length", "entries F6_VWAP_FAIL (bars k+1 .. k+10 after the cross: k + 11)")],
    "F7_RF_TRIPLE": _rf(),
    "F7_RF_ONLY": _rf(),
    "F8_VWICK": [_p("body_frac", 0.7, "mult", "entries F8 (body >= 0.7 * range)", bounds=(0.0, 1.0)),
                 _p("body_atr", 1.3, "mult", "entries F8 (body >= 1.3 * atr)"), _zone_life()],
    "F9_FVG": [_fvg_min_atr(), _zone_life()],
    "F9_IFVG": [_fvg_min_atr(), _zone_life()],
    "F9_OB": [_zone_life()],
    "F9_BREAKER": [_zone_life()],
    "F10_M2022": [_swing_k(), _disp_atr(), _p("sweep_bars", 20, "length", "entries F10 (raid in [m - 20, m - 1])"),
                  _fvg_min_atr()],
    "F10_OTE": _legs(),
    "F11_TSOUP": [_p("tsoup_len", 20, "length", "entries F11 (L20 / H20 window and the age window)"),
                  _p("min_age", 4, "length", "entries F11 (age_lo / age_hi >= 4)")],
    "F11_RAID": [_swing_k()],
    "F11_PO3": [_p("po3_range_h", 8, "length", "PO3_RANGE_MIN = 8 * 60 (accumulation range: first 8 h of the UTC day, "
                   "whole hours)", bounds=(1, 16)),
                _p("po3_rev_bars", 3, "length", "PO3_REVERSAL_BARS = 3 (close back inside within 3 bars)")],
    "F12_MSS": [_swing_k()],
    "F12_MSS_DISP": [_swing_k(), _disp_atr()],
    "F13_FVG_PD": [_swing_k(), _fvg_min_atr(), _zone_life()],
    "F13_RAID_PD": [_swing_k()],
    "F14_SMT": [_p("smt_len", 20, "length", "entries F14 (rolling(20) max / min of BTC and of the coin)")],
    "F15_ASIA_BRK": [_p("asia_win_h", 8, "length", "session_signals (window 00:00-08:00 ET, whole hours)", bounds=(1, 20))],
    "F15_ASIA_SWEEP": [_p("asia_win_h", 8, "length", "session_signals (window 00:00-08:00 ET, whole hours)",
                          bounds=(1, 20))],
    "F15_LON_BRK": [_p("lon_win_h", 7, "length", "session_signals (window 05:00-12:00 ET, whole hours)", bounds=(1, 19))],
    "F15_OPEN0930": [_p("judge_min", 60, "length", "session_signals (judged on the first bar closing >= T_ref + 60 min)")],
    "F15_OPEN0000": [_p("judge_min", 60, "length", "session_signals (judged on the first bar closing >= T_ref + 60 min)")],
    "F15_ORB": [_p("orb_bars", 2, "length", "ORB_BARS = 2 (opening range = first 2 bars of the UTC day)")],
    "F16_FIB382": _legs() + [_zone_life()],
    "F16_FIB500": _legs() + [_zone_life()],
    "F16_FIB618": _legs() + [_zone_life()],
    "F16_FIB764": _legs() + [_zone_life()],
    "F17_Z": _z(),
    "F17_Z_HL": _z() + [_p("hl_len", 100, "length", "entries F17_Z_HL (rolling(100) cov / var of log close)"),
                        _p("half_life", 20, "length", "entries F17_Z_HL (gate phi <= 2 ** (-1 / 20))")],
}
assert list(DEFS) == list(C.DEF_IDS), "DEFS must follow lib_c.DEFS"
TFS_OF: dict[str, tuple] = {d: tuple(t) for d, _f, t in C.DEFS}
_SPEC = {name: {p["name"]: p for p in ps} for name, ps in DEFS.items()}


def _as_len(v, what: str) -> int:
    if isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, float, np.integer, np.floating)):
        raise ValueError(f"{what}: a length must be a whole number, got {v!r}")
    if not np.isfinite(v) or float(v) != int(v) or int(v) < 1:
        raise ValueError(f"{what}: a length must be a whole number >= 1, got {v!r}")
    return int(v)


def _resolve(name: str, overrides: dict) -> dict:
    spec = _SPEC[name]
    bad = sorted(set(overrides) - set(spec))
    if bad:
        raise ValueError(f"{name}: unknown parameter(s) {bad}")
    out = {}
    for k, s in spec.items():
        v = overrides.get(k, s["default"])
        if s["kind"] == "length" and isinstance(s["default"], (list, tuple)):
            v = tuple(_as_len(x, f"{name}.{k}") for x in v)
            if len(v) != len(s["default"]):
                raise ValueError(f"{name}.{k}: needs {len(s['default'])} lengths, got {len(v)}")
        elif s["kind"] == "length":
            v = _as_len(v, f"{name}.{k}")
        else:
            v = float(v)
        out[k] = v
    return out


# ------------------------------------------------------------------ building blocks with numbers (copied from lib_c)
def _lag(x: np.ndarray, k: int) -> np.ndarray:
    """lib_c._prev(x, k), also for k >= len(x) (all NaN)."""
    return _prev(x, k) if k < len(x) else np.full(len(x), np.nan)


def structure(o, h, l, c, k: int, piv=None) -> dict:
    """lib_c.structure with SW = k (pivots k bars each side, known k bars later)."""
    n = len(c)
    ph_conf, pl_conf = piv if piv is not None else C.pivots_conf(h, l, k)
    nan = _NAN
    hi_a, lo_a, phi_a, plo_a = (np.full(n, nan) for _ in range(4))
    hi_i, lo_i = np.full(n, -1), np.full(n, -1)
    bos_up, bos_dn, mss_up, mss_dn = (np.zeros(n, bool) for _ in range(4))
    raid_long, raid_short = np.zeros(n, bool), np.zeros(n, bool)
    dem_lo, dem_hi, sup_lo, sup_hi = (np.full(n, nan) for _ in range(4))
    hl, ll, cl = np.asarray(h, float).tolist(), np.asarray(l, float).tolist(), np.asarray(c, float).tolist()
    phc, plc = ph_conf.tolist(), pl_conf.tolist()
    hi_lvl = lo_lvl = prev_hi = prev_lo = nan
    hi_idx = lo_idx = -1
    hi_bos = lo_bos = hi_raid = lo_raid = False
    state = 0
    for t in range(n):
        if phc[t]:
            p = t - k
            prev_hi, hi_lvl, hi_idx = hi_lvl, hl[p], p
            hi_bos = hi_raid = True
        if plc[t]:
            p = t - k
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


def range_filter_dir(c, period: int, mult: float) -> np.ndarray:
    """lib_c.range_filter_dir with sampling period ``period`` (second span 2 * period - 1) and multiplier ``mult``."""
    c = np.asarray(c, float)
    d = pd.Series(c).diff().abs().fillna(0.0)
    avr = d.ewm(span=period, adjust=False).mean()
    rng = (mult * avr.ewm(span=2 * period - 1, adjust=False).mean()).to_numpy().tolist()
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


# zones are 5 arrays (birth, lo, hi, dir, kill) instead of lib_c's list of tuples; the order of zones never matters
# (every resolver ORs one signal per zone into the output)
def _zones(b=(), lo=(), hi=(), d=(), kill=None) -> tuple:
    b = np.asarray(b, np.int64)
    kill = np.full(len(b), np.nan) if kill is None else np.asarray(kill, float)
    return b, np.asarray(lo, float), np.asarray(hi, float), np.asarray(d, np.int64), kill


def _zcat(*zs) -> tuple:
    return tuple(np.concatenate([z[i] for z in zs]) for i in range(5)) if zs else _zones()


def _zlist(lst: list) -> tuple:
    if not lst:
        return _zones()
    b, lo, hi, d, kill = zip(*lst)
    return _zones(b, lo, hi, d, kill)


def fvg_zones(h, l, atr, min_atr: float) -> tuple:
    """lib_c.fvg_zones with FVG_MIN_ATR = min_atr."""
    n = len(h)
    if n < 3:
        return _zones()
    up = (l[2:] > h[:-2]) & ((l[2:] - h[:-2]) >= min_atr * atr[2:])
    dn = (h[2:] < l[:-2]) & ((l[:-2] - h[2:]) >= min_atr * atr[2:])
    bu, bd = np.flatnonzero(up) + 2, np.flatnonzero(dn) + 2
    return _zones(np.r_[bu, bd], np.r_[h[bu - 2], h[bd]], np.r_[l[bu], l[bd - 2]],
                  np.r_[np.ones(len(bu), np.int64), -np.ones(len(bd), np.int64)])


def _chunks(idx: np.ndarray, life: int):
    step = max(1, _CELLS // max(life, 1))
    for i in range(0, len(idx), step):
        yield idx[i:i + step]


def _window(b: np.ndarray, life: int, n: int):
    """(bar index matrix b+1 .. b+life clipped to n-1, in-range mask)."""
    m = b[:, None] + 1 + np.arange(life)
    inr = m < n
    return np.minimum(m, n - 1), inr


def _first(m: np.ndarray, life: int) -> np.ndarray:
    """First True column per row; ``life`` when the row has none."""
    return np.where(m.any(1), m.argmax(1), life)


def flip_zones(c, Z: tuple, life: int) -> tuple[tuple, np.ndarray]:
    """lib_c.flip_zones with EXP = life (vectorized): (flipped zones, need). need = flip offset + 1: the flipped zone
    exists for every zone life >= need (the first close beyond within ``life`` bars is the same for any shorter life
    that still reaches it)."""
    n = len(c)
    b, lo, hi, d, _k = Z
    parts, need = [], []
    if life >= 1:
        for up in (True, False):
            sel = np.flatnonzero((b + 1 < n) & ((d > 0) if up else ~(d > 0)))
            for q in _chunks(sel, life):
                I, inr = _window(b[q], life, n)
                m = (c[I] < lo[q, None]) if up else (c[I] > hi[q, None])
                j = _first(m & inr, life)
                g = j < life
                parts.append(_zones(b[q][g] + 1 + j[g], lo[q][g], hi[q][g], np.full(int(g.sum()), -1 if up else 1)))
                need.append(j[g] + 1)
    return _zcat(*parts), (np.concatenate(need) if need else np.zeros(0, np.int64))


# A resolution table holds, for the zones that fire within H bars of their birth, the zone index, the signal bar, its
# offset from birth and the side. lib_c's answer for any zone life L <= H is the rows with offset < L: the first touch
# (first confirm, for the wait variant) and the first kill within L bars are those within H bars when they lie below L.
def _table(b, ft, ok, up, H: int, need=None) -> dict:
    zi = np.flatnonzero(ok)
    return dict(H=H, zi=zi, s=b[zi] + 1 + ft[zi], ft=ft[zi], up=up[zi], need=None if need is None else need[zi])


def fire(n: int, T: dict, life: int, sel=None) -> tuple[np.ndarray, np.ndarray]:
    """(long, short) of table ``T`` (built for H >= life) at zone life ``life``; ``sel``: bool per zone of the table's
    zone set (only those zones count)."""
    if life > T["H"]:
        raise ValueError(f"table built for {T['H']} bars, asked for {life}")
    lg, sh = np.zeros(n, bool), np.zeros(n, bool)
    m = T["ft"] < life
    if T["need"] is not None:
        m &= T["need"] <= life
    if sel is not None:
        m &= sel[T["zi"]]
    s, up = T["s"][m], T["up"][m]
    lg[s[up]] = True
    sh[s[~up]] = True
    return lg, sh


def zone_table(n, h, l, c, Z: tuple, H: int, conf: str, need=None) -> dict:
    """lib_c.resolve_zones as a table for zone lives up to H. conf: 'mid' (close beyond the zone middle, conf_mid),
    'edge' (long close > lo, short close < hi: conf8 / conf_ote), 'lvl' (close beyond lo: conf_lvl)."""
    b, lo, hi, d, kill = Z
    ft, ok, up_all = np.full(len(b), H, np.int64), np.zeros(len(b), bool), d > 0
    valid = (b + 1 < n) & np.isfinite(lo) & np.isfinite(hi)
    for up in (True, False):
        sel = np.flatnonzero(valid & (up_all if up else ~up_all)) if H >= 1 else np.zeros(0, np.int64)
        for q in _chunks(sel, H):
            I, inr = _window(b[q], H, n)
            touch = ((l[I] <= hi[q, None]) if up else (h[I] >= lo[q, None])) & inr
            f = _first(touch, H)
            g = f < H
            kq = kill[q]
            if not np.isnan(kq).all():
                km = ((h[I] > kq[:, None]) if up else (l[I] < kq[:, None])) & inr
                g &= _first(km, H) > f
            cs, zl, zh = c[np.minimum(b[q] + 1 + f, n - 1)], lo[q], hi[q]
            if conf == "mid":
                mid = (zl + zh) / 2
                cf = cs >= mid if up else cs <= mid
            elif conf == "edge":
                cf = cs > zl if up else cs < zh
            elif conf == "lvl":
                cf = cs > zl if up else cs < zl
            else:
                raise ValueError(conf)
            ft[q], ok[q] = f, g & cf
    return _table(b, ft, ok, up_all, H, need)


def wait_table(n, c, h, l, Z: tuple, H: int, base_l: np.ndarray, base_s: np.ndarray) -> dict:
    """lib_c._resolve_wait as a table for zone lives up to H. conf3(s, lo, hi, d) = base_l[s] & (c[s] >= lo) for
    longs, base_s[s] & (c[s] <= hi) for shorts; a close beyond the far side (long c < lo, short c > hi) ends the zone."""
    b, lo, hi, d, _k = Z
    ft, ok, up_all = np.full(len(b), H, np.int64), np.zeros(len(b), bool), d > 0
    valid = np.isfinite(lo) & np.isfinite(hi)
    for up in (True, False):
        sel = np.flatnonzero(valid & (up_all if up else ~up_all)) if H >= 1 else np.zeros(0, np.int64)
        for q in _chunks(sel, H):
            I, inr = _window(b[q], H, n)
            cI, zl, zh = c[I], lo[q, None], hi[q, None]
            if up:
                km = cI < zl
                sg = (l[I] <= zh) & base_l[I] & (cI >= zl)
            else:
                km = cI > zh
                sg = (h[I] >= zl) & base_s[I] & (cI <= zh)
            fs = _first(sg & inr, H)
            ft[q], ok[q] = fs, (fs < H) & (fs < _first(km & inr, H))
    return _table(b, ft, ok, up_all, H)


def resolve_zones(n, h, l, c, Z: tuple, life: int, conf: str) -> tuple[np.ndarray, np.ndarray]:
    """lib_c.resolve_zones with EXP = life."""
    return fire(n, zone_table(n, h, l, c, Z, life, conf), life)


def resolve_wait(n, c, h, l, Z: tuple, life: int, base_l: np.ndarray, base_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """lib_c._resolve_wait with EXP = life."""
    return fire(n, wait_table(n, c, h, l, Z, life, base_l, base_s), life)


def impulse_legs(S: dict, h, l, atr, k: int, leg_atr: float, leg_max: int) -> tuple:
    """lib_c.impulse_legs with SW = k, ZONE_ATR_LEG = leg_atr, LEG_MAX_BARS = leg_max: (t, H, L, dir) arrays."""
    tu = np.flatnonzero(S["ph_conf"])
    p, q = tu - k, S["lo_idx"][tu]
    Hu, Lu = h[p], S["lo"][tu]
    oku = (q >= 0) & (p - q <= leg_max) & (Hu - Lu >= leg_atr * atr[tu])
    td = np.flatnonzero(S["pl_conf"])
    p, q = td - k, S["hi_idx"][td]
    Ld, Hd = l[p], S["hi"][td]
    okd = (q >= 0) & (p - q <= leg_max) & (Hd - Ld >= leg_atr * atr[td])
    return (np.r_[tu[oku], td[okd]], np.r_[Hu[oku], Hd[okd]], np.r_[Lu[oku], Ld[okd]],
            np.r_[np.ones(int(oku.sum()), np.int64), -np.ones(int(okd.sum()), np.int64)])


# ------------------------------------------------------------------ one series: base arrays + memoized blocks
class _Series:
    """The arrays of one (df, tf, coin, ctx) and its block cache (a fresh dict when the caller passes none)."""

    def __init__(self, df: pd.DataFrame, tf: str, ctx, coin: str, cache):
        self.df, self.tf, self.ctx, self.coin = df, tf, ctx, coin
        self.cache = {} if cache is None else cache
        self.horizon = 0 if cache is None else HORIZON
        n = len(df)
        cl = df["close"].to_numpy(float)
        fp = (tf, coin, n, cl[[0, -1]].tobytes() if n else b"")
        base = self.cache.get("__base__")
        if base is None:
            o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
            ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
            base = self.cache["__base__"] = dict(fp=fp, o=o, h=h, l=l, c=c, v=v, ts=ts)
        elif base["fp"] != fp:
            raise ValueError("cache was built for another series (tf, coin, length or closes differ)")
        self.o, self.h, self.l, self.c, self.v, self.ts = (base[k] for k in ("o", "h", "l", "c", "v", "ts"))
        self.n, self.tfm = n, C.TF_MIN[tf]

    def get(self, key, fn):
        try:
            return self.cache[key]
        except KeyError:
            v = self.cache[key] = fn()
            return v

    def table(self, key, build, life: int) -> dict:
        """The resolution table ``key`` covering ``life``: build(H) with H = max(life, horizon), rebuilt when a longer
        life is asked."""
        T = self.cache.get(key)
        if T is None or T["H"] < life:
            T = self.cache[key] = build(max(life, self.horizon))
        return T

    # indicators
    def atr(self):
        return self.get(("atr",), lambda: C.env()["fg"].atr(self.df, 14).to_numpy(float))

    def ema(self, k: int):
        return self.get(("ema", k), lambda: C.env()["pi"].pine_ema(self.c, k))

    def rsi(self, k: int):
        return self.get(("rsi", k), lambda: C.env()["pi"].pine_rsi(self.c, k))

    def adx(self):
        return self.get(("adx",), lambda: C.env()["fg"].dmi_adx(self.df, 14, 14)[2].to_numpy(float))

    def hadx(self):
        fg = C.env()["fg"]
        return self.get(("hadx",), lambda: C.htf_value(self.df, self.tf, lambda dh: fg.dmi_adx(dh, 14, 14)[2].to_numpy(float)))

    def hmax1(self, k: int):
        return self.get(("hmax1", k), lambda: pd.Series(self.h).rolling(k).max().shift(1).to_numpy())

    def lmin1(self, k: int):
        return self.get(("lmin1", k), lambda: pd.Series(self.l).rolling(k).min().shift(1).to_numpy())

    # structure
    def piv(self, k: int):
        return self.get(("piv", k), lambda: C.pivots_conf(self.h, self.l, k))

    def S(self, k: int) -> dict:
        return self.get(("S", k), lambda: structure(self.o, self.h, self.l, self.c, k, self.piv(k)))

    def pd_zone(self, k: int):
        def mk():
            S = self.S(k)
            eq = (S["hi"] + S["lo"]) / 2
            okr = S["lo"] < S["hi"]
            return okr & (self.c < eq), okr & (self.c > eq)
        return self.get(("pd", k), mk)

    def mss_disp(self, k: int, disp: float):
        def mk():
            S, atr = self.S(k), self.atr()
            return S["mss_up"] & ((self.c - self.o) >= disp * atr), S["mss_dn"] & ((self.o - self.c) >= disp * atr)
        return self.get(("mssd", k, disp), mk)

    def legs(self, k: int, leg_atr: float, leg_max: int):
        return self.get(("legs", k, leg_atr, leg_max),
                        lambda: impulse_legs(self.S(k), self.h, self.l, self.atr(), k, leg_atr, leg_max))

    # zones
    def fvgz(self, x: float):
        return self.get(("fvgz", x), lambda: fvg_zones(self.h, self.l, self.atr(), x))

    def fvg_fire(self, x: float, life: int, sel=None):
        T = self.table(("fvgtab", x), lambda H: zone_table(self.n, self.h, self.l, self.c, self.fvgz(x), H, "mid"), life)
        return fire(self.n, T, life, sel)

    def obz(self):
        return self.get(("obz",), lambda: _zlist(C.ob_zones(self.o, self.h, self.l, self.c)))

    # sessions / days
    def et(self):
        def mk():
            day, mins = C.et_wall(self.ts)
            ev = mins >= 20 * 60
            asia = {}
            if ev.any():
                g = pd.DataFrame({"d": day[ev] + 1, "h": self.h[ev], "l": self.l[ev]}).groupby("d").agg(
                    hi=("h", "max"), lo=("l", "min"), cnt=("h", "size"))
                full = g[g["cnt"] == 240 // self.tfm]
                asia = dict(zip(full.index.tolist(), zip(full["hi"].tolist(), full["lo"].tolist())))
            return day, mins, C._blocks(day), asia
        return self.get(("et",), mk)

    def utcday(self):
        def mk():
            dayd = self.ts.astype("datetime64[D]")
            day = dayd.astype(np.int64)
            mins = ((self.ts - dayd.astype("datetime64[ns]")) // np.timedelta64(1, "m")).astype(np.int64)
            if not self.n:
                e = np.zeros(0, np.int64)
                return mins, e, e, e
            cut = np.flatnonzero(np.diff(day) != 0) + 1
            st, en = np.r_[0, cut], np.r_[cut, self.n]
            return mins, st, en, np.repeat(np.arange(len(st)), en - st)
        return self.get(("utcday",), mk)


def _lead_ok(X: _Series, nb: int, strict: bool):
    """Per UTC day: (ok, first-nb-bar index matrix): the day's first nb bars sit at minutes 0, tfm, .. (nb-1) * tfm and
    the day has at least nb bars (more than nb when ``strict``), as utc_day_signals checks."""
    mins, st, en, _blk = X.utcday()
    J = np.arange(nb)
    I = st[:, None] + J
    inb = I < en[:, None]
    I = np.minimum(I, max(X.n - 1, 0))
    ok = inb.all(1) & (mins[I] == J * X.tfm).all(1)
    if strict:
        ok &= (en - st) > nb
    return ok, I


def _first_per_day(mask: np.ndarray, blk: np.ndarray, nblk: int) -> np.ndarray:
    """First bar index of each day where mask is True (a large number where none)."""
    out = np.full(nblk, 10**18, np.int64)
    idx = np.flatnonzero(mask)
    if len(idx):
        u, f = np.unique(blk[idx], return_index=True)
        out[u] = idx[f]
    return out


# ------------------------------------------------------------------ the definitions (one function each)
def _div(X: _Series, p: dict, ind: np.ndarray):
    k, mx = p["swing_k"], p["div_max_bars"]
    h, l, n = X.h, X.l, X.n
    P, Q = X.get(("pividx", k), lambda: tuple(np.flatnonzero(x) - k for x in X.piv(k)))
    lg, sh = np.zeros(n, bool), np.zeros(n, bool)
    if len(P) > 1:
        a, b = P[:-1], P[1:]
        ok = ((b - a) <= mx) & (h[b] > h[a]) & (ind[b] < ind[a])
        sh[b[ok] + k] = True
    if len(Q) > 1:
        a, b = Q[:-1], Q[1:]
        ok = ((b - a) <= mx) & (l[b] < l[a]) & (ind[b] > ind[a])
        lg[b[ok] + k] = True
    return lg, sh


def _f1_rsi(X, p):
    return _div(X, p, X.rsi(p["rsi_len"]))


def _f1_mom(X, p):
    m = p["mom_len"]
    return _div(X, p, X.get(("mom", m), lambda: X.c - _lag(X.c, m)))


def _f1_pvt(X, p):
    return _div(X, p, X.get(("pvt",), lambda: np.cumsum(np.nan_to_num(X.v * (X.c / _prev(X.c) - 1)))))


def _f2(X, p):
    def mk():
        s1, r1 = C.demark_levels(X.ts, X.o, X.h, X.l, X.c)
        return (X.l <= s1) & (X.c > s1), (X.h >= r1) & (X.c < r1)
    return X.get(("F2",), mk)


def _f3_bos(X, p):
    S = X.S(p["swing_k"])
    return S["bos_up"], S["bos_dn"]


def _f3_bos_zone(X, p):
    k, life, e = p["swing_k"], p["zone_life"], p["ema_len"]

    def zones():
        S = X.S(k)
        bu = np.flatnonzero(S["bos_up"] | S["mss_up"])
        bd = np.flatnonzero(S["bos_dn"] | S["mss_dn"])
        return _zones(np.r_[bu, bd], np.r_[S["dem_lo"][bu], S["sup_lo"][bd]], np.r_[S["dem_hi"][bu], S["sup_hi"][bd]],
                      np.r_[np.ones(len(bu), np.int64), -np.ones(len(bd), np.int64)])

    def base():                         # conf3 without the zone term: s >= 1, body, close beyond bar s-1, beyond EMA
        E, ph, pl = X.ema(e), _prev(X.h), _prev(X.l)
        return (X.c > X.o) & (X.c > ph) & (X.c > E), (X.c < X.o) & (X.c < pl) & (X.c < E)
    bl, bs = X.get(("conf3", e), base)
    T = X.table(("bosw", k, e), lambda H: wait_table(X.n, X.c, X.h, X.l, X.get(("bosz", k), zones), H, bl, bs), life)
    return fire(X.n, T, life)


def _f3_hhhl(X, p):
    S = X.S(p["swing_k"])
    return (S["pl_conf"] & (S["lo"] > S["prev_lo"]) & (S["hi"] > S["prev_hi"]),
            S["ph_conf"] & (S["hi"] < S["prev_hi"]) & (S["lo"] < S["prev_lo"]))


def _f4_pull(X, p):
    ef, em, es = X.ema(p["ema_fast"]), X.ema(p["ema_mid"]), X.ema(p["ema_slow"])
    al_up = _prevb((ef > em) & (em > es))
    al_dn = _prevb((ef < em) & (em < es))
    return al_up & (X.l <= em) & (X.c > em), al_dn & (X.h >= em) & (X.c < em)


def _f4_pull_rsi(X, p):
    ef, es, k = X.ema(p["ema_fast"]), X.ema(p["ema_slow"]), p["rsi_len"]
    r = X.rsi(k)
    rp = X.get(("rsi_prev", k), lambda: _prev(r))
    lo_lv = p["rsi_level"]
    hi_lv = 100.0 - lo_lv
    return (_prevb(ef > es) & (X.c > es) & (rp <= lo_lv) & (r > lo_lv),
            _prevb(ef < es) & (X.c < es) & (rp >= hi_lv) & (r < hi_lv))


def _f4_fan(X, p):
    em = [X.ema(k) for k in p["fan_lens"]]
    up = dn = np.ones(X.n, bool)
    for a, b in zip(em[:-1], em[1:]):
        up, dn = up & (a > b), dn & (a < b)
    return _first_event(up), _first_event(dn)


def _box(X, p, width_atr: float):
    bl = p["box_len"]

    def geom():
        hi, lo = X.hmax1(bl), X.lmin1(bl)
        width = hi - lo
        return width, (X.c - lo) / width
    width, pos = X.get(("box", bl), geom)
    valid = (X.adx() < p["adx_max"]) & (width >= width_atr * X.atr())
    e = p["edge"]
    return valid & (pos >= 0) & (pos <= e), valid & (pos >= 1 - e) & (pos <= 1)


def _f5_box(X, p):
    lg, sh = _box(X, p, p["width_atr"])
    return lg & (X.c > X.o), sh & (X.c < X.o)


def _f5_box_rsi(X, p):
    lg, sh = _box(X, p, 3.0)
    r, lv = X.rsi(14), p["rsi_level"]
    return lg & (r < lv), sh & (r > 100.0 - lv)


def _f5_box_htf(X, p):
    lg, sh = _f5_box(X, p)
    hq = X.hadx() < p["adx_max"]
    return lg & hq, sh & hq


def _vwap(X):
    def mk():
        vw, vday = C.daily_vwap(X.ts, X.h, X.l, X.c, X.v)
        same = np.r_[False, vday[1:] == vday[:-1]]
        pc, pv = _prev(X.c), _prev(vw)
        return vw, vday, same & (pc <= pv) & (X.c > vw), same & (pc >= pv) & (X.c < vw)
    return X.get(("vwap",), mk)


def _f6_cross(X, p):
    _vw, _d, up_x, dn_x = _vwap(X)
    return up_x, dn_x


def _f6_fail(X, p):
    fb = p["fail_bars"]

    def mk():
        vw, vday, up_x, dn_x = _vwap(X)
        c, o, n = X.c, X.o, X.n
        lg, sh = np.zeros(n, bool), np.zeros(n, bool)
        # per bar: the retest candidate and the kill of lib_c's F6_VWAP_FAIL loop (same UTC day as the cross)
        cand_s, kill_s = (X.h >= vw) & (c < vw) & (c < o), c > vw
        cand_l, kill_l = (X.l <= vw) & (c > vw) & (c > o), c < vw
        for out, ev, cand, kill in ((sh, dn_x, cand_s, kill_s), (lg, up_x, cand_l, kill_l)):
            for q in _chunks(np.flatnonzero(ev), fb):
                I, inr = _window(q, fb, n)
                sd = (vday[I] == vday[q][:, None]) & inr
                ic, ik = _first(sd & cand[I], fb), _first(sd & kill[I], fb)
                g = (ic < fb) & (ic < ik)
                out[q[g] + 1 + ic[g]] = True
        return lg, sh
    return X.get(("F6_FAIL", fb), mk)


def _rf_dir(X, p):
    pr, m = p["rf_period"], p["rf_mult"]
    return X.get(("rf", pr, m), lambda: range_filter_dir(X.c, pr, m))


def _f7_only(X, p):
    rf = _rf_dir(X, p)
    pr = X.get(("rf_prev",) + (p["rf_period"], p["rf_mult"]), lambda: _prev(rf))
    return (rf == 1) & (pr == -1), (rf == -1) & (pr == 1)


def _f7_triple(X, p):
    rf = _rf_dir(X, p)
    ha = X.get(("ha",), lambda: C.heikin_bull(X.o, X.h, X.l, X.c))
    hha = X.get(("hha",), lambda: C.htf_value(X.df, X.tf, lambda dh: C.heikin_bull(
        dh["open"].to_numpy(float), dh["high"].to_numpy(float), dh["low"].to_numpy(float), dh["close"].to_numpy(float))))
    return _first_event((rf == 1) & (ha == 1) & (hha == 1)), _first_event((rf == -1) & (ha == 0) & (hha == 0))


def _f8(X, p):
    bf, ba = p["body_frac"], p["body_atr"]

    def zones():
        body, rngb = X.get(("body",), lambda: (np.abs(X.c - X.o), X.h - X.l))
        big = (rngb > 0) & (body >= bf * rngb) & (body >= ba * X.atr())
        ku, kd = np.flatnonzero(big & (X.c > X.o)), np.flatnonzero(big & (X.c < X.o))
        return _zones(np.r_[ku, kd], np.r_[X.l[ku], X.h[kd]], np.r_[X.l[ku], X.h[kd]],
                      np.r_[np.ones(len(ku), np.int64), -np.ones(len(kd), np.int64)])
    life = p["zone_life"]
    T = X.table(("vwick", bf, ba), lambda H: zone_table(X.n, X.h, X.l, X.c, zones(), H, "edge"), life)
    return fire(X.n, T, life)


def _f9_fvg(X, p):
    return X.fvg_fire(p["fvg_min_atr"], p["zone_life"])


def _flip_table(X, Z: tuple, H: int) -> dict:
    Zf, need = flip_zones(X.c, Z, H)
    return zone_table(X.n, X.h, X.l, X.c, Zf, H, "mid", need)


def _f9_ifvg(X, p):
    x, life = p["fvg_min_atr"], p["zone_life"]
    return fire(X.n, X.table(("ifvgtab", x), lambda H: _flip_table(X, X.fvgz(x), H), life), life)


def _f9_ob(X, p):
    life = p["zone_life"]
    return fire(X.n, X.table(("obtab",), lambda H: zone_table(X.n, X.h, X.l, X.c, X.obz(), H, "mid"), life), life)


def _f9_breaker(X, p):
    life = p["zone_life"]
    return fire(X.n, X.table(("brktab",), lambda H: _flip_table(X, X.obz(), H), life), life)


def _f10_m2022(X, p):
    k, sw = p["swing_k"], p["sweep_bars"]
    du, dd = X.mss_disp(k, p["disp_atr"])

    def recent():                       # lib_c any_in(cs, m - sweep_bars, m - 1): a raid in [max(m - sw, 0), m - 1]
        S, m = X.S(k), np.arange(X.n)
        out = []
        for raid in (S["raid_long"], S["raid_short"]):
            P = np.r_[0, np.cumsum(raid)]
            out.append((m >= 1) & ((P[m] - P[np.maximum(m - sw, 0)]) > 0))
        return tuple(out)
    rl, rs = X.get(("recent", k, sw), recent)
    b, _lo, _hi, d, _kill = X.fvgz(p["fvg_min_atr"])
    bm = np.maximum(b - 1, 0)           # the MSS bar m is b - 1 or b (fvg births are >= 2, so b - 1 >= 1)
    inc = np.where(d > 0, ((b >= 1) & du[bm] & rl[bm]) | (du[b] & rl[b]), ((b >= 1) & dd[bm] & rs[bm]) | (dd[b] & rs[b]))
    return X.fvg_fire(p["fvg_min_atr"], 50, inc)


def _f10_ote(X, p):
    key = (p["swing_k"], p["leg_atr"], p["leg_max_bars"])

    def build(Hz):
        t, H, Lw, d = X.legs(*key)
        up = d > 0
        rg = H - Lw
        Z = (t, np.where(up, H - 0.79 * rg, Lw + 0.62 * rg), np.where(up, H - 0.62 * rg, Lw + 0.79 * rg), d,
             np.where(up, H, Lw))
        return zone_table(X.n, X.h, X.l, X.c, Z, Hz, "edge")
    return fire(X.n, X.table(("ote",) + key, build, 50), 50)


def _fib(f: float):
    def fn(X, p):
        key, life = (p["swing_k"], p["leg_atr"], p["leg_max_bars"]), p["zone_life"]

        def build(Hz):
            t, H, Lw, d = X.legs(*key)
            up = d > 0
            r = np.where(up, H - f * (H - Lw), Lw + f * (H - Lw))
            return zone_table(X.n, X.h, X.l, X.c, (t, r, r, d, np.where(up, H, Lw)), Hz, "lvl")
        return fire(X.n, X.table(("fib", f) + key, build, life), life)
    return fn


def _f11_tsoup(X, p):
    w, a = p["tsoup_len"], p["min_age"]

    def ages():
        n, l, h = X.n, X.l, X.h
        age_lo, age_hi = np.full(n, -1.0), np.full(n, -1.0)
        if n > w:
            wl = sliding_window_view(l, w)[:n - w]
            wh = sliding_window_view(h, w)[:n - w]
            idx = np.arange(w, n)
            age_lo[w:] = idx - (np.arange(n - w) + wl.argmin(1))
            age_hi[w:] = idx - (np.arange(n - w) + wh.argmax(1))
        return age_lo, age_hi
    age_lo, age_hi = X.get(("age", w), ages)
    Lw, Hw = X.lmin1(w), X.hmax1(w)
    return (X.l < Lw) & (X.c > Lw) & (age_lo >= a), (X.h > Hw) & (X.c < Hw) & (age_hi >= a)


def _f11_raid(X, p):
    S = X.S(p["swing_k"])
    return S["raid_long"], S["raid_short"]


def _f11_po3(X, p):
    rmin, rev = p["po3_range_h"] * 60, p["po3_rev_bars"]

    def mk():
        n, tfm, c = X.n, X.tfm, X.c
        mins, st, en, blk = X.utcday()
        lg, sh = np.zeros(n, bool), np.zeros(n, bool)
        if not n:
            return lg, sh
        nr = max(1, rmin // tfm)
        ok, I = _lead_ok(X, nr, False)
        rh, rl = np.where(ok, X.h[I].max(1), np.nan), np.where(ok, X.l[I].min(1), np.nan)
        up, dn = X.h > rh[blk], X.l < rl[blk]
        K = np.flatnonzero(ok[blk] & (mins >= rmin) & (mins < C.PO3_WINDOW_END) & (up != dn))
        if not len(K):
            return lg, sh
        # first t in k .. k+rev (same day, no missing bar since k) whose close is back inside [rl, rh]
        J = np.arange(rev + 1)
        T = K[:, None] + J
        bk = blk[K]
        Tc = np.minimum(T, n - 1)
        alive = np.logical_and.accumulate((T < en[bk][:, None]) & (mins[Tc] - mins[K][:, None] == J * tfm), axis=1)
        hit = alive & (rl[bk][:, None] <= c[Tc]) & (c[Tc] <= rh[bk][:, None])
        has = hit.any(1)
        t, b, side = (K + hit.argmax(1))[has], bk[has], np.where(up[K], -1, 1)[has]
        if not len(t):
            return lg, sh
        tmin = np.full(len(st), np.iinfo(np.int64).max)
        np.minimum.at(tmin, b, t)
        at = t == tmin[b]
        pos, neg = np.zeros(len(st), bool), np.zeros(len(st), bool)
        pos[b[at & (side > 0)]] = True
        neg[b[at & (side < 0)]] = True
        lg[tmin[pos & ~neg]] = True
        sh[tmin[neg & ~pos]] = True
        return lg, sh
    return X.get(("po3", rmin, rev), mk)


def _f12_mss(X, p):
    S = X.S(p["swing_k"])
    return S["mss_up"], S["mss_dn"]


def _f12_mss_disp(X, p):
    return X.mss_disp(p["swing_k"], p["disp_atr"])


def _f13_fvg_pd(X, p):
    fl, fs = X.fvg_fire(p["fvg_min_atr"], p["zone_life"])
    disc, prem = X.pd_zone(p["swing_k"])
    return fl & disc, fs & prem


def _f13_raid_pd(X, p):
    S = X.S(p["swing_k"])
    disc, prem = X.pd_zone(p["swing_k"])
    return S["raid_long"] & disc, S["raid_short"] & prem


def _f14_smt(X, p):
    n, w = X.n, p["smt_len"]
    btc = (X.ctx or {}).get("BTCUSD")
    if btc is None or X.coin == "BTCUSD":
        return np.zeros(n, bool), np.zeros(n, bool)

    def bmap():
        bts = pd.to_datetime(btc["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
        j = np.searchsorted(bts, X.ts)
        okj = (j < len(bts)) & (bts[np.minimum(j, len(bts) - 1)] == X.ts)
        return okj, np.minimum(j, len(bts) - 1), btc["high"].to_numpy(float), btc["low"].to_numpy(float)
    okj, jj, bh, bl = X.get(("btc", len(btc)), bmap)

    def btc_new():
        bmax = pd.Series(bh).rolling(w).max().shift(1).to_numpy()
        bmin = pd.Series(bl).rolling(w).min().shift(1).to_numpy()
        return okj & (bh > bmax)[jj], okj & (bl < bmin)[jj]
    nh, nl = X.get(("btc_new", len(btc), w), btc_new)
    return nl & (X.l >= X.lmin1(w)), nh & (X.h <= X.hmax1(w))


def _asia(X, p):
    W = p["asia_win_h"] * 60

    def mk():
        n, h, l, c = X.n, X.h, X.l, X.c
        _day, mins, blocks, asia = X.et()
        brk = (np.zeros(n, bool), np.zeros(n, bool))
        swp = (np.zeros(n, bool), np.zeros(n, bool))
        for d, a, b in blocks:
            if d not in asia:
                continue
            m = mins[a:b]
            hh, ll, cc = h[a:b], l[a:b], c[a:b]
            ahi, alo = asia[d]
            win = (m >= 0) & (m < W)
            iu = np.flatnonzero(win & (cc > ahi))
            idn = np.flatnonzero(win & (cc < alo))
            first_u = iu[0] if len(iu) else 10**9
            first_d = idn[0] if len(idn) else 10**9
            if first_u < first_d:
                brk[0][a + first_u] = True
            elif first_d < first_u:
                brk[1][a + first_d] = True
            su = np.flatnonzero(win & (hh > ahi) & (cc < ahi))
            sd = np.flatnonzero(win & (ll < alo) & (cc > alo))
            first_su = su[0] if len(su) else 10**9
            first_sd = sd[0] if len(sd) else 10**9
            if first_su < first_sd:
                swp[1][a + first_su] = True
            elif first_sd < first_su:
                swp[0][a + first_sd] = True
        return {"F15_ASIA_BRK": brk, "F15_ASIA_SWEEP": swp}
    return X.get(("asia", W), mk)


def _f15_asia_brk(X, p):
    return _asia(X, p)["F15_ASIA_BRK"]


def _f15_asia_sweep(X, p):
    return _asia(X, p)["F15_ASIA_SWEEP"]


def _f15_lon(X, p):
    end = 300 + p["lon_win_h"] * 60

    def mk():
        n, h, l, c, tfm = X.n, X.h, X.l, X.c, X.tfm
        _day, mins, blocks, _asia_ = X.et()
        lg, sh = np.zeros(n, bool), np.zeros(n, bool)
        for _d, a, b in blocks:
            m = mins[a:b]
            hh, ll, cc = h[a:b], l[a:b], c[a:b]
            lr = (m >= 120) & (m < 300)
            if lr.sum() == 180 // tfm:
                lhi, llo = hh[lr].max(), ll[lr].min()
                win = (m >= 300) & (m < end)
                iu = np.flatnonzero(win & (cc > lhi))
                idn = np.flatnonzero(win & (cc < llo))
                first_u = iu[0] if len(iu) else 10**9
                first_d = idn[0] if len(idn) else 10**9
                if first_u < first_d:
                    lg[a + first_u] = True
                elif first_d < first_u:
                    sh[a + first_d] = True
        return lg, sh
    return X.get(("lon", end), mk)


def _open(X, p):
    jm = p["judge_min"]

    def mk():
        n, o, c, tfm = X.n, X.o, X.c, X.tfm
        _day, mins, blocks, _asia_ = X.et()
        out = {k: (np.zeros(n, bool), np.zeros(n, bool)) for k in ("F15_OPEN0930", "F15_OPEN0000")}
        for _d, a, b in blocks:
            m = mins[a:b]
            cc, oo = c[a:b], o[a:b]
            for name, tref in (("F15_OPEN0930", 9 * 60 + 30), ("F15_OPEN0000", 0)):
                r = np.flatnonzero((m <= tref) & (tref < m + tfm))
                if not len(r):
                    continue
                r0 = int(r[0])
                cand = np.flatnonzero((np.arange(len(m)) >= r0) & (m + tfm >= tref + jm))
                if not len(cand):
                    continue
                s0 = int(cand[0])
                if m[s0] - m[r0] != (s0 - r0) * tfm:
                    continue
                if cc[s0] > oo[r0]:
                    out[name][0][a + s0] = True
                elif cc[s0] < oo[r0]:
                    out[name][1][a + s0] = True
        return out
    return X.get(("open", jm), mk)


def _f15_open0930(X, p):
    return _open(X, p)["F15_OPEN0930"]


def _f15_open0000(X, p):
    return _open(X, p)["F15_OPEN0000"]


def _f15_orb(X, p):
    nb = p["orb_bars"]

    def mk():
        n, c = X.n, X.c
        lg, sh = np.zeros(n, bool), np.zeros(n, bool)
        if not n:
            return lg, sh
        mins, st, _en, blk = X.utcday()
        ok, I = _lead_ok(X, nb, True)
        oh, ol = np.where(ok, X.h[I].max(1), np.nan), np.where(ok, X.l[I].min(1), np.nan)
        after = ok[blk] & ((np.arange(n) - st[blk]) >= nb)
        fu = _first_per_day(after & (c > oh[blk]), blk, len(st))
        fd = _first_per_day(after & (c < ol[blk]), blk, len(st))
        lg[fu[fu < fd]] = True
        sh[fd[fd < fu]] = True
        return lg, sh
    return X.get(("orb", nb), mk)


def _zscore(X, w):
    def mk():
        s = pd.Series(X.c)
        z = ((s - s.rolling(w).mean()) / s.rolling(w).std(ddof=0)).to_numpy()
        return z, _prev(z)
    return X.get(("z", w), mk)


def _f17_z(X, p):
    z, zp = _zscore(X, p["z_len"])
    lv = p["z_level"]
    return (z < -lv) & (zp >= -lv), (z > lv) & (zp <= lv)


def _f17_z_hl(X, p):
    lg, sh = _f17_z(X, p)
    w = p["hl_len"]

    def phi():
        x = pd.Series(np.log(X.c))
        xl = x.shift(1)
        return (x.rolling(w).cov(xl) / xl.rolling(w).var()).to_numpy()
    gate = X.get(("phi", w), phi) <= 2.0 ** (-1 / p["half_life"])
    return lg & gate, sh & gate


_FN = {
    "F1_RSI_DIV": _f1_rsi, "F1_MOM_DIV": _f1_mom, "F1_PVT_DIV": _f1_pvt,
    "F2_DEMARK": _f2,
    "F3_BOS": _f3_bos, "F3_BOS_ZONE": _f3_bos_zone, "F3_HHHL": _f3_hhhl,
    "F4_PULL": _f4_pull, "F4_PULL_RSI": _f4_pull_rsi, "F4_FAN": _f4_fan,
    "F5_BOX": _f5_box, "F5_BOX_RSI": _f5_box_rsi, "F5_BOX_HTF": _f5_box_htf,
    "F6_VWAP_CROSS": _f6_cross, "F6_VWAP_FAIL": _f6_fail,
    "F7_RF_TRIPLE": _f7_triple, "F7_RF_ONLY": _f7_only,
    "F8_VWICK": _f8,
    "F9_FVG": _f9_fvg, "F9_IFVG": _f9_ifvg, "F9_OB": _f9_ob, "F9_BREAKER": _f9_breaker,
    "F10_M2022": _f10_m2022, "F10_OTE": _f10_ote,
    "F11_TSOUP": _f11_tsoup, "F11_RAID": _f11_raid, "F11_PO3": _f11_po3,
    "F12_MSS": _f12_mss, "F12_MSS_DISP": _f12_mss_disp,
    "F13_FVG_PD": _f13_fvg_pd, "F13_RAID_PD": _f13_raid_pd,
    "F14_SMT": _f14_smt,
    "F15_ASIA_BRK": _f15_asia_brk, "F15_ASIA_SWEEP": _f15_asia_sweep, "F15_LON_BRK": _f15_lon,
    "F15_OPEN0930": _f15_open0930, "F15_OPEN0000": _f15_open0000, "F15_ORB": _f15_orb,
    **{name: _fib(f) for name, f in C.FIB.items()},
    "F17_Z": _f17_z, "F17_Z_HL": _f17_z_hl,
}
assert set(_FN) == set(DEFS)


def signals(df: pd.DataFrame, tf: str, name: str, ctx: dict | None = None, coin: str = "", cache: dict | None = None,
            **overrides) -> tuple[np.ndarray, np.ndarray]:
    """(long, short) boolean arrays of len(df) for definition ``name`` on ``tf`` (known at each bar's close);
    lib_c.entries(df, tf, ctx, coin)[name] when no override is given. ``ctx['BTCUSD']`` is needed for F14_SMT.
    Unknown names, timeframes the definition does not cover, and unknown or malformed overrides raise ValueError."""
    if name not in DEFS:
        raise ValueError(f"unknown definition {name!r}")
    if tf not in TFS_OF[name]:
        raise ValueError(f"{name} is not defined on {tf} (only {TFS_OF[name]})")
    p = _resolve(name, overrides)
    X = _Series(df, tf, ctx, coin, cache)
    with np.errstate(invalid="ignore", divide="ignore"):
        lg, sh = _FN[name](X, p)
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    both = lg & sh
    return lg & ~both, sh & ~both
