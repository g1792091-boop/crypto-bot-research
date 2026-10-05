"""deploy/paperbot-reset.sh: syntax (bash -n, shellcheck when installed), what it archives and keeps (never the
agents' memory, the owners' inbox or a market recorder), and the --dry-run / refusal paths with a fake systemctl
(nothing is stopped, moved or changed)."""

import hashlib
import json
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
                  "failalert", "price_alerts.json", "debate", "shadow200", "obsidian")


def _list(name):
    m = re.search(rf'^{name}="([^"]*)"$', TEXT, re.M)
    assert m, name
    return [w for w in m.group(1).split() if w != "\\"]            # (a line continuation)


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
                             "checkpoint_bars", "rehearsal", "dscheck"}
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
    # the one exception: the DeepSeek check's bar cache (regenerable public klines) goes back from the archive
    back = [m for m in mvs if '"$DATA/dscheck/"' in m]
    assert back == ['if [ -e "$g" ]; then mv "$g" "$DATA/dscheck/"; fi'], back
    assert '"$ARCH/dscheck/$DSCHECK_CACHE"' in TEXT and _list("DSCHECK_CACHE") == ["bars5m.db"]
    mvs = [m for m in mvs if m not in back]
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
    # a stateful systemctl: FAKE_ACTIVE are running until stopped, started again by start; FAKE_STATES
    # ("unit=state ...", e.g. paperbot-live3=activating for a unit in auto-restart) gives other states until stopped;
    # FAKE_JOB_RUNS ("unit=n") is a oneshot job that answers "activating" n times, then "inactive"; is-active prints
    # the state (exit 0 only for "active"); FAKE_ENABLED answer is-enabled; `show -p LoadState` answers "loaded"
    # except for FAKE_NOT_LOADED; a start of a unit in FAKE_FAIL_START fails; starting paperbot-backup.service
    # writes today's backup folder like deploy/paperbot-backup.sh (a copy of each run database) unless
    # FAKE_BACKUP_EMPTY=1; `show -p Result` answers FAKE_RESULT (default success)
    fake.write_text(f"""#!/bin/bash
echo "$*" >> "{log}"
cmd="$1"; shift
case "$cmd" in
  is-active)
    u="${{@: -1}}"
    st=inactive
    for a in $FAKE_ACTIVE; do [ "$a" = "$u" ] && st=active; done
    for a in $FAKE_STATES; do [ "${{a%%=*}}" = "$u" ] && st="${{a#*=}}"; done
    for a in $FAKE_JOB_RUNS; do
      if [ "${{a%%=*}}" = "$u" ]; then
        c="{tmp_path}/runs.$u"; k=$(cat "$c" 2>/dev/null || echo 0); echo $((k+1)) > "$c"
        if [ "$k" -lt "${{a#*=}}" ]; then st=activating; else st=inactive; fi
      fi
    done
    grep -qx "$u" "{stopped}" && st=inactive
    [ "$1" = --quiet ] || echo "$st"
    [ "$st" = active ] && exit 0
    exit 3 ;;
  is-enabled)
    u="${{@: -1}}"
    for a in $FAKE_ENABLED; do [ "$a" = "$u" ] && exit 0; done
    exit 1 ;;
  show)
    u="${{@: -1}}"
    case "$*" in
      *LoadState*)
        for a in $FAKE_NOT_LOADED; do [ "$a" = "$u" ] && {{ echo not-found; exit 0; }}; done
        echo loaded ;;
      *) echo "${{FAKE_RESULT:-success}}" ;;
    esac ;;
  stop) for u in "$@"; do echo "$u" >> "{stopped}"; done ;;
  start)
    for u in "$@"; do
      for f in $FAKE_FAIL_START; do [ "$f" = "$u" ] && exit 1; done
      if [ "$u" = paperbot-backup.service ] && [ "${{FAKE_BACKUP_EMPTY:-0}}" != 1 ]; then
        d="$PAPERBOT_BACKUPS/$(date -u +%Y%m%d)"; mkdir -p "$d"
        for db in paper3 daily3 checkpoint agents3 inbox; do
          [ -f "$PAPERBOT_LIB/$db.db" ] && cp "$PAPERBOT_LIB/$db.db" "$d/$db.db"
        done
      fi
      grep -vx "$u" "{stopped}" > "{stopped}.n" || true; mv "{stopped}.n" "{stopped}"
    done ;;
esac
exit 0
""")
    fake.chmod(0o755)
    e = dict(os.environ, PAPERBOT_LIB=str(data), PAPERBOT_ETC=str(tmp_path / "etc"), PAPERBOT_PY=sys.executable,
             PAPERBOT_RESET_USER="", PAPERBOT_SYSTEMCTL=str(fake), PAPERBOT_RESET_HM="2200",
             PAPERBOT_BACKUPS=str(tmp_path / "backups"), FAKE_ENABLED="",
             FAKE_ACTIVE="paperbot-live3 paperbot-dash paperbot-agents.timer")
    return {"data": data, "env": e, "log": log, "tmp": tmp_path}


def _run(env, *args):
    return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=env["env"], timeout=120)


def test_dry_run_changes_nothing(env):
    before = _tree_hash(env["data"])
    r = _run(env, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "[멈출 것] paperbot-live3 paperbot-dash paperbot-agents.timer (" in out
    # without --agents-off the agents' tick comes back like the rest (owners' D15: P11's must-items landed)
    assert "[끝나고 다시 켤 것] paperbot-live3 paperbot-dash paperbot-agents.timer\n" in out
    assert "[꺼 둘 것]" not in out and "[에이전트 회의] 다시 켬(지금처럼)" in out
    assert "[계속 돌 것] paperbot-shadow200.timer" in out
    assert "  paper3.db" in out and "  tradealerts.json" in out and "  checkpoint_bars" in out
    keep = out.split("[그대로 둘 것]")[1].split("[agents3.db")[0]
    assert "agents3.db" in keep and "inbox.db" in keep and "price_alerts.json" in keep and "liq.db" in keep
    assert "loss:strat:V45_AMB: 812 -> 0" in out
    assert _tree_hash(env["data"]) == before
    calls = env["log"].read_text().splitlines()
    assert calls and all(c.startswith(("is-active", "is-enabled", "show")) for c in calls)
    assert "[옮기기 전에 새 백업] paperbot-backup.service" in out
    assert "paperbot-offsite.timer가 켜져 있지 않아 건너뜁니다" in out
    assert not (env["tmp"] / "backups").exists()


def test_dry_run_with_agents_off_shows_the_tick_kept_off_and_what_stops(env):
    env["env"]["FAKE_ENABLED"] = "paperbot-obsidian.timer"
    r = _run(env, "--dry-run", "--agents-off")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "[끝나고 다시 켤 것] paperbot-live3 paperbot-dash\n" in out
    assert ("[꺼 둘 것] paperbot-agents.timer (--agents-off: 에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음."
            in out)
    assert "[꺼 둘 것] paperbot-obsidian.timer (리셋 뒤 점검을 마치고 두 분이 켬" in out
    assert "[에이전트 회의] 꺼짐(--agents-off)" in out


def test_dry_run_shows_the_offsite_copy_when_its_timer_is_enabled(env):
    env["env"]["FAKE_ENABLED"] = "paperbot-offsite.timer"
    r = _run(env, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "paperbot-offsite.service도 한 번 돌립니다" in r.stdout
    assert not any(c.startswith("start") for c in env["log"].read_text().splitlines())


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
    assert all(c.startswith(("is-active", "is-enabled", "show")) for c in env["log"].read_text().splitlines())
    assert not any(c.startswith(("stop", "start")) for c in env["log"].read_text().splitlines())


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
    assert stops == ["stop " + " ".join(ALL_UNITS)]                    # every loaded unit, whatever its state
    # the fresh backup runs after everything stopped and before the move; no off-site copy (timer not enabled);
    # the agents' tick comes back without --agents-off (owners' D15)
    assert starts == ["start paperbot-backup.service",
                      "start paperbot-live3 paperbot-dash paperbot-tgtrades paperbot-agents.timer"]
    assert not any(c.startswith("disable") for c in calls)
    assert "에이전트 회의(paperbot-agents.timer): 켜짐" in r.stdout.split("요약")[1]
    assert "에이전트 꺼짐" not in r.stdout
    assert calls.index("start paperbot-backup.service") > calls.index(stops[0])
    out = r.stdout
    assert "no process has the run files open" in out and "요약" in out and "봇이 아직 새 계좌를 만들지 않았습니다" in out
    assert "agents3.db 백업: copied" in out
    assert out.index("backup ok:") < out.index("== 4. archive")
    assert "off-site copy skipped" in out
    day = next(p for p in (env["tmp"] / "backups").iterdir() if re.fullmatch(r"\d{8}", p.name))
    assert (day / "paper3.db").read_text() == "x" and (day / "daily3.db").exists()


ALL_UNITS = _list("SERVICES") + _list("TIMERS")


def _starts(env):
    return [c for c in env["log"].read_text().splitlines() if c.startswith("start")]


def test_a_crash_looping_or_failed_unit_is_stopped_and_the_right_set_restarted(env):
    """Review m1: `is-active` is not "active" for a service waiting to auto-restart ("activating"): it is stopped
    anyway (every loaded unit is), and started again; an enabled unit that failed comes back too; a failed unit that
    is not enabled is stopped but stays off; a unit that is not installed is not touched."""
    _yes_env(env, FAKE_ACTIVE="paperbot-dash paperbot-agents.timer",
             FAKE_STATES="paperbot-live3=activating paperbot-tgtrades=failed paperbot-evening.timer=failed",
             FAKE_ENABLED="paperbot-tgtrades paperbot-daily3.timer", FAKE_NOT_LOADED="paperbot-offsite.timer")
    r = _run(env, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = env["log"].read_text().splitlines()
    stops = [c for c in calls if c.startswith("stop")]
    want = [u for u in ALL_UNITS if u != "paperbot-offsite.timer"]
    assert stops == ["stop " + " ".join(want)]
    assert _starts(env)[-1] == ("start paperbot-live3 paperbot-dash paperbot-tgtrades paperbot-agents.timer "
                                "paperbot-daily3.timer")
    assert "paperbot-live3: activating" in r.stdout and "paperbot-tgtrades: failed, enabled" in r.stdout
    assert not (env["data"] / "paper3.db").exists()


def test_a_running_oneshot_job_is_waited_for(env):
    """A oneshot job (nightly check, backup, checkpoint) shows "activating" while it runs, never "active"."""
    _yes_env(env, FAKE_JOB_RUNS="paperbot-daily3.service=2", PAPERBOT_RESET_POLL="0")
    r = _run(env, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("waiting for a scheduled job to finish: paperbot-daily3.service") == 2
    assert r.stdout.index("waiting for a scheduled job") < r.stdout.index("== 2. fresh backup")


def test_dry_run_lists_a_crash_looping_unit(env):
    env["env"].update(FAKE_ACTIVE="paperbot-dash", FAKE_STATES="paperbot-live3=activating")
    r = _run(env, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[멈출 것] paperbot-live3 paperbot-dash (" in r.stdout
    assert "[끝나고 다시 켤 것] paperbot-live3 paperbot-dash\n" in r.stdout


def _yes_env(env, **extra):
    stub = env["tmp"] / "install.sh"
    stub.write_text("#!/bin/bash\nexit 0\n")
    env["env"].update(PAPERBOT_INSTALL=str(stub), PAPERBOT_RESET_WAIT="0", ALLOW_DIRTY="1",
                      **{"FAKE_ACTIVE": "paperbot-live3 paperbot-dash", **extra})


@pytest.mark.parametrize("fail", [{"FAKE_FAIL_START": "paperbot-backup.service"}, {"FAKE_RESULT": "exit-code"},
                                  {"FAKE_BACKUP_EMPTY": "1"}])
def test_a_failed_backup_stops_before_anything_moves(env, fail):
    _yes_env(env, **fail)
    r = _run(env, "--yes")
    assert r.returncode == 1, r.stdout
    out = r.stdout
    assert "새 백업" in out and "아무 파일도 옮기지 않고" in out and "단계 backup" in out
    assert "이전 실행은 그대로입니다" in out and "sudo systemctl start paperbot-live3 paperbot-dash" in out
    assert "journalctl -u paperbot-backup" in out
    assert (env["data"] / "paper3.db").exists() and not (env["data"] / "archive").exists()
    calls = env["log"].read_text().splitlines()
    assert not any(c.startswith("start paperbot-live3") for c in calls)
    assert "start paperbot-offsite.service" not in calls


def test_the_offsite_copy_runs_when_enabled_and_its_failure_only_warns(env):
    _yes_env(env, FAKE_ENABLED="paperbot-offsite.timer")
    r = _run(env, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = env["log"].read_text().splitlines()
    starts = [c for c in calls if c.startswith("start")]
    assert starts[:2] == ["start paperbot-backup.service", "start paperbot-offsite.service"]
    assert "off-site copy: sent" in r.stdout
    # a second reset (fresh tree) where the off-site copy fails: warned twice (step and summary), the run goes on
    for f in ("paper3.db", "daily3.db"):
        (env["data"] / f).write_text("x")
    env["log"].write_text("")
    (env["tmp"] / "stopped").write_text("")
    env["env"]["FAKE_FAIL_START"] = "paperbot-offsite.service"
    r = _run(env, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "경고: 서버 밖 복사(paperbot-offsite.service)가 실패했습니다" in out
    assert "서버 밖 복사는 실패했습니다" in out.split("요약")[1]
    assert not (env["data"] / "paper3.db").exists()


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
    assert any(c.startswith("stop") for c in calls)
    assert [c for c in calls if c.startswith("start")] == ["start paperbot-backup.service"]   # the bot stays off


def test_proc_fallback_finds_an_open_run_file_under_pipefail(tmp_path):
    """Review 3b m1: without fuser and lsof the /proc walk must still see a holder (find over /proc exits 1 when a
    PID vanishes mid-walk; a `find | grep -q` pipeline then reads false under pipefail)."""
    fn = re.search(r"^holders\(\) \{\n.*?^\}\n", TEXT, re.S | re.M).group(0)
    data = tmp_path / "lib"
    data.mkdir()
    (data / "agents3.db").write_text("x")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    os.symlink(shutil.which("find"), bin_ / "find")              # no fuser, no lsof on this PATH
    holder = subprocess.Popen([sys.executable, "-c", "import sys, time; f = open(sys.argv[1]); time.sleep(60)",
                               str(data / "agents3.db")])
    try:
        import time
        deadline = time.time() + 10
        while not any(os.path.realpath(os.path.join(f"/proc/{holder.pid}/fd", fd)) == str(data / "agents3.db")
                      for fd in os.listdir(f"/proc/{holder.pid}/fd")) and time.time() < deadline:
            time.sleep(0.05)
        script = f"set -Eeuo pipefail\nARCHIVE_DBS='paper3.db daily3.db checkpoint.db'\nDATA='{data}'\n{fn}\nholders\n"
        r = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=60,
                           env={"PATH": str(bin_)})
        assert r.returncode == 0, r.stderr
        assert r.stdout.split() == ["agents3.db"], (r.stdout, r.stderr)
    finally:
        holder.kill()
        holder.wait()
    r = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=60, env={"PATH": str(bin_)})
    assert r.returncode == 0 and r.stdout.strip() == ""                                    # nobody holds it now


def test_install_puts_fuser_on_the_server():
    with open(os.path.join(ROOT, "deploy", "install.sh"), encoding="utf-8") as fh:
        apt = re.search(r"apt-get [^\n]*install -yq ([^\n]*\\\n[^\n]*)", fh.read()).group(1)
    assert "psmisc" in apt.split()


def test_yes_keeps_a_pre_reset_copy_apart_from_the_nightly_folder(env):
    """Review 3b m2: the 08:40 KST nightly backup rewrites today's folder with the NEW run; the reset keeps the
    stopped run's copy in <date>-before-reset-<time>/<date>/ (a folder offsite.py sends with --from/--date)."""
    from paperbot import offsite
    _yes_env(env, FAKE_ENABLED="paperbot-offsite.timer", FAKE_FAIL_START="paperbot-offsite.service")
    r = _run(env, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    backups = env["tmp"] / "backups"
    days = sorted(p.name for p in backups.iterdir())
    assert len(days) == 2 and re.fullmatch(r"\d{8}", days[0]) and re.fullmatch(rf"{days[0]}-before-reset-\d{{6}}Z",
                                                                                days[1])
    kept = backups / days[1]
    assert sorted(os.listdir(kept)) == [days[0]]
    assert (kept / days[0] / "paper3.db").read_text() == "x" and (kept / days[0] / "agents3.db").exists()
    # the nightly backup of the same UTC day now copies the new run into the day's folder: the kept copy stays
    (env["data"] / "paper3.db").write_text("new run")
    subprocess.run([env["env"]["PAPERBOT_SYSTEMCTL"], "start", "paperbot-backup.service"], env=env["env"], check=True)
    assert (backups / days[0] / "paper3.db").read_text() == "new run"
    assert (kept / days[0] / "paper3.db").read_text() == "x"
    assert offsite.find_folder(kept, days[0], None) == kept / days[0]
    resend = f"python -m paperbot.offsite send --from {kept} --date {days[0]}"
    out = r.stdout
    assert f"pre-reset copy kept: {kept}/{days[0]}" in out
    assert resend in out.split("== 3.")[0] and resend in out.split("요약")[1]
    assert "같은 날짜 폴더, 이전 실행 복사본" not in out
    assert f"옮기기 전 새 백업: {kept}/{days[0]}" in out


def _new_run_after_a_reset(env, start_ago_ms=3_600_000):
    import time
    now = int(time.time() * 1000)
    start = now - start_ago_ms
    (env["data"] / "paper3.db").write_bytes(b"")
    c = sqlite3.connect(str(env["data"] / "paper3.db"))
    c.execute("CREATE TABLE accounts (account_id TEXT, strategy TEXT, timeframe TEXT, kind TEXT, created_ts INTEGER)")
    c.execute("INSERT INTO accounts VALUES ('V45_AMB@15m', 'V45_AMB', '15m', 'strategy', ?)", (start,))
    c.commit()
    c.close()
    a = sqlite3.connect(str(env["data"] / "agents3.db"))
    a.execute("INSERT INTO cursors (k, v) VALUES ('run:restarted', ?)",
              (json.dumps({"ts": start - 300_000, "archive": "/var/lib/paperbot/archive/run-x"}),))
    a.commit()
    a.close()


def test_a_second_yes_after_the_reset_is_refused_unless_forced(env):
    _new_run_after_a_reset(env)
    _yes_env(env)
    before = _tree_hash(env["data"])
    r = _run(env, "--dry-run")
    assert r.returncode == 0 and "재시작은 이미 끝났습니다" in r.stdout and "--yes는 거절됩니다" in r.stdout
    r = _run(env, "--yes")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "재시작은 이미 끝났습니다" in r.stdout and "--yes --force-again" in r.stdout
    assert "아무것도 멈추거나 옮기지 않았습니다" in r.stdout
    assert _tree_hash(env["data"]) == before
    assert not any(c.startswith(("stop", "start")) for c in env["log"].read_text().splitlines())
    r = _run(env, "--yes", "--force-again")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "--force-again" in r.stdout and not (env["data"] / "paper3.db").exists()
    assert subprocess.run(["bash", SCRIPT, "--yes", "--again"], capture_output=True, text=True).returncode == 2


def test_a_run_older_than_a_day_is_not_a_repeat(env):
    _new_run_after_a_reset(env, start_ago_ms=25 * 3_600_000)
    _yes_env(env)
    r = _run(env, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "재시작은 이미 끝났습니다" not in r.stdout


DOC = os.path.join(ROOT, "docs", "server-setup-v3.md")


@pytest.mark.parametrize("vintage", ["worktree", "HEAD", "613506c"])
def test_the_doc_budget_box_sets_each_line_once_on_any_agents_env(tmp_path, vintage):
    """Review 3b m4: the reset section's "사용량 설정" box, run on an agents.env made from the current example and
    from the 613506c-era one (only a commented #AGENTS_BUDGET= line, where a bare `sed` changed nothing), leaves
    exactly one AGENTS_BUDGET= line with the owners' value and one AGENTS_RESEARCH_EVERY_MIN=180, keeps the mode,
    and the agents read the intended limits."""
    from paperbot.agents.rooms import policy_from_env
    from paperbot.launchcheck import parse_env
    text = open(DOC, encoding="utf-8").read()
    sec = text[text.index("4. 사용량 설정"):]
    box = sec[sec.index("```bash\n") + 8:sec.index("   ```", sec.index("```bash\n") + 8)]
    want = re.search(r"^\s*B='(AGENTS_BUDGET=[^']*)'$", box, re.M).group(1)
    assert "/" not in want and "&" not in want
    ex = (open(os.path.join(ROOT, "deploy", "agents.env.example"), encoding="utf-8").read() if vintage == "worktree"
          else subprocess.run(["git", "-C", ROOT, "show", f"{vintage}:deploy/agents.env.example"], capture_output=True,
                              text=True, check=True).stdout)
    env = tmp_path / "agents.env"
    env.write_text(ex + "AGENTS_RESEARCH_EVERY_MIN=60\n")
    env.chmod(0o640)
    script = "\n".join(ln.strip() for ln in box.splitlines()).replace("sudo ", "").replace("/etc/paperbot/agents.env",
                                                                                            str(env))
    r = subprocess.run(["bash", "-c", "set -e\n" + script.replace("stat -c '%U:%G %a'", "stat -c '%a'")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    vals, bad, dup = parse_env(env.read_text())
    assert vals["AGENTS_BUDGET"] == want.split("=", 1)[1] and vals["AGENTS_RESEARCH_EVERY_MIN"] == "180"
    assert not dup, dup
    lines = env.read_text().splitlines()
    assert sum(ln.startswith("AGENTS_BUDGET=") for ln in lines) == 1
    assert sum(ln.startswith("AGENTS_RESEARCH_EVERY_MIN=") for ln in lines) == 1
    assert oct(env.stat().st_mode & 0o777) == "0o640" and r.stdout.strip().endswith("640")
    p = policy_from_env(vals)
    assert p.triggers.research_every_ms == 180 * 60_000
    caps = dict(x.split("=", 1) for x in want.split("=", 1)[1].split(","))
    total_calls, total_tokens = (int(v) for v in caps["total"].split(":"))
    assert tuple(p.total_budget)[:2] == (total_calls, total_tokens)


def test_the_doc_budget_box_and_the_env_template_hold_the_same_lines():
    text = open(DOC, encoding="utf-8").read()
    sec = text[text.index("4. 사용량 설정"):]
    want = re.search(r"^\s*B='(AGENTS_BUDGET=[^']*)'$", sec, re.M).group(1)
    ex = open(os.path.join(ROOT, "deploy", "agents.env.example"), encoding="utf-8").read().splitlines()
    assert [ln for ln in ex if ln.startswith("AGENTS_BUDGET=")] == [want]
    assert [ln for ln in ex if ln.startswith("AGENTS_RESEARCH_EVERY_MIN=")] == ["AGENTS_RESEARCH_EVERY_MIN=180"]


# ---------------------------------------------------------------------------------- paper v4 (owners 2026-10-05)
def test_v4_stop_lists_hold_the_debate_room_obsidian_and_dscheck_never_the_shadow_test():
    """The debate room reads paper3.db all the time and the Obsidian export / DeepSeek check read the run's files:
    stopped while the files move. The DeepSeek-200 shadow test (own database, pinned T0) is never stopped."""
    assert "paperbot-debate" in _list("SERVICES")
    for u in ("paperbot-obsidian.timer", "paperbot-dscheck.timer"):
        assert u in _list("TIMERS")
    for u in ("paperbot-obsidian.service", "paperbot-dscheck.service"):
        assert u in _list("JOBS")
    for name in ("SERVICES", "TIMERS", "JOBS"):
        assert not [u for u in _list(name) if "shadow200" in u], name
    # every unit file the lists name exists in deploy/
    for u in _list("SERVICES") + _list("TIMERS") + _list("JOBS"):
        f = u if "." in u else u + ".service"
        assert os.path.exists(os.path.join(ROOT, "deploy", f)), f
    assert _list("AFTER_CHECK_TIMERS") == ["paperbot-obsidian.timer", "paperbot-shadow200.timer",
                                           "paperbot-dscheck.timer"]
    # the same three timers install.sh leaves alone while resetting (it prints each one's state)
    inst = open(os.path.join(ROOT, "deploy", "install.sh"), encoding="utf-8").read()
    assert "for t in " + " ".join(_list("AFTER_CHECK_TIMERS")) + "; do" in inst


def test_v4_install_runs_in_resetting_mode_and_the_after_check_timers_stay_off(env):
    """--agents-on (the default, said explicitly) brings the tick back; the Obsidian export and the DeepSeek check are
    stopped and kept off (disabled, not started) whatever they were; the shadow test is never touched; the DeepSeek
    check's bar cache stays in place while its run summaries are archived."""
    stub = env["tmp"] / "install.sh"
    stub.write_text('#!/bin/bash\necho "resetting=${PAPERBOT_RESETTING:-}" >> "%s"\n' % (env["tmp"] / "installed"))
    env["env"].update(PAPERBOT_INSTALL=str(stub), PAPERBOT_RESET_WAIT="0", ALLOW_DIRTY="1",
                      FAKE_ACTIVE="paperbot-live3 paperbot-dash paperbot-debate paperbot-agents.timer "
                                  "paperbot-obsidian.timer paperbot-shadow200.timer",
                      FAKE_ENABLED="paperbot-agents.timer paperbot-dscheck.timer")
    ds = env["data"] / "dscheck"
    (ds / "days").mkdir(parents=True)
    (ds / "last.txt").write_text("old run\n")
    (ds / "days" / "2026-10-04.json").write_text("{}")
    (ds / "bars5m.db").write_text("cache")
    r = _run(env, "--agents-on", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (env["tmp"] / "installed").read_text() == "resetting=1\n"
    calls = env["log"].read_text().splitlines()
    stops = [c for c in calls if c.startswith("stop")]
    assert len(stops) == 1 and "paperbot-debate" in stops[0] and "paperbot-obsidian.timer" in stops[0]
    assert "shadow200" not in " ".join(c for c in calls if c.startswith(("stop", "start", "disable")))
    assert _starts(env)[-1] == "start paperbot-live3 paperbot-dash paperbot-debate paperbot-agents.timer"
    assert [c for c in calls if c.startswith("disable")] == ["disable paperbot-obsidian.timer paperbot-dscheck.timer"]
    out = r.stdout
    assert "[꺼 둘 것] paperbot-obsidian.timer (리셋 뒤 점검을 마치고" in out and "에이전트 꺼짐" not in out
    assert ("점검에 [고칠 것]이 없으면 켜기: sudo systemctl enable --now paperbot-obsidian.timer paperbot-shadow200.timer "
            "paperbot-dscheck.timer") in out
    assert "리셋 뒤 점검을 마치고 켤 타이머(지금 상태):" in out and "paperbot-dscheck.timer: 자동 시작" in out
    # the run's dscheck summaries are archived, the bar cache is not
    arch = next((env["data"] / "archive").iterdir())
    assert (arch / "dscheck" / "last.txt").exists() and (arch / "dscheck" / "days" / "2026-10-04.json").exists()
    assert not (arch / "dscheck" / "bars5m.db").exists()
    assert sorted(os.listdir(ds)) == ["bars5m.db"] and (ds / "bars5m.db").read_text() == "cache"


def test_v4_agents_off_keeps_the_tick_off_and_says_what_stops(env):
    stub = env["tmp"] / "install.sh"
    stub.write_text("#!/bin/bash\ntrue\n")
    env["env"].update(PAPERBOT_INSTALL=str(stub), PAPERBOT_RESET_WAIT="0", ALLOW_DIRTY="1",
                      FAKE_ENABLED="paperbot-agents.timer")
    r = _run(env, "--yes", "--agents-off")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = env["log"].read_text().splitlines()
    assert _starts(env)[-1] == "start paperbot-live3 paperbot-dash"
    assert "disable paperbot-agents.timer" in calls
    assert calls.index("disable paperbot-agents.timer") < calls.index(_starts(env)[-1])
    summary = r.stdout.split("요약")[1]
    assert "!! 에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음 (paperbot-agents.timer 꺼짐, --agents-off)" in summary
    assert "sudo systemctl enable --now paperbot-agents.timer" in summary


def test_v4_flags_in_any_order_and_unknown_ones_refused():
    for args in (["--agents-off"], ["--force-again"], ["--yes", "--dry-run"], ["--yes", "--agent-off"],
                 ["--yes", "--agents-on", "--agents-off"], ["--agents-off", "--dry-run", "--agents-on"]):
        r = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True)
        assert r.returncode == 2 and "--agents-off" in r.stdout, args
    assert 'AGENTS_OFF_KO="에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음"' in TEXT
    from paperbot import launchcheck as L
    assert L.AGENTS_OFF_KO == "에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음"
    assert "5m accounts are gone" not in TEXT and "156" not in TEXT and "144" not in TEXT


REHEARSE = os.path.join(ROOT, "deploy", "rehearse-reset.sh")


def test_rehearse_script_syntax():
    subprocess.run(["bash", "-n", REHEARSE], check=True)
    sc = shutil.which("shellcheck")
    if sc is not None:
        r = subprocess.run([sc, REHEARSE], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout
    text = open(REHEARSE, encoding="utf-8").read()
    assert "set -Eeuo pipefail" in text and "PAPERBOT_LIB=\"$W/lib\"" in text
    # it never acts on the real server: the reset only ever gets the fake systemctl and the stub install
    assert 'PAPERBOT_SYSTEMCTL="$W/stub/systemctl"' in text and 'PAPERBOT_INSTALL="$W/stub/install.sh"' in text
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        assert not re.search(r"\brm\s+-|\bmv\s", code), line
        assert not re.search(r'REAL_SYSTEMCTL"? (stop|start|disable|enable|restart)', code), line


def test_rehearse_reset_on_copies_passes_and_leaves_the_source_alone(tmp_path):
    """The whole rehearsal on a fake server: a v3 paper3.db, the agents' and the owners' databases; a fake "real"
    systemctl that only answers questions. The source folder is unchanged; every check passes."""
    if os.geteuid() != 0:
        pytest.skip("the script refuses to run without root")
    from paperbot.store3 import Store3
    src = tmp_path / "src"
    src.mkdir()
    st = Store3(str(src / "paper3.db"))
    for tf in ("15m", "30m", "1h", "4h"):
        for k in range(36):
            st.add_account(f"S{k}@{tf}", f"S{k}", tf, "strategy", 1_790_000_000_000, "paper-v3")
    st.commit()
    st.close()
    a = R.open_agents(str(src / "agents3.db"))
    R.ensure_rooms(a)
    a.execute("INSERT INTO cursors VALUES ('loss:strat:V45_AMB', '5')")
    a.commit()
    a.close()
    R.open_inbox_rw(str(src / "inbox.db")).close()
    (src / "tradealerts.json").write_text("{}")
    real = tmp_path / "systemctl"
    real.write_text("""#!/bin/bash
cmd="$1"; shift
u="${@: -1}"
echo "$cmd $*" >> "%s"
case "$cmd" in
  is-active) case "$u" in paperbot-live3|paperbot-debate|paperbot-agents.timer|paperbot-obsidian.timer|\
paperbot-shadow200.timer) [ "$1" = --quiet ] || echo active; exit 0;; esac; [ "$1" = --quiet ] || echo inactive; exit 3 ;;
  is-enabled) case "$u" in paperbot-live3|paperbot-agents.timer) exit 0;; esac; exit 1 ;;
  show) echo loaded ;;
  *) echo "NOT ALLOWED $cmd" >> "%s"; exit 1 ;;
esac
""" % (tmp_path / "real.log", tmp_path / "real.log"))
    real.chmod(0o755)
    before = _tree_hash(src)
    env = dict(os.environ, PAPERBOT_LIB=str(src), REHEARSE_BASE=str(tmp_path / "base"), PAPERBOT_ETC=str(tmp_path / "etc"),
               PAPERBOT_PY=sys.executable, PAPERBOT_RESET_USER="", REHEARSE_REAL_SYSTEMCTL=str(real), ALLOW_DIRTY="1",
               PAPERBOT_RESET_POLL="0")
    r = subprocess.run(["bash", REHEARSE], capture_output=True, text=True, env=env, timeout=300)
    out = r.stdout
    from paperbot import launchcheck as L
    hashed = all(k == "OK" for k, _ in L.rules_lines(ROOT))
    if hashed:                       # the release: every check passes
        assert r.returncode == 0, out[-3000:] + r.stderr[-2000:]
        assert "[실패" not in out and "[OK] 연습 리셋 통과" in out
    else:                            # the v4 documents are not hashed yet (before the release): only that check fails
        assert r.returncode == 1, out[-3000:] + r.stderr[-2000:]
        assert [ln for ln in out.splitlines() if ln.startswith("[실패")] == [
            "[실패] 규칙 문서(v3·v4)가 해시 파일과 같음 (launchcheck와 같은 점검)", "[실패 1개] 위 [실패] 줄과 "
            + out.split("[실패 1개] 위 [실패] 줄과 ")[1].splitlines()[0]]
    for word in ("paperbot-debate 멈춤 목록에 있음", "paperbot-obsidian.timer 멈춤 목록에 있음",
                 "shadow200)은 멈추지 않음", "에이전트 회의 타이머는 다시 켬(--agents-off 없음",
                 "딥시크 밤 재계산 타이머는 다시 켜지 않음", "원래 계좌 331개 = 매매법 144",
                 "PAPERBOT_RESETTING=1"):
        assert word in out, word
    assert _tree_hash(src) == before                               # the real folder is only read
    assert "NOT ALLOWED" not in (tmp_path / "real.log").read_text()


GUIDE = os.path.join(ROOT, "docs", "server-setup-v4.md")


def test_v4_guide_has_the_staging_run_the_reset_and_no_v3_numbers():
    text = open(GUIDE, encoding="utf-8").read()
    # the two lines the guide quotes verbatim name the core group's own 144 (P13): the start banner (live3 cmd_run,
    # split by group) and the first full 09:20 parity line (daily3); both built here from config, then left out
    from paperbot import daily3
    from paperbot.config import V4_ACCOUNTS, V4_GROUP_ACCOUNTS
    banner = (f"paper v4 started: {V4_ACCOUNTS} accounts ("
              + ", ".join(f"{g} {n}" for g, n in V4_GROUP_ACCOUNTS.items()) + "), brackets: …, taker fee …%")
    parity = f"재계산 일치 {V4_ACCOUNTS}/{V4_ACCOUNTS}" + daily3._split_text(
        [(g, f"{n}/{n}") for g, n in V4_GROUP_ACCOUNTS.items()])
    assert text.count(banner) == 2 and parity in text
    text = text.replace(banner, "").replace(parity, "")
    for word in ("156", "144", "5분봉 제외", "뺐음"):
        assert word not in text, word
    # the staging run: its own unit, database and env file without Telegram / healthchecks, the 01:00 boundary
    assert "sudo systemd-run --unit=paper4-staging --collect --uid=paperbot --gid=paperbot" in text
    assert "--db /var/lib/paperbot/staging/paper4.db" in text and "01:00" in text
    assert "grep -E '^BINANCE_API_(KEY|SECRET)='" in text and "TELEGRAM|DEADMAN" in text
    assert "멈춤 기준" in text and "60초" in text and "30초" in text
    # the commands it names exist with these options
    assert "sudo bash deploy/rehearse-reset.sh" in text and os.path.exists(REHEARSE)
    assert "sudo bash deploy/paperbot-reset.sh --yes" in text and "--agents-off" in TEXT and "--agents-off" in text
    assert "--agents-off" in open(REHEARSE, encoding="utf-8").read()
    assert "--force-again" in text and "paperbot.launchcheck --stage after" in text
    from paperbot import launchcheck as L
    assert "--db" in open(L.__file__, encoding="utf-8").read()
    after = re.search(r"enable --now (paperbot-obsidian\.timer [^\n`]*)", text).group(1).split()
    assert after == _list("AFTER_CHECK_TIMERS")
    assert "되돌리기" in text and "/opt/crypto-bot-research.old" in text


def test_v4_guide_python_boxes_run_on_a_v4_database(tmp_path):
    """Every `python - <db> <<'PY'` box of the guide runs on a v4-shaped database (read-only) without an error."""
    from paperbot.config import v4_account_defs
    from paperbot.store3 import Store3
    db = str(tmp_path / "paper4.db")
    st = Store3(db)
    for d in v4_account_defs([f"S{k}" for k in range(36)]):
        st.add_account(f"{d['strategy']}@{d['timeframe']}", d["strategy"], d["timeframe"], d["kind"], 1, "paper-v4",
                       None, d["data"])
    st.conn.execute("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, delay_ms, status) "
                    "VALUES (4 * 3600 * 1000, '5m', 'REEL_H1', 'BTCUSDT', 1, 9000, 'SUBMITTED')")
    st.conn.execute("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, delay_ms, status) "
                    "VALUES (4 * 3600 * 1000, '15m', 'F9_FVG', 'ETHUSDT', -1, 21000, 'SUBMITTED')")
    st.commit()
    st.close()
    text = open(GUIDE, encoding="utf-8").read()
    boxes = re.findall(r"python - [^\n]*<<'PY'\n(.*?)\nPY\n", text, re.S)
    assert len(boxes) == 2
    for code in boxes:
        r = subprocess.run([sys.executable, "-", db], input=code, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "REEL_H1" in r.stdout
