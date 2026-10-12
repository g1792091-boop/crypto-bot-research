"""Hunt round 2 server kit (PREREG_HUNT_R2.md 11-12): bootstrap_r2.sh and wait_go_r2.sh parse, the owners' guide
SERVER_R2_KO.md carries exactly the lines the kit prints, the kit's file names are the pin's KIT list, the go marker is
round 2's own, and the status parser's part labels are the select step's own pmap labels. Temporary folders only; the
repository's pin state is never read."""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from research.hunt_r2 import pin_r2 as PN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "research", "hunt_r2")
BOOT = os.path.join(KIT, "bootstrap_r2.sh")
WAIT = os.path.join(KIT, "wait_go_r2.sh")
GUIDE = os.path.join(KIT, "SERVER_R2_KO.md")


def _read(p: str) -> str:
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def test_kit_files_are_the_pins_kit_list():
    for rel in PN.KIT:
        assert os.path.exists(os.path.join(ROOT, rel)), rel


@pytest.mark.parametrize("path", [BOOT, WAIT])
def test_scripts_parse(path):
    subprocess.run(["bash", "-n", path], check=True)


def _restart_line(base: str = "/root/hunt_r2") -> str:
    """The restart line bootstrap_r2.sh prints on a real server (its own assignments, evaluated by bash)."""
    want = ("SELF=", "TM=", "SES=", 'if [ "$DRYRUN" = 1 ]; then RUNCMD=', "RESTART=")
    lines = [ln for ln in _read(BOOT).splitlines() if ln.startswith(want)]
    assert len(lines) == len(want)
    script = f"DRYRUN=0\nBASE={base}\nREPO=$BASE/crypto-bot-research\n" + "\n".join(lines) + '\necho "$RESTART"\n'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_guide_restart_line_is_the_one_the_kit_prints():
    line = _restart_line()
    assert line.startswith("bash /root/hunt_r2/crypto-bot-research/research/hunt_r2/bootstrap_r2.sh idle && {")
    assert "tmux respawn-pane -k -t hunt-r2" in line and "tmux new -d -s hunt-r2" in line
    assert line in _read(GUIDE).splitlines()


def test_guide_one_line_waits_for_round_2s_go_commit():
    guide = _read(GUIDE)
    one = [ln for ln in guide.splitlines() if ln.startswith("apt-get")]
    assert len(one) == 1
    one = one[0]
    assert ("git clone -q -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git "
            "/root/hunt_r2/crypto-bot-research") in one
    assert "cp /root/hunt_r2/crypto-bot-research/research/hunt_r2/wait_go_r2.sh /root/hunt_r2/wait_go_r2.sh" in one
    assert one.endswith('tmux new -s hunt-r2 "bash /root/hunt_r2/wait_go_r2.sh; bash"')
    for cmd in ("status", "push"):
        assert f"bash /root/hunt_r2/crypto-bot-research/research/hunt_r2/bootstrap_r2.sh {cmd}" in guide
    assert "/root/r1_private.tgz" in guide and "/root/t2_private.tgz" in guide


def test_wait_go_marker_branch_and_handover():
    w = _read(WAIT)
    assert "MARK=research/hunt_r2/GO_COMMIT" in w
    assert "BR=${HUNT_R2_BRANCH:-claude/keen-pasteur-wav02u}" in w
    assert 'exec bash "$REPO/research/hunt_r2/bootstrap_r2.sh"' in w
    b = _read(BOOT)
    assert 'cp -f "$REPO/research/hunt_r2/wait_go_r2.sh" "$WAITER"' in b      # no go commit: wait again


def test_status_part_labels_are_the_select_steps_own():
    sel = _read(os.path.join(KIT, "select_r2.py"))
    labels = set()
    for lab in re.findall(r'label=f?"([^"]+)"', sel):
        labels |= {lab.replace("{null}", x) for x in ("a", "b")}
    boot = _read(BOOT)
    parts = re.search(r'^SEL_PARTS="([^"]+)"', boot, re.M).group(1).split("|")
    cpu = re.search(r'^SEL_CPU_MIN="([^"]+)"', boot, re.M).group(1).split()
    assert len(parts) == len(cpu) == 7
    assert set(parts) <= labels, set(parts) - labels


def _dry(tmp_path, *args):
    env_file = tmp_path / "dryenv.sh"
    base = tmp_path / "base"
    env_file.write_text(f"export HUNT_R2_BASE={base}\nexport HUNT_R2_REPO={ROOT}\nexport HUNT_R2_INBOX={tmp_path}\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("HUNT_R2_")}
    env["HUNT_R2_DRYENV"] = str(env_file)
    return subprocess.run(["bash", BOOT, "--dry-run", *args], capture_output=True, text=True, env=env, timeout=60)


def test_dry_run_status_and_idle_before_the_go_commit(tmp_path):
    r = _dry(tmp_path, "status")
    assert r.returncode == 0
    assert "아직 고정 전인데 기다리기가 멈춰 있습니다" in r.stdout
    assert r.stdout.strip().splitlines()[-1].startswith(f"HUNT_R2_DRYENV={tmp_path / 'dryenv.sh'} bash {BOOT} --dry-run idle")
    assert _dry(tmp_path, "idle").returncode == 0                  # nothing runs: the restart line goes on
    u = _dry(tmp_path, "update", "not-a-commit")
    assert u.returncode == 2 and "사용법" in u.stdout
