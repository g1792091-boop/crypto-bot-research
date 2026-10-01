"""Regressions for the live-trading review (2026-10): each test reproduces a verified finding against the fake
exchange and checks the fix. Fake exchange only: every test here runs with sockets blocked."""

import email.message
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.response

import pytest

from fakefutures import FakeFutures
from paperbot import risk as R
from paperbot import testnet as TN
from paperbot.executor import ExecConfig, ExecStore, Refused, stage_review, stage_text
from paperbot.mainnet import online_gates
from paperbot.notify import CRITICAL
from paperbot.testnet import TestnetClient, TransientError
from test_executor import BTC, T0, World
from test_live_mainnet import Live, Paper

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETH = "ETHUSDT"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path)
    yield world
    world.store.close()


def refuse_eth_closes(fake):
    """Every market order on ETHUSDT is refused (-4131 PERCENT_PRICE in a fast market)."""
    orig = fake.route

    def route(m, path, q):
        if (m, path) == ("POST", "/fapi/v1/order") and q.get("symbol") == ETH:
            return fake.err(-4131, "The counterparty's best price does not meet the PERCENT_PRICE filter limit.")
        return orig(m, path, q)
    fake.route = route


def loops(w, n):
    """Like run(): a loop error is logged by the caller, the next loop goes on."""
    errors = []
    for _ in range(n):
        try:
            w.loop()
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    return errors


# ------------------------------------------------------------------ kill switch and limits come first
def test_a_stuck_reconcile_action_does_not_block_the_kill_switch(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()
    refuse_eth_closes(w.fake)
    w.fake.pos[ETH], w.fake.entry[ETH] = 2.0, 50.0           # a stray position whose close keeps being refused
    (tmp_path / "STOP").write_text("")
    errors = loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted and w.ex.trade is None
    assert errors and "-4131" in str(errors[0])                # the stuck symbol is still reported (loop_error)


def test_kill_switch_and_daily_loss_act_while_the_algo_order_reads_fail(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=60.0)
    w.paper(stop=90.0)
    w.loop()
    w.fake.fail("GET", "/fapi/v1/openAlgoOrders", "503_before", times=10_000)
    w.fake.set_price(BTC, 91.0)
    w.fake.add_funding(BTC, -30.0)                             # -45 - 30: over the $60 daily limit
    loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted and "하루 한도" in w.ex.risk.halt_reason
    w.store.close()
    (tmp_path / "k").mkdir()
    w = World(tmp_path / "k")
    w.paper(stop=95.0)
    w.loop()
    w.fake.fail("GET", "/fapi/v1/openAlgoOrders", "503_before", times=10_000)
    (tmp_path / "k" / "STOP").write_text("")
    loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted
    w.store.close()


def test_the_kill_switch_needs_nothing_but_positions_and_reduce_only_orders(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()
    w.fake.fail("GET", "/fapi/v2/account", "503_before", times=10_000)        # the account read keeps failing
    (tmp_path / "STOP").write_text("")
    errors = loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted and errors


def test_the_paper_exit_is_followed_while_another_symbol_is_stuck(w):
    w.paper(stop=95.0)
    w.loop()
    refuse_eth_closes(w.fake)
    w.fake.pos[ETH], w.fake.entry[ETH] = 2.0, 50.0
    w.src.intent = None                                        # the paper account exits
    loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and "paper 청산" in w.trades()[0][2]
    w.src.intent = None
    w.paper(stop=95.0, entry_time=w.clock.t)                   # but no NEW position while a symbol is stuck
    loops(w, 1)
    assert w.fake.pos[BTC] == 0


def test_flatten_goes_on_past_a_symbol_that_cannot_be_closed(tmp_path):
    w = World(tmp_path, fake=FakeFutures(prices={ETH: 50.0, BTC: 100.0, "SOLUSDT": 10.0}))   # ETH is listed first
    w.paper(stop=95.0)
    w.loop()
    refuse_eth_closes(w.fake)
    w.fake.pos[ETH], w.fake.entry[ETH] = 2.0, 50.0
    try:
        w.ex._flatten_halt(R.Decision(R.FLATTEN_HALT, ["시험"]))
    except Exception:  # noqa: BLE001  (the stuck symbol is reported either way)
        pass
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted
    w.store.close()


# ------------------------------------------------------------------ mainnet restart with an open position
def mainnet_with_open_trade(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    ex = lv.executor()
    ex.start()
    paper.enter(T0, qty=5.0, leverage=20)
    lv.clock.t = T0 + 70_000
    ex.loop_once()
    assert lv.fake.pos[BTC] == 5.0
    lv.store.close()
    lv.store = ExecStore(lv.cfg.db)
    return paper, lv


def test_one_dropped_permission_read_on_restart_is_retried(tmp_path):
    paper, lv = mainnet_with_open_trade(tmp_path)
    try:
        lv.fake.fail("GET", "/sapi/v1/account/apiRestrictions", "drop_before", times=1)
        ex = lv.executor()
        ex.start()                                             # retried: no refusal, the trade is managed again
        assert ex.trade["status"] == "open" and lv.events("mainnet_gates")
    finally:
        lv.close()


def test_an_unreachable_permission_check_is_a_restartable_error_with_an_alert(tmp_path):
    paper, lv = mainnet_with_open_trade(tmp_path)
    try:
        lv.fake.fail("GET", "/sapi/v1/account/apiRestrictions", "drop_before", times=50)
        with pytest.raises(TransientError) as e:               # exit 1 (systemd restarts), not Refused (exit 2)
            lv.executor().start()
        assert not isinstance(e.value, Refused)
        assert any(lvl == CRITICAL and "열린 포지션 BTCUSDT" in txt for lvl, txt in lv.note.messages)
    finally:
        lv.close()


# ------------------------------------------------------------------ an entry is never sent twice
class LateFake(FakeFutures):
    """-1007 "execution status unknown": the order reaches the matching engine only after the next request;
    client order ids are unique among OPEN orders only (a filled market order's id may be used again)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.late, self.late_next = None, 0

    def __call__(self, method, url, headers, body):
        import urllib.parse as up
        if self.late_next and method == "POST" and up.urlparse(url).path == "/fapi/v1/order":
            self.late_next -= 1
            self.late = (method, url, headers, body)
            return 503, json.dumps({"code": -1007, "msg": "Timeout waiting for response from backend server."}).encode()
        out = super().__call__(method, url, headers, body)
        if self.late is not None:
            late, self.late = self.late, None
            super().__call__(*late)
        return out

    def _market(self, q):
        self.by_client.pop(q.get("newClientOrderId"), None)
        return super()._market(q)


def entry_orders(fake):
    return [c for c in fake.calls if c[:2] == ("POST", "/fapi/v1/order") and c[2].get("reduceOnly") is None]


def test_an_entry_whose_answer_was_lost_is_never_sent_again(tmp_path):
    fake = LateFake()
    w = World(tmp_path, fake=fake, max_notional_usd=600.0)
    fake.late_next = 1
    w.paper(stop=95.0)
    w.loop()
    assert len(entry_orders(fake)) == 1 and fake.pos[BTC] == 5.0
    w.loop()                                                   # the reconcile adopts it and protects it
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and len(entry_orders(fake)) == 1
    assert not w.events("unknown_position")
    w.store.close()


def test_a_rate_limited_look_up_after_a_lost_entry_answer_is_not_a_refusal(w):
    w.paper(stop=95.0)
    w.fake.fail("POST", "/fapi/v1/order", "503_after")         # executed, answer lost
    w.fake.fail("GET", "/fapi/v1/order", "429", times=8)       # and the look-up is rate limited
    w.loop()
    assert w.ex.trade is not None and not w.events("entry_refused") and w.src.intent.key not in w.ex.done
    w.loop()
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and not w.events("unknown_position")


def test_a_late_execution_after_a_503_is_adopted_not_refused(w):
    fake, orig = w.fake, w.fake.route
    state = {"armed": True, "queued": None}

    def route(m, path, q):
        if state["queued"] is not None and not (m == "GET" and path == "/fapi/v1/order"):
            qq, state["queued"] = state["queued"], None
            orig("POST", "/fapi/v1/order", qq)                  # the backend executes the first send late
        if state["armed"] and (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") is None:
            state["armed"], state["queued"] = False, dict(q)
            return 503, {"code": -1007, "msg": "Send status unknown; execution status unknown."}
        return orig(m, path, q)
    fake.route = route
    w.paper(stop=95.0)
    w.loop()
    assert not w.events("entry_refused") and w.ex.trade["status"] == "entering"
    w.loop()
    assert fake.pos[BTC] == 5.0 and w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    assert not w.events("unknown_position")


def test_a_second_fill_is_cut_back_to_the_planned_size(w):
    w.paper(stop=95.0)
    w.fake.fail("POST", "/fapi/v1/order", "503_before")
    w.fake.fail("GET", "/fapi/v1/order", "503_before", times=20)
    w.loop()
    assert w.ex.trade["status"] == "entering"
    w.fake.pos[BTC], w.fake.entry[BTC] = 10.0, 100.0           # two fills landed (an earlier send executed late)
    w.fake.failures.clear()
    w.loop()
    assert w.fake.pos[BTC] == 5.0 and w.stops() == [(95.0, 5.0)] and w.events("oversize")


def test_a_position_that_grew_past_the_notional_cap_is_cut_back(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.pos[BTC] = 12.0                                     # $1,200 > the $1,000 cap
    w.loop()
    assert w.fake.pos[BTC] == 10.0 and w.stops() == [(95.0, 10.0)] and w.events("oversize")


# ------------------------------------------------------------------ a missing paper account mid-run
def test_a_paper_account_missing_mid_run_alerts_and_keeps_protecting(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, mode="testnet")
    try:
        ex = lv.executor()
        ex.start()
        paper.enter(T0, qty=5.0, leverage=20)
        lv.clock.t = T0 + 70_000
        ex.loop_once()
        assert lv.fake.pos[BTC] == 5.0
        paper.s.put_state("accounts", T0 + 120_000, {"last_ts": T0 + 120_000, "engines": {
            "OTHER@15m": {"wallet": 1.0, "position": None, "pending": []}}})
        paper.s.commit()
        for o in lv.fake.live_stops(BTC):
            o["algoStatus"] = "CANCELED"                       # and the stop disappears meanwhile
        ex.run(max_loops=3)                                    # no Refused out of the loop (exit 2: never restarted)
        assert any(lvl == CRITICAL and "paper 계좌를 읽을 수 없습니다" in txt for lvl, txt in lv.note.messages)
        assert lv.fake.pos[BTC] == 5.0 and lv.fake.covered(BTC)          # still reconciled and protected
    finally:
        lv.close()


# ------------------------------------------------------------------ no pacing pause between a fill and its stop
def test_no_rate_limit_pause_between_the_fill_and_its_stop(w):
    log = []
    w.ex.c.sleep = lambda s: log.append((len(w.fake.calls), s))
    orig = w.fake.route

    def route(m, path, q):
        out = orig(m, path, q)
        if (m, path) == ("POST", "/fapi/v1/order"):
            w.fake.weight = 1950                               # another process on this IP used the minute's weight
        return out
    w.fake.route = route
    w.paper(stop=95.0)
    w.loop()
    i_fill = next(i for i, c in enumerate(w.fake.calls) if c[:2] == ("POST", "/fapi/v1/order"))
    i_stop = next(i for i, c in enumerate(w.fake.calls) if c[:2] == ("POST", "/fapi/v1/algoOrder"))
    assert not [(n, s) for n, s in log if i_fill < n <= i_stop + 1 and s > 5]


# ------------------------------------------------------------------ a partial close keeps the stops
def partial_reduce_only(fake, frac):
    orig = fake._market
    state = {"armed": True}

    def market(q):
        if state["armed"] and q.get("reduceOnly") == "true":
            state["armed"] = False
            q = dict(q, quantity=str(round(float(q["quantity"]) * frac, 3)))
        return orig(q)
    fake._market = market


def test_a_paper_exit_that_fills_in_part_keeps_the_rest_protected(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 104.0)
    n = len(w.fake.timeline)
    partial_reduce_only(w.fake, 0.6)
    w.src.intent = None
    w.loop()
    assert w.fake.pos[BTC] == 2.0 and w.fake.covered(BTC) and w.events("not_flat")
    assert not [t for t in w.fake.timeline[n:] if BTC in t[3] and not t[3][BTC][1]]
    w.loop()                                                   # the next loop closes the rest
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and not w.fake.live_stops()


def test_a_lock_close_that_fills_in_part_keeps_the_old_stop(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 100.5)
    partial_reduce_only(w.fake, 0.6)
    w.paper(stop=101.1)                                        # past the price: -2021 -> reduce-only close
    w.loop()
    assert w.fake.pos[BTC] == 2.0 and w.fake.covered(BTC)


# ------------------------------------------------------------------ a stop firing between the two reads
def test_a_stop_firing_between_the_reads_is_not_a_missing_stop(w):
    w.paper(stop=95.0)
    w.loop()
    orig = w.fake.route
    state = {"armed": True}

    def route(m, path, q):
        if state["armed"] and (m, path) == ("GET", "/fapi/v1/openAlgoOrders") and q.get("symbol") == BTC:
            state["armed"] = False
            w.fake.set_price(BTC, 94.0)                        # the exchange stop fires right now
        return orig(m, path, q)
    w.fake.route = route
    w.loop(2)
    assert not w.events("no_stop") and w.fake.pos[BTC] == 0 and "거래소 손절" in w.trades()[0][2]
    w.store.commit()
    assert stage_review(w.cfg.db, w.cfg.paper_db, w.cfg.account, w.clock.t)["emergencies"] == {}


# ------------------------------------------------------------------ a restart never loosens a lock
def test_a_restart_in_the_middle_of_a_lock_move_keeps_the_tighter_stop(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 110.0)
    w.paper(stop=106.0)

    def die(*a, **k):
        raise KeyboardInterrupt("killed after the exchange moved the stop")
    w.ex._after_move = die
    with pytest.raises(KeyboardInterrupt):
        w.loop()
    assert w.stops() == [(106.0, 5.0)]
    w.restart()

    class Broken:
        def read(self):
            raise sqlite3.OperationalError("database is locked")
    w.ex.source = Broken()
    loops(w, 1)
    assert w.stops() == [(106.0, 5.0)] and w.ex.trade["stop"] == 106.0


def test_two_stops_left_by_a_crash_keep_the_tighter_one(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 110.0)
    w.client.stop_close(BTC, "SELL", 106.0, qty=5.0)           # the new stop placed, the old not yet cancelled
    w.loop()
    assert w.stops() == [(106.0, 5.0)]


# ------------------------------------------------------------------ the order keys are not readable by others
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="prctl is Linux only")
@pytest.mark.parametrize("module,argv", [("paperbot.executor", ["check-config", "--config", "/nonexistent.json"]),
                                         ("paperbot.testnet", ["reconcile"])])
def test_the_executor_and_the_drill_hide_their_environment(module, argv):
    code = ("import atexit, ctypes, runpy, sys; libc = ctypes.CDLL(None); "
            "atexit.register(lambda: print('DUMPABLE', libc.prctl(3, 0, 0, 0, 0), flush=True)); "
            f"sys.argv = ['{module}'] + {argv!r}; runpy.run_module('{module}', run_name='__main__')")
    env = {k: v for k, v in os.environ.items() if not k.endswith(("API_KEY", "API_SECRET"))}
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert "DUMPABLE 0" in out.stdout, (out.stdout, out.stderr[-2000:])


# ------------------------------------------------------------------ the key-permission gate fails closed
@pytest.mark.parametrize("body", [b"", b"null", b"<html>maintenance</html>"])
def test_a_permission_answer_that_is_not_a_record_refuses(tmp_path, body):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    lv.fake.restrictions.update(enableWithdrawals=True, ipRestrict=False)
    send = lv.send

    def odd(method, url, headers, b):
        if "/sapi/v1/account/apiRestrictions" in url:
            return 200, body, {}
        return send(method, url, headers, b)
    lv.keycheck.send = odd
    try:
        with pytest.raises((Refused, TransientError)):
            lv.executor().start()
        assert not lv.events("mainnet_gates") and not [c for c in lv.fake.calls if c[0] != "GET"]
    finally:
        lv.close()
    assert online_gates(lambda: None, 100.0, 500.0)[0]


def test_a_200_that_is_not_json_is_an_unknown_outcome():
    c = TestnetClient("k", "s", send=lambda *a: (200, b"<html>maintenance</html>", {}))
    with pytest.raises(TransientError):
        c.position(BTC)


# ------------------------------------------------------------------ the wallet guard
def test_other_assets_in_the_futures_wallet_refuse_the_start(tmp_path):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    lv.fake.other_assets = {"BNB": 3.0}
    try:
        with pytest.raises(Refused) as e:
            lv.executor().start()
        assert "BNB" in str(e.value)
    finally:
        lv.close()


# ------------------------------------------------------------------ redirects are never followed
class _Redirector(urllib.request.BaseHandler):
    handler_order = 100

    def __init__(self):
        self.seen = []

    def https_open(self, req):
        self.seen.append((req.host, dict(req.header_items())))
        if req.host == "testnet.binancefuture.com":
            hdrs = email.message.Message()
            hdrs["Location"] = "http://evil.example/steal"
            resp = urllib.response.addinfourl(io.BytesIO(b""), hdrs, req.full_url, 302)
        else:
            resp = urllib.response.addinfourl(io.BytesIO(b"{}"), email.message.Message(), req.full_url, 200)
        resp.msg = "x"
        return resp
    http_open = https_open


def test_a_redirect_is_never_followed(monkeypatch):
    red = _Redirector()
    monkeypatch.setattr(TN, "_OPENER", TN._build_opener(urllib.request.ProxyHandler({}), red))
    status, _, _ = TN.urllib_send("GET", "https://testnet.binancefuture.com/fapi/v2/account?signature=x",
                                  {"X-MBX-APIKEY": "secret-key"}, None)
    assert status == 302 and [h for h, _ in red.seen] == ["testnet.binancefuture.com"]


# ------------------------------------------------------------------ stage-check counts live days from a real start
def test_stage_check_counts_days_from_the_first_start_that_passed_the_gates(tmp_path):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, fake=FakeFutures(wallet=700.0, host="fapi.binance.com", api_key="lk"))
    try:
        with pytest.raises(Refused):                           # day 0: refused (wallet over budget x 1.2)
            lv.executor().start()
        lv.fake.wallet = 500.0
        lv.clock.t += 20 * 86_400_000                          # day 20: fixed, really started
        lv.executor().start()
        lv.store.commit()
        r = stage_review(lv.cfg.db, lv.cfg.paper_db, lv.cfg.account, lv.clock.t + 11 * 86_400_000)
        assert r["start"] == lv.clock.t and "실거래 기간 11일" in stage_text(r, lv.cfg.account)
    finally:
        lv.close()


# ------------------------------------------------------------------ a ratio-scaled lock past the price
def test_a_ratio_lock_past_the_price_uses_the_paper_lock_instead_of_closing(tmp_path):
    w = World(tmp_path, fake=FakeFutures(prices={BTC: 100.5, ETH: 50.0, "SOLUSDT": 10.0}))
    w.paper(stop=95.0, entry=100.0)                            # the live fill (100.5) is worse than the paper's
    w.loop()
    w.fake.set_price(BTC, 100.6)
    w.paper(stop=100.3, entry=100.0)                           # paper lock 100.3 < 100.6; scaled: 100.9 > 100.6
    w.loop()
    assert w.fake.pos[BTC] == 5.0 and w.stops() == [(100.3, 5.0)] and w.ex.trade["stop"] == 100.3
    assert not w.events("stop_would_trigger")
    w.store.close()


# ------------------------------------------------------------------ deposits and withdrawals are not P&L
def test_a_withdrawal_of_profit_is_not_a_daily_loss(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=100.0, max_drawdown_pct=0.4)
    w.paper(stop=95.0)
    w.loop()
    w.loop()
    w.fake.add_transfer(-150.0)                                # the owners take $150 of profit out
    w.loop()
    assert not w.ex.risk.halted and w.fake.pos[BTC] == 5.0 and w.events("transfer")
    assert w.ex.risk.peak_equity == pytest.approx(10_000.0 - 150.0 - 2.5 * 0 - w.fake.fee * 500, abs=1.0)
    w.clock.t += 301_000
    w.loop()
    w.store.commit()
    text = stage_text(stage_review(w.cfg.db, w.cfg.paper_db, w.cfg.account, w.clock.t), w.cfg.account)
    assert "최대 낙폭 0%" in text                                # the equity curve without the withdrawal
    w.store.close()


def test_a_deposit_does_not_hide_a_daily_loss(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=100.0)
    w.paper(stop=90.0)
    w.loop()
    assert w.fake.pos[BTC] == 5.0
    w.fake.add_transfer(50.0)                                  # a top-up
    w.fake.set_price(BTC, 91.0)                                # -45
    w.fake.add_funding(BTC, -60.0)                             # -60: $105 lost today, $55 after the top-up
    w.clock.t += 61_000                                        # the transfers are read once a minute
    w.loop()
    assert w.ex.risk.halted and w.fake.pos[BTC] == 0 and "하루 한도" in w.ex.risk.halt_reason
    w.store.close()


def test_an_unreadable_transfer_history_never_holds_back_a_daily_loss_halt(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=100.0)
    w.paper(stop=90.0)
    w.loop()
    w.fake.fail("GET", "/fapi/v1/income", "503_before", times=10_000)
    w.fake.set_price(BTC, 91.0)
    w.fake.add_funding(BTC, -60.0)                             # $105 lost today
    w.clock.t += 61_000
    loops(w, 1)
    assert w.ex.risk.halted and w.fake.pos[BTC] == 0
    w.store.close()


# ------------------------------------------------------------------ the loss at the stop fits the day's limit
def test_an_entry_is_cut_to_what_is_left_of_the_daily_loss_limit(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=100.0)
    w.loop()
    w.fake.wallet -= 90.0                                      # $90 lost today already
    w.paper(stop=95.0)                                         # 5 x ~$5.14 = ~$25.7 at the stop
    w.loop()
    assert 0 < w.fake.pos[BTC] < 2.0 and "남은 손실 한도" in w.events("entry_check")[-1][2]
    st = R.RiskState(day_start_equity=1_000.0)
    d = R.check_entry(risk_cfg := R.RiskConfig(daily_max_loss_usd=100.0, max_drawdown_pct=0.5,
                                               max_consecutive_losses=4, max_leverage=20, max_notional_usd=1e9,
                                               allowed_symbols=(BTC,), kill_file="/x/STOP"),
                      st, BTC, 50.0, 100.0, 20, 0.001, stop=90.0, equity=1_000.0, max_loss_frac=0.15)
    assert d.action == R.REDUCE and d.qty * 10.0 <= 100.0 + 1e-6 and risk_cfg.problems() == []
    w.store.close()


# ------------------------------------------------------------------ P&L from the trade's own fills
def test_an_exit_and_a_new_entry_in_the_same_loop_keep_their_own_fills(w):
    w.paper(stop=95.0, entry_time=w.clock.t - 30_000)
    w.loop()
    w.fake.set_price(BTC, 110.0)                               # A: +50
    w.paper(stop=105.0, entry_time=w.clock.t - 20_000, entry=110.0)
    w.loop()                                                   # exits A and enters B in the same loop
    w.fake.set_price(BTC, 109.0)                               # B: -5 and fees
    w.src.intent = None
    w.loop()
    (_, pa, sa, ra), (_, pb, sb, rb) = w.store.conn.execute(
        "SELECT key, pnl, pnl_source, realized FROM trades ORDER BY entry_ts").fetchall()
    assert sa == sb == "fills" and ra == pytest.approx(50.0) and rb == pytest.approx(-5.0)
    assert pb < 0 and w.ex.risk.consecutive_losses == 1


def test_fills_are_read_in_exchange_time(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    lv.fake.clock = lambda: lv.clock.t + 8_000                # the exchange's clock is 8 s ahead of ours
    try:
        ex = lv.executor()
        ex.start()
        paper.enter(T0, qty=5.0, leverage=20)
        lv.clock.t = T0 + 70_000
        ex.loop_once()
        lv.fake.set_price(BTC, 106.0)
        paper.flat(T0 + 600_000)
        lv.clock.t = T0 + 630_000
        ex.loop_once()
        pnl, src = lv.store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
        assert src == "fills" and pnl == pytest.approx(lv.fake.wallet - 520.0) and pnl > 25
        assert ex.risk.consecutive_losses == 0
    finally:
        lv.close()


def test_fills_not_yet_complete_right_after_the_close_are_read_again(w):
    w.paper(stop=95.0)
    w.loop()
    orig = w.fake.route
    state = {"hide": True}

    def route(m, path, q):
        status, data = orig(m, path, q)
        if path == "/fapi/v1/userTrades" and state["hide"]:
            state["hide"] = False
            data = data[:-1]                                   # the newest fill is not visible yet
        return status, data
    w.fake.route = route
    w.fake.set_price(BTC, 110.0)
    w.src.intent = None
    w.loop()                                                   # the half record is not kept; read again later
    assert any("체결 수량이 맞지 않음" in e[2] for e in w.events("cost_note"))
    w.loop()
    pnl, src = w.store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
    assert src == "fills" and pnl == pytest.approx(w.fake.wallet - 10_000.0) and pnl > 45
    assert w.ex.risk.consecutive_losses == 0


def test_a_trade_held_more_than_seven_days_is_measured_from_its_fills(w):
    w.paper(stop=95.0)
    w.loop()
    w.clock.t += 8 * 86_400_000
    w.src.ts = None
    w.fake.set_price(BTC, 104.0)
    w.src.intent = None
    w.loop()
    assert w.store.conn.execute("SELECT pnl_source FROM trades").fetchone()[0] == "fills"


def test_a_fee_paid_in_bnb_counts_in_the_trade_pnl(tmp_path):
    fake = FakeFutures(prices={BTC: 100.0, ETH: 50.0, "SOLUSDT": 10.0, "BNBUSDT": 500.0})
    fake.fee_asset = "BNB"
    w = World(tmp_path, fake=fake)
    w.paper(stop=95.0)
    w.loop()
    fake.set_price(BTC, 100.06)                                # +0.30 realised, ~0.50 of fees paid in BNB
    w.src.intent = None
    w.loop()
    pnl, src = w.store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
    assert src == "fills" and pnl == pytest.approx(0.30 - 0.0005 * (500 + 500.3), abs=1e-6)
    assert w.ex.risk.consecutive_losses == 1
    w.store.close()


def test_a_liquidation_clearance_fee_counts_in_the_trade_pnl(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 94.0)
    w.fake.add_income(BTC, "INSURANCE_CLEAR", -2.0)
    w.loop()
    pnl, src = w.store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
    assert src == "fills" and pnl == pytest.approx(w.fake.wallet - 10_000.0)


# ------------------------------------------------------------------ a failed cancel never closes a protected position
def test_a_refused_cancel_of_the_old_stop_keeps_the_new_stop_and_the_position(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.pos[BTC] = 7.0                                      # the stop (5) no longer covers: re-protect
    w.fake.fail("DELETE", "/fapi/v1/algoOrder", ("code", -4000, "Some other refusal."))
    w.loop()
    assert w.fake.pos[BTC] == 7.0 and w.fake.covered(BTC) and not w.events("protect_failed")
    w.loop()
    assert w.stops() == [(95.0, 7.0)]
    w.fake.fail("DELETE", "/fapi/v1/algoOrder",
                ("code", -1021, "Timestamp for this request is outside of the recvWindow."))
    w.fake.pos[BTC] = 8.0
    w.loop()
    assert w.stops() == [(95.0, 8.0)] and not w.events("protect_failed")


# ------------------------------------------------------------------ alerts do not depend on the database
def test_a_database_that_cannot_be_written_does_not_silence_the_kill_switch(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()

    class Full:
        def __init__(self, conn):
            self.c = conn

        def execute(self, *a, **k):
            if a and str(a[0]).lstrip().upper().startswith(("INSERT", "UPDATE")):
                raise sqlite3.OperationalError("database or disk is full")
            return self.c.execute(*a, **k)

        def __getattr__(self, n):
            return getattr(self.c, n)
    w.store.conn = Full(w.store.conn)
    (tmp_path / "STOP").write_text("")
    n = len(w.note.messages)
    w.ex.start = lambda: None                                  # the executor is running already
    w.ex.run(max_loops=2)
    new = w.note.messages[n:]
    assert w.fake.pos[BTC] == 0 and any(lvl == CRITICAL for lvl, _ in new)
    assert any("DB에 기록하지 못합니다" in txt for _, txt in new)


# ------------------------------------------------------------------ SIGTERM finishes the loop in progress
def test_sigterm_between_the_fill_and_the_stop_lets_the_stop_go_on(tmp_path):
    """`systemctl stop` (SIGTERM) right after the entry fill: `executor run` finishes the loop in progress (the stop
    goes on the exchange), then stops. Without a handler Python dies at once and leaves the position without a
    stop. Run in a child process: the signal is real."""
    conf = tmp_path / "executor.json"
    conf.write_text(json.dumps({
        "account": "A@15m", "paper_db": str(tmp_path / "paper3.db"), "db": str(tmp_path / "exec.db"),
        "qty_scale": 1.0, "poll_s": 0.5, "paper_env_file": str(tmp_path / "live.env"),
        "risk": {"daily_max_loss_usd": 500.0, "max_drawdown_pct": 0.4, "max_consecutive_losses": 4,
                 "max_leverage": 20, "max_notional_usd": 1000.0, "allowed_symbols": [BTC],
                 "kill_file": str(tmp_path / "STOP")}}))
    script = f"""
import os, signal, sqlite3, sys, time
sys.path[:0] = [{REPO!r}, {os.path.join(REPO, 'tests')!r}]
from fakefutures import FakeFutures
from paperbot.notify import ListNotifier
from paperbot.testnet import TestnetClient
import paperbot.executor as X
now = lambda: int(time.time() * 1000)
fake = FakeFutures()
fake.clock = now
t0 = now() - 60_000
orig = fake.route
def route(m, path, q):
    out = orig(m, path, q)
    if (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") is None:
        os.kill(os.getpid(), signal.SIGTERM)                 # systemctl stop right after the entry fill
    return out
fake.route = route
class Src:
    def __init__(self, *a):
        pass
    def read(self):
        return X.Intent(key=f"A@15m|BTCUSDT|{{t0}}", symbol="BTCUSDT", side=1, qty=5.0, leverage=20, stop=95.0,
                        entry_price=100.0, entry_time=t0), now() - 1_000
X.Paper3Source = Src
X._clients = lambda cfg, env=None: (TestnetClient("k", "s", send=fake, clock_ms=now), None)
X._notifier = ListNotifier
rc = X.main(["run", "--config", {str(conf)!r}, "--max-loops", "5"])
c = sqlite3.connect({str(tmp_path / "exec.db")!r})
stopped = c.execute("SELECT COUNT(*) FROM events WHERE kind = 'sigterm'").fetchone()[0]
print("RESULT", rc, fake.pos["BTCUSDT"], fake.covered("BTCUSDT"), stopped, flush=True)
"""
    out = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert "RESULT 0 5.0 True 1" in out.stdout, (out.returncode, out.stdout, out.stderr[-2000:])


# ------------------------------------------------------------------ the kill file must be visible to the service
def test_a_kill_file_the_service_cannot_see_is_refused(tmp_path):
    base = dict(account="A@15m", paper_db="/var/lib/paperbot/paper3.db", db="/var/lib/paperbot/exec/executor.db",
                qty_scale=1.0)
    rk = dict(daily_max_loss_usd=100.0, max_drawdown_pct=0.4, max_consecutive_losses=4, max_leverage=20,
              max_notional_usd=4000.0, allowed_symbols=(BTC,))
    for bad in ("/tmp/STOP", "/home/owner/STOP", "/var/lib/paperbot/exec/sub/STOP"):
        probs = ExecConfig(**base, risk=R.RiskConfig(**rk, kill_file=bad)).problems()
        assert any("비상 정지 파일" in p for p in probs), bad
    for good in ("/var/lib/paperbot/STOP", "/var/lib/paperbot/exec/STOP"):
        assert ExecConfig(**base, risk=R.RiskConfig(**rk, kill_file=good)).problems() == []


# ------------------------------------------------------------------ positionRisk lagging the fill
def test_a_position_read_that_lags_the_fill_is_read_again(w):
    orig = w.fake.route
    state = {"stale": 0}

    def route(m, path, q):
        if (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") is None:
            state["stale"] = 1
        if (m, path) == ("GET", "/fapi/v2/positionRisk") and q.get("symbol") == BTC and state["stale"]:
            state["stale"] -= 1
            return 200, [{"symbol": BTC, "positionAmt": "0", "entryPrice": "0"}]
        return orig(m, path, q)
    w.fake.route = route
    w.paper(stop=95.0)
    w.loop()
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and not w.events("entry_unfilled")


def test_a_position_read_that_keeps_lagging_leaves_the_entry_to_the_reconcile(w):
    orig = w.fake.route
    state = {"stale": 0}

    def route(m, path, q):
        if (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") is None:
            state["stale"] = 5
        if (m, path) == ("GET", "/fapi/v2/positionRisk") and q.get("symbol") == BTC and state["stale"]:
            state["stale"] -= 1
            return 200, [{"symbol": BTC, "positionAmt": "0", "entryPrice": "0"}]
        return orig(m, path, q)
    w.fake.route = route
    w.paper(stop=95.0)
    w.loop()
    assert w.ex.trade["status"] == "entering" and not w.events("entry_unfilled")
    w.loop()
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and not w.events("unknown_position")


# ------------------------------------------------------------------ an answer cut in the middle
def test_an_entry_answer_cut_in_the_middle_is_looked_up(w):
    w.paper(stop=95.0)
    w.fake.fail("POST", "/fapi/v1/order", "cut_after")
    w.loop()
    assert len(entry_orders(w.fake)) == 1 and w.stops() == [(95.0, 5.0)] and not w.events("no_stop")


# ------------------------------------------------------------------ the algo service not showing a new stop yet
def test_a_new_stop_not_visible_yet_is_not_a_failure(w):
    w.paper(stop=95.0)
    w.fake.fail("GET", "/fapi/v1/algoOrder", ("code", -2013, "Order does not exist."))
    w.loop()
    assert w.fake.pos[BTC] == 5.0 and w.stops() == [(95.0, 5.0)] and not w.events("protect_failed")


# ------------------------------------------------------------------ the units hide the executor's backups too
def test_agents_and_dashboard_cannot_see_the_executor_backups():
    for svc in ("deploy/paperbot-agents.service", "deploy/paperbot-dash.service"):
        with open(os.path.join(REPO, svc), encoding="utf-8") as fh:
            hidden = next(x for x in fh.read().splitlines() if x.startswith("InaccessiblePaths="))
        assert "-/var/backups/paperbot" in hidden, svc
