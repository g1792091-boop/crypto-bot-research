"""Chart views of the DeepSeek-200 F9 / F10 / F11 definitions (paperbot/strategy_view_defs/DS_F9_*.py, DS_F10_*.py,
DS_F11_*.py): AND of each side's conditions equals the research signal (lib_c.entries) on every bar.

lib_c.py is loaded by path under a private module name inside entry_marks._contained(): its import inserts into
sys.path and sets warnings filters, and both are restored. The fast tests use synthetic bars (with a few bars
missing, for the UTC-day rules of F11_PO3). The real-data test builds the live service's frames (the last
config.DS_WINDOW_5M[tf] 5m bars, resampled by paperbot.dssig.frame) from the 5-year Binance bar files; set
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
IDS = ("F9_FVG", "F9_IFVG", "F9_OB", "F9_BREAKER", "F10_M2022", "F10_OTE", "F11_TSOUP", "F11_RAID", "F11_PO3")
_LIVE: dict = {}      # {id: signals} summed over the live-window cases (test_every_definition_fires_live)
TFS = (("15m", "15min", 4000), ("1h", "1h", 3000), ("4h", "4h", 2000))
BARS = os.environ.get("DS_BARS_DIR", "")


@pytest.fixture(scope="module")
def lib_c():
    from paperbot import sweepsig
    from paperbot.entry_marks import _contained
    sweepsig.lib()                     # the locked library first, as paperbot.dssig loads it
    path0, filters0 = list(sys.path), list(warnings.filters)
    name = "_test_ds_views_f9_f11_lib_c"
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


def synth(n: int, freq: str, seed: int = 7, drop: int = 6) -> pd.DataFrame:
    """Fat-tailed random walk whose opens are off the last close (gaps, so FVGs and order blocks form); ``drop``
    bars removed at random (a missing bar breaks a UTC day's range for F11_PO3)."""
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


# ------------------------------------------------------------------ exactness
@pytest.mark.parametrize("tf,freq,n", TFS)
def test_and_of_conditions_equals_lib_c_on_synthetic_bars(lib_c, views, tf, freq, n):
    counts = check(lib_c, views, synth(n, freq), tf)
    for i, (nl, ns) in counts.items():
        assert nl > 0 and ns > 0, f"{i} {tf}: the synthetic bars give no {'long' if not nl else 'short'} signal"


def test_same_bar_long_and_short_rule_is_a_condition(lib_c, views):
    """lib_c drops both sides when they fire on one bar; the last line of each side carries that rule."""
    df = synth(4000, "15min")
    df.attrs["tf"] = "15m"
    cancelled = 0
    for i in ("F9_IFVG", "F9_OB", "F9_BREAKER"):
        v = views[i](df.copy(), "15m")
        for side in ("long", "short"):
            assert v[side][-1][0].startswith("같은 봉")
            cancelled += int((AND(v[side][:-1], len(df)) & ~v[side][-1][1]).sum())
    assert cancelled > 0
    check(lib_c, views, df, "15m")


def test_po3_reads_the_utc_day_and_skips_days_with_a_missing_range_bar(lib_c, views):
    df = synth(3000, "1h", seed=11, drop=0)
    day = pd.to_datetime(df["ts"]).dt.floor("D")
    gone = day == day.iloc[500]
    hole = df.index[gone & (pd.to_datetime(df["ts"]).dt.hour == 3)]     # 03:00 UTC: inside the 00-08 UTC range
    df = df.drop(index=hole).reset_index(drop=True)
    check(lib_c, views, df, "1h")
    v = views["F11_PO3"](df.copy(), "1h")
    lost = (pd.to_datetime(df["ts"]).dt.floor("D") == day.iloc[500]).to_numpy()
    ready = dict(v["long"])["오늘 축적 범위 완성(한국 09~17시)"]
    assert lost.any() and not ready[lost].any() and ready.any()


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
        assert 2 <= len(v["overlays"]) <= 6, i
        for o in v["overlays"]:
            assert o["name"] and len(o["values"]) == len(df), (i, o["name"])
        for side in ("long", "short"):
            labels = [k for k, _a in v[side]]
            assert 4 <= len(labels) <= 6 and len(set(labels)) == len(labels), (i, side)
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
        for side in ("long", "short"):
            assert all(np.asarray(a).shape == (n,) for _k, a in v[side])
            if n < 3:
                assert not AND(v[side], n).any()


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
def test_every_definition_fires_on_the_live_windows():
    """The live-window cases above sum signals over all definitions; this checks each one fired somewhere (a definition
    that never fires would pass the exactness check unnoticed). Runs after them (file order)."""
    if not _LIVE:
        pytest.skip("the live-window cases did not run")
    assert all(_LIVE.get(i, 0) > 0 for i in IDS), _LIVE
