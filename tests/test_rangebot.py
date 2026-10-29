"""레인지 봇 (owners 2026-10-26): paperbot/rangebot.py on the combined bot, and the fixed take-profit of paperbot/combo.py.

- the fixed take-profit: net ROE +10 % on the fill (sizing.tp_from_roe), filled at its price; no ladder step;
- the runner on a synthetic paper3.db with the custom signals set by the test: a signal waits for its 0.2 ATR pullback
  (WAITING); the 5-minute bar of the first touch ends -> the entry at the next 5-minute open (BROKE + a new SUBMITTED
  row); no touch in 60 minutes -> FILTERED; a touch in the last minute enters at the hour;
- one signal at a time (a wait, a position, an entry about to be filled), the coin order at the same close, the coin's
  and BTC's supertrend, the liquidation room, the weekend / NYSE-open pause at the signal and again at the entry;
- restart keeps the wait; the state for the live site; the Telegram words; the executor's reader sees the entry;
- the supertrend read equals pine_indicators.exchange_supertrend on the 1h bars of the same 5m history;
- owners 10-29: the deploy config checks the friend's trend indicator on the signal's 1h bar instead of the two
  supertrends (paperbot/friendtrend.py): with the signal -> waits; against or no entry (2 sideways, 2-2) -> FILTERED
  with the votes; unreadable -> no entry and an alert; its read equals friendtrend.last_trend on the same 1h frame;
- the deploy config passes check-config; wrong ones are refused."""

import json
from collections import deque
from pathlib import Path

import numpy as np
import pytest

from paperbot import combo as C
from paperbot import rangebot as RB
from paperbot.notify import ListNotifier
from paperbot.sizing import tp_from_roe
from paperbot.store3 import Store3

MIN = 60_000
FIVE = 300_000
HOUR = 3_600_000
T0 = 1_791_158_400_000                        # 2026-10-05 00:00 UTC (Monday 09:00 KST)
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
PX = {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0, "SOLUSDT": 150.0, "DOGEUSDT": 0.2, "LTCUSDT": 80.0, "BCHUSDT": 400.0}
SPECS = {s: {"qty_step": 0.0001 if s == "BTCUSDT" else 0.001, "min_notional": 5.0, "tick_size": 0.01} for s in SYMS}
from paperbot.margin import BracketTier, Brackets  # noqa: E402
BRK = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 50, 0.005, 300.0)])
BRACKETS = {s: BRK for s in SYMS}
DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "combo.range.json"
MEMBER = "ds-F7_RF_TRIPLE-1h-1"
# the range section before owners 10-29: the coin's and BTC's 1h supertrend (the supertrend tests use it)
ST_RANGE = {"pullback_atr": 0.2, "wait_min": 60, "coin_st": True, "btc_st": True, "st_period": 10, "st_mult": 3.0,
            "liq_check": True, "liq_mmr": 0.005}


def rcfg(tmp_path, **kw):
    d = json.loads(DEPLOY.read_text(encoding="utf-8"))
    d.update(paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "range.db"), macro_blackout_min=None)
    d.update(kw)
    return C.ComboConfig.from_dict(d)


class FakeCustom:
    """The custom signals set by the test: {boundary: [(symbol, side, atr)]}; the signal bar's close is the price then."""

    def __init__(self, members, px):
        self.members = [m for m in members if m.custom]
        self.plan: dict = {}
        self.errors: list = []
        self.hist: dict = {}
        self.px = px

    def add_1m(self, bar):
        pass

    def fill_gaps(self, fetch, boundary):
        pass

    def compute(self, boundary):
        return [{"member": self.members[0], "symbol": s, "side": side, "atr": atr, "ctx": {"close": self.px[s]}}
                for s, side, atr in self.plan.get(boundary, [])]


class World:
    def __init__(self, tmp_path, **kw):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.tmp = tmp_path
        self.paper = Store3(str(tmp_path / "paper3.db"))
        self.now = T0
        self.px = dict(PX)
        self.cfg = rcfg(tmp_path, **kw)
        assert self.cfg.problems() == []
        self.note = ListNotifier()
        self.st: dict = {}                         # symbol -> supertrend side (default: with the signal)
        self.ft: dict = {}                         # symbol -> the friend's trend (default: with the signal)
        self.add_minutes(T0 - 10 * MIN, 10)
        self.open()

    def open(self):
        self.members = C.resolve_members(self.cfg.members, self.cfg.picks_file)
        self.store = Store3(self.cfg.db)
        self.book = C.build_book(self.cfg, C.settings_of(self.cfg), BRACKETS, self.store, self.note, SPECS)
        self.custom = FakeCustom(self.members, self.px)
        self.run = RB.RangeRunner(self.cfg, self.members, self.book, self.store, self.note, self.custom,
                                  now_ms=lambda: self.now, prices=lambda: {})
        self.run.supertrend = lambda sym, bc: self.st.get(sym, self.default_st)
        self.run.friend_trend = lambda sym, bc: self.ft.get(sym, friend_votes(self.default_st))
        self.default_st = 1

    def restart(self):
        plan = self.custom.plan
        self.store.close()
        self.open()
        self.custom.plan = plan

    def add_minutes(self, start, n, move=None, low=None, high=None):
        rows = []
        for k in range(n):
            t = start + k * MIN
            for s in SYMS:
                o = self.px[s]
                c = o * (1 + (move or {}).get(s, 0.0))
                lo = min(o, c) * 0.9999 if (low or {}).get(s) is None else low[s]
                hi = max(o, c) * 1.0001 if (high or {}).get(s) is None else high[s]
                rows.append({"ts": t, "symbol": s, "open": o, "high": hi, "low": lo, "close": c, "volume": 10.0,
                             "mark_open": o, "mark_high": hi, "mark_low": lo, "mark_close": c,
                             "close_time": t + MIN - 1, "processed_at": t + MIN + 5000})
                self.px[s] = c
        self.paper.live_bars(rows)
        self.paper.commit()

    def step(self, t, move=None, low=None, high=None):
        """The rule bot writes minute t; the bot polls a little after it closed."""
        self.add_minutes(t, 1, move, low, high)
        self.now = t + 65_000
        self.run.poll()

    def to(self, a, b, **kw):
        for t in range(a, b, MIN):
            self.step(t, **kw)

    def engine(self, aid=C.ACCOUNT):
        return self.book.engines[aid]

    def rows(self):
        return [(bc, sym, st, json.loads(d)) for bc, sym, st, d in self.store.conn.execute(
            "SELECT bar_close, symbol, status, data FROM signal_log ORDER BY id")]

    def trades(self):
        return [json.loads(d) for (d,) in self.store.conn.execute(
            "SELECT data FROM trades WHERE account_id = ? ORDER BY id", (C.ACCOUNT,))]


def friend_votes(trend, line=None, ema=None, chop=None, st=None):
    """A friend's trend read: the trend and its four votes (each vote the trend's side unless given)."""
    d = {"line": trend or 1, "ema": trend or 1, "chop": trend, "st": trend}
    d.update({k: v for k, v in (("line", line), ("ema", ema), ("chop", chop), ("st", st)) if v is not None})
    return {"trend": trend, **d, "ema_rsi": 55.0 if trend >= 0 else 45.0, "chop_zone": 2 * (d["chop"] or 0)}


H = T0 + HOUR                                 # the 1h close of the tests' signals (10:00 KST Monday)
ATR = 300.0                                   # BTC's 1h ATR: the pullback level is 60 bp of it = 60 below the close


def _start(w, signals=None, at=H):
    w.now = T0 + 5_000
    w.run.poll()
    w.custom.plan[at] = signals if signals is not None else [("BTCUSDT", 1, ATR)]
    w.to(T0, at)                              # up to the signal: its close is computed after the minute at - 1


def test_fixed_take_profit_is_net_roe_on_the_fill_and_no_ladder(tmp_path):
    cfg = rcfg(tmp_path)
    s = C.settings_of(cfg)
    assert s.tp_mode == "fixed" and s.default_tp_roe == pytest.approx(0.10)
    pol = C.FixedLevPolicy(s, cfg)
    sig = type("S", (), {"side": 1})()
    dec = type("D", (), {"leverage": 40})()
    assert pol.take_profit(sig, 60000.0, dec) == pytest.approx(60000.0 * (1 + 0.10 / 40 + 0.0014))
    assert pol.take_profit(sig, 60000.0, dec) == pytest.approx(tp_from_roe(1, 60000.0, 40, 0.10, s.round_trip_cost))
    # every other bot keeps its ladder and no take-profit price
    other = C.ComboConfig.from_dict({**json.loads((DEPLOY.parent / "combo.vwap.json").read_text()), "paper_db": "a",
                                     "db": "b"})
    assert C.settings_of(other).tp_mode == "ladder" and np.isnan(C.FixedLevPolicy(C.settings_of(other), other)
                                                                  .take_profit(sig, 1.0, dec))
    assert "take_profit_roe" not in C.run_config(other) and "range" not in C.run_config(other)
    assert C.run_config(cfg)["take_profit_roe"] == 0.1 and C.run_config(cfg)["range"]["pullback_atr"] == 0.2


def test_a_signal_waits_for_its_pullback_then_enters_at_the_next_five_minute_open(tmp_path):
    w = World(tmp_path)
    _start(w)
    close = w.px["BTCUSDT"]
    level = close - 0.2 * ATR
    w.step(H)                                                    # due: waits
    (bc, sym, st, d), = w.rows()
    assert (bc, sym, st) == (H, "BTCUSDT", "WAITING") and d["range"]["level"] == pytest.approx(level)
    assert d["why"].startswith(f"되돌림 기다림: {level:.6g}까지") and w.run.wait["until"] == H + HOUR
    w.to(H + MIN, H + 7 * MIN)                                   # no touch
    assert w.engine().position is None and w.run.wait["hit"] is None
    w.step(H + 7 * MIN, low={"BTCUSDT": level - 1})              # touched in the 5m bar 10:05-10:10
    w.step(H + 8 * MIN)
    assert w.engine().position is None and w.run.queue == []     # the 5-minute bar has not ended
    w.step(H + 9 * MIN)                                          # it ends: the entry is queued for 10:10
    assert len(w.run.queue) == 1 and w.run.wait is None
    w.step(H + 10 * MIN)
    p = w.engine().position
    assert p is not None and p.side == 1 and p.entry_time == H + 10 * MIN and p.leverage == 40
    assert p.tp_price == pytest.approx(p.entry_price * (1 + 0.10 / 40 + 0.0014))
    assert p.signal.meta["range"]["touch"] == H + 7 * MIN and p.signal.meta["range"]["entry_t"] == H + 10 * MIN
    assert p.margin == pytest.approx(0.4 * 1000, rel=0.01)
    rows = w.rows()
    assert [(r[0], r[2]) for r in rows] == [(H, "BROKE"), (H + 10 * MIN, "SUBMITTED")]
    assert rows[1][3]["pulled"] and rows[0][3]["why"].startswith("되돌림 확인:")
    assert w.run.counts[MEMBER] == {"waiting": 1, "submitted": 1}
    # the Telegram entry line names the strategy and the pullback
    ent = [m for _l, m in w.note.messages if "진입" in m and "레인지 필터 3중 일치" in m]
    assert ent and "0.2 ATR" in ent[-1] and "10분 뒤 진입" in ent[-1] and "익절" in ent[-1]
    # the executor's reader sees the entry like any other (unchanged executor code)
    from paperbot.executor import Paper3Source
    it, _ts = Paper3Source(w.cfg.db, C.ACCOUNT).read()
    assert it.symbol == "BTCUSDT" and it.entry_time == H + 10 * MIN


def test_take_profit_closes_at_its_price(tmp_path):
    w = World(tmp_path)
    _start(w)
    w.step(H)
    w.step(H + MIN, low={"BTCUSDT": w.px["BTCUSDT"] - 0.25 * ATR})
    w.to(H + 2 * MIN, H + 5 * MIN)
    w.step(H + 5 * MIN)
    p = w.engine().position
    assert p is not None and p.entry_time == H + 5 * MIN
    tp = p.tp_price
    w.step(H + 6 * MIN, high={"BTCUSDT": tp * 1.001})
    assert w.engine().position is None
    t, = w.trades()
    assert t["exit_reason"] == "TP" and t["exit_price"] == pytest.approx(tp)
    # the take-profit price counts a taker exit with slippage; it fills as a maker at its price: +12.8 % at 40x (the
    # research's sim.run_position books the same)
    assert t["roe"] == pytest.approx(0.10 + 40 * (0.0014 - 0.0005 - 0.0002), abs=0.002)
    ex = [m for _l, m in w.note.messages if "청산" in m]
    assert ex and "익절" in ex[-1] and "레인지 필터 3중 일치" in ex[-1]


def test_no_touch_in_the_hour_drops_the_signal(tmp_path):
    w = World(tmp_path)
    _start(w)
    w.to(H, H + 59 * MIN)
    assert w.run.wait is not None
    w.step(H + 59 * MIN)
    assert w.run.wait is None and w.engine().position is None
    (bc, _s, st, d), = w.rows()
    assert st == "FILTERED" and d["why"].startswith("되돌림 안 옴")
    assert w.run.counts[MEMBER] == {"waiting": 1, "no_pullback": 1}


def test_a_touch_in_the_last_minute_enters_at_the_hour_and_takes_the_slot(tmp_path):
    w = World(tmp_path)
    _start(w)
    w.custom.plan[H + HOUR] = [("ETHUSDT", 1, 10.0)]
    w.to(H, H + 59 * MIN)
    w.step(H + 59 * MIN, low={"BTCUSDT": w.px["BTCUSDT"] - ATR})
    w.step(H + HOUR)
    assert w.engine().position.entry_time == H + HOUR and w.engine().position.symbol == "BTCUSDT"
    eth = [r for r in w.rows() if r[1] == "ETHUSDT"]
    assert [(r[0], r[2]) for r in eth] == [(H + HOUR, "FILTERED")]
    assert eth[0][3]["why"].startswith("한 신호씩: 이번 분에 BTC 롱 진입이 먼저")


def test_one_signal_at_a_time_in_coin_order_and_while_holding(tmp_path):
    w = World(tmp_path)
    _start(w, [("BTCUSDT", 1, ATR), ("ETHUSDT", -1, 10.0)])
    w.step(H)
    st = {r[1]: (r[2], r[3]["why"]) for r in w.rows()}
    assert st["BTCUSDT"][0] == "WAITING"
    assert st["ETHUSDT"] == ("FILTERED", f"한 신호씩: BTC 롱 되돌림 기다리는 중({RB.kst(H + HOUR)}까지)")
    # BTC enters; a signal while the position is open is not taken
    w.step(H + MIN, low={"BTCUSDT": w.px["BTCUSDT"] - ATR})
    w.custom.plan[H + 2 * HOUR] = [("SOLUSDT", 1, 1.0)]
    w.to(H + 2 * MIN, H + 2 * HOUR + MIN)
    assert w.engine().position is not None
    sol = [r for r in w.rows() if r[1] == "SOLUSDT"]
    assert sol[0][2] == "FILTERED" and sol[0][3]["why"] == "한 신호씩: BTC 롱 포지션 들고 있음"


def test_supertrend_against_skips_and_the_next_coin_of_the_same_close_waits(tmp_path):
    w = World(tmp_path, range=ST_RANGE)
    w.st = {"BTCUSDT": 1, "ETHUSDT": -1, "SOLUSDT": 1}
    _start(w, [("ETHUSDT", 1, 10.0), ("SOLUSDT", 1, 1.0)])
    w.step(H)
    st = {r[1]: (r[2], r[3]["why"]) for r in w.rows()}
    assert st["ETHUSDT"] == ("FILTERED", "추세 확인: ETH 1시간 슈퍼트렌드 하락(신호 롱와 반대)")
    assert st["SOLUSDT"][0] == "WAITING" and w.run.wait["signal"]["symbol"] == "SOLUSDT"
    # BTC's supertrend against: no entry either
    w2 = World(tmp_path / "b", range=ST_RANGE)
    w2.st = {"BTCUSDT": -1}
    _start(w2, [("SOLUSDT", 1, 1.0)])
    w2.step(H)
    (_bc, _s, stt, d), = w2.rows()
    assert stt == "FILTERED" and d["why"] == "추세 확인: BTC 1시간 슈퍼트렌드 하락(신호 롱와 반대)"


def test_unreadable_supertrend_means_no_entry_and_an_alert(tmp_path):
    w = World(tmp_path, range=ST_RANGE)

    def boom(sym, bc):
        raise C.ComboError("BTC 5분봉 10개뿐")
    w.run.supertrend = boom
    _start(w)
    w.step(H)
    (_bc, _s, st, d), = w.rows()
    assert st == "FILTERED" and d["why"].startswith("슈퍼트렌드를 못 읽어 진입 안 함: BTC 5분봉")
    assert any("슈퍼트렌드를 못 읽어" in m for _l, m in w.note.messages)


def test_too_wild_an_hour_has_no_liquidation_room(tmp_path):
    w = World(tmp_path)
    # 30x: stop 1.53 % + ATR must fit in 1/30 - 0.5 % = 2.83 % -> an ATR of 1.4 % does not
    _start(w, [("SOLUSDT", 1, 150.0 * 0.014)])
    w.step(H)
    (_bc, _s, st, d), = w.rows()
    assert st == "FILTERED" and d["why"].startswith("강제청산 여유 부족: 손절 거리 1.53% + 1시간 ATR 1.40% > 2.83%")
    w2 = World(tmp_path / "b")
    _start(w2, [("SOLUSDT", 1, 150.0 * 0.012)])
    w2.step(H)
    assert w2.rows()[0][2] == "WAITING"


def test_pauses_at_the_signal_and_again_at_the_entry(tmp_path):
    # NYSE open on 10-05 (summer time): 13:30 UTC, no entry from 13:00 to 14:00 UTC
    w = World(tmp_path)
    s = T0 + 12 * HOUR
    _start(w, at=s)
    w.to(s, s + 56 * MIN)
    w.step(s + 56 * MIN, low={"BTCUSDT": w.px["BTCUSDT"] - ATR})     # touched 12:56 -> the entry would be 13:00
    w.to(s + 57 * MIN, s + 61 * MIN)
    assert w.engine().position is None
    rows = w.rows()
    assert [(r[0], r[2]) for r in rows] == [(s, "BROKE"), (s + HOUR, "FILTERED")]
    assert "나스닥 개장" in rows[1][3]["why"]
    # a signal inside the pause is not taken (the slot stays free)
    w.custom.plan[s + 2 * HOUR] = [("BTCUSDT", 1, ATR)]
    w.to(s + 61 * MIN, s + 2 * HOUR + MIN)
    assert w.run.wait is not None and w.run.wait["t0"] == s + 2 * HOUR


def test_weekend_signal_is_not_taken(tmp_path):
    w = World(tmp_path)
    sat = T0 + 5 * 86_400_000 - 9 * HOUR + HOUR       # Saturday 01:00 KST
    w.now = T0 + 5_000
    w.run.poll()
    w.custom.plan[sat] = [("BTCUSDT", 1, ATR)]
    w.add_minutes(T0, (sat - 2 * MIN - T0) // MIN)
    w.now = sat - MIN
    while w.book.last_ts < sat - 3 * MIN:          # the catch-up reads 600 minutes a poll
        w.run.poll()
    w.to(sat - 2 * MIN, sat + MIN)
    (_bc, _s, st, d), = w.rows()
    assert st == "FILTERED" and d["why"].startswith("주말") and w.run.wait is None


def test_restart_keeps_the_wait(tmp_path):
    w = World(tmp_path)
    _start(w)
    w.step(H)
    w.step(H + MIN)
    w.restart()
    assert w.run.wait is not None and w.run.wait["t0"] == H
    w.step(H + 2 * MIN, low={"BTCUSDT": w.px["BTCUSDT"] - ATR})
    w.to(H + 3 * MIN, H + 6 * MIN)
    assert w.engine().position is not None and w.engine().position.entry_time == H + 5 * MIN


def test_state_for_the_live_site(tmp_path):
    w = World(tmp_path, range=ST_RANGE)
    w.st = {"ETHUSDT": -1}
    _start(w)
    w.step(H)
    _ts, st = w.store.get_state(RB.STATE_RANGE)
    assert st["wait"]["symbol"] == "BTCUSDT" and st["wait"]["level"] == pytest.approx(w.run.wait["level"])
    assert st["supertrend"]["ETHUSDT"] == -1 and st["supertrend"]["BTCUSDT"] == 1 and st["st_at"] == H
    assert st["busy"].startswith("한 신호씩") and any("되돌림 진입" in x for x in st["rules"])
    assert "friend" not in st
    # the deploy config (owners 10-29): the friend's trend per coin, no supertrend read
    w2 = World(tmp_path / "b")
    w2.ft = {"ETHUSDT": friend_votes(0, chop=0, st=0)}
    w2.run.supertrend = lambda sym, bc: pytest.fail("the supertrend is not read")
    _start(w2)
    w2.step(H)
    _ts, st = w2.store.get_state(RB.STATE_RANGE)
    assert st["friend"]["ETHUSDT"]["trend"] == 0 and st["friend"]["BTCUSDT"]["trend"] == 1 and st["supertrend"] == {}
    assert any(x.startswith("추세 확인: 친구 추세지표 1시간봉") for x in st["rules"])


def test_the_supertrend_read_equals_the_indicator_on_the_same_history(tmp_path):
    from paperbot import sweepsig
    from paperbot.dssig import frame
    lib = sweepsig.lib()
    members = C.resolve_members([{"pick": MEMBER}])
    custom = C.CustomSignals(members, ["BTCUSDT"], lib=lib)
    rng = np.random.default_rng(3)
    n = 400 * 12
    ts0 = T0 - n * FIVE
    c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    custom.bootstrap("BTCUSDT", [(ts0 + k * FIVE, o[k], hi[k], lo[k], c[k], 5.0) for k in range(n)])
    w = World(tmp_path)
    run = RB.RangeRunner(w.cfg, w.members, w.book, w.store, w.note, custom, now_ms=lambda: T0, prices=lambda: {})
    df = frame(np.array([ts0 + k * FIVE for k in range(n)]), o, hi, lo, c, np.full(n, 5.0), tf="1h", lib=lib)
    _line, d = lib.pi.exchange_supertrend(df["high"].to_numpy(float), df["low"].to_numpy(float),
                                          df["close"].to_numpy(float), 10, 3.0)
    assert run.supertrend("BTCUSDT", T0) == int(np.asarray(d)[-1])
    # an earlier close reads the bars before it only
    df2 = df.iloc[:-5]
    _l2, d2 = lib.pi.exchange_supertrend(df2["high"].to_numpy(float), df2["low"].to_numpy(float),
                                         df2["close"].to_numpy(float), 10, 3.0)
    assert run.supertrend("BTCUSDT", T0 - 5 * HOUR) == int(np.asarray(d2)[-1])
    with pytest.raises(C.ComboError, match="5분봉"):
        run.supertrend("BTCUSDT", T0 - 200 * HOUR)               # too little history before it
    run.custom.hist["ETHUSDT"] = deque()
    with pytest.raises(C.ComboError):
        run.supertrend("ETHUSDT", T0)


def test_the_friends_trend_decides_the_signal(tmp_path):
    """Owners 10-29: the friend's trend on the signal's 1h bar must be the signal's side; 2 sideways or 2-2 is no entry."""
    w = World(tmp_path)
    assert w.cfg.range["friend_tf"] == "1h" and not w.cfg.range["coin_st"] and not w.cfg.range["btc_st"]
    w.ft = {"ETHUSDT": friend_votes(-1, line=1, chop=-1, st=-1, ema=-1),
            "SOLUSDT": friend_votes(0, line=1, ema=1, chop=0, st=0),
            "DOGEUSDT": friend_votes(0, line=1, ema=-1, chop=1, st=-1)}
    w.run.supertrend = lambda sym, bc: pytest.fail("the supertrend is not read")
    _start(w, [("ETHUSDT", 1, 10.0), ("SOLUSDT", 1, 1.0), ("DOGEUSDT", 1, 0.001), ("LTCUSDT", 1, 0.5)])
    w.step(H)
    st = {r[1]: (r[2], r[3]["why"]) for r in w.rows()}
    assert st["ETHUSDT"] == ("FILTERED", "추세 확인: 친구 추세지표 1시간 하락 (하늘·보라 선 상승 · EMA RSI 하락 · 찹존 하락 · "
                                         "슈퍼트렌드 하락)(신호 롱와 반대)")
    assert st["SOLUSDT"] == ("FILTERED", "추세 확인: 친구 추세지표 1시간 진입 금지 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 횡보 · "
                                         "슈퍼트렌드 횡보)")
    assert st["DOGEUSDT"] == ("FILTERED", "추세 확인: 친구 추세지표 1시간 진입 금지 (하늘·보라 선 상승 · EMA RSI 하락 · 찹존 상승 · "
                                          "슈퍼트렌드 하락)")
    assert st["LTCUSDT"][0] == "WAITING" and "친구 추세 상승" in st["LTCUSDT"][1]
    assert w.run.wait["info"]["friend"]["trend"] == 1
    # the entry keeps the votes; the Telegram entry line says them
    w.step(H + MIN, low={"LTCUSDT": w.px["LTCUSDT"] - 1.0})
    w.to(H + 2 * MIN, H + 6 * MIN)
    p = w.engine().position
    assert p is not None and p.symbol == "LTCUSDT" and p.signal.meta["range"]["friend"]["trend"] == 1
    ent = [m for _l, m in w.note.messages if "진입" in m and "레인지 필터 3중 일치" in m]
    assert ent and "친구 추세 상승 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 상승 · 슈퍼트렌드 상승)" in ent[-1]
    # a short signal needs a falling trend
    w2 = World(tmp_path / "b")
    w2.ft = {"BTCUSDT": friend_votes(-1)}
    _start(w2, [("BTCUSDT", -1, ATR)])
    w2.step(H)
    assert w2.rows()[0][2] == "WAITING"


def test_unreadable_friends_trend_means_no_entry_and_an_alert(tmp_path):
    w = World(tmp_path)

    def boom(sym, bc):
        raise C.ComboError("BTC 5분봉 10개뿐(친구 추세지표에 3600개 필요)")
    w.run.friend_trend = boom
    _start(w)
    w.step(H)
    (_bc, _s, st, d), = w.rows()
    assert st == "FILTERED" and d["why"].startswith("친구 추세지표를 못 읽어 진입 안 함: BTC 5분봉")
    assert any("친구 추세지표" in m and "못 읽어" in m for _l, m in w.note.messages)


def test_the_friends_trend_read_equals_the_indicator_on_the_same_history(tmp_path):
    from paperbot import friendtrend as FT
    from paperbot import sweepsig
    from paperbot.dssig import frame
    lib = sweepsig.lib()
    members = C.resolve_members([{"pick": MEMBER}])
    custom = C.CustomSignals(members, ["BTCUSDT"], lib=lib)
    rng = np.random.default_rng(5)
    n = 400 * 12
    ts0 = T0 - n * FIVE
    c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    vol = rng.uniform(1.0, 9.0, n)
    custom.bootstrap("BTCUSDT", [(ts0 + k * FIVE, o[k], hi[k], lo[k], c[k], vol[k]) for k in range(n)])
    w = World(tmp_path)
    run = RB.RangeRunner(w.cfg, w.members, w.book, w.store, w.note, custom, now_ms=lambda: T0, prices=lambda: {})
    df = frame(np.array([ts0 + k * FIVE for k in range(n)]), o, hi, lo, c, vol, tf="1h", lib=lib)
    want = FT.last_trend(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")))
    got = run.friend_trend("BTCUSDT", T0)
    assert got == want and got["trend"] in (-1, 0, 1) and set(FT.VOTES) <= set(got)
    df2 = df.iloc[:-7]
    assert run.friend_trend("BTCUSDT", T0 - 7 * HOUR) == FT.last_trend(*(df2[k].to_numpy(float) for k in
                                                                   ("open", "high", "low", "close", "volume")))
    with pytest.raises(C.ComboError, match="친구 추세지표"):
        run.friend_trend("BTCUSDT", T0 - 200 * HOUR)                  # too little history before it


def test_deploy_config_and_wrong_ones(tmp_path):
    from argparse import Namespace
    assert C.cmd_check(Namespace(config=str(DEPLOY))) == 0
    cfg = rcfg(tmp_path)
    assert cfg.problems() == []
    text = C.start_text(cfg, C.resolve_members(cfg.members, cfg.picks_file), 1000.0)
    assert "고정 익절 순ROE +10%" in text and "되돌림 진입" in text and "계단" in text.split("고정 익절")[1][:60]
    bad = {
        "ladder": ({"ladder": {"first_lock": 0.1, "step": 0.05, "trigger_gap": 0.01}}, "ladder는 null"),
        "no tp": ({"take_profit_roe": None, "ladder": None}, "ladder에 first_lock"),
        "early": ({"early_exit": "own"}, "early_exit"),
        "tf": ({"members": [{"pick": "ds-F7_RF_TRIPLE-4h-1"}]}, "1시간봉 매매법만"),
        "stop": ({"stop": {"mode": "atr", "atr": 2}}, "손절은"),
        "rule": ({"range": {"pullback_atr": 0.2, "wait_min": 61}}, "wait_min"),
        "key": ({"range": {"pull": 0.2}}, "알 수 없는 이름"),
        "tp": ({"take_profit_roe": 1.5}, "take_profit_roe"),
        "atr room twice": ({"liq_buffer_atr": 1.0}, "liq_buffer_atr는 0"),
        "friend tf": ({"range": {"friend_tf": "4h"}}, "friend_tf"),
    }
    for name, (over, words) in bad.items():
        probs = rcfg(tmp_path, **over).problems()
        assert any(words in p for p in probs), (name, probs)


# ---------------------------------------------------------------- the live watcher's ⏳ (paperbot/livecheck.py)
def test_the_watcher_reads_the_range_wait_and_its_result(tmp_path):
    import sqlite3
    from paperbot import livecheck as LC
    w = World(tmp_path)
    _start(w)
    level = w.px["BTCUSDT"] - 0.2 * ATR
    w.step(H)
    w.step(H + MIN)
    pc, rc = sqlite3.connect(w.cfg.db), sqlite3.connect(str(tmp_path / "paper3.db"))
    (x,) = LC.pending_entries(pc, rc, H + 2 * MIN)
    assert x["kind"] == "pullback" and x["level"] == pytest.approx(level) and x["touched"] is False
    assert x["until"] == H + 59 * MIN and x["to_go"] is not None and x["to_go"] > 0
    # the signal's own minute counts for the range bot: a dip there is a touch
    rc.execute("UPDATE live_bars SET low = ? WHERE symbol = 'BTCUSDT' AND ts = ?", (level - 1, H))
    rc.commit()
    (x,) = LC.pending_entries(pc, rc, H + 2 * MIN)
    assert x["touched"] is True


def test_the_result_line_of_a_touch_in_the_last_five_minutes(tmp_path):
    import sqlite3
    from paperbot import livecheck as LC
    w = World(tmp_path)
    _start(w)
    w.custom.plan[H + HOUR] = [("BTCUSDT", -1, ATR)]          # the same coin's next signal at the entry minute
    w.to(H, H + 59 * MIN)
    w.step(H + 59 * MIN, low={"BTCUSDT": w.px["BTCUSDT"] - ATR})
    w.step(H + HOUR)
    assert w.engine().position.entry_time == H + HOUR
    pc = sqlite3.connect(w.cfg.db)
    assert LC.wait_result(pc, f"{MEMBER}|BTCUSDT|{H}") == f"→ ✅ 되돌림! {LC.kst(H + HOUR)}에 진입했어요 (🟢 진입 알림 참고)"
    # an earlier touch: the entry minute inside the hour, as before
    w2 = World(tmp_path / "b")
    _start(w2)
    w2.step(H)
    w2.step(H + MIN, low={"BTCUSDT": w2.px["BTCUSDT"] - ATR})
    w2.to(H + 2 * MIN, H + 6 * MIN)
    pc2 = sqlite3.connect(w2.cfg.db)
    assert LC.wait_result(pc2, f"{MEMBER}|BTCUSDT|{H}") == f"→ ✅ 되돌림! {LC.kst(H + 5 * MIN)}에 진입했어요 (🟢 진입 알림 참고)"
