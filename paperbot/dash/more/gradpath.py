"""졸업 길 (#/path, 매매법 › 졸업 길): how far the project is from "a strategy that does not lose", as five stages
read from the databases the dashboard already reads (all read-only; nothing is written anywhere):

    아이디어   debate.db debate_ideas (the 24-hour debate room), agents3.db trials kind 'hypothesis' (the meetings' hypothesis
               ledger), inbox.db owner_messages in the lab room (두 분이 새 매매법 연구실에 쓴 글)
    5년 시험   agents3.db trials kind 'test' (a number of an existing strategy) and 'newlab' (a new strategy) with their
               latest result: passed / failed / described / proposed / lapsed / no_data / error, the first failed gate line
               as the reason, and the proposal row of that trial (agents3.db proposals + the owners' clicks in inbox.db)
    모의 계좌  paper3.db accounts on the board (dash.app.Data.board): 기존 36, DeepSeek (counts only, owners' D10 / D11),
               the reel, the approved extra / new-lab accounts; the coin flips as the yardstick (counted, never a candidate)
    30일 판정  checkpoint.db (paperbot.checkpoint.dashboard_view): before the first verdict "판정 전" with the date and the
               accounts that already have the checkpoint's minimum trades; after it the verdict counts per status and the
               accounts that passed (DeepSeek: per status counts only, never one account)
    실전 후보  agents/readiness.evaluate through dash/analysis.readiness_view (the same numbers as 분석 › 실전 준비도): the
               accounts that meet all eight conditions, and what each condition waits for (before the verdict the
               performance conditions are not counted here: no pass / fail hint before the verdict, CONTRACT.md 1.3)

    GET /api/v4/gradpath     background + cached ``TTL_S`` (one computation at a time: dash/analysis.Heavy)

A stage with no data says so (``state: "none"``, "아직 없음"); a source that is not there (no agents3.db, the debate room
never started) says that (``state: "off"``) instead of a zero. Every item carries where it is stuck (``wait``) in plain
Korean ("거래 12건 더 필요", "관찰 기간 10/27까지 제안 없음") and a link into an existing screen (``go``: name, arg, query).
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from typing import Any, Optional

TTL_S = 120
WAIT_S = 3.0
ITEMS = 6                         # items per stage in the answer (the page shows a short list and links on)
TEXT_MAX = 160
LAB_ROOM = "team:lab"
DAY_MS = 86_400_000
KST_MS = 9 * 3_600_000
LABEL = "표시만: 아무것도 켜거나 바꾸지 않음"
STAGE_KO = (("ideas", "아이디어"), ("tests", "5년 시험"), ("paper", "모의 계좌"), ("verdict", "30일 판정"),
            ("ready", "실전 후보"))
# the paper groups shown in stage 3 (paperbot/groups.py keys), in this order; "flip" is the yardstick only
GROUP_KO = {"core": "기존 36", "ds200": "딥시크", "reel": "릴스 5분", "extra": "추가 계좌", "flip": "동전 봇"}
TEST_DONE = ("passed", "failed", "described", "proposed", "lapsed")       # a test that ran and counted
TEST_ADVANCED = {"proposed": 0, "passed": 1, "lapsed": 2, "described": 3, "failed": 4, "no_data": 5, "error": 6}
PROPOSAL_KO = {"awaiting_owner": "두 분 승인 기다림", "approved": "두 분 승인 · 모의 계좌로", "rejected": "두 분이 거절",
               "blocked_gate": "코드 관문에서 막힘", "blocked_cap": "계좌 자리가 차서 대기"}
STATUS_KO = {"passed": "통과", "failed": "탈락", "described": "설명용 시험", "proposed": "제안됨", "lapsed": "다시 판정에서 탈락",
             "no_data": "자료 없어 못 돌림", "error": "오류로 못 돌림", None: "결과 기다림"}
# the readiness conditions that judge performance: not counted here before the first verdict (CONTRACT.md 1.3)
PERF_CONDS = ("q1_fdr", "second_check", "regimes2", "neighbour_tf")


# ---------------------------------------------------------------- small helpers
def _now() -> int:
    return int(time.time() * 1000)


def _mmdd(ms: Optional[int]) -> str:
    if not ms:
        return "—"
    t = time.gmtime((int(ms) + KST_MS) / 1000)
    return f"{t.tm_mon}/{t.tm_mday}"


def _days_left(ts: Optional[int], now: int) -> Optional[int]:
    """Whole KST days from today to the day of ``ts`` (0 = today)."""
    if not ts:
        return None
    return int((int(ts) + KST_MS) // DAY_MS - (now + KST_MS) // DAY_MS)


def _cut(s: Any, n: int = TEXT_MAX) -> str:
    t = " ".join(str(s or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _name(code: Any) -> str:
    """A strategy's Korean name (agents/roster3.STRATEGY_KO, the names every screen uses), else the code."""
    from ...agents.roster3 import STRATEGY_KO
    return _cut(STRATEGY_KO.get(str(code or ""), code), 40)


def _ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    from ..analysis import ro_connect
    return ro_connect(path) if path and os.path.exists(path) else None


def _close(c: Optional[sqlite3.Connection]) -> None:
    if c is not None:
        try:
            c.close()
        except sqlite3.Error:
            pass


def _stage(sid: str, **kw) -> dict:
    ko = dict(STAGE_KO)[sid]
    out = {"id": sid, "ko": ko, "count": 0, "state": "none", "head": "", "items": [], "parts": [], "go": None,
           "none_ko": "아직 없음"}
    out.update(kw)
    return out


def item(title: str, wait: str, *, sub: str = "", ts: Optional[int] = None, tone: str = "", go: Optional[dict] = None,
         tag: str = "", acct: Optional[str] = None) -> dict:
    """One row of a stage: what it is, where it is stuck (``wait``), when, and where a tap goes. ``acct``: the account
    id when the row is one account (the page names it the dashboard's way)."""
    return {"title": _cut(title, 120), "sub": _cut(sub, TEXT_MAX), "wait": _cut(wait, 120), "ts": ts, "tone": tone,
            "go": go, "tag": tag, "acct": acct}


def go(name: str, arg: Optional[str] = None, **query) -> dict:
    return {"name": name, "arg": arg, "query": {k: v for k, v in query.items() if v is not None} or None}


# ---------------------------------------------------------------- 1. ideas
def ideas_stage(debate_ro: Optional[sqlite3.Connection], agents_ro: Optional[sqlite3.Connection],
                inbox_ro: Optional[sqlite3.Connection]) -> dict:
    """The debate room's ideas, the meetings' hypotheses, the owners' posts in the lab room: newest first."""
    parts, rows = [], []
    if debate_ro is not None:
        try:
            n = int(debate_ro.execute("SELECT COUNT(*) FROM debate_ideas").fetchone()[0])
            got = debate_ro.execute("SELECT id, ts, text, tag, status FROM debate_ideas ORDER BY id DESC LIMIT ?",
                                    (ITEMS,)).fetchall()
        except sqlite3.Error:
            n, got = None, []
        if n is not None:
            parts.append({"k": "debate", "ko": "토론방 아이디어", "n": n, "go": go("debate")})
            for r in got:
                st = str(r[4] or "new")
                rows.append(item(r[2], "다음 단계: 회의에서 5년 시험 요청" if st == "new" else f"상태: {_cut(st, 30)}",
                                 sub="24시간 토론방", ts=int(r[1] or 0),
                                 go=go("debate"), tag="토론방"))
    if agents_ro is not None:
        from ...agents import rooms_db as R
        hyps = R.trial_history(agents_ro, kinds=("hypothesis",), limit=ITEMS)
        n = R.trial_counts(agents_ro).get("hypothesis", 0)
        parts.append({"k": "hypothesis", "ko": "회의 가설", "n": int(n), "go": go("rooms")})
        for t in hyps:
            spec = t.get("spec") if isinstance(t.get("spec"), dict) else {}
            res = t.get("result") or {}
            body = res.get("result") if isinstance(res.get("result"), dict) else {}
            if res.get("status") == "graded":
                wait = "채점됨: " + ("예측이 맞음" if body.get("correct") else "예측이 틀림")
            elif res.get("status") == "expired":
                wait = "채점 기한이 지남"
            elif spec.get("prediction"):
                wait = "예측 채점 기다림 (거래가 쌓이면 코드가 채점)"
            else:
                wait = "시험 전 · 채점할 예측 없음"
            rows.append(item(spec.get("text") or f"가설 #{t['id']}", wait,
                             sub=f"회의 가설 #{t['id']}" + (f" · {_name(t.get('strategy'))}" if t.get("strategy") else ""),
                             ts=int(t.get("ts") or 0), go=go("rooms", t.get("room_id")), tag="회의"))
    if inbox_ro is not None:
        try:
            n = int(inbox_ro.execute("SELECT COUNT(*) FROM owner_messages WHERE room_id = ?", (LAB_ROOM,)).fetchone()[0])
            got = inbox_ro.execute("SELECT id, ts, author, text FROM owner_messages WHERE room_id = ? ORDER BY id DESC "
                                   "LIMIT ?", (LAB_ROOM, ITEMS)).fetchall()
        except sqlite3.Error:
            n, got = None, []
        if n is not None:
            parts.append({"k": "owner", "ko": "두 분 글 (연구실)", "n": n, "go": go("rooms", LAB_ROOM)})
            for r in got:
                rows.append(item(r[3], "연구실 직원이 읽고 시험할지 정함", sub="두 분 글" + (f" · {_cut(r[2], 20)}" if r[2] else ""),
                                 ts=int(r[1] or 0), go=go("rooms", LAB_ROOM), tag="두 분"))
    rows.sort(key=lambda x: -(x["ts"] or 0))
    count = sum(p["n"] for p in parts)
    if not parts:
        return _stage("ideas", state="off", none_ko="아직 없음: 토론방·회의 기록을 읽을 수 없습니다", go=go("debate"))
    return _stage("ideas", count=count, state="has" if count else "none", parts=parts, items=rows[:ITEMS],
                  head=" · ".join(f"{p['ko']} {p['n']:,}" for p in parts), go=go("debate"))


# ---------------------------------------------------------------- 2. five-year tests
def _test_title(spec: dict) -> str:
    """The lab's own Korean words for a number test (agents/labtests.describe_ko), else the template name."""
    try:
        from ...agents.labtests import describe_ko
        return describe_ko({**spec, "strategy": _name(spec.get("strategy"))})
    except Exception:  # noqa: BLE001  (an older spec without a field: its template name)
        bits = [str(spec.get(k)) for k in ("strategy", "timeframe", "template") if spec.get(k)]
        return " · ".join(bits)


def first_failed(gate: Any) -> str:
    """The first gate line that did not pass ('… 미달'), else the first line."""
    rs = gate.get("reasons") if isinstance(gate, dict) else None
    rs = [str(r) for r in rs] if isinstance(rs, list) else []
    for r in rs:
        if "미달" in r:
            return r
    return rs[0] if rs else ""


def trial_wait(kind: str, status: Optional[str], body: dict, prop: Optional[dict], observe: dict) -> tuple[str, str]:
    """(wait words, tone) of one five-year test from its latest result and its proposal."""
    gate = body.get("gate") if isinstance(body.get("gate"), dict) else {}
    if prop is not None:
        st = prop.get("effective_status") or prop.get("status")
        run = prop.get("account_running")
        if st == "approved" and isinstance(run, dict):
            return "모의 계좌에서 도는 중", "good"
        return PROPOSAL_KO.get(st, f"제안 상태: {_cut(st, 20)}"), "accent" if st in ("awaiting_owner", "approved") else ""
    if status == "passed":
        if observe.get("observing"):
            return f"관찰 기간 {observe.get('until_ko')}까지 제안 없음", "accent"
        return ("새 매매법 제안 차례 기다림" if kind == "newlab" else "복사 계좌 제안 차례 기다림"), "accent"
    if status == "proposed":
        return "제안됨 · 두 분 결정 기다림", "accent"
    if status == "lapsed":
        return "시험 수가 늘어 다시 판정하니 기준 미달", ""
    if status == "failed":
        return (_cut(first_failed(gate), 110) or "관문 미달"), ""
    if status == "described":
        return "설명용 시험이라 합격·불합격 없음", ""
    if status in ("no_data", "error"):
        return "돌리지 못함: 다시 요청하면 그때 돌림", ""
    return "코드가 돌리기를 기다림", ""


def _prop_rank(prop: dict) -> int:
    """Where a test with a proposal sorts: approved first, then waiting for the owners, a refused one with the failures."""
    st = prop.get("effective_status") or prop.get("status")
    return {"approved": 0, "awaiting_owner": 0}.get(st, 4)


def tests_stage(agents_ro: Optional[sqlite3.Connection], proposals: list, observe: dict) -> dict:
    if agents_ro is None:
        return _stage("tests", state="off", none_ko="아직 없음: 시험 장부(agents3.db)를 읽을 수 없습니다", go=go("rooms", LAB_ROOM))
    from ...agents import rooms_db as R
    try:
        by = agents_ro.execute(
            "SELECT t.kind, (SELECT status FROM trial_results WHERE id = (SELECT MAX(id) FROM trial_results "
            "WHERE trial_id = t.id)) AS st, COUNT(*) FROM trials t WHERE t.kind IN ('test', 'newlab') GROUP BY 1, 2"
        ).fetchall()
    except sqlite3.Error:
        by = []
    counts: dict = {}
    for kind, st, n in by:
        counts.setdefault(kind, {})[st] = int(n)
    done = {k: sum(v for s, v in c.items() if s in TEST_DONE) for k, c in counts.items()}
    good = {k: sum(v for s, v in c.items() if s in ("passed", "proposed")) for k, c in counts.items()}
    bad = {k: sum(v for s, v in c.items() if s in ("failed", "lapsed")) for k, c in counts.items()}
    total = sum(done.values())
    props = {}
    for p in proposals or []:
        if p.get("trial_id") is not None and p.get("status") != "blocked_cap":
            props.setdefault(int(p["trial_id"]), p)
    rows = []
    for t in R.trial_history(agents_ro, kinds=("test", "newlab"), limit=500):
        res = t.get("result") or {}
        st = res.get("status")
        body = res.get("result") if isinstance(res.get("result"), dict) else {}
        spec = t.get("spec") if isinstance(t.get("spec"), dict) else {}
        prop = props.get(int(t["id"]))
        wait, tone = trial_wait(t["kind"], st, body, prop, observe)
        if t["kind"] == "newlab":
            title = body.get("description_ko") or f"새 매매법 #{t['id']}"
            sub = f"새 매매법 시험 #{t['id']}" + (f" · {body.get('test_number'):,}번째 시험" if isinstance(body.get("test_number"), int) else "")
            where = go("rooms", LAB_ROOM)
        else:
            title = _test_title(spec) or f"숫자 바꾸기 시험 #{t['id']}"
            sub = f"기존 매매법 숫자 시험 #{t['id']}"
            where = go("rooms", t.get("room_id"))
        rows.append(dict(item(str(title), wait, sub=sub, ts=int(t.get("ts") or 0), tone=tone, go=where,
                              tag=STATUS_KO.get(st, _cut(st, 20))),
                         rank=_prop_rank(prop) if prop is not None else TEST_ADVANCED.get(st, 7)))
    rows.sort(key=lambda x: (x["rank"], -(x["ts"] or 0)))
    for r in rows:
        r.pop("rank", None)
    parts = [{"k": "newlab", "ko": "새 매매법", "n": done.get("newlab", 0), "good": good.get("newlab", 0),
              "bad": bad.get("newlab", 0), "go": go("rooms", LAB_ROOM)},
             {"k": "test", "ko": "기존 매매법 숫자", "n": done.get("test", 0), "good": good.get("test", 0),
              "bad": bad.get("test", 0), "go": go("rooms")}]
    passed = sum(good.values())
    head = f"시험 {total:,}번 · 통과 {passed:,} · 탈락 {sum(bad.values()):,}"
    return _stage("tests", count=total, state="has" if total else "none", parts=parts, items=rows[:ITEMS], head=head,
                  passed=passed, go=go("rooms", LAB_ROOM),
                  none_ko=("아직 없음: 연구실이 아직 5년 시험을 돌리지 않았습니다"
                           + (f" (관찰 기간 {observe.get('until_ko')}까지는 통과해도 제안하지 않음)" if observe.get("observing") else "")))


# ---------------------------------------------------------------- 3. paper accounts
def paper_stage(board: dict, min_trades: int, verdict_ko: str) -> dict:
    accts = [a for a in (board or {}).get("accounts") or [] if isinstance(a, dict)]
    if not accts:
        return _stage("paper", none_ko="아직 없음: 돌고 있는 모의 계좌가 없습니다", go=go("board"))
    groups: dict = {}
    for a in accts:
        g = a.get("group") or "other"
        e = groups.setdefault(g, {"n": 0, "trades": 0, "enough": 0, "max": 0, "bust": 0, "list": []})
        n = int(a.get("trades") or 0)
        e["n"] += 1
        e["trades"] += n
        e["enough"] += n >= min_trades
        e["max"] = max(e["max"], n)
        e["bust"] += bool(a.get("bust"))
        e["list"].append(n)
    parts, rows = [], []
    for g in ("core", "ds200", "reel", "extra"):
        e = groups.get(g)
        if not e:
            continue
        ns = sorted(e["list"])
        med = ns[len(ns) // 2] if ns else 0
        parts.append({"k": g, "ko": GROUP_KO[g], "n": e["n"], "trades": e["trades"], "enough": e["enough"],
                      "go": go("board", group=g)})
        if g == "extra":
            continue                                   # the extra accounts are listed one by one below
        if e["enough"] >= e["n"]:
            wait = f"모든 계좌가 판정 최소 거래 {min_trades}건을 넘김 · {verdict_ko}"
        else:
            wait = (f"거래 {min_trades}건 넘은 계좌 {e['enough']:,}/{e['n']:,} · 가운데 계좌는 거래 "
                    f"{max(0, min_trades - med):,}건 더 필요")
        sub = f"계좌 {e['n']:,}개 · 닫힌 거래 {e['trades']:,}건" + (f" · 파산 {e['bust']:,}" if e["bust"] else "")
        rows.append(item(f"{GROUP_KO[g]} 계좌들", wait, sub=sub, go=go("board", group=g), tag=GROUP_KO[g],
                         tone="accent" if e["enough"] else ""))
    extras = sorted((a for a in accts if a.get("group") == "extra"), key=lambda a: -int(a.get("created_ts") or 0))
    for a in extras:
        n = int(a.get("trades") or 0)
        wait = (f"판정 최소 거래 {min_trades}건 넘김" if n >= min_trades else f"거래 {min_trades - n:,}건 더 필요")
        rows.append(item(a.get("label_ko") or a.get("account_id") or "추가 계좌", wait,
                         sub=f"추가 계좌 · {_mmdd(a.get('created_ts'))} 시작 · 거래 {n:,}건", ts=a.get("created_ts"),
                         go=go("account", a.get("account_id")), tag="추가", tone="accent" if n >= min_trades else "",
                         acct=None if a.get("label_ko") else a.get("account_id")))
    flips = groups.get("flip", {}).get("n", 0)
    count = sum(p["n"] for p in parts)
    head = " · ".join(f"{p['ko']} {p['n']:,}" for p in parts)
    return _stage("paper", count=count, state="has" if count else "none", parts=parts, items=rows[:ITEMS + 2], head=head,
                  flips=flips, go=go("board"))


# ---------------------------------------------------------------- 4. the 30-day verdict
def verdict_stage(cp: dict, board: dict, next_cp: Optional[dict], now: int, min_trades: int) -> dict:
    from ...checkpoint import FAIL, HOLD, OBSERVE, OBSERVE_TFS, PASS1, PASS2
    nts = (next_cp or {}).get("ts")
    if not cp or not cp.get("ready"):
        left = _days_left(nts, now)
        when = f"{_mmdd(nts)} 첫 판정" + (f" (D-{left})" if left is not None and left > 0 else " (오늘)" if left == 0 else "")
        rows = []
        accts = [a for a in (board or {}).get("accounts") or [] if isinstance(a, dict) and a.get("group") in ("core", "ds200", "reel", "extra")]
        for g in ("core", "ds200", "reel", "extra"):
            gs = [a for a in accts if a.get("group") == g]
            if not gs:
                continue
            judged = [a for a in gs if a.get("timeframe") not in OBSERVE_TFS]
            ok = sum(int(a.get("trades") or 0) >= min_trades for a in judged)
            wait = (f"판정 받을 거래 {min_trades}건 채운 계좌 {ok:,}/{len(judged):,}" if judged else "모두 관찰용(4시간봉)")
            rows.append(item(f"{GROUP_KO[g]}", wait, sub="4시간봉은 관찰용이라 판정하지 않음" if len(judged) < len(gs) else "",
                             go=go("checkpoint"), tag="판정 전"))
        return _stage("verdict", count=None, state="wait", head=f"판정 전 · {when}", items=rows,
                      none_ko=f"판정 전: {when}", when_ko=when, next_ts=nts, go=go("checkpoint"))
    # the coin flips are the yardstick, never a candidate: left out of the counts and the list
    rows_cp = [r for r in cp.get("rows") or [] if isinstance(r, dict) and r.get("group") != "flip"]
    passed = [r for r in rows_cp if r.get("status") in (PASS1, PASS2)]
    by_group: dict = {}
    for r in rows_cp:
        by_group.setdefault(r.get("group") or "other", {}).setdefault(r.get("status"), 0)
        by_group[r.get("group") or "other"][r.get("status")] += 1
    parts = [{"k": s, "ko": s, "n": sum(1 for r in rows_cp if r.get("status") == s)}
             for s in (PASS2, PASS1, FAIL, HOLD, OBSERVE)]
    items = []
    for r in passed:
        if r.get("group") == "ds200":
            continue                                    # DeepSeek: counts only (below), never one account
        st = r.get("status")
        wait = "2차 통과 · 실전 조건 확인으로" if st == PASS2 else "1차 합격 · 다음 30일(2차) 기다림"
        items.append(item(r.get("account_id") or "", wait, sub=f"거래 {int(r.get('trades') or 0):,}건", tone="good",
                          go=go("account", r.get("account_id")), tag=st, acct=r.get("account_id")))
    ds = by_group.get("ds200") or {}
    if ds:
        items.append(item("딥시크 (묶음 숫자만)", "묶음 숫자: " + " · ".join(f"{k} {v:,}" for k, v in ds.items() if k), sub="계좌별로는 보이지 않음 (참고)",
                          go=go("checkpoint"), tag="딥시크"))
    held = [r for r in rows_cp if r.get("status") == HOLD and r.get("group") != "ds200"]
    for r in held[:2]:
        n = int(r.get("trades") or 0)
        items.append(item(r.get("account_id") or "", f"보류: 거래 {max(0, min_trades - n):,}건 더 필요" if n < min_trades
                          else "보류: 이유는 판정 화면에", sub=f"거래 {n:,}건", go=go("account", r.get("account_id")),
                          tag=HOLD, acct=r.get("account_id")))
    n_pass = len(passed)
    head = f"{cp.get('date') or ''} 판정 · " + " · ".join(f"{p['ko']} {p['n']:,}" for p in parts if p["n"])
    return _stage("verdict", count=n_pass, state="has" if n_pass else "none", parts=parts, items=items[:ITEMS + 2],
                  head=head, date=cp.get("date"), next_ts=nts, go=go("checkpoint"),
                  none_ko=f"{cp.get('date') or ''} 판정에서 합격한 계좌 없음")


# ---------------------------------------------------------------- 5. ready for live
def ready_stage(rd: Optional[dict], cp_ready: bool, next_cp: Optional[dict], best_trades: int) -> dict:
    """The readiness conditions (agents/readiness via dash/analysis.readiness_view) and what each waits for.
    ``best_trades``: the most closed trades of one 기존 36 account (the board), for '거래 N건 더 필요'."""
    if not isinstance(rd, dict) or rd.get("pending"):
        return _stage("ready", state="pending", none_ko="계산 중", go=go("analysis", "ready"))
    if rd.get("error"):
        return _stage("ready", state="off", none_ko=f"아직 없음: {_cut(rd['error'], 60)}", go=go("analysis", "ready"))
    s = rd.get("summary") or {}
    bc = s.get("by_condition") or {}
    conds = rd.get("conditions") or []
    nts = (next_cp or {}).get("ts")
    rows = []
    for c in conds:
        cid = c.get("id")
        v = bc.get(cid) or {}
        ok = int(v.get("✅") or 0)
        if cid == "day30":
            days = float(s.get("days_running") or 0)
            wait = "시작 후 30일 지남" if days >= 30 else f"30일까지 {max(1, math.ceil(30 - days)):,}일 더"
        elif cid == "trades200":
            wait = (f"거래 200건 넘은 계좌 {ok:,}개" if ok else f"가장 많은 계좌도 거래 {max(0, 200 - best_trades):,}건 더 필요")
        elif cid in PERF_CONDS and not cp_ready:
            wait = f"{_mmdd(nts)} 판정 뒤에 셈" if cid != "second_check" else "1차 판정 다음 30일 뒤"
        elif cid in ("cost_ratio", "testnet"):
            wait = "실거래 쪽 기록이라 두 분이 확인"
        else:
            wait = f"충족 {ok:,} · 아님 {int(v.get('❌') or 0):,} · 판단 전 {int(v.get('아직 판단 불가') or 0):,}"
        rows.append(item(c.get("label") or cid or "", wait, go=go("analysis", "ready"), tag="조건"))
    met = int(s.get("met_all") or 0)
    head = f"실전 조건 8개 모두 채운 계좌 {met:,}개 · 기존 36 계좌 {int(s.get('accounts') or 0):,}개 중"
    return _stage("ready", count=met, state="has" if met else "none", head=head, items=rows,
                  none_ko=("아직 없음: 판정 전에는 실전 후보가 나올 수 없습니다" if not cp_ready else "아직 없음: 8개 조건을 모두 채운 계좌 없음"),
                  q6_6=s.get("q6_6"), go=go("analysis", "ready"))


# ---------------------------------------------------------------- everything
def path_view(data, rooms, paper_db: str, debate_db: Optional[str], checkpoint_db: Optional[str], now: int,
              readiness: Optional[dict] = None) -> dict:
    from ...checkpoint import MIN_TRADES
    try:
        summ = data.summary(now)
    except Exception:  # noqa: BLE001  (a missing paper3.db never takes the page down)
        summ = {}
    obs_ts = summ.get("observe_until")
    observe = {"observing": bool(summ.get("observing")), "until": obs_ts,
               "until_ko": _mmdd(obs_ts) if obs_ts else "—"}
    next_cp = summ.get("next_checkpoint") if isinstance(summ.get("next_checkpoint"), dict) else None
    try:
        board = data.board()
    except Exception:  # noqa: BLE001
        board = {}
    try:
        proposals = rooms.proposals(limit=1000) if getattr(rooms, "agents_db", None) else []
    except Exception:  # noqa: BLE001
        proposals = []
    dc = _ro(debate_db)
    try:
        with rooms.ro(rooms.agents_db) as a, rooms.ro(getattr(rooms, "inbox_db", None)) as ib:
            s1 = ideas_stage(dc, a, ib)
            s2 = tests_stage(a, proposals, observe)
    finally:
        _close(dc)
    from ...agents.readiness import checkpoint_view
    cp = checkpoint_view(checkpoint_db if checkpoint_db and os.path.exists(checkpoint_db) else None)
    vko = f"{_mmdd((next_cp or {}).get('ts'))} 판정 기다림"
    s3 = paper_stage(board, MIN_TRADES, vko)
    s4 = verdict_stage(cp, board, next_cp, now, MIN_TRADES)
    if readiness is None:
        from ..analysis import readiness_view
        readiness = readiness_view(paper_db, checkpoint_db, now, next_cp)
    best = max([int(a.get("trades") or 0) for a in (board or {}).get("accounts") or []
                if isinstance(a, dict) and a.get("group") == "core"] or [0])
    s5 = ready_stage(readiness, bool(cp.get("ready")), next_cp, best)
    stages = [s1, s2, s3, s4, s5]
    frontier = None
    for st in stages:
        if st.get("count"):
            frontier = st["id"]
    # D+ the way the top bar counts it (core/shell.js: the restart banner's day, else summary day - 1)
    rs = summ.get("restart") if isinstance(summ.get("restart"), dict) else {}
    dplus = rs.get("day") if rs.get("ready") else (int(summ["day"]) - 1 if summ.get("day") else None)
    return {"label": LABEL, "now": now, "start": summ.get("start"), "dplus": dplus, "observe": observe,
            "next_checkpoint": next_cp, "verdict_ready": bool(cp.get("ready")), "min_trades": MIN_TRADES,
            "stages": stages, "frontier": frontier}


def fresh_cached(heavy, key: str) -> Optional[dict]:
    """분석 › 실전 준비도's own cached answer (dash/analysis.Heavy) while it is within its time to live, else None (then
    path_view computes it itself): an old answer is never shown as today's."""
    lock, cache = getattr(heavy, "lock", None), getattr(heavy, "cache", None)
    if lock is None or not isinstance(cache, dict):
        return None
    with lock:
        hit = cache.get(key)
    if not hit or time.time() - hit[0] >= hit[2]:
        return None
    v = hit[1]
    return v if isinstance(v, dict) and not v.get("error") and not v.get("pending") else None


def register(app, ctx) -> dict:
    from ..analysis import Heavy
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):
        heavy = Heavy()
    # the debate room's file: the dashboard's own default (create_app: debate/debate.db next to paper3.db)
    debate_db = getattr(ctx, "debate_db", None) or os.path.join(os.path.dirname(os.path.abspath(ctx.db)), "debate", "debate.db")

    def make() -> dict:
        return path_view(ctx.data, ctx.rooms, ctx.db, debate_db, ctx.checkpoint_db, _now(), fresh_cached(heavy, "readiness"))

    @app.get("/api/v4/gradpath")
    def get_gradpath():
        """졸업 길: five stages from an idea to a live candidate; background + cached ``TTL_S``."""
        return heavy.get("gradpath", TTL_S, make, wait_s=WAIT_S)

    return {"routes": ["/api/v4/gradpath"]}
