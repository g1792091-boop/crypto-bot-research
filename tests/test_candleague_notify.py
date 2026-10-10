"""candleague/notify.py: the [후보 리그] tag, the summary once a day after 09:00 KST when caught up, bust notices
once, DeepSeek money hidden, a Telegram failure never raises."""

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
    t = N.summary_text(_doc())
    assert t.startswith("[후보 리그] 아침 요약 (10-05 09:00 KST까지)")
    assert "S2_ST_ROC 15m (고정 익절 2R · 손절 1.5 ATR): 12건, 한 번 평균 +0.40%, 잔고 $5,200" in t
    assert "기본값 +0.10%, 동전 -0.10%" in t and "아직 판단 이름" in t
    assert "F17_Z 15m (고정 익절 2R · 손절 1.5 ATR): 7건 (딥시크: 금액 숨김)" in t


def test_once_a_day_and_bust_once(tmp_path):
    conn = RN.open_db(str(tmp_path / "l.db"))
    sent = []
    nt = N.Notifier(conn, sender=sent.append)
    assert nt.after_pass(_doc(), KST9 - 60_000, caught_up=True) == []            # 08:59 KST
    assert nt.after_pass(_doc(), KST9 + 60_000, caught_up=False) == []           # still catching up
    assert len(nt.after_pass(_doc(), KST9 + 120_000, caught_up=True)) == 1        # the day's summary
    assert nt.after_pass(_doc(), KST9 + 3_600_000, caught_up=True) == []          # not twice
    out = nt.after_pass(_doc(bust=True), KST9 + 7_200_000, caught_up=True)
    assert len(out) == 1 and out[0].startswith("[후보 리그] 파산: F17_Z 15m (cand)")
    assert nt.after_pass(_doc(bust=True), KST9 + 7_300_000, caught_up=True) == []
    assert len(sent) == 2 and all(t.startswith("[후보 리그]") for t in sent)


def test_a_telegram_failure_never_raises(tmp_path):
    conn = RN.open_db(str(tmp_path / "l.db"))

    def boom(text):
        raise OSError("down")
    assert len(N.Notifier(conn, sender=boom).after_pass(_doc(bust=True), KST9 + 60_000, caught_up=True)) == 2


def test_below_the_band_is_told_once(tmp_path):
    conn = RN.open_db(str(tmp_path / "l.db"))
    nt = N.Notifier(conn)
    doc = _doc()
    doc["judge"]["c1"]["band"] = {"n": 10, "below": True, "p5": 0.006, "median": 0.01}
    out = nt.after_pass(doc, KST9 - 3_600_000, caught_up=True)
    assert len(out) == 1 and out[0].startswith("[후보 리그] 예상보다 아래: S2_ST_ROC 15m") and "+0.40% < 백테스트 하위 5% +0.60%" in out[0]
    assert nt.after_pass(doc, KST9 - 3_000_000, caught_up=True) == []
