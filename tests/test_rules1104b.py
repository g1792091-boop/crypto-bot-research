"""Owners 11-04, later: "15분봉30분봉 히스토 그램 추세가 같아야하고 5분봉에서 obv macd가 0선아래에서 양봉이 나오면 롱 진입
숏진입은 반대 조건으로". The two mix bots: the OBV histogram's turn on 5m bars (rule "o4h", tf "5m"), the 추세 MACD
histogram of the last closed 30m bar (trend_tf) and of the last closed 15m bar (trend_tf2) both on the signal's side,
the stop the owners' fixed 15m ATR x 3 (stop_tf). The rule, its refusals, its words, the config, the bot's reads, the
signals listing and the morning replay."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from paperbot import friendtrend as FT
from paperbot import mixcheck as MC
from paperbot import mixchop as M

sys.path.insert(0, os.path.dirname(__file__))

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
HOUR = 3_600_000


def _three(n5, seed, end_ms=T0, vol=0.0012):
    """5m kline rows ending at ``end_ms`` and the 15m / 30m rows made of them (Binance's bars are sums of the 5m ones)."""
    rng = np.random.default_rng(seed)
    t = end_ms - M.MIN5 * np.arange(n5, 0, -1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, vol, n5)))
    o = np.r_[c[0], c[:-1]]
    h, lo = np.maximum(o, c) * 1.0007, np.minimum(o, c) * 0.9993
    v = rng.uniform(100, 1000, n5)
    r5 = [[int(t[i]), o[i], h[i], lo[i], c[i], v[i]] for i in range(n5)]

    def agg(ms):
        k = ms // M.MIN5
        out = []
        for i in range(n5 - k + 1):
            if t[i] % ms == 0:
                s = slice(i, i + k)
                out.append([int(t[i]), o[i], float(h[s].max()), float(lo[s].min()), c[i + k - 1], float(v[s].sum())])
        return out
    return r5, agg(M.MIN15), agg(M.MIN30)


def _frames(r5, r15, r30, ce):
    tail = lambda df: df.tail(M.BARS - 1).reset_index(drop=True)  # noqa: E731
    return (tail(M.bars_frame(r5, M.MIN5, ce)), tail(M.bars_frame(r15, M.MIN15, ce)), tail(M.bars_frame(r30, M.MIN30, ce)))


def _tm(trend, hist=None, yellow=False):
    return {"trend": trend, "hist": 3.2 * trend if hist is None else hist, "macd": 10.0 * trend, "yellow": yellow}


def _o4(side):
    return {"ac": -3.0 if side > 0 else 3.0, "col": side, "turn": side, "side": side, "macd": 5.0}


def _cfg_file(tmp_path, name="mixrange.paper.json", **over):
    d = json.loads((DEPLOY / name).read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "s.json"), log=str(tmp_path / "l.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN"), telegram=False, **over)
    p = tmp_path / f"c{len(list(tmp_path.glob('c*.json')))}.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


# ====================================================================== the configs
def test_the_four_configs_run_the_5m_turn_with_the_30m_and_15m_trends_and_the_15m_stop():
    for name in ("mixrange.live.json", "mixrange.paper.json", "mixchop.live.json", "mixchop.paper.json"):
        raw = json.loads((DEPLOY / name).read_text(encoding="utf-8"))
        cfg = M.load_config(str(DEPLOY / name))
        assert (cfg.rules, cfg.tf, cfg.trend, cfg.trend_tf, cfg.trend_tf2, cfg.stop_tf, cfg.trend_both) == \
            (("o4h",), "5m", "macd", "30m", "15m", "15m", False), name
        assert (cfg.tf_ms, cfg.trend_tf_ms, cfg.trend_tf2_ms, cfg.stop_tf_ms) == (M.MIN5, M.MIN30, M.MIN15, M.MIN15)
        assert (cfg.trend2_ko, cfg.stop_ko, cfg.stop_atr, cfg.margin_frac) == ("15분", "15분", 3.0, 0.4)
        # the fixed rules as they were (owners: "고정규칙은 건들지마")
        assert raw["ladder"] == {"trigger": 10, "lock": 8, "step": 2} and raw["ladder_basis"] == "gross"
        assert raw["coins"] == {"BTCUSDT": {"leverage": 40}, "SOLUSDT": {"leverage": 40}, "ZECUSDT": {"leverage": 20}}
        assert "trend_both" not in raw


def test_the_config_refusals(tmp_path):
    for bad in ({"trend_tf2": "7m"}, {"trend_tf2": "30m"}, {"stop_tf": "2h"}, {"trend_tf2": "15m", "trend_both": True},
                {"tf": "15m", "trend_tf2": "5m"}):
        with pytest.raises(M.MixError):
            M.load_config(str(_cfg_file(tmp_path, **bad)))
    # (ignored where it means nothing, as trend_tf / trend_both)
    assert M.load_config(str(_cfg_file(tmp_path, trend="bar"))).trend_tf2 is None
    same = M.load_config(str(_cfg_file(tmp_path, trend_tf2="5m", stop_tf="5m")))
    assert (same.trend_tf2, same.trend_both, same.stop_tf, same.trend2_ko) == (None, True, None, "5분")


# ====================================================================== the rule
def _judge(monkeypatch, t30, t15, signal=1, seed=5):
    r5, r15, r30 = _three(4800, seed)
    ce = T0
    b5, b15, b30 = _frames(r5, r15, r30, ce)
    seen = []

    def tm(h, l, c, v):
        seen.append(len(c))
        return t30 if len(seen) == 1 else t15
    monkeypatch.setattr(FT, "tmacd_state", tm)
    monkeypatch.setattr(FT, "o4_state", lambda *a: _o4(signal))
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    ev = M.Bot.judge("o4h", co, b5, b30, ce, M.MIN5, "macd", M.MIN30, False, tb2=b15, trend_tf2_ms=M.MIN15,
                     sb=b15, stop_tf_ms=M.MIN15)
    return ev, seen, (b5, b15, b30)


def test_both_trends_on_the_signals_side_enter_with_the_15m_atr_stop(monkeypatch):
    ev, seen, (b5, b15, b30) = _judge(monkeypatch, _tm(1), _tm(1, 0.8))
    assert ev["side"] == 1 and ev["why"] == "" and seen == [len(b30), len(b15)]      # the 30m first, then the 15m
    assert (ev["tf"], ev["trend_tf"], ev["trend_tf2"], ev["stop_tf"]) == ("5분", "30분", "15분", "15분")
    assert (ev["tsig"], ev["tmacd_sig"]) == (1, 0.8)
    a15 = float(M.atr(b15.high, b15.low, b15.close, 14)[-1])
    a5 = float(M.atr(b5.high, b5.low, b5.close, 14)[-1])
    assert ev["stop_dist"] == pytest.approx(3 * a15) and ev["close"] == pytest.approx(float(b5.close.iloc[-1]))
    assert a15 > 1.3 * a5                                                             # (not the 5m ATR)
    line = M.reason_words({**ev, "close_ms": T0}, 1)
    assert "추세 MACD 30분 히스토그램 0선 위 상승(+3.20) · 추세 MACD 15분 히스토그램 0선 위 상승(+0.80)" in line
    short, _s, _f = _judge(monkeypatch, _tm(-1), _tm(-1, -0.5, yellow=True), signal=-1)
    assert short["side"] == -1


def test_the_15m_against_the_30m_does_not_enter(monkeypatch):
    ev, _s, _f = _judge(monkeypatch, _tm(1), _tm(-1, -0.4))
    assert ev["side"] == 0 and ev["why"] == "추세 MACD 15분 히스토그램 0선 아래 하락(-0.40): 30분 추세(상승)와 같은 쪽 아님"
    first, _s, _f = _judge(monkeypatch, _tm(-1), _tm(1))
    assert first["why"].startswith("추세 MACD 30분 히스토그램 0선 아래 하락")              # the 30m said first
    none, _s, _f = _judge(monkeypatch, _tm(1), _tm(1), signal=0)
    assert none["side"] == 0 and none["why"] == "OBV 히스토그램 양봉·음봉 전환 없음"


def test_a_15m_bar_not_closed_yet_is_not_read(monkeypatch):
    r5, r15, r30 = _three(4800, 6)
    ce = T0 + M.MIN5                                     # 5 minutes into a 15m bar: the 15m bar closed at T0 is the last
    b5, b15, b30 = _frames(r5, r15, r30, T0)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    b5n = M.bars_frame(r5 + [[T0, 1, 1, 1, 1, 1]], M.MIN5, ce)
    old = b15.iloc[:-1]                                  # its last bar closed before T0: not what the bot reads at ce
    ev = M.evaluate_friend("o4h", co, b5n, ce, M.MIN5, "macd", tb=b30, trend_tf_ms=M.MIN30, tb2=old, trend_tf2_ms=M.MIN15)
    assert ev["side"] == 0 and ev["why"] == "추세 15분봉이 아직 없음"


# ====================================================================== the bot's reads and words
def test_the_bot_reads_the_15m_once_and_passes_it(tmp_path, monkeypatch):
    p = _cfg_file(tmp_path, no_weekend=False, us_open_pre_min=0, us_open_pause_min=0, macro_blackout_min=0)
    cfg = M.load_config(str(p))
    ce = T0 + M.MIN5
    rows = {"5m": [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in ce - M.MIN5 * np.arange(1500, -1, -1)],
            "15m": [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in T0 - M.MIN15 * np.arange(1500, -1, -1)],
            "30m": [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in T0 - M.MIN30 * np.arange(1500, -1, -1)]}
    asked, got = [], []

    def fetch(sym, tf, n):
        asked.append((sym, tf))
        return rows[tf]

    def fake_eval(rule, co, b, close_ms, tf_ms=M.MIN30, trend="four", tb=None, trend_tf_ms=None, trend_both=False,
                  tb2=None, trend_tf2_ms=None, sb=None, stop_tf_ms=None):
        got.append((co.symbol, tf_ms, trend_tf_ms, trend_tf2_ms, stop_tf_ms, trend_both, sb is tb2))
        assert int(b.open_ms.iloc[-1]) + M.MIN5 == close_ms and int(tb.open_ms.iloc[-1]) + M.MIN30 == T0
        assert int(tb2.open_ms.iloc[-1]) + M.MIN15 == T0                           # the last 15m bar closed by ce
        side = 1 if co.symbol == "SOLUSDT" else 0
        return {"symbol": co.symbol, "close_ms": close_ms, "side": side, "rule": rule, "o4": -2.0, "o4_turn": side,
                "o4_col": side, "why": "" if side else "OBV 히스토그램 양봉·음봉 전환 없음", "close": 10.0, "stop_dist": 0.1,
                "stop_pct": 1.0, "trend": 1, "trend_mode": "macd", "tf": "5분", "trend_tf": "30분", "tmacd": 1.0,
                "tmacd_line": 4.0, "tyellow": False, "trend_tf2": "15분", "tsig": 1, "tmacd_sig": 0.5, "tyellow_sig": False,
                "stop_tf": "15분"}
    monkeypatch.setattr(M, "evaluate_friend", fake_eval)
    msgs = []
    bot = M.Bot(cfg, M.PaperBroker(100.0, cfg.taker_fee), fetch, lambda: ce + 5_000, notify=lambda lv, t: msgs.append(t),
                sleep=lambda s: None)
    bot.start()
    assert "5분봉 마감마다 판단 (추세는 30분봉 추세 MACD 히스토그램 + 15분봉도 같은 쪽일 때만 · 손절은 15분봉 ATR)" in msgs[0]
    bot.on_close(ce)
    assert got == [(s, M.MIN5, M.MIN30, M.MIN15, M.MIN15, False, True) for s in ("BTCUSDT", "SOLUSDT", "ZECUSDT")]
    assert sorted(asked) == sorted([(s, tf) for s in ("BTCUSDT", "SOLUSDT", "ZECUSDT") for tf in ("5m", "30m", "15m")])
    assert bot.pos is not None and bot.pos.symbol == "SOLUSDT"
    entry = next(m for m in msgs if "롱 진입" in m)
    assert "· 추세 MACD 30분 히스토그램 0선 위 상승(+1.00) · 추세 MACD 15분 히스토그램 0선 위 상승(+0.50)" in entry


def test_the_check_line(tmp_path, monkeypatch, capsys):
    p = _cfg_file(tmp_path)
    monkeypatch.setattr(M, "public_spec", lambda c: lambda sym: {"status": "Trading", "max_leverage": 50.0, "min_qty": 0.001,
                                                                "qty_step": 0.001, "min_notional": 5.0, "tick": 0.01})
    r5, r15, r30 = _three(800, 7)
    src = {"5m": r5, "15m": r15, "30m": r30}
    asked = []

    def fetch(base):
        def f(s, tf, n):
            asked.append(tf)
            return [r for r in src[tf] if r[0] < T0][-n:]
        return f
    monkeypatch.setattr(M, "binance_fetch", fetch)
    monkeypatch.setattr(M.time, "time", lambda: T0 / 1000 + 60)
    assert M.cmd_check(argparse.Namespace(config=str(p))) == 0
    out = capsys.readouterr().out
    assert ("매매법·손절: OBV 히스토그램 전환(0선 아래 양봉 롱 · 0선 위 음봉 숏) · 손절 15분봉 ATR 3배(모든 코인) · 신호 5분봉 · "
            "추세: 30분봉 추세 MACD 히스토그램(0선 위 상승 · 0선 아래 하락) + 15분봉 추세 MACD도 같은 쪽일 때만") in out
    assert set(asked) == {"15m"}                         # the stop size the check shows: the 15m ATR


# ====================================================================== the signals listing and the morning replay
def test_the_signal_list_agrees_with_the_bot(monkeypatch):
    r5, r15, r30 = _three(4800, 11)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    b5, b15, b30 = _frames(r5, r15, r30, T0)
    lines = M.friend_history(co, b5, "o4h", 80, M.MIN5, "macd", b30, M.MIN30, False, b15, M.MIN15, b15, M.MIN15)
    assert lines and all(" · 15분 히스토그램 " in ln for ln in lines)
    assert any(ln.endswith("X (15분 추세 다름)") for ln in lines) and any(ln.endswith("진입") for ln in lines)
    for ln in lines:
        hhmm = ln.split(" KST")[0]
        ce = next(int(t) + M.MIN5 for t in b5.open_ms if M.kst(int(t) + M.MIN5) == hhmm)
        f5, f15, f30 = (b[b.open_ms + ms <= ce].reset_index(drop=True) for b, ms in ((b5, M.MIN5), (b15, M.MIN15), (b30, M.MIN30)))
        ev = M.evaluate_friend("o4h", co, f5, ce, M.MIN5, "macd", tb=f30, trend_tf_ms=M.MIN30, tb2=f15, trend_tf2_ms=M.MIN15,
                               sb=f15, stop_tf_ms=M.MIN15)
        assert (ev["side"] != 0) == ln.endswith("진입"), (ln, ev["why"])
        assert f"손절폭 {ev['stop_dist'] / ev['close'] * 100:.2f}%" in ln                 # (the 15m ATR x 3)


def test_the_morning_replay_reads_the_same_bars():
    cfg = M.load_config(str(DEPLOY / "mixrange.paper.json"))
    cfg.coins = cfg.coins[:1]
    r5, r15, r30 = _three(5200, 83)
    src = {"5m": r5, "15m": r15, "30m": r30}

    def klines(symbol, tf, start, limit):
        return [r for r in src[tf] if r[0] >= start][:limit]
    day0 = T0 - 4 * HOUR
    co = cfg.coins[0]
    log = []
    for ce in range(day0 + M.MIN5, T0 + 1, M.MIN5):
        b5, b15, b30 = _frames(r5, r15, r30, ce)
        ev = M.Bot.judge("o4h", co, b5, b30, ce, M.MIN5, "macd", M.MIN30, False, tb2=b15, trend_tf2_ms=M.MIN15,
                         sb=b15, stop_tf_ms=M.MIN15)
        if ev.get("o4_turn") or ev["side"]:
            log.append({"ts": ce + 5_000, "kind": "signal", **ev})
    assert log
    rp = MC.signal_replay(cfg, day0, T0, log, klines, obs=[[T0 + 3 * 60_000, T0, None]], st_last=T0)
    assert rp["state"] == "ok" and rp["different"] == [] and rp["rules"] == ["o4h"]
    flip = [dict(log[0], o4_turn=-int(log[0]["o4_turn"]))] + log[1:]
    rp2 = MC.signal_replay(cfg, day0, T0, flip, klines, obs=[[T0 + 3 * 60_000, T0, None]], st_last=T0)
    assert [x["close_ms"] for x in rp2["different"]] == [log[0]["close_ms"]]
