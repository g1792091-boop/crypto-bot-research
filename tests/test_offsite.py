"""Off-site copy of the nightly backup to Telegram (paperbot/offsite.py; docs/offsite-backup.md).

No test touches the network: every Telegram call goes to a fake sender, and urlopen and socket
connections raise if anything tries."""

import hashlib
import io
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import tarfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paperbot import offsite as off
from paperbot.notify import WARN, ListNotifier

REPO = Path(__file__).resolve().parents[1]
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijklmn"
CHAT_BACKUP = "-1009999"
CHAT_CRITICAL = "-1001111"
DATE = "20261001"
NOW = datetime(2026, 10, 1, 23, 59, tzinfo=timezone.utc)        # same UTC day as the folder
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_BACKUP": CHAT_BACKUP, "TELEGRAM_CHAT_CRITICAL": CHAT_CRITICAL}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to use the network")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


REAL_FREE_FLOOR = off.free_floor


@pytest.fixture(autouse=True)
def no_free_floor(monkeypatch):
    """The disk this test runs on is not the server's: the free-space floor is tested on its own."""
    monkeypatch.setattr(off, "free_floor", lambda total: 0)


def parse_multipart(body: bytes, ctype: str) -> tuple[dict, dict]:
    boundary = ctype.split("boundary=", 1)[1].encode()
    fields, files = {}, {}
    for chunk in body.split(b"--" + boundary)[1:]:
        if chunk.startswith(b"--"):
            break
        head, _, data = chunk[2:].partition(b"\r\n\r\n")
        data = data[:-2]                                   # the CRLF before the next boundary
        disp = head.decode().split("\r\n")[0]
        name = disp.split('name="', 1)[1].split('"', 1)[0]
        if 'filename="' in disp:
            files[name] = (disp.split('filename="', 1)[1].split('"', 1)[0], data)
        else:
            fields[name] = data.decode()
    return fields, files


class FakeTelegram:
    """Records every call; answers from ``script`` (status, json) or raises an exception from it,
    then answers ok."""

    def __init__(self, script=()):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        assert url.startswith(off.API + "/bot")
        method = url.rsplit("/", 1)[1]
        fields, files = parse_multipart(body, headers["Content-Type"])
        assert int(headers["Content-Length"]) == len(body)
        self.calls.append({"url": url, "method": method, "fields": fields, "files": files, "body_len": len(body)})
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, BaseException):
                raise step
            status, payload = step
            return status, json.dumps(payload).encode()
        return 200, json.dumps({"ok": True, "result": {"message_id": len(self.calls)}}).encode()

    def documents(self):
        return [c for c in self.calls if c["method"] == "sendDocument"]


def make_db(path: Path, rows: int, seed: int, blob: int = 256):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v BLOB, s TEXT)")
    con.execute("CREATE INDEX t_s ON t (s)")
    rnd = __import__("random").Random(seed)
    con.executemany("INSERT INTO t (v, s) VALUES (?, ?)",
                    [(rnd.randbytes(blob), f"row{i}") for i in range(rows)])
    con.commit()
    con.close()


def make_backup(tmp_path: Path, date=DATE, names=("agents3", "inbox", "paper3", "exec/executor"), rows=120):
    """Live databases in lib/, consistent copies (VACUUM INTO, as deploy/paperbot-backup.sh) in backups/<date>/."""
    lib, root = tmp_path / "lib", tmp_path / "backups"
    folder = root / date
    folder.mkdir(parents=True, exist_ok=True)
    for k, name in enumerate(names):
        src = lib / f"{name}.db"
        make_db(src, rows, seed=k)
        con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        con.execute("VACUUM INTO ?", (str(folder / (Path(name).name + ".db")),))
        con.close()
    return root, lib, folder


def no_zstd(name):
    return None if name == "zstd" else shutil.which(name)


def send(tmp_path, root, lib, fake, env=ENV, part_size=16 * 1024, which=no_zstd, sleeps=None, **kw):
    sleeps = [] if sleeps is None else sleeps
    return off.send_backup(root, "TELEGRAM_CHAT_BACKUP", lib=lib, part_size=part_size, env=env, sender=fake,
                           sleep=sleeps.append, now=NOW, which=which, work=tmp_path, log=lambda s: None,
                           out=lambda s: None, wait_s=0, **kw)


def save_downloads(fake: FakeTelegram, into: Path) -> list[Path]:
    """What the owners download from the chat: every document, under its file name."""
    into.mkdir(parents=True, exist_ok=True)
    paths = []
    for c in fake.documents():
        name, data = c["files"]["document"]
        (into / name).write_bytes(data)
        paths.append(into / name)
    return paths


# ---------------------------------------------------------------- splitting at the limit
def test_plan_parts_at_the_limit():
    P = 1000
    assert off.plan_parts(P, P) == [(0, P)]
    assert off.plan_parts(P - 1, P) == [(0, P - 1)]
    assert off.plan_parts(P + 1, P) == [(0, P), (P, 1)]
    assert off.plan_parts(3 * P, P) == [(0, P), (P, P), (2 * P, P)]
    plan = off.plan_parts(3 * P - 1, P)
    assert [n for _, n in plan] == [P, P, P - 1]
    assert all(o == i * P for i, (o, _) in enumerate(plan))
    with pytest.raises(ValueError):
        off.plan_parts(10, 0)


def test_default_part_fits_the_telegram_upload_limit():
    caption = "x" * off.CAPTION_LIMIT
    body, _ = off.multipart({"chat_id": CHAT_BACKUP, "caption": caption, "disable_notification": "true"},
                            ("document", "paperbot-20261001.tar.zst.enc.part99-of-99", b"z" * 10))
    overhead = len(body.decode("utf-8", "replace").encode()) - 10
    assert off.DEFAULT_PART + overhead < off.TELEGRAM_UPLOAD_LIMIT
    assert off.DEFAULT_PART <= off.MAX_PART < off.TELEGRAM_UPLOAD_LIMIT
    assert off.MULTIPART_ROOM > overhead


def test_part_size_above_the_limit_is_refused(tmp_path):
    root, lib, _ = make_backup(tmp_path)
    fake = FakeTelegram()
    with pytest.raises(off.OffsiteError, match="한도"):
        send(tmp_path, root, lib, fake, part_size=50 * 1024 * 1024)
    assert fake.calls == []
    notes = ListNotifier()
    rc = off.main(["send", "--from", str(root), "--lib", str(lib), "--part-mb", "50"], env=ENV, sender=fake,
                  sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd)
    assert rc == 1 and fake.calls == [] and notes.messages[0][0] == WARN


# ---------------------------------------------------------------- send: parts, captions, hashes
def test_send_splits_uploads_and_captions(tmp_path):
    root, lib, folder = make_backup(tmp_path)
    fake = FakeTelegram()
    P = 16 * 1024
    m = send(tmp_path, root, lib, fake, part_size=P)
    docs = fake.documents()
    n = len(m["parts"])
    assert n >= 3 and len(docs) == n + 1                          # parts, then the manifest
    payloads = [d["files"]["document"][1] for d in docs[:n]]
    whole = b"".join(payloads)
    assert len(whole) == m["size"] and hashlib.sha256(whole).hexdigest() == m["sha256"]
    assert all(len(p) == P for p in payloads[:-1]) and 0 < len(payloads[-1]) <= P
    assert m["archive"] == f"paperbot-{DATE}.tar.gz" and m["compression"] == "gzip" and not m["encrypted"]
    assert set(m["databases"]) == {"agents3.db", "inbox.db", "paper3.db", "executor.db"}
    for i, (d, part) in enumerate(zip(docs, m["parts"]), 1):
        f, (fname, data) = d["fields"], d["files"]["document"]
        assert f["chat_id"] == CHAT_BACKUP and f["disable_notification"] == "true"
        assert fname == part["name"] == f"paperbot-{DATE}.tar.gz.part{i:02d}-of-{n:02d}"
        cap = f["caption"]
        assert len(cap) <= off.CAPTION_LIMIT
        assert f"paperbot 백업 {DATE}" in cap and f"조각 {i}/{n}" in cap
        assert hashlib.sha256(data).hexdigest() == part["sha256"] and part["sha256"] in cap
        assert m["sha256"] in cap
        assert f"({len(data)} B)" in cap and f"({m['size']} B)" in cap
    last = docs[-1]
    assert last["files"]["document"][0] == f"paperbot-{DATE}.manifest.json"
    sent_manifest = json.loads(last["files"]["document"][1])
    assert sent_manifest == m and sent_manifest["format"] == off.MANIFEST_FORMAT
    summary = last["fields"]["caption"]
    assert "서버 밖 백업 완료" in summary and f"조각 {n}개" in summary and "참고" not in summary
    assert all(TOKEN not in json.dumps(c["fields"]) for c in fake.calls)


def test_one_part_when_the_archive_fits(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake, part_size=off.DEFAULT_PART)
    assert len(m["parts"]) == 1 and m["parts"][0]["name"].endswith(".part01-of-01")
    assert m["parts"][0]["sha256"] == m["sha256"]


def test_backup_chat_falls_back_to_critical_with_a_note(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram()
    env = {k: v for k, v in ENV.items() if k != "TELEGRAM_CHAT_BACKUP"}
    send(tmp_path, root, lib, fake, env=env)
    assert {c["fields"]["chat_id"] for c in fake.calls} == {CHAT_CRITICAL}
    assert "TELEGRAM_CHAT_BACKUP" in fake.documents()[-1]["fields"]["caption"]


def test_dry_run_needs_no_token_and_sends_nothing(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram()
    outs = []
    m = off.send_backup(root, lib=lib, part_size=16 * 1024, env={}, sender=fake, now=NOW, which=no_zstd,
                        work=tmp_path, log=lambda s: None, out=outs.append, wait_s=0, dry_run=True)
    assert fake.calls == [] and m["parts"]
    text = "\n".join(outs)
    assert "완료" not in text and "보낸 파일" not in text          # nothing was sent: no success line
    assert "dry run" in text and "아무것도 보내지 않음" in text and "보낼 파일" in text


def test_yesterdays_folder_is_taken_after_midnight_utc(tmp_path):
    # the backup runs 23:40 UTC (folder = that UTC day); the off-site copy runs at 00:15 UTC the next day
    root, lib, _ = make_backup(tmp_path, date="20260930", rows=5)
    after_midnight = datetime(2026, 10, 1, 0, 15, tzinfo=timezone.utc)
    assert off.find_folder(root, None, after_midnight).name == "20260930"
    (root / "20261001").mkdir()
    assert off.find_folder(root, None, after_midnight).name == "20261001"   # today's wins when present
    with pytest.raises(off.OffsiteError, match="없습니다"):
        off.find_folder(root, None, datetime(2026, 10, 3, 0, 15, tzinfo=timezone.utc))


# ---------------------------------------------------------------- missing / incomplete backup
def test_missing_folder_fails_with_warn_and_exit_1(tmp_path, capsys):
    root = tmp_path / "backups"
    (root / "20260920").mkdir(parents=True)                    # an old folder only
    notes, fake = ListNotifier(), FakeTelegram()
    rc = off.main(["send", "--from", str(root), "--lib", str(tmp_path / "lib")], env=ENV, sender=fake,
                  sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd)
    assert rc == 1 and fake.calls == []
    (level, text), = notes.messages
    assert level == WARN and "서버 밖 백업 실패" in text and "20260920" in text and "없습니다" in text
    assert "paperbot-backup" in capsys.readouterr().err


def test_folder_problems_are_listed_and_the_good_copies_kept(tmp_path):
    root, lib, folder = make_backup(tmp_path, rows=5)
    assert off.check_folder(folder, lib) == ({p.name: p.stat().st_size for p in sorted(folder.iterdir())}, [])
    (folder / "paper3.db").rename(folder / "paper3.db.part")    # the copy killed half-way (no paper3.db)
    waits = []
    files, problems = off.check_folder(folder, lib, wait_s=90, sleep=waits.append, poll_s=30, log=lambda s: None)
    assert waits == [30, 30, 30]                                   # waited for the writer, then went on
    assert set(files) == {"agents3.db", "inbox.db", "executor.db"}
    assert problems == [(off.UNFINISHED, "paper3.db.part"), (off.MISSING, "paper3.db")]
    (folder / "paper3.db.part").unlink()
    (folder / "inbox.db").write_bytes(b"not a database at all")
    files, problems = off.check_folder(folder, lib)
    assert set(files) == {"agents3.db", "executor.db"}
    assert problems == [(off.NOT_SQLITE, "inbox.db"), (off.MISSING, "inbox.db"), (off.MISSING, "paper3.db")]
    assert off.problems_text(problems) == (f"{off.NOT_SQLITE}: inbox.db; {off.MISSING}: inbox.db, paper3.db")


def test_a_failed_paper3_copy_still_sends_the_others_then_warns(tmp_path):
    # paper3's copy failed (the largest, copied last); agents3/inbox/executor still go off-site that day
    root, lib, folder = make_backup(tmp_path, rows=5)
    (folder / "paper3.db").unlink()
    notes, fake = ListNotifier(), FakeTelegram()
    rc = off.main(["send", "--from", str(root), "--lib", str(lib), "--wait-min", "0"], env=ENV, sender=fake,
                  sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd)
    assert rc == 1
    docs = fake.documents()
    manifest = json.loads(docs[-1]["files"]["document"][1])
    assert set(manifest["databases"]) == {"agents3.db", "inbox.db", "executor.db"}
    assert manifest["problems"] == [f"{off.MISSING}: paper3.db"]
    summary = docs[-1]["fields"]["caption"]
    assert "일부만" in summary and "완료" not in summary and "paper3.db" in summary
    (level, text), = notes.messages
    assert level == WARN and "서버 밖 백업 실패" in text and f"{off.MISSING}: paper3.db" in text
    assert "나머지 DB 3개" in text and "다음 날" in text                  # a new DB: included from tomorrow
    files = save_downloads(fake, tmp_path / "dl")
    out = tmp_path / "o"
    assert off.restore_backup(files, out, which=no_zstd, log=lambda s: None) == 0
    assert sorted(p.name for p in (out / DATE).iterdir()) == ["agents3.db", "executor.db", "inbox.db"]


def test_a_copy_finished_while_waiting_is_accepted(tmp_path):
    root, lib, folder = make_backup(tmp_path, rows=5)
    part = folder / "paper3.db.part"
    part.write_bytes(b"x")
    files, problems = off.check_folder(folder, lib, wait_s=300, sleep=lambda s: part.unlink(),
                                       log=lambda s: None)
    assert "paper3.db" in files and problems == []


def test_empty_folder_is_refused(tmp_path):
    (tmp_path / "b" / DATE).mkdir(parents=True)
    with pytest.raises(off.OffsiteError, match="비어"):
        off.check_folder(tmp_path / "b" / DATE, tmp_path / "lib")
    root, lib, folder = make_backup(tmp_path, names=("inbox",), rows=5)
    (folder / "inbox.db").write_bytes(b"junk")
    with pytest.raises(off.OffsiteError, match="보낼 만한 DB"):
        off.check_folder(folder, lib)


# ---------------------------------------------------------------- retries, 429, refusals
def test_retries_network_errors_429_and_5xx(capsys):
    fake = FakeTelegram([
        urllib.error.URLError("timed out"),
        (429, {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 7",
               "parameters": {"retry_after": 7}}),
        (502, {"ok": False, "description": "Bad Gateway"}),
        ConnectionResetError(104, "Connection reset by peer"),
    ])
    sleeps = []
    tg = off.Telegram(TOKEN, fake, sleeps.append)
    assert tg.call("sendDocument", {"chat_id": "1"}, ("document", "a", b"x")) == {"message_id": 5}
    assert sleeps == [5, 8, 45, 120]
    assert len(fake.calls) == 5
    assert TOKEN not in capsys.readouterr().err


def test_gives_up_after_the_last_attempt():
    fake = FakeTelegram([(500, {"ok": False, "description": "Internal"})] * 10)
    sleeps = []
    with pytest.raises(off.TelegramError, match="6번 모두 실패"):
        off.Telegram(TOKEN, fake, sleeps.append, log=lambda s: None).call("sendDocument", {})
    assert len(fake.calls) == 6 and sleeps == list(off.BACKOFF)


def test_a_refusal_is_not_retried_and_explained():
    fake = FakeTelegram([(400, {"ok": False, "description": "Bad Request: chat not found"})])
    with pytest.raises(off.TelegramError, match="봇이 그 단체방에 없습니다"):
        off.Telegram(TOKEN, fake, lambda s: None).call("sendDocument", {"chat_id": "1"})
    assert len(fake.calls) == 1
    fake = FakeTelegram([(400, {"ok": False, "description": "Bad Request: group chat was upgraded to a supergroup",
                                "parameters": {"migrate_to_chat_id": -1002222}})])
    with pytest.raises(off.TelegramError, match="-1002222"):
        off.Telegram(TOKEN, fake, lambda s: None).call("sendDocument", {"chat_id": "1"})


def test_a_very_long_retry_after_fails_instead_of_sleeping():
    fake = FakeTelegram([(429, {"ok": False, "description": "Too Many Requests",
                                "parameters": {"retry_after": 3600}})])
    sleeps = []
    with pytest.raises(off.TelegramError, match="3600"):
        off.Telegram(TOKEN, fake, sleeps.append).call("sendDocument", {})
    assert sleeps == []


def test_upload_retried_inside_a_send(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram([TimeoutError("read timed out"),
                         (429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 3}})])
    sleeps = []
    m = send(tmp_path, root, lib, fake, sleeps=sleeps)
    assert sleeps == [5, 4]
    first = [c for c in fake.documents() if c["files"]["document"][0] == m["parts"][0]["name"]]
    assert len(first) == 3                                         # the same part, three attempts


# ---------------------------------------------------------------- token redaction
def test_redact_hides_the_token_in_every_form():
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    for text in (url, f"error at {TOKEN}", urllib.request.quote(url, safe=""), f"bot{TOKEN} trailing",
                 "other 987654321:ZZanotherTokenShapedValue_123456"):
        out = off.redact(text, TOKEN)
        assert TOKEN not in out and "AAFakeToken" not in out and "ZZanother" not in out and "<token>" in out
    assert off.redact("sha256 " + "ab" * 32, TOKEN) == "sha256 " + "ab" * 32


def test_token_never_printed_or_sent_in_a_failure(tmp_path, capsys):
    root, lib, _ = make_backup(tmp_path, rows=5)

    def leaky(url, body, headers, timeout):            # an error message that quotes the whole URL
        raise OSError(f"connection to {url} failed")

    notes = ListNotifier()
    rc = off.main(["send", "--from", str(root), "--lib", str(lib)], env=ENV, sender=leaky,
                  sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd)
    assert rc == 1
    err = capsys.readouterr()
    assert TOKEN not in err.err and TOKEN not in err.out and "<token>" in err.err
    (level, text), = notes.messages
    assert level == WARN and TOKEN not in text and "<token>" in text and DATE in text


def test_unexpected_error_traceback_is_redacted(tmp_path, capsys):
    root, lib, _ = make_backup(tmp_path, rows=5)

    def broken(url, body, headers, timeout):
        raise RuntimeError(f"bug while posting to {url}")

    notes = ListNotifier()
    assert off.main(["send", "--from", str(root), "--lib", str(lib)], env=ENV, sender=broken,
                    sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd) == 1
    err = capsys.readouterr().err
    assert "Traceback" in err and "RuntimeError" in err and TOKEN not in err
    assert TOKEN not in notes.messages[0][1]


def test_bad_token_shape_is_refused_without_printing_it(tmp_path, capsys):
    root, lib, _ = make_backup(tmp_path, rows=5)
    notes, fake = ListNotifier(), FakeTelegram()
    env = {**ENV, "TELEGRAM_BOT_TOKEN": "'" + TOKEN + "'"}
    assert off.main(["send", "--from", str(root), "--lib", str(lib)], env=env, sender=fake,
                    sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd) == 1
    assert fake.calls == [] and "모양" in notes.messages[0][1]
    assert TOKEN not in capsys.readouterr().err


# ---------------------------------------------------------------- failure: WARN and exit 1
def test_upload_failure_sends_warn_and_exits_1(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram([(503, {"ok": False, "description": "Service Unavailable"})] * 6)
    notes, sleeps = ListNotifier(), []
    rc = off.main(["send", "--from", str(root), "--lib", str(lib)], env=ENV, sender=fake,
                  sleep=sleeps.append, notifier=notes, now=NOW, which=no_zstd)
    assert rc == 1 and sleeps == list(off.BACKOFF)
    (level, text), = notes.messages
    assert level == WARN and "서버 밖 백업 실패" in text and "journalctl -u paperbot-offsite" in text
    assert "503" in text


def test_success_exits_0_without_warn(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    notes, fake = ListNotifier(), FakeTelegram()
    rc = off.main(["send", "--from", str(root), "--lib", str(lib), "--work", str(tmp_path)], env=ENV,
                  sender=fake, sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd)
    assert rc == 0 and notes.messages == [] and len(fake.documents()) == 2
    assert not list(tmp_path.glob("paperbot-offsite-*"))          # the temporary folder is removed


# ---------------------------------------------------------------- restore
def test_restore_round_trip_with_integrity_check(tmp_path, capsys):
    root, lib, folder = make_backup(tmp_path)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake)
    files = save_downloads(fake, tmp_path / "dl")
    # Telegram Desktop may rename a download ("name (1)"); parts are matched by sha256, not by name
    renamed = files[1].with_name(files[1].name + " (1)")
    files[1].rename(renamed)
    files[1] = renamed
    out = tmp_path / "restored"
    rc = off.main(["restore", "--parts", *map(str, reversed(files)), "--out", str(out)], env={}, which=no_zstd)
    assert rc == 0
    for name in m["databases"]:
        assert (out / DATE / name).read_bytes() == (folder / name).read_bytes()
        assert off.integrity_check(out / DATE / name) == "ok"
    assert not list(out.glob(".offsite-restore-*")) and sorted(p.name for p in (out / DATE).iterdir()) == \
        sorted(m["databases"])
    text = capsys.readouterr().out
    assert "integrity_check ok" in text and "다음 순서" in text
    assert "/var/lib/paperbot/exec/executor.db" in text and f"{out / DATE / 'paper3.db'}" in text


def test_restore_without_manifest_needs_the_sha256(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake)
    parts = [p for p in save_downloads(fake, tmp_path / "dl") if not p.name.endswith(".json")]
    with pytest.raises(off.OffsiteError, match="--sha256"):
        off.restore_backup(parts, tmp_path / "o1", which=no_zstd, log=lambda s: None)
    assert off.restore_backup(parts, tmp_path / "o2", sha256=m["sha256"], which=no_zstd, log=lambda s: None) == 0
    assert (tmp_path / "o2" / DATE / "paper3.db").exists()


def test_restore_detects_a_damaged_or_missing_part(tmp_path):
    root, lib, _ = make_backup(tmp_path)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake)
    files = save_downloads(fake, tmp_path / "dl")
    data = bytearray(files[1].read_bytes())
    data[10] ^= 0xFF
    files[1].write_bytes(bytes(data))
    with pytest.raises(off.OffsiteError, match="2번"):
        off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None)
    with pytest.raises(off.OffsiteError, match="1번"):
        off.restore_backup(files[1:], tmp_path / "o", which=no_zstd, log=lambda s: None)
    parts = [p for p in files if not p.name.endswith(".json")]
    with pytest.raises(off.OffsiteError, match="sha256"):
        off.restore_backup(parts, tmp_path / "o", sha256=m["sha256"], which=no_zstd, log=lambda s: None)
    assert not (tmp_path / "o" / DATE).exists()


def test_restore_reports_a_corrupt_database(tmp_path, capsys):
    root, lib, folder = make_backup(tmp_path, names=("paper3",), rows=400)
    db = folder / "paper3.db"
    raw = bytearray(db.read_bytes())
    page = 4096
    for off_ in range(2 * page, min(len(raw), 6 * page)):           # garbage over b-tree pages, header kept
        raw[off_] = (off_ * 37) & 0xFF
    db.write_bytes(bytes(raw))
    fake = FakeTelegram()
    send(tmp_path, root, lib, fake)
    files = save_downloads(fake, tmp_path / "dl")
    rc = off.main(["restore", "--parts", *map(str, files), "--out", str(tmp_path / "o")], env={}, which=no_zstd)
    assert rc == 1
    text = capsys.readouterr().out
    assert "손상" in text and "integrity_check ok" not in text and "다음 순서" not in text


def _hand_made_backup(tmp_path, members):
    """A tar.gz with the given (name, bytes) members, as one part plus its manifest."""
    arc = tmp_path / f"paperbot-{DATE}.tar.gz"
    with tarfile.open(arc, "w:gz") as tar:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    blob = arc.read_bytes()
    part = tmp_path / f"{arc.name}.part01-of-01"
    part.write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    manifest = {"format": off.MANIFEST_FORMAT, "date": DATE, "archive": arc.name, "compression": "gzip",
                "encrypted": False, "size": len(blob), "sha256": sha,
                "parts": [{"index": 1, "name": part.name, "offset": 0, "size": len(blob), "sha256": sha}]}
    mf = tmp_path / f"paperbot-{DATE}.manifest.json"
    mf.write_text(json.dumps(manifest))
    return [part, mf]


def test_restore_refuses_unsafe_paths_in_the_archive(tmp_path):
    db = b"SQLite format 3\x00" + b"\x00" * 100
    (tmp_path / "a").mkdir()
    files = _hand_made_backup(tmp_path / "a", [(f"{DATE}/inbox.db", db), ("../../evil.db", db)])
    with pytest.raises(off.OffsiteError, match="이상한 경로"):
        off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None)
    assert not (tmp_path / "evil.db").exists() and not (tmp_path.parent / "evil.db").exists()
    assert not (tmp_path / "o" / DATE).exists()                   # the half-unpacked folder is removed
    (tmp_path / "b").mkdir()
    files = _hand_made_backup(tmp_path / "b", [(f"{DATE}/inbox.db", db), ("other/inbox.db", db)])
    with pytest.raises(off.OffsiteError, match="두 번"):
        off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None)
    (tmp_path / "c").mkdir()
    files = _hand_made_backup(tmp_path / "c", [(f"{DATE}/notes.txt", b"hello")])
    with pytest.raises(off.OffsiteError, match="데이터베이스가 아닌"):
        off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None)


def test_restore_will_not_overwrite_an_earlier_restore(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram()
    send(tmp_path, root, lib, fake)
    files = save_downloads(fake, tmp_path / "dl")
    assert off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None) == 0
    with pytest.raises(off.OffsiteError, match="이미 있고"):
        off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None)


# ---------------------------------------------------------------- encryption (openssl CLI only)
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


@needs_openssl
def test_encrypted_round_trip(tmp_path):
    root, lib, folder = make_backup(tmp_path)
    fake = FakeTelegram()
    env = {**ENV, "BACKUP_PASSPHRASE": "correct horse battery staple"}
    m = send(tmp_path, root, lib, fake, env=env)
    assert m["encrypted"] and m["archive"].endswith(".tar.gz.enc") and m["cipher"] == off.CIPHER
    assert "-iter 200000" in m["cipher"] and "-pbkdf2" in m["cipher"]
    whole = b"".join(d["files"]["document"][1] for d in fake.documents()[:-1])
    assert whole.startswith(b"Salted__")                           # openssl's salted format
    assert b"SQLite format 3" not in whole and b"row1" not in whole
    assert "암호화 openssl" in fake.documents()[0]["fields"]["caption"]
    files = save_downloads(fake, tmp_path / "dl")
    with pytest.raises(off.OffsiteError, match="BACKUP_PASSPHRASE"):
        off.restore_backup(files, tmp_path / "o0", env={}, which=no_zstd, log=lambda s: None)
    with pytest.raises(off.OffsiteError, match="암호"):
        off.restore_backup(files, tmp_path / "o1", env={"BACKUP_PASSPHRASE": "wrong"}, which=no_zstd,
                           log=lambda s: None)
    asked = []
    rc = off.restore_backup(files, tmp_path / "o2", env={}, which=no_zstd, log=lambda s: None,
                            ask=lambda prompt: asked.append(prompt) or "correct horse battery staple")
    assert rc == 0 and asked
    assert (tmp_path / "o2" / DATE / "paper3.db").read_bytes() == (folder / "paper3.db").read_bytes()


def test_passphrase_without_openssl_is_refused(tmp_path, capsys):
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake, notes = FakeTelegram(), ListNotifier()

    def nothing(name):
        return None

    env = {**ENV, "BACKUP_PASSPHRASE": "secret passphrase"}
    rc = off.main(["send", "--from", str(root), "--lib", str(lib)], env=env, sender=fake,
                  sleep=lambda s: None, notifier=notes, now=NOW, which=nothing)
    assert rc == 1 and fake.calls == []
    assert "openssl" in notes.messages[0][1] and "secret passphrase" not in capsys.readouterr().err


# ---------------------------------------------------------------- compression
def test_gzip_when_zstd_is_missing(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    m = send(tmp_path, root, lib, FakeTelegram(), which=no_zstd)
    assert m["compression"] == "gzip" and m["archive"].endswith(".tar.gz")
    with pytest.raises(off.OffsiteError, match="zstd"):
        send(tmp_path, root, lib, FakeTelegram(), which=no_zstd, compression="zstd")


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd not installed")
def test_zstd_round_trip(tmp_path):
    root, lib, folder = make_backup(tmp_path)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake, which=shutil.which)
    assert m["compression"] == "zstd" and m["archive"].endswith(".tar.zst")
    files = save_downloads(fake, tmp_path / "dl")
    assert off.restore_backup(files, tmp_path / "o", which=shutil.which, log=lambda s: None) == 0
    assert (tmp_path / "o" / DATE / "agents3.db").read_bytes() == (folder / "agents3.db").read_bytes()


@needs_openssl
@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd not installed")
def test_zstd_and_encryption_stream_into_one_archive(tmp_path):
    # tar -> zstd -> openssl is one pipe: the work folder only ever holds the encrypted archive
    root, lib, folder = make_backup(tmp_path)
    seen = []

    def sender(url, body, headers, timeout):
        seen.append(sorted(p.name for w in tmp_path.glob("paperbot-offsite-*") for p in w.iterdir()))
        return 200, json.dumps({"ok": True, "result": {}}).encode()

    fake = FakeTelegram()

    def both(*a):
        sender(*a)
        return fake(*a)

    env = {**ENV, "BACKUP_PASSPHRASE": "zstd-and-openssl-passphrase"}
    m = send(tmp_path, root, lib, both, env=env, which=shutil.which)
    assert m["archive"] == f"paperbot-{DATE}.tar.zst.enc" and m["compression"] == "zstd" and m["encrypted"]
    assert all(names == [m["archive"]] for names in seen)
    files = save_downloads(fake, tmp_path / "dl")
    assert b"".join(f.read_bytes() for f in files[:-1]).startswith(b"Salted__")
    assert off.restore_backup(files, tmp_path / "o", env={"BACKUP_PASSPHRASE": "zstd-and-openssl-passphrase"},
                              which=shutil.which, log=lambda s: None) == 0
    for name in m["databases"]:
        assert (tmp_path / "o" / DATE / name).read_bytes() == (folder / name).read_bytes()


def test_a_failing_compressor_fails_the_send(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    broken = tmp_path / "zstd"
    broken.write_text("#!/bin/sh\necho 'zstd: out of space' >&2\nexit 1\n")
    broken.chmod(0o755)
    fake = FakeTelegram()
    with pytest.raises(off.OffsiteError, match="zstd 압축 실패 \\(exit 1\\): zstd: out of space"):
        send(tmp_path, root, lib, fake, which=lambda n: str(broken) if n == "zstd" else shutil.which(n))
    assert fake.calls == [] and not list(tmp_path.glob("paperbot-offsite-*"))


# ---------------------------------------------------------------- chats
def test_chats_lists_ids_and_titles(capsys):
    fake = FakeTelegram([(200, {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": -4123, "title": "paperbot 알림", "type": "group"}}},
        {"update_id": 2, "my_chat_member": {"chat": {"id": -4567, "title": "paperbot 백업", "type": "group"}}},
    ]})])
    assert off.main(["chats"], env=ENV, sender=fake, sleep=lambda s: None) == 0
    out = capsys.readouterr().out
    assert "-4567" in out and "paperbot 백업" in out and "-4123" in out and TOKEN not in out
    assert fake.calls[0]["method"] == "getUpdates"


# ---------------------------------------------------------------- a run that systemd stops
def test_sigterm_during_an_upload_sends_one_warn_and_exits_1(tmp_path):
    # TimeoutStartSec, a reboot or `systemctl stop`: Python's default would end the run silently
    root, lib, _ = make_backup(tmp_path, rows=5)
    before = signal.getsignal(signal.SIGTERM)
    calls = []

    def stalled(url, body, headers, timeout):
        calls.append(url)
        os.kill(os.getpid(), signal.SIGTERM)
        raise AssertionError("SIGTERM did not interrupt the upload")

    notes = ListNotifier()
    rc = off.main(["send", "--from", str(root), "--lib", str(lib), "--work", str(tmp_path)], env=ENV,
                  sender=stalled, sleep=lambda s: None, notifier=notes, now=NOW, which=no_zstd)
    assert rc == 1 and len(calls) == 1                       # no retry after the stop
    (level, text), = notes.messages
    assert level == WARN and "SIGTERM" in text and "시간 제한" in text and DATE in text
    assert signal.getsignal(signal.SIGTERM) == before        # the previous handler is back
    assert not list(tmp_path.glob("paperbot-offsite-*"))


def test_the_retries_stop_inside_the_time_limit():
    # 6 attempts x 300 s + 485 s of backoff would be 2285 s: the run limit stops it in time instead
    t = [0.0]
    timeouts = []

    def slow(url, body, headers, timeout):
        timeouts.append(timeout)
        t[0] += timeout                                       # every attempt runs into its timeout
        raise TimeoutError("timed out")

    def sleep(s):
        t[0] += s

    tg = off.Telegram(TOKEN, slow, sleep, log=lambda s: None, deadline=1500.0, clock=lambda: t[0])
    with pytest.raises(off.TelegramError, match="시간 제한") as e:
        tg.call("sendDocument", {"chat_id": "1"}, ("document", "a", b"x"))
    assert t[0] <= 1500 and "TimeoutError" in str(e.value) and TOKEN not in str(e.value)
    assert timeouts[0] == off.UPLOAD_TIMEOUT and all(x >= off.MIN_ATTEMPT_S for x in timeouts)
    assert timeouts[-1] < off.UPLOAD_TIMEOUT                 # the last attempt was shortened to fit
    t[0] = 0.0                                                # a 429 wait that does not fit is not slept
    fake = FakeTelegram([(429, {"ok": False, "description": "Too Many Requests",
                                "parameters": {"retry_after": 600}})])
    slept = []
    tg = off.Telegram(TOKEN, fake, slept.append, log=lambda s: None, deadline=300.0, clock=lambda: t[0])
    with pytest.raises(off.TelegramError, match="시간 제한"):
        tg.call("sendDocument", {})
    assert slept == [] and len(fake.calls) == 1


def test_a_send_past_its_time_limit_warns(tmp_path):
    root, lib, _ = make_backup(tmp_path, rows=5)
    t = [0.0]

    def slow(url, body, headers, timeout):
        t[0] += timeout
        raise TimeoutError("timed out")

    with pytest.raises(off.TelegramError, match="시간 제한"):
        send(tmp_path, root, lib, slow, clock=lambda: t[0], max_s=600)
    assert t[0] <= 600
    assert off.RUN_LIMIT_S < 60 * 60                          # below the unit's TimeoutStartSec=60min


def test_stopped_hook_warns_only_when_systemd_killed_the_run():
    for env in ({"SERVICE_RESULT": "success", "EXIT_CODE": "exited", "EXIT_STATUS": "0"},
                {"SERVICE_RESULT": "exit-code", "EXIT_CODE": "exited", "EXIT_STATUS": "1"},   # main warned
                {"SERVICE_RESULT": "timeout", "EXIT_CODE": "exited", "EXIT_STATUS": "1"},     # SIGTERM path
                {}):
        notes = ListNotifier()
        assert off.main(["stopped"], env={**ENV, **env}, notifier=notes) == 0 and notes.messages == []
    notes = ListNotifier()
    env = {**ENV, "SERVICE_RESULT": "oom-kill", "EXIT_CODE": "killed", "EXIT_STATUS": "KILL"}
    assert off.main(["stopped"], env=env, notifier=notes) == 0
    (level, text), = notes.messages
    assert level == WARN and "메모리" in text and "oom-kill" in text and "journalctl -u paperbot-offsite" in text
    notes = ListNotifier()
    off.main(["stopped"], env={**ENV, "SERVICE_RESULT": "timeout", "EXIT_CODE": "killed", "EXIT_STATUS": "KILL"},
             notifier=notes)
    assert len(notes.messages) == 1 and "강제로 멈춰졌습니다" in notes.messages[0][1]


# ---------------------------------------------------------------- restore: folders, wrong passphrase
def test_restore_takes_a_folder_with_subfolders_and_strays(tmp_path):
    # Telegram Desktop saves a clicked file into Downloads/Telegram Desktop; scp -r copies folders
    root, lib, folder = make_backup(tmp_path)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake)
    dl = tmp_path / "restore-in"
    files = save_downloads(fake, dl / "Telegram Desktop")
    (dl / "desktop.ini").write_text("[.ShellClassInfo]")
    (dl / ".DS_Store").write_bytes(b"\0" * 10)
    out = tmp_path / "o"
    logs = []
    assert off.restore_backup([dl], out, which=no_zstd, log=logs.append) == 0
    assert (out / DATE / "paper3.db").read_bytes() == (folder / "paper3.db").read_bytes()
    assert any("desktop.ini" in s and "참고" in s for s in logs)
    for f in files:                                          # without the manifest: by name, strays skipped
        if f.name.endswith(".json"):
            f.unlink()
    logs = []
    assert off.restore_backup([dl], tmp_path / "o2", sha256=m["sha256"][:16], which=no_zstd,
                              log=logs.append) == 0
    assert any("desktop.ini" in s for s in logs)
    rc = off.main(["restore", "--parts", str(dl), "--out", str(tmp_path / "o3"), "--sha256", m["sha256"]],
                  env={}, which=no_zstd)
    assert rc == 0
    with pytest.raises(off.OffsiteError, match="폴더 이름만"):    # a glob the shell could not expand
        off.restore_backup([dl / "*"], tmp_path / "o4", which=no_zstd, log=lambda s: None)
    (tmp_path / "empty").mkdir()
    with pytest.raises(off.OffsiteError, match="비어"):
        off.restore_backup([tmp_path / "empty"], tmp_path / "o5", which=no_zstd, log=lambda s: None)


@needs_openssl
def test_a_wrong_passphrase_that_passes_openssl_is_named(tmp_path, monkeypatch):
    # about 1 wrong passphrase in 256 passes openssl's padding check and "decrypts" to noise
    root, lib, _ = make_backup(tmp_path, rows=5)
    fake = FakeTelegram()
    send(tmp_path, root, lib, fake, env={**ENV, "BACKUP_PASSPHRASE": "the-right-passphrase-123"})
    files = save_downloads(fake, tmp_path / "dl")

    def lucky_wrong(args, passphrase, which, what):
        Path(args[args.index("-out") + 1]).write_bytes(os.urandom(4096))

    monkeypatch.setattr(off, "openssl_run", lucky_wrong)
    with pytest.raises(off.OffsiteError, match="암호") as e:
        off.restore_backup(files, tmp_path / "o", env={"BACKUP_PASSPHRASE": "wrong-139-passphrase"},
                           which=no_zstd, log=lambda s: None)
    assert "압축 풀기 실패" in str(e.value) and "sha256" in str(e.value)
    assert not (tmp_path / "o" / DATE).exists()


def test_an_unreadable_unencrypted_archive_does_not_blame_a_passphrase(tmp_path):
    db = b"SQLite format 3\x00" + b"\x00" * 100
    files = _hand_made_backup(tmp_path, [(f"{DATE}/inbox.db", db)])
    noise = os.urandom(2048)
    files[0].write_bytes(noise)
    m = json.loads(files[1].read_text())
    sha = hashlib.sha256(noise).hexdigest()
    m.update(size=len(noise), sha256=sha)
    m["parts"][0].update(size=len(noise), sha256=sha)
    files[1].write_text(json.dumps(m))
    with pytest.raises(off.UnpackError) as e:
        off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None)
    assert "암호" not in str(e.value)


# ---------------------------------------------------------------- secrets stay out of child processes
@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd not installed")
def test_zstd_gets_no_token_passphrase_or_exchange_key(tmp_path, monkeypatch):
    dump = tmp_path / "zstd-env.txt"
    wrapper = tmp_path / "zstd"
    wrapper.write_text(f"#!/bin/sh\nenv >> {dump}\nexec {shutil.which('zstd')} \"$@\"\n")
    wrapper.chmod(0o755)
    secret = "binance-secret-value-0123456789"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BACKUP_PASSPHRASE", "passphrase-for-the-env-test")
    monkeypatch.setenv("BINANCE_API_SECRET", secret)

    def which(name):
        return str(wrapper) if name == "zstd" else shutil.which(name)

    root, lib, folder = make_backup(tmp_path, rows=5)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake, env=dict(os.environ, **ENV), which=which)
    assert m["compression"] == "zstd"
    files = save_downloads(fake, tmp_path / "dl")
    assert off.restore_backup(files, tmp_path / "o", env=os.environ, which=which, log=lambda s: None) == 0
    seen = dump.read_text()
    assert seen.count("PATH=") >= 2                          # both the pack and the unpack ran the wrapper
    for value in (TOKEN, "passphrase-for-the-env-test", secret):
        assert value not in seen


def test_redact_also_hides_the_passphrase():
    text = off.redact(f"failed with long-passphrase-value and {TOKEN}", TOKEN, "long-passphrase-value")
    assert "long-passphrase-value" not in text and TOKEN not in text and "<secret>" in text
    assert off.redact("short", TOKEN, "") == "short"


# ---------------------------------------------------------------- copies replaced while packing, disk
def test_a_copy_replaced_while_packing_is_archived_whole(tmp_path, monkeypatch):
    # paperbot-backup.sh renames a new copy over the old one (a manual run): the archive must hold one
    # whole file, never the old size cut from the new file
    root, lib, folder = make_backup(tmp_path, names=("paper3",), rows=50)
    old = (folder / "paper3.db").read_bytes()
    bigger = tmp_path / "bigger.db"
    make_db(bigger, 2000, seed=9)
    real = tarfile.TarFile.gettarinfo

    def gettarinfo(self, *a, **k):
        ti = real(self, *a, **k)
        os.replace(bigger, folder / "paper3.db")             # the atomic rename, between stat and read
        return ti

    monkeypatch.setattr(tarfile.TarFile, "gettarinfo", gettarinfo)
    fake = FakeTelegram()
    m = send(tmp_path, root, lib, fake)
    monkeypatch.setattr(tarfile.TarFile, "gettarinfo", real)
    assert m["databases"] == {"paper3.db": len(old)}
    files = save_downloads(fake, tmp_path / "dl")
    assert off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None) == 0
    assert (tmp_path / "o" / DATE / "paper3.db").read_bytes() == old


def test_disk_space_floor_protects_the_live_databases(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "free_floor", REAL_FREE_FLOOR)
    G = 1024 ** 3
    assert off.free_floor(160 * G) == 16 * G and off.free_floor(10 * G) == 2 * G
    root, lib, folder = make_backup(tmp_path, rows=5)
    raw = sum(p.stat().st_size for p in folder.iterdir())
    usage = shutil._ntuple_diskusage if hasattr(shutil, "_ntuple_diskusage") else None

    def disk(free, total=160 * G):
        def du(path):
            return usage(total, total - free, free) if usage else type("U", (), {"total": total, "free": free})()
        return du

    # the old check (free >= raw + 64 MB) passed here and could fill the disk under paperbot-live3
    monkeypatch.setattr(off.shutil, "disk_usage", disk(raw + 64 * 1024 * 1024 + 1))
    fake = FakeTelegram()
    with pytest.raises(off.OffsiteError, match="디스크 여유"):
        send(tmp_path, root, lib, fake)
    assert fake.calls == []
    monkeypatch.setattr(off.shutil, "disk_usage", disk(16 * G + raw + 2 * 1024 * 1024))
    send(tmp_path, root, lib, fake)
    files = save_downloads(fake, tmp_path / "dl")
    monkeypatch.setattr(off.shutil, "disk_usage", disk(16 * G))     # a practice restore on the live server
    with pytest.raises(off.OffsiteError, match="디스크 여유"):
        off.restore_backup(files, tmp_path / "o", which=no_zstd, log=lambda s: None)
    assert not (tmp_path / "o" / DATE).exists()


# ---------------------------------------------------------------- the deploy files
def test_db_list_matches_the_backup_script():
    sh = (REPO / "deploy" / "paperbot-backup.sh").read_text(encoding="utf-8")
    loop, = re.findall(r"^for f in (.+); do$", sh, re.M)
    assert tuple(loop.split()) == off.DB_NAMES


def test_offsite_unit_is_read_only_and_keeps_secrets_out():
    unit = (REPO / "deploy" / "paperbot-offsite.service").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in unit.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    kv = {}
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            kv.setdefault(k, []).append(v)
    assert kv["User"] == ["paperbot"] and kv["ProtectSystem"] == ["strict"] and "ReadWritePaths" not in kv
    assert kv["EnvironmentFile"] == ["/etc/paperbot/live.env"]
    hidden = " ".join(kv["InaccessiblePaths"]).split()
    assert "-/etc/paperbot" in hidden and "-/var/lib/paperbot/.claude" in hidden
    assert {"BINANCE_API_KEY", "BINANCE_API_SECRET", "DEADMAN_URL"} <= set(" ".join(kv["UnsetEnvironment"]).split())
    assert kv["ExecStart"][0].endswith("-m paperbot.offsite send --from /var/backups/paperbot "
                                       "--chat-env TELEGRAM_CHAT_BACKUP --lib /var/lib/paperbot")
    stop_post, = kv["ExecStopPost"]
    assert stop_post.startswith("-") and stop_post.endswith("-m paperbot.offsite stopped")
    limit, = kv["TimeoutStartSec"]
    assert limit == "60min" and off.RUN_LIMIT_S + 5 * 60 <= 60 * 60
    assert kv["LimitCORE"] == ["0"] and kv["UMask"] == ["0077"] and kv["NoNewPrivileges"] == ["yes"]
    timer = (REPO / "deploy" / "paperbot-offsite.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 00:15:00 UTC" in timer and "Persistent=true" in timer


def test_next_steps_check_after_the_start_not_before():
    text = off.next_steps(Path("/root/restore-out/20261001"), ["paper3.db", "executor.db"])
    assert "--stage after" in text and "paperbot-offsite.timer" in text
    assert "10번(--stage before)은 하지 않습니다" in text
