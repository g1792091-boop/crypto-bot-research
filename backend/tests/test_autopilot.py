"""오토파일럿: 차트 지표 → 후보 → 3구간 관문 → 봇 배치 → 시그널, 새 지표 · 매매법 라이브러리."""
import time

from fastapi.testclient import TestClient

from app import autopilot, backtest, indicators as ind, library
from app.data import market
from app.main import app, paper
from app.strategy import StrategySpec, validate
from app.team import engine as team

c = TestClient(app)


def test_new_dsl_indicators_have_full_length():
    cs, _ = market.candles("BTCUSDT", "1h", 300)
    for t in ("wma", "hma", "vwma", "mfi", "willr", "roc", "psar", "donchian", "keltner", "stochrsi", "ichimoku", "cmf", "aroon", "atr_stop"):
        out = ind.compute(cs, t, {})
        assert out and all(len(v) == len(cs) for v in out.values()), t
        assert any(x is not None for v in out.values() for x in v[-20:]), t
    w = ind.compute(cs, "willr", {})["value"]
    assert all(-100 <= x <= 0 for x in w if x is not None)
    tr = ind.compute(cs, "atr_stop", {})["trend"]
    assert set(x for x in tr if x is not None) <= {1, -1}


def test_chart_indicators_map_to_valid_candidates():
    chart = [{"key": "ema", "params": {"length": 50}}, {"key": "rsi", "params": {"length": 14}}, {"key": "bb", "params": {}},
             {"key": "volume", "params": {}}, {"key": "kalman", "params": {}}, {"key": "ichimoku", "params": {}}]
    u = autopilot.usable(chart)
    assert set(u["usable"]) == {"ema", "rsi", "bb", "volume", "ichimoku"} and u["unusable"] == ["kalman"]
    specs, used_default = autopilot.candidates("BTCUSDT", "1h", chart)
    assert not used_default and 0 < len(specs) <= 240
    assert all(not validate(s) for s in specs)
    assert any("RSI" in s.name for s in specs) and any("볼린저" in s.name for s in specs)
    # 쓸 수 있는 진입 지표가 없으면 기본 지표로
    specs2, used_default2 = autopilot.candidates("BTCUSDT", "1h", [{"key": "kalman", "params": {}}])
    assert used_default2 and specs2


def test_three_window_gate_and_family_dedupe():
    r = autopilot.evaluate("BTCUSDT", "1h", [{"key": "ema", "params": {"length": 50}}, {"key": "rsi", "params": {}}])
    assert r["tried"] > 50 and r["finalists"] <= 15
    for p in r["passed"]:
        s = p["seg"]
        assert s["train"]["trades"] >= autopilot.GATE["train"]["trades"] and s["valid"]["net"] > 0 and s["hold"]["net"] > 0
        assert (s["hold"]["pf"] or 0) >= autopilot.GATE["hold"]["pf"]
    fams = [p["name"].split(" · ")[0] for p in r["passed"]]
    assert len(fams) == len(set(fams))
    assert r["periods"]["train_to"] < r["periods"]["valid_to"] < r["periods"]["hold_to"]


def test_search_deploys_bots_and_emits_signals(monkeypatch):
    for bid in list(autopilot.state["bots"]):
        autopilot.retire(bid, "테스트 초기화")
    autopilot.set_settings(team_review=False, max_bots=2, extra_interval=False, observe_if_none=True)
    autopilot.set_context("BTCUSDT", "1h", [{"key": "ema", "params": {"length": 50}}, {"key": "macd", "params": {}}])
    autopilot.state["searching"] = True
    autopilot._search("테스트")
    bots = autopilot.status()["bots"]
    assert 1 <= len(bots) <= 2 and all(b["symbol"] == "BTCUSDT" and b["interval"] == "1h" for b in bots)
    assert all(b["id"] in paper.bots for b in bots)
    kinds = {b["kind"] for b in bots}
    assert kinds <= {"pass", "observe"}
    assert any(s["type"] == "deploy" for s in autopilot.recent_signals(0))
    # 봇이 진입하면 진입 시그널 (진입가 · 손절 · 익절)
    b = paper.bots[bots[0]["id"]]
    cs, _ = market.candles("BTCUSDT", "1h", 50)
    b.sim.pending = "long"
    b.sim.execute_pending(cs[-1]["close"], int(time.time()), cs[-1]["high"] - cs[-1]["low"])
    since = int(time.time()) - 1
    assert autopilot.watch_bots() >= 1
    sig = [s for s in autopilot.recent_signals(since) if s["type"] == "entry"]
    assert sig and sig[0]["side"] == "long" and sig[0]["entry"] > 0 and sig[0]["strategy"]
    # 차트 코인을 바꾸면 포지션 없는 봇만 정리
    autopilot.set_context("ETHUSDT", "4h", [])
    autopilot._review_old()
    left = autopilot.status()["bots"]
    assert [x["id"] for x in left] == [bots[0]["id"]]                 # 포지션 있는 봇은 남음
    r = c.get("/api/autopilot/signals", params={"since": 0}).json()
    assert r["items"]
    autopilot.retire(bots[0]["id"], "테스트 정리")


def test_team_reviews_autopilot_candidates():
    cand = [{"id": "ap:BTCUSDT:1h:0", "kind": "autopilot", "target": "테스트", "gate": {"passed": True, "test_trades": 12, "reason": "통과"}},
            {"id": "ap:BTCUSDT:1h:1", "kind": "autopilot", "target": "탈락", "gate": {"passed": False, "test_trades": 3, "reason": "탈락"}}]
    run = team.run_pipeline("autopilot", "테스트", extra={"candidates": cand})
    t0 = time.time()
    while run.status == "running" and time.time() - t0 < 60:
        time.sleep(0.2)
    ap = {a["candidate"]: a["decision"] for a in run.results["approvals"]}
    assert ap == {"ap:BTCUSDT:1h:0": "approve", "ap:BTCUSDT:1h:1": "reject"}
    assert [m["from"] for m in run.messages if m["from"] != "code"] == ["validator", "approver", "risk", "lead"]


def test_endpoints_and_library():
    st = c.get("/api/autopilot").json()
    assert "settings" in st and "usable" in st and st["gate"]["train"]["trades"] == 20
    r = c.post("/api/autopilot/context", json={"symbol": "솔라나", "interval": "15m", "indicators": [{"key": "supertrend", "params": {}}]}).json()
    assert r["context"]["symbol"] == "SOLUSDT" and r["usable"]["usable"] == ["supertrend"]
    s = c.post("/api/autopilot/settings", json={"max_bots": 99, "leverage": 500}).json()
    assert s["max_bots"] == 10 and s["leverage"] == 50
    c.post("/api/autopilot/settings", json={"max_bots": 3, "leverage": 3})
    items = c.get("/api/strategy/library", params={"symbol": "ETH", "interval": "4h"}).json()["items"]
    assert len(items) >= 20
    cs, _ = market.candles("ETHUSDT", "4h", 800)
    for it in items:
        sp = StrategySpec(**it["spec"])
        assert not validate(sp), it["key"]
        assert sp.symbol == "ETHUSDT"
        backtest.run(sp, cs, None)
    assert len(library.LIBRARY) == len(items)
