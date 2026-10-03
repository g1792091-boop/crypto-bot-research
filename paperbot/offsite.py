"""Off-site copy of the nightly database backup to a private Telegram chat (docs/offsite-backup.md).

    python -m paperbot.offsite send    --from /var/backups/paperbot --chat-env TELEGRAM_CHAT_BACKUP
    python -m paperbot.offsite restore --parts DOWNLOADS/restore-in --out DIR   # a folder, or the files
    python -m paperbot.offsite chats   # chat ids the bot has seen (to find the backup group's id)
    python -m paperbot.offsite stopped # ExecStopPost: WARN when systemd killed a send before it could alert

The owners run one Vultr server without Vultr's automatic backups. deploy/paperbot-backup.sh writes
consistent copies of the databases into /var/backups/paperbot/<YYYYMMDD>/ every night (23:40 UTC,
08:40 KST; the folder is named by the UTC date); if the server is lost, those copies are lost with it.

send: takes the newest backup folder (today's UTC date, else yesterday's: the 23:40 UTC run's folder
is "yesterday" once the clock has passed midnight UTC) and checks it: a copy still being written, a
database that exists on the server without a copy, or a copy that is not an SQLite file is a problem.
Every good copy is still sent (the small databases are the most valuable), then the problems fail the
run. It packs the copies as tar + zstd (gzip when the zstd program is missing), encrypts the stream
with the openssl program when BACKUP_PASSPHRASE is set (no homemade cryptography: without openssl it
refuses and sends nothing; only one archive is ever on disk), splits it into parts below Telegram's
50 MB document limit and uploads each part with sendDocument (urllib, multipart/form-data), then a
manifest (part names, sizes, sha256s) with a short Korean summary as its caption. Network errors, 5xx
and 429 (retry_after) are retried with backoff, within one time limit for the whole run (RUN_LIMIT_S,
below the unit's TimeoutStartSec). Any failure sends a Korean WARN through the normal notifier and
exits 1, so paperbot-offsite.service fails visibly; so does a SIGTERM (unit timeout, reboot, stop).
A run that systemd kills outright (memory limit, SIGKILL) is reported by `stopped` (ExecStopPost).

restore: takes the downloaded files or a folder holding them, matches the parts to the manifest by
sha256 (file names may change on download), joins them, checks the whole archive's sha256, decrypts,
unpacks (plain files only, no paths outside the output folder) and runs PRAGMA integrity_check on
every database; prints the next steps in Korean.

Reads only the backup folder, and the live database paths (existence only, for the completeness
check); writes only its temporary folder (send) or --out (restore). It is not a writer of any database.
The bot token is in every request URL: every error and log line goes through redact(). The zstd and
openssl programs get a minimal environment (PATH; openssl also the passphrase), never the token.
"""

from __future__ import annotations

import argparse
import getpass
import gzip
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import IO, Callable, Mapping, Optional, Sequence

from .notify import WARN, ConsoleNotifier, Notifier, TelegramNotifier

API = "https://api.telegram.org"
# the databases deploy/paperbot-backup.sh copies (keep the two lists the same: tests/test_offsite.py
# compares them); a copy is <basename>.db
DB_NAMES = ("agents3", "inbox", "liq", "checkpoint", "exec/executor", "exec/executor-testnet", "daily3", "paper3")
TELEGRAM_UPLOAD_LIMIT = 50_000_000      # Bot API: documents up to 50 MB (read as decimal MB, the stricter)
MULTIPART_ROOM = 1_000_000              # form fields, caption and boundaries around the file
MAX_PART = TELEGRAM_UPLOAD_LIMIT - MULTIPART_ROOM
DEFAULT_PART = 45 * 1024 * 1024         # 47.2 MB
CAPTION_LIMIT = 1024
SQLITE_HEADER = b"SQLite format 3\x00"
MANIFEST_FORMAT = "paperbot-offsite/1"
BACKOFF = (5, 15, 45, 120, 300)         # seconds before retry 1..5 (6 attempts in all)
MAX_RETRY_AFTER = 900                   # a longer 429 wait fails at once (any wait also has to fit RUN_LIMIT_S)
UPLOAD_TIMEOUT = 300.0                  # urllib: each of connect, send and the answer (an attempt: up to 3x)
# One send stops itself (Korean WARN, exit 1) after this long: deploy/paperbot-offsite.service gives it
# TimeoutStartSec=60min, so the retries never run into systemd's SIGTERM (which also ends in a WARN).
RUN_LIMIT_S = 50 * 60
MIN_ATTEMPT_S = 30.0                    # an upload attempt with less time than this left is not started
# Free space the job always leaves on the disk it shares with the live databases (live3 commits every 5 s)
FREE_FLOOR = 2 * 1024 ** 3
FREE_FLOOR_SHARE = 10                   # ... or 1/10 of the disk, whichever is larger
OPENSSL_ENC = ("enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-salt")
CIPHER = "openssl " + " ".join(OPENSSL_ENC)
KST = timezone(timedelta(hours=9))
PART_RE = re.compile(r"^(?P<base>.+)\.part(?P<i>\d+)-of-(?P<n>\d+)$")
_TOKEN_RE = re.compile(r"\d{5,}(?::|%3A)[A-Za-z0-9_-]{20,}", re.IGNORECASE)

Sender = Callable[[str, bytes, dict, float], tuple]   # (url, body, headers, timeout) -> (status, body bytes)


class OffsiteError(Exception):
    """A failure explained for the owners (Korean); the message never holds the bot token."""


class TelegramError(OffsiteError):
    pass


class UnpackError(OffsiteError):
    """The archive could not be decompressed or read as tar (after its sha256 matched)."""


def redact(text, token: Optional[str] = None, *others: str) -> str:
    """The text with the bot token (exact value, and anything shaped like a bot token) and any other
    secret given (the backup passphrase) replaced."""
    s = str(text)
    for secret, label in [(token, "<token>")] + [(o, "<secret>") for o in others]:
        for t in {secret or "", (secret or "").strip()}:
            if len(t) >= 8:
                s = s.replace(t, label)
                s = s.replace(urllib.parse.quote(t, safe=""), label)
    return _TOKEN_RE.sub("<token>", s)


def _child_env(**extra: str) -> dict:
    """The environment of a zstd/openssl child: PATH only (plus ``extra``), never the token or other keys."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **extra}


def free_floor(total: int) -> int:
    return max(FREE_FLOOR, total // FREE_FLOOR_SHARE)


def check_space(where: Path, need: int, what: str) -> None:
    """OffsiteError unless ``need`` bytes fit on ``where``'s disk with free_floor() still left over."""
    du = shutil.disk_usage(where)
    floor = free_floor(du.total)
    if du.free - need < floor:
        raise OffsiteError(f"디스크 여유가 모자랍니다: {where}에 {fmt_size(du.free)} 남음. {what}에 최대 "
                           f"{fmt_size(need)}가 필요하고, 돌고 있는 봇을 위해 {fmt_size(floor)}는 늘 남겨 둡니다 "
                           "(df -h 로 확인, 오래된 파일 정리)")


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def fmt_size(n: float) -> str:
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- Telegram (urllib only)
def urllib_sender(url: str, body: bytes, headers: dict, timeout: float) -> tuple:
    """POST; returns (status, body). Network errors raise (OSError and subclasses, HTTPException)."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:      # a 4xx/5xx answer is an answer, not a network error
        try:
            data = e.read()
        except Exception:
            data = b""
        return e.code, data


def multipart(fields: Mapping[str, str], file: Optional[tuple] = None) -> tuple[bytes, str]:
    """multipart/form-data body and its Content-Type. ``file`` = (field, filename, bytes)."""
    if not fields and file is None:
        raise ValueError("an empty multipart form is refused by Telegram (HTTP 400): send at least one field")
    boundary = "paperbot-" + secrets.token_hex(16)
    out: list[bytes] = []
    for k, v in fields.items():
        out += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode(),
                str(v).encode("utf-8"), b"\r\n"]
    if file is not None:
        field, filename, data = file
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "file"
        out += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{safe}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n".encode(), data, b"\r\n"]
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def _hint(status: int, desc: str, params: dict) -> str:
    d = desc.lower()
    if params.get("migrate_to_chat_id"):
        return (f" — 단체방이 슈퍼그룹으로 바뀌어 방 번호가 {params['migrate_to_chat_id']}(으)로 바뀌었습니다. "
                "/etc/paperbot/live.env의 방 번호를 고치세요")
    if status == 401:
        return " — 봇 토큰(TELEGRAM_BOT_TOKEN)이 틀렸습니다"
    if "chat not found" in d:
        return " — 방 번호가 틀렸거나 봇이 그 단체방에 없습니다"
    if status == 403:
        return " — 봇이 그 단체방에서 내보내졌거나 막혔습니다. 봇을 다시 넣으세요"
    if status == 413 or "too large" in d:
        return " — 파일 조각이 텔레그램 한도(50 MB)보다 큽니다"
    return ""


class Telegram:
    """Bot API calls with retries. The token is only in the URL; nothing this class prints or raises
    contains it."""

    def __init__(self, token: str, sender: Optional[Sender] = None, sleep: Callable[[float], None] = time.sleep,
                 timeout: float = UPLOAD_TIMEOUT, backoff: Sequence[float] = BACKOFF,
                 log: Callable[[str], None] = _stderr, deadline: Optional[float] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.token = token
        self.sender = sender or urllib_sender
        self.sleep = sleep
        self.timeout = timeout
        self.backoff = tuple(backoff)
        self.log = log
        self.deadline = deadline        # clock() value after which nothing new is started (None: no limit)
        self.clock = clock

    def _left(self) -> Optional[float]:
        return None if self.deadline is None else self.deadline - self.clock()

    def _out_of_time(self, method: str, problem: str) -> TelegramError:
        last = f"; 마지막 문제: {problem}" if problem else ""
        return TelegramError(redact(f"텔레그램 {method}: 이번 실행의 시간 제한에 걸려 그만둡니다 "
                                    f"(업로드가 너무 느리거나 조각이 너무 많음{last})", self.token))

    def call(self, method: str, fields: Mapping[str, str], file: Optional[tuple] = None):
        body, ctype = multipart(fields, file)
        url = f"{API}/bot{self.token}/{method}"
        headers = {"Content-Type": ctype, "Content-Length": str(len(body))}
        attempts = len(self.backoff) + 1
        problem = ""
        for attempt in range(1, attempts + 1):
            wait = float(self.backoff[attempt - 1]) if attempt <= len(self.backoff) else 0.0
            timeout = self.timeout
            left = self._left()
            if left is not None:
                # urllib's timeout bounds connect, the upload and the answer one by one: 3 of them must fit
                timeout = min(timeout, left / 3)
                if timeout < MIN_ATTEMPT_S:
                    raise self._out_of_time(method, problem)
            try:
                status, raw = self.sender(url, body, headers, timeout)
            except (OSError, http.client.HTTPException) as exc:     # timeouts, resets, DNS, TLS
                problem = f"network {type(exc).__name__}: {exc}"
            else:
                try:
                    data = json.loads(raw or b"{}")
                except ValueError:
                    data = {}
                data = data if isinstance(data, dict) else {}
                if status == 200 and data.get("ok"):
                    return data.get("result")
                desc = str(data.get("description") or (raw or b"")[:200])
                params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
                problem = f"HTTP {status}: {desc}"
                if status == 429:
                    after = params.get("retry_after")
                    if isinstance(after, (int, float)) and after > 0:
                        if after > MAX_RETRY_AFTER:
                            raise TelegramError(redact(
                                f"텔레그램이 {after:.0f}초 기다리라고 합니다(너무 김, {problem})", self.token))
                        wait = float(after) + 1.0
                elif status < 500:
                    raise TelegramError(redact(f"텔레그램이 {method} 요청을 거절했습니다 ({problem})"
                                               f"{_hint(status, desc, params)}", self.token))
            if attempt == attempts:
                raise TelegramError(redact(f"텔레그램 {method}: {attempts}번 모두 실패 ({problem})", self.token))
            left = self._left()
            if left is not None and wait + 3 * MIN_ATTEMPT_S > left:
                raise self._out_of_time(method, problem)
            self.log(redact(f"telegram {method}: {problem}; retry {attempt}/{attempts - 1} in {wait:.0f} s",
                            self.token))
            self.sleep(wait)
        raise AssertionError("unreachable")


# ---------------------------------------------------------------- the backup folder
def find_folder(root: Path, date: Optional[str], now: datetime) -> Path:
    if not root.is_dir():
        raise OffsiteError(f"백업 폴더({root})가 없습니다 (서버 안 백업 paperbot-backup이 한 번도 돌지 않음?)")
    if date:
        if not re.fullmatch(r"\d{8}", date):
            raise OffsiteError(f"--date는 YYYYMMDD 모양이어야 합니다: {date!r}")
        wanted = [date]
    else:
        today = now.astimezone(timezone.utc).date()
        wanted = [today.strftime("%Y%m%d"), (today - timedelta(days=1)).strftime("%Y%m%d")]
    for d in wanted:
        if (root / d).is_dir():
            return root / d
    have = sorted(p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d{8}", p.name))
    raise OffsiteError(f"오늘 백업 폴더가 없습니다 ({root}/{' 또는 '.join(wanted)}; 가장 최근: "
                       f"{have[-1] if have else '없음'}). 서버 안 백업이 실패했는지 봅니다: "
                       "systemctl status paperbot-backup")


UNFINISHED = "백업이 끝나지 않았습니다"
MISSING = "백업이 빠졌습니다"
NOT_SQLITE = "백업 파일이 SQLite 파일이 아닙니다"


def problems_text(problems: Sequence[tuple[str, str]]) -> str:
    """'백업이 빠졌습니다: paper3.db; …' from check_folder's (kind, file name) list."""
    kinds: dict[str, list[str]] = {}
    for kind, name in problems:
        kinds.setdefault(kind, []).append(name)
    return "; ".join(f"{k}: {', '.join(v)}" for k, v in kinds.items())


def check_folder(folder: Path, lib: Optional[Path], wait_s: float = 0.0,
                 sleep: Callable[[float], None] = time.sleep, poll_s: float = 30.0,
                 log: Callable[[str], None] = _stderr) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """({file name: bytes} of the folder's good database copies, [(problem, file name)]).

    Problems: a copy still being written after ``wait_s`` (<name>.db.part: the backup is running or
    was killed), a copy that is not an SQLite file (left out), a database that exists in ``lib``
    without a good copy. The good copies are still sent: one failed paper3 copy must not keep the
    small, most valuable databases off-site. OffsiteError only when there is no good copy at all."""
    waited = 0.0
    while True:
        parts = sorted(p.name for p in folder.glob("*.part"))
        if not parts or waited >= wait_s:
            break
        log(f"backup still writing {', '.join(parts)}; waiting")
        sleep(poll_s)
        waited += poll_s
    problems = [(UNFINISHED, p) for p in parts]
    files = {}
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name.endswith(".db"):
            with open(p, "rb") as fh:
                if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                    problems.append((NOT_SQLITE, p.name))
                    continue
            files[p.name] = p.stat().st_size
    if lib is not None and lib.is_dir():
        for f in DB_NAMES:
            base = f.rsplit("/", 1)[-1] + ".db"
            if (lib / f"{f}.db").exists() and base not in files:
                problems.append((MISSING, base))
    elif lib is not None:
        log(f"note: {lib} not found; checked the folder only")
    if not files and not problems:
        raise OffsiteError(f"백업 폴더({folder})가 비어 있습니다 (봇을 켜기 전이거나 복사가 모두 실패)")
    if not files:
        raise OffsiteError(f"백업 폴더({folder})에 보낼 만한 DB 복사본이 없습니다: {problems_text(problems)} "
                           "(systemctl status paperbot-backup --no-pager)")
    return files, problems


# ---------------------------------------------------------------- pack, encrypt, split
@dataclass
class Archive:
    path: Path
    name: str
    size: int
    sha256: str
    compression: str
    encrypted: bool
    members: dict           # {file name: bytes archived}
    newest_mtime: float     # of the archived copies


def _tar_clean(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    ti.mode = 0o640
    return ti


def choose_compression(compression: str, which: Callable[[str], Optional[str]],
                       log: Callable[[str], None] = _stderr) -> str:
    if compression == "gzip":
        return "gzip"
    if which("zstd"):
        return "zstd"
    if compression == "zstd":
        raise OffsiteError("zstd 프로그램이 없습니다 (sudo apt install zstd, 또는 --compress gzip)")
    log("note: zstd not installed; using gzip (sudo apt install zstd)")
    return "gzip"


def pack(folder: Path, files: Sequence[str], work: Path, compression: str, passphrase: str = "",
         which: Callable[[str], Optional[str]] = shutil.which, log: Callable[[str], None] = _stderr) -> Archive:
    """tar of the copies -> zstd (or gzip) -> openssl (with a passphrase) -> one file in ``work``.

    The stages are one pipe, so only the final archive is ever on disk (the disk is shared with the
    live databases). Each copy is opened once and archived from that open file with its own fstat
    size: a copy that paperbot-backup.sh replaces meanwhile (atomic rename) is archived whole (the old
    one), never cut to a stale size."""
    date = folder.name
    comp = choose_compression(compression, which, log)
    name = f"paperbot-{date}.tar." + ("zst" if comp == "zstd" else "gz") + (".enc" if passphrase else "")
    path = work / name
    members: dict[str, int] = {}
    newest = 0.0
    stages: list[tuple[str, subprocess.Popen, IO[bytes]]] = []

    def spawn(what: str, argv: list, stdout, env: dict) -> IO[bytes]:
        err = tempfile.TemporaryFile(dir=str(work))          # a file, not a pipe: no deadlock on stderr
        try:
            p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout, stderr=err, env=env)
        except BaseException:
            err.close()
            raise
        stages.append((what, p, err))
        return p.stdin

    final = open(path, "wb")
    try:
        sink: IO[bytes] = final
        if passphrase:
            exe = which("openssl")
            if not exe:
                raise OffsiteError("openssl 프로그램이 없어 암호화할 수 없습니다 (sudo apt install openssl)")
            # the passphrase reaches openssl through its environment, never its command line (ps shows that)
            sink = spawn("openssl 암호화", [exe, *OPENSSL_ENC, "-pass", "env:BACKUP_PASSPHRASE"], final,
                         _child_env(BACKUP_PASSPHRASE=passphrase))
        if comp == "zstd":
            upstream = sink
            sink = spawn("zstd 압축", [which("zstd") or "zstd", "-q", "-T2", "-10", "-c"], upstream, _child_env())
            if upstream is not final:
                upstream.close()          # zstd holds openssl's input now; openssl ends when zstd does
        broken = False
        try:
            gz = gzip.GzipFile(filename="", fileobj=sink, mode="wb", compresslevel=6, mtime=0) \
                if comp == "gzip" else None
            with tarfile.open(fileobj=gz or sink, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for f in files:
                    with open(folder / f, "rb") as fh:
                        ti = _tar_clean(tar.gettarinfo(arcname=f"{date}/{f}", fileobj=fh))
                        tar.addfile(ti, fh)
                    members[f] = ti.size
                    newest = max(newest, float(ti.mtime))
            if gz is not None:
                gz.close()                # the gzip trailer; the sink itself stays open
        except BrokenPipeError:           # a stage stopped reading: never a whole archive
            broken = True
        finally:
            if sink is not final:
                try:
                    sink.close()
                except BrokenPipeError:
                    broken = True
        failures = []
        for what, p, err in reversed(stages):             # the stage next to tar first
            rc = p.wait()
            if rc != 0:
                err.seek(0)
                failures.append(f"{what} 실패 (exit {rc}): {err.read().decode(errors='replace').strip()[-300:]}")
        if failures or broken:
            raise OffsiteError("; ".join(failures) or "압축 중 파이프가 끊겼습니다")
    except BaseException:
        for _, p, _ in stages:
            if p.poll() is None:
                p.kill()
                p.wait()
        raise
    finally:
        final.close()
        for _, _, err in stages:
            err.close()
    return Archive(path, name, path.stat().st_size, sha256_file(path), comp, bool(passphrase), members, newest)


def openssl_run(args: Sequence[str], passphrase: str, which: Callable[[str], Optional[str]], what: str) -> None:
    exe = which("openssl")
    if not exe:
        raise OffsiteError(f"openssl 프로그램이 없어 {what}할 수 없습니다 (sudo apt install openssl)")
    # the passphrase reaches openssl through its environment, never its command line (ps shows that)
    env = _child_env(BACKUP_PASSPHRASE=passphrase)
    r = subprocess.run([exe, *args], env=env, capture_output=True)
    if r.returncode != 0:
        tail = r.stderr.decode(errors="replace").strip()[-300:]
        if what == "복호화" and "bad decrypt" in tail.lower():
            raise OffsiteError("복호화 실패: 암호(BACKUP_PASSPHRASE)가 틀렸거나 파일이 손상되었습니다")
        raise OffsiteError(f"openssl {what} 실패 (exit {r.returncode}): {tail}")


def plan_parts(size: int, part_size: int) -> list[tuple[int, int]]:
    """(offset, length) of each part: every part ``part_size`` bytes except a shorter last one."""
    if part_size <= 0:
        raise ValueError("part_size must be positive")
    return [(off, min(part_size, size - off)) for off in range(0, size, part_size)]


def part_name(archive: str, i: int, n: int) -> str:
    w = max(2, len(str(n)))
    return f"{archive}.part{i:0{w}d}-of-{n:0{w}d}"


def _kst(ts: float) -> str:
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d %H:%M")


def part_caption(m: dict, p: dict) -> str:
    enc = "암호화 openssl aes-256-cbc" if m["encrypted"] else "암호화 없음"
    return "\n".join([
        f"paperbot 백업 {m['date']} · 조각 {p['index']}/{p['of']}",
        f"파일 {p['name']}",
        f"조각 {fmt_size(p['size'])} ({p['size']} B) · sha256 {p['sha256']}",
        f"전체 {fmt_size(m['size'])} ({m['size']} B) · sha256 {m['sha256']}",
        f"DB 원본 {fmt_size(sum(m['databases'].values()))} · {m['compression']} · {enc}",
        f"백업 시각 {m['backup_kst']} (한국)",
    ])[:CAPTION_LIMIT]


def summary_text(m: dict, note: str = "", dry_run: bool = False) -> str:
    dbs = " · ".join(f"{k.removesuffix('.db')} {fmt_size(v)}" for k, v in m["databases"].items())
    enc = "암호화함" if m["encrypted"] else "암호화 없음"
    problems = m.get("problems") or []
    if dry_run:
        head = f"paperbot 서버 밖 백업 시험(dry run): 아무것도 보내지 않음 — {m['date']} 폴더"
    elif problems:
        head = f"paperbot 서버 밖 백업 일부만 보냄: {m['date']} 폴더"
    else:
        head = f"paperbot 서버 밖 백업 완료: {m['date']} 폴더"
    lines = [
        f"{head} (백업 시각 {m['backup_kst']} 한국)",
        f"DB {len(m['databases'])}개 {fmt_size(sum(m['databases'].values()))} → {'보낼' if dry_run else '보낸'} 파일 "
        f"{fmt_size(m['size'])} ({m['compression']}, {enc}), 조각 {len(m['parts'])}개",
        f"DB: {dbs}",
    ]
    if problems:
        lines.append(f"빠진 것: {'; '.join(problems)} (알림방 경고 참고)")
    lines += [
        f"전체 sha256 {m['sha256'][:16]}…",
        f"되살릴 때: 이 목록 파일과 조각 {len(m['parts'])}개를 모두 내려받습니다 (docs/offsite-backup.md)",
    ]
    if note:
        lines.append(note)
    return "\n".join(lines)[:CAPTION_LIMIT]


def resolve_chat(env: Mapping[str, str], chat_env: str) -> tuple[str, str]:
    chat = (env.get(chat_env) or "").strip()
    if chat:
        return chat, ""
    critical = (env.get("TELEGRAM_CHAT_CRITICAL") or "").strip()
    if not critical:
        raise OffsiteError(f"보낼 방이 없습니다: {chat_env}, TELEGRAM_CHAT_CRITICAL 값이 모두 비어 있습니다 "
                           "(/etc/paperbot/live.env)")
    return critical, (f"참고: {chat_env} 값이 비어 있어 기본 알림방으로 보냈습니다. 백업 전용 단체방을 만들어 "
                      "넣어 주세요 (docs/offsite-backup.md)")


def check_token(token: str) -> None:
    if not token:
        raise OffsiteError("TELEGRAM_BOT_TOKEN이 비어 있습니다 (/etc/paperbot/live.env)")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise OffsiteError("TELEGRAM_BOT_TOKEN 모양이 이상합니다 (숫자:글자 모양이어야 함; 앞뒤 빈칸·따옴표 확인)")


def send_backup(root: Path, chat_env: str = "TELEGRAM_CHAT_BACKUP", *, date: Optional[str] = None,
                lib: Optional[Path] = None, part_size: int = DEFAULT_PART, compression: str = "auto",
                work: Optional[Path] = None, dry_run: bool = False, wait_s: float = 300.0,
                env: Optional[Mapping[str, str]] = None, sender: Optional[Sender] = None,
                sleep: Callable[[float], None] = time.sleep, now: Optional[datetime] = None,
                which: Callable[[str], Optional[str]] = shutil.which,
                log: Callable[[str], None] = _stderr, out: Callable[[str], None] = print,
                info: Optional[dict] = None, max_s: float = RUN_LIMIT_S,
                clock: Callable[[], float] = time.monotonic) -> dict:
    """Pack, split and upload one backup folder; returns the manifest. Raises OffsiteError, also after
    the upload when the folder had problems (check_folder): the good copies are sent, the run fails."""
    env = os.environ if env is None else env
    info = {} if info is None else info
    deadline = clock() + max_s
    if not 0 < part_size <= MAX_PART:
        raise OffsiteError(f"조각 크기 {part_size} B는 텔레그램 한도 안이어야 합니다 (최대 {MAX_PART} B, 기본 45 MB)")
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat, note = "", ""
    if not dry_run:
        check_token(token)
        chat, note = resolve_chat(env, chat_env)
        if note:
            log(redact(note, token))
    passphrase = env.get("BACKUP_PASSPHRASE") or ""
    if passphrase and not which("openssl"):
        raise OffsiteError("BACKUP_PASSPHRASE가 있는데 openssl 프로그램이 없습니다. 직접 만든 암호화는 쓰지 않으므로 "
                           "아무것도 보내지 않았습니다 (sudo apt install openssl, 또는 암호화 없이 보내려면 "
                           "BACKUP_PASSPHRASE를 비움)")
    folder = find_folder(Path(root), date, now or datetime.now(timezone.utc))
    info["date"] = folder.name
    files, problems = check_folder(folder, lib, wait_s, sleep, log=log)
    if problems:
        log(f"problems in {folder.name}: {problems_text(problems)}; sending the good copies")
    raw = sum(files.values())
    workdir = Path(tempfile.mkdtemp(prefix="paperbot-offsite-", dir=str(work) if work else None))
    try:
        # worst case: the copies do not compress at all (only one archive is ever on disk: see pack)
        check_space(workdir, raw + 1024 * 1024, "압축 파일")
        arc = pack(folder, list(files), workdir, compression, passphrase, which, log)
        plan = plan_parts(arc.size, part_size)
        manifest = {
            "format": MANIFEST_FORMAT, "date": folder.name, "backup_kst": _kst(arc.newest_mtime),
            "archive": arc.name, "compression": arc.compression, "encrypted": arc.encrypted,
            "cipher": CIPHER if arc.encrypted else None, "size": arc.size, "sha256": arc.sha256,
            "part_size": part_size, "parts": [], "databases": dict(arc.members),
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if problems:
            manifest["problems"] = [f"{k}: {n}" for k, n in problems]
        tg = None if dry_run else Telegram(token, sender, sleep, log=log, deadline=deadline, clock=clock)
        parts = []
        with open(arc.path, "rb") as fh:
            for i, (off, length) in enumerate(plan, 1):
                fh.seek(off)
                data = fh.read(length)
                p = {"index": i, "of": len(plan), "name": part_name(arc.name, i, len(plan)), "offset": off,
                     "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                caption = part_caption(manifest, p)
                if tg is not None:
                    tg.call("sendDocument", {"chat_id": chat, "caption": caption, "disable_notification": "true",
                                             "disable_content_type_detection": "true"},
                            ("document", p["name"], data))
                out(f"part {i}/{len(plan)} {p['name']} {p['size']} B sha256 {p['sha256']}"
                    + (" (dry run: not sent)" if tg is None else " sent"))
                parts.append({k: p[k] for k in ("index", "name", "offset", "size", "sha256")})
        manifest["parts"] = parts
        summary = summary_text(manifest, note, dry_run=dry_run)
        if tg is not None:
            tg.call("sendDocument", {"chat_id": chat, "caption": summary, "disable_notification": "true",
                                     "disable_content_type_detection": "true"},
                    ("document", f"paperbot-{folder.name}.manifest.json",
                     (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode()))
        out(summary)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if problems:
        sent = "dry run이라 보내지 않았습니다" if dry_run else "'paperbot 백업' 방에 보냈습니다"
        hint = (" (서버에는 있는데 폴더에 온전한 복사본이 없음. 오늘 새로 생긴 DB라면 다음 날 백업부터 들어갑니다)"
                if any(k == MISSING for k, _ in problems) else "")
        raise OffsiteError(f"{problems_text(problems)}{hint}. 나머지 DB {len(files)}개는 {sent}. "
                           "서버 안 백업을 확인합니다: systemctl status paperbot-backup --no-pager")
    return manifest


# ---------------------------------------------------------------- restore
def _load_manifest(path: Path) -> dict:
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OffsiteError(f"목록 파일을 읽을 수 없습니다: {path} ({type(exc).__name__})")
    if not isinstance(m, dict) or m.get("format") != MANIFEST_FORMAT or not isinstance(m.get("parts"), list):
        raise OffsiteError(f"paperbot 백업 목록 파일이 아닙니다: {path}")
    return m


def _order_by_manifest(m: dict, files: Sequence[Path], log: Callable[[str], None]) -> list[Path]:
    by_hash: dict[str, Path] = {}
    for f in files:
        by_hash.setdefault(sha256_file(f), f)
    ordered, missing = [], []
    for p in m["parts"]:
        f = by_hash.pop(p["sha256"], None)
        if f is None:
            missing.append(f"{p['index']}번({p['name']})")
        else:
            ordered.append(f)
    if missing:
        raise OffsiteError(f"조각 {len(m['parts'])}개 중 {', '.join(missing)}이 없거나 손상되었습니다 "
                           "(sha256이 맞는 파일 없음). 텔레그램에서 다시 내려받으세요")
    for f in by_hash.values():
        log(f"참고: 목록에 없는 파일은 쓰지 않습니다: {f}")
    return ordered


def _order_by_name(files: Sequence[Path]) -> tuple[list[Path], str]:
    groups: dict[tuple[str, int], dict[int, Path]] = {}
    for f in files:
        mt = PART_RE.match(f.name)
        if not mt:
            raise OffsiteError(f"조각 파일 이름이 아닙니다: {f.name} (….partNN-of-NN)")
        groups.setdefault((mt["base"], int(mt["n"])), {})[int(mt["i"])] = f
    if len(groups) != 1:
        raise OffsiteError("여러 날짜(또는 여러 묶음)의 조각이 섞였습니다. 한 날짜의 조각만 넣으세요")
    (base, n), got = next(iter(groups.items()))
    missing = [str(i) for i in range(1, n + 1) if i not in got]
    if missing:
        raise OffsiteError(f"조각 {n}개 중 {', '.join(missing)}번이 없습니다")
    return [got[i] for i in range(1, n + 1)], base


def _safe_member(m: tarfile.TarInfo) -> Optional[str]:
    """The file name to write for a tar member, None for a directory; OffsiteError for anything else."""
    p = PurePosixPath(m.name)
    if p.is_absolute() or ".." in p.parts or len(p.parts) > 2:
        raise OffsiteError(f"압축 파일 안에 이상한 경로가 있습니다: {m.name!r}")
    if m.isdir():
        return None
    if not m.isfile() or not re.fullmatch(r"[A-Za-z0-9._-]+\.db", p.name):
        raise OffsiteError(f"압축 파일 안에 데이터베이스가 아닌 항목이 있습니다: {m.name!r}")
    return p.name


def unpack(archive: Path, compression: str, dest: Path, which: Callable[[str], Optional[str]]) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    names: list[str] = []

    def extract(tar: tarfile.TarFile) -> None:
        for m in tar:
            name = _safe_member(m)
            if name is None:
                continue
            if name in names:
                raise OffsiteError(f"압축 파일 안에 같은 이름이 두 번 있습니다: {name}")
            src = tar.extractfile(m)
            target = dest / name
            with open(target, "wb") as fh:
                shutil.copyfileobj(src, fh, 1 << 20)
            os.chmod(target, 0o640)
            names.append(name)

    try:
        if compression == "zstd":
            exe = which("zstd")
            if not exe:
                raise OffsiteError("zstd 프로그램이 없어 풀 수 없습니다 (sudo apt install zstd)")
            proc = subprocess.Popen([exe, "-d", "-c", "-q", str(archive)], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=_child_env())
            try:
                with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                    extract(tar)
            finally:
                proc.stdout.close()
                err = proc.stderr.read()
                rc = proc.wait()
            if rc != 0:
                raise UnpackError(f"zstd 풀기 실패 (exit {rc}): {err.decode(errors='replace')[-300:]}")
        else:
            with tarfile.open(archive, mode="r|gz") as tar:
                extract(tar)
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        raise UnpackError(f"압축 풀기 실패: {type(exc).__name__}: {exc}")
    if not names:
        raise OffsiteError("압축 파일 안에 데이터베이스가 없습니다")
    return names


def integrity_check(path: Path) -> str:
    """'ok', or what PRAGMA integrity_check (read-only, no -wal/-shm created) reported."""
    uri = "file:" + urllib.parse.quote(str(path.resolve())) + "?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True)
        try:
            rows = con.execute("PRAGMA integrity_check").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        return f"{type(exc).__name__}: {exc}"
    return "ok" if rows == [("ok",)] else "; ".join(str(r[0]) for r in rows[:5])


EXEC_DIR = "/var/lib/paperbot/exec"
# the order executor's own user (deploy/install.sh): its folder and databases are its own, never paperbot's (the agents'
# and the dashboard's user): group paperbot may read them (the nightly backup), nothing running as paperbot may change
# them (docs/live-safety.md 1-9)
EXEC_USER = "paperbot-exec"


def _target(name: str) -> str:
    return f"{EXEC_DIR}/{name}" if name.startswith("executor") else f"/var/lib/paperbot/{name}"


def _owner(target: str) -> str:
    return f"{EXEC_USER} -g paperbot" if target.startswith(EXEC_DIR + "/") else "paperbot -g paperbot"


def next_steps(dest: Path, names: Sequence[str]) -> str:
    lines = [
        "",
        "다음 순서 (docs/offsite-backup.md 9-5):",
        "1) 봇과 작업을 모두 멈춥니다 (새 서버에서 아직 켜지 않았다면 'not loaded' 같은 말이 나와도 괜찮습니다):",
        "   sudo systemctl stop paperbot-live3 paperbot-dash paperbot-liq paperbot-executor \\",
        "     paperbot-agents.timer paperbot-agents.service paperbot-daily3.timer paperbot-checkpoint.timer \\",
        "     paperbot-checkpoint.service paperbot-backup.timer paperbot-offsite.timer",
        "2) 데이터베이스를 제자리에 넣고, 남아 있을 수 있는 -wal/-shm 파일을 지웁니다:",
    ]
    if any(_target(n).startswith(EXEC_DIR + "/") for n in names):
        lines += [
            f"   (주문 실행기 DB는 실행기 전용 사용자 {EXEC_USER}의 것입니다. 'invalid user'가 나오면 먼저 "
            "cd /root/crypto-bot-research && sudo bash deploy/install.sh 를 하고 이 줄부터 다시 붙여 넣습니다)",
            f"   sudo install -d -o {EXEC_USER} -g paperbot -m 750 {EXEC_DIR}",
        ]
    for n in names:
        t = _target(n)
        lines.append(f"   sudo install -o {_owner(t)} -m 640 {dest / n} {t}")
        lines.append(f"   sudo rm -f {t}-wal {t}-shm")
    lines += [
        "3) 그날은 에이전트를 쉬게 합니다 (AI 사용 기록이 백업 시점으로 돌아감): 켤 때 paperbot-agents.timer만 빼고,",
        "   다음 날 sudo systemctl start paperbot-agents.timer",
        "4) docs/server-setup-v3.md 11번(시작)대로 켜고 (paperbot-offsite.timer도 함께), 12번(첫 1시간 확인)을 합니다.",
        "   확인은 12번의 launchcheck --stage after로 합니다(그날 쉬게 한 paperbot-agents.timer 줄은 따르지 않음).",
        "   10번(--stage before)은 하지 않습니다: 되살린 paper3.db를 옮기라는 줄을 따르면 되살린 기록이 빠집니다.",
        "   주문 실행기(paperbot-executor)는 켜지 않습니다 (docs/live-safety.md).",
    ]
    return "\n".join(lines)


def restore_backup(files: Sequence[Path], out: Path, *, sha256: Optional[str] = None,
                   env: Optional[Mapping[str, str]] = None, which: Callable[[str], Optional[str]] = shutil.which,
                   ask: Optional[Callable[[str], str]] = None, log: Callable[[str], None] = print) -> int:
    """Verify, join, decrypt, unpack and integrity-check; 0 when every database is ok, else 1.
    ``files``: the downloaded files, or folders holding them (searched with their subfolders; hidden
    files skipped), e.g. Telegram Desktop's own download folder."""
    env = os.environ if env is None else env
    paths: list[Path] = []
    from_folder: set[Path] = set()
    for p in map(Path, files):
        if p.is_dir():
            found = sorted(x for x in p.rglob("*") if x.is_file()
                           and not any(s.startswith(".") for s in x.relative_to(p).parts))
            if not found:
                raise OffsiteError(f"폴더가 비어 있습니다: {p}")
            from_folder.update(found)
            paths += found
        elif p.is_file():
            paths.append(p)
        else:
            glob_hint = (" (폴더 이름만 주면 됩니다: --parts /root/restore-in)"
                         if any(c in str(p) for c in "*?[") else "")
            raise OffsiteError(f"파일이 없습니다: {p}{glob_hint}")
    seen: set[Path] = set()
    paths = [p for p in paths if not (p.resolve() in seen or seen.add(p.resolve()))]
    manifests = [p for p in paths if p.name.endswith(".manifest.json")]
    parts = [p for p in paths if p not in manifests]
    if len(manifests) > 1:
        raise OffsiteError("목록 파일(.manifest.json)이 여러 개입니다. 한 날짜의 것만 넣으세요 (폴더에는 그 날짜의 "
                           f"파일만): {', '.join(p.name for p in manifests)}")
    if not parts:
        raise OffsiteError("조각 파일이 없습니다")
    m = _load_manifest(manifests[0]) if manifests else None
    if m is not None:
        ordered = _order_by_manifest(m, parts, log)
        archive_name, expect = m["archive"], m["sha256"]
        compression, encrypted, date = m["compression"], bool(m["encrypted"]), str(m["date"])
        if not re.fullmatch(r"\d{8}", date) or "/" in archive_name or compression not in ("zstd", "gzip"):
            raise OffsiteError(f"목록 파일 내용이 이상합니다: {manifests[0]}")
        log(f"조각 {len(ordered)}개의 sha256이 목록과 맞습니다")
        raw_size = sum(v for v in (m.get("databases") or {}).values() if isinstance(v, int))
    else:
        stray = [p for p in parts if p in from_folder and not PART_RE.match(p.name)]
        for p in stray:                       # e.g. desktop.ini, another download in the same folder
            log(f"참고: 조각 이름이 아닌 파일은 쓰지 않습니다: {p}")
        parts = [p for p in parts if p not in stray]
        if not parts:
            raise OffsiteError("조각 파일이 없습니다")
        ordered, archive_name = _order_by_name(parts)
        raw_size = 0
        if not sha256 or not re.fullmatch(r"[0-9a-fA-F]{12,64}", sha256):
            raise OffsiteError("목록 파일(paperbot-<날짜>.manifest.json)을 함께 넣거나, 조각 설명에 적힌 전체 sha256을 "
                               "--sha256으로 주세요")
        expect = sha256.lower()
        encrypted = archive_name.endswith(".enc")
        compression = "zstd" if archive_name.removesuffix(".enc").endswith(".zst") else "gzip"
        mt = re.search(r"(\d{8})", archive_name)
        date = mt.group(1) if mt else "restored"
    dest = out / date
    if dest.exists() and any(dest.iterdir()):
        raise OffsiteError(f"폴더({dest})가 이미 있고 비어 있지 않습니다. 다른 --out 폴더를 고르세요")
    out.mkdir(parents=True, exist_ok=True)
    # joined archive (+ its decrypted copy) + the databases; without the manifest assume 6x compression.
    # A practice restore runs on the live server: the bot's disk keeps free_floor() free.
    arc_size = sum(f.stat().st_size for f in ordered)
    check_space(out, arc_size + max(arc_size if encrypted else 0, raw_size or 6 * arc_size), "되살리기")
    tmp = Path(tempfile.mkdtemp(prefix=".offsite-restore-", dir=str(out)))
    try:
        joined = tmp / re.sub(r"[^A-Za-z0-9._-]", "_", archive_name)
        h = hashlib.sha256()
        with open(joined, "wb") as dst:
            for f in ordered:
                with open(f, "rb") as src:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        h.update(chunk)
                        dst.write(chunk)
        got = h.hexdigest()
        if not got.startswith(expect):
            raise OffsiteError(f"합친 파일의 sha256이 다릅니다 (기대 {expect[:16]}…, 실제 {got[:16]}…): "
                               "조각이 빠졌거나 섞였습니다")
        log(f"전체 sha256 확인: {got}")
        archive = joined
        if encrypted:
            passphrase = env.get("BACKUP_PASSPHRASE") or ""
            if not passphrase and ask is not None:
                passphrase = ask("백업 암호(BACKUP_PASSPHRASE): ")
            if not passphrase:
                raise OffsiteError("암호화된 백업입니다: BACKUP_PASSPHRASE가 필요합니다")
            archive = joined.with_name(joined.name.removesuffix(".enc") or "archive")
            openssl_run(["enc", "-d", *OPENSSL_ENC[1:], "-in", str(joined), "-out", str(archive),
                         "-pass", "env:BACKUP_PASSPHRASE"], passphrase, which, "복호화")
            joined.unlink()
        created = not dest.exists()
        try:
            names = unpack(archive, compression, dest, which)
        except BaseException as exc:
            # nothing half-unpacked is left behind to be mistaken for a good restore (dest was empty)
            if created:
                shutil.rmtree(dest, ignore_errors=True)
            else:
                for f in dest.iterdir():
                    f.unlink()
            if encrypted and isinstance(exc, UnpackError):
                # openssl's padding check lets about 1 wrong passphrase in 256 through: the result is noise
                raise OffsiteError(f"{exc} — 전체 확인값(sha256)은 맞았으므로 암호(BACKUP_PASSPHRASE)가 틀렸을 가능성이 "
                                   "큽니다. 암호를 다시 확인하세요") from None
            raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = 0
    log(f"되살린 데이터베이스: {dest}")
    for n in sorted(names):
        res = integrity_check(dest / n)
        bad += res != "ok"
        log(f"  {n:<24} {fmt_size((dest / n).stat().st_size):>10}  integrity_check {res}")
    if bad:
        log(f"\n{bad}개 데이터베이스가 손상되었습니다. 제자리에 넣지 말고, 텔레그램에서 하루 전 백업을 받아 다시 해 보세요.")
        return 1
    log(next_steps(dest, sorted(names)))
    return 0


# ---------------------------------------------------------------- chats
def list_chats(env: Mapping[str, str], sender: Optional[Sender] = None, sleep=time.sleep,
               out: Callable[[str], None] = print) -> int:
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    check_token(token)
    # a form with no part at all (only the closing boundary) gets "HTTP 400" with an empty body from Telegram
    updates = Telegram(token, sender, sleep, timeout=30.0).call("getUpdates", {"limit": "100", "timeout": "0"}) or []
    seen: dict[int, tuple[str, str]] = {}
    for u in updates:
        for key in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
            chat = (u.get(key) or {}).get("chat") if isinstance(u, dict) else None
            if isinstance(chat, dict) and "id" in chat:
                title = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
                seen[chat["id"]] = (title or "?", chat.get("type", "?"))
    if not seen:
        out("최근 메시지가 없습니다. 새 단체방에 /start@<봇 아이디>를 한 번 보내고 다시 실행하세요.")
        return 0
    for cid, (title, kind) in seen.items():
        out(f"방 번호 {cid}   이름 {title}   ({kind})")
    return 0


# ---------------------------------------------------------------- CLI
def default_notifier(env: Mapping[str, str]) -> Notifier:
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_CRITICAL"):
        try:
            return TelegramNotifier()
        except KeyError:
            pass
    return ConsoleNotifier()


SIGTERM_REASON = ("중간에 멈춰졌습니다(SIGTERM): 한 번 실행 시간 제한(1시간)을 넘겼거나, 서버가 다시 시작되었거나, "
                  "누가 멈췄습니다")


def _on_sigterm(signum, frame):
    # systemd's TimeoutStartSec, a reboot or `systemctl stop`: become an ordinary failure, so main()'s
    # WARN goes out (Python's default would end the process silently). Once: the alert is not interrupted.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise OffsiteError(SIGTERM_REASON)


def stopped_alert(env: Mapping[str, str]) -> Optional[str]:
    """For ExecStopPost=: the WARN text when systemd ended the send before it could alert by itself
    (killed by a signal: the memory limit, SIGKILL after the stop timeout; or a core dump), else None.
    A run that exited by itself already alerted when it failed (main) and is left alone."""
    code = (env.get("EXIT_CODE") or "").strip()
    if code not in ("killed", "dumped"):
        return None
    result = (env.get("SERVICE_RESULT") or "?").strip()
    status = (env.get("EXIT_STATUS") or "?").strip()
    why = "메모리 한도(1 GB)를 넘었습니다" if result == "oom-kill" else "강제로 멈춰졌습니다"
    return (f"서버 밖 백업이 비정상으로 끝났습니다: {why} (systemd {result}, {code} {status}). "
            "이날 백업은 텔레그램에 다 가지 못했을 수 있습니다.\n"
            "서버 안 백업(/var/backups/paperbot)은 그대로 있습니다. 내일 같은 시각에 다시 시도합니다.\n"
            "확인: sudo journalctl -u paperbot-offsite -n 50 --no-pager")


def main(argv: Optional[list[str]] = None, *, env: Optional[Mapping[str, str]] = None,
         sender: Optional[Sender] = None, sleep: Optional[Callable[[float], None]] = None,
         notifier: Optional[Notifier] = None, now: Optional[datetime] = None,
         which: Optional[Callable[[str], Optional[str]]] = None,
         ask: Optional[Callable[[str], str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.offsite", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help="pack, split and upload the newest backup folder")
    s.add_argument("--from", dest="root", type=Path, default=Path("/var/backups/paperbot"))
    s.add_argument("--chat-env", default="TELEGRAM_CHAT_BACKUP",
                   help="env variable holding the backup chat id (empty: TELEGRAM_CHAT_CRITICAL, with a note)")
    s.add_argument("--date", help="YYYYMMDD folder (default: today's UTC folder, else yesterday's)")
    s.add_argument("--lib", type=Path, default=None,
                   help="live databases, for the completeness check (default $PAPERBOT_LIB or /var/lib/paperbot)")
    s.add_argument("--part-mb", type=float, default=45.0, help="part size in MB (1024*1024 bytes), at most 46")
    s.add_argument("--compress", choices=("auto", "zstd", "gzip"), default="auto")
    s.add_argument("--work", type=Path, default=None, help="temporary folder (default: $TMPDIR or /tmp)")
    s.add_argument("--wait-min", type=float, default=5.0, help="wait this long for a backup still being written")
    s.add_argument("--max-min", type=float, default=RUN_LIMIT_S / 60,
                   help="stop (WARN, exit 1) after this many minutes; keep it below the unit's TimeoutStartSec")
    s.add_argument("--dry-run", action="store_true", help="pack and split, print the parts, upload nothing")
    r = sub.add_parser("restore", help="verify, join, decrypt, unpack and integrity-check downloaded parts")
    r.add_argument("--parts", nargs="+", type=Path, required=True,
                   help="the parts and the .manifest.json, or a folder holding them")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--sha256", help="whole-archive sha256 from a part's caption (only without the manifest)")
    sub.add_parser("chats", help="list the chat ids the bot has seen recently (getUpdates)")
    sub.add_parser("stopped", help="ExecStopPost: WARN when systemd killed a send before it could alert")
    a = ap.parse_args(argv)

    env = os.environ if env is None else env
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    passphrase = env.get("BACKUP_PASSPHRASE") or ""
    which = which or shutil.which
    sleep = sleep or time.sleep
    info: dict = {}
    if a.cmd == "stopped":
        text = stopped_alert(env)
        if text:
            _stderr(text)
            (notifier or default_notifier(env)).send(WARN, redact(text, token, passphrase))
        return 0
    alerting = a.cmd == "send" and not a.dry_run
    armed, previous = False, None
    if alerting:
        try:
            previous = signal.signal(signal.SIGTERM, _on_sigterm)
            armed = True
        except ValueError:                    # not the main thread: no handler (systemd runs it in the main one)
            pass
    try:
        if a.cmd == "send":
            lib = a.lib or Path(env.get("PAPERBOT_LIB") or "/var/lib/paperbot")
            send_backup(a.root, a.chat_env, date=a.date, lib=lib, part_size=int(a.part_mb * 1024 * 1024),
                        compression=a.compress, work=a.work, dry_run=a.dry_run, wait_s=a.wait_min * 60,
                        env=env, sender=sender, sleep=sleep, now=now, which=which, info=info,
                        max_s=a.max_min * 60)
            return 0
        if a.cmd == "restore":
            asker = ask if ask is not None else (getpass.getpass if sys.stdin.isatty() else None)
            return restore_backup(a.parts, a.out, sha256=a.sha256, env=env, which=which, ask=asker)
        return list_chats(env, sender, sleep)
    except Exception as exc:
        if armed:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)     # the WARN below is not interrupted
        if isinstance(exc, OffsiteError):
            reason = redact(exc, token, passphrase)
        else:
            _stderr(redact(traceback.format_exc(), token, passphrase))
            reason = redact(f"{type(exc).__name__}: {exc}", token, passphrase)
        _stderr(f"offsite {a.cmd} failed: {reason}")
        if alerting:
            text = (f"서버 밖 백업 실패 ({info.get('date', '날짜 모름')}): {reason}\n"
                    "서버 안 백업(/var/backups/paperbot)은 그대로 있습니다. 내일 같은 시각에 다시 시도합니다.\n"
                    "확인: sudo journalctl -u paperbot-offsite -n 50 --no-pager")
            (notifier or default_notifier(env)).send(WARN, redact(text, token, passphrase))
        return 1
    finally:
        if armed:
            signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)


if __name__ == "__main__":
    sys.exit(main())
