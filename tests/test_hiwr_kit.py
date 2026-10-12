"""research/hiwr/bootstrap.sh and wait_go.sh, rehearsed in a temporary folder (--dry-run, stand-ins only; no install, no
download, no push, no tmux, no change to this repository). The waiter is visible to status / idle / update and a pasted
restart line never kills it; a run without a go commit hands over to the waiter again; 'update' stays allowed after a
select that refused before computing anything and is locked once select computed an exit table. No price is read."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIWR = os.path.join(ROOT, "research", "hiwr")
BRANCH = "claude/keen-pasteur-wav02u"
WAIT_MSG = "고정된 커밋을 기다리는 중입니다"

pytestmark = pytest.mark.skipif(not (shutil.which("git") and shutil.which("bash")), reason="needs git and bash")


def _git(cwd, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True, env=env).stdout


def _world(tmp_path):
    """A scratch origin (bare) whose branch holds the kit's two scripts, and the server's clone of it."""
    src = tmp_path / "src"
    (src / "research" / "hiwr").mkdir(parents=True)
    for f in ("bootstrap.sh", "wait_go.sh"):
        shutil.copy(os.path.join(HIWR, f), src / "research" / "hiwr" / f)
    _git(src, "init", "-q", "-b", BRANCH)
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "kit")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(origin)], check=True)
    base = tmp_path / "base"
    base.mkdir()
    repo = base / "crypto-bot-research"
    subprocess.run(["git", "clone", "-q", "-b", BRANCH, str(origin), str(repo)], check=True)
    env_file = tmp_path / "dry.env"
    env_file.write_text(f"export HIWR_BASE={base}\nexport HIWR_REPO={repo}\nexport HIWR_TMUX='tmux -L hiwr_test_kit'\n"
                        f"export HIWR_RETRY_SLEEP=0\n")
    return {"src": src, "origin": origin, "base": base, "repo": repo, "env_file": env_file,
            "script": str(repo / "research" / "hiwr" / "bootstrap.sh")}


def _publish_go(w):
    """The developer publishes GO_COMMIT (the commit of the pin) on the branch."""
    head = _git(w["src"], "rev-parse", "HEAD").strip()
    (w["src"] / "research" / "hiwr" / "GO_COMMIT").write_text(head + "\n")
    _git(w["src"], "add", "-A")
    _git(w["src"], "commit", "-q", "-m", "go")
    _git(w["src"], "push", "-q", str(w["origin"]), BRANCH)
    return head


def _env(w, **kw):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HIWR_")}
    env.update(HIWR_DRYENV=str(w["env_file"]), HIWR_REPO=str(w["repo"]), HIWR_BASE=str(w["base"]),
               HIWR_BRANCH=BRANCH, WAIT_POLL="1")
    env.update(kw)
    return env


def _stub_start(tmp_path):
    """A stand-in for bootstrap.sh that the waiter execs: it writes the go commit it was given."""
    started = tmp_path / "started.txt"
    stub = tmp_path / "start_stub.sh"
    stub.write_text(f'echo "$HIWR_GO" > {started}\n')
    return started, f"bash {stub}"


def _boot(w, *args, **kw):
    r = subprocess.run(["bash", w["script"], "--dry-run", *args], capture_output=True, text=True, timeout=120,
                       env=_env(w, **kw), cwd=str(w["base"]))
    return r.returncode, r.stdout + r.stderr


def _until(pred, seconds=30.0):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if pred():
            return True
        time.sleep(0.2)
    return False


def test_the_waiter_is_visible_and_a_restart_line_does_not_kill_it(tmp_path):
    w = _world(tmp_path)
    started, stub = _stub_start(tmp_path)
    shutil.copy(os.path.join(HIWR, "wait_go.sh"), w["base"] / "wait_go.sh")
    p = subprocess.Popen(["bash", str(w["base"] / "wait_go.sh")], env=_env(w, HIWR_WAIT_EXEC=stub),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _until(lambda: (w["base"] / "WAITING").exists())
        assert (w["base"] / "WAITING").read_text().strip() == str(p.pid)
        rc, out = _boot(w, "status")
        assert rc == 0 and WAIT_MSG in out and "돌고 있지 않습니다" not in out
        rc, out = _boot(w, "idle")                       # the restart line's guard: refuses, the waiter lives on
        assert rc == 1 and WAIT_MSG in out and p.poll() is None
        rc, out = _boot(w, "update", "abcdef1")
        assert rc == 1 and WAIT_MSG in out and p.poll() is None
        rc, out = _boot(w)                               # a pasted run line refuses too
        assert rc == 1 and WAIT_MSG in out and p.poll() is None
        go = _publish_go(w)                              # the pin arrives: the waiter starts the run at that commit
        assert _until(lambda: started.exists() and started.read_text().strip() == go)
        assert p.wait(timeout=30) == 0
        assert not (w["base"] / "WAITING").exists()
        assert _git(w["repo"], "rev-parse", "HEAD").strip() == go
    finally:
        if p.poll() is None:
            p.kill()


def test_a_run_without_a_go_commit_waits_again(tmp_path):
    """After a reboot (or the waiter's 12 hours) the restart line runs bootstrap without a go commit: it hands over to
    wait_go.sh instead of stopping; status says how to wait again when nothing waits."""
    w = _world(tmp_path)
    rc, out = _boot(w, "status")
    assert "다시 기다립니다" in out and "bootstrap.sh" in out.splitlines()[-1]
    go = _publish_go(w)
    started, stub = _stub_start(tmp_path)
    rc, out = _boot(w, HIWR_DRY_WAIT="1", HIWR_WAIT_EXEC=stub)
    assert rc == 0 and "아직 고정 전입니다" in out, out
    assert started.read_text().strip() == go and (w["base"] / "wait_go.sh").exists()
    assert not (w["base"] / "RUNNING").exists()


STUB_HIWR = r'''
import os, sys
mode = os.environ["STUB_SELECT"]
if sys.argv[1] == "select":
    if mode == "refuse":
        print("REFUSED: research/hiwr/PREREG_HIWR.sha256 does not match: changed research/hiwr/hiwr.py")
        sys.exit(2)
    work = sys.argv[sys.argv.index("--work") + 1]
    os.makedirs(os.path.join(work, "select_0123", "tables", "1h_BTCUSDT"), exist_ok=True)
    print("Traceback: something broke after the exit tables")
    sys.exit(1)
sys.exit(0)
'''
STUB_HELPER = r'''
import sys
if sys.argv[1] == "verify":
    print("VERIFY coins 30/30 identical (stand-in)")
sys.exit(0)
'''


def _select_world(tmp_path, mode):
    w = _world(tmp_path)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "stub_hiwr.py").write_text(STUB_HIWR)
    (stubs / "stub_helper.py").write_text(STUB_HELPER)
    (stubs / "stub_data.py").write_text("import sys\nsys.exit(0)\n")
    (stubs / "test_tiny.py").write_text("def test_ok():\n    assert True\n")
    pin = w["repo"] / "research" / "hiwr" / "pin_kit_test.txt"
    pin.write_text("".join(f"{'0' * 64}  research/hiwr/{f}\n" for f in ("data_manifest_sel.json",
                                                                       "data_check_sel.json")))
    py = sys.executable
    with open(w["env_file"], "a") as fh:
        fh.write(f"export HIWR_PY={py}\nexport HIWR_CMD='{py} {stubs / 'stub_hiwr.py'}'\n"
                 f"export HIWR_DATA_CMD='{py} {stubs / 'stub_data.py'}'\n"
                 f"export HIWR_HELPER_STUB='{py} {stubs / 'stub_helper.py'}'\n"
                 f"export HIWR_HELPER_STUB_SUBS='pincheck build verify'\n"
                 f"export HIWR_PIN_REL=research/hiwr/pin_kit_test.txt\n"
                 f"export HIWR_SELFCHECK_TESTS={stubs / 'test_tiny.py'}\nexport STUB_SELECT={mode}\n")
    return w


def test_update_stays_allowed_after_a_refused_select(tmp_path):
    """A select that refuses before computing anything (pin mismatch) leaves 'update' open: the developer's fixed
    commit can be swapped in without destroying the server."""
    w = _select_world(tmp_path, "refuse")
    rc, out = _boot(w)
    assert rc == 1 and "고르기 거부" in out and "잃는 것이 없습니다" in out, out[-2000:]
    assert not (w["base"] / "SELECT_RAN").exists()
    rc, out = _boot(w, "update", "abcdef1")
    assert rc == 0 and "코드를 abcdef1 으로 바꿨습니다" in out, out


def test_update_is_locked_once_select_computed_something(tmp_path):
    w = _select_world(tmp_path, "compute")
    rc, out = _boot(w)
    assert rc == 1 and "고르기 실패" in out and "지우지(Destroy) 마세요" in out, out[-2000:]
    assert (w["base"] / "SELECT_RAN").exists()
    rc, out = _boot(w, "update", "abcdef1")
    assert rc == 1 and "이미 계산을 시작해서" in out
