"""Chart views of the DeepSeek-200 structure family (paperbot/strategy_view_defs/DS_<ID>.py): F3_BOS, F3_BOS_ZONE,
F3_HHHL, F12_MSS, F12_MSS_DISP, F13_FVG_PD, F13_RAID_PD, F14_SMT.

AND of a view's long (short) conditions must equal research/deepseek200/lib_c.py ``entries()`` long (short) on every
bar. lib_c is loaded by path under a private module name, contained: sys.path and the warnings filters are restored
(checked here). Fast tests use synthetic bars; the real-bar test needs DS_BARS_DIR (a directory holding
<coin>-5m.csv.gz of the research/binance_data build) and is skipped without it.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_C = os.path.join(ROOT, "research", "deepseek200", "lib_c.py")
IDS = ("F3_BOS", "F3_BOS_ZONE", "F3_HHHL", "F12_MSS", "F12_MSS_DISP", "F13_FVG_PD", "F13_RAID_PD", "F14_SMT")
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
BARS = os.environ.get("DS_BARS_DIR", "")
HANGUL = re.compile("[가-힣]")


@pytest.fixture(scope="module")
def C():
    """lib_c, loaded contained (as paperbot/dssig.py and entry_marks._contained do)."""
    from paperbot import sweepsig
    sweepsig.lib()                                   # the vendored indicators, as the dashboard loads them
    name = "_test_strategy_views_ds_structure_lib_c"
    path0, filters0 = list(sys.path), list(warnings.filters)
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, LIB_C)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        from paperbot.entry_marks import _contained
        try:
            with _contained():                   # restores sys.path, the warnings filters and SWEEP_DATA
                spec.loader.exec_module(mod)     # lib_c inserts into sys.path and sets filterwarnings("ignore")
                mod.env()
        except BaseException:
            sys.modules.pop(name, None)
            raise
        finally:
            sys.path[:] = path0
    assert sys.path == path0, "lib_c changed sys.path"
    assert warnings.filters == filters0, "lib_c changed the warnings filters"
    return mod


@pytest.fixture(scope="module")
def V(C):
    return {i: getattr(importlib.import_module(f"paperbot.strategy_view_defs.DS_{i}"), f"view_DS_{i}") for i in IDS}


def bars(n: int, tf: str, seed: int, base=None, beta: float = 0.0) -> pd.DataFrame:
    """Random walk with trending / ranging stretches and big candles. ``base`` (a frame) adds beta x its returns."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.choice([-1, 0, 0, 1], size=n // 120 + 1), 120)[:n]
    sig = 0.006 * np.exp(np.repeat(rng.normal(0, 0.4, n // 60 + 1), 60)[:n])
    ret = rng.normal(0, 1, n) * sig + regime * 0.15 * sig
    ret[rng.random(n) < 0.03] *= 4
    if base is not None:
        ret = beta * np.diff(np.log(base["close"].to_numpy()), prepend=np.log(base["close"].iloc[0])) + ret * 0.6
    c = 100 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.0005, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 1, n) * sig * 0.8)
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 1, n) * sig * 0.8)
    ts = pd.date_range("2025-01-01", periods=n, freq=f"{TF_MIN[tf]}min", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": rng.lognormal(0, 1, n) * 100})


def AND(view: dict, side: str, n: int) -> np.ndarray:
    conds = view[side]
    return np.logical_and.reduce([np.asarray(a, bool) for _k, a in conds]) if conds else np.zeros(n, bool)


def assert_exact(C, V, df, tf, coin="ETHUSD", btc=None, ids=IDS, attrs_btc=False) -> dict:
    """AND(conditions) == lib_c on every bar, both sides; returns the lib_c signal counts."""
    R = C.entries(df.copy(), tf, {"BTCUSD": btc} if btc is not None else None, coin)
    counts = {}
    for i in ids:
        d = df.copy()
        if i == "F14_SMT" and attrs_btc:
            d.attrs["btc"] = btc
            v = V[i](d, tf)
        else:
            v = V[i](d, tf, btc) if i == "F14_SMT" else V[i](d, tf)
        for side, k in (("long", 0), ("short", 1)):
            want = np.asarray(R[i][k], bool)
            got = AND(v, side, len(df))
            bad = np.flatnonzero(want != got)
            assert not len(bad), f"{i} {tf} {side}: {len(bad)} bars differ, first {bad[:5].tolist()}"
            counts[(i, side)] = int(want.sum())
    return counts


# ------------------------------------------------------------------ ids and the view contract
def test_ids_are_lib_c_definitions(C):
    assert all(i in C.DEF_IDS for i in IDS)
    assert all(dict((d[0], d[2]) for d in C.DEFS)[i] == ("15m", "30m", "1h", "4h") for i in IDS)


@pytest.mark.parametrize("ident", IDS)
def test_view_contract(V, ident):
    df = bars(700, "1h", 3)
    btc = bars(700, "1h", 4)
    v = V[ident](df, "1h", btc) if ident == "F14_SMT" else V[ident](df, "1h")
    assert set(v) == {"overlays", "panes", "long", "short"}
    assert v["overlays"] and v["long"] and v["short"]
    for o in v["overlays"]:
        # "join": True = a line through pivot points that the chart draws joined (the zigzag); every other v4 line
        # breaks where it has no value (strategy_views.render, once the v4 gap patch is applied)
        assert set(o) - {"join"} == {"name", "values"} and o.get("join", True) is True
        assert HANGUL.search(o["name"]) or o["name"] == "EMA200"
        assert np.asarray(o["values"], dtype=float).shape == (700,)
    for p in v["panes"]:
        assert set(p) == {"name", "series", "levels"} and HANGUL.search(p["name"]) and isinstance(p["levels"], list)
        for s in p["series"]:
            assert HANGUL.search(s["name"]) and np.asarray(s["values"], dtype=float).shape == (700,)
    for side in ("long", "short"):
        for name, arr in v[side]:
            assert isinstance(name, str) and HANGUL.search(name)
            assert isinstance(arr, np.ndarray) and arr.dtype == bool and arr.shape == (700,)
        assert len({n for n, _a in v[side]}) == len(v[side])


@pytest.mark.parametrize("n", [0, 1, 5, 7, 30, 250])
def test_short_frames(V, n):
    df = bars(max(n, 1), "15m", 9).iloc[:n].reset_index(drop=True)
    for i in IDS:
        v = V[i](df.copy(), "15m")
        for o in v["overlays"]:
            assert len(o["values"]) == n
        for side in ("long", "short"):
            assert all(len(a) == n for _k, a in v[side])


# ------------------------------------------------------------------ exactness
@pytest.mark.parametrize("tf,seed", [("15m", 1), ("30m", 2), ("1h", 3), ("4h", 4), ("1h", 5)])
def test_exact_on_synthetic_bars(C, V, tf, seed):
    btc = bars(3000, tf, 100 + seed)
    df = bars(3000, tf, seed, base=btc, beta=0.9)
    counts = assert_exact(C, V, df, tf, btc=btc)
    assert_exact(C, V, df, tf, btc=btc, ids=("F14_SMT",), attrs_btc=True)
    assert all(v > 0 for (i, _s), v in counts.items() if i != "F3_BOS_ZONE"), counts
    assert counts[("F3_BOS_ZONE", "long")] + counts[("F3_BOS_ZONE", "short")] > 0


def test_exact_on_a_later_start_and_with_missing_btc_bars(C, V):
    btc = bars(4000, "1h", 21)
    df = bars(4000, "1h", 22, base=btc, beta=1.0)
    part = df.iloc[1234:].reset_index(drop=True)                     # history start changes the structure state
    assert_exact(C, V, part, "1h", btc=btc)
    holes = btc.drop(index=np.arange(1500, 4000, 7)).reset_index(drop=True)   # BTC bars missing: no F14 there
    assert_exact(C, V, df, "1h", btc=holes, ids=("F14_SMT",))
    assert_exact(C, V, df, "1h", btc=btc.iloc[-100:].reset_index(drop=True), ids=("F14_SMT",))   # dssig sends 100


def test_f14_both_sides_on_one_bar_give_neither(C, V):
    n = 30
    ts = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    flat = lambda p: pd.DataFrame({"ts": ts, "open": p, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 1.0})
    coin, btc = flat(np.full(n, 100.0)), flat(np.full(n, 50.0))
    btc.loc[25, ["high", "low"]] = [60.0, 40.0]       # BTC: new 20-bar high AND new 20-bar low; the coin holds both
    R = C.entries(coin.copy(), "1h", {"BTCUSD": btc}, "ETHUSD")
    v = V["F14_SMT"](coin.copy(), "1h", btc)
    assert not R["F14_SMT"][0][25] and not R["F14_SMT"][1][25]
    names = dict(v["long"])
    assert names["BTC가 20봉 저점을 새로 깸"][25] and names["이 코인은 20봉 저점을 지킴"][25]
    assert not names["반대(숏) 신호와 겹치지 않음"][25] and not AND(v, "long", n)[25] and not AND(v, "short", n)[25]
    btc.loc[25, "low"] = 49.0                        # only the new high now: short only
    v = V["F14_SMT"](coin.copy(), "1h", btc)
    assert AND(v, "short", n)[25] and not AND(v, "long", n).any()
    assert C.entries(coin.copy(), "1h", {"BTCUSD": btc}, "ETHUSD")["F14_SMT"][1][25]


def test_f14_without_btc_or_for_btc_itself_is_off(C, V):
    df = bars(800, "15m", 31)
    btc = bars(800, "15m", 32)
    for d in (df.copy(), df.copy()):
        v = V["F14_SMT"](d, "15m")                                      # no BTC bars at all
        assert not AND(v, "long", len(df)).any() and not AND(v, "short", len(df)).any()
        assert not dict(v["long"])["BTC가 20봉 저점을 새로 깸"].any()
    d = df.copy()
    d.attrs["symbol"] = "BTCUSDT"
    d.attrs["btc"] = btc
    v = V["F14_SMT"](d, "15m")
    assert not AND(v, "long", len(df)).any() and not AND(v, "short", len(df)).any()
    R = C.entries(df.copy(), "15m", None, "BTCUSD")
    assert not R["F14_SMT"][0].any() and not R["F14_SMT"][1].any()


def test_views_do_not_touch_the_frame(V):
    df = bars(600, "30m", 41)
    before = df.copy()
    for i in IDS:
        V[i](df, "30m")
    pd.testing.assert_frame_equal(df, before)


# ------------------------------------------------------------------ dashboard render
def test_render_through_strategy_views(V, monkeypatch):
    import paperbot.strategy_views as sv
    monkeypatch.setattr(sv, "_VIEWS", {f"DS_{i}": V[i] for i in IDS})
    df = bars(1500, "1h", 51)
    for i in IDS:
        r = sv.render(f"DS_{i}", df, "1h", tail=500)
        json.dumps(r, ensure_ascii=False)
        assert r["strategy"] == f"DS_{i}" and r["conditions"]["long"] and r["conditions"]["short"]
        for o in r["overlays"]:
            assert all(np.isfinite(p["value"]) for p in o["data"] if "value" in p) and len(o["data"]) <= 500
        assert all(isinstance(c["on"], bool) for side in ("long", "short") for c in r["conditions"][side])


# ------------------------------------------------------------------ recorded checks
@pytest.mark.parametrize("ident", IDS)
def test_docstring_records_exact_checks(ident):
    mod = importlib.import_module(f"paperbot.strategy_view_defs.DS_{ident}")
    line = mod.__doc__.split("Checks: ", 1)[1].splitlines()[0]
    checks = json.loads(line)
    rp = {k: v for k, v in checks.items() if k.endswith(("_recall", "_precision"))}
    assert len(rp) == 16 and all(v == 1 for v in rp.values()), rp
    assert all(v > 0 for k, v in checks.items() if k.endswith("_signals"))


# ------------------------------------------------------------------ real bars, live windows (needs DS_BARS_DIR)
@pytest.mark.skipif(not (BARS and os.path.exists(os.path.join(BARS, "btcusd-5m.csv.gz"))),
                    reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")
def test_exact_on_real_live_windows(C, V):
    from paperbot import dssig, sweepsig
    from paperbot.config import DS_WINDOW_5M
    L = sweepsig.lib()
    five = {}

    def cols(coin):
        if coin not in five:
            d = pd.read_csv(os.path.join(BARS, f"{coin.lower()}-5m.csv.gz"))
            t = (pd.to_datetime(d["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(np.int64)
            five[coin] = (t,) + tuple(d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        return five[coin]

    def window(coin, tf, boundary, since=None):
        a = cols(coin)
        keep = a[0] + 300_000 <= boundary
        if since is not None:
            return dssig.frame(*(x[keep & (a[0] >= since)] for x in a), tf=tf, lib=L)
        return dssig.frame(*(x[keep][-DS_WINDOW_5M[tf]:] for x in a), tf=tf, lib=L)

    total = {}
    for coin, tf, when in (("BTCUSD", "15m", "2023-03-10"), ("ETHUSD", "1h", "2024-08-05"),
                           ("SOLUSD", "4h", "2026-09-01"), ("DOGEUSD", "30m", "2022-06-15")):
        b = int(pd.Timestamp(when, tz="UTC").value // 1_000_000)
        df = window(coin, tf, b)
        assert int(df["ts"].iloc[-1].value // 1_000_000) + dssig.TF_MS[tf] == b
        btc = None
        if coin != "BTCUSD":
            first = int(df["ts"].iloc[0].value // 1_000_000)
            btc = window("BTCUSD", tf, b, since=max(first, b - dssig.BTC_TF_BARS * dssig.TF_MS[tf]))
        for k, v in assert_exact(C, V, df, tf, coin=coin, btc=btc).items():
            total[k] = total.get(k, 0) + v
    assert all(total[(i, s)] > 0 for i in IDS for s in ("long", "short") if i != "F14_SMT"), total
