"""research/fullgrid/ds_defs.py: the parameterized DeepSeek-200 entries.

- default parity with research/deepseek200/lib_c.py entries, bar for bar, both sides, with and without a shared cache
  (synthetic 15m / 30m / 1h / 4h; a BTC coin; a coin without BTC context; the Binance bars when present)
- overrides equal lib_c with its module constants patched (SW + pivots_conf's default k, EXP, FVG_MIN_ATR,
  ZONE_ATR_LEG, LEG_MAX_BARS, ORB_BARS, PO3_RANGE_MIN, PO3_REVERSAL_BARS)
- every parameter changes the signals (inert ones printed, a few allowed); bad overrides raise ValueError
- look-ahead: overridden signals on a truncated / junk-tailed frame equal the full frame's before the cut
- speed per call, cold and warm cache (printed, loose bound only)

Synthetic data only, except test_real_data_parity (skipped when the bar files are absent).
"""

from __future__ import annotations

import importlib.util
import math
import os
import time

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("fullgrid_ds_defs", os.path.join(ROOT, "research", "fullgrid", "ds_defs.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)
C = D.C                                          # the lib_c module ds_defs loaded (one object: no double load)

BARS = os.environ.get("DS_DEFS_BARS", "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f"
                                      "/scratchpad/binance/bars")
SYN_N = {"15m": 8000, "30m": 6000, "1h": 6000, "4h": 5000}
KINDS = {"length", "mult", "threshold_abs", "threshold_neutral"}

# the parameter list of every definition, in order (fixed by the study design)
EXPECTED = {
    "F1_RSI_DIV": ["swing_k", "div_max_bars", "rsi_len"], "F1_MOM_DIV": ["swing_k", "div_max_bars", "mom_len"],
    "F1_PVT_DIV": ["swing_k", "div_max_bars"], "F2_DEMARK": [],
    "F3_BOS": ["swing_k"], "F3_BOS_ZONE": ["swing_k", "zone_life", "ema_len"], "F3_HHHL": ["swing_k"],
    "F4_PULL": ["ema_fast", "ema_mid", "ema_slow"], "F4_PULL_RSI": ["ema_fast", "ema_slow", "rsi_len", "rsi_level"],
    "F4_FAN": ["fan_lens"],
    "F5_BOX": ["box_len", "adx_max", "edge", "width_atr"], "F5_BOX_RSI": ["box_len", "adx_max", "edge", "rsi_level"],
    "F5_BOX_HTF": ["box_len", "adx_max", "edge", "width_atr"],
    "F6_VWAP_CROSS": [], "F6_VWAP_FAIL": ["fail_bars"],
    "F7_RF_TRIPLE": ["rf_period", "rf_mult"], "F7_RF_ONLY": ["rf_period", "rf_mult"],
    "F8_VWICK": ["body_frac", "body_atr", "zone_life"],
    "F9_FVG": ["fvg_min_atr", "zone_life"], "F9_IFVG": ["fvg_min_atr", "zone_life"], "F9_OB": ["zone_life"],
    "F9_BREAKER": ["zone_life"],
    "F10_M2022": ["swing_k", "disp_atr", "sweep_bars", "fvg_min_atr"], "F10_OTE": ["swing_k", "leg_atr", "leg_max_bars"],
    "F11_TSOUP": ["tsoup_len", "min_age"], "F11_RAID": ["swing_k"], "F11_PO3": ["po3_range_h", "po3_rev_bars"],
    "F12_MSS": ["swing_k"], "F12_MSS_DISP": ["swing_k", "disp_atr"],
    "F13_FVG_PD": ["swing_k", "fvg_min_atr", "zone_life"], "F13_RAID_PD": ["swing_k"],
    "F14_SMT": ["smt_len"],
    "F15_ASIA_BRK": ["asia_win_h"], "F15_ASIA_SWEEP": ["asia_win_h"], "F15_LON_BRK": ["lon_win_h"],
    "F15_OPEN0930": ["judge_min"], "F15_OPEN0000": ["judge_min"], "F15_ORB": ["orb_bars"],
    **{f: ["swing_k", "leg_atr", "leg_max_bars", "zone_life"] for f in ("F16_FIB382", "F16_FIB500", "F16_FIB618", "F16_FIB764")},
    "F17_Z": ["z_len", "z_level"], "F17_Z_HL": ["z_len", "z_level", "hl_len", "half_life"],
}


def _eq(a, b) -> bool:
    return np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def _vary(spec: dict, m: float):
    """The parameter at m x its default (threshold_neutral: neutral + m x (default - neutral)); None when the value
    leaves the declared bounds or rounds back to the default."""
    d, kind = spec["default"], spec["kind"]
    lo, hi = spec.get("bounds", (0.0, math.inf))
    if kind == "length":
        if isinstance(d, list):
            v = [max(1, int(math.floor(x * m + 0.5))) for x in d]
        else:
            v = min(max(1, int(math.floor(d * m + 0.5))), hi)
    elif kind in ("mult", "threshold_abs"):
        v = d * m
        if not lo < v <= hi:
            return None
    else:
        v = spec["neutral"] + m * (d - spec["neutral"])
        if not lo <= v <= hi:
            return None
    return None if v == d else v


def _variant(name: str, m: float) -> dict:
    """Every parameter of ``name`` at m x (those that cannot move stay at the default)."""
    out = {}
    for s in D.DEFS[name]:
        v = _vary(s, m)
        if v is not None:
            out[s["name"]] = v
    return out


# ------------------------------------------------------------------ declarations
def test_defs_declared():
    assert list(D.DEFS) == list(C.DEF_IDS) and len(D.DEFS) == 44
    assert D.TFS_OF == {d: tuple(t) for d, _f, t in C.DEFS}
    for name, ps in D.DEFS.items():
        assert [p["name"] for p in ps] == EXPECTED[name], name
        for p in ps:
            assert set(p) - {"bounds"} == {"name", "default", "kind", "neutral", "where"}, (name, p)
            assert p["kind"] in KINDS and p["where"]
            assert (p["neutral"] is None) == (p["kind"] != "threshold_neutral"), (name, p["name"])
            if "bounds" in p:
                lo, hi = p["bounds"]
                d = p["default"]
                assert lo < (d if not isinstance(d, list) else min(d)) <= hi
    defaults = {p["name"]: p["default"] for ps in D.DEFS.values() for p in ps if p["name"] not in
                ("ema_fast", "ema_slow", "rsi_level")}
    assert defaults == {"swing_k": 3, "div_max_bars": 60, "rsi_len": 14, "mom_len": 10, "zone_life": 50, "ema_len": 200,
                        "ema_mid": 50, "fan_lens": [8, 13, 21, 34, 55], "box_len": 48, "adx_max": 20.0, "edge": 0.15,
                        "width_atr": 3.0, "fail_bars": 10, "rf_period": 100, "rf_mult": 3.0, "body_frac": 0.7,
                        "body_atr": 1.3, "fvg_min_atr": 0.5, "disp_atr": 1.2, "sweep_bars": 20, "leg_atr": 3.0,
                        "leg_max_bars": 30, "tsoup_len": 20, "min_age": 4, "po3_range_h": 8, "po3_rev_bars": 3,
                        "smt_len": 20, "asia_win_h": 8, "lon_win_h": 7, "judge_min": 60, "orb_bars": 2, "z_len": 20,
                        "z_level": 2.0, "hl_len": 100, "half_life": 20}
    by = {(n, p["name"]): p for n, ps in D.DEFS.items() for p in ps}
    assert (by["F4_PULL", "ema_fast"]["default"], by["F4_PULL", "ema_slow"]["default"]) == (9, 200)
    assert (by["F4_PULL_RSI", "ema_fast"]["default"], by["F4_PULL_RSI", "ema_slow"]["default"]) == (20, 50)
    assert (by["F4_PULL_RSI", "rsi_level"]["default"], by["F4_PULL_RSI", "rsi_level"]["neutral"]) == (40.0, 50.0)
    assert (by["F5_BOX_RSI", "rsi_level"]["default"], by["F5_BOX_RSI", "rsi_level"]["neutral"]) == (30.0, 50.0)


def test_bad_calls_raise():
    df = C.synth(600, "1h", 1)
    with pytest.raises(ValueError, match="unknown parameter"):
        D.signals(df, "1h", "F3_BOS", swing_kk=4)
    with pytest.raises(ValueError, match="unknown parameter"):
        D.signals(df, "1h", "F2_DEMARK", swing_k=4)
    with pytest.raises(ValueError):
        D.signals(df, "1h", "F3_BOS", swing_k=2.5)
    with pytest.raises(ValueError):
        D.signals(df, "1h", "F3_BOS", swing_k=0)
    with pytest.raises(ValueError):
        D.signals(df, "1h", "F4_FAN", fan_lens=[8, 13, 21])
    with pytest.raises(ValueError):
        D.signals(df, "1h", "NOPE")
    with pytest.raises(ValueError):
        D.signals(df, "4h", "F15_ASIA_BRK")
    cache = {}
    D.signals(df, "1h", "F3_BOS", cache=cache)
    with pytest.raises(ValueError, match="another series"):
        D.signals(C.synth(600, "1h", 2), "1h", "F3_BOS", cache=cache)


# ------------------------------------------------------------------ default parity
@pytest.mark.parametrize("tf", ["15m", "30m", "1h", "4h"])
def test_default_parity_synthetic(tf):
    P = C.synth_panel(SYN_N[tf], tf, 3)
    btc = {"BTCUSD": P["BTCUSD"]}
    silent = []
    for coin, ctx in (("ETHUSD", btc), ("BTCUSD", btc), ("SOLUSD", None)):
        df = P[coin]
        want = C.entries(df, tf, ctx, coin)
        assert set(want) == {d for d, tfs in D.TFS_OF.items() if tf in tfs}
        cache = {}
        for name in want:
            for cc in (cache, None):
                got = D.signals(df, tf, name, ctx, coin, cc)
                assert got[0].dtype == bool and got[0].shape == (len(df),)
                assert _eq(got, want[name]), f"{tf} {coin} {name} cache={cc is not None}"
            if coin == "ETHUSD" and not (want[name][0].any() or want[name][1].any()):
                silent.append(name)
        again = D.signals(df, tf, "F16_FIB618", ctx, coin, cache)   # a returned array is never the cached one
        again[0][:] = True
        assert _eq(D.signals(df, tf, "F16_FIB618", ctx, coin, cache), want["F16_FIB618"])
    print(f"\n{tf}: definitions without a signal on the ETH series: {silent}")
    assert len(silent) <= 1, silent


@pytest.mark.skipif(not os.path.exists(os.path.join(BARS, "ethusd-15m.csv.gz")), reason="Binance bar files not present")
@pytest.mark.parametrize("tf", ["15m", "30m", "1h", "4h"])
def test_real_data_parity(tf):
    L = C.env()["L"]
    pth = {c: os.path.join(BARS, f"{c.lower()}-{tf}.csv.gz") for c in ("ETHUSD", "BTCUSD")}
    if not all(os.path.exists(p) for p in pth.values()):
        pytest.skip(f"{tf} bar files not present")
    fr = {c: L.read_ohlcv(p).tail(20000).reset_index(drop=True) for c, p in pth.items()}
    ctx = {"BTCUSD": fr["BTCUSD"]}
    for coin in ("ETHUSD", "BTCUSD"):
        df = fr[coin]
        want = C.entries(df, tf, ctx, coin)
        cache = {}
        for name in want:
            assert _eq(D.signals(df, tf, name, ctx, coin, cache), want[name]), f"{tf} {coin} {name}"


# ------------------------------------------------------------------ overrides
_SWING = [n for n, ps in EXPECTED.items() if "swing_k" in ps]
_LIFE = [n for n, ps in EXPECTED.items() if "zone_life" in ps]
_FVG = [n for n, ps in EXPECTED.items() if "fvg_min_atr" in ps]
_LEG = [n for n, ps in EXPECTED.items() if "leg_atr" in ps]
PATCHES = (
    [({"SW": k}, {"swing_k": k}, _SWING) for k in (2, 5)]
    + [({"EXP": e}, {"zone_life": e}, _LIFE) for e in (17, 100, 200)]          # 200 > HORIZON: tables rebuilt
    + [({"FVG_MIN_ATR": x}, {"fvg_min_atr": x}, _FVG) for x in (0.25, 1.0)]
    + [({"ZONE_ATR_LEG": 1.5}, {"leg_atr": 1.5}, _LEG), ({"LEG_MAX_BARS": 12}, {"leg_max_bars": 12}, _LEG)]
    + [({"ORB_BARS": b}, {"orb_bars": b}, ["F15_ORB"]) for b in (1, 5)]
    + [({"PO3_RANGE_MIN": h * 60, "PO3_REVERSAL_BARS": r}, {"po3_range_h": h, "po3_rev_bars": r}, ["F11_PO3"])
       for h, r in ((4, 3), (12, 1))]
)


@pytest.mark.parametrize("tf", ["15m", "1h", "4h"])
def test_overrides_equal_patched_lib_c(tf, monkeypatch):
    """lib_c's module-level numbers patched -> lib_c.entries is the parameterized rule; ds_defs must agree. SW needs
    pivots_conf's default k patched too (bound when lib_c was loaded). F10_M2022 / F10_OTE keep zone life 50 here."""
    P = C.synth_panel(3500, tf, 7)
    df, ctx, coin = P["SOLUSD"], {"BTCUSD": P["BTCUSD"]}, "SOLUSD"
    cache = {}
    for patch, ov, names in PATCHES:
        with monkeypatch.context() as mp:
            for k, v in patch.items():
                mp.setattr(C, k, v)
                if k == "SW":
                    mp.setattr(C.pivots_conf, "__defaults__", (v,))
            want = C.entries(df, tf, ctx, coin)
        for name in names:
            if name in want and not (name.startswith("F10") and "zone_life" in ov):
                assert _eq(D.signals(df, tf, name, ctx, coin, cache, **ov), want[name]), f"{tf} {ov} {name}"
    assert _eq(D.signals(df, tf, "F16_FIB500", ctx, coin, cache), C.entries(df, tf, ctx, coin)["F16_FIB500"])


def test_each_parameter_changes_signals():
    """Each parameter alone at 1/3x, 0.5x, 2x and 3x (values outside its bounds dropped): at least one changes the
    signal set. Results with and without the cache agree for every variant. A few parameters may be inert on these
    series and are printed: e.g. F1 div_max_bars only bites when two consecutive swing pivots are far apart (at
    swing_k 3 they are at most ~50 bars apart even on 5 years of real 15m bars; at swing_k 9 a third are > 30)."""
    out = {}
    for tf, n in (("1h", 6000), ("15m", 8000)):
        P = C.synth_panel(n, tf, 11)
        df, ctx, coin = P["ETHUSD"], {"BTCUSD": P["BTCUSD"]}, "ETHUSD"
        cache = {}
        for name, ps in D.DEFS.items():
            if tf not in D.TFS_OF[name] or (tf == "15m" and not name.startswith(("F15", "F11_PO3"))):
                continue
            base = D.signals(df, tf, name, ctx, coin, cache)
            for s in ps:
                vals = [v for v in (_vary(s, m) for m in (1 / 3, 0.5, 2.0, 3.0)) if v is not None]
                assert len(vals) >= 2, (name, s["name"])
                changed = False
                for v in vals:
                    got = D.signals(df, tf, name, ctx, coin, cache, **{s["name"]: v})
                    assert _eq(got, D.signals(df, tf, name, ctx, coin, None, **{s["name"]: v})), (name, s["name"], v)
                    changed |= not _eq(got, base)
                out[(tf, name, s["name"])] = changed
    inert = sorted(k for k, ch in out.items() if not ch)
    print(f"\n{sum(out.values())} of {len(out)} (timeframe, definition, parameter) cases change the signals; inert: {inert}")
    assert len(inert) <= 3, inert
    # div_max_bars is threaded through: with far-apart pivots (swing_k 9) a short limit drops divergences
    P = C.synth_panel(6000, "1h", 11)
    for name in ("F1_RSI_DIV", "F1_PVT_DIV", "F1_MOM_DIV"):
        wide = D.signals(P["ETHUSD"], "1h", name, swing_k=9)
        assert not _eq(D.signals(P["ETHUSD"], "1h", name, swing_k=9, div_max_bars=20), wide), name


# ------------------------------------------------------------------ look-ahead
def _junk_tail(df, cut, rng):
    d = df.copy()
    for k in ("open", "high", "low", "close"):
        d.loc[d.index[cut:], k] = d[k].to_numpy()[cut:] * rng.uniform(0.5, 1.5, len(d) - cut)
    d.loc[d.index[cut:], "volume"] = rng.lognormal(0, 1, len(d) - cut) * 100
    return d


@pytest.mark.parametrize("tf,n,names", [
    ("1h", 3000, [d for d in D.DEFS if not d.startswith("F15")]),
    ("15m", 4000, [d for d in D.DEFS if d.startswith(("F15", "F11_PO3", "F14", "F5_BOX_HTF", "F7_RF_TRIPLE"))]),
])
def test_lookahead_overridden(tf, n, names):
    """Signals at bar t use bars <= t only, for overridden values too: a frame cut after t (or with junk after the cut,
    BTC context included) gives the same signals before the cut (no margin needed)."""
    df, btc = C.synth(n, tf, 21), C.synth(n, tf, 22)
    rng = np.random.default_rng(3)
    full_cache = {}
    frames = []
    for cut in (int(n * 0.55), int(n * 0.83)):
        frames.append((cut, df.iloc[:cut].copy(), btc.iloc[:cut].copy(), {}))
        frames.append((cut, _junk_tail(df, cut, rng), _junk_tail(btc, cut, rng), {}))
    for name in names:
        for m in (0.5, 2.0):
            ov = _variant(name, m)
            want = D.signals(df, tf, name, {"BTCUSD": btc}, "ETHUSD", full_cache, **ov)
            for cut, d2, b2, cc in frames:
                got = D.signals(d2, tf, name, {"BTCUSD": b2}, "ETHUSD", cc, **ov)
                for side in (0, 1):
                    assert np.array_equal(got[side][:cut], want[side][:cut]), f"look-ahead {name} {tf} {ov} cut={cut}"


# ------------------------------------------------------------------ speed (printed)
def test_speed_per_call():
    """cold: first call on a fresh cache (every block built); first use: a new value of the swept parameter (its blocks
    built); warm: the same calls again (every block cached: what most grid calls cost)."""
    tf, n = "15m", 20000
    P = C.synth_panel(n, tf, 5)
    df, ctx = P["ETHUSD"], {"BTCUSD": P["BTCUSD"]}
    rows = []
    for name, ov in (("F16_FIB618", [{"swing_k": k, "zone_life": z} for k in (2, 4) for z in (25, 75, 150)]),
                     ("F3_BOS_ZONE", [{"swing_k": k, "ema_len": e} for k in (2, 4) for e in (100, 300, 400)]),
                     ("F5_BOX", [{"box_len": b, "adx_max": a} for b in (24, 96) for a in (10.0, 25.0, 40.0)]),
                     ("F10_M2022", [{"swing_k": k, "disp_atr": x} for k in (2, 4) for x in (0.6, 1.5, 2.4)])):
        cache = {}
        t0 = time.perf_counter()
        D.signals(df, tf, name, ctx, "ETHUSD", cache)
        cold = time.perf_counter() - t0
        tt = []
        for _ in range(2):
            t0 = time.perf_counter()
            for o in ov:
                D.signals(df, tf, name, ctx, "ETHUSD", cache, **o)
            tt.append((time.perf_counter() - t0) / len(ov))
        rows.append((name, cold, tt[0], tt[1]))
    print("\nper call on 20,000 15m bars: " + "; ".join(
        f"{nm} cold {c * 1e3:.1f} ms, first use {f * 1e3:.1f} ms, warm {w * 1e3:.2f} ms" for nm, c, f, w in rows))
    assert all(w < 0.5 for *_x, w in rows)
