"""Demo lab nightly backup (demobot/backup.py, CONTRACT.md 8.8).

A temporary demo.db with views / decisions / passes / depth / notified / meta / outbox rows is backed up through a fake
HTTP poster (the multipart body is parsed back), then restored into a fresh database: the same rows. The encrypted
path runs the real openssl when it is installed. Also: only the listed tables (outbox 7 days), a missing table counted
0, the 45 MB refusal, the passphrase-without-openssl refusal, retries on network / 5xx / 429 inside the time limit,
backup.json written on success and on failure, restore refusing while the engine runs, and the token and the
passphrase never in an output, an error or backup.json."""
import email.parser
import email.policy
import gzip
import json
import os
import shutil
import sqlite3
import urllib.parse

import pytest

from demobot import backup as B

T0 = 1_791_590_400_000          # 2026-10-10 00:00 UTC = 09:00 KST
DAY = 86_400_000
TOKEN = "9" * 10 + ":" + "TESTONLY" * 5          # token-shaped, built here (no literal token in the repo)
PASS = "correct-horse-battery-" + "staple" * 3
HAS_OPENSSL = shutil.which("openssl") is not None

# the engine's tables (copied from demobot/store.py and demobot/views.py so these tests do not depend on them)
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS bars(coin TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL,
  PRIMARY KEY(coin, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS cells(coin TEXT, tf TEXT, ts INTEGER, side INTEGER, e_ts INTEGER, done INTEGER,
  atr REAL, raw REAL, f BLOB, t BLOB, PRIMARY KEY(coin, tf, ts, side)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS cells_open ON cells(done) WHERE done = 0;
CREATE TABLE IF NOT EXISTS decisions(acct TEXT, seq INTEGER, t_ms INTEGER, coin TEXT, L INTEGER, combo INTEGER,
  exit INTEGER, info TEXT, PRIMARY KEY(acct, seq, coin, L)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS notified(acct TEXT, key TEXT, status TEXT, ts_ms INTEGER, PRIMARY KEY(acct, key))
  WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS passes(acct TEXT, L INTEGER, start_ms INTEGER, status TEXT, decided_ms INTEGER,
  result TEXT, PRIMARY KEY(acct, L, start_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS depth(coin TEXT, ts INTEGER, bid REAL, ask REAL, buy TEXT, sell TEXT,
  PRIMARY KEY(coin, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS views(id INTEGER PRIMARY KEY AUTOINCREMENT, t_ms INTEGER, entered_ms INTEGER, coin TEXT,
  side INTEGER, zones TEXT, stop REAL, targets TEXT, memo TEXT, status TEXT, text TEXT, from_name TEXT,
  done_sent INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, ts_ms INTEGER, kind TEXT, payload TEXT,
  text TEXT, sent_ms INTEGER, tries INTEGER DEFAULT 0, error TEXT);
CREATE INDEX IF NOT EXISTS outbox_unsent ON outbox(id) WHERE sent_ms IS NULL;
"""
KEPT = ("views", "decisions", "passes", "depth", "notified", "meta", "outbox")


def make_db(path, skip=()):
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for t in skip:
        conn.execute(f"DROP TABLE {t}")
    conn.execute("BEGIN")
    if "views" not in skip:
        for i in range(1, 6):
            conn.execute("INSERT INTO views(t_ms, entered_ms, coin, side, zones, stop, targets, memo, status, text, "
                         "from_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (T0 - i * 3_600_000, T0, "BTCUSD", -1, json.dumps({"B": [84750.0, 84840.0]}), 85600.0, "[]",
                          f"메모 {i}", "watching", f"관점 BTC 숏 B 84750-84840 #{i}", "민수"))
        conn.execute("DELETE FROM views WHERE id = 3")                    # a gap in the ids (AUTOINCREMENT)
    for i in range(2500):                                                  # more than one batch
        conn.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)",
                     (f"ad-r26-S2-15m", i, T0 - i * 900_000, "ALL", 20, i % 343, i % 14, json.dumps({"why_ko": "1등"})))
    if "passes" not in skip:
        conn.execute("INSERT INTO passes VALUES(?,?,?,?,?,?)", ("fx-fr-S2-15m", 20, T0, "confirming", None, None))
        conn.execute("INSERT INTO passes VALUES(?,?,?,?,?,?)", ("fx-fr-S2-15m", 30, T0 - 30 * DAY, "failed",
                                                                T0 - 2 * DAY, json.dumps({"why_ko": "낙폭 31%"})))
    if "depth" not in skip:
        for i in range(300):
            conn.execute("INSERT INTO depth VALUES(?,?,?,?,?,?)",
                         ("BTCUSD", T0 - i * 900_000, 62000.0, 62000.1, json.dumps([0.8, 1.1, None]), "[0.9,1.2,null]"))
    conn.execute("INSERT INTO notified VALUES(?,?,?,?)", ("fx-fr-S2-15m", "BTCUSD|15m|1|1|20", "closed", T0))
    for k, v in (("live_start_ms", T0 - 10 * DAY), ("history_start_ms", T0 - 200 * DAY), ("warm_done_ms", T0 - 11 * DAY),
                 ("forming", {"BTCUSD": [T0, 62000.0]}), ("pass_sent", ["fx-fr-S2-15m|20"]), ("tg_offset", 506),
                 ("reviews", [{"week_ko": "10/05~10/11", "summary_ko": ["한 주"]}])):
        conn.execute("INSERT INTO meta VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False)))
    for i, age in enumerate((0, 1, 6, 8, 20)):                             # days old: the last two are left out
        conn.execute("INSERT INTO outbox(ts_ms, kind, payload, text, sent_ms, tries) VALUES(?,?,?,?,?,0)",
                     (T0 - age * DAY, "warn", "{}", f"⚠ #{i}", T0 - age * DAY + 1000))
    conn.execute("INSERT INTO bars VALUES('BTCUSD', 1, 1, 1, 1, 1, 1)")    # rebuilt from Binance: never backed up
    conn.execute("INSERT INTO cells VALUES('BTCUSD', '15m', 1, 1, 1, 0, 1.0, 1.0, x'00', x'00')")
    conn.execute("COMMIT")
    return conn


def dump(path, tables=KEPT, outbox_since=None):
    conn = sqlite3.connect(path)
    out = {}
    for t in tables:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
            continue
        where = f" WHERE ts_ms >= {outbox_since}" if t == "outbox" and outbox_since is not None else ""
        out[t] = sorted(map(repr, conn.execute(f"SELECT * FROM {t}{where}").fetchall()))
    conn.close()
    return out


class Poster:
    """A fake Telegram: records each request, answers from a script of (status, json) or exceptions."""

    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        a = self.answers.pop(0) if self.answers else (200, {"ok": True, "result": {"message_id": 1}})
        if isinstance(a, BaseException):
            raise a
        status, ans = a
        return status, (json.dumps(ans).encode() if not isinstance(ans, bytes) else ans)

    def form(self, i=-1):
        """The multipart fields and the file of call ``i``: ({name: text}, (filename, bytes))."""
        c = self.calls[i]
        raw = f"Content-Type: {c['headers']['Content-Type']}\r\n\r\n".encode() + c["body"]
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(raw)
        fields, file = {}, None
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if part.get_filename():
                file = (part.get_filename(), part.get_payload(decode=True))
            else:
                fields[name] = part.get_payload(decode=True).decode("utf-8")
        return fields, file


def cfg(tmp_path, db, **kw):
    c = {"DEMOBOT_TG_TOKEN": TOKEN, "DEMOBOT_TG_CHAT": "-100777", "DEMOBOT_BACKUP_CHAT": "",
         "DEMOBOT_BACKUP_PASSPHRASE": "", "DEMOBOT_DB": str(db), "DEMOBOT_SNAP": str(tmp_path / "snap")}
    c.update(kw)
    return c


def no_sleep(_):
    return None


def send(c, poster, now=T0, **kw):
    out = []
    rc = B.cmd_send(c, now, verbose=True, out=out.append, sender=poster, sleep=no_sleep, **kw)
    return rc, out


def backup_json(tmp_path):
    return json.loads((tmp_path / "snap" / "backup.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- send
def test_round_trip_send_then_restore_into_a_fresh_database(tmp_path, capsys):
    db = tmp_path / "demo.db"
    live = make_db(db)                                  # the engine keeps its connection open (WAL) meanwhile
    poster = Poster()
    rc, out = send(cfg(tmp_path, db), poster)
    assert rc == 0, out
    assert len(poster.calls) == 1 and poster.calls[0]["url"] == f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    fields, (fname, data) = poster.form()
    assert fields["chat_id"] == "-100777" and fields["disable_notification"] == "true" and "parse_mode" not in fields
    assert fname == "demolab-20261010-0900.db.gz" and data[:2] == b"\x1f\x8b"
    cap = fields["caption"]
    assert cap.startswith("💾 데모 랩 밤 백업 · 10/10 09:00") and "암호화 아니오" in cap and len(cap) <= 1024
    assert "관점 4 · 설정 바꿈 2,500 · 통과·확인 2 · 호가 비용 300 · 알림 표시 1 · 기본 정보·주간 회의록 7 · " \
           "보낸 알림(7일) 3" in cap
    assert "주간 회의록" in cap and "restore" in cap and TOKEN not in cap
    st = backup_json(tmp_path)
    assert st == {"last_ok_ms": T0, "last_try_ms": T0, "bytes": len(data), "encrypted": False, "error_ko": None,
                  "tables": {"views": 4, "decisions": 2500, "passes": 2, "depth": 300, "notified": 1, "meta": 7,
                             "outbox": 3}}
    assert list(st["tables"]) == list(KEPT)
    # the file holds only the listed tables (outbox: 7 days), not the rebuilt ones
    f = tmp_path / "got.db.gz"
    f.write_bytes(data)
    plain = tmp_path / "got.db"
    plain.write_bytes(gzip.decompress(data))
    names = {r[0] for r in sqlite3.connect(plain).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names - {"sqlite_sequence"} == set(KEPT)
    # restore into a fresh database: the same rows
    fresh = tmp_path / "new" / "demo.db"
    out2 = []
    assert B.cmd_restore(str(f), cfg(tmp_path, fresh), state=lambda u: "inactive", out=out2.append) == 0, out2
    want = dump(db, outbox_since=T0 - 7 * DAY)
    want["meta"] = [r for r in want["meta"] if "forming" not in r]       # the old server's forming bar: not restored
    assert dump(fresh) == want
    text = "\n".join(out2)
    assert "백업 파일 확인 (integrity_check): ok" in text and "(새로 만듦)" in text
    assert "warm.sh" in text and "on.sh" in text and text.index("warm.sh") < text.index("on.sh")
    c = sqlite3.connect(fresh)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("SELECT seq FROM sqlite_sequence WHERE name='views'").fetchone()[0] == 5   # new ids go on from 5
    c.execute("INSERT INTO views(t_ms) VALUES(1)")
    assert c.execute("SELECT MAX(id) FROM views").fetchone()[0] == 6
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='outbox_unsent'").fetchone()[0] == 1
    live.close()
    assert TOKEN not in capsys.readouterr().out


def test_restore_into_an_existing_database_replaces_rows_and_keeps_its_own_market_facts(tmp_path):
    db = tmp_path / "demo.db"
    make_db(db).close()
    poster = Poster()
    assert send(cfg(tmp_path, db), poster)[0] == 0
    f = tmp_path / "b.db.gz"
    f.write_bytes(poster.form()[1][1])
    target = tmp_path / "t.db"
    t = sqlite3.connect(target, isolation_level=None)
    t.executescript(SCHEMA)
    t.execute("ALTER TABLE passes ADD COLUMN extra TEXT DEFAULT 'x'")                 # a newer engine's column
    t.execute("INSERT INTO meta VALUES('history_start_ms', '42'), ('live_start_ms', '7'), ('forming', 'new')")
    t.execute("INSERT INTO decisions VALUES('ad-r26-S2-15m', 0, 0, 'ALL', 20, 0, 0, 'stale')")
    t.execute("INSERT INTO decisions VALUES('other', 0, 0, 'ALL', 20, 0, 0, 'mine')")
    t.close()
    out = []
    assert B.cmd_restore(str(f), cfg(tmp_path, target), state=lambda u: None, out=out.append) == 0, out
    t = sqlite3.connect(target)
    meta = dict(t.execute("SELECT k, v FROM meta"))
    assert meta["history_start_ms"] == "42" and meta["forming"] == "new"            # the target's own market facts
    assert meta["live_start_ms"] == str(T0 - 10 * DAY) and "reviews" in meta        # the records come back
    assert json.loads(meta["reviews"])[0]["week_ko"] == "10/05~10/11"
    assert t.execute("SELECT info FROM decisions WHERE acct='ad-r26-S2-15m' AND seq=0").fetchone()[0] != "stale"
    assert t.execute("SELECT info FROM decisions WHERE acct='other'").fetchone()[0] == "mine"
    assert t.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 2501
    assert {r[0] for r in t.execute("SELECT extra FROM passes")} == {"x"}
    text = "\n".join(out)
    assert "(새로 만듦)" not in text and "warm.sh" not in text and "on.sh" in text
    assert "systemctl로 엔진 상태를 확인하지 못했습니다" in text


def test_missing_tables_are_skipped_and_counted_zero(tmp_path):
    db = tmp_path / "demo.db"
    make_db(db, skip=("passes", "depth", "views")).close()                  # an older engine
    poster = Poster()
    rc, out = send(cfg(tmp_path, db), poster)
    assert rc == 0, out
    st = backup_json(tmp_path)
    assert st["tables"]["passes"] == 0 and st["tables"]["depth"] == 0 and st["tables"]["views"] == 0
    assert st["tables"]["decisions"] == 2500
    f = tmp_path / "b.db.gz"
    f.write_bytes(poster.form()[1][1])
    out2 = []
    assert B.cmd_restore(str(f), cfg(tmp_path, tmp_path / "x.db"), state=lambda u: "inactive",
                         out=out2.append) == 0
    assert "(백업에 없던 표: views, passes, depth)" in "\n".join(out2)


def test_backup_chat_overrides_the_group(tmp_path):
    db = tmp_path / "demo.db"
    make_db(db).close()
    poster = Poster()
    assert send(cfg(tmp_path, db, DEMOBOT_BACKUP_CHAT="-100555"), poster)[0] == 0
    assert poster.form()[0]["chat_id"] == "-100555"


def test_backup_goes_to_both_owners_private_chats(tmp_path):
    db = tmp_path / "demo.db"
    make_db(db).close()
    poster = Poster()
    rc, out = send(cfg(tmp_path, db, DEMOBOT_TG_CHAT="111111111, 222222222"), poster)
    assert rc == 0, out
    assert [poster.form(i)[0]["chat_id"] for i in range(2)] == ["111111111", "222222222"]
    assert poster.form(0)[1] == poster.form(1)[1] and poster.form(0)[0]["caption"] == poster.form(1)[0]["caption"]
    assert "보냄: 111111111" in out and "보냄: 222222222" in out and "2곳" in out[-2]
    assert backup_json(tmp_path)["last_ok_ms"] == T0
    poster = Poster()                                                       # DEMOBOT_BACKUP_CHAT may be a list too
    assert send(cfg(tmp_path, db, DEMOBOT_TG_CHAT="111", DEMOBOT_BACKUP_CHAT="333,-100444"), poster)[0] == 0
    assert [poster.form(i)[0]["chat_id"] for i in range(2)] == ["333", "-100444"]


def test_backup_is_good_only_when_every_chat_got_it(tmp_path, capsys):
    db = tmp_path / "demo.db"
    make_db(db).close()
    c = cfg(tmp_path, db, DEMOBOT_TG_CHAT="111111111,222222222")
    assert send(c, Poster())[0] == 0
    blocked = (403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})
    poster = Poster([blocked, (200, {"ok": True, "result": {}})])          # the first chat fails, the second is tried
    rc, out = send(c, poster, now=T0 + DAY)
    assert rc == 1 and [poster.form(i)[0]["chat_id"] for i in range(2)] == ["111111111", "222222222"]
    st = backup_json(tmp_path)
    assert st["last_ok_ms"] == T0 and st["last_try_ms"] == T0 + DAY
    err = st["error_ko"]
    assert err.startswith("백업 파일을 2곳 중 1곳에만 보냈습니다. 보냄: 222222222 · 못 보냄: 111111111: ")
    assert "blocked by the user" in err and "차단" in err
    assert "못 보냄: 111111111" in "\n".join(out) and TOKEN not in err + capsys.readouterr().err


@pytest.mark.skipif(not HAS_OPENSSL, reason="no openssl")
def test_encrypted_round_trip_with_openssl(tmp_path, monkeypatch):
    db = tmp_path / "demo.db"
    make_db(db).close()
    seen = []
    real_run = B.subprocess.run

    def spy(argv, **kw):
        seen.append((list(argv), dict(kw.get("env") or {})))
        return real_run(argv, **kw)
    monkeypatch.setattr(B.subprocess, "run", spy)
    poster = Poster()
    rc, out = send(cfg(tmp_path, db, DEMOBOT_BACKUP_PASSPHRASE=PASS), poster)
    assert rc == 0, out
    argv, env = seen[0]
    assert argv[1:6] == ["enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in"]
    assert argv[-2:] == ["-pass", "env:DEMOBOT_BACKUP_PASSPHRASE"]
    assert PASS not in " ".join(argv)                                       # never on the command line
    assert env == {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DEMOBOT_BACKUP_PASSPHRASE": PASS}  # no token
    fields, (fname, data) = poster.form()
    assert fname.endswith(".db.gz.enc") and data.startswith(b"Salted__") and "암호화 예" in fields["caption"]
    assert backup_json(tmp_path)["encrypted"] is True
    f = tmp_path / fname
    f.write_bytes(data)
    # the passphrase from the environment
    fresh = tmp_path / "a.db"
    assert B.cmd_restore(str(f), cfg(tmp_path, fresh, DEMOBOT_BACKUP_PASSPHRASE=PASS), state=lambda u: None,
                         out=print) == 0
    assert dump(fresh)["views"] == dump(db)["views"]
    # asked for it (no passphrase in the environment)
    fresh2 = tmp_path / "b.db"
    out = []
    assert B.cmd_restore(str(f), cfg(tmp_path, fresh2), ask=lambda prompt: PASS, state=lambda u: None,
                         out=out.append) == 0
    assert "암호 풀림" in "\n".join(out) and PASS not in "\n".join(out)
    # a wrong passphrase: nothing made, the passphrase not shown
    fresh3 = tmp_path / "c.db"
    out = []
    wrong = "wrong-passphrase-" + "x" * 10
    assert B.cmd_restore(str(f), cfg(tmp_path, fresh3), ask=lambda prompt: wrong, state=lambda u: None,
                         out=out.append) == 1
    text = "\n".join(out)
    assert "되살리지 못했습니다" in text and ("암호" in text) and wrong not in text and not fresh3.exists()
    # no passphrase at all
    out = []
    assert B.cmd_restore(str(f), cfg(tmp_path, fresh3), state=lambda u: None, out=out.append) == 1
    assert "암호화된 백업입니다" in "\n".join(out) and not fresh3.exists()
    # the manual way written in the guide opens it too
    gz = tmp_path / "manual.db.gz"
    r = B.subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", str(f), "-out", str(gz),
                          "-pass", "env:P"], env={"PATH": os.environ["PATH"], "P": PASS})
    assert r.returncode == 0 and gzip.decompress(gz.read_bytes())[:16] == B.SQLITE_MAGIC


def test_passphrase_without_openssl_sends_nothing(tmp_path):
    db = tmp_path / "demo.db"
    make_db(db).close()
    poster = Poster()
    rc, out = send(cfg(tmp_path, db, DEMOBOT_BACKUP_PASSPHRASE=PASS), poster, which=lambda name: None)
    assert rc == 1 and poster.calls == []
    st = backup_json(tmp_path)
    assert "openssl" in st["error_ko"] and st["last_ok_ms"] is None and st["last_try_ms"] == T0
    assert PASS not in json.dumps(st, ensure_ascii=False) and PASS not in "\n".join(out)


def test_a_file_over_45_mb_is_refused(tmp_path, monkeypatch):
    db = tmp_path / "demo.db"
    make_db(db).close()
    monkeypatch.setattr(B, "MAX_BYTES", 100)
    poster = Poster()
    rc, out = send(cfg(tmp_path, db), poster)
    assert rc == 1 and poster.calls == [] and "45 MB를 넘어 보내지 않았습니다" in backup_json(tmp_path)["error_ko"]


def test_failure_keeps_the_last_good_backup_and_exits_1(tmp_path, capsys):
    db = tmp_path / "demo.db"
    make_db(db).close()
    c = cfg(tmp_path, db)
    assert send(c, Poster())[0] == 0
    good = backup_json(tmp_path)
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    bad = Poster([(400, {"ok": False, "description": f"Bad Request: chat not found ({url})"})])
    rc, out = send(c, bad, now=T0 + DAY)
    assert rc == 1 and len(bad.calls) == 1                                  # a 4xx is not retried
    st = backup_json(tmp_path)
    assert st["last_ok_ms"] == T0 and st["last_try_ms"] == T0 + DAY and st["tables"] == good["tables"]
    assert st["bytes"] == good["bytes"] and "chat not found" in st["error_ko"] and "번호(DEMOBOT_BACKUP_CHAT" in st["error_ko"]
    everything = json.dumps(st, ensure_ascii=False) + "\n".join(out) + capsys.readouterr().err
    assert TOKEN not in everything and TOKEN.split(":")[1] not in everything and "<token>" in everything
    assert send(c, Poster(), now=T0 + 2 * DAY)[0] == 0
    assert backup_json(tmp_path)["error_ko"] is None and backup_json(tmp_path)["last_ok_ms"] == T0 + 2 * DAY


def test_missing_settings_or_database(tmp_path):
    db = tmp_path / "demo.db"
    rc, out = send(cfg(tmp_path, db, DEMOBOT_TG_TOKEN=""), Poster())
    assert rc == 1 and "sudoedit" in backup_json(tmp_path)["error_ko"]
    rc, out = send(cfg(tmp_path, db), Poster())
    assert rc == 1 and "데이터베이스가 없습니다" in backup_json(tmp_path)["error_ko"]
    assert not db.exists()                                                   # read-only: never made


def test_a_broken_database_is_a_clean_failure(tmp_path):
    db = tmp_path / "demo.db"
    db.write_bytes(b"not a database at all" * 100)
    rc, out = send(cfg(tmp_path, db), Poster())
    assert rc == 1 and "데이터베이스를 읽지 못했습니다" in backup_json(tmp_path)["error_ko"]


def test_unwritable_snap_folder_fails_visibly(tmp_path):
    db = tmp_path / "demo.db"
    make_db(db).close()
    (tmp_path / "snap").write_text("a file, not a folder")
    out = []
    assert B.cmd_send(cfg(tmp_path, db), T0, verbose=True, out=out.append, sender=Poster(), sleep=no_sleep) == 1
    assert "backup.json을 쓰지 못했습니다" in "\n".join(out)


# ---------------------------------------------------------------- the upload: retries and the time limit
class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def upload(poster, clock=None, deadline=None, log=None):
    clock = clock or Clock()
    return B.send_document(TOKEN, "-1", "f.db.gz", b"x", "cap", sender=poster, sleep=clock.sleep, clock=clock,
                           deadline=deadline, log=log or (lambda s: None)), clock


def test_network_errors_5xx_and_429_are_retried_with_backoff():
    logs = []
    p = Poster([OSError(f"reset by peer https://api.telegram.org/bot{TOKEN}/sendDocument"),
                (502, {"ok": False, "description": "Bad Gateway"}),
                (429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}}),
                (200, {"ok": True, "result": {"message_id": 9}})])
    res, clock = upload(p, log=logs.append)
    assert res == {"message_id": 9} and len(p.calls) == 4
    assert clock.slept == [5.0, 15.0, 8.0]                                 # backoff, backoff, retry_after + 1
    assert all(TOKEN not in x for x in logs) and "<token>" in logs[0]


def test_gives_up_after_all_tries_and_on_a_long_429():
    p = Poster([(500, {"ok": False, "description": "boom"})] * 10)
    with pytest.raises(B.BackupError) as ei:
        upload(p)
    assert "5번 모두 실패" in str(ei.value) and len(p.calls) == 5
    p = Poster([(429, {"ok": False, "parameters": {"retry_after": 3600}})])
    with pytest.raises(B.BackupError) as ei:
        upload(p)
    assert "너무 김" in str(ei.value) and len(p.calls) == 1


def test_the_time_limit_stops_the_retries():
    p = Poster([OSError("timeout")] * 10)
    clock = Clock()
    with pytest.raises(B.BackupError) as ei:
        upload(p, clock=clock, deadline=100.0)
    assert "시간 제한" in str(ei.value) and len(p.calls) == 3 and sum(clock.slept) < 100   # 5 + 15, then no room
    assert all(c["timeout"] <= 100.0 / 3 for c in p.calls)
    with pytest.raises(B.BackupError):
        upload(Poster(), clock=clock, deadline=clock.t + 10.0)              # too little time left: not even tried


@pytest.mark.parametrize("status,body,hint", [(401, {"ok": False, "description": "Unauthorized"}, "토큰"),
                                              (403, {"ok": False, "description": "Forbidden: bot was kicked"}, "빠졌"),
                                              (400, {"ok": False, "description": "Bad Request: group chat was upgraded",
                                                     "parameters": {"migrate_to_chat_id": -1009}}, "-1009"),
                                              (413, {"ok": False, "description": "Request Entity Too Large"}, "한도")])
def test_refusals_fail_at_once_with_a_korean_hint(status, body, hint):
    p = Poster([(status, body)])
    with pytest.raises(B.BackupError) as ei:
        upload(p)
    assert hint in str(ei.value) and len(p.calls) == 1 and TOKEN not in str(ei.value)


def test_multipart_and_the_real_sender_shape(monkeypatch):
    body, ctype = B.multipart({"chat_id": "-1", "caption": "한글"}, ("document", "a b/../c.db.gz", b"\x00\x01"))
    assert ctype.startswith("multipart/form-data; boundary=demobot-")
    assert b'filename="a_b_.._c.db.gz"' in body and "한글".encode() in body and b"\x00\x01" in body
    seen = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok":true,"result":1}'

    def fake(req, timeout=None):
        seen.update(url=req.full_url, method=req.get_method(), timeout=timeout)
        return Resp()
    monkeypatch.setattr(B.urllib.request, "urlopen", fake)
    assert B.urllib_sender("https://x/bot1/sendDocument", b"b", {}, 5.0) == (200, b'{"ok":true,"result":1}')
    assert seen == {"url": "https://x/bot1/sendDocument", "method": "POST", "timeout": 5.0}


# ---------------------------------------------------------------- restore: refusals
def test_restore_refuses_while_the_engine_runs_unless_forced(tmp_path):
    db = tmp_path / "demo.db"
    make_db(db).close()
    poster = Poster()
    assert send(cfg(tmp_path, db), poster)[0] == 0
    f = tmp_path / "b.db.gz"
    f.write_bytes(poster.form()[1][1])
    target = tmp_path / "t.db"
    sqlite3.connect(target).executescript(SCHEMA)                           # the engine's own database
    out = []
    for state in ("active", "activating", "reloading"):
        assert B.cmd_restore(str(f), cfg(tmp_path, target), state=lambda u, s=state: s if u == B.LIVE_UNIT
                             else "inactive", out=out.append) == 1
    assert dump(target)["views"] == [] and "off.sh" in "\n".join(out) and "--force" in "\n".join(out)
    out = []
    assert B.cmd_restore(str(f), cfg(tmp_path, target), force=True,
                         state=lambda u: "active" if u == B.LIVE_UNIT else "inactive", out=out.append) == 0
    assert len(dump(target)["views"]) == 4 and "켜진 채로 넣었습니다" in "\n".join(out)
    out = []
    assert B.cmd_restore(str(f), cfg(tmp_path, tmp_path / "w.db"),
                         state=lambda u: "activating" if u == "demobot-warm.service" else "inactive",
                         out=out.append) == 1
    assert "첫 채우기" in "\n".join(out)


def test_restore_refuses_bad_files(tmp_path):
    target = tmp_path / "t.db"
    out = []
    assert B.cmd_restore(str(tmp_path / "missing"), cfg(tmp_path, target), state=lambda u: None, out=out.append) == 1
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"hello world" * 10)
    assert B.cmd_restore(str(junk), cfg(tmp_path, target), state=lambda u: None, out=out.append) == 1
    cut = tmp_path / "cut.db.gz"
    cut.write_bytes(gzip.compress(b"SQLite format 3\x00" + b"\x00" * 5000)[:40])
    assert B.cmd_restore(str(cut), cfg(tmp_path, target), state=lambda u: None, out=out.append) == 1
    notdb = tmp_path / "notdb.gz"
    notdb.write_bytes(gzip.compress(b"plain text, not sqlite"))
    assert B.cmd_restore(str(notdb), cfg(tmp_path, target), state=lambda u: None, out=out.append) == 1
    text = "\n".join(out)
    assert "파일이 없습니다" in text and "데모 랩 백업 파일이 아닙니다" in text and "압축을 풀지 못했습니다" in text
    assert "SQLite 파일이 아닙니다" in text and not target.exists()


def test_restore_reports_a_damaged_backup_and_changes_nothing(tmp_path, monkeypatch):
    db = tmp_path / "demo.db"
    make_db(db).close()
    poster = Poster()
    assert send(cfg(tmp_path, db), poster)[0] == 0
    f = tmp_path / "b.db.gz"
    f.write_bytes(poster.form()[1][1])
    monkeypatch.setattr(B, "integrity_check", lambda p: "*** in database main ***\nPage 3 is never used")
    out = []
    assert B.cmd_restore(str(f), cfg(tmp_path, tmp_path / "t.db"), state=lambda u: None, out=out.append) == 1
    assert "손상" in "\n".join(out) and not (tmp_path / "t.db").exists()


def test_a_failed_merge_leaves_no_new_database(tmp_path, monkeypatch):
    db = tmp_path / "demo.db"
    make_db(db).close()
    poster = Poster()
    assert send(cfg(tmp_path, db), poster)[0] == 0
    f = tmp_path / "b.db.gz"
    f.write_bytes(poster.form()[1][1])
    target = tmp_path / "t.db"

    def boom(*a):
        sqlite3.connect(target).close()                                      # the file was made, then it failed
        raise sqlite3.OperationalError(f"disk I/O error near {TOKEN}")
    monkeypatch.setattr(B, "merge", boom)
    out = []
    assert B.cmd_restore(str(f), cfg(tmp_path, target), state=lambda u: None, out=out.append) == 1
    assert not target.exists() and TOKEN not in "\n".join(out) and "disk I/O error" in "\n".join(out)


def test_integrity_check_reads_only(tmp_path):
    p = tmp_path / "x.db"
    sqlite3.connect(p).execute("CREATE TABLE t(a)").connection.commit()
    assert B.integrity_check(str(p)) == "ok"
    assert sorted(os.listdir(tmp_path)) == ["x.db"]
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 200)
    assert B.integrity_check(str(bad)) != "ok"


# ---------------------------------------------------------------- settings, redaction, CLI
def test_settings_from_the_environment_then_the_env_file(tmp_path):
    f = tmp_path / "demobot.env"
    f.write_text(f"DEMOBOT_TG_TOKEN='{TOKEN}'\nDEMOBOT_TG_CHAT=-100\nDEMOBOT_BACKUP_PASSPHRASE=\"{PASS}\"\n"
                 "DEMOBOT_DASH_SECRET=zzz\n", encoding="utf-8")
    s = B.settings({}, str(f))
    assert s["DEMOBOT_TG_TOKEN"] == TOKEN and s["DEMOBOT_BACKUP_PASSPHRASE"] == PASS and "DEMOBOT_DASH_SECRET" not in s
    assert s["DEMOBOT_DB"] == "/var/lib/demobot/demo.db" and s["DEMOBOT_SNAP"] == "/var/lib/demobot/snap"
    s = B.settings({"DEMOBOT_TG_CHAT": "-5", "DEMOBOT_DB": "/x.db"}, str(f))
    assert s["DEMOBOT_TG_CHAT"] == "-5" and s["DEMOBOT_DB"] == "/x.db" and s["DEMOBOT_TG_TOKEN"] == TOKEN
    assert B.settings({}, str(tmp_path / "missing"))["DEMOBOT_TG_TOKEN"] == ""


def test_redact_removes_the_token_and_the_passphrase():
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    text = f"{url} {TOKEN.replace(':', '%3A')} pass={PASS} q={urllib.parse.quote(PASS, safe='')}"
    r = B.redact(text, TOKEN, PASS)
    assert TOKEN not in r and TOKEN.split(":")[1] not in r and PASS not in r
    assert r.count("<token>") == 2 and r.count("<secret>") == 2
    assert B.redact("1234567:" + "abcdefghij" * 3) == "<token>"             # an unknown token-shaped text too
    assert B.redact("nothing", None, None, "") == "nothing"


def test_cli_refuses_root_for_send(monkeypatch, capsys):
    monkeypatch.setattr(B.os, "geteuid", lambda: 0)
    assert B.main(["now", "--env-file", "/nonexistent"], env={}) == 2
    assert "sudo -u demobot" in capsys.readouterr().out


def test_cli_send_end_to_end(tmp_path, monkeypatch, capsys):
    db = tmp_path / "demo.db"
    make_db(db).close()
    monkeypatch.setattr(B.os, "geteuid", lambda: 1000)
    poster = Poster()
    monkeypatch.setattr(B, "urllib_sender", poster)
    env = cfg(tmp_path, db)
    assert B.main(["send", "--env-file", "/nonexistent"], env=env) == 0
    out = capsys.readouterr().out
    assert json.loads(out.strip().splitlines()[-1])["backup"] == "sent" and TOKEN not in out
    assert B.main(["now", "--env-file", "/nonexistent"], env=env) == 0
    assert "보냈습니다" in capsys.readouterr().out and len(poster.calls) == 2
