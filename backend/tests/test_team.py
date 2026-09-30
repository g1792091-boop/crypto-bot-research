"""에이전트 팀: 근거·권한 검사, 규칙 모드 회의, AI 모드(가짜 응답)에서의 대화·검사, 봇 관문, 사람 질문, 적용 권한."""
import json
import time

from fastapi.testclient import TestClient

from app import config, llm
from app.main import app
from app.team import checks, engine as team, rules

c = TestClient(app)


def _wait(run_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = c.get(f"/api/team/runs/{run_id}").json()
        if v["status"] != "running":
            return v
        time.sleep(0.2)
    raise AssertionError("회의가 끝나지 않음")


def _small():
    team.save_settings(coins=["BTCUSDT", "ETHUSDT"], bot_gate=False)


def test_checks_evidence_and_permissions():
    given = {"market": {"BTCUSDT": {"price": 1, "regime": {"4h": {"score": 30}}}}, "strategist": {"allowed": [{"symbol": "BTCUSDT", "direction": "long"}]}}
    assert checks.resolve(given, "market.BTCUSDT.regime.4h.score") == (True, 30)
    assert checks.resolve(given, "strategist.allowed.0.direction") == (True, "long")
    assert checks.resolve(given, "market.ETHUSDT.price")[0] is False
    out, probs = checks.check("analyst", {"message": "m", "headline": "h", "findings": [
        {"claim": "ok", "kind": "fact", "severity": "info", "evidence": ["market.BTCUSDT.price"]},
        {"claim": "없는 경로", "evidence": ["market.XRPUSDT.price"]},
        {"claim": "근거 없음"}]}, given)
    assert [f["claim"] for f in out["findings"]] == ["ok"] and len(probs) == 2
    # 리스크: long 을 both 로 넓히면 거부, none 으로 좁히기는 허용, 확대 조치는 거부
    out, probs = checks.check("risk", {"headline": "h", "risk_level": "normal",
                                       "decisions": [{"symbol": "BTCUSDT", "direction": "both", "evidence": ["strategist.allowed.0"]}],
                                       "actions": [{"action": "increase_leverage", "target": "x", "evidence": ["market.BTCUSDT.price"]}]}, given)
    assert out["decisions"] == [] and out["actions"] == [] and any("확대" in p for p in probs)
    out, _ = checks.check("risk", {"headline": "h", "risk_level": "??", "decisions": [{"symbol": "BTCUSDT", "direction": "none", "evidence": ["strategist.allowed.0"]}]}, given)
    assert out["decisions"][0]["direction"] == "none" and out["risk_level"] == "caution"
    # 검증관·승인관은 코드 관문 탈락을 뒤집지 못함
    g2 = {"candidates": [{"id": "hyp:0", "gate": {"passed": False}}], "verdicts": [{"candidate": "hyp:0", "verdict": "pass"}]}
    v, _ = checks.check("validator", {"headline": "h", "verdicts": [{"candidate": "hyp:0", "verdict": "pass", "evidence": ["candidates.0.gate"]}]}, g2)
    assert v["verdicts"][0]["verdict"] == "fail"
    a, _ = checks.check("approver", {"headline": "h", "approvals": [{"candidate": "hyp:0", "decision": "approve", "evidence": ["candidates.0.gate"]}]}, g2)
    assert a["approvals"][0]["decision"] == "reject"


def test_rules_every_role_passes_its_own_checks():
    # 규칙 분석의 근거 경로가 그 역할의 입력에 실제로 있는지 (버리는 주장 0)
    pk = {"meta": {"rules": {}}, "market": {"BTCUSDT": {"price": 100, "atr_1h_pct": 1.5, "rsi_1h": 75, "regime": {"15m": {"label": "숏", "score": -40},
          "1h": {"label": "롱", "score": 50}, "4h": {"label": "롱", "score": 60}, "1d": {"label": "롱", "score": 40}}, "verdict": {"label": "롱", "score": 40, "agree": "3/5"}}},
          "book": {"positions": [{"symbol": "BTCUSDT", "side": "long", "leverage": 10, "stop": None}], "max_drawdown_pct": 25, "today": {"trades": 0},
                   "whatif": {"n": 0, "policies": {}, "reproduction_ok": None}, "trades_recent": [], "causes": {}},
          "bots": {}, "ops": {"data_source": "synthetic", "scanner": {"errors": 0}, "ai": "none"}, "knowledge": {"lessons": [], "memos": []}}
    ch = rules.chart(pk)
    assert ch["calls"][0]["bias"] == "long"
    st = rules.strategist({**pk, "analysts": {"chart": ch}})
    assert st["allowed"][0]["direction"] == "long"
    for kind, fn, g in (("analyst", rules.chart, pk), ("strategist", rules.strategist, {**pk, "analysts": {"chart": ch}}),
                        ("analyst", rules.critic, {**pk, "strategist": st}), ("risk", rules.risk, {**pk, "strategist": st}),
                        ("analyst", rules.ops_auditor, pk), ("lead", rules.lead, {**pk, "strategist": st})):
        out, probs = checks.check(kind, fn(g), g)
        assert out is not None and probs == [], (fn.__name__, probs)
    rk = rules.risk({**pk, "strategist": st})
    assert rk["risk_level"] == "caution" and any(a["action"] == "reduce" for a in rk["actions"])   # 손절 없는 포지션 · 낙폭 25%


def test_morning_rules_mode_makes_plan_and_chat():
    _small()
    r = c.post("/api/team/run", json={"pipeline": "morning"}).json()
    assert c.post("/api/team/run", json={"pipeline": "evening"}).status_code == 400      # 동시에 두 회의 불가
    v = _wait(r["id"])
    senders = [m["from"] for m in v["messages"]]
    for rid in ("chart", "flow", "macro", "news", "analog", "strategist", "critic", "risk", "lead"):
        assert rid in senders, rid
    assert senders.index("strategist") < senders.index("critic") < senders.index("risk") < senders.index("lead")
    plan = v["results"]["plan"]
    assert set(plan["allowed"]) == {"BTCUSDT", "ETHUSDT"} and v["results"]["lead"]["summary"]
    assert any(m["kind"] == "result" for m in v["messages"])
    ro = c.get("/api/team/roster").json()
    assert len(ro["roster"]) == 23 and ro["plan"]["run_id"] == r["id"]
    assert {x["team"] for x in ro["roster"]} == set(ro["teams"])


def test_ai_mode_thread_checks_and_narrowing(monkeypatch):
    _small()
    seen = {}

    def fake(system, user, tier="opus", max_tokens=6000, **kw):
        g = json.loads(user)
        role = g["role"]
        seen.setdefault(role, []).append((tier, g))
        if role == "전략가":
            return {"message": "@반론 검토관 BTC 롱, ETH 숏입니다", "headline": "초안", "allowed": [
                {"symbol": "BTCUSDT", "direction": "long", "reason": "r", "evidence": ["market.BTCUSDT.price"]},
                {"symbol": "ETHUSDT", "direction": "short", "reason": "r", "evidence": ["market.ETHUSDT.price"]}], "focus": [], "findings": []}, "", "m-opus"
        if role == "리스크 책임자":
            return {"message": "ETH 는 쉬고 BTC 는 양방향으로", "headline": "주의", "risk_level": "caution", "decisions": [
                {"symbol": "BTCUSDT", "direction": "both", "reason": "넓히기 시도", "evidence": ["strategist.allowed.0"]},
                {"symbol": "ETHUSDT", "direction": "none", "reason": "좁힘", "evidence": ["strategist.allowed.1"]}],
                "actions": [{"action": "keep", "target": "전체", "reason": "-", "evidence": ["meta.rules"]}], "findings": []}, "", "m-opus"
        if role == "팀장":
            return {"message": "정리", "summary": ["a", "b", "c"], "human_actions": [], "glossary": [], "watch_next": []}, "", "m-sonnet"
        return {"message": f"{role} 보고", "headline": "h", "findings": [
            {"claim": "좋은 주장", "kind": "fact", "severity": "info", "evidence": ["meta.coins"]},
            {"claim": "지어낸 숫자", "kind": "fact", "severity": "info", "evidence": ["market.XRPUSDT.price"]}], "calls": [], "proposals": []}, "", "m-sonnet"
    monkeypatch.setattr(config, "provider", lambda: "claude")
    monkeypatch.setattr(llm, "json_call", fake)
    v = _wait(c.post("/api/team/run", json={"pipeline": "morning"}).json()["id"])
    plan = v["results"]["plan"]["allowed"]
    assert plan["BTCUSDT"]["direction"] == "long" and plan["ETHUSDT"]["direction"] == "none"   # 넓히기 거부, 좁히기 반영
    checks_msgs = [m for m in v["messages"] if m["kind"] == "check"]
    assert any("확대 거부" in m["text"] for m in checks_msgs) and any("입력에 없는 경로" in m["text"] for m in checks_msgs)
    assert seen["전략가"][0][0] == "opus" and seen["차트·장세 분석가"][0][0] == "sonnet"          # 역할 등급별 모델
    th = seen["반론 검토관"][0][1]["thread"]
    assert any("BTC 롱, ETH 숏" in x["text"] for x in th)                                          # 앞 대화를 읽음
    assert "strategist" in seen["반론 검토관"][0][1]
    assert "market" not in seen["리스크 책임자"][0][1]                                               # 역할마다 받는 데이터가 다름
    msg = next(m for m in v["messages"] if m["from"] == "chart")
    assert msg["meta"]["source"] == "m-sonnet" and len(msg["data"]["findings"]) == 1


def test_bot_gate_follows_plan():
    team._state["plan"] = {"made": time.time(), "allowed": {"BTCUSDT": {"direction": "short"}}}
    team.save_settings(bot_gate=False)
    assert team.gate_allows("BTCUSDT", "long")
    team.save_settings(bot_gate=True)
    assert not team.gate_allows("BTCUSDT", "long") and team.gate_allows("BTCUSDT", "short")
    assert team.gate_allows("SOLUSDT", "long")                                                      # 계획에 없는 코인은 통과
    team._state["plan"]["made"] = time.time() - 40 * 3600
    assert team.gate_allows("BTCUSDT", "long")                                                      # 오래된 계획은 쓰지 않음
    team.save_settings(bot_gate=False)


def test_human_mention_and_apply_rules():
    ch = c.post("/api/team/chat").json()
    r = c.post(f"/api/team/runs/{ch['id']}/say", json={"text": "@리스크 책임자 BTC 롱 버텨도 돼?"}).json()
    assert r["to"] == "risk"
    time.sleep(0.5)
    v = c.get(f"/api/team/runs/{ch['id']}").json()
    assert v["messages"][-1]["from"] == "risk" and "키" in v["messages"][-1]["text"]
    assert c.post(f"/api/team/runs/{ch['id']}/say", json={"text": "요약해줘"}).json()["to"] == "lead"
    bad = c.post("/api/team/apply", json={"kind": "candidate", "run_id": ch["id"], "candidate": "hyp:0"})
    assert bad.status_code == 400 and "찾지 못" in bad.json()["detail"]


def test_learning_promotion_needs_sample():
    run = team.Run("evening")
    k = team.knowledge()
    k["memos"] = [{"id": "m1", "text": "작은 표본", "n": 5, "seen": 3}, {"id": "m2", "text": "큰 표본", "n": 40, "seen": 2}]
    team._save_knowledge(k)
    team._apply_learning(run, {"memos": [], "promote": [{"memo_id": "m1"}, {"memo_id": "m2"}], "expire": []})
    k = team.knowledge()
    assert [x["text"] for x in k["lessons"]] == ["큰 표본"] and [x["id"] for x in k["memos"]] == ["m1"]
    assert any("승격 거부" in m["text"] for m in run.messages)


def test_hypothesis_to_paper_bot_after_restart(monkeypatch):
    """사용자 보고: 가설 매매법을 페이퍼 봇으로 돌리려는데 오류 → 앱을 다시 켜도 · 승인 전이어도(관찰 봇) · 채팅 가설도 시작된다."""
    from app.main import paper
    _small()
    monkeypatch.setattr(team, "_gate_from_backtest", lambda spec, bars=1500: {"passed": True, "test_trades": 30, "reason": "통과"})
    monkeypatch.setattr(team, "improve_candidates", lambda run: [])
    monkeypatch.setattr(team, "scan_bots", lambda run: {"tried": 0, "top": []})
    v = _wait(c.post("/api/team/run", json={"pipeline": "weekly"}).json()["id"], 300)
    hyps = [x for x in v["results"]["candidates"] if x["kind"] == "hypothesis"]
    assert hyps and "spec" not in hyps[0]
    saved = json.loads((team._dir() / f"run_{v['id']}.json").read_text(encoding="utf-8"))
    assert set(saved["results"]["cand_specs"]) >= {h["id"] for h in hyps}           # 전략도 저장됨
    team.runs[v["id"]] = team.Run.from_dict(saved)                                    # 앱을 다시 켠 상태 (packet 없음)
    appr = {a["candidate"]: a["decision"] for a in v["results"].get("approvals") or []}
    before = len(paper.bots)
    for h in hyps:
        r = c.post("/api/team/apply", json={"kind": "candidate", "run_id": v["id"], "candidate": h["id"]})
        if appr.get(h["id"]) == "approve":
            assert r.status_code == 200 and "시작" in r.json()["msg"]
        else:
            assert r.status_code == 400 and "관찰 봇" in r.json()["detail"]
            r = c.post("/api/team/apply", json={"kind": "candidate", "run_id": v["id"], "candidate": h["id"], "force": True})
            assert r.status_code == 200 and "미검증" in r.json()["msg"]
    r = c.post("/api/team/apply", json={"kind": "hypothesis", "rule": "4시간봉 RSI 14 가 30 아래에서 위로 돌파하면 롱, 손절 2%, 익절 4%",
                                        "symbol": "eth", "interval": "4h", "name": "과매도"})
    assert r.status_code == 200 and "ETHUSDT 4h" in r.json()["msg"]
    bad = c.post("/api/team/apply", json={"kind": "hypothesis", "rule": "아무 뜻 없는 문장", "symbol": "BTCUSDT"})
    assert bad.status_code == 400 and "읽지 못했습니다" in bad.json()["detail"]
    new = [b for b in list(paper.bots.values())[before:]]
    assert len(new) == len(hyps) + 1 and all(b.spec.name.startswith("팀 가설") for b in new)
    for b in new:
        paper.bots.pop(b.id, None)


def test_empty_ai_answer_falls_back_to_rules(monkeypatch):
    """약한 모델이 형식만 맞춘 빈 답({})을 주면 그 에이전트는 규칙 분석으로 대신한다 (가설이 사라지지 않게)."""
    monkeypatch.setattr(config, "provider", lambda: "nvidia")
    calls = []
    monkeypatch.setattr(llm, "json_call", lambda *a, **k: calls.append(1) or ({}, "{}", "nvidia:x"))
    run = team.Run("weekly")
    run.packet = {"meta": team._meta("weekly"), "market": {"BTCUSDT": {"regime": {"1h": {"score": 50}, "4h": {"score": 50}, "1d": {"score": 50}}}}}
    out = team.call_role(run, "researcher", {})
    assert len(calls) == 2 and out and out["hypotheses"]
    assert any("내용 없는 답" in m["text"] for m in run.messages)
