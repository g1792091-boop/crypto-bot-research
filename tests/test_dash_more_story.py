"""v4 additions: 오늘의 하이라이트 (/api/v4/story, dash/more/story.py) and 지난번 본 뒤로 (/api/v4/since,
dash/more/since.py) on a small synthetic world: the day's numbers per group (up / down / flat, medians, trades, P&L only
for core / reel / extra), the best and worst account of any group, the reel against its three 5m coin flips, DeepSeek at
count level, busts and liquidations, meeting conclusions (the lead's line first), D+n and the run's days; the since
summary (clamped to the run and to 7 days, per-group counts, best / worst trade of core / reel / extra, busts, alerts,
milestones); empty databases; the routes behind the login, cached and small; and the page side's rules (storage
wrapped, never on the first visit, captions and the reference note on the story pages)."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.agents import rooms_db as R  # noqa: E402
from paperbot.dash.app import _ro_uri, create_app, hash_password  # noqa: E402
from paperbot.dash.more import since as N  # noqa: E402
from paperbot.dash.more import story as S  # noqa: E402
from paperbot.models import TradeRecord  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
PW = "story horse battery"
SECRET = b"s" * 32
DAY0 = "2026-10-01"
T0 = S.day_start(DAY0)                       # 00:00 KST of DAY0
NOW = T0 + 15 * HOUR                         # 15:00 KST
START = T0 - 2 * DAY + 10 * HOUR             # 09/29 10:00 KST

ACCOUNTS = [("A@15m", "strategy", {}), ("B@15m", "strategy", {}), ("C@1h", "strategy", {}), ("D@30m", "strategy", {}),
            ("E@30m", "strategy", {}),
            ("F3_BOS@15m", "ds200", {"family": "F3"}), ("F3_BOS@30m", "ds200", {"family": "F3"}),
            ("F3_BOS@1h", "ds200", {"family": "F3"}), ("F9_FVG@15m", "ds200", {"family": "F9"}),
            ("REEL_H1@5m", "reel", {"family": "REEL"}),
            ("RANDOM_1@5m", "random", {}), ("RANDOM_2@5m", "random", {}), ("RANDOM_3@5m", "random", {}),
            ("RANDOM_1@15m", "random", {}), ("RANDOM_1@1h", "random", {})]
# (account, hours after 00:00 KST of DAY0, pnl, exit reason); every account starts at 5,000
TODAY = [("A@15m", 1, 50.0, None), ("A@15m", 2, 25.0, None), ("B@15m", 3, -100.0, None), ("E@30m", 4, -4995.0, "LIQ"),
         ("F3_BOS@15m", 5, 200.0, None), ("F3_BOS@30m", 5.02, -10.0, None), ("F3_BOS@1h", 5.04, 15.0, None),
         ("F9_FVG@15m", 6, 5.0, None), ("F9_FVG@15m", 6.02, 5.0, None),
         ("REEL_H1@5m", 7, 30.0, None), ("REEL_H1@5m", 8, -10.0, None), ("REEL_H1@5m", 9, 20.0, None),
         ("RANDOM_1@5m", 10, 10.0, None), ("RANDOM_3@5m", 10.02, -20.0, None), ("RANDOM_1@15m", 11, -5.0, None)]


def _trade(st, aid, t, pnl, eq_after, reason=None):
    strat, tf = aid.split("@")
    st.trade(aid, TradeRecord(
        strategy_id=strat, symbol="BTCUSDT", timeframe=tf, side=1, signal_ts=t - HOUR, entry_time=t - 30 * MIN,
        entry_price=100.0, exit_time=t, exit_price=101.0, exit_reason=reason or ("LOCK" if pnl > 0 else "SL"), qty=1.0,
        leverage=20, tier="normal", margin=100.0, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=0.1, funding=0.0,
        pnl=pnl, roe=pnl / 100.0, price_move=0.01, mae_price=99.5, mfe_price=101.5, equity_after=eq_after, score=0.0,
        context={}))


def _world(tmp_path, base=T0, start=START):
    """paper3.db and agents3.db of the synthetic day (DAY0 shifted to ``base``)."""
    shift = base - T0
    db, adb = str(tmp_path / "p.db"), str(tmp_path / "a.db")
    st = Store3(db)
    for aid, kind, data in ACCOUNTS:
        s, tf = aid.split("@")
        st.add_account(aid, s, tf, kind, start + shift, "paper-v4", None, data)
    st.put_state("run", start + shift, {"initial_equity": 5000.0, "taker_fee": 0.0005})
    wallet = {aid: 5000.0 for aid, _k, _d in ACCOUNTS}
    _trade(st, "D@30m", base - 5 * HOUR, -4996.0, 4.0, "LIQ")              # bust the day before
    wallet["D@30m"] = 4.0
    _trade(st, "C@1h", base - 3 * HOUR, 12.0, 5012.0)                     # yesterday only: flat today
    wallet["C@1h"] = 5012.0
    for aid, h_, pnl, reason in TODAY:
        wallet[aid] += pnl
        _trade(st, aid, base + int(h_ * HOUR), pnl, wallet[aid], reason)
    eng = {aid: {"wallet": w, "bust": aid in ("D@30m", "E@30m")} for aid, w in wallet.items()}
    st.put_state("accounts", base + 14 * HOUR, {"engines": eng, "last_ts": base + 14 * HOUR})
    st.alert(base + 8 * HOUR, "WARN", "[B@15m] drawdown 31.2% (level 30%), equity 3440.10")
    st.alert(base + 8 * HOUR + MIN, "INFO", "시작 알림")
    st.commit()
    st.conn.close()
    a = R.open_agents(adb)
    R.ensure_rooms(a, ts=start + shift)

    def rnd(room, trig, t, status, decision, ended=None):
        return int(a.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status, decision) "
                             "VALUES (?,?,?,?,?,?,?)", (room, trig, "{}", t, ended, status,
                                                         json.dumps(decision, ensure_ascii=False))).lastrowid)
    r1 = rnd("team:review", "ranking", base + 9 * HOUR, "done",
             {"summary_ko": "🧾 결정: 상위가 같은 방향, 운일 수 있음", "final": {"action": "note"}}, base + 9 * HOUR + 9 * MIN)
    R.post(a, "team:review", r1, "ranking", "team_lead", None, "summary", "요약",
           {"answer": {"summary": ["상위 5개 중 4개가 같은 숏 방향이라 시장 덕일 수 있습니다.", "30건 전에는 결론 없음."]}},
           ts=base + 9 * HOUR + 8 * MIN)
    rnd("team:market", "morning", base + 8 * HOUR, "no_action", {"summary_ko": "🧾 아침 회의: 큰 변화 없음"}, base + 8 * HOUR + 5 * MIN)
    rnd("team:risk", "incident", base + 14 * HOUR, "running", {})
    rnd("team:market", "evening", base - 2 * HOUR, "done", {"summary_ko": "🧾 어제 저녁: 할 일 없음"}, base - 2 * HOUR + 5 * MIN)
    a.commit()
    a.close()
    return db, adb


def _conns(db, adb):
    c = sqlite3.connect(_ro_uri(db), uri=True)
    a = R.open_ro(adb)
    return c, a


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """One synthetic world for the read-only tests (building one costs seconds of fsync on a busy disk)."""
    return _world(tmp_path_factory.mktemp("story"))


# ---------------------------------------------------------------- the story of one day
def test_story_counts_the_day_per_group_and_names_the_best_and_worst_of_any_group(world):
    c, a = _conns(*world)
    d = S.story(c, a, DAY0, NOW)
    assert d["ready"] and d["day"] == DAY0 and d["today"] and d["t0"] == T0
    assert d["trades"]["total"] == len(TODAY)
    g = d["trades"]["groups"]
    assert g["core"] == {"trades": 4, "wins": 2, "liq": 1, "pnl": -5020.0}
    assert g["reel"]["pnl"] == 40.0 and g["reel"]["trades"] == 3
    assert "pnl" not in g["ds200"] and "pnl" not in g["flip"]               # DeepSeek and coin flips: counted (D10 / D11)
    core = d["groups"]["core"]                                                # D (bust the day before) is left out
    assert (core["n"], core["up"], core["down"], core["flat"], core["active"]) == (4, 1, 2, 1, 3)
    assert core["median"] == pytest.approx(-0.01) and core["median_active"] == pytest.approx(-0.02)
    assert d["groups"]["flip_same"]["n"] == 2 and d["groups"]["flip5"]["n"] == 3
    assert d["groups"]["flip"]["n"] == 5
    # best / worst: any group, with the group (the page names it and says one day is luck)
    assert d["best"]["account_id"] == "F3_BOS@15m" and d["best"]["group"] == "ds200" and d["best"]["pnl"] == 200.0
    assert d["best"]["change"] == pytest.approx(0.04)
    assert d["worst"]["account_id"] == "E@30m" and d["worst"]["liq"] == 1


def test_story_reel_against_its_three_5m_flips_and_deepseek_at_count_level(world):
    c, a = _conns(*world)
    d = S.story(c, a, DAY0, NOW)
    reel = d["reel"]["accounts"][0]
    assert reel["account_id"] == "REEL_H1@5m" and reel["pips"] == [1, -1, 1] and reel["wins"] == 2
    assert reel["change"] == pytest.approx(40 / 5000)
    flips = d["reel"]["flips"]
    assert [f["account_id"] for f in flips] == ["RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m"]
    assert all("pnl" not in f for f in flips)                                # coin flips: the change only
    assert [f["trades"] for f in flips] == [1, 0, 1]
    assert d["reel"]["flips_median_active"] == pytest.approx((0.002 - 0.004) / 2)
    ds = d["ds"]
    assert (ds["n"], ds["up"], ds["down"], ds["flat"], ds["trades"]) == (4, 3, 1, 0, 5)
    assert ds["best_family"]["family"] == "F3" and ds["best_family"]["n"] == 3
    text = json.dumps(ds)
    assert "F3_BOS@15m" not in text and "account_id" not in text             # no DeepSeek account numbers


def test_story_busts_liquidations_meetings_and_the_run_clock(world):
    c, a = _conns(*world)
    d = S.story(c, a, DAY0, NOW)
    b = d["busts"]
    assert b["liquidations"] == 1 and b["liq_by_group"] == {"core": 1}
    assert b["busts"] == 1 and b["named"][0]["account_id"] == "E@30m"     # D went bust the day before: not today's
    m = d["meetings"]
    assert (m["n"], m["finished"], m["decided"], m["running"]) == (3, 2, 1, 1)
    assert m["lines"][0]["line"].startswith("상위 5개 중 4개가")              # the lead's first line, decision first
    assert m["lines"][1]["line"] == "아침 회의: 큰 변화 없음"                  # else the code summary, lead mark cut
    assert d["dn"] == 2 and d["dn_now"] == 2 and d["of"] == 30
    assert d["days"] == [{"day": "2026-09-29", "dn": 0}, {"day": "2026-09-30", "dn": 1}, {"day": DAY0, "dn": 2}]
    assert d["verdict_ts"] > NOW and d["days_left"] >= 27
    # the day before: its own trades and meetings only
    y = S.story(c, a, "2026-09-30", NOW)
    assert y["trades"]["total"] == 2 and y["meetings"]["n"] == 1 and y["dn"] == 1
    assert y["busts"]["busts"] == 1 and y["busts"]["named"][0]["account_id"] == "D@30m"


def test_story_refuses_days_outside_the_run_and_an_empty_database_is_not_ready(world, tmp_path):
    c, a = _conns(*world)
    for bad in ("2026-09-28", "2026-10-02", "2026-1-01", "x"):
        with pytest.raises(ValueError):
            S.story(c, a, bad, NOW)
    empty = str(tmp_path / "e.db")
    Store3(empty).conn.close()
    e = sqlite3.connect(_ro_uri(empty), uri=True)
    out = S.story(e, None, None, NOW)
    assert out["ready"] is False and out["days"] == []
    s = N.since(e, None, NOW - HOUR, NOW)
    assert s["empty"] is True and s["trades"]["total"] == 0 and s["start"] is None


def test_meetings_without_agents_db_say_so():
    m = S.meetings(None, T0, T0 + DAY)
    assert m["n"] == 0 and m["lines"] == [] and "error" in m


# ---------------------------------------------------------------- since the last visit
def test_since_clamps_to_the_run_and_seven_days():
    now = START + 20 * DAY
    assert N.clamp_after(0, START, now) == (now - 7 * DAY, True)
    assert N.clamp_after(START - DAY, START, START + DAY) == (START, True)
    assert N.clamp_after(now + DAY, START, now) == (now, False)
    assert N.clamp_after(now - HOUR, START, now) == (now - HOUR, False)


def test_since_counts_per_group_names_trades_busts_alerts_and_milestones(world):
    c, a = _conns(*world)
    s = N.since(c, a, T0 + 6 * HOUR + 30 * MIN, NOW)
    t = s["trades"]
    assert t["total"] == 6 and set(t["groups"]) == {"reel", "flip"}
    assert t["groups"]["reel"] == {"trades": 3, "wins": 2, "liq": 0, "pnl": 40.0}
    assert "pnl" not in t["groups"]["flip"]                                 # coin flips: counted only
    assert s["best"]["account_id"] == "REEL_H1@5m" and s["best"]["pnl"] == 30.0 and s["best"]["group"] == "reel"
    assert s["worst"]["pnl"] == -10.0
    assert s["busts"]["n"] == 0 and s["alerts"]["n"] == 1 and s["alerts"]["latest"][0]["level"] == "WARN"
    assert s["meetings"]["finished"] == 2 and s["meetings"]["lines"][0]["room_id"] == "team:review"
    assert {"kind": "day", "from": 1, "to": 2} in s["milestones"] and s["empty"] is False
    # earlier: the liquidation and the bust of E come in; DeepSeek P&L stays out, the best trade is of core / reel only
    s2 = N.since(c, a, T0 + 3 * HOUR + 30 * MIN, NOW)
    assert s2["busts"]["n"] == 1 and s2["busts"]["named"][0]["account_id"] == "E@30m"
    assert s2["trades"]["liquidations"] == 1 and "pnl" not in s2["trades"]["groups"]["ds200"]
    assert s2["best"]["account_id"] == "REEL_H1@5m"                         # F3_BOS's +200 is DeepSeek: not named
    assert s2["worst"]["account_id"] == "E@30m"
    # nothing after the last trade, alert and meeting
    s3 = N.since(c, a, NOW - MIN, NOW)
    assert s3["empty"] is True and s3["best"] is None and s3["worst"] is None


# ---------------------------------------------------------------- the routes
@pytest.fixture
def client(world, tmp_path):
    db, adb = world
    app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], agents_db=adb,
                     inbox_db=str(tmp_path / "inbox.db"))
    c = TestClient(app)
    return c, app


def test_routes_sit_behind_the_login_answer_small_and_are_cached(client):
    c, app = client
    assert c.get("/api/v4/story").status_code == 401 and c.get("/api/v4/since?after=0").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    t = time.perf_counter()
    r = c.get(f"/api/v4/story?day={DAY0}")
    assert r.status_code == 200 and time.perf_counter() - t < 5
    d = r.json()
    assert d["trades"]["total"] == len(TODAY) and len(r.content) < 150_000
    assert DAY0 in app.state.more["story"]["cache"]
    assert c.get(f"/api/v4/story?day={DAY0}").json() == d                  # the cached answer
    assert c.get("/api/v4/story").status_code == 200                        # today (no trades of its own)
    assert c.get("/api/v4/story?day=2020-01-01").status_code == 400
    assert c.get("/api/v4/story?day=bad").status_code == 400
    s = c.get("/api/v4/since?after=0")
    assert s.status_code == 200 and s.json()["clamped"] is True and len(s.content) < 150_000
    j = s.json()
    assert j["clamped_by"] == ("start" if j["after"] == j["start"] else "week")   # the run start or 7 days back
    assert len(app.state.more["since"]["cache"]) == 1
    assert c.get("/api/v4/since?after=0").json() == s.json()


def test_story_is_fast_on_a_month_of_trades(tmp_path):
    """331 accounts x 30 days at about 700 trades a day: the day's story and a week of 'since' stay well under 300 ms."""
    db = str(tmp_path / "big.db")
    st = Store3(db)
    now = T0 + 15 * HOUR
    start = now - 30 * DAY
    ids = [f"S{i}@15m" for i in range(144)] + [f"F3_X{i}@15m" for i in range(171)] + ["REEL_H1@5m"] + \
          [f"RANDOM_{k}@{tf}" for k in (1, 2, 3) for tf in ("5m", "15m", "30m", "1h", "4h")]
    kinds = ["strategy"] * 144 + ["ds200"] * 171 + ["reel"] + ["random"] * 15
    for aid, k in zip(ids, kinds):
        st.add_account(aid, aid.split("@")[0], aid.split("@")[1], k, start, "paper-v4", None, {"family": "F3"} if k == "ds200" else {})
    import random
    rnd = random.Random(3)
    rows = []
    for j in range(21_000):
        aid = ids[rnd.randrange(len(ids))]
        t = start + int((j + 1) * 30 * DAY / 21_000)
        p = rnd.gauss(0, 20)
        rows.append((aid, "BTCUSDT", t - HOUR, t, "SL" if p < 0 else "LOCK", 20, p, p / 100, 5000 + p, "{}"))
    st.conn.executemany("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                        "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    st.put_state("accounts", now, {"engines": {aid: {"wallet": 5000.0, "bust": False} for aid in ids}})
    st.commit()
    st.conn.close()
    c = sqlite3.connect(_ro_uri(db), uri=True)
    S.story(c, None, DAY0, now)                                              # warm the imports
    t = time.perf_counter()
    d = S.story(c, None, DAY0, now)
    took = time.perf_counter() - t
    assert d["trades"]["total"] > 400 and took < 0.3, took
    t = time.perf_counter()
    s = N.since(c, None, now - 7 * DAY, now)
    assert s["trades"]["total"] > 4000 and time.perf_counter() - t < 0.3
    assert len(json.dumps(d)) < 150_000 and len(json.dumps(s)) < 20_000


# ---------------------------------------------------------------- the page side
def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


def test_since_sheet_is_wired_once_never_on_the_first_visit_and_keeps_storage_wrapped():
    main, since = _read("core", "main.js"), _read("core", "since.js")
    assert 'import {startSince} from "./since.js";' in main and main.count("startSince()") == 1
    assert "localStorage" not in since and "local.get(KEY" in since and "local.set(KEY" in since
    assert "prev != null && serverNow() - prev >= GAP_MS" in since          # the first visit only records the time
    assert '"/static/v4/core/since.css"' in since and os.path.exists(os.path.join(V4, "core", "since.css"))
    assert "/api/v4/since?after=" in since and "ASSUME_KO" in since
    assert "innerHTML" not in since


def test_story_pages_carry_the_captions_and_the_reference_note():
    story, pages, kit = _read("screens", "story.js"), _read("screens", "story-pages.js"), _read("screens", "story-kit.js")
    assert "ui.assume()" in story                                            # the money caption in the frame's footer
    assert pages.count("ui.refNote(") >= 3                                   # summary, reel, DeepSeek
    assert "하루 성적은 운이 큽니다" in pages
    assert "export function storyRing(ctx)" in kit
    assert "motion.reduced()" in story and "animationend" in story           # no auto-advance under reduced motion
    for src in (story, pages, kit):
        assert "innerHTML" not in src and "localStorage" not in src
    css = _read("screens", "story.css") + _read("screens", "story-kit.css") + _read("core", "since.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", css, flags=re.S))


def test_the_page_and_the_server_count_the_same_days():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    kit = "file://" + os.path.join(V4, "screens", "story-kit.js")
    script = (f"const k = await import('{kit}');\n"
              f"console.log(JSON.stringify(k.runDays({START}, {NOW}).reverse()));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == S.run_days(START, NOW)
