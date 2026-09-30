"""Entry-study definitions (PREREG_ENTRY.md sections 3 B / 4 C) of the batch
N15_KC_AO, N16_BBRSI, N19_FIB_CHOP, N20_EMA9_CHOP:
research/entry_study/strength_defs/<NAME>.py and research/entry_study/param_defs/<NAME>.py.

Synthetic bars only (no data files, no network): schema, shapes, NaN-safety, causality of strength(),
default signals() == the locked port (ports12.py, via sweep_lib._clean), parameter threading, and the
variant rules."""

from __future__ import annotations

import importlib.util
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from paperbot import sweepsig  # noqa: E402

L = sweepsig.lib()
import fg_indicators as fg  # noqa: E402  (vendored locked code, on sys.path after lib())
import ports12  # noqa: E402
from strategies import cross_above, cross_below  # noqa: E402

NAMES = ["N15_KC_AO", "N16_BBRSI", "N19_FIB_CHOP", "N20_EMA9_CHOP"]
SHORT_ONLY = {"N20_EMA9_CHOP"}
KINDS = {"length", "mult", "threshold_neutral", "threshold_abs"}
MULTS = (0.5, 0.75, 1.25, 1.5)
WARM = 300


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_n15batch_{kind}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = {n: _load("strength_defs", n) for n in NAMES}
PD = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int, seed: int, freq: str = "1h", wick_p: float = 0.03) -> pd.DataFrame:
    """Random walk with drifting regimes, occasional shocks (band pokes, RSI extremes, crosses) and
    occasional long single-bar wicks (a bar poking outside the Keltner band inside a trend, for N15)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.004, n // 150 + 1), 150)[:n]
    shock = np.where(rng.random(n) < 0.01, rng.normal(0, 0.05, n), 0.0)
    c = 100 * np.exp(np.cumsum(drift + shock + rng.normal(0, 0.01, n)))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    w, size = rng.random(n), rng.uniform(0.02, 0.06, n)
    lo = np.where(w < wick_p / 2, lo * (1 - size), lo)
    h = np.where((w >= wick_p / 2) & (w < wick_p), h * (1 + size), h)
    v = rng.lognormal(3, 0.6, n)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v})


N_OF = {"N15_KC_AO": 20000}   # N15 fires a few times per 10,000 bars (band poke while AO is on the trend side)


def data(name: str, seed: int) -> pd.DataFrame:
    return synth(N_OF.get(name, 3000), seed)


@pytest.fixture(scope="module")
def bars():
    return synth(3000, 1)


@pytest.fixture(scope="module")
def long_bars():
    return synth(20000, 3)


def _locked(name, df):
    p = ports12.PORTS12[name](df)
    return L._clean(p["L"], p["S"], len(df))


def _sh(x, k=1):
    x = np.asarray(x, dtype=float)
    return np.r_[np.full(min(k, len(x)), np.nan), x[:-k]] if k else x


# ------------------------------------------------------------------ strength_defs
@pytest.mark.parametrize("name", NAMES)
def test_features_schema(name):
    feats = SD[name].FEATURES
    assert 1 <= len(feats) <= 3
    seen = set()
    for f in feats:
        assert set(f) == {"name", "label_ko", "unit", "higher_is_stronger", "why"}
        assert f["name"] == f["name"].lower() and " " not in f["name"] and f["name"] not in seen
        seen.add(f["name"])
        assert 0 < len(f["label_ko"]) <= 20
        assert isinstance(f["higher_is_stronger"], bool)
        assert f["unit"] and f["why"]


@pytest.mark.parametrize("name", NAMES)
def test_strength_shapes_and_finite_at_signals(name, bars, long_bars):
    df = long_bars if name in N_OF else bars
    st = SD[name].strength(df, "1h")
    assert list(st) == [f["name"] for f in SD[name].FEATURES]
    lg, sh = PD[name].signals(df, "1h")
    post = np.arange(len(df)) >= WARM
    assert (sh & post).any()
    assert (lg & post).any() == (name not in SHORT_ONLY)
    path_only = {"reentry_rsi_depth", "div_gap_atr"}   # N16: defined on the bars where that path fires
    for f, (vl, vs) in st.items():
        for v in (vl, vs):
            assert isinstance(v, np.ndarray) and v.dtype == float and v.shape == (len(df),)
            assert not np.isinf(v).any()
        if name in SHORT_ONLY:
            assert np.isnan(vl).all()
        elif f not in path_only:
            assert np.isfinite(vl[lg & post]).all(), f
        if f not in path_only:
            assert np.isfinite(vs[sh & post]).all(), f


def test_n16_every_signal_has_a_path_feature():
    for seed in (1, 2, 3):
        df = synth(3000, seed)
        st = SD["N16_BBRSI"].strength(df, "1h")
        lg, sh = PD["N16_BBRSI"].signals(df, "1h")
        post = np.arange(len(df)) >= WARM
        for side, sig in ((0, lg), (1, sh)):
            re_ok = np.isfinite(st["reentry_rsi_depth"][side])
            dv_ok = np.isfinite(st["div_gap_atr"][side])
            assert (re_ok | dv_ok)[sig & post].all()
            assert re_ok[sig & post].any() and dv_ok[sig & post].any()


def test_strength_bounds_on_signal_bars():
    """Features that measure 'how far past the rule' respect the rule wherever it fired (locked levels).
    Bounds: (lower, lower is strict, upper or None); NaN (N16 path features, N20 ADX warm-up) skipped."""
    eps = 1e-9
    bounds = {
        "N15_KC_AO": {"prev_pierce_atr": (0.0, True, None), "reentry_atr": (0.0, True, None),
                      "ao_atr": (0.0, True, None)},
        "N16_BBRSI": {"reentry_rsi_depth": (-eps, False, 25.0 + eps), "div_gap_atr": (0.0, True, None),
                      "body_atr": (0.0, True, None)},
        "N19_FIB_CHOP": {"touch_depth_atr": (-0.2 - eps, False, None), "close_past_line_atr": (0.0, True, None),
                         "chop_slope": (0.2 - eps, False, None)},
        "N20_EMA9_CHOP": {"cross_gap_atr": (0.0, True, None), "adx_room": (0.0, True, 20.0 + eps)},
    }
    n_checked = {n: 0 for n in bounds}
    for seed in (1, 2, 3):
        for name, fb in bounds.items():
            df = data(name, seed)
            st = SD[name].strength(df, "1h")
            lg, sh = PD[name].signals(df, "1h")
            post = np.arange(len(df)) >= WARM
            for f, (lo_b, strict, hi_b) in fb.items():
                x = np.r_[st[f][0][lg & post], st[f][1][sh & post]]
                x = x[~np.isnan(x)]
                assert ((x > lo_b) if strict else (x >= lo_b)).all(), (name, f, seed)
                if hi_b is not None:
                    assert (x <= hi_b).all(), (name, f, seed)
                n_checked[name] += len(x)
    assert all(v > 0 for v in n_checked.values()), n_checked


def test_mirrored_features(bars):
    for name, feats in (("N15_KC_AO", ["ao_atr"]), ("N16_BBRSI", ["body_atr"]),
                        ("N19_FIB_CHOP", ["close_past_line_atr", "chop_slope"])):
        st = SD[name].strength(bars, "1h")
        for f in feats:
            vl, vs = st[f]
            ok = ~np.isnan(vl)
            assert np.array_equal(ok, ~np.isnan(vs)), (name, f)
            assert np.allclose(vl[ok], -vs[ok]), (name, f)


def test_n15_values(bars):
    st = SD["N15_KC_AO"].strength(bars, "1h")
    up, _m, lo = (x.to_numpy(float) for x in fg.keltner_channel(bars, 20, 10, 2.0))
    a = fg.atr(bars, 14).to_numpy(float)
    ao = fg.awesome_oscillator(bars, 5, 34).to_numpy(float)
    lo_, h, c = (bars[k].to_numpy(float) for k in ("low", "high", "close"))
    for i in (100, 1234, 2999):
        assert math.isclose(st["prev_pierce_atr"][0][i], (lo[i - 1] - lo_[i - 1]) / a[i - 1], abs_tol=1e-12)
        assert math.isclose(st["prev_pierce_atr"][1][i], (h[i - 1] - up[i - 1]) / a[i - 1], abs_tol=1e-12)
        assert math.isclose(st["reentry_atr"][0][i], (c[i] - lo[i]) / a[i], abs_tol=1e-12)
        assert math.isclose(st["ao_atr"][1][i], -ao[i] / a[i], abs_tol=1e-12)


def test_n16_reentry_depth_is_rsi_band_level(bars):
    """Where the re-entry path fires, the previous bar's mapped RSI was below the lower band, i.e. RSI < 25."""
    st = SD["N16_BBRSI"].strength(bars, "1h")
    r = fg.rsi(bars["close"], 14).to_numpy(float)
    vl, vs = st["reentry_rsi_depth"]
    il, is_ = np.flatnonzero(np.isfinite(vl)), np.flatnonzero(np.isfinite(vs))
    assert len(il) and len(is_)
    assert np.allclose(vl[il], 25.0 - r[il - 1]) and np.allclose(vs[is_], r[is_ - 1] - 75.0)


def test_n19_values(bars):
    st = SD["N19_FIB_CHOP"].strength(bars, "1h")
    h, lo_, c = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    a = fg.atr(bars, 14).to_numpy(float)
    for i in (500, 1777, 2999):
        hh, ll = h[i - 36:i - 2].max(), lo_[i - 36:i - 2].min()   # 34 bars ending 3 bars ago
        mid = ll + 0.5 * (hh - ll)
        assert math.isclose(st["touch_depth_atr"][0][i], (mid - lo_[i]) / a[i], abs_tol=1e-12)
        assert math.isclose(st["touch_depth_atr"][1][i], (h[i] - mid) / a[i], abs_tol=1e-12)
        assert math.isclose(st["close_past_line_atr"][0][i], (c[i] - mid) / a[i], abs_tol=1e-12)
    cz = fg.research_chop_zone(bars, 34, 14).to_numpy()
    slope = st["chop_slope"][0]
    ok = np.isfinite(slope)
    assert np.array_equal(np.isin(cz, ["GREEN", "BLUE"])[ok], slope[ok] >= 0.2)
    assert np.array_equal(np.isin(cz, ["RED", "DARK_RED"])[ok], slope[ok] <= -0.2)


def test_n20_values(bars):
    st = SD["N20_EMA9_CHOP"].strength(bars, "1h")
    reg = fg.research_chop_regime(bars, 14).to_numpy()
    room = st["adx_room"][1]
    ok = np.isfinite(room)
    assert np.array_equal(np.isin(reg, ["YELLOW", "RED"])[ok], room[ok] > 0)
    assert np.isnan(room[:26]).all() and ok[26:].all()        # ADX14 (Wilder DI then Wilder DX) from bar 26


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("n", [0, 1, 2, 5, 30])
def test_nan_safety_short_series(name, n):
    df = synth(max(n, 1), 7).iloc[:n].reset_index(drop=True)
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert vl.shape == (n,) and vs.shape == (n,)
        assert vl.dtype == float and vs.dtype == float
    lg, sh = PD[name].signals(df, "1h")
    assert lg.shape == (n,) and sh.shape == (n,) and lg.dtype == bool and sh.dtype == bool


@pytest.mark.parametrize("name", NAMES)
def test_nan_safety_flat_bars(name):
    df = synth(600, 11)
    df.loc[200:260, ["open", "high", "low", "close"]] = 50.0      # flat stretch: ATR -> 0, band width 0
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert not np.isinf(vl).any() and not np.isinf(vs).any()
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df)
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", [3, 4])
def test_strength_causal(name, seed):
    df = synth(1500, seed)
    full = SD[name].strength(df, "1h")
    rng = np.random.default_rng(seed)
    for k in sorted(rng.integers(20, len(df) - 1, size=5)):
        part = SD[name].strength(df.iloc[:k].reset_index(drop=True), "1h")
        for f in full:
            for side in (0, 1):
                assert np.array_equal(full[f][side][:k], part[f][side], equal_nan=True), (f, side, k)


@pytest.mark.parametrize("name", NAMES)
def test_strength_ignores_index(name, bars):
    a = SD[name].strength(bars, "1h")
    shifted = bars.copy()
    shifted.index = shifted.index + 1000
    b = SD[name].strength(shifted, "1h")
    for f in a:
        for side in (0, 1):
            assert np.array_equal(a[f][side], b[f][side], equal_nan=True)


# ------------------------------------------------------------------ param_defs
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", [1, 2, 5])
def test_default_signals_equal_locked(name, seed):
    df = data(name, seed)
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df)
    assert lg.dtype == bool and sh.dtype == bool
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)
    assert not (lg & sh).any()
    assert sh.sum() > 0 and (lg.sum() > 0) == (name not in SHORT_ONLY)


@pytest.mark.parametrize("name", NAMES)
def test_default_signals_ignore_index(name, bars):
    shifted = bars.copy()
    shifted.index = shifted.index + 1000
    a, b = PD[name].signals(bars, "1h"), PD[name].signals(shifted, "1h")
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


@pytest.mark.parametrize("name", NAMES)
def test_default_signals_timeframe_free(name, bars):
    a = PD[name].signals(bars, "1h")
    for tf in ("15m", "4h"):
        b = PD[name].signals(bars, tf)
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


@pytest.mark.parametrize("k", [2, 3, 4, 5])
def test_n16_pivot_events_equal_locked_loop(k):
    df = synth(700, 12)
    df.loc[100:110, "low"] = 90.0            # ties: equal lows inside one window
    df.loc[300:305, "high"] = 200.0
    mod = PD["N16_BBRSI"]
    for col, low, fn in (("low", True, fg.confirmed_pivot_low), ("high", False, fg.confirmed_pivot_high)):
        ev, _v = fn(df[col], k, k)
        assert np.array_equal(mod.pivot_events(df[col].to_numpy(float), k, low), ev.to_numpy(bool)), (col, k)


@pytest.mark.parametrize("name", NAMES)
def test_params_schema(name):
    mod = PD[name]
    assert mod.EXCLUDED_REASON is None
    assert 1 <= len(mod.PARAMS) <= 4
    names = [p["name"] for p in mod.PARAMS]
    assert len(set(names)) == len(names)
    for p in mod.PARAMS:
        assert set(p) == {"name", "default", "kind", "neutral", "where"}
        assert p["kind"] in KINDS
        assert (p["neutral"] is not None) == (p["kind"] == "threshold_neutral")
        assert "third_party/sweep/harness/vendor/" in p["where"]
        if p["kind"] == "length":
            assert isinstance(p["default"], int)


def _expected(p, m):
    d = p["default"]
    if p["kind"] == "length":
        return max(2, int(math.floor(d * m + 0.5)))
    if p["kind"] in ("mult", "threshold_abs"):
        return d * m
    return p["neutral"] + m * (d - p["neutral"])


@pytest.mark.parametrize("name", NAMES)
def test_variants_rules(name):
    mod = PD[name]
    for p in mod.PARAMS:
        for use in (p, p["name"]):
            vs = mod.variants(use)
            assert len(vs) == 4
            for v, m in zip(vs, MULTS):
                assert list(v) == [p["name"]]
                got, want = v[p["name"]], _expected(p, m)
                if p["kind"] == "length":
                    assert got == want and isinstance(got, int) and got >= 2
                else:
                    assert math.isclose(got, want, rel_tol=0, abs_tol=1e-11)


def test_variant_values_spelled_out():
    """The concrete numbers the runner will use (PREREG 4)."""
    got = {n: {p["name"]: [v[p["name"]] for v in PD[n].variants(p)] for p in PD[n].PARAMS} for n in NAMES}
    assert got["N15_KC_AO"] == {
        "kc_len": [10, 15, 25, 30], "kc_mult": [1.0, 1.5, 2.5, 3.0],
        "ao_fast": [3, 4, 6, 8],                                           # 2.5 -> 3, 3.75 -> 4, 6.25 -> 6, 7.5 -> 8
        "ao_slow": [17, 26, 43, 51]}                                       # 25.5 -> 26, 42.5 -> 43
    assert got["N16_BBRSI"] == {
        "bb_len": [10, 15, 25, 30], "rsi_len": [7, 11, 18, 21],            # 10.5 -> 11, 17.5 -> 18
        "map_scale": [1.0, 1.5, 2.5, 3.0], "pivot_len": [2, 2, 4, 5]}      # 1.5 -> 2, 2.25 -> 2, 3.75 -> 4, 4.5 -> 5
    assert got["N19_FIB_CHOP"] == {
        "range_len": [17, 26, 43, 51], "fib_level": [0.25, 0.375, 0.625, 0.75],
        "touch_atr": [0.1, 0.15000000000000002, 0.25, 0.30000000000000004],
        "slope_thr": [0.1, 0.15000000000000002, 0.25, 0.30000000000000004]}
    assert got["N20_EMA9_CHOP"] == {
        "ema_len": [5, 7, 11, 14], "adx_len": [7, 11, 18, 21],             # 4.5 -> 5, 6.75 -> 7, 11.25 -> 11, 13.5 -> 14
        "adx_thr": [10.0, 15.0, 25.0, 30.0]}


@pytest.mark.parametrize("name", NAMES)
def test_variants_run_and_move_signals(name, bars, long_bars):
    bars = long_bars if name in N_OF else bars
    mod = PD[name]
    base = mod.signals(bars, "1h")
    moved = 0
    n_var = 0
    for p in mod.PARAMS:
        for ov in mod.variants(p):
            lg, sh = mod.signals(bars, "1h", **ov)
            assert lg.shape == (len(bars),) and lg.dtype == bool and sh.dtype == bool
            assert not (lg & sh).any()
            if name in SHORT_ONLY:
                assert not lg.any()
            n_var += 1
            moved += int(not (np.array_equal(lg, base[0]) and np.array_equal(sh, base[1])))
    assert moved == n_var


# ---- the overrides reach the intended number of the locked expression
def test_n15_threading(long_bars):
    df = long_bars
    kl, km, af, asl = 30, 1.5, 8, 51
    up, _m, lo = (x.to_numpy(float) for x in fg.keltner_channel(df, kl, 10, km))
    ao = fg.awesome_oscillator(df, af, asl).to_numpy(float)
    h, lo_, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    with np.errstate(invalid="ignore"):
        long = (_sh(lo_) < _sh(lo)) & (c > lo) & (ao > _sh(ao)) & (ao > 0)
        short = (_sh(h) > _sh(up)) & (c < up) & (ao < _sh(ao)) & (ao < 0) & ~long
    lg, sh = PD["N15_KC_AO"].signals(df, "1h", kc_len=kl, kc_mult=km, ao_fast=af, ao_slow=asl)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_n16_threading():
    df = synth(1500, 2)
    bl, rl, ms, k = 30, 11, 2.5, 4
    o, h, lo_, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    up, _m, lo, _r, mp, sg = fg.mapped_rsi_bollinger(df, bl, 2.0, rl, 5, ms)
    upf, lof, mpf = up.to_numpy(float), lo.to_numpy(float), mp.to_numpy(float)
    with np.errstate(invalid="ignore"):
        reL = (_sh(mpf) < _sh(lof)) & (mpf >= lof) & cross_above(mp, sg)
        reS = (_sh(mpf) > _sh(upf)) & (mpf <= upf) & cross_below(mp, sg)
    div = {}
    for side, (col, fn) in {"L": ("low", fg.confirmed_pivot_low), "S": ("high", fg.confirmed_pivot_high)}.items():
        ev = fn(df[col], k, k)[0].to_numpy(bool)
        x = df[col].to_numpy(float)
        out = np.zeros(len(df), bool)
        prev = None
        for i in np.flatnonzero(ev):
            p = i - k
            if prev is not None and 5 <= p - prev <= 60:
                out[i] = (x[p] < x[prev] and mpf[p] > mpf[prev]) if side == "L" else \
                         (x[p] > x[prev] and mpf[p] < mpf[prev])
            prev = p
        div[side] = out
    long = (reL | div["L"]) & (c > o)
    short = (reS | div["S"]) & (c < o) & ~long
    lg, sh = PD["N16_BBRSI"].signals(df, "1h", bb_len=bl, rsi_len=rl, map_scale=ms, pivot_len=k)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_n16_map_scale_half_kills_reentry(bars):
    """At map_scale 1.0 the mapped RSI can only reach the band at RSI 0 / 100: only divergences remain."""
    mod = PD["N16_BBRSI"]
    lg, sh = mod.signals(bars, "1h", map_scale=1.0)
    up, _m, lo, _r, mp, sg = fg.mapped_rsi_bollinger(bars, 20, 2.0, 14, 5, 1.0)
    with np.errstate(invalid="ignore"):
        assert not (mp.to_numpy(float) < lo.to_numpy(float) - 1e-9).any()
    assert lg.sum() > 0


def test_n19_threading(bars):
    df = bars
    n, f, t, thr = 51, 0.75, 0.3, 0.1
    o, h, lo_, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    a = fg.atr(df, 14).to_numpy(float)
    hh = _sh(pd.Series(h).rolling(n).max().to_numpy(), 3)
    ll = _sh(pd.Series(lo_).rolling(n).min().to_numpy(), 3)
    R = hh - ll
    base = fg.ema(df["close"], 34)
    slope = ((base - base.shift(3)) / fg.atr(df, 14).replace(0, np.nan)).to_numpy(float)
    with np.errstate(invalid="ignore"):
        line_l, line_s = hh - f * R, ll + f * R
        long = (lo_ <= line_l + t * a) & (c > line_l) & (c > o) & (slope >= thr)
        short = (h >= line_s - t * a) & (c < line_s) & (c < o) & (slope <= -thr) & ~long
    lg, sh = PD["N19_FIB_CHOP"].signals(df, "1h", range_len=n, fib_level=f, touch_atr=t, slope_thr=thr)
    assert long.sum() > 0 and short.sum() > 0
    # hh - f R and ll + (1 - f) R may differ in the last bit; allow disagreement only where close sits on the line
    diff = np.flatnonzero((lg != long) | (sh != short))
    assert all(min(abs(c[i] - line_l[i]), abs(lo_[i] - line_l[i] - t * a[i])) < 1e-9 for i in diff)


def test_n19_fib_mirror(bars):
    """A deeper retracement (larger fib_level) moves the long line down and the short line up."""
    mod = PD["N19_FIB_CHOP"]
    for f in (0.25, 0.75):
        lg, sh = mod.signals(bars, "1h", fib_level=f)
        assert lg.dtype == bool and not (lg & sh).any()
    # with a zero touch tolerance and fib 1.0 the long line is the range low: a long needs low <= range low
    lg, _ = mod.signals(bars, "1h", fib_level=1.0, touch_atr=0.0)
    ll = _sh(bars["low"].rolling(34).min().to_numpy(float), 3)
    assert (bars["low"].to_numpy(float)[lg] <= ll[lg]).all()


def test_n20_threading(bars):
    df = bars
    el, al, thr = 14, 7, 30.0
    c = df["close"].to_numpy(float)
    e = fg.ema(df["close"], el).to_numpy(float)
    adx = fg.dmi_adx(df, al, al)[2].to_numpy(float)
    with np.errstate(invalid="ignore"):
        short = ~(adx >= thr) & (c < e) & (_sh(c) >= _sh(e))
    lg, sh = PD["N20_EMA9_CHOP"].signals(df, "1h", ema_len=el, adx_len=al, adx_thr=thr)
    assert short.sum() > 0 and not lg.any()
    assert np.array_equal(sh, short)


@pytest.mark.parametrize("name", NAMES)
def test_unknown_override_rejected(name, bars):
    with pytest.raises(ValueError):
        PD[name].signals(bars, "1h", not_a_param=1)
