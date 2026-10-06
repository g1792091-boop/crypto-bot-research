"""Disputes: who was right, graded by code (design #102 C; owners' doc: docs/agent-rooms.md '편 가르기와 누가 맞았나').

A strategy room with sides on (policy ``sides``, AGENTS_SIDES=1) has two fixed seats: the advocate (the strategy's own
specialist, ``spec_<S>``) defends the strategy, the attacker (one of ``ATTACKER_POOL``, dealt by code) looks for one flaw.
When the attacker disagrees it must name the test that settles it (``clean_settle``): a 5-year lab test of the room's
strategy (labtests templates, run through the shared test queue so it is counted in that room's ledger), or a forward
check that code grades on the next N closed trades (paper3, read-only). A team lead in the six review meetings may open
one dispute between two staff who disagreed in the meeting (``open_from_lead``).

Code grades every dispute (``grade_due``), never a model:
- lab: the pre-registered LAB CLAIM RULE (``lab_verdict``; not the copy gate): the attacker (the variant is better)
  wins only when period 1 and period 2 both improve with p < 0.05 (period 2 with >= 100 variant trades), period 3
  improves when it has >= 30 baseline trades, and for stop_atr the leverage-free return improves in periods 1 and 2;
  otherwise the advocate wins; no data or an error voids it;
- forward ``tag_gap``: the attacker wins when the mean ROE of the next N trades WITH the tag is below that of the
  trades WITHOUT it (each group >= 5 trades, else void);
- forward ``vs_flip``: the attacker ('no edge') wins when the strategy's mean ROE over its next N trades is at or below
  the coin flips' (RANDOM_1..3, same timeframes, same window; fewer than N/2 flip trades: void).
Every forward result also shows the coin-flip mirror (the same split on coin-flip trades), so luck is visible. A
forward check expires after 45 days.

Storage: the ``disputes`` table in agents3.db (``ensure``: CREATE TABLE IF NOT EXISTS from this non-frozen module; the
sides, the claim and the test of a row can never change, a final status can never change, and nothing is deleted).
The seats are written once to the cursor ``disputes:sides``.

The shared test queue (paperbot/agents/labintake.py) runs a lab dispute's test (source 'meeting', ``_enqueue``; its daily
budget ``dispute_tests_per_day`` and room gap ``dispute_room_gap_days`` are the queue's, labintake.run_due).
``_labintake`` imports it lazily: without it (an install from before the queue) a lab dispute stays 'queued' with no
intake row and a later tick hands it over (``hand_over``).
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from typing import Any, Iterable, Optional

from ..config import V3_TRADE_TFS
from . import rooms_db as R
from .roster3 import STRATEGY_KO

DAY_MS = 86_400_000
TFS = V3_TRADE_TFS                 # 15m / 30m / 1h / 4h (no 5m: v4 has no 5m parent account)
ATTACKER_POOL = ("devils_advocate", "entry_timing", "exit_timing", "whatif")   # all sonnet, all strategy-room roles
EXPERT_ATTACKERS = ("entry_timing", "exit_timing", "whatif")
SIDES_CURSOR = "disputes:sides"
SOURCES = ("strategy_room", "team_lead")
KINDS = ("lab", "forward")
STATUSES = ("queued", "open", "settled", "void", "expired", "conceded", "duplicate")
PENDING = ("queued", "open")
FINAL = ("settled", "void", "expired", "conceded", "duplicate")
LAB_TEMPLATES = ("stop_atr", "lock_start", "skip_tag")       # timeframe_only is descriptive: it settles nothing
LAB_PARAM = {"stop_atr": "k", "lock_start": "first_lock", "skip_tag": "tag"}   # the template's one value
FORWARD_CHECKS = ("tag_gap", "vs_flip")
FORWARD_MIN_N, FORWARD_MAX_N = 20, 60
FORWARD_SPAN_DAYS = 14             # N = the strategy's closed trades per day x 14, clamped to 20-60
FORWARD_MAX_WAIT_DAYS = 30         # 20 trades must fit in 30 days, else the strategy gets lab checks only
EXPIRE_DAYS = 45                   # a pending dispute is closed as expired after this
HANDOVER_DAYS = 14                 # a lab dispute that never reached the shared test queue expires after this
GROUP_MIN = 5                      # tag_gap: trades with and without the tag, each at least this many
SMALL = 10                         # the board says "표본 적음" under this many settled disputes
LAB_ALPHA = 0.05                   # the claim rule's p (fixed, not the copy gate's Bonferroni p)
P2_MIN_TRADES = 100
P3_MIN_BASE = 30
FLIPS = tuple(f"RANDOM_{k}" for k in (1, 2, 3))
# what the shared queue's latest event means for a lab dispute waiting on it
INTAKE_DONE = ("tested", "reused")
INTAKE_VOID = ("duplicate", "not_counted", "bad_spec", "refused", "declined", "error")
INTAKE_EXPIRED = ("expired",)

STATUS_KO = {"queued": "5년 시험 대기", "open": "앞으로 거래로 확인 중", "settled": "결론", "void": "무효(가릴 수 없음)",
             "expired": "기한 지남", "conceded": "편드는 직원이 인정", "duplicate": "이미 가린 내용(점수 없음)"}
KIND_KO = {"lab": "5년 시험", "forward": "앞으로 N건"}
SOURCE_KO = {"strategy_room": "매매법 방", "team_lead": "팀장"}
WINNER_KO = {"a": "공격 쪽 맞음", "b": "편드는 쪽 맞음"}
BASE_NOTE_KO = ("5년 시험에서 바꾼 규칙이 실제로 나아진 경우는 드뭅니다(지난 연구 2,000개 조합 통과 0개). 그래서 5년 시험 "
                "다툼은 편드는 쪽이 거의 늘 이깁니다. 점수는 그 편의 기준 비율, 동전 50%와 함께 보세요. 앞으로 N건 확인은 "
                "20~60건이라 동전 던지기에 가깝고, 규칙을 바꾸는 근거가 되지 않습니다. 한 모델이 모든 역할을 맡으므로 사람의 "
                "실력 점수가 아닙니다.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    round_id INTEGER,
    strategy TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('strategy_room', 'team_lead')),
    claim_ko TEXT NOT NULL,
    side_a TEXT NOT NULL,              -- the attacker: the claim is true
    side_b TEXT NOT NULL,              -- the advocate: the claim is not true
    kind TEXT NOT NULL CHECK (kind IN ('lab', 'forward')),
    spec TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'open', 'settled', 'void', 'expired', 'conceded', 'duplicate')),
    intake_id INTEGER,
    trial_id INTEGER,
    winner TEXT CHECK (winner IN ('a', 'b') OR winner IS NULL),
    outcome TEXT,
    settled_ts INTEGER,
    data TEXT                          -- confidence, base_trade_id, n, dup_of, refusal, mirror ...
);
CREATE INDEX IF NOT EXISTS disputes_status ON disputes (status, id);
CREATE INDEX IF NOT EXISTS disputes_strategy ON disputes (strategy, id);
CREATE INDEX IF NOT EXISTS disputes_side_a ON disputes (side_a);
CREATE INDEX IF NOT EXISTS disputes_side_b ON disputes (side_b);
CREATE TRIGGER IF NOT EXISTS disputes_fixed_u BEFORE UPDATE OF ts, room_id, round_id, strategy, source, claim_ko,
    side_a, side_b, kind, spec, spec_hash ON disputes
BEGIN SELECT RAISE(ABORT, 'disputes: the sides, the claim and the test of a dispute are fixed'); END;
CREATE TRIGGER IF NOT EXISTS disputes_final_u BEFORE UPDATE ON disputes
WHEN OLD.status IN ('settled', 'void', 'expired', 'conceded', 'duplicate')
BEGIN SELECT RAISE(ABORT, 'disputes: a final status is never changed'); END;
CREATE TRIGGER IF NOT EXISTS disputes_no_delete BEFORE DELETE ON disputes
BEGIN SELECT RAISE(ABORT, 'disputes are never deleted'); END;
"""


def ensure(conn: sqlite3.Connection) -> None:
    """Create the table on agents3.db when it is missing (the tick's connection, the only writer)."""
    conn.executescript(SCHEMA)
    conn.commit()


# ---------------------------------------------------------------- small helpers
def _loads(s: Any) -> Any:
    if s is None or isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mean(xs: list) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _pp(x: Optional[float]) -> str:
    return "없음" if x is None else f"{x * 100:+.2f}%p"


def _pct(x: Optional[float]) -> str:
    return "없음" if x is None else f"{x * 100:+.2f}%"


def _pv(p: Optional[float]) -> str:
    return "없음" if p is None else f"{p:.3g}"


def name(role: str) -> str:
    return R.role_name(role) if role else ""


def _table_ok(conn: Optional[sqlite3.Connection], table: str = "disputes") -> bool:
    if conn is None:
        return False
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None
    except sqlite3.Error:
        return False


def _rows(conn: Optional[sqlite3.Connection], where: str = "1=1", args: tuple = (), limit: int = 5000,
          order: str = "id DESC") -> list[dict]:
    if not _table_ok(conn):
        return []
    try:
        rows = R._dicts(conn.execute(f"SELECT * FROM disputes WHERE {where} ORDER BY {order} LIMIT ?",
                                     (*args, max(1, int(limit)))))
    except sqlite3.Error:
        return []
    for r in rows:
        r["spec"] = _loads(r.get("spec")) or {}
        r["data"] = _loads(r.get("data")) or {}
    return rows


def get(conn: Optional[sqlite3.Connection], dispute_id: int) -> Optional[dict]:
    rows = _rows(conn, "id = ?", (int(dispute_id),), 1)
    return rows[0] if rows else None


# ---------------------------------------------------------------- seats
def default_sides(version: int = 1) -> dict:
    """Each of the 36 strategies' advocate (its own specialist) and attacker (the pool, dealt in roster order; version 2
    and later shift the deal by one seat, so a checkpoint re-deal gives every strategy a new attacker)."""
    names = list(STRATEGY_KO)
    return {s: {"advocate": f"spec_{s}", "attacker": ATTACKER_POOL[(i + version - 1) % len(ATTACKER_POOL)]}
            for i, s in enumerate(names)}


def sides_view(conn: Optional[sqlite3.Connection]) -> dict:
    """The seats in force (read-only): the cursor when it was written, else version 1 as it would be written."""
    v = None
    if conn is not None:
        try:
            v = R.get_cursor(conn, SIDES_CURSOR)
        except sqlite3.Error:
            v = None
    if isinstance(v, dict) and isinstance(v.get("sides"), dict):
        return v
    return {"version": 1, "since": None, "pool": list(ATTACKER_POOL), "sides": default_sides(1)}


def seats_written(conn: Optional[sqlite3.Connection]) -> Optional[dict]:
    """The seats cursor when the agents tick has written it (it does only with sides on), else None: the dashboard
    shows a room's sides only then (a feature that is off is not shown)."""
    if conn is None:
        return None
    try:
        v = R.get_cursor(conn, SIDES_CURSOR)
    except sqlite3.Error:
        return None
    return v if isinstance(v, dict) and isinstance(v.get("sides"), dict) else None


def room_seats(conn: Optional[sqlite3.Connection], strategy: str) -> Optional[dict]:
    """{advocate, attacker} of one strategy with each seat's record (dashboard), or None while sides were never on."""
    v = seats_written(conn)
    seat = ((v or {}).get("sides") or {}).get(strategy)
    if not seat:
        return None
    b = board(conn, turns=False)

    def one(role: str, side: str) -> dict:
        r = role_record(b, role)
        return {"role": role, "name": name(role),
                "record": {k: r[k] for k in ("won", "lost", "settled", "pending", "conceded", "expected", "small")},
                "record_side": r["as_advocate" if side == "advocate" else "as_attacker"]}
    return {"version": v.get("version", 1), "since": v.get("since"), "advocate": one(seat["advocate"], "advocate"),
            "attacker": one(seat["attacker"], "attacker"), "base_rates": b["base_rates"], "coin_flip": 0.5}


def sides(conn: sqlite3.Connection, now_ms: int) -> dict:
    """The seats, written once to the cursor ``disputes:sides`` (the tick's writer connection)."""
    v = R.get_cursor(conn, SIDES_CURSOR)
    if isinstance(v, dict) and isinstance(v.get("sides"), dict):
        return v
    v = {"version": 1, "since": int(now_ms), "pool": list(ATTACKER_POOL), "sides": default_sides(1)}
    R.set_cursor(conn, SIDES_CURSOR, v)
    return v


def redeal(conn: sqlite3.Connection, now_ms: int) -> dict:
    """A new deal of the attackers (only at a checkpoint, by hand): version + 1. Every stored dispute keeps the roles
    it was opened with."""
    old = sides(conn, now_ms)
    ver = int(old.get("version") or 1) + 1
    v = {"version": ver, "since": int(now_ms), "pool": list(ATTACKER_POOL), "sides": default_sides(ver)}
    R.set_cursor(conn, SIDES_CURSOR, v)
    return v


def attacker_of(strategy: str, conn: Optional[sqlite3.Connection] = None) -> str:
    seat = (sides_view(conn).get("sides") or {}).get(strategy) or {}
    if seat.get("attacker") in ATTACKER_POOL:
        return seat["attacker"]
    names = list(STRATEGY_KO)
    return ATTACKER_POOL[(names.index(strategy) if strategy in names else 0) % len(ATTACKER_POOL)]


def advocate_of(strategy: str) -> str:
    return f"spec_{strategy}"


# ---------------------------------------------------------------- the settle (the test that decides a dispute)
def _lab_names() -> tuple:
    from .actions import lab_strategies
    return tuple(lab_strategies())


def _skip_tags() -> list:
    from .actions import templates
    return list((templates().get("skip_tag") or {}).get("tag") or [])


def _account_ids(strategy: str, timeframe: Optional[str]) -> list[str]:
    return [f"{strategy}@{tf}" for tf in ([timeframe] if timeframe else TFS)]


def forward_info(paper_ro: Optional[sqlite3.Connection], strategy: str, timeframe: Optional[str],
                 now_ms: int) -> dict:
    """How many trades a forward check of this strategy (and timeframe) waits for: N = closed trades per day over the
    last 14 days (or since the run's start when it is younger) x 14, clamped to 20-60. ``ok`` is False when 20 trades
    would take more than 30 days (rare signals: lab checks only) or paper3 cannot be read."""
    out = {"timeframe": timeframe, "per_day": None, "n": None, "ok": False, "why": ""}
    if paper_ro is None:
        out["why"] = "paper3를 읽지 못해 앞으로 확인을 정할 수 없음"
        return out
    from .triggers import run_start
    start = run_start(paper_ro)
    lo = int(now_ms) - FORWARD_SPAN_DAYS * DAY_MS
    if start is not None:
        lo = max(lo, int(start))
    days = max(1.0, (int(now_ms) - lo) / DAY_MS)
    ids = _account_ids(strategy, timeframe)
    try:
        n = int(paper_ro.execute(f"SELECT COUNT(*) FROM trades WHERE account_id IN ({','.join('?' * len(ids))}) "
                                 "AND exit_time >= ? AND exit_time <= ?", (*ids, lo, int(now_ms))).fetchone()[0])
    except sqlite3.Error:
        out["why"] = "paper3를 읽지 못해 앞으로 확인을 정할 수 없음"
        return out
    per_day = n / days
    out["per_day"] = round(per_day, 3)
    if per_day * FORWARD_MAX_WAIT_DAYS < FORWARD_MIN_N:
        out["why"] = (f"거래가 드물어(하루 {per_day:.2f}건) {FORWARD_MIN_N}건이 {FORWARD_MAX_WAIT_DAYS}일 안에 모이지 않음: "
                      "5년 시험으로만 가릴 수 있음")
        return out
    out["n"] = int(min(FORWARD_MAX_N, max(FORWARD_MIN_N, math.ceil(per_day * FORWARD_SPAN_DAYS))))
    out["ok"] = True
    return out


def forward_table(paper_ro: Optional[sqlite3.Connection], strategy: str, now_ms: int) -> dict:
    """``forward_info`` for all four timeframes together ('all') and each one: the room's packet carries it, so the
    attacker's answer is checked against code numbers (``clean_settle(..., forward=...)``). Compact (tokens): ok, n,
    per_day, and a short why when a forward check is not possible."""
    out = {}
    for tf in (None, *TFS):
        f = forward_info(paper_ro, strategy, tf, now_ms)
        row = {"ok": f["ok"], "n": f["n"], "per_day": f["per_day"]}
        if not f["ok"]:
            row["why"] = ("paper3를 읽지 못함" if f["per_day"] is None
                          else f"거래 드묾(하루 {f['per_day']:.2f}건): 5년 시험만")
        out[tf or "all"] = row
    return out


def clean_settle(raw: Any, strategy: Optional[str], paper_ro: Optional[sqlite3.Connection] = None,
                 now_ms: Optional[int] = None, forward: Optional[dict] = None) -> tuple[Optional[dict], str]:
    """The test a model named to settle its dispute, in code's canonical form, or (None, why in Korean).

    lab:     {"kind": "lab", "test": {"template": stop_atr|lock_start|skip_tag, "timeframe": 15m-4h, <value>}}
             checked with actions.validate (the room's own request_test form); 5m, timeframe_only and any name
             outside the 36 are refused.
    forward: {"kind": "forward", "check": "tag_gap"|"vs_flip", "tag": <skip tag> (tag_gap only), "timeframe": tf|null}
             with N from ``forward_info`` (``forward``: the packet's precomputed table, else paper3)."""
    if not isinstance(raw, dict):
        return None, "가릴 시험(settle)이 없음"
    if not isinstance(strategy, str) or strategy not in _lab_names():
        return None, "잠긴 매매법 36개만 다툼을 시험으로 가릴 수 있음"
    kind = raw.get("kind")
    tf = raw.get("timeframe")
    if kind == "lab":
        test = dict(raw.get("test") if isinstance(raw.get("test"), dict) else
                    {k: v for k, v in raw.items() if k != "kind"})
        param = LAB_PARAM.get(test.get("template"))
        if param and param not in test and "value" in test:      # {"template", "timeframe", "value"} (the prompt's form)
            test[param] = test.pop("value")
        test.pop("value", None)
        if test.get("template") not in LAB_TEMPLATES:
            return None, f"5년 시험 종류는 {', '.join(LAB_TEMPLATES)} 중 하나(설명용 시험은 다툼을 가리지 못함)"
        if test.get("timeframe") not in TFS:
            return None, f"5년 시험 시간봉은 {'·'.join(TFS)} 중 하나(5분봉 없음)"
        if test.get("strategy") not in (None, "", strategy):
            return None, "이 방의 매매법만 시험할 수 있음"
        from .actions import validate
        clean, problems = validate({"action": "request_test", "test": {**test, "strategy": strategy}},
                                   strategy=strategy, allow=("request_test",))
        if clean.get("action") != "request_test":
            return None, "허용된 5년 시험 형식이 아님: " + ("; ".join(str(p) for p in problems)[:200] or "형식 오류")
        spec = dict(clean["test"])
        if spec.get("timeframe") not in TFS or spec.get("template") not in LAB_TEMPLATES:
            return None, "허용된 5년 시험 형식이 아님"
        return {"kind": "lab", "test": spec}, ""
    if kind == "forward":
        check = raw.get("check")
        if check not in FORWARD_CHECKS:
            return None, f"앞으로 확인(check)은 {' 또는 '.join(FORWARD_CHECKS)}"
        if tf in ("", "all"):
            tf = None
        if tf is not None and tf not in TFS:
            return None, f"시간봉은 {'·'.join(TFS)} 또는 null"
        out: dict = {"kind": "forward", "check": check, "timeframe": tf}
        if check == "tag_gap":
            tag = raw.get("tag").strip() if isinstance(raw.get("tag"), str) else None
            if tag not in _skip_tags():
                return None, "tag는 진입 특징 이름 중 하나(" + ", ".join(_skip_tags()) + ")"
            out["tag"] = tag
        info = (forward or {}).get(tf or "all") if isinstance(forward, dict) else None
        if not isinstance(info, dict):
            info = forward_info(paper_ro, strategy, tf, int(now_ms or 0)) if paper_ro is not None and now_ms else None
        if not isinstance(info, dict) or not info.get("ok") or not info.get("n"):
            return None, (info or {}).get("why") or "앞으로 확인할 거래 수를 정할 수 없음"
        out["n"] = int(info["n"])
        return out, ""
    return None, "settle.kind는 lab 또는 forward"


def identity(spec: dict) -> dict:
    """What makes two disputes the same claim (N is left out: the same check named another day is the same claim)."""
    if spec.get("kind") == "lab":
        return {"kind": "lab", "test": spec.get("test")}
    return {"kind": "forward", "check": spec.get("check"), "tag": spec.get("tag"), "timeframe": spec.get("timeframe")}


def _test_ko(test: dict) -> str:
    from .actions import lab_module
    lab = lab_module()
    fn = getattr(lab, "describe_ko", None) if lab is not None else None
    if fn is not None:
        try:
            return str(fn(test))
        except (KeyError, TypeError, ValueError):
            pass
    vals = ", ".join(f"{k}={v}" for k, v in test.items() if k not in ("template", "strategy"))
    return f"{test.get('template')} ({vals})"


def settle_ko(spec: Optional[dict], strategy: Optional[str] = None) -> str:
    """The settle in plain Korean (code text)."""
    if not isinstance(spec, dict):
        return "없음"
    if spec.get("kind") == "lab":
        return "5년 시험 · " + _test_ko(spec.get("test") or {})
    tf = spec.get("timeframe")
    where = f"{tf} " if tf else ""
    n = spec.get("n")
    if spec.get("check") == "tag_gap":
        return f"앞으로 {where}거래 {n}건: '{spec.get('tag')}' 붙은 거래가 안 붙은 거래보다 나쁜지"
    return f"앞으로 {where}거래 {n}건: 같은 기간 동전 계좌보다 나은지"


# ---------------------------------------------------------------- the shared test queue (labintake)
def _labintake():
    """paperbot.agents.labintake when it is installed (with enqueue), else None: the dispute waits as 'queued'."""
    try:
        from . import labintake as LI  # noqa: F401  (lazy: an install from before the queue has none)
    except ImportError:
        return None
    return LI if callable(getattr(LI, "enqueue", None)) else None


def _source_ref(dispute_id: int) -> str:
    return f"dispute:{int(dispute_id)}"


def _intake_id(conn: sqlite3.Connection, dispute_id: int) -> Optional[int]:
    if not _table_ok(conn, "lab_intake"):
        return None
    try:
        r = conn.execute("SELECT id FROM lab_intake WHERE source = 'meeting' AND source_ref = ?",
                         (_source_ref(dispute_id),)).fetchone()
    except sqlite3.Error:
        return None
    return int(r[0]) if r else None


def _enqueue(conn: sqlite3.Connection, d: dict, now_ms: int) -> tuple[Optional[int], str]:
    """Hand a lab dispute's test to the shared queue: source 'meeting', ref 'dispute:<id>', engine 'labtest', the
    strategy's own ledger (strat:<S>). Returns (intake id or None, why not in Korean)."""
    LI = _labintake()
    if LI is None:
        return None, "시험 대기열(labintake)이 아직 설치되지 않음: 다음 차례에 다시 넘김"
    test = (d.get("spec") or {}).get("test") or {}
    meta = {"dispute_id": d["id"], "by_role": d["side_a"], "advocate": d["side_b"], "claim_ko": d["claim_ko"][:300],
            "round_id": d.get("round_id"), "origin_room": d.get("room_id"), "fidelity": "exact",
            "conceded": d.get("status") == "conceded" or bool((d.get("data") or {}).get("conceded"))}
    try:
        if callable(getattr(LI, "ensure", None)):
            LI.ensure(conn)
        LI.enqueue(conn, source="meeting", source_ref=_source_ref(d["id"]), engine="labtest", spec=test,
                   strategy=d["strategy"], idea_ko=d["claim_ko"][:300], meta=meta, now=int(now_ms))
    except Exception as exc:  # noqa: BLE001  (a queue error leaves the dispute queued; tried again next tick)
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return None, f"시험 대기열에 넣지 못함({type(exc).__name__}): 다음 차례에 다시 넘김"
    iid = _intake_id(conn, d["id"])
    return iid, ("" if iid is not None else "시험 대기열에 줄이 생기지 않음: 다음 차례에 다시 넘김")


def _update(conn: sqlite3.Connection, dispute_id: int, **cols: Any) -> bool:
    """Change only the columns a dispute may change (never the sides, the claim or the test), only while pending."""
    allowed = {"status", "intake_id", "trial_id", "winner", "outcome", "settled_ts", "data"}
    sets = {k: v for k, v in cols.items() if k in allowed}
    if not sets:
        return False
    if "data" in sets:
        sets["data"] = R._dumps(sets["data"])
    cur = conn.execute(f"UPDATE disputes SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ? AND status IN "
                       "('queued', 'open')", (*sets.values(), int(dispute_id)))
    conn.commit()
    return cur.rowcount > 0


def hand_over(conn: sqlite3.Connection, now_ms: int) -> int:
    """Lab disputes still 'queued' without an intake row go to the shared queue now that it exists (idempotent: the
    queue keys on source_ref). A conceded lab dispute whose test could not be queued when it was written (no queue
    yet) is handed over too, within ``HANDOVER_DAYS``: its row is final, so only the queue gets the test (found by
    its source_ref). Returns how many were handed over."""
    if not _table_ok(conn) or _labintake() is None:
        return 0
    n = 0
    for d in _rows(conn, "status = 'queued' AND kind = 'lab' AND intake_id IS NULL", (), 50, "id"):
        iid, _why = _enqueue(conn, d, now_ms)
        if iid is not None and _update(conn, d["id"], intake_id=iid):
            n += 1
    for d in _rows(conn, "status = 'conceded' AND kind = 'lab' AND intake_id IS NULL AND ts >= ?",
                   (int(now_ms) - HANDOVER_DAYS * DAY_MS,), 50, "id"):
        if _intake_id(conn, d["id"]) is None and _enqueue(conn, d, now_ms)[0] is not None:
            n += 1
    return n


# ---------------------------------------------------------------- open
def open_dispute(conn: sqlite3.Connection, *, room_id: str, round_id: Optional[int], strategy: str, source: str,
                 claim_ko: str, side_a: str, side_b: str, settle: dict, now_ms: int,
                 confidence: Optional[int] = None, conceded: bool = False,
                 paper_ro: Optional[sqlite3.Connection] = None) -> dict:
    """Write one dispute (``settle`` from ``clean_settle``). Returns {id, status, text_ko, ...}:
    - conceded: the advocate gave in (final 'conceded', never scored); a lab test is still handed to the queue as the
      room's own test;
    - duplicate: the same claim (strategy, kind and identity hash) is already settled or pending, or the 5-year test
      already sits in this strategy's ledger (its old result is shown, never scored);
    - lab: 'queued' and handed to the shared test queue (run after the meetings, in strat:<S>'s own ledger);
    - forward: 'open' from now (the base trade id is paper3's newest trade, for the record)."""
    if source not in SOURCES:
        raise ValueError(f"unknown dispute source: {source!r}")
    kind = settle.get("kind")
    if kind not in KINDS:
        raise ValueError("settle must come from clean_settle")
    ensure(conn)
    spec = dict(settle)
    shash = R.spec_hash(identity(spec))
    claim = " ".join(R.clean_text(str(claim_ko or "")).split())[:300] or settle_ko(spec, strategy)
    data: dict = {"confidence": confidence if isinstance(confidence, int) and 1 <= confidence <= 3 else None}
    status = "conceded" if conceded else ("queued" if kind == "lab" else "open")
    dup = None
    if not conceded:
        same = _rows(conn, "strategy = ? AND kind = ? AND spec_hash = ? AND status IN "
                     "('settled', 'queued', 'open')", (strategy, kind, shash), 1)
        if same:
            dup = same[0]
            data.update(dup_of=dup["id"], dup_status=dup["status"], dup_winner=dup.get("winner"),
                        dup_outcome=dup.get("outcome"))
            status = "duplicate"
        elif kind == "lab":
            old = R.find_trial(conn, strategy, spec["test"], kind="test")
            st = ((old or {}).get("result") or {}).get("status")
            if old is not None and st in ("passed", "failed", "described"):
                data.update(dup_trial=int(old["id"]), dup_trial_status=st)
                status = "duplicate"
    if kind == "forward" and paper_ro is not None:
        try:
            r = paper_ro.execute("SELECT MAX(id) FROM trades").fetchone()
            data["base_trade_id"] = int(r[0]) if r and r[0] is not None else 0
        except sqlite3.Error:
            data["base_trade_id"] = None
    if kind == "forward":
        data["n"] = spec.get("n")
    if conceded:
        data["conceded"] = True
    cur = conn.execute(
        "INSERT INTO disputes (ts, room_id, round_id, strategy, source, claim_ko, side_a, side_b, kind, spec, spec_hash, "
        "status, data, settled_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (int(now_ms), room_id, round_id, strategy, source, claim, side_a, side_b, kind, R._dumps(spec), shash,
         "queued" if (conceded and kind == "lab") else status, R._dumps(data),
         int(now_ms) if status in ("conceded", "duplicate") else None))     # final at once: it ended now
    conn.commit()
    did = int(cur.lastrowid)
    d = get(conn, did) or {}
    out = {"id": did, "status": status, "kind": kind, "intake_id": None, "settle_ko": settle_ko(spec, strategy),
           "side_a": side_a, "side_b": side_b, "claim_ko": claim}
    if kind == "lab" and status in ("queued", "conceded"):
        iid, why = _enqueue(conn, d, now_ms)
        out["intake_id"] = iid
        if conceded:
            # written 'queued' only so the queue row could be attached; now final
            conn.execute("UPDATE disputes SET status = 'conceded', intake_id = ? WHERE id = ? AND status = 'queued'",
                         (iid, did))
            conn.commit()
        elif iid is not None:
            _update(conn, did, intake_id=iid)
        else:
            out["handover_ko"] = why
    out["text_ko"] = open_text(out, strategy, dup_data=data if status == "duplicate" else None)
    return out


def open_text(o: dict, strategy: str, dup_data: Optional[dict] = None) -> str:
    """The room's code line for a new dispute."""
    who = f"공격 {name(o['side_a'])} vs 편 {name(o['side_b'])}"
    if o["status"] == "conceded":
        tail = " · 5년 시험은 방의 시험으로 대기열에 넣음(점수 없음)" if o["kind"] == "lab" and o.get("intake_id") else ""
        return f"⚔️ 다툼 #{o['id']}: {who} · 편드는 직원이 인정해 점수 없이 끝냄{tail}"
    if o["status"] == "duplicate":
        dd = dup_data or {}
        if dd.get("dup_trial"):
            return (f"⚔️ 다툼 #{o['id']}: {who} · 이미 한 5년 시험(시험 #{dd['dup_trial']})이라 점수 없이 이전 결과를 "
                    "보여 줍니다")
        what = WINNER_KO.get(dd.get("dup_winner") or "", STATUS_KO.get(dd.get("dup_status") or "", ""))
        return f"⚔️ 다툼 #{o['id']}: {who} · 같은 주장(다툼 #{dd.get('dup_of')}, {what})이 있어 점수 없이 그 결과를 따릅니다"
    if o["kind"] == "lab":
        wait = "5년 시험 대기(회의 뒤 코드가 이 방 장부로 돌림)" if o.get("intake_id") else \
            "5년 시험 대기(" + (o.get("handover_ko") or "다음 차례에 대기열로 넘김") + ")"
        return f"⚔️ 다툼 #{o['id']} 열림: {who} · {o['settle_ko']} · {wait}"
    return f"⚔️ 다툼 #{o['id']} 열림: {who} · {o['settle_ko']} · 코드가 거래가 차면 채점"


# ---------------------------------------------------------------- the team lead's dispute
def clean_lead_dispute(raw: Any) -> Optional[dict]:
    """The lead's ``dispute`` field in shape only (whether it may open is ``open_from_lead``'s job)."""
    if not isinstance(raw, dict):
        return None
    out = {k: (" ".join(R.clean_text(raw[k].strip()[:300]).split()) if isinstance(raw.get(k), str) else None)
           for k in ("strategy", "side_a", "side_b", "claim")}
    out["settle"] = raw.get("settle") if isinstance(raw.get("settle"), dict) else None
    return out if any(out.values()) else None


def _spoke(this_round: dict) -> dict:
    """{role: its answer} of everyone who spoke in this meeting (team turns: 'team:<role>', others by turn)."""
    out: dict = {}
    for v in (this_round or {}).values():
        if isinstance(v, dict) and isinstance(v.get("role"), str):
            out.setdefault(v["role"], v)
    return out


def open_from_lead(conn: sqlite3.Connection, raw: Any, this_round: dict, *, room_id: str, round_id: Optional[int],
                   now_ms: int, paper_ro: Optional[sqlite3.Connection] = None) -> dict:
    """A team lead's dispute (six review meetings): only between two staff who BOTH spoke in this meeting, one of whom
    answered the other with stance 'disagree' (this_round.responds_to), about one of the 36, with a valid settle.
    One per meeting (the lead has one field). Returns {ok, ...open_dispute} or {ok: False, why_ko}."""
    d = clean_lead_dispute(raw)
    if d is None:
        return {"ok": False, "why_ko": "다툼 내용이 없음"}
    s, a, b = d.get("strategy"), d.get("side_a"), d.get("side_b")
    if s not in _lab_names():
        return {"ok": False, "why_ko": "잠긴 매매법 36개 중 하나가 아님"}
    spoke = _spoke(this_round)
    if not a or not b or a == b or a not in spoke or b not in spoke:
        return {"ok": False, "why_ko": "두 직원이 모두 이번 회의에서 말하지 않음"}

    def disagreed(x: str, y: str) -> bool:
        rt = (spoke.get(x) or {}).get("responds_to")
        return isinstance(rt, dict) and rt.get("role") == y and rt.get("stance") == "disagree"
    if not (disagreed(a, b) or disagreed(b, a)):
        return {"ok": False, "why_ko": "회의에서 한 사람이 다른 사람에게 '반대'로 답한 기록이 없음"}
    settle, why = clean_settle(d.get("settle"), s, paper_ro, now_ms)
    if settle is None:
        return {"ok": False, "why_ko": why}
    o = open_dispute(conn, room_id=room_id, round_id=round_id, strategy=s, source="team_lead",
                     claim_ko=d.get("claim") or "", side_a=a, side_b=b, settle=settle, now_ms=now_ms, paper_ro=paper_ro)
    return {"ok": True, **o}


# ---------------------------------------------------------------- grading: lab
def lab_verdict(trial: Optional[dict]) -> dict:
    """The LAB CLAIM RULE on a stored test (the 'test' trial's latest result), pre-registered in docs/agent-rooms.md.
    {status settled|void, winner a|b|None, line_ko, numbers}. The copy gate (Bonferroni over the room's tests) is a
    separate answer and is quoted next to it, never mixed in."""
    res = (trial or {}).get("result") or {}
    st = res.get("status")
    body = res.get("result") if isinstance(res.get("result"), dict) else {}
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    if st not in ("passed", "failed") or not result.get("ok"):
        why = {"no_data": "시험 자료가 없어", "error": "시험 오류로", "described": "설명용 시험이라"}.get(st, "시험 결과가 없어")
        return {"status": "void", "winner": None, "line_ko": f"{why} 가릴 수 없음(무효)", "numbers": {}}
    P = result.get("periods") if isinstance(result.get("periods"), dict) else {}
    if not (isinstance(P.get("1"), dict) and isinstance(P.get("2"), dict)):
        # a finished run without its period table cannot answer the claim: void, never a default win for the advocate
        return {"status": "void", "winner": None, "line_ko": "시험 결과에 1·2기간 숫자가 없어 가릴 수 없음(무효)",
                "numbers": {}}
    p1, p2, p3 = (P.get(k) if isinstance(P.get(k), dict) else {} for k in ("1", "2", "3"))

    def num(row: dict, *keys: str) -> Optional[float]:
        x: Any = row
        for k in keys:
            x = x.get(k) if isinstance(x, dict) else None
        return _f(x)
    d1, pv1, d2, pv2 = num(p1, "diff"), num(p1, "p"), num(p2, "diff"), num(p2, "p")
    nv2 = int(num(p2, "variant", "trades") or 0)
    checks = {"p1": d1 is not None and pv1 is not None and d1 > 0 and pv1 < LAB_ALPHA,
              "p2": d2 is not None and pv2 is not None and d2 > 0 and pv2 < LAB_ALPHA and nv2 >= P2_MIN_TRADES}
    nb3 = int(num(p3, "baseline", "trades") or 0)
    d3 = num(p3, "diff")
    if p3.get("available") and nb3 >= P3_MIN_BASE:
        checks["p3"] = d3 is not None and d3 > 0
    tmpl = (result.get("template") or (trial or {}).get("spec", {}).get("template"))
    if tmpl == "stop_atr":
        n1, n2 = num(p1, "diff_notional"), num(p2, "diff_notional")
        checks["notional"] = n1 is not None and n2 is not None and n1 > 0 and n2 > 0
    won = all(checks.values())
    gate = body.get("gate") if isinstance(body.get("gate"), dict) else {}
    n = body.get("n_trials") or gate.get("n_trials")
    gate_ko = ("복제 관문: " + ("통과" if gate.get("pass") is True else "불통과")
               + (f"(이 방 시험 {int(n)}번째, 기준 p<{LAB_ALPHA / max(1, int(n)):.2g})" if n else "")
               + (" · 복제 계좌는 회의에서 따로 제안하고 두 분 확인이 필요" if gate.get("pass") is True else ""))
    nums = f"1기간 {_pp(d1)}, p={_pv(pv1)} · 2기간 {_pp(d2)}, p={_pv(pv2)}"
    return {"status": "settled", "winner": "a" if won else "b", "checks": checks,
            "numbers": {"d1": d1, "p1": pv1, "d2": d2, "p2": pv2, "n_variant_2": nv2, "d3": d3, "n_base_3": nb3},
            "gate_pass": gate.get("pass") is True, "n_trials": n,
            "line_ko": f"{'공격하는 직원' if won else '편드는 직원'} 맞음({nums}) · {gate_ko}"}


def _intake_last(conn: sqlite3.Connection, intake_id: Optional[int]) -> Optional[dict]:
    if intake_id is None or not _table_ok(conn, "lab_intake_events"):
        return None
    try:
        r = conn.execute("SELECT status, trial_id, detail, ts FROM lab_intake_events WHERE intake_id = ? "
                         "ORDER BY id DESC LIMIT 1", (int(intake_id),)).fetchone()
    except sqlite3.Error:
        return None
    if r is None:
        return None
    return {"status": r[0], "trial_id": r[1], "detail": _loads(r[2]), "ts": r[3]}


def _lab_trial(conn: sqlite3.Connection, d: dict) -> tuple[Optional[dict], Optional[dict]]:
    """(the test trial that settles this lab dispute, the queue's latest event): the queue's tested/reused trial, else
    the same test in the strategy's ledger made after the dispute opened (e.g. the meeting's own request_test)."""
    ev = _intake_last(conn, d.get("intake_id"))
    tid = ev.get("trial_id") if ev and ev.get("status") in INTAKE_DONE else None
    if tid:
        t = R.get_trial(conn, int(tid))
        if t is not None:
            return t, ev
    test = (d.get("spec") or {}).get("test") or {}
    t = R.find_trial(conn, d["strategy"], test, kind="test")
    res = (t or {}).get("result") or {}
    # a result written after the dispute opened: a new trial, or an older number that could not run before (no data /
    # error keeps its number, request_test runs it again under it)
    if t is not None and res.get("status") in ("passed", "failed", "no_data", "error") and \
            int(res.get("ts") or 0) >= int(d["ts"]):
        return t, ev
    return None, ev


# ---------------------------------------------------------------- grading: forward
def _trades(paper_ro: sqlite3.Connection, ids: list[str], since_ms: int, until_ms: Optional[int] = None) -> list[tuple]:
    sql = (f"SELECT id, account_id, entry_time, exit_time, roe, data FROM trades WHERE account_id IN "
           f"({','.join('?' * len(ids))}) AND entry_time >= ?")
    args: list = [*ids, int(since_ms)]
    if until_ms is not None:
        sql += " AND exit_time <= ?"
        args.append(int(until_ms))
    return paper_ro.execute(sql + " ORDER BY exit_time, id", args).fetchall()


def _tagged(rows: list[tuple], tag: str, round_trip: float) -> tuple[list[float], list[float]]:
    from ..cards import card
    yes, no = [], []
    for _id, aid, _e, _x, roe, data in rows:
        try:
            t = json.loads(data)
            tags = card(aid, t, round_trip)["tags"]
        except (TypeError, ValueError, KeyError):
            continue
        r = _f(roe)
        if r is None:
            continue
        (yes if tag in tags else no).append(r)
    return yes, no


def forward_verdict(d: dict, paper_ro: Optional[sqlite3.Connection], now_ms: int, round_trip: float = 0.0) -> Optional[dict]:
    """None while the N trades are not in (and not expired); else {status settled|void|expired, winner, line_ko,
    mirror}. Trades are the strategy's first N closed trades ENTERED after the dispute (scorecard's rule)."""
    spec = d.get("spec") or {}
    n = int(spec.get("n") or (d.get("data") or {}).get("n") or FORWARD_MIN_N)
    S, tf, ts = d["strategy"], spec.get("timeframe"), int(d["ts"])
    expired = now_ms - ts > EXPIRE_DAYS * DAY_MS
    if paper_ro is None:
        return {"status": "expired", "winner": None, "line_ko": f"{EXPIRE_DAYS}일 안에 거래를 읽지 못함"} if expired else None
    from .triggers import run_start
    start = run_start(paper_ro)
    if start is not None and int(start) > ts:
        # paper3 was replaced by a new run after the dispute opened (a reset): its trades are another experiment's
        return {"status": "void", "winner": None,
                "line_ko": "다툼을 연 뒤 모의 실험이 새로 시작되어(새 계좌) 가릴 수 없음(무효)"}
    try:
        rows = _trades(paper_ro, _account_ids(S, tf), ts)
    except sqlite3.Error:
        return None
    if len(rows) < n:
        if expired:
            return {"status": "expired", "winner": None, "progress": len(rows),
                    "line_ko": f"{EXPIRE_DAYS}일 안에 거래 {n}건이 모이지 않음({len(rows)}건): 기한 지남"}
        return None
    use = rows[:n]
    end = int(use[-1][3])
    flip_ids = [f"{f}@{t}" for f in FLIPS for t in ([tf] if tf else TFS)]
    try:
        flips = _trades(paper_ro, flip_ids, ts, end)
    except sqlite3.Error:
        flips = []
    if spec.get("check") == "tag_gap":
        tag = spec.get("tag") or ""
        yes, no = _tagged(use, tag, round_trip)
        fy, fn = _tagged(flips, tag, round_trip)
        mirror = {"with_n": len(fy), "with_mean": _mean(fy), "without_n": len(fn), "without_mean": _mean(fn)}
        mirror["gap"] = None if mirror["with_mean"] is None or mirror["without_mean"] is None else \
            mirror["with_mean"] - mirror["without_mean"]
        mtxt = (f"동전 거울: 같은 기간 동전 계좌의 '{tag}' 거래 {len(fy)}건 평균 {_pct(mirror['with_mean'])} vs 없는 거래 "
                f"{len(fn)}건 {_pct(mirror['without_mean'])}")
        if len(yes) < GROUP_MIN or len(no) < GROUP_MIN:
            return {"status": "void", "winner": None, "mirror": mirror,
                    "line_ko": f"'{tag}' 붙은 거래 {len(yes)}건 · 안 붙은 거래 {len(no)}건: 한쪽이 {GROUP_MIN}건 미만이라 "
                               f"가릴 수 없음(무효) · {mtxt}"}
        my, mn = _mean(yes), _mean(no)
        won = my < mn
        return {"status": "settled", "winner": "a" if won else "b", "mirror": mirror,
                "numbers": {"with_n": len(yes), "with_mean": my, "without_n": len(no), "without_mean": mn},
                "line_ko": (f"{'공격하는 직원' if won else '편드는 직원'} 맞음('{tag}' 거래 {len(yes)}건 평균 {_pct(my)} vs "
                            f"없는 거래 {len(no)}건 {_pct(mn)}) · {mtxt} · 동전 50%에 가까운 확인이라 규칙 근거 아님")}
    s_roe = [r for r in (_f(x[4]) for x in use) if r is not None]
    f_roe = [r for r in (_f(x[4]) for x in flips) if r is not None]
    one = [r for (_i, aid, _e, _x, roe, _d) in flips if aid.startswith(FLIPS[0] + "@") for r in [_f(roe)] if r is not None]
    rest = [r for (_i, aid, _e, _x, roe, _d) in flips if not aid.startswith(FLIPS[0] + "@") for r in [_f(roe)] if r is not None]
    mirror = {"one_n": len(one), "one_mean": _mean(one), "rest_n": len(rest), "rest_mean": _mean(rest)}
    mtxt = (f"동전 거울: 동전 하나(RANDOM_1) {len(one)}건 평균 {_pct(mirror['one_mean'])} vs 나머지 동전 {len(rest)}건 "
            f"{_pct(mirror['rest_mean'])}")
    if len(f_roe) < n / 2:
        return {"status": "void", "winner": None, "mirror": mirror,
                "line_ko": f"같은 기간 동전 계좌 거래 {len(f_roe)}건(필요 {math.ceil(n / 2)}건): 가릴 수 없음(무효)"}
    ms, mf = _mean(s_roe), _mean(f_roe)
    won = ms is not None and mf is not None and ms <= mf
    return {"status": "settled", "winner": "a" if won else "b", "mirror": mirror,
            "numbers": {"n": len(s_roe), "mean": ms, "flip_n": len(f_roe), "flip_mean": mf},
            # the advocate's label says only what the N trades show (their mean above the flips'), never that the strategy
            # is 'better than the coin flips': 20-60 trades before the 30-day verdict are no pass hint (CONTRACT 1.3)
            "line_ko": (f"{'공격하는 직원(우위 없음)' if won else f'편드는 직원(이 {len(s_roe)}건 평균이 동전보다 높음)'} 맞음(거래 "
                        f"{len(s_roe)}건 평균 "
                        f"{_pct(ms)} vs 동전 {len(f_roe)}건 {_pct(mf)}) · {mtxt} · 동전 50%에 가까운 확인이라 규칙 근거 아님")}


def progress(d: dict, paper_ro: Optional[sqlite3.Connection]) -> Optional[int]:
    """Trades of an open forward dispute so far (for the dashboard: '앞으로 40건 중 12건')."""
    if d.get("kind") != "forward" or d.get("status") != "open" or paper_ro is None:
        return None
    spec = d.get("spec") or {}
    try:
        ids = _account_ids(d["strategy"], spec.get("timeframe"))
        return int(paper_ro.execute(f"SELECT COUNT(*) FROM trades WHERE account_id IN ({','.join('?' * len(ids))}) "
                                    "AND entry_time >= ?", (*ids, int(d["ts"]))).fetchone()[0])
    except sqlite3.Error:
        return None


# ---------------------------------------------------------------- grading: the tick
def _post(conn: sqlite3.Connection, d: dict, text: str, data: dict, now_ms: int) -> None:
    rooms = [R.strategy_room_id(d["strategy"])]
    if d.get("room_id") and d["room_id"] not in rooms:
        rooms.append(d["room_id"])
    for room in rooms:
        R.post(conn, room, None, None, "code", None, "system", text, data, ts=now_ms)


def _close(conn: sqlite3.Connection, d: dict, v: dict, now_ms: int, trial_id: Optional[int] = None) -> Optional[dict]:
    data = dict(d.get("data") or {})
    for k in ("mirror", "numbers", "checks", "gate_pass", "n_trials", "progress"):
        if v.get(k) is not None:
            data[k] = v[k]
    ok = _update(conn, d["id"], status=v["status"], winner=v.get("winner"), outcome=v["line_ko"][:600],
                 settled_ts=int(now_ms), data=data, **({"trial_id": int(trial_id)} if trial_id else {}))
    if not ok:
        return None
    who = f"공격 {name(d['side_a'])} vs 편 {name(d['side_b'])}"
    trial = f" · 5년 시험 #{trial_id}" if trial_id else ""
    head = "결론" if v["status"] == "settled" else f"결론({STATUS_KO.get(v['status'], v['status'])})"
    text = f"⚖️ 다툼 #{d['id']} {head}: {who}{trial} · {v['line_ko']}"
    _post(conn, d, text, {"action": "dispute", "dispute_id": d["id"], "status": v["status"], "winner": v.get("winner"),
                          "trial_id": trial_id}, now_ms)
    return {"dispute_id": d["id"], "status": v["status"], "winner": v.get("winner"), "trial_id": trial_id,
            "line_ko": v["line_ko"]}


def grade_due(conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection], now_ms: int,
              round_trip: float = 0.0) -> list[dict]:
    """Hand queued lab disputes to the shared queue, then settle what can be settled (code only, 0 AI): lab disputes
    whose test is in the ledger, forward checks whose N trades are in; expire the rest after their time. Posts
    '⚖️ 다툼 #n 결론: …' in strat:<S> and in the room that opened it."""
    if not _table_ok(conn):
        return []
    hand_over(conn, now_ms)
    done: list[dict] = []
    for d in _rows(conn, "status IN ('queued', 'open')", (), 500, "id"):
        try:
            if (d.get("data") or {}).get("conceded"):
                # a conceded dispute is written 'queued' only for the moment its test is handed to the queue; a pass
                # that stopped in between leaves it so: it is final and never scored
                _update(conn, d["id"], status="conceded", settled_ts=int(d["ts"]))
                continue
            if d["kind"] == "lab":
                t, ev = _lab_trial(conn, d)
                if t is not None:
                    got = _close(conn, d, lab_verdict(t), now_ms, int(t["id"]))
                elif ev and ev.get("status") in INTAKE_VOID:
                    got = _close(conn, d, {"status": "void", "winner": None,
                                           "line_ko": f"시험 대기열에서 시험하지 않음({ev['status']}): 가릴 수 없음(무효)"},
                                 now_ms)
                elif ev and ev.get("status") in INTAKE_EXPIRED:
                    got = _close(conn, d, {"status": "expired", "winner": None,
                                           "line_ko": "시험 대기열의 기한이 지나 시험하지 못함"}, now_ms)
                elif d.get("intake_id") is None and now_ms - int(d["ts"]) > HANDOVER_DAYS * DAY_MS:
                    got = _close(conn, d, {"status": "expired", "winner": None,
                                           "line_ko": f"{HANDOVER_DAYS}일 동안 시험 대기열에 넘기지 못함"}, now_ms)
                elif now_ms - int(d["ts"]) > EXPIRE_DAYS * DAY_MS:
                    got = _close(conn, d, {"status": "expired", "winner": None,
                                           "line_ko": f"{EXPIRE_DAYS}일 안에 5년 시험을 하지 못함"}, now_ms)
                else:
                    got = None
            else:
                v = forward_verdict(d, paper_ro, now_ms, round_trip)
                got = _close(conn, d, v, now_ms) if v is not None else None
        except sqlite3.IntegrityError:
            continue          # a row a concurrent writer finished: nothing to do
        except (sqlite3.OperationalError, TypeError, ValueError, KeyError, AttributeError, IndexError) as exc:
            # one odd row (a trade's data code cannot read, a locked read) never stops the others' grading; it is
            # tried again next tick and expires on time like any other
            print(f"warning: dispute #{d.get('id')} not graded: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            continue
        if got:
            done.append(got)
    return done


def tick(conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection], now_ms: int,
         round_trip: float = 0.0, seats: bool = False) -> list[dict]:
    """The agents tick's one call: the table, the seats (only with sides on: ``seats``) and the grading (always, so a
    dispute opened before sides were turned off is still settled)."""
    ensure(conn)
    if seats:
        sides(conn, now_ms)
    return grade_due(conn, paper_ro, now_ms, round_trip)


# ---------------------------------------------------------------- the board (who was right)
def _attack_turns(conn: Optional[sqlite3.Connection]) -> dict:
    """{role: {attacks, talk_only, gave_up}} from every attack turn ever posted (the rooms' messages)."""
    out: dict = {}
    if conn is None:
        return out
    try:
        rows = conn.execute("SELECT role, data FROM messages WHERE kind = 'challenge' AND data LIKE ?",
                            ('%"turn": "attack"%',)).fetchall()
    except sqlite3.Error:
        return out
    for role, data in rows:
        d = _loads(data) or {}
        if not isinstance(d, dict) or d.get("turn") != "attack":
            continue
        a = d.get("answer") if isinstance(d.get("answer"), dict) else {}
        k = out.setdefault(role, {"attacks": 0, "talk_only": 0, "gave_up": 0})
        k["attacks"] += 1
        if a.get("talk_only"):
            k["talk_only"] += 1
        if a.get("verdict") == "agree" and not a.get("verdict_coerced"):
            k["gave_up"] += 1
    return out


def _empty_role(role: str) -> dict:
    wl = lambda: {"won": 0, "lost": 0}  # noqa: E731
    return {"role": role, "name": name(role), "won": 0, "lost": 0, "settled": 0, "hit_rate": None,
            "as_attacker": wl(), "as_advocate": wl(), "by_kind": {"lab": wl(), "forward": wl()},
            "pending": 0, "conceded": 0, "void": 0, "expired": 0, "duplicate": 0, "attacks": 0, "talk_only": 0,
            "gave_up": 0, "expected": 0.0, "small": True}


def _check_of(r: dict) -> str:
    """The finest kind a base rate is kept for: 'lab', or the forward check ('tag_gap' / 'vs_flip')."""
    if r.get("kind") == "lab":
        return "lab"
    c = (r.get("spec") or {}).get("check") if isinstance(r.get("spec"), dict) else None
    return c if c in FORWARD_CHECKS else "forward"


def base_rates(rows: Iterable[dict]) -> dict:
    """The attacker's share of settled disputes by kind (the advocate's is 1 minus it), next to the coin flip's 50%;
    also per forward check ('tag_gap', 'vs_flip'): their base rates can differ (a strategy that trails the coin flips
    hands the attacker most vs_flip checks), and ``board``'s expected wins use the finest one."""
    rows = list(rows)
    out: dict = {}
    for k in ("lab", "forward", "all") + FORWARD_CHECKS:
        rs = [r for r in rows if r["status"] == "settled"
              and (k == "all" or r["kind"] == k or (k in FORWARD_CHECKS and _check_of(r) == k))]
        a = sum(r.get("winner") == "a" for r in rs)
        out[k] = {"settled": len(rs), "attacker_won": a, "advocate_won": len(rs) - a,
                  "attacker_share": a / len(rs) if rs else None, "advocate_share": (len(rs) - a) / len(rs) if rs else None,
                  "small": len(rs) < SMALL}
    out["coin_flip"] = 0.5
    return out


def board(conn: Optional[sqlite3.Connection], turns: bool = True) -> dict:
    """Per role over the whole run: won / lost (as attacker, as advocate, by kind), pending, conceded, talk-only attacks
    and attacks given up, and ``expected``: the wins the side's base rate alone would give (so 9/10 for an advocate
    of lab disputes that advocates win 92% of the time reads as the base rate, not as skill). Plus the base rates, the
    coin-flip 50% and the small-sample flag (under 10 settled)."""
    rows = _rows(conn, limit=100_000, order="id")
    rates = base_rates(rows)
    by: dict = {}

    def get_(role: str) -> dict:
        return by.setdefault(role, _empty_role(role))
    for r in rows:
        a, b = get_(r["side_a"]), get_(r["side_b"])
        st = r["status"]
        if st in PENDING:
            a["pending"] += 1
            b["pending"] += 1
        elif st == "conceded":
            b["conceded"] += 1
        elif st in ("void", "expired", "duplicate"):
            a[st] += 1
            b[st] += 1
        elif st == "settled" and r.get("winner") in ("a", "b"):
            share = (rates.get(_check_of(r)) or rates[r["kind"]])["attacker_share"] or 0.0
            for row, side, mine in ((a, "as_attacker", "a"), (b, "as_advocate", "b")):
                won = r["winner"] == mine
                row["won" if won else "lost"] += 1
                row[side]["won" if won else "lost"] += 1
                row["by_kind"][r["kind"]]["won" if won else "lost"] += 1
                row["expected"] += share if mine == "a" else 1.0 - share
    for role, k in (_attack_turns(conn) if turns else {}).items():    # turns=False: the disputes table only
        row = get_(role)
        row.update(k)
    out = []
    for row in by.values():
        row["settled"] = row["won"] + row["lost"]
        row["hit_rate"] = row["won"] / row["settled"] if row["settled"] else None
        row["expected"] = round(row["expected"], 2)
        row["small"] = row["settled"] < SMALL
        out.append(row)
    out.sort(key=lambda x: (-x["settled"], -x["pending"], -x["attacks"], x["name"]))
    totals = {st: sum(r["status"] == st for r in rows) for st in STATUSES}
    totals["pending"] = totals["queued"] + totals["open"]
    totals["talk_only"] = sum(r["talk_only"] for r in out)
    totals["gave_up"] = sum(r["gave_up"] for r in out)
    totals["attacks"] = sum(r["attacks"] for r in out)
    return {"roles": out, "base_rates": rates, "totals": totals, "small": rates["all"]["settled"] < SMALL,
            "min": SMALL, "coin_flip": 0.5, "note": BASE_NOTE_KO}


def line_of(r: dict) -> str:
    """One dispute in one line (code text): 'N17 · 공격 청산 타점 분석가 vs 편 켈트너·RSI 전담 · 첫 잠금 … · 5년 시험 #41
    → 편 맞음'."""
    who = f"공격 {name(r['side_a'])} vs 편 {name(r['side_b'])}"
    what = settle_ko(r.get("spec"), r.get("strategy"))
    if r["status"] == "settled":
        end = WINNER_KO.get(r.get("winner") or "", "결론")
    else:
        end = STATUS_KO.get(r["status"], r["status"])
    trial = f" · 시험 #{r['trial_id']}" if r.get("trial_id") else ""
    return f"{r['strategy']} · {who} · {r.get('claim_ko') or what} · {what}{trial} → {end}"


def list_rows(conn: Optional[sqlite3.Connection], strategy: Optional[str] = None, room: Optional[str] = None,
              status: Optional[str] = None, limit: int = 50, paper_ro: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Disputes for the dashboard, newest first, every word code text except ``claim_ko`` (the model's claim, shown as a
    quote). ``room``: disputes opened in that room or about its strategy."""
    where, args = ["1=1"], []
    if strategy:
        where.append("strategy = ?")
        args.append(strategy)
    if room:
        rs = R.room_strategy(room)
        if rs:
            where.append("(room_id = ? OR strategy = ?)")
            args += [room, rs]
        else:
            where.append("room_id = ?")
            args.append(room)
    if status:
        where.append("status = ?")
        args.append(status)
    out = []
    for r in _rows(conn, " AND ".join(where), tuple(args), min(max(int(limit), 1), 500)):
        spec = r.get("spec") or {}
        n = spec.get("n")
        prog = progress(r, paper_ro)
        if prog is not None and n:
            prog = min(prog, int(n))           # N in, graded at the next tick: never 'N건 중 N+3건'
        out.append({"id": r["id"], "ts": r["ts"], "room_id": r["room_id"], "round_id": r.get("round_id"),
                    "strategy": r["strategy"], "strategy_ko": STRATEGY_KO.get(r["strategy"], r["strategy"]),
                    "source": r["source"], "source_ko": SOURCE_KO.get(r["source"], r["source"]),
                    "claim_ko": r["claim_ko"], "side_a": r["side_a"], "side_a_name": name(r["side_a"]),
                    "side_b": r["side_b"], "side_b_name": name(r["side_b"]), "kind": r["kind"],
                    "kind_ko": KIND_KO.get(r["kind"], r["kind"]), "settle_ko": settle_ko(spec, r["strategy"]),
                    "status": r["status"], "status_ko": STATUS_KO.get(r["status"], r["status"]),
                    "winner": r.get("winner"), "winner_ko": WINNER_KO.get(r.get("winner") or "", ""),
                    "outcome": r.get("outcome"), "settled_ts": r.get("settled_ts"), "trial_id": r.get("trial_id"),
                    "intake_id": r.get("intake_id"), "n": n, "progress": prog,
                    "progress_ko": (f"앞으로 {n}건 중 {prog}건" if prog is not None and n else ""),
                    "mirror": (r.get("data") or {}).get("mirror"), "line_ko": line_of(r)})
    return out


def who_was_right(conn: Optional[sqlite3.Connection], recent: int = 20) -> dict:
    """The staff board's '누가 맞았나' block: tiles, base rates, per-role rows and the latest results (≤ 20).
    ``active``: sides were ever on (the seats cursor) or a dispute exists; False = the feature never ran (AGENTS_SIDES
    off, the default), so the dashboard hides the card instead of describing an attacker who does not exist."""
    b = board(conn)
    t = b["totals"]
    rates = b["base_rates"]
    return {"active": seats_written(conn) is not None or bool(_rows(conn, limit=1)),
            "tiles": {"settled": rates["all"]["settled"], "attacker_won": rates["all"]["attacker_won"],
                      "attacker_share": rates["all"]["attacker_share"], "pending": t["pending"],
                      "conceded": t["conceded"], "talk_only": t["talk_only"], "gave_up": t["gave_up"]},
            "base_rates": rates, "roles": b["roles"], "small": b["small"], "min": SMALL, "coin_flip": 0.5,
            "recent": [r for r in list_rows(conn, limit=200) if r["status"] in FINAL][:max(0, int(recent))],
            "note": b["note"]}


def of_rounds(conn: Optional[sqlite3.Connection], round_ids: Iterable[int]) -> dict:
    """{round_id: {id, status, status_ko, winner, winner_ko, kind}} of the dispute each meeting opened (the digest)."""
    ids = [int(i) for i in round_ids if i is not None]
    out: dict = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in _rows(conn, f"round_id IN ({','.join('?' * len(part))})", tuple(part), 5000, "id"):
            out.setdefault(int(r["round_id"]), {"id": r["id"], "status": r["status"],
                                                "status_ko": STATUS_KO.get(r["status"], r["status"]),
                                                "winner": r.get("winner"), "winner_ko": WINNER_KO.get(r.get("winner") or "", ""),
                                                "kind": r["kind"]})
    return out


def settled_between(conn: Optional[sqlite3.Connection], since_ms: int, until_ms: int, limit: int = 30) -> list[dict]:
    """Disputes that ended (settled, void, expired, conceded) in [since, until): claim, sides, winner, the code line
    (the Saturday learning packet: do_not_retest)."""
    out = []
    for r in _rows(conn, "settled_ts >= ? AND settled_ts < ? AND status != 'duplicate'", (int(since_ms), int(until_ms)),
                   limit, "settled_ts"):
        out.append({"id": r["id"], "strategy": r["strategy"], "claim": r["claim_ko"][:200], "kind": r["kind"],
                    "settle_ko": settle_ko(r.get("spec"), r["strategy"]), "side_a": r["side_a"], "side_b": r["side_b"],
                    "status": r["status"], "winner": r.get("winner"),
                    "winner_ko": WINNER_KO.get(r.get("winner") or "", STATUS_KO.get(r["status"], "")),
                    "outcome": (r.get("outcome") or "")[:300]})
    return out


def week_summary(conn: Optional[sqlite3.Connection], since_ms: int, until_ms: int) -> Optional[dict]:
    """The Sunday report's '누가 맞았나' numbers: settled this week (attacker / advocate), the whole run's attacker share
    next to the coin flip's 50%, pending. None when there is no dispute at all."""
    rows = _rows(conn, limit=100_000, order="id")
    if not rows:
        return None
    week = [r for r in rows if r["status"] == "settled" and since_ms <= int(r.get("settled_ts") or 0) < until_ms]
    br = base_rates(rows)
    rates = br["all"]
    return {"week_settled": len(week), "week_attacker": sum(r.get("winner") == "a" for r in week),
            "week_advocate": sum(r.get("winner") == "b" for r in week),
            "all_settled": rates["settled"], "all_attacker": rates["attacker_won"],
            "all_attacker_share": rates["attacker_share"], "pending": sum(r["status"] in PENDING for r in rows),
            "small": rates["settled"] < SMALL,
            # by kind: a 5-year dispute's base rate is far from the coin flip, so the two are never pooled in the line
            "by_kind": {k: {x: br[k][x] for x in ("settled", "attacker_won", "attacker_share")} for k in KINDS}}


def week_line(w: Optional[dict]) -> str:
    """'누가 맞았나: 이번 주 결론 3건(공격 1·편 2) · 실험 전체 공격 쪽 5년 시험 0/30(0%) · 앞으로 N건 6/10(60%, 동전 50%)
    · 대기 4' (code text). The 5-year and the forward shares are given apart: only the forward one is read against the
    coin flip's 50% (a 5-year dispute is nearly always the advocate's)."""
    if not w:
        return ""
    by = w.get("by_kind") or {}
    parts = []
    for k, label in (("lab", "5년 시험"), ("forward", "앞으로 N건")):
        r = by.get(k) or {}
        if not r.get("settled"):
            continue
        share = r.get("attacker_share")
        pct = f"{share * 100:.0f}%" if share is not None else ""
        pct += ", 동전 50%" if k == "forward" else ""
        parts.append(f"{label} {r['attacker_won']}/{r['settled']}" + (f"({pct})" if pct else ""))
    if parts:
        total = "실험 전체 공격 쪽 " + " · ".join(parts)
    else:
        total = f"실험 전체 공격 쪽 {w.get('all_attacker', 0)}/{w.get('all_settled', 0)}"
    total += " 표본 적음" if w.get("small") else ""
    return (f"누가 맞았나: 이번 주 결론 {w['week_settled']}건(공격 {w['week_attacker']}·편 {w['week_advocate']}) · "
            f"{total} · 대기 {w['pending']}")


def role_record(b: dict, role: str) -> dict:
    """One role's row of ``board`` (zeros when it has none)."""
    for r in b.get("roles") or []:
        if r["role"] == role:
            return r
    return _empty_role(role)


# ---------------------------------------------------------------- the room's packet
def _intake_tests_today(conn: sqlite3.Connection, now_ms: int, room: Optional[str] = None,
                        since_ms: Optional[int] = None) -> Optional[int]:
    """Counted 'meeting' tests of the shared queue since ``since_ms`` (default: the KST day), optionally in one room;
    None when the queue's tables are not there."""
    if not (_table_ok(conn, "lab_intake") and _table_ok(conn, "lab_intake_events")):
        return None
    # what the queue counts against a source's day (labintake._COUNTED_SQL): a finished test, or a run that got a
    # ledger number but no result (no data / error: it is in the room's n all the same)
    sql = ("SELECT COUNT(*) FROM lab_intake_events e JOIN lab_intake i ON i.id = e.intake_id WHERE i.source = 'meeting' "
           "AND (e.status = 'tested' OR (e.status IN ('not_counted', 'error') AND e.trial_id IS NOT NULL)) AND e.ts >= ?")
    args: list = [R.kst_day_start_ms(now_ms) if since_ms is None else int(since_ms)]
    if room:
        sql += " AND i.room_id = ?"
        args.append(room)
    try:
        return int(conn.execute(sql, args).fetchone()[0])
    except sqlite3.Error:
        return None


def dispute_tests(conn: sqlite3.Connection, strategy: str, now_ms: int, per_day: int = 3, gap_days: int = 7) -> dict:
    """{left_today, room_test_ok_now, next_p_threshold}: what a lab settle would get now (the queue decides; this is
    what the room is told). Counted from the shared queue, else from the disputes table."""
    room = R.strategy_room_id(strategy)
    day0 = R.kst_day_start_ms(now_ms)
    used = _intake_tests_today(conn, now_ms)
    recent = _intake_tests_today(conn, now_ms, room, now_ms - gap_days * DAY_MS)
    if used is None:
        used = len(_rows(conn, "kind = 'lab' AND ts >= ? AND status IN ('queued', 'settled', 'void')", (day0,), 100))
    if recent is None:
        recent = len(_rows(conn, "kind = 'lab' AND strategy = ? AND ts >= ? AND status IN ('queued', 'settled', 'void')",
                           (strategy, now_ms - gap_days * DAY_MS), 100))
    n = R.trial_count(conn, room_id=room, kinds=("test",))
    return {"left_today": max(0, int(per_day) - int(used)), "per_day": int(per_day),
            "room_test_ok_now": recent == 0, "gap_days": int(gap_days),
            "tests_in_room": n, "next_p_threshold": round(LAB_ALPHA / (n + 1), 6),
            "note": f"하루 {per_day}개·한 방 {gap_days}일에 1개(넘치면 대기). 시험마다 이 방 관문 기준이 엄격해짐"}


def packet(conn: sqlite3.Connection, strategy: str, paper_ro: Optional[sqlite3.Connection], now_ms: int,
           per_day: int = 3, gap_days: int = 7) -> dict:
    """The strategy room's 'sides' and 'disputes' sections (code only, ≈0.45k tokens)."""
    b = board(conn)
    seat_adv, seat_att = advocate_of(strategy), attacker_of(strategy, conn)

    def seat(role: str, side: str) -> dict:
        r = role_record(b, role)
        return {"role": role, "name": name(role), "side": side,
                "record": {k: r[k] for k in ("won", "lost", "settled", "pending", "conceded", "talk_only", "gave_up")},
                "record_side": r["as_advocate" if side == "advocate" else "as_attacker"]}
    rows = list_rows(conn, strategy=strategy, limit=40, paper_ro=paper_ro)
    return {
        "sides": {"advocate": seat(seat_adv, "advocate"), "attacker": seat(seat_att, "attacker"),
                  "version": sides_view(conn).get("version", 1),
                  "base_rates": {k: {x: b["base_rates"][k][x] for x in ("settled", "attacker_share")}
                                 for k in ("lab", "forward")}, "coin_flip": 0.5,
                  "note": "점수는 코드가 채점(편의 기준 비율·동전 50%와 함께 봄)"},
        "disputes": {
            "open": [{k: r[k] for k in ("id", "claim_ko", "kind", "settle_ko", "status_ko", "progress_ko")}
                     for r in rows if r["status"] in PENDING][:5],
            "settled_recent": [{"id": r["id"], "line": (r.get("outcome") or r["status_ko"])[:300],
                                "settle_ko": r["settle_ko"], "status": r["status"]}
                               for r in rows if r["status"] in FINAL][:8],
            "dispute_tests": dispute_tests(conn, strategy, now_ms, per_day, gap_days),
            "forward": forward_table(paper_ro, strategy, now_ms)}}       # the claim rule itself is fixed prompt text
