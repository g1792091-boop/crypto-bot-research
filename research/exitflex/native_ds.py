"""The eight DeepSeek strategies' own exits (family F11 of PREREG_EXITFLEX.md, Appendix A.9 - A.16).

    native(df, tf, name, combo, ctx, coin) -> NativeDS(lx, sx, inv_l, inv_s, tgt_l, tgt_s)

``df`` is the pick's chart frame (``run.frame``), ``ctx`` is None for BTC and {"BTCUSD": BTC's chart frame of the same
timeframe} for the other coins (what ``run.signals`` passes to ``ds_defs.signals``), ``coin`` is the symbol without its
last letter ("BTCUSD", "DOGEUSD", ...), ``combo`` is the pick's combo. The result holds, for every chart bar of ``df``:
    lx, sx      bool arrays. One state component per side (rule C1-C4): a long closes as RULE at a check when lx is true,
                a short when sx is true. False everywhere for the five level-only strategies (F10_OTE, F11_TSOUP,
                F1_PVT_DIV, F5_BOX, F9_FVG).
    inv_l,inv_s float arrays indexed by the signal bar, NaN elsewhere: the per-signal invalidation level. A long exits
                when a chart close is below inv_l[i0], a short when a close is above inv_s[i0] (level test, rule C3).
                Fixed at the signal bar, never moves. NaN = none.
    tgt_l,tgt_s float arrays indexed by the signal bar, NaN elsewhere and where the strategy has no target: the
                per-signal native target (F11.b only). The raw level is given; "used only when it lies beyond the fill"
                (rule C6, the kernel's TP_STRUCT rule) is the kernel's decision, because the fill is not known here.
Nothing here depends on a bar after the bar it is indexed by (tests: causality).

The function calls ``ds_defs.signals`` exactly as ``run.signals`` does, with a cache dict it owns, and then reads the blocks
the entry built from that cache through ``D._Series`` and ``D._resolve`` (``ds_defs`` is the module object
``run.ds_module()`` returns, the one ``run.signals`` uses). It adds no number: every number is a combo value or one that
``ds_defs`` fixes (the OTE zone life 50; the 0.5 of the TSOUP middle is Appendix A's).

DECISIONS (readings chosen where Appendix A is ambiguous; PREREG_EXITFLEX.md is not edited)
1. Return type. A.0 says "returns lx, sx, inv_l, inv_s ... tgt_l, tgt_s" without a container. ``NativeDS`` is a NamedTuple in
   exactly that order, so the 6-tuple unpacking and the dict reading of ``runner_x.f11_provider_from_modules`` both work
   (it also answers ``r["lx"]``, ``r.get("lx")``, ``r.keys()``). Arrays are fresh (never views of the cache).
2. "asserts the result equals run.signals". The signature has no data folder or symbol, so ``native`` cannot call
   ``run.signals``. It makes the identical ``ds_module().signals(df, tf, name, ctx=ctx, coin=coin, cache=cache, **combo)``
   call (``run.signals`` does nothing else to the arrays but ``np.asarray(.., bool)``) and, when the caller passes
   ``expect=(long, short)`` (the arrays ``run.signals`` returned, which the runner's provider receives as ``sl, ss``),
   asserts they are equal to the bar. The tests do this on synthetic bars and on real select-period bars (T6).
3. Cache blocks. The entry builds every block this module reads (legs, zone tables, FVG zones, pivots, PVT, RF, HA, the
   rolling max / min, the structure) in the same cache, so they are cache hits. ``X.table`` is called with a ``build`` that
   raises, so a miss is a bug and stops the run; no copy of ``_f10_ote``'s or ``_f9_fvg``'s ``build`` and no second
   formula for PVT is kept (A.9 and A.12 allow a fallback copy; none is needed and a copy could drift).
4. Several zones firing on one bar and side (A.9, A.16): the rows are sorted by (signal bar, t) for F10_OTE and
   (signal bar, b) for F9_FVG and the last row of each bar is taken, so the largest t / b wins. Writing the rows into an
   array with repeated indices is not used because NumPy does not define which duplicate wins.
5. Recovery check (A.9, A.12, A.16 "the difference is only bars where ds_defs dropped a both-side signal"). Stronger than a
   subset test: the recovered raw (long, short) rows must give exactly the final signals, long == raw_long & ~raw_short and
   short == raw_short & ~raw_long, the rule ``ds_defs.signals`` ends with. A missing row for a final signal is an
   AssertionError, never a NaN level.
6. F1_PVT_DIV: the pairs are recomputed with ``_div``'s own three conditions on the cached pivots and PVT; the signal bar
   b + swing_k must be unique per side (A.12 "each b is the second pivot of at most one pair"), asserted.
7. F11_TSOUP: the target is (Hw[s] + Lw[s]) / 2 on both sides, the invalidation l[s] (long) or h[s] (short). Lw and Hw
   must be finite on every signal bar (A.10), asserted.
8. F12_MSS_DISP: lx = bos_dn | mss_dn and sx = bos_up | mss_up from ``X.S(swing_k)``, the target is prev_hi[s] (long) or
   prev_lo[s] (short); a NaN prev_hi / prev_lo stays NaN (no target, rule C7). No invalidation level.
9. F7_RF_ONLY / F7_RF_TRIPLE: no level and no target (all NaN). lx / sx are comparisons, so a NaN input (the higher-timeframe
   Heikin-Ashi in the warm-up) is False: it neither fires nor needs an arm (C7). On a signal bar of the strategy's own side
   all three inputs of the entry hold, so the own-side component is False there (asserted for every strategy, A.0).
10. A level or target is never written on a bar that is not a final signal bar of its own side (asserted), so a bar that
    ``ds_defs`` dropped as both-sided carries nothing. For the five level strategies every final signal bar must carry both
    its invalidation and its target (asserted); lx and sx are all False for them.
11. ``name`` outside the eight raises ValueError (the core strategies' exits are in native.py).
12. The OTE zone life 50 is a named constant (``OTE_LIFE``): A.9 writes it as a literal and ``ds_defs._f10_ote`` hard-codes it;
    if the two ever differ the recovery check of DECISIONS 5 fails.
13. Tests: ``research/exitflex/test_native_ds.py`` (a file of its own so that the core strategies' test file is not disturbed).
"""

from __future__ import annotations

import os
import sys
from typing import NamedTuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FG = os.path.join(ROOT, "research", "fullgrid")

NAMES = ("F10_OTE", "F11_TSOUP", "F12_MSS_DISP", "F1_PVT_DIV", "F5_BOX", "F7_RF_ONLY", "F7_RF_TRIPLE", "F9_FVG")
# the five strategies whose own exit is two levels (an invalidation and a target): both must exist at every final signal bar
LEVEL_STRATEGIES = ("F10_OTE", "F11_TSOUP", "F1_PVT_DIV", "F5_BOX", "F9_FVG")
OTE_LIFE = 50           # lib_c's zone life of F10_OTE (ds_defs._f10_ote passes 50 to X.table and to fire); A.9 repeats it
_NAN = float("nan")
_RUN = {}


class NativeDS(NamedTuple):
    """The six arrays of ``native`` (order of A.0). Readable as a tuple, or by name like a dict."""
    lx: np.ndarray
    sx: np.ndarray
    inv_l: np.ndarray
    inv_s: np.ndarray
    tgt_l: np.ndarray
    tgt_s: np.ndarray

    def __getitem__(self, k):
        if isinstance(k, str):
            if k not in self._fields:
                raise KeyError(k)
            return getattr(self, k)
        return tuple.__getitem__(self, k)

    def get(self, k, default=None):
        return getattr(self, k) if k in self._fields else default

    def keys(self):
        return self._fields


def fg():
    """research/fullgrid/run.py as module ``run`` (the name sizing.py imports it under)."""
    if "run" not in _RUN:
        if FG not in sys.path:
            sys.path.insert(0, FG)
        import run as R  # noqa: E402
        if not os.path.abspath(R.__file__).startswith(FG):
            raise RuntimeError("module 'run' is not research/fullgrid/run.py")
        _RUN["run"] = R
    return _RUN["run"]


def ds_module():
    """ds_defs as ``run.signals`` uses it (one module object per process)."""
    return fg().ds_module()


def _no_build(*_a, **_k):
    raise AssertionError("native_ds: a block the entry must have built is not in the cache")


def _hit(X, key):
    """A cache entry the entry built (DECISIONS 3)."""
    try:
        return X.cache[key]
    except KeyError:
        raise AssertionError(f"native_ds: cache block {key!r} was not built by the entry") from None


def _last_per_bar(s: np.ndarray, rank: np.ndarray, z: np.ndarray) -> tuple:
    """Rows (bar s, rank, zone index z) -> one row per bar: the one with the largest rank (DECISIONS 4)."""
    if not len(s):
        return s, z
    o = np.lexsort((rank, s))
    s, z = s[o], z[o]
    last = np.r_[s[1:] != s[:-1], True]
    return s[last], z[last]


def _same_signals(name: str, raw_l: np.ndarray, raw_s: np.ndarray, lg: np.ndarray, sh: np.ndarray) -> None:
    """DECISIONS 5: the recovered rows reproduce ds_defs' final signals, dropped both-side bars aside."""
    assert np.array_equal(lg, raw_l & ~raw_s), f"{name}: recovered long rows do not give the entry's long signals"
    assert np.array_equal(sh, raw_s & ~raw_l), f"{name}: recovered short rows do not give the entry's short signals"


class _Out:
    """The six arrays being filled."""

    def __init__(self, n: int):
        self.lx, self.sx = np.zeros(n, bool), np.zeros(n, bool)
        self.inv_l, self.inv_s, self.tgt_l, self.tgt_s = (np.full(n, _NAN) for _ in range(4))


# ------------------------------------------------------------------ the eight definitions
def _f10_ote(D, X, p, lg, sh, out: _Out) -> None:
    """A.9. Invalidation = the swing the impulse leg started from (long: L, short: H); target = the leg's other end."""
    key = (p["swing_k"], p["leg_atr"], p["leg_max_bars"])
    t, H, Lw, _d = X.legs(*key)                          # the arrays the entry used: legs sorted as built, zi indexes them
    T = X.table(("ote",) + key, _no_build, OTE_LIFE)     # the table the entry used
    m = T["ft"] < OTE_LIFE
    s, zi, up = T["s"][m], T["zi"][m], T["up"][m]
    n = X.n
    raw_l, raw_s = np.zeros(n, bool), np.zeros(n, bool)
    sl, zl = _last_per_bar(s[up], t[zi[up]], zi[up])
    ss, zs = _last_per_bar(s[~up], t[zi[~up]], zi[~up])
    raw_l[sl], raw_s[ss] = True, True
    _same_signals("F10_OTE", raw_l, raw_s, lg, sh)
    keep_l, keep_s = lg[sl], sh[ss]
    sl, zl, ss, zs = sl[keep_l], zl[keep_l], ss[keep_s], zs[keep_s]
    out.inv_l[sl], out.tgt_l[sl] = Lw[zl], H[zl]
    out.inv_s[ss], out.tgt_s[ss] = H[zs], Lw[zs]


def _f11_tsoup(D, X, p, lg, sh, out: _Out) -> None:
    """A.10. Invalidation = the false breakout's own extreme (long: l[s], short: h[s]); target = the middle of the range."""
    w = p["tsoup_len"]
    Lw, Hw = X.lmin1(w), X.hmax1(w)                       # the cached arrays the entry used
    li, si = np.flatnonzero(lg), np.flatnonzero(sh)
    for i in (li, si):
        assert np.isfinite(Lw[i]).all() and np.isfinite(Hw[i]).all(), "F11_TSOUP: a signal bar without a finite range"
    mid = (Hw + Lw) / 2
    out.inv_l[li], out.tgt_l[li] = X.l[li], mid[li]
    out.inv_s[si], out.tgt_s[si] = X.h[si], mid[si]


def _f12_mss_disp(D, X, p, lg, sh, out: _Out) -> None:
    """A.11. The strategy's own structure turning back (per-bar flags); target = the swing before the one the MSS broke."""
    S = X.S(p["swing_k"])
    out.lx[:] = S["bos_dn"] | S["mss_dn"]
    out.sx[:] = S["bos_up"] | S["mss_up"]
    li, si = np.flatnonzero(lg), np.flatnonzero(sh)
    out.tgt_l[li] = S["prev_hi"][li]
    out.tgt_s[si] = S["prev_lo"][si]


def _f1_pvt_div(D, X, p, lg, sh, out: _Out) -> None:
    """A.12. Invalidation = the second (divergence) pivot's price; target = the extreme between the two pivots."""
    k, mx = p["swing_k"], p["div_max_bars"]
    P, Q = _hit(X, ("pividx", k))                         # P: swing-high pivots, Q: swing-low pivots (bar of the pivot itself)
    ind = _hit(X, ("pvt",))
    h, l, n = X.h, X.l, X.n
    raw_l, raw_s = np.zeros(n, bool), np.zeros(n, bool)
    with np.errstate(invalid="ignore"):
        if len(Q) > 1:
            a, b = Q[:-1], Q[1:]
            ok = ((b - a) <= mx) & (l[b] < l[a]) & (ind[b] > ind[a])
            a, b = a[ok], b[ok]
            assert len(np.unique(b)) == len(b)
            raw_l[b + k] = True
            for ai, bi in zip(a.tolist(), b.tolist()):
                if lg[bi + k]:
                    out.inv_l[bi + k], out.tgt_l[bi + k] = l[bi], h[ai:bi + 1].max()
        if len(P) > 1:
            a, b = P[:-1], P[1:]
            ok = ((b - a) <= mx) & (h[b] > h[a]) & (ind[b] < ind[a])
            a, b = a[ok], b[ok]
            assert len(np.unique(b)) == len(b)
            raw_s[b + k] = True
            for ai, bi in zip(a.tolist(), b.tolist()):
                if sh[bi + k]:
                    out.inv_s[bi + k], out.tgt_s[bi + k] = h[bi], l[ai:bi + 1].min()
    _same_signals("F1_PVT_DIV", raw_l, raw_s, lg, sh)


def _f5_box(D, X, p, lg, sh, out: _Out) -> None:
    """A.13. Invalidation = the box edge on the entry side (fixed at the signal bar); target = the far edge."""
    bl = p["box_len"]
    hi, lo = X.hmax1(bl), X.lmin1(bl)                     # the cached arrays the entry used
    li, si = np.flatnonzero(lg), np.flatnonzero(sh)
    for i in (li, si):
        assert np.isfinite(hi[i]).all() and np.isfinite(lo[i]).all(), "F5_BOX: a signal bar without a finite box"
    out.inv_l[li], out.tgt_l[li] = lo[li], hi[li]
    out.inv_s[si], out.tgt_s[si] = hi[si], lo[si]


def _f7_rf_only(D, X, p, lg, sh, out: _Out) -> None:
    """A.14. The range-filter direction is the other way (= the strategy's own opposite signal). No level, no target."""
    rf = D._rf_dir(X, p)
    out.lx[:] = rf == -1
    out.sx[:] = rf == 1


def _f7_rf_triple(D, X, p, lg, sh, out: _Out) -> None:
    """A.15. Any of the three (range filter, chart Heikin-Ashi, higher-timeframe Heikin-Ashi) turned the other way."""
    rf = D._rf_dir(X, p)
    ha, hha = _hit(X, ("ha",)), _hit(X, ("hha",))
    out.lx[:] = (rf == -1) | (ha == 0) | (hha == 0)
    out.sx[:] = (rf == 1) | (ha == 1) | (hha == 1)


def _f9_fvg(D, X, p, lg, sh, out: _Out) -> None:
    """A.16. Invalidation = the far side of the gap; target = the swing extreme the gap's move made before the touch."""
    x, life = p["fvg_min_atr"], p["zone_life"]
    b, lo, hi, _d, _kill = X.fvgz(x)                      # the zone set the entry used: zi indexes it
    T = X.table(("fvgtab", x), _no_build, life)           # the table the entry used (built with conf 'mid')
    assert T["need"] is None
    m = T["ft"] < life
    s, zi, up = T["s"][m], T["zi"][m], T["up"][m]
    n = X.n
    raw_l, raw_s = np.zeros(n, bool), np.zeros(n, bool)
    sl, zl = _last_per_bar(s[up], b[zi[up]], zi[up])
    ss, zs = _last_per_bar(s[~up], b[zi[~up]], zi[~up])
    raw_l[sl], raw_s[ss] = True, True
    _same_signals("F9_FVG", raw_l, raw_s, lg, sh)
    keep_l, keep_s = lg[sl], sh[ss]
    sl, zl, ss, zs = sl[keep_l], zl[keep_l], ss[keep_s], zs[keep_s]
    out.inv_l[sl] = lo[zl]
    out.inv_s[ss] = hi[zs]
    for si, zi_ in zip(sl.tolist(), zl.tolist()):
        out.tgt_l[si] = X.h[b[zi_] - 1:si].max()          # bars b - 1 .. s - 1
    for si, zi_ in zip(ss.tolist(), zs.tolist()):
        out.tgt_s[si] = X.l[b[zi_] - 1:si].min()


_BUILD = {"F10_OTE": _f10_ote, "F11_TSOUP": _f11_tsoup, "F12_MSS_DISP": _f12_mss_disp, "F1_PVT_DIV": _f1_pvt_div,
          "F5_BOX": _f5_box, "F7_RF_ONLY": _f7_rf_only, "F7_RF_TRIPLE": _f7_rf_triple, "F9_FVG": _f9_fvg}
assert tuple(sorted(_BUILD)) == tuple(sorted(NAMES))


def native(df, tf: str, name: str, combo: dict, ctx, coin: str, expect=None) -> NativeDS:
    """The own-exit arrays of DeepSeek strategy ``name`` on ``df`` (see the module docstring).

    ``expect`` = (long, short) as returned by ``run.signals`` on the same frame: asserted equal to this function's own
    ``ds_defs.signals`` call (DECISIONS 2)."""
    if name not in _BUILD:
        raise ValueError(f"native_ds: {name!r} is not one of the eight DeepSeek strategies {NAMES}")
    D = ds_module()
    cache: dict = {}
    lg, sh = D.signals(df, tf, name, ctx=ctx, coin=coin, cache=cache, **combo)
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    if expect is not None:
        el, es = np.asarray(expect[0], bool), np.asarray(expect[1], bool)
        assert np.array_equal(lg, el) and np.array_equal(sh, es), f"{name}: signals differ from run.signals"
    X = D._Series(df, tf, ctx, coin, cache)
    p = D._resolve(name, combo)
    out = _Out(len(df))
    _BUILD[name](D, X, p, lg, sh, out)
    # what A.0 asserts: the own-side component is false at every signal bar of its side (C3 arms it at once), and a level
    # or target exists only on a final signal bar of its own side
    assert not out.lx[lg].any() and not out.sx[sh].any(), f"{name}: an own-side component is true at its signal bar"
    for arr, sig in ((out.inv_l, lg), (out.tgt_l, lg), (out.inv_s, sh), (out.tgt_s, sh)):
        assert not (np.isfinite(arr) & ~sig).any(), f"{name}: a level or target on a bar that is not its signal bar"
    if name in LEVEL_STRATEGIES:                          # A.9 - A.16: every final signal bar receives its levels
        for arr, sig in ((out.inv_l, lg), (out.tgt_l, lg), (out.inv_s, sh), (out.tgt_s, sh)):
            assert np.isfinite(arr[sig]).all(), f"{name}: a final signal bar without its level or target"
        assert not out.lx.any() and not out.sx.any()
    return NativeDS(out.lx, out.sx, out.inv_l, out.inv_s, out.tgt_l, out.tgt_s)
