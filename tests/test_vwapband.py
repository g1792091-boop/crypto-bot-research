"""운이냐 고장이냐 (paperbot/vwapband.py; owners 10-25, docs/vwap-bot-ko.md 9): the 'VWAP 개선판''s live record against
its own 5-year paper trades (research/vwap30/band.json, made by research/vwap30/code/vwband.py from the same 5,805 trades
as scale.json).

- the research file: the same trades as scale.json, the 17 days as the guide states them (37 wins 3 losses, x3.64,
  -23.7 %), the losing runs and the stretches add up;
- the three checks against hand-made records: the binomial band (checked by brute force), the losing run, the deepest
  drop (equity, margin share, or the bot's own 40 % margin: said which), the verdict words and their thresholds;
- the honest words (the 5 years lost per trade; 정상 범위 = as in the 5 years) and the 17 days labelled as picked;
- a file that cannot be read is said, never replaced by numbers; the morning check's lines."""
from __future__ import annotations

import json
import math
import os

import pytest

from paperbot import vwapband as B

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _fresh():
    B._cache.clear()
    yield
    B._cache.clear()


def _trades(results, start=1000.0, frac=0.4, win_roe=0.11, loss_roe=-0.45):
    """Closed paper trades (oldest first) with the engine's equity: each a win (+11 % net ROE) or a loss (-45 %) on 40 %
    of the account."""
    eq, out = start, []
    for i, won in enumerate(results):
        roe = win_roe if won else loss_roe
        pnl = eq * frac * roe
        eq += pnl
        out.append({"id": i, "pnl": pnl, "roe": roe, "equity_after": eq})
    return out


def test_the_research_file_is_the_scale_trades_and_adds_up():
    ref = B.load()
    assert ref["state"] == "ok" and ref["src"] == "research/vwap30/band.json"
    with open(os.path.join(ROOT, "research", "vwap30", "scale.json"), encoding="utf-8") as fh:
        scale = json.load(fh)
    for k in ("trades", "win_rate", "avg_win_roe", "avg_loss_roe", "breakeven_win", "data_end"):
        assert ref[k] == scale[k], k
    assert ref["roe_per_trade"] < 0 and ref["win_rate"] < ref["breakeven_win"]           # the 5 years lost per trade
    st = ref["streaks"]
    assert sum(st["by_len"].values()) == st["runs"] and st["reach"]["1"] == st["runs"] and str(st["longest"]) in st["by_len"]
    assert sum(int(k) * v for k, v in st["by_len"].items()) == ref["trades"] - ref["wins"]  # every loss is in one run
    for m, w in ref["windows"].items():
        assert w["count"] == ref["trades"] - int(m) + 1 and sum(w["wins"]) == w["count"] and sum(w["dd_bins"]) == w["count"]
        assert len(w["wins"]) == int(m) + 1 and len(w["dd_bins"]) == ref["dd_bins"]
    p = ref["pick17"]                                     # docs/vwap-bot-ko.md 3장: the research's 17 days at margin 40 %
    assert (p["n"], p["wins"], p["losses"]) == (40, 37, 3) and p["mult"] == pytest.approx(3.64, abs=0.005)
    assert p["max_dd"] == pytest.approx(0.237, abs=0.0005)


def test_the_binomial_band_by_brute_force():
    for n, k, p in ((10, 6, 0.72), (50, 30, 0.7201), (3, 0, 0.5), (1, 1, 0.3)):
        brute = sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
        assert B.binom_cdf(k, n, p) == pytest.approx(brute, rel=1e-9)
    assert B.binom_cdf(-1, 5, 0.5) == 0.0 and B.binom_cdf(5, 5, 0.5) == 1.0
    assert B.binom_q(0.05, 50, 0.7201) == 31 and B.binom_q(0.95, 50, 0.7201) == 41
    assert B.binom_cdf(1000, 2000, 0.7) < 1e-50                                           # a long record: no overflow


def test_the_verdict_words_and_their_lines():
    assert [B.verdict_of(x) for x in (None, 1.0, 0.05, 0.0499, 0.01, 0.0099, 0.0)] == \
        ["정상 범위", "정상 범위", "정상 범위", "드묾", "드묾", "아주 드묾", "아주 드묾"]
    assert B.worst(["정상 범위", "아주 드묾", "드묾"]) == "아주 드묾" and B.worst([]) == "정상 범위"
    assert B.VERDICT_KO["아주 드묾"] == "아주 드묾: 설계와 다르게 돌고 있을 수 있어요"
    assert [B.share_ko(x) for x in (0.4712, 0.025, 0.0026, 0.0004, None)] == ["47%", "2.5%", "0.3%", "0.1% 미만", "—"]


def test_a_record_as_the_five_years_is_in_the_normal_range():
    ref = B.load()
    b = B.band(_trades([True, True, False, True, True, True, False, True, True, True] * 5), 1000.0)
    assert b["state"] == "ok" and (b["n"], b["wins"]) == (50, 40) and not b["small"]
    w = b["win"]
    assert (w["lo"], w["hi"]) == (31, 41) and w["p5y"] == ref["win_rate"] and w["verdict"] == "정상 범위"
    assert w["p_low"] == pytest.approx(B.binom_cdf(40, 50, ref["win_rate"]))
    assert w["ko"].startswith("승률 40/50승(80%) · 5년 승률(72.0%)이면 50번에 보통 31~41승") and w["ko"].endswith("→ 정상 범위")
    assert w["emp"]["m"] == 50 and 0 < w["emp"]["share"] <= 1 and "5년의 실제 50번 구간" in w["emp"]["ko"]
    assert b["streak"]["now"] == 0 and b["streak"]["ko"] == "지금 연패 없음(마지막 거래가 이김) → 정상 범위"
    d = b["dd"]
    assert d["how"] == "equity" and d["m"] == 50 and d["verdict"] == "정상 범위"
    # the deepest drop of the record by hand (the account after each trade against its running peak)
    eq, peak, deep = 1.0, 1.0, 0.0
    for t in _trades([True, True, False, True, True, True, False, True, True, True] * 5):
        eq *= 1 + 0.4 * t["roe"]
        peak = max(peak, eq)
        deep = max(deep, 1 - eq / peak)
    assert d["deepest"] == pytest.approx(deep) and d["now"] == pytest.approx(1 - eq / peak)
    assert b["verdict"] == "정상 범위" and b["rare"] is False


def test_a_losing_run_and_a_deep_drop_are_rare_and_say_so():
    ref = B.load()
    st = ref["streaks"]
    b = B.band(_trades([True] * 15 + [False] * 4), 1000.0)
    s = b["streak"]
    assert s["now"] == 4 and s["reach"] == st["reach"]["4"] and s["share"] == pytest.approx(st["reach"]["4"] / st["runs"])
    assert s["verdict"] == B.verdict_of(s["share"]) == "드묾"
    assert s["ko"].startswith(f"지금 4연패 · 5년 연패 {st['runs']:,}번 중 4연패 이상 {st['reach']['4']:,}번(")
    b5 = B.band(_trades([True] * 15 + [False] * 5), 1000.0)
    assert b5["streak"]["verdict"] == "아주 드묾" and b5["verdict"] == "아주 드묾" and b5["verdict_ko"] == B.VERY_RARE_KO
    longest = st["longest"]
    far = B.streak_check(longest + 1, ref)
    assert far["verdict"] == "아주 드묾" and f"5년 동안 가장 긴 연패는 {longest}연패였어요" in far["ko"]
    one = B.streak_check(1, ref)
    assert one["verdict"] == "정상 범위" and f"5년 거래의 {1 - ref['win_rate']:.0%}가 진 거래라 흔한 일" in one["ko"]
    # the win rate far below the 5 years: rare by the binomial (the chance of this few wins or fewer)
    low = B.band(_trades([True, False] * 25), 1000.0)
    assert low["win"]["p_low"] < 0.01 and low["win"]["verdict"] == "아주 드묾"
    # a drop deeper than almost every 5-year stretch of that length
    deep = B.dd_check([-0.2] * 4 + [0.04] * 6, 10, ref, "equity")
    assert deep["deepest"] == pytest.approx(1 - 0.8 ** 4) and deep["verdict"] in ("드묾", "아주 드묾") and deep["share"] < 0.05
    assert deep["ko"].startswith("시작 뒤 가장 깊은 낙폭 −59%") and "5년 10번 구간 중 이만큼 깊었던 곳" in deep["ko"]


def test_a_good_stretch_is_said_good_luck_and_the_17_days_are_labelled():
    ref = B.load()
    w = B.win_check(40, 37, ref)
    assert w["verdict"] == "정상 범위" and w["good"] and "5년보다 드물게 좋음: 운이 좋은 구간일 수 있어요" in w["ko"]
    rv = B.ref_view(ref)
    assert rv["pick17"]["ko"].startswith("참고 17일(10/05~10/23, 이 봇을 고를 때 본 가장 좋은 기간): 40번 37승 3패(92.5%)")
    assert "고른 기간이라 앞으로의 기대치가 아니에요" in rv["pick17"]["ko"]
    assert rv["honest_ko"].startswith(f"솔직히: 5년 페이퍼 {ref['trades']:,}번은 승률 72.0%로 본전 승률 78.6%보다 낮아 거래당 손해였어요")
    assert "'정상 범위'는 5년처럼 돈다는 뜻이지 돈을 번다는 뜻이 아니에요" in rv["honest_ko"] and "−3.3%" in rv["honest_ko"]


def test_how_the_account_steps_are_measured():
    # the engine's equity: exact; the paper's starting wallet with its own P&L; an executor's margin share; else 40 %
    g, how = B.steps([{"pnl": -20.0, "roe": -0.5, "equity_after": 80.0}])
    assert g == [pytest.approx(-0.2)] and how == "equity"
    g, how = B.steps([{"pnl": 10.0, "roe": 0.1}, {"pnl": -22.0, "roe": -0.5}], initial=100.0)
    assert g == [pytest.approx(0.1), pytest.approx(-0.2)] and how == "equity"
    g, how = B.steps([{"pnl": -1.0, "roe": -0.5}], margin_frac=0.4)
    assert g == [pytest.approx(-0.2)] and how == "margin_frac"
    g, how = B.steps([{"pnl": -1.0, "roe": -0.25}])
    assert g == [pytest.approx(-0.1)] and how == "margin40" and B.HOW_KO[how] == "증거금 40% × 순ROE로 계산"
    assert B.drops([0.1, -0.5, 0.2]) == (pytest.approx(0.5), pytest.approx(1 - 0.66 / 1.1))
    assert B.losing_run([{"pnl": 1}, {"pnl": -1}, {"pnl": 0}]) == 2 and B.losing_run([]) == 0


def test_an_empty_record_and_an_unreadable_file(tmp_path, monkeypatch):
    assert B.band([]) == {"state": "empty", "n": 0, "ko": "아직 닫힌 거래가 없어요", "verdict": None}
    assert B.lines(B.band([]), "페이퍼") == ["- 운이냐 고장이냐 · 페이퍼: 아직 닫힌 거래가 없어요"]
    monkeypatch.setattr(B, "BAND_FILE", str(tmp_path / "gone.json"))
    b = B.band(_trades([True, False]))
    assert b["state"] == "missing" and b["reason_ko"] == B.MISSING_KO and "win" not in b
    assert B.lines(b, "딥코인 실거래") == [f"- 운이냐 고장이냐 · 딥코인 실거래: {B.MISSING_KO}"] and B.ref_line() is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"trades": 1}), encoding="utf-8")
    monkeypatch.setattr(B, "BAND_FILE", str(bad))
    assert B.load()["state"] == "error" and B.ref_view()["state"] == "error" and B.streak_ko(B.band(_trades([False]))) is None


def test_the_morning_lines():
    b = B.band(_trades([True] * 8 + [False] * 2), 1000.0)
    head, detail = B.lines(b, "페이퍼")
    assert head == "- 운이냐 고장이냐 · 페이퍼(거래 10번): 정상 범위 · 아직 표본 적음"
    assert detail.startswith("  승률 8/10승(5년이면 보통 5~9승, 이만큼 이하 ") and "지금 2연패(5년 연패 중 27%가 이만큼) 정상" in detail
    assert "가장 깊은 낙폭 −33%(5년 10번 구간 중 " in detail                 # 1 - 0.82 x 0.82
    line = B.ref_line()
    assert line.startswith("  기준: 5년 페이퍼 5,805번(승률 72.0%, 본전 78.6% 아래라 거래당 손해: 정상 범위 = 5년처럼 돈다는 뜻)")
    assert line.endswith("17일(10/05~10/23) 40번 37승 3패는 고른 가장 좋은 기간이라 기대치 아님")
    assert B.streak_ko(b) == b["streak"]["ko"] and b["streak"]["ko"].endswith("→ 정상 범위")
