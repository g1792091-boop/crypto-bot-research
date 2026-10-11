"""후보 리그 starts at its install time (owners 2026-10-12: "거래기록은 왜 안보이는거야? ... 커스텀값 봇 돌린 시점부터
원래 돌리고있었던 규칙봇 형식처럼 해야지 봇 돌린시점부터 거래 기록이랑 다 보이게").

* Engine (candleague/runner.py): a VERSION 1 database (replayed from 2026-10-01, meta.started_ms = the install time)
  starts over on the new code's first construction FROM ITS INSTALL TIME floored to 5 minutes: the replay's trades and
  engine states are gone, a copy of the whole old database is kept next to it (league_replay_from_1001_<UTC date>.db,
  made once even when the install script made it first), meta.start_ms is recorded and meta.started_ms kept; a second
  construction does not start over again; a later VERSION bump starts over from the SAME recorded start; a fresh
  database starts at its own first run; a copy that cannot be made deletes nothing.
* Catching up is "the processed time was more than 30 minutes behind the clock when the record was written"
  (dash.py catching_up, lk.js catchingUp), never the install time.
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


def _league(db, now=NOW, start_ms=None, db_path=True):
    return RN.League(RN.open_db(str(db)), _accts(), TP.BRACKETS, TP.SPECS, sweepsig.lib(), PS.FrameSource(data),
                     TP._steps_from(data), TP.SYMS, start_ms=start_ms, log=lambda s: None,
                     db_path=str(db) if db_path else None, now_ms=now)


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
    lg = _league(tmp_path / "b.db", start_ms=START + 61_000)               # CANDLEAGUE_START: a lost database rebuilt
    assert lg.start_ms == START
    assert RN.parse_start("2026-10-11T03:00Z") == RN.parse_start("2026-10-11 03:00") == 1_791_687_600_000
    assert RN.parse_start("1791687600000") == 1_791_687_600_000 and RN.parse_start("") is None
    assert RN.league_start({"start_ms": 7 * RN.FIVE + 1, "started_ms": 99}, 0, 5) == (7 * RN.FIVE, 99)


# ------------------------------------------------------------------------------------------------ catching up
def test_catching_up_reads_the_lag_not_the_install_time():
    t = 1_791_700_000_000
    assert D.catching_up({"generated_ms": t, "done_ms": t - 31 * 60_000})
    assert not D.catching_up({"generated_ms": t, "done_ms": t - 29 * 60_000})
    assert not D.catching_up({"generated_ms": t, "done_ms": t - 6 * 60_000, "started_ms": t + 86_400_000})
    assert not D.catching_up({"done_ms": t}) and not D.catching_up({})


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
    assert o["health"] == "따라잡는 중 (10/11 13:01까지 계산)"
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
    assert "D+1 (2일째, 한국 날짜)" in g and "시작 12:00 (설치)" in g and "다시 돌리기" not in g
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
    stop = sh.index("systemctl stop $RUNNING")
    copy = sh.index("-m candleague backup")
    swap = sh.index('mv "$APP.new" "$APP"')
    assert stop < copy < swap
    assert 'cd "$APP.new" && runuser -u candleague' in sh[stop:copy + 400]        # the NEW code decides, as candleague
    assert "10월 1일부터 따라잡" not in sh
