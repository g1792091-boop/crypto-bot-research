"""Owners 2026-10-31: '추세 3개 일치' (EMARSI_ALL.pine).

- friendtrend part 7: the three trends (EMA RSI green / red, the sky / purple line, the supertrend average of ATR 14 with
  factors 3 and 5) and the EMA RSI histogram's light -> dark bar; a read on the history up to a bar is the pane at that
  bar; 1,500 bars read the same last values as a longer history; a side needs all three trends that way;
- 친구 15분 봇 (WOO X Pro 2, paperbot/mixchop.py): rules "obv" and "ema3" on 15m bars; "ema3" enters on its own three
  trends (not the four votes); the deploy configs; its signals listing and the morning replay;
- the 레인지 봇 slot (WOO X Pro): the range filter member and the ROC entry are gone, 추세 3개 일치 on 15m bars is its
  only entry (members [], range.ema3_tf "15m"): the 5m history is kept without a custom member, a turn with its three
  trends enters at the next minute's open with an ATR x 3 stop on the ladder, the liquidation room, one position; the
  read equals friendtrend's on the same 5m history; check-config, the start words and the site's words."""
import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest

from paperbot import combo as C
from paperbot import friendtrend as FT
from paperbot import mixcheck as MC
from paperbot import mixchop as M
from paperbot import rangebot as RB

sys.path.insert(0, os.path.dirname(__file__))
import test_rangebot as TR  # noqa: E402
from test_rules1030 import frame, walk  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
MIN, FIVE, HOUR = 60_000, 300_000, 3_600_000


# ====================================================================== friendtrend part 7
def test_the_three_trends_and_the_histogram_turn_on_a_prefix():
    o, h, lo, c, v = walk(1200, seed=17)
    P = FT.ema3_pane(h, lo, c)
    # the parts: the EMA RSI of part 1, the sky / purple line of part 1, the supertrend average 14·3 / 14·5
    er = FT.ema_rsi(c)
    assert np.allclose(P["ersi"][100:], er[100:]) and (P["line"] == np.where(M.line_gold(c), 1, -1)).all()
    _, a = M.supertrend(h, lo, c, 14, 3.0)
    _, b = M.supertrend(h, lo, c, 14, 5.0)
    assert (P["st"] == np.where(a & b, 1, np.where(~a & ~b, -1, 0))).all()
    want_tr = np.where((P["ema"] == 1) & (P["line"] == 1) & (P["st"] == 1), 1,
                       np.where((P["ema"] == -1) & (P["line"] == -1) & (P["st"] == -1), -1, 0))
    assert (P["trend"] == want_tr).all()
    cs, dark = P["cs"], P["dark"]
    turns = [i for i in range(300, len(c)) if cs[i] == cs[i - 1] != 0 and dark[i] and not dark[i - 1]]
    assert len(turns) >= 20
    sides = set()
    for i in turns:
        st = FT.ema3_state(h[:i + 1], lo[:i + 1], c[:i + 1])
        assert st["turn"] == cs[i] and st["trend"] == P["trend"][i]
        assert st["side"] == (cs[i] if P["trend"][i] == cs[i] else 0)
        sides.add(st["side"])
    assert sides == {1, -1, 0}
    # the owners' rule: 2 up 1 down, or sideways -> no entry
    assert FT.ema3_words({"trend": 0, "votes": {"ema": 1, "line": 1, "st": -1}}) == \
        "진입 금지 (EMA RSI 초록 · 하늘·보라 선 하늘 · 슈퍼트렌드 하락)"
    assert FT.ema3_words({"trend": 1, "votes": {"ema": 1, "line": 1, "st": 1}}).startswith("3개 상승 (")


def test_fifteen_hundred_bars_read_the_same_three_trends():
    o, h, lo, c, v = walk(4000, seed=19)
    cut = slice(-1500, None)
    P, Q = FT.ema3_pane(h, lo, c), FT.ema3_pane(h[cut], lo[cut], c[cut])
    for k in ("ema", "line", "st", "trend", "cs"):
        assert (P[k][-300:] == Q[k][-300:]).all(), k
    assert (P["dark"][-300:] == Q["dark"][-300:]).all()
    assert FT.ema3_state(h, lo, c) == FT.ema3_state(h[cut], lo[cut], c[cut])


# ====================================================================== 친구 15분 봇
def test_the_friend_bot_runs_obv_and_ema3_on_15m(tmp_path):
    # the 10-31 day's form (10-31 evening: 30m bars, the OBV turn with the AC bar, tests/test_rules1031b.py)
    for name, mode in (("mixchop.live.json", "mainnet"), ("mixchop.paper.json", "paper")):
        d = json.loads((DEPLOY / name).read_text(encoding="utf-8"))
        d.update(name="친구 15분 봇", tf="15m", rules=["obv", "ema3"])
        p = tmp_path / name
        p.write_text(json.dumps(d), encoding="utf-8")
        cfg = M.load_config(str(p))
        assert cfg.mode == mode and cfg.name == "친구 15분 봇" and cfg.exchange == "wooxpro"
        assert (cfg.tf, cfg.trend, cfg.rules, cfg.stop_atr) == ("15m", "four", ("obv", "ema3"), 3.0)
        assert {c.symbol: c.leverage for c in cfg.coins} == {"SOLUSDT": 40, "ETHUSDT": 40, "XRPUSDT": 40, "BCHUSDT": 40,
                                                            "ZECUSDT": 20, "DOGEUSDT": 40}
        assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0} and cfg.margin_frac == 0.4
        assert "매매법 OBV 진한색 + 추세 3개 일치(같은 봉이면 OBV 진한색 먼저)" in M.plan_words(cfg)


def test_ema3_enters_on_its_own_three_trends(monkeypatch):
    b15 = frame(400, tf_ms=M.MIN15, vol=0.002)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    four = {"trend": -1, "line": -1, "ema": -1, "chop": -1, "st": 0, "ema_rsi": 40.0, "chop_zone": -2}

    def run(e3):
        monkeypatch.setattr(FT, "ema3_state", lambda *a: e3)
        monkeypatch.setattr(FT, "last_trend", lambda *a: four)       # the four votes say down: not this rule's trend
        return M.evaluate_friend("ema3", co, b15, T0, M.MIN15, "four")
    up = {"trend": 1, "votes": {"ema": 1, "line": 1, "st": 1}, "ersi": 63.4, "cs": 1, "dark": True, "turn": 1, "side": 1}
    ev = run(up)
    assert ev["side"] == 1 and ev["trend"] == 1 and ev["e3_turn"] == 1 and ev["ersi"] == 63.4 and ev["tf"] == "15분"
    a = float(M.atr(b15.high, b15.low, b15.close, 14)[-1])
    assert ev["stop_dist"] == pytest.approx(3 * a)
    words = M.reason_words(ev, 1, name=True)
    assert words.startswith("근거(추세 3개 일치): EMA RSI 막대 연한 초록→진한 초록(EMA RSI 63.4) · 추세 15분 3개 상승 (EMA RSI 초록")
    ev = run({**up, "trend": 0, "votes": {"ema": 1, "line": 1, "st": 0}, "side": 0})
    assert ev["side"] == 0 and ev["why"] == "EMA RSI 막대 진한 초록인데 추세 진입 금지 (EMA RSI 초록 · 하늘·보라 선 하늘 · 슈퍼트렌드 횡보)"
    ev = run({**up, "turn": 0, "side": 0})
    assert ev["why"] == "EMA RSI 막대 연한색→진한색 없음"
    row = M.board_row([run(up)], T0)
    assert row["rules"]["ema3"]["side"] == 1 and row["e3_votes"] == {"ema": 1, "line": 1, "st": 1}


def test_the_ema3_signals_listing_and_the_morning_replay():
    cfg = M.load_config(str(DEPLOY / "mixchop.paper.json"))
    cfg.coins = cfg.coins[:1]
    cfg.rules = ("ema3",)
    cfg.tf = "15m"                                       # the 10-31 day's bars (10-31 evening: 30m)
    rng = np.random.default_rng(41)
    n = 2000
    day0 = T0 - 24 * HOUR
    t15 = T0 - M.MIN15 * np.arange(n, 0, -1)
    c = 150 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    rows = [[int(t15[i]), o[i], hi[i], lo[i], c[i], rng.uniform(100, 1000)] for i in range(n)]
    b = M.bars_frame(rows, M.MIN15, T0)
    lines = M.friend_history(cfg.coins[0], b, "ema3", 5, M.MIN15)
    assert 1 <= len(lines) <= 5 and all("EMA RSI 막대" in x and "추세 " in x and "→" in x for x in lines)

    def klines(symbol, tf, start, limit):
        assert tf == "15m"
        return [r for r in rows if r[0] >= start][:limit]
    log = []
    co = cfg.coins[0]
    for ce in range(day0 + M.MIN15, T0 + 1, M.MIN15):
        bb = M.bars_frame(rows, M.MIN15, ce).tail(M.BARS - 1).reset_index(drop=True)
        ev = M.Bot.judge("ema3", co, bb, bb, ce, M.MIN15, "four")
        if ev.get("e3_turn") or ev["side"]:
            log.append({"ts": ce + 5_000, "kind": "signal", **ev})
    assert log
    rp = MC.signal_replay(cfg, day0, T0, log, klines, obs=[[T0 + 3 * MIN, T0, None]], st_last=T0)
    assert rp["state"] == "ok" and rp["different"] == [] and rp["rules"] == ["ema3"]
    assert rp["e3_turns"] == sum(1 for r in log if r.get("e3_turn"))
    assert f"EMA RSI 막대 연한→진한 {rp['e3_turns']}번" in MC.replay_lines(rp)[0]
    gone = log[0]
    rp2 = MC.signal_replay(cfg, day0, T0, log[1:], klines, obs=[], st_last=T0)
    assert any(x["close_ms"] == gone["close_ms"] and x["rule"] == "ema3" for x in rp2["missed"] + rp2["unsure"])


# ====================================================================== the 레인지 봇 slot: 추세 3개 일치 only
H = TR.H
Q = TR.T0 + 15 * MIN                     # a 15m close


def _e3(side=1, trend=None, atr=100.0, close=60000.0, ersi=None):
    tr = side if trend is None else trend
    return {"e3": {"trend": tr, "votes": {"ema": tr, "line": tr or 1, "st": tr}, "ersi": ersi if ersi is not None else
                   (62.0 if side >= 0 else 38.0), "cs": side or 1, "dark": True, "turn": side, "side": side if tr == side else 0},
            "atr": atr, "close": close}


class E3World(TR.World):
    """The range test world on the deploy config of 10-31 (no member, 추세 3개 일치 15m only); ``e3``: {(symbol, 15m
    close): read}, every other a read without a turn."""

    def __init__(self, tmp_path, **kw):
        self.e3: dict = {}
        self.reads: list = []
        super().__init__(tmp_path, deploy=True, **kw)

    def open(self):
        super().open()

        def read(sym, bc):
            self.reads.append((sym, bc))
            return self.e3.get((sym, bc), _e3(0, trend=0))
        self.run.ema3_read = read

        def boom(*a):
            raise AssertionError("no ROC read without roc_tf")
        self.run.roc_read = boom


def _go(w, upto):
    w.now = TR.T0 + 5_000
    w.run.poll()
    w.to(TR.T0, upto)


def test_the_deploy_config_is_ema3_only(tmp_path, capsys):
    d = json.loads((DEPLOY / "combo.range.json").read_text(encoding="utf-8"))
    assert d["members"] == [] and d["range"]["ema3_tf"] == "15m" and d["range"]["ema3_stop_atr"] == 3 and d["range"]["roc_tf"] is None
    cfg = TR.rcfg(tmp_path, deploy=True)
    assert cfg.problems() == [] and C.settings_of(cfg).tp_mode == "ladder"
    rules = RB.RangeRules.from_dict(cfg.range)
    assert rules.extras() == {"ema3": "15m"} and RB.hist_need(cfg.range) == 1500 * 3 + 12
    words = rules.describe(range_on=False)
    assert words[0] == RB.ONE_WORDS and words[1].startswith("추세 3개 일치(15분봉): EMA RSI · 하늘·보라 선 · 슈퍼트렌드(14·3 / 14·5)")
    assert "손절 15분 ATR(14) × 3, 그 거리가 (1/배수 - 0.5%) 안쪽일 때만" in words[1] and not any("되돌림" in x for x in words)
    assert C.stop_text(cfg) == "추세 3개 일치 15분 ATR(14) × 3"
    assert C.cmd_check(Namespace(config=str(DEPLOY / "combo.range.json"))) == 0
    out = capsys.readouterr().out
    assert "- 추세 3개 일치(15분봉):" in out and "손절: 추세 3개 일치 15분 ATR(14) × 3 / 계단 익절" in out and out.strip().endswith("준비됨")
    assert "F7_RF_TRIPLE" not in out and "ROC 진입" not in out
    text = C.start_text(cfg, [], 1000.0)
    assert "추세 3개 일치(15분봉)" in text and "계단 익절" in text
    from paperbot.dash.more import livebots as L
    assert [x["ko"] for x in L.range_words(d)] == words
    # wrong numbers; no entry at all
    for over, want in (({"ema3_tf": "1h"}, "range.ema3_tf"), ({"ema3_stop_atr": 20}, "range.ema3_stop_atr")):
        assert any(want in p for p in TR.rcfg(tmp_path, deploy=True, range={**cfg.range, **over}).problems()), over
    assert any("members가 비어 있습니다" in p for p in TR.rcfg(tmp_path, deploy=True, range={**cfg.range, "ema3_tf": None}).problems())


def test_the_5m_history_is_kept_without_a_custom_member():
    from paperbot.models import Bar
    cs = C.CustomSignals([], ["BTCUSDT"], keep_min=RB.hist_need({"ema3_tf": "15m"}))
    assert cs.members == [] and cs.keep == 4512
    for k in range(10):
        cs.add_1m(Bar("BTCUSDT", TR.T0 + k * MIN, TR.T0 + (k + 1) * MIN - 1, 100.0, 101.0, 99.0, 100.5, volume=5.0))
    assert [r[0] for r in cs.hist["BTCUSDT"]] == [TR.T0, TR.T0 + FIVE]  # ten minutes: two complete 5m bars
    assert C.CustomSignals([], ["BTCUSDT"]).keep == 0                   # every other bot: as before


def test_a_15m_turn_with_its_three_trends_enters_with_an_atr_stop_on_the_ladder(tmp_path):
    w = E3World(tmp_path)
    w.e3[("BTCUSDT", Q)] = _e3(1, atr=100.0, ersi=63.4)
    _go(w, Q + MIN)
    assert {bc for _s, bc in w.reads} == {Q} and {s for s, _bc in w.reads} == set(TR.SYMS)
    bc, sym, st, d = w.rows()[0]
    assert (bc, sym, st) == (Q, "BTCUSDT", "SUBMITTED")
    row = w.store.conn.execute("SELECT timeframe, strategy FROM signal_log WHERE bar_close = ?", (Q,)).fetchone()
    assert row == ("15m", "EMA3-15m")
    p = w.engine().position
    assert p is not None and p.symbol == "BTCUSDT" and p.side == 1 and p.entry_time == Q and p.leverage == 40
    assert p.signal.meta["stop_dist"] == pytest.approx(300.0) and p.signal.meta["range"]["ema3"] is True
    assert p.tp_price != p.tp_price                                     # the ladder, no fixed take-profit
    ent = [m for _l, m in w.note.messages if "진입" in m and "추세 3개 일치" in m]
    assert ent and "추세 3개 일치 15분봉 10-05 09:15 마감: EMA RSI 막대 연한 초록→진한 초록(EMA RSI 63.4)" in ent[-1]
    assert "추세 3개 상승 (EMA RSI 초록 · 하늘·보라 선 하늘 · 슈퍼트렌드 상승)" in ent[-1] and "손절 15분 ATR(100) × 3" in ent[-1]
    # while it holds, the next 15m turn is filtered (one position)
    w.e3[("ETHUSDT", Q + 15 * MIN)] = _e3(1, close=2500.0, atr=5.0)
    w.to(Q + MIN, Q + 16 * MIN)
    rows = {(sym, bc): (st, d.get("why", "")) for bc, sym, st, d in w.rows()}
    assert rows[("ETHUSDT", Q + 15 * MIN)] == ("FILTERED", "한 신호씩: BTC 롱 포지션 들고 있음")
    _ts, snap = w.store.get_state(RB.STATE_RANGE)
    assert snap["ema3"]["ETHUSDT"]["side"] == 1 and snap["ema3"]["ETHUSDT"]["at"] == Q + 15 * MIN
    assert "roc" not in snap and snap["supertrend"] == {}                # no range member: no 1h trend read


def test_too_wild_for_the_liquidation_room_and_no_side_without_the_trends(tmp_path):
    w = E3World(tmp_path)
    w.e3[("SOLUSDT", Q)] = _e3(-1, close=150.0, atr=1.5)                 # 3 x 1.5 = 3 % > 1/30 - 0.5 %
    w.e3[("ETHUSDT", Q)] = _e3(1, trend=0)                                # a turn without its three trends: no row
    _go(w, Q + MIN)
    rows = {(sym, bc): (st, d.get("why", "")) for bc, sym, st, d in w.rows()}
    assert rows == {("SOLUSDT", Q): ("FILTERED", "강제청산 여유 부족: 손절 15분 ATR × 3 = 3.00% > 2.83%(30배)")}
    assert w.engine().position is None


def test_the_ema3_read_equals_friendtrend_on_the_same_history(tmp_path):
    from paperbot import sweepsig
    from paperbot.dssig import frame as dsframe
    lib = sweepsig.lib()
    custom = C.CustomSignals([], ["BTCUSDT"], lib=lib, keep_min=RB.hist_need({"ema3_tf": "15m"}))
    rng = np.random.default_rng(23)
    n = 1700 * 3
    ts0 = TR.T0 - n * FIVE
    c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.0015, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.0008, np.minimum(o, c) * 0.9992
    vol = rng.uniform(1.0, 9.0, n)
    custom.bootstrap("BTCUSDT", [(ts0 + k * FIVE, o[k], hi[k], lo[k], c[k], vol[k]) for k in range(n)])
    w = TR.World(tmp_path, deploy=True)
    run = RB.RangeRunner(w.cfg, w.members, w.book, w.store, w.note, custom, now_ms=lambda: TR.T0, prices=lambda: {})
    df = dsframe(np.array([ts0 + k * FIVE for k in range(n)]), o, hi, lo, c, vol, tf="15m", lib=lib).tail(RB.ROC_BARS)
    a = {k: df[k].to_numpy(float) for k in ("high", "low", "close")}
    got = run.ema3_read("BTCUSDT", TR.T0)
    assert got["e3"] == FT.ema3_state(a["high"], a["low"], a["close"])
    assert got["atr"] == pytest.approx(float(M.atr(a["high"], a["low"], a["close"], 14)[-1]))
    with pytest.raises(C.ComboError, match="15분봉이 없음"):
        run.ema3_read("BTCUSDT", TR.T0 + 5 * MIN)
    assert run.extra["ema3"].label == "EMA3-15m" and run.roc is None and "EMA3-15m" in run.by_label


def test_the_site_reads_the_ema3_entry(tmp_path):
    from paperbot.dash.more import livebots as L
    from paperbot.dash.more import liverange as R
    from paperbot.dash.more import livewhy as W
    cfg = json.loads((DEPLOY / "combo.range.json").read_text(encoding="utf-8"))
    info = {"ema3": True, "side": -1, "close": 60000.0, "atr": 100.0, "k": 3.0, "t0": Q, "ersi": 37.5, "turn": -1,
            "e3_trend": -1, "e3_votes": {"ema": -1, "line": -1, "st": -1}, "tf": "15m"}
    out = {x["id"]: x for x in W.range_checks(cfg, Q + MIN, -1, "BTCUSDT", 40, info, 0.0014)}
    assert out["ema3_trend"]["ok"] is True and out["ema3_trend"]["ko"].startswith("추세 3개: 3개 하락 (EMA RSI 빨강 · 하늘·보라 선 보라")
    assert out["ema3"]["ko"].endswith("EMA RSI 막대 연한 빨강→진한 빨강 (EMA RSI 37.5)")
    assert out["liq"]["ko"] == "강제청산 여유: 손절 15분 ATR × 3 = 0.50% → 2.00% 안쪽 (40배)"
    assert out["tp"]["ko"].startswith("익절은 계단 순ROE 10%에서 8% 잠금") and "pull" not in out
    snap = {"range": (TR.T0, {"supertrend": {}, "busy": "", "rules": [],
                              "ema3": {"BTCUSDT": {"at": Q, "turn": 1, "cs": 1, "dark": True, "ersi": 63.0, "side": 1, "trend": 1},
                                       "ETHUSDT": {"at": Q, "turn": 0, "cs": -1, "dark": False, "ersi": 44.0, "side": 0, "trend": -1}}})}
    sv = R.supertrend_of(snap, TR.T0)
    assert [(x["coin"], x["side"], x["ko"]) for x in sv["ema3"]] == [("BTC", 1, "롱 신호"), ("ETH", 0, "3개 하락 · 막대 빨강 연함")]
    rows = R.signals_view({"signals": [(1, Q, "15m", "EMA3-15m", "BTCUSDT", 1, "FILTERED", json.dumps({"why": "한 신호씩: …"}))],
                           "outcomes": []}, TR.T0 + HOUR)["rows"]
    assert rows[0]["entry_ko"] == "추세 3개 15분"
    pl = {x["key"]: x["ko"] for x in R.plan_of(cfg, [], 0.0014)["lines"]}
    assert pl["signal"].startswith("추세 3개 일치") and "pull" not in pl and "liq" not in pl and pl["one"].startswith("포지션 있는 동안")
    assert [x["id"] for x in L.range_words(cfg)] == ["range_one", "range_ema3", "range_none"]
