"""후보 리그 starts at its install time (owners 2026-10-12: "거래기록은 왜 안보이는거야? ... 커스텀값 봇 돌린 시점부터
원래 돌리고있었던 규칙봇 형식처럼 해야지 봇 돌린시점부터 거래 기록이랑 다 보이게").

* Engine (candleague/runner.py): a VERSION 1 database (replayed from 2026-10-01, meta.started_ms = the install time)
  starts over on the new code's first construction FROM ITS INSTALL TIME floored to 5 minutes: the replay's trades and
  engine states are gone, a copy of the whole old database is kept next to it (league_replay_from_1001_<UTC date>.db,
  made once even when the install script made it first), meta.start_ms is recorded and meta.started_ms kept; a second
  construction does not start over again; a later VERSION bump starts over from the SAME recorded start; a fresh
  database starts at its own first run; a copy that cannot be made deletes nothing.
* Catching up is the snapshot's own ``catching``: written true only right after a start-over or a computed chunk while
  the processed time is more than 30 minutes behind (dash.py catching_up, lk.js catchingUp), never the install time; a
  restart that makes no progress (a crash loop, Binance down) writes no snapshot and never reads as catching up.
* The start also lives in league_start.json next to the database: a lost database, or VERSION 1 code run by mistake,
  cannot move it; CANDLEAGUE_START (with its time zone) rebuilds only a league with no recorded start, as its install
  time too (no replay framing); a bad value never stops a league that has a start.
* Telegram: bust and warning notices wait until caught up; a start-over that recomputed a span says so once.
* Every day count and "시작부터" reads the snapshot's start (Telegram summary, the dashboard's lk.js helpers, 요약 and 서버
  상태 mounted under node); the '설치 뒤 진입만' switch hides itself when nothing lies before the install; no hard-coded
  10/01 is left in the dashboard's code, notify.py, summary.py or dash.py (only comments that explain the history).
* The install script copies the record with the engine stopped and before the code swap.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import sqlite3
import sys
import tokenize

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

import test_candleague_pos_ui as POS  # noqa: E402  (its node DOM stand-in)
import test_paramshadow as TP  # noqa: E402
from candleague import candidates as C  # noqa: E402
from candleague import dash as D  # noqa: E402
from candleague import notify as N  # noqa: E402
from candleague import runner as RN  # noqa: E402
from paperbot import paramshadow as PS  # noqa: E402
from paperbot import sweepsig  # noqa: E402

data = {s: TP._synth5(i + 3, TP.P0[s]) for i, s in enumerate(TP.SYMS)}
START = TP.D0                                             # 2026-10-05 00:00 UTC (the synthetic bars' first day)
INSTALL = START + TP.DAY + 7 * 60_000 + 13_000            # an install time off the 5-minute grid
FLOOR = START + TP.DAY + 5 * 60_000
NOW = START + 2 * TP.DAY + 3_600_000
JS = os.path.join(ROOT, "candleague", "static", "js")


def _accts():
    combo = C.default_combo("core", "S2_ST_ROC")
    cand = {"id": "core-S2-15m-1", "kind": "core", "name": "S2_ST_ROC", "tf": "15m",
            "combo": {k: C._plain(v) for k, v in combo.items()}, "exit": "tp1R|1", "source": {}}
    return C.accounts([cand])


def _league(db, now=NOW, start_ms=None, db_path=True, clock=None):
    return RN.League(RN.open_db(str(db)), _accts(), TP.BRACKETS, TP.SPECS, sweepsig.lib(), PS.FrameSource(data),
                     TP._steps_from(data), TP.SYMS, start_ms=start_ms, log=lambda s: None,
                     db_path=str(db) if db_path else None, now_ms=now, clock=clock)


def _v1_db(path, monkeypatch, trades=12):
    """A database as the server has it under VERSION 1: replayed from 'START' (its 10/01), installed at INSTALL, a
    finished day of trades, engine states, the notifier's keys."""
    monkeypatch.setattr(RN, "VERSION", 1)
    fp = RN.fingerprint(_accts())
    monkeypatch.setattr(RN, "VERSION", 2)
    conn = RN.open_db(str(path))
    RN._put(conn, "meta", {"fingerprint": fp, "done": START + 2 * TP.DAY, "started_ms": INSTALL, "notes": ["x"]})
    RN._put(conn, "engines", {"core-S2-15m-1": {"wallet": 4321.0}})
    RN._put(conn, "summary_day", "2026-10-06")
    RN._put(conn, "busts_told", ["core-S2-15m-1-flip"])
    conn.executemany("INSERT INTO trades VALUES (?, ?, ?)",
                     [("core-S2-15m-1", START + i * 3_600_000, json.dumps({"pnl": -1.0, "exit_time": START + i * 3_600_000,
                                                                          "entry_time": START + i * 3_600_000 - 60_000}))
                      for i in range(trades)])
    conn.commit()
    conn.close()
    return fp


def _meta(path):
    c = sqlite3.connect(str(path))
    try:
        return json.loads(c.execute("SELECT v FROM kv WHERE k = 'meta'").fetchone()[0])
    finally:
        c.close()


def _count(path, table="trades"):
    c = sqlite3.connect(str(path))
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


# ------------------------------------------------------------------------------------------------ the engine
def test_v1_replay_starts_over_from_its_install_time(tmp_path, monkeypatch):
    db = tmp_path / "league.db"
    _v1_db(db, monkeypatch)
    lg = _league(db)
    m = _meta(db)
    assert m["start_ms"] == FLOOR == lg.start_ms == lg.done and m["started_ms"] == INSTALL
    assert m["fingerprint"] == RN.fingerprint(_accts()) and m["reset_ms"] == NOW
    assert _count(db) == 0 and RN._get(lg.conn, "engines") is None and RN._get(lg.conn, "busts_told") is None
    assert RN._get(lg.conn, "summary_day") == "2026-10-06"                 # no second 09:00 summary that day
    copies = sorted(glob.glob(str(tmp_path / "league_*.db")))
    assert [os.path.basename(p) for p in copies] == ["league_replay_from_1001_20261007.db"] == [m["backup"]]
    assert _count(copies[0]) == 12 and _meta(copies[0])["started_ms"] == INSTALL     # the whole old record
    assert not os.path.exists(copies[0] + "-wal")                                    # one plain file
    assert not glob.glob(str(tmp_path / "*.part"))
    # from the start on: only bars closing after the start give signals, every trade is entered after it
    lg.advance(START + 2 * TP.DAY)
    rows = [json.loads(d) for (d,) in lg.conn.execute("SELECT data FROM trades")]
    assert rows and min(r["entry_time"] for r in rows) > FLOOR
    snap = RN.write_snapshots(str(tmp_path / "snap"), lg, START + 2 * TP.DAY + 60_000)
    assert snap["start_ms"] == FLOOR and snap["started_ms"] == INSTALL
    book = json.load(open(tmp_path / "snap" / "trades.json"))
    assert all(b["equity"][0] == [FLOOR, 5000.0] for b in book.values())
    # a second construction (a restart, the next code update without a VERSION change) carries on
    n = _count(db)
    again = _league(db, now=NOW + TP.DAY)
    assert again.start_ms == FLOOR and again.done == START + 2 * TP.DAY and _count(db) == n
    assert len(glob.glob(str(tmp_path / "league_*.db"))) == 1 and _meta(db)["reset_ms"] == NOW


def test_install_script_copy_is_not_made_twice(tmp_path, monkeypatch):
    db = tmp_path / "league.db"
    _v1_db(db, monkeypatch)
    first = RN.backup_if_reset(str(db), _accts(), now_ms=NOW)               # the install script, engine stopped
    assert os.path.basename(first) == "league_replay_from_1001_20261007.db" and _count(db) == 12
    assert RN.backup_if_reset(str(db), _accts(), now_ms=NOW + 60_000) == first           # run again: the same copy
    lg = _league(db, now=NOW + 120_000)
    assert _meta(db)["backup"] == os.path.basename(first) and lg.done == FLOOR
    assert len(glob.glob(str(tmp_path / "league_*.db"))) == 1
    assert RN.backup_if_reset(str(db), _accts()) is None                     # nothing to copy once started over
    assert RN.backup_if_reset(str(tmp_path / "none.db"), _accts()) is None


def test_a_copy_that_fails_deletes_nothing(tmp_path, monkeypatch):
    db = tmp_path / "league.db"
    _v1_db(db, monkeypatch)

    def no_space(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(RN, "backup_db", no_space)
    with pytest.raises(OSError):
        _league(db)
    assert _count(db) == 12 and "start_ms" not in _meta(db)


def test_a_later_version_keeps_the_recorded_start(tmp_path, monkeypatch):
    db = tmp_path / "league.db"
    lg = _league(db, now=FLOOR + 90_000, start_ms=None)                    # a fresh database: its own first run
    assert lg.start_ms == FLOOR and _meta(db)["started_ms"] == FLOOR + 90_000
    lg.advance(START + 2 * TP.DAY)
    assert _count(db) > 0 and not glob.glob(str(tmp_path / "league_*.db"))
    monkeypatch.setattr(RN, "VERSION", 3)                                   # a later change of the calculation
    lg2 = _league(db, now=NOW + 5 * TP.DAY)
    m = _meta(db)
    assert lg2.start_ms == FLOOR == lg2.done == m["start_ms"] and m["started_ms"] == FLOOR + 90_000 and _count(db) == 0
    assert [os.path.basename(p) for p in glob.glob(str(tmp_path / "league_*.db"))] == ["league_from_1006_20261012.db"]


def test_fresh_database_and_the_start_setting(tmp_path):
    lg = _league(tmp_path / "a.db", now=NOW + 299_999)
    assert lg.start_ms == lg.done == NOW and _meta(tmp_path / "a.db")["started_ms"] == NOW + 299_999
    assert RN.read_start_file(str(tmp_path / "a.db")) == {"start_ms": NOW, "started_ms": NOW + 299_999}
    lg = _league(tmp_path / "b.db", start_ms=START + 61_000)               # CANDLEAGUE_START: a lost database rebuilt
    m = _meta(tmp_path / "b.db")
    assert lg.start_ms == START and m["started_ms"] == START + 61_000      # the start is the install: no replay before it
    snap = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW)
    assert snap["started_ms"] - snap["start_ms"] < 5 * 60_000 and snap["catching"] is True
    assert RN.parse_start("2026-10-11T03:00Z") == RN.parse_start("2026-10-11T12:00+09:00") == 1_791_687_600_000
    assert RN.parse_start("2026-10-11 12:00+09:00") == RN.parse_start("2026-10-11T03:00z") == 1_791_687_600_000
    assert RN.parse_start("1791687600000") == 1_791_687_600_000 and RN.parse_start("") is None
    for bad in ("2026-10-11 12:00", "10/11 12:00", "어제"):                # no zone (12:00 read as UTC = 9 h late), not a time
        with pytest.raises(ValueError):
            RN.parse_start(bad)
    assert RN.league_start({"start_ms": 7 * RN.FIVE + 1, "started_ms": 99}, 5) == (7 * RN.FIVE, 99)
    assert RN.league_start({"started_ms": 7 * RN.FIVE + 9}, 5, {"start_ms": 3 * RN.FIVE, "started_ms": 3 * RN.FIVE + 7}) \
        == (3 * RN.FIVE, 3 * RN.FIVE + 7)                                 # the start file beats a VERSION 1 install time
    assert RN.league_start({"started_ms": 7 * RN.FIVE + 9}, 5, None, 2 * RN.FIVE + 1) == (2 * RN.FIVE, 2 * RN.FIVE + 1)
    assert RN.league_start({}, 9 * RN.FIVE + 4) == (9 * RN.FIVE, 9 * RN.FIVE + 4)


def test_the_start_survives_old_code_and_a_lost_database(tmp_path, monkeypatch):
    """VERSION 1 code run by mistake (app.old) starts the league over from 10/01 again and records its own 'now' as the
    install time, and a database can be lost: the start file next to it keeps the start for the next VERSION 2 run."""
    db = tmp_path / "league.db"
    _v1_db(db, monkeypatch)
    lg = _league(db)
    assert RN.read_start_file(str(db)) == {"start_ms": FLOOR, "started_ms": INSTALL}
    lg.advance(START + 2 * TP.DAY)
    lg.conn.close()
    # VERSION 1 code: deletes the rows without a copy, replays from its 10/01, records only started_ms = the rollback
    monkeypatch.setattr(RN, "VERSION", 1)
    fp1 = RN.fingerprint(_accts())
    monkeypatch.setattr(RN, "VERSION", 2)
    c = RN.open_db(str(db))
    c.execute("DELETE FROM kv")
    c.execute("DELETE FROM trades")
    RN._put(c, "meta", {"fingerprint": fp1, "done": START, "started_ms": NOW + 3 * TP.DAY})
    c.commit()
    c.close()
    back = _league(db, now=NOW + 4 * TP.DAY, start_ms=START + 7 * 3_600_000)     # even with a stray CANDLEAGUE_START
    m = _meta(db)
    assert back.reset and back.start_ms == FLOOR == m["start_ms"] and m["started_ms"] == INSTALL
    back.conn.close()
    # the database lost (the folder kept): the next run rebuilds from the same start
    for f in glob.glob(str(tmp_path / "league.db*")):
        os.remove(f)
    again = _league(db, now=NOW + 5 * TP.DAY)
    assert again.start_ms == FLOOR and _meta(db)["started_ms"] == INSTALL and again.done == FLOOR


def test_explicit_start_is_read_only_without_a_recorded_one(tmp_path, monkeypatch):
    db = tmp_path / "league.db"
    conn = RN.open_db(str(db))
    with pytest.raises(ValueError):                                        # nothing recorded: a bad value stops here
        RN.explicit_start("10/11 12:00", conn, str(db), log=lambda s: None)
    assert RN.explicit_start("2026-10-11T12:00+09:00", conn, str(db), log=lambda s: None) == 1_791_687_600_000
    assert RN.explicit_start("", conn, str(db)) is None
    conn.close()
    lg = _league(db)                                                       # a start is recorded now
    said = []
    assert RN.explicit_start("10/11 12:00", lg.conn, str(db), log=said.append) is None and said   # not even read
    # the install script's line: what the next run will use
    db2 = tmp_path / "old.db"
    _v1_db(db2, monkeypatch)
    assert RN.plan_start(str(db2), _accts(), now_ms=NOW) == (True, FLOOR, INSTALL)
    assert RN.plan_start(str(db), _accts(), now_ms=NOW) == (False, lg.start_ms, _meta(db)["started_ms"])
    assert RN.plan_start(str(tmp_path / "none.db"), _accts()) is None
    monkeypatch.setattr(RN.C, "load", lambda path=None: [])
    accts = _accts()
    monkeypatch.setattr(RN.C, "accounts", lambda cands: accts)
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert RN.main(["backup", "--db", str(db2)]) == 0
        assert RN.main(["backup", "--db", str(tmp_path / "x.db"), "--start", "10/11 12:00"]) == 0   # no database: nothing read
    out = buf.getvalue()
    assert "새로 시작하기 전 기록 복사" in out and f"새 시작: {RN._kst(FLOOR)} KST (설치한 때 {RN._kst(INSTALL)} KST)" in out
    fresh = tmp_path / "fresh.db"
    RN.open_db(str(fresh)).close()
    with contextlib.redirect_stdout(io.StringIO()):
        assert RN.main(["backup", "--db", str(fresh), "--start", "2026-10-11 12:00"]) == 1         # refused before the swap


# ------------------------------------------------------------------------------------------------ catching up
def test_catching_up_reads_the_lag_not_the_install_time():
    t = 1_791_700_000_000
    assert D.catching_up({"generated_ms": t, "done_ms": t - 31 * 60_000})          # a snapshot from before the flag
    assert not D.catching_up({"generated_ms": t, "done_ms": t - 29 * 60_000})
    assert not D.catching_up({"generated_ms": t, "done_ms": t - 6 * 60_000, "started_ms": t + 86_400_000})
    assert not D.catching_up({"done_ms": t}) and not D.catching_up({})
    assert not D.catching_up({"generated_ms": t, "done_ms": t - 3 * 3_600_000, "catching": False})   # the engine's word
    assert D.catching_up({"generated_ms": t, "done_ms": t - 31 * 60_000, "catching": True})


def test_a_restart_without_progress_never_reads_as_catching_up(tmp_path):
    """A crash loop (Binance down, a bug in a pass): the engine restarts every 30 s on a league 2 hours behind. Such a
    restart writes no snapshot, and a snapshot written without progress says catching False, so the dashboard shows
    the engine as stopped / late (red), never as 'catching up'."""
    db = tmp_path / "league.db"
    t0 = START + TP.DAY
    lg = _league(db, now=t0)                                               # a fresh league, caught up to t0
    lg.conn.close()
    later = t0 + 2 * 3_600_000                                             # 2 hours later, nothing processed
    again = _league(db, now=later, clock=lambda: later)
    assert not again.reset and again.advanced_ms is None
    doc = RN.write_snapshots(str(tmp_path / "snap"), again, later)
    assert doc["catching"] is False and not D.catching_up(doc)
    pos = D.positions_doc(doc, None)
    assert pos["catching"] is False and not D.catching_up(pos)
    # progress (a chunk) right before the write: catching; the same snapshot written 20 minutes later without more: not
    again.advance(t0 + 3_600_000)
    assert again.advanced_ms == later
    assert RN.write_snapshots(str(tmp_path / "snap"), again, later)["catching"] is True
    assert RN.write_snapshots(str(tmp_path / "snap"), again, later + 20 * 60_000)["catching"] is False


def test_main_writes_at_start_only_after_a_start_over(tmp_path, monkeypatch):
    """runner.main: the snapshot written as the engine starts (so the old screens go at once) only when that start
    started the league over; a plain restart whose first pass fails leaves the last snapshot to age (red)."""
    from paperbot import binance as BN

    class Down(Exception):
        pass

    class NoRest:
        def __init__(self, *a, **k):
            pass

    class DeadSource:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, name):
            def down(*a, **k):
                raise Down("binance down")
            return down

    def dead_fetch(*a, **k):
        raise Down("binance down")
    monkeypatch.setattr(BN, "BinanceREST", NoRest)
    monkeypatch.setattr(PS, "RestSource", DeadSource)
    monkeypatch.setattr(PS, "make_fetcher", dead_fetch)
    monkeypatch.setattr(RN.C, "load", lambda path=None: [])
    accts = _accts()
    monkeypatch.setattr(RN.C, "accounts", lambda cands: accts)
    monkeypatch.setattr(RN, "load_exchange", lambda path, syms: (TP.BRACKETS, TP.SPECS, "test"))
    monkeypatch.setattr(sweepsig, "lib", lambda: TP_LIB)
    monkeypatch.setenv("CANDLEAGUE_START", "어제")                           # a stray value: not read once recorded
    db, snap = tmp_path / "league.db", tmp_path / "snap"
    old = int(__import__("time").time() * 1000) - 2 * 3_600_000
    c = RN.open_db(str(db))
    RN._put(c, "meta", {"fingerprint": RN.fingerprint(_accts()), "done": old // RN.FIVE * RN.FIVE,
                        "start_ms": old // RN.FIVE * RN.FIVE, "started_ms": old})
    c.commit()
    c.close()
    with pytest.raises(Down):
        RN.main(["once", "--db", str(db), "--snap", str(snap)])
    assert not (snap / "league.json").exists()
    db2 = tmp_path / "v1" / "league.db"
    os.makedirs(db2.parent)
    _v1_db(db2, monkeypatch)
    with pytest.raises(SystemExit):                                        # no start recorded: a bad value is refused
        RN.main(["once", "--db", str(db2), "--snap", str(snap)])
    assert _count(db2) == 12 and not (snap / "league.json").exists()
    monkeypatch.delenv("CANDLEAGUE_START")
    with pytest.raises(Down):
        RN.main(["once", "--db", str(db2), "--snap", str(snap)])
    doc = json.load(open(snap / "league.json"))
    assert doc["start_ms"] == FLOOR and doc["catching"] is True and D.catching_up(doc)


TP_LIB = sweepsig.lib()


# ------------------------------------------------------------------------------------------------ Telegram
def test_bust_notices_wait_and_a_start_over_says_so_once(tmp_path, monkeypatch):
    db = tmp_path / "league.db"
    _v1_db(db, monkeypatch)
    lg = _league(db, now=NOW)
    nt = N.Notifier(lg.conn)
    row = lambda i, bust: {"id": f"a{i}", "role": "cand", "name": "S2_ST_ROC", "tf": "15m", "bust": bust,  # noqa: E731
                           "trades": 40, "wins": 20, "mean_ret": -0.01, "wallet": 0.0 if bust else 5000.0}
    doc = {"done_ms": NOW - 3 * TP.DAY, "start_ms": FLOOR, "lag_s": 0, "watch": {},
           "accounts": [row(1, True), row(2, False)],
           "judge": {"a2": {"verdict": "not_yet", "band": {"n": 30, "below": True, "p5": -0.005, "median": 0.0}}}}
    assert nt.after_pass(doc, NOW, caught_up=False) == []                  # catching up: nothing yet
    out = [t for t in nt.after_pass({**doc, "done_ms": NOW - 200_000}, NOW + 60_000, caught_up=True)
           if not t.startswith("📊")]                                      # (the day's 09:00 summary goes as usual)
    assert len(out) == 1 and out[0].startswith("🔄 새로 시작 · 후보 리그")
    assert f"{N._kst(FLOOR)} KST 시작부터 모든 계좌 $5,000으로 다시 계산했습니다" in out[0]
    assert "파산 1 · 경고등 1" in out[0] and "이전 기록은 서버에 복사해 두었습니다" in out[0]
    assert nt.after_pass({**doc, "done_ms": NOW}, NOW + 400_000, caught_up=True) == []      # said once, busts counted in it
    out = nt.after_pass({**doc, "accounts": [row(1, True), row(2, True)]}, NOW + 700_000, caught_up=True)
    assert len(out) == 1 and out[0].startswith("🚨 후보 리그 파산")                          # a new bust after it: as before


# ------------------------------------------------------------------------------------------------ Telegram
def test_summary_counts_days_from_the_start():
    start = 1_791_687_600_000                                              # 2026-10-11 03:00 UTC = 12:00 KST
    now = 1_791_763_260_000                                                # 2026-10-12 09:01 KST
    doc = {"done_ms": now - 400_000, "start_ms": start, "lag_s": 60, "accounts": [], "judge": {}, "watch": {}}
    t = N.summary_text(doc, now)
    assert "D+1 · 10/11 12:00 시작부터 2일째" in t.split("\n")[2] and "10/01" not in t
    assert N.start_line({**doc}, start + 3_600_000) == "D+0 · 10/11 12:00 시작부터 1일째"


# ------------------------------------------------------------------------------------------------ the dashboard
LEAGUE = """
const START = 1791687600000, INSTALL = START + 207e3, NOW = 1791763260000;      // 10/11 12:00 KST, 12:03:27, 10/12 09:01
const lg = (o = {}) => ({start_ms: START, started_ms: INSTALL, generated_ms: NOW - 60e3, done_ms: NOW - 400e3, lag_s: 340, accounts: [],
  judge: {}, notes: [], ds_money: true, server: {}, watch: {checkpoints: [
    {id: "C1", date: "2026-11-11", ko: "1차 점검", after: "시작 후 한 달", what: "멈출지 보기", ms: 1794355200000, days_left: 30},
    {id: "C2", date: "2026-12-11", ko: "2차 점검", after: "시작 후 두 달", what: "통과 보기", ms: 1796947200000, days_left: 60}],
    pools: {}, strategies: {}, picks: {}, min_trades: 300}, ...o});
"""


def test_lk_helpers_and_the_hidden_switch(tmp_path):
    o = POS._run(tmp_path, LEAGUE + f"""
const A = await import("file://{os.path.join(JS, 'after.js')}");
const d = lg();
LKm.setLeague(d);
out.day = [LKm.dPlus(d, NOW), LKm.calDay(d, NOW), LKm.dPlus(d, START + 3600e3), LKm.calDay(d, START + 3600e3)];
out.line = LKm.dayLine(d, NOW); out.from = LKm.fromKo(d); out.start = LKm.startKo(d);
out.replay = [LKm.replayedBefore(d), LKm.replayedBefore(lg({{start_ms: 1790812800000}}))];
out.catching = [LKm.catchingUp(d), LKm.catchingUp(lg({{done_ms: NOW - 40 * 60e3}})), LKm.catchingUp(lg({{started_ms: NOW + 864e5}}))];
out.health = LKm.health(lg({{done_ms: NOW - 20 * 3600e3, generated_ms: NOW - 30e3}}), NOW).ko;
out.healthFlag = [LKm.health(lg({{done_ms: NOW - 20 * 3600e3, generated_ms: NOW - 30e3, catching: true}}), NOW).ko,
  LKm.health(lg({{done_ms: NOW - 3 * 3600e3, generated_ms: NOW - 20e3, catching: false}}), NOW)];   // a crash loop's restart
out.rebuild = [LKm.replayedBefore(lg({{started_ms: START}})), A.installMs(lg({{started_ms: START}}))];
const ban = K.staleBanner({{catching_up: true, start_ms: START, done_ms: START + 3900e3, generated_ms: NOW}});
out.banner = [...ban.childNodes].map((n) => n.textContent);
out.install = [A.installMs(d), A.installMs(lg({{start_ms: 1790812800000}}))];
localStorage.setItem("cl-after", "true");                          // a viewer who had the switch on before the update
out.afterOn = A.afterOn(d);
const bar = A.afterBar();
out.barHidden = bar.hidden;
const PP = {{started_ms: INSTALL, start_ms: START, positions: [{{id: "a", since: START + 60e3}}], counts: {{open: 1}}}};
out.posSame = A.afterPositions(PP) === PP;
""")
    assert o["day"] == [1, 2, 0, 1]
    assert o["line"] == "D+1 · 10/11 12:00 시작부터 2일째" and o["from"] == "10/11 12:00 시작부터" and o["start"] == "10/11 12:00"
    assert o["replay"] == [False, True] and o["catching"] == [False, True, False]
    assert o["health"] == "따라잡는 중 (10/11 13:01까지 계산)"            # a snapshot without the engine's flag
    assert o["healthFlag"][0] == "따라잡는 중 (10/11 13:01까지 계산)"
    assert o["healthFlag"][1]["lv"] == "bad" and "늦음" in o["healthFlag"][1]["ko"]
    assert o["rebuild"] == [False, None]                                   # a CANDLEAGUE_START rebuild: no replay framing
    assert o["banner"] == ["엔진이 따라잡는 중", "10/11 12:00 시작부터 10/11 13:05 KST까지 계산함 · 아래 포지션은 그 시각의 것이라 "
                           "실시간 손익·거리는 감춥니다 (따라잡으면 저절로 보임)"]
    assert o["install"] == [None, 1791687600000 + 207000] and o["afterOn"] is False and o["barHidden"] and o["posSame"]


def _ctx():
    return """
const subs = {league: [], pos: []};
const ctx = {meta: async () => ({}), api: async (p) => (await fetch(p)).json(), onLeague: (f) => { subs.league.push(f); if (LKm.league()) f(LKm.league()); },
  onPositions: (f) => { subs.pos.push(f); }, onLive: () => {}, every: () => {}, onAfterChange: () => {}, args: [], query: {}};
"""


def test_home_and_status_read_the_start(tmp_path):
    """요약's 일정 card (D+n, its first step, the line under it, the LED bar's day cell) and 서버 상태's tiles read the
    snapshot's start; the catch-up shows its share of the span from the start; no 10/01 anywhere, no switch."""
    o = POS._run(tmp_path, LEAGUE + _ctx() + f"""
globalThis.API["/api/fills"] = {{fills: []}};
globalThis.API["/api/live"] = {{coins: [], generated_ms: NOW}};
const H = await import("file://{os.path.join(JS, 'screens', 'home.js')}");
const S = await import("file://{os.path.join(JS, 'screens', 'status.js')}");
const LV = await import("file://{os.path.join(JS, 'live.js')}");
LV.noteServerMs && LV.noteServerMs(NOW);
LKm.setLeague(lg());
const el = document.createElement("div");
document.body.append(el);
await H.mount(el, ctx);
await tick(50);
out.home = el.textContent;
out.goal = el.querySelector(".s2a-goal") ? el.querySelector(".s2a-goal").textContent : null;
out.switchShown = el.querySelectorAll(".kp-after").filter((b) => !b.hidden).length;
const st = document.createElement("div");
document.body.append(st);
LKm.setLeague(lg({{done_ms: START + 6 * 3600e3, generated_ms: NOW - 30e3}}));            // right after the start-over
await S.mount(st, ctx);
await tick(50);
out.status = st.textContent;
""")
    assert "10/01" not in o["home"] and "10월 1일" not in o["home"] and o["switchShown"] == 0
    g = o["goal"]
    assert "D+1 (2일째, 한국 날짜)" in g and "10/1112:00 시작 (설치)" in g and "다시 돌리기" not in g
    assert "봇을 켠 때(10/11 12:00)부터 모든 계좌 $5,000으로 시작" in g
    assert "시작부터" in o["home"] and "시작 후 한 달 · 멈출지 보기" in o["home"]
    s = o["status"]
    assert "10/01" not in s and "10/11 12:00 시작 (설치한 때)" in s and "따라잡는 중 (시작부터 기록 쓴 시각까지의" in s


def _strings_without_comments_js(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//\s.*$", "", ln) for ln in text.splitlines())


def _py_strings(path: str) -> list[str]:
    out = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.STRING:
                out.append(tok.string)
    return out


def test_no_hard_coded_first_day_left():
    bad = []
    for path in glob.glob(os.path.join(ROOT, "candleague", "static", "**", "*.js"), recursive=True) + \
            [os.path.join(ROOT, "candleague", "static", "index.html")]:
        if "vendor" in path:
            continue
        code = _strings_without_comments_js(open(path, encoding="utf-8").read())
        bad += [f"{path}: {m}" for m in re.findall(r".{0,30}(?:10/01|10월 1일).{0,30}", code)]
    for name in ("notify.py", "summary.py", "dash.py"):
        for s in _py_strings(os.path.join(ROOT, "candleague", name)):
            if re.search(r"10/01|10월 1일|10-01", s):
                bad.append(f"{name}: {s[:80]}")
    assert not bad, bad


def test_install_script_copies_before_the_swap():
    sh = open(os.path.join(ROOT, "deploy", "candleague", "install_candleague.sh")).read()
    # the engine and the watch are stopped whatever their state (a crash-looping engine is "activating", not "active")
    stop = sh.index("systemctl stop candleague-live.service candleague-watch.timer candleague-watch.service $RUNNING")
    assert "active|activating|reloading) RUNNING=" in sh[:stop]
    copy = sh.index("-m candleague backup")
    swap = sh.index('mv "$APP.new" "$APP"')
    assert stop < copy < swap
    assert 'cd "$APP.new" && runuser -u candleague' in sh[stop:copy + 400]        # the NEW code decides, as candleague
    fail = sh[sh.index('if [ "$BK_RC" -ne 0 ]; then'):swap]                     # a failed copy: nothing swapped
    assert 'rm -rf "$APP.new"' in fail and "systemctl start $RUNNING" in fail and "exit 1" in fail
    assert "10월 1일부터 따라잡" not in sh


def test_home_and_rank_memories_belong_to_one_record(tmp_path):
    """요약's 자리 비운 사이 and 순위표's ▲▼ remember the last visit per device: a visit to the record before the
    start-over is not compared with the new one, and a visit during the catch-up is not remembered."""
    o = POS._run(tmp_path, LEAGUE + _ctx() + f"""
globalThis.API["/api/fills"] = {{fills: []}};
globalThis.API["/api/live"] = {{coins: [], generated_ms: NOW}};
const H = await import("file://{os.path.join(JS, 'screens', 'home.js')}");
const RR = await import("file://{os.path.join(JS, 'screens', 'rank-rows.js')}");
const acct = {{id: "c1", role: "cand", kind: "core", name: "S2_ST_ROC", tf: "15m", trades: 40, wins: 20, mean_ret: 0.01, wallet: 5100, bust: false}};
const was = {{t: NOW - 5 * 864e5, judge: {{c1: ["not_yet", false]}}, bust: []}};             // the 10/01 record, no start
localStorage.setItem("cl-home-seen", JSON.stringify(was));
LKm.setLeague(lg({{accounts: [acct], judge: {{c1: {{verdict: "early"}}}}, catching: true}}));
let el = document.createElement("div");
document.body.append(el);
await H.mount(el, ctx);
await tick(50);
out.awayOld = el.textContent.includes("자리 비운 사이");
out.kept = localStorage.getItem("cl-home-seen") === JSON.stringify(was);
const m1 = RR.rankMemo("rank-memo|" + START, {{now: NOW}}); m1.save({{c1: 0.02}});
const m2 = RR.rankMemo("rank-memo|" + 1790812800000, {{now: NOW + 3600e3}});
out.memoOther = m2.base;
""")
    assert o["awayOld"] is False and o["kept"] is True and o["memoOther"] is None


def test_open_pages_learn_of_an_update(tmp_path, monkeypatch):
    """/api/league carries the installed commit (VERSION.json next to the code) so an open page reloads itself after an
    update (app.js pollLeague) instead of showing the old screens; nothing is added in a checkout without the file."""
    from fastapi.testclient import TestClient
    from candleague.live import Live
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "league.json").write_text(json.dumps({"accounts": [], "start_ms": 1}))

    def client():
        c = TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32, live=Live(mode="fake")),
                       base_url="http://league.test")
        c.post("/login", content="password=pw-123", follow_redirects=False,
               headers={"content-type": "application/x-www-form-urlencoded", "origin": "http://league.test"})
        return c
    assert D.code_version() is None and "code" not in client().get("/api/league").json()
    monkeypatch.setattr(D, "code_version", lambda: "abc123")
    assert client().get("/api/league").json() == {"accounts": [], "start_ms": 1, "code": "abc123"}
    app = open(os.path.join(JS, "app.js"), encoding="utf-8").read()
    assert "codeSeen && d.code !== codeSeen) { location.reload();" in app
