"""deploy/update-dash.sh: the dashboard-only update (paper v4). It swaps in paperbot/dash/ from the checkout and
restarts only paperbot-dash; it refuses when anything the bot runs differs, refuses uncommitted changes, rolls back
when the new dashboard does not come up, and --rollback restores the previous one. Runs the real script against a
temporary checkout and installed tree with a fake systemctl."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "deploy", "update-dash.sh")

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason="the script refuses to run without root")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@t"))


@pytest.fixture
def world(tmp_path):
    repo, app = tmp_path / "repo", tmp_path / "opt"
    (repo / "deploy").mkdir(parents=True)
    (repo / "paperbot" / "dash" / "static").mkdir(parents=True)
    (repo / "paperbot" / "live3.py").write_text("BOT = 1\n")
    (repo / "paperbot" / "dash" / "app.py").write_text("DASH = 1\n")
    (repo / "paperbot" / "dash" / "static" / "a.js").write_text("old\n")
    shutil.copy(SCRIPT, repo / "deploy" / "update-dash.sh")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1")
    subprocess.run(["cp", "-a", str(repo), str(app)], check=True)       # what install.sh does
    shutil.rmtree(app / ".git")
    log, state = tmp_path / "systemctl.log", tmp_path / "active"
    state.write_text("0")
    fake = tmp_path / "systemctl"
    fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\ncase "$1" in is-active) exit $(cat {state});; esac\nexit 0\n')
    fake.chmod(0o755)
    env = dict(os.environ, PAPERBOT_APP=str(app), PAPERBOT_PY=sys.executable, PAPERBOT_SYSTEMCTL=str(fake),
               PAPERBOT_DASH_WAIT_S="2", PAPERBOT_GROUP="root")
    return {"repo": repo, "app": app, "log": log, "state": state, "env": env}


def _run(w, *args):
    return subprocess.run(["bash", str(w["repo"] / "deploy" / "update-dash.sh"), *args], env=w["env"],
                          capture_output=True, text=True, timeout=60)


def _calls(w):
    return w["log"].read_text().splitlines() if w["log"].exists() else []


def test_a_dashboard_only_change_is_swapped_in_and_only_the_dashboard_restarts(world):
    (world["repo"] / "paperbot" / "dash" / "static" / "a.js").write_text("new\n")
    (world["repo"] / "paperbot" / "dash" / "more.py").write_text("NEW = 1\n")
    (world["repo"] / "docs").mkdir()
    (world["repo"] / "docs" / "x.md").write_text("doc\n")
    _git(world["repo"], "add", "-A")
    _git(world["repo"], "commit", "-qm", "v2")
    r = _run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    app = world["app"]
    assert (app / "paperbot" / "dash" / "static" / "a.js").read_text() == "new\n"
    assert (app / "paperbot" / "dash" / "more.py").exists()
    assert (app / "paperbot" / "dash.old" / "static" / "a.js").read_text() == "old\n"
    assert (app / "paperbot" / "live3.py").read_text() == "BOT = 1\n"
    head = subprocess.run(["git", "-C", str(world["repo"]), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert json.loads((app / "DASH_VERSION.json").read_text())["commit"] == head
    restarts = [c for c in _calls(world) if c.startswith(("restart", "stop", "start"))]
    assert restarts == ["restart paperbot-dash"]
    assert "대시보드 업데이트 완료" in r.stdout


def test_a_change_outside_the_dashboard_is_refused_and_nothing_moves(world):
    (world["repo"] / "paperbot" / "live3.py").write_text("BOT = 2\n")
    (world["repo"] / "paperbot" / "dash" / "static" / "a.js").write_text("new\n")
    _git(world["repo"], "commit", "-qam", "v2")
    r = _run(world)
    assert r.returncode != 0
    assert "paperbot/live3.py" in r.stdout
    assert (world["app"] / "paperbot" / "dash" / "static" / "a.js").read_text() == "old\n"
    assert not (world["app"] / "paperbot" / "dash.old").exists()
    assert not [c for c in _calls(world) if c.startswith("restart")]


def test_uncommitted_changes_are_refused(world):
    (world["repo"] / "paperbot" / "dash" / "static" / "a.js").write_text("dirty\n")
    r = _run(world)
    assert r.returncode != 0 and "커밋하지 않은 변경" in r.stdout
    assert not _calls(world)


def test_a_dashboard_that_does_not_come_up_is_rolled_back(world):
    (world["repo"] / "paperbot" / "dash" / "static" / "a.js").write_text("broken\n")
    _git(world["repo"], "commit", "-qam", "v2")
    world["state"].write_text("3")                         # is-active fails: the new dashboard never comes up
    r = _run(world)
    assert r.returncode == 1 and "되돌" in r.stdout
    assert (world["app"] / "paperbot" / "dash" / "static" / "a.js").read_text() == "old\n"
    assert not (world["app"] / "DASH_VERSION.json").exists()
    assert [c for c in _calls(world) if c.startswith("restart")] == ["restart paperbot-dash"] * 2


def test_rollback_brings_back_the_previous_dashboard(world):
    (world["repo"] / "paperbot" / "dash" / "static" / "a.js").write_text("new\n")
    _git(world["repo"], "commit", "-qam", "v2")
    assert _run(world).returncode == 0
    r = _run(world, "--rollback")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (world["app"] / "paperbot" / "dash" / "static" / "a.js").read_text() == "old\n"
    assert not (world["app"] / "paperbot" / "dash.old").exists()
    assert _run(world, "--rollback").returncode != 0      # nothing left to roll back to
