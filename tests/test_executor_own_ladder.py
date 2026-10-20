"""거래소 기준 익절 (owners 10-20, "거래소 기준으로 익절해야지"): with ``"ladder_from": "own"`` each executor judges the
take-profit ladder on ITS OWN position: its own fill, its own exchange's 1m candles (last price) and its own exchange's
costs, never the paper's lock steps. The unchanged entry and first stop, the paper's REV only before the live position's
own first lock, a paper exit at a price level leaving the live position on its own stop and ladder, restarts, never a
looser stop, failed stop moves tried again. The DOGE case of 10-20 in exact numbers on the fake Bybit and MEXC.

Every world runs the real executor (paperbot/executor.py) on a fake exchange (tests/fakefutures.py, fakebybit.py,
fakemexc.py: their 1m candles are built from every set_price) and a real paper database (paperbot.store3, read through
Paper3Source as cmd_run builds it). No network."""

from __future__ import annotations

import dataclasses
import json
import socket
from pathlib import Path

import pytest

from fakebybit import FakeBybit
from fakefutures import FakeFutures
from fakemexc import FakeMexc
from paperbot import mexc as MX
from paperbot import risk as R
from paperbot.bybit import BybitClient
from paperbot.executor import ExecConfig, ExecStore, Executor, Paper3Source, main
from paperbot.ladder import net_roe, roe_price
from paperbot.ladder2 import ComboLadder
from paperbot.mainnet import FLAG, FLAG_VALUE
from paperbot.models import TradeRecord
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3
from paperbot.testnet import TestnetClient, round_stop

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy"
T0 = 1_800_000_000_000                         # a minute boundary
MIN = 60_000
ACC = "COMBO@mix"
BTC, DOGE = "BTCUSDT", "DOGEUSDT"
LADDER = {"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03}
SPEC = ComboLadder.of(LADDER)
PAPER_RT = 0.0014                              # the paper rules' round trip (taker 0.05 % + slippage 0.02 %, both sides)
BYBIT_RT = 2 * (0.00055 + 0.0002)              # 0.15 %
MEXC_RT = 2 * (0.0008 + 0.0002)                # 0.20 %
BINANCE_RT = 2 * (0.0005 + 0.0002)             # 0.14 %
COSTS = {"bybit": {"taker_fee": 0.00055, "slippage": 0.0002}, "mexc": {"taker_fee": 0.0008, "slippage": 0.0002}}
BYBIT_ENV = {"BYBIT_TESTNET_API_KEY": "k", "BYBIT_TESTNET_API_SECRET": "s"}
MEXC_ENV = {FLAG: FLAG_VALUE, "MEXC_LIVE_KEY": "mk", "MEXC_LIVE_SECRET": "ms", MX.KEY_CHECKED: MX.KEY_CHECKED_VALUE}


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


def paper_stop(side: int, entry: float, lev: int, roe: float = 0.5) -> float:
    """The paper's net-ROE stop (combo.py ``stop: {"mode": "roe", "net": true}``)."""
    return entry * (1 - side * (roe / lev - PAPER_RT))


class Paper:
    """The paper bot's database (store3 schema, COMBO@mix) as paperbot/combo.py writes it: its open position, and the
    trade record it writes in the same commit as the position goes."""

    def __init__(self, path: str, clock: Clock):
        self.path, self.clock, self.s = path, clock, Store3(path)
        self.s.add_account(ACC, "combo", "mix", "combo", clock.t, "combo-v2")
        self.pos = None
        self.put(None)

    def put(self, symbol=None, side=1, entry=100.0, lev=20, stop=None, entry_time=None, qty=1.0, lock=None):
        self.pos = None if symbol is None else {
            "symbol": symbol, "side": side, "qty": qty, "leverage": lev, "stop_price": stop, "stop_initial": stop,
            "entry_price": entry, "entry_time": entry_time, "lock_roe": lock, "signal": {}}
        self.s.put_state("accounts", self.clock.t - 20_000, {"last_ts": self.clock.t - 20_000, "engines": {
            ACC: {"wallet": 1000.0, "position": self.pos, "pending": []}}})
        self.s.commit()

    def lock(self, stop: float, lock: float) -> None:
        self.put(**{**self._args(), "stop": stop, "lock": lock})

    def _args(self) -> dict:
        p = self.pos
        return {"symbol": p["symbol"], "side": p["side"], "entry": p["entry_price"], "lev": p["leverage"],
                "stop": p["stop_price"], "entry_time": p["entry_time"], "qty": p["qty"], "lock": p["lock_roe"]}

    def exit(self, reason: str, price: float, record: bool = True) -> None:
        """The paper closes its position (paperbot/engine.py _finish): the trade record, then no position."""
        p = self.pos
        if record:
            side, entry = p["side"], p["entry_price"]
            pnl = side * p["qty"] * (price - entry)
            margin = p["qty"] * entry / p["leverage"]
            self.s.trade(ACC, TradeRecord(
                strategy_id="V39_ALL", symbol=p["symbol"], timeframe="1h", side=side, signal_ts=p["entry_time"] - 1,
                entry_time=p["entry_time"], entry_price=entry, exit_time=self.clock.t - 1_000, exit_price=price,
                exit_reason=reason, qty=p["qty"], leverage=p["leverage"], tier="best", margin=margin,
                stop_price=p["stop_price"], tp_price=float("nan"), liq_price=0.0, fees=0.0, funding=0.0, pnl=pnl,
                roe=pnl / margin, price_move=side * (price / entry - 1), mae_price=entry, mfe_price=entry,
                equity_after=1000.0 + pnl, score=3.0, stop_initial=p["stop_initial"], lock_roe=p["lock_roe"]))
        self.put(None)

    def close(self):
        self.s.close()


class Rig:
    """One executor on one fake exchange, following ``Paper`` through Paper3Source (as cmd_run builds it)."""

    def __init__(self, tmp_path, exchange="binance", ladder_from="own", prices=None, symbols=(BTC, "ETHUSDT"),
                 ladder=LADDER, net_costs=None, clock=None, paper=None, **cfg_kw):
        self.tmp, self.exchange = Path(tmp_path), exchange
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.clock = clock or Clock()
        self.own_paper = paper is None                 # closed with the rig (a shared one is the caller's)
        self.paper = paper or Paper(str(self.tmp / "live-ac.db"), self.clock)
        if exchange == "binance":
            self.fake = FakeFutures(prices=prices or {BTC: 10_000.0, "ETHUSDT": 50.0, "SOLUSDT": 10.0})
        elif exchange == "bybit":
            self.fake = FakeBybit(prices=prices or {BTC: 10_000.0, "ETHUSDT": 50.0})
        else:
            self.fake = FakeMexc(prices=prices, wallet=100.0)
        self.fake.clock = self.clock
        self.note = ListNotifier()
        live = exchange == "mexc"
        risk = R.RiskConfig(max_leverage=40, max_notional_usd=10_000.0, max_loss_frac=0.35,
                            allowed_symbols=tuple(symbols), kill_file=str(self.tmp / "STOP"))
        self.cfg = ExecConfig(account=ACC, paper_db=self.paper.path, db=str(self.tmp / f"exec-{exchange}.db"),
                              qty_scale=0.1, risk=risk, exchange=exchange, mode="mainnet" if live else "testnet",
                              budget_usd=100.0 if live else None, sweep_every=1,
                              paper_env_file=str(self.tmp / "live.env"), ladder_from=ladder_from, ladder=ladder,
                              net_costs=net_costs, **cfg_kw)
        self.store = None
        self.open()

    def clients(self):
        kw = dict(send=self.fake, clock_ms=self.clock)
        if self.exchange == "binance":
            return TestnetClient("k", "s", **kw), None, None
        if self.exchange == "bybit":
            return BybitClient("k", "s", sleep=lambda s: None, **kw), None, BYBIT_ENV
        return (MX.MexcClient("mk", "ms", sleep=lambda s: None, **kw),
                MX.MexcKeyCheckClient("mk", "ms", attested=True, sleep=lambda s: None, **kw), MEXC_ENV)

    def open(self):
        self.store = ExecStore(self.cfg.db)
        client, keycheck, env = self.clients()
        self.ex = Executor(self.cfg, client, Paper3Source(self.cfg.paper_db, ACC), self.store, self.note,
                           now_ms=self.clock, sleep=lambda s: None, keycheck=keycheck, env=env)
        self.ex.start()
        return self.ex

    def restart(self, **change):
        self.store.close()
        if change:
            self.cfg = dataclasses.replace(self.cfg, **change)
        return self.open()

    def close(self):
        self.store.close()
        if self.own_paper:
            self.paper.close()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def next_minute(self):
        """Into the next minute (the fill's own minute counts only its close: its high may predate the fill)."""
        self.clock.t += MIN - self.clock.t % MIN + 1_000

    def sym(self, symbol):
        return symbol.replace("USDT", "_USDT") if self.exchange == "mexc" else symbol

    def price(self, symbol, *prices):
        for p in prices:
            self.fake.set_price(self.sym(symbol), p)

    def stops(self, symbol=BTC):
        s = self.sym(symbol)
        if self.exchange == "binance":
            return sorted(float(o["triggerPrice"]) for o in self.fake.live_stops(s))
        if self.exchange == "bybit":
            return sorted(float(o["triggerPrice"]) for o in self.fake.live_stops(s))
        return sorted(float(p["triggerPrice"]) for p in self.fake.live_plans(s))

    def amt(self, symbol=BTC):
        s = self.sym(symbol)
        if self.exchange == "mexc":
            return float(self.fake.amt(s))
        return float(self.fake.pos[s])

    def kline_calls(self):
        return [c for c in self.fake.calls if c[1] in ("/fapi/v1/klines", "/v5/market/kline")
                or c[1].startswith("/api/v1/contract/kline/")]

    def events(self, kind):
        return [(lv, txt, json.loads(d)) for lv, txt, d in self.store.conn.execute(
            "SELECT level, text, data FROM events WHERE kind = ? ORDER BY id", (kind,))]

    def trades(self):
        return self.store.conn.execute("SELECT key, exit_reason, exit_ts IS NOT NULL, data FROM trades ORDER BY entry_ts"
                                       ).fetchall()

    def own(self):
        return (self.ex.trade or {}).get("own")

    def enter(self, symbol=BTC, side=1, entry=10_000.0, lev=20, qty=1.0, stop=None, fill=None):
        """The paper enters (just now); the exchange's price is ``fill``; one loop follows it."""
        if fill is not None:
            self.price(symbol, fill)
        stop = stop if stop is not None else paper_stop(side, entry, lev)
        self.paper.put(symbol, side, entry, lev, stop, self.clock.t - 30_000, qty)
        self.loop()
        assert self.ex.trade is not None and self.ex.trade["status"] == "open", self.events("entry_check")


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    r.close()


# ====================================================================== the config
def test_check_config_validates_the_own_ladder_and_says_it_in_words(tmp_path, capsys):
    base = json.loads((DEPLOY / "executor.live-bybit.json").read_text(encoding="utf-8"))
    base.update(db=str(tmp_path / "x.db"), risk={**base["risk"], "kill_file": str(tmp_path / "STOP")})

    def check(**change):
        d = {**base, **change}
        d = {k: v for k, v in d.items() if v is not None}
        p = tmp_path / "c.json"
        p.write_text(json.dumps(d), encoding="utf-8")
        rc = main(["check-config", "--config", str(p)])
        return rc, capsys.readouterr().out.strip().splitlines()

    rc, lines = check()
    assert rc == 0 and lines[-1] == "준비됨"
    assert lines[0].startswith("익절(계단 잠금): 거래소 기준 - 이 실행기의 체결가, 이 거래소의 1분봉 고가·저가")
    assert lines[1] == "계단: 순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%)"
    assert lines[2] == "기준(ladder_basis \"net\"): 순ROE - 수수료·슬리피지 왕복을 뺀 ROE (페이퍼와 같은 정의)"
    assert lines[3] == "순ROE 비용: 바이비트 테이커 0.055% + 슬리피지 0.02% (한쪽), 왕복 0.15%, 펀딩은 계산에 넣지 않음"
    assert "빠른 청산(반대 신호)은 자기 첫 잠금 전에만 따름" in lines[4]
    rc, lines = check(exchange="mexc")
    assert rc == 0 and "순ROE 비용: MEXC 테이커 0.08% + 슬리피지 0.02% (한쪽), 왕복 0.2%, 펀딩은 계산에 넣지 않음" in lines
    # "own" without a ladder, with a broken one, unknown keys, bad costs: refused
    rc, lines = check(ladder=None)
    assert rc == 1 and any("ladder_from \"own\"(거래소 기준 익절)은 ladder" in ln for ln in lines)
    rc, lines = check(ladder={**LADDER, "next_gap": None})
    assert rc == 1 and any("next_trigger와 next_gap은 둘 다" in ln for ln in lines)
    rc, lines = check(ladder={**LADDER, "first_lock": "0.1"})
    assert rc == 1 and any("first_lock는 숫자" in ln for ln in lines)
    rc, lines = check(ladder={**LADDER, "lock": 0.1})
    assert rc == 1 and any("ladder에 모르는 항목: lock" in ln for ln in lines)
    rc, lines = check(ladder={**LADDER, "next_trigger": 0.105})
    assert rc == 1 and any("next_trigger는 첫 잠금이 걸리는 순ROE" in ln for ln in lines)
    rc, lines = check(net_costs={"bybit": {"taker_fee": 0.055, "slippage": 0.0002}})
    assert rc == 1 and any("net_costs의 bybit" in ln for ln in lines)
    rc, lines = check(net_costs={"okx": {"taker_fee": 0.0005, "slippage": 0.0002}})
    assert rc == 1 and any("net_costs의 거래소 'okx'" in ln for ln in lines)
    rc, lines = check(ladder_from="exchange")
    assert rc == 1 and any("ladder_from은 \"paper\"" in ln for ln in lines)
    rc, lines = check(ladder_basis="screen")
    assert rc == 1 and any("ladder_basis는 \"net\"" in ln for ln in lines)
    # "gross" (owners 10-20, a later choice): the screen's ROE; what a first lock leaves after the costs, per coin
    rc, lines = check(ladder_basis="gross", ladder={"first_lock": 0.12, "trigger_gap": 0.01, "step": 0.05})
    assert rc == 0 and lines[1] == "계단: 화면 ROE 13%에서 12% 잠금, 이후 5%씩"
    assert lines[2].startswith("기준(ladder_basis \"gross\"): 화면 ROE - 거래소 앱에 보이는 수수료 전 ROE")
    assert lines[3] == "비용(참고): 바이비트 테이커 0.055% + 슬리피지 0.02% (한쪽), 왕복 0.15%"
    # 12 % - 40 x 0.15 % = 6 %, 12 % - 30 x 0.15 % = 7.5 %
    assert lines[4] == ("첫 잠금 화면 +12%가 남기는 순ROE: BTC 40배 +6.0%, ETH·SOL·DOGE·LTC·BCH 30배 +7.5% "
                        "(잠금 - 배수 × 왕복 비용 0.15%)")
    rc, lines = check(exchange="mexc", ladder_basis="gross")
    assert rc == 0 and ("첫 잠금 화면 +10%가 남기는 순ROE: BTC 40배 +2.0%, ETH·SOL·DOGE·LTC·BCH 30배 +4.0% "
                        "(잠금 - 배수 × 왕복 비용 0.2%)") in lines
    rc, lines = check(exchange="mexc", ladder_basis="gross",
                      ladder={"first_lock": 0.05, "trigger_gap": 0.01, "step": 0.05})
    assert rc == 0 and any("BTC 40배 -3.0% (손실을 잠금)" in ln for ln in lines)
    # without net_costs the exchange's default numbers (the same as the live configs')
    rc, lines = check(net_costs=None)
    assert rc == 0 and "순ROE 비용: 바이비트 테이커 0.055% + 슬리피지 0.02% (한쪽), 왕복 0.15%, 펀딩은 계산에 넣지 않음" in lines
    # an old config: the paper's lock steps, as before
    old = {k: v for k, v in base.items() if k not in ("ladder_from", "ladder", "net_costs")}
    cfg = ExecConfig.from_dict(old)
    assert (cfg.ladder_from, cfg.ladder, cfg.net_costs) == ("paper", None, None) and cfg.problems() == []
    rc, lines = check(ladder_from=None, ladder=None, net_costs=None)
    assert rc == 0 and lines[0] == "익절(계단 잠금): 페이퍼 기준 - paper의 잠금을 따라 손절을 옮김 (stop_from \"ratio\": 체결가 비율)"


def test_each_live_executor_runs_the_ladder_of_the_paper_bot_it_follows():
    """deploy/executor.live-*.json: "ladder_from": "own" with the 규칙봇 15 ladder, the same as the combo config of the
    paper bot each one follows (its paper_db is that config's own db), and both exchanges' costs."""
    combos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DEPLOY.glob("combo.live15*.json"))]
    for name in ("executor.live-bybit.json", "executor.live-mexc.json"):
        d = json.loads((DEPLOY / name).read_text(encoding="utf-8"))
        combo = next(c for c in combos if c["db"] == d["paper_db"])
        assert d["ladder_from"] == "own" and d["ladder"] == combo["ladder"] == LADDER
        assert d["net_costs"] == COSTS and d["ladder_basis"] == "net"          # "gross" is the owners' later choice
        cfg = ExecConfig.from_dict(d)
        assert cfg.problems() == [] and cfg.ladder_spec() == SPEC
        assert cfg.own_round_trip() == pytest.approx(BYBIT_RT if d["exchange"] == "bybit" else MEXC_RT)


# ====================================================================== the DOGE case of 10-20
DOGE_PAPER_ENTRY, DOGE_TOP = 0.07937, 0.07974


def doge(tmp_path, exchange: str, ladder_from: str, fill: float, **kw) -> Rig:
    prices = {DOGE: fill, BTC: 10_000.0} if exchange == "bybit" else None
    r = Rig(tmp_path, exchange=exchange, ladder_from=ladder_from, prices=prices, symbols=(DOGE,), net_costs=COSTS, **kw)
    r.enter(DOGE, 1, DOGE_PAPER_ENTRY, 30, qty=50_000.0, fill=fill)
    return r


@pytest.mark.parametrize("exchange,fill,rt,after,lock_px", [
    ("bybit", 0.07924, BYBIT_RT, 0.07964, 0.07963),
    ("mexc", 0.07925, MEXC_RT, 0.07969, 0.07968)])
def test_the_doge_long_locks_on_each_exchanges_own_fill(tmp_path, exchange, fill, rt, after, lock_px):
    """10-20: paper entry 0.07937, Bybit filled 0.07924, MEXC 0.07925, the exchanges topped at 0.07974. The paper's first
    trigger (net ROE +11 % from ITS entry with ITS costs) was 0.07977: nothing locked. Judged on each exchange's own fill
    and costs both are past +11 % and lock +10 %."""
    paper_trigger = roe_price(1, DOGE_PAPER_ENTRY, 30, 0.11, PAPER_RT)
    assert paper_trigger == pytest.approx(0.0797721, abs=1e-7) and round(paper_trigger, 5) == 0.07977 > DOGE_TOP
    r = doge(tmp_path, exchange, "own", fill)
    try:
        t = r.ex.trade
        assert t["entry_price"] == pytest.approx(fill) and t["own"]["lock"] is None
        first = t["stop_initial"]
        assert first == round_stop(fill * paper_stop(1, DOGE_PAPER_ENTRY, 30) / DOGE_PAPER_ENTRY, 0.00001, 1)  # "ratio"
        trigger = roe_price(1, fill, 30, 0.11, rt)
        assert trigger < DOGE_TOP
        r.next_minute()
        r.price(DOGE, DOGE_TOP, after)               # the top between two loops: only the 1m candle's high shows it
        assert net_roe(1, fill, after, 30, rt) < 0.11  # the price the loop sees would not lock
        r.loop()
        o = r.ex.trade["own"]
        best_roe = 30 * (DOGE_TOP / fill - 1 - rt)
        assert o["best"] == DOGE_TOP and o["best_roe"] == pytest.approx(best_roe) and o["src"] == "kline"
        assert o["lock"] == pytest.approx(0.10) and best_roe < 0.15               # +10 %, not yet the 15 % step
        want = round_stop(roe_price(1, fill, 30, 0.10, rt), 0.00001, 1)
        assert want == lock_px and r.ex.trade["stop"] == lock_px and r.stops(DOGE) == [lock_px]
        assert o["next"]["lock"] == pytest.approx(0.12) and o["next"]["at"] == pytest.approx(0.15)
        assert o["next"]["price"] == pytest.approx(fill * (1 + 0.15 / 30 + rt))
        (lv, text, data), = r.events("own_lock")
        assert lv == "INFO" and data["lock"] == pytest.approx(0.1) and data["stop"] == lock_px and data["old"] == first
        assert f"거래소 기준 잠금 +10% (자기 체결가 기준): 체결 {fill:g}, 거래소 최고 {DOGE_TOP:g}" in text
        # the paper never locked and never moves the live stop
        r.loop(2)
        assert r.stops(DOGE) == [lock_px]
        # the price falls through the lock: the exchange stop closes it, booked as a stop that fired
        r.price(DOGE, lock_px - 0.00002)
        r.loop()
        assert r.amt(DOGE) == 0 and r.ex.trade is None
        (_k, why, closed, data), = r.trades()
        assert closed and "발동" in why and json.loads(data)["own"]["lock"] == pytest.approx(0.1)
    finally:
        r.close()


@pytest.mark.parametrize("exchange,fill,ladder,after,lock,lock_px", [
    # the 규칙봇 15 ladder on the screen's ROE: 30 x (0.07974 / fill - 1) = +18.9 % (Bybit) / +18.5 % (MEXC):
    # past 15 % -> 12 %
    ("bybit", 0.07924, LADDER, 0.07960, 0.12, 0.07956),
    ("mexc", 0.07925, LADDER, 0.07960, 0.12, 0.07957),
    # the owners' question (10-20): "화면 13% -> 12%, then steps": 13 % -> 12 %, 18 % -> 17 %, ...
    ("bybit", 0.07924, {"first_lock": 0.12, "trigger_gap": 0.01, "step": 0.05}, 0.07970, 0.17, 0.07969),
    ("mexc", 0.07925, {"first_lock": 0.12, "trigger_gap": 0.01, "step": 0.05}, 0.07971, 0.17, 0.07970)])
def test_the_doge_long_on_the_gross_basis(tmp_path, exchange, fill, ladder, after, lock, lock_px):
    """``"ladder_basis": "gross"``: best, triggers and lock prices before fees (the exchange screen's ROE): lock price
    = fill x (1 + lock / leverage), no cost term; the ladder's trigger -> lock on that scale."""
    r = doge(tmp_path, exchange, "own", fill, ladder=ladder, ladder_basis="gross")
    try:
        spec = ComboLadder.of(ladder)
        gross = 30 * (DOGE_TOP / fill - 1)
        assert spec.lock_for(gross) == pytest.approx(lock)
        r.next_minute()
        r.price(DOGE, DOGE_TOP, after)
        r.loop()
        o = r.ex.trade["own"]
        assert o["basis"] == "gross" and o["rt"] == 0.0 and o["cost_rt"] == pytest.approx(BYBIT_RT if exchange == "bybit"
                                                                                          else MEXC_RT)
        assert o["best"] == DOGE_TOP and o["best_roe"] == pytest.approx(gross) and o["lock"] == pytest.approx(lock)
        assert round_stop(fill * (1 + lock / 30), 0.00001, 1) == lock_px == r.stops(DOGE)[0] == r.ex.trade["stop"]
        (_lv, text, data), = r.events("own_lock")
        assert data["basis"] == "gross" and f"거래소 기준 잠금 화면 +{lock:.0%} (자기 체결가 기준)" in text and "화면 ROE +" in text
        # what it leaves after the exchange's costs: lock - 30 x round trip
        assert net_roe(1, fill, lock_px, 30, o["cost_rt"]) == pytest.approx(lock - 30 * o["cost_rt"], abs=0.004)
    finally:
        r.close()


@pytest.mark.parametrize("exchange,fill", [("bybit", 0.07924), ("mexc", 0.07925)])
def test_the_doge_long_with_the_paper_ladder_never_locks(tmp_path, exchange, fill):
    """The same prices with "ladder_from": "paper" (the old configs): the paper did not lock, so neither does the
    executor; it never reads its own candles."""
    r = doge(tmp_path, exchange, "paper", fill)
    try:
        first = r.ex.trade["stop"]
        r.next_minute()
        r.price(DOGE, DOGE_TOP, fill + 0.0004)
        r.loop(3)
        assert r.stops(DOGE) == [first] and "own" not in r.ex.trade and not r.events("own_lock")
        assert r.kline_calls() == []
    finally:
        r.close()


# ====================================================================== the ladder, step by step
def test_a_long_climbs_the_ladder_on_its_own_fill_and_ignores_the_papers_steps(rig):
    rig.enter(BTC, 1, 9_990.0, 20, qty=0.5, fill=10_000.0)             # the paper filled 10 lower than the exchange
    t = rig.ex.trade
    assert t["entry_price"] == 10_000.0 and t["own"]["fill_ms"] == T0 + 3_000
    rt = BINANCE_RT
    steps = [(10_070.0, 0.10, 10_064.0), (10_090.0, 0.12, 10_074.0), (10_115.0, 0.17, 10_099.0),
             (10_141.0, 0.22, 10_124.0), (10_165.0, 0.27, 10_149.0)]
    for top, lock, px in steps:
        assert round_stop(roe_price(1, 10_000.0, 20, lock, rt), 0.1, 1) == px
        rig.next_minute()
        rig.price(BTC, top)
        rig.loop()
        assert rig.ex.trade["own"]["lock"] == pytest.approx(lock), top
        assert rig.stops() == [px] and rig.ex.trade["stop"] == px
    # the paper's own lock steps (on ITS entry) move nothing
    rig.paper.lock(stop=10_160.0, lock=0.27)
    rig.loop(2)
    assert rig.stops() == [10_149.0]
    assert [round(e[2]["lock"], 2) for e in rig.events("own_lock")] == [0.1, 0.12, 0.17, 0.22, 0.27]


def test_a_short_locks_below_its_own_fill(tmp_path):
    r = Rig(tmp_path)
    try:
        r.enter(BTC, -1, 10_010.0, 20, qty=0.5, fill=10_000.0)
        rt = BINANCE_RT
        first = r.ex.trade["stop"]
        assert first > 10_000.0
        r.next_minute()
        r.price(BTC, 9_930.0, 9_934.0)                # the low between loops: -0.7 % = +11.2 % net
        r.loop()
        o = r.ex.trade["own"]
        assert o["best"] == 9_930.0 and o["best_roe"] == pytest.approx(20 * (1 - 9_930.0 / 10_000.0 - rt))
        px = round_stop(roe_price(-1, 10_000.0, 20, 0.10, rt), 0.1, -1)
        assert px == 9_936.0 and r.stops() == [9_936.0] and o["lock"] == pytest.approx(0.1)
        r.next_minute()
        r.price(BTC, 9_910.0)                           # +15.2 %: 12 %
        r.loop()
        assert r.stops() == [round_stop(roe_price(-1, 10_000.0, 20, 0.12, rt), 0.1, -1)] == [9_926.0]
        r.price(BTC, 9_927.0)                           # back up through the lock: the stop buys it back
        r.loop()
        assert r.amt() == 0 and r.ex.trade is None and "발동" in r.trades()[0][1]
    finally:
        r.close()


def test_the_fill_minutes_high_does_not_count_but_its_close_does(rig):
    """The fill's own 1m candle may hold prices from before the fill: only its close (sampled every loop) counts."""
    rig.price(BTC, 10_080.0)                            # before the fill, in the same minute
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.loop()
    assert rig.ex.trade["own"]["best"] == 10_000.0 and rig.ex.trade["own"]["lock"] is None
    rig.price(BTC, 10_072.0)                            # still the fill minute: its close now
    rig.loop()
    assert rig.ex.trade["own"]["best"] == 10_072.0 and rig.ex.trade["own"]["lock"] == pytest.approx(0.1)


# ====================================================================== restarts
def test_a_restart_keeps_best_and_lock_and_reads_the_minutes_it_missed(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_092.0, 10_080.0)                  # +15.6 %: 12 %
    rig.loop()
    assert rig.ex.trade["own"]["lock"] == pytest.approx(0.12) and rig.stops() == [10_074.0]
    saved = json.loads(rig.store.conn.execute("SELECT data FROM state WHERE k = 'bot'").fetchone()[0])["trade"]["own"]
    assert saved["lock"] == pytest.approx(0.12) and saved["best"] == 10_092.0
    rig.store.close()
    # while it is off: a spike to +20.4 % and back
    rig.clock.t += 5 * MIN
    rig.price(BTC, 10_116.0, 10_101.0)
    rig.clock.t += 2 * MIN
    rig.open()
    assert rig.ex.trade["own"]["lock"] == pytest.approx(0.12) and rig.ex.trade["own"]["best"] == 10_092.0
    rig.loop()
    assert rig.ex.trade["own"]["best"] == 10_116.0 and rig.ex.trade["own"]["lock"] == pytest.approx(0.17)
    assert rig.stops() == [10_099.0]
    # restarted again with the price lower: nothing locks lower, the stop stays
    rig.restart()
    rig.price(BTC, 10_100.0)
    rig.loop(2)
    assert rig.ex.trade["own"]["lock"] == pytest.approx(0.17) and rig.stops() == [10_099.0]


def test_a_position_from_before_the_switch_starts_its_ladder_from_its_entry(tmp_path):
    """Switched from "paper" to "own" with a position open (the guide says not to: only at 포지션: null): the ladder
    starts from the entry's send time, reads the candles since then, and only ever tightens."""
    r = Rig(tmp_path, ladder_from="paper")
    try:
        r.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
        r.next_minute()
        r.price(BTC, 10_070.0, 10_066.0)
        r.loop()
        first = r.ex.trade["stop"]
        assert r.stops() == [first] and "own" not in r.ex.trade
        r.restart(ladder_from="own", ladder=LADDER)
        r.loop()
        assert r.ex.trade["own"]["best"] == 10_070.0 and r.stops() == [10_064.0]
    finally:
        r.close()


# ====================================================================== paper exits
def test_the_paper_closes_on_its_lock_the_live_position_stays_and_exits_on_its_own_stop(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_070.0)
    rig.loop()
    assert rig.stops() == [10_064.0]
    # the paper locked on its own prices and its lock stop closed it (LOCK): the live position stays
    rig.paper.lock(stop=10_064.0, lock=0.10)
    rig.loop()
    rig.paper.exit("LOCK", 10_064.0)
    orders = len([c for c in rig.fake.calls if c[1] == "/fapi/v1/order" and c[0] == "POST"])
    rig.loop(3)
    assert rig.amt() == 0.05 and rig.ex.trade is not None and rig.stops() == [10_064.0]
    assert len([c for c in rig.fake.calls if c[1] == "/fapi/v1/order" and c[0] == "POST"]) == orders   # no close sent
    assert rig.ex.trade["paper_exit"]["action"] == "stay" and rig.ex.trade["paper_exit"]["reason"] == "LOCK"
    (lv, text, _d), = rig.events("own_stay")
    assert lv == "INFO" and "paper가 계단 익절로 닫았습니다 → 거래소 기준으로 계속 들고 갑니다" in text
    # it keeps climbing its own ladder after the paper is gone, then its own stop closes it
    rig.next_minute()
    rig.price(BTC, 10_095.0)
    rig.loop()
    assert rig.stops() == [10_074.0] and rig.ex.trade["own"]["lock"] == pytest.approx(0.12)
    rig.price(BTC, 10_073.0)
    rig.loop()
    assert rig.amt() == 0 and rig.ex.trade is None
    key, why, closed, data = rig.trades()[0]
    assert closed and why == "거래소 손절(또는 잠금) 발동" and json.loads(data)["paper_exit"]["action"] == "stay"
    rig.loop(2)
    assert rig.amt() == 0 and len(rig.trades()) == 1                    # the same paper position is never re-entered


@pytest.mark.parametrize("reason", ["SL", "LIQ", "TP"])
def test_every_price_exit_of_the_paper_leaves_the_live_position_on_its_own_stop(tmp_path, reason):
    r = Rig(tmp_path)
    try:
        r.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
        first = r.ex.trade["stop"]
        r.paper.exit(reason, 9_920.0)
        r.loop(2)
        assert r.amt() == 0.05 and r.stops() == [first] and r.ex.trade["paper_exit"]["action"] == "stay"
        r.price(BTC, first - 1)
        r.loop()
        assert r.amt() == 0 and "발동" in r.trades()[0][1]
    finally:
        r.close()


def test_rev_before_its_own_first_lock_is_followed(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_050.0)                                            # +8.6 %: no lock of its own yet
    rig.loop()
    assert rig.ex.trade["own"]["lock"] is None
    rig.paper.exit("REV", 10_050.0)
    rig.loop()
    assert rig.amt() == 0 and rig.ex.trade is None
    key, why, closed, _d = rig.trades()[0]
    assert closed and why == "paper 청산 → 거래소 포지션 닫기 (paper 빠른 청산(반대 신호), 자기 첫 잠금 전)"


def test_rev_after_its_own_first_lock_is_ignored(rig):
    """The paper had not locked (its entry was worse), so its fast stop was still armed; the live position had locked
    on its own fill: the REV is not followed."""
    rig.enter(BTC, 1, 10_010.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_072.0)
    rig.loop()
    assert rig.ex.trade["own"]["lock"] == pytest.approx(0.1)
    rig.paper.exit("REV", 10_070.0)
    rig.loop(2)
    assert rig.amt() == 0.05 and rig.stops() == [10_064.0] and rig.ex.trade["paper_exit"]["action"] == "stay"
    (_lv, text, _d), = rig.events("own_stay")
    assert "자기 잠금 +10%가 있어 빠른 청산을 따르지 않고" in text


@pytest.mark.parametrize("reason,words", [("HALT", "paper 멈춤 청산"), ("MANUAL", "paper 수동 청산"), ("END", "paper END")])
def test_other_paper_exits_are_followed(tmp_path, reason, words):
    r = Rig(tmp_path)
    try:
        r.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
        r.next_minute()
        r.price(BTC, 10_072.0)
        r.loop()
        assert r.ex.trade["own"]["lock"] == pytest.approx(0.1)          # even with a lock of its own
        r.paper.exit(reason, 10_070.0)
        r.loop()
        assert r.amt() == 0 and r.trades()[0][1] == f"paper 청산 → 거래소 포지션 닫기 ({words})"
    finally:
        r.close()


def test_a_paper_exit_without_a_record_waits_then_follows(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.paper.exit("SL", 9_900.0, record=False)
    rig.loop(5)                                                        # 15 s: waits, the exchange stop protects
    assert rig.amt() == 0.05 and rig.events("paper_exit_wait")
    rig.loop(6)
    assert rig.amt() == 0 and rig.trades()[0][1] == "paper 청산 → 거래소 포지션 닫기 (paper 청산 이유를 못 읽음)"
    assert rig.events("paper_exit_unknown")[0][0] == "WARN"


def test_a_paper_position_that_shows_again_resets_the_wait(rig):
    """A read where the paper position was missing, then the same position again (no trade record): the wait for its
    exit reason starts over the next time it goes."""
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    pos = dict(rig.paper.pos)
    rig.paper.put(None)
    rig.loop(4)
    assert "paper_gone" in rig.ex.trade
    rig.paper.put(pos["symbol"], pos["side"], pos["entry_price"], pos["leverage"], pos["stop_price"], pos["entry_time"],
                  pos["qty"])
    rig.loop()
    assert "paper_gone" not in rig.ex.trade
    rig.paper.put(None)
    rig.loop(5)
    assert rig.amt() == 0.05                                           # 15 s of a new wait, not 27
    rig.loop(6)
    assert rig.amt() == 0


def market_orders(r: Rig) -> int:
    return len([c for c in r.fake.calls if c[1] == "/fapi/v1/order" and c[0] == "POST"])


def test_a_new_paper_entry_while_the_live_position_stays_is_not_followed(rig):
    """Owners 10-20 (decision 1): the live position kept on its own stop and ladder is NEVER closed for the paper's next
    entry. That entry is left out and recorded plainly (a missed signal, INFO: no Telegram); it is never joined later,
    also not once the live position closed on its own stop while the paper still holds it. The next FRESH paper entry
    is followed as before."""
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    stop = rig.ex.trade["stop"]
    rig.paper.exit("SL", 9_900.0)
    rig.loop(2)
    assert rig.amt() == 0.05 and rig.ex.trade["paper_exit"]["action"] == "stay"
    sent = market_orders(rig)
    eth_key = f"{ACC}|ETHUSDT|{rig.clock.t - 20_000}"
    rig.paper.put("ETHUSDT", -1, 50.0, 20, paper_stop(-1, 50.0, 20), rig.clock.t - 20_000, 40.0)
    rig.loop(3)
    # the live position stays, with its stop; nothing was sent to close it; the new entry is not followed
    assert rig.amt() == 0.05 and rig.stops() == [stop] and rig.amt("ETHUSDT") == 0
    assert market_orders(rig) == sent and rig.ex.trade["key"].startswith(f"{ACC}|{BTC}|")
    (lv, text, data), = rig.events("own_busy")                         # recorded once, plainly
    assert lv == "INFO" and data["key"] == eth_key and eth_key in rig.ex.done
    assert "실거래가 아직 자기 포지션(거래소 기준, BTCUSDT 롱)을 들고 있어 이번 진입은 따라가지 않음" in text
    assert not [m for _lv, m in rig.note.messages if "ETHUSDT" in m or "따라가지 않음" in m]
    assert not rig.events("late") and len(rig.trades()) == 1
    # its own stop closes it; the paper still holds ETH (30 s old): never joined
    rig.price(BTC, stop - 1)
    rig.loop()
    assert rig.amt() == 0 and rig.ex.trade is None and "발동" in rig.trades()[0][1]
    rig.loop(2)
    assert rig.amt("ETHUSDT") == 0 and len(rig.trades()) == 1
    # the paper's next, fresh entry is followed
    rig.paper.exit("SL", 50.5)
    rig.price(BTC, 10_000.0)
    rig.paper.put(BTC, 1, 10_000.0, 20, paper_stop(1, 10_000.0, 20), rig.clock.t - 10_000, 0.5)
    rig.loop()
    assert rig.amt() == 0.05 and rig.ex.trade is not None and rig.ex.trade["status"] == "open"
    assert len(rig.trades()) == 2 and len(rig.events("own_busy")) == 1


def test_a_followed_paper_exit_with_a_new_entry_in_the_same_read_closes_then_follows(rig):
    """The paper's own exit of the live position still decides when the paper already holds the next position: a REV
    before the live position's first lock is followed (closed), and the new entry is judged like any entry."""
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.paper.exit("REV", 9_990.0)
    rig.paper.put("ETHUSDT", -1, 50.0, 20, paper_stop(-1, 50.0, 20), rig.clock.t - 10_000, 40.0)
    rig.loop()
    assert rig.amt() == 0 and rig.amt("ETHUSDT") == -4.0 and not rig.events("own_busy")
    first, second = rig.trades()
    assert first[1] == "paper 청산 → 거래소 포지션 닫기 (paper 빠른 청산(반대 신호), 자기 첫 잠금 전)" and not second[2]


def test_a_new_entry_while_the_exit_reason_is_unread_is_not_given_up(rig):
    """The paper position went, its trade record is not readable yet, and the paper already holds the next one: the live
    position waits on its exchange stop (OWN_EXIT_WAIT_S) without closing for the new entry and without giving it up;
    after the wait it follows the paper out, and the new entry (still fresh) is followed."""
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.paper.exit("SL", 9_900.0, record=False)
    rig.paper.put("ETHUSDT", -1, 50.0, 20, paper_stop(-1, 50.0, 20), rig.clock.t - 3_000, 40.0)
    rig.loop(5)
    assert rig.amt() == 0.05 and rig.amt("ETHUSDT") == 0 and not rig.events("own_busy")
    rig.loop(6)
    assert rig.amt() == 0 and rig.amt("ETHUSDT") == -4.0
    assert rig.trades()[0][1] == "paper 청산 → 거래소 포지션 닫기 (paper 청산 이유를 못 읽음)"


# ====================================================================== never looser, failures, candles
def test_a_stop_already_tighter_than_the_lock_is_never_loosened(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_080.0)
    t = rig.ex.trade
    # a tighter stop already on the exchange (a move that reached it before a restart saved it): adopted, kept
    rig.ex._move(t, 10_070.0, [s["algoId"] for s in rig.fake.live_stops(BTC)], "test")
    rig.loop()
    assert rig.ex.trade["own"]["lock"] == pytest.approx(0.1) and rig.stops() == [10_070.0]
    assert rig.ex.trade["own"]["lock_price"] == 10_070.0
    moves = [e for e in rig.events("own_lock")]
    assert moves[0][2]["stop"] == 10_070.0
    # every stop the executor ever set went one way
    levels = [float(o["triggerPrice"]) for o in sorted(rig.fake.algos.values(), key=lambda o: o["algoId"])]
    assert levels == sorted(levels)


def test_a_refused_stop_move_keeps_the_old_stop_and_is_tried_again(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    first = rig.ex.trade["stop"]
    rig.next_minute()
    rig.price(BTC, 10_075.0)
    rig.fake.fail("POST", "/fapi/v1/algoOrder", ("code", -1111, "Precision is over the maximum defined for this asset."))
    rig.loop()
    assert rig.stops() == [first] and rig.ex.trade["own"]["lock"] is None and rig.events("move_failed")
    assert not rig.events("own_lock")
    rig.loop()                                                          # tried again: moved, lock recorded once
    assert rig.stops() == [10_064.0] and rig.ex.trade["own"]["lock"] == pytest.approx(0.1)
    assert len(rig.events("own_lock")) == 1


def test_a_lost_answer_of_the_stop_move_makes_no_second_stop(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_075.0)
    rig.fake.fail("POST", "/fapi/v1/algoOrder", "503_after")             # placed, the answer lost: looked up by its id
    rig.loop()
    assert rig.stops() == [10_064.0] and rig.ex.trade["own"]["lock"] == pytest.approx(0.1)
    rig.loop(2)
    assert rig.stops() == [10_064.0]
    first = next(i for i, c in enumerate(rig.fake.calls) if c[1] == "/fapi/v1/algoOrder" and c[0] == "POST")
    assert [t for t in rig.fake.unprotected_moments(BTC) if t[0] > first] == []      # never without a stop


def test_a_lock_already_past_the_price_closes_at_market(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_075.0, 10_060.0)                                  # armed at 10,075, already back under 10,064
    rig.loop()
    assert rig.amt() == 0 and rig.ex.trade is None
    (_lv, text, data), = rig.events("own_lock")
    assert data["closed"] is True and "시장가로 닫았습니다" in text
    assert "이미 지나" in rig.trades()[0][1]


def test_candles_that_cannot_be_read_use_the_last_price_and_are_read_again(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.next_minute()
    rig.price(BTC, 10_075.0, 10_050.0)                                 # the top between loops
    rig.fake.fail("GET", "/fapi/v1/klines", "503_before", times=4)       # every retry of this loop
    rig.loop()
    o = rig.ex.trade["own"]
    assert o["src"] == "last" and o["best"] == 10_050.0 and o["lock"] is None
    (lv, text, _d), = rig.events("own_prices")
    assert lv == "WARN" and "1분봉을 못 읽어 이번에는 지금 가격 10050만 봅니다" in text
    assert any("1분봉을 못 읽어" in m for _lv, m in rig.note.messages)
    rig.price(BTC, 10_066.0)
    rig.loop()                                                          # read again from the same minute: the top counts
    assert rig.ex.trade["own"]["best"] == 10_075.0 and rig.stops() == [10_064.0]
    assert rig.ex.trade["own"]["src"] == "kline"


@pytest.mark.parametrize("answer", ["empty", "old"])
def test_a_candle_answer_without_recent_minutes_is_not_a_read(rig, answer):
    """An exchange that answers the 1m candles with an empty list (e.g. a time unit it reads otherwise: MEXC's is not
    confirmed live, docs/mexc-ko.md) or with old minutes only (a feed that stopped) must not pass for "the price did
    not move": the ladder would then never lock. The last price stands in (warned), the minutes are read again."""
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    real = rig.fake.klines
    fill_min = rig.ex.trade["own"]["fill_ms"] - rig.ex.trade["own"]["fill_ms"] % MIN
    rig.fake.klines = (lambda s, lo, hi: []) if answer == "empty" else \
        (lambda s, lo, hi: [b for b in real(s, lo, hi) if b[0] <= fill_min])
    rig.clock.t += 3 * MIN
    rig.price(BTC, 10_080.0)                                            # +14.6 % net: lock 10 %
    rig.loop()
    o = rig.ex.trade["own"]
    assert o["src"] == "last" and o["best"] == 10_080.0 and o["lock"] == pytest.approx(0.1)
    assert rig.stops() == [10_064.0]
    (lv, text, _d), = rig.events("own_prices")
    assert lv == "WARN" and "1분봉을 못 읽어 이번에는 지금 가격 10080만 봅니다" in text
    assert ("빈 목록" if answer == "empty" else "마지막 분") in text
    rig.fake.klines = real                                              # readable again: the minutes are read again
    rig.loop()
    assert rig.ex.trade["own"]["src"] == "kline" and rig.ex.trade["own"]["read_min"] > fill_min


def test_long_gaps_are_read_in_pages(rig):
    rig.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
    rig.store.close()
    rig.clock.t += 700 * MIN                                            # off for 11+ hours
    rig.price(BTC, 10_070.0)
    rig.clock.t += 500 * MIN
    rig.price(BTC, 10_055.0)
    rig.open()
    before = len(rig.kline_calls())
    rig.loop()
    assert len(rig.kline_calls()) - before == 3                          # 1,200 minutes in pages of 500
    (_lv, _text, data), = rig.events("own_lock")
    assert data["best"] == 10_070.0 and data["closed"] is True          # the top 700 minutes back was read
    assert rig.amt() == 0 and rig.ex.trade is None                      # its lock (10,064) is above 10,055: closed


def test_the_paper_mode_reads_no_candles_and_follows_the_papers_lock(tmp_path):
    r = Rig(tmp_path, ladder_from="paper", ladder=None)
    try:
        r.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
        r.next_minute()
        r.price(BTC, 10_200.0)
        r.loop()
        first = r.ex.trade["stop"]
        assert r.stops() == [first] and r.kline_calls() == []
        r.paper.lock(stop=10_064.0, lock=0.10)
        r.loop()
        assert r.stops() == [10_064.0] and r.kline_calls() == [] and "own" not in r.ex.trade
        r.paper.exit("LOCK", 10_064.0)
        r.loop()
        assert r.amt() == 0 and r.trades()[0][1] == "paper 청산 → 거래소 포지션 닫기"
    finally:
        r.close()


def test_the_start_record_names_the_rule(rig):
    (start,) = [e for e in rig.events("start")]
    assert "익절 거래소 기준(순ROE 11%에서 10% 잠금" in start[1] and "비용 바이낸스 테이커 0.05%" in start[1]
    assert start[2]["ladder_from"] == "own" and start[2]["ladder"] == LADDER and start[2]["round_trip"] == BINANCE_RT


def test_the_three_adapters_read_1m_candles_oldest_first():
    """testnet.py / bybit.py / mexc.py ``klines``: [(open ms, high, low, close)] of the last price, oldest first, the
    minute still forming included; MEXC's seconds (or milliseconds) both read; a garbled answer is an error."""
    from paperbot.testnet import TransientError
    clock = Clock()
    fb = FakeFutures(prices={BTC: 100.0, "ETHUSDT": 50.0, "SOLUSDT": 10.0})
    by = FakeBybit(prices={BTC: 100.0, "ETHUSDT": 50.0})
    mx = FakeMexc()
    clients = [TestnetClient("k", "s", send=fb, clock_ms=clock), BybitClient("k", "s", send=by, clock_ms=clock),
               MX.MexcClient("mk", "ms", send=mx, clock_ms=clock)]
    for f in (fb, by, mx):
        f.clock = clock
    for f, s in ((fb, BTC), (by, BTC), (mx, "BTC_USDT")):
        f.set_price(s, 101.0)
        f.set_price(s, 102.5)
    clock.t += MIN + 5_000
    for f, s in ((fb, BTC), (by, BTC), (mx, "BTC_USDT")):
        f.set_price(s, 99.0)
        f.set_price(s, 99.5)
    want = [(T0, 102.5, 101.0, 102.5), (T0 + MIN, 99.5, 99.0, 99.5)]
    for c in clients:
        assert c.klines(BTC, T0, clock.t) == want, type(c).__name__
        assert c.klines(BTC, T0 + MIN, clock.t) == want[1:], type(c).__name__
    mx.kline_ms = True
    assert clients[2].klines(BTC, T0, clock.t) == want
    assert [c for c in mx.calls if c[1] == "/api/v1/contract/kline/BTC_USDT"][0][2] == {
        "interval": "Min1", "start": str(T0 // 1000), "end": str(clock.t // 1000)}
    bad = FakeMexc()
    bad.clock = clock
    bad.route = lambda m, path, q: bad._ok({"time": [1, 2], "high": [1.0]})
    with pytest.raises(TransientError):
        MX.MexcClient("mk", "ms", send=bad, clock_ms=clock).klines(BTC, T0, clock.t)


@pytest.mark.parametrize("exchange,path,refusal,fill,top,lock_px", [
    ("bybit", "/v5/order/create", ("ret", 10001, "params error"), 0.07924, 0.07970, 0.07963),
    ("mexc", "/api/v1/private/planorder/place", ("ret", 2002, "Parameter error"), 0.07925, 0.07974, 0.07968)])
def test_a_refused_stop_move_on_bybit_and_mexc_is_tried_again(tmp_path, exchange, path, refusal, fill, top, lock_px):
    """The exchange refuses the new (tighter) stop once: the old stop stays on the exchange, no lock is recorded, the
    next loop places it; the position is never without a stop."""
    r = doge(tmp_path, exchange, "own", fill)
    try:
        first = r.ex.trade["stop"]
        r.next_minute()
        r.price(DOGE, top)
        if exchange == "bybit":
            r.fake.fail("POST", path, refusal, when=lambda q: "triggerPrice" in q)
        else:
            r.fake.fail("POST", path, refusal)
        r.loop()
        assert r.stops(DOGE) == [first] and r.ex.trade["own"]["lock"] is None and r.events("move_failed")
        r.loop()
        assert r.stops(DOGE) == [lock_px] and r.ex.trade["own"]["lock"] == pytest.approx(0.1)
        assert len(r.events("own_lock")) == 1
        first = next(i for i, c in enumerate(r.fake.calls) if c[1] == path and (exchange == "mexc" or "triggerPrice" in c[2]))
        assert [t for t in r.fake.unprotected_moments(r.sym(DOGE)) if t[0] > first] == []
    finally:
        r.close()
