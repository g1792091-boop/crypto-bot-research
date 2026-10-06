"""흐름 (dash/more/flow.py): the group race and the profit calendar on a small synthetic paper3.db.

Checks: group medians per hour (the last row of each hour, carried forward; the hour-end fast path and the in-hour
fallback give the same rule), the coin flips' middle-50 % band and the 5m flips' own median, the run start as the first
point and now as the last, step subsampling on Korea-time boundaries, Korea-time days in the calendar (a row or an exit
at exactly 00:00 KST closes the day before), the day's change of the median, up / down counts, best / worst accounts,
trades / wins / P&L / liquidations / busts per day, a day without any record shown as empty (never zero), the season
ending on the verdict day, incremental reads equal a fresh read, copies left out, an empty database, the login, and
the honesty wording in the page files."""

import calendar as _cal
import json
import os
import sqlite3

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import Data, create_app, hash_password  # noqa: E402
from paperbot.dash.more import flow as F  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

H = 3_600_000
MIN = 60_000
INIT = 5000.0
START = _cal.timegm((2026, 9, 29, 2, 0, 0)) * 1000          # 11:00 KST, 2026-09-29 (a Tuesday)
NOW = START + 75 * H + 30 * MIN                               # 2026-10-02 14:30 KST
GAP = range(38, 62)                                           # hours ending on KST day 10/1: no equity rows at all
SLOPE = {"S1@15m": 1, "S2@15m": 2, "S3@1h": 3, "D1@15m": -1, "D2@15m": -3, "REEL_H1@5m": 10,
         "RANDOM_1@5m": 0, "RANDOM_2@5m": 1, "RANDOM_3@5m": -1, "RANDOM_1@15m": 2, "RANDOM_2@15m": -2, "C1@15m": 50}
KIND = {"S": "strategy", "D": "ds200", "R": "reel", "C": "copy"}
PW = "correct horse battery"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")


def kind_of(aid: str) -> str:
    return "random" if aid.startswith("RANDOM") else "reel" if aid.startswith("REEL") else KIND[aid[0]]


def _trade(c, aid, t, pnl, reason, eq_after):
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
              "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (aid, "BTCUSDT", t - H, t, reason, 20, pnl, pnl / 100, eq_after,
               json.dumps({"side": 1, "entry_price": 100.0, "exit_price": 101.0, "fees": 0.1, "funding": 0.0})))


def make_db(path: str) -> str:
    st = Store3(path)
    for aid in SLOPE:
        strat, tf = aid.split("@")
        st.add_account(aid, strat, tf, kind_of(aid), START, "paper-v4", "S1" if aid.startswith("C") else None, {})
    st.put_state("run", START, {"initial_equity": INIT, "taker_fee": 0.0005})
    for aid, k in SLOPE.items():
        for i in range(1, 76):
            if i in GAP:
                continue
            st.equity(aid, START + i * H, INIT + k * i, 0.0)
    # S1, hour 5: no row at the hour's end, two rows inside it -> the later one (8000) is the hour's value
    st.conn.execute("DELETE FROM equity WHERE account_id = 'S1@15m' AND ts = ?", (START + 5 * H,))
    st.equity("S1@15m", START + 5 * H - 20 * MIN, 9000.0, 0.0)
    st.equity("S1@15m", START + 5 * H - 10 * MIN, 8000.0, 0.0)
    c = st.conn
    _trade(c, "S1@15m", START + 3 * H, 10.0, "TP", 5010.0)
    _trade(c, "S1@15m", START + 13 * H, -5.0, "SL", 5005.0)      # exactly 00:00 KST 9/30: closes 9/29
    _trade(c, "S1@15m", START + 14 * H, -20.0, "LIQ", 4985.0)
    _trade(c, "RANDOM_2@15m", START + 20 * H, -500.0, "LIQ", 7.0)  # bust (wallet under 10), 07:00 KST 9/30
    _trade(c, "RANDOM_2@15m", START + 22 * H, -1.0, "SL", 6.0)     # a later one does not count again
    _trade(c, "D1@15m", START + 66 * H, 3.0, "TP", 5003.0)         # 10/2
    _trade(c, "C1@15m", START + 3 * H, 99.0, "TP", 5099.0)         # a copy: not in the race
    st.commit()
    st.conn.close()
    return path


@pytest.fixture
def db(tmp_path):
    return make_db(str(tmp_path / "paper3.db"))


def flow(db, now=NOW):
    return F.Flow(Data(db), now_fn=lambda: now)


def at(r, t):
    i = r["t"].index(t)
    return {g: r["median"][g][i] for g in r["median"]}, r["band"]["lo"][i], r["band"]["hi"][i]


# ---------------------------------------------------------------- the race
def test_race_medians_band_and_points(db):
    r = flow(db).race("3600000")
    assert r["ready"] and r["step"] == H and r["keys"] == ["core", "ds200", "reel", "flip"]
    assert r["n"] == {"core": 3, "ds200": 2, "reel": 1, "flip": 5, "flip5m": 3}       # the copy is left out
    assert r["t"][0] == START and r["t"][-1] == NOW and len(r["t"]) == 1 + 75 + 1
    assert all(r["median"][g][0] == INIT for g in ("core", "ds200", "reel", "flip", "flip5m"))
    med, lo, hi = at(r, START + 10 * H)
    assert med == {"core": 5020.0, "ds200": 4980.0, "reel": 5100.0, "flip": 5000.0, "flip5m": 5000.0}
    assert (lo, hi) == (4990.0, 5010.0)                       # flips 5000 -/+ 2k, k: the 25th / 75th percentile
    # hour 5 of S1 has no end-of-hour row: its last row inside the hour (8000) counts, not the earlier 9000
    med5, _, _ = at(r, START + 5 * H)
    assert med5["core"] == 5015.0                             # sorted 5010, 5015, 8000
    assert at(r, START + 6 * H)[0]["core"] == 5012.0
    # 10/1 has no rows: carried forward from the last hour of 9/30 (k = 37) through the whole day
    assert at(r, START + 50 * H)[0]["core"] == 5074.0
    assert at(r, START + 75 * H)[0]["core"] == 5150.0 and r["median"]["core"][-1] == 5150.0
    assert r["busts"] == [[START + 20 * H, "flip"]]
    assert r["next_verdict"] == _cal.timegm((2026, 10, 29, 0, 0, 0)) * 1000 and r["verdict_k"] == 1
    assert len(json.dumps(r)) < 150_000


def test_race_steps_keep_korea_time_boundaries(db):
    f = flow(db)
    assert f.race("auto")["step"] == 15 * MIN                 # day 3: 15 minutes (fill-home; hourly from day 7)
    for step in (4 * H, 24 * H):
        r = f.race(str(step))
        assert r["step"] == step and r["t"][0] == START and r["t"][-1] == NOW
        assert all((t + 9 * H) % step == 0 for t in r["t"][1:-1])
    day = f.race(str(24 * H))
    assert day["t"][1:-1] == [START + 13 * H, START + 37 * H, START + 61 * H]   # 00:00 KST 9/30, 10/1, 10/2
    assert day["median"]["core"][1:-1] == [5026.0, 5074.0, 5074.0]
    assert F.auto_step(0, 41 * 24 * H) == 4 * H and F.auto_step(0, 161 * 24 * H) == 24 * H


def test_incremental_reads_equal_a_fresh_read(db):
    f = flow(db, START + 30 * H + 30 * MIN)
    f.sync(force=True)
    early = f.race("3600000")
    assert early["t"][-1] == START + 30 * H + 30 * MIN
    f.now_fn = lambda: NOW
    f.cache.clear()
    f.sync(force=True)
    assert f.race("3600000") == flow(db).race("3600000")
    assert f.calendar() == flow(db).calendar()


# ---------------------------------------------------------------- the calendar
def test_calendar_days_changes_counts_and_accounts(db):
    c = flow(db).calendar()
    assert c["ready"] and c["season"] == 0 and c["seasons"] == 1 and c["today"] == "2026-10-02"
    days = c["days"]
    assert len(days) == 31 and days[0]["d"] == "2026-09-29" and days[-1]["d"] == "2026-10-29"
    assert days[0]["dow"] == 1 and days[0]["i"] == 0                       # Tuesday, run day 0
    assert days[-1]["verdict"] == c["verdict_ts"] == _cal.timegm((2026, 10, 29, 0, 0, 0)) * 1000
    by = {d["d"]: d for d in days}
    d1 = by["2026-09-29"]
    assert d1["state"] == "done"
    core = d1["g"]["core"]
    assert core["med"] == 5026.0 and core["chg"] == pytest.approx(26 / 5000, abs=1e-6)
    assert (core["up"], core["down"]) == (3, 0)
    assert core["best"]["id"] == "S3@1h" and core["worst"]["id"] == "S1@15m"
    assert core["best"]["chg"] == pytest.approx(39 / 5000, abs=1e-6)
    assert (core["trades"], core["wins"], core["pnl"], core["liq"]) == (2, 1, 5.0, 0)   # the 00:00 exit closes 9/29
    ds = d1["g"]["ds200"]
    assert ds["med"] == 4974.0 and (ds["up"], ds["down"]) == (0, 2) and ds["best"]["id"] == "D1@15m"
    assert d1["g"]["reel"]["chg"] == pytest.approx(130 / 5000, abs=1e-6)
    assert d1["g"]["flip"]["chg"] == 0.0 and d1["f5"] == {"med": 5000.0, "chg": 0.0, "n": 3}
    d2 = by["2026-09-30"]
    assert d2["g"]["core"]["chg"] == pytest.approx(48 / 5026, abs=1e-6)
    assert (d2["g"]["core"]["trades"], d2["g"]["core"]["liq"], d2["g"]["core"]["pnl"]) == (1, 1, -20.0)
    assert d2["g"]["flip"]["busts"] == 1 and d2["g"]["flip"]["trades"] == 2 and d2["g"]["core"]["busts"] == 0
    # 10/1: not a single equity row -> no record, never a zero
    assert by["2026-10-01"]["state"] == "empty" and "g" not in by["2026-10-01"]
    d4 = by["2026-10-02"]
    assert d4["state"] == "today" and d4["g"]["core"]["med"] == 5150.0
    assert d4["g"]["core"]["chg"] == pytest.approx(76 / 5074, abs=1e-6)        # against the carried end of 10/1
    assert d4["g"]["ds200"]["trades"] == 1 and d4["g"]["ds200"]["wins"] == 1
    assert all(d["state"] == "future" and "g" not in d for d in days if d["d"] > "2026-10-02")
    assert len(json.dumps(c)) < 150_000


def test_seasons_end_on_the_verdict_day():
    start = START
    ss = F.Flow.seasons(start, F.kst_day(start))
    assert len(ss) == 1 and ss[0][0] == F.kst_day(start) and F.day_label(ss[0][1]) == "2026-10-29"
    later = F.Flow.seasons(start, F.kst_day(_cal.timegm((2026, 11, 2, 0, 0, 0)) * 1000))
    assert len(later) == 2 and F.day_label(later[1][0]) == "2026-10-30" and F.day_label(later[1][1]) == "2026-11-28"
    assert F.weekday(F.kst_day(start)) == 1 and F.day_label(F.kst_day(start + 13 * H)) == "2026-09-30"
    assert F.kst_day(start + 13 * H - 1) == F.kst_day(start)                  # 23:59:59.999 KST is still 9/29


def test_an_empty_database_answers_not_ready(tmp_path):
    p = str(tmp_path / "empty.db")
    Store3(p).conn.close()
    f = flow(p)
    assert f.race("auto")["ready"] is False and f.race("auto")["t"] == []
    assert f.calendar() == {"ready": False, "season": 0, "seasons": 0, "days": []}


def test_quantile_matches_the_linear_rule():
    assert F.quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert F.quantile([1.0, 2.0, 3.0, 4.0, 5.0], 0.25) == 2.0
    assert F.quantile([7.0], 0.75) == 7.0 and F.quantile([], 0.5) is None


# ---------------------------------------------------------------- the routes, behind the login
def test_routes_are_registered_read_only_and_behind_the_login(db):
    before = os.path.getmtime(db)
    c = TestClient(create_app(db, hash_password(PW), b"x" * 32))
    assert c.get("/api/v4/flow/race").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/api/v4/flow/race?step=auto")
    assert r.status_code == 200 and r.json()["ready"] and r.json()["n"]["core"] == 3
    k = c.get("/api/v4/flow/calendar")
    assert k.status_code == 200 and k.json()["ready"] and k.json()["days"][0]["d"] == "2026-09-29"
    assert c.get("/api/v4/flow/calendar?season=9").json()["season"] == k.json()["seasons"] - 1
    assert "flow" in c.app.state.more
    assert os.path.getmtime(db) == before                                  # nothing written
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM equity").fetchone()[0] > 0


# ---------------------------------------------------------------- the page files: honesty and the home card
def _src(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as fh:
        return fh.read()


def test_page_files_keep_the_honesty_rules():
    js = {n: _src(n) for n in ("flow.js", "flow-kit.js", "flow-cal.js")}
    for n in ("flow.js", "flow-cal.js"):
        assert "ui.refNote(" in js[n] and "ui.assume(" in js[n], n             # comparison + money captions
    for n, s in js.items():
        for word in ("승자", "우승", "합격", "통과", "1등", "꼴찌", "최고의 매매법"):
            assert word not in s, (n, word)
    kit = js["flow-kit.js"]
    assert "export function raceMini(ctx)" in kit and '"/api/v4/flow/race"' in kit
    assert "motion.reduced()" in kit                                       # no replay under reduced motion
    assert "visibilitychange" in js["flow.js"] and "chart.pause()" in js["flow.js"]   # paused when hidden
    assert '"/api/v4/flow/calendar"' in js["flow-cal.js"] and "기록 없음" in js["flow-cal.js"]
    assert _src("flow.css").startswith('@import url("flow-kit.css");')
    assert 'new URL("flow-kit.css", import.meta.url)' in kit              # home loads the kit css itself
