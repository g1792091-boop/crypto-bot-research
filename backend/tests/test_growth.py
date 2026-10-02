"""1억 챌린지 검증 · 그리드 · 펀딩 차익 · 보호 장치 · 오픈소스 목록."""
import os
import time
from types import SimpleNamespace as NS

os.environ.setdefault("DATA_SOURCE", "synthetic")

from app.quant import carry, grid, growth, protect  # noqa: E402


def test_target_math_1000x_in_30_days():
    m = growth.target_math(100_000, 100_000_000, 30)
    assert m["multiple"] == 1000 and 9.9 < m["doublings"] < 10 and 25.8 < m["daily_pct"] < 26


def test_growth_is_honest_about_ruin():
    a = growth.analyze(src={"label": "가정", "returns": growth._assumed_returns(), "per_day": 3, "assumed": True}, sims=800)
    rows = {r["scale"]: r for r in a["rows"]}
    assert rows[1]["p_ruin"] <= 1 and rows[30]["p_ruin"] > 50          # 레버리지를 올리면 파산 확률이 먼저 오른다
    assert a["best"]["p_target"] < 5 and "가정" in a["verdict"]
    assert rows[30]["over_limit"] and not rows[1]["over_limit"]
    assert a["kelly"]["half"] <= growth.MAX_LIVE_LEV / 3


def test_growth_negative_edge_says_no():
    a = growth.analyze(src={"label": "나쁜 전략", "returns": [0.01] * 40 + [-0.012] * 60, "per_day": 2, "assumed": False}, sims=300)
    assert a["kelly"]["k"] == 0 and "기대값" in a["verdict"] and a["realistic_days"] is None


def _bars(prices):
    return [{"time": 1_700_000_000 + i * 3600, "open": p, "high": p * 1.004, "low": p * 0.996, "close": p, "volume": 1} for i, p in enumerate(prices)]


def test_grid_profits_in_range_and_stops_on_breakdown():
    up_down = [100 + 4 * ((i // 10) % 2 * 2 - 1) * ((i % 10) / 10) for i in range(400)]   # 96~104 박스 왕복
    r = grid.backtest(_bars(up_down), 95, 105, levels=10, leverage=2)
    assert r["round_trips"] > 5 and not r["liquidated"]
    crash = [100 - i * 0.5 for i in range(60)]
    r2 = grid.backtest(_bars(crash), 95, 105, levels=10, leverage=2, stop_pct=3)
    assert r2["stopped_at"] or r2["liquidated"]
    assert r2["return_pct"] < 0


def test_grid_and_carry_scan_synthetic():
    g = grid.scan(["BTCUSDT"])
    assert g and "return_pct" in g[0]
    c = carry.scan(["BTCUSDT", "ETHUSDT"])
    assert all("apr_pct" in x for x in c) and "펀딩" in carry.text(c)


def test_protections_block_new_entries():
    now = time.time()
    losses = [NS(pnl=-100, exit_time=now - 3600 * k) for k in (5, 3, 1)]
    r = protect.check(losses, 10_000, now)
    assert r["blocked"] and "손실 3번" in r["reason"]
    fresh_loss = [NS(pnl=50, exit_time=now - 90_000), NS(pnl=-20, exit_time=now - 60)]
    assert "분" in protect.check(fresh_loss, 10_000, now)["reason"]
    ok = [NS(pnl=40, exit_time=now - 7200 * k) for k in range(5)]
    assert not protect.check(ok, 10_000, now)["blocked"]


def test_live_sync_respects_protection(monkeypatch):
    from app import live
    opened = []
    monkeypatch.setitem(live.S, "enabled", True)
    monkeypatch.setitem(live.S, "approved", {"p1": {}})
    monkeypatch.setattr(live, "open_position", lambda *a, **k: opened.append(a))
    live._state["positions"].pop("p1", None)
    live.sync([{"id": "p1", "name": "t", "symbol": "BTCUSDT", "side": 1, "price": 100.0, "leverage": 2, "blocked": "24시간 안 손실 3번"}])
    assert opened == []
    live.sync([{"id": "p1", "name": "t", "symbol": "BTCUSDT", "side": 1, "price": 100.0, "leverage": 2, "blocked": None}])
    assert len(opened) == 1


def test_oss_catalog_and_api():
    from fastapi.testclient import TestClient

    from app.knowledge import oss
    from app.main import app
    assert len(oss.PROJECTS) >= 12 and all({"repo", "license", "applied", "todo", "kind"} <= set(p) for p in oss.PROJECTS)
    c = TestClient(app)
    assert c.get("/api/oss").json()["items"][0]["repo"]
    g = c.get("/api/growth?start=100000&target=1000000&days=60&lev=3").json()
    assert g["math"]["multiple"] == 10 and len(g["rows"]) == len(growth.SCALES)
    assert c.get("/api/growth?start=0").status_code == 400
    assert c.get("/api/carry/scan?symbols_csv=BTCUSDT").json()["items"]


def test_new_teams_and_tools():
    from app.office import roster, tools
    for tid in ("growth", "carry", "oss"):
        assert len(roster.MEMBERS[tid]) == 11
    assert "growth_check" in roster.tools_for("growth_1") and "results_search" in roster.tools_for("growth_1")
    r = tools.run("oss_projects", {"query": "freqtrade"})
    assert "freqtrade" in r["text"]
