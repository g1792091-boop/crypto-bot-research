"""The 24-hour debate room's hypotheses: a small fixed menu, validated and graded by code (never by the model).

The model may only pick one of ``KINDS`` and fill its parameters; anything else is dropped (and recorded as dropped).
Grading reads paper3.db and daily3.db READ-ONLY once the hypothesis' horizon is reached and writes only the debate
service's own database (debate.db, table debate_hypotheses). Nothing here can place an order or touch a bot database.

Kinds (parameters, what is graded)
- ``strategy_roe_sign``  {strategy, tf, op "<"|">", n 5..50}: the mean ROE of that account's NEXT n closed trades is
                         below / above 0.
- ``best_vs_normal``     {n 50..2000}: over the next n closed trades of the strategy accounts, the mean return per unit
                         of exposure (pnl / (margin x leverage), docs/levrule-eval.md's r) of the 좋은 자리 ("best")
                         tier is higher than the 보통 ("normal") tier. Fewer than 5 trades in a tier: void.
- ``parity_streak``      {days 1..14, accounts optional}: the next ``days`` nightly checks (daily3.db reports) all show
                         0 replay mismatches (the report's own count, early_kline and restart gaps excluded).
- ``busts_by_day``       {day 1..60, max_busts 0..50}: when the run reaches day D, at most max_busts strategy accounts
                         are bust.

A hit or a miss is a number about ONE claim; a speaker's hit rate (``scoreboard``) is a small-sample number until
``SMALL_GRADED`` graded claims, and never a verdict on a person or on a strategy.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
from typing import Any, Optional

DAY_MS = 86_400_000
KST_MS = 9 * 3_600_000
TRADE_TFS = ("15m", "30m", "1h", "4h")
KINDS = ("strategy_roe_sign", "best_vs_normal", "parity_streak", "busts_by_day")
EXPIRE_DAYS = 21               # a claim whose horizon is not reached by then is 'expired' (not graded)
MAX_OPEN = 30                  # open claims at once (bounded table, bounded grading work)
MIN_TIER_TRADES = 5            # best_vs_normal: trades each tier needs in the window
SMALL_GRADED = 10              # fewer graded claims than this: a speaker's hit rate is a small sample
NAME_RE = re.compile(r"^[A-Za-z0-9_]{2,40}$")

MENU_KO = (
    "고를 수 있는 가설 종류는 아래 4가지뿐입니다. 이 밖의 것, 숫자가 범위를 벗어난 것은 코드가 버립니다.\n"
    '1. {"kind":"strategy_roe_sign","params":{"strategy":"N17_KC_RSI","tf":"1h","op":"<","n":20}} '
    "= 그 매매법·봉 계좌의 앞으로 청산 n건(5~50)의 평균 ROE가 0보다 작다(<) / 크다(>)\n"
    '2. {"kind":"best_vs_normal","params":{"n":200}} '
    "= 앞으로 청산되는 전략 계좌 거래 n건(50~2000)에서 좋은 자리 거래의 노출 1단위당 평균 손익이 보통 거래보다 크다\n"
    '3. {"kind":"parity_streak","params":{"days":3}} '
    "= 앞으로 밤 점검 days번(1~14)이 모두 재계산 불일치 0개다\n"
    '4. {"kind":"busts_by_day","params":{"day":20,"max_busts":2}} '
    "= 실험 D+day(현재보다 뒤, 60 이하)에 파산한 전략 계좌가 max_busts개(0~50) 이하다")


# ---------------------------------------------------------------- helpers
def _int(v: Any, lo: int, hi: int) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not isinstance(v, int) or not lo <= v <= hi:
        return None
    return v


def kst_day(ms: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def run_start(paper: Optional[sqlite3.Connection]) -> Optional[int]:
    """The run's start (first strategy / coin-flip account), like checkpoint.run_facts; None when unknown."""
    if paper is None:
        return None
    try:
        r = paper.execute("SELECT MIN(created_ts) FROM accounts WHERE kind IN ('strategy', 'random')").fetchone()
    except sqlite3.Error:
        return None
    return int(r[0]) if r and r[0] is not None else None


def _max_trade_id(paper: sqlite3.Connection, account: Optional[str] = None) -> int:
    if account:
        r = paper.execute("SELECT MAX(id) FROM trades WHERE account_id = ?", (account,)).fetchone()
    else:
        r = paper.execute("SELECT MAX(t.id) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                          "WHERE a.kind = 'strategy'").fetchone()
    return int(r[0]) if r and r[0] is not None else 0


# ---------------------------------------------------------------- validation (at proposal time)
def validate(item: Any, paper: Optional[sqlite3.Connection], daily: Optional[sqlite3.Connection],
             now_ms: int) -> tuple[Optional[dict], str, str]:
    """(clean claim, '', horizon text) for a claim that is on the menu with parameters in range, else
    (None, why it was dropped, ''). The clean claim is {"kind", "params"}: the params hold what the grader needs,
    including the baselines code read now (``base_id``, ``base_day``). Never raises."""
    try:
        return _validate(item, paper, daily, now_ms)
    except (sqlite3.Error, TypeError, ValueError, KeyError) as exc:
        return None, f"검증 중 오류: {type(exc).__name__}", ""


def _validate(item: Any, paper, daily, now_ms: int) -> tuple[Optional[dict], str, str]:
    if not isinstance(item, dict):
        return None, "가설이 객체가 아님", ""
    kind, p = item.get("kind"), item.get("params")
    if kind not in KINDS:
        return None, f"메뉴에 없는 종류: {str(kind)[:40]}", ""
    if not isinstance(p, dict):
        return None, "params가 객체가 아님", ""
    if kind == "strategy_roe_sign":
        s, tf, op, n = p.get("strategy"), p.get("tf"), p.get("op"), _int(p.get("n"), 5, 50)
        if not isinstance(s, str) or not NAME_RE.match(s) or tf not in TRADE_TFS or op not in ("<", ">") or n is None:
            return None, "strategy_roe_sign 값이 범위 밖(strategy, tf 15m/30m/1h/4h, op <|>, n 5~50)", ""
        if paper is None:
            return None, "paper3.db를 읽을 수 없어 확인 못 함", ""
        aid = f"{s}@{tf}"
        r = paper.execute("SELECT 1 FROM accounts WHERE account_id = ? AND kind = 'strategy'", (aid,)).fetchone()
        if r is None:
            return None, f"그런 전략 계좌가 없음: {aid}", ""
        return ({"kind": kind, "params": {"strategy": s, "tf": tf, "op": op, "n": n, "account": aid,
                                          "base_id": _max_trade_id(paper, aid)}},
                "", f"{aid}의 다음 {n}건 청산")
    if kind == "best_vs_normal":
        n = _int(p.get("n"), 50, 2000)
        if n is None:
            return None, "best_vs_normal 값이 범위 밖(n 50~2000)", ""
        if paper is None:
            return None, "paper3.db를 읽을 수 없어 확인 못 함", ""
        return ({"kind": kind, "params": {"n": n, "base_id": _max_trade_id(paper)}}, "",
                f"다음 {n}건 청산(전략 계좌 전체)")
    if kind == "parity_streak":
        days, acc = _int(p.get("days"), 1, 14), p.get("accounts")
        if days is None or (acc is not None and _int(acc, 1, 400) is None):
            return None, "parity_streak 값이 범위 밖(days 1~14)", ""
        base = kst_day(now_ms - DAY_MS)                      # no nightly report yet: the checks of today on count
        if daily is not None:
            r = daily.execute("SELECT MAX(day) FROM reports").fetchone()
            if r and r[0]:
                base = str(r[0])
        clean = {"days": days, "base_day": base}
        if acc is not None:
            clean["accounts"] = int(acc)
        return {"kind": kind, "params": clean}, "", f"앞으로 밤 점검 {days}번"
    day, k = _int(p.get("day"), 1, 60), _int(p.get("max_busts"), 0, 50)       # busts_by_day
    if day is None or k is None:
        return None, "busts_by_day 값이 범위 밖(day 1~60, max_busts 0~50)", ""
    start = run_start(paper)
    if start is None:
        return None, "실험 시작 시각을 알 수 없음", ""
    if (now_ms - start) / DAY_MS >= day:
        return None, "그 날짜는 이미 지났음", ""
    return {"kind": kind, "params": {"day": day, "max_busts": k, "start_ts": start}}, "", f"D+{day}"


# ---------------------------------------------------------------- grading (when the horizon is reached)
OLD_RUN_KO = "이전 실행에서 한 주장(실험을 다시 시작해 새 실행 숫자로 채점하지 않음)"


def grade(kind: str, params: dict, ts: int, paper: Optional[sqlite3.Connection], daily: Optional[sqlite3.Connection],
          now_ms: int) -> Optional[dict]:
    """None while the horizon is not reached, else {"status": "graded"|"void"|"expired", "outcome": "hit"|"miss"|
    "void: ..."|"expired", "detail": {...}}. Never raises (an unreadable database leaves the claim open).
    A claim made before the current run started (paper v4 restart, owners 2026-10-05: its run_start differs) is
    void, whatever its kind: it is never graded against the new run's accounts."""
    try:
        start = run_start(paper)
        if start is not None and (int(ts) < start or (kind == "busts_by_day" and params.get("start_ts") is not None
                                                       and int(params["start_ts"]) != start)):
            return _void(OLD_RUN_KO, claim_ts=int(ts), run_start=start)
        res = _grade(kind, params, paper, daily, now_ms)
    except (sqlite3.Error, TypeError, ValueError, KeyError):
        return None
    if res is None and kind != "busts_by_day" and now_ms - int(ts) > EXPIRE_DAYS * DAY_MS:
        return {"status": "expired", "outcome": "expired", "detail": {"why": f"{EXPIRE_DAYS}일 안에 기준에 못 미침"}}
    return res


def _graded(hit: bool, **detail) -> dict:
    return {"status": "graded", "outcome": "hit" if hit else "miss", "detail": detail}


def _void(why: str, **detail) -> dict:
    return {"status": "void", "outcome": f"void: {why}", "detail": {"why": why, **detail}}


def _grade(kind: str, p: dict, paper, daily, now_ms: int) -> Optional[dict]:
    if kind == "strategy_roe_sign":
        if paper is None:
            return None
        base, n, aid = int(p["base_id"]), int(p["n"]), p["account"]
        if _max_trade_id(paper, aid) < base:
            return _void("DB가 새로 시작됨(거래 번호가 줄어듦)")
        rows = paper.execute("SELECT roe FROM trades WHERE account_id = ? AND id > ? ORDER BY id LIMIT ?",
                             (aid, base, n)).fetchall()
        if len(rows) < n:
            return None
        mean = statistics.fmean(float(r[0]) for r in rows)
        return _graded(mean < 0 if p["op"] == "<" else mean > 0, mean_roe=round(mean, 5), trades=n)
    if kind == "best_vs_normal":
        if paper is None:
            return None
        base, n = int(p["base_id"]), int(p["n"])
        if _max_trade_id(paper) < base:
            return _void("DB가 새로 시작됨(거래 번호가 줄어듦)")
        rows = paper.execute("SELECT t.pnl, t.leverage, t.data FROM trades t JOIN accounts a ON a.account_id = "
                             "t.account_id WHERE a.kind = 'strategy' AND t.id > ? ORDER BY t.id LIMIT ?",
                             (base, n)).fetchall()
        if len(rows) < n:
            return None
        grp: dict[str, list[float]] = {"best": [], "normal": []}
        for pnl, lev, data in rows:
            try:
                d = json.loads(data)
                tier, margin = d.get("tier"), float(d.get("margin") or 0)
                lev = float(lev)
            except (TypeError, ValueError, AttributeError):
                continue
            if tier in grp and margin > 0 and lev > 0:
                grp[tier].append(float(pnl) / (margin * lev))
        if min(len(grp["best"]), len(grp["normal"])) < MIN_TIER_TRADES:
            return _void("한쪽 묶음이 5건 미만(표본이 너무 작음)", best=len(grp["best"]), normal=len(grp["normal"]))
        mb, mn = statistics.fmean(grp["best"]), statistics.fmean(grp["normal"])
        return _graded(mb > mn, mean_r_best=round(mb, 7), mean_r_normal=round(mn, 7),
                       best=len(grp["best"]), normal=len(grp["normal"]))
    if kind == "parity_streak":
        if daily is None:
            return None
        days = int(p["days"])
        rows = daily.execute("SELECT day, data FROM reports WHERE day > ? ORDER BY day LIMIT ?",
                             (str(p["base_day"]), days * 3)).fetchall()
        ok = 0
        for day, data in rows:
            try:
                par = json.loads(data).get("parity")
            except (TypeError, ValueError, AttributeError):
                continue
            if not isinstance(par, dict) or "mismatched_accounts" not in par:
                continue                                       # no check that night: it counts neither way
            if p.get("accounts") is not None and par.get("accounts") != p["accounts"]:
                return _graded(False, day=day, accounts=par.get("accounts"), want=p["accounts"])
            if int(par["mismatched_accounts"]) > 0:
                return _graded(False, day=day, mismatched=int(par["mismatched_accounts"]))
            ok += 1
            if ok >= days:
                return _graded(True, nights=ok)
        return None
    if kind == "busts_by_day":                                     # the account count at the moment D is reached
        if paper is None or now_ms < int(p["start_ts"]) + int(p["day"]) * DAY_MS:
            return None
        st = paper.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        eng = json.loads(st[0])["engines"] if st else {}
        ids = {r[0] for r in paper.execute("SELECT account_id FROM accounts WHERE kind = 'strategy'")}
        busts = sum(1 for a, e in eng.items() if a in ids and e.get("bust"))
        return _graded(busts <= int(p["max_busts"]), busts=busts)
    return None


# ---------------------------------------------------------------- the debate database's side
def grade_open(db: sqlite3.Connection, paper: Optional[sqlite3.Connection], daily: Optional[sqlite3.Connection],
               now_ms: int) -> int:
    """Grade every open claim whose horizon is reached; returns how many changed. Writes only ``db``."""
    changed = 0
    for hid, ts, kind, pj in db.execute("SELECT id, ts, kind, params_json FROM debate_hypotheses "
                                        "WHERE status = 'open' ORDER BY id").fetchall():
        try:
            params = json.loads(pj)["params"]
        except (TypeError, ValueError, KeyError):
            res = {"status": "void", "outcome": "void: 저장된 값을 읽지 못함", "detail": {}}
        else:
            res = grade(kind, params, ts, paper, daily, now_ms)
        if res is None:
            continue
        db.execute("UPDATE debate_hypotheses SET status = ?, outcome = ?, graded_ts = ? WHERE id = ?",
                   (res["status"], res["outcome"] + ("" if not res.get("detail") else " " + json.dumps(
                       res["detail"], ensure_ascii=False, separators=(",", ":"))[:200]), int(now_ms), hid))
        changed += 1
    return changed


def scoreboard(db: sqlite3.Connection) -> dict:
    """Per speaker: graded claims, hits and the hit rate, plus the totals; ``small`` = fewer than SMALL_GRADED graded
    (a small sample: no conclusion about anyone)."""
    out: dict[str, dict] = {}
    for sp, outcome in db.execute("SELECT speaker, outcome FROM debate_hypotheses WHERE status = 'graded'"):
        b = out.setdefault(sp or "?", {"graded": 0, "hit": 0})
        b["graded"] += 1
        b["hit"] += str(outcome).startswith("hit")
    for b in out.values():
        b["rate"] = round(b["hit"] / b["graded"], 3) if b["graded"] else None
        b["small"] = b["graded"] < SMALL_GRADED
    tot_g, tot_h = sum(b["graded"] for b in out.values()), sum(b["hit"] for b in out.values())
    counts = {s: n for s, n in db.execute("SELECT status, COUNT(*) FROM debate_hypotheses GROUP BY status")}
    return {"speakers": out, "graded": tot_g, "hit": tot_h, "rate": round(tot_h / tot_g, 3) if tot_g else None,
            "small": tot_g < SMALL_GRADED, "by_status": counts, "small_below": SMALL_GRADED}


# ---------------------------------------------------------------- Korean wording for the dashboard
def claim_ko(kind: str, params_json: Any) -> str:
    """One Korean line for a stored claim ('' when unreadable)."""
    try:
        p = (json.loads(params_json) or {}).get("params") or {}
    except (TypeError, ValueError, AttributeError):
        return ""
    try:
        if kind == "strategy_roe_sign":
            return f"{p['account']}의 앞으로 청산 {p['n']}건 평균 ROE가 0보다 {'작다' if p['op'] == '<' else '크다'}"
        if kind == "best_vs_normal":
            return f"앞으로 {p['n']}건에서 좋은 자리 거래의 노출당 평균 손익이 보통 거래보다 크다"
        if kind == "parity_streak":
            return f"앞으로 밤 점검 {p['days']}번이 모두 재계산 불일치 0개다"
        if kind == "busts_by_day":
            return f"D+{p['day']}에 파산한 전략 계좌가 {p['max_busts']}개 이하다"
    except (KeyError, TypeError):
        return ""
    return ""


def status_ko(status: str, outcome: Optional[str]) -> str:
    if status == "graded":
        return "맞음" if str(outcome).startswith("hit") else "틀림"
    return {"open": "채점 대기", "void": "무효(표본 부족 등)", "expired": "기한 지남(채점 안 함)",
            "dropped": "메뉴에 맞지 않아 버림"}.get(status, status)
