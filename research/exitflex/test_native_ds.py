"""Tests of native_ds.py: the eight DeepSeek strategies' own exits (PREREG_EXITFLEX.md Appendix A.9 - A.16; section 13: T2
hand paths, T3 cut against full, T5 causality, T6 parity with ds_defs / run.signals).

    python -m pytest -q research/exitflex/test_native_ds.py

Kept in its own file so that the core strategies' section (native.py / test_native.py, written by another session) is not
disturbed; the two can be merged later.

BLIND. Everything here is synthetic bars or hand-built paths, plus one real-data class on the select period
(minutes before 2024-01-01 only, cut in memory at load) that checks equality with ``run.signals`` and causality. The tests
print nothing; they assert booleans and counts of cases. No profit, loss, win share, hold time or trade outcome is computed
anywhere: a "first exit bar" below is the index of the first chart close at which an exit condition holds on a hand-built
path, not a trade result.

Layout
  harness      synthetic frames, hand-built bars, a mirror (long <-> short) transform, the rule of A.0 on one signal.
  interface    the six arrays, access by name, refusal of other names, the ``expect`` check, the picks' combos.
  hand paths   one per strategy and side (a side is the mirror of the other): levels, targets, the first exit bar.
  oracles      plain-Python re-derivations of A.9, A.12, A.16 (zones, pivots, ties), A.10, A.13 levels, A.14 and A.15 inputs.
  properties   own side false at its signal bars, levels on every signal bar and only there, mirror symmetry, causality
               (prefix and perturbed future), F7_RF_ONLY = the opposite-signal exit (Known limit 11).
  real data    the 15 picks on the select period: equality with run.signals, levels everywhere, causality.
"""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, ROOT, os.path.join(ROOT, "research", "fullgrid")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import native_ds as ND  # noqa: E402

R = ND.fg()
D = ND.ds_module()
FGI = D.C.env()["fg"]                      # the vendor indicators ds_defs uses (ATR14 here)
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
M = 400.0                                  # the mirror axis: price' = M - price
START = pd.Timestamp("2022-01-03", tz="UTC").value // 10 ** 6      # a Monday 00:00 UTC, aligned to every timeframe
CANDIDATES = os.path.join(ROOT, "candleague", "data", "candidates.json")
FG1M = os.environ.get("EXITFLEX_FG1M", "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/"
                                       "scratchpad/fg1m")
CUT_MS = 1_704_067_200_000                 # 2024-01-01 00:00 UTC: no real bar at or after it is used anywhere here


# ====================================================================================================== harness
def mkdf(bars, tf="1h", v=None, start_ms=START):
    """A chart frame (the layout run.build_frame gives) from (open, high, low, close) rows."""
    a = np.array(bars, float)
    o, h, l, c = a.T
    assert (h >= np.maximum(o, c)).all() and (l <= np.minimum(o, c)).all(), "inconsistent hand-built bar"
    n = len(c)
    ms = start_ms + np.arange(n, dtype=np.int64) * TF_MS[tf]
    df = pd.DataFrame({"ts": pd.to_datetime(ms, unit="ms", utc=True), "open": o, "high": h, "low": l, "close": c,
                       "volume": np.ones(n) if v is None else np.asarray(v, float)})
    df.attrs["tf"] = tf
    return df


def mirror(df, axis=M):
    """The same bars upside down: long entries become short entries (and conversely) for a strategy that is symmetric."""
    out = df.copy()
    out["open"], out["high"], out["low"], out["close"] = axis - df["open"], axis - df["low"], axis - df["high"], axis - df["close"]
    out.attrs["tf"] = df.attrs["tf"]
    return out


def filler(n, base=100.0, amp=1.0, seed=0):
    """Quiet oscillation around ``base`` (range about 2), open = previous close, with a little noise so that no two bars tie."""
    rng = np.random.default_rng(seed)
    cl = base + amp * np.sin(np.arange(n) * 0.9) + rng.normal(0, 0.05, n)
    out, prev = [], base
    for c in cl:
        out.append((prev, max(prev, c) + 0.5 + abs(rng.normal(0, 0.03)), min(prev, c) - 0.5 - abs(rng.normal(0, 0.03)), c))
        prev = c
    return out


def saw(n, seed=1):
    """A sawtooth between 94 and 106 (period 8): a range with a known floor (about 93) and ceiling (about 107)."""
    rng = np.random.default_rng(seed)
    pat = np.array([100, 103, 106, 103, 100, 97, 94, 97], float)
    out, prev = [], 100.0
    for i in range(n):
        c = pat[i % 8] + rng.normal(0, 0.02)
        out.append((prev, max(prev, c) + 1 + abs(rng.normal(0, 0.02)), min(prev, c) - 1 - abs(rng.normal(0, 0.02)), c))
        prev = c
    return out


def zig(points, p0=100.0, spread=0.3, wick=0.6):
    """Waypoints [(bars, target price), ...]: closes move linearly, open = previous close, high / low = the extremes of open
    and close widened by ``spread``; the last bar of a segment that turns gets an extra ``wick`` so it is a strict pivot."""
    out, prev = [], p0
    for si, (n, tgt) in enumerate(points):
        nxt = points[si + 1][1] if si + 1 < len(points) else None
        for k in range(1, n + 1):
            c = prev + (tgt - prev) * k / n
            o = out[-1][3] if out else p0
            h, l = max(o, c) + spread, min(o, c) - spread
            if k == n and nxt is not None:
                if tgt > prev and nxt < tgt:
                    h += wick
                if tgt < prev and nxt > tgt:
                    l -= wick
            out.append((o, h, l, c))
        prev = tgt
    return out


def rand_df(seed, n, tf="1h", vol=0.01, trend=0.0006, seg=180, scale=100.0):
    """A seeded random walk with drifting regimes (so ranges, trends and reversals all occur)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-1.0, 1.0, 0.0], size=n // seg + 1), seg)[:n] * trend
    c = scale * np.exp(np.cumsum(rng.normal(0, vol, n) + drift))
    o = np.r_[scale, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    ms = START + np.arange(n, dtype=np.int64) * TF_MS[tf]
    df = pd.DataFrame({"ts": pd.to_datetime(ms, unit="ms", utc=True), "open": o, "high": h, "low": l, "close": c,
                       "volume": rng.uniform(1, 5, n)})
    df.attrs["tf"] = tf
    return df


def perturb_after(df, i, seed):
    """The same frame up to and including bar i; every bar after it replaced by a different random walk (other volatility,
    other volume) that starts at bar i's close."""
    n = len(df)
    out = df.copy()
    if i >= n - 1:
        return out
    tail = rand_df(seed, n - i - 1, df.attrs["tf"], vol=0.03, trend=0.002, seg=40, scale=1.0)
    k = float(df["close"].iloc[i])
    for col in ("open", "high", "low", "close"):
        out.iloc[i + 1:, out.columns.get_loc(col)] = tail[col].to_numpy() * k
    out.iloc[i + 1:, out.columns.get_loc("volume")] = tail["volume"].to_numpy() * 7.0
    out.attrs["tf"] = df.attrs["tf"]
    return out


def prefix(df, i):
    out = df.iloc[:i + 1].reset_index(drop=True).copy()
    out.attrs["tf"] = df.attrs["tf"]
    return out


def sig(df, tf, name, combo, ctx=None, coin="BTCUSD"):
    """(long, short) from a fresh ds_defs call (its own cache), the reference the tests compare with."""
    lg, sh = D.signals(df, tf, name, ctx=ctx, coin=coin, cache={}, **combo)
    return np.asarray(lg, bool), np.asarray(sh, bool)


def calc(df, tf, name, combo, ctx=None, coin="BTCUSD"):
    return ND.native(df, tf, name, combo, ctx, coin)


def same(a, b):
    return np.array_equal(np.asarray(a), np.asarray(b), equal_nan=True)


def first_exit(res, df, i0, side):
    """The rule of A.0 on the signal bar i0 of ``side`` (+1 long, -1 short): the own-side component and the level test are
    both false at i0 (``native`` asserts it), so rule C3 arms them at once; the exit is the first chart close after i0 at which
    the component is true or the close is beyond the level (below inv_l, above inv_s). None when there is none."""
    comp = res.lx if side > 0 else res.sx
    lvl = res.inv_l[i0] if side > 0 else res.inv_s[i0]
    c = df["close"].to_numpy()
    for j in range(i0 + 1, len(c)):
        if comp[j]:
            return j
        if np.isfinite(lvl) and ((c[j] < lvl) if side > 0 else (c[j] > lvl)):
            return j
    return None


def first_true_after(x, i0):
    nz = np.flatnonzero(np.asarray(x, bool)[i0 + 1:])
    return int(nz[0]) + i0 + 1 if len(nz) else None


def fin(x):
    return np.isfinite(x)


# the strategies, a dense combination of each (many signals on a random walk) and the timeframe it is tried on
DENSE = {
    "F10_OTE": ("1h", dict(swing_k=2, leg_atr=1.0, leg_max_bars=30)),
    "F11_TSOUP": ("4h", dict(tsoup_len=10, min_age=2)),
    "F12_MSS_DISP": ("1h", dict(swing_k=2, disp_atr=0.3)),
    "F1_PVT_DIV": ("1h", dict(swing_k=3, div_max_bars=40)),
    "F5_BOX": ("1h", dict(box_len=20, adx_max=40.0, edge=0.3, width_atr=1.0)),
    "F7_RF_ONLY": ("1h", dict(rf_period=10, rf_mult=1.5)),
    "F7_RF_TRIPLE": ("1h", dict(rf_period=10, rf_mult=1.5)),
    "F9_FVG": ("1h", dict(fvg_min_atr=0.3, zone_life=30)),
}
LEVEL_ONLY = ("F10_OTE", "F11_TSOUP", "F1_PVT_DIV", "F5_BOX", "F9_FVG")
SYMMETRIC = tuple(n for n in DENSE if n != "F1_PVT_DIV")     # PVT is built from price ratios: not an exact mirror


# the 15 picks as Appendix A writes them (the combos), against candidates.json
APPENDIX_A = {
    "ds-F10_OTE-1h-1": ("F10_OTE", "1h", dict(swing_k=3, leg_atr=3.75, leg_max_bars=30)),
    "ds-F10_OTE-4h-1": ("F10_OTE", "4h", dict(swing_k=3, leg_atr=1.5, leg_max_bars=15)),
    "ds-F11_TSOUP-4h-1": ("F11_TSOUP", "4h", dict(tsoup_len=30, min_age=2)),
    "ds-F12_MSS_DISP-1h-1": ("F12_MSS_DISP", "1h", dict(swing_k=2, disp_atr=1.8)),
    "ds-F12_MSS_DISP-4h-1": ("F12_MSS_DISP", "4h", dict(swing_k=5, disp_atr=0.96)),
    "ds-F1_PVT_DIV-1h-1": ("F1_PVT_DIV", "1h", dict(swing_k=9, div_max_bars=75)),
    "ds-F5_BOX-15m-1": ("F5_BOX", "15m", dict(box_len=72, adx_max=16.0, edge=0.12, width_atr=9.0)),
    "ds-F5_BOX-4h-1": ("F5_BOX", "4h", dict(box_len=48, adx_max=60.0, edge=0.45, width_atr=1.5)),
    "ds-F7_RF_ONLY-30m-1": ("F7_RF_ONLY", "30m", dict(rf_period=80, rf_mult=9.0)),
    "ds-F7_RF_ONLY-1h-3": ("F7_RF_ONLY", "1h", dict(rf_period=67, rf_mult=2.4)),
    "ds-F7_RF_ONLY-4h-1": ("F7_RF_ONLY", "4h", dict(rf_period=33, rf_mult=1.0)),
    "ds-F7_RF_TRIPLE-1h-1": ("F7_RF_TRIPLE", "1h", dict(rf_period=80, rf_mult=9.0)),
    "ds-F7_RF_TRIPLE-4h-1": ("F7_RF_TRIPLE", "4h", dict(rf_period=50, rf_mult=4.5)),
    "ds-F9_FVG-1h-1": ("F9_FVG", "1h", dict(fvg_min_atr=1.0, zone_life=40)),
    "ds-F9_FVG-4h-1": ("F9_FVG", "4h", dict(fvg_min_atr=0.1667, zone_life=75)),
}


def ds_picks():
    with open(CANDIDATES) as fh:
        rows = json.load(fh)["candidates"]
    return [r for r in rows if r["kind"] == "ds"]


# ====================================================================================================== interface
def test_the_eight_strategies_of_appendix_a():
    assert tuple(sorted(ND.NAMES)) == tuple(sorted({v[0] for v in APPENDIX_A.values()}))
    assert len(ND.NAMES) == 8 and set(ND.NAMES) == set(ND._BUILD)


def test_picks_are_the_fifteen_of_appendix_a():
    rows = ds_picks()
    assert sorted(r["id"] for r in rows) == sorted(APPENDIX_A)
    for r in rows:
        name, tf, combo = APPENDIX_A[r["id"]]
        assert (r["name"], r["tf"]) == (name, tf)
        assert set(r["combo"]) == set(combo)
        for k, v in combo.items():
            assert abs(float(r["combo"][k]) - v) < 1e-3 * max(1.0, abs(v)), (r["id"], k)


@pytest.mark.parametrize("name", ND.NAMES)
def test_result_arrays(name):
    tf, combo = DENSE[name]
    df = rand_df(3, 900, tf)
    before = df.copy()
    r = calc(df, tf, name, combo)
    n = len(df)
    assert isinstance(r, tuple) and len(r) == 6
    lx, sx, inv_l, inv_s, tgt_l, tgt_s = r                        # the order of A.0, as the runner's glue unpacks it
    for a in (lx, sx):
        assert a.dtype == bool and a.shape == (n,)
    for a in (inv_l, inv_s, tgt_l, tgt_s):
        assert a.dtype == np.float64 and a.shape == (n,)
    for k, a in zip(("lx", "sx", "inv_l", "inv_s", "tgt_l", "tgt_s"), r):
        assert r[k] is a and getattr(r, k) is a and r.get(k) is a      # also readable by name, as a dict
    assert tuple(r.keys()) == ("lx", "sx", "inv_l", "inv_s", "tgt_l", "tgt_s")
    assert dict(r).keys() == set(r.keys()) and r.get("zz") is None
    with pytest.raises(KeyError):
        r["zz"]
    r3 = pickle.loads(pickle.dumps(r))                              # worker processes may pass it around
    assert isinstance(r3, ND.NativeDS) and all(same(a, b) for a, b in zip(r, r3))
    assert df.equals(before)                                       # the input frame is not changed
    r2 = calc(df, tf, name, combo)                                 # nothing is kept between calls
    assert all(same(a, b) for a, b in zip(r, r2))


def test_other_names_are_refused():
    df = rand_df(1, 300, "1h")
    for bad in ("F3_BOS", "F16_FIB618", "N13_3OUTSIDE", "DOGE", ""):
        with pytest.raises(ValueError):
            ND.native(df, "1h", bad, {}, None, "BTCUSD")


@pytest.mark.parametrize("name", ND.NAMES)
def test_expect_is_checked_against_run_signals_style_arrays(name):
    tf, combo = DENSE[name]
    df = rand_df(4, 900, tf)
    lg, sh = sig(df, tf, name, combo)
    r = ND.native(df, tf, name, combo, None, "BTCUSD", expect=(lg, sh))        # equal: passes
    assert all(same(a, b) for a, b in zip(r, calc(df, tf, name, combo)))
    for bad_l, bad_s in ((~lg, sh), (lg, ~sh)):
        with pytest.raises(AssertionError):
            ND.native(df, tf, name, combo, None, "BTCUSD", expect=(bad_l, bad_s))


# ====================================================================================================== hand paths
def path_box():
    """A sawtooth range (floor about 93, ceiling about 107), then a bullish bar in the bottom 20% of the box (bar 60), then
    a close below the floor (bar 63)."""
    b = saw(60)
    seq = [(94.0, 96.5, 93.5, 95.5),          # 60: signal bar, pos = (95.5 - 92.97) / 14.06 = 0.18 <= edge 0.2
           (95.5, 97.0, 95.0, 96.5),          # 61
           (96.5, 96.8, 94.5, 95.0),          # 62: still above the floor
           (95.0, 95.2, 92.0, 92.5)]          # 63: closes below the floor 92.97
    return mkdf(b + seq)


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f5_box(side):
    combo = dict(box_len=10, adx_max=100.0, edge=0.2, width_atr=0.5)
    df = path_box() if side > 0 else mirror(path_box())
    lg, sh = sig(df, "1h", "F5_BOX", combo)
    s = 60
    assert (lg if side > 0 else sh)[s] and not (sh if side > 0 else lg)[s]
    r = calc(df, "1h", "F5_BOX", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    hi, lo = h[s - 10:s].max(), l[s - 10:s].min()                   # the box of the previous 10 bars, by hand
    if side > 0:
        assert abs(lo - 92.97) < 0.1 and abs(hi - 107.03) < 0.1       # the design, checked
        assert (r.inv_l[s], r.tgt_l[s]) == (lo, hi) and not fin(r.inv_s).any() and not fin(r.tgt_s).any()
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (hi, lo) and not fin(r.inv_l).any() and not fin(r.tgt_l).any()
    assert not r.lx.any() and not r.sx.any()                       # a level-only strategy
    assert first_exit(r, df, s, side) == 63                        # not at 61 or 62, at the first close beyond the floor


def path_tsoup():
    b = filler(50)
    last = b[-1][3]
    seq = [(last, 100.8, 98.0, 99.0),          # 50
           (99.0, 99.5, 97.0, 98.0),           # 51
           (98.0, 98.5, 92.5, 93.5),           # 52: the lowest low of the window (92.5), age 4 at the signal bar
           (93.5, 96.0, 93.0, 95.5),           # 53
           (95.5, 98.0, 95.0, 97.5),           # 54
           (97.5, 99.0, 96.5, 98.0),           # 55
           (98.0, 98.2, 90.0, 94.0),           # 56: signal bar, low 90.0 < 92.5, close 94.0 back above it
           (94.0, 95.0, 92.0, 94.5),           # 57: close above the sweep low
           (94.5, 94.6, 89.0, 89.5)]           # 58: close below 90.0
    return mkdf(b + seq, tf="4h")


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f11_tsoup(side):
    combo = dict(tsoup_len=10, min_age=2)
    df = path_tsoup() if side > 0 else mirror(path_tsoup())
    lg, sh = sig(df, "4h", "F11_TSOUP", combo)
    s = 56
    assert (lg if side > 0 else sh)[s] and not (sh if side > 0 else lg)[s]
    r = calc(df, "4h", "F11_TSOUP", combo, )
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    mid = (h[s - 10:s].max() + l[s - 10:s].min()) / 2               # the middle of the 10 bars before the signal bar
    if side > 0:
        assert abs(df["low"][s] - 90.0) < 1e-9 and abs(l[s - 10:s].min() - 92.5) < 1e-9
        assert (r.inv_l[s], r.tgt_l[s]) == (l[s], mid)
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (h[s], mid)
    assert not r.lx.any() and not r.sx.any()
    assert first_exit(r, df, s, side) == 58                        # a close beyond the sweep extreme, not the earlier retest


def path_mss(single_high=False):
    if single_high:         # only one swing high before the break: no "swing high before the one broken"
        pts = [(8, 100.0), (6, 90.0), (4, 93.0), (6, 86.0), (4, 96.0), (3, 99.0)]
    else:
        pts = [(8, 100.0), (6, 90.0), (4, 96.0), (6, 86.0), (4, 93.0), (4, 88.0), (4, 97.0), (4, 101.0), (4, 94.0),
               (3, 98.0), (5, 90.0)]
    return mkdf(zig(pts))


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f12_mss_disp(side):
    combo = dict(swing_k=2, disp_atr=0.5)
    base = path_mss()
    df = base if side > 0 else mirror(base)
    lg, sh = sig(df, "1h", "F12_MSS_DISP", combo)
    s = 34                                      # closes 90.25, 92.5, 94.75, 97: the third is the first above the swing high 93.9
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F12_MSS_DISP", combo)
    h, l, c = (base[k].to_numpy() for k in ("high", "low", "close"))
    # target: the swing high before the one the MSS broke = the bar-17 turn (96 + spread 0.3 + wick 0.6)
    assert abs(h[17] - 96.9) < 1e-9
    assert not fin(r.inv_l).any() and not fin(r.inv_s).any()            # no invalidation level: the structure flag is the exit
    if side > 0:
        assert r.tgt_l[s] == h[17]
    else:
        assert r.tgt_s[s] == M - h[17]
    # the exit: the structure turns back. The swing low of bar 43 is confirmed at bar 45 (swing_k 2); the first close below
    # its low afterwards is the exit (bar 50). Nothing fires between the signal bar and then.
    pivot_low = l[43]
    j = next(j for j in range(45, len(c)) if c[j] < pivot_low)     # from the bar that confirms the pivot (45)
    assert j == 50
    comp = r.lx if side > 0 else r.sx
    other = r.sx if side > 0 else r.lx
    assert not comp[s:j].any() and comp[j]
    assert first_exit(r, df, s, side) == j
    # the other side's flag, bos / mss in the signal's direction, is what a position on the other side would exit on
    assert other[s]                                                  # true at the signal bar itself (the MSS)


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f12_no_target_when_there_is_no_earlier_swing_high(side):
    combo = dict(swing_k=2, disp_atr=0.5)
    df = path_mss(single_high=True)
    df = df if side > 0 else mirror(df)
    lg, sh = sig(df, "1h", "F12_MSS_DISP", combo)
    s = 27
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F12_MSS_DISP", combo)
    assert np.isnan(r.tgt_l[s]) and np.isnan(r.tgt_s[s])            # NaN = none (C7): the hard stop and the structure act


def path_pvt():
    b = filler(40)
    last = b[-1][3]
    seq = [(last, 100.5, 98.6, 99.0),      # 40
           (99.0, 99.2, 98.2, 98.5),       # 41
           (98.5, 98.7, 96.8, 97.0),       # 42: first swing low a (low 96.8)
           (97.0, 98.5, 96.9, 98.0),       # 43
           (98.0, 99.2, 97.9, 99.0),       # 44
           (99.0, 101.2, 98.9, 101.0),     # 45: the rally has big volume
           (101.0, 103.2, 100.9, 103.0),   # 46
           (103.0, 105.2, 102.9, 105.0),   # 47
           (105.0, 107.2, 104.9, 107.0),   # 48
           (107.0, 108.5, 106.5, 107.5),   # 49: highest high between the lows (108.5)
           (107.5, 107.6, 105.4, 105.5),   # 50: the decline has tiny volume
           (105.5, 105.6, 103.4, 103.5),   # 51
           (103.5, 103.6, 101.4, 101.5),   # 52
           (101.5, 101.6, 99.4, 99.5),     # 53
           (99.5, 99.6, 97.4, 97.5),       # 54
           (97.5, 97.6, 95.5, 96.5),       # 55: second swing low b (low 95.5 < 96.8), PVT higher: bullish divergence
           (96.5, 98.0, 96.0, 97.5),       # 56
           (97.5, 99.0, 97.0, 98.5),       # 57: b + 2 = the bar that confirms the pivot = the signal bar
           (98.5, 99.0, 97.5, 98.0),       # 58
           (98.0, 98.5, 96.0, 96.5),       # 59: still above l[b]
           (96.5, 96.7, 94.5, 95.0)]       # 60: close below l[b] = 95.5
    v = np.ones(len(b) + len(seq))
    v[45:50] = 100.0
    return b + seq, v


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f1_pvt_div(side):
    combo = dict(swing_k=2, div_max_bars=30)
    bars, v = path_pvt()
    df = mkdf(bars, v=v)
    df = df if side > 0 else mirror(df)
    lg, sh = sig(df, "1h", "F1_PVT_DIV", combo)
    s = 57
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F1_PVT_DIV", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    if side > 0:
        assert (r.inv_l[s], r.tgt_l[s]) == (l[55], h[42:56].max()) and l[55] == 95.5 and h[42:56].max() == 108.5
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (h[55], l[42:56].min())
    assert not r.lx.any() and not r.sx.any()
    assert first_exit(r, df, s, side) == 60


def path_fvg():
    b = filler(50)
    last = b[-1][3]
    seq = [(last, 101.0, 99.5, 100.5),        # 50: b - 2, high 101.0
           (100.5, 108.5, 100.4, 108.0),      # 51: the displacement bar
           (108.0, 110.0, 104.0, 109.0),      # 52: b, low 104.0 > 101.0: a gap of 3 (zone [101, 104], middle 102.5)
           (109.0, 112.0, 108.0, 111.0),      # 53
           (111.0, 113.5, 109.0, 112.0),      # 54: the highest high before the touch (113.5)
           (112.0, 112.5, 108.5, 109.0),      # 55
           (108.0, 108.5, 103.5, 105.0),      # 56: s: low 103.5 <= 104.0 touches, close 105.0 >= 102.5
           (105.0, 105.5, 102.0, 102.5),      # 57: above the gap bottom
           (102.5, 102.6, 100.0, 100.5)]      # 58: close below the gap bottom 101.0
    return mkdf(b + seq)


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f9_fvg(side):
    combo = dict(fvg_min_atr=0.5, zone_life=10)
    df = path_fvg()
    df = df if side > 0 else mirror(df)
    lg, sh = sig(df, "1h", "F9_FVG", combo)
    s = 56
    assert (lg if side > 0 else sh)[s] and (lg | sh).sum() == 1
    r = calc(df, "1h", "F9_FVG", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    if side > 0:
        assert (r.inv_l[s], r.tgt_l[s]) == (101.0, 113.5) == (h[50], h[51:56].max())
    else:                    # short: the gap's top is l[b-2] of the mirrored bars; the target is the lowest low b-1 .. s-1
        assert (r.inv_s[s], r.tgt_s[s]) == (l[50], l[51:56].min()) and r.inv_s[s] == M - 101.0
    assert first_exit(r, df, s, side) == 58


def test_hand_f9_fvg_two_gaps_the_latest_one_gives_the_levels():
    b = filler(50)
    last = b[-1][3]
    seq = [(last, 101.0, 99.5, 100.5),      # 50
           (100.5, 108.5, 100.4, 108.0),    # 51
           (108.0, 110.0, 104.0, 109.0),    # 52: b1, zone [101, 104]
           (109.0, 112.0, 108.0, 111.5),    # 53
           (111.5, 119.0, 109.5, 118.5),    # 54
           (118.5, 121.0, 115.0, 120.0),    # 55: b2, zone [112, 115]
           (120.0, 122.0, 117.0, 121.0),    # 56
           (121.0, 121.5, 116.5, 117.0),    # 57
           (117.0, 117.5, 103.5, 114.0),    # 58: touches both tops, closes above both middles
           (114.0, 114.5, 110.0, 111.0),    # 59: close 111.0 is below the later gap's bottom 112.0 (the older gap's 101.0 is far)
           (111.0, 111.5, 108.0, 108.5)]    # 60
    combo = dict(fvg_min_atr=0.5, zone_life=10)
    for side in (1, -1):
        df = mkdf(b + seq)
        df = df if side > 0 else mirror(df)
        atr = FGI.atr(df, 14).to_numpy(float)
        Z = D.fvg_zones(df["high"].to_numpy(), df["low"].to_numpy(), atr, 0.5)
        assert sorted(Z[0].tolist()) == [52, 55]                      # the design: exactly these two gaps
        lg, sh = sig(df, "1h", "F9_FVG", combo)
        assert (lg if side > 0 else sh)[58] and (lg | sh).sum() == 1
        r = calc(df, "1h", "F9_FVG", combo)
        if side > 0:
            assert r.inv_l[58] == 112.0 and r.tgt_l[58] == 122.0      # b2 = 55: h[53], max(h[54:58]); not the older gap's 101
        else:
            assert r.inv_s[58] == M - 112.0 and r.tgt_s[58] == M - 122.0
        assert first_exit(r, df, 58, side) == 59                    # the close under 112 (the older gap's 101 is not reached)


def path_ote():
    b = filler(40)
    last = b[-1][3]
    seq = [(last, 100.5, 98.6, 99.0),      # 40
           (99.0, 99.2, 97.0, 97.5),       # 41
           (97.5, 97.8, 95.0, 96.0),       # 42: swing low, L = 95.0 (confirmed at 44)
           (96.0, 99.0, 95.9, 98.5),       # 43
           (98.5, 102.0, 98.0, 101.5),     # 44
           (101.5, 105.0, 101.0, 104.5),   # 45
           (104.5, 108.0, 104.0, 107.5),   # 46
           (107.5, 110.0, 107.0, 109.5),   # 47
           (109.5, 111.0, 109.0, 110.5),   # 48
           (110.5, 112.0, 110.0, 111.0),   # 49: swing high, H = 112.0
           (111.0, 111.5, 109.5, 110.0),   # 50
           (110.0, 110.5, 108.0, 108.5),   # 51: confirms the swing high: the leg is born (t = 51), H - L = 17
           (108.5, 108.8, 104.5, 105.0),   # 52
           (105.0, 105.2, 104.0, 104.5),   # 53: low 104.0 above the 62% level 101.46: no touch yet
           (104.5, 104.8, 101.0, 102.0),   # 54: s: low 101.0 <= 101.46, close 102.0 > the 79% level 98.57
           (102.0, 102.2, 98.0, 98.5),     # 55
           (98.5, 98.6, 95.5, 96.0),       # 56: above L
           (96.0, 96.2, 94.0, 94.5)]       # 57: close below L = 95.0
    return mkdf(b + seq)


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f10_ote(side):
    combo = dict(swing_k=2, leg_atr=2.0, leg_max_bars=30)
    base = path_ote()
    df = base if side > 0 else mirror(base)
    atr = FGI.atr(base, 14).to_numpy(float)
    assert 17.0 >= 2.0 * atr[51]                                   # the design: the leg is at least 2 ATR long
    lg, sh = sig(df, "1h", "F10_OTE", combo)
    s = 54
    assert (lg if side > 0 else sh)[s]
    r = calc(df, "1h", "F10_OTE", combo)
    if side > 0:
        assert (r.inv_l[s], r.tgt_l[s]) == (95.0, 112.0)             # L = the swing low the leg started from, H = its top
    else:
        assert (r.inv_s[s], r.tgt_s[s]) == (M - 95.0, M - 112.0)
    assert not r.lx.any() and not r.sx.any()
    assert first_exit(r, df, s, side) == 57                        # 56 closes at 96.0, above 95.0


# ====================================================================================================== oracles
def atr14(df):
    return FGI.atr(df, 14).to_numpy(float)


def pivots(x, k, high):
    """Strict swing highs (or lows) by definition: x[p] beyond the k bars on each side."""
    n = len(x)
    out = []
    for p in range(k, n - k):
        nb = [x[q] for q in range(p - k, p + k + 1) if q != p]
        if (x[p] > max(nb)) if high else (x[p] < min(nb)):
            out.append(p)
    return out


def ote_rows(df, k, leg_atr, leg_max, life=50):
    """(s, side, t, H, L) of every zone that fires, from the text of A.9, in plain loops."""
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    n, atr = len(c), atr14(df)
    ph, pl = pivots(h, k, True), pivots(l, k, False)
    rows = []
    for up in (True, False):
        for p in (ph if up else pl):
            t = p + k
            prior = [q for q in (pl if up else ph) if q + k <= t]             # the last swing confirmed at or before t
            if not prior:
                continue
            q = prior[-1]
            if up:
                H, L = h[p], l[q]
                if not (p - q <= leg_max and H - L >= leg_atr * atr[t]):
                    continue
                rg = H - L
                for s in range(t + 1, min(t + life, n - 1) + 1):
                    if l[s] <= H - 0.62 * rg:                                   # the first touch of the band
                        if not any(h[x] > H for x in range(t + 1, s + 1)) and c[s] > H - 0.79 * rg:
                            rows.append((s, 1, t, H, L))
                        break
            else:
                Lw, H = l[p], h[q]
                if not (p - q <= leg_max and H - Lw >= leg_atr * atr[t]):
                    continue
                rg = H - Lw
                for s in range(t + 1, min(t + life, n - 1) + 1):
                    if h[s] >= Lw + 0.62 * rg:
                        if not any(l[x] < Lw for x in range(t + 1, s + 1)) and c[s] < Lw + 0.79 * rg:
                            rows.append((s, -1, t, H, Lw))
                        break
    return rows


@pytest.mark.parametrize("seed", (1, 2, 3, 5))
def test_oracle_f10_ote_rows_levels_and_the_tie_rule(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    k, la, lm = 2, 1.0, 30
    rows = ote_rows(df, k, la, lm)
    by = {}
    for s, side, t, H, L in rows:
        by.setdefault((s, side), []).append((t, H, L))
    r = calc(df, "1h", "F10_OTE", dict(swing_k=k, leg_atr=la, leg_max_bars=lm))
    lg, sh = sig(df, "1h", "F10_OTE", dict(swing_k=k, leg_atr=la, leg_max_bars=lm))
    raw_l = np.zeros(len(df), bool)
    raw_s = np.zeros(len(df), bool)
    for s, side in by:
        (raw_l if side > 0 else raw_s)[s] = True
    assert same(lg, raw_l & ~raw_s) and same(sh, raw_s & ~raw_l)         # the entry is the rows of A.9 (A.9's test)
    for (s, side), lst in by.items():
        if not ((lg if side > 0 else sh)[s]):
            continue
        t, H, L = max(lst)                                               # the most recently confirmed leg (largest t)
        got = (r.inv_l[s], r.tgt_l[s]) if side > 0 else (r.inv_s[s], r.tgt_s[s])
        assert got == ((L, H) if side > 0 else (H, L))
    assert same(fin(r.inv_l), lg) and same(fin(r.tgt_l), lg) and same(fin(r.inv_s), sh) and same(fin(r.tgt_s), sh)


def fvg_rows(df, x, life):
    """(s, side, b, lo, hi) of every gap whose first touch confirms (close beyond the middle), from the text of A.16."""
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    n, atr = len(c), atr14(df)
    rows = []
    for b in range(2, n):
        up = l[b] > h[b - 2] and (l[b] - h[b - 2]) >= x * atr[b]
        dn = h[b] < l[b - 2] and (l[b - 2] - h[b]) >= x * atr[b]
        if not (up or dn):
            continue
        lo, hi = (h[b - 2], l[b]) if up else (h[b], l[b - 2])
        for s in range(b + 1, min(b + life, n - 1) + 1):
            if (l[s] <= hi) if up else (h[s] >= lo):                  # the first touch decides, whatever the close is
                if (c[s] >= (lo + hi) / 2) if up else (c[s] <= (lo + hi) / 2):
                    rows.append((s, 1 if up else -1, b, lo, hi))
                break
    return rows


FVG_ORACLE = (0.1, 100)           # fvg_min_atr, zone_life: many small gaps that live long, so that several fire on one bar


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_oracle_f9_fvg_rows_levels_and_the_tie_rule(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    x, life = FVG_ORACLE
    rows = fvg_rows(df, x, life)
    by = {}
    for s, side, b, lo, hi in rows:
        by.setdefault((s, side), []).append((b, lo, hi))
    combo = dict(fvg_min_atr=x, zone_life=life)
    r = calc(df, "1h", "F9_FVG", combo)
    lg, sh = sig(df, "1h", "F9_FVG", combo)
    raw_l = np.zeros(len(df), bool)
    raw_s = np.zeros(len(df), bool)
    for s, side in by:
        (raw_l if side > 0 else raw_s)[s] = True
    assert same(lg, raw_l & ~raw_s) and same(sh, raw_s & ~raw_l)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    for (s, side), lst in by.items():
        if not ((lg if side > 0 else sh)[s]):
            continue
        b, lo, hi = max(lst)                                              # the most recently born gap (largest b)
        if side > 0:
            assert (r.inv_l[s], r.tgt_l[s]) == (lo, h[b - 1:s].max())
        else:
            assert (r.inv_s[s], r.tgt_s[s]) == (hi, l[b - 1:s].min())
    assert same(fin(r.inv_l), lg) and same(fin(r.tgt_l), lg) and same(fin(r.inv_s), sh) and same(fin(r.tgt_s), sh)


def test_the_tie_rules_are_exercised_by_these_series():
    """Bars where several zones fire on one side with different levels (so that "the largest t / b" decides something): the
    OTE and FVG oracle series above contain plenty of them (a count of bars, not a result)."""
    n_ote = n_fvg = 0
    for seed in (1, 2, 3, 5):
        by = {}
        for s, side, t, H, L in ote_rows(rand_df(seed, 2500, "1h", vol=0.012), 2, 1.0, 30):
            by.setdefault((s, side), []).append((t, H, L))
        n_ote += sum(len(v) > 1 and len({(H, L) for _t, H, L in v}) > 1 and (s, -side) not in by for (s, side), v in by.items())
    for seed in (1, 2, 3):
        by = {}
        for s, side, b, lo, hi in fvg_rows(rand_df(seed, 2500, "1h", vol=0.012), *FVG_ORACLE):
            by.setdefault((s, side), []).append((b, lo, hi))
        n_fvg += sum(len(v) > 1 and len({(lo, hi) for _b, lo, hi in v}) > 1 and (s, -side) not in by for (s, side), v in by.items())
    assert n_ote >= 5 and n_fvg >= 5


def pvt_pairs(df, k, mx):
    """(side, a, b) of every ok pair of consecutive swing pivots, from the text of A.12, in plain loops."""
    h, l, c, v = (df[x].to_numpy() for x in ("high", "low", "close", "volume"))
    pvt = np.cumsum([0.0] + [v[i] * (c[i] / c[i - 1] - 1) for i in range(1, len(c))])
    out = []
    pl, ph = pivots(l, k, False), pivots(h, k, True)
    for a, b in zip(pl[:-1], pl[1:]):
        if b - a <= mx and l[b] < l[a] and pvt[b] > pvt[a]:
            out.append((1, a, b))
    for a, b in zip(ph[:-1], ph[1:]):
        if b - a <= mx and h[b] > h[a] and pvt[b] < pvt[a]:
            out.append((-1, a, b))
    return out


@pytest.mark.parametrize("seed", (1, 2, 3, 4))
def test_oracle_f1_pvt_div_pairs_and_levels(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    k, mx = 3, 40
    pairs = pvt_pairs(df, k, mx)
    combo = dict(swing_k=k, div_max_bars=mx)
    r = calc(df, "1h", "F1_PVT_DIV", combo)
    lg, sh = sig(df, "1h", "F1_PVT_DIV", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    raw_l = np.zeros(len(df), bool)
    raw_s = np.zeros(len(df), bool)
    for side, a, b in pairs:
        (raw_l if side > 0 else raw_s)[b + k] = True
    assert same(lg, raw_l & ~raw_s) and same(sh, raw_s & ~raw_l)
    seen = 0
    for side, a, b in pairs:
        s = b + k
        if side > 0 and lg[s]:
            assert (r.inv_l[s], r.tgt_l[s]) == (l[b], h[a:b + 1].max())
            seen += 1
        if side < 0 and sh[s]:
            assert (r.inv_s[s], r.tgt_s[s]) == (h[b], l[a:b + 1].min())
            seen += 1
    assert seen >= 10
    assert same(fin(r.inv_l), lg) and same(fin(r.tgt_l), lg) and same(fin(r.inv_s), sh) and same(fin(r.tgt_s), sh)


@pytest.mark.parametrize("seed", (1, 2))
def test_oracle_f11_tsoup_entry_and_levels(seed):
    df = rand_df(seed, 2500, "4h", vol=0.012)
    w, age = 10, 2
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    n = len(c)
    exp_l, exp_s = np.zeros(n, bool), np.zeros(n, bool)
    for s in range(w, n):
        Lw, Hw = l[s - w:s].min(), h[s - w:s].max()
        age_lo = s - (s - w + int(np.argmin(l[s - w:s])))
        age_hi = s - (s - w + int(np.argmax(h[s - w:s])))
        exp_l[s] = l[s] < Lw and c[s] > Lw and age_lo >= age
        exp_s[s] = h[s] > Hw and c[s] < Hw and age_hi >= age
    both = exp_l & exp_s
    exp_l, exp_s = exp_l & ~both, exp_s & ~both
    combo = dict(tsoup_len=w, min_age=age)
    lg, sh = sig(df, "4h", "F11_TSOUP", combo)
    assert same(lg, exp_l) and same(sh, exp_s)
    r = calc(df, "4h", "F11_TSOUP", combo)
    for s in np.flatnonzero(lg):
        assert (r.inv_l[s], r.tgt_l[s]) == (l[s], (h[s - w:s].max() + l[s - w:s].min()) / 2)
    for s in np.flatnonzero(sh):
        assert (r.inv_s[s], r.tgt_s[s]) == (h[s], (h[s - w:s].max() + l[s - w:s].min()) / 2)
    assert lg.sum() >= 20 and sh.sum() >= 20
    assert same(fin(r.inv_l), lg) and same(fin(r.tgt_l), lg) and same(fin(r.inv_s), sh) and same(fin(r.tgt_s), sh)


@pytest.mark.parametrize("seed", (1, 2))
def test_oracle_f5_box_levels(seed):
    df = rand_df(seed, 2500, "1h", vol=0.012)
    combo = dict(box_len=20, adx_max=40.0, edge=0.3, width_atr=1.0)
    lg, sh = sig(df, "1h", "F5_BOX", combo)
    r = calc(df, "1h", "F5_BOX", combo)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    assert lg.sum() >= 10 and sh.sum() >= 10
    for s in np.flatnonzero(lg):
        assert (r.inv_l[s], r.tgt_l[s]) == (l[s - 20:s].min(), h[s - 20:s].max())
    for s in np.flatnonzero(sh):
        assert (r.inv_s[s], r.tgt_s[s]) == (h[s - 20:s].max(), l[s - 20:s].min())
    assert same(fin(r.inv_l), lg) and same(fin(r.tgt_l), lg) and same(fin(r.inv_s), sh) and same(fin(r.tgt_s), sh)


def rf_dir_ref(c, period, mult):
    """The range filter of A.14 in plain loops: r = mult x EMA(2p - 1) of EMA(p) of |close change|; the filter steps up to
    c - r when c - r > f and down to c + r when c + r < f; the direction is the sign of its last step."""
    c = np.asarray(c, float)
    a1, a2 = 2.0 / (period + 1), 2.0 / (2 * period - 1 + 1)
    e1 = e2 = 0.0
    f, dr = c[0], 0
    out = np.zeros(len(c))
    for i in range(len(c)):
        d = abs(c[i] - c[i - 1]) if i else 0.0
        e1 = d if i == 0 else a1 * d + (1 - a1) * e1
        e2 = e1 if i == 0 else a2 * e1 + (1 - a2) * e2
        if i == 0:
            continue
        r = mult * e2
        nf = c[i] - r if c[i] - r > f else (c[i] + r if c[i] + r < f else f)
        dr = 1 if nf > f else (-1 if nf < f else dr)
        f = nf
        out[i] = dr
    return out


def ha_ref(o, h, l, c):
    """Heikin-Ashi candle colour: 1 up, 0 down, 0.5 flat (HA close (o+h+l+c)/4; HA open = mean of the previous HA open and close)."""
    n = len(c)
    hac = (o + h + l + c) / 4
    hao = np.zeros(n)
    hao[0] = (o[0] + c[0]) / 2
    for i in range(1, n):
        hao[i] = (hao[i - 1] + hac[i - 1]) / 2
    return np.where(hac > hao, 1.0, np.where(hac < hao, 0.0, 0.5))


def hha_ref(df, ratio):
    """The higher-timeframe Heikin-Ashi colour at each chart bar: the last HTF bar (``ratio`` chart bars, aligned to the first
    bar) that has closed at or before the chart bar's close; NaN before the first one has."""
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    m = len(c) // ratio + (len(c) % ratio > 0)
    ho = np.array([o[k * ratio] for k in range(m)])
    hh = np.array([h[k * ratio:(k + 1) * ratio].max() for k in range(m)])
    hl = np.array([l[k * ratio:(k + 1) * ratio].min() for k in range(m)])
    hc = np.array([c[min((k + 1) * ratio, len(c)) - 1] for k in range(m)])
    col = ha_ref(ho, hh, hl, hc)
    out = np.full(len(c), np.nan)
    for i in range(len(c)):
        j = (i + 1) // ratio - 1                      # HTF bar j closes after (j + 1) x ratio chart bars
        if j >= 0:
            out[i] = col[j]
    return out


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_oracle_f7_rf_only(seed):
    df = rand_df(seed, 1500, "1h", vol=0.01)
    combo = dict(rf_period=10, rf_mult=1.5)
    rf = rf_dir_ref(df["close"].to_numpy(), 10, 1.5)
    assert same(rf, D.range_filter_dir(df["close"].to_numpy(), 10, 1.5))      # the library's filter is the text's filter
    r = calc(df, "1h", "F7_RF_ONLY", combo)
    assert same(r.lx, rf == -1) and same(r.sx, rf == 1)
    assert not fin(r.inv_l).any() and not fin(r.inv_s).any() and not fin(r.tgt_l).any() and not fin(r.tgt_s).any()
    lg, sh = sig(df, "1h", "F7_RF_ONLY", combo)
    prev = np.r_[0.0, rf[:-1]]
    assert same(lg, (rf == 1) & (prev == -1)) and same(sh, (rf == -1) & (prev == 1))     # the entry is the direction turn


@pytest.mark.parametrize("tf,ratio,seed", (("1h", 4, 1), ("1h", 4, 2), ("4h", 6, 3)))
def test_oracle_f7_rf_triple(tf, ratio, seed):
    df = rand_df(seed, 1500, tf, vol=0.01)
    combo = dict(rf_period=10, rf_mult=1.5)
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    rf, ha, hha = rf_dir_ref(c, 10, 1.5), ha_ref(o, h, l, c), hha_ref(df, ratio)
    assert np.isnan(hha[:ratio - 1]).all() and not np.isnan(hha[ratio - 1:]).any()
    r = calc(df, tf, "F7_RF_TRIPLE", combo)
    with np.errstate(invalid="ignore"):
        exp_l = (rf == -1) | (ha == 0) | (hha == 0)                # a NaN or a flat 0.5 compares False: it does not fire
        exp_s = (rf == 1) | (ha == 1) | (hha == 1)
    assert same(r.lx, exp_l) and same(r.sx, exp_s)
    assert not fin(r.inv_l).any() and not fin(r.tgt_l).any() and not fin(r.inv_s).any() and not fin(r.tgt_s).any()
    lg, sh = sig(df, tf, "F7_RF_TRIPLE", combo)
    up, dn = (rf == 1) & (ha == 1) & (hha == 1), (rf == -1) & (ha == 0) & (hha == 0)
    assert same(lg, up & ~np.r_[False, up[:-1]]) and same(sh, dn & ~np.r_[False, dn[:-1]])       # first bar of a run
    for s in np.flatnonzero(lg):                  # the first end is never later than the opposite signal
        j = first_true_after(r.lx, s)
        if j is not None:
            assert j <= (first_true_after(sh, s) or 10 ** 9)


def test_f7_rf_triple_each_of_the_three_inputs_can_end_a_trade_alone():
    """The OR of A.15 is exercised: across series there are long entries whose first exit is caused by the range filter alone,
    by the chart Heikin-Ashi alone, and by the higher-timeframe Heikin-Ashi alone (and the same for shorts)."""
    seen = {1: set(), -1: set()}
    for seed in range(1, 9):
        df = rand_df(seed, 1500, "1h", vol=0.01)
        o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
        rf, ha, hha = rf_dir_ref(c, 10, 1.5), ha_ref(o, h, l, c), hha_ref(df, 4)
        r = calc(df, "1h", "F7_RF_TRIPLE", dict(rf_period=10, rf_mult=1.5))
        lg, sh = sig(df, "1h", "F7_RF_TRIPLE", dict(rf_period=10, rf_mult=1.5))
        for side, mine, comp, turned in ((1, lg, r.lx, (rf == -1, ha == 0, hha == 0)),
                                         (-1, sh, r.sx, (rf == 1, ha == 1, hha == 1))):
            for s in np.flatnonzero(mine):
                j = first_true_after(comp, s)
                if j is not None:
                    flags = tuple(bool(t[j]) for t in turned)
                    if sum(flags) == 1:
                        seen[side].add(flags.index(True))
    assert seen[1] == {0, 1, 2} and seen[-1] == {0, 1, 2}


def test_f7_rf_triple_a_missing_higher_timeframe_value_does_not_fire():
    df = rand_df(5, 60, "1h", vol=0.01)
    r = calc(df, "1h", "F7_RF_TRIPLE", dict(rf_period=10, rf_mult=1.5))
    c, o, h, l = (df[x].to_numpy() for x in ("close", "open", "high", "low"))
    rf, ha = rf_dir_ref(c, 10, 1.5), ha_ref(o, h, l, c)
    assert same(r.lx[:3], ((rf == -1) | (ha == 0))[:3])             # bars 0-2: no 4h bar has closed yet (NaN): only rf and ha count
    assert same(r.sx[:3], ((rf == 1) | (ha == 1))[:3])


def path_rf(side=1):
    """100 down to 80, up to 120, down to 90, up to 110 in 25-bar legs."""
    pts = [(25, 80.0), (25, 120.0), (25, 90.0), (25, 110.0)]
    out, prev = [], 100.0
    for n, tgt in pts:
        for k in range(1, n + 1):
            c = prev + (tgt - prev) * k / n
            o = out[-1][3] if out else 100.0
            out.append((o, max(o, c) + 0.4, min(o, c) - 0.4, c))
        prev = tgt
    return mkdf(out)


@pytest.mark.parametrize("side", (1, -1))
def test_hand_f7_rf_only_the_exit_is_the_opposite_signal(side):
    combo = dict(rf_period=5, rf_mult=1.5)
    df = path_rf() if side > 0 else mirror(path_rf())
    r = calc(df, "1h", "F7_RF_ONLY", combo)
    lg, sh = sig(df, "1h", "F7_RF_ONLY", combo)
    mine, opp = (lg, sh) if side > 0 else (sh, lg)
    assert mine.sum() >= 1 and opp.sum() >= 1
    n_exits = 0
    for s in np.flatnonzero(mine):
        j = first_exit(r, df, s, side)
        assert j == first_true_after(opp, s) and (j is None or opp[j])
        n_exits += j is not None
    assert n_exits >= 1
    rf = rf_dir_ref(df["close"].to_numpy(), 5, 1.5)
    assert same(r.lx, rf == -1) and same(r.sx, rf == 1)


# ====================================================================================================== properties
@pytest.mark.parametrize("name", ND.NAMES)
@pytest.mark.parametrize("seed", (1, 2))
def test_every_signal_bar_has_its_levels_and_the_own_side_is_quiet(name, seed):
    tf, combo = DENSE[name]
    df = rand_df(seed, 2500, tf, vol=0.012)
    lg, sh = sig(df, tf, name, combo)
    ND.native(df, tf, name, combo, None, "BTCUSD", expect=(lg, sh))           # T6: the asserted equality with ds_defs signals
    r = calc(df, tf, name, combo)
    assert lg.sum() >= 3 and sh.sum() >= 3
    assert not r.lx[lg].any() and not r.sx[sh].any()                             # A.0: false at their own signal bars
    if name in LEVEL_ONLY:
        for arr, sg in ((r.inv_l, lg), (r.tgt_l, lg), (r.inv_s, sh), (r.tgt_s, sh)):
            assert same(fin(arr), sg)                                          # a level and a target on every signal bar, only there
        assert not r.lx.any() and not r.sx.any()
        # the invalidation is on the losing side of the signal bar's close, except where the entry makes it impossible (A.9-A.16)
        c = df["close"].to_numpy()
        assert (c[lg] >= r.inv_l[lg]).all() and (c[sh] <= r.inv_s[sh]).all()
    elif name == "F12_MSS_DISP":
        assert not fin(r.inv_l).any() and not fin(r.inv_s).any()
        assert ((~fin(r.tgt_l)) | lg).all() and ((~fin(r.tgt_s)) | sh).all()
    else:
        for arr in (r.inv_l, r.inv_s, r.tgt_l, r.tgt_s):
            assert not fin(arr).any()


@pytest.mark.parametrize("name", ND.NAMES)
def test_other_side_component_at_a_signal_bar(name):
    """A.0 coin-flip note: a position on the other side uses its own side's component under rule C3. For the range-filter
    strategies that component is already true at the strategy's own signal bar, so a flipped position must wait."""
    tf, combo = DENSE[name]
    df = rand_df(2, 2500, tf, vol=0.012)
    lg, sh = sig(df, tf, name, combo)
    r = calc(df, tf, name, combo)
    if name in ("F7_RF_ONLY", "F7_RF_TRIPLE"):
        assert r.sx[lg].all() and r.lx[sh].all()
    if name in LEVEL_ONLY:
        assert not r.sx[lg].any() and not r.lx[sh].any()


@pytest.mark.parametrize("name", SYMMETRIC)
def test_mirror_symmetry(name):
    """Turning the bars upside down turns every long into a short with the mirrored levels, targets and components."""
    tf, combo = DENSE[name]
    df = rand_df(3, 2000, tf, vol=0.012)
    mdf = mirror(df)
    lg, sh = sig(df, tf, name, combo)
    mlg, msh = sig(mdf, tf, name, combo)
    assert same(lg, msh) and same(sh, mlg) and lg.sum() >= 3
    r, mr = calc(df, tf, name, combo), calc(mdf, tf, name, combo)
    assert same(r.lx, mr.sx) and same(r.sx, mr.lx)
    for a, b in ((r.inv_l, mr.inv_s), (r.inv_s, mr.inv_l), (r.tgt_l, mr.tgt_s), (r.tgt_s, mr.tgt_l)):
        assert same(fin(a), fin(b))
        assert np.allclose(M - a[fin(a)], b[fin(b)], rtol=0, atol=1e-9)


def cut_points(df, tf, name, combo, n_signal=4):
    lg, sh = sig(df, tf, name, combo)
    sigs = np.flatnonzero(lg | sh)
    pick = sigs[np.linspace(0, len(sigs) - 1, n_signal).astype(int)] if len(sigs) else np.array([], int)
    return sorted({int(i) for i in pick if i >= 100} | {len(df) // 3, len(df) // 2, len(df) - 5})


def upto(r, i):
    return [a[:i + 1] for a in r]


@pytest.mark.parametrize("name", ND.NAMES)
def test_causality_prefix_and_perturbed_future(name):
    """T3 / T5: the arrays at bars <= i do not change when the bars after i are cut off or replaced by other prices and volumes."""
    tf, combo = DENSE[name]
    df = rand_df(7, 1800, tf, vol=0.012)
    full = calc(df, tf, name, combo)
    for i in cut_points(df, tf, name, combo):
        cut = calc(prefix(df, i), tf, name, combo)
        assert all(same(a, b) for a, b in zip(upto(full, i), cut)), (name, i, "prefix")
        for seed in (11, 12):
            pert = calc(perturb_after(df, i, seed), tf, name, combo)
            assert all(same(a, b) for a, b in zip(upto(full, i), upto(pert, i))), (name, i, seed, "perturbed")


@pytest.mark.parametrize("tf,combo", (("1h", dict(rf_period=10, rf_mult=1.5)), ("4h", dict(rf_period=8, rf_mult=1.2))))
def test_causality_of_the_higher_timeframe_inputs_of_f7_rf_triple(tf, combo):
    """Cutting at every chart bar of one higher-timeframe bar and the bar after it: the HTF colour is taken only from closed bars."""
    df = rand_df(9, 900, tf, vol=0.012)
    full = calc(df, tf, "F7_RF_TRIPLE", combo)
    for i in range(300, 330):
        cut = calc(prefix(df, i), tf, "F7_RF_TRIPLE", combo)
        assert all(same(a, b) for a, b in zip(upto(full, i), cut)), i


def test_f7_rf_only_is_the_opposite_signal_exit():
    """Known limit 11: for F7_RF_ONLY the strategy's own exit (F11) is its opposite signal (F3): the first bar after a signal at
    which the own-side component is true is the first opposite signal, and there are no levels or targets, so F11.a = F3.a
    (both keep the pick's take-profit) and F11.b = F3.b (neither has one)."""
    n_checked = 0
    for seed, (tf, combo) in ((1, ("1h", dict(rf_period=10, rf_mult=1.5))), (2, ("30m", dict(rf_period=6, rf_mult=1.0))),
                              (3, ("4h", dict(rf_period=33, rf_mult=1.0)))):
        df = rand_df(seed, 2500, tf, vol=0.012)
        lg, sh = sig(df, tf, "F7_RF_ONLY", combo)
        r = calc(df, tf, "F7_RF_ONLY", combo)
        assert not fin(r.inv_l).any() and not fin(r.inv_s).any() and not fin(r.tgt_l).any() and not fin(r.tgt_s).any()
        for side, mine, opp in ((1, lg, sh), (-1, sh, lg)):
            for s in np.flatnonzero(mine):
                assert first_exit(r, df, s, side) == first_true_after(opp, s)
                n_checked += 1
    assert n_checked >= 100


def test_f7_rf_triple_is_not_the_opposite_signal_exit():
    """A.15: one turned input ends the trade, long before all three have turned (which is the opposite signal)."""
    df = rand_df(1, 2500, "1h", vol=0.012)
    combo = dict(rf_period=10, rf_mult=1.5)
    lg, sh = sig(df, "1h", "F7_RF_TRIPLE", combo)
    r = calc(df, "1h", "F7_RF_TRIPLE", combo)
    earlier = later = 0
    for s in np.flatnonzero(lg):
        j, o = first_true_after(r.lx, s), first_true_after(sh, s)
        if j is not None and o is not None:
            assert j <= o
            earlier += j < o
            later += j > o
    assert earlier >= 10 and later == 0


# ====================================================================================================== real data (select period)
@pytest.fixture(scope="module")
def real():
    """BTC and DOGE 1m arrays cut in memory at 2024-01-01 (minutes that open before it), and ``run`` reading them: its
    ``minute_data`` is replaced for this module, so ``run.frame`` / ``run.signals`` build the study's own chart bars from the
    cut arrays. No bar at or after the cut is ever used."""
    if not os.path.isdir(os.path.join(FG1M, "1m")):
        pytest.skip("the study's 1m arrays are not on this machine")
    cut = {}
    for sym in ("BTCUSDT", "DOGEUSDT"):
        d = R.DATA.load(FG1M, sym)
        n = int(np.searchsorted(d["ts"], CUT_MS, side="left"))
        cut[sym] = {k: np.ascontiguousarray(d[k][:n]) for k in ("ts", "o", "h", "l", "c", "v")}
        del d
        assert cut[sym]["ts"][-1] < CUT_MS
    mp = pytest.MonkeyPatch()
    mp.setattr(R, "minute_data", lambda data_dir, sym: cut[sym])
    R.frame.cache_clear()
    yield "select-cut"
    mp.undo()
    R.frame.cache_clear()
    R.M.clear()


def real_inputs(real_dir, sym, tf):
    df, close_ms = R.frame(real_dir, sym, tf)
    assert close_ms.max() <= CUT_MS                                          # no chart bar closes after the cut
    ctx = None if sym == "BTCUSDT" else {"BTCUSD": R.frame(real_dir, "BTCUSDT", tf)[0]}
    return df, ctx, sym[:-1]


PICKS = ds_picks() if os.path.exists(CANDIDATES) else []


@pytest.mark.parametrize("pick", PICKS, ids=[p["id"] for p in PICKS])
@pytest.mark.parametrize("sym", ("BTCUSDT", "DOGEUSDT"))
def test_real_parity_with_run_signals_levels_and_quiet_own_side(real, pick, sym):
    """T6: native_ds reproduces run.signals bar for bar on the select-period bars (its own call is asserted equal), every
    final signal bar of a level strategy has its levels, the own side is quiet at its signal bars. Booleans only."""
    name, tf, combo = pick["name"], pick["tf"], pick["combo"]
    df, ctx, coin = real_inputs(real, sym, tf)
    lg, sh = R.signals(real, "ds", name, sym, tf, combo)
    r = ND.native(df, tf, name, combo, ctx, coin, expect=(lg, sh))
    assert not r.lx[lg].any() and not r.sx[sh].any()
    if name in LEVEL_ONLY:
        for arr, sg in ((r.inv_l, lg), (r.tgt_l, lg), (r.inv_s, sh), (r.tgt_s, sh)):
            assert same(fin(arr), sg)
    elif name == "F12_MSS_DISP":
        assert not fin(r.inv_l).any() and not fin(r.inv_s).any()
        assert ((~fin(r.tgt_l)) | lg).all() and ((~fin(r.tgt_s)) | sh).all()
    else:
        assert not any(fin(a).any() for a in (r.inv_l, r.inv_s, r.tgt_l, r.tgt_s))
    if name == "F7_RF_ONLY":                                                   # Known limit 11 on the real picks
        for side, mine, opp in ((1, lg, sh), (-1, sh, lg)):
            for s in np.flatnonzero(mine)[:200]:
                assert first_exit(r, df, s, side) == first_true_after(opp, s)


@pytest.mark.parametrize("pick", PICKS, ids=[p["id"] for p in PICKS])
def test_real_causality(real, pick):
    """T3 / T5 on real select-period bars (BTC): cutting the frame, or replacing the bars after a cut with other prices, leaves
    the arrays at and before the cut unchanged."""
    name, tf, combo = pick["name"], pick["tf"], pick["combo"]
    df, ctx, coin = real_inputs(real, "BTCUSDT", tf)
    n = len(df)
    full = ND.native(df, tf, name, combo, ctx, coin)
    lg, sh = sig(df, tf, name, combo, ctx, coin)
    sigs = np.flatnonzero(lg | sh)
    cuts = {int(n * 0.45), int(n * 0.8)}
    if len(sigs):
        cuts |= {int(sigs[len(sigs) // 2]), int(sigs[-1])}
    for i in sorted(cuts):
        cut = ND.native(prefix(df, i), tf, name, combo, ctx_cut(ctx, i), coin)
        assert all(same(a, b) for a, b in zip(upto(full, i), cut)), (pick["id"], i, "prefix")
    i = int(sigs[len(sigs) // 2]) if len(sigs) else n // 2
    pert = ND.native(perturb_after(df, i, 5), tf, name, combo, ctx, coin)
    assert all(same(a, b) for a, b in zip(upto(full, i), upto(pert, i))), (pick["id"], i, "perturbed")


def ctx_cut(ctx, i):
    return None if ctx is None else {"BTCUSD": prefix(ctx["BTCUSD"], i)}
