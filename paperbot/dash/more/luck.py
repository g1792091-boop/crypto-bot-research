"""운 vs 실력 (luck-calc, owners' idea 1 '운으로 통과할 개수'): for every place where this project tests many things at
once, how many were tested, the pass rule, how many would pass by luck alone, how many really passed, and one plain
verdict line. Read-only: the bot's databases (``mode=ro``), the research summaries and paperbot/dash/data/*.json;
nothing is computed again here except the small 'luck alone' numbers (exact sums or a seeded simulation).

    GET /api/v4/luck        (background + cached ``TTL_S``; the first answer may be ``{"pending": true}``)

Places (``rows``, each {id, part: now|past, title, where, tested, rule_ko, luck, luck_ko, passed, passed_ko, tail,
verdict, verdict_ko, note}):

now (this run's own records)
- ``checkpoint``  30일 판정 (paperbot/checkpoint.py): before the verdict the accounts it can judge (paper3.db, judged
                  timeframes per family) and the luck numbers of its rule (BH per family at FAMILY_ALPHA under 'no
                  account has any skill': a seeded simulation of uniform p-values); after it the verdict's own
                  tested / luck_passed / lucky_expected. Never a pass hint before ``ready`` (verdict 'before').
- ``newlab``      새 매매법 시험실 (agents3.db trials kind 'newlab'; gate (a) p < 0.05 / test number): luck <= the sum of
                  0.05 / i (the gate's other checks only make it stricter), passed = latest result in NEWLAB_PASSED.
- ``roomtests``   방마다 규칙 바꾸기 시험 (trials kind 'test', labtests.gate p < 0.05 / the room's test count): the same
                  sum per room over the tests that could pass (a 'described' one cannot).
- ``synergy``     조합 시너지 (agents/synergy.py): the best of ~20,000 combinations against the same search on day-shuffled
                  P&L (rank_p): one comparison of a maximum, so luck = 1 in 20; the dashboard's own cached answer is used
                  when there is one.
- ``debate``      토론방 가설 (debate.db, agents/debate_grade.scoreboard): hits against the hits expected by chance.
- ``staff``       직원 예측 (agents3.db, agents/scorecard.scorecard): correct against half of the graded ones (a direction
                  call; the base rate is not stored, so 50 % is an assumption and the page says so).

past (5-year studies, files)
- ``library``     research/library/out{,_b}/summary.json (2,000 settings, 3-stage gauntlet)
- ``ds5y``        research/deepseek200/out/summary.json (342 settings; counts only, no money: D10 / D11)
- ``reel5m``      research/reel5m/out/summary.json
- ``entry``       paperbot/agents/research_prior.json (four pre-registered entry studies)
- ``indranges``   paperbot/dash/data/indranges.json (좋은 수치 찾기: BH over the cells) — '준비 중' until it exists
- ``combo5y``     paperbot/dash/data/combo5y.json (조합 5년, merged-signal rules: BH + shuffle null) — '준비 중' until then
                  (``PAPERBOT_LUCK_DATA`` names another folder for these two, e.g. a preview)

``verdict``: preparing (no file / no database yet), waiting (nothing tested yet or a small sample), before (the 30-day
verdict has not happened), none (0 passed), like_luck / some / more from ``tail`` = the chance that luck alone gives at
least the passes seen (< 0.01 more, < 0.10 some). Descriptive: 설명용, 판정 아님.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from functools import lru_cache
from typing import Any, Callable, Optional

import numpy as np

TTL_S = 600
WAIT_S = 3.0
LABEL = "설명용, 판정 아님"
ALPHA = 0.05
SMALL_GRADED = 10            # graded predictions before a hit count is read (agents/debate_grade.SMALL_GRADED)
MORE_TAIL, SOME_TAIL = 0.01, 0.10
SIMS = 2000                  # seeded simulation of the BH rule under 'no skill anywhere'
SEED = 20261006
STUDY_LUCK = 0.05            # a 3-stage gauntlet: stage 2 at p < 0.05 / k over the k carried over -> at most 0.05
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA = os.path.join(ROOT, "paperbot", "dash", "data")
SHORT = {"checkpoint": "30일 판정", "newlab": "새 매매법 시험실", "roomtests": "방별 규칙 시험", "synergy": "조합 시너지",
         "staff": "직원 예측", "debate": "토론방 가설", "library": "라이브러리 2,000개", "ds5y": "딥시크 342개",
         "reel5m": "5분 단타 40개", "entry": "진입 연구 4개", "indranges": "좋은 수치 찾기", "combo5y": "조합 5년"}
VERDICT_KO = {
    "preparing": "준비 중",
    "waiting": "아직 숫자가 적어 말할 수 없음",
    "before": "판정 전: 그날까지 합격도 불합격도 없음",
    "none": "통과 0개: 아직 진짜를 찾지 못함",
    "like_luck": "통과한 수가 운으로 나올 수와 비슷: 아직 진짜를 찾았다고 할 수 없음",
    "some": "운으로 나올 수보다 조금 많음: 아직 확실하지 않음",
    "more": "운으로 나올 수보다 확실히 많음",
}


def _r(x: Any, n: int = 3) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None


def _int(x: Any) -> Optional[int]:
    try:
        return None if x is None or isinstance(x, bool) else int(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the luck math (pure)
def harmonic_luck(n: int, alpha: float = ALPHA) -> float:
    """Expected passes by luck of n tests where test i passes at p < alpha / i (the lab's growing strictness)."""
    return float(sum(alpha / i for i in range(1, max(0, int(n)) + 1)))


def pb_tail(ps, k: int) -> float:
    """P(at least k of independent events with chances ``ps`` happen) (Poisson-binomial, exact)."""
    k = int(k)
    if k <= 0:
        return 1.0
    ps = [min(1.0, max(0.0, float(p))) for p in ps]
    if k > len(ps):
        return 0.0
    dist = np.zeros(k + 1)          # dist[j] = P(j so far), the last cell = P(k or more)
    dist[0] = 1.0
    for p in ps:
        top = dist[k]
        nxt = dist * (1 - p)
        nxt[1:] += dist[:-1] * p
        nxt[k] = top + dist[k - 1] * p   # 'k or more' stays there
        dist = nxt
    return float(min(1.0, max(0.0, dist[k])))


def poisson_tail(lam: float, k: int) -> float:
    """P(Poisson(lam) >= k)."""
    k = int(k)
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    term, cdf = math.exp(-lam), 0.0
    for i in range(k):
        cdf += term
        term *= lam / (i + 1)
    return float(min(1.0, max(0.0, 1.0 - cdf)))


def binom_tail(n: int, k: int, p: float) -> float:
    """P(Binomial(n, p) >= k)."""
    return pb_tail([p] * max(0, int(n)), k)


@lru_cache(maxsize=64)
def bh_null(m: int, alpha: float, sims: int = SIMS, seed: int = SEED) -> tuple:
    """How many of ``m`` tests Benjamini-Hochberg at ``alpha`` passes when nothing is real (independent uniform
    p-values), simulated ``sims`` times with a fixed seed: (mean, the passes per run as a tuple of counts)."""
    m = int(m)
    if m <= 0 or alpha <= 0:
        return 0.0, (0,) * sims
    rng = np.random.default_rng(seed + m)
    out = np.zeros(sims, dtype=np.int64)
    thr = np.arange(1, m + 1) * (alpha / m)
    step = max(1, min(sims, 4_000_000 // m))
    for a in range(0, sims, step):
        u = np.sort(rng.random((min(step, sims - a), m)), axis=1)
        ok = u <= thr
        anyok = ok.any(axis=1)
        last = m - np.argmax(ok[:, ::-1], axis=1)
        out[a:a + len(u)] = np.where(anyok, last, 0)
    return float(out.mean()), tuple(int(x) for x in out)


def bh_luck(families: list) -> tuple[float, Callable[[int], float]]:
    """[(m, alpha)] families, each with its own BH -> (expected passes in all, tail(k) = P(at least k passes))."""
    runs = None
    for m, a in families:
        if not m:
            continue
        _mean, counts = bh_null(int(m), float(a))
        arr = np.asarray(counts)
        runs = arr if runs is None else runs + arr
    if runs is None:
        return 0.0, lambda k: 1.0 if k <= 0 else 0.0
    mean = float(runs.mean())
    return mean, lambda k: float(np.mean(runs >= k)) if k > 0 else 1.0


def verdict(tested: Optional[int], passed: Optional[int], tail: Optional[float], *, small: bool = False,
            before: bool = False) -> str:
    """The row's plain verdict key (VERDICT_KO)."""
    if tested is None:
        return "preparing"
    if before:
        return "before"
    if small or not tested or passed is None:
        return "waiting"
    if passed <= 0:
        return "none"
    if tail is None:
        return "waiting"
    return "more" if tail < MORE_TAIL else "some" if tail < SOME_TAIL else "like_luck"


def row(rid: str, part: str, title: str, where: dict, *, tested=None, rule_ko="", luck=None, luck_ko="",
        passed=None, passed_ko="", tail=None, small=False, before=False, note="", extra=None) -> dict:
    v = verdict(tested, passed, tail, small=small, before=before)
    out = {"id": rid, "part": part, "title": title, "short": SHORT.get(rid, title), "where": where, "tested": tested, "rule_ko": rule_ko,
           "luck": _r(luck, 3), "luck_ko": luck_ko, "passed": passed, "passed_ko": passed_ko, "tail": _r(tail, 4),
           "small": bool(small), "verdict": v, "verdict_ko": VERDICT_KO[v], "note": note}
    if extra:
        out.update(extra)
    return out


def _load(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    from ..analysis import ro_connect
    return ro_connect(path)


def _close(c: Optional[sqlite3.Connection]) -> None:
    if c is not None:
        try:
            c.close()
        except sqlite3.Error:
            pass


# ---------------------------------------------------------------- now: the 30-day verdict
def checkpoint_row(paper_db: Optional[str], checkpoint_db: Optional[str]) -> dict:
    from ... import checkpoint as CK
    where = {"screen": "checkpoint"}
    title = "30일 판정 (계좌마다 동전 봇과 비교)"
    al = dict(CK.FAMILY_ALPHA)
    rule = (f"같은 봉 동전 봇 {CK.N_BOTS:,}개보다 잘했는지 본 뒤 묶음마다 보정(FDR " +
            " · ".join(f"{CK.FAMILY_KO[g]} {a * 100:g}%" for g, a in al.items()) + ")")
    v = CK.latest_verdict(checkpoint_db) if checkpoint_db else None
    if isinstance(v, dict) and v.get("families"):
        fams = [(f.get("tested") or 0, f.get("alpha") or al.get(f.get("group"), 0)) for f in v["families"]]
        luck, tail = bh_luck(fams)
        tested, passed = _int(v.get("tested")), _int(v.get("luck_passed"))
        return row("checkpoint", "now", title, where, tested=tested, rule_ko=rule, luck=luck,
                   luck_ko=f"실력이 하나도 없어도 평균 {luck:.2f}개 (보정 없이 봤다면 {float(v.get('lucky_if_uncorrected') or 0):.1f}개)",
                   passed=passed, passed_ko=f"운 시험 통과 {passed or 0:,}개 (그중 운일 수 있는 수 많아야 "
                                            f"{float(v.get('lucky_expected') or 0):.1f}개)",
                   tail=tail(passed or 0), extra={"date": v.get("date"), "ready": True,
                                                   "uncorrected": _r(v.get("lucky_if_uncorrected"), 2)})
    # before the verdict: the accounts it can judge (judged timeframes per family), the rule's luck numbers
    counts = {g: 0 for g in al}
    start = None
    c = _ro(paper_db)
    if c is None:
        return row("checkpoint", "now", title, where, rule_ko=rule, note="paper3.db 없음")
    try:
        try:
            start = CK.run_facts(c).get("start_ts")
        except (sqlite3.Error, ValueError):
            start = None
        for kind, tf, strat in c.execute("SELECT kind, timeframe, strategy FROM accounts"):
            g = CK.account_family(kind, strat)
            if g in counts and kind in ("strategy", "ds200", "reel") and tf in CK.JUDGED_BY_FAMILY.get(g, ()):
                counts[g] += 1
    except sqlite3.Error:
        return row("checkpoint", "now", title, where, rule_ko=rule, note="paper3.db를 읽지 못함")
    finally:
        _close(c)
    m = sum(counts.values())
    luck, tail = bh_luck([(counts[g], al[g]) for g in al])
    unc = sum(counts[g] * al[g] for g in al)
    plain = m * ALPHA
    first = CK.checkpoint_ts(int(start), 1) if start else None
    return row("checkpoint", "now", title, where, tested=m, rule_ko=rule, luck=luck,
               luck_ko=(f"실력이 하나도 없어도 평균 {luck:.2f}개 (1개라도 나올 확률 {tail(1) * 100:.0f}%). "
                        f"보정 없이 '동전 봇 95%보다 잘하면 합격'이었다면 약 {plain:.1f}개"),
               passed=None, passed_ko="판정 전", before=True,
               note=("판정 대상 계좌 수(15분·30분·1시간, 5분봉 매매법은 5분). 거래 30건이 안 된 계좌는 그날 보류라 실제 검정 수는 "
                     "더 적을 수 있습니다. 추가 계좌는 따로 셉니다"),
               extra={"ready": False, "families": [{"family": g, "name": CK.FAMILY_KO[g], "accounts": counts[g],
                                                     "alpha": al[g]} for g in al],
                      "uncorrected": _r(unc, 2), "plain": _r(plain, 2), "any_luck": _r(tail(1), 4),
                      "first_verdict_ts": first})


# ---------------------------------------------------------------- now: the agents' ledgers
def _trial_status(c: sqlite3.Connection, kind: str) -> list[tuple]:
    """[(trial id, room, latest status)] of one trial kind, oldest first."""
    return [tuple(r) for r in c.execute(
        "SELECT t.id, t.room_id, (SELECT r.status FROM trial_results r WHERE r.trial_id = t.id ORDER BY r.id DESC LIMIT 1) "
        "FROM trials t WHERE t.kind = ? ORDER BY t.id", (kind,))]


def ledger_rows(agents_db: Optional[str]) -> list[dict]:
    lab_w, room_w, staff_w = {"screen": "rooms", "arg": "team:lab"}, {"screen": "rooms"}, {"screen": "digest", "arg": "staff"}
    lab_t, room_t = "새 매매법 시험실 (5년 자료로 새 아이디어 시험)", "방마다 규칙 바꾸기 시험"
    staff_t = "직원 예측 성적표"
    lab_rule = "p < 0.05 ÷ 시험 번호 (시험이 늘수록 엄격) + 2기간·3기간·동전 비교"
    room_rule = "p < 0.05 ÷ 그 방의 시험 수 + 2기간도 같은 방향"
    staff_rule = "정해 둔 거래 수가 차면 코드가 맞음·틀림 채점"
    c = _ro(agents_db)
    if c is None:
        why = "에이전트 기록(agents3.db)이 아직 없습니다"
        return [row("newlab", "now", lab_t, lab_w, rule_ko=lab_rule, note=why),
                row("roomtests", "now", room_t, room_w, rule_ko=room_rule, note=why),
                row("staff", "now", staff_t, staff_w, rule_ko=staff_rule, note=why)]
    out = []
    try:
        from ...agents.rooms_db import NEWLAB_PASSED
        try:
            lab = _trial_status(c, "newlab")
        except sqlite3.Error:
            lab = None
        if lab is None:
            out.append(row("newlab", "now", lab_t, lab_w, rule_ko=lab_rule, note="시험 장부를 읽지 못함"))
        else:
            n = len(lab)
            passed = sum(1 for _i, _r0, s in lab if s in NEWLAB_PASSED)
            ps = [ALPHA / i for i in range(1, n + 1)]
            luck = sum(ps)
            out.append(row("newlab", "now", lab_t, lab_w, tested=n, rule_ko=lab_rule, luck=luck,
                           luck_ko=f"많아야 {luck:.2f}개 (1번째 시험 5%, 2번째 2.5%, … 를 더한 값)" if n else "시험이 생기면 계산",
                           passed=passed, passed_ko=f"관문 통과 {passed:,}개", tail=pb_tail(ps, passed),
                           note="" if n else "아직 새 매매법 시험이 없습니다"))
        try:
            tests = _trial_status(c, "test")
        except sqlite3.Error:
            tests = None
        if tests is None:
            out.append(row("roomtests", "now", room_t, room_w, rule_ko=room_rule, note="시험 장부를 읽지 못함"))
        else:
            seen: dict = {}
            ps, passed, gradable = [], 0, 0
            for _tid, room, status in tests:
                seen[room] = seen.get(room, 0) + 1
                if status == "described":
                    continue
                gradable += 1
                ps.append(ALPHA / seen[room])
                passed += status == "passed"
            luck = sum(ps)
            out.append(row("roomtests", "now", room_t, room_w, tested=len(tests), rule_ko=room_rule, luck=luck,
                           luck_ko=f"많아야 {luck:.2f}개 (방마다 5%, 2.5%, … 를 더한 값)" if tests else "시험이 생기면 계산",
                           passed=passed, passed_ko=f"통과 {passed:,}개 (설명용 시험 {len(tests) - gradable:,}개는 통과가 없음)",
                           tail=pb_tail(ps, passed), note="" if tests else "아직 방에서 시험한 것이 없습니다"))
        try:
            from ...agents.scorecard import scorecard
            tot = (scorecard(c) or {}).get("total") or {}
        except (sqlite3.Error, ImportError):
            tot = None
        if tot is None:
            out.append(row("staff", "now", staff_t, staff_w, rule_ko=staff_rule, note="성적표를 읽지 못함"))
        else:
            g, k = int(tot.get("graded") or 0), int(tot.get("correct") or 0)
            out.append(row("staff", "now", staff_t, staff_w, tested=g, rule_ko=staff_rule, luck=g * 0.5,
                           luck_ko=f"반반으로 찍어도 약 {g * 0.5:.1f}개 (위·아래 맞히기라 50%로 가정)" if g else "채점이 생기면 계산",
                           passed=k, passed_ko=f"맞힘 {k:,}개 / 채점 {g:,}개", tail=binom_tail(g, k, 0.5),
                           small=g < SMALL_GRADED, note=f"채점 {SMALL_GRADED}개가 되기 전에는 결론을 내지 않습니다" if g < SMALL_GRADED else "",
                           extra={"need": SMALL_GRADED, "waiting_n": int(tot.get("waiting") or 0)}))
    finally:
        _close(c)
    return out


def debate_row(debate_db: Optional[str]) -> dict:
    title, where = "토론방 가설 (맞힌 수)", {"screen": "debate"}
    rule = "주장한 일이 기한 안에 정말 일어나면 맞힘 (코드 채점, 너무 쉬운 주장은 빼고)"
    c = _ro(debate_db)
    if c is None:
        return row("debate", "now", title, where, rule_ko=rule, note="토론방이 아직 돌지 않았습니다")
    try:
        from ...agents.debate_grade import scoreboard
        sb = scoreboard(c)
    except (sqlite3.Error, ImportError):
        return row("debate", "now", title, where, rule_ko=rule, note="토론방 기록을 읽지 못함")
    finally:
        _close(c)
    g, k = int(sb.get("graded") or 0), int(sb.get("hit") or 0)
    exp = float(sb.get("expected_hits") or 0.0)
    p0 = exp / g if g else 0.5
    return row("debate", "now", title, where, tested=g, rule_ko=rule, luck=exp if g else None,
               luck_ko=f"그냥 일어날 확률로만 맞혀도 약 {exp:.1f}개" if g else "채점이 생기면 계산",
               passed=k, passed_ko=f"맞힘 {k:,}개 / 채점 {g:,}개", tail=binom_tail(g, k, p0) if g else None,
               small=g < SMALL_GRADED, note=f"채점 {SMALL_GRADED}개가 되기 전에는 결론을 내지 않습니다" if g < SMALL_GRADED else "",
               extra={"need": SMALL_GRADED})


def synergy_row(syn: Optional[dict]) -> dict:
    """조합 시너지 from the analysis view's answer (agents/synergy.py dash_view + its day-0 waiting)."""
    from ...agents import synergy as SY
    title, where = "조합 시너지 (매매법 2~5개 묶음 고르기)", {"screen": "analysis", "arg": "synergy"}
    rule = "가장 좋은 묶음이 날짜를 섞은 자료로 같은 탐색을 한 최고 점수 20번 중 19번보다 높으면"
    if not isinstance(syn, dict) or syn.get("error"):
        return row("synergy", "now", title, where, rule_ko=rule,
                   note=str((syn or {}).get("error") or "아직 계산 전") if isinstance(syn, dict) else "아직 계산 전")
    n = int(syn.get("units") or 0)
    searched = 0
    for k in range(SY.KMIN, min(SY.KMAX, n) + 1):
        full = math.comb(n, k)
        searched += full if (full <= SY.EXHAUSTIVE or k == SY.KMIN) else min(full, SY.BEAM * (n - k + 1))
    sd = syn.get("shuffled_days") or {}
    waiting = bool(syn.get("waiting") or syn.get("small")) or not sd
    rank_p = _r(sd.get("rank_p"), 4)
    passed = None if waiting or rank_p is None else int(rank_p <= ALPHA)
    beats = _r(sd.get("real_beats_share"), 3)
    return row("synergy", "now", title, where, tested=searched if n else 0, rule_ko=rule, luck=ALPHA,
               luck_ko="20번에 1번 (5%): 묶음이 아무 의미 없어도 이만큼은 1등이 섞은 자료보다 높게 나옴",
               passed=passed, passed_ko=("기다리는 중" if passed is None else
                                         f"섞은 자료 최고 점수 {int(sd.get('runs') or 0)}번 중 {beats * 100:.0f}%보다 높음"
                                         if beats is not None else "—"),
               tail=rank_p, small=waiting,
               note=f"묶음 후보 약 {searched:,}개 중 가장 좋은 것을 고르므로, 섞은 자료로 같은 고르기를 해서 견줍니다"
               if n else "", extra={"days": syn.get("days"), "min_trades": syn.get("min_trades")})


# ---------------------------------------------------------------- past: the 5-year studies
def _gauntlet(rid: str, title: str, paths: list, where: dict, what: str, counts_only: bool = False) -> dict:
    docs = [_load(p) for p in paths]
    docs = [d for d in docs if d]
    rule = "3단계 관문: 1기간 고르기 → 2기간 확인(p < 0.05 ÷ 넘어온 수) → 3기간 최종"
    if not docs:
        return row(rid, "past", title, where, rule_ko=rule, note="결과 파일이 아직 없습니다")
    n = sum(int(d.get("configs") or 0) for d in docs)
    s1 = sum(int(d.get("stage1") or 0) for d in docs)
    s2 = sum(int(d.get("stage2") or 0) for d in docs)
    s3 = sum(int(d.get("stage3") or 0) for d in docs)
    luck = STUDY_LUCK * len(docs)               # one top-30 carry-over per run
    return row(rid, "past", title, where, tested=n, rule_ko=rule, luck=luck,
               luck_ko=f"많아야 {luck:.2f}개 (2단계 보정 덕분에 1개 미만)",
               passed=s3, passed_ko=f"3단계까지 통과 {s3:,}개 (1단계 {s1:,} → 2단계 {s2:,})",
               tail=poisson_tail(luck, s3), note=what,
               extra={"stages": [s1, s2, s3], **({"counts_only": True} if counts_only else {})})


def entry_row(path: Optional[str] = None) -> dict:
    from ...agents.packets3 import RESEARCH_PRIOR
    title, where = "지난 진입 연구 4개 (지지·저항, 진입 수치, 숫자 바꾸기, 추세선)", {"screen": "strategies"}
    d = _load(path or RESEARCH_PRIOR)
    rule = "사전 등록한 기준으로 세 기간 모두 통과"
    if not d or not isinstance(d.get("totals"), dict):
        return row("entry", "past", title, where, rule_ko=rule, note="연구 요약 파일이 없습니다")
    n = sum(int(v or 0) for v in d["totals"].values())
    sr = 0
    for s in (d.get("strategies") or {}).values():
        p = ((s or {}).get("support_resistance") or {}).get("passed_all3")
        sr += len(p) if isinstance(p, list) else int(p or 0)
    return row("entry", "past", title, where, tested=n, rule_ko=rule, luck=None,
               luck_ko="연구마다 보정 방법이 달라 한 숫자로 적지 않음",
               passed=0, passed_ko=f"진짜로 남은 것 0개 (지지·저항 후보 {sr}개는 무작위 진입에서도 같아 시장 전체의 성질)",
               tail=None, note=str(d.get("conclusion_ko") or "")[:400])


def indranges_row(path: str) -> dict:
    title, where = "좋은 수치 찾기 (지표 구간마다 5년 성적)", {"screen": "analysis"}
    d = _load(path)
    rules = (d or {}).get("rules") if isinstance(d, dict) else None
    if not isinstance(rules, dict) or _int(rules.get("tests")) is None:
        return row("indranges", "past", title, where, rule_ko="칸마다 차이 시험 + 보정(FDR) + 세 구간 같은 방향",
                   note="결과 파일이 아직 없습니다")
    m, k = int(rules["tests"]), int(rules.get("passed") or 0)
    fdr = float(rules.get("fdr") or ALPHA)
    luck, tail = bh_luck([(m, fdr)])
    better, worse = _int(rules.get("better")), _int(rules.get("worse"))
    side = f" (더 좋음 {better:,} · 더 나쁨 {worse:,})" if better is not None and worse is not None else ""
    return row("indranges", "past", title, where, tested=m,
               rule_ko=f"칸마다 차이 시험 + 보정(FDR {fdr * 100:g}%) + 세 구간 같은 방향 + 최소 크기", luck=luck,
               luck_ko=f"실제 차이가 없다면 평균 {luck:.2f}개 (보정 없이 5%였다면 약 {m * ALPHA:.0f}개)",
               passed=k, passed_ko=f"차이가 확인된 칸 {k:,}개{side} · 그중 운일 수 있는 수 많아야 {fdr * k:.0f}개",
               tail=tail(k), note="차이가 진짜라는 뜻이지, 그 구간에서 돈을 번다는 뜻은 아닙니다 (거래당 손익은 따로 봐야 함)")


def combo5y_row(path: str) -> dict:
    title, where = "조합 5년 (매매법 신호를 합친 규칙)", {"screen": "analysis"}
    d = _load(path)
    mg = (d or {}).get("merged") if isinstance(d, dict) else None
    if not isinstance(mg, dict) or _int(mg.get("tested")) is None:
        return row("combo5y", "past", title, where, rule_ko="보정(FDR) 통과 + 신호를 섞은 자료보다 좋음",
                   note="결과 파일이 아직 없습니다")
    m = int(mg["tested"])
    fdr = float(mg.get("fdr") or ALPHA)
    bh_pass, both = int(mg.get("bh_pass") or 0), int(mg.get("both_pass") or 0)
    luck, tail = bh_luck([(m, fdr)])
    trials = _int(mg.get("trials"))
    return row("combo5y", "past", title, where, tested=m,
               rule_ko=f"보정(FDR {fdr * 100:g}%) 통과 + 신호를 섞은 자료보다 좋음", luck=luck,
               luck_ko=f"실제 효과가 없다면 평균 {luck:.2f}개 (보정 없이 5%였다면 약 {m * ALPHA:.0f}개)",
               passed=both, passed_ko=f"둘 다 통과 {both:,}개 (보정만 통과 {bh_pass:,}개)", tail=tail(both),
               note=(f"만든 규칙 {trials:,}개 중 거래가 충분한 {m:,}개를 시험" if trials else ""))


# ---------------------------------------------------------------- the whole answer
def example() -> dict:
    """The coin example of the page (exact numbers, computed): 100 people flip a coin 20 times each."""
    people, flips, hit = 100, 20, 15
    p = binom_tail(flips, hit, 0.5)
    return {"people": people, "flips": flips, "hit": hit, "share": _r(p, 4), "expected": _r(people * p, 2)}


def luck_view(paper_db: Optional[str], *, agents_db: Optional[str] = None, checkpoint_db: Optional[str] = None,
              debate_db: Optional[str] = None, syn: Optional[dict] = None, data_dir: str = DATA,
              research: str = os.path.join(ROOT, "research"), now_ms: Optional[int] = None) -> dict:
    t0 = time.perf_counter()
    rows = [checkpoint_row(paper_db, checkpoint_db)]
    rows += ledger_rows(agents_db)
    rows.insert(3, synergy_row(syn))
    rows.append(debate_row(debate_db))
    rows += [
        _gauntlet("library", "매매법 라이브러리 2,000개 (5년)", [os.path.join(research, "library", "out", "summary.json"),
                                                         os.path.join(research, "library", "out_b", "summary.json")],
                  {"screen": "strategies"}, "RSI·MACD·이평·돈치안·볼린저·캔들 등 이미 알려진 규칙을 모아 시험"),
        _gauntlet("ds5y", "딥시크 정의 342개 (5년)", [os.path.join(research, "deepseek200", "out", "summary.json")],
                  {"screen": "board", "query": {"g": "ds200"}}, "딥시크가 낸 정의 171개 × 청산 2가지 (거래 수·통과 수만)",
                  counts_only=True),
        _gauntlet("reel5m", "5분 단타 변형 40개 (5년)", [os.path.join(research, "reel5m", "out", "summary.json")],
                  {"screen": "strategies", "arg": "REEL_H1"}, "릴스 5분 단타와 그 변형"),
        entry_row(),
        indranges_row(os.path.join(data_dir, "indranges.json")),
        combo5y_row(os.path.join(data_dir, "combo5y.json")),
    ]
    have = [r for r in rows if r["tested"] is not None]
    return {"label": LABEL, "rows": rows, "example": example(), "verdict_ko": VERDICT_KO,
            "summary": {"places": len(rows), "with_data": len(have),
                        "tested": sum(int(r["tested"] or 0) for r in have),
                        "passed": sum(int(r["passed"] or 0) for r in have if r["passed"] is not None),
                        "more": [r["id"] for r in rows if r["verdict"] == "more"],
                        "some": [r["id"] for r in rows if r["verdict"] == "some"]},
            "now": now_ms if now_ms is not None else int(time.time() * 1000),
            "runtime_s": round(time.perf_counter() - t0, 3)}


def register(app, ctx) -> dict:
    from ..analysis import Heavy, synergy_view
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):
        heavy = Heavy()
    db = getattr(ctx, "db", None)
    side = os.path.dirname(os.path.abspath(db)) if db else ""
    cp = getattr(ctx, "checkpoint_db", None) or (os.path.join(side, "checkpoint.db") if db else None)
    deb = getattr(ctx, "debate_db", None) or (os.path.join(side, "debate", "debate.db") if db else None)

    def compute() -> dict:
        now = int(time.time() * 1000)
        syn = heavy.peek("synergy")                   # the 조합 시너지 tab's own cached answer, when it has one
        if not isinstance(syn, dict) or syn.get("pending") or syn.get("error"):
            syn = synergy_view(db, now) if db else None
        return luck_view(db, agents_db=getattr(ctx, "agents_db", None), checkpoint_db=cp, debate_db=deb, syn=syn,
                         data_dir=os.environ.get("PAPERBOT_LUCK_DATA") or DATA, now_ms=now)

    @app.get("/api/v4/luck")
    def get_luck():
        """운 vs 실력: every place that tests many things, its luck numbers and a plain verdict (background, cached)."""
        from ..app import json_finite
        return json_finite(heavy.get("luck", TTL_S, compute, wait_s=WAIT_S))

    return {"routes": ["/api/v4/luck"]}
