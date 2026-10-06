"""Disputes (paperbot/agents/disputes.py): the ledger, the seats, the settle check, the pre-registered lab claim rule,
the forward checks on a fake paper3, duplicates, the board, and the adapter to the shared test queue (labintake, written
on another branch: both with and without it)."""

import json
import sqlite3
import sys
import types

import pytest

from paperbot.agents import actions as A
from paperbot.agents import disputes as DS
from paperbot.agents import labtests as L
from paperbot.agents import rooms_db as R
from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.store3 import Store3
from test_cards import trade

S = "N17_KC_RSI"
ROOM = f"strat:{S}"
DAY = 86_400_000
T0 = 1_800_000_000_000
REAL_LABINTAKE = DS._labintake                                   # before any test patches it
LAB = {"kind": "lab", "test": {"template": "skip_tag", "timeframe": "1h", "tag": "추세 반대 진입"}}   # as a model writes it
LABC = {"kind": "lab", "test": {**LAB["test"], "strategy": S}}                                       # as clean_settle gives it


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(DS, "_labintake", lambda: None)          # the queue is not installed (default case)
    c = R.open_agents(str(tmp_path / "agents3.db"))
    R.ensure_rooms(c, ts=T0)
    DS.ensure(c)
    return c


class Paper:
    """A fake paper3.db (Store3 schema) with the 36's and the coin flips' accounts."""

    def __init__(self, tmp_path, start=T0 - 20 * DAY, name="paper3.db"):
        self.path = str(tmp_path / name)
        self.store = Store3(self.path)
        for tf in ("15m", "30m", "1h", "4h"):
            self.store.add_account(f"{S}@{tf}", S, tf, "strategy", start, "paper-v3")
            for k in (1, 2, 3):
                self.store.add_account(f"RANDOM_{k}@{tf}", f"RANDOM_{k}", tf, "random", start, "paper-v3")
        self.store.commit()

    def add(self, aid, entry, roe, context=None, n=1, step=60_000):
        for k in range(n):
            e = entry + k * step
            t = trade(strategy_id=aid.split("@")[0], timeframe=aid.split("@")[1], entry_time=e, exit_time=e + 30_000,
                      signal_ts=e - 1, roe=roe, pnl=roe * 100, exit_reason="LOCK" if roe > 0 else "SL",
                      context=context if context is not None else {"regime": "trend_down"})
            self.store.conn.execute(
                "INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (aid, "BTCUSDT", t["entry_time"], t["exit_time"], t["exit_reason"], 40, t["pnl"], t["roe"], 5000.0,
                 json.dumps(t)))
        self.store.commit()

    def ro(self):
        return R.open_ro(self.path)


UP = {"regime": "trend_up", "htf_regime": "trend_up", "adx": 30.0, "di_plus": 30.0, "di_minus": 10.0}   # long: no tag
DOWN = {"regime": "trend_down"}                                                               # long: 추세 반대 진입


def _lab_trial(conn, test, status, periods, gate_pass=False, n=3, ts=T0 + 1000, template=None):
    spec = {**test, "strategy": S}
    tid = R.add_trial(conn, ROOM, S, "test", spec, None, ts=ts)
    result = {"ok": status in ("passed", "failed"), "template": template or test["template"], "periods": periods}
    R.add_trial_result(conn, tid, status, {"result": result, "gate": {"pass": gate_pass, "n_trials": n}, "n_trials": n},
                       ts=ts + 1)
    return tid


def _period(diff, p, nv=500, nb=500, avail=True, **kw):
    return {"available": avail, "baseline": {"trades": nb, "mean_roe": -0.01}, "variant": {"trades": nv, "mean_roe": 0.001},
            "diff": diff, "p": p, **kw}


def _open(conn, settle, now=T0, side_a="exit_timing", side_b=f"spec_{S}", **kw):
    return DS.open_dispute(conn, room_id=ROOM, round_id=7, strategy=S, source="strategy_room", claim_ko="추세 반대 진입이 손해",
                           side_a=side_a, side_b=side_b, settle=settle, now_ms=now, **kw)


# ------------------------------------------------------------------ ledger rules
def test_the_triggers_keep_sides_claim_and_test_fixed_and_a_final_status_final(conn):
    o = _open(conn, LABC)
    assert o["status"] == "queued"
    for col, v in (("side_a", "whatif"), ("side_b", "x"), ("claim_ko", "다른 주장"), ("spec", "{}"), ("kind", "forward"),
                   ("strategy", "S1_EMA_RSI_CHOP"), ("ts", 1), ("room_id", "team:lead"), ("spec_hash", "x")):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE disputes SET {col} = ? WHERE id = ?", (v, o["id"]))
    conn.rollback()
    assert DS._update(conn, o["id"], status="settled", winner="b", outcome="편 맞음", settled_ts=T0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE disputes SET winner = 'a' WHERE id = ?", (o["id"],))
    conn.rollback()
    assert DS._update(conn, o["id"], winner="a") is False                    # the helper never touches a final row
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM disputes")
    conn.rollback()
    assert DS.get(conn, o["id"])["winner"] == "b"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO disputes (ts, room_id, strategy, source, claim_ko, side_a, side_b, kind, spec, spec_hash, "
                     "status) VALUES (1, 'r', 's', 'strategy_room', 'c', 'a', 'b', 'lab', '{}', 'h', 'won')")
    DS.ensure(conn)                                                         # idempotent


def test_the_seats_are_dealt_once_deterministically_and_rows_keep_their_roles(conn):
    names = list(STRATEGY_KO)
    for i, s in enumerate(names):
        assert DS.attacker_of(s) == DS.ATTACKER_POOL[i % 4] and DS.advocate_of(s) == f"spec_{s}"
    assert {DS.attacker_of(s) for s in names} == set(DS.ATTACKER_POOL)
    assert sum(DS.attacker_of(s) == "whatif" for s in names) == 9                  # each attacker covers 9 strategies
    assert set(DS.ATTACKER_POOL) <= set(R.STRATEGY_ROOM_ROLES)                    # all strategy-room roles
    assert R.get_cursor(conn, DS.SIDES_CURSOR) is None
    v = DS.sides(conn, T0)
    assert v["version"] == 1 and v["since"] == T0 and DS.sides(conn, T0 + DAY)["since"] == T0     # written once
    att = DS.attacker_of(S, conn)
    o = _open(conn, LABC, side_a=att)
    v2 = DS.redeal(conn, T0 + 30 * DAY)                                            # a checkpoint re-deal
    assert v2["version"] == 2 and DS.attacker_of(S, conn) != att
    assert all(DS.attacker_of(s, conn) != DS.attacker_of(s) for s in names)
    assert DS.get(conn, o["id"])["side_a"] == att                                 # the stored dispute keeps its seat


# ------------------------------------------------------------------ the settle
def test_clean_settle_accepts_the_two_forms_and_refuses_5m_descriptive_and_non_36(conn, tmp_path):
    good, why = DS.clean_settle(LAB, S)
    assert why == "" and good == {"kind": "lab", "test": {"template": "skip_tag", "strategy": S, "timeframe": "1h",
                                                         "tag": "추세 반대 진입"}}
    v, _ = DS.clean_settle({"kind": "lab", "test": {"template": "stop_atr", "timeframe": "4h", "value": 2.5}}, S)
    assert v["test"]["k"] == 2.5 and "value" not in v["test"]                        # the prompt's 'value' form
    for bad in ({"kind": "lab", "test": {"template": "skip_tag", "timeframe": "5m", "tag": "추세 반대 진입"}},
                {"kind": "lab", "test": {"template": "timeframe_only"}},
                {"kind": "lab", "test": {"template": "timeframe_only", "timeframe": "1h"}},
                {"kind": "lab", "test": {"template": "stop_atr", "timeframe": "1h", "k": 2.0}},
                {"kind": "lab", "test": {"template": "skip_tag", "timeframe": "1h", "tag": "강제청산"}},
                {"kind": "lab", "test": {**LAB["test"], "strategy": "S1_EMA_RSI_CHOP"}},
                {"kind": "forward", "check": "tag_gap", "tag": "추세 반대 진입", "timeframe": "5m"},
                {"kind": "forward", "check": "win_rate"}, {"kind": "debate"}, None, "lab"):
        got, why = DS.clean_settle(bad, S)
        assert got is None and why, bad
    from paperbot.config import DS200_FAMILY, REEL_NAME
    for name in (next(iter(DS200_FAMILY)), REEL_NAME, "RANDOM_1", "NOPE"):
        got, why = DS.clean_settle(LAB, name)
        assert got is None and "36" in why
    fwd = {"all": {"ok": True, "n": 33}, "1h": {"ok": False, "why": "거래가 드물어"}}
    got, _ = DS.clean_settle({"kind": "forward", "check": "tag_gap", "tag": "추세 반대 진입", "timeframe": None}, S,
                             forward=fwd)
    assert got == {"kind": "forward", "check": "tag_gap", "timeframe": None, "tag": "추세 반대 진입", "n": 33}
    got, why = DS.clean_settle({"kind": "forward", "check": "vs_flip", "timeframe": "1h"}, S, forward=fwd)
    assert got is None and "드물어" in why
    got, why = DS.clean_settle({"kind": "forward", "check": "tag_gap", "tag": "없는 특징"}, S, forward=fwd)
    assert got is None and "tag" in why


def test_forward_n_follows_the_strategys_trades_per_day_and_rare_strategies_get_lab_only(tmp_path):
    p = Paper(tmp_path, start=T0 - 30 * DAY)
    paper = p.ro()
    info = DS.forward_info(paper, S, "1h", T0)
    assert info["ok"] is False and "5년 시험으로만" in info["why"]                 # no trades at all
    p.add(f"{S}@1h", T0 - 13 * DAY, 0.1, n=14, step=DAY // 2)                     # 14 trades in 14 days: 1 a day
    info = DS.forward_info(p.ro(), S, "1h", T0)
    assert info["per_day"] == pytest.approx(1.0) and info["n"] == 20 and info["ok"]          # 14 -> clamped to 20
    p.add(f"{S}@15m", T0 - 10 * DAY, 0.1, n=140, step=DAY // 20)
    info = DS.forward_info(p.ro(), S, None, T0)
    assert info["n"] == 60                                                         # 11 a day x 14 -> clamped to 60
    young = Paper(tmp_path, start=T0 - 2 * DAY, name="young.db")
    young.add(f"{S}@4h", T0 - DAY, 0.1, n=2)
    assert DS.forward_info(young.ro(), S, "4h", T0)["per_day"] == pytest.approx(1.0)       # the run is 2 days old
    assert set(DS.forward_table(paper, S, T0)) == {"all", "15m", "30m", "1h", "4h"}


# ------------------------------------------------------------------ the lab claim rule
def test_the_lab_claim_rule_attacker_and_advocate_wins_void_and_the_copy_gate_quoted_apart(conn):
    t = LAB["test"]
    win = _lab_trial(conn, t, "failed", {"1": _period(0.004, 0.01), "2": _period(0.002, 0.03, nv=150),
                                          "3": _period(0.001, 0.5, nb=40)}, gate_pass=False, n=5)
    v = DS.lab_verdict(R.get_trial(conn, win))
    assert v["status"] == "settled" and v["winner"] == "a"                     # the claim rule is not the copy gate
    assert "공격하는 직원 맞음" in v["line_ko"] and "복제 관문: 불통과(이 방 시험 5번째, 기준 p<0.01)" in v["line_ko"]
    for periods, why in (({"1": _period(0.004, 0.06), "2": _period(0.002, 0.01)}, "p1 not < 0.05"),
                         ({"1": _period(0.004, 0.01), "2": _period(-0.001, 0.01)}, "p2 worse"),
                         ({"1": _period(0.004, 0.01), "2": _period(0.002, 0.01, nv=99)}, "p2 < 100 trades"),
                         ({"1": _period(0.004, 0.01), "2": _period(0.002, 0.01), "3": _period(-0.001, 0.9, nb=30)},
                          "p3 worse with 30 baseline trades")):
        tid = _lab_trial(conn, {**t, "timeframe": "4h"}, "failed", periods)
        v = DS.lab_verdict(R.get_trial(conn, tid))
        assert (v["status"], v["winner"]) == ("settled", "b"), why
        assert v["line_ko"].startswith("편드는 직원 맞음")
    # period 3 with too few baseline trades is left out
    tid = _lab_trial(conn, {**t, "timeframe": "15m"}, "passed",
                     {"1": _period(0.004, 0.01), "2": _period(0.002, 0.01), "3": _period(-0.5, 0.9, nb=29)}, True, 1)
    v = DS.lab_verdict(R.get_trial(conn, tid))
    assert v["winner"] == "a" and "복제 관문: 통과" in v["line_ko"] and "두 분 확인" in v["line_ko"]
    for st in ("no_data", "error"):
        tid = _lab_trial(conn, {**t, "timeframe": "30m"}, st, {})
        assert DS.lab_verdict(R.get_trial(conn, tid))["status"] == "void"


def test_stop_atr_needs_the_leverage_free_return_too(conn):
    t = {"template": "stop_atr", "timeframe": "1h", "k": 2.5}
    base = {"1": _period(0.004, 0.01), "2": _period(0.002, 0.01)}
    no = _lab_trial(conn, t, "failed", {k: {**v, "diff_notional": -0.0001} for k, v in base.items()})
    assert DS.lab_verdict(R.get_trial(conn, no))["winner"] == "b"
    yes = _lab_trial(conn, {**t, "timeframe": "4h"}, "failed", {k: {**v, "diff_notional": 0.0001} for k, v in base.items()})
    assert DS.lab_verdict(R.get_trial(conn, yes))["winner"] == "a"


# ------------------------------------------------------------------ forward checks on a fake paper3
def _fwd(conn, paper, check, n=20, tag="추세 반대 진입", tf="1h", now=T0):
    settle, why = DS.clean_settle({"kind": "forward", "check": check, "tag": tag, "timeframe": tf}, S,
                                  forward={tf or "all": {"ok": True, "n": n}})
    assert settle, why
    return _open(conn, settle, now=now, paper_ro=paper)


def test_tag_gap_hit_miss_void_and_the_coin_flip_mirror(conn, tmp_path):
    p = Paper(tmp_path)
    hit = _fwd(conn, p.ro(), "tag_gap")
    assert hit["status"] == "open" and DS.get(conn, hit["id"])["data"]["base_trade_id"] == 0
    p.add(f"{S}@1h", T0 - DAY, -0.5, DOWN, n=5)                                  # entered BEFORE: never counted
    p.add(f"{S}@1h", T0 + 60_000, -0.2, DOWN, n=8)                               # tagged losers
    assert DS.grade_due(conn, p.ro(), T0 + DAY) == []                            # 8 < 20: waits
    p.add(f"{S}@1h", T0 + DAY, 0.1, UP, n=12)
    p.add("RANDOM_1@1h", T0 + 60_000, -0.1, DOWN, n=3)
    p.add("RANDOM_2@1h", T0 + 60_000, 0.05, UP, n=4)
    [g] = DS.grade_due(conn, p.ro(), T0 + 2 * DAY, 0.0014)
    assert (g["status"], g["winner"]) == ("settled", "a")
    row = DS.get(conn, hit["id"])
    assert row["data"]["numbers"]["with_n"] == 8 and row["data"]["numbers"]["without_n"] == 12
    assert row["data"]["mirror"]["with_n"] == 3 and row["data"]["mirror"]["without_n"] == 4
    assert "동전 거울" in row["outcome"] and "규칙 근거 아님" in row["outcome"]
    msgs = [m["text"] for m in R.room_messages(conn, ROOM, limit=50)]
    assert any(t.startswith(f"⚖️ 다툼 #{hit['id']} 결론: 공격 청산 타점 분석가") for t in msgs)
    # a miss: the tagged trades did better
    miss = _fwd(conn, p.ro(), "tag_gap", tf="4h", now=T0 + 3 * DAY)
    p.add(f"{S}@4h", T0 + 3 * DAY + 60_000, 0.3, DOWN, n=10)
    p.add(f"{S}@4h", T0 + 4 * DAY, -0.1, UP, n=10)
    [g] = DS.grade_due(conn, p.ro(), T0 + 5 * DAY)
    assert g["dispute_id"] == miss["id"] and g["winner"] == "b"
    # void: fewer than 5 trades on one side
    void = _fwd(conn, p.ro(), "tag_gap", tf="15m", now=T0 + 6 * DAY)
    p.add(f"{S}@15m", T0 + 6 * DAY + 60_000, -0.3, DOWN, n=4)
    p.add(f"{S}@15m", T0 + 7 * DAY, 0.1, UP, n=16)
    [g] = DS.grade_due(conn, p.ro(), T0 + 8 * DAY)
    assert g["dispute_id"] == void["id"] and g["status"] == "void" and g["winner"] is None


def test_vs_flip_hit_miss_void_and_expiry(conn, tmp_path):
    p = Paper(tmp_path)
    hit = _fwd(conn, p.ro(), "vs_flip", tf="1h")
    p.add(f"{S}@1h", T0 + 60_000, -0.05, n=20)
    p.add("RANDOM_1@1h", T0 + 60_000, 0.01, n=6)
    p.add("RANDOM_3@1h", T0 + 60_000, -0.01, n=6)
    p.add("RANDOM_2@1h", T0 + 30 * DAY, 0.5, n=6)                                # after the window: not counted
    [g] = DS.grade_due(conn, p.ro(), T0 + DAY)
    assert (g["dispute_id"], g["status"], g["winner"]) == (hit["id"], "settled", "a")          # no edge: attacker
    row = DS.get(conn, hit["id"])
    assert row["data"]["numbers"]["flip_n"] == 12 and row["data"]["mirror"]["one_n"] == 6
    miss = _fwd(conn, p.ro(), "vs_flip", tf="4h", now=T0 + 2 * DAY)
    p.add(f"{S}@4h", T0 + 2 * DAY + 60_000, 0.2, n=20)
    p.add("RANDOM_1@4h", T0 + 2 * DAY + 60_000, -0.1, n=10)
    [g] = DS.grade_due(conn, p.ro(), T0 + 3 * DAY)
    assert (g["dispute_id"], g["winner"]) == (miss["id"], "b")
    void = _fwd(conn, p.ro(), "vs_flip", tf="30m", now=T0 + 4 * DAY)
    p.add(f"{S}@30m", T0 + 4 * DAY + 60_000, 0.2, n=20)
    p.add("RANDOM_1@30m", T0 + 4 * DAY + 60_000, 0.1, n=9)                       # 9 < 20 / 2
    [g] = DS.grade_due(conn, p.ro(), T0 + 5 * DAY)
    assert (g["dispute_id"], g["status"]) == (void["id"], "void")
    late = _fwd(conn, p.ro(), "vs_flip", tf="15m", now=T0 + 6 * DAY)
    p.add(f"{S}@15m", T0 + 6 * DAY + 60_000, 0.2, n=5)
    [g] = DS.grade_due(conn, p.ro(), T0 + 52 * DAY)
    assert (g["dispute_id"], g["status"]) == (late["id"], "expired")
    row = DS.get(conn, late["id"])
    assert row["status"] == "expired" and "기한 지남" in row["outcome"]
    assert DS.list_rows(conn, status="expired")[0]["status_ko"] == "기한 지남"


def test_an_open_forward_dispute_shows_its_progress(conn, tmp_path):
    p = Paper(tmp_path)
    o = _fwd(conn, p.ro(), "vs_flip", n=40, tf=None)
    p.add(f"{S}@1h", T0 + 60_000, 0.1, n=7)
    p.add(f"{S}@15m", T0 + 60_000, 0.1, n=5)
    [row] = DS.list_rows(conn, strategy=S, paper_ro=p.ro())
    assert row["id"] == o["id"] and row["progress"] == 12 and row["progress_ko"] == "앞으로 40건 중 12건"
    assert row["settle_ko"] == "앞으로 거래 40건: 같은 기간 동전 계좌보다 나은지"


# ------------------------------------------------------------------ duplicates, concessions
def test_duplicates_are_shown_never_scored(conn):
    first = _open(conn, LABC)
    again = _open(conn, LABC, now=T0 + DAY)                       # pending: the same claim
    assert again["status"] == "duplicate" and "다툼 #" in again["text_ko"]
    DS._update(conn, first["id"], status="settled", winner="b", outcome="편 맞음", settled_ts=T0 + 2 * DAY)
    third = _open(conn, LABC, now=T0 + 3 * DAY, side_a="whatif")
    assert third["status"] == "duplicate" and DS.get(conn, third["id"])["data"]["dup_of"] == first["id"]
    assert "편드는 쪽 맞음" in third["text_ko"]
    # a test already in the strategy's ledger: its result is shown, the dispute is not scored
    t = {"template": "lock_start", "timeframe": "1h", "first_lock": 0.2}
    tid = _lab_trial(conn, t, "failed", {"1": _period(-0.001, 0.9), "2": _period(-0.001, 0.9)})
    settle, _ = DS.clean_settle({"kind": "lab", "test": t}, S)
    old = _open(conn, settle, now=T0 + 4 * DAY)
    assert old["status"] == "duplicate" and f"시험 #{tid}" in old["text_ko"]
    b = DS.board(conn)
    assert b["base_rates"]["all"]["settled"] == 1 and b["totals"]["duplicate"] == 3
    # a conceded dispute: final, never scored, its lab test still handed to the queue when there is one
    c = _open(conn, {"kind": "lab", "test": {**LAB["test"], "timeframe": "4h", "strategy": S}}, now=T0 + 5 * DAY,
              conceded=True)
    assert c["status"] == "conceded" and DS.get(conn, c["id"])["status"] == "conceded"
    assert DS.role_record(DS.board(conn), f"spec_{S}")["conceded"] == 1


# ------------------------------------------------------------------ the shared test queue adapter
def _fake_labintake(calls):
    m = types.ModuleType("paperbot.agents.labintake")

    def ensure(c):
        c.executescript("""
        CREATE TABLE IF NOT EXISTS lab_intake (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, source TEXT NOT NULL,
            source_ref TEXT NOT NULL, room_id TEXT NOT NULL, engine TEXT NOT NULL, strategy TEXT, spec TEXT NOT NULL,
            spec_hash TEXT NOT NULL, description_ko TEXT NOT NULL, idea_ko TEXT NOT NULL DEFAULT '', meta TEXT,
            UNIQUE (source, source_ref));
        CREATE TABLE IF NOT EXISTS lab_intake_events (id INTEGER PRIMARY KEY AUTOINCREMENT, intake_id INTEGER NOT NULL,
            ts INTEGER NOT NULL, status TEXT NOT NULL, trial_id INTEGER, detail TEXT);""")

    def enqueue(c, source, source_ref, engine, spec, strategy, idea_ko, meta, now, needs_ok=False):
        calls.append({"source": source, "source_ref": source_ref, "engine": engine, "spec": spec, "strategy": strategy,
                      "meta": meta})
        cur = c.execute("INSERT OR IGNORE INTO lab_intake (ts, source, source_ref, room_id, engine, strategy, spec, spec_hash, "
                        "description_ko, idea_ko, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (now, source, source_ref, f"strat:{strategy}", engine, strategy, json.dumps(spec), "h", "d",
                         idea_ko, json.dumps(meta)))
        if cur.rowcount:
            c.execute("INSERT INTO lab_intake_events (intake_id, ts, status) VALUES (?,?,'queued')", (cur.lastrowid, now))
        c.commit()
        return cur.lastrowid if cur.rowcount else None
    m.ensure, m.enqueue = ensure, enqueue
    return m


def test_without_the_queue_a_lab_dispute_waits_and_a_later_tick_hands_it_over(conn, monkeypatch):
    monkeypatch.setitem(sys.modules, "paperbot.agents.labintake", None)        # an import of it fails
    assert REAL_LABINTAKE() is None                                             # the real adapter: ImportError -> None
    o = _open(conn, LABC)
    assert o["status"] == "queued" and o["intake_id"] is None and "아직 설치되지 않음" in o["text_ko"]
    assert DS.grade_due(conn, None, T0 + DAY) == [] and DS.get(conn, o["id"])["status"] == "queued"
    calls: list = []
    monkeypatch.setattr(DS, "_labintake", lambda: _fake_labintake(calls))     # the queue is installed later
    DS.grade_due(conn, None, T0 + 2 * DAY)
    row = DS.get(conn, o["id"])
    assert row["intake_id"] == 1 and row["status"] == "queued"
    assert calls == [{"source": "meeting", "source_ref": f"dispute:{o['id']}", "engine": "labtest",
                      "spec": {"template": "skip_tag", "strategy": S, "timeframe": "1h", "tag": "추세 반대 진입"},
                      "strategy": S, "meta": calls[0]["meta"]}]
    assert calls[0]["meta"]["by_role"] == "exit_timing" and calls[0]["meta"]["dispute_id"] == o["id"]
    DS.grade_due(conn, None, T0 + 3 * DAY)
    assert len(calls) == 1                                                       # handed over once


def test_a_lab_dispute_is_settled_from_the_queues_tested_event(conn, monkeypatch):
    calls: list = []
    monkeypatch.setattr(DS, "_labintake", lambda: _fake_labintake(calls))
    o = DS.open_dispute(conn, room_id="team:review", round_id=3, strategy=S, source="team_lead", claim_ko="잠금이 낮음",
                        side_a="pnl_reviewer", side_b="performance",
                        settle={"kind": "lab", "test": {"template": "lock_start", "timeframe": "1h", "first_lock": 0.3,
                                                        "strategy": S}}, now_ms=T0)
    assert o["intake_id"] == 1 and "회의 뒤 코드가 이 방 장부로" in o["text_ko"]
    conn.execute("INSERT INTO lab_intake_events (intake_id, ts, status) VALUES (1, ?, 'running')", (T0 + 10,))
    conn.commit()
    assert DS.grade_due(conn, None, T0 + 20) == []
    tid = _lab_trial(conn, {"template": "lock_start", "timeframe": "1h", "first_lock": 0.3}, "failed",
                     {"1": _period(0.001, 0.3), "2": _period(0.001, 0.4)}, ts=T0 + 30)
    conn.execute("INSERT INTO lab_intake_events (intake_id, ts, status, trial_id) VALUES (1, ?, 'tested', ?)", (T0 + 40, tid))
    conn.commit()
    [g] = DS.grade_due(conn, None, T0 + 50)
    assert (g["status"], g["winner"], g["trial_id"]) == ("settled", "b", tid)
    for room in (ROOM, "team:review"):                                          # the strategy room and the origin room
        assert any(m["text"].startswith(f"⚖️ 다툼 #{o['id']}") for m in R.room_messages(conn, room, limit=20))
    # a queue that refused the test voids the dispute
    o2 = _open(conn, {"kind": "lab", "test": {**LAB["test"], "timeframe": "15m", "strategy": S}}, now=T0 + 60)
    conn.execute("INSERT INTO lab_intake_events (intake_id, ts, status) VALUES (?, ?, 'refused')", (o2["intake_id"], T0 + 70))
    conn.commit()
    [g] = DS.grade_due(conn, None, T0 + 80)
    assert (g["dispute_id"], g["status"]) == (o2["id"], "void")


def test_the_meetings_own_test_settles_a_dispute_without_the_queue_and_old_handovers_expire(conn):
    o = _open(conn, LABC)
    tid = _lab_trial(conn, LAB["test"], "failed", {"1": _period(0.004, 0.01), "2": _period(0.003, 0.02)}, ts=T0 + 5)
    [g] = DS.grade_due(conn, None, T0 + 10)
    assert (g["dispute_id"], g["winner"], g["trial_id"]) == (o["id"], "a", tid)
    o2 = _open(conn, {"kind": "lab", "test": {**LAB["test"], "timeframe": "4h", "strategy": S}}, now=T0 + 20)
    [g] = DS.grade_due(conn, None, T0 + 20 + (DS.HANDOVER_DAYS + 1) * DAY)
    assert (g["dispute_id"], g["status"]) == (o2["id"], "expired")


@pytest.mark.skipif(REAL_LABINTAKE() is None, reason="paperbot/agents/labintake.py is not merged yet")
def test_the_real_shared_queue_takes_a_dispute(tmp_path):   # pragma: no cover  (runs once the other branch is merged)
    c = R.open_agents(str(tmp_path / "agents3.db"))
    R.ensure_rooms(c, ts=T0)
    DS.ensure(c)
    o = _open(c, LABC)
    assert o["intake_id"] is not None
    r = c.execute("SELECT source, source_ref, engine, strategy FROM lab_intake WHERE id = ?", (o["intake_id"],)).fetchone()
    assert tuple(r) == ("meeting", f"dispute:{o['id']}", "labtest", S)


# ------------------------------------------------------------------ the team lead's dispute
def test_a_lead_dispute_needs_two_speakers_and_a_recorded_disagree(conn):
    raw = {"strategy": S, "side_a": "pnl_reviewer", "side_b": "performance", "claim": "이 매매법은 동전보다 낫지 않음",
           "settle": LAB}
    spoke = {"team:performance": {"role": "performance", "headline": "좋음"},
             "team:pnl_reviewer": {"role": "pnl_reviewer", "responds_to": {"role": "performance", "stance": "agree"}}}
    got = DS.open_from_lead(conn, raw, spoke, room_id="team:review", round_id=2, now_ms=T0)
    assert got["ok"] is False and "반대" in got["why_ko"]
    spoke["team:pnl_reviewer"]["responds_to"]["stance"] = "disagree"
    for bad, why in (({**raw, "side_b": "risk_officer"}, "말하지"), ({**raw, "strategy": "RANDOM_1"}, "36"),
                     ({**raw, "settle": {"kind": "lab", "test": {"template": "timeframe_only"}}}, "설명용"),
                     ({**raw, "side_b": "pnl_reviewer"}, "말하지"), ("x", "없음")):
        got = DS.open_from_lead(conn, bad, spoke, room_id="team:review", round_id=2, now_ms=T0)
        assert got["ok"] is False and why in got["why_ko"], bad
    got = DS.open_from_lead(conn, raw, spoke, room_id="team:review", round_id=2, now_ms=T0)
    assert got["ok"] is True and got["status"] == "queued"
    row = DS.get(conn, got["id"])
    assert (row["source"], row["side_a"], row["side_b"], row["room_id"]) == ("team_lead", "pnl_reviewer", "performance",
                                                                              "team:review")


# ------------------------------------------------------------------ the board
def _settled(conn, kind, winner, a="exit_timing", b=f"spec_{S}", k=[0]):
    k[0] += 1
    settle = ({"kind": "lab", "test": {"template": "stop_atr", "timeframe": "1h", "k": 1.5, "strategy": S}}
              if kind == "lab" else {"kind": "forward", "check": "vs_flip", "timeframe": "1h", "n": 20 + k[0]})
    conn.execute("INSERT INTO disputes (ts, room_id, strategy, source, claim_ko, side_a, side_b, kind, spec, spec_hash, "
                 "status, winner, outcome, settled_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (T0, ROOM, S, "strategy_room", "c", a, b, kind, json.dumps(settle), f"h{k[0]}",
                  "settled" if winner else "open", winner, "o", T0 if winner else None))
    conn.commit()


def test_board_math_base_rates_expected_wins_and_the_small_sample_flag(conn):
    for w in ("b", "b", "b", "a"):
        _settled(conn, "lab", w)
    for w in ("a", "b"):
        _settled(conn, "forward", w, a="whatif")
    _settled(conn, "forward", None, a="whatif")                                 # pending
    R.post(conn, ROOM, 1, "m", "exit_timing", None, "challenge", "x", {"turn": "attack", "answer": {"verdict": "disagree",
                                                                                                  "talk_only": True}})
    R.post(conn, ROOM, 1, "m", "exit_timing", None, "challenge", "x", {"turn": "attack", "answer": {"verdict": "agree"}})
    R.post(conn, ROOM, 1, "m", "devils_advocate", None, "challenge", "x", {"turn": "challenge", "answer": {"verdict": "agree"}})
    b = DS.board(conn)
    br = b["base_rates"]
    assert br["lab"] == {"settled": 4, "attacker_won": 1, "advocate_won": 3, "attacker_share": 0.25, "advocate_share": 0.75,
                         "small": True}
    assert br["forward"]["attacker_share"] == 0.5 and br["all"]["settled"] == 6 and br["coin_flip"] == 0.5
    spec = DS.role_record(b, f"spec_{S}")
    assert (spec["won"], spec["lost"], spec["settled"], spec["pending"]) == (4, 2, 6, 1)
    assert spec["as_advocate"] == {"won": 4, "lost": 2} and spec["by_kind"]["lab"] == {"won": 3, "lost": 1}
    assert spec["expected"] == pytest.approx(4 * 0.75 + 2 * 0.5)                 # what the base rate alone gives
    assert spec["hit_rate"] == pytest.approx(4 / 6) and spec["small"] is True
    ex = DS.role_record(b, "exit_timing")
    assert (ex["won"], ex["lost"], ex["as_attacker"]) == (1, 3, {"won": 1, "lost": 3})
    assert (ex["attacks"], ex["talk_only"], ex["gave_up"]) == (2, 1, 1)          # only attack turns are counted
    assert DS.role_record(b, "devils_advocate")["attacks"] == 0
    assert b["small"] is True and b["totals"]["pending"] == 1 and "동전 50%" in b["note"]
    w = DS.who_was_right(conn)
    assert w["tiles"]["settled"] == 6 and w["tiles"]["attacker_share"] == pytest.approx(2 / 6)
    assert len(w["recent"]) == 6 and all(" → " in r["line_ko"] for r in w["recent"])
    assert DS.board(None)["roles"] == [] and DS.who_was_right(None)["tiles"]["settled"] == 0


def test_the_rooms_packet_has_both_seats_the_rule_and_the_test_budget(conn, tmp_path):
    p = Paper(tmp_path)
    _settled(conn, "lab", "b", a=DS.attacker_of(S))
    now = T0 + 8 * DAY                                                          # the settled one is from day 0
    pk = DS.packet(conn, S, p.ro(), now, per_day=3, gap_days=7)
    assert pk["sides"]["advocate"]["role"] == f"spec_{S}" and pk["sides"]["attacker"]["role"] == DS.attacker_of(S)
    assert pk["sides"]["advocate"]["record_side"] == {"won": 1, "lost": 0}
    assert pk["disputes"]["settled_recent"][0]["status"] == "settled"
    dt = pk["disputes"]["dispute_tests"]
    assert dt["left_today"] == 3 and dt["room_test_ok_now"] is True and dt["next_p_threshold"] == 0.05
    assert pk["disputes"]["forward"]["all"]["ok"] is False and "추세 반대 진입" in pk["disputes"]["skip_tags"]
    assert len(json.dumps(pk, ensure_ascii=False)) < 6000
    _open(conn, LABC, now=now)
    dt = DS.dispute_tests(conn, S, now + 1000)
    assert dt["left_today"] == 2 and dt["room_test_ok_now"] is False
