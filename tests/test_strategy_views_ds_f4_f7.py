"""Chart views of the DeepSeek-200 F4 / F6 / F7 definitions (paperbot/strategy_view_defs/DS_F4_*.py, DS_F6_*.py,
DS_F7_*.py): AND of each side's conditions equals the research signal (lib_c.entries) on every bar.

lib_c.py is loaded by path under a private module name inside entry_marks._contained(): its import inserts into
sys.path and sets warnings filters, and both are restored. The fast tests use synthetic bars (a few bars missing,
so UTC days and higher-timeframe bins are uneven) and hand-made VWAP days. The real-data test builds the live
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
IDS = ("F4_PULL", "F4_PULL_RSI", "F4_FAN", "F6_VWAP_CROSS", "F6_VWAP_FAIL", "F7_RF_TRIPLE", "F7_RF_ONLY")
_LIVE: dict = {}      # {id: signals} summed over the live-window cases (test_every_definition_fires_live)
TFS = (("15m", "15min", 6000), ("30m", "30min", 4000), ("1h", "1h", 4000), ("4h", "4h", 3000))
BARS = os.environ.get("DS_BARS_DIR", "")


@pytest.fixture(scope="module")
def lib_c():
    from paperbot import sweepsig
    from paperbot.entry_marks import _contained
    sweepsig.lib()                     # the locked library first, as paperbot.dssig loads it
    path0, filters0 = list(sys.path), list(warnings.filters)
    name = "_test_ds_views_f4_f7_lib_c"
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
    assert lib_c.HTF_OF == {"15m": "1h", "30m": "2h", "1h": "4h", "4h": "1d"}     # F7_RF_TRIPLE's copy


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


def vwap_day(closes, extra=None) -> pd.DataFrame:
    """One UTC day of 15m bars whose VWAP stays at 100: the first bar trades 1e9 at 100, the others volume 1.
    ``closes``: (open, high, low, close) of bars 1..; bars before 00:00 UTC are on the previous day."""
    rows = [(100.0, 100.0, 100.0, 100.0, 1e9)] + [(o, h, lo, c, 1.0) for o, h, lo, c in closes]
    ts = pd.date_range("2025-06-02 00:00", periods=len(rows), freq="15min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.insert(0, "ts", ts)
    pre = synth(400, "15min", seed=4, drop=0)
    pre["ts"] = pd.date_range(end=ts[0] - pd.Timedelta("15min"), periods=len(pre), freq="15min", tz="UTC")
    return pd.concat([pre, df], ignore_index=True)


def test_vwap_fail_first_failed_retest_after_a_break(lib_c, views):
    bars = [(100.5, 101.2, 100.4, 101.0),        # 1 above VWAP
            (100.8, 100.9, 99.4, 99.5),          # 2 closes below: the break
            (99.5, 99.8, 99.2, 99.6),            # 3 no retest yet
            (99.7, 100.2, 99.5, 99.6),           # 4 high reaches VWAP, red close below -> short
            (99.7, 100.3, 99.5, 99.55)]          # 5 the same again: the break is used up
    df = vwap_day(bars)
    base = len(df) - len(bars) - 1
    check(lib_c, views, df, "15m")
    v = views["F6_VWAP_FAIL"](df.copy(), "15m")
    sig = AND(v["short"], len(df))
    assert sig[base + 4] and not sig[base + 5] and not sig[base + 3]
    lines = dict(v["short"])
    assert lines["최근 10봉 안에 VWAP 아래로 이탈(같은 날)"][base + 5]
    assert not lines["이탈 뒤 첫 재시험(앞선 신호 없음)"][base + 5]


def test_vwap_fail_close_back_above_cancels_the_break(lib_c, views):
    bars = [(100.5, 101.2, 100.4, 101.0),        # 1 above VWAP
            (100.8, 100.9, 99.4, 99.5),          # 2 break below
            (99.6, 100.5, 99.5, 100.3),          # 3 closes back above VWAP: the break is cancelled
            (100.3, 100.4, 99.4, 99.6),          # 4 below again (a new break, cannot fire on its own bar)
            (99.7, 100.2, 99.5, 99.6)]           # 5 failed retest of the new break -> short
    df = vwap_day(bars)
    base = len(df) - len(bars) - 1
    check(lib_c, views, df, "15m")
    v = views["F6_VWAP_FAIL"](df.copy(), "15m")
    sig = AND(v["short"], len(df))
    assert not sig[base + 4] and sig[base + 5]
    assert not dict(v["short"])["이탈 뒤 VWAP 위 마감 없음"][base + 4]


def test_vwap_fail_waits_ten_bars_only(lib_c, views):
    bars = [(100.5, 101.2, 100.4, 101.0), (100.8, 100.9, 99.4, 99.5)]    # break at 2
    bars += [(99.5, 99.8, 99.2, 99.6)] * 10                               # 3..12: no retest
    bars += [(99.7, 100.2, 99.5, 99.6)]                                   # 13: 11 bars after -> too late
    df = vwap_day(bars)
    check(lib_c, views, df, "15m")
    v = views["F6_VWAP_FAIL"](df.copy(), "15m")
    assert not AND(v["short"], len(df))[-1]
    assert dict(v["short"])["최근 10봉 안에 VWAP 아래로 이탈(같은 날)"][-2]
    assert not dict(v["short"])["최근 10봉 안에 VWAP 아래로 이탈(같은 날)"][-1]


def test_vwap_cross_never_on_a_days_first_bar(lib_c, views):
    df = synth(3000, "1h", seed=9, drop=0)
    check(lib_c, views, df, "1h")
    v = views["F6_VWAP_CROSS"](df.copy(), "1h")
    first = (pd.to_datetime(df["ts"]).dt.hour == 0).to_numpy()
    for side in ("long", "short"):
        assert not AND(v[side], len(df))[first].any()
        assert not dict(v[side])["하루 첫 봉 아님(VWAP는 매일 오전 9시 새로 시작)"][first].any()


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
    total = (0, 0)
    for frac in (0.5, 1.0):
        end = int(t5[0] + (t5[-1] - t5[0]) * frac) + 300_000
        boundary = end - end % dssig.TF_MS[tf]
        keep = cols[0] + 300_000 <= boundary
        df = dssig.frame(*(a[keep][-DS_WINDOW_5M[tf]:] for a in cols), tf=tf, lib=sweepsig.lib())
        counts = check(lib_c, views, df, tf, coin)
        for k, x in counts.items():                 # per definition, over every live case
            _LIVE[k] = _LIVE.get(k, 0) + x[0] + x[1]
        total = (total[0] + sum(x[0] for x in counts.values()), total[1] + sum(x[1] for x in counts.values()))
    assert total[0] > 0 and total[1] > 0


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
        assert 1 <= len(v["overlays"]) <= 6, i
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


@pytest.mark.parametrize("tf,htf", [("15m", "1시간봉"), ("30m", "2시간봉"), ("1h", "4시간봉"), ("4h", "일봉")])
def test_rf_triple_names_the_higher_timeframe(views, tf, htf):
    v = views["F7_RF_TRIPLE"](synth(300, {"15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}[tf]), tf)
    assert f"{htf} 하이킨아시 양봉(마감된 봉)" in dict(v["long"])
    assert f"{htf} 하이킨아시 음봉(마감된 봉)" in dict(v["short"])


@pytest.mark.parametrize("n", [0, 1, 2, 3, 7, 25])
def test_views_run_on_very_short_frames(lib_c, views, n):
    df = synth(60, "1h", drop=0).iloc[:n].reset_index(drop=True)
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
