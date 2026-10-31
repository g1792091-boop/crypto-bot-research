"""Owners 2026-10-31 evening: 'OBV 진한색 + AC' (OBV_MACD.pine) for the 바이비트 봇 and the friend bot.

The owners: "30분봉 진입 추세는 그대로 두고 진입 방식만 바꾸는데 상승 추세에서 초록진한선이 뜨는데 히스토그램이 플러스 양봉이면
진입 숏 추세이고 빨간진한선이 나오고 마이너스 음봉이면 진입 … 상승장인데 초록진한선이 나오고 플러스 음봉이면 진입 금지 하락장인데
빨간 진한선이 나오는데 마이너스 양봉이면 진입금지 원래 있던 진입 금지는 그대로 두는데 50일선위 숏 아래 롱은 삭제", and their
answers: the dark line = the OBV pane's light -> dark turn the bots already read; the WOO X Pro bot = the friend bot
(WOO X Pro 2), on 30m bars with the 바이비트 봇's four-vote trend.

- friendtrend part 8: OBV MACD's AC histogram = (line - the conditional signal) - its SMA 5, green when it rose, red when
  it fell; a side = a green turn with the AC bar plus and green, a red turn with it minus and red; no 50 line;
- mixchop rule "obvac": its words, the trend still checked, the friend's own other rules unchanged; the deploy configs
  (바이비트 봇: ["obvac"]; 친구 30분 봇: 30m, four votes, ["obvac", "ema3"]); its signals listing and the morning replay;
- the site: the rule's name, the AC words on the signal rows and on the friend trend board."""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from paperbot import friendtrend as FT
from paperbot import mixcheck as MC
from paperbot import mixchop as M

sys.path.insert(0, os.path.dirname(__file__))
from test_rules1030 import frame, walk  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
SCREENS = ROOT / "paperbot" / "dash" / "static" / "v4" / "screens"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
MIN, HOUR = 60_000, 3_600_000


# ====================================================================== friendtrend part 8
def test_the_ac_bar_is_the_scripts():
    o, h, lo, c, v = walk(1200, seed=23)
    P = FT.ac_pane(h, lo, c, v)
    hraw = FT.obv_pane(h, lo, c, v)["hist"]                    # OBV MACD's hRaw = macd - sig = line - condSig
    for i in range(100, len(c)):
        want = hraw[i] - sum(hraw[i - 4:i + 1]) / 5            # acV = hRaw - ta.sma(hRaw, 5)
        assert P["ac"][i] == pytest.approx(want, rel=1e-9, abs=1e-12)
        prev = P["ac"][i - 1]
        col = 1 if P["ac"][i] > prev else -1 if P["ac"][i] < prev else 0
        assert P["ac_col"][i] == col
    assert P["ac_col"][0] == 0 and not math.isfinite(P["ac"][3])  # the SMA 5 is not defined yet: grey
    # a read on the history up to a bar is the pane at that bar (the indicators look back only)
    sides = set()
    for i in range(300, len(c), 7):
        st = FT.obvac_state(h[:i + 1], lo[:i + 1], c[:i + 1], v[:i + 1])
        assert st["ac"] == pytest.approx(round(P["ac"][i], 4)) and st["ac_col"] == P["ac_col"][i]
        sides.add(st["side"])
    assert {0} <= sides


def test_fifteen_hundred_bars_read_the_same_ac():
    o, h, lo, c, v = walk(4000, seed=29)
    cut = slice(-1500, None)
    P, Q = FT.ac_pane(h, lo, c, v), FT.ac_pane(h[cut], lo[cut], c[cut], v[cut])
    # a hairline bar (the line on the wrong side of its signal while cs is kept) is |line| x 1e-6 high, and the running
    # sum's level depends on where the history starts (TradingView: the chart's first loaded bar): the AC values move by
    # a few 1e-5 at most, never their sign or colour
    assert np.allclose(P["ac"][-300:], Q["ac"][-300:], rtol=0, atol=1e-3)
    assert (P["ac_col"][-300:] == Q["ac_col"][-300:]).all()
    assert (np.sign(P["ac"][-300:]) == np.sign(Q["ac"][-300:])).all()


def test_the_owners_four_cases_and_no_50_line():
    side = FT.ac_side
    assert side(1, 0.42, 1) == 1                               # 상승 + 진한 초록 + 플러스 양봉: 진입
    assert side(1, 0.42, -1) == 0                              # 상승 + 진한 초록 + 플러스 음봉: 진입 금지
    assert side(-1, -0.31, -1) == -1                           # 하락 + 진한 빨강 + 마이너스 음봉: 진입
    assert side(-1, -0.31, 1) == 0                             # 하락 + 진한 빨강 + 마이너스 양봉: 진입 금지
    assert side(1, -0.2, 1) == 0 and side(1, -0.2, -1) == 0    # 진한 초록인데 마이너스: the owners' entry is plus 양봉 only
    assert side(-1, 0.2, -1) == 0 and side(1, 0.42, 0) == 0 and side(0, 0.42, 1) == 0
    assert side(1, float("nan"), 1) == 0
    assert FT.ac_words(0.4231, 1) == "플러스 양봉(0.42)" and FT.ac_words(-0.31, -1) == "마이너스 음봉(-0.31)"
    assert FT.ac_words(0.12, -1) == "플러스 음봉(0.12)" and FT.ac_words(None, 1) == "못 읽음"
    assert "d50" not in FT.obvac_state(*walk(400, seed=3)[1:])  # no 50 line in this rule


# ====================================================================== mixchop rule "obvac"
def _eval(monkeypatch, ob, trend=1, tf=M.MIN30):
    b = frame(400, tf_ms=tf, vol=0.002)
    co = M.Coin("SOLUSDT", 0.0, 3.0, 100.0, 40)
    four = {"trend": trend, "line": trend, "ema": trend, "chop": 0, "st": trend, "ema_rsi": 55.0, "chop_zone": 1}
    monkeypatch.setattr(FT, "obvac_state", lambda *a: ob)
    monkeypatch.setattr(FT, "last_trend", lambda *a: four)
    return M.evaluate_friend("obvac", co, b, T0, tf, "four"), b


def test_obvac_enters_on_the_turn_with_the_ac_bar_and_the_trend(monkeypatch):
    up = {"turn": 1, "cs": 1, "dark": True, "ac": 0.42, "ac_col": 1, "side": 1}
    ev, b = _eval(monkeypatch, up)
    assert ev["side"] == 1 and ev["rule"] == "obvac" and ev["ac"] == 0.42 and ev["ac_col"] == 1 and "tf" not in ev
    assert ev["stop_dist"] == pytest.approx(3 * float(M.atr(b.high, b.low, b.close, 14)[-1]))
    words = M.reason_words(ev, 1, name=True)
    assert words.startswith("근거(OBV 진한색 + AC): OBV 연한 초록→진한 초록 · AC 플러스 양봉(0.42) · 친구 추세 30분 상승 (")
    # 상승장인데 진한 초록 + 플러스 음봉: 진입 금지, said so
    ev, _ = _eval(monkeypatch, {**up, "ac_col": -1, "side": 0})
    assert ev["side"] == 0 and ev["why"] == "OBV 진한 초록인데 AC 플러스 음봉(0.42)"
    # 하락장인데 진한 빨강 + 마이너스 양봉: 진입 금지
    dn = {"turn": -1, "cs": -1, "dark": True, "ac": -0.31, "ac_col": 1, "side": 0}
    ev, _ = _eval(monkeypatch, dn, trend=-1)
    assert ev["side"] == 0 and ev["why"] == "OBV 진한 빨강인데 AC 마이너스 양봉(-0.31)"
    ev, _ = _eval(monkeypatch, {**dn, "ac_col": -1, "side": -1}, trend=-1)
    assert ev["side"] == -1
    # the trend's own 진입 금지 stays (owners: "원래 있던 진입 금지는 그대로")
    ev, _ = _eval(monkeypatch, up, trend=0)
    assert ev["side"] == 0 and ev["why"].startswith("친구 추세 진입 금지")
    ev, _ = _eval(monkeypatch, up, trend=-1)
    assert ev["side"] == 0 and ev["why"].endswith(": 신호 롱와 반대")
    ev, _ = _eval(monkeypatch, {**up, "turn": 0, "side": 0})
    assert ev["why"] == "OBV 연한색→진한색 없음"
    row = M.board_row([_eval(monkeypatch, up)[0]], T0)
    assert row["rules"]["obvac"]["side"] == 1 and (row["ac"], row["ac_col"]) == (0.42, 1)
    assert "obvac" in M.FRIEND_RULES and M.RULE_KO["obvac"] == "OBV 진한색 + AC"


def test_the_deploy_configs():
    for name, mode in (("mixbybit.live.json", "mainnet"), ("mixbybit.paper.json", "paper")):
        cfg = M.load_config(str(DEPLOY / name))
        assert cfg.mode == mode and cfg.exchange == "bybit" and cfg.name == "바이비트 봇"
        assert (cfg.tf, cfg.trend, cfg.rules, cfg.stop_atr) == ("30m", "four", ("obvac",), 3.0)
        assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0} and cfg.margin_frac == 0.4
    for name, mode in (("mixchop.live.json", "mainnet"), ("mixchop.paper.json", "paper")):
        cfg = M.load_config(str(DEPLOY / name))
        assert cfg.mode == mode and cfg.exchange == "wooxpro" and cfg.name == "친구 30분 봇"
        assert (cfg.tf, cfg.trend, cfg.rules, cfg.stop_atr) == ("30m", "four", ("obvac", "ema3"), 3.0)
        assert {c.symbol: c.leverage for c in cfg.coins} == {"SOLUSDT": 40, "ETHUSDT": 40, "XRPUSDT": 40, "BCHUSDT": 40,
                                                            "ZECUSDT": 20, "DOGEUSDT": 40}
        assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0} and cfg.margin_frac == 0.4
        assert "매매법 OBV 진한색 + AC + 추세 3개 일치(같은 봉이면 OBV 진한색 + AC 먼저)" in M.plan_words(cfg)


def _walk_rows(n, seed, tf):
    rng = np.random.default_rng(seed)
    t = T0 - tf * np.arange(n, 0, -1)
    c = 150 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
    return [[int(t[i]), o[i], hi[i], lo[i], c[i], rng.uniform(100, 1000)] for i in range(n)]


def test_the_signals_listing_and_the_morning_replay():
    cfg = M.load_config(str(DEPLOY / "mixbybit.paper.json"))
    cfg.coins = cfg.coins[:1]
    rows = _walk_rows(2000, 43, M.MIN30)
    b = M.bars_frame(rows, M.MIN30, T0)
    lines = M.friend_history(cfg.coins[0], b, "obvac", 8, M.MIN30)
    assert 1 <= len(lines) <= 8 and all(" AC " in x and "→" in x for x in lines)
    assert any("X (AC 조건 안 맞음)" in x for x in M.friend_history(cfg.coins[0], b, "obvac", 200, M.MIN30))

    def klines(symbol, tf, start, limit):
        assert tf == "30m"
        return [r for r in rows if r[0] >= start][:limit]
    day0 = T0 - 24 * HOUR
    log = []
    co = cfg.coins[0]
    for ce in range(day0 + M.MIN30, T0 + 1, M.MIN30):
        bb = M.bars_frame(rows, M.MIN30, ce).tail(M.BARS - 1).reset_index(drop=True)
        ev = M.Bot.judge("obvac", co, bb, bb, ce, M.MIN30, "four")
        if ev.get("turn") or ev["side"]:
            log.append({"ts": ce + 5_000, "kind": "signal", **ev})
    assert log
    rp = MC.signal_replay(cfg, day0, T0, log, klines, obs=[[T0 + 3 * MIN, T0, None]], st_last=T0)
    assert rp["state"] == "ok" and rp["different"] == [] and rp["rules"] == ["obvac"]
    assert rp["turns"] == sum(1 for r in log if r.get("turn"))
    assert f"OBV 연한→진한 {rp['turns']}번" in MC.replay_lines(rp)[0]
    gone = log[0]
    rp2 = MC.signal_replay(cfg, day0, T0, log[1:], klines, obs=[], st_last=T0)
    assert any(x["close_ms"] == gone["close_ms"] and x["rule"] == "obvac" for x in rp2["missed"] + rp2["unsure"])
    assert MC.RULE_TAG["obvac"] == "(OBV 진한색 + AC)" and MC.RULE_WHAT["obvac"] == "OBV 연한→진한"


# ====================================================================== the site
def test_the_board_and_the_rule_lines():
    from paperbot.dash.more import liveftrend as FTR
    from paperbot.dash.more import livemix as X
    ev = {"symbol": "BTCUSDT", "close_ms": T0, "side": 1, "why": "", "rule": "obvac", "close": 60000.0, "turn": 1,
          "obv_cs": 1, "obv_dark": True, "ac": 0.42, "ac_col": 1, "trend": 1,
          "votes": {"line": 1, "ema": 1, "chop": 1, "st": 0}}
    row = FTR.m30_row(M.board_row([ev], T0), T0 + MIN)
    assert row["state"] == "ok" and (row["ac"], row["ac_col"]) == (0.42, 1) and row["obv50"] is None
    assert row["rules"]["obvac"] == {"side": 1, "why": "", "ko": "OBV 진한색 + AC"}
    assert any(x.startswith("OBV 진한색 + AC(바이비트 봇 · 친구 30분 봇, 10-31 저녁부터)") for x in FTR.RULES_KO)
    assert any(x.startswith("친구 30분 봇(WOO X Pro 2, 10-31 저녁부터 30분봉") for x in FTR.RULES_KO)
    assert {"ac", "ac_col"} <= set(X.VAL_KEYS)


def _node(js: str) -> str:
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_the_screens_say_the_ac_bar():
    out = json.loads(_node(f"""
    const X = await import('file://{SCREENS}/livebots-mix.js');
    const F = await import('file://{SCREENS}/livebots-ftrend.js');
    console.log(JSON.stringify({{v: X.valsKo({{rule: "obvac", ac: 0.4231, ac_col: 1, trend: 1, close: 100, stop_pct: 1.2,
      votes: {{line: 1, ema: 1, chop: 0, st: 1}}}}), a: F.acKo(-0.31, -1), b: F.acKo(0.12, -1), n: F.acKo(null, 1),
      w: X.MIX_UI.wait, y: X.BYBIT_UI.wait}}));"""))
    assert "AC 플러스 양봉 0.42" in out["v"] and "OBV 50선" not in out["v"]
    assert (out["a"], out["b"], out["n"]) == ("마이너스 음봉 (\u22120.31)", "플러스 음봉 (0.12)", "못 읽음")   # fmt.num: U+2212
    for w in (out["w"], out["y"]):
        assert "AC 막대가 그 쪽(롱: 플러스 양봉, 숏: 마이너스 음봉)" in w
    assert out["w"].startswith("30분봉이 끝날 때") and "50선 조건 없음" in out["y"]
    routes = (ROOT / "paperbot" / "dash" / "static" / "v4" / "core" / "routes.js").read_text(encoding="utf-8")
    assert 'mixbot: {ko: "친구 30분 봇"' in routes and "OBV 진한색 + AC" in routes
