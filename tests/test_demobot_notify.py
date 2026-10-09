"""Demo lab bot Telegram (demobot/notify.py) and its server kit (deploy/demobot/, docs/demobot/INSTALL_KO.md).

render(): every kind of CONTRACT.md sections 5, 7.3 and 8 in Korean, coin names without the quote, one emoji at most and
only at the start, under Telegram's 4096 characters even with 200 trades. Outbox: queue / flush order, limit, pacing, errors
kept and retried, giving up after 5 tries, warn at most once per 'what' an hour, never raising, the token never
stored. The deploy kit statically: the units' sandbox lines, nothing of the rule bot touched, no env file printed."""
import io
import json
import re
import shutil
import sqlite3
import subprocess
import unicodedata
import urllib.error
from pathlib import Path

import pytest

from demobot import notify as N

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "deploy" / "demobot"
DOC = REPO / "docs" / "demobot" / "INSTALL_KO.md"
T0 = 1_791_590_400_000          # 2026-10-10 00:00 UTC = 09:00 KST
TOKEN = "9" * 10 + ":" + "TESTONLY" * 5          # token-shaped, built here (no literal token in the repo)


def trade(i=0, closed=False, coin="BTCUSD", side=1):
    t = {"account": f"ad-r26-S2-15m-{i}", "name": "S2 자동 · 5거래마다(26주) · 15분", "coin": coin, "side": side,
         "entry": 62345.12, "exit": None, "reason": None, "setting_ko": "ST 14/2 ROC 50",
         "exit_ko": "사다리(규칙봇 방식)", "pnl_by_L": None, "R": None}
    if closed:
        t.update({"name": "S2 친구 값 · 15분", "coin": "DOGEUSD", "side": -1, "entry": 0.21345, "exit": 0.20871,
                  "reason": "lock", "setting_ko": "ST 8/3 ROC 37", "exit_ko": "익절 1.5R · 손절 2ATR",
                  "pnl_by_L": {"20": 12.3, "30": 18.45, "40": 24.6, "50": -30.75}, "R": 1.5})
    return t


DAILY = {"day": "2026-10-10", "live_days": 3.25, "trades_24h": 57,
         "best": [{"id": "fx-fr-S2-15m", "name": "S2 친구 값 · 15분", "L": 50, "pnl_pct": 12.34, "pnl": 123.4}],
         "worst": [{"id": "cf-15m", "name": "동전 던지기 · 15분", "L": 50, "pnl_pct": -45.6}],
         "by_kind": [{"kind": "fixed", "kind_ko": "고정", "mean_pnl_pct": {"20": 1.2, "30": 1.8, "40": 2.3, "50": -2.9}},
                     {"kind": "flip", "mean_pnl_pct": {"20": -1.0, "30": -1.5, "40": -2.0, "50": -2.5}}],
         "passed": 0,
         "leaders": [{"strategy": "S2_ST_ROC", "tf": "15m", "window": "26w", "exit": "house",
                      "label": "ST 20/2 ROC 50", "n": 312, "mean_R": 0.051, "win_rate": 0.41, "luck95": 0.03,
                      "beats_luck": True},
                     {"strategy": "N04_ST_KLINGER", "tf": "30m", "window": "4w", "exit": "tp1.5R_sl2atr",
                      "label": "ST 8/3 KVOx1 sig 13", "n": 120, "mean_R": 0.02, "win_rate": 0.5, "luck95": 0.06,
                      "beats_luck": False}]}
SWITCH = {"account": "fr-S2-15m", "name": "S2 친구 규칙 · 15분", "items": [
    {"coin": "ALL", "L": None, "from_ko": "ST 10/6 ROC 9", "to_ko": "ST 20/2 ROC 50",
     "why_ko": "최근 26주 주변 평균 1등 (-0.05R, 1,234건)"},
    {"coin": "BTCUSD", "L": 20, "from_ko": "ST 10/6 ROC 9", "to_ko": "ST 8/3 ROC 37", "why_ko": "26주 수익 + 낙폭 최소"}]}
PASS = {"account": "fx-fr-S2-15m", "name": "S2 친구 값 · 15분", "L": 20,
        "checks": [{"name_ko": "실시간 거래 100건 이상", "ok": True, "value_ko": "134건"},
                   {"name_ko": "운 기준 넘음", "ok": True, "value_ko": "+0.08R"}]}
SAMPLES = {
    "start": {"phase": "live", "accounts": 48, "live_start_ms": T0},
    "tick": {"bar_ms": T0, "opens": [trade(0), trade(1, coin="ETHUSD", side=-1)], "closes": [trade(2, closed=True)]},
    "switch": SWITCH, "daily": DAILY, "warn": {"what": "data", "detail_ko": "15분봉 2개 빠짐 (BTC, ETH)"},
    "pass": PASS}
# the view log (CONTRACT.md 7.3)
ZONES = {"A": None, "B": [84750.0, 84840.0], "C": [85300.0, 85300.0]}
FOLLOW_CLOSED = {"status": "closed", "entry_ms": T0, "entry": 84750.0, "stop": 85600.0, "exit_ms": T0 + 3600_000,
                 "R": 1.2, "wallet20_pct": 4.8, "legs_ko": "1R 절반 · 본전 청산"}
FOLLOW_MISSED = {"status": "missed", "entry_ms": None, "entry": None, "stop": None, "exit_ms": None, "R": None,
                 "wallet20_pct": None, "legs_ko": ""}
VIEWS = {
    "view_ack": {"id": 12, "coin": "BTCUSD", "side": -1, "t_ms": T0 + 5 * 3600_000 + 180_000, "zones": ZONES,
                 "stop": 85600.0, "targets": [], "memo": "4시간 저항", "notes_ko": ["시각 없음: 받은 시각 10/10 14:03 사용"]},
    "view_err": {"text_ko": "코인을 모르겠습니다: ADA\n예: 관점 BTC 숏 B 84750-84840"},
    "view_cancel": {"id": 12, "ok": True},
    "view_list": {"views": [{"id": 13, "t_ms": T0, "coin": "ETHUSD", "side": 1, "status": "watching", "dir24": None,
                             "touch_R": None},
                            {"id": 12, "t_ms": T0 - 86_400_000, "coin": "BTCUSD", "side": -1, "status": "done",
                             "dir24": -0.83, "touch_R": 1.2}]},
    "view_help": {},
    "view_done": {"id": 12, "coin": "BTCUSD", "side": -1, "dir": {"4h": 0.41, "24h": -0.83, "48h": 1.25},
                  "reached": True, "touch": FOLLOW_CLOSED, "confirm": FOLLOW_MISSED,
                  "summary_ko": "끝난 관점 5개 · 표본 부족 (5/30)"}}
SAMPLES.update(VIEWS)
# round 3 (CONTRACT.md 8.1, 8.8, 8.9, 8.10)
WINDOW = {"n": 23, "mean_R": 0.12, "pnl": 123.4, "pnl_pct": 12.34, "max_dd": 0.183}
CONFIRMED = {"account": "fx-fr-S2-15m", "name": "S2 친구 값 · 15분", "L": 20, "result": "confirmed", "start_ms": T0,
             "decided_ms": T0 + 28 * 86_400_000, "window": WINDOW, "why_ko": ""}
FAILED = dict(CONFIRMED, result="failed", why_ko="평균 R이 0 이하 (-0.05R)",
              window=dict(WINDOW, mean_R=-0.05, pnl=-40.0, pnl_pct=-4.0))
DAILY3 = dict(DAILY, passed=1, confirming=1, candidates=0, costs={"median_entry_bps": 3.14, "assumed_bps": 2.0},
              regime=[{"coin": "BTCUSD", "trend": "up", "vol": "normal"}, {"coin": "ETHUSD", "trend": "range",
                                                                            "vol": "high"},
                      {"coin": "SOLUSD", "trend": None, "vol": None}])
WEEK = {"week_ko": "10/12~10/18", "start_ms": T0, "end_ms": T0 + 7 * 86_400_000, "final": True,
        "summary_ko": ["이번 주 거래 312건, 오른 계좌 20개 · 내린 계좌 28개.", "가장 좋은 줄: S2 친구 값 · 15분 50배 +12.3%.",
                       "고정 계좌 평균 +1.2%, 자동 계좌 평균 -0.8%."],
        "decide_ko": ["S2 친구 값 · 15분 20배가 확인 기간을 통과: 실전 후보로 둘지 정하기"],
        "judge": {"passed": 1, "confirming": 2, "candidates": 1, "closer": [], "further": []},
        "stops": {"saved": [], "cost": [], "net_pct": 1.25},
        "costs": {"median_entry_bps": 2.6, "assumed_bps": 2.0, "eaten": []},
        "regime": [{"coin": "BTCUSD", "trend": "up", "vol": "normal", "share": {"up": 0.5, "down": 0.2, "range": 0.3}}],
        "views": {"n": 7, "done": 5, "dir24_rate": 0.6}}
SAMPLES.update({"confirm_done": CONFIRMED, "warn_clear": {"what": "dead", "detail_ko": "마지막 계산 10/10 09:00 (3분 전)"},
                "weekly": {"week": WEEK}})


def emoji_ok(text: str) -> bool:
    """At most one emoji, and only at the very start of the message."""
    return not any(unicodedata.category(c) == "So" or ord(c) >= 0x1F000 for c in text[3:])


# ---------------------------------------------------------------- render
def test_every_kind_is_korean_short_and_has_one_emoji_at_most_at_the_start():
    for kind, payload in SAMPLES.items():
        text = N.render(kind, payload, now_ms=T0)
        assert text and len(text) < 4096, kind
        assert re.search(r"[가-힣]", text.split("\n")[0]), kind          # the first line says what happened, in Korean
        assert emoji_ok(text), (kind, text)
        assert "USD" not in text and TOKEN not in text, kind


def test_tick_bundles_entries_and_exits_one_line_each():
    text = N.render("tick", SAMPLES["tick"])
    lines = text.split("\n")
    assert lines[0] == "🧪 데모 랩 모의 거래 · 진입 2 · 청산 1"
    assert lines[1] == "10/10 09:00 봉"                                   # KST
    opens = [ln for ln in lines if ln.startswith("- ") and "→" not in ln]
    closes = [ln for ln in lines if ln.startswith("- ") and "→" in ln]
    assert len(opens) == 2 and len(closes) == 1
    assert "BTC 롱 62,345.1" in opens[0] and "ETH 숏" in opens[1] and "ST 14/2 ROC 50" in opens[0]
    assert "사다리(규칙봇 방식)" in opens[0]
    c = closes[0]
    assert c.startswith("- S2 친구 값 · 15분: DOGE 숏 0.21345 → 0.20871 잠금 익절 +1.50R")
    assert "20배 +$12.30 · 30배 +$18.45 · 40배 +$24.60 · 50배 -$30.75" in c
    assert "ST 8/3 ROC 37" in c and "익절 1.5R · 손절 2ATR" in c


@pytest.mark.parametrize("reason,ko", [("stop", "손절"), ("lock", "잠금 익절"), ("liq", "강제청산"), ("tp", "익절"),
                                       ("time", "시간 청산")])
def test_exit_reasons_in_korean(reason, ko):
    t = dict(trade(closed=True), reason=reason)
    assert f" {ko} " in N.render("tick", {"bar_ms": T0, "opens": [], "closes": [t]})


def test_tick_with_200_trades_is_cut_below_the_limit_and_says_how_many_are_left():
    text = N.render("tick", {"bar_ms": T0, "opens": [trade(i) for i in range(100)],
                             "closes": [trade(i, closed=True) for i in range(100)]})
    assert len(text) < 4096
    assert text.split("\n")[0].endswith("진입 100 · 청산 100")
    shown = sum(1 for ln in text.split("\n") if ln.startswith("- "))
    m = re.search(r"외 (\d+)건은 대시보드에서$", text)
    assert m and shown + int(m[1]) == 200 and shown >= 10
    assert "\n진입 100\n" in text and "\n청산 100\n" in text           # both sections get room


def test_tick_without_trades_is_empty_and_one_huge_line_is_clipped():
    assert N.render("tick", {"bar_ms": T0, "opens": [], "closes": []}) == ""
    t = dict(trade(), setting_ko="x" * 10_000)
    assert len(N.render("tick", {"bar_ms": T0, "opens": [t] * 20, "closes": []})) < 4096


def test_start_switch_warn_pass():
    warm = N.render("start", {"phase": "warm", "accounts": 48, "live_start_ms": 0})
    assert warm.startswith("▶️ 데모 랩 시작 · 준비 중") and "주문 없음" in warm
    live = N.render("start", SAMPLES["start"], now_ms=T0 + 86_400_000)
    assert live.startswith("▶️ 데모 랩 시작 · 계좌 48개") and "이어서 돌림 · 실시간 시작 10/10 09:00" in live
    sw = N.render("switch", SWITCH, now_ms=T0)
    assert sw.startswith("🔁 설정 바꿈 · S2 친구 규칙 · 15분")
    assert "- 전체 코인: ST 10/6 ROC 9 → ST 20/2 ROC 50 · 최근 26주" in sw and "- BTC 20배: " in sw
    for what, ko in N.WARN_KO.items():
        w = N.render("warn", {"what": what, "detail_ko": "자세히"}, now_ms=T0)
        assert w.startswith(f"⚠ 데모 랩 경고 · {ko}") and "자세히" in w and w.endswith("10/10 09:00")
    p = N.render("pass", PASS, now_ms=T0)
    assert p.startswith("🏁 우리 기준 통과 · S2 친구 값 · 15분 20배")
    assert "- 실시간 거래 100건 이상: 134건 (충족)" in p and "실제 돈을 쓸지는 두 분이 정합니다" in p


def test_daily_summary():
    d = N.render("daily", DAILY)
    lines = d.split("\n")
    assert lines[0] == "📋 데모 랩 하루 요약 · 10/10" and lines[1] == "실시간 3.2일째 · 지난 24시간 거래 57건"
    assert "- S2 친구 값 · 15분 50배 +12.3% (+$123.40)" in d and "- 동전 던지기 · 15분 50배 -45.6%" in d
    assert "- 고정 20배 +1.2% · 30배 +1.8% · 40배 +2.3% · 50배 -2.9%" in d and "- 동전 던지기 20배 -1.0%" in d
    assert ("- S2 15분 (26주): ST 20/2 ROC 50 · 사다리(규칙봇 방식) · +0.05R · 승률 41% · 312건 · "
            "운 기준 +0.03R → 운보다 나음") in d
    assert "N04 30분 (4주): ST 8/3 KVOx1 sig 13 · 익절 1.5R · 손절 2ATR" in d and "운과 구별 안 됨" in d
    assert lines[-2:] == ["우리 기준 통과 0개", "통과 전에는 실제 돈 금지"]
    d2 = N.render("daily", dict(DAILY, passed=2))
    assert "우리 기준 통과 2개 (실제 돈은 두 분이 정합니다)" in d2 and d2.endswith("통과 전에는 실제 돈 금지")


@pytest.mark.parametrize("kind", list(SAMPLES) + ["other"])
@pytest.mark.parametrize("payload", [None, {}, {"opens": "x", "closes": [None, 3], "items": [1], "best": [None],
                                                 "checks": "?", "L": "abc", "bar_ms": "?", "live_days": float("nan")},
                                     {"confirm_end_ms": "?", "result": None, "window": "x", "start_ms": None,
                                      "decided_ms": float("nan"), "why_ko": None, "confirming": "x", "candidates": None,
                                      "costs": [], "regime": [None, 1, {"coin": None}], "week": "x", "what": None},
                                     {"week": {"summary_ko": "x", "decide_ko": [None, 3], "judge": [], "stops": "?",
                                               "costs": None, "views": {"n": None, "dir24_rate": "?"}}}])
def test_render_never_raises(kind, payload):
    out = N.render(kind, payload)
    assert isinstance(out, str) and len(out) < 4096


# ---------------------------------------------------------------- round 3 kinds (CONTRACT.md 8.1, 8.8, 8.9, 8.10)
def test_pass_says_the_confirmation_period_started_and_its_earliest_end_in_kst():
    p = N.render("pass", dict(PASS, confirm_end_ms=T0 + 28 * 86_400_000), now_ms=T0).split("\n")
    assert p[0] == "🏁 우리 기준 통과 · S2 친구 값 · 15분 20배"
    assert p[1] == "4주 확인 기간 시작 · 빨라도 11/07(토)에 끝남 (한국 시간)"
    text = "\n".join(p)
    assert "지금부터 새로 들어간 거래만 다시 셉니다" in text and "최대 8주" in text and "'실전 후보'" in text
    assert "실제 돈을 쓸지는 두 분이 정합니다" in text and p[-1] == "10/10 09:00"
    late = N.render("pass", dict(PASS, confirm_end_ms=1_791_644_400_000))        # 10/10 15:00 UTC = 10/11 00:00 KST
    assert "빨라도 10/11(일)에 끝남" in late
    for missing in ({}, {"confirm_end_ms": None}, {"confirm_end_ms": 0}, {"confirm_end_ms": "x"}):
        old = N.render("pass", dict(PASS, **missing), now_ms=T0)
        assert "확인 기간" not in old and "- 실시간 거래 100건 이상: 134건 (충족)" in old


def test_confirm_done_confirmed_is_a_candidate_and_still_the_owners_decision():
    c = N.render("confirm_done", CONFIRMED).split("\n")
    assert c[0] == "✅ 확인 기간 통과 · S2 친구 값 · 15분 20배" and c[1] == "이제 '실전 후보'입니다"
    assert "확인 기간 10/10 ~ 11/07" in c
    assert "거래 23건 · 평균 +0.12R · 수익 +$123.40 (+12.3%) · 최대 낙폭 18.3%" in c
    assert c[-1] == "실제 돈을 쓸지는 두 분이 정합니다 (정하기 전에는 실제 돈 금지)"
    assert "이유" not in "\n".join(c)


def test_confirm_done_failed_gives_why():
    f = N.render("confirm_done", FAILED).split("\n")
    assert f[0] == "❌ 확인 기간 실패 · S2 친구 값 · 15분 20배" and f[1] == "이유: 평균 R이 0 이하 (-0.05R)"
    assert "거래 23건 · 평균 -0.05R · 수익 -$40.00 (-4.0%) · 최대 낙폭 18.3%" in f
    assert "확인 기간이 새로 시작됩니다" in f[-2] and f[-1] == "실제 돈 금지 그대로"
    assert "이유: 기록 없음" in N.render("confirm_done", dict(FAILED, why_ko=None))


def test_confirm_done_with_missing_fields():
    bare = N.render("confirm_done", {"result": "confirmed"}).split("\n")
    assert bare[0] == "✅ 확인 기간 통과 · ?" and "확인 기간" in bare and not any("거래" in x for x in bare)
    odd = N.render("confirm_done", {"name": "X", "L": None, "result": "maybe", "start_ms": T0, "window": {}})
    assert odd.startswith("🏁 확인 기간 끝 · X\n결과를 알 수 없음") and "확인 기간 10/10부터" in odd
    part = N.render("confirm_done", dict(CONFIRMED, window={"n": 3, "mean_R": None, "pnl": None, "max_dd": None}))
    assert "거래 3건 · 평균 - · 수익 - · 최대 낙폭 -" in part


def test_warn_knows_the_watch_kinds_and_warn_clear_says_it_recovered():
    for what, ko in (("dead", "엔진이 멈춤"), ("rank", "순위표가 안 만들어짐"), ("backup", "밤 백업이 안 됨")):
        assert N.WARN_KO[what].startswith(ko)
        w = N.render("warn", {"what": what, "detail_ko": "자세히"}, now_ms=T0)
        assert w.startswith(f"⚠ 데모 랩 경고 · {ko}") and "자세히" in w
    c = N.render("warn_clear", SAMPLES["warn_clear"], now_ms=T0).split("\n")
    assert c == ["✅ 데모 랩 회복 · 엔진이 다시 돎", "마지막 계산 10/10 09:00 (3분 전)", "10/10 09:00"]
    assert N.render("warn_clear", {"what": "rank"}) == "✅ 데모 랩 회복 · 순위표가 다시 만들어짐"
    assert N.render("warn_clear", {"what": "backup"}) == "✅ 데모 랩 회복 · 밤 백업이 다시 됨"
    assert set(N.CLEAR_KO) >= set(N.WARN_KO)
    assert N.render("warn_clear", {"what": "zzz", "detail_ko": None}) == "✅ 데모 랩 회복 · 'zzz' 경고 풀림"
    assert N.render("warn_clear", None) == "✅ 데모 랩 회복 · 경고 풀림"


def test_daily_round3_additions():
    d = N.render("daily", DAILY3)
    lines = d.split("\n")
    i = lines.index("시장 국면 (4시간 추세 · 15분 변동)")
    assert lines[i + 1:i + 4] == ["- BTC 상승 추세 · 변동 보통", "- ETH 횡보 · 변동 큼", "- SOL 아직 모름"]
    assert lines[-4:] == ["우리 기준 통과 1개 (실제 돈은 두 분이 정합니다)", "확인 기간 중 1줄 · 실전 후보 0줄",
                          "실제 진입 비용 (호가창, 중앙값) 3.1bp · 가정 2bp보다 1.1bp 큼 (1bp = 0.01%)",
                          "통과 전에는 실제 돈 금지"]
    d2 = N.render("daily", dict(DAILY3, candidates=2, costs={"median_entry_bps": 1.2, "assumed_bps": 2.0}))
    assert "실전 후보 2줄 (실제 돈은 두 분이 정합니다)" in d2 and "가정 2bp보다 0.8bp 작음" in d2
    assert "가정과 같음" in N.render("daily", dict(DAILY3, costs={"median_entry_bps": 2.0, "assumed_bps": 2.0}))
    none = N.render("daily", dict(DAILY3, costs={"median_entry_bps": None}, confirming=None, candidates=None,
                                  regime=None))
    assert "실제 진입 비용: 아직 잰 거래 없음 (가정 2bp, 1bp = 0.01%)" in none
    assert "확인 기간 중" not in none and "시장 국면" not in none
    assert "실제 진입 비용: 아직 잰 거래 없음" in N.render("daily", dict(DAILY, costs=None))
    old = N.render("daily", DAILY)                                       # an older engine: nothing new shown
    assert "확인 기간" not in old and "진입 비용" not in old and "시장 국면" not in old


def test_weekly_review_is_short():
    w = N.render("weekly", {"week": WEEK}).split("\n")
    assert w[0] == "📅 데모 랩 주간 회의록 · 10/12~10/18" and w[1:4] == WEEK["summary_ko"]
    i = w.index("두 분이 정할 것")
    assert w[i + 1] == "- S2 친구 값 · 15분 20배가 확인 기간을 통과: 실전 후보로 둘지 정하기"
    text = "\n".join(w)
    assert "판정: 우리 기준 통과 1줄 · 확인 기간 중 2줄 · 실전 후보 1줄" in w
    assert "정지 규칙: 썼다면 줄마다 평균 +1.2%p (+면 정지 규칙을 쓴 쪽이 나음)" in w
    neg = N.render("weekly", {"week": dict(WEEK, stops={"net_pct": -3.0})})
    assert "정지 규칙: 썼다면 줄마다 평균 -3.0%p" in neg
    assert "실제 진입 비용 (호가창, 중앙값) 2.6bp · 가정 2bp보다 0.6bp 큼 (1bp = 0.01%)" in w
    assert "관점: 7개 · 끝남 5개 · 24시간 방향 적중 60%" in w
    assert "실제 돈을 쓸지는 두 분이 정합니다" in text and len(w) <= 20
    many = N.render("weekly", {"week": dict(WEEK, summary_ko=[f"문장 {i}." for i in range(10)])})
    assert "문장 5." in many and "문장 6." not in many                             # at most 6 sentences
    nothing = N.render("weekly", {"week": dict(WEEK, decide_ko=[])})
    assert "두 분이 정할 것: 없음" in nothing.split("\n") and "\n- " not in nothing


@pytest.mark.parametrize("payload", [None, {}, {"week": None}, {"week": {}}, {"week": "x"},
                                     {"week": {"week_ko": None, "summary_ko": None, "decide_ko": None, "judge": None,
                                               "stops": None, "costs": None, "views": None}}])
def test_weekly_with_empty_or_missing_fields(payload):
    w = N.render("weekly", payload).split("\n")
    assert w[0] == "📅 데모 랩 주간 회의록" and w[1] == "이번 주 요약 없음"
    assert "두 분이 정할 것: 없음" in w and "판정: 기록 없음" in w and "정지 규칙: 기록 없음" in w
    assert "실제 진입 비용: 아직 잰 거래 없음 (가정 2bp, 1bp = 0.01%)" in w and "관점: 기록 없음" in w


def test_weekly_partial_fields():
    w = N.render("weekly", {"week": {"week_ko": "10/12~10/18", "summary_ko": ["", "  ", "한 문장."],
                                     "judge": {"passed": 0}, "stops": {"net_pct": None},
                                     "views": {"n": 0, "done": 0, "dir24_rate": None}}})
    lines = w.split("\n")
    assert lines[1] == "한 문장." and "판정: 우리 기준 통과 0줄 · 확인 기간 중 -줄 · 실전 후보 -줄" in lines
    assert "정지 규칙: 기록 없음" in lines and "관점: 0개 · 끝남 0개 · 24시간 방향 적중 -" in lines
    long = N.render("weekly", {"week": dict(WEEK, decide_ko=["x" * 900] * 40)})
    assert len(long) < 4096 and "외 " in long


def test_view_ack_shows_the_zones_stop_targets_and_the_parser_notes():
    a = N.render("view_ack", VIEWS["view_ack"]).split("\n")
    assert a[0] == "📝 관점 #12 기록 · BTC 숏" and a[1] == "10/10 14:03 기준 (한국 시간)"
    assert "구간 B 84,750~84,840 · C 85,300" in a and "손절 85,600" in a
    assert "목표 없음: 1R에 절반 · 본전 · 나머지 2R" in a and "메모 4시간 저항" in a
    assert "- 시각 없음: 받은 시각 10/10 14:03 사용" in a and a[-1].endswith("취소: 취소 12")
    b = N.render("view_ack", dict(VIEWS["view_ack"], side=1, coin="ETHUSD", zones={"A": [3050, 3060]}, stop=None,
                                  targets=[3120, 3180.5], memo="", notes_ko=[]))
    assert "ETH 롱" in b and "구간 A 3,050~3,060" in b and "목표 3,120, 3,180.5" in b and "손절 없음" in b
    assert N.zones_text({"C": 85300, "A": [2.5, 2.4]}) == "A 2.4~2.5 · C 85,300" and N.zones_text(None) == "-"


def test_view_err_cancel_list_help():
    e = N.render("view_err", VIEWS["view_err"])
    assert e.startswith("❓ 관점을 기록하지 못했습니다\n코인을 모르겠습니다: ADA") and "관점도움" in e
    assert N.VIEW_EXAMPLES[0] in N.render("view_err", {})                     # no reason given: usage + example
    assert N.render("view_cancel", {"id": 12, "ok": True}).startswith("🗑 관점 #12 취소했습니다")
    assert N.render("view_cancel", {"id": 99, "ok": False}).startswith("❓ 관점 #99 취소 안 됨")
    li = N.render("view_list", VIEWS["view_list"])
    assert li.startswith("📒 관점 목록 · 최근 2개")
    assert "- #13 10/10 09:00 ETH 롱 · 지켜보는 중" in li
    assert "- #12 10/09 09:00 BTC 숏 · 끝남 · 24시간 -0.83% · 구간 진입 +1.20R" in li
    assert "아직 기록한 관점이 없습니다" in N.render("view_list", {"views": []})
    h = N.render("view_help", {})
    assert h.startswith("📖 관점 기록장 쓰는 법") and N.VIEW_USAGE in h
    assert all(x in h for x in N.VIEW_EXAMPLES) and len(N.VIEW_EXAMPLES) == 2
    assert "취소 12" in h and "관점목록" in h and "관점도움" in h and "GitHub" in h
    for ex in N.VIEW_EXAMPLES:                                                 # the examples follow 7.3's format
        assert re.fullmatch(r"관점( \d\d/\d\d \d\d:\d\d)? (BTC|ETH|SOL|DOGE|LTC|BCH|XRP) (롱|숏)( [ABC] [\d,]+([-~][\d,]+)?)+"
                            r"( 손절 [\d,]+)?( 목표 [\d,]+(,[\d,]+)?)?( 메모 .+)?", ex), ex


def test_view_done_shows_direction_reach_and_both_follow_modes():
    d = N.render("view_done", VIEWS["view_done"]).split("\n")
    assert d[0] == "📊 관점 #12 결과 · BTC 숏"
    assert d[1] == "말한 방향으로 4시간 +0.41% · 24시간 -0.83% · 48시간 +1.25%"
    assert d[2] == "구간 도달 예"
    assert d[3] == "- 구간 바로 진입: 청산 · 진입 84,750 · +1.20R · 20배 잔고 +4.8% · 1R 절반 · 본전 청산"
    assert d[4] == "- 15분 종가 확인 진입: 진입 못 함 (48시간 안에)"
    assert d[5] == "끝난 관점 5개 · 표본 부족 (5/30)"
    o = N.render("view_done", dict(VIEWS["view_done"], reached=False, dir={"4h": None},
                                   confirm={"status": "open", "entry": 84700.0, "R": -0.3}))
    assert "구간 도달 아니오" in o and "48시간 -" in o and "- 15분 종가 확인 진입: 보유 중 · 진입 84,700 · -0.30R (진행 중)" in o


def test_helpers():
    assert N.coin("BTCUSD") == "BTC" and N.coin("DOGEUSDT") == "DOGE" and N.coin("ALL") == "전체 코인"
    assert N.px(62345.12) == "62,345.1" and N.px(0.21345) == "0.21345" and N.px(None) == "-"
    assert N.usd(-5.1) == "-$5.10" and N.usd(1234.5) == "+$1,234.50"
    assert N.exit_label("tp1.5R_sl2atr") == "익절 1.5R · 손절 2ATR" and N.exit_label(0) == "사다리(규칙봇 방식)"
    assert N.rate(0.415) == "42%" and N.rate(41.5) == "42%"
    assert N.day_ko(T0) == "10/10(토)" and N.share(0.183) == "18.3%" and N.share(None) == "-"


# ---------------------------------------------------------------- outbox
class Clock:
    def __init__(self, t_ms=T0):
        self.t = t_ms / 1000

    def time(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def advance(self, s):
        self.t += s

    slept: list


def box(conn=None, clock=None):
    clock = clock or Clock()
    clock.slept = []
    conn = conn or sqlite3.connect(":memory:")
    return N.Outbox(conn, clock=clock.time, sleep=clock.sleep, monotonic=clock.time), conn, clock


class Sender:
    def __init__(self, fail=None):
        self.sent, self.fail, self.calls = [], fail, 0

    def __call__(self, token, chat, text):
        self.calls += 1
        if self.fail:
            f = self.fail(self.calls) if callable(self.fail) else self.fail
            if f is not None:
                raise f
        self.sent.append((token, chat, text))


def rows(conn):
    return conn.execute("SELECT id, kind, sent_ms, tries, error FROM outbox ORDER BY id").fetchall()


def test_queue_stores_the_rendered_text_and_flush_sends_in_order_paced():
    ob, conn, clk = box()
    for i in range(3):
        ob.queue("warn", {"what": f"w{i}", "detail_ko": f"#{i}"})
    ob.queue("tick", {"bar_ms": T0, "opens": [], "closes": []})          # nothing happened: not stored
    stored = conn.execute("SELECT text, payload FROM outbox ORDER BY id").fetchall()
    assert len(stored) == 3 and stored[0][0] == N.render("warn", {"what": "w0", "detail_ko": "#0"}, now_ms=T0)
    assert json.loads(stored[0][1])["what"] == "w0"
    s = Sender()
    assert ob.flush(TOKEN, "-100123", send=s) == 3
    assert [t.split("\n")[1] for _, _, t in s.sent] == ["#0", "#1", "#2"]
    assert all(r[2] is not None for r in rows(conn))
    assert clk.slept and all(x <= 1.0 for x in clk.slept) and sum(clk.slept) >= 2.0     # 1 a second
    st = ob.state()
    assert st == {"configured": True, "queued": 0, "last_ok_ms": st["last_ok_ms"], "last_error": None}
    assert st["last_ok_ms"] >= T0


def test_flush_respects_the_limit_and_the_minute_budget():
    ob, conn, clk = box()
    for i in range(30):
        ob.queue("warn", {"what": f"w{i}"})
    s = Sender()
    assert ob.flush(TOKEN, "c", limit=2, send=s) == 2
    assert ob.flush(TOKEN, "c", limit=30, send=s) == N.PER_MINUTE - 2      # about 20 a minute per group
    clk.advance(61)
    assert ob.flush(TOKEN, "c", limit=30, send=s) == 30 - N.PER_MINUTE
    assert len(s.sent) == 30 and ob.state()["queued"] == 0


def test_not_configured_sends_nothing_and_keeps_the_queue(monkeypatch):
    monkeypatch.delenv("DEMOBOT_TG_TOKEN", raising=False)
    monkeypatch.delenv("DEMOBOT_TG_CHAT", raising=False)
    ob, conn, _ = box()
    assert ob.state()["configured"] is False
    ob.queue("start", SAMPLES["start"])
    s = Sender()
    assert ob.flush("", "", send=s) == 0 and ob.flush(TOKEN, " ", send=s) == 0 and s.calls == 0
    assert ob.state()["queued"] == 1 and ob.state()["configured"] is False


def test_error_is_kept_and_retried_after_a_pause():
    ob, conn, clk = box()
    ob.queue("start", SAMPLES["start"])
    ob.queue("warn", {"what": "data"})
    s = Sender(fail=lambda n: RuntimeError("boom") if n == 1 else None)
    assert ob.flush(TOKEN, "c", send=s) == 0                          # first try failed: stops, never raises
    r = rows(conn)[0]
    assert r[2] is None and r[3] == 1 and r[4] == "RuntimeError: boom"
    assert ob.state()["last_error"] == "RuntimeError: boom" and ob.state()["queued"] == 2
    assert ob.flush(TOKEN, "c", send=s) == 0 and s.calls == 1          # paused (30 s)
    clk.advance(N.BACKOFF_S + 1)
    assert ob.flush(TOKEN, "c", send=s) == 2                          # same order: the failed one first
    assert "▶️" in s.sent[0][2] and rows(conn)[0][4] == "RuntimeError: boom"     # the error stays on the row
    assert ob.state()["last_error"] is None


def test_gives_up_a_row_after_5_refusals_and_moves_on():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    ob.queue("warn", {"what": "disk"})
    s = Sender(fail=lambda n: N.TelegramError("HTTP 400: Bad Request: message is too long") if n <= 5 else None)
    for _ in range(5):
        assert ob.flush(TOKEN, "c", send=s) == 0
        clk.advance(N.BACKOFF_MAX_S + 1)
    assert rows(conn)[0][3] == 5 and rows(conn)[1][3] == 0 and s.calls == 5
    assert ob.state()["queued"] == 1
    assert ob.flush(TOKEN, "c", send=s) == 1 and s.calls == 6          # the first one is not tried again
    assert rows(conn)[0][2] is None and rows(conn)[1][2] is not None


def test_transient_errors_do_not_count_a_try_and_429_waits_as_asked():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    s = Sender(fail=N.TelegramError("HTTP 429: Too Many Requests", transient=True, retry_after=100))
    assert ob.flush(TOKEN, "c", send=s) == 0
    assert rows(conn)[0][3] == 0 and "429" in rows(conn)[0][4]
    clk.advance(60)
    assert ob.flush(TOKEN, "c", send=s) == 0 and s.calls == 1         # still inside retry_after
    clk.advance(41)
    s.fail = None
    assert ob.flush(TOKEN, "c", send=s) == 1


@pytest.mark.parametrize("exc", [OSError("network down"), ValueError("x"), urllib.error.URLError("dns"),
                                 TimeoutError(), Exception("anything")])
def test_flush_never_raises_when_send_throws(exc):
    ob, conn, _ = box()
    ob.queue("warn", {"what": "error"})
    assert ob.flush(TOKEN, "c", send=Sender(fail=exc)) == 0
    assert ob.flush(TOKEN, "c", send=lambda *a: False) == 0                # a sender saying False is a failure too


def test_flush_and_state_never_raise_on_a_broken_database():
    ob, conn, _ = box()
    ob.queue("warn", {"what": "error"})
    conn.close()
    assert ob.flush(TOKEN, "c", send=Sender()) == 0
    assert ob.state()["last_error"].startswith("db:")


def test_the_token_never_lands_in_the_table_or_the_state():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    ob.flush(TOKEN, "c", send=Sender(fail=RuntimeError(f"failed {url} and {TOKEN.replace(':', '%3A')}")))
    dump = "\n".join(str(x) for x in conn.execute("SELECT * FROM outbox").fetchall())
    assert TOKEN not in dump and TOKEN.split(":")[1] not in dump and "<token>" in dump
    assert TOKEN not in json.dumps(ob.state())
    other = "1234567:" + "abcdefghij" * 3                     # any token-shaped text, even an unknown one
    assert N.redact(f"x {other} y") == "x <token> y"


def test_api_errors_carry_no_token(monkeypatch):
    def http_error(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     io.BytesIO(b'{"ok":false,"description":"Bad Request: chat not found"}'))
    monkeypatch.setattr(N.urllib.request, "urlopen", http_error)
    with pytest.raises(N.TelegramError) as ei:
        N.send_message(TOKEN, "c", "hi")
    assert str(ei.value) == "HTTP 400: Bad Request: chat not found" and not ei.value.transient
    assert ei.value.__suppress_context__

    def busy(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {},
                                     io.BytesIO(b'{"ok":false,"description":"Too Many Requests",'
                                                b'"parameters":{"retry_after":7}}'))
    monkeypatch.setattr(N.urllib.request, "urlopen", busy)
    with pytest.raises(N.TelegramError) as ei:
        N.send_message(TOKEN, "c", "hi")
    assert ei.value.transient and ei.value.retry_after == 7.0

    def down(req, timeout=None):
        raise urllib.error.URLError(f"cannot reach {req.full_url}")
    monkeypatch.setattr(N.urllib.request, "urlopen", down)
    with pytest.raises(N.TelegramError) as ei:
        N.send_message(TOKEN, "c", "hi")
    assert ei.value.transient and TOKEN not in str(ei.value) and "<token>" in str(ei.value)


def test_send_message_is_plain_silent_and_without_preview(monkeypatch):
    seen = {}
    monkeypatch.setattr(N, "api", lambda token, method, params, timeout: seen.update(m=method, p=params, t=timeout))
    N.send_message(TOKEN, "-100", "안녕")
    assert seen["m"] == "sendMessage" and seen["t"] == N.TIMEOUT_S
    assert seen["p"] == {"chat_id": "-100", "text": "안녕", "disable_web_page_preview": "true",
                         "disable_notification": "true"}
    assert "parse_mode" not in seen["p"]


def test_warn_at_most_once_per_what_per_hour():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data", "detail_ko": "a"})
    ob.queue("warn", {"what": "data", "detail_ko": "b"})
    ob.queue("warn", {"what": "disk", "detail_ko": "c"})
    clk.advance(59 * 60)
    ob.queue("warn", {"what": "data", "detail_ko": "d"})
    assert [r[1] for r in rows(conn)] == ["warn", "warn"]
    clk.advance(2 * 60)
    ob.queue("warn", {"what": "data", "detail_ko": "e"})
    texts = [t for (t,) in conn.execute("SELECT text FROM outbox ORDER BY id")]
    assert len(texts) == 3 and "e" in texts[-1].split("\n")[1]
    ob.queue("start", SAMPLES["start"])
    ob.queue("start", SAMPLES["start"])                                     # only warn is limited
    assert len(rows(conn)) == 5


def test_queue_joins_the_callers_transaction_or_commits_itself(tmp_path):
    path = tmp_path / "demo.db"
    conn = sqlite3.connect(path, isolation_level=None)                     # as demobot/store.connect
    ob, _, _ = box(conn)
    conn.execute("BEGIN IMMEDIATE")
    ob.queue("start", SAMPLES["start"])
    conn.execute("ROLLBACK")
    assert rows(conn) == []
    ob.queue("start", SAMPLES["start"])
    other = sqlite3.connect(path)
    assert other.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
    conn2 = sqlite3.connect(tmp_path / "b.db")                               # default (implicit transactions)
    ob2, _, _ = box(conn2)
    ob2.queue("start", SAMPLES["start"])
    assert not conn2.in_transaction


def test_old_rows_are_pruned_and_stale_ones_given_up():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    ob.flush(TOKEN, "c", send=Sender())
    clk.advance(10)
    ob.queue("warn", {"what": "disk"})                                     # never sent (no chat yet)
    clk.advance(25 * 3600)
    ob.flush("", "", send=Sender())
    ob.queue("warn", {"what": "error"})
    s = Sender()
    assert ob.flush(TOKEN, "c", send=s) == 1 and "오류" in s.sent[0][2]   # the 25-hour-old one is not sent
    assert rows(conn)[1][3] == N.MAX_TRIES and "24시간" in rows(conn)[1][4]
    clk.advance(31 * 86400)
    ob.flush(TOKEN, "c", send=Sender())
    assert rows(conn) == []                                                # sent and given-up rows: 30 days


def test_state_reads_the_environment_before_any_flush(monkeypatch):
    monkeypatch.setenv("DEMOBOT_TG_TOKEN", TOKEN)
    monkeypatch.setenv("DEMOBOT_TG_CHAT", "-100")
    ob, _, _ = box()
    assert ob.state() == {"configured": True, "queued": 0, "last_ok_ms": None, "last_error": None}


OUTBOX_COLS = [("id", "INTEGER", None), ("ts_ms", "INTEGER", None), ("kind", "TEXT", None),
               ("payload", "TEXT", None), ("text", "TEXT", None), ("sent_ms", "INTEGER", None),
               ("tries", "INTEGER", "0"), ("error", "TEXT", None), ("sent_to", "TEXT", None)]


def test_outbox_table_shape():
    _, conn, _ = box()
    cols = [(r[1], r[2], r[4]) for r in conn.execute("PRAGMA table_info(outbox)")]
    assert cols == OUTBOX_COLS
    N.Outbox(conn)                                                         # twice: no error


def test_an_older_outbox_table_is_migrated_and_its_rows_still_go_out(tmp_path):
    path = tmp_path / "demo.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE outbox(id INTEGER PRIMARY KEY, ts_ms INTEGER, kind TEXT, payload TEXT, text TEXT, "
                "sent_ms INTEGER, tries INTEGER DEFAULT 0, error TEXT)")            # as round 2 made it
    old.execute("INSERT INTO outbox(ts_ms, kind, payload, text, sent_ms, tries) VALUES(?, 'warn', '{}', 'done', ?, 0)",
                (T0 - 1000, T0 - 500))
    old.execute("INSERT INTO outbox(ts_ms, kind, payload, text, tries) VALUES(?, 'warn', '{}', 'pending', 0)",
                (T0 - 1000,))
    old.commit()
    old.close()
    conn = sqlite3.connect(path, isolation_level=None)
    ob, _, _ = box(conn)
    assert [(r[1], r[2], r[4]) for r in conn.execute("PRAGMA table_info(outbox)")] == OUTBOX_COLS
    s = Sender()
    assert ob.flush(TOKEN, "111,222", send=s) == 1
    assert [(c, t) for _, c, t in s.sent] == [("111", "pending"), ("222", "pending")]   # the sent row is not resent
    assert json.loads(conn.execute("SELECT sent_to FROM outbox WHERE text='pending'").fetchone()[0]) == ["111", "222"]
    N.Outbox(conn)                                                         # again: no second ALTER
    other = sqlite3.connect(path)                                          # committed for other connections
    assert "sent_to" in [r[1] for r in other.execute("PRAGMA table_info(outbox)")]


def test_parse_chats():
    assert N.parse_chats("123456789,987654321") == ["123456789", "987654321"]
    assert N.parse_chats(" 111 , -100222,,111, ") == ["111", "-100222"]
    assert N.parse_chats(-100777) == ["-100777"] and N.parse_chats("") == [] and N.parse_chats(None) == []
    assert N.parse_chats("1,2,3,4,5,6") == ["1", "2", "3", "4"]                # at most 4


def test_every_message_goes_to_every_listed_chat_in_order():
    ob, conn, clk = box()
    for i in range(3):
        ob.queue("warn", {"what": f"w{i}", "detail_ko": f"#{i}"})
    s = Sender()
    assert ob.flush(TOKEN, "111, 222", send=s) == 3
    assert [(c, t.split("\n")[1]) for _, c, t in s.sent] == [("111", "#0"), ("222", "#0"), ("111", "#1"),
                                                             ("222", "#1"), ("111", "#2"), ("222", "#2")]
    assert all(x <= 1.0 for x in clk.slept) and sum(clk.slept) >= 5.0         # one a second over all chats
    assert ob.state() == {"configured": True, "queued": 0, "last_ok_ms": ob.state()["last_ok_ms"], "last_error": None}


def test_a_partial_failure_retries_only_the_failed_chat_and_never_double_sends():
    ob, conn, clk = box()
    ob.queue("start", SAMPLES["start"])
    ob.queue("warn", {"what": "data", "detail_ko": "x"})
    fail_222 = {"on": True}

    def send(token, chat, text):
        if chat == "222" and fail_222["on"]:
            raise N.TelegramError("HTTP 403: Forbidden: bot was blocked by the user")
        got.append((chat, text.split("\n")[0]))
    got = []
    assert ob.flush(TOKEN, "111,222", send=send) == 0                        # no row reached both chats
    assert got == [("111", "▶️ 데모 랩 시작 · 계좌 48개"), ("111", "⚠ 데모 랩 경고 · 시세 자료 빠짐")]  # 111 goes on
    r = conn.execute("SELECT sent_ms, tries, error, sent_to FROM outbox ORDER BY id").fetchall()
    assert r[0][0] is None and r[0][1] == 1 and r[0][2] == "222: HTTP 403: Forbidden: bot was blocked by the user"
    assert json.loads(r[0][3]) == ["111"] and json.loads(r[1][3]) == ["111"] and r[1][1] == 0   # 222 paused
    st = ob.state()
    assert st["queued"] == 2 and st["last_error"].startswith("222: HTTP 403")
    got.clear()
    assert ob.flush(TOKEN, "111,222", send=send) == 0 and got == []          # 222 still paused, 111 has all
    ob.queue("warn", {"what": "disk"})                                     # new rows still reach 111 at once
    assert ob.flush(TOKEN, "111,222", send=send) == 0 and got == [("111", "⚠ 데모 랩 경고 · 디스크 공간 부족")]
    got.clear()
    fail_222["on"] = False
    clk.advance(N.BACKOFF_S + 1)
    assert ob.flush(TOKEN, "111,222", send=send) == 3
    assert got == [("222", "▶️ 데모 랩 시작 · 계좌 48개"), ("222", "⚠ 데모 랩 경고 · 시세 자료 빠짐"),
                   ("222", "⚠ 데모 랩 경고 · 디스크 공간 부족")]                     # in order, 111 not again
    assert ob.state()["queued"] == 0 and ob.state()["last_error"] is None
    assert all(json.loads(x) == ["111", "222"] for (x,) in conn.execute("SELECT sent_to FROM outbox"))


def test_a_chat_that_keeps_failing_gives_the_row_up_but_the_other_chat_got_it():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    calls = []

    def send(token, chat, text):
        calls.append(chat)
        if chat == "999":
            raise N.TelegramError("HTTP 400: Bad Request: chat not found")
    for _ in range(N.MAX_TRIES):
        ob.flush(TOKEN, "111,999", send=send)
        clk.advance(N.BACKOFF_MAX_S + 1)
    assert calls == ["111"] + ["999"] * N.MAX_TRIES                         # 111 once, 999 five times
    row = conn.execute("SELECT sent_ms, tries, sent_to FROM outbox").fetchone()
    assert row[0] is None and row[1] == N.MAX_TRIES and json.loads(row[2]) == ["111"]
    assert ob.flush(TOKEN, "111,999", send=send) == 0 and len(calls) == 1 + N.MAX_TRIES    # given up


def test_the_minute_budget_is_per_chat():
    ob, conn, clk = box()
    for i in range(N.PER_MINUTE + 2):
        ob.queue("warn", {"what": f"w{i}"})
    s = Sender()
    assert ob.flush(TOKEN, "111,222", limit=100, send=s) == N.PER_MINUTE
    assert len(s.sent) == 2 * N.PER_MINUTE
    clk.advance(61)
    assert ob.flush(TOKEN, "111,222", limit=100, send=s) == 2 and len(s.sent) == 2 * N.PER_MINUTE + 4


# ---------------------------------------------------------------- commands from the group (poll_commands)
def upd(uid, chat=-100777, text="관점 BTC 숏 B 84750-84840", date=1_791_608_580, first="민수", kind="message"):
    m = {"message_id": uid, "date": date, "chat": {"id": chat, "type": "supergroup"}, "from": {"id": 5, "first_name": first}}
    if text is not None:
        m["text"] = text
    return {"update_id": uid, kind: m}


class Get:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def __call__(self, token, method, params, timeout):
        self.calls.append((method, params, timeout))
        if self.exc:
            raise self.exc
        return self.result


def test_poll_keeps_only_the_groups_text_messages_and_moves_past_everything_seen():
    g = Get([upd(500), upd(501, chat=-100999, text="관점 ETH 롱 A 1"), upd(502, text=None),
             upd(503, text="관점목록", first=None), {"update_id": 504, "my_chat_member": {"chat": {"id": -100777}}},
             upd(505, chat=42, text="취소 1"), "junk", {"update_id": "x"}])
    off, items = N.poll_commands(TOKEN, "-100777", 500, timeout=25, get=g)
    assert off == 506                                                     # other chats and non-messages too
    assert items == [{"update_id": 500, "text": "관점 BTC 숏 B 84750-84840", "date_ms": 1_791_608_580_000,
                      "from_name": "민수"},
                     {"update_id": 503, "text": "관점목록", "date_ms": 1_791_608_580_000, "from_name": ""}]
    method, params, timeout = g.calls[0]
    assert method == "getUpdates" and params["offset"] == "500" and params["timeout"] == "25"
    assert json.loads(params["allowed_updates"]) == ["message"] and timeout > 25        # HTTP waits past the poll
    assert N.poll_commands(TOKEN, -100777, 0, get=Get([upd(7)]))[1][0]["update_id"] == 7   # an int chat id works
    g0 = Get([])
    assert N.poll_commands(TOKEN, "-100777", 0, get=g0) == (0, []) and "offset" not in g0.calls[0][1]
    assert N.poll_commands(TOKEN, "-100777", 506, get=Get([])) == (506, [])


def test_poll_accepts_every_listed_chat_and_ignores_strangers():
    g = Get([upd(1, chat=111, text="관점 BTC 숏 B 84750-84840", first="민수"),
             upd(2, chat=222, text="관점목록", first="지훈"),
             upd(3, chat=333, text="관점 ETH 롱 A 1", first="낯선 사람"),             # someone who found the bot
             upd(4, chat=-100777, text="취소 1"),                                    # a group not listed
             upd(5, chat=222, text="/start", first="지훈")])
    off, items = N.poll_commands(TOKEN, "111, 222", 0, get=g)
    assert off == 6
    assert [(i["update_id"], i["from_name"]) for i in items] == [(1, "민수"), (2, "지훈"), (5, "지훈")]
    off, items = N.poll_commands(TOKEN, "111,-100777", 0, get=Get([upd(4, chat=-100777, text="취소 1"),
                                                                  upd(6, chat=333, text="관점목록")]))
    assert [i["update_id"] for i in items] == [4] and off == 7
    assert N.poll_commands(TOKEN, " , ", 0, get=g) == (0, [])                # no chat listed: nothing read


@pytest.mark.parametrize("exc", [N.TelegramError("HTTP 409: Conflict"), urllib.error.URLError("dns"), OSError("x"),
                                 ValueError("bad json"), Exception("anything")])
def test_poll_never_raises_and_keeps_the_offset(exc):
    assert N.poll_commands(TOKEN, "-100777", 321, get=Get(exc=exc)) == (321, [])


def test_poll_bad_answers_and_missing_settings_keep_the_offset():
    assert N.poll_commands(TOKEN, "-100777", 9, get=Get({"ok": True})) == (9, [])
    assert N.poll_commands(TOKEN, "-100777", 9, get=Get(None)) == (9, [])
    g = Get([upd(1)])
    assert N.poll_commands("", "-100777", 9, get=g) == (9, []) and N.poll_commands(TOKEN, " ", 9, get=g) == (9, [])
    assert g.calls == [] and N.poll_commands(TOKEN, "-1", "bad", get=Get([])) == (0, [])


def test_poll_errors_are_logged_without_the_token(capsys, monkeypatch):
    monkeypatch.setattr(N, "_poll_err", {"text": None, "t": 0.0})
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    assert N.poll_commands(TOKEN, "-100777", 3, get=Get(exc=RuntimeError(f"reset by peer at {url}"))) == (3, [])
    err = capsys.readouterr().err
    assert "reset by peer" in err and "<token>" in err and TOKEN not in err and TOKEN.split(":")[1] not in err
    N.poll_commands(TOKEN, "-100777", 3, get=Get(exc=RuntimeError(f"reset by peer at {url}")))
    assert capsys.readouterr().err == ""                                   # the same error again: not repeated

    def down(req, timeout=None):                                          # the real api(): HTTP error, token in URL
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"ok":false}'))
    monkeypatch.setattr(N.urllib.request, "urlopen", down)
    assert N.poll_commands(TOKEN, "-100777", 4) == (4, [])
    assert TOKEN not in capsys.readouterr().err


# ---------------------------------------------------------------- CLI
def test_cli_test_message(capsys):
    out = []
    assert N.cmd_test(TOKEN, "-100", send=lambda t, c, x: out.append(x), out=print) == 0
    assert out[0].startswith("🧪 데모 랩 테스트 메시지\n")
    assert "보냈습니다" in capsys.readouterr().out
    fail = N.TelegramError("HTTP 401: Unauthorized")

    def bad(t, c, x):
        raise RuntimeError(f"{fail} {TOKEN}")
    assert N.cmd_test(TOKEN, "-100", send=bad) == 1
    o = capsys.readouterr().out
    assert TOKEN not in o and "토큰이 틀렸습니다" in o
    assert N.cmd_test("", "-100") == 2 and N.cmd_test(TOKEN, "") == 2
    assert "sudoedit" in capsys.readouterr().out


def test_cli_test_sends_to_every_chat_and_reports_each(capsys):
    got = []

    def send(t, c, x):
        if c == "222":
            raise N.TelegramError(f"HTTP 403: Forbidden: bot can't initiate conversation with a user {TOKEN}")
        got.append(c)
    assert N.cmd_test(TOKEN, "111,222,-100333", send=send) == 1
    o = capsys.readouterr().out
    assert got == ["111", "-100333"] and "보냄: 111" in o and "보냄: -100333" in o
    assert "보내지 못했습니다: 222 · HTTP 403" in o and "시작(Start)" in o and "3곳 중 1곳" in o and TOKEN not in o
    assert N.cmd_test(TOKEN, "111,222", send=lambda t, c, x: got.append(c)) == 0
    assert "보냈습니다 (2곳)" in capsys.readouterr().out


def test_cli_chatid_lists_groups_and_never_the_token(capsys):
    updates = [{"update_id": 1, "my_chat_member": {"chat": {"id": -555, "title": "데모 랩", "type": "group"}}},
               {"update_id": 2, "message": {"chat": {"id": -555, "title": "데모 랩", "type": "group"},
                                            "migrate_to_chat_id": -1001234567890}},
               {"update_id": 3, "message": {"chat": {"id": -1001234567890, "title": "데모 랩", "type": "supergroup"}}},
               {"update_id": 4, "message": {"chat": {"id": 42, "first_name": "Kim", "type": "private"}}},
               {"update_id": 5, "message": {"chat": {"id": 7001, "first_name": "민수", "last_name": "이",
                                                     "type": "private"}, "text": "/start"}}]

    def call(token, method, params):
        return {"username": "demolab_test_bot"} if method == "getMe" else updates
    assert N.cmd_chatid(TOKEN, call=call) == 0
    o = capsys.readouterr().out
    assert TOKEN not in o and "/start@demolab_test_bot" in o and "시작(Start)" in o
    assert "방 번호 -1001234567890   이름 데모 랩   (supergroup)" in o
    assert "-1001234567890 로 바뀜" in o
    assert "개인 번호 42   이름 Kim   (개인)" in o and "개인 번호 7001   이름 민수 이   (개인)" in o
    assert o.index("(개인)") < o.index("supergroup")                      # people first (the default), then groups
    assert "DEMOBOT_TG_CHAT=123456789,987654321" in o and "쉼표" in o
    assert N.cmd_chatid(TOKEN, call=lambda t, m, p: {} if m == "getMe" else []) == 0
    assert "최근 메시지가 없습니다" in capsys.readouterr().out
    assert N.cmd_chatid("") == 2


def test_credentials_from_the_env_file(tmp_path):
    f = tmp_path / "demobot.env"
    f.write_text(f"# c\nDEMOBOT_TG_TOKEN='{TOKEN}'\nDEMOBOT_TG_CHAT=\"-100\"\nDEMOBOT_DASH_SECRET=zzz\n", encoding="utf-8")
    assert N.credentials(str(f), env={}) == (TOKEN, "-100")
    assert N.credentials(str(f), env={"DEMOBOT_TG_TOKEN": "a", "DEMOBOT_TG_CHAT": "b"}) == ("a", "b")
    assert N.credentials(str(tmp_path / "missing"), env={}) == ("", "")
    assert "DEMOBOT_DASH_SECRET" not in N.read_env_file(str(f))


# ---------------------------------------------------------------- the server kit (static)
def unit(name) -> dict:
    out: dict = {}
    sec = ""
    for ln in (KIT / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        k, _, v = ln.partition("=")
        out.setdefault(sec, {}).setdefault(k, []).append(v)
    return out


HARDENING = {"NoNewPrivileges": "yes", "PrivateTmp": "yes", "ProtectSystem": "strict", "ProtectHome": "yes",
             "PrivateDevices": "yes", "RestrictSUIDSGID": "yes"}
RULE_BOT_HIDDEN = {"-/etc/paperbot", "-/var/lib/paperbot", "-/var/backups/paperbot"}


def test_engine_unit():
    svc = unit("demobot-live.service")["[Service]"]
    assert svc["User"] == ["demobot"] and svc["WorkingDirectory"] == ["/opt/demobot/app"]
    assert svc["EnvironmentFile"] == ["/etc/demobot/demobot.env"]
    assert svc["ExecStart"] == ["/opt/demobot/venv/bin/python -m demobot run"]
    for k, v in {"Nice": "10", "CPUQuota": "30%", "MemoryMax": "1200M", "MemoryHigh": "900M", "Restart": "always",
                 "RestartSec": "20", **HARDENING}.items():
        assert svc[k] == [v], k
    assert svc["ReadWritePaths"] == ["/var/lib/demobot"]
    assert set(svc["InaccessiblePaths"][0].split()) >= RULE_BOT_HIDDEN
    env = " ".join(svc["Environment"]).split()
    assert {"OPENBLAS_NUM_THREADS=1", "OMP_NUM_THREADS=1", "MKL_NUM_THREADS=1"} <= set(env)


def test_dashboard_unit_is_read_only_and_waits_for_the_tailscale_address():
    u = unit("demobot-dash.service")
    svc = u["[Service]"]
    assert svc["User"] == ["demobot"] and svc["MemoryMax"] == ["300M"]
    assert svc["ExecStart"] == ["/opt/demobot/venv/bin/python -m demobot.dash --host ${DEMOBOT_DASH_HOST} "
                                "--port ${DEMOBOT_DASH_PORT}"]
    for k, v in HARDENING.items():
        assert svc[k] == [v], k
    assert "ReadWritePaths" not in svc                                       # writes nothing
    assert svc["TemporaryFileSystem"] == ["/var/lib/demobot:ro"] and svc["BindReadOnlyPaths"] == ["/var/lib/demobot/snap"]
    assert set(svc["InaccessiblePaths"][0].split()) >= RULE_BOT_HIDDEN | {"-/etc/demobot"}
    assert "DEMOBOT_TG_TOKEN" in svc["UnsetEnvironment"][0].split()
    pre = " ".join(svc["ExecStartPre"])
    assert "ip -4 -o addr show" in pre and "$$DEMOBOT_DASH_HOST" in pre
    assert any(not p.startswith("-") and "exit 1" in p for p in svc["ExecStartPre"])   # empty host: refuse
    assert "tailscaled.service" in u["[Unit]"]["After"][0]


def test_rank_unit_is_a_capped_oneshot_with_the_engines_sandbox():
    u = unit("demobot-rank.service")
    svc = u["[Service]"]
    live = unit("demobot-live.service")["[Service]"]
    assert svc["Type"] == ["oneshot"] and svc["ExecStart"] == ["/opt/demobot/venv/bin/python -m demobot rank"]
    for k in ("User", "Group", "UMask", "WorkingDirectory", "EnvironmentFile", "Environment", "UnsetEnvironment",
              "ReadWritePaths", "InaccessiblePaths", "RestrictAddressFamilies"):
        assert svc[k] == live[k], k                                        # same sandbox and env handling
    for k, v in {"Nice": "15", "CPUQuota": "50%", "MemoryHigh": "1200M", "MemoryMax": "1500M",
                 "TimeoutStartSec": "40min", **HARDENING}.items():
        assert svc[k] == [v], k
    assert svc["ReadWritePaths"] == ["/var/lib/demobot"]
    assert set(svc["InaccessiblePaths"][0].split()) >= RULE_BOT_HIDDEN
    assert "Restart" not in svc and "[Install]" not in u                    # started by its timer only


def test_rank_timer_hourly_at_minute_7():
    u = unit("demobot-rank.timer")
    t = u["[Timer]"]
    assert t["OnCalendar"] == ["*-*-* *:07:00"] and t["OnBootSec"] == ["10min"]
    assert t["Persistent"] == ["false"] and t["RandomizedDelaySec"] == ["0"]
    assert t["Unit"] == ["demobot-rank.service"] and u["[Install]"]["WantedBy"] == ["timers.target"]


def unit_files():
    return sorted(list(KIT.glob("*.service")) + list(KIT.glob("*.timer")))


def test_the_kit_has_the_units():
    assert {p.name for p in unit_files()} == {"demobot-live.service", "demobot-dash.service", "demobot-rank.service",
                                              "demobot-rank.timer", "demobot-backup.service", "demobot-backup.timer",
                                              "demobot-watch.service", "demobot-watch.timer"}


@pytest.mark.parametrize("name,cmd,mem,high", [("demobot-backup.service", "demobot.backup send", "300M", "250M"),
                                                ("demobot-watch.service", "demobot.watch", "150M", "120M")])
def test_backup_and_watch_units_are_small_oneshots_with_the_engines_sandbox(name, cmd, mem, high):
    u = unit(name)
    svc = u["[Service]"]
    live = unit("demobot-live.service")["[Service]"]
    assert svc["Type"] == ["oneshot"] and svc["ExecStart"] == [f"/opt/demobot/venv/bin/python -m {cmd}"]
    for k in ("User", "Group", "UMask", "WorkingDirectory", "EnvironmentFile", "Environment", "UnsetEnvironment",
              "ReadWritePaths", "InaccessiblePaths", "RestrictAddressFamilies", "ProtectKernelTunables",
              "ProtectKernelModules", "ProtectControlGroups", "LockPersonality", "IOSchedulingClass"):
        assert svc[k] == live[k], k
    for k, v in {"MemoryMax": mem, "MemoryHigh": high, "CPUQuota": "20%", **HARDENING}.items():
        assert svc[k] == [v], k
    assert int(svc["Nice"][0]) >= 10 and svc["User"] == ["demobot"]
    assert svc["ReadWritePaths"] == ["/var/lib/demobot"]
    assert set(svc["InaccessiblePaths"][0].split()) >= RULE_BOT_HIDDEN
    assert "Restart" not in svc and "[Install]" not in u                    # started by their timers only
    assert "network-online.target" in u["[Unit]"]["After"][0]
    assert "AF_UNIX" in svc["RestrictAddressFamilies"][0]                   # the watch asks systemd over D-Bus


def test_backup_timer_nightly_at_0440_kst_and_caught_up():
    u = unit("demobot-backup.timer")
    t = u["[Timer]"]
    assert t["OnCalendar"] == ["*-*-* 19:40:00 UTC"] and t["Persistent"] == ["true"]
    assert t["Unit"] == ["demobot-backup.service"] and u["[Install]"]["WantedBy"] == ["timers.target"]


def test_watch_timer_every_10_minutes():
    u = unit("demobot-watch.timer")
    t = u["[Timer]"]
    assert t["OnCalendar"] == ["*-*-* *:04/10:00"] and t["Persistent"] == ["false"]
    assert t["Unit"] == ["demobot-watch.service"] and u["[Install]"]["WantedBy"] == ["timers.target"]


@pytest.mark.parametrize("path", unit_files(), ids=lambda p: p.name)
def test_units_mention_the_rule_bot_only_to_hide_it(path):
    for ln in path.read_text(encoding="utf-8").splitlines():
        if "paperbot" in ln:
            assert ln.startswith("InaccessiblePaths="), ln


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="no systemd-analyze")
def test_units_verify():
    r = subprocess.run(["systemd-analyze", "verify", *map(str, unit_files())], capture_output=True, text=True)
    problems = [ln for ln in (r.stdout + r.stderr).splitlines()
                if ln.strip() and "is not executable" not in ln and "/opt/demobot/venv" not in ln]
    assert problems == []


def test_the_scripts_handle_the_ranking_timer():
    text = {p.name: p.read_text(encoding="utf-8") for p in scripts()}
    inst = text["install_demobot.sh"]
    assert "demobot-rank.service demobot-rank.timer" in inst                 # both files installed
    assert re.search(r'SWAP_UNITS="[^"]*demobot-rank\.timer', inst)          # paused for the code swap
    enable = inst[inst.index('if [ "$DB_EXISTED" = 1 ]; then'):]
    assert "systemctl enable --quiet demobot-live.service demobot-rank.timer" in enable    # same 'ready' rule
    assert "demobot-rank.timer" in text["on.sh"] and "systemctl start --no-block demobot-rank.service" in text["on.sh"]
    assert "disable --now --quiet demobot-live.service demobot-dash.service demobot-rank.timer" in text["off.sh"]
    assert "/etc/systemd/system/demobot-rank.timer" in text["uninstall.sh"]
    assert "systemctl start demobot-rank.service" in text["warm.sh"]


def test_the_scripts_handle_the_backup_and_watch_timers():
    text = {p.name: p.read_text(encoding="utf-8") for p in scripts()}
    inst = text["install_demobot.sh"]
    files = re.search(r'UNIT_FILES="([^"]+)"', inst)[1].replace("\\\n", " ").split()
    assert set(files) >= {"demobot-backup.service", "demobot-backup.timer", "demobot-watch.service",
                          "demobot-watch.timer"}
    swap = re.search(r'SWAP_UNITS="([^"]+)"', inst)[1].split()
    assert {"demobot-backup.timer", "demobot-watch.timer"} <= set(swap)
    assert set(re.search(r'ONESHOTS="([^"]+)"', inst)[1].split()) == {"demobot-rank.service", "demobot-backup.service",
                                                                       "demobot-watch.service"}
    enable = inst[inst.index('if [ "$DB_EXISTED" = 1 ]; then'):inst.index("echo \"== firewall\"")]
    assert ("systemctl enable --quiet demobot-live.service demobot-rank.timer demobot-backup.timer "
            "demobot-watch.timer") in enable
    upd = enable[enable.index("else"):]                                      # update: switched on when the engine is
    assert "systemctl is-enabled --quiet demobot-live.service" in upd and "for t in $NEW_TIMERS" in upd
    assert 'systemctl enable --quiet "$t"' in upd and 'systemctl start "$t"' in upd
    assert re.search(r'NEW_TIMERS="demobot-backup\.timer demobot-watch\.timer"', inst)
    keys = re.search(r'OPTIONAL_KEYS="([^"]+)"', inst)[1].split()
    assert keys == ["DEMOBOT_DEADMAN_URL", "DEMOBOT_BACKUP_CHAT", "DEMOBOT_BACKUP_PASSPHRASE"]
    assert 'echo "$k="' in inst and '>> "$ENVF"' in inst                     # empty lines only, never a value
    on = text["on.sh"]
    assert "for t in demobot-backup.timer demobot-watch.timer" in on and '/etc/systemd/system/$t' in on
    off = text["off.sh"]
    assert "disable --now --quiet demobot-backup.timer demobot-watch.timer 2>/dev/null || true" in off
    assert "systemctl stop demobot-rank.service demobot-backup.service demobot-watch.service" in off
    un = text["uninstall.sh"]
    for f in ("demobot-backup.service", "demobot-backup.timer", "demobot-watch.service", "demobot-watch.timer"):
        assert f"/etc/systemd/system/{f}" in un
    assert "demobot-watch.timer" in text["warm.sh"]
    assert "install_demobot.sh\" --update" in text["update.sh"]


def test_update_adds_the_missing_optional_keys_to_an_old_env_file(tmp_path):
    """The env-file block of install_demobot.sh, run on a round-2 env file: three empty keys appended, once."""
    inst = (KIT / "install_demobot.sh").read_text(encoding="utf-8")
    block = inst[inst.index('ADDED=""'):inst.index('DB_PATH="$(envval DEMOBOT_DB)"')]
    keys = re.search(r'OPTIONAL_KEYS="[^"]+"', inst)[0]
    envf = tmp_path / "demobot.env"
    old = "DEMOBOT_TG_TOKEN=x\nDEMOBOT_TG_CHAT=-100\n#DEMOBOT_BACKUP_CHAT=\n"
    envf.write_text(old, encoding="utf-8")
    script = f'set -euo pipefail\nENVF="{envf}"\n{keys}\n{block}'
    for _ in range(2):
        subprocess.run(["bash", "-c", script], check=True, capture_output=True)
    got = envf.read_text(encoding="utf-8")
    assert got.startswith(old) and got.count("DEMOBOT_DEADMAN_URL=") == 1
    assert got.count("\nDEMOBOT_BACKUP_PASSPHRASE=\n") == 1 and got.count("DEMOBOT_BACKUP_CHAT=") == 1


def scripts():
    return sorted(KIT.glob("*.sh"))


def code_lines(p: Path):
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_scripts_never_start_or_stop_a_rule_bot_unit_and_never_print_an_env_file():
    assert {p.name for p in scripts()} >= {"install_demobot.sh", "capacity_check.sh", "on.sh", "off.sh", "update.sh",
                                           "uninstall.sh", "warm.sh", "firewall.sh"}
    for p in scripts():
        for ln in code_lines(p):
            if re.search(r"systemctl\s+(\S+\s+)*(start|stop|restart|enable|disable|kill|mask|reload|try-restart)\b", ln):
                assert "paperbot" not in ln, (p.name, ln)
            if "/etc/paperbot" in ln or "/var/lib/paperbot" in ln:
                assert "InaccessiblePaths" in ln, (p.name, ln)              # only to hide them (warm.sh)
            assert not re.search(r"\b(cat|less|more|head|tail)\b[^|<]*\.env\b", ln), (p.name, ln)
            assert not re.search(r"\b(cat|less|more|head|tail)\b[^|<]*\$ENVF", ln), (p.name, ln)
            if re.search(r"\b(echo|printf)\b", ln):                     # a secret's VALUE is never printed
                assert not re.search(r"\$\((env)?val\s+DEMOBOT_(TG_TOKEN|DASH_SECRET|DASH_PASSWORD_HASH)\)", ln), ln
                assert not re.search(r"\$\{?[HS]\}?\b", ln) or p.name != "on.sh", ln


def test_capacity_check_is_read_only():
    text = "\n".join(code_lines(KIT / "capacity_check.sh"))
    for bad in ("systemctl start", "systemctl stop", "systemctl restart", "systemctl enable", "ufw allow",
                "useradd", "rm ", "mkdir", "install -d", "install -m", " > /", "tee "):
        assert bad not in text, bad
    assert not re.search(r"^\s*(sudo\s+)?apt(-get)?\s", text, re.M)          # only named in a hint, never run
    assert "같은 서버에 설치해도 됩니다" in text and "2048" in text and "3072" in text and "0.7" in text
    assert "약 800 MB" in text and "약 1.8 GB" in text and "순위표" in text


def test_install_copies_only_the_listed_paths_and_handles_the_env_file_safely():
    text = (KIT / "install_demobot.sh").read_text(encoding="utf-8")
    m = re.search(r'CODE_PATHS="([^"]+)"', text)
    paths = m[1].replace("\\\n", " ").split()
    assert paths == ["demobot", "paperbot", "third_party/sweep", "research/entry_study/param_defs",
                     "research/entry_study/DEFS_BC.sha256", "research/st_custom/out/picks.csv",
                     "research/st_custom/PREREG.md", "research/st_custom/PREREG.sha256"]
    for p in paths:
        assert (REPO / p).exists(), p
    assert "--exclude='paperbot/dash/static'" in text
    assert 'if [ ! -f "$ENVF" ]; then' in text and "-m 640" in text and "chown root:demobot \"$ENVF\"" in text
    assert 'if [ "$(id -u)" -ne 0 ]' in text and "app.old" in text and "app.new" in text
    assert "-m demobot selfcheck" in text and "unknown command" in text
    fw = (KIT / "firewall.sh").read_text(encoding="utf-8")
    assert "ufw allow in on tailscale0 to any port" in fw and "Anywhere on tailscale0" in fw
    assert 'bash "$HERE/firewall.sh"' in text and 'bash "$HERE/firewall.sh"' in (KIT / "on.sh").read_text(encoding="utf-8")


def test_plugins_folder_is_made_but_its_files_never_touched():
    inst = (KIT / "install_demobot.sh").read_text(encoding="utf-8")
    assert "PLUGINS=$ETC/plugins" in inst and 'install -d -o root -g demobot -m 750 "$PLUGINS"' in inst
    for ln in code_lines(KIT / "install_demobot.sh"):
        if "PLUGINS" in ln or "plugins" in ln:
            assert ln.startswith("PLUGINS=") or ln.startswith('install -d -o root -g demobot -m 750 "$PLUGINS"'), ln
    for p in scripts():                                                    # no script changes what is inside
        for ln in code_lines(p):
            assert not re.search(r"\b(rm|chmod|chown|cp|mv|tee|install)\b[^#]*/etc/demobot/plugins/", ln), (p.name, ln)
            assert not re.search(r"\b(cat|less|more|head|tail)\b[^|]*plugins", ln), (p.name, ln)
    dash = unit("demobot-dash.service")["[Service]"]
    assert "-/etc/demobot" in dash["InaccessiblePaths"][0].split()          # the dashboard cannot see the plug-ins
    for name in ("demobot-live.service", "demobot-rank.service"):           # the engine and the ranking read them
        svc = unit(name)["[Service]"]
        hidden = " ".join(svc.get("InaccessiblePaths", [])) + " ".join(svc.get("TemporaryFileSystem", []))
        assert "/etc/demobot" not in hidden and svc["User"] == ["demobot"] and svc["ProtectSystem"] == ["strict"]
    assert "#DEMOBOT_PLUGINS=/etc/demobot/plugins" in (KIT / "demobot.env.example").read_text(encoding="utf-8")


def test_env_example_has_the_contract_keys_and_no_values():
    kv = dict(ln.split("=", 1) for ln in (KIT / "demobot.env.example").read_text(encoding="utf-8").splitlines()
              if ln and not ln.startswith("#"))
    assert set(kv) == {"DEMOBOT_TG_TOKEN", "DEMOBOT_TG_CHAT", "DEMOBOT_DASH_PASSWORD_HASH", "DEMOBOT_DASH_SECRET",
                       "DEMOBOT_DASH_HOST", "DEMOBOT_DASH_PORT", "DEMOBOT_DB", "DEMOBOT_SNAP",
                       "DEMOBOT_DEADMAN_URL", "DEMOBOT_BACKUP_CHAT", "DEMOBOT_BACKUP_PASSPHRASE"}
    assert all(kv[k] == "" for k in ("DEMOBOT_TG_TOKEN", "DEMOBOT_TG_CHAT", "DEMOBOT_DASH_PASSWORD_HASH",
                                     "DEMOBOT_DASH_SECRET", "DEMOBOT_DEADMAN_URL", "DEMOBOT_BACKUP_CHAT",
                                     "DEMOBOT_BACKUP_PASSPHRASE"))
    lines = (KIT / "demobot.env.example").read_text(encoding="utf-8").splitlines()
    for k in ("DEMOBOT_DEADMAN_URL", "DEMOBOT_BACKUP_CHAT", "DEMOBOT_BACKUP_PASSPHRASE"):   # a Korean comment above
        i = lines.index(f"{k}=")
        assert any(re.search(r"[가-힣]", ln) for ln in lines[max(0, i - 3):i] if ln.startswith("#")), k
    assert "healthchecks.io" in "\n".join(lines) and "openssl rand -hex" in "\n".join(lines)
    assert kv["DEMOBOT_DASH_PORT"] == "8090" and kv["DEMOBOT_DASH_HOST"] == "127.0.0.1"
    assert kv["DEMOBOT_DB"] == "/var/lib/demobot/demo.db" and kv["DEMOBOT_SNAP"] == "/var/lib/demobot/snap"


@pytest.mark.skipif(not shutil.which("bash"), reason="no bash")
@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.name)
def test_scripts_parse(path):
    subprocess.run(["bash", "-n", str(path)], check=True)
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", "-S", "warning", str(path)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout


def test_owner_guide():
    text = DOC.read_text(encoding="utf-8")
    assert ("git clone --branch claude/keen-pasteur-wav02u --depth 1 "
            "https://github.com/g1792091-boop/crypto-bot-research /root/demobot-src") in text
    assert "SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env" in text
    assert "python -m demobot.notify chatid" in text and "demobot.dash hash" in text
    assert "openssl rand -hex 32" in text and "tailscale ip -4" in text and ":8090" in text
    assert "systemctl list-timers demobot-rank.timer" in text and "매시 7분" in text
    assert "/setprivacy" in text and "`Disable`" in text and "관리자" in text      # the bot must read the group
    views = text[text.index("## 6. 관점 기록장 쓰는 법"):text.index("## 7.")]
    assert all(x in views for x in N.VIEW_EXAMPLES) and N.VIEW_USAGE in views
    assert "취소 12" in views and "관점목록" in views and "관점도움" in views and "GitHub" in views
    plug = text[text.index("## 7. 비공개 매매법 넣기 (선택)"):text.index("## 8.")]
    assert "/etc/demobot/plugins/" in plug and "sha256" in plug and "root:demobot, 640" in plug
    assert "sudo rm /etc/demobot/plugins/<파일 이름>.py" in plug
    assert plug.count("sudo bash /root/demobot-src/deploy/demobot/on.sh") == 2
    assert not re.search(r"\bcat\b[^\n|]*(\.env|/etc/demobot)", text)
    assert "cd /opt/crypto-bot-research" not in text and "deploy/install.sh" not in text   # the rule bot's kit


def test_owner_guide_private_chats_are_the_default():
    text = DOC.read_text(encoding="utf-8")
    tg = text[text.index("## 2. 텔레그램"):text.index("## 3.")]
    assert "개인 대화" in tg and "시작**(Start)" in tg and "/start" in tg
    assert "python -m demobot.notify chatid" in tg and "(개인)" in tg
    assert "SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env" in tg and "DEMOBOT_TG_CHAT=123456789,987654321" in tg
    assert "쉼표" in tg and "보냈습니다 (2곳)" in tg and "무시합니다" in tg
    assert "개인 대화에는 BotFather의 `/setprivacy` 설정이 필요 없습니다" in tg
    group = tg[tg.index("**단체방으로 받으려면 (선택)**"):]
    assert "/setprivacy" in group and "`Disable`" in group and "관리자" in group
    assert "/setprivacy" not in tg[:tg.index("**단체방으로 받으려면")].replace("`/setprivacy` 설정이 필요 없습니다", "")
    views = text[text.index("## 6. 관점 기록장 쓰는 법"):text.index("## 7.")]
    assert "개인 대화" in views and "두 분 모두" in views
    up = text[text.index("## 12."):text.index("## 13.")]
    assert "개인 대화" in up and "off.sh" in up and "DEMOBOT_TG_CHAT=번호1,번호2" in up
    rest = text.replace(tg, "").replace(up, "")
    assert all("단체방" not in ln or "DEMOBOT_TG_CHAT" in ln for ln in rest.splitlines()), \
        [ln for ln in rest.splitlines() if "단체방" in ln]


def guide_section(text, head, nxt):
    return text[text.index(head):text.index(nxt)]


def test_owner_guide_round3_sections():
    text = DOC.read_text(encoding="utf-8")
    heads = re.findall(r"^## (\d+)\. ", text, re.M)
    assert heads == [str(i) for i in range(14)]                               # numbered 0..13, in order
    hc = guide_section(text, "## 9. 서버 밖 감시: healthchecks.io", "## 10.")
    assert "새 체크" in hc and "`demolab`" in hc and "Period 15 minutes" in hc and "Grace Time 30 minutes" in hc
    assert "Ping URL" in hc and "채팅" in hc and "SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env" in hc
    assert "DEMOBOT_DEADMAN_URL=" in hc and "초록(up)" in hc and "on.sh" in hc
    bk = guide_section(text, "## 10. 밤 백업과 되살리기", "## 11.")
    assert "04:40" in bk and "주간 회의록" in bk and "관점 기록" in bk and "들어 있지 않은 것" in bk
    assert "바이낸스" in bk and "DEMOBOT_BACKUP_PASSPHRASE=" in bk and "openssl rand -hex 24" in bk
    assert "sudo -u demobot /opt/demobot/venv/bin/python -m demobot.backup now" in bk
    assert "-m demobot.backup restore /var/lib/demobot/" in bk and "off.sh" in bk and "integrity_check" in bk
    assert "sudo install -o demobot -g demobot -m 600" in bk and "warm.sh" in bk
    w = guide_section(text, "## 11. 감시 (10분마다)", "## 12.")
    assert all(ko.split(" (")[0] in w for ko in (N.WARN_KO["dead"], N.WARN_KO["rank"], N.WARN_KO["backup"]))
    assert "3시간에 한 번" in w and "✅ 데모 랩 회복" in w and "healthchecks.io" in w
    up = guide_section(text, "## 12. 업데이트: 이미 설치한 서버 (2차 → 3차)", "## 13.")
    assert "cd /root/demobot-src && git pull && sudo bash deploy/demobot/update.sh" in up
    assert "systemctl list-timers 'demobot-*'" in up and "demobot-backup.timer" in up and "demobot-watch.timer" in up
    assert "== 요약" in up and "9번" in up and "10번" in up
    assert "## 13. 이 봇이 하지 않는 것" in text
    assert "12번 업데이트만" in text[:text.index("## 0.")]                       # existing installs: told at the top
