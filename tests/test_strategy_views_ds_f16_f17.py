"""Chart views of the DeepSeek-200 F16 / F17 definitions (paperbot/strategy_view_defs/DS_F16_*.py, DS_F17_*.py): AND of
each side's conditions equals the research signal (lib_c.entries) on every bar.

lib_c.py is loaded by path under a private module name inside entry_marks._contained(): its import inserts into
sys.path and sets warnings filters, and both are restored. The fast tests use synthetic bars (a few bars missing).
The real-data tests read the Binance bar files in DS_BARS_DIR (<coin>-5m.csv.gz, and <coin>-<tf>.csv.gz when present):
the live service's frames (the last config.DS_WINDOW_5M[tf] 5m bars, resampled by paperbot.dssig.frame) and the last
20,000 bars of the 15m / 1h files. They are skipped without it.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_C = os.path.join(ROOT, "research", "deepseek200", "lib_c.py")
IDS = ("F16_FIB382", "F16_FIB500", "F16_FIB618", "F16_FIB764", "F17_Z", "F17_Z_HL")
_LIVE: dict = {}      # {id: signals} summed over the live-window cases (test_every_definition_fires_live)
FIB = {"F16_FIB382": 0.382, "F16_FIB500": 0.5, "F16_FIB618": 0.618, "F16_FIB764": 0.764}
TFS = (("15m", "15min", 4000), ("30m", "30min", 3000), ("1h", "1h", 3000), ("4h", "4h", 2000))
BARS = os.environ.get("DS_BARS_DIR", "")


@pytest.fixture(scope="module")
def lib_c():
    from paperbot import sweepsig
    from paperbot.entry_marks import _contained
    sweepsig.lib()                     # the locked library first, as paperbot.dssig loads it
    path0, filters0 = list(sys.path), list(warnings.filters)
    name = "_test_ds_views_f16_f17_lib_c"
    spec = importlib.util.spec_from_file_location(name, LIB_C)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        with _contained():
            spec.loader.exec_module(mod)
            mod.env()
    except BaseException:
        sys.modules.pop(name, None)
        raise
    assert sys.path == path0, "lib_c left sys.path changed"
    assert warnings.filters == filters0, "lib_c left the warnings filters changed"
    yield mod
    sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def views():
    from paperbot import sweepsig
    sweepsig.lib()                     # the view modules import the vendored indicator code
    return {i: getattr(importlib.import_module(f"paperbot.strategy_view_defs.DS_{i}"), f"view_DS_{i}") for i in IDS}


def synth(n: int, freq: str, seed: int = 7, drop: int = 6, wick: float = 0.002) -> pd.DataFrame:
    """Fat-tailed random walk with gapped opens and wicks of about ``wick``; ``drop`` bars removed at random."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.004))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, wick, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, wick, n)))
    df = pd.DataFrame({"ts": pd.date_range("2025-03-01", periods=n, freq=freq, tz="UTC"), "open": o, "high": h,
                       "low": lo, "close": c, "volume": rng.uniform(1, 10, n)})
    if drop:
        df = df.drop(index=rng.choice(np.arange(100, n), drop, replace=False)).reset_index(drop=True)
    return df


def AND(conds, n: int) -> np.ndarray:
    out = np.ones(n, bool)
    for _label, arr in conds:
        a = np.asarray(arr)
        assert a.dtype == bool and a.shape == (n,)
        out &= a
    return out


def check(lib_c, views, df: pd.DataFrame, tf: str, coin: str = "ETHUSD") -> dict:
    """{id: (long signals, short signals)} after asserting AND(conditions) == lib_c on every bar."""
    df = df.reset_index(drop=True)
    df.attrs["tf"] = tf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        R = lib_c.entries(df.copy(), tf, None, coin)
    out = {}
    for i in IDS:
        v = views[i](df.copy(), tf)
        for side, sig in zip(("long", "short"), R[i]):
            got = AND(v[side], len(df))
            bad = np.flatnonzero(got != sig)
            assert not len(bad), f"{i} {tf} {side}: {len(bad)} bars differ, first {bad[:5].tolist()}"
        out[i] = (int(R[i][0].sum()), int(R[i][1].sum()))
    return out


# ------------------------------------------------------------------ definitions
def test_ids_and_parameters_are_lib_c_s(lib_c):
    tfs = {d: tuple(t) for d, _f, t in lib_c.DEFS}
    for i in IDS:
        assert i in lib_c.DEF_IDS and tfs[i] == ("15m", "30m", "1h", "4h")
    assert lib_c.FIB == FIB
    assert (lib_c.EXP, lib_c.SW, lib_c.ZONE_ATR_LEG, lib_c.LEG_MAX_BARS) == (50, 3, 3.0, 30)
    for i, f in FIB.items():
        mod = importlib.import_module(f"paperbot.strategy_view_defs.DS_{i}")
        assert mod._F == f and (mod._EXP, mod._SW, mod._LEG_ATR, mod._LEG_BARS) == (50, 3, 3.0, 30)


# ------------------------------------------------------------------ exactness
@pytest.mark.parametrize("tf,freq,n", TFS)
def test_and_of_conditions_equals_lib_c_on_synthetic_bars(lib_c, views, tf, freq, n):
    counts = check(lib_c, views, synth(n, freq), tf)
    for i, (nl, ns) in counts.items():
        assert nl > 0 and ns > 0, f"{i} {tf}: the synthetic bars give no {'long' if not nl else 'short'} signal"


def test_same_bar_long_and_short_rule_is_the_last_line_of_f16(lib_c, views):
    """lib_c drops both sides when they fire on one bar; for F16 the last line of each side carries that rule (it took
    out 0-5 bars per definition on the real series). Long wicks make a bar reach a long and a short line at once."""
    cancelled = 0
    for seed in (3, 4):
        df = synth(4000, "15min", seed=seed, wick=0.01)
        df.attrs["tf"] = "15m"
        for i in FIB:
            v = views[i](df.copy(), "15m")
            assert v["long"][-1][0] == "같은 봉 숏 신호 없음" and v["short"][-1][0] == "같은 봉 롱 신호 없음"
            cancelled += int((AND(v["long"][:-1], len(df)) & ~v["long"][-1][1]).sum())
        check(lib_c, views, df, "15m")
    assert cancelled > 0


def test_f16_lines_are_the_legs_fib_level(views):
    """On a bar with a long focus the drawn line is H - f x (H - L) of the drawn leg; the pane's depth reaches the
    line's level exactly when the close sits on it."""
    df = synth(4000, "1h", seed=3)
    for i, f in FIB.items():
        v = views[i](df.copy(), "1h")
        ov = {o["name"]: np.asarray(o["values"]) for o in v["overlays"]}
        H, L = ov["상승 구간 고점(넘으면 무효)"], ov["상승 구간 시작 저점"]
        r = ov[f"롱 {i[7:9]}.{i[9]}% 되돌림선" if f != 0.5 else "롱 50% 되돌림선"]
        on = np.isfinite(r)
        assert on.any() and np.allclose(r[on], H[on] - f * (H[on] - L[on]))
        assert (H[on] > L[on]).all()
        Hs, Ls = ov["하락 구간 시작 고점"], ov["하락 구간 저점(깨면 무효)"]
        rs = ov[f"숏 {i[7:9]}.{i[9]}% 되돌림선" if f != 0.5 else "숏 50% 되돌림선"]
        ons = np.isfinite(rs)
        assert ons.any() and np.allclose(rs[ons], Ls[ons] + f * (Hs[ons] - Ls[ons]))
        assert v["panes"][0]["levels"] == [0, round(f * 100, 1), 100]


def test_f17_gate_matters_and_z_lines_are_the_bollinger_bands(lib_c, views):
    df = synth(3000, "1h", seed=9)
    z = views["F17_Z"](df.copy(), "1h")
    hl = views["F17_Z_HL"](df.copy(), "1h")
    n = len(df)
    assert (AND(hl["long"], n) <= AND(z["long"], n)).all() and AND(hl["long"], n).sum() < AND(z["long"], n).sum()
    assert [k for k, _a in hl["long"]][:2] == [k for k, _a in z["long"]]
    up, _mid, dn, _bw = lib_c.env()["fg"].bollinger_bands(df["close"].astype(float), 20, 2.0)
    ov = {o["name"]: np.asarray(o["values"]) for o in z["overlays"]}
    assert np.allclose(ov["평균 + 표준편차 2배 (Z = +2)"], up.to_numpy(), equal_nan=True)
    assert np.allclose(ov["평균 − 표준편차 2배 (Z = −2)"], dn.to_numpy(), equal_nan=True)
    assert not (AND(z["long"], n) & AND(z["short"], n)).any()


def _frames_5m(coin: str):
    p = os.path.join(BARS, f"{coin.lower()}-5m.csv.gz")
    if not os.path.exists(p):
        pytest.skip(f"{p} missing")
    d5 = pd.read_csv(p)
    t5 = (pd.to_datetime(d5["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(np.int64)
    return (t5,) + tuple(d5[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
@pytest.mark.parametrize("coin,tf", [("BTCUSD", "15m"), ("ETHUSD", "1h"), ("LTCUSD", "4h"), ("BCHUSD", "30m")])
def test_and_of_conditions_equals_lib_c_on_live_windows(lib_c, views, coin, tf):
    dssig = pytest.importorskip("paperbot.dssig")
    from paperbot import sweepsig
    from paperbot.config import DS_WINDOW_5M
    cols = _frames_5m(coin)
    t5 = cols[0]
    total = (0, 0)
    for frac in (0.35, 0.7, 1.0):
        end = int(t5[0] + (t5[-1] - t5[0]) * frac) + 300_000
        boundary = end - end % dssig.TF_MS[tf]
        keep = cols[0] + 300_000 <= boundary
        df = dssig.frame(*(a[keep][-DS_WINDOW_5M[tf]:] for a in cols), tf=tf, lib=sweepsig.lib())
        counts = check(lib_c, views, df, tf, coin)
        for k, x in counts.items():                 # per definition, over every live case
            _LIVE[k] = _LIVE.get(k, 0) + x[0] + x[1]
        total = (total[0] + sum(x[0] for x in counts.values()), total[1] + sum(x[1] for x in counts.values()))
    assert total[0] > 0 and total[1] > 0


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-<tf>.csv.gz)")
@pytest.mark.parametrize("coin,tf", [("BTCUSD", "15m"), ("ETHUSD", "1h")])
def test_and_of_conditions_equals_lib_c_on_the_bar_files(lib_c, views, coin, tf):
    p = os.path.join(BARS, f"{coin.lower()}-{tf}.csv.gz")
    if not os.path.exists(p):
        pytest.skip(f"{p} missing")
    df = pd.read_csv(p).iloc[-20_000:].reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    counts = check(lib_c, views, df, tf, coin)
    assert all(nl > 0 and ns > 0 for nl, ns in counts.values())


# ------------------------------------------------------------------ shape, labels, render
def test_views_follow_the_strategy_view_contract(views, monkeypatch):
    import paperbot.strategy_views as sv
    df = synth(1500, "15min")
    monkeypatch.setattr(sv, "get_view", lambda name: views[name[3:]] if name[3:] in views else None)
    for i in IDS:
        d = df.copy()
        d.attrs["tf"] = "15m"
        v = views[i](d, "15m")
        assert set(v) == {"overlays", "panes", "long", "short"}, i
        assert 3 <= len(v["overlays"]) <= 6 and 1 <= len(v["panes"]) <= 2, i
        for o in v["overlays"]:
            assert o["name"] and len(o["values"]) == len(df), (i, o["name"])
        for p in v["panes"]:
            assert p["name"] and p["series"] and all(len(s["values"]) == len(df) for s in p["series"]), (i, p["name"])
        for side in ("long", "short"):
            labels = [k for k, _a in v[side]]
            assert 2 <= len(labels) <= 5 and len(set(labels)) == len(labels), (i, side)
            assert all(any("가" <= ch <= "힣" for ch in k) for k in labels), (i, side)   # Korean wording
        r = sv.render(f"DS_{i}", df, "15m", tail=300)
        json.dumps(r, ensure_ascii=False)
        assert [c["name"] for c in r["conditions"]["long"]] == [k for k, _a in v["long"]]
        assert any(o["data"] for o in r["overlays"]), i
        for o in r["overlays"]:
            assert all(np.isfinite(p["value"]) for p in o["data"] if "value" in p), (i, o["name"])


@pytest.mark.parametrize("n", [0, 1, 2, 3, 7, 25])
def test_views_run_on_very_short_frames(views, n):
    df = synth(60, "1h", drop=0).iloc[:n].reset_index(drop=True)
    for i in IDS:
        v = views[i](df.copy(), "1h")
        for o in v["overlays"]:
            assert len(o["values"]) == n
        for p in v["panes"]:
            assert all(len(s["values"]) == n for s in p["series"])
        for side in ("long", "short"):
            assert all(np.asarray(a).shape == (n,) for _k, a in v[side])
            if n < 21:
                assert not AND(v[side], n).any()


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
def test_every_definition_fires_on_the_live_windows():
    """The live-window cases above sum signals over all definitions; this checks each one fired somewhere (a definition
    that never fires would pass the exactness check unnoticed). Runs after them (file order)."""
    if not _LIVE:
        pytest.skip("the live-window cases did not run")
    assert all(_LIVE.get(i, 0) > 0 for i in IDS), _LIVE
