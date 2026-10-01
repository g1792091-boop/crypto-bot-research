"""The launch check (paperbot/launchcheck.py) against a faked server: env files and folders live under
tmp_path, every command, HTTP answer, file owner and the clock are fakes. Nothing touches the network or
the real system (the autouse fixture makes any real command or connection fail the test)."""

import base64
import json
import os
import re
import socket
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pytest

from paperbot import launchcheck as L
from paperbot.agents import labdata as LD
from paperbot.config import V3_SYMBOLS

NOW = int(datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
MIN, DAY = 60_000, 86_400_000
KEY = "a1B2" * 16
SECRET = "s9T8" * 16
TOKEN = "123456789:AAH" + "x" * 32
CHAT = "-1001234567890"
CHAT_INFO = "-1009876543210"
DEADMAN = "https://hc-ping.com/0f3c1d2e-aaaa-bbbb-cccc-1234567890ab"
PW_HASH = "pbkdf2$200000${}${}".format(base64.b64encode(b"s" * 16).decode(), base64.b64encode(b"k" * 32).decode())
DASH_SECRET = "f0" * 32
CLAUDE = "sk-ant-oat01-" + "z" * 40
TS_IP = "100.101.102.103"
COMMIT = "d86c085" + "0" * 33
SECRETS = (KEY, SECRET, TOKEN, DEADMAN, PW_HASH, DASH_SECRET, CLAUDE, "0f3c1d2e-aaaa-bbbb-cccc-1234567890ab")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = "/opt/paperbot/venv/bin/python"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("launchcheck tests must not use the network or run real commands")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def live_env(**over):
    v = {"BINANCE_API_KEY": KEY, "BINANCE_API_SECRET": SECRET, "TELEGRAM_BOT_TOKEN": TOKEN,
         "TELEGRAM_CHAT_CRITICAL": CHAT, "TELEGRAM_CHAT_WARN": "", "TELEGRAM_CHAT_INFO": CHAT_INFO,
         "DEADMAN_URL": DEADMAN, **over}
    return "# /etc/paperbot/live.env\n" + "".join(f"{k}={x}\n" for k, x in v.items())


def dash_env(**over):
    v = {"DASH_PASSWORD_HASH": f"'{PW_HASH}'", "DASH_SECRET": DASH_SECRET, "DASH_HOST": TS_IP, **over}
    return "".join(f"{k}={x}\n" for k, x in v.items())


def agents_env(token=CLAUDE, extra=""):
    """The shipped template (deploy/agents.env.example) filled in the way the owners do."""
    with open(os.path.join(REPO_ROOT, "deploy", "agents.env.example")) as fh:
        text = fh.read()
    text = text.replace("CLAUDE_CODE_OAUTH_TOKEN=\n", f"CLAUDE_CODE_OAUTH_TOKEN={token}\n")
    text = text.replace("TELEGRAM_BOT_TOKEN=\n", f"TELEGRAM_BOT_TOKEN={TOKEN}\n")
    text = text.replace("TELEGRAM_CHAT_CRITICAL=\n", f"TELEGRAM_CHAT_CRITICAL={CHAT}\n")
    return text + extra


def jbody(obj, status=200):
    return status, json.dumps(obj).encode(), {}


SPEC = {"status": "TRADING", "contractType": "PERPETUAL",
        "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"}]}
READ_ONLY = {"ipRestrict": True, "enableReading": True, "enableWithdrawals": False, "enableFutures": False,
             "enableSpotAndMarginTrading": False, "enableMargin": False, "enableInternalTransfer": False,
             "permitsUniversalTransfer": False, "enableVanillaOptions": False, "enablePortfolioMarginTrading": False}
CHRONY_OK = ("Reference ID    : A9FEA97B (169.254.169.123)\nSystem time     : 0.000012345 seconds fast of NTP time\n"
             "Leap status     : Normal\n")
UFW_OK = ("Status: active\n\nTo                         Action      From\n--                         ------      ----\n"
          "OpenSSH                    ALLOW       Anywhere\nAnywhere on tailscale0     ALLOW       Anywhere\n"
          "OpenSSH (v6)               ALLOW       Anywhere (v6)\n")
SS_OK = (f"LISTEN 0      2048   {TS_IP}:8080      0.0.0.0:*\nLISTEN 0      4096   0.0.0.0:22      0.0.0.0:*\n")


class Server:
    """A healthy paper v3 server, faked. Tests change one thing and look at the lines."""

    def __init__(self, tmp_path, stage="before", agents=True):
        self.tmp = tmp_path
        self.etc, self.app, self.lib, self.backups, self.repo = (
            str(tmp_path / n) for n in ("etc", "app", "lib", "backups", "repo"))
        for d in (self.etc, self.app, self.lib, self.backups, os.path.join(self.repo, ".git"),
                  os.path.join(self.lib, "exec"), os.path.join(self.app, "docs")):
            os.makedirs(d, exist_ok=True)
        self.owners: dict = {}
        self.calls: list = []
        self.http: list = []
        self.write_env("live", live_env())
        self.write_env("dash", dash_env())
        self.write_env("agents", agents_env() if agents else agents_env(token=""))
        self.write_env("executor", "TESTNET_API_KEY=\nLIVE_API_KEY=\n")
        self.owners[self.etc] = (0o750, "root", "paperbot")
        self.owners[os.path.join(self.etc, "executor.env")] = (0o600, "root", "root")
        with open(os.path.join(self.app, "VERSION.json"), "w") as fh:
            json.dump({"commit": COMMIT, "tag": None, "dirty": False, "source": "install.sh",
                       "installed_at": "2026-10-01T03:00:00Z"}, fh)
        for name in ("paper-v3-rules", "paper-v3-rules-addendum"):
            data = f"rules {name}\n".encode()
            with open(os.path.join(self.app, "docs", f"{name}.md"), "wb") as fh:
                fh.write(data)
            import hashlib
            with open(os.path.join(self.app, "docs", f"{name}.sha256"), "w") as fh:
                fh.write(f"{hashlib.sha256(data).hexdigest()}  docs/{name}.md\n")
        self.meminfo = str(tmp_path / "meminfo")
        with open(self.meminfo, "w") as fh:
            fh.write("MemTotal:        8131200 kB\nMemFree:  100 kB\n")
        os.makedirs(os.path.join(self.lib, ".local", "bin"))
        open(os.path.join(self.lib, ".local", "bin", "claude"), "w").close()
        self.ref = self.make_lab()
        self.units = self.unit_table(stage, agents)
        self.head = COMMIT
        self.tailscale = {"BackendState": "Running", "Self": {"TailscaleIPs": [TS_IP, "fd7a:115c:a1e0::1"]}}
        self.cmd_out = {("chronyc",): (0, CHRONY_OK, ""), ("ufw", "status"): (0, UFW_OK, ""),
                        ("ss",): (0, SS_OK, ""), (VENV, "-c", "import paperbot"): (0, "", "")}
        self.auth = {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}
        self.perm = dict(READ_ONLY)
        self.server_ms = NOW
        self.routes = {}
        if stage == "after":
            self.make_db(start=NOW - 2 * 3_600_000, heartbeat=NOW - 20_000)

    # ------------------------------------------------------------ files
    def write_env(self, name, text):
        path = os.path.join(self.etc, f"{name}.env")
        with open(path, "w") as fh:
            fh.write(text)
        self.owners.setdefault(path, (0o640, "root", "paperbot"))

    def make_lab(self):
        lab = os.path.join(self.lib, "lab")
        ref = {"main": {}, "pre2021": {}}
        for src, d, seed in (("main", lab, 1), ("pre2021", os.path.join(lab, "pre2021"), 2)):
            os.makedirs(d, exist_ok=True)
            arrs = {"ts": np.arange(10, dtype=np.int64), "c": np.linspace(1, 2, 10) * seed}
            np.savez_compressed(os.path.join(d, "sig_5m_BTCUSD.npz"), **arrs)
            ref[src]["5m_BTCUSD"] = {"digest": LD.content_digest(arrs), "bars": 10}
        return ref

    def make_db(self, start, heartbeat=None, brackets="Binance leverageBracket (live)", commit=COMMIT):
        conn = sqlite3.connect(os.path.join(self.lib, "paper3.db"))
        conn.executescript("CREATE TABLE accounts (account_id TEXT, kind TEXT, created_ts INTEGER);"
                           "CREATE TABLE runs (id INTEGER PRIMARY KEY, started_ts INTEGER, data TEXT);"
                           "CREATE TABLE state (k TEXT PRIMARY KEY, ts INTEGER, data TEXT);")
        if start is not None:
            conn.execute("INSERT INTO accounts VALUES ('S1_15m', 'strategy', ?)", (start,))
            conn.execute("INSERT INTO runs (started_ts, data) VALUES (?, '{}')", (start,))
            conn.execute("INSERT INTO state VALUES ('run', ?, ?)", (start, json.dumps(
                {"accounts": 195, "brackets": brackets, "taker_fee": 0.0005, "commit": commit, "restored": False})))
        if heartbeat is not None:
            conn.execute("INSERT INTO state VALUES ('heartbeat', ?, '{}')", (heartbeat,))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------ units
    @staticmethod
    def unit_table(stage, agents):
        t = {}
        for u in L.INSTALLED:
            t[u] = {"LoadState": "loaded", "UnitFileState": "disabled", "ActiveState": "inactive", "SubState": "dead",
                    "Result": "success", "NRestarts": "0", "ExecMainStatus": "0"}
        t["paperbot-live3.service"]["ExecStart"] = (
            "{ path=/opt/paperbot/venv/bin/python ; argv[]=/opt/paperbot/venv/bin/python -m paperbot.live3 run "
            "--db /var/lib/paperbot/paper3.db --procs 4 ; ignore_errors=no }")
        for u in L.LEGACY + (L.LABBUILD,):
            t[u] = {"LoadState": "not-found", "UnitFileState": "", "ActiveState": "inactive", "SubState": "dead"}
        for u in L.SYSTEM:
            t[u] = {"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "active", "SubState": "running"}
        if stage == "after":
            for u in L.SERVICES:
                t[u].update(UnitFileState="enabled", ActiveState="active", SubState="running")
            for u in L.TIMERS + (L.AGENT_TIMERS if agents else ()):
                t[u].update(UnitFileState="enabled", ActiveState="active", SubState="waiting",
                            NextElapseUSecRealtime="Fri 2026-10-02 00:20:00 UTC")
        return t

    # ------------------------------------------------------------ the fakes
    def run(self, cmd, env=None, timeout=30.0, cwd=None):
        cmd = list(cmd)
        self.calls.append((cmd, env, cwd))
        if cmd[:2] == ["systemctl", "show"]:
            blocks = []
            for u in cmd[3:]:
                props = {"Id": u, **self.units.get(u, {"LoadState": "not-found"})}
                blocks.append("\n".join(f"{k}={v}" for k, v in props.items()))
            return 0, "\n\n".join(blocks) + "\n", ""
        if cmd[:3] == ["tailscale", "status", "--json"]:
            return (127, "", "not found") if self.tailscale is None else (0, json.dumps(self.tailscale), "")
        if cmd[:2] == ["git", "-C"]:
            return 0, self.head + "\n", ""
        if cmd[:4] == [L.RUNUSER, "-u", "paperbot", "--"] or cmd[:1] == [os.path.join(self.lib, ".local/bin/claude")]:
            st = dict(self.auth)
            if not (env or {}).get("CLAUDE_CODE_OAUTH_TOKEN"):
                st = {"loggedIn": False}
            return 0, json.dumps(st), ""
        for prefix in sorted(self.cmd_out, key=len, reverse=True):
            if tuple(cmd[:len(prefix)]) == prefix:
                return self.cmd_out[prefix]
        return 127, "", f"{cmd[0]}: not found"

    def fetch(self, method, url, headers=None, data=None, timeout=10.0):
        self.http.append((method, url, dict(headers or {}), data))
        for part, answer in self.routes.items():
            if part in url:
                return answer(method, url, headers or {}, data) if callable(answer) else answer
        u = urllib.parse.urlsplit(url)
        signed = "signature=" in (u.query or "")
        if signed and (headers or {}).get("X-MBX-APIKEY") != KEY:
            return jbody({"code": -2015, "msg": "Invalid API-key, IP, or permissions for action, "
                                                "request ip: 203.0.113.7"}, 401)
        if u.hostname == "fapi.binance.com":
            if u.path == "/fapi/v1/time":
                return jbody({"serverTime": self.server_ms})
            if u.path == "/fapi/v1/exchangeInfo":
                return jbody({"symbols": [{"symbol": s, **SPEC} for s in V3_SYMBOLS + ("XRPUSDT",)]})
            if u.path == "/fapi/v1/klines":
                return jbody([[0, "1", "1", "1", "65000.0", "1", 59_999]])
            if u.path == "/fapi/v1/commissionRate":
                return jbody({"takerCommissionRate": "0.000500", "makerCommissionRate": "0.000200"})
            if u.path == "/fapi/v1/leverageBracket":
                return jbody([{"symbol": s, "brackets": [{"bracket": 1, "initialLeverage": 75, "notionalCap": 5000,
                                                          "maintMarginRatio": 0.005}]} for s in V3_SYMBOLS])
        if u.hostname == "api.binance.com" and u.path == "/sapi/v1/account/apiRestrictions":
            return jbody(self.perm)
        if u.hostname == "api.telegram.org":
            if u.path == f"/bot{TOKEN}/getMe":
                return jbody({"ok": True, "result": {"username": "paper_bot"}})
            if u.path == f"/bot{TOKEN}/sendMessage":
                return jbody({"ok": True, "result": {}})
            return jbody({"ok": False, "error_code": 401, "description": "Unauthorized"}, 401)
        if u.hostname == "hc-ping.com":
            return 200, b"OK", {}
        if url == f"http://{TS_IP}:8080/":
            return 200, b"<html>login</html>", {}
        raise OSError(f"unexpected URL in test: {u.hostname}{u.path}")

    def stat(self, path):
        if not os.path.exists(path):
            return None
        is_dir = os.path.isdir(path)
        mode, owner, group = self.owners.get(path, (0o750 if is_dir else 0o640, "paperbot", "paperbot"))
        return L.FileInfo(mode, owner, group, is_dir)

    def ctx(self, **over):
        kw = dict(run=self.run, fetch=self.fetch, stat=self.stat, now_ms=lambda: NOW, sleep=lambda s: None,
                  cpu_count=lambda: 4, disk_free=lambda p: 120e9, euid=0, username="root", etc=self.etc,
                  app=self.app, lib=self.lib, backups=self.backups, repo=self.repo, meminfo=self.meminfo,
                  venv_python=VENV)
        kw.update(over)
        return L.Ctx(**kw)

    def envs(self, ctx=None):
        return L.read_envs(ctx or self.ctx())

    def sent(self, method):
        return [h for h in self.http if h[1].endswith("/" + method)]


def st(lines):
    return [s for s, _ in lines]


def txt(lines):
    return "\n".join(t for _, t in lines)


def fixes(lines):
    return [t for s, t in lines if s == L.FIX]


@pytest.fixture
def lab_ref(monkeypatch):
    holder = {}
    monkeypatch.setattr(LD, "reference", lambda path=LD.REFERENCE: holder["ref"])
    return holder


def run_main(srv, lab_ref, argv, **ctx_over):
    lab_ref["ref"] = srv.ref
    out = []
    code = L.main(argv, ctx=srv.ctx(**ctx_over), out=out.append)
    return code, "\n".join(out)


# ---------------------------------------------------------------- whole runs
def test_healthy_server_before_the_start_passes_and_prints_no_secret(tmp_path, lab_ref):
    srv = Server(tmp_path, "before")
    code, out = run_main(srv, lab_ref, ["--stage", "before"])
    assert code == 0, out
    assert "[고칠 것]" not in out
    assert "시작 준비가 끝났습니다" in out and L.START_CMD in out
    for s in SECRETS:
        assert s not in out
    assert "BINANCE_API_KEY=set" in out and "DEADMAN_URL=set" in out
    # every printed line is a section header, a tagged line or the verdict's command line
    for row in out.splitlines()[1:]:
        assert row.startswith(("== ", "[OK] ", "[고칠 것] ", "[참고] ", "     ")), row
    # nothing was sent: no Telegram message, no dead-man ping
    assert not srv.sent("sendMessage") and not [h for h in srv.http if "hc-ping.com" in h[1]]


def test_healthy_server_after_the_start_passes_with_test_message_and_ping(tmp_path, lab_ref):
    srv = Server(tmp_path, "after")
    code, out = run_main(srv, lab_ref, ["--stage", "after", "--send-test", "--ping"])
    assert code == 0, out
    assert "봇이 정상으로 돌고 있습니다" in out and "봇 생존 신호 정상: 20초 전" in out
    assert "paperbot-live3: 켜짐·실행 중" in out and "다음 실행 Fri 2026-10-02 00:20:00 UTC" in out
    assert len([h for h in srv.http if "hc-ping.com" in h[1]]) == 1
    # CRITICAL loud, INFO silent; the empty WARN chat falls back to CRITICAL and gets no second message
    msgs = [dict(urllib.parse.parse_qsl(h[3].decode())) for h in srv.sent("sendMessage")]
    assert [(m["chat_id"], m["disable_notification"]) for m in msgs] == [(CHAT, "false"), (CHAT_INFO, "true")]
    for s in SECRETS:
        assert s not in out


def test_a_whole_run_writes_nothing(tmp_path, lab_ref):
    srv = Server(tmp_path, "after")

    def tree():
        return {os.path.join(d, f): os.stat(os.path.join(d, f)).st_mtime_ns
                for d, _, files in os.walk(tmp_path) for f in files}
    before = tree()
    code, out = run_main(srv, lab_ref, ["--stage", "after"])
    assert code == 0, out
    assert tree() == before


def test_one_problem_makes_the_exit_code_1(tmp_path, lab_ref):
    srv = Server(tmp_path, "before")
    srv.write_env("live", live_env(DEADMAN_URL=""))
    code, out = run_main(srv, lab_ref, [])
    assert code == 1
    assert "DEADMAN_URL=empty" in out and "고칠 것 1개" in out and "아직 시작하지 마세요" in out
    assert "== 봇 멈춤 알림" not in out          # nothing more to say there than the env line


def test_a_broken_check_is_reported_and_the_others_still_run(tmp_path, lab_ref, monkeypatch):
    srv = Server(tmp_path, "before")

    def boom(*a):
        raise RuntimeError(f"bad {SECRET}")
    monkeypatch.setattr(L, "check_clock", boom)
    code, out = run_main(srv, lab_ref, [])
    assert code == 1 and "이 점검이 오류로 멈췄습니다: RuntimeError: bad ***" in out
    assert "== 서비스" in out and "== 에이전트 방" in out and SECRET not in out


def test_agents_not_set_up_are_only_notes(tmp_path, lab_ref):
    srv = Server(tmp_path, "before", agents=False)
    os.remove(os.path.join(srv.lib, ".local", "bin", "claude"))
    code, out = run_main(srv, lab_ref, [])
    assert code == 0, out
    assert "에이전트 방은 아직 설정하지 않았습니다" in out and "[참고] Claude Code가 paperbot 사용자에게 설치되지 않았습니다" in out
    assert "[참고] agents.env 값: CLAUDE_CODE_OAUTH_TOKEN=empty" in out
    # --agents yes makes the same server fail
    code, out = run_main(srv, lab_ref, ["--agents", "yes"])
    assert code == 1 and "[고칠 것] Claude Code가 paperbot 사용자에게 설치되지 않았습니다" in out
    code, out = run_main(srv, lab_ref, ["--agents", "no"])
    assert code == 0 and "점검 건너뜀 (--agents no)" in out


# ---------------------------------------------------------------- env files
def test_parse_env_reads_like_systemd():
    text = ("# comment\n; also a comment\n\nA=1\n  B = two words  \nC='pbkdf2$200000$x$y'\nD=\"q\\\"x\"\n"
            "export E=1\nnot a pair\nF=a\\\nb\nA=3\nG=\n")
    values, bad, dup = L.parse_env(text)
    assert values == {"A": "3", "B": "two words", "C": "pbkdf2$200000$x$y", "D": 'q"x', "F": "ab", "G": ""}
    assert bad == [8, 9] and dup == ["A"]


def test_env_files_permissions_values_and_forbidden_keys(tmp_path):
    srv = Server(tmp_path)
    srv.owners[os.path.join(srv.etc, "live.env")] = (0o644, "paperbot", "paperbot")
    srv.write_env("live", live_env(BINANCE_API_SECRET="", TESTNET_API_KEY="t" * 64) + "export X=1\n")
    srv.write_env("agents", agents_env(extra="ANTHROPIC_API_KEY=sk-ant-api03-zzzzzzzzzz\n"))
    srv.write_env("dash", dash_env(BINANCE_API_KEY=KEY))
    ctx = srv.ctx()
    lines = L.check_env_files(ctx, srv.envs(ctx), True)
    f = "\n".join(fixes(lines))
    path = os.path.join(srv.etc, "live.env")
    assert f"live.env 권한이 paperbot:paperbot 644입니다 (맞는 값 root:paperbot 640): sudo chown root:paperbot {path}" in f
    assert "BINANCE_API_KEY=set, BINANCE_API_SECRET=empty" in f
    assert "live.env에 TESTNET_API_KEY 줄이 들어 있습니다" in f and "10번째 줄을 읽을 수 없습니다" in f
    assert "agents.env에 ANTHROPIC_API_KEY 줄이 들어 있습니다: AI 회의가 Claude 구독이 아니라 사용량 과금" in f
    assert "dash.env에 BINANCE_API_KEY 줄이 들어 있습니다" in f
    assert KEY not in txt(lines) and "sk-ant-api03" not in txt(lines)


def test_env_files_missing_folder_or_unreadable(tmp_path):
    srv = Server(tmp_path)
    os.remove(os.path.join(srv.etc, "dash.env"))
    lines = L.check_env_files(srv.ctx(), srv.envs(), False)
    assert any("dash.env가 없습니다: 설치 스크립트가 만듭니다" in t for t in fixes(lines))

    def closed(path):
        raise PermissionError(path)
    ctx = srv.ctx(stat=closed)
    lines = L.check_env_files(ctx, L.read_envs(ctx), False)
    assert fixes(lines) and "sudo로 실행하세요" in txt(lines)


def test_key_and_telegram_shapes(tmp_path):
    srv = Server(tmp_path)
    srv.write_env("live", live_env(BINANCE_API_SECRET="-----BEGIN PRIVATE KEY-----MC4CAQ", TELEGRAM_BOT_TOKEN="abc",
                                   TELEGRAM_CHAT_CRITICAL="my group", BINANCE_API_KEY=KEY[:40]))
    f = "\n".join(fixes(L.check_env_files(srv.ctx(), srv.envs(), True)))
    assert "개인 키(RSA/Ed25519)" in f and "TELEGRAM_BOT_TOKEN 모양" in f and "TELEGRAM_CHAT_CRITICAL 모양" in f
    notes = txt([x for x in L.check_env_files(srv.ctx(), srv.envs(), True) if x[0] == L.NOTE])
    assert "BINANCE_API_KEY 길이가 보통 바이낸스 키(64자)와 다릅니다" in notes


def test_env_billing_names_are_the_runners():
    from paperbot.agents.runner import ENV_BILLING
    assert set(L.ENV_BILLING) == set(ENV_BILLING)
    assert set(ENV_BILLING) <= set(L.FORBIDDEN["agents"])


# ---------------------------------------------------------------- Binance
def binance(srv, **ctx_over):
    ctx = srv.ctx(**ctx_over)
    return L.check_binance(ctx, L.read_env(ctx, "live"))


def test_binance_read_only_key_works(tmp_path):
    srv = Server(tmp_path)
    lines = binance(srv)
    assert st(lines) == [L.OK] * 4, lines
    assert "지역 차단 없음" in txt(lines) and "taker 수수료 0.0500%" in txt(lines) and "읽기만 가능" in txt(lines)
    signed = [h for h in srv.http if "signature=" in h[1]]
    assert len(signed) == len(V3_SYMBOLS) + 2 and all(h[2]["X-MBX-APIKEY"] == KEY for h in signed)
    assert all(h[0] == "GET" for h in srv.http)


def test_binance_region_blocked(tmp_path):
    srv = Server(tmp_path)
    srv.routes["/fapi/v1/time"] = (451, b"Service unavailable from a restricted location", {})
    lines = binance(srv)
    assert st(lines) == [L.FIX] and "지역 차단" in txt(lines) and "서울·도쿄·싱가포르" in txt(lines)


def test_binance_wrong_key_or_ip_shows_the_servers_address(tmp_path):
    srv = Server(tmp_path)
    srv.write_env("live", live_env(BINANCE_API_KEY="b" * 64))
    lines = binance(srv)
    assert st(lines)[-1] == L.FIX and "-2015" in txt(lines) and "203.0.113.7" in txt(lines)


@pytest.mark.parametrize("perm, expect", [
    ({"enableFutures": True}, "선물 거래 권한이 켜져"),
    ({"enableWithdrawals": True, "enableSpotAndMarginTrading": True}, "현물·마진 거래, 출금 권한이 켜져"),
    ({"ipRestrict": False}, "IP 제한이 없습니다"),
])
def test_binance_key_must_be_read_only_and_ip_restricted(tmp_path, perm, expect):
    srv = Server(tmp_path)
    srv.perm.update(perm)
    lines = binance(srv)
    assert any(expect in t for t in fixes(lines)), lines


def test_binance_permission_list_unreadable_is_only_a_note(tmp_path):
    srv = Server(tmp_path)
    srv.routes["apiRestrictions"] = (403, b"forbidden", {})
    lines = binance(srv)
    assert st(lines) == [L.OK, L.OK, L.OK, L.NOTE] and "눈으로 확인하세요" in lines[-1][1]


def test_binance_clock_skew_and_missing_key(tmp_path):
    srv = Server(tmp_path)
    srv.server_ms = NOW + 2500
    srv.write_env("live", live_env(BINANCE_API_KEY=""))
    lines = binance(srv)
    assert "2500 ms 어긋납니다" in txt(lines) and "읽기 전용 키가 비어 있어" in txt(lines)
    assert not [h for h in srv.http if "signature=" in h[1]]


def test_binance_hint_codes():
    assert "-1022" in L.binance_hint('/x: HTTP 400 b\'{"code":-1022,"msg":"Signature for this request is not valid."}'
                                     "'")
    assert "공백 없이" in L.binance_hint('{"code": -2014, "msg": "API-key format invalid."}')
    assert L.binance_hint("plain text") == "plain text"


# ---------------------------------------------------------------- Telegram
def test_telegram_without_send_test_only_checks_the_token(tmp_path):
    srv = Server(tmp_path)
    lines = L.check_telegram(srv.ctx(), srv.envs(), True, False)
    assert st(lines) == [L.OK, L.NOTE] and "@paper_bot" in txt(lines) and "방 2곳" in txt(lines)
    assert not srv.sent("sendMessage") and len(srv.sent("getMe")) == 1


def test_telegram_send_test_reports_each_chat(tmp_path):
    srv = Server(tmp_path)
    srv.routes["sendMessage"] = lambda m, url, h, data: (
        jbody({"ok": False, "description": "Bad Request: chat not found"}, 400)
        if dict(urllib.parse.parse_qsl(data.decode()))["chat_id"] == CHAT_INFO else jbody({"ok": True}))
    lines = L.check_telegram(srv.ctx(), srv.envs(), True, True)
    assert st(lines) == [L.OK, L.OK, L.FIX]
    assert "live.env INFO 방으로 보내지 못했습니다(HTTP 400 Bad Request: chat not found)" in lines[2][1]
    assert "-100으로 시작" in lines[2][1] and TOKEN not in txt(lines)


def test_telegram_agents_chat_is_tested_too_and_a_bad_token_fails(tmp_path):
    srv = Server(tmp_path)
    srv.write_env("agents", agents_env().replace(f"TELEGRAM_CHAT_CRITICAL={CHAT}",
                                                 "TELEGRAM_CHAT_CRITICAL=-1005555555555"))
    lines = L.check_telegram(srv.ctx(), srv.envs(), True, True)
    assert "agents.env의 텔레그램 봇·CRITICAL 방이 live.env와 다릅니다" in txt(lines)
    chats = [dict(urllib.parse.parse_qsl(h[3].decode()))["chat_id"] for h in srv.sent("sendMessage")]
    assert chats == [CHAT, CHAT_INFO, "-1005555555555"]
    srv.write_env("live", live_env(TELEGRAM_BOT_TOKEN="999999:" + "y" * 35))
    lines = L.check_telegram(srv.ctx(), srv.envs(), True, True)
    assert st(lines) == [L.FIX] and "BotFather" in txt(lines) and "y" * 35 not in txt(lines)


def test_telegram_network_error_does_not_leak_the_token(tmp_path):
    srv = Server(tmp_path)

    def down(method, url, headers, data):
        raise OSError(f"cannot reach {url}")
    srv.routes["api.telegram.org"] = down
    lines = L.check_telegram(srv.ctx(), srv.envs(), True, True)
    assert st(lines) == [L.FIX] and "OSError" in txt(lines) and TOKEN not in txt(lines)


# ---------------------------------------------------------------- dead-man check
def test_deadman_pings_only_with_the_flag(tmp_path):
    srv = Server(tmp_path)
    live = srv.envs()["live"]
    lines = L.check_deadman(srv.ctx(), live, False, "before")
    assert st(lines) == [L.OK, L.NOTE] and not srv.http and "'new'" in lines[1][1]
    lines = L.check_deadman(srv.ctx(), live, True, "before")
    assert st(lines) == [L.OK, L.OK, L.NOTE] and "6분" in lines[2][1]
    assert [h[1] for h in srv.http] == [DEADMAN]
    assert DEADMAN not in txt(lines)


def test_deadman_bad_url_or_failed_ping(tmp_path):
    srv = Server(tmp_path)
    srv.write_env("live", live_env(DEADMAN_URL="hc-ping.com/abc"))
    assert st(L.check_deadman(srv.ctx(), srv.envs()["live"], True, "before")) == [L.FIX]
    srv.write_env("live", live_env())
    srv.routes["hc-ping.com"] = (404, b"not found", {})
    lines = L.check_deadman(srv.ctx(), srv.envs()["live"], True, "after")
    assert st(lines) == [L.OK, L.FIX] and "HTTP 404" in lines[1][1]
    assert L.check_deadman(srv.ctx(), L.EnvFile("live", "x"), True, "before") == []


# ---------------------------------------------------------------- dashboard, Tailscale, firewall
def test_password_hash_is_the_dashboards_own_format():
    from paperbot.dash.app import hash_password
    assert L.password_hash_ok(hash_password("correct horse battery"))
    assert L.password_hash_ok(PW_HASH)
    for bad in ("", "pbkdf2", "pbkdf2200000xx", "pbkdf2$1000$c2FsdHNhbHQ=$" + base64.b64encode(b"k" * 32).decode(),
                PW_HASH[:-8]):
        assert not L.password_hash_ok(bad)


@pytest.mark.parametrize("host, expect", [
    (TS_IP, [L.OK]), ("127.0.0.1", [L.OK, L.NOTE]), ("localhost", [L.OK, L.NOTE]), ("0.0.0.0", [L.FIX]),
    ("203.0.113.9", [L.FIX]), ("my-server", [L.FIX]), ("fd7a:115c:a1e0::1", [L.OK]),
])
def test_dash_host(host, expect):
    assert st(L.dash_host_lines(host)) == expect


def test_dash_env_lines(tmp_path):
    srv = Server(tmp_path)
    assert st(L.check_dash(srv.ctx(), srv.envs()["dash"], "before")) == [L.OK, L.OK, L.OK]
    srv.write_env("dash", dash_env(DASH_PASSWORD_HASH="pbkdf2", DASH_SECRET="short", DASH_SECURE_COOKIE="1"))
    lines = L.check_dash(srv.ctx(), srv.envs()["dash"], "before")
    assert st(lines) == [L.FIX, L.FIX, L.OK, L.FIX] and "작은따옴표" in lines[0][1] and "openssl" in lines[1][1]


def test_dash_after_start_must_listen_on_dash_host_only(tmp_path):
    srv = Server(tmp_path, "after")
    lines = L.check_dash(srv.ctx(), srv.envs()["dash"], "after")
    assert st(lines) == [L.OK] * 4 and f"http://{TS_IP}:8080" in lines[-1][1]
    srv.cmd_out[("ss",)] = (0, "LISTEN 0 2048 0.0.0.0:8080 0.0.0.0:*\n", "")
    f = fixes(L.check_dash(srv.ctx(), srv.envs()["dash"], "after"))
    assert any("모든 주소에 열려" in t for t in f) and any("DASH_HOST(" in t for t in f)
    srv.cmd_out[("ss",)] = (0, "LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\n", "")
    assert any("8080 포트에서 기다리고 있지 않습니다" in t for t in fixes(L.check_dash(srv.ctx(), srv.envs()["dash"], "after")))


def test_a_wrong_dash_host_is_reported_once(tmp_path):
    srv = Server(tmp_path, "after")
    srv.write_env("dash", dash_env(DASH_HOST="0.0.0.0"))
    dash = srv.envs()["dash"]
    assert len(fixes(L.check_dash(srv.ctx(), dash, "after"))) == 1
    assert not fixes(L.check_tailscale(srv.ctx(), dash))
    srv.write_env("dash", dash_env(DASH_HOST="100.64.0.77"))        # another machine's Tailscale address
    assert any("이 서버의 Tailscale 주소" in t for t in fixes(L.check_tailscale(srv.ctx(), srv.envs()["dash"])))


def test_tailscale_and_firewall(tmp_path):
    srv = Server(tmp_path)
    dash = srv.envs()["dash"]
    lines = L.check_tailscale(srv.ctx(), dash)
    assert st(lines) == [L.OK, L.OK] and TS_IP in lines[0][1]
    srv.tailscale["Self"]["KeyExpiry"] = "2027-03-30T00:00:00Z"
    srv.tailscale["Self"]["TailscaleIPs"] = ["100.64.0.9"]
    lines = L.check_tailscale(srv.ctx(), dash)
    assert st(lines) == [L.OK, L.FIX, L.NOTE, L.OK] and "2027-03-30" in lines[2][1]
    srv.cmd_out[("ufw", "status")] = (0, UFW_OK.replace("Anywhere on tailscale0", "8080/tcp") + "", "")
    f = fixes(L.check_tailscale(srv.ctx(), dash))
    assert any("8080 포트가 인터넷에 열려" in t for t in f) and any("ufw allow in on tailscale0" in t for t in f)
    srv.cmd_out[("ufw", "status")] = (0, "Status: inactive\n", "")
    assert any("방화벽(ufw)이 꺼져" in t for t in fixes(L.check_tailscale(srv.ctx(), dash)))
    # not root: the firewall is not looked at
    before = len(srv.calls)
    lines = L.check_tailscale(srv.ctx(euid=999, username="paperbot"), dash)
    assert lines[-1] == (L.NOTE, "방화벽(ufw) 규칙은 sudo(root)로 실행할 때만 확인합니다")
    assert [c[0][0] for c in srv.calls[before:]] == ["tailscale"]


def test_tailscale_missing_is_fine_only_with_an_ssh_tunnel(tmp_path):
    srv = Server(tmp_path)
    srv.tailscale = None
    assert st(L.check_tailscale(srv.ctx(), srv.envs()["dash"]))[0] == L.FIX
    srv.write_env("dash", dash_env(DASH_HOST="127.0.0.1"))
    srv.cmd_out[("ufw", "status")] = (0, UFW_OK.replace("Anywhere on tailscale0     ALLOW       Anywhere\n", ""), "")
    lines = L.check_tailscale(srv.ctx(), srv.envs()["dash"])
    assert st(lines) == [L.NOTE, L.OK] and "SSH 터널" in lines[0][1]


# ---------------------------------------------------------------- server size, clock
def test_resources(tmp_path):
    srv = Server(tmp_path)
    states = srv.unit_table("before", True)
    assert st(L.check_resources(srv.ctx(), states)) == [L.OK, L.OK, L.OK]
    lines = L.check_resources(srv.ctx(cpu_count=lambda: 2, disk_free=lambda p: 3e9), states)
    assert st(lines) == [L.FIX, L.OK, L.FIX] and "--procs 4" in lines[0][1] and "--procs 2" in lines[0][1]
    states["paperbot-live3.service"]["ExecStart"] = "argv[]=python -m paperbot.live3 run --procs 2 ;"
    with open(srv.meminfo, "w") as fh:
        fh.write("MemTotal:        3900000 kB\n")
    lines = L.check_resources(srv.ctx(cpu_count=lambda: 2, disk_free=lambda p: 12e9), states)
    assert st(lines) == [L.NOTE, L.NOTE, L.NOTE]
    assert L.live3_procs(None) is None


def test_clock(tmp_path):
    srv = Server(tmp_path)
    assert st(L.check_clock(srv.ctx())) == [L.OK]
    srv.cmd_out[("chronyc",)] = (0, CHRONY_OK.replace("Normal", "Not synchronised"), "")
    assert "Not synchronised" in L.check_clock(srv.ctx())[0][1]
    srv.cmd_out[("chronyc",)] = (1, "", "506 Cannot talk to daemon")
    assert st(L.check_clock(srv.ctx())) == [L.FIX]
    del srv.cmd_out[("chronyc",)]
    assert "설치 스크립트" in L.check_clock(srv.ctx())[0][1]


# ---------------------------------------------------------------- systemd units
def test_units_before_the_start(tmp_path):
    srv = Server(tmp_path)
    states = L.unit_states(srv.ctx())
    lines = L.check_units(states, "before", True)
    assert L.FIX not in st(lines), lines
    assert "서비스 파일 14개 설치됨" in txt(lines) and "아직 꺼져 있음" in txt(lines)
    states["paperbot-dash.service"]["LoadState"] = "not-found"
    states[L.EXECUTOR]["UnitFileState"] = "enabled"
    states["paperbot-record.timer"].update(LoadState="loaded", UnitFileState="enabled", ActiveState="active")
    states["paperbot-live3.service"]["ActiveState"] = "active"
    states["chrony.service"]["ActiveState"] = "inactive"
    lines = L.check_units(states, "before", True)
    f = "\n".join(fixes(lines))
    assert "설치되지 않은 서비스: paperbot-dash.service" in f and "disable --now paperbot-executor" in f
    assert "paperbot-record.timer" in f and "enable --now chrony" in f
    assert "이미 켜져 있음: paperbot-live3" in txt(lines)
    assert L.check_units(None, "before", False) == [(L.FIX, L.check_units(None, "after", True)[0][1])]


def test_units_after_the_start(tmp_path):
    srv = Server(tmp_path, "after")
    states = L.unit_states(srv.ctx())
    assert L.FIX not in st(L.check_units(states, "after", True))
    states["paperbot-live3.service"].update(ActiveState="activating", SubState="auto-restart", NRestarts="12")
    states["paperbot-checkpoint.timer"]["UnitFileState"] = "disabled"
    states["paperbot-backup.service"]["Result"] = "exit-code"
    states["paperbot-checkpoint.service"]["Result"] = "exit-code"
    states["paperbot-agents.service"].update(Result="exit-code", ExecMainStatus="2")
    states[L.EXECUTOR]["ActiveState"] = "active"
    lines = L.check_units(states, "after", True)
    f = "\n".join(fixes(lines))
    assert "paperbot-live3: 실행 중이 아님(activating/auto-restart); 12번 다시 시작함(계속 죽는 중). 원인: journalctl" in f
    assert f.count("journalctl -u paperbot-live3") == 1
    assert "paperbot-checkpoint.timer: 꺼져 있음" in f and "paperbot-backup의 지난 실행이 실패" in f
    assert "Claude 로그인 확인에서 멈췄습니다" in f
    notes = txt([x for x in lines if x[0] == L.NOTE])
    assert "paperbot-checkpoint의 지난 실행이 실패" in notes and "주문 실행기(paperbot-executor)가 켜져" in notes
    # agents not wanted: their timers off are only notes
    states2 = Server(tmp_path / "b", "after", agents=False).unit_table("after", False)
    lines = L.check_units(states2, "after", False)
    assert L.FIX not in st(lines)
    assert "에이전트 방 타이머 꺼져 있음: paperbot-agents.timer, paperbot-labmonthly.timer" in txt(lines)


def test_expected_units_are_the_ones_install_sh_installs():
    with open(os.path.join(REPO_ROOT, "deploy", "install.sh")) as fh:
        text = fh.read()
    loop = re.search(r"for u in ([^;]*); do\s+install -m 644", text).group(1)
    installed = set(loop.replace("\\", " ").split())
    assert set(L.INSTALLED) <= installed            # never asks for a unit install.sh does not install
    for u in L.INSTALLED + L.LEGACY:
        assert os.path.exists(os.path.join(REPO_ROOT, "deploy", u)), u


def test_offsite_timer_is_required_once_installed(tmp_path):
    srv = Server(tmp_path, "after")
    states = L.unit_states(srv.ctx())
    assert "offsite" not in txt(L.check_units(states, "after", True))           # not installed: not asked
    assert L.start_command(states) == L.START_CMD
    states["paperbot-offsite.timer"] = {"LoadState": "loaded", "UnitFileState": "disabled",
                                        "ActiveState": "inactive"}
    states["paperbot-offsite.service"] = {"LoadState": "loaded", "Result": "exit-code"}
    f = fixes(L.check_units(states, "after", True))
    assert any("paperbot-offsite.timer: 꺼져 있음" in t for t in f)
    assert any("paperbot-offsite의 지난 실행이 실패" in t for t in f)
    assert L.start_command(states) == L.START_CMD + " paperbot-offsite.timer"


def test_backup_chat_is_checked_and_tested_when_set(tmp_path):
    srv = Server(tmp_path)
    srv.write_env("live", live_env(TELEGRAM_CHAT_BACKUP="-1007777777777", BACKUP_PASSPHRASE="correct horse battery"))
    lines = L.check_telegram(srv.ctx(), srv.envs(), True, True)
    chats = [dict(urllib.parse.parse_qsl(h[3].decode()))["chat_id"] for h in srv.sent("sendMessage")]
    assert chats == [CHAT, CHAT_INFO, "-1007777777777"] and "live.env BACKUP 방" in txt(lines)
    assert "correct horse battery" in L.secret_values(srv.envs())
    srv.write_env("live", live_env(TELEGRAM_CHAT_BACKUP="backup group"))
    assert any("TELEGRAM_CHAT_BACKUP 모양" in t for t in fixes(L.check_env_files(srv.ctx(), srv.envs(), True)))


# ---------------------------------------------------------------- code, data, paper3.db
def test_code_version_rules_and_clone(tmp_path):
    srv = Server(tmp_path)
    lines = L.check_code(srv.ctx())
    assert st(lines) == [L.OK, L.OK] and "커밋 d86c085000" in lines[0][1] and "규칙 문서 2개" in lines[1][1]
    srv.head = "e" * 40
    srv.cmd_out[(VENV, "-c", "import paperbot")] = (1, "", "/opt/paperbot/venv/bin/python: No module named 'paperbot'")
    lines = L.check_code(srv.ctx())
    assert st(lines) == [L.OK, L.OK, L.NOTE, L.NOTE] and "git pull" in lines[2][1] and "cd /opt" in lines[3][1]
    assert [c[2] for c in srv.calls if c[0][0] == VENV] == ["/", "/"]
    with open(os.path.join(srv.app, "docs", "paper-v3-rules.md"), "a") as fh:
        fh.write("changed\n")
    with open(os.path.join(srv.app, "VERSION.json"), "w") as fh:
        json.dump({"commit": COMMIT, "dirty": True}, fh)
    f = fixes(L.check_code(srv.ctx()))
    assert "커밋 안 된 수정" in f[0] and "docs/paper-v3-rules.md" in f[1]
    os.remove(os.path.join(srv.app, "VERSION.json"))
    assert "VERSION.json이 없습니다" in fixes(L.check_code(srv.ctx()))[0]


def test_data_folder_files_must_belong_to_paperbot(tmp_path):
    srv = Server(tmp_path)
    assert st(L.check_data_dir(srv.ctx())) == [L.OK]
    lock = os.path.join(srv.lib, "agents3.db.lock")
    open(lock, "w").close()
    srv.owners[lock] = (0o644, "root", "root")
    f = fixes(L.check_data_dir(srv.ctx()))
    assert len(f) == 1 and lock in f[0] and f"sudo chown -R paperbot:paperbot {srv.lib}" in f[0]


def test_paper_db_before_the_start(tmp_path):
    srv = Server(tmp_path)
    lines = L.check_paper_db(srv.ctx(), "before")
    assert st(lines) == [L.OK] and "새로 시작" in lines[0][1]
    srv.make_db(start=None)
    assert "아직 계좌가 없습니다" in L.check_paper_db(srv.ctx(), "before")[0][1]
    os.remove(os.path.join(srv.lib, "paper3.db"))
    srv.make_db(start=NOW - 3 * 3_600_000)
    assert st(L.check_paper_db(srv.ctx(), "before")) == [L.NOTE]
    os.remove(os.path.join(srv.lib, "paper3.db"))
    srv.make_db(start=NOW - 9 * DAY)
    lines = L.check_paper_db(srv.ctx(), "before")
    assert st(lines) == [L.FIX] and "9일 전(2026-09-22)" in lines[0][1] and "--stage after" in lines[0][1]
    moved = f"{srv.lib}/paper3.db* {srv.lib}/daily3.db* {srv.lib}/checkpoint.db*"
    assert f"sudo mv {moved} {srv.backups}/old/" in lines[0][1]


def test_paper_db_after_the_start(tmp_path):
    srv = Server(tmp_path, "after")
    lines = L.check_paper_db(srv.ctx(), "after")
    assert st(lines) == [L.OK, L.OK, L.OK] and "계좌 195개" in lines[1][1] and "0.0500%" in lines[1][1]
    stale = L.check_paper_db(srv.ctx(now_ms=lambda: NOW + 10 * MIN), "after")
    assert stale[0][0] == L.FIX and "620초 전" in stale[0][1]
    os.remove(os.path.join(srv.lib, "paper3.db"))
    srv.make_db(start=NOW - MIN, heartbeat=None, brackets="EXAMPLE TABLE (not exchange data)", commit="f" * 40)
    lines = L.check_paper_db(srv.ctx(), "after")
    assert st(lines) == [L.FIX, L.FIX, L.NOTE, L.OK] and "400일치" in lines[0][1] and "예시" in lines[1][1]
    os.remove(os.path.join(srv.lib, "paper3.db"))
    assert "아직 없습니다" in fixes(L.check_paper_db(srv.ctx(), "after"))[0]


# ---------------------------------------------------------------- agent rooms
def test_lab_files_against_the_reference(tmp_path):
    srv = Server(tmp_path)
    lines = L.check_lab(srv.ctx(), None, True, ref=srv.ref)
    assert lines == [(L.OK, "5년 시험 자료 2/2개가 연구 자료와 같음")]
    assert not os.path.exists(os.path.join(srv.lib, "lab", LD.MANIFEST))       # read-only, unlike labdata check
    np.savez_compressed(os.path.join(srv.lib, "lab", "sig_5m_BTCUSD.npz"), ts=np.arange(3))
    lines = L.check_lab(srv.ctx(), None, True, ref=srv.ref)
    assert st(lines) == [L.FIX] and "1/2개만" in lines[0][1] and "다름 1" in lines[0][1]
    assert st(L.check_lab(srv.ctx(), None, False, ref=srv.ref)) == [L.NOTE]
    srv.owners[os.path.join(srv.lib, "lab")] = (0o755, "root", "root")
    assert "chown -R paperbot:paperbot" in L.check_lab(srv.ctx(), None, False, ref=srv.ref)[0][1]
    building = {L.LABBUILD: {"ActiveState": "active"}}
    assert "만드는 중" in L.check_lab(srv.ctx(), building, True, ref=srv.ref)[0][1]
    lines = L.check_lab(srv.ctx(lib=str(tmp_path / "nowhere")), None, True, ref=srv.ref)
    assert st(lines) == [L.FIX] and "systemd-run" in lines[0][1]


def test_claude_login_runs_as_paperbot_with_the_token_in_the_environment(tmp_path):
    srv = Server(tmp_path)
    lines = L.check_claude(srv.ctx(), srv.envs()["agents"], True)
    assert lines == [(L.OK, "Claude Code 로그인: 구독으로 로그인됨 (oauth_token), API 키 아님")]
    cmd, env, _ = [c for c in srv.calls if c[0][0] == L.RUNUSER][0]
    claude = os.path.join(srv.lib, ".local", "bin", "claude")
    assert cmd == [L.RUNUSER, "-u", "paperbot", "--", claude, "--setting-sources", "", "auth", "status", "--json"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == CLAUDE and env["HOME"] == srv.lib
    assert CLAUDE not in " ".join(cmd) and "AGENTS_BUDGET" not in env and "TELEGRAM_BOT_TOKEN" not in env
    # as paperbot itself: no runuser
    srv.calls.clear()
    assert st(L.check_claude(srv.ctx(euid=999, username="paperbot"), srv.envs()["agents"], True)) == [L.OK]
    assert srv.calls[0][0][0] == claude
    assert st(L.check_claude(srv.ctx(euid=1000, username="ubuntu"), srv.envs()["agents"], True)) == [L.NOTE]


@pytest.mark.parametrize("auth, expect", [
    ({"loggedIn": True, "authMethod": "api_key", "apiKeySource": "/login managed key"}, "API 키"),
    ({"loggedIn": False}, "setup-token"),
    ({"loggedIn": True, "authMethod": "third_party", "apiProvider": "bedrock"}, "Bedrock"),
])
def test_claude_login_refusals(tmp_path, auth, expect):
    srv = Server(tmp_path)
    srv.auth = auth
    lines = L.check_claude(srv.ctx(), srv.envs()["agents"], True)
    assert st(lines) == [L.FIX] and expect in lines[0][1]
    assert st(L.check_claude(srv.ctx(), srv.envs()["agents"], False)) == [L.NOTE]


def test_agents_policy_template_and_observation(tmp_path):
    srv = Server(tmp_path)
    ag = srv.envs()["agents"]
    lines = L.check_agents_policy(srv.ctx(), ag, True, None)
    assert st(lines) == [L.OK, L.OK], lines                # the owners' template: no budget warning
    assert "AI 하루 최대 160회" in lines[0][1] and "봇 첫 시작부터 21일 복사 제안 없음" in lines[1][1]
    start = NOW - 2 * DAY
    assert "2026-10-20까지" in L.check_agents_policy(srv.ctx(), ag, True, start)[1][1]
    srv.write_env("agents", agents_env(extra="AGENTS_BUDGET=loss=8\n"))
    lines = L.check_agents_policy(srv.ctx(), srv.envs()["agents"], True, None)
    assert L.NOTE in st(lines) and "예산 경고" in txt(lines)
    srv.write_env("agents", agents_env(extra="AGENTS_BUDGET=loss=lots\n"))
    lines = L.check_agents_policy(srv.ctx(), srv.envs()["agents"], True, None)
    assert st(lines) == [L.FIX] and "agents.env 값이 잘못됐습니다" in lines[0][1]
    srv.write_env("agents", agents_env(extra="AGENTS_OBSERVE_UNTIL=2026-09-30\n"))
    assert "이미 지났습니다" in L.check_agents_policy(srv.ctx(), srv.envs()["agents"], True, None)[-1][1]
    srv.write_env("agents", agents_env(extra="AGENTS_OBSERVE_DAYS=0\n"))
    assert "관찰 기간 꺼짐" in L.check_agents_policy(srv.ctx(), srv.envs()["agents"], True, None)[-1][1]
    os.remove(os.path.join(srv.etc, "agents.env"))
    assert st(L.check_agents_policy(srv.ctx(), srv.envs()["agents"], False, None)) == [L.NOTE]


def test_secret_values_and_scrub():
    envs = {"live": L.EnvFile("live", "x", values={"BINANCE_API_KEY": KEY, "DEADMAN_URL": DEADMAN,
                                                   "TELEGRAM_CHAT_WARN": ""}),
            "dash": L.EnvFile("dash", "y", values={"DASH_HOST": TS_IP, "DASH_SECRET": DASH_SECRET}),
            "agents": L.EnvFile("agents", "z", values={"AGENTS_BUDGET": "total=80:2000000", "AGENTS_OWNER_OK": "auto"})}
    secrets = L.secret_values(envs)
    assert TS_IP not in secrets and "total=80:2000000" not in secrets
    text = L.scrub(f"{KEY} {DEADMAN} /0f3c1d2e-aaaa-bbbb-cccc-1234567890ab {DASH_SECRET} {TS_IP}", secrets)
    assert text == f"*** *** /*** *** {TS_IP}"
