import json
import os
import stat
import subprocess
import sys

import pytest

from paperbot import Brackets, Settings, Signal
from paperbot.agents.__main__ import main as agents_main
from paperbot.agents.budget import BudgetedRunner
from paperbot.agents.packets import evening_packet, slice_for
from paperbot.agents.pipeline import run_evening, ReportStore
from paperbot.agents.roles import EVENING_ROLES, check_output, resolve, system_prompt
from paperbot.agents.runner import (AgentCallError, ClaudeCodeRunner, FakeRunner,
                                    UsageLimitReached, child_env, extract_json)
from paperbot.archive import RECORD_SYMBOLS
from paperbot.ledger import BarStore, RecordingNotifier, record_run
from paperbot.live import make_books
from paperbot.notify import ListNotifier
from paperbot.replay import replay

sys.path.insert(0, os.path.dirname(__file__))
from test_analysis import walk  # noqa: E402

MIN = 60_000
ROLE = {r.rid: r for r in EVENING_ROLES}


@pytest.fixture
def ledger(tmp_path):
    s = Settings()
    db = str(tmp_path / "paper.db")
    bars = walk(2 * 1440)
    sigs = []
    for k, i in enumerate(range(30, len(bars) - 100, 45)):
        b = bars[i]
        side = 1 if k % 2 == 0 else -1
        sigs.append(Signal(b.close_time, "BTCUSDT", "1m", "demo", side,
                           b.close * (1 - side * 0.005),
                           meta={"ctx": {"atr": b.close * 0.002, "regime": "chop"}}))
    brackets = {x: Brackets.example() for x in s.symbols}
    note = RecordingNotifier(db, ListNotifier(), clock_ms=lambda: bars[-10].open_time)
    engines, ledgers = make_books(s, brackets, {}, note, db, "run1")
    replay(s, {"BTCUSDT": bars}, sigs, brackets, {}, engines)
    note.send("WARN", "BTCUSDT gap backfilled")
    for led in ledgers:
        led.close()
    note.close()
    st = BarStore(db)
    st.add(bars)
    st.close()
    return db, bars[-1].close_time + 1


def test_packet_has_both_books_and_ops(ledger):
    db, now = ledger
    p = evening_packet(db, now, boot=100)
    assert set(p["books"]) == {"owner", "recommended"}
    own = p["books"]["owner"]
    assert own["cumulative"]["trades"] > 30
    assert own["today"]["trades"] == len(own["trades_today"]) > 0
    assert own["whatif"]["reproduction_ok"] is True
    assert own["equity"]["available"]
    assert p["ops"]["bars_1m"]["BTCUSDT"]["missing"] == 0
    assert p["ops"]["bars_1m"]["ETHUSDT"]["missing"] == 1440
    assert p["ops"]["alerts"]["by_level"]["WARN"] == 1
    assert any(x["status"] == "ENTERED" for x in p["ops"]["signals"])
    sl = slice_for(p, ("ops", "books.*.today"))
    assert set(sl) == {"meta", "ops", "books"} and set(sl["books"]["owner"]) == {"today"}


def test_check_output_drops_claims_without_valid_evidence():
    given = {"books": {"owner": {"today": {"win_rate": 0.5}}}}
    out = {"headline": "h", "findings": [
        {"claim": "ok", "evidence": ["books.owner.today.win_rate"]},
        {"claim": "made up", "evidence": ["books.owner.today.sharpe"]},
        {"claim": "no evidence"}],
        "proposals": []}
    clean, probs = check_output(ROLE["performance_analyst"], out, given)
    assert [f["claim"] for f in clean["findings"]] == ["ok"] and len(probs) == 2
    assert resolve({"a": [1, {"b": 2}]}, "a.1.b") == (True, 2)
    pol = {"policies": {"TP_1.5R": {"n": 3}, "TP_1": {"5R": 0}}}
    assert resolve(pol, "policies.TP_1.5R.n") == (True, 3)
    assert resolve(pol, "policies.TRAIL_1.5ATR.n")[0] is False


def test_risk_officer_cannot_increase():
    given = {"books": {"owner": {"equity": {"drawdown": 0.1}}}}
    ev = ["books.owner.equity.drawdown"]
    out = {"headline": "h", "risk_level": "caution", "findings": [], "actions": [
        {"action": "increase_leverage", "target": "all", "evidence": ev},
        {"action": "reduce", "target": "demo", "evidence": ev}]}
    clean, probs = check_output(ROLE["risk_officer"], out, given)
    assert [a["action"] for a in clean["actions"]] == ["reduce"]
    assert any("not allowed" in p for p in probs)


def test_prompts_load_for_every_role():
    for r in EVENING_ROLES:
        sp = system_prompt(r)
        assert "절대 규칙" in sp and "JSON" in sp and r.name_ko in sp


def test_pipeline_runs_checks_and_reports(ledger):
    db, now = ledger
    p = evening_packet(db, now, boot=100)
    answers = {
        "performance_analyst": {"headline": "성과", "findings": [
            {"claim": "오늘 승률", "kind": "fact", "severity": "info",
             "evidence": ["books.owner.today.win_rate"]},
            {"claim": "지어낸 숫자", "evidence": ["books.owner.today.sharpe_ratio"]}],
            "proposals": []},
        "pnl_reviewer": "not json at all",
        "risk_officer": {"headline": "낙폭 확인", "risk_level": "caution", "findings": [],
                         "actions": [{"action": "reduce", "target": "demo", "reason": "연속 손실",
                                      "evidence": ["books.owner.equity.drawdown",
                                                   "analysts.performance_analyst.findings.0"]}]},
    }
    runner = FakeRunner(answers, fail={"whatif_analyst": AgentCallError("timeout")})
    store = ReportStore(db)
    note = ListNotifier()
    rep = run_evening(p, runner, store, note, now)
    store.close()
    assert set(rep["failed"]) == {"pnl_reviewer", "whatif_analyst"}
    assert rep["risk"]["risk_level"] == "caution" and rep["risk"]["actions"][0]["action"] == "reduce"
    assert rep["dropped_claims"]["performance_analyst"]
    # Risk officer saw only checked analyst output; lead got failed roles.
    risk_call = [c for c in runner.calls if c["role"] == "risk_officer"][0]
    assert len(risk_call["packet"]["analysts"]["performance_analyst"]["findings"]) == 1
    lead_call = [c for c in runner.calls if c["role"] == "team_lead"][0]
    assert "pnl_reviewer" in lead_call["packet"]["failed_roles"]
    assert [c["model"] for c in runner.calls if c["role"] == "risk_officer"] == ["opus"]
    level, text = note.messages[-1]
    assert level == "WARN" and "오늘의 점검" in text and "주의" in text
    assert "실패/미실행 역할" in text and "근거 검사에서 버린 주장" in text
    own = p["books"]["owner"]
    assert f"오늘 {own['today']['trades']}건" in text  # numbers come from code
    import sqlite3
    rows = sqlite3.connect(db).execute("SELECT role, status FROM agent_reports").fetchall()
    assert ("performance_analyst", "ok") in rows and ("whatif_analyst", "failed") in rows


def test_usage_limit_stops_remaining_calls(ledger):
    db, now = ledger
    p = evening_packet(db, now, boot=100)
    runner = FakeRunner(fail={"performance_analyst": UsageLimitReached("weekly limit")})
    rep = run_evening(p, runner, None, None, now)
    assert [c["role"] for c in runner.calls] == ["ops_auditor", "performance_analyst"]
    assert rep["stopped"] and rep["lead"] is None
    assert "팀장 요약 없음" in rep["telegram"] and "사용량 한도" in rep["telegram"]


class FakeProc:
    def __init__(self, out, code=0, err=""):
        self.stdout, self.returncode, self.stderr = out, code, err


def test_runner_command_env_and_parsing():
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["env"], seen["input"] = cmd, kw["env"], kw["input"]
        return FakeProc(json.dumps({"type": "result", "is_error": False,
                                    "result": 'Here:\n```json\n{"a": 1}\n```', "num_turns": 1}))

    env = {"PATH": "/bin", "HOME": "/root", "CLAUDE_CODE_OAUTH_TOKEN": "t",
           "ANTHROPIC_API_KEY": "sk-should-not-pass", "BINANCE_API_SECRET": "x",
           "TELEGRAM_BOT_TOKEN": "y"}
    r = ClaudeCodeRunner(env=env, run=run)
    res = r.call("sonnet", "sys", "do it", {"role": "x", "n": 1})
    assert res.data == {"a": 1}
    cmd = seen["cmd"]
    assert "--bare" not in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--model") + 1] == "sonnet" and "--safe-mode" in cmd
    assert set(seen["env"]) == {"PATH", "HOME", "CLAUDE_CODE_OAUTH_TOKEN"}
    assert json.loads(seen["input"])["n"] == 1
    assert child_env({"ANTHROPIC_AUTH_TOKEN": "z"}) == {}


def test_runner_maps_errors():
    lim = ClaudeCodeRunner(env={}, run=lambda c, **k: FakeProc(json.dumps(
        {"is_error": True, "result": "You've hit your weekly limit · resets Mon"}), 1))
    with pytest.raises(UsageLimitReached):
        lim.call("sonnet", "s", "i", {})
    bad = ClaudeCodeRunner(env={}, run=lambda c, **k: FakeProc("", 2, "boom"))
    with pytest.raises(AgentCallError):
        bad.call("sonnet", "s", "i", {})

    def slow(c, **k):
        raise subprocess.TimeoutExpired(c, 1)
    with pytest.raises(AgentCallError):
        ClaudeCodeRunner(env={}, run=slow).call("sonnet", "s", "i", {})


def test_runner_real_subprocess_with_stub_binary(tmp_path):
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\n"
                    "if [ -n \"$ANTHROPIC_API_KEY\" ]; then echo leaked; exit 3; fi\n"
                    "cat > /dev/null\n"
                    "echo '{\"type\":\"result\",\"is_error\":false,\"result\":\"{\\\"ok\\\": true}\"}'\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {"PATH": os.environ["PATH"], "ANTHROPIC_API_KEY": "sk-x"}
    res = ClaudeCodeRunner(str(stub), env=env).call("opus", "s", "i", {"x": 1})
    assert res.data == {"ok": True}


def test_extract_json_variants():
    assert extract_json('prose {"a": {"b": "}"}} more') == {"a": {"b": "}"}}
    assert extract_json("no json") is None
    assert extract_json('[1,2] then {"k": 2}') == {"k": 2}


def test_cli_dry_run(ledger, capsys):
    db, _ = ledger
    out = db + ".report.json"
    # The fixture's trades are old, so "today" has none; agents still run by default.
    code = agents_main(["evening", "--ledger", db, "--dry-run", "--out", out])
    rep = json.loads(open(out, encoding="utf-8").read())
    assert code == 0 and not rep["skipped"] and "(dry-run)" in rep["telegram"]
    code = agents_main(["evening", "--ledger", db, "--dry-run", "--skip-no-trade-days",
                        "--out", out])
    rep = json.loads(open(out, encoding="utf-8").read())
    assert code == 0 and rep["skipped"] and "AI 점검은 생략" in rep["telegram"]


def test_no_trade_day_agents_run_by_default_and_skip_is_opt_in(ledger):
    db, now = ledger
    p = evening_packet(db, now + 3 * 86_400_000, boot=50)  # window with no closed trades
    runner = FakeRunner()
    rep = run_evening(p, runner, None, None, now)
    assert len(runner.calls) == 6 and not rep["skipped"]
    pnl_call = [c for c in runner.calls if c["role"] == "pnl_reviewer"][0]["packet"]
    assert "activity" in pnl_call and "market" in pnl_call
    runner = FakeRunner()
    note = ListNotifier()
    rep = run_evening(p, runner, None, note, now, skip_if_no_trades=True)
    assert runner.calls == [] and rep["skipped"]
    level, text = note.messages[-1]
    assert "AI 점검은 생략" in text and "[숫자: 코드 계산]" in text
    assert level == "WARN"  # 1m bars missing for five symbols is still reported


def test_activity_funnel_and_market(ledger):
    db, now = ledger
    p = evening_packet(db, now, boot=50)
    act = p["activity"]
    assert act["run"]["recorded"] is False  # fixture never went through `live run`
    f = act["funnel"]["owner"]
    assert f["signals"] == sum(f["by_status"].values()) > 0
    assert f["by_strategy"]["demo"]["ENTERED"] == f["by_status"]["ENTERED"]
    assert act["trades_today"]["owner"] == p["books"]["owner"]["today"]["trades"]
    m = p["market"]["BTCUSDT"]
    assert m["available"] and m["range_pct"] > 0 and "prev_day_range_pct" in m
    assert m["regime_15m"] in ("trend_up", "trend_down", "box", "chop", "unknown")
    assert p["market"]["ETHUSDT"] == {"available": False}
    assert p["ops"]["bars_1m"]["BTCUSDT"]["minutes_since_last_bar"] == 0
    assert p["ops"]["bars_1m"]["ETHUSDT"]["last_bar_kst"] is None
    record_run(db, "live1", now - 3600_000, {"strategies": [], "books": ["owner"],
                                             "brackets": "file x"})
    run = evening_packet(db, now, boot=50)["activity"]["run"]
    assert run["recorded"] and run["strategies_connected"] == 0 and run["starts_in_window"] == 1


class TokenRunner(FakeRunner):
    def __init__(self, tokens):
        super().__init__()
        self.tokens = tokens

    def call(self, model, system_prompt, instruction, packet):
        res = super().call(model, system_prompt, instruction, packet)
        res.meta = {"usage": {"input_tokens": self.tokens, "output_tokens": 0}}
        return res


def test_daily_call_cap_spans_runs_and_resets_next_day(ledger):
    db, now = ledger
    p = evening_packet(db, now, boot=50)
    clock = {"t": now}
    runner = BudgetedRunner(FakeRunner(), db, max_calls=8, max_tokens=10**9,
                            clock_ms=lambda: clock["t"])
    first = run_evening(p, runner, None, None, now)
    assert first["failed"] == [] and runner.used_today()[0] == 6
    note = ListNotifier()
    second = run_evening(p, runner, None, note, now)
    assert len(runner.runner.calls) == 8  # stopped at the cap, 2 more calls only
    assert second["stopped"].startswith("budget") and len(second["failed"]) == 4
    assert "하루 사용량 상한" in note.messages[-1][1]
    clock["t"] = now + 86_400_000  # next Korea-time day
    assert runner.used_today() == (0, 0)
    assert run_evening(p, runner, None, None, now)["failed"] == []
    runner.close()


def test_daily_token_cap_and_failed_calls_count(ledger):
    db, now = ledger
    p = evening_packet(db, now, boot=50)
    runner = BudgetedRunner(TokenRunner(40_000), db, max_calls=100, max_tokens=100_000,
                            clock_ms=lambda: now)
    rep = run_evening(p, runner, None, None, now)
    assert runner.used_today() == (3, 120_000)  # third call ran past the cap, fourth refused
    assert rep["stopped"].startswith("budget")
    runner.close()
    failing = BudgetedRunner(FakeRunner(fail={"ops_auditor": AgentCallError("x")}), db,
                             max_calls=100, max_tokens=10**9, clock_ms=lambda: now + 5 * 86_400_000)
    failing.call("sonnet", "s", "i", {"role": "performance_analyst"})
    with pytest.raises(AgentCallError):
        failing.call("sonnet", "s", "i", {"role": "ops_auditor"})
    assert failing.used_today()[0] == 2
    failing.close()


def test_cli_refuses_to_call_claude_without_the_subscription_login(ledger, tmp_path):
    db, _ = ledger
    code = agents_main(["evening", "--ledger", db, "--claude-bin", str(tmp_path / "no-such-claude"),
                        "--agents-db", str(tmp_path / "agents.db")])
    assert code == 2 and not os.path.exists(tmp_path / "agents.db")     # no call made, nothing counted


def test_cli_writes_agent_tables_to_agents_db_only(ledger):
    db, _ = ledger
    agents_main(["evening", "--ledger", db, "--dry-run"])
    import sqlite3
    agents_db = os.path.join(os.path.dirname(db), "agents.db")
    assert sqlite3.connect(agents_db).execute("SELECT COUNT(*) FROM agent_reports").fetchone()[0] > 0
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM agent_reports").fetchone()[0] == 0


def test_packet_recording_section_and_mode(tmp_path):
    from test_recorder import CELLS, fill, synth
    from paperbot.archive import MarketArchive
    from paperbot.ledger import BookStore
    from paperbot.recorder import Recorder, _ms
    df = synth()
    market = str(tmp_path / "market.db")
    ledger_db = str(tmp_path / "paper.db")
    arch = MarketArchive(market)
    fill(arch, df)
    ms = _ms(df["ts"])
    books = BookStore(ledger_db, ["BTCUSDT"], clock_ms=lambda: int(ms[-50]))
    books.add([{"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.02", "time": 1}])
    books.close()
    now = int(ms[-1]) + 300_000
    Recorder(arch, ledger_path=ledger_db, cells=CELLS, clock_ms=lambda: now - 1000).run(["BTCUSDT"])
    arch.close()
    p = evening_packet(ledger_db, now, boot=50, market=market)
    assert p["meta"]["mode"]["cells"] == {"trade": 0, "record_only": 164, "excluded": 58}
    rec = p["recording"]
    assert rec["available"] and rec["last_run"]["status"] == "ok"
    assert rec["signals_in_window"]["total"] > 20
    assert rec["signals_in_window"]["by_symbol"] == {"BTCUSDT": rec["signals_in_window"]["total"]}
    assert rec["mismatches_in_window"]["total"] == 0
    cov = rec["coverage_in_window"]
    assert set(cov) == set(RECORD_SYMBOLS) and cov["BTCUSDT"]["missing_5m"] == 0
    assert cov["XRPUSDT"]["bars_5m"] == 0 and cov["XRPUSDT"]["last_5m_bar_kst"] is None
    assert rec["order_book_snapshots_in_window"] == {"BTCUSDT": 1}
    ops = slice_for(p, ROLE["ops_auditor"].inputs)
    lead = slice_for(p, ROLE["team_lead"].inputs)
    assert "recording" in ops and lead["recording"]["signals_in_window"]["total"] > 20
    assert resolve(ops, "recording.coverage_in_window.XRPUSDT.missing_5m")[0]
    none = evening_packet(ledger_db, now, boot=50)
    assert none["recording"]["available"] is False
