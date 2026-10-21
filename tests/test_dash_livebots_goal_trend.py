"""실거래 › 목표 rebuilt for the 추세판단 봇 (owners 10/21 night; dash/more/liveinsight.py goal: ``path``, ``grid``, ``progress``,
the break-even from its own numbers; screens/livebots-goal.js): the goal is x6 a month, the replay made -4.9 % a trade.

On the world of tests/test_dash_livebots_fees.py (the trend bot's paper and both executors since 10/21 23:28 KST):
- 목표 경로: x6 over the replay's 1.11 a weekday x the month's 22 weekdays (about 24 entries: +7.6 % of the wallet, about
  +19 % net ROE a trade at 40 % margin) and over the bot's own speed (few weekdays: said so, the need stays the replay's),
  the actual rows (replay 가상 · paper · each executor, the old bot's trade left out);
- 무엇이면 닿나: every cell is exp(n [p ln(1 + m w) + (1 - p) ln(1 - m l)]), the need column gives x6 back, the replay's spot;
- the break-even and the needed win rate from the replay's average win / loss under 20 own trades (never the old bot's
  +10 % / -50 %), its own from 20; no numbers at all: None with the reason;
- each account against the x6 path this month, from the bot's start (paper money and real money);
- another bot: no path, no grid, no progress, the old break-even as before;
- the view in node: the words, the old bot's numbers nowhere, no null / NaN; the house rules of the css."""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_dash_livebots_fees import BAD, CFG, FEE, NOW, ROOT, SINCE, _node, _read, build_world, house_rules  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import liveinsight as I  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("goal"))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    yield
    L._cache.clear()


# ================================================================ 목표 (server)
def test_goal_path_for_the_trend_bot(world):
    d = json_finite(I.goal(world["p"], NOW, world["more"]))
    p = d["path"]
    assert p["target_mult"] == 6.0 and p["margin"] == 0.4 and p["month_weekdays"] == pytest.approx(22.0)
    rep, live = p["rows"]
    n = 1.11 * 22
    assert rep["id"] == "replay" and rep["n"] == pytest.approx(n) and rep["growth"] == pytest.approx(6 ** (1 / n) - 1)
    assert rep["roe"] == pytest.approx((6 ** (1 / n) - 1) / 0.4) and abs(rep["roe"] - 0.19) < 0.005        # about +19 % a trade
    # its own: 4 entries on Wed 0.02 + Thu + Fri + Mon + Tue 0.5 weekdays (few: under 5 weekdays)
    wd = I.weekday_days(SINCE, NOW)
    assert live["id"] == "live" and live["entries"] == 4 and live["per_weekday"] == pytest.approx(4 / wd) and live["few"] is True
    assert live["n"] == pytest.approx(4 / wd * 22) and live["roe"] == pytest.approx((6 ** (1 / live["n"]) - 1) / 0.4)
    # the actual rows are held against the replay's speed until the bot's own is measured over 5 weekdays
    assert p["need_roe"] == pytest.approx(rep["roe"]) and p["need_src"] == "replay"
    act = {r["id"]: r for r in p["actual"]}
    assert (act["replay"]["n"], act["replay"]["win_rate"], act["replay"]["roe_mean"]) == (89, 0.494, -0.0492)
    pts = world["pts"]
    assert act["paper"]["n"] == 4 and act["paper"]["roe_mean"] == pytest.approx(sum(t["roe"] for t in pts) / 4) and act["paper"]["small"]
    by = world["by"]
    assert act["bybit"]["n"] == 3 and act["bybit"]["real"] is True and act["bybit"]["est"] == 1      # the old trade is not the bot's
    assert act["bybit"]["win_rate"] == pytest.approx(sum(1 for t in by[1:] if t["pnl"] > 0) / 3)
    assert act["mexc"]["n"] == 2


def test_goal_grid_and_break_even_from_its_own_numbers(world):
    d = json_finite(I.goal(world["p"], NOW, world["more"]))
    rep = I.replay_numbers()
    w, l = rep["avg_win"], -rep["avg_loss"]
    assert w == pytest.approx(0.1230, abs=1e-3) and l == pytest.approx(0.2176, abs=1e-3)
    # the break-even from the replay's averages (under 20 trades of its own), never the old +10 % / -50 %
    be = I.need_win(1.0, 1, 0.4, w, l)
    assert d["break_even"] == pytest.approx(be) and abs(d["break_even"] - 0.655) < 0.005
    assert d["break_even_plain"] == [pytest.approx(l / (w + l))] * 2 and abs(d["break_even_plain"][0] - 0.639) < 0.005
    assert "재현" in d["break_even_ko"] and "+12.3%" in d["break_even_ko"] and "−21.8%" in d["break_even_ko"] and "증거금 40%" in d["break_even_ko"]
    assert d["break_even"] != pytest.approx(I.BREAK_EVEN) and d["record"]["break_even"] == d["break_even"]
    g = d["grid"]
    n = 1.11 * 22                                                            # the live count is under 5 weekdays: the replay's
    assert g["state"] == "ok" and g["n_src"] == "replay" and g["n"] == pytest.approx(n) and g["l"] == pytest.approx(l) and g["l_src"] == "replay"
    assert [r["p"] for r in g["rows"]] == list(I.GRID_WINS) and g["avg_wins"] == list(I.GRID_AVG_WIN)
    for r in g["rows"]:
        for c in r["cells"]:
            want = math.exp(n * (r["p"] * math.log(1 + 0.4 * c["w"]) + (1 - r["p"]) * math.log(1 - 0.4 * l)))
            assert c["mult"] == pytest.approx(want) and c["reach"] == (want >= 6.0)
        # the need column gives x6 back
        assert I._month_mult(n, 0.4, r["p"], r["need_w"], l) == pytest.approx(6.0)
    assert not any(c["reach"] for c in g["rows"][0]["cells"]) and g["rows"][-1]["cells"][-1]["reach"]
    sp = g["spots"][0]
    assert sp["id"] == "replay" and sp["p"] == 0.494 and sp["mult"] == pytest.approx(I._month_mult(n, 0.4, 0.494, w, l)) and sp["mult"] < 1
    assert g["ko"].startswith("가상 계산이에요") and "예측이 아니에요" in g["ko"]
    # the win rate the goal needs uses the same averages
    need = next(a for a in d["accts"] if a["id"] == "paper")["need"]
    assert (need["w"], need["l"], need["w_src"]) == (pytest.approx(w), pytest.approx(l), "replay") and "(재현 · 가상)" in need["src_ko"]


def test_goal_progress_against_the_x6_path(world):
    d = json_finite(I.goal(world["p"], NOW, world["more"]))
    acc = {a["id"]: a for a in d["accts"]}
    mo = I.month_of(NOW)
    wd = I.weekday_days(SINCE, NOW)
    pr = acc["paper"]["progress"]
    old = world["old"]
    assert pr["from_ms"] == SINCE and pr["from_ko"] == "추세판단 봇 시작(10/21 23:28)부터"
    assert pr["start_equity"] == pytest.approx(1000.0 + old["pnl"]) and pr["now_equity"] == pytest.approx(world["wallet"])
    assert pr["path_now"] == pytest.approx(6 ** (wd / 22)) and pr["path_end"] == pytest.approx(6 ** (I.weekday_days(SINCE, mo["to_ms"]) / 22))
    assert pr["mult"] == pytest.approx(world["wallet"] / (1000.0 + old["pnl"])) and pr["vs_path"] == pytest.approx(pr["mult"] / pr["path_now"] - 1)
    b = acc["bybit"]["progress"]
    assert b["start_equity"] == 104.0 and b["now_equity"] == 98.8 and b["late_start"] is False   # the last sample before the start
    w = acc["mexc"]["progress"]
    assert w["start_equity"] == 100.0 and w["from_ms"] == SINCE                                 # the sample at 22:00 is before 23:28


def test_goal_trend_avg_and_another_bot(world, tmp_path):
    rep = I.replay_numbers()
    few = I.trend_avg_of({"n": 5, "avg_win": 0.3, "avg_loss": -0.1}, rep)
    assert few["src"] == "replay" and few["w"] == pytest.approx(rep["avg_win"])
    own = I.trend_avg_of({"n": 20, "avg_win": 0.3, "avg_loss": -0.1}, rep)
    assert (own["src"], own["w"], own["l"]) == ("own", 0.3, 0.1) and own["src_ko"] == "추세판단 봇 시작 뒤 닫힌 거래 20번"
    none = I.trend_avg_of({"n": 3}, {"state": "missing"})
    assert none["w"] is None and none["src"] == "none"
    cx = {"trend": {"name": "x"}, "cfg": CFG, "_avg": none}
    assert I.break_even_of(cx) == (None, [], I.TREND_BE_NONE_KO.format(k=20))
    # another bot: no path, no grid, no progress, the old break-even as before
    other = str(tmp_path / "other.db")
    s = Store3(other)
    s.put_state("combo_run", SINCE, {"taker_fee": FEE, "config": {**CFG, "trend": None, "name": "규칙봇 15"}})
    s.close()
    d = I.goal(dict(world["p"], paper=other), NOW, world["more"])
    assert d["path"] is None and d["grid"] is None and d["break_even"] == I.BREAK_EVEN
    assert all("progress" not in a for a in d["accts"])


def test_the_goal_view_draws_the_trend_bots_goal(world, tmp_path):
    g = I.goal(world["p"], NOW, world["more"])
    out = _node(tmp_path, """const v = await run(G.goalView, D_g); const t = texts(v.el);
    console.log(JSON.stringify({t, rows: G.pathRows(D_g.path), act: G.actualRows(D_g.path), grid: G.gridView(D_g.grid), spots: G.spotWords(D_g.grid),
      pw: G.progressWords(D_g.accts[0].progress, D_g.target), pw0: G.progressWords({state: 'none'}), pace: [G.paceWords({need: 6, wins: 47}, 0.04),
      G.paceWords({need: 6, wins: 50})], none: [G.pathRows(null).length, G.actualRows(null).length, G.gridView(null), G.gridView({state: 'none'})]}));""", g=g)
    t = out["t"]
    for w in ("목표 경로 (한 달 ×6)", "재현 진입 속도 (평일 하루 1.11번 × 평일 22일)", "한 달 약 24번", "거래마다 지갑 +7.6%", "평균 순ROE +19.0%",
              "이 봇 실제 진입 속도", "아직 흔들려요", "재현 (가상)", "89번", "49%", "−4.9%", "필요한 것과 차이 (재현 진입 속도 기준)",
              "페이퍼(연습)", "바이비트", "WOO X Pro",
              "표본 적음", "모든 거래가 똑같이 번다고 칠 때의 숫자예요", "무엇이면 닿나", "×6에 필요한 이긴 거래 평균", "재현(가상): 이긴 비율 49%",
              "가상 계산이에요", "이번 달 ×6 경로 (연습 돈)", "이번 달 ×6 경로 (진짜 돈)", "×6 경로라면 지금", "추세판단 봇 시작(10/21 23:28)부터",
              "월말 경로", "본전 약 65%", "단순 합으로는 64%", "+4% 승리로"):
        assert w in t, w
    for old in ("본전 약 86%", "82%~83%", "본전 약 85%", "6.2번", "+3% 승리로", "약 75%", "이길 때 +10%, 질 때 −50%, 증거금 30%"):
        assert old not in t, old
    assert not BAD.search(t), BAD.search(t)
    assert [r["id"] for r in out["rows"]] == ["replay", "live"] and out["rows"][1]["few"] is True
    act = {r["id"]: r for r in out["act"]}
    gap = (-0.0492 - g["path"]["need_roe"]) * 100
    assert act["replay"]["gap"] == f"{gap:.1f}%p".replace("-", "−") and act["replay"]["gapTone"] == "down" and act["paper"]["small"] is True
    gr = out["grid"]
    assert gr["head"][0] == "이긴 비율 \\\\ 이긴 거래 평균".replace("\\\\", "\\") and gr["head"][1] == "+10%" and len(gr["rows"]) == 5
    assert gr["rows"][-1]["cells"][-1]["reach"] is True and gr["rows"][0]["cells"][0]["reach"] is False
    assert out["spots"][0].startswith("재현(가상): 이긴 비율 49%") and out["pw"]["ko"].startswith("×6 경로라면 지금 ×") and out["pw0"] is None
    assert out["pace"][0].endswith("+4% 승리로 47번 (지는 거래 없이)") and out["pace"][1].endswith("+3% 승리로 50번 (지는 거래 없이)")
    assert out["none"] == [0, 0, None, None]


def test_the_files_keep_the_house_rules():
    house_rules("livebots-goal", "lbg")
    doc = _read(ROOT, "docs", "livedash-ko.md")
    assert "목표 경로" in doc and "무엇이면 닿나" in doc and "목표 경로" in _read(ROOT, "paperbot", "dash", "static", "v4", "INVENTORY.md")
