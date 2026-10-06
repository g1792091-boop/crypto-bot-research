"""The shadow league's engine: one tick follows closed bars in order and writes signals, virtual trades, coin-flip
clones and the owners'-style account. Restarts, gaps, double ticks, warming up, failing feeds, migrations. All bars are
committed synthetic fixtures served by a fake klines endpoint: nothing here reaches the network."""

import os
import sqlite3

import numpy as np
import pytest

from shadowleague_world import (HOUR, MIN, T0, FakeExchange, make_member, now_after_bar, open_store, series_arrays)
from paperbot.agents import committee as CM
from paperbot.shadowleague import account as AC
from paperbot.shadowleague import clones as CL
from paperbot.shadowleague import feed as FD
from paperbot.shadowleague import league as LG
from paperbot.shadowleague import sim as SM
from paperbot.shadowleague import store as ST
from paperbot.shadowleague import zoneflip as ZF

ALL = list(range(1099, 3999, 100)) + [3999]
START = T0 + 1000 * HOUR                      # the member starts at bar 1000: its history begins at bar 0 (= the fixture's start)
TABLES = ("members", "feeds", "bars", "series_state", "signals", "trades", "clones", "account_daily")
BOOKKEEPING = {"members": {"created_ms", "activated_ms", "last_tick_ms"}, "series_state": {"updated_ms"},
               "signals": {"recorded_ms"}, "trades": {"recorded_ms", "closed_ms"}, "clones": {"created_ms", "resolved_ms"},
               "feeds": {"last_fetch_ms", "last_ok_ms", "next_try_ms"}}


@pytest.fixture(autouse=True)
def unhurried(monkeypatch):
    """A busy test machine must not turn a slow tick into a 'timed out' one: the wall-time tests set their own limits."""
    monkeypatch.setattr(LG, "WORK_S", 1e6)
    monkeypatch.setattr(LG, "HARD_S", 1e6)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the shadow league tests must not use the network")
    monkeypatch.setattr(CM, "http_get", boom)
    import socket
    monkeypatch.setattr(socket.socket, "connect", boom)


def dump(store, tables=TABLES) -> dict:
    """The tables' contents without the columns that record WHEN this run did something (wall clock bookkeeping)."""
    out = {}
    for t in tables:
        cur = store.conn.execute(f"SELECT * FROM {t}")
        cols = [d[0] for d in cur.description]
        keep = [i for i, c in enumerate(cols) if c not in BOOKKEEPING.get(t, ())]
        out[t] = sorted(tuple(r[i] for i in keep) for r in cur.fetchall())
    return out


def ticks(store, ex, member, idxs, tf="1h", reopen=False, get=None):
    """One league tick after each bar index in ``idxs`` (the clock shows just after that bar closed and settled)."""
    last = None
    for i in idxs:
        ex.now_ms = now_after_bar(tf, i)
        if reopen:
            path = store.path
            store.close()
            store = ST.Store(path)
        last = LG.League(store, (member,), get or ex.get).tick(ex.now_ms)
        assert not last["errors"], last["errors"]
    return store, last


def world(tmp_path, tf="1h", start=START, k=10, coins=("BTC",), name="shadow_league.db"):
    ex = FakeExchange(coins=coins, tfs=(tf,))
    m = make_member(coins=coins, tfs=(tf,), start_ms=start, k=k)
    return ex, m, open_store(tmp_path, name)


# ------------------------------------------------------------------------------------------------ against the batch code
def test_the_tick_finds_exactly_the_trades_of_the_studys_batch_code(tmp_path):
    ex, m, st = world(tmp_path)
    a = series_arrays("BTC", "1h")
    S = ZF.signals_from_arrays(a["o"], a["h"], a["l"], a["c"], a["v"])
    want, _ = SM.simulate(S["chosen"]["ZF_MAIN"], a["o"], a["h"], a["l"], a["c"], SM.cost_for("1h"), 1000, len(a["c"]) - 1)
    assert len(want) == 6
    st, out = ticks(st, ex, m, ALL)
    got = st.trades(m.member_id)
    assert len(got) == len(want) and all(g["status"] == "closed" for g in got)
    for g, w in zip(got, want):
        assert g["signal_ms"] == T0 + w["signal_idx"] * HOUR and g["entry_ms"] == T0 + w["entry_idx"] * HOUR
        assert g["exit_ms"] == T0 + w["exit_idx"] * HOUR
        for k, wk in (("entry_px", "entry_px"), ("stop_px", "stop_px"), ("target_px", "target_px"), ("exit_px", "exit_px"),
                      ("net", "net"), ("gross", "gross"), ("gross_raw", "gross_raw"), ("fee", "fee"), ("funding", "funding"),
                      ("mae", "mae"), ("mfe", "mfe"), ("sl_dist", "sl_dist"), ("tp_dist", "tp_dist")):
            assert g[k] == w[wk], (k, g[k], w[wk])                 # bit for bit: the same floats, not 'close'
        assert (g["reason"], g["hold"], g["side"]) == (w["reason"], w["hold"], w["side"])
    # every signal the batch code chose is in the table, with its plan
    sig = {s["bar_ms"]: s for s in (dict(r) for r in st.conn.execute("SELECT * FROM signals"))}
    for r, x in S["chosen"]["ZF_MAIN"].items():
        if r >= 1000:
            s = sig[T0 + r * HOUR]
            assert (s["stop"], s["target"], s["touches"], s["side"]) == (x["stop"], x["target"], x["n_touch"], x["side"])
            assert s["status"] in ("taken", "busy") and s["plan_entry"] == x["ref"]
    assert sum(1 for s in sig.values() if s["status"] == "taken") == 6


def test_tables_hold_what_the_dashboard_needs(tmp_path):
    ex, m, st = world(tmp_path)
    st, _ = ticks(st, ex, m, ALL)
    t = st.trades(m.member_id)[0]
    assert t["gross"] is not None and t["net"] == pytest.approx(t["gross"] - t["fee"] - t["funding"])
    assert t["acct_taken"] in (0, 1) and t["acct_equity"] is not None
    clones = st.clones_of(m.member_id)
    assert len(clones) == 6 * 10 and all(c["status"] in ("pending", "closed") for c in clones)
    ad = st.conn.execute("SELECT * FROM account_daily WHERE scope = 'all' ORDER BY day_ms").fetchall()
    assert ad and ad[0]["day_ms"] % AC.DAY_MS == 0 and ad[0]["equity"] > 0
    f = st.feed("BTC", "1h")
    assert f["state"] == "ok" and f["n_ingested"] == 4000 and f["first_bar_ms"] == T0 and f["holes"] == 0
    assert st.get_meta("last_tick")["errors"] == []


# ------------------------------------------------------------------------------------------------ restart, gap, double tick
def _scenario(tmp_path, name, idxs, reopen=False, tf="1h", start=START, k=10):
    ex, m, st = world(tmp_path, tf=tf, start=start, name=name, k=k)
    st, _ = ticks(st, ex, m, idxs, tf=tf, reopen=reopen)
    return dump(st), st


def test_one_bar_ticks_a_restart_every_few_ticks_a_gap_and_one_late_tick_make_the_same_tables(tmp_path):
    base, _ = _scenario(tmp_path, "a.db", range(1240, 1540))                      # a tick after every bar
    assert base["trades"] and base["clones"] and base["signals"]
    runs = {"restart": _scenario(tmp_path, "b.db", range(1240, 1540), reopen=True)[0],
            "every 37 bars": _scenario(tmp_path, "c.db", list(range(1240, 1540, 37)) + [1539], reopen=True)[0],
            "a long gap": _scenario(tmp_path, "d.db", [1240, 1241, 1242, 1539])[0],
            "one late tick": _scenario(tmp_path, "e.db", [1539])[0]}
    for name, got in runs.items():
        for t in TABLES:
            assert got[t] == base[t], f"{name}: table {t} differs"


def test_a_late_catch_up_of_thousands_of_bars_gives_every_clone_the_entry_bar_it_drew(tmp_path):
    """One late pass moves the cursor far past the early trades; the bars older than the retention window are then pruned.
    The clones of those trades (entering up to 5 days BEFORE the trade) must still be simulated on the bars they chose,
    never on the oldest bar that happens to be left: the tables equal those of a run that ticked all along."""
    a_tbl, a_st = _scenario(tmp_path, "inc.db", list(range(1099, 3999, 25)) + [3999], k=20)
    b_tbl, b_st = _scenario(tmp_path, "late.db", [3999, 3999, 3999], k=20)
    assert a_tbl["clones"] and a_tbl["trades"]
    for st in (a_st, b_st):
        bad = st.conn.execute("SELECT COUNT(*) FROM clones WHERE entry_ms IS NOT NULL AND entry_ms != target_ms").fetchone()[0]
        assert bad == 0, "a clone was simulated on a bar other than the one it drew"
    for t in ("members", "feeds", "series_state", "signals", "trades", "clones", "account_daily"):
        assert b_tbl[t] == a_tbl[t], t
    assert b_st.get_meta("last_tick")["errors"] == []


def test_a_pending_clone_keeps_its_entry_bar_through_the_pruning_and_a_lost_one_is_reported_not_guessed(tmp_path):
    ex, m, st = world(tmp_path, k=10)
    st, _ = ticks(st, ex, m, [1239, 1539])
    n_bars = st.conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    pend = [c["target_ms"] for c in st.clones_of(m.member_id) if c["status"] == "pending"]
    assert pend and st.oldest_pending_clone_ms(m.member_id, "BTC", "1h") == min(pend)
    assert st.oldest_pending_clone_ms(m.member_id, "ETH", "1h") is None and st.oldest_pending_clone_ms("nobody", "BTC", "1h") is None
    # a clone far in the past of everything stored cannot be simulated: it says so and stays pending
    cl = CL.make_clones(m.member_id, {"trade_id": "x", "coin": "BTC", "tf": "1h", "side": 1, "entry_ms": T0 + 5 * HOUR,
                                      "sl_dist": 0.01, "tp_dist": 0.03}, HOUR, T0, T0, 3, 5)
    st.conn.execute("DELETE FROM bars WHERE t_ms < ?", (T0 + 400 * HOUR,))
    st.add_clones(cl)
    problems: list = []
    LG.League(st, (m,), ex.get)._resolve_clones(m, ex.now_ms, problems)
    assert problems and "no longer stored" in problems[0]
    assert {r["status"] for r in st.conn.execute("SELECT status FROM clones WHERE trade_id = 'x'")} == {"pending"}
    assert n_bars > 0


class ScriptedDetector:
    """A detector that reports given long signals (bar number -> stop, target) on flat bars whose volume is the bar number
    plus one: pins the ENGINE's rules (one position per coin and timeframe, entry at the next open, skips) without any
    price pattern to depend on."""
    id = "scripted_v1"
    min_bars = 300

    def __init__(self, plan):
        self.plan = dict(plan)

    def params(self):
        return {"plan": {str(k): list(v) for k, v in sorted(self.plan.items())}}

    def detect(self, o, h, l, c, v, atr, first_r):
        out = []
        number = {int(x) - 1: i for i, x in enumerate(v)}          # the volume of bar k is k + 1: its number survives pruning
        for k, (stop, target) in sorted(self.plan.items()):
            r = number.get(k)
            if r is not None and first_r <= r < len(c):
                out.append({"r": r, "b": r - 2, "side": 1, "ref": float(c[r]), "stop": stop, "target": target, "rr": 3.0,
                            "touches": 3, "atr": 1.0, "skip": "", "chosen": True,
                            "extra": {"zone_lo": 98.0, "zone_hi": 99.0, "tz_lo": 103.0, "tz_hi": 104.0}})
        return out


def _flat_world(tmp_path, name):
    n = 1400
    a = {"o": np.full(n, 100.0), "h": np.full(n, 100.1), "l": np.full(n, 99.9), "c": np.full(n, 100.0),
         "v": np.arange(1.0, n + 1)}
    a["h"][1013] = 103.5                       # target 103 of the first trade
    a["l"][1030] = 98.5                        # stop 99 of the second trade
    a["o"][1032], a["l"][1032] = 98.0, 97.9    # this bar opens below the stop of the signal before it
    a["h"][1040] = 101.5                       # target 101 of the fourth trade
    ex = FakeExchange(coins=("BTC",), tfs=("1h",), arrays={("BTC", "1h"): a})
    plan = {900: (99.0, 103.0),                            # before the member's start date (bar 1000): never recorded
            1010: (99.0, 103.0), 1013: (99.0, 103.0), 1014: (99.0, 104.0), 1016: (99.0, 104.0), 1030: (99.0, 104.0),
            1031: (99.0, 104.0), 1033: (99.0, 101.0), 1389: (99.0, 104.0),
            1050: (100.0 * (1.0 + SM.SLIP_SIDE), 104.0),        # the stop is exactly where the entry fills: no room, no trade
            1052: (99.0, 100.0 * (1.0 + SM.SLIP_SIDE)),         # the target is exactly where the entry fills
            1100: (90.0, 110.0)}                                # neither is ever touched: the 48th bar closes it
    m = LG.Member(member_id="scripted", name_ko="시험", detector=ScriptedDetector(plan), start_ms=START, tfs=("1h",),
                  coins=("BTC",), clones_k=5)
    return ex, m, open_store(tmp_path, name)


EXPECTED_STATUS = {1010: "taken", 1013: "busy", 1014: "taken", 1016: "busy", 1030: "busy", 1031: "skip_entry",
                   1033: "taken", 1050: "skip_entry", 1052: "skip_entry", 1100: "taken", 1389: "taken"}


@pytest.mark.parametrize("idxs", [list(range(1005, 1400)), [1399], [1100, 1250, 1389, 1399], [1389, 1390, 1399]])
def test_the_engine_takes_one_position_per_series_and_skips_busy_and_gapped_entries(tmp_path, idxs):
    """A signal on the exit bar of the open trade, or while it is open, is skipped (the study's rule: bars <= the previous
    exit bar); the next bar after the exit may trade; an open already beyond the stop is skipped and leaves the series
    flat; a signal on the newest bar waits for its entry bar. The same whatever the tick pattern."""
    ex, m, st = _flat_world(tmp_path, "scripted.db")
    st, out = ticks(st, ex, m, idxs)
    sig = {(s["bar_ms"] - T0) // HOUR: s["status"] for s in (dict(r) for r in st.conn.execute("SELECT * FROM signals"))}
    assert sig == EXPECTED_STATUS, sig
    tr = {(t["signal_ms"] - T0) // HOUR: t for t in st.trades(m.member_id)}
    assert sorted(tr) == [1010, 1014, 1033, 1100, 1389]
    assert (tr[1010]["reason"], (tr[1010]["exit_ms"] - T0) // HOUR, tr[1010]["hold"]) == ("TP", 1013, 3)
    assert (tr[1014]["reason"], (tr[1014]["exit_ms"] - T0) // HOUR, tr[1014]["entry_px"]) == ("SL", 1030, 100.0 * (1 + SM.SLIP_SIDE))
    assert (tr[1033]["reason"], (tr[1033]["exit_ms"] - T0) // HOUR) == ("TP", 1040)
    # the time exit: the close of the 48th bar (entry bar included), with slippage, never one bar early whatever the tick pattern
    t = tr[1100]
    assert (t["reason"], t["hold"], t["entry_ms"], (t["exit_ms"] - T0) // HOUR) == ("TIME", 48, T0 + 1101 * HOUR, 1148)
    assert t["exit_px"] == 100.0 * (1.0 - SM.SLIP_SIDE)
    assert t["net"] == pytest.approx(t["exit_px"] / t["entry_px"] - 1 - 2 * SM.FEE_SIDE - SM.FUNDING_8H * 48 * 60 / 480)
    assert tr[1389]["status"] == "open" and tr[1389]["entry_ms"] == T0 + 1390 * HOUR     # entered at the next bar's open
    assert tr[1010]["net"] == pytest.approx(103.0 / (100.0 * (1 + SM.SLIP_SIDE)) - 1 - 2 * SM.FEE_SIDE - SM.FUNDING_8H * 3 * 60 / 480)


def test_a_member_added_after_its_start_dates_bars_were_dropped_says_so_instead_of_starting_late(tmp_path):
    """A second member whose start date is older than the oldest bar the league still holds (the first member's retention
    window moved on) must not quietly begin at the oldest stored bar: that would be another record under the same start."""
    ex, a, st = world(tmp_path)
    st, _ = ticks(st, ex, a, [3999, 3999, 3999])                      # the first member has processed everything; old bars are pruned
    first = st.load_bars("BTC", "1h")["t"][0]
    assert first > T0 + 1500 * HOUR
    late = make_member(member_id="late", start_ms=T0 + 1200 * HOUR, k=5)              # start date before the oldest stored bar
    fresh = make_member(member_id="fresh", start_ms=int(first) + 400 * HOUR, k=5)      # start date inside the stored bars
    ex.now_ms = now_after_bar("1h", 3999)
    out = LG.League(st, (a, late, fresh), ex.get).tick(ex.now_ms)
    s = st.series("late", "BTC", "1h")
    assert s["status"] == "error" and "시작일" in s["note"] and s["last_bar_ms"] is None
    assert not [r for r in st.conn.execute("SELECT 1 FROM signals WHERE member_id = 'late'")]
    assert st.series("fresh", "BTC", "1h")["status"] == "recording" and st.series(a.member_id, "BTC", "1h")["status"] == "recording"
    assert out["errors"] == []                                        # a per-series state, not a crash of the pass


def test_irregular_ticks_of_15_minute_bars_with_5_to_10_minute_gaps_make_the_same_tables(tmp_path):
    """A pass that is a few minutes late sees the same closed bars; a pass that was missed sees two bars at once."""
    start = T0 + 1000 * 15 * MIN
    tf = "15m"
    idx = list(range(1240, 1560))
    base, _ = _scenario(tmp_path, "a.db", idx, tf=tf, start=start)
    rng = np.random.default_rng(7)
    ex, m, st = world(tmp_path, tf=tf, start=start, name="b.db")
    now = now_after_bar(tf, 1240)
    end = now_after_bar(tf, 1559)
    while now < end:
        ex.now_ms = now
        out = LG.League(st, (m,), ex.get).tick(now)
        assert not out["errors"]
        now += int(rng.choice([6, 10, 15, 15, 22, 31, 40])) * MIN              # late by 5-10 minutes, or a missed pass
    ex.now_ms = end
    LG.League(st, (m,), ex.get).tick(end)
    got = dump(st)
    assert base["trades"], "the window must contain a trade"
    for t in TABLES:
        assert got[t] == base[t], t


def test_a_second_tick_of_the_same_bars_changes_nothing(tmp_path):
    ex, m, st = world(tmp_path)
    st, _ = ticks(st, ex, m, range(1099, 1600, 100))
    before, n_req = dump(st), len(ex.requests)
    out = LG.League(st, (m,), ex.get).tick(ex.now_ms)
    out2 = LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert (out["bars_added"], out["signals"], out["opened"], out["closed"]) == (0, 0, 0, 0)
    assert (out2["bars_added"], out2["signals"], out2["opened"], out2["closed"]) == (0, 0, 0, 0)
    assert dump(st) == before and len(ex.requests) == n_req                    # not even a request: no bar was due


def test_a_crash_inside_a_chunk_leaves_nothing_half_written(tmp_path, monkeypatch):
    ex, m, st = world(tmp_path)
    st, _ = ticks(st, ex, m, [1239])
    before = dump(st)
    calls = {"n": 0}
    real = st.add_trade

    def broken(row):
        calls["n"] += 1
        raise RuntimeError("disk full")
    monkeypatch.setattr(st, "add_trade", broken)
    ex.now_ms = now_after_bar("1h", 1539)
    out = LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert calls["n"] >= 1 and out["errors"] and "disk full" in out["errors"][0]
    after = dump(st, ("signals", "trades", "clones"))
    assert after["signals"] == before["signals"] and after["trades"] == before["trades"]      # the chunk rolled back
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "error" and "disk full" in s["note"]                                  # and says so
    monkeypatch.setattr(st, "add_trade", real)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)                                                  # the next pass redoes it
    full, _ = _scenario(tmp_path, "full.db", [1239, 1539])
    for t in ("signals", "trades", "clones"):
        assert dump(st, (t,))[t] == full[t]


# ------------------------------------------------------------------------------------------------ the feed
def test_a_new_request_is_made_only_when_a_new_bar_has_closed(tmp_path):
    ex, m, st = world(tmp_path)
    ex.now_ms = now_after_bar("1h", 1099)
    lg = LG.League(st, (m,), ex.get)
    lg.tick(ex.now_ms)
    first = len(ex.requests)
    assert first >= 1
    for minutes in (5, 15, 30, 45):                          # the same hour: bar 1100 is still forming
        ex.now_ms = now_after_bar("1h", 1099) + minutes * MIN
        lg.tick(ex.now_ms)
    assert len(ex.requests) == first
    ex.now_ms = now_after_bar("1h", 1100)
    lg.tick(ex.now_ms)
    assert len(ex.requests) == first + 1
    r = ex.requests[-1]
    assert r["start"] == T0 + 1100 * HOUR and r["end"] == T0 + 1100 * HOUR and r["limit"] == 1
    assert r["end"] <= ex.now_ms - FD.SETTLE_MS - HOUR + 1       # never asks for a bar that is not settled and closed


def test_a_bar_that_closed_a_moment_ago_waits_for_the_settle_time(tmp_path):
    assert FD.SETTLE_MS == 20_000                                # the live feed's rule (and the docs): 20 seconds
    ex, m, st = world(tmp_path)
    ex.now_ms = T0 + 1100 * HOUR + FD.SETTLE_MS - 1_000          # bar 1099 closed 19 s ago
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert st.feed("BTC", "1h")["last_bar_ms"] == T0 + 1098 * HOUR
    ex.now_ms += 2_000
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert st.feed("BTC", "1h")["last_bar_ms"] == T0 + 1099 * HOUR


def test_a_bar_that_is_still_forming_is_never_stored_even_if_the_exchange_sends_it(tmp_path):
    """The request ends at the newest settled bar, but an answer that carries the forming bar anyway (or a bar that closed
    a moment ago) must not be kept: a stored bar is final."""
    ex, m, st = world(tmp_path)
    ex.now_ms = now_after_bar("1h", 1099)

    def greedy(url):
        rows = ex.get(url)
        t = T0 + 1100 * HOUR                                       # the bar that opened a few minutes ago and is half done
        rows.append([t, "1.0", "9.0", "0.5", "7.0", "3", t + HOUR - 1, "0", 0, "0", "0", "0"])
        t2 = T0 + 1099 * HOUR + 1                                  # an hour-grid violation as well
        rows.append([t2, "1.0", "2.0", "0.5", "1.5", "3", t2 + HOUR - 1, "0", 0, "0", "0", "0"])
        return rows
    LG.League(st, (m,), greedy).tick(ex.now_ms)
    bars = st.load_bars("BTC", "1h")
    assert int(bars["t"][-1]) == T0 + 1099 * HOUR and 9.0 not in bars["h"]
    f = st.feed("BTC", "1h")
    assert f["last_bar_ms"] == T0 + 1099 * HOUR


def test_the_first_tick_fetches_the_history_before_the_start_date(tmp_path):
    ex, m, st = world(tmp_path)
    ex.now_ms = now_after_bar("1h", 1099)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert [(r["start"], r["limit"]) for r in ex.requests] == [(T0, 1100)]       # HISTORY_BARS (1000) before the start, then to now
    assert st.series(m.member_id, "BTC", "1h")["status"] == "recording"
    assert FD.anchor_ms(START, "1h") == T0


def test_a_failing_feed_is_an_error_with_its_reason_never_nothing(tmp_path):
    ex, m, st = world(tmp_path)
    ex.fail = 99
    ex.now_ms = now_after_bar("1h", 1099)
    lg = LG.League(st, (m,), ex.get)
    lg.tick(ex.now_ms)
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "error" and "TimeoutError" in s["note"] and s["last_bar_ms"] is None
    f = st.feed("BTC", "1h")
    assert f["state"] == "error" and "TimeoutError" in f["error"] and f["error_count"] == 1
    n = len(ex.requests)
    lg.tick(ex.now_ms + MIN)                                   # inside the back-off: no second request
    assert len(ex.requests) == n
    ex.fail = 0
    ex.now_ms += FD.BACKOFF_MS + 1_000
    lg.tick(ex.now_ms)
    assert st.series(m.member_id, "BTC", "1h")["status"] == "recording" and st.feed("BTC", "1h")["state"] == "ok"
    assert st.feed("BTC", "1h")["error"] is None


def test_a_series_that_fell_behind_while_the_feed_failed_reads_error_then_catches_up(tmp_path):
    ex, m, st = world(tmp_path)
    st, _ = ticks(st, ex, m, [1239])
    ex.fail = 99
    ex.now_ms = now_after_bar("1h", 1250)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "error" and "늦음" in s["note"] and s["last_bar_ms"] == T0 + 1239 * HOUR
    ex.fail = 0
    ex.now_ms = now_after_bar("1h", 1539)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "recording" and s["last_bar_ms"] == T0 + 1539 * HOUR
    full, _ = _scenario(tmp_path, "full.db", [1239, 1539])
    assert dump(st)["trades"] == full["trades"] and dump(st)["bars"] == full["bars"]


def test_a_bad_answer_rejects_the_page_and_says_so(tmp_path):
    ex, m, st = world(tmp_path)
    ex.garbage = True
    ex.now_ms = now_after_bar("1h", 1099)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert st.feed("BTC", "1h")["state"] == "error" and st.load_bars("BTC", "1h")["t"].size == 0
    # the exchange sends a bar off the grid
    ex2, m2, st2 = world(tmp_path, name="two.db")
    orig = ex2.get

    def off_grid(url):
        rows = orig(url)
        rows[3][0] += 1_000
        return rows
    ex2.now_ms = now_after_bar("1h", 1099)
    LG.League(st2, (m2,), off_grid).tick(ex2.now_ms)
    f = st2.feed("BTC", "1h")
    assert f["state"] == "error" and "grid" in f["error"] and st2.load_bars("BTC", "1h")["t"].size == 0


def test_no_price_source_is_an_error_not_an_empty_record(tmp_path):
    ex, m, st = world(tmp_path)
    out = LG.League(st, (m,), None).tick(now_after_bar("1h", 1099))
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "error" and "no price source" in s["note"]
    assert st.trades(m.member_id) == [] and out["bars_added"] == 0


def test_bars_with_no_trades_are_dropped_like_the_study_and_counted_as_a_hole(tmp_path):
    ex, m, st = world(tmp_path)
    ex.data[("BTC", "1h")]["v"][500] = 0.0
    ex.now_ms = now_after_bar("1h", 1099)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    f = st.feed("BTC", "1h")
    assert f["n_ingested"] == 1099 and f["holes"] == 1
    assert T0 + 500 * HOUR not in set(st.load_bars("BTC", "1h")["t"].tolist())


def test_old_bars_are_pruned_but_never_ahead_of_the_cursor(tmp_path):
    ex, m, st = world(tmp_path)
    st, _ = ticks(st, ex, m, list(range(1099, 3999, 300)) + [3999])
    t = st.load_bars("BTC", "1h")["t"]
    assert len(t) == ST.KEEP_BARS + 1 and t[-1] == T0 + 3999 * HOUR and t[0] == T0 + (3999 - ST.KEEP_BARS) * HOUR
    assert st.feed("BTC", "1h")["n_ingested"] == 4000          # the count of bars ever held does not shrink


# ------------------------------------------------------------------------------------------------ warming up and waiting
def test_too_short_a_history_says_warming_up_and_makes_no_signal(tmp_path):
    ex = FakeExchange(coins=("BTC",), tfs=("1h",), arrays={("BTC", "1h"): {k: v[:150] for k, v in series_arrays("BTC", "1h").items()}})
    m = make_member(start_ms=T0 + 100 * HOUR)
    st = open_store(tmp_path)
    ex.now_ms = now_after_bar("1h", 149)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    s = st.series(m.member_id, "BTC", "1h")
    assert (s["status"], s["warm_have"], s["warm_need"]) == ("warming", 150, 300)
    assert s["note"] == "워밍업 중 (150봉 더 필요)" and s["last_bar_ms"] is None
    assert st.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0


def test_warming_ends_when_enough_bars_exist_and_the_first_signals_come_after(tmp_path):
    arr = {k: v[:700] for k, v in series_arrays("BTC", "1h").items()}
    ex = FakeExchange(coins=("BTC",), tfs=("1h",), arrays={("BTC", "1h"): arr})
    m = make_member(start_ms=T0 + 100 * HOUR)
    st = open_store(tmp_path)
    ex.now_ms = now_after_bar("1h", 249)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert st.series(m.member_id, "BTC", "1h")["status"] == "warming"
    ex.now_ms = now_after_bar("1h", 699)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "recording" and s["last_bar_ms"] == T0 + 699 * HOUR
    first = [r[0] for r in st.conn.execute("SELECT bar_ms FROM signals ORDER BY bar_ms")]
    assert all(x >= T0 + 300 * HOUR for x in first)             # never a signal on fewer than 300 bars of history


def test_before_the_start_date_it_only_collects_bars(tmp_path):
    ex, m, st = world(tmp_path)
    ex.now_ms = now_after_bar("1h", 899)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "waiting" and "시작일 전" in s["note"] and s["last_bar_ms"] is None
    assert st.feed("BTC", "1h")["n_ingested"] == 900
    ex.now_ms = now_after_bar("1h", 1001)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    assert st.series(m.member_id, "BTC", "1h")["status"] == "recording"


def test_a_start_date_far_ahead_is_waiting_not_warming_and_asks_for_nothing(tmp_path):
    ex, m, st = world(tmp_path, start=T0 + 3500 * HOUR)             # its history would begin at bar 2500; now is bar 100
    ex.now_ms = now_after_bar("1h", 100)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    s = st.series(m.member_id, "BTC", "1h")
    assert s["status"] == "waiting" and "시작일 전" in s["note"] and ex.requests == []


# ------------------------------------------------------------------------------------------------ several coins and timeframes
def test_several_coins_and_timeframes_are_followed_independently(tmp_path):
    coins, tfs = ("BTC", "ETH"), ("1h", "4h")
    ex = FakeExchange(coins=coins, tfs=tfs)
    m = make_member(coins=coins, tfs=tfs, start_ms=T0 + 1000 * 4 * HOUR, k=5)
    st = open_store(tmp_path)
    for i in range(1100, 3999, 400):
        ex.now_ms = now_after_bar("1h", i * 4 + 3) if False else T0 + (i + 1) * 4 * HOUR + FD.SETTLE_MS + 5_000
        out = LG.League(st, (m,), ex.get).tick(ex.now_ms)
        assert not out["errors"]
    rows = {(s["coin"], s["tf"]): s for s in st.series_rows(m.member_id)}
    assert set(rows) == {(c, tf) for c in coins for tf in tfs}
    assert {r["status"] for r in rows.values()} <= {"recording", "waiting"}
    assert len(ex.requests_for("BTC", "4h")) >= 1 and len(ex.requests_for("ETH", "1h")) >= 1


# ------------------------------------------------------------------------------------------------ clones
def test_clones_are_the_same_whenever_they_are_made(tmp_path):
    a = CL.draw_offsets("zoneflip|BTC|1h|100|1|90|1.5", 120, 50, -1000)
    b = CL.draw_offsets("zoneflip|BTC|1h|100|1|90|1.5", 120, 50, -1000)
    c = CL.draw_offsets("zoneflip|BTC|1h|101|1|90|1.5", 120, 50, -1000)
    assert a == b and a != c and len(a) == 50
    assert all(x != 0 and -120 <= x <= 120 for x in a)
    assert CL.seed_parts("x")[0] == CL.SEED == 20261006
    assert all(x >= -7 for x in CL.draw_offsets("t", 120, 50, -7))                  # never before the series' first bar
    assert CL.window_bars(HOUR) == 120 and CL.window_bars(15 * MIN) == 480 and CL.window_bars(4 * HOUR) == 30


def test_the_clone_draw_depends_on_the_trade_id_alone_not_on_the_clock_or_global_random_state(monkeypatch):
    """The same id gives the same draw on any machine at any time (golden values pin the algorithm: a silent change would
    make new clones differ from the ones already in the database)."""
    import time
    import numpy as np
    tid = "zoneflip|BTC|1h|100|1|90|1.5"
    assert CL.seed_parts(tid) == [20261006, 4021001553, 2154804604]
    assert CL.draw_offsets(tid, 120, 8, -1000) == [96, -79, -110, -18, 33, -28, -119, 107]
    assert CL.draw_offsets("t", 480, 5, -7) == [125, 447, 41, 225, 61]
    monkeypatch.setattr(time, "time", lambda: 4_000_000_000.0)
    monkeypatch.setattr(time, "monotonic", lambda: 12345.0)
    np.random.seed(99)
    assert CL.draw_offsets(tid, 120, 8, -1000) == [96, -79, -110, -18, 33, -28, -119, 107]


def test_every_trade_has_k_clones_with_its_own_distances_and_the_study_s_exit(tmp_path):
    ex, m, st = world(tmp_path, k=50)
    st, _ = ticks(st, ex, m, ALL)
    a = series_arrays("BTC", "1h")
    cost = m.trade.cost("1h")
    for t in st.trades(m.member_id):
        cl = [c for c in st.clones_of(m.member_id) if c["trade_id"] == t["trade_id"]]
        assert len(cl) == 50 and sorted(c["k"] for c in cl) == list(range(50))
        for c in cl:
            assert c["offset_bars"] != 0 and abs(c["offset_bars"]) <= 120 and c["tf"] == "1h" and c["coin"] == "BTC"
            assert (c["side"], c["sl_dist"], c["tp_dist"]) == (t["side"], t["sl_dist"], t["tp_dist"])
            assert c["target_ms"] == t["entry_ms"] + c["offset_bars"] * HOUR and c["target_ms"] >= T0
        done = [c for c in cl if c["status"] == "closed"]
        assert done
        for c in done[:6]:                                      # the same exit as the study's coin flips, bit for bit
            e = (c["target_ms"] - T0) // HOUR
            side = c["side"]
            entry = a["o"][e] * (1.0 + side * cost.slip_side)
            net = SM.exit_fixed_batch(np.array([side]), np.array([e]), np.array([entry]),
                                      np.array([entry * (1.0 - side * c["sl_dist"])]),
                                      np.array([entry * (1.0 + side * c["tp_dist"])]), a["o"], a["h"], a["l"], a["c"], cost)[0]
            assert c["net"] == net and c["entry_ms"] == c["target_ms"]


def test_a_clone_that_enters_after_the_real_trade_waits_and_never_reads_future_bars(tmp_path):
    ex, m, st = world(tmp_path, k=50)
    st, _ = ticks(st, ex, m, [1259])                            # the signal at bar 1252 entered at 1253 and closed at 1256
    assert len(st.trades(m.member_id)) == 1
    cl = list(st.clones_of(m.member_id))
    future = [c for c in cl if c["target_ms"] > T0 + 1259 * HOUR]
    assert future and all(c["status"] == "pending" and c["entry_ms"] is None for c in future)
    assert all(c["status"] == "closed" for c in cl if c["target_ms"] + 48 * HOUR <= T0 + 1259 * HOUR)
    snap = {c["clone_id"]: c for c in cl if c["status"] == "closed"}
    st, _ = ticks(st, ex, m, [1300, 1400, 1539])
    later = {c["clone_id"]: c for c in st.clones_of(m.member_id)}
    for cid, c in snap.items():                                 # a decided clone never changes
        for k in ("entry_ms", "entry_px", "exit_ms", "exit_px", "reason", "net", "hold"):
            assert later[cid][k] == c[k]
    assert all(later[c["clone_id"]]["status"] == "closed" for c in future if c["target_ms"] + 48 * HOUR <= T0 + 1539 * HOUR)
    full, _ = _scenario(tmp_path, "full.db", [1539], k=50)
    assert dump(st, ("clones",)) == {"clones": full["clones"]}


# ------------------------------------------------------------------------------------------------ definitions and wall time
def test_a_changed_definition_stops_that_member_instead_of_mixing_rules(tmp_path):
    ex, m, st = world(tmp_path)
    ex.now_ms = now_after_bar("1h", 1099)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    other = make_member(start_ms=START, k=11)                   # same id, another definition (k clones)
    out = LG.League(st, (other,), ex.get).tick(now_after_bar("1h", 1199))
    assert "정의가" in out["members"][m.member_id]["halted"]
    assert "정의가" in st.member(m.member_id)["halted"]
    assert st.series(m.member_id, "BTC", "1h")["last_bar_ms"] == T0 + 1099 * HOUR       # nothing was processed
    LG.League(st, (m,), ex.get).tick(now_after_bar("1h", 1199))
    assert st.member(m.member_id)["halted"] is None


class StepClock:
    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def test_a_tick_that_runs_out_of_time_stops_and_the_next_one_finishes_the_rest(tmp_path):
    coins = ("BTC", "ETH", "SOL")
    ex = FakeExchange(coins=coins, tfs=("1h",))
    m = make_member(coins=coins, start_ms=START, k=4)
    st = open_store(tmp_path, "slow.db")
    ex.now_ms = now_after_bar("1h", 1539)
    out = LG.League(st, (m,), ex.get, clock=StepClock(6.0)).tick(ex.now_ms, work_s=14.0, hard_s=20.0)
    assert out["timed_out"] and out["behind"] >= 1
    assert {s["coin"]: s["status"] for s in st.series_rows(m.member_id)} == {"BTC": "recording"}   # ETH and SOL wait
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    rows = {s["coin"]: s for s in st.series_rows(m.member_id)}
    assert all(r["status"] == "recording" and r["last_bar_ms"] == T0 + 1539 * HOUR for r in rows.values())
    ex2 = FakeExchange(coins=coins, tfs=("1h",))
    st2 = open_store(tmp_path, "fast.db")
    ex2.now_ms = ex.now_ms
    LG.League(st2, (m,), ex2.get).tick(ex2.now_ms)
    assert dump(st) == dump(st2)


def test_no_request_starts_when_it_could_end_after_the_hard_cap(tmp_path):
    ex, m, st = world(tmp_path)
    ex.now_ms = now_after_bar("1h", 1099)
    clock = StepClock(0.0)
    clock.t = 19.0
    r = FD.sync_series(st, "BTC", "1h", ex.get, ex.now_ms, FD.anchor_ms(START, "1h"), deadline_at=20.0, clock=clock)
    assert r["state"] == "budget" and ex.requests == []         # 19 s + 6.5 s > 20 s: not started


# ------------------------------------------------------------------------------------------------ migrations
OLD_SCHEMA_V1 = ST.V1


def test_a_database_of_an_earlier_schema_is_brought_forward_without_losing_a_row(tmp_path):
    path = os.path.join(str(tmp_path), "old.db")
    c = sqlite3.connect(path)
    c.executescript(OLD_SCHEMA_V1)                                # what the first release created: no clones, no account
    c.execute("INSERT INTO league_meta VALUES ('schema_version', '1')")
    c.execute("INSERT INTO members (member_id, name_ko, detector, spec_json, spec_sha256, start_ms, created_ms) "
              "VALUES ('zoneflip', '옛 멤버', 'zoneflip_v1', '{}', 'abc', 1, 2)")
    c.execute("INSERT INTO trades (trade_id, member_id, coin, tf, side, signal_ms, entry_ms, entry_px, stop_px, target_px, "
              "sl_dist, tp_dist, status, recorded_ms) VALUES ('t1', 'zoneflip', 'BTC', '1h', 1, 1, 2, 100, 99, 105, 0.01, 0.05, 'open', 3)")
    c.commit()
    assert not any(r[1] == "acct_taken" for r in c.execute("PRAGMA table_info(trades)"))
    c.close()
    st = ST.Store(path)
    assert st.version == 2 == ST.SCHEMA_VERSION
    assert [r[1] for r in st.conn.execute("PRAGMA table_info(trades)") if r[1].startswith("acct_")] == [
        "acct_taken", "acct_ret", "acct_equity", "acct_liq"]
    assert {r[0] for r in st.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {"clones", "account_daily"}
    assert st.member("zoneflip")["name_ko"] == "옛 멤버" and st.trade("t1")["entry_px"] == 100
    assert st.trade("t1")["acct_taken"] is None
    ddl1 = ST.schema_ddl(st.conn)
    st.close()
    st = ST.Store(path)                                           # and again: nothing changes
    assert ST.schema_ddl(st.conn) == ddl1 and st.version == 2


def test_a_file_with_the_tables_but_no_version_row_is_repaired(tmp_path):
    path = os.path.join(str(tmp_path), "half.db")
    st = ST.Store(path)
    st.conn.execute("DELETE FROM league_meta WHERE k = 'schema_version'")
    st.close()
    st = ST.Store(path)
    assert st.version == 2
    assert [r[1] for r in st.conn.execute("PRAGMA table_info(trades)") if r[1] == "acct_taken"]


def test_the_default_path_is_next_to_the_agents_database(tmp_path):
    assert ST.default_path(os.path.join(str(tmp_path), "agents3.db")) == os.path.join(str(tmp_path), "shadow_league.db")


# ------------------------------------------------------------------------------------------------ the owners' account
def _t(i, coin, entry, exit_, net, mae=-0.001, tf="1h"):
    return {"trade_id": i, "coin": coin, "tf": tf, "entry_ms": entry, "exit_ms": exit_, "net": net, "mae": mae}


def test_the_account_follows_the_owners_rules():
    tr = [_t("a", "BTC", 10, 20, 0.02),                        # +2 % at 1x -> +8 % on the account (4x)
          _t("b", "ETH", 15, 30, 0.05),                        # enters before a's exit bar opens: not taken
          _t("c", "ETH", 20, 40, -0.10),                       # enters exactly at a's exit bar: taken; the loss is capped at -20 %
          _t("d", "BTC", 50, 60, 0.01, mae=-0.05),             # a 5 % adverse move: liquidated, costs the margin (20 %)
          _t("e", "SOL", 70, 80, 0.01)]
    res = {r["trade_id"]: r for r in AC.run_account(tr)}
    assert [res[k]["taken"] for k in "abcde"] == [True, False, True, True, True]
    assert res["a"]["ret"] == pytest.approx(0.08) and res["a"]["equity"] == pytest.approx(5400.0)
    assert res["b"]["why"] == "busy" and res["b"]["equity"] is None
    assert res["c"]["ret"] == pytest.approx(-0.20) and res["c"]["equity"] == pytest.approx(5400 * 0.8)
    assert res["d"]["liquidated"] and res["d"]["ret"] == pytest.approx(-0.20)
    assert res["e"]["equity"] == pytest.approx(5400 * 0.8 * 0.8 * 1.04)
    assert AC.OWN_LIQ == pytest.approx(0.045) and AC.OWN_EXPO == 4.0 and AC.OWN_MARGIN == 0.2 and AC.START_EQUITY == 5000.0


def test_an_adverse_move_of_exactly_the_liquidation_level_liquidates_and_a_hair_less_does_not():
    """The study's rule is 'liquidated = -mae >= OWN_LIQ' (research/search/search.py owners_book): equality liquidates."""
    on = AC.run_account([_t("x", "BTC", 10, 20, 0.01, mae=-AC.OWN_LIQ)])[0]
    off = AC.run_account([_t("y", "BTC", 10, 20, 0.01, mae=-(AC.OWN_LIQ - 1e-9))])[0]
    assert on["liquidated"] and on["ret"] == pytest.approx(-AC.OWN_MARGIN)
    assert not off["liquidated"] and off["ret"] == pytest.approx(4 * 0.01)


def test_the_account_exposure_follows_the_members_own_margin_and_leverage():
    a = LG.AccountSpec()
    assert a.exposure == AC.OWN_EXPO == 4.0 and a.margin_frac == AC.OWN_MARGIN and a.leverage == 20
    assert LG.AccountSpec(margin_frac=0.1, leverage=10).exposure == 1.0
    assert "exposure" not in LG.Member.spec(make_member())["account"]          # a property, not part of the stored definition


def test_an_open_taken_trade_blocks_every_later_one_and_is_not_marked_to_market():
    tr = [_t("a", "BTC", 10, 20, 0.02), {"trade_id": "o", "coin": "BTC", "tf": "1h", "entry_ms": 30, "exit_ms": None,
                                         "net": None, "mae": None}, _t("z", "ETH", 99, 120, 0.5)]
    res = {r["trade_id"]: r for r in AC.run_account(tr)}
    assert res["o"]["taken"] and res["o"]["why"] == "open" and res["o"]["equity"] is None
    assert not res["z"]["taken"] and res["z"]["why"] == "busy"


def test_the_account_equals_the_studys_owners_curve_on_real_simulated_trades(tmp_path):
    import pandas as pd
    import shadowleague_original as SO
    if not SO.available():
        pytest.skip("the study's environment cannot be loaded here")
    orig = SO.load_original()
    from paperbot.shadowleague import sim
    rows = []
    for seed, coin in ((10, "BTCUSD"), (1, "ETHUSD"), (24, "SOLUSD")):
        a = series_arrays({"BTCUSD": "BTC", "ETHUSD": "ETH", "SOLUSD": "SOL"}[coin], "1h")
        S = ZF.signals_from_arrays(a["o"], a["h"], a["l"], a["c"], a["v"])
        tr, _ = sim.simulate(S["chosen"]["ZF_CTRL"], a["o"], a["h"], a["l"], a["c"], sim.cost_for("1h"), 400, len(a["c"]) - 1)
        for t in tr:
            rows.append({"entry_ts": pd.Timestamp(T0 + t["entry_idx"] * HOUR, unit="ms"),
                         "exit_ts": pd.Timestamp(T0 + t["exit_idx"] * HOUR, unit="ms"), "net": t["net"], "mae": t["mae"],
                         "symbol": coin})
    df = pd.DataFrame(rows)
    assert len(df) > 20
    study = orig.owners_curve(df)
    mine = AC.run_account([{"trade_id": str(i), "coin": r["symbol"], "tf": "1h", "entry_ms": int(r["entry_ts"].value // 10 ** 6),
                            "exit_ms": int(r["exit_ts"].value // 10 ** 6), "net": r["net"], "mae": r["mae"]}
                           for i, r in df.iterrows()], start_equity=1.0)
    taken = [r for r in mine if r["taken"]]
    assert len(taken) == len(study)
    assert [r["equity"] for r in taken] == pytest.approx(study["equity"].tolist(), abs=1e-12, rel=1e-12)


def test_daily_equity_rows_start_on_the_start_day_and_stop_at_the_processed_time():
    tr = [_t("a", "BTC", AC.DAY_MS + 10, AC.DAY_MS + 20 * HOUR, 0.02), _t("b", "BTC", 3 * AC.DAY_MS, 3 * AC.DAY_MS + HOUR, -0.01)]
    res = AC.run_account(tr)
    rows = AC.daily_equity(tr, res, start_ms=0, asof_ms=3 * AC.DAY_MS + 30 * MIN)
    assert [r["day_ms"] for r in rows] == [0, AC.DAY_MS, 2 * AC.DAY_MS, 3 * AC.DAY_MS]
    assert [round(r["equity"], 2) for r in rows] == [5000.0, 5400.0, 5400.0, 5400.0]       # b is not finished by the cut
    assert rows[-1]["asof_ms"] == 3 * AC.DAY_MS + 30 * MIN and rows[1]["asof_ms"] == 2 * AC.DAY_MS
    assert AC.daily_equity(tr, res, start_ms=10, asof_ms=5) == []
    later = AC.daily_equity(tr, res, start_ms=0, asof_ms=3 * AC.DAY_MS + 3 * HOUR)
    assert round(later[-1]["equity"], 2) == round(5400 * (1 - 0.04), 2) and later[-1]["taken"] == 2


def test_the_account_is_recomputed_from_the_trades_not_accumulated(tmp_path):
    ex, m, st = world(tmp_path)
    st, _ = ticks(st, ex, m, ALL)
    rows = st.conn.execute("SELECT * FROM account_daily WHERE scope = '1h' ORDER BY day_ms").fetchall()
    tr = st.trades(m.member_id)
    res = AC.run_account(tr)
    taken = [r for r in res if r["taken"]]
    assert rows[-1]["equity"] == pytest.approx(taken[-1]["equity"])
    assert rows[-1]["taken"] == len(taken) and rows[0]["day_ms"] == AC.day_start(START)
    per_trade = {t["trade_id"]: t for t in tr}
    for r in res:
        assert per_trade[r["trade_id"]]["acct_taken"] == int(r["taken"])
    # the same table again after more ticks of nothing
    LG.League(st, (m,), ex.get).update_accounts(m)
    assert [dict(x) for x in st.conn.execute("SELECT * FROM account_daily WHERE scope = '1h' ORDER BY day_ms")] == [dict(x) for x in rows]
