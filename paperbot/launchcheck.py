"""Paper v3 launch check: is this server ready to start the paper bot, and does it run as it should?

    cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage before
    cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after

    --stage before|after   before: everything filled in and installed, nothing started yet (default);
                           after: the bot, dashboard, recorders and timers run, the bot's heartbeat is fresh
    --send-test            one test message to every configured Telegram chat
    --ping                 one ping to DEADMAN_URL (healthchecks.io then shows the check as "up")
    --agents auto|yes|no   the agent rooms: yes = required, no = not checked, auto (default) = required once
                           agents.env has a Claude token or paperbot-agents.timer is enabled, else shown as [참고]
    --skip-lab             do not re-hash the 5-year lab files (a minute or so of disk reads)

Prints one Korean line per check: [OK], [고칠 것] (fix it before going on; the exit code is 1 while one is
left) or [참고] (worth knowing; optional), then a verdict. Exit code 0 only when nothing is left to fix.

Run it as root (sees everything; the Claude Code check then runs as user paperbot through runuser) or as
user paperbot (``sudo -u paperbot``: the env files are group-readable; the firewall is then not checked).

Safe at any time, also while the bot runs:
- secrets are never printed: values show only as "set" / "empty", and every line is scrubbed of the env
  files' values before it is printed;
- nothing is written, started, enabled or changed: the env files are parsed the way systemd reads them
  (never ``source``d), paper3.db is opened read-only, and the lab files are hashed in memory
  (``labdata check`` itself writes its manifest, so it is not called);
- outbound calls: Binance public data and the read-only key's signed GETs (fapi.binance.com,
  api.binance.com), Telegram getMe; with --send-test one message per chat, with --ping one GET of
  DEADMAN_URL. Nothing here can place an order.

Each check is a small function of a ``Ctx`` whose command runner, HTTP fetcher, file-info lookup, clock
and paths are injectable: tests/test_launchcheck.py fakes all of them (no network, no real system).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import grp
import hashlib
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
from .config import V3_SYMBOLS, v3_settings
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
RUNUSER = "/usr/sbin/runuser"               # util-linux; runs the command itself, not paperbot's nologin shell
WALLET_API = "https://api.binance.com"      # key permissions (GET /sapi/v1/account/apiRestrictions)
TELEGRAM = "https://api.telegram.org"
DAY_MS = 86_400_000
HEARTBEAT_MAX_S = 90                        # the dashboard's "봇 생존 신호: 정상" threshold
FRESH_RUN_MS = DAY_MS                       # before the start: a paper3.db younger than this is "just started"
MAX_RESTARTS = 3
TAILNET = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))

INSTALL = "cd /root/crypto-bot-research && sudo bash deploy/install.sh"
START_CMD = ("sudo systemctl enable --now paperbot-live3 paperbot-dash paperbot-liq paperbot-daily3.timer "
             "paperbot-backup.timer paperbot-checkpoint.timer")
AFTER_CMD = ("cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck "
             "--stage after")
CLAUDE_INSTALL = "sudo -u paperbot -H bash -c 'cd ~ && curl -fsSL https://claude.ai/install.sh | bash'"
CLAUDE_TOKEN = "sudo -u paperbot -H /var/lib/paperbot/.local/bin/claude setup-token"
LAB_BUILD = ("sudo systemd-run --uid=paperbot --gid=paperbot --unit=paperbot-labbuild "
             "-p WorkingDirectory=/opt/crypto-bot-research -p Nice=10 /opt/paperbot/venv/bin/python "
             "-m paperbot.agents.labdata build --out /var/lib/paperbot/lab --procs 2")

# env file -> (owner, group, mode) as deploy/install.sh makes them
ENV_SPECS = {"live": ("root", USER, 0o640), "dash": ("root", USER, 0o640),
             "agents": ("root", USER, 0o640), "executor": ("root", "root", 0o600)}
LIVE_REQUIRED = ("BINANCE_API_KEY", "BINANCE_API_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL",
                 "DEADMAN_URL")
LIVE_OPTIONAL = ("TELEGRAM_CHAT_WARN", "TELEGRAM_CHAT_INFO")
DASH_REQUIRED = ("DASH_PASSWORD_HASH", "DASH_SECRET", "DASH_HOST")
AGENTS_REQUIRED = ("CLAUDE_CODE_OAUTH_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL")
ORDER_KEYS = ("TESTNET_API_KEY", "TESTNET_API_SECRET", "LIVE_API_KEY", "LIVE_API_SECRET", "PAPERBOT_LIVE_MAINNET")
EXCHANGE_KEYS = ("BINANCE_API_KEY", "BINANCE_API_SECRET") + ORDER_KEYS
# same names as paperbot/agents/runner.ENV_BILLING (a test keeps them equal): per-token billing outside the plan
ENV_BILLING = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
FORBIDDEN = {
    "live": {k: "주문용 키·스위치는 executor.env(root만 읽음)에만 둡니다" for k in ORDER_KEYS},
    "dash": {k: "대시보드에는 거래소 키가 필요 없습니다" for k in EXCHANGE_KEYS},
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
LABBUILD = "paperbot-labbuild.service"
INSTALLED = SERVICES + TIMERS + AGENT_TIMERS + JOBS + (EXECUTOR,)
ALL_UNITS = INSTALLED + LEGACY + SYSTEM + (LABBUILD,)
UNIT_PROPS = ("Id,LoadState,UnitFileState,ActiveState,SubState,Result,NRestarts,ExecMainStatus,"
              "NextElapseUSecRealtime,ExecStart")
RULES_SUMS = ("docs/paper-v3-rules.sha256", "docs/paper-v3-rules-addendum.sha256")

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
    sleep: Callable[[float], None] = time.sleep
    cpu_count: Callable[[], Optional[int]] = os.cpu_count
    disk_free: Callable[[str], int] = _disk_free
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


def scrub(text: str, secrets: Iterable[str]) -> str:
    for s in secrets:
        if s and s in text:
            text = text.replace(s, "***")
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
    for k in ("TELEGRAM_CHAT_CRITICAL",) + LIVE_OPTIONAL:
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
                out.append(fix(f"{name}.env에 {key}가 들어 있습니다: {why}. 그 줄을 지우세요"))
    live, dash, agents = envs["live"], envs["dash"], envs["agents"]
    out += _values_line(live, LIVE_REQUIRED, fix)
    out += _values_line(live, LIVE_OPTIONAL, note, "비어 있으면 CRITICAL 방으로 갑니다")
    out += _binance_key_format(live) + _telegram_format(live)
    out += _values_line(dash, DASH_REQUIRED, fix)
    out += _values_line(agents, AGENTS_REQUIRED, fix if agents_wanted else note,
                        "" if agents_wanted else "에이전트 방을 켤 때 채웁니다")
    out += _telegram_format(agents)
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
    except OSError as exc:
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
    """(label, token, chat id, silent) for each distinct chat the bot and the agents send to."""
    out, seen = [], set()
    files = [envs["live"]] + ([envs["agents"]] if agents_wanted else [])
    for ef in files:
        tok = ef.get("TELEGRAM_BOT_TOKEN")
        crit = ef.get("TELEGRAM_CHAT_CRITICAL")
        if not (tok and crit):
            continue
        for level in ("CRITICAL", "WARN", "INFO"):
            chat = ef.get(f"TELEGRAM_CHAT_{level}") or crit
            if (tok, chat) in seen:
                continue
            seen.add((tok, chat))
            out.append((f"{ef.name}.env {level}", tok, chat, level == "INFO"))
    return out


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
    if agents_wanted and agents.get("TELEGRAM_BOT_TOKEN") and (
            agents.get("TELEGRAM_BOT_TOKEN") != token
            or agents.get("TELEGRAM_CHAT_CRITICAL") != live.get("TELEGRAM_CHAT_CRITICAL")):
        out.append(note("agents.env의 텔레그램 봇·CRITICAL 방이 live.env와 다릅니다 (보통 같은 값을 넣습니다)"))
    chats = telegram_chats(envs, agents_wanted)
    if not send_test:
        out.append(note(f"시험 메시지는 보내지 않았습니다: --send-test를 붙이면 설정된 방 {len(chats)}곳에 하나씩 보냅니다"))
        return out
    for label, tok, chat, silent in chats:
        text = f"[시험] paperbot 시작 점검: {label} 알림이 이 방으로 옵니다. 답장하지 않아도 됩니다."
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
        out.append(note("핑은 보내지 않았습니다(--ping으로 한 번 보냄). 새 체크는 첫 핑 전('new')에는 알림을 보내지 "
                        "않습니다: 봇을 시작한 뒤 healthchecks.io에서 'up'(초록)이 되는지 꼭 보세요"
                        if stage == "before" else
                        "healthchecks.io 화면에서 이 체크가 'up'(초록)인지 눈으로 보세요: 봇이 1분마다 핑을 보냅니다"))
        return out
    try:
        status, _, _ = ctx.fetch("GET", url, {"User-Agent": "paperbot-launchcheck"}, None, 10.0)
        why = f"HTTP {status}"
    except OSError as exc:
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


def dash_host_lines(host: str) -> list[Line]:
    if not host:
        return []
    ip = _host_ip(host)
    if ip is None:
        return [fix(f"DASH_HOST={host}는 IP 주소가 아닙니다: Tailscale 주소(`tailscale ip -4`의 100.x.y.z)나 "
                    "127.0.0.1을 넣으세요")]
    if ip.is_loopback:
        return [ok(f"DASH_HOST={host}: 인터넷에 열리지 않음"),
                note("이 주소면 대시보드는 SSH 터널로만 봅니다. 폰에서 보려면 Tailscale 주소(100.x.y.z)를 넣으세요")]
    if ip.is_unspecified:
        return [fix(f"DASH_HOST={host}는 모든 주소입니다: 대시보드가 인터넷 쪽에도 열립니다. Tailscale 주소(100.x.y.z)를 "
                    "넣으세요")]
    if any(ip.version == net.version and ip in net for net in TAILNET):
        return [ok(f"DASH_HOST={host}: Tailscale 주소 (인터넷에 열리지 않음)")]
    return [fix(f"DASH_HOST={host}는 Tailscale 주소(100.64.0.0/10)도 127.0.0.1도 아닙니다: 대시보드는 Tailscale이나 "
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
    except OSError as exc:
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
    out += dash_host_lines(dash.get("DASH_HOST"))
    if dash.get("DASH_SECURE_COOKIE"):
        out.append(fix("DASH_SECURE_COOKIE가 켜져 있습니다: Tailscale(http)에서는 로그인이 막힙니다. 그 줄을 지우세요"))
    if stage == "after" and dash.get("DASH_HOST"):
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
                                                         ": docs/server-setup-v3.md 6번대로 설치하세요")))
    elif not isinstance(st, dict):
        out.append(level("Tailscale 상태를 읽지 못했습니다: sudo systemctl enable --now tailscaled && sudo tailscale up"))
    else:
        state = st.get("BackendState")
        me = st.get("Self") or {}
        ips = [str(a) for a in me.get("TailscaleIPs") or []]
        if state == "Running":
            out.append(ok(f"Tailscale 연결됨: 이 서버 {', '.join(a for a in ips if '.' in a) or '?'}"))
            if ip is not None and not loop and str(ip) not in ips:
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
    rc, text, _ = ctx.run(["ufw", "status"])
    if rc != 0:
        return out + [fix(f"방화벽(ufw) 상태를 읽지 못했습니다: 설치 스크립트를 다시 실행하세요 ({INSTALL})")]
    if not re.search(r"^Status:\s*active", text, re.M):
        return out + [fix("방화벽(ufw)이 꺼져 있습니다: sudo ufw enable (설치 스크립트는 SSH만 열고 켭니다)")]
    rules = [r for r in text.splitlines() if "ALLOW" in r]
    fw: list[Line] = []
    if any(re.match(r"8080(/tcp)?\b", r) and "tailscale0" not in r for r in rules):
        fw.append(fix("방화벽에서 8080 포트가 인터넷에 열려 있습니다: sudo ufw delete allow 8080 "
                      "(대시보드는 Tailscale로만 봅니다)"))
    if not loop and not any("tailscale0" in r for r in rules):
        fw.append(fix("방화벽에 Tailscale 허용 규칙이 없습니다: sudo ufw allow in on tailscale0"))
    return out + (fw or [ok("방화벽 켜짐 (SSH" + ("" if loop else "와 Tailscale") + "만 허용)")])


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


def service_line(unit: str, d: dict) -> Line:
    name = _short(unit)
    restarts = int(d.get("NRestarts") or 0) if (d.get("NRestarts") or "0").isdigit() else 0
    problems = []
    if not _enabled(d):
        problems.append(f"부팅 때 자동으로 켜지지 않음 (sudo systemctl enable {name})")
    if (d.get("ActiveState"), d.get("SubState")) != ("active", "running"):
        problems.append(f"실행 중이 아님({d.get('ActiveState')}/{d.get('SubState')}): journalctl -u {name} -n 50")
    if restarts > MAX_RESTARTS:
        problems.append(f"{restarts}번 다시 시작함(계속 죽는 중): journalctl -u {name} -n 50")
    if problems:
        return fix(f"{name}: " + "; ".join(problems))
    return ok(f"{name}: 켜짐·실행 중 (자동 재시작 {restarts}번)")


def timer_line(unit: str, d: dict, required: bool) -> Line:
    if _enabled(d) and d.get("ActiveState") == "active":
        nxt = d.get("NextElapseUSecRealtime") or ""
        return ok(f"{unit}: 켜짐" + (f", 다음 실행 {nxt}" if nxt and nxt != "n/a" else ""))
    return (fix if required else note)(f"{unit}: 꺼져 있음 → sudo systemctl enable --now {unit}")


def check_units(states: Optional[dict], stage: str, agents_wanted: bool) -> list[Line]:
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
        out += [service_line(u, st(u)) for u in SERVICES]
        out += [timer_line(u, st(u), True) for u in TIMERS]
        for job in ("paperbot-daily3.service", "paperbot-backup.service"):
            if st(job).get("Result") not in (None, "", "success"):
                out.append(fix(f"{_short(job)}의 지난 실행이 실패했습니다({st(job).get('Result')}): "
                               f"journalctl -u {_short(job)} -n 50"))
        cp = st("paperbot-checkpoint.service")
        if cp.get("Result") not in (None, "", "success"):
            out.append(note("paperbot-checkpoint의 지난 실행이 실패했습니다: 봇이 paper3.db를 만들기 전 한 번은 괜찮습니다. "
                            "계속되면 journalctl -u paperbot-checkpoint -n 50"))
    for u in AGENT_TIMERS:
        if stage == "after" and agents_wanted:
            out.append(timer_line(u, st(u), True))
        elif _enabled(st(u)):
            out.append(ok(f"{u}: 켜짐"))
        else:
            out.append(note(f"{u}: 꺼져 있음 (에이전트 방: Claude 로그인·5년 자료·드라이런을 마친 뒤 "
                            "sudo systemctl enable --now paperbot-agents.timer paperbot-labmonthly.timer)"))
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
    rc, _, _ = ctx.run([ctx.venv_python, "-c", "import paperbot"], None, 30.0, "/")
    if rc != 0:
        out.append(note("`python -m paperbot…` 명령은 다른 폴더에서는 안 됩니다(No module named 'paperbot'): "
                        "문서의 명령 앞에 `cd /opt/crypto-bot-research &&`를 붙이세요"))
    return out


def check_data_dir(ctx: Ctx) -> list[Line]:
    """/var/lib/paperbot and the backups belong to paperbot; a root-owned file in them (a command run with
    sudo but without -u paperbot) stops the services that must write it."""
    out: list[Line] = []
    for path in (ctx.lib, ctx.backups):
        info = ctx.stat(path)
        if info is None:
            out.append(fix(f"{path} 폴더가 없습니다: {INSTALL}"))
        elif (info.owner, info.group) != (ctx.user, ctx.user):
            out.append(fix(f"{path} 주인이 {info.owner}:{info.group}입니다: sudo chown {ctx.user}:{ctx.user} {path}"))
    foreign = []
    for d in (ctx.lib, os.path.join(ctx.lib, "exec"), os.path.join(ctx.lib, "lab")):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            info = ctx.stat(p)
            if info is not None and info.owner != ctx.user:
                foreign.append(p)
    if foreign:
        more = f" 외 {len(foreign) - 5}개" if len(foreign) > 5 else ""
        out.append(fix(f"{ctx.user}가 아닌 사용자 소유 파일이 있어 서비스가 쓰지 못합니다: {', '.join(foreign[:5])}{more} → "
                       f"sudo chown -R {ctx.user}:{ctx.user} <그 파일>"))
    elif not out:
        out.append(ok(f"데이터 폴더 주인 {ctx.user} (다른 사용자 소유 파일 없음)"))
    return out


def read_paper_db(path: str) -> dict:
    """Run start, heartbeat and the last start's record from paper3.db, opened read-only."""
    conn = sqlite3.connect(f"file:{urllib.parse.quote(path)}?mode=ro", uri=True, timeout=5.0)
    try:
        conn.execute("PRAGMA query_only = 1")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        one = lambda q: (conn.execute(q).fetchone() or (None,))[0]          # noqa: E731
        start = None
        if "accounts" in tables:
            start = one("SELECT MIN(created_ts) FROM accounts WHERE kind IN ('strategy', 'random')")
        if start is None and "runs" in tables:
            start = one("SELECT MIN(started_ts) FROM runs")
        hb = run = None
        if "state" in tables:
            hb = one("SELECT ts FROM state WHERE k = 'heartbeat'")
            raw = one("SELECT data FROM state WHERE k = 'run'")
            run = json.loads(raw) if raw else None
        return {"start": None if start is None else int(start), "heartbeat": None if hb is None else int(hb),
                "run": run if isinstance(run, dict) else None}
    finally:
        conn.close()


def paper_start(ctx: Ctx) -> Optional[int]:
    path = os.path.join(ctx.lib, "paper3.db")
    try:
        return read_paper_db(path)["start"] if ctx.stat(path) is not None else None
    except (sqlite3.Error, OSError, ValueError):
        return None


def check_paper_db(ctx: Ctx, stage: str) -> list[Line]:
    path = os.path.join(ctx.lib, "paper3.db")
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
                    "관찰 기간이 그날부터 셉니다. 시험으로 돌린 것이면 새로 시작하기 전에 옮기세요: "
                    "sudo systemctl stop paperbot-live3 && sudo mkdir -p /var/backups/paperbot/old && "
                    "sudo mv /var/lib/paperbot/paper3.db* /var/lib/paperbot/daily3.db* "
                    "/var/lib/paperbot/checkpoint.db* /var/backups/paperbot/old/ . "
                    "이어서 돌리는 것이면 --stage after로 확인하세요")]
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
    run = db["run"]
    if run:
        src = str(run.get("brackets") or "")
        fee = run.get("taker_fee")
        if "EXAMPLE" in src:
            out.append(fix("봇이 예시 레버리지 구간으로 돌고 있습니다(거래소 값 아님): 읽기 전용 키를 넣고 "
                           "sudo systemctl restart paperbot-live3"))
        else:
            out.append(ok(f"계좌 {run.get('accounts', '?')}개, 레버리지 구간: 거래소 실제 값"
                          + (f", taker 수수료 {float(fee):.4%}" if fee is not None else "")
                          + (", 재시작 뒤 이어서 돌림" if run.get("restored") else "")))
        ver = installed_version(ctx) or {}
        if run.get("commit") and ver.get("commit") and run["commit"] != ver["commit"]:
            out.append(note(f"봇이 설치된 코드({str(ver['commit'])[:10]})가 아닌 {str(run['commit'])[:10]}로 돌고 있습니다: "
                            "sudo systemctl restart paperbot-live3"))
    if start is not None:
        out.append(ok(f"첫 시작 {kst_text(start)}(한국 시간)"))
    return out


# ---------------------------------------------------------------- agent rooms
def agents_configured(agents: EnvFile, states: Optional[dict]) -> bool:
    timer = ((states or {}).get("paperbot-agents.timer") or {})
    return bool(agents.get("CLAUDE_CODE_OAUTH_TOKEN")) or _enabled(timer)


def check_lab(ctx: Ctx, states: Optional[dict], agents_wanted: bool, ref: Optional[dict] = None) -> list[Line]:
    """The 5-year lab caches against the research digests, like ``labdata check`` but without writing
    its manifest (this check may run as root and must not leave a root-owned file in the lab folder)."""
    level = fix if agents_wanted else note
    lab = os.path.join(ctx.lib, "lab")
    if ((states or {}).get(LABBUILD) or {}).get("ActiveState") in ("active", "activating"):
        return [note("5년 시험 자료를 지금 만드는 중입니다(paperbot-labbuild): journalctl -fu paperbot-labbuild, "
                     "끝난 뒤 다시 확인하세요")]
    info = ctx.stat(lab)
    if info is None:
        return [level(f"5년 시험 자료 폴더가 없습니다(에이전트 방에 필요). 30~60분 걸립니다: {LAB_BUILD}")]
    out: list[Line] = []
    if info.owner != ctx.user:
        out.append(fix(f"{lab} 주인이 {info.owner}입니다: sudo chown -R {ctx.user}:{ctx.user} {lab}"))
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
    if ctx.stat(claude) is None:
        return [level(f"Claude Code가 {ctx.user} 사용자에게 설치되지 않았습니다(에이전트 방에 필요): {CLAUDE_INSTALL}")]
    if ctx.euid == 0:
        prefix = [RUNUSER, "-u", ctx.user, "--"]     # keeps the environment below; HOME becomes paperbot's
    elif ctx.username == ctx.user:
        prefix = []
    else:
        return [note(f"Claude Code 로그인은 root나 {ctx.user}로 실행할 때만 확인합니다")]
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
        return [ok(f"Claude Code 로그인: 구독으로 로그인됨 ({why or '?'}), API 키 아님")]
    return [level(f"Claude Code 로그인 확인 실패: {why}. {claude_hint(why)}")]


def check_agents_policy(ctx: Ctx, agents: EnvFile, agents_wanted: bool, run_start: Optional[int]) -> list[Line]:
    """agents.env's AGENTS_* settings through the tick's own parser, its budget warnings, and the
    observation period (no copy proposals) they give."""
    level = fix if agents_wanted else note
    from .agents.rooms import OBSERVE_DAYS_DEFAULT, budget_warnings, policy_from_env
    try:
        p = policy_from_env(dict(agents.values))
    except ValueError as exc:
        return [level(f"agents.env 값이 잘못됐습니다: {exc}. 이대로면 에이전트 회의가 시작하지 않습니다")]
    out = [ok(f"agents.env 설정 읽힘: AI 하루 최대 {p.total_budget[0]}회·{p.total_budget[1]:,} 토큰, "
              f"7일 {p.week_budget[0]}회·{p.week_budget[1]:,} 토큰")]
    out += [note(f"예산 경고(그 회의는 열리지 못함): {w}") for w in budget_warnings(p)]
    if p.observe_until:
        if p.observe_until < kst_day(ctx.now_ms()):
            out.append(note(f"관찰 기간: AGENTS_OBSERVE_UNTIL={p.observe_until}가 이미 지났습니다 → 관찰 기간 없이 복사 "
                            "제안이 나올 수 있습니다"))
        else:
            out.append(ok(f"관찰 기간: {p.observe_until}(한국 날짜)까지 복사 제안 없음"))
    elif p.observe_days <= 0:
        out.append(note(f"관찰 기간 꺼짐(AGENTS_OBSERVE_DAYS=0): 첫날부터 복사 제안이 나올 수 있습니다 "
                        f"(정한 값은 {OBSERVE_DAYS_DEFAULT}일)"))
    else:
        until = (f", {kst_day(run_start + p.observe_days * DAY_MS - 1)}까지" if run_start is not None else "")
        text = f"관찰 기간: 봇 첫 시작부터 {p.observe_days}일{until} 복사 제안 없음"
        out.append(ok(text) if p.observe_days == OBSERVE_DAYS_DEFAULT else
                   note(f"{text} (정한 값 {OBSERVE_DAYS_DEFAULT}일과 다름)"))
    return out


# ---------------------------------------------------------------- run and report
def guard(fn: Callable[..., list], *args, **kw) -> list[Line]:
    """A check that breaks is reported as one [고칠 것] line; the other checks still run."""
    try:
        return list(fn(*args, **kw))
    except Exception as exc:  # noqa: BLE001
        return [fix(f"이 점검이 오류로 멈췄습니다: {type(exc).__name__}: {exc}"[:300])]


def run_checks(ctx: Ctx, stage: str = "before", send_test: bool = False, ping: bool = False,
               agents: str = "auto", skip_lab: bool = False) -> tuple[list[tuple[str, list[Line]]], list[str]]:
    """[(section title, lines)] and the secret values to scrub from them."""
    envs = read_envs(ctx)
    states = guard(lambda: [unit_states(ctx)])[0]
    states = states if isinstance(states, dict) or states is None else None
    wanted = agents == "yes" or (agents == "auto" and agents_configured(envs["agents"], states))
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
        ("서비스", guard(check_units, states, stage, wanted)),
        ("데이터", guard(check_data_dir, ctx) + guard(check_paper_db, ctx, stage)),
    ]
    if agents == "no":
        sections.append(("에이전트 방", [note("점검 건너뜀 (--agents no)")]))
    else:
        head = [] if wanted else [note("에이전트 방은 아직 설정하지 않았습니다(선택). 아래 줄은 참고만 합니다: 켤 때는 "
                                       "--agents yes로 다시 확인하세요")]
        lab = ([note("5년 시험 자료 확인 건너뜀 (--skip-lab)")] if skip_lab else guard(check_lab, ctx, states, wanted))
        sections.append(("에이전트 방", head + guard(check_claude, ctx, ag, wanted)
                         + guard(check_agents_policy, ctx, ag, wanted, paper_start(ctx)) + lab))
    return sections, secret_values(envs)


def report(sections: list[tuple[str, list[Line]]], stage: str, secrets: Sequence[str] = (),
           out: Callable[[str], None] = print) -> int:
    """Prints every line (scrubbed) and the verdict; returns the exit code (0 = nothing to fix)."""
    n_fix = n_note = 0
    for title, lines in sections:
        out(f"== {title}")
        for status, text in lines:
            out(f"[{status}] {scrub(text, secrets)}")
            n_fix += status == FIX
            n_note += status == NOTE
    out("== 결론")
    if n_fix:
        out(f"[{FIX}] 고칠 것 {n_fix}개, 참고 {n_note}개: 위의 [{FIX}] 줄을 고친 뒤 이 점검을 다시 돌리세요."
            + (" 아직 시작하지 마세요." if stage == "before" else ""))
        return 1
    if stage == "before":
        out(f"[{OK}] 시작 준비가 끝났습니다 (참고 {n_note}개). 시작: {START_CMD}")
        out(f"     시작하고 5분쯤 뒤 확인: {AFTER_CMD}")
    else:
        out(f"[{OK}] 봇이 정상으로 돌고 있습니다 (참고 {n_note}개). healthchecks.io가 'up'인지, 텔레그램에 "
            "'paper v3 started'가 왔는지 눈으로도 보세요.")
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
    args = ap.parse_args(argv)
    ctx = ctx or Ctx()
    out(f"paperbot 시작 점검 ({'시작 전' if args.stage == 'before' else '시작 후'}): "
        f"{kst_text(ctx.now_ms())} 한국 시간, 실행 사용자 {ctx.username}")
    sections, secrets = run_checks(ctx, args.stage, args.send_test, args.ping, args.agents, args.skip_lab)
    return report(sections, args.stage, secrets, out)


if __name__ == "__main__":
    sys.exit(main())
