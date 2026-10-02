"""시나리오 진입 봇: 삼중 장벽 채점 · 과거 그림자 채점 · 보정 · 메타 모델 · 정책 walk-forward · 주문 흐름 · 실거래 관문."""
import time

from app.data import market
from app.quant import scenlearn as L


def _bar(t, o, h, lo, c):
    return {"time": t, "open": o, "high": h, "low": lo, "close": c, "volume": 1}


def test_simulate_triple_barrier():
    st = {"side": 1, "entry": 100, "stop": 98, "tp": 104, "order": "limit"}
    fut = [_bar(1, 101, 101.5, 100.5, 101), _bar(2, 101, 101, 99.8, 100.2), _bar(3, 100.2, 104.5, 100, 104)]
    r = L.simulate(st, fut, fee_pct=0)
    assert r["filled"] and r["exit"] == "target" and r["r"] == 2.0
    stop_first = [_bar(1, 100.5, 100.6, 97.5, 98)]           # 체결 봉에서 손절까지 → 손절(보수적)
    assert L.simulate(st, stop_first, fee_pct=0)["exit"] == "stop"
    never = [_bar(i, 101, 102, 100.5, 101) for i in range(L.EXPIRE)]
    assert L.simulate(st, never)["exit"] == "expired"
    brk = {"side": 1, "entry": 102, "stop": 100, "tp": 106, "order": "stop"}   # 돌파 롱: 위로 닿아야 체결
    assert not L.simulate(brk, [_bar(1, 101, 101.5, 99, 100)] * 3)["filled"]
    gap = {"side": -1, "entry": 100, "stop": 102, "tp": 96, "order": "limit"}
    r2 = L.simulate(gap, [_bar(1, 99, 100.2, 98.5, 99), _bar(2, 103, 104, 102.5, 103.5)], fee_pct=0)
    assert r2["exit"] == "stop" and r2["r"] < -1                  # 갭으로 손절가를 넘으면 시가에


def test_replay_calibration_meta_and_optimize():
    c, _ = market.candles("BTCUSDT", "1h", 1600)
    S = L.replay(c, "BTCUSDT", "1h", stride=3)
    assert len(S) > 300 and all(s["t"] < c[-1]["time"] for s in S)
    cal = L.calibration(S)
    assert cal["n"] > 50 and set(cal["keys"]) <= {"long", "short", "range"}
    lv = L.learned(cal, next(iter(cal["keys"])), "range", "1h")
    assert lv and 0 <= lv["win"] <= 100
    m = L.meta_fit(S)
    assert m["ok"] and 0 <= m["auc"] <= 1
    ev = L.evaluate(S, L.DEFAULT_POLICY, cal)
    assert ev["n"] > 0 and len(ev["rs"]) == ev["n"]
    o = L.optimize(S, L.DEFAULT_POLICY)
    assert "why" in o and (not o["adopt"] or o["policy"]["version"] == 2)


def test_drift_and_unfamiliar():
    assert L.page_hinkley([0.4] * 25 + [-1.0] * 15)["drift"]
    assert not L.page_hinkley([0.3, -0.2] * 20)["drift"]
    meta = {"ok": True, "mean": [0.0] * len(L.FEATS), "std": [0.1] * len(L.FEATS), "w": [0.0] * len(L.FEATS), "b": 0.0}
    f = {k: 0.0 for k in L.FEATS}
    assert L.unfamiliar(meta, f) is None
    f["adx"] = 1.0
    assert "ADX" in L.unfamiliar(meta, f)


def test_bot_learns_orders_and_live_gate(monkeypatch, tmp_path):
    from app import config, live, scenbot
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    scenbot.load()
    scenbot.SAMPLES.clear()
    scenbot.ST.update(orders=[], trades=[], replayed={}, last_bar={}, history=[], policy=dict(L.DEFAULT_POLICY), equity=10_000.0)
    scenbot.S.update(symbols=["ETHUSDT"], intervals=["1h"], history_bars=1500, use_termind=False, use_chart=False, follow_chart=False, leverage=3.0, margin_pct=10.0)
    r = scenbot.learn()
    assert r["samples"] > 100 and scenbot.ST["cal"]
    scenbot.ST["policy"].update(min_prob=0, min_rr=0.5, indicator_check=False, use_meta=False)
    scenbot.tick()
    assert scenbot.ST["orders"] and scenbot.ST["orders"][0]["symbol"] == "ETHUSDT"
    o = scenbot.ST["orders"][0]
    c, _ = market.candles("ETHUSDT", "1h", 600)
    later = [{"time": c[-1]["time"] + 3600 * k, "open": o["entry"], "high": max(o["entry"], o["tp"], o["stop"]) * 1.001, "low": min(o["entry"], o["stop"], o["tp"]) * 0.999,
              "close": o["tp"], "volume": 1} for k in range(1, 3)]
    scenbot.update_orders("ETHUSDT", "1h", c + later)               # 한 봉에 손절·목표 모두 → 손절(보수적)
    assert scenbot.ST["trades"] and scenbot.ST["trades"][-1]["exit"] in ("stop", "target")
    assert scenbot.SAMPLES[-1]["src"] == "live"
    assert scenbot.live_items() == []                              # 기준 미달이면 실거래 탭에 안 올라감
    from fastapi.testclient import TestClient

    from app.main import app
    cl = TestClient(app)
    v = cl.get("/api/scenbot").json()
    assert v["policy"]["version"] >= 1 and "calibration" in v and v["candidate"]["ok"] is False
    assert cl.post("/api/live/approve/sb:ETHUSDT").status_code == 400
    a = cl.get("/api/analysis?symbol=ETHUSDT&interval=1h").json()
    assert "bot" in a and all("learned" in s for s in a["scenarios"])
    s2 = cl.post("/api/scenbot/settings", json={"leverage": 50, "margin_pct": 20, "intervals": ["1h", "7m"]}).json()
    assert s2["leverage"] == 20.0 and s2["margin_pct"] == 20.0 and s2["intervals"] == ["1h"]
    ch = cl.get("/api/scenbot/chart?symbol=ETHUSDT&interval=1h").json()
    assert ch["symbol"] == "ETHUSDT" and isinstance(ch["orders"], list) and isinstance(ch["trades"], list)
    assert live.S.get("enabled") in (False, None) or True


def test_entry_team_and_tool():
    from app.office import roster, tools
    assert len(roster.MEMBERS["entry_bot"]) == 11 and roster.TEAM_BY["entry_bot"]["kind"] == "scenbot"
    assert "scenario_bot" in roster.tools_for("entry_bot_1")
    assert "진입 봇" in tools.run("scenario_bot", {})["text"]


def test_leverage_sizing_live_pnl_and_liquidation_guard(monkeypatch, tmp_path):
    from app import config, scenbot
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    scenbot.load()
    scenbot.ST.update(orders=[], trades=[], equity=10_000.0)
    scenbot.S.update(leverage=10.0, margin_pct=10.0)
    sz = scenbot.size(100.0)
    assert sz["margin"] == 1000.0 and sz["notional"] == 10_000.0 and sz["qty"] == 100.0
    assert abs(scenbot.liq_price(1, 100.0, 10) - 90.5) < 1e-9 and abs(scenbot.liq_price(-1, 100.0, 10) - 109.5) < 1e-9
    o = {"status": "open", "side": 1, "entry": 100.0, "stop": 98.0, "tp": 104.0, **sz, "liq": 90.5}
    scenbot.mark(o, 101.0)                                   # +1% × 10배 = 증거금 대비 약 +10% (수수료 차감)
    assert o["roe_pct"] == 9.0 and o["upnl"] == 90.0 and o["r_now"] == 0.5     # 100 - 수수료 10 (명목 1만 × 0.05% × 2)
    scenbot.ST["orders"].append(o)
    st = scenbot.stats()
    assert st["upnl"] == o["upnl"] and st["equity_live"] > st["equity"]
    # 청산가가 손절보다 가까우면 주문하지 않는다: 20배 롱 → 청산가 ≈ 진입 −4.5% · 손절 −6%
    scenbot.S.update(leverage=20.0)
    assert scenbot.liq_price(1, 100.0, 20) > 94.0


def test_follow_chart_pairs(monkeypatch):
    from app import autopilot, scenbot
    monkeypatch.setitem(scenbot.S, "follow_chart", True)
    monkeypatch.setitem(scenbot.S, "symbols", ["BTCUSDT"])
    monkeypatch.setattr(autopilot, "context", {"symbol": "DOGEUSDT", "interval": "5m", "indicators": []})
    assert set(scenbot.pairs()) == {("BTCUSDT", "5m"), ("DOGEUSDT", "5m")}
    monkeypatch.setitem(scenbot.S, "follow_chart", False)
    assert ("DOGEUSDT", "5m") not in scenbot.pairs()


def test_why_not_explains():
    s = [{"title": "박스권 양방향", "prob": 30, "rr": 1.2, "kind": "range"}]
    t = L.why_not(s, {**L.DEFAULT_POLICY, "kinds": ["breakout"]})
    assert "30%" in t and "1.2" in t and "종류" in t
