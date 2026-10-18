"""The Bybit review fixes (commit 6737e74) carried to MEXC from day one: each case runs the real executor (or client)
against the fake MEXC exchange (tests/fakemexc.py), under each answer MEXC might give where its docs are silent
(a repeated externalOid answered with the old order, refused, or accepted as a second order). No network."""

import pytest

import paperbot.mexc as MX
from fakebybit import FakeBybit
from fakefutures import FakeFutures
from fakemexc import FakeMexc
from paperbot.bybit import BybitClient
from paperbot.executor import ExecConfig, ExecStore, Executor
from paperbot.mainnet import Refused
from paperbot.notify import WARN
from paperbot.testnet import RateLimited, TestnetClient
from test_mexc_executor import B, BTC, LIVE_ENV, T0, Clock, World, no_network  # noqa: F401

CREATE = "/api/v1/private/order/create"
PLACE = "/api/v1/private/planorder/place"


def entries(fake):
    return [o for o in fake.orders.values() if o["side"] in (1, 3)]


def opening_posts(fake):
    return [q for m, p, q in fake.calls if p == CREATE and q["side"] in (1, 3)]


def mexc_world(tmp_path, dup="existing", **kw):
    fake = FakeMexc(wallet=10_000.0)
    fake.dup_external = dup
    return World(tmp_path, fake=fake, **kw)


# ------------------------------------------------------------------ 1. an accepted order never reads as "not executed"
def test_rate_limit_on_the_read_back_keeps_the_entry_and_protects_it(tmp_path):
    w = mexc_world(tmp_path)
    w.fake.market_lag = 1
    w.fake.fail("GET", "/api/v1/private/order/get/", "429", times=1)
    w.paper(stop=95.0)
    w.loop()
    assert len(opening_posts(w.fake)) == 1 and len(entries(w.fake)) == 1
    assert w.amt() == 5 and w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    assert not w.events("entry_refused") and not w.protected_after_first_stop()
    w.store.close()


def test_a_ban_on_the_read_back_adopts_and_protects_after_the_ban(tmp_path):
    w = mexc_world(tmp_path)
    w.fake.fail("GET", "/api/v1/private/order/get/", "403", times=1)
    w.fake.fail("GET", "/api/v1/private/position/open_positions", "403", times=1,
                when=lambda q: q.get("symbol") == B and w.fake.pos[B] != 0)       # still banned after the fill
    w.paper(stop=95.0)
    with pytest.raises(RateLimited):                       # the loop waits out the ban (run() sleeps)
        w.loop()
    assert w.amt() == 5 and w.ex.trade["status"] == "entering" and not w.events("entry_refused")
    w.loop()                                               # ban over: the position is adopted and protected
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and w.events("recover")
    assert len(opening_posts(w.fake)) == 1 and len(entries(w.fake)) == 1
    w.store.close()


@pytest.mark.parametrize("dup", ["existing", "error", "accept"])
@pytest.mark.parametrize("code", [510, 2037, 603])
def test_a_rate_limited_or_repeated_create_with_a_lagging_lookup_never_doubles_the_entry(tmp_path, dup, code):
    """Executed, but answered "too frequent" / "repeated request"; the look-ups by externalOid do not show it yet.
    Whatever MEXC does with a repeated externalOid (even a second order), the entry is never sent again."""
    w = mexc_world(tmp_path, dup=dup)
    w.fake.fail("POST", CREATE, ("ret_after", code, "Excessive frequency of requests"), times=1,
                when=lambda q: q["side"] in (1, 3))
    w.fake.fail("GET", "/api/v1/private/order/external/", ("ret", 2040, "order not exist"), times=4)
    w.paper(stop=95.0)
    w.loop()
    assert len(opening_posts(w.fake)) == 1 and len(entries(w.fake)) == 1 and w.amt() == 5
    assert w.ex.trade["status"] == "entering" and w.events("entry_unknown")
    w.loop()                                               # the reconcile adopts and protects what filled
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and len(opening_posts(w.fake)) == 1
    assert entries(w.fake)[0]["orderId"] in w.ex.trade["orders"]          # found by its id after the stop
    w.src.intent = None
    w.loop()
    assert w.fake.pos[B] == 0 and w.trades()[0][4] == "fills"            # so its P&L comes from its fills
    w.store.close()


def test_a_create_whose_answer_is_cut_is_found_by_its_external_id(tmp_path):
    w = mexc_world(tmp_path, dup="accept")
    w.fake.fail("POST", CREATE, "cut_after", times=1, when=lambda q: q["side"] in (1, 3))
    w.paper(stop=95.0)
    w.loop()
    assert len(opening_posts(w.fake)) == 1 and w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    w.store.close()


@pytest.mark.parametrize("kind", [("ret_after", 9999, "Public abnormal"), "cut_after", "503_after"])
def test_a_stop_created_but_answered_with_an_error_is_found_not_doubled(tmp_path, kind):
    w = mexc_world(tmp_path)
    w.fake.fail("POST", PLACE, kind, times=1)
    w.paper(stop=95.0)
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and len(w.stop_posts()) == 1 and not w.events("protect_failed")
    w.store.close()


def test_client_returns_the_accepted_order_when_its_read_back_fails():
    fake, clock = FakeMexc(), Clock()
    fake.clock = clock
    c = MX.MexcClient("mk", "ms", send=fake, clock_ms=clock, sleep=lambda s: None)
    c.one_way()
    c.leverage(BTC, 20)
    fake.fail("GET", "/api/v1/private/order/get/", "503_before", times=9)
    o = c.market(BTC, "BUY", 0.001, client_id="pbe9")
    assert o["status"] == "NEW" and o["orderId"] and "readBack" in o and fake.pos[B] == 10


# ------------------------------------------------------------------ 2. one database, one exchange
def test_a_database_of_another_exchange_is_refused(tmp_path):
    w = mexc_world(tmp_path)                               # a MEXC database
    cfg = w.cfg
    assert w.store.get_state("meta")["exchange"] == "mexc"
    w.store.close()
    store = ExecStore(cfg.db)
    bybit_cfg = ExecConfig(**{**cfg.__dict__, "exchange": "bybit", "mode": "testnet", "budget_usd": None})
    with pytest.raises(Refused) as e:                      # ... used by a Bybit executor
        Executor(bybit_cfg, BybitClient("k", "s", send=FakeBybit()), w.src, store,
                 env={"BYBIT_TESTNET_API_KEY": "k", "BYBIT_TESTNET_API_SECRET": "s"})
    assert "mexc" in str(e.value)
    binance_cfg = ExecConfig(**{**cfg.__dict__, "exchange": "binance", "mode": "testnet", "budget_usd": None})
    with pytest.raises(Refused):                           # ... or a Binance one
        Executor(binance_cfg, TestnetClient("bk", "bs", send=FakeFutures(api_key="bk")), w.src, store, env={})
    store.close()
    (tmp_path / "b").mkdir()                               # a Binance database (no "exchange" in it)
    old = ExecStore(str(tmp_path / "b" / "exec-mexc.db"))
    old.put_state("meta", T0, {"mode": "mainnet", "account": "V45_AMB@15m", "since": T0})
    old.close()
    w2 = World.__new__(World)
    with pytest.raises(Refused) as e:
        World.__init__(w2, tmp_path / "b")
    assert "binance" in str(e.value)
    w2.store.close()
    (tmp_path / "c").mkdir()                               # a Bybit database
    old = ExecStore(str(tmp_path / "c" / "exec-mexc.db"))
    old.put_state("meta", T0, {"mode": "mainnet", "account": "V45_AMB@15m", "since": T0, "exchange": "bybit"})
    old.close()
    w3 = World.__new__(World)
    with pytest.raises(Refused) as e:
        World.__init__(w3, tmp_path / "c")
    assert "bybit" in str(e.value)
    w3.store.close()


# ------------------------------------------------------------------ 3. the sign of realized P&L
@pytest.mark.parametrize("net", [False, True])
def test_pnl_from_fills_whether_profit_is_gross_or_net(tmp_path, net):
    w = mexc_world(tmp_path)
    w.fake.profit_net = net
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(B, 104.0)
    w.src.intent = None
    w.loop()
    key, qty, reason, pnl, source = w.trades()[0]
    assert source == "fills" and pnl == pytest.approx(w.fake.wallet - 10_000.0) and pnl > 0
    assert not w.events("pnl_check")
    w.store.close()


def test_the_executor_keeps_the_wallet_estimate_and_alerts_once_on_a_mismatch(tmp_path):
    w = mexc_world(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(B, 104.0)
    w.fake.profit_tamper = lambda d: {**d, "profit": -abs(d["profit"]) - 50}
    w.src.intent = None
    w.loop()
    key, qty, reason, pnl, source = w.trades()[0]
    assert source == "wallet" and pnl == pytest.approx(w.fake.wallet - 10_000.0) and pnl > 0
    assert w.ex.risk.consecutive_losses == 0
    assert {lvl for _, lvl, _ in w.events("pnl_check")} == {WARN}
    assert sum("MEXC 체결 profit" in t for _, t in w.note.messages) == 1
    w.loop(3)                                              # retried later: still not booked, not alerted again
    assert w.trades()[0][4] == "wallet" and sum("MEXC 체결 profit" in t for _, t in w.note.messages) == 1
    w.store.close()


# ------------------------------------------------------------------ 4. the key: what MEXC cannot show is stated
@pytest.mark.parametrize("value", [None, "", "yes", "FUTURES_ONLY", MX.KEY_CHECKED_VALUE.lower()])
def test_the_key_statement_must_be_exact(tmp_path, value):
    env = {k: v for k, v in LIVE_ENV.items() if k != MX.KEY_CHECKED}
    if value is not None:
        env[MX.KEY_CHECKED] = value
    w = World.__new__(World)
    with pytest.raises(Refused) as e:
        World.__init__(w, tmp_path, env=env)
    assert MX.KEY_CHECKED in str(e.value)
    w.store.close()


def test_a_key_that_cannot_read_the_futures_account_is_refused(tmp_path):
    fake = FakeMexc(wallet=10_000.0)
    fake.fail("GET", "/api/v1/private/account/assets", ("ret", 701, "Account read permission is required"),
              times=99)
    w = World.__new__(World)
    with pytest.raises(Exception):                         # refused: nothing verified, nothing traded
        World.__init__(w, tmp_path, fake=fake)
    assert not fake.orders and not fake.plans
    w.store.close()


# ------------------------------------------------------------------ 5. client ids never repeat
def test_stop_and_close_ids_never_repeat_after_a_restart_that_lost_the_counter(tmp_path):
    w = mexc_world(tmp_path)                               # a repeated id would answer the OLD order
    w.paper(stop=95.0)
    w.loop()
    bot = w.store.get_state("bot")
    bot["trade"]["n"] = 0                                  # the counter's save was lost before the restart
    w.store.put_state("bot", T0, bot)
    w.store.commit()
    w.restart()
    for p in w.fake.live_plans(B):
        p["state"] = 2                                     # its stop is gone: placed again
    w.loop()
    w.fake.set_price(B, 106.0)
    w.paper(stop=101.1)
    w.loop()
    w.src.intent = None
    w.loop()
    ids = [q["externalOid"] for m, p, q in w.fake.calls if p in (CREATE, PLACE)]
    assert len(ids) == len(set(ids)) == 5 and all(len(x) <= 32 for x in ids)
    assert w.fake.pos[B] == 0 and not w.events("protect_failed") and w.trades()[0][4] == "fills"
    w.store.close()


# ------------------------------------------------------------------ 6. re-sync on time and replay codes
@pytest.mark.parametrize("code,msg", [(513, "Invalid request(for open api serves time more or less than 10s)"),
                                      (603, "Repeated requests")])
def test_time_and_replay_answers_resync_and_never_double(tmp_path, code, msg):
    w = mexc_world(tmp_path, dup="accept")
    w.fake.fail("GET", "/api/v1/private/position/open_positions", ("ret", code, msg), times=1,
                when=lambda q: not q.get("symbol"))
    w.fake.fail("POST", CREATE, ("ret", code, msg), times=1, when=lambda q: q["side"] in (1, 3))
    w.paper(stop=95.0)
    w.loop()
    if code == 513:                                        # refused, not executed: re-synced and sent once more
        assert w.amt() == 5 and len(entries(w.fake)) == 1 and w.stops() == [(95.0, 5.0)]
        assert sum("서버 시간 다시 맞춤" in t for _, _, t in w.events("retry")) == 2
    else:                                                  # unknown: looked up, never sent again
        sent = [f for f in w.fake.failures if f[1] == CREATE]
        assert sent[0][3] == 0 and not opening_posts(w.fake)  # the one send (refused here) was never repeated
        assert not entries(w.fake) and w.ex.trade["status"] == "entering" and w.events("entry_unknown")
        w.clock.t += 61_000
        w.loop()
        assert w.ex.trade is None and w.fake.pos[B] == 0 and w.events("recover")
    w.store.close()


# ------------------------------------------------------------------ 7. bonuses are transfers, not P&L
def test_a_bonus_is_counted_as_a_transfer_not_profit_or_loss(tmp_path):
    w = mexc_world(tmp_path, daily_max_loss_usd=60.0)
    w.loop()
    w.fake.bonus = 100.0                                   # granted: not profit
    w.clock.t += 61_000
    w.loop()
    w.clock.t += 61_000
    w.loop()
    assert w.ex.risk.transfers == pytest.approx(100.0) and len(w.events("transfer")) == 1
    w.fake.bonus = 0.0                                     # taken back: not a loss (no daily-loss halt)
    w.clock.t += 61_000
    w.loop()
    w.clock.t += 61_000
    w.loop()
    assert not w.ex.risk.halted and w.ex.risk.transfers == pytest.approx(0.0) and len(w.events("transfer")) == 2
    w.store.close()


# ------------------------------------------------------------------ market order type 6 (ccxt's choice) by config
def test_the_market_order_type_comes_from_the_config(tmp_path):
    w = mexc_world(tmp_path, cfg_kw={"mexc_market_type": 6})
    w.client.market_type = 6                               # MX.clients passes it in the real start-up
    w.paper(stop=95.0)
    w.loop()
    w.src.intent = None
    w.loop()
    assert [q["type"] for m, p, q in w.fake.calls if p == CREATE] == [6, 6] and w.fake.pos[B] == 0
    c, _ = MX.clients("mainnet", LIVE_ENV, market_type=6)
    assert c.market_type == 6
    w.store.close()
