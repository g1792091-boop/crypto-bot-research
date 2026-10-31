"""Owners 2026-10-30: the three bots' new rules.

- friendtrend: the OBV 50 line (part 4), the OBV ROC pane (part 5) and WOO X Pro 2's swing trend (part 6): a read on the
  history up to a bar equals the pane on the whole history at that bar; 1,500 bars read the same last values as a longer
  history; the swing rule on every combination of its three votes (the owners' cases: chop sideways + supertrend down +
  the sky line = long);
- 바이비트 봇 (paperbot/mixchop.py, rule "obv50") and the friend bot's 15m form (rules "roc50", "obv50" on 15m bars, the
  swing trend): the rules enter only on their side of 50 with their trend, the stop is ATR14 of the signal bar x 3; a 15m
  close in the bot's loop; the morning replay (paperbot/mixcheck.py) recomputes 15m closes. Later on 10-30 the owners
  put the friend bot (WOO X Pro 2) on the 바이비트 봇's first rule instead ("역추세 안되겠다 … 바이비트 원래 obv 매매법만
  적용", 30m bars): 친구 30분 봇, rule "obv" with the four votes; the 15m form stays a config away;
- 레인지 봇 (paperbot/rangebot.py): the ROC entry on 30m closes (the 30m four-vote trend, the purple line's side of 50,
  ATR x 3, the liquidation room, one position with the range entries), the ladder net ROE 10 -> 8 then 5 instead of the
  fixed +10 %; the read equals friendtrend's on the same 5m history; a restart keeps a queued ROC entry; the deploy
  config, its words on the site; the WOO X Pro executor template (the paper's stop distance, its own ladder)."""
import itertools
import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from paperbot import combo as C
from paperbot import friendtrend as FT
from paperbot import mixcheck as MC
from paperbot import mixchop as M
from paperbot import rangebot as RB
from paperbot.executor import ExecConfig

sys.path.insert(0, os.path.dirname(__file__))
import test_rangebot as TR  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
MIN, FIVE, HOUR = 60_000, 300_000, 3_600_000


def walk(n, seed=1, px=100.0, vol=0.004):
    rng = np.random.default_rng(seed)
    c = px * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, vol, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, vol, n))
    return o, h, lo, c, rng.uniform(100, 1000, n)


def frame(n, tf_ms=M.MIN30, seed=1, end_ms=T0, **kw):
    o, h, lo, c, v = walk(n, seed, **kw)
    t = end_ms - tf_ms * np.arange(n, 0, -1)
    return pd.DataFrame({"open_ms": t.astype(np.int64), "open": o, "high": h, "low": lo, "close": c, "volume": v})


# ====================================================================== friendtrend parts 4 - 6
def test_the_roc_read_on_a_prefix_is_the_pane_at_that_bar():
    o, h, lo, c, v = walk(900, seed=5)
    P = FT.roc_pane(h, lo, c, v)
    cs, dark, osc = P["cs"], P["dark"], P["osc"]
    turns = [i for i in range(300, len(c)) if cs[i] == cs[i - 1] and dark[i] and not dark[i - 1]]
    assert len(turns) >= 10 and {int(cs[i]) for i in turns} == {1, -1}
    sides = set()
    for i in turns:
        st = FT.roc_state(h[:i + 1], lo[:i + 1], c[:i + 1], v[:i + 1])
        assert st["turn"] == cs[i] and st["osc"] == pytest.approx(round(float(osc[i]), 2))
        want = 1 if cs[i] > 0 and osc[i] < 50 else (-1 if cs[i] < 0 and osc[i] > 50 else 0)
        assert st["side"] == want
        sides.add(want)
    assert sides == {1, -1, 0}
    # a bar that is not a turn: no side whatever the line
    quiet = next(i for i in range(300, len(c)) if not (cs[i] == cs[i - 1] and dark[i] and not dark[i - 1]))
    assert FT.roc_state(h[:quiet + 1], lo[:quiet + 1], c[:quiet + 1], v[:quiet + 1])["side"] == 0
    # the purple line is drawn 0 ~ 100 (50 + 50 tanh)
    fin = osc[np.isfinite(osc)]
    assert fin.min() >= 0 and fin.max() <= 100


def test_the_obv50_read_on_a_prefix_is_the_obv_turn_with_its_line():
    o, h, lo, c, v = walk(900, seed=9)
    P = FT.obv_pane(h, lo, c, v)
    cs, dark = P["cs"], P["dark"]
    d50 = FT.to50(P["line"], M.ema(P["line"], FT.OBV50_BASE), FT.OBV50_NORM, FT.OBV50_SENS)
    turns = [i for i in range(300, len(c)) if cs[i] == cs[i - 1] != 0 and dark[i] and not dark[i - 1]]
    assert len(turns) >= 10
    sides = set()
    for i in turns:
        st = FT.obv50_state(h[:i + 1], lo[:i + 1], c[:i + 1], v[:i + 1])
        assert st["turn"] == cs[i] == FT.obv_turn(h[:i + 1], lo[:i + 1], c[:i + 1], v[:i + 1])
        want = 1 if cs[i] > 0 and d50[i] < 50 else (-1 if cs[i] < 0 and d50[i] > 50 else 0)
        assert st["side"] == want and st["d50"] == pytest.approx(round(float(d50[i]), 2))
        sides.add(want)
    assert sides >= {1, -1}


def test_fifteen_hundred_bars_read_the_same_roc_and_obv50():
    o, h, lo, c, v = walk(4000, seed=13)
    cut = slice(-1500, None)
    P, Q = FT.roc_pane(h, lo, c, v), FT.roc_pane(h[cut], lo[cut], c[cut], v[cut])
    assert (P["cs"][-300:] == Q["cs"][-300:]).all() and (P["dark"][-300:] == Q["dark"][-300:]).all()
    assert np.allclose(P["osc"][-300:], Q["osc"][-300:], atol=1e-6)
    a, b = FT.obv50_state(h, lo, c, v), FT.obv50_state(h[cut], lo[cut], c[cut], v[cut])
    assert a == b


def test_the_swing_trend_on_every_combination():
    for line, chop, st in itertools.product((1, -1), (1, -1, 0), (1, -1, 0)):
        t = {"line": line, "chop": chop, "st": st, "ema": 1}
        ok = chop in (0, -line) and st in (0, -line) and 0 in (chop, st)
        assert FT.swing_side(t) == (line if ok else 0), (line, chop, st)
    # the owners' cases (10-30): chop sideways + supertrend down + the sky line -> long ("2번은 가능"); both sideways ->
    # its side; one with the line (two of the same trend) -> no entry; both against -> no entry
    assert FT.swing_side({"line": 1, "chop": 0, "st": -1}) == 1
    assert FT.swing_side({"line": -1, "chop": 0, "st": 0}) == -1
    assert FT.swing_side({"line": 1, "chop": 1, "st": 0}) == 0 and FT.swing_side({"line": 1, "chop": -1, "st": -1}) == 0
    assert FT.swing_words({"line": 1, "chop": 0, "st": -1}) == "롱 가능 (하늘·보라 선 상승 · 찹존 횡보 · 슈퍼트렌드 하락)"
    assert FT.swing_words({"line": 1, "chop": 1, "st": 0}).startswith("진입 금지 (")


# ====================================================================== the two mix bots' rules
def _coin(lev=40, sl=3.0, sym="SOLUSDT"):
    return M.Coin(sym, 0.0, sl, 100.0, lev)


def _votes(t=None, line=1, ema=1, chop=0, st=-1):
    return {"trend": t if t is not None else int(FT.trend_of([line], [ema], [chop], [st])[0]), "line": line, "ema": ema,
            "chop": chop, "st": st, "ema_rsi": 55.0, "chop_zone": 2 * chop}


def test_roc50_on_15m_bars_with_the_swing_trend(monkeypatch):
    b15 = frame(400, tf_ms=M.MIN15, vol=0.002)
    ce = T0
    co = _coin()

    def run(rs, votes, trend="swing"):
        monkeypatch.setattr(FT, "roc_state", lambda *a: rs)
        monkeypatch.setattr(FT, "last_trend", lambda *a: votes)
        return M.evaluate_friend("roc50", co, b15, ce, M.MIN15, trend)
    up = {"turn": 1, "cs": 1, "dark": True, "osc": 38.5, "side": 1}
    ev = run(up, _votes(line=1, chop=0, st=-1))            # the sky line up, chop sideways, supertrend down: long
    assert ev["side"] == 1 and ev["tf"] == "15분" and ev["trend_mode"] == "swing" and ev["trend"] == 1
    assert ev["roc"] == 38.5 and ev["roc_turn"] == 1 and ev["votes"]["st"] == -1
    a = float(M.atr(b15.high, b15.low, b15.close, 14)[-1])
    assert ev["stop_dist"] == pytest.approx(3 * a)
    ev = run(up, _votes(line=1, chop=1, st=0))              # two of the same trend: no entry
    assert ev["side"] == 0 and ev["why"] == "추세 진입 금지 (하늘·보라 선 상승 · 찹존 상승 · 슈퍼트렌드 횡보)"
    ev = run(up, _votes(line=-1, chop=0, st=0))
    assert ev["side"] == 0 and ev["why"].startswith("추세 숏 가능 (") and ev["why"].endswith(": 신호 롱와 반대")
    ev = run({**up, "osc": 61.0, "side": 0}, _votes())     # a green turn over 50: no signal
    assert ev["side"] == 0 and ev["why"] == "ROC 막대 진한 초록인데 보라 선이 50선 위(ROC 61.0)"
    ev = run({"turn": 0, "cs": 1, "dark": False, "osc": 40.0, "side": 0}, _votes())
    assert ev["why"] == "ROC 막대 연한색→진한색 없음"
    # the closing 15m bar must be there
    assert M.evaluate_friend("roc50", co, b15, ce + M.MIN15, M.MIN15, "swing")["why"] == "15분봉이 아직 없음"


def test_obv50_with_the_four_votes_on_30m(monkeypatch):
    b30 = frame(400, vol=0.002)
    co = _coin(sym="BTCUSDT")
    monkeypatch.setattr(FT, "obv50_state", lambda *a: {"turn": -1, "cs": -1, "dark": True, "d50": 63.2, "side": -1})
    monkeypatch.setattr(FT, "last_trend", lambda *a: _votes(t=-1, line=-1, ema=-1, chop=-1, st=0))
    ev = M.evaluate_friend("obv50", co, b30, T0)
    assert ev["side"] == -1 and ev["obv50"] == 63.2 and "tf" not in ev and "trend_mode" not in ev
    monkeypatch.setattr(FT, "obv50_state", lambda *a: {"turn": -1, "cs": -1, "dark": True, "d50": 40.0, "side": 0})
    ev = M.evaluate_friend("obv50", co, b30, T0)
    assert ev["side"] == 0 and ev["why"] == "OBV 진한 빨강인데 50선 아래(OBV 40.0)"


def test_the_friend_deploy_configs_and_wrong_ones(tmp_path):
    for name, mode in (("mixchop.live.json", "mainnet"), ("mixchop.paper.json", "paper")):
        cfg = M.load_config(str(DEPLOY / name))
        assert cfg.mode == mode and cfg.exchange == "wooxpro" and cfg.name == "친구 30분 봇"
        # owners 10-30, later: the 바이비트 봇's first rule (OBV light -> dark, the four votes); 10-31: on 15m bars with
        # 추세 3개 일치 added (tests/test_rules1031.py); 10-31 evening: back on 30m bars, the OBV turn with the AC bar
        # (tests/test_rules1031b.py)
        assert (cfg.tf, cfg.trend, cfg.rules, cfg.stop_atr) == ("30m", "four", ("obvac",), 3.0)
        assert cfg.tf_ms == M.MIN30 and cfg.tf_ko == "30분"
        assert {c.symbol: c.leverage for c in cfg.coins} == {"SOLUSDT": 40, "ETHUSDT": 40, "XRPUSDT": 40, "BCHUSDT": 40,
                                                            "ZECUSDT": 20, "DOGEUSDT": 40}
        assert all(c.sl_atr == 3.0 for c in cfg.coins)
        assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0} and cfg.margin_frac == 0.4
    base = json.loads((DEPLOY / "mixchop.live.json").read_text(encoding="utf-8"))
    bad = {"tf": ({"tf": "5m"}, "tf"), "trend": ({"trend": "two"}, "trend"),
           "mix on 15m": ({"rules": ["mix"], "tf": "15m"}, "30m")}
    for what, (over, words) in bad.items():
        p = tmp_path / f"{what}.json"
        p.write_text(json.dumps({**base, **over}), encoding="utf-8")
        with pytest.raises(M.MixError, match=words):
            M.load_config(str(p))


def test_a_15m_close_in_the_bots_loop(tmp_path, monkeypatch):
    d = json.loads((DEPLOY / "mixchop.paper.json").read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "state.json"), log=str(tmp_path / "log.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN.STOP"), telegram=False, start_equity=100,
             tf="15m", trend="swing", rules=["roc50", "obv50"], name="친구 15분 봇")        # the 15m form
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    cfg = M.load_config(str(p))
    ce = T0 + M.MIN15                                      # a quarter that is not a 30m close
    rows = [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in ce - M.MIN15 * np.arange(400, -1, -1)]   # with the bar opening now
    asked, calls = [], []

    def fetch(sym, tf, n):
        asked.append(tf)
        return rows

    def fake_eval(rule, co, b, close_ms, tf_ms=M.MIN30, trend="four"):
        calls.append((rule, co.symbol, tf_ms, trend, int(b.open_ms.iloc[-1]) + tf_ms == close_ms))
        side = 1 if (rule, co.symbol) == ("obv50", "ETHUSDT") else 0
        return {"symbol": co.symbol, "close_ms": close_ms, "side": side, "why": "" if side else "없음", "rule": rule,
                "close": 10.0, "stop_dist": 0.1, "stop_pct": 1.0, "trend": side, "obv50": 41.0, "turn": side,
                "votes": {"line": 1, "ema": 1, "chop": 0, "st": -1}, "trend_mode": "swing", "tf": "15분"}
    monkeypatch.setattr(M, "evaluate_friend", fake_eval)
    msgs = []
    bot = M.Bot(cfg, M.PaperBroker(100.0, cfg.taker_fee), fetch, lambda: ce + 5_000, notify=lambda lv, t: msgs.append(t),
                sleep=lambda s: None)
    bot.on_close(ce)
    assert set(asked) == {"15m"}                           # no 1h bars for the friend's rules
    assert calls[:2] == [("roc50", "SOLUSDT", M.MIN15, "swing", True), ("obv50", "SOLUSDT", M.MIN15, "swing", True)]
    assert bot.pos is not None and bot.pos.symbol == "ETHUSDT" and bot.pos.side == 1 and bot.last_close_ms == ce
    assert bot.board["ETHUSDT"]["rules"]["obv50"]["side"] == 1 and bot.board["SOLUSDT"]["tf"] == "15분"


def test_the_morning_replay_recomputes_15m_closes():
    cfg = M.load_config(str(DEPLOY / "mixchop.paper.json"))
    cfg.coins = cfg.coins[:1]                              # SOL
    cfg.tf, cfg.trend, cfg.rules = "15m", "swing", ("roc50", "obv50")      # the 15m form
    rng = np.random.default_rng(31)
    n = 2000
    day0 = T0 - 24 * HOUR
    t15 = T0 - M.MIN15 * np.arange(n, 0, -1)
    c = 150 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    vol = rng.uniform(100, 1000, n)
    rows = [[int(t15[i]), o[i], hi[i], lo[i], c[i], vol[i]] for i in range(n)]

    def klines(symbol, tf, start, limit):
        assert tf == "15m"
        return [r for r in rows if r[0] >= start][:limit]
    log = []
    co = cfg.coins[0]
    for ce in range(day0 + M.MIN15, T0 + 1, M.MIN15):     # what the bot logged: its own judge on 15m bars
        b = M.bars_frame(rows, M.MIN15, ce).tail(M.BARS - 1).reset_index(drop=True)
        for rule in cfg.rules:
            ev = M.Bot.judge(rule, co, b, b, ce, M.MIN15, "swing")
            if ev.get("turn") or ev.get("roc_turn") or ev["side"]:
                log.append({"ts": ce + 5_000, "kind": "signal", **ev})
    assert {r["rule"] for r in log} == {"roc50", "obv50"}
    rp = MC.signal_replay(cfg, day0, T0, log, klines, obs=[[T0 + 3 * MIN, T0, None]], st_last=T0)
    assert rp["state"] == "ok" and rp["different"] == [] and rp["rules"] == ["roc50", "obv50"]
    assert rp["closes"] == 96 and rp["tf_ko"] == "15분"
    assert rp["roc_turns"] == sum(1 for r in log if r["rule"] == "roc50" and r.get("roc_turn"))
    assert rp["turns"] == sum(1 for r in log if r["rule"] == "obv50" and r.get("turn"))
    line = MC.replay_lines(rp)[0]
    assert f"ROC 막대 연한→진한 {rp['roc_turns']}번" in line and "15분봉 96개" in line
    # a turn the bot did not log is found again
    gone = next(r for r in log if r["rule"] == "roc50")
    rp2 = MC.signal_replay(cfg, day0, T0, [r for r in log if r is not gone], klines, obs=[], st_last=T0)
    assert any(x["close_ms"] == gone["close_ms"] and x["rule"] == "roc50" for x in rp2["missed"] + rp2["unsure"])


# ====================================================================== 레인지 봇: the ROC entry and the ladder
H = TR.H                                         # 2026-10-05 10:00 KST (Monday): the tests' 1h close
B = TR.T0 + 30 * MIN                             # a 30m close before it


def _roc(side=1, osc=None, trend=None, atr=100.0, close=60000.0, **votes):
    t = trend if trend is not None else side
    return {"roc": {"turn": side, "cs": side or 1, "dark": True, "osc": osc if osc is not None else (40.0 if side >= 0 else 60.0),
                    "side": side},
            "trend": TR.friend_votes(t, **votes), "atr": atr, "close": close}


def _r1030():
    """The 레인지 봇 config of 10-30 (the range filter member and the ROC entry; 10-31 replaced both: test_rules1031.py)."""
    d = json.loads((DEPLOY / "combo.range.json").read_text(encoding="utf-8"))
    rng = {k: v for k, v in d["range"].items() if k not in ("ema3_tf", "ema3_stop_atr")}
    return {"members": [{"pick": TR.MEMBER}], "range": {**rng, "roc_tf": "30m", "roc_stop_atr": 3}}


R1030 = _r1030()


class RocWorld(TR.World):
    """The range test world on the deploy config (owners 10-30: the ladder, the ROC entry); ``roc``: {(symbol, 30m
    close): read}, every other coin and close a read without a turn."""

    def __init__(self, tmp_path, **kw):
        self.roc: dict = {}
        self.reads: list = []
        super().__init__(tmp_path, deploy=True, **{**R1030, **kw})

    def open(self):
        super().open()

        def read(sym, bc):
            self.reads.append((sym, bc))
            return self.roc.get((sym, bc), _roc(0, osc=50.0, trend=1))
        self.run.roc_read = read


def _go(w, upto):
    w.now = TR.T0 + 5_000
    w.run.poll()
    w.to(TR.T0, upto)


def test_the_deploy_config_takes_the_ladder_and_the_roc_entry(tmp_path, capsys):
    cfg = TR.rcfg(tmp_path, deploy=True, **R1030)       # the deploy config as of 10-30 (10-31: test_rules1031.py)
    assert cfg.problems() == [] and cfg.take_profit_roe is None
    s = C.settings_of(cfg)
    assert s.tp_mode == "ladder" and (s.ladder_first_lock, s.ladder_trigger_gap, s.ladder_step) == (0.08, 0.02, 0.05)
    assert C.take_profit_text(cfg) == "계단 익절 순ROE 10%에서 8% 잠금, 이후 5%씩"
    rules = RB.RangeRules.from_dict(cfg.range)
    assert (rules.roc_tf, rules.roc_stop_atr, rules.friend_tf) == ("30m", 3, "1h")
    words = rules.describe()
    assert words[-2].startswith("ROC 진입(30분봉): 친구 추세지표 30분봉(네 표)이 상승일 때 ROC 막대가 연한 초록→진한 초록이고 "
                                "보라선이 50 아래면 롱") and "손절 30분 ATR(14) × 3, 그 거리가 (1/배수 - 0.5%) 안쪽일 때만" in words[-2]
    f30 = tmp_path / "range1030.json"
    f30.write_text(json.dumps({**json.loads((DEPLOY / "combo.range.json").read_text(encoding="utf-8")), **R1030}), encoding="utf-8")
    assert C.cmd_check(Namespace(config=str(f30))) == 0
    out = capsys.readouterr().out
    assert "계단 익절 순ROE 10%에서 8% 잠금, 이후 5%씩" in out and "- ROC 진입(30분봉):" in out and out.strip().endswith("준비됨")
    text = C.start_text(cfg, C.resolve_members(cfg.members, cfg.picks_file), 1000.0)
    assert "ROC 진입(30분봉)" in text and "계단 익절" in text
    # the site says the same words (dash/more/livebots.range_words, held to describe())
    from paperbot.dash.more import livebots as L
    assert [x["ko"] for x in L.range_words(json.loads(f30.read_text()))] == words
    # wrong ROC numbers
    for over, want in (({"roc_tf": "15m"}, "range.roc_tf"), ({"roc_stop_atr": 0.2}, "range.roc_stop_atr")):
        bad = TR.rcfg(tmp_path, deploy=True, members=R1030["members"], range={**cfg.range, **over})
        assert any(want in p for p in bad.problems()), over
    # the 10-26 form still loads: the fixed take-profit, no ladder
    assert TR.rcfg(tmp_path).problems() == [] and C.settings_of(TR.rcfg(tmp_path)).tp_mode == "fixed"


def test_a_roc_turn_with_its_trend_enters_at_the_next_open_with_an_atr_stop(tmp_path):
    w = RocWorld(tmp_path)
    w.roc[("BTCUSDT", B)] = _roc(1, osc=38.2, atr=100.0)
    _go(w, B + MIN)                                        # minute B: the entry at its open
    assert {s for s, bc in w.reads if bc == B} == set(TR.SYMS) and all(bc % (30 * MIN) == 0 for _s, bc in w.reads)
    bc, sym, st, d = w.rows()[0]
    assert (bc, sym, st) == (B, "BTCUSDT", "SUBMITTED")
    row = w.store.conn.execute("SELECT timeframe, strategy FROM signal_log WHERE bar_close = ?", (B,)).fetchone()
    assert row == ("30m", "ROC50-30m")
    p = w.engine().position
    assert p is not None and p.symbol == "BTCUSDT" and p.side == 1 and p.entry_time == B and p.leverage == 40
    assert p.signal.meta["stop_dist"] == pytest.approx(300.0)                 # ATR 100 x 3 from the reference price
    assert p.entry_price - p.stop_price == pytest.approx(300.0 + 60000.0 * 0.0002)   # (the fill has the paper's slippage)
    assert p.signal.meta["stop_rule"] == "3 x ATR" and p.signal.meta["range"]["roc"] is True
    assert p.tp_price != p.tp_price                         # no fixed take-profit: the ladder
    ent = [m for _l, m in w.note.messages if "진입" in m and "ROC 50선" in m]
    assert ent and "ROC 30분봉 10-05 09:30 마감: 연한 초록→진한 초록, 보라선 38.2(50 아래)" in ent[-1]
    assert "친구 추세 30분 상승 (" in ent[-1] and "손절 30분 ATR(100) × 3" in ent[-1]
    # the ladder: net ROE 10 % -> the stop locks 8 %
    e = p.entry_price
    w.step(B + MIN, high={"BTCUSDT": e * 1.0045})
    assert w.engine().position.lock_roe == pytest.approx(0.08)
    assert w.engine().position.stop_price > e


def test_a_roc_turn_against_its_trend_or_too_wild_is_filtered(tmp_path):
    w = RocWorld(tmp_path)
    w.roc[("ETHUSDT", B)] = _roc(-1, osc=64.0, trend=1)
    w.roc[("BTCUSDT", B)] = _roc(1, trend=0, chop=0, st=0)
    w.roc[("SOLUSDT", B + 30 * MIN)] = _roc(1, atr=1.5, close=150.0)        # 3 x 1.5 = 3 % > 1/30 - 0.5 % = 2.83 %
    _go(w, H + MIN)
    rows = {(sym, bc): (st, d["why"]) for bc, sym, st, d in w.rows()}
    st, why = rows[("ETHUSDT", B)]
    assert st == "FILTERED" and why.startswith("추세 확인: 친구 추세지표 30분 상승 (") and why.endswith("(신호 숏와 반대)")
    st, why = rows[("BTCUSDT", B)]
    assert st == "FILTERED" and why.startswith("추세 확인: 친구 추세지표 30분 진입 금지 (")
    st, why = rows[("SOLUSDT", B + 30 * MIN)]
    assert st == "FILTERED" and why == "강제청산 여유 부족: 손절 30분 ATR × 3 = 3.00% > 2.83%(30배)"
    assert w.engine().position is None
    from paperbot.dash.more import livebots as L
    assert L.why_cat("FILTERED", rows[("ETHUSDT", B)][1])[0] == "range_friend"
    assert L.why_cat("FILTERED", rows[("SOLUSDT", B + 30 * MIN)][1])[0] == "range_liq"


def test_one_position_with_the_range_entries(tmp_path):
    # a range signal waiting for its pullback: the ROC turn of the same close and the next one are filtered
    w = RocWorld(tmp_path)
    w.custom.plan[H] = [("BTCUSDT", 1, TR.ATR)]
    w.roc[("ETHUSDT", H)] = _roc(1, close=2500.0, atr=5.0)
    w.roc[("SOLUSDT", H + 30 * MIN)] = _roc(1, close=150.0, atr=0.3)
    _go(w, H + 31 * MIN)
    rows = {(sym, bc): (st, d.get("why", "")) for bc, sym, st, d in w.rows()}
    assert rows[("BTCUSDT", H)][0] == "WAITING"
    assert rows[("ETHUSDT", H)] == ("FILTERED", "한 신호씩: BTC 롱 되돌림 기다리는 중(10-05 11:00까지)")
    assert rows[("SOLUSDT", H + 30 * MIN)][0] == "FILTERED" and rows[("SOLUSDT", H + 30 * MIN)][1].startswith("한 신호씩: BTC 롱")
    # a ROC position: the range signal of the next hour is filtered
    w2 = RocWorld(tmp_path / "b")
    w2.roc[("BTCUSDT", B)] = _roc(1)
    w2.custom.plan[H] = [("ETHUSDT", 1, 20.0)]
    _go(w2, H + MIN)
    assert w2.engine().position.symbol == "BTCUSDT"
    rows = {(sym, bc): (st, d.get("why", "")) for bc, sym, st, d in w2.rows()}
    assert rows[("ETHUSDT", H)] == ("FILTERED", "한 신호씩: BTC 롱 포지션 들고 있음")


def test_a_restart_keeps_a_queued_roc_entry(tmp_path):
    w = RocWorld(tmp_path)
    w.roc[("DOGEUSDT", B)] = _roc(-1, osc=70.0, close=0.2, atr=0.0005)
    _go(w, B)                                              # the turn is read after minute B - 1: queued for minute B
    assert w.rows()[0][2] == "SUBMITTED" and w.engine().position is None
    w.restart()
    assert "ROC50-30m" in w.run.by_label and [q.bar_close for q in w.run.queue] == [B]
    w.step(B)
    p = w.engine().position
    assert p is not None and p.symbol == "DOGEUSDT" and p.side == -1


def test_no_roc_read_on_a_catch_up_and_none_without_roc_tf(tmp_path):
    w = RocWorld(tmp_path)
    w.now = B + 10 * MIN                                   # long after the close: late anyway
    w.run._roc_signals(B)
    assert w.reads == []
    w2 = TR.World(tmp_path / "b")                         # the 10-29 config: no ROC member, no reads
    assert w2.run.roc is None and "ROC50-30m" not in w2.run.by_label


def test_the_roc_read_equals_friendtrend_on_the_same_history(tmp_path):
    from paperbot import sweepsig
    from paperbot.dssig import frame as dsframe
    lib = sweepsig.lib()
    members = C.resolve_members([{"pick": TR.MEMBER}])
    custom = C.CustomSignals(members, ["BTCUSDT"], lib=lib)
    rng = np.random.default_rng(17)
    n = 1700 * 6
    ts0 = TR.T0 - n * FIVE
    c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.0015, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.0008, np.minimum(o, c) * 0.9992
    vol = rng.uniform(1.0, 9.0, n)
    custom.bootstrap("BTCUSDT", [(ts0 + k * FIVE, o[k], hi[k], lo[k], c[k], vol[k]) for k in range(n)])
    w = TR.World(tmp_path, deploy=True, **R1030)
    run = RB.RangeRunner(w.cfg, w.members, w.book, w.store, w.note, custom, now_ms=lambda: TR.T0, prices=lambda: {})
    df = dsframe(np.array([ts0 + k * FIVE for k in range(n)]), o, hi, lo, c, vol, tf="30m", lib=lib).tail(RB.ROC_BARS)
    a = {k: df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")}
    got = run.roc_read("BTCUSDT", TR.T0)
    assert got["roc"] == FT.roc_state(a["high"], a["low"], a["close"], a["volume"])
    assert got["trend"] == FT.last_trend(a["open"], a["high"], a["low"], a["close"], a["volume"])
    assert got["atr"] == pytest.approx(float(M.atr(a["high"], a["low"], a["close"], 14)[-1]))
    assert got["close"] == pytest.approx(a["close"][-1])
    with pytest.raises(C.ComboError, match="30분봉이 없음"):
        run.roc_read("BTCUSDT", TR.T0 + 5 * MIN)          # not a 30m close
    with pytest.raises(C.ComboError, match="ROC에 1800개 필요"):
        run.roc_read("BTCUSDT", ts0 + 200 * 30 * MIN)


def test_the_live_site_state_has_each_coins_roc_read(tmp_path):
    w = RocWorld(tmp_path)
    w.roc[("BTCUSDT", B)] = _roc(1, trend=-1)
    _go(w, B + 2 * MIN)
    _ts, snap = w.store.get_state(RB.STATE_RANGE)
    assert set(snap["roc"]) == set(TR.SYMS)
    assert snap["roc"]["BTCUSDT"] == {"at": B, "turn": 1, "cs": 1, "dark": True, "osc": 40.0, "side": 1, "trend": -1}
    assert any(x.startswith("ROC 진입(30분봉)") for x in snap["rules"])


def test_the_wooxpro_executor_template_follows_the_papers_stop_with_its_own_ladder():
    d = json.loads((DEPLOY / "executor.live-wooxpro-range.json").read_text(encoding="utf-8"))
    assert d["stop_from"] == "ratio" and not {"stop_roe", "stop_net", "stop_scale"} & set(d)
    assert (d["ladder_from"], d["ladder_basis"], d["take_profit_roe"]) == ("own", "net", None)
    assert d["ladder"] == {"first_lock": 0.08, "trigger_gap": 0.02, "step": 0.05}
    assert d["paper_db"] == "/var/lib/paperbot/combo/range.db" and d["leverage_by_symbol"] == {"BTCUSDT": 40, "*": 30}
    assert ExecConfig.from_dict(d).problems() == []
    # the same ladder as the paper bot's
    r = json.loads((DEPLOY / "combo.range.json").read_text(encoding="utf-8"))
    assert r["ladder"] == d["ladder"] and r["take_profit_roe"] is None


def test_the_friend_trend_board_shows_the_obv50_rule():
    from paperbot.dash.more import liveftrend as FTR
    ev = {"symbol": "BTCUSDT", "close_ms": T0, "side": 1, "why": "", "rule": "obv50", "close": 60000.0, "turn": 1,
          "obv_cs": 1, "obv_dark": True, "obv50": 41.3, "trend": 1, "votes": {"line": 1, "ema": 1, "chop": 1, "st": 0}}
    row = FTR.m30_row(M.board_row([ev], T0), T0 + MIN)
    assert row["state"] == "ok" and row["obv50"] == 41.3 and row["stoch"] is None
    assert row["rules"]["obv50"] == {"side": 1, "why": "", "ko": "OBV 50선"} and row["obv"]["ko"] == "진한 초록"
    assert any(x.startswith("OBV 50선(바이비트 봇, 10-30 ~ 10-31)") for x in FTR.RULES_KO)    # 10-31 evening: AC instead


def test_the_range_screen_shows_a_roc_position_and_its_ladder(tmp_path, monkeypatch):
    """The 레인지 봇 screen (screens/livebots-range.js) with a ROC position on the ladder: the entry signal's 30m bar instead
    of the pullback, the ladder and its lock instead of a fixed take-profit price."""
    from paperbot.dash.more import livebots as L
    from paperbot.dash.more import liverange as R
    from tests import range_world as RW
    from tests.test_dash_live_range import BAD, SCREENS, _node
    p = RW.build(str(tmp_path / "w"))
    more = RW.more(str(tmp_path / "w"))
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    L._cache.clear()
    d = json.loads(json.dumps(R.build(p, more, RW.NOW), default=str))
    assert d["position"] is not None
    d["plan"]["ladder"] = R.ladder_of({"first_lock": 0.08, "trigger_gap": 0.02, "step": 0.05})
    d["position"].update(tp=None, tp_move=None, lock_roe=0.08,
                         range={"roc": True, "side": d["position"]["side"], "t0": RW.NOW - 40 * MIN, "osc": 38.2, "k": 3.0,
                                "atr": 1.2, "close": 100.0})
    out = _node(tmp_path, f"""
    const X = await import('file://{SCREENS}/livebots-range.js');
    const ctx = {{params: {{query: {{}}}}, alive: () => true, track() {{}}, listen() {{}}, on() {{}}, watch() {{}}, href: (n) => '#/' + n,
      every() {{}}, api: async () => JSON.parse(JSON.stringify(D_d))}};
    const v = X.rangeView(ctx); await tick(); await tick();
    console.log(JSON.stringify({{a: texts(v.el)}}));""", d=d)
    a = out["a"]
    assert "계단 순ROE 10%에서 8% 잠금, 그 뒤 5%씩 · 지금 순ROE +8% 잠금" in a
    assert "진입 신호" in a and "ROC 30분봉" in a and "보라선 38.2 · 손절 30분 ATR × 3 (되돌림 안 기다림)" in a
    assert not BAD.search(a), BAD.search(a)



def test_the_friend_bot_on_the_bybit_bots_first_rule(tmp_path, monkeypatch):
    """Owners 10-30, later: WOO X Pro 2 trades the 바이비트 봇's first rule (OBV light -> dark with the four-vote trend,
    30m bars), its coins, leverage, stop, ladder and margin kept; the check and the start words say so."""
    cfg = M.load_config(str(DEPLOY / "mixchop.live.json"))
    cfg.tf, cfg.rules = "30m", ("obv",)                  # (10-30's form; 10-31 put it on 15m with 추세 3개 일치)
    b30 = frame(400, vol=0.002)
    co = cfg.coins[0]
    monkeypatch.setattr(FT, "obv_state", lambda *a: {"turn": 1, "cs": 1, "dark": True})
    monkeypatch.setattr(FT, "last_trend", lambda *a: _votes(t=1, line=1, ema=1, chop=0, st=1))
    ev = M.Bot.judge("obv", co, b30, b30.iloc[0:0], T0, cfg.tf_ms, cfg.trend)
    assert ev["side"] == 1 and ev["rule"] == "obv" and "tf" not in ev and "trend_mode" not in ev
    # the swing reading would have refused it (two of the same trend): the four votes take it
    assert FT.swing_side(_votes(t=1, line=1, ema=1, chop=0, st=1)) == 0
    monkeypatch.setattr(FT, "last_trend", lambda *a: _votes(t=0, line=1, ema=1, chop=0, st=0))
    assert M.Bot.judge("obv", co, b30, b30.iloc[0:0], T0, cfg.tf_ms, cfg.trend)["side"] == 0
    assert "OBV 진한색" in M.plan_words(cfg) and "ROC" not in M.plan_words(cfg)


def test_the_site_explains_a_roc_entry_and_reads_the_ladder():
    """왜 들어갔나 (livewhy.range_checks) for a ROC entry; 목표 연구's 손절 해부 (livegoalres.range_stops) with the ladder;
    the 레인지 봇 screen's ROC chips and each signal's entry kind (liverange)."""
    from paperbot.dash.more import livegoalres as G
    from paperbot.dash.more import liverange as R
    from paperbot.dash.more import livewhy as W
    cfg = json.loads((DEPLOY / "combo.range.json").read_text(encoding="utf-8"))
    info = {"roc": True, "side": 1, "close": 60000.0, "atr": 100.0, "k": 3.0, "t0": TR.T0 + 30 * MIN, "osc": 38.2, "turn": 1,
            "friend": TR.friend_votes(1)}
    out = {x["id"]: x for x in W.range_checks(cfg, TR.T0 + 31 * MIN, 1, "BTCUSDT", 40, info, 0.0014)}
    assert out["friend"]["ok"] is True and out["friend"]["ko"].startswith("추세 확인: 친구 추세지표 30분 상승 (")
    assert out["roc"]["ok"] is True and "보라선 38.2 (50 아래이어야 함)" in out["roc"]["ko"]
    assert out["liq"]["ok"] is True and out["liq"]["ko"] == "강제청산 여유: 손절 30분 ATR × 3 = 0.50% → 2.00% 안쪽 (40배)"
    assert out["entry"]["ko"].startswith("되돌림 안 기다림") and "pull" not in out
    assert out["tp"]["ko"] == "익절은 계단 순ROE 10%에서 8% 잠금, 그 뒤 5%씩 (고정 익절 없음)"
    # the 10-26 config still says its fixed take-profit; a range entry still shows its pullback
    old = {**cfg, "ladder": None, "take_profit_roe": 0.1}
    pull = {"side": 1, "close": 100.0, "atr": 1.0, "k": 0.2, "level": 99.8, "t0": TR.T0, "until": TR.T0 + HOUR,
            "touch": TR.T0 + 10 * MIN, "entry_t": TR.T0 + 15 * MIN, "friend": TR.friend_votes(1)}
    o2 = {x["id"]: x for x in W.range_checks(old, TR.T0 + 15 * MIN, 1, "SOLUSDT", 30, pull, 0.0014)}
    assert o2["tp"]["ko"].startswith("익절은 순ROE +10% 고정") and o2["pull"]["ok"] is True
    assert o2["friend"]["ko"].startswith("추세 확인: 친구 추세지표 1시간 상승")
    # 손절 해부 reads the ladder's first lock (net ROE 10 %) as the take-profit side
    it = G.range_stops([], cfg, 0.0014, None, TR.T0)
    assert it["state"] == "ok" and it["lead_ko"] == "손절로 끝난 거래가 아직 없어요"     # (not 'no take-profit level')
    it2 = G.range_stops([], {**cfg, "ladder": None, "take_profit_roe": None}, 0.0014, None, TR.T0)
    assert it2["state"] == "missing" and it2["lead_ko"] == "설정에 고정 익절도 계단도 없어 익절 자리를 몰라요"
    # the screen: each coin's ROC read, and which entry a signal row is
    snap = {"range": (TR.T0, {"supertrend": {}, "friend": {}, "busy": "", "rules": [],
                              "roc": {"BTCUSDT": {"at": B, "turn": 1, "cs": 1, "dark": True, "osc": 38.2, "side": 1, "trend": 1},
                                      "ETHUSDT": {"at": B, "turn": 0, "cs": -1, "dark": False, "osc": 55.0, "side": 0, "trend": 0},
                                      "SOLUSDT": {"at": B, "error": "SOL 5분봉 기록 없음"}}})}
    sv = R.supertrend_of(snap, TR.T0)
    assert [(x["coin"], x["side"], x.get("ko")) for x in sv["roc"]] == [("BTC", 1, "롱 신호"), ("ETH", 0, "빨강 연함"),
                                                                      ("SOL", None, None)]
    assert sv["roc"][0]["osc_ko"] == "보라선 38.2" and sv["roc"][2]["error_ko"] == "SOL 5분봉 기록 없음"
    rows = R.signals_view({"signals": [(1, B, "30m", "ROC50-30m", "BTCUSDT", 1, "FILTERED", json.dumps({"why": "한 신호씩: …"})),
                                       (2, H, "1h", "ds-F7_RF_TRIPLE-1h-1", "ETHUSDT", -1, "WAITING", json.dumps({"why": "되돌림 기다림: …"}))],
                           "outcomes": []}, TR.T0 + 2 * HOUR)["rows"]
    assert [r["entry_ko"] for r in rows] == ["ROC 30분", "레인지 1시간"]


def test_the_friend_trend_board_shows_the_friend_bot_and_the_roc_reads(tmp_path):
    """친구 추세판 (screens/livebots-ftrend.js): per coin the 레인지 봇's ROC 30분 read and the 친구 30분 봇's own 30m read."""
    from paperbot.dash.more import liveftrend as FTR
    from tests.test_dash_live_range import SCREENS, _node
    ev = {"symbol": "SOLUSDT", "close_ms": T0, "side": 1, "why": "", "rule": "obv", "close": 150.0, "turn": 1, "obv_cs": 1,
          "obv_dark": True, "trend": 1, "votes": {"line": 1, "ema": 1, "chop": 1, "st": 0}}
    f30 = FTR.m30_row(M.board_row([ev], T0), T0 + MIN)
    roc = FTR.roc_row({"symbol": "SOLUSDT", "coin": "SOL", "side": 1, "ko": "롱 신호", "osc": 38.2, "osc_ko": "보라선 38.2", "at": T0})
    assert FTR.roc_row(None) is None and FTR.roc_row({"side": None, "error_ko": "못 읽음"})["state"] == "error"
    d = {"now_ms": T0 + MIN, "m30": {"state": "off", "ko": "바이비트 봇이 아직 꺼져 있어요"}, "h1": {"state": "none", "ko": "-"},
         "f30": {"state": "ok", "bot_ko": "실거래 봇", "last_close_ms": T0, "stale": False},
         "roc": {"state": "ok", "at": T0, "stale": False}, "agree": [], "rules_ko": FTR.RULES_KO,
         "coins": [{"symbol": "SOLUSDT", "coin": "SOL", "in30": True, "m30": FTR.m30_row(None, T0), "inf": True, "f30": f30,
                    "h1": {"state": "none"}, "roc": roc}]}
    out = _node(tmp_path, f"""
    const F = await import('file://{SCREENS}/livebots-ftrend.js');
    const ctx = {{params: {{query: {{}}}}, alive: () => true, track() {{}}, listen() {{}}, on() {{}}, watch() {{}}, href: (n) => '#/' + n,
      every() {{}}, api: async () => JSON.parse(JSON.stringify(D_d))}};
    const v = F.ftrendView(ctx); await tick(); await tick();
    console.log(JSON.stringify({{a: texts(v.el)}}));""", d=d)
    a = out["a"]
    for w in ("ROC 30분 (레인지 봇) 롱 신호 보라선 38.2", "30분 (친구 30분 봇) 상승", "OBV 진한 초록", "롱 신호",
              "친구 30분 봇 (실거래 봇)", "ROC 30분(레인지 봇, 10-30)"):
        assert w in a, (w, a)


def test_the_start_screen_centre_is_the_bots_trading_now(tmp_path):
    """한눈에 (owners 10-30 photo: the centre still the switched-off 추세판단 봇): once no executor follows it, the centre's
    ring and words are the bots trading now (livebots-hq.js liveBots / liveBotsWords / idleWords with the bots)."""
    from tests import test_dash_livev39 as TV
    from tests.test_dash_live_range import SCREENS
    out = TV._node(tmp_path, f"""
    const HQ = await import('file://{SCREENS}/livebots-hq.js');
    const d = {{paper: {{state: 'ok', stale: true}}, execs: [{{id: 'mexc', bot: 'range', follows_ko: '레인지 봇'}}, {{id: 'deepcoin', bot: 'paper2'}}],
      accts: [{{id: 'mexc', name_ko: 'WOO X Pro', follows_ko: '레인지 봇', state: 'ok', stale: false, halted: false, position: null}},
              {{id: 'deepcoin', name_ko: '딥코인', follows_ko: 'VWAP 개선판', state: 'ok', stale: false, position: {{symbol: 'ETHUSDT', side: -1}}}}]}};
    const mixes = [{{bot: '친구 30분 봇', account: 'WOO X Pro 2', unit: 'paperbot-mixchop', live: {{status: {{state: 'running'}}, position: null}}}},
                   {{bot: '바이비트 봇', account: '바이비트', unit: 'paperbot-mixbybit', live: {{status: {{state: 'off'}}}}}}];
    const bots = HQ.liveBots(d, mixes);
    const allOn = HQ.liveBots(d, [mixes[0]]);
    console.log(JSON.stringify({{bots, w: HQ.liveBotsWords(bots), on: HQ.liveBotsWords(allOn), idle: HQ.idleWords(d, null, allOn),
      none: HQ.liveBotsWords([]), old: HQ.idleWords(d, null)}}));""")
    bots = out["bots"]
    assert [(b["bot"], b["account"], b["ko"]) for b in bots] == [("레인지 봇", "WOO X Pro", "돌아가는 중"), ("VWAP 개선판", "딥코인", "돌아가는 중"),
                                                               ("친구 30분 봇", "WOO X Pro 2", "돌아가는 중"), ("바이비트 봇", "바이비트", "꺼짐")]
    assert bots[1]["pos"] == "ETH 숏" and bots[1]["symbol"] == "ETHUSDT" and bots[0]["pos"] is None
    assert out["w"] == {"tone": "warn", "head": "실거래 봇 3/4개 돌아가는 중", "sub": "포지션: ETH 숏 (VWAP 개선판)"}
    assert out["on"]["tone"] == "ok" and out["on"]["head"] == "실거래 봇 3/3개 돌아가는 중"
    assert out["idle"]["head"] == "실거래 봇 3/3개 돌아가는 중" and out["idle"]["on"] is True
    assert out["none"]["head"] == "실거래 봇 불러오는 중"
    assert out["old"]["head"] == "추세판단 봇 꺼 둠"                   # without the bots (an old caller): as before


def test_a_switched_off_optional_executor_leaves_the_site(tmp_path, monkeypatch):
    """Owners 10-30 ("딥코인 봇이랑 투비트 봇은 안돌릴예정"): once their units are disabled and stopped, the 딥코인 and 투비트
    slots leave the site's answers as if they were not installed (livebots.installed); a running or unknown one stays."""
    from paperbot import livecheck as LC
    from paperbot.dash.more import livebots as L
    p = {k: str(tmp_path / f"{k}.json") for k in ("deepcoin_config", "toobit_config", "wooxpro2_config")}
    for v in p.values():
        Path(v).write_text("{}", encoding="utf-8")
    base = {"bybit_config": str(tmp_path / "no-b.json"), "mexc_config": str(tmp_path / "no-m.json"), **p}
    states = {"paperbot-executor-deepcoin": ("inactive", "disabled"), "paperbot-executor-toobit": ("active", "enabled"),
              "paperbot-executor-wooxpro2": ("", "")}
    monkeypatch.setattr(LC, "unit_state", lambda u: states.get(u, ("", "")))
    # owners 10-31: both slots are retired from the site for good (tests/test_retired_slots.py); the switch-off rule they
    # came with still holds for an optional slot (WOO X Pro 2), checked here with them kept
    monkeypatch.setattr(L, "RETIRED_SLOTS", ())
    L._off_cache.clear()
    ids = [s[0] for s in L.installed(base)]
    assert "deepcoin" not in ids and "toobit" in ids and "wooxpro2" in ids
    states["paperbot-executor-toobit"] = ("inactive", "disabled")
    L._off_cache.clear()
    assert [s[0] for s in L.installed(base)] == [x for x in ids if x not in ("deepcoin", "toobit")]
    # a unit systemd does not know (a machine without it): unknown, it stays
    states["paperbot-executor-deepcoin"] = ("", "not-found")
    L._off_cache.clear()
    assert "deepcoin" in [s[0] for s in L.installed(base)] and LC.switched_off("paperbot-executor-deepcoin") is False
    # a failed one still counts as running (its alarms stay): it stays on the site
    states["paperbot-executor-toobit"] = ("failed", "disabled")
    L._off_cache.clear()
    assert "toobit" in [s[0] for s in L.installed(base)]
    L._off_cache.clear()
