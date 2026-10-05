"""Chart views of the DeepSeek-200 F15 session definitions (paperbot/strategy_view_defs/DS_F15_*.py): F15_ASIA_BRK,
F15_ASIA_SWEEP, F15_LON_BRK, F15_OPEN0930, F15_OPEN0000 (US Eastern sessions, 15m / 30m / 1h only) and F15_ORB
(UTC day, all four timeframes). AND of each side's conditions must equal research/deepseek200/lib_c.py ``entries()``
on every bar.

lib_c.py is loaded by path under a private module name inside entry_marks._contained(): its import inserts into
sys.path and sets warnings filters, and both are restored (checked here). The fast tests use synthetic bars around
both daylight-saving changes, with bars and a whole day missing. The real-data test builds the live service's frames
(the last config.DS_WINDOW_5M[tf] 5m bars, resampled by paperbot.dssig.frame) from the 5-year Binance bar files; set
DS_BARS_DIR to a directory holding <coin>-5m.csv.gz. It is skipped without it.
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
SES = ("F15_ASIA_BRK", "F15_ASIA_SWEEP", "F15_LON_BRK", "F15_OPEN0930", "F15_OPEN0000")
IDS = SES + ("F15_ORB",)
_LIVE: dict = {}      # {id: signals} summed over the live-window cases (test_every_definition_fires_live)
BARS = os.environ.get("DS_BARS_DIR", "")
FREQ = {"15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}


@pytest.fixture(scope="module")
def lib_c():
    from paperbot import sweepsig
    from paperbot.entry_marks import _contained
    sweepsig.lib()                     # the locked library first, as paperbot.dssig loads it
    path0, filters0 = list(sys.path), list(warnings.filters)
    name = "_test_ds_views_f15_lib_c"
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
    return {i: getattr(importlib.import_module(f"paperbot.strategy_view_defs.DS_{i}"), f"view_DS_{i}") for i in IDS}


def synth(n: int, tf: str, start: str = "2025-02-25", seed: int = 7, drop: int = 0,
          drop_day: bool = False) -> pd.DataFrame:
    """Fat-tailed random walk; ``drop`` bars removed at random and, with ``drop_day``, one whole UTC day."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.004))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    df = pd.DataFrame({"ts": pd.date_range(start, periods=n, freq=FREQ[tf], tz="UTC"), "open": o, "high": h,
                       "low": lo, "close": c, "volume": rng.uniform(1, 10, n)})
    if drop:
        df = df.drop(index=rng.choice(np.arange(n), drop, replace=False)).reset_index(drop=True)
    if drop_day:
        d = pd.to_datetime(df["ts"]).dt.floor("D")
        df = df[d != d.iloc[len(df) // 2]].reset_index(drop=True)
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
        sig = R.get(i, (np.zeros(len(df), bool), np.zeros(len(df), bool)))   # ET sessions: none on 4h
        for side, s in zip(("long", "short"), sig):
            got = AND(v[side], len(df))
            bad = np.flatnonzero(got != s)
            assert not len(bad), f"{i} {tf} {side}: {len(bad)} bars differ, first {bad[:5].tolist()}"
        out[i] = (int(sig[0].sum()), int(sig[1].sum()))
    return out


# ------------------------------------------------------------------ definitions
def test_ids_are_lib_c_definitions(lib_c):
    tfs = {d: tuple(t) for d, _f, t in lib_c.DEFS}
    for i in SES:
        assert tfs[i] == ("15m", "30m", "1h"), i
    assert tfs["F15_ORB"] == ("15m", "30m", "1h", "4h") and lib_c.ORB_BARS == 2


def test_et_clock_follows_new_york_time():
    """The views' fixed US rule (as lib_c.et_wall) equals the IANA zone over 2020-2026, both DST edges included."""
    from paperbot.strategy_view_defs import DS_F15_ASIA_BRK as A
    ts = pd.date_range("2020-01-01", "2026-12-31 23:45", freq="15min", tz="UTC")
    day, mins = A._et_clock(pd.DataFrame({"ts": ts}))
    ny = ts.tz_convert("America/New_York")
    want_day = ((ny.tz_localize(None).normalize() - pd.Timestamp("1970-01-01")) // pd.Timedelta("1D")).to_numpy()
    assert np.array_equal(day, want_day)
    assert np.array_equal(mins, (ny.hour * 60 + ny.minute).to_numpy())


# ------------------------------------------------------------------ exactness
@pytest.mark.parametrize("tf,n", [("15m", 6000), ("30m", 4000), ("1h", 3000), ("4h", 1500)])
@pytest.mark.parametrize("start", ["2025-02-25", "2025-10-20"])      # spring and autumn DST changes inside
def test_and_of_conditions_equals_lib_c_on_synthetic_bars(lib_c, views, tf, n, start):
    counts = check(lib_c, views, synth(n, tf, start, drop=25, drop_day=True), tf)
    for i, (nl, ns) in counts.items():
        if tf == "4h" and i in SES:
            assert nl == ns == 0
        else:
            assert nl > 0 and ns > 0, f"{i} {tf}: the synthetic bars give no {'long' if not nl else 'short'} signal"


def test_session_definitions_are_off_on_4h(views):
    df = synth(1500, "4h")
    for i in SES:
        v = views[i](df.copy(), "4h")
        assert not AND(v["long"], len(df)).any() and not AND(v["short"], len(df)).any(), i


def test_missing_range_bar_removes_that_days_signal(lib_c, views):
    """A bar missing inside a range (Asia 20-24 ET, London 02-05 ET, ORB first 2 bars, or between the open-bias
    reference and judging bars) turns that day's first line off, as lib_c gives no signal that day."""
    df = synth(4000, "15m", "2025-06-02", seed=3)
    ts = pd.to_datetime(df["ts"])
    et = ts.dt.tz_convert("America/New_York")
    d0 = et.dt.normalize().iloc[2000]
    holes = [(d0 - pd.Timedelta("1D")).replace(hour=21), d0.replace(hour=3), d0.replace(hour=9, minute=45),
             d0.replace(hour=0, minute=15)]
    utc_day = ts.dt.floor("D").iloc[2600]
    drop = et.isin(holes) | (ts == utc_day + pd.Timedelta("15min"))
    assert drop.sum() == 5
    df = df[~drop].reset_index(drop=True)
    check(lib_c, views, df, "15m")
    et = pd.to_datetime(df["ts"]).dt.tz_convert("America/New_York")
    today = (et.dt.normalize() == d0).to_numpy() & (et.dt.hour < 20).to_numpy()   # from 20:00 ET: tomorrow's range
    for i in ("F15_ASIA_BRK", "F15_ASIA_SWEEP", "F15_LON_BRK"):
        ready = views[i](df.copy(), "15m")["long"][0][1]
        assert not ready[today].any() and ready.any(), i
    for i in ("F15_OPEN0930", "F15_OPEN0000"):
        v = views[i](df.copy(), "15m")
        judge, nogap = v["long"][1][1], v["long"][2][1]
        assert judge[today].sum() == 1 and not (judge & nogap)[today].any(), i
    ready = views["F15_ORB"](df.copy(), "15m")["long"][0][1]
    lost = (pd.to_datetime(df["ts"]).dt.floor("D") == utc_day).to_numpy()
    assert not ready[lost].any() and ready.any()


def test_two_sided_sweep_bar_blocks_the_day(lib_c, views):
    """A bar that sweeps both Asia levels gives no signal, and the day has none after it (lib_c: first sweeps tie, or an
    earlier sweep already took the day)."""
    df = synth(3000, "15m", "2025-06-02", seed=5)
    et = pd.to_datetime(df["ts"]).dt.tz_convert("America/New_York")
    i = int(np.flatnonzero(((et.dt.hour == 1) & (et.dt.minute == 0)).to_numpy())[10])
    df.loc[i, "high"] = df["high"].iloc[i - 30:i].max() * 1.05
    df.loc[i, "low"] = df["low"].iloc[i - 30:i].min() * 0.95
    check(lib_c, views, df, "15m")
    v = views["F15_ASIA_SWEEP"](df.copy(), "15m")
    both = ~dict(v["long"])["같은 봉에서 고가 쪽 스윕 없음"] & ~dict(v["short"])["같은 봉에서 저가 쪽 스윕 없음"]
    assert both[i]
    rest = (et.dt.normalize() == et.dt.normalize().iloc[i]).to_numpy() & (np.arange(len(df)) >= i)
    assert not (AND(v["long"], len(df)) | AND(v["short"], len(df)))[rest].any()
    later = rest & (et.dt.hour < 20).to_numpy() & (np.arange(len(df)) > i)       # from 20:00 ET: the next range
    assert later.any() and not dict(v["long"])["오늘 첫 스윕(앞서 레인지 찌르고 복귀한 봉 없음)"][later].any()


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
@pytest.mark.parametrize("coin,tf", [("BTCUSD", "15m"), ("ETHUSD", "1h"), ("BCHUSD", "30m"), ("LTCUSD", "4h")])
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
    for frac in (0.3, 0.7, 1.0):
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
    df = synth(1500, "15m")
    monkeypatch.setattr(sv, "_VIEWS", {f"DS_{i}": views[i] for i in IDS})
    for i in IDS:
        d = df.copy()
        d.attrs["tf"] = "15m"
        v = views[i](d, "15m")
        assert set(v) == {"overlays", "panes", "long", "short"}, i
        assert 1 <= len(v["overlays"]) <= 6 and v["panes"] == [], i
        for o in v["overlays"]:
            assert o["name"] and len(o["values"]) == len(df), (i, o["name"])
        for side in ("long", "short"):
            labels = [k for k, _a in v[side]]
            assert 4 <= len(labels) <= 6 and len(set(labels)) == len(labels), (i, side)
            assert all(any("가" <= ch <= "힣" for ch in k) for k in labels), (i, side)   # Korean wording
        r = sv.render(f"DS_{i}", df, "15m", tail=300)
        json.dumps(r, ensure_ascii=False)
        assert [c["name"] for c in r["conditions"]["long"]] == [k for k, _a in v["long"]]
        assert all(o["data"] for o in r["overlays"]), i
        for o in r["overlays"]:
            assert all(np.isfinite(p["value"]) for p in o["data"] if "value" in p), (i, o["name"])


@pytest.mark.parametrize("n", [0, 1, 2, 3, 7, 25])
@pytest.mark.parametrize("tf", ["15m", "4h"])
def test_views_run_on_very_short_frames(views, n, tf):
    df = synth(60, tf).iloc[:n].reset_index(drop=True)
    for i in IDS:
        v = views[i](df.copy(), tf)
        for o in v["overlays"]:
            assert len(o["values"]) == n
        for side in ("long", "short"):
            for _k, a in v[side]:
                assert np.asarray(a).shape == (n,)


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
def test_every_definition_fires_on_the_live_windows():
    """The live-window cases above sum signals over all definitions; this checks each one fired somewhere (a definition
    that never fires would pass the exactness check unnoticed). Runs after them (file order)."""
    if not _LIVE:
        pytest.skip("the live-window cases did not run")
    assert all(_LIVE.get(i, 0) > 0 for i in IDS), _LIVE
