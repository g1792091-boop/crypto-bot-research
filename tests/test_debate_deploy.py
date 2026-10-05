"""The debate room's deployment and key isolation: the unit file, install.sh, the env template, the permission model
(the key file is readable by user paperbot-debate only), runner.ENV_ALLOW staying free of the paid key, and launchcheck's
lines about it."""
import os
import re
import subprocess
from pathlib import Path

from paperbot import launchcheck as L
from paperbot.agents import runner

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"
UNIT = "paperbot-debate.service"


def unit(name=UNIT) -> dict:
    out: dict = {}
    sec = ""
    for ln in (DEPLOY / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        k, _, v = ln.partition("=")
        out.setdefault(sec, {}).setdefault(k, []).append(v)
    return out


def can_read(mode, owner, group, user, groups):
    """POSIX read permission of a file for a user (not root) with the given groups."""
    if user == owner:
        return bool(mode & 0o400)
    if group in groups:
        return bool(mode & 0o040)
    return bool(mode & 0o004)


# ---------------------------------------------------------------- the unit
def test_unit_is_sandboxed_like_the_agents_unit_and_can_write_only_its_folder():
    u = unit()
    svc = u["[Service]"]
    assert svc["User"] == ["paperbot-debate"] and svc["Group"] == ["paperbot"] and svc["UMask"] == ["0027"]
    for k in ("NoNewPrivileges", "PrivateTmp", "ProtectHome", "PrivateDevices"):
        assert svc[k] == ["yes"], k
    assert svc["ProtectSystem"] == ["strict"] and svc["KillMode"] == ["mixed"]
    assert svc["ReadWritePaths"] == ["/var/lib/paperbot/debate"]
    assert svc["ReadOnlyPaths"] == ["/var/lib/paperbot"]
    hidden = set(svc["InaccessiblePaths"][0].split())
    assert {"-/etc/paperbot", "-/var/lib/paperbot/exec", "-/var/backups/paperbot", "-/var/lib/paperbot/.claude",
            "-/var/lib/paperbot/.local"} <= hidden
    assert svc["Restart"] == ["on-failure"] and svc["RestartPreventExitStatus"] == ["2"]       # no crash loop
    assert "-m paperbot.agents.debate run" in svc["ExecStart"][0]
    assert "OnFailure" not in u.get("[Unit]", {})                       # (the failure hook is for scheduled jobs only)
    assert any(x.startswith("StartLimit") for x in u["[Unit]"])
    # unlike the agents unit: no Claude Code login, no subscription token, no other env file
    assert svc["EnvironmentFile"] == ["/etc/paperbot/debate.env"]
    text = (DEPLOY / UNIT).read_text(encoding="utf-8")
    for other in ("agents.env", "live.env", "dash.env", "executor.env"):
        assert not re.search(rf"EnvironmentFile=.*{other}", text), other
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in text.replace("subscription token", "")


def test_no_other_unit_loads_the_key_file_and_the_ones_that_name_secrets_hide_it():
    for f in sorted(DEPLOY.glob("*.service")):
        if f.name == UNIT:
            continue
        assert "EnvironmentFile=/etc/paperbot/debate.env" not in f.read_text(encoding="utf-8"), f.name
    for name in ("paperbot-agents.service", "paperbot-dash.service"):
        hidden = unit(name)["[Service]"]["InaccessiblePaths"][0].split()
        assert "-/etc/paperbot/debate.env" in hidden, name
    live = unit("paperbot-live3.service")["[Service]"]
    assert live["EnvironmentFile"] == ["/etc/paperbot/live.env"]


# ---------------------------------------------------------------- install.sh
def test_install_script_creates_the_user_and_folder_installs_but_never_starts_the_unit():
    path = DEPLOY / "install.sh"
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    sh = path.read_text(encoding="utf-8")
    assert "groupadd --system paperbot-debate" in sh and "useradd --system --gid paperbot-debate --groups paperbot" in sh
    assert "install -d -o paperbot-debate -g paperbot -m 2750 /var/lib/paperbot/debate" in sh
    assert "install -o root -g paperbot-debate -m 640" in sh and "chown root:paperbot-debate /etc/paperbot/debate.env" in sh
    loop = re.search(r"for u in ([^;]*); do\s+install -m 644", sh).group(1).replace("\\", " ").split()
    assert UNIT in loop
    # not enabled or started, and not among the services stopped and restarted for the code swap
    units_line = next(l for l in sh.splitlines() if l.startswith("UNITS="))
    assert "debate" not in units_line
    body = sh.split("cat <<'NEXT'")[0]
    acts = [l for l in body.splitlines() if not l.lstrip().startswith(("echo", "#"))]     # what it does, not what it prints
    assert not any(re.search(r"systemctl\s+(enable|start|restart|stop)\b", l) and "debate" in l for l in acts)
    assert not any("is-active" not in l and "is-enabled" not in l and "debate" in l and "systemctl" in l for l in acts)
    assert "docs/debate-room.md" in sh
    # only the two Telegram lines are copied from agents.env (grep), never printed; an existing file is never replaced
    block = sh[sh.index("The debate room's paid API key"):sh.index("# The executor's order keys")]
    assert "TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_CRITICAL" in block and "ANTHROPIC" not in block
    assert 'if [ ! -f /etc/paperbot/debate.env ]' in block
    assert "echo" not in block.replace("# ", "#") or all("$line" not in l for l in block.splitlines() if "echo" in l)
    assert "cat /etc/paperbot" not in sh and "cat \"$f\"" not in sh


def test_the_telegram_copy_snippet_copies_two_lines_and_prints_nothing(tmp_path):
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    block = sh[sh.index("if [ ! -f /etc/paperbot/debate.env ]"):sh.index("[ -f /etc/paperbot/debate.env ] && chmod")]
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "agents.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=secret-oauth\nTELEGRAM_BOT_TOKEN=12345:TOKENVALUE\n"
                                    "TELEGRAM_CHAT_CRITICAL=-100123\nTELEGRAM_CHAT_WARN=\nANTHROPIC_API_KEY=nope\n")
    snippet = (block.replace("/etc/paperbot", str(etc)).replace('"$APP/deploy/debate.env.example"',
               f'"{DEPLOY / "debate.env.example"}"').replace("install -o root -g paperbot-debate -m 640", "install -m 640"))
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + snippet], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "" and "TOKENVALUE" not in r.stderr
    text = (etc / "debate.env").read_text()
    assert "TELEGRAM_BOT_TOKEN=12345:TOKENVALUE" in text and "TELEGRAM_CHAT_CRITICAL=-100123" in text
    assert "secret-oauth" not in text and "nope" not in text and re.search(r"^ANTHROPIC_API_KEY=$", text, re.M)
    assert text.count("TELEGRAM_BOT_TOKEN=") == 1
    # an existing file is left alone
    (etc / "debate.env").write_text("ANTHROPIC_API_KEY=mine\n")
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + snippet], capture_output=True, text=True)
    assert r.returncode == 0 and (etc / "debate.env").read_text() == "ANTHROPIC_API_KEY=mine\n"


# ---------------------------------------------------------------- the env template
def test_env_template_has_an_empty_key_and_the_documented_defaults():
    text = (DEPLOY / "debate.env.example").read_text(encoding="utf-8")
    vals = {}
    for ln in text.splitlines():
        if ln and not ln.startswith("#"):
            k, eq, v = ln.partition("=")
            assert eq and re.fullmatch(r"[A-Z_]+", k), ln
            vals[k] = v
    assert vals["ANTHROPIC_API_KEY"] == "" and vals["TELEGRAM_BOT_TOKEN"] == "" and vals["TELEGRAM_CHAT_CRITICAL"] == ""
    assert vals["DEBATE_MODEL"] == "claude-haiku-4-5-20251001" and vals["DEBATE_EVERY_MIN"] == "20"
    assert vals["DEBATE_MONTHLY_USD_CAP"] == "40"
    for name in ("DEBATE_PRICE_IN", "DEBATE_PRICE_OUT", "DEBATE_HOURLY_USD_CAP", "DEBATE_TURNS", "DEBATE_MAX_TOKENS"):
        assert f"#{name}=" in text
    assert "sk-ant" not in text and "sudoedit" in text
    from paperbot.agents import debate
    cfg = debate.config_from_env(vals)                                  # the template parses with the service's own parser
    assert cfg.api_key == "" and cfg.every_min == 20 and cfg.monthly_cap == 40.0


def test_key_file_permission_model_only_the_debate_user_can_read_it():
    owner, group, mode = L.ENV_SPECS["debate"]
    assert (owner, group, mode) == ("root", "paperbot-debate", 0o640)
    assert can_read(mode, owner, group, "paperbot-debate", {"paperbot-debate", "paperbot"})
    assert not can_read(mode, owner, group, "paperbot", {"paperbot"})           # agents, dashboard, live runner
    assert not can_read(mode, owner, group, "paperbot-exec", {"paperbot"})
    assert L.ENV_SPECS["agents"][1] == "paperbot" and L.ENV_SPECS["debate"][1] != L.USER


# ---------------------------------------------------------------- the key cannot reach the existing rooms
def test_the_agents_never_get_the_paid_key():
    assert "ANTHROPIC_API_KEY" not in runner.ENV_ALLOW and not any(k.startswith("DEBATE_") for k in runner.ENV_ALLOW)
    assert "ANTHROPIC_API_KEY" in runner.ENV_BILLING
    parent = {"ANTHROPIC_API_KEY": "sk-ant-api03-x" * 3, "DEBATE_MODEL": "m", "PATH": "/bin", "HOME": "/h",
              "CLAUDE_CODE_OAUTH_TOKEN": "t"}
    assert "ANTHROPIC_API_KEY" not in runner.child_env(parent) and "ANTHROPIC_API_KEY" not in runner.call_env(parent)
    assert "DEBATE_MODEL" not in runner.child_env(parent)
    for env in ("agents.env.example", "live.env.example", "dash.env.example", "executor.env.example"):
        assert not re.search(r"^\s*ANTHROPIC_API_KEY\s*=", (DEPLOY / env).read_text(encoding="utf-8"), re.M), env
    assert not re.search(r"^\s*[A-Z_]*DEBATE", (DEPLOY / "agents.env.example").read_text(encoding="utf-8"), re.M)
    # no agent-room module reads or imports the debate room, and the debate room imports no room runner
    here = REPO / "paperbot" / "agents"
    for f in here.glob("*.py"):
        if f.name.startswith("debate"):
            continue
        assert "paperbot.agents.debate" not in f.read_text(encoding="utf-8") and "from . import debate" not in f.read_text(encoding="utf-8"), f.name
    for f in here.glob("debate*.py"):
        src = f.read_text(encoding="utf-8")
        assert "from .runner" not in src and "import runner" not in src and "agents.runner" not in src, f.name


def test_launchcheck_refuses_the_paid_key_anywhere_but_debate_env():
    assert L.DEBATE_KEY in L.FORBIDDEN["live"] and L.DEBATE_KEY in L.FORBIDDEN["dash"]
    assert L.DEBATE_KEY in L.FORBIDDEN["agents"]                         # (ENV_BILLING: the subscription would turn into API billing)
    assert set(L.ENV_BILLING) == set(runner.ENV_BILLING)


# ---------------------------------------------------------------- launchcheck's lines
from test_launchcheck import Server, NOW as LC_NOW                         # noqa: E402


def lines(srv, **over):
    ctx = srv.ctx(**over)
    envs = L.read_envs(ctx)
    states = L.unit_states(ctx)
    return L.check_debate(ctx, states, envs), envs, ctx


def kinds(ls):
    return [s for s, _ in ls]


def set_unit(srv, enabled):
    srv.units[L.DEBATE_UNIT] = {"LoadState": "loaded", "UnitFileState": "enabled" if enabled else "disabled",
                                "ActiveState": "active" if enabled else "inactive"}


GOOD_KEY = "sk-ant-api03-" + "A" * 60


def test_launchcheck_not_installed_or_off_is_a_note_never_a_fix(tmp_path):
    srv = Server(tmp_path)
    ls, *_ = lines(srv)
    assert kinds(ls) == [L.NOTE] and "설치되어 있지 않습니다" in ls[0][1]
    set_unit(srv, False)
    ls, *_ = lines(srv)
    assert kinds(ls) == [L.NOTE] and "꺼져 있습니다" in ls[0][1]
    srv.write_env("debate", f"ANTHROPIC_API_KEY={GOOD_KEY}\n")                    # a key in the file while off: still no fix
    srv.owners[os.path.join(srv.etc, "debate.env")] = (0o640, "root", "paperbot-debate")
    ls, *_ = lines(srv)
    assert L.FIX not in kinds(ls)
    srv.write_env("debate", "ANTHROPIC_API_KEY=short\n")
    ls, *_ = lines(srv)
    assert kinds(ls) == [L.NOTE, L.NOTE] and "모양이 API 키" in ls[1][1]


def test_launchcheck_enabled_without_a_key_is_a_fix_and_with_a_key_shows_the_last_round(tmp_path):
    srv = Server(tmp_path)
    set_unit(srv, True)
    srv.write_env("debate", "ANTHROPIC_API_KEY=\n")
    srv.owners[os.path.join(srv.etc, "debate.env")] = (0o640, "root", "paperbot-debate")
    ls, *_ = lines(srv)
    assert L.FIX in kinds(ls) and any("ANTHROPIC_API_KEY가 비어 있습니다" in t for _, t in ls)
    srv.write_env("debate", f"ANTHROPIC_API_KEY={GOOD_KEY}\n")
    ls, *_ = lines(srv)
    assert L.FIX not in kinds(ls) and any("아직 토론 기록이 없습니다" in t for _, t in ls)
    # a running service: last round time and the month's spend against the cap
    from paperbot.agents import debate as D
    ddir = os.path.join(srv.lib, "debate")
    os.makedirs(ddir, exist_ok=True)
    db = D.DB(os.path.join(ddir, "debate.db"))
    db.conn.execute("INSERT INTO debate_rounds (ts, status, cost_usd) VALUES (?, 'ok', 0.01)", (LC_NOW - 5 * 60_000,))
    db.put("run", {"state": "running", "reason": "", "ts": LC_NOW, "model": D.DEFAULT_MODEL, "every_min": 20, "cap": 40.0})
    db.put("heartbeat", LC_NOW - 10_000)
    db.put(f"spend:month:{D.kst_month(LC_NOW)}", 12.5)
    db.close()
    srv.owners[ddir] = (0o2750, "paperbot-debate", "paperbot")
    ls, *_ = lines(srv)
    ok = [t for s, t in ls if s == L.OK]
    assert len(ok) == 1 and "마지막 토론" in ok[0] and "$12.50 / 한도 $40 (31.2%)" in ok[0] and "20분마다" in ok[0]
    assert GOOD_KEY not in "\n".join(t for _, t in ls)
    # a paused service (credit) is a note with its reason; no key in the service's own state is a fix
    d2 = D.DB(os.path.join(ddir, "debate.db"))
    d2.put("run", {"state": "paused", "reason": D.CAUSE_KO["credit"], "ts": LC_NOW, "model": "m", "every_min": 20, "cap": 40.0})
    d2.close()
    ls, *_ = lines(srv)
    assert any(s == L.NOTE and "API 잔액 부족" in t for s, t in ls)


def test_launchcheck_checks_the_key_file_permissions_and_scrubs_the_key(tmp_path):
    srv = Server(tmp_path)
    set_unit(srv, True)
    srv.write_env("debate", f"ANTHROPIC_API_KEY={GOOD_KEY}\n")
    path = os.path.join(srv.etc, "debate.env")
    srv.owners[path] = (0o640, "root", "paperbot-debate")
    ctx = srv.ctx()
    envs = L.read_envs(ctx)
    assert not [t for s, t in L.check_env_files(ctx, envs, False) if s == L.FIX and "debate.env" in t]
    for bad in ((0o640, "root", "paperbot"), (0o644, "root", "paperbot-debate"), (0o600, "root", "root"),
                (0o660, "root", "paperbot-debate")):
        srv.owners[path] = bad
        ctx = srv.ctx()
        fixes = [t for s, t in L.check_env_files(ctx, L.read_envs(ctx), False) if s == L.FIX and "debate.env" in t]
        assert fixes and "root:paperbot-debate 640" in fixes[0] and "chown root:paperbot-debate" in fixes[0], bad
    # run as a user who cannot read it (paperbot): no error, one note
    srv.owners[path] = (0o640, "root", "paperbot-debate")
    ctx = srv.ctx(euid=998, username="paperbot")
    envs = L.read_envs(ctx)
    assert envs["debate"].exists and envs["debate"].values == {} and envs["debate"].error is None
    ls = L.check_debate(ctx, L.unit_states(ctx), envs)
    assert any("root만 열어 볼 수 있습니다" in t for _, t in ls)
    # the key counts among the values report() scrubs
    ctx = srv.ctx()
    assert GOOD_KEY in L.secret_values(L.read_envs(ctx))
    # and the paid key in another env file is refused
    srv.write_env("dash", open(os.path.join(srv.etc, "dash.env")).read() + f"ANTHROPIC_API_KEY={GOOD_KEY}\n")
    ctx = srv.ctx()
    assert any("유료 API 키는 debate.env" in t for s, t in L.check_env_files(ctx, L.read_envs(ctx), False) if s == L.FIX)
