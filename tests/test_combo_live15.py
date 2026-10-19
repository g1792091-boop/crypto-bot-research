"""The 15-strategy live bot of 2026-10-19 (deploy/combo.live15.json) on paperbot/combo.py:

- the two-part ladder (paperbot/ladder2.py): 11 -> 10, 15 -> 12, 20 -> 17, 25 -> 22 ... and the old form unchanged;
- the stop at -50% net ROE (fees and slippage of both sides in) and its realised ROE;
- the engine's lock steps with the new ladder, and the early exit only before the first lock;
- no_chase members: a long at the top of the 7-day / 24-hour range is FILTERED, one in the middle is entered, a filtered
  signal still turns the strategy (closes its open position with early_exit), too few hours means no entry;
- a new config on the same database drops the old members' queued signals;
- the config file itself: no problems, 15 members, 4 no_chase, check-config's words."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from paperbot import combo as C
from paperbot.ladder import LadderSpec
from paperbot.ladder2 import ComboLadder
from paperbot.margin import BracketTier, Brackets
from paperbot.models import Bar, Signal
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

ROOT = Path(__file__).resolve().parent.parent
CFG15 = ROOT / "deploy" / "combo.live15.json"
MIN = 60_000
HOUR = 3_600_000
T0 = 1_791_158_400_000                        # 2026-10-05 00:00 UTC, a Monday (09:00 KST)
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
PX = {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0, "SOLUSDT": 150.0, "DOGEUSDT": 0.2, "LTCUSDT": 80.0, "BCHUSDT": 400.0}
SPECS = {s: {"qty_step": 0.0001 if s == "BTCUSDT" else 0.001, "min_notional": 5.0, "tick_size": 0.01} for s in SYMS}
BRK = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 50, 0.005, 300.0)])
BRACKETS = {s: BRK for s in SYMS}
LAD15 = {"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03}


# ---------------------------------------------------------------- the ladder
def test_two_part_ladder_locks_like_the_owners_said():
    lad = ComboLadder.of(LAD15)
    assert lad.two_part
    for best, lock in [(0.0, None), (0.109, None), (0.11, 0.10), (0.149, 0.10), (0.15, 0.12), (0.199, 0.12),
                       (0.20, 0.17), (0.25, 0.22), (0.30, 0.27), (0.349, 0.27), (0.35, 0.32)]:
        got = lad.lock_for(best)
        assert (got is None and lock is None) or abs(got - lock) < 1e-9, (best, got, lock)
    assert lad.next_after(None) == pytest.approx((0.10, 0.11))
    assert lad.next_after(0.10) == pytest.approx((0.12, 0.15))
    assert lad.next_after(0.12) == pytest.approx((0.17, 0.20))
    assert lad.next_after(0.17) == pytest.approx((0.22, 0.25))
    assert lad.trigger_of(0.10) == pytest.approx(0.11) and lad.trigger_of(0.22) == pytest.approx(0.25)
    assert [lad.index(x) for x in (None, 0.10, 0.12, 0.17, 0.22)] == [0, 1, 2, 3, 4]
    assert lad.problems() == []
    assert "15%에서 12%" in lad.describe() and "20%에서 17%" in lad.describe()


def test_old_form_is_the_rule_bots_ladder():
    for first, step, gap in [(0.10, 0.03, 0.01), (0.10, 0.05, 0.02), (0.10, 0.05, 0.01)]:
        a, b = ComboLadder(first, step, gap), LadderSpec(first, step, gap)
        for k in range(0, 600):
            best = k / 1000
            x, y = a.lock_for(best), b.lock_for(best)
            assert (x is None and y is None) or abs(x - y) < 1e-12
    assert ComboLadder.of({"first_lock": 0.1}) is None
    bad = ComboLadder.of({**LAD15, "next_trigger": 0.105}).problems()
    assert bad and "next_trigger" in bad[0]
    assert ComboLadder.of({"first_lock": 0.1, "step": 0.05, "trigger_gap": 0.01, "next_trigger": 0.15}).problems()


# ---------------------------------------------------------------- the config file
def test_live15_config_is_clean_and_has_the_owners_15():
    raw = json.loads(CFG15.read_text(encoding="utf-8"))
    cfg = C.ComboConfig.from_dict(raw)
    assert cfg.problems() == []
    ms = C.resolve_members(cfg.members)
    assert [m.label for m in ms] == [
        "V39_ALL@1h", "S3_CMO_SANDWICH@30m", "N20_EMA9_CHOP@30m", "N05_PSAR_POC@30m", "S3_CMO_SANDWICH@1h",
        "N06_MACD_ORB@30m", "OBV_S@30m", "F9_IFVG@1h", "S6_EMA_DMI_ADX@1h", "F15_ORB@30m", "N08_ICHI_WR@30m",
        "F3_BOS@30m", "F7_RF_ONLY@1h", "F9_FVG@1h", "N12_ICHI_AO@30m"]
    assert [m.label for m in ms if m.no_chase] == ["F3_BOS@30m", "F7_RF_ONLY@1h", "F9_FVG@1h", "N12_ICHI_AO@30m"]
    assert all(not m.custom and m.research is None and m.tf in ("30m", "1h") for m in ms)
    assert cfg.stop_net and cfg.early_exit == "own" and cfg.early_exit_until_lock
    assert cfg.no_weekend and cfg.macro_blackout_min == 30 and cfg.us_open_pause_min == 30
    assert cfg.lev_of("BTCUSDT") == 40 and cfg.lev_of("SOLUSDT") == 30 and cfg.margin == 0.4
    assert cfg.ladder_spec == ComboLadder.of(LAD15)
    # the executors follow this database: the same path as the A+C bot's
    assert cfg.db == json.loads((ROOT / "deploy" / "executor.live-bybit.json").read_text())["paper_db"]
    assert cfg.db == json.loads((ROOT / "deploy" / "executor.live-mexc.json").read_text())["paper_db"]


def test_check_config_words(capsys):
    assert C.main(["check-config", "--config", str(CFG15)]) == 0
    out = capsys.readouterr().out
    for want in ("순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)", "15%에서 12%", "20%에서 17%",
                 "첫 잠금 +10% 전까지만", "추격 진입 막기: 4개 매매법", "준비됨"):
        assert want in out, want


def test_new_keys_are_checked():
    base = json.loads(CFG15.read_text(encoding="utf-8"))
    for over, want in [({"stop": {"mode": "roe", "roe": 0.5, "net": "yes"}}, "stop.net"),
                       ({"stop": {"mode": "roe", "roe": 0.02, "net": True}}, "수수료보다"),
                       ({"stop": {"mode": "roe", "roe": 0.5, "nett": True}}, "stop에 알 수 없는"),
                       ({"ladder": {**LAD15, "next_gap": None}}, "둘 다"),
                       ({"ladder": {**LAD15, "extra": 1}}, "ladder에 알 수 없는"),
                       ({"early_exit": None}, "early_exit_until_lock")]:
        probs = " | ".join(C.ComboConfig.from_dict({**base, **over}).problems())
        assert want in probs, (over, probs)
    with pytest.raises(C.ComboError, match="no_chase"):
        C.resolve_members([{"strategy": "V39_ALL", "tf": "1h", "no_chase": "yes"}])


# ---------------------------------------------------------------- the engine
def _cfg(tmp_path, **kw):
    raw = json.loads(CFG15.read_text(encoding="utf-8"))
    raw.update(paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "combo.db"), telegram=False)
    raw.update(kw)
    return C.ComboConfig.from_dict(raw)


def _engine(cfg):
    return C.ComboEngine(C.settings_of(cfg), BRACKETS, combo=cfg, symbol_specs=SPECS)


def _sig(sym="BTCUSDT", side=1, ref=None, member="V39_ALL@1h", tf="1h", ts=T0 - 1):
    ref = PX[sym] if ref is None else ref
    return Signal(ts=ts, symbol=sym, timeframe=tf, strategy_id=member.split("@")[0], side=side, stop_price=0.0,
                  tier="best", score=3.0, atr=ref * 0.003,
                  meta={"ref_price": ref, "member_order": 1, "member": member})


def _bar(sym, t, o, h=None, l=None, c=None):
    h = max(o, c or o) if h is None else h
    l = min(o, c or o) if l is None else l
    return Bar(sym, t, t + MIN - 1, o, h, l, o if c is None else c)


def test_net_stop_distance_and_its_realised_roe(tmp_path):
    cfg = _cfg(tmp_path)
    e = _engine(cfg)
    rt = e.s.round_trip_cost
    s, why = e._with_stop(_sig("BTCUSDT"), _bar("BTCUSDT", T0, 60000.0))
    assert why is None and s.meta["stop_dist"] == pytest.approx(60000 * (0.5 / 40 - rt))
    s, _ = e._with_stop(_sig("SOLUSDT"), _bar("SOLUSDT", T0, 150.0))
    assert s.meta["stop_dist"] == pytest.approx(150 * (0.5 / 30 - rt))
    # enter BTC long at 60000, then a bar falls through the stop: the trade loses ~50% of its margin, costs in
    for sym, px, lev in (("BTCUSDT", 60000.0, 40), ("SOLUSDT", 150.0, 30)):
        e = _engine(cfg)
        e.submit(_sig(sym, ref=px))
        e.step({sym: _bar(sym, T0, px)})
        p = e.position
        assert p is not None and p.leverage == lev
        e.step({sym: _bar(sym, T0 + MIN, px, l=px * 0.97, c=px * 0.975)})
        assert e.position is None
        t = e.trades[-1]
        assert t.exit_reason == "SL" and t.roe == pytest.approx(-0.50, abs=0.006), (sym, t.roe)
        # 40% margin: the account loses about a fifth (under the 35% cap: no size cut)
        assert 0.18 < -t.pnl / 1000 < 0.22


def test_engine_steps_the_two_part_ladder(tmp_path):
    e = _engine(_cfg(tmp_path))
    e.submit(_sig("BTCUSDT", ref=60000.0))
    e.step({"BTCUSDT": _bar("BTCUSDT", T0, 60000.0)})
    p = e.position
    rt = e.s.round_trip_cost

    def px_at(roe):                       # the price where net ROE reaches roe (no funding)
        return p.entry_price * (1 + (roe / 40 + rt))

    e.step({"BTCUSDT": _bar("BTCUSDT", T0 + MIN, px_at(0.105), h=px_at(0.112))})
    assert e.position.lock_roe == pytest.approx(0.10)
    e.step({"BTCUSDT": _bar("BTCUSDT", T0 + 2 * MIN, px_at(0.14), h=px_at(0.16))})
    assert e.position.lock_roe == pytest.approx(0.12)              # not 0.15 (the old form would say 0.15)
    e.step({"BTCUSDT": _bar("BTCUSDT", T0 + 3 * MIN, px_at(0.19), h=px_at(0.205))})
    assert e.position.lock_roe == pytest.approx(0.17)
    e.step({"BTCUSDT": _bar("BTCUSDT", T0 + 4 * MIN, px_at(0.18), l=px_at(0.15), c=px_at(0.16))})
    assert e.position is None
    t = e.trades[-1]
    # the lock price is the engine's own (paperbot/ladder.py roe_price, both sides' slippage in): the realised net ROE
    # is the lock plus one slippage's worth (40 x 0.02%), never under it
    assert t.exit_reason == "LOCK" and 0.17 <= t.roe <= 0.17 + 40 * e.s.slippage_frac + 0.001


def test_early_exit_only_before_the_first_lock(tmp_path):
    for until_lock, locked, closes in [(True, False, True), (True, True, False), (False, True, True)]:
        e = _engine(_cfg(tmp_path, early_exit_until_lock=until_lock))
        e.submit(_sig("BTCUSDT", ref=60000.0))
        e.step({"BTCUSDT": _bar("BTCUSDT", T0, 60000.0)})
        p = e.position
        t = T0 + MIN
        if locked:
            hi = p.entry_price * (1 + 0.12 / 40 + e.s.round_trip_cost)
            e.step({"BTCUSDT": _bar("BTCUSDT", t, hi * 0.9999, h=hi)})
            assert e.position.lock_roe is not None
            t += MIN
        e.exit_signal(_sig("BTCUSDT", side=-1, ts=t - 1))
        e.step({"BTCUSDT": _bar("BTCUSDT", t, e.position.mfe_price if locked else 60000.0)})
        assert (e.position is None) == closes, (until_lock, locked)
        if closes:
            assert e.trades[-1].exit_reason == "REV"


# ---------------------------------------------------------------- no_chase in the runner
def test_chase_check_edges():
    k = (T0 // HOUR)
    hours = {k - j: (110.0, 90.0) for j in range(1, 169)}                  # 7 days between 90 and 110
    assert C.chase_check(hours, T0, 1, 100.0) == (False, "")
    c, why = C.chase_check(hours, T0, 1, 106.5)                              # 82% of the 7-day range: a chase
    assert c is True and "7일" in why
    assert C.chase_check(hours, T0, -1, 106.5)[0] is False                  # a short up there is fine
    assert C.chase_check(hours, T0, -1, 92.0)[0] is True                    # a short at the bottom is a chase
    near = dict(hours)
    for j in range(1, 25):
        near[k - j] = (101.0, 99.0)                                          # the last day a tight 99-101 range
    c, why = C.chase_check(near, T0, 1, 100.9)
    assert c is True and "24시간" in why                                     # top 10% of the day
    assert C.chase_check({k - j: (110.0, 90.0) for j in range(1, 10)}, T0, 1, 100.0)[0] is None
    only_day = {k - j: (110.0, 90.0) for j in range(1, 25)}                 # 24 hours, not 150 of 168: the day only
    assert C.chase_check(only_day, T0, 1, 107.0)[0] is False


class World:
    """paper3.db with a week of hourly history (BTC between 58,000 and 62,000, the last day between 59,500 and
    60,500) and the 15-strategy bot reading it."""

    def __init__(self, tmp_path, **kw):
        self.paper = Store3(str(tmp_path / "paper3.db"))
        self.px = dict(PX)
        rows = []
        for j in range(170, 0, -1):                                           # one row per hour: chase_hours needs no more
            t = T0 - j * HOUR
            for s in SYMS:
                o = self.px[s]
                w = 0.0333 if j > 24 else 0.00833                             # 58,000-62,000, then 59,500-60,500
                rows.append(self._row(t, s, o, o * (1 + w), o * (1 - w), o))
        self.paper.live_bars(rows)
        self.paper.commit()
        self.cfg = _cfg(tmp_path, **kw)
        self.note = ListNotifier()
        self.now = T0
        self.add_minutes(T0 - 10 * MIN, 10)
        self.members = C.resolve_members(self.cfg.members)
        self.store = Store3(self.cfg.db)
        self.book = C.build_book(self.cfg, C.settings_of(self.cfg), BRACKETS, self.store, self.note, SPECS)
        self.run = C.ComboRunner(self.cfg, self.members, self.book, self.store, self.note, None,
                                 now_ms=lambda: self.now, prices=lambda: {})

    @staticmethod
    def _row(t, s, o, h, l, c):
        return {"ts": t, "symbol": s, "open": o, "high": h, "low": l, "close": c, "volume": 1.0, "mark_open": o,
                "mark_high": h, "mark_low": l, "mark_close": c, "close_time": t + MIN - 1, "processed_at": t + MIN + 5000}

    def add_minutes(self, start, n, px=None):
        rows = []
        for k in range(n):
            t = start + k * MIN
            for s in SYMS:
                o = (px or {}).get(s, self.px[s])
                rows.append(self._row(t, s, o, o * 1.0001, o * 0.9999, o))
                self.px[s] = o
        self.paper.live_bars(rows)
        self.paper.commit()

    def signal(self, label, sym, side, bar_close):
        strategy, tf = label.split("@")
        ref = self.px[sym]
        self.paper.log_signals([{"bar_close": bar_close, "timeframe": tf, "strategy": strategy, "symbol": sym,
                                 "side": side, "atr": ref * 0.003, "ref_price": ref, "ref_time": bar_close + 20_000,
                                 "delay_ms": 20_000, "status": "SUBMITTED", "data": {"ctx": {}}}])
        self.paper.commit()

    def step_to(self, bar_close):
        last = self.book.last_ts if self.book.last_ts is not None else T0 - MIN
        self.add_minutes(last + MIN, (bar_close - last) // MIN)
        self.now = bar_close + 65_000
        self.run.poll()

    def status(self, label):
        return self.store.conn.execute("SELECT status, data FROM signal_log WHERE strategy = ? ORDER BY id DESC LIMIT 1",
                                       (label,)).fetchone()


def test_runner_blocks_a_chase_and_enters_the_middle(tmp_path):
    w = World(tmp_path)
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30, px={"BTCUSDT": 61_800.0})          # BTC near the top of its 7-day range (58,000-62,000)
    w.signal("F3_BOS@30m", "BTCUSDT", 1, B)                  # a no_chase member's long there: not taken
    w.step_to(B)
    st, data = w.status("F3_BOS@30m")
    assert st == "FILTERED" and "추격 진입 막기" in json.loads(data)["why"]
    assert w.book.engines[C.ACCOUNT].position is None
    assert w.run.counts["F3_BOS@30m"] == {"filtered": 1}
    B2 = B + 30 * MIN
    w.add_minutes(B + MIN, 29, px={"BTCUSDT": 60_000.0})     # back in the middle
    w.signal("F3_BOS@30m", "BTCUSDT", 1, B2)
    w.step_to(B2)
    p = w.book.engines[C.ACCOUNT].position
    assert p is not None and p.side == 1 and p.signal.meta["member"] == "F3_BOS@30m"
    # the same top-of-range long from a member without no_chase is entered (only the four take the rule)
    (tmp_path / "b").mkdir()
    w2 = World(tmp_path / "b")
    w2.now = T0 + 5_000
    w2.run.poll()
    w2.add_minutes(T0, 30, px={"BTCUSDT": 61_800.0})
    w2.signal("N20_EMA9_CHOP@30m", "BTCUSDT", 1, B)
    w2.step_to(B)
    assert w2.book.engines[C.ACCOUNT].position is not None


def test_a_blocked_signal_still_turns_its_strategy(tmp_path):
    w = World(tmp_path)
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30, px={"BTCUSDT": 60_000.0})
    w.signal("F3_BOS@30m", "BTCUSDT", 1, B)
    w.step_to(B)
    assert w.book.engines[C.ACCOUNT].position is not None
    B2 = B + 30 * MIN
    w.add_minutes(B + MIN, 29, px={"BTCUSDT": 59_550.0})     # near the day's low (above the -50% stop): a short is a chase
    w.signal("F3_BOS@30m", "BTCUSDT", -1, B2)
    w.step_to(B2)
    e = w.book.engines[C.ACCOUNT]
    assert e.position is None and e.trades[-1].exit_reason == "REV"        # the long is closed, no short opened
    st, data = w.status("F3_BOS@30m")
    assert st == "FILTERED" and "추격" in json.loads(data)["why"]


def test_too_few_hours_means_no_entry(tmp_path):
    w = World(tmp_path)
    w.paper.conn.execute("DELETE FROM live_bars WHERE ts < ?", (T0 - 12 * HOUR,))
    w.paper.commit()
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal("F9_FVG@1h", "BTCUSDT", 1, B)
    w.step_to(B)
    st, data = w.status("F9_FVG@1h")
    assert st == "FILTERED" and "모자람" in json.loads(data)["why"]
    assert w.book.engines[C.ACCOUNT].position is None


def test_a_new_config_drops_the_old_members_queued_signals(tmp_path):
    w = World(tmp_path)
    old = dataclasses.asdict(_sig("BTCUSDT", member="F5_BOX_HTF@1h#94~x"))
    keep = dataclasses.asdict(_sig("BTCUSDT", member="V39_ALL@1h"))
    w.store.put_state(C.STATE_KEY, T0, {"cursor": 0, "queue": [{"bar_close": T0 + HOUR, "signal": old},
                                                                {"bar_close": T0 + HOUR, "signal": keep}],
                                         "breaks": [{"member": "F5_BOX_HTF@1h#94~x", "signal": old, "t0": T0, "until": T0 + HOUR}],
                                         "counts": {}})
    w.store.commit()
    run = C.ComboRunner(w.cfg, w.members, w.book, w.store, w.note, None, now_ms=lambda: T0, prices=lambda: {})
    assert [q.signal["meta"]["member"] for q in run.queue] == ["V39_ALL@1h"]
    assert run.breaks == []
    alerts = [r[0] for r in w.store.conn.execute("SELECT text FROM alerts").fetchall()]
    assert any("설정이 바뀜" in a for a in alerts)
