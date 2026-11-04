"""Owners 11-04 night: "매매법 확실히 파악 된거지? 대시보드랑 텔레그램 알림 수정했어?". 관제실 follows the running bot: its
coins (the 친구 15분 봇 alone, ZEC; the 레인지 봇 off for good) and its signal bar (5m), the 15m 추세 MACD beside the 30m
one; the morning check counts the bot's own closes (5m)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from paperbot import mixcheck as MC
from paperbot import mixchop as M
from paperbot.dash.more import livedeck as D

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30 + 7 * 60_000


def test_the_deck_follows_the_running_bot(monkeypatch):
    # every mix bot on (a test machine): the 친구 15분 봇's coin and the 레인지 봇's, in COINS' order; the first's bar
    monkeypatch.setattr(D, "bot_order", lambda: ("bybit", "mix", "range"))
    assert D.deck_coins() == ("BTCUSDT", "SOLUSDT", "ZECUSDT") and D.deck_tf() == "5m"
    # the server of 11-04 night: the 바이비트 봇 and the 레인지 봇 off for good -> the ZEC bot alone
    monkeypatch.setattr(D, "bot_order", lambda: ("mix",))
    assert D.deck_coins() == ("ZECUSDT",) and D.deck_tf() == "5m"
    monkeypatch.setattr(D, "bot_order", lambda: ())
    assert D.deck_coins() == D.COINS and D.deck_tf() == "15m"             # (nothing readable: as before)


def _rows(tf_ms, n, seed):
    rng = np.random.default_rng(seed)
    t = (NOW // tf_ms) * tf_ms - tf_ms * np.arange(n - 1, -1, -1)
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    return [{"time": int(t[i]) // 1000, "open": o[i], "high": max(o[i], c[i]) * 1.001, "low": min(o[i], c[i]) * 0.999,
             "close": c[i], "volume": 100 + i % 7} for i in range(n)]


def test_a_coin_on_5m_bars_with_the_15m_trend():
    src = {"5m": _rows(M.MIN5, 1000, 1), "15m": _rows(M.MIN15, 1000, 2), "30m": _rows(M.MIN30, 1000, 3)}
    asked = []

    def candles(sym, tf, n):
        asked.append(tf)
        return src[tf]
    v = D.coin_view("ZECUSDT", candles, NOW, "o4h", "5m")
    assert v["state"] == "ok" and (v["tf"], v["tf_ko"], v["tf_ms"]) == ("5m", "5분", M.MIN5) and sorted(asked) == ["15m", "30m", "5m"]
    assert v["last_ms"] == NOW // M.MIN5 * M.MIN5 and len(v["spark"]) == 288        # (the last closed 5m bar; 24 hours)
    assert set(v["tm15"]) == {"trend", "hist", "yellow"} and v["tm15"]["trend"] in (-1, 0, 1)
    old = D.coin_view("ZECUSDT", candles, NOW, "o4h")                               # (15m as before: no second read)
    assert old["tf"] == "15m" and "tm15" not in old and len(old["spark"]) == 96


def test_the_screen_words_follow_the_bar():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    js = ROOT / "paperbot" / "dash" / "static" / "v4" / "screens" / "livebots-deck.js"
    dom = ROOT / "tests" / "anasyn_dom.mjs"
    script = (f"await import('file://{dom}');\nconst DK = await import('file://{js}');\n"
              "console.log(JSON.stringify({nc: DK.nextClose(7 * 60000, 5 * 60000), nc15: DK.nextClose(7 * 60000),"
              " bar: DK.barOf({coins: [{state: 'error'}, {state: 'ok', tf_ms: 300000, tf_ko: '5분'}]}), bar0: DK.barOf(null),"
              " tm: DK.tmKo({trend30: [[0, 1]], tm30: {hist: 3.2}, tm15: {trend: -1, hist: -0.4}}), tm1: DK.tmKo({trend30: [[0, 1]], tm30: {hist: 3.2}}),"
              " px: DK.priceNow(null, null, {state: 'ok', last: 41.2, tf: '5m', symbol: 'ZECUSDT'}, 0).src}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["nc"] == {"at": 10 * 60000, "left_ms": 3 * 60000} and out["nc15"] == {"at": 15 * 60000, "left_ms": 8 * 60000}
    assert out["bar"] == {"ms": 300000, "ko": "5분"} and out["bar0"] == {"ms": M.MIN15, "ko": "15분"}
    assert out["tm"] == "상승 +3.20 · 15분 하락 −0.40" and out["tm1"] == "상승 +3.20" and out["px"] == "5m"


def test_the_morning_check_counts_the_bots_own_closes():
    t = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
    rows = [{"kind": "skip", "ts": t + 2 * M.MIN5 + 5_000}, {"kind": "entry", "ts": t + 4 * M.MIN5 + 5_000}]
    assert MC.handled_closes(rows, [], None, M.MIN5) == {t + 2 * M.MIN5, t + 4 * M.MIN5}
    assert MC.handled_closes(rows, [], None) == {t}                                 # (30m, as before)
