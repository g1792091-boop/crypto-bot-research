"""Claude 경로를 API 호출 없이 검증 (llm.parse 를 가짜로 대체)."""
from app import agents, config, llm, nl_strategy
from app.agents import AnalystReport, RiskReview, TradeDecision
from app.strategy import Condition, ConditionGroup, IndicatorSpec, StrategySpec


def test_nl_strategy_retries_once_on_invalid_spec(monkeypatch):
    calls = []
    bad = StrategySpec(name="bad", long_entry=ConditionGroup(conditions=[Condition(left="nope", op=">", right="1")]))
    good = StrategySpec(name="good", indicators=[IndicatorSpec(id="rsi", type="rsi")],
                        long_entry=ConditionGroup(conditions=[Condition(left="rsi", op="<", right="30")]))

    def fake_parse(system, user, schema, **kw):
        calls.append(user)
        return bad if len(calls) == 1 else good

    monkeypatch.setattr(config, "provider", lambda: "claude")
    monkeypatch.setattr(llm, "parse", fake_parse)
    spec, engine = nl_strategy.from_text("RSI 30 아래면 롱")
    assert engine == "claude" and spec.name == "good"
    assert len(calls) == 2 and "검증 오류" in calls[1]


def test_agent_team_pipeline_with_llm(monkeypatch):
    seen = []

    def fake_parse(system, user, schema, **kw):
        seen.append(schema)
        if schema is AnalystReport:
            return AnalystReport(stance="bullish", confidence=70, key_points=["x"], summary="s")
        if schema is RiskReview:
            return RiskReview(max_leverage=3, position_pct=10, warnings=[], event_risk=False, summary="r")
        return TradeDecision(action="long", confidence=65, entry=100, stop_loss=98, take_profits=[104],
                             leverage=3, position_pct=10, rationale="t")

    monkeypatch.setattr(config, "provider", lambda: "claude")
    monkeypatch.setattr(llm, "parse", fake_parse)
    out = agents.run_team("BTCUSDT")
    assert out["engine"] == "claude" and out["decision"]["action"] == "long"
    assert seen.count(AnalystReport) == 3 and seen[-1] is TradeDecision
