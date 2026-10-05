"""The deploy files: the failure alert of the scheduled jobs, the agents' pinned Claude Code, the GH Coin pack of the
nightly backup."""
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from paperbot import failalert as FA
from paperbot import offsite as off

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"


def _unit(name: str) -> dict:
    """{section: [lines]} of a unit file, comments left out."""
    out: dict = {}
    sec = ""
    for ln in (DEPLOY / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        out.setdefault(sec, []).append(ln)
    return out


def test_failed_scheduled_jobs_send_one_korean_warning():
    for unit in FA.JOBS_KO:                          # every job the handler names has the hook, and the other way
        assert "OnFailure=paperbot-failed@%n.service" in _unit(unit)["[Unit]"], unit
    hooked = {p.name for p in DEPLOY.glob("*.service")
              if any(ln.startswith("OnFailure=") for lines in _unit(p.name).values() for ln in lines)}
    assert hooked == set(FA.JOBS_KO)
    t = _unit("paperbot-failed@.service")["[Service]"]
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.failalert %i" in t
    assert "User=paperbot" in t and "EnvironmentFile=/etc/paperbot/live.env" in t
    assert "UnsetEnvironment=BINANCE_API_KEY BINANCE_API_SECRET DEADMAN_URL" in t
    assert not any(ln.startswith("OnFailure=") for ln in _unit("paperbot-failed@.service").get("[Unit]", []))
    # a deploy or a restore stops a running agent pass on purpose: no alert for that (a timeout still alerts)
    assert "SuccessExitStatus=SIGTERM" in _unit("paperbot-agents.service")["[Service]"]
    inst = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    loop = re.search(r"for u in ([^;]*); do\s+install -m 644", inst).group(1)
    assert "paperbot-failed@.service" in loop.replace("\\", " ").split()
    assert "install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/failalert" in inst


def test_the_owners_check_of_the_units_shows_only_the_settings():
    """The owners' check after a deploy (`systemctl cat <the five jobs> | grep -E ...`): one line per setting, no
    comment that only mentions one (6 failure hooks with the weekly rehearsal and the Obsidian export, 1 pinned Claude Code, 1 clean stop)."""
    text = "\n".join(f"# /etc/systemd/system/{u}\n" + (DEPLOY / u).read_text(encoding="utf-8") for u in FA.JOBS_KO)
    for pat in (r"OnFailure|DISABLE_AUTOUPDATER|SuccessExitStatus",
                r"^(OnFailure=|Environment=DISABLE_AUTOUPDATER|SuccessExitStatus=)"):
        got = [ln for ln in text.splitlines() if re.search(pat, ln)]
        assert len(got) == 8 and sum("OnFailure" in ln for ln in got) == 6 == len(FA.JOBS_KO), (pat, got)


def test_agents_unit_keeps_claude_code_from_updating_itself():
    from paperbot.agents.runner import ENV_ALLOW
    assert "Environment=DISABLE_AUTOUPDATER=1" in _unit("paperbot-agents.service")["[Service]"]
    assert "DISABLE_AUTOUPDATER" in ENV_ALLOW                # the runner passes it on to the Claude Code child


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="needs the sqlite3 program")
def test_backup_packs_the_ghcoin_files_and_they_come_back(tmp_path):
    lib, out = tmp_path / "lib", tmp_path / "backups"
    (lib / "ghcoin").mkdir(parents=True)
    calls = b'{"ev":"open","sym":"BTCUSDT"}\n{"ev":"close","r":-1.07}\n'
    state = '{"open": {}, "last": {"BTCUSDT": 1}}'.encode()
    (lib / "ghcoin" / "calls.jsonl").write_bytes(calls)
    (lib / "ghcoin" / "state.json").write_bytes(state)                 # no patterns.jsonl yet: left out
    c = sqlite3.connect(lib / "inbox.db")
    c.execute("CREATE TABLE t (x)")
    c.commit()
    c.close()

    def backup():
        return subprocess.run(["sh", str(DEPLOY / "paperbot-backup.sh")], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "PAPERBOT_LIB": str(lib), "PAPERBOT_BACKUPS": str(out)})
    r = backup()
    assert r.returncode == 0, r.stderr
    day, = os.listdir(out)
    folder = out / day
    assert sorted(os.listdir(folder)) == ["ghcoin.db", "inbox.db"]
    files, problems = off.check_folder(folder, lib)                    # the off-site copy sends it like a database
    assert set(files) == {"ghcoin.db", "inbox.db"} and problems == []
    # the restore line of docs/ghcoin-recorder.md, pasted with the path "다음 순서" printed for ghcoin.db. Two date
    # folders (docs/offsite-backup.md 9-4: a damaged day, then the day before into the same --out): the one printed
    restored = tmp_path / "restore-out"
    good, bad = restored / "20261007", restored / "20261008"
    good.mkdir(parents=True)
    bad.mkdir()
    shutil.copy(folder / "ghcoin.db", good / "ghcoin.db")
    c = sqlite3.connect(bad / "ghcoin.db")
    c.execute("CREATE TABLE files (name TEXT PRIMARY KEY, data BLOB)")
    c.execute("INSERT INTO files VALUES ('calls.jsonl', x'00')")
    c.commit()
    c.close()
    back = tmp_path / "restored"
    back.mkdir()
    doc = (REPO / "docs" / "ghcoin-recorder.md").read_text(encoding="utf-8")
    line = re.search(r"^\s*(sudo sqlite3 .* FROM files\")$", doc, re.M).group(1)
    assert "/root/restore-out/날짜/ghcoin.db" in line and "*" not in line and '"다음 순서"의 `ghcoin.db` 줄' in doc
    printed = re.search(r"install .* (\S+/ghcoin\.db) /var/lib/paperbot/ghcoin\.db",
                        off.next_steps(good, ["ghcoin.db", "inbox.db"])).group(1)
    cmd = (line.removeprefix("sudo ").replace("/root/restore-out/날짜/ghcoin.db", printed)
           .replace("/var/lib/paperbot/ghcoin/", f"{back}/"))
    r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert sorted(os.listdir(back)) == ["calls.jsonl", "state.json"]
    assert (back / "calls.jsonl").read_bytes() == calls and (back / "state.json").read_bytes() == state
    # no recorder files: no ghcoin.db (and nothing else changes)
    shutil.rmtree(lib / "ghcoin")
    shutil.rmtree(out)
    assert backup().returncode == 0
    assert os.listdir(out / day) == ["inbox.db"]


def test_weekly_checkpoint_rehearsal_unit_is_sandboxed_and_never_the_real_verdict():
    """deploy/paperbot-rehearsal.service/.timer: the weekly checkpoint_preview run as paperbot with live.env's
    read-only key, a fresh file in /var/lib/paperbot/rehearsal, never the real checkpoint.db (hidden), no Telegram
    of its own, the failure warning through paperbot-failed@; installed by install.sh but never enabled there."""
    u = _unit("paperbot-rehearsal.service")
    svc, unit = u["[Service]"], u["[Unit]"]
    assert "OnFailure=paperbot-failed@%n.service" in unit
    assert "User=paperbot" in svc and "Group=paperbot" in svc and "Type=oneshot" in svc
    assert "EnvironmentFile=/etc/paperbot/live.env" in svc
    unset = next(ln for ln in svc if ln.startswith("UnsetEnvironment=")).split("=", 1)[1].split()
    assert {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL", "TELEGRAM_CHAT_WARN", "TELEGRAM_CHAT_INFO",
            "DEADMAN_URL"} <= set(unset)
    assert "BINANCE_API_KEY" not in unset and "BINANCE_API_SECRET" not in unset   # the signed bracket call
    ex = next(ln for ln in svc if ln.startswith("ExecStart="))
    assert "-m paperbot.checkpoint_preview " in ex and "--rehearsal-dir /var/lib/paperbot/rehearsal" in ex
    assert "--keep 4" in ex and "--db /var/lib/paperbot/paper3.db" in ex
    assert "--cache /var/lib/paperbot/rehearsal/" in ex                       # its own cache, not the real one
    assert "checkpoint.db" not in ex and "--out" not in ex and "checkpoint_bars" not in ex
    paths = {k: next(ln for ln in svc if ln.startswith(k + "=")).split("=", 1)[1].split()
             for k in ("ReadWritePaths", "ReadOnlyPaths", "InaccessiblePaths")}
    assert paths["ReadWritePaths"] == ["/var/lib/paperbot"]                  # for paper3.db's -shm only
    assert "-/var/lib/paperbot/paper3.db" in paths["ReadOnlyPaths"]
    assert "-/var/lib/paperbot/daily3.db" in paths["ReadOnlyPaths"]
    # the real verdict file appears only to hide it
    assert "-/var/lib/paperbot/checkpoint.db" in paths["InaccessiblePaths"]
    assert "-/var/lib/paperbot/checkpoint_bars" in paths["InaccessiblePaths"]
    assert {"-/etc/paperbot/agents.env", "-/etc/paperbot/executor.env", "-/var/lib/paperbot/exec"} \
        <= set(paths["InaccessiblePaths"])
    for k in ("ReadWritePaths", "ReadOnlyPaths"):
        assert not any("checkpoint.db" in p for p in paths[k]), k
    for k in ("NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict", "Nice=19", "IOSchedulingClass=idle"):
        assert k in svc, k
    assert any(ln.startswith("MemoryMax=") for ln in svc) and any(ln.startswith("TimeoutStartSec=") for ln in svc)
    t = _unit("paperbot-rehearsal.timer")
    assert "OnCalendar=Wed *-*-* 03:30:00 UTC" in t["[Timer]"] and "Persistent=true" in t["[Timer]"]
    assert "WantedBy=timers.target" in t["[Install]"]
    inst = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    loop = re.search(r"for u in ([^;]*); do\s+install -m 644", inst).group(1).replace("\\", " ").split()
    assert {"paperbot-rehearsal.service", "paperbot-rehearsal.timer"} <= set(loop)
    assert "install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/rehearsal" in inst
    jobs = re.search(r'JOBS="([^"]*)"', inst).group(1).replace("\\", " ").split()
    assert "paperbot-rehearsal.service" in jobs                              # a deploy waits for a running one
    # like every timer, installed but never enabled or started by the script (the owners turn it on once)
    assert not re.search(r"systemctl (enable|start)[^\n]*paperbot-rehearsal", inst.replace(
        "echo \"weekly checkpoint rehearsal installed but off; to turn it on once: sudo systemctl enable --now "
        "paperbot-rehearsal.timer\"", ""))
    assert "paperbot-rehearsal.service" in FA.JOBS_KO
