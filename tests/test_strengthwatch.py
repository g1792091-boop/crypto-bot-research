"""Loud alarm when the entry-strength score fails live (review M2): only strategy signals of cells WITH quality edges
count, a WARN rings at most once an hour per cause, every boundary with failures gets an alert row, the 09:20
summary counts them and launchcheck --stage after flags a run where none of the recent signals has a score. Sizing
is never touched."""

import json
import os

from paperbot import Bar, Brackets, Signal
from paperbot import strengthwatch as SW
from paperbot.accounts import AccountBook
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.live3 import Runner3
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
FIVE = 300_000
S = v3_settings()
EDGE = ("N02_ST_KST", "15m")          # a cell with quality edges
NO_EDGE = ("N21_ST_RSI_ADX", "15m")   # no edges: always 'normal', never an alarm
GOOD = {"side": 1, "features": [{"name": "kst_gap_atr", "value": 2.0}, {"name": "st_dist_atr", "value": 6.5}]}


def sig(strategy=EDGE[0], tf=EDGE[1], strength="missing", symbol="BTCUSDT", ts=15 * MIN - 1, meta=None):
    ctx = {} if strength == "missing" else {"strength": strength}
    return Signal(ts=ts, symbol=symbol, timeframe=tf, strategy_id=strategy, side=1, stop_price=0.0, tier="best",
                  atr=0.2, meta={"stop_dist": 0.4, "ctx": ctx, **(meta or {})})


def test_failure_causes():
    assert SW.failure(sig(strength=GOOD)) is None
    assert SW.failure(sig()) == "no_strength"
    assert SW.failure(sig(strength={"error": "ValueError: boom"})) == "strength_error"
    lock = "RuntimeError: strength_defs/N02_ST_KST.py: sha256 3a464cfbda7d != locked 2fe19359bc1c"
    assert SW.failure(sig(strength={"error": lock})) == "hash_mismatch"
    assert SW.failure(sig(strength={"features": [{"name": "kst_gap_atr", "value": None}]})) == "no_values"
    # expected 'normal', never an alarm: a cell without edges, a coin flip, a forced group
    assert SW.failure(sig(*NO_EDGE)) is None
    assert SW.failure(sig("DOGE", "4h")) is None and SW.failure(sig("N02_ST_KST", "4h")) == "no_strength"
    assert SW.failure(sig("RANDOM_1", "15m")) is None
    assert SW.failure(sig(meta={"lev_group": "normal"})) is None
    # the same on a signal_log row's dict
    assert SW.failure({"strategy_id": EDGE[0], "timeframe": EDGE[1], "meta": {"ctx": None}}) == "no_strength"


def test_watch_rings_once_an_hour_per_cause_and_logs_every_boundary(tmp_path):
    store = Store3(str(tmp_path / "w.db"))
    out = ListNotifier()
    clock = {"t": 1_000_000}
    w = SW.StrengthWatch(store, out, lambda: clock["t"])
    subs = [("N02_ST_KST@15m", sig()), ("N02_ST_KST@15m", sig(symbol="ETHUSDT")),
            ("N21_ST_RSI_ADX@15m", sig(*NO_EDGE)), ("RANDOM_1@15m", sig("RANDOM_1")),
            ("N02_ST_KST@15m", sig(strength=GOOD, symbol="SOLUSDT"))]
    assert [f[0] for f in w.observe(15 * MIN, subs)] == ["no_strength", "no_strength"]
    assert len(out.messages) == 1 and out.messages[0][0] == "WARN"
    text = out.messages[0][1]
    assert text.startswith("⚠ 신호 세기 계산 실패 2건 · 세기 기록 없음") and "N02_ST_KST 15분 ×2" in text
    assert "좋은 자리 판정이 '보통'으로 처리됨" in text
    rows = store.conn.execute("SELECT level, text FROM alerts").fetchall()
    assert len(rows) == 1 and rows[0][0] == "WARN" and rows[0][1].startswith("strength score failed for 2 strategy")
    # 10 minutes later: a row, no message; another cause rings at once
    clock["t"] += 10 * MIN
    w.observe(30 * MIN, [("N02_ST_KST@15m", sig())])
    lock = "RuntimeError: strength_defs/N02_ST_KST.py: sha256 3a46 != locked 2fe1"
    w.observe(30 * MIN, [("N02_ST_KST@15m", sig(strength={"error": lock}))])
    assert len(out.messages) == 2 and "잠금(해시) 불일치" in out.messages[1][1] and "오류: RuntimeError" in out.messages[1][1]
    assert store.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 3
    # an hour after the first message: rings again with the count since then
    clock["t"] += 51 * MIN
    w.observe(90 * MIN, [("N02_ST_KST@15m", sig())])
    assert len(out.messages) == 3 and out.messages[2][1].startswith("⚠ 신호 세기 계산 실패 2건")
    assert dict(w.total) == {"no_strength": 4, "hash_mismatch": 1}
    # nothing to say: no row, no message
    assert w.observe(95 * MIN, subs[2:]) == [] and len(out.messages) == 3
    assert store.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 4


class EdgeService:
    """One strategy signal of an edge cell at ``fire_at``, its strength as given."""

    def __init__(self, fire_at, strength):
        self.fire_at, self.strength, self.last = fire_at, strength, {}

    def add_5m(self, b):
        self.last[b.symbol] = b.open_time + FIVE

    def complete(self, boundary):
        return all(self.last.get(s) == boundary for s in V3_SYMBOLS)

    def due(self, boundary):
        return ["15m"] if boundary % (3 * FIVE) == 0 else []

    def compute(self, boundary, tf, now_ms, book):
        if boundary != self.fire_at:
            return [], [], []
        ref = book()["BTCUSDT"][1]
        s = sig(strength=self.strength, ts=boundary - 1)
        s.meta.update(ref_price=ref, ref_time=now_ms())
        row = {"bar_close": boundary, "timeframe": tf, "strategy": EDGE[0], "symbol": "BTCUSDT", "side": 1,
               "atr": 0.2, "ref_price": ref, "ref_time": now_ms(), "delay_ms": 1000, "status": "SUBMITTED",
               "data": {"ctx": s.meta["ctx"]}}
        return [row], [(f"{EDGE[0]}@{EDGE[1]}", s)], []


def steps(lo, hi):
    return [(i * MIN, {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.05, 99.95, 100.0, volume=1.0)
                       for s in V3_SYMBOLS}, {}) for i in range(lo, hi)]


def run_once(tmp_path, name, strength, watch=True):
    store = Store3(str(tmp_path / name))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    book.open_accounts([{"strategy": EDGE[0], "timeframe": EDGE[1], "kind": "strategy"}], 0)
    out = ListNotifier()
    run = Runner3(book, EdgeService(15 * MIN, strength), store, out, V3_SYMBOLS, lambda: 12345,
                  lambda: {"BTCUSDT": (100.1, 100.2)})
    if not watch:
        run.strength = None
    run.process(steps(0, 17))
    return store, book, out, run


def test_runner_alarms_without_touching_the_size(tmp_path):
    store, book, out, run = run_once(tmp_path, "a.db", "missing")
    pos = book.engines["N02_ST_KST@15m"].position
    assert pos is not None
    assert [t for lv, t in out.messages if "신호 세기 계산 실패 1건" in t]
    assert store.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE 'strength score failed%'").fetchone()[0] == 1
    assert store.get_state("health")[1]["strength_failures"] == {"no_strength": 1}
    # the same run without the watcher: the same position (size, leverage), no alarm
    store2, book2, out2, _ = run_once(tmp_path, "b.db", "missing", watch=False)
    p2 = book2.engines["N02_ST_KST@15m"].position
    assert (pos.qty, pos.leverage, pos.margin, pos.entry_price) == (p2.qty, p2.leverage, p2.margin, p2.entry_price)
    assert not [t for lv, t in out2.messages if "신호 세기" in t]
    # the old tier walk never reads the strength: no watcher
    from paperbot.config import V3_OLD_TIER_WALK
    book4 = AccountBook(v3_settings(**V3_OLD_TIER_WALK), {s: Brackets.example() for s in V3_SYMBOLS},
                        Store3(str(tmp_path / "d.db")))
    assert Runner3(book4, EdgeService(0, None), book4.store, None, V3_SYMBOLS, lambda: 0, dict).strength is None
    # a scored signal: no alarm
    store3, _, out3, _ = run_once(tmp_path, "c.db", GOOD)
    assert not [t for lv, t in out3.messages if "신호 세기" in t]
    assert store3.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE 'strength score failed%'").fetchone()[0] == 0


def _log(store, rows):
    store.log_signals([{"bar_close": bc, "timeframe": tf, "strategy": st, "symbol": sym, "side": 1, "atr": 0.2,
                        "ref_price": 1.0, "ref_time": bc, "delay_ms": 1, "status": status,
                        "data": {"ctx": ctx}} for bc, st, tf, sym, status, ctx in rows])
    store.commit()


def test_daily_count_and_summary_line(tmp_path):
    from paperbot.daily3 import notify_report
    store = Store3(str(tmp_path / "d.db"))
    _log(store, [(15 * MIN, *EDGE, "BTCUSDT", "SUBMITTED", {"strength": GOOD}),
                 (15 * MIN, *EDGE, "ETHUSDT", "SUBMITTED", {}),
                 (30 * MIN, *EDGE, "ETHUSDT", "SUBMITTED", {"strength": {"error": "x: sha256 a != locked b"}}),
                 (30 * MIN, *EDGE, "SOLUSDT", "LATE", {}),                         # not traded: not counted
                 (30 * MIN, *NO_EDGE, "SOLUSDT", "SUBMITTED", {}),                 # no edges: expected normal
                 (30 * MIN, "RANDOM_1", "15m", "SOLUSDT", "SUBMITTED", None),       # coin flip
                 (2 * 86_400_000, *EDGE, "BTCUSDT", "SUBMITTED", {})])              # another day
    c = SW.day_counts(store.conn, 0, 86_400_000)
    assert c == {"checked": 3, "failed": 2, "causes": {"no_strength": 1, "hash_mismatch": 1},
                 "cells": {"N02_ST_KST|15m": 2}}
    line = SW.summary_line(c)
    assert line.startswith("⚠ 신호 세기 계산 실패 2/3") and "'보통'으로 처리됨" in line
    assert SW.summary_line({"checked": 5, "failed": 0, "causes": {}}) == "신호 세기 계산 실패 0/5"
    assert SW.summary_line({"checked": 0, "failed": 0}) is None and SW.summary_line(None) is None
    out = ListNotifier()
    rep = {"day": "2026-10-05", "parity": {"accounts": 156, "mismatched_accounts": 0}, "data_quality": {},
           "strength": c}
    msgs = notify_report(rep, out, trades_day=3)
    assert msgs[0][0] == "INFO" and "⚠ 신호 세기 계산 실패 2/3" in msgs[0][1]
    assert "신호 세기" not in notify_report({**rep, "strength": {"error": "x"}}, ListNotifier())[0][1]


def test_launchcheck_after_flags_a_run_without_strength(tmp_path):
    from paperbot import launchcheck as L
    path = str(tmp_path / "paper3.db")
    store = Store3(path)
    assert L.strength_lines(path) == []                                            # no signal yet: nothing to say
    _log(store, [(k * 15 * MIN, *EDGE, "BTCUSDT", "SUBMITTED", {"marks_error": "boom"}) for k in range(1, 25)])
    _log(store, [(k * 15 * MIN, *NO_EDGE, "ETHUSDT", "SUBMITTED", {}) for k in range(1, 25)])
    lines = L.strength_lines(path)
    assert [s for s, _ in lines] == [L.FIX] and "20건 모두 신호 세기 계산 실패(세기 기록 없음)" in lines[0][1]
    _log(store, [(k * 15 * MIN, *EDGE, "SOLUSDT", "SUBMITTED", {"strength": GOOD}) for k in range(30, 35)])
    lines = L.strength_lines(path)
    assert [s for s, _ in lines] == [L.NOTE] and "20건 중 15건" in lines[0][1]
    _log(store, [(k * 15 * MIN, *EDGE, "LTCUSDT", "SUBMITTED", {"strength": GOOD}) for k in range(40, 60)])
    lines = L.strength_lines(path)
    assert [s for s, _ in lines] == [L.OK] and "20건 모두" in lines[0][1]
    store.close()
    assert os.path.exists(path) and json.dumps(lines, ensure_ascii=False)
