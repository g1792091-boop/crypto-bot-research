"""Owners 2026-11-02: the site's words for the three bots' new trend and entries (the 30m 추세 MACD histogram's side of 0,
the 바이비트 봇's OBV 히스토그램 turn "o4h", the 친구 15분 봇's and the 레인지 봇's 3합 히스토그램 0 cross "h3x").

The pure functions of the three screens that say them, run in node: the 관제실's grid cell, entry reason and coin trend
(screens/livebots-deck.js cellOf / whyKo / tmKo), the bot screens' row words (screens/livebots-mix.js h3Val / o4Val /
tmKo / trendKo / waitWords / h0xVal), the 친구 추세판's trend cell and entry words (screens/livebots-ftrend.js trendCell /
h3Ko / o4Ko); the titles and the subs of the menu (core/routes.js, screens/livebots.js). The program's own words are in
tests/test_rules1102.py."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")


def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = (f"await import('file://{DOM}');\n"
              f"const DK = await import('file://{SCREENS}/livebots-deck.js');\n"
              f"const MX = await import('file://{SCREENS}/livebots-mix.js');\n"
              f"const FT = await import('file://{SCREENS}/livebots-ftrend.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_deck_words():
    """관제실: the grid cell of an "o4h" / "h3x" row (its value, its turn or cross, the trend), the entry card's reason
    (the 15m entry · the 30m 추세 MACD), a coin's 30m 추세 MACD (the yellow bars by their side of 0)."""
    out = _node("""console.log(JSON.stringify({
  o4: DK.cellOf({rule: "o4h", trend: 1, o4: -3.21, o4_turn: 1, side: 1}),
  o4q: DK.cellOf({rule: "o4h", trend: -1, o4: 0.4, o4_turn: 0, side: 0}),
  o4n: DK.cellOf({rule: "o4h", trend: 1, side: 0}),
  h3: DK.cellOf({rule: "h3x", trend: -1, h3: -2.5, x0: -1, side: 0}),
  h3s: DK.cellOf({rule: "h3x", trend: 1, h3: 1.25, x0: 1, side: 1}),
  w3: DK.whyKo({rule: "h3x", tf: "15분", trend_tf: "30분", trend_mode: "macd", trend: 1, tmacd: 3.214, x0: 1, h3: 2.5}),
  w4: DK.whyKo({rule: "o4h", tf: "15분", trend_tf: "30분", trend_mode: "macd", trend: -1, tmacd: -1.4, o4_turn: -1, o4: 2.1}),
  wb: DK.whyKo({rule: "h0x", tf: "15분", trend_tf: "30분", trend_mode: "bar", trend: 1, x0: 1, h6: 4.08}),
  tmu: DK.tmKo({trend30: [[1, 1]], tm30: {hist: 3.214, macd: 5, yellow: false}}),
  tmd: DK.tmKo({trend30: [[1, -1]], tm30: {hist: -1.4, yellow: true}}),
  tm0: DK.tmKo({trend30: [[1, 0]], tm30: {hist: 0}}),
}));""")
    assert out["o4"] == {"tone": "up", "big": "OBV −3.2", "sub": "롱 신호", "sig": 1}
    assert out["o4q"] == {"tone": "down", "big": "OBV 0.4", "sub": "하락", "sig": 0}
    assert out["o4n"]["big"] == "OBV —"
    assert out["h3"] == {"tone": "down", "big": "−2.5", "sub": "0선 ↓ · 하락", "sig": 0}
    assert out["h3s"]["sub"] == "롱 신호" and out["h3s"]["big"] == "1.3"
    assert out["w3"] == "15분봉 3합 히스토그램 0선 위로 돌파 (2.50) · 추세 MACD 30분 상승 (3.21)"
    assert out["w4"] == "15분봉 OBV 히스토그램 0선 위 음봉 전환 (2.10) · 추세 MACD 30분 하락 (−1.40)"
    assert out["wb"].endswith("· 추세 바 30분 종합 상승")          # an entry of before 11-02 keeps its own words
    assert out["tmu"] == "상승 +3.21" and out["tmd"] == "하락 −1.40" and out["tm0"] == "0선 0.00"


def test_the_bot_screen_words():
    """봇별 화면 (관제 · 신호 기록): a row's 3합 / OBV histogram, its 추세 MACD (a yellow bar said, read by its side of 0),
    the wait line of each bot (15분봉 진입 · 30분봉 추세 MACD), an "h3x" row not read as the old "h0x"."""
    out = _node("""console.log(JSON.stringify({
  h3u: MX.h3Val({rule: "h3x", x0: 1, h3: 2.5}), h3n: MX.h3Val({rule: "h3x", x0: 0, h3: -0.3}), h3o: MX.h3Val({rule: "h0x", x0: 1, h6: 2}),
  h0: MX.h0xVal({rule: "h3x", x0: 1, h3: 2.5}), h0o: MX.h0xVal({rule: "h0x", x0: 1, h6: 2}),
  o4l: MX.o4Val({o4: -3, o4_turn: 1}), o4s: MX.o4Val({o4: 2.1, o4_turn: -1}), o4n: MX.o4Val({o4: 0.4, o4_turn: 0}), o4x: MX.o4Val({}),
  tu: MX.trendKo({trend_mode: "macd", trend: 1, tf: "15분", trend_tf: "30분", tmacd: 3.214, tyellow: false}),
  ty: MX.trendKo({trend_mode: "macd", trend: -1, tf: "15분", trend_tf: "30분", tmacd: -1.4, tyellow: true}),
  t0: MX.trendKo({trend_mode: "macd", trend: 0, tf: "15분", trend_tf: "30분", tmacd: 0}),
  wm: MX.waitWords("15분", "30분", MX.H3X_WAIT, "macd"), wb: MX.waitWords("15분", "30분", MX.O4H_WAIT, "macd"),
  ui: [MX.MIX_UI, MX.RANGE_UI, MX.BYBIT_UI].map((o) => [o.trend || null]),
  rk: [MX.RULE_KO.o4h, MX.RULE_KO.h3x],
}));""")
    assert out["h3u"] == "3합 히스토그램 0선 위로 돌파 2.50" and out["h3n"] == "3합 히스토그램 0선 돌파 없음 −0.30"
    assert out["h3o"] is None and out["h0"] is None and out["h0o"] == "히스토그램 0선 위로 돌파 2.00"
    assert out["o4l"] == "OBV 히스토그램 0선 아래 양봉 전환 −3.00" and out["o4s"] == "OBV 히스토그램 0선 위 음봉 전환 2.10"
    assert out["o4n"] == "OBV 히스토그램 0선 위 전환 없음 0.40" and out["o4x"] is None
    assert out["tu"] == "추세 MACD 30분 히스토그램 0선 위 상승 +3.21"
    assert out["ty"] == "추세 MACD 30분 히스토그램 0선 아래 하락 −1.40 · 노란 막대"
    assert out["t0"] == "추세 MACD 30분 히스토그램 0선(진입 안 함) 0.00"
    assert out["wm"].startswith("15분봉이 끝날 때 30분봉의 추세 MACD 히스토그램(0선 위 = 상승, 0선 아래 = 하락, 노란 막대도 같음) 쪽으로 ")
    assert "15분봉 3합 히스토그램이 0선을 그 쪽으로 돌파하면" in out["wm"]
    assert "0선 아래에서 양봉으로 바뀌면 롱, 0선 위에서 음봉으로" in out["wb"] and "OBV 선은 안 봐요" in out["wb"]
    assert out["rk"] == ["OBV 히스토그램 전환(0선 아래 양봉 롱 · 0선 위 음봉 숏)", "3합 히스토그램 0선 돌파"]


def test_the_ftrend_words():
    """친구 추세판: a coin's 30m 추세 MACD cell (the yellow bar said, 0 = no entry) and its entry words."""
    out = _node("""console.log(JSON.stringify({
  u: FT.trendCell({state: "ok", trend: 1, tm: {ko: "0선 위 상승", hist: 3.214, yellow: false}}),
  y: FT.trendCell({state: "ok", trend: -1, tm: {ko: "0선 아래 하락", hist: -1.4, yellow: true}}),
  z: FT.trendCell({state: "ok", trend: 0, tm: {ko: "0선", hist: 0}}),
  e: FT.trendCell({state: "error", ko: "15분봉을 못 읽음"}),
  h3: FT.h3Ko({ko: "3합 히스토그램 0선 위로 돌파", h3: 2.5}), h3n: FT.h3Ko(null),
  o4: FT.o4Ko({ko: "OBV 히스토그램 0선 아래 양봉 전환(-3.20)"}), o4n: FT.o4Ko(null),
}));""")
    assert out["u"] == {"text": "추세 MACD 0선 위 상승", "tone": "up", "sub": "히스토그램 +3.21"}
    assert out["y"] == {"text": "추세 MACD 0선 아래 하락", "tone": "down", "sub": "히스토그램 −1.40 · 노란 막대(0선 기준으로 봄)"}
    assert out["z"]["tone"] == "side" and out["z"]["sub"].endswith("0선 · 진입 안 함")
    assert out["e"] == {"text": "못 읽음", "tone": "na", "sub": "15분봉을 못 읽음"}
    assert out["h3"] == "3합 히스토그램 0선 위로 돌파 (2.50)" and out["h3n"] is None
    assert out["o4"] == "OBV 히스토그램 0선 아래 양봉 전환(-3.20)" and out["o4n"] is None


def test_the_menu_words():
    """The titles (core/routes.js) and the subs (screens/livebots.js) name the 11-02 rules, not the old trend bar's."""
    routes = open(os.path.join(V4, "core", "routes.js"), encoding="utf-8").read()
    tabs = open(os.path.join(SCREENS, "livebots.js"), encoding="utf-8").read()
    for line in (l for l in routes.splitlines() if l.lstrip().startswith(("bybitbot: {", "rangebot: {", "mixbot: {", "ftrend: {"))):
        assert "추세 MACD 30분" in line and "추세 바" not in line, line
    assert "추세 MACD 30분 + OBV 히스토그램 전환" in routes and routes.count("추세 MACD 30분 + 3합 히스토그램 0선 돌파") == 2
    assert tabs.count("추세 MACD 30분 + OBV 히스토그램 전환") == 2 and tabs.count("추세 MACD 30분 + 3합 히스토그램 0선 돌파") == 3
    assert "OBV 진한색 + AC" not in tabs and "추세 바 30분" not in tabs
