"""Extra paper accounts, the agents' side (docs/agent-rooms.md "복제 계좌", "새 매매법 연구실 계좌").

Two kinds of extra paper account can run next to the original 195 in the live runner (paperbot/live3.py,
the only writer of paper3.db), each one a NEW account; the originals never change:

- copy    one of the 36 strategies on one timeframe with exactly one lab-template change (stop_atr k,
          lock_start first_lock, skip_tag tag), from a copy proposal (actions.propose_copy);
- newlab  a new strategy in the lab grammar (docs/newlab-prereg.md), from a lab pass the owners approved
          (actions.newlab_propose: a proposal row of kind 'newlab', the same awaiting_owner flow).

This module is the contract between the two sides, as the agents see it (no import of the runtime):

- what a proposal row carries (``change.kind`` and ``change.account``, built by code from the trial row only:
  ``copy_account`` / ``newlab_account``, never from model text) and how an account is identified
  (``content_key``, ``source_of``: the proposal row (id and time), the trial (id and time) and the content);
- what it reads back from paper3.db, read-only: the running extras (``paper_extras``, matched to a proposal by
  exact ``data.source`` equality in ``account_of_proposal``, never by an account id or a proposal id alone)
  and the runner's state ``extras`` (``runner_state``: its refusals, suspended or held accounts);
- the caps as the union of active proposals and running extras (``slots``);
- the code-only housekeeping of every agents tick (``extras_tick``): say in the room when an account started,
  close approved proposals the runner refused for good (or that a reject click, a failed gate or a bust parent
  ended), and flag running extras whose proposal is missing or no longer approved. Nothing here can stop or
  change a running account, and nothing is changed while paper3.db cannot be read.

The live runner re-checks everything itself at the moment it creates an account (the gate with its own counts,
the caps, the owners' click in inbox.db, the run it belongs to); this side only proposes and records.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from typing import Any, Optional

from ..sessions import KST
from . import rooms_db as R

V = 1                                              # change.account["v"] and accounts.data["v"]
KINDS = ("copy", "newlab")                         # accounts.kind of an extra (the 195 are strategy / random)
TFS = ("5m", "15m", "30m", "1h", "4h")
COPY_PARAM = {"stop_atr": "k", "lock_start": "first_lock", "skip_tag": "tag"}   # the lab templates a copy may use
PARENT_MIN_TRADES = 30                             # closed trades the copy's parent account needs (paper3 trades)
NEWLAB_CAP_TOTAL = 10                              # new-strategy accounts at once (the runtime refuses more)
LAB_ROOM = R.LAB_ROOM

# Runtime refusal codes that only a status change can resolve (state 'extras'.refused[pid].permanent); both
# sides copy this literal (docs: the extras design, section 3.4).
PERMANENT = frozenset({"contract_missing", "contract_mismatch", "spec_invalid", "trial_status", "stale_run",
                       "owner_ok_missing", "owner_click_missing", "duplicate", "gate_now_fail", "parent_missing",
                       "parent_bust"})

# Account ids are assigned by the runner (never by this side); these are what they look like.
COPY_ID_RE = re.compile(r"^(?P<S>[A-Za-z0-9_]+)@(?P<tf>5m|15m|30m|1h|4h)~c(?P<n>[1-9][0-9]{0,3})$")
NEWLAB_ID_RE = re.compile(r"^NL(?P<n>[1-9][0-9]{0,3})@(?P<tf>5m|15m|30m|1h|4h)$")

# Korean for the runner's refusal codes (room lines and the dashboard)
REFUSAL_KO = {
    "contract_missing": "제안에 계좌 정의가 없어(이 기능 전에 만든 제안) 실행기가 계좌를 만들 수 없습니다",
    "contract_mismatch": "제안의 계좌 정의가 시험 기록과 맞지 않아 실행기가 받지 않았습니다",
    "spec_invalid": "계좌 규칙이 실행기의 검사(정해진 값 목록)를 통과하지 못했습니다",
    "trial_status": "시험 기록이 계좌를 만들 수 있는 상태가 아닙니다",
    "stale_run": "이번 paper 실행 전이나 관찰 기간 중에 만든(또는 결정한) 제안이라 이 실행에서는 계좌를 만들지 않습니다",
    "owner_ok_missing": "운영 처음 60일 안의 결정이라 두 분 확인이 필요한데, 두 분이 승인한 기록이 없습니다",
    "owner_click_missing": "두 분 승인으로 기록돼 있지만 대시보드에서 누른 승인 클릭을 찾지 못했습니다",
    "duplicate": "같은 계좌(같은 원본에 같은 규칙, 또는 같은 새 매매법)가 이미 돌고 있습니다",
    "gate_now_fail": "계좌를 만들기 직전에 지금 시험 수로 다시 판정하니 코드 관문을 통과하지 못했습니다",
    "parent_missing": "원본 계좌가 paper3에 없습니다",
    "parent_bust": "원본 계좌가 파산했습니다",
    "observing": "관찰 기간이라 기다립니다",
    "paused": "운영자가 새 계좌 시작을 잠시 멈춰 두었습니다",
    "agents_unreadable": "실행기가 agents3.db를 읽지 못해 기다립니다",
    "inbox_unreadable": "실행기가 inbox.db를 읽지 못해 기다립니다",
    "agents_regressed": "agents3.db가 예전 백업으로 바뀐 것 같아 운영자 확인을 기다립니다",
    "stale_ok": "이 기능이 켜지기 전에 승인한 제안이라, 두 분이 한 번 더 승인해야 시작합니다",
    "reject_pending": "두 분의 거절 클릭이 있어 계좌를 만들지 않습니다",
    "gate_disagree": "관문 다시 판정이 두 계산에서 달라 운영자 확인을 기다립니다",
    "gate_code_unavailable": "관문 판정 코드를 불러오지 못해 기다립니다",
    "parent_trades": f"원본 계좌의 거래가 아직 {PARENT_MIN_TRADES}건이 안 돼 기다립니다",
    "cap_strategy": "이 매매법의 복제 계좌 자리(1개)가 차 있어 기다립니다",
    "cap_copy_total": "복제 계좌 전체 자리(10개)가 차 있어 기다립니다",
    "cap_newlab_total": "새 매매법 계좌 자리(10개)가 차 있어 기다립니다",
    "newlab_unavailable": "새 매매법 신호 코드를 실행기에서 쓸 수 없어 기다립니다",
    "id_conflict": "계좌 번호가 겹쳐 운영자 확인을 기다립니다",
}
EXTRA_STATUS_KO = {"active": "도는 중", "suspended": "멈춤(보류)", "held": "정지(동결)"}

STARTED_CURSOR = "extra_started:{pid}@{ts}"        # the room was told the account started (once)
ORPHAN_CURSOR = "extra_orphan:{aid}@{created}"     # the room was told a running extra has no approved proposal
ORPHANS = "extras:orphans"                         # {account id: {...}} for the dashboard's badge


class PaperUnreadable(LookupError):
    """paper3.db is missing or cannot be read: nothing that depends on it may change."""


# ---------------------------------------------------------------- the contract (pure)
def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if isinstance(v, int) else None


def copy_account(trial: Optional[dict]) -> Optional[dict]:
    """``change.account`` of a copy proposal, from the trial row only (its stored, code-normalised spec):
    {"v": 1, "kind": "copy", "trial_id", "strategy", "timeframe", "parent": "S@tf", "rule": {"template", <param>}}.
    None for a trial that is not a copyable 5-year test (a descriptive template, an odd spec). No account id:
    the runner assigns it."""
    if not isinstance(trial, dict) or trial.get("kind") != "test":
        return None
    sp = trial.get("spec")
    tid = _int(trial.get("id"))
    if not isinstance(sp, dict) or tid is None:
        return None
    tmpl = sp.get("template")
    param = COPY_PARAM.get(tmpl) if isinstance(tmpl, str) else None
    s, tf = sp.get("strategy"), sp.get("timeframe")
    if param is None or not isinstance(s, str) or not s or tf not in TFS:
        return None
    v = sp.get(param)
    if tmpl == "skip_tag":
        if not isinstance(v, str) or not v:
            return None
        val: Any = v
    else:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        val = float(v)
    return {"v": V, "kind": "copy", "trial_id": tid, "strategy": s, "timeframe": tf, "parent": f"{s}@{tf}",
            "rule": {"template": tmpl, param: val}}


def newlab_account(trial: Optional[dict]) -> Optional[dict]:
    """``change.account`` of a new-strategy proposal, from the 'newlab' trial row only: {"v": 1, "kind":
    "newlab", "trial_id", "timeframe", "spec" (the stored canonical spec), "spec_hash" (= trials.spec_hash =
    newlab.spec_hash(spec))}. None when the row is not a lab test or its hash does not match its spec."""
    if not isinstance(trial, dict) or trial.get("kind") != "newlab":
        return None
    sp, h, tid = trial.get("spec"), trial.get("spec_hash"), _int(trial.get("id"))
    if not isinstance(sp, dict) or not isinstance(h, str) or tid is None or sp.get("timeframe") not in TFS:
        return None
    if R.spec_hash(sp) != h:
        return None
    return {"v": V, "kind": "newlab", "trial_id": tid, "timeframe": sp["timeframe"], "spec": sp, "spec_hash": h}


def content_key(account: Any) -> Optional[str]:
    """'copy:' + the rule as sorted compact JSON, or 'newlab:' + spec_hash; None when there is no account."""
    if not isinstance(account, dict):
        return None
    if account.get("kind") == "copy" and isinstance(account.get("rule"), dict):
        return "copy:" + json.dumps(account["rule"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if account.get("kind") == "newlab" and isinstance(account.get("spec_hash"), str):
        return "newlab:" + account["spec_hash"]
    return None


def source_of(p: dict, t: dict, account: Any) -> dict:
    """The identity of the account a proposal row starts (``accounts.data.source``), compared by exact equality."""
    return {"proposal_id": p.get("id"), "proposal_ts": p.get("ts"), "trial_id": t.get("id"), "trial_ts": t.get("ts"),
            "content": content_key(account)}


def proposal_kind(p: Optional[dict]) -> str:
    ch = (p or {}).get("change")
    k = ch.get("kind") if isinstance(ch, dict) else None
    return k if k in KINDS else "copy"


def proposal_account(p: Optional[dict]) -> Optional[dict]:
    ch = (p or {}).get("change")
    acc = ch.get("account") if isinstance(ch, dict) else None
    return acc if isinstance(acc, dict) else None


def rule_ko(rule: Any) -> str:
    """One short Korean line for a copy's rule."""
    if not isinstance(rule, dict):
        return "규칙 없음"
    t = rule.get("template")
    try:
        if t == "stop_atr":
            return f"손절 {float(rule.get('k')):g} ATR"
        if t == "lock_start":
            return f"첫 익절 잠금 +{round(float(rule.get('first_lock')) * 100)}%"
    except (TypeError, ValueError):
        return str(t)
    if t == "skip_tag":
        return f"'{rule.get('tag')}' 진입 건너뛰기"
    return str(t)


def label_of(e: dict) -> str:
    """The runner's own Korean label of an extra (``data.label_ko``), else a plain one."""
    d = e.get("data") if isinstance(e.get("data"), dict) else {}
    if isinstance(d.get("label_ko"), str) and d["label_ko"]:
        return d["label_ko"]
    if e.get("kind") == "copy":
        return f"{e.get('parent') or e.get('strategy')} 복제 · {rule_ko(d.get('rule'))}"
    return f"새 매매법 {e.get('strategy')} · {e.get('timeframe')}"


def copy_label(e: dict) -> str:
    """How a copy's trades are labelled in its parent's packet."""
    d = e.get("data") if isinstance(e.get("data"), dict) else {}
    return f"copy: {e.get('account_id')}, rule {rule_ko(d.get('rule'))}"


# ---------------------------------------------------------------- paper3.db (read-only)
def paper_extras(paper_ro: Optional[sqlite3.Connection]) -> Optional[list[dict]]:
    """The extra accounts in paper3.db (rowid order): account_id, strategy, timeframe, kind, created_ts, parent and
    ``data`` (decoded). [] when there is none (or no accounts table yet); None when paper3.db is missing or a
    read fails (the caller then changes nothing)."""
    if paper_ro is None:
        return None
    try:
        rows = paper_ro.execute("SELECT account_id, strategy, timeframe, kind, created_ts, parent, data FROM accounts "
                                "WHERE kind IN ('copy', 'newlab') ORDER BY rowid").fetchall()
    except sqlite3.OperationalError as exc:
        return [] if "no such table" in str(exc) else None
    except sqlite3.Error:
        return None
    out = []
    for r in rows:
        try:
            d = json.loads(r[6]) if r[6] else {}
        except (TypeError, ValueError):
            d = {}
        out.append({"account_id": r[0], "strategy": r[1], "timeframe": r[2], "kind": r[3], "created_ts": r[4],
                    "parent": r[5], "data": d if isinstance(d, dict) else {}})
    return out


def snapshot(paper_ro: Optional[sqlite3.Connection]) -> tuple[Optional[list], Optional[dict]]:
    """(``paper_extras``, ``runner_state``) read in ONE read transaction, so an account the runner creates in
    between is never seen half (its row without its state, or the reverse)."""
    if paper_ro is None:
        return None, None
    began = False
    try:
        if not paper_ro.in_transaction:
            paper_ro.execute("BEGIN")
            began = True
    except sqlite3.Error:
        began = False
    try:
        return paper_extras(paper_ro), runner_state(paper_ro)
    finally:
        if began:
            try:
                paper_ro.execute("COMMIT")
            except sqlite3.Error:
                pass


def runner_state(paper_ro: Optional[sqlite3.Connection]) -> Optional[dict]:
    """The runner's state 'extras' (v 1) or None (absent: the runtime feature is not deployed; or unreadable)."""
    if paper_ro is None:
        return None
    try:
        r = paper_ro.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()
        v = json.loads(r[0]) if r and r[0] else None
    except (sqlite3.Error, TypeError, ValueError):
        return None
    return v if isinstance(v, dict) and v.get("v") == V else None


def extra_status(state: Optional[dict], account_id: str) -> str:
    """'active', 'suspended' or 'held' (the runner lists only the extras that are not active)."""
    acc = (state or {}).get("accounts")
    got = acc.get(account_id) if isinstance(acc, dict) else None
    st = got.get("status") if isinstance(got, dict) else None
    return st if st in ("suspended", "held") else "active"


def refusal_of(state: Optional[dict], p: dict) -> Optional[dict]:
    """The runner's current refusal of this proposal row (state 'extras'.refused[pid] with the same proposal_ts)."""
    ref = (state or {}).get("refused")
    got = ref.get(str(p.get("id"))) if isinstance(ref, dict) else None
    if not isinstance(got, dict) or got.get("proposal_ts") != p.get("ts"):
        return None
    return {**got, "text_ko": REFUSAL_KO.get(str(got.get("code")), str(got.get("code")))}


def parent_facts(paper_ro: Optional[sqlite3.Connection], parent: str) -> Optional[dict]:
    """{"exists", "kind", "bust", "trades"} of a copy's parent account (closed trades counted in paper3 trades;
    bust from the saved engine state or a BUST alert). None when paper3.db cannot be read."""
    if paper_ro is None:
        return None
    try:
        r = paper_ro.execute("SELECT kind FROM accounts WHERE account_id = ?", (parent,)).fetchone()
        n = int(paper_ro.execute("SELECT COUNT(*) FROM trades WHERE account_id = ?", (parent,)).fetchone()[0])
        st = paper_ro.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        tag = f"[{parent}] BUST:"
        alert = paper_ro.execute("SELECT 1 FROM alerts WHERE level = 'WARN' AND substr(text, 1, ?) = ? LIMIT 1",
                                 (len(tag), tag)).fetchone()
    except sqlite3.Error:
        return None
    eng = {}
    if st is not None:
        try:
            eng = (json.loads(st[0]).get("engines") or {}).get(parent) or {}
        except (TypeError, ValueError, AttributeError):
            eng = {}
    return {"exists": r is not None, "kind": None if r is None else r[0], "trades": n,
            "bust": bool(alert) or bool(isinstance(eng, dict) and eng.get("bust"))}


def account_of_proposal(paper_ro: Optional[sqlite3.Connection], p: dict, t: Optional[dict],
                        extras: Optional[list] = None) -> Optional[dict]:
    """The running extra started from this proposal row: ``data.source`` equal to ``source_of(p, t,
    change.account)``, exactly (a reused proposal id with another time, another trial or another content is a
    different account). None when there is none; raises PaperUnreadable when paper3.db cannot be read."""
    if extras is None:
        extras = paper_extras(paper_ro)
        if extras is None:
            raise PaperUnreadable("paper3.db")
    acc = proposal_account(p)
    if acc is None or not isinstance(t, dict):
        return None
    src = source_of(p, t, acc)
    if src["content"] is None:
        return None
    for e in extras:
        if e["data"].get("source") == src:
            return e
    return None


def running_account(conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection], p: dict,
                    extras: Optional[list] = None) -> Optional[dict]:
    """``account_of_proposal`` with the trial read from agents3.db (raises PaperUnreadable)."""
    t = R.get_trial(conn, int(p["trial_id"])) if _int(p.get("trial_id")) else None
    return account_of_proposal(paper_ro, p, t, extras)


def slots(conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection], kind: str,
          strategy: Optional[str] = None, extras: Optional[list] = None) -> Optional[int]:
    """Slots in use for the caps: active proposals of this kind (and strategy) plus the running extras of this
    kind (and strategy) that match no active proposal (an agents3.db restored without the row, a proposal
    closed after its account started). None when paper3.db cannot be read (then nothing is proposed)."""
    if extras is None:
        extras = paper_extras(paper_ro)
    if extras is None:
        return None
    n = R.active_proposals(conn, strategy, kind=kind)
    for e in extras:
        if e["kind"] != kind or (strategy is not None and e["strategy"] != strategy):
            continue
        src = e["data"].get("source") if isinstance(e["data"].get("source"), dict) else {}
        pid = _int(src.get("proposal_id"))
        p = R.get_proposal(conn, pid) if pid is not None and 0 < pid < 2 ** 63 else None
        if (p is not None and p["status"] in R.ACTIVE_PROPOSAL_STATUSES and proposal_kind(p) == kind
                and (strategy is None or p.get("strategy") == strategy)):
            got = running_account(conn, paper_ro, p, extras)
            if got is not None and got["account_id"] == e["account_id"]:
                continue                                # counted with its proposal
        n += 1
    return n


def reject_click(inbox_ro: Optional[sqlite3.Connection], p: dict) -> Optional[bool]:
    """Is there an owner reject click for this proposal row (written at or after the row)? None: unreadable."""
    if inbox_ro is None:
        return None
    try:
        r = inbox_ro.execute("SELECT 1 FROM approvals WHERE proposal_id = ? AND decision = 'reject' AND ts >= ? "
                             "LIMIT 1", (int(p["id"]), int(p["ts"]))).fetchone()
    except (sqlite3.Error, TypeError, ValueError, OverflowError):
        return None
    return r is not None


def account_stats(paper_ro: sqlite3.Connection, ids: list[str]) -> dict:
    """{account id: {"wallet", "bust", "trades", "wins", "pnl", "position"}} from paper3 (read errors: {})."""
    if not ids:
        return {}
    out = {a: {"wallet": None, "bust": False, "trades": 0, "wins": 0, "pnl": 0.0, "position": False} for a in ids}
    try:
        q = ",".join("?" * len(ids))
        for aid, n, w, pnl in paper_ro.execute(f"SELECT account_id, COUNT(*), SUM(pnl > 0), SUM(pnl) FROM trades "
                                               f"WHERE account_id IN ({q}) GROUP BY account_id", ids):
            out[aid].update(trades=int(n), wins=int(w or 0), pnl=round(float(pnl or 0.0), 2))
        st = paper_ro.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        eng = (json.loads(st[0]).get("engines") or {}) if st else {}
    except (sqlite3.Error, TypeError, ValueError, AttributeError):
        return out
    for a in ids:
        e = eng.get(a) if isinstance(eng.get(a), dict) else {}
        out[a].update(wallet=e.get("wallet"), bust=bool(e.get("bust")), position=bool(e.get("position")))
    return out


def overview(paper_ro: Optional[sqlite3.Connection], kind: Optional[str] = None,
             strategy: Optional[str] = None) -> list[dict]:
    """The running extras (of one kind / strategy) as code-written rows for the packets and the rooms: id, label,
    rule or spec, start, proposal number, the runner's status, wallet, trades. [] when paper3.db is unreadable."""
    extras = paper_extras(paper_ro) or []
    sel = [e for e in extras if (kind is None or e["kind"] == kind)
           and (strategy is None or e["strategy"] == strategy)]
    if not sel:
        return []
    state = runner_state(paper_ro)
    stats = account_stats(paper_ro, [e["account_id"] for e in sel])
    out = []
    for e in sel:
        d = e["data"]
        src = d.get("source") if isinstance(d.get("source"), dict) else {}
        row = {"account_id": e["account_id"], "kind": e["kind"], "strategy": e["strategy"],
               "timeframe": e["timeframe"], "parent": e["parent"], "created_ts": e["created_ts"],
               "label_ko": label_of(e), "proposal_id": src.get("proposal_id"), "trial_id": src.get("trial_id"),
               "status": extra_status(state, e["account_id"]), **stats.get(e["account_id"], {})}
        if e["kind"] == "copy":
            row.update(rule=d.get("rule"), rule_ko=rule_ko(d.get("rule")), label=copy_label(e))
        else:
            row.update(spec=d.get("spec"), spec_hash=d.get("spec_hash"), description_ko=d.get("description_ko"))
        out.append(row)
    return out


# ---------------------------------------------------------------- the tick's housekeeping
def _kst(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=KST).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _room_of(e: dict) -> str:
    return LAB_ROOM if e.get("kind") == "newlab" else R.strategy_room_id(str(e.get("strategy")))


def _close(conn: sqlite3.Connection, p: dict, text: str, data: dict, now: int) -> bool:
    """approved -> rejected by code, with its room line, in one transaction."""
    try:
        changed = R.set_proposal_status(conn, int(p["id"]), "rejected", "code", ts=now, commit=False)
        if changed:
            R.post(conn, p["room_id"], None, "extras", "code", None, "system", text,
                   {"action": "extras_close", "proposal_id": p["id"], **data}, ts=now, commit=False)
        conn.commit()
        return bool(changed)
    except (sqlite3.Error, ValueError):
        conn.rollback()
        return False


def _repair_trial(conn: sqlite3.Connection, p: dict, t: dict, now: int) -> bool:
    """A 'newlab' trial whose proposal exists but whose latest result is still 'passed': append 'proposed'
    (idempotent: only while it is 'passed')."""
    res = t.get("result") or {}
    if t.get("kind") != "newlab" or res.get("status") != "passed":
        return False
    body = res.get("result") if isinstance(res.get("result"), dict) else {}
    prop = (p.get("change") or {}).get("proposal") if isinstance(p.get("change"), dict) else None
    R.add_trial_result(conn, int(t["id"]), "proposed", {**body, "proposal": prop, "proposal_id": p["id"],
                                                        "repaired": True, "proposed_ts": now}, ts=now)
    return True


def extras_tick(ctx: Any) -> dict:
    """Code-only housekeeping each tick (``ctx``: rooms.RoundContext). Nothing when paper3.db cannot be read.
    For every approved proposal:
      - its account runs (exact source match): say so once in its room;
      - no account, and the runner refused it for good (state 'extras'.refused with this row's time and
        ``permanent``): close it by code, with the reason (a new-strategy trial still 'passed' although its
        proposal exists is repaired instead: 'proposed' appended);
      - no account and a reject click for this row: close it (a reject refused while an account ran, then a
        paper3 restore);
      - no account and the gate judged now fails, or a copy's parent is bust or missing: close it.
    For every running extra whose proposal is missing or no longer approved: one loud room line and a badge on
    the dashboard (cursor ``extras:orphans``). A running account is never touched. Never raises."""
    out: dict = {"started": [], "closed": [], "repaired": [], "orphans": []}
    conn, now = ctx.agents_conn, int(ctx.now_ms)
    try:
        extras, state = snapshot(ctx.paper_ro)
        if extras is None:
            out["skipped"] = "paper3 unreadable"
            return out
        from . import rooms as RM                      # gate_now (lazy: rooms imports this module)
        for p in reversed(R.list_proposals(conn, status="approved", limit=1000)):
            t = R.get_trial(conn, int(p["trial_id"])) if _int(p.get("trial_id")) else None
            e = account_of_proposal(ctx.paper_ro, p, t, extras)
            kind = proposal_kind(p)
            if e is not None:
                key = STARTED_CURSOR.format(pid=p["id"], ts=p["ts"])
                if R.get_cursor(conn, key) is None:
                    R.post(conn, p["room_id"], None, "extras", "code", None, "system",
                           f"📗 계좌가 시작됐습니다: {label_of(e)} ({e['account_id']}), 시작 {_kst(e['created_ts'])}. "
                           f"제안 #{p['id']}의 규칙대로 돌고, 원본 계좌와 따로 셉니다.",
                           {"action": "extra_started", "proposal_id": p["id"], "account_id": e["account_id"],
                            "created_ts": e["created_ts"]}, ts=now, commit=False)
                    R.set_cursor(conn, key, now)
                    out["started"].append(p["id"])
                continue
            ref = refusal_of(state, p)
            if ref is not None and ref.get("permanent") is True and ref.get("code") in PERMANENT:
                code = ref["code"]
                if (code == "trial_status" and ref.get("detail") == "passed" and kind == "newlab"
                        and t is not None and _repair_trial(conn, p, t, now)):
                    out["repaired"].append(p["id"])
                    continue
                text = f"제안 #{p['id']}을 코드가 거절로 닫았습니다: {REFUSAL_KO.get(code, code)}."
                if code == "owner_click_missing":
                    text = "⚠️ " + text + " 운영자가 확인해 주세요."
                if _close(conn, p, text, {"why": "runtime_refusal", "code": code}, now):
                    out["closed"].append((p["id"], code))
                    if code == "owner_click_missing":
                        _notify(ctx, f"[추가 계좌] 제안 #{p['id']}: {REFUSAL_KO[code]} (코드가 닫음)")
                continue
            if reject_click(ctx.inbox_ro, p):
                if _close(conn, p, f"제안 #{p['id']}: 두 분의 거절 클릭이 남아 있어 닫습니다(계좌는 시작되지 않았습니다).",
                          {"why": "reject_click"}, now):
                    out["closed"].append((p["id"], "reject_click"))
                continue
            g, n = RM.gate_now(conn, p, now)
            if g.get("pass") is not True:
                if _close(conn, p, f"제안 #{p['id']}은 지금 시험 수({n}번)로 다시 판정하니 코드 관문을 통과하지 못해 "
                                   "코드가 거절로 닫았습니다(계좌는 시작되지 않았습니다).",
                          {"why": "gate_now", "gate_now": {"pass": False, "n_trials": n}}, now):
                    out["closed"].append((p["id"], "gate_now"))
                continue
            acc = proposal_account(p)
            if kind == "copy" and isinstance(acc, dict) and isinstance(acc.get("parent"), str):
                f = parent_facts(ctx.paper_ro, acc["parent"])
                if f is not None and (not f["exists"] or f["kind"] != "strategy" or f["bust"]):
                    why = "원본 계좌가 파산해" if f["bust"] and f["exists"] else "원본 계좌가 paper3에 없어"
                    if _close(conn, p, f"제안 #{p['id']}: {why} 복제하지 않고 코드가 거절로 닫았습니다.",
                              {"why": "parent_bust" if f["bust"] and f["exists"] else "parent_missing"}, now):
                        out["closed"].append((p["id"], "parent"))
        out["orphans"] = _orphans(ctx, extras, now)
    except Exception as exc:  # noqa: BLE001  (housekeeping only: the meetings go on)
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        print(f"warning: extra-account housekeeping failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        out["error"] = type(exc).__name__
    return out


def _notify(ctx: Any, text: str) -> None:
    from ..notify import WARN
    try:
        ctx.notifier.send(WARN, text)
    except Exception:  # noqa: BLE001  delivery must not break the tick
        pass


def _orphans(ctx: Any, extras: list, now: int) -> list[str]:
    """Running extras whose proposal row is missing, has another time or content, or is not 'approved'."""
    conn = ctx.agents_conn
    found: dict = {}
    for e in extras:
        src = e["data"].get("source") if isinstance(e["data"].get("source"), dict) else {}
        pid = _int(src.get("proposal_id"))
        p = R.get_proposal(conn, pid) if pid is not None and 0 < pid < 2 ** 63 else None
        if p is None or p.get("ts") != src.get("proposal_ts"):
            why = "missing"
        elif running_account(conn, ctx.paper_ro, p, extras) is None:
            why = "other_content"
        elif p["status"] != "approved":
            why = p["status"]
        else:
            continue
        found[e["account_id"]] = {"proposal_id": pid, "why": why, "created_ts": e["created_ts"]}
        key = ORPHAN_CURSOR.format(aid=e["account_id"], created=e["created_ts"])
        if R.get_cursor(conn, key) is None:
            what = {"missing": "agents3.db에 그 제안이 없습니다(예전 백업으로 되살렸을 수 있음)",
                    "other_content": "같은 번호의 제안이 다른 내용입니다"}.get(why, f"그 제안이 지금 '{why}' 상태입니다")
            R.post(conn, _room_of(e), None, "extras", "code", None, "system",
                   f"⚠️ 추가 계좌 {label_of(e)} ({e['account_id']})는 제안 #{pid}로 시작해 돌고 있는데, {what}. "
                   "계좌는 규칙대로 계속 돕니다(바꾸거나 멈추지 않음). 대시보드에 '제안 상태와 달리 실행 중'으로 표시합니다.",
                   {"action": "extra_orphan", "account_id": e["account_id"], "proposal_id": pid, "why": why},
                   ts=now, commit=False)
            R.set_cursor(conn, key, now)
            _notify(ctx, f"[추가 계좌] {e['account_id']}: 제안 #{pid}와 맞지 않는 상태로 실행 중 ({why})")
    if R.get_cursor(conn, ORPHANS) != found:
        R.set_cursor(conn, ORPHANS, found)
    return sorted(found)
