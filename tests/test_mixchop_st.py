"""The friend bot's second rule (owners 10-26, paperbot/mixchop.py evaluate_st, ``rules`` / ``stop_atr``): TradingView's
Supertrend and Stoch RSI, the same answers as the research that chose it (research/mixchop_st/study.py new_signals) on
every close of the bot's 1,500-bar window, the rule order on one coin, the stop multiple of both rules, the words.
Owners 10-27: Stoch RSI 14/11/4/6 (was %D 5) and MOM(10) of the 30m above / below 0 (study.NEW)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from paperbot import mixchop as M

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "mixchop_st"))
import study as S  # noqa: E402


def _ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 1_000_000)


def _walk(n: int, seed: int) -> np.ndarray:
    """30m rows [open_ms, open, high, low, close]: a random walk with trending stretches (so the supertrends turn)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.0015, n // 150 + 1), 150)[:n]
    ret = drift + rng.normal(0, 0.004, n)
    c = 100.0 * np.exp(np.cumsum(ret))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    t = _ms("2026-01-01") + np.arange(n) * M.MIN30
    return np.column_stack([t, o, h, l, c])


def _hours(a30: np.ndarray) -> np.ndarray:
    """1h rows from pairs of 30m rows (the first starts on the hour)."""
    a = a30[: len(a30) // 2 * 2].reshape(-1, 2, 5)
    return np.column_stack([a[:, 0, 0], a[:, 0, 1], a[:, :, 2].max(1), a[:, :, 3].min(1), a[:, 1, 4]])


def _frame(a: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(a, columns=["open_ms", "open", "high", "low", "close"])
    df["open_ms"] = df.open_ms.astype(np.int64)
    return df


def test_supertrend_is_tradingviews():
    spec = importlib.util.spec_from_file_location("pine_indicators",
                                                  ROOT / "third_party/sweep/harness/vendor/pine_indicators.py")
    PI = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(PI)
    a = _walk(3000, 1)
    for f in (3.0, 6.0):
        line, up = M.supertrend(a[:, 2], a[:, 3], a[:, 4], 14, f)
        l2, d2 = PI.exchange_supertrend(a[:, 2], a[:, 3], a[:, 4], 14, f)
        # the first ~100 bars differ by the starting direction only (TradingView starts "down"); the bot reads 1,500
        assert (up[200:] == (d2[200:] == 1)).all()
        assert np.allclose(line[200:], l2[200:])


@pytest.mark.parametrize("seed", [2, 3])
def test_every_close_answers_as_the_research(seed):
    a30 = _walk(2400, seed)
    a1h = _hours(a30)
    co = M.Coin("SOLUSDT", 8.0, 3.0, 150.0, 40)
    ce_all = a30[:, 0].astype(np.int64) + M.MIN30
    want = S.new_signals(co, a30, a1h, S.NEW, int(ce_all[1700]), int(ce_all[-1]))
    df30, df1h = _frame(a30), _frame(a1h)
    seen = 0
    for i in range(1700, len(a30)):
        ce = int(ce_all[i])
        b30 = df30.iloc[i - 1498:i + 1].reset_index(drop=True)
        b1h = df1h[df1h.open_ms + M.H1 <= ce].tail(1499).reset_index(drop=True)
        ev = M.evaluate_st(co, b30, b1h, ce)
        w = want.get(ce)
        if w is None:
            assert ev["side"] == 0, (i, ev)
            continue
        e2 = S.with_stop(w, co, "atr")                                # the research's stop and liquidation guard
        assert ev["side"] == e2["side"], (i, ev, e2)
        assert ev["stop_dist"] == pytest.approx(e2["stop_dist"], rel=1e-6)
        seen += 1
    assert seen >= 3                                                  # the walk really fired the rule


def _cfg(tmp_path, **extra):
    raw = {"mode": "paper", "state": str(tmp_path / "state.json"), "log": str(tmp_path / "log.jsonl"),
           "start_equity": 50.0, "kill_file": str(tmp_path / "STOP"), "own_stop_file": str(tmp_path / "MIX.STOP"),
           "telegram": False, "coins": {"SOLUSDT": {}, "ETHUSDT": {}}, "max_notional_usd": 10000, "margin_frac": 0.4,
           "ladder": {"trigger": 12, "lock": 10, "step": 5}, "ladder_every_s": 60, **extra}
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(raw))
    return M.load_config(str(p))


def test_rules_and_stop_atr_in_the_config(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.rules == ("mix",) and cfg.stop_atr is None
    assert [c.sl_atr for c in cfg.coins] == [2.0, 1.5]                # the coins' own multiples, as before
    cfg = _cfg(tmp_path, rules=["mix", "st"], stop_atr=3)
    assert cfg.rules == ("mix", "st") and cfg.stop_atr == 3.0 and [c.sl_atr for c in cfg.coins] == [3.0, 3.0]
    for bad in ({"rules": []}, {"rules": ["mix", "mix"]}, {"rules": ["x"]}, {"rules": "st"}, {"stop_atr": 0.1},
                {"stop_atr": True}, {"stop_atr": "3"}):
        with pytest.raises(M.MixError):
            _cfg(tmp_path, **bad)


def _bars_rows(start_ms, n, px=100.0):
    return [[start_ms + i * M.MIN30, px, px + 0.5, px - 0.5, px] for i in range(n)]


def _fake(rule, side, **kv):
    def ev(co, b30, b1h, ce):
        return {"symbol": co.symbol, "close_ms": ce, "side": side, "why": "" if side else "x", "rule": rule,
                "close": 100.0, "atr": 0.5, "stop_dist": 0.5 * co.sl_atr, "stop_pct": 0.5 * co.sl_atr,
                "avg_rsi_30m": 60, "avg_rsi_1h": 55, "k": 30.1, "d": 25.2, "rsi26_30m": 56.0, "rsi26_1h": 54.0,
                "cross": "gold" if rule == "st" else "", "to_cyan": rule == "mix" and side > 0, **kv}
    return ev


@pytest.mark.parametrize("mix_side,st_side,rule", [(1, 1, "mix"), (0, -1, "st"), (-1, 0, "mix")])
def test_the_friends_rule_answers_first_on_one_coin(tmp_path, monkeypatch, mix_side, st_side, rule):
    cfg = _cfg(tmp_path, rules=["mix", "st"], stop_atr=3)
    close = _ms("2026-10-27 01:00")
    monkeypatch.setattr(M, "evaluate", _fake("mix", mix_side))
    monkeypatch.setattr(M, "evaluate_st", _fake("st", st_side))
    said = []
    fetch = lambda s, tf, n: _bars_rows(close - 400 * M.MIN30, 403) if tf == "30m" else []   # noqa: E731
    bot = M.Bot(cfg, M.PaperBroker(50.0, 0.0), fetch, lambda: close + 5000, notify=lambda lv, t: said.append(t),
                sleep=lambda s: None)
    bot.start()
    assert "매매법 친구 매매법 + 슈퍼트렌드·스톡RSI(같은 봉이면 친구 매매법 먼저)" in said[0]
    assert "손절 ATR 3배(모든 코인)" in said[0]
    bot.on_close(close)
    p = bot.pos
    want_side = mix_side if rule == "mix" else st_side
    assert p is not None and p.symbol == "SOLUSDT" and p.side == want_side
    assert p.stop_dist == pytest.approx(1.5) and p.stop == pytest.approx(100.0 - want_side * 1.5)   # ATR 0.5 x 3
    rows = [json.loads(x) for x in open(cfg.log)]
    (en,) = [r for r in rows if r["kind"] == "entry"]
    assert en["why"]["rule"] == rule
    entry_msg = next(t for t in said if "진입" in t and "근거" in t)
    if rule == "st":
        assert "근거(슈퍼트렌드·스톡RSI): 슈퍼트렌드 14/3·14/6 하락 · 스톡RSI 데드크로스(K 30.1 / D 25.2)" in entry_msg
    else:
        assert "근거(친구 매매법): " in entry_msg and "평균 RSI 60" in entry_msg
    sig = [r for r in rows if r["kind"] == "signal"]
    assert {r["rule"] for r in sig} >= {"st"}                          # the cross is logged even when not taken


def test_the_second_rule_alone_and_its_words(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, rules=["st"])
    assert cfg.rules == ("st",) and [c.sl_atr for c in cfg.coins] == [2.0, 1.5]
    close = _ms("2026-10-27 01:00")
    monkeypatch.setattr(M, "evaluate", lambda *a: pytest.fail("the friend's rule is off"))
    monkeypatch.setattr(M, "evaluate_st", _fake("st", 1))
    said = []
    fetch = lambda s, tf, n: _bars_rows(close - 400 * M.MIN30, 403) if tf == "30m" else []   # noqa: E731
    bot = M.Bot(cfg, M.PaperBroker(50.0, 0.0), fetch, lambda: close + 5000, notify=lambda lv, t: said.append(t),
                sleep=lambda s: None)
    bot.start()
    bot.on_close(close)
    assert bot.pos is not None and bot.pos.side == 1
    msg = next(t for t in said if "근거" in t)
    assert "근거: 슈퍼트렌드 14/3·14/6 상승 · 스톡RSI 골든크로스" in msg      # one rule: no name in front


def test_a_real_answer_without_a_cross_or_with_failing_conditions():
    a30 = _walk(2000, 4)
    a1h = _hours(a30)
    co = M.Coin("SOLUSDT", 8.0, 3.0, 150.0, 40)
    df30, df1h = _frame(a30), _frame(a1h)
    whys = set()
    for i in range(1700, 2000):
        ce = int(a30[i, 0]) + M.MIN30
        ev = M.evaluate_st(co, df30.iloc[:i + 1], df1h[df1h.open_ms + M.H1 <= ce], ce)
        assert ev["rule"] == "st" and ev["stop_dist"] == pytest.approx(ev["atr"] * 3.0)
        whys.add(ev["why"] if not ev["why"].endswith("조건 안 맞음") else "조건")
    assert "스톡RSI 크로스 없음" in whys and "조건" in whys
    ce = int(a30[1801, 0]) + M.MIN30                                  # a close on the hour: its 1h bar closes with it
    assert ce % M.H1 == 0
    ev = M.evaluate_st(co, df30.iloc[:1802], df1h[df1h.open_ms + M.H1 <= ce - M.H1], ce)
    assert ev["why"] == "1시간봉이 아직 없음"                           # ... and it is not there yet


def test_the_live_config_runs_both_rules_with_a_3_atr_stop():
    cfg = M.load_config(str(ROOT / "deploy" / "mixchop.live.json"))
    # owners 10-31: the friend bot trades OBV light -> dark and 추세 3개 일치 on 15m bars (tests/test_rules1031.py); 10-31
    # evening: on 30m bars, the OBV turn with the AC bar (tests/test_rules1031b.py); the stop multiple, the ladder and the
    # margin stay
    assert cfg.rules == ("obvac",) and cfg.stop_atr == 3.0           # (10-31 evening, later: 추세 3개 일치 out)
    assert {c.sl_atr for c in cfg.coins} == {3.0}
    # owners 10-27 "친구봇 익절기준은 1 계단 10->8로 바꿔주고": 10 -> 8, 15 -> 13, 20 -> 18 ...
    assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0} and cfg.margin_frac == 0.4
    assert "계단 순ROE +10%→+8%, +15%→+13%, +20%→+18%" in M.plan_words(cfg)


def test_the_signals_command_lists_the_crosses(tmp_path, monkeypatch, capsys):
    """``python -m paperbot.mixchop signals``: the friend's colour changes, then the second rule's last crosses (oldest
    first) with what the bot would have done, to put next to TradingView."""
    a30 = _walk(2000, 5)
    a1h = _hours(a30)
    end = int(a30[-1, 0]) + M.MIN30
    rows = {"30m": a30.tolist(), "1h": a1h.tolist()}
    monkeypatch.setattr(M, "binance_fetch", lambda base: lambda s, tf, n: [r for r in rows[tf] if r[0] < end][-n:])
    monkeypatch.setattr(M.time, "time", lambda: end / 1000 + 60)
    cfg = _cfg(tmp_path, rules=["mix", "st"], stop_atr=3)
    import argparse
    assert M.cmd_signals(argparse.Namespace(config=str(tmp_path / "cfg.json"), n=4)) == 0
    out = capsys.readouterr().out
    assert out.count("-- 슈퍼트렌드·스톡RSI: 스톡RSI 14/11/4/6 크로스 (슈퍼트렌드 14/3·14/6, RSI26 30분·1시간, MOM 10)") == len(cfg.coins)
    cross = [ln for ln in out.splitlines() if " KST 마감  골든" in ln or " KST 마감  데드" in ln]
    assert len(cross) == 4 * len(cfg.coins) and all("K " in ln and "RSI26 30분" in ln and "  MOM " in ln and "→ " in ln
                                                    for ln in cross)
    first = cross[:4]
    assert first == sorted(first)                                     # oldest first


def test_the_check_command_names_the_rules_and_the_stop(tmp_path, monkeypatch, capsys):
    from paperbot import wooxpro as WX
    a30 = _walk(200, 6)
    end = int(a30[-1, 0]) + M.MIN30

    class Pub:
        def spec(self, s):
            return {"status": "TRADING", "max_leverage": 50, "contract_size": 1, "min_qty": 0.01, "qty_step": 0.01, "min_notional": 1}
    monkeypatch.setattr(WX, "public_client", lambda: Pub())
    monkeypatch.setattr(M, "binance_fetch", lambda base: lambda s, tf, n: a30.tolist()[-n:])
    monkeypatch.setattr(M.time, "time", lambda: end / 1000 + 60)
    _cfg(tmp_path, rules=["mix", "st"], stop_atr=3)
    import argparse
    assert M.cmd_check(argparse.Namespace(config=str(tmp_path / "cfg.json"))) == 0
    out = capsys.readouterr().out.splitlines()
    assert "매매법·손절: 친구 매매법 + 슈퍼트렌드·스톡RSI(같은 봉이면 친구 매매법 먼저) · 손절 ATR 3배(모든 코인)" in out
    _cfg(tmp_path)
    assert M.cmd_check(argparse.Namespace(config=str(tmp_path / "cfg.json"))) == 0
    assert not any(ln.startswith("매매법·손절") for ln in capsys.readouterr().out.splitlines())     # the friend's alone: as before


def test_the_10_27_rule_is_the_10_26_rule_with_d6_and_mom():
    """Owners 10-27: "스톡RSI 14/11/4/6 ... RSI26이 50 위에 있고 MOM도 0선 위에 있고": the bot's numbers, and on a long walk
    every new signal is a %D-6 signal whose MOM agrees, and some %D-6 signals are dropped by MOM."""
    assert M.ST_STOCH == (14, 11, 4, 6) and M.ST_MOM == 10
    a30 = _walk(6000, 7)
    a1h = _hours(a30)
    co = M.Coin("SOLUSDT", 8.0, 3.0, 150.0, 40)
    lo, hi = int(a30[400, 0]), int(a30[-1, 0]) + M.MIN30
    new = S.new_signals(co, a30, a1h, S.NEW, lo, hi)
    d6 = S.new_signals(co, a30, a1h, {**S.NEW, "mom": 0}, lo, hi)
    mm = M.mom(a30[:, 4], 10)
    ce = a30[:, 0].astype(np.int64) + M.MIN30
    assert new and set(new) < set(d6)
    for t, e in d6.items():
        i = int(np.searchsorted(ce, t))
        assert (t in new) == (mm[i] * e["side"] > 0)


def test_the_entry_words_and_the_mom_condition(tmp_path):
    ev = {"rule": "st", "close_ms": _ms("2026-10-27 01:00"), "k": 30.1, "d": 25.2, "rsi26_30m": 56.0, "rsi26_1h": 54.0,
          "mom": 0.0042}
    assert M.reason_words(ev, 1, True) == ("근거(슈퍼트렌드·스톡RSI): 슈퍼트렌드 14/3·14/6 상승 · 스톡RSI 골든크로스(K 30.1 / D 25.2)"
                                           " · RSI26 30분 56.0 · 1시간 54.0 · MOM 0.0042 (10/27 10:00 봉)")
    a30 = _walk(3000, 8)
    a1h = _hours(a30)
    co = M.Coin("SOLUSDT", 8.0, 3.0, 150.0, 40)
    df30, df1h = _frame(a30), _frame(a1h)
    moms = []
    for i in range(1700, 3000):
        ce = int(a30[i, 0]) + M.MIN30
        ev = M.evaluate_st(co, df30.iloc[i - 1498:i + 1].reset_index(drop=True),
                           df1h[df1h.open_ms + M.H1 <= ce].tail(1499).reset_index(drop=True), ce)
        if ev.get("cross"):
            assert ev["mom"] == pytest.approx(float(M.mom(a30[:i + 1, 4], 10)[-1]), rel=1e-5)
            moms.append(ev["why"])
    assert any("30분 MOM" in w for w in moms)                          # the new condition really says no sometimes
