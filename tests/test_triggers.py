"""Room triggers (paperbot/agents/triggers.py): code decides when the staff meet."""

import datetime as dt
import json
import sqlite3

import pytest

from paperbot.agents import triggers as T
from paperbot.agents.triggers import (TriggerPolicy, advance_cursors, begin_round, expire_stale_rounds, find_due,
                                      finish_round)
from paperbot.daily3 import SCHEMA as DAILY_SCHEMA
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
S, S2 = "N17_KC_RSI", "V45_AMB"           # weekly weekdays (KST): N17 Tuesday, V45 Friday
ROOM, ROOM2 = f"strat:{S}", f"strat:{S2}"

# agents3.db / inbox.db tables as documented in interface 1 (used when rooms_db is not importable)
AGENTS_DDL = """
CREATE TABLE IF NOT EXISTS rooms (room_id TEXT PRIMARY KEY, kind TEXT, strategy TEXT, title TEXT, members TEXT,
                                  created_ts INTEGER);
CREATE TABLE IF NOT EXISTS rounds (round_id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, trigger TEXT,
    trigger_data TEXT, started_ts INTEGER, ended_ts INTEGER, status TEXT, decision TEXT, calls INTEGER,
    tokens INTEGER);
CREATE TABLE IF NOT EXISTS cursors (k TEXT PRIMARY KEY, v TEXT);
"""
INBOX_DDL = """
CREATE TABLE IF NOT EXISTS owner_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, room_id TEXT,
                                           author TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, proposal_id INTEGER,
                                      decision TEXT, author TEXT, note TEXT);
"""


def kst(y, m, d, hh=0, mm=0):
    """UTC ms of a Korea-time wall clock."""
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc).timestamp() * 1000) - 9 * HOUR


def rec(strategy, tf, pnl, exit_time, side=1, context=None):
    return TradeRecord(
        strategy_id=strategy, symbol="BTCUSDT", timeframe=tf, side=side, signal_ts=exit_time - 3 * HOUR - 1,
        entry_time=exit_time - 3 * HOUR, entry_price=100.0, exit_time=exit_time,
        exit_price=99.0 if pnl < 0 else 101.0, exit_reason="SL" if pnl < 0 else "LOCK", qty=1.0, leverage=20,
        tier="best", margin=50.0, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=0.1, funding=0.0, pnl=pnl,
        roe=pnl / 50, price_move=-0.01 if pnl < 0 else 0.01, mae_price=99.0, mfe_price=100.2,
        equity_after=1000 + pnl, score=0.0, context=context or {})


class World:
    """Synthetic paper3.db (Store3), daily3.db, inbox.db and agents3.db in tmp_path."""

    def __init__(self, tmp_path, start, agents_conn=None):
        self.paths = {k: str(tmp_path / f"{k}.db") for k in ("paper", "daily", "inbox", "agents")}
        self.store = Store3(self.paths["paper"])
        for strat in (S, S2):
            for tf in ("15m", "1h"):
                self.store.add_account(f"{strat}@{tf}", strat, tf, "strategy", start, "paper-v3")
        self.store.add_account("RANDOM_1@15m", "RANDOM_1", "15m", "random", start, "paper-v3")
        self.store.put_state("run", start + 5 * DAY, {"taker_fee": 0.0005})     # rewritten at a restart
        self.store.commit()
        self.daily = sqlite3.connect(self.paths["daily"])
        self.daily.executescript(DAILY_SCHEMA)
        self.inbox = sqlite3.connect(self.paths["inbox"])
        self.inbox.executescript(INBOX_DDL)
        if agents_conn is None:
            agents_conn = sqlite3.connect(self.paths["agents"])
            agents_conn.executescript(AGENTS_DDL)
        self.agents = agents_conn

    # -------------------------------------------------- writers
    def trade(self, aid, pnl, exit_time, **kw):
        strat, tf = aid.split("@")
        self.store.trade(aid, rec(strat, tf, pnl, exit_time, **kw))
        self.store.commit()

    def alert(self, ts, level, text):
        self.store.alert(ts, level, text)
        self.store.commit()

    def say(self, room, text, ts, author="owner1"):
        cur = self.inbox.execute("INSERT INTO owner_messages (ts, room_id, author, text) VALUES (?,?,?,?)",
                                 (ts, room, author, text))
        self.inbox.commit()
        return cur.lastrowid

    def report(self, day, data):
        self.daily.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (day, 0, json.dumps(data)))
        self.daily.commit()

    def run(self, due, now, status="done", calls=3):
        rid = begin_round(self.agents, due, now)
        finish_round(self.agents, rid, status, now + 5 * MIN, decision={"action": "note"}, calls=calls)
        return rid

    def cursors(self):
        return dict(self.agents.execute("SELECT k, v FROM cursors"))

    # -------------------------------------------------- reader
    def due(self, now, policy=None, only=None):
        ro = {k: sqlite3.connect(f"file:{self.paths[k]}?mode=ro", uri=True) for k in ("paper", "daily", "inbox")}
        before = self.agents.total_changes
        try:
            got = find_due(ro["paper"], ro["daily"], self.agents, ro["inbox"], now, policy)
        finally:
            for c in ro.values():
                c.close()
        assert self.agents.total_changes == before          # find_due never writes
        for d in got:
            json.dumps(d.data)                                  # trigger_data must be JSON
        return [d for d in got if only is None or d.trigger in (only if isinstance(only, tuple) else (only,))]


START = kst(2026, 9, 20, 14, 0)         # run start (accounts created); day 30 = 2026-10-20 14:00 KST
QUIET = kst(2026, 10, 7, 15, 0)         # Wednesday 15:00 KST: no meeting window, no N17/V45 weekly day


@pytest.fixture
def w(tmp_path):
    return World(tmp_path, START)


def keys(ds):
    return [(d.room_id, d.trigger, d.priority) for d in ds]


# ------------------------------------------------------------------ incident
def test_incident_liquidation_fires_once_then_waits_for_new_alerts(w):
    t = QUIET
    w.alert(t - 10 * MIN, "INFO", f"[{S}@15m] EXIT BTCUSDT SL pnl -10.00")
    w.alert(t - 9 * MIN, "WARN", f"[{S}@15m] drawdown 20.0% (level 20%), equity 800.00")
    w.alert(t - 8 * MIN, "CRITICAL", f"[{S}@15m] LIQUIDATED BTCUSDT 40x lost margin 25.00")
    ds = w.due(t)
    assert keys(ds) == [("team:ops", "incident", 0)]
    d = ds[0]
    assert d.meeting == "incident" and d.data["counts"] == {"liquidation": 1}
    assert d.data["evidence_ts"] == t - 8 * MIN and "강제청산 1건" in d.data["summary_ko"]
    assert keys(w.due(t)) == keys(ds)                        # no side effects: same answer again
    w.run(d, t)
    assert w.cursors()["incident:alert_rowid"] == "3"
    assert w.due(t + MIN) == []                              # deduped by alert rowid
    w.alert(t + 5 * MIN, "WARN", "data gap at 123: no bar for ['BTCUSDT']")
    assert w.due(t + 20 * MIN) == []                         # 30 min between incident rounds: batch bursts
    ds = w.due(t + 30 * MIN)
    assert keys(ds) == [("team:ops", "incident", 0)] and ds[0].data["counts"] == {"data_gap": 1}


def test_incident_signal_timeout_and_nightly_reports(w):
    t = QUIET
    w.alert(t - HOUR, "WARN", "signal workers did not answer within 120s; signals skipped at 1 for 15m, 1h")
    w.report("2026-10-05", {"day": "2026-10-05", "parity": {"accounts": 195, "mismatched_accounts": 2},
                            "data_quality": {"BTCUSDT": {"missing": 3}, "ETHUSDT": {"missing": 0},
                                             "max_abs_funding_pct": 0.01}})
    w.report("2026-10-06", {"day": "2026-10-06", "parity": "no 00:00 snapshot for this day (runner not running then)",
                            "data_quality": {"BTCUSDT": {"missing": 0}}})
    ds = w.due(t)
    assert keys(ds) == [("team:ops", "incident", 0)]
    assert ds[0].data["counts"] == {"signal_timeout": 1, "parity_mismatch": 1, "missing_bars": 1, "no_snapshot": 1}
    w.run(ds[0], t)
    assert w.cursors()["incident:report_day"] == "2026-10-06"
    w.report("2026-10-05", {"parity": {"accounts": 195, "mismatched_accounts": 5}})   # re-run of a handled day
    w.report("2026-10-07", {"parity": {"accounts": 195, "mismatched_accounts": 0},
                            "data_quality": {"BTCUSDT": {"missing": 0}}})           # a clean night
    assert w.due(t + HOUR) == []
    w.report("2026-10-08", {"parity": {"accounts": 195, "mismatched_accounts": 1}})
    ds = w.due(t + HOUR)
    assert ds[0].data["counts"] == {"parity_mismatch": 1} and ds[0].data["items"][0]["day"] == "2026-10-08"


# ------------------------------------------------------------------ owner
def test_owner_message_starts_a_round_in_its_room(w):
    t = QUIET
    w.trade(f"{S}@15m", -10.0, t - 2 * HOUR)
    m1 = w.say(ROOM, "요즘 손절이 왜 이렇게 많나요?", t - 3 * MIN)
    w.say("team:lead", "이번 주 요약 부탁해요", t - 2 * MIN)
    w.say("strat:NOPE", "없는 방", t - MIN)
    ds = w.due(t)
    assert keys(ds) == [(ROOM, "owner", 1), ("team:lead", "owner", 1)]      # oldest evidence first
    d = ds[0]
    assert d.data["message_ids"] == [m1] and d.data["messages"][0]["text"].startswith("요즘")
    assert d.data["cursors"] == {f"owner:{ROOM}": str(m1), f"loss:{ROOM}": "1"}
    for x in ds:
        w.run(x, t)
    assert w.due(t + MIN) == []
    m3 = w.say(ROOM, "하나 더", t + 2 * MIN)
    ds = w.due(t + 3 * MIN)
    assert keys(ds) == [(ROOM, "owner", 1)] and ds[0].data["message_ids"] == [m3]


# ------------------------------------------------------------------ loss cluster
def test_loss_cluster_needs_three_new_losses_and_four_hours_between_rounds(w):
    t = QUIET
    w.trade(f"{S}@15m", -10.0, t - 5 * HOUR)
    w.trade(f"{S}@1h", -12.0, t - 4 * HOUR)
    w.trade(f"{S}@15m", 8.0, t - 3 * HOUR)                  # a win does not count
    for k in range(5):                                       # coin-flip losses never count
        w.trade("RANDOM_1@15m", -5.0, t - 3 * HOUR + k)
    w.trade(f"{S2}@15m", -5.0, t - 3 * HOUR)
    w.trade(f"{S2}@1h", -5.0, t - 3 * HOUR)
    assert w.due(t) == []
    w.trade(f"{S}@1h", -9.0, t - HOUR)
    ds = w.due(t)
    assert keys(ds) == [(ROOM, "loss_cluster", 2)]
    d = ds[0]
    assert d.data["losses"] == 3 and d.data["by_timeframe"] == {"15m": 1, "1h": 2}
    assert d.data["evidence_ts"] == t - 5 * HOUR and d.data["exit_reasons"] == {"SL": 3}
    assert d.data["strategy"] == S and "새 손실 3건" in d.data["summary_ko"]
    w.run(d, t)
    assert w.due(t + MIN) == []
    for k in range(3):
        w.trade(f"{S}@15m", -7.0, t + HOUR + k)
    assert w.due(t + 3 * HOUR) == []                         # min gap 4h since the last loss round
    ds = w.due(t + 4 * HOUR)
    assert keys(ds) == [(ROOM, "loss_cluster", 2)] and ds[0].data["losses"] == 3


def test_loss_cluster_by_a_repeated_tag(w):
    t = QUIET
    pol = TriggerPolicy(loss_min_count=10, loss_tag_min_count=3)
    against = {"regime": "trend_down"}                       # a long into a down trend: "추세 반대 진입"
    w.trade(f"{S}@15m", -10.0, t - 5 * HOUR, context=against)
    w.trade(f"{S}@1h", -10.0, t - 4 * HOUR, context=against)
    w.trade(f"{S}@1h", -10.0, t - 4 * HOUR, context={"regime": "trend_up"})
    assert w.due(t, pol) == []
    w.trade(f"{S}@15m", -10.0, t - 2 * HOUR, context=against)
    ds = w.due(t, pol)
    assert keys(ds) == [(ROOM, "loss_cluster", 2)]
    assert ds[0].data["top_tags"] == [{"tag": "추세 반대 진입", "losses": 3}]
    assert "추세 반대 진입 3건" in ds[0].data["summary_ko"]


def test_any_round_in_the_room_counts_as_having_seen_the_losses(w):
    t = QUIET
    for k in range(3):
        w.trade(f"{S}@15m", -10.0, t - 3 * HOUR + k)
    w.say(ROOM, "손실 이야기 좀 해 주세요", t - MIN)
    ds = w.due(t)
    assert keys(ds) == [(ROOM, "owner", 1)]                  # one round per room per tick; owner first
    w.run(ds[0], t)
    assert w.due(t + MIN) == []                              # the owner round saw these losses
    assert w.due(t + MIN, TriggerPolicy(any_round_resets_losses=False)) == []   # cursor is already written
    for k in range(3):
        w.trade(f"{S}@1h", -10.0, t + k)
    assert keys(w.due(t + MIN)) == [(ROOM, "loss_cluster", 2)]


# ------------------------------------------------------------------ bust
def test_bust_fires_once_per_account(w):
    t = QUIET
    w.store.put_state("accounts", t - HOUR, {"engines": {f"{S}@15m": {"bust": True}, f"{S}@1h": {"bust": False},
                                                         "RANDOM_1@15m": {"bust": True}}})
    w.store.commit()
    ds = w.due(t)
    assert keys(ds) == [(ROOM, "bust", 2)] and ds[0].data["accounts"] == [f"{S}@15m"]
    assert "계좌 파산" in ds[0].data["summary_ko"]
    w.run(ds[0], t)
    assert w.due(t + MIN) == []
    w.alert(t + 2 * MIN, "WARN", f"[{S2}@1h] BUST: bust: equity 9.00 below 10.00")   # alert before the next save
    ds = w.due(t + 3 * MIN)
    assert keys(ds) == [(ROOM2, "bust", 2)] and ds[0].data["evidence_ts"] == t + 2 * MIN
    w.run(ds[0], t + 3 * MIN)
    w.store.put_state("accounts", t + 4 * MIN, {"engines": {f"{S}@15m": {"bust": True},
                                                            f"{S2}@1h": {"bust": True}}})
    w.store.commit()
    assert w.due(t + 5 * MIN) == []


# ------------------------------------------------------------------ checkpoint
def test_checkpoint_on_day_30_60_90(tmp_path):
    w = World(tmp_path, START)
    only = "checkpoint"
    assert w.due(START + 30 * DAY - MIN, only=only) == []
    ds = w.due(START + 30 * DAY, only=only)
    assert keys(ds) == [("team:lead", "checkpoint", 3)]
    assert ds[0].data["day"] == 30 and ds[0].data["run_start"] == START      # not the restart time in state 'run'
    w.run(ds[0], START + 30 * DAY)
    assert w.due(START + 45 * DAY, only=only) == []
    ds = w.due(START + 60 * DAY + HOUR, only=only)
    assert ds[0].data["key"] == f"checkpoint:{START}:60"     # the run start is part of the key
    (tmp_path / "x").mkdir()
    fresh = World(tmp_path / "x", START)
    ds = fresh.due(START + 95 * DAY, only=only)               # started late: only the latest checkpoint
    assert [d.data["day"] for d in ds] == [90]
    assert T.run_start(None) is None


# ------------------------------------------------------------------ weekly
def test_weekly_review_on_the_strategy_weekday_after_30_trades(w):
    tue, wed = kst(2026, 10, 6, 15), kst(2026, 10, 7, 15)   # N17: index 22, 22 % 7 = 1 = Tuesday
    assert T.kst_weekday(tue) == T.STRATEGIES.index(S) % 7
    for k in range(29):
        w.trade(f"{S}@15m" if k % 2 else f"{S}@1h", 5.0, tue - 5 * DAY + k * HOUR)
    for k in range(40):
        w.trade(f"{S2}@15m", 5.0, tue - 5 * DAY + k * HOUR)    # V45's day is Friday: 33 trades by its end
    # V45's Friday review never ran: it is still owed on Tuesday (its own slot key), N17 is not due yet
    [v45] = w.due(tue, only="weekly")
    assert (v45.room_id, v45.data["key"]) == (f"strat:{S2}", f"weekly:{S2}:2026-10-02")
    assert T.kst_weekday(T.weekly_slot(tue, T.STRATEGIES.index(S2))) == T.STRATEGIES.index(S2) % 7 == 4
    w.run(v45, tue)
    assert w.due(tue, only="weekly") == []
    w.trade(f"{S}@15m", 5.0, tue - HOUR)
    assert w.due(tue - DAY, only="weekly") == []               # Monday: not N17's weekday
    ds = w.due(tue, only="weekly")
    assert keys(ds) == [(ROOM, "weekly", 4)] and ds[0].data["trades"] == 30
    assert ds[0].data["key"] == f"weekly:{S}:2026-10-06" and ds[0].data["evidence_ts"] == T.kst_day_start(tue)
    # a review that did not run on its day stays due on the next days (same slot), until it has run
    late = w.due(wed, only="weekly")
    assert keys(late) == [(ROOM, "weekly", 4)] and late[0].data["key"] == ds[0].data["key"]
    assert "2026-10-06 검토를 미뤘던 것" in late[0].data["summary_ko"]
    w.run(ds[0], tue)
    assert w.due(tue + HOUR, only="weekly") == [] and w.due(wed, only="weekly") == []
    assert w.due(tue + 7 * DAY, only="weekly") == []           # no 30 new trades since the last weekly
    for k in range(30):
        w.trade(f"{S}@1h", 5.0, tue + DAY + k * MIN)
    assert keys(w.due(tue + 7 * DAY, only="weekly")) == [(ROOM, "weekly", 4)]


# ------------------------------------------------------------------ morning / evening (KST)
def test_morning_meeting_once_per_kst_day(w):
    pol = TriggerPolicy(enabled=("morning", "evening"))
    assert w.due(kst(2026, 10, 5, 7, 59), pol) == []
    t = kst(2026, 10, 5, 8, 0)                                 # 2026-10-04 23:00 UTC
    ds = w.due(t, pol)
    assert keys(ds) == [("team:market", "morning", 3)]
    assert ds[0].data["key"] == "morning:2026-10-05" and ds[0].data["evidence_ts"] == t
    w.run(ds[0], t)
    assert w.due(kst(2026, 10, 5, 9, 0), pol) == []
    assert w.due(kst(2026, 10, 6, 7, 59), pol) == []
    assert w.due(kst(2026, 10, 6, 11, 59), pol)[0].data["key"] == "morning:2026-10-06"
    assert w.due(kst(2026, 10, 6, 12, 0), pol) == []           # window (4h) over: skipped that day


def test_evening_review_then_lead_and_the_midnight_boundary(w):
    pol = TriggerPolicy(enabled=("morning", "evening"))
    assert w.due(kst(2026, 10, 5, 21, 59), pol) == []
    t = kst(2026, 10, 5, 22, 0)
    ds = w.due(t, pol)
    assert keys(ds) == [("team:review", "evening", 3), ("team:lead", "evening", 3)]
    assert w.due(t, TriggerPolicy(enabled=("evening",), max_rounds_per_tick=1)) == ds[:1]
    rid = begin_round(w.agents, ds[0], t)
    assert w.due(t + 5 * MIN, pol) == []                       # lead waits while the review team meets
    finish_round(w.agents, rid, "done", t + 10 * MIN)
    ds2 = w.due(t + 11 * MIN, pol)
    assert keys(ds2) == [("team:lead", "evening", 3)]
    w.run(ds2[0], t + 11 * MIN)
    assert w.due(t + 20 * MIN, pol) == []
    # next day nobody met at 22:00: after midnight KST it is still that evening's meeting, until 02:00
    ds = w.due(kst(2026, 10, 7, 1, 30), pol)
    assert [d.data["key"] for d in ds] == ["evening:2026-10-06"] * 2
    assert w.due(kst(2026, 10, 7, 2, 0), pol) == []


# ------------------------------------------------------------------ order and caps
def test_priority_order_oldest_evidence_and_global_cap(tmp_path):
    now = kst(2026, 10, 6, 8, 30)                              # Tuesday (N17 weekly), morning window
    start = kst(2026, 10, 6, 6, 0) - 30 * DAY                  # day-30 checkpoint at 06:00 today
    w = World(tmp_path, start)
    for k in range(30):
        w.trade(f"{S}@15m", -5.0 if k % 3 == 0 else 5.0, now - 3 * DAY + k * HOUR)
    w.alert(now - 2 * HOUR, "WARN", f"[{S2}@1h] BUST: bust: equity 9.00 below 10.00")
    w.say("team:risk", "레버리지 너무 높지 않나요?", now - 5 * MIN)
    w.alert(now - 10 * MIN, "CRITICAL", f"[{S2}@15m] LIQUIDATED ETHUSDT 50x lost margin 20.00")
    everything = [("team:ops", "incident", 0), ("team:risk", "owner", 1), (ROOM2, "bust", 2),   # a bust first
                  (ROOM, "loss_cluster", 2), ("team:lead", "checkpoint", 3), ("team:market", "morning", 3)]
    assert keys(w.due(now)) == everything[:4]                  # at most 4 rounds per tick
    assert keys(w.due(now, TriggerPolicy(max_rounds_per_tick=10))) == everything   # N17 weekly waits (1/room/tick)
    got = w.due(now, TriggerPolicy(max_rounds_per_tick=10, max_per_room_per_tick=2))
    assert keys(got) == everything + [(ROOM, "weekly", 4)]


def test_room_day_cap_in_kst_days_and_incidents_are_exempt(w):
    t = kst(2026, 10, 7, 15, 0)
    w.say(ROOM, "첫 질문", kst(2026, 10, 6, 23, 50))
    w.run(w.due(kst(2026, 10, 6, 23, 50))[0], kst(2026, 10, 6, 23, 50))     # yesterday (KST): does not count
    for k in range(3):
        w.say(ROOM, f"질문 {k}", t + k * HOUR)
        ds = w.due(t + k * HOUR + MIN)
        assert keys(ds) == [(ROOM, "owner", 1)]
        w.run(ds[0], t + k * HOUR + MIN)
    w.say(ROOM, "네 번째 질문", t + 3 * HOUR)
    assert w.due(t + 3 * HOUR + MIN) == []                     # 3 rounds in this room today
    assert w.due(t + 3 * HOUR + MIN, TriggerPolicy(max_rounds_per_room_day=4)) != []
    ds = w.due(kst(2026, 10, 8, 0, 0), only="owner")           # new KST day (15:00 UTC)
    assert keys(ds) == [(ROOM, "owner", 1)]
    for k in range(4):                                         # incidents: no daily cap
        w.alert(t + k * HOUR, "CRITICAL", f"[{S}@15m] LIQUIDATED BTCUSDT 40x lost margin 1.00")
        ds = w.due(t + k * HOUR + MIN, only="incident")
        assert keys(ds) == [("team:ops", "incident", 0)]
        w.run(ds[0], t + k * HOUR + MIN)


# ------------------------------------------------------------------ crash safety
def test_running_round_blocks_then_fires_again_once_after_two_hours(w):
    t = QUIET
    for k in range(3):
        w.trade(f"{S}@15m", -10.0, t - 3 * HOUR + k)
    d = w.due(t)[0]
    rid = begin_round(w.agents, d, t)                          # the tick dies during this round
    assert json.loads(w.agents.execute("SELECT trigger_data FROM rounds WHERE round_id = ?",
                                       (rid,)).fetchone()[0])["cursors"] == d.data["cursors"]
    assert w.cursors() == {}                                   # cursors move only when a round ends
    assert w.due(t + HOUR) == []
    assert w.due(t + 2 * HOUR - 1) == []
    ds = w.due(t + 2 * HOUR)                                   # treated as failed: fires again
    assert keys(ds) == [(ROOM, "loss_cluster", 2)]
    assert ds[0].data["key"] == d.data["key"] and ds[0].data["retry_of"] == rid
    assert ds[0].data["summary_ko"].startswith("(중단된 회의 다시 시작)")
    begin_round(w.agents, ds[0], t + 2 * HOUR)                 # ... and dies again
    assert w.due(t + 4 * HOUR + 1) == []                       # only once: waits for new evidence
    w.trade(f"{S}@1h", -10.0, t + 4 * HOUR)
    # the two crashed rounds used 2 of the room's 3 daily slots; the 3rd is kept for an owner post
    assert w.due(t + 4 * HOUR + 1) == []
    ds = w.due(t + 4 * HOUR + 1, TriggerPolicy(owner_reserved_per_room_day=0))
    assert keys(ds) == [(ROOM, "loss_cluster", 2)] and ds[0].data["retry_of"] is None
    assert ds[0].data["losses"] == 4                           # nothing was lost
    w.run(ds[0], t + 4 * HOUR + 1)
    assert w.cursors()[f"loss:{ROOM}"] == "4" and w.due(t + 9 * HOUR, only="loss_cluster") == []


def test_expiring_stale_rounds_changes_nothing_about_what_is_due(w):
    t = QUIET
    for k in range(3):
        w.trade(f"{S}@15m", -10.0, t - 3 * HOUR + k)
    d = w.due(t)[0]
    rid = begin_round(w.agents, d, t)
    assert expire_stale_rounds(w.agents, t + HOUR) == []        # still possibly working
    before = w.due(t + 2 * HOUR)
    assert expire_stale_rounds(w.agents, t + 2 * HOUR) == [rid]
    status, decision = w.agents.execute("SELECT status, decision FROM rounds WHERE round_id = ?", (rid,)).fetchone()
    assert status == "failed" and json.loads(decision)["reason"] == "stale"
    after = w.due(t + 2 * HOUR)
    assert [x.data for x in after] == [x.data for x in before] and after[0].data["retry_of"] == rid
    assert w.cursors() == {}


def test_a_round_left_running_is_expired_under_the_lock_even_after_the_clock_stepped_back(w):
    """With the tick lock held (stale_ms=0) no other pass owns a 'running' round; one whose start is 'later'
    than now (the clock stepped back after the pass died) kept blocking its room and trigger."""
    t = QUIET
    for k in range(3):
        w.trade(f"{S}@15m", -10.0, t - 3 * HOUR + k)
    d = w.due(t)[0]
    rid = begin_round(w.agents, d, t + 20 * 60_000)             # started by a pass whose clock was ahead
    assert expire_stale_rounds(w.agents, t + 5 * 60_000) == []  # without the lock: possibly still working
    assert expire_stale_rounds(w.agents, t + 5 * 60_000, stale_ms=0) == [rid]
    assert w.agents.execute("SELECT status FROM rounds WHERE round_id = ?", (rid,)).fetchone()[0] == "failed"


def test_failed_round_retries_once_and_done_is_never_repeated(w):
    t = QUIET
    w.say(ROOM, "질문", t)
    d = w.due(t + MIN)[0]
    w.run(d, t + MIN, status="failed")
    ds = w.due(t + 2 * MIN)
    assert ds[0].data["retry_of"] is not None
    w.run(ds[0], t + 2 * MIN, status="failed")
    assert w.due(t + 3 * MIN) == []
    # a finished round whose cursors never got written is not repeated for the same evidence
    w.say(ROOM2, "질문", t)
    d = w.due(t + 4 * MIN)[0]
    rid = begin_round(w.agents, d, t + 4 * MIN)
    w.agents.execute("UPDATE rounds SET status = 'done' WHERE round_id = ?", (rid,))
    w.agents.commit()
    assert w.due(t + 5 * MIN) == []


def test_budget_stop_defers_the_trigger_class_to_the_next_kst_day(w):
    t = kst(2026, 10, 7, 15, 0)
    w.say(ROOM, "질문 1", t)
    w.say(ROOM2, "질문 2", t)
    d = w.due(t + MIN)[0]
    w.run(d, t + MIN, status="stopped_budget", calls=0)
    assert w.cursors() == {}
    w.alert(t + 2 * MIN, "CRITICAL", "[x] ENGINE HALTED: y. Operator action required.")
    assert keys(w.due(t + 3 * MIN)) == [("team:ops", "incident", 0)]    # other classes still meet
    ds = w.due(kst(2026, 10, 8, 0, 1), TriggerPolicy(enabled=("owner",)))
    assert keys(ds) == [(ROOM, "owner", 1), (ROOM2, "owner", 1)]
    assert ds[0].data["retry_of"] is None                     # a budget stop is not a failed attempt


# ------------------------------------------------------------------ misc
def test_missing_databases_and_empty_agents_db(tmp_path):
    empty = sqlite3.connect(":memory:")
    assert find_due(None, None, empty, None, QUIET) == []
    ds = find_due(None, None, empty, None, kst(2026, 10, 7, 8, 0))
    assert keys(ds) == [("team:market", "morning", 3)]


def test_cursors_only_move_forward(w):
    advance_cursors(w.agents, {"cursors": {"loss:strat:X": "10", "sched:morning:team:market": "2026-10-05"}})
    wrote = advance_cursors(w.agents, {"cursors": {"loss:strat:X": "9", "sched:morning:team:market": "2026-10-04",
                                                   "owner:team:lead": "3"}})
    assert wrote == {"owner:team:lead": "3"}
    assert w.cursors() == {"loss:strat:X": "10", "sched:morning:team:market": "2026-10-05", "owner:team:lead": "3"}
    with pytest.raises(KeyError):
        finish_round(w.agents, 999, "done", QUIET)


def test_works_on_the_rooms_db_schema(tmp_path):
    rooms_db = pytest.importorskip("paperbot.agents.rooms_db")
    conn = rooms_db.open_agents(str(tmp_path / "agents3.db"))
    if hasattr(rooms_db, "ensure_rooms"):
        rooms_db.ensure_rooms(conn)
    (tmp_path / "w").mkdir()
    w = World(tmp_path / "w", START, agents_conn=conn)
    w.say(ROOM, "질문", QUIET)
    ds = w.due(QUIET + MIN)
    assert keys(ds) == [(ROOM, "owner", 1)]
    w.run(ds[0], QUIET + MIN)
    assert w.due(QUIET + 2 * MIN) == []


# ================================================================== review fixes (regression tests)
def test_a_bust_goes_before_older_loss_clusters(tmp_path):
    t = QUIET
    w = World(tmp_path, START)
    others = [s for s in T.STRATEGIES if s not in (S, S2)][:11]
    for s in others:
        w.store.add_account(f"{s}@1h", s, "1h", "strategy", START, "paper-v3")
        for k in range(3):
            w.store.trade(f"{s}@1h", rec(s, "1h", -5.0, t - 2 * DAY + k * HOUR))
    w.store.commit()
    w.alert(t - 10 * MIN, "WARN", f"[{S2}@1h] BUST: bust: equity 9.00 below 10.00")
    ds = w.due(t)
    assert keys(ds)[0] == (ROOM2, "bust", 2) and len(ds) == 4          # first, although its evidence is newest
    assert all(d.trigger == "loss_cluster" for d in ds[1:])


def test_a_bust_seen_only_in_the_saved_state_dates_from_its_last_trade(w):
    t = QUIET
    w.trade(f"{S}@15m", -40.0, t - 6 * HOUR)
    w.store.put_state("accounts", t - MIN, {"engines": {f"{S}@15m": {"bust": True}}})   # saved just now
    w.store.commit()
    [d] = w.due(t, only="bust")
    assert d.data["evidence_ts"] == t - 6 * HOUR


def _stopped(w, due, now, stopped, blocks=None):
    rid = begin_round(w.agents, due, now)
    dec = {"action": None, "stopped": stopped}
    if blocks is not None:
        dec["blocks"] = blocks
    finish_round(w.agents, rid, "stopped_budget", now + MIN, decision=dec, calls=0)


def test_what_a_budget_stop_pauses(w):
    t = QUIET
    w.say(ROOM, "질문", t - 10 * MIN)
    w.alert(t - 5 * MIN, "CRITICAL", f"[{S}@15m] LIQUIDATED BTCUSDT 40x lost margin 1.00")
    for k in range(3):
        w.trade(f"{S2}@15m", -10.0, t - 3 * HOUR + k)
    owner = w.due(t, only="owner")[0]
    # a class cap pauses that class only
    _stopped(w, owner, t, "budget_class")
    assert {d.trigger for d in w.due(t + 2 * MIN)} == {"incident", "loss_cluster"}
    # the reserve for incidents / scheduled meetings pauses the others, never the incident
    _stopped(w, w.due(t + 2 * MIN, only="loss_cluster")[0], t + 2 * MIN, "budget_reserve",
             ["owner", "loss", "weekly"])
    assert [d.trigger for d in w.due(t + 4 * MIN)] == ["incident"]
    # the total or the 7-day cap pause everything, until the next KST day
    _stopped(w, w.due(t + 4 * MIN)[0], t + 4 * MIN, "budget_total")
    assert w.due(t + 6 * MIN) == []
    assert {d.trigger for d in w.due(kst(2026, 10, 8, 0, 5))} >= {"owner", "loss_cluster", "incident"}


def test_a_plan_usage_limit_pauses_everything_for_an_hour_only(w):
    t = QUIET
    w.say(ROOM, "질문", t - 10 * MIN)
    _stopped(w, w.due(t)[0], t, "usage_limit")                 # the round stops at t + 1 min
    assert w.due(t + 30 * MIN) == []
    assert w.due(t + HOUR) == []                               # the hour runs from the stop, not the start
    ds = w.due(t + HOUR + MIN)
    assert keys(ds) == [(ROOM, "owner", 1)] and ds[0].data["retry_of"] is None
    assert w.due(t + HOUR + MIN, TriggerPolicy(usage_backoff_ms=2 * HOUR)) == []


def test_transient_failures_are_retried_with_a_growing_pause(w):
    t = QUIET
    w.say(ROOM, "질문", t - 10 * MIN)
    # each round fails 1 min after it starts; the pause runs from the failure
    for k, (at, pause) in enumerate(((t, 10), (t + 11 * MIN, 20), (t + 32 * MIN, 40))):
        [d] = w.due(at)
        assert d.data["retry_of"] is None                          # never counted as a failed attempt
        rid = begin_round(w.agents, d, at)
        finish_round(w.agents, rid, "failed", at + MIN, decision={"error": "x", "transient": True, "calls_ok": 0},
                     calls=2)
        assert w.due(at + pause * MIN) == []
    assert keys(w.due(t + 73 * MIN)) == [(ROOM, "owner", 1)]
    # transient rounds with no answer do not use the room's daily slots
    st = T._Rooms(w.agents, t + 70 * MIN, TriggerPolicy())
    assert st.rounds_today(ROOM) == 0


def test_one_meeting_that_keeps_failing_transiently_waits_alone(w):
    """Three transient failures in a row of ONE meeting (e.g. its first speaker's model is refused):
    it waits on its own growing pause, and the other rooms are no longer paused."""
    t = QUIET
    w.say(ROOM, "질문", t - 10 * MIN)
    at = t
    for pause in (10, 20, 40):
        [d] = w.due(at)
        rid = begin_round(w.agents, d, at)
        finish_round(w.agents, rid, "failed", at + MIN, decision={"error": "x", "transient": True, "calls_ok": 0},
                     calls=2)
        at += MIN + pause * MIN
    w.say(ROOM2, "다른 방 질문", at - 30 * MIN)
    ended = at - 40 * MIN                                      # the third failure
    assert keys(w.due(ended + MIN)) == [(ROOM2, "owner", 1)]   # the other room meets; ROOM waits alone
    assert keys(w.due(ended + 40 * MIN)) == [(ROOM, "owner", 1), (ROOM2, "owner", 1)]
    # two different meetings failing in a row is an outage again: every room waits
    [d] = [x for x in w.due(ended + 40 * MIN) if x.room_id == ROOM2]
    rid = begin_round(w.agents, d, ended + 41 * MIN)
    finish_round(w.agents, rid, "failed", ended + 42 * MIN, decision={"error": "x", "transient": True, "calls_ok": 0},
                 calls=2)
    assert w.due(ended + 43 * MIN) == []


def test_stopped_rounds_do_not_use_the_rooms_daily_slots(w):
    t = QUIET
    for k in range(3):
        w.say(ROOM, f"질문 {k}", t + k * MIN)
        d = w.due(t + k * MIN + 30, only="owner")[0]
        rid = begin_round(w.agents, d, t + k * MIN + 30)
        finish_round(w.agents, rid, "stopped_budget", t + k * MIN + 40,
                     decision={"stopped": "budget_class", "blocks": []}, calls=2)
    st = T._Rooms(w.agents, t + HOUR, TriggerPolicy())
    assert st.rounds_today(ROOM) == 0 and keys(w.due(t + HOUR)) == [(ROOM, "owner", 1)]


def test_find_due_leaves_out_what_the_caller_defers(w):
    t = QUIET
    w.say(ROOM, "질문", t - 10 * MIN)
    for k in range(3):
        w.trade(f"{S2}@15m", -10.0, t - 3 * HOUR + k)
    assert {d.trigger for d in w.due(t)} == {"owner", "loss_cluster"}
    ro = {k: sqlite3.connect(f"file:{w.paths[k]}?mode=ro", uri=True) for k in ("paper", "daily", "inbox")}
    try:
        got = find_due(ro["paper"], ro["daily"], w.agents, ro["inbox"], t, None, defer_triggers=("loss_cluster",))
        assert [d.trigger for d in got] == ["owner"]
        got = find_due(ro["paper"], ro["daily"], w.agents, ro["inbox"], t, None, defer_classes=("owner",),
                       skip_rooms=(ROOM2,))
        assert got == []
    finally:
        for c in ro.values():
            c.close()


def test_a_file_that_is_not_a_database_reads_as_empty(w):
    with open(w.paths["daily"], "wb") as fh:
        fh.write(b"garbage" * 200)
    bad = sqlite3.connect(w.paths["daily"])
    assert T._rows(bad, "SELECT * FROM reports") == []
    bad.close()
