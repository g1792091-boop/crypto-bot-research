"""Fixes after the review of the Bybit adapter (2026-10-18): each case runs the real executor (or client) against the
fake Bybit exchange (tests/fakebybit.py). No network."""

import pytest

import paperbot.bybit as BY
from fakebybit import FakeBybit
from fakefutures import FakeFutures
from paperbot.executor import ExecConfig, ExecStore, Executor, preflight
from paperbot.mainnet import Refused, check_permissions
from paperbot.notify import WARN
from paperbot.testnet import RateLimited, TestnetClient
from test_bybit_executor import BTC, LIVE_ENV, T0, Clock, World, no_network  # noqa: F401


def creates(fake, stop=False):
    return [q for m, p, q in fake.calls if p == "/v5/order/create" and ("triggerPrice" in q) == stop]


def entry_orders(fake):
    return [o for o in fake.orders.values() if o["triggerDirection"] == 0 and not o["reduceOnly"]]


# ------------------------------------------------------------------ 1. an accepted order never reads as "not executed"
def test_rate_limit_on_the_read_back_keeps_the_entry_and_protects_it(tmp_path):
    w = World(tmp_path)
    w.fake.market_lag = 1
    w.fake.fail("GET", "/v5/order/realtime", "429", times=1, when=lambda q: bool(q.get("orderId")))
    w.paper(stop=95.0)
    w.loop()
    assert len(creates(w.fake)) == 1 and len(entry_orders(w.fake)) == 1
    assert w.fake.pos[BTC] == 5 and w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    assert not w.events("entry_refused") and not w.protected_after_first_stop()
    w.store.close()


def test_ban_on_the_read_back_adopts_and_protects_after_the_ban(tmp_path):
    w = World(tmp_path)
    w.fake.fail("GET", "/v5/order/realtime", "403", times=1, when=lambda q: bool(q.get("orderId")))
    w.fake.fail("GET", "/v5/position/list", "403", times=1,
                when=lambda q: q.get("symbol") == BTC and w.fake.pos[BTC] != 0)      # still banned after the fill
    w.paper(stop=95.0)
    with pytest.raises(RateLimited):                       # the loop waits out the ban (run() sleeps 600 s)
        w.loop()
    assert w.fake.pos[BTC] == 5 and w.ex.trade["status"] == "entering" and not w.events("entry_refused")
    w.loop()                                               # ban over: the position is adopted and protected
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and w.events("recover")
    assert len(creates(w.fake)) == 1 and len(entry_orders(w.fake)) == 1
    w.store.close()


def test_rate_limited_create_with_a_lagging_lookup_never_doubles_the_entry(tmp_path):
    w = World(tmp_path)
    # executed, but answered "too many visits"; the look-ups by orderLinkId do not show it yet
    w.fake.fail("POST", "/v5/order/create", ("ret_after", 10006, "Too many visits!"), times=1,
                when=lambda q: "triggerPrice" not in q)
    for path in ("/v5/order/realtime", "/v5/order/history"):
        w.fake.fail("GET", path, ("ret", 0, "OK"), times=6, when=lambda q: bool(q.get("orderLinkId")))
    w.paper(stop=95.0)
    w.loop()
    assert len(entry_orders(w.fake)) == 1 and w.fake.pos[BTC] == 5            # the resend met 110072: no 2nd order
    assert len(creates(w.fake)) == 2 and creates(w.fake)[0]["orderLinkId"] == creates(w.fake)[1]["orderLinkId"]
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and not w.events("entry_refused")
    assert entry_orders(w.fake)[0]["orderId"] in w.ex.trade["orders"]      # found by its id after the stop
    w.src.intent = None
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.trades()[0][4] == "fills"            # so its P&L comes from its fills
    w.store.close()


def test_a_stop_created_but_answered_with_a_server_error_is_found_not_doubled(tmp_path):
    w = World(tmp_path)
    w.fake.fail("POST", "/v5/order/create", ("ret_after", 10016, "Server error"), times=1,
                when=lambda q: "triggerPrice" in q)
    w.paper(stop=95.0)
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and len(creates(w.fake, stop=True)) == 1 and not w.events("protect_failed")
    w.store.close()


def test_client_returns_the_accepted_order_when_its_read_back_fails():
    fake = FakeBybit()
    clock = Clock()
    fake.clock = clock
    c = BY.BybitClient("k", "s", send=fake, clock_ms=clock, sleep=lambda s: None)
    fake.fail("GET", "/v5/order/realtime", "503_before", times=9, when=lambda q: bool(q.get("orderId")))
    o = c.market(BTC, "BUY", 1.0, client_id="pbe9")
    assert o["status"] == "NEW" and o["orderId"] and "readBack" in o and fake.pos[BTC] == 1


# ------------------------------------------------------------------ 2. one database, one exchange
def binance_executor(w, db_cfg):
    store = ExecStore(db_cfg.db)
    cfg = ExecConfig(**{**db_cfg.__dict__, "exchange": "binance"})
    return store, lambda: Executor(cfg, TestnetClient("bk", "bs", send=FakeFutures(api_key="bk")), w.src, store,
                                   env={})


def test_a_database_of_the_other_exchange_is_refused(tmp_path):
    w = World(tmp_path)                                      # a Bybit database
    cfg = w.cfg
    w.store.close()
    store, make = binance_executor(w, cfg)
    with pytest.raises(Refused) as e:
        make()
    assert "bybit" in str(e.value)
    store.close()
    (tmp_path / "b").mkdir()
    w2 = World.__new__(World)
    b_cfg = ExecConfig(**{**cfg.__dict__, "db": str(tmp_path / "b" / "exec-testnet.db")})
    store, make = binance_executor(w, b_cfg)
    make().start()                                          # a Binance database (no "exchange" in it)
    store.close()
    with pytest.raises(Refused) as e:
        World.__init__(w2, tmp_path / "b")
    assert "binance" in str(e.value)
    w2.store.close()
    (tmp_path / "c").mkdir()                                # an old record: only the bot state, an open trade
    old = ExecStore(str(tmp_path / "c" / "exec-testnet.db"))
    old.put_state("bot", T0, {"trade": {"key": "V45_AMB@15m|BTCUSDT|1", "symbol": BTC, "status": "open"},
                              "mode": "testnet", "account": "V45_AMB@15m"})
    old.close()
    w3 = World.__new__(World)
    with pytest.raises(Refused):
        World.__init__(w3, tmp_path / "c")
    w3.store.close()


def test_binance_databases_keep_their_meta_unchanged(tmp_path):
    w = World(tmp_path)
    assert w.store.get_state("meta")["exchange"] == "bybit"
    w.store.close()
    (tmp_path / "b").mkdir()
    cfg = ExecConfig(**{**w.cfg.__dict__, "db": str(tmp_path / "b" / "e.db")})
    store, make = binance_executor(w, cfg)
    make()
    assert set(store.get_state("meta")) == {"mode", "account", "since"}
    store.close()


# ------------------------------------------------------------------ 3. the sign of realized P&L
def scenario(fake, clock):
    c = BY.BybitClient("k", "s", send=fake, clock_ms=clock, sleep=lambda s: None)
    c.market(BTC, "BUY", 2.0)
    clock.t += 1000
    fake.set_price(BTC, 110.0)
    c.market(BTC, "SELL", 3.0)                                # closes the long 2, opens a short 1
    clock.t += 1000
    fake.set_price(BTC, 105.0)
    c.market(BTC, "BUY", 1.0, reduce_only=True)
    return c.user_trades(BTC, T0 - 5000, clock.t + 5000)


@pytest.mark.parametrize("meaning", ["order", "position"])
def test_realized_sign_comes_from_the_fills_not_the_records_side(meaning):
    fake, clock = FakeBybit(), Clock()
    fake.clock = clock
    fake.closed_side = meaning
    fills = scenario(fake, clock)
    assert [round(float(f["realizedPnl"]), 6) for f in fills] == [0.0, 20.0, 5.0]
    assert [f["realizedCheck"] for f in fills] == [None, "ok", "ok"]


def test_a_record_that_disagrees_is_flagged():
    fake, clock = FakeBybit(), Clock()
    fake.clock = clock

    def flip(r):                                              # the gross P&L with the opposite sign
        gross = float(r["closedPnl"]) + float(r["openFee"]) + float(r["closeFee"])
        return {**r, "closedPnl": str(-gross - float(r["openFee"]) - float(r["closeFee"]))}
    fake.closed_tamper = flip
    fills = scenario(fake, clock)
    assert [f["realizedCheck"] for f in fills] == [None, "mismatch", "mismatch"]


def test_the_executor_keeps_the_wallet_estimate_and_alerts_on_a_mismatch(tmp_path):
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 104.0)
    w.fake.closed_tamper = lambda r: {**r, "closedPnl": str(-abs(float(r["closedPnl"])) - 50)}
    w.src.intent = None
    w.loop()
    key, qty, reason, pnl, source = w.trades()[0]
    assert source == "wallet" and pnl == pytest.approx(w.fake.wallet - 10_000.0) and pnl > 0
    assert w.ex.risk.consecutive_losses == 0
    assert {lvl for _, lvl, _ in w.events("pnl_check")} == {WARN}           # recorded at each check, alerted once
    assert sum("closed-pnl" in t for _, t in w.note.messages) == 1
    w.loop(3)                                                 # retried later: still not booked, not alerted again
    assert w.trades()[0][4] == "wallet" and sum("closed-pnl" in t for _, t in w.note.messages) == 1
    w.store.close()


def test_the_drill_fails_when_the_sign_is_flipped(monkeypatch):
    def run(fake):
        clock = Clock()
        fake.clock, fake.slip = clock, 0.001                  # entry above, exit below: a real loss to check
        c = BY.BybitClient("k", "s", send=fake, clock_ms=clock, sleep=lambda s: None)
        return BY.BybitDrill(c, BTC, wait=lambda s: None).run()
    log = run(FakeBybit())
    assert all(r["ok"] for r in log) and log[-1]["detail"]["realized"] < 0
    real = BY.fills_from_executions

    def flipped(execs, closed=None):
        out = real(execs, closed)
        for f in out:
            f["realizedPnl"] = BY._num(-BY.Decimal(f["realizedPnl"]))
            if f["realizedCheck"] == "mismatch":
                f["realizedCheck"] = "ok"                      # even if the cross-check were fooled too
        return out
    monkeypatch.setattr(BY, "fills_from_executions", flipped)
    with pytest.raises(AssertionError) as e:
        run(FakeBybit())
    assert "fills and P&L" in str(e.value)


# ------------------------------------------------------------------ 4. the key: contract trading only, a sub-account
@pytest.mark.parametrize("group,names", [
    ("FiatP2P", ["FiatP2POrder"]), ("FiatBitPay", ["FaitPayOrder"]), ("FiatConvertBroker", ["FiatConvertBrokerOrder"]),
    ("BitCard", ["BitCard"]), ("BlockTrade", ["BlockTrade"]), ("Affiliate", ["Affiliate"]), ("ByXPost", ["ByXPost"]),
    ("Earn", ["Earn"]), ("Exchange", ["ExchangeHistory"]), ("CopyTrading", ["x"]), ("NFT", ["x"]),
    ("Spot", ["SpotTrade"]), ("Options", ["OptionsTrade"]), ("Wallet", ["Withdraw"]), ("Wallet", ["AccountTransfer"]),
    ("Wallet", ["SomethingNew"]), ("SomethingNew", ["x"])])
def test_every_permission_but_contract_trading_is_refused(group, names):
    info = FakeBybit().key_info
    rec = BY.permission_record({**info, "permissions": {**info["permissions"], group: names}})
    assert check_permissions(rec), (group, names)


def test_a_main_account_key_is_refused():
    info = FakeBybit().key_info
    ok = {**info, "permissions": {"ContractTrade": ["Order", "Position"], "Derivatives": ["DerivativesTrade"],
                                  "Spot": [], "Wallet": [], "FiatP2P": []}}
    assert check_permissions(BY.permission_record(ok)) == []
    for master in (True, None):
        probs = check_permissions(BY.permission_record({**ok, "isMaster": master}))
        assert any("하위 계정" in p for p in probs), master


def test_mainnet_refuses_a_main_account_key(tmp_path):
    fake = FakeBybit(wallet=520.0, host="api.bybit.com", api_key="lk", api_secret="ls")
    fake.key_info["isMaster"] = True
    w = World.__new__(World)
    with pytest.raises(Refused) as e:
        World.__init__(w, tmp_path, mode="mainnet", fake=fake, env=LIVE_ENV)
    assert "하위 계정" in str(e.value)
    w.store.close()


# ------------------------------------------------------------------ 5. client ids never repeat
def test_stop_and_close_ids_never_repeat_after_a_restart_that_lost_the_counter(tmp_path):
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    bot = w.store.get_state("bot")
    bot["trade"]["n"] = 0                                     # the counter's save was lost before the restart
    w.store.put_state("bot", T0, bot)
    w.store.commit()
    w.restart()
    for o in w.fake.live_stops(BTC):
        o["orderStatus"] = "Deactivated"                       # its stop is gone: placed again
    w.loop()
    w.fake.set_price(BTC, 106.0)
    w.paper(stop=101.1)
    w.loop()
    w.src.intent = None
    w.loop()
    links = [q["orderLinkId"] for m, p, q in w.fake.calls if p == "/v5/order/create"]
    assert len(links) == len(set(links)) == 5 and all(len(x) <= 36 for x in links)
    assert w.fake.pos[BTC] == 0 and not w.events("protect_failed") and w.trades()[0][4] == "fills"
    w.store.close()


def test_binance_client_ids_are_unchanged(tmp_path):
    w = World(tmp_path)
    w.store.close()
    store, make = binance_executor(w, ExecConfig(**{**w.cfg.__dict__, "db": str(tmp_path / "bn.db")}))
    ex = make()
    t = {"base": "0123456789ab", "n": 4}
    assert ex._cid(t, "s") == "pb0123456789abs5"
    store.close()


def test_a_duplicate_id_on_a_stop_is_looked_up_not_a_failed_protection(tmp_path):
    w = World(tmp_path)
    w.fake.fail("POST", "/v5/order/create", ("ret_after", 110072, "OrderLinkedID is duplicate"), times=1,
                when=lambda q: "triggerPrice" in q)
    w.paper(stop=95.0)
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.ex.trade["status"] == "open" and not w.events("protect_failed")
    w.store.close()


# ------------------------------------------------------------------ minor
@pytest.mark.parametrize("code,msg", [(-1, "request expired"), (10014, "Invalid duplicate request"),
                                      (10002, "invalid request, please check your server timestamp")])
def test_expired_or_replayed_requests_resync_and_retry(tmp_path, code, msg):
    w = World(tmp_path)
    w.fake.fail("GET", "/v5/position/list", ("ret", code, msg), times=1, when=lambda q: q.get("settleCoin"))
    w.fake.fail("POST", "/v5/order/create", ("ret", code, msg), times=1, when=lambda q: "triggerPrice" not in q)
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 5 and len(entry_orders(w.fake)) == 1 and w.stops() == [(95.0, 5.0)]
    assert sum("서버 시간 다시 맞춤" in t for _, _, t in w.events("retry")) == 2
    w.store.close()


def test_bonuses_airdrops_refunds_and_converts_are_not_trading_pnl(tmp_path):
    w = World(tmp_path)
    w.loop()
    for kind, amount in (("FEE_REFUND", 3.0), ("AIRDROP", 5.0), ("CURRENCY_BUY", -2.0), ("BONUS", 1.0)):
        w.fake.add_log(kind, amount)
    w.clock.t += 61_000
    w.loop()
    assert len(w.events("transfer")) == 4 and w.ex.risk.transfers == pytest.approx(7.0)
    rows = w.client.income(None, None, T0, w.clock.t)
    assert {r["info"]: r["incomeType"] for r in rows} == {"FEE_REFUND": "TRANSFER", "AIRDROP": "TRANSFER",
                                                         "CURRENCY_BUY": "TRANSFER", "BONUS": "TRANSFER"}
    w.store.close()


def test_preflight_reports_account_type_margin_and_position_mode(tmp_path):
    fake = FakeBybit()
    fake.hedge[BTC] = True
    w = World.__new__(World)
    World.__init__(w, tmp_path, fake=fake)
    w.store.close()
    w.fake.info["marginMode"], w.fake.hedge[BTC] = "REGULAR_MARGIN", True      # as before the executor's start
    lines = []
    preflight(w.cfg, w.client, None, out=lines.append)
    assert "[OK]   계정 종류: 통합 거래 계정 UTA 2.0 pro (unifiedMarginStatus 6)" in lines
    assert any(x.startswith("[OK]") and "REGULAR_MARGIN" in x and "격리 마진으로 바꿉니다" in x for x in lines)
    assert any(x.startswith("[OK]") and "양방향" in x and BTC in x for x in lines)
    fake.pos["ETHUSDT"], fake.entry["ETHUSDT"] = BY.Decimal("1"), 50.0          # something open: cannot switch
    lines = []
    preflight(w.cfg, w.client, None, out=lines.append)
    assert any(x.startswith("[FAIL]") and "REGULAR_MARGIN" in x for x in lines)
    fake.info["marginMode"], fake.hedge[BTC], fake.pos["ETHUSDT"] = "ISOLATED_MARGIN", False, BY.Decimal("0")
    lines = []
    preflight(w.cfg, w.client, None, out=lines.append)
    assert "[OK]   마진 모드: 격리(ISOLATED_MARGIN)" in lines and "[OK]   포지션 모드: 단방향(one-way)" in lines


def test_active_orders_are_listed_and_cancelled_by_the_order_filter():
    fake, clock = FakeBybit(), Clock()
    fake.clock = clock
    c = BY.BybitClient("k", "s", send=fake, clock_ms=clock, sleep=lambda s: None)
    c.market(BTC, "BUY", 1.0)
    c.stop_close(BTC, "SELL", 95.0, qty=1.0)
    oid = fake.add_resting(BTC, "Buy", "0.5", 90.0)
    assert [o["orderId"] for o in c.open_orders(BTC)] == [oid]            # active orders only, not the stop
    assert [o["orderType"] for o in c.open_algo_orders(BTC)] == ["STOP_MARKET"]
    assert c.cancel_all(BTC)["cancelled"] == 1 and not c.open_orders(BTC)
    assert len(fake.live_stops(BTC)) == 1                                # the stop stays (StopOrder is separate)
