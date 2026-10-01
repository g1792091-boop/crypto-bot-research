"""Off-site copy of the nightly backup to Telegram (paperbot/offsite.py; docs/offsite-backup.md).

No test touches the network: every Telegram call goes to a fake sender, and urlopen and socket
connections raise if anything tries."""

import hashlib
import io
import json
import os
import shutil
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
    m = send(tmp_path, root, lib, fake, env={}, dry_run=True)
    assert fake.calls == [] and m["parts"]


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


def test_incomplete_folder_is_refused(tmp_path):
    root, lib, folder = make_backup(tmp_path, rows=5)
    (folder / "paper3.db.part").write_bytes(b"half")
    with pytest.raises(off.OffsiteError, match="끝나지 않았습니다"):
        off.check_complete(folder, lib)
    waits = []
    with pytest.raises(off.OffsiteError, match="paper3.db.part"):
        off.check_complete(folder, lib, wait_s=90, sleep=waits.append, poll_s=30, log=lambda s: None)
    assert waits == [30, 30, 30]
    (folder / "paper3.db.part").unlink()
    (folder / "inbox.db").unlink()                             # exists on the server, no copy
    with pytest.raises(off.OffsiteError, match="inbox.db"):
        off.check_complete(folder, lib)
    make_db(lib / "inbox.db", 1, 0) if not (lib / "inbox.db").exists() else None
    (folder / "inbox.db").write_bytes(b"not a database at all")
    with pytest.raises(off.OffsiteError, match="SQLite"):
        off.check_complete(folder, lib)


def test_a_copy_finished_while_waiting_is_accepted(tmp_path):
    root, lib, folder = make_backup(tmp_path, rows=5)
    part = folder / "paper3.db.part"
    part.write_bytes(b"x")
    files = off.check_complete(folder, lib, wait_s=300, sleep=lambda s: part.unlink(), log=lambda s: None)
    assert "paper3.db" in files


def test_empty_folder_is_refused(tmp_path):
    (tmp_path / "b" / DATE).mkdir(parents=True)
    with pytest.raises(off.OffsiteError, match="비어"):
        off.check_complete(tmp_path / "b" / DATE, tmp_path / "lib")


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
    assert f"/var/lib/paperbot/exec/executor.db" in text and f"{out / DATE / 'paper3.db'}" in text


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


def test_restore_refuses_unsafe_paths_in_the_archive(tmp_path):
    arc = tmp_path / f"paperbot-{DATE}.tar.gz"
    with tarfile.open(arc, "w:gz") as tar:
        data = b"SQLite format 3\x00" + b"\x00" * 100
        ti = tarfile.TarInfo("../../evil.db")
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
    with pytest.raises(off.OffsiteError, match="이상한 경로"):
        off.restore_backup([part, mf], tmp_path / "o", which=no_zstd, log=lambda s: None)
    assert not (tmp_path / "evil.db").exists() and not (tmp_path.parent / "evil.db").exists()


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
