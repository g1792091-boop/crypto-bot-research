"""A scheduled job's failure warning clears once the same job has since run successfully (the owners re-ran
paperbot-obsidian by hand after the 09:50 failure on 10/06, and 서버·비용 still said '확인할 것이 있습니다')."""
import os
import subprocess
import time

from paperbot.dash import analysis as AN
from paperbot.dash.more import jobs as J


def _runner(blocks: dict, calls: list):
    def run(cmd, **kw):
        calls.append(cmd)
        units = [a for a in cmd if a.startswith("paperbot-")]
        text = "\n\n".join("\n".join([f"Id={u}"] + [f"{k}={v}" for k, v in blocks.get(u, {}).items()]) for u in units)
        return subprocess.CompletedProcess(cmd, 0, stdout=text + "\n", stderr="")
    return run


def _fail(tmp_path, unit, day, ts_s):
    d = tmp_path / "fa"
    os.makedirs(d, exist_ok=True)
    p = d / unit
    p.write_text(day)
    os.utime(p, (ts_s, ts_s))
    return str(d)


def _utc(ts_s):
    return time.strftime("%a %Y-%m-%d %H:%M:%S UTC", time.gmtime(ts_s))


def test_a_later_success_marks_the_failure_recovered(tmp_path, monkeypatch):
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl")
    t_fail = int(time.time()) - 3 * 3600
    d = _fail(tmp_path, "paperbot-obsidian.service", "2026-10-06", t_fail)
    calls = []
    run = _runner({"paperbot-obsidian.service": {"Result": "success", "ExecMainExitTimestamp": _utc(t_fail + 3600)}}, calls)
    fa = AN.mark_recovered(AN.failalert_records(d), runner=run)
    assert fa[0]["recovered_ts"] == (t_fail + 3600) * 1000
    assert calls and "paperbot-obsidian.service" in calls[0]          # one fixed-name call, nothing from a request


def test_a_success_before_the_warning_or_a_failed_rerun_keeps_the_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl")
    t_fail = int(time.time()) - 3 * 3600
    d = _fail(tmp_path, "paperbot-obsidian.service", "2026-10-06", t_fail)
    for blk in ({"Result": "success", "ExecMainExitTimestamp": _utc(t_fail - 600)},      # the success was earlier
                {"Result": "exit-code", "ExecMainExitTimestamp": _utc(t_fail + 3600)},   # re-run failed again
                {}):                                                                      # never ran / unknown
        fa = AN.mark_recovered(AN.failalert_records(d), runner=_runner({"paperbot-obsidian.service": blk}, []))
        assert "recovered_ts" not in fa[0]


def test_without_systemctl_the_records_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(J.shutil, "which", lambda name: None)                 # a container / test machine
    d = _fail(tmp_path, "paperbot-daily3.service", "2026-10-06", int(time.time()) - 60)
    fa = AN.failalert_records(d)
    assert AN.mark_recovered(fa) == fa


def test_health_warns_only_for_a_failure_not_yet_fixed(tmp_path, monkeypatch):
    from tests.test_dash_v4server import _world, Data, A
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl")
    db = str(tmp_path / "p.db")
    store = _world(db, trades=False)
    now = int(time.time() * 1000)
    store.put_state("heartbeat", now, {"last_step": now})
    store.commit()
    store.close()
    t_fail = now // 1000 - 3 * 3600
    d = _fail(tmp_path, "paperbot-obsidian.service", "2026-10-06", t_fail)
    _fail(tmp_path, "paperbot-daily3.service", "2026-10-06", t_fail)
    run = _runner({"paperbot-obsidian.service": {"Result": "success", "ExecMainExitTimestamp": _utc(t_fail + 3600)},
                   "paperbot-daily3.service": {"Result": "exit-code", "ExecMainExitTimestamp": _utc(t_fail)}}, [])
    h = AN.health(Data(db), A.Rooms(None, None, paper_db=db), None, None, None, now_ms=now, failalert_dir=d, jobs_runner=run)
    lines = [w for w in h["warnings"] if w.startswith("예약 작업 실패 경고")]
    assert len(lines) == 1 and "매일 점검" in lines[0], lines
    rec = {f["unit"]: f for f in h["job_failures"]}
    assert rec["paperbot-obsidian.service"].get("recovered_ts") and not rec["paperbot-daily3.service"].get("recovered_ts")


def test_the_pages_show_a_fixed_job_as_fixed():
    root = os.path.join(os.path.dirname(__file__), "..", "paperbot", "dash", "static", "v4", "screens")
    srv = open(os.path.join(root, "server-health.js"), encoding="utf-8").read()
    assert "!f.recovered_ts" in srv and "다시 돌려서 성공" in srv
    assert "fail.recovered_ts" in open(os.path.join(root, "server-jobs.js"), encoding="utf-8").read()
    assert "f.recovered_ts" in open(os.path.join(root, "alerts.js"), encoding="utf-8").read()
