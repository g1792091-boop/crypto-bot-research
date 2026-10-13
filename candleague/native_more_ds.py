"""The owner-exit league's own-structure arrays for five DeepSeek strategies that research/exitflex/native_ds.py does not cover
(owners' decision 2026-10-13): F15_LON_BRK, F15_ORB, F3_BOS, F4_FAN, F6_VWAP_FAIL.

    native_arrays(df, tf, name, combo, ctx, coin, expect=None) -> the same dict as candleague.native_more.native_arrays:
        "comp_long" / "comp_short": [("state", float64 array)], one tri-state value per chart bar (1.0 true, 0.0 false, NaN unknown:
        neither fires nor arms, rule C7); "lvl_*" / "tgt_*": all NaN (no own stop or target level for these five);
        "names_long" / "names_short".

Not part of the pre-registered study (research/exitflex is untouched); ``candleague.rulex.native_hash`` includes this file, so a
change here restarts the league. Rules C1-C8 of research/exitflex/native.py apply unchanged.

Like native_ds.py, the entry is called first (``ds_defs.signals`` with a cache this function owns) and the blocks the entry built are
read back through ``ds_defs._Series`` / ``ds_defs._resolve`` with the pick's own combo. A long's structure is BROKEN (short: mirrored) when

    F15_LON_BRK   the close is back inside the London range (<= its top), from 05:00 ET of the day whose range it is, until that ET day ends
    F15_ORB       the close is back inside the day's opening range (<= its top), from the bar after the opening bars until the UTC day ends
    F3_BOS        the close is below the last confirmed swing low of the entry's own structure (``ds_defs.structure``, swing_k of the pick)
    F4_FAN        the shortest EMA of the ribbon is below the middle EMA
    F6_VWAP_FAIL  the close is below the day's VWAP (UTC day; the first bar of a day has none: unknown, the entry only works inside one day)

Every one is a 'state' component. The range / swing / VWAP of bar i is known at bar i's close (no bar after i enters). Because a
component array is per bar and not per position, "the range the signal used" is the range of the day the bar belongs to; a position
held into the next day sees the new day's range from its first usable bar on (documented, one line in the report of the change).
"""

from __future__ import annotations

import numpy as np

from . import native_more as NM

NAMES = ("F15_LON_BRK", "F15_ORB", "F3_BOS", "F4_FAN", "F6_VWAP_FAIL")
STATE = NM.STATE
SPEC = {
    "F15_LON_BRK": {"long": ((STATE, "close back inside the London range"),), "short": ((STATE, "close back inside the London range"),)},
    "F15_ORB": {"long": ((STATE, "close back inside the opening range"),), "short": ((STATE, "close back inside the opening range"),)},
    "F3_BOS": {"long": ((STATE, "close below the last swing low"),), "short": ((STATE, "close above the last swing high"),)},
    "F4_FAN": {"long": ((STATE, "shortest EMA < middle EMA"),), "short": ((STATE, "shortest EMA > middle EMA"),)},
    "F6_VWAP_FAIL": {"long": ((STATE, "close < VWAP"),), "short": ((STATE, "close > VWAP"),)},
}


def ds_module():
    """ds_defs as ``run.signals`` uses it (one module object per process)."""
    return NM.fg().ds_module()


def _f15_lon(D, X, p):
    """The London range 02:00-05:00 ET of each ET day (the entry's own loop: whole range present), known from 05:00 ET."""
    n, h, l, c, tfm = X.n, X.h, X.l, X.c, X.tfm
    _day, mins, blocks, _asia = X.et()
    top, bot = np.full(n, np.nan), np.full(n, np.nan)
    for _d, a, b in blocks:
        m = mins[a:b]
        lr = (m >= 120) & (m < 300)
        if lr.sum() == 180 // tfm:
            after = m >= 300
            top[a:b] = np.where(after, h[a:b][lr].max(), np.nan)
            bot[a:b] = np.where(after, l[a:b][lr].min(), np.nan)
    v = NM.fin(c, top, bot)
    with np.errstate(invalid="ignore"):
        return NM.tri(c <= top, v), NM.tri(c >= bot, v), top, bot


def _f15_orb(D, X, p):
    nb = p["orb_bars"]
    n, c = X.n, X.c
    _mins, st, _en, blk = X.utcday()
    ok, I = D._lead_ok(X, nb, True)
    oh, ol = np.where(ok, X.h[I].max(1), np.nan), np.where(ok, X.l[I].min(1), np.nan)
    after = ok[blk] & ((np.arange(n) - st[blk]) >= nb)
    top, bot = np.where(after, oh[blk], np.nan), np.where(after, ol[blk], np.nan)
    v = NM.fin(c, top, bot)
    with np.errstate(invalid="ignore"):
        return NM.tri(c <= top, v), NM.tri(c >= bot, v), top, bot


def _f3_bos(D, X, p):
    S = X.S(p["swing_k"])
    lo, hi, c = NM.f(S["lo"]), NM.f(S["hi"]), X.c
    with np.errstate(invalid="ignore"):
        return NM.tri(c < lo, NM.fin(c, lo)), NM.tri(c > hi, NM.fin(c, hi)), None, None


def _f4_fan(D, X, p):
    em = [NM.f(X.ema(k)) for k in p["fan_lens"]]
    a, m = em[0], em[len(em) // 2]
    v = NM.fin(a, m)
    with np.errstate(invalid="ignore"):
        return NM.tri(a < m, v), NM.tri(a > m, v), None, None


def _f6_vwap_fail(D, X, p):
    vw, vday, _up, _dn = D._vwap(X)
    same = np.r_[False, vday[1:] == vday[:-1]]
    c = X.c
    v = NM.fin(c, vw) & same
    with np.errstate(invalid="ignore"):
        return NM.tri(c < vw, v), NM.tri(c > vw, v), None, None


_BUILD = {"F15_LON_BRK": _f15_lon, "F15_ORB": _f15_orb, "F3_BOS": _f3_bos, "F4_FAN": _f4_fan, "F6_VWAP_FAIL": _f6_vwap_fail}


def native_arrays(df, tf: str, name: str, combo: dict, ctx, coin: str, expect=None) -> dict:
    """The own-structure arrays of DeepSeek strategy ``name`` on ``df`` (see the module docstring). ``expect`` = (long, short) as
    returned by ``run.signals`` on the same frame: asserted equal to this function's own ``ds_defs.signals`` call."""
    if name not in _BUILD:
        raise ValueError(f"native_more_ds: {name!r} is not one of {NAMES}")
    n = len(df)
    if n == 0:
        z = [(STATE, np.zeros(0))]
        return NM.out_dict(SPEC[name], 0, z, list(z))
    D = ds_module()
    combo = dict(combo or {})
    cache: dict = {}
    lg, sh = D.signals(df, tf, name, ctx=ctx, coin=coin, cache=cache, **combo)
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    if expect is not None:
        el, es = np.asarray(expect[0], bool), np.asarray(expect[1], bool)
        if not (el.shape == lg.shape and es.shape == sh.shape and np.array_equal(lg, el) and np.array_equal(sh, es)):
            raise AssertionError(f"{name}: signals differ from run.signals")
    X = D._Series(df, tf, ctx, coin, cache)
    p = D._resolve(name, combo)
    long_c, short_c, top, bot = _BUILD[name](D, X, p)
    if name in ("F15_LON_BRK", "F15_ORB"):
        # guard against a wrong copy of the entry's range: every final signal bar closes beyond the range it broke
        with np.errstate(invalid="ignore"):
            if not ((X.c[lg] > top[lg]).all() and (X.c[sh] < bot[sh]).all()):
                raise AssertionError(f"{name}: a signal bar does not close beyond the range this file derived")
    return NM.out_dict(SPEC[name], n, [(STATE, long_c)], [(STATE, short_c)])
