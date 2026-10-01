"""Entry marks of live signals (paperbot/entry_marks.py) against the entry study's own code.

Parity: the live marks of a frame truncated at bar i equal research/entry_study/sr.py and
strength_defs/<NAME>.py (loaded the study's way, analysis_bc.load_def) run on the whole series at
bar i, on Binance futures bars from data/pre2021. Plus: the signal path is unchanged by the marks,
failures are recorded instead of raised, the loss-card tags and the strategy endpoint."""

from __future__ import annotations

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
import pytest

from paperbot import entry_marks as EM
from paperbot import sigservice as SS
from paperbot import sweepsig
from paperbot.recorder import build_frames

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))

import sr as SR_RESEARCH  # noqa: E402  (the study's module, imported the study's way)

PRE = os.path.join(ROOT, "data", "pre2021")
L = sweepsig.lib()


def _csv(coin: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(PRE, f"{coin}-{tf}.csv.gz"))
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.attrs["tf"] = tf
    return df


def _chart(coin: str, tf: str) -> pd.DataFrame:
    if tf == "30m":                     # no 30m file: the locked resampler on the 15m bars
        return L.resample_ohlcv(_csv(coin, "15m"), "30m")
    return _csv(coin, tf)


def _research_sr(df: pd.DataFrame, tf: str, i: int, side: int) -> dict:
    f = SR_RESEARCH.features_for(df, tf, None, np.array([i]), np.array([side]))
    return {k: v[0] for k, v in f.items()}


def _same_sr(live: dict, ref: dict, rel: float = 1e-9) -> None:
    assert live["lev"] == (float(ref["lev"]) if np.isfinite(ref["lev"]) else None)
    for name in ("room", "floor"):
        assert live[name] == pytest.approx(float(ref[name]), abs=5e-5), name
        assert live[name + "_type"] == int(ref[name + "_type"]) and live[name + "_kind"] == int(ref[name + "_kind"])
        assert live[name + "_ko"] == EM.KIND_KO.get(int(ref[name + "_kind"]))
    for mine, theirs in (("room_px", "ahead_px"), ("floor_px", "behind_px"), ("lock_px", "lock_px"),
                         ("stop_px", "stop_px"), ("atr", "atr"), ("close", "close")):
        want = float(ref[theirs])
        if np.isfinite(want):
            assert live[mine] == pytest.approx(want, rel=rel), mine
        else:
            assert live[mine] is None, mine
    for flag in EM.FLAGS:
        want = float(ref[flag])
        assert live[flag] == (int(want) if np.isfinite(want) else None), flag


# ------------------------------------------------------------------ S/R parity
@pytest.mark.parametrize("coin,tf", [("bchusd", "15m"), ("ethusd", "30m"), ("btcusd", "1h"), ("dogeusd", "4h")])
def test_sr_marks_of_a_truncated_frame_equal_the_study(coin, tf):
    df = _chart(coin, tf)
    n = len(df)
    for i in (n - 1, n // 2, 700, 333):
        live = EM.sr_marks(df.iloc[:i + 1].reset_index(drop=True), tf)
        for side in (1, -1):
            _same_sr(live[str(side)], _research_sr(df, tf, i, side))


@pytest.mark.parametrize("tf", ["5m", "15m", "30m", "1h", "4h"])
def test_live_history_gives_the_full_history_levels(tf):
    """What the service sends (signal window, plus the older bars of marks_window_5m where that is
    longer, i.e. 4h) gives the same marks as the study on all bars since 2020-01-01."""
    d5 = _csv("ltcusd", "5m")
    per = L.tf_minutes(tf) // 5
    for back in (0, 7 * per + 3 * per):
        end = len(d5) - (len(d5) % per) - back                 # 5m bars up to a chart bar close
        full = build_frames(L, d5.iloc[:end].reset_index(drop=True), [tf])[tf]
        n = SS.window_5m(L, tf)
        m = max(n, EM.marks_window_5m(L, tf))
        win = d5.iloc[end - n:end].reset_index(drop=True)
        df = build_frames(L, win, [tf])[tf]
        pre = d5.iloc[end - m:end - n]
        sr_df = None
        if len(pre):
            p = (pre["ts"].astype("int64").to_numpy() // 1_000_000, pre["open"].to_numpy(), pre["high"].to_numpy(),
                 pre["low"].to_numpy(), pre["close"].to_numpy(), pre["volume"].to_numpy())
            sr_df = SS._marks_frame(L, p, win, df, tf)
            assert sr_df is not None and len(sr_df) > len(df)
        assert tf != "4h" or sr_df is not None                 # the 4h signal window alone is too short
        live = EM.marks(df, tf, {}, sr_df)["sr"]
        for side in (1, -1):
            _same_sr(live[str(side)], _research_sr(full, tf, len(full) - 1, side), rel=1e-7)


def test_marks_window_covers_the_study_lookbacks():
    SR = EM.sr_module()
    for tf, htf in SR.HTF.items():
        per, hper = L.tf_minutes(tf) // 5, L.tf_minutes(htf) // 5
        m = EM.marks_window_5m(L, tf)
        assert m >= (SR.PIVOT_LOOKBACK + SR.PIVOT_K + 1) * hper and m >= SR.VP_BARS * per and m >= 14 * 288
    assert EM.marks_window_5m(L, "1d") == 0
    svc = SS.SignalService(["BTCUSDT"], [], random_rates={}, procs=1)
    keep = svc.hist["BTCUSDT"].maxlen
    assert all(m <= keep for m in svc.mark_windows.values())   # the service holds enough 5m bars


# ------------------------------------------------------------------ strength parity
def test_strength_marks_equal_the_study_for_all_36():
    BC = pytest.importorskip("analysis_bc")
    df = _csv("solusd", "1h").iloc[-1500:].reset_index(drop=True)
    df.attrs["tf"] = "1h"
    names = SS.strategy_names(L)
    assert len(names) == 36
    for name in names:
        S = BC.load_def("strength_defs", name)
        ref = S.strength(df, "1h")
        for i in (len(df) - 1, 1100, 900):
            cut = df.iloc[:i + 1].reset_index(drop=True)
            cut.attrs["tf"] = "1h"
            for side in (1, -1):
                live = EM.strength_marks(name, cut, "1h", side)
                assert live["side"] == side and [f["name"] for f in live["features"]] == [f["name"] for f in S.FEATURES]
                for f, lf in zip(S.FEATURES, live["features"]):
                    want = float(BC.side_values(ref[f["name"]][0], ref[f["name"]][1], [i], [side])[0])
                    assert lf["label_ko"] == f["label_ko"] and lf["higher_is_stronger"] == f["higher_is_stronger"]
                    if np.isfinite(want):
                        assert lf["value"] == pytest.approx(want, rel=1e-5, abs=1e-12), (name, f["name"], i, side)
                    else:
                        assert lf["value"] is None, (name, f["name"], i, side)
    assert EM.strength_marks("RANDOM_1", df, "1h", 1) is None


def test_strength_defs_load_only_when_they_match_the_locked_hashes(monkeypatch, tmp_path):
    man = tmp_path / "DEFS_BC.sha256"
    man.write_text("0" * 64 + "  strength_defs/N24_DMI.py\n")
    monkeypatch.setattr(EM, "DEFS_SHA", str(man))
    monkeypatch.setattr(EM, "_STRENGTH", {})
    with pytest.raises(RuntimeError, match="locked"):
        EM.strength_module("N24_DMI")
    m = EM.marks(_csv("btcusd", "1h").iloc[-400:].reset_index(drop=True), "1h", {"N24_DMI": 1})
    assert "sha256" in m["strength"]["N24_DMI"]["error"] and "1" in m["sr"]


def test_loading_the_study_leaves_the_process_as_it_was(monkeypatch):
    monkeypatch.delenv("SWEEP_DATA", raising=False)
    for k in [k for k in sys.modules if k.startswith("_paperbot_entry_sr") or k.startswith("_paperbot_strength_")]:
        monkeypatch.delitem(sys.modules, k)
    monkeypatch.setattr(EM, "_SR", None)
    monkeypatch.setattr(EM, "_STRENGTH", {})
    path, filters = list(sys.path), list(warnings.filters)
    EM.sr_module()
    EM.strength_module("DOGE")
    EM.sr_marks(_csv("btcusd", "4h").iloc[-400:].reset_index(drop=True), "4h")
    assert sys.path == path and warnings.filters == filters and "SWEEP_DATA" not in os.environ


# ------------------------------------------------------------------ the live worker
def _df5(n: int, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    ts = np.arange(n, dtype=np.int64) * 300_000 + 1_700_006_400_000      # a UTC midnight
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999,
                         "close": c, "volume": rng.uniform(1, 5, n)})


def _job(d: pd.DataFrame, tf: str, end: int, n: int, m: int = 0) -> tuple:
    a = d.iloc[end - n:end]
    job = ("BTCUSDT", tf, int(a["ts"].iloc[-1]) + 300_000, a["ts"].to_numpy(), a["open"].to_numpy(),
           a["high"].to_numpy(), a["low"].to_numpy(), a["close"].to_numpy(), a["volume"].to_numpy())
    if m > n:
        p = d.iloc[end - m:end - n]
        job += ((p["ts"].to_numpy(), p["open"].to_numpy(), p["high"].to_numpy(), p["low"].to_numpy(),
                 p["close"].to_numpy(), p["volume"].to_numpy()),)
    return job


def test_worker_signals_are_the_same_with_and_without_the_marks(monkeypatch):
    tf = "4h"
    n = SS.window_5m(L, tf)
    m = EM.marks_window_5m(L, tf)
    d = _df5(m + 48 * 40)
    fired = 0
    for k in range(40):
        end = m + 48 * k
        plain = SS.compute_last(_job(d, tf, end, n))
        long = SS.compute_last(_job(d, tf, end, n, m))
        assert plain["ready"] and plain["sides"] == long["sides"] and plain["atr"] == long["atr"]
        assert plain.get("ctx") == long.get("ctx")
        if any(plain["sides"].values()):
            fired += 1
            w5 = _frame5(d, end, n)
            want = EM.sr_marks(SS._marks_frame(L, _job(d, tf, end, n, m)[9], w5, build_frames(L, w5, [tf])[tf], tf), tf)
            assert long["marks"]["sr"] == want
            assert set(long["marks"]["strength"]) == {k2 for k2, v in long["sides"].items() if v}
        else:
            assert "marks" not in plain and "marks" not in long
    assert fired


def _frame5(d: pd.DataFrame, end: int, n: int) -> pd.DataFrame:
    a = d.iloc[end - n:end].reset_index(drop=True)
    return a.assign(ts=pd.to_datetime(a["ts"], unit="ms", utc=True))


def test_jobs_keep_the_signal_window_and_add_older_bars_for_4h_only():
    svc = SS.SignalService(["BTCUSDT"], [], random_rates={}, procs=1, trade_tfs=("1h", "4h"), record_tfs=("1d",))
    d = _df5(100_000)
    svc.bootstrap("BTCUSDT", d.itertuples(index=False, name=None))
    b = int(d["ts"].iloc[-1]) + 300_000
    rows = list(svc.hist["BTCUSDT"])
    for tf in ("1h", "4h"):
        job, = svc._jobs(b, tf)
        n = svc.windows[tf]
        a = np.array(rows[-n:], dtype=float)                  # the construction before the marks existed
        for k, col in enumerate((a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])):
            assert np.array_equal(job[3 + k], col) and job[3 + k].dtype == col.dtype
        if tf == "1h":
            assert len(job) == 9
        else:
            assert len(job) == 10 and len(job[9][0]) == svc.mark_windows[tf] - n and job[9][0][-1] < job[3][0]


def test_failures_are_recorded_and_signals_still_flow(monkeypatch):
    svc = SS.SignalService(["BTCUSDT"], [], random_rates={"1h": 1.0}, seeds=(1,), procs=1, trade_tfs=("1h",),
                           record_tfs=())
    name = svc.names[0]
    marks = {"sr": {"1": {"room": 1.5, "level_before_lock": 1}, "-1": {"room": 0.5}},
             "strength": {name: {"side": 1, "features": [{"name": "x", "value": 2.0}]}}, "ms": {}}
    fake = {"symbol": "BTCUSDT", "tf": "1h", "ready": True, "close": 100.0, "atr": 1.0, "sides": {name: 1},
            "errors": [], "ctx": {"regime": "box"}, "marks": marks}
    svc._jobs = lambda boundary, tf: []
    svc._map = lambda jobs: [fake]
    rows, subs, _ = svc.compute(3_600_000 * 10, "1h", lambda: 3_600_000 * 10 + 2000,
                                lambda: {"BTCUSDT": (99.9, 100.1)})
    by = {r["strategy"]: r for r in rows}
    ctx = by[name]["data"]["ctx"]
    assert ctx["regime"] == "box" and ctx["sr"]["room"] == 1.5 and ctx["strength"]["features"][0]["value"] == 2.0
    rnd = [r for r in rows if r["strategy"].startswith("RANDOM_")]
    assert rnd and "strength" not in rnd[0]["data"]["ctx"]
    assert rnd[0]["data"]["ctx"]["sr"] == marks["sr"][str(rnd[0]["side"])]
    assert dict(subs)[f"{name}@1h"].meta["ctx"] == ctx
    assert fake["ctx"] == {"regime": "box"}                   # the bar's ctx is not changed in place

    fake["marks"] = {"error": "ValueError: x"}
    rows, subs, _ = svc.compute(3_600_000 * 10, "1h", lambda: 3_600_000 * 10 + 2000,
                                lambda: {"BTCUSDT": (99.9, 100.1)})
    assert rows[0]["status"] == "SUBMITTED" and rows[0]["data"]["ctx"]["marks_error"] == "ValueError: x"

    def boom(*a, **k):
        raise ZeroDivisionError("nope")
    monkeypatch.setattr(EM, "sr_marks", boom)
    monkeypatch.setattr(EM, "strength_marks", boom)
    m = EM.marks(_csv("btcusd", "1h").iloc[-400:].reset_index(drop=True), "1h", {"N01_ST_EMA": -1, "N24_DMI": 0})
    assert m["sr"] == {"error": "ZeroDivisionError: nope"} and m["strength"] == {"N01_ST_EMA": m["sr"]}
    assert EM.attach({"adx": 20}, m, "N01_ST_EMA", -1)["sr"] == {"error": "ZeroDivisionError: nope"}
    assert EM.marks(_csv("btcusd", "1h").iloc[-400:], "1d", {})["sr"]["error"].startswith("no higher timeframe")

    monkeypatch.setattr(EM, "marks", boom)
    d = _df5(SS.window_5m(L, "1h") + 12 * 200, seed=9)
    n = SS.window_5m(L, "1h")
    for k in range(200):
        r = SS.compute_last(_job(d, "1h", n + 12 * k, n))
        if any(r["sides"].values()):
            assert r["marks"] == {"error": "ZeroDivisionError: nope"} and "ctx" in r
            break
    else:
        pytest.fail("no signal in the synthetic series")


# ------------------------------------------------------------------ loss cards
def _trade(ctx: dict, **over) -> dict:
    t = {"strategy_id": "N24_DMI", "symbol": "BTCUSDT", "timeframe": "1h", "side": 1, "signal_ts": 899_999,
         "entry_time": 900_000, "entry_price": 100.0, "exit_time": 900_000 + 5 * 3_600_000, "exit_price": 99.0,
         "exit_reason": "SL", "leverage": 20, "roe": -0.2, "pnl": -10.0, "mfe_price": None, "mae_price": None,
         "context": ctx}
    t.update(over)
    return t


def test_card_tags_from_the_entry_marks():
    from paperbot.cards import TAG_NOTES, TAGS, card, tag_stats
    sr = {"room": 0.4, "room_ko": "전날 고가", "floor": 0.8, "floor_ko": "스윙 저점", "level_before_lock": 1,
          "support_before_stop": 1, "breakout": 0}
    st = {"side": 1, "features": [{"name": "adx_drop", "label_ko": "ADX", "value": 3.0}]}
    c = card("N24_DMI@1h", _trade({"sr": sr, "strength": st}), 0.0014)
    assert {"저항 바로 앞 진입", "지지선 뒤 손절"} <= set(c["tags"]) and "돌파 진입" not in c["tags"]
    assert c["sr"] == sr and c["strength"] == st["features"]
    c2 = card("N24_DMI@1h", _trade({"sr": {**sr, "level_before_lock": None, "support_before_stop": 0,
                                           "breakout": 1}}), 0.0014)
    assert "돌파 진입" in c2["tags"] and not {"저항 바로 앞 진입", "지지선 뒤 손절"} & set(c2["tags"])
    for ctx in ({}, {"sr": None}, {"sr": {"error": "x"}}, {"sr": "junk"}, {"strength": {"error": "y"}}):
        c3 = card("N24_DMI@1h", _trade(ctx), 0.0014)
        assert not {"저항 바로 앞 진입", "지지선 뒤 손절", "돌파 진입"} & set(c3["tags"])
        assert c3["sr"] is None and c3["strength"] is None
    sr_tags = {"저항 바로 앞 진입", "지지선 뒤 손절", "돌파 진입"}
    assert sr_tags <= set(TAG_NOTES) <= {n for n, _ in TAGS}
    assert set(TAG_NOTES) - sr_tags == {"경제지표 발표 전후"}          # the macro tag (events.py) has its own note
    assert all("관계없" in TAG_NOTES[n] for n in sr_tags)              # descriptive: the study found no effect
    assert "설명용" in TAG_NOTES["경제지표 발표 전후"]
    rows = {r["tag"]: r for r in tag_stats([c, card("N24_DMI@1h", _trade({}, pnl=5.0, roe=0.1), 0.0014)])}
    assert rows["저항 바로 앞 진입"]["loss_share"] == 1.0 and rows["저항 바로 앞 진입"]["win_share"] == 0.0
    assert rows["돌파 진입"]["note"] == TAG_NOTES["돌파 진입"] and rows["강제청산"]["note"] is None


# ------------------------------------------------------------------ dashboard
def test_strategy_endpoint_shows_the_latest_signal_marks(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    import time

    from fastapi.testclient import TestClient

    import paperbot.strategy_views as sv
    from paperbot.dash.app import create_app, hash_password
    from paperbot.store3 import Store3

    def view(df, tf):
        return {"overlays": [], "panes": [], "long": [("항상", np.ones(len(df), bool))], "short": []}

    db = str(tmp_path / "p.db")
    s = Store3(db)
    now = int(time.time() * 1000)
    sr = {"room": 1.25, "room_ko": "라운드 넘버", "floor": 0.5, "floor_ko": "스윙 저점", "breakout": 1}
    st = {"side": -1, "features": [{"name": "f", "label_ko": "강도", "unit": "ATR14", "unit_ko": "ATR",
                                    "higher_is_stronger": True, "value": 0.7}]}
    rows = [{"bar_close": now - 7_200_000, "timeframe": "1h", "strategy": "X", "symbol": "BTCUSDT", "side": 1,
             "atr": 1.0, "ref_price": 1.0, "ref_time": now, "delay_ms": 1, "status": "SUBMITTED",
             "data": {"ctx": {"sr": {"room": 9}}}},
            {"bar_close": now - 3_600_000, "timeframe": "1h", "strategy": "X", "symbol": "BTCUSDT", "side": -1,
             "atr": 1.0, "ref_price": 1.0, "ref_time": now, "delay_ms": 1, "status": "SUBMITTED",
             "data": {"ctx": {"regime": "box", "sr": sr, "strength": st}}},
            {"bar_close": now - 60_000, "timeframe": "1h", "strategy": "Y", "symbol": "BTCUSDT", "side": 1,
             "atr": 1.0, "ref_price": 1.0, "ref_time": now, "delay_ms": 1, "status": "SUBMITTED", "data": {}},
            {"bar_close": now - 60_000, "timeframe": "1h", "strategy": "X", "symbol": "ETHUSDT", "side": 1,
             "atr": 1.0, "ref_price": 1.0, "ref_time": now, "delay_ms": 1, "status": "SUBMITTED", "data": {}}]
    s.log_signals(rows)
    s.conn.commit()
    s.close()
    monkeypatch.setattr(sv, "_VIEWS", {"X": view, "Z": view})
    ts = pd.date_range("2026-01-01", periods=60, freq="1h", tz="UTC")
    c = np.linspace(100, 110, 60)
    frame = pd.DataFrame({"ts": ts, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0})
    app = create_app(db, hash_password("correct horse battery"), b"x" * 32, frames=lambda s_, tf, n: frame)
    cl = TestClient(app)
    cl.post("/api/login", json={"password": "correct horse battery"})
    r = cl.get("/api/strategy/X", params={"tf": "1h", "symbol": "BTCUSDT"}).json()
    assert r["conditions"]["long"][0]["on"] is True
    ls = r["last_signal"]
    assert ls["side"] == -1 and ls["status"] == "SUBMITTED" and ls["sr"] == sr and ls["strength"] == st
    assert ls["bar_close"] == now - 3_600_000 and ls["error"] is None
    assert cl.get("/api/strategy/X", params={"tf": "1h", "symbol": "SOLUSDT"}).json()["last_signal"] is None
    assert cl.get("/api/strategy/Z", params={"tf": "1h", "symbol": "BTCUSDT"}).json()["last_signal"] is None
    eth = cl.get("/api/strategy/X", params={"tf": "1h", "symbol": "ETHUSDT"}).json()["last_signal"]
    assert eth["sr"] is None and eth["strength"] is None             # a signal logged before the marks existed


def test_signal_log_rows_serialise_the_marks(tmp_path):
    from paperbot.store3 import Store3
    df = _csv("btcusd", "1h").iloc[-800:].reset_index(drop=True)
    m = EM.marks(df, "1h", {"N01_ST_EMA": 1, "DOGE": -1})
    ctx = EM.attach({"adx": 12.0}, m, "DOGE", -1)
    s = Store3(str(tmp_path / "p.db"))
    s.log_signals([{"bar_close": 1, "timeframe": "1h", "strategy": "DOGE", "symbol": "BTCUSDT", "side": -1,
                    "atr": 1.0, "ref_price": None, "ref_time": 1, "delay_ms": 0, "status": "RECORD",
                    "data": {"ctx": ctx}}])
    back = json.loads(s.conn.execute("SELECT data FROM signal_log").fetchone()[0])["ctx"]
    s.close()
    assert back == ctx and back["sr"] == m["sr"]["-1"] and back["strength"]["side"] == -1
    assert "NaN" not in json.dumps(back)
