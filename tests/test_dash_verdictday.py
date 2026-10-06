"""판정 날 시계 (review 10/06 fix 1 "판정 날 아침 09:00부터 결과 대신 '2번째 판정 · 30일 남음'", change 13 "D-29와 D+0 / 30이
나란히", additions 2 "판정 결과가 나온 뒤" and 13 "판정 기계 준비됐나 · 30일 길 이정표"; paperbot/dash/more/verdictday.py).

The clock is simulated at 11/04 08:59, 09:00, 09:05 (before the checkpoint job ran), 09:36 (the job waited for the runner's
state), 09:40 (the job failed), 10:00 (the snapshot is frozen, the bots are running), 10:41 (no trace at all), after the
job wrote the verdict and on the next days, for every place that shows the countdown or the verdict: the clock itself,
/api/summary (next_checkpoint, verdict_clock, restart: the top chip's data), restart_banner, the 자는 동안 sheet
(more/since.py), the story (more/story.py), the race (more/flow.py), 졸업 길 (more/gradpath.py), /api/v4/verdictday and
the page modules (core/verdictday.js, screens/checkpoint*.js) in node. checkpoint.db is always in a shape the real
checkpoint job leaves (paperbot/checkpoint.py functions, read-only use: open_out, run_due, freeze_snapshot,
store_snapshot, main's own error path), paper3.db the runner's (tests/test_checkpoint._paper_db).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import time

import pytest

from paperbot import checkpoint as ck
from paperbot.dash.more import verdictday as V
from test_checkpoint import BR, S, SPECS, _LenientCells, _minutes_for, _paper_db, _trades

DAY, H, MIN = 86_400_000, 3_600_000, 60_000
START = 1_791_212_400_000                 # 2026-10-05 15:00 UTC: the real v4 run's first account (00:00 KST 10/06)
CP1 = START - START % DAY + 30 * DAY      # 2026-11-04 00:00 UTC = 09:00 KST: the first verdict
CP2 = CP1 + 30 * DAY                      # 2026-12-04 09:00 KST
DATE1 = "2026-11-04"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


@pytest.fixture(autouse=True)
def _cells(monkeypatch):
    monkeypatch.setattr(ck, "_P_BEST_CELLS", _LenientCells(ck.p_best_cells()))


def _paper(folder, day_state=True) -> str:
    """paper3.db written the way the runner writes it: a 30-day run started 10/05 15:00 UTC, the 09:00 KST state of 11/04
    (``day:2026-11-04``) unless ``day_state`` is False (the runner has not reached that minute yet)."""
    path = os.path.join(str(folder), "paper3.db")
    lo = START
    accts = {
        "GOOD@1h": {"created": START, "wallet": 400_000.0, "trades": _trades(40, lo, CP1, 9875.0), "signals": 400},
        "NOISE@1h": {"created": START, "wallet": 5_050.0, "trades": _trades(40, lo, CP1, 1.25), "signals": 400},
        "FEW@1h": {"created": START, "wallet": 9_000.0, "trades": _trades(29, lo, CP1, 100.0), "signals": 300},
        "GOOD@4h": {"created": START, "wallet": 400_000.0, "trades": _trades(40, lo, CP1, 9875.0), "signals": 100},
        "F3_BOS@1h": {"created": START, "kind": "ds200", "wallet": 400_000.0, "trades": _trades(40, lo, CP1, 9875.0),
                      "signals": 400},
        "RANDOM_1@1h": {"created": START, "kind": "random", "wallet": 3_000.0, "trades": _trades(35, lo, CP1, -57.0),
                        "signals": 300},
    }
    _paper_db(path, accts, CP1)
    if not day_state:
        c = sqlite3.connect(path)
        c.execute("DELETE FROM state WHERE k = ?", ("day:" + DATE1,))
        c.commit()
        c.close()
    return path


_VERDICT: dict = {}


@pytest.fixture(scope="module", autouse=True)
def _drop_verdict_world():
    yield
    d = _VERDICT.pop("dir", None)
    if d:
        shutil.rmtree(d, ignore_errors=True)


def _verdict_world(tmp_path) -> tuple:
    """The 'verdict' state built once per test run (run_due on 30 days of 1m bars takes seconds) and copied."""
    if "dir" not in _VERDICT:
        import tempfile
        d = tempfile.mkdtemp(prefix="vday-")
        old = ck._P_BEST_CELLS
        ck._P_BEST_CELLS = _LenientCells(ck.p_best_cells())
        try:
            paper = _paper(d)
            out = os.path.join(d, "checkpoint.db")
            ck.open_out(out).close()
            v = ck.run_due(paper, out, _minutes_for(), S, BR, SPECS, None, now_ms=CP1 + 2 * H, n_bots=50,
                           log=lambda *_: None)
            assert len(v) == 1 and v[0]["date"] == DATE1
            for name in ("paper3.db", "checkpoint.db"):        # one file each (no WAL left behind)
                c = sqlite3.connect(os.path.join(d, name))
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                c.close()
        finally:
            ck._P_BEST_CELLS = old
        _VERDICT["dir"] = d
    for name in ("paper3.db", "checkpoint.db"):
        shutil.copy(os.path.join(_VERDICT["dir"], name), str(tmp_path / name))
    return str(tmp_path / "paper3.db"), str(tmp_path / "checkpoint.db")


def _state(tmp_path, which: str, monkeypatch=None):
    """(paper3.db, checkpoint.db) with checkpoint.db as the job leaves it:
    none     no file (the job never ran on this server)
    empty    the schema only (every hourly run before a checkpoint is due creates it)
    wait     the 09:35 run found no ``day:<date>`` state yet: job_log '30일 판정 대기' (run_due's own line)
    error    the 09:35 run failed before freezing (Binance unreachable): job_log '30일 판정 오류' (main's own except path)
    snap     the snapshot is frozen and hashed, the coin-flip bots are running (no verdict row yet)
    verdict  the verdict is stored (run_due, 50 bots)"""
    if which == "verdict":
        return _verdict_world(tmp_path)
    paper = _paper(tmp_path, day_state=which != "wait")
    out = str(tmp_path / "checkpoint.db")
    if which == "none":
        return paper, out
    ck.open_out(out).close()
    if which == "wait":
        assert ck.run_due(paper, out, _minutes_for(), S, BR, SPECS, None, now_ms=CP1 + 35 * MIN, n_bots=20,
                          log=lambda *_: None) == []
    elif which == "error":
        import paperbot.live as LIVE

        def down():
            raise ConnectionError("binance unreachable")
        monkeypatch.setattr(LIVE, "_rest", down)
        monkeypatch.setattr(ck.time, "time", lambda: (CP1 + 35 * MIN) / 1000)
        with pytest.raises(ConnectionError):
            ck.main(["run", "--db", paper, "--out", out, "--no-notify"])
        monkeypatch.undo()
        monkeypatch.setattr(ck, "_P_BEST_CELLS", _LenientCells(ck.p_best_cells()))
    elif which == "snap":
        conn = ck.ro_connect(paper)
        snap = ck.freeze_snapshot(conn, CP1, settings=S)
        conn.close()
        o = ck.open_out(out)
        ck.store_snapshot(o, snap, CP1 + 36 * MIN)
        o.close()
    return paper, out


def _clock(paper, out, now):
    return V.clock(START, now, V.read_ledger(out), V.day_state_reader(paper))


# ---------------------------------------------------------------- the clock at each moment of the verdict morning
def test_0859_is_still_the_countdown(tmp_path):
    paper, out = _state(tmp_path, "empty")
    c = _clock(paper, out, CP1 - MIN)
    assert (c["k"], c["ts"], c["due"], c["state"], c["n"], c["left"]) == (1, CP1, False, "before", 29, 1)
    assert c["line_ko"] == "30일 중 29일 지남 · 판정 오늘 09:00 (11/04)"          # never '판정까지 1일' for one minute
    assert V.clock(START, CP1 - DAY + MIN, V.read_ledger(out))["line_ko"] == "30일 중 29일 지남 · 판정 내일 09:00 (11/04)"
    assert V.clock(START, START, None)["line_ko"] == "30일 중 0일 지남 · 판정까지 30일 (11/04 09:00)"


@pytest.mark.parametrize("which", ["none", "empty"])
@pytest.mark.parametrize("at", [0, 5 * MIN])
def test_0900_and_0905_keep_the_first_verdict_while_the_job_has_not_run(tmp_path, which, at):
    paper, out = _state(tmp_path, which)
    c = _clock(paper, out, CP1 + at)
    assert (c["k"], c["ts"], c["due"], c["state"], c["late"]) == (1, CP1, True, "waiting_job", False)
    assert c["db"] == ("missing" if which == "none" else "ok")
    assert c["saved_ts"] == CP1                                  # the runner saved its 09:00 state (paper3.db)
    assert c["line_ko"] == "30일 판정 날 · 09:35에 계산 시작" and c["chip_ko"] == {"main": "판정 날", "opt": " · 결과 계산 중"}
    assert "12/04" not in json.dumps(c, ensure_ascii=False) and "2번째" not in c["line_ko"]


def test_the_job_waits_for_the_runner_state(tmp_path):
    paper, out = _state(tmp_path, "wait")
    c = _clock(paper, out, CP1 + 36 * MIN)
    assert (c["k"], c["due"], c["state"], c["saved_ts"]) == (1, True, "waiting_state", None)
    assert c["wait_ts"] == CP1 + 35 * MIN and c["line_ko"] == "30일 판정 날 · 봇의 09:00 상태 저장을 기다리는 중"


def test_a_failed_job_is_a_red_state_never_a_new_countdown(tmp_path, monkeypatch):
    paper, out = _state(tmp_path, "error", monkeypatch)
    led = V.read_ledger(out)
    assert led["db"] == "ok" and [x["kind"] for x in led["log"][DATE1]] == ["error"]
    c = V.clock(START, CP1 + 40 * MIN, led, V.day_state_reader(paper))
    assert (c["k"], c["due"], c["state"], c["error_kind"]) == (1, True, "failed", "ConnectionError")
    assert c["next_try_ts"] == CP1 + 95 * MIN                    # the hourly :35 retry
    assert c["chip_ko"]["opt"] == " · 확인 필요" and "오류" in c["line_ko"]


def test_the_snapshot_frozen_means_computing(tmp_path):
    paper, out = _state(tmp_path, "snap")
    c = _clock(paper, out, CP1 + H)
    assert (c["k"], c["due"], c["state"], c["snapshot_ts"]) == (1, True, "computing", CP1 + 36 * MIN)
    assert c["line_ko"] == "30일 판정 날 · 동전 봇 비교 계산 중" and not c["late"]
    assert c["chip_ko"]["opt"] == " · 결과 계산 중"


def test_computing_over_four_hours_asks_for_a_look(tmp_path):
    """A run killed by its own limits (MemoryMax / TimeoutStartSec of paperbot-checkpoint.service) leaves no error line:
    'computing' must not go on forever without a word."""
    paper, out = _state(tmp_path, "snap")
    assert not _clock(paper, out, CP1 + 36 * MIN + 4 * H)["late"]
    c = _clock(paper, out, CP1 + 37 * MIN + 4 * H)
    assert (c["state"], c["late"], c["due"], c["k"]) == ("computing", True, True, 1)
    assert c["line_ko"] == "30일 판정 날 · 동전 봇 비교 계산이 4시간 넘게 끝나지 않음"
    assert c["chip_ko"]["opt"] == " · 확인 필요" and "12/04" not in json.dumps(c, ensure_ascii=False)
    assert V.SLOW_MS == 4 * H
    from paperbot.dash.app import Data
    nc = Data(paper, checkpoint_db=out).summary(CP1 + 37 * MIN + 4 * H)["next_checkpoint"]
    assert (nc["k"], nc["due"], nc["state"], nc["late"]) == (1, True, "computing", True)
    js = open(os.path.join(V4, "screens", "server-health.js"), encoding="utf-8").read()
    assert "!!nx.late" in js


def test_no_trace_100_minutes_after_0900_is_late(tmp_path):
    paper, out = _state(tmp_path, "empty")
    assert not _clock(paper, out, CP1 + 99 * MIN)["late"]
    c = _clock(paper, out, CP1 + 101 * MIN)
    assert c["state"] == "waiting_job" and c["late"] and c["line_ko"] == "30일 판정 날 · 판정 작업이 아직 돌지 않았습니다"


def test_an_unreadable_checkpoint_db_is_unknown_never_no_verdict(tmp_path):
    paper, out = _state(tmp_path, "none")
    with open(out, "wb") as fh:
        fh.write(b"this is not a database" * 100)
    led = V.read_ledger(out)
    assert led["db"] == "error"
    c = V.clock(START, CP1 + 3 * H, led)
    assert (c["k"], c["due"], c["state"]) == (1, True, "unknown") and c["line_ko"] == "30일 판정 날 · 판정 기록을 읽지 못함"
    # without any word from checkpoint.db (a caller that passes no ledger) the same: never the next checkpoint
    assert V.clock(START, CP1 + 3 * H, None)["state"] == "unknown"


def test_after_the_job_wrote_the_verdict_and_the_next_days(tmp_path):
    paper, out = _state(tmp_path, "verdict")
    led = V.read_ledger(out)
    c = V.clock(START, CP1 + 2 * H + MIN, led)
    assert (c["k"], c["ts"], c["due"], c["state"], c["of"]) == (2, CP2, False, "before", 60)
    assert c["last"] == {"k": 1, "day": 30, "date": DATE1, "ts": CP1, "stored_ts": CP1 + 2 * H}
    assert c["line_ko"] == "60일 중 30일 지남 · 2번째 판정까지 30일 (12/04 09:00)"
    d1 = V.clock(START, CP1 + DAY + H, led)
    assert (d1["n"], d1["left"], d1["line_ko"]) == (31, 29, "60일 중 31일 지남 · 2번째 판정까지 29일 (12/04 09:00)")
    d2 = V.clock(START, CP1 + 2 * DAY + 9 * H, led)
    assert d2["n"] + d2["left"] == 60 and d2["chip_ko"] == {"main": "32/60일", "opt": " · 2번째 판정 12/04"}
    # the second verdict morning: the same rule again (the first verdict stays 'last')
    c2 = V.clock(START, CP2 + 5 * MIN, led)
    assert (c2["k"], c2["due"], c2["state"], c2["last"]["date"]) == (2, True, "waiting_job", DATE1)
    assert c2["line_ko"] == "60일 판정 날 · 09:35에 계산 시작"


def test_every_hour_of_the_first_season_names_11_04_and_the_numbers_add_up():
    led = {"db": "ok", "verdicts": {}, "snapshots": {}, "log": {}}
    t = START
    while t < CP1 + 3 * DAY:
        c = V.clock(START, t, led)
        assert c["k"] == 1 and c["mmdd"] == "11/04", t
        if not c["due"]:
            assert c["n"] + c["left"] == 30 and c["left"] == -(-(CP1 - t) // DAY), t
        else:
            assert t >= CP1 and c["passed_ko"] == "30일 판정 날", t
        t += 7 * H + 13 * MIN


def test_past_day_180_there_is_no_next_verdict():
    led = {"db": "ok", "verdicts": {ck.day_str(ck.checkpoint_ts(START, k)): ck.checkpoint_ts(START, k) + H for k in range(1, 7)},
           "snapshots": {}, "log": {}}
    c = V.clock(START, ck.checkpoint_ts(START, 6) + 2 * H, led)
    assert c["state"] == "ended" and c["ts"] is None and not c["due"] and c["last"]["day"] == 180
    from paperbot.dash.app import restart_banner
    b = restart_banner(START, ck.checkpoint_ts(START, 6) + 2 * H, led)
    assert b["verdict_mmdd"] == "—" and b["text"].endswith("판정 끝") and b["chip_ko"]["opt"] == " · 판정 끝"


# ---------------------------------------------------------------- every place that shows the countdown or the verdict
def _summary(paper, out, now):
    from paperbot.dash.app import Data
    return Data(paper, checkpoint_db=out).summary(now)


@pytest.mark.parametrize("which,at,k,due,state", [
    ("empty", -MIN, 1, False, "before"), ("none", 0, 1, True, "waiting_job"), ("empty", 5 * MIN, 1, True, "waiting_job"),
    ("wait", 36 * MIN, 1, True, "waiting_state"), ("snap", H, 1, True, "computing"),
    ("verdict", 2 * H + MIN, 2, False, "before"), ("verdict", DAY + H, 2, False, "before")])
def test_summary_and_the_top_chip_data(tmp_path, which, at, k, due, state):
    paper, out = _state(tmp_path, which)
    s = _summary(paper, out, CP1 + at)
    nc, rs, vc = s["next_checkpoint"], s["restart"], s["verdict_clock"]
    assert (nc["k"], nc["due"], nc["state"]) == (k, due, state) and nc["ts"] == (CP1 if k == 1 else CP2)
    assert (rs["checkpoint"], rs["due"], rs["verdict_ts"]) == (k, due, nc["ts"]) and vc["line_ko"] == rs["line_ko"]
    # the chip reads rs.day / rs.of / rs.verdict_mmdd (core/shell.js): the first verdict's date until it is stored
    assert rs["verdict_mmdd"] == ("11/04" if k == 1 else "12/04") and rs["of"] == 30 * k
    if due:
        assert rs["text"] == "새 실험 D+30 · 30일 판정 결과 기다림" and rs["chip_ko"]["main"] == "판정 날"
    elif k == 1:
        assert rs["text"] == "새 실험 D+29 / 30 · 첫 판정 11/04"
    else:
        assert rs["text"].endswith("2번째 판정 12/04")


def test_the_failed_morning_through_the_summary(tmp_path, monkeypatch):
    paper, out = _state(tmp_path, "error", monkeypatch)
    s = _summary(paper, out, CP1 + 3 * H)
    assert s["next_checkpoint"]["state"] == "failed" and s["restart"]["verdict_mmdd"] == "11/04"
    assert s["verdict_clock"]["error_kind"] == "ConnectionError"


def test_restart_banner_with_and_without_the_ledger(tmp_path):
    from paperbot.dash.app import restart_banner
    paper, out = _state(tmp_path, "verdict")
    assert restart_banner(START, CP1 + 5 * MIN)["text"] == "새 실험 D+30 · 30일 판정 결과 기다림"
    b = restart_banner(START, CP1 + 3 * H, V.read_ledger(out))
    assert (b["checkpoint"], b["of"], b["verdict_mmdd"], b["text"]) == (2, 60, "12/04", "새 실험 D+30 · 2번째 판정 12/04")


def test_the_sleep_sheet_says_whether_the_result_is_stored(tmp_path):
    from paperbot.dash.more.since import since
    paper, out = _state(tmp_path, "verdict")
    empty = {"db": "ok", "verdicts": {}, "snapshots": {}, "log": {}}
    c = sqlite3.connect(f"file:{paper}?mode=ro", uri=True)
    try:
        before = since(c, None, CP1 - H, CP1 + 5 * MIN, ledger=empty)
        m = [x for x in before["milestones"] if x["kind"] == "verdict"]
        assert m == [{"kind": "verdict", "k": 1, "ts": CP1, "judged": False, "stored_ts": None}]
        assert before["verdict_ts"] == CP1 and before["verdict_due"] and before["line_ko"] == "30일 판정 날 · 09:35에 계산 시작"
        led = V.read_ledger(out)
        slept = since(c, None, CP1 - 2 * H, CP1 + 3 * H, ledger=led)
        assert [x["judged"] for x in slept["milestones"] if x["kind"] == "verdict"] == [True]
        assert slept["verdict_ts"] == CP2 and slept["verdict_k"] == 2
        # looked at 09:10, back at 12:00: the result stored in between is named
        back = since(c, None, CP1 + 10 * MIN, CP1 + 3 * H, ledger=led)
        assert [x for x in back["milestones"] if x["kind"].startswith("verdict")] == [
            {"kind": "verdict_result", "k": 1, "ts": CP1 + 2 * H, "cp_ts": CP1}]
        # checkpoint.db unreadable: the verdict day is named without a claim either way (never '계산 중' as a fact)
        bad = since(c, None, CP1 - H, CP1 + 5 * MIN, ledger={"db": "error", "verdicts": {}, "snapshots": {}, "log": {}})
        assert [x["judged"] for x in bad["milestones"] if x["kind"] == "verdict"] == [None]
        none = since(c, None, CP1 - H, CP1 + 5 * MIN, ledger={"db": "missing", "verdicts": {}, "snapshots": {}, "log": {}})
        assert [x["judged"] for x in none["milestones"] if x["kind"] == "verdict"] == [False]
    finally:
        c.close()
    js = open(os.path.join(V4, "core", "since.js"), encoding="utf-8").read()
    assert "m.judged == null" in js and "결과 기록을 읽지 못함" in js


def test_the_story_and_the_race_and_the_path(tmp_path):
    from paperbot.dash.app import Data
    from paperbot.dash.more import flow as F
    from paperbot.dash.more import gradpath as GP
    from paperbot.dash.more.story import story
    paper, out = _state(tmp_path, "verdict")
    empty_dir = tmp_path / "e"
    empty_dir.mkdir()
    shutil.copy(paper, empty_dir / "paper3.db")
    c = sqlite3.connect(f"file:{paper}?mode=ro", uri=True)
    try:
        st = story(c, None, None, CP1 + 5 * MIN, {"db": "ok", "verdicts": {}, "snapshots": {}, "log": {}})
        assert (st["verdict_ts"], st["verdict_due"], st["verdict_k"], st["days_left"]) == (CP1, True, 1, 0)
        st2 = story(c, None, None, CP1 + 3 * H, V.read_ledger(out))
        assert (st2["verdict_ts"], st2["verdict_due"], st2["verdict_k"]) == (CP2, False, 2)
    finally:
        c.close()
    assert F.Flow(Data(str(empty_dir / "paper3.db")))._next_verdict(START, CP1 + 5 * MIN) == (1, CP1)
    assert F.Flow(Data(paper, checkpoint_db=out))._next_verdict(START, CP1 + 3 * H) == (2, CP2)
    # 졸업 길: the verdict day without a record says so, never '12/04 첫 판정'
    nc = Data(str(empty_dir / "paper3.db")).summary(CP1 + 5 * MIN)["next_checkpoint"]
    assert GP.overdue(nc, False)
    v = GP.verdict_stage({"ready": False}, {}, nc, CP1 + 5 * MIN, 30)
    assert v["when_ko"] == "11/04 첫 판정 날 · 판정 기록 기다림" and "12/04" not in json.dumps(v, ensure_ascii=False)
    late = Data(str(empty_dir / "paper3.db")).summary(CP1 + DAY + H)["next_checkpoint"]
    v = GP.verdict_stage({"ready": False}, {}, late, CP1 + DAY + H, 30)
    assert v["when_ko"] == "첫 판정일 지남 · 판정 기록 기다림" and "12/04" not in json.dumps(v, ensure_ascii=False)
    early = Data(str(empty_dir / "paper3.db")).summary(CP1 - MIN)["next_checkpoint"]
    assert not GP.overdue(early, False)
    assert GP.verdict_stage({"ready": False}, {}, early, CP1 - MIN, 30)["when_ko"] == "11/04 첫 판정 (오늘 09:00)"
    week = Data(str(empty_dir / "paper3.db")).summary(CP1 - 7 * DAY + H)["next_checkpoint"]
    assert GP.verdict_stage({"ready": False}, {}, week, CP1 - 7 * DAY + H, 30)["when_ko"] == "11/04 첫 판정 (7일 남음)"


# ---------------------------------------------------------------- the routes, the clock moved
def _client(paper, out, monkeypatch, now, timers=None):
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app
    monkeypatch.setattr(V, "timers", lambda runner=None: timers or {"ready": True, "available": False, "reason": "test", "jobs": {}})
    monkeypatch.setattr(time, "time", lambda: now / 1000)
    return TestClient(create_app(paper, None, b"s" * 32, checkpoint_db=out, candles=lambda s, i, n: []))


def test_routes_on_the_verdict_morning(tmp_path, monkeypatch):
    paper, out = _state(tmp_path, "snap")
    c = _client(paper, out, monkeypatch, CP1 + H)
    s = c.get("/api/summary").json()
    assert s["next_checkpoint"]["due"] and s["restart"]["verdict_mmdd"] == "11/04"
    assert c.get("/api/checkpoint").json() == {"ready": False}
    v = c.get("/api/v4/verdictday").json()
    assert v["clock"]["state"] == "computing" and v["meeting"] is None and v["ledger"]["db"] == "ok"
    assert v["machine"]["level"] == "unknown" and v["machine"]["rehearsal"]["state"] == "missing"
    assert [m["kind"] for m in v["milestones"] if m["kind"] in ("verdict", "next")] == ["verdict", "next"]


def test_routes_after_the_verdict(tmp_path, monkeypatch):
    paper, out = _state(tmp_path, "verdict")
    c = _client(paper, out, monkeypatch, CP1 + 3 * H)
    assert c.get("/api/checkpoint").json()["ready"]
    v = c.get("/api/v4/verdictday").json()
    assert v["clock"]["k"] == 2 and v["clock"]["last"]["date"] == DATE1
    for _ in range(50):
        a = c.get("/api/v4/verdictday/after").json()
        if not a.get("pending"):
            break
        time.sleep(0.1)
    assert a["ready"] and a["date"] == DATE1 and a["order"] == list(V.CHECK_IDS)
    ids = [x["account_id"] for x in a["accounts"]]
    assert ids == ["GOOD@1h"]                               # the 1차 합격 of the 36; DeepSeek only as a count
    assert "F3_BOS@1h" not in json.dumps(a) and a["ds_passed"] == sum(
        1 for r in ck.dashboard_view(out)["rows"] if r["group"] == "ds200" and r["status"] in (ck.PASS1, ck.PASS2))
    g = a["accounts"][0]
    assert g["in_readiness"] and set(g["conditions"]) == set(V.CHECK_IDS)
    assert g["conditions"]["trades200"]["v"] == "not_yet"              # 40 trades < 200
    assert g["conditions"]["cost_ratio"]["v"] == "unknown" and g["conditions"]["testnet"]["v"] == "unknown"


# ---------------------------------------------------------------- 판정 기계 and the road's milestones
def test_rehearsal_summaries_say_only_whether_it_ran(tmp_path):
    from paperbot import checkpoint_preview as CPV
    folder = tmp_path / "rehearsal"
    folder.mkdir()
    t0 = time.mktime(time.strptime("2026-10-28 03:30", "%Y-%m-%d %H:%M")) - time.timezone
    ok = CPV.summary_of({"accounts": {}, "tested": 120, "counts": {"1차 합격": 3}, "runtime_s": 1400.0}, as_of="2026-10-28",
                        days=23, out="x", started=t0, finished=t0 + 1500, status="ok", min_trades=10, bots=2000)
    bad = CPV.summary_of(None, as_of="2026-10-21", days=16, out="y", started=t0 - 7 * 86400, finished=t0 - 7 * 86400 + 60,
                         status="failed", error="RuntimeError: brackets call failed", bots=2000)
    CPV._write_json(str(folder / "rehearsal-20261021T033000Z.json"), bad)
    CPV._write_json(str(folder / "rehearsal-20261028T033000Z.json"), ok)
    CPV._write_json(str(folder / "latest.json"), ok)
    rh = V.rehearsals(str(folder))
    assert [r["status"] for r in rh["runs"]] == ["failed", "ok"] and rh["runs"][0]["error_kind"] == "RuntimeError"
    assert rh["runs"][1]["projected_real_s"] == pytest.approx(1400.0 * ck.N_BOTS / 2000)
    assert "tested" not in json.dumps(rh) and "1차 합격" not in json.dumps(rh, ensure_ascii=False)   # never its numbers
    c = V.clock(START, CP1 - 5 * DAY, {"db": "ok", "verdicts": {}, "snapshots": {}, "log": {}})
    on = {"available": True, "jobs": {"paperbot-checkpoint": {"state": "on", "ok": True}, "paperbot-rehearsal": {"state": "on"}}}
    assert V.machine(rh, on, c)["level"] == "ok" and V.machine(rh, on, c)["projected_s"] == pytest.approx(7000.0)
    off = {"available": True, "jobs": {"paperbot-checkpoint": {"state": "off"}}}
    assert V.machine(rh, off, c)["level"] == "bad"
    assert V.machine(rh, {"available": False, "reason": "systemctl 없음"}, c)["level"] == "unknown"
    failed_last = {"state": "ok", "runs": rh["runs"][::-1]}
    assert V.machine(failed_last, on, c)["level"] == "warn"
    assert V.machine(failed_last, {"available": False, "reason": "systemctl 없음"}, c)["level"] == "warn"   # its own file says so
    assert V.rehearsals(str(tmp_path / "nope")) == {"state": "missing", "runs": []}


def test_road_milestones_of_the_first_season():
    c = V.clock(START, START + 3 * DAY, {"db": "ok", "verdicts": {}, "snapshots": {}, "log": {}})
    ms = V.milestones(c, [{"status": "ok", "ts": START - START % DAY + 2 * DAY + 3 * H + 30 * MIN}])
    kinds = [(m["kind"], ck.day_str(m["ts"])) for m in ms]
    weds = [d for k, d in kinds if k == "rehearsal"]
    assert weds == ["2026-10-07", "2026-10-14", "2026-10-21", "2026-10-28", "2026-11-04"]
    by = {(m["kind"], ck.day_str(m["ts"])): m for m in ms}
    assert by[("rehearsal", "2026-10-07")]["ko"] == "판정 연습 12:30 · 정상 끝남"
    assert by[("rehearsal", "2026-11-04")]["ko"] == "판정 연습 없음 (판정 날이라 건너뜀)"      # deploy: skipped on a verdict day
    assert by[("rehearsal", "2026-11-04")]["skip"] and not by[("rehearsal", "2026-10-28")]["skip"]
    assert f"{ck.REHEARSAL_BOTS:,}개" in by[("rehearsal", "2026-10-14")]["ko"]
    dst = by[("dst", "2026-11-01")]
    assert dst["ts"] == ck._nth_sunday(2026, 11, 1) * DAY + 6 * H and "1시간 늦게" in dst["ko"]
    assert ck.et_offset_minutes(dst["ts"] - 1) == -240 and ck.et_offset_minutes(dst["ts"]) == -300
    assert "09:35" in by[("verdict", DATE1)]["ko"] and by[("next", "2026-12-04")]["ts"] == CP2
    # on the verdict day after the result: the done verdict and the next season's marks
    after = V.milestones(V.clock(START, CP1 + 3 * H, {"db": "ok", "verdicts": {DATE1: CP1 + 2 * H}, "snapshots": {}, "log": {}}))
    v = [m for m in after if m["kind"] == "verdict"]
    assert [(m["ts"], m.get("done", False)) for m in v] == [(CP1, True), (CP2, False)] and "결과 저장 11:00" in v[0]["ko"]


def test_the_job_messages_the_ledger_reads_are_the_checkpoint_jobs_own():
    src = open(os.path.join(ROOT, "paperbot", "checkpoint.py"), encoding="utf-8").read()
    assert '일 판정 대기 · ' in src and '일 판정 오류 · ' in src and '\\n\\n오류: {type(exc).__name__}' in src
    assert V.JOB_MINUTE == 35 and "*:35:00 UTC" in open(os.path.join(ROOT, "deploy", "paperbot-checkpoint.timer")).read()
    assert "Wed *-*-* 03:30:00 UTC" in open(os.path.join(ROOT, "deploy", "paperbot-rehearsal.timer")).read()


# ---------------------------------------------------------------- the page modules in node
def _node(module, body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    url = "file://" + os.path.join(V4, module)
    r = subprocess.run([node, "--input-type=module", "-e",
                        "globalThis.localStorage = {getItem() { return null; }, setItem() {}, removeItem() {}};\n"
                        f"const m = await import('{url}');\n" + body], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_page_clock_words(tmp_path):
    paper, out = _state(tmp_path, "snap")
    clocks = {"before": V.clock(START, CP1 - 29 * DAY + 3 * H, None), "last": V.clock(START, CP1 - 3 * H, None),
              "eve": V.clock(START, CP1 - 13 * H, None),
              "snap": _clock(paper, out, CP1 + H), "wait": V.clock(START, CP1 + 5 * MIN, V.read_ledger(out)),
              "unknown": V.clock(START, CP1 + 5 * MIN, None)}
    clocks["wait"] = {**clocks["wait"], "state": "waiting_job", "snapshot_ts": None, "saved_ts": CP1}
    clocks["failed"] = {**clocks["snap"], "state": "failed", "error_kind": "ConnectionError"}
    clocks["slow"] = {**clocks["snap"], "late": True, "now": clocks["snap"]["snapshot_ts"] + 5 * H}
    now = {k: c["now"] for k, c in clocks.items()}
    out_ = _node("core/verdictday.js", f"const C = {json.dumps(clocks)}; const N = {json.dumps(now)}; const r = {{}};\n"
                 "for (const k of Object.keys(C)) r[k] = {big: m.bigWords(C[k], N[k]), steps: m.dueSteps(C[k], N[k]).map((s) => s.state),"
                 " notes: m.dueSteps(C[k], N[k]).map((s) => s.note), when: m.whenKo(C[k])};\n"
                 "r.left = m.leftWords(28 * 86400000 + 18 * 3600000 + 59 * 60000); r.line = m.lineKo({verdict_clock: C.snap});\n"
                 "console.log(JSON.stringify(r));")
    assert out_["before"]["big"] == {"big": "29일", "unit": "남음"} and out_["before"]["steps"] == []
    assert out_["last"]["big"] == {"big": "오늘", "unit": "09:00"} and out_["eve"]["big"] == {"big": "내일", "unit": "09:00"}
    assert out_["snap"]["big"]["big"] == "계산 중" and out_["snap"]["steps"] == ["done", "done", "now", "wait"]
    assert out_["wait"]["steps"] == ["done", "wait", "wait", "wait"] and out_["wait"]["notes"][1] == "09:35에 시작"
    assert out_["failed"]["big"]["big"] == "확인 필요" and out_["failed"]["steps"][2] == "bad" and "ConnectionError" in out_["failed"]["notes"][2]
    assert out_["unknown"]["big"]["big"] == "확인 필요" and "done" not in out_["unknown"]["steps"]
    assert out_["slow"]["big"]["big"] == "확인 필요" and out_["slow"]["steps"] == ["done", "done", "bad", "wait"]
    assert out_["slow"]["notes"][2] == "계산 중 · 5시간째 · 너무 오래 걸림"
    assert out_["left"] == "28일 18시간 59분" and out_["line"] == "30일 판정 날 · 동전 봇 비교 계산 중"
    assert out_["snap"]["when"] == "첫 판정 · 11월 4일 (수) 09:00 (한국 시각)"


def test_result_map_groups_and_deepseek_counts(tmp_path):
    paper, out = _state(tmp_path, "verdict")
    view = ck.dashboard_view(out)
    r = _node("screens/checkpoint-after.js", f"const v = {json.dumps(view)};\n"
              "const x = m.mapRows(v, null); console.log(JSON.stringify({tfs: x.tfs, rows: x.rows.map((r) => [r.strategy, Object.keys(r.cells).sort(), r.best])}));")
    assert r["tfs"] == ["15m", "30m", "1h"]
    assert r["rows"][0][0] == "GOOD" and r["rows"][0][2] == 1                # the 1차 합격 first
    assert all(s != "F3_BOS" for s, _c, _b in r["rows"]) and all("4h" not in c for _s, c, _b in r["rows"])


def test_page_sources_keep_one_sentence_and_the_honesty_rules():
    rd = lambda *p: open(os.path.join(V4, *p), encoding="utf-8").read()      # noqa: E731
    ck_js = rd("screens", "checkpoint.js")
    assert "`D-${" not in ck_js and "`D+${x.day}`" not in ck_js and "판정 시각이 지났습니다" not in ck_js
    assert "vday.bigWords" in ck_js and "vday.dueSteps" in ck_js and 'ctx.every(60000, loadVd' in ck_js
    assert "ctx.store.refresh(\"checkpoint\")" in ck_js                         # a stored verdict switches the page at once
    after = rd("screens", "checkpoint-after.js")
    assert "거래는 아무것도 바뀌지 않습니다" in after and "(계좌별로는 보이지 않음)" in after and "없다는 뜻이 아닙니다" in after
    for f in ("checkpoint-after.js", "checkpoint-machine.js"):
        s = rd("screens", f)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "toLocaleString", "Intl.NumberFormat", "eval("):
            assert bad not in s, (f, bad)
    band = rd("core", "verdictday.js")
    assert 'local.set(SEEN, last.date)' in band and "BAND_DAYS = 3" in band
    main = rd("core", "main.js")
    assert "startVerdictBand();" in main and 'href="/static/v4/core/verdictday.css"' in rd("index.html")
    assert "vday.vclock(s0)" in rd("screens", "road-kit.js") and "c.passed_ko" in rd("screens", "home.js")
    sh = rd("screens", "server-health.js")
    assert "`D-${" not in sh and "일 남음" in sh and "nx.due" in sh                # 서버 › 상태 타일: the same clock
    story = rd("screens", "story-pages.js")
    assert "`D-${left}`" not in story and "d.verdict_due" in story
    since = rd("core", "since.js")
    assert "결과 계산 중" in since and "m.judged" in since and "verdict_result" in since
