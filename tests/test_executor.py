import json
import os
import re

import pytest

from fakefutures import FakeFutures
from paperbot import risk as R
from paperbot.executor import (ExecConfig, ExecStore, Executor, Guarded, Intent, Paper3Source, Refused, main)
from paperbot.notify import CRITICAL, ListNotifier
from paperbot.testnet import RateLimited, TestnetClient, TestnetError, UnknownOutcome

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1_800_000_000_000
BTC = "BTCUSDT"


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Source:
    """Stands in for paper3.db: the paper account's open position (or None)."""

    def __init__(self, clock):
        self.clock, self.intent, self.ts = clock, None, None

    def read(self):
        return self.intent, (self.ts if self.ts is not None else self.clock() - 30_000)


def risk_cfg(tmp_path, **kw):
    d = dict(daily_max_loss_usd=500.0, max_drawdown_pct=0.2, max_consecutive_losses=3, max_leverage=20,
             max_notional_usd=1_000.0, allowed_symbols=(BTC, "ETHUSDT"), kill_file=str(tmp_path / "STOP"))
    d.update(kw)
    return R.RiskConfig(**d)


class World:
    def __init__(self, tmp_path, fake=None, retries=4, **risk_kw):
        self.tmp = tmp_path
        self.clock = Clock()
        self.fake = fake or FakeFutures()
        self.fake.clock = self.clock                       # fills and funding carry the test's time
        self.src = Source(self.clock)
        self.note = ListNotifier()
        self.sleeps = []
        self.cfg = ExecConfig(account="V45_AMB@15m", paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "exec.db"),
                              qty_scale=1.0, risk=risk_cfg(tmp_path, **risk_kw), retries=retries, sweep_every=1)
        self.open()

    def open(self):
        self.store = ExecStore(self.cfg.db)
        self.client = TestnetClient("k", "s", send=self.fake, clock_ms=self.clock)
        self.ex = Executor(self.cfg, self.client, self.src, self.store, self.note, now_ms=self.clock,
                           sleep=self.sleeps.append)
        self.ex.start()
        return self.ex

    def restart(self):
        self.store.close()
        return self.open()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def paper(self, stop, side=1, qty=5.0, lev=20, symbol=BTC, entry_time=None, entry=100.0):
        et = entry_time if entry_time is not None else (
            self.src.intent.entry_time if self.src.intent else self.clock.t - 60_000)
        self.src.intent = Intent(key=f"V45_AMB@15m|{symbol}|{et}", symbol=symbol, side=side, qty=qty, leverage=lev,
                                 stop=stop, entry_price=entry, entry_time=et)

    def events(self, kind=None):
        q = "SELECT kind, level, text FROM events" + (" WHERE kind = ?" if kind else "") + " ORDER BY id"
        return self.store.conn.execute(q, (kind,) if kind else ()).fetchall()

    def trades(self):
        return self.store.conn.execute("SELECT key, qty, exit_reason, pnl FROM trades ORDER BY entry_ts").fetchall()

    def stops(self):
        return [(float(o["triggerPrice"]), float(o["quantity"])) for o in self.fake.live_stops(BTC)]

    def protected_after_first_stop(self, symbol=BTC):
        """Every request after the first protective stop saw the position covered."""
        first = next(i for i, c in enumerate(self.fake.calls) if c[1] == "/fapi/v1/algoOrder" and c[0] == "POST")
        return [t for t in self.fake.unprotected_moments(symbol) if t[0] > first]


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path)
    yield world
    world.store.close()


# ------------------------------------------------------------------ entry and stops
def test_entry_places_market_and_a_confirmed_exchange_stop(w):
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.algos         # nothing to mirror yet
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 5.0 and w.stops() == [(95.0, 5.0)]
    stop = w.fake.live_stops(BTC)[0]
    assert stop["workingType"] == "CONTRACT_PRICE" and stop["priceProtect"] is False and stop["reduceOnly"]
    assert w.fake.margin[BTC] == "ISOLATED" and w.fake.lev[BTC] == 20
    assert w.ex.trade["status"] == "open" and w.ex.trade["stop_algo_id"] == stop["algoId"]
    # the stop was read back after placing it (confirmed live)
    i = next(i for i, c in enumerate(w.fake.calls) if c[1] == "/fapi/v1/algoOrder" and c[0] == "POST")
    assert w.fake.calls[i + 1][:2] == ("GET", "/fapi/v1/algoOrder")
    # only the entry fill and the position read come before the stop
    early = [t for t in w.fake.unprotected_moments(BTC) if t[0] <= i]
    assert [t[2] for t in early] == ["/fapi/v1/order", "/fapi/v2/positionRisk"]
    assert not w.protected_after_first_stop()
    assert w.trades()[0][1] == 5.0
    # requests that change something are recorded with their parameters (no signature)
    rows = w.store.conn.execute("SELECT method, path, params FROM requests").fetchall()
    assert any(p == "/fapi/v1/algoOrder" and '"triggerPrice": 95.0' in prm for _, p, prm in rows)
    assert not any("signature" in prm for *_, prm in rows)


def test_lock_steps_never_leave_the_position_unprotected(w):
    w.paper(stop=95.0)
    w.loop()
    steps = [(105.0, 101.1), (109.0, 104.9), (113.0, 109.3), (118.0, 113.6)]
    for price, lock in steps:
        w.fake.set_price(BTC, price)
        w.paper(stop=lock)
        w.loop()
        assert w.stops() == [(lock, 5.0)], (price, lock)
        assert w.ex.trade["stop"] == lock
        assert not w.protected_after_first_stop()
    # failures in the middle of a move: answer lost after the stop was placed, a refused stop, a lost cancel
    w.fake.set_price(BTC, 125.0)
    w.paper(stop=118.0)
    w.fake.fail("POST", "/fapi/v1/algoOrder", "503_after")
    w.loop()
    assert w.stops() == [(118.0, 5.0)]                       # looked up by client id: no duplicate
    w.paper(stop=120.0)
    w.fake.fail("POST", "/fapi/v1/algoOrder", ("code", -1111, "Precision is over the maximum defined for this asset."))
    w.loop()
    assert w.stops() == [(118.0, 5.0)] and w.events("move_failed")    # old stop kept
    w.fake.fail("DELETE", "/fapi/v1/algoOrder", "drop_before")
    w.loop()
    assert w.stops() == [(120.0, 5.0)]
    assert not w.protected_after_first_stop()
    # paper exit -> close, cancel, flat
    w.src.intent = None
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.live_stops() and w.ex.trade is None
    key, qty, reason, pnl = w.trades()[0]
    assert "paper 청산" in reason and pnl > 0
    assert not w.protected_after_first_stop()


def test_lock_past_the_price_closes_with_a_reduce_only_market_order(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 100.5)
    w.paper(stop=101.1)                                       # paper locked at 101.1; the price is already below
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.live_stops() and w.ex.trade is None
    assert w.events("stop_would_trigger") and "시장가" in w.trades()[0][2]
    close = [c for c in w.fake.calls if c[1] == "/fapi/v1/order" and c[2].get("reduceOnly") == "true"]
    assert len(close) == 1
    w.loop(3)                                                 # the same paper position is not entered again
    assert w.fake.pos[BTC] == 0 and len(w.trades()) == 1


def test_stop_hit_on_the_exchange_is_booked(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 94.0)
    assert w.fake.pos[BTC] == 0
    w.loop()
    key, qty, reason, pnl = w.trades()[0]
    assert "거래소 손절" in reason and pnl < 0 and w.ex.risk.consecutive_losses == 1
    w.loop(2)
    assert w.fake.pos[BTC] == 0 and len(w.trades()) == 1      # paper still open: not re-entered


def test_stop_distance_follows_the_actual_fill(tmp_path):
    """The testnet price is not the market price the paper account sees: by default the exchange stop keeps
    the paper's distance from the fill ("ratio"); "price" copies the paper's stop price."""
    w = World(tmp_path, fake=FakeFutures(prices={BTC: 200.0, "ETHUSDT": 50.0, "SOLUSDT": 10.0}),
              max_notional_usd=5_000.0)
    w.paper(stop=95.0, entry=100.0)
    w.loop()
    assert w.stops() == [(190.0, 5.0)]
    w.fake.set_price(BTC, 212.0)
    w.paper(stop=101.1, entry=100.0)                       # paper lock at +1.1 % from its fill
    w.loop()
    assert w.stops() == [(202.2, 5.0)] and not w.protected_after_first_stop()
    w.store.close()
    (tmp_path / "p").mkdir()
    w2 = World(tmp_path / "p", fake=FakeFutures(prices={BTC: 200.0, "ETHUSDT": 50.0, "SOLUSDT": 10.0}),
               max_notional_usd=5_000.0, daily_max_loss_usd=1_000.0)      # a far stop: room for its loss
    w2.store.close()
    w2.cfg = ExecConfig(**{**w2.cfg.__dict__, "stop_from": "price"})
    w2.open()
    w2.paper(stop=95.0, entry=100.0)
    w2.loop()                                              # the paper stop is far below this price: still valid
    assert w2.stops() == [(95.0, 5.0)]
    w2.store.close()


def test_partial_fill_gets_a_stop_for_what_was_filled(w):
    w.fake.partial = 0.6
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 3.0 and w.stops() == [(95.0, 3.0)] and w.events("partial_fill")


# ------------------------------------------------------------------ reconcile
def test_unknown_position_is_closed_and_alerted(w):
    w.fake.pos["ETHUSDT"], w.fake.entry["ETHUSDT"] = 2.0, 50.0
    w.loop()
    assert w.fake.pos["ETHUSDT"] == 0
    assert any(lvl == CRITICAL and "모르는 포지션" in txt for lvl, txt in w.note.messages)


def test_missing_stop_is_put_back_or_the_position_closed(w):
    w.paper(stop=95.0)
    w.loop()
    for o in w.fake.live_stops(BTC):
        o["algoStatus"] = "CANCELED"                          # someone removed it on the website
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.events("no_stop")
    for o in w.fake.live_stops(BTC):
        o["algoStatus"] = "CANCELED"
    w.fake.last[BTC] = 94.0                                    # and the price is already past it
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and not w.fake.live_stops()


def test_stop_smaller_than_position_and_extra_stops(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.pos[BTC] = 7.0                                      # the position grew outside the bot
    w.loop()
    assert w.stops() == [(95.0, 7.0)] and w.ex.trade["qty"] == 7.0 and w.events("size_mismatch")
    w.client.stop_close(BTC, "SELL", 90.0, qty=7.0)            # a stray extra stop
    w.loop()
    assert w.stops() == [(95.0, 7.0)] and w.events("extra_stops")


def test_stray_stops_without_a_position_are_cancelled(w):
    w.client.stop_close(BTC, "SELL", 90.0, qty=1.0)
    w.loop()
    assert not w.fake.live_stops() and w.events("stray_orders")


# ------------------------------------------------------------------ restarts
def test_restart_after_crash_between_fill_and_stop(w):
    w.paper(stop=95.0)

    def die(*a, **k):
        raise KeyboardInterrupt("process killed")
    w.ex._protect = die
    with pytest.raises(KeyboardInterrupt):
        w.loop()
    assert w.fake.pos[BTC] == 5.0 and not w.fake.live_stops()
    w.restart()
    assert w.ex.trade["status"] == "open"
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.events("no_stop")
    assert any(lvl == CRITICAL and "손절이 없습니다" in txt for lvl, txt in w.note.messages)


def test_restart_while_entry_outcome_unknown(w):
    w.paper(stop=95.0)
    w.fake.fail("POST", "/fapi/v1/order", "drop_before", times=8)     # never reaches the exchange
    w.fake.fail("GET", "/fapi/v1/order", "drop_before", times=8)      # and the look-ups fail too
    w.loop()
    assert w.ex.trade["status"] == "entering" and w.events("entry_unknown")
    w.fake.failures.clear()
    w.restart()
    w.clock.t += 61_000                                               # the entry never showed up (entry_unknown_s)
    w.loop()
    assert w.ex.trade is None and w.fake.pos[BTC] == 0 and w.events("recover")
    # a lost answer after the order was executed: looked up by client id, never sent twice
    w.paper(stop=96.0, entry_time=w.clock.t - 30_000)
    w.fake.fail("POST", "/fapi/v1/order", "drop_after")
    w.loop()
    entries = [c for c in w.fake.calls if c[:2] == ("POST", "/fapi/v1/order") and c[2].get("reduceOnly") is None]
    assert len(entries) == 1 and w.fake.pos[BTC] == 5.0 and w.stops() == [(96.0, 5.0)]


def test_restart_keeps_open_trade_and_lock(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 106.0)
    w.paper(stop=101.1)
    w.loop()
    w.restart()
    assert w.ex.trade["stop"] == 101.1
    w.loop()
    assert w.stops() == [(101.1, 5.0)] and w.fake.pos[BTC] == 5.0
    assert not w.protected_after_first_stop()


# ------------------------------------------------------------------ risk
def test_kill_switch_flattens_halts_and_needs_a_person(w, tmp_path, capsys):
    w.paper(stop=95.0)
    w.loop()
    (tmp_path / "STOP").write_text("")
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.live_stops() and w.ex.risk.halted
    assert any(lvl == CRITICAL and "비상 정지" in txt for lvl, txt in w.note.messages)
    os.remove(tmp_path / "STOP")
    w.paper(stop=97.0, entry_time=w.clock.t)                  # a new paper entry
    w.loop(2)
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted
    w.restart()
    assert w.ex.risk.halted
    # clearing: refused while the executor holds the database, done by a person once it is stopped
    conf = tmp_path / "executor.json"
    conf.write_text(json.dumps({"account": w.cfg.account, "paper_db": w.cfg.paper_db, "db": w.cfg.db,
                                "qty_scale": 1.0, "risk": {**R.RiskConfig().__dict__, **w.cfg.risk.__dict__,
                                                           "allowed_symbols": list(w.cfg.risk.allowed_symbols)}}))
    assert main(["clear-halt", "--config", str(conf), "--by", "owner"]) == 2
    w.store.close()
    (tmp_path / "STOP").write_text("")
    assert main(["clear-halt", "--config", str(conf), "--by", "owner"]) == 1      # kill file still there
    os.remove(tmp_path / "STOP")
    assert main(["clear-halt", "--config", str(conf), "--by", "owner", "--note", "점검 끝"]) == 0
    w.open()
    assert not w.ex.risk.halted
    halts = w.store.conn.execute("SELECT action, who FROM halts ORDER BY id").fetchall()
    assert halts == [("halt", None), ("clear", "owner")]
    capsys.readouterr()


def test_daily_loss_halt_survives_restart(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=60.0)
    w.paper(stop=90.0)                                        # loss at the stop ~$51: fits the daily limit
    w.loop()
    assert w.fake.pos[BTC] == 5.0
    w.fake.set_price(BTC, 95.5)                               # -22.5 unrealised
    w.fake.add_funding(BTC, -40.0)                            # and a funding payment: -62.5 today
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted and "하루 한도" in w.ex.risk.halt_reason
    w.restart()
    w.fake.set_price(BTC, 100.0)
    w.paper(stop=97.0, entry_time=w.clock.t)
    w.loop()
    assert w.ex.risk.halted and w.fake.pos[BTC] == 0
    w.store.close()


def test_consecutive_losses_halt(tmp_path):
    w = World(tmp_path, max_consecutive_losses=2)
    for k in range(2):
        w.fake.set_price(BTC, 100.0)
        w.paper(stop=95.0, entry_time=w.clock.t - 10_000)
        w.loop()
        assert w.fake.pos[BTC] == 5.0, k
        w.fake.set_price(BTC, 94.0)
        w.loop()
    assert w.ex.risk.halted and "연속 손실 2번" in w.ex.risk.halt_reason
    w.fake.set_price(BTC, 100.0)
    w.paper(stop=95.0, entry_time=w.clock.t)
    w.loop()
    assert w.fake.pos[BTC] == 0
    w.store.close()


def test_entry_limits_from_risk_config(tmp_path):
    w = World(tmp_path, max_leverage=10, max_notional_usd=300.0)
    w.paper(stop=95.0, qty=5.0, lev=50)
    w.loop()
    assert w.fake.pos[BTC] == 3.0 and w.fake.lev[BTC] == 10 and w.stops() == [(95.0, 3.0)]
    w.src.intent = None
    w.loop()
    w.paper(stop=0.5, symbol="SOLUSDT", entry_time=w.clock.t)          # not an allowed coin
    w.loop()
    assert w.fake.pos["SOLUSDT"] == 0 and any("허용 코인" in e[2] for e in w.events("entry_check"))
    w.store.close()


def test_late_or_stale_paper_is_not_followed(w):
    w.paper(stop=95.0, entry_time=w.clock.t - 600_000)
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.events("late")
    w.src.ts = w.clock.t - 3_600_000
    w.paper(stop=95.0, entry_time=w.clock.t)
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.events("paper_stale")
    w.src.ts = None
    w.loop()
    assert w.fake.pos[BTC] == 5.0


# ------------------------------------------------------------------ errors and limits
def test_retry_policy(tmp_path):
    fake = FakeFutures()
    sleeps = []
    c = Guarded(TestnetClient("k", "s", send=fake, clock_ms=lambda: T0), sleeps.append, retries=4)
    fake.fail("GET", "/fapi/v2/positionRisk", "503_before", times=2)
    assert c.position(BTC)["positionAmt"] == "0.0" and sleeps == [0.5, 1.0]
    fake.fail("GET", "/fapi/v2/positionRisk", "429")
    sleeps.clear()
    c.position(BTC)
    assert sleeps == [2.0]                                       # Retry-After
    fake.fail("GET", "/fapi/v2/positionRisk", "418")
    with pytest.raises(RateLimited):
        c.position(BTC)
    n = len(fake.calls)
    fake.fail("POST", "/fapi/v1/leverage", ("code", -4028, "Leverage 200 is not valid"))
    with pytest.raises(TestnetError):
        c.leverage(BTC, 200)
    assert len(fake.calls) == n                                  # a 4xx is not retried
    fake.fail("POST", "/fapi/v1/order", "drop_after")
    c.market(BTC, "BUY", 1.0, client_id="pbtest1")               # executed, answer lost: found by its client id
    fake.fail("POST", "/fapi/v1/order", "drop_before")
    with pytest.raises(UnknownOutcome):                          # an opening order is never sent a second time
        c.market(BTC, "BUY", 1.0, client_id="pbtest2")
    assert fake.pos[BTC] == 1.0 and len([x for x in fake.calls if x[:2] == ("POST", "/fapi/v1/order")]) == 1
    fake.fail("POST", "/fapi/v1/order", "drop_before")
    c.market(BTC, "SELL", 0.5, reduce_only=True, client_id="pbtest2x")    # a reduce-only close is sent again
    assert fake.pos[BTC] == 0.5 and len([x for x in fake.calls if x[:2] == ("POST", "/fapi/v1/order")]) == 2
    fake.fail("POST", "/fapi/v1/order", "503_before", times=9)
    with pytest.raises(TestnetError):
        c.market(BTC, "BUY", 1.0, client_id="pbtest3")
    assert fake.pos[BTC] == 0.5
    a = c.stop_close(BTC, "SELL", 90.0, qty=0.5, client_id="pbs1")
    fake.fail("DELETE", "/fapi/v1/algoOrder", "503_after")
    assert c.cancel_algo(algo_id=a["algoId"])["gone"] and not fake.live_stops()


def test_loop_errors_are_logged_and_the_loop_goes_on(w):
    w.fake.fail("GET", "/fapi/v2/positionRisk", "503_before", times=20)
    w.ex.run(max_loops=3)
    errs = w.events("loop_error")
    assert len(errs) == 3 and "TransientError" in errs[0][2]
    assert w.sleeps.count(w.cfg.poll_s) >= 3
    w.fake.failures.clear()
    w.fake.fail("GET", "/fapi/v2/positionRisk", "418")
    w.ex.run(max_loops=1)
    assert w.events("rate_limit") and 120.0 in w.sleeps


# ------------------------------------------------------------------ refusals and isolation
def test_refuses_anything_but_the_testnet(tmp_path):
    w = World(tmp_path)
    w.store.close()
    store = ExecStore(str(tmp_path / "x.db"))
    try:
        c = TestnetClient("k", "s", send=w.fake)
        c.base = "https://fapi.binance.com"                     # tampered after construction
        with pytest.raises(Refused):
            Executor(w.cfg, c, w.src, store)
        c = TestnetClient("k", "s", send=w.fake)
        with pytest.raises(Refused):
            Executor(ExecConfig(**{**w.cfg.__dict__, "mode": "mainnet"}), c, w.src, store)
        with pytest.raises(Refused) as e:
            Executor(ExecConfig(**{**w.cfg.__dict__, "risk": R.RiskConfig()}), c, w.src, store)
        assert "하루 최대 손실" in str(e.value)
    finally:
        store.close()
    with pytest.raises(ValueError):
        TestnetClient("k", "s", base="https://fapi.binance.com")


def test_one_writer(tmp_path):
    a = ExecStore(str(tmp_path / "e.db"))
    with pytest.raises(Refused):
        ExecStore(str(tmp_path / "e.db"))
    a.close()
    ExecStore(str(tmp_path / "e.db")).close()


def test_testnet_key_must_not_be_the_paper_key(tmp_path, monkeypatch, capsys):
    conf = tmp_path / "c.json"
    conf.write_text(json.dumps({"account": "A@15m", "paper_db": "p", "db": str(tmp_path / "e.db"), "qty_scale": 1,
                                "risk": {}}))
    assert main(["check-config", "--config", str(conf)]) == 1
    assert "하루 최대 손실" in capsys.readouterr().out
    monkeypatch.setenv("TESTNET_API_KEY", "same")
    monkeypatch.setenv("TESTNET_API_SECRET", "x")
    monkeypatch.setenv("BINANCE_API_KEY", "same")
    assert main(["run", "--config", str(conf), "--max-loops", "0"]) == 2


def test_paper3_source(tmp_path):
    from paperbot.store3 import Store3
    db = str(tmp_path / "paper3.db")
    s = Store3(db)
    pos = {"symbol": BTC, "side": -1, "qty": 0.5, "leverage": 30, "stop_price": 105.0, "entry_price": 100.0,
           "entry_time": T0, "signal": {}}
    s.put_state("accounts", T0 + 60_000, {"last_ts": T0, "engines": {"A@15m": {"position": pos},
                                                                       "B@15m": {"position": None}}})
    s.commit()
    it, ts = Paper3Source(db, "A@15m").read()
    assert ts == T0 + 60_000 and it.side == -1 and it.stop == 105.0 and it.key == f"A@15m|{BTC}|{T0}"
    assert Paper3Source(db, "B@15m").read() == (None, T0 + 60_000)
    with pytest.raises(Refused):
        Paper3Source(db, "C@15m").read()
    s.close()


def test_agents_and_paper_runner_never_reach_order_code():
    """AI agents never place orders: nothing under paperbot/agents (nor the paper runner, the
    dashboard or the nightly check) imports the executor, the testnet or mainnet client or the risk layer."""
    pat = re.compile(r"^\s*(from\s+\S*\b(executor|testnet|mainnet|risk)\b\s+import|"
                     r"import\s+\S*\b(executor|testnet|mainnet)\b|"
                     r"from\s+\.+\s+import\s+.*\b(executor|testnet|mainnet)\b)", re.M)
    roots = [os.path.join(REPO, "paperbot", "agents"), os.path.join(REPO, "paperbot", "dash")]
    files = [os.path.join(r, f) for root in roots for r, _, fs in os.walk(root) for f in fs if f.endswith(".py")]
    files += [os.path.join(REPO, "paperbot", f) for f in ("live3.py", "live.py", "daily3.py", "store3.py")]
    hits = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            if pat.search(fh.read()):
                hits.append(os.path.relpath(path, REPO))
    assert hits == []
