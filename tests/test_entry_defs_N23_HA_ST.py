"""Entry-study definitions (PREREG_ENTRY.md sections 3 B / 4 C) of the batch
N23_HA_ST, N24_DMI, N25_DST_CCI, OBV_S:
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

NAMES = ["N23_HA_ST", "N24_DMI", "N25_DST_CCI", "OBV_S"]
LOCKED = {"N23_HA_ST": S.n23_heikin_supertrend, "N24_DMI": S.n24_dmi,
          "N25_DST_CCI": S.n25_double_supertrend_cci, "OBV_S": S.obv_s}
KINDS = {"length", "mult", "threshold_neutral", "threshold_abs"}
MULTS = (0.5, 0.75, 1.25, 1.5)
WARM = 300


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_n23batch_{kind}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = {n: _load("strength_defs", n) for n in NAMES}
PD = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int, seed: int, freq: str = "1h") -> pd.DataFrame:
    """Random walk with drifting regimes and occasional shocks (supertrend flips, CCI extremes, DI crosses)."""
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
    long, short = LOCKED[name](df)
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


@pytest.mark.parametrize("name", NAMES)
def test_signals_fire_on_synthetic_bars(name):
    df = synth(6000, 2)
    lg, sh = PD[name].signals(df, "1h")
    assert lg.sum() > 0 and sh.sum() > 0


def test_strength_bounds_on_signal_bars():
    """Features that measure 'how far past the rule' respect the rule wherever it fired."""
    bounds = {"N23_HA_ST": {"ha_body_atr": 0.0, "st_line_dist_atr": 0.0, "st_age_bars": 0.0},
              "N24_DMI": {"adx_margin": 0.0, "di_spread": 0.0},
              "N25_DST_CCI": {"cci_cross_size": 0.0, "cci_dip_depth": 0.0, "st_agree_count": 1.0},
              "OBV_S": {"obv_gap_vol": 0.0, "ac_atr": 0.0, "stc_room": 0.0}}
    strict = {("N23_HA_ST", "ha_body_atr"), ("N24_DMI", "di_spread"), ("N25_DST_CCI", "cci_cross_size"),
              ("OBV_S", "obv_gap_vol"), ("OBV_S", "ac_atr"), ("OBV_S", "stc_room")}
    for seed in (1, 2, 3):
        df = synth(4000, seed)
        post = np.arange(len(df)) >= WARM
        for name, fb in bounds.items():
            st = SD[name].strength(df, "1h")
            lg, sh = PD[name].signals(df, "1h")
            for f, b in fb.items():
                x = np.r_[st[f][0][lg & post], st[f][1][sh & post]]
                assert not np.isnan(x).any(), (name, f, seed)
                assert ((x > b) if (name, f) in strict else (x >= b)).all(), (name, f, seed)


def test_n23_values(bars):
    import fg_fast
    import fg_indicators as fg
    st = SD["N23_HA_ST"].strength(bars, "1h")
    ha = fg_fast.heikin_ashi(bars)
    atr = fg.atr(bars, 14).to_numpy(float)
    body = (ha["ha_close"] - ha["ha_open"]).to_numpy(float) / atr
    ok = np.isfinite(body)
    assert np.allclose(st["ha_body_atr"][0][ok], body[ok]) and np.allclose(st["ha_body_atr"][1][ok], -body[ok])
    d = fg_fast.supertrend(bars, 10, 6.0)[1].to_numpy(float)
    with np.errstate(invalid="ignore"):
        up = d > 0
    age = st["st_age_bars"][0]
    assert np.isnan(age[~up]).all()
    first = np.flatnonzero(up[1:] & (d[:-1] < 0))[0] + 1
    for i in range(first, len(d)):
        if up[i]:
            assert age[i] == (0 if not up[i - 1] else age[i - 1] + 1)


def test_n24_values(bars):
    import fg_indicators as fg
    st = SD["N24_DMI"].strength(bars, "1h")
    adx, plus, minus = (x.to_numpy(float) for x in fg.adx_dmi(bars, 14))
    ok = np.isfinite(adx)
    assert np.allclose(st["adx_margin"][0][ok], adx[ok] - 25) and np.allclose(st["adx_margin"][1][ok], 25 - adx[ok])
    ok = np.isfinite(plus - minus)
    assert np.allclose(st["di_spread"][0][ok], (plus - minus)[ok])
    assert np.allclose(st["di_spread"][1][ok], (minus - plus)[ok])


def test_n25_dip_depth_is_run_extreme(bars):
    import fg_fast
    st = SD["N25_DST_CCI"].strength(bars, "1h")
    c = fg_fast.cci(bars, 20).to_numpy(float)
    dl, ds = st["cci_dip_depth"]
    for i in range(1, len(c)):
        if np.isfinite(c[i - 1]) and c[i - 1] <= -100:
            j = i - 1
            while j - 1 >= 0 and np.isfinite(c[j - 1]) and c[j - 1] <= -100:
                j -= 1
            assert math.isclose(dl[i], -100 - c[j:i].min(), abs_tol=1e-9)
        else:
            assert np.isnan(dl[i])
        if np.isfinite(c[i - 1]) and c[i - 1] >= 100:
            j = i - 1
            while j - 1 >= 0 and np.isfinite(c[j - 1]) and c[j - 1] >= 100:
                j -= 1
            assert math.isclose(ds[i], c[j:i].max() - 100, abs_tol=1e-9)
        else:
            assert np.isnan(ds[i])
    agree_l, agree_s = st["st_agree_count"]
    ok = ~np.isnan(agree_l)
    assert np.array_equal(ok, ~np.isnan(agree_s)) and np.allclose(agree_l[ok] + agree_s[ok], 2.0)
    assert set(np.unique(agree_l[ok])) <= {0.0, 1.0, 2.0}


def test_obv_s_gap_invariant_to_obv_start(bars):
    """OBV's level depends on where the series starts; the OBV - SMA30(OBV) gap does not."""
    st_full = SD["OBV_S"].strength(bars, "1h")
    st_tail = SD["OBV_S"].strength(bars.iloc[500:].reset_index(drop=True), "1h")
    a, b = st_full["obv_gap_vol"][0][600:], st_tail["obv_gap_vol"][0][100:]
    assert np.allclose(a, b, rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("name", NAMES)
def test_strength_is_causal(name):
    df = synth(2500, 5)
    full = SD[name].strength(df, "1h")
    for k in (40, 333, 900, 1717, 2499):
        part = SD[name].strength(df.iloc[:k].reset_index(drop=True), "1h")
        for f, (vl, vs) in full.items():
            pl, ps = part[f]
            assert np.array_equal(pl, vl[:k], equal_nan=True), (f, k)
            assert np.array_equal(ps, vs[:k], equal_nan=True), (f, k)


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
    df = synth(900, 11)
    df.loc[200:260, ["open", "high", "low", "close"]] = 50.0      # flat stretch: ATR -> 0, HA range 0
    df.loc[300:340, "volume"] = 0.0                               # zero volume (OBV, volume SMA)
    df.loc[400, "volume"] = np.nan                                # a missing volume
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert not np.isinf(vl).any() and not np.isinf(vs).any()
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df)
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)


# ------------------------------------------------------------------ param_defs
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_default_signals_equal_locked(name, seed):
    df = synth(4000, seed)
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df)
    assert lg.dtype == bool and sh.dtype == bool
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)
    assert not (lg & sh).any()


@pytest.mark.parametrize("name", NAMES)
def test_default_signals_equal_registry(name, bars):
    """The sweep registry entry (what built the ground-truth caches) gives the same bars."""
    raw = L.compute_signals({"X": bars.copy()}, "1h", [name])[name]["X"]
    lg, sh = PD[name].signals(bars, "1h")
    assert np.array_equal(lg, raw > 0) and np.array_equal(sh, raw < 0)


@pytest.mark.parametrize("name", NAMES)
def test_params_schema(name):
    m = PD[name]
    assert m.EXCLUDED_REASON is None
    assert 1 <= len(m.PARAMS) <= 4
    names = [p["name"] for p in m.PARAMS]
    assert len(set(names)) == len(names)
    for p in m.PARAMS:
        assert set(p) == {"name", "default", "kind", "neutral", "where"}
        assert p["kind"] in KINDS
        assert (p["neutral"] is not None) == (p["kind"] == "threshold_neutral")
        assert "strategies.py:" in p["where"]
        if p["kind"] == "length":
            assert isinstance(p["default"], int)


def _expected(p, m):
    d, kind = p["default"], p["kind"]
    if kind == "length":
        return max(2, int(math.floor(d * m + 0.5)))
    if kind in ("mult", "threshold_abs"):
        return d * m
    return p["neutral"] + m * (d - p["neutral"])


@pytest.mark.parametrize("name", NAMES)
def test_variants_rule(name):
    m = PD[name]
    for p in m.PARAMS:
        vs = m.variants(p["name"])
        assert vs == m.variants(p)
        assert len(vs) == 4
        for ov, mult in zip(vs, MULTS):
            assert list(ov) == [p["name"]]
            v = ov[p["name"]]
            e = _expected(p, mult)
            if p["kind"] == "length":
                assert isinstance(v, int) and v == e and v >= 2
            else:
                assert math.isclose(v, e, rel_tol=1e-12, abs_tol=1e-12)


def test_variant_values_spelled_out():
    got = {n: {p["name"]: [list(v.values())[0] for v in PD[n].variants(p)] for p in PD[n].PARAMS} for n in NAMES}
    assert got["N23_HA_ST"] == {"st_atr_len": [5, 8, 13, 15], "st_mult": [3.0, 4.5, 7.5, 9.0],
                                "wick_tol": [0.01, 0.015, 0.025, 0.03]}
    assert got["N24_DMI"] == {"di_len": [7, 11, 18, 21], "adx_len": [7, 11, 18, 21],
                              "adx_long_min": [12.5, 18.75, 31.25, 37.5],
                              "adx_short_max": [12.5, 18.75, 31.25, 37.5]}
    assert got["N25_DST_CCI"] == {"cci_len": [10, 15, 25, 30], "cci_level": [50.0, 75.0, 125.0, 150.0],
                                  "st_fast_mult": [3.0, 4.5, 7.5, 9.0], "st_slow_mult": [3.0, 4.5, 7.5, 9.0]}
    assert got["OBV_S"] == {"obv_ma_len": [15, 23, 38, 45], "stc_level": [60.0, 65.0, 75.0, 80.0],
                            "stoch_k_smooth": [2, 3, 5, 6], "ao_slow_len": [17, 26, 43, 51]}


@pytest.mark.parametrize("name", NAMES)
def test_variants_run_and_change_signals(name):
    df = synth(5000, 4)
    m = PD[name]
    lg0, sh0 = m.signals(df, "1h")
    changed = 0
    for p in m.PARAMS:
        for ov in m.variants(p):
            lg, sh = m.signals(df, "1h", **ov)
            assert lg.shape == (len(df),) and sh.shape == (len(df),)
            assert lg.dtype == bool and sh.dtype == bool and not (lg & sh).any()
            changed += int((lg != lg0).any() or (sh != sh0).any())
    assert changed >= 3 * len(m.PARAMS)   # nearly every variant moves some signal on 5000 bars


def test_one_sided_parameters_touch_one_side():
    df = synth(5000, 6)
    m = PD["N24_DMI"]
    lg0, sh0 = m.signals(df, "1h")
    lg, sh = m.signals(df, "1h", adx_long_min=12.5)
    assert np.array_equal(sh & ~lg, sh0 & ~lg)       # shorts only lose bars that became longs
    lg, sh = m.signals(df, "1h", adx_short_max=37.5)
    assert np.array_equal(lg, lg0)


def test_obv_s_stc_level_mirrors():
    """stc_level L: longs need STC < L, shorts STC > 100 - L; the locked keywords give the same bars."""
    df = synth(4000, 8)
    for lvl in (60.0, 80.0):
        lg, sh = PD["OBV_S"].signals(df, "1h", stc_level=lvl)
        rl, rs = L._clean(*S.obv_s(df, stc_ob=lvl, stc_os=100.0 - lvl), len(df))
        assert np.array_equal(lg, rl) and np.array_equal(sh, rs)


def test_unknown_override_rejected(bars):
    for name in NAMES:
        with pytest.raises(ValueError):
            PD[name].signals(bars, "1h", not_a_param=1)


# Each parameter mapped to the literal(s) of the locked source it replaces (text substitution).
_MUTATIONS = {
    ("N23_HA_ST", "st_atr_len"): lambda v: [("supertrend_v2(df, 10, 6.0)", f"supertrend_v2(df, {v}, 6.0)")],
    ("N23_HA_ST", "st_mult"): lambda v: [("supertrend_v2(df, 10, 6.0)", f"supertrend_v2(df, 10, {v!r})")],
    ("N23_HA_ST", "wick_tol"): lambda v: [("/ rng, 0.02)", f"/ rng, {v!r})")],
    ("N24_DMI", "di_len"): lambda v: [("adx_line, plus, minus = fg.adx_dmi(df, 14)",
                                       f"plus, minus, adx_line = fg.dmi_adx(df, {v}, 14)")],
    ("N24_DMI", "adx_len"): lambda v: [("adx_line, plus, minus = fg.adx_dmi(df, 14)",
                                        f"plus, minus, adx_line = fg.dmi_adx(df, 14, {v})")],
    ("N24_DMI", "adx_long_min"): lambda v: [("ge(adx_line, 25.0)", f"ge(adx_line, {v!r})")],
    ("N24_DMI", "adx_short_max"): lambda v: [("le(adx_line, 25.0)", f"le(adx_line, {v!r})")],
    ("N25_DST_CCI", "cci_len"): lambda v: [("fg_fast.cci(df, 20)", f"fg_fast.cci(df, {v})")],
    ("N25_DST_CCI", "cci_level"): lambda v: [("cross_above(c, -100.0)", f"cross_above(c, -{v!r})"),
                                             ("cross_below(c, 100.0)", f"cross_below(c, {v!r})")],
    ("N25_DST_CCI", "st_fast_mult"): lambda v: [("supertrend_v2(df, 10, 6.0)", f"supertrend_v2(df, 10, {v!r})")],
    ("N25_DST_CCI", "st_slow_mult"): lambda v: [("supertrend_v2(df, 20, 6.0)", f"supertrend_v2(df, 20, {v!r})")],
    ("OBV_S", "obv_ma_len"): lambda v: [("pi.pine_sma(o, 30)", f"pi.pine_sma(o, {v})")],
    ("OBV_S", "stc_level"): lambda v: [("stc_ob: float = 70.0, stc_os: float = 30.0",
                                        f"stc_ob: float = {v!r}, stc_os: float = {100.0 - v!r}")],
    ("OBV_S", "stoch_k_smooth"): lambda v: [("pi.pine_sma(raw, 4)", f"pi.pine_sma(raw, {v})")],
    ("OBV_S", "ao_slow_len"): lambda v: [("pi.ao_ac(high, low, 5, 34, 5)", f"pi.ao_ac(high, low, 5, {v}, 5)")],
}


def _mutant(name, pname, v):
    import inspect
    import textwrap
    fn = LOCKED[name]
    src = textwrap.dedent(inspect.getsource(fn))
    for a, b in _MUTATIONS[(name, pname)](v):
        assert a in src, (name, pname, a)
        src = src.replace(a, b)
    g = dict(vars(S))
    exec(compile(src, f"<mutant {name} {pname}={v}>", "exec"), g)
    return g[fn.__name__]


@pytest.mark.parametrize("name", NAMES)
def test_every_variant_equals_locked_source_with_literal_replaced(name):
    """signals(**variant) == the locked function with that one literal changed in its source."""
    df = synth(3000, 9)
    m = PD[name]
    assert {p["name"] for p in m.PARAMS} == {k[1] for k in _MUTATIONS if k[0] == name}
    for p in m.PARAMS:
        for ov in m.variants(p):
            lg, sh = m.signals(df, "1h", **ov)
            rl, rs = L._clean(*_mutant(name, p["name"], ov[p["name"]])(df), len(df))
            assert np.array_equal(lg, rl) and np.array_equal(sh, rs), (name, ov)
