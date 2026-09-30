"""Entry-study definitions for the batch N02_ST_KST, N03_ADX_GC, N07_ICHI_CMO, N08_ICHI_WR
(research/entry_study/strength_defs/<NAME>.py and param_defs/<NAME>.py, PREREG_ENTRY.md sections 3-4).

Synthetic bars only (no data files): shapes, NaN safety, causality of strength(), the variant
rules, and that signals() with no overrides equals the locked strategy function."""

from __future__ import annotations

import importlib.util
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from paperbot import sweepsig  # noqa: E402

L = sweepsig.lib()
NAMES = ["N02_ST_KST", "N03_ADX_GC", "N07_ICHI_CMO", "N08_ICHI_WR"]
MULTS = (0.5, 0.75, 1.25, 1.5)


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_{kind}_{name}", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


STRENGTH = {n: _load("strength_defs", n) for n in NAMES}
PARAMS = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int = 4000, seed: int = 1, tf: str = "1h") -> pd.DataFrame:
    """Random walk with random-length regimes (drift up, down or none), tuned so that ADX hovers
    around 25 and every strategy of the batch fires on both sides over seeds 1-5."""
    rng = np.random.default_rng(seed)
    blocks = rng.integers(20, 300, size=n)
    drift = np.concatenate([np.full(b, rng.choice([-0.001, 0.0, 0.001])) for b in blocks])[:n]
    r = drift + rng.normal(0, 0.006, n)
    c = 100.0 * np.exp(np.cumsum(r))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    ts = pd.date_range("2024-01-01", periods=n, freq={"15m": "15min", "1h": "1h", "4h": "4h"}[tf], tz="UTC")
    df = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c,
                       "volume": rng.uniform(10, 100, n)})
    df.attrs["tf"] = tf
    return df


SEEDS = (1, 2, 3, 4, 5)


@pytest.fixture(scope="module")
def bars():
    return synth(1200, seed=7)


# ---------------------------------------------------------------------------------------------
# strength_defs
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_features_metadata(name):
    m = STRENGTH[name]
    assert 1 <= len(m.FEATURES) <= 3
    names = [f["name"] for f in m.FEATURES]
    assert len(set(names)) == len(names)
    for f in m.FEATURES:
        assert set(f) >= {"name", "label_ko", "unit", "higher_is_stronger", "why"}
        assert f["name"] == f["name"].lower() and " " not in f["name"]
        assert 0 < len(f["label_ko"]) <= 20
        assert isinstance(f["higher_is_stronger"], bool)
        assert f["why"] and f["unit"]


@pytest.mark.parametrize("name", NAMES)
def test_strength_shapes_and_finite(name, bars):
    m = STRENGTH[name]
    out = m.strength(bars, "1h")
    assert set(out) == {f["name"] for f in m.FEATURES}
    for f, (a, b) in out.items():
        assert a.shape == (len(bars),) and b.shape == (len(bars),)
        assert a.dtype.kind == "f" and b.dtype.kind == "f"
        assert not np.isinf(a).any() and not np.isinf(b).any()
    n_sig = [0, 0]
    for seed in SEEDS:
        df = synth(seed=seed)
        out = m.strength(df, "1h")
        lo, sh = PARAMS[name].signals(df, "1h")
        lo[:300] = sh[:300] = False
        n_sig[0] += int(lo.sum())
        n_sig[1] += int(sh.sum())
        for f, (a, b) in out.items():
            assert np.isfinite(a[lo]).all() and np.isfinite(b[sh]).all(), f   # defined on every signal
    assert min(n_sig) > 0


@pytest.mark.parametrize("name", NAMES)
def test_strength_causal(name, bars):
    m = STRENGTH[name]
    full = m.strength(bars, "1h")
    for k in (60, 250, 611, 1000, len(bars) - 1):
        part = m.strength(bars.iloc[:k].reset_index(drop=True), "1h")
        for f in full:
            for side in (0, 1):
                assert np.array_equal(full[f][side][:k], part[f][side], equal_nan=True), (f, side, k)


@pytest.mark.parametrize("name", NAMES)
def test_strength_nan_safe(name, bars):
    """Flat bars (ATR 0, zero ranges) and a hole of NaN prices give NaN, never inf or an error."""
    m = STRENGTH[name]
    df = bars.copy()
    df.loc[400:460, ["open", "high", "low", "close"]] = 100.0
    df.loc[700:705, ["open", "high", "low", "close"]] = np.nan
    out = m.strength(df, "1h")
    for f, (a, b) in out.items():
        assert a.shape == (len(df),) and not np.isinf(a).any() and not np.isinf(b).any()
    tiny = bars.iloc[:5].reset_index(drop=True)
    for f, (a, b) in m.strength(tiny, "1h").items():
        assert a.shape == (5,) and b.shape == (5,)


def test_strength_mirrors():
    df = synth(900, seed=3)
    for name in ("N07_ICHI_CMO", "N08_ICHI_WR"):
        out = STRENGTH[name].strength(df, "1h")
        for f in ("tk_gap_atr", "cloud_gap_atr"):
            a, b = out[f]
            ok = np.isfinite(a)
            assert np.allclose(a[ok], -b[ok])
    a, b = STRENGTH["N08_ICHI_WR"].strength(df, "1h")["wr_margin"]
    ok = np.isfinite(a)
    assert np.allclose(a[ok] + b[ok], 60.0)          # (%R + 80) + (-20 - %R)
    a, b = STRENGTH["N03_ADX_GC"].strength(df, "1h")["adx_excess"]
    assert np.array_equal(a, b, equal_nan=True)


def test_cross_lag_is_zero_to_two_on_signals():
    seen = set()
    for seed in SEEDS:
        df = synth(seed=seed)
        lo, sh = PARAMS["N03_ADX_GC"].signals(df, "1h")
        a, b = STRENGTH["N03_ADX_GC"].strength(df, "1h")["cross_lag_bars"]
        assert set(np.unique(a[lo])) <= {0.0, 1.0, 2.0}
        assert set(np.unique(b[sh])) <= {0.0, 1.0, 2.0}
        seen |= set(np.unique(a[lo])) | set(np.unique(b[sh]))
    assert seen


# ---------------------------------------------------------------------------------------------
# param_defs
# ---------------------------------------------------------------------------------------------
LOCKED = {"N02_ST_KST": "n02_supertrend_kst", "N03_ADX_GC": "n03_adx_golden_cross",
          "N07_ICHI_CMO": "n07_ichimoku_cmo", "N08_ICHI_WR": "n08_ichimoku_williams"}


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_default_equals_locked(name, seed):
    df = synth(seed=seed)
    lo, sh = PARAMS[name].signals(df, "1h")
    ref_l, ref_s = L.REGISTRY[name](df, None)
    ref_l, ref_s = L._clean(ref_l, ref_s, len(df))
    assert lo.dtype == bool and sh.dtype == bool and lo.shape == (len(df),)
    assert np.array_equal(lo, ref_l) and np.array_equal(sh, ref_s)
    assert not (lo & sh).any()
    import strategies as S
    assert L.REGISTRY[name].__name__ == LOCKED[name] == getattr(S, LOCKED[name]).__name__


@pytest.mark.parametrize("name", NAMES)
def test_params_metadata(name):
    m = PARAMS[name]
    assert m.EXCLUDED_REASON is None
    assert 1 <= len(m.PARAMS) <= 4
    for p in m.PARAMS:
        assert p["kind"] in ("length", "mult", "threshold_neutral", "threshold_abs")
        assert (p["neutral"] is not None) == (p["kind"] == "threshold_neutral")
        assert "strategies.py" in p["where"]


def _round_len(x):
    return max(2, int(math.floor(x + 0.5)))


@pytest.mark.parametrize("name", NAMES)
def test_variants_rules(name):
    m = PARAMS[name]
    for p in m.PARAMS:
        vs = m.variants(p)
        assert vs == m.variants(p["name"]) and len(vs) == 4
        for mult, ov in zip(MULTS, vs):
            assert list(ov) == [p["name"]]
            v, d = ov[p["name"]], p["default"]
            if p["kind"] == "length":
                want = [_round_len(mult * x) for x in d] if isinstance(d, list) else _round_len(mult * d)
                assert v == want
            elif p["kind"] in ("mult", "threshold_abs"):
                assert v == pytest.approx(mult * d)
            else:
                assert v == pytest.approx(p["neutral"] + mult * (d - p["neutral"]))
            assert v != d


def test_variant_values_spelled_out():
    v = {p["name"]: [list(o.values())[0] for o in PARAMS["N02_ST_KST"].variants(p)]
         for p in PARAMS["N02_ST_KST"].PARAMS}
    assert v["st_atr_len"] == [5, 8, 13, 15]                   # round half up: 7.5 -> 8, 12.5 -> 13
    assert v["st_mult"] == [3.0, 4.5, 7.5, 9.0]
    assert v["kst_roc_lens"][0] == [5, 8, 10, 15] and v["kst_roc_lens"][3] == [15, 23, 30, 45]
    assert v["kst_signal_len"] == [5, 7, 11, 14]
    w = [o["wr_oversold"] for o in PARAMS["N08_ICHI_WR"].variants("wr_oversold")]
    assert w == [-65.0, -72.5, -87.5, -95.0]
    a = [o["adx_level"] for o in PARAMS["N03_ADX_GC"].variants("adx_level")]
    assert a == [12.5, 18.75, 31.25, 37.5]


@pytest.mark.parametrize("name", NAMES)
def test_variants_run(name):
    m = PARAMS[name]
    df = synth(900, seed=4)
    for p in m.PARAMS:
        for ov in m.variants(p):
            lo, sh = m.signals(df, "1h", **ov)
            assert lo.shape == (len(df),) and sh.shape == (len(df),)
            assert lo.dtype == bool and not (lo & sh).any()


@pytest.mark.parametrize("name", NAMES)
def test_unknown_override_rejected(name):
    with pytest.raises(ValueError):
        PARAMS[name].signals(synth(300), "1h", no_such_param=3)


def test_wr_levels_mirror():
    """wr_oversold moves the short level to -100 - value: shorts at -35 when longs at -65."""
    import fg_indicators as fg
    m = PARAMS["N08_ICHI_WR"]
    n = [0, 0]
    for seed in SEEDS:
        df = synth(seed=seed)
        lo, sh = m.signals(df, "1h", wr_oversold=-65.0)
        wr = fg.williams_r(df, 14).to_numpy()
        prev = np.r_[np.nan, wr[:-1]]
        assert (wr[lo] > -65.0).all() and (wr[sh] < -35.0).all()
        # a %R cross of the moved level (not of -80 / -20) is what triggers some signals
        n[0] += int((lo & (wr > -65.0) & (prev <= -65.0)).sum())
        n[1] += int((sh & (wr < -35.0) & (prev >= -35.0)).sum())
    assert min(n) > 0


@pytest.mark.parametrize("name", NAMES)
def test_signals_nan_safe(name):
    df = synth(800, seed=6)
    df.loc[300:305, ["open", "high", "low", "close"]] = np.nan
    lo, sh = PARAMS[name].signals(df, "1h")
    assert lo.dtype == bool and lo.shape == (len(df),) and not (lo & sh).any()
