"""실거래 › 관제실 (#/deck, the live site's main screen since 2026-11-01; dash/more/livedeck.py + screens/livebots-deck.js /
livebots-deck.css; owners: "이런 화면느낌으로 메인화면으로 똑같이 만들어 줄수 있어?", "딱 대시보드 들어갔을때 메인화면이 이렇게
떴으면 좋겠네", "동그라미 이색깔로 전체적으로 이 색깔 느낌으로").

- the answer, on a world of the three mix bots' own files (the 레인지 봇 with a closed trade, an open SOL short and its board,
  the 바이비트 봇 with nothing yet, the 친구 15분 봇 not installed) and made-up Binance bars: each bot's balance, record,
  position, curve, the first row on the 10-31 night rules, the newest entry (진입 카드), the grid of board rows, the tape, the
  48-hour flow, the totals; each coin's closed 15m bars, the histogram and its 0 crosses (the bots' own formulas, part 9 of
  paperbot/friendtrend.py), the trend bar on the closed 30m bars; Binance down, a short history, a server without prices:
  each said, never guessed; one bot's broken files never hide the others; the coins read once a minute
- 목표 ×6 (owners 11-01: "내 1달 목표 수익률 달성을 위해 필요한 대시보드 화면 내용들"): each bot's month against the path to ×6
  with the 목표 연구 arithmetic (dash/more/livegoalres.py), the three together, the daily growth the rest needs; a bot without
  this month's trades or not installed said so; the arithmetic never breaks the answer
- the route in the live app, behind its login
- the pure functions in node (the grid cell, the lane, the % curve and the forward test's split, the entry card, the
  words of an entry's signal, the clock, the attractor's step) and the whole screen rendered in node on the real answer:
  no null / undefined / NaN
- static: colours and font sizes only through tokens (the palette in tokens.css), the screen's imports through pb.js,
  read-only (no POST, no fetch of its own, no HTML parsing), the decoration said on the screen, the start screen, the tab
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import numpy as np
import pytest

pytest.importorskip("fastapi")

from paperbot import friendtrend as FT  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livedeck as D  # noqa: E402
from tests.test_dash_mixrange_site import NOW, START, _ev, _trade, _write_range  # noqa: E402
from tests.test_mixbybit_checks import DAY0, H, MIN, _write  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-deck.js")
CSS = os.path.join(SCREENS, "livebots-deck.css")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")
MIN15, MIN30 = 15 * MIN, 30 * MIN
CE = NOW // MIN15 * MIN15                      # the last 15m close before NOW

POS = {"symbol": "SOLUSDT", "side": -1, "qty": 10.66, "entry": 104.6, "stop_dist": 1.4, "stop": 106.0, "best": 103.4, "step": 0,
       "opened_ms": NOW - 2 * H, "signal_close_ms": NOW - 2 * H - 5_000, "signal_close": 104.6, "last_bar_ms": NOW - MIN,
       "stop_id": "s1", "equity_before": 96.5, "leverage": 40, "roe_act": 10.0}
BOARD = {"SOLUSDT": {"close_ms": CE, "trend": -1, "trend_mode": "bar", "tf": "15분", "trend_tf": "30분", "bar_n": [1, 5, 0], "x0": -1,
                     "h6": -3.2, "rules": {"h0x": {"side": -1, "why": ""}}},
         "ETHUSDT": {"close_ms": CE, "trend": 0, "trend_mode": "bar", "tf": "15분", "trend_tf": "30분", "bar_n": [2, 2, 2], "x0": 1,
                     "h6": 1.15, "rules": {"h0x": {"side": 0, "why": "추세 바 종합 횡보(진입 금지)"}}}}


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _range_rows():
    live = [START] + _trade("SOLUSDT", -1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 96.5, qty=10.66)
    live.append({"ts": NOW - 20 * MIN + 4_000, "kind": "signal", **_ev("ETHUSDT", NOW - 20 * MIN, 1, 0,
                                                                       "추세 바 종합 횡보(진입 금지) (상승 2 · 하락 2 · 횡보 2)", trend=0)})
    live += _trade("SOLUSDT", -1, NOW - 2 * H, None, 104.6, 1.4, 96.5, 96.5, qty=10.66)[:2]     # the open short: signal, entry
    paper = [START] + _trade("SOLUSDT", -1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 97.0, qty=10.66)
    paper += _trade("SOLUSDT", -1, NOW - 2 * H + 60_000, None, 104.6, 1.4, 97.0, 97.0, qty=10.66)[:2]
    return live, paper


# this world's coins: the owners' six of 10-31 night (owners 11-03 moved the 관제실 to the two WOO X Pro bots' coins,
# BTC · SOL · XRP · BCH · ZEC · DOGE: tests/test_dash_rules1102.py)
WORLD_COINS = ("SOLUSDT", "ETHUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT")


@pytest.fixture(autouse=True)
def _world_coins(monkeypatch):
    monkeypatch.setattr(D, "COINS", WORLD_COINS)
    # (its coins and its 15m bars: owners 11-04 evening moved 관제실 to the running bot's coins and bars, deck_coins /
    # deck_tf: tests/test_rules1104d.py)
    monkeypatch.setattr(D, "deck_coins", lambda: D.COINS)
    monkeypatch.setattr(D, "deck_tf", lambda: "15m")
    # (and its histogram: the 3합 of the friend bot of then; owners 11-03 evening moved both bots to the OBV histogram's
    # turn, livedeck.hist_rule "o4h": test_the_histogram_follows_the_bots_entry_rule)
    monkeypatch.setattr(D, "hist_rule", lambda: "h3x")


@pytest.fixture
def world(tmp_path, monkeypatch):
    live, paper = _range_rows()
    env = _write_range(str(tmp_path / "r"), live, paper,
                       live_state={"position": dict(POS), "start_equity": 100.0, "last_close_ms": CE, "saved_ms": NOW - MIN,
                                   "mode": "mainnet", "board": BOARD})
    env.update(_write(str(tmp_path / "b"), [], []))
    for k in ("CONFIG", "PAPER_CONFIG", "STATE", "LOG", "PAPER_STATE", "PAPER_LOG"):    # the friend bot: not installed here
        env[f"PAPERBOT_MIX_{k}"] = str(tmp_path / "none" / k.lower())
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("PAPERBOT_MIX_BOT", raising=False)
    L._cache.clear()
    D._coin_cache.clear()
    yield {"live": live, "paper": paper, "tmp": tmp_path}
    L._cache.clear()
    D._coin_cache.clear()


def candles_of(calls=None, fail=False, m=1000):
    """Made-up Binance klines (dash/app.py rows: ``time`` in seconds) ending with the bar still open at NOW."""
    def f(sym, iv, n=300):
        if calls is not None:
            calls.append((sym, iv))
        if fail:
            raise RuntimeError("binance down")
        step = {"15m": 900, "30m": 1800}[iv]
        rng = np.random.default_rng(sum(map(ord, sym)) + step)
        base = {"SOLUSDT": 104.0, "ETHUSDT": 2400.0, "XRPUSDT": 1.3, "BCHUSDT": 420.0, "ZECUSDT": 1235.0, "DOGEUSDT": 0.08}[sym]
        c = base * np.exp(np.cumsum(rng.normal(0, 0.003, m)))
        end = (NOW // 1000) // step * step
        t0 = end - (m - 1) * step
        return [{"time": t0 + i * step, "open": float(c[i - 1] if i else c[0]), "high": float(max(c[i], c[i - 1] if i else c[0]) * 1.002),
                 "low": float(min(c[i], c[i - 1] if i else c[0]) * 0.998), "close": float(c[i]), "volume": 100.0 + 10 * (i % 7)}
                for i in range(m)]
    return f


# ---------------------------------------------------------------- the answer
def test_the_three_bots_from_their_own_files(world):
    d = json_finite(D.build(candles_of(), NOW))
    json.dumps(d, allow_nan=False)
    assert d["now_ms"] == NOW and d["mmr"] == pytest.approx(0.005)
    assert [b["id"] for b in d["bots"]] == ["bybit", "mix", "range"]
    by, mix, rg = d["bots"]
    assert (by["name_ko"], mix["name_ko"], rg["name_ko"]) == ("바이비트 봇", "친구 15분 봇", "레인지 봇")
    assert mix["status"]["state"] == "off" and "equity" not in mix and "curve" not in mix      # not installed: nothing made up
    assert not any(k.startswith("_") for b in d["bots"] for k in b)
    # the 레인지 봇: its balance line from the start, the closed loss, the open short
    assert rg["curve"][0] == [DAY0 - H, 100.0] and rg["curve"][-1] == [DAY0 + 3 * H, 96.5]
    assert rg["record"]["n"] == 1 and rg["record"]["wins"] == 0 and rg["record"]["pnl"] == pytest.approx(-3.5)
    assert rg["position"]["state"] == "ok" and rg["position"]["symbol"] == "SOLUSDT" and rg["position"]["side"] == -1
    assert rg["position"]["entry"] == pytest.approx(104.6) and rg["position"]["stop"] == pytest.approx(106.0)
    # the first row it wrote on the 10-31 night rules (a 30m trend bar): the closed trade's signal
    first = next(r for r in world["live"] if r.get("trend_tf") or (isinstance(r.get("why"), dict) and r["why"].get("trend_tf")))
    assert rg["rules_since_ms"] == first["ts"] == DAY0 + 2 * H - 4_000
    # 진입 카드: its newest entry, with the signal it entered on
    le = rg["last_entry"]
    assert le["symbol"] == "SOLUSDT" and le["side"] == -1 and le["entry"] == pytest.approx(104.6) and le["leverage"] == 40
    assert le["ts"] == NOW - 2 * H and le["why"]["rule"] == "h0x" and le["why"]["trend_tf"] == "30분" and le["why"]["x0"] == -1
    # the config's ladder and stop (the deploy file's), the paper twin, the two entering together
    cfg = json.load(open(os.path.join(ROOT, "deploy", "mixrange.live.json"), encoding="utf-8"))
    assert rg["ladder"] and rg["stop_atr"] == pytest.approx(float(cfg.get("stop_atr", rg["stop_atr"])))
    assert rg["paper"]["record"]["n"] == 1 and rg["pcurve"][-1] == [DAY0 + 3 * H, 97.0]
    assert rg["parity"] == {"n": 2, "same": 2, "share": 1.0}
    # the 바이비트 봇: running files, nothing traded yet
    assert by["record"]["n"] == 0 and by["curve"] == [] and by["last_entry"] is None and by["position"] is None


def test_the_grid_the_tape_the_flow_and_the_totals(world):
    d = D.build(candles_of(), NOW)
    assert [g["symbol"] for g in d["grid"]] == list(D.COINS)
    sol = d["grid"][0]["bots"]
    assert set(sol) == {"range"} and sol["range"]["trend"] == -1 and sol["range"]["side"] == -1 and sol["range"]["rule"] == "h0x"
    assert sol["range"]["h6"] == pytest.approx(-3.2) and sol["range"]["close_ms"] == CE
    eth = d["grid"][1]["bots"]["range"]
    assert eth["side"] == 0 and eth["x0"] == 1 and eth["why"] == "추세 바 종합 횡보(진입 금지)"
    assert all(g["bots"] == {} for g in d["grid"][2:])
    # the tape: newest first, every row in the owners' words, a plain signal row without a side or a cross left out
    tape = d["tape"]
    assert [r["ts"] for r in tape] == sorted((r["ts"] for r in tape), reverse=True)
    assert all(r["kind"] in D.TAPE_KINDS and r["kind_ko"] == D.TAPE_KINDS[r["kind"]] for r in tape)
    assert not any("None" in r["text"] for r in tape)
    kinds = [r["kind"] for r in tape]
    assert kinds.count("entry") == 2 and kinds.count("exit") == 1 and kinds.count("start") == 1
    ex = next(r for r in tape if r["kind"] == "exit")
    assert ex["pnl"] == pytest.approx(-3.5) and ex["coin"]
    assert next(r for r in tape if r["kind"] == "entry")["text"] == "숏 진입 104.6 · 손절 106"
    sig = next(r for r in tape if r["kind"] == "signal" and r["symbol"] == "ETHUSDT")
    assert sig["text"].startswith("히스토그램 0선 위로 돌파 · 추세 바 종합 횡보")
    # the flow: 48 hours of 15m slots up to now, the crosses and the entries the bots logged in it
    fl = d["flow"]
    assert len(fl) == 192 and fl[-1][0] == CE and all(b[0] - a[0] == MIN15 for a, b in zip(fl, fl[1:]))
    assert sum(x[2] for x in fl) == 2 and sum(x[1] for x in fl) >= 2
    slot = {x[0]: x for x in fl}
    assert slot[(NOW - 2 * H) // MIN15 * MIN15][2] == 1
    t = d["totals"]
    assert t["open"] == 1 and t["n"] == 1 and t["wins"] == 0 and t["win_rate"] == 0.0


def test_each_coin_from_closed_binance_bars_and_the_bots_formulas(world):
    calls = []
    d = D.build(candles_of(calls), NOW)
    assert [c["symbol"] for c in d["coins"]] == list(D.COINS) and all(c["state"] == "ok" for c in d["coins"])
    assert sorted(set(iv for _s, iv in calls)) == ["15m", "30m"]
    f = candles_of()
    for c in d["coins"]:
        assert len(c["bars"]) == D.CHART_N and len(c["hist"]) == D.CHART_N and len(c["cross"]) == D.CHART_N
        assert len(c["spark"]) == D.SPARK_N and len(c["trend30"]) == D.TREND_N
        assert all(b[0] + MIN15 <= NOW for b in c["bars"]) and c["bars"][-1][0] + 2 * MIN15 > NOW      # the open bar left out
        assert all(t + MIN30 <= NOW for t, _v in c["trend30"]) and c["trend30"][-1][0] + 2 * MIN30 > NOW
        assert all(b[0] - a[0] == MIN30 for a, b in zip(c["trend30"], c["trend30"][1:]))
        assert set(c["cross"]) <= {-1, 0, 1} and {v for _t, v in c["trend30"]} <= {-1, 0, 1}
        assert len(c["o4side"]) == D.CHART_N and set(c["o4side"]) <= {-1, 0, 1} and set(c["tm30"]) == {"hist", "macd", "yellow"}
        # the same numbers as the bots' own formulas on the same closed bars (owners 11-02: the 3합 histogram, the
        # OBV4 MACD histogram's entries, the 30m 추세 MACD)
        r15 = [r for r in f(c["symbol"], "15m", D.HIST_BARS) if r["time"] * 1000 + MIN15 <= NOW]
        r30 = [r for r in f(c["symbol"], "30m", D.HIST_BARS) if r["time"] * 1000 + MIN30 <= NOW]
        a15 = [np.array([r[k] for r in r15]) for k in ("open", "high", "low", "close", "volume")]
        h = FT.h3_pane(*a15)
        assert c["hist"][-1] == pytest.approx(round(float(h["hist"][-1]), 3)) and c["cross"][-1] == int(h["cross"][-1])
        assert c["o4side"] == [int(x) for x in FT.o4_pane(*a15[1:])["side"][-D.CHART_N:]]
        tm = FT.tmacd_pane(*(np.array([r[k] for r in r30]) for k in ("high", "low", "close", "volume")))
        assert c["trend30"][-1][1] == int(tm["trend"][-1]) and c["tm30"]["hist"] == pytest.approx(round(float(tm["hist"][-1]), 3))
        assert c["last"] == pytest.approx(r15[-1]["close"]) and c["chg24"] == pytest.approx(r15[-1]["close"] / r15[-97]["close"] - 1)
    assert all(c["hist_rule"] == "h3x" for c in d["coins"])
    # read once a minute for every viewer
    n = len(calls)
    D.build(candles_of(calls), NOW)
    assert len(calls) > n                                    # (a new function: a new key)
    g = candles_of(calls)
    D.build(g, NOW)
    k = len(calls)
    D.build(g, NOW + 20_000)
    assert len(calls) == k


def test_coins_say_what_could_not_be_read(world):
    down = D.build(candles_of(fail=True), NOW)["coins"]
    assert all(c["state"] == "error" and c["ko"] == "바이낸스 봉을 못 읽었어요" and "binance down" in c["reason"] for c in down)
    D._coin_cache.clear()
    short = D.build(candles_of(m=200), NOW)["coins"]
    assert all(c["state"] == "short" and c["ko"] == "지난 봉이 모자라요" and "bars" not in c for c in short)
    none = D.build(None, NOW)["coins"]
    assert all(c["state"] == "error" and c["ko"] == "가격 읽기가 없는 서버예요" for c in none)
    # the bots are still there either way
    assert [b["id"] for b in D.build(None, NOW)["bots"]] == ["bybit", "mix", "range"]


def test_one_bots_broken_files_never_hide_the_others(world, monkeypatch):
    real = D.bot_view

    def broken(prof, now):
        if prof.id == "bybit":
            raise ValueError("bad file")
        return real(prof, now)
    monkeypatch.setattr(D, "bot_view", broken)
    d = json_finite(D.build(None, NOW))
    by = d["bots"][0]
    assert by["status"] == {"state": "error", "ko": "기록을 읽지 못했어요"} and "bad file" in by["reason"]
    assert d["bots"][2]["record"]["n"] == 1 and d["totals"]["open"] == 1


def test_the_goal_against_the_path_to_x6(world, monkeypatch):
    from paperbot.dash.more import livegoalres as G
    g = D.build(None, NOW)["goal"]
    assert g["target"] == 6.0 and g["month_days"] == 30 and g["goal_ko"] == G.GOAL_KO and g["from_ms"] == G.month_from(NOW)[0]
    by, mix, rg = g["bots"]
    assert (by["id"], mix["id"], rg["id"]) == ("bybit", "mix", "range")
    assert (by["name_ko"], mix["name_ko"], rg["name_ko"]) == ("바이비트 봇", "친구 15분 봇", "레인지 봇")    # the configs' names
    assert by["state"] == "missing" and by["reason_ko"] and mix["state"] == "off" and mix["reason_ko"]
    # the 레인지 봇: from its first trade this month (the wallet before it: 100) to its balance now (96.5)
    m = rg["month"]
    assert rg["state"] == "ok" and m["from_ms"] == DAY0 + 2 * H and m["start_equity"] == 100.0 and m["now_equity"] == pytest.approx(96.5)
    days = (NOW - (DAY0 + 2 * H)) / (24 * H)
    assert m["days"] == pytest.approx(days) and m["mult"] == pytest.approx(0.965)
    assert m["path_now"] == pytest.approx(6 ** (days / 30)) and m["vs_path"] == pytest.approx(0.965 / 6 ** (days / 30) - 1)
    assert rg["need_daily"] == pytest.approx((6 / 0.965) ** (1 / (30 - days)) - 1)
    assert rg["n"] == 1 and rg["tone"] == "thin" and "아직 판단하지 않아요" in rg["verdict_ko"]
    # the same numbers as the bot's own 목표 연구
    acc = next(a for a in G.mix_bot(None, NOW, "range")["accounts"] if a["id"] == "live")
    assert acc["month"] == m and acc["verdict_ko"] == rg["verdict_ko"]
    # the three together: only the bots with this month's numbers
    a = g["all"]
    assert a["start_equity"] == 100.0 and a["now_equity"] == pytest.approx(96.5) and a["need_daily"] == pytest.approx(rg["need_daily"])
    # the arithmetic of one bot breaking never hides the others, nor the answer
    real = G.mix_bot

    def broken(p, now, bot="mix"):
        if bot == "bybit":
            raise ValueError("bad")
        return real(p, now, bot)
    monkeypatch.setattr(G, "mix_bot", broken)
    g2 = D.build(None, NOW)["goal"]
    assert g2["bots"][0]["state"] == "error" and "bad" in g2["bots"][0]["reason"] and g2["bots"][2]["state"] == "ok"
    monkeypatch.setattr(D, "goal_view", lambda *a, **k: 1 / 0)
    d = D.build(None, NOW)
    assert d["goal"]["state"] == "error" and d["goal"]["ko"] == "목표 숫자를 만들지 못했어요" and len(d["bots"]) == 3


def test_the_route_in_the_live_app_behind_its_login(world, tmp_path):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    from tests.test_livedash_app import PW, _app
    assert "livedeck" in LA.MODULES
    c = TestClient(_app(tmp_path))
    assert c.get(D.ROUTE).status_code in (401, 403)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get(D.ROUTE)
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"now_ms", "bots", "coins", "grid", "tape", "flow", "totals", "mmr"} and len(d["coins"]) == 6
    assert [b["id"] for b in d["bots"]] == ["bybit", "mix", "range"]


def test_the_month_view_calendar_and_its_risk():
    """Owners 11-01 "다 해줘": this month's days (KST) with the three bots' closed trades (P&L over the day's starting
    balance), the days over the daily rate ×6 needs, the losing run, the worst trade, the deepest fall of a balance."""
    from paperbot.dash.more import livegoalres as G
    from paperbot.dash.more import livebots as LB
    now = 1793458800000 + 3 * LB.DAY + 5 * 3600 * 1000            # (the 4th of a KST month, 05:00)
    m0, n = G.month_from(now)
    H = 3600 * 1000
    b1 = {"name_ko": "레인지 봇", "curve": [[m0 - LB.DAY, 100.0], [m0 + H, 108.0], [m0 + LB.DAY + H, 103.0], [m0 + LB.DAY + 2 * H, 99.0],
                                            [m0 + 2 * LB.DAY + 2 * H, 103.0]],
          "_trades": [{"exit_ms": m0 + 2 * LB.DAY + 2 * H, "pnl": 4.0, "coin": "SOL", "side": -1},
                      {"exit_ms": m0 + LB.DAY + 2 * H, "pnl": -4.0, "coin": "SOL", "side": -1},
                      {"exit_ms": m0 + LB.DAY + H, "pnl": -5.0, "coin": "ETH", "side": 1},
                      {"exit_ms": m0 + H, "pnl": 8.0, "coin": "ETH", "side": 1},
                      {"exit_ms": m0 - H, "pnl": -50.0, "coin": "XRP", "side": 1},          # (last month: not counted)
                      {"exit_ms": m0 + 3 * LB.DAY + H, "pnl": None, "coin": "BCH", "side": 1}]}  # (모름: counts in n only)
    b2 = {"name_ko": "꺼진 봇"}
    v = D.month_view([b1, b2], now, 6.0)
    assert (v["from_ms"], v["days_n"], v["target"]) == (m0, n, 6.0) and v["need"] == pytest.approx(6 ** (1 / 30) - 1)
    d = {x["d"]: x for x in v["days"]}
    assert d[1]["state"] == "past" and (d[1]["n"], d[1]["pnl"], d[1]["base"]) == (1, 8.0, 100.0) and d[1]["pct"] == pytest.approx(0.08)
    assert (d[2]["n"], d[2]["wins"], d[2]["pnl"], d[2]["base"]) == (2, 0, -9.0, 108.0)
    assert (d[3]["pnl"], d[3]["base"]) == (4.0, 99.0)
    assert d[4]["state"] == "today" and (d[4]["n"], d[4]["pnl"]) == (1, 0.0)
    assert d[5] == {"d": 5, "ms": m0 + 4 * LB.DAY, "state": "future"} and len(v["days"]) == n
    assert (v["over"], v["green"], v["red"]) == (1, 2, 1)                            # (8% is over the 6.2% a day)
    assert v["best"]["d"] == 1 and v["worst"] == {"d": 2, "pct": pytest.approx(-9 / 108), "pnl": -9.0}
    assert (v["loss_run"], v["max_loss_run"], v["trades_n"]) == (0, 2, 4)            # (−5, −4 in a row, then +4)
    assert v["worst_trade"]["pnl"] == -5.0 and v["worst_trade"]["bot_ko"] == "레인지 봇"
    assert v["dd"]["bot_ko"] == "레인지 봇" and v["dd"]["pct"] == pytest.approx(99 / 108 - 1)
    # nothing yet: every past day flat, no best / worst, no fall
    e = D.month_view([{"name_ko": "x"}], now, 6.0)
    assert e["over"] == e["green"] == e["red"] == 0 and "best" not in e and e["dd"] is None and e["trades_n"] == 0


def test_the_price_now_shared_every_5_seconds(monkeypatch):
    """GET /api/v4/livebots/deck/px: Binance's mark, last and funding for the six coins, one fetch per PX_TTL_S shared by
    every viewer; a coin that did not answer is left out (never a zero); nothing came = state error with the words."""
    calls = []

    def fake(symbols):
        calls.append(tuple(symbols))
        return {"SOLUSDT": {"last": 150.5, "mark": 150.6, "funding": 0.0001, "next_ms": 1}, "ETHUSDT": {"last": float("nan")},
                "XRPUSDT": {"mark": 0.61}, "BTCUSDT": {"last": 1.0}}
    D._PX_CACHE.clear()
    v = D.px_view(fake, now_ms=7)
    assert calls == [D.COINS] and v["state"] == "ok" and v["now_ms"] == 7
    assert v["coins"] == {"SOLUSDT": {"last": 150.5, "mark": 150.6, "funding": 0.0001, "next_ms": 1}, "XRPUSDT": {"mark": 0.61}}
    assert v["missing"] == ["ETHUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT"]
    assert D.px_view(fake) is v and len(calls) == 1                                  # (cached for every viewer)
    D._PX_CACHE.clear()

    def down(_s):
        raise OSError("no network")
    w = D.px_view(down, now_ms=8)
    assert w["state"] == "error" and w["coins"] == {} and "15분봉" in w["ko"] and "OSError" in w["reason"]
    D._PX_CACHE.clear()


# ---------------------------------------------------------------- the screen in node
def _node(body: str, data=None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = (f"const T = await import('file://{DOM}');\n"
              f"const M = await import('file://{JS}');\n"
              f"const A = JSON.parse({json.dumps(json.dumps(data or {}))});\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_pure_functions():
    out = _node("""console.log(JSON.stringify({
      tone: [M.toneOf(1), M.toneOf(-1), M.toneOf(0), M.toneOf(null), M.toneOf("x")],
      pct: [M.pctKo(0.0123), M.pctKo(-0.004), M.pctKo(null), M.pctKo(-0.035, 1)],
      px: [M.pxKo(104.6), M.pxKo(100), M.pxKo(2405.1), M.pxKo(0.080156), M.pxKo(81867.5), M.pxKo(null), M.pxKo("x")],
      nc: M.nextClose(Date.UTC(2026, 10, 1, 3, 7, 30)), at: Date.UTC(2026, 10, 1, 3, 15),
      mm: [M.mmss(0), M.mmss(65000), M.mmss(-5), M.mmss(899999)],
      cell: [M.cellOf(null), M.cellOf({rule: "h0x", trend: -1, h6: -3.2, x0: -1, side: -1}),
             M.cellOf({rule: "obvac", trend: 1, ac: 0.38, turn: 1, side: 0}), M.cellOf({rule: "h0x", trend: 0, h6: 1.15, x0: 1, side: 0})],
      lane: M.laneOf({state: "ok", side: -1, entry: 104.6, stop: 106, next: {trigger: 104.251}, leverage: 40}, 103.925),
      lane0: [M.laneOf(null, 1), M.laneOf({state: "none"}, 1), M.laneOf({state: "ok", entry: 1}, 1)],
      pc: [M.pctCurve([[1, 100], [2, 96.5], [3, "x"]]), M.pctCurve([[1, 0], [2, 5]]), M.pctCurve(null)],
      since: [M.since([[1, 100], [2, 110], [3, 99], [4, 104.5]], 2), M.since([[1, 100], [2, 110]], 9), M.since([], 1),
              M.since([[1, 100], [2, 90], [3, 99]], null)],
      why: [M.whyKo({rule: "h0x", tf: "15분", trend_tf: "30분", trend: -1, x0: -1, h6: -4.21}),
            M.whyKo({rule: "obvac", tf: "15분", trend_tf: "30분", trend: 1, turn: 1, ac: 0.12, ac_col: 1}), M.whyKo(null)],
      card: M.cardOf([{name_ko: "바이비트 봇", position: null, last_entry: null},
        {name_ko: "레인지 봇", stop_atr: 3, ladder: {trigger: 10, lock: 8, step: 5},
         position: {state: "ok", symbol: "SOLUSDT", coin: "SOL", side: -1, entry: 104.6, stop: 106, leverage: 40, opened_ms: 5, first_act_price: 104.251, step: 0},
         last_entry: {symbol: "SOLUSDT", why: {rule: "h0x", tf: "15분", trend_tf: "30분", trend: -1, x0: -1, h6: -4.21, bar_n: [1, 5, 0]}}}], 0.005),
      past: M.cardOf([{name_ko: "바이비트 봇", ladder: {trigger: 10, lock: 8, step: 5}, stop_atr: 3,
        last_entry: {ts: 9, symbol: "ETHUSDT", coin: "ETH", side: 1, entry: 100, stop: 98, leverage: 40, why: {bar_n: [4, 1, 1]}}},
        {name_ko: "레인지 봇", last_entry: {ts: 3, symbol: "SOLUSDT", side: -1, entry: 50, stop: 51, leverage: 20, why: {}}}], 0.005),
      none: M.cardOf([{name_ko: "x"}]),
      az: M.aizawa([0.1, 0, 0]),
      far: (() => { let p = [0.1, 0, 0]; let lo = [9, 9, 9], hi = [-9, -9, -9];
        for (let i = 0; i < 20000; i++) { p = M.aizawa(p); for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p[k]); hi[k] = Math.max(hi[k], p[k]); } }
        return {lo, hi}; })(),
      api: M.DECK_API,
      path: [M.pathAt(6, 0), M.pathAt(6, 15), M.pathAt(6, 30), M.pathAt(6, -3), M.pathAt(null, 3), M.pathAt(6, null)],
      mult: [M.multKo(1.0798), M.multKo(6), M.multKo(5000), M.multKo(0.001), M.multKo(null)],
      rate: [M.rateKo(0.554), M.rateKo(1), M.rateKo(null)],
      line: M.monthLine([[1000, 100], [86400000 * 2, 104.2], [86400000 * 3, "x"]], {from_ms: 86400000, start_equity: 96.5, now_equity: 110}, 86400000 * 4),
      line0: [M.monthLine([[1, 2]], null, 5), M.monthLine([], {from_ms: 1, start_equity: 0}, 5)],
    }));""")
    assert out["tone"] == ["up", "down", "flat", "na", "na"]
    assert out["pct"] == ["+1.23%", "−0.40%", "—", "−3.5%"]
    assert out["px"] == ["104.6", "100", "2405.1", "0.080156", "81867.5", "—", "—"]
    assert out["nc"] == {"at": out["at"], "left_ms": 450_000} and out["mm"] == ["00:00", "01:05", "00:00", "15:00"]
    c0, c1, c2, c3 = out["cell"]
    assert c0 == {"tone": "na", "big": "—", "sub": "기록 없음", "sig": 0}
    assert c1 == {"tone": "down", "big": "−3.2", "sub": "숏 신호", "sig": -1}
    assert c2 == {"tone": "up", "big": "AC 0.38", "sub": "OBV 진한 초록 · 상승", "sig": 0}
    assert c3 == {"tone": "flat", "big": "1.2", "sub": "0선 ↑ · 진입 금지", "sig": 0}
    # a short's lane reads right to left: the stop on the left, the price now beyond the next lock
    ln = out["lane"]
    assert ln["stop"] == pytest.approx(0) and ln["now"] == pytest.approx(1)
    assert ln["entry"] == pytest.approx(1 - 0.675 / 2.075) and ln["next"] == pytest.approx(1 - 0.326 / 2.075)
    assert ln["nextPx"] == pytest.approx(104.251) and ln["roe"] == pytest.approx(0.675 / 104.6 * 40)
    assert out["lane0"] == [None, None, None]
    assert out["pc"][0] == [[1, 0], [2, pytest.approx(-0.035)]] and out["pc"][1] == [] and out["pc"][2] == []
    s1, s2, s3, s4 = out["since"]
    assert s1["ret"] == pytest.approx(0.045) and s1["dd"] == pytest.approx(0.99 / 1.1 - 1)
    assert s2 is None and s3 is None and s4["ret"] == pytest.approx(-0.01) and s4["dd"] == pytest.approx(-0.1)
    assert out["why"] == ["15분봉 히스토그램 0선 아래로 돌파 (−4.21) · 추세 바 30분 종합 하락",
                          "15분봉 OBV 연한→진한 초록 · AC 플러스 양봉 (0.12) · 추세 바 30분 종합 상승", ""]
    cd = out["card"]                                         # the open position first
    assert cd["live"] is True and cd["bot"] == "레인지 봇" and (cd["sideKo"], cd["sideEn"], cd["lev"]) == ("숏", "SHORT", 40)
    assert cd["agree"] == 5 and cd["dist"] == pytest.approx(1.4 / 104.6) and cd["rr"] == pytest.approx(0.349 / 1.4)
    assert cd["liq"] == pytest.approx(104.6 * (1 + 1 / 40 - 0.005)) and cd["stopAtr"] == 3
    assert cd["target"] == "순ROE +10%에 닿으면 손절을 +8%로 옮기고, 그 뒤 5%마다 한 계단씩 올려요"
    pa = out["past"]                                         # else the newest entry of any bot, said to be past
    assert pa["live"] is False and pa["bot"] == "바이비트 봇" and pa["coin"] == "ETH" and pa["agree"] == 4
    assert pa["act"] == pytest.approx(100 * (1 + 0.1 / 40)) and pa["liq"] == pytest.approx(100 * (1 - (1 / 40 - 0.005)))
    assert out["none"] is None
    # the attractor (decoration): one Euler step of the Aizawa system, bounded over a long run
    x, y, z = 0.1, 0.0, 0.0
    a, b, c, dd, e, f = 0.95, 0.7, 0.6, 3.5, 0.25, 0.1
    dx, dy = (z - b) * x - dd * y, dd * x + (z - b) * y
    dz = c + a * z - z ** 3 / 3 - (x * x + y * y) * (1 + e * z) + f * z * x ** 3
    assert out["az"] == [pytest.approx(x + dx * 0.011), pytest.approx(y + dy * 0.011), pytest.approx(z + dz * 0.011)]
    assert all(-2 < v < 2.5 for v in out["far"]["lo"] + out["far"]["hi"])
    assert out["api"] == D.ROUTE
    # 목표 ×6: the path to ×6 over 30 days, the multiples in words, a bot's month in multiples of its month-start balance
    assert out["path"][0] == 1 and out["path"][1] == pytest.approx(6 ** 0.5) and out["path"][2] == pytest.approx(6)
    assert out["path"][3] == 1 and out["path"][4] is None and out["path"][5] is None
    assert out["mult"] == ["×1.08", "×6.00", "×1000 넘게", "×0.01 아래", "—"] and out["rate"] == ["55%", "100%", "—"]
    assert out["line"] == [[0, 1], [1, pytest.approx(104.2 / 96.5)], [3, pytest.approx(110 / 96.5)]]
    assert out["line0"] == [[], []]


def test_the_price_now_the_risk_and_the_alerts():
    """The price now (live while fresh, else the 15m close), one position's risk at it, the risk bar, the sounds of new
    records (core/sound.js playLive's names)."""
    out = _node("""
    const coin = {symbol: "SOLUSDT", state: "ok", last: 100};
    const live = {state: "ok", coins: {SOLUSDT: {last: 101, mark: 101.2, funding: 0.0001, next_ms: 9}}};
    const pos = {state: "ok", side: -1, entry: 104.6, stop: 106, leverage: 40, qty: 10, stop_pnl: -14, equity_before: 100};
    console.log(JSON.stringify({
      p1: M.priceNow(live, 1000, coin, 5000), p2: M.priceNow(live, 1000, coin, 1000 + 31000), p3: M.priceNow(null, null, coin, 0),
      p4: M.priceNow({coins: {SOLUSDT: {last: 99}}}, 1, coin, 2), p5: M.priceNow(null, null, {state: "error"}, 0), arr: M.priceNow({coins: []}, 1, coin, 2),
      r: M.riskOf(pos, 103.6, 98, 0.005, 0.0001), rl: M.riskOf({...pos, side: 1, entry: 100, stop: 98, stop_pnl: null}, 101, null, 0.005, -0.0002),
      r0: M.riskOf(null, 100), r1: M.riskOf(pos, null), bar: M.riskBar(pos, M.riskOf(pos, 103.6, 98)),
      usd: [M.usdKo(1.5), M.usdKo(-2), M.usdKo(0), M.usdKo(null)],
      snd: M.liveSoundsOf([{kind: "entry"}, {kind: "exit", pnl: 2}, {kind: "exit", pnl: -1}, {kind: "exit", pnl: null}, {kind: "signal"}, {kind: "adopted"}]),
      snd0: M.liveSoundsOf(null), api: M.PX_API}));""")
    assert out["p1"] == {"px": 101.2, "src": "live", "funding": 0.0001, "next_ms": 9}       # (the mark first)
    assert out["p2"] == {"px": 100, "src": "15m", "funding": None, "next_ms": None}        # (30 s old: not now any more)
    assert out["p3"] == out["p2"] and out["p4"]["px"] == 99 and out["p5"] is None and out["arr"]["src"] == "15m"
    r = out["r"]                                           # a short from 104.6, 10 coins, 40x, price now 103.6
    assert r["pnl"] == pytest.approx(10.0) and r["roe"] == pytest.approx((1 - 103.6 / 104.6) * 40)
    assert r["liq"] == pytest.approx(104.6 * (1 + (1 / 40 - 0.005))) and r["toLiq"] == pytest.approx(-(103.6 - r["liq"]) / 103.6)
    assert r["toStop"] == pytest.approx((106 - 103.6) / 103.6) and r["stopPnl"] == -14 and r["stopPct"] == pytest.approx(-14 / 98)
    assert r["funding"] == {"rate": 0.0001, "pays": False, "usd": pytest.approx(0.0001 * 10 * 103.6)}   # (a short is paid)
    rl = out["rl"]       # a long without stop_pnl: the stop's P&L from its qty and prices; funding < 0 = the long is paid
    assert rl["stopPnl"] == pytest.approx(-20) and rl["stopPct"] == pytest.approx(-0.2)     # (of equity_before: no balance given)
    assert rl["funding"]["pays"] is False and rl["liq"] < 100 and rl["toStop"] == pytest.approx((101 - 98) / 101)
    assert out["r0"] is None and out["r1"] is None
    b = out["bar"]
    assert b["liq"] == 0 and b["entry"] == pytest.approx(0.5) and 0 < b["stop"] < b["entry"] < b["now"] <= 1
    assert out["usd"] == ["+$1.50", "−$2.00", "+$0.00", "—"]
    assert out["snd"] == ["lv_entry", "lv_tp", "lv_sl"] and out["snd0"] == [] and out["api"] == D.PX_ROUTE


def test_the_goal_ladder_the_feed_and_the_wire():
    """Owners 11-01: "100달러로 한달만에 700달러, 800달러 … 5000달러 그이상" (what each goal needs a day, arithmetic only) and
    their picture again (the coins' feed lines, the raw record log)."""
    out = _node("""console.log(JSON.stringify({
      lad: M.ladderOf(), lad7: M.ladderOf([7, 0, -1, null, "x"], 30, 100), goals: M.GOAL_LADDER,
      feed: M.feedLines([{state: "ok", coin: "SOL", spark: [100, 101, 99.5]}, {state: "error", coin: "ETH"},
        {state: "ok", coin: "XRP", spark: [2]}, {state: "ok", coin: "BCH", spark: [0, 5]}, {state: "ok", coin: "ZEC", spark: [50, null, 55]}]),
      wire: M.wireOf([{ts: Date.UTC(2026, 10, 1, 2, 50), bot_ko: "레인지 봇", coin: "SOL", kind: "exit", side: -1, pnl: 7.700000000000003,
        text: "손절"}, {ts: null, bot_ko: "바이비트 봇", kind: "signal", text: "롱 신호"}], 7),
      wire0: M.wireOf(null)}));""")
    assert out["goals"] == [6, 7, 10, 20, 50]
    assert [r["x"] for r in out["lad"]] == [6, 7, 10, 20, 50] and [r["usd"] for r in out["lad"]] == [600, 700, 1000, 2000, 5000]
    for r in out["lad"]:
        assert (1 + r["daily"]) ** 30 == pytest.approx(r["x"])
    assert [round(r["daily"] * 100, 1) for r in out["lad"]] == [6.2, 6.7, 8.0, 10.5, 13.9]
    assert out["lad7"] == [{"x": 7, "usd": 700, "daily": pytest.approx(7 ** (1 / 30) - 1)}]   # (a bad goal is left out)
    # each coin keeps its place (its colour) in the order; one that is not read, too short or starts at 0 drops out
    f = out["feed"]
    assert [(x["k"], x["coin"]) for x in f] == [(0, "SOL"), (4, "ZEC")]
    assert f[0]["pts"] == [[0, 0], [1, pytest.approx(0.01)], [2, pytest.approx(-0.005)]] and f[0]["last"] == pytest.approx(-0.005)
    assert f[1]["pts"] == [[0, 0], [1, pytest.approx(0.1)]]                                   # (a missing close skipped)
    w = out["wire"]
    assert w[0]["t"] == "11:50" and w[0]["kind"] == "exit"                                    # (KST)
    assert json.loads(w[0]["txt"]) == {"bot": "레인지 봇", "coin": "SOL", "kind": "exit", "side": -1, "pnl": 7.7, "text": "손절"}
    assert w[1]["t"] == "--:--" and json.loads(w[1]["txt"]) == {"bot": "바이비트 봇", "coin": "—", "kind": "signal", "side": 0, "text": "롱 신호"}
    assert out["wire0"] == []


def test_the_whole_screen_renders_on_the_real_answer(world):
    d = json_finite(D.build(candles_of(), NOW))
    out = _node("""
const ctx = {params: {query: {}}, alive: () => true, api: async (p) => { await null; if (A.fail) throw Object.assign(new Error("x"), {status: 0, kind: "network"}); return A.d; },
  every(ms, fn, o) { if (!o || o.now !== false) fn(); }, track() {}, listen() {}, watch() {}, on() {}, timeout() {}, href: (n, a) => '#/' + n + '/' + a};
const v = M.deckView(ctx);
await new Promise((r) => setTimeout(r, 40));
const ok = T.walk(v.el);
A.fail = true; A.d = null;
const v2 = M.deckView(ctx);
await new Promise((r) => setTimeout(r, 40));
const bad = T.walk(v2.el);
console.log(JSON.stringify({ok: ok.text, cls: ok.classes.join(" "), bad: bad.text}));""", {"d": d})
    t = out["ok"]
    assert not BAD.search(t), BAD.search(t)
    for w in ("관제실", "바이비트 봇", "친구 15분 봇", "레인지 봇", "지갑", "추세 그리드", "진입 카드", "포지션 진행", "실행 기록",
              "포워드 테스트", "히스토그램", "신호 흐름", "숏", "SHORT", "106.692", "장식", "목표 ×6", "경로보다", "남은 날 하루에 필요",
              "목표 연구 →", "코인 흐름", "FEED", "WIRE", "목표별 하루 필요", "×50", "$5,000", "하루 +13.9%", "SIGNAL CASCADE",
              "신호 · 48H", "다음 15분 마감", "30M TREND MACD", "3합 히스토그램", "추세 MACD 30분", "돌고 있음", "위험", "RISK", "청산가까지", "손절가에 닿으면",
              "펀딩 (바이낸스)", "이번 달 가장 깊은 낙폭", "연속 손실", "CALENDAR", "목표 넘은 날", "가장 좋은 날", "미실현 · 수수료 전",
              "지금", "ROE", "(수수료 전)"):
        assert w in t, w
    assert "dk-cell down" in out["cls"] and "dk-side down" in out["cls"] and "dk-grow g-thin" in out["cls"]
    # owners 11-01 (the picture again, their video): the feed's lines in the coins' colours, the opening's class, the ladder
    # (the walk sees the html's classes: the svg lines' own are drawn by s())
    assert "dk boot" in out["cls"] and "dk-gl on" in out["cls"] and "dk-mono dk-cid dk-k5" in out["cls"] and "dk-wl exit" in out["cls"]
    assert "×1 ×2 ×3 ×6 0일 10일 20일 30일 목표 ×6" in re.sub(r"\s+", " ", t)      # the goal chart: its axes and the path's tag
    assert not BAD.search(out["bad"])


# ---------------------------------------------------------------- static
def test_tokens_only_imports_through_pb_and_read_only():
    css, js, tok = _read(CSS), _read(JS), _read(os.path.join(V4, "tokens.css"))
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", body)
    for m in re.finditer(r"font-size\s*:\s*([^;}]+)", body):
        assert m.group(1).strip().startswith("var(--t-"), m.group(0)
    used = set(re.findall(r"var\((--dk-[\w-]+)\)", css)) | set(re.findall(r'"(--dk-[\w-]+)"', js))
    defined = set(re.findall(r"^\s*(--dk-[\w-]+)\s*:", tok, flags=re.M))
    assert used and used <= defined, used - defined
    assert {"--dk-core-cyan", "--dk-core-blue", "--dk-core-sand", "--dk-core-pink", "--dk-core-violet", "--dk-core-haze"} <= used
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", re.sub(r"//[^\n]*", "", js))
    imports = re.findall(r'from\s+"([^"]+)"', js)
    assert imports == ["../core/pb.js"]
    assert "innerHTML" not in js and "fetch(" not in js and "POST" not in js and "DOMParser" not in js
    # the decoration is said on the screen
    assert "흐름 모양·별·입자 색은 장식(Aizawa 흐름)" in js


def test_the_start_screen_and_the_tab():
    routes, lb = _read(os.path.join(V4, "core", "routes.js")), _read(os.path.join(SCREENS, "livebots.js"))
    assert 'export const LIVE_START = "deck";' in routes
    assert re.search(r'deck: \{ko: "관제실", group: "now"', routes)
    assert 'import {deckView} from "./livebots-deck.js";' in lb
    assert '{id: "deck", label: "관제실", make: (ctx) => deckView(ctx), own: true, bare: true}' in lb
    assert '@import url("livebots-deck.css");' in _read(os.path.join(SCREENS, "livebots.css"))
    assert "관제실" in _read(os.path.join(V4, "INVENTORY.md"))
    assert '.screen:has(.lb-tab-deck)' in _read(CSS)


def test_the_bot_screens_and_the_room_wear_the_hud():
    """Owners 11-01 ("봇별 화면이랑 회의실도 이렇게 멋있게 만들어야지"): each live bot's menu screens wear the 관제실's finish
    (screens/livebots-hud.css on .lb-hud), the room's panels take the 관제실's (its root is .dk). Tokens only, the 클래식 skin
    left as it was, the opening one-shot and still under reduced motion."""
    scr = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
    lb, hud = _read(os.path.join(scr, "livebots.js")), _read(os.path.join(scr, "livebots-hud.css"))
    routes = _read(os.path.join(ROOT, "paperbot", "dash", "static", "v4", "core", "routes.js"))
    menu = re.findall(r'"(\w+)"', "".join(re.findall(r'screens: \[([^\]]*)\]', routes.split("const LIVE_GROUPS = [")[1].split("];")[0])))
    hud_set = set(re.findall(r'"(\w+)"', re.search(r"export const HUD = new Set\(\[([^\]]*)\]\)", lb).group(1)))
    # every menu tab but the two with their own look (+ the 바이비트 봇's two, off the menu since 11-03: an old link)
    assert hud_set - {"bybitbot", "bybitperf"} == set(menu) - {"deck", "room"}
    assert 'el.classList.add("lb-hud", "lb-boot");' in lb and 'el.classList.remove("lb-boot"), 2600)' in lb
    assert '@import url("livebots-hud.css");' in _read(os.path.join(scr, "livebots.css"))
    body = re.sub(r"/\*.*?\*/", "", hud, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d", body) and not re.search(r"font-size:\s*\d", body)
    tok = _read(os.path.join(ROOT, "paperbot", "dash", "static", "v4", "tokens.css"))
    assert {v for v in re.findall(r"var\((--dk-[\w-]+)", body)} <= set(re.findall(r"(--dk-[\w-]+):", tok))
    rules = [r for r in re.findall(r"([^{}]+)\{", body) if r.strip() and not r.strip().startswith(("@", "from", "to"))]
    assert all(':root:not([data-skin="classic"]) .lb-hud' in r for r in rules if "%" not in r), rules
    anim = body.split("@media (prefers-reduced-motion: no-preference)")
    assert len(anim) == 2 and "animation" not in anim[0]               # (the opening only where motion is welcome)
    deck = re.sub(r"/\*.*?\*/", "", _read(os.path.join(scr, "livebots-deck.css")), flags=re.S)
    assert ".dk .dk-p::before" in deck and ".dk .dk-p:not(.rm-a-room) > .dk-ph" in deck   # (the room's panels too)
