"""Entry-study definitions (PREREG_ENTRY.md sections 3 B / 4 C) of the batch
N05_PSAR_POC, N06_MACD_ORB, N11_BREAKAWAY, N13_3OUTSIDE:
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
import fg_fast  # noqa: E402  (vendored locked code, on sys.path after lib())
import fg_indicators as fg  # noqa: E402
import ports12  # noqa: E402
from poc_fast import poc_series  # noqa: E402
from strategies import cross_above, cross_below, recent  # noqa: E402

NAMES = ["N05_PSAR_POC", "N06_MACD_ORB", "N11_BREAKAWAY", "N13_3OUTSIDE"]
KINDS = {"length", "mult", "threshold_neutral", "threshold_abs"}
MULTS = (0.5, 0.75, 1.25, 1.5)
WARM = 300
EPS = 1e-9


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_n05batch_{kind}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = {n: _load("strength_defs", n) for n in NAMES}
PD = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int, seed: int, freq: str = "1h") -> pd.DataFrame:
    """Random walk with drifting regimes and occasional shocks (big bodies, pattern breaks, crosses);
    the open sits a little off the previous close (as in the exchange data), so gap rules can bind."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.004, n // 150 + 1), 150)[:n]
    shock = np.where(rng.random(n) < 0.01, rng.normal(0, 0.05, n), 0.0)
    c = 100 * np.exp(np.cumsum(drift + shock + rng.normal(0, 0.01, n)))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(0, 0.0015, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    v = rng.lognormal(3, 0.6, n)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v})


@pytest.fixture(scope="module")
def bars():
    return synth(3000, 1)


@pytest.fixture(scope="module")
def long_bars():
    """N11's five-bar pattern is rare; a longer series gives it both long and short signals."""
    return synth(12000, 3)


def _df_for(name, bars, long_bars):
    return long_bars if name == "N11_BREAKAWAY" else bars


def _locked(name, df):
    p = ports12.PORTS12[name](df)
    return L._clean(p["L"], p["S"], len(df))


def _sh(x, k):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:len(x) - k] if k else x
    return out


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
    df = _df_for(name, bars, long_bars)
    st = SD[name].strength(df, "1h")
    assert list(st) == [f["name"] for f in SD[name].FEATURES]
    lg, sh = PD[name].signals(df, "1h")
    post = np.arange(len(df)) >= WARM
    assert (lg & post).any() and (sh & post).any()
    for f, (vl, vs) in st.items():
        for v in (vl, vs):
            assert isinstance(v, np.ndarray) and v.dtype == float and v.shape == (len(df),)
            assert not np.isinf(v).any()
        assert np.isfinite(vl[lg & post]).all(), f
        assert np.isfinite(vs[sh & post]).all(), f


# (lower, lower is strict, upper, upper is strict) that the locked rule implies on every signal bar
BOUNDS = {
    "N05_PSAR_POC": {"pierce_depth": (0.5, False, 1.0, True), "poc_bounce_atr": (-0.2, False, None, False),
                     "sar_gap_atr": (0.0, True, None, False)},
    "N06_MACD_ORB": {"orb_break_atr": (None, False, 1.5, False), "macd_line_atr": (0.0, True, None, False),
                     "macd_hist_atr": (0.0, True, None, False)},
    "N11_BREAKAWAY": {"reversal_body_atr": (0.8, False, None, False), "first_body_atr": (0.8, False, None, False),
                      "pause_body_atr": (0.0, False, 0.4, False)},
    "N13_3OUTSIDE": {"engulf_body_atr": (0.5, False, None, False), "confirm_close_atr": (0.0, True, None, False),
                     "breakout_atr": (0.0, True, None, False)},
}


@pytest.mark.parametrize("name", NAMES)
def test_strength_bounds_on_signal_bars(name):
    """Features that measure 'how far past the rule' respect the rule wherever it fired (locked levels)."""
    n_checked = 0
    for seed in (1, 2, 3):
        df = synth(12000 if name == "N11_BREAKAWAY" else 3000, seed)
        st = SD[name].strength(df, "1h")
        lg, sh = PD[name].signals(df, "1h")
        post = np.arange(len(df)) >= WARM
        for f, (lo_b, lo_strict, hi_b, hi_strict) in BOUNDS[name].items():
            x = np.r_[st[f][0][lg & post], st[f][1][sh & post]]
            assert not np.isnan(x).any(), (f, seed)
            if lo_b is not None:
                assert ((x > lo_b) if lo_strict else (x >= lo_b - EPS)).all(), (f, seed, x.min())
            if hi_b is not None:
                assert ((x < hi_b) if hi_strict else (x <= hi_b + EPS)).all(), (f, seed, x.max())
            n_checked += len(x)
    assert n_checked > 0


def test_n05_values(bars):
    df = bars
    st = SD["N05_PSAR_POC"].strength(df, "1h")
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    a = fg.atr(df, 14).to_numpy(float)
    poc = poc_series(df, 100, 32)
    sar = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)[0].to_numpy(float)
    for i in (400, 1234, 2999):
        assert math.isclose(st["poc_bounce_atr"][0][i], (c[i] - poc[i]) / a[i], rel_tol=1e-12)
        assert math.isclose(st["sar_gap_atr"][1][i], (sar[i] - c[i]) / a[i], rel_tol=1e-12)
        o1, c1 = o[i - 1], c[i - 1]
        pl, ps = st["pierce_depth"]
        if c1 < o1:
            assert math.isclose(pl[i], (c[i] - c1) / (o1 - c1), rel_tol=1e-12) and np.isnan(ps[i])
        else:
            assert np.isnan(pl[i])


def test_n06_opening_range(bars):
    """The opening range is the first bar of each UTC date, NaN on that bar, carried through the day."""
    oh, ol = SD["N06_MACD_ORB"].opening_range(bars)
    ts = pd.to_datetime(bars["ts"], utc=True)
    first = (ts.dt.hour == 0).to_numpy()          # 1h synthetic bars start at midnight
    assert np.isnan(oh[first]).all() and np.isnan(ol[first]).all()
    for i in (25, 47, 1000, 2999):
        j = i - ts.iloc[i].hour
        assert oh[i] == bars["high"].iloc[j] and ol[i] == bars["low"].iloc[j]


def test_n11_values(long_bars):
    df = long_bars
    st = SD["N11_BREAKAWAY"].strength(df, "1h")
    b = (df["close"] - df["open"]).to_numpy(float)
    a = fg.atr(df, 14).to_numpy(float)
    for i in (500, 7777, 11999):
        assert math.isclose(st["reversal_body_atr"][0][i], b[i] / a[i], rel_tol=1e-12)
        assert math.isclose(st["first_body_atr"][1][i], b[i - 4] / a[i], rel_tol=1e-12)
        assert math.isclose(st["pause_body_atr"][0][i], max(abs(b[i - 2]), abs(b[i - 1])) / a[i], rel_tol=1e-12)


def test_n13_pattern_unique_and_read_on_pattern_bar(bars):
    mod = SD["N13_3OUTSIDE"]
    df = bars
    bull, bear, a = mod.patterns(df)
    for pat in (bull, bear):
        idx = np.flatnonzero(pat)
        assert pat.any() and (np.diff(idx) >= 3).all()
    st = mod.strength(df, "1h")
    lg, sh = PD["N13_3OUTSIDE"].signals(df, "1h")
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    checked = 0
    for side, sig, pat in ((0, lg, bull), (1, sh, bear)):
        sgn = 1.0 if side == 0 else -1.0
        for i in np.flatnonzero(sig):
            j = i - 1 if pat[i - 1] else i - 2
            assert pat[j]
            assert math.isclose(st["engulf_body_atr"][side][i], sgn * (c[j - 1] - o[j - 1]) / a[j], rel_tol=1e-12)
            assert math.isclose(st["confirm_close_atr"][side][i], sgn * (c[j] - c[j - 1]) / a[j], rel_tol=1e-12)
            lvl = h[j - 2:j + 1].max() if side == 0 else lo[j - 2:j + 1].min()
            assert math.isclose(st["breakout_atr"][side][i], sgn * (c[i] - lvl) / a[i], rel_tol=1e-12)
            checked += 1
    assert checked > 0
    near = np.zeros(len(df), bool)
    for k in (1, 2):
        near[k:] |= bull[:-k]
    assert np.isnan(st["engulf_body_atr"][0][~near]).all()


def test_mirrored_features(bars, long_bars):
    pairs = {"N05_PSAR_POC": ["poc_bounce_atr", "sar_gap_atr"],
             "N06_MACD_ORB": ["macd_line_atr", "macd_hist_atr"],
             "N11_BREAKAWAY": ["reversal_body_atr", "first_body_atr"]}
    for name, feats in pairs.items():
        st = SD[name].strength(_df_for(name, bars, long_bars), "1h")
        for f in feats:
            vl, vs = st[f]
            ok = ~np.isnan(vl)
            assert np.array_equal(ok, ~np.isnan(vs)), (name, f)
            assert np.allclose(vl[ok], -vs[ok]), (name, f)
    vl, vs = SD["N11_BREAKAWAY"].strength(long_bars, "1h")["pause_body_atr"]
    assert np.array_equal(vl, vs, equal_nan=True)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("n", [0, 1, 2, 5, 30, 120])
def test_nan_safety_short_series(name, n):
    df = synth(max(n, 1), 7).iloc[:n].reset_index(drop=True)
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert vl.shape == (n,) and vs.shape == (n,)
        assert vl.dtype == float and vs.dtype == float
        assert not np.isinf(vl).any() and not np.isinf(vs).any()
    lg, sh = PD[name].signals(df, "1h")
    assert lg.shape == (n,) and sh.shape == (n,) and lg.dtype == bool and sh.dtype == bool


@pytest.mark.parametrize("name", NAMES)
def test_nan_safety_flat_and_gappy_bars(name):
    df = synth(900, 11)
    df.loc[200:330, ["open", "high", "low", "close"]] = 50.0     # flat stretch: POC window H == L, bodies 0
    df.loc[400:410, "volume"] = 0.0                              # zero volume in the profile window
    df = df.drop(index=range(600, 640)).reset_index(drop=True)   # a data gap (missing hours)
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert not np.isinf(vl).any() and not np.isinf(vs).any()
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df)
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", [3, 4])
def test_strength_causal(name, seed):
    df = synth(1500, seed, freq="15min")
    full = SD[name].strength(df, "15m")
    rng = np.random.default_rng(seed)
    for k in sorted(rng.integers(20, len(df) - 1, size=5)):
        part = SD[name].strength(df.iloc[:k].reset_index(drop=True), "15m")
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
    df = synth(3000, seed)
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df)
    assert lg.dtype == bool and sh.dtype == bool
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)
    assert not (lg & sh).any()


@pytest.mark.parametrize("name", NAMES)
def test_default_signals_equal_locked_other_tf(name):
    df = synth(4000, 8, freq="15min")
    lg, sh = PD[name].signals(df, "15m")
    rl, rs = _locked(name, df)
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)


def test_n11_default_equals_locked_long(long_bars):
    lg, sh = PD["N11_BREAKAWAY"].signals(long_bars, "1h")
    rl, rs = _locked("N11_BREAKAWAY", long_bars)
    assert lg.sum() > 0 and sh.sum() > 0
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)


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
        assert "third_party/sweep/harness/vendor/ports12.py:" in p["where"]
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
    assert got["N05_PSAR_POC"] == {
        "poc_lookback": [50, 75, 125, 150], "poc_tol": [0.1, 0.15, 0.25, 0.3],
        "pierce_frac": [0.25, 0.375, 0.625, 0.75], "sar_af": [0.01, 0.015, 0.025, 0.03]}
    assert got["N06_MACD_ORB"] == {
        "macd_fast": [6, 9, 15, 18], "macd_slow": [13, 20, 33, 39],        # 19.5 -> 20, 32.5 -> 33 (half up)
        "macd_signal": [5, 7, 11, 14], "ext_cap": [0.75, 1.125, 1.875, 2.25]}  # 4.5 -> 5, 6.75 -> 7, 11.25 -> 11
    assert got["N11_BREAKAWAY"] == {
        "big_body": [0.4, 0.6, 1.0, 1.2], "small_body": [0.2, 0.3, 0.5, 0.6],
        "gap_tol": [0.025, 0.0375, 0.0625, 0.075], "prior_n": [3, 4, 6, 8]}  # 2.5 -> 3, 3.75 -> 4, 7.5 -> 8
    assert got["N13_3OUTSIDE"] == {
        "engulf_min": [0.25, 0.375, 0.625, 0.75], "prior_n": [3, 4, 6, 8],
        "atr_len": [7, 11, 18, 21]}                                         # 10.5 -> 11, 17.5 -> 18


@pytest.mark.parametrize("name", NAMES)
def test_variants_run_and_move_signals(name, bars, long_bars):
    df = _df_for(name, bars, long_bars)
    mod = PD[name]
    base = mod.signals(df, "1h")
    moved = total = 0
    for p in mod.PARAMS:
        moved_p = 0
        for ov in mod.variants(p):
            lg, sh = mod.signals(df, "1h", **ov)
            assert lg.shape == (len(df),) and lg.dtype == bool and sh.dtype == bool
            assert not (lg & sh).any()
            total += 1
            moved_p += int(not (np.array_equal(lg, base[0]) and np.array_equal(sh, base[1])))
        assert moved_p >= 1, p["name"]            # every parameter reaches the rule
        moved += moved_p
    assert moved >= total * 3 // 4, (moved, total)


@pytest.mark.parametrize("name", NAMES)
def test_explicit_defaults_equal_no_overrides(name, bars):
    mod = PD[name]
    a = mod.signals(bars, "1h")
    b = mod.signals(bars, "1h", **{p["name"]: p["default"] for p in mod.PARAMS})
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


# ---- the overrides reach the intended number of the locked expression
def test_n05_threading(bars):
    df = bars
    lb, tol, fr, af = 150, 0.3, 0.375, 0.03
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = fg.atr(df, 14).to_numpy(float)
    poc = poc_series(df, lb, 32)
    ps = fg_fast.parabolic_sar(df, af, af, 0.2)[0].to_numpy(float)
    o1, c1 = _sh(o, 1), _sh(c, 1)
    with np.errstate(invalid="ignore"):
        sup = (np.abs(lo - poc) <= tol * a) | ((lo <= poc) & (poc <= c))
        res = (np.abs(h - poc) <= tol * a) | ((c <= poc) & (poc <= h))
        mid = fr * o1 + (1.0 - fr) * c1                 # fraction fr of the previous body taken back
        pierce = (c1 < o1) & (c > o) & (c >= mid) & (c < o1)
        dark = (c1 > o1) & (c < o) & (c <= mid) & (c > o1)
        long = sup & pierce & (c > ps)
        short = res & dark & (c < ps) & ~long
    lg, sh = PD["N05_PSAR_POC"].signals(df, "1h", poc_lookback=lb, poc_tol=tol, pierce_frac=fr, sar_af=af)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_n05_pierce_frac_half_is_midpoint():
    """f * o1 + (1 - f) * c1 at f = 0.5 is bit-identical to the locked (o1 + c1) / 2."""
    rng = np.random.default_rng(0)
    o1 = rng.uniform(1e-3, 1e5, 200000)
    c1 = o1 * rng.uniform(0.9, 1.1, 200000)
    assert np.array_equal(0.5 * o1 + (1.0 - 0.5) * c1, (o1 + c1) / 2.0)


def test_n06_threading(bars):
    df = bars
    fa, sl_, sg, cap = 9, 33, 5, 0.75
    h, lo, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a = fg.atr(df, 14).to_numpy(float)
    oh, ol = SD["N06_MACD_ORB"].opening_range(df)
    c1 = _sh(c, 1)
    ml, sl, hist = fg.macd(df["close"], fa, sl_, sg)
    mu, md = cross_above(ml, sl), cross_below(ml, sl)
    hs, mlf = hist.to_numpy(float), ml.to_numpy(float)
    hs1 = _sh(hs, 1)
    with np.errstate(invalid="ignore"):
        bu, bd = (c > oh) & (c1 <= oh), (c < ol) & (c1 >= ol)
        long = recent(bu, 2) & recent(mu, 2) & (mlf > 0) & (hs > 0) & (hs >= hs1) & ((c - oh) <= cap * a) & (bu | mu)
        short = recent(bd, 2) & recent(md, 2) & (mlf < 0) & (hs < 0) & (hs <= hs1) & ((ol - c) <= cap * a) & (bd | md)
    short &= ~long
    lg, sh = PD["N06_MACD_ORB"].signals(df, "1h", macd_fast=fa, macd_slow=sl_, macd_signal=sg, ext_cap=cap)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_n11_threading(long_bars):
    df = long_bars
    big, small, gap, pn = 0.6, 0.5, 0.075, 3
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    a = fg.atr(df, 14).to_numpy(float)
    b = c - o
    B1, B2, B3, B4 = _sh(b, 4), _sh(b, 3), _sh(b, 2), _sh(b, 1)
    O2, C1, C2 = _sh(o, 3), _sh(c, 4), _sh(c, 3)
    last, first = _sh(c, 5), _sh(c, 4 + pn)
    with np.errstate(invalid="ignore"):
        small34 = (np.abs(B3) <= small * a) & (np.abs(B4) <= small * a)
        long = (last < first) & (B1 < 0) & (-B1 >= big * a) & (B2 < 0) & (O2 <= C1 + gap * a) & small34 \
            & (b > 0) & (b >= big * a) & (c > C2)
        short = (last > first) & (B1 > 0) & (B1 >= big * a) & (B2 > 0) & (O2 >= C1 - gap * a) & small34 \
            & (b < 0) & (-b >= big * a) & (c < C2)
    short &= ~long
    lg, sh = PD["N11_BREAKAWAY"].signals(df, "1h", big_body=big, small_body=small, gap_tol=gap, prior_n=pn)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_n13_threading(bars):
    df = bars
    em, pn, al = 0.375, 8, 21
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = fg.atr(df, al).to_numpy(float)
    b = c - o
    last, first = _sh(c, 3), _sh(c, 2 + pn)
    B1, B2 = _sh(b, 2), _sh(b, 1)
    O1, C1, O2, C2 = _sh(o, 2), _sh(c, 2), _sh(o, 1), _sh(c, 1)
    with np.errstate(invalid="ignore"):
        bull = (last < first) & (B1 < 0) & (B2 > 0) & (B2 >= em * a) & (O2 <= C1) & (C2 >= O1) & (b > 0) & (c > C2)
        bear = (last > first) & (B1 > 0) & (B2 < 0) & (-B2 >= em * a) & (O2 >= C1) & (C2 <= O1) & (b < 0) & (c < C2)
    n = len(df)
    long, short = np.zeros(n, bool), np.zeros(n, bool)
    for i in range(3, n):
        for j in (i - 1, i - 2):
            if bull[j]:
                lvl = h[j - 2:j + 1].max()
                long[i] |= bool(c[i] > lvl and c[i - 1] <= lvl)
            if bear[j]:
                lvl = lo[j - 2:j + 1].min()
                short[i] |= bool(c[i] < lvl and c[i - 1] >= lvl)
    short &= ~long
    lg, sh = PD["N13_3OUTSIDE"].signals(df, "1h", engulf_min=em, prior_n=pn, atr_len=al)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


@pytest.mark.parametrize("name", NAMES)
def test_unknown_override_rejected(name, bars):
    with pytest.raises(ValueError):
        PD[name].signals(bars, "1h", not_a_param=1)
