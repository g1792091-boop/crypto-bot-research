"""풋프린트 분석(진입 신호 · 지지저항 판정 · 다음 봉)."""
from fastapi.testclient import TestClient

from app.main import app
from app.quant import footprint
from app.quant.scanner import SIGNALS, Scanner

c = TestClient(app)
T0 = 1_700_000_000


def _bar(i, o, h, l, cl, levels, delta=None):
    vol = sum(s + b for _, s, b in levels)
    d = sum(b - s for _, s, b in levels) if delta is None else delta
    return {"time": T0 + i * 3600, "open": o, "high": h, "low": l, "close": cl, "volume": vol, "delta": d, "levels": levels,
            "stacked": [], "imb_buy": [], "imb_sell": [], "poc": levels[0][0]}


def test_absorption_long_signal_and_outcome():
    bars = [_bar(i, 100, 101, 99, 100, [[99, 5, 5], [100, 5, 5]]) for i in range(12)]
    # 새 저점을 찍으며 바닥에서 매도가 쏟아졌는데(매도 30) 윗부분에서 마감 → 매도 흡수 롱
    bars.append(_bar(12, 99.5, 100.2, 98.5, 100.0, [[98.5, 30, 3], [99, 4, 4], [99.5, 2, 8], [100, 2, 6]]))
    bars.append(_bar(13, 100, 104, 99.9, 103.8, [[100, 1, 5], [103, 1, 5]]))          # 익절(2R) 먼저 닿음
    bars.append(_bar(14, 103.8, 104, 103, 103.5, [[103, 1, 1]]))                       # 진행 중 봉
    sig = footprint.bar_signals(bars, [1.0] * len(bars), 0.5)
    s = next(x for x in sig if x["time"] == bars[12]["time"])
    assert s["dir"] == "long" and any("흡수" in r for r in s["reasons"]) and s["stop"] < 98.5 and s["outcome"] == "take"


def test_level_tests_hold_and_break():
    bars = [_bar(i, 101, 102, 100, 101.5, [[100, 8, 2], [101, 3, 3]]) for i in range(10)]   # 100 에 매도 몰림, 위에서 마감
    bars.append(_bar(10, 101.5, 102, 101, 101.8, [[101, 1, 1]]))
    t = footprint.level_tests(bars, [{"price": 100.2, "source": "테스트"}], 1.0, 0.5)[0]
    assert t["role"] == "support" and t["status"] == "holding" and "흡수" in t["text"]
    broken = [_bar(i, 101, 101.5, 99, 99.5, [[99, 2, 2], [100, 2, 2], [101, 1, 1]]) for i in range(10)]
    broken.append(_bar(10, 99.5, 99.6, 98, 98.2, [[98, 1, 1]]))
    t = footprint.level_tests(broken, [{"price": 100.2, "source": "테스트"}], 1.0, 0.5)[0]
    assert t["role"] == "resistance" and t["status"] in ("broken", "holding")   # 이제 위에 있으므로 저항으로 판정


def test_next_bar_odds_buckets():
    cs = []
    for i in range(400):
        up = i % 2 == 0                                   # 매수 우위로 끝난 봉 다음엔 항상 하락, 반대도 마찬가지
        cs.append({"time": T0 + i * 3600, "open": 100, "high": 101, "low": 99, "close": 100.8 if up else 99.2,
                   "volume": 10, "taker_buy": 8 if up else 2})
    o = footprint.next_bar_odds(cs)
    assert o["last_closed"]["n"] > 100 and o["last_closed"]["p_up"] in (0, 100)


def test_footprint_analysis_endpoint():
    r = c.get("/api/footprint", params={"symbol": "eth", "interval": "1h", "analysis": "true"}).json()
    a = r["analysis"]
    assert {"signals", "signal_stats", "levels", "next"} <= set(a) and r["bars"]
    assert all(lv["status"] in ("holding", "weakening", "broken", "untested") for lv in a["levels"])


def test_scanner_has_footprint_not_rotation(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    assert "footprint" in SIGNALS and "rotation" not in SIGNALS
    sc = Scanner()
    sc.set_config(symbols=["eth"], intervals=["1h"])
    sc.scan()
    assert not sc.errors
