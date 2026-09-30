"""Entry-study definitions for the batch N09_ALLIG_AROON, N10_HA_PSAR, N12_ICHI_AO, N14_ICHI_RSI
(research/entry_study/strength_defs/<NAME>.py and param_defs/<NAME>.py, PREREG_ENTRY.md sections 3-4).

Synthetic bars only (no data files): shapes, NaN safety, causality of strength(), the variant
rules, and that signals() with no overrides equals the locked strategy function. N14 almost never
fires on random bars, so it also gets a hand-built series (uptrend, crash, slow bounce, one
high-wick bar) on which the locked rule fires, plus its exact mirror for the short side."""

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
pytestmark = pytest.mark.filterwarnings("ignore:All-NaN slice encountered:RuntimeWarning")  # vendored HA on NaN bars
NAMES = ["N09_ALLIG_AROON", "N10_HA_PSAR", "N12_ICHI_AO", "N14_ICHI_RSI"]
RANDOM_FIRING = ["N09_ALLIG_AROON", "N10_HA_PSAR", "N12_ICHI_AO"]
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
    """Random walk with random-length regimes (drift up, down or none)."""
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


def crafted(bounce: float = 1.0, mirror: bool = False) -> pd.DataFrame:
    """200 bars up (+0.5), 20 bars crash (-4), slow bounce; bar 229 has a high wick to 210 so the
    Tenkan jumps over the Kijun while RSI(14) is still under 30 (28.2 with bounce 1.0) and the
    cloud is still green: the N14 long fires on bar 229. ``mirror`` reflects every price about 200
    (high <-> low), which mirrors Ichimoku and gives RSI -> 100 - RSI, so N14 shorts on bar 229."""
    steps = np.r_[np.full(200, 0.5), np.full(20, -4.0), np.full(40, bounce)]
    c = 100.0 + np.cumsum(steps)
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) + 0.1
    lo = np.minimum(o, c) - 0.1
    h[229] = 210.0
    if mirror:
        o, c, h, lo = 400.0 - o, 400.0 - c, 400.0 - lo, 400.0 - h
    df = pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=len(c), freq="1h", tz="UTC"),
                       "open": o, "high": h, "low": lo, "close": c, "volume": 1.0})
    df.attrs["tf"] = "1h"
    return df


SEEDS = (1, 2, 3, 4, 5)


@pytest.fixture(scope="module")
def bars():
    return synth(1200, seed=7)


def _signal_sets(name):
    """(df, long, short) cases where the strategy fires, warm-up bars dropped."""
    if name == "N14_ICHI_RSI":
        cases = [crafted(), crafted(mirror=True)]
    else:
        cases = [synth(seed=s) for s in SEEDS]
    out = []
    for df in cases:
        lo, sh = PARAMS[name].signals(df, "1h")
        lo[:200 if name == "N14_ICHI_RSI" else 300] = False
        sh[:200 if name == "N14_ICHI_RSI" else 300] = False
        out.append((df, lo, sh))
    return out


# ---------------------------------------------------------------------------------------------
# strength_defs
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_features_metadata(name):
    m = STRENGTH[name]
    assert m.NAME == name
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
    for df, lo, sh in _signal_sets(name):
        out = m.strength(df, "1h")
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
    for k in (0, 1, 5):
        tiny = bars.iloc[:k].reset_index(drop=True)
        for f, (a, b) in m.strength(tiny, "1h").items():
            assert a.shape == (k,) and b.shape == (k,)


def test_strength_mirrors():
    df = synth(900, seed=3)
    pairs = {"N09_ALLIG_AROON": ["aroon_spread"], "N10_HA_PSAR": ["ha_body_atr", "sar_gap_atr"],
             "N12_ICHI_AO": ["ao_atr", "tk_gap_atr", "cloud_gap_atr"],
             "N14_ICHI_RSI": ["tk_gap_atr", "cloud_gap_atr"]}
    for name, feats in pairs.items():
        out = STRENGTH[name].strength(df, "1h")
        for f in feats:
            a, b = out[f]
            ok = np.isfinite(a)
            assert ok.sum() > 500 and np.array_equal(ok, np.isfinite(b))
            assert np.allclose(a[ok], -b[ok]), (name, f)
    a, b = STRENGTH["N14_ICHI_RSI"].strength(df, "1h")["rsi_depth"]
    ok = np.isfinite(a)
    assert np.allclose(a[ok] + b[ok], -40.0)          # (30 - RSI) + (RSI - 70)
    # lips gap: long side measures past max(teeth, jaw), short side past min(teeth, jaw)
    a, b = STRENGTH["N09_ALLIG_AROON"].strength(df, "1h")["lips_gap_atr"]
    ok = np.isfinite(a) & np.isfinite(b)
    assert ok.sum() > 500 and ((a[ok] <= 0) | (b[ok] <= 0)).all()


def test_strength_mirror_series():
    """On the exact price mirror, every N14 long feature at bar i equals the short feature at bar i
    (from bar 60: in its first 14 bars the vendored fg.rsi returns 0, not NaN, on both series)."""
    up, dn = STRENGTH["N14_ICHI_RSI"].strength(crafted(), "1h"), STRENGTH["N14_ICHI_RSI"].strength(crafted(mirror=True), "1h")
    for f in up:
        a, b = up[f][0][60:], dn[f][1][60:]
        ok = np.isfinite(a)
        assert np.array_equal(ok, np.isfinite(b)) and np.allclose(a[ok], b[ok]), f


def test_strength_on_signal_bars():
    """On signal bars the features sit on the side the rule requires."""
    for df, lo, sh in _signal_sets("N09_ALLIG_AROON"):
        out = STRENGTH["N09_ALLIG_AROON"].strength(df, "1h")
        a, b = out["aroon_spread"]
        assert (a[lo] >= 0).all() and (b[sh] >= 0).all()
        a, b = out["lips_gap_atr"]
        assert (a[lo] > 0).all() and (b[sh] > 0).all()
        a, b = out["sync_gap_bars"]
        assert set(np.unique(a[lo])) <= {0.0, 1.0} and set(np.unique(b[sh])) <= {0.0, 1.0}
    for df, lo, sh in _signal_sets("N10_HA_PSAR"):
        out = STRENGTH["N10_HA_PSAR"].strength(df, "1h")
        for f in ("ha_body_atr", "sar_gap_atr"):
            a, b = out[f]
            assert (a[lo] > 0).all() and (b[sh] > 0).all(), f
        a, b = out["sar_age_bars"]
        assert (a[lo] >= 0).all() and (b[sh] >= 0).all()
        assert (a[lo] == 0).any() and (a[lo] > 2).any()        # flip-triggered and HA-triggered longs
    for df, lo, sh in _signal_sets("N12_ICHI_AO"):
        out = STRENGTH["N12_ICHI_AO"].strength(df, "1h")
        a, b = out["ao_atr"]
        assert (a[lo] > 0).all() and (b[sh] > 0).all()
        a, b = out["cloud_gap_atr"]
        assert (a[lo] > 0).all() and (b[sh] > 0).all()
    for df, lo, sh in _signal_sets("N14_ICHI_RSI"):
        out = STRENGTH["N14_ICHI_RSI"].strength(df, "1h")
        a, b = out["rsi_depth"]
        assert (a[lo] > 0).all() and (b[sh] > 0).all()
        a, b = out["cloud_gap_atr"]
        assert (a[lo] > 0).all() and (b[sh] > 0).all()


# ---------------------------------------------------------------------------------------------
# param_defs
# ---------------------------------------------------------------------------------------------
LOCKED = {"N09_ALLIG_AROON": "n09_alligator_aroon", "N10_HA_PSAR": "n10_heikin_psar",
          "N12_ICHI_AO": "n12_ichimoku_ao", "N14_ICHI_RSI": "n14_ichimoku_rsi"}


def _locked(name, df):
    ref_l, ref_s = L.REGISTRY[name](df, None)
    return L._clean(ref_l, ref_s, len(df))


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_default_equals_locked(name, seed):
    df = synth(seed=seed)
    lo, sh = PARAMS[name].signals(df, "1h")
    ref_l, ref_s = _locked(name, df)
    assert lo.dtype == bool and sh.dtype == bool and lo.shape == (len(df),)
    assert np.array_equal(lo, ref_l) and np.array_equal(sh, ref_s)
    assert not (lo & sh).any()
    import strategies as S
    assert L.REGISTRY[name].__name__ == LOCKED[name] == getattr(S, LOCKED[name]).__name__


@pytest.mark.parametrize("bounce", (0.4, 0.8, 1.0, 1.2))
@pytest.mark.parametrize("mirror", (False, True))
def test_n14_crafted_equals_locked(bounce, mirror):
    df = crafted(bounce, mirror)
    lo, sh = PARAMS["N14_ICHI_RSI"].signals(df, "1h")
    ref_l, ref_s = _locked("N14_ICHI_RSI", df)
    assert np.array_equal(lo, ref_l) and np.array_equal(sh, ref_s)
    if bounce <= 1.0:
        assert (sh if mirror else lo)[229] and not (lo if mirror else sh).any()


@pytest.mark.parametrize("name", NAMES)
def test_params_metadata(name):
    m = PARAMS[name]
    assert m.NAME == name and m.EXCLUDED_REASON is None
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
                assert v == _round_len(mult * d) and isinstance(v, int)
            elif p["kind"] in ("mult", "threshold_abs"):
                assert v == pytest.approx(mult * d)
            else:
                assert v == pytest.approx(p["neutral"] + mult * (d - p["neutral"]))
            assert v != d


def test_variant_values_spelled_out():
    def vals(name):
        return {p["name"]: [list(o.values())[0] for o in PARAMS[name].variants(p)] for p in PARAMS[name].PARAMS}
    v = vals("N09_ALLIG_AROON")
    assert v == {"lips_len": [3, 4, 6, 8], "teeth_len": [4, 6, 10, 12], "jaw_len": [7, 10, 16, 20],
                 "aroon_len": [13, 19, 31, 38]}                      # round half up: 2.5 -> 3, 6.5 -> 7
    v = vals("N10_HA_PSAR")
    assert v == {"sar_af_start": [0.01, 0.015, 0.025, 0.03], "sar_af_step": [0.01, 0.015, 0.025, 0.03],
                 "sar_af_max": [0.1, 0.15, 0.25, 0.3], "wick_tol": [0.01, 0.015, 0.025, 0.03]}
    v = vals("N12_ICHI_AO")
    assert v == {"tenkan_len": [5, 7, 11, 14], "kijun_len": [13, 20, 33, 39], "ao_fast_len": [3, 4, 6, 8],
                 "ao_slow_len": [17, 26, 43, 51]}
    v = vals("N14_ICHI_RSI")
    assert v == {"tenkan_len": [5, 7, 11, 14], "kijun_len": [13, 20, 33, 39], "rsi_len": [7, 11, 18, 21],
                 "rsi_oversold": [40.0, 35.0, 25.0, 20.0]}


@pytest.mark.parametrize("name", NAMES)
def test_variants_run(name):
    m = PARAMS[name]
    df = synth(900, seed=4)
    for p in m.PARAMS:
        for ov in m.variants(p):
            lo, sh = m.signals(df, "1h", **ov)
            assert lo.shape == (len(df),) and sh.shape == (len(df),)
            assert lo.dtype == bool and not (lo & sh).any()


@pytest.mark.parametrize("name", RANDOM_FIRING)
def test_every_parameter_moves_the_signal(name):
    """Each parameter reaches the rule: some variant changes the signal bars on random bars."""
    m = PARAMS[name]
    dfs = [synth(1500, seed=s) for s in (1, 2)]
    base = [m.signals(df, "1h") for df in dfs]
    for p in m.PARAMS:
        moved = False
        for ov in m.variants(p):
            for df, (lo, sh) in zip(dfs, base):
                vl, vs = m.signals(df, "1h", **ov)
                moved |= bool((vl != lo).any() or (vs != sh).any())
        assert moved, p["name"]


def test_n09_lips_as_slow_as_teeth_never_fires():
    """lips_len x1.5 = 8 = teeth_len: SMA8 is never strictly above/below itself (documented)."""
    m = PARAMS["N09_ALLIG_AROON"]
    ov = m.variants("lips_len")[3]
    assert ov == {"lips_len": 8}
    for s in (1, 2):
        lo, sh = m.signals(synth(seed=s), "1h", **ov)
        assert not lo.any() and not sh.any()


def test_n14_rsi_levels_mirror():
    """rsi_oversold moves the long level and the short level 100 - value together.
    Crafted bar 229 has RSI 28.2 (long) / 71.8 (mirror, short)."""
    m = PARAMS["N14_ICHI_RSI"]
    want = {30.0: [229], 40.0: [229, 230], 35.0: [229, 230], 25.0: [], 20.0: []}
    for mirror in (False, True):
        df = crafted(1.0, mirror)
        for lvl, bars_ in want.items():
            lo, sh = m.signals(df, "1h", rsi_oversold=lvl)
            assert np.flatnonzero(sh if mirror else lo).tolist() == bars_, (mirror, lvl)
            assert not (lo if mirror else sh).any()


def test_n14_other_params_reach_the_rule(monkeypatch):
    """N14 never fires on random bars, so: tenkan_len / rsi_len change the crafted signal, and
    kijun_len (whose variants all keep the crafted high-wick cross) is checked to reach fg.ichimoku."""
    m = PARAMS["N14_ICHI_RSI"]
    df = crafted(1.0)
    lo, _sh = m.signals(df, "1h")
    for p in ("tenkan_len", "rsi_len"):
        assert any((m.signals(df, "1h", **ov)[0] != lo).any() for ov in m.variants(p)), p
    calls = []
    real = m.fg.ichimoku
    monkeypatch.setattr(m.fg, "ichimoku", lambda d, *a: calls.append(a) or real(d, *a))
    for ov in m.variants("kijun_len"):
        m.signals(df, "1h", **ov)
    m.signals(df, "1h", rsi_len=7)
    assert calls == [(9, 13, 52, 26), (9, 20, 52, 26), (9, 33, 52, 26), (9, 39, 52, 26), (9, 26, 52, 26)]


@pytest.mark.parametrize("name", NAMES)
def test_unknown_override_rejected(name):
    with pytest.raises(ValueError):
        PARAMS[name].signals(synth(300), "1h", no_such_param=3)


@pytest.mark.parametrize("name", NAMES)
def test_signals_nan_safe(name):
    df = synth(800, seed=6)
    df.loc[300:305, ["open", "high", "low", "close"]] = np.nan
    lo, sh = PARAMS[name].signals(df, "1h")
    ref_l, ref_s = _locked(name, df)
    assert lo.dtype == bool and lo.shape == (len(df),) and not (lo & sh).any()
    assert np.array_equal(lo, ref_l) and np.array_equal(sh, ref_s)
