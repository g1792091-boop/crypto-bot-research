"""Owners 11-04: "30분봉이랑 15분봉 추세macd 히스토그램이 추세가 같을때만 진입" — the two mix bots (레인지 봇, 친구 15분 봇)
enter only when the 추세 MACD histogram of the last closed 30m bar and that of the 15m signal bar itself are on the
signal's side of 0 (config ``trend_both``; paperbot/mixchop.py evaluate_friend). The rule and its words: the entry,
the refusal, the 근거 line, the signal list, the start message, the check line; the config's refusals; the deploy
configs; the site's wait line and trend words."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from paperbot import friendtrend as FT
from paperbot import mixchop as M

sys.path.insert(0, os.path.dirname(__file__))
from test_rules1031c import _pair  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30


def _tm(trend, hist=None, yellow=False):
    return {"trend": trend, "hist": 3.2 * trend if hist is None else hist, "macd": 10.0 * trend, "yellow": yellow}


def _o4(side):
    return {"ac": -3.0 if side > 0 else 3.0, "col": side, "turn": side, "side": side, "macd": 5.0}


def _judge(monkeypatch, t30, t15, signal=1, both=True):
    """The OBV histogram's turn ``signal`` on a 15m close with the 30m 추세 MACD ``t30`` and the 15m one ``t15`` (the
    30m one is read first, then the signal bars' own)."""
    r15, r30 = _pair(800, 5)
    ce = T0
    b15 = M.bars_frame(r15, M.MIN15, ce)
    b30 = M.bars_frame(r30, M.MIN30, ce)
    seen = []

    def tm(h, l, c, v):
        seen.append(len(c))
        return t30 if len(seen) == 1 else t15
    monkeypatch.setattr(FT, "tmacd_state", tm)
    monkeypatch.setattr(FT, "o4_state", lambda *a: _o4(signal))
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    ev = M.Bot.judge("o4h", co, b15, b30, ce, M.MIN15, "macd", M.MIN30, both)
    return ev, seen, (len(b30), len(b15))


def test_both_on_the_signals_side_enters(monkeypatch):
    ev, seen, (n30, n15) = _judge(monkeypatch, _tm(1), _tm(1, 0.8))
    assert ev["side"] == 1 and ev["why"] == "" and seen == [n30, n15]            # 30m first, then the 15m bars
    assert (ev["trend"], ev["tmacd"], ev["tsig"], ev["tmacd_sig"], ev["tyellow_sig"]) == (1, 3.2, 1, 0.8, False)
    assert ev["trend_tf"] == "30분" and ev["tf"] == "15분"
    short, _s, _n = _judge(monkeypatch, _tm(-1), _tm(-1, -0.5, yellow=True), signal=-1)
    assert short["side"] == -1 and short["tyellow_sig"] is True                  # a yellow 15m bar counts by its side
    line = M.reason_words({**ev, "close_ms": T0}, 1)
    assert "· 추세 MACD 30분 히스토그램 0선 위 상승(+3.20) · 추세 MACD 15분 히스토그램 0선 위 상승(+0.80)" in line


def test_the_15m_against_the_30m_does_not_enter(monkeypatch):
    ev, _s, _n = _judge(monkeypatch, _tm(1), _tm(-1, -0.4))
    assert ev["side"] == 0 and ev["tsig"] == -1
    assert ev["why"] == "추세 MACD 15분 히스토그램 0선 아래 하락(-0.40): 30분 추세(상승)와 같은 쪽 아님"
    flat, _s, _n = _judge(monkeypatch, _tm(1), _tm(0, 0.0))
    assert flat["side"] == 0 and flat["why"].startswith("추세 MACD 15분 히스토그램 0선(진입 안 함")
    # the 30m against the signal is still said first (the rule of 11-02)
    first, seen, _n = _judge(monkeypatch, _tm(-1), _tm(1))
    assert first["side"] == 0 and first["why"].startswith("추세 MACD 30분 히스토그램 0선 아래 하락")


def test_without_trend_both_the_15m_is_not_read(monkeypatch):
    ev, seen, (n30, _n15) = _judge(monkeypatch, _tm(1), _tm(-1), both=False)
    assert ev["side"] == 1 and seen == [n30] and "tsig" not in ev               # (the rule of 11-02 as it was)


def _cfg(tmp_path, **over):
    """The 레인지 봇's config as it was on 11-04 (15m signals, trend_both); since later that day the deploy configs run
    the 5m turn with the 15m trend on its own bars (tests/test_rules1104b.py)."""
    d = json.loads((DEPLOY / "mixrange.paper.json").read_text(encoding="utf-8"))
    for k in ("trend_tf2", "stop_tf"):
        d.pop(k, None)
    d.update(tf="15m", trend_both=True)
    d.update(state=str(tmp_path / "s.json"), log=str(tmp_path / "l.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN"), telegram=False, **over)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return M.load_config(str(p))


def test_the_configs(tmp_path):
    cfg = _cfg(tmp_path)
    assert (cfg.trend, cfg.trend_tf, cfg.trend_both, cfg.rules, cfg.tf, cfg.trend2_ko) == ("macd", "30m", True, ("o4h",), "15m", "15분")
    assert _cfg(tmp_path, trend_both=False).trend_both is False
    with pytest.raises(M.MixError):
        _cfg(tmp_path, trend_both="yes")
    # like trend_tf, it means something only with the 추세 MACD on longer bars than the signal's: ignored otherwise
    for other in ({"trend": "bar"}, {"trend_tf": "15m"}, {"trend_tf": None}):
        assert _cfg(tmp_path, **other).trend_both is False, other


def test_the_words_of_the_start_and_the_check(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path, start_equity=100)
    msgs = []
    bot = M.Bot(cfg, M.PaperBroker(100.0, cfg.taker_fee), lambda s, tf, n: [], lambda: T0 + 5_000,
                notify=lambda lv, t: msgs.append(t), sleep=lambda s: None)
    bot.start()
    assert "15분봉 마감마다 판단 (추세는 30분봉 추세 MACD 히스토그램 + 15분봉도 같은 쪽일 때만)" in msgs[0]
    monkeypatch.setattr(M, "public_spec", lambda c: lambda sym: {"status": "Trading", "max_leverage": 50.0, "min_qty": 0.001,
                                                                "qty_step": 0.001, "min_notional": 5.0, "tick": 0.01})
    r15, r30 = _pair(1600, 7)
    src = {"15m": r15, "30m": r30}
    monkeypatch.setattr(M, "binance_fetch", lambda base: lambda s, tf, n: [r for r in src[tf] if r[0] < T0][-n:])
    monkeypatch.setattr(M.time, "time", lambda: T0 / 1000 + 60)
    p = tmp_path / "c.json"
    assert M.cmd_check(type("A", (), {"config": str(p)})()) == 0
    out = capsys.readouterr().out
    assert "추세: 30분봉 추세 MACD 히스토그램(0선 위 상승 · 0선 아래 하락) + 15분봉 추세 MACD도 같은 쪽일 때만" in out


def test_the_signal_list_says_the_15m(monkeypatch):
    """friend_history (the ``signals`` listing): each OBV turn with both trends; a turn the 15m 추세 MACD is against is
    an X, and the list agrees with evaluate_friend at the same closes."""
    r15, r30 = _pair(1600, 11)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    b15 = M.bars_frame(r15, M.MIN15, T0)
    b30 = M.bars_frame(r30, M.MIN30, T0)
    lines = M.friend_history(co, b15, "o4h", 60, M.MIN15, "macd", b30, M.MIN30, True)
    assert lines and all(" · 15분 히스토그램 " in ln for ln in lines)
    plain = M.friend_history(co, b15, "o4h", 60, M.MIN15, "macd", b30, M.MIN30, False)
    assert len(plain) == len(lines) and not any("15분 히스토그램" in ln for ln in plain)
    entered = [ln for ln in lines if ln.endswith("진입")]
    blocked = [ln for ln in lines if ln.endswith("X (15분 추세 다름)")]
    assert len([ln for ln in plain if ln.endswith("진입")]) == len(entered) + len(blocked)
    # the same answer as the bot's own evaluate_friend at each listed close
    for ln in lines:
        hhmm = ln.split(" KST")[0]
        ce = next(int(t) + M.MIN15 for t in b15.open_ms if M.kst(int(t) + M.MIN15) == hhmm)
        f15 = b15[b15.open_ms + M.MIN15 <= ce].reset_index(drop=True)
        f30 = b30[b30.open_ms + M.MIN30 <= ce // M.MIN30 * M.MIN30].reset_index(drop=True)
        ev = M.evaluate_friend("o4h", co, f15, ce, M.MIN15, "macd", tb=f30, trend_tf_ms=M.MIN30, trend_both=True)
        assert (ev["side"] != 0) == ln.endswith("진입"), (ln, ev["why"])


def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    js = ROOT / "paperbot" / "dash" / "static" / "v4" / "screens" / "livebots-mix.js"
    dom = ROOT / "tests" / "anasyn_dom.mjs"
    script = f"await import('file://{dom}');\nconst MX = await import('file://{js}');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_site_words():
    # (the words of 11-04's 15m signals; since that evening the live bots' are the 5m ones: tests/test_dash_mixrange_site.py)
    out = _node("""console.log(JSON.stringify({
  w: [MX.waitWords("15분", "30분", MX.o4hWait, "macd2"), MX.waitWords("15분", "30분", MX.o4hWait, "macd2"), MX.BYBIT_UI.wait],
  tm: [MX.tmKo({trend_mode: "macd", trend: 1, tmacd: 3.21, trend_tf: "30분", tf: "15분", tsig: 1, tmacd_sig: 0.8}),
       MX.tmKo({trend_mode: "macd", trend: 1, tmacd: 3.21, trend_tf: "30분", tf: "15분"})],
}));""")
    mix, rng, by = out["w"]
    assert mix.startswith("15분봉이 끝날 때 30분봉의 추세 MACD 히스토그램(0선 위 = 상승, 0선 아래 = 하락, 노란 막대도 같음)이 "
                          "15분봉에서도 같은 쪽일 때 15분봉 OBV 히스토그램")
    assert mix == rng and "15분봉에서도" not in by                                # (the 바이비트 봇, off, as it was)
    assert out["tm"] == ["추세 MACD 30분 히스토그램 0선 위 상승 +3.21 · 15분 상승 +0.80", "추세 MACD 30분 히스토그램 0선 위 상승 +3.21"]
