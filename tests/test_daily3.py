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


# ---------------------------------------------------------------------------- paper v4: groups and the reel's exits
# One account per group (core, a 15m coin flip, DeepSeek, the reel, a 5m coin flip) run through AccountBook the way
# live3 does, with the signals built as the v4 runner builds them (sigservice): house signals with a stop distance,
# the reel's and the 5m flips' signals by the reel_engine contract (absolute stop, first target, the 19 closes in
# meta["reel"]) and their entry levels logged in signal_log data["reel"]. The day replayed is 1970-01-02 (D1); the
# live run starts 6 hours before so the 00:00 snapshot holds open positions (a reel trade among them).
import sys  # noqa: E402

import pytest  # noqa: E402

from paperbot import Signal  # noqa: E402
from paperbot.config import DS200_DEFS, v4_account_defs, v4_settings  # noqa: E402
from paperbot.engine import PaperEngine  # noqa: E402
from paperbot.aggregate import TF_MS  # noqa: E402

S4 = v4_settings()
D1 = DAY
FIVE = 5 * MIN
CORE_NAMES = [f"C{k}" for k in range(36)]
DS_ID = DS200_DEFS[0][0]
V4_PICK = {"C0@15m", "RANDOM_1@15m", f"{DS_ID}@15m", "REEL_H1@5m", "RANDOM_1@5m"}


def _v4_defs(pick=V4_PICK):
    return [d for d in v4_account_defs(CORE_NAMES) if f"{d['strategy']}@{d['timeframe']}" in pick]


def _steps_from(t0, n, seed=5):
    rng = np.random.default_rng(seed)
    px = {s: 100.0 for s in V3_SYMBOLS}
    out = []
    for i in range(n):
        t = t0 + i * MIN
        bars = {}
        for s in V3_SYMBOLS:
            o = px[s]
            c = o * np.exp(rng.normal(0, 0.0015))
            h = max(o, c) * (1 + abs(rng.normal(0, 0.0007)))
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.0007)))
            bars[s] = Bar(s, t, t + MIN - 1, o, h, lo, c, o, h, lo, c, volume=10.0)
            px[s] = c
        fund = {s: 0.0001 for s in V3_SYMBOLS} if t % (8 * HOUR) == 0 else {}
        out.append((t, bars, fund))
    return out


def reel_levels(five: list, lookback: int) -> dict:
    """Entry levels of a 5m long from the closed 5m bars (o, h, l, c) of one coin, shaped as reelsig.signal returns
    them: the stop under the lowest low of the last ``lookback`` bars, the first target = the upper band of the last
    bar, the 19 closes of bars s-18..s."""
    from paperbot.reel_engine import upper_band
    closes = [b[3] for b in five[-20:]]
    atr = float(np.mean([b[1] - b[2] for b in five[-14:]]))
    swing = min(b[2] for b in five[-lookback:])
    return {"side": 1, "bar_open": None, "atr14": atr, "swing_low": swing, "stop": swing - 0.05 * atr,
            "up_band": upper_band(closes), "closes": closes[1:]}


def reel_live_signal(row: dict, lv: dict) -> Signal:
    """The live reel / 5m coin-flip Signal by the reel_engine contract (what sigservice submits)."""
    return Signal(ts=row["bar_close"] - 1, symbol=row["symbol"], timeframe="5m", strategy_id=row["strategy"], side=1,
                  stop_price=lv["stop"], tier="best", tp_price=lv["up_band"], atr=row["atr"],
                  meta={"ref_price": row["ref_price"], "ref_time": row["ref_time"], "delay_ms": row["delay_ms"],
                        "account": f"{row['strategy']}@5m", "reel": lv})


def _v4_live_day(path, seed=24, ds_stop=1.3, pick=V4_PICK, rates=None):
    """The live UTC day D1 (plus 6 hours before and 1 hour after) of the accounts ``pick`` (``_v4_defs``)."""
    rates = rates or {"reel": 0.35, "flip5": 0.35, "core": 0.5, "flip15": 0.3, "ds": 0.5}
    store = Store3(path)
    book = AccountBook(S4, BR, store)
    t0 = D1 - 6 * HOUR
    defs = _v4_defs(pick)
    book.open_accounts(defs, t0)
    steps = _steps_from(t0, (DAY + 7 * HOUR) // MIN, seed=seed)
    rng = np.random.default_rng(seed + 1)
    five = {s: [] for s in V3_SYMBOLS}
    part: dict = {}
    by_kind = {}
    for d in defs:
        by_kind.setdefault((d["kind"], d["timeframe"]), []).append(d["strategy"])

    def log(row, sig):
        store.log_signals([row])
        book.submit(f"{row['strategy']}@{row['timeframe']}", sig)

    def base_row(b, tf, name, s, side, atr, bars):
        return {"bar_close": b, "timeframe": tf, "strategy": name, "symbol": s, "side": side, "atr": atr,
                "ref_price": bars[s].close, "ref_time": b + 9000, "delay_ms": 9000, "status": "SUBMITTED"}

    for ts, bars, fund in steps:
        book.step(ts, bars, fund)
        for s, x in bars.items():
            p = part.get(s)
            part[s] = [x.open, x.high, x.low, x.close] if p is None else \
                [p[0], max(p[1], x.high), min(p[2], x.low), x.close]
        b = ts + MIN
        if b % FIVE == 0:
            for s in V3_SYMBOLS:
                five[s].append(tuple(part.pop(s)))
            if len(five["BTCUSDT"]) >= 20:
                forced = D1 - 20 * MIN <= b < D1                # a reel trade open across 00:00
                for kind, look, p in (("reel", 6, rates["reel"]), ("random", 12, rates["flip5"])):
                    for name in by_kind.get((kind, "5m"), []):
                        if not (forced and kind == "reel") and rng.random() >= p:
                            continue
                        s = "BTCUSDT" if forced else V3_SYMBOLS[int(rng.integers(6))]
                        lv = reel_levels(five[s], look)
                        row = base_row(b, "5m", name, s, 1, lv["atr14"], bars)
                        row["data"] = {"close": five[s][-1][3], "group": "reel" if kind == "reel" else "flip",
                                       "reel": lv}
                        log(row, reel_live_signal(row, lv))
        for tf in ("15m", "30m", "1h", "4h"):
            if b % TF_MS[tf]:
                continue
            for kind, p in (("strategy", rates["core"]), ("random", rates["flip15"]), ("ds200", rates["ds"])):
                for name in by_kind.get((kind, tf), []):
                    if rng.random() >= p:
                        continue
                    s = V3_SYMBOLS[int(rng.integers(6))]
                    side = 1 if rng.random() < 0.5 else -1
                    row = base_row(b, tf, name, s, side, 0.15, bars)
                    if kind == "ds200":                         # a stop that is not 2 ATR, logged with the row
                        dist = ds_stop * row["atr"] + 0.013
                        row["data"] = {"close": bars[s].close, "group": "ds200", "stop_dist": dist}
                        sig = Signal(ts=b - 1, symbol=s, timeframe=tf, strategy_id=name, side=side, stop_price=0.0,
                                     tier="best", atr=row["atr"],
                                     meta={"stop_dist": dist, "ref_price": row["ref_price"],
                                           "ref_time": row["ref_time"], "delay_ms": row["delay_ms"],
                                           "account": f"{name}@{tf}", "ctx": {}})
                        log(row, sig)
                    else:
                        log(row, make_signal(row))
        if ts % (30 * MIN) == 0:
            book.save(ts)
    book.save(steps[-1][0])
    store.commit()
    return store, steps


class _V4Rest:
    def server_time(self):
        return D1 + DAY + 2 * MIN


@pytest.fixture(scope="module")
def v4_day(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("v4") / "paper4.db")
    store, steps = _v4_live_day(path)
    yield store, steps
    store.close()


def _v4_replay(store, steps, **kw):
    from paperbot.daily3 import engine_classes, extras_of
    conn = store.conn
    snap = json.loads(conn.execute("SELECT data FROM state WHERE k = ?", (day_key(D1),)).fetchone()[0])
    sigs = kw.pop("sigs", None) or day_signals(conn, D1, D1 + DAY, with_data=True)
    ecls = kw.pop("engine_cls", engine_classes(conn))
    rep = replay(S4, BR, {}, snap, sigs, [s for s in steps if D1 <= s[0] < D1 + DAY], extras=extras_of(conn),
                 engine_cls=ecls)
    stored = stored_trades(conn, D1, D1 + DAY)
    return compare({a: [t for t in ts if t.exit_time < D1 + DAY] for a, ts in rep.items()}, stored), rep, stored, snap


def test_v4_logged_reel_signal_round_trips_to_the_live_signal():
    """make_signal rebuilds the reel's (and a 5m flip's) live Signal exactly from its signal_log row; a house row
    keeps its 2 ATR stop, and a logged stop_dist wins unless the caller asks for an ATR multiple."""
    five = [(100 + k * 0.1, 100.5 + k * 0.1, 99.5 + k * 0.1, 100.2 + k * 0.1) for k in range(30)]
    lv = reel_levels(five, 6)
    row = {"bar_close": D1 + FIVE, "timeframe": "5m", "strategy": "REEL_H1", "symbol": "ETHUSDT", "side": 1,
           "atr": lv["atr14"], "ref_price": 103.1, "ref_time": D1 + FIVE + 9000, "delay_ms": 9000,
           "status": "SUBMITTED", "data": json.dumps({"close": 103.0, "group": "reel", "reel": lv})}
    live = reel_live_signal(row, lv)
    assert make_signal(row) == live
    assert make_signal(row, stop_atr=1.5) == live                   # an ATR multiple never applies to the reel
    assert "stop_dist" not in make_signal(row).meta
    assert make_signal(row, ref=102.9).meta["ref_price"] == 102.9
    from paperbot.reel_engine import signal_problem
    assert signal_problem(make_signal(row)) is None
    bad = dict(row, data=json.dumps({"reel": {"stop": "x"}}))
    assert signal_problem(make_signal(bad)) is not None             # rejected by the engine, as live would
    house = dict(row, timeframe="15m", strategy="C0", atr=0.2, data=json.dumps({"ctx": {"regime": "box"}}))
    assert make_signal(house).meta["stop_dist"] == pytest.approx(2 * 0.2)
    logged = dict(house, data=json.dumps({"stop_dist": 0.77, "lev_group": "normal"}))
    assert make_signal(logged).meta["stop_dist"] == 0.77 and make_signal(logged).meta["lev_group"] == "normal"
    assert make_signal(logged, stop_atr=3.0).meta["stop_dist"] == pytest.approx(0.6)
    no_data = {k: v for k, v in house.items() if k != "data"}
    assert make_signal(no_data).meta == {"stop_dist": pytest.approx(0.4), "ref_price": 103.1,
                                         "ref_time": D1 + FIVE + 9000, "delay_ms": 9000, "account": "C0@15m"}


def test_v4_engine_classes_extras_and_groups(v4_day, tmp_path, monkeypatch):
    from paperbot import accounts as A
    from paperbot.accounts import HeldEngine
    from paperbot.daily3 import account_groups, engine_classes, extras_of
    from paperbot.reel_engine import ReelEngine
    store, _ = v4_day
    conn = store.conn
    assert engine_classes(conn) == {"REEL_H1@5m": ReelEngine, "RANDOM_1@5m": ReelEngine}
    assert extras_of(conn) == {}                                     # ds200 and reel are originals, not extras
    assert account_groups(conn) == {"C0@15m": "core", "RANDOM_1@15m": "flip", f"{DS_ID}@15m": "ds200",
                                    "REEL_H1@5m": "reel", "RANDOM_1@5m": "flip"}
    # the live book built the same classes
    book = AccountBook(S4, BR, store)
    assert book.load()
    assert {a: type(e) for a, e in book.engines.items() if type(e) is not PaperEngine} == engine_classes(conn)

    # a reel engine module that cannot be imported: those two accounts are held (as the live book holds them)
    monkeypatch.setitem(sys.modules, "paperbot.reel_engine", None)
    assert engine_classes(conn) == {"REEL_H1@5m": HeldEngine, "RANDOM_1@5m": HeldEngine}
    monkeypatch.undo()
    assert A.original_engine_cls("reel", "5m") is ReelEngine
    # a v3-shaped database (no data, no new kinds): no own engines, a 5m coin flip there keeps PaperEngine
    v3 = Store3(str(tmp_path / "v3.db"))
    AccountBook(S, BR, v3).open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"},
                                          {"strategy": "RANDOM_1", "timeframe": "5m", "kind": "random"}], 0)
    assert engine_classes(v3.conn) == {} and set(account_groups(v3.conn).values()) == {"core", "flip"}
    v3.close()


REEL_EXIT_ACCOUNTS = ("REEL_H1@5m", "RANDOM_1@5m")


def test_v4_one_account_per_group_replays_to_zero_mismatch(v4_day):
    store, steps = v4_day
    mism, rep, stored, snap = _v4_replay(store, steps)
    assert mism == [], [(m["account_id"], m["replayed"][:2], m["stored"][:2]) for m in mism]
    assert set(rep) == V4_PICK
    for aid in V4_PICK:
        assert len(stored.get(aid, [])) >= 2, aid
    reasons = {t["exit_reason"] for a in REEL_EXIT_ACCOUNTS for t in stored[a]}
    assert {"SL", "TP"} <= reasons <= {"SL", "TP", "TIME", "LIQ"}       # the reel's exits, never the ladder's LOCK
    # the 00:00 snapshot held a reel trade in the middle: the replay continued it from its saved exit state
    for aid in REEL_EXIT_ACCOUNTS:
        pos = snap["engines"][aid]["position"]
        assert pos and "reel_exit" in pos["signal"]["meta"], aid
        first = stored[aid][0]
        assert first["entry_time"] < D1 <= first["exit_time"]
    # without the reel's engine class exactly the reel and the 5m coin flip do not replay
    bad, *_ = _v4_replay(store, steps, engine_cls={})
    assert {m["account_id"] for m in bad} == set(REEL_EXIT_ACCOUNTS)


def test_v4_replay_uses_the_logged_stop_distance(v4_day):
    """A non-ATR stop (DeepSeek here, logged in the row's data.stop_dist) replays to parity, and only because the
    replay reads it: with the logged distance removed the replay falls back to 2 ATR and that account mismatches."""
    store, steps = v4_day
    sigs = day_signals(store.conn, D1, D1 + DAY, with_data=True)
    ds = [d for lst in sigs.values() for d in lst if d["strategy"] == DS_ID]
    assert ds and all(json.loads(d["data"])["stop_dist"] != pytest.approx(2 * d["atr"]) for d in ds)
    for d in ds:
        x = json.loads(d["data"])
        del x["stop_dist"]
        d["data"] = json.dumps(x)
    bad, *_ = _v4_replay(store, steps, sigs=sigs)
    assert {m["account_id"] for m in bad} == {f"{DS_ID}@15m"}


def test_v4_run_day_split_report_and_shadows(v4_day, tmp_path, monkeypatch):
    import sqlite3
    import time as _time

    from paperbot import daily3 as D
    from paperbot.notify import ListNotifier
    store, steps = v4_day
    conn = store.conn
    monkeypatch.setattr(D, "fetch_steps", lambda rest, syms, a, b: [s for s in steps if a <= s[0] < b])
    out = sqlite3.connect(str(tmp_path / "daily4.db"))
    out.executescript(D.SCHEMA)
    t0 = _time.perf_counter()
    dsc = tmp_path / "dscheck"
    dsc.mkdir()
    (dsc / "last.txt").write_text("딥시크 밤 재계산 1970-01-01 (UTC): 불일치 0 · 일치 10/10\n", encoding="utf-8")
    rep = D.run_day(conn, out, _V4Rest(), S4, BR, {}, "1970-01-02", dscheck_dir=str(dsc))
    rep["runtime_s"] = _time.perf_counter() - t0
    par = rep["parity"]
    assert par["accounts"] == 5 and par["mismatched_accounts"] == 0
    one = {"accounts": 1, "ok": 1, "mismatched": 0, "early_kline": 0, "crash_gaps": 0}
    assert par["groups"] == {"core": one, "ds200": one, "reel": one, "flip": {**one, "accounts": 2, "ok": 2}}
    assert list(par["groups"]) == ["core", "ds200", "reel", "flip"]
    per = {}
    for aid, n in conn.execute("SELECT account_id, COUNT(*) FROM trades WHERE exit_time >= ? AND exit_time < ? "
                               "GROUP BY account_id", (D1, D1 + DAY)):
        per[aid] = n
    n = sum(per.values())
    assert rep["trades"] == {"total": n, "groups": {
        "core": per["C0@15m"], "ds200": per[f"{DS_ID}@15m"], "reel": per["REEL_H1@5m"],
        "flip": per["RANDOM_1@15m"] + per["RANDOM_1@5m"]}}
    # shadows: the reel-exit accounts get limit and skipped shadows on their own engine, no house what-ifs
    tv = rep["shadows"]["trade_variants"]
    assert tv["own_exit_trades"] == per["REEL_H1@5m"] + per["RANDOM_1@5m"]
    assert tv["closed"] == n - tv["own_exit_trades"] and tv["no_signal"] == 0
    kinds = {}
    for aid, kind, reason in out.execute("SELECT account_id, kind, exit_reason FROM shadows"):
        kinds.setdefault(aid, {}).setdefault(kind, []).append(reason)
    for aid in REEL_EXIT_ACCOUNTS:
        assert set(kinds[aid]) <= {"limit", "skipped"} and kinds[aid]["skipped"], (aid, set(kinds[aid]))
        assert {r for r in kinds[aid]["limit"] + kinds[aid]["skipped"] if r} <= {"SL", "TP", "TIME", "LIQ"}
    assert {"base", "lev20", "tp1R"} <= set(kinds[f"{DS_ID}@15m"]) and {"base"} <= set(kinds["C0@15m"])
    # a signal the reel's own entry rules skipped is no "skipped" shadow; one skipped "in position" is
    skips = dict(conn.execute("SELECT reason LIKE 'reel:%', COUNT(*) FROM outcomes WHERE status = 'SKIPPED' "
                              "AND step_ts >= ? AND step_ts < ? AND account_id IN (?, ?) GROUP BY 1",
                              (D1, D1 + DAY, *REEL_EXIT_ACCOUNTS)).fetchall())
    assert skips[1] > 0 and sum(len(kinds[a]["skipped"]) for a in REEL_EXIT_ACCOUNTS) == skips[0]
    # the 09:20 text: parity and trades by group
    msgs = D.notify_report(rep, ListNotifier(), trades_day=n)
    assert msgs[0][0] == "INFO"
    assert "재계산 일치 5/5 (매매법 1/1 · 딥시크 1/1 · 5분 단타 1/1 · 동전 2/2)" in msgs[0][1]
    assert (f"거래 {n}건 (매매법 {per['C0@15m']} · 딥시크 {per[f'{DS_ID}@15m']} · 5분 단타 {per['REEL_H1@5m']} · "
            f"동전 {per['RANDOM_1@15m'] + per['RANDOM_1@5m']})") in msgs[0][1]
    # G28: the limit and skipped shadows by group, the totals unchanged; the text splits core / reel, DeepSeek counted
    sg = rep["shadows"]["groups"]
    assert list(sg) == ["core", "ds200", "reel", "flip"]
    for k in ("limit_signals", "limit_filled", "skipped"):
        assert sum(x[k] for x in sg.values()) == rep["shadows"][k], k
    rows = {}
    for aid, kind, filled in out.execute("SELECT account_id, kind, filled FROM shadows WHERE kind IN "
                                         "('limit', 'skipped')"):
        rows.setdefault(aid, []).append((kind, filled))
    assert sg["reel"]["limit_signals"] == sum(1 for k, _ in rows.get("REEL_H1@5m", []) if k == "limit") > 0
    assert sg["ds200"]["skipped"] == sum(1 for k, _ in rows.get(f"{DS_ID}@15m", []) if k == "skipped")
    text = msgs[0][1]
    assert (f"\n지정가였다면 체결 매매법 {sg['core']['limit_filled']}/{sg['core']['limit_signals']} · 5분 단타 "
            f"{sg['reel']['limit_filled']}/{sg['reel']['limit_signals']}\n") in text
    assert f"\n포지션 중이라 놓친 신호 매매법 {sg['core']['skipped']} · 5분 단타 {sg['reel']['skipped']}\n" in text
    assert (f"\n딥시크 (개수만): 지정가 체결 {sg['ds200']['limit_filled']}/{sg['ds200']['limit_signals']} · "
            f"놓친 신호 {sg['ds200']['skipped']}") in text
    assert "동전" not in text.split("거래 ")[1].split("\n", 1)[1]          # the flips' shadows: the report only
    # the DeepSeek recomputation's last line (the night before's, its own day); missing: said so
    assert rep["dscheck"].startswith("딥시크 밤 재계산 1970-01-01 (UTC): 불일치 0")
    assert "\n딥시크 밤 재계산 1970-01-01 (UTC): 불일치 0 · 일치 10/10" in text
    gone = D.notify_report({**rep, "dscheck": None}, ListNotifier(), trades_day=n)[0][1]
    assert "\n딥시크 밤 재계산: 결과 없음 (" in gone
    assert D.dscheck_line(str(tmp_path / "nowhere")) is None and D.dscheck_line(None) is None


def test_v4_notify_report_shadow_and_stop_slippage_lines():
    """G28 on a report: numbers for core and the reel (and extras when they had any), one DeepSeek count line, no
    coin-flip line; the stop slippage per group; a v3 report keeps its text."""
    from paperbot.daily3 import notify_report
    from paperbot.notify import ListNotifier, usd

    def sh(sig, fil, skip):
        return {"limit_signals": sig, "limit_filled": fil, "limit_mean_roe": None, "skipped": skip}

    def cell(exits, measured, real=0.0, paper=0.0, diff=None):
        return {"exits": exits, "measured": measured, "real_bps_median": real, "paper_bps_median": paper,
                "diff_usd_total": diff}
    rep = {"day": "2026-10-07", "parity": {"accounts": 331, "mismatched_accounts": 0},
           "shadows": {"limit_signals": 120, "limit_filled": 60, "skipped": 30,
                       "groups": {"core": sh(40, 25, 7), "ds200": sh(70, 30, 20), "reel": sh(1, 0, 0),
                                  "flip": sh(9, 5, 3)}},
           "stop_slippage": {"overall": cell(20, 18, 3.0, 1.0, 5.0),
                             "groups": {"core": cell(6, 6, 2.5, 1.0, 1.25), "ds200": cell(12, 10, 3.5, 1.0, 3.5),
                                        "reel": cell(1, 1, 4.0, 1.0, 0.25), "flip": cell(1, 1)}},
           "data_quality": {}}
    text = notify_report(rep, ListNotifier())[0][1]
    assert text == ("🔎 매일 점검 · 10/07\n\n재계산 일치 331/331\n지정가였다면 체결 매매법 25/40 · 5분 단타 0/1\n"
                    "포지션 중이라 놓친 신호 매매법 7 · 5분 단타 0\n"
                    f"손절 체결 매매법 6건: 실제 2.5bp vs paper 1.0bp\n→ paper보다 {usd(1.25)}\n"
                    f"손절 체결 5분 단타 1건: 실제 4.0bp vs paper 1.0bp\n→ paper보다 {usd(0.25)}\n"
                    "딥시크 (개수만): 지정가 체결 30/70 · 놓친 신호 20 · 손절 12건\n빠진 1분봉 0")
    # extras with signals get their numbers; a v3 report (no DeepSeek / reel group) keeps the old lines
    rep["shadows"]["groups"]["extra"] = sh(4, 1, 2)
    assert "\n지정가였다면 체결 매매법 25/40 · 5분 단타 0/1 · 추가 계좌 1/4\n" in notify_report(rep, ListNotifier())[0][1]
    v3 = {**rep, "shadows": {"limit_signals": 49, "limit_filled": 30, "skipped": 10,
                             "groups": {"core": sh(40, 25, 7), "flip": sh(9, 5, 3)}},
          "stop_slippage": {"overall": cell(7, 7, 2.0, 1.0, 1.0), "groups": {"core": cell(6, 6), "flip": cell(1, 1)}}}
    t3 = notify_report(v3, ListNotifier())[0][1]
    assert "\n지정가였다면 체결 30/49\n포지션 중이라 놓친 신호 10\n" in t3 and "\n손절 체결 7건: 실제 2.0bp" in t3


def test_start_day_is_a_silent_line_not_a_missing_snapshot(tmp_path, monkeypatch):
    """G25: the run's start day has no 00:00 snapshot by design: INFO "시작한 날: 재계산 없음" (report ``start_day``,
    parity still a string), the day before the run likewise; a later day without its snapshot stays the WARN."""
    import sqlite3

    from paperbot import daily3 as D
    from paperbot.notify import ListNotifier
    store = Store3(str(tmp_path / "p.db"))
    started = DAY + 17 * HOUR + 5 * MIN
    AccountBook(S, BR, store).open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"},
                                             {"strategy": "RANDOM_1", "timeframe": "15m", "kind": "random"}], started)
    store.commit()
    store.add_account("A@15m~c1", "A", "15m", "copy", DAY - HOUR, "v3", parent="A@15m")   # an extra: not the start
    store.commit()
    assert D.run_start_ts(store.conn) == started
    monkeypatch.setattr(D, "fetch_steps", lambda rest, syms, a, b: [])

    def night(day):
        out = sqlite3.connect(":memory:")
        out.executescript(D.SCHEMA)
        return D.run_day(store.conn, out, _V4Rest(), S, BR, {}, day)
    rep = night("1970-01-02")
    assert rep["start_day"] == {"run_start": started, "before_run": False}
    assert isinstance(rep["parity"], str) and rep["parity"].startswith("start day: the run started at 1970-01-02 17:05")
    msgs = D.notify_report(rep, ListNotifier(), trades_day=0)
    assert [m[0] for m in msgs] == ["INFO"] and msgs[0][1].startswith("🔎 매일 점검 · 01/02\n\n시작한 날: 재계산 없음 (")
    before = night("1970-01-01")
    assert before["start_day"]["before_run"] is True
    assert "\n시작 전 날: 재계산 없음" in D.notify_report(before, ListNotifier())[0][1]
    later = night("1970-01-03")
    assert "start_day" not in later and later["parity"].startswith("no 00:00 snapshot")
    assert D.notify_report(later, ListNotifier())[0][0] == "WARN"
    store.close()


def test_stop_slippage_reads_core_and_reel_exits_first_and_splits_by_group(tmp_path, monkeypatch):
    """G28: a bigger DeepSeek exit no longer takes the cap from a core exit; the summary has ``groups``."""
    import paperbot.daily3 as D
    from test_slipcost import SLIP, T0, Rest, paper, world_trades
    exits = [("F9_FVG@15m", "BTCUSDT", 1, 100.0, 50.0, 99.5 * (1 - SLIP), "SL", T0),        # the larger notional
             ("A@1h", "ETHUSDT", -1, 50.0, 1.0, 50.0 * (1 + SLIP), "SL", 40 * MIN + MIN - 1)]
    conn = paper(tmp_path, exits)
    conn.execute("UPDATE accounts SET kind = 'ds200' WHERE account_id = 'F9_FVG@15m'")
    conn.commit()
    monkeypatch.setattr(D, "STOP_MAX_MINUTES", 1)
    rest = Rest(world_trades())
    rows, s = D.stop_slippage(conn, rest, S, "1970-01-01", 0, DAY, sleep=lambda x: None)
    assert [c["symbol"] for c in rest.calls] == ["ETHUSDT"]
    assert {r["account_id"]: r["status"] for r in rows} == {"A@1h": "ok", "F9_FVG@15m": "cap"}
    assert s["groups"]["core"]["measured"] == 1 and s["groups"]["ds200"] == {**s["groups"]["ds200"], "exits": 1,
                                                                             "measured": 0}
    assert list(s["groups"]) == ["core", "ds200"]


def test_v4_notify_report_split_text():
    from paperbot.daily3 import notify_report
    from paperbot.notify import ListNotifier

    def g(a, mism=0, early=0, gaps=0):
        return {"accounts": a, "ok": a - mism - early - gaps, "mismatched": mism, "early_kline": early,
                "crash_gaps": gaps}
    rep = {"day": "2026-10-07",
           "parity": {"accounts": 331, "mismatched_accounts": 2, "early_kline": 1,
                      "groups": {"core": g(144, early=1), "ds200": g(171, mism=1), "reel": g(1, mism=1),
                                 "flip": g(15)}},
           "trades": {"total": 812, "groups": {"core": 300, "ds200": 480, "reel": 2, "flip": 30}},
           "data_quality": {}}
    msgs = notify_report(rep, ListNotifier(), trades_day=812)
    assert [m[0] for m in msgs] == ["CRITICAL"]
    assert msgs[0][1] == ("재계산 불일치 · 10/07\n\n계좌 2개의 거래가 paper와 다름 (딥시크 1 · 5분 단타 1)\n"
                          "(그 밖에 1개는 확정 전 1분봉: 정상)\n운영 감사관 확인 필요\n자세히: daily3.db mismatches\n\n"
                          "매일 점검\n재계산 일치 328/331 (매매법 143/144 · 딥시크 170/171 · 5분 단타 0/1 · 동전 15/15)\n"
                          "거래 812건 (매매법 300 · 딥시크 480 · 5분 단타 2 · 동전 30)\n빠진 1분봉 0")
    ok = {**rep, "parity": {"accounts": 331, "mismatched_accounts": 0,
                            "groups": {"core": g(144), "ds200": g(171), "reel": g(1), "flip": g(15)}}}
    text = notify_report(ok, ListNotifier(), trades_day=812)[0][1]
    assert "재계산 일치 331/331 (매매법 144/144 · 딥시크 171/171 · 5분 단타 1/1 · 동전 15/15)\n" in text


def test_v4_full_shape_day_331_of_331_and_runtime(tmp_path, monkeypatch):
    """The whole v4 shape (331 accounts, config.v4_account_defs) on one synthetic day at the house signal rate
    (0.013 per coin and bar, 6 coins): parity 331/331 split 144 / 171 / 1 / 15, and the night's runtime recorded
    (the server's 4 vCPU run the night beside the live runner; on the dev box this run_day takes about 6 s)."""
    import sqlite3
    import time as _time

    from paperbot import daily3 as D
    p_any = 1 - (1 - 0.013) ** 6
    pick = {f"{d['strategy']}@{d['timeframe']}" for d in v4_account_defs(CORE_NAMES)}
    assert len(pick) == 331
    store, steps = _v4_live_day(str(tmp_path / "paper4.db"), pick=pick,
                                rates={"reel": p_any, "flip5": p_any, "core": p_any, "flip15": p_any, "ds": p_any})
    monkeypatch.setattr(D, "fetch_steps", lambda rest, syms, a, b: [s for s in steps if a <= s[0] < b])
    out = sqlite3.connect(str(tmp_path / "daily4.db"))
    out.executescript(D.SCHEMA)
    t0 = _time.perf_counter()
    rep = D.run_day(store.conn, out, _V4Rest(), S4, BR, {}, "1970-01-02")
    took = _time.perf_counter() - t0
    print(f"run_day on a synthetic 331-account day: {took:.1f} s, {rep['trades']['total']} trades, "
          f"{out.execute('SELECT COUNT(*) FROM shadows').fetchone()[0]} shadow rows")
    par = rep["parity"]
    assert par["accounts"] == 331 and par["mismatched_accounts"] == 0
    assert {g: (x["accounts"], x["ok"]) for g, x in par["groups"].items()} == \
        {"core": (144, 144), "ds200": (171, 171), "reel": (1, 1), "flip": (15, 15)}
    assert all(rep["trades"]["groups"][g] > 0 for g in ("core", "ds200", "reel", "flip"))
    assert took < 120
    store.close()
