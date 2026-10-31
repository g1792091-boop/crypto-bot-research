"""Owners 2026-10-31 night, the clean redo of three bots (레인지 봇, 바이비트 봇, WOO X Pro 2 친구 봇).

The owners: "이 추세지표는 레인지봇, 바이비트봇, woo x pro 2친구봇에 공통으로 쓰이는 추세지표야" (추세 바만.pine),
"이거는 바이비트, woox pro2 친구봇 진입방식 파일이야" (OBV MACD), the friend's note for WOO X Pro 2 ("15분봉 진입 추세 바를
통해서 추세를 정하고 그리고 추세에 맞게 히스토 그램이 0선 돌파 할때 진입", 'ALL + OBV6 MACD'), and their answers: the
레인지 봇 the same as the friend bot ("15분봉 0선 돌파만", its old 추세 3개 일치 entry out), every bot on SOL · ETH · XRP ·
BCH · ZEC · DOGE ("모든 코인 종목들은 SOL · ETH · XRP · BCH · ZEC · DOGE 이걸로 해줘"), and the 레인지 봇 moved onto the mix
bots' program trading the first WOO X Pro account itself ("무슨 방법이 제일 괜찮은데? 그 방법으로 해줘").

- friendtrend part 9: the trend bar's six rows and 종합 against the script's own formulas, the 'ALL + OBV6 MACD'
  histogram and its 0 cross; a read on the history up to a bar is the pane at that bar; 1,500 bars read what a longer
  history reads;
- mixchop: trend "bar" (종합 노랑 = no entry, no four votes), rule "h0x" (the cross on 종합's side), the 바이비트 봇's
  OBV MACD rule under the trend bar, the words, the board, the bot's loop, the signals listing;
- mixcheck: the replay and the morning's count of the 0 crosses; the 레인지 봇's profile;
- the configs (three bots, one trend, six coins), the 레인지 봇's units (Conflicts= the old range executor), install.sh,
  the backup, the failure alerts, the live checks (REPLACED_BY "mexc")."""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from paperbot import friendtrend as FT
from paperbot import mixcheck as MC
from paperbot import mixchop as M

sys.path.insert(0, os.path.dirname(__file__))
from test_rules1030 import frame, walk  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
MIN, HOUR = 60_000, 3_600_000
SIX = ["SOLUSDT", "ETHUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT"]


# ====================================================================== the script's formulas, written out again
def _ema(x, n):
    """Pine ta.ema: the first n values' mean, then alpha = 2 / (n + 1); leading na skipped."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(x))
    f = ok[0]
    s = x[f:f + n].mean()
    out[f + n - 1] = s
    a = 2.0 / (n + 1)
    for i in range(f + n, len(x)):
        s = a * x[i] + (1 - a) * s
        out[i] = s
    return out


def _sma(x, n):
    return pd.Series(np.asarray(x, float)).rolling(n).mean().to_numpy()


def _zsq(x, n):
    """zsq(x, len) => sd = ta.stdev(x, len), sd > 0 ? tanh(x / sd) : 0.0 (tanh's argument clipped to +-10), then nz."""
    x = np.asarray(x, float)
    sd = pd.Series(x).rolling(n).std(ddof=0).to_numpy()
    out = np.zeros(len(x))
    for i in range(len(x)):
        if np.isfinite(sd[i]) and sd[i] > 0 and np.isfinite(x[i]):
            out[i] = math.tanh(max(min(x[i] / sd[i], 10.0), -10.0))
    return out


def _six_four(h, l, c, v):
    hlc3 = (h + l + c) / 3
    sv = np.array([v[i] if i > 0 and hlc3[i] - hlc3[i - 1] >= 0 else -v[i] for i in range(len(c))])
    sgn = np.r_[0.0, np.sign(np.diff(c))]
    ob = np.cumsum(sgn * v)                                              # ta.obv
    hl2 = (h + l) / 2
    ao = _sma(hl2, 5) - _sma(hl2, 34)
    roc = np.r_[np.full(9, np.nan), 100 * (c[9:] - c[:-9]) / c[:-9]]
    zO, zR, zK = _zsq(ob - _ema(ob, 20), 100), _zsq(roc, 100), _zsq(_ema(sv, 34) - _ema(sv, 55), 100)
    zM, zAo, zAc = _zsq(_ema(c, 12) - _ema(c, 26), 100), _zsq(ao, 100), _zsq(ao - _sma(ao, 5), 100)
    return _ema(100 * (zO + zR + zK + zM + zAo + zAc) / 6, 3), _ema(100 * (zAo + zAc + zO + zK) / 4, 3)


def _tot(st1, st2, st3, st4, st5, st6):
    """⓪ 종합, line for line from the script."""
    rows = (st1, st2, st3, st4, st5, st6)
    n_up = sum(1 for x in rows if x == 1)
    n_dn = sum(1 for x in rows if x == -1)
    n_sd = 6 - n_up - n_dn
    return 0 if n_sd >= 2 or (n_up >= 2 and n_dn >= 2) else 1 if n_up >= 2 else -1 if n_dn >= 2 else 0


# ====================================================================== friendtrend part 9
def test_the_six_and_four_averages_are_the_scripts():
    _o, h, lo, c, v = walk(1200, seed=61)
    six, four = FT.six_four(h, lo, c, v)
    w6, w4 = _six_four(h, lo, c, v)
    assert np.allclose(six[200:], w6[200:], rtol=1e-9, atol=1e-9) and np.allclose(four[200:], w4[200:], rtol=1e-9, atol=1e-9)


def test_the_trend_bar_rows_and_the_total_are_the_scripts():
    _o, h, lo, c, v = walk(1500, seed=62)
    P = FT.bar_pane(h, lo, c, v)
    R = P["rows"]
    er = FT.ema_rsi(c)
    w6, w4 = _six_four(h, lo, c, v)
    _, up5 = M.supertrend(h, lo, c, 14, 5.0)
    _, up3 = M.supertrend(h, lo, c, 14, 3.0)
    rsi_s = (np.nan_to_num(M.rsi(c, 26), nan=50.0) - 50) / 50
    roc = np.r_[np.full(9, np.nan), 100 * (c[9:] - c[:-9]) / c[:-9]]
    mom = np.r_[np.full(10, np.nan), c[10:] - c[:-10]]
    nline = np.cumsum((rsi_s + _zsq(roc, 100) + _zsq(mom, 100)) / 3)
    nsig = _ema(nline, 9)
    seen = set()
    for i in range(300, len(c)):
        cyan, purp = nline[i] > nsig[i], nline[i] < nsig[i]
        green, red = er[i] > 50, er[i] < 50
        s_dir = 1 if up5[i] and up3[i] else -1 if not up5[i] and not up3[i] else 0
        score = (1 if cyan else -1 if purp else 0) + (1 if green else -1 if red else 0) + s_dir
        st1 = 1 if score >= 2 else -1 if score <= -2 else 0
        st2 = 1 if w6[i] >= 0 else -1
        st3 = 1 if cyan else -1 if purp else 0
        st4 = 1 if green else -1 if red else 0
        st6 = 1 if w4[i] >= 0 else -1
        assert (R["score"][i], R["six"][i], R["line"][i], R["ema"][i], R["st"][i], R["four"][i]) == \
            (st1, st2, st3, st4, s_dir, st6), i
        assert P["score"][i] == score and P["trend"][i] == _tot(st1, st2, st3, st4, s_dir, st6), i
        seen.add(int(P["trend"][i]))
    assert seen == {1, -1, 0}                       # 초록, 빨강 and 노랑 all occur on this walk


def test_the_total_rule_on_every_combination():
    import itertools
    for rows in itertools.product((1, -1, 0), (1, -1), (1, -1, 0), (1, -1, 0), (1, -1, 0), (1, -1)):
        up = sum(x == 1 for x in rows)
        dn = sum(x == -1 for x in rows)
        sd = 6 - up - dn
        P = _tot(*rows)
        assert P == (0 if sd >= 2 or (up >= 2 and dn >= 2) else 1 if up >= 2 else -1 if dn >= 2 else 0)
    # the module's vectorised rule on the same table
    combos = list(itertools.product((1, -1, 0), (1, -1), (1, -1, 0), (1, -1, 0), (1, -1, 0), (1, -1)))
    A = np.array(combos)
    up, dn = (A == 1).sum(1), (A == -1).sum(1)
    sd = 6 - up - dn
    got = np.where((sd >= 2) | ((up >= 2) & (dn >= 2)), 0, np.where(up >= 2, 1, np.where(dn >= 2, -1, 0)))
    assert list(got) == [_tot(*r) for r in combos]
    # two up and two down with two sideways, three up and three down: 노랑; five up, one down: 초록
    assert _tot(1, 1, -1, -1, 0, 1) == 0 and _tot(1, 1, 1, -1, -1, -1) == 0 and _tot(1, 1, 1, 1, 1, -1) == 1
    assert _tot(-1, -1, -1, 1, -1, -1) == -1 and _tot(1, 1, 0, 0, 1, 1) == 0


def test_the_histogram_and_its_zero_cross_are_the_scripts():
    _o, h, lo, c, v = walk(1500, seed=63)
    H = FT.h6_pane(h, lo, c, v)
    a = 2 * (FT.ema_rsi(c) - 50)                              # valA ("EMA RSI")
    ml = FT.mix_line(h, lo, c, v)
    v_obv = 100 * _zsq(ml - _ema(ml, 52), 100)                # vObv
    w6, _w4 = _six_four(h, lo, c, v)
    avg = (a + (v_obv + w6) / 2) / 2                          # (valA * 1 + valB * 1) / 2, valB = (vObv + v6) / 2
    macd = _ema(avg, 3)
    sig = _ema(macd, 9)
    hist = macd - sig
    assert np.allclose(H["hist"][300:], hist[300:], rtol=1e-8, atol=1e-8)
    assert np.allclose(H["macd"][300:], macd[300:], rtol=1e-8, atol=1e-8)
    for i in range(300, len(c)):                              # ta.crossover / ta.crossunder of the histogram and 0
        want = 1 if hist[i] > 0 and hist[i - 1] <= 0 else -1 if hist[i] < 0 and hist[i - 1] >= 0 else 0
        assert H["cross"][i] == want, i
    # the cross is the MACD line crossing its signal (the same bar, MACD mode)
    gold = H["macd"] > H["sig"]
    for i in range(300, len(c)):
        if H["cross"][i]:
            assert bool(gold[i]) == (H["cross"][i] > 0) and bool(gold[i - 1]) != bool(gold[i])
    assert {1, -1} <= set(int(x) for x in H["cross"][300:])


def test_a_read_on_a_prefix_is_the_pane_at_that_bar_and_1500_bars_are_enough():
    _o, h, lo, c, v = walk(3000, seed=64)
    P = FT.bar_pane(h, lo, c, v)
    H = FT.h6_pane(h, lo, c, v)
    sides = set()
    for i in range(400, 3000, 97):
        st = FT.h0x_state(h[:i + 1], lo[:i + 1], c[:i + 1], v[:i + 1])
        assert st["bar"]["trend"] == P["trend"][i] and st["cross"] == H["cross"][i]
        assert st["bar"]["rows"] == {k: int(r[i]) for k, r in P["rows"].items()}
        assert st["side"] == (st["cross"] if st["cross"] == st["bar"]["trend"] else 0)
        sides.add(st["side"])
    # the bot reads 1,499 closed bars: the same rows, 종합 and histogram as the whole history at the last bar
    for end in (2200, 2600, 2999):
        a = FT.bar_state(h[end - 1498:end + 1], lo[end - 1498:end + 1], c[end - 1498:end + 1], v[end - 1498:end + 1])
        assert a["trend"] == P["trend"][end] and a["rows"] == {k: int(r[end]) for k, r in P["rows"].items()}
        x = FT.h6_pane(h[end - 1498:end + 1], lo[end - 1498:end + 1], c[end - 1498:end + 1], v[end - 1498:end + 1])
        assert x["hist"][-1] == pytest.approx(H["hist"][end], abs=1e-6) and x["cross"][-1] == H["cross"][end]


def test_the_trend_bar_words():
    t = {"trend": 1, "rows": {"score": 1, "six": 1, "line": 1, "ema": 1, "st": 0, "four": -1}, "n": [4, 1, 1], "score": 2}
    assert FT.bar_words(t) == ("종합 상승 (상승 4 · 하락 1 · 횡보 1: 3개 점수 +2 · 6종 평균 상승 · 하늘·보라 선 하늘 · "
                               "EMA RSI 초록 · 슈퍼트렌드 횡보 · 4종 평균 하락)")
    t0 = {"trend": 0, "rows": {"score": 0, "six": -1, "line": 1, "ema": -1, "st": 0, "four": 1}, "n": [2, 2, 2], "score": 0}
    assert FT.bar_words(t0).startswith("종합 횡보(진입 금지) (상승 2 · 하락 2 · 횡보 2: 3개 점수 0 · ")
    assert FT.bar_words({"trend": -1}) == "종합 하락"
    assert [k for k, _ in FT.BAR_ROWS] == ["score", "six", "line", "ema", "st", "four"]
    assert FT.h0x_side(1, 1) == 1 and FT.h0x_side(-1, -1) == -1 and FT.h0x_side(1, 0) == 0 and FT.h0x_side(1, -1) == 0
    assert FT.h0x_side(0, 1) == 0


# ====================================================================== mixchop: trend "bar", rule "h0x"
def _bar(trend, rows=None, n=None, score=None):
    rows = rows or {"score": trend, "six": trend or 1, "line": trend, "ema": trend, "st": trend, "four": trend or -1}
    up = sum(1 for x in rows.values() if x == 1)
    dn = sum(1 for x in rows.values() if x == -1)
    return {"trend": trend, "rows": rows, "n": n or [up, dn, 6 - up - dn], "score": 3 * trend if score is None else score,
            "ersi": 61.2}


def _h6(cross, hist=4.2, n=400):
    x = np.zeros(n, np.int8)
    x[-1] = cross
    hv = np.full(n, 1.0)
    hv[-1] = hist
    return {"macd": hv, "sig": hv, "hist": hv, "cross": x}


def _judge(monkeypatch, rule, bar, cross=0, ob=None, tf=M.MIN15):
    b = frame(400, tf_ms=tf, vol=0.002)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 30)
    monkeypatch.setattr(FT, "bar_state", lambda *a: bar)
    monkeypatch.setattr(FT, "h6_pane", lambda *a: _h6(cross))
    monkeypatch.setattr(FT, "last_trend", lambda *a: pytest.fail("the four votes are not this trend"))
    if ob is not None:
        monkeypatch.setattr(FT, "obvac_state", lambda *a: ob)
    return M.Bot.judge(rule, co, b, b.iloc[0:0], T0, tf, "bar")


def test_h0x_enters_on_the_cross_with_the_trend_bar(monkeypatch):
    ev = _judge(monkeypatch, "h0x", _bar(1), cross=1)
    assert ev["side"] == 1 and ev["rule"] == "h0x" and ev["x0"] == 1 and ev["h6"] == 4.2 and ev["tf"] == "15분"
    assert ev["trend"] == 1 and ev["trend_mode"] == "bar" and ev["bar"]["score"] == 1 and ev["bar_n"] == [6, 0, 0]
    assert ev["ema_rsi"] == 61.2 and "votes" not in ev and "chop_zone" not in ev
    assert _judge(monkeypatch, "h0x", _bar(-1), cross=-1)["side"] == -1
    # the cross against 종합: no entry, the trend bar said
    ev = _judge(monkeypatch, "h0x", _bar(-1), cross=1)
    assert ev["side"] == 0 and ev["why"].startswith("추세 바 종합 하락 (") and ev["why"].endswith(": 신호 롱와 반대")
    # 종합 노랑: no entry whichever way it crossed
    yellow = _bar(0, rows={"score": 0, "six": 1, "line": 1, "ema": -1, "st": 0, "four": -1}, score=1)
    for x in (1, -1):
        ev = _judge(monkeypatch, "h0x", yellow, cross=x)
        assert ev["side"] == 0 and ev["why"] == ("추세 바 종합 횡보(진입 금지) (상승 2 · 하락 2 · 횡보 2: 3개 점수 +1 · 6종 평균 상승 "
                                                "· 하늘·보라 선 하늘 · EMA RSI 빨강 · 슈퍼트렌드 횡보 · 4종 평균 하락)")
    # no cross: said so, whatever 종합 is
    ev = _judge(monkeypatch, "h0x", _bar(1), cross=0)
    assert ev["side"] == 0 and ev["why"] == "히스토그램 0선 돌파 없음" and ev["x0"] == 0
    # the signal's words and the board
    ev = _judge(monkeypatch, "h0x", _bar(1), cross=1)
    assert M.friend_words(ev, 1).startswith("히스토그램 0선 위로 돌파(히스토그램 4.2) · 추세 바 15분 종합 상승 (상승 6 · ")
    assert M.reason_words(ev, 1).startswith("근거: 히스토그램 0선 위로 돌파")
    row = M.board_row([ev], T0)
    assert row["rules"]["h0x"] == {"side": 1, "why": ""} and row["trend_mode"] == "bar" and row["x0"] == 1
    assert row["bar"] == ev["bar"] and row["bar_n"] == [6, 0, 0] and row["bar_score"] == 3 and "votes" not in row
    assert M.RULE_KO["h0x"] == "히스토그램 0선 돌파" and "h0x" in M.FRIEND_RULES and "h0x" not in M.OBV_RULES
    assert "bar" in M.TRENDS


def test_the_bybit_rule_under_the_trend_bar(monkeypatch):
    up = {"turn": 1, "cs": 1, "dark": True, "ac": 0.42, "ac_col": 1, "side": 1}
    ev = _judge(monkeypatch, "obvac", _bar(1), ob=up, tf=M.MIN30)
    assert ev["side"] == 1 and ev["trend_mode"] == "bar" and "tf" not in ev and ev["ac"] == 0.42
    assert M.friend_words(ev, 1) == ("OBV 연한 초록→진한 초록 · AC 플러스 양봉(0.42) · 추세 바 30분 종합 상승 (상승 6 · 하락 0 · "
                                      "횡보 0: 3개 점수 +3 · 6종 평균 상승 · 하늘·보라 선 하늘 · EMA RSI 초록 · 슈퍼트렌드 상승 · "
                                      "4종 평균 상승)")
    ev = _judge(monkeypatch, "obvac", _bar(0, rows={"score": 0, "six": 1, "line": 1, "ema": 1, "st": 0, "four": -1}),
                ob=up, tf=M.MIN30)
    assert ev["side"] == 0 and ev["why"].startswith("추세 바 종합 횡보(진입 금지)")
    ev = _judge(monkeypatch, "obvac", _bar(-1), ob=up, tf=M.MIN30)
    assert ev["side"] == 0 and ev["why"].endswith(": 신호 롱와 반대")


def test_the_real_indicators_through_the_bot(monkeypatch):
    """No patches: the bot's answer on each close is the pane's (the cross on 종합's side), the stop guard aside."""
    b = frame(1500, tf_ms=M.MIN15, vol=0.002, seed=7)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 30)
    o, h, lo, c, v = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    P, H = FT.bar_pane(h, lo, c, v), FT.h6_pane(h, lo, c, v)
    got = set()
    for i in range(1100, 1500):
        if not H["cross"][i]:
            continue
        bb = b.iloc[:i + 1].reset_index(drop=True)
        ev = M.evaluate_friend("h0x", co, bb, int(bb.open_ms.iloc[-1]) + M.MIN15, M.MIN15, "bar")
        want = int(H["cross"][i]) if H["cross"][i] == P["trend"][i] else 0
        assert ev["x0"] == H["cross"][i] and ev["trend"] == P["trend"][i] and ev["side"] == (want if ev["liq_ok"] else 0)
        got.add(ev["side"])
    assert {1, -1, 0} <= got


def test_a_15m_close_in_the_loop_logs_the_cross_and_enters(tmp_path, monkeypatch):
    d = json.loads((DEPLOY / "mixrange.paper.json").read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "state.json"), log=str(tmp_path / "log.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN.STOP"), no_weekend=False, us_open_pre_min=0, us_open_pause_min=0,
             macro_blackout_min=0)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    cfg = M.load_config(str(p))
    ce = T0 + M.MIN15
    rows = [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in ce - M.MIN15 * np.arange(400, -1, -1)]   # with the bar opening now
    asked = []

    def fetch(sym, tf, n):
        asked.append(tf)
        return rows

    def fake_eval(rule, co, b, close_ms, tf_ms=M.MIN30, trend="four"):
        assert (rule, tf_ms, trend) == ("h0x", M.MIN15, "bar")
        x0 = {"ETHUSDT": 1, "SOLUSDT": -1}.get(co.symbol, 0)
        side = 1 if co.symbol == "ETHUSDT" else 0
        return {"symbol": co.symbol, "close_ms": close_ms, "side": side, "rule": rule, "x0": x0, "h6": 3.1 * x0,
                "why": "" if side else ("추세 바 종합 횡보(진입 금지)" if x0 else "히스토그램 0선 돌파 없음"),
                "close": 10.0, "stop_dist": 0.1, "stop_pct": 1.0, "trend": side, "trend_mode": "bar", "tf": "15분",
                "bar": {"score": side, "six": 1, "line": side, "ema": side, "st": side, "four": 1},
                "bar_n": [6, 0, 0] if side else [2, 0, 4], "bar_score": 3 * side}
    monkeypatch.setattr(M, "evaluate_friend", fake_eval)
    msgs = []
    bot = M.Bot(cfg, M.PaperBroker(100.0, cfg.taker_fee), fetch, lambda: ce + 5_000, notify=lambda lv, t: msgs.append(t),
                sleep=lambda s: None)
    bot.on_close(ce)
    assert set(asked) == {"15m"}
    assert bot.pos is not None and bot.pos.symbol == "ETHUSDT" and bot.pos.side == 1
    logged = [json.loads(x) for x in Path(cfg.log).read_text(encoding="utf-8").splitlines()]
    sig = {r["symbol"]: r for r in logged if r.get("kind") == "signal"}
    assert set(sig) == {"ETHUSDT", "SOLUSDT"}                     # a cross is logged even when the trend refused it
    assert sig["SOLUSDT"]["x0"] == -1 and sig["SOLUSDT"]["side"] == 0
    assert bot.board["ETHUSDT"]["rules"]["h0x"]["side"] == 1 and bot.board["XRPUSDT"]["trend_mode"] == "bar"
    assert any("히스토그램 0선 위로 돌파" in m and "추세 바 15분 종합 상승" in m for m in msgs)


def test_the_signals_listing_and_the_check(tmp_path, monkeypatch, capsys):
    cfg = M.load_config(str(DEPLOY / "mixrange.paper.json"))
    b = frame(1500, tf_ms=M.MIN15, vol=0.002, seed=9)
    lines = M.friend_history(cfg.coins[0], b, "h0x", 30, M.MIN15, "bar")
    assert 1 <= len(lines) <= 30 and all("히스토그램 0선 " in x and " 추세 바 종합 " in x and "→" in x for x in lines)
    assert any(x.endswith("→ X (종합 노랑, 진입 금지)") for x in lines) or any(x.endswith("→ X (추세 다름)") for x in lines)
    o, h, lo, c, v = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    n_cross = int((FT.h6_pane(h, lo, c, v)["cross"][301:] != 0).sum())
    assert len(M.friend_history(cfg.coins[0], b, "h0x", 10_000, M.MIN15, "bar")) == n_cross
    # the bybit bot's rule listed under the trend bar
    ob = M.friend_history(cfg.coins[0], frame(1500, tf_ms=M.MIN30, vol=0.002, seed=9), "obvac", 5, M.MIN30, "bar")
    assert ob and all(" 추세 바 종합 " in x for x in ob)
    # ``signals``: the trend bar named once per rule
    rows = b[["open_ms", "open", "high", "low", "close", "volume"]].to_numpy().tolist()
    end = int(rows[-1][0]) + M.MIN15
    monkeypatch.setattr(M, "binance_fetch", lambda base: lambda s, tf, n: [r for r in rows if r[0] < end][-n:])
    monkeypatch.setattr(M.time, "time", lambda: end / 1000 + 60)
    assert M.cmd_signals(argparse.Namespace(config=str(DEPLOY / "mixrange.paper.json"), n=3)) == 0
    out = capsys.readouterr().out
    assert out.count("  -- 히스토그램 0선 돌파 (추세 15분: 추세 바 종합(3개 점수 · 6종 · 하늘·보라 · EMA RSI · 슈퍼트렌드 · 4종, "
                     "노랑이면 진입 안 함))") == 6


def test_the_morning_replay_counts_the_crosses():
    cfg = M.load_config(str(DEPLOY / "mixrange.paper.json"))
    cfg.coins = cfg.coins[:1]
    b = frame(2000, tf_ms=M.MIN15, vol=0.002, seed=11, end_ms=T0)
    rows = b[["open_ms", "open", "high", "low", "close", "volume"]].to_numpy().tolist()
    rows = [[int(r[0]), *r[1:]] for r in rows]

    def klines(symbol, tf, start, limit):
        assert tf == "15m"
        return [r for r in rows if r[0] >= start][:limit]
    day0 = T0 - 24 * HOUR
    log = []
    co = cfg.coins[0]
    for ce in range(day0 + M.MIN15, T0 + 1, M.MIN15):
        bb = M.bars_frame(rows, M.MIN15, ce).tail(M.BARS - 1).reset_index(drop=True)
        ev = M.Bot.judge("h0x", co, bb, bb, ce, M.MIN15, "bar")
        if ev.get("x0") or ev["side"]:
            log.append({"ts": ce + 5_000, "kind": "signal", **ev})
    assert log
    rp = MC.signal_replay(cfg, day0, T0, log, klines, obs=[[T0 + 3 * MIN, T0, None]], st_last=T0)
    assert rp["state"] == "ok" and rp["different"] == [] and rp["rules"] == ["h0x"] and rp["tf_ko"] == "15분"
    assert rp["x0s"] == len(log) and "turns" not in rp
    assert f"히스토그램 0선 돌파 {rp['x0s']}번" in MC.replay_lines(rp)[0]
    gone = log[0]
    rp2 = MC.signal_replay(cfg, day0, T0, log[1:], klines, obs=[], st_last=T0)
    assert any(x["close_ms"] == gone["close_ms"] and x["rule"] == "h0x" for x in rp2["missed"] + rp2["unsure"])
    # a row the bot logged with the other direction: told apart
    flip = [dict(log[0], x0=-int(log[0]["x0"]))] + log[1:]
    rp3 = MC.signal_replay(cfg, day0, T0, flip, klines, obs=[[T0 + 3 * MIN, T0, None]], st_last=T0)
    assert [x["close_ms"] for x in rp3["different"]] == [gone["close_ms"]]
    assert MC.signal_counts(log)["x0s"] == len({(r["symbol"], r["close_ms"]) for r in log})
    assert MC.RULE_TAG["h0x"] == "(히스토그램 0선 돌파)" and MC.RULE_WHAT["h0x"] == "히스토그램 0선 돌파"


# ====================================================================== the configs
def _cfg(name):
    return M.load_config(str(DEPLOY / name))


def test_three_bots_one_trend_six_coins():
    bots = {"bybit": ("mixbybit.live.json", "mixbybit.paper.json"), "friend": ("mixchop.live.json", "mixchop.paper.json"),
            "range": ("mixrange.live.json", "mixrange.paper.json")}
    for key, (live, paper) in bots.items():
        for name, mode in ((live, "mainnet"), (paper, "paper")):
            cfg = _cfg(name)
            assert cfg.mode == mode and cfg.trend == "bar" and cfg.symbols == SIX, name
            assert cfg.stop_atr == 3.0 and {c.sl_atr for c in cfg.coins} == {3.0}
            assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0} and cfg.ladder_every_s == 60
            assert cfg.margin_frac == 0.4 and cfg.equity_floor_frac == 0 and cfg.max_notional_usd == 10000
            assert cfg.no_weekend and cfg.us_open_pre_min == cfg.us_open_pause_min == cfg.macro_blackout_min == 30
            assert cfg.telegram == (mode == "mainnet")
    by, fr, rg = _cfg("mixbybit.live.json"), _cfg("mixchop.live.json"), _cfg("mixrange.live.json")
    assert (by.name, by.exchange, by.tf, by.rules) == ("바이비트 봇", "bybit", "30m", ("obvac",))
    assert (fr.name, fr.exchange, fr.tf, fr.rules) == ("친구 15분 봇", "wooxpro", "15m", ("h0x",))
    assert (rg.name, rg.exchange, rg.tf, rg.rules) == ("레인지 봇", "wooxpro", "15m", ("h0x",))
    assert {c.symbol: c.leverage for c in by.coins} == {c.symbol: c.leverage for c in fr.coins} == \
        {**{s: 40 for s in SIX}, "ZECUSDT": 20}
    # the 레인지 봇 keeps its leverage (the old range executor's 30x; ZEC 20x as the other two)
    assert {c.symbol: c.leverage for c in rg.coins} == {**{s: 30 for s in SIX}, "ZECUSDT": 20}
    # the friend bot and the 레인지 봇: one rule, one trend, one bar; their own files
    same = ("tf", "trend", "rules", "stop_atr", "ladder", "margin_frac", "equity_floor_frac", "ladder_every_s")
    assert {k: getattr(fr, k) for k in same} == {k: getattr(rg, k) for k in same}
    files = [(c.state, c.log, c.own_stop_file) for c in (by, fr, rg, _cfg("mixbybit.paper.json"),
                                                          _cfg("mixchop.paper.json"), _cfg("mixrange.paper.json"))]
    assert len({x for f in files for x in f}) == 18
    assert rg.state == "/var/lib/paperbot/exec/mixrange-state.json" and rg.own_stop_file == "/var/lib/paperbot/exec/mixrange.STOP"
    rp = _cfg("mixrange.paper.json")
    assert rp.state.startswith("/var/lib/paperbot/mixrange-paper/") and rp.start_equity == 100
    words = M.plan_words(rg)
    assert "매매법 히스토그램 0선 돌파" in words and "손절 ATR 3배" in words and "계단 순ROE +10%→+8%, +15%→+13%" in words
    # a trend that is not one of the three is refused, with the new one named
    with pytest.raises(M.MixError, match="bar: 추세 바 종합"):
        p = Path(os.environ.get("TMPDIR", "/tmp")) / "bad-trend-1031c.json"
        d = json.loads((DEPLOY / "mixrange.live.json").read_text(encoding="utf-8"))
        p.write_text(json.dumps({**d, "trend": "votes"}), encoding="utf-8")
        try:
            M.load_config(str(p))
        finally:
            p.unlink()


def test_the_range_bot_is_the_third_mix_profile():
    from paperbot.dash.more import livemix as X
    R = X.PROFILES["range"]
    assert R.name == "레인지 봇" and R.exchange_ko == "WOO X Pro" and R.guide == "docs/range-bot-ko.md"
    assert [b[2] for b in R.bots] == ["paperbot-mixrange", "paperbot-mixrange-paper"]
    assert R.env["live"]["config"] == ("PAPERBOT_MIXRANGE_CONFIG", "/etc/paperbot/mixrange.json")
    assert R.env["live"]["repo_config"][1].endswith("deploy/mixrange.live.json")
    assert R.files == {"live": (_cfg("mixrange.live.json").state, _cfg("mixrange.live.json").log),
                       "paper": (_cfg("mixrange.paper.json").state, _cfg("mixrange.paper.json").log)}
    assert R.check_dir == "/var/lib/paperbot/mixrangecheck" and R.backtest is None
    os.environ[X.BOT_ENV] = "range"
    try:
        assert MC.prof_env() is R                              # the checks' units say PAPERBOT_MIX_BOT=range
    finally:
        del os.environ[X.BOT_ENV]


# ====================================================================== units, install, checks
def _unit(name):
    return (DEPLOY / name).read_text(encoding="utf-8").splitlines()


def test_the_range_bots_units():
    live = _unit("paperbot-mixrange.service")
    assert "Conflicts=paperbot-executor-mexc.service" in live and "EnvironmentFile=/etc/paperbot/executor.env" in live
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.mixchop run --config /etc/paperbot/mixrange.json" in live
    assert "OOMScoreAdjust=-900" in live and "RestartPreventExitStatus=2" in live
    paper = _unit("paperbot-mixrange-paper.service")
    assert "User=paperbot" in paper and not [x for x in paper if x.startswith("EnvironmentFile=/etc/paperbot/executor")]
    assert "ReadWritePaths=/var/lib/paperbot/mixrange-paper" in paper
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.mixchop run --config /etc/paperbot/mixrange-paper.json" in paper
    for u in ("paperbot-mixrangecheck.service", "paperbot-mixrangecheck-pass.service"):
        lines = _unit(u)
        assert "Environment=PAPERBOT_MIX_BOT=range" in lines and "ReadWritePaths=/var/lib/paperbot/mixrangecheck" in lines
        assert "ReadOnlyPaths=-/var/lib/paperbot/exec -/var/lib/paperbot/mixrange-paper /opt/crypto-bot-research" in lines
        assert "OnFailure=paperbot-failed@%n.service" in lines and not any("bybit" in x.lower() for x in lines
                                                                           if not x.startswith("#"))
    assert "OnCalendar=*-*-* 00:09:00 UTC" in _unit("paperbot-mixrangecheck.timer")
    assert "OnCalendar=*:3/5" in _unit("paperbot-mixrangecheck-pass.timer")
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    for u in ("paperbot-mixrange.service", "paperbot-mixrange-paper.service", "paperbot-mixrangecheck.service",
              "paperbot-mixrangecheck-pass.service", "paperbot-mixrangecheck.timer", "paperbot-mixrangecheck-pass.timer"):
        assert u in sh, u
    assert not re.search(r"systemctl (enable|start|restart)[^\n]*paperbot-mixrange(\.service|-paper|\s|$)", sh)
    assert "for t in paperbot-mixrangecheck.timer paperbot-mixrangecheck-pass.timer; do" in sh
    assert "install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/mixrange-paper" in sh
    bk = (DEPLOY / "paperbot-backup.sh").read_text(encoding="utf-8")
    for f in ("exec/mixrange-state.json", "exec/mixrange-log.jsonl", "mixrange-paper/state.json", "mixrange-paper/log.jsonl",
              "mixrangecheck/state.json"):
        assert f in bk, f


def test_the_live_checks_and_the_failure_alerts_know_the_range_bot():
    from paperbot import failalert as FA
    from paperbot import livecheck as LC
    assert LC.REPLACED_BY["mexc"] == ("/etc/paperbot/mixrange.json", "paperbot-mixrange", "레인지 봇")
    assert LC.REPLACED_BY["wooxpro2"] == ("/etc/paperbot/mixchop.json", "paperbot-mixchop", "친구 15분 봇")
    assert "paperbot-mixrange.service" in LC.PROTECTED_UNITS
    assert FA.JOBS_KO["paperbot-mixrangecheck.service"][0] == "레인지 봇 아침 점검(09:09)"
    assert "PAPERBOT_MIX_BOT=range" in FA.JOBS_KO["paperbot-mixrangecheck-pass.service"][1]
