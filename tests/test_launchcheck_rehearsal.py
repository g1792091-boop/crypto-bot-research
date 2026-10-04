"""launchcheck and the weekly checkpoint rehearsal timer: installed by install.sh but left off, so it is shown as
[참고] only (on, off, or a failed last run), never [고칠 것], and it is not asked of a server that lacks it."""

import os

from paperbot import launchcheck as L
from test_launchcheck import REPO_ROOT, Server, fixes, st, txt

T = "paperbot-rehearsal.timer"


def test_the_rehearsal_timer_is_optional_and_known():
    assert T in L.OPTIONAL_TIMERS and T in L.ALL_UNITS and "paperbot-rehearsal.service" in L.ALL_UNITS
    assert T not in L.TIMERS and T not in L.INSTALLED and T not in L.EXTRA_TIMERS
    assert os.path.exists(os.path.join(REPO_ROOT, "deploy", T))
    with open(os.path.join(REPO_ROOT, "deploy", "install.sh")) as fh:
        assert T in fh.read()


def test_off_on_and_failed_are_notes_only(tmp_path):
    srv = Server(tmp_path, "after")
    states = L.unit_states(srv.ctx())
    assert "rehearsal" not in txt(L.check_units(states, "after", True))           # not installed: not mentioned
    states[T] = {"LoadState": "loaded", "UnitFileState": "disabled", "ActiveState": "inactive"}
    lines = L.check_units(states, "after", True)
    assert L.FIX not in st(lines) and not any("rehearsal" in f for f in fixes(lines))
    assert any(x[0] == L.NOTE and f"{T}: 꺼져 있음 → sudo systemctl enable --now {T}" in x[1] for x in lines)
    states[T] = {"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "active",
                 "NextElapseUSecRealtime": "Wed 2026-10-07 03:30:00 UTC"}
    states["paperbot-rehearsal.service"] = {"LoadState": "loaded", "Result": "exit-code"}
    lines = L.check_units(states, "after", True)
    assert any(x[0] == L.OK and x[1].startswith(f"{T}: 켜짐") for x in lines)
    assert any(x[0] == L.NOTE and "paperbot-rehearsal의 지난 실행이 실패" in x[1] for x in lines)
    assert L.FIX not in st(lines)
    assert T not in L.start_command(states)                                         # the owners turn it on
    assert "rehearsal" not in txt(L.check_units(states, "before", True))
