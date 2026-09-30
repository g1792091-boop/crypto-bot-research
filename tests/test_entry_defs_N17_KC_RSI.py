"""Entry-study definitions (PREREG_ENTRY.md sections 3 B / 4 C) of the batch
N17_KC_RSI, N18_VWMA_MACD, N21_ST_RSI_ADX, N22_VORTEX_PSAR:
research/entry_study/strength_defs/<NAME>.py and research/entry_study/param_defs/<NAME>.py.

Synthetic bars only (no data files, no network): schema, shapes, NaN-safety, causality of strength(),
default signals() == the locked strategy function, and the variant rules."""

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
import strategies as S  # noqa: E402  (vendored locked code, on sys.path after lib())

NAMES = ["N17_KC_RSI", "N18_VWMA_MACD", "N21_ST_RSI_ADX", "N22_VORTEX_PSAR"]
KINDS = {"length", "mult", "threshold_neutral", "threshold_abs"}
MULTS = (0.5, 0.75, 1.25, 1.5)
WARM = 300


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_n17batch_{kind}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = {n: _load("strength_defs", n) for n in NAMES}
PD = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int, seed: int, freq: str = "1h") -> pd.DataFrame:
    """Random walk with drifting regimes and occasional shocks (band touches, RSI extremes, crosses)."""
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


def _locked(name, df):
    long, short = S.CANDIDATES_15M[name](df)
    return L._clean(long, short, len(df))


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
def test_strength_shapes_and_finite_at_signals(name, bars):
    st = SD[name].strength(bars, "1h")
    assert list(st) == [f["name"] for f in SD[name].FEATURES]
    lg, sh = PD[name].signals(bars, "1h")
    post = np.arange(len(bars)) >= WARM
    for f, (vl, vs) in st.items():
        for v in (vl, vs):
            assert isinstance(v, np.ndarray) and v.dtype == float and v.shape == (len(bars),)
            assert not np.isinf(v).any()
        assert np.isfinite(vl[lg & post]).all(), f
        assert np.isfinite(vs[sh & post]).all(), f


@pytest.mark.parametrize("name", ["N17_KC_RSI", "N18_VWMA_MACD", "N22_VORTEX_PSAR"])
def test_signals_fire_on_synthetic_bars(name, bars):
    lg, sh = PD[name].signals(bars, "1h")
    assert lg.sum() > 0 and sh.sum() > 0


def test_strength_bounds_on_signal_bars():
    """Features that measure 'how far past the rule' respect the rule wherever it fired."""
    bounds = {"N17_KC_RSI": {"rsi_depth": 0.0, "band_pierce_atr": -0.10 - 1e-9},
              "N21_ST_RSI_ADX": {"rsi_extreme": 0.0, "adx_cross_size": 0.0},
              "N22_VORTEX_PSAR": {"vi_spread": 0.0, "psar_dist_atr": 0.0, "psar_age_bars": 0.0}}
    for seed in (1, 2, 3):
        df = synth(3000, seed)
        for name, fb in bounds.items():
            st = SD[name].strength(df, "1h")
            lg, sh = PD[name].signals(df, "1h")
            for f, b in fb.items():
                x = np.r_[st[f][0][lg], st[f][1][sh]]
                x = x[~np.isnan(x)]
                assert (x >= b).all(), (name, f, seed)


def test_n17_window_matches_sync_rule(bars):
    """rsi_depth / band_pierce_atr take the extreme of bars i-2 .. i, so on every N17 signal bar the RSI
    condition and the band touch are each met somewhere in that window (and nowhere earlier is used)."""
    import fg_indicators as fg
    st = SD["N17_KC_RSI"].strength(bars, "1h")
    r = fg.rsi(bars["close"], 14).to_numpy(float)
    mid = fg.ema(bars["close"], 20).to_numpy(float)
    a = fg.atr(bars, 14).to_numpy(float)
    lower = mid - 2.0 * a
    lg, _sh = PD["N17_KC_RSI"].signals(bars, "1h")
    for i in np.flatnonzero(lg)[:200]:
        if i < WARM:
            continue
        w = slice(i - 2, i + 1)
        assert math.isclose(st["rsi_depth"][0][i], 30.0 - np.nanmin(r[w]), abs_tol=1e-9)
        assert math.isclose(st["band_pierce_atr"][0][i],
                            np.nanmax((lower[w] - bars["low"].to_numpy(float)[w]) / a[w]), abs_tol=1e-9)


def test_n18_mirrored(bars):
    st = SD["N18_VWMA_MACD"].strength(bars, "1h")
    for f, (vl, vs) in st.items():
        ok = ~np.isnan(vl)
        assert np.array_equal(ok, ~np.isnan(vs)), f
        assert np.allclose(vl[ok], -vs[ok]), f


def test_n21_st_side_and_adx_symmetry(bars):
    import fg_fast
    st = SD["N21_ST_RSI_ADX"].strength(bars, "1h")
    d = fg_fast.supertrend(bars, 10, 6.0)[1].to_numpy(float)
    with np.errstate(invalid="ignore"):
        up, dn = d > 0, d < 0
    dl, ds = st["st_line_dist_atr"]
    assert np.array_equal(~np.isnan(dl), up & ~np.isnan(dl)) and not np.isnan(dl[up][20:]).any()
    assert np.array_equal(~np.isnan(ds), dn & ~np.isnan(ds)) and not np.isnan(ds[dn][20:]).any()
    assert (dl[up & ~np.isnan(dl)] >= 0).all() and (ds[dn & ~np.isnan(ds)] >= 0).all()
    al, as_ = st["adx_cross_size"]
    assert np.array_equal(al, as_, equal_nan=True)


def test_n22_psar_age_counts_runs(bars):
    import fg_fast
    st = SD["N22_VORTEX_PSAR"].strength(bars, "1h")
    ps = fg_fast.parabolic_sar(bars, 0.02, 0.02, 0.20)[0].to_numpy(float)
    c = bars["close"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        above = c > ps
    age = st["psar_age_bars"][0]
    assert np.isnan(age[~above]).all()
    # first observed move above the SAR (SAR exists from bar 1, so a change of side needs bar >= 2)
    first_start = np.flatnonzero(above[2:] & ~above[1:-1])[0] + 2
    assert np.isnan(age[:first_start]).all()
    for i in range(first_start, len(c)):
        if above[i]:
            assert age[i] == (0 if not above[i - 1] else age[i - 1] + 1)


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
    df.loc[200:260, ["open", "high", "low", "close"]] = 50.0      # flat stretch: ATR -> 0, RSI 50
    df.loc[300:310, "volume"] = 0.0                               # zero volume (VWMA denominator)
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
        assert "third_party/sweep/harness/vendor/strategies.py:" in p["where"]
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
                assert math.isclose(v[p["name"]], _expected(p, m), rel_tol=0, abs_tol=1e-12)
                if p["kind"] == "length":
                    assert isinstance(v[p["name"]], int) and v[p["name"]] >= 2


def test_variant_values_spelled_out():
    """The concrete numbers the runner will use (PREREG 4)."""
    got = {n: {p["name"]: [v[p["name"]] for v in PD[n].variants(p)] for p in PD[n].PARAMS} for n in NAMES}
    assert got["N17_KC_RSI"]["kc_len"] == [10, 15, 25, 30]
    assert got["N17_KC_RSI"]["rsi_len"] == [7, 11, 18, 21]          # 10.5 -> 11, 17.5 -> 18 (half up)
    assert np.allclose(got["N17_KC_RSI"]["kc_mult"], [1.0, 1.5, 2.5, 3.0])
    assert np.allclose(got["N17_KC_RSI"]["rsi_level"], [40.0, 35.0, 25.0, 20.0])
    assert got["N18_VWMA_MACD"]["macd_fast"] == [6, 9, 15, 18]
    assert got["N18_VWMA_MACD"]["macd_slow"] == [13, 20, 33, 39]    # 19.5 -> 20, 32.5 -> 33
    assert got["N18_VWMA_MACD"]["macd_signal"] == [5, 7, 11, 14]    # 4.5 -> 5, 6.75 -> 7, 11.25 -> 11, 13.5 -> 14
    assert np.allclose(got["N21_ST_RSI_ADX"]["adx_level"], [12.5, 18.75, 31.25, 37.5])
    assert np.allclose(got["N21_ST_RSI_ADX"]["st_mult"], [3.0, 4.5, 7.5, 9.0])
    assert np.allclose(got["N22_VORTEX_PSAR"]["psar_max"], [0.10, 0.15, 0.25, 0.30])


@pytest.mark.parametrize("name", NAMES)
def test_variants_run_and_move_signals(name, bars):
    mod = PD[name]
    base = mod.signals(bars, "1h")
    moved = 0
    for p in mod.PARAMS:
        for ov in mod.variants(p):
            lg, sh = mod.signals(bars, "1h", **ov)
            assert lg.shape == (len(bars),) and lg.dtype == bool and sh.dtype == bool
            assert not (lg & sh).any()
            moved += int(not (np.array_equal(lg, base[0]) and np.array_equal(sh, base[1])))
    if name != "N21_ST_RSI_ADX":          # N21 rarely fires at all; checked on relaxed levels below
        assert moved >= 12


def test_n21_levels_reach_the_rule():
    """N21 almost never fires with the locked levels (also on real bars); on these synthetic series widened
    levels make it fire on both sides, and the re-implementation matches a direct evaluation of the locked
    expression with those levels threaded in."""
    import fg_fast
    import fg_indicators as fg
    from strategies import _b, cross_below, gt, lt
    ov = dict(adx_level=37.5, rsi_level=40.0, st_mult=9.0)
    n_long = n_short = 0
    for seed in (0, 3):
        df = synth(6000, seed)
        lg, sh = PD["N21_ST_RSI_ADX"].signals(df, "1h", **ov)
        up = _b(fg_fast.supertrend_v2(df, 10, 9.0)[1])
        r = fg.rsi(df["close"], 14)
        x = cross_below(fg.adx_dmi(df, 14)[0], 37.5)
        short = ~up & x & gt(r, 60.0) & lt(r, r.shift(1))
        long = up & x & lt(r, 40.0) & gt(r, r.shift(1)) & ~short
        assert np.array_equal(lg, long) and np.array_equal(sh, short & ~long)
        n_long += int(lg.sum())
        n_short += int(sh.sum())
    assert n_long > 0 and n_short > 0


@pytest.mark.parametrize("name", NAMES)
def test_unknown_override_rejected(name, bars):
    with pytest.raises(ValueError):
        PD[name].signals(bars, "1h", not_a_param=1)
