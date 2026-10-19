"""paperbot/livesim.py: one signal on the paper bot's own engine (a fresh ComboEngine of the config it runs) over the rule bot's
1m bars, for 못 탄 신호 성적 (paperbot/livemissed.py).

The world (tests/livesim_world.py) is the combined paper bot REALLY running (ComboRunner + AccountBook + ComboEngine) over a
hand-made paper3.db, so its trades and outcomes are its own records:
- parity: every ENTERED signal of the paper account, rebuilt from its outcome and simulated with the account's wallet at that
  moment and the same funding rates, gives the paper bot's own trade: entry time, price, stop, leverage, margin; exit time,
  price, reason (LOCK and SL; a research 1 % stop; a trade that paid funding), net ROE and pnl;
- without the funding rates (the watcher has none) only the funding differs; a bigger wallet makes a bigger trade, the ROE
  stays;
- still open: the bars run out first (the latest net ROE, the stop and lock of the paper bot's own open position at that
  minute);
- no_data: no 1m bar at the entry minute (never a made-up price); refused: a stop that cannot fit inside liquidation.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livesim_world as W  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot import livesim as LS  # noqa: E402
from paperbot.ladder import net_roe  # noqa: E402
from paperbot.livepnl import open_ro  # noqa: E402

MIN = W.MIN


def _records(w):
    """(rig, outcomes [(step, status, reason, symbol, signal json, detail)], trades [dict]) of the paper bot's database."""
    pc = open_ro(w.paper_db)
    try:
        run = json.loads(pc.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()[0])
        outs = [(int(s), st, r, sym, json.loads(d)) for s, st, r, sym, d in pc.execute(
            "SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? ORDER BY id", (C.ACCOUNT,))]
        trades = [json.loads(d) | {"equity_after": eq} for d, eq in pc.execute(
            "SELECT data, equity_after FROM trades WHERE account_id = ? ORDER BY exit_time, id", (C.ACCOUNT,))]
    finally:
        pc.close()
    return LS.rig_of(run["config"], taker_fee=run["taker_fee"]), outs, trades


def _wallet(trades, step):
    prev = [t for t in trades if t["exit_time"] < step]
    return prev[-1]["equity_after"] if prev else 1000.0


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    w = W.build(str(tmp_path_factory.mktemp("livesim")))
    yield w
    w.close()


def test_parity_every_entered_signal_gives_the_paper_bots_own_trade(world):
    rig, outs, trades = _records(world)
    rc = open_ro(world.rule_db)
    seen = []
    try:
        for step, status, _reason, sym, d in outs:
            if status != "ENTERED":
                continue
            t = next(x for x in trades if x["entry_time"] == step and x["symbol"] == sym)
            sig = LS.signal_of(d["signal"])
            r = LS.simulate_db(rig, sig, rc, step, wallet=_wallet(trades, step), funding=W.FUNDING)
            assert r["state"] == "closed", (sym, r["state"], r["why"])
            e, x = r["entry"], r["exit"]
            assert (e["ts"], e["leverage"]) == (t["entry_time"], t["leverage"])
            for k_sim, k_rec in ((e["price"], t["entry_price"]), (e["stop"], t["stop_initial"]), (e["margin"], t["margin"]),
                                 (e["qty"], t["qty"]), (x["liq"], t["liq_price"]), (x["price"], t["exit_price"]),
                                 (x["roe"], t["roe"]), (x["pnl"], t["pnl"]), (x["fees"], t["fees"]), (x["funding"], t["funding"])):
                assert k_sim == pytest.approx(k_rec, rel=1e-12, abs=1e-9), (sym, k_sim, k_rec)
            assert (x["ts"], x["reason"], x["lock"]) == (t["exit_time"], t["exit_reason"], t["lock_roe"])
            assert r["path"][0]["t"] == step and r["path"][-1]["exit"] is True and r["path"][-1]["roe"] == t["roe"]
            assert r["best_roe"] >= x["roe"] and r["funding"] == "included"
            seen.append((sym, t["exit_reason"], t["funding"] != 0, e["stop_rule"]))
    finally:
        rc.close()
    assert [s[:2] for s in seen] == [("BTCUSDT", "LOCK"), ("ETHUSDT", "SL"), ("BCHUSDT", "LOCK")]
    assert seen[0][2] is True                                   # the BTC trade paid funding, the simulation too
    assert seen[2][3].startswith("1% of the fill")              # the research stop (meta rstop ["pct", 1.0]) went through


def test_without_funding_rates_only_the_funding_differs(world):
    rig, outs, trades = _records(world)
    step, _st, _r, _sym, d = next(o for o in outs if o[1] == "ENTERED")
    t = trades[0]
    rc = open_ro(world.rule_db)
    try:
        r = LS.simulate_db(rig, LS.signal_of(d["signal"]), rc, step, wallet=1000.0)
    finally:
        rc.close()
    assert r["funding"] == "excluded" and r["exit"]["funding"] == 0.0 and t["funding"] > 0
    assert r["entry"]["price"] == t["entry_price"] and r["exit"]["reason"] == t["exit_reason"] == "LOCK"
    assert r["exit"]["ts"] == t["exit_time"]
    assert abs(r["exit"]["roe"] - t["roe"]) < 0.002                 # funding moved the lock price a hair, nothing else


def test_the_wallet_sizes_the_trade_not_its_roe(world):
    rig, outs, trades = _records(world)
    step, _st, _r, _sym, d = [o for o in outs if o[1] == "ENTERED"][1]           # the ETH long
    rc = open_ro(world.rule_db)
    try:
        a = LS.simulate_db(rig, LS.signal_of(d["signal"]), rc, step, wallet=_wallet(trades, step))
        b = LS.simulate_db(rig, LS.signal_of(d["signal"]), rc, step, wallet=2 * _wallet(trades, step))
    finally:
        rc.close()
    assert b["entry"]["margin"] == pytest.approx(2 * a["entry"]["margin"], rel=0.01)
    assert b["exit"]["roe"] == pytest.approx(a["exit"]["roe"], abs=0.002) and a["exit"]["reason"] == b["exit"]["reason"] == "SL"
    assert a["wallet"] != b["wallet"]
    none = LS.simulate(rig, LS.signal_of(d["signal"]), [], step, wallet=None)
    assert none["wallet"] == rig.initial == 1000.0                  # no wallet: the initial equity


def test_still_open_when_the_bars_run_out_matches_the_paper_bots_open_position(tmp_path):
    w = W.build(str(tmp_path / "w"), until=W.B1 + 20 * MIN)       # BTC entered at B1, still open
    try:
        p = w.engine().position
        assert p is not None and p.symbol == "BTCUSDT" and p.lock_roe is not None
        rig, outs, trades = _records(w)
        step, _st, _r, _sym, d = next(o for o in outs if o[1] == "ENTERED")
        rc = open_ro(w.rule_db)
        try:
            r = LS.simulate_db(rig, LS.signal_of(d["signal"]), rc, step, wallet=1000.0, funding=W.FUNDING)
        finally:
            rc.close()
        assert r["state"] == "open" and r["exit"] is None and r["minutes"] == 20 and len(r["path"]) == 20
        assert r["last_ts"] == W.B1 + 19 * MIN == r["latest"]["ts"]
        assert (r["stop"], r["lock"]) == (p.stop_price, p.lock_roe)            # the paper bot's own stop and lock now
        assert r["entry"]["price"] == p.entry_price and r["entry"]["ts"] == p.entry_time
        last = W.price("BTCUSDT", W.B1 + 20 * MIN)
        ff = p.funding_paid / p.notional_entry
        assert r["latest"]["close"] == pytest.approx(last)
        assert r["latest"]["roe"] == pytest.approx(net_roe(1, p.entry_price, last, 40, rig.settings.round_trip_cost, ff))
        assert r["best_roe"] >= r["latest"]["roe"] and r["path"][-1]["lock"] == p.lock_roe
    finally:
        w.close()


def test_a_skipped_signal_that_stays_open(world):
    rig, outs, _trades = _records(world)
    step, _st, reason, sym, d = next(o for o in outs if o[3] == "DOGEUSDT")
    assert reason == "lower score than entered signal"
    rc = open_ro(world.rule_db)
    try:
        r = LS.simulate_db(rig, LS.signal_of(d["signal"]), rc, step)
    finally:
        rc.close()
    assert r["state"] == "open" and r["latest"]["roe"] < 0 and r["lock"] is None      # flat price: the costs only
    assert r["entry"]["leverage"] == 30 and r["entry"]["stop_rule"].startswith("1% of the fill")


def test_no_data_never_makes_up_a_price(world, tmp_path):
    rig, outs, _trades = _records(world)
    step, _st, _r, sym, d = next(o for o in outs if o[1] == "SKIPPED")
    sig = LS.signal_of(d["signal"])
    r = LS.simulate(rig, sig, [], step)
    assert r["state"] == "no_data" and r["entry"] is None and r["path"] == [] and "1분봉이 없어요" in r["why"]
    rc = open_ro(world.rule_db)
    try:
        later = LS.read_bars(rc, sym, step + 5 * MIN, step + 10 * MIN)
        assert LS.simulate(rig, sig, later, step)["state"] == "no_data"          # the entry minute itself is missing
    finally:
        rc.close()
    from paperbot.store3 import Store3
    empty = str(tmp_path / "empty-paper3.db")
    Store3(empty).close()
    ec = open_ro(empty)
    try:
        assert LS.simulate_db(rig, sig, ec, step)["state"] == "no_data"
        assert list(LS.iter_bars(ec, sym, step)) == []
    finally:
        ec.close()


def test_refused_when_the_stop_cannot_fit(world):
    rig, outs, _trades = _records(world)
    step, _st, _r, sym, d = next(o for o in outs if o[3] == "ETHUSDT" and o[1] == "SKIPPED")
    sig = LS.signal_of(d["signal"])
    wide = dataclasses.replace(sig, atr=sig.atr * 40, meta={**sig.meta})        # even 1 ATR is past liquidation at 30x
    rc = open_ro(world.rule_db)
    try:
        r = LS.simulate_db(rig, wide, rc, step)
    finally:
        rc.close()
    assert r["state"] == "refused" and r["entry"] is None and r["reject"]["reason"] == "stop rule"
    assert "강제청산 안쪽" in r["why"] and "does not fit" in r["reject"]["detail"][0]


def test_signal_of_rebuilds_the_outcome_signal_and_the_rig_reads_the_config(world):
    _rig, outs, _trades = _records(world)
    for _step, _st, _r, _sym, d in outs:
        sig = LS.signal_of(d["signal"])
        assert json.loads(json.dumps(dataclasses.asdict(sig), default=str)) == d["signal"]
    rig = LS.rig_of({**W.CONFIG, "unknown_newer_key": 1, "paper_db": "x", "db": "y"}, taker_fee=0.0004)
    assert rig.settings.taker_fee == 0.0004 and rig.cfg.lev_of("BTCUSDT") == 40 and rig.cfg.telegram is False
    assert rig.settings.ladder.lock_for(0.11) == pytest.approx(0.10) and rig.settings.ladder.lock_for(0.14) == pytest.approx(0.13)
    assert any("saved table" in n for n in rig.notes) and set(rig.brackets) == set(C.V3_SYMBOLS)
    bad = LS.rig_of({**W.CONFIG, "brackets_file": "/nonexistent/brackets.json"})
    assert any("unreadable" in n for n in bad.notes) and set(bad.brackets) == set(C.V3_SYMBOLS)    # the saved table, said so


def test_thin_path_keeps_the_ends_and_every_lock_step():
    path = [{"t": i, "c": 1.0, "roe": 0.0, "lock": (None if i < 300 else 0.1 if i < 600 else 0.13)} for i in range(1000)]
    th = LS.thin_path(path, 50)
    assert len(th) <= 50 and th[0]["t"] == 0 and th[-1]["t"] == 999
    assert {300, 600} <= {p["t"] for p in th}
    assert LS.thin_path(path[:10], 50) == path[:10]
