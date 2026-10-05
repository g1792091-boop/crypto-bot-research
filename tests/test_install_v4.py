"""deploy/install.sh for paper v4: with PAPERBOT_RESETTING=1 (set by the reset) the Obsidian export, the DeepSeek-200
shadow test and the DeepSeek nightly recompute check are installed but their timers are not switched (on or off),
each one's real state is printed and docs/server-setup-v4.md says which to turn on after the reset checks; without
the variable the timers are switched on as before. The dscheck units are installed, waited for during a code swap, and have their own folder."""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SH = (REPO / "deploy" / "install.sh").read_text(encoding="utf-8")
TIMERS = ("paperbot-obsidian.timer", "paperbot-shadow200.timer", "paperbot-dscheck.timer")


def _enable_block() -> str:
    start = SH.index('if [ "${PAPERBOT_RESETTING:-0}" = "1" ]; then')
    end = SH.index("\nfi\n", start) + len("\nfi\n")
    return SH[start:end]


def _run(tmp_path, env_value, enabled=()):
    log = tmp_path / "systemctl.log"
    # a fake systemctl: logs every call; is-enabled / is-active answer like the real one (FAKE: the enabled timers)
    on = " ".join(enabled)
    script = (f'systemctl() {{ echo "$*" >> "{log}"; case "$1" in '
              f'is-enabled) for t in {on or "none"}; do [ "$t" = "$2" ] && {{ echo enabled; return 0; }}; done; '
              f'echo disabled; return 1 ;; '
              f'is-active) for t in {on or "none"}; do [ "$t" = "$2" ] && {{ echo active; return 0; }}; done; '
              f'echo inactive; return 3 ;; esac; }}\n'
              + ("" if env_value is None else f"export PAPERBOT_RESETTING={env_value}\n")
              + "set -euo pipefail\n" + _enable_block())
    env = {"PATH": "/usr/bin:/bin"}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    return r.stdout, calls


def test_install_sh_is_valid_bash():
    assert subprocess.run(["bash", "-n", str(REPO / "deploy" / "install.sh")]).returncode == 0


def test_without_the_variable_the_three_timers_are_switched_on(tmp_path):
    for value in (None, "0", ""):
        out, calls = _run(tmp_path, value)
        assert calls == [f"enable --now {t}" for t in TIMERS], (value, calls)
        assert "리셋 중" not in out
        (tmp_path / "systemctl.log").unlink()


def test_while_resetting_nothing_is_switched_and_each_timers_real_state_is_printed(tmp_path):
    # review finding 2: no blanket "not switched on" line; each timer's real is-enabled / is-active state, and the
    # guide (not a command for all three) says which to turn on after the reset checks
    out, calls = _run(tmp_path, "1", enabled=("paperbot-shadow200.timer",))
    assert not [c for c in calls if not c.startswith(("is-enabled", "is-active"))], calls
    assert sorted(c.split()[-1] for c in calls if c.startswith("is-enabled")) == sorted(TIMERS)
    assert "리셋 중" in out and "여기서 켜거나 끄지 않았습니다" in out
    assert "paperbot-shadow200.timer: 자동 시작 enabled, 지금 active" in out
    assert "paperbot-obsidian.timer: 자동 시작 disabled, 지금 inactive" in out
    assert "paperbot-dscheck.timer: 자동 시작 disabled, 지금 inactive" in out
    assert "docs/server-setup-v4.md 5단계" in out and "enable --now" not in out
    assert (REPO / "docs" / "server-setup-v4.md").exists()


def test_the_units_are_installed_either_way_and_dscheck_is_known():
    loop = re.search(r"for u in ([^;]*); do\s+install -m 644", SH)
    units = set(loop.group(1).replace("\\", " ").split())
    assert {"paperbot-dscheck.service", "paperbot-dscheck.timer", "paperbot-obsidian.service",
            "paperbot-obsidian.timer", "paperbot-shadow200.service", "paperbot-shadow200.timer"} <= units
    assert loop.start() < SH.index('if [ "${PAPERBOT_RESETTING:-0}" = "1" ]')      # installed before the switch
    for u in ("paperbot-dscheck.service", "paperbot-dscheck.timer"):
        assert (REPO / "deploy" / u).exists()
    jobs = re.search(r'JOBS="([^"]*)"', SH).group(1).replace("\\", " ").split()
    assert "paperbot-dscheck.service" in jobs                       # a code swap waits for a running check
    assert "install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/dscheck" in SH
    # the variable decides only the timers' switch: no other line reads it
    code = [ln for ln in SH.splitlines() if not ln.lstrip().startswith("#")]
    assert sum("PAPERBOT_RESETTING" in ln for ln in code) == 1
    # every enable of these timers sits in the not-resetting branch
    block = _enable_block()
    else_part = block[block.index("\nelse\n"):]
    for t in TIMERS:
        acts = [ln for ln in SH.splitlines() if f"systemctl enable --now {t}" in ln and not ln.lstrip().startswith(("echo", "#"))]
        assert len(acts) == 1 and acts[0] in else_part, t
