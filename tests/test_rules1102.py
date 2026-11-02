"""Owners 2026-11-02: the three bots' new trend and entries, from the three Pine scripts they sent.

The owners: "30분봉 추세 15분봉은 진입 바꾸지말고 30분봉 추세인데 추세를 macd 히스토그램으로 사용 0선 위에 있으면 상승 0선
아래에 있으면 하락으로" (추세 MACD.pine), the 바이비트 봇: "obv 선은 사용 안함 히스토그램으로 진입 … 30분봉 추세macd가 봉 상관
없이 0선위에 있으면 상승추세로 보고 15분봉 obv 히스토그램이 0선 아래에서 양봉으로 바뀌면 롱진입 숏 진입은 반대 조건으로 …
추세 macd에서 노란 히스토 그램이 나와도 0선아래에 있으면 하락추세로 보고 0선 위에 있으면 상승추세로 보고 진입가능" (OBV4
MACD.pine), WOO X Pro 1 · 2: "30분봉 추세 macd가 0선 위에 있으면 상승 추세로 보고 15분봉 3합 히스토 그램이 0선을 상향 돌파
하면 롱진입 숏 진입은 반대 조건으로" (3합 히스토그램.pine).

- friendtrend part 10: the 추세 MACD's histogram (its six values, the MACD line, the signal) and its side of 0 whatever its
  colour (the yellow bars too), the OBV4 MACD's AC histogram and its colour turns, the 15종 MACD's fifteen inputs and the
  3합 histogram and its 0 cross, each against the script's formulas written out again here; a read on the history up to
  a bar is the pane at that bar; 1,499 bars read what a longer history reads;
- mixchop: trend "macd", rules "o4h" (the 바이비트 봇) and "h3x" (the 친구 15분 봇 and the 레인지 봇), the words, the board,
  the trend of the last closed 30m bar, the bot's loop, the signals listing, the check's and the start message's words;
- mixcheck: the replay and the morning's counts;
- the six deploy configs."""
import argparse
import json
import math
import os
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
from test_rules1031c import _ema, _pair, _sma, _six_four, _zsq  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
MIN, HOUR = 60_000, 3_600_000
SIX = ["SOLUSDT", "ETHUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT"]


def _roc(c, n):
    return np.r_[np.full(n, np.nan), 100 * (c[n:] - c[:-n]) / c[:-n]]


def _mom(c, n):
    return np.r_[np.full(n, np.nan), c[n:] - c[:-n]]


# ====================================================================== friendtrend part 10: 추세 MACD
def test_the_trend_macd_is_the_scripts():
    _o, h, lo, c, v = walk(1500, seed=71)
    T = FT.tmacd_pane(h, lo, c, v)
    rsi_s = (np.nan_to_num(M.rsi(c, 26), nan=50.0) - 50) / 50
    nline = np.cumsum((rsi_s + _zsq(_roc(c, 9), 100) + _zsq(_mom(c, 10), 100)) / 3)    # ta.cum((nRsiS + nRocS + nMomS) / 3)
    nsig = _ema(nline, 9)
    e_rsi = FT.ema_rsi(c)
    su = (M.supertrend(h, lo, c, 14, 5.0)[0] + M.supertrend(h, lo, c, 14, 3.0)[0]) / 2   # (su1 + su2) / 2
    v_n = 100 * _zsq(nline - nsig, 100)                       # ③ 하늘색 / 보라색
    v_e = 2 * (e_rsi - 50)                                    # ④ EMA RSI
    v_s = 100 * _zsq(c - su, 100)                             # ⑤ 슈퍼트렌드 평균 선 위 / 아래
    v_1 = (v_n + v_e + v_s) / 3                               # ① 3개 점수
    six, four = _six_four(h, lo, c, v)                        # ② · ⑥
    macd = _ema((v_1 + six + v_n + v_e + v_s + four) / 6, 3)  # tot4In: six values
    sig = _ema(macd, 9)
    hist = macd - sig
    assert np.allclose(T["macd"][300:], macd[300:], atol=1e-8) and np.allclose(T["hist"][300:], hist[300:], atol=1e-8)
    # the trend is the histogram's side of 0, whatever its colour: the yellow (종합 횡보) bars count the same way
    for i in range(300, len(c)):
        assert T["trend"][i] == (1 if hist[i] > 0 else -1 if hist[i] < 0 else 0), i
    B = FT.bar_pane(h, lo, c, v)
    assert (T["yellow"] == (B["trend"] == 0)).all()
    yel = [i for i in range(300, len(c)) if T["yellow"][i]]
    assert yel and {int(T["trend"][i]) for i in yel} == {1, -1}            # yellow bars on both sides of 0


def test_the_trend_macd_words():
    assert FT.tmacd_words({"trend": 1, "hist": 3.214, "yellow": False}) == "히스토그램 0선 위 상승(+3.21)"
    assert FT.tmacd_words({"trend": -1, "hist": -1.4, "yellow": True}) == "히스토그램 0선 아래 하락(-1.40, 노란 막대)"
    assert FT.tmacd_words({"trend": 0, "hist": 0.0}) == "히스토그램 0선(진입 안 함, +0.00)"
    assert FT.tmacd_words({"trend": 0, "hist": None}) == "히스토그램 0선(진입 안 함, 못 읽음)"


# ====================================================================== OBV4 MACD
def test_the_obv4_histogram_and_its_turns_are_the_scripts():
    _o, h, lo, c, v = walk(1500, seed=72)
    P = FT.o4_pane(h, lo, c, v)
    ml = FT.mix_line(h, lo, c, v)
    hl2 = (h + lo) / 2
    ao = _sma(hl2, 5) - _sma(hl2, 34)
    z = _zsq(ml - _ema(ml, 52), 100) + _zsq(ao, 100) + _zsq(ao - _sma(ao, 5), 100) + _zsq(_ema(c, 12) - _ema(c, 26), 100)
    macd = _ema(100 * z / 4, 3)
    sig = _ema(macd, 9)
    hraw = macd - sig
    acv = hraw - _sma(hraw, 5)                                # the default histogram 'AC 오실레이터 (가속)'
    assert np.allclose(P["ac"][300:], acv[300:], atol=1e-8) and np.allclose(P["macd"][300:], macd[300:], atol=1e-8)
    sides = set()
    for i in range(300, len(c)):
        green, red = acv[i] > acv[i - 1], acv[i] < acv[i - 1]
        assert P["col"][i] == (1 if green else -1 if red else 0)
        ac_g = green and not (acv[i - 1] > acv[i - 2])        # the script's 'AC 초록 전환'
        ac_r = red and not (acv[i - 1] < acv[i - 2])
        assert P["turn"][i] == (1 if ac_g else -1 if ac_r else 0), i
        want = 1 if ac_g and acv[i] < 0 else -1 if ac_r and acv[i] > 0 else 0   # under 0 turning green / over 0 red
        assert P["side"][i] == want, i
        sides.add(want)
    assert sides == {1, -1, 0}
    # a green turn over 0 and a red turn under 0 are not entries
    assert any(P["turn"][i] == 1 and P["ac"][i] > 0 and P["side"][i] == 0 for i in range(300, len(c)))
    assert any(P["turn"][i] == -1 and P["ac"][i] < 0 and P["side"][i] == 0 for i in range(300, len(c)))


def test_the_obv4_words():
    assert FT.o4_words(-3.2, 1) == "0선 아래 양봉 전환(-3.20)"
    assert FT.o4_words(2.1, -1) == "0선 위 음봉 전환(2.10)"
    assert FT.o4_words(1.1, 1) == "0선 위 양봉 전환(1.10)"
    assert FT.o4_words(0.4, 0) == "전환 없음(0.40)" and FT.o4_words(None, 0) == "전환 없음(못 읽음)"


# ====================================================================== 15종 MACD and the 3합 histogram
def _loops_q15(o, h, lo, c, v):
    """The 15종 MACD's inputs that are not one-line built-ins, bar by bar as the script writes them."""
    n = len(c)
    hlc3 = (h + lo + c) / 3
    out = {k: np.full(n, np.nan) for k in ("bb", "wpr", "mfi", "uo", "poc")}
    atr = M.atr(h, lo, c, 14)
    for i in range(n):
        if i >= 19:                                           # ta.bb(close, 20, 2)
            w = c[i - 19:i + 1]
            bm, sd = w.mean(), w.std()
            up, dn = bm + 2 * sd, bm - 2 * sd
            out["bb"][i] = (c[i] - dn) / (up - dn) - 0.5 if up - dn > 0 else 0.0
        if i >= 13:                                           # ta.wpr(14)
            mx, mn = h[i - 13:i + 1].max(), lo[i - 13:i + 1].min()
            out["wpr"][i] = (100 * (c[i] - mx) / (mx - mn) if mx != mn else -50.0) + 50
            ups = dns = 0.0                                   # ta.mfi(hlc3, 14)
            for j in range(i - 13, i + 1):
                ch = hlc3[j] - hlc3[j - 1] if j > 0 else math.nan
                ups += v[j] * (0.0 if ch <= 0 else hlc3[j])
                dns += v[j] * (0.0 if ch >= 0 else hlc3[j])
            out["mfi"][i] = (100 - 100 / (1 + ups / dns) if dns != 0 else 50.0) - 50
        if i >= 27:                                           # the ultimate oscillator 7 / 14 / 28
            pc = [c[j - 1] if j > 0 else c[j] for j in range(i - 27, i + 1)]
            bp = [c[j] - min(lo[j], p) for j, p in zip(range(i - 27, i + 1), pc)]
            tr = [max(h[j], p) - min(lo[j], p) for j, p in zip(range(i - 27, i + 1), pc)]
            parts = [sum(bp[-k:]) / sum(tr[-k:]) if sum(tr[-k:]) > 0 else 0.5 for k in (7, 14, 28)]
            out["uo"][i] = 100 * (4 * parts[0] + 2 * parts[1] + parts[2]) / 7 - 50
        if i >= 100:                                          # the VPVR point of control: 100 bars, 24 rows
            hi, lw = h[i - 99:i + 1].max(), lo[i - 99:i + 1].min()
            rg = hi - lw
            if rg > 0:
                bins = [0.0] * 24
                for j in range(100):
                    x = hlc3[i - j]
                    k = min(max(int(math.floor((x - lw) / rg * 24)), 0), 23)
                    bins[k] += v[i - j]
                poc = lw + (bins.index(max(bins)) + 0.5) * rg / 24
                out["poc"][i] = (c[i] - poc) / atr[i] if atr[i] > 0 else 0.0
    return out


def test_the_15_inputs_and_the_3hap_histogram_are_the_scripts():
    o, h, lo, c, v = walk(1500, seed=73)
    P = FT.q15_parts(o, h, lo, c, v)
    assert tuple(P) == FT.Q15_KEYS and len(FT.Q15_KEYS) == 15
    L = _loops_q15(o, h, lo, c, v)
    for k in ("bb", "wpr", "mfi", "uo", "poc"):
        assert np.allclose(P[k][300:], L[k][300:], atol=1e-8), k
    # TSI 5 / 20 (EMA 20 then EMA 5 of the change, over the same of its size) and its EMA 5
    pc = np.r_[np.nan, np.diff(c)]
    tsi = _ema(_ema(pc, 20), 5) / _ema(_ema(np.abs(pc), 20), 5)
    assert np.allclose(P["smio"][300:], (tsi - _ema(tsi, 5))[300:], atol=1e-10)
    vs = _ema(v, 10)
    vo = 100 * (_ema(v, 5) - vs) / vs
    sd = pd.Series(vo).rolling(100).std(ddof=0).to_numpy()
    sg = np.sign(np.r_[np.full(5, 0.0), c[5:] - c[:-5]])
    vt = np.where(sd > 0, np.tanh(np.clip(vo / np.where(sd > 0, sd, 1), -10, 10)), 0.0)
    assert np.allclose(P["vo"][300:], _ema(np.nan_to_num(np.maximum(vt, 0) * sg), 3)[300:], atol=1e-10)
    q = _ema(100 * sum(P[k] if k == "vo" else _ema(_zsq(P[k], 100), 3) for k in FT.Q15_KEYS) / 15, 3)
    assert np.allclose(FT.q15_line(o, h, lo, c, v)[300:], q[300:], atol=1e-8)
    # 3합: ① the 'ALL + OBV6 MACD' line, ② 2 x (EMA RSI - 50), ③ the 15종 line; mean, signal EMA 9, histogram
    H = FT.h3_pane(o, h, lo, c, v)
    avg = (FT.h6_pane(h, lo, c, v)["macd"] + 2 * (FT.ema_rsi(c) - 50) + q) / 3
    sig = _ema(avg, 9)
    hist = avg - sig
    assert np.allclose(H["hist"][300:], hist[300:], atol=1e-8)
    for i in range(300, len(c)):                              # ta.crossover / ta.crossunder of the histogram and 0
        assert H["cross"][i] == (1 if hist[i] > 0 and hist[i - 1] <= 0 else -1 if hist[i] < 0 and hist[i - 1] >= 0 else 0)
    assert {1, -1} <= set(int(x) for x in H["cross"][300:])


def test_a_read_on_a_prefix_is_the_pane_at_that_bar_and_1499_bars_are_enough():
    o, h, lo, c, v = walk(2600, seed=74)
    T, O, H = FT.tmacd_pane(h, lo, c, v), FT.o4_pane(h, lo, c, v), FT.h3_pane(o, h, lo, c, v)
    for i in range(400, 2600, 131):
        s = slice(0, i + 1)
        t = FT.tmacd_state(h[s], lo[s], c[s], v[s])
        assert t["trend"] == T["trend"][i] and t["yellow"] == bool(T["yellow"][i])
        ob = FT.o4_state(h[s], lo[s], c[s], v[s])
        assert (ob["turn"], ob["side"], ob["col"]) == (O["turn"][i], O["side"][i], O["col"][i])
        assert FT.h3_state(o[s], h[s], lo[s], c[s], v[s])["cross"] == H["cross"][i]
    for end in (2000, 2599):
        s = slice(end - 1498, end + 1)
        t = FT.tmacd_pane(h[s], lo[s], c[s], v[s])
        assert t["hist"][-1] == pytest.approx(T["hist"][end], abs=1e-6) and t["trend"][-1] == T["trend"][end]
        assert FT.o4_pane(h[s], lo[s], c[s], v[s])["ac"][-1] == pytest.approx(O["ac"][end], abs=1e-6)
        x = FT.h3_pane(o[s], h[s], lo[s], c[s], v[s])
        assert x["hist"][-1] == pytest.approx(H["hist"][end], abs=1e-6) and x["cross"][-1] == H["cross"][end]


# ====================================================================== mixchop: trend "macd", rules "o4h" and "h3x"
def _tm(trend, hist=None, yellow=False):
    return {"trend": trend, "hist": 3.2 * trend if hist is None else hist, "macd": 10.0 * trend, "yellow": yellow}


def _judge(monkeypatch, rule, tm, o4=None, h3=None):
    b = frame(400, tf_ms=M.MIN15, vol=0.002)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 30)
    monkeypatch.setattr(FT, "tmacd_state", lambda *a: tm)
    monkeypatch.setattr(FT, "bar_state", lambda *a: pytest.fail("the trend bar is not this trend"))
    monkeypatch.setattr(FT, "last_trend", lambda *a: pytest.fail("the four votes are not this trend"))
    if o4 is not None:
        monkeypatch.setattr(FT, "o4_state", lambda *a: o4)
    if h3 is not None:
        monkeypatch.setattr(FT, "h3_state", lambda *a: h3)
    return M.Bot.judge(rule, co, b, b.iloc[0:0], T0, M.MIN15, "macd")


def _o4(side, turn=None, ac=None):
    turn = side if turn is None else turn
    return {"ac": (-3.0 if turn > 0 else 3.0) if ac is None else ac, "col": turn, "turn": turn, "side": side, "macd": 5.0}


def test_h3x_on_the_trend_macd(monkeypatch):
    ev = _judge(monkeypatch, "h3x", _tm(1), h3={"cross": 1, "hist": 2.5, "avg": 9.0})
    assert ev["side"] == 1 and ev["why"] == "" and ev["trend_mode"] == "macd" and (ev["x0"], ev["h3"]) == (1, 2.5)
    assert (ev["tmacd"], ev["tmacd_line"], ev["tyellow"]) == (3.2, 10.0, False) and "bar" not in ev and "votes" not in ev
    # "노란 히스토그램이 나와도 … 0선 위에 있으면 상승추세로 보고 진입가능": a yellow bar over 0 is still up
    assert _judge(monkeypatch, "h3x", _tm(1, yellow=True), h3={"cross": 1, "hist": 2.5, "avg": 9.0})["side"] == 1
    assert _judge(monkeypatch, "h3x", _tm(-1, yellow=True), h3={"cross": -1, "hist": -2.5, "avg": -9.0})["side"] == -1
    no = _judge(monkeypatch, "h3x", _tm(-1, yellow=True), h3={"cross": 1, "hist": 2.5, "avg": 9.0})
    assert no["side"] == 0 and no["why"] == "추세 MACD 히스토그램 0선 아래 하락(-3.20, 노란 막대): 신호 롱와 반대"
    zero = _judge(monkeypatch, "h3x", _tm(0, hist=0.0), h3={"cross": 1, "hist": 2.5, "avg": 9.0})
    assert zero["side"] == 0 and zero["why"] == "추세 MACD 히스토그램 0선(진입 안 함, +0.00)"
    none = _judge(monkeypatch, "h3x", _tm(1), h3={"cross": 0, "hist": 0.5, "avg": 9.0})
    assert none["side"] == 0 and none["why"] == "3합 히스토그램 0선 돌파 없음"
    # the words (the entry's 근거 line, the signal lists)
    w = M.friend_words({**ev, "trend_tf": "30분"}, 1)
    assert w == "3합 히스토그램 0선 위로 돌파(히스토그램 2.5) · 추세 MACD 30분 히스토그램 0선 위 상승(+3.20)"
    assert M.reason_words({**ev, "trend_tf": "30분"}, 1).startswith("근거: 3합 히스토그램 0선 위로 돌파")
    row = M.board_row([ev], T0)
    assert {"tmacd", "tmacd_line", "tyellow", "x0", "h3", "trend_mode"} <= set(row) and row["rules"]["h3x"]["side"] == 1


def test_o4h_on_the_trend_macd(monkeypatch):
    ev = _judge(monkeypatch, "o4h", _tm(1), o4=_o4(1))
    assert ev["side"] == 1 and (ev["o4"], ev["o4_col"], ev["o4_turn"]) == (-3.0, 1, 1)
    assert _judge(monkeypatch, "o4h", _tm(-1, yellow=True), o4=_o4(-1))["side"] == -1
    against = _judge(monkeypatch, "o4h", _tm(-1), o4=_o4(1))
    assert against["side"] == 0 and against["why"].startswith("추세 MACD 히스토그램 0선 아래 하락(-3.20): 신호 롱와 반대")
    over = _judge(monkeypatch, "o4h", _tm(1), o4=_o4(0, turn=1, ac=1.5))
    assert over["side"] == 0 and over["why"] == "OBV 히스토그램 0선 위 양봉 전환(1.50): 롱은 0선 아래 양봉 전환만"
    under = _judge(monkeypatch, "o4h", _tm(-1), o4=_o4(0, turn=-1, ac=-1.5))
    assert under["why"] == "OBV 히스토그램 0선 아래 음봉 전환(-1.50): 숏은 0선 위 음봉 전환만"
    assert _judge(monkeypatch, "o4h", _tm(1), o4=_o4(0, turn=0, ac=0.2))["why"] == "OBV 히스토그램 양봉·음봉 전환 없음"
    w = M.friend_words({**ev, "trend_tf": "30분"}, 1)
    assert w == "OBV 히스토그램 0선 아래 양봉 전환(-3.00) · 추세 MACD 30분 히스토그램 0선 위 상승(+3.20)"
    sh = _judge(monkeypatch, "o4h", _tm(-1), o4=_o4(-1))
    assert M.friend_words({**sh, "trend_tf": "30분"}, -1).startswith("OBV 히스토그램 0선 위 음봉 전환(3.00) · ")
    assert M.RULE_KO["o4h"] == "OBV 히스토그램 전환(0선 아래 양봉 롱 · 0선 위 음봉 숏)" and M.RULE_KO["h3x"] == "3합 히스토그램 0선 돌파"
    assert {"o4h", "h3x"} <= set(M.FRIEND_RULES) and "macd" in M.TRENDS


def test_the_real_indicators_through_the_bot_and_the_30m_trend():
    """The trend is the 추세 MACD of the last 30m bar closed by the 15m close (no look ahead); the entry on the 15m bars."""
    r15, r30 = _pair(4000, 81)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    got = {"h3x": set(), "o4h": set()}
    seen_yellow = False
    for k in range(0, 600, 7):
        ce = T0 - k * M.MIN15
        b = M.bars_frame(r15, M.MIN15, ce).tail(1499).reset_index(drop=True)
        tb = M.bars_frame(r30, M.MIN30, ce).tail(1499).reset_index(drop=True)
        assert int(tb.open_ms.iloc[-1]) + M.MIN30 == ce // M.MIN30 * M.MIN30
        t = FT.tmacd_state(*(tb[x].to_numpy(float) for x in ("high", "low", "close", "volume")))
        o, h, lo, c, v = (b[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
        for rule in ("h3x", "o4h"):
            ev = M.Bot.judge(rule, co, b, tb, ce, M.MIN15, "macd", M.MIN30)
            assert ev["trend"] == t["trend"] and ev["tmacd"] == t["hist"] and ev["trend_tf"] == "30분"
            want = FT.h3_state(o, h, lo, c, v)["cross"] if rule == "h3x" else FT.o4_state(h, lo, c, v)["side"]
            assert ev["side"] in (0, want)
            if want and want == t["trend"] and ev["liq_ok"]:
                assert ev["side"] == want
            got[rule].add(ev["side"])
            seen_yellow |= bool(ev["tyellow"]) and ev["side"] != 0
    assert {1, -1} <= got["h3x"] | got["o4h"]


def test_the_signals_listing_check_and_start(tmp_path, monkeypatch, capsys):
    cfg = M.load_config(str(DEPLOY / "mixrange.paper.json"))
    r15, r30 = _pair(3000, 82)
    b = M.bars_frame(r15, M.MIN15, T0).tail(1499).reset_index(drop=True)
    tb = M.bars_frame(r30, M.MIN30, T0).tail(1499).reset_index(drop=True)
    TM = FT.tmacd_pane(*(tb[k].to_numpy(float) for k in ("high", "low", "close", "volume")))
    o, h, lo, c, v = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    t_close = tb.open_ms.to_numpy() + M.MIN30
    for rule in ("h3x", "o4h"):
        lines = M.friend_history(cfg.coins[0], b, rule, 10_000, M.MIN15, "macd", tb, M.MIN30)
        assert lines and all(" 추세 MACD 30분 히스토그램 0선" in x and "→" in x for x in lines)
        P = FT.h3_pane(o, h, lo, c, v) if rule == "h3x" else FT.o4_pane(h, lo, c, v)
        mark = P["cross"] if rule == "h3x" else P["turn"]
        side = P["cross"] if rule == "h3x" else P["side"]
        want = []
        for i in range(301, len(c)):
            if not mark[i]:
                continue
            j = int(np.searchsorted(t_close, int(b.open_ms.iloc[i]) + M.MIN15, side="right") - 1)
            tr = int(TM["trend"][j])
            want.append("X (롱은 0선 아래 양봉 전환, 숏은 0선 위 음봉 전환만)" if not side[i] else
                        "롱 진입" if side[i] == tr == 1 else "숏 진입" if side[i] == tr == -1 else "X (추세 다름)")
        assert len(lines) == len(want)
        for ln, w in zip(lines, want):
            assert ln.endswith(w) or ("X (손절 폭" in ln and "진입" in w), (ln, w)
        if rule == "h3x":
            assert all("3합 히스토그램 0선 " in x for x in lines)
        else:
            assert all("OBV 히스토그램 0선 " in x and " 전환(" in x for x in lines)
            assert any(x.endswith("X (롱은 0선 아래 양봉 전환, 숏은 0선 위 음봉 전환만)") for x in lines)
    # ``signals``: the 30m trend named once per rule and coin
    src = {"15m": r15, "30m": r30}
    monkeypatch.setattr(M, "binance_fetch", lambda base: lambda s, tf, n: [r for r in src[tf] if r[0] < T0][-n:])
    monkeypatch.setattr(M.time, "time", lambda: T0 / 1000 + 60)
    assert M.cmd_signals(argparse.Namespace(config=str(DEPLOY / "mixrange.paper.json"), n=3)) == 0
    out = capsys.readouterr().out
    assert out.count("  -- 3합 히스토그램 0선 돌파 (추세 30분: 추세 MACD 히스토그램(0선 위 상승 · 0선 아래 하락, 노란 막대도 같음))") == 6
    # the check's rules line
    monkeypatch.setattr(M, "public_spec", lambda cfg: lambda sym: {"status": "Trading", "max_leverage": 50.0, "min_qty": 0.001,
                                                                  "qty_step": 0.001, "min_notional": 5.0, "tick": 0.01})
    assert M.cmd_check(argparse.Namespace(config=str(DEPLOY / "mixrange.paper.json"))) == 0
    assert ("매매법·손절: 3합 히스토그램 0선 돌파 · 손절 ATR 3배(모든 코인) · 신호 15분봉 · 추세: 30분봉 추세 MACD 히스토그램"
            "(0선 위 상승 · 0선 아래 하락)") in capsys.readouterr().out.splitlines()
    # the start message says the trend
    d = json.loads((DEPLOY / "mixrange.paper.json").read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "s.json"), log=str(tmp_path / "l.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN.STOP"))
    p = tmp_path / "c.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    c2 = M.load_config(str(p))
    msgs = []
    bot = M.Bot(c2, M.PaperBroker(100.0, c2.taker_fee), lambda s, tf, n: [], lambda: T0 + 5_000,
                notify=lambda lv, t: msgs.append(t), sleep=lambda s: None)
    bot.start()
    assert "매매법 3합 히스토그램 0선 돌파" in msgs[0] and "15분봉 마감마다 판단 (추세는 30분봉 추세 MACD 히스토그램)" in msgs[0]


def test_a_15m_close_in_the_loop_logs_the_turn_and_enters(tmp_path, monkeypatch):
    d = json.loads((DEPLOY / "mixbybit.paper.json").read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "state.json"), log=str(tmp_path / "log.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN.STOP"), no_weekend=False, us_open_pre_min=0, us_open_pause_min=0,
             macro_blackout_min=0)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    cfg = M.load_config(str(p))
    ce = T0 + M.MIN15
    rows = {"15m": [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in ce - M.MIN15 * np.arange(400, -1, -1)],
            "30m": [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in T0 - M.MIN30 * np.arange(400, -1, -1)]}

    def fake_eval(rule, co, b, close_ms, tf_ms=M.MIN30, trend="four", tb=None, trend_tf_ms=None):
        assert (rule, tf_ms, trend, trend_tf_ms) == ("o4h", M.MIN15, "macd", M.MIN30)
        turn = {"ETHUSDT": 1, "SOLUSDT": -1}.get(co.symbol, 0)
        side = 1 if co.symbol == "ETHUSDT" else 0
        return {"symbol": co.symbol, "close_ms": close_ms, "side": side, "rule": rule, "o4": -2.0 * turn or 0.3,
                "o4_col": turn, "o4_turn": turn, "why": "" if side else ("추세 MACD 히스토그램 0선 위 상승(+1.00): 신호 숏와 반대"
                                                                       if turn else "OBV 히스토그램 양봉·음봉 전환 없음"),
                "close": 10.0, "stop_dist": 0.1, "stop_pct": 1.0, "trend": 1, "trend_mode": "macd", "tf": "15분",
                "trend_tf": "30분", "tmacd": 1.0, "tmacd_line": 4.0, "tyellow": False}
    monkeypatch.setattr(M, "evaluate_friend", fake_eval)
    msgs = []
    bot = M.Bot(cfg, M.PaperBroker(100.0, cfg.taker_fee), lambda s, tf, n: rows[tf], lambda: ce + 5_000,
                notify=lambda lv, t: msgs.append(t), sleep=lambda s: None)
    bot.on_close(ce)
    assert bot.pos is not None and bot.pos.symbol == "ETHUSDT" and bot.pos.side == 1
    logged = [json.loads(x) for x in Path(cfg.log).read_text(encoding="utf-8").splitlines()]
    sig = {r["symbol"]: r for r in logged if r.get("kind") == "signal"}
    assert set(sig) == {"ETHUSDT", "SOLUSDT"}                     # a turn is logged even when the trend refused it
    assert sig["SOLUSDT"]["o4_turn"] == -1 and sig["SOLUSDT"]["side"] == 0
    assert bot.board["ETHUSDT"]["tmacd"] == 1.0 and bot.board["ETHUSDT"]["o4_turn"] == 1
    entry = next(m for m in msgs if "근거" in m)
    assert "근거: OBV 히스토그램 0선 아래 양봉 전환(-2.00) · 추세 MACD 30분 히스토그램 0선 위 상승(+1.00)" in entry


# ====================================================================== mixcheck
def test_the_morning_replay_counts_the_new_signals():
    for name, rule, key, words in (("mixrange.paper.json", "h3x", "h3s", "3합 히스토그램 0선 돌파"),
                                   ("mixbybit.paper.json", "o4h", "o4s", "OBV 히스토그램 양봉·음봉 전환")):
        cfg = M.load_config(str(DEPLOY / name))
        cfg.coins = cfg.coins[:1]
        r15, r30 = _pair(4000, 83)
        src = {"15m": r15, "30m": r30}

        def klines(symbol, tf, start, limit):
            return [r for r in src[tf] if r[0] >= start][:limit]
        day0 = T0 - 24 * HOUR
        log = []
        co = cfg.coins[0]
        for ce in range(day0 + M.MIN15, T0 + 1, M.MIN15):
            bb = M.bars_frame(r15, M.MIN15, ce).tail(M.BARS - 1).reset_index(drop=True)
            tb = M.bars_frame(r30, M.MIN30, ce).tail(M.BARS - 1).reset_index(drop=True)
            ev = M.Bot.judge(rule, co, bb, tb, ce, M.MIN15, "macd", M.MIN30)
            if ev.get("x0") or ev.get("o4_turn") or ev["side"]:
                log.append({"ts": ce + 5_000, "kind": "signal", **ev})
        assert log
        rp = MC.signal_replay(cfg, day0, T0, log, klines, obs=[[T0 + 3 * MIN, T0, None]], st_last=T0)
        assert rp["state"] == "ok" and rp["different"] == [] and rp["rules"] == [rule]
        assert rp[key] == len(log) and f"{words} {rp[key]}번" in MC.replay_lines(rp)[0]
        assert MC.signal_counts(log)[key] == len({(r["symbol"], r["close_ms"]) for r in log})
        flip = [dict(log[0], **({"x0": -int(log[0]["x0"])} if rule == "h3x" else {"o4_turn": -int(log[0]["o4_turn"])}))] + log[1:]
        rp3 = MC.signal_replay(cfg, day0, T0, flip, klines, obs=[[T0 + 3 * MIN, T0, None]], st_last=T0)
        assert [x["close_ms"] for x in rp3["different"]] == [log[0]["close_ms"]]
    assert MC.RULE_TAG["h3x"] == "(3합 히스토그램 0선 돌파)" and MC.RULE_TAG["o4h"] == "(OBV 히스토그램 전환)"
    assert MC.RULE_WHAT["h3x"] == "3합 히스토그램 0선 돌파" and MC.RULE_WHAT["o4h"] == "OBV 히스토그램 양봉·음봉 전환"


# ====================================================================== the configs
def test_three_bots_on_the_trend_macd():
    bots = {"bybit": ("mixbybit.live.json", "mixbybit.paper.json", ("o4h",)),
            "friend": ("mixchop.live.json", "mixchop.paper.json", ("h3x",)),
            "range": ("mixrange.live.json", "mixrange.paper.json", ("h3x",))}
    for key, (live, paper, rules) in bots.items():
        for name, mode in ((live, "mainnet"), (paper, "paper")):
            cfg = M.load_config(str(DEPLOY / name))
            assert (cfg.mode, cfg.trend, cfg.rules, cfg.symbols) == (mode, "macd", rules, SIX), name
            # "30분봉 추세 15분봉은 진입 바꾸지말고"
            assert (cfg.tf, cfg.trend_tf, cfg.trend_tf_ms) == ("15m", "30m", M.MIN30), name
            assert cfg.stop_atr == 3.0 and cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0}
            assert cfg.margin_frac == 0.4 and cfg.equity_floor_frac == 0
            assert {c.symbol: c.leverage for c in cfg.coins} == {**{s: 40 for s in SIX}, "ZECUSDT": 20}
    by = M.load_config(str(DEPLOY / "mixbybit.live.json"))
    assert "매매법 OBV 히스토그램 전환(0선 아래 양봉 롱 · 0선 위 음봉 숏)" in M.plan_words(by)
    assert "매매법 3합 히스토그램 0선 돌파" in M.plan_words(M.load_config(str(DEPLOY / "mixrange.live.json")))
    # a trend that is not one of the four is refused, the new one named
    p = Path(os.environ.get("TMPDIR", "/tmp")) / "bad-trend-1102.json"
    p.write_text(json.dumps({**json.loads((DEPLOY / "mixrange.live.json").read_text(encoding="utf-8")), "trend": "macd2"}),
                 encoding="utf-8")
    try:
        with pytest.raises(M.MixError, match="macd: 추세 MACD 히스토그램 0선 위 / 아래"):
            M.load_config(str(p))
    finally:
        p.unlink()
