"""The 24-hour debate room as an idea factory (owner item B): assigned sides, the code check of each round's ONE lab
idea, the daily pick that hands at most 1-2 ideas a day to the agents' lab intake queue, and the read-back of results.
Debate side, code only, no AI call, no writes outside debate.db.

The debate service writes only debate.db (this module's ``debate_lab_ideas`` table, created by ``ensure``; the service
is its only writer). It reads agents3.db read-only (the lab ledger, the intake queue's results). It imports newlab and
labtests only to CALL normalize_spec / spec_hash / describe_ko (pure, data-free; about +100 MB and 1 s at import); if the
import fails an idea is stored 'unchecked' and the agents side still checks it (agents/labintake.py re-makes every spec,
so nothing here is ever trusted there). It never imports rooms.py or the agents' runner.

Seats (owners 10/06, after the design): five SPECIALISTS instead of personalities. 차트 분석가 (entries, trend, support
and resistance, 매물대), 리스크 책임자 (stop size, leverage, losing streaks), 퀀트 (numbers, sample size, coin flips),
시장 분석가 (funding, liquidations, volume, the macro calendar) and the 심판, a seat of its own that weighs both sides and
writes the round's one testable idea. Sides: SIDES = 찬성 / 반대 / 심판, assigned by code per round (``sides_for``): the
four specialists split 2-2 into 찬성 / 반대 and the split changes every round (three pairings x which pair is 찬성: all
six in six rounds, so every specialist plays both sides equally often); the 심판 is always the 심판. The model's own
label is never used. ``factory_order`` puts 찬성1, 반대1, 찬성2, 반대2 first, replies in between, the 심판 last.

Idea checks (``check_idea``): newlab grammar or one of the 36's what-if templates; 5m, timeframe_only and names outside
the 36 refused; an exact repeat of the ledger 'duplicate' (the old trial is shown), of this room's own ideas of the
last 30 days 'repeat' (counted as a back of the earlier one), a near-copy (rooms._similar score >= 7) of a FAILED lab
test 'near_duplicate'. Only 'ok' ideas are candidates.

Daily pick (``slot_pick``): at 21:00 KST (per_day 1, covering the 24 h before) or at 09:00 and 21:00 (per_day 2), the best
candidate of the slot by a code score goes to 'queued' (the contract labintake.pull_debate reads); the others are
'not_picked' with the reason. No candidate, no test: nothing is forced.

Grading (``settle``): 찬성 was right when the test passed, 반대 when it failed; the check 반대 named (con_check, ①-⑥) is
graded too, because pass/fail alone has a base rate near 0 (library 2,000 combinations, 0 passes). One model plays every
role (#88), so this is a record of sides, never of a person.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any, Optional

from . import debate_packet as P
from . import labintake as LI
from . import rooms_db as R

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
KST_MS = 9 * HOUR_MS
# the factory's seats (debate.FACTORY_ROLES; a test keeps them equal): four specialists, then the judge's own seat
ROLES = ("차트 분석가", "리스크 책임자", "퀀트", "시장 분석가", "심판")
JUDGE = "심판"
SIDES = ("찬성", "반대", "심판")
# the three ways to split four specialists 2-2 (by index into the four)
PAIRINGS = (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2)))
MIN_TURNS, MAX_TURNS = 5, 9
TFS = ("15m", "30m", "1h", "4h")
CHECK_MARKS = ("①", "②", "③", "④", "⑤", "⑥")
CHECK_ALIASES = {**{k: m for k, m in zip("abcdef", CHECK_MARKS)}, **{str(i): m for i, m in enumerate(CHECK_MARKS, 1)}}
MAX_TEXT = 200
REPEAT_DAYS = 30
NEAR_SCORE = 7
READBACK_TOKENS = 600
GOAL_KO = "많은 매매법을 시험해 결국 돈을 잃지 않는 매매법을 찾는다"
CHECK_STATUSES = ("ok", "bad_spec", "refused", "cannot_express", "missing", "duplicate", "repeat", "near_duplicate",
                  "unchecked")
CHECK_KO = {"ok": "시험 후보", "bad_spec": "문법 밖", "refused": "시험 대상 아님", "cannot_express": "문법으로 못 옮김",
            "missing": "아이디어 없음(답이 잘림)", "duplicate": "이미 시험함", "repeat": "같은 아이디어가 이미 후보(그 아이디어를 밈)",
            "near_duplicate": "비슷한 실패 시험 있음", "unchecked": "검사 못 함(연구실 쪽에서 다시 검사)"}
QUEUE_KO = {"candidate": "후보", "queued": "오늘 시험 줄", "not_picked": "이번엔 안 뽑힘", "skipped": "시험 후보 아님"}
# check statuses that can be picked: 'unchecked' too (the agents side checks it: labintake.canon)
PICKABLE = ("ok", "unchecked")
ROUND_KINDS = ("factory", "deep")
DEEP_BONUS = 1.0                    # slot_pick: the daily deep debate's idea (Opus, three calls) scores this much more

SCHEMA = """
CREATE TABLE IF NOT EXISTS debate_lab_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    question_kind TEXT,
    question_key TEXT,
    question_ko TEXT,
    engine TEXT NOT NULL,
    strategy TEXT,
    spec_json TEXT,
    spec_hash TEXT,
    description_ko TEXT,
    claim_ko TEXT,
    pro_ko TEXT,
    con_ko TEXT,
    con_check TEXT,
    backs INTEGER,
    weak_json TEXT,
    check_status TEXT NOT NULL,
    check_ko TEXT,
    old_trial_id INTEGER,
    queue_status TEXT NOT NULL DEFAULT 'candidate',
    queue_ko TEXT,
    slot TEXT,
    score REAL,
    lab_status TEXT,
    lab_trial_id INTEGER,
    lab_test_number INTEGER,
    lab_result_ko TEXT,
    lab_detail TEXT,
    lab_ts INTEGER,
    settled_side TEXT,
    con_check_hit INTEGER
);
CREATE INDEX IF NOT EXISTS debate_lab_ideas_queue ON debate_lab_ideas (queue_status, id);
CREATE INDEX IF NOT EXISTS debate_lab_ideas_hash ON debate_lab_ideas (spec_hash);
"""


# added columns (ALTER TABLE ADD COLUMN when missing; older rows keep NULL): round_kind = the kind of round that wrote
# the idea ('factory' = a regular round, 'deep' = the daily deep debate)
ADDED_COLUMNS = (("round_kind", "TEXT"),)


def ensure(conn: sqlite3.Connection) -> None:
    """debate.db's idea table (CREATE TABLE IF NOT EXISTS, then the added columns; the debate service is the file's only
    writer)."""
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(debate_lab_ideas)")}
    for col, typ in ADDED_COLUMNS:
        if col not in cols:
            conn.execute(f"ALTER TABLE debate_lab_ideas ADD COLUMN {col} {typ}")
    conn.commit()


# ---------------------------------------------------------------- sides and order (code, never the model)
def sides_for(n: int, roles: tuple = ROLES) -> dict:
    """{seat: side} for round ``n``: the last seat (the 심판) judges every round; the four specialists split 2-2, by
    pairing ``n % 3`` with the pairs swapped every three rounds, so the split changes every round and over any six
    rounds each specialist argues 찬성 three times and 반대 three times."""
    judge, spec = roles[-1], list(roles[:-1])
    if len(spec) != 4:
        raise ValueError("sides_for: four specialists and a judge")
    a, b = PAIRINGS[n % 3]
    pro, con = (a, b) if (n // 3) % 2 == 0 else (b, a)
    out = {spec[i]: "찬성" for i in pro}
    out.update({spec[i]: "반대" for i in con})
    out[judge] = "심판"
    return {r: out[r] for r in roles}


def factory_order(n: int, turns: int, roles: tuple = ROLES) -> list[str]:
    """Speakers of round ``n``: 찬성1, 반대1, 찬성2, 반대2, then replies alternating 반대 / 찬성, the 심판 last. ``turns``
    is clamped to 5-9, so every seat speaks at least once (debate-chat's 'all five speak' rule)."""
    sides = sides_for(n, roles)
    pro = [r for r in roles if sides[r] == "찬성"]
    con = [r for r in roles if sides[r] == "반대"]
    judge = next(r for r in roles if sides[r] == "심판")
    t = min(max(int(turns), MIN_TURNS), MAX_TURNS)
    out = [pro[0], con[0], pro[1], con[1]]
    replies = [con[0], pro[0], con[1], pro[1]]
    out += replies[:t - 5]
    return out + [judge]


SIDE_RULE_KO = ("찬성·반대는 자기 생각과 달라도 맡은 편만 변호(편 바꾸기·'둘 다 일리 있음'으로 비켜 가기 금지), "
                "반대는 떨어질 관문 칸(①~⑥) 하나를 꼭 짚음")


def sides_text(n: int, roles: tuple = ROLES) -> str:
    """The user text's side line (code): who plays which side this round, and the rule that an assigned side is argued
    as assigned (one model plays every role, so without it the sides drift to agreement: a straw man is the risk the
    plan names)."""
    s = sides_for(n, roles)
    pro = ", ".join(r for r in roles if s[r] == "찬성")
    con = ", ".join(r for r in roles if s[r] == "반대")
    judge = next(r for r in roles if s[r] == "심판")
    seat = "심판" if judge == "심판" else f"심판 {judge}"
    return f"찬성 {pro} / 반대 {con} / {seat} — 마지막 발언은 심판. {SIDE_RULE_KO}"


# ---------------------------------------------------------------- the idea check (code)
def _text(v: Any, n: int = MAX_TEXT) -> str:
    return R.clean_text(" ".join(v.split()))[:n] if isinstance(v, str) else ""


def _sql_in(values: tuple) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


def _row_id(v: Any) -> Optional[int]:
    """A positive integer that can be a debate_lab_ideas id (SQLite INTEGER), else None."""
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 2 ** 62 else None


def _lab_names() -> tuple:
    from ..strategy_view_defs import NAMES
    return tuple(NAMES)


def _ledger_newlab(agents_ro: Optional[sqlite3.Connection]) -> dict:
    """{spec hash: (latest trial id, its latest status)} of the lab's counted tests (read-only; {} when unreadable)."""
    if agents_ro is None:
        return {}
    try:
        rows = agents_ro.execute(
            "SELECT t.spec_hash, t.id, (SELECT status FROM trial_results WHERE id = (SELECT MAX(id) FROM trial_results "
            "WHERE trial_id = t.id)) FROM trials t WHERE t.kind = 'newlab' ORDER BY t.id").fetchall()
    except sqlite3.Error:
        return {}
    return {h: (int(i), st) for h, i, st in rows}


def _ledger_test(agents_ro: Optional[sqlite3.Connection], strategy: str, h: str) -> Optional[tuple]:
    if agents_ro is None:
        return None
    try:
        r = agents_ro.execute(
            "SELECT t.id, (SELECT status FROM trial_results WHERE id = (SELECT MAX(id) FROM trial_results "
            "WHERE trial_id = t.id)) FROM trials t WHERE t.kind = 'test' AND t.strategy = ? AND t.spec_hash = ? "
            "ORDER BY t.id DESC LIMIT 1", (strategy, h)).fetchone()
    except sqlite3.Error:
        return None
    return (int(r[0]), r[1]) if r else None


def _index(agents_ro: Optional[sqlite3.Connection]) -> list[dict]:
    return R.trial_index(agents_ro, "newlab") if agents_ro is not None else []


def similar(spec: dict, index: list[dict], most: int = 5) -> list[dict]:
    """A copy of rooms._similar's code score (rooms.py, not imported here): same entry 3, same values 1, same timeframe
    2, same direction 1, each shared filter kind 1 and identical filter 1; only the same entry family with a score of
    5 or more; the closest first."""
    def sig(sp):
        e = sp.get("entry") or {}
        fl = [f for f in sp.get("filters") or [] if isinstance(f, dict)]
        return e.get("family"), json.dumps(e.get("params"), sort_keys=True), sp.get("timeframe"), sp.get("direction"), fl
    fam, par, tf, d, fl = sig(spec)
    kinds = {f.get("kind") for f in fl}
    out = []
    for r in index:
        sp = r.get("spec") if isinstance(r.get("spec"), dict) else {}
        f2, p2, t2, d2, fl2 = sig(sp)
        score = 3 * (f2 == fam) + (f2 == fam and p2 == par) + 2 * (t2 == tf) + (d2 == d)
        score += len(kinds & {f.get("kind") for f in fl2}) + sum(1 for f in fl2 if f in fl)
        if f2 == fam and score >= 5:
            out.append({"trial_id": r["id"], "similarity": score, "status": r.get("status")})
    out.sort(key=lambda x: (-x["similarity"], -x["trial_id"]))
    return out[:most]


def library_overlap(spec: dict) -> bool:
    """A copy of rooms._library_overlap: both sides, no filter or only the EMA200 trend filter (library A/B tested
    exactly that, with other exits)."""
    fl = spec.get("filters") or []
    return spec.get("direction") == "both" and (not fl or fl == [{"kind": "trend_ema", "length": 200}])


def _canon(engine: str, raw: dict) -> tuple:
    """(canonical spec, hash, description, strategy) or a (status, Korean reason) refusal (status first element str)."""
    if engine == "newlab":
        from . import newlab as NL
        try:
            c = NL.normalize_spec(raw.get("spec"))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
            return ("bad_spec", str(exc)[:200] or "문법에 맞지 않음")
        if c["timeframe"] not in TFS:
            return ("refused", LI.REFUSE_5M_KO)
        return c, NL.spec_hash(c), NL.describe_ko(c), None
    from . import labtests as LT
    test = raw.get("test") if isinstance(raw.get("test"), dict) else raw.get("spec")
    if not isinstance(test, dict):
        return ("bad_spec", "36개 고쳐 보기 시험은 {template, strategy, timeframe, ...} 객체여야 합니다.")
    s = test.get("strategy") or raw.get("strategy")
    if not isinstance(s, str) or s not in _lab_names():
        return ("refused", "5년 시험은 잠긴 매매법 36개만 할 수 있습니다(딥시크·릴스·동전 계좌는 시험 대상 아님).")
    if test.get("template") in LT.DESCRIPTIVE:
        return ("refused", "설명용 시험(봉별 성적 보기)은 아무것도 가리지 못해 받지 않습니다.")
    try:
        c = LT.normalize_spec(test, s)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        return ("bad_spec", str(exc)[:200])
    if c.get("timeframe") not in TFS:
        return ("refused", LI.REFUSE_5M_KO)
    return c, R.spec_hash(c), LT.describe_ko(c), s


def check_idea(raw: Any, agents_ro: Optional[sqlite3.Connection], debate_conn: Optional[sqlite3.Connection],
               now: int) -> dict:
    """The code check of one round's lab_idea (model words are data): {engine, strategy, spec, spec_hash,
    description_ko, check_status, check_ko, old_trial_id?, repeat_of?, similar?, library_overlap?} plus the cleaned
    words (claim_ko, pro_ko, con_ko <= 200 chars, con_check one of ①-⑥, backs, weak)."""
    out: dict = {"engine": "none", "strategy": None, "spec": None, "spec_hash": None, "description_ko": "",
                 "check_status": "missing", "check_ko": CHECK_KO["missing"]}
    if not isinstance(raw, dict):
        return out
    cc = raw.get("con_check")
    cc = CHECK_ALIASES.get(str(cc).strip().lower(), cc) if isinstance(cc, (str, int)) and not isinstance(cc, bool) else cc
    # model words are data: a 'weak' that is not a list, or an id that is not a plausible row id, is dropped (never
    # a crash of the round, never an integer SQLite cannot store)
    weak_raw = raw.get("weak") if isinstance(raw.get("weak"), list) else []
    weak = [{"id": int(w["id"]), "why": _text(w.get("why"), 120)} for w in weak_raw[:2]
            if isinstance(w, dict) and _row_id(w.get("id")) is not None]
    backs = _row_id(raw.get("backs"))
    out.update(claim_ko=_text(raw.get("claim")), pro_ko=_text(raw.get("pro")), con_ko=_text(raw.get("con")),
               con_check=cc if cc in CHECK_MARKS else None, backs=backs, weak=weak)
    engine = raw.get("engine")
    if engine == "none":
        out.update(check_status="cannot_express", check_ko=CHECK_KO["cannot_express"], none_reason=_text(raw.get("reason")))
        return out
    if engine not in ("newlab", "labtest"):
        out.update(check_status="bad_spec", check_ko="engine은 newlab, labtest, none 중 하나")
        return out
    out["engine"] = engine
    try:
        got = _canon(engine, raw)
    except ImportError:                       # the lab modules cannot load here: the agents side checks it
        spec = raw.get("spec") if engine == "newlab" else raw.get("test")
        s = None
        if engine == "labtest" and isinstance(spec, dict):
            s = spec.get("strategy") if isinstance(spec.get("strategy"), str) else raw.get("strategy")
        out.update(check_status="unchecked", check_ko=CHECK_KO["unchecked"], spec=spec,
                   strategy=s if isinstance(s, str) and 0 < len(s) <= 64 else None)
        return out
    if isinstance(got[0], str):
        out.update(check_status=got[0], check_ko=got[1],
                   spec=raw.get("spec") if engine == "newlab" else raw.get("test"))
        return out
    spec, h, desc, s = got
    out.update(spec=spec, spec_hash=h, description_ko=desc, strategy=s, check_status="ok", check_ko=CHECK_KO["ok"])
    # 1. the ledger (agents3, read-only): an exact repeat is answered from it, never tested again
    old = _ledger_newlab(agents_ro).get(h) if engine == "newlab" else _ledger_test(agents_ro, s, h)
    if old is not None:
        out.update(check_status="duplicate", old_trial_id=old[0],
                   check_ko=f"이미 시험함: 장부 #{old[0]} ({old[1] or '결과 없음'})")
        return out
    # 2. this room's own ideas of the last 30 days: a repeat backs the earlier one
    if debate_conn is not None:
        try:
            r = debate_conn.execute("SELECT id FROM debate_lab_ideas WHERE spec_hash = ? AND ts >= ? AND check_status IN "
                                    "('ok', 'repeat') ORDER BY id LIMIT 1", (h, int(now) - REPEAT_DAYS * DAY_MS)).fetchone()
        except sqlite3.Error:
            r = None
        if r is not None:
            out.update(check_status="repeat", repeat_of=int(r[0]), backs=int(r[0]),
                       check_ko=f"같은 아이디어가 이미 후보: #{int(r[0])}를 미는 것으로 셈")
            return out
    # 3. a near-copy of a FAILED lab test (the lab skeptic's rule, by code); the library overlap only costs score
    if engine == "newlab":
        sim = similar(spec, _index(agents_ro))
        out["similar"] = sim[:3]
        out["library_overlap"] = library_overlap(spec)
        near = [x for x in sim if x["similarity"] >= NEAR_SCORE and x.get("status") == "failed"]
        if near:
            out.update(check_status="near_duplicate", old_trial_id=near[0]["trial_id"],
                       check_ko=f"비슷한 실패 시험 있음: 장부 #{near[0]['trial_id']} (닮은 점수 {near[0]['similarity']})")
    return out


def add_idea(conn: sqlite3.Connection, round_id: int, ts: int, question: Optional[dict], checked: dict,
             commit: bool = True, round_kind: Optional[str] = None) -> int:
    """Store one round's checked idea (debate.db). Only an 'ok' idea, or one this side could not check ('unchecked':
    the lab modules did not load; the agents side re-makes every spec and refuses what is outside the grammar), is a
    candidate for the daily pick. ``round_kind``: 'factory' or 'deep' (the daily deep debate's idea)."""
    q = question or {}
    cur = conn.execute(
        "INSERT INTO debate_lab_ideas (round_id, ts, question_kind, question_key, question_ko, engine, strategy, "
        "spec_json, spec_hash, description_ko, claim_ko, pro_ko, con_ko, con_check, backs, weak_json, check_status, "
        "check_ko, old_trial_id, queue_status, round_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (int(round_id), int(ts), q.get("kind"), q.get("key"), _text(q.get("question_ko"), 300), checked["engine"],
         checked.get("strategy"), None if checked.get("spec") is None else json.dumps(checked["spec"], ensure_ascii=False,
                                                                                     default=str),
         checked.get("spec_hash"), checked.get("description_ko") or "", checked.get("claim_ko", ""),
         checked.get("pro_ko", ""), checked.get("con_ko", ""), checked.get("con_check"), checked.get("backs"),
         json.dumps(checked.get("weak") or [], ensure_ascii=False), checked["check_status"], checked.get("check_ko"),
         checked.get("old_trial_id"), "candidate" if checked["check_status"] in PICKABLE else "skipped",
         round_kind if round_kind in ROUND_KINDS else None))
    if commit:
        conn.commit()
    return int(cur.lastrowid)


# ---------------------------------------------------------------- the daily pick
def _kst_hour_start(now: int) -> dt.datetime:
    return dt.datetime.fromtimestamp((int(now) + KST_MS) / 1000, tz=dt.timezone.utc)


def _closes(now: int, per_day: int) -> list[tuple]:
    """(close ms, 'am'|'pm') of the slots of yesterday, today and tomorrow (KST), oldest first."""
    k = _kst_hour_start(now)
    day0 = int(dt.datetime(k.year, k.month, k.day, tzinfo=dt.timezone.utc).timestamp() * 1000) - KST_MS
    hours = ((21, "pm"),) if per_day == 1 else ((9, "am"), (21, "pm"))
    return [(d + h * HOUR_MS, n) for d in (day0 - DAY_MS, day0, day0 + DAY_MS) for h, n in hours]


def _slot(close: int, name: str, per_day: int) -> tuple:
    span = DAY_MS if per_day == 1 else 12 * HOUR_MS
    return f"slot:{P.kst_day(close - 1)}:{name}", close - span, close


def last_slot(now: int, per_day: int) -> Optional[tuple]:
    """(slot key, start ms, close ms) of the latest slot closed at or before ``now``; None when per_day is 0.
    per_day 1: one slot closing 21:00 KST covering the 24 h before; per_day 2: 09:00 and 21:00, 12 h each."""
    if per_day <= 0:
        return None
    t, n = [(t, n) for t, n in _closes(now, per_day) if t <= now][-1]
    return _slot(t, n, min(per_day, 2))


def open_slot(now: int, per_day: int) -> Optional[tuple]:
    """The slot ``now`` falls in (it closes after ``now``); None when per_day is 0."""
    if per_day <= 0:
        return None
    t, n = [(t, n) for t, n in _closes(now, per_day) if t > now][0]
    return _slot(t, n, min(per_day, 2))


def _backs_weak(conn: sqlite3.Connection, ids: list[int]) -> dict:
    out = {i: [0, 0] for i in ids}
    for backs, weak in conn.execute("SELECT backs, weak_json FROM debate_lab_ideas WHERE backs IS NOT NULL "
                                    "OR (weak_json IS NOT NULL AND weak_json != '[]')"):
        if backs in out:
            out[backs][0] += 1
        try:
            for w in json.loads(weak or "[]"):
                if isinstance(w, dict) and w.get("id") in out:
                    out[w["id"]][1] += 1
        except (TypeError, ValueError):
            continue
    return out


def _score(row: dict, backs: int, weak: int, fams: set, combos: set) -> float:
    s = 1.0 + backs - weak
    if row["engine"] == "newlab":
        try:
            sp = json.loads(row["spec_json"] or "{}")
        except (TypeError, ValueError):
            sp = {}
        if ((sp.get("entry") or {}).get("family")) not in fams:
            s += 1
        if json.dumps(sp.get("filters") or [], sort_keys=True) not in combos:
            s += 1
        if library_overlap(sp):
            s -= 2
    if row.get("question_kind") in ("big_losses", "worst_vs_flip", "loss_traits"):
        s += 0.5
    if row.get("round_kind") == "deep":           # the day's most important question, argued in three separate calls
        s += DEEP_BONUS
    return s


def slot_pick(conn: sqlite3.Connection, agents_ro: Optional[sqlite3.Connection], now: int, per_day: int) -> dict:
    """At most one idea per slot to the lab intake queue: among the slot's candidates (check 'ok'), score = 1 + backs -
    weak + 1 (entry family never in the ledger) + 1 (filter combination never tested) - 2 (library overlap) + 0.5
    (question big_losses / worst_vs_flip / loss_traits) + DEEP_BONUS (the daily deep debate's idea); the best with
    score >= 1 -> 'queued', ties to the oldest; the others
    'not_picked' with a code reason. Older candidates whose slot passed are 'not_picked' too. Idempotent (only
    'candidate' rows are looked at). Returns {slot, queued, not_picked}."""
    sl = last_slot(now, per_day)
    out: dict = {"slot": sl[0] if sl else None, "queued": None, "not_picked": []}
    if sl is None:
        return out
    key, start, close = sl
    cols = [c[1] for c in conn.execute("PRAGMA table_info(debate_lab_ideas)")]
    rows = [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT * FROM debate_lab_ideas WHERE queue_status = 'candidate' AND check_status IN {_sql_in(PICKABLE)} "
        "AND ts < ? ORDER BY id", (close,)).fetchall()]
    stale = [r for r in rows if r["ts"] < start]
    rows = [r for r in rows if r["ts"] >= start]
    # one pick per slot, ever: an idea stored after the slot was picked (a round that began before the close and
    # ended after it) is not a second pick of the same slot
    taken = conn.execute("SELECT id FROM debate_lab_ideas WHERE queue_status = 'queued' AND slot = ? ORDER BY id LIMIT 1",
                         (key,)).fetchone()
    if taken is not None:
        try:
            for r in rows:
                conn.execute("UPDATE debate_lab_ideas SET queue_status = 'not_picked', slot = ?, queue_ko = ? WHERE id = ?",
                             (key, f"하루 {per_day}개 한도: 이번엔 #{int(taken[0])}", r["id"]))
                out["not_picked"].append(r["id"])
            for r in stale:
                conn.execute("UPDATE debate_lab_ideas SET queue_status = 'not_picked', queue_ko = ? WHERE id = ?",
                             ("뽑는 시각을 지나 이번엔 시험하지 않음", r["id"]))
                out["not_picked"].append(r["id"])
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return out
    fams, combos = set(), set()
    for r in _index(agents_ro):
        sp = r.get("spec") if isinstance(r.get("spec"), dict) else {}
        fams.add((sp.get("entry") or {}).get("family"))
        combos.add(json.dumps(sp.get("filters") or [], sort_keys=True))
    bw = _backs_weak(conn, [r["id"] for r in rows])
    scored = sorted(((_score(r, *bw[r["id"]], fams, combos), r) for r in rows), key=lambda x: (-x[0], x[1]["id"]))
    best = scored[0] if scored and scored[0][0] >= 1 else None
    try:
        for s, r in scored:
            if best is not None and r["id"] == best[1]["id"]:
                conn.execute("UPDATE debate_lab_ideas SET queue_status = 'queued', slot = ?, score = ?, queue_ko = ? "
                             "WHERE id = ?", (key, s, f"하루 {per_day}개 몫: 이번 칸에서 뽑힘 (점수 {s:g})", r["id"]))
                out["queued"] = r["id"]
            else:
                why = (f"하루 {per_day}개 한도: 이번엔 #{best[1]['id']}" if best is not None
                       else f"점수 {s:g}: 1 미만이라 이번 칸은 시험하지 않음")
                conn.execute("UPDATE debate_lab_ideas SET queue_status = 'not_picked', slot = ?, score = ?, queue_ko = ? "
                             "WHERE id = ?", (key, s, why, r["id"]))
                out["not_picked"].append(r["id"])
        for r in stale:
            conn.execute("UPDATE debate_lab_ideas SET queue_status = 'not_picked', queue_ko = ? WHERE id = ?",
                         ("뽑는 시각을 지나 이번엔 시험하지 않음", r["id"]))
            out["not_picked"].append(r["id"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return out


# ---------------------------------------------------------------- results back from the lab (agents3, read-only)
def settle(card: dict, con_check: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """(settled side, con_check hit) of a tested idea: 찬성 when the test passed, 반대 when it failed; None for a
    duplicate, a reuse, a test that did not count or an error (no new evidence). The hit: the check 반대 named really
    failed (1) or not (0)."""
    if (card or {}).get("status") != "tested":
        return None, None
    d = card.get("detail") or {}
    v = d.get("verdict")
    side = "찬성" if v == "passed" else ("반대" if v == "failed" else None)
    hit = None
    if side is not None and con_check in CHECK_MARKS:
        hit = int(con_check in (d.get("failed_checks") or []))
    return side, hit


def result_line_ko(detail: Any, status: str = "tested", trial_id: Optional[int] = None) -> str:
    """The code's one-line result (labintake.result_ko: never model words)."""
    return LI.result_ko(detail, status, trial_id)


def _debate_cards(agents_ro: Optional[sqlite3.Connection], limit: int = 200) -> dict:
    """{debate idea id: the intake card} of the ideas the agents took from this room."""
    out = {}
    for c in LI.view(agents_ro, "debate", limit):
        ref = str(c.get("source_ref") or "")
        if ref.startswith("debate:") and ref[7:].isdigit():
            out.setdefault(int(ref[7:]), c)
    return out


def sync_lab(conn: sqlite3.Connection, agents_ro: Optional[sqlite3.Connection], now: int) -> int:
    """Write each taken idea's lab status, trial, test number, code result line and the graded sides into debate.db
    (from agents3 read-only; missing tables = nothing). Returns the number of rows changed."""
    cards = _debate_cards(agents_ro)
    if not cards:
        return 0
    n = 0
    try:
        for iid, c in cards.items():
            row = conn.execute("SELECT lab_status, lab_trial_id, con_check FROM debate_lab_ideas WHERE id = ?",
                               (iid,)).fetchone()
            if row is None or (row[0] == c["status"] and row[1] == c["trial_id"]):
                continue
            side, hit = settle(c, row[2])
            d = c.get("detail") or {}
            conn.execute("UPDATE debate_lab_ideas SET lab_status = ?, lab_trial_id = ?, lab_test_number = ?, "
                         "lab_result_ko = ?, lab_detail = ?, lab_ts = ?, settled_side = ?, con_check_hit = ? WHERE id = ?",
                         (c["status"], c["trial_id"], d.get("test_number") if isinstance(d.get("test_number"), int) else None,
                          c["result_ko"][:300], json.dumps(d, ensure_ascii=False, default=str)[:4000], c["status_ts"],
                          side, hit, iid))
            n += 1
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return n


def _lab_numbers(agents_ro: Optional[sqlite3.Connection]) -> dict:
    # every counted 'newlab' trial (actions.newlab_count: rows, not distinct specs)
    n = R.trial_count(agents_ro, kinds=("newlab",)) if agents_ro is not None else 0
    try:
        from . import newlab as NL
        mp = NL.max_passable_n()
    except Exception:  # noqa: BLE001  (the lab module is optional here)
        mp = None
    return {"tests_so_far": n, "next_p": round(0.05 / (n + 1), 8), "can_still_pass": None if mp is None else n <= mp}


def readback(conn: sqlite3.Connection, agents_ro: Optional[sqlite3.Connection], now: int, per_day: int = 1) -> dict:
    """The packet's 'idea_factory' block (about 600 tokens at most): the goal, today's pick and candidates, the
    candidates of the open slot (backs / weak), the latest lab results of this room's ideas (code lines), why lab
    tests fail, the lab's count and next threshold, and the room's record (tested, passed, which side was right,
    how often the check 반대 named really failed)."""
    sl = open_slot(now, per_day)
    start = sl[1] if sl else now - DAY_MS
    cols = [c[1] for c in conn.execute("PRAGMA table_info(debate_lab_ideas)")]
    open_rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT * FROM debate_lab_ideas WHERE queue_status = 'candidate' AND ts >= ? ORDER BY id DESC LIMIT 6",
        (start,)).fetchall()]
    bw = _backs_weak(conn, [r["id"] for r in open_rows])
    queued_today = conn.execute("SELECT COUNT(*) FROM debate_lab_ideas WHERE queue_status = 'queued' AND slot LIKE ?",
                                (f"slot:{P.kst_day(now)}:%",)).fetchone()[0]
    cards = _debate_cards(agents_ro)
    done = [c for c in cards.values() if c["status"] in ("tested", "reused", "duplicate")]
    done.sort(key=lambda c: -c["status_ts"])
    recent = []
    for c in done[:5]:
        d = c.get("detail") or {}
        recent.append({"desc": c["description_ko"][:90], "verdict": d.get("verdict"),
                       "failed": d.get("failed_checks"), "p1_mean_roe": (d.get("p1") or {}).get("mean_roe"),
                       "coinflip_diff": (d.get("p1") or {}).get("coinflip_diff"),
                       "test_no": d.get("test_number"), "line": c["result_ko"][:140]})
    rec = {"tested": 0, "passed": 0, "찬성_right": 0, "반대_right": 0, "con_check_hits": 0, "con_check_graded": 0}
    # the base rates: lab passes are near 0, so 반대 is 'right' almost always by the base rate alone; each side's
    # count is shown next to what the lab's usual rates would give (the pass rate; the named check's usual fail share)
    base = LI.base_rates(agents_ro)
    exp_pro = exp_hit = 0.0
    for iid, c in cards.items():
        if c["status"] != "tested":
            continue
        rec["tested"] += 1
        row = conn.execute("SELECT con_check FROM debate_lab_ideas WHERE id = ?", (iid,)).fetchone()
        side, hit = settle(c, row[0] if row else None)
        rates = base.get(c.get("engine")) or {}
        rec["passed"] += int(side == "찬성")
        if side:
            rec[f"{side}_right"] += 1
            exp_pro += float(rates.get("pass_rate") or 0.0)
        if hit is not None:
            rec["con_check_graded"] += 1
            rec["con_check_hits"] += hit
            exp_hit += float((rates.get("fail_share") or {}).get(row[0]) or 0.0)
    graded = rec["찬성_right"] + rec["반대_right"]
    rec["찬성_expected"] = round(exp_pro, 2)                  # what the lab's pass rate alone gives 찬성
    rec["반대_expected"] = round(graded - exp_pro, 2)         # ... and 반대
    rec["con_check_expected"] = round(exp_hit, 2)            # hits the named checks' usual fail shares give
    rec["base_note"] = "_expected = 연구실 평소 비율(통과율, 그 칸의 평소 탈락률)만으로 맞힐 수. 그보다 많아야 실력"
    wf = LI.why_fail(agents_ro)
    out = {"goal": GOAL_KO,
           "today": {"queued": f"{queued_today}/{per_day}", "candidates": len(open_rows)},
           "slot_candidates": [{"id": r["id"], "desc": (r["description_ko"] or "")[:90], "backs": bw[r["id"]][0],
                                "weak": bw[r["id"]][1]} for r in open_rows],
           "recent_results": recent,
           "why_fail": {"tests": wf["tests"], "failed": wf["failed"]},
           "lab": _lab_numbers(agents_ro), "record": rec,
           "note": "같은 아이디어·이미 떨어진 것과 같은 것은 금지(이미 있는 후보는 backs로 밈). 한 AI가 다섯 역할을 맡은 편 기록이며 사람 성적이 아님"}
    for ml, ms in ((6, 120), (4, 90), (3, 70)):
        if P.estimate_tokens(P.compact_json(out)) <= READBACK_TOKENS:
            break
        out = P.shrink(out, ml, ms)
    return out
