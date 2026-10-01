"""Mainnet gates, fast (signal) entries, P&L from fills, cost ratio and stage-check. Fake exchange only:
every test here runs with sockets blocked."""

import json
import os
import socket
import time

import pytest

from fakefutures import FakeFutures
from paperbot import livepnl as P
from paperbot import risk as R
from paperbot.executor import (ExecConfig, ExecStore, Executor, Paper3Source, Refused, main, preflight,
                               stage_review, stage_text)
from paperbot.mainnet import FLAG, FLAG_VALUE, KeyCheckClient, MainnetClient, trading_keys
from paperbot.notify import CRITICAL, INFO, ListNotifier
from paperbot.store3 import Store3
from paperbot.testnet import TestnetClient, TransientError

T0 = 1_800_000_000_000
BTC = "BTCUSDT"
DAY = 86_400_000
LIVE_ENV = {FLAG: FLAG_VALUE, "LIVE_API_KEY": "lk", "LIVE_API_SECRET": "ls", "BINANCE_API_KEY": "paperkey",
            "BINANCE_API_SECRET": "papersecret", "TESTNET_API_KEY": "tk", "TESTNET_API_SECRET": "ts"}


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


def risk_cfg(tmp_path, **kw):
    d = dict(daily_max_loss_usd=100.0, max_drawdown_pct=0.4, max_consecutive_losses=4, max_leverage=20,
             max_notional_usd=1_000.0, allowed_symbols=(BTC, "ETHUSDT"), kill_file=str(tmp_path / "STOP"))
    d.update(kw)
    return R.RiskConfig(**d)


def cfg_for(tmp_path, mode="mainnet", **kw):
    d = dict(account="S1@15m", paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / f"exec-{mode}.db"),
             qty_scale=1.0, risk=risk_cfg(tmp_path), mode=mode, budget_usd=500.0 if mode == "mainnet" else None,
             retries=3, sweep_every=1, paper_env_file=str(tmp_path / "live.env"))
    d.update(kw)
    return ExecConfig(**d)


class Paper:
    """Stands in for the paper runner: writes paper3.db the way live3 does (signal_log + accounts state)."""

    def __init__(self, path, account="S1@15m"):
        self.s = Store3(path)
        self.account = account
        self.engine = {"wallet": 5000.0, "peak_equity": 5000.0, "max_drawdown": 0.0, "halted": False,
                       "halt_reason": "", "bust": False, "position": None, "pending": []}
        self.save(T0 - 120_000)

    def save(self, last_ts):
        self.s.put_state("accounts", last_ts, {"last_ts": last_ts, "engines": {
            self.account: self.engine, "OTHER@15m": {"wallet": 1.0, "position": None, "pending": []}}})
        self.s.commit()

    def submit(self, boundary, ready, ref=100.0, atr=1.0, symbol=BTC, side=1, score=0.0, strategy="S1"):
        """live3._signals at ``boundary``: the signal row and the engine's pending signal, one commit."""
        self.s.log_signals([{"bar_close": boundary, "timeframe": "15m", "strategy": strategy, "symbol": symbol,
                             "side": side, "atr": atr, "ref_price": ref, "ref_time": ready,
                             "delay_ms": ready - boundary, "status": "SUBMITTED", "data": {}}])
        if strategy == self.account.split("@")[0]:
            self.engine["pending"].append({
                "ts": boundary - 1, "symbol": symbol, "timeframe": "15m", "strategy_id": strategy, "side": side,
                "stop_price": 0.0, "tier": "best", "atr": atr, "score": score,
                "meta": {"stop_dist": 2 * atr, "ref_price": ref, "ref_time": ready, "account": self.account}})
        self.save(boundary - 60_000)

    def enter(self, boundary, qty, leverage, ref=100.0, atr=1.0, side=1, symbol=BTC):
        """The next 1m step: the account fills at ref price + slippage, stop 2 ATR from the ref price."""
        self.engine["pending"] = []
        self.engine["position"] = {"symbol": symbol, "side": side, "qty": qty, "leverage": leverage,
                                   "stop_price": ref - side * 2 * atr, "entry_price": ref * (1 + side * 0.0002),
                                   "entry_time": boundary, "signal": {}}
        self.save(boundary)

    def flat(self, last_ts):
        self.engine["pending"], self.engine["position"] = [], None
        self.save(last_ts)


class Live:
    """An executor on the fake exchange (mainnet host by default), with timed requests."""

    def __init__(self, tmp_path, mode="mainnet", fake=None, env=None, sleep=None, **kw):
        self.tmp, self.clock = tmp_path, Clock()
        host = "fapi.binance.com" if mode == "mainnet" else "testnet.binancefuture.com"
        self.fake = fake or FakeFutures(wallet=520.0, host=host, api_key="lk" if mode == "mainnet" else "k")
        self.fake.clock = self.clock
        self.times = []                                       # (clock, method, path)
        self.cfg = cfg_for(tmp_path, mode, **kw)
        self.note = ListNotifier()
        self.env = dict(LIVE_ENV if env is None else env)
        self.sleep = sleep or (lambda s: setattr(self.clock, "t", self.clock.t + int(s * 1000)))
        self.store = ExecStore(self.cfg.db)
        key = ("lk", "ls") if mode == "mainnet" else ("k", "s")
        cls = MainnetClient if mode == "mainnet" else TestnetClient
        self.client = cls(*key, send=self.send, clock_ms=self.clock)
        self.keycheck = KeyCheckClient(*key, send=self.send, clock_ms=self.clock) if mode == "mainnet" else None
        self.source = Paper3Source(self.cfg.paper_db, self.cfg.account)

    def send(self, method, url, headers, body):
        self.times.append((self.clock.t, method, url.split("?")[0].split(".com")[1]))
        return self.fake(method, url, headers, body)

    def executor(self):
        return Executor(self.cfg, self.client, self.source, self.store, self.note, now_ms=self.clock,
                        sleep=self.sleep, keycheck=self.keycheck, env=self.env)

    def events(self, kind):
        return self.store.conn.execute("SELECT level, text FROM events WHERE kind = ? ORDER BY id", (kind,)).fetchall()

    def close(self):
        self.store.close()


# ------------------------------------------------------------------ gates: offline
def test_mainnet_refuses_without_every_offline_gate(tmp_path):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    try:
        def refused(env=None, cfg=None, client=None, keycheck="same"):
            with pytest.raises(Refused) as e:
                Executor(cfg or lv.cfg, client or lv.client, lv.source, lv.store, env=LIVE_ENV if env is None else env,
                         keycheck=lv.keycheck if keycheck == "same" else keycheck)
            return str(e.value)
        # the switch: flag missing or not exactly I_UNDERSTAND
        assert FLAG in refused({k: v for k, v in LIVE_ENV.items() if k != FLAG})
        assert FLAG in refused({**LIVE_ENV, FLAG: "yes"})
        # keys: only LIVE_*; never the paper runner's read-only key, never a testnet key
        assert "LIVE_API_KEY" in refused({**LIVE_ENV, "LIVE_API_KEY": ""})
        assert "읽기 전용" in refused({**LIVE_ENV, "BINANCE_API_KEY": "lk"})
        assert "읽기 전용" in refused({**LIVE_ENV, "BINANCE_API_SECRET": "ls"})
        assert "테스트넷" in refused({**LIVE_ENV, "TESTNET_API_KEY": "lk"})
        (tmp_path / "live.env").write_text("# paper runner\nBINANCE_API_KEY=lk\nBINANCE_API_SECRET=x\n")
        assert "읽기 전용" in refused({k: v for k, v in LIVE_ENV.items() if not k.startswith("BINANCE")})
        os.remove(tmp_path / "live.env")
        other = MainnetClient("other", "ls", send=lv.send)
        assert "LIVE_API_KEY" in refused(client=other)            # the client must carry the LIVE_* key
        assert "키 권한" in refused(keycheck=None)                 # no start without the permission check
        # host allowlist: fapi.binance.com only, and the mainnet client class only
        with pytest.raises(ValueError):
            MainnetClient("lk", "ls", base="https://testnet.binancefuture.com")
        with pytest.raises(ValueError):
            MainnetClient("lk", "ls", base="https://fapi.binance.com.evil.io")
        with pytest.raises(ValueError):
            KeyCheckClient("lk", "ls", base="https://fapi.binance.com")
        tampered = MainnetClient("lk", "ls", send=lv.send)
        tampered.base = "https://demo-fapi.binance.com"
        assert "fapi.binance.com" in refused(client=tampered)
        assert "fapi.binance.com" in refused(client=TestnetClient("lk", "ls", send=lv.send))
        assert "testnet" in refused(cfg=cfg_for(tmp_path, "testnet"), client=MainnetClient("lk", "ls"))
        # the risk config complete, and the budget set
        assert "하루 최대 손실" in refused(cfg=cfg_for(tmp_path, risk=R.RiskConfig()))
        assert "하루 최대 손실" in refused(cfg=cfg_for(tmp_path, risk=risk_cfg(tmp_path, daily_max_loss_usd=None)))
        assert "budget_usd" in refused(cfg=cfg_for(tmp_path, budget_usd=None))
        assert not lv.fake.calls                                   # nothing reached the exchange
    finally:
        lv.close()


def test_trading_keys_per_mode():
    assert trading_keys("mainnet", LIVE_ENV) == ("lk", "ls")
    assert trading_keys("testnet", LIVE_ENV) == ("tk", "ts")
    with pytest.raises(Refused):                                  # testnet key = paper key
        trading_keys("testnet", {**LIVE_ENV, "TESTNET_API_KEY": "paperkey"})
    with pytest.raises(Refused):                                  # testnet key = live key
        trading_keys("testnet", {**LIVE_ENV, "TESTNET_API_SECRET": "ls"})
    with pytest.raises(Refused):                                  # the paper key from its env file only
        trading_keys("mainnet", {FLAG: FLAG_VALUE, "LIVE_API_KEY": "lk", "LIVE_API_SECRET": "ls"},
                     {"BINANCE_API_KEY": "lk"})
    with pytest.raises(Refused):
        trading_keys("demo", LIVE_ENV)


# ------------------------------------------------------------------ gates: online (start)
@pytest.mark.parametrize("change,needle", [
    ({"enableWithdrawals": True}, "출금"),
    ({"enableWithdrawals": None}, "출금"),
    ({"enableFutures": False}, "선물 거래 권한"),
    ({"ipRestrict": False}, "IP 제한"),
])
def test_mainnet_refuses_a_key_with_the_wrong_permissions(tmp_path, change, needle):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    lv.fake.restrictions.update(change)
    try:
        ex = lv.executor()
        with pytest.raises(Refused) as e:
            ex.start()
        assert needle in str(e.value)
        assert not [c for c in lv.fake.calls if c[0] != "GET"]     # nothing was changed or ordered
        assert any(lvl == CRITICAL and needle in txt for lvl, txt in lv.note.messages)
    finally:
        lv.close()


def test_mainnet_does_not_start_while_the_permission_check_cannot_be_reached(tmp_path):
    """Unreachable after the retries: no order, a CRITICAL alert, and an error that is NOT a refusal (exit 1, so
    systemd tries again in 30 s; a refusal, exit 2, would leave an open position unattended until a person acts)."""
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    lv.fake.fail("GET", "/sapi/v1/account/apiRestrictions", "drop_before", times=5)
    try:
        with pytest.raises(TransientError):
            lv.executor().start()
        assert not [c for c in lv.fake.calls if c[0] != "GET"]
        assert any(lvl == CRITICAL and "키 권한 확인이 안 됩니다" in txt for lvl, txt in lv.note.messages)
    finally:
        lv.close()


def test_mainnet_balance_guard_and_a_full_cycle_on_the_same_code_path(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, fake=FakeFutures(wallet=600.01, host="fapi.binance.com", api_key="lk"))
    try:
        with pytest.raises(Refused) as e:                         # budget 500 x 1.2 = 600
            lv.executor().start()
        assert "하위 계정" in str(e.value)
    finally:
        lv.close()
    (tmp_path / "x").mkdir()
    lv = Live(tmp_path / "x", fake=FakeFutures(wallet=600.0, host="fapi.binance.com", api_key="lk"),
              paper_db=str(tmp_path / "paper3.db"))
    lv.fake.restrictions["enableInternalTransfer"] = True
    try:
        with pytest.raises(Refused) as e:                         # a permission the executor never needs
            lv.executor().start()
        assert "계정 간 이체" in str(e.value)
        lv.fake.restrictions["enableInternalTransfer"] = False
        ex = lv.executor()
        ex.start()
        assert lv.events("mainnet_gates") and not lv.events("key_permission")
        # the paper account enters: the same mirroring as on the testnet, on fapi.binance.com
        paper.enter(T0, qty=5.0, leverage=20)
        lv.clock.t = T0 + 70_000
        ex.loop_once()
        assert lv.fake.pos[BTC] == 5.0 and [(float(o["triggerPrice"]), o["quantity"]) for o in
                                            lv.fake.live_stops(BTC)] == [(98.0, "5.0")]
        assert {h for h in (lv.client.host, lv.keycheck.host)} == {"fapi.binance.com", "api.binance.com"}
        st = lv.store.get_state("meta")
        assert st["mode"] == "mainnet" and st["account"] == "S1@15m"
    finally:
        lv.close()


def test_one_database_per_mode_and_account(tmp_path):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, mode="testnet", db=str(tmp_path / "e.db"))
    lv.executor()
    lv.close()
    lv = Live(tmp_path, db=str(tmp_path / "e.db"))
    try:
        with pytest.raises(Refused) as e:
            lv.executor()
        assert "testnet 기록" in str(e.value)
    finally:
        lv.close()
    lv = Live(tmp_path, mode="testnet", db=str(tmp_path / "e.db"), account="OTHER@15m")
    try:
        with pytest.raises(Refused) as e:
            lv.executor()
        assert "새 db" in str(e.value)
    finally:
        lv.close()


def test_cli_refuses_before_any_request(tmp_path, monkeypatch, capsys):
    conf = tmp_path / "executor.json"
    rk = {**risk_cfg(tmp_path).__dict__, "allowed_symbols": [BTC]}
    base = {"mode": "mainnet", "account": "S1@15m", "paper_db": str(tmp_path / "p.db"), "db": str(tmp_path / "e.db"),
            "qty_scale": 0.1, "budget_usd": 500, "paper_env_file": str(tmp_path / "live.env"), "risk": rk}
    conf.write_text(json.dumps(base))
    for k in list(os.environ):
        if k.endswith(("API_KEY", "API_SECRET")) or k == FLAG:
            monkeypatch.delenv(k)
    assert main(["run", "--config", str(conf), "--max-loops", "0"]) == 2
    assert FLAG in capsys.readouterr().err
    monkeypatch.setenv(FLAG, FLAG_VALUE)
    monkeypatch.setenv("LIVE_API_KEY", "same")
    monkeypatch.setenv("LIVE_API_SECRET", "s2")
    (tmp_path / "live.env").write_text("BINANCE_API_KEY=same\n")
    assert main(["preflight", "--config", str(conf)]) == 2
    assert "읽기 전용" in capsys.readouterr().err
    conf.write_text(json.dumps({**base, "budget_usd": None}))
    assert main(["check-config", "--config", str(conf)]) == 1
    assert "budget_usd" in capsys.readouterr().out


def test_preflight_lists_every_gate(tmp_path):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, entry_source="signal")
    lv.fake.server_time = lv.clock.t + 200
    out = []
    try:
        assert preflight(lv.cfg, lv.client, lv.keycheck, out.append)
        assert all(x.startswith("[OK]") for x in out) and len(out) == 7, out
        lv.fake.restrictions["enableWithdrawals"] = True
        out.clear()
        assert not preflight(lv.cfg, lv.client, lv.keycheck, out.append)
        assert any(x.startswith("[FAIL]") and "출금" in x for x in out)
        assert not [c for c in lv.fake.calls if c[0] != "GET"]
    finally:
        lv.close()


# ------------------------------------------------------------------ fast entries (signal mode)
def scheduled_sleep(clock, plan):
    """sleep() for run(): advances the clock and runs the paper runner's writes when their time comes."""
    def sleep(s):
        clock.t += int(round(s * 1000))
        for when in sorted(plan):
            if when <= clock.t:
                plan.pop(when)()
    return sleep


def test_signal_mode_enters_within_the_poll_interval_and_follows_the_paper_position(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    B = T0 + 4_000 - 800                                       # a 15m bar closed; signal ready 0.8 s later
    ready = B + 800
    plan = {}
    lv = Live(tmp_path, entry_source="signal")
    lv.sleep = scheduled_sleep(lv.clock, plan)
    try:
        ex = lv.executor()
        plan[ready] = lambda: paper.submit(B, ready)
        ex.run(max_loops=3)
        orders = [t for t, m, p in lv.times if (m, p) == ("POST", "/fapi/v1/order")]
        assert len(orders) == 1 and 0 <= orders[0] - ready <= lv.cfg.direct_poll_s * 1000, (orders, ready)
        t = ex.trade
        assert t["direct"] and not t["confirmed"] and t["key"] == f"S1@15m|{BTC}|{B}"
        assert t["signal_lag_ms"] <= 1_500 and t["entry_ref"] == 100.0 and t["signal_ref"] == 100.0
        # paper stop = ref - 2 ATR = 98, paper fill 100.02: the exchange stop keeps that distance from the fill
        assert [float(o["triggerPrice"]) for o in lv.fake.live_stops(BTC)] == [98.0]
        assert "빠른 진입" in lv.events("entry")[0][1]
        stop_posts = len([c for c in lv.fake.calls if c[:2] == ("POST", "/fapi/v1/algoOrder")])
        # the paper runner fills the account at the next 1m step (60 s later) and saves it
        plan[B + 62_000] = lambda: paper.enter(B, qty=t["planned_qty"], leverage=t["paper_leverage"])
        ex.run(max_loops=25)
        assert ex.trade["confirmed"] and lv.events("direct_confirmed")[0][0] == INFO
        assert len([c for c in lv.fake.calls if c[:2] == ("POST", "/fapi/v1/algoOrder")]) == stop_posts  # no move
        assert len([c for c in lv.fake.calls if c[:2] == ("POST", "/fapi/v1/order")]) == 1          # no re-entry
        # from here it is the normal mirror: a lock step moves the stop, the paper exit closes
        lv.fake.set_price(BTC, 104.0)
        paper.engine["position"]["stop_price"] = 101.0
        paper.save(B + 120_000)
        ex.loop_once()
        assert [float(o["triggerPrice"]) for o in lv.fake.live_stops(BTC)] == [101.0]    # 100 x 101/100.02, up
        paper.flat(B + 180_000)
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0 and ex.trade is None
    finally:
        lv.close()


def test_signal_mode_closes_when_the_paper_account_does_not_enter(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, entry_source="signal")
    try:
        ex = lv.executor()
        ex.start()
        B = T0
        lv.clock.t = B + 900
        paper.submit(B, B + 700)
        ex.loop_once()
        assert lv.fake.pos[BTC] > 0
        lv.clock.t += 30_000
        ex.loop_once()                                         # paper not stepped yet: wait, stop protects
        assert lv.fake.pos[BTC] > 0 and ex.trade["status"] == "open"
        paper.flat(B)                                          # the step at B ran: no position (rejected)
        lv.clock.t += 40_000
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0 and ex.trade is None and not lv.fake.live_stops()
        reason = lv.store.conn.execute("SELECT exit_reason FROM trades").fetchone()[0]
        assert "진입하지 않았습니다" in reason
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0                           # not entered again
    finally:
        lv.close()


def test_signal_mode_leaves_unclear_signals_to_the_paper_path(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, entry_source="signal")
    try:
        ex = lv.executor()
        ex.start()
        # another strategy's signal: ignored
        lv.clock.t = T0 + 1_000
        paper.submit(T0, T0 + 500, strategy="S2")
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0 and not lv.events("entry_check")
        # seen too late (after a restart, say): left to the paper path
        lv.clock.t = T0 + 900_000 + 30_000
        paper.submit(T0 + 900_000, T0 + 900_000 + 500)
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0 and lv.events("direct_late")
        # the paper account already holds a position: the paper engine will skip the signal
        paper.engine["pending"] = []
        paper.engine["position"] = {"symbol": "ETHUSDT", "side": 1, "qty": 1.0, "leverage": 20, "stop_price": 40.0,
                                    "entry_price": 50.0, "entry_time": T0 - 600_000, "signal": {}}
        paper.save(T0 + 1_800_000 - 60_000)
        lv.clock.t = T0 + 1_800_000 + 1_000
        paper.submit(T0 + 1_800_000, T0 + 1_800_000 + 500)
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0 and lv.events("direct_skip")
    finally:
        lv.close()


# ------------------------------------------------------------------ P&L and cost from fills
def test_pnl_from_fills_with_commission_and_funding(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    fake = FakeFutures(wallet=520.0, host="fapi.binance.com", api_key="lk", fee=0.0005)
    fake.slip = 0.001
    lv = Live(tmp_path, fake=fake)
    try:
        ex = lv.executor()
        ex.start()
        paper.enter(T0, qty=5.0, leverage=20)
        lv.clock.t = T0 + 70_000
        ex.loop_once()
        assert lv.fake.pos[BTC] == 5.0
        lv.fake.add_funding(BTC, -0.30)
        lv.fake.set_price(BTC, 106.0)
        lv.clock.t += 3_000
        paper.flat(T0 + 3_600_000)
        lv.clock.t = T0 + 3_600_000 + 30_000
        ex.loop_once()
        row = lv.store.conn.execute("SELECT pnl, pnl_source, realized, commission, funding, slippage, real_cost, "
                                    "assumed_cost, cost_ok FROM trades").fetchone()
        pnl, src, realized, comm, fund, slip, real, assumed, ok = row
        e_in, e_out = 100.0 * 1.001, 106.0 * 0.999
        assert src == "fills" and ok == 1
        assert realized == pytest.approx(5 * (e_out - e_in))
        assert comm == pytest.approx(5 * (e_in + e_out) * 0.0005)
        assert fund == pytest.approx(-0.30)
        assert pnl == pytest.approx(realized - comm + fund)
        assert slip == pytest.approx(5 * (e_in - 100.0) + 5 * (106.0 - e_out))       # vs the price seen
        assert real == pytest.approx(comm + slip)
        assert assumed == pytest.approx(5 * (e_in + e_out) * (0.0005 + 0.0002))
        assert lv.store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 2
        assert lv.store.conn.execute("SELECT income FROM funding").fetchone()[0] == pytest.approx(-0.30)
        # the wallet moved by exactly the same amount
        assert lv.fake.wallet - 520.0 == pytest.approx(pnl)
    finally:
        lv.close()


def test_stop_exit_costs_and_late_fills(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    fake = FakeFutures(wallet=520.0, host="fapi.binance.com", api_key="lk")
    fake.stop_slip = 0.002
    lv = Live(tmp_path, fake=fake)
    try:
        ex = lv.executor()
        ex.start()
        paper.enter(T0, qty=5.0, leverage=20)
        lv.clock.t = T0 + 70_000
        ex.loop_once()
        lv.fake.fail("GET", "/fapi/v1/userTrades", ("code", -1000, "An unknown error occured."), times=2)
        lv.fake.set_price(BTC, 97.0)                           # the exchange stop at 98 fires, fills 0.2 % worse
        lv.clock.t += 3_000
        ex.loop_once()
        row = lv.store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
        assert row[1] == "wallet" and row[0] < 0 and lv.events("fills_unread")       # an estimate for now
        lv.clock.t += 3_000
        ex.loop_once()                                         # read again on a later loop
        pnl, src, slip, comm = lv.store.conn.execute(
            "SELECT pnl, pnl_source, slippage, commission FROM trades").fetchone()
        # the price jumped through the stop (98 -> 97) and the fill was 0.2 % worse still: all of it counts
        # against the stop level, where the paper rules exit a stop inside a bar
        assert src == "fills" and slip == pytest.approx(5 * (98.0 - 97.0 * 0.998))
        assert pnl == pytest.approx(lv.fake.wallet - 520.0) and ex.risk.consecutive_losses == 1
    finally:
        lv.close()


def test_trade_costs_and_ratio():
    fills = [{"side": "SELL", "price": "100.0", "qty": "2", "realizedPnl": "0", "commission": "0.1",
              "commissionAsset": "USDT"},
             {"side": "BUY", "price": "95.0", "qty": "2", "realizedPnl": "10.0", "commission": "0.095",
              "commissionAsset": "USDT"}]
    c = P.trade_costs(-1, fills, [{"income": "0.5"}], entry_ref=100.1, exit_ref=94.9)      # a short
    assert c["pnl"] == pytest.approx(10.0 - 0.195 + 0.5)
    assert c["slippage"] == pytest.approx(2 * (100.1 - 100.0) + 2 * (95.0 - 94.9))
    assert c["assumed_cost"] == pytest.approx(390.0 * 0.0007) and c["ok"]
    bnb = P.trade_costs(-1, [{**f, "commissionAsset": "BNB"} for f in fills], [], 100.1, 94.9)
    assert not bnb["ok"] and "BNB" in bnb["problems"][0]
    assert not P.trade_costs(1, [], [], 1.0, 1.0)["ok"]
    r = P.cost_ratio([c, bnb, {"ok": True, "real_cost": 0.6, "assumed_cost": 0.4}])
    assert r["measured"] == 2 and r["trades"] == 3
    assert r["ratio"] == pytest.approx((c["real_cost"] + 0.6) / (c["assumed_cost"] + 0.4))
    assert P.cost_ratio([])["ratio"] is None


# ------------------------------------------------------------------ stage check
def make_record(path, mode, days, n, pnl, real, assumed, now, curve=(500, 520, 540), halts=0, emergencies=0):
    st = ExecStore(path)
    st.put_state("meta", now - days * DAY, {"mode": mode, "account": "S1@15m", "since": now - days * DAY})
    for i in range(n):
        t0 = now - days * DAY + (i + 1) * 3_600_000
        t = {"key": f"S1@15m|{BTC}|{t0}", "symbol": BTC, "side": 1, "qty": 1.0, "leverage": 20, "entry_ts": t0,
             "mode": mode}
        st.trade_open(t)
        st.trade_close(t["key"], t0 + 600_000, "paper 청산", pnl, t)
        st.trade_costs(t["key"], {"pnl": pnl, "realized": pnl + 0.1, "commission": 0.1, "funding": 0.0,
                                  "slippage": real - 0.1, "real_cost": real, "assumed_cost": assumed, "ok": True})
    for i, e in enumerate(curve):
        st.equity(now - days * DAY + i * 300_000, e, e)
    for _ in range(halts):
        st.halt_log(now - DAY, "halt", "방향이 반대인 포지션 발견", planned=False)
    st.halt_log(now - DAY, "halt", "오늘 손실이 하루 한도에 닿았습니다", planned=True)
    for _ in range(emergencies):
        st.event(now - DAY, "critical", "unknown_position", "모르는 포지션")
    st.close()


def paper_trades(path, pnls, now):
    s = Store3(path)
    for i, p in enumerate(pnls):
        s.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, "
                       "roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       ("S1@15m", BTC, now - 10 * DAY, now - (i + 1) * DAY, "LOCK", 30, p, 0.1, 5000, "{}"))
    s.commit()
    s.close()


def stage_conf(tmp_path, db):
    conf = tmp_path / "executor.json"
    conf.write_text(json.dumps({"mode": "mainnet", "budget_usd": 500, "account": "S1@15m",
                                "paper_db": str(tmp_path / "paper3.db"), "db": db, "qty_scale": 0.1,
                                "risk": {**risk_cfg(tmp_path).__dict__, "allowed_symbols": [BTC]}}))
    return str(conf)


def test_stage_check_passes_with_the_live_record(tmp_path, capsys):
    now = int(time.time() * 1000)
    paper_trades(str(tmp_path / "paper3.db"), [120.0, -40.0, 60.0], now)
    db = str(tmp_path / "e.db")
    make_record(db, "mainnet", 31, 30, 1.5, real=0.3, assumed=0.25, now=now)
    assert main(["stage-check", "--config", stage_conf(tmp_path, db)]) == 0
    out = capsys.readouterr().out
    assert "실거래 기록" in out and out.count("- 통과:") == 7
    assert "실제 비용 ÷ 가정 비용 1.20" in out and "잰 거래 30/30건" in out
    assert "paper 계좌 S1@15m 같은 기간: 끝난 거래 3건, 손익 $+140.00 (실행기 크기로 환산 $+14.00)" in out
    assert "결론: 통과 — 최대 레버리지 50배" in out


@pytest.mark.parametrize("kw,needle", [
    (dict(real=0.4, assumed=0.25), "미달: 실제 비용 ÷ 가정 비용 1.60"),
    (dict(halts=1), "미달: 계획에 없던 멈춤 1번"),
    (dict(emergencies=2), "미달: 계획에 없던 멈춤 2번"),
    (dict(days=20), "미달: 실거래 기간 20일"),
    (dict(n=12), "미달: 끝난 거래 12건"),
    (dict(pnl=-1.0), "미달: 실거래 순손익"),
    (dict(curve=(500, 600, 420)), "미달: 최대 낙폭 30%"),
])
def test_stage_check_names_what_is_missing(tmp_path, kw, needle):
    now = int(time.time() * 1000)
    paper_trades(str(tmp_path / "paper3.db"), [50.0], now)
    args = dict(mode="mainnet", days=31, n=30, pnl=1.5, real=0.3, assumed=0.25, now=now)
    args.update(kw)
    db = str(tmp_path / "e.db")
    make_record(db, **args)
    r = stage_review(db, str(tmp_path / "paper3.db"), "S1@15m", now)
    text = stage_text(r, "S1@15m")
    assert not r["review"]["ok"] and needle in text and "최대 레버리지 20배" in text, text


def test_stage_check_never_passes_on_testnet_records_or_missing_paper(tmp_path, capsys):
    now = int(time.time() * 1000)
    db = str(tmp_path / "e.db")
    make_record(db, "testnet", 31, 30, 1.5, real=0.3, assumed=0.25, now=now)
    paper_trades(str(tmp_path / "paper3.db"), [50.0], now)
    assert main(["stage-check", "--config", stage_conf(tmp_path, db)]) == 1
    out = capsys.readouterr().out
    assert "테스트넷 기록" in out and "참고용" in out
    r = stage_review(db, str(tmp_path / "nope.db"), "S1@15m", now)
    assert "paper3.db를 읽지 못했습니다" in stage_text(r, "S1@15m") and not r["review"]["ok"]


# ------------------------------------------------------------------ clock
def test_server_time_is_resynced_periodically_and_after_a_clock_refusal(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, mode="testnet", time_sync_s=600)
    try:
        ex = lv.executor()
        ex.start()
        syncs = lambda: len([1 for _, m, p in lv.times if p == "/fapi/v1/time"])  # noqa: E731
        assert syncs() == 1
        paper.save(lv.clock.t)
        ex.loop_once()
        assert syncs() == 1
        lv.clock.t += 601_000
        paper.save(lv.clock.t)
        ex.loop_once()
        assert syncs() == 2 and lv.events("time_sync")
        lv.fake.fail("GET", "/fapi/v2/positionRisk",
                     ("code", -1021, "Timestamp for this request is outside of the recvWindow."))
        ex.loop_once()
        assert syncs() == 3 and not lv.events("loop_error")
    finally:
        lv.close()


# ------------------------------------------------------------------ deploy
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def test_executor_unit_is_installed_but_never_started_by_install_sh():
    unit = _read("deploy/paperbot-executor.service").splitlines()
    for line in ("User=paperbot", "EnvironmentFile=/etc/paperbot/executor.env",
                 "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.executor run --config /etc/paperbot/executor.json",
                 "Restart=on-failure", "RestartPreventExitStatus=2", "NoNewPrivileges=yes", "ProtectSystem=strict",
                 "ReadWritePaths=/var/lib/paperbot"):
        assert line in unit, line
    inst = _read("deploy/install.sh")
    body = inst.split("cat <<'NEXT'")[0]
    assert "paperbot-executor.service; do" in body                         # installed with the other units
    units = next(x for x in body.splitlines() if x.startswith("UNITS="))
    assert "executor" not in units                                         # never stopped/started for a swap
    for line in body.splitlines():
        if "paperbot-executor" in line and "systemctl" in line and not line.strip().startswith("echo"):
            assert "is-active" in line, line                               # only asks; never enable/start/restart
    assert "install -o root -g root -m 600" in body and "/etc/paperbot/executor.env" in body
    assert "install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/exec" in body
    env = _read("deploy/executor.env.example")
    for line in env.splitlines():
        if line and not line.startswith("#"):
            assert line.endswith("="), line                                # no value, no secret in the repository
    for name in ("TESTNET_API_KEY", "LIVE_API_KEY", "LIVE_API_SECRET", "PAPERBOT_LIVE_MAINNET"):
        assert f"\n{name}=\n" in env
    for svc in ("deploy/paperbot-agents.service", "deploy/paperbot-dash.service"):
        hidden = next(x for x in _read(svc).splitlines() if x.startswith("InaccessiblePaths="))
        assert "-/etc/paperbot/executor.env" in hidden and "-/var/lib/paperbot/exec" in hidden, svc
    wrapper = _read("deploy/paperbot-exec.sh")
    assert "testnet|executor) shift" in wrapper and "EnvironmentFile=/etc/paperbot/executor.env" in wrapper
