"""Entry-study definitions (PREREG_ENTRY.md sections 3 B / 4 C) of the batch
OBV_B, V39_ALL, V45_AMB, DOGE:
research/entry_study/strength_defs/<NAME>.py and research/entry_study/param_defs/<NAME>.py.

Synthetic bars only (no data files, no network): schema, shapes, NaN-safety, causality of strength(),
default signals() == the locked strategy (sweep_lib registry; DOGE through paperbot.sigservice.doge_join),
timeframe handling (V45 higher-timeframe frame, DOGE length scaling) and the variant rules."""

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

NAMES = ["OBV_B", "V39_ALL", "V45_AMB", "DOGE"]
KINDS = {"length", "mult", "threshold_neutral", "threshold_abs"}
MULTS = (0.5, 0.75, 1.25, 1.5)
FREQ = {"15m": "15min", "1h": "1h", "4h": "4h"}
WARM = 300


def _load(kind: str, name: str):
    path = os.path.join(ROOT, "research", "entry_study", kind, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_test_obvbbatch_{kind}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = {n: _load("strength_defs", n) for n in NAMES}
PD = {n: _load("param_defs", n) for n in NAMES}


def synth(n: int, seed: int, tf: str = "1h", start: str = "2024-01-01 00:00") -> pd.DataFrame:
    """Random walk with drifting regimes and occasional shocks (crosses, pullbacks, trend runs)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.004, n // 150 + 1), 150)[:n]
    shock = np.where(rng.random(n) < 0.01, rng.normal(0, 0.05, n), 0.0)
    c = 100 * np.exp(np.cumsum(drift + shock + rng.normal(0, 0.01, n)))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    v = rng.lognormal(3, 0.6, n)
    ts = pd.date_range(start, periods=n, freq=FREQ[tf], tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v})


@pytest.fixture(scope="module")
def bars():
    return synth(3000, 1)


def _locked(name, df, tf):
    """The locked signal as the caches hold it: compute_signals on the chart bars; DOGE = doge_join(DOGE_L, DOGE_S)."""
    from paperbot.sigservice import doge_join
    d = df.copy()
    d.attrs["tf"] = tf
    if name == "DOGE":
        raw = L.compute_signals({"X": d}, tf, ["DOGE_L", "DOGE_S"], strict=True)
        s = doge_join(raw["DOGE_L"]["X"], raw["DOGE_S"]["X"])
    else:
        s = L.compute_signals({"X": d}, tf, [name], strict=True)[name]["X"]
    return s > 0, s < 0


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
@pytest.mark.parametrize("tf", ["15m", "1h"])
def test_strength_shapes_and_finite_at_signals(name, tf):
    df = synth(3000, 2, tf)
    st = SD[name].strength(df, tf)
    assert list(st) == [f["name"] for f in SD[name].FEATURES]
    lg, sh = PD[name].signals(df, tf)
    assert lg.sum() + sh.sum() > 0
    post = np.arange(len(df)) >= WARM
    for f, (vl, vs) in st.items():
        for v in (vl, vs):
            assert isinstance(v, np.ndarray) and v.dtype == float and v.shape == (len(df),)
            assert not np.isinf(v).any()
        assert np.isfinite(vl[lg & post]).all(), f
        assert np.isfinite(vs[sh & post]).all(), f


def test_strength_bounds_on_signal_bars():
    """Features that measure 'how far past the rule' respect the rule wherever it fired."""
    bounds = {"OBV_B": {"obv_cross_vol": 0.0, "ac_atr": 0.0, "stc_room": 0.0},
              "V39_ALL": {"st_dist_atr": -1e-9},
              "V45_AMB": {"stc_room": 0.0, "pullback_angle": 1.0, "macd_hist_atr": 0.0},
              "DOGE": {"ema_spread_pct": 0.0, "k_depth": 0.0, "rsi_margin": 0.0}}
    strict = {"OBV_B": {"obv_cross_vol", "ac_atr", "stc_room"}, "V45_AMB": {"stc_room", "macd_hist_atr"},
              "DOGE": {"ema_spread_pct", "k_depth", "rsi_margin"}}
    for seed in (1, 2, 3):
        for tf in ("15m", "1h"):
            df = synth(3000, seed, tf)
            for name, fb in bounds.items():
                st = SD[name].strength(df, tf)
                lg, sh = PD[name].signals(df, tf)
                for f, b in fb.items():
                    x = np.r_[st[f][0][lg], st[f][1][sh]]
                    x = x[~np.isnan(x)]
                    if f in strict.get(name, ()):
                        assert (x > b).all(), (name, f, seed, tf)
                    else:
                        assert (x >= b).all(), (name, f, seed, tf)


def test_obv_b_features_match_the_rule(bars):
    import pine_indicators as pi
    st = SD["OBV_B"].strength(bars, "1h")
    c, v = bars["close"].to_numpy(float), bars["volume"].to_numpy(float)
    o = pi.obv(c, v)
    ma, vm = pi.pine_sma(o, 9), pi.pine_sma(v, 9)
    ok = np.isfinite(ma) & np.isfinite(vm)
    assert np.allclose(st["obv_cross_vol"][0][ok], ((o - ma) / vm)[ok])
    for f in ("obv_cross_vol", "ac_atr"):
        vl, vs = st[f]
        m = ~np.isnan(vl)
        assert np.array_equal(m, ~np.isnan(vs)) and np.allclose(vl[m], -vs[m])
    vl, vs = st["stc_room"]
    assert np.allclose(vl + vs, 40.0)          # (70 - stc) + (stc - 30)


def test_v39_st_side(bars):
    import pine_indicators as pi
    st = SD["V39_ALL"].strength(bars, "1h")
    h, lo, c = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    _line, d3 = pi.exchange_supertrend(h, lo, c, 10, 3.0)
    dl, ds_ = st["st_dist_atr"]
    assert np.isnan(dl[d3 == -1]).all() and np.isnan(ds_[d3 == 1]).all()
    assert np.isfinite(dl[(d3 == 1) & (np.arange(len(c)) >= 20)]).all()
    for f in ("di_gap", "chop_angle"):
        vl, vs = st[f]
        m = ~np.isnan(vl)
        assert np.allclose(vl[m], -vs[m])


def test_v45_stc_room_uses_both_frames(bars):
    import pine_indicators as pi
    st = SD["V45_AMB"].strength(bars, "1h")
    htf = L.HTF_OF["1h"]
    _d, stc_h = L.v45_htf_components(bars, L.resample_ohlcv(bars, htf), htf, "closed")
    stc_c = pi.stc(bars["close"].to_numpy(float), 12, 26, 50, 0.5)
    vl, vs = st["stc_room"]
    assert np.isnan(vl[np.isnan(stc_h)]).all()
    m = np.isfinite(stc_h)
    assert np.allclose(vl[m], 75.0 - np.maximum(stc_c, stc_h)[m])
    assert np.allclose(vs[m], np.minimum(stc_c, stc_h)[m] - 25.0)


def test_doge_long_array_follows_the_rule_that_fired():
    """Cached DOGE long signals include the short-rule bars; there the long array carries the short-rule value."""
    df = synth(3000, 1, "1h")
    st = SD["DOGE"].strength(df, "1h")
    lr, sr = PD["DOGE"].rule_signals(df, "1h")
    assert lr.sum() > 0 and sr.sum() > 0
    for f, (vl, vs) in st.items():
        assert np.array_equal(vl[sr], vs[sr], equal_nan=True), f
        assert not np.allclose(vl[lr], vs[lr]), f


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("n", [0, 1, 2, 5, 30])
def test_nan_safety_short_series(name, n):
    df = synth(max(n, 1), 7).iloc[:n].reset_index(drop=True)
    st = SD[name].strength(df, "1h")
    assert list(st) == [f["name"] for f in SD[name].FEATURES]
    for vl, vs in st.values():
        assert vl.shape == (n,) and vs.shape == (n,)
        assert vl.dtype == float and vs.dtype == float
    lg, sh = PD[name].signals(df, "1h")
    assert lg.shape == (n,) and sh.shape == (n,) and lg.dtype == bool and sh.dtype == bool


@pytest.mark.parametrize("name", NAMES)
def test_nan_safety_flat_and_gappy_bars(name):
    df = synth(900, 11)
    df.loc[200:260, ["open", "high", "low", "close"]] = 50.0      # flat stretch: ATR -> 0, zero ranges
    df.loc[300:330, "volume"] = 0.0                               # zero volume (OBV_B volume mean)
    df = df.drop(index=range(500, 520)).reset_index(drop=True)    # a data gap (partial HTF bins for V45)
    st = SD[name].strength(df, "1h")
    for vl, vs in st.values():
        assert not np.isinf(vl).any() and not np.isinf(vs).any()
    lg, sh = PD[name].signals(df, "1h")
    rl, rs = _locked(name, df, "1h")
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", [3, 4])
def test_strength_causal(name, seed):
    df = synth(1500, seed, "1h", start="2024-01-01 01:00")
    full = SD[name].strength(df, "1h")
    rng = np.random.default_rng(seed)
    cuts = [int(k) for k in rng.integers(20, len(df) - 1, size=5)]
    cuts += [int(np.flatnonzero(df["ts"].dt.hour.to_numpy() % 4 == 0)[50]) + d for d in (0, 1)]  # 4h HTF edge
    for k in sorted(cuts):
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
@pytest.mark.parametrize("tf", ["15m", "1h", "4h"])
@pytest.mark.parametrize("seed", [1, 5])
def test_default_signals_equal_locked(name, tf, seed):
    df = synth(3000, seed, tf)
    lg, sh = PD[name].signals(df, tf)
    rl, rs = _locked(name, df, tf)
    assert lg.dtype == bool and sh.dtype == bool
    assert np.array_equal(lg, rl) and np.array_equal(sh, rs)
    assert not (lg & sh).any()


def test_doge_sides_are_the_rules_own_sides():
    """DOGE goes long on the long rule and SHORT on the short rule (the old long-only join was a bug)."""
    df = synth(3000, 1, "1h")
    d = df.copy()
    d.attrs["tf"] = "1h"
    lr, sr = PD["DOGE"].rule_signals(df, "1h")
    ref_l, _z = L.doge_long(d)
    _z, ref_s = L.doge_short(d)
    assert np.array_equal(lr, ref_l) and np.array_equal(sr, ref_s)
    assert lr.sum() > 0 and sr.sum() > 0 and not (lr & sr).any()
    assert PD["DOGE"].JOIN_AS_CACHED is False
    lg, sh = PD["DOGE"].signals(df, "1h")
    assert np.array_equal(lg, lr) and np.array_equal(sh, sr)


@pytest.mark.parametrize("tf", ["5m", "15m", "30m", "1h", "4h", "1d"])
def test_doge_lengths_match_locked_scaling(tf):
    p = PD["DOGE"].doge_params(tf)
    ref = L.doge_params(tf)
    assert {k: p[k] for k in ref} == ref
    assert p["spread_min"] == 0.15 and p["chop_max"] == 61.8


def test_doge_length_variants_scale_like_the_locked_rule():
    mod = PD["DOGE"]
    got = {tf: [mod.doge_params(tf, **ov)["ema_slow"] for ov in mod.variants("ema_slow")] for tf in ("15m", "1h", "4h")}
    assert got == {"15m": [26, 39, 65, 78], "1h": [7, 10, 16, 20], "4h": [2, 2, 4, 5]}
    got = {tf: [mod.doge_params(tf, **ov)["stoch_len"] for ov in mod.variants("stoch_len")] for tf in ("15m", "1h", "4h")}
    assert got == {"15m": [12, 18, 29, 35], "1h": [3, 4, 7, 9], "4h": [2, 2, 2, 2]}
    for ov in mod.variants("ema_slow") + mod.variants("stoch_len"):        # only the varied length moves
        for tf in ("15m", "1h", "4h"):
            p, ref = mod.doge_params(tf, **ov), L.doge_params(tf)
            assert {k: v for k, v in p.items() if k in ref and k not in ov} == {k: v for k, v in ref.items() if k not in ov}


@pytest.mark.parametrize("tf", ["15m", "1h", "4h"])
def test_v45_htf_components_default_equals_locked(tf):
    df = synth(2000, 3, tf)
    htf, dfh = PD["V45_AMB"].htf_frame(df, tf)
    assert htf == L.HTF_OF[tf]
    a = PD["V45_AMB"].htf_components(df, dfh, htf)
    b = L.v45_htf_components(df, dfh, htf, "closed")
    for x, y in zip(a, b):
        assert np.array_equal(x, y, equal_nan=True)


def test_v45_st_mult_main_half_equals_strict_and_never_fires(bars):
    """x0.5 of the main multiplier (3.0) equals the strict one: the two chart SuperTrends coincide, no signal."""
    ov = PD["V45_AMB"].variants("st_mult_main")[0]
    assert ov == {"st_mult_main": 3.0}
    lg, sh = PD["V45_AMB"].signals(bars, "1h", **ov)
    assert not lg.any() and not sh.any()


def test_v45_uses_the_next_timeframe(bars):
    """Same chart bars, different chart timeframe label -> different HTF frame -> the tf argument matters."""
    a = PD["V45_AMB"].signals(bars, "1h")
    b = PD["V45_AMB"].signals(bars, "15m")
    rl, rs = _locked("V45_AMB", bars, "15m")
    assert np.array_equal(b[0], rl) and np.array_equal(b[1], rs)
    assert not (np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]))


@pytest.mark.parametrize("name", ["OBV_B", "V39_ALL"])
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
        assert "third_party/sweep/harness/" in p["where"] and ":" in p["where"]
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
    assert got["OBV_B"]["break_len"] == [5, 7, 11, 14]            # 4.5 -> 5, 6.75 -> 7, 11.25 -> 11, 13.5 -> 14
    assert got["OBV_B"]["ao_fast"] == [3, 4, 6, 8]                # 2.5 -> 3, 3.75 -> 4, 6.25 -> 6, 7.5 -> 8
    assert got["OBV_B"]["ao_slow"] == [17, 26, 43, 51]            # 25.5 -> 26, 42.5 -> 43
    assert got["OBV_B"]["ac_len"] == [3, 4, 6, 8]
    assert np.allclose(got["V39_ALL"]["st_mult"], [1.5, 2.25, 3.75, 4.5])
    assert got["V39_ALL"]["dmi_len"] == [10, 15, 25, 30]
    assert np.allclose(got["V39_ALL"]["dmi_gap"], [1.0, 1.5, 2.5, 3.0])
    assert got["V39_ALL"]["stoch_len"] == [7, 11, 18, 21]         # 10.5 -> 11, 17.5 -> 18
    assert np.allclose(got["V45_AMB"]["st_mult_main"], [3.0, 4.5, 7.5, 9.0])
    assert np.allclose(got["V45_AMB"]["st_mult_strict"], [1.5, 2.25, 3.75, 4.5])
    assert np.allclose(got["V45_AMB"]["htf_st_mult"], [3.0, 4.5, 7.5, 9.0])
    assert got["V45_AMB"]["stoch_len"] == [7, 11, 18, 21]
    assert got["DOGE"]["ema_slow"] == [78, 117, 195, 234]         # 5-minute base lengths
    assert got["DOGE"]["stoch_len"] == [35, 53, 88, 105]          # 52.5 -> 53, 87.5 -> 88
    assert np.allclose(got["DOGE"]["spread_min"], [0.075, 0.1125, 0.1875, 0.225])
    assert np.allclose(got["DOGE"]["chop_max"], [30.9, 46.35, 77.25, 92.7])


@pytest.mark.parametrize("name", NAMES)
def test_variants_run_and_move_signals(name):
    mod = PD[name]
    df = synth(8000, 2, "1h")
    base = mod.signals(df, "1h")
    moved = 0
    for p in mod.PARAMS:
        for ov in mod.variants(p):
            lg, sh = mod.signals(df, "1h", **ov)
            assert lg.shape == (len(df),) and lg.dtype == bool and sh.dtype == bool
            assert not (lg & sh).any()
            moved += int(not (np.array_equal(lg, base[0]) and np.array_equal(sh, base[1])))
    assert moved >= 14, moved


@pytest.mark.parametrize("name", NAMES)
def test_explicit_defaults_equal_no_override(name, bars):
    mod = PD[name]
    a = mod.signals(bars, "1h")
    b = mod.signals(bars, "1h", **{p["name"]: p["default"] for p in mod.PARAMS})
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


@pytest.mark.parametrize("name", NAMES)
def test_unknown_override_rejected(name, bars):
    with pytest.raises(ValueError):
        PD[name].signals(bars, "1h", not_a_param=1)
