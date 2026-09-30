"""research/entry_study/final_signals.py: period-3 bars built like the sweep data, cache format."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))

import final_signals as F  # noqa: E402
from paperbot import sweepsig  # noqa: E402

L = sweepsig.lib()


def _bars5(start="2020-01-09 08:05", end="2020-01-12 23:50", drop=()):
    rng = np.random.default_rng(0)
    ts = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq="5min")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(ts))))
    o = np.r_[100.0, c[:-1]]
    df = pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999,
                       "close": c, "volume": rng.lognormal(3, 0.5, len(ts))})
    df = df[~df["ts"].isin(pd.DatetimeIndex(list(drop), tz="UTC"))].reset_index(drop=True)
    return df


def _write(df, path):
    out = df.copy()
    out["ts"] = out["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(path, index=False, compression="gzip")


def test_trim_drops_partial_edge_bins_only():
    gap = ["2020-01-10 12:05", "2020-01-10 12:10"]   # interior partial 30m bin 12:00
    d5 = _bars5(drop=gap)
    r = L.resample_ohlcv(d5, "30m")
    t, dropped = F.trim_partial_edges(r, d5, "30m")
    assert r["ts"].iloc[0] == pd.Timestamp("2020-01-09 08:00", tz="UTC")      # 5 of 6 5m bars
    assert r["ts"].iloc[-1] == pd.Timestamp("2020-01-12 23:30", tz="UTC")     # 5 of 6 5m bars
    assert len(t) == len(r) - 2 and len(dropped) == 2
    assert t["ts"].iloc[0] == pd.Timestamp("2020-01-09 08:30", tz="UTC")
    assert t["ts"].iloc[-1] == pd.Timestamp("2020-01-12 23:00", tz="UTC")
    assert pd.Timestamp("2020-01-10 12:00", tz="UTC") in set(t["ts"])           # interior partial kept
    full = _bars5(start="2020-01-09 08:00", end="2020-01-12 23:55")
    t2, d2 = F.trim_partial_edges(L.resample_ohlcv(full, "4h"), full, "4h")
    assert d2 == [] and len(t2) == len(L.resample_ohlcv(full, "4h"))
    # series starts at a bin open but a 5m bar inside the first / last bin is missing: a gap, kept
    holes = _bars5(start="2020-01-09 08:00", end="2020-01-12 23:55",
                   drop=["2020-01-09 08:20", "2020-01-12 23:40"])
    r3 = L.resample_ohlcv(holes, "30m")
    t3, d3 = F.trim_partial_edges(r3, holes, "30m")
    assert d3 == [] and len(t3) == len(r3)


def test_load_bars_mirrors_resampled_5m(tmp_path):
    d5 = _bars5()
    _write(d5, tmp_path / "ltcusd-5m.csv.gz")
    native15 = L.resample_ohlcv(d5, "15m")          # a native file keeps its partial first kline
    _write(native15, tmp_path / "ltcusd-15m.csv.gz")
    b5 = F.load_bars(L, "5m", "LTCUSD", str(tmp_path))
    assert len(b5) == len(d5) and b5.attrs["dropped_edges"] == []
    b15 = F.load_bars(L, "15m", "LTCUSD", str(tmp_path))
    # first (08:00, 2 of 3) and last (23:45, 2 of 3) native klines are partial and dropped
    assert b15["ts"].iloc[0] == pd.Timestamp("2020-01-09 08:15", tz="UTC") and len(b15) == len(native15) - 2
    assert b15["ts"].iloc[-1] == pd.Timestamp("2020-01-12 23:30", tz="UTC")
    b30 = F.load_bars(L, "30m", "LTCUSD", str(tmp_path))
    ref, _ = F.trim_partial_edges(L.resample_ohlcv(d5, "30m"), d5, "30m")
    pd.testing.assert_frame_equal(b30.reset_index(drop=True), ref.reset_index(drop=True), check_like=True)
    bad = native15.copy()
    bad.loc[10, "close"] *= 1.01
    _write(bad, tmp_path / "ltcusd-15m.csv.gz")
    with pytest.raises(ValueError):
        F.load_bars(L, "15m", "LTCUSD", str(tmp_path))


def test_signal_arrays_format_matches_period12_cache():
    df = L.synth_ohlcv(2500, "1h", seed=3)
    arr = F.signal_arrays(L, df, "1h", "BTCUSD")
    sys.path.insert(0, os.path.join(ROOT, "research", "paper_rules"))
    import rules_bt as RB
    names = RB.strategy_names(L)
    assert set(arr) == {"ts", "o", "h", "l", "c", "v", "atr"} | {f"s__{n}" for n in names}
    assert len(names) == 36
    assert arr["ts"].dtype == np.int64 and arr["ts"][0] == pd.Timestamp("2021-07-01").value
    for n in names:
        a = arr[f"s__{n}"]
        assert a.dtype == np.int8 and len(a) == len(df) and set(np.unique(a)) <= {-1, 0, 1}
    raw = L.compute_signals({"BTCUSD": df}, "1h", ["DOGE_L", "DOGE_S", "N17_KC_RSI"], strict=True)
    from paperbot.sigservice import doge_join
    assert np.array_equal(arr["s__DOGE"], doge_join(raw["DOGE_L"]["BTCUSD"], raw["DOGE_S"]["BTCUSD"]))
    assert np.array_equal(arr["s__N17_KC_RSI"], raw["N17_KC_RSI"]["BTCUSD"])
    assert np.array_equal(arr["v"], df["volume"].to_numpy(float))
    assert F.content_digest(arr) == F.content_digest(dict(arr))
