"""WOO X Pro (paperbot/wooxpro.py) on the fake exchange (tests/fakewooxpro.py): signing, contract units, orders, the
stop protocol (place, confirm, move with two at once, cancel), a stop that fires, fills and P&L, income, error mapping,
key gates, the drill, and the executor's whole cycle with ``"exchange": "wooxpro"`` (owners 10-20). No network."""

import json
import socket

import pytest

from fakewooxpro import FakeWooX
from paperbot import risk as R
from paperbot import wooxpro as WX
from paperbot.executor import ExecConfig, ExecStore, Executor, Intent, Refused
from paperbot.mainnet import FLAG, FLAG_VALUE
from paperbot.notify import ListNotifier
from paperbot.testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, RateLimited, TestnetError, TransientError,
                              covers, live_stops, move_stop, place_stop)

T0 = 1_800_000_000_000
BTC, DOGE = "BTCUSDT", "DOGEUSDT"
LIVE_ENV = {FLAG: FLAG_VALUE, "WOOXPRO_LIVE_KEY": "wk", "WOOXPRO_LIVE_SECRET": "ws", "WOOXPRO_LIVE_MEMO": "wm",
            WX.KEY_CHECKED: WX.KEY_CHECKED_VALUE}


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


def make(fake=None, clock=None, **kw):
    clock = clock or Clock()
    fake = fake or FakeWooX()
    fake.clock = clock
    c = WX.WooXProClient("wk", "ws", "wm", send=fake, clock_ms=clock, sleep=lambda s: None, **kw)
    return c, fake, clock


def ready(c, fake, symbols=(BTC,)):
    c.sync_time()
    c.one_way()
    for s in symbols:
        c.isolated(s)
    return c


# ------------------------------------------------------------------ transport, signing, errors
def test_signed_requests_and_the_envelope():
    c, fake, _ = make()
    assert c.position_mode() == "hedge_mode"
    m, path, query, body = fake.calls[-1][1:]
    assert (m, path, body) == ("GET", "/contract/private/get-position-mode", None)
    bad = WX.WooXProClient("wk", "ws", "other-memo", send=fake, clock_ms=fake.now, sleep=lambda s: None)
    with pytest.raises(TestnetError) as e:                 # the memo is part of the signature
        bad.position_mode()
    assert e.value.code == 30005
    with pytest.raises(ValueError):
        WX.WooXProClient("wk", "ws", "wm", base="https://api.wooxpro.com")
    with pytest.raises(ValueError):
        WX.WooXProClient("wk", "ws", "")                   # no memo: refused at construction


def test_error_codes_map_to_the_executor_classes():
    c, fake, clock = make()
    fake.fail("GET", "/contract/private/get-position-mode", "429", times=9)       # past the read retries
    with pytest.raises(RateLimited) as e:
        c.position_mode()
    assert e.value.status == 429
    fake.fails.clear()
    fake.fail("GET", "/contract/private/get-position-mode", "403")
    with pytest.raises(RateLimited) as e:
        c.position_mode()
    assert e.value.status == 418
    fake.fail("GET", "/contract/private/get-position-mode", "503_before")
    with pytest.raises(TransientError):
        c.position_mode()
    fake.fail("GET", "/contract/private/get-position-mode", "503_html", times=9)
    with pytest.raises(TransientError) as e:
        c.position_mode()
    assert e.value.status == 503 and "<html" not in str(e.value)       # the alert says what it is, not the page
    assert "503 Service Temporarily Unavailable (WOO X Pro 서버의 오류 페이지" in str(e.value)
    fake.fails.clear()
    c.offset_ms = 120_000                                  # a clock two minutes off: the clock refusal (-1021)
    with pytest.raises(TestnetError) as e:
        c.position_mode()
    assert e.value.code == BAD_TIMESTAMP
    c.offset_ms = 0
    with pytest.raises(TestnetError) as e:
        c.order(BTC, order_id="12345")
    assert e.value.code == NOT_FOUND[0]


@pytest.mark.parametrize("source", ["system", "funding", "none"])
def test_server_time(source):
    c, fake, clock = make()
    fake.time_source = source
    clock.t += 0
    off = c.sync_time()
    assert off == 0 and c.time_source == {"system": "/system/time", "funding": "/contract/public/funding-rate",
                                          "none": "local"}[source]


def test_contract_units_from_the_details():
    c, fake, _ = make()
    sp = c.spec(BTC)
    assert sp["qty_step"] == 0.001 and sp["min_qty"] == 0.001 and sp["tick"] == 0.1 and sp["max_leverage"] == 100
    assert c.spec(DOGE)["qty_step"] == 10 and c._contracts(DOGE, 25.0) == 2      # floored, never more than asked
    with pytest.raises(TestnetError):
        c.spec("BTCUSD")                                   # not a USDT perpetual
    assert c.price(BTC) == 100.0


def test_klines_in_seconds_and_pieces():
    c, fake, clock = make()
    for i in range(3):
        fake.set_price(BTC, 100.0 + i)
        clock.t += 60_000
    rows = c.klines(BTC, T0 - 60_000, clock.t)
    assert [r[0] for r in rows] == [T0, T0 + 60_000, T0 + 120_000] and rows[-1][3] == 102.0
    assert c.kline_source == "last"


def test_empty_last_price_candles_are_read_from_the_mark_price_candles():
    """The owners' server, 10-20: /contract/public/kline answered [] for every coin while /markprice-kline answered."""
    c, fake, clock = make()
    fake.last_kline_empty = True
    for i in range(3):
        fake.set_price(BTC, 100.0 + i)
        clock.t += 60_000
    rows = c.klines(BTC, T0 - 60_000, clock.t)
    assert [r[0] for r in rows] == [T0, T0 + 60_000, T0 + 120_000] and rows[-1][3] == 102.0
    assert c.kline_source == "mark"
    paths = [x[2] for x in fake.calls if "kline" in x[2]]
    assert paths == ["/contract/public/kline", "/contract/public/markprice-kline"]


# ------------------------------------------------------------------ account set-up
def test_one_way_and_isolated_leverage_read_back():
    c, fake, _ = make()
    ready(c, fake, symbols=(BTC, DOGE))
    assert fake.mode == "one_way_mode"
    assert fake.levs[BTC] == ["isolated", 40] and fake.levs[DOGE] == ["isolated", 30]
    lines = c.account_setup((BTC, DOGE))
    assert lines[0] == (True, "포지션 모드: 단방향(one-way)") and all(ok for ok, _ in lines)


def test_hedge_mode_with_a_position_is_refused():
    c, fake, _ = make()
    fake.pos[BTC] = 5
    with pytest.raises(Refused):
        c.one_way()


# ------------------------------------------------------------------ orders and stops
def test_market_entry_close_and_reduce_only_sides():
    c, fake, _ = make()
    ready(c, fake)
    o = c.market(BTC, "BUY", 5.0, client_id="pbAentry1")
    assert o["status"] == "FILLED" and o["executedQty"] == "5" and o["avgPrice"] == "100.0"
    assert fake.pos[BTC] == 5000 and float(c.position(BTC)["positionAmt"]) == 5.0
    assert c.order(BTC, client_id="pbAentry1")["orderId"] == o["orderId"]        # found by its client_order_id
    body = json.loads(fake.calls[-4][4] if fake.calls[-4][2].endswith("submit-order") else
                      next(x[4] for x in fake.calls if x[2].endswith("submit-order")))
    assert body["side"] == 1 and body["type"] == "market" and body["size"] == 5000 and body["leverage"] == "40"
    x = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbAclose1")
    assert x["status"] == "FILLED" and x["reduceOnly"] is True and fake.pos[BTC] == 0
    sent = [json.loads(b) for _, m, p, _, b in fake.calls if p.endswith("submit-order")]
    assert [s["side"] for s in sent] == [1, 3]


def test_a_long_client_id_is_hashed_to_letters_and_digits():
    cid = "pb1800000000000V45_AMB@15m|BTCUSDT-s3r00ff00ff"
    ext = WX.ext_id(cid)
    assert len(ext) <= 32 and ext.isalnum() and WX.ext_id(cid) == ext
    assert WX.ext_id("pbAs1r1a2b3c4d") == "pbAs1r1a2b3c4d"


def test_opening_order_rate_limit_is_an_unknown_outcome_never_resent():
    c, fake, _ = make()
    ready(c, fake)
    fake.fail("POST", "/contract/private/submit-order", "429")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbAentry2")
    assert sum(1 for x in fake.calls if x[2].endswith("submit-order")) == 1


def test_duplicate_client_id_answers_the_existing_order():
    c, fake, _ = make()
    ready(c, fake)
    first = c.market(BTC, "BUY", 1.0, client_id="pbAentry3")
    again = c.market(BTC, "BUY", 1.0, client_id="pbAentry3")
    assert again["orderId"] == first["orderId"] and fake.pos[BTC] == 1000


def test_stop_place_confirm_move_cancel():
    c, fake, _ = make()
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs1r1")
    stops = live_stops(c, BTC)
    assert len(stops) == 1 and stops[0]["algoId"] == st["algoId"] and stops[0]["triggerPrice"] == "95"
    assert stops[0]["workingType"] == "CONTRACT_PRICE" and covers(stops[0], 5.0) and stops[0]["side"] == "SELL"
    body = json.loads(next(x[4] for x in fake.calls if x[2].endswith("submit-tp-sl-order")))
    assert body == {"symbol": BTC, "type": "stop_loss", "side": 3, "size": 5000, "trigger_price": "95",
                    "executive_price": "95", "price_type": 1, "plan_category": 1, "client_order_id": "pbAs1r1",
                    "category": "market"}
    seen = {}
    orig = c.cancel_algo

    def watch(algo_id=None, client_id=None):
        seen.setdefault("during", len(live_stops(c, BTC)))
        return orig(algo_id=algo_id, client_id=client_id)
    c.cancel_algo = watch
    fake.set_price(BTC, 105.0)
    mv = move_stop(c, BTC, "SELL", 101.1, 5.0, [st["algoId"]], client_id="pbAs2r2")
    c.cancel_algo = orig
    assert mv["result"] == "moved" and seen["during"] == 2
    assert [(x["triggerPrice"], x["quantity"]) for x in live_stops(c, BTC)] == [("101.1", "5")]
    assert not fake.unprotected()
    c.cancel_all_algo(BTC)
    assert not live_stops(c, BTC)


def test_stop_found_after_a_lost_answer():
    c, fake, _ = make()
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    fake.fail("POST", "/contract/private/submit-tp-sl-order", "drop_after")
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbAs1r9")
    got = c.algo_order(client_id="pbAs1r9")                 # by its client_order_id in the resting list
    assert got["algoStatus"] == "NEW" and got["triggerPrice"] == "95"


@pytest.mark.parametrize("past", ["refuse", "invalid", "trigger"])
def test_a_stop_past_the_price(past):
    c, fake, _ = make()
    fake.plan_past = past
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    fake.set_price(BTC, 100.5)
    if past in ("refuse", "invalid"):
        with pytest.raises(TestnetError) as e:
            c.stop_close(BTC, "SELL", 101.1, 5.0, client_id="pbAs3r3")
        assert e.value.code == WOULD_TRIGGER                 # the executor then closes at market
        assert sum(1 for x in fake.calls if x[2].endswith("submit-tp-sl-order")) == 1   # refused once, not retried
    else:
        got = place_stop(c, BTC, "SELL", 101.1, 5.0, client_id="pbAs3r3")
        assert got.get("fired") and fake.pos[BTC] == 0


@pytest.mark.parametrize("side,close,move", [(1, "SELL", -0.4), (-1, "BUY", 0.4)])
def test_a_lock_past_the_price_answered_with_40012_closes_at_market(side, close, move):
    """Live 10-21 01:00 (BCH long) and 10-28 21:35 (XRP short): WOO X Pro answered the lock move with 40012 "The stop
    loss price is invalid, needs to be lesser / greater than the order price"; read as a system error, the same price
    was sent again for four minutes while the old stop stayed. Now it is the -2021 path: closed at market at once."""
    c, fake, _ = make()
    fake.plan_past = "invalid"
    ready(c, fake)
    c.market(BTC, "BUY" if side > 0 else "SELL", 5.0, client_id="pbAe")
    old = place_stop(c, BTC, close, 95.0 if side > 0 else 105.0, 5.0, client_id="pbAs7r1")
    lock = 100.2 if side > 0 else 99.8
    fake.set_price(BTC, 100.0 + move)                       # the price went back through the lock
    r = move_stop(c, BTC, close, lock, 5.0, [old["algoId"]], client_id="pbAs7r2", close_id="pbAc7r2")
    assert r["result"] == "closed" and r["flat"] and fake.pos[BTC] == 0
    assert sum(1 for x in fake.calls if x[2].endswith("submit-tp-sl-order")) == 2   # the first stop + one refusal


def test_40012_without_the_stop_text_stays_a_system_error():
    c, fake, _ = make()
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    fake.fail("POST", "/contract/private/submit-tp-sl-order", ("ret", 40012, "System error"), times=9)
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbAs8r1")


@pytest.mark.parametrize("history_plans,placed_cid", [(True, True), (True, False), (False, True)])
def test_a_fired_stop_reads_as_triggered_with_its_market_order(history_plans, placed_cid):
    c, fake, _ = make()
    fake.history_plans, fake.placed_cid = history_plans, placed_cid
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs4r4")
    fake.set_price(BTC, 94.0)
    assert fake.pos[BTC] == 0
    got = c.algo_order(algo_id=st["algoId"])
    assert got["algoStatus"] == "TRIGGERED" and got["actualOrderId"]
    fills = c.user_trades(BTC, T0 - 5_000, T0 + 5_000)
    assert {f["orderId"] for f in fills} >= {got["actualOrderId"]}


def test_cancelled_stop_reads_as_cancelled():
    c, fake, _ = make()
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs5r5")
    c.cancel_algo(algo_id=st["algoId"])
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"
    with pytest.raises(TestnetError) as e:
        c.cancel_algo(algo_id=st["algoId"])
    assert e.value.code in NOT_FOUND


# ------------------------------------------------------------------ fills, P&L, income
def test_fills_replay_the_realized_pnl_and_check_realised_profit():
    c, fake, clock = make()
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    clock.t += 60_000
    fake.set_price(BTC, 110.0)
    c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbAx")
    fills = c.user_trades(BTC, T0 - 5_000, clock.t + 5_000)
    assert [f["side"] for f in fills] == ["BUY", "SELL"]
    out = fills[1]
    assert out["realizedPnl"] == "50" and out["realizedCheck"] == "ok" and out["wooSide"] == 3
    assert float(out["commission"]) == pytest.approx(0.0006 * 5 * 110.0)
    assert float(c.account()["totalWalletBalance"]) == pytest.approx(10_000 + 50 - 0.0006 * 5 * 210)


def test_trades_window_is_split_when_full(monkeypatch):
    c, fake, clock = make()
    ready(c, fake, symbols=(DOGE,))
    for i in range(130):
        c.market(DOGE, "BUY", 10.0, client_id=f"pbB{i}")
        c.market(DOGE, "SELL", 10.0, reduce_only=True, client_id=f"pbC{i}")
        clock.t += 1_000
    fills = c.user_trades(DOGE, T0 - 1_000, clock.t + 1_000)
    assert len(fills) == 260


def test_income_funding_and_transfers():
    c, fake, clock = make()
    fake.add_funding(BTC, -1.25, time=T0 + 1_000)
    fake.add_transfer(50.0, time=T0 + 2_000)
    rows = c.income(None, None, T0, T0 + 10_000)
    assert [(r["incomeType"], r["income"]) for r in rows] == [("FUNDING_FEE", "-1.25"), ("TRANSFER", "50")]
    assert [r["incomeType"] for r in c.income(BTC, None, T0, T0 + 10_000)] == ["FUNDING_FEE"]


# ------------------------------------------------------------------ keys and allowlist
def test_keys_gates():
    assert WX.trading_keys("mainnet", LIVE_ENV) == ("wk", "ws", "wm")
    for drop, needle in (("WOOXPRO_LIVE_MEMO", "MEMO"), (FLAG, "실거래 스위치"), ("WOOXPRO_LIVE_SECRET", "비어")):
        env = {k: v for k, v in LIVE_ENV.items() if k != drop}
        with pytest.raises(Refused, match=needle):
            WX.trading_keys("mainnet", env)
    with pytest.raises(Refused, match="MEXC"):
        WX.trading_keys("mainnet", {**LIVE_ENV, "MEXC_LIVE_KEY": "wk"})
    with pytest.raises(Refused, match="테스트넷"):
        WX.trading_keys("testnet", LIVE_ENV)
    c, kc = WX.clients("mainnet", LIVE_ENV)
    WX.refuse_unless_allowed("mainnet", c)
    with pytest.raises(Refused):
        WX.refuse_unless_allowed("mainnet", WX.public_client())
    with pytest.raises(Refused):
        WX.refuse_unless_allowed("mainnet", kc)                        # the key-check class never trades


def test_key_check_needs_the_owners_statement():
    fake = FakeWooX()
    fake.clock = Clock()
    for attested, problems in ((True, False), (False, True)):
        kc = WX.WooXProKeyCheckClient("wk", "ws", "wm", send=fake, clock_ms=fake.clock, sleep=lambda s: None,
                                      attested=attested)
        perm = kc.api_restrictions()
        from paperbot.mainnet import check_permissions
        assert bool(check_permissions(perm)) is problems


def test_agents_never_import_the_module():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "paperbot"
    for p in list(root.glob("agents*.py")) + list(root.glob("rooms*.py")) + list((root / "agents").glob("**/*.py")):
        assert "wooxpro" not in p.read_text(encoding="utf-8"), p


# ------------------------------------------------------------------ the drill
def test_drill_check_and_order_cycle_with_the_trigger_test():
    c, fake, clock = make()
    fake.prices[DOGE] = 0.2
    kc = WX.WooXProKeyCheckClient("wk", "ws", "wm", send=fake, clock_ms=clock, sleep=lambda s: None, attested=True)
    waits = []

    def wait(s):
        waits.append(s)
        clock.t += int(s * 1000)
        stops = [float(p["trigger_price"]) for p in fake.plans.values()]
        if fake.pos[DOGE] and len(stops) == 1 and stops[0] < 0.2:
            fake.set_price(DOGE, 0.2008)                  # the price moves 0.4 % our way: the test stop goes above entry
        elif fake.pos[DOGE] and len(stops) == 1 and stops[0] > 0.2:
            fake.set_price(DOGE, 0.2)                     # ... and comes back to it: the stop fires
    d = WX.WooXProDrill(c, symbol=DOGE, keycheck=kc, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000)
    d.check()
    d.order_cycle()
    fails = [r for r in d.log if not r["ok"]]
    assert not fails, fails
    steps = {r["step"]: r for r in d.log}
    fired = next(r for k, r in steps.items() if k.startswith("손절 발동 시험:"))
    assert fired["detail"]["status"] == "TRIGGERED"
    assert steps["이익 쪽 손절(계단 잠금 자리, 진입가보다 유리한 곳)이 걸림"]["ok"]
    assert steps["체결 기록에 수수료가 들어 있음(0이면 수수료를 못 읽는 것)"]["ok"]
    assert steps["펀딩·입출금 기록 읽기(지난 7일)"]["ok"]
    pnl = next(r for k, r in steps.items() if k.startswith("체결로 계산한 손익"))
    assert pnl["detail"]["fee_rate_pct"] == pytest.approx(0.06, abs=1e-3)
    assert fake.pos[DOGE] == 0 and not fake.plans


def test_drill_prints_each_step_as_it_happens_and_a_last_line():
    c, fake, clock = make()
    fake.prices[DOGE] = 0.2
    lines = []
    d = WX.WooXProDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                        say=lines.append)
    assert WX.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert len([x for x in lines if x.startswith("[OK]")]) == len(d.log)
    assert any("창을 닫지 마세요" in x for x in lines)
    assert lines[-1] == "끝: drill 모두 [OK]"
    assert fake.pos[DOGE] == 0 and not fake.plans


@pytest.mark.parametrize("stop", ["error", "ctrl_c"])
def test_a_drill_stopped_part_way_leaves_the_coin_flat(stop):
    c, fake, clock = make()
    fake.prices[DOGE] = 0.2
    lines = []

    def wait(s):            # the stop is resting and the trigger test waits: then the drill is stopped
        clock.t += int(s * 1000)
        if fake.pos[DOGE] and fake.plans and clock.t > T0 + 60_000:
            if stop == "ctrl_c":
                raise KeyboardInterrupt("SIGHUP")
            raise ValueError("an unexpected reply")
    d = WX.WooXProDrill(c, symbol=DOGE, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000,
                        say=lines.append)
    assert not WX.run_drill(c, d, "drill", True, pause=lambda s: None)
    steps = {r["step"]: r for r in d.log}
    assert not steps["멈춤"]["ok"] and ("KeyboardInterrupt" if stop == "ctrl_c" else "ValueError") in \
        steps["멈춤"]["detail"]
    assert steps["정리 후 상태"]["ok"], steps["정리 후 상태"]
    assert fake.pos[DOGE] == 0 and not fake.plans and not fake.live_stops()
    assert lines[-1].startswith("끝: drill [FAIL]")


def test_the_clean_up_still_cancels_when_the_close_fails():
    c, fake, clock = make()
    ready(c, fake, (DOGE,))
    fake.prices[DOGE] = 0.2
    c.market(DOGE, "BUY", 30)
    place_stop(c, DOGE, "SELL", 0.19, 30)
    fake.fail("POST", "/contract/private/submit-order", ("ret", 40011, "Invalid parameter"), times=1)
    log = []
    WX.leave_flat(c, DOGE, lambda *row: log.append(row))
    assert log[0][0].startswith("정리: 포지션 닫기 실패") and not log[0][1]
    assert not fake.plans and fake.pos[DOGE] != 0          # the stop is gone even though the close failed
    assert log[-1][0] == "정리 후 상태" and not log[-1][1]


def test_drill_stops_when_two_stops_cannot_rest_at_once():
    c, fake, clock = make()
    fake.two_stops = False
    fake.prices[DOGE] = 0.2
    d = WX.WooXProDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    d.check()
    with pytest.raises((AssertionError, TestnetError)):
        d.order_cycle()


# ------------------------------------------------------------------ the executor, whole cycle
class Source:
    def __init__(self, clock):
        self.clock, self.intent, self.ts = clock, None, None

    def read(self):
        return self.intent, (self.ts if self.ts is not None else self.clock() - 30_000)


class World:
    def __init__(self, tmp_path, fake=None, **cfg_kw):
        self.clock = Clock()
        self.fake = fake or FakeWooX(wallet=10_000.0)
        self.fake.clock = self.clock
        self.src = Source(self.clock)
        self.note = ListNotifier()
        risk = R.RiskConfig(daily_max_loss_usd=500.0, max_drawdown_pct=0.2, max_consecutive_losses=3, max_leverage=40,
                            max_notional_usd=1_000.0, allowed_symbols=(BTC, "ETHUSDT"),
                            kill_file=str(tmp_path / "STOP"))
        self.cfg = ExecConfig(account="V45_AMB@15m", paper_db=str(tmp_path / "paper3.db"),
                              db=str(tmp_path / "exec-woox.db"), qty_scale=1.0, risk=risk, retries=4, sweep_every=1,
                              exchange="wooxpro", mode="mainnet", budget_usd=10_000.0,
                              paper_env_file=str(tmp_path / "live.env"), **cfg_kw)
        self.store = ExecStore(self.cfg.db)
        kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda s: None)
        self.client = WX.WooXProClient("wk", "ws", "wm", **kw)
        self.keycheck = WX.WooXProKeyCheckClient("wk", "ws", "wm", attested=True, **kw)
        self.ex = Executor(self.cfg, self.client, self.src, self.store, self.note, now_ms=self.clock,
                           sleep=lambda s: None, keycheck=self.keycheck, env=dict(LIVE_ENV))
        self.ex.start()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def paper(self, stop, side=1, qty=5.0, lev=20, entry=100.0):
        et = self.src.intent.entry_time if self.src.intent else self.clock.t - 60_000
        self.src.intent = Intent(key=f"V45_AMB@15m|{BTC}|{et}", symbol=BTC, side=side, qty=qty, leverage=lev,
                                 stop=stop, entry_price=entry, entry_time=et)

    def stops(self):
        return [(float(p["trigger_price"]), int(p["size"])) for p in self.fake.live_stops(BTC)]


def test_executor_config_problems():
    risk = R.RiskConfig(max_leverage=40, allowed_symbols=(BTC,), kill_file="/var/lib/paperbot/STOP")
    cfg = ExecConfig(account="A", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="wooxpro",
                     mode="testnet", budget_usd=100.0, risk=risk)
    assert any("WOO X Pro에는 선물 테스트넷이 없습니다" in p for p in cfg.problems())
    cfg = ExecConfig(account="A", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="wooxpro",
                     mode="mainnet", budget_usd=100.0, risk=risk,
                     net_costs={"wooxpro": {"taker_fee": 0.00042, "slippage": 0.0002}})
    assert not [p for p in cfg.problems() if "net_costs" in p or "exchange" in p]


def test_executor_entry_stop_lock_steps_and_exit_from_fills(tmp_path):
    w = World(tmp_path)
    assert w.fake.mode == "one_way_mode" and w.fake.levs[BTC] == ["isolated", 40]
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 5000 and w.stops() == [(95.0, 5000)]
    assert w.fake.levs[BTC] == ["isolated", 20]                        # the paper's leverage
    assert w.ex.prefix == "[WOO X Pro 실거래 실행기]" and w.store.get_state("meta")["exchange"] == "wooxpro"
    for price, lock in [(105.0, 101.1), (109.0, 104.9), (113.0, 109.3)]:
        w.fake.set_price(BTC, price)
        w.paper(stop=lock)
        w.loop()
        assert w.stops() == [(lock, 5000)], (price, lock)
    assert not w.fake.unprotected()
    w.fake.add_funding(BTC, -1.25)
    w.src.intent = None                                                # paper exit
    w.loop(2)
    assert w.fake.pos[BTC] == 0 and not w.fake.plans and w.ex.trade is None
    key, qty, reason, pnl, source = w.store.conn.execute(
        "SELECT key, qty, exit_reason, pnl, pnl_source FROM trades").fetchone()
    assert source == "fills" and pnl == pytest.approx(w.fake.wallet - 10_000.0, abs=1e-6)


def test_the_own_ladder_locks_on_mark_price_candles_when_the_last_price_candles_are_empty(tmp_path):
    """The owners' server, 10-20: WOO X Pro's last-price 1m candles came back empty. The "own" ladder (its fill, this
    exchange's 1m highs) reads the mark price's candles instead: a high between two loops still locks, with no
    "candles unreadable" warning."""
    fake = FakeWooX(wallet=10_000.0)
    fake.last_kline_empty = True
    ladder = {"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03}
    w = World(tmp_path, fake=fake, ladder_from="own", ladder=ladder,
              net_costs={"wooxpro": {"taker_fee": 0.00042, "slippage": 0.0002}})
    w.paper(stop=95.0, lev=5)
    w.loop()
    t = w.ex.trade
    assert t is not None and t["entry_price"] == pytest.approx(100.0)
    w.clock.t += 60_000 - w.clock.t % 60_000 + 1_000                 # the next minute
    w.fake.set_price(BTC, 102.5)                                     # 5x: net ROE +11.9 %, between two loops
    w.fake.set_price(BTC, 102.3)                                     # the loop's own price: +10.9 %, no lock by itself
    w.loop()
    o = w.ex.trade["own"]
    assert o["src"] == "kline" and o["best"] == pytest.approx(102.5) and o["lock"] == pytest.approx(0.10)
    assert w.stops() == [(102.2, 5000)]                              # +10 % net: 102.124, a tick up (never looser)
    assert not w.store.conn.execute("SELECT 1 FROM events WHERE kind = 'own_prices'").fetchall()
    assert w.ex.c.kline_source == "mark"


def test_executor_books_a_stop_that_fired_on_the_exchange(tmp_path):
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 94.0)                                        # the exchange stop fires
    w.loop(3)
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None
    reason, source = w.store.conn.execute("SELECT exit_reason, pnl_source FROM trades").fetchone()
    assert "손절" in reason and source == "fills"


# ------------------------------------------------------------------ the live site: the second slot's name and database
def test_live_site_reads_the_second_slots_exchange_and_database(tmp_path):
    from paperbot.dash.more import livebots as LB
    cfg = tmp_path / "executor-mexc.json"
    cfg.write_text(json.dumps({"exchange": "wooxpro", "db": str(tmp_path / "executor-wooxpro-live.db"),
                               "account": "COMBO@mix"}), encoding="utf-8")
    env = {"PAPERBOT_LIVE_MEXC_CONFIG": str(cfg), "PAPERBOT_LIVE_BYBIT_CONFIG": str(tmp_path / "none.json")}
    p = LB.paths(env)
    assert p["mexc_db"] == str(tmp_path / "executor-wooxpro-live.db")
    assert p["bybit_db"] == "/var/lib/paperbot/exec/executor-bybit-live.db"           # no config: the guide's path
    assert LB.paths({**env, "PAPERBOT_LIVE_MEXC_DB": "/x.db"})["mexc_db"] == "/x.db"   # the variable still wins
    configs = {ex: LB.read_config(p[ck]) for ex, _ko, _dk, ck in LB.EXECS}
    assert [ko for _ex, ko, _dk, _ck in LB.slots(configs)] == ["바이비트", "WOO X Pro"]


def test_a_read_refused_for_the_rate_is_read_again_but_an_order_never():
    c, fake, clock = make()
    pauses = []

    def pause(s):
        pauses.append(s)
        clock.t += int(s * 1000)
    c.sleep = pause
    fake.fail("GET", "/contract/private/get-position-mode", "429", times=2)
    assert c.position_mode() == "hedge_mode" and len(pauses) == 2                  # read again after a pause
    fake.fail("GET", "/contract/private/get-position-mode", "429", times=9)
    with pytest.raises(RateLimited):
        c.position_mode()                                                         # at most READ_RETRIES times
    fake.fails.clear()
    ready(c, fake)
    fake.fail("POST", "/contract/private/submit-order", "429")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbAentry7")
    assert sum(1 for x in fake.calls if x[2].endswith("submit-order")) == 1      # an order: never resent here


def test_a_setting_a_cancel_or_a_stop_refused_for_the_rate_is_sent_again():
    """The first live check (10-20) stopped on a 429 right before the one-way switch: settings, cancels and stops
    (refused, nothing ran) are sent again after a pause."""
    c, fake, clock = make()
    c.sleep = lambda s: setattr(clock, "t", clock.t + int(s * 1000))
    fake.fail("POST", "/contract/private/set-position-mode", "429", times=2)
    c.one_way()
    assert c.position_mode() == "one_way_mode"
    fake.fail("POST", "/contract/private/submit-leverage", "429", times=1)
    c.isolated(BTC)
    assert fake.levs[BTC] == ["isolated", 40]
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    fake.fail("POST", "/contract/private/submit-tp-sl-order", "429", times=1)
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs")
    assert [float(p["trigger_price"]) for p in fake.live_stops(BTC)] == [95.0]
    fake.fail("POST", "/contract/private/cancel-plan-order", "429", times=1)
    c.cancel_algo(algo_id=st["algoId"])
    assert not fake.live_stops(BTC)


def test_review_fixes_state_sign_trigger_income_and_server_errors():
    c, fake, _ = make()
    ready(c, fake)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs6r6")
    fake.plans[st["algoId"]]["state"] = 4                    # a finished row still in the list: never a covering stop
    assert live_stops(c, BTC) == [] and c.algo_order(algo_id=st["algoId"])["algoStatus"] != "NEW"
    fake.plans[st["algoId"]]["state"] = 1
    fake.plans[st["algoId"]]["trigger_price"] = ""          # a resting stop without its level: an error, never 0
    with pytest.raises(TransientError):
        live_stops(c, BTC)
    fake.plans[st["algoId"]]["trigger_price"] = "95"
    # income: rows of other kinds (a server that ignores flow_type) are never booked as transfers or funding
    fake.flows.append({"symbol": BTC, "type": "Realized PNL", "flow": 1, "amount": "-300", "asset": "USDT",
                       "account": "futures", "time": str(T0 + 1), "tran_id": "9"})
    assert c.income(None, None, T0, T0 + 10) == []
    # a 5xx carrying an unknown code: an unknown outcome, never a refusal
    real = fake.__call__

    def five(method, url, headers, body):
        if url.endswith("submit-tp-sl-order") and not getattr(five, "done", False):
            five.done = True
            real(method, url, headers, body)
            return 500, json.dumps({"code": 50000, "message": "Bad Request"}).encode(), {}
        return real(method, url, headers, body)
    c.send = five
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 96.0, 5.0, client_id="pbAs7r7")
    c.send = real
    fake.fails.clear()
    # a short read with a negative amount and position_type 2 stays a short
    c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbAx2")
    c.market(BTC, "SELL", 2.0, client_id="pbAs8")
    orig = fake._route

    def neg(m, path, query, body):
        st_, raw, h = orig(m, path, query, body)
        if path == "/contract/private/position":
            d = json.loads(raw)
            for r in d["data"]:
                r["current_amount"] = "-" + r["current_amount"]
            raw = json.dumps(d).encode()
        return st_, raw, h
    fake._route = neg
    assert float(c.position(BTC)["positionAmt"]) == -2.0
