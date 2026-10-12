"""Hunt round 2 server kit (PREREG_HUNT_R2.md 11-12): bootstrap_r2.sh and wait_go_r2.sh parse, the owners' guide
SERVER_R2_KO.md carries exactly the lines the kit prints, the kit's file names are the pin's KIT list, the go marker is
round 2's own, and the status parser's part labels are the select step's own pmap labels. Temporary folders only; the
repository's pin state is never read."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

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
    env = {k: v for k, v in os.environ.items() if not k.startswith("HUNT_R2_") and k != "DRYRUN"}   # a rehearsal's
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True, env=env)   # tmux -L
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
    assert len(parts) == len(cpu) == 6
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
    last = r.stdout.strip().splitlines()[-1]
    assert last.startswith(f"HUNT_R2_DRYENV={tmp_path / 'dryenv.sh'} bash {BOOT} --dry-run idle")
    assert _dry(tmp_path, "idle").returncode == 0                  # nothing runs: the restart line goes on
    u = _dry(tmp_path, "update", "not-a-commit")
    assert u.returncode == 2 and "사용법" in u.stdout


# ------------------------------------------------------------------ fixes after the 2026-10-12 review
def _env_file(tmp_path, base, extra=""):
    env_file = tmp_path / "dryenv.sh"
    env_file.write_text(f"export HUNT_R2_BASE={base}\nexport HUNT_R2_REPO={ROOT}\nexport HUNT_R2_INBOX={tmp_path}\n"
                        + extra)
    return env_file


def _run(env_file, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HUNT_R2_")}
    env["HUNT_R2_DRYENV"] = str(env_file)
    return subprocess.run(["bash", BOOT, "--dry-run", *args], capture_output=True, text=True, env=env, timeout=60)


def _stage_state(base, n, minutes_in, log_lines):
    import time
    os.makedirs(base, exist_ok=True)
    t0 = int(time.time()) - minutes_in * 60
    with open(os.path.join(base, "STAGE"), "w") as fh:
        fh.write(f"{n}|stage {n}|{t0}\n")
    with open(os.path.join(base, "STAGES"), "w") as fh:
        fh.write(f"0|run start|{t0}\n{n}|stage {n}|{t0}\n")
    with open(os.path.join(base, "STAGE_POS"), "w") as fh:
        fh.write("0")
    with open(os.path.join(base, "run.log"), "w") as fh:
        fh.write("".join(x + "\n" for x in log_lines))


def _fake_run(base):
    p = subprocess.Popen(["bash", "-c", 'exec -a "bash /x/research/hunt_r2/bootstrap_r2.sh" sleep 30'])
    with open(os.path.join(base, "RUNNING"), "w") as fh:
        fh.write(str(p.pid))
    return p


def _minutes(txt):
    m = re.search(r"약 (?:(\d+)시간 )?(\d+)분", txt)
    return int(m.group(1) or 0) * 60 + int(m.group(2))


def test_status_prints_the_verdict_time_and_the_reads_maximum_apart(tmp_path):
    base = str(tmp_path / "base")
    env_file = _env_file(tmp_path, base, "export HUNT_R2_NCPU=32\nexport HUNT_R2_GO=abcdef1\n")
    _stage_state(base, 6, 100, ["[event store (name, timeframe, coin)] 10200/10200 done, 1500s",
                                "[null (b′) units] 11700/17000 done, 4140s", "[null (b′) units] 11900/17000 done, 4200s"])
    p = _fake_run(base)
    try:
        out = _run(env_file, "status").stdout
    finally:
        p.kill()
    lines = out.splitlines()
    v = next(x for x in lines if x.strip().startswith("판정까지:"))
    m = next(x for x in lines if "참고 분석(고른 것이 있을 때만" in x)
    assert _minutes(m) - _minutes(v) >= 12 * 60                      # the reads cap is only in the second line
    assert _minutes(v) < 10 * 60
    assert "장부용 비공개 파일" in out


def test_status_pace_after_a_restart_is_not_the_resumed_parts_pace(tmp_path):
    base = str(tmp_path / "base")
    env_file = _env_file(tmp_path, base, "export HUNT_R2_NCPU=32\nexport HUNT_R2_GO=abcdef1\n")
    # a restart: 12,000 finished parts are counted in the first minute
    _stage_state(base, 6, 2, ["[null (a′) units] 12000/17000 done, 61s"])
    p = _fake_run(base)
    try:
        one = _minutes(next(x for x in _run(env_file, "status").stdout.splitlines() if "판정까지:" in x))
        _stage_state(base, 6, 3, ["[null (a′) units] 12000/17000 done, 61s", "[null (a′) units] 12150/17000 done, 121s"])
        two = _minutes(next(x for x in _run(env_file, "status").stdout.splitlines() if "판정까지:" in x))
    finally:
        p.kill()
    naive = 61 * 5000 // 12000 // 60 + 1                                # the old single-line pace (about 1 minute)
    assert one > naive + 30                                            # one line: the planned time for the rest
    assert two >= (60 * 4850 // 150) // 60                              # two lines: the pace between them


def test_inbox_line_shows_before_the_select_step(tmp_path):
    base = str(tmp_path / "base")
    env_file = _env_file(tmp_path, base, "export HUNT_R2_GO=abcdef1\n")
    (tmp_path / "r1_private.tgz").write_bytes(b"")
    _stage_state(base, 2, 1, [])
    p = _fake_run(base)
    try:
        out = _run(env_file, "status").stdout
    finally:
        p.kill()
    assert "장부용 비공개 파일(.tgz) 1개 받음" in out


def test_update_stays_open_after_a_select_refusal_before_computing(tmp_path):
    base = str(tmp_path / "base")
    env_file = _env_file(tmp_path, base, "export HUNT_R2_GO=abcdef1\n")
    _stage_state(base, 6, 1, ["refused: something before computing"])
    r = _run(env_file, "update", "abcdef2")
    assert r.returncode == 0 and "abcdef2" in r.stdout                 # stage 6 began, nothing computed
    os.makedirs(os.path.join(base, "private"), exist_ok=True)
    (tmp_path / "base" / "private" / "SELECT_STARTED").write_text("x")  # the select step's own marker
    r = _run(env_file, "update", "abcdef3")
    assert r.returncode == 1 and "이미 계산을 시작" in r.stdout


def _helper_code():
    b = _read(BOOT)
    i = b.index("<<'PYEOF'\n") + len("<<'PYEOF'\n")
    return b[i:b.index("\nPYEOF\n", i)]


def test_private_files_are_matched_by_sha256_not_by_name(tmp_path):
    import hashlib
    pub, priv, cand = tmp_path / "pub", tmp_path / "priv", tmp_path / "cand"
    for d in (priv, cand):
        d.mkdir()
    r1 = b'{"results": {"r1": 1}}'
    t2 = b'{"results": {"t2": 2}}'
    for rel, data in (("research/hunt/out/wide/test.json", r1), ("research/hiwr/out/test.json", t2)):
        f = pub / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"private_sha256": hashlib.sha256(data).hexdigest()}))
    (cand / "1.json").write_bytes(t2)                                  # track 2's file, found first
    (cand / "2.json").write_bytes(b"stale")
    (cand / "3.json").write_bytes(r1)
    out = subprocess.run([sys.executable, "-", "pickprivate", str(pub), str(priv), str(cand)], input=_helper_code(),
                         capture_output=True, text=True, cwd=str(tmp_path), timeout=60)
    assert out.returncode == 0, out.stderr
    assert (priv / "wide_test_private.json").read_bytes() == r1
    assert (priv / "test_private.json").read_bytes() == t2
    assert "sha256 matches" in out.stdout


def test_kit_reads_ledger_inputs_from_the_results_branches_only():
    b = _read(BOOT)
    body = b[b.index("put_public() {"):b.index("ledger_inputs() {")]
    assert '"$REPO/$p"' not in body and "checkout:" not in body
    assert "ulimit -n 65536" in b
    assert '--wall-s "$left"' in b and "pretest_stop" in b and "SKIP_PRETEST" in b
    assert "--ledger-extra" in b and '--ledger-public "$LPUB"' in b


def test_guide_warns_against_pasting_into_the_running_pane_and_has_no_block_storage():
    g = _read(GUIDE)
    assert "계산이 돌고 있는 tmux 화면 안에는 아무것도 붙여 넣지 마세요" in g
    assert "hunt-r2-disk" not in g and "Block Storage는 만들지 마세요" in g
    assert "r1_private.tgz" in g and "이름을 바꿔" in g
    assert "약 1.6배" in g
