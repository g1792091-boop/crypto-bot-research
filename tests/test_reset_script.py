"""deploy/paperbot-reset.sh: syntax (bash -n, shellcheck when installed), what it archives and keeps (never the
agents' memory, the owners' inbox or a market recorder), and the --dry-run / refusal paths with a fake systemctl
(nothing is stopped, moved or changed)."""

import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

from paperbot.agents import rooms_db as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "deploy", "paperbot-reset.sh")
TEXT = open(SCRIPT, encoding="utf-8").read()
NEVER_ARCHIVED = ("agents3.db", "inbox.db", "liq.db", "market.db", "flow.db", "paper.db", "ghcoin", "lab", "exec",
                  "failalert", "price_alerts.json")


def _list(name):
    m = re.search(rf'^{name}="([^"]*)"$', TEXT, re.M)
    assert m, name
    return m.group(1).split()


def test_bash_syntax():
    subprocess.run(["bash", "-n", SCRIPT], check=True)


def test_shellcheck():
    sc = shutil.which("shellcheck")
    if sc is None:
        pytest.skip("shellcheck not installed")
    r = subprocess.run([sc, SCRIPT], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_strict_mode_and_modes():
    assert "set -Eeuo pipefail" in TEXT
    assert "--dry-run" in TEXT and "--yes" in TEXT


def test_the_archive_lists_never_hold_memory_or_market_data():
    archived = _list("ARCHIVE_DBS") + _list("ARCHIVE_FILES")
    assert set(archived) == {"paper3.db", "daily3.db", "checkpoint.db", "tradealerts.json", "evening-latest.json",
                             "checkpoint_bars", "rehearsal"}
    for name in NEVER_ARCHIVED:
        assert name not in archived, name
        assert name in _list("KEEP"), name
    # no line moves or deletes a kept file, and nothing is ever deleted
    for line in TEXT.splitlines():
        code = line.split("#", 1)[0]
        if re.search(r"\bmv\b", code) and "echo" not in code:
            assert not any(n in code for n in NEVER_ARCHIVED), line
        assert not re.search(r"\brm\s+-", code), line


def test_moved_items_are_only_the_lists():
    """Every `mv` of the real run moves "$DATA/$f..." with $f from ARCHIVE_DBS / ARCHIVE_FILES."""
    mvs = [ln.strip() for ln in TEXT.splitlines() if re.match(r"\s*(if .*then )?mv ", ln.strip()) or " mv \"$DATA" in ln]
    assert mvs and all('"$DATA/$f' in m and '"$ARCH/"' in m for m in mvs), mvs
    loops = re.findall(r"for f in (\$\w+); do\n(?:.*\n){0,3}?.*mv \"\$DATA", TEXT)
    assert set(loops) == {"$ARCHIVE_DBS", "$ARCHIVE_FILES"}


# ---------------------------------------------------------------------------------- running it (fakes)
def _tree_hash(path):
    h = hashlib.sha256()
    for root, dirs, files in sorted(os.walk(path)):
        dirs.sort()
        for f in sorted(files):
            if f.endswith(("-wal", "-shm")):          # a read-only SQLite reader may create these (no content)
                continue
            p = os.path.join(root, f)
            h.update(p.encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


@pytest.fixture
def env(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("the script refuses to run without root")
    data = tmp_path / "lib"
    data.mkdir()
    a = R.open_agents(str(data / "agents3.db"))
    R.ensure_rooms(a)
    a.execute("INSERT INTO cursors VALUES ('loss:strat:V45_AMB', '812')")
    a.commit()
    a.close()
    R.open_inbox_rw(str(data / "inbox.db")).close()
    for f in ("paper3.db", "daily3.db", "liq.db", "tradealerts.json", "price_alerts.json"):
        (data / f).write_text("x")
    (data / "checkpoint_bars").mkdir()
    (data / "lab").mkdir()
    log = tmp_path / "systemctl.log"
    fake = tmp_path / "systemctl"
    stopped = tmp_path / "stopped"
    stopped.write_text("")
    # a stateful systemctl: FAKE_ACTIVE are running until stopped, started again by start
    fake.write_text(f"""#!/bin/bash
echo "$*" >> "{log}"
cmd="$1"; shift
case "$cmd" in
  is-active)
    u="${{@: -1}}"
    grep -qx "$u" "{stopped}" && exit 3
    for a in $FAKE_ACTIVE; do [ "$a" = "$u" ] && exit 0; done
    exit 3 ;;
  stop) for u in "$@"; do echo "$u" >> "{stopped}"; done ;;
  start) for u in "$@"; do grep -vx "$u" "{stopped}" > "{stopped}.n" || true; mv "{stopped}.n" "{stopped}"; done ;;
esac
exit 0
""")
    fake.chmod(0o755)
    e = dict(os.environ, PAPERBOT_LIB=str(data), PAPERBOT_ETC=str(tmp_path / "etc"), PAPERBOT_PY=sys.executable,
             PAPERBOT_RESET_USER="", PAPERBOT_SYSTEMCTL=str(fake), PAPERBOT_RESET_HM="2200",
             FAKE_ACTIVE="paperbot-live3 paperbot-dash paperbot-agents.timer")
    return {"data": data, "env": e, "log": log, "tmp": tmp_path}


def _run(env, *args):
    return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=env["env"], timeout=120)


def test_dry_run_changes_nothing(env):
    before = _tree_hash(env["data"])
    r = _run(env, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "[멈출 것] paperbot-live3 paperbot-dash paperbot-agents.timer" in out
    assert "  paper3.db" in out and "  tradealerts.json" in out and "  checkpoint_bars" in out
    keep = out.split("[그대로 둘 것]")[1].split("[agents3.db")[0]
    assert "agents3.db" in keep and "inbox.db" in keep and "price_alerts.json" in keep and "liq.db" in keep
    assert "loss:strat:V45_AMB: 812 -> 0" in out
    assert _tree_hash(env["data"]) == before
    calls = env["log"].read_text().splitlines()
    assert calls and all(c.startswith("is-active") for c in calls)


def test_refused_in_the_nightly_window(env):
    env["env"]["PAPERBOT_RESET_HM"] = "0905"
    before = _tree_hash(env["data"])
    r = _run(env, "--yes")
    assert r.returncode == 1 and "08:30-09:40 KST" in r.stdout
    assert _tree_hash(env["data"]) == before and not env["log"].exists()


def test_refused_while_the_order_executor_runs(env):
    env["env"]["FAKE_ACTIVE"] += " paperbot-executor"
    before = _tree_hash(env["data"])
    r = _run(env, "--yes")
    assert r.returncode == 1 and "sudo systemctl stop paperbot-executor" in r.stdout
    assert _tree_hash(env["data"]) == before
    assert all(c.startswith("is-active") for c in env["log"].read_text().splitlines())


def test_usage_without_a_mode():
    r = subprocess.run(["bash", SCRIPT], capture_output=True, text=True)
    assert r.returncode == 2 and "--dry-run" in r.stdout


def test_yes_moves_the_run_keeps_memory_and_restarts(env):
    stub = env["tmp"] / "install.sh"
    stub.write_text('#!/bin/bash\necho installed >> "%s"\n' % (env["tmp"] / "installed"))
    env["env"].update(PAPERBOT_INSTALL=str(stub), PAPERBOT_RESET_WAIT="0", ALLOW_DIRTY="1",
                      FAKE_ACTIVE="paperbot-live3 paperbot-dash paperbot-tgtrades paperbot-agents.timer paperbot-liq")
    r = _run(env, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    data = env["data"]
    archs = list((data / "archive").iterdir())
    assert len(archs) == 1 and archs[0].name.startswith("run-")
    arch = archs[0]
    assert sorted(os.listdir(arch)) == sorted(["paper3.db", "daily3.db", "tradealerts.json", "checkpoint_bars",
                                               "agents3-before-reset.db", "inbox-before-reset.db"])
    for kept in ("agents3.db", "inbox.db", "liq.db", "price_alerts.json", "lab", "rehearsal"):
        assert (data / kept).exists(), kept
    assert not (data / "paper3.db").exists() and not (data / "tradealerts.json").exists()
    c = sqlite3.connect(str(data / "agents3.db"))
    cur = dict(c.execute("SELECT k, v FROM cursors"))
    c.close()
    assert cur["loss:strat:V45_AMB"] == "0" and "run:restarted" in cur
    assert (env["tmp"] / "installed").read_text() == "installed\n"
    calls = env["log"].read_text().splitlines()
    stops = [c for c in calls if c.startswith("stop")]
    starts = [c for c in calls if c.startswith("start")]
    assert stops == ["stop paperbot-live3 paperbot-dash paperbot-tgtrades paperbot-agents.timer"]
    assert starts == ["start paperbot-live3 paperbot-dash paperbot-tgtrades paperbot-agents.timer"]
    out = r.stdout
    assert "no process has the run files open" in out and "요약" in out and "봇이 아직 새 계좌를 만들지 않았습니다" in out
    assert "agents3.db 백업: copied" in out


def test_an_unreadable_agents_db_stops_the_reset_before_anything_is_stopped(env):
    env["env"].update(ALLOW_DIRTY="1")
    (env["data"] / "agents3.db").write_text("not a database")
    r = _run(env, "--dry-run")
    assert r.returncode == 1 and "읽을 수 없음" in r.stdout
    r = _run(env, "--yes")
    assert r.returncode == 1 and "읽을 수 없음" in r.stdout
    assert not any(c.startswith("stop") for c in env["log"].read_text().splitlines())


def test_a_failure_after_the_move_prints_how_to_go_on_or_back(env):
    stub = env["tmp"] / "install.sh"
    stub.write_text("#!/bin/bash\nexit 0\n")
    py = env["tmp"] / "py"                                          # the helper's apply fails
    py.write_text('#!/bin/bash\nfor a in "$@"; do [ "$a" = apply ] && { echo boom >&2; exit 1; }; done\n'
                  f'exec {sys.executable} "$@"\n')
    py.chmod(0o755)
    env["env"].update(PAPERBOT_INSTALL=str(stub), PAPERBOT_RESET_WAIT="0", ALLOW_DIRTY="1", PAPERBOT_PY=str(py),
                      FAKE_ACTIVE="paperbot-live3 paperbot-dash")
    r = _run(env, "--yes")
    assert r.returncode == 1, r.stdout
    out = r.stdout
    arch = next((env["data"] / "archive").iterdir())
    assert out.count("!! 실패") == 1 and "단계 moved" in out and "이전 실행으로 되돌리기" in out
    assert f"sudo mv {arch}/paper3.db {env['data']}/" in out and f"sudo mv {arch}/tradealerts.json" in out
    assert "sudo systemctl start paperbot-live3 paperbot-dash" in out
    assert f"paperbot.resetrun apply --lib {env['data']} --archive {arch}" in out
    calls = env["log"].read_text().splitlines()
    assert any(c.startswith("stop") for c in calls) and not any(c.startswith("start") for c in calls)
