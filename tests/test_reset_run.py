"""paperbot/resetrun.py: the agents' side of the clean restart (deploy/paperbot-reset.sh). Fresh databases with the
real schemas (rooms_db.open_agents / open_inbox_rw, committee.ensure, store3.Store3): the agents' memory survives,
the cursors that point into the old paper3.db are reset, open proposals of the old run are closed, backups come
first, and a second run changes nothing."""

import datetime as dt
import json
import os
import sqlite3

import pytest

from paperbot import checkpoint as CP
from paperbot import resetrun as RR
from paperbot.agents import committee as CM
from paperbot.agents import rooms_db as R
from paperbot.agents import triggers as TR
from paperbot.sessions import KST
from paperbot.store3 import Store3

NOW = int(dt.datetime(2026, 10, 4, 22, 10, tzinfo=KST).timestamp() * 1000)
OLD_START = int(dt.datetime(2026, 9, 30, 21, 0, tzinfo=KST).timestamp() * 1000)
# the paper v4 restart text (owners 2026-10-05): written from config.V4_GROUPS, never typed in (no "5분봉 제외")
RESTART_KO = ("실험을 2026-10-04에 처음부터 다시 시작함 (paper v4: $5,000 계좌 331개 = 매매법 36개 × 15분·30분·1시간·4시간 + "
              "딥시크 정의 44개(39개 15분·30분·1시간·4시간, 5개 15분·30분·1시간, 171계좌) + 릴스 5분 단타 1개(5분봉, 자기 청산 "
              "규칙) + 동전 15개(5분봉 3개 포함). 매매법 36개는 5분봉 없음, 5분봉은 릴스와 그 비교용 동전만. 좋은 자리 "
              "50·40배·보통 30·20배(비중=배수%), 딥시크·릴스는 늘 보통. 1분봉 8초 뒤 읽기)")
GATE_OK = {"pass": True, "n_trials": 3}

RUN_BOUND = {"loss:strat:V45_AMB": "812", "loss:team:lab": "799", "weekly:strat:N17_KC_RSI": "640",
             "bust:V45_AMB@5m": "1790000000000", "bust:NL1@1h": "1790000001000", "incident:alert_rowid": "55",
             "checkpoint:day": "30", "paper:fingerprint": json.dumps({"run": OLD_START, "t": [812, 1], "a": [55, 2]}),
             "extras:orphans": json.dumps({"V45_AMB@5m~c1": {"why": "missing"}}),
             "proposals:gate_now": json.dumps({"3": {"pass": True, "n_trials": 3}})}
LONG_LIVED = {"owner:team:lead": "4", "owner_copied:team:lead": "4", "inbox:approvals": "2",
              "inbox:approvals_ts": "1790000000000", "incident:report_day": "2026-10-03",
              "analysis:cost_review": "2026-09-28", "event_review:last": "1790000000000",
              "move:BTCUSDT": "1790000000000", "tf_split:strat:V45_AMB": "1790000000000",
              "telegram:evening:2026-10-03": "1790000000000", "flag_owners:2026-10-03": "1",
              "newlab_alert:abc": "1790000000000", "usage_scale": json.dumps({"scale": 1.0}),
              "policy:caps": json.dumps({"total": 100}), "tick:last": json.dumps({"ts": 1, "ok": True}),
              "recheck_through": "2026-09", "security:check": json.dumps({"ok": True}),
              "meetings:skipped": json.dumps({}), "extra_started:3@1790000000000": "1"}


def _dump(path, tables=None):
    c = sqlite3.connect(path)
    try:
        names = tables or [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                                   "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: c.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in names}
    finally:
        c.close()


def _cursors(path):
    return dict(_dump(path, ["cursors"])["cursors"])


@pytest.fixture
def lib(tmp_path):
    data = tmp_path / "lib"
    data.mkdir()
    arch = data / "archive" / "run-20261004T131000Z"
    arch.mkdir(parents=True)
    # agents3.db
    a = R.open_agents(str(data / "agents3.db"))
    R.ensure_rooms(a, ts=OLD_START)
    CM.ensure(a)
    a.execute("INSERT INTO committee_calls (ts, day, symbol, status, direction, confidence) VALUES (?,?,?,?,?,?)",
              (OLD_START, "2026-10-01", "BTCUSDT", "graded", "상승", 2))
    a.execute("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)", (OLD_START, "2026-10-01", "rooms", "x", "m", 1, 10))
    h = R.add_trial_with_result(a, "strat:V45_AMB", "V45_AMB", "hypothesis", {"text": "losses cluster at night"},
                                "open", {"prediction": None}, ts=OLD_START + 1)
    R.add_trial_result(a, h, "graded", {"hit": False}, ts=OLD_START + 2)
    t_copy = R.add_trial_with_result(a, "strat:V45_AMB", "V45_AMB", "test",
                                     {"template": "stop_atr", "strategy": "V45_AMB", "timeframe": "5m", "k": 2.5},
                                     "passed", {"gate": GATE_OK}, ts=OLD_START + 3)
    t_nl = R.add_trial_with_result(a, "team:lab", None, "newlab", {"v": "newlab-v1", "timeframe": "5m"},
                                   "proposed", {"gate": GATE_OK}, ts=OLD_START + 4)
    t_bl = R.add_trial_with_result(a, "strat:N17_KC_RSI", "N17_KC_RSI", "test", {"template": "x"}, "failed",
                                   {"gate": {"pass": False}}, ts=OLD_START + 5)
    R.add_note(a, "strat:V45_AMB", "V45_AMB", "밤에 손실이 몰림", ts=OLD_START + 6)
    R.post(a, "team:lead", None, "evening", "team_lead", None, "summary", "첫날 요약", ts=OLD_START + 7)
    p_appr = R.add_proposal(a, "strat:V45_AMB", "V45_AMB", t_copy,
                            {"kind": "copy", "account": {"v": 1, "kind": "copy", "timeframe": "5m"}}, GATE_OK,
                            "approved", "owner:A", ts=OLD_START + 8)
    p_wait = R.add_proposal(a, "team:lab", None, t_nl,
                            {"kind": "newlab", "account": {"v": 1, "kind": "newlab", "timeframe": "5m"}}, GATE_OK,
                            "awaiting_owner", ts=OLD_START + 9)
    p_blk = R.add_proposal(a, "strat:N17_KC_RSI", "N17_KC_RSI", t_bl, {"kind": "copy"}, {"pass": False},
                           "blocked_gate", ts=OLD_START + 10)
    for k, v in {**RUN_BOUND, **LONG_LIVED}.items():
        a.execute("INSERT INTO cursors (k, v) VALUES (?, ?)", (k, v))
    a.commit()
    a.close()
    # inbox.db
    i = R.open_inbox_rw(str(data / "inbox.db"))
    R.add_owner_message(i, "team:lead", "A", "5분봉 계좌는 어때요?", ts=OLD_START + 11)
    R.add_approval(i, p_appr, "approve", "A", ts=OLD_START + 12)
    keep = R.add_price_alert(i, "BTCUSDT", "above", 70000.0, "돌파", "A", ts=OLD_START + 13)
    gone = R.add_price_alert(i, "ETHUSDT", "below", 2000.0, "", "B", ts=OLD_START + 14)
    R.change_price_alert(i, keep, "rearm", ts=OLD_START + 15)
    R.change_price_alert(i, gone, "delete", ts=OLD_START + 16)
    i.close()
    # the old run's paper3.db, already moved into the archive by the script (with 5m accounts)
    st = Store3(str(arch / "paper3.db"))
    for tf in ("5m", "15m", "30m", "1h", "4h"):
        st.add_account(f"V45_AMB@{tf}", "V45_AMB", tf, "strategy", OLD_START, "paper-v3")
        st.add_account(f"RANDOM_1@{tf}", "RANDOM_1", tf, "random", OLD_START, "paper-v3")
    st.commit()
    st.close()
    return {"data": data, "arch": arch, "agents": str(data / "agents3.db"), "inbox": str(data / "inbox.db"),
            "ids": {"approved": p_appr, "awaiting": p_wait, "blocked": p_blk}}


def _apply(lib, now=NOW):
    return RR.apply(lib["agents"], lib["inbox"], str(lib["arch"]), now_ms=now, old_paper=str(lib["arch"] / "paper3.db"))


def test_plan_is_read_only_and_names_exactly_the_run_bound_cursors(lib):
    before = (_dump(lib["agents"]), _dump(lib["inbox"]))
    c = R.open_ro(lib["agents"])
    try:
        plan = RR.cursor_plan(c)
        props = RR.open_proposals(c)
    finally:
        c.close()
    assert set(plan) == set(RUN_BOUND)
    assert {k for k, (_, new) in plan.items() if new is None} == {
        "bust:V45_AMB@5m", "bust:NL1@1h", "paper:fingerprint", "extras:orphans", "proposals:gate_now"}
    assert [p["id"] for p in props] == [lib["ids"]["approved"], lib["ids"]["awaiting"]]
    assert {p["timeframe"] for p in props} == {"5m"}
    assert RR.main(["plan", "--lib", str(lib["data"]), "--etc", str(lib["data"] / "no-etc")]) == 0
    assert (_dump(lib["agents"]), _dump(lib["inbox"])) == before


def test_apply_keeps_memory_resets_run_bound_state_and_backs_up_first(lib):
    agents_before, inbox_before = _dump(lib["agents"]), _dump(lib["inbox"])
    n_rooms = len(agents_before["rooms"])
    res = _apply(lib)
    # backups of the state BEFORE the reset, single-file copies that pass the integrity check
    for name, back in RR.BACKUP_NAMES.items():
        assert res["backups"][name] == "copied"
        p = str(lib["arch"] / back)
        c = sqlite3.connect(p)
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        c.close()
        assert _dump(p) == (agents_before if name == "agents3.db" else inbox_before)
    after = _dump(lib["agents"])
    # memory: unchanged rows
    for t in ("trials", "trial_results", "committee_calls", "agent_calls", "rounds", "rooms"):
        assert after[t] == agents_before[t], t
    assert after["notes"][:len(agents_before["notes"])] == agents_before["notes"]
    assert after["messages"][:len(agents_before["messages"])] == agents_before["messages"]
    # inbox.db: not touched at all (owners' posts, approvals, price alerts)
    assert _dump(lib["inbox"]) == inbox_before
    i = R.open_ro(lib["inbox"])
    assert [(x["symbol"], x["price"]) for x in R.price_alerts(i)] == [("BTCUSDT", 70000.0)]
    i.close()
    # cursors: run-bound ones reset like triggers.reconcile_paper_cursors does for a new run; the rest unchanged
    cur = _cursors(lib["agents"])
    for k in ("loss:strat:V45_AMB", "loss:team:lab", "weekly:strat:N17_KC_RSI", "incident:alert_rowid",
              "checkpoint:day"):
        assert cur[k] == "0", k
    for k in ("bust:V45_AMB@5m", "bust:NL1@1h", "paper:fingerprint", "extras:orphans", "proposals:gate_now"):
        assert k not in cur, k
    assert {k: cur[k] for k in LONG_LIVED} == LONG_LIVED
    assert set(res["cursors"]) == set(RUN_BOUND)
    # proposals: the old run's open ones closed, the rest as they were
    a = R.open_ro(lib["agents"])
    ids = lib["ids"]
    for pid in (ids["approved"], ids["awaiting"]):
        p = R.get_proposal(a, pid)
        assert (p["status"], p["decided_by"], p["decided_ts"]) == ("rejected", RR.CLOSED_BY, NOW)
    assert R.get_proposal(a, ids["blocked"])["status"] == "blocked_gate"
    assert [p["id"] for p in res["closed"]] == [ids["approved"], ids["awaiting"]]
    # the marker and one note + one line per room
    m = json.loads(cur[RR.MARKER])
    assert m["day_kst"] == "2026-10-04" and m["archive"] == str(lib["arch"]) and m["text_ko"] == RESTART_KO
    assert (m["old_run_start"], m["old_originals"], m["old_5m_accounts"]) == (OLD_START, 10, 2)
    assert m["old_groups"] == {"core": 5, "ds200": 0, "reel": 0, "flip": 5} and m["old_shape"] == "v3"
    assert (m["new_run"], m["new_accounts"]) == ("paper-v4", 331)
    new_notes = after["notes"][len(agents_before["notes"]):]
    assert len(new_notes) == n_rooms == res["rooms_told"]
    assert {n[2] for n in new_notes} == {r[0] for r in after["rooms"]}
    assert all(RESTART_KO in n[4] for n in new_notes)
    notes = R.room_notes(a, "strat:V45_AMB", 1)
    assert RESTART_KO in notes[0]["text"] and notes[0]["strategy"] == "V45_AMB"
    lines = [x for x in R.room_messages(a, "team:lab", limit=50) if (x.get("data") or {}).get("action")]
    assert {x["data"]["action"] for x in lines} == {"run_restart", "run_restart_close"}
    a.close()


def test_apply_twice_changes_nothing_more(lib):
    _apply(lib)
    first = _dump(lib["agents"])
    backups = {n: os.path.getmtime(lib["arch"] / b) for n, b in RR.BACKUP_NAMES.items()}
    res = _apply(lib, now=NOW + 60_000)
    assert res["already"] is True and res["cursors"] == {} and res["closed"] == [] and res["rooms_told"] == 0
    assert set(res["backups"].values()) == {"kept"}
    assert {n: os.path.getmtime(lib["arch"] / b) for n, b in RR.BACKUP_NAMES.items()} == backups
    assert _dump(lib["agents"]) == first


def test_a_later_second_restart_is_recorded_with_its_history(lib):
    _apply(lib)
    arch2 = lib["data"] / "archive" / "run-20261104T131000Z"
    arch2.mkdir()
    c = sqlite3.connect(lib["agents"])
    c.execute("UPDATE cursors SET v = '77' WHERE k = 'loss:strat:V45_AMB'")
    c.commit()
    c.close()
    res = RR.apply(lib["agents"], lib["inbox"], str(arch2), now_ms=NOW + 31 * 86_400_000)
    assert res["already"] is False and set(res["cursors"]) == {"loss:strat:V45_AMB"}
    m = json.loads(_cursors(lib["agents"])[RR.MARKER])
    assert m["archive"] == str(arch2) and m["history"][0]["archive"] == str(lib["arch"])


def test_a_failure_rolls_back_the_reset_but_keeps_the_backups(lib, monkeypatch):
    before = _dump(lib["agents"])

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(RR.R, "set_proposal_status", boom)
    with pytest.raises(RuntimeError):
        _apply(lib)
    assert _dump(lib["agents"]) == before
    assert all((lib["arch"] / b).exists() for b in RR.BACKUP_NAMES.values())
    monkeypatch.undo()
    res = _apply(lib)                                   # run again after the fix: the first backup is kept
    assert set(res["backups"].values()) == {"kept"} and len(res["closed"]) == 2


def test_apply_refuses_while_another_writer_holds_agents3(lib):
    w = sqlite3.connect(lib["agents"])
    w.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            _apply(lib)
    finally:
        w.rollback()
        w.close()
    assert "0" != _cursors(lib["agents"])["loss:strat:V45_AMB"]


def test_after_the_reset_the_new_run_needs_no_further_reconciliation(lib, tmp_path):
    """The first tick of the new run (triggers.reconcile_paper_cursors on the new paper3.db) has nothing left to
    reset, and stores the new run's fingerprint."""
    _apply(lib)
    new = tmp_path / "paper3.db"
    st = Store3(str(new))
    st.add_account("V45_AMB@15m", "V45_AMB", "15m", "strategy", NOW + 5_000, "paper-v3")
    st.commit()
    st.close()
    a = sqlite3.connect(lib["agents"])
    p = sqlite3.connect(f"file:{new}?mode=ro", uri=True)
    assert TR.reconcile_paper_cursors(a, p) == {}
    fp = TR.store_paper_fingerprint(a, p)
    assert fp["run"] == NOW + 5_000
    a.close()
    p.close()


def test_the_rules_cover_every_cursor_the_triggers_tie_to_paper3():
    import paperbot.agents.extra_accounts as XA
    import paperbot.agents.rooms as RM
    assert RR.GATE_NOW == RM.GATE_NOW
    keys = {"loss:x", "weekly:x", "bust:x", TR.ALERT_CURSOR, "checkpoint:day", TR.PAPER_FP, XA.ORPHANS}
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE cursors (k TEXT PRIMARY KEY, v TEXT)")
    c.executemany("INSERT INTO cursors VALUES (?, '9')", [(k,) for k in keys])
    assert set(TR._paper_cursors(c)) <= set(RR.cursor_plan(c))
    assert set(RR.cursor_plan(c)) == keys
    for prefix in TR.TRADE_CURSOR_PREFIXES:
        assert (prefix, "0") in RR.CURSOR_RULES


def test_start_info_uses_the_checkpoint_rule(tmp_path, capsys):
    p = tmp_path / "paper3.db"
    assert RR.start_info(str(p)) is None
    assert RR.main(["start", "--paper-db", str(p)]) == 3
    st = Store3(str(p))
    start = NOW + 7_000
    for tf in ("15m", "30m", "1h", "4h"):
        st.add_account(f"V45_AMB@{tf}", "V45_AMB", tf, "strategy", start, "paper-v3")
    st.commit()
    st.close()
    info = RR.start_info(str(p))
    assert info["start"] == start and info["checkpoint"] == CP.checkpoint_ts(start, 1)
    assert info["checkpoint"] == CP.floor_day(start) + 30 * CP.DAY_MS
    assert info["checkpoint_kst"] == "2026-11-03 09:00" and info["start_kst"] == "2026-10-04 22:10"
    assert info["accounts"] == 4 and info["timeframes"] == ["15m", "1h", "30m", "4h"]
    capsys.readouterr()
    assert RR.main(["start", "--paper-db", str(p)]) == 0
    out = capsys.readouterr().out
    assert "새 실행 시작 2026-10-04 22:10 KST" in out and "첫 30일 판정 2026-11-03 09:00 KST" in out


def test_cli_apply_prints_a_korean_summary(lib, capsys):
    assert RR.main(["apply", "--lib", str(lib["data"]), "--archive", str(lib["arch"])]) == 0
    out = capsys.readouterr().out
    assert "agents3.db 백업: copied" in out and "inbox.db 백업: copied" in out
    assert f"초기화한 커서 {len(RUN_BOUND)}개" in out and "닫은 제안 2개" in out


def test_config_warnings_name_old_run_values(tmp_path):
    ex, exe = tmp_path / "extras.json", tmp_path / "executor.json"
    assert RR.config_warnings(str(ex), str(exe)) == []
    ex.write_text(json.dumps({"agents_ack": "a:1@2", "inbox_ack": None, "accept_code": {"NL1@1h": "x"},
                              "observe_until": "2026-10-21", "pause_activation": False}), encoding="utf-8")
    exe.write_text(json.dumps({"account": "V45_AMB@5m"}), encoding="utf-8")
    w = RR.config_warnings(str(ex), str(exe))
    assert len(w) == 4
    assert any("agents_ack" in x for x in w) and any("accept_code" in x for x in w)
    assert any("observe_until" in x for x in w) and any("V45_AMB@5m" in x for x in w)


def test_missing_agents_db_is_nothing_to_reset(tmp_path):
    arch = tmp_path / "arch"
    arch.mkdir()
    res = RR.apply(str(tmp_path / "agents3.db"), str(tmp_path / "inbox.db"), str(arch), now_ms=NOW)
    assert res["backups"] == {"agents3.db": "missing", "inbox.db": "missing"} and "note" in res
    assert not (tmp_path / "agents3.db").exists()


def test_as_root_it_works_as_the_services_user(lib):
    """``--user``: started by root (the reset script), the helper becomes that user before it opens anything, so
    the -wal/-shm and backup files it creates belong to the services' user (paperbot on the server)."""
    import pwd
    import shutil
    import subprocess
    import sys
    import tempfile
    if os.geteuid() != 0:
        pytest.skip("needs root")
    try:
        nobody = pwd.getpwnam("nobody")
    except KeyError:
        pytest.skip("no user 'nobody'")
    top = tempfile.mkdtemp(prefix="resetrun-", dir="/tmp")
    try:
        data = os.path.join(top, "lib")
        shutil.copytree(lib["data"], data)
        arch = os.path.join(data, "archive", lib["arch"].name)
        for root, dirs, files in os.walk(top):
            for n in dirs + files + ["."]:
                os.chown(os.path.join(root, n), nobody.pw_uid, nobody.pw_gid)
        os.chmod(top, 0o755)
        run = [sys.executable, "-m", "paperbot.resetrun"]
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run(run + ["apply", "--lib", data, "--archive", arch, "--user", "nobody"], cwd=root_dir,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        for p in (os.path.join(arch, "agents3-before-reset.db"), os.path.join(arch, "inbox-before-reset.db"),
                  os.path.join(data, "agents3.db")):
            assert os.stat(p).st_uid == nobody.pw_uid, p
        assert _cursors(os.path.join(data, "agents3.db"))["loss:strat:V45_AMB"] == "0"
        os.chmod(data, 0o700)
        os.chown(data, 0, 0)                            # a folder the user cannot read: refused, not "missing"
        r = subprocess.run(run + ["plan", "--lib", data, "--user", "nobody"], cwd=root_dir, capture_output=True,
                           text=True, timeout=60)
        assert r.returncode == 1 and "읽을 수 없음" in r.stdout
    finally:
        shutil.rmtree(top, ignore_errors=True)


def _paper_at(path, start, version="paper-v4"):
    st = Store3(str(path))
    for tf in ("15m", "30m", "1h", "4h"):
        st.add_account(f"V45_AMB@{tf}", "V45_AMB", tf, "strategy", start, version)
    st.commit()
    st.close()


def test_guard_refuses_a_second_reset_of_the_new_run(lib, capsys, monkeypatch):
    """Review 3b m2: after the reset, paper3.db holds the NEW run (started minutes after the run:restarted marker):
    another --yes would archive it, so `guard` refuses (exit 4) with a Korean explanation."""
    paper = lib["data"] / "paper3.db"
    _paper_at(paper, OLD_START, "paper-v3")                         # before the reset: the old run, days old
    assert RR.repeat_reason(str(paper), lib["agents"], NOW) is None
    assert RR.main(["guard", "--lib", str(lib["data"])]) == 0
    paper.unlink()
    _apply(lib)                                                      # the reset writes the marker at NOW
    assert RR.repeat_reason(str(paper), lib["agents"], NOW) is None   # the bot has not made its accounts yet
    start = NOW + 4 * 60_000
    _paper_at(paper, start)
    later = start + 3 * 3_600_000
    why = RR.repeat_reason(str(paper), lib["agents"], later)
    assert why and "재시작은 이미 끝났습니다" in why and "2026-10-04 22:14" in why and "--force-again" in why
    assert str(lib["arch"]) in why
    assert RR.repeat_reason(str(paper), lib["agents"], start + 24 * 3_600_000) is None    # a day later: allowed
    capsys.readouterr()
    monkeypatch.setattr(RR.time, "time", lambda: later / 1000)
    assert RR.main(["guard", "--lib", str(lib["data"])]) == 4
    assert "재시작은 이미 끝났습니다" in capsys.readouterr().out


def test_guard_ignores_a_young_v3_run_made_by_the_v3_restart(lib, capsys, monkeypatch):
    """Ops review 1 (BLOCKER): the v3 restart (10-05) used this script too, so agents3.db holds a run:restarted
    marker minutes before the v3 run's start, and tonight's v4 reset comes less than 24 h later. That v3 run is not
    the v4 reset's new run: the guard must let --yes through. The same young run made by v4 is refused."""
    paper = lib["data"] / "paper3.db"
    _apply(lib)                                                      # the v3 restart's marker at NOW
    start = NOW + 4 * 60_000
    _paper_at(paper, start, "paper-v3")                              # the v3 run it started
    later = start + 15 * 3_600_000                                   # tonight's reset, 15 h later
    assert RR.repeat_reason(str(paper), lib["agents"], later) is None
    monkeypatch.setattr(RR.time, "time", lambda: later / 1000)
    assert RR.main(["guard", "--lib", str(lib["data"])]) == 0
    paper.unlink()
    _paper_at(paper, start)                                          # the same start, written by a v4 runner
    assert "재시작은 이미 끝났습니다" in (RR.repeat_reason(str(paper), lib["agents"], later) or "")
    capsys.readouterr()


def test_guard_ignores_an_old_marker_and_a_missing_agents_db(lib, tmp_path):
    paper = lib["data"] / "paper3.db"
    _apply(lib, now=NOW - 3 * 86_400_000)                            # a restart days before this run
    _paper_at(paper, NOW)
    assert RR.repeat_reason(str(paper), lib["agents"], NOW + 60_000) is None
    assert RR.repeat_reason(str(paper), str(tmp_path / "none.db"), NOW + 60_000) is None
    (tmp_path / "bad.db").write_text("not a database")
    assert RR.repeat_reason(str(tmp_path / "bad.db"), lib["agents"], NOW + 60_000) is None


# ---------------------------------------------------------------------------------- paper v4 (owners 2026-10-05)
def _v4_db(path, start=NOW, version="paper-v4", drop=None, extra=None):
    from paperbot.config import v4_account_defs
    st = Store3(str(path))
    for d in v4_account_defs([f"S{k}" for k in range(36)]):
        aid = f"{d['strategy']}@{d['timeframe']}"
        if aid == drop:
            continue
        st.add_account(aid, d["strategy"], d["timeframe"], d["kind"], start, version, None, d["data"])
    for row in extra or ():
        st.add_account(*row)
    st.commit()
    st.close()
    return str(path)


def test_the_v4_text_is_the_v4_run_and_never_the_v3_wording():
    from paperbot.config import V4_ACCOUNTS, V4_GROUP_ACCOUNTS
    t = RR.WHAT_CHANGED_KO
    assert RR.restart_text("2026-10-04") == RESTART_KO
    assert "5분봉 제외" not in t and "뺐음" not in t and "156" not in t and "144" not in t
    assert f"계좌 {V4_ACCOUNTS}개" in t and f"{V4_GROUP_ACCOUNTS['ds200']}계좌" in t and "릴스 5분 단타" in t
    assert RR.what_changed_ko() == t


def test_paper_facts_of_a_v4_db_has_nothing_off_its_timeframes(tmp_path):
    f = RR.paper_facts(_v4_db(tmp_path / "paper3.db"))
    assert f["off_tf"] == 0 and f["originals"] == 331 and f["shape"] == "v4" and f["utc_days"] == 1
    assert f["groups"] == {"core": 144, "ds200": 171, "reel": 1, "flip": 15}
    assert f["by_tf"] == {"5m": 4, "15m": 83, "30m": 83, "1h": 83, "4h": 78}
    assert f["start"] == NOW and f["versions"] == ["paper-v4"]


def test_paper_facts_tell_a_v3_db_and_a_wrong_v4_db(tmp_path):
    st = Store3(str(tmp_path / "v3.db"))
    for tf in ("15m", "30m", "1h", "4h"):
        for k in range(36):
            st.add_account(f"S{k}@{tf}", f"S{k}", tf, "strategy", OLD_START, "paper-v3")
        for k in (1, 2, 3):
            st.add_account(f"RANDOM_{k}@{tf}", f"RANDOM_{k}", tf, "random", OLD_START, "paper-v3")
    st.commit()
    st.close()
    f = RR.paper_facts(str(tmp_path / "v3.db"))
    assert (f["shape"], f["originals"], f["off_tf"]) == ("v3", 156, 0)
    # one DeepSeek account missing, a strategy account on 5m, an F15 session definition on 4h, the reel on 15m
    bad = _v4_db(tmp_path / "bad.db", drop="F1_RSI_DIV@15m",
                 extra=[("S0@5m", "S0", "5m", "strategy", NOW, "paper-v4"),
                        ("F15_ASIA_BRK@4h", "F15_ASIA_BRK", "4h", "ds200", NOW, "paper-v4"),
                        ("REEL_H1@15m", "REEL_H1", "15m", "reel", NOW, "paper-v4")])
    f = RR.paper_facts(bad)
    assert f["off_tf"] == 3 and f["shape"] == "other" and f["originals"] == 333
    assert RR.paper_facts(_v4_db(tmp_path / "v.db", version="paper-v3"))["shape"] == "other"
    assert RR.paper_facts(str(tmp_path / "none.db")) == {}


def test_start_info_counts_every_group(tmp_path, capsys):
    p = _v4_db(tmp_path / "paper3.db", start=NOW + 7_000)
    info = RR.start_info(p)
    assert info["accounts"] == 331 and info["shape"] == "v4" and info["utc_days"] == 1
    assert info["timeframes"] == ["15m", "1h", "30m", "4h", "5m"]
    assert info["groups"] == {"core": 144, "ds200": 171, "reel": 1, "flip": 15}
    capsys.readouterr()
    assert RR.main(["start", "--paper-db", p]) == 0
    out = capsys.readouterr().out
    assert "원래 계좌 331개" in out and "매매법 144 · 딥시크 171 · 릴스 5분 단타 1 · 동전 15" in out and "!!" not in out


def test_start_info_warns_on_a_short_account_set(tmp_path, capsys):
    p = _v4_db(tmp_path / "paper3.db", drop="REEL_H1@5m")
    assert RR.main(["start", "--paper-db", p]) == 0
    out = capsys.readouterr().out
    assert "원래 계좌 330개" in out and "!! 계좌가 아직 규칙의 331개" in out


@pytest.mark.parametrize("acct, bad", [("V45_AMB@15m", ""), ("V45_AMB@4h", ""), ("V45_AMB@5m", "봉"),
                                       ("F9_FVG@15m", "딥시크"), ("REEL_H1@5m", "릴스"), ("RANDOM_1@1h", "동전"),
                                       ("V45_AMB@15m~c1", "추가 계좌"), ("NL3@1h", "추가 계좌"), ("x", "봉")])
def test_the_executor_may_follow_only_a_core_account(tmp_path, acct, bad):
    why = RR.executor_problem(acct)
    assert (why == "") == (bad == "") and bad in why
    exe = tmp_path / "executor.json"
    exe.write_text(json.dumps({"account": acct}), encoding="utf-8")
    w = RR.config_warnings(str(tmp_path / "none.json"), str(exe))
    assert (w == []) == (bad == "")


def test_plan_shows_the_new_run_and_the_old_runs_shape(lib, capsys):
    import shutil
    shutil.copy(lib["arch"] / "paper3.db", lib["data"] / "paper3.db")
    assert RR.main(["plan", "--lib", str(lib["data"]), "--etc", str(lib["data"] / "no-etc")]) == 0
    out = capsys.readouterr().out
    assert "[새 실행] paper v4: $5,000 계좌 331개" in out
    assert "원래 계좌 10개(매매법 5 · 동전 5; v4 규칙 밖 봉 1개)" in out
