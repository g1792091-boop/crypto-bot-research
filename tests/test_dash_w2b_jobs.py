"""Wave 2 part B, A9: /api/v4/jobs (dash/more/jobs.py) reads the paperbot timers from systemd (on / off, last / next
run, last result) with a fixed unit list, a 2 s timeout and a 60 s cache, and degrades to {available: false} when
systemctl is missing, times out or refuses (a container, this test machine); the 예약 작업 card shows 꺼짐 for a
switched-off timer instead of 수집 전 and keeps its calendar rows when the route cannot answer."""

import os
import subprocess
import time
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import jobs as J  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
PW = "jobs horse battery"
SECRET = b"j" * 32


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


def _timer(unit, file_state="enabled", active="active", last="Mon 2026-10-05 23:40:01 UTC",
           nxt="Tue 2026-10-06 23:40:00 UTC", load="loaded"):
    return (f"Id={unit}.timer\nLoadState={load}\nUnitFileState={file_state}\nActiveState={active}\n"
            f"LastTriggerUSec={last}\nNextElapseUSecRealtime={nxt}\n")


def _service(unit, result="success", active="inactive", sub="dead", exit_ts="Mon 2026-10-05 23:41:10 UTC"):
    return (f"Id={unit}.service\nLoadState=loaded\nActiveState={active}\nSubState={sub}\nResult={result}\n"
            f"ExecMainExitTimestamp={exit_ts}\n")


def fake_runner(timers: dict, services: dict, calls: list):
    """A subprocess.run stand-in: answers `systemctl show` for the units it is asked about."""
    def run(cmd, **kw):
        calls.append((cmd, kw))
        units = [c for c in cmd if c.startswith("paperbot-")]
        src = timers if units and units[0].endswith(".timer") else services
        out = "\n".join(src.get(u.rsplit(".", 1)[0], f"Id={u}\nLoadState=not-found\n") for u in units)
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    return run


@pytest.fixture
def systemctl(monkeypatch):
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)


# ---------------------------------------------------------------- parsing
def test_timestamps_and_blocks_parse_the_same_on_any_server():
    assert J.parse_ts("Mon 2026-10-05 23:40:01 UTC") == 1791243601000
    assert J.parse_ts("Tue 2026-10-06 08:40:01 KST") == 1791243601000
    assert J.parse_ts("2026-10-05 23:40:01") == 1791243601000             # no zone: the command runs with TZ=UTC
    assert J.parse_ts("Mon 2026-10-05 23:40:01.123456 UTC") == 1791243601000
    assert J.parse_ts("@1791243601") == 1791243601000
    for v in ("n/a", "", None, "0", "garbage", "Mon 2026-10-05 23:40:01 PDT"):
        assert J.parse_ts(v) is None
    got = J.parse_show(_timer("paperbot-backup") + "\n" + _timer("paperbot-offsite", "disabled", "inactive", "n/a", ""))
    assert set(got) == {"paperbot-backup.timer", "paperbot-offsite.timer"}
    assert got["paperbot-offsite.timer"]["UnitFileState"] == "disabled"


def test_a_switched_off_timer_is_off_with_no_next_run_and_a_missing_one_is_missing():
    on = J.job_state(J.parse_show(_timer("paperbot-backup"))["paperbot-backup.timer"],
                     J.parse_show(_service("paperbot-backup"))["paperbot-backup.service"])
    assert on["state"] == "on" and on["ok"] is True and on["result"] == "success" and not on["running"]
    assert on["last_ms"] == 1791243601000 and on["next_ms"] == J.parse_ts("Tue 2026-10-06 23:40:00 UTC")
    off = J.job_state(J.parse_show(_timer("paperbot-obsidian", "disabled", "inactive", "n/a", ""))["paperbot-obsidian.timer"],
                      J.parse_show(_service("paperbot-obsidian", exit_ts="n/a"))["paperbot-obsidian.service"])
    assert off["state"] == "off" and off["next_ms"] is None and off["last_ms"] is None
    assert off["ok"] is None and off["result"] is None                       # never ran: no result shown
    # enabled on disk but not started (a timer nobody ran `systemctl start` for) is off too
    idle = J.job_state(J.parse_show(_timer("paperbot-evening", "enabled", "inactive"))["paperbot-evening.timer"], None)
    assert idle["state"] == "off"
    assert J.job_state({"Id": "x.timer", "LoadState": "not-found"}, None)["state"] == "missing"
    assert J.job_state(None, None)["state"] == "missing"
    failed = J.job_state(J.parse_show(_timer("paperbot-offsite"))["paperbot-offsite.timer"],
                         J.parse_show(_service("paperbot-offsite", "exit-code", "failed", "failed"))["paperbot-offsite.service"])
    assert failed["ok"] is False and failed["result"] == "exit-code"


# ---------------------------------------------------------------- the command
def test_one_fixed_systemctl_call_per_kind_with_a_2s_timeout_and_utc(systemctl):
    calls: list = []
    timers = {u: _timer(u) for u in J.UNITS}
    timers["paperbot-obsidian"] = _timer("paperbot-obsidian", "disabled", "inactive", "n/a", "")
    run = fake_runner(timers, {u: _service(u) for u in J.UNITS}, calls)
    d = J.jobs(run)
    assert d["available"] is True and set(d["jobs"]) == set(J.UNITS)
    assert d["jobs"]["paperbot-obsidian"]["state"] == "off" and d["jobs"]["paperbot-backup"]["state"] == "on"
    assert len(calls) == 2
    for cmd, kw in calls:
        assert cmd[:2] == ["/usr/bin/systemctl", "show"] and "--no-pager" in cmd
        assert kw["timeout"] == J.TIMEOUT_S == 2.0 and kw["env"]["TZ"] == "UTC" and kw["env"]["LC_ALL"] == "C"
        assert not kw.get("shell")
        assert all(c.startswith(("/", "show", "--", "-p", "Id,", "paperbot-")) for c in cmd)


def test_it_degrades_cleanly_without_systemctl_on_a_timeout_and_on_an_error(monkeypatch):
    monkeypatch.setattr(J.shutil, "which", lambda name: None)
    d = J.jobs(lambda *a, **k: pytest.fail("must not run"))
    assert d == {"ready": True, "available": False, "reason": "systemctl 없음", "ts": d["ts"], "jobs": {}}
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    d = J.jobs(slow)
    assert d["available"] is False and "2초" in d["reason"] and d["jobs"] == {}

    def refused(cmd, **kw):
        return SimpleNamespace(returncode=1, stdout="", stderr="System has not been booted with systemd as init system (PID 1).\n")
    d = J.jobs(refused)
    assert d["available"] is False and d["reason"].startswith("systemctl 오류") and d["jobs"] == {}

    def broken(cmd, **kw):
        raise PermissionError("no")
    assert J.jobs(broken)["available"] is False


# ---------------------------------------------------------------- the route
@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "paper3.db")
    Store3(db).close()
    app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], inbox_db=str(tmp_path / "inbox.db"))
    return TestClient(app), app


def test_route_is_behind_the_login_cached_60s_and_degrades_on_this_machine(client, monkeypatch):
    c, app = client
    assert c.get("/api/v4/jobs").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    monkeypatch.setattr(J.shutil, "which", lambda name: None)                 # as in a container: no systemctl
    r = c.get("/api/v4/jobs")
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["jobs"] == {}
    cache = app.state.more["jobs"]["cache"]
    assert "v" in cache
    # a cached answer is served for 60 s (no second systemctl call even if it would answer now)
    calls: list = []
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(J.subprocess, "run", fake_runner({u: _timer(u) for u in J.UNITS}, {}, calls))
    assert c.get("/api/v4/jobs").json()["available"] is False and not calls
    cache["v"] = (time.time() - J.TTL_S - 1, cache["v"][1])                    # expire it
    d = c.get("/api/v4/jobs").json()
    assert d["available"] is True and len(calls) == 2 and d["jobs"]["paperbot-daily3"]["state"] == "on"
    assert len(c.get("/api/v4/jobs").content) < 10_000


# ---------------------------------------------------------------- the page
def test_the_jobs_card_reads_the_route_and_says_off_not_not_yet():
    srv, jobs, kit = _read("screens", "server.js"), _read("screens", "server-jobs.js"), _read("screens", "server-kit.js")
    assert '"/api/v4/jobs"' in srv and "jobs.setJobs(" in srv and "v4Jobs = false" in srv      # 404 stops the polling
    assert "card.setJobs" in jobs and '"꺼짐"' in jobs and '"설치 안 됨"' in jobs
    assert 'sys.state === "off"' in jobs and "ui.notYet()" in jobs            # 수집 전 stays only without a record
    units = {u for u in J.UNITS}
    for u in units:                                                           # the server's list = the card's rows
        assert f'unit: "{u}"' in kit
