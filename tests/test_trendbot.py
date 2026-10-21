"""추세판단 봇 (owners 2026-10-21): paperbot/trendjudge.py and paperbot/trendbot.py on the combined bot.

- the judge: the four judges equal their chart views bar for bar (V3.9 supertrend, EMA·DMI·ADX, OBV, 일목·AO), the 3-of-4
  vote, the hold, ADX strength and 끝물; closed bars only, a failed fetch waits (no fetch storm);
- the entry checks in their order, the pullback depth (deeper after a long bar), the score;
- the runner on a synthetic paper3.db: a signal with the trend waits for its pullback (WAITING), the touching minute
  queues the entry for the next minute (BROKE + a new SUBMITTED row), no touch -> FILTERED; a signal against the trend
  is FILTERED with the reason and still closes the open position as the fast stop; restart keeps the waits;
- the supervisor: TIME (4 entry bars without the first lock) and JUDGE (a higher bar closed after the entry judged the
  other way), never after the first lock, the reason on the trade and in the message;
- the pauses: a member with 2 losses in a row (24 h), a coin and side after a loss (2 h), the daily loss limit;
- the deploy config (deploy/combo.trend.json) passes check-config; a wrong one is refused."""

import dataclasses
import json
import types

import numpy as np
import pandas as pd
import pytest

from paperbot import combo as C
from paperbot import trendbot as TB
from paperbot import trendjudge as TJ
from paperbot.models import TradeRecord
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
HOUR = 3_600_000
T0 = 1_791_158_400_000                        # 2026-10-05 00:00 UTC (Monday 09:00 KST)
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
PX = {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0, "SOLUSDT": 150.0, "DOGEUSDT": 0.2, "LTCUSDT": 80.0, "BCHUSDT": 400.0}
SPECS = {s: {"qty_step": 0.0001 if s == "BTCUSDT" else 0.001, "min_notional": 5.0, "tick_size": 0.01} for s in SYMS}
from paperbot.margin import BracketTier, Brackets  # noqa: E402
BRK = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 50, 0.005, 300.0)])
BRACKETS = {s: BRK for s in SYMS}
CORE = ["N08_ICHI_WR", "F3_BOS", "S3_CMO_SANDWICH"]
RULES = TJ.TrendRules()


# ---------------------------------------------------------------- bars
def frame(n=300, seed=5, drift=(0.002, -0.002), tf="1h", t0=T0):
    """Synthetic closed bars: the first half drifting by drift[0] a bar, the second by drift[1]."""
    rng = np.random.default_rng(seed)
    half = n // 2
    ret = np.concatenate([rng.normal(drift[0], 0.004, half), rng.normal(drift[1], 0.004, n - half)])
    c = 100 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    v = rng.uniform(50, 150, n)
    return pd.DataFrame({"ts": pd.to_datetime(t0 + np.arange(n) * TJ.TF_MS[tf], unit="ms"), "open": o, "high": h,
                         "low": lo, "close": c, "volume": v})


def test_the_judges_equal_their_chart_views_bar_for_bar():
    from paperbot import strategy_views as SV
    df = frame(drift=(0.002, -0.002))
    arr = TJ.vote_arrays(df)
    V = SV.views()

    def cond(view, side, label):
        return dict(view[side])[label]
    s6, obv, v39, n12 = (V[n](df, "1h") for n in ("S6_EMA_DMI_ADX", "OBV_S", "V39_ALL", "N12_ICHI_AO"))
    assert np.array_equal(arr["S6"] == 1, cond(s6, "long", "종가가 EMA20 위") & cond(s6, "long", "+DI가 -DI 위"))
    assert np.array_equal(arr["S6"] == -1, cond(s6, "short", "종가가 EMA20 아래") & cond(s6, "short", "-DI가 +DI 위"))
    assert np.array_equal(arr["OBV"] == 1, cond(obv, "long", "OBV가 30봉 평균 위"))
    assert np.array_equal(arr["OBV"] == -1, cond(obv, "short", "OBV가 30봉 평균 아래"))
    assert np.array_equal(arr["V39"] == 1, cond(v39, "long", "슈퍼트렌드(10·3) 상승"))
    assert np.array_equal(arr["V39"] == -1, cond(v39, "short", "슈퍼트렌드(10·3) 하락"))
    ov = {o["name"]: o["values"] for o in n12["overlays"]}
    assert np.allclose(ov["구름 A(선행스팬1)"], arr["span_a"], equal_nan=True)
    assert np.allclose(ov["구름 B(선행스팬2)"], arr["span_b"], equal_nan=True)
    assert np.allclose(n12["panes"][0]["series"][0]["values"], arr["ao"], equal_nan=True)
    # the vote: up in the first half, down at the end
    raw = TJ.raw_votes(arr, 3)
    assert (raw[100:150] == 1).all() and (raw[260:] == -1).all()


def test_judgment_hold_strength_and_tired():
    up = frame(drift=(0.002, 0.002))
    j = TJ.judge_frame(up, "BTCUSDT", "1h", RULES)
    assert j.dir == 1 and j.raw == 1 and j.up >= 3 and j.held == (1, 1)
    assert j.bar_close == int(up["ts"].iloc[-1].value // 1_000_000) + HOUR
    assert "1시간 상승" in j.text(RULES)
    # the hold: a direction seen on the last bar only is 보류 on 1h (2 bars), already a trend on 4h (1 bar)
    arr = TJ.vote_arrays(frame(drift=(0.002, -0.002)))
    raw = TJ.raw_votes(arr, 3)
    k = next(i for i in range(150, 300) if raw[i] == -1 and raw[i - 1] != -1)
    df = frame(drift=(0.002, -0.002)).iloc[:k + 1].reset_index(drop=True)
    j1 = TJ.judge_frame(df, "BTCUSDT", "1h", RULES)
    j4 = TJ.judge_frame(df.assign(ts=df["ts"]), "BTCUSDT", "4h", RULES)
    assert j1.raw == -1 and j1.dir == 0 and "유지 확인 중" in j1.text(RULES)
    assert j4.raw == -1 and j4.dir == -1
    tired = dataclasses.replace(j, adx=45.0, adx_prev=47.0)
    assert tired.tired(RULES) and not dataclasses.replace(j, adx=45.0, adx_prev=44.0).tired(RULES)


# ---------------------------------------------------------------- the entry checks
def J(dir=1, raw=None, votes=None, adx=25.0, adx_prev=24.0, close=60000.0, ema20=59900.0, atr=300.0, tf="1h",
      bar_close=T0):
    votes = votes or {"V39": dir, "S6": dir, "OBV": dir, "N12": 0}
    return TJ.Judgment(symbol="BTCUSDT", tf=tf, bar_close=bar_close, votes=votes, raw=dir if raw is None else raw,
                       dir=dir, held=(dir, dir), adx=adx, adx_prev=adx_prev, close=close, ema20=ema20, atr=atr)


def S(ema20=60000.0, atr=180.0, rsi=50.0, rng=100.0, tf="30m"):
    return TJ.Spot(tf=tf, bar_close=T0, close=60000.0, ema20=ema20, atr=atr, rsi=rsi, range=rng)


@pytest.mark.parametrize("j,s,strategy,side,words", [
    (J(dir=0, raw=1), S(), "N08_ICHI_WR", 1, "1시간 추세 보류(상승 0·하락 0·중립 4, 상승 유지 확인 중)"),
    (J(dir=-1), S(), "N08_ICHI_WR", 1, "1시간 추세가 하락이라 롱 안 함"),
    (J(adx=18.0), S(), "N08_ICHI_WR", 1, "1시간 추세 힘 약함(ADX 18, 20 미만)"),
    (J(adx=44.0, adx_prev=46.0), S(), "N08_ICHI_WR", 1, "1시간 추세 끝물(ADX 44, 40 넘고 꺾임)"),
    (J(adx=33.0), S(), "F3_BOS", 1, "돌파형은 추세 초입만(ADX 33"),
    (J(adx=25.0, adx_prev=26.0), S(), "F15_ORB", 1, "돌파형은 추세 초입만(ADX 25, 꺾임"),
    (J(ema20=59000.0), S(), "N08_ICHI_WR", 1, "1시간 EMA20에서 3.3 ATR 위(너무 뻗음"),
    (J(), S(ema20=59600.0), "N08_ICHI_WR", 1, "30분 EMA20에서 2.2 ATR 위(진입 자리 아님"),
    (J(), S(rsi=71.0), "N08_ICHI_WR", 1, "30분 RSI 71 과열"),
    (J(dir=-1, ema20=60100.0), S(rsi=29.0), "N08_ICHI_WR", -1, "30분 RSI 29 침체"),
])
def test_entry_checks_in_order(j, s, strategy, side, words):
    if j.dir == 0:
        j = dataclasses.replace(j, votes={"V39": 0, "S6": 0, "OBV": 0, "N12": 0})
    why, info = TJ.check(RULES, strategy, "30m", side, 60000.0, j, s)
    assert why.startswith(words), why
    assert "judge" in info and "spot" in info


def test_a_pass_returns_the_pullback_deeper_after_a_long_bar_and_the_score():
    why, info = TJ.check(RULES, "N08_ICHI_WR", "30m", 1, 60000.0, J(), S())
    assert why == "" and info["pullback_atr"] == 0.25 and info["level"] == pytest.approx(60000.0 - 0.25 * 180.0)
    why, info = TJ.check(RULES, "N08_ICHI_WR", "30m", -1, 60000.0, J(dir=-1, ema20=60100.0), S(rng=400.0))
    assert why == "" and info["big_bar"] and info["level"] == pytest.approx(60000.0 + 0.5 * 180.0)
    # breakout early in the trend passes
    assert TJ.check(RULES, "F3_BOS", "30m", 1, 60000.0, J(adx=24.0, adx_prev=21.0), S())[0] == ""
    sc, parts = TJ.score(RULES, 1, J(votes={"V39": 1, "S6": 1, "OBV": 1, "N12": 1}), S(), 60000.0, [1, 1, -1, 1])
    assert parts == {"strength": 1.0, "spot": 1.0, "record": 0.25, "record_n": 4} and sc == pytest.approx(2.25)
    sc2, parts2 = TJ.score(RULES, 1, J(), S(ema20=59865.0), 60000.0, [1, -1])
    assert parts2["strength"] == 0.0 and parts2["record"] == 0.0 and parts2["spot"] == pytest.approx(0.5)


# ---------------------------------------------------------------- bars from Binance
def test_klines_closed_bars_only_and_a_failure_waits():
    now = {"t": T0 + 2 * HOUR + 2_000}
    calls = []
    rows = [[T0 - (300 - k) * HOUR, 1, 2, 0.5, 1.5, 10] for k in range(300)] + [[T0 + k * HOUR, 1, 2, 0.5, 1.5, 10]
                                                                               for k in range(3)]

    def fetch(sym, tf, n):
        calls.append((sym, tf, n))
        if now.get("down"):
            raise OSError("down")
        return rows
    k = TJ.Klines(fetch, lambda: now["t"])
    # 2 s after the 2h close: the bar closing at 2h is not settled yet; the one closing at 1h is there
    with pytest.raises(TJ.TrendError, match="아직 못 받음"):
        k.frame("BTCUSDT", "1h", now["t"])
    df = k.frame("BTCUSDT", "1h", T0 + 2 * HOUR - 1)
    assert int(df["ts"].iloc[-1].value // 1_000_000) == T0 and len(df) == TJ.KEEP
    now["t"] += 5_000
    df = k.frame("BTCUSDT", "1h", now["t"])
    assert int(df["ts"].iloc[-1].value // 1_000_000) == T0 + HOUR
    n = len(calls)
    k.frame("BTCUSDT", "1h", now["t"])                       # cached: no fetch
    assert len(calls) == n
    now.update(down=True, t=T0 + 3 * HOUR + 10_000)
    with pytest.raises(TJ.TrendError):
        k.frame("BTCUSDT", "1h", now["t"])
    assert k.errors and len(calls) == n + 1
    for sym in ("ETHUSDT", "SOLUSDT"):                       # any coin: no fetch while waiting
        with pytest.raises(TJ.TrendError):
            k.frame(sym, "1h", now["t"])
    assert len(calls) == n + 1
    now["t"] += TJ.RETRY_MS
    with pytest.raises(TJ.TrendError):
        k.frame("ETHUSDT", "1h", now["t"])
    assert len(calls) == n + 2 and k.wait_until - now["t"] == 2 * TJ.RETRY_MS


# ---------------------------------------------------------------- the runner
class FakeJudge:
    """Judgments and entry bars set by the test (bar_close follows the time asked)."""

    def __init__(self):
        self.j = {}
        self.s = {}
        self.fail = None
        self.k = types.SimpleNamespace(errors=[])

    def judgment(self, sym, tf, t):
        if self.fail:
            raise TJ.TrendError(self.fail)
        j = self.j.get((sym, tf)) or J(tf=tf)
        return dataclasses.replace(j, symbol=sym, tf=tf, bar_close=int(t) - int(t) % TJ.TF_MS[tf])

    def spot(self, sym, tf, t):
        if self.fail:
            raise TJ.TrendError(self.fail)
        s = self.s.get((sym, tf)) or S(tf=tf)
        return dataclasses.replace(s, tf=tf, bar_close=int(t) - int(t) % TJ.TF_MS[tf])


def tcfg(tmp_path, **kw):
    d = dict(paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "trend.db"),
             members=[{"strategy": "N08_ICHI_WR", "tf": "30m"}, {"strategy": "F3_BOS", "tf": "30m"},
                      {"strategy": "S3_CMO_SANDWICH", "tf": "1h"}],
             trend={}, rank=["score", "timeframe", "order"], margin=0.4, max_loss_frac=0.35, liq_buffer_atr=0.0,
             stop={"mode": "roe", "roe": 0.5, "net": True}, early_exit="own", early_exit_until_lock=True,
             ladder={"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03},
             name="추세판단 봇", telegram=True)
    d.update(kw)
    return C.ComboConfig.from_dict(d)


class World:
    def __init__(self, tmp_path, **kw):
        self.paper = Store3(str(tmp_path / "paper3.db"))
        self.now = T0
        self.px = dict(PX)
        self.cfg = tcfg(tmp_path, **kw)
        assert self.cfg.problems() == []
        self.note = ListNotifier()
        self.judge = FakeJudge()
        self.add_minutes(T0 - 10 * MIN, 10)
        self.open()

    def open(self):
        self.members = C.resolve_members(self.cfg.members, core=CORE)
        self.store = Store3(self.cfg.db)
        self.book = C.build_book(self.cfg, C.settings_of(self.cfg), BRACKETS, self.store, self.note, SPECS)
        self.run = TB.TrendRunner(self.cfg, self.members, self.book, self.store, self.note, None,
                                  now_ms=lambda: self.now, prices=lambda: {}, judge=self.judge)

    def restart(self):
        self.store.close()
        self.open()

    def add_minutes(self, start, n, move=None):
        rows = []
        for k in range(n):
            t = start + k * MIN
            for s in SYMS:
                o = self.px[s]
                c = o * (1 + (move or {}).get(s, 0.0))
                rows.append({"ts": t, "symbol": s, "open": o, "high": max(o, c) * 1.0001, "low": min(o, c) * 0.9999,
                             "close": c, "volume": 10.0, "mark_open": o, "mark_high": max(o, c), "mark_low": min(o, c),
                             "mark_close": c, "close_time": t + MIN - 1, "processed_at": t + MIN + 5000})
                self.px[s] = c
        self.paper.live_bars(rows)
        self.paper.commit()

    def signal(self, strategy, sym, side, bar_close, tf="30m"):
        ref = self.px[sym]
        self.paper.log_signals([{"bar_close": bar_close, "timeframe": tf, "strategy": strategy, "symbol": sym,
                                 "side": side, "atr": ref * 0.003, "ref_price": ref, "ref_time": bar_close + 20_000,
                                 "delay_ms": 20_000, "status": "SUBMITTED", "data": {"ctx": {}}}])
        self.paper.commit()

    def step(self, t, move=None):
        """The rule bot writes minute t; the bot polls a little after it closed."""
        self.add_minutes(t, 1, move)
        self.now = t + 65_000
        self.run.poll()

    def engine(self, aid=C.ACCOUNT):
        return self.book.engines[aid]

    def rows(self, member):
        return self.store.conn.execute("SELECT bar_close, status, data FROM signal_log WHERE strategy = ? ORDER BY id",
                                       (member,)).fetchall()

    def trades(self):
        return [json.loads(d) for (d,) in self.store.conn.execute(
            "SELECT data FROM trades WHERE account_id = ? ORDER BY id", (C.ACCOUNT,))]


def _start(w):
    w.now = T0 + 5_000
    w.run.poll()


def _to(w, a, b, move=None):
    for t in range(a, b, MIN):
        w.step(t, move)


def _enter_long(w, member="N08_ICHI_WR"):
    """A 30m long signal at B = T0 + 30 min, its pullback in the 2nd minute, the entry in the 3rd."""
    _start(w)
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal(member, "BTCUSDT", 1, B)
    w.step(B)                                       # due: waits for the pullback
    w.step(B + MIN, move={"BTCUSDT": -0.001})      # trades 0.1 % lower: the 0.25 ATR (0.075 %) level is touched
    w.step(B + 2 * MIN)                            # the entry minute
    p = w.engine().position
    assert p is not None and p.symbol == "BTCUSDT" and p.side == 1 and p.entry_time == B + 2 * MIN
    return B, p


def test_a_signal_with_the_trend_waits_for_its_pullback_then_enters(tmp_path):
    w = World(tmp_path)
    B, p = _enter_long(w)
    rows = w.rows("N08_ICHI_WR@30m")
    assert [(r[0], r[1]) for r in rows] == [(B, "BROKE"), (B + 2 * MIN, "SUBMITTED")]
    first = json.loads(rows[0][2])
    assert first["why"].startswith("되돌림 확인: ") and first["trend"]["judge"]["dir"] == 1
    assert p.signal.meta["pulled"] and p.signal.meta["pull_minute"] == B + MIN
    assert p.signal.meta["trend"]["judge"].startswith("1시간 상승")
    assert p.signal.score == pytest.approx(1.0)                   # 3 of 4 (0) + at the EMA20 (1) + no record (0)
    assert w.run.counts["N08_ICHI_WR@30m"] == {"waiting": 1, "submitted": 1}
    # the executor's reader sees the entry like any other (unchanged executor code)
    from paperbot.executor import Paper3Source
    it, _ts = Paper3Source(w.cfg.db, C.ACCOUNT).read()
    assert it.symbol == "BTCUSDT" and it.entry_time == B + 2 * MIN


def test_no_pullback_within_the_entry_bar_drops_the_signal(tmp_path):
    w = World(tmp_path)
    _start(w)
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)
    _to(w, B, B + 31 * MIN, move={"BTCUSDT": 0.0002})
    assert w.engine().position is None
    (bc, st, d), = w.rows("N08_ICHI_WR@30m")
    assert st == "FILTERED" and json.loads(d)["why"].startswith("되돌림 안 옴") and not w.run.pulls


def test_against_the_trend_is_filtered_and_still_closes_as_the_fast_stop(tmp_path):
    w = World(tmp_path)
    B, p = _enter_long(w)
    B2 = B + 30 * MIN
    _to(w, B + 3 * MIN, B2)
    w.signal("N08_ICHI_WR", "BTCUSDT", -1, B2)      # the 1h trend is still up: no short ...
    w.step(B2)
    assert w.engine().position is None              # ... but the same member turned: out (REV), no switch
    t, = w.trades()
    assert t["exit_reason"] == "REV" and t["exit_time"] == B2
    st, d = w.rows("N08_ICHI_WR@30m")[-1][1:]
    assert st == "FILTERED" and json.loads(d)["why"] == "1시간 추세가 상승이라 숏 안 함(상승 3·하락 0·중립 1)"
    assert json.loads(d)["trend"]["judge"]["text"].startswith("1시간 상승")


def test_an_unreadable_judgment_means_no_entry_and_an_alert(tmp_path):
    w = World(tmp_path)
    _start(w)
    w.judge.fail = "BTCUSDT 1시간 끝난 봉을 아직 못 받음"
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal("F3_BOS", "BTCUSDT", 1, B)
    w.step(B)
    (bc, st, d), = w.rows("F3_BOS@30m")
    assert st == "FILTERED" and "추세 판단을 못 읽어 진입 안 함" in json.loads(d)["why"]
    assert any("추세 판단을 못 읽어" in n[1] for n in w.note.messages)


def test_a_restart_keeps_the_wait(tmp_path):
    w = World(tmp_path)
    _start(w)
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)
    w.step(B)
    assert len(w.run.pulls) == 1
    w.restart()
    assert len(w.run.pulls) == 1 and w.run.since == T0              # the first start, kept
    w.step(B + MIN, move={"BTCUSDT": -0.001})
    w.step(B + 2 * MIN)
    assert w.engine().position is not None


# ---------------------------------------------------------------- the supervisor
def test_time_exit_after_four_entry_bars_without_the_first_lock(tmp_path):
    w = World(tmp_path)
    B, p = _enter_long(w)
    E = p.entry_time
    _to(w, B + 3 * MIN, E + 4 * 30 * MIN)
    assert w.engine().position is not None
    w.step(E + 4 * 30 * MIN)
    assert w.engine().position is None
    t, = w.trades()
    assert t["exit_reason"] == "TIME" and t["exit_time"] == E + 120 * MIN
    assert t["context"]["exit_why"] == "진입 봉 4개(30분 4개) 안에 첫 잠금 못 감"
    assert any("감독 청산(시간 정리)(진입 봉 4개" in n[1] for n in w.note.messages)


def test_judge_exit_when_a_later_higher_bar_turns_and_never_after_the_first_lock(tmp_path):
    w = World(tmp_path)
    B, p = _enter_long(w)
    w.judge.j[("BTCUSDT", "1h")] = J(dir=-1, votes={"V39": -1, "S6": -1, "OBV": -1, "N12": 1})
    H = T0 + HOUR                                   # the first 1h bar closed after the entry
    _to(w, B + 3 * MIN, H)
    assert w.engine().position is not None          # the bar judged at the entry closed before it: no exit
    w.step(H)
    t, = w.trades()
    assert t["exit_reason"] == "JUDGE" and t["exit_time"] == H
    assert t["context"]["exit_why"] == "1시간 판단이 하락로 바뀜(상승 1·하락 3·중립 0)"
    # with the first lock: the ladder alone decides
    (tmp_path / "b").mkdir()
    w2 = World(tmp_path / "b")
    B, p = _enter_long(w2)
    p.lock_roe = 0.10
    w2.judge.j[("BTCUSDT", "1h")] = J(dir=-1)
    _to(w2, B + 3 * MIN, B + 3 * HOUR)
    assert w2.engine().position is not None and not w2.trades()


# ---------------------------------------------------------------- the pauses
def _rec(w, member, symbol, side, pnl, exit_t, tf="30m"):
    w.store.trade(C.ACCOUNT, TradeRecord(
        strategy_id=member, symbol=symbol, timeframe=tf, side=side, signal_ts=exit_t - HOUR - 1,
        entry_time=exit_t - HOUR, entry_price=PX[symbol], exit_time=exit_t, exit_price=PX[symbol], exit_reason="SL",
        qty=1.0, leverage=40, tier="best", margin=400.0, stop_price=0.0, tp_price=float("nan"), liq_price=0.0,
        fees=0.0, funding=0.0, pnl=pnl, roe=pnl / 400.0, price_move=0.0, mae_price=0.0, mfe_price=0.0,
        equity_after=1000.0 + pnl, score=1.0, stop_initial=0.0, lock_roe=None))
    w.store.commit()


def test_a_member_with_two_losses_in_a_row_pauses_24_hours(tmp_path):
    w = World(tmp_path)
    _start(w)
    w.run.since = T0 - 3 * HOUR                     # the bot's own trades start here
    _rec(w, "N08_ICHI_WR", "ETHUSDT", 1, -50.0, T0 - 2 * HOUR)
    _rec(w, "N08_ICHI_WR", "SOLUSDT", -1, -40.0, T0 - HOUR)
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)
    w.signal("F3_BOS", "BTCUSDT", 1, B)
    w.step(B)
    (_bc, st, d), = w.rows("N08_ICHI_WR@30m")
    assert st == "FILTERED" and json.loads(d)["why"].startswith("N08_ICHI_WR 30분 손실 2번 연속: ")
    assert w.rows("F3_BOS@30m")[0][1] == "WAITING"          # another member goes on
    warns = [n for n in w.note.messages if "그 매매법만 쉼" in n[1]]
    assert len(warns) == 1
    pz = w.run.pauses(B)
    assert list(pz["members"]) == ["N08_ICHI_WR@30m"] and pz["members"]["N08_ICHI_WR@30m"][1] == T0 - HOUR + 24 * HOUR
    assert ("SOLUSDT", -1) in pz["coins"] and ("ETHUSDT", 1) not in pz["coins"]   # 2 h after its loss


def test_the_coin_and_side_pause_and_the_daily_loss_limit(tmp_path):
    w = World(tmp_path)
    _start(w)
    w.run.since = T0 - 3 * HOUR
    _rec(w, "F3_BOS", "BTCUSDT", 1, -100.0, T0 - 30 * MIN)
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)
    w.signal("S3_CMO_SANDWICH", "BTCUSDT", -1, B, tf="1h")
    w.judge.j[("BTCUSDT", "4h")] = J(dir=-1, ema20=60100.0, tf="4h")
    w.step(B)
    st, d = w.rows("N08_ICHI_WR@30m")[0][1:]
    assert st == "FILTERED" and json.loads(d)["why"].startswith("BTC 롱 손실 뒤 2시간 쉼")
    assert w.rows("S3_CMO_SANDWICH@1h")[0][1] == "WAITING"   # the other side goes on
    # the KST day (it started at T0 - 9 h + ... : 00:00 KST = 15:00 UTC the day before) lost 30 %
    _rec(w, "S3_CMO_SANDWICH", "ETHUSDT", -1, -250.0, B + 5 * MIN, tf="1h")
    B2 = T0 + HOUR
    _to(w, B + MIN, B2)
    w.signal("F3_BOS", "SOLUSDT", 1, B2)
    w.step(B2)
    st, d = w.rows("F3_BOS@30m")[0][1:]
    assert st == "FILTERED" and json.loads(d)["why"].startswith("하루 손실 한도: 오늘(한국 시간) 계좌 -35%")
    assert sum("하루 손실 한도" in n[1] for n in w.note.messages) == 1


def test_the_live_site_state(tmp_path):
    w = World(tmp_path)
    _start(w)
    B = T0 + 30 * MIN
    w.add_minutes(T0, 30)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)
    w.step(B)
    ts, st = w.store.get_state(TB.STATE_TREND)
    assert ts == B and set(st["coins"]) == set(SYMS) and st["coins"]["BTCUSDT"]["1h"]["dir"] == 1
    assert st["coins"]["BTCUSDT"]["4h"]["text"].startswith("4시간 상승")
    (wt,) = st["waits"]
    assert wt["member"] == "N08_ICHI_WR@30m" and wt["until"] == B + 30 * MIN and st["rules"] == RULES.describe()


# ---------------------------------------------------------------- the config
def test_the_deploy_config_and_refusals(tmp_path):
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "combo.trend.json")
    cfg = C.ComboConfig.from_file(path)
    assert cfg.problems() == [] and cfg.db == "/var/lib/paperbot/combo/live-ac.db" and cfg.name == "추세판단 봇"
    assert TJ.TrendRules.from_dict(cfg.trend) == TJ.TrendRules()
    ms = C.resolve_members(cfg.members, cfg.picks_file)
    assert [m.label for m in ms] == ["N08_ICHI_WR@30m", "N05_PSAR_POC@30m", "F3_BOS@30m", "F15_ORB@30m",
                                     "N06_MACD_ORB@30m", "S3_CMO_SANDWICH@30m", "N20_EMA9_CHOP@30m", "F9_FVG@1h",
                                     "F9_IFVG@1h", "S3_CMO_SANDWICH@1h"]
    assert all(m.no_chase for m in ms) and ms[6].when == ((("side", -1),),)
    assert C.make_cls(cfg).func is TB.TrendEngine and C.make_cls(dataclasses.replace(cfg, trend=None)).func is C.ComboEngine
    bad = tcfg(tmp_path, members=[{"strategy": "N08_ICHI_WR", "tf": "15m"}], rank=["order"],
               trend={"adx_min": 50, "nope": 1})
    assert "trend에 알 수 없는 이름: nope" in " ".join(bad.problems())
    probs = " | ".join(tcfg(tmp_path, members=[{"strategy": "N08_ICHI_WR", "tf": "15m"},
                                               {"strategy": "F3_BOS", "tf": "30m", "numbers": {}}],
                            rank=["order"], trend={"adx_min": 50}).problems())
    for want in ("30m 또는 1h만", "기본값 신호만", '"score"로 시작', "adx_tired는 adx_min보다"):
        assert want in probs, probs


# ---------------------------------------------------------------- the switch on the server (deploy/trend_switch.py)
def _switch():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "trend_switch.py")
    spec = importlib.util.spec_from_file_location("trend_switch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_switch_shows_then_writes_and_keeps_the_old_files(tmp_path, capsys):
    import os
    S = _switch()
    deploy = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy")
    combo, woo, bybit = tmp_path / "combo.json", tmp_path / "executor-mexc.json", tmp_path / "executor.json"
    combo.write_text(open(os.path.join(deploy, "combo.live15.json"), encoding="utf-8").read(), encoding="utf-8")
    woo.write_text(open(os.path.join(deploy, "executor.live-wooxpro.json"), encoding="utf-8").read(), encoding="utf-8")
    bybit.write_text(open(os.path.join(deploy, "executor.live-bybit.json"), encoding="utf-8").read(), encoding="utf-8")
    os.chmod(combo, 0o640)
    before = {p: p.read_text(encoding="utf-8") for p in (combo, woo, bybit)}
    args = ["--combo", str(combo), "--exec", str(woo), "--exec", str(bybit)]
    assert S.main(args) == 0
    out = capsys.readouterr().out
    assert "규칙봇 15 → 추세판단 봇 · 매매법 14개 → 진입 10개" in out and "보여 주기만" in out
    assert "paper_db /var/lib/paperbot/combo/live15-mexc.db → /var/lib/paperbot/combo/live-ac.db" in out
    assert "paper_db 그대로 /var/lib/paperbot/combo/live-ac.db" in out
    assert {p: p.read_text(encoding="utf-8") for p in before} == before            # nothing written
    assert S.main(args + ["--write"]) == 0
    out = capsys.readouterr().out
    assert json.loads(combo.read_text(encoding="utf-8")) == json.loads(open(os.path.join(deploy, "combo.trend.json"),
                                                                           encoding="utf-8").read())
    assert oct(os.stat(combo).st_mode & 0o777) == "0o640"
    w = json.loads(woo.read_text(encoding="utf-8"))
    assert w["paper_db"] == "/var/lib/paperbot/combo/live-ac.db"
    assert {k: v for k, v in w.items() if k != "paper_db"} == {k: v for k, v in json.loads(before[woo]).items() if k != "paper_db"}
    assert bybit.read_text(encoding="utf-8") == before[bybit]
    backups = sorted(p.name for p in tmp_path.iterdir() if ".before-trend-" in p.name)
    assert len(backups) == 2 and backups[0].startswith("combo.json.before-trend-")
    # again: nothing left to change
    assert S.main(args + ["--write"]) == 0
    assert "이미 추세판단 봇 설정" in capsys.readouterr().out
    # a config of another database: refused
    other = tmp_path / "other.json"
    other.write_text(json.dumps({**json.loads(before[combo]), "db": "/var/lib/paperbot/combo/x.db"}), encoding="utf-8")
    assert S.main(["--combo", str(other), "--exec", str(woo)]) == 1
    assert "db" in capsys.readouterr().out


def test_the_old_rules_shadow_is_the_live15_bot_on_its_own_database():
    import os
    deploy = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy")
    live = json.load(open(os.path.join(deploy, "combo.live15.json"), encoding="utf-8"))
    sh = json.load(open(os.path.join(deploy, "combo.shadow-rule15.json"), encoding="utf-8"))
    assert sh["db"] == "/var/lib/paperbot/combo/shadow-rule15.db" and sh["telegram"] is False
    assert {k: v for k, v in sh.items() if k not in ("db", "telegram", "name")} == \
        {k: v for k, v in live.items() if k not in ("db", "telegram", "name")}
    cfg = C.ComboConfig.from_dict(sh)
    assert cfg.problems() == [] and cfg.trend is None


# ---------------------------------------------------------------- the morning check's replay (paperbot/livereplay.py)
class _Market:
    """A flat-ish market for livereplay: every interval from one 1m walk, closed bars only."""

    def __init__(self):
        rng = np.random.default_rng(3)
        self.t0 = T0 - 400 * 4 * HOUR
        n = (T0 + 2 * 86_400_000 - self.t0) // MIN
        self.c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.0004, int(n))))

    def klines(self, symbol, interval, start, end):
        from paperbot import livereplay as LR
        ms = LR.IV_MS[interval]
        k = ms // MIN
        out = []
        t = max(int(start), self.t0) - (max(int(start), self.t0) - self.t0) % ms
        scale = PX[symbol] / 60000
        while t < end and (t - self.t0) // MIN + k <= len(self.c):
            i = (t - self.t0) // MIN
            seg = self.c[i:i + k] * scale
            out.append([t, float(seg[0]), float(seg.max()), float(seg.min()), float(seg[-1]), 100.0])
            t += ms
        return out

    def mark_klines(self, symbol, start, end):
        return [r[:5] for r in self.klines(symbol, "1m", start, end)]

    def funding(self, symbol, start, end):
        return []

    def oi(self, symbol, start, end):
        return []

    def specs(self, symbols):
        return {s: SPECS[s] for s in symbols}

    def brackets(self, cfg):
        return {s: BRK for s in cfg.symbols}, "test"


def test_the_morning_replay_runs_the_trend_bot(tmp_path):
    import os
    from paperbot import livereplay as LR
    deploy = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy")
    raw = json.load(open(os.path.join(deploy, "combo.trend.json"), encoding="utf-8"))
    hist = {"since": T0 - 86_400_000, "trades": [dataclasses.asdict(TradeRecord(
        strategy_id="F3_BOS", symbol="BTCUSDT", timeframe="30m", side=1, signal_ts=T0 - 2 * HOUR - 1,
        entry_time=T0 - 2 * HOUR, entry_price=60000.0, exit_time=T0 - HOUR, exit_price=59000.0, exit_reason="SL",
        qty=0.01, leverage=40, tier="best", margin=15.0, stop_price=0.0, tp_price=float("nan"), liq_price=0.0,
        fees=0.0, funding=0.0, pnl=-7.5, roe=-0.5, price_move=-0.0167, mae_price=0.0, mfe_price=0.0,
        equity_after=992.5, score=1.0, stop_initial=0.0, lock_roe=None))]}
    res = LR.replay_day(raw, _Market(), T0, T0 + 3 * HOUR, seed={"trend_history": hist}, now_ms=T0 + 4 * HOUR,
                        workdir=str(tmp_path))
    assert res.minutes > 0 and res.trades == [] and not res.seeded           # the history is not one of the day's trades
    assert not [e for e in res.errors if "Traceback" in e]
