import math

from fastapi.testclient import TestClient

from app import improve
from app.main import app
from app.nl_strategy import rule_edit, rule_parse
from app.paper import PaperBot
from app.strategy import validate


def _spec():
    return rule_parse("BTC 1시간봉 EMA 20/50 골든크로스 롱 데드크로스 숏, RSI 70 이상이면 롱 제외, 손절 2% 익절 4% 5배")


def test_rule_edit_changes_only_what_was_asked():
    s = _spec()
    s2, ch = rule_edit(s, "손절 3%로 하고 레버리지 10배로")
    assert s2.risk.stop_loss_pct == 3 and s2.risk.leverage == 10 and s2.risk.take_profit_pct == 4 and len(ch) == 2
    s3, ch = rule_edit(s, "RSI 조건 빼줘")
    assert all("rsi" not in c.left for c in s3.long_entry.conditions) and not any(i.type == "rsi" for i in s3.indicators)
    s4, ch = rule_edit(s, "MACD 골든크로스도 추가")
    assert any(c.left == "macd.line" for c in s4.long_entry.conditions) and validate(s4) == []
    s5, ch = rule_edit(s, "롱만 하고 4시간봉으로")
    assert s5.short_entry is None and s5.interval == "4h"
    assert rule_edit(s, "안녕")[1] == []


def test_explain_trade_mentions_causes():
    trade = {"side": "long", "entry_time": 10, "exit_time": 20, "pnl": -50.0, "exit_reason": "stop_loss"}
    f = {"with_trend": False, "adx": 12.0, "rsi": 75.0, "atr_pct": 2.0, "high_vol": True, "stretch_atr": 3.1,
         "vol_ratio": 0.5, "st_agree": False, "funding": None, "bars_held": 3}
    n = improve.explain(trade, f)
    assert not n["win"] and len(n["bad"]) >= 5 and "손실" in n["note"]
    n2 = improve.explain({**trade, "pnl": 80.0, "exit_reason": "take_profit"},
                         {**f, "with_trend": True, "adx": 30.0, "st_agree": True, "rsi": 55, "stretch_atr": 1.0,
                          "vol_ratio": 1.8, "high_vol": False})
    assert n2["win"] and "잘 된 이유" in n2["note"] and len(n2["good"]) >= 3


def test_improve_only_applies_validated_changes():
    rep = improve.run_for(_spec(), 1500)
    assert rep["baseline"]["train"]["trades"] > 0 and rep["journal"]
    if rep["applied"]:
        assert rep["after"]["train"]["net_pnl"] > rep["baseline"]["train"]["net_pnl"]
        assert rep["after"]["test"]["net_pnl"] >= rep["baseline"]["test"]["net_pnl"]
        assert validate(__import__("app.strategy", fromlist=["StrategySpec"]).StrategySpec(**rep["spec"])) == []
    for c in rep["candidates"]:
        if c["passed"]:
            assert c["test"]["net_pnl"] >= rep["baseline"]["test"]["net_pnl"]


def test_old_pickled_bot_gets_new_fields():
    bot = PaperBot(spec=_spec())
    state = dict(bot.__dict__)
    for k in ("auto_improve", "journal", "versions", "improve_every", "improved_at_trades"):
        state.pop(k)
    b2 = PaperBot.__new__(PaperBot)
    b2.__setstate__(state)
    assert b2.journal == [] and b2.auto_improve is False and b2.to_dict()["versions"] == []


def test_refine_and_markers_endpoints():
    with TestClient(app) as c:
        spec = _spec().model_dump()
        r = c.post("/api/strategy/refine", json={"spec": spec, "message": "익절 6%로"}).json()
        assert r["spec"]["risk"]["take_profit_pct"] == 6 and r["backtest"]["metrics"]
        r = c.post("/api/strategy/refine", json={"spec": spec, "message": "알아서 개선해줘"}).json()
        assert r["engine"] == "improve" and "improve" in r
        bot = c.post("/api/paper/bots", json={"spec": spec}).json()
        cfg = c.post(f"/api/paper/bots/{bot['id']}/config", json={"auto_improve": True, "improve_every": 5}).json()
        assert cfg["auto_improve"] and cfg["improve_every"] == 5
        assert c.post(f"/api/paper/bots/{bot['id']}/improve").status_code == 200
        c.post("/api/paper/order", json={"symbol": "BTCUSDT", "side": "short", "margin": 100, "leverage": 3})
        c.post("/api/paper/close/BTCUSDT")
        m = c.get("/api/paper/markers?symbol=BTCUSDT").json()
        assert any(b["id"] == bot["id"] for b in m["bots"]) and m["manual"]["trades"][-1]["symbol"] == "BTCUSDT"
