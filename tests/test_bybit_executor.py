"""The executor (unchanged order logic) on the fake Bybit v5 exchange: ``"exchange": "bybit"``. Mirrors
tests/test_executor.py and the mainnet gates of tests/test_live_mainnet.py. No network."""

import json
import socket

import pytest

from fakebybit import FakeBybit
from paperbot import risk as R
from paperbot.bybit import BybitClient, BybitKeyCheckClient, BybitMainnetClient, Decimal
from paperbot.executor import ExecConfig, ExecStore, Executor, Intent, Paper3Source, Refused, main, preflight
from paperbot.mainnet import FLAG, FLAG_VALUE
from paperbot.notify import CRITICAL, ListNotifier
from paperbot.testnet import TestnetClient

T0 = 1_800_000_000_000
BTC = "BTCUSDT"
TESTNET_ENV = {"BYBIT_TESTNET_API_KEY": "k", "BYBIT_TESTNET_API_SECRET": "s"}
LIVE_ENV = {FLAG: FLAG_VALUE, "BYBIT_LIVE_API_KEY": "lk", "BYBIT_LIVE_API_SECRET": "ls"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Source:
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
    def __init__(self, tmp_path, fake=None, mode="testnet", env=None, cfg_kw=None, **risk_kw):
        self.tmp, self.mode = tmp_path, mode
        self.clock = Clock()
        live = mode == "mainnet"
        self.fake = fake or FakeBybit(wallet=520.0 if live else 10_000.0,
                                      host="api.bybit.com" if live else "api-testnet.bybit.com",
                                      api_key="lk" if live else "k", api_secret="ls" if live else "s")
        self.fake.clock = self.clock
        self.src = Source(self.clock)
        self.note = ListNotifier()
        self.sleeps = []
        self.env = dict(env if env is not None else (LIVE_ENV if live else TESTNET_ENV))
        self.cfg = ExecConfig(account="V45_AMB@15m", paper_db=str(tmp_path / "paper3.db"),
                              db=str(tmp_path / f"exec-{mode}.db"), qty_scale=1.0, risk=risk_cfg(tmp_path, **risk_kw),
                              retries=4, sweep_every=1, exchange="bybit", mode=mode,
                              budget_usd=500.0 if live else None, paper_env_file=str(tmp_path / "live.env"),
                              **(cfg_kw or {}))
        self.open()

    def clients(self):
        if self.mode == "mainnet":
            kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda s: None)
            return BybitMainnetClient("lk", "ls", **kw), BybitKeyCheckClient("lk", "ls", **kw)
        return BybitClient("k", "s", send=self.fake, clock_ms=self.clock, sleep=lambda s: None), None

    def open(self, start=True):
        self.store = ExecStore(self.cfg.db)
        self.client, self.keycheck = self.clients()
        self.ex = Executor(self.cfg, self.client, self.src, self.store, self.note, now_ms=self.clock,
                           sleep=self.sleeps.append, keycheck=self.keycheck, env=self.env)
        if start:
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
        return self.store.conn.execute("SELECT key, qty, exit_reason, pnl, pnl_source FROM trades ORDER BY entry_ts"
                                       ).fetchall()

    def stops(self, symbol=BTC):
        return [(float(o["triggerPrice"]), float(o["qty"])) for o in self.fake.live_stops(symbol)]

    def stop_posts(self):
        return [i for i, c in enumerate(self.fake.calls) if c[1] == "/v5/order/create" and "triggerPrice" in c[2]]

    def protected_after_first_stop(self, symbol=BTC):
        first = self.stop_posts()[0]
        return [t for t in self.fake.unprotected_moments(symbol) if t[0] > first]


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path)
    yield world
    world.store.close()


# ------------------------------------------------------------------ entry and stops
def test_entry_places_market_and_a_confirmed_exchange_stop(w):
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.orders
    assert w.fake.info["marginMode"] == "ISOLATED_MARGIN" and w.fake.hedge[BTC] is False   # set at the start
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 5 and w.stops() == [(95.0, 5.0)] and w.fake.lev[BTC] == "20"
    stop = w.fake.live_stops(BTC)[0]
    assert stop["triggerBy"] == "LastPrice" and stop["reduceOnly"] and stop["closeOnTrigger"]
    assert stop["triggerDirection"] == 2 and stop["side"] == "Sell"
    assert w.ex.trade["status"] == "open" and w.ex.trade["stop_algo_id"] == stop["orderId"]
    i = w.stop_posts()[0]
    assert w.fake.calls[i + 1][:2] == ("GET", "/v5/order/realtime")          # confirmed live by its id
    assert w.fake.calls[i + 1][2]["orderId"] == stop["orderId"]
    early = [t for t in w.fake.unprotected_moments(BTC) if t[0] <= i]
    assert [t[2] for t in early] == ["/v5/order/create", "/v5/order/realtime", "/v5/position/list"]
    assert not w.protected_after_first_stop()
    assert w.trades()[0][1] == 5.0
    rows = w.store.conn.execute("SELECT method, path, params FROM requests").fetchall()
    assert any(p == "/v5/order/create" and '"triggerPrice": "95.00"' in prm for _, p, prm in rows)
    assert not any("X-BAPI" in prm or "sign" in prm.lower() for *_, prm in rows)
    assert any("[바이비트 테스트넷 실행기]" in t for _, t in w.note.messages) or w.ex.prefix == "[바이비트 테스트넷 실행기]"


def test_lock_steps_never_leave_the_position_unprotected_and_pnl_from_fills(w):
    w.paper(stop=95.0)
    w.loop()
    wallet0 = 10_000.0
    for price, lock in [(105.0, 101.1), (109.0, 104.9), (113.0, 109.3), (118.0, 113.6)]:
        w.fake.set_price(BTC, price)
        w.paper(stop=lock)
        w.loop()
        assert w.stops() == [(lock, 5.0)], (price, lock)
        assert w.ex.trade["stop"] == lock and not w.protected_after_first_stop()
    w.fake.set_price(BTC, 125.0)
    w.paper(stop=118.0)
    w.fake.fail("POST", "/v5/order/create", "503_after")                    # placed, answer lost
    w.loop()
    assert w.stops() == [(118.0, 5.0)]                                      # found by orderLinkId: no duplicate
    w.paper(stop=120.0)
    w.fake.fail("POST", "/v5/order/create", ("ret", 10001, "params error"))  # refused: the old stop stays
    w.loop()
    assert w.stops() == [(118.0, 5.0)] and w.events("move_failed")
    w.fake.fail("POST", "/v5/order/cancel", "drop_before")
    w.loop()
    assert w.stops() == [(120.0, 5.0)] and not w.protected_after_first_stop()
    w.fake.add_funding(BTC, -1.25)                                          # funding while open
    w.src.intent = None                                                     # paper exit
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.live_stops() and w.ex.trade is None
    key, qty, reason, pnl, source = w.trades()[0]
    assert "paper 청산" in reason and source == "fills"
    assert pnl == pytest.approx(w.fake.wallet - wallet0, abs=1e-9)          # fills + funding = the wallet change
    realized, commission, funding = w.store.conn.execute("SELECT realized, commission, funding FROM trades").fetchone()
    assert realized == pytest.approx(5 * (125.0 - 100.0)) and funding == pytest.approx(-1.25)
    assert commission == pytest.approx(0.00055 * 5 * (100.0 + 125.0))
    assert not w.protected_after_first_stop()


def test_lock_past_the_price_closes_with_a_reduce_only_market_order(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 100.5)
    w.paper(stop=101.1)                                                     # 110093: the price is already below
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.live_stops() and w.ex.trade is None
    assert w.events("stop_would_trigger") and "시장가" in w.trades()[0][2]
    closes = [c for c in w.fake.calls if c[1] == "/v5/order/create" and c[2].get("reduceOnly")
              and "triggerPrice" not in c[2]]
    assert len(closes) == 1
    w.loop(3)
    assert w.fake.pos[BTC] == 0 and len(w.trades()) == 1


def test_stop_hit_on_the_exchange_is_booked_from_its_fills(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 94.0)
    assert w.fake.pos[BTC] == 0
    w.loop()
    key, qty, reason, pnl, source = w.trades()[0]
    assert "거래소 손절" in reason and source == "fills" and w.ex.risk.consecutive_losses == 1
    assert pnl == pytest.approx(5 * (94.0 - 100.0) - 0.00055 * 5 * (100.0 + 94.0))
    w.loop(2)
    assert w.fake.pos[BTC] == 0 and len(w.trades()) == 1


def test_partial_fill_gets_a_stop_for_what_was_filled(w):
    w.fake.partial = 0.6
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 3 and w.stops() == [(95.0, 3.0)] and w.events("partial_fill")


def test_async_order_reads_and_late_cancels(w):
    w.fake.market_lag, w.fake.cancel_lag = 2, 1
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 5 and w.stops() == [(95.0, 5.0)]
    w.fake.set_price(BTC, 106.0)
    w.paper(stop=101.1)
    w.loop(2)                                     # the old stop still listed for a read: cancelled again, quietly
    assert w.stops() == [(101.1, 5.0)] and not w.events("no_stop") and not w.protected_after_first_stop()
    w.src.intent = None
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and w.trades()[0][4] == "fills"


# ------------------------------------------------------------------ reconcile
def test_unknown_position_is_closed_and_alerted(w):
    w.fake.pos["ETHUSDT"], w.fake.entry["ETHUSDT"] = Decimal("2"), 50.0
    w.loop()
    assert w.fake.pos["ETHUSDT"] == 0
    assert any(lvl == CRITICAL and "모르는 포지션" in txt for lvl, txt in w.note.messages)


def test_missing_stop_is_put_back_or_the_position_closed(w):
    w.paper(stop=95.0)
    w.loop()
    for o in w.fake.live_stops(BTC):
        o["orderStatus"] = "Deactivated"                                    # removed on the website
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.events("no_stop")
    for o in w.fake.live_stops(BTC):
        o["orderStatus"] = "Deactivated"
    w.fake.last[BTC] = 94.0                                                 # and the price is already past it
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and not w.fake.live_stops()


def test_stop_size_follows_the_position_both_ways(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.pos[BTC] = Decimal("7")                                           # grew outside the bot
    w.loop()
    assert w.stops() == [(95.0, 7.0)] and w.ex.trade["qty"] == 7.0 and w.events("size_mismatch")
    w.fake.pos[BTC] = Decimal("4")                                           # shrank: a larger stop is replaced
    n = len(w.fake.calls)
    w.loop()
    assert w.stops() == [(95.0, 4.0)] and w.events("stop_size")
    assert not [t for t in w.fake.unprotected_moments(BTC) if t[0] >= n]    # new stop first, then the old one goes
    w.client.stop_close(BTC, "SELL", 90.0, qty=4.0)                         # a stray extra stop
    w.loop()
    assert w.stops() == [(95.0, 4.0)] and w.events("extra_stops")


def test_stray_stops_without_a_position_are_cancelled(w):
    w.fake.pos[BTC] = Decimal("1")
    w.client.stop_close(BTC, "SELL", 90.0, qty=1.0)
    w.fake.pos[BTC] = Decimal("0")
    w.loop()
    assert not w.fake.live_stops() and w.events("stray_orders")


# ------------------------------------------------------------------ restarts and unknown outcomes
def test_restart_after_crash_between_fill_and_stop(w):
    w.paper(stop=95.0)

    def die(*a, **k):
        raise KeyboardInterrupt("process killed")
    w.ex._protect = die
    with pytest.raises(KeyboardInterrupt):
        w.loop()
    assert w.fake.pos[BTC] == 5 and not w.fake.live_stops()
    w.restart()
    assert w.ex.trade["status"] == "open"
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.events("no_stop")


def test_entry_with_an_unknown_outcome_is_never_sent_twice(w):
    w.paper(stop=95.0)
    w.fake.fail("POST", "/v5/order/create", "drop_before", times=8)
    w.fake.fail("GET", "/v5/order/realtime", "drop_before", times=8, when=lambda q: "orderLinkId" in q)
    w.loop()
    assert w.ex.trade["status"] == "entering" and w.events("entry_unknown")
    w.fake.failures.clear()
    w.restart()
    w.clock.t += 61_000
    w.loop()
    assert w.ex.trade is None and w.fake.pos[BTC] == 0 and w.events("recover")
    w.paper(stop=96.0, entry_time=w.clock.t - 30_000)
    w.fake.fail("POST", "/v5/order/create", "drop_after")                    # executed, answer lost
    w.loop()
    entries = [c for c in w.fake.calls if c[1] == "/v5/order/create" and "triggerPrice" not in c[2]
               and not c[2].get("reduceOnly")]
    assert len(entries) == 1 and w.fake.pos[BTC] == 5 and w.stops() == [(96.0, 5.0)]
    w.fake.fail("POST", "/v5/order/create", ("ret_after", 10016, "Server error"))   # a server error after the stop
    w.paper(stop=97.0)
    w.loop()
    assert w.stops() == [(97.0, 5.0)]                                       # looked up, not doubled


def test_restart_keeps_open_trade_and_lock(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 106.0)
    w.paper(stop=101.1)
    w.loop()
    w.restart()
    assert w.ex.trade["stop"] == 101.1
    w.loop()
    assert w.stops() == [(101.1, 5.0)] and w.fake.pos[BTC] == 5 and not w.protected_after_first_stop()


# ------------------------------------------------------------------ margin mode, risk
def test_no_entry_unless_isolated(tmp_path):
    fake = FakeBybit()
    fake.margin_refusal = "Equity needs to be equal to or greater than 1000 USDC"
    w = World.__new__(World)
    with pytest.raises(Refused):                                            # nothing open: the executor does not start
        World.__init__(w, tmp_path, fake=fake)
    assert w.events("margin_refused") and any(lvl == CRITICAL and "1000 USDC" in t for lvl, t in w.note.messages)
    w.store.close()
    (tmp_path / "b").mkdir()
    fake2 = FakeBybit()
    fake2.pos["ETHUSDT"], fake2.entry["ETHUSDT"] = Decimal("1"), 50.0          # restart with a cross position open
    w2 = World(tmp_path / "b", fake=fake2)
    assert w2.events("margin") and fake2.info["marginMode"] == "REGULAR_MARGIN"
    w2.loop()                                                                # the unknown position is closed
    assert fake2.pos["ETHUSDT"] == 0
    fake2.margin_refusal = "Equity needs to be equal to or greater than 1000 USDC"
    w2.paper(stop=95.0, entry_time=w2.clock.t)
    w2.loop()                                                                # still cross margin: never an entry
    assert fake2.pos[BTC] == 0 and w2.events("leverage_refused")
    fake2.margin_refusal = None
    w2.paper(stop=95.0, entry_time=w2.clock.t)
    w2.loop()                                                                # nothing open now: switched, entered
    assert fake2.info["marginMode"] == "ISOLATED_MARGIN" and fake2.pos[BTC] == 5 and w2.stops() == [(95.0, 5.0)]
    w2.store.close()


def test_kill_switch_flattens_and_halts(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()
    (tmp_path / "STOP").write_text("")
    w.loop()
    assert w.fake.pos[BTC] == 0 and not w.fake.live_stops() and w.ex.risk.halted


def test_daily_loss_halt(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=60.0)
    w.paper(stop=90.0)
    w.loop()
    assert w.fake.pos[BTC] == 5
    w.fake.set_price(BTC, 95.5)
    w.fake.add_funding(BTC, -40.0)
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted and "하루 한도" in w.ex.risk.halt_reason
    w.store.close()


def test_deposits_are_not_profit(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=60.0)
    w.loop()
    w.fake.add_transfer(-80.0)                                              # a withdrawal is not a loss
    w.clock.t += 61_000
    w.loop()
    assert not w.ex.risk.halted and w.events("transfer")


# ------------------------------------------------------------------ refusals
def test_refuses_the_wrong_client_host_or_config(tmp_path):
    w = World(tmp_path)
    w.store.close()
    store = ExecStore(str(tmp_path / "x.db"))
    try:
        for c in (TestnetClient("k", "s", send=w.fake),                    # a Binance client with exchange bybit
                  BybitMainnetClient("k", "s", send=w.fake)):               # a mainnet client in testnet mode
            with pytest.raises(Refused):
                Executor(w.cfg, c, w.src, store, env=TESTNET_ENV)
        c = BybitClient("k", "s", send=w.fake)
        c.base = "https://api.bybit.com"                                    # tampered after construction
        with pytest.raises(Refused):
            Executor(w.cfg, c, w.src, store, env=TESTNET_ENV)
        binance_cfg = ExecConfig(**{**w.cfg.__dict__, "exchange": "binance"})
        with pytest.raises(Refused):                                        # a Bybit client with exchange binance
            Executor(binance_cfg, BybitClient("k", "s", send=w.fake), w.src, store, env=TESTNET_ENV)
        with pytest.raises(Refused):                                        # the key is a Binance key
            Executor(w.cfg, BybitClient("k", "s", send=w.fake), w.src, store, env={**TESTNET_ENV, "LIVE_API_KEY": "k"})
        for bad in ({"exchange": "gate"}, {"bybit_host": "api.bytick.com"}, {"exchange": "binance",
                                                                              "bybit_host": "api-testnet.bybit.com"}):
            probs = ExecConfig(**{**w.cfg.__dict__, **bad}).problems()
            assert any("exchange" in p or "bybit_host" in p for p in probs), bad
        assert ExecConfig(**{**w.cfg.__dict__, "bybit_host": "api-testnet.bybit.com"}).problems() == []
    finally:
        store.close()


def test_cli_check_config_and_keys(tmp_path, monkeypatch, capsys):
    conf = tmp_path / "c.json"
    risk = {**R.RiskConfig().__dict__, **risk_cfg(tmp_path).__dict__, "allowed_symbols": [BTC]}
    conf.write_text(json.dumps({"account": "A@15m", "paper_db": "p", "db": str(tmp_path / "e.db"), "qty_scale": 1,
                                "exchange": "bybit", "risk": risk}))
    assert main(["check-config", "--config", str(conf)]) == 0
    for k in ("BYBIT_TESTNET_API_KEY", "BYBIT_TESTNET_API_SECRET", "TESTNET_API_KEY", "BINANCE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "same")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "x")
    monkeypatch.setenv("BINANCE_API_KEY", "same")
    assert main(["run", "--config", str(conf), "--max-loops", "0"]) == 2     # refused before any request
    capsys.readouterr()


# ------------------------------------------------------------------ mainnet gates
def test_mainnet_gates_and_a_full_cycle(tmp_path):
    w = World(tmp_path, mode="mainnet")
    assert w.events("mainnet_gates") and w.ex.prefix == "[바이비트 실거래 실행기]"
    w.paper(stop=95.0, qty=2.0)
    w.loop()
    assert w.fake.pos[BTC] == 2 and w.stops() == [(95.0, 2.0)]
    w.src.intent = None
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.trades()[0][4] == "fills"
    w.store.close()


@pytest.mark.parametrize("change,needle", [
    ({"ips": []}, "IP"), ({"readOnly": 1}, "선물"),
    ({"permissions": {"ContractTrade": ["Order", "Position"], "Wallet": ["Withdraw"]}}, "출금"),
    ({"permissions": {"ContractTrade": ["Order", "Position"], "Spot": ["SpotTrade"]}}, "현물"),
])
def test_mainnet_refuses_a_key_with_the_wrong_permissions(tmp_path, change, needle):
    fake = FakeBybit(wallet=520.0, host="api.bybit.com", api_key="lk", api_secret="ls")
    fake.key_info.update(change)
    with pytest.raises(Refused) as e:
        World(tmp_path, mode="mainnet", fake=fake)
    assert needle in str(e.value)


def test_mainnet_balance_and_asset_guards_and_preflight(tmp_path):
    fake = FakeBybit(wallet=900.0, host="api.bybit.com", api_key="lk", api_secret="ls")
    (tmp_path / "a").mkdir()
    with pytest.raises(Refused) as e:
        World(tmp_path / "a", mode="mainnet", fake=fake)
    assert "1.2배" in str(e.value)
    fake = FakeBybit(wallet=500.0, host="api.bybit.com", api_key="lk", api_secret="ls")
    fake.other_coins = {"BTC": 0.01}
    (tmp_path / "b").mkdir()
    with pytest.raises(Refused) as e:
        World(tmp_path / "b", mode="mainnet", fake=fake)
    assert "USDT 말고" in str(e.value)
    fake.other_coins = {}
    (tmp_path / "c").mkdir()
    w = World(tmp_path / "c", mode="mainnet", fake=fake, cfg_kw={"bybit_host": "api.bybit.com"})
    lines = []
    w.client.offset_ms = 0
    preflight(w.cfg, w.client, w.keycheck, out=lines.append)
    assert any("api.bybit.com" in x for x in lines) and any("출금 꺼짐" in x for x in lines)
    assert [x for x in lines if x.startswith("[FAIL]")] == ["[FAIL] paper3.db: unable to open database file"]
    w.store.close()


def test_mainnet_needs_the_flag_and_its_own_keys(tmp_path):
    for i, env in enumerate(({**LIVE_ENV, FLAG: ""}, {**LIVE_ENV, "BYBIT_TESTNET_API_KEY": "lk"},
                             {**LIVE_ENV, "BINANCE_API_SECRET": "ls"})):
        (tmp_path / str(i)).mkdir()
        with pytest.raises(Refused):
            World(tmp_path / str(i), mode="mainnet", env=env)


# ------------------------------------------------------------------ the combined bot account, from its database
def test_follows_the_combined_account_from_its_database_at_40x(tmp_path):
    """COMBO@mix from a paper database (the research16.db layout: the accounts state) -> the unchanged executor ->
    Bybit: BTC at 40x isolated, the stop resting on the exchange, the lock moving it, the exit booked from fills."""
    from paperbot.store3 import Store3
    db = str(tmp_path / "research16.db")
    s = Store3(db)
    clock = Clock()

    def put(position):
        s.put_state("accounts", clock.t - 20_000, {"last_ts": clock.t, "engines": {"COMBO@mix": {
            "wallet": 1000.0, "position": position, "pending": []}}})
        s.commit()
    pos = {"symbol": BTC, "side": 1, "qty": 4.0, "leverage": 40, "stop_price": 97.5, "entry_price": 100.0,
           "entry_time": clock.t - 30_000, "signal": {}}
    put(pos)
    fake = FakeBybit(wallet=100.0)
    fake.clock = clock
    cfg = ExecConfig(account="COMBO@mix", paper_db=db, db=str(tmp_path / "exec.db"), qty_scale=0.1,
                     risk=risk_cfg(tmp_path, max_leverage=40, max_notional_usd=10_000.0, max_loss_frac=0.35,
                                   daily_max_loss_usd=40.0, max_drawdown_pct=0.5),
                     exchange="bybit", sweep_every=1, paper_env_file=str(tmp_path / "live.env"))
    store = ExecStore(cfg.db)
    ex = Executor(cfg, BybitClient("k", "s", send=fake, clock_ms=clock, sleep=lambda x: None),
                  Paper3Source(db, cfg.account), store, ListNotifier(), now_ms=clock, sleep=lambda x: None,
                  env=TESTNET_ENV)
    ex.start()
    clock.t += 3_000
    ex.loop_once()
    assert fake.pos[BTC] == Decimal("0.4") and fake.lev[BTC] == "40" and fake.info["marginMode"] == "ISOLATED_MARGIN"
    assert [(o["triggerPrice"], o["qty"]) for o in fake.live_stops(BTC)] == [("97.50", "0.400")]
    fake.set_price(BTC, 104.0)
    put({**pos, "stop_price": 101.0})
    clock.t += 3_000
    ex.loop_once()
    assert [o["triggerPrice"] for o in fake.live_stops(BTC)] == ["101.00"]
    put(None)
    clock.t += 3_000
    ex.loop_once()
    assert fake.pos[BTC] == 0 and not fake.live_stops()
    pnl, source = store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
    assert source == "fills" and pnl == pytest.approx(fake.wallet - 100.0)
    store.close()
    s.close()
