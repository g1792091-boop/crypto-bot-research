"""Checkpoint verdicts (paperbot/checkpoint.py; docs/paper-v3-rules.md 4 + addendum Q1-Q3)."""

import hashlib
import json
import os
import sqlite3

import numpy as np
import pytest

from paperbot import Bar, Brackets, Signal
from paperbot import checkpoint as ck
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.engine import PaperEngine
from paperbot.notify import INFO, ListNotifier
from paperbot.sizing import size_position
from paperbot.store3 import Store3

MIN = 60_000
DAY = 86_400_000
S = v3_settings()
BR = {s: Brackets.example() for s in V3_SYMBOLS}
SPECS = {s: {"qty_step": 0.001, "min_notional": 5.0} for s in V3_SYMBOLS}
T0 = 1_790_000_000_000 - 1_790_000_000_000 % DAY          # a UTC midnight (2026-09-22)


def synth_minutes(lo, hi, seed=1, vol=0.0012, gaps=0.0004, gap_size=0.03, mark_wicks=0.0):
    """Random-walk 1m bars for the six coins: occasional gaps at the open, mark price near last
    (with occasional mark-only wicks), funding every 8 hours."""
    rng = np.random.default_rng(seed)
    m = ck.empty_minutes(lo, hi, V3_SYMBOLS)
    T = len(m.ts)
    for k in range(6):
        g = np.where(rng.random(T) < gaps, rng.normal(0, gap_size, T), 0.0)
        e = rng.normal(0, vol, T)
        c = 100.0 * (1 + k) * np.exp(np.cumsum(g + e))
        o = c * np.exp(-e)
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, T)))
        lo_ = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, T)))
        nz = 1 + rng.normal(0, 0.0002, T)
        wick = np.where(rng.random(T) < mark_wicks, rng.normal(0, 0.03, T), 0.0)
        m.o[:, k], m.h[:, k], m.l[:, k], m.c[:, k] = o, h, lo_, c
        m.mo[:, k], m.mc[:, k] = o * nz, c * nz
        m.mh[:, k] = h * nz * (1 + np.maximum(wick, 0))
        m.ml[:, k] = lo_ * nz * (1 + np.minimum(wick, 0))
        f = (m.ts % (8 * 3_600_000)) == 0
        m.fr[f, k] = rng.normal(0.0001, 0.0005, f.sum())
    return m


# ---------------------------------------------------------------------------- sizing and engine parity
def test_size_vec_matches_size_position():
    rng = np.random.default_rng(3)
    br = ck._BracketArrays.of(Brackets.example())
    n = 3000
    eq = rng.uniform(20, 60_000, n)
    side = rng.choice([-1.0, 1.0], n)
    fill = rng.uniform(0.1, 1000, n)
    atr = fill * rng.uniform(0.0005, 0.02, n)
    stop = fill - side * 2 * atr
    got = ck.size_vec(S, eq, side, fill, stop, atr, br, 0.001, 5.0)
    for i in range(n):
        d = size_position(S, eq[i], int(side[i]), fill[i], stop[i], "best", Brackets.example(), atr=atr[i],
                          qty_step=0.001, min_notional=5.0)
        assert d.ok == got["ok"][i], i
        if d.ok:
            assert d.leverage == got["lev"][i]
            assert d.qty == pytest.approx(got["qty"][i], rel=1e-12)
            assert d.liq_price == pytest.approx(got["liq"][i], rel=1e-9)
            assert d.margin == pytest.approx(got["margin"][i], rel=1e-12)


def _engine_run(m, tf, lo, hi, sigs, atr, s=S):
    """The same bots through the real PaperEngine, minute by minute."""
    ends, tab = atr
    atr_at = {int(t): tab[i] for i, t in enumerate(ends)}
    w = m.window(lo, hi)
    engines = [PaperEngine(s, BR, symbol_specs=SPECS, book=f"b{i}") for i in range(sigs.shape[0])]
    bidx = {int(t): j for j, t in enumerate(sorted({int(t) for t in w.ts if t % ck.TF_MS[tf] == 0}))}
    for t in range(len(w.ts)):
        ts = int(w.ts[t])
        bars = {s: Bar(s, ts, ts + MIN - 1, w.o[t, k], w.h[t, k], w.l[t, k], w.c[t, k],
                       w.mo[t, k], w.mh[t, k], w.ml[t, k], w.mc[t, k]) for k, s in enumerate(V3_SYMBOLS)}
        fund = {s: w.fr[t, k] for k, s in enumerate(V3_SYMBOLS) if not np.isnan(w.fr[t, k])}
        if ts in bidx:
            a = atr_at[ts]
            for i, e in enumerate(engines):
                for k, s in enumerate(V3_SYMBOLS):
                    sd = int(sigs[i, bidx[ts], k])
                    if sd and np.isfinite(a[k]):
                        e.submit(Signal(ts=ts - 1, symbol=s, timeframe=tf, strategy_id="R", side=sd, stop_price=0.0,
                                        tier="best", atr=float(a[k]),
                                        meta={"stop_dist": 2.0 * a[k], "ref_price": float(w.o[t, k])}))
        for e in engines:
            e.step(bars, fund)
    return engines


@pytest.mark.parametrize("tf,kw,bust_below", [
    ("15m", dict(seed=11, vol=0.002), 10.0),                                          # wide stops: 20x, locks
    ("5m", dict(seed=7, vol=0.0003, gaps=0.002, gap_size=0.03, mark_wicks=0.002), 10.0),  # 30-50x, gaps, LIQ
    ("5m", dict(seed=8, vol=0.0003, gaps=0.002, gap_size=0.03, mark_wicks=0.002), 4500.0),  # bust path
])
def test_bots_match_paper_engine(tf, kw, bust_below):
    s = v3_settings(bust_below=bust_below)
    lo = T0 + 4 * DAY
    hi = lo + 3 * DAY
    m = synth_minutes(T0, hi, **kw)
    atr = ck.tf_atr(m, tf)
    n_b = 24
    nbound = int(np.count_nonzero(m.window(lo, hi).ts % ck.TF_MS[tf] == 0))
    rng = np.random.default_rng(5)
    sigs = np.where(rng.random((n_b, nbound, 6)) < 0.03, np.where(rng.random((n_b, nbound, 6)) < 0.5, 1, -1), 0)
    boundaries = {int(t): j for j, t in enumerate(sorted(int(t) for t in m.window(lo, hi).ts
                                                         if t % ck.TF_MS[tf] == 0))}

    def draw(ts, idx, rates, C):
        s_ = sigs[idx, boundaries[ts], :]
        return s_ != 0, np.where(s_ == 0, 1, s_)

    res = ck.simulate_bots(m, tf, lo, hi, np.full(n_b, 0.03), s, BR, SPECS, draw=draw, atr=atr)
    engines = _engine_run(m, tf, lo, hi, sigs, atr, s)
    reasons = set()
    for i, e in enumerate(engines):
        reasons |= {t.exit_reason for t in e.trades}
        assert res["wallet"][i] == pytest.approx(e.wallet, rel=1e-9, abs=1e-6), (i, len(e.trades))
        assert res["trades"][i] == len(e.trades) + (e.position is not None)
        assert bool(res["bust"][i]) == e.bust
        want = e.wallet
        if e.position is not None:
            p = e.position
            want += ck.open_value(p.side, p.qty, p.entry_price, p.margin, e._last_mark[p.symbol], S)
        assert res["equity"][i] == pytest.approx(want, rel=1e-9, abs=1e-6)
    assert {"SL", "LOCK"} <= reasons          # the comparison covered stops and profit locks
    if bust_below > 10:
        assert any(e.bust for e in engines) and not all(e.bust for e in engines)
    elif tf == "5m":
        assert "LIQ" in reasons and {t.leverage for e in engines for t in e.trades} >= {30, 40}
    assert sum(len(e.trades) for e in engines) > 50


def test_bh_matches_definition():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216])
    q, rej = ck.bh(p, 0.05)
    # textbook example (Benjamini & Hochberg style): the two smallest are rejected at 5%
    assert rej.tolist() == [True, True] + [False] * 8
    m = len(p)
    for i in range(m):        # q_i = min over j with p_j >= p_i of p_j m / rank_j
        ranks = np.argsort(np.argsort(p)) + 1
        want = min(min(p[j] * m / ranks[j] for j in range(m) if p[j] >= p[i]), 1.0)
        assert q[i] == pytest.approx(want)
    rng = np.random.default_rng(0)
    for _ in range(200):
        pv = rng.random(int(rng.integers(1, 40))) ** 3
        q, rej = ck.bh(pv, 0.1)
        assert ((q <= 0.1 + 1e-12) == rej).all()
        srt = np.sort(pv)
        k = max([i + 1 for i in range(len(pv)) if srt[i] <= (i + 1) * 0.1 / len(pv)], default=0)
        assert rej.sum() == k
    assert ck.bh([], 0.1)[1].size == 0


def test_luck_p():
    bots = np.arange(2000.0)
    assert ck.luck_p(5000.0, bots) == pytest.approx(1 / 2001)
    assert ck.luck_p(-1.0, bots) == 1.0
    assert ck.luck_p(1000.0, bots) == pytest.approx(1001 / 2001)


# ---------------------------------------------------------------------------- synthetic run
def _paper_db(path, accounts, cp, extra_states=()):
    """paper3.db written the way the runner writes it, without running 30 days of minutes.
    accounts: aid -> dict(tf, kind, created, wallet, trades [(entry, exit, pnl)], signals n,
    bust, position)."""
    st = Store3(path)
    st.put_state("run", T0, {"initial_equity": 5000.0, "taker_fee": 0.0005, "settings": "paper-v3"})
    st.add_run(T0, {"commit": "x", "changes": []})
    engines = {}
    for aid, a in accounts.items():
        strat, tf = aid.split("@")
        st.add_account(aid, strat, tf, a.get("kind", "strategy"), a.get("created", T0 + 5 * 3_600_000), "paper-v3",
                       a.get("parent"))
        for k, (et, xt, pnl) in enumerate(a["trades"]):
            st.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, "
                            "pnl, roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (aid, "BTCUSDT", et, xt, "SL", 20, pnl, 0.0, 0.0, "{}"))
        n_sig = a.get("signals", 0)
        span = ck.TF_MS[tf]
        bcs = np.linspace(a.get("created", T0) + span, cp - span, max(n_sig, 1)).astype(np.int64)
        bcs = bcs - bcs % span
        st.log_signals([{"bar_close": int(b), "timeframe": tf, "strategy": strat, "symbol": V3_SYMBOLS[j % 6],
                         "side": 1, "atr": 1.0, "ref_price": 1.0, "ref_time": int(b), "delay_ms": 1,
                         "status": "SUBMITTED"} for j, b in enumerate(bcs[:n_sig])])
        engines[aid] = {"wallet": a["wallet"], "peak_equity": 5000.0, "max_drawdown": 0.0, "halted": a.get("bust", False),
                        "halt_reason": "", "bust": a.get("bust", False), "warned": [],
                        "last_mark": a.get("last_mark", {}), "position": a.get("position"), "pending": [],
                        "n_trades": len(a["trades"])}
    st.put_state("day:" + ck.day_str(cp), cp, {"engines": engines})
    for key, ts, data in extra_states:
        st.put_state(key, ts, data)
    st.close()


def _trades(n, lo, hi, pnl_each):
    t = np.linspace(lo + 3_600_000, hi - 3 * 3_600_000, n).astype(np.int64)
    return [(int(x), int(x) + 3_600_000, pnl_each) for x in t]


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


@pytest.fixture
def run_db(tmp_path):
    cp = T0 + 30 * DAY
    lo = T0 + 5 * 3_600_000
    accts = {
        # far above anything a coin-flip bot reaches: 40 trades, $5,000 -> $400,000
        "GOOD@1h": {"wallet": 400_000.0, "trades": _trades(40, lo, cp, 9875.0), "signals": 400},
        # noise: 40 trades and a small gain, well inside the bots' spread
        "NOISE@1h": {"wallet": 5_050.0, "trades": _trades(40, lo, cp, 1.25), "signals": 400},
        # not enough trades yet
        "FEW@1h": {"wallet": 9_000.0, "trades": _trades(29, lo, cp, 100.0), "signals": 300},
        # 4h: observation only, however good
        "GOOD@4h": {"wallet": 400_000.0, "trades": _trades(40, lo, cp, 9875.0), "signals": 100},
        "RANDOM_1@1h": {"kind": "random", "wallet": 3_000.0, "trades": _trades(35, lo, cp, -57.0), "signals": 300},
    }
    path = str(tmp_path / "paper3.db")
    _paper_db(path, accts, cp)
    return path, cp


def _minutes_for(seed=2):
    cache = {}

    def get(lo, hi):
        key = (lo, hi)
        if key not in cache:
            cache[key] = synth_minutes(lo, hi, seed=seed)
        return cache[key]
    return get


def test_synthetic_checkpoint_run(run_db, tmp_path):
    path, cp = run_db
    out = str(tmp_path / "checkpoint.db")
    before = _sha(path)
    note = ListNotifier()
    done = ck.run_due(path, out, _minutes_for(), S, BR, SPECS, note, now_ms=cp + 3_600_000, n_bots=200,
                      log=lambda *_: None)
    assert _sha(path) == before                      # paper3.db untouched
    assert len(done) == 1
    v = done[0]
    acc = v["accounts"]
    assert acc["GOOD@1h"]["status"] == ck.PASS1
    assert acc["GOOD@1h"]["p"] == pytest.approx(1 / 201)
    assert acc["NOISE@1h"]["status"] == ck.FAIL and acc["NOISE@1h"]["p"] > 0.1
    assert acc["FEW@1h"]["status"] == ck.HOLD and "29" in acc["FEW@1h"]["reason"]
    assert acc["GOOD@4h"]["status"] == ck.OBSERVE and acc["GOOD@4h"].get("p") is None
    assert acc["RANDOM_1@1h"]["status"] == ck.OBSERVE
    assert v["tested"] == 2 and v["luck_passed"] == 1
    assert v["lucky_expected"] == pytest.approx(0.1) and v["lucky_if_uncorrected"] == pytest.approx(0.2)
    assert v["day"] == 30
    # the signal rate given to the bots is the account's own: 400 signals / (6 coins x 1h bars)
    bars = (cp - (T0 + 6 * 3_600_000)) // 3_600_000
    assert acc["GOOD@1h"]["rate"] == pytest.approx(400 / (6 * bars), rel=0.01)
    assert note.messages and note.messages[-1][0] == INFO and "체크포인트 30일" in note.messages[-1][1]
    assert "1차 합격: GOOD@1h" in note.messages[-1][1]
    # read API
    assert ck.statuses(out)["GOOD@1h"] == ck.PASS1
    assert ck.account_status(out, "NOISE@1h")["status"] == ck.FAIL
    view = ck.dashboard_view(out)
    assert view["ready"] and view["rows"][0]["account_id"] == "GOOD@1h"
    # a second run does nothing (verdicts are final)
    assert ck.run_due(path, out, _minutes_for(), S, BR, SPECS, note, now_ms=cp + 7_200_000, n_bots=200,
                      log=lambda *_: None) == []


def test_waits_for_runner_snapshot(tmp_path):
    cp = T0 + 30 * DAY
    path = str(tmp_path / "paper3.db")
    _paper_db(path, {"A@1h": {"wallet": 5000.0, "trades": []}}, cp + DAY)   # only a later day saved
    out = str(tmp_path / "checkpoint.db")
    note = ListNotifier()
    assert ck.run_due(path, out, _minutes_for(), S, BR, SPECS, note, now_ms=cp + 3_600_000, log=lambda *_: None) == []
    assert len(note.messages) == 1 and "day:" in note.messages[0][1]
    ck.run_due(path, out, _minutes_for(), S, BR, SPECS, note, now_ms=cp + 7_200_000, log=lambda *_: None)
    assert len(note.messages) == 1                    # warned once per checkpoint


# ---------------------------------------------------------------------------- snapshot (Q2)
def test_snapshot_frozen_and_hashed(run_db, tmp_path):
    path, cp = run_db
    conn = ck.ro_connect(path)
    snap = ck.freeze_snapshot(conn, cp)
    conn.close()
    out = ck.open_out(str(tmp_path / "c.db"))
    sha = ck.store_snapshot(out, snap, cp)
    assert sha == hashlib.sha256(ck.canonical(snap).encode()).hexdigest()
    got, sha2 = ck.load_snapshot(out, snap["date"])
    assert got == snap and sha2 == sha
    with pytest.raises(sqlite3.DatabaseError):
        out.execute("UPDATE snapshots SET data = '{}'")
    with pytest.raises(sqlite3.DatabaseError):
        out.execute("DELETE FROM snapshots")
    assert ck.store_snapshot(out, {**snap, "accounts": {}}, cp) == sha     # a second freeze keeps the first
    # bypassing the guard (dropping the trigger) is caught by the hash
    out.execute("DROP TRIGGER snapshots_frozen_u")
    out.execute("UPDATE snapshots SET data = replace(data, '400000', '400001')")
    with pytest.raises(ck.SnapshotTampered):
        ck.load_snapshot(out, snap["date"])


def test_snapshot_values(tmp_path):
    cp = T0 + 30 * DAY
    pos = {"symbol": "BTCUSDT", "side": 1, "qty": 2.0, "entry_price": 100.0, "entry_time": cp - DAY,
           "leverage": 20, "margin": 10.0, "entry_fee": 0.1, "funding_paid": 0.05, "tier": "base",
           "margin_initial": 10.0, "stop_price": 95.0, "tp_price": float("nan"), "liq_price": 95.5,
           "signal": {"ts": 0, "symbol": "BTCUSDT", "timeframe": "1h", "strategy_id": "A", "side": 1,
                      "stop_price": 95.0}}
    lo = T0 + 5 * 3_600_000
    path = str(tmp_path / "p.db")
    _paper_db(path, {"A@1h": {"wallet": 4000.0, "trades": _trades(3, lo, cp, 1.0) + [(lo, cp + 5, 7.0)],
                              "position": pos, "last_mark": {"BTCUSDT": 103.0}, "signals": 12}}, cp)
    conn = ck.ro_connect(path)
    snap = ck.freeze_snapshot(conn, cp)
    a = snap["accounts"]["A@1h"]
    # equity = wallet + 2 x (103 - 100) - 2 x 103 x (fee + slippage)
    assert a["equity"] == pytest.approx(4000 + 6 - 206 * (0.0005 + 0.0002))
    assert len(a["trades"]) == 3                      # the trade closed after the checkpoint is not in it
    st = ck.period_stats(a, lo, cp, S, 5000.0)
    assert st["trades"] == 4                          # the open one counts in the period it was entered
    assert st["pnl"] == pytest.approx(3.0 + 6 - 206 * 0.0007 - 0.1 - 0.05)
    assert st["signals"] == 12
    # read-only: the connection cannot write
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO alerts VALUES (1, 'INFO', 'x')")
    conn.close()


# ---------------------------------------------------------------------------- schedule (Q3)
def _snap(cp, accounts, initial=5000.0):
    return {"date": ck.day_str(cp), "cp_ts": cp, "run": {"initial_equity": initial, "start_ts": T0,
                                                        "taker_fee": 0.0005, "slippage": 0.0002},
            "accounts": accounts}


def _acct(tf, n_trades, equity, lo, hi, created=None, kind="strategy", bust=False):
    return {"strategy": "X", "timeframe": tf, "kind": kind, "created_ts": created or T0 + 3_600_000, "parent": None,
            "wallet": equity, "bust": bust, "position": None, "mark": None, "equity": equity,
            "trades": [list(t) for t in _trades(n_trades, lo, hi, 1.0)] if n_trades else [], "signals": {}}


def test_first_eligible_at_30_trades():
    cp1, cp2 = T0 + 30 * DAY, T0 + 60 * DAY
    s1 = _snap(cp1, {"A@1h": _acct("1h", 29, 6000.0, T0, cp1)})
    rows, tasks = ck.plan(s1, {}, {}, S)
    assert rows["A@1h"]["status"] == ck.HOLD and not tasks
    # 60 days: now 35 trades in total -> judged here, on the whole window since the start
    s2 = _snap(cp2, {"A@1h": _acct("1h", 35, 6000.0, T0, cp2)})
    rows, tasks = ck.plan(s2, {"A@1h": {"date": s1["date"], **rows["A@1h"]}}, {}, S)
    assert [(t.aid, t.stage, t.lo, t.hi) for t in tasks] == [("A@1h", "1차", T0 + 3_600_000, cp2)]
    # a copy started 10 days before the checkpoint waits for its own 30 days
    s3 = _snap(cp2, {"C@1h": _acct("1h", 50, 9000.0, cp2 - 10 * DAY, cp2, created=cp2 - 10 * DAY)})
    rows, tasks = ck.plan(s3, {}, {}, S)
    assert rows["C@1h"]["status"] == ck.HOLD and not tasks
    # day 180 without 30 trades: no verdict possible
    s4 = _snap(T0 + 180 * DAY, {"A@1h": _acct("1h", 5, 6000.0, T0, T0 + 180 * DAY)})
    rows, _ = ck.plan(s4, {}, {}, S)
    assert "판정 불가" in rows["A@1h"]["reason"]


def test_4h_observation_only():
    cp = T0 + 30 * DAY
    s = _snap(cp, {"A@4h": _acct("4h", 80, 90_000.0, T0, cp), "A@1h": _acct("1h", 80, 90_000.0, T0, cp)})
    rows, tasks = ck.plan(s, {}, {}, S)
    assert rows["A@4h"]["status"] == ck.OBSERVE
    assert [t.aid for t in tasks] == ["A@1h"]


def test_decide_rules():
    cp = T0 + 30 * DAY
    s = _snap(cp, {"UP@1h": _acct("1h", 40, 9000.0, T0, cp), "DOWN@1h": _acct("1h", 40, 4000.0, T0, cp),
                   "BUST@1h": _acct("1h", 40, 5.0, T0, cp, bust=True)})
    rows, tasks = ck.plan(s, {}, {}, S)
    pv = {"UP@1h": {"p": 0.001}, "DOWN@1h": {"p": 0.001}, "BUST@1h": {"p": 0.001}}
    summ = ck.decide(s, rows, tasks, pv)
    assert rows["UP@1h"]["status"] == ck.PASS1
    assert rows["DOWN@1h"]["status"] == ck.FAIL and "평가금" in rows["DOWN@1h"]["reason"]
    assert rows["BUST@1h"]["status"] == ck.FAIL and "파산" in rows["BUST@1h"]["reason"]
    assert summ["tested"] == 3 and summ["counts"][ck.PASS1] == 1


def test_second_check(run_db, tmp_path):
    """1st pass at day 30, then the next 30 days alone decide: trades and P&L entered in them."""
    path, cp1 = run_db
    out = str(tmp_path / "checkpoint.db")
    ck.run_due(path, out, _minutes_for(), S, BR, SPECS, None, now_ms=cp1 + 1, n_bots=100, log=lambda *_: None)
    assert ck.statuses(out)["GOOD@1h"] == ck.PASS1
    cp2 = cp1 + 30 * DAY
    lo = T0 + 5 * 3_600_000
    t1 = _trades(40, lo, cp1, 9875.0)
    accts = {
        # period 2: 35 new trades, +$2,000,000 on a $400,000 start -> +$25,000 on $5,000: far above the bots
        "GOOD@1h": {"wallet": 2_400_000.0, "trades": t1 + _trades(35, cp1, cp2, 2_000_000 / 35), "signals": 800},
        "NOISE@1h": {"wallet": 5_000.0, "trades": _trades(40, lo, cp1, 1.25), "signals": 400},
        "FEW@1h": {"wallet": 9_000.0, "trades": _trades(29, lo, cp1, 100.0), "signals": 300},
        "GOOD@4h": {"wallet": 400_000.0, "trades": _trades(40, lo, cp1, 9875.0), "signals": 100},
        "RANDOM_1@1h": {"kind": "random", "wallet": 3_000.0, "trades": [], "signals": 300},
    }
    path2 = str(tmp_path / "paper3b.db")
    # same database content plus the day-60 state (a fresh file built the same way)
    conn = sqlite3.connect(path)
    day30 = conn.execute("SELECT ts, data FROM state WHERE k = ?", ("day:" + ck.day_str(cp1),)).fetchone()
    conn.close()
    _paper_db(path2, accts, cp2, extra_states=[("day:" + ck.day_str(cp1), day30[0], json.loads(day30[1]))])
    done = ck.run_due(path2, out, _minutes_for(), S, BR, SPECS, None, now_ms=cp2 + 1, n_bots=100,
                      log=lambda *_: None)
    v = done[-1]
    g = v["accounts"]["GOOD@1h"]
    assert g["stage"] == "2차" and g["window"] == [cp1, cp2]
    assert g["trades"] == 35 and g["pnl"] == pytest.approx(2_000_000)
    assert g["pnl_scaled"] == pytest.approx(25_000, rel=1e-6)
    assert g["status"] == ck.PASS2
    assert v["accounts"]["NOISE@1h"]["status"] == ck.FAIL and "유지" in v["accounts"]["NOISE@1h"]["reason"]
    assert v["accounts"]["FEW@1h"]["status"] == ck.HOLD


def test_minutes_cache(tmp_path):
    """Binance source: one request set per coin and day, then the .npz cache."""
    calls = []
    d0 = T0

    class Rest:
        def klines(self, s, i, start_time, limit):
            calls.append(("k", s, start_time))
            return [[start_time + j * MIN, "1", "2", "0.5", "1.5", "10", start_time + j * MIN + MIN - 1]
                    for j in range(1440)]

        def mark_klines(self, s, i, start_time, limit):
            return [[start_time + j * MIN, "1", "2", "0.5", "1.4"] for j in range(1440)]

        def funding_rates(self, s, start_time, limit):
            return [{"fundingTime": start_time + 8 * 3_600_000 + 3, "fundingRate": "0.0001"}]

    src = ck.BinanceMinutes(Rest(), str(tmp_path / "bars"), pause=0, now_ms=lambda: d0 + 5 * DAY)
    m = src.load(d0, d0 + 2 * DAY)
    assert m.o.shape == (2880, 6) and np.all(m.mc == 1.4)
    assert np.nansum(m.fr) == pytest.approx(0.0001 * 12) and m.fr[480, 0] == 0.0001
    n = len(calls)
    src.load(d0 + 3_600_000, d0 + DAY)
    assert len(calls) == n and len(os.listdir(tmp_path / "bars")) == 12


def test_dashboard_endpoint(run_db, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app
    path, cp = run_db
    app = create_app(path, None, b"x" * 32)               # no password: tests only
    c = TestClient(app)
    assert c.get("/api/checkpoint").json() == {"ready": False}
    ck.run_due(path, str(tmp_path / "checkpoint.db"), _minutes_for(), S, BR, SPECS, None, now_ms=cp + 1, n_bots=50,
               log=lambda *_: None)
    v = c.get("/api/checkpoint").json()
    assert v["ready"] and v["day"] == 30 and v["counts"][ck.PASS1] == 1
    assert {r["account_id"]: r["status"] for r in v["rows"]}["GOOD@4h"] == ck.OBSERVE
    assert "checkpoint.js" in c.get("/").text


# ---------------------------------------------------------------------------- extra accounts (paperbot/extras.py)
def _x(tf, n_trades, equity, lo, hi, kind, created, rule=None):
    a = _acct(tf, n_trades, equity, lo, hi, created=created, kind=kind)
    a["rule"] = rule or {"stop_atr": 2.0, "first_lock": 0.1, "skip_tag": None}
    a["events"] = []
    return a


def _stage2_setup(with_extra, extra_kind="newlab", rule=None):
    cp1, cp2 = T0 + 30 * DAY, T0 + 60 * DAY
    accts = {"A@1h": _acct("1h", 70, 9000.0, T0, cp2), "B@1h": _acct("1h", 70, 7000.0, T0, cp2)}
    prior = {aid: {"date": ck.day_str(cp1), "status": ck.PASS1, "stage": "1차", "window": [T0 + 3_600_000, cp1]}
             for aid in accts}
    prev = {ck.day_str(cp1): {"accounts": {"A@1h": {"equity": 8000.0}, "B@1h": {"equity": 6000.0}}}}
    if with_extra:
        created = T0 + 3_600_000
        aid = "NL1@1h" if extra_kind == "newlab" else "A@1h~c1"
        accts[aid] = _x("1h", 70, 9500.0, T0, cp2, extra_kind, created, rule)
        prior[aid] = {"date": ck.day_str(cp1), "status": ck.PASS1, "stage": "1차", "window": [created, cp1],
                      "created_ts": created}
        prev[ck.day_str(cp1)]["accounts"][aid] = {"equity": 8500.0}
    for a in accts.values():
        a["signals"] = {ck.day_str(cp1 + k * DAY): 30 for k in range(30)}
    return _snap(cp2, accts), prior, prev


def _q1(snap, prior, prev, n_bots=60):
    rows, tasks = ck.plan(snap, prior, prev, S)
    cp = snap["cp_ts"]
    m = synth_minutes(T0 + 20 * DAY, cp, seed=4)
    pv, groups = ck.run_tasks(tasks, lambda lo, hi: m.window(lo, hi), S, BR, SPECS, n_bots, 7, 5000.0)
    summ = ck.decide(snap, rows, tasks, pv)
    return rows, tasks, pv, groups, summ


def test_originals_byte_identical_with_extra_in_shared_stage2_window():
    base = _q1(*_stage2_setup(False))
    for kind in ("newlab", "copy"):
        got = _q1(*_stage2_setup(True, kind, {"stop_atr": 2.0, "first_lock": 0.1, "skip_tag": None}))
        rows0, _t0, pv0, groups0, _s0 = base
        rows1, tasks1, pv1, groups1, _s1 = got
        extra = "NL1@1h" if kind == "newlab" else "A@1h~c1"
        assert [t.cls for t in tasks1 if t.aid == extra] == [extra]
        assert [t.window if hasattr(t, "window") else (t.lo, t.hi) for t in tasks1 if t.aid == extra] == \
            [(T0 + 30 * DAY, T0 + 60 * DAY)]                                  # the originals' stage-2 window
        for aid in ("A@1h", "B@1h"):
            for k in ("p", "bots_median", "bots_p90", "bots_bust", "bots_trades"):
                assert pv1[aid][k] == pv0[aid][k], (kind, aid, k)
        assert groups1[:len(groups0)] == [{**g, "seconds": groups1[i]["seconds"]} for i, g in enumerate(groups0)]
        assert len(groups1) == len(groups0) + 1 and groups1[-1]["account_id"] == extra
        if kind == "newlab":                       # family B: the originals' q too are unchanged
            for aid in ("A@1h", "B@1h"):
                assert rows1[aid]["q"] == rows0[aid]["q"] and "q_orig" not in rows1[aid]


def test_extra_groups_own_seed_and_rule(monkeypatch):
    import hashlib as _h
    snap, prior, prev = _stage2_setup(True, "copy", {"stop_atr": 2.5, "first_lock": 0.2, "skip_tag": None})
    seen = []
    real = ck.simulate_bots

    def spy(m, tf, lo, hi, rates, s, brackets, specs=None, seed=0, **kw):
        seen.append((list(seed), len(rates), s.ladder_first_lock, kw.get("stop_atr")))
        return real(m, tf, lo, hi, rates, s, brackets, specs, seed=seed, **kw)
    monkeypatch.setattr(ck, "simulate_bots", spy)
    rows, tasks, pv, groups, summ = _q1(snap, prior, prev, n_bots=40)
    seed_base = 7
    orig = [seed_base, 60, (T0 + 30 * DAY) // MIN % 2 ** 31]
    assert seen[0] == (orig, 80, 0.1, 2.0)                                # the originals: 2 accounts x 40 bots
    want = orig + [int(_h.sha256(b"A@1h~c1").hexdigest()[:8], 16)]
    assert seen[1] == (want, 40, 0.2, 2.5)                                # the copy alone, its own rule and seed
    assert groups[1]["seed"] == want and groups[1]["first_lock"] == 0.2 and groups[1]["stop_atr"] == 2.5


def test_fdr_family_a_copies_family_b_newlab():
    cp = T0 + 30 * DAY
    accts = {f"S{k}@1h": _acct("1h", 40, 9000.0, T0, cp) for k in range(4)}
    accts["S0@1h~c1"] = _x("1h", 40, 9000.0, T0, cp, "copy", T0 - DAY)
    accts["NL1@1h"] = _x("1h", 40, 9000.0, T0, cp, "newlab", T0 - DAY)
    accts["NL2@15m"] = _x("15m", 40, 9000.0, T0, cp, "newlab", T0 - DAY)
    s = _snap(cp, accts)
    rows, tasks = ck.plan(s, {}, {}, S)
    p = {"S0@1h": 0.001, "S1@1h": 0.02, "S2@1h": 0.03, "S3@1h": 0.5, "S0@1h~c1": 0.004, "NL1@1h": 0.01,
         "NL2@15m": 0.04}
    summ = ck.decide(s, rows, tasks, {a: {"p": v} for a, v in p.items()})
    fam_a = ["S0@1h", "S1@1h", "S2@1h", "S3@1h", "S0@1h~c1"]
    qa, _ = ck.bh([p[a] for a in fam_a], ck.ALPHA)
    for a, q in zip(fam_a, qa):
        assert rows[a]["q"] == pytest.approx(q)
    qb, _ = ck.bh([p["NL1@1h"], p["NL2@15m"]], ck.ALPHA)
    assert rows["NL1@1h"]["q"] == pytest.approx(qb[0]) and rows["NL2@15m"]["q"] == pytest.approx(qb[1])
    assert summ["tested"] == 5 and summ["family_b"]["tested"] == 2


def test_q_orig():
    cp = T0 + 30 * DAY
    accts = {f"S{k}@1h": _acct("1h", 40, 9000.0, T0, cp) for k in range(3)}
    s0 = _snap(cp, dict(accts))
    rows0, tasks0 = ck.plan(s0, {}, {}, S)
    p = {"S0@1h": 0.004, "S1@1h": 0.03, "S2@1h": 0.2}
    ck.decide(s0, rows0, tasks0, {a: {"p": v} for a, v in p.items()})
    accts["S0@1h~c1"] = _x("1h", 40, 9000.0, T0, cp, "copy", T0 - DAY)
    s1 = _snap(cp, accts)
    rows1, tasks1 = ck.plan(s1, {}, {}, S)
    ck.decide(s1, rows1, tasks1, {a: {"p": v} for a, v in dict(p, **{"S0@1h~c1": 0.001}).items()})
    for a in p:
        assert "q_orig" not in rows0[a]                                     # no copies: q is the originals' own
        assert rows1[a]["q_orig"] == pytest.approx(rows0[a]["q"])
        assert rows1[a]["q"] != pytest.approx(rows0[a]["q"]) or a == "S2@1h"
    assert "q_orig" not in rows1["S0@1h~c1"]


def _extras_paper_db(path, cp):
    from paperbot.extras import content_key_copy
    st = Store3(path)
    st.put_state("run", T0, {"initial_equity": 5000.0, "taker_fee": 0.0005, "settings": "paper-v3"})
    st.add_run(T0, {"commit": "x", "changes": []})
    st.add_run(T0 + 12 * DAY, {"commit": "y", "changes": ["commit", "extra_code"]})
    created = T0 + 10 * DAY
    st.add_account("S@1h", "S", "1h", "strategy", T0, "paper-v3")
    st.add_account("S@1h~c1", "S", "1h", "copy", created, "paper-v3", "S@1h",
                   {"v": 1, "kind": "copy", "rule": {"template": "skip_tag", "tag": "추세 반대 진입"},
                    "source": {"content": content_key_copy({"template": "skip_tag", "tag": "추세 반대 진입"})}})
    st.add_account("NL1@1h", "NL1", "1h", "newlab", created, "paper-v3", None,
                   {"v": 1, "kind": "newlab", "rule": None, "spec_hash": "h"})
    rows = []
    for k in range(40):
        b = T0 + (k + 1) * 12 * 3_600_000
        side = 1 if k % 2 else -1
        ctx = {"regime": "trend_down"}                     # a long here carries the tag
        rows.append({"bar_close": b, "timeframe": "1h", "strategy": "S", "symbol": "BTCUSDT", "side": side,
                     "atr": 1.0, "ref_price": 1.0, "ref_time": b, "delay_ms": 1, "status": "SUBMITTED",
                     "data": {"ctx": ctx}})
        rows.append({"bar_close": b, "timeframe": "1h", "strategy": "NL1", "symbol": "ETHUSDT", "side": 1,
                     "atr": 1.0, "ref_price": 1.0, "ref_time": b, "delay_ms": 1, "status": "SUBMITTED", "data": {}})
    st.log_signals(rows)
    ev = [{"ts": created, "account_id": "S@1h~c1", "event": "created", "effective": created},
          {"ts": created, "account_id": "NL1@1h", "event": "created", "effective": created},
          {"ts": T0 + 15 * DAY, "account_id": "NL1@1h", "event": "suspended", "code": "code_changed",
           "effective": T0 + 15 * DAY},
          {"ts": T0 + 16 * DAY, "account_id": "NL1@1h", "event": "code_accepted", "code": "code_changed",
           "effective": T0 + 16 * DAY},
          {"ts": T0 + 16 * DAY, "account_id": "NL1@1h", "event": "resumed", "code": "code_changed",
           "effective": T0 + 16 * DAY}]
    st.put_state("extras", T0 + 20 * DAY, {"v": 1, "events": ev, "health": {
        "skipped_runs": [[T0 + 20 * DAY, T0 + 20 * DAY + 3 * 3_600_000]]}})
    eng = {"wallet": 5000.0, "peak_equity": 5000.0, "max_drawdown": 0.0, "halted": False, "halt_reason": "",
           "bust": False, "warned": [], "last_mark": {}, "position": None, "pending": [], "n_trades": 0}
    st.put_state("day:" + ck.day_str(cp), cp, {"engines": {a: dict(eng) for a in ("S@1h", "S@1h~c1", "NL1@1h")}})
    st.close()
    return created


def test_snapshot_v2_extras_and_v1_fields_unchanged(tmp_path):
    from paperbot.agents import labtests as LT
    cp = T0 + 30 * DAY
    path = str(tmp_path / "p.db")
    created = _extras_paper_db(path, cp)
    conn = ck.ro_connect(path)
    snap = ck.freeze_snapshot(conn, cp)
    conn.close()
    assert snap["version"] == 2
    o = snap["accounts"]["S@1h"]
    assert set(o) == {"strategy", "timeframe", "kind", "created_ts", "parent", "wallet", "bust", "halted",
                      "position", "mark", "equity", "trades", "signals"}               # exactly the v1 fields
    assert sum(o["signals"].values()) == 40
    c = snap["accounts"]["S@1h~c1"]
    assert c["rule"] == {"stop_atr": 2.0, "first_lock": 0.1, "skip_tag": "추세 반대 진입"}
    # the parent's signals after the copy's start, minus the ones its tag drops (longs in a downtrend)
    want = sum(1 for k in range(40) if T0 + (k + 1) * 12 * 3_600_000 > created
               and not LT.has_tag("추세 반대 진입", 1 if k % 2 else -1, {"regime": "trend_down"}))
    assert sum(c["signals"].values()) == want and 0 < want < 40
    n = snap["accounts"]["NL1@1h"]
    assert sum(n["signals"].values()) == sum(1 for k in range(40) if T0 + (k + 1) * 12 * 3_600_000 >= created)
    assert [e["event"] for e in n["events"]] == ["created", "suspended", "code_accepted", "resumed"]
    assert n["skipped_runs"] == [[T0 + 20 * DAY, T0 + 20 * DAY + 3 * 3_600_000]]
    assert ck.skipped_bars(n["skipped_runs"], "1h", created, cp, created) == 4
    assert snap["run"]["extra_code_changes"] == [{"ts": T0 + 12 * DAY, "changes": ["extra_code"]}]
    assert snap["run"]["trading_changes"] == []                           # extra_code is not the originals' Q5


def test_extra_warnings_only_on_extras(tmp_path):
    cp = T0 + 40 * DAY
    path = str(tmp_path / "p.db")
    _extras_paper_db(path, cp)
    conn = ck.ro_connect(path)
    snap = ck.freeze_snapshot(conn, cp)
    conn.close()
    rows, tasks = ck.plan(snap, {}, {}, S)
    w = ck.extra_warnings(snap, rows)
    assert any("추가 계좌만 해당: NL1@1h, S@1h~c1" in x for x in w)
    assert any(x.startswith("NL1@1h:") and "Q5 사건" in x for x in w)
    assert all("S@1h:" not in x and "S@1h " not in x for x in w)
    assert "notes" not in rows["S@1h"] and rows["NL1@1h"]["notes"]
    assert rows["NL1@1h"]["created_ts"] == T0 + 10 * DAY and "created_ts" not in rows["S@1h"]


def test_prior_ignores_reused_id_with_other_created_ts():
    cp = T0 + 60 * DAY
    accts = {"NL1@1h": _x("1h", 40, 9000.0, T0 + 20 * DAY, cp, "newlab", T0 + 20 * DAY)}
    prior = {"NL1@1h": {"date": ck.day_str(T0 + 30 * DAY), "status": ck.FAIL, "stage": "1차",
                        "created_ts": T0 + 2 * DAY, "reason": "x"}}
    rows, tasks = ck.plan(_snap(cp, accts), prior, {}, S)
    assert [t.aid for t in tasks] == ["NL1@1h"] and rows["NL1@1h"]["stage"] == "1차"    # judged from its new start
    prior["NL1@1h"]["created_ts"] = T0 + 20 * DAY
    rows, tasks = ck.plan(_snap(cp, accts), prior, {}, S)
    assert rows["NL1@1h"]["status"] == ck.FAIL and not tasks


def test_run_start_ignores_extras(tmp_path):
    path = str(tmp_path / "p.db")
    st = Store3(path)
    st.add_account("NL1@1h", "NL1", "1h", "newlab", T0 - 5 * DAY, "paper-v3", None, {})
    st.add_account("S@1h", "S", "1h", "strategy", T0, "paper-v3")
    st.add_account("RANDOM_1@1h", "RANDOM_1", "1h", "random", T0 + 1, "paper-v3")
    st.close()
    conn = ck.ro_connect(path)
    assert ck.run_facts(conn)["start_ts"] == T0
    conn.close()
