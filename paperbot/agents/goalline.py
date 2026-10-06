"""목표 진척도 한 줄 (owners' round 2, 10/06): how far the project is from its goal, in one line of code text that the
dashboard's 홈 shows on top and the 22:00 evening Telegram can carry (rooms.compose_evening, AGENTS_GOAL_LINE=1):

    오늘 5년 시험 3개(통과 0) · 동전보다 나은 새 매매법 후보 0개(시험 57개라 운만으로도 많아야 0.24개) · 첫 판정 D-23(11/04)

- tests today: the counted 5-year tests whose first result was written in today's KST day (the lab's 'newlab' trials and
  the strategy rooms' 'test' trials that ran: passed / failed / described; one that could not run is not a test), and
  how many of them passed their gate when they ran;
- candidates better than coin flips: the new-strategy tests whose latest result is a pass (rooms_db.NEWLAB_PASSED; gate
  ⑥ of every new-strategy test is 'better than the coin flips', docs/newlab-prereg.md), next to what luck alone gives
  with the same gate rule (the luck-calc's own numbers, paperbot/dash/more/luck.py: at most the sum of 0.05 / i over
  the tests, and the chance of seeing at least that many passes by luck);
- the verdict: D-day to the next 30-day verdict (00:00 UTC = 09:00 KST of day 30k after the run start, the same date the
  dashboard's top bar and 졸업 길 name), or that the first verdict day passed without a record yet.

Read-only on every database; no AI. Nothing here says pass or fail about a paper account before the verdict.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from . import rooms_db as R

DAY_MS = 86_400_000
KST_MS = 9 * 3_600_000
RAN = ("passed", "failed", "described")          # a first result that means the test ran (and counted)


def _mmdd(ms: int) -> str:
    return time.strftime("%m/%d", time.gmtime((int(ms) + KST_MS) / 1000))


def days_left(ts: int, now: int) -> int:
    """Whole KST days from today to the day of ``ts`` (0 = today), the way 졸업 길 counts its D-day."""
    return int((int(ts) + KST_MS) // DAY_MS - (int(now) + KST_MS) // DAY_MS)


def tests_today(agents_ro: Optional[sqlite3.Connection], now: int) -> dict:
    """{tests, passed, newlab, room}: counted 5-year tests whose first result came in today's KST day."""
    out = {"tests": 0, "passed": 0, "newlab": 0, "room": 0}
    if agents_ro is None:
        return out
    day0 = R.kst_day_start_ms(now)
    try:
        rows = agents_ro.execute(
            "SELECT t.kind, r.status FROM trials t JOIN trial_results r ON r.id = "
            "(SELECT MIN(id) FROM trial_results WHERE trial_id = t.id) "
            "WHERE t.kind IN ('newlab', 'test') AND r.ts >= ? AND r.ts < ?", (day0, day0 + DAY_MS)).fetchall()
    except sqlite3.Error:
        return out
    for kind, status in rows:
        if status not in RAN:
            continue
        out["tests"] += 1
        out["passed"] += status == "passed"
        out["newlab" if kind == "newlab" else "room"] += 1
    return out


def newlab_luck(agents_ro: Optional[sqlite3.Connection]) -> dict:
    """{tested, passed, luck, tail}: every new-strategy test (all rooms), the latest-result passes, what luck alone gives
    under the gate's growing strictness (the luck-calc's harmonic sum and Poisson-binomial tail, dash/more/luck.py)."""
    from ..dash.more.luck import ALPHA, pb_tail
    out = {"tested": 0, "passed": 0, "luck": 0.0, "tail": None}
    if agents_ro is None:
        return out
    try:
        rows = agents_ro.execute(
            "SELECT t.id, (SELECT r.status FROM trial_results r WHERE r.trial_id = t.id ORDER BY r.id DESC LIMIT 1) "
            "FROM trials t WHERE t.kind = 'newlab' ORDER BY t.id").fetchall()
    except sqlite3.Error:
        return out
    n = len(rows)
    passed = sum(1 for _tid, st in rows if st in R.NEWLAB_PASSED)
    ps = [ALPHA / i for i in range(1, n + 1)]
    out.update(tested=n, passed=passed, luck=round(sum(ps), 4), tail=round(pb_tail(ps, passed), 4) if n else None)
    return out


def verdict_day(paper_ro: Optional[sqlite3.Connection], checkpoint_db: Optional[str], now: int) -> dict:
    """{k, ts, mmdd, left, ready, overdue}: the next 30-day verdict after ``now`` (k-th), the latest verdict's existence
    (``ready``), and ``overdue`` when a verdict day passed but checkpoint.db has no verdict yet."""
    from .. import checkpoint as CK
    from .readiness import checkpoint_view
    start = None
    if paper_ro is not None:
        try:
            start = CK.run_facts(paper_ro).get("start_ts")
        except (sqlite3.Error, ValueError, TypeError):
            start = None
    cp = checkpoint_view(checkpoint_db) if checkpoint_db else {"ready": False}
    out: dict = {"k": None, "ts": None, "mmdd": None, "left": None, "ready": bool(cp.get("ready")), "overdue": False,
                 "date": cp.get("date"), "ended": False}
    if not start:
        return out
    k = 1
    while CK.checkpoint_ts(int(start), k) <= int(now):
        k += 1
    if k * CK.PERIOD_DAYS > CK.NO_VERDICT_DAYS:
        # the rules: after day NO_VERDICT_DAYS (180) the run is observation only, no new verdict (checkpoint.py)
        out.update(ended=True, end_day=CK.NO_VERDICT_DAYS)
        return out
    ts = CK.checkpoint_ts(int(start), k)
    out.update(k=k, ts=ts, mmdd=_mmdd(ts), left=days_left(ts, now), overdue=k > 1 and not out["ready"])
    return out


def _num(x: float) -> str:
    return f"{x:.2f}" if x < 10 else f"{x:.0f}"


def goal(agents_ro: Optional[sqlite3.Connection], paper_ro: Optional[sqlite3.Connection],
         checkpoint_db: Optional[str], now: Optional[int] = None) -> dict:
    """The line's numbers and its Korean text (``text_ko``, one line; ``parts`` for a screen that lays them out)."""
    now = int(time.time() * 1000) if now is None else int(now)
    t = tests_today(agents_ro, now)
    nl = newlab_luck(agents_ro)
    v = verdict_day(paper_ro, checkpoint_db, now)
    p1 = f"오늘 5년 시험 {t['tests']:,}개(통과 {t['passed']:,})"
    if nl["tested"]:
        p2 = (f"동전보다 나은 새 매매법 후보 {nl['passed']:,}개(시험 {nl['tested']:,}개라 운만으로도 많아야 "
              f"{_num(nl['luck'])}개)")
    else:
        p2 = "동전보다 나은 새 매매법 후보 0개(아직 새 매매법 시험 없음)"
    if v.get("ended"):
        p3 = f"판정 기간 끝({v['end_day']}일 뒤로는 새 판정 없이 관찰만)"
    elif v["ts"] is None:
        p3 = "판정 날짜는 봇이 첫 계좌를 만들면 정해짐"
    elif v["overdue"]:
        p3 = "첫 판정일 지남 · 판정 기록 기다림"
    else:
        name = "첫 판정" if v["k"] == 1 else "다음 판정"
        p3 = f"{name} " + (f"D-{v['left']}" if v["left"] and v["left"] > 0 else "오늘") + f"({v['mmdd']})"
    return {"now": now, "tests_today": t, "newlab": nl, "verdict": v, "parts": [p1, p2, p3],
            "text_ko": " · ".join([p1, p2, p3]),
            "caveat_ko": ("후보는 5년 자료의 관문(동전 비교 ⑥ 포함)을 넘은 새 매매법입니다. 시험을 많이 할수록 운으로 넘는 것도 "
                          "생기므로 운으로 나올 수와 함께 봅니다. 모의 계좌의 합격·불합격은 30일 판정에서만 정합니다.")}


def telegram_line(agents_ro: Optional[sqlite3.Connection], paper_ro: Optional[sqlite3.Connection],
                  checkpoint_db: Optional[str], now: Optional[int] = None) -> str:
    """'🎯 목표 진척도: …' for the evening Telegram; '' when it cannot be read (the message goes out without it)."""
    try:
        return "🎯 목표 진척도: " + goal(agents_ro, paper_ro, checkpoint_db, now)["text_ko"]
    except Exception:  # noqa: BLE001  (one optional line never stops the evening report)
        return ""
