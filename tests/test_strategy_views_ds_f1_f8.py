"""Chart views of the DeepSeek-200 F1 / F2 / F5 / F8 definitions (paperbot/strategy_view_defs/DS_F1_*.py,
DS_F2_DEMARK.py, DS_F5_*.py, DS_F8_VWICK.py): AND of each side's conditions equals the research signal
(lib_c.entries) on every bar.

lib_c.py is loaded by path under a private module name inside entry_marks._contained(): its import inserts into
sys.path and sets warnings filters, and both are restored (checked). The fast tests use synthetic bars (a few bars
missing, so UTC days and higher-timeframe bins are uneven) and hand-made cases. The real-data test builds the live
service's frames (the last config.DS_WINDOW_5M[tf] 5m bars, resampled by paperbot.dssig.frame) from the 5-year Binance
bar files; set DS_BARS_DIR to a directory holding <coin>-5m.csv.gz. It is skipped without it.
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
IDS = ("F1_RSI_DIV", "F1_MOM_DIV", "F1_PVT_DIV", "F2_DEMARK", "F5_BOX", "F5_BOX_RSI", "F5_BOX_HTF", "F8_VWICK")
_LIVE: dict = {}      # {id: signals} summed over the live-window cases (test_every_definition_fires_live)
TFS = (("15m", "15min", 6000), ("30m", "30min", 4000), ("1h", "1h", 4000), ("4h", "4h", 3000))
BARS = os.environ.get("DS_BARS_DIR", "")


@pytest.fixture(scope="module")
def lib_c():
    from paperbot import sweepsig
    from paperbot.entry_marks import _contained
    sweepsig.lib()                     # the locked library first, as paperbot.dssig loads it
    path0, filters0 = list(sys.path), list(warnings.filters)
    name = "_test_ds_views_f1_f8_lib_c"
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
    sweepsig.lib()                     # the view modules import the vendored indicator code and sweep_lib
    return {i: getattr(importlib.import_module(f"paperbot.strategy_view_defs.DS_{i}"), f"view_DS_{i}") for i in IDS}


def synth(n: int, freq: str, seed: int = 7, drop: int = 6) -> pd.DataFrame:
    """Fat-tailed random walk with gappy opens; ``drop`` bars removed at random (uneven UTC days and HTF bins)."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.004))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
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
def test_ids_are_lib_c_definitions(lib_c):
    tfs = {d: tuple(t) for d, _f, t in lib_c.DEFS}
    for i in IDS:
        assert i in lib_c.DEF_IDS and tfs[i] == ("15m", "30m", "1h", "4h")
    assert lib_c.HTF_OF == {"15m": "1h", "30m": "2h", "1h": "4h", "4h": "1d"}     # F5_BOX_HTF's copy
    assert (lib_c.SW, lib_c.EXP) == (3, 50)                                      # F1 swings, F8 level life


# ------------------------------------------------------------------ exactness
@pytest.mark.parametrize("tf,freq,n", TFS)
def test_and_of_conditions_equals_lib_c_on_synthetic_bars(lib_c, views, tf, freq, n):
    counts = check(lib_c, views, synth(n, freq), tf)
    for i, (nl, ns) in counts.items():
        assert nl > 0 and ns > 0, f"{i} {tf}: the synthetic bars give no {'long' if not nl else 'short'} signal"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_and_of_conditions_equals_lib_c_with_more_seeds(lib_c, views, seed):
    check(lib_c, views, synth(5000, "15min", seed=seed, drop=40), "15m")
    check(lib_c, views, synth(2500, "1h", seed=seed, drop=20), "1h")
    check(lib_c, views, synth(1500, "4h", seed=seed, drop=10), "4h")


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
@pytest.mark.parametrize("coin,tf", [("BTCUSD", "15m"), ("ETHUSD", "1h"), ("LTCUSD", "4h"), ("BCHUSD", "30m")])
def test_and_of_conditions_equals_lib_c_on_live_windows(lib_c, views, coin, tf):
    dssig = pytest.importorskip("paperbot.dssig")
    from paperbot import sweepsig
    from paperbot.config import DS_WINDOW_5M
    p = os.path.join(BARS, f"{coin.lower()}-5m.csv.gz")
    if not os.path.exists(p):
        pytest.skip(f"{p} missing")
    d5 = pd.read_csv(p)
    t5 = (pd.to_datetime(d5["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(np.int64)
    cols = (t5,) + tuple(d5[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    total = np.zeros(2, int)
    for frac in (0.5, 1.0):
        end = int(t5[0] + (t5[-1] - t5[0]) * frac) + 300_000
        boundary = end - end % dssig.TF_MS[tf]
        keep = cols[0] + 300_000 <= boundary
        df = dssig.frame(*(a[keep][-DS_WINDOW_5M[tf]:] for a in cols), tf=tf, lib=sweepsig.lib())
        counts = check(lib_c, views, df, tf, coin)
        for k, x in counts.items():                 # per definition, over every live case
            _LIVE[k] = _LIVE.get(k, 0) + x[0] + x[1]
        total += np.array([sum(x[0] for x in counts.values()), sum(x[1] for x in counts.values())])
    assert total[0] > 0 and total[1] > 0


# ------------------------------------------------------------------ hand-made cases
def _bars(rows, start="2025-06-02 00:00", freq="15min") -> pd.DataFrame:
    """(open, high, low, close) rows as a 15m frame with volume 1."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "ts", pd.date_range(start, periods=len(rows), freq=freq, tz="UTC"))
    df["volume"] = 1.0
    return df


def test_demark_levels_come_from_the_previous_utc_day(lib_c, views):
    day1 = [(100.0, 101.0, 99.0, 100.5)] * 95 + [(100.0, 104.0, 98.0, 102.0)]     # O 100, H 104, L 98, C 102
    day2 = [(102.0, 102.5, 101.0, 102.2)] * 20 + [(102.0, 102.2, 98.5, 100.4)]    # bar 20: wick to S1, close above
    df = _bars(day1 + day2)
    check(lib_c, views, df, "15m")
    v = views["F2_DEMARK"](df.copy(), "15m")
    x = 2 * 104 + 98 + 102                                                         # C > O: 2H + L + C
    lines = {o["name"]: o["values"] for o in v["overlays"]}
    s1 = lines["디마크 지지선 S1(전날 기준, 오전 9시 갱신)"]
    r1 = lines["디마크 저항선 R1(전날 기준, 오전 9시 갱신)"]
    assert np.isnan(s1[:96]).all() and np.isnan(r1[:96]).all()                    # no day before the first one
    assert np.allclose(s1[96:], x / 2 - 104) and np.allclose(r1[96:], x / 2 - 98)  # S1 = 100, R1 = 106
    sig = AND(v["long"], len(df))
    assert sig[-1] and sig.sum() == 1
    assert dict(v["long"])["저가가 디마크 지지선(S1)에 닿음"][-1]


def test_demark_needs_the_calendar_day_just_before(lib_c, views):
    day1 = [(100.0, 101.0, 99.0, 100.5)] * 96
    day3 = [(102.0, 102.5, 101.0, 102.2)] * 20 + [(102.0, 102.2, 90.0, 99.9)]
    df = pd.concat([_bars(day1), _bars(day3, start="2025-06-04 00:00")], ignore_index=True)   # 06-03 has no bar
    check(lib_c, views, df, "15m")
    v = views["F2_DEMARK"](df.copy(), "15m")
    assert all(np.isnan(o["values"]).all() for o in v["overlays"])
    assert not AND(v["long"], len(df)).any() and not AND(v["short"], len(df)).any()


def test_virgin_wick_first_touch_only(lib_c, views):
    quiet = [(100.0, 100.3, 99.7, 100.0)] * 40
    big = [(100.0, 110.5, 99.8, 110.0)]                       # body 10 >= 0.7 x range 10.7 and >= 1.3 ATR
    above = [(110.0, 110.3, 109.7, 110.1)] * 5
    touch = [(105.0, 105.2, 99.5, 100.5)]                     # low 99.5 <= 99.8, close 100.5 > 99.8 -> long
    again = [(100.5, 100.8, 99.0, 100.6)]                     # touches again: the level is used up
    df = _bars(quiet + big + above + touch + again)
    check(lib_c, views, df, "15m")
    v = views["F8_VWICK"](df.copy(), "15m")
    sig = AND(v["long"], len(df))
    t = len(quiet) + 1 + len(above)
    assert sig[t] and sig.sum() == 1
    lines = dict(v["long"])
    assert lines["장대 양봉 꼬리 끝이 안 닿은 채 대기(50봉 안)"][t - 1] and lines["저가가 꼬리 끝에 처음 닿음"][t]
    level = {o["name"]: o["values"] for o in v["overlays"]}["롱 대기 꼬리 끝(장대 양봉 저가)"]
    assert level[t] == 99.8 and np.isnan(level[len(quiet)])


def test_virgin_wick_close_below_uses_the_level_up(lib_c, views):
    quiet = [(100.0, 100.3, 99.7, 100.0)] * 40
    big = [(100.0, 110.5, 99.8, 110.0)]
    above = [(110.0, 110.3, 109.7, 110.1)] * 5
    pierce = [(105.0, 105.2, 99.0, 99.5)]                     # touch, close below 99.8 -> no signal
    back = [(99.5, 100.5, 99.6, 100.4)]                       # would hold it, but the level is gone
    df = _bars(quiet + big + above + pierce + back)
    check(lib_c, views, df, "15m")
    v = views["F8_VWICK"](df.copy(), "15m")
    assert not AND(v["long"], len(df)).any()
    t = len(quiet) + 1 + len(above)
    assert dict(v["long"])["저가가 꼬리 끝에 처음 닿음"][t] and not dict(v["long"])["종가는 꼬리 끝 위에서 마감"][t]


@pytest.mark.parametrize("i", ["F1_RSI_DIV", "F1_MOM_DIV", "F1_PVT_DIV"])
def test_divergence_segments_join_the_two_swings(lib_c, views, i):
    df = synth(3000, "1h", seed=5, drop=0)
    check(lib_c, views, df, "1h")
    v = views[i](df.copy(), "1h")
    n = len(df)
    ov = {o["name"]: np.asarray(o["values"], float) for o in v["overlays"]}
    for side, name in (("long", "마지막 강세 다이버전스(가격 저점)"), ("short", "마지막 약세 다이버전스(가격 고점)")):
        sig = np.flatnonzero(AND(v[side], n))
        seg = np.flatnonzero(np.isfinite(ov[name]))
        assert len(sig) and len(seg) == 2, (i, side)
        assert seg[1] == sig[-1] - 3 and seg[1] - seg[0] <= 60          # b = the swing confirmed on the last signal
        a, b = ov[name][seg]
        assert (b < a) if side == "long" else (b > a)
        swings = ov["스윙 저점 잇기" if side == "long" else "스윙 고점 잇기"]
        assert np.isfinite(swings[seg]).all() and np.allclose(swings[seg], ov[name][seg])   # both ends are swings
    pane = v["panes"][0]["series"]
    assert sum(np.isfinite(np.asarray(s["values"], float)).sum() for s in pane[1:]) == 4


@pytest.mark.parametrize("tf,htf", [("15m", "1시간봉"), ("30m", "2시간봉"), ("1h", "4시간봉"), ("4h", "일봉")])
def test_box_htf_names_the_higher_timeframe(views, tf, htf):
    v = views["F5_BOX_HTF"](synth(300, {"15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}[tf]), tf)
    assert f"{htf}도 횡보(ADX 20 미만, 마감된 봉)" in dict(v["long"])
    assert f"{htf}도 횡보(ADX 20 미만, 마감된 봉)" in dict(v["short"])


def test_box_lines_are_the_previous_48_bars(views):
    df = synth(400, "1h", drop=0)
    v = views["F5_BOX"](df.copy(), "1h")
    ov = {o["name"]: np.asarray(o["values"], float) for o in v["overlays"]}
    top, bot = ov["박스 위(직전 48봉 최고가)"], ov["박스 아래(직전 48봉 최저가)"]
    assert np.isnan(top[:48]).all()
    assert top[300] == df["high"].iloc[252:300].max() and bot[300] == df["low"].iloc[252:300].min()
    assert np.allclose(ov["롱 구역 끝(아래 15%)"][48:], bot[48:] + 0.15 * (top[48:] - bot[48:]))


# ------------------------------------------------------------------ shape, labels, render
def test_views_follow_the_strategy_view_contract(views, monkeypatch):
    import paperbot.strategy_views as sv
    df = synth(1500, "15min")
    monkeypatch.setattr(sv, "_VIEWS", {f"DS_{i}": views[i] for i in IDS})
    for i in IDS:
        d = df.copy()
        d.attrs["tf"] = "15m"
        v = views[i](d, "15m")
        assert set(v) == {"overlays", "panes", "long", "short"}, i
        assert 1 <= len(v["overlays"]) <= 6 and len(v["panes"]) <= 2, i
        for o in v["overlays"]:
            assert o["name"] and len(o["values"]) == len(df), (i, o["name"])
        for p in v["panes"]:
            assert p["name"] and all(len(s["values"]) == len(df) for s in p["series"]), (i, p["name"])
        for side in ("long", "short"):
            labels = [k for k, _a in v[side]]
            assert 2 <= len(labels) <= 6 and len(set(labels)) == len(labels), (i, side)
            assert all(any("가" <= ch <= "힣" for ch in k) for k in labels), (i, side)   # Korean wording
        r = sv.render(f"DS_{i}", df, "15m", tail=300)
        json.dumps(r, ensure_ascii=False)
        assert [c["name"] for c in r["conditions"]["long"]] == [k for k, _a in v["long"]]
        assert all(o["data"] for o in r["overlays"][:1]), i
        for o in r["overlays"]:
            assert all(np.isfinite(p["value"]) for p in o["data"] if "value" in p), (i, o["name"])


@pytest.mark.parametrize("n", [0, 1, 2, 3, 7, 25, 60])
def test_views_run_on_very_short_frames(lib_c, views, n):
    df = synth(80, "1h", drop=0).iloc[:n].reset_index(drop=True)
    for i in IDS:
        v = views[i](df.copy(), "1h")
        for o in v["overlays"]:
            assert len(o["values"]) == n
        for p in v["panes"]:
            assert all(len(s["values"]) == n for s in p["series"])
        for side in ("long", "short"):
            assert all(np.asarray(a).shape == (n,) for _k, a in v[side])
            if n < 2:
                assert not AND(v[side], n).any()
    if n >= 25:                        # lib_c itself needs more than its 10-bar momentum look-back
        check(lib_c, views, df, "1h")


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
def test_every_definition_fires_on_the_live_windows():
    """The live-window cases above sum signals over all definitions; this checks each one fired somewhere (a definition
    that never fires would pass the exactness check unnoticed). Runs after them (file order)."""
    if not _LIVE:
        pytest.skip("the live-window cases did not run")
    assert all(_LIVE.get(i, 0) > 0 for i in IDS), _LIVE
