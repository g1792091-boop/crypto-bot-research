"""거래소 기준 익절 (owners 10-20) on the live side's checks, messages and site: an executor with ``"ladder_from": "own"``
parts from the paper by design (its own locks, its own exits, still open after the paper's price exit). None of that is an
alarm, all of it is shown: paperbot/livecheck.py (the 🔒 / ✅ / ❌ lines, the loss card, "lost where the paper won", the
costs, the morning check), paperbot/livemissed.py (no "did not follow") and the 8093 site's 포지션 card
(dash/more/livepos.py, livebots.py, screens/livebots-pos.js).

The executor records are the real executor's (paperbot/executor.py on the fake Bybit and MEXC, tests/
test_executor_own_ladder.py ``Rig``) following one real paper database; nothing here is hand-written into them."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from paperbot import livecheck as LC
from paperbot import livemissed as LM
from paperbot.dash.more import livebots as L
from paperbot.dash.more import livepos as P
from paperbot.ladder import roe_price
from paperbot.notify import INFO
from test_executor_own_ladder import (BTC, BYBIT_RT, COSTS, DOGE, MIN, Clock, Paper, Rig, paper_stop)
from test_executor_own_ladder import no_network  # noqa: F401  (autouse: no network here either)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
UNITS = lambda unit: ("active", "enabled")            # noqa: E731  (both executors meant to run)
ENTRY = 0.07937


def info(rig: Rig, name: str, ladder_from: str = "own") -> LC.ExecInfo:
    return LC.ExecInfo(name=name, config="-", unit=f"paperbot-executor-{name}", db=rig.cfg.db, light_n=0, light_min=0.85,
                       exchange=name, budget=100.0, kill_file="/nonexistent/STOP", ladder_from=ladder_from)


class Two:
    """Bybit and MEXC ("own") following one paper bot, on one clock."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.clock = Clock()
        self.paper = Paper(str(tmp_path / "live-ac.db"), self.clock)
        self.by = Rig(tmp_path / "b", exchange="bybit", prices={DOGE: 0.07924, BTC: 10_000.0}, symbols=(DOGE,),
                      net_costs=COSTS, clock=self.clock, paper=self.paper)
        self.mx = Rig(tmp_path / "m", exchange="mexc", symbols=(DOGE,), net_costs=COSTS, clock=self.clock,
                      paper=self.paper)
        self.mx.price(DOGE, 0.07925)
        self.infos = [info(self.by, "bybit"), info(self.mx, "mexc")]
        self.src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=self.paper.path,
                              rule_db=str(tmp_path / "p3.db"), combo_config="-", executors=self.infos)
        self.out = LC.open_out(self.src.db)
        self.sent: list = []

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.by.ex.loop_once()
            self.mx.ex.loop_once()

    def prices(self, by: float, mx: float):
        self.by.price(DOGE, by)
        self.mx.price(DOGE, mx)

    def send(self, level, text):
        self.sent.append((level, text))
        return True

    def trade_pass(self):
        return LC.trade_pass(self.src, self.out, self.clock.t, None, self.send, infos=self.infos, units=UNITS)

    def close(self):
        self.out.close()
        self.by.close()
        self.mx.close()
        self.paper.close()


@pytest.fixture
def two(tmp_path):
    w = Two(tmp_path)
    yield w
    w.close()


def test_the_doge_day_on_telegram_both_lock_on_their_own_fills_and_close_before_the_paper(two):
    """10-20: the paper enters at 0.07937; Bybit fills 0.07924, MEXC 0.07925; the exchanges top at 0.07974. Each executor
    locks +10 % on its own fill (a 🔒 line each, in the existing style); the price falls back through each one's lock
    (their own stops close them: ✅ 청산 (거래소 기준), the paper still open); then the paper stops out. Its loss card
    names each executor's own exit. The own exits (a win where the paper lost, another exit time and price) are never a
    "실거래-페이퍼 차이", and neither is the 16 bps BETTER entry (owners 10-20, decision 2: only a worse entry alarms)."""
    two.paper.put(DOGE, 1, ENTRY, 30, paper_stop(1, ENTRY, 30), two.clock.t - 30_000, 50_000.0)
    two.loop()
    assert two.by.ex.trade["entry_price"] == 0.07924 and two.mx.ex.trade["entry_price"] == 0.07925
    two.clock.t += MIN
    two.prices(0.07974, 0.07974)
    two.prices(0.07966, 0.07970)
    two.loop()
    assert two.by.stops(DOGE) == [0.07963] and two.mx.stops(DOGE) == [0.07968]
    got = two.trade_pass()
    locks = {k: t for k, _key, _lv, t in got if k.startswith("lock:")}
    assert set(locks) == {"lock:bybit", "lock:mexc"} and all(lv == INFO for lv, _t in two.sent)
    assert locks["lock:bybit"].split("\n") == [
        "🔒 바이비트 잠금 +10% (자기 체결가 기준) · 손절 0.07963",
        f"DOGE 롱 · 체결 0.07924 · 거래소 최고 0.07974 (순ROE {30 * (0.07974 / 0.07924 - 1 - BYBIT_RT):+.1%}) · 거래소 기준"]
    assert locks["lock:mexc"].startswith("🔒 MEXC 잠금 +10% (자기 체결가 기준) · 손절 0.07968\nDOGE 롱 · 체결 0.07925")
    assert any(k == "entry" for k, *_r in got)
    assert not [k for k, *_r in got if k == "lock"]                   # the paper has not locked: no paper 🔒
    assert not [k for k, *_r in two.trade_pass() if k.startswith("lock")]   # once each
    # back down through both locks: their own stops close them, the paper is still open
    two.prices(0.07962, 0.07967)
    two.loop()
    assert two.by.ex.trade is None and two.mx.ex.trade is None and two.paper.pos is not None
    got = two.trade_pass()
    exits = {k: t for k, _key, _lv, t in got if k.startswith("exit:")}
    assert set(exits) == {"exit:bybit", "exit:mexc"}
    lines = exits["exit:bybit"].split("\n")
    assert lines[0].startswith("✅ 바이비트 청산 (거래소 기준) · DOGE 롱 · 순ROE +")
    assert lines[1].endswith("· 자기 잠금 +10% 손절 발동") and lines[2] == "페이퍼: 아직 열림 (따로 닫혀요)"
    assert "알람 아님" in lines[3]
    # the paper stops out later (its own stop on its own prices): a loss card, quiet; each executor's own exit on it
    two.clock.t += 30 * MIN
    two.paper.exit("SL", paper_stop(1, ENTRY, 30))
    two.loop()
    cards = LC.cards_pass(two.src, two.out, two.clock.t, None, send=two.send, infos=two.infos)
    (card,) = cards
    outs = card["executors"]
    assert {o["name"]: (o["status"], o["own_exit"], o["own_lock"]) for o in outs} == {
        "bybit": ("followed", True, pytest.approx(0.1)), "mexc": ("followed", True, pytest.approx(0.1))}
    assert outs[0]["entry_bps"] == pytest.approx((0.07924 - ENTRY) / ENTRY * 1e4) and outs[0]["exit_bps"] is None
    # the entry is 16 bps BETTER than the paper's (a long filled lower): shown, quiet, no "실거래-페이퍼 차이"
    assert outs[0]["entry_bps"] < -LC.GAP_BPS
    assert card["gap"] is False and card["label"] != "실거래-페이퍼 차이" and card["loud"] is False
    assert not any(lv != INFO for lv, _t in two.sent) and "🚨" not in card["text"]
    assert "· 진입 -16.4" in card["text"] and "진입이 페이퍼보다 유리" in card["text"]
    same_entry = [{**o, "entry_bps": 1.0} for o in outs]
    assert LC.live_gap(same_entry, card["exit_time"]) is False                  # the own exits alone: never a gap
    assert LC.live_gap([{**o, "own_exit": False} for o in same_entry], card["exit_time"]) is True   # "paper": a gap
    # the same 16 bps the other way (a worse entry) still alarms, for "own" and "paper" alike
    worse = [{**o, "entry_bps": -o["entry_bps"]} for o in outs]
    assert LC.live_gap(worse, card["exit_time"]) is True
    assert LC.live_gap([{**o, "own_exit": False, "pnl": -1.0, "exit_ts": card["exit_time"]} for o in worse],
                       card["exit_time"]) is True
    assert "· 거래소 기준 청산 " in card["text"] and "(자기 잠금 +10%)" in card["text"]
    # the morning check: shown in its own block, no slippage flag from the different exits
    reps = [LC.exec_report(ex, LC.paper_trades(LC.open_ro(two.paper.path), LC.ACCOUNT), two.clock.t - 3 * 3_600_000,
                           two.clock.t + MIN, two.clock.t) for ex in two.infos]
    for r in reps:
        c = r["cost"]
        assert c["own_exits"] == 1 and c["exit_bps"] is None and c["flags"] == [] and c["unmeasured"] == 0
        assert r["costs"][0]["exit_gap_bps"] is not None
    block = LC.own_lines(reps)
    assert block[0] == "거래소 기준 익절(어제, 페이퍼와 따로 닫힌 실거래 · 알람 아님)"
    assert block[1].startswith("- 바이비트 ") and "(자기 잠금 +10%) · 페이퍼 손절 " in block[1]
    assert any("1번은 거래소 기준으로 따로 닫혀 청산 가격은 페이퍼와 비교하지 않음" in ln for ln in LC.cost_lines(reps))


def test_a_worse_entry_of_the_same_size_still_alarms_on_the_loss_card(tmp_path):
    """Decision 2 (owners 10-20) the other way: the paper long at 0.07911, Bybit filled 0.07924 (16.4 bps WORSE). The
    live position's own stop closes it, then the paper stops out: the loss card says "실거래-페이퍼 차이", loud."""
    clock = Clock()
    paper = Paper(str(tmp_path / "live-ac.db"), clock)
    by = Rig(tmp_path / "b", exchange="bybit", prices={DOGE: 0.07924, BTC: 10_000.0}, symbols=(DOGE,), net_costs=COSTS,
             clock=clock, paper=paper)
    out = LC.open_out(str(tmp_path / "livecheck.db"))
    ex = info(by, "bybit")
    src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=paper.path, rule_db=str(tmp_path / "p3.db"),
                     combo_config="-", executors=[ex])
    sent = []
    try:
        worse = 0.07911
        paper.put(DOGE, 1, worse, 30, paper_stop(1, worse, 30), clock.t - 30_000, 50_000.0)
        by.loop()
        assert by.ex.trade["entry_price"] == 0.07924
        by.price(DOGE, by.ex.trade["stop"] - 0.00001)                 # its own stop first
        by.loop()
        assert by.ex.trade is None
        clock.t += 5 * MIN
        paper.exit("SL", paper_stop(1, worse, 30))
        (card,) = LC.cards_pass(src, out, clock.t, None, send=lambda lv, tx: sent.append((lv, tx)) or True, infos=[ex])
        (o,) = card["executors"]
        assert o["own_exit"] is True and o["entry_bps"] == pytest.approx((0.07924 - worse) / worse * 1e4)
        assert o["entry_bps"] > LC.GAP_BPS
        assert card["gap"] is True and card["label"] == "실거래-페이퍼 차이" and card["loud"] is True
        assert sent[0][0] == LC.CRITICAL and sent[0][1].startswith("🚨 ") and "진입이 페이퍼보다 유리" not in sent[0][1]
    finally:
        out.close()
        by.close()
        paper.close()


def test_a_paper_entry_left_out_while_the_own_position_stays_is_a_quiet_missed_signal(two):
    """Decision 1 (owners 10-20) on the checks and the site: Bybit stays on its own after the paper's stop-out, the paper
    enters again, Bybit leaves that entry out ("own_busy"). Not "실거래가 페이퍼를 따라가지 않았습니다" (CRITICAL); the 🟢
    message says why, plainly; it is a missed signal of the executor in livemissed and on the 8093 site (why_missed)."""
    two.paper.put(DOGE, 1, ENTRY, 30, paper_stop(1, ENTRY, 30), two.clock.t - 30_000, 50_000.0)
    two.loop()
    two.paper.exit("SL", 0.0790)
    two.loop()
    assert two.by.ex.trade["paper_exit"]["action"] == "stay" and two.mx.ex.trade["paper_exit"]["action"] == "stay"
    two.clock.t += 10 * MIN
    entry2 = two.clock.t - 20_000
    two.paper.put(DOGE, -1, 0.0792, 30, paper_stop(-1, 0.0792, 30), entry2, 50_000.0)
    two.loop(2)
    key = f"{LC.ACCOUNT}|{DOGE}|{entry2}"
    assert two.by.ex.trade["key"] != key and two.by.amt(DOGE) > 0 and two.mx.amt(DOGE) > 0      # both still long
    for r in (two.by, two.mx):
        (lv, _text, data), = r.events("own_busy")
        assert lv == "INFO" and data["key"] == key
    two.clock.t += 4 * MIN                                             # past FOLLOW_MS
    two.loop()
    conds, judged, _seen = LC.watch_conditions(two.src, two.clock.t, units=UNITS, exists=lambda p: False)
    assert {"follow:bybit:", "follow:mexc:"} <= judged
    assert not [c for c in conds if c.key.startswith("follow:")], [c.text for c in conds]
    for ex, r in zip(two.infos, (two.by, two.mx)):
        st = LC.entry_state(ex, LC.open_ro(r.cfg.db), key, [], entry2, True)
        assert st == {"state": "busy"}
        assert LC.entry_exec_line(ex, st, DOGE).endswith("⏸ 자기 포지션(거래소 기준)을 들고 있어 따라가지 않음")
    # the 8093 site: a missed signal with its reason
    rec = L.read_exec(two.by.cfg.db, two.clock.t)
    w = L.why_missed(rec, {"symbol": DOGE, "entry_time": entry2}, LC.ACCOUNT)
    assert w["state"] == "missed" and w["why_kind"] == "own_busy" and "자기 포지션(거래소 기준)" in w["why_ko"]
    # livemissed: a row of the executor group, with that reason
    res = LM.missed_pass(two.src, two.out, two.clock.t, log=lambda _m: None)
    assert "error" not in res and res["exec"] == 2
    rows = two.out.execute("SELECT executor, why_kind, why FROM missed WHERE grp = 'exec' ORDER BY executor").fetchall()
    assert [(e, k) for e, k, _w in rows] == [("bybit", "own_busy"), ("mexc", "own_busy")]
    assert all("자기 포지션(거래소 기준)" in w for _e, _k, w in rows)
    # the paper closes it (a loss): its card says each executor left it out, quietly
    two.clock.t += MIN
    two.paper.exit("SL", paper_stop(-1, 0.0792, 30))
    (card,) = [c for c in LC.cards_pass(two.src, two.out, two.clock.t, None, send=two.send, infos=two.infos)
               if c["entry_time"] == entry2]
    assert [o["status"] for o in card["executors"]] == ["not_followed", "not_followed"] and card["gap"] is False
    assert f"바이비트 {LC.OWN_BUSY_KO}" in card["text"]


def test_the_paper_wins_on_its_lock_the_live_position_stays_and_loses_no_alarm(tmp_path):
    """The paper filled better, locked on its own prices and closed on its lock (a win); Bybit had not reached its own
    first trigger: it stays (the ✅ message says so at once, without waiting for it), later its own stop closes it at a
    loss. Twice: "실거래가 페이퍼가 이긴 거래에서 졌습니다" is not raised for an "own" executor (it is for "paper")."""
    clock = Clock()
    paper = Paper(str(tmp_path / "live-ac.db"), clock)
    by = Rig(tmp_path / "b", exchange="bybit", clock=clock, paper=paper, symbols=(BTC,), net_costs=COSTS)
    out = LC.open_out(str(tmp_path / "livecheck.db"))
    ex = info(by, "bybit")
    src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=paper.path, rule_db=str(tmp_path / "p3.db"),
                     combo_config="-", executors=[ex])
    sent = []
    try:
        for i in range(2):
            by.price(BTC, 10_000.0)
            entry = 9_998.0                                            # the paper filled 2 bps better
            paper.put(BTC, 1, entry, 20, paper_stop(1, entry, 20), clock.t - 30_000, 5.0)
            by.loop()
            assert by.ex.trade["entry_price"] == 10_000.0
            by.next_minute()
            by.price(BTC, 10_060.0)                         # live +9 % net: no lock; the paper locked on its own prices
            by.loop()
            lock_px = roe_price(1, entry, 20, 0.10, 0.0014)
            paper.lock(lock_px, 0.10)
            by.loop()
            paper.exit("LOCK", lock_px)
            by.loop()
            assert by.ex.trade is not None and by.ex.trade["paper_exit"]["action"] == "stay"
            got = LC.trade_pass(src, out, clock.t, None, lambda lv, tx: sent.append((lv, tx)) or True, infos=[ex],
                                units=UNITS)
            (win,) = [t for k, _key, _lv, t in got if k == "exit"]
            assert "바이비트 아직 열림 · 거래소 기준 손절·계단으로 따로 닫혀요" in win
            by.price(BTC, by.ex.trade["stop"] - 1)                      # its own stop
            by.loop()
            assert by.ex.trade is None
            got = LC.trade_pass(src, out, clock.t, None, lambda lv, tx: sent.append((lv, tx)) or True, infos=[ex],
                                units=UNITS)
            (own,) = [t for k, _key, _lv, t in got if k == "exit:bybit"]
            assert own.startswith("❌ 바이비트 청산 (거래소 기준) · BTC 롱 · 순ROE -") and "· 자기 손절 발동" in own
            assert "\n페이퍼: " in own and "잠금 +10% 청산 +" in own and "분 먼저)" in own
            clock.t += 10 * MIN
        assert all(lv == INFO for lv, _t in sent)
        c = LC.open_ro(by.cfg.db)
        papers = LC.paper_trades(LC.open_ro(paper.path), LC.ACCOUNT)
        assert len(LC.exec_vs_paper(c, papers)) == 2                     # what a "paper" executor would be held to
        assert LC.exec_vs_paper(c, papers, ex=ex) == []
        c.close()
        conds, judged, _seen = LC.watch_conditions(src, clock.t, units=UNITS, exists=lambda p: False)
        assert "vs_paper:bybit" in judged and not [x for x in conds if x.key.startswith("vs_paper")]
        assert not [x for x in conds if x.key.startswith("follow:")]
        # the trade's own record decides, not the config (a config edited before the restart changes nothing yet)
        old = info(by, "bybit", ladder_from="paper")
        t0 = LC.exec_trades(LC.open_ro(by.cfg.db))[0]
        assert LC.own_exit(old, t0) is True and LC.own_exit(old, {**t0, "data": {"stop": 1.0}}) is False
        assert LC.own_exit(ex, {**t0, "data": {}}) is True                  # no record at all: the config says "own"
        # its costs: the different exits are not slippage for "own" (they would be for "paper")
        rep = LC.exec_report(ex, papers, clock.t - 3 * 3_600_000, clock.t + MIN, clock.t)
        assert rep["cost"]["own_exits"] == 2 and rep["cost"]["exit_bps"] is None and rep["cost"]["flags"] == []
        plain = [{**r, "own_exit": False, "exit_bps": r["exit_gap_bps"]} for r in rep["costs"]]
        c_old = LC.cost_summary(plain, ex.fee)
        assert c_old["exit_bps"] > LC.SLIP_FLAG_BPS and c_old["flags"]
        # the site's 체결 비교 (livebots.fill_gaps): its entries count, its own exits are no fill gap
        rows = [{"key": t["key"], "symbol": t["symbol"], "side": t["side"], "entry_time": t["entry_ts"],
                 "exit_time": t["exit_ts"], "entry_price": t["entry_price"], "commission": t["commission"],
                 "funding": t["funding"], "pnl": t["pnl"], "leverage": t["leverage"], "exit_raw": t["exit_raw"],
                 "paper": {"entry_price": 9_998.0, "exit_price": 10_062.0, "roe": 0.1}}
                for t in L.read_exec(by.cfg.db, clock.t)["trades"]]
        g_own, g_old = L.fill_gaps(by.cfg.db, rows, "bybit", "own"), L.fill_gaps(by.cfg.db, rows, "bybit")
        assert (g_own["entry_n"], g_own["exit_n"], g_old["exit_n"]) == (2, 0, 2) and g_old["exit_gap"] < 0
        assert all(r["own_exit"] for r in g_own["rows"]) and not any(r["own_exit"] for r in g_old["rows"])
        # 못 탄 신호: both paper trades were followed (the live trade closed later): no "실행기가 안 따라감" row
        src.executors = [ex]
        res = LM.missed_pass(src, out, clock.t, log=lambda _m: None)
        assert "error" not in res and res["exec"] == 0
        assert out.execute("SELECT COUNT(*) FROM missed WHERE grp = 'exec'").fetchone()[0] == 0
    finally:
        out.close()
        by.close()
        paper.close()


def test_a_card_waits_for_an_executor_closing_but_not_for_one_that_stays(two):
    two.paper.put(DOGE, 1, ENTRY, 30, paper_stop(1, ENTRY, 30), two.clock.t - 30_000, 50_000.0)
    two.loop()
    two.paper.exit("SL", 0.0790)                                       # a loss on the paper's own prices
    assert LC.cards_pass(two.src, two.out, two.clock.t, None, send=two.send, infos=two.infos) == []   # not seen yet
    two.loop()                                                         # both record that they stay
    (card,) = LC.cards_pass(two.src, two.out, two.clock.t, None, send=two.send, infos=two.infos)
    assert [(o["name"], o["status"], o["staying"]) for o in card["executors"]] == [("bybit", "open", True),
                                                                                    ("mexc", "open", True)]
    assert f"바이비트 {LC.OPEN_OWN_KO}" in card["text"] and card["loud"] is False


def test_the_position_card_shows_its_own_lock_next_step_and_basis(two):
    two.paper.put(DOGE, 1, ENTRY, 30, paper_stop(1, ENTRY, 30), two.clock.t - 30_000, 50_000.0)
    two.loop()
    two.clock.t += MIN
    two.prices(0.07974, 0.07966)
    two.loop()
    rec = L.read_exec(two.by.cfg.db, two.clock.t)
    pos = rec["position"]
    assert pos["own"]["lock"] == pytest.approx(0.1) and pos["lock_roe"] == pytest.approx(0.1)
    assert pos["own"]["basis"] == "net"
    paper = L.read_paper(two.paper.path, [LC.ACCOUNT], two.clock.t)
    pp = paper["accounts"][LC.ACCOUNT]["position"]
    cfg = json.loads(open(os.path.join(ROOT, "deploy", "combo.live15.json"), encoding="utf-8").read())
    x = {"id": "bybit", "name_ko": "바이비트", "follows": LC.ACCOUNT, "record": rec, "config": {"ladder_from": "own"}}
    card = P.exec_card(x, pp, paper, {"cfg": cfg, "members": []}, None, {"state": "missing", "reason_ko": "없음"},
                       two.clock.t)
    p = card["position"]
    assert p["ladder_from"] == "exchange" and p["basis_ko"] == "거래소 기준" and p["lock_roe"] == pytest.approx(0.1)
    assert p["stop"] == 0.07963 and p["locked"] is True and p["round_trip"] == pytest.approx(BYBIT_RT)
    nx = p["next"]
    assert nx["from"] == "exchange" and nx["lock"] == pytest.approx(0.12) and nx["at"] == pytest.approx(0.15)
    assert nx["price"] == pytest.approx(0.07924 * (1 + 0.15 / 30 + BYBIT_RT))          # its own fill, its own costs
    assert [s["state"] for s in p["ladder"][:2]] == ["done", "next"]
    assert p["secured"]["roe"] == pytest.approx(30 * (0.07963 / 0.07924 - 1 - BYBIT_RT))
    assert p["fast"]["state"] == "off" and "자기 첫 잠금" in p["fast"]["ko"]
    assert "바이비트 비용 기준" in p["cost_ko"] and p["own_best"]["price"] == 0.07974
    # the terminal's account: its own next step
    acct = L.acct_exec(x, pp, two.clock.t)
    nl = acct["position"]["next_lock"]
    assert nl["from"] == "exchange" and nl["lock"] == pytest.approx(0.12)
    # the paper closed on a price exit: the card says the live position stays
    two.paper.exit("SL", 0.0790)
    two.loop()
    rec = L.read_exec(two.by.cfg.db, two.clock.t)
    card = P.exec_card({**x, "record": rec}, None, paper, {"cfg": cfg, "members": []}, None, {"state": "missing"},
                       two.clock.t)
    assert card["position"]["staying"]["ko"].startswith("페이퍼는 이미 닫았어요 (손절)")
    if shutil.which("node") is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    data = json.loads(json.dumps(card, allow_nan=False))
    script = (f"const D = await import('{dom}');\nif (!Node.prototype.after) Node.prototype.after = function () {{}};\n"
              f"const X = await import('file://{V4}/screens/livebots-pos.js');\nconst d = {json.dumps(data)};\n"
              "console.log(JSON.stringify(D.walk(X.posCard(d))));")
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    text = " ".join(json.loads(r.stdout.strip().splitlines()[-1])["text"].split())
    for word in ("거래소 기준", "잠금선 (거래소 기준 +10% 잠금)", "0.07963", "거래소 기준 (자기 체결가)", "15%에 닿으면 12% 잠금",
                 "이 거래소 1분봉", "페이퍼는 이미 닫았어요 (손절)", "거래소 비용 기준"):
        assert word in text, word
    assert "undefined" not in text and "NaN" not in text and "null" not in text


def test_a_gross_basis_lock_says_screen_roe(tmp_path):
    """``"ladder_basis": "gross"``: the 🔒 line and the card say 화면 ROE (the exchange screen's, before fees)."""
    clock = Clock()
    paper = Paper(str(tmp_path / "live-ac.db"), clock)
    by = Rig(tmp_path / "b", exchange="bybit", prices={DOGE: 0.07924, BTC: 10_000.0}, symbols=(DOGE,), net_costs=COSTS,
             clock=clock, paper=paper, ladder_basis="gross")
    out = LC.open_out(str(tmp_path / "livecheck.db"))
    try:
        paper.put(DOGE, 1, ENTRY, 30, paper_stop(1, ENTRY, 30), clock.t - 30_000, 50_000.0)
        by.loop()
        by.next_minute()
        by.price(DOGE, 0.07974, 0.07960)
        by.loop()
        ex = info(by, "bybit")
        src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=paper.path, rule_db="-", combo_config="-",
                         executors=[ex])
        got = LC.trade_pass(src, out, clock.t, None, lambda lv, tx: True, infos=[ex], units=UNITS)
        (text,) = [t for k, _key, _lv, t in got if k == "lock:bybit"]
        assert text.startswith("🔒 바이비트 잠금 화면 +12% (자기 체결가 기준) · 손절 0.07956\n") and "(화면 ROE +18.9%)" in text
        rec = L.read_exec(by.cfg.db, clock.t)
        x = {"id": "bybit", "name_ko": "바이비트", "follows": LC.ACCOUNT, "record": rec, "config": {}}
        p = P.exec_card(x, None, {"state": "missing"}, {"cfg": {}, "members": []}, None, {"state": "missing"},
                        clock.t)["position"]
        assert p["basis"] == "gross" and p["basis_ko"] == "거래소 기준 · 화면 ROE" and p["ladder_round_trip"] == 0.0
        assert p["round_trip"] == pytest.approx(BYBIT_RT)
        assert p["next"]["price"] == pytest.approx(0.07924 * (1 + 0.20 / 30))
    finally:
        out.close()
        by.close()
        paper.close()
