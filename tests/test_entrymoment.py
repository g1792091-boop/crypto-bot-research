"""agents/entrymoment.py: closed strategy trades by the moment of entry (strength, volatility, candle shape,
liquidation bursts, holding time, funding, weekday) and the signals not taken; descriptive, bounded, read-only."""

import json
import sqlite3

import numpy as np
import pytest

from paperbot.agents import entrymoment as EM
from paperbot.agents import riskreward as RRW
from paperbot.flow import _schema as flow_schema
from paperbot.liqstream import SCHEMA as LIQ_SCHEMA
from paperbot.archive import SCHEMA as MARKET_SCHEMA

from test_rooms import HOUR, MIN, S, World, kst, rec

M15 = 15 * MIN
T1 = kst(2026, 10, 7, 9, 0)              # entry (= signal bar close) of trade 1: a hammer after a burst
T2 = T1 + 6 * HOUR                       # entry of trade 2: bullish engulfing, no burst
NOW = T2 + 6 * HOUR
STRONG = {"side": 1, "features": [{"name": "band_pierce_atr", "value": 5.0}, {"name": "rsi_depth", "value": 20.0}]}


def bar15(t0, o, h, l, c):
    """15 one-minute rows that make one 15m bar (o, h, l, c)."""
    rows = []
    for k in range(15):
        mo = o if k == 0 else (o + c) / 2
        mc = c if k == 14 else (o + c) / 2
        mh, ml = max(mo, mc), min(mo, mc)
        if k == 5:
            ml = l
        if k == 10:
            mh = h
        rows.append((t0 + k * MIN, "BTCUSDT", mo, mh, ml, mc))
    return rows


def fill_bars(world, start, end, special):
    """Alternating green / red 15m bars of range 1 from ``start`` to ``end`` with ``special`` {bar open: ohlc}."""
    rows, k, t = [], 0, start
    while t < end:
        if t in special:
            rows += bar15(t, *special[t])
        elif k % 2:
            rows += bar15(t, 100.2, 100.5, 99.5, 99.8)              # red
        else:
            rows += bar15(t, 99.8, 100.5, 99.5, 100.2)              # green
        k += 1
        t += M15
    world.store.conn.executemany(
        "INSERT INTO live_bars (ts, symbol, open, high, low, close, processed_at) VALUES (?,?,?,?,?,?,0)", rows)
    world.store.commit()


@pytest.fixture
def setup(tmp_path):
    w = World(tmp_path)
    # trade 1: a long on a hammer bar (signal bar [T1-15m, T1)), strength recorded; trade 2: bullish engulfing
    special = {T1 - M15: (99.8, 100.4, 97.0, 100.3),
               T2 - 2 * M15: (100.2, 100.3, 99.85, 99.9),                  # red, body 0.3
               T2 - M15: (99.8, 100.5, 99.7, 100.4)}                       # green, covers it
    fill_bars(w, T1 - 6 * 24 * HOUR, T2 + HOUR, special)
    w.store.trade(f"{S}@15m", rec(S, "15m", 4.0, T1 + 3 * HOUR, context={"regime": "trend_up", "strength": STRONG}))
    w.store.trade(f"{S}@15m", rec(S, "15m", -3.0, T2 + 3 * HOUR))
    w.store.commit()
    liq = str(tmp_path / "liq.db")
    c = sqlite3.connect(liq)
    c.executescript(LIQ_SCHEMA)
    base = T1 - 3 * 24 * HOUR
    rows = [(base + k * 37 * MIN, base + k * 37 * MIN, "BTCUSDT", "SELL", 1.0, 100.0, 100.0, 0)
            for k in range(60)]                                             # 60 small minutes of $100
    rows.append((T1 - 5 * MIN, T1 - 5 * MIN, "BTCUSDT", "BUY", 10_000.0, 100.0, 100.0, 0))   # shorts squeezed
    c.executemany("INSERT INTO liq (event_ts, trade_ts, symbol, side, filled_qty, avg_price, price, received_ts) "
                  "VALUES (?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    flow = str(tmp_path / "flow.db")
    c = sqlite3.connect(flow)
    c.executescript(flow_schema())
    c.execute("INSERT INTO premium5m VALUES ('BTCUSDT', ?, 0, 0, 0, 0.0008, 0)", (T1 - 10 * MIN,))
    c.commit()
    c.close()
    market = str(tmp_path / "market.db")
    c = sqlite3.connect(market)
    c.executescript(MARKET_SCHEMA)
    c.execute("INSERT INTO funding VALUES ('BTCUSDT', ?, -0.0002, 100, 0)", (T2 - HOUR,))
    c.commit()
    c.close()
    return w, {"liq_path": liq, "flow_path": flow, "market_path": market}


def test_small_n_is_the_riskreward_convention():
    assert EM.SMALL_N == RRW.SMALL_N


def test_each_trade_gets_the_buckets_of_its_entry_moment(setup):
    w, paths = setup
    feat = EM.features(w.paper(), NOW, **paths)
    r1, r2 = feat["rows"]
    b1, b2 = r1["b"], r2["b"]
    assert b1["strength"] == "strong" and b2["strength"] == "unknown"
    # hammer: lower wick 2.8 of range 3.4, upper 0.1 -> pin bar in the long's direction; the bar before is green too
    assert b1["pattern"] == "pin_with" and b1["streak"] == "with_2" and b1["close_loc"] == "strong"
    assert b1["wick_against"] == "<0.2" and b1["wick_with"] == "0.4+"
    assert b1["volatility"] == "high" and b1["body"] == "0.3-1"
    assert b1["liq"] == "burst_with" and b2["liq"] == "none"
    # premium 0.08% -> 0.08% + clamp(0.01% - 0.08%) = 0.03% (high); trade 2: settled -0.02% an hour before
    assert b1["funding"] == "high" and b2["funding"] == "neg"
    assert feat["coverage"]["funding_source"] == {"settled": 1, "premium_est": 1, "none": 0}
    assert b2["pattern"] == "engulf_with" and b1["hold"] == "2h-8h"
    assert b1["weekday"] == "수"
    assert r1["eq"] == pytest.approx(4.0 / 1000)
    assert feat["coverage"]["candle"] == 2 and feat["coverage"]["liq"] == 2


def test_candle_rules_mirror_for_a_short():
    b = EM.resample(*_arrs([(0, 100.2, 100.3, 97.0, 100.0)]), M15)
    b["atr"] = np.array([1.0])
    got = EM.candle(b, 0, -1)
    # a hammer pushes up: against a short; the long lower wick is the wick the short does not want
    assert got["pattern"] == "pin_against" and got["wick_against"] == "0.4+" and got["close_loc"] == "weak"
    doji = EM.resample(*_arrs([(0, 100.0, 100.5, 99.5, 100.05)]), M15)
    doji["atr"] = np.array([1.0])
    assert EM.candle(doji, 0, 1)["pattern"] == "doji" and EM.candle(doji, 0, 1)["streak"] == "doji"


def _arrs(bars):
    rows = []
    for t0, o, h, l, c in bars:
        rows += bar15(t0, o, h, l, c)
    a = np.array([r[:1] + r[2:] for r in rows], float)
    return a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4]


def test_unknown_without_bars_liquidations_or_funding(tmp_path):
    w = World(tmp_path)
    w.store.trade(f"{S}@15m", rec(S, "15m", 1.0, T1))
    w.store.commit()
    feat = EM.features(w.paper(), NOW)
    b = feat["rows"][0]["b"]
    assert {b[k] for k in ("volatility", "body", "pattern", "liq", "funding", "strength")} == {"unknown"}
    assert feat["coverage"]["liq_note"] == "liq.db 없음" and feat["coverage"]["bars_note"]


def test_packet_cells_small_flags_multiple_comparisons_and_size(setup):
    w, paths = setup
    for k in range(30):                                                    # more trades, outside the bar history
        w.store.trade(f"{S}@1h", rec(S, "1h", 2.0 if k % 3 else -2.0, T2 - (k + 40) * HOUR))
    w.store.commit()
    pk = EM.packet(w.paper(), NOW, daily_ro=w.daily, names_ko={S: "켈트너"}, **paths)
    assert pk["trades"] == 32 and pk["min_n"] == EM.SMALL_N
    cell = pk["all"]["hold"]["2h-8h"]
    assert cell["n"] == 32 and "small" not in cell and set(cell) >= {"n", "wr", "roe", "eq"}
    assert pk["all"]["strength"]["strong"] == {**pk["all"]["strength"]["strong"], "n": 1, "small": True}
    mc = pk["multiple_comparisons"]
    assert mc["buckets_examined"] > 10 and mc["chance_hits_at_5pct"] == round(0.05 * mc["buckets_not_small"], 1)
    assert "가설" in pk["note"] and EM.compact_bytes(pk) < EM.MAX_BYTES
    assert all(not n.get("small") and n["n"] >= EM.SMALL_N for n in pk["notable"])
    assert pk["skipped_signals"]["skipped_outcome"]["signals"] == 0


def test_packet_stays_bounded_with_many_strategies(tmp_path):
    w = World(tmp_path)
    for s in range(36):
        name = f"X{s:02d}"
        for tf in ("5m", "15m", "30m", "1h", "4h"):
            w.store.add_account(f"{name}@{tf}", name, tf, "strategy", T1 - 30 * 24 * HOUR, "paper-v3")
            for k in range(12):
                w.store.trade(f"{name}@{tf}", rec(name, tf, (-1) ** k * (k + s % 7), T1 - (k * 7 + s) * HOUR,
                                                  symbol=("BTCUSDT", "ETHUSDT")[k % 2]))
    w.store.commit()
    pk = EM.packet(w.paper(), NOW)
    assert pk["trades"] == 36 * 5 * 12 and EM.compact_bytes(pk) < EM.MAX_BYTES
    brief = EM.strategy_brief(w.paper(), "X03", NOW)
    assert brief["trades"] == 60 and EM.compact_bytes(brief) < EM.BRIEF_MAX_BYTES
    assert brief["buckets"]["hold"] and "unknown" not in brief["buckets"].get("liq", {})


def test_skipped_signals_report_counts_and_the_nightly_shadow_outcome(setup):
    w, paths = setup
    sig = {"signal": {"ts": T1 - 1, "symbol": "ETHUSDT"}, "detail": {}}
    for k in range(3):
        w.store.conn.execute("INSERT INTO outcomes (account_id, step_ts, status, reason, symbol, data) VALUES "
                             "(?,?,?,?,?,?)", (f"{S}@15m", T1 + k * MIN, "SKIPPED", "in position", "ETHUSDT",
                                               json.dumps(sig)))
    w.store.conn.execute("INSERT INTO outcomes (account_id, step_ts, status, reason, symbol, data) VALUES "
                         "(?,?,?,?,?,?)", ("RANDOM_1@15m", T1, "SKIPPED", "in position", "ETHUSDT", "{}"))
    w.store.commit()
    for k, roe in enumerate((0.2, -0.1, None)):
        w.daily.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"skipped|{S}@15m|ETHUSDT|{T1 + k * M15}", "2026-10-07", "skipped", f"{S}@15m", "ETHUSDT",
                         "15m", 1, None, roe, None, int(roe is not None), "{}"))
    w.daily.commit()
    sk = EM.skipped_signals(w.paper(), w.daily, 0, NOW)
    assert sk["not_taken"] == {"SKIPPED:in position": 3}                   # the coin flip's is left out
    o = sk["skipped_outcome"]
    assert o["signals"] == 3 and o["resolved"] == 2 and o["roe"] == pytest.approx(0.05) and o["small"] is True
    none = EM.skipped_signals(w.paper(), None, 0, NOW)
    assert "기록 없음" in none["skipped_outcome"]["note"]


def test_dash_view_and_strategy_brief(setup):
    w, paths = setup
    v = EM.dash_view(w.paper(), NOW, daily_ro=w.daily, **paths)
    assert v["trades"] == 2 and v["dims"] == list(EM.DIMS) and v["bucket_order"]["pattern"][0] == "engulf_with"
    assert "multiple_comparisons" in v and "all" in v
    b = EM.strategy_brief(w.paper(), S, NOW, **paths)
    assert b["trades"] == 2 and b["buckets"]["pattern"]["pin_with"]["small"] is True
    assert EM.strategy_brief(w.paper(), "NOPE", NOW)["trades"] == 0
    assert EM.packet(None, NOW) == {"error": "paper3.db 없음"}


def test_the_module_only_reads(setup, tmp_path):
    w, paths = setup
    before = {p: open(p, "rb").read() for p in paths.values()}
    EM.packet(w.paper(), NOW, daily_ro=w.daily, **paths)
    assert {p: open(p, "rb").read() for p in paths.values()} == before
