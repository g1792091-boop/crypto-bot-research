"""Entry-study definitions (PREREG_ENTRY.md sections 3 B / 4 C) of the batch
S2_ST_ROC, S5_DONCHIAN_MFI, S6_EMA_DMI_ADX, N01_ST_EMA:
research/entry_study/strength_defs/<NAME>.py and research/entry_study/param_defs/<NAME>.py.

Synthetic bars only (no data files, no network): schema, shapes, NaN-safety, causality of strength(),
default signals() == the locked strategy function, the variant rules, every variant == the locked function
with that one constant replaced in its source, and every variant moves at least one signal bar."""

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

NAMES = ["S2_ST_ROC", "S5_DONCHIAN_MFI", "S6_EMA_DMI_ADX", "N01_ST_EMA"]
KINDS = {"length", "mult", "threshold_neutral", "threshold_abs"}
MULTS = (0.5, 0.75, 1.25, 1.5)


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_{kind}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = {n: _load("strength_defs", n) for n in NAMES}
PD = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int, seed: int, freq: str = "1h") -> pd.DataFrame:
    """Random walk with drifting regimes (so ADX, supertrend flips and channel breakouts all occur)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.004, n // 200 + 1), 200)[:n]
    c = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.01, n)))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    v = rng.lognormal(3, 0.6, n)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v})


@pytest.fixture(scope="module")
def bars():
    return synth(2500, 1)


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
    assert lg.sum() + sh.sum() > 0
    warm = 300
    post = np.arange(len(bars)) >= warm
    for f, (vl, vs) in st.items():
        for v in (vl, vs):
            assert isinstance(v, np.ndarray) and v.dtype == float and v.shape == (len(bars),)
        # on signal bars after warm-up the strategy's own quantities exist, except st_age_bars before the
        # series' first supertrend flip to that side (tested exactly in test_st_age_nan_only_before_first_flip)
        okl, oks = lg & post, sh & post
        if f == "st_age_bars":
            okl, oks = okl & ~_before_first_flip(bars, +1), oks & ~_before_first_flip(bars, -1)
        assert np.isfinite(vl[okl]).all(), f
        assert np.isfinite(vs[oks]).all(), f


def _before_first_flip(df, side):
    import fg_fast
    d = fg_fast.supertrend(df, 10, 6.0)[1].to_numpy(float)
    dp = np.r_[np.nan, d[:-1]]
    with np.errstate(invalid="ignore"):
        flip = (d > 0) & (dp <= 0) if side > 0 else (d < 0) & (dp >= 0)
    return np.cumsum(flip) == 0


@pytest.mark.parametrize("name", ["S2_ST_ROC", "N01_ST_EMA"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_st_age_nan_only_before_first_flip(name, seed):
    import fg_fast
    df = synth(2500, seed)
    d = fg_fast.supertrend(df, 10, 6.0)[1].to_numpy(float)
    age_l, age_s = SD[name].strength(df, "1h")["st_age_bars"]
    with np.errstate(invalid="ignore"):
        up, dn = d > 0, d < 0
    assert np.array_equal(np.isnan(age_l), ~up | _before_first_flip(df, +1))
    assert np.array_equal(np.isnan(age_s), ~dn | _before_first_flip(df, -1))
    # 0 on the flip bar, +1 per bar while the direction holds
    i = np.flatnonzero(up & ~_before_first_flip(df, +1))
    for a, b in zip(i[:-1], i[1:]):
        if b == a + 1:
            assert age_l[b] == 0 or age_l[b] == age_l[a] + 1


def test_strength_signs_on_signal_bars(bars):
    """Features that measure 'how far past the rule' are >= 0 wherever the rule fired."""
    must_be_nonneg = {"S2_ST_ROC": ["roc_past_zero", "st_line_dist_atr", "st_age_bars"],
                      "S5_DONCHIAN_MFI": ["breakout_atr", "mfi_past_level", "sync_gap_bars"],
                      "S6_EMA_DMI_ADX": ["adx_over_25", "di_spread", "cross_gap_bars"],
                      "N01_ST_EMA": ["st_line_dist_atr", "st_age_bars"]}
    for name, feats in must_be_nonneg.items():
        st = SD[name].strength(bars, "1h")
        lg, sh = PD[name].signals(bars, "1h")
        for f in feats:
            vl, vs = st[f][0][lg], st[f][1][sh]
            assert (vl[~np.isnan(vl)] >= 0).all() and (vs[~np.isnan(vs)] >= 0).all(), (name, f)
    sd5 = SD["S5_DONCHIAN_MFI"].strength(bars, "1h")["sync_gap_bars"]
    lg, sh = PD["S5_DONCHIAN_MFI"].signals(bars, "1h")
    assert (sd5[0][lg] <= 2).all() and (sd5[1][sh] <= 2).all()
    sd6 = SD["S6_EMA_DMI_ADX"].strength(bars, "1h")["cross_gap_bars"]
    lg, sh = PD["S6_EMA_DMI_ADX"].signals(bars, "1h")
    assert (sd6[0][lg] <= 1).all() and (sd6[1][sh] <= 1).all()


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("n", [0, 1, 2, 5, 30])
def test_nan_safety_short_series(name, n):
    df = synth(max(n, 1), 7).iloc[:n].reset_index(drop=True)
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert vl.shape == (n,) and vs.shape == (n,)
    lg, sh = PD[name].signals(df, "1h")
    assert lg.shape == (n,) and sh.shape == (n,) and lg.dtype == bool and sh.dtype == bool


@pytest.mark.parametrize("name", NAMES)
def test_nan_safety_flat_and_zero_volume(name):
    """Flat prices (ATR 0, DI 0/0, MFI both-zero) and zero volume must not raise; no inf leaks out."""
    df = synth(400, 3)
    df.loc[100:180, ["open", "high", "low", "close"]] = 100.0
    df.loc[150:250, "volume"] = 0.0
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert not np.isinf(vl).any() and not np.isinf(vs).any()
    PD[name].signals(df, "1h")


@pytest.mark.parametrize("name", NAMES)
def test_strength_is_causal(name):
    df = synth(1500, 11, "15min")
    full = SD[name].strength(df, "15m")
    for k in (40, 333, 800, 1201, 1499):
        part = SD[name].strength(df.iloc[:k], "15m")
        for f in full:
            for side in (0, 1):
                assert np.array_equal(full[f][side][:k], part[f][side], equal_nan=True), (f, side, k)


@pytest.mark.parametrize("name", NAMES)
def test_strength_ignores_index(name, bars):
    """A non-RangeIndex (e.g. a slice of a bigger frame) gives the same values."""
    a = SD[name].strength(bars, "1h")
    shifted = bars.copy()
    shifted.index = shifted.index + 1000
    b = SD[name].strength(shifted, "1h")
    for f in a:
        for side in (0, 1):
            assert np.array_equal(a[f][side], b[f][side], equal_nan=True)


# ------------------------------------------------------------------ param_defs
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_default_signals_equal_locked(name, seed):
    df = synth(2500, seed)
    ref_l, ref_s = L._clean(*S.CANDIDATES_15M[name](df), len(df))
    lg, sh = PD[name].signals(df, "1h")
    assert np.array_equal(lg, ref_l) and np.array_equal(sh, ref_s)
    assert not (lg & sh).any()


@pytest.mark.parametrize("name", NAMES)
def test_params_schema(name):
    mod = PD[name]
    assert mod.EXCLUDED_REASON is None
    assert 1 <= len(mod.PARAMS) <= 4
    for p in mod.PARAMS:
        assert set(p) == {"name", "default", "kind", "neutral", "where"}
        assert p["kind"] in KINDS
        assert (p["neutral"] is not None) == (p["kind"] == "threshold_neutral")
        assert p["where"].startswith("third_party/sweep/harness/vendor/strategies.py:")
    # explicitly passing the defaults is the same as no override
    df = synth(800, 5)
    base = mod.signals(df, "1h")
    same = mod.signals(df, "1h", **{p["name"]: p["default"] for p in mod.PARAMS})
    assert np.array_equal(base[0], same[0]) and np.array_equal(base[1], same[1])
    with pytest.raises(ValueError):
        mod.signals(df, "1h", not_a_param=1)


def _expected(p, m):
    d = p["default"]
    if p["kind"] == "length":
        return max(2, int(math.floor(d * m + 0.5)))
    if p["kind"] == "threshold_neutral":
        return p["neutral"] + m * (d - p["neutral"])
    return d * m


@pytest.mark.parametrize("name", NAMES)
def test_variants_rules(name):
    mod = PD[name]
    for p in mod.PARAMS:
        vs = mod.variants(p["name"])
        assert vs == mod.variants(p)                      # name or PARAMS entry
        assert len(vs) == 4
        for v, m in zip(vs, MULTS):
            assert list(v) == [p["name"]]
            got = v[p["name"]]
            assert got == pytest.approx(_expected(p, m))
            if p["kind"] == "length":
                assert isinstance(got, int) and got >= 2


def test_variant_values_locked():
    """Concrete values (round half up, min 2; threshold distance from the neutral point)."""
    v = lambda n, p: [list(d.values())[0] for d in PD[n].variants(p)]  # noqa: E731
    assert v("S2_ST_ROC", "st_atr_len") == [5, 8, 13, 15]
    assert v("S2_ST_ROC", "st_mult") == [3.0, 4.5, 7.5, 9.0]
    assert v("S2_ST_ROC", "roc_len") == [5, 7, 11, 14]
    assert v("S5_DONCHIAN_MFI", "dc_len") == [10, 15, 25, 30]
    assert v("S5_DONCHIAN_MFI", "mfi_len") == [7, 11, 18, 21]
    assert v("S5_DONCHIAN_MFI", "mfi_level") == [40.0, 35.0, 25.0, 20.0]
    assert v("S5_DONCHIAN_MFI", "sync") == [2, 2, 4, 5]
    assert v("S6_EMA_DMI_ADX", "ema_len") == [10, 15, 25, 30]
    assert v("S6_EMA_DMI_ADX", "di_len") == [7, 11, 18, 21]
    assert v("S6_EMA_DMI_ADX", "adx_len") == [7, 11, 18, 21]
    assert v("S6_EMA_DMI_ADX", "adx_min") == [12.5, 18.75, 31.25, 37.5]
    assert v("N01_ST_EMA", "ema_fast") == [3, 4, 6, 8]
    assert v("N01_ST_EMA", "ema_slow") == [10, 15, 25, 30]
    assert v("N01_ST_EMA", "st_atr_len") == [5, 8, 13, 15]
    assert v("N01_ST_EMA", "st_mult") == [3.0, 4.5, 7.5, 9.0]


@pytest.mark.parametrize("name", NAMES)
def test_every_variant_runs_and_is_causal(name, bars):
    mod = PD[name]
    base = mod.signals(bars, "1h")
    changed = 0
    for p in mod.PARAMS:
        for ov in mod.variants(p):
            lg, sh = mod.signals(bars, "1h", **ov)
            assert lg.shape == sh.shape == (len(bars),) and not (lg & sh).any()
            changed += int(not (np.array_equal(lg, base[0]) and np.array_equal(sh, base[1])))
            k = 1700
            lk, sk = mod.signals(bars.iloc[:k], "1h", **ov)
            assert np.array_equal(lg[:k], lk) and np.array_equal(sh[:k], sk)
    assert changed >= 1


@pytest.fixture(scope="module")
def change_frames():
    return [synth(4000, s) for s in (1, 2, 3)]


@pytest.mark.parametrize("name", NAMES)
def test_each_variant_changes_signals(name, change_frames):
    """Every one of the 4 variants of every parameter moves at least one signal bar (on 3 synthetic series;
    on one short series a few supertrend-length variants can leave the bars unchanged)."""
    mod = PD[name]
    bases = [mod.signals(df, "1h") for df in change_frames]
    for p in mod.PARAMS:
        for ov in mod.variants(p):
            moved = 0
            for df, (bl, bs) in zip(change_frames, bases):
                lg, sh = mod.signals(df, "1h", **ov)
                moved += int(((lg.astype(np.int8) - sh.astype(np.int8)) != (bl.astype(np.int8) - bs.astype(np.int8))).sum())
            assert moved > 0, (name, ov)


# The locked function with one constant replaced in its own source: the variant must equal it bar for bar,
# so each parameter is wired to the right place (e.g. di_len vs adx_len, both mirrored MFI levels).
_FN = {"S2_ST_ROC": "s2_supertrend_roc", "S5_DONCHIAN_MFI": "s5_donchian_mfi",
       "S6_EMA_DMI_ADX": "s6_ema_dmi_adx", "N01_ST_EMA": "n01_supertrend_ema"}
_MUT = {  # (name, param): [(old text, new text with {v} = value, {w} = 100 - value, occurrences)]
    ("S2_ST_ROC", "st_atr_len"): [("fg_fast.supertrend(df, 10, 6.0)", "fg_fast.supertrend(df, {v}, 6.0)", 1)],
    ("S2_ST_ROC", "st_mult"): [("fg_fast.supertrend(df, 10, 6.0)", "fg_fast.supertrend(df, 10, {v})", 1)],
    ("S2_ST_ROC", "roc_len"): [('fg.roc(df["close"], 9)', 'fg.roc(df["close"], {v})', 1)],
    ("S5_DONCHIAN_MFI", "dc_len"): [("fg.donchian_channel(df, 20,", "fg.donchian_channel(df, {v},", 1)],
    ("S5_DONCHIAN_MFI", "mfi_len"): [("fg.mfi(df, 14)", "fg.mfi(df, {v})", 1)],
    ("S5_DONCHIAN_MFI", "mfi_level"): [("30.0", "{v}", 2), ("70.0", "{w}", 2)],
    ("S5_DONCHIAN_MFI", "sync"): [("sync = 3", "sync = {v}", 1)],
    ("S6_EMA_DMI_ADX", "ema_len"): [('fg.ema(df["close"], 20)', 'fg.ema(df["close"], {v})', 1)],
    ("S6_EMA_DMI_ADX", "di_len"): [("fg.dmi_adx(df, 14, 14)", "fg.dmi_adx(df, {v}, 14)", 1)],
    ("S6_EMA_DMI_ADX", "adx_len"): [("fg.dmi_adx(df, 14, 14)", "fg.dmi_adx(df, 14, {v})", 1)],
    ("S6_EMA_DMI_ADX", "adx_min"): [("ge(adx, 25.0)", "ge(adx, {v})", 1)],
    ("N01_ST_EMA", "ema_fast"): [('fg.ema(df["close"], 5)', 'fg.ema(df["close"], {v})', 1)],
    ("N01_ST_EMA", "ema_slow"): [('fg.ema(df["close"], 20)', 'fg.ema(df["close"], {v})', 1)],
    ("N01_ST_EMA", "st_atr_len"): [("fg_fast.supertrend(df, 10, 6.0)", "fg_fast.supertrend(df, {v}, 6.0)", 1)],
    ("N01_ST_EMA", "st_mult"): [("fg_fast.supertrend(df, 10, 6.0)", "fg_fast.supertrend(df, 10, {v})", 1)],
}


def _mutated_locked(name, pname, v):
    import inspect
    import re
    src = inspect.getsource(getattr(S, _FN[name]))
    fmt = lambda x: repr(float(x)) if isinstance(x, float) else str(int(x))  # noqa: E731
    for old, new, count in _MUT[(name, pname)]:
        pat = r"(?<![\w.])" + re.escape(old)
        assert len(re.findall(pat, src)) == count, (name, pname, old)
        w = fmt(100.0 - v) if isinstance(v, float) else ""
        src = re.sub(pat, new.format(v=fmt(v), w=w), src)
    ns = dict(vars(S))
    exec(compile(src, f"<{name} {pname}={v}>", "exec"), ns)
    return ns[_FN[name]]


def test_mutation_table_covers_params():
    assert {(n, p["name"]) for n in NAMES for p in PD[n].PARAMS} == set(_MUT)


@pytest.mark.parametrize("name", NAMES)
def test_variant_equals_locked_code_with_that_constant(name):
    df = synth(2500, 2)
    mod = PD[name]
    for p in mod.PARAMS:
        for ov in mod.variants(p):
            ref_l, ref_s = L._clean(*_mutated_locked(name, p["name"], ov[p["name"]])(df), len(df))
            lg, sh = mod.signals(df, "1h", **ov)
            assert np.array_equal(lg, ref_l) and np.array_equal(sh, ref_s), (name, ov)


def test_s5_mfi_level_is_mirrored():
    """mfi_level moves the long level (30) and the short level (100 - level = 70) together."""
    import fg_indicators as fg
    df = synth(2500, 2)
    m = fg.mfi(df, 14).to_numpy(float)
    lg, sh = PD["S5_DONCHIAN_MFI"].signals(df, "1h", mfi_level=40.0)
    assert (m[lg] > 40.0).all() and (m[sh] < 60.0).all()
