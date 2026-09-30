"""Entry-study definitions (PREREG_ENTRY.md sections 3 B / 4 C) of the batch
S1_EMA_RSI_CHOP, S3_CMO_SANDWICH, S4_BB_BBP, N04_ST_KLINGER:
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
from strategies import cross_above, cross_below, ge, gt, le, lt, recent, shift_bool  # noqa: E402

NAMES = ["S1_EMA_RSI_CHOP", "S3_CMO_SANDWICH", "S4_BB_BBP", "N04_ST_KLINGER"]
KINDS = {"length", "mult", "threshold_neutral", "threshold_abs"}
MULTS = (0.5, 0.75, 1.25, 1.5)
WARM = 300


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_s1batch_{kind}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = {n: _load("strength_defs", n) for n in NAMES}
PD = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int, seed: int, freq: str = "1h") -> pd.DataFrame:
    """Random walk with drifting regimes and occasional shocks (band breaks, RSI extremes, crosses)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.004, n // 150 + 1), 150)[:n]
    shock = np.where(rng.random(n) < 0.01, rng.normal(0, 0.05, n), 0.0)
    c = 100 * np.exp(np.cumsum(drift + shock + rng.normal(0, 0.01, n)))
    o = np.r_[100.0, c[:-1]]
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
    """S1 needs three events inside 3 bars and fires rarely; a long series gives it signals."""
    return synth(20000, 3)


def _locked(name, df):
    p = ports12.PORTS12[name](df)
    return L._clean(p["L"], p["S"], len(df))


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
    df = long_bars if name == "S1_EMA_RSI_CHOP" else bars
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


@pytest.mark.parametrize("name", NAMES)
def test_signals_fire_on_synthetic_bars(name, bars, long_bars):
    df = long_bars if name == "S1_EMA_RSI_CHOP" else bars
    lg, sh = PD[name].signals(df, "1h")
    assert lg.sum() > 0 and sh.sum() > 0


def test_strength_bounds_on_signal_bars():
    """Features that measure 'how far past the rule' respect the rule wherever it fired (locked levels).
    Bounds: (lower, lower is strict, upper or None)."""
    eps = 1e-9
    bounds = {
        "S1_EMA_RSI_CHOP": {"rsi_extreme": (0.0, True, None), "ema_gap_atr": (0.0, True, None),
                            "chop_angle_deg": (1.0 - eps, False, None)},
        "S3_CMO_SANDWICH": {"cmo_level": (0.0, True, None), "sandwich_match_atr": (0.0, False, 0.3 + eps),
                            "prior_move_atr": (0.0, True, None)},
        "S4_BB_BBP": {"band_break_atr": (0.0, True, None), "squeeze_ratio": (0.0, False, 1.0 + eps),
                      "bbp_atr": (0.0, True, None)},
        "N04_ST_KLINGER": {"st_dist_atr": (0.0, False, None)},
    }
    n_checked = {n: 0 for n in bounds}
    for seed in (1, 2, 3):
        for name, fb in bounds.items():
            df = synth(20000 if name == "S1_EMA_RSI_CHOP" else 3000, seed)
            st = SD[name].strength(df, "1h")
            lg, sh = PD[name].signals(df, "1h")
            post = np.arange(len(df)) >= WARM
            for f, (lo_b, strict, hi_b) in fb.items():
                x = np.r_[st[f][0][lg & post], st[f][1][sh & post]]
                assert not np.isnan(x).any(), (name, f, seed)
                assert ((x > lo_b) if strict else (x >= lo_b)).all(), (name, f, seed)
                if hi_b is not None:
                    assert (x <= hi_b).all(), (name, f, seed)
                n_checked[name] += len(x)
    assert all(v > 0 for v in n_checked.values()), n_checked


def test_s1_rsi_window(long_bars):
    """rsi_extreme is the most extreme RSI of bars i-3 .. i (an RSI hook on bar j in i-2 .. i reads RSI[j-1]);
    on every signal bar an RSI below 30 (above 70) lies in that window."""
    st = SD["S1_EMA_RSI_CHOP"].strength(long_bars, "1h")
    r = fg.rsi(long_bars["close"], 14).to_numpy(float)
    lg, sh = PD["S1_EMA_RSI_CHOP"].signals(long_bars, "1h")
    for i in np.flatnonzero(lg):
        if i >= WARM:
            assert math.isclose(st["rsi_extreme"][0][i], 30.0 - r[i - 3:i + 1].min(), abs_tol=1e-9)
            assert r[i - 3:i].min() < 30.0
    for i in np.flatnonzero(sh):
        if i >= WARM:
            assert math.isclose(st["rsi_extreme"][1][i], r[i - 3:i + 1].max() - 70.0, abs_tol=1e-9)
            assert r[i - 3:i].max() > 70.0


def test_s1_rsi_warmup_masked():
    df = synth(100, 4)
    vl, vs = SD["S1_EMA_RSI_CHOP"].strength(df, "1h")["rsi_extreme"]
    assert np.isnan(vl[:14]).all() and np.isnan(vs[:14]).all()     # locked RSI reads 0 there
    assert np.isfinite(vl[14:]).all()


def test_s3_pattern_read_on_latest_pattern_bar(bars):
    """sandwich_match_atr / prior_move_atr are read on the most recent pattern bar j in i-2 .. i."""
    df = bars
    mod = SD["S3_CMO_SANDWICH"]
    bull, bear, a, h, l, c = mod._patterns(df)
    st = mod.strength(df, "1h")
    lg, sh = PD["S3_CMO_SANDWICH"].signals(df, "1h")
    checked = 0
    for side, sig, pat in ((0, lg, bull), (1, sh, bear)):
        for i in np.flatnonzero(sig):
            if i < WARM:
                continue
            j = max(k for k in (i - 2, i - 1, i) if pat[k])
            if side == 0:
                match, prior = abs(l[j - 2] - l[j]) / a[j], (c[j - 7] - c[j - 3]) / a[j]
            else:
                match, prior = abs(h[j - 2] - h[j]) / a[j], (c[j - 3] - c[j - 7]) / a[j]
            assert math.isclose(st["sandwich_match_atr"][side][i], match, abs_tol=1e-12)
            assert math.isclose(st["prior_move_atr"][side][i], prior, abs_tol=1e-12)
            checked += 1
    assert checked > 0
    # outside any pattern window the pattern features are missing
    no_bull = ~recent(bull, 3)
    assert np.isnan(st["sandwich_match_atr"][0][no_bull]).all()
    assert np.isnan(st["prior_move_atr"][1][~recent(bear, 3)]).all()


def test_s4_squeeze_window(bars):
    st = SD["S4_BB_BBP"].strength(bars, "1h")
    sl, ss = st["squeeze_ratio"]
    assert np.array_equal(sl, ss, equal_nan=True)
    _up, _mid, _lo, bw = fg.bollinger_bands(bars["close"], 20, 2.0)
    thr = fg.rolling_percentile_threshold(bw, 100, 0.2).to_numpy(float)
    ratio = bw.to_numpy(float) / thr
    for i in (500, 1234, 2999):
        assert math.isclose(sl[i], np.nanmin(ratio[i - 5:i]), abs_tol=1e-12)
    # squeeze on bars i-1..i-5 <=> min ratio <= 1 (thresholds are positive on these bars)
    sq_prev = recent(shift_bool(le(bw, thr), 1), 5)
    ok = np.isfinite(sl)
    assert np.array_equal(sq_prev[ok], sl[ok] <= 1.0)


def test_s4_squeeze_defined_after_flat_closes():
    """Flat closes give bandwidth 0 and, over enough of the 100-bar window, a threshold 0; the rule still
    counts that as a squeeze (0 <= 0), so the breakout signal after it must get a value (0), not NaN."""
    checked = 0
    for seed in range(6):
        df = synth(600, seed)
        df.loc[200:300, ["open", "high", "low", "close"]] = 50.0
        lg, sh = PD["S4_BB_BBP"].signals(df, "1h")
        sl, ss = SD["S4_BB_BBP"].strength(df, "1h")["squeeze_ratio"]
        for side, sig in ((sl, lg), (ss, sh)):
            x = side[sig & (np.arange(len(df)) >= WARM)]
            assert np.isfinite(x).all() and (x <= 1.0).all(), seed
        i = 301
        if lg[i] or sh[i]:
            assert (sl if lg[i] else ss)[i] == 0.0
            checked += 1
    assert checked > 0


def test_mirrored_features(bars):
    for name, feats in (("S4_BB_BBP", ["bbp_atr"]), ("N04_ST_KLINGER", ["kvo_gap_vol", "st_dist_atr"]),
                        ("S3_CMO_SANDWICH", ["cmo_level"]), ("S1_EMA_RSI_CHOP", ["ema_gap_atr", "chop_angle_deg"])):
        st = SD[name].strength(bars, "1h")
        for f in feats:
            vl, vs = st[f]
            ok = ~np.isnan(vl)
            assert np.array_equal(ok, ~np.isnan(vs)), (name, f)
            assert np.allclose(vl[ok], -vs[ok]), (name, f)


def test_n04_st_side(bars):
    st = SD["N04_ST_KLINGER"].strength(bars, "1h")
    d = fg_fast.supertrend(bars, 10, 6.0)[1].to_numpy(float)
    dl, ds = st["st_dist_atr"]
    with np.errstate(invalid="ignore"):
        up, dn = d > 0, d < 0
    assert (dl[up & ~np.isnan(dl)] >= 0).all() and (ds[dn & ~np.isnan(ds)] >= 0).all()


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
def test_nan_safety_flat_and_gappy_bars(name):
    df = synth(600, 11)
    df.loc[200:260, ["open", "high", "low", "close"]] = 50.0      # flat stretch: ATR -> 0, bandwidth 0
    df.loc[300:310, "volume"] = 0.0                               # zero volume (Klinger force, volume scale)
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
    df = synth(3000, seed)
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df)
    assert lg.dtype == bool and sh.dtype == bool
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)
    assert not (lg & sh).any()


def test_s1_default_equals_locked_long(long_bars):
    lg, sh = PD["S1_EMA_RSI_CHOP"].signals(long_bars, "1h")
    rl, rs = _locked("S1_EMA_RSI_CHOP", long_bars)
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
            d = p["default"]
            assert isinstance(d, int) or (isinstance(d, list) and all(isinstance(x, int) for x in d))


def _expected(p, m):
    d = p["default"]
    if p["kind"] == "length":
        f = lambda x: max(2, int(math.floor(x * m + 0.5)))  # noqa: E731
        return [f(x) for x in d] if isinstance(d, list) else f(d)
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
                    assert got == want
                    for x in (got if isinstance(got, list) else [got]):
                        assert isinstance(x, int) and x >= 2
                else:
                    assert math.isclose(got, want, rel_tol=0, abs_tol=1e-11)


def test_variant_values_spelled_out():
    """The concrete numbers the runner will use (PREREG 4)."""
    got = {n: {p["name"]: [v[p["name"]] for v in PD[n].variants(p)] for p in PD[n].PARAMS} for n in NAMES}
    assert got["S1_EMA_RSI_CHOP"] == {
        "ema_slow": [10, 15, 25, 30], "rsi_len": [7, 11, 18, 21],          # 10.5 -> 11, 17.5 -> 18 (half up)
        "rsi_level": [40.0, 35.0, 25.0, 20.0], "chop_len": [17, 26, 43, 51]}  # 25.5 -> 26, 42.5 -> 43
    assert got["S3_CMO_SANDWICH"] == {
        "cmo_len": [7, 11, 18, 21], "body_min": [0.04, 0.06, 0.1, 0.12],
        "match_tol": [0.15, 0.225, 0.375, 0.45], "prior_n": [3, 4, 6, 8]}   # 2.5 -> 3, 3.75 -> 4, 7.5 -> 8
    assert got["S4_BB_BBP"] == {
        "bb_len": [10, 15, 25, 30], "bb_mult": [1.0, 1.5, 2.5, 3.0],
        "sq_lookback": [50, 75, 125, 150], "sq_pct": [0.1, 0.15, 0.25, 0.3]}
    assert got["N04_ST_KLINGER"] == {
        "st_atr_len": [5, 8, 13, 15], "st_mult": [3.0, 4.5, 7.5, 9.0],
        "kvo_lens": [[17, 28], [26, 41], [43, 69], [51, 83]],             # 27.5 -> 28, 42.5 -> 43, 82.5 -> 83
        "kvo_signal_len": [7, 10, 16, 20]}                                # 6.5 -> 7, 9.75 -> 10, 16.25 -> 16


@pytest.mark.parametrize("name", NAMES)
def test_variants_run_and_move_signals(name, bars, long_bars):
    df = long_bars if name == "S1_EMA_RSI_CHOP" else bars
    mod = PD[name]
    base = mod.signals(df, "1h")
    moved = 0
    for p in mod.PARAMS:
        for ov in mod.variants(p):
            lg, sh = mod.signals(df, "1h", **ov)
            assert lg.shape == (len(df),) and lg.dtype == bool and sh.dtype == bool
            assert not (lg & sh).any()
            moved += int(not (np.array_equal(lg, base[0]) and np.array_equal(sh, base[1])))
    assert moved >= (8 if name == "S1_EMA_RSI_CHOP" else 14)


# ---- the overrides reach the intended number of the locked expression
def test_s1_threading(long_bars):
    df = long_bars
    es, rl, lvl, cl = 30, 7, 40.0, 51
    close = df["close"]
    e5, e20 = fg.ema(close, 5), fg.ema(close, es)
    r = fg.rsi(close, rl).to_numpy(float)
    r1 = np.r_[np.nan, r[:-1]]
    cz = fg.chop_zone_proxy(df, cl, 1.0, 5.0, 14)[1].to_numpy(float)
    cz1 = np.r_[np.nan, cz[:-1]]
    eu, ed = cross_above(e5, e20), cross_below(e5, e20)
    with np.errstate(invalid="ignore"):
        ru, rd = (r1 < lvl) & (r > r1), (r1 > 100 - lvl) & (r < r1)
        cu, cd = (cz1 <= 0) & (cz > 0), (cz1 >= 0) & (cz < 0)
        lst = (e5.to_numpy() > e20.to_numpy()) & (cz > 0)
        sst = (e5.to_numpy() < e20.to_numpy()) & (cz < 0)
    long = recent(eu, 3) & recent(ru, 3) & recent(cu, 3) & lst & (eu | ru | cu)
    short = recent(ed, 3) & recent(rd, 3) & recent(cd, 3) & sst & (ed | rd | cd) & ~long
    lg, sh = PD["S1_EMA_RSI_CHOP"].signals(df, "1h", ema_slow=es, rsi_len=rl, rsi_level=lvl, chop_len=cl)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_s3_threading(bars):
    df = bars
    cl, bm, tol, pn = 21, 0.04, 0.45, 8
    o, h, lo_, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = fg.atr(df, 14).to_numpy(float)
    sh_ = lambda x, k: np.r_[np.full(k, np.nan), x[:-k]]  # noqa: E731
    b = c - o
    b1, b2 = sh_(b, 2), sh_(b, 1)
    last, first = sh_(c, 3), sh_(c, 2 + pn)
    with np.errstate(invalid="ignore"):
        bodies = (np.abs(b1) >= bm * a) & (np.abs(b2) >= bm * a) & (np.abs(b) >= bm * a)
        bear = (last > first) & bodies & (b1 > 0) & (b2 < 0) & (b > 0) & (np.abs(sh_(h, 2) - h) <= tol * a) \
            & (c <= np.maximum(sh_(h, 2), h) + 0.075 * a)
        bull = (last < first) & bodies & (b1 < 0) & (b2 > 0) & (b < 0) & (np.abs(sh_(lo_, 2) - lo_) <= tol * a) \
            & (c >= np.minimum(sh_(lo_, 2), lo_) - 0.075 * a)
    cm = fg.cmo(df["close"], cl)
    cmu, cmd = cross_above(cm, 0.0), cross_below(cm, 0.0)
    long = recent(bull, 3) & recent(cmu, 3) & gt(cm, 0.0) & (bull | cmu)
    short = recent(bear, 3) & recent(cmd, 3) & lt(cm, 0.0) & (bear | cmd) & ~long
    lg, sh = PD["S3_CMO_SANDWICH"].signals(df, "1h", cmo_len=cl, body_min=bm, match_tol=tol, prior_n=pn)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_s4_threading(bars):
    df = bars
    bl, bmul, lb, pct = 30, 2.5, 150, 0.3
    close = df["close"]
    up, _mid, lo_, bw = fg.bollinger_bands(close, bl, bmul)
    sq = le(bw, fg.rolling_percentile_threshold(bw, lb, pct))
    sq_prev = recent(shift_bool(sq, 1), 5)
    bbp = fg.bull_bear_power(df, 13)[2]
    long = sq_prev & gt(close, up) & le(close.shift(1), up.shift(1)) & gt(bbp, 0.0)
    short = sq_prev & lt(close, lo_) & ge(close.shift(1), lo_.shift(1)) & lt(bbp, 0.0) & ~long
    lg, sh = PD["S4_BB_BBP"].signals(df, "1h", bb_len=bl, bb_mult=bmul, sq_lookback=lb, sq_pct=pct)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_n04_threading(bars):
    df = bars
    al, mul, lens, sig = 15, 3.0, [17, 28], 20
    d = fg_fast.supertrend(df, al, mul)[1].to_numpy(float)
    kl, ks = fg.klinger_oscillator(df, lens[0], lens[1], sig)
    up, dn = cross_above(kl, ks), cross_below(kl, ks)
    dp = np.r_[np.nan, d[:-1]]
    with np.errstate(invalid="ignore"):
        fu, fd = (d > 0) & (dp <= 0), (d < 0) & (dp >= 0)
    long = gt(d, 0) & recent(up, 2) & (up | fu)
    short = lt(d, 0) & recent(dn, 2) & (dn | fd) & ~long
    lg, sh = PD["N04_ST_KLINGER"].signals(df, "1h", st_atr_len=al, st_mult=mul, kvo_lens=lens, kvo_signal_len=sig)
    assert long.sum() > 0 and short.sum() > 0
    assert np.array_equal(lg, long) and np.array_equal(sh, short)


def test_n04_kvo_lens_validated(bars):
    with pytest.raises(ValueError):
        PD["N04_ST_KLINGER"].signals(bars, "1h", kvo_lens=[34])


@pytest.mark.parametrize("name", NAMES)
def test_unknown_override_rejected(name, bars):
    with pytest.raises(ValueError):
        PD[name].signals(bars, "1h", not_a_param=1)
