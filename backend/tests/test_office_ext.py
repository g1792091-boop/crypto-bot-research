import json
import time
import zipfile

import pytest

from app import live, llm
from app.office import engine as office
from app.office import org, roster, teamjobs


@pytest.fixture
def env(monkeypatch):
    def run(kind, system, user, max_tokens, *a, **k):
        if "새 매매법 개발" in system:
            spec = {"name": "커스텀 모멘텀 돌파" if "커스텀 지표" in system else "EMA 추세", "indicators": [
                {"id": "f", "type": "ema", "length": 20}, {"id": "s", "type": "ema", "length": 50},
                {"id": "vm", "type": "custom", "expr": "(close - close[20]) / (ind(\"atr\",{length:14}) * sqrt(20))"}],
                "long_entry": {"logic": "all", "conditions": [{"left": "f", "op": "crosses_above", "right": "s"}]},
                "short_entry": {"logic": "all", "conditions": [{"left": "f", "op": "crosses_below", "right": "s"}]},
                "risk": {"leverage": 3, "atr_stop_mult": 2}}
            return "💭 설계합니다.\n```json\n" + json.dumps(spec, ensure_ascii=False) + "\n```\n이유입니다.", "fake:m"
        return "💭 자료를 봤습니다.\n지금은 추세가 이어지는 중입니다.\n결론: 관망", "fake:m"
    monkeypatch.setattr(llm, "_run", run)
    monkeypatch.setattr(office, "ai_ok", lambda: True)
    import app.main  # noqa: F401
    office.load()
    office.ST.update(office._default_state())
    office.LOG.clear()
    office.RT["queue"].clear()
    return run


def test_org_has_all_requested_teams_with_lead_and_ten():
    names = {t["name"] for t in roster.TEAMS}
    for need in ["보조지표 분석팀", "매매법 개발팀", "백테스트팀", "데모거래팀", "실거래팀", "추세 분석팀", "진입 타점 분석팀", "뉴스·경제지표팀",
                 "지지저항 분석팀", "익절손절 관리팀", "코인별 상황 분석팀", "커스텀 지표 개발팀", "커스텀 지표 백테스트팀", "커스텀 지표 데모거래팀",
                 "커스텀 지표 실거래팀", "차트·캔들 패턴 분석팀", "비트코인팀", "도지코인팀"]:
        assert need in names, need
    for t in roster.TEAMS:
        if t.get("ext"):
            mem = roster.MEMBERS[t["id"]]
            assert len(mem) == 11 and roster.BY_ID[mem[0]]["lead"] and sum(roster.BY_ID[m]["lead"] for m in mem) == 1
    assert len({a["name"] for a in roster.AGENTS}) == len(roster.AGENTS)
    assert all(roster.WATCH.get(a["id"]) for a in roster.AGENTS)


def test_pipeline_dev_backtest_demo_promote(env):
    teamjobs.run_team("dev")
    p = teamjobs.pipeline()[-1]
    assert p["stage"] == "backtest" and not p["custom"]
    teamjobs.run_team("bt")
    assert p["stage"] in ("demo", "rejected") and p["bt"]["grade"]
    assert any(e["kind"] == "bt" and e.get("pid") == p["id"] for e in office.LOG)
    if p["stage"] == "demo":
        teamjobs.run_team("demo")
        assert p["bot_id"] in office._paper.bots
        b = office._paper.bots[p["bot_id"]]
        b.created = time.time() - 5 * 86400                       # 데모 성과가 쌓였다고 가정
        from app.engine import Trade
        for i in range(12):
            b.sim.trades.append(Trade("long", i, i + 1, 100, 103 if i % 3 else 99, 1, 3, 30.0 if i % 3 else -10.0, 3, 0.1, 0, "x", "y"))
        b.sim.cash = 10_000 + sum(t.pnl for t in b.sim.trades)
        teamjobs.run_team("demo")
        assert p["stage"] == "candidate" and p["demo"]["trades"] == 12
        assert any(x["id"] == p["id"] and not x["approved"] for x in teamjobs.live_items())


def test_custom_pipeline_requires_custom_indicator(env):
    teamjobs.run_team("cdev")
    p = teamjobs.pipeline()[-1]
    assert p["custom"] and any(i["type"] == "custom" for i in p["spec"]["indicators"])
    teamjobs.run_team("cbt")
    assert p["stage"] in ("demo", "rejected")


@pytest.mark.parametrize("team", ["ind", "trend", "sr", "pattern", "board", "tpsl", "coin_btc", "coin_doge", "entry", "news"])
def test_analysis_teams_post_and_save(env, team):
    teamjobs.run_team(team)
    assert any(e["ch"] == team and e["kind"] == "agent" and e.get("text") for e in office.LOG), team
    assert (office._dir() / "files" / "teams" / team).exists()


def test_rule_fallback_without_ai(env, monkeypatch):
    monkeypatch.setattr(office, "ai_ok", lambda: False)
    teamjobs.run_team("cdev")
    teamjobs.run_team("dev")
    assert len(teamjobs.pipeline()) >= 1


def test_live_signing_guards_and_sync(monkeypatch, tmp_path):
    import hashlib
    import hmac
    q = live.sign({"symbol": "BTCUSDT", "timestamp": 1}, "secret")
    assert q.endswith(hmac.new(b"secret", b"symbol=BTCUSDT&timestamp=1", hashlib.sha256).hexdigest())
    calls = []

    def fake_req(method, path, params=None, signed=True):
        calls.append((method, path, dict(params or {})))
        if path == "/fapi/v1/exchangeInfo":
            return {"symbols": [{"symbol": "BTCUSDT", "filters": [{"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                                                                  {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}
        return {"orderId": 1}
    monkeypatch.setattr(live, "_req", fake_req)
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    live.S.update(live.DEFAULT, approved={}, enabled=False)
    live._state.update(positions={}, realized=0.0, day=time.strftime("%Y-%m-%d"))
    item = {"id": "p1", "name": "T", "symbol": "BTCUSDT", "side": 1, "price": 50_000.0, "leverage": 50}
    live.sync([item])
    assert not calls                                                   # 꺼져 있으면 아무것도 안 함
    live.S["enabled"] = True
    live.sync([item])
    assert not calls                                                   # 승인 안 됐으면 안 함
    live.approve("p1", True)
    live.sync([item])
    orders = [c for c in calls if c[1] == "/fapi/v1/order"]
    lev = [c for c in calls if c[1] == "/fapi/v1/leverage"]
    assert orders and orders[0][2]["side"] == "BUY" and orders[0][2]["quantity"] == 0.001   # 50 USDT / 50000 = 0.001
    assert lev[0][2]["leverage"] == 5                                  # 최대 레버리지로 잘림
    live.sync([{**item, "side": 0, "price": 40_000.0}])                 # 데모가 청산 → 실거래도 청산
    closes = [c for c in calls if c[1] == "/fapi/v1/order" and c[2].get("reduceOnly") == "true"]
    assert closes and live._state["realized"] < 0
    live.S["daily_loss_usdt"] = 1.0
    live.sync([item])                                                  # 하루 손실 한도 → 진입 거부
    assert len([c for c in calls if c[1] == "/fapi/v1/order"]) == 2
    live.S.update(enabled=False, approved={})


def test_results_listing_zip_and_safe_path(env):
    from app.office import results
    teamjobs.run_team("board")
    d = results.listing()
    paths = {f["path"] for f in d["files"]}
    assert "research.csv" in paths and "pipeline.csv" in paths and any(p.startswith("boards/") for p in paths)
    z = results.zip_all()
    assert "research.csv" in zipfile.ZipFile(z).namelist()
    with pytest.raises(ValueError):
        results.safe_path("../state.json")


def test_api_results_models_live(env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/office/results").json()
    assert r["root"].endswith("files") and r["files"]
    f = r["files"][0]["path"]
    assert c.get("/api/office/results/file", params={"path": f}).status_code == 200
    assert c.get("/api/office/results/file", params={"path": "../../x"}).status_code == 404
    assert c.get("/api/office/results/zip").headers["content-type"] == "application/zip"
    assert c.post("/api/office/cfg", json={"models": {"team:bt": "nvidia#2:auto"}}).json()["models"]["team:bt"] == "nvidia#2:auto"
    assert c.post("/api/office/cfg", json={"models": {"team:bt": "bad model"}}).status_code == 400
    assert office.assigned_routes("bt_3") == ["nvidia#2:auto"]
    office.set_cfg({"models": {}})
    assert c.post("/api/live/settings", json={"enabled": True}).status_code == 400          # 확인 문구 없이 못 켬
    assert c.post("/api/live/settings", json={"testnet": False, "confirm": "아니"}).status_code == 400
    assert c.get("/api/live").json()["settings"]["testnet"] is True
    assert c.post("/api/live/approve/nope").status_code == 400
    assert c.get("/api/office/pipeline").json()["rules"]["promote"]["trades"] == 10


def test_assign_keys_evenly(env, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY_2", "x2")
    from app import config
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "x1")
    m = office.assign_keys_evenly()
    vals = list(m.values())
    assert "nvidia:auto" in vals and "nvidia#2:auto" in vals and len(m) == len(roster.TEAMS)
    office.set_cfg({"models": {}})
