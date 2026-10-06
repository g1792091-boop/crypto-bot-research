"""Review of fix-verdict (판정 날 시계, 판정 뒤 할 일, 판정 기계): the cases the first build missed.

- checkpoint.db's verdict row carries the job RUN's clock (run_due takes ``now`` once when the hourly run starts and
  judge() stores the verdict with it), so a verdict computed from 09:35 for two hours says 09:35. The dashboard reads
  when it was really written (ts + the verdict's own runtime_s): the band's '결과 저장' time, the road's mark and the
  자는 동안 sheet (looked at 10:00 while it computed, back at 12:00: the result must be named).
- the runner's 09:00 state still missing 100 minutes on is a 'look' state, like the job leaving no trace.
- systemd's word on the job (on the server): a run killed by its limits leaves no line in checkpoint.db; a retry after
  an error is computing now.
- the lead's meeting when agents3.db cannot be read is said as such, never '아직 시작 전'.
"""
import json
import os
import sqlite3

import pytest

from paperbot import checkpoint as ck
from paperbot.dash.more import verdictday as V
from test_dash_verdictday import CP1, DATE1, DAY, H, MIN, START, V4, _client, _clock, _node, _paper, _state


def _ledger_with(tmp_path, ts: int, runtime_s) -> str:
    """checkpoint.db made by the checkpoint module itself (open_out: its schema and triggers) holding one verdict row
    the way judge() writes it: (date, ts = the run's now, sha, data with runtime_s)."""
    out = str(tmp_path / "checkpoint.db")
    o = ck.open_out(out)
    data = {"date": DATE1, "cp_ts": CP1, "day": 30, "accounts": {}, "text": "x"}
    if runtime_s is not None:
        data["runtime_s"] = runtime_s
    with o:
        o.execute("INSERT INTO verdicts VALUES (?,?,?,?)", (DATE1, ts, "0" * 64, ck.canonical(data)))
    o.close()
    return out


def test_the_store_time_is_the_run_start_plus_its_runtime(tmp_path):
    out = _ledger_with(tmp_path, CP1 + 35 * MIN, 7000.0)          # the 09:35 run, 1 h 56 min of coin flips
    led = V.read_ledger(out)
    assert led["verdicts"][DATE1] == CP1 + 35 * MIN and led["done"][DATE1] == CP1 + 35 * MIN + 7_000_000
    c = V.clock(START, CP1 + 3 * H, led)
    assert c["last"]["stored_ts"] == CP1 + 35 * MIN and c["last"]["done_ts"] == CP1 + 35 * MIN + 7_000_000
    ms = V.milestones(c)
    done = [m for m in ms if m["kind"] == "verdict" and m.get("done")][0]
    assert "결과 저장 11:31쯤" in done["ko"] and "09:35" not in done["ko"]


def test_a_verdict_without_runtime_reads_its_row_ts(tmp_path):
    out = _ledger_with(tmp_path, CP1 + 2 * H, None)
    led = V.read_ledger(out)
    assert led["done"][DATE1] == CP1 + 2 * H
    assert V.clock(START, CP1 + 3 * H, led)["last"]["done_ts"] == CP1 + 2 * H


def test_the_sleep_sheet_names_a_result_written_after_a_visit_during_the_computation(tmp_path):
    """Looked at 10:00 (computing since 09:35), back at 12:00: the result written at 11:31 is named, although the row
    says 09:35 (before the 10:00 visit)."""
    from paperbot.dash.more.since import since
    paper = _paper(tmp_path)
    out = _ledger_with(tmp_path, CP1 + 35 * MIN, 7000.0)
    c = sqlite3.connect(f"file:{paper}?mode=ro", uri=True)
    try:
        back = since(c, None, CP1 + H, CP1 + 3 * H, ledger=V.read_ledger(out))
    finally:
        c.close()
    assert [x for x in back["milestones"] if x["kind"].startswith("verdict")] == [
        {"kind": "verdict_result", "k": 1, "ts": CP1 + 35 * MIN + 7_000_000, "cp_ts": CP1}]


def test_the_runner_state_missing_100_minutes_on_asks_for_a_look(tmp_path):
    paper, out = _state(tmp_path, "wait")
    assert not _clock(paper, out, CP1 + 99 * MIN)["late"]
    c = _clock(paper, out, CP1 + 101 * MIN)
    assert (c["state"], c["late"], c["due"], c["k"]) == ("waiting_state", True, True, 1)
    assert c["line_ko"] == "30일 판정 날 · 봇의 09:00 상태 저장이 아직 없음 · 봇이 도는지 확인"
    assert c["chip_ko"]["opt"] == " · 확인 필요" and "12/04" not in json.dumps(c, ensure_ascii=False)
    r = _node("core/verdictday.js", f"const c = {json.dumps(c)};\n"
              "const s = m.dueSteps(c, c.now); console.log(JSON.stringify({st: s.map((x) => x.state), notes: s.map((x) => x.note), "
              "big: m.bigWords(c, c.now)}));")
    assert r["st"] == ["bad", "wait", "wait", "wait"] and r["big"]["big"] == "확인 필요"
    assert "판정 작업이 아직 돌지 않았습니다" not in json.dumps(r, ensure_ascii=False)     # the job did run (it logged the wait)
    js = open(os.path.join(V4, "screens", "checkpoint.js"), encoding="utf-8").read()
    assert 'c.late && c.state === "waiting_state"' in js


def test_systemd_says_a_killed_run_or_a_retry(tmp_path):
    paper, out = _state(tmp_path, "snap")
    snap = _clock(paper, out, CP1 + 2 * H)
    failed = {**snap, "state": "failed", "error_kind": "ConnectionError"}
    waiting = {**_clock(paper, out, CP1 + 2 * H), "state": "waiting_job", "snapshot_ts": None}
    job = lambda **k: {"systemd": True, "job": {"state": "on", "last_ms": CP1 + 95 * MIN, **k}}     # noqa: E731
    cases = {
        "killed": [snap, job(ok=False, running=False, result="oom-kill")],
        "killed_before": [waiting, job(ok=False, running=False, result="timeout")],
        "retry": [failed, job(ok=False, running=True, result="exit-code")],
        "running": [snap, job(ok=True, running=True, result="success")],
        "old_run": [snap, {"systemd": True, "job": {"state": "on", "last_ms": CP1 - 25 * MIN, "ok": False, "running": False}}],
        "off_server": [snap, {"systemd": False, "job": None}],
        "failed_logged": [failed, job(ok=False, running=False, result="exit-code")],
    }
    r = _node("core/verdictday.js", f"const C = {json.dumps(cases)}; const r = {{}};\n"
              "for (const [k, [c, mm]] of Object.entries(C)) { const js = m.jobSays(c, mm); "
              "r[k] = {js, steps: m.dueSteps(c, c.now, js).map((s) => s.state), note: (m.dueSteps(c, c.now, js)[2] || {}).note}; }\n"
              "console.log(JSON.stringify(r));")
    assert r["killed"]["js"]["dead"] and r["killed"]["js"]["ko"] == "메모리 한도로 멈춤" and r["killed"]["steps"][2] == "bad"
    assert "10:35 시작" in r["killed"]["note"] and "메모리 한도로 멈춤" in r["killed"]["note"]
    assert r["killed_before"]["js"]["dead"] and r["killed_before"]["js"]["ko"] == "시간 한도로 멈춤"
    assert r["retry"]["js"] == {"rerun": True, "since": CP1 + 95 * MIN} and r["retry"]["steps"][2] == "now"
    assert "다시 계산 중" in r["retry"]["note"] and "ConnectionError" in r["retry"]["note"]
    for k in ("running", "old_run", "off_server", "failed_logged"):      # nothing to add: the ledger's own words stay
        assert r[k]["js"] is None, k
    assert r["failed_logged"]["steps"][2] == "bad" and "ConnectionError" in r["failed_logged"]["note"]
    js = open(os.path.join(V4, "screens", "checkpoint.js"), encoding="utf-8").read()
    assert "vday.jobSays(c, st.vd && st.vd.machine)" in js and "vday.dueSteps(c, now, js)" in js


def test_the_meeting_when_agents_db_cannot_be_read(tmp_path, monkeypatch):
    paper, out = _state(tmp_path, "verdict")
    c = _client(paper, out, monkeypatch, CP1 + 3 * H)
    agents = os.path.join(os.path.dirname(paper), "agents3.db")
    assert not os.path.exists(agents)                              # the test world has no agents3.db
    v = c.get("/api/v4/verdictday").json()
    assert v["clock"]["last"]["date"] == DATE1 and v["meeting"] == {"error": "agents3.db를 읽지 못함"}
    after = open(os.path.join(V4, "screens", "checkpoint-after.js"), encoding="utf-8").read()
    assert "st.vd.failed ? {failed: true}" in after and "m.error || m.failed" in after


def test_words_the_review_changed():
    ui = open(os.path.join(V4, "core", "ui.js"), encoding="utf-8").read()
    assert "판정 결과를 기다리는 중" in ui and "verdictTs <= Date.now()" in ui      # never '다음 11/04' at 10:00 on 11/04
    band = open(os.path.join(V4, "core", "verdictday.js"), encoding="utf-8").read()
    assert "last.done_ts || last.stored_ts" in band and "dismissed === last.date" in band
    c = V.clock(START, START + 3 * DAY, {"db": "ok", "verdicts": {}, "snapshots": {}, "log": {}})
    dst = [m for m in V.milestones(c) if m["kind"] == "dst"][0]
    assert f"딥시크 세션 매매법 {len(ck.SESSION_RULES)}개" in dst["ko"]
    assert all(s.startswith("F15_") for s in ck.SESSION_RULES)      # DeepSeek's F15 session definitions only


@pytest.mark.parametrize("which", ["empty", "snap"])
def test_the_summary_carries_done_ts_only_after_a_verdict(tmp_path, which):
    from paperbot.dash.app import Data
    paper, out = _state(tmp_path, which)
    s = Data(paper, checkpoint_db=out).summary(CP1 + 2 * H)
    assert s["verdict_clock"]["last"] is None and s["next_checkpoint"]["due"]


def _jobs(**job):
    return {"ready": True, "available": True, "jobs": {"paperbot-checkpoint": {"state": "on", **job}}}


def test_the_server_clock_takes_systemds_word_everywhere(tmp_path, monkeypatch):
    """A run killed by its limits (no line in checkpoint.db): every screen's clock says 확인 필요 at once (the top chip's
    data, the home card's words, the server tile's late), not '계산 중' for 4 hours; a retry after a logged error says
    it is computing again."""
    from paperbot.dash.app import Data
    paper, out = _state(tmp_path, "snap")
    killed = _jobs(last_ms=CP1 + 95 * MIN, ok=False, running=False, result="oom-kill")
    monkeypatch.setattr(V, "timers", lambda runner=None: killed)
    s = Data(paper, checkpoint_db=out).summary(CP1 + 2 * H)
    vc = s["verdict_clock"]
    assert (vc["state"], vc["late"], vc["job"]["dead"], vc["job"]["result"]) == ("computing", True, True, "oom-kill")
    assert vc["line_ko"] == "30일 판정 날 · 판정 작업이 메모리 한도로 멈춤 · 매시 35분에 다시 시도"
    assert s["next_checkpoint"]["late"] and s["restart"]["chip_ko"]["opt"] == " · 확인 필요"
    # the same run still going, a run that ended well, or one from before the checkpoint: the ledger's own words
    for jb in (_jobs(last_ms=CP1 + 95 * MIN, ok=None, running=True), _jobs(last_ms=CP1 + 95 * MIN, ok=True, running=False),
               _jobs(last_ms=CP1 - 25 * MIN, ok=False, running=False, result="exit-code"),
               {"ready": True, "available": False, "reason": "systemctl 없음", "jobs": {}}):
        monkeypatch.setattr(V, "timers", lambda runner=None, jb=jb: jb)
        c = Data(paper, checkpoint_db=out).summary(CP1 + 2 * H)["verdict_clock"]
        assert (c["state"], c["late"], "job" in c) == ("computing", False, False), jb
        assert c["line_ko"] == "30일 판정 날 · 동전 봇 비교 계산 중"
    # a systemctl that raises never takes the summary down
    def boom(runner=None):
        raise OSError("no systemd")
    monkeypatch.setattr(V, "timers", boom)
    assert Data(paper, checkpoint_db=out).summary(CP1 + 2 * H)["verdict_clock"]["state"] == "computing"


def test_a_retry_after_a_logged_error_is_computing_again(tmp_path, monkeypatch):
    paper, out = _state(tmp_path, "error", monkeypatch)
    led = V.read_ledger(out)
    retry = _jobs(last_ms=CP1 + 95 * MIN, ok=False, running=True, result="exit-code")
    c = V.clock(START, CP1 + 2 * H, led, V.day_state_reader(paper), lambda: retry)
    assert (c["state"], c["job"], c["late"]) == ("failed", {"rerun": True, "dead": False, "since": CP1 + 95 * MIN}, False)
    assert c["line_ko"] == "30일 판정 날 · 앞선 계산은 오류 · 지금 다시 계산 중" and c["chip_ko"]["opt"] == " · 결과 계산 중"
    r = _node("core/verdictday.js", f"const c = {json.dumps(c)};\n"
              "console.log(JSON.stringify({big: m.bigWords(c, c.now), js: m.jobSays(c, null), st: m.dueSteps(c, c.now, m.jobSays(c, null)).map((s) => s.state)}));")
    assert r["big"]["big"] == "계산 중" and r["js"] == {"rerun": True, "since": CP1 + 95 * MIN} and r["st"][2] == "now"
    # the logged error with no run going: still the red state
    dead = V.clock(START, CP1 + 2 * H, led, V.day_state_reader(paper), lambda: _jobs(last_ms=CP1 + 95 * MIN, ok=False,
                                                                                      running=False, result="exit-code"))
    assert dead["state"] == "failed" and "job" not in dead and dead["chip_ko"]["opt"] == " · 확인 필요"
