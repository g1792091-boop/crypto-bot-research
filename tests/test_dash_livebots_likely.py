"""진입 가능성 순위 (owners 10/19 "각 매매법마다 진입 가능성 몇%, 순위별로 뭐가 제일 진입가능성이 높은지"): how often, in the 5-year
backtest of the settings the bot runs, an hour like this one (KST day group and hour) was followed by each strategy's
entry signal within 1 / 4 / 24 hours (deploy/combo.live-ac.likely.json), ranked with the break signals waiting now first.
Past frequency, never a forecast (dash/more/livebots.py likely, likely_rows; GET /api/v4/livebots/likely)."""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import events  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW, MIN, H, DAY = W.NOW, W.MIN, W.H, W.DAY
T0W = NOW - 10 * MIN                                   # the world's WAITING row: BCH long, N03_ADX_GC 15m


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    f = tmp_path / "macro.csv"
    f.write_text("ts_utc,kind,source_url\n", encoding="utf-8")
    monkeypatch.setattr(events, "PATH", f)
    events.reset()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    L._likely_ref.clear()
    yield
    events.reset()
    L._likely_ref.clear()


def test_the_file_matches_the_config_the_bot_runs():
    ref = L.load_likely()
    with open(os.path.join(ROOT, "deploy", "combo.live-ac.json"), "rb") as f:
        raw = f.read()
    assert ref["source"]["config_sha256"] == hashlib.sha256(raw).hexdigest(), \
        "deploy/combo.live-ac.json changed: rebuild deploy/combo.live-ac.likely.json (likely27.py)"
    cfg = json.loads(raw)["members"]
    assert set(ref["strategies"]) == {m["strategy"] for m in cfg}
    for s, e in ref["strategies"].items():
        assert e["settings"] == sum(1 for m in cfg if m["strategy"] == s)
    for per in ("recent", "all"):
        for g in ("mt", "fri", "sat", "sun"):
            assert ref["samples"][per][g] > 50
            for h in range(24):
                bot = ref["bot"][per]
                assert bot["w1"][g][h] <= bot["w4"][g][h] <= bot["w24"][g][h] <= 100
                for e in ref["strategies"].values():
                    for w in ("w1", "w4", "w24"):
                        assert 0 <= e[per][w][g][h] <= bot[w][g][h]               # one strategy never beats the whole bot
                nxt = sum(e[per]["next"][g][h] for e in ref["strategies"].values())
                assert 95 <= nxt <= 100.6, (per, g, h, nxt)        # the next entry is some strategy's (1-decimal rounding)


def test_kst_cell():
    mon = 1792335600000                                     # 2026-10-19 00:00 KST (Monday)
    assert L.kst_cell(mon + 30 * MIN) == ("mt", 0)
    assert L.kst_cell(mon + 3 * DAY + 23 * H) == ("mt", 23)            # Thursday 23:00
    assert L.kst_cell(mon + 4 * DAY + 23 * H) == ("fri", 23)
    assert L.kst_cell(mon + 5 * DAY + 9 * H) == ("sat", 9)
    assert L.kst_cell(mon + 6 * DAY) == ("sun", 0)


def _ref(**over):
    def cells(v):
        return {g: [v] * 24 for g in ("mt", "fri", "sat", "sun")}

    def strat(w4, w24, nxt, sat=0.0):
        e = {per: {"w1": cells(w4 / 4), "w4": cells(w4), "w24": cells(w24), "next": cells(nxt)} for per in ("recent", "all")}
        for per in ("recent", "all"):
            e[per]["w1"]["sat"] = [sat] * 24
        return {"type": "추세", "settings": 2, "tfs": ["15m"], "signals": {"all": 100, "recent": 30}, **e}
    ref = {"bot": {per: {"w1": cells(20.0), "w4": cells(45.0), "w24": cells(90.0), "next_h_median": cells(4.5)} for per in ("recent", "all")},
           "samples": {per: {g: 300 for g in ("mt", "fri", "sat", "sun")} for per in ("recent", "all")},
           "strategies": {"A": strat(10.0, 40.0, 15.0), "B": strat(5.0, 30.0, 8.0, sat=2.0), "C": strat(5.0, 35.0, 9.0)}, "source": {}}
    ref["strategies"].update(over)
    return ref


def test_ranking_waits_first_then_four_hours_then_a_day():
    mem = [{"strategy": s, "tf": "15m"} for s in ("A", "B", "C", "D")]
    out = L.likely_rows(_ref(), NOW, mem, [])
    assert [r["strategy"] for r in out["rows"]] == ["A", "C", "B", "D"]         # D: not in the file, last, no numbers
    assert [r["rank"] for r in out["rows"]] == [1, 2, 3, 4]
    d = out["rows"][-1]
    assert d["known"] is False and d["p"]["w4"] == {"recent": None, "all": None}
    assert out["rows"][0]["p"]["w4"] == {"recent": 10.0, "all": 10.0} and out["rows"][0]["n_settings"] == 1
    assert out["cell"]["group"] == "mt" and out["bot"]["w4"]["recent"] == 45.0 and out["bot"]["next_h_median"]["recent"] == 4.5
    waits = [{"strategy": "B", "symbol": "BCHUSDT", "side": 1, "tf": "15m", "to_go": 0.004, "touched": False, "until": NOW + 5 * MIN},
             {"strategy": "C", "symbol": "ETHUSDT", "side": -1, "tf": "15m", "to_go": 0.02, "touched": False, "until": NOW + 9 * MIN},
             {"strategy": "C", "symbol": "SOLUSDT", "side": 1, "tf": "15m", "to_go": -0.001, "touched": True, "until": NOW + 9 * MIN}]
    out = L.likely_rows(_ref(), NOW, mem, waits)
    assert [r["strategy"] for r in out["rows"]] == ["C", "B", "A", "D"]         # beyond its level first, then the closest
    assert [w["symbol"] for w in out["rows"][0]["waits"]] == ["SOLUSDT", "ETHUSDT"]
    fri_noon = 1792335600000 + 4 * DAY + 12 * H + 20 * MIN                   # Friday 12:20 KST: the 24 hours run into Saturday
    hrs = L.likely_rows(_ref(), fri_noon, mem, [])["rows"][2]["hours"]
    assert len(hrs) == 24 and hrs[0]["t"] == fri_noon - 20 * MIN and hrs[0]["p"] == 1.25 and hrs[-1]["p"] == 2.0


def _world(tmp_path, monkeypatch):
    d = tmp_path / "w"
    d.mkdir()
    p = W.build_world(str(d))
    rule = str(d / "paper3.db")
    W.rule_bars(rule, "BCHUSDT", T0W - 20 * MIN, NOW, high=lambda ts: 101.0 if T0W - 15 * MIN <= ts < T0W else 100.5)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", rule)
    return p


def test_the_endpoint_on_the_world(tmp_path, monkeypatch):
    p = _world(tmp_path, monkeypatch)
    r = L.likely(p, NOW)
    assert r["state"] == "ok" and r["cell"]["group"] == "mt" and r["cell"]["samples"]["recent"] > 50
    top = r["rows"][0]
    assert top["strategy"] == "N03_ADX_GC" and top["rank"] == 1 and top["known"] and top["type"]
    assert top["waits"][0]["symbol"] == "BCHUSDT" and top["waits"][0]["level"] == 101.0
    assert 0 < top["p"]["w4"]["recent"] <= r["bot"]["w4"]["recent"] and len(top["hours"]) == 24
    assert top["sig"]["week"] >= 1 and top["sig"]["last_ms"]
    assert r["blocked_ko"] == "이미 포지션이 있어 새 진입 안 함(한 번에 하나)"                  # the world holds a paper position
    assert "예측이 아니라 과거 빈도" in r["note_ko"]
    n = L.whynow(p, NOW)["likely"]
    assert n["state"] == "ok" and [x["strategy"] for x in n["top"]] == [x["strategy"] for x in r["rows"][:L.LIKELY_TOP]]


def test_missing_and_broken_file(tmp_path, monkeypatch):
    p = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(L, "LIKELY_FILE", str(tmp_path / "nope.json"))
    r = L.likely(p, NOW)
    assert r["state"] == "missing" and r["rows"] == [] and "진입 가능성 기준표" in r["reason_ko"]
    assert L.whynow(p, NOW)["likely"]["state"] == "missing"
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    monkeypatch.setattr(L, "LIKELY_FILE", str(bad))
    assert L.likely(p, NOW)["state"] == "error" and L.whynow(p, NOW)["likely"]["state"] == "error"
