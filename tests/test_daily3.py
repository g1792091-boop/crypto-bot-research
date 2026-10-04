import json

import numpy as np

from paperbot import Bar, Brackets
from paperbot.accounts import AccountBook, day_key
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.daily3 import compare, data_quality, day_signals, limit_fill, make_signal, replay, stored_trades
from paperbot.store3 import Store3

MIN = 60_000
DAY = 86_400_000
HOUR = 3_600_000
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
    # one message a day (owners' layout 2026-10-04): loud only for a real mismatch or a missing snapshot
    assert [m[0] for m in msgs] == ["CRITICAL"] and out.messages == msgs
    assert msgs[0][1] == ("재계산 불일치 · 10/01\n\n계좌 2개의 거래가 paper와 다름\n운영 감사관 확인 필요\n"
                          "자세히: daily3.db mismatches\n\n매일 점검\n재계산 일치 193/195\n거래 120건\n"
                          "지정가였다면 체결 25/40\n포지션 중이라 놓친 신호 7\n빠진 1분봉 3 (BTC 3)")
    ok = notify_report({**rep, "parity": {"accounts": 195, "mismatched_accounts": 0}}, ListNotifier(), trades_day=120)
    assert [m[0] for m in ok] == ["INFO"] and ok[0][1].startswith("🔎 매일 점검 · 10/01\n\n재계산 일치 195/195\n")

    clean = notify_report({"day": "d", "parity": "no 00:00 snapshot", "data_quality": {}}, ListNotifier())
    assert [m[0] for m in clean] == ["WARN"] and clean[0][1].startswith("재계산 못 함 · d\n\n그날 09:00(한국) 상태 저장이 없음")


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


# ---------------------------------------------------------------------------- extras (paperbot/extras.py)
def _extras_day(tmp_path, gap_at=None):
    """A live UTC day with extras through the real runner (tests/extras_world.py): a lock_start copy started at
    00:00, a stop_atr copy, a skip_tag copy and a new-strategy account started mid-day, a held interval (an
    engine fault, then a restart) and a suspended interval (a changed code pin, then accepted)."""
    from paperbot import extras as X
    from paperbot import newlab_live as NLL
    from tests.extras_world import World, T0 as W0
    rng = np.random.default_rng(12)
    path = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, 3000)))
    t_start = W0 - 30 * MIN

    def px(t):
        return float(path[(t - t_start) // MIN])

    def script(w):
        for b in range(t_start, W0 + DAY + HOUR, 5 * MIN):
            k = (b // (5 * MIN)) % 7
            ctx = {"regime": "trend_down" if k % 2 else "trend_up", "adx": 30.0}
            w.service.fire[(b, "5m")] = [("N17_KC_RSI@5m", 1 if k % 3 else -1, "BTCUSDT", dict(ctx))]
            if b % (15 * MIN) == 0:
                w.service.fire[(b, "15m")] = [("V45_AMB@15m", -1 if k % 2 else 1, "ETHUSDT", dict(ctx)),
                                              ("S2_ST_ROC@15m", 1, "SOLUSDT", dict(ctx))]

    def fake_compute(self, B, due, deadline):
        out = []
        for aid, (name, tf, spec) in self.specs.items():
            if tf in due and (B // (5 * MIN)) % 4 == 0:
                out.append({"symbol": "LTCUSDT", "tf": tf, "ready": True, "why": None, "bars": 500,
                            "bar_open": B - 5 * MIN, "close": px(B - MIN), "atr_last": 0.2,
                            "sides": {aid: 1 if (B // (5 * MIN)) % 8 else -1}, "ctx": {"regime": "box"},
                            "errors": []})
        return out, []
    real_compute = NLL.NewlabSignals.compute
    NLL.NewlabSignals.compute = fake_compute
    try:
        w = World(tmp_path, hist=True, start_at=t_start, run_start=t_start,
                  strategies=("V45_AMB", "N17_KC_RSI", "S2_ST_ROC"), tfs=("5m", "15m"))
        script(w)
        steps = []

        def step(t):
            w.process(t, px=px(t))
            steps.append((t, w.bars(t, px(t)), {}))
        real_phase1 = X.Extras._phase1

        def phase1(self, boundary, submitted, j):
            if boundary == gap_at:
                return False                 # killed between the 195's commit and the copy's (crash gap)
            return real_phase1(self, boundary, submitted, j)
        X.Extras._phase1 = phase1
        t = t_start
        while t < W0 + DAY + 30 * MIN:
            if t == W0 - 2 * MIN:
                w.copy_proposal("N17_KC_RSI", "5m", {"template": "lock_start", "first_lock": 0.15})
            if t == W0 + 2 * HOUR:
                w.copy_proposal("V45_AMB", "15m", {"template": "stop_atr", "k": 2.5})
                w.copy_proposal("S2_ST_ROC", "15m", {"template": "skip_tag", "tag": "추세 반대 진입"})
                w.newlab_proposal(0)
            if t == W0 + 6 * HOUR:
                e = w.book.engines["V45_AMB@15m~c2"]

                def boom(*a, **k):
                    raise ZeroDivisionError("injected")
                e._mark_to_market = boom
            if t in (W0 + 8 * HOUR, W0 + 10 * HOUR):
                cfg = None
                if t == W0 + 8 * HOUR:
                    w.store.commit()
                    w.close()
                    import sqlite3 as _sq
                    c = _sq.connect(w.db)
                    d = json.loads(c.execute("SELECT data FROM accounts WHERE account_id = 'NL1@5m'").fetchone()[0])
                    d["code"]["recorder"] = "0" * 64
                    c.execute("UPDATE accounts SET data = ? WHERE account_id = 'NL1@5m'", (json.dumps(d),))
                    c.commit()
                    c.close()
                else:
                    pin = NLL.pin_text(w.ext.newlab.pin())
                    w.close()
                    cfg = str(tmp_path / "extras.json")
                    with open(cfg, "w") as fh:
                        json.dump({"accept_code": {"NL1@5m": pin}}, fh)
                w = World(tmp_path, hist=True, start_at=t, strategies=("V45_AMB", "N17_KC_RSI", "S2_ST_ROC"),
                          tfs=("5m", "15m"), config_path=cfg)
                script(w)
            step(t)
            t += MIN
        X.Extras._phase1 = real_phase1
    finally:
        NLL.NewlabSignals.compute = real_compute
    return w, [s for s in steps if W0 <= s[0] < W0 + DAY], W0


def test_replay_with_extras_zero_mismatch(tmp_path):
    from paperbot.daily3 import extras_of
    w, steps, day0 = _extras_day(tmp_path)
    conn = w.store.conn
    ext = extras_of(conn)
    assert set(ext) == {"N17_KC_RSI@5m~c1", "V45_AMB@15m~c2", "S2_ST_ROC@15m~c3", "NL1@5m"}
    assert ext["N17_KC_RSI@5m~c1"]["created_ts"] == day0                              # in the 00:00 snapshot
    snap = json.loads(conn.execute("SELECT data FROM state WHERE k = ?", (day_key(day0),)).fetchone()[0])
    assert "N17_KC_RSI@5m~c1" in snap["engines"] and "V45_AMB@15m~c2" not in snap["engines"]
    assert [s for _, s in ext["V45_AMB@15m~c2"]["timeline"]] == ["active", "held", "active"]
    assert [s for _, s in ext["NL1@5m"]["timeline"]] == ["active", "suspended", "active"]
    assert conn.execute("SELECT COUNT(*) FROM outcomes WHERE status = 'FILTERED'").fetchone()[0] > 0
    rep = replay(S, BR, {}, snap, day_signals(conn, day0, day0 + DAY, with_data=True), steps, extras=ext)
    stored = stored_trades(conn, day0, day0 + DAY)
    mism = compare({a: [t for t in ts if t.exit_time < day0 + DAY] for a, ts in rep.items()}, stored)
    assert mism == [], [m["account_id"] for m in mism]
    for aid in ext:
        assert len(stored.get(aid, [])) >= 2, aid
    # without the extras' rules the copies do not reproduce (the replay really uses them)
    rep2 = replay(S, BR, {}, snap, day_signals(conn, day0, day0 + DAY, with_data=True), steps)
    bad = compare({a: [t for t in ts if t.exit_time < day0 + DAY] for a, ts in rep2.items()}, stored)
    assert {m["account_id"] for m in bad} >= {"V45_AMB@15m~c2", "S2_ST_ROC@15m~c3"}
    w.close()


def test_replay_detects_wrong_copy_rule(tmp_path):
    from paperbot.daily3 import extras_of
    w, steps, day0 = _extras_day(tmp_path)
    conn = w.store.conn
    ext = extras_of(conn)
    ext["V45_AMB@15m~c2"]["stop_atr"] = 2.0
    snap = json.loads(conn.execute("SELECT data FROM state WHERE k = ?", (day_key(day0),)).fetchone()[0])
    rep = replay(S, BR, {}, snap, day_signals(conn, day0, day0 + DAY, with_data=True), steps, extras=ext)
    mism = compare({a: [t for t in ts if t.exit_time < day0 + DAY] for a, ts in rep.items()},
                   stored_trades(conn, day0, day0 + DAY))
    assert [m["account_id"] for m in mism] == ["V45_AMB@15m~c2"]
    w.close()


def test_crash_gap_label(tmp_path):
    from paperbot.daily3 import CRASH_GAP_KO, extras_of, label_crash_gaps
    from tests.extras_world import T0 as W0
    gap = W0 + 3 * HOUR + 15 * MIN
    w, steps, day0 = _extras_day(tmp_path, gap_at=gap)
    conn = w.store.conn
    w.store.add_run(gap + 2 * MIN, {"commit": "x"})           # the restart that followed the kill
    w.store.commit()
    ext = extras_of(conn)
    snap = json.loads(conn.execute("SELECT data FROM state WHERE k = ?", (day_key(day0),)).fetchone()[0])
    rep = replay(S, BR, {}, snap, day_signals(conn, day0, day0 + DAY, with_data=True), steps, extras=ext)
    mism = compare({a: [t for t in ts if t.exit_time < day0 + DAY] for a, ts in rep.items()},
                   stored_trades(conn, day0, day0 + DAY))
    assert mism and all(m["account_id"] in ext for m in mism)                  # never one of the originals
    label_crash_gaps(mism, ext, conn)
    gaps = [m for m in mism if m.get("crash_gap")]
    assert gaps and all(m["label"] == CRASH_GAP_KO for m in gaps)
    first = [m for m in mism if m["account_id"] == "V45_AMB@15m~c2" or m["account_id"] == "S2_ST_ROC@15m~c3"
             or m["account_id"] == "N17_KC_RSI@5m~c1"]
    assert first and first[0].get("crash_gap")
    # the nightly message keeps a gap out of the CRITICAL count
    from paperbot.daily3 import notify_report
    from paperbot.notify import ListNotifier
    msgs = notify_report({"day": "d", "parity": {"accounts": 199, "mismatched_accounts": 0, "crash_gaps": 1},
                          "data_quality": {}}, ListNotifier())
    assert [m[0] for m in msgs] == ["INFO"] and CRASH_GAP_KO in msgs[0][1]                 # a line of the silent summary
    w.close()


def test_copy_losses_get_their_stop_what_ifs_and_skipped_shadows_use_the_copys_settings(tmp_path, monkeypatch):
    """A copy's loss card reads the stop what-ifs under its parent's id (the copy repeats the parent's signal):
    they are computed also when only the copy lost (here the parent never took the signals). A lock_start copy's
    skipped signal is replayed with its own first lock."""
    import sqlite3
    from paperbot import daily3 as D
    from paperbot.cards import cards_from_db
    from paperbot.models import SignalOutcome
    store = Store3(str(tmp_path / "c.db"))
    book = AccountBook(S, BR, store)
    book.open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"},
                        {"strategy": "A", "timeframe": "15m", "kind": "copy", "account_id": "A@15m~c1",
                         "parent": "A@15m", "data": {"v": 1, "kind": "copy",
                                                     "rule": {"template": "stop_atr", "k": 1.5}}},
                        {"strategy": "B", "timeframe": "15m", "kind": "strategy"},
                        {"strategy": "B", "timeframe": "15m", "kind": "copy", "account_id": "B@15m~c2",
                         "parent": "B@15m", "data": {"v": 1, "kind": "copy",
                                                     "rule": {"template": "lock_start", "first_lock": 0.3}}}], 0)
    steps = _steps(DAY // MIN + 1)
    rng = np.random.default_rng(4)
    skipped = None
    for ts, bars, fund in steps:
        book.step(ts, bars, fund)
        b = ts + MIN
        if b % (15 * MIN) == 0 and b < DAY - HOUR and rng.random() < 0.7:
            s = V3_SYMBOLS[int(rng.integers(6))]
            row = {"bar_close": b, "timeframe": "15m", "strategy": "A", "symbol": s,
                   "side": 1 if rng.random() < 0.5 else -1, "atr": 0.15, "ref_price": bars[s].close,
                   "ref_time": b + 5000, "delay_ms": 5000, "status": "SUBMITTED"}
            store.log_signals([row])
            book.submit("A@15m~c1", make_signal(row, stop_atr=1.5))        # only the copy takes it
            if skipped is None:
                skipped = dict(row, strategy="B")
                store.log_signals([skipped])
                store.outcome("B@15m~c2", SignalOutcome(make_signal(skipped), "SKIPPED", "in position", b))
        book.save(ts)
    store.commit()
    conn = store.conn
    lost = conn.execute("SELECT COUNT(*) FROM trades WHERE account_id = 'A@15m~c1' AND exit_reason IN ('SL','LIQ')"
                        ).fetchone()[0]
    assert lost > 0 and conn.execute("SELECT COUNT(*) FROM trades WHERE account_id = 'A@15m'").fetchone()[0] == 0
    seen = []
    real_alone = D._alone

    def alone(settings, *a, **k):
        seen.append(settings)
        return real_alone(settings, *a, **k)
    monkeypatch.setattr(D, "_alone", alone)
    rows = D.shadows(S, BR, {}, conn, "d", 0, DAY, steps)
    stop = [r for r in rows if r["kind"].startswith("stop")]
    assert len(stop) == 3 * lost and all(r["account_id"] == "A@15m" for r in stop)
    assert all(json.loads(r["data"])["actual_roe"] is None and json.loads(r["data"])["copies"] == ["A@15m~c1"]
               for r in stop)
    assert [r["account_id"] for r in rows if r["kind"] == "skipped" and r["account_id"].startswith("B@")] == \
        ["B@15m~c2"]
    assert any(getattr(x, "ladder_first_lock", None) == 0.3 for x in seen)        # the copy's own first lock
    # the copy's loss cards now show the what-ifs
    daily = sqlite3.connect(":memory:")
    daily.executescript(D.SCHEMA)
    daily.executemany("INSERT INTO shadows VALUES (:key,:day,:kind,:account_id,:symbol,:timeframe,:side,"
                      ":filled,:roe,:exit_reason,:resolved,:data)", rows)
    cards = cards_from_db(conn, S.round_trip_cost, account_id="A@15m~c1", daily_conn=daily, limit=500)
    losing = [c for c in cards if c["pnl"] < 0]
    assert losing and all(set(c["if_stop"]) == {"1.5", "2.5", "3.0"} for c in losing)
    store.close()
