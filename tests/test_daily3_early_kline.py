"""daily3: mismatches caused by a 1m kline the live feed read before Binance had folded in the minute's last
trades ("early_kline", option 1 + 3a of the 2026-10-03 parity diagnosis).

A synthetic live day: account A is long BTC. In minute M the final kline reaches A's stop in its last trades, the
kline live stepped on did not (same open, higher low, lower volume). Live then exits later, at the next minute's
open beyond the stop (shape "gap") or at the same stop two minutes later (shape "in_bar"); the replay on final
klines exits in M. Account B (ETH) has a stored trade changed by hand: a real parity problem.
"""

import json
import sqlite3

import pytest

import paperbot.daily3 as D
from paperbot import Bar, Brackets
from paperbot.accounts import AccountBook
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.daily3 import EARLY_KLINE_KO, LIVE_BARS_PARITY_KO, make_signal
from paperbot.fillcost import bar_rows
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
DAY = 86_400_000
S = v3_settings()
BR = {s: Brackets.example() for s in V3_SYMBOLS}
M = 30                     # the trigger minute (index)
N = 60


def _bar(sym, i, o, h, lo, c, vol=10.0):
    return Bar(sym, i * MIN, i * MIN + MIN - 1, o, h, lo, c, o, h, lo, c, volume=vol)


def _flat(sym, i, px=100.0):
    return _bar(sym, i, px, px + 0.05, px - 0.05, px)


def live_world(tmp_path, shape="gap", record=True, twin=None, real=True):
    """(paper3 store, final steps, stop of A). ``twin``: a second BTC account C with A's signal; "bad" changes
    its stored exit reason (a mismatch whose shape is not an early kline)."""
    store = Store3(str(tmp_path / "paper3.db"))
    book = AccountBook(S, BR, store)
    names = ["A", "B"] + (["C"] if twin else [])
    book.open_accounts([{"strategy": k, "timeframe": "15m", "kind": "strategy"} for k in names], 0)
    final_steps = []
    stop = {}
    for i in range(N):
        fin = {s: _flat(s, i) for s in V3_SYMBOLS}
        liv = dict(fin)
        if stop:
            a, b = stop["BTCUSDT"], stop["ETHUSDT"]
            if i == M:      # final: the last trades reach the stop; live's early read did not see them
                fin["BTCUSDT"] = _bar("BTCUSDT", i, 100.0, 100.05, a - 0.03, a - 0.02)
                liv["BTCUSDT"] = _bar("BTCUSDT", i, 100.0, 100.05, a + 0.01, a + 0.02, vol=7.0)
            elif i > M and shape == "gap":
                px = a - 0.04
                fin["BTCUSDT"] = liv["BTCUSDT"] = (_bar("BTCUSDT", i, a - 0.02, a - 0.01, a - 0.06, px)
                                                   if i == M + 1 else _flat("BTCUSDT", i, px))
            elif i > M and shape == "in_bar":
                if i == M + 1:
                    fin["BTCUSDT"] = liv["BTCUSDT"] = _bar("BTCUSDT", i, a + 0.03, a + 0.05, a + 0.01, a + 0.02)
                elif i == M + 2:
                    fin["BTCUSDT"] = liv["BTCUSDT"] = _bar("BTCUSDT", i, a + 0.02, a + 0.04, a - 0.01, a)
                else:
                    fin["BTCUSDT"] = liv["BTCUSDT"] = _flat("BTCUSDT", i, a)
            if i == 40:     # ETH: a plain stop, the same in both
                fin["ETHUSDT"] = liv["ETHUSDT"] = _bar("ETHUSDT", i, 100.0, 100.05, b - 0.5, b - 0.3)
            elif i > 40:
                fin["ETHUSDT"] = liv["ETHUSDT"] = _flat("ETHUSDT", i, b - 0.3)
        book.step(i * MIN, liv, {})
        if record:
            store.fill_costs(bar_rows(i * MIN, liv, i * MIN + MIN + 40))     # what live3's FillProbe call writes
        if i == 14:
            for k, sym in [("A", "BTCUSDT"), ("B", "ETHUSDT")] + ([("C", "BTCUSDT")] if twin else []):
                row = {"bar_close": 15 * MIN, "timeframe": "15m", "strategy": k, "symbol": sym, "side": 1,
                       "atr": 0.2, "ref_price": 100.0, "ref_time": 15 * MIN + 5000, "delay_ms": 5000,
                       "status": "SUBMITTED"}
                store.log_signals([row])
                book.submit(f"{k}@15m", make_signal(row))
        if i == 15:
            stop = {"BTCUSDT": book.engines["A@15m"].position.stop_price,
                    "ETHUSDT": book.engines["B@15m"].position.stop_price}
        book.save(i * MIN)
        final_steps.append((i * MIN, fin, {}))
    if real:
        _edit(store, "B@15m", pnl=lambda t: t["pnl"] + 1.0)
    if twin == "bad":
        _edit(store, "C@15m", exit_reason=lambda t: "TP")
    store.commit()
    return store, final_steps, stop["BTCUSDT"]


def _edit(store, aid, **change):
    rid, data = store.conn.execute("SELECT id, data FROM trades WHERE account_id = ?", (aid,)).fetchone()
    t = json.loads(data)
    for k, f in change.items():
        t[k] = f(t)
    store.conn.execute("UPDATE trades SET data = ? WHERE id = ?", (json.dumps(t), rid))


class Rest:
    """server_time and the public aggTrades endpoint (``trades``: symbol -> [(ms, price)])."""

    def __init__(self, trades=None, limit=None):
        self.trades = {s: [{"a": k + 1, "p": str(p), "q": "1", "T": t} for k, (t, p) in enumerate(sorted(rows))]
                       for s, rows in (trades or {}).items()}
        self.calls = []

    def server_time(self):
        return DAY + 2 * MIN

    def _get(self, path, params):
        assert path == "/fapi/v1/aggTrades"
        self.calls.append(dict(params))
        rows = self.trades.get(params["symbol"], [])
        if "fromId" in params:
            rows = [r for r in rows if r["a"] >= params["fromId"]]
        else:
            rows = [r for r in rows if params["startTime"] <= r["T"] <= params["endTime"]]
        return rows[:params["limit"]]


def minute_trades(stop, at):
    """BTC trades of minute M that rebuild its final kline; the first trade at the stop comes ``at`` ms into it."""
    t0 = M * MIN
    return [(t0 + 100, 100.0), (t0 + 20_000, 100.05), (t0 + 25_000, 100.0), (t0 + at, stop - 0.03),
            (t0 + 59_990, stop - 0.02)]


def run(tmp_path, monkeypatch, store, steps, rest):
    monkeypatch.setattr(D, "fetch_steps", lambda r, syms, a, b: [s for s in steps if a <= s[0] < b])
    out = sqlite3.connect(str(tmp_path / "daily3.db"))
    out.executescript(D.SCHEMA)
    rep = D.run_day(store.conn, out, rest, S, BR, {}, "1970-01-01")
    mm = {aid: json.loads(d) for aid, d in out.execute("SELECT account_id, data FROM mismatches")}
    return rep, mm, out


# ---------------------------------------------------------------------------- (i) live's own bars (option 3a)
@pytest.mark.parametrize("shape", ["gap", "in_bar"])
def test_replay_on_live_bars_removes_an_early_kline_mismatch_and_keeps_a_real_one(tmp_path, monkeypatch, shape):
    store, steps, stop = live_world(tmp_path, shape=shape)
    a = json.loads(store.conn.execute("SELECT data FROM trades WHERE account_id = 'A@15m'").fetchone()[0])
    assert a["exit_time"] == ((M + 1) * MIN if shape == "gap" else (M + 2) * MIN + MIN - 1)   # live: later
    rest = Rest()                                    # live bars cover the minute: no aggTrades request
    rep, mm, _ = run(tmp_path, monkeypatch, store, steps, rest)
    assert rest.calls == []
    par = rep["parity"]
    assert set(mm) == {"A@15m", "B@15m"}
    assert par["mismatched_accounts"] == 1 and par["early_kline"] == 1           # B stays, A is explained
    assert par["live_bars"]["bars"] == N * len(V3_SYMBOLS) and par["live_bars"]["mismatched"] == 1
    assert par["live_bars"]["only_on_live_bars"] == []
    A, B = mm["A@15m"], mm["B@15m"]
    assert A["early_kline"] and A["label"] == EARLY_KLINE_KO
    p = A["proof"]
    assert (p["source"], p["symbol"], p["minute"]) == ("live_bars", "BTCUSDT", M * MIN)
    assert p["live_bar"]["low"] > stop >= p["final_bar"]["low"] and p["live_bar"]["open"] == p["final_bar"]["open"]
    assert p["live_bar"]["volume"] < p["final_bar"]["volume"] and p["processed_ms_after_close"] == 40
    assert not B.get("early_kline") and B["label"] == LIVE_BARS_PARITY_KO and B["live_bars_replay"] == "mismatch"
    assert par["early_kline_events"] == [{"symbol": "BTCUSDT", "minute": M * MIN, "utc": "00:30:00.000",
                                          "source": "live_bars", "accounts": ["A@15m"]}]
    msgs = D.notify_report(rep, ListNotifier())
    assert msgs[0][0] == "CRITICAL" and "계좌 1개" in msgs[0][1] and "그 밖에 1개" in msgs[0][1]
    assert "재계산 일치 0/2 (확정 전 1분봉 1)" in msgs[-1][1]


def test_without_the_real_mismatch_the_day_is_one_warn_and_a_rerun_relabels_cleanly(tmp_path, monkeypatch):
    store, steps, _ = live_world(tmp_path, real=False)
    out = sqlite3.connect(str(tmp_path / "daily3.db"))
    out.executescript(D.SCHEMA)
    # the night before the fix: an unlabelled mismatch row for the day (and one of another day) is in daily3.db
    out.execute("INSERT INTO mismatches VALUES ('1970-01-01', 'A@15m', '{}')")
    out.execute("INSERT INTO mismatches VALUES ('1969-12-31', 'X', '{}')")
    out.commit()
    rep, mm, out = run(tmp_path, monkeypatch, store, steps, Rest())
    assert rep["parity"]["mismatched_accounts"] == 0 and rep["parity"]["early_kline"] == 1
    rows = out.execute("SELECT day, account_id, data FROM mismatches ORDER BY day").fetchall()
    assert [(d, a) for d, a, _ in rows] == [("1969-12-31", "X"), ("1970-01-01", "A@15m")]
    assert json.loads(rows[1][2])["label"] == EARLY_KLINE_KO
    msgs = [m for m in D.notify_report(rep, ListNotifier(), trades_day=2) if "빠진 1분봉:" not in m[1]]
    assert [m[0] for m in msgs] == ["WARN", "INFO"]                       # (the synthetic day is only 60 minutes)
    assert msgs[0][1].startswith("[1970-01-01] 재계산 차이 1개 계좌: 모두 '1분봉을 확정 전에 읽음'으로 확인됨(계산 오류 아님")
    assert msgs[1][1].startswith("[1970-01-01] 매일 점검: 재계산 일치 1/2 (확정 전 1분봉 1) · 거래 2건")


# ---------------------------------------------------------------------------- (ii) the minute's trades (option 1)
@pytest.mark.parametrize("shape", ["gap", "in_bar"])
def test_aggtrades_prove_an_early_kline_when_the_stop_was_reached_in_the_last_ms(tmp_path, monkeypatch, shape):
    store, steps, stop = live_world(tmp_path, shape=shape, record=False)
    rest = Rest({"BTCUSDT": minute_trades(stop, 59_700)})                    # 300 ms before the close
    rep, mm, _ = run(tmp_path, monkeypatch, store, steps, rest)
    A = mm["A@15m"]
    assert A["early_kline"] and A["label"] == EARLY_KLINE_KO
    p = A["proof"]
    assert p["source"] == "aggTrades" and p["trades"]["first_at_stop"]["ms_before_close"] == 300
    assert p["live_exit"]["shape"] == ("open_gap" if shape == "gap" else "in_bar")
    assert all(p["trades"]["rebuilt"][k] == p["trades"]["final"][k] for k in ("open", "high", "low", "close"))
    assert rep["parity"]["early_kline"] == 1 and rep["parity"]["mismatched_accounts"] == 1     # B: no proof
    assert "live_bars" in rep["parity"] and rep["parity"]["live_bars"]["bars"] == 0
    assert not mm["B@15m"].get("early_kline") and mm["B@15m"]["early_kline_check"]["failed"]
    assert {c["symbol"] for c in rest.calls} == {"BTCUSDT", "ETHUSDT"}


def test_aggtrades_paging_by_id(tmp_path, monkeypatch):
    store, steps, stop = live_world(tmp_path, record=False, real=False)
    monkeypatch.setattr(D, "AGG_LIMIT", 2)
    rest = Rest({"BTCUSDT": minute_trades(stop, 59_800)})
    rep, mm, _ = run(tmp_path, monkeypatch, store, steps, rest)
    assert mm["A@15m"]["early_kline"] and mm["A@15m"]["proof"]["trades"]["trades"] == 5
    assert [("fromId" in c) for c in rest.calls] == [False, True, True]


def test_a_stop_reached_mid_minute_stays_unexplained(tmp_path, monkeypatch):
    store, steps, stop = live_world(tmp_path, record=False, real=False)
    rep, mm, _ = run(tmp_path, monkeypatch, store, steps, Rest({"BTCUSDT": minute_trades(stop, 30_000)}))
    A = mm["A@15m"]
    assert not A.get("early_kline") and A["label"] == D.EARLY_SUSPECT_KO       # the shape fits, the proof does not
    assert any("30000 ms before the close" in f for f in A["early_kline_check"]["failed"])
    assert rep["parity"]["mismatched_accounts"] == 1 and "early_kline" not in rep["parity"]
    assert D.notify_report(rep, ListNotifier())[0][0] == "CRITICAL"


def test_a_feed_warning_keeps_it_unexplained(tmp_path, monkeypatch):
    store, steps, stop = live_world(tmp_path, record=False, real=False)
    store.alert(M * MIN + 70_000, "WARN", f"data gap at {M * MIN}: no bar for ['BTCUSDT']")
    store.alert(M * MIN + 71_000, "WARN", "data gap at 1: no bar for ['ETHUSDT']")     # another coin: not counted
    store.commit()
    rep, mm, _ = run(tmp_path, monkeypatch, store, steps, Rest({"BTCUSDT": minute_trades(stop, 59_700)}))
    A = mm["A@15m"]
    assert not A.get("early_kline") and rep["parity"]["mismatched_accounts"] == 1
    assert len(A["early_kline_check"]["feed_warnings"]) == 1
    assert any("feed warning" in f for f in A["early_kline_check"]["failed"])


def test_trades_that_do_not_rebuild_the_kline_or_a_failed_request_prove_nothing(tmp_path, monkeypatch):
    store, steps, stop = live_world(tmp_path, record=False, real=False)
    tr = minute_trades(stop, 59_700)
    tr[1] = (tr[1][0], 100.04)                                    # the high is not the final kline's
    rep, mm, _ = run(tmp_path, monkeypatch, store, steps, Rest({"BTCUSDT": tr}))
    assert not mm["A@15m"].get("early_kline")
    assert any("cannot verify" in f for f in mm["A@15m"]["early_kline_check"]["failed"])

    class Down(Rest):
        def _get(self, path, params):
            raise ConnectionError("down")
    (tmp_path / "b").mkdir()
    rep, mm, _ = run(tmp_path / "b", monkeypatch, store, steps, Down())
    assert not mm["A@15m"].get("early_kline") and rep["parity"]["mismatched_accounts"] == 1


def test_every_account_of_the_coin_minute_must_fit(tmp_path, monkeypatch):
    store, steps, stop = live_world(tmp_path, record=False, real=False, twin="ok")
    rep, mm, _ = run(tmp_path, monkeypatch, store, steps, Rest({"BTCUSDT": minute_trades(stop, 59_700)}))
    assert mm["A@15m"]["early_kline"] and mm["C@15m"]["early_kline"] and rep["parity"]["early_kline"] == 2
    assert rep["parity"]["early_kline_events"][0]["accounts"] == ["A@15m", "C@15m"]
    (tmp_path / "b").mkdir()
    store2, steps2, stop2 = live_world(tmp_path / "b", record=False, real=False, twin="bad")
    rep, mm, _ = run(tmp_path / "b", monkeypatch, store2, steps2, Rest({"BTCUSDT": minute_trades(stop2, 59_700)}))
    assert not mm["A@15m"].get("early_kline") and not mm["C@15m"].get("early_kline")
    assert rep["parity"]["mismatched_accounts"] == 2
    assert mm["A@15m"]["early_kline_check"]["failed"] == ["another account of the same coin-minute was not explained"]
