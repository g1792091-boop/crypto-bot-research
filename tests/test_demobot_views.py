"""Demo lab view log (CONTRACT 7.3): parsing, scoring rules, commands, verdict."""
import numpy as np
import pytest

from demobot import store as ST
from demobot import views as V

NOW = 1_791_000_000_000
M15 = 900_000


def test_parse_basic_and_errors():
    st, v, notes = V.parse("관점 BTC 숏 B 84750-84840 C 85300 손절 85600", NOW)
    assert st == "ok" and v["coin"] == "BTCUSD" and v["side"] == -1
    assert v["zones"]["B"] == [84750.0, 84840.0] and v["zones"]["C"] == [85300.0, 85300.0] and v["stop"] == 85600.0
    assert notes == ["시각 없음: 받은 시각 사용"] and v["t_ms"] == NOW
    st, v, _n = V.parse("관점 10/08 15:54 ethusdt 롱 B 2,122~2,130 목표 2160/2190 메모 역추세 확인", NOW)
    assert st == "ok" and v["coin"] == "ETHUSD" and v["targets"] == [2160.0, 2190.0] and v["memo"] == "역추세 확인"
    assert v["zones"]["B"] == [2122.0, 2130.0]
    for bad in ("관점 BTC 롱", "관점 XYZ 롱 B 1", "관점 BTC 위 B 1", "관점 BTC 롱 B abc", "관점 BTC 롱 B 1 무엇 2"):
        assert V.parse(bad, NOW)[0] == "err", bad
    assert V.parse("관점 BTC 롱 B 50000", NOW, price_of=lambda c: 90000.0)[0] == "err"     # 30% sanity


def _bars(path, t0):
    return {"ts": t0 + np.arange(len(path), dtype=np.int64) * M15, "o": np.array([p[0] for p in path], float),
            "h": np.array([p[1] for p in path], float), "l": np.array([p[2] for p in path], float),
            "c": np.array([p[3] for p in path], float)}


def test_score_short_touch_and_confirm():
    t0 = (NOW // M15) * M15
    path = [(100, 100.5, 99.8, 100.2), (100.2, 101.6, 100.1, 101.4), (101.4, 101.5, 100.6, 100.7),
            (100.7, 100.8, 98.5, 98.7), (98.7, 99, 96.9, 97.2)] + [(97.2, 97.5, 96.8, 97)] * 200
    b = _bars(path, t0 + M15)
    v = dict(id=1, t_ms=t0 + 60_000, coin="BTCUSD", side=-1, zones={"A": None, "B": [101, 102], "C": None},
             stop=103.0, targets=[], memo="", status="watching")
    s = V.score(v, b, NOW)
    assert s["ref_price"] == 100 and s["reached"] and s["finished"]
    t = s["follow"]["touch"]
    assert t["entry"] == 101.0 and t["legs_ko"] == "익절 · 익절" and abs(t["R"] - 1.48) < 0.01
    c = s["follow"]["confirm"]
    assert abs(c["entry"] - 100.7 * (1 - 0.0002)) < 1e-9 and c["legs_ko"] == "익절 · 시간"


def test_score_stop_and_missed():
    t0 = (NOW // M15) * M15
    # long, zone 98-99 below, stop 97; price drops through the stop in the touch bar
    path = [(100, 100.2, 99.5, 99.6), (99.6, 99.7, 96.5, 96.8)] + [(96.8, 97, 96.5, 96.9)] * 200
    b = _bars(path, t0 + M15)
    v = dict(id=2, t_ms=t0 + 60_000, coin="BTCUSD", side=1, zones={"A": None, "B": [98, 99], "C": None},
             stop=97.0, targets=[], memo="", status="watching")
    s = V.score(v, b, NOW)
    assert s["follow"]["touch"]["legs_ko"] == "손절" and s["follow"]["touch"]["R"] < -1
    assert s["follow"]["confirm"]["status"] == "missed"
    # never reached in 48 h
    path = [(100, 100.5, 99.8, 100.2)] * 300
    s = V.score(dict(v, id=3), _bars(path, t0 + M15), NOW)
    assert s["reached"] is False and s["follow"]["touch"]["status"] == "missed" and s["finished"]


def test_commands_and_snapshot(tmp_path):
    conn = ST.connect(str(tmp_path / "d.db"))
    V.ensure(conn)
    out = V.handle(conn, {"text": "관점 BTC 롱 B 99 C 98 손절 97", "date_ms": NOW}, NOW)
    assert out[0][0] == "view_ack" and out[0][1]["id"] == 1
    assert V.handle(conn, {"text": "안녕하세요", "date_ms": NOW}, NOW) == []
    assert V.handle(conn, {"text": "관점 BTC", "date_ms": NOW}, NOW)[0][0] == "view_err"
    assert V.handle(conn, {"text": "관점도움"}, NOW)[0][0] == "view_help"
    assert V.handle(conn, {"text": "관점목록"}, NOW)[0][1]["views"][0]["id"] == 1
    assert V.handle(conn, {"text": "취소 1"}, NOW) == [("view_cancel", {"id": 1, "ok": True})]
    assert V.handle(conn, {"text": "취소 1"}, NOW) == [("view_cancel", {"id": 1, "ok": False})]
    snap, newly = V.snapshot(conn, {}, NOW)
    assert snap["summary"]["n"] == 0 and snap["views"][0]["status"] == "cancelled" and newly == []


def test_verdict_needs_30():
    scored = []
    for i in range(30):
        scored.append(dict(id=i, status="done", finished=True, dir={"4h": 1.0, "24h": 1.0, "48h": 1.0}, reached=True,
                           follow={"touch": dict(status="closed", R=0.5, entry_ms=NOW + i * 7 * 86400000,
                                                 exit_ms=NOW + i * 7 * 86400000 + 1, wallet20_pct=1.0),
                                   "confirm": dict(status="missed")}))
    s = V.summarize(scored[:29])
    assert s["verdict_ko"].startswith("표본 부족")
    s = V.summarize(scored)
    assert "동전보다 확실히 나음" in s["verdict_ko"] and "바로 진입" in s["verdict_ko"]
    assert s["dir"]["24h"]["p"] < 1e-6
