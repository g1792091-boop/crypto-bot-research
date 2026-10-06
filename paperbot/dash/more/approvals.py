"""결재함 (#/inbox, review addition 8): every proposal that waits for the owners, with what they need to decide in one
place, and the past decisions. Read-only over agents3.db, inbox.db and paper3.db.

    GET /api/v4/approvals

Approving and rejecting stay exactly where they were: POST /api/proposals/<id>/decide (dash/app.py Rooms.decide, with
all its checks: the code gate, the gate judged again with the room's tests now, the owners' earlier reject, a started
account). This route only reads. Per waiting proposal (``waiting``; an approved one the runner will start only after
one more click, as the room's '다시 승인': ``again`` true; an owners' click that the agents tick has not applied yet:
``decided``):

- the proposal row as /api/proposals sends it (effective status, the owners' click, the gate now, the running account,
  the runner's refusal, whether the runner's extra-account feature is on)
- ``periods``: the 5-year test of its trial, per period (1: 2021-08~2024-06, 2: 2024-07~2026-09, 3: 2020-01~2021-07):
  a copy's 원본 (the rule now) vs 바꾼 것 (the changed rule): trades, mean ROE per trade, mean P&L on the account's
  equity per trade; a new strategy's own numbers and its difference from the coin flips (agents/labtests.py,
  agents/newlab.py ledger_row). p-values stay in the gate's own reasons.
- ``voices``: the staff lines of the meeting that made the proposal (the analysis, the 반론 검토관's verdict, the
  approver's answer), one line each, as stored
- ``rule_ko`` / ``title_ko``: the one thing a copy changes, the new strategy's description

``past``: the latest decided proposals (approved / rejected, who decided, when), a running copy with its same-period
return next to its parent's (dash/more/copycmp.py). ``period``: the run's start, the end of the observation period (no
proposals before it), the end of the owners' OK period (``owner_ok_days``, at least 60, the runner's own when longer)
and the first owners' click (the home guide card shows until there is one). Cached ``TTL_S``.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional

TTL_S = 20.0
DAY_MS = 86_400_000
OBSERVE_DAYS = 21                 # dash/app.py summary(): start + 21 days unless the runner's floor is later
OWNER_OK_DAYS = 60                # agents/rooms.py RoomsPolicy.owner_ok_days (the runner's own wins when longer)
PAST_MAX = 20
SPEAK = ("analysis", "challenge", "expert", "revision", "verdict")
VERDICT_KO = {"agree": ("찬성", "for"), "disagree": ("반대", "against"), "needs_test": ("시험 더 필요", "against")}
DECIDER_KO = {"owner": "두 분", "approver": "승인관(AI)", "code": "코드"}
RE_APPROVE = ("stale_ok", "owner_click_missing")   # agents/extra_accounts.RE_APPROVE: the runner needs one more click
TEXT_MAX = 180


def _cut(s, n: int = TEXT_MAX) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _month_before(day: str) -> str:
    """'2024-07-01' (an exclusive end) -> '2024-06'."""
    try:
        y, m = int(day[:4]), int(day[5:7])
    except (TypeError, ValueError):
        return str(day or "")[:7]
    if day[8:10] == "01":
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


def period_label(pid: str, row: dict) -> str:
    s, e = str(row.get("start") or ""), str(row.get("end") or "")
    return f"{pid}기간 ({s[:7]}~{_month_before(e)})" if s and e else f"{pid}기간"


def _arm(label: str, x: Optional[dict]) -> dict:
    x = x if isinstance(x, dict) else {}
    return {"label": label, "trades": x.get("trades"), "mean_roe": x.get("mean_roe"), "pnl_equity": x.get("mean_pnl_equity")}


def period_rows(kind: str, trial: Optional[dict]) -> list[dict]:
    """The 5-year table of a proposal's trial (copy: 원본 vs 바꾼 것; newlab: the strategy and its coin-flip difference)."""
    res = (trial or {}).get("result") or {}
    body = res.get("result") if isinstance(res, dict) else None
    body = body if isinstance(body, dict) else {}
    out = []
    if kind == "newlab":
        P = ((body.get("ledger") or {}).get("periods")) or {}
        for pid in ("1", "2", "3"):
            r = P.get(pid)
            if not isinstance(r, dict):
                out.append({"pid": pid, "label": f"{pid}기간", "available": False, "why": "자료 없음", "arms": []})
                continue
            out.append({"pid": pid, "label": f"{pid}기간", "available": True, "arms": [_arm("새 매매법", r)],
                        "diff": r.get("coinflip_diff"), "diff_ko": "동전 봇보다 거래당 ROE"})
        return out
    run = body.get("result") if isinstance(body.get("result"), dict) else {}
    P = run.get("periods") if isinstance(run.get("periods"), dict) else {}
    for pid in ("1", "2", "3"):
        r = P.get(pid)
        if not isinstance(r, dict):
            continue
        if not r.get("available"):
            out.append({"pid": pid, "label": period_label(pid, r), "available": False, "why": r.get("why") or "자료 없음", "arms": []})
            continue
        out.append({"pid": pid, "label": period_label(pid, r), "available": True,
                    "arms": [_arm("원본", r.get("baseline")), _arm("바꾼 것", r.get("variant"))],
                    "diff": r.get("diff"), "diff_ko": "바꾼 것 − 원본 (거래당 ROE)"})
    return out


def _round_of(a: sqlite3.Connection, pid: int, trial: Optional[dict]) -> Optional[int]:
    """The meeting that made the proposal: its 'propose_copy' / new-lab action line, else the trial's own meeting."""
    try:
        r = a.execute("SELECT round_id FROM messages WHERE kind = 'action' AND round_id IS NOT NULL "
                      "AND json_extract(data, '$.proposal_id') = ? ORDER BY id LIMIT 1", (pid,)).fetchone()
        if r and r[0] is not None:
            return int(r[0])
    except sqlite3.Error:
        pass
    rid = (trial or {}).get("round_id")
    return int(rid) if isinstance(rid, int) else None


def voices(a: sqlite3.Connection, round_id: Optional[int], roles: dict, approver: Optional[dict]) -> list[dict]:
    """One stored line per staff member of the meeting (the last one each said), with its stance."""
    out: dict = {}
    if round_id is not None:
        try:
            rows = a.execute("SELECT id, role, speaker_name, kind, text, data FROM messages WHERE round_id = ? "
                             f"AND kind IN ({','.join('?' * len(SPEAK))}) ORDER BY id", (round_id, *SPEAK)).fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows:
            try:
                d = json.loads(r["data"]) if r["data"] else {}
            except (TypeError, ValueError):
                d = {}
            ans = d.get("answer") if isinstance(d, dict) and isinstance(d.get("answer"), dict) else {}
            role = r["role"]
            if r["kind"] == "analysis" and (out.get(role) or {}).get("stance") == "제안":
                continue                                  # the proposer's own line stays the one shown
            if r["kind"] == "challenge" and ans.get("verdict") in VERDICT_KO:
                stance, tone = VERDICT_KO[ans["verdict"]]
            elif role == "approver" or "approve" in ans:
                stance, tone = ("승인관 찬성", "for") if ans.get("approve") is True else ("승인관 반대", "against")
            elif r["kind"] == "challenge":
                stance, tone = "반론", "against"
            elif r["kind"] == "analysis" and not any(v["stance"] == "제안" for v in out.values()):
                stance, tone = "제안", "for"              # the meeting's first analysis: the staff member who proposed it
            else:
                stance, tone = "의견", "neutral"
            line = ans.get("headline") or str(r["text"] or "").split("\n")[0]
            name = r["speaker_name"] or (roles.get(role) or {}).get("name") or role
            out[role] = {"role": role, "name": name, "stance": stance, "tone": tone, "text": _cut(line), "id": int(r["id"])}
    if "approver" not in out and isinstance(approver, dict):
        ok = approver.get("approve") is True
        out["approver"] = {"role": "approver", "name": (roles.get("approver") or {}).get("name") or "자율 승인관",
                           "stance": "승인관 찬성" if ok else "승인관 반대", "tone": "for" if ok else "against",
                           "text": _cut(approver.get("reason") or ""), "id": 2 ** 62}   # after the meeting's lines
    return sorted(out.values(), key=lambda v: v["id"])[:6]


def decider(p: dict) -> Optional[str]:
    by = str(p.get("decided_by") or "")
    return DECIDER_KO.get(by.split(":", 1)[0]) if by else None


def _period(rooms, db: str, now: int) -> dict:
    from ...accounts import ORIGINAL_KINDS
    from ..app import _ro_uri
    start = None
    try:
        c = sqlite3.connect(_ro_uri(db), uri=True, timeout=5)
        try:
            r = c.execute("SELECT MIN(created_ts) FROM accounts WHERE kind IN (%s)" % ",".join("?" * len(ORIGINAL_KINDS)),
                          ORIGINAL_KINDS).fetchone()
            start = int(r[0]) if r and r[0] is not None else None
        finally:
            c.close()
    except sqlite3.Error:
        start = None
    _extras, xs = rooms.runtime()
    days = OWNER_OK_DAYS
    cfg = ((xs or {}).get("config") or {}).get("owner_ok_days")
    if isinstance(cfg, (int, float)) and not isinstance(cfg, bool):
        days = max(days, int(cfg))
    floor = (xs or {}).get("observe_until")
    obs = None
    if start is not None:
        obs = start + OBSERVE_DAYS * DAY_MS
        if isinstance(floor, int) and not isinstance(floor, bool):
            obs = max(obs, floor)
    decs = rooms._decisions()
    first = min((int(d["ts"]) for d in decs.values() if d.get("ts")), default=None)
    return {"start": start, "observe_until": obs, "observing": obs is not None and now < obs, "owner_ok_days": days,
            "owner_ok_until": start + days * DAY_MS if start is not None else None, "first_owner_decision_ts": first,
            "runtime_ready": xs is not None}


def view(rooms, db: str, now_ms: Optional[int] = None) -> dict:
    from ...agents.extra_accounts import rule_ko
    from . import copycmp
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    props = rooms.proposals(limit=1000)
    titles = {k: v.get("title") or k for k, v in (getattr(rooms, "specs", {}) or {}).items()}
    waiting, decided, past = [], [], []
    with rooms.ro(rooms.agents_db) as a:
        ready = a is not None
        for p in props:
            od = p.get("owner_decision") or {}
            eff = p.get("effective_status")
            ch = p.get("change") if isinstance(p.get("change"), dict) else {}
            acc = p.get("account") if isinstance(p.get("account"), dict) else {}
            card = {k: p.get(k) for k in ("id", "ts", "room_id", "strategy", "strategy_ko", "trial_id", "status", "effective_status",
                                          "owner_decision", "gate", "gate_now", "account_running", "runtime_refusal",
                                          "runtime_ready", "kind", "decided_ts")}
            card["room_title"] = titles.get(p.get("room_id"), p.get("room_id"))
            card["rule_ko"] = rule_ko(acc.get("rule")) if acc.get("rule") else None
            card["parent"] = acc.get("parent")
            test = ch.get("test") if isinstance(ch.get("test"), dict) else {}
            card["timeframe"] = acc.get("timeframe") or test.get("timeframe")
            card["test"] = test or None                       # the changed rule as stored (the page names it in words)
            card["why"] = _cut(ch.get("why") or "", 400) or None
            prop = ch.get("proposal") if isinstance(ch.get("proposal"), dict) else {}
            card["title_ko"] = _cut(prop.get("description_ko") or "", 200) or None
            card["decider_ko"] = decider(p)
            open_now = p.get("status") == "awaiting_owner"
            # approved, but the runner refused to start it until the owners click once more (stale_ok: given before
            # its extra-account feature started; owner_click_missing): the room's '다시 승인', here too
            ref = p.get("runtime_refusal") if isinstance(p.get("runtime_refusal"), dict) else {}
            again = (p.get("status") == "approved" and not p.get("account_running") and eff == "approved"
                     and not (od and not od.get("applied")) and ref.get("code") in RE_APPROVE)
            # the owners clicked approve again after the runner's stale_ok refusal: it re-checks at its next pass (no
            # button). owner_click_missing keeps its button: only the owner who decided can mend it (another owner's
            # click leaves the refusal as it was, and the card must not look done)
            sent = bool(again and ref.get("code") == "stale_ok" and od.get("decision") == "approve"
                        and isinstance(ref.get("since"), (int, float)) and int(od.get("ts") or 0) > int(ref["since"]))
            card["again"], card["again_sent"] = again and not sent, sent
            if (open_now or again) and a is not None:
                trial = rooms.R.get_trial(a, int(p["trial_id"])) if p.get("trial_id") else None
                card["periods"] = period_rows(card["kind"], trial)
                card["voices"] = voices(a, _round_of(a, int(p["id"]), trial), rooms.roles, ch.get("approver"))
            if sent:
                decided.append(card)
            elif again:
                waiting.append(card)
            elif open_now and eff == "awaiting_owner":
                waiting.append(card)
            elif open_now:                      # the owners clicked; the agents tick applies it within 15 minutes
                decided.append(card)
            elif p.get("status") in ("approved", "rejected") and len(past) < PAST_MAX:
                run = p.get("account_running")
                if run and card["kind"] == "copy":
                    try:
                        cmp = copycmp.compare(db, run["account_id"], now)
                        card["cmp"] = {"copy_ret": cmp["copy"].get("ret"), "parent_ret": cmp["parent"].get("ret"),
                                       "copy_trades": cmp["copy"]["trades"], "parent_trades": cmp["parent"]["trades"],
                                       "small": cmp["copy"]["small"], "since": cmp["since"], "count_only": cmp["count_only"]}
                    except Exception:  # noqa: BLE001  (a copy the board cannot read: the row says nothing about it)
                        card["cmp"] = None
                card["owner_clicked"] = bool(od)
                past.append(card)
    waiting.sort(key=lambda c: (int(c.get("ts") or 0), int(c["id"])))
    return {"ready": ready, "now": now, "waiting": waiting, "decided": decided, "past": past,
            "period": _period(rooms, db, now)}


def fingerprint(rooms) -> tuple:
    """What changes when a proposal is made or decided: the owners' last click (inbox.db) and the proposals table."""
    out: list = []
    for path, sql in ((rooms.inbox_db, "SELECT MAX(id) FROM approvals"),
                      (rooms.agents_db, "SELECT COUNT(*), MAX(id), MAX(COALESCE(decided_ts, 0)) FROM proposals")):
        with rooms.ro(path) as c:
            try:
                out.append(tuple(c.execute(sql).fetchone()) if c is not None else None)
            except sqlite3.Error:
                out.append(None)
    return tuple(out)


def register(app, ctx) -> dict:
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/approvals")
    def get_approvals():
        """결재함: the proposals that wait for the owners with their evidence, and the past decisions (read-only).
        Cached ``TTL_S``, and answered again at once when a proposal is made or the owners clicked."""
        fp = fingerprint(ctx.rooms)
        hit = cache.get("v")
        if hit and hit[2] == fp and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get("v")
            if hit and hit[2] == fp and time.time() - hit[0] < TTL_S:
                return hit[1]
            v = view(ctx.rooms, ctx.db)
            cache["v"] = (time.time(), v, fp)
        return v

    return {"routes": ["/api/v4/approvals"], "cache": cache}
