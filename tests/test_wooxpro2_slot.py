"""The fourth live executor, WOO X Pro 2 (owners 10-24, docs/friend-bot-ko.md: a second WOO X Pro account, a friend's,
trades the paper bot '친구 매매법', /var/lib/paperbot/combo/friend.db): the executor's own pieces, the server's files, the
live checks and messages, and the live site.

The executor (on the fake exchange, tests/fakewooxpro.py; no network): its name from its config's ``label``
("[WOO X Pro 2 실거래 실행기]", the first WOO X Pro executor keeps its words); ``own_keys`` (WOO X Pro's API names no
account id, so the account is known by its key: another exchange's key in its environment, a database tied to another
key, a key another executor's database used, all refuse the start before any request, and every executor refuses a key
another database is tied to); 잔고 바닥 (``equity_floor_frac``: no new entry once the balance is at 70 % of the start
recorded at its first run, said once, an open position untouched, until clear-floor) and 원금 회수 안내
(``double_notice``: one message at 2x).

The four-executor world: tests/vwap_site_world.py with 바이비트 and WOO X Pro on the 추세판단 봇 (live-ac.db), 딥코인 on
vwap.db (as tests/test_deepcoin_slot.py), and WOO X Pro 2 on friend.db (a hand-made '친구 매매법' record). With the slot
not installed (no config file, no database) and friend.db absent every answer is as without the slot.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fakewooxpro import FakeWooX  # noqa: E402
from paperbot import executor as E  # noqa: E402
from paperbot import risk as R  # noqa: E402
from paperbot import wooxpro as WX  # noqa: E402
from paperbot.executor import ExecConfig, ExecStore, Executor, Intent, KeyMixup  # noqa: E402
from paperbot.mainnet import FLAG, FLAG_VALUE  # noqa: E402
from paperbot.notify import CRITICAL, INFO, ListNotifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_800_000_000_000
BTC, ETH = "BTCUSDT", "ETHUSDT"
LIVE_ENV = {FLAG: FLAG_VALUE, "WOOXPRO_LIVE_KEY": "wk", "WOOXPRO_LIVE_SECRET": "ws", "WOOXPRO_LIVE_MEMO": "wm",
            WX.KEY_CHECKED: WX.KEY_CHECKED_VALUE}
TEMPLATE = ROOT / "deploy" / "executor.live-wooxpro2.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ================================================================ the executor on the fake exchange
class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Source:
    def __init__(self, clock):
        self.clock, self.intent = clock, None

    def read(self):
        return self.intent, self.clock() - 30_000


def _cfg(tmp_path, db="exec-woox2.db", **kw) -> ExecConfig:
    """The template's rules (no loss-streak, drawdown or daily halt), a test's own files."""
    risk = R.RiskConfig(max_leverage=40, max_notional_usd=50_000.0, max_loss_frac=0.35, allowed_symbols=(BTC, ETH),
                        kill_file=str(tmp_path / "STOP"))
    base = dict(account="COMBO@mix", paper_db=str(tmp_path / "friend.db"), db=str(tmp_path / db), qty_scale=1.0,
                risk=risk, retries=4, sweep_every=1, exchange="wooxpro", mode="mainnet", budget_usd=10_000.0,
                paper_env_file=str(tmp_path / "live.env"), label="WOO X Pro 2", own_keys=True, equity_floor_frac=0.7,
                double_notice=True)
    base.update(kw)
    return ExecConfig(**base)


class World:
    """One WOO X Pro account (the fake exchange) and one executor; ``key``: its access key (the fake checks every
    signature against its own key)."""

    def __init__(self, tmp_path, cfg: ExecConfig = None, fake=None, key="wk", env=None, clock=None, start=True):
        self.clock = clock or Clock()
        self.fake = fake or FakeWooX(wallet=10_000.0, api_key=key)
        self.fake.clock = self.clock
        self.src = Source(self.clock)
        self.note = ListNotifier()
        self.cfg = cfg or _cfg(tmp_path)
        self.store = ExecStore(self.cfg.db)
        kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda s: None)
        self.client = WX.WooXProClient(key, "ws", "wm", **kw)
        self.keycheck = WX.WooXProKeyCheckClient(key, "ws", "wm", attested=True, **kw)
        env = dict(LIVE_ENV, WOOXPRO_LIVE_KEY=key) if env is None else env
        try:
            self.ex = Executor(self.cfg, self.client, self.src, self.store, self.note, now_ms=self.clock,
                               sleep=lambda s: None, keycheck=self.keycheck, env=env)
        except Exception:
            self.store.close()
            raise
        if start:
            self.ex.start()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def paper(self, symbol=BTC, side=1, qty=5.0, lev=35, entry=100.0, stop=99.43):
        et = self.clock.t - 30_000
        self.src.intent = Intent(key=f"COMBO@mix|{symbol}|{et}", symbol=symbol, side=side, qty=qty, leverage=lev,
                                 stop=stop, entry_price=entry, entry_time=et)

    def said(self):
        """What went to Telegram, without the start's standing key note (WOO X Pro reports no key permissions)."""
        return [m for m in self.note.messages if "키 권한을 API로 알려 주지 않습니다" not in m[1]]

    def events(self, kind):
        return [(lv, t) for lv, t in self.store.conn.execute("SELECT level, text FROM events WHERE kind = ? ORDER BY id",
                                                              (kind,))]

    def close(self):
        self.store.close()


def test_the_template_is_the_paper_bot_and_the_safety_the_owners_were_told(tmp_path):
    """deploy/executor.live-wooxpro2.json (the owners' final settings of 10-24): WOO X Pro, its own name, database and
    paper bot (friend.db, COMBO@mix), the other live templates' costs and protections, the paper's ladder (12 % -> 10 %
    locked, then every 5 %) on its own fill, its stop at net ROE -50 % (its own WOO X Pro costs) from its own fill
    (1.3046 % at 35x, the paper's leverage), no signal light, 잔고 바닥 70 %, 원금 회수 안내; the money (budget_usd,
    qty_scale) is left empty so it cannot start before the owners set it."""
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    cfg = ExecConfig.from_file(str(TEMPLATE))
    assert (cfg.exchange, cfg.label, cfg.mode, cfg.account) == ("wooxpro", "WOO X Pro 2", "mainnet", "COMBO@mix")
    assert (cfg.paper_db, cfg.db) == ("/var/lib/paperbot/combo/friend.db", "/var/lib/paperbot/exec/executor-wooxpro2-live.db")
    assert (cfg.ladder_from, cfg.ladder_basis, cfg.stop_from, cfg.stop_roe, cfg.stop_net, cfg.entry_source) == (
        "own", "net", "roe", 0.5, True, "paper")
    assert cfg.ladder == {"first_lock": 0.1, "trigger_gap": 0.02, "step": 0.05}
    assert cfg.ladder_spec().describe() == "순ROE 12%에서 10% 잠금, 이후 5%씩"
    assert cfg.risk.max_leverage == 35                     # 35x on every coin: the paper's; another is refused, never cut
    assert (cfg.equity_floor_frac, cfg.double_notice, cfg.own_keys, cfg.signal_light_n) == (0.7, True, True, 0)
    dc = json.loads((ROOT / "deploy" / "executor.live-deepcoin.json").read_text(encoding="utf-8"))
    assert raw["net_costs"] == dc["net_costs"] and raw["net_costs"]["wooxpro"] == {"taker_fee": 0.00042, "slippage": 0.0002}
    assert {k: v for k, v in raw["risk"].items() if k not in ("max_loss_frac", "max_leverage")} == \
        {k: v for k, v in dc["risk"].items() if k not in ("max_loss_frac", "max_leverage")}
    assert raw["risk"]["max_loss_frac"] == 0.35 and raw["risk"]["kill_file"] == "/var/lib/paperbot/STOP"
    assert cfg.problems() == ["qty_scale은 0보다 커야 합니다", "실거래(mainnet)는 정한 금액 budget_usd(예: 500)가 필요합니다"]
    filled = ExecConfig.from_dict({**raw, "budget_usd": 300, "qty_scale": 0.3})
    assert filled.problems() == []
    # one stop-out: margin 40 % x net ROE -50 % = 20 % of the balance (the screen's -45.66 % + 35 x WOO X Pro's 0.124 %
    # round trip); the executor's own loss check (the paper rules' 0.14 % round trip) reads 20.2 %: inside 0.35
    dist = 0.5 / 35 - filled.own_round_trip()
    assert dist == pytest.approx(0.0130457, abs=1e-7) and 0.4 * 35 * (dist + filled.own_round_trip()) == pytest.approx(0.2)
    own_check = 0.4 * 35 * (dist + 2 * (0.0005 + 0.0002))
    assert own_check == pytest.approx(0.2022, abs=1e-4) and own_check < raw["risk"]["max_loss_frac"]
    # 잔고 바닥 70 %: one stop 80 %, two in a row 64 % (the floor), three 51 %
    assert [round(0.8 ** n, 3) for n in (1, 2, 3)] == [0.8, 0.64, 0.512]


def test_the_new_fields_are_checked_and_absent_means_as_before(tmp_path):
    cfg = _cfg(tmp_path)
    assert not cfg.problems()
    bad = _cfg(tmp_path, label="[x]", own_keys="yes", equity_floor_frac=1.5, double_notice=1)
    assert [p for p in bad.problems() if "label" in p or "own_keys" in p or "equity_floor" in p or "double" in p] == [
        "label은 실행기 이름입니다(예: \"WOO X Pro 2\", 20자 이하, 대괄호 없이)", "own_keys는 true 또는 false입니다",
        "equity_floor_frac은 0~1 사이 비율입니다(예: 70% → 0.7, 끄려면 null)", "double_notice는 true 또는 false입니다"]
    plain = ExecConfig.from_dict({"account": "COMBO@mix", "paper_db": "p", "db": "d", "qty_scale": 1.0, "risk": {}})
    assert (plain.label, plain.own_keys, plain.equity_floor_frac, plain.double_notice) == (None, False, None, False)
    assert E.guard_lines(plain) == []


# ---------------------------------------------------------------- the owners' trade settings (10-24): 35x, -50 %, 10/5
LADDER_10_5 = {"first_lock": 0.1, "trigger_gap": 0.02, "step": 0.05}
NET_STOP = 0.5 / 35 - 2 * (0.00042 + 0.0002)                 # 1.3046 % of the fill: net ROE -50 % at WOO X Pro's costs


def _roe_cfg(tmp_path, **kw) -> ExecConfig:
    """The template's trade rules: the stop at net ROE -50 % (its own costs) from its own fill, its own 10/5 ladder."""
    base = dict(stop_from="roe", stop_roe=0.5, stop_net=True, ladder_from="own", ladder=dict(LADDER_10_5),
                net_costs={"wooxpro": {"taker_fee": 0.00042, "slippage": 0.0002}})
    base.update(kw)
    return _cfg(tmp_path, **base)


def _paper_at(w, symbol, side, raw, qty, lev=35):
    """The paper's entry as '친구 매매법' makes it (stop {"mode": "roe", "roe": 0.5, "net": true}): its stop 0.5 / 35 less
    the paper rules' 0.14 % round trip from the signal's raw price, its own fill 0.02 % slippage past that price."""
    w.paper(symbol=symbol, side=side, qty=qty, lev=lev, entry=raw * (1 + side * 0.0002),
            stop=raw * (1 - side * (0.5 / lev - 0.0014)))


def test_the_stop_settings_are_checked(tmp_path):
    assert _roe_cfg(tmp_path).problems() == []
    assert _roe_cfg(tmp_path, stop_net=False, stop_roe=0.2).problems() == []       # the screen's ROE before fees
    assert _roe_cfg(tmp_path, stop_roe=None, stop_net=False).problems() == [
        "stop_from \"roe\"는 stop_roe(화면 ROE 손절, 수수료 전, 0~1 사이 비율, 예: -20% → 0.2)가 있어야 합니다"]
    for bad in (0, 1.2, -0.2, True, "0.2"):
        assert _roe_cfg(tmp_path, stop_roe=bad).problems()
    assert _roe_cfg(tmp_path, ladder_from="paper", ladder=None).problems() == [
        "stop_from \"roe\"는 ladder_from \"own\"(거래소 기준 익절)과 함께만 씁니다"]
    assert _cfg(tmp_path, stop_roe=0.2).problems() == ["stop_roe는 stop_from \"roe\"일 때만 씁니다"]
    assert _cfg(tmp_path, stop_net=True).problems() == ["stop_net은 stop_from \"roe\"일 때만 씁니다"]
    assert _roe_cfg(tmp_path, stop_net="yes").problems() == [
        "stop_net은 true(순ROE, 이 거래소 비용 포함) 또는 false(화면 ROE, 수수료 전)입니다"]
    assert _roe_cfg(tmp_path, stop_roe=0.04).problems() == [                  # 0.04 / 40 = 0.1 % < the 0.124 % costs
        "stop_roe 0.04(순ROE)는 40배에서 왕복 비용 0.124%보다 가까워 손절 자리가 없습니다"]
    assert _cfg(tmp_path, stop_from="x").problems() == ["stop_from은 \"ratio\", \"price\" 또는 \"roe\"입니다"]
    assert (_cfg(tmp_path).stop_roe, _cfg(tmp_path).stop_net) == (None, False)    # every other executor: as before


def test_the_stop_is_net_roe_minus_50_percent_from_its_own_fill(tmp_path):
    """Long and short: 0.5 / 35 - 0.124 % = 1.3046 % from the executor's own fill (screen ROE -45.66 %), rounded to
    the tick at most one tick tighter, never looser, wherever the paper filled. "ratio" would copy the paper's distance
    from the paper's fill (its own 0.14 % costs, its stop from the raw price 0.02 % before its fill): 1.3082 %."""
    fake = FakeWooX(prices={BTC: 60_000.0, ETH: 2_510.0}, wallet=10_000.0)
    w = World(tmp_path, cfg=_roe_cfg(tmp_path), fake=fake)
    assert NET_STOP == pytest.approx(0.0130457, abs=1e-7) and NET_STOP * 35 == pytest.approx(0.4566, abs=1e-4)
    _paper_at(w, BTC, 1, 60_000.0, 0.1)
    w.loop()
    t = w.ex.trade
    (plan,) = fake.live_stops(BTC)
    assert (t["entry_price"], t["leverage"], fake.levs[BTC]) == (60_000.0, 35, ["isolated", 35])
    assert t["stop"] == t["stop_initial"] == pytest.approx(float(plan["trigger_price"])) == pytest.approx(59_217.3)
    assert NET_STOP - 0.1 / 60_000 <= (60_000.0 - t["stop"]) / 60_000.0 <= NET_STOP
    paper = w.src.intent
    ratio = E.round_stop(60_000.0 * paper.stop / paper.entry_price, 0.1, 1)
    assert (60_000.0 - ratio) / 60_000.0 == pytest.approx(0.013082, abs=3e-6)
    fake.set_price(BTC, 59_200.0)                          # the price reaches it: the exchange stop closes the position
    w.src.intent = None
    w.loop(2)
    assert w.ex.trade is None and fake.pos[BTC] == 0
    assert w.store.conn.execute("SELECT exit_reason FROM trades WHERE symbol = ?", (BTC,)).fetchall() == [
        ("거래소 손절(또는 잠금) 발동",)]
    w.clock.t += 60_000
    _paper_at(w, ETH, -1, 2_500.0, 2.0)                    # the paper's short at 2,500, WOO X Pro 2's fill at 2,510
    w.loop()
    t = w.ex.trade
    (plan,) = fake.live_stops(ETH)
    assert (t["entry_price"], t["leverage"]) == (2_510.0, 35)
    assert t["stop"] == pytest.approx(float(plan["trigger_price"])) == pytest.approx(2_542.74)
    assert NET_STOP - 0.01 / 2_510 <= (t["stop"] - 2_510.0) / 2_510.0 <= NET_STOP
    # the screen's ROE before fees (stop_net false): 0.2 / 35 = 0.5714 %, the same rounding
    w.ex.cfg = _roe_cfg(tmp_path, stop_net=False, stop_roe=0.2)
    assert w.ex._stop_level(0.0, 0.0, 60_000.0, 0.1, 1, 35) == pytest.approx(59_657.2)
    w.close()


def test_a_full_size_entry_is_not_cut_one_stop_is_a_fifth_of_the_balance(tmp_path):
    """Margin 40 % at 35x (the paper's $1,000 wallet, qty_scale 1): its loss at the stop with the paper rules' costs is
    about 20 % of the balance, inside max_loss_frac 0.35, so the size is the paper's (no cut); its liquidation (about
    2.36 % away at the fake's 0.5 % maintenance ratio) is past the stop."""
    fake = FakeWooX(prices={BTC: 60_000.0}, wallet=1_000.0)
    w = World(tmp_path, cfg=_roe_cfg(tmp_path, budget_usd=1_000.0), fake=fake)
    _paper_at(w, BTC, 1, 60_000.0, 1_000 * 0.4 * 35 / 60_012.0)
    w.loop()
    (lv, text), = w.events("entry_check")
    assert lv == INFO and text.startswith("진입 검사(BTCUSDT): allow")
    t = w.ex.trade
    assert t["qty"] == pytest.approx(0.233) and t["leverage"] == 35 and not w.events("liq_inside_stop")
    loss = t["qty"] * ((60_000.0 - t["stop"]) + (60_000.0 + t["stop"]) * 0.0007)
    assert loss / 1_000.0 == pytest.approx(0.2018, abs=5e-4) and loss / 1_000.0 < 0.35
    w.close()


def test_a_liquidation_before_the_stop_refuses_the_entry_and_never_moves_the_stop(tmp_path):
    """The maintenance ratio of the position's size puts the liquidation at 1 / 35 - 1.5 % = 1.36 %: not 0.2 % past the
    1.30 % stop: no entry (no leverage set, no order), said on Telegram. A size past the last bracket: the same."""
    fake = FakeWooX(prices={BTC: 60_000.0, ETH: 2_510.0}, wallet=1_000.0)
    fake.brackets[BTC] = [(100, 0, 10_000, 0.005), (50, 10_000, 1_000_000, 0.015)]
    fake.brackets[ETH] = [(100, 0, 1_000, 0.005)]
    w = World(tmp_path, cfg=_roe_cfg(tmp_path, budget_usd=1_000.0), fake=fake)
    _paper_at(w, BTC, 1, 60_000.0, 1_000 * 0.4 * 35 / 60_012.0)
    w.loop(2)
    assert w.ex.trade is None and fake.pos[BTC] == 0 and not fake.live_stops() and fake.levs[BTC] == ["isolated", 40]
    (lv, text), = w.events("liq_inside_stop")
    assert lv == E.WARN and text.startswith("BTCUSDT 진입하지 않습니다: 35배 포지션 $13,980의 청산가가 약 1.36% 거리"
                                           "(유지증거금률 1.50%)라 손절 1.30%보다 0.2% 넘게 멀지 않습니다")
    assert text.endswith("손절은 옮기지 않습니다")
    assert any(m[0] == E.WARN and m[1].startswith("[WOO X Pro 2 실거래 실행기] BTCUSDT 진입하지 않습니다") for m in w.said())
    w.clock.t += 60_000
    _paper_at(w, ETH, -1, 2_500.0, 2.0)
    w.loop(2)
    assert w.ex.trade is None and fake.pos[ETH] == 0
    (_lv, text), = [e for e in w.events("liq_inside_stop") if e[1].startswith("ETHUSDT")]
    assert "포지션 $5,020가 거래소 위험 한도의 마지막 구간을 넘습니다" in text
    w.close()


def test_35x_or_no_trade_never_another_leverage(tmp_path):
    """A coin WOO X Pro allows less than 35x on, a position past what 35x allows (its leverage risk limit), a config cap
    below the paper's 35x: each refuses the entry, says so on Telegram, and leaves no position and no order."""
    fake = FakeWooX(prices={BTC: 60_000.0, ETH: 2_510.0}, wallet=10_000.0)
    fake.max_lev[BTC] = 30
    fake.brackets[ETH] = [(35, 0, 1_000), (20, 1_000, 1_000_000)]
    w = World(tmp_path, cfg=_roe_cfg(tmp_path), fake=fake)
    _paper_at(w, BTC, 1, 60_000.0, 0.1)
    w.loop(2)
    # nothing traded: BTC stays at the start's isolated 30x (the coin's max), never set to 35x nor traded at 30x
    assert w.ex.trade is None and fake.pos[BTC] == 0 and not fake.live_stops() and fake.levs[BTC] == ["isolated", 30]
    (lv, text), = w.events("leverage_refused")
    assert lv == E.WARN and "BTCUSDT 레버리지 35배 설정이 거절돼 진입하지 않습니다" in text and "최대 30배" in text
    assert any(m[0] == E.WARN and m[1].startswith("[WOO X Pro 2 실거래 실행기] BTCUSDT 레버리지 35배") for m in w.said())
    w.clock.t += 60_000
    _paper_at(w, ETH, -1, 2_500.0, 2.0)                    # $5,020 at 35x: past the $1,000 35x allows
    w.loop(2)
    assert w.ex.trade is None and fake.pos[ETH] == 0 and not fake.live_stops()
    (lv, text), = w.events("entry_refused")
    assert lv == E.WARN and "ETHUSDT 진입 주문이 거절됐습니다" in text and "40029" in text
    w.close()
    os.makedirs(tmp_path / "cap", exist_ok=True)
    risk = R.RiskConfig(max_leverage=30, max_notional_usd=50_000.0, max_loss_frac=0.35, allowed_symbols=(BTC, ETH),
                        kill_file=str(tmp_path / "STOP"))
    fake = FakeWooX(prices={BTC: 60_000.0, ETH: 2_510.0}, wallet=10_000.0)
    o = World(tmp_path, cfg=_roe_cfg(tmp_path / "cap", db="cap.db", risk=risk), fake=fake)
    _paper_at(o, BTC, 1, 60_000.0, 0.1)
    o.loop(2)
    assert o.ex.trade is None and fake.pos[BTC] == 0 and fake.levs[BTC] == ["isolated", 40] and not fake.live_stops()
    (lv, text), = o.events("leverage_refused")
    assert lv == E.WARN and "paper는 35배인데 이 실행기 설정의 상한 risk.max_leverage가 30배라 진입하지 않습니다" in text
    assert any(m[1].startswith("[WOO X Pro 2 실거래 실행기] BTCUSDT paper는 35배인데") for m in o.said())
    o.close()


def test_the_check_at_35x_says_every_coin_the_largest_position_and_the_liquidation_against_the_stop():
    """``paperbot.wooxpro check --leverage 35 --stop-net-roe 0.5`` (docs/friend-bot-ko.md 7-4): every coin isolated at
    35x, read back; each coin's largest position at 35x from WOO X Pro's leverage risk limit; and for the position
    margin 40 % of the balance opens at 35x, its liquidation against the stop and up to which balance that holds. A coin
    below 35x stops the check."""
    clock = Clock()
    fake = FakeWooX()                                      # balance $10,000: positions of $140,000
    fake.clock = clock
    fake.brackets["DOGEUSDT"] = [(25, 0, 50_000), (10, 50_000, 500_000)]
    fake.brackets["LTCUSDT"] = [(50, 0, 100_000, 0.005), (50, 100_000, 1_000_000, 0.015)]
    c = WX.WooXProClient("wk", "ws", "wm", send=fake, clock_ms=clock, sleep=lambda s: None)
    d = WX.WooXProDrill(c, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000, leverage=35,
                        stop_net_roe=0.5)
    d.check()
    steps = {r["step"]: r for r in d.log}
    assert steps["계약 정보(6개 코인), 최대 배수 35배 이상"]["ok"]
    lev = steps["격리 레버리지 모든 코인 35배(다시 읽어 확인)"]
    assert lev["ok"] and lev["detail"] == {s: 35 for s in WX.COINS}
    assert all(fake.levs[s] == ["isolated", 35] for s in WX.COINS)
    caps = steps["35배로 열 수 있는 포지션 크기(거래소 위험 한도)"]
    # the fake's limits: 100x coins keep 50x (>= 35x) up to $1M, the 50x coins drop to 25x past $200k
    assert not caps["ok"] and caps["detail"] == {
        "BTCUSDT": "$1,000,000까지", "ETHUSDT": "$1,000,000까지", "SOLUSDT": "$200,000까지", "DOGEUSDT": "35배 안 됨",
        "LTCUSDT": "$1,000,000까지", "BCHUSDT": "$200,000까지"}
    taker = c.fee_rate("DOGEUSDT")["taker"]
    stop = 0.5 / 35 - 2 * (taker + 0.0002)
    (liq,) = [r for r in d.log if r["step"].startswith("35배 청산가와 손절(")]
    assert liq["step"] == (f"35배 청산가와 손절(잔고 $10,000 × 40% × 35배 = 포지션 $140,000, 손절 = 순ROE -50% = 가격 {stop:.2%}, "
                           f"테이커 {taker:.3%} + 슬리피지 0.02%)")
    assert not liq["ok"] and liq["detail"] == {
        "BTCUSDT": f"청산 약 2.36%(유지증거금률 0.50%) · 손절 {stop:.2%} → 손절이 먼저 · 잔고 $71,429까지 같음",
        "ETHUSDT": f"청산 약 2.36%(유지증거금률 0.50%) · 손절 {stop:.2%} → 손절이 먼저 · 잔고 $71,429까지 같음",
        "SOLUSDT": f"청산 약 2.36%(유지증거금률 0.50%) · 손절 {stop:.2%} → 손절이 먼저 · 잔고 $14,286까지 같음",
        "DOGEUSDT": "포지션 $140,000는 35배로 못 엶(거래소가 거절, 실행기는 진입 안 함)",
        "LTCUSDT": f"청산 약 1.36%(유지증거금률 1.50%) · 손절 {stop:.2%} → 청산이 먼저이거나 너무 붙음: 실행기가 진입하지 않음"
                   " · 잔고 $7,143까지 같음",
        "BCHUSDT": f"청산 약 2.36%(유지증거금률 0.50%) · 손절 {stop:.2%} → 손절이 먼저 · 잔고 $14,286까지 같음"}
    assert "격리 레버리지 BTC 40배, 나머지 30배(다시 읽어 확인)" not in steps
    fake.max_lev["SOLUSDT"] = 30                           # a fresh run (the client keeps the contract specs it read)
    c = WX.WooXProClient("wk", "ws", "wm", send=fake, clock_ms=clock, sleep=lambda s: None)
    d = WX.WooXProDrill(c, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000, leverage=35)
    with pytest.raises(AssertionError, match="최대 배수 35배 이상"):
        d.check()
    assert d.log[-1]["detail"]["SOLUSDT"]["max_leverage"] == 30 and not d.log[-1]["ok"]
    plain = WX.WooXProDrill(c, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert (plain.leverage, plain.stop_net_roe) == (None, None)   # the other WOO X Pro's check: as before


def test_its_name_in_every_message_and_the_first_woo_x_pro_keeps_its_own(tmp_path):
    w = World(tmp_path)
    assert w.ex.prefix == "[WOO X Pro 2 실거래 실행기]" == E.exec_prefix(w.cfg)
    w.close()
    plain = _cfg(tmp_path / "x", db="x.db", label=None, own_keys=False, equity_floor_frac=None, double_notice=False)
    os.makedirs(tmp_path / "x", exist_ok=True)
    o = World(tmp_path, cfg=plain)
    assert o.ex.prefix == "[WOO X Pro 실거래 실행기]" == WX.PREFIX["mainnet"] == E.exec_prefix(plain)
    assert o.ex.floor_on is False and o.store.get_state(E.FLOOR) is None      # floor off: nothing recorded, nothing said
    o.loop(2)
    assert o.store.get_state(E.FLOOR) is None and not o.said()
    o.close()


# ---------------------------------------------------------------- 잔고 바닥 and 원금 회수 안내
def test_the_start_is_recorded_once_and_said_with_its_balance(tmp_path):
    w = World(tmp_path)
    w.loop()
    f = w.store.get_state(E.FLOOR)
    assert f["start"] == pytest.approx(10_000.0) and f["hit"] is False and f["frac"] == 0.7
    (lv, text), = w.said()
    assert lv == INFO and text.startswith("[WOO X Pro 2 실거래 실행기] 시작 금액 기록: 이 계정의 잔고 $10,000.00.")
    assert "70%($7,000.00)에 닿으면 새 진입을 멈추고, 2배($20,000.00)가 되면 원금 회수를 알려 드립니다" in text
    assert "앱에서 확인하세요" in text
    w.fake.wallet = 9_000.0                         # later balances never move the start
    w.loop(2)
    assert w.store.get_state(E.FLOOR)["start"] == pytest.approx(10_000.0) and len(w.said()) == 1
    w.close()


def test_the_floor_stops_new_entries_once_said_loudly_and_never_closes_the_open_position(tmp_path):
    w = World(tmp_path)
    w.loop()
    w.paper()                                       # an entry before the floor: followed
    w.loop()
    assert w.ex.trade is not None and w.fake.pos[BTC] > 0 and w.fake.live_stops(BTC)
    w.fake.wallet = 6_950.0                         # the closed balance at 69.5 % of the start
    w.loop(3)
    hits = [m for m in w.said() if "잔고 바닥" in m[1]]
    assert len(hits) == 1 and hits[0][0] == CRITICAL
    assert hits[0][1].startswith("[WOO X Pro 2 실거래 실행기] 잔고 바닥: 잔고 $6,950.00가 시작 금액 $10,000.00의 70%($7,000.00)에")
    assert "열린 포지션은 거래소 손절·계단이 그대로 지킵니다" in hits[0][1] and "clear-floor" in hits[0][1]
    assert w.ex.trade is not None and w.fake.pos[BTC] > 0 and w.fake.live_stops(BTC)      # nothing closed by the floor
    assert w.ex.floor_blocked() and w.store.get_state(E.FLOOR)["hit"] is True
    w.src.intent = None                             # the paper closes: the position goes as always
    w.loop(2)
    assert w.ex.trade is None and w.fake.pos[BTC] == 0
    w.clock.t += 60_000
    w.paper(symbol=ETH, entry=100.0, stop=97.64)    # a new paper entry while the floor holds: not followed
    w.loop(2)
    assert w.ex.trade is None and w.fake.pos[ETH] == 0
    (lv, text), = w.events("floor_skip")
    assert lv == INFO and "ETHUSDT 진입을 따라가지 않습니다" in text
    assert json.loads(w.store.conn.execute("SELECT data FROM events WHERE kind = 'floor_skip'").fetchone()[0])["key"] == \
        w.src.intent.key
    assert sum(1 for m in w.said() if "잔고 바닥" in m[1]) == 1      # said once
    w.close()


def test_the_floor_holds_across_a_restart_until_clear_floor(tmp_path):
    cfg = _cfg(tmp_path)
    path = tmp_path / "executor-wooxpro2.json"
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.update(db=cfg.db, paper_db=cfg.paper_db, budget_usd=10_000, qty_scale=1.0)
    path.write_text(json.dumps(raw), encoding="utf-8")
    w = World(tmp_path, cfg=cfg)
    w.loop()
    w.fake.wallet = 7_000.0                          # exactly 70 %: reached
    w.loop()
    w.close()
    again = World(tmp_path, cfg=cfg, fake=w.fake, clock=w.clock)
    assert again.ex.floor_blocked()
    again.paper()
    again.loop(2)
    assert again.ex.trade is None and again.events("floor_skip")
    again.close()
    out = subprocess.run([sys.executable, "-m", "paperbot.executor", "status", "--db", cfg.db], capture_output=True,
                         text=True, cwd=ROOT)
    assert "잔고 바닥: 멈춤 중 - 잔고 $7,000.00가 시작 금액 $10,000.00" in out.stdout and "clear-floor" in out.stdout
    assert "원금 회수 안내: 아직 (2배 = $20,000.00)" in out.stdout
    assert E.main(["clear-floor", "--config", str(path), "--by", "운영자", "--note", "다시 시작"]) == 0
    f = ExecStore(cfg.db, lock=False)
    assert f.get_state(E.FLOOR)["start"] is None and f.get_state(E.FLOOR)["was"]["hit"] is True
    (text,), = f.conn.execute("SELECT text FROM events WHERE kind = 'floor_cleared'").fetchall()
    assert "운영자님이 잔고 바닥 기록을 지웠습니다(시작 금액 $10,000.00, 멈춤 중이었음; 메모: 다시 시작)" in text
    f.close()
    third = World(tmp_path, cfg=cfg, fake=w.fake, clock=w.clock)
    assert not third.ex.floor_blocked()
    third.loop()                                     # the balance now is the new start
    assert third.store.get_state(E.FLOOR)["start"] == pytest.approx(7_000.0)
    third.clock.t += 60_000
    third.paper(symbol=ETH)
    third.loop()
    assert third.ex.trade is not None
    third.close()


def test_double_notice_once_at_twice_the_start(tmp_path):
    w = World(tmp_path)
    w.loop()
    w.fake.wallet = 19_990.0
    w.loop()
    assert not [m for m in w.said() if "원금 회수 안내" in m[1]]
    w.fake.wallet = 20_050.0
    w.loop(3)
    dbl = [m for m in w.said() if "원금 회수 안내" in m[1]]
    assert len(dbl) == 1 and dbl[0][0] == INFO
    assert dbl[0][1] == ("[WOO X Pro 2 실거래 실행기] 💰 원금 회수 안내: 잔고 $20,050.00가 시작 금액 $10,000.00의 2배가 됐어요. "
                         "원금을 빼실지 정하세요(실행기는 그대로 거래합니다. 이 안내는 한 번만 갑니다)")
    assert w.store.get_state(E.FLOOR)["double_told"] is True
    w.close()


def test_a_floor_turned_off_in_the_config_blocks_nothing(tmp_path):
    w = World(tmp_path)
    w.loop()
    w.fake.wallet = 6_000.0
    w.loop()
    w.close()
    off = _cfg(tmp_path, equity_floor_frac=None)
    again = World(tmp_path, cfg=off, fake=w.fake, clock=w.clock)
    assert not again.ex.floor_blocked()
    again.paper()
    again.loop()
    assert again.ex.trade is not None
    again.close()


# ---------------------------------------------------------------- which key, which account
def test_another_exchanges_key_in_its_environment_refuses_the_start(tmp_path):
    env = dict(LIVE_ENV, BYBIT_LIVE_API_KEY="by", DEEPCOIN_LIVE_PASSPHRASE="pp")
    with pytest.raises(KeyMixup) as e:
        World(tmp_path, env=env)
    assert "키 파일에 다른 거래소 키(BYBIT_LIVE_API_KEY, DEEPCOIN_LIVE_PASSPHRASE)가 있습니다" in str(e.value)
    assert "by" not in str(e.value).replace("BYBIT", "") and "pp" not in str(e.value).replace("PASSPHRASE", "")
    s = ExecStore(str(tmp_path / "exec-woox2.db"), lock=False)
    assert s.get_state("meta") is None and s.get_state(E.KEY_TIE) is None        # refused before anything was written
    s.close()


def test_its_database_is_tied_to_its_first_key_until_untie_key(tmp_path):
    w = World(tmp_path, key="friendkey")
    tie = w.store.get_state(E.KEY_TIE)
    assert tie["fp"] == E.key_fp("wooxpro", "friendkey") and "friendkey" not in json.dumps(tie)
    w.close()
    with pytest.raises(KeyMixup) as e:
        World(tmp_path, key="otherkey", start=False)
    assert "처음 켤 때의 다른 WOO X Pro 키에 묶여 있습니다" in str(e.value) and "untie-key" in str(e.value)
    path = tmp_path / "executor-wooxpro2.json"
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.update(db=str(tmp_path / "exec-woox2.db"), budget_usd=10_000, qty_scale=1.0)
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert E.main(["untie-key", "--config", str(path), "--by", "운영자", "--note", "새 키(잔고 확인)"]) == 0
    w2 = World(tmp_path, key="otherkey")
    assert w2.store.get_state(E.KEY_TIE)["fp"] == E.key_fp("wooxpro", "otherkey")
    assert w2.events("key_untied")[0][1].startswith("운영자님이 이 DB의 키 묶음을 풀었습니다")
    w2.close()


def test_the_two_woo_x_pro_accounts_never_trade_with_each_others_key(tmp_path):
    """The owners' WOO X Pro executor (no own_keys: as before) records the key it started with; WOO X Pro 2 started with
    that key is refused, and the owners' executor started with WOO X Pro 2's key (tied to its database) is refused too.
    Each with its own key: both start."""
    owners = _cfg(tmp_path, db="executor-wooxpro-live.db", label=None, own_keys=False, equity_floor_frac=None,
                  double_notice=False, paper_db=str(tmp_path / "live-ac.db"))
    o = World(tmp_path, cfg=owners, key="ownerskey")
    assert o.store.get_state(E.KEY_SEEN)["fp"] == E.key_fp("wooxpro", "ownerskey") and o.store.get_state(E.KEY_TIE) is None
    o.close()
    friend = _cfg(tmp_path, db="executor-wooxpro2-live.db")
    with pytest.raises(KeyMixup) as e:
        World(tmp_path, cfg=friend, key="ownerskey", start=False)
    assert "다른 실행기 DB(executor-wooxpro-live.db)가 쓰는 키입니다" in str(e.value)
    f = World(tmp_path, cfg=friend, key="friendkey", start=False)
    f.close()
    with pytest.raises(KeyMixup) as e:
        World(tmp_path, cfg=owners, key="friendkey", start=False)
    assert "다른 실행기 DB(executor-wooxpro2-live.db)에 묶인 키입니다" in str(e.value)
    o2 = World(tmp_path, cfg=owners, key="ownerskey", start=False)                    # its own key: as before
    o2.close()
    # an executor of another exchange, or an old database of the same key that is not tied: never refused
    assert E.key_holders(str(tmp_path / "new.db"), "bybit", E.key_fp("wooxpro", "ownerskey"), ties_only=False) == []
    (tmp_path / "broken.db").write_bytes(b"not a database")
    assert E.key_holders(str(tmp_path / "new.db"), "wooxpro", E.key_fp("wooxpro", "friendkey"), ties_only=True) == [
        "executor-wooxpro2-live.db"]


def test_a_mixed_up_key_is_said_on_telegram_and_exits_2(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    path = tmp_path / "executor-wooxpro2.json"
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.update(db=cfg.db, paper_db=cfg.paper_db, budget_usd=10_000, qty_scale=1.0,
               risk={**raw["risk"], "kill_file": str(tmp_path / "STOP")}, paper_env_file=str(tmp_path / "live.env"))
    path.write_text(json.dumps(raw), encoding="utf-8")
    fake = FakeWooX(wallet=10_000.0)
    fake.clock = Clock()
    note = ListNotifier()
    kw = dict(send=fake, clock_ms=fake.clock, sleep=lambda s: None)
    monkeypatch.setattr(E, "_clients", lambda c, env=None: (WX.WooXProClient("wk", "ws", "wm", **kw),
                                                           WX.WooXProKeyCheckClient("wk", "ws", "wm", attested=True, **kw)))
    monkeypatch.setattr(E, "_notifier", lambda: note)
    for k, v in {**LIVE_ENV, "MEXC_LIVE_KEY": "mk"}.items():
        monkeypatch.setenv(k, v)
    assert E.main(["run", "--config", str(path), "--max-loops", "1"]) == 2
    (lv, text), = note.messages
    assert lv == CRITICAL and text.startswith("[WOO X Pro 2 실거래 실행기] 실행기를 시작하지 않습니다(키가 섞임, 주문 없음): ")
    assert "MEXC_LIVE_KEY" in text and not fake.calls                       # no request at all


def test_check_config_and_preflight_say_the_name_the_key_rule_and_the_floor(tmp_path, capsys):
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.update(budget_usd=200, qty_scale=0.2)
    path = tmp_path / "executor-wooxpro2.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert E.main(["check-config", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "이름: WOO X Pro 2 (알림 머리말 [WOO X Pro 2 실거래 실행기])" in out
    assert "계단: 순ROE 12%에서 10% 잠금, 이후 5%씩" in out and "신호등: 꺼짐" in out
    assert ("손절: 이 실행기의 체결가에서 순ROE -50%(이 거래소 비용 왕복 0.124% 포함, 펀딩 제외) 자리, 거래하는 배수로 계산 "
            "(35배면 가격 1.3046%, 화면 ROE 약 -45.66%). 페이퍼의 손절 가격은 쓰지 않음") in out
    assert ("청산가 확인: 진입 전에 거래소 위험 한도(그 크기의 유지증거금률)로 청산가를 어림해, 손절이 청산가보다 0.2% 넘게 "
            "가깝지 않으면 진입하지 않고 알림 (손절은 옮기지 않음)") in out
    assert "잔고 바닥: 켜짐 - 잔고가 시작 금액(처음 돌 때 기록)의 70%에 닿으면 새 진입 멈춤" in out
    assert "원금 회수 안내: 켜짐 - 잔고가 시작 금액의 2배가 되면 텔레그램 한 번" in out and out.rstrip().endswith("준비됨")
    plain = json.loads((ROOT / "deploy" / "executor.live-wooxpro.json").read_text(encoding="utf-8"))
    p2 = tmp_path / "executor-mexc.json"
    p2.write_text(json.dumps(plain), encoding="utf-8")
    E.main(["check-config", "--config", str(p2)])
    out = capsys.readouterr().out
    assert "이름:" not in out and "잔고 바닥" not in out and "원금 회수" not in out and "키:" not in out
    # preflight: the key rule and the floor's record, before any start
    cfg = _cfg(tmp_path)
    w = World(tmp_path, cfg=cfg)
    w.loop()
    w.fake.wallet = 6_000.0
    w.loop()
    w.close()
    lines = []
    E.preflight(cfg, w.client, w.keycheck, out=lines.append, env=dict(LIVE_ENV))
    text = "\n".join(lines)
    assert not [x for x in lines if x.startswith("[FAIL]") and "friend.db" not in x], lines      # (no paper file here: its real name, friend.db)
    assert "[OK]   키: 이 실행기 자기 키(다른 거래소 키 없음, 다른 실행기 DB의 키 아님, 이 DB에 묶인 키와 같음)" in text
    assert "[주의] 잔고 바닥: 멈춤 중" in text and "[OK]   원금 회수 안내: 아직" in text
    lines = []
    assert E.preflight(cfg, w.client, w.keycheck, out=lines.append, env=dict(LIVE_ENV, BYBIT_LIVE_API_SECRET="x")) is False
    assert any(x.startswith("[FAIL] 키: 키 파일에 다른 거래소 키(BYBIT_LIVE_API_SECRET)") for x in lines)


# ================================================================ the server's files
def test_the_unit_loads_its_own_key_file_instead_of_executor_env():
    unit = (ROOT / "deploy" / "paperbot-executor-wooxpro2.service").read_text(encoding="utf-8")
    lines = [x.strip() for x in unit.splitlines() if x.strip() and not x.startswith("#")]
    assert "EnvironmentFile=/etc/paperbot/executor-wooxpro2.env" in lines
    assert "EnvironmentFile=-/etc/paperbot/live-telegram.env" in lines
    assert not [x for x in lines if x.startswith("EnvironmentFile=") and "executor.env" in x]
    assert "InaccessiblePaths=-/etc/paperbot/agents.env -/etc/paperbot/dash.env -/etc/paperbot/executor.env" in lines
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.executor run --config /etc/paperbot/executor-wooxpro2.json" in lines
    assert "User=paperbot-exec" in lines and "RestartPreventExitStatus=2" in lines and "OOMScoreAdjust=-900" in lines
    assert "NEVER enables or starts it" in unit


def test_the_key_file_template_holds_only_its_own_names():
    env = (ROOT / "deploy" / "executor-wooxpro2.env.example").read_text(encoding="utf-8")
    names = re.findall(r"^#?([A-Z][A-Z0-9_]+)=", env, re.M)
    assert names == ["WOOXPRO_LIVE_KEY", "WOOXPRO_LIVE_SECRET", "WOOXPRO_LIVE_MEMO", "WOOXPRO_LIVE_KEY_CHECKED",
                     "PAPERBOT_LIVE_MAINNET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL", "TELEGRAM_CHAT_WARN",
                     "TELEGRAM_CHAT_INFO"]
    for line in env.splitlines():                           # every value empty: nothing secret in the repository
        if re.match(r"^#?[A-Z][A-Z0-9_]+=", line):
            assert line.endswith("="), line
    assert "FUTURES_ONLY_NO_WITHDRAW_IP_BOUND" in env and "158.247.200.152" in env and "sudoedit" in env
    # the names the executor reads at its start with this file alone: the key, secret, memo, statement and the switch
    got = WX.clients("mainnet", {**{n: "v" + n for n in ("WOOXPRO_LIVE_KEY", "WOOXPRO_LIVE_SECRET", "WOOXPRO_LIVE_MEMO")},
                                 FLAG: FLAG_VALUE, WX.KEY_CHECKED: WX.KEY_CHECKED_VALUE}, {})
    assert got[1].attested is True
    assert (WX.KEY_CHECKED_VALUE, FLAG, FLAG_VALUE) == ("FUTURES_ONLY_NO_WITHDRAW_IP_BOUND", "PAPERBOT_LIVE_MAINNET",
                                                        "I_UNDERSTAND")
    assert E.foreign_keys("wooxpro", {"WOOXPRO_LIVE_KEY": "a", "TELEGRAM_BOT_TOKEN": "t", FLAG: FLAG_VALUE}) == []


def test_install_installs_the_unit_never_starts_it_and_writes_no_key():
    sh = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert ('install -m 644 "$APP/deploy/paperbot-executor-wooxpro2.service" '
            "/etc/systemd/system/paperbot-executor-wooxpro2.service") in sh
    assert not re.search(r"systemctl (enable|start)\b[^\n]*paperbot-executor-wooxpro2", sh)
    assert "systemctl is-active --quiet paperbot-executor-wooxpro2" in sh and "sudo systemctl restart paperbot-executor-wooxpro2" in sh
    assert not re.search(r"(install|cp)\s[^\n]*executor\.live-wooxpro2\.json", sh)          # the config: the owners'
    # its key file: the empty template, root only (sudoedit then edits a root-only file), never a key
    assert ('install -o root -g root -m 600 "$APP/deploy/executor-wooxpro2.env.example" '
            "/etc/paperbot/executor-wooxpro2.env") in sh
    assert ("[ -f /etc/paperbot/executor-wooxpro2.env ] && chmod 600 /etc/paperbot/executor-wooxpro2.env && "
            "chown root:root /etc/paperbot/executor-wooxpro2.env") in sh
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / "install.sh")]).returncode == 0


def _wrapper(tmp_path, args, keyfile=None):
    """deploy/paperbot-exec.sh with id and systemd-run stubbed: (exit, stdout, systemd-run's arguments)."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "id").write_text('#!/bin/sh\ncase "$*" in\n  -u) echo 0 ;;\n  "-u paperbot-exec") echo 990 ;;\n'
                             '  "-u paperbot") echo 991 ;;\n  *) exit 0 ;;\nesac\n', encoding="utf-8")
    (bin_ / "systemd-run").write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done > "$CALLS"\n', encoding="utf-8")
    for f in ("id", "systemd-run"):
        os.chmod(bin_ / f, 0o755)
    script = (ROOT / "deploy" / "paperbot-exec.sh").read_text(encoding="utf-8")
    if keyfile is not None:
        script = script.replace("/etc/paperbot/executor-wooxpro2.env", str(keyfile))
    sh = tmp_path / "paperbot-exec.sh"
    sh.write_text(script, encoding="utf-8")
    calls = tmp_path / "calls"
    calls.unlink(missing_ok=True)
    r = subprocess.run(["sh", str(sh), *args], env={**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}",
                                                    "CALLS": str(calls)}, capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, calls.read_text().splitlines() if calls.exists() else []


def test_the_drill_wrapper_runs_with_the_second_key_file_on_request(tmp_path):
    rc, _out, run = _wrapper(tmp_path, ["wooxpro", "check"])
    assert rc == 0 and "EnvironmentFile=/etc/paperbot/executor.env" in run and run[-3:] == ["-m", "paperbot.wooxpro", "check"]
    assert "InaccessiblePaths=-/etc/paperbot/agents.env -/etc/paperbot/dash.env" in run
    rc, out, run = _wrapper(tmp_path, ["--keys", "wooxpro2", "wooxpro", "check"])     # no key file yet: said, nothing run
    assert rc == 1 and "executor-wooxpro2.env is missing" in out and run == []
    kf = tmp_path / "executor-wooxpro2.env"
    kf.write_text("", encoding="utf-8")
    rc, _out, run = _wrapper(tmp_path, ["--keys", "wooxpro2", "wooxpro", "drill", "--confirm-order", "REAL_ORDER"], kf)
    assert rc == 0 and f"EnvironmentFile={kf}" in run and "EnvironmentFile=/etc/paperbot/executor.env" not in run
    assert "InaccessiblePaths=-/etc/paperbot/agents.env -/etc/paperbot/dash.env -/etc/paperbot/executor.env" in run
    assert run[-5:] == ["-m", "paperbot.wooxpro", "drill", "--confirm-order", "REAL_ORDER"]
    rc, _out, run = _wrapper(tmp_path, ["--keys", "wooxpro2", "executor", "preflight", "--config",
                                        "/etc/paperbot/executor-wooxpro2.json"], kf)
    assert rc == 0 and run[-5:] == ["-m", "paperbot.executor", "preflight", "--config", "/etc/paperbot/executor-wooxpro2.json"]
    rc, out, run = _wrapper(tmp_path, ["--keys", "other", "wooxpro", "check"])
    assert rc == 1 and "usage" in out and run == []


def test_the_backups_and_the_restore_know_its_database():
    from paperbot import offsite as off
    assert "exec/executor-wooxpro2-live" in off.DB_NAMES
    sh = (ROOT / "deploy" / "paperbot-backup.sh").read_text(encoding="utf-8")
    assert tuple(re.search(r"^for f in (.+); do$", sh, re.M).group(1).split()) == off.DB_NAMES
    dest = Path("/root/restore-out/20261026")
    n = "executor-wooxpro2-live.db"
    text = off.next_steps(dest, [n])
    assert f"sudo install -o paperbot-exec -g paperbot -m 640 {dest / n} /var/lib/paperbot/exec/{n}" in text
    assert "paperbot-executor-wooxpro2" in text.split("2)")[0]          # stopped before its file goes back
    # not backed up (not installed): the restore's words as before
    assert "wooxpro2" not in off.next_steps(dest, ["executor-deepcoin-live.db", "paper3.db"])


# ================================================================ the live site: the four-executor world
from paperbot import livecheck as LC  # noqa: E402
from paperbot import livepreview as LPV  # noqa: E402
from paperbot import liveteam as T  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import liveinsight as LI  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livepos as LPOS  # noqa: E402
from paperbot.dash.more import livevwap as VW  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402
from tests import vwap_site_world as V  # noqa: E402

NOW, MIN, H, DAY = V.NOW, V.MIN, V.H, V.DAY
SCREENS, DOM, BAD = FW.SCREENS, FW.DOM, FW.BAD
V4 = os.path.dirname(SCREENS)
# '친구 매매법' as its run record says it (the hand-made record of this world; the bot itself is paperbot/combo.py)
FRIEND_CFG = {"name": "친구 매매법", "members": [{"strategy": "FRIEND_ROC", "tf": "15m"}],
              "leverage": {"BTCUSDT": 35, "default": 35}, "margin": 0.4, "initial_equity": 1000,
              "stop": {"mode": "roe", "roe": 0.5, "net": True},
              "ladder": {"first_lock": 0.1, "trigger_gap": 0.02, "step": 0.05}, "no_weekend": True}
# (coin, side, entry ms, hours held, reason, raw entry, raw exit): F1 a win, F2 a stop, F3 seen late by WOO X Pro 2
FRIEND = (("ETHUSDT", -1, V.K(5, 10, 15), 2, "LOCK", 2500.0, 2491.0),
          ("SOLUSDT", 1, V.K(5, 14, 30), 3, "SL", 150.0, 148.07),
          ("LTCUSDT", 1, V.K(6, 2, 45), 1, "LOCK", 80.0, 80.3))
FPOS = ("BCHUSDT", -1, V.K(6, 11, 15), 512.0)                     # the open one: WOO X Pro 2 holds it too


def friend_db(path: str) -> dict:
    """friend.db in the store3 schema: its run record, three closed trades, its open position."""
    s = Store3(path)
    s.put_state("combo_run", V.K(4, 9), {"taker_fee": FW.FEE, "config": FRIEND_CFG})
    eq, out = 1000.0, []
    for sym, side, et, held, reason, e, x in FRIEND:
        d = FW._paper_trade(s.conn, sym, side, et, et + held * H, reason, e, x, "FRIEND_ROC", "15m", 35, eq)
        eq += d["pnl"]
        out.append(d)
    sym, side, et, px = FPOS
    stop = round(px * (1 - side * (0.5 / 35 - 0.0014)), 2)
    pos = {"symbol": sym, "side": side, "qty": 400 * 35 / px, "entry_price": px, "entry_time": et, "leverage": 35,
           "tier": "best", "margin": 400.0, "margin_initial": 400.0, "stop_price": stop, "tp_price": None, "liq_price": 0.0,
           "entry_fee": 0.2, "stop_initial": stop, "lock_roe": None,
           "signal": {"ts": et - 1, "symbol": sym, "timeframe": "15m", "strategy_id": "FRIEND_ROC", "side": side,
                      "stop_price": stop, "meta": {"member_order": 0}}}
    s.put_state("accounts", NOW - MIN, {"engines": {V.ACC: {"wallet": eq, "position": pos}}})
    s.put_state("heartbeat", NOW - 2000, {})
    s.close()
    return {"path": path, "trades": out, "position": pos}


@pytest.fixture(scope="module")
def w4(tmp_path_factory):
    """The four-executor world (module docstring): ``p4`` its paths; ``p3`` the three-executor world of
    tests/test_deepcoin_slot.py (no key of the fourth slot); ``p0`` with the fourth slot's keys and the third paper bot's
    but none of their files (a server where they are not installed); ``p2`` / ``p20``: the two-executor world without and
    with those keys."""
    folder = str(tmp_path_factory.mktemp("fourth") / "w")
    w = V.build(folder, switch=False)
    p2 = dict(w["p"])
    vt, vwap = w["vt"], p2["paper2"]
    p3 = {**p2, "deepcoin_db": os.path.join(folder, "executor-deepcoin-live.db"),
          "deepcoin_config": os.path.join(folder, "executor-deepcoin.json")}
    dc = V.exec_db(p3["deepcoin_db"], p3["deepcoin_config"], "deepcoin", vwap, [], vwap_closed=[vt["E4"], vt["E5"], vt["E7"]],
                   late=[vt["E6"]], open_pos=V.paper_position(vwap), light=(20, 0.75),
                   extra={"ladder_from": "own", "risk": {"max_loss_frac": 0.2}})
    fr = friend_db(os.path.join(folder, "friend.db"))
    p4 = {**p3, "wooxpro2_db": os.path.join(folder, "executor-wooxpro2-live.db"),
          "wooxpro2_config": os.path.join(folder, "executor-wooxpro2.json"), "paper3": fr["path"]}
    w2 = V.exec_db(p4["wooxpro2_db"], p4["wooxpro2_config"], "wooxpro", fr["path"], fr["trades"][:2], late=[fr["trades"][2]],
                   open_pos=fr["position"], light=(0, 0.85),
                   extra={"label": "WOO X Pro 2", "ladder_from": "own", "own_keys": True, "equity_floor_frac": 0.7,
                          "double_notice": True, "risk": {"max_loss_frac": 0.35}})
    no = os.path.join(folder, "none")
    off = {"wooxpro2_db": no + "-wooxpro2.db", "wooxpro2_config": no + "-wooxpro2.json", "paper3": no + "-friend.db"}
    p0 = {**p3, **off}
    p20 = {**p2, **off, "deepcoin_db": no + "-deepcoin.db", "deepcoin_config": no + "-deepcoin.json"}
    return {**w, "p4": p4, "p3": p3, "p2": p2, "p0": p0, "p20": p20, "dc": dc, "w2": w2, "fr": fr, "folder": folder}


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


def _flat(x) -> str:
    return json.dumps(json_finite(x), sort_keys=True, ensure_ascii=False, default=str)


def _answers(p: dict, more: dict) -> dict:
    """The site's answers that name the executors, at the world's clock."""
    return {"build": L.build(p, NOW), "trades": L.trade_rows(p, NOW, more), "perf": L.perf(p, NOW, more),
            "safety": L.safety(p, NOW, more=more), "settings": L.settings(p, NOW), "costs": L.costs(p, NOW),
            "map": L.map_view(p, NOW), "now": L.whynow(p, NOW), "pos": LPOS.build(p, more, NOW), "risk": LI.risk(p, NOW, more),
            "health": LI.health(p, NOW, more), "goal": LI.goal(p, NOW, more), "judge": LI.judge(p, NOW, more),
            "groups": LI.groups(p, NOW, more), "vwap": VW.control(p, NOW, more), "vwperf": VW.perf(p, NOW, more)}


@pytest.fixture(scope="module")
def answers(w4):
    more = dict(w4["more"])
    out = {}
    for k in ("p2", "p20", "p3", "p0", "p4"):
        L._cache.clear()
        out[k] = _answers(w4[k], more)
    return out


def test_not_installed_every_answer_is_as_before(w4, answers):
    """The fourth slot's keys and the third paper bot's, their files not there: the very same answers as without the keys,
    with two executors and with three."""
    assert L.installed(w4["p0"]) == L.installed(w4["p3"]) and [s[0] for s in L.installed(w4["p0"])] == ["bybit", "mexc", "deepcoin"]
    assert L.installed(w4["p20"]) == L.EXECS
    assert _flat(answers["p0"]) == _flat(answers["p3"]) and _flat(answers["p20"]) == _flat(answers["p2"])
    for k in ("p0", "p20"):
        words = _flat(answers[k])
        assert "wooxpro2" not in words and "WOO X Pro 2" not in words and "친구 매매법" not in words and "friend.db" not in words
    assert sorted(answers["p0"]["build"]["paths"]) == sorted(w4["p3"])        # the answer's paths: as they were


def test_the_slot_shows_once_its_config_or_its_database_is_there(w4):
    p4, folder = w4["p4"], w4["folder"]
    assert [s[0] for s in L.installed(p4)] == ["bybit", "mexc", "deepcoin", "wooxpro2"]
    for p, rec, cfg in (({**p4, "wooxpro2_db": os.path.join(folder, "none-w.db")}, "missing", "ok"),
                        ({**p4, "wooxpro2_config": os.path.join(folder, "none-w.json")}, "ok", "missing")):
        assert [s[0] for s in L.installed(p)][-1] == "wooxpro2"
        _c, _f, _paper, execs = L.sources(p, NOW)
        x = execs[-1]
        assert (x["id"], x["record"]["state"], x["config"]["state"]) == ("wooxpro2", rec, cfg)
        assert x["name_ko"] == ("WOO X Pro 2" if cfg == "ok" else "WOO X Pro 2")       # its config's label, else its slot's name
    d = L.paths({})
    assert (d["wooxpro2_db"], d["wooxpro2_config"], d["paper3"]) == (
        "/var/lib/paperbot/exec/executor-wooxpro2-live.db", "/etc/paperbot/executor-wooxpro2.json",
        "/var/lib/paperbot/combo/friend.db")
    assert (L.ENV["wooxpro2_db"][0], L.ENV["wooxpro2_config"][0], L.ENV["paper3"][0]) == (
        "PAPERBOT_LIVE_WOOXPRO2_DB", "PAPERBOT_LIVE_WOOXPRO2_CONFIG", "PAPERBOT_LIVE_PAPER3_DB")
    assert L.paths({"PAPERBOT_LIVE_WOOXPRO2_CONFIG": p4["wooxpro2_config"]})["wooxpro2_db"] == p4["wooxpro2_db"]
    assert L.shown_paths(w4["p0"]) == w4["p3"] and L.shown_paths(p4) == p4
    env = (ROOT / "deploy" / "dash.env.example").read_text(encoding="utf-8")
    for line in ("#PAPERBOT_LIVE_WOOXPRO2_DB=/var/lib/paperbot/exec/executor-wooxpro2-live.db",
                 "#PAPERBOT_LIVE_WOOXPRO2_CONFIG=/etc/paperbot/executor-wooxpro2.json",
                 "#PAPERBOT_LIVE_PAPER3_DB=/var/lib/paperbot/combo/friend.db"):
        assert line in env


def test_its_name_is_its_label_and_the_first_woo_x_pro_keeps_its_own():
    ok = lambda ex, **k: {"state": "ok", "exchange": ex, **k}                       # noqa: E731
    got = L.slots({"bybit": ok("bybit"), "mexc": ok("wooxpro"), "deepcoin": ok("deepcoin"),
                   "wooxpro2": ok("wooxpro", label="WOO X Pro 2")})
    assert [ko for _x, ko, _d, _c in got] == ["바이비트", "WOO X Pro", "딥코인", "WOO X Pro 2"]
    assert L.slots({"wooxpro2": {"state": "missing"}})[-1][:2] == ("wooxpro2", "WOO X Pro 2")
    assert "label" not in L.read_config(str(ROOT / "deploy" / "executor.live-wooxpro.json"))       # nothing new for the others
    assert L.read_config(str(TEMPLATE))["label"] == "WOO X Pro 2"


def test_the_site_with_four_executors(w4, answers):
    a = answers["p4"]
    b = a["build"]
    assert [(x["id"], x["name_ko"], x.get("follows_ko")) for x in b["execs"]] == [
        ("bybit", "바이비트", "추세판단 봇"), ("mexc", "WOO X Pro", "추세판단 봇"), ("deepcoin", "딥코인", "VWAP 개선판"),
        ("wooxpro2", "WOO X Pro 2", "친구 매매법")]
    w2 = next(x for x in b["accts"] if x["id"] == "wooxpro2")
    assert w2["state"] == "ok" and w2["kind"] == "live" and w2["name_ko"] == "WOO X Pro 2"
    assert w2["position"]["symbol"] == "BCHUSDT" and w2["follows_ko"] == "친구 매매법"
    # the page's paper bots are the two as before: '친구 매매법' never takes the VWAP bot's place, nor an account of its own
    assert [x["id"] for x in b["papers"]] == ["paper", "paper2"] and b["papers"][1]["name"] == "VWAP 개선판"
    assert not [x for x in b["accts"] if x["id"] == "paper3"] and sorted(b["paths"]) == sorted(w4["p4"])
    # 거래: its own table, each trade paired with the paper trade it followed (friend.db), the late one said why
    t = a["trades"]["accts"]
    rows = t["wooxpro2"]["rows"]
    assert sorted(r["key"] for r in rows) == sorted(x["key"] for x in w4["w2"]["live"])
    assert all(r["paper"] and r["paper"]["exit_reason"] in ("LOCK", "SL") for r in rows)
    assert {r["paper"]["exit_reason"] for r in rows} == {"LOCK", "SL"}
    assert all(r["live"]["wooxpro2"]["state"] == "other" for r in t["paper"]["rows"])
    assert all(r["live"]["wooxpro2"]["why_ko"].startswith("이때 WOO X Pro 2는 ") for r in t["paper"]["rows"])
    # 포지션 · 비용 · 안전 · 설정 · 봇 상태 · 위험 · 성적
    assert [x["id"] for x in a["pos"]["cards"]] == ["paper", "paper2", "bybit", "mexc", "deepcoin", "wooxpro2", "flip"]
    card = next(x for x in a["pos"]["cards"] if x["id"] == "wooxpro2")
    assert card["position"] and card["position"]["symbol"] == "BCHUSDT" and card["follows_ko"] == "친구 매매법"
    c = a["costs"]
    assert c["execs"][-1] == {"id": "wooxpro2", "name_ko": "WOO X Pro 2"} and c["accts"]["wooxpro2"]["n"] == 2
    fee = next(x for x in c["fees"]["execs"] if x["id"] == "wooxpro2")
    assert fee["exchange"] == "wooxpro" and fee["rates"]["taker_disc"] == 0.00042           # WOO X Pro's own rates
    assert [x["id"] for x in a["safety"]["execs"]] == ["bybit", "mexc", "deepcoin", "wooxpro2"]
    assert [(x["id"], x.get("follows_ko")) for x in a["settings"]["execs"]][-1] == ("wooxpro2", "친구 매매법")
    assert [(i["who"], i["ko"]) for i in a["health"]["items"] if i.get("id") == "exec"][-1] == ("wooxpro2", "WOO X Pro 2 실행기")
    assert a["risk"]["kill"]["what_ko"].startswith("네 실행기가 모두 멈춰요")
    assert answers["p3"]["risk"]["kill"]["what_ko"].startswith("세 실행기가 모두 멈춰요")
    assert "wooxpro2" in a["perf"]["accts"] and "wooxpro2" in a["groups"]["accts"]
    assert [x["id"] for x in a["vwap"]["followers"]] == ["deepcoin"]                # the VWAP bot's page: its own executor only
    # the late paper entry: why it was not followed, from the executor's own record
    words = _flat(a)
    assert "WOO X Pro 2" in words and not re.search(r"WOO X Pro 2(이|은|을|과|으로)(?![가-힣])", words)


def test_a_floor_skip_has_its_words(w4):
    assert L.WHY_KO["floor_skip"] == "잔고 바닥 멈춤(새 진입 없음) 동안이라 따라가지 않았어요"
    assert L.KIND_KO["floor_hit"] == "잔고 바닥 멈춤" and L.KIND_KO["double"] == "원금 회수 안내"


SCREENS_JS = """
const view = async (sum, tr, sf, co) => {
  K.setPapers(sum.papers); K.setExecs(sum.execs);
  const band = P.bandLine(mkCtx(null)); band.set(sum, "ok");
  const hub = {get: () => sum, state: () => "ok", at: () => sum.now_ms, retry: () => {}};
  const hq = await run(HQ.hqView, (p) => (p.endsWith('/now') ? D_now : {}), hub);
  hq.set(sum, "ok");
  const hqw = D.walk(hq.el);
  const t = await run(TR.tradesView, tr), s = await run(SF.safetyView, sf), c = await run(CO.costView, co);
  return {real: texts(ui.note(K.realLine(sum))), band: texts(band.el), hq: hqw.text.replace(/\\s+/g, ' '),
    reactors: hqw.classes.filter((x) => x.split(' ').includes('lbh-reactor')).length, deck: hqw.classes.find((x) => x.startsWith('lbh-deck')),
    trades: texts(t.el), safety: texts(s.el), cost: texts(c.el), costCards: D.walk(c.el).classes.filter((x) => /lbk-a-wooxpro2/.test(x)).length};
};
const three = await view(D_s3, D_t3, D_f3, D_c3);
const four = await view(D_s4, D_t4, D_f4, D_c4);
const ids4 = [K.execsNow(), K.execIds(D_s4), K.execIds(D_t4), K.execIds(D_c4), PE.idsOf(D_p4), MA.idsOf({accounts: {wooxpro2: {}}}),
  K.execsKo(), K.acctsKo(6), K.countKo(4), K.countKo(3), K.countKo(2)];
console.log(JSON.stringify({three, four, ids4}));
""".replace("NOW", str(NOW))


def _node(tmp_path, body: str, **data) -> dict:
    import shutil
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              "for (const [k, f] of Object.entries({after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),"
              " replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {"
              " const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; };\n"
              f"Date.now = () => {NOW};\n"
              f"const K = await import('file://{SCREENS}/livebots-kit.js'); const P = await import('file://{SCREENS}/livebots-parts.js');\n"
              f"const HQ = await import('file://{SCREENS}/livebots-hq.js'); const TR = await import('file://{SCREENS}/livebots-trades.js');\n"
              f"const SF = await import('file://{SCREENS}/livebots-safety.js'); const CO = await import('file://{SCREENS}/livebots-cost.js');\n"
              f"const PE = await import('file://{SCREENS}/livebots-perf.js'); const MA = await import('file://{SCREENS}/livebots-map.js');\n"
              f"const {{ui}} = await import('file://{V4}/core/pb.js');\n" + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 10));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (a) => ({params: {query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, timeout() {}, every() {},"
              " href: (n, x) => '#/' + n + (x ? '/' + x : ''), api: async (p) => JSON.parse(JSON.stringify(typeof a === 'function' ? a(p) : a))});\n"
              "const run = async (V, a, hub) => { const v = hub ? V(mkCtx(a), hub) : V(mkCtx(a)); await tick(); await tick(); return v; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_screens_in_node(w4, answers, tmp_path):
    a3, a4 = answers["p0"], answers["p4"]
    out = _node(tmp_path, SCREENS_JS, s3=a3["build"], t3=a3["trades"], f3=a3["safety"], c3=a3["costs"],
                s4=a4["build"], t4=a4["trades"], f4=a4["safety"], c4=a4["costs"], p4=a4["perf"], now=a4["now"])
    three, four = out["three"], out["four"]
    for k, t in three.items():                             # not installed: nothing of it anywhere
        if k != "hq":
            assert "WOO X Pro 2" not in str(t), k
    # 한눈에: the four live accounts always (owners 10-25 night): WOO X Pro 2 is the mix bot's card (친구 15분 봇(믹스)), never
    # the old executor's while the server does not have it
    assert three["reactors"] == 4 and {"three", "four"} <= set(three["deck"].split()) and "five" not in three["deck"].split()
    assert "WOO X Pro 2 진짜 돈 봇 친구 15분 봇 스스로 매매" in three["hq"] and "친구 매매법" not in three["hq"]
    ids = out["ids4"]
    assert ids[:4] == [["bybit", "mexc", "deepcoin", "wooxpro2"]] * 4
    assert ids[4] == ["paper", "paper2", "bybit", "mexc", "deepcoin", "wooxpro2"] and ids[5][-1] == "wooxpro2"
    assert ids[6] == "바이비트 · WOO X Pro · 딥코인 · WOO X Pro 2" and ids[7] == "여섯 계좌" and ids[8:] == ["네", "세", "두"]
    # the old '친구 매매법' executor keeps its reactor while the server has it, next to the mix bot's card
    assert four["reactors"] == 5 and {"three", "four", "five"} <= set(four["deck"].split())
    assert four["hq"].count("WOO X Pro 2 진짜 돈 봇") == 2 and "친구 15분 봇" in four["hq"]
    assert "WOO X Pro 2 $" in four["real"] and "WOO X Pro 2 $" in four["band"]
    assert "바이비트 · WOO X Pro · 딥코인 · WOO X Pro 2" in four["hq"]
    assert "WOO X Pro 2" in four["trades"]                               # its table is a choice
    assert "실행기 네 개" in four["safety"] and four["costCards"] >= 1 and "WOO X Pro 2 실거래 · 진짜 돈" in four["cost"]
    for k, t in four.items():
        assert not BAD.search(str(t)), (k, BAD.search(str(t)))


def test_the_house_rules_of_the_fourth_slot():
    kit = FW._read(SCREENS, "livebots-kit.js")
    assert 'export const EXEC_SLOTS = ["bybit", "mexc", "deepcoin", "wooxpro2", "toobit"];' in kit      # (the fifth: test_toobit_slot.py)
    assert 'wooxpro2: {ko: "WOO X Pro 2", s: "W2"' in kit
    shorts = re.findall(r'^  \w+: \{ko: "[^"]+", s: "(\w+)"', kit, re.M)
    assert "W2" in shorts and len(shorts) == len(set(shorts)), shorts
    css = FW._read(V4, "tokens.css")
    assert "--series-w2: hsl(250 var(--av-s) var(--av-ring-l));" in css
    for f, cls in (("livebots.css", ".lb-a-wooxpro2 .lb-sw"), ("livebots-hq.css", ".lbh-x-wooxpro2"), ("livebots-cost.css", ".lbk-a-wooxpro2"),
                   ("livebots-map.css", ".lbm-a-wooxpro2"), ("livebots-risk.css", ".lbv-a-wooxpro2"), ("livebots-goal.css", ".lbg-a-wooxpro2"),
                   ("livebots-expect.css", ".lex-a-wooxpro2")):
        assert cls in FW._read(SCREENS, f), (f, cls)
    hq = FW._read(SCREENS, "livebots-hq.css")
    assert ".lbh-deck.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }" in hq
    # the words that count the executors: one helper, two and three exactly as before
    for f in sorted(os.listdir(SCREENS)):
        if f.startswith("livebots") and f.endswith(".js"):
            assert not re.search(r'length > 2 \? "세" : "두"', FW._read(SCREENS, f)), f


# ================================================================ the live checks and the Telegram messages
def test_livecheck_reads_the_fourth_executor_only_once_installed(tmp_path, monkeypatch):
    cfg, db = tmp_path / "executor-wooxpro2.json", tmp_path / "executor-wooxpro2-live.db"
    spec = LC.OPTIONAL_EXECUTORS[:1] + (("wooxpro2", str(cfg), "paperbot-executor-wooxpro2", str(db), 0, 0.85),)
    spec = tuple((n, str(tmp_path / f"{n}.json"), u, str(tmp_path / f"{n}.db"), k, s) if n == "deepcoin" else (n, c, u, d, k, s)
                 for n, c, u, d, k, s in spec)
    monkeypatch.setattr(LC, "OPTIONAL_EXECUTORS", spec)
    base = tuple((n, str(tmp_path / f"{n}.json"), u, str(tmp_path / f"{n}.db"), k, s) for n, _p, u, _d, k, s in LC.EXECUTORS)
    assert LC.installed_specs(base, spec) == base
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.update(db=str(db), budget_usd=300, qty_scale=0.3)
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    infos = LC.load_executors(LC.installed_specs(base, spec))
    assert [e.name for e in infos] == ["bybit", "mexc", "wooxpro2"]
    f = infos[-1]
    assert (f.label, f.unit, f.db, f.paper_db, f.light_n, f.budget, f.max_loss, f.exchange) == (
        "WOO X Pro 2", "paperbot-executor-wooxpro2", str(db), "/var/lib/paperbot/combo/friend.db", 0, 300.0, 0.35, "wooxpro")
    assert f.fee == LC.ASSUMED_FEE["wooxpro"] and LC.pad_of("wooxpro2", f.label) == "WOO X Pro 2 "
    assert LC.ExecInfo("mexc", "", "", "", 0, 0.9, exchange="wooxpro").label == "WOO X Pro"      # the first keeps its name
    # this server's own: the start guide's paths
    assert [x[0] for x in LC.OPTIONAL_EXECUTORS] == ["deepcoin", "wooxpro2"]
    monkeypatch.undo()
    assert LC.OPTIONAL_EXECUTORS[1] == ("wooxpro2", "/etc/paperbot/executor-wooxpro2.json", "paperbot-executor-wooxpro2",
                                        "/var/lib/paperbot/exec/executor-wooxpro2-live.db", 0, 0.85)
    # the STOP file stops all four; never suggested to stop under low memory
    assert LC.every_ko(2) == "두 실행기 모두" and LC.every_ko(3) == "세 실행기 모두" and LC.every_ko(4) == "네 실행기 모두"
    assert "paperbot-executor-wooxpro2.service" in LC.PROTECTED_UNITS and not LC.experiment("paperbot-executor-wooxpro2.service")
    four = [LC.ExecInfo(n, "", "", "", 0, 0.85, kill_file="/var/lib/paperbot/STOP") for n in ("bybit", "mexc", "deepcoin", "wooxpro2")]
    assert "(네 실행기 모두 바로 닫고 멈추려면 sudo touch /var/lib/paperbot/STOP)" in LC.streak_todo(four)
    lines = LC.memory_lines([("paperbot-agents.service", 900 * 1024 ** 2)], ("paperbot-executor-wooxpro2",))
    assert lines[1].endswith("paperbot-combo-mexc, paperbot-executor-wooxpro2")


def test_the_morning_check_says_its_floor():
    r = {"label": "WOO X Pro 2", "trades": 2, "wins": 1, "pnl": 3.0, "equity": 69.0, "halted": False,
         "floor": {"start": 100.0, "hit": True, "frac": 0.7}}
    lines, _small = LC.exec_score_lines(r)
    assert lines[-1] == "  잔고 바닥 멈춤 중: 새 진입 없음(시작 금액 $100.00의 70%에 닿음, 풀기: clear-floor)"
    assert not [x for x in LC.exec_score_lines({**r, "floor": {"start": 100.0, "hit": False}})[0] if "잔고 바닥" in x]
    assert not [x for x in LC.exec_score_lines({k: v for k, v in r.items() if k != "floor"})[0] if "잔고 바닥" in x]


@pytest.fixture(scope="module")
def preview():
    return LPV.scenes("wooxpro2")


def test_the_preview_with_four_executors(preview):
    texts = [t for _title, _lv, t in preview]
    assert texts[0] == "▶️ WOO X Pro 2 실행기 켜짐 · 잔고 $107.87 · 따라가는 페이퍼: 친구 매매법"
    entry = next(t for t in texts if t.startswith("🟢 진입"))
    assert "친구 매매법" in entry and "WOO X Pro 2 ✅" in entry
    assert "바이비트" not in entry and "딥코인" not in entry and "WOO X Pro ✅" not in entry       # its own executor only
    exit_ = next(t for t in texts if t.startswith("✅ 청산"))
    assert "친구 매매법" in exit_ and "WOO X Pro 2 +$" in exit_ and "잔고 $" in exit_
    morning = next(t for t in texts if t.startswith("📋"))
    for word in ("- WOO X Pro 2 1번 +$", "수수료 0.042%(가정 0.042%)", "- 바이비트: 어제 닫힌 거래 없음", "- 딥코인: 어제 닫힌 거래 없음",
                 "친구 매매법 (WOO X Pro 2가 따라감)", "- WOO X Pro 2(친구 매매법 따라간 거래): 거래 1번", "VWAP 개선판 (딥코인이 따라감)",
                 "(모든 봇 같음)"):
        assert word in morning, word
    friend = morning.split("친구 매매법 (WOO X Pro 2가 따라감)")[1]
    assert "5년 기준" not in friend and "늘리기 기준" not in friend         # the VWAP bot's own reference lines are its own
    vwap = morning.split("VWAP 개선판 (딥코인이 따라감)")[1].split("친구 매매법")[0]
    assert "참고: 5년 기준 본전 승률 79%" in vwap and "늘리기 기준(두 분)" in vwap
    for t in texts:
        assert not re.search(r"\b(None|null|undefined|nan)\b", t), t


def test_the_preview_flag(monkeypatch):
    seen = []
    monkeypatch.setattr(LPV, "main", lambda world="live15": seen.append(world) or 0)
    for flags, world in (({"wooxpro2": True}, "wooxpro2"), ({"deepcoin": True}, "deepcoin"), ({}, "live15")):
        LC.cmd_preview(argparse.Namespace(**{"old": False, "two": False, "vwap": False, "deepcoin": False, "wooxpro2": False,
                                             **flags}))
        assert seen[-1] == world


def test_the_team_reads_the_fourth_executor_once_installed(w4, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none-combo.json"))
    assert [e.name for e in T.bot_world(w4["p4"])["infos"]] == ["bybit", "mexc", "deepcoin", "wooxpro2"]
    assert [e.label for e in T.bot_world(w4["p4"])["infos"]][-1] == "WOO X Pro 2"
    assert [e.name for e in T.bot_world(w4["p0"])["infos"]] == ["bybit", "mexc", "deepcoin"]


def test_its_paper_bot_has_its_unit_and_low_memory_never_suggests_either(tmp_path):
    assert LC.unit_of("/var/lib/paperbot/combo/friend.db") == "paperbot-combo-friend"
    assert "paperbot-combo-friend" in LC.paper_unit_todo("/var/lib/paperbot/combo/friend.db")
    friend = tmp_path / "friend.db"
    friend.write_bytes(b"")
    ex =LC.ExecInfo("wooxpro2", "", "paperbot-executor-wooxpro2", "", 0, 0.85, exchange="wooxpro", paper_db=str(friend))
    src = LC.Sources(db=str(tmp_path / "lc.db"), executors=[ex], paper2_db=str(tmp_path / "none-vwap.db"))
    host = LC.Host(disk_free=lambda p: 40 * 1024 ** 3, mem_available=lambda: 100 * 1024 ** 2,
                   unit_memory=lambda: [("paperbot-agents.service", 900 * 1024 ** 2)], paths=(str(tmp_path),))
    conds, _judged = LC.health_conditions(host, src)
    mem = next(c for c in conds if c.key == "memory")
    assert "paperbot-combo-mexc, paperbot-combo-friend, paperbot-executor-wooxpro2" in mem.text
    friend.unlink()                                   # its paper bot's file not there: only the executor, as for 딥코인
    conds, _judged = LC.health_conditions(host, src)
    assert next(c for c in conds if c.key == "memory").text.count("paperbot-combo-friend") == 0
