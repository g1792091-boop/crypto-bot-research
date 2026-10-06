"""The debate room's hypotheses: the fixed menu, validation of the model's claim, and grading by code on synthetic
paper3.db / daily3.db fixtures (read-only; the debate database is the only thing written)."""
import json
import sqlite3

import pytest

from paperbot import daily3
from paperbot.agents import debate as D
from paperbot.agents import debate_grade as G
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

DAY = 86_400_000
NOW = 1_791_158_400_000 + 10 * DAY
START = NOW - 10 * DAY


def trade(st, aid, pnl, lev=20, tier="normal", margin=100.0, t=0):
    s, tf = aid.split("@")
    st.trade(aid, TradeRecord(
        strategy_id=s, symbol="BTCUSDT", timeframe=tf, side=1, signal_ts=NOW + t - 1, entry_time=NOW + t - 1,
        entry_price=100.0, exit_time=NOW + t, exit_price=100.0, exit_reason="LOCK" if pnl > 0 else "SL", qty=1.0,
        leverage=lev, tier=tier, margin=margin, stop_price=99.0, tp_price=0.0, liq_price=90.0, fees=0.1, funding=0.0,
        pnl=pnl, roe=pnl / margin, price_move=0.0, mae_price=99.5, mfe_price=100.5, equity_after=5000.0 + pnl,
        score=0.0, context={}))


@pytest.fixture
def world(tmp_path):
    paper, daily = str(tmp_path / "paper3.db"), str(tmp_path / "daily3.db")
    st = Store3(paper)
    for a in ("S1@15m", "S1@1h", "S2@15m"):
        st.add_account(a, a.split("@")[0], a.split("@")[1], "strategy", START, "paper-v3")
    st.add_account("RANDOM_1@15m", "RANDOM_1", "15m", "random", START, "paper-v3")
    st.put_state("run", START, {"initial_equity": 5000.0})
    st.put_state("accounts", NOW, {"engines": {"S1@15m": {"wallet": 5000.0, "bust": False},
                                               "S1@1h": {"wallet": 5.0, "bust": True},
                                               "S2@15m": {"wallet": 5000.0}}})
    trade(st, "S1@15m", 1.0, t=-5)                                       # an old trade: before the claim
    st.commit()
    d = sqlite3.connect(daily)
    d.executescript(daily3.SCHEMA)
    d.execute("INSERT INTO reports (day, ts, data) VALUES ('2026-10-14', 1, ?)",
              (json.dumps({"parity": {"accounts": 156, "mismatched_accounts": 0}}),))
    d.commit()
    d.close()

    class W:
        pass
    w = W()
    w.st, w.paper, w.daily = st, paper, daily
    w.ro = lambda: sqlite3.connect(f"file:{paper}?mode=ro", uri=True)
    w.dro = lambda: sqlite3.connect(f"file:{daily}?mode=ro", uri=True)
    return w


def claim(w, kind, params, now=NOW):
    p, d = w.ro(), w.dro()
    try:
        return G.validate({"kind": kind, "params": params}, p, d, now)
    finally:
        p.close()
        d.close()


def graded(w, c, now=NOW + DAY):
    p, d = w.ro(), w.dro()
    try:
        return G.grade(c["kind"], c["params"], NOW, p, d, now)
    finally:
        p.close()
        d.close()


# ---------------------------------------------------------------- validation: only the menu, only in range
def test_validation_keeps_the_menu_and_drops_everything_else(world):
    ok, why, horizon = claim(world, "strategy_roe_sign", {"strategy": "S1", "tf": "15m", "op": "<", "n": 5})
    assert ok and why == "" and ok["params"]["account"] == "S1@15m" and "S1@15m" in horizon and ok["params"]["base_id"] == 1
    bad = [
        ("martingale", {"n": 5}, "메뉴에 없는 종류"),
        ("strategy_roe_sign", {"strategy": "S1", "tf": "5m", "op": "<", "n": 10}, "범위 밖"),     # 5m was removed
        ("strategy_roe_sign", {"strategy": "S1", "tf": "15m", "op": "==", "n": 10}, "범위 밖"),
        ("strategy_roe_sign", {"strategy": "S1", "tf": "15m", "op": "<", "n": 4}, "범위 밖"),
        ("strategy_roe_sign", {"strategy": "S1", "tf": "15m", "op": "<", "n": 51}, "범위 밖"),
        ("strategy_roe_sign", {"strategy": "S1;DROP", "tf": "15m", "op": "<", "n": 10}, "범위 밖"),
        ("strategy_roe_sign", {"strategy": "S9", "tf": "15m", "op": "<", "n": 10}, "그런 전략 계좌가 없음"),
        ("strategy_roe_sign", {"strategy": "RANDOM_1", "tf": "15m", "op": "<", "n": 10}, "그런 전략 계좌가 없음"),
        ("best_vs_normal", {"n": 10}, "범위 밖"),
        ("best_vs_normal", {"n": True}, "범위 밖"),
        ("parity_streak", {"days": 0}, "범위 밖"),
        ("parity_streak", {"days": 15}, "범위 밖"),
        ("busts_by_day", {"day": 5, "max_busts": 1}, "이미 지났음"),                                # run is D+10
        ("busts_by_day", {"day": 61, "max_busts": 1}, "범위 밖"),
        ("busts_by_day", {"day": 20, "max_busts": -1}, "범위 밖"),
    ]
    for kind, params, expect in bad:
        c, why, _ = claim(world, kind, params)
        assert c is None and expect in why, (kind, params, why)
    assert G.validate("not a dict", None, None, NOW)[0] is None
    assert G.validate({"kind": "best_vs_normal", "params": "x"}, None, None, NOW)[0] is None
    assert "읽을 수 없어" in G.validate({"kind": "best_vs_normal", "params": {"n": 100}}, None, None, NOW)[1]


# ---------------------------------------------------------------- grading of each kind
def test_strategy_roe_sign_waits_for_n_trades_then_grades(world):
    c, *_ = claim(world, "strategy_roe_sign", {"strategy": "S1", "tf": "15m", "op": "<", "n": 5})
    for i in range(4):
        trade(world.st, "S1@15m", -2.0, t=i)
    world.st.commit()
    assert graded(world, c) is None                                      # 4 of 5 closed: not yet
    trade(world.st, "S1@15m", -2.0, t=9)
    trade(world.st, "S1@15m", 500.0, t=10)                               # the 6th is after the window
    world.st.commit()
    r = graded(world, c)
    assert r["status"] == "graded" and r["outcome"] == "hit" and r["detail"]["mean_roe"] < 0
    c2, *_ = claim(world, "strategy_roe_sign", {"strategy": "S1", "tf": "15m", "op": ">", "n": 5})
    # c2's baseline already holds the 6 trades: it waits for 5 new ones
    assert graded(world, c2) is None
    for i in range(5):
        trade(world.st, "S1@15m", -3.0, t=20 + i)
    world.st.commit()
    r2 = graded(world, c2)
    assert r2["outcome"] == "miss" and r2["detail"]["mean_roe"] < 0


def test_best_vs_normal_compares_return_per_exposure(world):
    c, *_ = claim(world, "best_vs_normal", {"n": 50})
    for i in range(25):
        trade(world.st, "S1@15m", 5.0, lev=50, tier="best", margin=100.0, t=i)      # r = 5 / 5000 = 0.001
        trade(world.st, "S2@15m", 1.0, lev=30, tier="normal", margin=100.0, t=i)    # r = 1 / 3000
    world.st.commit()
    r = graded(world, c)
    assert r["outcome"] == "hit" and r["detail"]["best"] == 25 and r["detail"]["normal"] == 25
    # the coin-flip account is not a strategy account: its trades are not in the window
    c2, *_ = claim(world, "best_vs_normal", {"n": 50})
    for i in range(25):
        trade(world.st, "S1@15m", -5.0, lev=50, tier="best", t=100 + i)
        trade(world.st, "S2@15m", 1.0, lev=30, tier="normal", t=100 + i)
        trade(world.st, "RANDOM_1@15m", 9.0, lev=50, tier="best", t=100 + i)
    world.st.commit()
    assert graded(world, c2)["outcome"] == "miss"


def test_best_vs_normal_is_void_when_a_tier_is_thin_or_the_db_restarted(world):
    c, *_ = claim(world, "best_vs_normal", {"n": 50})
    for i in range(50):
        trade(world.st, "S1@15m", 1.0, tier="best" if i < 3 else "normal", t=i)
    world.st.commit()
    r = graded(world, c)
    assert r["status"] == "void" and "5건 미만" in r["outcome"]
    c["params"]["base_id"] = 10_000                                      # the database was replaced (ids went back)
    assert graded(world, c)["status"] == "void"


def test_parity_streak_hits_misses_and_ignores_nights_without_a_check(world):
    c, *_ = claim(world, "parity_streak", {"days": 3})
    assert c["params"]["base_day"] == "2026-10-14"                      # the newest report at the time of the claim
    def report(day, par):
        d = sqlite3.connect(world.daily)
        d.execute("INSERT INTO reports (day, ts, data) VALUES (?,?,?)", (day, 1, json.dumps({"parity": par})))
        d.commit()
        d.close()
    ok = {"accounts": 156, "mismatched_accounts": 0}
    report("2026-10-15", ok)
    report("2026-10-16", "no 00:00 snapshot for this day (runner not running then)")   # counts neither way
    report("2026-10-17", ok)
    assert graded(world, c) is None
    report("2026-10-18", ok)
    r = graded(world, c)
    assert r["outcome"] == "hit" and r["detail"]["nights"] == 3
    c2, *_ = claim(world, "parity_streak", {"days": 3, "accounts": 156})
    c2["params"]["base_day"] = "2026-10-14"
    report("2026-10-19", {"accounts": 156, "mismatched_accounts": 2})
    c3 = {"kind": "parity_streak", "params": {"days": 3, "base_day": "2026-10-18"}}
    assert graded(world, c3)["outcome"] == "miss"                       # the first bad night decides at once
    c4 = {"kind": "parity_streak", "params": {"days": 1, "accounts": 157, "base_day": "2026-10-14"}}
    assert graded(world, c4)["outcome"] == "miss" and graded(world, c4)["detail"]["want"] == 157


def test_busts_by_day_is_graded_when_the_day_is_reached(world):
    c, *_ = claim(world, "busts_by_day", {"day": 12, "max_busts": 1})
    p, d = world.ro(), world.dro()
    try:
        assert G.grade(c["kind"], c["params"], NOW, p, d, START + 11 * DAY) is None           # D+11: not yet
        r = G.grade(c["kind"], c["params"], NOW, p, d, START + 12 * DAY)
        assert r["outcome"] == "hit" and r["detail"]["busts"] == 1                           # S1@1h is bust: 1 <= 1
        c0 = {"kind": "busts_by_day", "params": {**c["params"], "max_busts": 0}}
        assert G.grade(c0["kind"], c0["params"], NOW, p, d, START + 13 * DAY)["outcome"] == "miss"
    finally:
        p.close()
        d.close()


def test_a_claim_that_never_reaches_its_horizon_expires(world):
    c, *_ = claim(world, "strategy_roe_sign", {"strategy": "S1", "tf": "15m", "op": "<", "n": 50})
    assert graded(world, c, NOW + 20 * DAY) is None
    assert graded(world, c, NOW + 22 * DAY)["status"] == "expired"
    assert G.grade("busts_by_day", {"day": 30, "max_busts": 1, "start_ts": START}, NOW, None, None, NOW + 99 * DAY) is None


def test_grade_open_writes_only_the_debate_db_and_the_scoreboard_is_a_small_sample(world, tmp_path):
    db = D.DB(str(tmp_path / "debate" / "debate.db"))
    c, *_ = claim(world, "best_vs_normal", {"n": 50})
    for sp, outcome in (("퀀트", "hit"), ("퀀트", "miss"), ("비관론자", "hit")):
        db.conn.execute("INSERT INTO debate_hypotheses (round_id, ts, speaker, kind, params_json, status, outcome) "
                        "VALUES (1, 1, ?, 'x', '{}', 'graded', ?)", (sp, outcome))
    db.conn.execute("INSERT INTO debate_hypotheses (round_id, ts, speaker, kind, params_json, status) VALUES "
                    "(1, ?, '퀀트', 'best_vs_normal', ?, 'open')", (NOW, json.dumps(c)))
    db.conn.execute("INSERT INTO debate_hypotheses (round_id, ts, speaker, kind, params_json, status) VALUES "
                    "(1, ?, '퀀트', 'best_vs_normal', 'not json', 'open')", (NOW,))
    db.conn.commit()
    for i in range(50):
        trade(world.st, "S1@15m", 1.0, tier="best" if i % 2 else "normal", t=i)
    world.st.commit()
    before = open(world.paper, "rb").read()
    p, d = world.ro(), world.dro()
    n = G.grade_open(db.conn, p, d, NOW + DAY)
    p.close()
    d.close()
    assert n == 2 and open(world.paper, "rb").read() == before            # the bot's file is untouched
    rows = {r[0]: r[1:] for r in db.conn.execute("SELECT id, status, outcome FROM debate_hypotheses WHERE id > 3")}
    assert rows[4][0] in ("graded",) and rows[5][0] == "void"
    sb = G.scoreboard(db.conn)
    assert sb["speakers"]["비관론자"] == {"graded": 1, "hit": 1, "rate": 1.0, "small": True}
    assert sb["small"] is True and sb["graded"] >= 4 and sb["by_status"]["void"] == 1
    assert G.claim_ko("busts_by_day", json.dumps({"params": {"day": 20, "max_busts": 2}})) == "D+20에 파산한 전략 계좌가 2개 이하다"
    assert G.status_ko("graded", "hit {...}") == "맞음" and G.status_ko("dropped", "x") == "메뉴에 맞지 않아 버림"


def test_the_factory_scoreboard_puts_each_side_next_to_the_lab_base_rates(tmp_path):
    """The idea factory's sides (debate.db only): settled ideas by side, the check 반대 named, and what the lab's usual
    rates alone would give (debate_state 'factory:base_rates'); absent before the factory's table exists."""
    path = str(tmp_path / "debate.db")
    c = sqlite3.connect(path)
    c.executescript(D.SCHEMA)
    assert G.factory_record(c) is None and "factory" not in G.scoreboard(c)
    c.close()
    db = D.DB(path)
    base = {"newlab": {"tests": 100, "passed": 1, "pass_rate": 0.01, "fail_share": {"⑥": 0.6, "①": 0.9}},
            "labtest": {"tests": 10, "passed": 0, "pass_rate": 0.0, "fail_share": {"①": 0.5}}}
    db.put("factory:base_rates", base)
    for i, (engine, side, cc, hit) in enumerate([("newlab", "반대", "⑥", 1), ("newlab", "반대", "①", 0),
                                                  ("labtest", "반대", "①", 1), ("newlab", "찬성", "⑥", 0)]):
        db.conn.execute("INSERT INTO debate_lab_ideas (round_id, ts, engine, check_status, queue_status, lab_status, "
                        "settled_side, con_check, con_check_hit) VALUES (?, ?, ?, 'ok', 'queued', 'tested', ?, ?, ?)",
                        (i, NOW, engine, side, cc, hit))
    db.conn.execute("INSERT INTO debate_lab_ideas (round_id, ts, engine, check_status, queue_status) "
                    "VALUES (9, ?, 'newlab', 'ok', 'candidate')", (NOW,))
    db.conn.commit()
    rec = G.scoreboard(db.conn)["factory"]
    assert (rec["tested"], rec["settled"], rec["찬성_right"], rec["반대_right"]) == (4, 4, 1, 3)
    assert rec["찬성_expected"] == 0.03 and rec["반대_expected"] == 3.97          # 0.01 x 3 newlab + 0 x 1 labtest
    assert (rec["con_check_hits"], rec["con_check_graded"], rec["con_check_expected"]) == (2, 4, 2.6)
    assert rec["small"] and rec["base_rates_known"] and "사람 성적이 아님" in rec["note"]
    db.close()
