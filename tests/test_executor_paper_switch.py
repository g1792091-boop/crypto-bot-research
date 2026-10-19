"""Switching an executor's paper source (owners 10-19, docs/live15-mexc-ko.md step 4): /etc/paperbot/executor-mexc.json's
``paper_db`` goes from 규칙봇 15 (-50 %, live-ac.db) to its -35 % twin (live15-mexc.db) while MEXC is flat, and only
paperbot-executor-mexc is restarted. Both paper databases hold the same account name (COMBO@mix) and their own trade
ids from 1. The unchanged executor (paperbot/executor.py; only its start record names the paper database now) on the
fake MEXC exchange, through the very Paper3Source cmd_run builds:

- the executor database is not tied to a paper database (only to its mode, account and exchange): the restart with the
  new paper_db starts, keeps its records (the old trades, the done keys) and records which paper database it follows;
- a position the new paper bot already holds at the switch is not followed late ("late"), one it opened less than
  max_entry_age_s before the restart is followed like after any restart;
- the next entry of the new paper bot is followed with ITS stop (-35 %), its lock moves the exchange stop, its exit
  closes; the old paper bot's later entries are never acted on;
- a new paper bot that has not written its first state yet is "paper_unreadable" (no entry) until it does;
- why the guide switches only at 포지션: null: an open live position the new paper bot does not hold is closed at once."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from fakemexc import FakeMexc
from paperbot import mexc as MX
from paperbot.executor import ExecConfig, ExecStore, Executor, Paper3Source
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3
from tests.livebots_world import _trade
from tests.test_mexc_executor import LIVE_ENV, Clock, no_network, risk_cfg  # noqa: F401  (no_network: autouse here too)

ACC = "COMBO@mix"
BTC, ETH = "BTCUSDT", "ETHUSDT"
B, E = "BTC_USDT", "ETH_USDT"
RT = 0.0014                                     # the paper rules' round trip (config.v3_settings)


def stop_of(side: int, entry: float, lev: int, roe: float) -> float:
    """The paper's net-ROE stop price (combo.py ``stop: {"mode": "roe", "net": true}``)."""
    return entry * (1 - side * (roe / lev - RT))


class Paper:
    """A paper bot's database (store3 schema, COMBO@mix) as paperbot/combo.py writes it."""

    def __init__(self, path: str, clock: Clock):
        self.path, self.clock, self.s = path, clock, Store3(path)
        self.s.add_account(ACC, "combo", "mix", "combo", clock.t, "combo-v2")
        self.s.commit()

    def history(self, n: int, start: int) -> None:
        eq = 1000.0
        for i in range(n):
            eq += 3.0
            self.s.trade(ACC, _trade(ETH, 1, start + i * 3_600_000, 3.0, 0.1, eq, "V39_ALL", "1h", "LOCK"))
        self.s.commit()

    def put(self, symbol=None, side=1, entry=100.0, lev=40, stop=None, entry_time=None, qty=4.0):
        pos = None if symbol is None else {"symbol": symbol, "side": side, "qty": qty, "leverage": lev, "stop_price": stop,
                                           "entry_price": entry, "entry_time": entry_time, "signal": {}}
        self.s.put_state("accounts", self.clock.t - 20_000, {"last_ts": self.clock.t - 20_000, "engines": {
            ACC: {"wallet": 1000.0, "position": pos, "pending": []}}})
        self.s.commit()

    def close(self):
        self.s.close()


class Mexc:
    """The MEXC executor as cmd_run builds it (Paper3Source on the config's paper_db), restartable with a new config."""

    def __init__(self, tmp_path, clock: Clock, paper_db: str):
        self.clock = clock
        self.fake = FakeMexc(wallet=100.0)
        self.fake.clock = clock
        self.note = ListNotifier()
        self.cfg = ExecConfig(account=ACC, paper_db=paper_db, db=str(tmp_path / "executor-mexc-live.db"), qty_scale=0.1,
                              risk=risk_cfg(tmp_path, max_leverage=40, max_notional_usd=10_000.0, max_loss_frac=0.35,
                                            daily_max_loss_usd=None, max_drawdown_pct=None, max_consecutive_losses=None),
                              exchange="mexc", mode="mainnet", budget_usd=100.0, sweep_every=1,
                              paper_env_file=str(tmp_path / "live.env"))
        self.store = None
        self.start()

    def start(self):
        self.store = ExecStore(self.cfg.db)
        kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda x: None)
        self.ex = Executor(self.cfg, MX.MexcClient("mk", "ms", **kw), Paper3Source(self.cfg.paper_db, self.cfg.account),
                           self.store, self.note, now_ms=self.clock, sleep=lambda x: None, env=LIVE_ENV,
                           keycheck=MX.MexcKeyCheckClient("mk", "ms", attested=True, **kw))
        self.ex.start()

    def restart(self, **change):
        """systemctl restart paperbot-executor-mexc after editing its config."""
        self.store.close()
        self.cfg = dataclasses.replace(self.cfg, **change)
        self.start()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def events(self, kind):
        return [(lv, txt, d) for lv, txt, d in self.store.conn.execute(
            "SELECT level, text, data FROM events WHERE kind = ? ORDER BY id", (kind,))]

    def trades(self):
        return self.store.conn.execute("SELECT key, symbol, exit_ts IS NOT NULL FROM trades ORDER BY entry_ts").fetchall()

    def plans(self, symbol):
        return [p["triggerPrice"] for p in self.fake.live_plans(symbol)]

    def close(self):
        self.store.close()


@pytest.fixture
def two(tmp_path):
    clock = Clock()
    old = Paper(str(tmp_path / "live-ac.db"), clock)
    new = Paper(str(tmp_path / "live15-mexc.db"), clock)
    m = Mexc(tmp_path, clock, old.path)
    yield clock, old, new, m
    m.close()
    old.close()
    new.close()


def _follow_one_old_trade(clock, old, m) -> str:
    """Before the switch: MEXC follows the -50 % paper bot through one whole trade (and is flat after it)."""
    t1 = clock.t - 30_000
    old.history(3, clock.t - 10 * 3_600_000)
    old.put(BTC, 1, 100.0, 40, stop_of(1, 100.0, 40, 0.50), t1)
    m.loop()
    assert m.fake.amt(B) == Decimal("0.4") and m.plans(B) == [pytest.approx(stop_of(1, 100.0, 40, 0.50), abs=0.1)]
    old.put(None)
    m.loop()
    assert m.fake.amt(B) == 0 and m.ex.trade is None
    return f"{ACC}|{BTC}|{t1}"


def test_switch_while_flat_skips_the_open_position_and_follows_the_next_entry(two):
    clock, old, new, m = two
    k1 = _follow_one_old_trade(clock, old, m)
    assert k1 in m.ex.done
    # the -35 % bot runs already (it was started first): its own history (trade ids 1.. like the old file's) and a position it
    # opened 10 minutes ago that the -50 % bot does not have
    new.history(5, clock.t - 20 * 3_600_000)
    q0 = clock.t - 600_000
    new.put(BTC, -1, 100.0, 40, stop_of(-1, 100.0, 40, 0.35), q0)
    # switch: MEXC shows 포지션: null; its config's paper_db changes; only the MEXC executor restarts
    m.restart(paper_db=new.path)
    m.loop()
    assert m.fake.amt(B) == 0 and m.ex.trade is None                    # not followed late
    late = m.events("late")
    assert late and late[-1][2] and f'"{ACC}|{BTC}|{q0}"' in late[-1][2] and "따라 하지 않습니다" in late[-1][1]
    # the start records say which paper database each start followed (old, then new); the record itself goes on
    starts = m.events("start")
    assert len(starts) == 2
    assert [f'"paper_db": "{p}"' in s[2] for s, p in zip(starts, (old.path, new.path))] == [True, True]
    assert f"(페이퍼 DB {new.path})" in starts[-1][1]
    assert m.trades() == [(k1, BTC, 1)] and k1 in m.ex.done and not m.events("paper_unreadable")
    meta = m.store.get_state("meta")
    assert meta["account"] == ACC and meta["exchange"] == "mexc" and meta["mode"] == "mainnet"
    # the old paper bot keeps trading: never acted on any more
    old.put(BTC, 1, 100.0, 40, stop_of(1, 100.0, 40, 0.50), clock.t - 10_000)
    m.loop(2)
    assert m.fake.amt(B) == 0
    # the new bot closes its position, then enters ETH: followed at once, with ITS -35 % stop
    new.put(None)
    m.loop()
    q1 = clock.t - 20_000
    s35 = stop_of(1, 50.0, 30, 0.35)
    new.put(ETH, 1, 50.0, 30, s35, q1)
    m.loop()
    assert m.fake.amt(E) == Decimal("0.4") and m.fake.amt(B) == 0
    assert m.plans(E) == [pytest.approx(s35, abs=0.01)] and abs(s35 / 50.0 - 1) == pytest.approx(0.35 / 30 - RT)
    assert m.ex.trade["key"] == f"{ACC}|{ETH}|{q1}"
    # its lock moves the exchange stop; its exit closes
    m.fake.set_price(E, 52.0)
    new.put(ETH, 1, 50.0, 30, 50.2, q1)
    m.loop()
    assert m.plans(E) == [pytest.approx(50.2, abs=0.01)]
    new.put(None)
    m.loop()
    assert m.fake.amt(E) == 0 and m.ex.trade is None
    assert m.trades() == [(k1, BTC, 1), (f"{ACC}|{ETH}|{q1}", ETH, 1)]
    assert not m.events("paper_unreadable") and not m.events("loop_error")


def test_a_position_opened_just_before_the_restart_is_followed_like_after_any_restart(two):
    clock, old, new, m = two
    _follow_one_old_trade(clock, old, m)
    q = clock.t - 60_000                                                 # 60 s old: inside max_entry_age_s (180 s)
    new.put(ETH, -1, 50.0, 30, stop_of(-1, 50.0, 30, 0.35), q)
    m.restart(paper_db=new.path)
    m.loop()
    assert m.fake.amt(E) == Decimal("-0.4") and m.ex.trade["key"] == f"{ACC}|{ETH}|{q}" and not m.events("late")


def test_a_new_paper_bot_that_has_not_started_is_unreadable_until_it_writes(two):
    clock, old, new, m = two
    _follow_one_old_trade(clock, old, m)
    empty = str(m.cfg.db).replace("executor-mexc-live.db", "never-started.db")
    Store3(empty).close()                                                # the file is there, no account state yet
    m.restart(paper_db=empty)
    m.loop()
    bad = m.events("paper_unreadable")
    assert bad and bad[0][0] == "CRITICAL" and "새 진입은 하지 않습니다" in bad[0][1]
    assert m.fake.amt(B) == 0 and m.fake.amt(E) == 0
    # the guide's order: the -35 % bot runs first; pointing at its database then works at once
    m.restart(paper_db=new.path)
    new.put(ETH, 1, 50.0, 30, stop_of(1, 50.0, 30, 0.35), clock.t - 10_000)
    m.loop()
    assert m.fake.amt(E) == Decimal("0.4")


def test_why_only_at_position_null_an_open_live_position_is_closed_at_once(two):
    clock, old, new, m = two
    t1 = clock.t - 30_000
    old.put(BTC, 1, 100.0, 40, stop_of(1, 100.0, 40, 0.50), t1)
    m.loop()
    assert m.fake.amt(B) == Decimal("0.4")
    new.put(None)
    m.restart(paper_db=new.path)                                         # the guide forbids this: MEXC is not flat
    m.loop()
    assert m.fake.amt(B) == 0 and m.ex.trade is None
    assert m.events("exit") and "paper 청산" in m.events("exit")[-1][1]
