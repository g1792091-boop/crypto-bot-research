"""The executor (unchanged order logic) on the fake MEXC contract exchange: ``"exchange": "mexc"``, mainnet only (MEXC
has no futures testnet). Mirrors tests/test_bybit_executor.py. No network."""

import json
import socket
from decimal import Decimal

import pytest

from fakemexc import FakeMexc
from paperbot import mexc as MX
from paperbot import risk as R
from paperbot.bybit import BybitMainnetClient
from paperbot.executor import ExecConfig, ExecStore, Executor, Intent, Paper3Source, Refused, main, preflight
from paperbot.mainnet import FLAG, FLAG_VALUE
from paperbot.notify import CRITICAL, WARN, ListNotifier

T0 = 1_800_000_000_000
BTC = "BTCUSDT"
B = "BTC_USDT"
LIVE_ENV = {FLAG: FLAG_VALUE, "MEXC_LIVE_KEY": "mk", "MEXC_LIVE_SECRET": "ms", MX.KEY_CHECKED: MX.KEY_CHECKED_VALUE}


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
    def __init__(self, tmp_path, fake=None, env=None, cfg_kw=None, budget=10_000.0, **risk_kw):
        self.tmp = tmp_path
        self.clock = Clock()
        self.fake = fake or FakeMexc(wallet=10_000.0)
        self.fake.clock = self.clock
        self.src = Source(self.clock)
        self.note = ListNotifier()
        self.sleeps = []
        self.env = dict(env if env is not None else LIVE_ENV)
        self.cfg = ExecConfig(account="V45_AMB@15m", paper_db=str(tmp_path / "paper3.db"),
                              db=str(tmp_path / "exec-mexc.db"), qty_scale=1.0, risk=risk_cfg(tmp_path, **risk_kw),
                              retries=4, sweep_every=1, exchange="mexc", mode="mainnet", budget_usd=budget,
                              paper_env_file=str(tmp_path / "live.env"), **(cfg_kw or {}))
        self.open()

    def clients(self):
        kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda s: None,
                  base=f"https://{self.cfg.mexc_host}" if self.cfg.mexc_host else None)
        attested = self.env.get(MX.KEY_CHECKED) == MX.KEY_CHECKED_VALUE
        return MX.MexcClient("mk", "ms", **kw), MX.MexcKeyCheckClient("mk", "ms", attested=attested, **kw)

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

    def amt(self, symbol=B):
        return float(self.fake.amt(symbol))

    def events(self, kind=None):
        q = "SELECT kind, level, text FROM events" + (" WHERE kind = ?" if kind else "") + " ORDER BY id"
        return self.store.conn.execute(q, (kind,) if kind else ()).fetchall()

    def trades(self):
        return self.store.conn.execute("SELECT key, qty, exit_reason, pnl, pnl_source FROM trades ORDER BY entry_ts"
                                       ).fetchall()

    def stops(self, symbol=B):
        cs = Decimal(self.fake.amt(symbol) / self.fake.pos[symbol]) if self.fake.pos[symbol] else Decimal("0.0001")
        return [(p["triggerPrice"], float(Decimal(str(p["vol"])) * cs)) for p in self.fake.live_plans(symbol)]

    def stop_posts(self):
        return [i for i, c in enumerate(self.fake.calls) if c[1].endswith("/planorder/place")]

    def protected_after_first_stop(self, symbol=B):
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
    assert w.fake.pos[B] == 0 and not w.fake.orders
    assert w.fake.mode == 2 and w.fake.levs[(B, 1)] == [1, 40] and w.fake.levs[("ETH_USDT", 2)] == [1, 30]
    w.paper(stop=95.0)
    w.loop()
    assert w.amt() == 5 and w.fake.pos[B] == 50_000 and w.stops() == [(95.0, 5.0)]
    assert w.fake.levs[(B, 1)] == [1, 20] and w.fake.pos_open[B] == 1            # isolated, the paper's 20x
    plan = w.fake.live_plans(B)[0]
    assert plan["side"] == 4 and plan["triggerType"] == 2 and plan["trend"] == 1 and plan["orderType"] == 5
    assert w.ex.trade["status"] == "open" and w.ex.trade["stop_algo_id"] == plan["id"]
    i = w.stop_posts()[0]
    assert w.fake.calls[i + 1][1].endswith("/planorder/list/orders")              # confirmed live in the list
    early = [t[2].rsplit("/", 1)[0] if "/order/get/" in t[2] else t[2]
             for t in w.fake.unprotected_moments(B) if t[0] <= i]
    assert early == ["/api/v1/private/order/create", "/api/v1/private/order/get",      # entry, read back,
                     "/api/v1/private/position/open_positions"]                       # position: then the stop
    assert not w.protected_after_first_stop()
    assert w.trades()[0][1] == 5.0
    rows = w.store.conn.execute("SELECT method, path, params FROM requests").fetchall()
    assert any(p.endswith("/planorder/place") and '"triggerPrice": "95"' in prm for _, p, prm in rows)
    assert not any("Signature" in prm or "ms" == prm for *_, prm in rows)
    assert w.ex.prefix == "[MEXC 실거래 실행기]" and w.store.get_state("meta")["exchange"] == "mexc"


def test_lock_steps_never_leave_the_position_unprotected_and_pnl_from_fills(w):
    w.paper(stop=95.0)
    w.loop()
    wallet0 = 10_000.0                                                       # before the entry and its fee
    for price, lock in [(105.0, 101.1), (109.0, 104.9), (113.0, 109.3), (118.0, 113.6)]:
        w.fake.set_price(B, price)
        w.paper(stop=lock)
        w.loop()
        assert w.stops() == [(lock, 5.0)], (price, lock)
        assert w.ex.trade["stop"] == lock and not w.protected_after_first_stop()
    w.fake.set_price(B, 125.0)
    w.paper(stop=118.0)
    w.fake.fail("POST", "/api/v1/private/planorder/place", "503_after")       # placed, answer lost
    w.loop()
    assert w.stops() == [(118.0, 5.0)]                                       # found by its fingerprint: no duplicate
    w.paper(stop=120.0)
    w.fake.fail("POST", "/api/v1/private/planorder/place", ("ret", 600, "Param error!"))   # refused: old stop stays
    w.loop()
    assert w.stops() == [(118.0, 5.0)] and w.events("move_failed")
    w.fake.fail("POST", "/api/v1/private/planorder/cancel", "drop_before")
    w.loop()
    assert w.stops() == [(120.0, 5.0)] and not w.protected_after_first_stop()
    w.fake.add_funding(B, -1.25)                                             # funding while open
    w.src.intent = None                                                      # paper exit
    w.loop()
    assert w.fake.pos[B] == 0 and not w.fake.live_plans() and w.ex.trade is None
    key, qty, reason, pnl, source = w.trades()[0]
    assert "paper 청산" in reason and source == "fills"
    assert pnl == pytest.approx(w.fake.wallet - wallet0, abs=1e-6)          # fills + funding = the wallet change
    realized, commission, funding = w.store.conn.execute("SELECT realized, commission, funding FROM trades").fetchone()
    assert realized == pytest.approx(5 * (125.0 - 100.0)) and funding == pytest.approx(-1.25)
    assert commission == pytest.approx(0.0005 * 5 * (100.0 + 125.0))
    assert not w.protected_after_first_stop()


@pytest.mark.parametrize("past", ["refuse", "trigger"])
def test_lock_past_the_price_closes_the_position(tmp_path, past):
    fake = FakeMexc(wallet=10_000.0)
    fake.plan_past = past
    w = World(tmp_path, fake=fake)
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(B, 100.5)
    w.paper(stop=101.1)                                                      # already above the price
    w.loop()
    if past == "trigger":                                                    # MEXC executed it at once: booked next
        w.loop()
    assert w.fake.pos[B] == 0 and not w.fake.live_plans() and w.ex.trade is None
    assert len(w.trades()) == 1 and w.trades()[0][4] == "fills"
    if past == "refuse":
        assert w.events("stop_would_trigger") and "시장가" in w.trades()[0][2]
    else:
        assert w.events("stop_fired")
    w.loop(3)
    assert w.fake.pos[B] == 0 and len(w.trades()) == 1
    w.store.close()


def test_stop_hit_on_the_exchange_is_booked_from_its_fills(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(B, 94.0)
    assert w.fake.pos[B] == 0
    w.loop()
    key, qty, reason, pnl, source = w.trades()[0]
    assert "거래소 손절" in reason and source == "fills" and w.ex.risk.consecutive_losses == 1
    assert pnl == pytest.approx(5 * (94.0 - 100.0) - 0.0005 * 5 * (100.0 + 94.0))
    w.loop(2)
    assert w.fake.pos[B] == 0 and len(w.trades()) == 1


def test_partial_fill_gets_a_stop_for_what_was_filled(w):
    w.fake.partial = 0.6
    w.paper(stop=95.0)
    w.loop()
    assert w.amt() == 3 and w.stops() == [(95.0, 3.0)] and w.events("partial_fill")


def test_async_order_reads(w):
    w.fake.market_lag = 2
    w.paper(stop=95.0)
    w.loop()
    assert w.amt() == 5 and w.stops() == [(95.0, 5.0)]
    w.fake.set_price(B, 106.0)
    w.paper(stop=101.1)
    w.loop(2)
    assert w.stops() == [(101.1, 5.0)] and not w.events("no_stop") and not w.protected_after_first_stop()
    w.src.intent = None
    w.loop()
    assert w.fake.pos[B] == 0 and w.ex.trade is None and w.trades()[0][4] == "fills"


# ------------------------------------------------------------------ reconcile
def test_unknown_positions_are_closed_and_alerted(w):
    w.fake.pos["ETH_USDT"], w.fake.entry["ETH_USDT"] = Decimal("200"), 50.0
    w.fake.pos["SOL_USDT"], w.fake.entry["SOL_USDT"], w.fake.pos_open["SOL_USDT"] = Decimal("-30"), 10.0, 2   # cross
    w.loop()
    assert w.fake.pos["ETH_USDT"] == 0 and w.fake.pos["SOL_USDT"] == 0
    assert sum(lvl == CRITICAL and "모르는 포지션" in txt for lvl, txt in w.note.messages) == 2


def test_missing_stop_is_put_back_or_the_position_closed(w):
    w.paper(stop=95.0)
    w.loop()
    for p in w.fake.live_plans(B):
        p["state"] = 2                                                       # cancelled in the app
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.events("no_stop")
    for p in w.fake.live_plans(B):
        p["state"] = 2
    w.fake.last[B] = 94.0                                                    # and the price is already past it
    w.loop()
    assert w.fake.pos[B] == 0 and w.ex.trade is None and not w.fake.live_plans()


def test_stop_size_follows_the_position_both_ways(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.pos[B] = Decimal("70000")                                         # grew outside the bot (7 BTC)
    w.loop()
    assert w.stops() == [(95.0, 7.0)] and w.ex.trade["qty"] == 7.0 and w.events("size_mismatch")
    w.fake.pos[B] = Decimal("40000")                                         # shrank: a larger stop is replaced
    n = len(w.fake.calls)
    w.loop()
    assert w.stops() == [(95.0, 4.0)] and w.events("stop_size")
    assert not [t for t in w.fake.unprotected_moments(B) if t[0] >= n]       # new stop first, then the old one goes
    w.client.stop_close(BTC, "SELL", 90.0, qty=4.0)                          # a stray extra stop
    w.loop()
    assert w.stops() == [(95.0, 4.0)] and w.events("extra_stops")


def test_stray_stops_without_a_position_are_cancelled(w):
    w.fake.pos[B], w.fake.entry[B] = Decimal("10000"), 100.0
    w.client.stop_close(BTC, "SELL", 90.0, qty=1.0)
    w.fake.pos[B] = Decimal("0")
    w.loop()
    assert not w.fake.live_plans() and w.events("stray_orders")


def test_a_stop_is_placed_again_before_it_expires(w):
    w.paper(stop=95.0)
    w.loop()
    first = w.fake.live_plans(B)[0]["id"]
    w.clock.t += 6 * 86_400_000 - 60_000                                     # not yet
    w.loop()
    assert [p["id"] for p in w.fake.live_plans(B)] == [first]
    w.clock.t += 120_000                                                     # 6 days old: placed again, same level
    n = len(w.fake.calls)
    w.loop()
    live = w.fake.live_plans(B)
    assert len(live) == 1 and live[0]["id"] != first and w.stops() == [(95.0, 5.0)] and w.events("stop_refresh")
    assert not [t for t in w.fake.unprotected_moments(B) if t[0] >= n]       # new first, then the old one goes
    assert w.fake.plans[first]["state"] == 2 and not w.events("no_stop")


# ------------------------------------------------------------------ restarts and unknown outcomes
def test_restart_after_crash_between_fill_and_stop(w):
    w.paper(stop=95.0)

    def die(*a, **k):
        raise KeyboardInterrupt("process killed")
    w.ex._protect = die
    with pytest.raises(KeyboardInterrupt):
        w.loop()
    assert w.amt() == 5 and not w.fake.live_plans()
    w.restart()
    assert w.ex.trade["status"] == "open"
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.events("no_stop")


def test_entry_with_an_unknown_outcome_is_never_sent_twice(w):
    w.paper(stop=95.0)
    w.fake.fail("POST", "/api/v1/private/order/create", "drop_before", times=8)
    w.fake.fail("GET", "/api/v1/private/order/external/", "drop_before", times=8)
    w.loop()
    assert w.ex.trade["status"] == "entering" and w.events("entry_unknown")
    w.fake.failures.clear()
    w.restart()
    w.clock.t += 61_000
    w.loop()
    assert w.ex.trade is None and w.fake.pos[B] == 0 and w.events("recover")
    w.paper(stop=96.0, entry_time=w.clock.t - 30_000)
    w.fake.fail("POST", "/api/v1/private/order/create", "drop_after")       # executed, answer lost
    w.loop()
    entries = [c for c in w.fake.calls if c[1].endswith("/order/create") and c[2]["side"] in (1, 3)]
    assert len(entries) == 1 and w.amt() == 5 and w.stops() == [(96.0, 5.0)]
    w.fake.fail("POST", "/api/v1/private/planorder/place", ("ret_after", 9999, "System busy"))  # after the stop
    w.paper(stop=97.0)
    w.loop()
    assert w.stops() == [(97.0, 5.0)]                                        # looked up, not doubled


def test_restart_keeps_open_trade_and_lock(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(B, 106.0)
    w.paper(stop=101.1)
    w.loop()
    w.restart()
    assert w.ex.trade["stop"] == 101.1
    w.loop()
    assert w.stops() == [(101.1, 5.0)] and w.amt() == 5 and not w.protected_after_first_stop()


# ------------------------------------------------------------------ position mode, risk
def test_hedge_mode_is_switched_or_refused(tmp_path):
    fake = FakeMexc(wallet=10_000.0)
    fake.mode = 1
    w = World(tmp_path, fake=fake)                                           # nothing open: switched at the start
    assert fake.mode == 2
    w.store.close()
    (tmp_path / "b").mkdir()
    fake2 = FakeMexc(wallet=10_000.0)
    fake2.mode = 1
    fake2.add_resting("ETH_USDT", 1, 5, 40.0)
    w2 = World.__new__(World)
    with pytest.raises(Refused):                                             # hedge with an order open: no start
        World.__init__(w2, tmp_path / "b", fake=fake2)
    assert w2.events("mode_refused") and any(lvl == CRITICAL and "양방향" in t for lvl, t in w2.note.messages)
    w2.store.close()
    (tmp_path / "c").mkdir()
    w3 = World(tmp_path / "c")
    w3.fake.mode = 1                                                         # switched in the app while running
    w3.paper(stop=95.0, entry_time=w3.clock.t)
    w3.loop()
    assert w3.fake.pos[B] == 0 and w3.events("leverage_refused")             # never an entry
    w3.store.close()


def test_kill_switch_flattens_and_halts(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()
    (tmp_path / "STOP").write_text("")
    w.loop()
    assert w.fake.pos[B] == 0 and not w.fake.live_plans() and w.ex.risk.halted


def test_daily_loss_halt(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=60.0)
    w.paper(stop=90.0)
    w.loop()
    assert w.amt() == 5
    w.fake.set_price(B, 95.5)
    w.fake.add_funding(B, -40.0)
    w.loop()
    assert w.fake.pos[B] == 0 and w.ex.risk.halted and "하루 한도" in w.ex.risk.halt_reason
    w.store.close()


def test_deposits_and_withdrawals_are_not_profit(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=60.0)
    w.loop()
    w.fake.add_transfer(-80.0)                                               # a withdrawal is not a loss
    w.clock.t += 61_000
    w.loop()
    assert not w.ex.risk.halted and w.events("transfer")
    assert w.ex.risk.transfers == pytest.approx(-80.0)


def test_signal_mode_falls_back_to_the_paper_position(tmp_path):
    w = World(tmp_path, cfg_kw={"entry_source": "signal"})
    assert w.ex.signals is None and w.events("signal_mode_off")
    w.store.close()


# ------------------------------------------------------------------ refusals
def test_refuses_the_wrong_mode_client_host_or_config(tmp_path):
    w = World(tmp_path)
    w.store.close()
    store = ExecStore(str(tmp_path / "x.db"))
    try:
        for c in (BybitMainnetClient("mk", "ms", send=w.fake),               # a Bybit client with exchange mexc
                  MX.MexcKeyCheckClient("mk", "ms", send=w.fake)):           # not the order client class
            with pytest.raises(Refused):
                Executor(w.cfg, c, w.src, store, env=LIVE_ENV, keycheck=w.keycheck)
        c = MX.MexcClient("mk", "ms", send=w.fake)
        c.base = "https://api.mexc.com.evil.io"                              # tampered after construction
        with pytest.raises(Refused):
            Executor(w.cfg, c, w.src, store, env=LIVE_ENV, keycheck=w.keycheck)
        testnet = ExecConfig(**{**w.cfg.__dict__, "mode": "testnet"})
        assert any("테스트넷" in p for p in testnet.problems())
        with pytest.raises(Refused):                                          # no MEXC testnet
            Executor(testnet, MX.MexcClient("mk", "ms", send=w.fake), w.src, store, env=LIVE_ENV,
                     keycheck=w.keycheck)
        bybit_cfg = ExecConfig(**{**w.cfg.__dict__, "exchange": "bybit"})
        with pytest.raises(Refused):                                          # a MEXC client with exchange bybit
            Executor(bybit_cfg, MX.MexcClient("mk", "ms", send=w.fake), w.src, store, env=LIVE_ENV)
        with pytest.raises(Refused):                                          # no key check client
            Executor(w.cfg, MX.MexcClient("mk", "ms", send=w.fake), w.src, store, env=LIVE_ENV)
        with pytest.raises(Refused):                                          # the key is a Bybit key
            Executor(w.cfg, MX.MexcClient("mk", "ms", send=w.fake), w.src, store,
                     env={**LIVE_ENV, "BYBIT_LIVE_API_KEY": "mk"}, keycheck=w.keycheck)
        for bad in ({"mexc_host": "api.bybit.com"}, {"exchange": "bybit", "mexc_host": "api.mexc.com"},
                    {"mexc_market_type": 1}):
            probs = ExecConfig(**{**w.cfg.__dict__, **bad}).problems()
            assert any("mexc" in p for p in probs), bad
        assert ExecConfig(**{**w.cfg.__dict__, "mexc_host": "contract.mexc.com", "mexc_market_type": 6}
                          ).problems() == []
    finally:
        store.close()


def test_cli_check_config_and_keys(tmp_path, monkeypatch, capsys):
    conf = tmp_path / "c.json"
    risk = {**R.RiskConfig().__dict__, **risk_cfg(tmp_path).__dict__, "allowed_symbols": [BTC]}
    conf.write_text(json.dumps({"account": "A@15m", "paper_db": "p", "db": str(tmp_path / "e.db"), "qty_scale": 1,
                                "exchange": "mexc", "mode": "mainnet", "budget_usd": 100, "risk": risk}))
    assert main(["check-config", "--config", str(conf)]) == 0
    for k in ("MEXC_LIVE_KEY", "MEXC_LIVE_SECRET", "BINANCE_API_KEY", FLAG):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(FLAG, FLAG_VALUE)
    monkeypatch.setenv("MEXC_LIVE_KEY", "same")
    monkeypatch.setenv("MEXC_LIVE_SECRET", "x")
    monkeypatch.setenv("BINANCE_API_KEY", "same")
    assert main(["run", "--config", str(conf), "--max-loops", "0"]) == 2     # refused before any request
    conf.write_text(json.dumps({"account": "A@15m", "paper_db": "p", "db": str(tmp_path / "e.db"), "qty_scale": 1,
                                "exchange": "mexc", "mode": "testnet", "risk": risk}))
    assert main(["check-config", "--config", str(conf)]) == 1
    assert "테스트넷" in capsys.readouterr().out


# ------------------------------------------------------------------ mainnet gates
def test_mainnet_gates_and_a_full_cycle(tmp_path):
    w = World(tmp_path)
    assert w.events("mainnet_gates") and w.ex.prefix == "[MEXC 실거래 실행기]"
    warn = w.events("key_permission")
    assert warn and warn[0][1] == WARN and MX.KEY_CHECKED in warn[0][2]       # what the API could not show, said
    w.paper(stop=95.0, qty=2.0)
    w.loop()
    assert w.amt() == 2 and w.stops() == [(95.0, 2.0)]
    w.src.intent = None
    w.loop()
    assert w.fake.pos[B] == 0 and w.trades()[0][4] == "fills"
    w.store.close()


def test_mainnet_refuses_without_the_owners_statement(tmp_path):
    env = {k: v for k, v in LIVE_ENV.items() if k != MX.KEY_CHECKED}
    w = World.__new__(World)
    with pytest.raises(Refused) as e:
        World.__init__(w, tmp_path, env=env)
    assert "출금" in str(e.value) and MX.KEY_CHECKED in str(e.value)
    assert not w.fake.orders
    w.store.close()


def test_mainnet_balance_bonus_and_asset_guards_and_preflight(tmp_path):
    for i, change in enumerate(({"wallet": 13_000.0}, {"bonus": 5.0}, {"other": {"MX": 2.0}})):
        fake = FakeMexc(wallet=change.get("wallet", 10_000.0))
        fake.bonus, fake.other = change.get("bonus", 0.0), change.get("other", {})
        (tmp_path / str(i)).mkdir()
        w = World.__new__(World)
        with pytest.raises(Refused) as e:
            World.__init__(w, tmp_path / str(i), fake=fake)
        assert ("1.2배" in str(e.value)) if i == 0 else ("USDT 말고" in str(e.value)), (change, str(e.value))
        w.store.close()
    (tmp_path / "ok").mkdir()
    w = World(tmp_path / "ok", cfg_kw={"mexc_host": "contract.mexc.com"})
    lines = []
    w.client.offset_ms = 0
    preflight(w.cfg, w.client, w.keycheck, out=lines.append)
    assert any("contract.mexc.com" in x for x in lines) and any("출금 꺼짐" in x for x in lines)
    assert any(x.startswith("[OK]") and "단방향" in x for x in lines)
    assert any(x.startswith("[OK]") and BTC in x and "1계약 0.0001" in x for x in lines)
    assert any(x.startswith("[주의]") and MX.KEY_CHECKED in x for x in lines)
    assert [x for x in lines if x.startswith("[FAIL]")] == ["[FAIL] paper3.db: unable to open database file"]
    w.store.close()


def test_mainnet_needs_the_flag_and_its_own_keys(tmp_path):
    for i, env in enumerate(({**LIVE_ENV, FLAG: ""}, {**LIVE_ENV, "BYBIT_LIVE_API_SECRET": "ms"},
                             {**LIVE_ENV, "LIVE_API_KEY": "mk"}, {**LIVE_ENV, "BINANCE_API_SECRET": "ms"})):
        (tmp_path / str(i)).mkdir()
        w = World.__new__(World)
        with pytest.raises(Refused):
            World.__init__(w, tmp_path / str(i), env=env)
        w.store.close()


# ------------------------------------------------------------------ the combined bot account, from its database
def test_follows_the_combined_account_from_its_database_at_40x(tmp_path):
    """COMBO@mix from a paper database (the research16.db layout) -> the unchanged executor -> MEXC: BTC at 40x
    isolated, the stop resting on MEXC, the lock moving it, the exit booked from fills."""
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
    fake = FakeMexc(wallet=100.0)
    fake.clock = clock
    cfg = ExecConfig(account="COMBO@mix", paper_db=db, db=str(tmp_path / "exec-mexc.db"), qty_scale=0.1,
                     risk=risk_cfg(tmp_path, max_leverage=40, max_notional_usd=10_000.0, max_loss_frac=0.35,
                                   daily_max_loss_usd=40.0, max_drawdown_pct=0.5),
                     exchange="mexc", mode="mainnet", budget_usd=100.0, sweep_every=1,
                     paper_env_file=str(tmp_path / "live.env"))
    store = ExecStore(cfg.db)
    kw = dict(send=fake, clock_ms=clock, sleep=lambda x: None)
    ex = Executor(cfg, MX.MexcClient("mk", "ms", **kw), Paper3Source(db, cfg.account), store, ListNotifier(),
                  now_ms=clock, sleep=lambda x: None, env=LIVE_ENV,
                  keycheck=MX.MexcKeyCheckClient("mk", "ms", attested=True, **kw))
    ex.start()
    clock.t += 3_000
    ex.loop_once()
    assert fake.amt(B) == Decimal("0.4") and fake.pos[B] == 4000 and fake.levs[(B, 1)] == [1, 40]
    assert [(p["triggerPrice"], p["vol"]) for p in fake.live_plans(B)] == [(97.5, 4000)]
    fake.set_price(B, 104.0)
    put({**pos, "stop_price": 101.0})
    clock.t += 3_000
    ex.loop_once()
    assert [p["triggerPrice"] for p in fake.live_plans(B)] == [101.0]
    put(None)
    clock.t += 3_000
    ex.loop_once()
    assert fake.pos[B] == 0 and not fake.live_plans()
    pnl, source = store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
    assert source == "fills" and pnl == pytest.approx(fake.wallet - 100.0)
    store.close()
    s.close()
