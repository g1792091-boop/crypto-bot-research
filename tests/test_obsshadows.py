"""Observation shadows (paperbot/obsshadows.py, docs/observation-shadows.md): hand-built 1m steps
whose variant outcomes are known in advance."""

import hashlib
import json
import os
import time

import numpy as np
import pytest

from paperbot import Bar, Brackets
from paperbot.config import V3_OLD_TIER_WALK, V3_SYMBOLS, v3_settings
from paperbot.daily3 import _alone, make_signal
from paperbot.ladder import roe_price
from paperbot.margin import BracketTier
from paperbot.obsshadows import (FIXED_LEVERAGE, LOCKS, TIME_STOP_BARS, VARIANTS, first_signal, pnl_equity,
                                 run_alone, summarize, symbol_steps, trade_shadows, variant_settings)
from paperbot.sizing import size_position
from paperbot.store3 import Store3

MIN = 60_000
DAY = 86_400_000
S = v3_settings()
BR = {s: Brackets.example() for s in V3_SYMBOLS}
# brackets that allow 50x on a $5,000 account's best tier (40% x 50x = $100k notional)
BR50 = {s: Brackets([BracketTier(10_000_000, 50, 0.004, 0.0)]) for s in V3_SYMBOLS}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYM = "BTCUSDT"
REF, ATR = 100.0, 0.2          # stop 2 ATR = 99.6
I0 = 10                        # signal ready at minute 10
RT = S.round_trip_cost
ENTRY = REF * (1 + S.slippage_frac)


def _bar(ts, o, h, lo, c):
    return Bar(SYM, ts, ts + MIN - 1, o, h, lo, c, o, h, lo, c, volume=1.0)


def _flat(n, px=ENTRY, wiggle=0.0002):
    return [(i * MIN, {SYM: _bar(i * MIN, px, px * (1 + wiggle), px * (1 - wiggle), px)}, {}) for i in range(n)]


def _row(tf="15m", side=1):
    return {"bar_close": I0 * MIN, "timeframe": tf, "strategy": "A", "symbol": SYM, "side": side, "atr": ATR,
            "ref_price": REF, "ref_time": I0 * MIN + 1000, "delay_ms": 1000, "status": "SUBMITTED"}


def _lev(settings, brackets):
    d = size_position(settings, settings.initial_equity, 1, ENTRY, REF - 2 * ATR, "best", brackets[SYM], atr=ATR)
    assert d.ok
    return d.leverage


def _db(tmp_path, row, steps, brackets=BR, settings=None):
    """paper3-like db with the signal and its actual trade (the current rules, run alone)."""
    store = Store3(str(tmp_path / "p.db"))
    store.log_signals([row])
    t, ok = _alone(settings or S, brackets, {}, make_signal(row), steps, I0)
    assert ok and t is not None
    store.trade(f"A@{row['timeframe']}", t)
    store.commit()
    return store.conn, t


def _by_kind(rows):
    return {r["kind"]: r for r in rows}


def test_variant_list_is_the_preregistered_one():
    from paperbot.agents.labtests import TEMPLATES
    assert VARIANTS == ("base", "lock15", "lock20", "lock30", "timestop", "lev10", "lev20")
    assert tuple(LOCKS.values()) == TEMPLATES["lock_start"]["first_lock"]
    assert TIME_STOP_BARS == {"5m": 14, "15m": 12, "30m": 10, "1h": 8, "4h": 6}
    assert variant_settings(S, "lock20").ladder.first_lock == 0.20
    assert variant_settings(S, "lock20").ladder.step == S.ladder.step
    for name, lev in FIXED_LEVERAGE.items():
        v = variant_settings(S, name)
        assert [(t.margin_frac, t.leverages) for t in v.tiers] == [(0.20, (lev,))]
        assert v.tier_chain("best") == [(v.tiers[0], lev)]
    assert variant_settings(S, "base") is S
    # default shares: the restarted run's rule (50x 50%, owners 2026-10-04)
    assert pnl_equity(-1.0, 50) == -0.50 and pnl_equity(0.5, 10) == 0.10 and pnl_equity(None, 20) is None


def test_preregistration_hash_matches():
    line = open(os.path.join(ROOT, "docs", "observation-shadows.sha256")).read().split()
    body = open(os.path.join(ROOT, "docs", "observation-shadows.md"), "rb").read()
    assert line[1] == "docs/observation-shadows.md" and hashlib.sha256(body).hexdigest() == line[0]


def test_time_stop_table_is_twice_the_card_median():
    path = os.path.join(ROOT, "research", "strategy_profiles", "out_binance", "cards.json")
    if not os.path.exists(path):
        pytest.skip("no cards file")
    if hashlib.sha256(open(path, "rb").read()).hexdigest() != (
            "1fa469abd0b730074c409137a52f3898ac3019d0912aae879e6b01a0746bdd09"):
        pytest.skip("cards rebuilt since the pre-registration (the table stays frozen)")
    tf_min = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
    cards = json.load(open(path))["cards"]
    for tf, m in tf_min.items():
        v = [r["median_hold_hours"] * 60 / m for c in cards for r in c["rows"]
             if r.get("tf") == tf and r.get("median_hold_hours") is not None]
        assert TIME_STOP_BARS[tf] == round(2 * float(np.median(v)))


def test_lock_15_locks_where_20_and_30_never_arm(tmp_path):
    lev = _lev(S, BR)
    p19 = roe_price(1, ENTRY, lev, 0.19, RT)      # best net ROE 19%: arms a 15% lock (trigger 17%), not 20% (22%)
    p18 = roe_price(1, ENTRY, lev, 0.18, RT)
    steps = _flat(I0 + 1)
    steps.append(((I0 + 1) * MIN, {SYM: _bar((I0 + 1) * MIN, ENTRY, p19, ENTRY * 0.9999, p18)}, {}))
    steps.append(((I0 + 2) * MIN, {SYM: _bar((I0 + 2) * MIN, p18, p18, 99.0, 99.1)}, {}))
    steps += [(ts + (I0 + 3) * MIN, {SYM: _bar(ts + (I0 + 3) * MIN, 99.1, 99.2, 99.0, 99.1)}, {})
              for ts, _, _ in _flat(5)]
    conn, actual = _db(tmp_path, _row(), steps)
    assert actual.exit_reason == "LOCK"
    rows, info = trade_shadows(S, BR, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal)
    k = _by_kind(rows)
    assert info == {"closed": 1, "no_signal": 0, "no_steps": 0} and len(rows) == len(VARIANTS)
    for v in ("base", "lock15"):
        assert k[v]["exit_reason"] == "LOCK" and abs(k[v]["roe"] - 0.15) < 0.01
    for v in ("lock20", "lock30"):
        assert k[v]["exit_reason"] == "SL" and k[v]["roe"] < -0.05
    assert k["base"]["roe"] == pytest.approx(actual.roe)
    rep = summarize(rows, info)
    assert rep["lock20"]["worse_share"] == 1.0 and rep["lock20"]["better_share"] == 0.0
    assert rep["base"]["better_share"] == 0.0 and rep["base"]["worse_share"] == 0.0
    assert rep["lock20"]["actual"]["mean_roe"] == pytest.approx(actual.roe)
    assert rep["lock20"]["mean_pnl_equity"] == pytest.approx(k["lock20"]["roe"] * pnl_equity(1.0, lev))


def test_time_stop_closes_a_stuck_trade_after_n_bars(tmp_path):
    steps = _flat(200)                            # sideways: no lock, no stop for 190 minutes
    steps.append((200 * MIN, {SYM: _bar(200 * MIN, ENTRY, ENTRY, 99.0, 99.1)}, {}))
    conn, actual = _db(tmp_path, _row(tf="5m"), steps)
    assert actual.exit_reason == "SL" and actual.exit_time == 201 * MIN - 1
    rows, info = trade_shadows(S, BR, {}, conn, "d", 0, 300 * MIN, steps, make_signal)
    k = _by_kind(rows)
    t = k["timestop"]
    assert t["exit_reason"] == "TIME" and t["resolved"] == 1
    # entry at minute 10; 14 five-minute bars later = minute 80, closed at the close of the minute-79 bar
    assert json.loads(t["data"])["exit_time"] == (I0 + 14 * 5) * MIN - 1
    assert actual.roe < t["roe"] < 0                          # costs only, smaller than the stop loss
    assert k["base"]["exit_reason"] == "SL" and k["base"]["roe"] == pytest.approx(actual.roe)
    assert summarize(rows, info)["timestop"]["better_share"] == 1.0


def test_time_stop_does_not_apply_once_the_lock_armed():
    lev = _lev(S, BR)
    p13 = roe_price(1, ENTRY, lev, 0.13, RT)      # arms the 10% lock
    steps = _flat(I0 + 1)
    steps.append(((I0 + 1) * MIN, {SYM: _bar((I0 + 1) * MIN, ENTRY, p13, ENTRY, ENTRY)}, {}))
    steps += [(i * MIN, {SYM: _bar(i * MIN, p13, p13 * 1.0001, p13 * 0.9999, p13)}, {}) for i in range(I0 + 2, 400)]
    ss = symbol_steps(steps, SYM)
    t, ok = run_alone(S, BR, {}, make_signal(_row(tf="5m")), ss, I0, time_stop_ms=14 * 5 * MIN)
    assert (t, ok) == (None, False)                            # still open, no time stop


def test_fixed_low_leverage_survives_a_gap_that_liquidates_50x(tmp_path):
    # the old tier walk (every signal 40% x 50x first): under the restarted run's quality_v1 rule this unscored
    # signal would be 'normal' (30x at most); test_levrule.py covers the shadows under that rule
    S = v3_settings(**V3_OLD_TIER_WALK)
    assert _lev(S, BR50) == 50
    steps = _flat(I0 + 3)
    steps.append(((I0 + 3) * MIN, {SYM: _bar((I0 + 3) * MIN, 97.0, 97.1, 96.9, 97.0)}, {}))   # gap -3%
    conn, actual = _db(tmp_path, _row(), steps, brackets=BR50, settings=S)
    assert actual.exit_reason == "LIQ" and actual.leverage == 50 and actual.roe < -1
    rows, info = trade_shadows(S, BR50, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal)
    k = _by_kind(rows)
    d10, d20 = json.loads(k["lev10"]["data"]), json.loads(k["lev20"]["data"])
    assert k["lev10"]["exit_reason"] == "SL" and d10["leverage"] == 10
    assert k["lev20"]["exit_reason"] == "SL" and d20["leverage"] == 20
    # the stop fills at the gapped open: ~ -3% x leverage, costs on top
    assert -0.33 < k["lev10"]["roe"] < -0.30 and -0.65 < k["lev20"]["roe"] < -0.60
    assert d10["actual_pnl_equity"] == pytest.approx(actual.roe * 0.40)
    assert d10["pnl_equity"] == pytest.approx(k["lev10"]["roe"] * 0.20)
    rep = summarize(rows, info)
    assert rep["base"]["liquidations"] == 1 and rep["lev10"]["liquidations"] == 0
    assert rep["lev10"]["actual"]["liquidations"] == 1 and rep["lev10"]["better_share"] == 1.0


def test_open_at_horizon_is_unresolved_and_left_out_of_means(tmp_path):
    lev = _lev(S, BR)
    p13 = roe_price(1, ENTRY, lev, 0.13, RT)
    steps = _flat(I0 + 1)
    steps.append(((I0 + 1) * MIN, {SYM: _bar((I0 + 1) * MIN, ENTRY, p13, ENTRY, p13)}, {}))
    steps.append(((I0 + 2) * MIN, {SYM: _bar((I0 + 2) * MIN, p13, p13, 99.8, 99.9)}, {}))   # actual: lock 10%
    steps += [(i * MIN, {SYM: _bar(i * MIN, 99.9, 99.95, 99.85, 99.9)}, {}) for i in range(I0 + 3, 300)]
    conn, actual = _db(tmp_path, _row(tf="4h"), steps)
    assert actual.exit_reason == "LOCK"
    rows, info = trade_shadows(S, BR, {}, conn, "d", 0, 300 * MIN, steps, make_signal)
    k = _by_kind(rows)
    # with a 30% first lock the drop to 99.8 stays above the 99.6 stop: still open after 290 minutes,
    # and the 4h time stop (6 bars = 24h) has not come either
    assert k["lock30"]["resolved"] == 0 and k["lock30"]["roe"] is None
    rep = summarize(rows, info)
    assert rep["lock30"]["open_at_horizon"] == 1 and rep["lock30"]["resolved"] == 0
    assert rep["lock30"]["mean_roe"] is None and rep["lock30"]["actual"]["mean_roe"] is None
    assert rep["base"]["resolved"] == 1


def test_day_rows_keys_unique_and_report_keys(tmp_path, monkeypatch):
    """run_day end to end on the synthetic live day of test_daily3: one row per closed trade and
    variant, keys unique across every shadow kind, report keys present."""
    import sqlite3

    import paperbot.daily3 as D
    from test_daily3 import _live_day
    store, steps = _live_day(str(tmp_path / "p.db"))
    monkeypatch.setattr(D, "fetch_steps", lambda rest, syms, a, b: [s for s in steps if a <= s[0] < b])

    class Rest:
        def server_time(self):
            return DAY + 2 * MIN

    out = sqlite3.connect(str(tmp_path / "d.db"))
    out.executescript(D.SCHEMA)
    rep = D.run_day(store.conn, out, Rest(), S, BR, {}, "1970-01-01")
    closed = store.conn.execute("SELECT COUNT(*) FROM trades WHERE exit_time < ?", (DAY,)).fetchone()[0]
    tv = rep["shadows"]["trade_variants"]
    assert closed > 10 and tv["closed"] == closed and tv["no_signal"] == 0 and tv["no_steps"] == 0
    for v in VARIANTS:
        assert set(tv[v]) == {"trades", "resolved", "rejected", "open_at_horizon", "mean_roe", "mean_pnl_equity",
                              "liquidations", "better_share", "worse_share", "actual"}
        assert tv[v]["trades"] == closed
        assert tv[v]["resolved"] + tv[v]["rejected"] + tv[v]["open_at_horizon"] == closed
    # the current rules re-run alone reproduce every actual trade sized at the same leverage; the
    # others differ only because the real account's equity (not $5,000 any more) picked another tier
    same = diff = 0
    for roe, data in out.execute("SELECT roe, data FROM shadows WHERE kind = 'base'"):
        d = json.loads(data)
        if d["leverage"] == d["actual_leverage"]:
            assert roe == pytest.approx(d["actual_roe"], abs=1e-9)
            same += 1
        else:
            diff += 1
    assert same > diff
    assert tv["base"]["better_share"] + tv["base"]["worse_share"] == pytest.approx(diff / closed)
    kinds = dict(out.execute("SELECT kind, COUNT(*) FROM shadows GROUP BY kind").fetchall())
    for v in VARIANTS:
        assert kinds[v] == closed
    assert {"limit", "stop1.5"} <= set(kinds)
    n = out.execute("SELECT COUNT(*) FROM shadows").fetchone()[0]
    assert n == sum(kinds.values()) == len({r[0] for r in out.execute("SELECT key FROM shadows")})
    json.dumps(rep)


def test_trades_entered_before_the_day_need_earlier_steps(tmp_path):
    steps = _flat(200)
    steps.append((200 * MIN, {SYM: _bar(200 * MIN, ENTRY, ENTRY, 99.0, 99.1)}, {}))
    conn, actual = _db(tmp_path, _row(tf="5m"), steps)
    start = 100 * MIN                                    # "the day" begins after the signal
    assert first_signal(conn, start, start + DAY) == I0 * MIN
    assert first_signal(conn, start + 8 * DAY, start + 9 * DAY) is None
    rows, info = trade_shadows(S, BR, {}, conn, "d", start, start + DAY, steps[100:], make_signal)
    assert rows == [] and info["no_steps"] == 1
    rows, info = trade_shadows(S, BR, {}, conn, "d", start, start + DAY, steps, make_signal)
    assert len(rows) == len(VARIANTS) and _by_kind(rows)["base"]["roe"] == pytest.approx(actual.roe)


def test_runtime_300_trades(tmp_path):
    """Cost check on synthetic data: 300 closed trades x 7 variants over a day of 1m steps."""
    rng = np.random.default_rng(3)
    n = DAY // MIN + 3 * 60
    steps = []
    px = {s: 100.0 for s in V3_SYMBOLS}
    for i in range(n):
        bars = {}
        for s in V3_SYMBOLS:
            o = px[s]
            c = o * np.exp(rng.normal(0, 0.0012))
            bars[s] = Bar(s, i * MIN, i * MIN + MIN - 1, o, max(o, c) * 1.0004, min(o, c) * 0.9996, c,
                          o, max(o, c) * 1.0004, min(o, c) * 0.9996, c, volume=1.0)
            px[s] = c
        steps.append((i * MIN, bars, {}))
    store = Store3(str(tmp_path / "p.db"))
    made = 0
    tfs = ("5m", "15m", "30m", "1h", "4h")
    while made < 300:
        tf = tfs[made % 5]
        bc = int(rng.integers(1, n - 600)) * MIN
        s = V3_SYMBOLS[int(rng.integers(6))]
        row = {"bar_close": bc, "timeframe": tf, "strategy": f"X{made}", "symbol": s,
               "side": 1 if rng.random() < 0.5 else -1, "atr": 0.25, "ref_price": steps[bc // MIN][1][s].open,
               "ref_time": bc, "delay_ms": 0, "status": "SUBMITTED"}
        t, ok = _alone(S, BR, {}, make_signal(row), steps, bc // MIN)
        if t is None or t.exit_time >= DAY:
            continue
        store.log_signals([row])
        store.trade(f"X{made}@{tf}", t)
        made += 1
    store.commit()
    t0 = time.perf_counter()
    rows, info = trade_shadows(S, BR, {}, store.conn, "d", 0, DAY, steps, make_signal)
    dt = time.perf_counter() - t0
    print(f"\n300 trades x {len(VARIANTS)} variants: {dt:.1f}s, rows {len(rows)}")
    assert len(rows) == 300 * len(VARIANTS)
    assert dt < 300


def test_copy_trades_skipped_newlab_kept(tmp_path):
    """A copy account's trades repeat its parent's signal (no shadow of their own); a new-strategy account's
    trades are shadowed from its own signal rows."""
    from paperbot.obsshadows import copy_accounts, trade_shadows
    from paperbot.daily3 import make_signal
    st = Store3(str(tmp_path / "p.db"))
    st.add_account("A@15m", "A", "15m", "strategy", 0, "paper-v3")
    st.add_account("A@15m~c1", "A", "15m", "copy", 0, "paper-v3", "A@15m", {"v": 1})
    st.add_account("NL1@15m", "NL1", "15m", "newlab", 0, "paper-v3", None, {"v": 1})
    steps = _flat(200)
    for aid, strat in (("A@15m", "A"), ("A@15m~c1", "A"), ("NL1@15m", "NL1")):
        row = {"bar_close": 15 * MIN, "timeframe": "15m", "strategy": strat, "symbol": "BTCUSDT", "side": 1,
               "atr": 0.2, "ref_price": 100.0, "ref_time": 15 * MIN, "delay_ms": 0, "status": "SUBMITTED"}
        if aid != "A@15m~c1":                                   # copies get no signal_log rows of their own
            st.log_signals([row])
        t = {"strategy_id": strat, "symbol": "BTCUSDT", "timeframe": "15m", "side": 1, "signal_ts": 15 * MIN - 1,
             "entry_time": 15 * MIN, "exit_time": 30 * MIN, "roe": -0.1, "leverage": 20, "exit_reason": "SL"}
        st.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, "
                        "roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (aid, "BTCUSDT", 15 * MIN, 30 * MIN, "SL", 20, -1.0, -0.1, 4999.0, json.dumps(t)))
    st.commit()
    assert copy_accounts(st.conn) == {"A@15m~c1"}
    rows, info = trade_shadows(S, BR, {}, st.conn, "d", 0, 200 * MIN, steps, make_signal)
    assert {r["account_id"] for r in rows} == {"A@15m", "NL1@15m"}
    assert info["copy_trades"] == 1 and info["closed"] == 2 and info["no_signal"] == 0
