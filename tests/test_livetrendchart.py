"""실거래 › 추세 차트 (#/tchart; owners 10/21 "대시보드 화면들 더 멋있게 모든 필요한 화면 부분들 다 추가로 만들어줘"; GET
/api/v4/livebots/trendchart, dash/more/livetrendchart.py; screens/livebots-tchart.js, livebots-tchart.css).

- ``history`` (every bar's judgment in one pass) equals trendjudge.judge_frame of the frame up to that bar, bar for bar
  (direction, raw vote, the four judges, ADX and the one before, EMA20, ATR, 끝물, 힘), on several markets, both
  judged timeframes and other numbers; and the newest cell on the bot's own 300-bar frame (trendjudge.Judge) is the same;
- the answer on a paper database written by the trend bot's own code (tests/test_livetrend.py's world) and synthetic
  Binance klines: 72 hourly cells per coin, the 4h cells, the cell in force now, the bot-record check, the entries and
  the supervisor's exit on the heatmap, the coin's signals by what became of them (entered / wait), its trades, the
  wait's level; at most FETCH_PER_BUILD fetches an answer (``pending`` until all are in), no fetch until a new bar
  closes; honest states: no file, another bot, no judgment yet, Binance down (못 읽음 with the reason, never a cell);
- the route is in the live site and the tab is wired (menu, search, css, inventory, docs);
- the view in node (the tiny DOM, a stand-in chart library that records what it was given): the heatmap, the now-chips,
  the check, the readout, the chart's candles / EMA / band / markers / the wait's dashed line, the events, 읽는 법; the
  pure helpers; then static checks of the js and the css."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_livetrend as LTT  # noqa: E402
import test_trendbot as T  # noqa: E402
from paperbot import trendjudge as TJ  # noqa: E402
from paperbot.dash.more import livetrendchart as TC  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-tchart.js")
CSS = os.path.join(SCREENS, "livebots-tchart.css")
HOUR = 3_600_000
MIN = 60_000
RULES = TJ.TrendRules()


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- synthetic Binance klines (a market with regimes)
ANCHOR = T.T0 - 120 * 86_400_000              # 4h-aligned: every timeframe's bars line up
_PATHS: dict = {}
TF_N = {"30m": 1, "1h": 2, "4h": 8, "1d": 48}


def _base(symbol: str):
    """30m bars from ANCHOR for 150 days: drifting up, down or sideways for 1-3 days at a time."""
    if symbol not in _PATHS:
        rng = np.random.default_rng(sum(symbol.encode()) * 7 + 3)
        n = 150 * 48
        drift = np.zeros(n)
        i = 0
        while i < n:
            k = int(rng.integers(48, 150))
            drift[i:i + k] = rng.choice([0.0012, -0.0012, 0.0, 0.0007, -0.0007])
            i += k
        ret = drift + rng.normal(0, 0.0035, n)
        c = np.exp(np.cumsum(ret))
        c *= T.PX.get(symbol, 100.0) / c[(T.T0 - ANCHOR) // 1_800_000]           # the world's price at T0
        o = np.r_[c[0], c[:-1]]
        hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0018, n)))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0018, n)))
        v = rng.uniform(80, 160, n) * (1 + 0.6 * np.abs(ret) / 0.0035)
        _PATHS[symbol] = (o, hi, lo, c, v)
    return _PATHS[symbol]


def synth_klines(symbol: str, interval: str, limit: int, now_ms: int) -> list:
    """Binance kline rows [open_ms, o, h, l, c, v, close_ms] of ``interval`` up to the bar holding ``now_ms`` (the forming
    one included, as Binance answers), the last ``limit``."""
    o, hi, lo, c, v = _base(symbol)
    k = TF_N[interval]
    ms = TJ.TF_MS[interval]
    m = (len(c) // k) * k
    agg = (o[:m:k], hi[:m].reshape(-1, k).max(axis=1), lo[:m].reshape(-1, k).min(axis=1), c[k - 1:m:k], v[:m].reshape(-1, k).sum(axis=1))
    last = int((now_ms - ANCHOR) // ms)
    first = max(0, last - limit + 1)
    return [[ANCHOR + i * ms, float(agg[0][i]), float(agg[1][i]), float(agg[2][i]), float(agg[3][i]), float(agg[4][i]),
             ANCHOR + (i + 1) * ms - 1] for i in range(first, min(last + 1, len(agg[0])))]


def synth_candles(symbol: str, interval: str, limit: int, now_ms: int) -> list:
    """/api/candles rows (dash/app.py fetch_candles' shape) of the same market."""
    return [{"time": r[0] // 1000, "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
            for r in synth_klines(symbol, interval, limit, now_ms)]


class Fetch:
    """A stand-in for Binance: synthetic rows, the calls counted, down on demand."""

    def __init__(self, now):
        self.now, self.calls, self.down = now, [], False

    def __call__(self, symbol, interval, limit):
        self.calls.append((symbol, interval, limit))
        if self.down:
            raise OSError("fapi.binance.com unreachable")
        return synth_klines(symbol, interval, limit, self.now["t"])


# ---------------------------------------------------------------- history == judge_frame, bar for bar
@pytest.mark.parametrize("tf,rules,step", [
    ("1h", RULES, 1),
    ("4h", RULES, 2),
    ("1h", TJ.TrendRules(vote_min=4, hold_1h=3, adx_min=25.0, adx_tired=35.0), 3),
    ("4h", TJ.TrendRules(vote_min=2, hold_4h=2, adx_min=15.0, adx_tired=30.0), 3),
])
def test_history_equals_judge_frame_bar_by_bar(tf, rules, step):
    """The heatmap's judgments are the bot's: element i of ``history`` = judge_frame(the frame up to bar i)."""
    fg, pi = TJ.lib()
    seen = set()
    frames = [T.frame(n=360, seed=5, drift=(0.002, -0.002), tf=tf), T.frame(n=360, seed=11, drift=(-0.0015, 0.0012), tf=tf),
              T.frame(n=300, seed=3, drift=(0.0, 0.0), tf=tf)]
    a = np.array(synth_klines("SOLUSDT", tf, 420, T.T0), dtype=float)
    frames.append(pd.DataFrame({"ts": pd.to_datetime(a[:, 0].astype(np.int64), unit="ms"), "open": a[:, 1], "high": a[:, 2],
                                "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5]}))
    for n, df in enumerate(frames):
        hist = TC.history(df, tf, rules, fg, pi)
        checked = 0
        for i in range(1, len(df), step if n == 0 else 3):          # the first market every ``step`` bars, the rest every 3
            try:
                j = TJ.judge_frame(df.iloc[:i + 1].reset_index(drop=True), "BTCUSDT", tf, rules, fg, pi)
            except TJ.TrendError:
                assert not hist["ok"][i], i                      # an empty value: 못 읽음 on the heatmap too
                continue
            assert bool(hist["ok"][i]) == (i >= TJ.MIN_BARS - 1), i      # the bot's frame refuses fewer bars
            assert (int(hist["dir"][i]), int(hist["raw"][i])) == (j.dir, j.raw), i
            assert {k: int(hist["votes"][k][i]) for k in TJ.JUDGES} == j.votes, i
            assert (int(hist["up"][i]), int(hist["down"][i])) == (j.up, j.down)
            assert int(hist["bar_close"][i]) == j.bar_close
            for name in ("adx", "adx_prev", "close", "ema20", "atr"):
                assert hist[name][i] == pytest.approx(getattr(j, name), rel=1e-12, abs=1e-12), (i, name)
            assert bool(hist["tired"][i]) == j.tired(rules) and bool(hist["strong"][i]) == (j.adx >= rules.adx_min)
            if hist["ok"][i]:
                checked += 1
                seen.add((j.dir, j.raw, j.tired(rules), j.adx >= rules.adx_min))
        assert checked > 50
    # every kind of cell came up: both trends, 보류, 유지 확인 중 (raw without dir), 힘 약함
    assert {s[0] for s in seen} == {1, -1, 0} and any(s[0] and not s[3] for s in seen)
    assert any(s[0] == 0 and s[1] != 0 for s in seen) == (rules.hold(tf) > 1)       # 유지 확인 중 only with a hold of 2+


def test_the_newest_cell_is_the_bots_own_judgment():
    """On the bot's own frame (trendjudge.Judge over Klines: the last 300 closed bars) the newest recomputed cell over 499
    bars is the same judgment, for every coin and every judged timeframe (1h, 4h, 1d: the synthetic market has only its
    120 days of daily bars, so both frames hold them all)."""
    now = {"t": T.T0 + 7 * HOUR + 20_000}
    judge = TJ.Judge(TJ.Klines(Fetch(now), lambda: now["t"]), RULES)
    b = TC.Bars(Fetch(now), lambda: now["t"])
    for sym in T.SYMS:
        for tf in TC.TFS:
            df, info = b.frame(sym, tf, now["t"], [99])
            want = TC.FRAME_BARS - 1 if tf != "1d" else (T.T0 - ANCHOR) // 86_400_000           # 499 rows, the forming one out
            assert info["state"] == "ok" and not info["stale"] and len(df) == want
            cell = TC.cells_of(b.history(sym, tf, df, RULES), now["t"] - HOUR, tf)[-1]
            j = judge.judgment(sym, tf, now["t"])
            assert TC._check(cell, j.to_dict(RULES)) == "same", (sym, tf)
            assert cell["t"] == j.bar_close and cell["votes"] == [j.votes[k] for k in TJ.JUDGES]


def test_the_cells_kinds():
    assert TC.kind(1, 1, True, False, True) == "up" and TC.kind(-1, -1, True, False, True) == "down"
    assert TC.kind(1, 1, False, False, True) == "up weak" and TC.kind(-1, -1, True, True, True) == "down tired"
    assert TC.kind(0, 1, True, False, True) == "hold up" and TC.kind(0, -1, True, False, True) == "hold down"
    assert TC.kind(0, 0, True, False, True) == "hold" and TC.kind(1, 1, True, False, False) == "na"
    h = {"bar_close": np.array([T.T0, T.T0 + HOUR]), "ok": np.array([False, True]), "dir": np.array([0, 1]), "raw": np.array([0, 1]),
         "up": np.array([0, 3]), "down": np.array([0, 1]), "votes": {k: np.array([0, 1 if k != "N12" else -1]) for k in TJ.JUDGES},
         "adx": np.array([np.nan, 27.456]), "adx_prev": np.array([np.nan, 26.0]), "strong": np.array([False, True]),
         "tired": np.array([False, False])}
    cells = TC.cells_of(h, T.T0, "1h")
    assert cells[0] == {"t": T.T0, "kind": "na", "why": "봉이 모자라거나 지표 값이 비어 있음 (봇도 판단 안 함)"}
    assert cells[1] == {"t": T.T0 + HOUR, "dir": 1, "raw": 1, "up": 3, "dn": 1, "votes": [1, 1, 1, -1], "adx": 27.46,
                        "adx_prev": 26.0, "kind": "up"}
    assert TC.cells_of(h, T.T0 + HOUR, "1h") == cells[1:]          # in force from its close for one bar


# ---------------------------------------------------------------- the answer
def _answer_world(tmp_path):
    w = LTT._world(tmp_path)
    now = {"t": T.T0 + HOUR + 2 * MIN}
    f = Fetch(now)
    return w, now, f, TC.Bars(f, lambda: now["t"])


def test_the_answer(tmp_path):
    w, now, f, b = _answer_world(tmp_path)
    p = {"paper": w.cfg.db}
    d = TC.build(p, "BTCUSDT", now["t"], b)
    # the first answer: FETCH_PER_BUILD fetches, the chosen coin first; the rest is 불러오는 중, never a made-up cell
    assert d["state"] == "ok" and d["pending"] is True and len(f.calls) == TC.FETCH_PER_BUILD
    assert f.calls[:3] == [("BTCUSDT", "1h", TJ.FETCH), ("BTCUSDT", "4h", TJ.FETCH), ("BTCUSDT", "1d", TJ.FETCH)]
    waiting = [s for s, row in d["heat"]["coins"].items() if row["1h"]["state"] == "pending"]
    assert waiting == ["SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"][-len(waiting):] and all(
        d["heat"]["coins"][s]["1h"]["cells"] == [] for s in waiting)
    d = TC.build(p, "BTCUSDT", now["t"], b)
    assert d["pending"] is False and len(f.calls) == 18
    d = TC.build(p, "BTCUSDT", now["t"] + 5 * MIN, b)
    assert len(f.calls) == 18                                     # no new bar closed: no fetch
    heat = d["heat"]
    assert list(heat["coins"]) == list(TC.COINS) and heat["hours"] == 72
    assert heat["t1"] == T.T0 + 2 * HOUR and heat["t0"] == heat["t1"] - 72 * HOUR
    for sym, row in heat["coins"].items():
        c1, c4, cd = row["1h"]["cells"], row["4h"]["cells"], row["1d"]["cells"]
        assert len(c1) == 72 and c1[0]["t"] == heat["t0"] and c1[-1]["t"] == T.T0 + HOUR      # the cell in force now
        assert c4[0]["t"] <= heat["t0"] < c4[0]["t"] + 4 * HOUR and c4[-1]["t"] == T.T0 and len(c4) == 19
        # the daily row (4h entries, owners 10-22): 4 days over the 72 hours, the newest closed at T0 (UTC midnight);
        # the synthetic market's 120 days are just enough for the newest (trendjudge.MIN_BARS): the older ones 못 읽음
        assert [c["t"] for c in cd] == [T.T0 - k * 86_400_000 for k in (3, 2, 1, 0)] and cd[-1]["kind"] != "na"
        assert all(c["kind"] == "na" for c in cd[:-1])
        assert all(c["kind"] in ("up", "down", "hold", "hold up", "hold down", "up weak", "down weak", "up tired", "down tired")
                   for c in c1 + c4)
        assert row["1h"]["stale"] is False and row["1h"]["check"] in ("same", "differs")
    assert d["rules"] == {"from": "bot", "vote_min": 3, "adx_min": 20.0, "adx_tired": 40.0, "hold_1h": 2, "hold_4h": 1, "hold_1d": 1,
                          "hold_entry": False, "pullback_wait": True, "time_bars": 4}
    # the heatmap's marks: the BTC long (30m: on the 1h row) and its supervisor exit (JUDGE at T0 + 1h)
    (e,) = d["marks"]["entries"]
    assert (e["symbol"], e["side"], e["tf"], e["htf"], e["t"], e["open"]) == ("BTCUSDT", 1, "30m", "1h", T.T0 + 32 * MIN, False)
    (x,) = d["marks"]["sup"]
    assert (x["reason"], x["reason_ko"], x["htf"]) == ("JUDGE", "감독(추세)", "1h") and x["why"].startswith("1시간 판단이 하락으로")
    # the chosen coin: its signal entered after its pullback, its trade, the band of both timeframes over 7 days
    c = d["chart"]
    (s,) = c["signals"]
    assert (s["kind"], s["kind_ko"], s["tf"], s["side"], s["entry_time"]) == ("entered", "진입", "30m", 1, T.T0 + 32 * MIN)
    assert s["why"].startswith("되돌림 확인: ") and s["level"] is not None and s["judge"].startswith("1시간 상승")
    (t,) = c["trades"]
    assert t["reason_ko"] == "감독(추세)" and t["entry_judge"].startswith("1시간 상승") and c["position"] is None and c["waits"] == []
    assert len(c["band"]["1h"]) == 168 and len(c["band"]["4h"]) == 43
    # ETH: the signal waiting for its pullback, its level as the chart's dashed line
    e = TC.build(p, "ETHUSDT", now["t"] + 5 * MIN, b)
    (s,) = e["chart"]["signals"]
    (wt,) = e["chart"]["waits"]
    assert (s["kind"], s["kind_ko"], s["cat"]) == ("wait", "되돌림 기다림", "pullback_wait") and s["level"] == pytest.approx(wt["level"])
    assert wt["member"] == "F3_BOS@30m" and wt["side"] == 1 and e["chart"]["trades"] == []
    # the next hour: the 1h bars of the six coins once (4h not yet)
    now["t"] = T.T0 + 2 * HOUR + 10_000
    d = TC.build(p, "BTCUSDT", now["t"], b)
    assert len(f.calls) == 24 and {x[1] for x in f.calls[18:]} == {"1h"}
    assert d["heat"]["coins"]["ETHUSDT"]["1h"]["cells"][-1]["t"] == T.T0 + 2 * HOUR


def test_the_check_against_the_bots_record(tmp_path):
    """The newest cell is compared with the bot's own judgment of that bar (state trend): the world's fake judge says
    otherwise (differs, with the bot's words); the real judge's record is the same."""
    w, now, f, b = _answer_world(tmp_path)
    d = TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)
    d = TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)
    btc = d["heat"]["coins"]["BTCUSDT"]["1h"]
    real = TJ.Judge(TJ.Klines(Fetch(now), lambda: now["t"]), RULES).judgment("BTCUSDT", "1h", now["t"])
    fake_says = btc["bot"]
    assert fake_says.startswith("1시간 하락") and btc["check"] == ("same" if real.dir == -1 and real.raw == -1 else "differs")
    st = w.store.get_state("trend")[1]
    jd = TJ.Judge(TJ.Klines(Fetch(now), lambda: now["t"]), RULES)
    st["coins"] = {s: {tf: jd.judgment(s, tf, now["t"]).to_dict(RULES) for tf in TC.TFS} for s in T.SYMS}
    w.store.put_state("trend", T.T0 + HOUR, st)
    w.store.commit()
    d = TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"] + MIN, b)
    assert all(row[tf]["check"] == "same" for row in d["heat"]["coins"].values() for tf in TC.TFS)


def test_honest_states(tmp_path):
    now = {"t": T.T0 + HOUR}
    b = TC.Bars(Fetch(now), lambda: now["t"])
    assert TC.build({"paper": str(tmp_path / "none.db")}, "BTCUSDT", now["t"], b)["state"] == "missing"
    s = Store3(str(tmp_path / "old.db"))
    s.put_state("combo_run", T.T0, {"config": {"name": "규칙봇 15", "trend": None}})
    s.commit()
    d = TC.build({"paper": str(tmp_path / "old.db")}, "BTCUSDT", now["t"], b)
    assert d["state"] == "off" and "추세판단 봇이 아니에요" in d["reason_ko"] and "heat" not in d
    s.put_state("combo_run", T.T0, {"config": {"name": "추세판단 봇", "trend": {}}})
    s.commit()
    d = TC.build({"paper": str(tmp_path / "old.db")}, "BTCUSDT", now["t"], b)
    assert d["state"] == "missing" and "첫 판단" in d["reason_ko"] and "heat" not in d
    s.close()
    assert b.k.rows == {}                                          # nothing fetched for an answer that shows no heatmap


def test_binance_down_says_so(tmp_path):
    """Bars that cannot be fetched: 못 읽음 with the reason, no cell; the trend bot's back-off holds the next fetches;
    the database part (signals, trades) still shows."""
    w, now, f, b = _answer_world(tmp_path)
    f.down = True
    d = TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)
    btc = d["heat"]["coins"]["BTCUSDT"]
    assert btc["1h"]["state"] == "error" and btc["1h"]["cells"] == [] and "바이낸스 봉을 못 받았어요" in btc["1h"]["reason_ko"]
    assert "unreachable" in btc["1h"]["reason_ko"] and len(f.calls) == 1             # the back-off: one failed request
    assert d["chart"]["signals"] and d["chart"]["trades"] and d["chart"]["band"] == {}
    # back up later: bars come in; an hour without a fetch keeps the older bars, said so (stale)
    f.down = False
    now["t"] += 3 * MIN
    TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)
    TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)
    f.down = True
    now["t"] = T.T0 + 2 * HOUR + 30_000
    d = TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)
    row = d["heat"]["coins"]["BTCUSDT"]["1h"]
    assert row["state"] == "ok" and row["stale"] is True and "최근 봉을 아직 못 받았어요" in row["reason_ko"]
    assert row["cells"][-1]["t"] == T.T0 + HOUR


def test_the_route_and_the_tab_are_wired():
    from paperbot.livedash import app as LA
    assert "livetrendchart" in LA.MODULES
    js = _read(os.path.join(SCREENS, "livebots.js"))
    assert 'import {tchartView} from "./livebots-tchart.js"' in js
    assert '{id: "tchart", label: "추세 차트", make: (ctx, hub) => tchartView(ctx, hub), own: true}' in js
    assert js.index('{id: "trend", label: "관제"') < js.index('{id: "tchart"') < js.index('{id: "hq", label: "한눈에"')
    routes = _read(os.path.join(V4, "core", "routes.js"))
    assert '"now", ko: "지금", screens: ["trend", "tchart", "hq", "pos"' in routes
    assert 'tchart: {ko: "추세 차트", group: "now", title: "추세 차트 (판단 기록과 신호)"}' in routes and "  tchart: () => [" in routes
    assert "tchart:" in _read(os.path.join(V4, "core", "search.js")).split("export const LIVE_ALIAS")[1]
    assert '@import url("livebots-tchart.css");' in _read(os.path.join(SCREENS, "livebots.css"))
    assert "livebots-tchart.js" in _read(os.path.join(V4, "INVENTORY.md"))
    assert "**추세 차트**" in _read(os.path.join(ROOT, "docs", "livedash-ko.md"))


def test_the_route_answers(tmp_path, monkeypatch):
    """GET /api/v4/livebots/trendchart on the live app (an unknown coin is refused)."""
    from fastapi.testclient import TestClient

    from paperbot.livedash import app as LA
    w, now, f, b = _answer_world(tmp_path)
    monkeypatch.setenv("PAPERBOT_LIVE_PAPER_DB", w.cfg.db)
    monkeypatch.setattr(TC, "_bars", b)
    app = LA.create_app(None, b"x" * 32, liq_db=None, inbox_db=None)
    c = TestClient(app)
    r = c.get("/api/v4/livebots/trendchart?symbol=ETHUSDT")
    assert r.status_code == 200 and r.json()["state"] == "ok" and r.json()["symbol"] == "ETHUSDT"
    assert c.get("/api/v4/livebots/trendchart?symbol=XRPUSDT").status_code == 400


# ---------------------------------------------------------------- the view in node
FAKE_LWC = """const calls = {markers: null, lines: [], band: null, candles: null, ema: null, range: null, removed: 0};
globalThis.getComputedStyle = () => ({getPropertyValue: (n) => n});
globalThis.LightweightCharts = {createChart: () => ({
  addHistogramSeries: () => ({setData: (x) => { calls.band = x; }, applyOptions() {}}),
  addLineSeries: () => ({setData: (x) => { calls.ema = x; }, applyOptions() {}}),
  addCandlestickSeries: () => ({setData: (x) => { calls.candles = x; }, applyOptions() {}, setMarkers: (m) => { calls.markers = m; },
    createPriceLine: (o) => { calls.lines.push(o); return o; }, removePriceLine: () => { calls.removed += 1; }}),
  priceScale: () => ({applyOptions() {}}), timeScale: () => ({setVisibleLogicalRange: (r) => { calls.range = r; }}),
  subscribeCrosshairMove() {}, resize() {}, remove() {}, applyOptions() {}})};
"""


def _node(body: str, data, candles=None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    now = (data or {}).get("now_ms") or T.T0
    script = (f"Date.now = () => {int(now)};\nconst D = await import('{dom}');\n" + FAKE_LWC
              + f"const X = await import('file://{JS}');\nconst d = {json.dumps(data)};\nconst cs = {json.dumps(candles or [])};\n"
              "const tick = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0)); };\n" + body)
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


VIEW = """const every = [], asked = [];
const ctx = {params: {query: {}}, api: (p) => { asked.push(p); return Promise.resolve(p.startsWith('/api/candles') ? cs : d); },
  every(ms, fn) { every.push(ms); }, watch() {}, alive: () => true, href: (n, a) => '#/' + n, track() {}};
const v = X.tchartView(ctx, {get: () => null});
await tick();
const w = D.walk(v.el);
const find = (n, c) => { if (!n || !n.childNodes) return null; if (String(n.className || "").split(" ").includes(c)) return n;
  for (const k of n.childNodes) { const f = find(k, c); if (f) return f; } return null; };
const count = (n, c) => { let k = 0; const go = (x) => { if (!x || !x.childNodes) return; if (String(x.className || "").split(" ").includes(c)) k++; x.childNodes.forEach(go); }; go(n); return k; };
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, every, asked,
  hidden: !!(find(v.el, "ltc-cards") || {}).hidden, cells: count(v.el, "ltc-c"), dots: count(v.el, "ltc-dot"), xs: count(v.el, "ltc-x"),
  calls: {markers: calls.markers, lines: calls.lines, band: calls.band && calls.band.slice(-4), nband: calls.band && calls.band.length,
    ema: calls.ema && calls.ema.slice(-2), nema: calls.ema && calls.ema.filter((x) => x.value == null).length, ncandles: calls.candles && calls.candles.length,
    range: calls.range}}));"""

PURE = """const R = {adx_min: 20, adx_tired: 40};
const cell = (kind, o) => ({t: 0, dir: 1, raw: 1, up: 3, dn: 1, adx: 27.4, adx_prev: 25, votes: [1, 1, 1, -1], kind, ...o});
const H = 3600000, t0 = Date.UTC(2026, 9, 4, 15), tb = Date.UTC(2026, 9, 5, 0);   // 10/05 00:00 KST; a 4h boundary
console.log(JSON.stringify({
  info: ["up", "down", "hold up", "hold down", "hold", "up weak", "down tired", "na"].map((k) => X.cellInfo(cell(k), "1h", R)),
  info4: X.cellInfo(cell("down"), "4h", R).allow, none: X.cellInfo(null, "4h", R),
  ticks: X.hourTicks(t0, 13),
  placed: X.placeCells([{t: t0 - 2 * H}, {t: t0 + 2 * H}, {t: t0 + 6 * H}], t0, t0 + 12 * H, "4h", t0 + 7 * H)
    .map((p) => [p.gap ? "gap" : p.c.t === t0 - 2 * H ? "a" : p.c.t === t0 + 2 * H ? "b" : "c", p.col, p.span, !!p.now]),
  x: [X.markX(t0 + 6 * H, t0, t0 + 12 * H), X.markX(t0 - 1, t0, t0 + 12 * H)],
  band: [X.bandAt(new Map([[t0 + H, "h1"], [t0, "h0"]]), (t0 + 30 * 60000) / 1000, "30m"), X.bandAt(new Map([[t0 + H, "h1"], [t0, "h0"]]), t0 / 1000, "30m"),
    X.bandAt(new Map([[tb, "q"]]), (tb + 3 * H) / 1000, "1h"), X.bandAt(new Map([[tb + 4 * H, "q"]]), (tb + 3 * H) / 1000, "1h")],
  bars: ["up", "down weak", "hold up", "hold", "na"].map((k) => X.bandBar(cell(k))),
  ema: X.ema([1, 2, 3, 4, 5, 6], 3),
  marks: X.chartMarks({signals: [{t: t0 + 30 * 60000, tf: "30m", side: 1, kind: "entered"}, {t: t0 + H, tf: "30m", side: -1, kind: "blocked", cat: "trend"},
      {t: t0 + H, tf: "1h", side: 1, kind: "wait"}, {t: t0 - 99 * H, tf: "30m", side: 1, kind: "wait"}],
    trades: [{side: 1, entry_time: t0 + 32 * 60000, exit_time: t0 + 61 * 60000, reason: "JUDGE", roe: -0.2}],
    position: {side: -1, entry_time: t0 + 90 * 60000}}, "30m", new Set([0, 1, 2, 3].map((i) => (t0 + i * 30 * 60000) / 1000)))
    .map((m) => [(m.time * 1000 - t0) / 60000, m.shape, m.key, m.text, m.position]),
  exits: ["LOCK", "SL", "REV", "JUDGE", "TIME", "ZZZ"].map(X.exitKo),
  marksv: [X.voteMark(1), X.voteMark(-1), X.voteMark(0)],
}));"""


def _view_answer(tmp_path):
    w, now, f, b = _answer_world(tmp_path)
    TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)
    d = json.loads(json.dumps(TC.build({"paper": w.cfg.db}, "BTCUSDT", now["t"], b)))
    return d, synth_candles("BTCUSDT", "30m", 300, now["t"])


def test_the_view(tmp_path):
    d, cs = _view_answer(tmp_path)
    out = _node(VIEW, d, cs)
    t, cls = out["text"], out["classes"]
    for bad in ("null", "undefined", "NaN", "[object"):
        assert bad not in t, bad
    for words in ("추세 흐름 · 최근 72시간", "30분 진입 받는 곳 (1시간 판단)", "1시간 진입 받는 곳 (4시간 판단)",
                  "4시간 진입 받는 곳 (일봉 판단)", "BTC", "ETH", "BCH", "1시간", "4시간", "일봉", "지금", "BTC · 1시간 판단 지금",
                  "BTC · 4시간 판단 지금", "BTC · 일봉 판단 지금", "에 씀", "V3.9", "일목·AO", "4시간 진입은 일봉 줄",
                  "상승 (그 방향 진입 받음)", "보류 · 3/4는 나왔지만 유지 확인 중", "힘 약함 · 끝물 (진입 안 함)", "못 읽음", "페이퍼 롱 진입", "숏 진입", "감독 청산",
                  "차트", "BTC 30분봉 · 아래 띠 = 그 봉이 끝날 때 봇이 본 1시간 판단", "1시간 지금", "4시간 지금", "일봉 지금",
                  "끝날 때 본 1시간 판단",
                  "진입한 신호", "되돌림 기다림", "되돌림 대기 가격", "EMA20", "아래 띠: 높으면 진입 받는 추세",
                  "이 코인 최근 3일", "롱 신호", "진입", "롱 거래 청산", "감독(추세)", "진입 때 1시간 상승", "되돌림 확인: ",
                  "읽는 법", "칸 하나 = 끝난 봉 하나의 판단이 쓰인 시간", "봇은 끝난 봉 300개로 판단"):
        assert words in t, words
    assert re.search(r"봇 기록과 (같음 \d+/1[28]|다름 \d+줄)", t)
    assert out["hidden"] is False and out["every"] == [30000]
    assert "/api/v4/livebots/trendchart?symbol=BTCUSDT" in out["asked"] and "/api/candles?symbol=BTCUSDT&interval=30m&limit=300" in out["asked"]
    # 6 coins x (72 hourly cells + 19 four-hour cells + 4 daily cells); the BTC entry dot and its supervisor exit on the 1h row
    assert out["cells"] == 6 * (72 + 19 + 4) and out["dots"] == 1 and out["xs"] == 1
    assert any(c.startswith("ltc-coin sel") for c in cls) and any("ltc-c " in c and " now" in c for c in cls)
    assert any(c.startswith("ltc-c up") or c.startswith("ltc-c down") for c in cls)
    calls = out["calls"]
    assert calls["ncandles"] == 300 and calls["nband"] == 300 and calls["nema"] == 19
    assert calls["range"] == {"from": 150, "to": 310}
    assert all(b.get("color") in ("--up", "--down", "--up-line", "--down-line", "--line-2") for b in calls["band"] if "value" in b)
    marks = calls["markers"]
    keys = [(m["shape"], m["color"], m["text"]) for m in marks]
    assert ("circle", "--up", "") in keys and ("arrowUp", "--up", "진입 롱") in keys and ("square", "--down", "감독(추세)") in keys
    assert [m["time"] for m in marks] == sorted(m["time"] for m in marks) and calls["lines"] == []


def test_the_view_draws_a_wait_and_an_open_position(tmp_path):
    d, cs = _view_answer(tmp_path)
    d["chart"]["waits"] = [{"member": "F3_BOS@30m", "side": 1, "tf": "30m", "level": cs[-1]["close"] * 0.998, "until": d["now_ms"] + 20 * MIN,
                            "t0": d["now_ms"] - MIN, "judge": "1시간 상승(상승 3·하락 0·중립 1, ADX 25 오름)"}]
    d["chart"]["position"] = {"symbol": "BTCUSDT", "side": -1, "strategy": "F3_BOS", "tf": "30m", "htf": "1h", "entry_time": d["now_ms"] - 10 * MIN,
                              "entry_price": cs[-1]["close"], "stop": None, "locked": False, "entry_judge": "1시간 하락(…)"}
    out = _node(VIEW, d, cs)
    lines = out["calls"]["lines"]
    assert [(x["title"], x["lineStyle"], x["color"]) for x in lines] == [("되돌림 대기 롱 30분", 2, "--warn"), ("페이퍼 진입 숏", 0, "--muted")]
    assert ("arrowDown", "--down", "진입 숏") in [(m["shape"], m["color"], m["text"]) for m in out["calls"]["markers"]]
    for words in ("롱 되돌림 대기", "닿으면 진입", "지금 기다림", "숏 보유 중", "페이퍼 포지션"):
        assert words in out["text"], words


def test_the_view_off_missing_and_unread_rows():
    out = _node(VIEW, {"state": "off", "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)"})
    assert "꺼짐" in out["text"] and "추세판단 봇이 아니에요" in out["text"] and out["hidden"] is True
    out = _node(VIEW, {"state": "missing", "reason_ko": "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"})
    assert "수집 전" in out["text"] and "첫 판단" in out["text"] and out["hidden"] is True
    row = {"state": "error", "reason_ko": "바이낸스 봉을 못 받았어요 · 잠시 뒤 다시 받아요 (OSError: down)", "cells": []}
    d = {"state": "ok", "now_ms": T.T0 + HOUR, "ts": T.T0 + HOUR, "pending": False, "symbol": "BTCUSDT",
         "rules": {"from": "default", "adx_min": 20, "adx_tired": 40},
         "heat": {"t0": T.T0 - 70 * HOUR, "t1": T.T0 + 2 * HOUR, "hours": 72,
                  "coins": {s: {"1h": row, "4h": {"state": "pending", "reason_ko": "봉을 받는 중이에요", "cells": []}} for s in T.SYMS}},
         "marks": {"entries": [], "sup": []}, "chart": {"symbol": "BTCUSDT", "band": {}, "signals": [], "trades": [], "position": None, "waits": []}}
    out = _node(VIEW, d)
    t = out["text"]
    for words in ("못 읽음 · 바이낸스 봉을 못 받았어요", "불러오는 중", "없음 · 모두 쉼", "기본값", "기본 숫자로 계산했어요",
                  "BTC: 최근 3일 신호·거래가 없어요", "가격 봉이 없어요"):
        assert words in t, words
    assert out["cells"] == 0 and not re.search(r"봇 기록과 (같음 \d|다름 \d)", t)


def test_the_pure_helpers():
    out = _node(PURE, {"now_ms": T.T0})
    info = out["info"]
    assert [(x["cls"], x["word"], x["allow"]["ko"], x["allow"]["side"]) for x in info] == [
        ("up", "상승", "30분 롱만", 1), ("down", "하락", "30분 숏만", -1), ("hold up", "보류 (상승 유지 확인 중)", "30분 쉼 · 보류", 0),
        ("hold down", "보류 (하락 유지 확인 중)", "30분 쉼 · 보류", 0), ("hold", "보류", "30분 쉼 · 보류", 0),
        ("up weak", "상승 · 힘 약함", "30분 쉼 · 힘 약함", 0), ("down tired", "하락 · 끝물", "30분 쉼 · 끝물", 0),
        ("na", "못 읽음", "30분 쉼 · 판단 못 읽음", 0)]
    assert info[0]["sub"] == "상승 3·하락 1 · ADX 27 오름" and info[5]["sub"].endswith("ADX 20 미만") and info[6]["sub"].endswith("ADX 40 넘고 꺾임")
    assert out["info4"] == {"side": -1, "ko": "1시간 숏만"} and out["none"]["word"] == "못 읽음"
    assert out["ticks"] == [{"i": 0, "day": True, "ko": "10/05"}, {"i": 6, "day": False, "ko": "06시"}, {"i": 12, "day": False, "ko": "12시"}]
    # a 4h cell from before the window is cut at its start, a missing one leaves a gap, the one in force now says so
    assert out["placed"] == [["a", 0, 2, False], ["b", 2, 4, False], ["c", 6, 4, True], ["gap", 10, 2, False]]
    assert out["x"] == [0.5, None]
    # 30m bar 00:30-01:00 closes at 01:00 -> the 1h bar closed at 01:00; 00:00-00:30 -> the one closed at 00:00;
    # a 1h bar 03:00-04:00 -> the 4h bar closed at 04:00, never the older one
    assert out["band"] == ["h1", "h0", None, "q"]
    assert out["bars"] == [{"value": 1, "key": "up"}, {"value": 0.6, "key": "down-dim"}, {"value": 0.38, "key": "up-dim"},
                           {"value": 0.2, "key": "hold"}, None]
    assert out["ema"][:2] == [None, None] and out["ema"][2:] == pytest.approx(list(pd.Series([1, 2, 3, 4, 5, 6.0]).ewm(span=3, adjust=False).mean()[2:]))
    assert out["marks"] == [[0, "circle", "up", "", "belowBar"], [30, "circle", "muted", "×", "aboveBar"], [30, "arrowUp", "up", "진입 롱", "belowBar"],
                            [60, "square", "down", "감독(추세)", "aboveBar"],
                            [90, "arrowDown", "down", "진입 숏", "aboveBar"]]
    assert out["exits"] == ["계단 익절", "손절", "빠른 청산", "감독(추세)", "감독(시간)", "ZZZ"] and out["marksv"] == ["▲", "▼", "–"]


def test_static():
    node = shutil.which("node")
    if node is not None:
        r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
    css = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css)
    for m in re.findall(r"font(?:-size)?:\s*([^;]+);", css):
        sizes = [x for x in re.findall(r"(?<![\w-])(\d+(?:\.\d+)?(?:px|rem|em|%))", m)]
        assert not sizes or "var(--t-" in m, m                   # every font size a --t-* token
    assert not re.search(r"font-size:\s*\d", css)
    # the class prefix is this screen's own
    for f in os.listdir(SCREENS):
        if f.endswith(".css") and f != "livebots-tchart.css":
            assert ".ltc-" not in _read(os.path.join(SCREENS, f)), f
    sels = [x.strip() for m in re.findall(r"(?:^|[{}])\s*([^@{}][^{}]*)\{", css) for x in m.split(",")]
    sels = [x for x in sels if x and not x.startswith("@") and not re.match(r"^(\d+%|from|to)$", x)]
    assert sels and all(x.startswith(".ltc") for x in sels), [x for x in sels if not x.startswith(".ltc")]
    src = _read(JS)
    assert 'export const API = "/api/v4/livebots/trendchart";' in src and "export function tchartView" in src
    assert "innerHTML" not in src and not re.search(r"#[0-9a-fA-F]{6}\b", src)
