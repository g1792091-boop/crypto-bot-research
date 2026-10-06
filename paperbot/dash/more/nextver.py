"""다음 버전 (owners' round 2, 10/06; #/nextver, reached from 졸업 길 and 홈's goal line): three read-only views for deciding,
after the 30-day verdict, what a next version (v5) could carry, plus the goal line of 홈.

    GET /api/v4/nextver   {candidates, claims, cantdo}   (cached ``TTL_S``; every database read-only)
    GET /api/v4/goal      the 목표 진척도 line (agents/goalline.py, the same text the evening Telegram can carry; its
                          verdict part in the verdict-day clock's words here, ``clock_words``: one D-day on every screen)

- 다음 버전 후보 장부 (``candidates``): every result that could become a change, each with an evidence grade written by
  code (``GRADES``): the new-strategy lab's passes (A: 5-year, pre-registered gate corrected for every test, later
  periods and the coin flips), the strategy rooms' passing what-if tests (B: corrected only for the room's own tests),
  disputes the attacker won (C: the lab claim rule at p < 0.05 without a correction; D: a forward check of 20-60 trades),
  and the 5-year studies (장세 스위치 regime5y, 조합 5년 combo5y when its file exists: their survivors; 손실 크기 규칙
  size5y is descriptive, so it is listed without a grade). Beside each group: what luck alone gives there (the
  luck-calc's own rows, dash/more/luck.py).
- 주장별 성적표 (``claims``): the same claim tried on many strategies (skip '추세 반대 진입', stop 2.5 ATR, first lock
  20 %): over the rooms' 5-year tests how often the pre-registered lab claim rule (agents/disputes.lab_verdict) held and
  how many passed the copy gate, plus the disputes about it (5-year and forward), next to the base rate over every claim
  and, for forward checks, the coin flip's 50 %.
- 연구실이 못 하는 아이디어 (``cantdo``): ideas no test could express: the owners' requests translated as 'none', the
  debate's ideas the judge could not put into the grammar or that code found outside it, the queue's 'bad_spec' rows;
  with the code's reason and a count per reason code (for deciding grammar extensions after the verdict).

Nothing here proposes, approves or changes anything; the observation period (no proposals before its end) and the
verdict rules are untouched. Model words (an idea, a claim) are shown only as quotes; every reason is code text.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

TTL_S = 90
GOAL_TTL_S = 60
LABEL = "보기만: 아무것도 제안·승인하지 않음"
GRADES = {
    "A": ("강함", "5년 자료 · 미리 정한 관문 · 모든 시험 수로 보정 · 뒤 기간·동전 비교까지 통과"),
    "B": ("보통", "5년 자료 · 그 방 시험 수로만 보정 · 뒤 기간도 같은 방향 (36개 방을 합친 수로는 보정 안 함)"),
    "C": ("약함", "5년 자료 · 시험 수 보정 없이 두 기간 p<0.05 (다툼 채점 규칙)"),
    "D": ("아주 약함", "앞으로 20~60건 확인 · 동전 던지기에 가까움"),
    "-": ("등급 없음", "설명용 연구 · 합격·불합격 없음"),
}
NOTE_KO = ("이 장부는 보기만 합니다. 다음 버전에 무엇을 넣을지는 30일 판정 뒤 두 분이 정하고, 넣을 것은 미리 등록한 뒤 새 자료로 "
           "다시 확인합니다. 관찰 기간에는 아무것도 제안하지 않습니다. 시험을 많이 하면 운으로 통과하는 것도 나오므로 묶음마다 "
           "운으로 나올 수와 함께 봅니다.")
CLAIM_NOTE_KO = ("같은 주장(예: '추세 반대 진입'은 건너뛰는 게 낫다)을 여러 매매법에서 시험한 결과입니다. '맞음'은 미리 정한 다툼 채점 "
                 "규칙(1·2기간 모두 나아지고 p<0.05)이고, 복제 관문은 그 방 시험 수로 보정한 더 엄격한 기준입니다. 기준 비율은 모든 "
                 "주장을 합친 비율이라, 그보다 크게 높아야 그 주장이 특별하다고 볼 수 있습니다. 앞으로 N건 확인은 동전 50%와 봅니다.")
CANTDO_NOTE_KO = ("문법(새 매매법 진입 40개·필터 5종, 36개 고쳐 보기 3가지)으로 옮길 수 없어 시험하지 못한 아이디어입니다. 판정 뒤 문법을 "
                  "넓힐지(newlab-v2, 미리 등록) 정할 때 씁니다. 지금은 이 목록 때문에 바뀌는 것이 없습니다.")
SMALL = 10
MAX_ROWS = 60


def _ro(path: Optional[str]):
    from ..analysis import ro_connect
    return ro_connect(path)


def _close(c) -> None:
    if c is not None:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


def clock_words(g: dict, paper_ro, paper_db: Optional[str], checkpoint_db: Optional[str], jobs=None) -> dict:
    """The goal line's verdict part in the verdict-day clock's words (dash/more/verdictday.py, fix-verdict change 13: one
    D-day wording on every screen, the sentence of 홈's head card, 판정 and 30일 길): '판정까지 23일 (11/04 09:00)',
    '2번째 판정까지 …', on a verdict day '30일 판정 날 · 동전 봇 비교 계산 중' until its result is stored (fix 1: never
    '다음 판정 D-29' while that verdict is still being computed), '판정 끝 (180일)'. goalline's own words stay when the run
    start is not known (paper3.db unreadable: '…읽지 못해 모름'; no account yet). The evening Telegram keeps goalline's
    text (agents side)."""
    from .story import run_start
    from .verdictday import clock, day_state_reader, read_ledger
    parts = list(g.get("parts") or [])
    if paper_ro is None or (g.get("verdict") or {}).get("error") or len(parts) != 3:
        return g
    start = run_start(paper_ro)
    if start is None:
        return g
    c = clock(start, int(g.get("now") or time.time() * 1000), read_ledger(checkpoint_db), day_state_reader(paper_db), jobs)
    if not c.get("ready"):
        return g
    parts[2] = c["line_ko"] if c.get("due") else c["rest_ko"]
    return {**g, "parts": parts, "text_ko": " · ".join(parts),
            "verdict_clock": {k: c.get(k) for k in ("k", "day", "ts", "due", "state", "line_ko")}}


def _load(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _loads(s: Any) -> Any:
    if s is None or isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def grade(g: str) -> dict:
    ko, why = GRADES[g]
    return {"grade": g, "grade_ko": ko, "grade_why": why}


# a pass / fail study whose pre-registered gate nothing passed: no grade, but never called 'descriptive' (it had a gate)
NO_SURVIVOR = {"grade": "-", "grade_ko": "후보 없음", "grade_why": "미리 정한 관문을 끝까지 넘은 칸이 없음(합격·불합격이 있는 연구)"}


def _test_ko(spec: dict) -> str:
    from ...agents.disputes import _test_ko as dko
    try:
        return dko(spec)
    except Exception:  # noqa: BLE001
        return str(spec.get("template") or "")


def _strategy_ko(s: Optional[str]) -> str:
    from ...agents.roster3 import STRATEGY_KO
    return STRATEGY_KO.get(s or "", s or "")


# ---------------------------------------------------------------- 1. 다음 버전 후보 장부
def lab_candidates(a) -> list[dict]:
    """The new-strategy passes (latest result passed / proposed / lapsed) and the rooms' passing what-if tests."""
    from ...agents import rooms_db as R
    if a is None:
        return []
    out = []
    for t in R.trial_history(a, kinds=("newlab",), limit=2000):
        res = t.get("result") or {}
        st = res.get("status")
        if st not in R.NEWLAB_PASSED:
            continue
        body = res.get("result") if isinstance(res.get("result"), dict) else {}
        lapsed = st == "lapsed"
        out.append({"kind": "newlab", "kind_ko": "새 매매법 5년 시험", "id": t["id"], "ts": t["ts"],
                    "title": body.get("description_ko") or json.dumps(t.get("spec"), ensure_ascii=False)[:160],
                    "sub": (f"새 매매법 시험 {body.get('test_number')}번째" if body.get("test_number") else "새 매매법 시험")
                    + {"passed": " · 관문 통과(제안 기다림)", "proposed": " · 두 분께 제안됨",
                       "lapsed": " · 통과했지만 지금 시험 수로 다시 판정하면 미달"}[st],
                    **grade("C" if lapsed else "A"), "go": {"name": "rooms", "arg": R.LAB_ROOM}})
    for t in R.trial_history(a, kinds=("test",), limit=2000):
        res = t.get("result") or {}
        if res.get("status") != "passed":
            continue
        body = res.get("result") if isinstance(res.get("result"), dict) else {}
        spec = t.get("spec") if isinstance(t.get("spec"), dict) else {}
        n = body.get("n_trials")
        out.append({"kind": "roomtest", "kind_ko": "36개 고쳐 보기 5년 시험", "id": t["id"], "ts": t["ts"],
                    "title": f"{_strategy_ko(t.get('strategy'))} · {_test_ko(spec)}",
                    "sub": f"시험 #{t['id']}" + (f" · 그 방 {n}번째 시험" if n else "") + " · 복제 관문 통과(그때 시험 수 기준)",
                    **grade("B"), "go": {"name": "rooms", "arg": R.strategy_room_id(t.get("strategy") or "")}})
    return out


def dispute_candidates(a) -> tuple[list[dict], dict]:
    """Settled disputes: the attacker won (the change is right) -> a candidate (C lab, D forward); the advocate won ->
    counted only ('바꾸지 않음'). Returns (rows, counts)."""
    from ...agents import disputes as DS
    rows = DS.list_rows(a, limit=500) if a is not None else []
    counts = {"settled": 0, "attacker": 0, "advocate": 0}
    out = []
    for d in rows:
        if d["status"] != "settled":
            continue
        counts["settled"] += 1
        if d.get("winner") != "a":
            counts["advocate"] += 1
            continue
        counts["attacker"] += 1
        out.append({"kind": "dispute", "kind_ko": f"다툼 · {d['kind_ko']}", "id": d["id"], "ts": d.get("settled_ts") or d["ts"],
                    "title": f"{d['strategy_ko']} · {d['settle_ko']}", "quote": d.get("claim_ko") or "",
                    "sub": f"공격 {d['side_a_name']} 맞음" + (f" · {d['outcome']}" if d.get("outcome") else ""),
                    **grade("C" if d["kind"] == "lab" else "D"),
                    "go": {"name": "rooms", "arg": f"strat:{d['strategy']}"}})
    return out, counts


def study_rows(data_dir: str) -> list[dict]:
    """The 5-year studies as committed: 장세 스위치 (regime5y), 조합 5년 (combo5y, when its file exists), 손실 크기 규칙
    (size5y, descriptive). Survivors are candidates; 0 survivors says so; a missing file says 준비 중."""
    out = []
    rg = _load(os.path.join(data_dir, "regime5y.json"))
    head = (rg or {}).get("head") if isinstance(rg, dict) else None
    if isinstance(head, dict) and head.get("tested") is not None:
        surv, tested = int(head.get("survivors") or 0), int(head.get("tested") or 0)
        out.append({"kind": "study", "kind_ko": "5년 연구 · 장세 스위치", "id": "regime5y", "ts": rg.get("generated_at"),
                    "title": f"맞는 장에서만 켜기: {tested:,}칸 시험 · 끝까지 남은 칸 {surv:,}개",
                    "sub": (f"보정(FDR)만 통과 {int(head.get('bh_pass') or 0):,}개 · 확인 기간 A·B 둘 다 같은 방향이어야 남음"),
                    "candidate": surv > 0, **(grade("A") if surv else NO_SURVIVOR),
                    "go": {"name": "analysis", "arg": "regime"}})
    else:
        out.append({"kind": "study", "kind_ko": "5년 연구 · 장세 스위치", "id": "regime5y", "title": "장세 스위치",
                    "sub": "결과 파일이 아직 없습니다(준비 중)", "candidate": False, **grade("-"), "preparing": True})
    cb = _load(os.path.join(data_dir, "combo5y.json"))
    mg = (cb or {}).get("merged") if isinstance(cb, dict) else None
    if isinstance(mg, dict) and mg.get("tested") is not None:
        both = int(mg.get("both_pass") or 0)
        out.append({"kind": "study", "kind_ko": "5년 연구 · 조합", "id": "combo5y", "ts": cb.get("generated_at"),
                    "title": f"매매법 신호를 합친 규칙: {int(mg['tested']):,}개 시험 · 둘 다 통과 {both:,}개",
                    "sub": f"보정(FDR)만 통과 {int(mg.get('bh_pass') or 0):,}개 · 신호를 섞은 자료보다도 좋아야 남음",
                    "candidate": both > 0, **(grade("B") if both else NO_SURVIVOR)})
    sz = _load(os.path.join(data_dir, "size5y.json"))
    pooled = ((sz or {}).get("pooled") or {}).get("all") if isinstance(sz, dict) else None
    if isinstance(pooled, dict):
        names = {r.get("key"): r.get("short") or r.get("ko") for r in sz.get("rules") or [] if isinstance(r, dict)}
        parts = []
        for key, cell in pooled.items():
            full = (cell or {}).get("full") if isinstance(cell, dict) else None
            if isinstance(full, dict) and full.get("n"):
                parts.append(f"{names.get(key, key)} {int(full.get('up') or 0):,}/{int(full['n']):,}칸")
        out.append({"kind": "study", "kind_ko": "5년 연구 · 손실 크기 규칙", "id": "size5y", "ts": sz.get("generated_at"),
                    "title": "같은 진입·청산에 크기 규칙만 바꿔 본 5년 (설명용, 판정 아님)",
                    "sub": "5년 뒤 $5,000보다 늘어난 칸: " + " · ".join(parts) if parts else "칸별 숫자 없음",
                    "candidate": False, **grade("-"), "go": {"name": "analysis", "arg": "size"}})
    return out


def candidates_view(agents_db: Optional[str], data_dir: str) -> dict:
    from .luck import ledger_rows_safe
    a = _ro(agents_db)
    try:
        lab = lab_candidates(a)
        disp, dcounts = dispute_candidates(a)
    finally:
        _close(a)
    studies = study_rows(data_dir)
    luck = {r["id"]: {k: r.get(k) for k in ("tested", "luck", "passed", "luck_ko", "passed_ko", "verdict_ko", "tail")}
            for r in ledger_rows_safe(agents_db) if r["id"] in ("newlab", "roomtests")}
    rows = lab + disp + [s for s in studies if s.get("candidate")]
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "-": 4}
    rows.sort(key=lambda r: (order[r["grade"]], -(r.get("ts") or 0)))
    return {"rows": rows[:MAX_ROWS], "total": len(rows), "studies": studies, "disputes": dcounts, "luck": luck,
            "grades": {k: {"ko": v[0], "why": v[1]} for k, v in GRADES.items()},
            "by_grade": {g: sum(1 for r in rows if r["grade"] == g) for g in GRADES}, "note_ko": NOTE_KO}


# ---------------------------------------------------------------- 2. 주장별 성적표
def claim_key(spec: dict) -> Optional[tuple]:
    """(template, value) of a what-if test, the claim it tries; None for a descriptive or odd spec."""
    from ...agents.disputes import LAB_PARAM
    t = spec.get("template") if isinstance(spec, dict) else None
    if t not in LAB_PARAM or spec.get(LAB_PARAM[t]) is None:
        return None
    return t, spec[LAB_PARAM[t]]


def claim_ko(key: tuple) -> str:
    t, v = key
    if t == "skip_tag":
        return f"'{v}' 붙은 진입은 건너뛰는 게 낫다"
    if t == "stop_atr":
        return f"손절을 {float(v):g} ATR로 바꾸면 낫다"
    if t == "lock_start":
        return f"첫 익절 잠금을 {float(v) * 100:.0f}%로 바꾸면 낫다"
    return f"{t} {v}"


def claims_view(agents_db: Optional[str]) -> dict:
    from ...agents import disputes as DS
    from ...agents import rooms_db as R
    a = _ro(agents_db)
    try:
        tests = R.trial_history(a, kinds=("test",), limit=2000) if a is not None else []
        disputes = DS._rows(a, "status = 'settled'", (), 100_000, "id") if a is not None else []   # with the spec
    finally:
        _close(a)
    by: dict = {}

    def row(key: tuple) -> dict:
        return by.setdefault(key, {"key": f"{key[0]}:{key[1]}", "template": key[0], "value": key[1],
                                   "claim_ko": claim_ko(key), "strategies": set(), "tests": 0, "held": 0, "gate": 0,
                                   "lab_disputes": 0, "lab_attacker": 0, "fwd_disputes": 0, "fwd_attacker": 0})
    ran = held_all = 0
    for t in tests:
        res = t.get("result") or {}
        if res.get("status") not in ("passed", "failed"):
            continue                     # a descriptive test or one that could not run claims nothing
        key = claim_key(t.get("spec") if isinstance(t.get("spec"), dict) else {})
        if key is None:
            continue
        v = DS.lab_verdict(t)
        r = row(key)
        r["strategies"].add(t.get("strategy"))
        r["tests"] += 1
        ran += 1
        if v.get("status") == "settled" and v.get("winner") == "a":
            r["held"] += 1
            held_all += 1
        r["gate"] += res.get("status") == "passed"
    fwd = fwd_a = 0
    for d in disputes:
        if d.get("status") != "settled" or d.get("winner") not in ("a", "b"):
            continue
        sp = d.get("spec") if isinstance(d.get("spec"), dict) else {}
        if d["kind"] == "lab":
            key = claim_key(sp.get("test") or {})
            if key is None:
                continue
            r = row(key)
            r["lab_disputes"] += 1
            r["lab_attacker"] += d["winner"] == "a"
        else:
            if sp.get("check") != "tag_gap" or not sp.get("tag"):
                continue                 # a vs_flip check is about a whole strategy, not a claim type
            r = row(("skip_tag", sp["tag"]))
            r["fwd_disputes"] += 1
            r["fwd_attacker"] += d["winner"] == "a"
            fwd += 1
            fwd_a += d["winner"] == "a"
        r["strategies"].add(d.get("strategy"))
    out = []
    base = held_all / ran if ran else None
    for r in by.values():
        r["strategies"] = len({s for s in r["strategies"] if s})
        r["held_share"] = r["held"] / r["tests"] if r["tests"] else None
        r["small"] = r["tests"] < SMALL
        out.append(r)
    out.sort(key=lambda r: (-r["tests"], -r["fwd_disputes"], r["key"]))
    return {"rows": out, "base": {"tests": ran, "held": held_all, "held_share": base, "small": ran < SMALL,
                                  "fwd_settled": fwd, "fwd_attacker": fwd_a,
                                  "fwd_share": fwd_a / fwd if fwd else None, "coin_flip": 0.5},
            "min": SMALL, "note_ko": CLAIM_NOTE_KO}


# ---------------------------------------------------------------- 3. 연구실이 못 하는 아이디어
def cantdo_view(agents_db: Optional[str], debate_db: Optional[str], limit: int = 100) -> dict:
    from ...agents import labintake as LI
    items: list[dict] = []
    codes: dict = {}
    a = _ro(agents_db)
    try:
        cards = LI.view(a, None, 200) if a is not None else []
        started = LI.exists(a)           # the queue's tables: made only once a source (owners, debate, disputes) is on
    finally:
        _close(a)
    for c in cards:
        m = c.get("meta") or {}
        if c["source"] == "owner":
            fid = m.get("fidelity")
            for code in m.get("reason_codes") or []:
                if fid in ("none", "approx") and code in LI.OWNER_REASON_KO:
                    codes.setdefault(code, {"code": code, "ko": LI.OWNER_REASON_KO[code], "none": 0, "approx": 0})
                    codes[code][fid] += 1
            if not (fid == "none" or c["status"] == "bad_spec"):
                continue
        elif c["status"] != "bad_spec":
            continue                     # a 5-minute or non-36 refusal is a rule of this run, not the grammar
        items.append({"source": c["source"], "source_ko": LI.SOURCE_KO.get(c["source"], c["source"]), "ts": c["ts"],
                      "quote": c.get("idea_ko") or "", "why_ko": str((c.get("detail") or {}).get("why") or "")[:300],
                      "reasons_ko": list(m.get("reasons_ko") or []), "status_ko": c["status_ko"],
                      "label": LI.owner_label(c) if c["source"] == "owner" else f"#{c['id']}"})
    deb = 0
    d = _ro(debate_db)
    try:
        if d is not None:
            try:
                rows = d.execute("SELECT id, ts, question_ko, claim_ko, check_status, check_ko FROM debate_lab_ideas "
                                 "WHERE check_status IN ('cannot_express', 'bad_spec') ORDER BY id DESC LIMIT 200").fetchall()
                # the idea factory has collected an idea (a classic debate.db holds only the empty table)
                started = started or d.execute("SELECT 1 FROM debate_lab_ideas LIMIT 1").fetchone() is not None
            except Exception:  # noqa: BLE001  (no idea table yet: nothing from the debate)
                rows = []
            for rid, ts, q, claim, st, ko in rows:
                deb += 1
                items.append({"source": "debate", "source_ko": "토론방", "ts": ts, "quote": claim or "",
                              "why_ko": (ko or "") + (" (심판이 문법으로 옮길 수 없다고 함)" if st == "cannot_express" else ""),
                              "question_ko": q or "", "reasons_ko": [], "status_ko": ko or st, "label": f"아이디어 #{rid}"})
    finally:
        _close(d)
    items.sort(key=lambda x: -(x.get("ts") or 0))
    tally = sorted(codes.values(), key=lambda r: -(r["none"] + r["approx"]))
    # started False: no source that collects such ideas has ever run (all off: the defaults); the screen says so instead
    # of '0개' that reads like a finished count
    return {"items": items[:limit], "total": len(items), "by_reason": tally, "debate": deb, "started": bool(started),
            "owner": sum(1 for x in items if x["source"] == "owner"), "note_ko": CANTDO_NOTE_KO}


# ---------------------------------------------------------------- routes
def register(app, ctx) -> dict:
    from .luck import DATA
    db = getattr(ctx, "db", None)
    side = os.path.dirname(os.path.abspath(db)) if db else ""
    debate_db = getattr(ctx, "debate_db", None) or (os.path.join(side, "debate", "debate.db") if db else None)
    cp = getattr(ctx, "checkpoint_db", None) or (os.path.join(side, "checkpoint.db") if db else None)
    agents_db = getattr(ctx, "agents_db", None)
    lock = threading.Lock()
    cache: dict = {}

    def cached(key: str, ttl: float, fn):
        with lock:
            hit = cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        v = fn()
        with lock:
            cache[key] = (time.time(), v)
        return v

    def nextver() -> dict:
        data_dir = os.environ.get("PAPERBOT_LUCK_DATA") or DATA
        return {"label": LABEL, "now": int(time.time() * 1000), "candidates": candidates_view(agents_db, data_dir),
                "claims": claims_view(agents_db), "cantdo": cantdo_view(agents_db, debate_db)}

    def goal() -> dict:
        from ...agents.goalline import goal as G
        from .verdictday import job_reader
        a = _ro(agents_db)
        p = _ro(db)
        try:
            # the verdict part in the clock's words (the same day and sentence as /api/summary's verdict_clock)
            return clock_words(G(a, p, cp if cp and os.path.exists(cp) else None), p, db, cp, job_reader())
        finally:
            _close(a)
            _close(p)

    @app.get("/api/v4/nextver")
    def get_nextver():
        """다음 버전 후보 장부 · 주장별 성적표 · 연구실이 못 하는 아이디어 (read-only, cached)."""
        from ..app import json_finite
        return json_finite(cached("nextver", TTL_S, nextver))

    @app.get("/api/v4/goal")
    def get_goal():
        """목표 진척도 한 줄 (agents/goalline.py, read-only, cached)."""
        from ..app import json_finite
        return json_finite(cached("goal", GOAL_TTL_S, goal))

    return {"routes": ["/api/v4/nextver", "/api/v4/goal"]}
