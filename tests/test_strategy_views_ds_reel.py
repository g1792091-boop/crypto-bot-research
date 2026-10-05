"""Chart view of the reel (paperbot/strategy_view_defs/REEL_H1.py, research/reel5m/PREREG_REEL5M.md H1): AND of the
long conditions equals the research signal on every bar, and the drawn swing low, stop and trade follow lib_reel5m.

The research signal is lib_reel5m.simulate(trade=False) (the position-independent machine the live signal runs,
paperbot/reelsig.py) on lib_reel5m.indicators with H1's settings (SMA200, CLOSE, LONG), started flat on the frame's
first bar; one placeholder bar is appended so that simulate, which needs the entry bar s+1, also reads the frame's last
bar. lib_reel5m.py is loaded by path under a private module name inside entry_marks._contained(): its import inserts
into sys.path and sets warnings filters, and both are restored. The real-data tests read <coin>-5m.csv.gz in
DS_BARS_DIR (the live windows: the last config.REEL_WINDOW_5M closed 5m bars); they are skipped without it.
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
LIB = os.path.join(ROOT, "research", "reel5m", "lib_reel5m.py")
BARS = os.environ.get("DS_BARS_DIR", "")
STOP = "손절선(최저점 − ATR 0.05배)"
LOW = "눌림 최저점(하단 이탈 뒤)"
TARGET = "익절 목표(직전 봉 상단)"


@pytest.fixture(scope="module")
def R():
    from paperbot import sweepsig
    from paperbot.entry_marks import _contained
    sweepsig.lib()
    path0, filters0 = list(sys.path), list(warnings.filters)
    name = "_test_ds_views_reel_lib_reel5m"
    spec = importlib.util.spec_from_file_location(name, LIB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        with _contained():
            spec.loader.exec_module(mod)
            mod.env()
    except BaseException:
        sys.modules.pop(name, None)
        raise
    assert sys.path == path0, "lib_reel5m left sys.path changed"
    assert warnings.filters == filters0, "lib_reel5m left the warnings filters changed"
    yield mod
    sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def cost(R):
    return R.env()["L"]._cost("5m", R.MAX_HOLD)


@pytest.fixture(scope="module")
def mod():
    from paperbot import sweepsig
    sweepsig.lib()
    return importlib.import_module("paperbot.strategy_view_defs.REEL_H1")


@pytest.fixture(scope="module")
def view(mod):
    return mod.view_REEL_H1


def synth(n: int, seed: int = 7, red: float = 0.002) -> pd.DataFrame:
    """5m bars: a random walk whose drift switches sign every 200-700 bars (so the middle band crosses SMA200 both
    ways), with fat-tailed moves (so closes fall below the lower band). Opens sit about ``red`` above the last close,
    so red candles are common and some setups wait out their 12 bars."""
    rng = np.random.default_rng(seed)
    drift = np.empty(n)
    i, sign = 0, 1.0
    while i < n:
        k = int(rng.integers(200, 700))
        drift[i:i + k] = sign * rng.uniform(0.0001, 0.0006)
        sign, i = -sign, i + k
    c = 100 * np.exp(np.cumsum(drift + rng.standard_t(3, n) * 0.0015))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(red, 0.0003, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    return pd.DataFrame({"ts": pd.date_range("2025-03-01", periods=n, freq="5min", tz="UTC"), "open": o, "high": h,
                         "low": lo, "close": c, "volume": rng.uniform(1, 10, n)})


def AND(conds, n: int) -> np.ndarray:
    out = np.ones(n, bool)
    for _label, arr in conds:
        a = np.asarray(arr)
        assert a.dtype == bool and a.shape == (n,)
        out &= a
    return out


def ref(R, cost, df: pd.DataFrame):
    """(signal per bar, lib's signal dicts, Prep) of H1's position-independent machine on ``df``."""
    df = df.reset_index(drop=True)
    n = len(df)
    pad = df.iloc[[-1]].copy()
    pad["ts"] = pad["ts"] + pd.Timedelta(minutes=5)
    d2 = pd.concat([df, pad], ignore_index=True)
    P = R.Prep(R.indicators(d2), "SMA200", "CLOSE", "LONG")
    _t, sg, _s = R.simulate(P, cost, 0, len(d2), "open", False)
    sig = np.zeros(n, bool)
    for s in sg:
        assert s["side"] == 1 and s["signal_idx"] < n
        sig[s["signal_idx"]] = True
    return sig, sg, P


def check(R, cost, view, df: pd.DataFrame) -> tuple[np.ndarray, list, dict]:
    df = df.reset_index(drop=True)
    v = view(df.copy(), "5m")
    assert v["short"] == []
    got = AND(v["long"], len(df))
    sig, sg, _P = ref(R, cost, df)
    bad = np.flatnonzero(got != sig)
    assert not len(bad), f"{len(bad)} bars differ, first {bad[:5].tolist()}"
    return sig, sg, v


# ------------------------------------------------------------------ the rule's numbers
def test_parameters_are_lib_reel5m_s(R, mod, cost):
    assert (R.BB_LEN, R.BB_K, R.MA_LEN, R.WAIT, R.STOP_BUF_ATR, R.MAX_HOLD) == \
        (mod._BB_LEN, mod._BB_K, mod._MA_LEN, mod._WAIT, mod._STOP_BUF, mod._MAX_HOLD)
    assert cost.slip_side == mod._SLIP
    from paperbot.config import REEL_NAME, REEL_TF
    assert (REEL_NAME, REEL_TF) == ("REEL_H1", "5m")


# ------------------------------------------------------------------ exactness and the machine's branches
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_and_of_conditions_equals_lib_reel5m_on_synthetic_bars(R, cost, view, seed):
    df = synth(6000, seed)
    sig, sg, v = check(R, cost, view, df)
    assert sig.sum() >= 10
    c = dict(v["long"])
    filt, alive = c["필터 켜짐(중심선 > 200선)"], c["하단 이탈 후 12봉 이내(기다리는 중)"]
    _up, _mid, dn, _bw = R.env()["fg"].bollinger_bands(df["close"].astype(float), 20, 2.0)
    breach = (df["close"].to_numpy() < dn.to_numpy()) & filt
    assert (alive & ~filt).any(), "no setup cancelled by the filter"
    nxt = np.r_[alive[1:], False]
    expired = alive & filt & ~sig & ~breach & ~nxt
    assert expired.any(), "no setup expired after 12 bars"
    assert (alive & breach).any(), "no breach while armed"
    assert not (sig & breach).any() and not (sig & ~alive).any()
    for s in np.flatnonzero(sig):              # a breach within the 12 bars before every signal
        assert breach[max(0, s - 12):s].any()


def test_swing_low_and_stop_on_signal_bars_are_lib_s(R, cost, view):
    df = synth(6000, 4)
    _sig, sg, v = check(R, cost, view, df)
    ov = {o["name"]: np.asarray(o["values"]) for o in v["overlays"]}
    atr = R.indicators(df)["atr"]
    assert sg
    for s in sg:
        i = s["signal_idx"]
        assert ov[LOW][i] == s["extreme"]
        assert ov[STOP][i] == s["stop_px"] == s["extreme"] - 0.05 * atr[i]


def test_drawn_trades_are_lib_reel5m_exit_trade(R, cost, view):
    """The target line covers exactly the bars of lib_reel5m.exit_trade of every signal that is not skipped (entry bar
    through exit bar) at the previous bar's upper band; the stop line there is the signal's stop when no new setup
    is waiting."""
    df = synth(6000, 5)
    _sig, sg, v = check(R, cost, view, df)
    _s2, _sg2, P = ref(R, cost, df)
    ov = {o["name"]: np.asarray(o["values"]) for o in v["overlays"]}
    n = len(df)
    want, stop_at = np.zeros(n, bool), {}
    for s in sg:
        e = s["signal_idx"] + 1
        if e >= n:
            continue
        entry = P.o[e] * (1 + cost.slip_side)
        if not entry > s["stop_px"] or not P.up_prev[e] > entry:
            continue
        tr = R.exit_trade(1, e, entry, s["stop_px"], P.up_prev, P.o, P.h, P.l, P.c, cost)
        want[e:tr["exit_idx"] + 1] = True
        for j in range(e, tr["exit_idx"] + 1):
            stop_at[j] = s["stop_px"]
    assert want.sum() > 100
    assert np.array_equal(np.isfinite(ov[TARGET]), want)
    assert np.array_equal(ov[TARGET][want], P.up_prev[:n][want])
    c = dict(v["long"])
    filt, alive = c["필터 켜짐(중심선 > 200선)"], c["하단 이탈 후 12봉 이내(기다리는 중)"]
    arming = (P.c[:n] < P.dn[:n]) & filt & ~alive
    setup = (alive & filt) | arming                   # the setup's own lowest low and stop take these bars
    assert np.array_equal(np.isfinite(ov[LOW]), setup | want)
    trade_only = [j for j in stop_at if not setup[j]]
    assert trade_only and all(ov[STOP][j] == stop_at[j] for j in trade_only)


def test_no_short_and_long_only_in_lib(R, cost, view):
    df = synth(4000, 6)
    v = view(df.copy(), "5m")
    assert v["short"] == []
    _sig, sg, _P = ref(R, cost, df)
    assert sg and all(s["side"] == 1 for s in sg)


@pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
@pytest.mark.parametrize("coin", ["BTCUSD", "ETHUSD"])
def test_and_of_conditions_equals_lib_reel5m_on_live_windows(R, cost, view, coin):
    from paperbot.config import REEL_WINDOW_5M
    p = os.path.join(BARS, f"{coin.lower()}-5m.csv.gz")
    if not os.path.exists(p):
        pytest.skip(f"{p} missing")
    df = pd.read_csv(p).iloc[-80_000:].reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    full, _sg, _v = check(R, cost, view, df)
    assert full.sum() > 100
    rng = np.random.default_rng(0)
    ends = sorted(set(rng.integers(REEL_WINDOW_5M + 1000, len(df), 12).tolist() + [len(df)]))
    for e in ends:
        w = df.iloc[e - REEL_WINDOW_5M:e]
        sig, _sg, v = check(R, cost, view, w)
        assert AND(v["long"], len(w))[-1] == full[e - 1]     # the 5,000-bar start does not change the last bar


# ------------------------------------------------------------------ shape, labels, render
def test_view_follows_the_strategy_view_contract(view, monkeypatch):
    import paperbot.strategy_views as sv
    df = synth(1500, 8)
    monkeypatch.setattr(sv, "get_view", lambda name: view if name == "REEL_H1" else None)
    v = view(df.copy(), "5m")
    assert set(v) == {"overlays", "panes", "long", "short"} and v["panes"] == [] and v["short"] == []
    assert [o["name"] for o in v["overlays"]] == ["볼린저 상단(20, 2)", "볼린저 중심선(20봉 평균)", "볼린저 하단(20, 2)",
                                                  "200봉 평균선", LOW, STOP, TARGET]
    assert [k for k, _a in v["long"]] == ["필터 켜짐(중심선 > 200선)", "하단 이탈 후 12봉 이내(기다리는 중)", "양봉",
                                          "밴드 안에서 마감"]
    for o in v["overlays"]:
        assert len(o["values"]) == len(df)
    r = sv.render("REEL_H1", df, "5m", tail=300)
    json.dumps(r, ensure_ascii=False)
    assert [c["name"] for c in r["conditions"]["long"]] == [k for k, _a in v["long"]]
    assert r["conditions"]["short"] == []
    for o in r["overlays"]:
        assert all(np.isfinite(p["value"]) for p in o["data"] if "value" in p), o["name"]


@pytest.mark.parametrize("n", [0, 1, 2, 3, 25, 199, 230])
def test_view_runs_on_very_short_frames(view, n):
    df = synth(260, 9).iloc[:n].reset_index(drop=True)
    v = view(df.copy(), "5m")
    for o in v["overlays"]:
        assert len(o["values"]) == n
    assert all(np.asarray(a).shape == (n,) for _k, a in v["long"])
    if n < 200:                                  # SMA200 is not there yet: the filter is off
        assert not AND(v["long"], n).any()
