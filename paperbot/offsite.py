"""Off-site copy of the nightly database backup to a private Telegram chat (docs/offsite-backup.md).

    python -m paperbot.offsite send    --from /var/backups/paperbot --chat-env TELEGRAM_CHAT_BACKUP
    python -m paperbot.offsite restore --parts DOWNLOADS/paperbot-20261001.* --out DIR
    python -m paperbot.offsite chats   # chat ids the bot has seen (to find the backup group's id)

The owners run one Vultr server without Vultr's automatic backups. deploy/paperbot-backup.sh writes
consistent copies of the databases into /var/backups/paperbot/<YYYYMMDD>/ every night (23:40 UTC,
08:40 KST; the folder is named by the UTC date); if the server is lost, those copies are lost with it.

send: takes the newest backup folder (today's UTC date, else yesterday's: the 23:40 UTC run's folder
is "yesterday" once the clock has passed midnight UTC), refuses one that is incomplete (a copy still
being written, or a database that exists on the server without a copy), packs it as tar + zstd (gzip
when the zstd program is missing), encrypts it with the openssl program when BACKUP_PASSPHRASE is set
(no homemade cryptography: without openssl it refuses and sends nothing), splits it into parts below
Telegram's 50 MB document limit and uploads each part with sendDocument (urllib, multipart/form-data),
then a manifest (part names, sizes, sha256s) with a short Korean summary as its caption. Network errors,
5xx and 429 (retry_after) are retried with backoff. Any failure sends a Korean WARN through the normal
notifier and exits 1, so paperbot-offsite.service fails visibly.

restore: matches the downloaded parts to the manifest by sha256 (file names may change on download),
joins them, checks the whole archive's sha256, decrypts, unpacks (plain files only, no paths outside
the output folder) and runs PRAGMA integrity_check on every database; prints the next steps in Korean.

Reads only the backup folder, and the live database paths (existence only, for the completeness
check); writes only its temporary folder (send) or --out (restore). It is not a writer of any database.
The bot token is in every request URL: every error and log line goes through redact().
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
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
from typing import Callable, Mapping, Optional, Sequence

from .notify import WARN, ConsoleNotifier, Notifier, TelegramNotifier

API = "https://api.telegram.org"
# the databases deploy/paperbot-backup.sh copies (keep the two lists the same); a copy is <basename>.db
DB_NAMES = ("agents3", "inbox", "liq", "checkpoint", "exec/executor", "exec/executor-testnet", "daily3", "paper3")
TELEGRAM_UPLOAD_LIMIT = 50_000_000      # Bot API: documents up to 50 MB (read as decimal MB, the stricter)
MULTIPART_ROOM = 1_000_000              # form fields, caption and boundaries around the file
MAX_PART = TELEGRAM_UPLOAD_LIMIT - MULTIPART_ROOM
DEFAULT_PART = 45 * 1024 * 1024         # 47.2 MB
CAPTION_LIMIT = 1024
SQLITE_HEADER = b"SQLite format 3\x00"
MANIFEST_FORMAT = "paperbot-offsite/1"
BACKOFF = (5, 15, 45, 120, 300)         # seconds before retry 1..5 (6 attempts in all)
MAX_RETRY_AFTER = 900                   # a longer 429 wait fails the run instead of sleeping past the unit timeout
UPLOAD_TIMEOUT = 300.0
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


def redact(text, token: Optional[str] = None) -> str:
    """The text with the bot token (exact value, and anything shaped like a bot token) replaced."""
    s = str(text)
    for t in {token or "", (token or "").strip()}:
        if len(t) >= 8:
            s = s.replace(t, "<token>")
            s = s.replace(urllib.parse.quote(t, safe=""), "<token>")
    return _TOKEN_RE.sub("<token>", s)


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
                 log: Callable[[str], None] = _stderr):
        self.token = token
        self.sender = sender or urllib_sender
        self.sleep = sleep
        self.timeout = timeout
        self.backoff = tuple(backoff)
        self.log = log

    def call(self, method: str, fields: Mapping[str, str], file: Optional[tuple] = None):
        body, ctype = multipart(fields, file)
        url = f"{API}/bot{self.token}/{method}"
        headers = {"Content-Type": ctype, "Content-Length": str(len(body))}
        attempts = len(self.backoff) + 1
        for attempt in range(1, attempts + 1):
            wait = float(self.backoff[attempt - 1]) if attempt <= len(self.backoff) else 0.0
            try:
                status, raw = self.sender(url, body, headers, self.timeout)
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


def check_complete(folder: Path, lib: Optional[Path], wait_s: float = 0.0,
                   sleep: Callable[[float], None] = time.sleep, poll_s: float = 30.0,
                   log: Callable[[str], None] = _stderr) -> dict[str, int]:
    """{file name: bytes} of the folder's database copies; OffsiteError when the folder is incomplete:
    a copy still being written (<name>.db.part; waited for up to ``wait_s``), no copy at all, a copy
    that is not an SQLite file, or a database that exists in ``lib`` without a copy."""
    waited = 0.0
    while True:
        parts = sorted(p.name for p in folder.glob("*.part"))
        if not parts:
            break
        if waited >= wait_s:
            raise OffsiteError(f"백업이 끝나지 않았습니다: {folder.name}에 쓰는 중인 파일 {', '.join(parts)} "
                               "(서버 안 백업이 아직 돌거나 중간에 끊김)")
        log(f"backup still writing {', '.join(parts)}; waiting")
        sleep(poll_s)
        waited += poll_s
    files = {p.name: p.stat().st_size for p in sorted(folder.iterdir()) if p.is_file() and p.name.endswith(".db")}
    if not files:
        raise OffsiteError(f"백업 폴더({folder})가 비어 있습니다 (봇을 켜기 전이거나 복사가 모두 실패)")
    bad = []
    for name in files:
        with open(folder / name, "rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                bad.append(name)
    if bad:
        raise OffsiteError(f"백업 파일이 SQLite 파일이 아닙니다: {', '.join(bad)}")
    missing = []
    if lib is not None and lib.is_dir():
        for f in DB_NAMES:
            base = f.rsplit("/", 1)[-1] + ".db"
            if (lib / f"{f}.db").exists() and base not in files:
                missing.append(base)
    elif lib is not None:
        log(f"note: {lib} not found; checked the folder only")
    if missing:
        raise OffsiteError(f"백업이 빠졌습니다: {', '.join(missing)} (서버에는 있는데 {folder.name} 폴더에 복사본이 "
                           "없음; systemctl status paperbot-backup)")
    return files


# ---------------------------------------------------------------- pack, encrypt, split
@dataclass
class Archive:
    path: Path
    name: str
    size: int
    sha256: str
    compression: str
    encrypted: bool


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
    date = folder.name
    comp = choose_compression(compression, which, log)
    name = f"paperbot-{date}.tar." + ("zst" if comp == "zstd" else "gz")
    path = work / name
    members = [(folder / f, f"{date}/{f}") for f in files]
    if comp == "zstd":
        proc = subprocess.Popen([which("zstd") or "zstd", "-q", "-T2", "-10", "-f", "-o", str(path)],
                                stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        broken = False
        try:
            with tarfile.open(fileobj=proc.stdin, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for src, arc in members:
                    tar.add(src, arcname=arc, recursive=False, filter=_tar_clean)
        except BrokenPipeError:                       # zstd stopped reading: never a whole archive
            broken = True
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                broken = True
            err = proc.stderr.read()
            rc = proc.wait()
        if rc != 0 or broken:
            raise OffsiteError(f"zstd 압축 실패 (exit {rc}): {err.decode(errors='replace')[-300:]}")
    else:
        with tarfile.open(path, mode="w:gz", compresslevel=6, format=tarfile.PAX_FORMAT) as tar:
            for src, arc in members:
                tar.add(src, arcname=arc, recursive=False, filter=_tar_clean)
    encrypted = False
    if passphrase:
        enc = path.with_name(name + ".enc")
        openssl_run([*OPENSSL_ENC, "-in", str(path), "-out", str(enc), "-pass", "env:BACKUP_PASSPHRASE"],
                    passphrase, which, "암호화")
        path.unlink()
        path, name, encrypted = enc, enc.name, True
    return Archive(path, name, path.stat().st_size, sha256_file(path), comp, encrypted)


def openssl_run(args: Sequence[str], passphrase: str, which: Callable[[str], Optional[str]], what: str) -> None:
    exe = which("openssl")
    if not exe:
        raise OffsiteError(f"openssl 프로그램이 없어 {what}할 수 없습니다 (sudo apt install openssl)")
    # the passphrase reaches openssl through its environment, never its command line (ps shows that)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "BACKUP_PASSPHRASE": passphrase}
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


def summary_text(m: dict, note: str = "") -> str:
    dbs = " · ".join(f"{k.removesuffix('.db')} {fmt_size(v)}" for k, v in m["databases"].items())
    enc = "암호화함" if m["encrypted"] else "암호화 없음"
    lines = [
        f"paperbot 서버 밖 백업 완료: {m['date']} 폴더 (백업 시각 {m['backup_kst']} 한국)",
        f"DB {len(m['databases'])}개 {fmt_size(sum(m['databases'].values()))} → 보낸 파일 {fmt_size(m['size'])} "
        f"({m['compression']}, {enc}), 조각 {len(m['parts'])}개",
        f"DB: {dbs}",
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
                info: Optional[dict] = None) -> dict:
    """Pack, split and upload one backup folder; returns the manifest. Raises OffsiteError."""
    env = os.environ if env is None else env
    info = {} if info is None else info
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
    files = check_complete(folder, lib, wait_s, sleep, log=log)
    raw = sum(files.values())
    workdir = Path(tempfile.mkdtemp(prefix="paperbot-offsite-", dir=str(work) if work else None))
    try:
        free = shutil.disk_usage(workdir).free
        if free < raw + 64 * 1024 * 1024:
            raise OffsiteError(f"임시 공간이 모자랍니다: {workdir}에 {fmt_size(free)} 남음, 약 {fmt_size(raw)} 필요")
        arc = pack(folder, list(files), workdir, compression, passphrase, which, log)
        made = max((folder / f).stat().st_mtime for f in files)
        plan = plan_parts(arc.size, part_size)
        manifest = {
            "format": MANIFEST_FORMAT, "date": folder.name, "backup_kst": _kst(made),
            "archive": arc.name, "compression": arc.compression, "encrypted": arc.encrypted,
            "cipher": CIPHER if arc.encrypted else None, "size": arc.size, "sha256": arc.sha256,
            "part_size": part_size, "parts": [], "databases": dict(files),
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        tg = None if dry_run else Telegram(token, sender, sleep, log=log)
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
        summary = summary_text(manifest, note)
        if tg is not None:
            tg.call("sendDocument", {"chat_id": chat, "caption": summary, "disable_notification": "true",
                                     "disable_content_type_detection": "true"},
                    ("document", f"paperbot-{folder.name}.manifest.json",
                     (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode()))
        out(summary)
        return manifest
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
                                    stderr=subprocess.PIPE)
            try:
                with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                    extract(tar)
            finally:
                proc.stdout.close()
                err = proc.stderr.read()
                rc = proc.wait()
            if rc != 0:
                raise OffsiteError(f"zstd 풀기 실패 (exit {rc}): {err.decode(errors='replace')[-300:]}")
        else:
            with tarfile.open(archive, mode="r|gz") as tar:
                extract(tar)
    except (tarfile.TarError, EOFError, zlib.error) as exc:
        raise OffsiteError(f"압축 풀기 실패: {type(exc).__name__}: {exc}")
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


def _target(name: str) -> str:
    return f"/var/lib/paperbot/exec/{name}" if name.startswith("executor") else f"/var/lib/paperbot/{name}"


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
    if any(n.startswith("executor") for n in names):
        lines.append("   sudo install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/exec")
    for n in names:
        t = _target(n)
        lines.append(f"   sudo install -o paperbot -g paperbot -m 640 {dest / n} {t}")
        lines.append(f"   sudo rm -f {t}-wal {t}-shm")
    lines += [
        "3) 그날은 에이전트를 쉬게 합니다 (AI 사용 기록이 백업 시점으로 돌아감): 켤 때 paperbot-agents.timer만 빼고,",
        "   다음 날 sudo systemctl start paperbot-agents.timer",
        "4) docs/server-setup-v3.md 11번(시작)대로 켜고 12번(첫 1시간 확인)을 합니다.",
        "   주문 실행기(paperbot-executor)는 켜지 않습니다 (docs/live-safety.md).",
    ]
    return "\n".join(lines)


def restore_backup(files: Sequence[Path], out: Path, *, sha256: Optional[str] = None,
                   env: Optional[Mapping[str, str]] = None, which: Callable[[str], Optional[str]] = shutil.which,
                   ask: Optional[Callable[[str], str]] = None, log: Callable[[str], None] = print) -> int:
    """Verify, join, decrypt, unpack and integrity-check; 0 when every database is ok, else 1."""
    env = os.environ if env is None else env
    paths = [Path(f) for f in files]
    for p in paths:
        if not p.is_file():
            raise OffsiteError(f"파일이 없습니다: {p}")
    manifests = [p for p in paths if p.name.endswith(".manifest.json")]
    parts = [p for p in paths if p not in manifests]
    if len(manifests) > 1:
        raise OffsiteError("목록 파일(.manifest.json)이 여러 개입니다. 한 날짜의 것만 넣으세요")
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
    else:
        ordered, archive_name = _order_by_name(parts)
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
        except BaseException:
            # nothing half-unpacked is left behind to be mistaken for a good restore (dest was empty)
            if created:
                shutil.rmtree(dest, ignore_errors=True)
            else:
                for f in dest.iterdir():
                    f.unlink()
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
    updates = Telegram(token, sender, sleep, timeout=30.0).call("getUpdates", {}) or []
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
    s.add_argument("--dry-run", action="store_true", help="pack and split, print the parts, upload nothing")
    r = sub.add_parser("restore", help="verify, join, decrypt, unpack and integrity-check downloaded parts")
    r.add_argument("--parts", nargs="+", type=Path, required=True, help="the parts and the .manifest.json")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--sha256", help="whole-archive sha256 from a part's caption (only without the manifest)")
    sub.add_parser("chats", help="list the chat ids the bot has seen recently (getUpdates)")
    a = ap.parse_args(argv)

    env = os.environ if env is None else env
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    which = which or shutil.which
    sleep = sleep or time.sleep
    info: dict = {}
    try:
        if a.cmd == "send":
            lib = a.lib or Path(env.get("PAPERBOT_LIB") or "/var/lib/paperbot")
            send_backup(a.root, a.chat_env, date=a.date, lib=lib, part_size=int(a.part_mb * 1024 * 1024),
                        compression=a.compress, work=a.work, dry_run=a.dry_run, wait_s=a.wait_min * 60,
                        env=env, sender=sender, sleep=sleep, now=now, which=which, info=info)
            return 0
        if a.cmd == "restore":
            asker = ask if ask is not None else (getpass.getpass if sys.stdin.isatty() else None)
            return restore_backup(a.parts, a.out, sha256=a.sha256, env=env, which=which, ask=asker)
        return list_chats(env, sender, sleep)
    except Exception as exc:
        if isinstance(exc, OffsiteError):
            reason = redact(exc, token)
        else:
            _stderr(redact(traceback.format_exc(), token))
            reason = redact(f"{type(exc).__name__}: {exc}", token)
        _stderr(f"offsite {a.cmd} failed: {reason}")
        if a.cmd == "send" and not a.dry_run:
            text = (f"서버 밖 백업 실패 ({info.get('date', '날짜 모름')}): {reason}\n"
                    "서버 안 백업(/var/backups/paperbot)은 그대로 있습니다. 내일 같은 시각에 다시 시도합니다.\n"
                    "확인: sudo journalctl -u paperbot-offsite -n 50 --no-pager")
            (notifier or default_notifier(env)).send(WARN, redact(text, token))
        return 1


if __name__ == "__main__":
    sys.exit(main())
