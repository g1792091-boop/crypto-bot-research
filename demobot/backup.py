"""Nightly backup of the demo lab's own records to Telegram (CONTRACT.md 8.8).

    python -m demobot.backup send            # demobot-backup.timer, every night 04:40 KST (19:40 UTC)
    python -m demobot.backup now             # the same, once, by hand (says each step in Korean)
    python -m demobot.backup restore FILE [--force]

send: copies only the records that cannot be rebuilt from Binance (tables ``TABLES``; ``outbox`` only its last 7 days)
out of demo.db, opened read-only (sqlite URI ``mode=ro``, one read transaction, so a consistent picture while the
engine keeps writing), into a small temporary SQLite file: each table is made from its own CREATE statement in
sqlite_master and filled in batches. A table the database does not have (an older engine) is skipped and counted 0.
The file is gzipped and, when ``DEMOBOT_BACKUP_PASSPHRASE`` is set, encrypted by the openssl program
(``openssl enc -aes-256-cbc -pbkdf2 -salt``; no homemade cryptography: without openssl nothing is sent). The
passphrase reaches openssl through its environment, never its command line. The file goes to every chat of
``DEMOBOT_BACKUP_CHAT`` (comma separated; default: every chat of ``DEMOBOT_TG_CHAT``, e.g. both owners' private chats)
with Telegram ``sendDocument`` (urllib, multipart/form-data), silent, with a short Korean caption; network errors,
5xx and 429 are retried with backoff inside one time limit for the run (``RUN_LIMIT_S``, below the unit's
TimeoutStartSec). Every chat is tried even when one fails; the backup counts as good only when all of them got it
(the error says which did not). A file over 45 MB is refused.
``snap/backup.json`` (written atomically) says how it went; a failure exits 1 so demobot-backup.service fails
visibly, and queues nothing: the outside watch (demobot/watch.py) reports a backup older than 36 hours.

restore: decrypts (passphrase from the environment or the env file, else asked), gunzips, runs
``PRAGMA integrity_check`` and copies every table into ``DEMOBOT_DB`` with INSERT OR REPLACE (the database is made
when it is missing). Refuses while demobot-live.service runs, unless ``--force``. Prints the next steps in Korean.

The bot token is in every request URL: every error and log line goes through ``redact`` (the token and the
passphrase removed). The settings come from the environment (the unit's EnvironmentFile), else from
/etc/demobot/demobot.env (readable by group demobot), so ``sudo -u demobot ... now`` works too.
"""
from __future__ import annotations

import argparse
import getpass
import gzip
import http.client
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Callable, Mapping, Optional, Sequence

from . import notify as N

# the records that cannot be rebuilt from Binance (CONTRACT.md 8.8); bars, funding, signals and cells are not here.
# meta also holds the finished weekly reviews ("주간 회의록", meta key `reviews`, CONTRACT.md 8.10)
TABLES = ("views", "decisions", "passes", "depth", "notified", "meta", "outbox")
TABLE_KO = {"views": "관점", "decisions": "설정 바꿈", "passes": "통과·확인", "depth": "호가 비용",
            "notified": "알림 표시", "meta": "기본 정보·주간 회의록", "outbox": "보낸 알림(7일)"}
OUTBOX_KEEP_MS = 7 * 86400_000
BATCH = 1000
MAX_BYTES = 45 * 1024 * 1024            # Telegram takes documents up to 50 MB: refuse well below
CAPTION_LIMIT = 1024
BACKOFF = (5, 15, 45, 120)              # seconds before retry 1..4
MAX_RETRY_AFTER = 300                   # a longer 429 wait fails at once
RUN_LIMIT_S = 15 * 60                   # demobot-backup.service: TimeoutStartSec=20min
MIN_ATTEMPT_S = 20.0                    # an upload attempt with less time than this left is not started
UPLOAD_TIMEOUT = 120.0
OPENSSL_ENC = ("enc", "-aes-256-cbc", "-pbkdf2", "-salt")
PASS_ENV = "DEMOBOT_BACKUP_PASSPHRASE"
ENV_FILE = N.ENV_FILE
ENV_KEYS = ("DEMOBOT_TG_TOKEN", "DEMOBOT_TG_CHAT", "DEMOBOT_BACKUP_CHAT", PASS_ENV, "DEMOBOT_DB", "DEMOBOT_SNAP")
DEFAULT_DB = "/var/lib/demobot/demo.db"
DEFAULT_SNAP = "/var/lib/demobot/snap"
LIVE_UNIT = "demobot-live.service"
KIT = "/root/demobot-src/deploy/demobot"
APP_PY = "cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python"
SQLITE_MAGIC = b"SQLite format 3\x00"
GZIP_MAGIC = b"\x1f\x8b"
SALTED_MAGIC = b"Salted__"             # openssl enc -salt
# meta keys (demobot/engine.py) that describe the market data of the database they are in: a restore keeps the
# target's own value when it has one (they are rewritten by `warm` anyway); `forming` (the 15m bar being formed on
# the old server) is never restored, the engine reads it again at its first tick
META_KEEP = ("history_start_ms", "warm_done_ms", "warm_issues")
META_SKIP = ("forming",)

Sender = Callable[[str, bytes, dict, float], tuple]   # (url, body, headers, timeout) -> (status, body bytes)


class BackupError(Exception):
    """A failure explained for the owners (Korean); the message never holds the token or the passphrase."""


def redact(text, token: Optional[str] = None, *others: Optional[str]) -> str:
    """``text`` without the bot token (``notify.redact``) and without any other secret given (the passphrase)."""
    s = N.redact(text, token)
    for o in others:
        for t in {o or "", (o or "").strip()}:
            if len(t) >= 4:
                s = s.replace(t, "<secret>").replace(urllib.parse.quote(t, safe=""), "<secret>")
    return s


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def fmt_size(n: float) -> str:
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def settings(env: Optional[Mapping[str, str]] = None, env_file: str = ENV_FILE) -> dict:
    """The keys of ``ENV_KEYS``: the environment first, else the env file (only the keys missing or empty)."""
    env = os.environ if env is None else env
    out = {k: (env.get(k) or "").strip() for k in ENV_KEYS}
    if not all(out.values()):
        f = N.read_env_file(env_file, keys=ENV_KEYS)
        for k in ENV_KEYS:
            out[k] = out[k] or (f.get(k) or "").strip()
    out["DEMOBOT_DB"] = out["DEMOBOT_DB"] or DEFAULT_DB
    out["DEMOBOT_SNAP"] = out["DEMOBOT_SNAP"] or DEFAULT_SNAP
    return out


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _ro_uri(path: str, immutable: bool = False) -> str:
    return "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro" + ("&immutable=1" if immutable else "")


def _write_json(path: str, obj) -> None:
    """Atomic (temp file in the same folder + os.replace)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- copy
def _columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({_q(table)})")]


def snapshot(db_path: str, out_path: str, now_ms: int, tables: Sequence[str] = TABLES, batch: int = BATCH) -> dict:
    """Copy ``tables`` of ``db_path`` (read-only) into the new SQLite file ``out_path``; {table: rows copied} in the
    order of ``tables`` (0 for a table the database does not have). ``outbox``: only rows of the last 7 days."""
    if not os.path.isfile(db_path):
        raise BackupError(f"데이터베이스가 없습니다: {db_path} (첫 채우기 전이거나 DEMOBOT_DB가 틀림)")
    src = sqlite3.connect(_ro_uri(db_path), uri=True, timeout=30, isolation_level=None)
    dst = sqlite3.connect(out_path, isolation_level=None)
    counts: dict = {}
    try:
        src.execute("BEGIN")                       # one read snapshot for every table
        master = {r[0]: r[1] for r in src.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'")}
        dst.execute("BEGIN")
        for t in tables:
            sql = master.get(t)
            if not sql:
                counts[t] = 0
                continue
            dst.execute(sql)
            for (isql,) in src.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
                                       "AND sql IS NOT NULL", (t,)).fetchall():
                dst.execute(isql)
            cols = _columns(src, t)
            names = ", ".join(_q(c) for c in cols)
            where, args = "", ()
            if t == "outbox" and "ts_ms" in cols:
                where, args = " WHERE ts_ms >= ?", (int(now_ms) - OUTBOX_KEEP_MS,)
            cur = src.execute(f"SELECT {names} FROM {_q(t)}{where}", args)
            ins = f"INSERT INTO {_q(t)} ({names}) VALUES ({', '.join('?' * len(cols))})"
            n = 0
            while True:
                rows = cur.fetchmany(batch)
                if not rows:
                    break
                dst.executemany(ins, rows)
                n += len(rows)
            counts[t] = n
        dst.execute("COMMIT")
        src.execute("COMMIT")
    finally:
        src.close()
        dst.close()
    return counts


def gzip_file(src: str, dst: str) -> None:
    with open(src, "rb") as fi, open(dst, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)


def _child_env(passphrase: str) -> dict:
    """openssl's environment: PATH and the passphrase only (never the token or other keys)."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), PASS_ENV: passphrase}


def openssl(args: Sequence[str], passphrase: str, what: str, which: Callable = shutil.which) -> None:
    exe = which("openssl")
    if not exe:
        raise BackupError(f"openssl 프로그램이 없어 {what}할 수 없습니다 (sudo apt install openssl)")
    # the passphrase reaches openssl through its environment, never its command line (ps would show that)
    r = subprocess.run([exe, *args, "-pass", f"env:{PASS_ENV}"], env=_child_env(passphrase), capture_output=True,
                       timeout=600)
    if r.returncode != 0:
        tail = redact(r.stderr.decode(errors="replace").strip()[-300:], None, passphrase)
        if what == "복호화" and "bad decrypt" in tail.lower():
            raise BackupError("복호화 실패: 암호(DEMOBOT_BACKUP_PASSPHRASE)가 틀렸거나 파일이 손상되었습니다")
        raise BackupError(f"openssl {what} 실패 (exit {r.returncode}): {tail}")


def encrypt(src: str, dst: str, passphrase: str, which: Callable = shutil.which) -> None:
    openssl([*OPENSSL_ENC, "-in", src, "-out", dst], passphrase, "암호화", which)


def decrypt(src: str, dst: str, passphrase: str, which: Callable = shutil.which) -> None:
    openssl([OPENSSL_ENC[0], "-d", *OPENSSL_ENC[1:], "-in", src, "-out", dst], passphrase, "복호화", which)


# ---------------------------------------------------------------- Telegram sendDocument (urllib only)
def urllib_sender(url: str, body: bytes, headers: dict, timeout: float) -> tuple:
    """POST; (status, body). Network errors raise (OSError and subclasses, HTTPException)."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:      # a 4xx/5xx answer is an answer, not a network error
        try:
            data = e.read()
        except Exception:  # noqa: BLE001
            data = b""
        return e.code, data


def multipart(fields: Mapping[str, str], file: Optional[tuple] = None) -> tuple:
    """multipart/form-data body and its Content-Type. ``file`` = (field, filename, bytes)."""
    boundary = "demobot-" + secrets.token_hex(16)
    out: list = []
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
        return (f" — 단체방 번호가 {params['migrate_to_chat_id']}(으)로 바뀌었습니다. 설정 파일의 번호를 고치세요: "
                f"{N.EDIT}")
    if status == 401:
        return f" — 봇 토큰(DEMOBOT_TG_TOKEN)이 틀렸습니다: {N.EDIT}"
    if "chat not found" in d or "initiate conversation" in d:
        return (" — 번호(DEMOBOT_BACKUP_CHAT 또는 DEMOBOT_TG_CHAT)가 틀렸거나, 그 사람이 아직 봇에서 시작(Start)을 "
                "누르지 않았습니다 (단체방이면 봇이 그 방에 없음)")
    if "blocked by the user" in d:
        return " — 그 사람이 봇을 차단했습니다. 차단을 풀고 시작(Start)을 누르세요"
    if status == 403:
        return " — 봇이 그 방에서 빠졌거나 막혔습니다. 봇을 다시 넣으세요"
    if status == 413 or "too large" in d:
        return " — 파일이 텔레그램 한도보다 큽니다"
    return ""


def send_document(token: str, chat: str, filename: str, data: bytes, caption: str, *,
                  sender: Optional[Sender] = None, sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic, deadline: Optional[float] = None,
                  backoff: Sequence[float] = BACKOFF, timeout: float = UPLOAD_TIMEOUT,
                  log: Callable[[str], None] = _stderr):
    """sendDocument (silent, plain caption) with retries: network errors, 5xx and 429 (its retry_after) are tried
    again after ``backoff``, while ``deadline`` (a ``clock()`` value) allows; other answers fail at once. Returns
    Telegram's result; raises ``BackupError`` (token removed)."""
    fields = {"chat_id": chat, "caption": caption[:CAPTION_LIMIT], "disable_notification": "true"}
    body, ctype = multipart(fields, ("document", filename, data))
    url = f"{N.API}/bot{token}/sendDocument"
    headers = {"Content-Type": ctype, "Content-Length": str(len(body))}
    send = sender or urllib_sender
    attempts = len(backoff) + 1
    problem = ""

    def out_of_time() -> BackupError:
        return BackupError(redact(f"텔레그램에 보내지 못했습니다: 이번 실행의 시간 제한에 걸림 ({problem or '느린 연결'})",
                                  token))

    for attempt in range(1, attempts + 1):
        wait = float(backoff[attempt - 1]) if attempt <= len(backoff) else 0.0
        t_out = timeout
        if deadline is not None:
            left = deadline - clock()
            t_out = min(t_out, left / 3)     # urllib's timeout bounds connect, upload and answer one by one
            if t_out < MIN_ATTEMPT_S:
                raise out_of_time()
        try:
            status, raw = send(url, body, headers, t_out)
        except (OSError, http.client.HTTPException) as exc:      # timeouts, resets, DNS, TLS
            problem = f"network {type(exc).__name__}: {exc}"
        else:
            try:
                ans = json.loads(raw or b"{}")
            except ValueError:
                ans = {}
            ans = ans if isinstance(ans, dict) else {}
            if status == 200 and ans.get("ok"):
                return ans.get("result")
            desc = str(ans.get("description") or (raw or b"")[:200])
            params = ans.get("parameters") if isinstance(ans.get("parameters"), dict) else {}
            problem = f"HTTP {status}: {desc}"
            if status == 429:
                after = params.get("retry_after")
                if isinstance(after, (int, float)) and not isinstance(after, bool) and after > 0:
                    if after > MAX_RETRY_AFTER:
                        raise BackupError(redact(f"텔레그램이 {after:.0f}초 기다리라고 합니다 (너무 김, {problem})", token))
                    wait = float(after) + 1.0
            elif status < 500:
                raise BackupError(redact(f"텔레그램이 백업 파일을 받지 않았습니다 ({problem}){_hint(status, desc, params)}",
                                         token))
        if attempt == attempts:
            raise BackupError(redact(f"텔레그램에 보내지 못했습니다: {attempts}번 모두 실패 ({problem})", token))
        if deadline is not None and wait + 3 * MIN_ATTEMPT_S > deadline - clock():
            raise out_of_time()
        log(redact(f"telegram sendDocument: {problem}; retry {attempt}/{attempts - 1} in {wait:.0f} s", token))
        sleep(wait)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------- send
def file_name(now_ms: int, encrypted: bool) -> str:
    return f"demolab-{N.kst(now_ms, '%Y%m%d-%H%M')}.db.gz" + (".enc" if encrypted else "")


def caption(now_ms: int, size: int, counts: Mapping[str, int], encrypted: bool) -> str:
    rows = " · ".join(f"{TABLE_KO.get(t, t)} {N.count(n)}" for t, n in counts.items())
    lines = [f"💾 데모 랩 밤 백업 · {N.kst(now_ms)}",
             f"크기 {fmt_size(size)} · 암호화 {'예 (openssl AES-256)' if encrypted else '아니오'}",
             rows,
             "관점·설정 바꿈·확인 기간·호가 비용·주간 회의록이 들어 있음",
             "시세와 계산 결과는 들어 있지 않음 (바이낸스에서 다시 만듦)",
             "되살리기: 이 파일을 서버에 올린 뒤 python -m demobot.backup restore 파일 (설치 안내 10번)"]
    return "\n".join(lines)[:CAPTION_LIMIT]


def write_status(snap: str, now_ms: int, ok: bool, size: int = 0, counts: Optional[dict] = None,
                 encrypted: bool = False, error_ko: Optional[str] = None) -> dict:
    """snap/backup.json (CONTRACT.md 8.8). A failure keeps the last good backup's facts (last_ok_ms, bytes, tables,
    encrypted) and sets last_try_ms and error_ko."""
    path = os.path.join(snap, "backup.json")
    prev = _read_json(path)
    out = {"last_ok_ms": prev.get("last_ok_ms"), "last_try_ms": int(now_ms), "bytes": prev.get("bytes", 0),
           "tables": prev.get("tables") if isinstance(prev.get("tables"), dict) else {},
           "encrypted": bool(prev.get("encrypted", False)), "error_ko": None}
    if ok:
        out.update(last_ok_ms=int(now_ms), bytes=int(size), tables=dict(counts or {}), encrypted=bool(encrypted))
    else:
        out["error_ko"] = error_ko or "알 수 없는 오류"
    _write_json(path, out)
    return out


def run_send(cfg: Mapping[str, str], now_ms: Optional[int] = None, *, sender: Optional[Sender] = None,
             which: Callable = shutil.which, sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.monotonic, say: Callable[[str], None] = lambda s: None,
             log: Callable[[str], None] = _stderr, run_limit_s: float = RUN_LIMIT_S) -> dict:
    """Make, pack and send the backup; {"bytes", "tables", "encrypted", "name"}. Raises ``BackupError`` (or anything
    unexpected); the caller words it and writes backup.json."""
    deadline = clock() + run_limit_s
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    token = cfg.get("DEMOBOT_TG_TOKEN") or ""
    chats = N.parse_chats(cfg.get("DEMOBOT_BACKUP_CHAT") or "") or N.parse_chats(cfg.get("DEMOBOT_TG_CHAT") or "")
    passphrase = cfg.get(PASS_ENV) or ""
    if not token or not chats:
        raise BackupError("텔레그램 토큰이나 번호가 비어 있습니다 (DEMOBOT_TG_TOKEN, DEMOBOT_TG_CHAT): " + N.EDIT)
    if passphrase and not which("openssl"):
        raise BackupError("DEMOBOT_BACKUP_PASSPHRASE가 있는데 openssl 프로그램이 없습니다. 직접 만든 암호화는 쓰지 않으므로 "
                          "보내지 않았습니다 (sudo apt install openssl, 또는 암호 없이 보내려면 그 줄을 비움)")
    work = tempfile.mkdtemp(prefix="demobot-backup-")
    try:
        os.chmod(work, 0o700)
        plain = os.path.join(work, "backup.db")
        say("기록 복사 중 (데이터베이스는 읽기만 함)")
        counts = snapshot(cfg.get("DEMOBOT_DB") or DEFAULT_DB, plain, now_ms)
        say("복사함: " + " · ".join(f"{t} {n}" for t, n in counts.items()))
        packed = plain + ".gz"
        gzip_file(plain, packed)
        if passphrase:
            say("암호화 중 (openssl AES-256)")
            enc = packed + ".enc"
            encrypt(packed, enc, passphrase, which)
            packed = enc
        size = os.path.getsize(packed)
        if size > MAX_BYTES:
            raise BackupError(f"백업 파일이 {fmt_size(size)}로 45 MB를 넘어 보내지 않았습니다 (텔레그램 한도 50 MB). "
                              "개발자에게 알려 주세요")
        name = file_name(now_ms, bool(passphrase))
        with open(packed, "rb") as fh:
            data = fh.read()
        cap = caption(now_ms, size, counts, bool(passphrase))
        ok, failed = [], []
        for c in chats:                    # every chat is tried, even after one failed
            say(f"텔레그램으로 보내는 중: {c} ({fmt_size(size)})")
            try:
                send_document(token, c, name, data, cap, sender=sender, sleep=sleep, clock=clock, deadline=deadline,
                              log=log)
            except BackupError as exc:
                failed.append((c, str(exc)))
                say(f"못 보냄: {c} · {exc}")
                continue
            ok.append(c)
            say(f"보냄: {c}")
        if failed and len(chats) == 1:
            raise BackupError(failed[0][1])
        if failed:
            what = "; ".join(f"{c}: {why}" for c, why in failed)
            raise BackupError(f"백업 파일을 {len(chats)}곳 중 {len(ok)}곳에만 보냈습니다. 보냄: {', '.join(ok) or '없음'} · "
                              f"못 보냄: {what}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"bytes": size, "tables": counts, "encrypted": bool(passphrase), "name": name, "chats": ok}


def cmd_send(cfg: Mapping[str, str], now_ms: Optional[int] = None, verbose: bool = False, out=print,
             **kw) -> int:
    """send / now: 0 when the backup went out and backup.json was written, else 1 (never raises)."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    token, passphrase = cfg.get("DEMOBOT_TG_TOKEN") or "", cfg.get(PASS_ENV) or ""
    snap = cfg.get("DEMOBOT_SNAP") or DEFAULT_SNAP
    say = out if verbose else (lambda s: None)
    try:
        res = run_send(cfg, now_ms, say=say, **kw)
    except Exception as exc:  # noqa: BLE001  (worded below; the unit fails visibly with exit 1)
        if isinstance(exc, BackupError):
            reason = redact(exc, token, passphrase)
        elif isinstance(exc, sqlite3.Error):
            reason = redact(f"데이터베이스를 읽지 못했습니다: {type(exc).__name__}: {exc}", token, passphrase)
        else:
            reason = redact(f"{type(exc).__name__}: {exc}", token, passphrase)
        reason = reason[:800]
        _stderr(f"demobot backup failed: {reason}")
        if verbose:
            out(f"백업하지 못했습니다: {reason}")
        try:
            write_status(snap, now_ms, False, error_ko=reason)
        except OSError as e2:
            _stderr(redact(f"demobot backup: cannot write {snap}/backup.json: {type(e2).__name__}: {e2}", token))
        return 1
    try:
        write_status(snap, now_ms, True, res["bytes"], res["tables"], res["encrypted"])
    except OSError as exc:
        _stderr(redact(f"demobot backup: sent, but cannot write {snap}/backup.json: {type(exc).__name__}: {exc}",
                       token))
        if verbose:
            out(f"보냈지만 {snap}/backup.json을 쓰지 못했습니다 (감시가 '백업 안 됨'으로 볼 수 있음)")
        return 1
    if not verbose:                # one line for the journal
        print(json.dumps({"backup": "sent", "bytes": res["bytes"], "tables": res["tables"],
                          "encrypted": res["encrypted"]}, ensure_ascii=False), flush=True)
    else:
        out(f"보냈습니다: {res['name']} ({fmt_size(res['bytes'])}, 암호화 {'예' if res['encrypted'] else '아니오'}, "
            f"{len(res['chats'])}곳)")
        out("텔레그램에서 💾 데모 랩 밤 백업 파일을 확인하세요.")
    return 0


# ---------------------------------------------------------------- restore
def integrity_check(path: str) -> str:
    """'ok', or what PRAGMA integrity_check (read-only, no -wal/-shm made) reported."""
    try:
        con = sqlite3.connect(_ro_uri(path, immutable=True), uri=True)
        try:
            rows = con.execute("PRAGMA integrity_check").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        return f"{type(exc).__name__}: {exc}"
    return "ok" if rows == [("ok",)] else "; ".join(str(r[0]) for r in rows[:5])


def systemd_state(unit: str, run=subprocess.run) -> Optional[str]:
    """`systemctl is-active UNIT`, or None when systemctl is missing or cannot talk to systemd."""
    try:
        r = run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    s = (r.stdout or "").strip().splitlines()
    s = s[0].strip() if s else ""
    return s if s in ("active", "reloading", "inactive", "failed", "activating", "deactivating", "maintenance",
                      "refreshing") else None


def merge(backup_db: str, db_path: str) -> dict:
    """INSERT OR REPLACE every table of ``backup_db`` (of ``TABLES``) into ``db_path`` (made when missing; a missing
    table is made from the backup's CREATE statement). Columns: those both sides have. One transaction.
    {table: rows in the backup} (tables the backup lacks are left out)."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    counts: dict = {}
    try:
        conn.execute("PRAGMA journal_mode=WAL")            # as demobot/store.connect
        conn.execute("ATTACH DATABASE ? AS bk", (backup_db,))
        bmaster = {r[0]: r[1] for r in conn.execute("SELECT name, sql FROM bk.sqlite_master WHERE type = 'table'")}
        conn.execute("BEGIN IMMEDIATE")
        try:
            have = {r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type = 'table'")}
            for t in TABLES:
                if t not in bmaster:
                    continue
                if t not in have:
                    conn.execute(bmaster[t])
                    for (isql,) in conn.execute("SELECT sql FROM bk.sqlite_master WHERE type = 'index' AND "
                                                "tbl_name = ? AND sql IS NOT NULL", (t,)).fetchall():
                        conn.execute(isql)
                mcols = set(_columns(conn, t, "main"))
                cols = [c for c in _columns(conn, t, "bk") if c in mcols]
                if not cols:
                    counts[t] = 0
                    continue
                names = ", ".join(_q(c) for c in cols)
                where, args = "", ()
                if t == "meta" and "k" in cols:
                    where = (f" WHERE k NOT IN ({', '.join('?' * len(META_SKIP))}) AND (k NOT IN "
                             f"({', '.join('?' * len(META_KEEP))}) OR k NOT IN (SELECT k FROM main.meta))")
                    args = (*META_SKIP, *META_KEEP)
                counts[t] = int(conn.execute(f"SELECT COUNT(*) FROM bk.{_q(t)}{where}", args).fetchone()[0])
                conn.execute(f"INSERT OR REPLACE INTO main.{_q(t)} ({names}) SELECT {names} FROM bk.{_q(t)}{where}",
                             args)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("DETACH DATABASE bk")
    finally:
        conn.close()
    return counts


def _chown_like_parent(db_path: str) -> None:
    """Run as root: give the database files the owner of their folder (the engine's user), so it can write them."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    st = os.stat(os.path.dirname(os.path.abspath(db_path)))
    if st.st_uid == 0:
        return
    for suf in ("", "-wal", "-shm"):
        p = db_path + suf
        if os.path.exists(p):
            os.chown(p, st.st_uid, st.st_gid)
            os.chmod(p, 0o640)


def unpack(file: str, work: str, passphrase_for: Callable[[], str], which: Callable = shutil.which) -> tuple:
    """(path of the SQLite file inside ``work``, encrypted?) from a backup file: openssl-encrypted, gzip, or plain."""
    with open(file, "rb") as fh:
        head = fh.read(16)
    encrypted = head.startswith(SALTED_MAGIC)
    cur = file
    if encrypted:
        passphrase = passphrase_for()
        if not passphrase:
            raise BackupError("암호화된 백업입니다: 암호(DEMOBOT_BACKUP_PASSPHRASE)가 필요합니다")
        cur = os.path.join(work, "backup.db.gz")
        decrypt(file, cur, passphrase, which)
        with open(cur, "rb") as fh:
            head = fh.read(16)
    out = os.path.join(work, "backup.db")
    if head.startswith(GZIP_MAGIC):
        try:
            with gzip.open(cur, "rb") as fi, open(out, "wb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
        except (OSError, EOFError, zlib.error) as exc:
            raise BackupError(f"압축을 풀지 못했습니다 ({type(exc).__name__}): 파일이 덜 받아졌거나 손상되었습니다") from None
    elif head.startswith(SQLITE_MAGIC):
        shutil.copyfile(cur, out)
    elif encrypted:
        # openssl's padding check lets about 1 wrong passphrase in 256 through: the result is noise
        raise BackupError("복호화한 내용이 백업이 아닙니다: 암호가 틀렸을 가능성이 큽니다. 암호를 다시 확인하세요")
    else:
        raise BackupError("데모 랩 백업 파일이 아닙니다 (demolab-….db.gz 또는 .db.gz.enc 파일을 쓰세요)")
    with open(out, "rb") as fh:
        if fh.read(16) != SQLITE_MAGIC:
            raise BackupError("압축을 푼 내용이 SQLite 파일이 아닙니다: 다른 파일이거나 손상되었습니다")
    return out, encrypted


def next_steps(db_path: str, created: bool, forced_live: bool) -> list:
    if created:
        return ["다음:",
                f"  1. 첫 채우기 (지난 26주 시세와 계산을 바이낸스에서 다시 만듦, 10~15분): sudo bash {KIT}/warm.sh",
                f"  2. 켜기: sudo bash {KIT}/on.sh",
                "  3. 봇에게 관점목록 을 보내 관점이 돌아왔는지 봅니다"]
    if forced_live:
        return ["엔진이 켜진 채로 넣었습니다. 다시 읽히도록 켜기를 한 번 더 합니다:",
                f"  sudo bash {KIT}/on.sh"]
    return ["다음:", f"  1. 켜기: sudo bash {KIT}/on.sh",
            "  2. 봇에게 관점목록 을 보내 관점이 돌아왔는지 봅니다"]


def cmd_restore(file: str, cfg: Mapping[str, str], force: bool = False, *, which: Callable = shutil.which,
                ask: Optional[Callable[[str], str]] = None, state: Callable[[str], Optional[str]] = systemd_state,
                out=print) -> int:
    """0 when the backup is in the database, else 1 (never raises; the passphrase and the token never printed)."""
    token, passphrase = cfg.get("DEMOBOT_TG_TOKEN") or "", cfg.get(PASS_ENV) or ""
    db_path = cfg.get("DEMOBOT_DB") or DEFAULT_DB
    asked: list = []

    def passphrase_for() -> str:
        if passphrase:
            return passphrase
        if ask is None:
            return ""
        got = ask("백업 암호 (DEMOBOT_BACKUP_PASSPHRASE, 화면에 안 보임): ")
        asked.append(got)
        return got

    if not os.path.isfile(file):
        out(f"파일이 없습니다: {file}")
        return 1
    live = state(LIVE_UNIT)
    running = live in ("active", "reloading", "activating", "deactivating", "refreshing")
    if running and not force:
        out("엔진(demobot-live)이 켜져 있어 되살리지 않았습니다. 먼저 끄세요:")
        out(f"  sudo bash {KIT}/off.sh")
        out("(꼭 켜진 채로 넣어야 하면 --force)")
        return 1
    if state("demobot-warm.service") in ("active", "activating"):
        out("첫 채우기(demobot-warm)가 도는 중입니다. 끝난 뒤 다시 하세요.")
        return 1
    work = tempfile.mkdtemp(prefix="demobot-restore-")
    created = False
    try:
        os.chmod(work, 0o700)
        bk, encrypted = unpack(file, work, passphrase_for, which)
        res = integrity_check(bk)
        out(f"백업 파일 확인 (integrity_check): {res}")
        if res != "ok":
            out("백업 파일이 손상되었습니다. 아무것도 바꾸지 않았습니다. 텔레그램에서 하루 전 백업을 받아 다시 해 보세요.")
            return 1
        created = not os.path.exists(db_path)
        counts = merge(bk, db_path)
        _chown_like_parent(db_path)
    except Exception as exc:  # noqa: BLE001
        if created:                # an empty database made by this try must not look like a restored one
            for suf in ("", "-wal", "-shm", "-journal"):
                try:
                    os.unlink(db_path + suf)
                except OSError:
                    pass
        secrets_ = [passphrase, *asked]
        if isinstance(exc, BackupError):
            reason = redact(exc, token, *secrets_)
        else:
            reason = redact(f"{type(exc).__name__}: {exc}", token, *secrets_)
        out(f"되살리지 못했습니다: {reason}")
        out("데이터베이스는 바뀌지 않았습니다 (한 번에 넣거나 아무것도 넣지 않음).")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out(f"되살렸습니다: {db_path}{' (새로 만듦)' if created else ''}{' · 암호 풀림' if encrypted else ''}")
    for t in TABLES:
        if t in counts:
            out(f"  {TABLE_KO.get(t, t):<10} {t:<10} {counts[t]:>8,}줄")
    missing = [t for t in TABLES if t not in counts]
    if missing:
        out(f"  (백업에 없던 표: {', '.join(missing)})")
    if live is None:
        out("(systemctl로 엔진 상태를 확인하지 못했습니다)")
    for ln in next_steps(db_path, created, running):
        out(ln)
    return 0


# ---------------------------------------------------------------- CLI
def main(argv=None, env: Optional[Mapping[str, str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot.backup",
                                 description="demo lab nightly backup to Telegram, and its restore")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("send", help="make the backup and send it (the nightly timer)")
    sub.add_parser("now", help="the same as send, once, by hand (says each step)")
    r = sub.add_parser("restore", help="put a backup file back into DEMOBOT_DB")
    r.add_argument("file")
    r.add_argument("--force", action="store_true", help="even while demobot-live.service runs")
    for p in sub.choices.values():
        p.add_argument("--env-file", default=ENV_FILE,
                       help="read the settings from here when they are not in the environment")
    a = ap.parse_args(argv)
    cfg = settings(env, a.env_file)
    if a.cmd in ("send", "now"):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            # root would leave root-owned -wal/-shm files next to demo.db that the engine cannot open
            print("root로 돌리지 않습니다. 이렇게 하세요:")
            print(f"  {APP_PY} -m demobot.backup {a.cmd}")
            return 2
        return cmd_send(cfg, verbose=a.cmd == "now")
    asker = getpass.getpass if sys.stdin.isatty() else None
    return cmd_restore(a.file, cfg, a.force, ask=asker)


if __name__ == "__main__":
    sys.exit(main())
