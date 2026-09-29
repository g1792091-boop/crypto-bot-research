"""gap_4: independent SPEC-BASED ports of the 12 FINGRAD strategies stage 1 excluded
(S1 S3 S4 N04 N05 N06 N11 N13 N15 N16 N19 N20).

Source of truth available: ONLY the previous session's prose report (artifact
46br7PTC1MtZoe78PAgGNF, text copy critic/doc_31set.txt lines 219-312) plus the
verbatim FINGRAD indicators.py (bt/fg_indicators.py).  fingrad_bot/strategies/*.py
(evaluate(), suggest_stop()) is NOT in the package, so none of this can be checked
against the real code.

Every port returns a dict:
  L, S        bool arrays: signal on bar t close
  stopL/stopS float arrays: documented initial structural stop if entered after bar t
  trailL/S    float arrays or None: per-bar trailing-stop proposal (applied favourably only)
  exL/exS     bool arrays or None: strategy-specific exit condition for an open LONG / SHORT
              (FINGRAD applies it with CONFIRM_2: true on 2 consecutive closes, >=2 bars held)
Opposite-signal exit (also CONFIRM_2) is added by the simulator from S / L.

Readings of ambiguous spec text are marked AMBIG and have a `variant` switch.
"""
from __future__ import annotations
import os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import fg_indicators as fg
import fg_fast
from strategies import _b, _f, recent, gt, lt, ge, le, cross_above, cross_below, shift_bool
from poc_fast import poc_series


def _roll_min(x, n):
    return pd.Series(_f(x)).rolling(n, min_periods=n).min().to_numpy()


def _roll_max(x, n):
    return pd.Series(_f(x)).rolling(n, min_periods=n).max().to_numpy()


def _sh(x, k):
    x = _f(x)
    out = np.full(len(x), np.nan)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:] = x
    return out


def _base(df):
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    a = _f(fg.atr(df, 14))
    return o, h, l, c, a


def _pack(L, S, stopL, stopS, trailL=None, trailS=None, exL=None, exS=None):
    L = _b(L); S = _b(S) & ~L
    return dict(L=L, S=S, stopL=_f(stopL), stopS=_f(stopS), trailL=trailL, trailS=trailS, exL=exL, exS=exS)


# ---------------------------------------------------------------- S1
def s1(df, variant=0):
    """S1 EMA5/20 + RSI14 + chop_zone_proxy (EMA34 1-bar slope angle), sync 3, FRESH."""
    o, h, l, c, a = _base(df)
    close = df["close"]
    e5, e20 = fg.ema(close, 5), fg.ema(close, 20)
    r = _f(fg.rsi(close, 14)); r1 = _sh(r, 1)
    _ang, cz, _st = fg.chop_zone_proxy(df, 34, 1.0, 5.0, 14)
    cz = _f(cz); cz1 = _sh(cz, 1)
    eu, ed = cross_above(e5, e20), cross_below(e5, e20)
    with np.errstate(invalid="ignore"):
        ru = (r1 < 30) & (r > r1); rd = (r1 > 70) & (r < r1)
        cu = (cz1 <= 0) & (cz > 0); cd = (cz1 >= 0) & (cz < 0)
        lst = (_f(e5) > _f(e20)) & (cz > 0); sst = (_f(e5) < _f(e20)) & (cz < 0)
    L = recent(eu, 3) & recent(ru, 3) & recent(cu, 3) & lst & (eu | ru | cu)
    S = recent(ed, 3) & recent(rd, 3) & recent(cd, 3) & sst & (ed | rd | cd)
    stopL = _roll_min(l, 3) - 0.1 * a; stopS = _roll_max(h, 3) + 0.1 * a
    # unique exit: EMA opposite cross OR (chop == 0 AND RSI moving against)
    with np.errstate(invalid="ignore"):
        exL = ed | ((cz == 0) & (r < r1)); exS = eu | ((cz == 0) & (r > r1))
    return _pack(L, S, stopL, stopS, stopL, stopS, exL, exS)


# ---------------------------------------------------------------- S3
def _prior_dir(c, first_lag, n=5, variant=0):
    """direction of the n closes before the pattern's first bar (first bar = t-first_lag).
    AMBIG: variant 0 -> c[t-fl-1] vs c[t-fl-n] (first vs last of the 5 preceding bars);
           variant 1 -> c[t-fl-1] vs c[t-fl-1-n] (critic's reading, 5-bar change)."""
    last = _sh(c, first_lag + 1)
    first = _sh(c, first_lag + n) if variant == 0 else _sh(c, first_lag + 1 + n)
    with np.errstate(invalid="ignore"):
        return last > first, last < first


def s3(df, variant=0):
    """S3 CMO14 + stick sandwich (3 bars, bodies >= 0.08 ATR), sync 3, FRESH."""
    o, h, l, c, a = _base(df)
    b = c - o
    b1, b2, b3 = _sh(b, 2), _sh(b, 1), b
    h1, h3, l1, l3 = _sh(h, 2), h, _sh(l, 2), l
    up_prior, dn_prior = _prior_dir(c, 2, 5, variant)
    with np.errstate(invalid="ignore"):
        bodies = (np.abs(b1) >= 0.08 * a) & (np.abs(b2) >= 0.08 * a) & (np.abs(b3) >= 0.08 * a)
        bear = up_prior & bodies & (b1 > 0) & (b2 < 0) & (b3 > 0) & (np.abs(h1 - h3) <= 0.3 * a) \
            & (c <= np.maximum(h1, h3) + 0.075 * a)
        bull = dn_prior & bodies & (b1 < 0) & (b2 > 0) & (b3 < 0) & (np.abs(l1 - l3) <= 0.3 * a) \
            & (c >= np.minimum(l1, l3) - 0.075 * a)
    cm = fg.cmo(df["close"], 14)
    cmu, cmd = cross_above(cm, 0.0), cross_below(cm, 0.0)
    L = recent(bull, 3) & recent(cmu, 3) & gt(cm, 0.0) & (bull | cmu)
    S = recent(bear, 3) & recent(cmd, 3) & lt(cm, 0.0) & (bear | cmd)
    # stop: low/high of the most recent qualifying pattern (completed at t, t-1 or t-2)
    pl3 = _roll_min(l, 3); ph3 = _roll_max(h, 3)
    stopL = np.full(len(c), np.nan); stopS = np.full(len(c), np.nan)
    for lag in (2, 1, 0):  # later assignment = more recent pattern wins
        pb = shift_bool(bull, lag) if lag else _b(bull)
        ps = shift_bool(bear, lag) if lag else _b(bear)
        stopL = np.where(pb, _sh(pl3, lag) - 0.1 * a, stopL)
        stopS = np.where(ps, _sh(ph3, lag) + 0.1 * a, stopS)
    # if FRESH came from CMO cross and pattern older, stopL already set by the loop
    exL = _b(cmd) | _b(bear); exS = _b(cmu) | _b(bull)
    return _pack(L, S, stopL, stopS, None, None, exL, exS)


# ---------------------------------------------------------------- S4
def s4(df, variant=0):
    o, h, l, c, a = _base(df)
    close = df["close"]
    up, mid, lo, bw = fg.bollinger_bands(close, 20, 2.0)
    thr = fg.rolling_percentile_threshold(bw, 100, 0.2)
    sq = le(bw, thr)
    sq_prev = recent(shift_bool(sq, 1), 5)          # any of t-1..t-5
    _bu, _be, bbp = fg.bull_bear_power(df, 13)
    L = sq_prev & gt(close, up) & le(close.shift(1), up.shift(1)) & gt(bbp, 0.0)
    S = sq_prev & lt(close, lo) & ge(close.shift(1), lo.shift(1)) & lt(bbp, 0.0)
    stopL = l - 0.1 * a; stopS = h + 0.1 * a
    trL = _roll_min(l, 3) - 0.1 * a; trS = _roll_max(h, 3) + 0.1 * a
    exL = lt(close, mid) | lt(bbp, 0.0); exS = gt(close, mid) | gt(bbp, 0.0)
    return _pack(L, S, stopL, stopS, trL, trS, exL, exS)


# ---------------------------------------------------------------- N04
def n04(df, variant=0):
    """N02 structure with Klinger(34,55,13) in place of KST."""
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    kl, ks = fg.klinger_oscillator(df, 34, 55, 13)
    up, dn = cross_above(kl, ks), cross_below(kl, ks)
    d = _f(direction); dp = _sh(d, 1)
    with np.errstate(invalid="ignore"):
        fu = (d > 0) & (dp <= 0); fd = (d < 0) & (dp >= 0)
    L = gt(d, 0) & recent(up, 2) & (up | fu)
    S = lt(d, 0) & recent(dn, 2) & (dn | fd)
    st = _f(line)
    exL = lt(d, 0) | dn; exS = gt(d, 0) | up
    return _pack(L, S, st, st, st, st, exL, exS)


# ---------------------------------------------------------------- N05
def n05(df, variant=0):
    o, h, l, c, a = _base(df)
    poc = poc_series(df, 100, 32)
    psar, pdir = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)
    ps = _f(psar); pd_ = _f(pdir)
    o1, c1 = _sh(o, 1), _sh(c, 1)
    with np.errstate(invalid="ignore"):
        sup = (np.abs(l - poc) <= 0.2 * a) | ((l <= poc) & (poc <= c))
        res = (np.abs(h - poc) <= 0.2 * a) | ((c <= poc) & (poc <= h))
        pierce = (c1 < o1) & (c > o) & (c >= (o1 + c1) / 2.0) & (c < o1)
        dark = (c1 > o1) & (c < o) & (c <= (o1 + c1) / 2.0) & (c > o1)
        L = sup & pierce & (c > ps)
        S = res & dark & (c < ps)
        pdp = _sh(pd_, 1)
        exL = (pd_ < 0) & (pdp > 0); exS = (pd_ > 0) & (pdp < 0)
    stopL = _roll_min(l, 2) - 0.1 * a; stopS = _roll_max(h, 2) + 0.1 * a
    return _pack(L, S, stopL, stopS, ps, ps, exL, exS)


# ---------------------------------------------------------------- N06
def n06(df, variant=0):
    o, h, l, c, a = _base(df)
    ts = pd.to_datetime(df["ts"], utc=True)
    day = ts.dt.floor("D")
    first = ~day.duplicated()                       # first bar of each UTC date (00:00 bar)
    orb_h = pd.Series(np.where(first, h, np.nan)).ffill().to_numpy()
    orb_l = pd.Series(np.where(first, l, np.nan)).ffill().to_numpy()
    fa = first.to_numpy()
    orb_h[fa] = np.nan; orb_l[fa] = np.nan          # range not complete on its own bar
    c1 = _sh(c, 1)
    with np.errstate(invalid="ignore"):
        bu = (c > orb_h) & (c1 <= orb_h)           # same-day level
        bd = (c < orb_l) & (c1 >= orb_l)
    ml, sl, hist = fg.macd(df["close"], 12, 26, 9)
    mu, md = cross_above(ml, sl), cross_below(ml, sl)
    hs = _f(hist); hs1 = _sh(hs, 1); mlf = _f(ml)
    with np.errstate(invalid="ignore"):
        L = recent(bu, 2) & recent(mu, 2) & (mlf > 0) & (hs > 0) & (hs >= hs1) & ((c - orb_h) <= 1.5 * a) & (bu | mu)
        S = recent(bd, 2) & recent(md, 2) & (mlf < 0) & (hs < 0) & (hs <= hs1) & ((orb_l - c) <= 1.5 * a) & (bd | md)
    stopL = orb_l - 0.1 * a; stopS = orb_h + 0.1 * a
    trL = _roll_min(l, 3) - 0.1 * a; trS = _roll_max(h, 3) + 0.1 * a
    return _pack(L, S, stopL, stopS, trL, trS, _b(md), _b(mu))


# ---------------------------------------------------------------- N11
def n11(df, variant=0, stop_variant=0):
    """Breakaway 5 bars; bar5 = t.  AMBIG prior trend (see _prior_dir), AMBIG stop '5봉 저가'."""
    o, h, l, c, a = _base(df)
    b = c - o
    B1, B2, B3, B4, B5 = (_sh(b, k) for k in (4, 3, 2, 1, 0))
    O2, C1, C2 = _sh(o, 3), _sh(c, 4), _sh(c, 3)
    upp, dnp = _prior_dir(c, 4, 5, variant)
    with np.errstate(invalid="ignore"):
        bull = dnp & (B1 < 0) & (-B1 >= 0.8 * a) & (B2 < 0) & (O2 <= C1 + 0.05 * a) \
            & (np.abs(B3) <= 0.4 * a) & (np.abs(B4) <= 0.4 * a) & (B5 > 0) & (B5 >= 0.8 * a) & (c > C2)
        bear = upp & (B1 > 0) & (B1 >= 0.8 * a) & (B2 > 0) & (O2 >= C1 - 0.05 * a) \
            & (np.abs(B3) <= 0.4 * a) & (np.abs(B4) <= 0.4 * a) & (B5 < 0) & (-B5 >= 0.8 * a) & (c < C2)
    if stop_variant == 0:
        stopL = _roll_min(l, 5) - 0.1 * a; stopS = _roll_max(h, 5) + 0.1 * a
    else:
        stopL = l - 0.1 * a; stopS = h + 0.1 * a
    return _pack(bull, bear, stopL, stopS, None, None, _b(bear), _b(bull))


# ---------------------------------------------------------------- N13
def n13(df, variant=0):
    """Three Outside Up/Down + confirmation breakout of the pattern high within 2 bars."""
    o, h, l, c, a = _base(df)
    b = c - o
    upp, dnp = _prior_dir(c, 2, 5, variant)
    B1, B2, B3 = _sh(b, 2), _sh(b, 1), b
    O1, C1, O2, C2 = _sh(o, 2), _sh(c, 2), _sh(o, 1), _sh(c, 1)
    with np.errstate(invalid="ignore"):
        bull = dnp & (B1 < 0) & (B2 > 0) & (B2 >= 0.5 * a) & (O2 <= C1) & (C2 >= O1) & (B3 > 0) & (c > C2)
        bear = upp & (B1 > 0) & (B2 < 0) & (-B2 >= 0.5 * a) & (O2 >= C1) & (C2 <= O1) & (B3 < 0) & (c < C2)
    ph3, pl3 = _roll_max(h, 3), _roll_min(l, 3)
    n = len(c)
    L = np.zeros(n, bool); S = np.zeros(n, bool)
    stopL = np.full(n, np.nan); stopS = np.full(n, np.nan)
    c1 = _sh(c, 1)
    for lag in (2, 1):  # pattern completed lag bars ago (lag 0 cannot break its own high)
        pb, ps = shift_bool(bull, lag), shift_bool(bear, lag)
        PH, PL = _sh(ph3, lag), _sh(pl3, lag)
        with np.errstate(invalid="ignore"):
            lk = pb & (c > PH) & (c1 <= PH)
            sk = ps & (c < PL) & (c1 >= PL)
        L |= lk; S |= sk
        stopL = np.where(lk, PL - 0.1 * a, stopL)
        stopS = np.where(sk, PH + 0.1 * a, stopS)
    return _pack(L, S, stopL, stopS, None, None, S.copy(), L.copy())


# ---------------------------------------------------------------- N15
def n15(df, variant=0):
    o, h, l, c, a = _base(df)
    up, mid, lo = fg.keltner_channel(df, 20, 10, 2.0)
    ao = _f(fg.awesome_oscillator(df, 5, 34)); ao1 = _sh(ao, 1)
    upf, lof = _f(up), _f(lo)
    with np.errstate(invalid="ignore"):
        L = (_sh(l, 1) < _sh(lof, 1)) & (c > lof) & (ao > ao1) & (ao > 0)
        S = (_sh(h, 1) > _sh(upf, 1)) & (c < upf) & (ao < ao1) & (ao < 0)
        exL = h >= upf; exS = l <= lof
    return _pack(L, S, l - 0.1 * a, h + 0.1 * a, None, None, exL, exS)


# ---------------------------------------------------------------- N16
def n16(df, variant=0):
    o, h, l, c, a = _base(df)
    up, mid, lo, rsi_, mp, sg = fg.mapped_rsi_bollinger(df, 20, 2.0, 14, 5, 2.0)
    upf, lof, mpf = _f(up), _f(lo), _f(mp)
    mp1, lo1, up1 = _sh(mpf, 1), _sh(lof, 1), _sh(upf, 1)
    xu, xd = cross_above(mp, sg), cross_below(mp, sg)
    with np.errstate(invalid="ignore"):
        reL = (mp1 < lo1) & (mpf >= lof) & xu
        reS = (mp1 > up1) & (mpf <= upf) & xd
    # divergence on confirmed price pivots (L3/R3), spacing 5..60 bars, AMBIG: pivots on price
    n = len(c)
    evL, _v = fg.confirmed_pivot_low(df["low"], 3, 3)
    evH, _w = fg.confirmed_pivot_high(df["high"], 3, 3)
    divL = np.zeros(n, bool); divS = np.zeros(n, bool)
    prev = None
    for i in np.where(_b(evL))[0]:
        p = i - 3
        if prev is not None and 5 <= p - prev <= 60 and l[p] < l[prev] and mpf[p] > mpf[prev]:
            divL[i] = True
        prev = p
    prev = None
    for i in np.where(_b(evH))[0]:
        p = i - 3
        if prev is not None and 5 <= p - prev <= 60 and h[p] > h[prev] and mpf[p] < mpf[prev]:
            divS[i] = True
        prev = p
    L = (reL | divL) & (c > o)
    S = (reS | divS) & (c < o)
    stopL = _roll_min(l, 5) - 0.2 * a; stopS = _roll_max(h, 5) + 0.2 * a
    return _pack(L, S, stopL, stopS, stopL, stopS, _b(xd), _b(xu))


# ---------------------------------------------------------------- N19
def n19(df, variant=0):
    """Fib 50% of the 34-bar range excluding the last 3 bars + research_chop_zone.
    AMBIG: variant 0 -> window t-36..t-3 (shift 3); variant 1 -> t-37..t-4 (shift 4)."""
    o, h, l, c, a = _base(df)
    k = 3 if variant == 0 else 4
    hh = _sh(_roll_max(h, 34), k); ll = _sh(_roll_min(l, 34), k)
    R = hh - ll; mid = ll + 0.5 * R
    cz = fg.research_chop_zone(df, 34, 14).to_numpy()
    g = np.isin(cz, ["GREEN", "BLUE"]); r = np.isin(cz, ["RED", "DARK_RED"])
    with np.errstate(invalid="ignore"):
        L = (l <= mid + 0.2 * a) & (c > mid) & (c > o) & g
        S = (h >= mid - 0.2 * a) & (c < mid) & (c < o) & r
    stopL = np.minimum(hh - 0.618 * R, _roll_min(l, 5)) - 0.1 * a
    stopS = np.maximum(ll + 0.618 * R, _roll_max(h, 5)) + 0.1 * a
    return _pack(L, S, stopL, stopS, None, None, None, None)


# ---------------------------------------------------------------- N20
def n20(df, variant=0):
    o, h, l, c, a = _base(df)
    close = df["close"]
    e9 = fg.ema(close, 9)
    reg = fg.research_chop_regime(df, 14).to_numpy()
    S = np.isin(reg, ["YELLOW", "RED"]) & lt(close, e9) & cross_below(close, e9)
    n = len(c)
    stopS = _roll_max(h, 8) + 0.25 * a
    exS = np.isin(reg, ["GREEN", "BLUE"]) & gt(close, e9) & (c > o)
    return _pack(np.zeros(n, bool), S, np.full(n, np.nan), stopS, None, None, np.zeros(n, bool), exS)


PORTS12 = {
    "S1_EMA_RSI_CHOP": s1, "S3_CMO_SANDWICH": s3, "S4_BB_BBP": s4, "N04_ST_KLINGER": n04,
    "N05_PSAR_POC": n05, "N06_MACD_ORB": n06, "N11_BREAKAWAY": n11, "N13_3OUTSIDE": n13,
    "N15_KC_AO": n15, "N16_BBRSI": n16, "N19_FIB_CHOP": n19, "N20_EMA9_CHOP": n20,
}
LIVE_POSITIVE = ("N19_FIB_CHOP", "N13_3OUTSIDE", "N11_BREAKAWAY")  # N08 (4th) was tested in stage 1
