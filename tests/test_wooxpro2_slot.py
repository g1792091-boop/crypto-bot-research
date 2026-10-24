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
import sqlite3
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

    def paper(self, symbol=BTC, side=1, qty=5.0, lev=30, entry=100.0, stop=97.64):
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
    """deploy/executor.live-wooxpro2.json: WOO X Pro, its own name, database and paper bot (friend.db, COMBO@mix), the
    other live templates' costs and protections, the paper's ladder (22 % -> 20 % locked, then every 10 %) on its own
    fill, its stop from the paper's (ratio), no signal light, one stop loses at most 35 %, 잔고 바닥 70 %, 원금 회수 안내;
    the money (budget_usd, qty_scale) is left empty so it cannot start before the owners set it."""
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    cfg = ExecConfig.from_file(str(TEMPLATE))
    assert (cfg.exchange, cfg.label, cfg.mode, cfg.account) == ("wooxpro", "WOO X Pro 2", "mainnet", "COMBO@mix")
    assert (cfg.paper_db, cfg.db) == ("/var/lib/paperbot/combo/friend.db", "/var/lib/paperbot/exec/executor-wooxpro2-live.db")
    assert (cfg.ladder_from, cfg.ladder_basis, cfg.stop_from, cfg.entry_source) == ("own", "net", "ratio", "paper")
    assert cfg.ladder == {"first_lock": 0.2, "trigger_gap": 0.02, "step": 0.1}
    assert cfg.ladder_spec().describe() == "순ROE 22%에서 20% 잠금, 이후 10%씩"
    assert (cfg.equity_floor_frac, cfg.double_notice, cfg.own_keys, cfg.signal_light_n) == (0.7, True, True, 0)
    dc = json.loads((ROOT / "deploy" / "executor.live-deepcoin.json").read_text(encoding="utf-8"))
    assert raw["net_costs"] == dc["net_costs"] and raw["net_costs"]["wooxpro"] == {"taker_fee": 0.00042, "slippage": 0.0002}
    assert {k: v for k, v in raw["risk"].items() if k != "max_loss_frac"} == \
        {k: v for k, v in dc["risk"].items() if k != "max_loss_frac"}
    assert raw["risk"]["max_loss_frac"] == 0.35 and raw["risk"]["kill_file"] == "/var/lib/paperbot/STOP"
    assert cfg.problems() == ["qty_scale은 0보다 커야 합니다", "실거래(mainnet)는 정한 금액 budget_usd(예: 500)가 필요합니다"]
    filled = ExecConfig.from_dict({**raw, "budget_usd": 300, "qty_scale": 0.3})
    assert filled.problems() == []
    # the net ROE of its stop: the paper's -75 % (its 0.14 % round trip) at WOO X Pro's 0.124 %: a hair tighter
    paper_dist = 0.75 / 30 - 2 * (0.0005 + 0.0002)
    assert 30 * (paper_dist + filled.own_round_trip()) == pytest.approx(0.7452)


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
    assert "계단: 순ROE 22%에서 20% 잠금, 이후 10%씩" in out and "신호등: 꺼짐" in out
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
    assert not [x for x in lines if x.startswith("[FAIL]") and "paper3.db" not in x], lines     # (no paper file here)
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
