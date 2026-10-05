"""Wave 3 dashboard additions (dash/more/bell.py, uptime.py, tradeshape.py and their page files) on small synthetic
databases: the approval bell's count, the uptime record's minutes / stops / restarts / night checks, the weekday x hour
heat and the fixed-bin result distribution (coin flips counted only, 5m flips and DeepSeek left out), the login, nothing
written, and the honesty rules in the page files (captions, no pass/fail words, no markup, tokens only)."""

import calendar as _cal
import json
import os
import re
import sqlite3

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.agents import rooms_db as R  # noqa: E402
from paperbot.dash.app import _ro_uri, create_app, hash_password  # noqa: E402
from paperbot.dash.more import tradeshape as T  # noqa: E402
from paperbot.dash.more import uptime as U  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

MIN = 60_000
H = 3_600_000
DAY = 86_400_000
KST = 9 * H
PW = "w3 horse battery"
SECRET = b"w" * 32
START = _cal.timegm((2026, 10, 5, 1, 0, 0)) * 1000            # 10:00 KST Monday 2026-10-05
NOW = START + 2 * DAY + 5 * H + 30 * MIN                       # 2026-10-07 15:30 KST
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
ACCOUNTS = [("S1@15m", "strategy"), ("S2@1h", "strategy"), ("DS1@15m", "ds200"), ("RANDOM_1@15m", "random"),
            ("RANDOM_1@5m", "random"), ("REEL_H1@5m", "reel")]


def _trade(c, aid, entry, pnl, eq_after, reason="SL"):
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)", (aid, "BTCUSDT", entry, entry + 30 * MIN, reason, 30, pnl, pnl / 100, eq_after, "{}"))


def make_world(tmp_path, gap=True):
    db = str(tmp_path / "paper3.db")
    st = Store3(db)
    for aid, kind in ACCOUNTS:
        s, tf = aid.split("@")
        st.add_account(aid, s, tf, kind, START, "paper-v4", None, {})
    st.put_state("run", START, {"initial_equity": 5000.0, "taker_fee": 0.0005})
    c = st.conn
    # trades: entry 10:00 KST Monday (weekday 0, hour 10) and 15:00 KST Tuesday (1, 15)
    _trade(c, "S1@15m", START, 250.0, 5250.0, "LOCK")                 # +5 % of 5000 -> bin '5~10%'
    _trade(c, "S1@15m", START + DAY + 5 * H, -525.0, 4725.0)          # exactly -10 % of 5250 -> bin "−10~−5%"
    _trade(c, "S2@1h", START, -2000.0, 3000.0, "LIQ")                  # -40 % -> '−20% 밑'
    _trade(c, "DS1@15m", START, 900.0, 5900.0)                         # DeepSeek: not in this picture
    _trade(c, "RANDOM_1@15m", START + DAY + 5 * H, 50.0, 5050.0)       # +1 % -> '0~2%' (counted, never summed)
    _trade(c, "RANDOM_1@5m", START, -50.0, 4950.0)                     # 5m flip: the reel's comparison, left out
    # live_bars: every minute from the start to now - 3 min, two coins, except a 10-minute stop on day 2 at 03:00 KST
    stop0 = START + DAY - 7 * H                                        # 2026-10-06 03:00 KST
    rows = []
    t = START
    while t < NOW - 3 * MIN:
        if not (gap and stop0 <= t < stop0 + 10 * MIN):
            for sym in ("BTCUSDT", "ETHUSDT"):
                rows.append((t, sym, 1.0, 1.0, 1.0, 1.0, 1.0, t + 61_000))
        t += MIN
    c.executemany("INSERT INTO live_bars (ts, symbol, open, high, low, close, volume, processed_at) VALUES (?,?,?,?,?,?,?,?)", rows)
    c.execute("INSERT INTO runs (started_ts, data) VALUES (?, ?)", (stop0 + 10 * MIN, "{}"))
    c.commit()
    c.close()
    # daily3.db: one night check
    from paperbot import daily3
    ddb = str(tmp_path / "daily3.db")
    d = sqlite3.connect(ddb)
    d.executescript(daily3.SCHEMA)
    d.execute("INSERT INTO reports (day, ts, data) VALUES (?,?,?)",
              ("2026-10-05", START + DAY - 9 * H + 30 * MIN, json.dumps({"parity": {"accounts": 6, "mismatched_accounts": 1}})))
    d.commit()
    d.close()
    return db, ddb, stop0


def _ro(db):
    return sqlite3.connect(_ro_uri(db), uri=True)


# ---------------------------------------------------------------- tradeshape
def test_bins_are_fixed_and_cover_everything():
    assert len(T.BIN_KO) == len(T.BINS) + 1 == 10
    assert T.bin_of(-0.5) == 0 and T.bin_of(-0.2) == 1 and T.bin_of(-0.1) == 2 and T.bin_of(-0.0001) == 4
    assert T.bin_of(0.0) == 5 and T.bin_of(0.05) == 7 and T.bin_of(0.2) == 9 and T.bin_of(3.0) == 9
    assert T.kst_wd_hour(START) == (0, 10) and T.kst_wd_hour(START + DAY + 5 * H) == (1, 15)


def test_shape_counts_the_36_and_same_timeframe_flips_only(tmp_path):
    db, _ddb, _s = make_world(tmp_path)
    with _ro(db) as c:
        d = T.shape(c, NOW)
    assert d["ready"] and d["trades"] == {"core": 3, "flip": 1}
    assert d["wins"] == {"core": 1, "flip": 1} and d["liq"] == {"core": 1, "flip": 0}
    dist = d["dist"]
    assert dist["core"][0] == 1 and dist["core"][2] == 1 and dist["core"][7] == 1 and sum(dist["core"]) == 3
    assert dist["flip"][5] == 1 and sum(dist["flip"]) == 1
    assert abs(sum(dist["core_share"]) - 1) < 1e-5
    mon10 = d["heat"]["core"][0][10]
    assert mon10["n"] == 2 and mon10["w"] == 1 and mon10["pnl"] == -1750.0
    assert d["heat"]["core"][1][15]["n"] == 1
    flip = d["heat"]["flip"][1][15]
    assert flip == {"n": 1, "w": 1}                                     # coin flips: counted, never with money
    assert d["heat"]["flip"][0][10] is None                            # the 5m flip is not here
    assert sum(x["n"] for row in d["heat"]["core"] for x in row if x) == 3   # DeepSeek is not here


def test_shape_of_an_empty_run_is_not_ready(tmp_path):
    st = Store3(str(tmp_path / "e.db"))
    st.conn.close()
    with _ro(str(tmp_path / "e.db")) as c:
        assert T.shape(c, NOW)["ready"] is False


# ---------------------------------------------------------------- uptime
def test_uptime_counts_minutes_stops_restarts_and_night_checks(tmp_path):
    db, ddb, stop0 = make_world(tmp_path)
    with _ro(db) as c:
        d = U.uptime(c, ddb, 7, NOW)
    assert d["ready"] and d["days"] == 7 and len(d["rows"]) == 7
    assert d["stops_n"] == 1 and d["stops"][0]["min"] == 10 and d["stops"][0]["from"] == stop0
    assert d["missing_min"] == 10 and d["stops_min"] == 10
    assert d["expected_min"] - d["stepped_min"] == 10 and 0.99 < d["share"] < 1
    assert [r["ts"] for r in d["restarts"]] == [stop0 + 10 * MIN]
    assert d["nightly"] == [{"day": "2026-10-05", "ts": START + DAY - 9 * H + 30 * MIN, "accounts": 6, "mismatched": 1}]
    rows = {r["day"]: r["h"] for r in d["rows"]}
    assert rows["2026-10-05"][9] is None                               # before the run: nothing expected
    assert rows["2026-10-05"][10] == [60, 60]
    assert rows["2026-10-06"][3] == [50, 60]                           # the stop
    assert rows["2026-10-07"][15] == [27, 27]                          # the hour now: minutes up to now - 3
    assert rows["2026-10-07"][16] == -1                                # still ahead
    assert rows["2026-10-01"] == [None] * 24


def test_uptime_stop_total_counts_every_stop_not_only_the_listed_ones(tmp_path, monkeypatch):
    db, ddb, _s = make_world(tmp_path)
    monkeypatch.setattr(U, "STOPS_MAX", 0)
    with _ro(db) as c:
        d = U.uptime(c, ddb, 7, NOW)
    assert d["stops"] == [] and d["stops_n"] == 1 and d["stops_min"] == 10


def test_uptime_without_gaps_and_before_any_account(tmp_path):
    db, ddb, _s = make_world(tmp_path, gap=False)
    with _ro(db) as c:
        d = U.uptime(c, ddb, 30, NOW)
    assert d["stops_n"] == 0 and d["missing_min"] == 0 and d["stops_min"] == 0 and d["share"] == 1.0 and len(d["rows"]) == 30
    st = Store3(str(tmp_path / "e.db"))
    st.conn.close()
    with _ro(str(tmp_path / "e.db")) as c:
        assert U.uptime(c, None, 7, NOW)["ready"] is False


# ---------------------------------------------------------------- routes (bell, uptime, tradeshape)
@pytest.fixture
def client(tmp_path):
    db, ddb, _s = make_world(tmp_path)
    adb = str(tmp_path / "agents3.db")
    a = R.open_agents(adb)
    R.ensure_rooms(a, ts=START)
    room = "strat:S5_DONCHIAN_MFI"
    tid = R.add_trial(a, room, "S5_DONCHIAN_MFI", "test", {"template": "stop_atr", "k": 2.5}, None, ts=START + H)
    R.add_trial_result(a, tid, "passed", {"gate": {"pass": True}}, ts=START + H)
    R.add_proposal(a, room, "S5_DONCHIAN_MFI", tid, {"strategy": "S5_DONCHIAN_MFI", "why": "합성"}, {"pass": True},
                   "awaiting_owner", ts=START + 2 * H)
    R.add_proposal(a, room, "S5_DONCHIAN_MFI", None, {"strategy": "S5_DONCHIAN_MFI"}, {"pass": False}, "blocked_gate",
                   ts=START + 3 * H)
    a.commit()
    a.close()
    before = os.path.getmtime(db)
    app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], agents_db=adb, daily_db=ddb,
                     inbox_db=str(tmp_path / "inbox.db"))
    return TestClient(app), db, before


def test_routes_sit_behind_the_login_answer_and_write_nothing(client):
    c, db, before = client
    for path in ("/api/v4/bell", "/api/v4/uptime", "/api/v4/tradeshape"):
        assert c.get(path).status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    b = c.get("/api/v4/bell").json()
    assert b["ready"] and b["n"] == 1 and b["rooms"][0]["n"] == 1 and b["items"][0]["strategy"] == "S5_DONCHIAN_MFI"
    u = c.get("/api/v4/uptime?days=30").json()
    assert u["ready"] and u["days"] == 30 and len(u["rows"]) == 30          # (the route runs on the real clock)
    assert c.get("/api/v4/uptime?days=3").json()["days"] == 7               # 7 or 30 only
    s = c.get("/api/v4/tradeshape")
    assert s.status_code == 200 and s.json()["trades"]["core"] >= 2 and len(s.content) < 60_000   # (real clock)
    assert {"bell", "uptime", "tradeshape"} <= set(c.app.state.more)
    assert os.path.getmtime(db) == before


def test_bell_without_agents_db_counts_nothing(tmp_path):
    db, ddb, _s = make_world(tmp_path)
    c = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], agents_db=str(tmp_path / "none.db"),
                              inbox_db=str(tmp_path / "inbox.db")))
    c.post("/api/login", json={"password": PW})
    b = c.get("/api/v4/bell").json()
    assert b["n"] == 0 and b["items"] == []


# ---------------------------------------------------------------- the page files
def _src(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


FILES_JS = [("core", "bell.js"), ("screens", "road-kit.js"), ("screens", "server-uptime.js"), ("screens", "analysis-shape.js")]
FILES_CSS = [("core", "bell.css"), ("screens", "road-kit.css"), ("screens", "server-uptime.css"), ("screens", "analysis-shape.css")]


def test_page_files_keep_the_honesty_and_safety_rules():
    for p in FILES_JS:
        s = _src(*p)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat"):
            assert bad not in s, (p, bad)
        for word in ("승자", "우승", "합격", "통과", "1등", "꼴찌", "✓", "✕"):
            assert word not in s, (p, word)
        assert "http://" not in s.replace("http://www.w3.org/2000/svg", "") and "https://" not in s, p
    shape = _src("screens", "analysis-shape.js")
    assert shape.count("ui.refNote(env.verdictTs)") == 2 and shape.count("ui.assume()") == 2
    assert "참고" in _src("screens", "road-kit.js") and "기록 없음" in _src("screens", "road-kit.js")
    road = _src("screens", "road-kit.js")
    assert "일째" not in road and "s0.restart" in road                   # one day count: the checkpoint clock's D+n
    assert "stops_min" in _src("screens", "server-uptime.js")
    assert "ui.smallSample(tot.core" in shape and "ui.smallSample(tot.flip" in shape
    for p in FILES_CSS:
        s = _src(*p)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", s), p                   # colours only from tokens
        assert "prefers-reduced-motion" in s or "animation" not in s, p


def test_wiring_is_additive():
    shell = _src("core", "shell.js")
    assert 'import {bellButton, startBell} from "./bell.js";' in shell and "startBell();" in shell
    assert 'import {pixelRoad} from "./road-kit.js";' in _src("screens", "home.js")
    assert "pixelRoad(ctx, {card: true})" in _src("screens", "checkpoint.js")
    assert "uptimeCard(ctx)" in _src("screens", "server.js")
    assert "outcomeCard(env)" in _src("screens", "analysis-risk.js") and "heatCard(env)" in _src("screens", "analysis-where.js")
    from paperbot.dash import more
    assert {"bell", "uptime", "tradeshape"} <= set(more.MODULES)
    # polling no faster than the existing screens
    assert "POLL_MS = 60000" in _src("core", "bell.js") and "REFRESH_MS = 120000" in _src("screens", "server-uptime.js")
    assert "REFRESH_MS = 5 * 60 * 1000" in _src("screens", "road-kit.js")
