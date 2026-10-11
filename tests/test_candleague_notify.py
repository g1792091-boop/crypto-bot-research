"""candleague/notify.py: the rule bot's wording (emoji, title, blank line, short lines, KST time last, 후보 리그 named),
the summary once a day after 09:00 KST when caught up, bust notices once, DeepSeek money hidden when it is, a Telegram
failure never raises, every message silent."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import notify as N  # noqa: E402
from candleague import runner as RN  # noqa: E402

KST9 = 1_791_158_400_000 + 0 * 3_600_000          # 2026-10-05 00:00 UTC = 09:00 KST


def _doc(bust=False):
    def r(i, role, kind, n, m, w, b=False):
        return {"id": i, "role": role, "kind": kind, "name": "S2_ST_ROC" if kind == "core" else "F17_Z", "tf": "15m",
                "exit_ko": "고정 익절 2R · 손절 1.5 ATR", "trades": n, "mean_ret": m, "wallet": w, "bust": b}
    accounts = [r("c1", "cand", "core", 12, 0.004, 5200.0), r("c1-flip", "flip", "core", 12, -0.001, 4900.0),
                r("base-core-S2_ST_ROC-15m", "base", "core", 20, 0.001, 5050.0),
                r("d1", "cand", "ds", 7, None, None, b=bust)]
    return {"done_ms": KST9, "lag_s": 30, "accounts": accounts, "judge": {"c1": {"verdict": "early"},
                                                                         "d1": {"verdict": "early"}}}


def test_summary_text():
    doc = _doc()
    doc["start_ms"] = KST9 - 4 * 86_400_000
    doc["watch"] = {"checkpoints": [{"ko": "1차 점검", "ms": KST9 + 37 * 86_400_000, "days_left": 37.0}],
                    "pools": {"core": {"picks": 1, "money": True, "roles": {"cand": {"n": 12, "mean": 0.004}},
                                       "c2": {"beats_base": True, "beats_flip": False}},
                              "ds": {"picks": 1, "money": False, "roles": {"cand": {"n": 7, "mean": None}},
                                     "c2": {"beats_base": None, "beats_flip": True}}}}
    t = N.summary_text(doc, KST9 + 60_000)
    lines = t.split("\n")
    assert lines[0] == "📊 아침 요약 · 후보 리그" and lines[1] == "" and lines[-1] == "10/05 09:01 KST"
    assert "10/01부터 5일째 · 10/05 09:00 KST까지 처리" in t and "다음 점검: 1차 11/11 · 37일 남음" in t
    assert "  후보 거래 12번 · 한 번 평균 +0.40%" in t and "  기본값보다 ▲ · 동전보다 ▼" in t
    assert "딥시크 묶음 (후보 1개)" in t and "  후보 거래 7번 · 금액 숨김" in t and "  기본값보다 — · 동전보다 ▲" in t
    assert "1. S2_ST_ROC 15분 · +0.40% · 12번 · $5,200" in t and "(거래 30번 전이라 운이 큽니다. 판단은 하지 않습니다)" in t
    assert "(딥시크 후보 1개는 금액 숨김 설정이라 순위에서 빠짐)" in t and "후보 리그 · 종이 매매 (실제 돈 아님)" in t
    assert "📌" not in t
    doc["watch"]["checkpoints"] = [{"ko": "1차 점검", "ms": KST9, "days_left": -0.001},
                                   {"ko": "2차 점검", "ms": KST9 + 30 * 86_400_000, "days_left": 29.999}]
    t = N.summary_text(doc, KST9 + 60_000)                  # 11/11-like: the checkpoint's own morning
    assert "📌 오늘 1차 점검 날입니다 · 확정 결과는 대시보드 '점검 진행' 맨 위" in t and "다음 점검: 2차" in t


def test_korean_names_and_silent_sending(monkeypatch):
    assert N.strat_ko("DOGE") == "도지 봇" and N.strat_ko("NOPE") == "NOPE"
    assert N.pick_ko({"name": "F5_BOX", "tf": "4h", "role": "quarter"}) == "박스권 양 끝 반전 4시간 1/4 크기"
    sent = {}

    class R:
        def read(self):
            return b"{}"

    def fake(url, body, timeout):
        sent["url"], sent["body"] = url, body.decode()
        return R()
    monkeypatch.setattr(N.urllib.request, "urlopen", fake)
    N.send_telegram("T", "42", "hi")
    assert "disable_notification=true" in sent["body"] and "chat_id=42" in sent["body"]


def test_once_a_day_and_bust_once(tmp_path):
    conn = RN.open_db(str(tmp_path / "l.db"))
    sent = []
    nt = N.Notifier(conn, sender=sent.append)
    assert nt.after_pass(_doc(), KST9 - 60_000, caught_up=True) == []            # 08:59 KST
    assert nt.after_pass(_doc(), KST9 + 60_000, caught_up=False) == []           # still catching up
    assert len(nt.after_pass(_doc(), KST9 + 120_000, caught_up=True)) == 1        # the day's summary
    assert nt.after_pass(_doc(), KST9 + 3_600_000, caught_up=True) == []          # not twice
    out = nt.after_pass(_doc(bust=True), KST9 + 7_200_000, caught_up=True)
    assert len(out) == 1 and out[0].startswith("🚨 후보 리그 파산 · F17_Z 15분\n\n") and "후보 리그" in out[0]
    assert nt.after_pass(_doc(bust=True), KST9 + 7_300_000, caught_up=True) == []
    assert len(sent) == 2 and all("후보 리그" in t and t.split("\n")[1] == "" for t in sent)


def test_a_telegram_failure_never_raises(tmp_path):
    conn = RN.open_db(str(tmp_path / "l.db"))

    def boom(text):
        raise OSError("down")
    assert len(N.Notifier(conn, sender=boom).after_pass(_doc(bust=True), KST9 + 60_000, caught_up=True)) == 2


def test_one_failing_chat_never_stops_the_others(tmp_path, monkeypatch):
    conn = RN.open_db(str(tmp_path / "l.db"))
    got = []

    def send(token, chat, text):
        if chat == "111":
            raise OSError("blocked")
        got.append(chat)
    monkeypatch.setattr(N, "send_telegram", send)
    monkeypatch.setenv("CANDLEAGUE_TG_TOKEN", "T")
    monkeypatch.setenv("CANDLEAGUE_TG_CHAT", "111,222")
    assert len(N.Notifier(conn).after_pass(_doc(bust=True), KST9 + 60_000, caught_up=True)) == 2
    assert got == ["222", "222"]


def test_below_the_band_is_told_once(tmp_path):
    conn = RN.open_db(str(tmp_path / "l.db"))
    nt = N.Notifier(conn)
    doc = _doc()
    doc["judge"]["c1"]["band"] = {"n": 10, "below": True, "p5": 0.006, "median": 0.01}
    out = nt.after_pass(doc, KST9 - 3_600_000, caught_up=True)
    assert len(out) == 1 and out[0].startswith("⚠ 후보 리그 경고등 · S2_ST_ROC 15분\n\n") and "한 번 평균 +0.40%" in out[0]
    assert "백테스트 예상 하위 5% +0.60%보다 낮음" in out[0]
    assert nt.after_pass(doc, KST9 - 3_000_000, caught_up=True) == []
