"""Paper launch check (v3, and the paper v4 run since the 2026-10 restart): is this server ready to start the paper
bot, and does it run as it should?

    cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage before
    cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
    cd <repo> && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.launchcheck --db <paper db>

    --stage before|after   before: everything filled in and installed, nothing started yet (default);
                           after: the bot, dashboard, recorders and timers run, the bot's heartbeat is fresh
    --send-test            one test message to every configured Telegram chat
    --ping                 one ping to DEADMAN_URL (healthchecks.io then shows the check as "up")
    --agents auto|yes|no   the agent rooms: yes = required, no = not checked, auto (default) = required once
                           agents.env has a Claude token or paperbot-agents.timer is enabled, else shown as [참고]
    --skip-lab             do not re-hash the 5-year lab files (a minute or so of disk reads)
    --db PATH              check only this run database (a staging run, a rehearsal copy): the bot's heartbeat, its
                           start record, the v4 account set per group, frozen (held) accounts, signal strength;
                           nothing else on the server is looked at (implies --stage after)

The account set (paper v4, docs/paper-v4-rules.md): every original account kind (accounts.ORIGINAL_KINDS) counted per
group and timeframe against config.V4_GROUPS (331: the 36 on 15m / 30m / 1h / 4h, the DeepSeek definitions on their
own timeframes, the reel and three coin flips on 5m, three coin flips on each core timeframe), all made on one UTC day
by a paper-v4 runner. A database of the v3 run is [고칠 것] with the reset command; any other difference is
[고칠 것] for the developer (never the reset: that would archive a running v4 run). A frozen account (HeldEngine:
its engine code could not be loaded at the start, accounts.AccountBook) is [고칠 것].

Prints one Korean line per check: [OK], [고칠 것] (fix it before going on; the exit code is 1 while one is
left) or [참고] (worth knowing; read it, usually nothing to do), then a verdict. Exit code 0 only when
nothing is left to fix: the owners' pass condition is "no [고칠 것] line and the last line is [OK]"
(docs/server-setup-v3.md 10 and 12), not "every line is [OK]".

Run it as root (sees everything; the Claude Code check then runs as user paperbot through runuser) or as
user paperbot (``sudo -u paperbot``: the env files are group-readable; the firewall is then not checked).

Safe at any time, also while the bot runs:
- secrets are never printed: values show only as "set" / "empty", every line is scrubbed of the env
  files' values (also in their escaped and URL-quoted forms) before it is printed, and a failed network
  call is reported by its error type only (its message may hold a URL with the bot token);
- nothing is written, started, enabled or changed: the env files are parsed the way systemd reads them
  (never ``source``d), paper3.db and liq.db are opened read-only (``immutable`` while their writer is
  stopped, so SQLite leaves no -wal/-shm files behind), and the lab files are hashed in memory
  (``labdata check`` itself writes its manifest, so it is not called). Python may still write its
  byte-code cache (__pycache__) for the code it imports, as for any program run by root;
- outbound calls: Binance public data and the read-only key's signed GETs (fapi.binance.com,
  api.binance.com), Telegram getMe and getChat (read-only: is the bot in each alert chat); with
  --send-test one message per chat instead of getChat, with --ping one GET of DEADMAN_URL. Nothing here
  can place an order.

Each check is a small function of a ``Ctx`` whose command runner, HTTP fetcher, file-info lookup, clock
and paths are injectable: tests/test_launchcheck.py fakes all of them (no network, no real system).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import grp
import hashlib
import http.client
import ipaddress
import json
import os
import pwd
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, Iterable, Optional, Sequence

from .binance import FAPI, BinanceError, BinanceREST, RegionBlocked
from .config import V3_SYMBOLS, V4_ACCOUNTS, V4_GROUP_ACCOUNTS, V4_VERSION, v3_settings
from .sessions import KST

OK, FIX, NOTE = "OK", "고칠 것", "참고"
Line = tuple  # (status, text)

ETC = "/etc/paperbot"
APP = "/opt/crypto-bot-research"
LIB = "/var/lib/paperbot"
BACKUPS = "/var/backups/paperbot"
REPO = "/root/crypto-bot-research"           # where docs/server-setup-v3.md clones the repository
VENV_PY = "/opt/paperbot/venv/bin/python"
USER = "paperbot"
# the order executor's own user (deploy/install.sh): never USER, whose processes (the agent rooms, the dashboard)
# could otherwise read the order keys from the executor's /proc/<pid>/environ (docs/live-safety.md 1-9)
EXEC_USER = "paperbot-exec"
RUNUSER = "/usr/sbin/runuser"               # util-linux; runs the command itself, not paperbot's nologin shell
WALLET_API = "https://api.binance.com"      # key permissions (GET /sapi/v1/account/apiRestrictions)
TELEGRAM = "https://api.telegram.org"
DAY_MS = 86_400_000
HEARTBEAT_MAX_S = 90                        # the dashboard's "봇 생존 신호: 정상" threshold
FRESH_RUN_MS = DAY_MS                       # before the start: a paper3.db younger than this is "just started"
MAX_RESTARTS = 3
RESTART_RECENT_S = 600                      # restarts count as "keeps crashing" while the current run is younger
SETTLE_MS = 10 * 60_000                     # after a start: bars, dead-man pings and the liq stream are judged
BAR_LAG_MAX_MS = 3 * 60_000                 # health.DeadMan withholds its ping past this lag
PING_MAX_MS = 3 * 60_000                    # the bot pings every minute: older than this is not pinging
LIQ_DOWN_MAX_MS = 10 * 60_000
TAILNET = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
ERROR_PREFIX = "이 점검이 오류로 멈췄습니다: "
ERROR_MAX = 300                             # an error line is cut after it is scrubbed, never before

INSTALL = "cd /root/crypto-bot-research && sudo bash deploy/install.sh"
START_CMD = ("sudo systemctl enable --now paperbot-live3 paperbot-dash paperbot-liq paperbot-daily3.timer "
             "paperbot-backup.timer paperbot-checkpoint.timer")
AFTER_CMD = ("cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck "
             "--stage after")
CLAUDE_INSTALL = "sudo -u paperbot -H bash -c 'cd ~ && curl -fsSL https://claude.ai/install.sh | bash'"
CLAUDE_TOKEN = "sudo -u paperbot -H /var/lib/paperbot/.local/bin/claude setup-token"
# --collect: a build that fails (e.g. "download failed ... run the same command again") leaves no failed
# transient unit behind, so the same command can be pasted again (docs/server-setup-v3.md 9)
LAB_BUILD = ("sudo systemd-run --uid=paperbot --gid=paperbot --unit=paperbot-labbuild --collect "
             "-p WorkingDirectory=/opt/crypto-bot-research -p Nice=10 /opt/paperbot/venv/bin/python "
             "-m paperbot.agents.labdata build --out /var/lib/paperbot/lab --procs 2")
OFFSITE_INSTALL = ("sudo install -m 644 /opt/crypto-bot-research/deploy/paperbot-offsite.service "
                   "/opt/crypto-bot-research/deploy/paperbot-offsite.timer /etc/systemd/system/ && "
                   "sudo systemctl daemon-reload")
# `claude setup-token` prints sk-ant-oat01- and a long run of base64url characters (well over 60, an
# assumption from the tokens seen, not a documented length); an API key starts sk-ant-api
CLAUDE_TOKEN_RE = re.compile(r"sk-ant-oat\d\d-[A-Za-z0-9_-]+")
CLAUDE_TOKEN_MIN_TAIL = 60

# env file -> (owner, group, mode) as deploy/install.sh makes them
DEBATE_USER = "paperbot-debate"             # the 24-hour debate room's own user (paid API key, docs/debate-room.md)
ENV_SPECS = {"live": ("root", USER, 0o640), "dash": ("root", USER, 0o640),
             "agents": ("root", USER, 0o640), "executor": ("root", "root", 0o600),
             # the paid API key: its own group, so user paperbot (agents, dashboard, live runner) cannot read it
             "debate": ("root", DEBATE_USER, 0o640)}
LIVE_REQUIRED = ("BINANCE_API_KEY", "BINANCE_API_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL",
                 "DEADMAN_URL")
LIVE_OPTIONAL = ("TELEGRAM_CHAT_WARN", "TELEGRAM_CHAT_INFO")
CHAT_KEYS = ("TELEGRAM_CHAT_CRITICAL",) + LIVE_OPTIONAL + ("TELEGRAM_CHAT_BACKUP",)   # BACKUP: offsite copy
DASH_REQUIRED = ("DASH_PASSWORD_HASH", "DASH_SECRET", "DASH_HOST")
AGENTS_REQUIRED = ("CLAUDE_CODE_OAUTH_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL")
ORDER_KEYS = ("TESTNET_API_KEY", "TESTNET_API_SECRET", "LIVE_API_KEY", "LIVE_API_SECRET", "PAPERBOT_LIVE_MAINNET")
EXCHANGE_KEYS = ("BINANCE_API_KEY", "BINANCE_API_SECRET") + ORDER_KEYS
# same names as paperbot/agents/runner.ENV_BILLING (a test keeps them equal): per-token billing outside the plan
ENV_BILLING = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
CLAUDE_KEY = "CLAUDE_CODE_OAUTH_TOKEN"
DEBATE_KEY = "ANTHROPIC_API_KEY"            # only /etc/paperbot/debate.env may hold it (checked in every other env file)
FORBIDDEN = {
    "live": {**{k: "주문용 키·스위치는 executor.env(root만 읽음)에만 둡니다" for k in ORDER_KEYS},
             CLAUDE_KEY: "Claude 토큰은 agents.env에만 둡니다",
             DEBATE_KEY: "유료 API 키는 debate.env(24시간 토론방 전용)에만 둡니다"},
    "dash": {**{k: "대시보드에는 거래소 키가 필요 없습니다" for k in EXCHANGE_KEYS},
             CLAUDE_KEY: "대시보드에는 Claude 토큰이 필요 없습니다",
             DEBATE_KEY: "유료 API 키는 debate.env(24시간 토론방 전용)에만 둡니다"},
    "debate": {**{k: "토론방에는 거래소 키가 필요 없습니다" for k in EXCHANGE_KEYS},
               CLAUDE_KEY: "토론방은 구독 토큰이 아니라 API 키(debate.env)를 씁니다"},
    "agents": {**{k: "AI 회의가 Claude 구독이 아니라 사용량 과금으로 바뀝니다" for k in ENV_BILLING},
               **{k: "에이전트는 거래소 키를 갖지 않습니다" for k in EXCHANGE_KEYS}},
}
# values that are not secret (never scrubbed from the output)
PUBLIC_KEYS = ("DASH_HOST", "DASH_OWNERS")
PUBLIC_PREFIXES = ("AGENTS_", "LAB_")

SERVICES = ("paperbot-live3.service", "paperbot-dash.service", "paperbot-liq.service")
TIMERS = ("paperbot-daily3.timer", "paperbot-backup.timer", "paperbot-checkpoint.timer")
AGENT_TIMERS = ("paperbot-agents.timer", "paperbot-labmonthly.timer")
JOBS = ("paperbot-daily3.service", "paperbot-backup.service", "paperbot-checkpoint.service",
        "paperbot-agents.service", "paperbot-labmonthly.service")
EXECUTOR = "paperbot-executor.service"
LEGACY = ("paperbot-live.service", "paperbot-evening.service", "paperbot-evening.timer",
          "paperbot-record.service", "paperbot-record.timer")
SYSTEM = ("fail2ban.service", "chrony.service")
AUTO_UPDATES = "unattended-upgrades.service"    # installed and enabled by install.sh's package list
LABBUILD = "paperbot-labbuild.service"
# required once installed: the off-site copy of the nightly backup (paperbot/offsite.py), added after the
# first install.sh; a server whose install.sh does not install it yet is not asked for it (a [참고] says so)
EXTRA_TIMERS = ("paperbot-offsite.timer",)
# required once installed, like the off-site timer: GH Coin's call recorder (ghcoin/recorder.mjs, a service)
EXTRA_SERVICES = ("paperbot-ghcoin.service", "paperbot-tgtrades.service")
OFFSITE_TIMER = "paperbot-offsite.timer"
# optional: installed by install.sh but left off (the owners turn it on once, docs/server-setup-v3.md); when it is
# installed its state is shown as [참고] only, never [고칠 것]: the weekly checkpoint rehearsal (checkpoint_preview)
OPTIONAL_TIMERS = ("paperbot-rehearsal.timer", "paperbot-obsidian.timer", "paperbot-shadow200.timer",
                   "paperbot-dscheck.timer")
# paper v4 reset (deploy/paperbot-reset.sh AFTER_CHECK_TIMERS): installed by the reset but left off; the owners turn
# them on after this check (docs/server-setup-v4.md step 5). Off after a reset is a [참고] with that one command.
AFTER_CHECK_TIMERS = ("paperbot-obsidian.timer", "paperbot-shadow200.timer", "paperbot-dscheck.timer")
# what the owners lose while the agents' tick is off (the same words as deploy/paperbot-reset.sh AGENTS_OFF_KO)
AGENTS_OFF_KO = "에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음"
# the bot's start line (live3: settings.version "paper-v4" -> "paper v4 started: N accounts (...)"), from config
RUN_NAME = V4_VERSION.replace("paper-v", "paper v")
# ... as Telegram words it (notify._run_started): '▶️ 봇 시작 · 모의 v4 · 계좌 331개' on a first start, '봇 재시작 · … 이어서
# 돌림' after an install or any restart (live3 logs 'paper v4 resumed: …' then)
RUN_KO = V4_VERSION.replace("paper-v", "모의 v")
# optional, paid: the 24-hour debate room. Installed by install.sh and left off; shown as [참고] unless the owners
# turned it on, and then a missing key is a [고칠 것]. Never part of INSTALLED (not installed is not a problem).
DEBATE_UNIT = "paperbot-debate.service"
INSTALLED = SERVICES + TIMERS + AGENT_TIMERS + JOBS + (EXECUTOR,)
ALL_UNITS = (INSTALLED + LEGACY + SYSTEM + (AUTO_UPDATES, LABBUILD) + EXTRA_TIMERS + EXTRA_SERVICES
             + ("paperbot-offsite.service", DEBATE_UNIT) + OPTIONAL_TIMERS
             + tuple(u.replace(".timer", ".service") for u in OPTIONAL_TIMERS))
UNIT_PROPS = ("Id,LoadState,UnitFileState,ActiveState,SubState,Result,NRestarts,ExecMainStatus,"
              "NextElapseUSecRealtime,ExecStart,ActiveEnterTimestampMonotonic,User,MainPID")
RULES_SUMS = ("docs/paper-v3-rules.sha256", "docs/paper-v3-rules-addendum.sha256",
              "docs/paper-v3-rules-change-1.sha256",    # change 1: 5m removed at the restart of 2026-10-04
              "docs/levrule-eval.sha256",               # how rule B is judged at day 30 (pre-registered)
              # paper v4 (2026-10): the run's rules, its verdict method, rule B's v4 population (D12); the same files
              # as runinfo.RULES_FILES' v4 part. Missing or changed = [고칠 것] (hashed before the reset).
              "docs/paper-v4-rules.sha256", "docs/paper-v4-verdict.sha256", "docs/levrule-eval-v4.sha256")

# the paper key must be read-only: any of these on is a problem (Binance apiRestrictions fields)
TRADE_PERMS = {"enableFutures": "선물 거래", "enableSpotAndMarginTrading": "현물·마진 거래", "enableMargin": "마진",
               "enableWithdrawals": "출금", "enableInternalTransfer": "계정 간 이체",
               "permitsUniversalTransfer": "통합 이체", "enableVanillaOptions": "옵션",
               "enablePortfolioMarginTrading": "포트폴리오 마진", "enableFixApiTrade": "FIX 주문"}


def ok(text: str) -> Line:
    return (OK, text)


def fix(text: str) -> Line:
    return (FIX, text)


def note(text: str) -> Line:
    return (NOTE, text)


# ---------------------------------------------------------------- the system, injectable
@dataclass(frozen=True)
class FileInfo:
    mode: int            # permission bits, e.g. 0o640
    owner: str
    group: str
    is_dir: bool = False


def run_cmd(cmd: Sequence[str], env: Optional[dict] = None, timeout: float = 30.0,
            cwd: Optional[str] = None) -> tuple[int, str, str]:
    """(exit code, stdout, stderr); 127 when the program is missing, 124 on a timeout. Never raises.
    Without ``env`` the command gets this process's environment with LC_ALL=C (untranslated output)."""
    if env is None:
        env = {**os.environ, "LC_ALL": "C"}
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:.0f}s"
    except OSError as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"
    return p.returncode, p.stdout or "", p.stderr or ""


def http_fetch(method: str, url: str, headers: Optional[dict] = None, data: Optional[bytes] = None,
               timeout: float = 10.0) -> tuple[int, bytes, dict]:
    """(status, body, headers) for any HTTP answer; network failures raise OSError."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as err:
        return err.code, err.read(), dict(err.headers or {})


def file_info(path: str) -> Optional[FileInfo]:
    """None when the path does not exist; PermissionError when a parent folder is closed to this user."""
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return FileInfo(st.st_mode & 0o7777, owner, group, os.path.isdir(path))


def _disk_free(path: str) -> int:
    while not os.path.exists(path) and path not in ("", "/"):
        path = os.path.dirname(path)
    return shutil.disk_usage(path or "/").free


def _uid(name: str) -> Optional[int]:
    """The user's number; None when there is no such user."""
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        return None


def _proc_uids(pid: int) -> Optional[tuple[int, ...]]:
    """A running process's real, effective, saved and filesystem uid (/proc/<pid>/status); None when unread."""
    try:
        with open(f"/proc/{int(pid)}/status") as fh:
            for row in fh:
                if row.startswith("Uid:"):
                    return tuple(int(x) for x in row.split()[1:5])
    except (OSError, ValueError):
        return None
    return None


def _whoami() -> str:
    try:
        return pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:
        return str(os.geteuid())


@dataclass
class Ctx:
    run: Callable[..., tuple[int, str, str]] = run_cmd
    fetch: Callable[..., tuple[int, bytes, dict]] = http_fetch
    stat: Callable[[str], Optional[FileInfo]] = file_info
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    # CLOCK_MONOTONIC in microseconds, the clock of systemd's ActiveEnterTimestampMonotonic
    mono_us: Callable[[], int] = lambda: int(time.monotonic() * 1_000_000)
    sleep: Callable[[float], None] = time.sleep
    cpu_count: Callable[[], Optional[int]] = os.cpu_count
    disk_free: Callable[[str], int] = _disk_free
    user_id: Callable[[str], Optional[int]] = _uid
    proc_uids: Callable[[int], Optional[tuple]] = _proc_uids
    euid: int = field(default_factory=os.geteuid)
    username: str = field(default_factory=_whoami)
    etc: str = ETC
    app: str = APP
    lib: str = LIB
    backups: str = BACKUPS
    repo: str = REPO
    meminfo: str = "/proc/meminfo"
    venv_python: str = VENV_PY
    user: str = USER

    @property
    def claude_bin(self) -> str:
        return os.path.join(self.lib, ".local", "bin", "claude")


def kst_text(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M")


def kst_day(ms: int) -> str:
    return kst_text(ms)[:10]


# ---------------------------------------------------------------- env files
KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1]
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1]
    return re.sub(r"\\(.)", r"\1", v)


def parse_env(text: str) -> tuple[dict, list[int], list[str]]:
    """KEY=VALUE pairs the way systemd's EnvironmentFile= reads them: blank lines and lines starting with
    # or ; are skipped, whitespace around the key and the value is dropped, one pair of quotes around the
    value is removed ('...' literally, "..." and bare values with backslash escapes), a trailing backslash
    joins the next line, nothing is expanded ($ stays $), and the last of repeated keys wins.
    Returns (values, numbers of unreadable lines, keys given more than once). Unreadable lines are
    reported by number only: they may hold a secret."""
    values: dict = {}
    bad: list[int] = []
    dup: set = set()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        no, s = i + 1, lines[i].strip()
        i += 1
        if not s or s[0] in "#;":
            continue
        while s.endswith("\\") and i < len(lines):
            s = s[:-1] + lines[i].strip()
            i += 1
        key, eq, val = s.partition("=")
        key = key.strip()
        if not eq or not KEY_RE.fullmatch(key):
            bad.append(no)
            continue
        if key in values:
            dup.add(key)
        values[key] = _unquote(val.strip())
    return values, bad, sorted(dup)


@dataclass
class EnvFile:
    name: str
    path: str
    info: Optional[FileInfo] = None
    values: dict = field(default_factory=dict)
    bad_lines: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    error: Optional[str] = None          # could not be read (permission)

    @property
    def exists(self) -> bool:
        return self.info is not None

    def get(self, key: str) -> str:
        return str(self.values.get(key) or "").strip()


def read_env(ctx: Ctx, name: str) -> EnvFile:
    """One /etc/paperbot/<name>.env. executor.env (the order keys, root only) is never read: only its
    permissions are checked."""
    ef = EnvFile(name, os.path.join(ctx.etc, f"{name}.env"))
    try:
        ef.info = ctx.stat(ef.path)
    except OSError as exc:
        ef.error = type(exc).__name__
        return ef
    if ef.info is None or name == "executor":
        return ef
    if name == "debate" and ctx.euid != 0:
        return ef                         # the paid key is readable by its own user and root only: nothing to read here
    try:
        with open(ef.path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        ef.error = type(exc).__name__
        return ef
    ef.values, ef.bad_lines, ef.duplicates = parse_env(text)
    return ef


def read_envs(ctx: Ctx) -> dict[str, EnvFile]:
    return {name: read_env(ctx, name) for name in ENV_SPECS}


def secret_values(envs: dict[str, EnvFile]) -> list[str]:
    """Every value that must never reach the output, longest first (scrubbed from each printed line)."""
    out = set()
    for ef in envs.values():
        for k, v in ef.values.items():
            if k in PUBLIC_KEYS or k.startswith(PUBLIC_PREFIXES) or len(v) < 8:
                continue
            out.add(v)
            if k == "DEADMAN_URL":
                tail = urllib.parse.urlsplit(v).path.strip("/")
                if len(tail) >= 8:
                    out.add(tail)
    return sorted(out, key=len, reverse=True)


def _secret_forms(s: str) -> list[str]:
    """The value as it may appear in an error message: as is, escaped the way repr() shows it (a tab as
    backslash-t), and URL-quoted (as in a request URL)."""
    forms = {s, repr(s)[1:-1], urllib.parse.quote(s), urllib.parse.quote(s, safe="")}
    return [f for f in forms if len(f) >= 8]


def scrub(text: str, secrets: Iterable[str]) -> str:
    forms = sorted({f for s in secrets if s for f in _secret_forms(s)}, key=len, reverse=True)
    for f in forms:
        if f in text:
            text = text.replace(f, "***")
    return text


def _values_line(ef: EnvFile, names: Sequence[str], level: Callable[[str], Line], why: str = "") -> list[Line]:
    if not ef.exists or ef.error:
        return []
    shown = ", ".join(f"{k}={'set' if ef.get(k) else 'empty'}" for k in names)
    empty = [k for k in names if not ef.get(k)]
    if not empty:
        return [ok(f"{ef.name}.env 값: {shown}")]
    return [level(f"{ef.name}.env 값: {shown}" + (f" ({why})" if why else f" → sudo nano {ef.path}"))]


def _telegram_format(ef: EnvFile) -> list[Line]:
    out = []
    tok = ef.get("TELEGRAM_BOT_TOKEN")
    if tok and not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", tok):
        out.append(fix(f"{ef.name}.env의 TELEGRAM_BOT_TOKEN 모양이 텔레그램 토큰(숫자:영문 35자 정도)이 아닙니다: "
                       "BotFather가 준 토큰을 공백 없이 그대로 넣으세요"))
    for k in CHAT_KEYS:
        v = ef.get(k)
        if v and not re.fullmatch(r"-?\d{3,}|@[A-Za-z0-9_]{5,}", v):
            out.append(fix(f"{ef.name}.env의 {k} 모양이 채팅 ID(숫자, 그룹은 -100으로 시작)가 아닙니다"))
    return out


def _binance_key_format(ef: EnvFile) -> list[Line]:
    key, secret = ef.get("BINANCE_API_KEY"), ef.get("BINANCE_API_SECRET")
    out = []
    for name, v in (("BINANCE_API_KEY", key), ("BINANCE_API_SECRET", secret)):
        if v and re.search(r"\s", v):
            out.append(fix(f"{name} 값 안에 공백·줄바꿈이 있습니다: 붙여 넣을 때 끼어든 것을 지우세요"))
    if "BEGIN" in secret and "KEY" in secret:
        out.append(fix("BINANCE_API_SECRET이 개인 키(RSA/Ed25519)입니다: 이 봇은 'System generated'(HMAC) 키만 씁니다. "
                       "바이낸스에서 System generated로 다시 만드세요"))
    elif key and secret and key == secret:
        out.append(fix("BINANCE_API_KEY와 BINANCE_API_SECRET이 같습니다: 키(API Key)와 비밀(Secret Key)을 각각 넣으세요"))
    for name, v in (("BINANCE_API_KEY", key), ("BINANCE_API_SECRET", secret)):
        if v and not re.search(r"\s", v) and "BEGIN" not in v and len(v) != 64:
            out.append(note(f"{name} 길이가 보통 바이낸스 키(64자)와 다릅니다: 잘리지 않았는지 보세요"))
    return out


def _claude_token_format(ef: EnvFile, level: Callable[[str], Line] = fix) -> list[Line]:
    """`claude auth status` only sees that a token is set (no call to the server), so a token damaged
    while copying would pass it: its shape is checked here. The value is never shown."""
    tok = ef.get(CLAUDE_KEY)
    if not tok:
        return []
    where = f"{ef.name}.env의 {CLAUDE_KEY}"
    redo = "docs/server-setup-v3.md 8-2의 setup-token 토큰을 다시 붙여 넣으세요"
    if re.search(r"\s", tok):
        return [level(f"{where} 값 안에 공백·줄바꿈이 끼어 있습니다: {redo}")]
    if tok.startswith("sk-ant-api"):
        return [level(f"{where}에 API 키(sk-ant-api…)가 들어 있습니다: 사용량 과금이 됩니다. {redo}")]
    if not CLAUDE_TOKEN_RE.fullmatch(tok):
        return [level(f"{where} 모양이 구독 토큰(sk-ant-oat01-로 시작, 영문·숫자·-·_만)이 아닙니다: {redo}")]
    tail = len(tok) - len("sk-ant-oat01-")
    if tail < CLAUDE_TOKEN_MIN_TAIL:
        return [level(f"{where}이 너무 짧습니다(sk-ant-oat01- 뒤 {tail}자): 끝까지 복사되지 않은 것 같습니다. {redo}")]
    return []


def _nano_leftovers(ctx: Ctx) -> list[Line]:
    """nano writes NAME.save (NAME.save.1, ...) with the whole unsaved text when its SSH session drops:
    a copy of the keys that nothing else reads or removes."""
    try:
        names = sorted(n for n in os.listdir(ctx.etc) if re.search(r"\.save(\.\d+)?$", n))
    except OSError:
        return []
    if not names:
        return []
    return [fix(f"{ctx.etc}에 nano가 접속이 끊길 때 남긴 파일이 있습니다(키가 들어 있을 수 있음): {', '.join(names)}. "
                f"필요한 값을 원래 파일로 옮긴 뒤 지우세요: sudo rm -f {ctx.etc}/*.save*")]


def check_env_files(ctx: Ctx, envs: dict[str, EnvFile], agents_wanted: bool) -> list[Line]:
    out: list[Line] = []
    try:
        d = ctx.stat(ctx.etc)
    except OSError:
        return [fix(f"{ctx.etc}를 볼 권한이 없습니다: sudo로 실행하세요 (root 또는 sudo -u paperbot)")]
    if d is None:
        return [fix(f"{ctx.etc} 폴더가 없습니다: 설치 스크립트를 먼저 실행하세요 ({INSTALL})")]
    if (d.owner, d.group, d.mode) != ("root", ctx.user, 0o750):
        out.append(fix(f"{ctx.etc} 권한이 {d.owner}:{d.group} {d.mode:o}입니다 (맞는 값 root:{ctx.user} 750): "
                       f"sudo chown root:{ctx.user} {ctx.etc} && sudo chmod 750 {ctx.etc}"))
    for name, ef in envs.items():
        owner, group, mode = ENV_SPECS[name]
        group = ctx.user if group == USER else group
        if ef.error:
            out.append(fix(f"{name}.env를 읽을 수 없습니다({ef.error}): sudo로 실행하세요 (root 또는 sudo -u paperbot)"))
            continue
        if not ef.exists:
            if name == "debate":
                continue                  # check_debate says whether the (optional, paid) debate room is installed
            required = name in ("live", "dash") or (name == "agents" and agents_wanted)
            out.append((fix if required else note)(
                f"{ef.path}가 없습니다" + (f": 설치 스크립트가 만듭니다 ({INSTALL})" if required else
                                           " (실거래 실행기를 쓸 때만 필요)" if name == "executor" else
                                           " (에이전트 방을 켤 때 필요)")))
            continue
        have = f"{ef.info.owner}:{ef.info.group} {ef.info.mode:o}"
        if (ef.info.owner, ef.info.group, ef.info.mode) == (owner, group, mode):
            out.append(ok(f"{name}.env 있음, 권한 {have}"))
        else:
            out.append(fix(f"{name}.env 권한이 {have}입니다 (맞는 값 {owner}:{group} {mode:o}): "
                           f"sudo chown {owner}:{group} {ef.path} && sudo chmod {mode:o} {ef.path}"))
        if ef.bad_lines:
            out.append(fix(f"{name}.env {', '.join(map(str, ef.bad_lines))}번째 줄을 읽을 수 없습니다: "
                           "한 줄에 '이름=값' 하나씩 (앞에 export 없이, # 은 줄 맨 앞에만)"))
        if ef.duplicates:
            out.append(note(f"{name}.env에 같은 이름이 두 번 이상 있습니다: {', '.join(ef.duplicates)} "
                            "(맨 아래 줄 값이 쓰입니다. 하나만 남기세요)"))
        for key, why in FORBIDDEN.get(name, {}).items():
            if ef.get(key):
                out.append(fix(f"{name}.env에 {key} 줄이 들어 있습니다: {why}. 그 줄을 지우세요"))
    out += _nano_leftovers(ctx)
    live, dash, agents = envs["live"], envs["dash"], envs["agents"]
    out += _values_line(live, LIVE_REQUIRED, fix)
    # empty is the documented setting (docs/server-setup-v3.md 4-2): not something to look at
    out += _values_line(live, LIVE_OPTIONAL, ok, "비어 있는 방은 CRITICAL 방으로 갑니다")
    out += _binance_key_format(live) + _telegram_format(live)
    out += _values_line(dash, DASH_REQUIRED, fix)
    out += _values_line(agents, AGENTS_REQUIRED, fix if agents_wanted else note,
                        "" if agents_wanted else "에이전트 방을 켤 때 채웁니다")
    out += _telegram_format(agents) + _claude_token_format(agents, fix if agents_wanted else note)
    out += _telegram_format(envs["debate"])
    return out


# ---------------------------------------------------------------- Binance
class _Rest(BinanceREST):
    def api_restrictions(self) -> dict:
        """The key's permissions (api.binance.com, signed GET; places nothing)."""
        return self._get("/sapi/v1/account/apiRestrictions", signed=True)


def _rest(ctx: Ctx, base: str = FAPI, key: Optional[str] = None, secret: Optional[str] = None) -> _Rest:
    return _Rest(base_url=base, fetch=lambda url, headers: ctx.fetch("GET", url, headers),
                 api_key=key, api_secret=secret, max_retries=1, backoff=1.0, sleep=ctx.sleep, clock_ms=ctx.now_ms)


def binance_hint(text: str) -> str:
    """Korean explanation of a refused signed request (Binance error code in the body)."""
    m = re.search(r'"code"\s*:\s*(-?\d+)', text)
    code = int(m.group(1)) if m else None
    ip = re.search(r"request ip:?\s*([0-9A-Fa-f.:]+[0-9A-Fa-f])", text)
    where = f" 바이낸스가 본 이 서버 주소: {ip.group(1)}" if ip else ""
    if code == -2015:
        return ("키·IP 제한·권한이 맞지 않습니다(-2015). 바이낸스 API 관리에서 IP 제한에 이 서버의 IPv4를 넣었는지, "
                "키를 끝까지 정확히 붙였는지, 선물(USDⓈ-M) 계정이 열려 있는지 보세요." + where)
    if code in (-2014, -2008):
        return f"API 키 모양이 틀렸습니다({code}): 앞뒤 공백 없이 키 전체를 다시 붙여 넣으세요"
    if code == -1022:
        return "서명이 틀렸습니다(-1022): BINANCE_API_SECRET이 그 키의 Secret Key인지 보세요"
    if code == -1021:
        return "서버 시계가 바이낸스와 어긋납니다(-1021): 아래 '시계' 줄을 보세요"
    return text[:240]


def key_permission_lines(perm) -> list[Line]:
    if not isinstance(perm, dict):
        return [note("키 권한 응답이 예상과 다릅니다: 바이낸스 API 관리 화면에서 'Enable Reading'만 켜져 있는지 눈으로 확인하세요")]
    on = [label for k, label in TRADE_PERMS.items() if perm.get(k) is True]
    out = []
    if on:
        out.append(fix(f"이 키에 {', '.join(on)} 권한이 켜져 있습니다. paper 봇 키는 읽기 전용이어야 합니다: "
                       "바이낸스 API 관리에서 'Enable Reading'만 남기고 끄거나, 키를 지우고 새로 만드세요"))
    if perm.get("ipRestrict") is not True:
        out.append(fix("키에 IP 제한이 없습니다: 바이낸스 API 관리 → Restrict access to trusted IPs only → 이 서버의 IPv4"))
    return out or [ok("키 권한: 읽기만 가능 (주문·출금·이체 꺼짐), 서버 IP로 제한됨")]


def check_binance(ctx: Ctx, live: EnvFile) -> list[Line]:
    """Public data (region not blocked, clock), then the read-only key exactly as live3 uses it at start
    (commission rate per coin, leverage brackets), then the key's permission list."""
    out: list[Line] = []
    pub = _rest(ctx)
    try:
        t0 = ctx.now_ms()
        server = pub.server_time()
        skew = server - (t0 + ctx.now_ms()) // 2
        specs = pub.exchange_info(V3_SYMBOLS)
        last = pub.klines(V3_SYMBOLS[0], "1m", limit=2)
    except RegionBlocked:
        return [fix("바이낸스가 이 서버를 막습니다(HTTP 451/403, 지역 차단): Vultr에서 서울·도쿄·싱가포르 지역으로 "
                    "서버를 다시 만드세요")]
    except BinanceError as exc:
        return [fix(f"바이낸스(fapi.binance.com)에 연결하지 못했습니다: {str(exc)[:200]}")]
    halted = [s for s, sp in specs.items() if sp.get("status") != "TRADING"]
    if halted:
        out.append(note(f"바이낸스 연결됨(지역 차단 없음). 거래 중이 아닌 코인: {', '.join(halted)}"))
    else:
        out.append(ok(f"바이낸스 공개 자료 받음: 지역 차단 없음, {len(specs)}개 코인 거래 중 "
                      f"({V3_SYMBOLS[0]} 마지막 가격 {last[-1][4]})"))
    if abs(skew) < 1000:
        out.append(ok(f"바이낸스 서버 시각과 이 서버 시계 차이 {skew} ms"))
    else:
        out.append(fix(f"이 서버 시계가 바이낸스와 {skew} ms 어긋납니다: 1초 넘으면 서명한 요청이 거절될 수 있습니다 "
                       "(아래 '시계' 줄)"))
    key, secret = live.get("BINANCE_API_KEY"), live.get("BINANCE_API_SECRET")
    if not (key and secret):
        out.append(fix("읽기 전용 키가 비어 있어 레버리지 구간·수수료를 확인하지 못했습니다. 봇은 이 키 없이는 시작하지 "
                       f"못합니다 (sudo nano {live.path})"))
        return out
    if re.search(r"\s", key + secret):
        # a key with a space or tab in it cannot go into a request header (and the error would quote it)
        out.append(fix("키 값 안에 공백이 있어 서명한 요청은 보내지 않았습니다: 위 '설정 파일' 줄대로 먼저 고치세요"))
        return out
    signed = _rest(ctx, key=key, secret=secret)
    try:
        rates = [float(signed.commission_rate(s)["takerCommissionRate"]) for s in V3_SYMBOLS]
        brackets = signed.leverage_brackets()
    except BinanceError as exc:
        out.append(fix("읽기 전용 키로 서명한 요청이 거절됐습니다: " + binance_hint(str(exc))))
        return out
    got = {p.get("symbol"): (p.get("brackets") or [None])[0] for p in brackets if isinstance(p, dict)}
    missing = [s for s in V3_SYMBOLS if not got.get(s)]
    if missing:
        out.append(fix(f"레버리지 구간을 받지 못한 코인: {', '.join(missing)}"))
    else:
        out.append(ok(f"읽기 전용 키 작동: {len(V3_SYMBOLS)}개 코인 레버리지 구간·수수료 받음 "
                      f"(taker 수수료 {max(rates):.4%})"))
        top = v3_settings().max_leverage
        low = [f"{s} {got[s].get('initialLeverage')}배" for s in V3_SYMBOLS
               if float(got[s].get("initialLeverage") or 0) < top]
        if low:
            out.append(note(f"거래소 최대 레버리지가 규칙의 최대 {top}배보다 낮은 코인: {', '.join(low)} "
                            "(엔진은 거래소 구간을 따릅니다)"))
    try:
        perm = _rest(ctx, WALLET_API, key, secret).api_restrictions()
    except BinanceError as exc:
        out.append(note(f"키 권한 목록(api.binance.com)을 읽지 못했습니다({binance_hint(str(exc))[:120]}). 위 요청이 "
                        "됐으니 키는 맞습니다: 바이낸스 API 관리에서 'Enable Reading'만 켜져 있고 IP 제한이 있는지 "
                        "눈으로 확인하세요"))
        return out
    return out + key_permission_lines(perm)


# ---------------------------------------------------------------- Telegram
def _telegram(ctx: Ctx, token: str, method: str, params: Optional[dict] = None) -> tuple[bool, object]:
    """(True, result) or (False, short reason). The URL holds the token: it is never part of the reason."""
    url = f"{TELEGRAM}/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode() if params is not None else None
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if data else {}
    try:
        status, body, _ = ctx.fetch("POST" if data else "GET", url, headers, data, 15.0)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        # only the type: the message may quote the URL (e.g. InvalidURL for a token with a tab in it)
        return False, f"api.telegram.org에 연결하지 못함: {type(exc).__name__}"
    try:
        j = json.loads(body or b"null")
    except ValueError:
        j = None
    if status == 200 and isinstance(j, dict) and j.get("ok"):
        return True, j.get("result")
    desc = j.get("description") if isinstance(j, dict) else None
    return False, f"HTTP {status}" + (f" {desc}" if desc else "")


def telegram_hint(reason: str) -> str:
    r = reason.lower()
    if "chat not found" in r:
        return "채팅 ID를 다시 보세요(그룹은 -100으로 시작). 봇이 그 그룹에 들어가 있어야 합니다"
    if "upgraded to a supergroup" in r:
        return "그룹 ID가 바뀌었습니다: 새 ID(-100…)로 고치세요"
    if "blocked by the user" in r or "can't initiate" in r or "not a member" in r or "kicked" in r:
        return "그 사람이 봇에게 /start를 보내거나, 봇을 그룹에 다시 넣으세요"
    if "401" in r or "404" in r or "unauthorized" in r:
        return "봇 토큰이 틀렸습니다: BotFather에서 다시 복사하세요"
    return "잠시 뒤 다시 해 보세요"


def telegram_chats(envs: dict[str, EnvFile], agents_wanted: bool) -> list[tuple[str, str, str, bool]]:
    """(label, token, chat id, silent) for each distinct chat the bot and the agents send to. Silent everywhere unless
    that env file says TELEGRAM_SOUND=1 (then INFO only), like notify.TelegramNotifier."""
    out, seen = [], set()
    files = [envs["live"]] + ([envs["agents"]] if agents_wanted else [])
    for ef in files:
        tok = ef.get("TELEGRAM_BOT_TOKEN")
        crit = ef.get("TELEGRAM_CHAT_CRITICAL")
        if not (tok and crit):
            continue
        for level in ("CRITICAL", "WARN", "INFO", "BACKUP"):
            chat = ef.get(f"TELEGRAM_CHAT_{level}") or crit
            if (tok, chat) in seen:
                continue
            seen.add((tok, chat))
            sound = str(ef.get("TELEGRAM_SOUND") or "").strip() == "1"
            out.append((f"{ef.name}.env {level}", tok, chat, (not sound) or level == "INFO"))
    return out


ROOMS_KO = {"CRITICAL": "긴급 알림방", "WARN": "경고 알림방", "INFO": "조용한 알림방", "BACKUP": "백업방"}


def room_ko(label: str) -> str:
    """'live.env CRITICAL' -> '긴급 알림방', 'agents.env INFO' -> '조용한 알림방 (에이전트)'."""
    env, _, level = label.partition(" ")
    room = ROOMS_KO.get(level, label)
    return room + (" (에이전트)" if env.startswith("agents") else "")


def check_telegram(ctx: Ctx, envs: dict[str, EnvFile], agents_wanted: bool, send_test: bool) -> list[Line]:
    live, agents = envs["live"], envs["agents"]
    token = live.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return [note("텔레그램 확인 건너뜀: live.env에 봇 토큰이 없습니다 (위 '설정 파일' 줄)")]
    good, res = _telegram(ctx, token, "getMe")
    if not good:
        return [fix(f"텔레그램이 봇 토큰을 받지 않습니다({res}): {telegram_hint(str(res))}")]
    name = res.get("username") if isinstance(res, dict) else None
    out = [ok(f"텔레그램 봇 @{name or '?'} 연결됨")]
    ag_token = agents.get("TELEGRAM_BOT_TOKEN")
    refused: set = set()                     # tokens Telegram did not take: their chats are not tried
    if agents_wanted and ag_token and (
            ag_token != token or agents.get("TELEGRAM_CHAT_CRITICAL") != live.get("TELEGRAM_CHAT_CRITICAL")):
        out.append(note("agents.env의 텔레그램 봇·CRITICAL 방이 live.env와 다릅니다 (보통 같은 값을 넣습니다)"))
        if ag_token != token:
            good, res = _telegram(ctx, ag_token, "getMe")
            if not good:
                refused.add(ag_token)
                out.append(fix(f"텔레그램이 agents.env의 봇 토큰을 받지 않습니다({res}): {telegram_hint(str(res))}"))
    chats = [c for c in telegram_chats(envs, agents_wanted) if c[1] not in refused]
    if not send_test:
        # getChat sends nothing: it only says whether this bot is in that chat (a wrong id, a bot that is not
        # in the group, or a group whose id changed to a supergroup's -100… id all fail here)
        seen = 0
        for label, tok, chat, _silent in chats:
            good, res = _telegram(ctx, tok, "getChat", {"chat_id": chat})
            if good:
                seen += 1
            else:
                out.append(fix(f"{label} 방을 찾지 못했습니다({res}): {telegram_hint(str(res))}"))
        if seen:
            out.append(ok(f"텔레그램 방 {seen}곳 확인됨: 봇이 들어가 있음 (메시지는 보내지 않음, --send-test로 시험 메시지)"))
        return out
    for label, tok, chat, silent in chats:
        text = f"🧪 시험 메시지 · {room_ko(label)}\n\n봇 알림이 이 방으로 옵니다\n답장하지 않아도 됩니다"
        good, res = _telegram(ctx, tok, "sendMessage",
                              {"chat_id": chat, "text": text, "disable_notification": json.dumps(silent)})
        if good:
            out.append(ok(f"시험 메시지 보냄: {label} 방" + (" (무음)" if silent else "") + ". 두 분 폰에 왔는지 보세요"))
        else:
            out.append(fix(f"{label} 방으로 보내지 못했습니다({res}): {telegram_hint(str(res))}"))
    return out


# ---------------------------------------------------------------- dead-man check (healthchecks.io)
def check_deadman(ctx: Ctx, live: EnvFile, ping: bool, stage: str) -> list[Line]:
    url = live.get("DEADMAN_URL")
    if not url:
        return []              # the env line already says DEADMAN_URL=empty
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or re.search(r"\s", url):
        return [fix("DEADMAN_URL이 https:// 주소가 아닙니다: healthchecks.io 체크 화면의 Ping URL을 그대로 넣으세요")]
    out = []
    if parts.hostname == "hc-ping.com":
        out.append(ok("DEADMAN_URL 모양 맞음 (hc-ping.com)"))
    else:
        out.append(note(f"DEADMAN_URL이 healthchecks.io(hc-ping.com) 주소가 아닙니다({parts.hostname}): "
                        "다른 감시 서비스라면 괜찮습니다"))
    if not ping:
        # after the start, the bot's own pings are checked from paper3.db (the '데이터' section)
        if stage == "before":
            out.append(note("핑은 보내지 않았습니다(--ping으로 한 번 보냄). 새 체크는 첫 핑 전('new')에는 알림을 보내지 "
                            "않습니다: 봇을 시작한 뒤 healthchecks.io에서 'up'(초록)이 되는지 꼭 보세요"))
        return out
    try:
        status, _, _ = ctx.fetch("GET", url, {"User-Agent": "paperbot-launchcheck"}, None, 10.0)
        why = f"HTTP {status}"
    except (OSError, ValueError, http.client.HTTPException) as exc:      # the message may quote the URL
        status, why = None, type(exc).__name__
    if status == 200:
        out.append(ok("DEADMAN_URL로 핑 보냄: healthchecks.io 화면에서 'up'이 됐는지 보세요"))
        if stage == "before":
            out.append(note("이제 체크가 켜졌습니다: 약 6분(1분 + 유예 5분) 안에 봇을 시작하지 않으면 두 분 폰에 'down' "
                            "알림이 갑니다. 알림이 제대로 오는지 보는 기회이기도 합니다"))
    else:
        out.append(fix(f"DEADMAN_URL로 핑을 보내지 못했습니다({why}): healthchecks.io에서 Ping URL을 다시 복사하세요"))
    return out


# ---------------------------------------------------------------- dashboard
HASH_RE = re.compile(r"pbkdf2\$(\d+)\$([A-Za-z0-9+/]+={0,2})\$([A-Za-z0-9+/]+={0,2})")


def _b64len(s: str) -> int:
    try:
        return len(base64.b64decode(s, validate=True))
    except (binascii.Error, ValueError):
        return -1


def password_hash_ok(h: str) -> bool:
    """The form paperbot.dash.app.hash_password writes: pbkdf2$ROUNDS$SALT$KEY (sha256, 32-byte key)."""
    m = HASH_RE.fullmatch(h)
    return bool(m) and int(m.group(1)) >= 100_000 and _b64len(m.group(2)) >= 8 and _b64len(m.group(3)) == 32


def _host_ip(host: str):
    if host == "localhost":
        return ipaddress.ip_address("127.0.0.1")
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _tailnet(ip) -> bool:
    return ip is not None and any(ip.version == net.version and ip in net for net in TAILNET)


def dash_host_lines(host: str) -> list[Line]:
    if not host:
        return []
    ip = _host_ip(host)
    if ip is None:
        return [fix(f"DASH_HOST({host})는 IP 주소가 아닙니다: Tailscale 주소(`tailscale ip -4`의 100.x.y.z)나 "
                    "127.0.0.1을 넣으세요")]
    if ip.is_loopback:
        return [ok(f"DASH_HOST={host}: 인터넷에 열리지 않음"),
                note("이 주소면 대시보드는 SSH 터널로만 봅니다. 폰에서 보려면 Tailscale 주소(100.x.y.z)를 넣으세요")]
    if ip.is_unspecified:
        return [fix(f"DASH_HOST({host})는 모든 주소라서 대시보드가 인터넷 쪽에도 열립니다: Tailscale 주소(100.x.y.z)를 "
                    "넣으세요")]
    if _tailnet(ip):
        return [ok(f"DASH_HOST={host}: Tailscale 주소 (인터넷에 열리지 않음)")]
    return [fix(f"DASH_HOST({host})는 Tailscale 주소(100.64.0.0/10)도 127.0.0.1도 아닙니다: 대시보드는 Tailscale이나 "
                "SSH 터널로만 엽니다")]


def dash_listen_lines(ctx: Ctx, host: str) -> list[Line]:
    rc, text, _ = ctx.run(["ss", "-H", "-l", "-t", "-n"])
    if rc != 0:
        return [note("열린 포트를 보지 못했습니다(ss): systemctl status paperbot-dash 로 확인하세요")]
    local = []
    for row in text.splitlines():
        cols = row.split()
        if len(cols) >= 5 and cols[3].rsplit(":", 1)[-1] == "8080":
            local.append(cols[3].rsplit(":", 1)[0].strip("[]").split("%")[0])
    if not local:
        return [fix("대시보드가 8080 포트에서 기다리고 있지 않습니다: journalctl -u paperbot-dash -n 30")]
    out = []
    if any(a in ("0.0.0.0", "*", "::") for a in local):
        out.append(fix("8080 포트가 모든 주소에 열려 있습니다: DASH_HOST를 Tailscale 주소로 고치고 "
                       "sudo systemctl restart paperbot-dash"))
    want = str(_host_ip(host) or host)
    if want not in local:
        out.append(fix(f"대시보드가 DASH_HOST({host})가 아닌 {', '.join(local)}에서 기다립니다: "
                       "sudo systemctl restart paperbot-dash"))
        return out
    netloc = f"[{want}]" if ":" in want else want
    try:
        status, _, _ = ctx.fetch("GET", f"http://{netloc}:8080/", {}, None, 5.0)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return out + [fix(f"대시보드 주소에 접속하지 못했습니다({type(exc).__name__}): journalctl -u paperbot-dash -n 30")]
    if status >= 500:
        return out + [fix(f"대시보드가 오류로 답합니다(HTTP {status}): journalctl -u paperbot-dash -n 30")]
    return out + [ok(f"대시보드 응답함: http://{netloc}:8080 (폰의 Tailscale 앱이 켜져 있어야 열립니다)")]


def check_dash(ctx: Ctx, dash: EnvFile, stage: str) -> list[Line]:
    out: list[Line] = []
    h = dash.get("DASH_PASSWORD_HASH")
    if h:
        if password_hash_ok(h):
            out.append(ok(f"대시보드 비밀번호 해시 모양 맞음 (pbkdf2, {int(HASH_RE.fullmatch(h).group(1)):,}회)"))
        else:
            out.append(fix("DASH_PASSWORD_HASH가 'python -m paperbot.dash hash' 결과 모양(pbkdf2$숫자$…$…)이 아닙니다: "
                           "결과 한 줄 전체를 작은따옴표로 감싸 넣으세요 (DASH_PASSWORD_HASH='pbkdf2$…')"))
    s = dash.get("DASH_SECRET")
    if s:
        out.append(ok("DASH_SECRET 길이 충분 (32자 이상)") if len(s) >= 32 else
                   fix("DASH_SECRET이 32자보다 짧아 대시보드가 시작하지 않습니다: `openssl rand -hex 32` 결과를 넣으세요"))
    host_lines = dash_host_lines(dash.get("DASH_HOST"))
    out += host_lines
    if dash.get("DASH_SECURE_COOKIE"):
        out.append(fix("DASH_SECURE_COOKIE가 켜져 있습니다: Tailscale(http)에서는 로그인이 막힙니다. 그 줄을 지우세요"))
    if stage == "after" and dash.get("DASH_HOST") and FIX not in (s for s, _ in host_lines):
        out += dash_listen_lines(ctx, dash.get("DASH_HOST"))
    return out


# ---------------------------------------------------------------- Tailscale and firewall
def check_tailscale(ctx: Ctx, dash: EnvFile) -> list[Line]:
    host = dash.get("DASH_HOST")
    ip = _host_ip(host) if host else None
    loop = ip is None or ip.is_loopback      # no Tailscale address in use (SSH tunnel)
    level = note if loop else fix
    out: list[Line] = []
    rc, text, _ = ctx.run(["tailscale", "status", "--json"])
    try:
        st = json.loads(text) if text.strip() else None
    except ValueError:
        st = None
    if rc == 127:
        out.append(level("Tailscale이 설치되지 않았습니다" + (": 대시보드는 SSH 터널로만 봅니다" if loop else
                                                         ": docs/server-setup-v3.md 7번(Tailscale)대로 설치하세요")))
    elif not isinstance(st, dict):
        out.append(level("Tailscale 상태를 읽지 못했습니다: sudo systemctl enable --now tailscaled && sudo tailscale up"))
    else:
        state = st.get("BackendState")
        me = st.get("Self") or {}
        ips = [str(a) for a in me.get("TailscaleIPs") or []]
        if state == "Running":
            out.append(ok(f"Tailscale 연결됨: 이 서버 {', '.join(a for a in ips if '.' in a) or '?'}"))
            if _tailnet(ip) and str(ip) not in ips:
                out.append(fix(f"DASH_HOST({host})가 이 서버의 Tailscale 주소({', '.join(ips)})와 다릅니다: "
                               "DASH_HOST를 고친 뒤 sudo systemctl restart paperbot-dash"))
            exp = me.get("KeyExpiry")
            if exp:
                out.append(note(f"Tailscale 키가 {str(exp)[:10]}에 만료됩니다(만료되면 대시보드가 끊김): Tailscale 관리 "
                                "화면 → Machines → 이 서버 → ⋯ → Disable key expiry"))
        else:
            out.append(level(f"Tailscale이 연결되지 않았습니다(상태 {state}): sudo tailscale up 후 나온 링크를 "
                             "폰에서 승인하세요"))
    if ctx.euid != 0:
        return out + [note("방화벽(ufw) 규칙은 sudo(root)로 실행할 때만 확인합니다")]
    return out + firewall_lines(ctx, loop)


def _ufw_rules(text: str) -> list[tuple[str, str]]:
    """(the 'To' part, the whole row) of each rule that lets traffic in (ALLOW or LIMIT), from
    `ufw status verbose`."""
    rules = []
    for row in text.splitlines():
        # the 'To' column is padded, but a long one ("Anywhere (v6) on tailscale0") leaves a single space
        m = re.match(r"(.+?)\s+(?:ALLOW|LIMIT)(?:\s+(IN|OUT|FWD))?\s+\S", row)
        if m and m.group(2) in (None, "IN"):
            rules.append((m.group(1).strip(), " ".join(row.split())))
    return rules


def _ssh_rule(to: str) -> bool:
    return bool(re.match(r"(22(/tcp)?|OpenSSH)(\s|\(|$)", to)) or "(OpenSSH" in to


def firewall_lines(ctx: Ctx, loop: bool) -> list[Line]:
    """`ufw status verbose`: on, incoming denied by default, and nothing let in but SSH and (with a
    Tailscale DASH_HOST) the tailscale0 interface."""
    rc, text, _ = ctx.run(["ufw", "status", "verbose"])
    if rc != 0:
        return [fix(f"방화벽(ufw) 상태를 읽지 못했습니다: 설치 스크립트를 다시 실행하세요 ({INSTALL})")]
    if not re.search(r"^Status:\s*active", text, re.M):
        return [fix("방화벽(ufw)이 꺼져 있습니다: sudo ufw enable (설치 스크립트는 SSH만 열고 켭니다)")]
    fw: list[Line] = []
    if not re.search(r"^Default:\s*deny \(incoming\)", text, re.M):
        fw.append(fix("방화벽 기본값이 '들어오는 연결 막기'가 아닙니다: sudo ufw default deny incoming"))
    rows = _ufw_rules(text)
    rules = [to for to, _ in rows]
    if any(re.match(r"8080(/tcp)?\b", r) and "tailscale0" not in r for r in rules):
        fw.append(fix("방화벽에서 8080 포트가 인터넷에 열려 있습니다(대시보드는 Tailscale로만 봅니다): "
                      "`sudo ufw status numbered`로 8080 줄의 번호를 보고 `sudo ufw delete <번호>` "
                      "(줄마다 한 번, 번호가 바뀌므로 지울 때마다 다시 확인)"))
    if not loop and not any("tailscale0" in r for r in rules):
        fw.append(fix("방화벽에 Tailscale 허용 규칙이 없습니다: sudo ufw allow in on tailscale0"))
    other = [row for to, row in rows if not _ssh_rule(to) and "tailscale0" not in to and not to.startswith("8080")]
    if other:
        fw.append(note(f"방화벽이 SSH·Tailscale 말고도 들여보내는 규칙: {' / '.join(other)}. 직접 연 것이 아니면 "
                       "`sudo ufw status numbered` 후 `sudo ufw delete <번호>`"))
    if any(s == FIX for s, _ in fw):
        return fw
    return [ok("방화벽 켜짐: 들어오는 연결은 기본으로 막고 SSH" + ("" if loop else "와 Tailscale") + "만 허용")] + fw


# ---------------------------------------------------------------- server size, clock
def mem_total_gib(path: str) -> Optional[float]:
    try:
        with open(path) as fh:
            for row in fh:
                if row.startswith("MemTotal:"):
                    return int(row.split()[1]) / 1024 / 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def live3_procs(states: Optional[dict]) -> Optional[int]:
    """--procs of the installed paperbot-live3 (unit file plus drop-ins, from systemctl show ExecStart)."""
    m = re.search(r"--procs[ =](\d+)", ((states or {}).get("paperbot-live3.service") or {}).get("ExecStart", ""))
    return int(m.group(1)) if m else None


def check_resources(ctx: Ctx, states: Optional[dict]) -> list[Line]:
    out: list[Line] = []
    procs = live3_procs(states) or 4
    cpu = ctx.cpu_count() or 0
    if cpu >= max(4, procs):
        out.append(ok(f"CPU {cpu}개 (권장 4개, 봇은 --procs {procs})"))
    elif cpu >= procs:
        out.append(note(f"CPU {cpu}개: 권장 4 vCPU보다 적습니다. 봇(--procs {procs})은 돌지만 신호 계산이 느려집니다"))
    else:
        out.append(fix(f"CPU {cpu}개인데 봇은 --procs {procs}로 설정돼 있습니다: Vultr에서 4 vCPU로 올리거나 "
                       f"`sudo systemctl edit paperbot-live3`로 --procs {cpu}로 바꾸세요"))
    mem = mem_total_gib(ctx.meminfo)
    if mem is None:
        out.append(note("메모리 크기를 읽지 못했습니다"))
    elif mem >= 7.0:            # an 8 GB plan shows about 7.7 GiB
        out.append(ok(f"메모리 {mem:.1f} GB (권장 8 GB)"))
    elif mem >= 3.5:
        out.append(note(f"메모리 {mem:.1f} GB: 권장 8 GB보다 적습니다. 봇과 에이전트 5년 시험이 함께 돌면 모자랄 수 있습니다"))
    else:
        out.append(fix(f"메모리 {mem:.1f} GB: 너무 적습니다. Vultr에서 8 GB로 올리세요"))
    free = ctx.disk_free(ctx.lib) / 1e9
    if free >= 20:
        out.append(ok(f"남은 디스크 {free:.0f} GB"))
    elif free >= 5:
        out.append(note(f"남은 디스크 {free:.1f} GB: 5년 시험 자료 1.5 GB와 14일치 백업을 생각하면 빠듯합니다"))
    else:
        out.append(fix(f"남은 디스크 {free:.1f} GB: 5 GB도 안 됩니다. 디스크를 늘리거나 비우세요"))
    return out


def check_clock(ctx: Ctx) -> list[Line]:
    rc, text, _ = ctx.run(["chronyc", "-n", "tracking"])
    if rc == 127:
        return [fix(f"chrony(시계 맞춤)가 없습니다: 설치 스크립트를 다시 실행하세요 ({INSTALL})")]
    if rc != 0:
        return [fix("chrony(시계 맞춤)가 답하지 않습니다: sudo systemctl enable --now chrony")]
    leap = re.search(r"^Leap status\s*:\s*(.+)$", text, re.M)
    off = re.search(r"^System time\s*:\s*([0-9.]+) seconds (fast|slow)", text, re.M)
    leap_s = leap.group(1).strip() if leap else "?"
    if leap_s == "Normal" and off and float(off.group(1)) < 0.5:
        return [ok(f"시계 동기화(chrony) 정상: 오차 {float(off.group(1)):.3f}초")]
    return [fix(f"시계가 동기화되지 않았습니다(chrony: {leap_s}): sudo systemctl restart chrony 후 몇 분 뒤 다시 확인")]


# ---------------------------------------------------------------- systemd units
def unit_states(ctx: Ctx, units: Sequence[str] = ALL_UNITS) -> Optional[dict]:
    """{unit: {property: value}} from one `systemctl show`; None when systemctl cannot be used."""
    rc, text, _ = ctx.run(["systemctl", "show", f"--property={UNIT_PROPS}", *units])
    if rc == 127 or not text.strip():
        return None
    states = {}
    for block in re.split(r"\n\s*\n", text.strip()):
        d = {}
        for row in block.splitlines():
            k, _, v = row.partition("=")
            d[k.strip()] = v.strip()
        if d.get("Id"):
            states[d["Id"]] = d
    return states


def _short(unit: str) -> str:
    return unit[:-len(".service")] if unit.endswith(".service") else unit


def _enabled(d: dict) -> bool:
    return d.get("UnitFileState") in ("enabled", "enabled-runtime")


def _active(d: dict) -> bool:
    return d.get("ActiveState") in ("active", "activating", "reloading")


def _run_age_s(d: dict, mono_us: Optional[int]) -> Optional[float]:
    """Seconds since the unit last became active (an automatic restart resets it); None when unknown."""
    raw = d.get("ActiveEnterTimestampMonotonic") or ""
    if mono_us is None or not raw.isdigit() or int(raw) <= 0:
        return None
    return max(0.0, (mono_us - int(raw)) / 1e6)


def _age_text(s: float) -> str:
    return f"{s / 86400:.0f}일" if s >= 2 * 86400 else f"{s / 3600:.0f}시간" if s >= 7200 else f"{s / 60:.0f}분"


def service_line(unit: str, d: dict, mono_us: Optional[int] = None) -> Line:
    """systemd's NRestarts counts every automatic restart since the last manual start, so a service that
    restarted a few times weeks ago (a Binance outage, a reboot before Tailscale was up) and has run
    fine since is a [참고]; it is [고칠 것] while it is down or its current run is younger than ten
    minutes (still crashing)."""
    name = _short(unit)
    restarts = int(d.get("NRestarts") or 0) if (d.get("NRestarts") or "0").isdigit() else 0
    running = (d.get("ActiveState"), d.get("SubState")) == ("active", "running")
    age = _run_age_s(d, mono_us) if running else None
    crashing = restarts > MAX_RESTARTS and (not running or age is None or age < RESTART_RECENT_S)
    problems = []
    if not _enabled(d):
        problems.append(f"부팅 때 자동으로 켜지지 않음 (sudo systemctl enable {name})")
    if not running:
        problems.append(f"실행 중이 아님({d.get('ActiveState')}/{d.get('SubState')})")
    if crashing:
        problems.append(f"{restarts}번 다시 시작함(계속 죽는 중)")
    if problems:
        logs = f". 원인: journalctl -u {name} -n 50" if not running or crashing else ""
        return fix(f"{name}: " + "; ".join(problems) + logs)
    if restarts > MAX_RESTARTS:
        return note(f"{name}: 켜짐·실행 중, 지금은 {_age_text(age)}째 정상. 그동안 자동 재시작 {restarts}번 "
                    f"(이유 보기: journalctl -u {name} -n 100 --no-pager)")
    return ok(f"{name}: 켜짐·실행 중 (자동 재시작 {restarts}번)")


def timer_line(unit: str, d: dict, required: bool) -> Line:
    if _enabled(d) and d.get("ActiveState") == "active":
        nxt = d.get("NextElapseUSecRealtime") or ""
        return ok(f"{unit}: 켜짐" + (f", 다음 실행 {nxt}" if nxt and nxt != "n/a" else ""))
    return (fix if required else note)(f"{unit}: 꺼져 있음 → sudo systemctl enable --now {unit}")


def check_units(states: Optional[dict], stage: str, agents_wanted: bool,
                mono_us: Optional[int] = None) -> list[Line]:
    if states is None:
        return [fix("systemctl을 쓸 수 없습니다: 이 점검은 설치한 서버(Ubuntu 24.04)에서 돌립니다")]
    st = lambda u: states.get(u) or {}          # noqa: E731
    out: list[Line] = []
    missing = [u for u in INSTALLED if st(u).get("LoadState") != "loaded"]
    out.append(fix(f"설치되지 않은 서비스: {', '.join(missing)} → {INSTALL}") if missing else
               ok(f"서비스 파일 {len(INSTALLED)}개 설치됨"))
    down = [_short(u) for u in SYSTEM if st(u).get("ActiveState") != "active"]
    out.append(fix(f"꺼져 있음: {', '.join(down)} → sudo systemctl enable --now {' '.join(down)}") if down else
               ok("fail2ban(로그인 공격 차단)·chrony(시계) 켜짐"))
    if st(AUTO_UPDATES).get("ActiveState") != "active":
        out.append(note("자동 보안 업데이트(unattended-upgrades)가 꺼져 있습니다: "
                        "sudo systemctl enable --now unattended-upgrades"))
    legacy = [u for u in LEGACY if _enabled(st(u)) or _active(st(u))]
    if legacy:
        out.append(fix(f"옛 버전(v1/v2) 서비스가 켜져 있습니다: {', '.join(legacy)} → "
                       f"sudo systemctl disable --now {' '.join(legacy)}"))
    ex = st(EXECUTOR)
    if _enabled(ex) or _active(ex):
        if stage == "before":
            out.append(fix("주문 실행기(paperbot-executor)가 켜져 있습니다: paper 시작에는 필요 없고 테스트넷 연습 전까지 "
                           "꺼 둡니다 → sudo systemctl disable --now paperbot-executor"))
        else:
            out.append(note("주문 실행기(paperbot-executor)가 켜져 있습니다: docs/live-safety.md 절차로 켠 것이 아니면 "
                            "sudo systemctl disable --now paperbot-executor"))
    else:
        out.append(ok("주문 실행기(paperbot-executor) 꺼져 있음 (paper만 돌림)"))
    if stage == "before":
        on = [_short(u) for u in SERVICES + TIMERS if _enabled(st(u)) or _active(st(u))]
        out.append(note(f"이미 켜져 있음: {', '.join(on)}. 시작한 뒤의 점검은 --stage after") if on else
                   ok("봇·대시보드·기록기·타이머는 아직 꺼져 있음 (시작 전 상태 그대로)"))
    else:
        out += [service_line(u, st(u), mono_us) for u in SERVICES]
        out += [timer_line(u, st(u), True) for u in TIMERS]
        for job in ("paperbot-daily3.service", "paperbot-backup.service"):
            if st(job).get("Result") not in (None, "", "success"):
                out.append(fix(f"{_short(job)}의 지난 실행이 실패했습니다({st(job).get('Result')}): "
                               f"journalctl -u {_short(job)} -n 50"))
        for u in EXTRA_SERVICES:
            if st(u).get("LoadState") == "loaded":
                out.append(service_line(u, st(u), mono_us))
        for u in EXTRA_TIMERS:
            if st(u).get("LoadState") == "loaded":
                out.append(timer_line(u, st(u), True))
                job = u.replace(".timer", ".service")
                if st(job).get("Result") not in (None, "", "success"):
                    out.append(fix(f"{_short(job)}의 지난 실행이 실패했습니다({st(job).get('Result')}): "
                                   f"journalctl -u {_short(job)} -n 50"))
        for u in OPTIONAL_TIMERS:                       # [참고] only: off is a choice, a failed run is worth a look
            if st(u).get("LoadState") == "loaded":
                out.append(timer_line(u, st(u), False))
                job = u.replace(".timer", ".service")
                if st(job).get("Result") not in (None, "", "success"):
                    out.append(note(f"{_short(job)}의 지난 실행이 실패했습니다({st(job).get('Result')}): "
                                    f"journalctl -u {_short(job)} -n 50"))
        later = [u for u in AFTER_CHECK_TIMERS if st(u).get("LoadState") == "loaded"
                 and not (_enabled(st(u)) and st(u).get("ActiveState") == "active")]
        if later:                                       # the v4 reset leaves them off on purpose: never a FIX
            out.append(note(f"리셋 뒤 꺼 둔 타이머 {len(later)}개: {', '.join(_short(u) for u in later)}. 이 점검에 "
                            f"[고칠 것]이 없으면 켜기: sudo systemctl enable --now {' '.join(AFTER_CHECK_TIMERS)} "
                            "(docs/server-setup-v4.md 5단계)"))
        cp = st("paperbot-checkpoint.service")
        if cp.get("Result") not in (None, "", "success"):
            out.append(note("paperbot-checkpoint의 지난 실행이 실패했습니다: 봇이 paper3.db를 만들기 전 한 번은 괜찮습니다. "
                            "계속되면 journalctl -u paperbot-checkpoint -n 50"))
    off = [u for u in AGENT_TIMERS if not (_enabled(st(u)) and st(u).get("ActiveState") == "active")]
    if stage == "after" and agents_wanted:
        for u in AGENT_TIMERS:
            if u == "paperbot-agents.timer" and u in off:
                # the v4 reset's --agents-off (owners' D15) keeps it off on purpose: a [참고] saying what stops
                out.append(note(f"{AGENTS_OFF_KO} (paperbot-agents.timer 꺼짐: 리셋을 --agents-off로 했거나 아직 "
                                "켜지 않음). 개발자가 '에이전트 v4 준비 끝'이라고 하면 "
                                "sudo systemctl enable --now paperbot-agents.timer"))
            else:
                out.append(timer_line(u, st(u), True))
    elif off and stage == "before" and agents_wanted:
        # the expected state before the start: the verdict's start command turns them on with the rest
        out.append(ok(f"에이전트 방 타이머는 아직 꺼져 있음: {', '.join(_short(u) for u in off)} (시작 명령이 함께 켭니다)"))
    elif off:
        out.append(note(f"에이전트 방 타이머 꺼져 있음: {', '.join(off)} (Claude 로그인·5년 자료·드라이런을 마친 뒤 "
                        "sudo systemctl enable --now paperbot-agents.timer paperbot-labmonthly.timer)"
                        + (f". {AGENTS_OFF_KO}" if "paperbot-agents.timer" in off else "")))
    else:
        out.append(ok("에이전트 방 타이머 켜짐 (paperbot-agents, paperbot-labmonthly)"))
    ag = st("paperbot-agents.service")
    if agents_wanted and ag.get("Result") not in (None, "", "success"):
        if ag.get("ExecMainStatus") == "2":
            out.append(fix("지난 에이전트 회의가 Claude 로그인 확인에서 멈췄습니다 (아래 'Claude Code 로그인' 줄)"))
        else:
            out.append(note(f"지난 에이전트 회의가 실패했습니다({ag.get('Result')}): systemctl status paperbot-agents"))
    return out


# ---------------------------------------------------------------- code, data folders, paper3.db
def installed_version(ctx: Ctx) -> Optional[dict]:
    try:
        with open(os.path.join(ctx.app, "VERSION.json")) as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def rules_lines(app: str) -> list[Line]:
    bad, n = [], 0
    for rel in RULES_SUMS:
        try:
            with open(os.path.join(app, rel)) as fh:
                rows = fh.read().splitlines()
        except OSError:
            bad.append(rel)
            continue
        for row in rows:
            parts = row.split()
            if len(parts) != 2:
                continue
            n += 1
            want, path = parts[0], parts[1].lstrip("*")
            try:
                with open(os.path.join(app, path), "rb") as fh:
                    got = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                got = None
            if got != want:
                bad.append(path)
    if bad or not n:
        return [fix(f"규칙 문서가 확정본과 다릅니다: {', '.join(bad) or '해시 파일 없음'}. 규칙은 두 분 합의 없이 바꾸지 "
                    "않습니다: 개발자에게 알리세요")]
    return [ok(f"규칙 문서 {n}개가 확정본과 같음 (sha256)")]


def check_code(ctx: Ctx) -> list[Line]:
    out: list[Line] = []
    ver = installed_version(ctx)
    commit = str((ver or {}).get("commit") or "")
    if ver is None:
        out.append(fix(f"{ctx.app}/VERSION.json이 없습니다: 코드가 설치 스크립트로 설치되지 않았습니다 ({INSTALL})"))
    elif ver.get("dirty") is True:
        out.append(fix(f"설치된 코드(커밋 {commit[:10]})에 커밋 안 된 수정이 섞여 있습니다(ALLOW_DIRTY): "
                       "git status로 수정을 정리한 뒤 다시 설치하세요"))
    elif not commit or commit == "unknown" or ver.get("dirty") is not False:
        out.append(fix(f"설치된 코드의 버전을 모릅니다: git clone한 폴더에서 다시 설치하세요 ({INSTALL})"))
    else:
        tag = f", 태그 {ver['tag']}" if ver.get("tag") else ""
        out.append(ok(f"설치된 코드: 커밋 {commit[:10]}{tag}, 수정 없음 (설치 {ver.get('installed_at', '?')})"))
    out += rules_lines(ctx.app)
    try:
        cloned = ctx.stat(os.path.join(ctx.repo, ".git")) is not None
    except OSError:
        cloned = False                         # /root is closed to user paperbot
    if cloned and commit:
        rc, head, _ = ctx.run(["git", "-C", ctx.repo, "rev-parse", "HEAD"])
        head = head.strip()
        if rc == 0 and head and head != commit:
            out.append(note(f"{ctx.repo}의 코드({head[:10]})가 설치된 코드({commit[:10]})와 다릅니다: git pull 뒤 "
                            "sudo bash deploy/install.sh 를 다시 실행했나요?"))
    rc, _, err = ctx.run([ctx.venv_python, "-c", "import paperbot"], None, 30.0, "/")
    if rc != 0 and "No module named" in err:
        out.append(note("`python -m paperbot…` 명령은 다른 폴더에서는 안 됩니다(No module named 'paperbot'): "
                        "문서의 명령 앞에 `cd /opt/crypto-bot-research &&`를 붙이세요"))
    return out


def check_data_dir(ctx: Ctx) -> list[Line]:
    """/var/lib/paperbot and the backups belong to paperbot, and /var/lib/paperbot/exec (the order executor's
    databases) to the executor's own user; a file of another owner in them (a command run with sudo but without
    -u paperbot / -u paperbot-exec) stops the service that must write it."""
    out: list[Line] = []
    for path in (ctx.lib, ctx.backups):
        info = ctx.stat(path)
        if info is None:
            out.append(fix(f"{path} 폴더가 없습니다: {INSTALL}"))
        elif (info.owner, info.group) != (ctx.user, ctx.user):
            out.append(fix(f"{path} 주인이 {info.owner}:{info.group}입니다: sudo chown {ctx.user}:{ctx.user} {path}"))
    exec_dir = os.path.join(ctx.lib, "exec")
    # the 24-hour debate room's folder belongs to its own user (deploy/install.sh makes it paperbot-debate:paperbot
    # 2750, check_debate wants exactly that): expected here too, and kept out of the chown -R remedy
    debate_dir = os.path.join(ctx.lib, "debate")
    foreign = []
    for d in (ctx.lib, exec_dir, os.path.join(ctx.lib, "lab")):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            want = (DEBATE_USER if p == debate_dir else
                    EXEC_USER if p == exec_dir or d == exec_dir else ctx.user)
            info = ctx.stat(p)
            if info is not None and info.owner != want:
                foreign.append(p)
    if foreign:
        more = f" 외 {len(foreign) - 5}개" if len(foreign) > 5 else ""
        back = (f" && sudo chown -R {DEBATE_DIR_MODE[0]}:{DEBATE_DIR_MODE[1]} {debate_dir}"
                if ctx.stat(debate_dir) is not None else "")
        out.append(fix(f"주인이 맞지 않는 파일이 있어 서비스가 쓰지 못합니다: {', '.join(foreign[:5])}{more} → "
                       f"sudo chown -R {ctx.user}:{ctx.user} {ctx.lib} && "
                       f"sudo chown -R {EXEC_USER}:{ctx.user} {exec_dir}{back} (그 사용자가 없으면 먼저 {INSTALL})"))
    elif not out:
        out.append(ok(f"데이터 폴더 주인 {ctx.user}, 주문 실행기 폴더 {EXEC_USER} (다른 사용자 소유 파일 없음)"))
    # the DeepSeek nightly recompute check's folder (install.sh and the reset make it, paperbot 750); its service can
    # make it itself, so a missing folder is a [참고] (a foreign owner is caught above)
    if ctx.stat(ctx.lib) is not None and ctx.stat(os.path.join(ctx.lib, "dscheck")) is None:
        out.append(note(f"{os.path.join(ctx.lib, 'dscheck')} 폴더가 없습니다(딥시크 밤 재계산 점검): "
                        f"sudo install -d -o {ctx.user} -g {ctx.user} -m 750 {os.path.join(ctx.lib, 'dscheck')}"))
    return out


def check_executor_user(ctx: Ctx, states: Optional[dict]) -> list[Line]:
    """The order executor (and the testnet drill, deploy/paperbot-exec.sh) runs as its own user paperbot-exec, never
    as paperbot: the agent rooms and the dashboard run as paperbot, and a process can read the environment of any
    process of its own user (/proc/<pid>/environ: the order keys systemd passes in). Checked once the executor unit
    is installed: the user exists and is neither paperbot nor root, the unit runs as it, its folder is its own (group
    paperbot may read, not write: the nightly backup), and paper3.db is readable by group paperbot (it follows it)."""
    ex = (states or {}).get(EXECUTOR) or {}
    if ex.get("LoadState") != "loaded":
        return []
    uid, base = ctx.user_id(EXEC_USER), ctx.user_id(ctx.user)
    if uid is None:
        return [fix(f"주문 실행기 전용 사용자 {EXEC_USER}가 없습니다: 설치 스크립트가 만듭니다 ({INSTALL})")]
    out: list[Line] = []
    if uid == 0 or uid == base:
        out.append(fix(f"{EXEC_USER}가 {'root' if uid == 0 else ctx.user}와 같은 사용자 번호(uid {uid})입니다: 다른 서비스가 "
                       f"실행기의 키를 읽을 수 있습니다 → sudo userdel {EXEC_USER} 뒤 {INSTALL}"))
    run_as = ex.get("User") or "root"
    if run_as != EXEC_USER:
        out.append(fix(f"paperbot-executor 서비스가 {run_as} 사용자로 돕니다(맞는 값 {EXEC_USER}): 에이전트·대시보드와 같은 "
                       f"사용자면 실행기의 키(/proc/…/environ)를 읽을 수 있습니다 → {INSTALL}"))
    # the unit's User= is the installed file (after daemon-reload); a process started before install.sh keeps the
    # user it was started as until it is restarted: look at the running process itself
    pid = ex.get("MainPID") or ""
    if _active(ex) and pid.isdigit() and int(pid) > 0 and run_as == EXEC_USER:
        ids = ctx.proc_uids(int(pid))
        if ids and any(u != uid for u in ids):
            other = next(u for u in ids if u != uid)
            who = ctx.user if other == base else "root" if other == 0 else f"uid {other}"
            out.append(fix(f"지금 돌고 있는 주문 실행기(pid {pid})는 아직 {who} 사용자입니다(설치 전에 켜진 예전 프로세스): "
                           f"그동안 {ctx.user} 사용자의 프로세스가 실행기의 키를 읽을 수 있습니다 → "
                           "sudo systemctl restart paperbot-executor"))
    d = os.path.join(ctx.lib, "exec")
    info = ctx.stat(d)
    if info is None:
        out.append(fix(f"{d} 폴더가 없습니다: {INSTALL}"))
    elif (info.owner, info.group, info.mode) != (EXEC_USER, ctx.user, 0o750):
        out.append(fix(f"{d} 권한이 {info.owner}:{info.group} {info.mode:o}입니다(맞는 값 {EXEC_USER}:{ctx.user} 750) → "
                       f"{INSTALL}"))
    paper = os.path.join(ctx.lib, "paper3.db")
    pi = ctx.stat(paper)
    if pi is not None and (pi.group != ctx.user or not pi.mode & 0o040):
        out.append(fix(f"주문 실행기({EXEC_USER}, 그룹 {ctx.user})가 {paper}를 읽을 수 없습니다({pi.owner}:{pi.group} "
                       f"{pi.mode:o}) → sudo chgrp {ctx.user} {paper} && sudo chmod g+r {paper}"))
    if not out:
        out.append(ok(f"주문 실행기는 전용 사용자 {EXEC_USER}로 돕니다(에이전트·대시보드의 {ctx.user}와 달라 키를 읽을 수 "
                      "없음)"))
    return out


def open_ro(path: str) -> sqlite3.Connection:
    """A read-only connection that leaves nothing behind. paper3.db and liq.db are WAL databases: a
    read-only open of one whose writer is stopped (no -wal/-shm next to it) would create those two files
    (root-owned when run as root), so it is then opened ``immutable`` (nothing can change it meanwhile).
    While the writer runs, its -wal/-shm exist and a plain read-only open uses them."""
    immutable = not (os.path.exists(path + "-wal") or os.path.exists(path + "-shm"))
    uri = f"file:{urllib.parse.quote(path)}?mode=ro" + ("&immutable=1" if immutable else "")
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.execute("PRAGMA query_only = 1")
    return conn


HELD_RE = re.compile(r"^\[(?P<aid>[^\]]+)\] engine code failed to load, account held")
HELD_LOOKBACK_MS = 10 * 60_000     # the load's alerts come just before the start record (server time, then bootstrap)


def held_accounts(conn: sqlite3.Connection, tables: set, run: Optional[dict], run_ts: Optional[int]) -> list[str]:
    """The original accounts this start froze (``HeldEngine``): the start record's own list when the runner writes
    one (``run["held"]``), plus the CRITICAL alerts "[<id>] engine code failed to load, account held" of this start
    (accounts.AccountBook._original_how; written at the load, just before the start record)."""
    out = set()
    if isinstance(run, dict) and isinstance(run.get("held"), (list, tuple)):
        out |= {str(a) for a in run["held"]}
    if "alerts" in tables and run_ts is not None:
        lo = int(run_ts) - HELD_LOOKBACK_MS
        if "runs" in tables:                    # never an alert of the start before this one
            prev = conn.execute("SELECT started_ts FROM runs WHERE started_ts < ? ORDER BY started_ts DESC LIMIT 1",
                                (int(run_ts),)).fetchone()
            if prev is not None and prev[0] is not None:
                lo = max(lo, int(prev[0]) + 1)
        for (text,) in conn.execute("SELECT text FROM alerts WHERE ts >= ? AND text LIKE '%account held%'", (lo,)):
            m = HELD_RE.match(str(text))
            if m:
                out.add(m.group("aid"))
    return sorted(out)


def extras_held(conn: sqlite3.Connection, tables: set) -> list[str]:
    """Extra accounts (copies, new strategies) the extras runtime holds frozen (state 'extras', status 'held')."""
    if "state" not in tables:
        return []
    row = conn.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()
    try:
        st = json.loads(row[0]) if row and row[0] else {}
    except (TypeError, ValueError):
        return []
    acc = st.get("accounts") if isinstance(st, dict) else None
    if not isinstance(acc, dict):
        return []
    return sorted(str(a) for a, v in acc.items() if isinstance(v, dict) and v.get("status") == "held")


def read_paper_db(path: str) -> dict:
    """Run start, heartbeat, this start's record and the bot's health row (bar lag, dead-man pings) from
    paper3.db, opened read-only; the original accounts per group (paper v4, resetrun.facts_of_rows) and the accounts
    this start froze."""
    from .resetrun import facts_of_rows, original_rows
    conn = open_ro(path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        one = lambda q: (conn.execute(q).fetchone() or (None,))[0]          # noqa: E731
        start = None
        originals = off_tf = facts = None
        if "accounts" in tables:
            facts = facts_of_rows(original_rows(conn))
            start, originals, off_tf = facts["start"], facts["originals"], facts["off_tf"]
        if start is None and "runs" in tables:
            start = one("SELECT MIN(started_ts) FROM runs")
        hb = run = run_ts = health = health_ts = None
        if "state" in tables:
            hb = one("SELECT ts FROM state WHERE k = 'heartbeat'")
            row = conn.execute("SELECT ts, data FROM state WHERE k = 'run'").fetchone()
            if row and row[1]:
                run_ts, run = row[0], json.loads(row[1])
            row = conn.execute("SELECT ts, data FROM state WHERE k = 'health'").fetchone()
            if row and row[1]:
                health_ts, health = row[0], json.loads(row[1])
        run = run if isinstance(run, dict) else None
        run_ts = None if run_ts is None else int(run_ts)
        return {"start": None if start is None else int(start), "heartbeat": None if hb is None else int(hb),
                "run": run, "run_ts": run_ts,
                "health": health if isinstance(health, dict) else None,
                "health_ts": None if health_ts is None else int(health_ts),
                "originals": None if originals is None else int(originals),
                "originals_off_tf": None if off_tf is None else int(off_tf), "facts": facts,
                "held": held_accounts(conn, tables, run, run_ts), "extras_held": extras_held(conn, tables)}
    finally:
        conn.close()


def paper_start(ctx: Ctx) -> Optional[int]:
    path = os.path.join(ctx.lib, "paper3.db")
    try:
        return read_paper_db(path)["start"] if ctx.stat(path) is not None else None
    except (sqlite3.Error, OSError, ValueError):
        return None


LIVE_BRACKETS = "Binance leverageBracket (live)"      # paperbot/live.load_brackets' source for the exchange's


def move_old_db_command(ctx: Ctx) -> str:
    """Moves a test run's databases into a new dated folder among the backups (pruned after 14 days like
    them), in one root shell: nullglob skips a database the test run never made, so nothing reads as an
    error. Ends without punctuation: it is copied as a whole."""
    names = " ".join(os.path.join(ctx.lib, f"{n}.db*") for n in ("paper3", "daily3", "checkpoint"))
    return (f"sudo systemctl stop paperbot-live3 && sudo bash -c 'shopt -s nullglob; "
            f"d={ctx.backups}/old-$(date -u +%Y%m%d%H%M); mkdir -p \"$d\" && mv {names} \"$d\"/ && "
            f"chown -R {ctx.user}:{ctx.user} \"$d\" && echo \"옮김: $d\"'")


def bot_health_lines(db: dict, now: int, deadman_set: bool) -> list[Line]:
    """The bot writes its heartbeat on every poll, also when no new bar came in: the 'health' row says
    whether 1m bars are fresh and whether its own dead-man pings get through (a DEADMAN_URL added after
    the start is not used until a restart, and healthchecks.io never alerts on a check that was never
    pinged)."""
    health, run_ts = db.get("health"), db.get("run_ts")
    settled = run_ts is not None and now - run_ts >= SETTLE_MS
    if health is None:
        return [note("봇의 상태 기록(health)이 없어 1분봉과 healthchecks.io 핑을 확인하지 못했습니다: healthchecks.io 화면이 "
                     "'up'(초록)인지 눈으로 보세요")]
    out: list[Line] = []
    last_bar = health.get("last_bar")
    lag = None if not isinstance(last_bar, (int, float)) else now - (int(last_bar) + 60_000)
    if lag is None or lag > BAR_LAG_MAX_MS:
        if not settled:
            return [note("봇이 아직 준비 중입니다(시작 10분 안): 1분봉·healthchecks.io 핑은 10분쯤 뒤 다시 확인하세요")]
        out.append(fix(("바이낸스 1분봉이 아직 한 번도 처리되지 않았습니다" if lag is None else
                        f"바이낸스 1분봉이 {lag // 60_000}분째 들어오지 않습니다")
                       + ": journalctl -u paperbot-live3 -n 50 (이대로면 healthchecks.io가 'down' 알림을 보냅니다)"))
        return out                          # stale bars also hold back the pings: nothing more to say about them
    out.append(ok(f"바이낸스 1분봉 정상: 마지막 봉 {max(0, lag) // 1000}초 지연"))
    if not deadman_set:
        return out
    dm = health.get("deadman") if isinstance(health.get("deadman"), dict) else {}
    last_ping, failures = dm.get("last_ping"), dm.get("failures") or 0
    ping_age = None if not isinstance(last_ping, (int, float)) else now - int(last_ping)
    if ping_age is not None and ping_age <= PING_MAX_MS:
        out.append(ok(f"봇이 healthchecks.io에 핑을 보내고 있음: 마지막 {ping_age // 1000}초 전")
                   if not failures else
                   note(f"봇이 healthchecks.io에 핑을 보내고 있음(마지막 {ping_age // 1000}초 전). 그동안 실패 "
                        f"{failures}번: 잠깐 끊긴 것이면 괜찮습니다"))
    elif not settled:
        out.append(note("봇의 첫 healthchecks.io 핑을 기다리는 중입니다(시작 10분 안): 10분쯤 뒤 다시 확인하세요"))
    else:
        out.append(fix("봇이 healthchecks.io에 핑을 보내지 못하고 있습니다(마지막 핑: "
                       + ("없음" if ping_age is None else f"{ping_age // 60_000}분 전")
                       + "): DEADMAN_URL을 봇 시작 뒤에 넣었거나 고쳤다면 sudo systemctl restart paperbot-live3. "
                       "그래도 같으면 journalctl -u paperbot-live3 -n 50 에서 'dead-man ping failed'를 보세요"))
    return out


def check_paper_db(ctx: Ctx, stage: str, deadman_set: bool = False, path: Optional[str] = None) -> list[Line]:
    """``path``: another run database (``--db``: a staging run, a rehearsal copy); its runner's code is then not
    compared with the installed code (a staging run uses its own checkout)."""
    other_db = path is not None
    path = path or os.path.join(ctx.lib, "paper3.db")
    now = ctx.now_ms()
    if ctx.stat(path) is None:
        if stage == "before":
            return [ok("paper3.db 없음: 처음부터 새로 시작합니다 (30일 판정과 관찰 기간은 첫 시작일부터 셉니다)")]
        return [fix("paper3.db가 아직 없습니다: 봇이 시작하지 못했습니다. journalctl -u paperbot-live3 -n 50 을 보세요")]
    try:
        db = read_paper_db(path)
    except (sqlite3.Error, ValueError) as exc:
        return [fix(f"paper3.db를 읽지 못했습니다: {exc}")]
    start = db["start"]
    if stage == "before":
        if start is None:
            return [ok("paper3.db가 있지만 아직 계좌가 없습니다 (새로 시작하는 것과 같음)")]
        age = now - start
        if age < FRESH_RUN_MS:
            return [note(f"이미 {kst_text(start)}(한국 시간)에 시작한 기록이 있습니다({age // 3_600_000}시간 전): "
                         "30일 판정과 관찰 기간은 이때부터 셉니다. 시작한 뒤의 점검은 --stage after")]
        return [fix(f"{age // DAY_MS}일 전({kst_day(start)})에 시작한 기록이 paper3.db에 남아 있습니다: 30일 판정과 "
                    "관찰 기간이 그날부터 셉니다. 이어서 돌리는 것(재시작, 백업에서 되살림)이면 옮기지 말고 --stage after로 "
                    "확인하세요. 시험으로 돌린 것이면 "
                    "새로 시작하기 전에 아래 명령으로 옮기세요(백업 폴더 안 old-날짜 폴더로, 14일 뒤 저절로 지워짐): "
                    + move_old_db_command(ctx))]
    out: list[Line] = []
    hb = db["heartbeat"]
    if hb is None:
        out.append(fix("봇 생존 신호가 아직 없습니다: 처음 시작 때는 400일치 5분봉을 받느라 몇 분 걸립니다. 5분 뒤 다시 "
                       "확인하고, 그래도 없으면 journalctl -u paperbot-live3 -n 50"))
    else:
        age_s = max(0, now - hb) / 1000
        out.append(ok(f"봇 생존 신호 정상: {age_s:.0f}초 전") if age_s < HEARTBEAT_MAX_S else
                   fix(f"봇 생존 신호가 {age_s:.0f}초 전입니다({HEARTBEAT_MAX_S}초 넘음): systemctl status paperbot-live3, "
                       "journalctl -u paperbot-live3 -n 50"))
        if age_s < HEARTBEAT_MAX_S:
            out += bot_health_lines(db, now, deadman_set)
    run = db["run"]
    if run:
        src = str(run.get("brackets") or "")
        fee = run.get("taker_fee")
        rest = ((f", taker 수수료 {float(fee):.4%}" if fee is not None else "")
                + (", 재시작 뒤 이어서 돌림" if run.get("restored") else ""))
        if "EXAMPLE" in src:
            out.append(fix("봇이 예시 레버리지 구간으로 돌고 있습니다(거래소 값 아님): 읽기 전용 키를 넣고 "
                           "sudo systemctl restart paperbot-live3"))
        elif src == LIVE_BRACKETS:
            out.append(ok(f"계좌 {run.get('accounts', '?')}개, 레버리지 구간: 거래소 실제 값{rest}"))
        else:
            out.append(note(f"계좌 {run.get('accounts', '?')}개, 레버리지 구간: {src or '?'} (거래소에서 지금 받은 값이 "
                            f"아님. --brackets 파일을 따로 준 것이 아니면 개발자에게){rest}"))
        ver = {} if other_db else (installed_version(ctx) or {})
        if run.get("commit") and ver.get("commit") and run["commit"] != ver["commit"]:
            out.append(note(f"봇이 설치된 코드({str(ver['commit'])[:10]})가 아닌 {str(run['commit'])[:10]}로 돌고 있습니다: "
                            "sudo systemctl restart paperbot-live3"))
    out += account_set_lines(db)
    out += held_lines(db)
    out += strength_lines(path)
    if start is not None:
        out.append(ok(f"첫 시작 {kst_text(start)}(한국 시간)"))
    return out


def check_run_db(ctx: Ctx, path: str) -> list[Line]:
    """``--db PATH``: only one run database (a staging run, a rehearsal copy), as after the start: the bot's heartbeat
    and health, its start record, the v4 account set, frozen accounts, signal strength. Read-only."""
    if not os.path.isfile(path):
        return [fix(f"{path}가 아직 없습니다: 봇이 이 DB로 시작하지 못했습니다(journalctl로 그 봇의 기록을 보세요)")]
    return check_paper_db(ctx, "after", False, path=os.path.abspath(path))


STRENGTH_RECENT = 20      # the last strategy signals of cells with quality edges that must carry a strength score


def strength_lines(path: str, n: int = STRENGTH_RECENT) -> list[Line]:
    """Do recent strategy signals of cells with quality edges carry a usable strength score (quality_v1 sizes a
    signal without one 'normal')? FIX when none of the last ``n`` does (review M2)."""
    try:
        from .strengthwatch import CAUSE_KO, recent_edge_signals
        conn = open_ro(path)
        try:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'signal_log'").fetchone():
                return []
            causes = recent_edge_signals(conn, n)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return [note(f"신호 세기 기록을 확인하지 못했습니다: {type(exc).__name__}: {exc}"[:200])]
    if not causes:
        return []                           # no strategy signal yet (just started): nothing to check
    bad = [c for c in causes if c]
    if not bad:
        return [ok(f"신호 세기 정상: 최근 매매법 신호 {len(causes)}건 모두 좋은 자리 판정 점수가 있음")]
    why = ", ".join(sorted({CAUSE_KO.get(c, c) for c in bad}))
    if len(bad) == len(causes):
        return [fix(f"최근 매매법 신호 {len(causes)}건 모두 신호 세기 계산 실패({why}): 좋은 자리 판정이 전부 '보통'(30·20배)으로 "
                    "처리되고 있습니다. 대시보드 알림 목록의 'strength score failed'를 개발자에게 보내세요")]
    return [note(f"최근 매매법 신호 {len(causes)}건 중 {len(bad)}건 신호 세기 계산 실패({why}): 그 신호는 '보통'으로 처리됨. "
                 "계속되면 개발자에게")]


RESET_CMD = "sudo bash deploy/paperbot-reset.sh --yes"


def _groups_text(groups: dict) -> str:
    from .resetrun import groups_text
    return groups_text(groups)


def account_set_lines(db: dict) -> list[Line]:
    """The original accounts are the v4 rules' set (config.V4_GROUPS, docs/paper-v4-rules.md): per group and timeframe,
    made by a paper-v4 runner, all on one UTC day. A database of the v3 run (only the 36 and the coin flips, made by a
    v3 runner) is [고칠 것] with the reset command; any other difference is [고칠 것] for the developer, never the
    reset (a running v4 run would be archived)."""
    f = db.get("facts") or {}
    n = db.get("originals")
    if not n:
        return []
    groups = _groups_text(f.get("groups") or {})
    if f.get("shape") == "v3":
        five = (f.get("by_tf") or {}).get("5m", 0)
        when = " 2026-10-04 재시작 전 실행(매매법 5분봉 있음)" if five else ""
        return [fix(f"paper3.db가 paper v3 실행{when}의 DB입니다(원래 계좌 {n}개: {groups}). 규칙은 paper v4 계좌 "
                    f"{V4_ACCOUNTS}개({_groups_text(V4_GROUP_ACCOUNTS)}): docs/server-setup-v4.md대로 {RESET_CMD} 로 "
                    "처음부터 다시 시작합니다")]
    out: list[Line] = []
    if f.get("shape") != "v4":
        why = []
        if f.get("off_tf"):
            why.append(f"그룹이 쓰지 않는 봉의 계좌 {f['off_tf']}개(예: 매매법 5분봉)")
        if f.get("versions") and f["versions"] != [V4_VERSION]:
            why.append(f"설정 버전 {'/'.join(f['versions'])}(규칙은 {V4_VERSION})")
        if n != V4_ACCOUNTS or not why:
            why.append(f"원래 계좌 {n}개({groups}), 규칙은 {V4_ACCOUNTS}개({_groups_text(V4_GROUP_ACCOUNTS)})")
        out.append(fix("paper3.db의 계좌가 v4 규칙과 다릅니다: " + "; ".join(why) + ". 처음부터 다시 시작하지 말고 "
                       "(돌던 실행이 보관 폴더로 감) 이 줄을 개발자에게 보내세요"))
    else:
        out.append(ok(f"원래 계좌 {n}개 = {groups} (paper v4 규칙과 같음, 5분봉 "
                      f"{(f.get('by_tf') or {}).get('5m', 0)}개: 릴스 5분 단타와 동전만)"))
    if (f.get("utc_days") or 0) > 1:
        out.append(fix(f"원래 계좌를 만든 UTC 날짜가 {f['utc_days']}개입니다(한 번에 만들어야 함): 늦게 만든 계좌는 30일 판정이 "
                       "다음 판정으로 밀립니다. 개발자에게 알리세요"))
    return out


def held_lines(db: dict) -> list[Line]:
    """Frozen accounts of this start: an original one is [고칠 것] (it neither trades nor manages its position: the
    engine code of its group could not be loaded); a frozen extra account is [참고] (paperbot/extras.py reports why)."""
    if not db.get("originals"):
        return []
    held, xh = list(db.get("held") or []), list(db.get("extras_held") or [])
    out: list[Line] = []
    if held:
        out.append(fix(f"멈춘(동결된) 원래 계좌 {len(held)}개: {', '.join(held[:8])}{' …' if len(held) > 8 else ''}. "
                       "그 계좌의 청산·진입 코드를 불러오지 못해 저장된 상태 그대로 멈춰 있습니다(다른 계좌는 정상): "
                       "대시보드 알림의 'engine code failed to load'를 개발자에게 보내세요"))
    else:
        out.append(ok("멈춘(동결된) 계좌 0개 (held = 0)"))
    if xh:
        out.append(note(f"멈춘 추가 계좌 {len(xh)}개: {', '.join(xh[:8])} (python -m paperbot.extras status 로 이유 확인)"))
    return out


# an extra paper account's id (paperbot/extras.py: a copy "S@15m~c1", a new strategy "NL1@1h")
EXTRA_ACCOUNT_RE = re.compile(r"(~c[0-9]+$)|(^NL[0-9]+@)")


def check_executor_account(ctx: Ctx) -> list[Line]:
    """The paper account the order executor follows (``account`` in /etc/paperbot/executor.json, no keys in it)
    must be an original strategy account (paper3.db kind 'strategy'). The executor itself does not refuse an
    extra account yet (a copy or a new strategy, docs/extra-accounts.md 9) or a coin-flip account, and would
    then trade real money on a rule that never went through the live-safety review. No file: nothing to say."""
    path = os.path.join(ctx.etc, "executor.json")
    if ctx.stat(path) is None:
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as exc:
        return [note(f"{path}를 읽지 못해 주문 실행기가 따라 할 계좌를 확인하지 못했습니다 ({type(exc).__name__})")]
    acct = cfg.get("account") if isinstance(cfg, dict) else None
    if not isinstance(acct, str) or not acct.strip():
        return [note(f"{path}에 따라 할 계좌(account)가 없습니다: 실행기의 check-config가 거부합니다")]
    kind = None
    db = os.path.join(ctx.lib, "paper3.db")
    if ctx.stat(db) is not None:
        try:
            conn = open_ro(db)
            try:
                row = conn.execute("SELECT kind FROM accounts WHERE account_id = ?", (acct,)).fetchone()
            finally:
                conn.close()
            kind = row[0] if row else None
        except sqlite3.Error:
            kind = None
    from .resetrun import executor_problem
    name_why = executor_problem(acct)
    if EXTRA_ACCOUNT_RE.search(acct) or (kind is not None and kind != "strategy") or (kind is None and name_why
                                                                                       and "봉" not in name_why):
        what = {"copy": "복제 계좌", "newlab": "새 매매법 계좌", "random": "동전 봇 계좌", "ds200": "딥시크 계좌",
                "reel": "릴스 5분 단타 계좌"}.get(kind, name_why if kind is None and name_why else "추가 계좌 이름")
        return [fix(f"주문 실행기가 따라 할 계좌 {acct}는 원래 매매법 계좌가 아닙니다({what}). 실행기는 아직 이런 계좌를 "
                    "거부하지 않아 실제 돈으로 따라 하게 됩니다 → /etc/paperbot/executor.json의 account를 원래 매매법 "
                    "계좌(예: V45_AMB@15m)로 바꾸세요 (docs/extra-accounts.md 9장)")]
    if kind is None:
        return [note(f"주문 실행기가 따라 할 계좌 {acct}를 paper3.db에서 찾지 못해 종류를 확인하지 못했습니다 "
                     "(봇 시작 전이면 괜찮습니다)")]
    return [ok(f"주문 실행기가 따라 할 계좌 {acct}: 원래 매매법 계좌")]


def check_liq(ctx: Ctx) -> list[Line]:
    """After the start: the liquidation recorder (paperbot-liq) keeps reconnecting on its own and stays
    'active' while the stream is down, and Binance keeps no history of liquidations: its connection log
    in liq.db says whether data is being recorded now."""
    path = os.path.join(ctx.lib, "liq.db")
    now = ctx.now_ms()
    if ctx.stat(path) is None:
        return [fix("liq.db가 없습니다: 강제청산 기록기(paperbot-liq)가 기록하지 못하고 있습니다. "
                    "journalctl -u paperbot-liq -n 30")]
    try:
        conn = open_ro(path)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "conn_log" not in tables:
                return [note("liq.db에 연결 기록이 아직 없습니다: 몇 분 뒤 다시 확인하세요")]
            up = conn.execute("SELECT MAX(ts) FROM conn_log WHERE event = 'connected'").fetchone()[0]
            down = conn.execute("SELECT MIN(ts) FROM conn_log WHERE event IN ('disconnected', 'stopped') "
                                "AND ts >= ?", (up or 0,)).fetchone()[0]
            last = conn.execute("SELECT MAX(received_ts) FROM liq").fetchone()[0] if "liq" in tables else None
        finally:
            conn.close()
    except (sqlite3.Error, ValueError) as exc:
        return [fix(f"liq.db를 읽지 못했습니다: {exc}")]
    if up is None and down is None:
        return [note("강제청산 기록기가 아직 연결 기록을 남기지 않았습니다: 몇 분 뒤 다시 확인하세요")]
    if down is None:
        seen = f", 마지막 청산 기록 {max(0, now - int(last)) // 60_000}분 전" if last is not None else ", 청산 기록은 아직 없음"
        return [ok(f"강제청산 기록기 연결됨: {kst_text(int(up))}(한국 시간)부터{seen}")]
    gone = max(0, now - int(down))
    if gone <= LIQ_DOWN_MAX_MS:
        return [note(f"강제청산 기록기가 {gone // 1000}초 전에 끊겨 다시 연결하는 중입니다: 몇 분 뒤 다시 확인하세요")]
    return [fix(f"강제청산 기록기가 {gone // 60_000}분째 바이낸스에 연결돼 있지 않습니다(이 동안의 청산 기록은 되살릴 수 "
                "없음): systemctl status paperbot-liq, journalctl -u paperbot-liq -n 30")]


def check_offsite(live: EnvFile, states: Optional[dict]) -> list[Line]:
    """The off-site copy of the nightly backup (paperbot/offsite.py): the only copy outside the server, as
    the owners keep Vultr's automatic backups off. Its timer itself is checked with the other units."""
    if states is None:
        return []
    if ((states.get(OFFSITE_TIMER) or {}).get("LoadState")) != "loaded":
        return [note("서버 밖 백업(paperbot-offsite)이 이 서버에 설치되지 않았습니다: 서버를 잃으면 기록도 함께 "
                     f"사라집니다. 설치: {OFFSITE_INSTALL} (docs/server-setup-v3.md 4-3, 11)")]
    if not live.get("TELEGRAM_CHAT_BACKUP"):
        return [note("live.env의 TELEGRAM_CHAT_BACKUP이 비어 있어 매일 백업 파일이 알림방(TELEGRAM_CHAT_CRITICAL에 넣은 방)으로 "
                     "갑니다. 그 방으로 받기로 했으면 그대로 두면 되고, 따로 받으려면 docs/server-setup-v3.md 4-3대로 "
                     "'paperbot 백업' 방 번호를 넣으세요")]
    return [ok("서버 밖 백업: 설치됨, 'paperbot 백업' 방 번호 있음 (매일 09:15 한국 시간)")]


# ---------------------------------------------------------------- agent rooms
def agents_configured(agents: EnvFile, states: Optional[dict]) -> bool:
    timer = ((states or {}).get("paperbot-agents.timer") or {})
    return bool(agents.get("CLAUDE_CODE_OAUTH_TOKEN")) or _enabled(timer)


def check_lab(ctx: Ctx, states: Optional[dict], agents_wanted: bool, ref: Optional[dict] = None) -> list[Line]:
    """The 5-year lab caches against the research digests, like ``labdata check`` but without writing
    its manifest (this check may run as root and must not leave a root-owned file in the lab folder)."""
    level = fix if agents_wanted else note
    lab = os.path.join(ctx.lib, "lab")
    build = (states or {}).get(LABBUILD) or {}
    if build.get("ActiveState") in ("active", "activating"):
        return [note("5년 시험 자료를 지금 만드는 중입니다(paperbot-labbuild): journalctl -fu paperbot-labbuild, "
                     "끝난 뒤 다시 확인하세요")]
    if build.get("ActiveState") == "failed":
        # a build started without --collect stays loaded as failed: the same systemd-run is then refused
        # ("Unit paperbot-labbuild.service was already loaded") until reset-failed
        return [level("5년 시험 자료 만들기가 실패한 채 남아 있습니다: 이유 보기 sudo journalctl -u paperbot-labbuild -n 30 "
                      "--no-pager → sudo systemctl reset-failed paperbot-labbuild → 다시 만들기(받은 것은 두고 이어서 "
                      f"합니다): {LAB_BUILD}")]
    info = ctx.stat(lab)
    if info is None:
        return [level(f"5년 시험 자료 폴더가 없습니다(에이전트 방에 필요). 30~60분 걸립니다: {LAB_BUILD}")]
    out: list[Line] = []
    if info.owner != ctx.user:
        out.append(level(f"{lab} 주인이 {info.owner}입니다: sudo chown -R {ctx.user}:{ctx.user} {lab}"))
    import numpy as np

    from .agents import labdata
    ref = ref or labdata.reference()
    p = labdata.paths(lab)
    same, missing, differ = 0, [], []
    for src in labdata.SOURCES:
        for key, want in sorted((ref.get(src) or {}).items()):
            f = os.path.join(p[src], f"sig_{key}.npz")
            if not os.path.exists(f):
                missing.append(f"{src} {key}")
                continue
            with np.load(f) as z:
                digest = labdata.content_digest({k: z[k] for k in z.files})
            if digest == want["digest"]:
                same += 1
            else:
                differ.append(f"{src} {key}")
    n = same + len(missing) + len(differ)
    if n and not missing and not differ:
        return out + [ok(f"5년 시험 자료 {same}/{n}개가 연구 자료와 같음")]
    some = ", ".join((missing + differ)[:4]) + (" …" if len(missing) + len(differ) > 4 else "")
    return out + [level(f"5년 시험 자료 {same}/{n}개만 연구 자료와 같습니다(없음 {len(missing)}, 다름 {len(differ)}: "
                        f"{some}). 같은 명령을 다시 실행하면 이어서 만듭니다: {LAB_BUILD}")]


def claude_hint(reason: str) -> str:
    r = reason.lower()
    if "not logged in" in r:
        return (f"agents.env의 CLAUDE_CODE_OAUTH_TOKEN을 확인하세요 (토큰 만들기: {CLAUDE_TOKEN}, 브라우저에서는 구독 "
                "계정으로 로그인)")
    if "api key" in r:
        return ("API 키 대신 구독을 써야 합니다: agents.env와 서버 어디에도 ANTHROPIC_API_KEY를 두지 말고, paperbot의 "
                "~/.claude.json에 저장된 Console 로그인을 지우세요")
    if "third-party" in r:
        return "Bedrock·Vertex 설정(CLAUDE_CODE_USE_*)을 지우세요"
    return f"Claude Code를 다시 설치해 보세요: {CLAUDE_INSTALL}"


def check_claude(ctx: Ctx, agents: EnvFile, agents_wanted: bool) -> list[Line]:
    """`claude --setting-sources "" auth status --json` as user paperbot with agents.env's variables, exactly
    the agents tick's own preflight (paperbot/agents/runner.auth_preflight): logged in, no apiKeySource."""
    level = fix if agents_wanted else note
    claude = ctx.claude_bin
    if ctx.euid == 0:
        prefix = [RUNUSER, "-u", ctx.user, "--"]     # keeps the environment below; HOME becomes paperbot's
    elif ctx.username == ctx.user:
        prefix = []
    else:
        return [note(f"Claude Code 로그인은 root나 {ctx.user}로 실행할 때만 확인합니다")]
    if ctx.stat(claude) is None:
        return [level(f"Claude Code가 {ctx.user} 사용자에게 설치되지 않았습니다(에이전트 방에 필요): {CLAUDE_INSTALL}")]
    home = ctx.lib
    # what paperbot-agents.service gives the pass: HOME/USER from User=, PATH from Environment=, then the env file
    parent = {"HOME": home, "USER": ctx.user, "LANG": "C.UTF-8",
              "PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin", **agents.values}

    def run(cmd, capture_output=True, text=True, timeout=60.0, env=None):    # subprocess.run's shape
        rc, out, err = ctx.run(prefix + list(cmd), env, timeout)
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    from .agents.runner import auth_preflight
    good, why = auth_preflight(claude, env=parent, run=run, timeout=60.0)
    if good:
        # auth status only sees that a token is set (no call to the server): the first real meeting is the
        # real test (docs/server-setup-v3.md 12)
        return [ok(f"Claude Code 로그인 설정 확인됨: 구독 토큰 ({why or '?'}), API 키 아님 "
                   "(토큰이 실제로 되는지는 시작 뒤 첫 회의에서 확인)")]
    return [level(f"Claude Code 로그인 확인 실패: {why}. {claude_hint(why)}")]


def check_agents_policy(ctx: Ctx, agents: EnvFile, agents_wanted: bool, run_start: Optional[int]) -> list[Line]:
    """agents.env's AGENTS_* settings through the tick's own parser, its budget warnings, and the
    observation period (no copy proposals) they give."""
    level = fix if agents_wanted else note
    if not agents.exists or agents.error:
        return [level(f"{agents.path}를 읽지 못해 에이전트 설정(AI 예산·관찰 기간)을 확인하지 못했습니다")]
    from .agents.rooms import OBSERVE_DAYS_DEFAULT, _kst_day_end, budget_warnings, policy_from_env
    try:
        p = policy_from_env(dict(agents.values))
    except ValueError as exc:
        return [level(f"agents.env 값이 잘못됐습니다: {exc}. 이대로면 에이전트 회의가 시작하지 않습니다")]
    out = [ok(f"agents.env 설정 읽힘: AI 하루 최대 {p.total_budget[0]}회·{p.total_budget[1]:,} 토큰, "
              f"7일 {p.week_budget[0]}회·{p.week_budget[1]:,} 토큰")]
    out += [note(f"예산 경고(그 회의는 열리지 못함): {w}") for w in budget_warnings(p)]
    if p.force_sonnet:
        out.append(note("AGENTS_FORCE_SONNET 켜짐: 상위 모델을 쓰는 역할도 모두 기본 모델로 회의합니다 "
                        "(끄려면 agents.env에서 그 줄을 지우거나 0)"))
    # the period lasts until the later of observe_days after the start and AGENTS_OBSERVE_UNTIL (rooms.observing;
    # the live runner's own floor can make it longer still); observe_days is never below 21 (policy_from_env)
    days_end = run_start + p.observe_days * DAY_MS if run_start is not None else None
    until_end = _kst_day_end(p.observe_until) if p.observe_until else None
    if until_end is not None and (until_end <= (days_end or 0) or (days_end is None and
                                                                     p.observe_until < kst_day(ctx.now_ms()))):
        when = f"{kst_day(days_end - 1)}까지" if days_end is not None else "까지"
        out.append(note(f"관찰 기간: AGENTS_OBSERVE_UNTIL({p.observe_until})이 이미 지났거나 봇 첫 시작부터 "
                        f"{p.observe_days}일보다 빨라 쓰이지 않습니다 → 봇 첫 시작부터 {p.observe_days}일{when} 복사 제안 없음"))
    elif until_end is not None:
        out.append(ok(f"관찰 기간: {p.observe_until}(한국 날짜)까지 복사 제안 없음"))
    else:
        until = f", {kst_day(days_end - 1)}까지" if days_end is not None else ""
        text = f"관찰 기간: 봇 첫 시작부터 {p.observe_days}일{until} 복사 제안 없음"
        out.append(ok(text) if p.observe_days == OBSERVE_DAYS_DEFAULT else
                   note(f"{text} (정한 값 {OBSERVE_DAYS_DEFAULT}일과 다름)"))
    return out


# ---------------------------------------------------------------- the 24-hour debate room (optional, paid API)
DEBATE_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")
DEBATE_DIR_MODE = ("paperbot-debate", "paperbot", 0o2750)    # owner, group, mode of /var/lib/paperbot/debate


def check_debate(ctx: Ctx, states: Optional[dict], envs: dict[str, EnvFile]) -> list[Line]:
    """Not installed or installed but off: [참고] only. Turned on: the key must be there (else [고칠 것]) and look like a key,
    the key file must be root:paperbot-debate 640 (check_env_files; user paperbot cannot read it), the service
    user and its folder must exist, and the last round, this month's spend against the cap are shown. The key is
    never printed (report() scrubs every env value)."""
    st = (states or {}).get(DEBATE_UNIT) or {}
    ef = envs["debate"]
    if st.get("LoadState") != "loaded":
        return [note("24시간 토론방(paperbot-debate, 유료 API)은 설치되어 있지 않습니다 (선택): 설치 스크립트를 다시 돌리면 "
                     "설치만 되고 켜지지 않습니다. 설명: docs/debate-room.md")]
    on = _enabled(st) or _active(st)
    level = fix if on else note
    out: list[Line] = []
    if ctx.user_id(DEBATE_USER) is None:
        out.append(level(f"토론방 사용자 {DEBATE_USER}가 없습니다: {INSTALL}"))
    if not on:
        out.append(note("24시간 토론방(유료 API)은 설치만 되어 있고 꺼져 있습니다. 쓰려면 docs/debate-room.md 순서대로 "
                        "키를 넣고 sudo systemctl enable --now paperbot-debate"))
    if ctx.euid != 0 and ef.exists:
        out.append(note(f"토론방 설정(debate.env)은 root만 열어 볼 수 있습니다(키 보호): sudo로 실행하면 키가 들어 있는지도 확인합니다"))
    elif ef.exists and not ef.error:
        key = ef.get(DEBATE_KEY)
        if key and not DEBATE_KEY_RE.fullmatch(key):
            out.append(level("debate.env의 ANTHROPIC_API_KEY 모양이 API 키(sk-ant-…, 공백 없음)가 아닙니다: 콘솔에서 받은 키를 "
                             "sudoedit로 다시 붙여 넣으세요"))
        if on and not key:
            out.append(fix("24시간 토론방이 켜져 있는데 debate.env에 ANTHROPIC_API_KEY가 비어 있습니다: "
                           "sudoedit /etc/paperbot/debate.env 에 키를 넣고 sudo systemctl restart paperbot-debate"))
    elif on and not ef.exists:
        out.append(fix(f"24시간 토론방이 켜져 있는데 {ef.path}가 없습니다: {INSTALL}"))
    d = ctx.stat(os.path.join(ctx.lib, "debate"))
    if d is not None and (d.owner, d.group, d.mode) != DEBATE_DIR_MODE:
        out.append(level(f"{ctx.lib}/debate 권한이 {d.owner}:{d.group} {d.mode:o}입니다 (맞는 값 {DEBATE_DIR_MODE[0]}:"
                         f"{DEBATE_DIR_MODE[1]} {DEBATE_DIR_MODE[2]:o}): {INSTALL}"))
    if on:
        from .agents import debate as DB
        s = DB.summary(os.path.join(ctx.lib, "debate", "debate.db"), ctx.now_ms())
        if not s.get("ready"):
            out.append(note("24시간 토론방이 켜져 있지만 아직 토론 기록이 없습니다: 켠 직후라면 첫 회차까지 기다리세요. "
                            "오래됐다면 journalctl -u paperbot-debate -n 30"))
        else:
            sp = s["spend"]
            last = "아직 없음" if not s.get("last_round_ts") else kst_text(s["last_round_ts"])
            line = (f"24시간 토론방 {s['state_ko']}: 마지막 토론 {last}, 이번 달 ${sp['month']:.2f} / 한도 ${sp['cap']:g}"
                    + (f" ({sp['pct']}%)" if sp.get("pct") is not None else "") + f", {s.get('every_min')}분마다")
            if s["state"] == "running":
                out.append(ok(line))
            elif s["state"] == "no_key":
                out.append(fix(line + f" — {s.get('reason')}"))
            else:
                out.append(note(line + (f" — {s.get('reason')}" if s.get("reason") else "")))
    return out


# ---------------------------------------------------------------- run and report
def guard(fn: Callable[..., list], *args, level: Callable[[str], Line] = fix) -> list[Line]:
    """A check that breaks is reported as one line (``level``: [고칠 것], or [참고] for an optional part);
    the other checks still run. The message is kept whole here: report() scrubs it, then cuts it (a cut
    made first could split a secret so that the scrub misses the rest)."""
    try:
        return list(fn(*args))
    except Exception as exc:  # noqa: BLE001
        return [level(f"{ERROR_PREFIX}{type(exc).__name__}: {exc}")]


def start_command(states: Optional[dict], agents_wanted: bool = False) -> str:
    """The start command for this server: the base units, the agent rooms' timers when they are wanted
    (docs/server-setup-v3.md 11 starts everything at once), and the extra timers its install.sh installed."""
    extra = [u for u in EXTRA_SERVICES + EXTRA_TIMERS if ((states or {}).get(u) or {}).get("LoadState") == "loaded"]
    return " ".join([START_CMD] + (list(AGENT_TIMERS) if agents_wanted else []) + extra)


def run_checks(ctx: Ctx, stage: str = "before", send_test: bool = False, ping: bool = False,
               agents: str = "auto", skip_lab: bool = False) -> tuple[list[tuple[str, list[Line]]], list[str], str]:
    """[(section title, lines)], the secret values to scrub from them, and this server's start command."""
    envs = read_envs(ctx)
    try:
        states = unit_states(ctx)
    except Exception:  # noqa: BLE001  (check_units then reports that systemctl cannot be used)
        states = None
    wanted = agents == "yes" or (agents == "auto" and agents_configured(envs["agents"], states))
    opt = fix if wanted else note
    live, dash, ag = envs["live"], envs["dash"], envs["agents"]
    sections = [
        ("코드", guard(check_code, ctx)),
        ("설정 파일 (/etc/paperbot)", guard(check_env_files, ctx, envs, wanted)),
        ("바이낸스", guard(check_binance, ctx, live)),
        ("텔레그램", guard(check_telegram, ctx, envs, wanted, send_test)),
        ("봇 멈춤 알림 (healthchecks.io)", guard(check_deadman, ctx, live, ping, stage)),
        ("대시보드", guard(check_dash, ctx, dash, stage)),
        ("Tailscale·방화벽", guard(check_tailscale, ctx, dash)),
        ("서버 사양", guard(check_resources, ctx, states)),
        ("시계", guard(check_clock, ctx)),
        ("서비스", guard(check_units, states, stage, wanted, ctx.mono_us())),
        ("서버 밖 백업 (텔레그램)", guard(check_offsite, live, states, level=note)),
        ("주문 실행기 사용자 (키 분리)", guard(check_executor_user, ctx, states)),
        ("24시간 토론방 (유료 API, 선택)", guard(check_debate, ctx, states, envs, level=note)),
        ("주문 실행기가 따라 할 계좌", guard(check_executor_account, ctx)),
        ("데이터", guard(check_data_dir, ctx) + guard(check_paper_db, ctx, stage, bool(live.get("DEADMAN_URL")))
         + (guard(check_liq, ctx) if stage == "after" else [])),
    ]
    if agents == "no":
        sections.append(("에이전트 방", [note("점검 건너뜀 (--agents no)")]))
    else:
        head = [] if wanted else [note("에이전트 방은 아직 설정하지 않았습니다(선택). 아래 줄은 참고만 합니다: 켤 때는 "
                                       "--agents yes로 다시 확인하세요")]
        lab = ([note("5년 시험 자료 확인 건너뜀 (--skip-lab)")] if skip_lab else
               guard(check_lab, ctx, states, wanted, level=opt))
        lines = (head + guard(check_claude, ctx, ag, wanted, level=opt)
                 + guard(check_agents_policy, ctx, ag, wanted, paper_start(ctx), level=opt) + lab)
        timer_on = _enabled(((states or {}).get("paperbot-agents.timer") or {}))
        if agents == "auto" and wanted and not timer_on and any(s == FIX for s, _ in lines):
            # only the Claude token made them "wanted": the paper bot need not wait for the agent rooms
            lines.append(note("에이전트 방을 나중에 켤 거면 `--agents no`를 붙여 점검하고 봇을 먼저 시작해도 됩니다. "
                              "그때 결론 줄의 시작 명령에는 에이전트 타이머가 빠져 있고, 8~9번을 마친 뒤 "
                              "sudo systemctl enable --now paperbot-agents.timer paperbot-labmonthly.timer 로 켭니다"))
        sections.append(("에이전트 방", lines))
    return sections, secret_values(envs), start_command(states, wanted)


def report(sections: list[tuple[str, list[Line]]], stage: str, secrets: Sequence[str] = (),
           out: Callable[[str], None] = print, start_cmd: str = START_CMD) -> int:
    """Prints every line (scrubbed) and the verdict; returns the exit code (0 = nothing to fix)."""
    n_fix = n_note = 0
    for title, lines in sections:
        if not lines:              # e.g. the dead-man section while DEADMAN_URL is empty (the env line says so)
            continue
        out(f"== {title}")
        for status, text in lines:
            text = scrub(text, secrets)
            if text.startswith(ERROR_PREFIX) and len(text) > ERROR_MAX:
                text = text[:ERROR_MAX] + "…"
            out(f"[{status}] {text}")
            n_fix += status == FIX
            n_note += status == NOTE
    out("== 결론")
    if n_fix:
        out(f"[{FIX}] 고칠 것 {n_fix}개, 참고 {n_note}개: 위의 [{FIX}] 줄을 고친 뒤 이 점검을 다시 돌리세요."
            + (" 아직 시작하지 마세요." if stage == "before" else ""))
        return 1
    if stage == "before":
        out(f"[{OK}] 시작 준비가 끝났습니다 (참고 {n_note}개: 읽어만 보세요). 시작: {start_cmd}")
        out(f"     시작하고 10~15분 뒤 확인: {AFTER_CMD}")
    else:
        out(f"[{OK}] 봇이 정상으로 돌고 있습니다 (참고 {n_note}개: 읽어만 보세요). healthchecks.io가 'up'인지, 텔레그램에 "
            f"'봇 시작 · {RUN_KO} · 계좌 {V4_ACCOUNTS}개'(처음 시작) 또는 '봇 재시작 · {RUN_KO} · 계좌 {V4_ACCOUNTS}개 … "
            f"이어서 돌림'(설치·재시작 뒤)이 왔는지 눈으로도 보세요.")
    return 0


def main(argv: Optional[list[str]] = None, ctx: Optional[Ctx] = None,
         out: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.launchcheck", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=("before", "after"), default="before")
    ap.add_argument("--send-test", action="store_true", help="one test message to every configured Telegram chat")
    ap.add_argument("--ping", action="store_true", help="one ping to DEADMAN_URL")
    ap.add_argument("--agents", choices=("auto", "yes", "no"), default="auto")
    ap.add_argument("--skip-lab", action="store_true", help="do not re-hash the 5-year lab files")
    ap.add_argument("--db", help="check only this run database (staging, rehearsal copy); implies --stage after")
    args = ap.parse_args(argv)
    if args.db:
        args.stage = "after"
    ctx = ctx or Ctx()
    out(f"paperbot 시작 점검 ({'시작 전' if args.stage == 'before' else '시작 후'}): "
        f"{kst_text(ctx.now_ms())} 한국 시간, 실행 사용자 {ctx.username}")
    if args.db:
        out(f"실행 DB만 점검(--db): {args.db}. 서버의 나머지(설정·서비스·텔레그램)는 보지 않습니다")
        return report([(f"실행 DB ({args.db})", guard(check_run_db, ctx, args.db))], "after", (), out)
    sections, secrets, start_cmd = run_checks(ctx, args.stage, args.send_test, args.ping, args.agents, args.skip_lab)
    return report(sections, args.stage, secrets, out, start_cmd)


if __name__ == "__main__":
    sys.dont_write_bytecode = True       # no root-owned __pycache__ for the modules imported from here on
    sys.exit(main())
