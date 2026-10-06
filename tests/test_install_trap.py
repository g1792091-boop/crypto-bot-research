"""deploy/install.sh: a failure after the services were stopped for the code swap (an error, Ctrl+C, a dropped SSH
session) must not leave the bot down. The script's own code-swap section runs here against a temporary folder with a
fake systemctl: the trap puts the previous code back when the swap was cut in half and starts again exactly the
units the script stopped; a clean run starts them once and clears the trap."""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SH = (REPO / "deploy" / "install.sh").read_text(encoding="utf-8")
STOPPED = ("paperbot-live3", "paperbot-dash", "paperbot-agents.timer")


def _between(start: str, end: str) -> str:
    i = SH.index(start)
    return SH[i:SH.index(end, i)]


def _script(tmp_path: Path, after_swap: str = "", after_start: str = "") -> str:
    func = _between("restart_stopped() {", "\n}\n") + "\n}\n"
    swap = _between('UNITS="paperbot-live3', 'echo "== GH Coin')
    start = _between('if [ -n "$RUNNING" ]; then\n  systemctl start $RUNNING', "\ncat <<'NEXT'")
    log = tmp_path / "systemctl.log"
    active = " ".join(STOPPED)
    stubs = (
        f'systemctl() {{ echo "$*" >> "{log}"; case "$1" in '
        f'is-active) for u in {active}; do [ "$u" = "$3" ] && return 0; done; return 3 ;; '
        f'show) echo inactive ;; stop) [ "${{FAIL_STOP:-}}" = 1 ] && return 1; [ "${{HUP_AT_STOP:-}}" = 1 ] && kill -HUP $$; return 0 ;; '
        f'start) [ "${{FAIL_START:-}}" = 1 ] && return 1; return 0 ;; esac; }}\n'
        "chown() { :; }\nchmod() { :; }\n"
        '_mvn=0\nmv() { _mvn=$((_mvn+1)); [ "$_mvn" = "${FAIL_MV:-0}" ] && return 1; command mv "$@"; }\n')
    return (stubs + "set -euo pipefail\n"
            + f'APP="{tmp_path / "app"}"\nREPO_DIR="{tmp_path / "repo"}"\nCOMMIT=abc\nTAG=\nDIRTY=false\n'
            + func + swap + after_swap + "\n" + start + after_start + "\n")


def _run(tmp_path: Path, env: dict = None, after_swap: str = "", after_start: str = ""):
    for name, text in (("repo", "new"), ("app", "old")):
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        (d / "code.txt").write_text(text)
    log = tmp_path / "systemctl.log"
    if log.exists():
        log.unlink()
    r = subprocess.run(["bash", "-c", _script(tmp_path, after_swap, after_start)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", **(env or {})}, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls


def _starts(calls):
    return [c for c in calls if c.startswith("start ")]


def test_a_clean_swap_starts_the_stopped_units_once_and_clears_the_trap(tmp_path):
    r, calls = _run(tmp_path, after_start="false")         # a failure after the clean start: no second start
    assert r.returncode == 1
    assert "stop " + " ".join(STOPPED) in calls and _starts(calls) == ["start " + " ".join(STOPPED)]
    assert "restarted: " + " ".join(STOPPED) in r.stdout and "stopped early" not in r.stdout
    assert (tmp_path / "app" / "code.txt").read_text() == "new"
    assert (tmp_path / "app.old" / "code.txt").read_text() == "old"


def test_a_swap_cut_in_half_puts_the_previous_code_back_and_starts_the_units_again(tmp_path):
    r, calls = _run(tmp_path, env={"FAIL_MV": "2"})        # 1: app -> app.old done, 2: app.new -> app fails
    assert r.returncode != 0
    assert (tmp_path / "app" / "code.txt").read_text() == "old"
    assert "put the previous code back" in r.stdout
    assert _starts(calls) == ["start " + " ".join(STOPPED)]
    assert "stopped early" in r.stdout and "started again: " + " ".join(STOPPED) in r.stdout


def test_an_error_after_the_swap_starts_the_units_again_on_the_new_code(tmp_path):
    r, calls = _run(tmp_path, after_swap="false")
    assert r.returncode == 1
    assert (tmp_path / "app" / "code.txt").read_text() == "new"
    assert _starts(calls) == ["start " + " ".join(STOPPED)] and "started again:" in r.stdout


def test_a_dropped_ssh_session_during_the_stop_starts_the_units_again(tmp_path):
    r, calls = _run(tmp_path, env={"HUP_AT_STOP": "1"})
    assert r.returncode == 129
    assert _starts(calls) == ["start " + " ".join(STOPPED)]


def test_a_failed_stop_starts_them_again_and_a_failed_start_says_what_to_type(tmp_path):
    r, calls = _run(tmp_path, env={"FAIL_STOP": "1"})
    assert r.returncode != 0 and _starts(calls) == ["start " + " ".join(STOPPED)]
    assert (tmp_path / "app" / "code.txt").read_text() == "old"
    r, calls = _run(tmp_path, env={"FAIL_START": "1"})
    assert r.returncode != 0 and len(_starts(calls)) == 2               # the script's own start, then the trap's
    assert "could not start again: " + " ".join(STOPPED) in r.stdout
    assert "sudo systemctl start " + " ".join(STOPPED) in r.stdout


def test_the_trap_is_armed_only_around_the_stop_and_never_names_the_debate_room_or_the_executor():
    arm = SH.index("trap restart_stopped EXIT")
    assert SH.index("for u in $UNITS; do") < arm < SH.index("systemctl stop $RUNNING")
    assert SH.index("trap - EXIT HUP INT TERM") > SH.index('echo "restarted:$RUNNING')
    func = _between("restart_stopped() {", "\n}\n")
    assert "debate" not in func and "executor" not in func
