import json
import time

import pytest

from app import llm
from app.office import engine as office
from app.office import roster

STRAT = {"name": "EMA 추세 + 커스텀 모멘텀", "indicators": [{"id": "f", "type": "ema", "length": 20}, {"id": "s", "type": "ema", "length": 50},
                                                           {"id": "vm", "type": "custom", "expr": "(close - close[20]) / (ind(\"atr\",{length:14}) * sqrt(20))"}],
         "long_entry": {"logic": "all", "conditions": [{"left": "f", "op": "crossover", "right": "s"}]},
         "short_entry": ["f crosses_below s"], "risk": {"leverage": "3", "atr_stop_mult": 2}}


@pytest.fixture
def fake_ai(monkeypatch):
    calls = []

    def run(kind, system, user, max_tokens, *a, **k):
        calls.append((system, user))
        if "새 매매법 개발" in system:
            return "💭 추세를 따라가 보겠습니다.\n```json\n" + json.dumps(STRAT, ensure_ascii=False) + "\n```\n추세 구간에서 버티는 전략입니다.", "fake:model"
        if "[잡담]" in system:
            return "레오: 비트코인 펀딩이 올랐네요.\n지안: 롱이 좀 쏠렸어요.\n레오: 회의 한번 하죠", "fake:model"
        if "회고·성장 회의" in system:
            return "💭 돌아보겠습니다.\n배운 점 정리.\n```json\n{\"lessons\":[\"검증 구간 거래 수를 먼저 본다\"],\"tasks\":[{\"title\":\"ETH 4시간 역추세 재시험\",\"why\":\"표본 부족\",\"owner\":\"세라\"}]}\n```", "fake:model"
        if "방향 예측 토론" in user and "<tool_result" not in user:
            return "💭 차트를 봤습니다.\n비트코인은 버티는 중입니다.\n예측: 비트코인 상승 60%\n예측: 이더리움 하락 55%", "fake:model"
        if "회의 중" in system and "<tool_result" not in user and "지금 비트코인" in user:
            return '<tool name="market_quote">{"symbols":["BTCUSDT"]}</tool>', "fake:model"
        return "💭 확인한 것을 정리합니다.\nWe need to think about this.\n\n자료를 보니 지금은 관망이 낫겠습니다. 리스크 판정: 승인", "fake:model"
    monkeypatch.setattr(llm, "_run", run)
    monkeypatch.setattr(office, "ai_ok", lambda: True)
    import app.main  # noqa: F401  (시그널 추적 장부를 연결한다)
    office.load()
    office.ST.update(office._default_state())
    office.LOG.clear()
    office.RT["queue"].clear()
    office.RT["meeting"] = None
    if not _runner["on"]:                                               # 회의 진행자 (job_forecast·job_task 가 회의를 기다린다)
        import threading
        threading.Thread(target=office._runner, daemon=True).start()
        _runner["on"] = True
    return calls


_runner = {"on": False}


def test_roster_four_teams_24_staff():
    assert [t["id"] for t in roster.TEAMS][:4] == ["coin", "quant", "strat", "data"]
    base = [a for a in roster.AGENTS if not a.get("ext")]
    assert len(base) == 24 and all(len(roster.MEMBERS[t]) == 6 for t in ("coin", "quant", "strat", "data"))
    assert {a["id"] for a in base if a["lead"]} == {"coin_fut", "qa", "strat", "sns"}
    assert all(roster.WATCH.get(a["id"]) for a in roster.AGENTS)            # 원본에서 놀던 9명도 볼 것이 있다
    assert "ml_predict" in roster.tools_for("ml") and "futures_flow" in roster.tools_for("deriv")


def test_speaker_order_rules():
    o = office._speaker_order("비트코인 지금 롱 들어가도 될까?", "coin", None, False)
    assert o[0] in roster.MEMBERS["coin"] and o[-3:] == ["devil", "risk", "strat"]
    o = office._speaker_order("새 매매법 만들어서 백테스트 해줘", "quant", None, True)
    assert "qa" in o and len(o) <= 4 and o[-1] == "strat"                 # 사용자 질문은 최대 4명
    o = office._speaker_order("@윤슬 알트 어때", "hq", None, False)
    assert o[0] == "alt"
    assert office._speaker_order("안녕", "data", None, False) == ["sns"]     # 일상 질문은 한 명


def test_ko_only_and_think():
    t = office.ko_only("We need to answer the user carefully and think about everything here.\n\n💭 차트를 먼저 봅니다.\n지금은 관망입니다.")
    think, body = office.split_think(t)
    assert think == "차트를 먼저 봅니다." and body == "지금은 관망입니다." and "We need" not in t


def test_normalize_spec_tolerates_ai_json():
    from app.strategy import StrategySpec, validate
    d = office.normalize_spec({**STRAT, "indicators": STRAT["indicators"] + [{"id": "bbx", "type": "bollinger", "params": {"length": "20"}}]})
    sp = StrategySpec.model_validate(d)
    assert sp.long_entry.conditions[0].op == "crosses_above" and sp.short_entry.conditions[0].right == "s"
    assert sp.indicators[-1].type == "bb" and sp.risk.leverage == 3 and sp.risk.fee_pct == 0.04
    assert validate(sp) == []


def test_meeting_with_tool_call(fake_ai):
    m = office.enqueue("코인-브리핑", "coin", "지금 비트코인·이더리움 상황 점검", "auto", ["coin_spot", "coin_fut"], wait=True)
    agents = [e for e in office.LOG if e["kind"] == "agent" and e.get("meeting") == m["id"]]
    assert [e["agent"] for e in agents] == m["order"] and m["order"][-1] == "strat"
    first = agents[0]
    assert first["steps"] and first["steps"][0]["name"] == "market_quote" and first["steps"][0]["status"] == "done"
    assert all(e["think"] for e in agents) and all("We need" not in e["text"] for e in agents)
    assert any(e["kind"] == "alert" for e in office.LOG)


def test_research_job_backtests_and_tracks(fake_ai):
    office.job_research()
    bt = [e for e in office.LOG if e["kind"] == "bt"]
    assert len(bt) == 1 and bt[0]["scen"] and bt[0]["grade"] and len(bt[0]["reasons"]) >= 4
    assert office.ST["research"][-1]["name"] == STRAT["name"]
    if bt[0]["pass"] and bt[0]["grade"] != "취약":
        assert office.ST["bots"] and "추적 중" in office.book_text()
    assert any("검증 관문" in s and "연구 카드" in s for s, _ in fake_ai)
    office.job_research()                                               # 두 번째는 세라 · 커스텀 지표 과제 (수식 문법이 프롬프트에 들어간다)
    assert office.ST["research"][-1]["author"] == "qb"
    assert any("사용자 수식 지표" in s and "이번 과제: 커스텀 지표" in s for s, _ in fake_ai)


def test_forecast_ledger_and_scoring(fake_ai):
    office.job_forecast()
    fc = office.ST["forecasts"]
    assert {f["asset"] for f in fc} >= {"비트코인", "이더리움"} and all(f["p0"] for f in fc)
    for f in fc:
        f["due"] = time.time() - 1
        f["p0"] = f["p0"] * 0.98                                       # 그 뒤 2% 올랐다고 가정
    out = office.score_forecasts()
    assert out and all(f["result"] for f in fc)
    btc = next(f for f in fc if f["asset"] == "비트코인")
    eth = next(f for f in fc if f["asset"] == "이더리움")
    assert btc["result"] == "hit" and eth["result"] == "miss"
    s = office.forecast_score()
    assert s["n"] == len(fc) and s["brier"] is not None


def test_ml_job_posts_card(fake_ai):
    office.ST["ml_i"] = 1                                               # ETH 1h · logreg
    office.job_ml()
    card = next(e for e in office.LOG if e["kind"] == "ml")
    assert card["edge"] in ("edge", "weak", "none") and "판정" in card["text"]
    assert any("머신러닝" in n or "로지스틱" in n for n in office.ST["notes"]["quant"])


def test_retro_and_task_flow(fake_ai):
    office.ST["retro_i"] = 1                                            # quant
    office.job_retro()
    assert "검증 구간 거래 수를 먼저 본다" in office.ST["notes"]["quant"]
    b = office.ST["backlog"][-1]
    assert b["title"] == "ETH 4시간 역추세 재시험" and b["owner"] == "qb"
    office.job_task()
    assert b["status"] == "done" and b["result"]


def test_chatter_can_call_meeting(fake_ai):
    office.RT["seen"] = {"coin_fut": [{"icon": "📈", "text": "BTC 펀딩 상승", "t": time.time()}]}
    office.RT["queue"].clear()
    office.chatter()
    lines = [e for e in office.LOG if e["kind"] == "agent" and e.get("chat")]
    assert len(lines) == 3 and any(e["kind"] == "divider" and "잡담에서" in (e.get("text") or "") for e in office.LOG) or office.RT["queue"]


def test_api_state_and_ask(fake_ai):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/office/roster").json()
    assert len(r["agents"]) == 277 and len(r["teams"]) == 27
    office.RT["queue"].clear()
    c.post("/api/office/ask", json={"text": "비트코인 지금 롱 어때?", "room": "coin"})
    st = c.get("/api/office/state?since=0").json()
    assert any(e["kind"] == "user" for e in st["log"]) and st["queue"] >= 1 and "board" in st
    assert c.post("/api/office/cfg", json={"every": 60}).json()["every"] == 60
    office.set_cfg({"every": 30})
