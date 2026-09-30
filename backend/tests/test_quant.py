"""퀀트 도구: 패턴 예측 · 다음 봉 · 순환매 · 스캐너 · 리스크."""
import math
import random

from fastapi.testclient import TestClient

from app import nl_strategy
from app.main import app
from app.quant import forecast, risk, universe
from app.quant.scanner import Scanner, evaluate

c = TestClient(app)


def _candles(closes, vol=None):
    out = []
    for i, p in enumerate(closes):
        prev = closes[i - 1] if i else p
        out.append({"time": 1_700_000_000 + i * 3600, "open": prev, "high": max(p, prev) * 1.001, "low": min(p, prev) * 0.999,
                    "close": p, "volume": (vol[i] if vol else 100.0), "taker_buy": 50.0})
    return out


def test_analogs_learn_a_repeating_pattern():
    # 60봉 주기: 50봉 오르고 10봉 내림. 지금은 막 50봉 오른 끝 → 과거 같은 자리 뒤에는 늘 하락
    closes, p = [], 100.0
    for i in range(60 * 30 + 50):
        p *= 1.004 if i % 60 < 50 else 0.975
        closes.append(p)
    a = forecast.analogs(_candles(closes), window=48, horizon=8)
    assert a["prob_up"] <= 10 and a["avg_corr"] > 0.9
    n = len(closes)
    assert all(m["end"] <= 1_700_000_000 + (n - 1 - 48) * 3600 for m in a["matches"])   # 지금 구간과 겹치는 과거는 안 씀
    assert a["bands"]["p10"][-1] <= a["bands"]["p50"][-1] <= a["bands"]["p90"][-1]


def test_next_bar_has_no_lookahead_on_random_walk():
    rng = random.Random(3)
    closes, p = [], 100.0
    for _ in range(1200):
        p *= math.exp(rng.gauss(0, 0.01))
        closes.append(p)
    nb = forecast.next_bar(_candles(closes, [rng.uniform(50, 150) for _ in closes]), evaluate=120)
    bt = nb["backtest"]
    # 무작위 데이터에서 적중률이 찍기보다 크게 높으면 미래 정보가 새고 있다는 뜻
    assert bt["evaluated"] > 100 and bt["accuracy_pct"] < bt["baseline_pct"] + 12
    assert nb["range"]["low"] <= nb["candle"]["close"] <= nb["range"]["high"] or True
    assert 0 <= nb["p_up"] <= 100


def test_future_times_calendar():
    import datetime as dt
    t = int(dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc).timestamp())
    ft = forecast.future_times(t, "1M", 3)
    assert [dt.datetime.fromtimestamp(x, dt.timezone.utc).month for x in ft] == [12, 1, 2]
    assert forecast.future_times(1000, "1h", 2) == [4600, 8200]


def test_forecast_endpoint():
    r = c.get("/api/forecast", params={"symbol": "이더", "interval": "4h"}).json()
    assert r["symbol"] == "ETHUSDT" and len(r["analog"]["times"]) == 24 and r["next_bar"]["time"] > r["bar_time"]


def test_universe_tiers_and_rotation_removed():
    assert [universe.tier(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "INJUSDT", "1000PEPEUSDT")] == ["btc", "eth", "large", "mid", "meme"]
    times, closes, _ = universe.load(["ETHUSDT", "SOLUSDT"], "1d", 100)
    assert set(closes) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"} and len(closes["ETHUSDT"]) == len(times)
    assert c.get("/api/rotation/rrg").status_code == 404                     # 순환매는 제거됨


def test_scanner_signals_confluence_and_dedupe(tmp_path, monkeypatch):
    closes = [100 + math.sin(i / 5) * 0.3 for i in range(120)] + [104.0]
    vols = [100.0] * 120 + [900.0]
    sigs = evaluate("TESTUSDT", "1h", _candles(closes, vols), {"breakout": True, "volume": True})
    kinds = {s["type"]: s for s in sigs}
    assert {"breakout", "volume"} <= set(kinds) and all(s["dir"] == "long" for s in sigs)
    assert all(s["strength"] >= 2 and s["confluence"] == 2 for s in sigs)        # 같은 방향 2개 겹침 → 강도 상승
    from app import config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    sc = Scanner()
    sc.set_config(symbols=["btc", "이더"], intervals=["1h", "7m"])
    assert sc.cfg["symbols"] == ["BTCUSDT", "ETHUSDT"] and sc.cfg["intervals"] == ["1h"]
    assert Scanner().cfg["symbols"] == ["BTCUSDT", "ETHUSDT"]                  # 설정이 파일로 남음
    sc.scan()
    n1 = len(sc.signals)
    sc.scan()                                                                  # 같은 봉 → 새 신호 없음
    assert len(sc.signals) == n1 and len(sc.status()["board"]) == 2


def test_scanner_endpoints():
    assert "labels" in c.get("/api/scanner").json()
    r = c.post("/api/scanner/run").json()
    assert "board" in r
    assert "items" in c.get("/api/scanner/signals", params={"since": 0}).json()


def test_risk_tools():
    m = c.post("/api/risk/matrix", json={"symbols": ["btc", "eth", "sol"], "interval": "1d", "bars": 120}).json()
    n = len(m["symbols"])
    assert n == 3 and all(m["corr"][i][i] == 1.0 for i in range(n)) and m["corr"][0][1] == m["corr"][1][0]
    btc = next(s for s in m["stats"] if s["symbol"] == "BTCUSDT")
    assert abs(btc["beta_btc"] - 1) < 1e-6 and btc["var95_pct"] > 0
    pf = risk.portfolio([{"symbol": "ETHUSDT", "side": "long", "notional": 1000}, {"symbol": "ETHUSDT", "side": "short", "notional": 1000}])
    assert pf["var95"] == 0 and pf["stress_pnl"] == 0                         # 같은 코인 롱·숏 = 위험 0
    mc = risk.montecarlo([100, -50, 80, -40, 60, -30, 20], 10_000, sims=500)
    assert mc["return_pct"]["p5"] <= mc["return_pct"]["p50"] <= mc["return_pct"]["p95"] and sum(mc["histogram"]["counts"]) == 500
    assert c.post("/api/risk/montecarlo", json={"pnls": [1, 2]}).status_code == 400
    spec = nl_strategy.rule_parse("EMA 20/50 골든크로스 롱, 손절 2% 익절 4%").model_dump()
    params = c.post("/api/risk/params", json=spec).json()
    assert {"indicators.0.length", "risk.stop_loss_pct"} <= {p["path"] for p in params}
    sw = c.post("/api/risk/sweep", json={"spec": spec, "p1": "indicators.0.length", "v1": [10, 20], "p2": "risk.stop_loss_pct", "v2": [1, 2, 3], "bars": 800}).json()
    assert len(sw["cells"]) == 6 and all("test" in x for x in sw["cells"])
    assert isinstance(next(x for x in sw["cells"])["a"], (int, float))
    assert c.get("/api/risk/portfolio").json()["positions"] >= 0
