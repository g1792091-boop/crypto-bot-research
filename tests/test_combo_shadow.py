"""The shadow paper bots (그림자 페이퍼 봇, docs/live1019-start-ko.md 11): three paper-only copies of the combined bot
(paperbot/combo.py, unchanged) with other configs, next to the live paper bot (deploy/combo.live-ac.json, which two
real-money executors follow) on the same live market.

- the three configs: they load and pass the config check ("준비됨"), keep every rule of the live paper bot except their
  members, their own database, their name and "telegram": false;
- B 안정형 = the members of combo.live-plateau37.json; 끄는 구간 없음 = live-ac's 95 members without "off" (a missing "off"
  is what combo.py reads as "no switch-off buckets"); 32개 = the 32-strategy / 101-setting live-ac of commit 2179a84;
- each database is its own and never the live paper bot's or an executor's paper_db;
- the template unit: the right ExecStart, the live unit's user and hardening, below it in CPU / disk / memory, no
  Telegram, and a start guard that refuses a config writing anywhere but shadow-<name>.db or with Telegram on;
- install.sh installs the template and never enables, starts or restarts a shadow (it only prints the command)."""

import dataclasses
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from paperbot import combo as C
from paperbot import rmember as RM

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"
LIVE = DEPLOY / "combo.live-ac.json"
UNIT = "paperbot-combo-shadow@.service"
LIVE_UNIT = "paperbot-combo.service"
OLD_COMMIT = "2179a84"                  # the live-ac config before it went down to 27 strategies / 95 settings
SHADOWS = {"b": ("그림자 B 안정형", 37), "nocut": ("그림자 끄는 구간 없음", 95), "ac32": ("그림자 32개", 101),
           "chase": ("그림자 어중간한 추격 막기", 95), "trend4h": ("그림자 4시간 역추세만", 95)}
# owners 10/19 "저점 추격 숏 고점 추격 롱 방지": the live members with extra switch-off buckets (rmember OFF_DIMS)
EXTRA_CUTS = {"chase": [["posside", 7], ["posside", 2]],      # long in the top 20% / short in the bottom 20% of the 7-day range
              "trend4h": [["ctr4", 1]]}                       # the coin's 4h trend agrees with the side
OWN = ("members", "db", "name", "telegram")   # what a shadow sets itself; every other key is the live bot's


def _load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _path(tag: str) -> Path:
    return DEPLOY / f"combo.shadow-{tag}.json"


def _unit(name: str) -> dict:
    """{section: {key: [values]}} of a unit file, comments left out."""
    out: dict = {}
    sec = ""
    for ln in (DEPLOY / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        k, v = ln.split("=", 1)
        out.setdefault(sec, {}).setdefault(k, []).append(v)
    return out


def _without(d: dict, keys) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


# ====================================================================== the configs
@pytest.mark.parametrize("tag", sorted(SHADOWS))
def test_each_shadow_config_loads_and_passes_the_config_check(tag, capsys):
    name, n = SHADOWS[tag]
    cfg = C.ComboConfig.from_file(str(_path(tag)))
    assert cfg.problems() == []
    members = C.resolve_members(cfg.members, cfg.picks_file)
    assert len(members) == n and C.research_problems(cfg, members) == []
    assert C.main(["check-config", "--config", str(_path(tag))]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().splitlines()[-1] == "준비됨" and "[문제]" not in out
    assert cfg.name == name and cfg.telegram is False


def test_the_shadows_keep_every_rule_of_the_live_paper_bot():
    live = _load(LIVE)
    for tag in SHADOWS:
        sh = _load(_path(tag))
        assert list(sh) == list(live), tag                                  # the same keys, in the same order
        assert _without(sh, OWN) == _without(live, OWN), tag
        assert sh["telegram"] is False and sh["name"] == SHADOWS[tag][0], tag


def test_each_shadow_writes_its_own_database_never_the_live_one_or_an_executors():
    live = _load(LIVE)
    dbs = {tag: _load(_path(tag))["db"] for tag in SHADOWS}
    assert dbs == {tag: f"/var/lib/paperbot/combo/shadow-{tag}.db" for tag in SHADOWS}
    assert len(set(dbs.values())) == len(SHADOWS)
    assert live["db"] == "/var/lib/paperbot/combo/live-ac.db" and live["db"] not in dbs.values()
    assert live["paper_db"] not in dbs.values()
    # no other paper bot config in the repository writes there
    others = {_load(p)["db"] for p in DEPLOY.glob("combo.*.json")
              if not p.name.startswith("combo.shadow-")
              and not p.name.endswith((".expected.json", ".likely.json"))}   # backtest references, not configs
    assert others and not others & set(dbs.values())
    # and no executor follows a shadow: every "paper_db" an owner guide or example gives an executor is another file
    named = set()
    for p in list((REPO / "docs").glob("*.md")) + list(DEPLOY.glob("*.json")) + list(DEPLOY.glob("*.example")):
        named |= set(re.findall(r'"paper_db"\s*:\s*"([^"]+)"', p.read_text(encoding="utf-8", errors="replace")))
    assert "/var/lib/paperbot/combo/live-ac.db" in named
    assert not named & set(dbs.values())


def test_b_is_the_plateau_members():
    assert _load(_path("b"))["members"] == _load(DEPLOY / "combo.live-plateau37.json")["members"]


def test_nocut_is_the_live_members_without_their_switch_off_buckets():
    live = _load(LIVE)["members"]
    nocut = _load(_path("nocut"))["members"]
    assert sum(1 for m in live if m.get("off")) >= 90                       # the live bot does use them
    assert nocut == [_without(m, ("off",)) for m in live]
    assert not any("off" in m for m in nocut)
    # combo.py reads a missing "off" as no buckets, exactly like an empty one
    for m in nocut:
        assert RM.parse_spec(m, "x") == RM.parse_spec({**m, "off": []}, "x")
    a = C.resolve_members(live)
    b = C.resolve_members(nocut)
    assert len(a) == len(b) == 95
    for x, y in zip(a, b):
        assert (x.kind, x.name, x.tf, x.numbers, x.when) == (y.kind, y.name, y.tf, y.numbers, y.when)
        assert y.research.off == frozenset()
        assert dataclasses.replace(x.research, off=frozenset()) == y.research


@pytest.mark.parametrize("tag", sorted(EXTRA_CUTS))
def test_the_anti_chase_shadows_are_the_live_members_plus_their_cuts(tag):
    """A change of the live config must be carried into these two (or they compare against a bot that no longer runs)."""
    live = _load(LIVE)["members"]
    sh = _load(_path(tag))["members"]
    assert len(sh) == len(live) == 95
    for m, s in zip(live, sh):
        assert _without(s, ("off",)) == _without(m, ("off",))
        assert s["off"] == list(m.get("off") or []) + [c for c in EXTRA_CUTS[tag] if c not in (m.get("off") or [])]
    for x in C.resolve_members(sh):
        hits = RM.off_hits(x.research, {**{d: -1 for d in RM.OFF_DIMS}, "posside": 7, "ctr4": 1})
        assert hits, x.name                                                 # every setting refuses that bucket


def test_ac32_is_the_32_strategy_live_config_of_the_earlier_commit():
    if not shutil.which("git"):
        pytest.skip("needs git")
    r = subprocess.run(["git", "-C", str(REPO), "show", f"{OLD_COMMIT}:deploy/combo.live-ac.json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"commit {OLD_COMMIT} not in this checkout")
    old = json.loads(r.stdout)
    sh = _load(_path("ac32"))
    later = ("us_open_pause_min",)                  # rules added to every bot after that commit (owners 10/19 night)
    assert _without(sh, ("db", "name", "telegram") + later) == _without(old, ("db", "name", "telegram"))
    assert [k for k in sh if k not in later] == list(old)
    assert len(old["members"]) == 101 and len({m["strategy"] for m in old["members"]}) == 32
    assert old["db"] == _load(LIVE)["db"] != sh["db"]


# ====================================================================== the unit
def test_the_template_unit_runs_the_shadow_config_below_the_live_paper_bot():
    u = _unit(UNIT)
    svc, live = u["[Service]"], _unit(LIVE_UNIT)["[Service]"]
    assert svc["ExecStart"] == ["/opt/paperbot/venv/bin/python -m paperbot.combo run "
                                "--config /opt/crypto-bot-research/deploy/combo.shadow-%i.json"]
    # the live paper bot's user, folder, environment, restart policy and hardening
    for k in ("Type", "User", "Group", "WorkingDirectory", "Restart", "RestartSec", "NotifyAccess",
              "WatchdogSec", "TimeoutStopSec", "NoNewPrivileges", "PrivateTmp", "ProtectSystem", "ProtectHome",
              "RestrictAddressFamilies", "ReadWritePaths", "InaccessiblePaths"):
        assert svc[k] == live[k], k
    # live.env as the live paper bot; never the owners' private chats of the live messages (the shadows send nothing)
    assert svc["EnvironmentFile"] == ["/etc/paperbot/live.env"]
    assert live["EnvironmentFile"] == ["/etc/paperbot/live.env", "-/etc/paperbot/live-telegram.env"]
    assert "-/etc/paperbot/executor.env" in svc["InaccessiblePaths"][0].split()
    assert u["[Unit]"]["StartLimitIntervalSec"] == ["0"]
    assert "paperbot-combo.service" in u["[Unit]"]["After"][0].split()
    # never in the way of the live paper bot (Nice 5, CPU weight 100) and the executors
    assert svc["Nice"] == ["10"] and int(svc["Nice"][0]) > int(live["Nice"][0])
    assert svc["CPUWeight"] == ["20"] and svc["IOWeight"] == ["20"]
    assert svc["MemoryMax"] == ["768M"]
    assert int(svc["OOMScoreAdjust"][0]) > 0
    # no Telegram even if live.env names a bot
    unset = svc["UnsetEnvironment"][0].split()
    assert {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL", "TELEGRAM_CHAT_WARN", "TELEGRAM_CHAT_INFO"} <= set(unset)


def _guard() -> list:
    """The unit's first ExecStartPre as an argv for this Python."""
    argv = shlex.split(_unit(UNIT)["[Service]"]["ExecStartPre"][0])
    assert argv[0] == "/opt/paperbot/venv/bin/python" and argv[1] == "-c"
    assert argv[3:] == ["/opt/crypto-bot-research/deploy/combo.shadow-%i.json", "%i"]
    return [sys.executable] + argv[1:3]


def _run_guard(config: Path, instance: str) -> subprocess.CompletedProcess:
    return subprocess.run(_guard() + [str(config), instance], capture_output=True, text=True)


def test_the_start_guard_refuses_a_config_that_could_touch_the_live_bot(tmp_path):
    for tag in SHADOWS:
        r = _run_guard(_path(tag), tag)
        assert r.returncode == 0, r.stderr
    sh = _load(_path("nocut"))
    for bad in ({**sh, "db": "/var/lib/paperbot/combo/live-ac.db"}, {**sh, "telegram": True},
                _without(sh, ("telegram",))):
        p = tmp_path / "combo.shadow-nocut.json"
        p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        r = _run_guard(p, "nocut")
        assert r.returncode != 0 and "shadow config refused" in r.stderr
    assert _run_guard(_path("b"), "nocut").returncode != 0                 # another shadow's database
    # the start lock: one shadow at a time, in the folder the unit may write
    pre = _unit(UNIT)["[Service]"]["ExecStartPre"]
    assert len(pre) == 2 and pre[1].startswith("/usr/bin/flock /var/lib/paperbot/combo/")


# ====================================================================== install.sh
def _shadow_block(sh: str) -> str:
    lines = sh.splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith("# the shadow paper bots"))
    j = next(n for n in range(i, len(lines)) if lines[n] == "fi")
    return "\n".join(lines[i:j + 1]) + "\n"


def test_install_installs_the_template_and_never_enables_or_starts_a_shadow():
    path = DEPLOY / "install.sh"
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    sh = path.read_text(encoding="utf-8")
    assert f'install -m 644 "$APP/deploy/{UNIT}" "/etc/systemd/system/{UNIT}"' in sh
    assert sh.index(UNIT) < sh.index("systemctl daemon-reload")
    units_line = next(ln for ln in sh.splitlines() if ln.startswith("UNITS="))
    assert "shadow" not in units_line                                       # not stopped / restarted for the swap
    for ln in sh.splitlines():
        s = ln.strip()
        if "combo-shadow" in s and not s.startswith(("#", "echo")):
            assert not re.search(r"systemctl\s+(enable|start|restart|stop)", s), s


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_install_prints_the_restart_command_for_running_shadows_only(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "calls.log"
    (fake / "systemctl").write_text('#!/bin/sh\necho "systemctl $*" >> "$CALLS"\n'
                                    '[ "$1" = list-units ] && printf "%b" "$FAKE_ACTIVE"\nexit 0\n')
    (fake / "install").write_text('#!/bin/sh\necho "install $*" >> "$CALLS"\n')
    for f in fake.iterdir():
        f.chmod(0o755)
    block = _shadow_block((DEPLOY / "install.sh").read_text(encoding="utf-8"))
    script = "set -euo pipefail\nAPP=/opt/crypto-bot-research\n" + block

    def run(active: str) -> str:
        env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "CALLS": str(log), "FAKE_ACTIVE": active}
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        return r.stdout

    assert run("") == ""
    out = run("paperbot-combo-shadow@b.service loaded active running x\n"
              "paperbot-combo-shadow@nocut.service loaded active running x\n")
    assert out.splitlines()[-1] == "  sudo systemctl restart paperbot-combo-shadow@b.service " \
                                   "paperbot-combo-shadow@nocut.service"
    calls = log.read_text().splitlines()
    assert f"install -m 644 /opt/crypto-bot-research/deploy/{UNIT} /etc/systemd/system/{UNIT}" in calls
    assert all(c.startswith("install ") or c.startswith("systemctl list-units ") for c in calls), calls
