import json

import numpy as np

from paperbot import Bar, Brackets
from paperbot.accounts import AccountBook, day_key
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.daily3 import compare, data_quality, day_signals, limit_fill, make_signal, replay, stored_trades
from paperbot.store3 import Store3

MIN = 60_000
DAY = 86_400_000
S = v3_settings()
BR = {s: Brackets.example() for s in V3_SYMBOLS}


def _steps(n, seed=5):
    rng = np.random.default_rng(seed)
    px = {s: 100.0 for s in V3_SYMBOLS}
    out = []
    for i in range(n):
        bars = {}
        for s in V3_SYMBOLS:
            o = px[s]
            c = o * np.exp(rng.normal(0, 0.0015))
            h = max(o, c) * (1 + abs(rng.normal(0, 0.0007)))
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.0007)))
            bars[s] = Bar(s, i * MIN, i * MIN + MIN - 1, o, h, lo, c, o, h, lo, c, volume=10.0)
            px[s] = c
        fund = {s: 0.0001 for s in V3_SYMBOLS} if i % 480 == 0 and i else {}
        out.append((i * MIN, bars, fund))
    return out


def _live_day(path):
    """Run the account book over one synthetic UTC day the way live3 does."""
    store = Store3(path)
    book = AccountBook(S, BR, store)
    book.open_accounts([{"strategy": k, "timeframe": "15m", "kind": "strategy"} for k in "AB"], 0)
    steps = _steps(DAY // MIN + 1)
    rng = np.random.default_rng(9)
    for ts, bars, fund in steps:
        book.step(ts, bars, fund)
        b = ts + MIN
        if b % (15 * MIN) == 0 and rng.random() < 0.6:
            s = V3_SYMBOLS[int(rng.integers(6))]
            row = {"bar_close": b, "timeframe": "15m", "strategy": "AB"[int(rng.integers(2))], "symbol": s,
                   "side": 1 if rng.random() < 0.5 else -1, "atr": 0.15, "ref_price": bars[s].close,
                   "ref_time": b + 5000, "delay_ms": 5000, "status": "SUBMITTED"}
            store.log_signals([row])
            book.submit(f"{row['strategy']}@15m", make_signal(row))
        book.save(ts)
    store.commit()
    return store, steps


def test_replay_matches_live_day(tmp_path):
    store, steps = _live_day(str(tmp_path / "p.db"))
    conn = store.conn
    snap = json.loads(conn.execute("SELECT data FROM state WHERE k = ?", (day_key(0),)).fetchone()[0])
    day_steps = [s for s in steps if s[0] < DAY]
    rep = replay(S, BR, {}, snap, day_signals(conn, 0, DAY), day_steps)
    stored = stored_trades(conn, 0, DAY)
    assert sum(len(v) for v in stored.values()) > 10
    assert compare({a: [t for t in ts if t.exit_time < DAY] for a, ts in rep.items()}, stored) == []
    # a changed record is caught
    k = next(iter(stored))
    stored[k][0]["exit_price"] *= 1.001
    assert [m["account_id"] for m in compare({a: [t for t in ts if t.exit_time < DAY] for a, ts in rep.items()},
                                             stored)] == [k]


def test_limit_fill_needs_trade_through():
    steps = _steps(40)
    b = steps[10][1]["BTCUSDT"]
    row = {"bar_close": 10 * MIN, "timeframe": "1m", "symbol": "BTCUSDT", "side": 1, "atr": 0.0,
           "ref_price": b.low}
    assert limit_fill(row, steps, 10) is None                      # limit at the low: touch only
    row["ref_price"] = b.low + 1e-6
    assert limit_fill(row, steps, 10) == (10, b.low + 1e-6)


def test_data_quality_counts_gaps_and_outliers():
    steps = _steps(120)
    del steps[50][1]["ETHUSDT"]
    bars = steps[60][1]
    x = bars["SOLUSDT"]
    bars["SOLUSDT"] = Bar(x.symbol, x.open_time, x.close_time, x.open, x.open * 1.2, x.open * 0.8, x.close,
                          x.open, x.open * 1.2, x.open * 0.8, x.close * 1.01, volume=0.0)
    q = data_quality(steps, V3_SYMBOLS, 0, 120 * MIN)
    assert q["ETHUSDT"]["missing"] == 1 and q["BTCUSDT"]["missing"] == 0
    assert q["SOLUSDT"]["extreme_ranges"] == 1 and q["SOLUSDT"]["zero_volume"] == 1
    assert q["SOLUSDT"]["max_last_mark_gap_pct"] > 0.9


def test_notify_report_routes_by_severity():
    from paperbot.daily3 import notify_report
    from paperbot.notify import ListNotifier
    out = ListNotifier()
    rep = {"day": "2026-10-01", "parity": {"accounts": 195, "mismatched_accounts": 2},
           "shadows": {"limit_signals": 40, "limit_filled": 25, "skipped": 7},
           "data_quality": {"BTCUSDT": {"missing": 3}, "ETHUSDT": {"missing": 0}, "max_abs_funding_pct": 0.01}}
    msgs = notify_report(rep, out, trades_day=120)
    assert [m[0] for m in msgs] == ["CRITICAL", "WARN", "INFO"]
    assert "계좌 2개" in msgs[0][1] and "BTCUSDT 3" in msgs[1][1]
    assert msgs[2][1] == ("[2026-10-01] 매일 점검: 재계산 일치 193/195 · 거래 120건 · "
                          "지정가였다면 체결 25/40 · 포지션 중이라 놓친 신호 7 · 빠진 1분봉 3")
    assert out.messages == msgs

    clean = notify_report({"day": "d", "parity": "no 00:00 snapshot", "data_quality": {}}, ListNotifier())
    assert [m[0] for m in clean] == ["WARN", "INFO"]


def test_stop_variants_cover_every_losing_trade_and_match_actual_at_2atr(tmp_path):
    from paperbot.daily3 import _alone, stop_shadows
    store, steps = _live_day(str(tmp_path / "s.db"))
    conn = store.conn
    idx = {ts: k for k, (ts, _, _) in enumerate(steps)}
    sigs = day_signals(conn, -1, DAY - 1)
    rows = stop_shadows(S, BR, {}, conn, "d", 0, DAY, steps, sigs, idx)
    lost = conn.execute("SELECT COUNT(*) FROM trades WHERE exit_reason IN ('SL','LIQ')").fetchone()[0]
    assert lost > 0 and len(rows) == 3 * lost
    assert {r["kind"] for r in rows} == {"stop1.5", "stop2.5", "stop3.0"}
    # the same machinery at 2 ATR reproduces the stored losing trade
    aid, data = conn.execute("SELECT account_id, data FROM trades WHERE exit_reason = 'SL' LIMIT 1").fetchone()
    t = json.loads(data)
    d = next(x for x in sigs[t["signal_ts"] + 1] if f"{x['strategy']}@15m" == aid and x["symbol"] == t["symbol"])
    alone, ok = _alone(S, BR, {}, make_signal(d, stop_atr=2.0), steps, idx[t["signal_ts"] + 1])
    assert ok and alone.exit_time == t["exit_time"] and abs(alone.roe - t["roe"]) < 1e-9
