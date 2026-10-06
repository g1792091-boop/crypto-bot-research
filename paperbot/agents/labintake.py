"""The shared lab intake queue: ideas from the 24-hour debate room, from meeting disputes and from the owners' own test
requests ('🧪 이 매매법 시험해줘', the lab room's form; see the owners' section at the end) wait here until code runs them
as real, counted 5-year tests. No AI calls here.

Only code decides what gets tested and when. Every test goes through ``actions.newlab_test`` (a new strategy in
newlab's grammar, counted in the lab's n, docs/newlab-prereg.md section 5) or ``actions.request_test`` (one of the
36's fixed what-if templates, counted in that strategy room's n), exactly like a lab meeting's or a strategy room's
own test: there is no side channel and no separate count. An identical earlier test is never run again (a newlab
spec already in the ledger is answered 'duplicate', a labtest is reused by ``request_test``; both free).

Storage (agents3.db, created here with CREATE TABLE IF NOT EXISTS; rooms_db is not touched):
  lab_intake         one row per idea, append-only: source (debate | meeting | owner), source_ref (unique per source:
                     'debate:<debate_lab_ideas.id>', 'dispute:<disputes.id>', 'owner:<owner_messages.id>:<i>'), the
                     target room, the engine (newlab | labtest), the spec in canonical form re-made by THIS code (the
                     source's own check is never trusted), its hash and the code's Korean description. The source's
                     words (idea_ko) are kept only as a quote.
  lab_intake_events  append-only status events; the latest event is the row's status (STATUSES).

Daily budget (the statistical price of every counted test, not only CPU), per KST day and source, counted as
'tested' events: debate <= ``lab_intake_debate_per_day`` (hard max 2), meeting <= ``dispute_tests_per_day`` (only
while ``sides`` is on, and one counted test per strategy room per ``dispute_room_gap_days``), owner <=
``lab_intake_owner_per_day``. A source whose budget is 0 is off: its rows wait (and expire). With every source off
``tick`` does nothing at all (no table is created, nothing is read).

``run_due`` NEVER proposes anything: a pass waits in the ledger like any lab pass, and rooms.newlab_tick proposes it
after the observation period, judged again with n at that time; copies only come from a strategy room's meeting.

The debate service imports this module only for its read helpers (view, today, why_fail, result_ko, STATUS_KO): the
module's top-level imports are light, and actions / newlab / labtests / rooms are imported inside the functions that
run on the agents side.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from . import rooms_db as R

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SOURCES = ("debate", "meeting", "owner")
ENGINES = ("newlab", "labtest")
STATUSES = ("queued", "needs_owner_ok", "running", "tested", "reused", "duplicate", "not_counted", "bad_spec",
            "refused", "declined", "error", "expired")
STATUS_KO = {"queued": "대기", "needs_owner_ok": "두 분 확인 필요", "running": "시험 중", "tested": "시험함",
             "reused": "이전 결과 재사용", "duplicate": "이미 시험함", "not_counted": "시험 수에 안 넣음",
             "bad_spec": "문법 밖", "refused": "거절", "declined": "그만", "error": "오류", "expired": "기한 지남"}
OPEN_STATUSES = ("queued", "needs_owner_ok", "running")
SOURCE_KO = {"debate": "토론방", "meeting": "회의", "owner": "두 분"}
SOURCE_LONG_KO = {"debate": "🗣️ 24시간 토론방 아이디어", "meeting": "⚔️ 회의 다툼", "owner": "🧪 두 분 시험 요청"}
SOURCE_PRIORITY = {"owner": 1, "meeting": 2, "debate": 3}
ENGINE_KO = {"newlab": "5년 시험·새 매매법", "labtest": "5년 시험·36개 고쳐 보기"}
DEBATE_PER_DAY_MAX = 2
# a queued row of these sources expires after this long (from the idea's own time): an old idea is not tested late
EXPIRE_MS = {"debate": 72 * HOUR_MS, "meeting": 14 * DAY_MS}
MAX_IDEA_CHARS = 300
PULL_BATCH = 10                      # new debate ideas taken into the queue per pass
LIMITS_CURSOR = "labintake:limits"   # the budgets in force (the dashboard shows them)
BLOCKED_CURSOR = "labintake:blocked"  # why queued rows wait ({"ts", "why"}): no engine, no data, exhausted
CHECK_MARKS = {"a": "①", "b": "②", "c": "③", "d": "④", "e": "⑤", "f": "⑥"}
NEWLAB_CHECK_KO = {"①": "1기간 수익·p 기준", "②": "거래 수·코인 과반", "③": "2기간 확인", "④": "3기간",
                   "⑤": "자금 대비 손익", "⑥": "동전보다 나음"}
LABTEST_CHECK_KO = {"①": "1기간 개선·p 기준", "②": "2기간도 개선", "③": "3기간", "④": "바꾼 규칙 자체 수익",
                    "⑤": "1기간 거래 수", "⑥": "레버리지 뺀 개선(손절폭만)"}
BLOCKED_KO = {"no_engine": "시험 엔진이 없어", "no_data": "이 서버에 5년 시험 자료(캐시)가 없어",
              "exhausted": "새 매매법 시험 수가 한도에 닿아 어떤 새 시험도 관문을 넘을 수 없어"}
REFUSE_5M_KO = "5분봉은 시험하지 않습니다(v4에는 5분봉 매매법 계좌가 없음): 15m·30m·1h·4h만 됩니다."

# The owners' requests (#103 idea inbox): what code says when a request cannot be tested as written. A fixed
# vocabulary, Korean written by code, never model prose.
OWNER_REASON_KO = {
    "exit_rule": "청산·익절·레버리지·크기는 고를 수 없습니다(36개에만 손절 1.5·2.5·3 ATR, 첫 잠금 15·20·30%가 있음)",
    "param_off_grid": "숫자가 문법의 값과 달라 가장 가까운 값으로 옮겼습니다(근사)",
    "state_entry": "'~인 동안' 같은 상태 진입은 문법에 없습니다(진입은 신호가 생기는 순간만)",
    "two_triggers_and": "두 신호를 동시에(AND) 쓰는 진입은 없습니다: 하나는 필터 5종 중 하나로만 됩니다",
    "pattern": "추세선·지지저항·피보나치·엘리엇·하모닉·다이버전스·머리어깨 같은 패턴은 문법에 없습니다",
    "data_missing": "호가·미결제약정·펀딩·청산·온체인·뉴스·지수 자료는 시험 자료에 없습니다(시가·고가·저가·종가·거래량·ATR만)",
    "universe": "코인 하나만·다른 코인·일봉·1분봉은 안 됩니다(시험은 언제나 6개 코인, 과반이 플러스여야 함)",
    "position_mgmt": "물타기·그리드·마틴게일·불타기·헤지 같은 포지션 관리는 없습니다",
    "filter_on_36_other": "36개 매매법에 붙일 수 있는 조건은 진입 상황 태그 7개 건너뛰기뿐입니다",
    "discretionary": "사람·AI의 판단으로 들어가는 규칙은 코드로 시험할 수 없습니다",
}
OWNER_EXITS_KO = "영상의 청산 규칙은 시험되지 않습니다(항상 2 ATR 손절·계단식 익절·20~50배)"
# the reasons that change the ENTRY that is tested (an 'exact' translation that names one is approximate)
ENTRY_REASON_CODES = ("param_off_grid", "state_entry", "two_triggers_and", "pattern", "data_missing", "universe",
                      "filter_on_36_other", "discretionary")
NOT_TESTED_KO = "시험하지 않았고 시험 수에도 넣지 않았습니다"
OWNER_DECISIONS = ("run", "decline")


def _trade_tfs() -> tuple:
    from ..config import V3_TRADE_TFS
    return tuple(V3_TRADE_TFS)


def _append_only(table: str) -> str:
    return (f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}\n"
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}\n"
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n")


def _in(values) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS lab_intake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN {_in(SOURCES)}),
    source_ref TEXT NOT NULL,
    room_id TEXT NOT NULL,
    engine TEXT NOT NULL CHECK (engine IN {_in(ENGINES)}),
    strategy TEXT,
    spec TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    description_ko TEXT NOT NULL,
    idea_ko TEXT NOT NULL DEFAULT '',
    meta TEXT,
    UNIQUE (source, source_ref)
);
CREATE INDEX IF NOT EXISTS lab_intake_source ON lab_intake (source, id);
CREATE INDEX IF NOT EXISTS lab_intake_hash ON lab_intake (spec_hash);
{_append_only("lab_intake")}
CREATE TABLE IF NOT EXISTS lab_intake_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN {_in(STATUSES)}),
    trial_id INTEGER,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS lab_intake_events_intake ON lab_intake_events (intake_id, id);
{_append_only("lab_intake_events")}
"""


def ensure(conn: sqlite3.Connection) -> None:
    """Create the two tables on agents3.db when missing (the tick's connection, the only writer)."""
    conn.executescript(SCHEMA)
    conn.commit()


def exists(conn: Optional[sqlite3.Connection]) -> bool:
    if conn is None:
        return False
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lab_intake_events'"
                            ).fetchone() is not None
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------- the budgets
def limits(policy: Any) -> dict:
    """{source: tests a KST day} from the rooms policy (0 = that source is off)."""
    deb = max(0, int(getattr(policy, "lab_intake_debate_per_day", 0) or 0))
    meet = max(0, int(getattr(policy, "dispute_tests_per_day", 0) or 0)) if getattr(policy, "sides", False) else 0
    own = max(0, int(getattr(policy, "lab_intake_owner_per_day", 0) or 0))
    return {"debate": min(deb, DEBATE_PER_DAY_MAX), "meeting": meet, "owner": own}


def enabled(policy: Any) -> bool:
    return any(v > 0 for v in limits(policy).values())


# ---------------------------------------------------------------- the canonical form (code, never the source's)
class IntakeRefused(ValueError):
    """An idea code will not test: ``status`` 'bad_spec' (outside the grammar / templates) or 'refused' (5m, a
    descriptive template, a name outside the 36). The message is Korean."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def canon(engine: str, spec: Any, strategy: Optional[str] = None) -> tuple[dict, str, str]:
    """(canonical spec, its ledger hash, the code's Korean description), or IntakeRefused.
    newlab: newlab.normalize_spec / spec_hash / describe_ko (the hash the ledger's 'newlab' trials carry).
    labtest: actions.validate (labtests.normalize_spec for that strategy) and rooms_db.spec_hash (the hash
    find_trial uses). Both engines still accept 5m; code refuses it here (v4 trades 15m-4h only), and refuses the
    descriptive timeframe_only template and every name outside the 36 (DeepSeek, the reel, coin flips)."""
    tfs = _trade_tfs()
    if engine == "newlab":
        from . import newlab as NL
        try:
            c = NL.normalize_spec(spec)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
            raise IntakeRefused("bad_spec", str(exc)[:300] or "문법에 맞지 않음") from None
        if c["timeframe"] not in tfs:
            raise IntakeRefused("refused", REFUSE_5M_KO)
        return c, NL.spec_hash(c), NL.describe_ko(c)
    if engine == "labtest":
        from . import actions as A
        if not isinstance(spec, dict):
            raise IntakeRefused("bad_spec", "36개 고쳐 보기 시험은 {template, timeframe, ...} 객체여야 합니다.")
        s = strategy if strategy not in (None, "") else spec.get("strategy")
        if not isinstance(s, str) or s not in A.lab_strategies():
            raise IntakeRefused("refused", "5년 시험은 잠긴 매매법 36개만 할 수 있습니다(딥시크·릴스·동전 계좌는 시험 대상 아님).")
        if spec.get("template") in A.descriptive():
            raise IntakeRefused("refused", "설명용 시험(봉별 성적 보기)은 아무것도 가리지 못해 받지 않습니다.")
        clean, problems = A.validate({"action": "request_test", "test": spec}, strategy=s)
        if clean.get("action") != "request_test":
            raise IntakeRefused("bad_spec", str(clean.get("detail") or "; ".join(problems) or "허용된 시험 형식이 아님")[:300])
        test = dict(clean["test"])
        if test.get("timeframe") not in tfs:
            raise IntakeRefused("refused", REFUSE_5M_KO)
        lab = A.lab_module()
        try:
            desc = lab.describe_ko(test) if lab is not None and hasattr(lab, "describe_ko") else ""
        except Exception:  # noqa: BLE001  (a description only)
            desc = ""
        if not desc:
            desc = f"{s} {test.get('timeframe')}: {A.TEMPLATE_KO.get(test.get('template'), test.get('template'))}"
        return test, R.spec_hash(test), desc
    raise IntakeRefused("bad_spec", "시험 종류(engine)는 newlab(새 매매법) 또는 labtest(36개 고쳐 보기)만 됩니다.")


def _room_for(engine: str, strategy: Optional[str]) -> str:
    return R.strategy_room_id(strategy) if engine == "labtest" and strategy else R.LAB_ROOM


def _dumps(x: Any) -> Optional[str]:
    return None if x is None else R.clean_text(json.dumps(x, ensure_ascii=False, default=str))


def _loads(s: Any) -> Any:
    if s is None or not isinstance(s, (str, bytes)):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s


def _text(v: Any, n: int) -> str:
    return R.clean_text(" ".join(v.split()))[:n] if isinstance(v, str) else ""


# ---------------------------------------------------------------- writes
def event(conn: sqlite3.Connection, intake_id: int, status: str, ts: int, trial_id: Optional[int] = None,
          detail: Any = None, *, commit: bool = True) -> int:
    if status not in STATUSES:
        raise ValueError(f"unknown intake status: {status!r}")
    cur = conn.execute("INSERT INTO lab_intake_events (intake_id, ts, status, trial_id, detail) VALUES (?,?,?,?,?)",
                       (int(intake_id), int(ts), status, None if trial_id is None else int(trial_id), _dumps(detail)))
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def enqueue(conn: sqlite3.Connection, source: str, source_ref: str, engine: str, spec: Any,
            strategy: Optional[str] = None, idea_ko: str = "", meta: Optional[dict] = None,
            now: Optional[int] = None, needs_ok: bool = False, refuse: Optional[str] = None) -> dict:
    """Put one idea in the queue (idempotent on (source, source_ref)): the row and its first event in one
    transaction. Code re-makes the spec (``canon``); an idea code will not test is still recorded, with a
    'bad_spec' / 'refused' event and the reason, so the source can be told. ``needs_ok``: the first status is
    'needs_owner_ok' instead of 'queued' (an owner's request translated only approximately). ``refuse``: record it
    as refused with this reason without trying (an owner's request that cannot be expressed at all).
    Returns {id, status, created, why?}."""
    if source not in SOURCES:
        raise ValueError(f"unknown intake source: {source!r}")
    source_ref = R.clean_text(str(source_ref))[:200]
    if not source_ref:
        raise ValueError("source_ref is required")
    old = conn.execute("SELECT id FROM lab_intake WHERE source = ? AND source_ref = ?", (source, source_ref)).fetchone()
    if old is not None:
        st = latest(conn, int(old[0]))
        return {"id": int(old[0]), "status": (st or {}).get("status"), "created": False}
    ts = int(time.time() * 1000) if now is None else int(now)
    s = strategy if isinstance(strategy, str) and strategy else (spec.get("strategy") if isinstance(spec, dict) else None)
    s = s if isinstance(s, str) and 0 < len(s) <= 64 else None
    eng = engine if engine in ENGINES else ("labtest" if s or (isinstance(spec, dict) and "template" in spec) else "newlab")
    why = ""
    try:
        if refuse:
            raise IntakeRefused("refused", str(refuse)[:300])
        c, h, desc = canon(eng if engine in ENGINES else "", spec, s)
        status = "needs_owner_ok" if needs_ok else "queued"
        stored, room = c, _room_for(eng, s)
    except IntakeRefused as exc:
        status, why = exc.status, exc.message
        stored = spec if spec is not None else {}
        try:
            h = R.spec_hash(stored)
        except (TypeError, ValueError):
            stored = str(spec)[:2000]
            h = R.spec_hash(stored)
        desc = f"(시험 안 함) {why}"[:300]
        from . import actions as A
        room = _room_for(eng, s if s in A.lab_strategies() else None)
    if eng == "newlab":
        s = None
    try:
        cur = conn.execute(
            "INSERT INTO lab_intake (ts, source, source_ref, room_id, engine, strategy, spec, spec_hash, description_ko, "
            "idea_ko, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (source, source_ref) DO NOTHING",
            (ts, source, source_ref, room, eng, s, _dumps(stored), h, R.clean_text(desc),
             _text(idea_ko, MAX_IDEA_CHARS), _dumps(meta or {})))
        if not cur.rowcount:                     # never with one writer; kept for safety
            conn.rollback()
            row = conn.execute("SELECT id FROM lab_intake WHERE source = ? AND source_ref = ?",
                               (source, source_ref)).fetchone()
            return {"id": int(row[0]), "status": (latest(conn, int(row[0])) or {}).get("status"), "created": False}
        iid = int(cur.lastrowid)
        event(conn, iid, status, ts, detail={"why": why} if why else None, commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    out = {"id": iid, "status": status, "created": True}
    if why:
        out["why"] = why
    return out


def enqueue_owner(conn: sqlite3.Connection, message_id: int, index: int, request: dict,
                  now: Optional[int] = None) -> dict:
    """An owner's request (#103 '이 매매법 시험해줘'), translated by the lab translator and re-normalized here:
    entry_fidelity 'exact' -> queued (runs within the owners' daily budget), 'approx' (or unknown) -> needs the owners'
    OK first ('needs_owner_ok', with what was kept and lost), 'none' -> refused (nothing counted). Reasons come from
    the fixed OWNER_REASON_KO vocabulary only."""
    req = request if isinstance(request, dict) else {}
    fid = req.get("entry_fidelity") if req.get("entry_fidelity") in ("exact", "approx", "none") else "approx"
    engine = req.get("engine") if req.get("engine") in ENGINES else "none"
    spec = req.get("test") if engine == "labtest" else req.get("spec")
    codes = [c for c in (req.get("reason_codes") or []) if isinstance(c, str) and c in OWNER_REASON_KO][:6]
    if fid == "exact" and any(c in ENTRY_REASON_CODES for c in codes):
        # code's rule, not the translator's: a request whose entry needed any of these changes is approximate (the
        # owners confirm it first); the exits / sizing never decide this (they are never tested, OWNER_EXITS_KO)
        fid = "approx"
    meta = {"fidelity": fid, "message_id": message_id, "index": index, "reason_codes": codes,
            "reasons_ko": [OWNER_REASON_KO[c] for c in codes],
            "kept": [_text(x, 80) for x in (req.get("kept") or []) if isinstance(x, str)][:6],
            "lost": [_text(x, 80) for x in (req.get("lost") or []) if isinstance(x, str)][:6],
            "exits_ko": OWNER_EXITS_KO}
    refuse = None
    if fid == "none" or engine == "none":
        fid = meta["fidelity"] = "none"
        refuse = " · ".join(meta["reasons_ko"]) or "문법으로 옮길 수 없는 요청입니다"
        refuse += f" ({NOT_TESTED_KO})"
    return enqueue(conn, "owner", f"owner:{int(message_id)}:{int(index)}", engine if engine in ENGINES else "newlab",
                   spec, req.get("strategy"), _text(req.get("idea"), MAX_IDEA_CHARS), meta, now,
                   needs_ok=fid != "exact", refuse=refuse)


def decide(conn: sqlite3.Connection, intake_id: int, decision: str, now: Optional[int] = None,
           author: str = "") -> bool:
    """The owners' click on a 'needs_owner_ok' row: 'run' -> queued, 'decline' -> declined (nothing counted).
    Any other state, or an unknown decision, changes nothing (False)."""
    if decision not in OWNER_DECISIONS:
        return False
    st = latest(conn, intake_id)
    if st is None or st["status"] != "needs_owner_ok":
        return False
    ts = int(time.time() * 1000) if now is None else int(now)
    event(conn, intake_id, "queued" if decision == "run" else "declined", ts,
          detail={"decision": decision, "author": _text(author, 40)})
    return True


# ---------------------------------------------------------------- reads
_ROW_SQL = ("SELECT i.id, i.ts, i.source, i.source_ref, i.room_id, i.engine, i.strategy, i.spec, i.spec_hash, "
            "i.description_ko, i.idea_ko, i.meta, e.status, e.ts AS status_ts, e.trial_id, e.detail "
            "FROM lab_intake i JOIN lab_intake_events e ON e.id = "
            "(SELECT MAX(id) FROM lab_intake_events WHERE intake_id = i.id)")


def _rows(conn: sqlite3.Connection, where: str = "", args: tuple = (), tail: str = "") -> list[dict]:
    cur = conn.execute(_ROW_SQL + (f" WHERE {where}" if where else "") + tail, args)
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, tuple(r)))
        for k in ("spec", "meta", "detail"):
            d[k] = _loads(d[k])
        if not isinstance(d["meta"], dict):
            d["meta"] = {}
        out.append(d)
    return out


def latest(conn: sqlite3.Connection, intake_id: int) -> Optional[dict]:
    rows = _rows(conn, "i.id = ?", (int(intake_id),))
    return rows[0] if rows else None


def rows_with_status(conn: sqlite3.Connection, statuses: tuple) -> list[dict]:
    return _rows(conn, f"e.status IN ({','.join('?' * len(statuses))})", tuple(statuses), " ORDER BY i.id")


# What uses up a source's budget: a 'tested' event, and a labtest that did not finish but left a numbered trial in
# its room's ledger (request_test keeps the number of a run that errored: it is in that room's n, the Bonferroni
# divisor, so it costs the same as a finished test)
_COUNTED_SQL = "(e.status = 'tested' OR (e.status IN ('not_counted', 'error') AND e.trial_id IS NOT NULL))"


def used_today(conn: sqlite3.Connection, source: str, now: int) -> int:
    """Tests of this source that cost the budget (``_COUNTED_SQL``) in the KST day of ``now``."""
    r = conn.execute("SELECT COUNT(*) FROM lab_intake_events e JOIN lab_intake i ON i.id = e.intake_id "
                     f"WHERE {_COUNTED_SQL} AND i.source = ? AND e.ts >= ? AND e.ts < ?",
                     (source, R.kst_day_start_ms(now), R.kst_day_start_ms(now) + DAY_MS)).fetchone()
    return int(r[0] or 0)


def _room_tested_since(conn: sqlite3.Connection, source: str, room_id: str, since: int) -> bool:
    r = conn.execute("SELECT 1 FROM lab_intake_events e JOIN lab_intake i ON i.id = e.intake_id WHERE "
                     f"{_COUNTED_SQL} AND i.source = ? AND i.room_id = ? AND e.ts >= ? LIMIT 1",
                     (source, room_id, since)).fetchone()
    return r is not None


# ---------------------------------------------------------------- the debate's hand-off (read-only on debate.db)
DEBATE_SQL = ("SELECT id, round_id, ts, engine, strategy, spec_json, claim_ko, pro_ko, con_ko, con_check, question_ko "
              "FROM debate_lab_ideas WHERE queue_status = 'queued' AND ts >= ? ORDER BY id LIMIT 50")


def pull_debate(ctx: Any, debate_db: Optional[str], now: int) -> int:
    """Take the debate's picked ideas (debate.db table debate_lab_ideas, queue_status 'queued', the last 3 days) into
    the queue. debate.db is opened read-only; a missing file or table, or a busy file, is simply tried again next
    pass. Every row is re-normalized here (debate.db is never trusted); a bad one is still recorded, as 'bad_spec'.
    No cursor: (source, source_ref) is unique, so the pull is idempotent. Returns the number of new rows."""
    if not debate_db:
        return 0
    try:
        dro = R.open_ro(debate_db)
    except sqlite3.Error:
        return 0
    if dro is None:
        return 0
    try:
        rows = [tuple(r) for r in dro.execute(DEBATE_SQL, (int(now) - 3 * DAY_MS,)).fetchall()]
    except sqlite3.Error:
        return 0
    finally:
        dro.close()
    conn = ctx.agents_conn
    seen = {r[0] for r in conn.execute("SELECT source_ref FROM lab_intake WHERE source = 'debate'")}
    made = 0
    for (iid, round_id, ts, engine, strategy, spec_json, claim, pro, con, con_check, question) in rows:
        ref = f"debate:{iid}"
        if ref in seen:
            continue
        if made >= PULL_BATCH:
            break
        spec = _loads(spec_json)
        meta = {"round_id": round_id, "origin_ts": ts, "question_ko": _text(question, 200),
                "claim_ko": _text(claim, 200), "pro_ko": _text(pro, 200), "con_ko": _text(con, 200),
                "con_check": _text(con_check, 4)}
        got = enqueue(conn, "debate", ref, str(engine or ""), spec, strategy if isinstance(strategy, str) else None,
                      _text(claim, MAX_IDEA_CHARS), meta, now)
        made += int(got["created"])
    return made


# ---------------------------------------------------------------- results (code numbers, code Korean)
def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _marks(checks: Any) -> tuple[list, list]:
    if not isinstance(checks, dict):
        return [], []
    bad = [CHECK_MARKS[k] for k in "abcdef" if k in checks and checks[k] is False]
    good = [CHECK_MARKS[k] for k in "abcdef" if checks.get(k) is True]
    return bad, good


def _period(row: Any, *keys) -> dict:
    row = row if isinstance(row, dict) else {}
    return {k: row.get(k) for k in keys if row.get(k) is not None}


def newlab_detail(status: Optional[str], gate: Any, ledger: Any, test_number: Any) -> dict:
    """The event detail of a newlab result (from newlab_test's answer or a stored trial body)."""
    gate = gate if isinstance(gate, dict) else {}
    led = ledger if isinstance(ledger, dict) else {}
    per = led.get("periods") if isinstance(led.get("periods"), dict) else {}
    checks = gate.get("checks") or led.get("checks") or {}
    bad, good = _marks(checks)
    n = gate.get("n_tests_so_far", led.get("n_tests_so_far"))
    return {"engine": "newlab", "verdict": "passed" if status in R.NEWLAB_PASSED else (status or "failed"),
            "stored_status": status, "test_number": test_number if test_number is not None else led.get("test_number"),
            "n_before": n, "threshold": _f(gate.get("alpha_period1")) or (0.05 / (int(n) + 1) if isinstance(n, int) else None),
            "checks": checks, "failed_checks": bad, "passed_checks": good,
            "reasons": [str(x)[:200] for x in (gate.get("reasons") or [])][:6],
            "p1": _period(per.get("1"), "trades", "mean_roe", "p", "mean_pnl_equity", "coinflip_diff", "coinflip_p"),
            "p2": _period(per.get("2"), "trades", "mean_roe", "p", "mean_pnl_equity", "coinflip_diff", "coinflip_p")}


def labtest_detail(status: Optional[str], gate: Any, result: Any, n_trials: Any, reused: bool = False) -> dict:
    """The event detail of a request_test result (its answer or a stored trial body)."""
    gate = gate if isinstance(gate, dict) else {}
    res = result if isinstance(result, dict) else {}
    per = res.get("periods") if isinstance(res.get("periods"), dict) else {}
    bad, good = _marks(gate.get("checks"))
    n = gate.get("n_trials", n_trials)

    def arm(pid):
        p = per.get(pid) if isinstance(per.get(pid), dict) else {}
        v = p.get("variant") if isinstance(p.get("variant"), dict) else {}
        return {**_period(p, "diff", "p", "diff_notional"),
                **({"variant_trades": v.get("trades")} if v.get("trades") is not None else {}),
                **({"variant_mean_roe": v.get("mean_roe")} if v.get("mean_roe") is not None else {})}
    return {"engine": "labtest", "verdict": status, "reused": bool(reused), "n_trials": n,
            "threshold": _f(gate.get("alpha_period1")) or (0.05 / max(1, int(n)) if isinstance(n, int) else None),
            "checks": gate.get("checks") or {}, "failed_checks": bad, "passed_checks": good,
            "reasons": [str(x)[:200] for x in (gate.get("reasons") or [])][:6], "p1": arm("1"), "p2": arm("2")}


def _pct(x: Any) -> str:
    v = _f(x)
    return "없음" if v is None else f"{v * 100:+.2f}%"


def _pp(x: Any) -> str:
    v = _f(x)
    return "없음" if v is None else f"{v * 100:+.2f}%p"


def _pv(x: Any) -> str:
    v = _f(x)
    return "없음" if v is None else (f"{v:.1e}" if v < 0.001 else f"{v:.2f}")


def _thr(x: Any) -> str:
    v = _f(x)
    return "?" if v is None else f"{v:.2g}"


def result_ko(detail: Any, status: Optional[str] = None, trial_id: Optional[int] = None) -> str:
    """One Korean line of code text from an event's detail, e.g. '불통과: ⑥ 동전과 차이 +0.02%p(p=0.41) · ① p=0.64 ·
    통과한 칸 ②③⑤ (새 매매법 시험 #57, 기준 p<0.00088)'. Never model words."""
    d = detail if isinstance(detail, dict) else {}
    if status in ("bad_spec", "refused"):
        return f"{STATUS_KO[status]}: {str(d.get('why') or '')[:200]}".rstrip(": ")
    if status in ("not_counted", "error"):
        why = d.get("why") or d.get("error") or ""
        if trial_id or d.get("numbered"):
            # request_test keeps the number of a run that did not finish: it is in that room's test count
            tid = f" #{trial_id}" if trial_id else ""
            return (f"{STATUS_KO[status]}: 시험을 끝내지 못했지만 장부{tid}에 번호가 남아 그 방의 시험 수에 들어감(오늘 몫도 씀)"
                    + (f" ({str(why)[:120]})" if why else ""))
        return f"{STATUS_KO[status]}: 시험 수에 넣지 않음" + (f" ({str(why)[:120]})" if why else "")
    if status == "expired":
        return "기한 지남: 시험하지 않았고 시험 수에도 넣지 않았습니다"
    if status == "declined":
        return "두 분이 그만두셨습니다: 시험하지 않았고 시험 수에도 넣지 않았습니다"
    if d.get("engine") not in ENGINES:
        return STATUS_KO.get(status or "", status or "")
    verdict = d.get("verdict")
    bad, good = d.get("failed_checks") or [], d.get("passed_checks") or []
    tid = f"#{trial_id}" if trial_id else ""
    if d["engine"] == "newlab":
        p1, p2 = d.get("p1") or {}, d.get("p2") or {}
        bits = []
        for m in bad:
            if m == "①":
                bits.append(f"① 1기간 거래당 {_pct(p1.get('mean_roe'))}(p={_pv(p1.get('p'))})")
            elif m == "③":
                bits.append(f"③ 2기간 거래당 {_pct(p2.get('mean_roe'))}(p={_pv(p2.get('p'))})")
            elif m == "⑥":
                bits.append(f"⑥ 동전과 차이 1기간 {_pp(p1.get('coinflip_diff'))}(p={_pv(p1.get('coinflip_p'))})")
            elif m == "②":
                bits.append(f"② 1기간 거래 {p1.get('trades', '?')}건")
            else:
                bits.append(f"{m} {NEWLAB_CHECK_KO.get(m, '')}")
        where = f"새 매매법 시험 {('#' + str(d['test_number'])) if d.get('test_number') else tid}, 기준 p<{_thr(d.get('threshold'))}"
    else:
        p1 = d.get("p1") or {}
        bits = []
        for m in bad:
            if m == "①":
                bits.append(f"① 1기간 개선 {_pp(p1.get('diff'))}(p={_pv(p1.get('p'))})")
            else:
                bits.append(f"{m} {LABTEST_CHECK_KO.get(m, '')}")
        where = f"이 방 시험 {d.get('n_trials', '?')}번째, 기준 p<{_thr(d.get('threshold'))}" + (f", 장부 {tid}" if tid else "")
    if verdict in ("passed",) or (verdict in R.NEWLAB_PASSED and d["engine"] == "newlab"):
        head = "통과: ①~⑥ 모두"
        tail = (" · 관찰 기간이면 기간 뒤 그때의 시험 수로 다시 판정해 제안(두 분 확인 필요)" if d["engine"] == "newlab"
                else " · 복제 제안은 그 매매법 방 회의에서만, 그때의 시험 수로 다시 판정(두 분 확인 필요)")
    elif verdict == "described":
        head, tail = "설명용 시험(판정 없음)", ""
    elif verdict in ("no_data", "error"):
        return f"{STATUS_KO.get(status or '', '')}: 시험을 하지 못했습니다(시험 수에 넣지 않음)".lstrip(": ")
    else:
        head = "불통과: " + (" · ".join(bits) if bits else "관문 미달")
        tail = f" · 통과한 칸 {''.join(good)}" if good else ""
    pre = {"reused": "이전 결과 재사용 · ", "duplicate": "이미 시험함 · "}.get(status or "", "")
    return f"{pre}{head}{tail} ({where})"


# ---------------------------------------------------------------- the agents side: run what is due
def _blocked(ctx: Any, engine: str) -> str:
    """Why this engine cannot test now ('' = it can): no engine, no 5-year cache, or (newlab) no test can pass."""
    from . import actions as A
    from .rooms import lab_ready
    if engine == "newlab" and A.newlab_module() is None:
        return "no_engine"
    if engine == "labtest" and A.lab_module() is None:
        return "no_engine"
    if not lab_ready(ctx.lab):
        return "no_data"
    if engine == "newlab" and A.newlab_exhausted(ctx.agents_conn):
        return "exhausted"
    return ""


def _ref_label(r: dict) -> str:
    ref = str(r.get("source_ref") or "")
    tail = ref.split(":", 1)[1] if ":" in ref else ref
    num = tail.split(":")[0]
    rnd = (r.get("meta") or {}).get("round_id")
    return f"#{num}" + (f"(회차 {rnd})" if r["source"] == "debate" and rnd not in (None, "") else "")


def _origin_ts(r: dict) -> int:
    o = (r.get("meta") or {}).get("origin_ts")
    return int(o) if isinstance(o, int) and not isinstance(o, bool) and 0 < o <= r["ts"] else int(r["ts"])


def _room_title(conn: sqlite3.Connection, room_id: str) -> str:
    room = R.get_room(conn, room_id)
    return (room or {}).get("title") or room_id


def _env(ctx: Any, r: dict, now_ms: int) -> Any:
    from . import actions as A
    from .rooms import observing
    lab_room = r["engine"] == "newlab"
    try:
        obs = observing(ctx) or ""
    except Exception:  # noqa: BLE001  (observation only matters for proposals, which this never makes)
        obs = ""
    return A.ActionEnv(conn=ctx.agents_conn, room_id=R.LAB_ROOM if lab_room else r["room_id"],
                       strategy=None if lab_room else r["strategy"], round_id=None, meeting="lab_intake",
                       now_ms=now_ms, room_title=R.LAB_TITLE if lab_room else _room_title(ctx.agents_conn, r["room_id"]),
                       notifier=ctx.notifier, lab=ctx.lab, observing=obs, paper_ro=ctx.paper_ro,
                       proposer="" if lab_room else str((r.get("meta") or {}).get("by_role") or ""),
                       newlab_cap_total=getattr(ctx.policy, "newlab_cap_total", 10))


def _free_answer(conn: sqlite3.Connection, r: dict) -> Optional[tuple]:
    """A newlab spec already in the ledger: ('duplicate', trial id, detail), answered for free (not run again,
    not counted). None otherwise."""
    if r["engine"] != "newlab":
        return None
    from . import actions as A
    tid = A.newlab_hashes(conn).get(r["spec_hash"])
    if tid is None:
        return None
    st, body = A.newlab_stored(R.get_trial(conn, tid))
    return "duplicate", tid, newlab_detail(st, body.get("gate"), body.get("ledger"), body.get("test_number"))


def _reusable(conn: sqlite3.Connection, r: dict) -> bool:
    """A labtest whose identical trial already has a final result: request_test reuses it (free, not counted)."""
    if r["engine"] != "labtest":
        return False
    from . import actions as A
    old = R.find_trial(conn, r["strategy"], r["spec"], kind="test")
    return old is not None and ((old.get("result") or {}).get("status") in A.FINAL_TEST_STATUSES)


def _run(ctx: Any, r: dict, now_ms: int) -> tuple[str, Optional[int], dict]:
    """Run one row through actions (the counted path). Returns (event status, trial id, detail)."""
    from . import actions as A
    env = _env(ctx, r, now_ms)
    label = f"[{SOURCE_KO[r['source']]} {_ref_label(r)}]"
    if r["engine"] == "newlab":
        res = A.newlab_test(env, r["spec"], idea=f"{label} {r.get('idea_ko') or ''}".strip()[:500])
        st = res.get("status")
        if st in ("passed", "failed"):
            return "tested", res.get("trial_id"), newlab_detail(st, res.get("gate"), res.get("ledger"),
                                                                res.get("test_number"))
        if st == "not_counted":
            return "not_counted", None, {"why": res.get("why"), "error": res.get("error")}
        return "error", None, {"error": res.get("error") or "시험 엔진 오류"}
    clean = {"action": "request_test", "test": dict(r["spec"]), "propose_copy_if_pass": False,
             "why": f"{label} 대기열 시험"}
    res = A.request_test(env, clean)
    st = res.get("status")
    if res.get("refused"):
        return "refused", None, {"why": res.get("text")}
    if res.get("reused"):
        return "reused", res.get("trial_id"), labtest_detail(st, res.get("gate"), res.get("result"),
                                                             res.get("n_trials"), reused=True)
    if st in ("passed", "failed", "described"):
        return "tested", res.get("trial_id"), labtest_detail(st, res.get("gate"), res.get("result"), res.get("n_trials"))
    # a run that did not finish keeps its ledger number (request_test): it is in the room's n, so it is marked and
    # costs the source's budget like a finished test (_COUNTED_SQL)
    numbered = {"numbered": True} if res.get("trial_id") is not None else {}
    if st == "no_data":
        return "not_counted", res.get("trial_id"), {"why": "no_data", "error": res.get("text"), **numbered}
    return "error", res.get("trial_id"), {"error": res.get("text") or st, **numbered}


def _announce(ctx: Any, r: dict, now_ms: int, used: Optional[int], lim: Optional[int], reuse: bool = False) -> None:
    room = R.LAB_ROOM if r["engine"] == "newlab" else r["room_id"]
    head = f"{SOURCE_LONG_KO[r['source']]} {_ref_label(r)}: {r['description_ko']}"
    if reuse:
        text = f"{head} — 같은 시험이 장부에 있어 다시 돌리지 않고 저장된 결과를 씁니다(시험 수에 넣지 않음)."
    else:
        text = (f"{head} — 코드가 5년 시험을 돌립니다(오늘 {SOURCE_KO[r['source']]} 몫 {used}/{lim}, "
                "시험 수에 들어감).")
    R.post(ctx.agents_conn, room, None, "lab_intake", "code", None, "system", text,
           {"lab_intake": r["id"], "source": r["source"], "source_ref": r["source_ref"], "engine": r["engine"],
            "spec_hash": r["spec_hash"]}, ts=now_ms)


def run_due(ctx: Any, now: int, max_per_pass: int = 2) -> dict:
    """Run the queued ideas that are due, owner > meeting > debate, then oldest first, at most ``max_per_pass`` real
    5-year runs. A newlab spec already in the ledger is answered 'duplicate' and a labtest with an identical final
    trial is reused (both free and outside the budget). Otherwise a row waits while its source's budget for the KST
    day is used up (or, for a meeting dispute, its strategy room had a counted test within the gap), while the lab
    is blocked (no engine, no data, exhausted: the reason is kept for the dashboard), or when the tick's wall time
    could not fit one more test. Each run: a 'running' event (committed), one code line in the target room, the test
    through actions (counted there), then the result event. Never proposes anything."""
    conn, p = ctx.agents_conn, ctx.policy
    lim = limits(p)
    out: dict = {"ran": [], "free": [], "expired": [], "blocked": "", "stopped": ""}
    clock = getattr(ctx, "clock", None)

    def ts_now() -> int:
        return int(clock()) if callable(clock) else int(now)
    rows = rows_with_status(conn, ("queued",))
    live = []
    for r in rows:
        exp = EXPIRE_MS.get(r["source"])
        if exp is not None and now - _origin_ts(r) > exp:
            span = f"{exp // HOUR_MS}시간" if exp < 4 * DAY_MS else f"{exp // DAY_MS}일"
            event(conn, r["id"], "expired", now, detail={"why": f"{span} 안에 시험하지 못함(시험 수에 안 넣음)"})
            out["expired"].append(r["id"])
        else:
            live.append(r)
    live.sort(key=lambda r: (SOURCE_PRIORITY[r["source"]], r["id"]))
    runs = 0
    blocked_now = ""
    for r in live:
        if lim.get(r["source"], 0) <= 0:
            continue                                     # that source is off: its rows wait (and expire)
        free = _free_answer(conn, r)
        if free is not None:
            st, tid, detail = free
            event(conn, r["id"], st, ts_now(), trial_id=tid, detail=detail)
            out["free"].append(r["id"])
            if r["source"] == "owner":
                _owner_result(ctx, r, st, tid, detail, ts_now())
            continue
        reuse = _reusable(conn, r)
        if not reuse:
            # the budget's day is the day the test would start (the clock, not the pass's start): a test that ran
            # past midnight is in the new day's budget, so the next row of this pass is judged by that day
            t_day = max(int(now), ts_now())
            used = used_today(conn, r["source"], t_day)
            if used >= lim[r["source"]]:
                continue
            if (r["source"] == "meeting" and r["room_id"].startswith("strat:")
                    and _room_tested_since(conn, "meeting", r["room_id"],
                                           t_day - max(0, int(getattr(p, "dispute_room_gap_days", 0) or 0)) * DAY_MS)):
                continue
            why = _blocked(ctx, r["engine"])
            if why:
                blocked_now = blocked_now or why
                continue
            if runs >= max_per_pass:
                out["stopped"] = "max_per_pass"
                break
            t0 = (getattr(ctx, "cache", None) or {}).get("tick_t0")
            if t0 is not None and time.monotonic() - float(t0) + float(p.lab_test_est_s) > float(p.tick_wall_s):
                out["stopped"] = "tick_wall"
                break
        else:
            used = None
        t = ts_now()
        event(conn, r["id"], "running", t)
        _announce(ctx, r, t, None if reuse else used + 1, None if reuse else lim[r["source"]], reuse=reuse)
        try:
            st, tid, detail = _run(ctx, r, ts_now())
        except Exception as exc:  # noqa: BLE001  (recorded; the tick goes on)
            st, tid, detail = "error", None, {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            if r["engine"] == "labtest":
                # request_test numbers a trial before it runs: one made by this run is in the room's n
                old = R.find_trial(conn, r["strategy"], r["spec"], kind="test")
                if old is not None and int(old.get("ts") or 0) >= t:
                    tid, detail["numbered"] = int(old["id"]), True
        event(conn, r["id"], st, ts_now(), trial_id=tid, detail=detail)
        if r["source"] == "owner":
            _owner_result(ctx, r, st, tid, detail, ts_now())
        (out["free"] if st == "reused" else out["ran"]).append(r["id"])
        if st != "reused":
            runs += 1
    out["blocked"] = blocked_now
    prev = R.get_cursor(conn, BLOCKED_CURSOR)
    cur = {"ts": int(now), "why": blocked_now} if blocked_now else None
    if (prev or {}).get("why") != (cur or {}).get("why"):
        R.set_cursor(conn, BLOCKED_CURSOR, cur)
    return out


def reconcile(conn: sqlite3.Connection, now: Optional[int] = None) -> int:
    """A 'running' row with no later event (the pass was killed in the middle): resolved from the ledger (the
    trial the run wrote, or an identical one that was there before), else back to 'queued'. Returns the number
    resolved. Runs under the tick's lock, so no other pass can be running it."""
    from . import actions as A
    ts = int(time.time() * 1000) if now is None else int(now)
    n = 0
    for r in rows_with_status(conn, ("running",)):
        st, tid, detail = "queued", None, {"why": "실행이 도중에 끝나 다시 줄 세움"}
        if r["engine"] == "newlab":
            hit = A.newlab_hashes(conn).get(r["spec_hash"])
            t = R.get_trial(conn, hit) if hit is not None else None
            if t is not None:
                s, body = A.newlab_stored(t)
                st = "tested" if int(t["ts"]) >= int(r["status_ts"]) else "duplicate"
                tid, detail = hit, newlab_detail(s, body.get("gate"), body.get("ledger"), body.get("test_number"))
        else:
            t = R.find_trial(conn, r["strategy"], r["spec"], kind="test")
            res = (t or {}).get("result") or {}
            if t is not None and res.get("status") in A.FINAL_TEST_STATUSES:
                body = res.get("result") if isinstance(res.get("result"), dict) else {}
                fresh = int(res.get("ts") or 0) >= int(r["status_ts"])
                st, tid = ("tested" if fresh else "reused"), t["id"]
                detail = labtest_detail(res.get("status"), body.get("gate"), body.get("result"), body.get("n_trials"),
                                        reused=not fresh)
        event(conn, r["id"], st, ts, trial_id=tid, detail={**detail, "reconciled": True})
        n += 1
    return n


def tick(ctx: Any, debate_db: Optional[str], now: int) -> dict:
    """The agents tick's hook (after the meetings, so meetings keep priority and tests use the time left in the pass):
    nothing at all while every source is off; else the tables, the budgets in force for the dashboard, recovery of a
    killed run, the debate's new picks, and the runs that are due."""
    p = ctx.policy
    if not enabled(p):
        return {"enabled": False}
    conn = ctx.agents_conn
    ensure(conn)
    lim = limits(p)
    if R.get_cursor(conn, LIMITS_CURSOR) != lim:
        R.set_cursor(conn, LIMITS_CURSOR, lim)
    out: dict = {"enabled": True, "reconciled": reconcile(conn, now)}
    # the owners' clicks on approximate requests (inbox.db, read-only), before the runs so a 'run' can test this pass
    out["decided"] = apply_owner_decisions(conn, getattr(ctx, "inbox_ro", None), now)
    out["pulled"] = pull_debate(ctx, debate_db, now) if lim["debate"] else 0
    out.update(run_due(ctx, now))
    return out


# ---------------------------------------------------------------- views (read-only; dashboard, lab packet, debate)
def card(r: dict) -> dict:
    meta = r.get("meta") or {}
    return {"id": r["id"], "ts": r["ts"], "source": r["source"], "source_ko": SOURCE_KO.get(r["source"], r["source"]),
            "source_ref": r["source_ref"], "room_id": r["room_id"], "engine": r["engine"],
            "engine_ko": ENGINE_KO.get(r["engine"], r["engine"]), "strategy": r["strategy"],
            "description_ko": r["description_ko"], "idea_ko": r["idea_ko"], "meta": meta,
            "status": r["status"], "status_ko": STATUS_KO.get(r["status"], r["status"]), "status_ts": r["status_ts"],
            "trial_id": r["trial_id"], "detail": r["detail"] if isinstance(r["detail"], dict) else {},
            "result_ko": result_ko(r["detail"], r["status"], r["trial_id"])}


def view(conn_ro: Optional[sqlite3.Connection], source: Optional[str] = None, limit: int = 30) -> list[dict]:
    """The newest queue rows as cards (status, code result line), optionally one source. [] before the tables."""
    if not exists(conn_ro):
        return []
    n = min(max(int(limit), 1), 200)
    try:
        if source in SOURCES:
            rows = _rows(conn_ro, "i.source = ?", (source,), f" ORDER BY i.id DESC LIMIT {n}")
        else:
            rows = _rows(conn_ro, "", (), f" ORDER BY i.id DESC LIMIT {n}")
    except sqlite3.Error:
        return []
    return [card(r) for r in rows]


def today(conn_ro: Optional[sqlite3.Connection], now: int, lim: Optional[dict] = None) -> dict:
    """Per source: counted tests used today / the budget, rows waiting; and why the lab waits, if it does."""
    out = {"day": R.kst_day(now), "sources": {}, "blocked": None, "blocked_ko": ""}
    if conn_ro is None:                  # no agents3.db yet: the same shape, all zero (the dashboard reads the keys)
        out["sources"] = {s: {"source_ko": SOURCE_KO[s], "used": 0, "limit": int((lim or {}).get(s, 0) or 0),
                              "waiting": 0} for s in SOURCES}
        return out
    try:
        if lim is None:
            lim = R.get_cursor(conn_ro, LIMITS_CURSOR) or {}
        blocked = R.get_cursor(conn_ro, BLOCKED_CURSOR)
    except sqlite3.Error:
        lim, blocked = lim or {}, None
    have = exists(conn_ro)
    for s in SOURCES:
        used = waiting = 0
        if have:
            try:
                used = used_today(conn_ro, s, now)
                waiting = len([r for r in rows_with_status(conn_ro, ("queued", "needs_owner_ok")) if r["source"] == s])
            except sqlite3.Error:
                pass
        out["sources"][s] = {"source_ko": SOURCE_KO[s], "used": used, "limit": int((lim or {}).get(s, 0) or 0),
                             "waiting": waiting}
    if isinstance(blocked, dict) and blocked.get("why"):
        out["blocked"] = blocked
        out["blocked_ko"] = BLOCKED_KO.get(blocked["why"], blocked["why"]) + " 대기열이 기다리는 중"
    return out


def why_fail(conn_ro: Optional[sqlite3.Connection]) -> dict:
    """The 'why it failed' board: over every counted newlab test, how often each gate check ①-⑥ failed (from the
    stored checks of the test's own result). Code numbers only."""
    out: dict = {"tests": 0, "failed": {m: 0 for m in CHECK_MARKS.values()}, "share": {}, "names_ko": NEWLAB_CHECK_KO,
                 "top": None, "text_ko": ""}
    if conn_ro is None:
        return out
    try:
        rows = conn_ro.execute(
            "SELECT COALESCE(json_extract(r.result, '$.ledger.checks'), json_extract(r.result, '$.gate.checks')) "
            "FROM trials t JOIN trial_results r ON r.id = (SELECT MIN(id) FROM trial_results WHERE trial_id = t.id) "
            "WHERE t.kind = 'newlab'").fetchall()
    except sqlite3.Error:
        return out
    n = 0
    for (raw,) in rows:
        checks = _loads(raw)
        if not isinstance(checks, dict) or not checks:
            continue
        n += 1
        for k, m in CHECK_MARKS.items():
            if checks.get(k) is False:
                out["failed"][m] += 1
    out["tests"] = n
    if n:
        out["share"] = {m: round(c / n, 3) for m, c in out["failed"].items()}
        top = max(out["failed"].items(), key=lambda kv: kv[1])
        if top[1]:
            out["top"] = top[0]
        ranked = sorted(((m, c) for m, c in out["failed"].items() if c), key=lambda kv: -kv[1])[:3]
        out["text_ko"] = (f"새 매매법 시험 {n:,}개 중 떨어진 칸: "
                          + ", ".join(f"{m} {NEWLAB_CHECK_KO[m]} 미달 {c / n:.0%}" for m, c in ranked)) if ranked \
            else f"새 매매법 시험 {n:,}개: 떨어진 칸 없음"
    return out


def base_rates(conn_ro: Optional[sqlite3.Connection]) -> dict:
    """The lab's base rates, per engine ('newlab' trials, 'labtest' = the 36's 'test' trials), from each test's own
    result (the first one that carries gate checks): {engine: {tests, passed, pass_rate, fail_share {①..⑥}}}. A side
    that is 'right' only as often as these rates is right by the base rate, not by skill (debate_factory.readback
    shows its record next to them). Code numbers; empty rates when nothing is readable."""
    out = {e: {"tests": 0, "passed": 0, "pass_rate": None, "fail_share": {}} for e in ENGINES}
    if conn_ro is None:
        return out
    for eng, kind in (("newlab", "newlab"), ("labtest", "test")):
        try:
            rows = conn_ro.execute(
                "SELECT r.trial_id, r.status, COALESCE(json_extract(r.result, '$.ledger.checks'), "
                "json_extract(r.result, '$.gate.checks')) FROM trial_results r JOIN trials t ON t.id = r.trial_id "
                "WHERE t.kind = ? ORDER BY r.id", (kind,)).fetchall()
        except sqlite3.Error:
            continue
        first: dict = {}
        for tid, st, raw in rows:
            checks = _loads(raw)
            if tid not in first and isinstance(checks, dict) and checks:
                first[tid] = (st, checks)
        n = len(first)
        if not n:
            continue
        failed = {m: 0 for m in CHECK_MARKS.values()}
        passed = 0
        for st, checks in first.values():
            passed += int(st == "passed" or (kind == "newlab" and st in R.NEWLAB_PASSED))
            for k, m in CHECK_MARKS.items():
                failed[m] += int(checks.get(k) is False)
        out[eng] = {"tests": n, "passed": passed, "pass_rate": round(passed / n, 4),
                    "fail_share": {m: round(c / n, 3) for m, c in failed.items()}}
    return out


def overview(conn_ro: Optional[sqlite3.Connection], now: int) -> dict:
    """The lab packet's 'intake' block (lab_overview): what waits (so the inventor does not propose it again), today's
    budget, the latest results."""
    rows = view(conn_ro, None, 40)
    queued = [{"source_ko": c["source_ko"], "engine_ko": c["engine_ko"], "description_ko": c["description_ko"][:160]}
              for c in rows if c["status"] in OPEN_STATUSES][:5]
    recent = [{"source_ko": c["source_ko"], "description_ko": c["description_ko"][:160], "status_ko": c["status_ko"],
               "result_ko": c["result_ko"][:200], "trial_id": c["trial_id"]}
              for c in rows if c["status"] in ("tested", "reused", "duplicate")][:5]
    t = today(conn_ro, now)
    return {"queued": queued, "today": {s: {"used": v["used"], "limit": v["limit"]} for s, v in t["sources"].items()},
            "recent": recent,
            "note": "토론방·회의·두 분의 아이디어 대기열(코드가 하루 몫만큼 시험, 모두 같은 장부·같은 시험 수). 대기 중인 매매법은 "
                    "다시 제안하지 말 것"}


# ---------------------------------------------------------------- the owners' requests (#103 '🧪 이 매매법 시험해줘')
# The lab room's form on the dashboard posts through the owners' usual POST /api/rooms/team:lab/say (inbox.db
# owner_messages, no schema change): the first line is always LAB_REQUEST_MARK and the guided fields follow as labelled
# lines (``request_text``). The lab owner meeting's translator (rooms.py, turn 'lab_translate', only while
# ``lab_intake_owner_per_day`` is above 0) puts each request into the grammar; code re-makes it here (``enqueue_owner``)
# and says plainly what was kept and lost. An approximate one waits for the owners' click: the dashboard appends it to
# inbox.db's lab_request_decisions (DECISIONS_SQL, created by dash/app.py, never by rooms_db) and the tick applies it
# read-only (``apply_owner_decisions``). The result comes back as a code line in the lab room and one silent Telegram.
LAB_REQUEST_MARK = "🧪 시험 요청"
OWNER_PER_DAY_MAX = 3                # AGENTS_LAB_INTAKE_OWNER_PER_DAY above this is refused (rooms.policy_from_env)
OWNER_REQUESTS_PER_DAY = 5           # requests a KST day the dashboard takes (each one opens an owner meeting: 2 AI calls)
REQUEST_TFS = ("15m", "30m", "1h", "4h", "모름")
REQUEST_SIDES = ("롱만", "숏만", "둘 다", "모름")
# (key, label in the stored text, required, most characters): all of them together stay under one owner post's
# 1,000 characters (rooms_db.MAX_OWNER_TEXT, the packet's owner_messages cut)
REQUEST_FIELDS = (("entry", "언제 들어가나", True, 350), ("exit", "언제 나오나", False, 200), ("timeframe", "시간봉", False, 10),
                  ("coins", "코인", False, 60), ("side", "롱·숏", False, 10),
                  ("link", "참고 링크(에이전트는 열 수 없음)", False, 150), ("note", "더 적을 것", False, 120))
LINK_NOTE_KO = "링크는 열 수 없어요(에이전트는 인터넷 없음), 규칙을 글로 적어 주세요"
FIDELITY_KO = {"exact": "정확히 옮김", "approx": "근사로 옮김", "none": "옮길 수 없음"}
DECISION_KO = {"run": "시험하기", "decline": "그만두기"}
OWNER_STEPS = (("received", "접수"), ("translated", "옮김"), ("confirmed", "확인"), ("tested", "시험"), ("result", "결과"))
DECISIONS_SQL = f"""
CREATE TABLE IF NOT EXISTS lab_request_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    intake_id INTEGER NOT NULL,
    source_ref TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN {_in(OWNER_DECISIONS)}),
    author TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS lab_request_decisions_intake ON lab_request_decisions (intake_id, id);
{_append_only("lab_request_decisions")}
"""


def is_lab_request(text: Any) -> bool:
    """Does an owner post start with the fixed first line of the dashboard's test-request form?"""
    if not isinstance(text, str):
        return False
    first = text.lstrip("﻿").strip().split("\n", 1)[0]
    return first.strip() == LAB_REQUEST_MARK


def request_text(fields: Any) -> str:
    """The stored text of a request from the form's fields (code-made, one labelled line per field, the mark first).
    ValueError with a Korean message when the entry is missing or a field is too long or not one of its choices."""
    if not isinstance(fields, dict):
        raise ValueError("시험 요청 내용이 없습니다")
    lines = [LAB_REQUEST_MARK]
    for key, label, need, most in REQUEST_FIELDS:
        raw = fields.get(key)
        v = " ".join(raw.split()) if isinstance(raw, str) else ""
        if not v:
            if need:
                raise ValueError(f"'{label}'을(를) 적어 주세요")
            continue
        if len(v) > most:
            raise ValueError(f"'{label.split('(')[0]}'은(는) {most}자까지 적을 수 있습니다")
        if key == "timeframe" and v not in REQUEST_TFS:
            raise ValueError("시간봉은 15m, 30m, 1h, 4h 중 하나(또는 모름)입니다")
        if key == "side" and v not in REQUEST_SIDES:
            raise ValueError("롱·숏은 롱만, 숏만, 둘 다 중 하나(또는 모름)입니다")
        lines.append(f"{label}: {v}")
    return "\n".join(lines)


def requests_today(inbox_ro: Optional[sqlite3.Connection], now: int) -> int:
    """The owners' test requests posted in the lab room in the KST day of ``now`` (the dashboard's daily cap)."""
    if inbox_ro is None:
        return 0
    day0 = R.kst_day_start_ms(now)
    try:
        rows = inbox_ro.execute("SELECT text FROM owner_messages WHERE room_id = ? AND ts >= ? AND ts < ?",
                                (R.LAB_ROOM, day0, day0 + DAY_MS)).fetchall()
    except sqlite3.Error:
        return 0
    return sum(1 for (t,) in rows if is_lab_request(t))


def owner_label(r: dict) -> str:
    """'#41-1' for the source_ref 'owner:41:0' (the owners' post and which of its requests)."""
    parts = str(r.get("source_ref") or "").split(":")
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        return f"#{parts[1]}-{int(parts[2]) + 1}"
    return _ref_label(r)


# ---- the owners' clicks (inbox.db, written by the dashboard; read here read-only)
def ensure_decisions(conn: sqlite3.Connection) -> None:
    """Create inbox.db's lab_request_decisions (the dashboard's writer connection only)."""
    conn.executescript(DECISIONS_SQL)
    conn.commit()


def decisions(inbox_ro: Optional[sqlite3.Connection], intake_ids: Optional[list] = None) -> dict:
    """{intake id: [{id, ts, intake_id, source_ref, decision, author}, oldest first]} from inbox.db; {} without the file
    or the table."""
    if inbox_ro is None:
        return {}
    want = None if intake_ids is None else {int(i) for i in intake_ids}
    if want is not None and not want:
        return {}
    try:
        rows = inbox_ro.execute("SELECT id, ts, intake_id, source_ref, decision, author FROM lab_request_decisions "
                                "ORDER BY id").fetchall()
    except sqlite3.Error:
        return {}
    out: dict = {}
    for r in rows:
        d = dict(zip(("id", "ts", "intake_id", "source_ref", "decision", "author"), tuple(r)))
        if d["decision"] not in OWNER_DECISIONS or (want is not None and int(d["intake_id"]) not in want):
            continue
        out.setdefault(int(d["intake_id"]), []).append(d)
    return out


def add_decision(conn: sqlite3.Connection, intake_id: int, source_ref: str, decision: str, author: str = "",
                 now: Optional[int] = None) -> int:
    """The dashboard's writer: one owner click (append-only). The tick applies it with ``decide`` only while the row
    still waits for the owners and its source_ref matches (a replaced agents3.db never takes another row's click)."""
    if decision not in OWNER_DECISIONS:
        raise ValueError(f"decision must be run or decline, not {decision!r}")
    ensure_decisions(conn)
    cur = conn.execute("INSERT INTO lab_request_decisions (ts, intake_id, source_ref, decision, author) VALUES (?,?,?,?,?)",
                       (int(time.time() * 1000) if now is None else int(now), int(intake_id),
                        R.clean_text(str(source_ref))[:200], decision, _text(author, 40)))
    conn.commit()
    return int(cur.lastrowid)


def apply_owner_decisions(conn: sqlite3.Connection, inbox_ro: Optional[sqlite3.Connection], now: int) -> list[dict]:
    """The owners' clicks on rows that wait for them: the first click on a row whose source_ref matches and that came
    after the row was made -> 'queued' (시험하기) or 'declined' (그만두기, nothing counted), with one code line in the lab
    room. No cursor: only rows still waiting are looked at, so a click is applied once. Returns what was applied."""
    waiting = [r for r in rows_with_status(conn, ("needs_owner_ok",)) if r["source"] == "owner"]
    got = decisions(inbox_ro, [r["id"] for r in waiting]) if waiting else {}
    out = []
    for r in waiting:
        for d in got.get(r["id"], []):
            if d["source_ref"] != r["source_ref"] or int(d["ts"]) < int(r["ts"]):
                continue                       # another agents3.db's row, or a click older than this row
            if decide(conn, r["id"], d["decision"], now, d.get("author") or ""):
                who = f"두 분({_text(d.get('author'), 40)})" if d.get("author") else "두 분"
                text = (f"🧪 두 분 시험 요청 {owner_label(r)}: {who}이 '{DECISION_KO[d['decision']]}'를 고르셨습니다 — "
                        + ("대기열에 넣었습니다. 오늘 두 분 몫 안에서 코드가 5년 시험을 돌립니다(시험 수에 들어감)."
                           if d["decision"] == "run" else NOT_TESTED_KO + "."))
                R.post(conn, R.LAB_ROOM, None, "lab_intake", "code", None, "system", text,
                       {"lab_intake": r["id"], "owner_request": True, "source_ref": r["source_ref"],
                        "decision": d["decision"], "decision_id": d["id"]}, ts=now)
                out.append({"intake_id": r["id"], "decision": d["decision"]})
            break
    return out


def _owner_result(ctx: Any, r: dict, st: str, tid: Optional[int], detail: Any, ts: int) -> None:
    """An owner request's result in the lab room (code text) and one silent Telegram (INFO)."""
    line = result_ko(detail, st, tid)
    text = f"🧪 두 분 시험 요청 {owner_label(r)} 결과: {r['description_ko']}\n{line}\n{OWNER_EXITS_KO}"
    R.post(ctx.agents_conn, R.LAB_ROOM, None, "lab_intake", "code", None, "code_result", text,
           {"lab_intake": r["id"], "owner_request": True, "source_ref": r["source_ref"], "status": st,
            "trial_id": tid}, ts=ts)
    try:
        from ..notify import INFO
        ctx.notifier.send(INFO, f"🧪 시험 요청 결과 (요청 {owner_label(r)})\n{r['description_ko']}\n{line}\n"
                                "→ 대시보드 '에이전트 방'의 새 매매법 연구실")
    except Exception:  # noqa: BLE001  (a notice only: the result is in the room and on the card)
        pass


def owner_stage(c: dict) -> dict:
    """Where an owner request is on 접수 → 옮김 → 확인 → 시험 → 결과: {done: [the steps that really happened], now}."""
    st = c.get("status")
    done = ["received", "translated"]
    if st in ("bad_spec", "refused"):
        return {"done": done, "now": None}
    if st == "needs_owner_ok":
        return {"done": done, "now": "confirmed"}
    if st == "declined":
        return {"done": done, "now": None}
    done.append("confirmed")                    # exact (no click needed) or the owners' 'run'
    if st in ("queued", "running"):
        return {"done": done, "now": "tested"}
    if st == "expired":
        return {"done": done, "now": None}
    return {"done": done + ["tested", "result"], "now": None}


def owner_cards(conn_ro: Optional[sqlite3.Connection], inbox_ro: Optional[sqlite3.Connection] = None,
                limit: int = 20) -> list[dict]:
    """The owners' requests as cards (newest first): the queue card plus how it was translated (정확 / 근사 / 불가), what
    was kept and lost (the translator's words, a quote), the code's reasons, a click not applied yet, the steps that
    really happened and the code's result line."""
    rows = view(conn_ro, "owner", limit)
    pend = decisions(inbox_ro, [c["id"] for c in rows if c["status"] == "needs_owner_ok"])
    for c in rows:
        m = c.get("meta") or {}
        fid = m.get("fidelity") if m.get("fidelity") in FIDELITY_KO else None
        clicks = [d for d in pend.get(c["id"], []) if d["source_ref"] == c["source_ref"] and int(d["ts"]) >= int(c["ts"])]
        c.update(label_ko=f"요청 {owner_label(c)}", fidelity=fid, fidelity_ko=FIDELITY_KO.get(fid or "", ""),
                 kept=[str(x) for x in m.get("kept") or []][:6], lost=[str(x) for x in m.get("lost") or []][:6],
                 reasons_ko=[str(x) for x in m.get("reasons_ko") or []][:6], exits_ko=OWNER_EXITS_KO,
                 decision=({"decision": clicks[0]["decision"], "decision_ko": DECISION_KO[clicks[0]["decision"]],
                            "ts": clicks[0]["ts"]} if clicks and c["status"] == "needs_owner_ok" else None),
                 stage=owner_stage(c), steps=[{"id": k, "label": v} for k, v in OWNER_STEPS],
                 counted=c["status"] == "tested" or (c["status"] in ("not_counted", "error")
                                                     and c.get("trial_id") is not None))
    return rows


def owner_block(conn_ro: Optional[sqlite3.Connection], inbox_ro: Optional[sqlite3.Connection], now: int,
                limit: int = 20) -> dict:
    """The dashboard's '두 분 시험 요청' block: on / off (the owners' daily budget the agents last saved), today's requests
    and tests against their caps, the cards, and the fixed words the form shows."""
    lim = 0
    try:
        saved = R.get_cursor(conn_ro, LIMITS_CURSOR) if conn_ro is not None else None
    except sqlite3.Error:
        saved = None
    if isinstance(saved, dict):
        try:
            lim = max(0, int(saved.get("owner") or 0))
        except (TypeError, ValueError):
            lim = 0
    used = 0
    if exists(conn_ro):
        try:
            used = used_today(conn_ro, "owner", now)
        except sqlite3.Error:
            used = 0
    return {"enabled": lim > 0, "limit": lim, "tests_today": used, "requests_today": requests_today(inbox_ro, now),
            "requests_max": OWNER_REQUESTS_PER_DAY, "cards": owner_cards(conn_ro, inbox_ro, limit),
            "mark": LAB_REQUEST_MARK, "link_note_ko": LINK_NOTE_KO, "exits_ko": OWNER_EXITS_KO,
            "not_tested_ko": NOT_TESTED_KO, "timeframes": list(REQUEST_TFS), "sides": list(REQUEST_SIDES),
            "off_ko": ("시험 요청은 아직 꺼져 있습니다(서버 설정 AGENTS_LAB_INTAKE_OWNER_PER_DAY가 0). 켜지면 이 양식으로 보낸 "
                       "요청을 연구원이 문법으로 옮기고, 코드가 하루 몫만큼 5년 시험을 돌립니다.")}
