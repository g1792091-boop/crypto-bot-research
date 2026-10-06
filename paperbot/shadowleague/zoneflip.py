"""The volume-zone flip detector of the reel "parkdando_" (support turns into resistance), vendored as pure functions
over numpy bar arrays. No data loader, no plotting, no import from research/ or from the rest of paperbot.

Source: the exact code that produced the 5-year result (lib_zoneflip.py, sha256 b4a5f6d0...f3, committed as
docs/zoneflip-reel/lib_zoneflip.py.txt on the owners' branch), rules fixed before the run in PREREG_ZONEFLIP.md
(sha256 202d638e...c8). ``vendor_manifest.json`` (next to this file) records the hashes of every original file and which
functions were copied; tests/test_shadowleague_parity.py proves the copies equal the original: the source text of each
copied function, and then the signals, stops and targets bit for bit on a fixture and on real bars.

Copied word for word: _edge, profiles, qualify, zone_runs, count_touches, resolve, choose and the numbers below.
Changed, and only in what is listed here:
  * setups: one optional argument ``b_min`` (default None = the original's behaviour exactly): only breaks at bar
    b >= b_min are looked at, so a live tick does not rebuild the profile of every old bar.
  * atr14: the original asks the locked fg_indicators.atr (pandas ewm); this is the same arithmetic in numpy, in the
    same order (tests compare it with pandas bit for bit). ``atr_next`` is the same step for one new bar.
  * signals_from_arrays / detect_new / ZoneFlipDetector: glue (the original's ``signals`` takes a DataFrame).

Rules (PREREG section 5), bar b = the bar the break happens on, r = the retest (= signal) bar, all values use closed
bars <= the bar they decide on:
  1. volume by price of bars b-200 .. b-1: 50 equal buckets over [lowest low, highest high], each bar's volume spread
     evenly over its own low-high range; a bucket counts when its volume is above the 80th percentile (the fullest
     bucket always counts); a zone = a run of adjacent counted buckets.
  2. broken down: close[b-1] >= zone low and close[b] < zone low - 0.25 ATR14[b] (mirror: broken up).
  3. touches (held): bars b-200 .. b-1 that came from the holding side, entered the zone and closed back out,
     counted greedily at least 3 bars apart; MAIN needs >= 3.
  4. retest: the first bar r in b+1 .. b+20 that trades back into the zone; it is a SHORT signal iff it closes back
     below the zone (mirror: LONG). stop = far edge +/- 0.25 ATR14[r]; target = the near edge of the nearest other zone
     of the same profile in the trade direction; skipped when there is no target, the stop is farther than 3 ATR14[r]
     or reward < 2 x risk. Long and short on one bar cancel each other; several on one side: the most recent break.
  5. entry at the next bar's open, exits: see sim.py (the study's engine conventions, 48 bars).
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as _SW

# ------------------------------------------------------------------ fixed parameters (PREREG section 4; copied)
VP_BARS = 200          # profile window: the 200 bars before the bar
N_BUCKETS = 50         # equal price buckets over the window's [min low, max high]
PCTL = 80.0            # bucket qualifies if volume > 80th percentile of the 50 bucket volumes (POC always)
BREAK_ATR = 0.25       # break = close beyond the far edge by at least 0.25 ATR14
MIN_TOUCHES = 3        # MAIN: at least 3 prior touches ...
TOUCH_GAP = 3          # ... at least 3 bars apart
RETEST_BARS = 20       # retest within 20 bars after the break bar
STOP_BUF_ATR = 0.25    # stop = far edge +/- 0.25 ATR14 of the signal bar
MAX_STOP_ATR = 3.0     # skip if stop distance > 3 ATR14
MIN_RR = 2.0           # skip if reward : risk < 2
MAX_HOLD = 48          # time exit after 48 bars (entry bar included), all timeframes
ATR_LEN = 14
VARIANTS = ("ZF_MAIN", "ZF_CTRL")     # MAIN: zone held >= 3 times (the shadow member); CTRL: no touch condition
DETECTOR_ID = "zoneflip_v1"
# bars of history the detector needs before its first signal: the profile (200) + 1 + room for the ATR to settle (the
# study dropped the first 300 bars of every series, sweep_lib.warmup_bars)
MIN_BARS = 300
LOOKBACK_BARS = VP_BARS + RETEST_BARS + 2


# ------------------------------------------------------------------ ATR14 (fg_indicators.atr, numpy, same arithmetic)
def true_range(h, l, c) -> np.ndarray:
    """max(high - low, |high - previous close|, |low - previous close|); the first bar has high - low only."""
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    tr = h - l
    if len(tr) > 1:
        pc = c[:-1]
        tr[1:] = np.fmax(np.fmax(tr[1:], np.abs(h[1:] - pc)), np.abs(l[1:] - pc))
    return tr


_ALPHA = 1.0 / ATR_LEN
_OLD_FACTOR = 1.0 - 1.0 / (1.0 + (1.0 - _ALPHA) / _ALPHA)      # pandas ewm: alpha = 1 / (1 + com), com = (1 - a) / a
_NEW_WT = 1.0 / (1.0 + (1.0 - _ALPHA) / _ALPHA)


def _step(w: float, x: float) -> float:
    """One Wilder step exactly as pandas ewm(adjust=False) takes it (a constant series stays constant)."""
    old_wt = 1.0 * _OLD_FACTOR
    if w != x:
        w = old_wt * w + _NEW_WT * x
        w /= (old_wt + _NEW_WT)
    return w


def atr14(h, l, c) -> np.ndarray:
    """fg_indicators.atr(df, 14): Wilder average of the true range, NaN for the first 13 bars. Needs finite input."""
    tr = true_range(h, l, c)
    n = len(tr)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    if not np.isfinite(tr).all():
        raise ValueError("atr14 needs finite highs, lows and closes")
    w = float(tr[0])
    for i in range(1, n):
        w = _step(w, float(tr[i]))
        if i + 1 >= ATR_LEN:
            out[i] = w
    return out


def atr_next(prev_atr: float, prev_close: float, h: float, l: float) -> float:
    """ATR14 of one new bar from the ATR14 of the bar before it (valid once that one exists, i.e. from bar 14 on)."""
    tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
    return _step(float(prev_atr), float(tr))


# ------------------------------------------------------------------ volume profile and zones
def _edge(lo_w, w, k):
    """Price of bucket boundary k (k = 0 .. N_BUCKETS). One expression everywhere so edges compare exactly."""
    return lo_w + k * w


def profiles(h, l, v, at, bars: int = VP_BARS, nb: int = N_BUCKETS, chunk: int = 512):
    """Volume by price for the window [t-bars, t-1] of each t in ``at`` (t >= bars).
    Returns vol (m, nb), lo_w (m,), w (m,), ok (m,). Each bar's volume is spread evenly over [low, high]
    (a bar with high == low puts all of it in the bucket containing that price; the top price goes to the top
    bucket). Uses bars strictly before t."""
    h, l = np.asarray(h, float), np.asarray(l, float)
    v = np.nan_to_num(np.asarray(v, float), nan=0.0)
    at = np.asarray(at, np.int64)
    m = len(at)
    vol = np.zeros((m, nb))
    lo_w, w = np.full(m, np.nan), np.full(m, np.nan)
    ok = np.zeros(m, bool)
    if m == 0:
        return vol, lo_w, w, ok
    assert at.min() >= bars, "profile needs `bars` earlier bars"
    Hw, Lw, Vw = _SW(h, bars), _SW(l, bars), _SW(v, bars)
    x = np.arange(nb + 1, dtype=float)
    for s0 in range(0, m, chunk):
        r = at[s0:s0 + chunk] - bars               # window start: bars r .. r+bars-1 = t-bars .. t-1
        Hr, Lr, Vr = Hw[r], Lw[r], Vw[r]
        lo, hi = Lr.min(axis=1), Hr.max(axis=1)
        ww = (hi - lo) / nb
        good = np.isfinite(ww) & (ww > 0)
        ws = np.where(good, ww, 1.0)
        a = (Lr - lo[:, None]) / ws[:, None]       # bar low / high in bucket units
        b = (Hr - lo[:, None]) / ws[:, None]
        span = b - a
        pos = span > 0
        sps = np.where(pos, span, 1.0)
        F = np.clip((x[None, None, :] - a[:, :, None]) / sps[:, :, None], 0.0, 1.0)
        pt = (x[None, None, :] > a[:, :, None]).astype(float)
        F = np.where(pos[:, :, None], F, pt)
        F[:, :, 0] = 0.0                           # everything lies inside [lo, hi]
        F[:, :, nb] = 1.0
        cum = np.einsum("tj,tjk->tk", Vr, F)
        vb = np.diff(cum, axis=1)
        tot = vb.sum(axis=1)
        good &= np.isfinite(tot) & (tot > 0)
        sl = slice(s0, s0 + len(r))
        vol[sl], lo_w[sl], w[sl], ok[sl] = vb, lo, ww, good
    return vol, lo_w, w, ok


def qualify(vol: np.ndarray) -> np.ndarray:
    """(m, nb) bool: bucket volume strictly above the 80th percentile of its row (numpy linear), POC always."""
    thr = np.percentile(vol, PCTL, axis=1)
    q = vol > thr[:, None]
    q[np.arange(len(vol)), vol.argmax(axis=1)] = True      # POC: lowest bucket on ties
    return q


def zone_runs(qrow: np.ndarray) -> list[tuple[int, int]]:
    """Maximal runs of qualifying buckets: [(first bucket, last bucket), ...] bottom to top."""
    out, k, nb = [], 0, len(qrow)
    while k < nb:
        if qrow[k]:
            j = k
            while j + 1 < nb and qrow[j + 1]:
                j += 1
            out.append((k, j))
            k = j + 1
        else:
            k += 1
    return out


def count_touches(o_side: int, zlo: float, zhi: float, h, l, c, b: int, bars: int = VP_BARS) -> list[int]:
    """Touches in bars b-bars .. b-1, greedy, at least TOUCH_GAP bars apart.
    o_side = -1 (zone broken DOWN, it was support): close[j-1] > zhi, low[j] <= zhi, close[j] > zhi.
    o_side = +1 (zone broken UP, it was resistance): close[j-1] < zlo, high[j] >= zlo, close[j] < zlo."""
    j0 = max(b - bars, 1)
    if j0 >= b:
        return []
    cp, cj = c[j0 - 1:b - 1], c[j0:b]
    if o_side < 0:
        hit = (cp > zhi) & (l[j0:b] <= zhi) & (cj > zhi)
    else:
        hit = (cp < zlo) & (h[j0:b] >= zlo) & (cj < zlo)
    out, last = [], -10**9
    for j in (np.flatnonzero(hit) + j0).tolist():
        if j - last >= TOUCH_GAP:
            out.append(j)
            last = j
    return out


def setups(o, h, l, c, v, atr, b_min=None) -> list[dict]:
    """Every zone break (both directions). Bar b needs b >= VP_BARS + 1 and a finite ATR14[b] > 0. Only bars whose
    close moved more than BREAK_ATR x ATR14 from the previous close can break a zone (necessary condition), so the
    profile is computed only there. Each record: b, side (trade side: -1 short after a down-break, +1 long after an
    up-break), zone edges, all zones of that profile, touch bars."""
    n = len(c)
    out: list[dict] = []
    if n <= VP_BARS + 1:
        return out
    with np.errstate(invalid="ignore"):
        dc = np.abs(c[1:] - c[:-1])
        cand = np.flatnonzero((dc > BREAK_ATR * atr[1:]) & np.isfinite(atr[1:]) & (atr[1:] > 0)) + 1
    cand = cand[cand >= VP_BARS + 1]
    if b_min is not None:                          # vendored: live ticks look at recent breaks only
        cand = cand[cand >= int(b_min)]
    if not len(cand):
        return out
    step = 4096
    karr = np.arange(N_BUCKETS)
    for s0 in range(0, len(cand), step):
        at = cand[s0:s0 + step]
        vol, lo_w, w, ok = profiles(h, l, v, at)
        q = qualify(vol)
        starts = q & ~np.c_[np.zeros((len(q), 1), bool), q[:, :-1]]
        ends = q & ~np.c_[q[:, 1:], np.zeros((len(q), 1), bool)]
        P_lo = _edge(lo_w[:, None], w[:, None], karr[None, :])
        P_hi = _edge(lo_w[:, None], w[:, None], karr[None, :] + 1)
        cb, cp, ab = c[at][:, None], c[at - 1][:, None], atr[at][:, None]
        with np.errstate(invalid="ignore"):
            dn = starts & (P_lo > cb + BREAK_ATR * ab) & (P_lo <= cp)
            up = ends & (P_hi < cb - BREAK_ATR * ab) & (P_hi >= cp)
        rows = np.flatnonzero(ok & (dn.any(axis=1) | up.any(axis=1)))
        for i in rows.tolist():
            b = int(at[i])
            runs = zone_runs(q[i])
            zl = np.array([_edge(lo_w[i], w[i], k0) for k0, _k1 in runs])
            zh = np.array([_edge(lo_w[i], w[i], k1 + 1) for _k0, k1 in runs])
            for zi, (k0, k1) in enumerate(runs):
                for side, hit in ((-1, dn[i, k0]), (1, up[i, k1])):
                    if not hit:
                        continue
                    t = count_touches(side, zl[zi], zh[zi], h, l, c, b)
                    out.append(dict(b=b, side=side, zi=zi, zlo=float(zl[zi]), zhi=float(zh[zi]), zones_lo=zl,
                                    zones_hi=zh, touches=t, n_touch=len(t)))
    return out


def resolve(setups_: list[dict], h, l, c, atr) -> list[dict]:
    """Retest -> signal records (before the MAIN / CTRL split and the same-bar rules). A signal has r (signal bar),
    side, stop, target and the reference risk / reward at close[r]. Records failing a filter are kept with ``skip``
    set (no_target / stop_far / rr) for the counts; a setup without a qualifying retest gives no record."""
    n = len(c)
    out = []
    for s in setups_:
        b, side, zlo, zhi = s["b"], s["side"], s["zlo"], s["zhi"]
        r1 = min(n - 1, b + RETEST_BARS)
        if r1 <= b:
            continue
        if side < 0:
            touch = h[b + 1:r1 + 1] >= zlo
        else:
            touch = l[b + 1:r1 + 1] <= zhi
        if not touch.any():
            continue
        r = b + 1 + int(touch.argmax())
        if not ((c[r] < zlo) if side < 0 else (c[r] > zhi)):
            continue                                # closed back in / through the zone: the break failed
        a = float(atr[r])
        if not (np.isfinite(a) and a > 0):
            continue
        ref = float(c[r])
        zl, zh = s["zones_lo"], s["zones_hi"]
        others = np.arange(len(zl)) != s["zi"]
        if side < 0:
            stop = zhi + STOP_BUF_ATR * a
            cand = zh[others & (zh < ref)]
            tgt = float(cand.max()) if len(cand) else np.nan
            ti = int(np.flatnonzero(others & (zh == tgt))[0]) if len(cand) else -1
        else:
            stop = zlo - STOP_BUF_ATR * a
            cand = zl[others & (zl > ref)]
            tgt = float(cand.min()) if len(cand) else np.nan
            ti = int(np.flatnonzero(others & (zl == tgt))[0]) if len(cand) else -1
        risk = side * (ref - stop)
        reward = side * (tgt - ref) if np.isfinite(tgt) else np.nan
        if not np.isfinite(tgt):
            skip = "no_target"
        elif risk > MAX_STOP_ATR * a:
            skip = "stop_far"
        elif not reward >= MIN_RR * risk:
            skip = "rr"
        else:
            skip = ""
        out.append(dict(r=r, b=b, side=side, zlo=zlo, zhi=zhi, n_touch=s["n_touch"], touches=s["touches"],
                        stop=float(stop), target=tgt, tz_lo=float(zl[ti]) if ti >= 0 else np.nan,
                        tz_hi=float(zh[ti]) if ti >= 0 else np.nan, atr=a, ref=ref, risk=float(risk),
                        reward=float(reward) if np.isfinite(reward) else np.nan, skip=skip))
    return out


def choose(sigs: list[dict], variant: str) -> dict[int, dict]:
    """Per signal bar: the variant's valid signals; long and short on the same bar -> none; several on one side ->
    the most recent break, then the smallest risk, then the lowest zone."""
    by: dict[int, list] = {}
    for s in sigs:
        if s["skip"] or (variant == "ZF_MAIN" and s["n_touch"] < MIN_TOUCHES):
            continue
        by.setdefault(s["r"], []).append(s)
    out = {}
    for r, ss in by.items():
        if len({s["side"] for s in ss}) > 1:
            continue
        out[r] = sorted(ss, key=lambda s: (-s["b"], s["risk"], s["zlo"]))[0]
    return out


# ------------------------------------------------------------------ glue
def signals_from_arrays(o, h, l, c, v, atr=None) -> dict:
    """The original's ``signals(df)`` for numpy arrays: {'atr', 'setups', 'sigs', 'chosen': {variant: {r: sig}}}."""
    o, h, l, c, v = (np.asarray(x, float) for x in (o, h, l, c, v))
    if atr is None:
        atr = atr14(h, l, c)
    st = setups(o, h, l, c, v, atr)
    sg = resolve(st, h, l, c, atr)
    return {"atr": atr, "setups": st, "sigs": sg, "chosen": {var: choose(sg, var) for var in VARIANTS}}


def detect_new(o, h, l, c, v, atr, first_r: int, variant: str = "ZF_MAIN") -> tuple[list[dict], dict[int, dict]]:
    """Signals whose signal bar r >= ``first_r``, from arrays that end at the latest closed bar n-1.
    Returns (every retest record with its skip reason, the chosen signal per bar for ``variant``).
    Nothing after bar r is read to decide the signal at r (resolve looks for the first touch in b+1..b+20 and stops at
    the first one), so what is found for r does not depend on how many later bars the arrays hold."""
    o, h, l, c, v = (np.asarray(x, float) for x in (o, h, l, c, v))
    first_r = max(int(first_r), 0)
    st = setups(o, h, l, c, v, atr, b_min=max(first_r - RETEST_BARS, 0))
    sg = [s for s in resolve(st, h, l, c, atr) if s["r"] >= first_r]
    return sg, choose(sg, variant)


class ZoneFlipDetector:
    """The shadow league's view of this detector (see league.Detector)."""
    id = DETECTOR_ID
    min_bars = MIN_BARS
    lookback = LOOKBACK_BARS
    variant = "ZF_MAIN"

    def params(self) -> dict:
        return {"vp_bars": VP_BARS, "buckets": N_BUCKETS, "percentile": PCTL, "break_atr": BREAK_ATR,
                "min_touches": MIN_TOUCHES, "touch_gap": TOUCH_GAP, "retest_bars": RETEST_BARS,
                "stop_buf_atr": STOP_BUF_ATR, "max_stop_atr": MAX_STOP_ATR, "min_rr": MIN_RR, "atr_len": ATR_LEN,
                "min_bars": MIN_BARS, "variant": self.variant}

    def detect(self, o, h, l, c, v, atr, first_r: int):
        return detect_new(o, h, l, c, v, atr, first_r, self.variant)
