"""The dashboard's '분석' tab and its neighbours: read-only views over the analyses the agents already compute
(paperbot/agents/*), the health card, the alert history, the 45-question checklist and the 24-hour debate room.

Everything here only READS: paper3.db, daily3.db, checkpoint.db, agents3.db, inbox.db (price alerts), liq.db,
flow.db, market.db are opened read-only (``mode=ro``); nothing is written to any bot database and no model is
called. The analyses are the agents' own functions (riskreward, survival, readiness, shock, compare, entrymoment,
synergy): the numbers are the same the staff read in their meetings.

Cost: the heavy ones (Monte Carlo, combination search, entry features) run in ONE background thread at a time
(``Heavy``): a request waits at most ``WAIT_S`` seconds, else it answers ``{"pending": true}`` and the page asks
again; a result is kept ``ttl`` seconds (5-15 minutes) for every viewer, an error 60 seconds. Once a result exists, an
expired one is answered at once (``stale: true``) while it is recomputed in the background, so a view that takes
seconds on a month of data (risk, shadows, synergy) holds a request only the very first time. The shadows view is
kept per daily3 report (it changes only when the nightly check writes a new one).

Routes (registered by ``register``; all behind the dashboard login like every other /api route):

- ``GET /api/time``                 the server clock (the bar-close countdown strip corrects the phone's clock with it)
- ``GET /api/analysis/health``      ① one card: bot heartbeat, 1m data, signals, agents, nightly check (parity with the
                                    early_kline label), checkpoint, AI usage, scheduled-job failure warnings
- ``GET /api/analysis/risk``        ② payoff, breakeven win rate, gap, give-back (agents/riskreward.py) and drawdown,
                                    bust probability (agents/survival.py) of the strategy accounts and the coin flips
- ``GET /api/analysis/readiness``   ③ the real-trading conditions table (agents/readiness.py)
- ``GET /api/analysis/shock``       ④ the shock test (agents/shock.py dash_view)
- ``GET /api/analysis/map``         ⑤ coin / side / timeframe / session / weekday / regime (agents/compare.py), plus the
                                    volatility and weekday buckets of agents/entrymoment.py when that one is cached
- ``GET /api/analysis/entry``       ⑥ the moment of entry (agents/entrymoment.py dash_view, '준비 중' when missing)
- ``GET /api/analysis/synergy``     조합 시너지 (agents/synergy.py dash_view)
- ``GET /api/analysis/levrule``     좋은 자리 vs 보통: leverage rule B's pre-registered evaluation (agents/leveval.py,
                                    docs/levrule-eval.md; '30일 판정 전 결론 없음' until day 30)
- ``GET /api/analysis/shadows``     그림자 비교: every nightly shadow vs base for the new run, grouped, with the 5-year
                                    reference lines, and the leverage equity curves (``?account=`` one account's)
- ``GET /api/analysis/questions``   ⑦ the 45-question checklist (paperbot/dash/questions45.json, see below)
- ``GET /api/analysis/alerts``      알림 기록: what is stored somewhere readable (see ``alert_history``)
- ``GET /api/debate``               the 24-hour debate room (paperbot/agents/debate.py, own service; see ``debate``)

The 45-question checklist reads ``paperbot/dash/questions45.json``:
``{"source": "<doc it was taken from>", "updated": "YYYY-MM-DD", "questions": [{"n": 1, "q": "질문", "status":
"done|partial|todo|na", "where": "어디서 답하는지", "note": "한 줄"}]}``. An empty list shows '준비 중'.

The 24-hour debate room reads, read-only, ``debate/debate.db`` next to paper3.db (``create_app(debate_db=...)``
overrides): tables debate_messages, debate_rounds, debate_hypotheses, debate_ideas, debate_state; the debate service
(paperbot-debate, its own user and its own paid API key) is that file's only writer. No file or no table: ``ready:
false`` and the page shows '꺼짐'.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from concurrent.futures import Future, TimeoutError as FutureTimeout
from typing import Any, Callable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_FILE = os.path.join(HERE, "questions45.json")
FAILALERT_DIR = "/var/lib/paperbot/failalert"     # paperbot/failalert.py STATE_DIR (one file per unit: the KST day)
WAIT_S = 8.0                 # a request waits this long for a heavy computation, then answers 'pending'
ERROR_TTL_S = 60             # an error is retried after this long
HEALTH_TTL_S = 20
ALERTS_TTL_S = 30
RISK_TTL_S = 900
READINESS_TTL_S = 600
SHOCK_TTL_S = 300
MAP_TTL_S = 900
ENTRY_TTL_S = 900
SYNERGY_TTL_S = 900
LEVRULE_TTL_S = 600
SHADOWS_TTL_S = 3 * 3600        # per daily3 report (a new nightly report is a new key)
HEAVY_KEEP = 256                # cached results kept (expired ones are dropped beyond this)
MAP_CARDS = 2000             # cards.cards_from_db's own cap: the latest this many closed trades per kind
READINESS_ROWS = 40
DEBATE_ROWS = 50
QUESTIONS_MAX = 200
DAY_MS = 86_400_000
NO_DATA = "아직 자료가 없습니다"


def ro_connect(path: Optional[str]) -> Optional[sqlite3.Connection]:
    """A read-only connection, None when the file is not there (never creates one)."""
    if not path or not os.path.exists(path):
        return None
    try:
        c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    c.row_factory = sqlite3.Row
    return c


def _close(*cs: Optional[sqlite3.Connection]) -> None:
    for c in cs:
        if c is not None:
            try:
                c.close()
            except sqlite3.Error:
                pass


def _r(x: Any, n: int = 4) -> Any:
    return round(x, n) if isinstance(x, float) else x


def _now() -> int:
    return int(time.time() * 1000)


def _age_ko(s: float) -> str:
    """'40초' / '12분' / '5시간' / '3일'."""
    s = max(0.0, float(s))
    return (f"{int(s)}초" if s < 90 else f"{int(s // 60)}분" if s < 5400 else f"{int(s // 3600)}시간" if s < 172800
            else f"{int(s // 86400)}일")


# ---------------------------------------------------------------- one heavy computation at a time
class Heavy:
    """Results of expensive read-only analyses, shared by every viewer. One computation runs at a time (a small
    server); the same key is never computed twice at once; a request waits at most ``wait_s``."""

    def __init__(self, wait_s: float = WAIT_S):
        self.wait_s = wait_s
        self.cache: dict = {}            # key -> (computed at (s), value, ttl)
        self.running: dict = {}          # key -> Future
        self.lock = threading.Lock()
        self.gate = threading.Lock()     # one computation at a time

    def peek(self, key: str) -> Optional[dict]:
        with self.lock:
            hit = self.cache.get(key)
        return None if hit is None else hit[1]

    def _run(self, key: str, fn: Callable[[], dict], fut: Future, ttl: float) -> None:
        with self.gate:
            try:
                val = fn()
                if not isinstance(val, dict):
                    val = {"value": val}
            except Exception as exc:  # noqa: BLE001  (a view never takes the page down)
                val = {"error": f"계산하지 못함: {type(exc).__name__}"}
        with self.lock:
            if len(self.cache) >= HEAVY_KEEP:
                now = time.time()
                for k in [k for k, h in self.cache.items() if now - h[0] >= h[2]]:
                    del self.cache[k]
            self.cache[key] = (time.time(), val, ERROR_TTL_S if "error" in val else ttl)
            self.running.pop(key, None)
        fut.set_result(val)

    def get(self, key: str, ttl: float, fn: Callable[[], dict], wait_s: Optional[float] = None) -> dict:
        wait = self.wait_s if wait_s is None else wait_s
        with self.lock:
            hit = self.cache.get(key)
            if hit is not None and time.time() - hit[0] < hit[2]:
                return {**hit[1], "computed_at": int(hit[0] * 1000)}
            fut = self.running.get(key)
            if fut is None:
                fut = Future()
                self.running[key] = fut
                threading.Thread(target=self._run, args=(key, fn, fut, ttl), daemon=True,
                                 name=f"dash-{key}").start()
            if hit is not None and "error" not in hit[1]:
                # an expired result: answered now, the new one is computed in the background (no viewer waits)
                return {**hit[1], "computed_at": int(hit[0] * 1000), "stale": True}
        try:
            fut.result(timeout=wait)
        except FutureTimeout:
            if hit is not None and "error" not in hit[1]:
                return {**hit[1], "computed_at": int(hit[0] * 1000), "stale": True}
            return {"pending": True, "note": "계산 중입니다. 잠시 뒤 자동으로 다시 불러옵니다"}
        with self.lock:
            got = self.cache.get(key)
        return {**got[1], "computed_at": int(got[0] * 1000)} if got else {"pending": True}


class Cached:
    """A small time cache for the cheap views (computed in the request)."""

    def __init__(self):
        self.store: dict = {}

    def get(self, key: str, ttl: float, fn: Callable[[], dict]) -> dict:
        hit = self.store.get(key)
        if hit is None or time.time() - hit[0] > ttl:
            self.store[key] = hit = (time.time(), fn())
        return {**hit[1], "computed_at": int(hit[0] * 1000)}


# ---------------------------------------------------------------- ① health
def _state(c: sqlite3.Connection, k: str) -> Optional[tuple]:
    try:
        r = c.execute("SELECT ts, data FROM state WHERE k = ?", (k,)).fetchone()
        return None if r is None else (int(r[0]), json.loads(r[1]))
    except (sqlite3.Error, TypeError, ValueError):
        return None


def _nightly(daily_db: Optional[str]) -> dict:
    """The newest nightly check (daily3.db reports): parity in plain numbers, the early_kline label, missing bars."""
    d = ro_connect(daily_db)
    if d is None:
        return {"ready": False, "why": "daily3.db 없음"}
    try:
        r = d.execute("SELECT day, ts, data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
        if r is None:
            return {"ready": False, "why": "아직 밤 점검 기록이 없음"}
        rep = json.loads(r["data"]) or {}
        labels: dict = {}
        mism = 0
        for (data,) in d.execute("SELECT data FROM mismatches WHERE day = ?", (r["day"],)):
            mism += 1
            try:
                lab = (json.loads(data or "{}") or {}).get("label")
            except (TypeError, ValueError, AttributeError):
                lab = None
            labels[lab or "설명 없음"] = labels.get(lab or "설명 없음", 0) + 1
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return {"ready": False, "why": f"daily3.db를 읽지 못함: {type(exc).__name__}"}
    finally:
        _close(d)
    par = rep.get("parity")
    out: dict = {"ready": True, "day": r["day"], "ts": int(r["ts"]), "mismatch_rows": mism, "mismatch_labels": labels}
    if isinstance(par, dict):
        out["parity"] = {k: par.get(k) for k in ("accounts", "mismatched_accounts", "early_kline", "crash_gaps",
                                                 "extra_accounts") if par.get(k) is not None}
    else:
        out["parity"] = {"note": str(par or "")[:200]}
    dq = rep.get("data_quality") or {}
    out["missing_bars"] = sum(int(q.get("missing") or 0) for q in dq.values() if isinstance(q, dict))
    return out


def _checkpoint_job(checkpoint_db: Optional[str]) -> Optional[dict]:
    c = ro_connect(checkpoint_db)
    if c is None:
        return None
    try:
        r = c.execute("SELECT ts, date, text FROM job_log ORDER BY rowid DESC LIMIT 1").fetchone()
        return None if r is None else {"ts": int(r["ts"]), "date": r["date"], "text": str(r["text"] or "")[:300]}
    except sqlite3.Error:
        return None
    finally:
        _close(c)


def failalert_records(path: str = FAILALERT_DIR) -> list[dict]:
    """The scheduled jobs that failed (paperbot/failalert.py keeps the KST day of its last warning per unit)."""
    out = []
    try:
        names = sorted(os.listdir(path))[:50]
    except OSError:
        return out
    try:
        from ..failalert import JOBS_KO
    except Exception:  # noqa: BLE001
        JOBS_KO = {}
    for n in names:
        p = os.path.join(path, n)
        try:
            with open(p, encoding="utf-8") as fh:
                day = fh.read(40).strip()
            mtime = int(os.path.getmtime(p) * 1000)
        except OSError:
            continue
        out.append({"unit": n, "job_ko": (JOBS_KO.get(n) or (n,))[0], "day": day, "ts": mtime})
    return out


def health(data, rooms, daily_db: Optional[str], checkpoint_db: Optional[str], liq_db: Optional[str],
           now_ms: Optional[int] = None, failalert_dir: str = FAILALERT_DIR) -> dict:
    """① One card: is everything alive and agreeing? Every part on its own (one missing part never hides the rest).
    ``problems`` / ``warnings``: plain Korean lines; ``level``: ok / warn / bad."""
    now = _now() if now_ms is None else int(now_ms)
    out: dict = {"now": now}
    problems: list = []
    warnings: list = []
    # bot and 1m data (paper3.db, written by the live runner)
    c = ro_connect(data.db)
    if c is None:
        out["bot"] = {"ready": False}
        problems.append("paper3.db를 열지 못했습니다 (봇이 아직 시작 전이거나 경로가 다름)")
    else:
        try:
            hb, run = _state(c, "heartbeat"), _state(c, "run")
            sig = [dict(r) for r in c.execute(
                "SELECT status, COUNT(*) AS n, AVG(delay_ms) AS d FROM signal_log WHERE bar_close > ? "
                "AND strategy NOT GLOB 'NL[0-9]*' GROUP BY status", (now - DAY_MS,))]
            al = {r[0]: int(r[1]) for r in c.execute(
                "SELECT level, COUNT(*) FROM alerts WHERE ts > ? GROUP BY level", (now - DAY_MS,))}
            crit = critical_split(c, now - DAY_MS)
        except sqlite3.Error as exc:
            hb, run, sig, al, crit = None, None, [], {}, critical_split(None, 0)
            problems.append(f"paper3.db를 읽지 못했습니다 ({type(exc).__name__})")
        finally:
            _close(c)
        age = (now - hb[0]) / 1000 if hb else None
        last = (hb[1] or {}).get("last_step") if hb and isinstance(hb[1], dict) else None
        data_age = (now - int(last)) / 1000 if isinstance(last, (int, float)) and last else None
        n_sig = sum(int(r["n"]) for r in sig)
        delays = [r["d"] for r in sig if r["d"] is not None]
        out["bot"] = {"ready": True, "heartbeat_ts": hb[0] if hb else None, "heartbeat_age_s": _r(age, 1),
                      "alive": age is not None and age < 90, "last_bar_ts": last, "data_age_s": _r(data_age, 1),
                      "data_fresh": data_age is not None and data_age < 300,
                      "accounts": (run[1] or {}).get("accounts") if run else None,
                      "signals_24h": n_sig, "signals_late_24h": sum(int(r["n"]) for r in sig if r["status"] == "LATE"),
                      "avg_delay_s": _r(sum(delays) / len(delays) / 1000, 2) if delays else None,
                      "alerts_24h": al, "liquidations_24h": crit["liquidations"], "busts_24h": crit["busts"],
                      "critical_other_24h": crit["other"]}
        if age is None:
            problems.append("봇 생존 신호가 없습니다")
        elif age >= 90:
            problems.append(f"봇 생존 신호가 {_age_ko(age)} 전에 멈췄습니다")
        if data_age is not None and data_age >= 300:
            problems.append(f"1분봉이 {_age_ko(data_age)}째 들어오지 않습니다")
        # every liquidation is CRITICAL (engine.py): only one of the 36 or the reel makes the card red; DeepSeek, the
        # coin flips and the extra accounts are a count line (G14). Any other CRITICAL alert is a problem. A bust is
        # logged as WARN (engine.py): counted here whatever its level, the same way (36 / reel red, others a line).
        liq, bust = crit["liquidations"], crit["busts"]

        def per_group(d: dict, groups) -> str:
            return " · ".join(f"{_group_ko(g)} {d[g]}건" for g in GROUP_LINE_ORDER if g in groups and d.get(g))
        if crit["other"]:
            problems.append(f"지난 24시간 긴급 경고 {crit['other']}건 (강제청산 빼고)")
        for what, d in (("강제청산", liq), ("파산", bust)):
            loud = sum(n for g, n in d.items() if g in LOUD_LIQ_GROUPS)
            if loud:
                problems.append(f"지난 24시간 {what} {loud}건 ({per_group(d, LOUD_LIQ_GROUPS)})")
            quiet = [g for g, n in d.items() if g not in LOUD_LIQ_GROUPS and n]
            if quiet:
                warnings.append(f"지난 24시간 {what} {per_group(d, quiet)}")
        if al.get("WARN"):
            warnings.append(f"지난 24시간 주의 경고 {al['WARN']}건")
    # liquidation recorder (its own liq.db)
    lq = ro_connect(liq_db)
    if lq is not None:
        try:
            r = lq.execute("SELECT MAX(received_ts) FROM liq").fetchone()
            t = int(r[0]) if r and r[0] else None
            out["liq_recorder"] = {"last_ts": t, "age_s": None if t is None else round((now - t) / 1000)}
        except sqlite3.Error:
            out["liq_recorder"] = {"last_ts": None}
        finally:
            _close(lq)
    # agents (agents3.db, read-only through the rooms helper)
    if rooms.agents_db:
        with rooms.ro(rooms.agents_db) as a:
            tick = rooms._cursor_obj(a, rooms.R.TICK_CURSOR)
            ai = rooms._ai_failing(a)
        t_age = (now - int(tick["ts"])) / 1000 if isinstance(tick, dict) and tick.get("ts") else None
        out["agents"] = {"configured": True, "last_tick": tick, "tick_age_s": _r(t_age, 0), "ai": ai}
        if t_age is None:
            warnings.append("에이전트 점검 기록이 아직 없습니다")
        elif t_age > 45 * 60:
            problems.append(f"에이전트 점검이 {_age_ko(t_age)}째 없습니다")
        elif isinstance(tick, dict) and tick.get("ok") is False:
            problems.append("에이전트 마지막 점검이 실패했습니다" + (f": {str(tick.get('why'))[:80]}" if tick.get("why") else ""))
        if isinstance(ai, dict) and ai.get("failed"):
            problems.append(f"AI 호출이 연속 {ai['failed']}번 답을 받지 못했습니다")
        try:
            u = rooms.usage(now)
            out["usage"] = {k: u.get(k) for k in ("day", "calls", "tokens", "cap_calls", "cap_tokens", "week")}
            if u.get("cap_calls") and u.get("calls", 0) >= u["cap_calls"]:
                warnings.append("오늘 AI 사용 한도에 닿았습니다")
        except Exception:  # noqa: BLE001
            out["usage"] = None
    else:
        out["agents"] = {"configured": False}
    # nightly check (daily3.db) with the early_kline label
    n = _nightly(daily_db)
    out["nightly"] = n
    if n.get("ready"):
        par = n.get("parity") or {}
        if par.get("mismatched_accounts"):
            problems.append(f"밤 점검 재계산 불일치 {par['mismatched_accounts']}개 계좌 ({n['day']})")
        elif par.get("early_kline"):
            warnings.append(f"밤 점검 차이 {par['early_kline']}개 계좌: 모두 '1분봉을 확정 전에 읽음'(early_kline)으로 확인됨")
        if "accounts" not in par:
            warnings.append(f"밤 점검이 재계산을 하지 못했습니다 ({n['day']})")
        if n.get("missing_bars"):
            warnings.append(f"밤 점검: 빠진 1분봉 {n['missing_bars']}개 ({n['day']})")
        if now - n["ts"] > 2 * DAY_MS:
            warnings.append("밤 점검 기록이 이틀 넘게 없습니다")
    # checkpoint (checkpoint.db)
    try:
        from ..checkpoint import dashboard_view
        cv = dashboard_view(checkpoint_db) if checkpoint_db and os.path.exists(checkpoint_db) else {"ready": False}
    except Exception:  # noqa: BLE001
        cv = {"ready": False}
    try:
        summ = data.summary(now)
    except Exception:  # noqa: BLE001
        summ = {}
    out["checkpoint"] = {"ready": bool(cv.get("ready")), "date": cv.get("date"), "day": cv.get("day"),
                         "counts": cv.get("counts"), "next": summ.get("next_checkpoint"),
                         "run_day": summ.get("day"), "last_job": _checkpoint_job(checkpoint_db)}
    # scheduled jobs that failed (failalert.py's own records, when this server keeps them)
    fa = failalert_records(failalert_dir)
    out["job_failures"] = fa
    for f in fa:
        if now - f["ts"] < DAY_MS:
            warnings.append(f"예약 작업 실패 경고: {f['job_ko']} ({f['day']})")
    out["problems"], out["warnings"] = problems[:20], warnings[:20]
    out["level"] = "bad" if problems else "warn" if warnings else "ok"
    return out


LIQ_LINE = re.compile(r"^\[([^\]\s]+)\] LIQUIDATED\b")
BUST_LINE = re.compile(r"^\[([^\]\s]+)\] BUST\b")
LOUD_LIQ_GROUPS = ("core", "reel")          # their liquidations and busts make the health card red (G14)
GROUP_LINE_ORDER = ("core", "reel", "extra", "ds200", "flip", "other")


def _group_ko(g: str) -> str:
    from ..groups import GROUP_KO
    return GROUP_KO.get(g, "기타")


def critical_split(c: Optional[sqlite3.Connection], since_ms: int) -> dict:
    """The alerts since ``since_ms``: the CRITICAL ones split into liquidations per group (the '[account] LIQUIDATED'
    lines of engine.py, the account's group by its kind: accounts.GROUP_OF_KIND) and every other CRITICAL ("other"),
    plus the busts per group ('[account] BUST: ...', whatever their level: engine.py logs them as WARN)."""
    out: dict = {"liquidations": {}, "busts": {}, "other": 0}
    if c is None:
        return out
    from ..accounts import GROUP_OF_KIND
    kinds = {r[0]: r[1] for r in c.execute("SELECT account_id, kind FROM accounts")}
    for level, text in c.execute("SELECT level, text FROM alerts WHERE ts > ? AND (level = 'CRITICAL' OR text LIKE "
                                 "'[%] BUST%')", (since_ms,)):
        text = str(text or "")
        m = LIQ_LINE.match(text) if level == "CRITICAL" else None
        b = None if m else BUST_LINE.match(text)
        if m is None and b is None:
            if level == "CRITICAL":
                out["other"] += 1
            continue
        key = "liquidations" if m else "busts"
        g = GROUP_OF_KIND.get(kinds.get((m or b).group(1)), "other")
        out[key][g] = out[key].get(g, 0) + 1
    return out


# ---------------------------------------------------------------- 알림 기록
ALERT_LEVELS = ("INFO", "WARN", "CRITICAL")


def alert_history(data, rooms, daily_db: Optional[str], checkpoint_db: Optional[str], limit: int = 200,
                  failalert_dir: str = FAILALERT_DIR, level: Optional[str] = None, exclude_info: bool = False) -> dict:
    """Every alert that is stored somewhere the dashboard can read. The Telegram messages themselves are not kept
    anywhere; what is kept: the live runner's alerts (paper3.db ``alerts``, every level), the nightly check's daily
    lines and mismatches (daily3.db), the checkpoint job's log (checkpoint.db ``job_log``), the agents tick's last
    state (agents3.db), the scheduled-job failure warnings (failalert's day files) and the fired price alerts."""
    out: dict = {"sources": [], "not_stored": ["텔레그램으로 보낸 글 원문(밤 점검 요약, 회의 요약, 거래 알림)은 따로 저장되지 않음"]}
    c = ro_connect(data.db)
    rows: list = []
    if c is not None:
        try:
            # level=WARN / CRITICAL (or "WARN,CRITICAL"): only those levels; exclude_info: every level but INFO
            # (G15: the operations alerts no longer scroll away under two INFO lines per trade)
            lv = [x for x in (level or "").upper().split(",") if x in ALERT_LEVELS]
            where, args = [], []
            if lv:
                where.append("level IN (%s)" % ",".join("?" * len(lv)))
                args += lv
            if exclude_info:
                where.append("level != 'INFO'")
            q = "SELECT ts, level, text FROM alerts" + (" WHERE " + " AND ".join(where) if where else "")
            rows = [{"ts": int(r["ts"]), "level": r["level"], "text": str(r["text"] or "")[:500], "source": "bot"}
                    for r in c.execute(q + " ORDER BY rowid DESC LIMIT ?", (*args, min(max(int(limit), 1), 500)))]
            out["sources"].append("paper3.db alerts")
        except sqlite3.Error:
            rows = []
        finally:
            _close(c)
    out["bot"] = rows
    nightly = []
    d = ro_connect(daily_db)
    if d is not None:
        try:
            for r in d.execute("SELECT day, ts, data FROM reports ORDER BY day DESC LIMIT 14"):
                try:
                    rep = json.loads(r["data"]) or {}
                except (TypeError, ValueError):
                    rep = {}
                par = rep.get("parity")
                dq = rep.get("data_quality") or {}
                nightly.append({"day": r["day"], "ts": int(r["ts"]),
                                "parity": ({k: par.get(k) for k in ("accounts", "mismatched_accounts", "early_kline",
                                                                     "crash_gaps") if par.get(k) is not None}
                                           if isinstance(par, dict) else {"note": str(par or "")[:200]}),
                                "missing_bars": sum(int(q.get("missing") or 0) for q in dq.values()
                                                    if isinstance(q, dict))})
            mm = []
            for r in d.execute("SELECT day, account_id, data FROM mismatches ORDER BY day DESC LIMIT 100"):
                try:
                    lab = (json.loads(r["data"] or "{}") or {}).get("label")
                except (TypeError, ValueError, AttributeError):
                    lab = None
                mm.append({"day": r["day"], "account_id": r["account_id"], "label": lab})
            out["mismatches"] = mm
            out["sources"].append("daily3.db reports, mismatches")
        except sqlite3.Error:
            pass
        finally:
            _close(d)
    out["nightly"] = nightly
    jobs = []
    cp = ro_connect(checkpoint_db)
    if cp is not None:
        try:
            jobs = [{"ts": int(r["ts"]), "date": r["date"], "text": str(r["text"] or "")[:300]}
                    for r in cp.execute("SELECT ts, date, text FROM job_log ORDER BY rowid DESC LIMIT 20")]
            out["sources"].append("checkpoint.db job_log")
        except sqlite3.Error:
            jobs = []
        finally:
            _close(cp)
    out["checkpoint_jobs"] = jobs
    if rooms.agents_db:
        with rooms.ro(rooms.agents_db) as a:
            out["agents_tick"] = rooms._cursor_obj(a, rooms.R.TICK_CURSOR)
            out["agents_ai"] = rooms._ai_failing(a)
    out["job_failures"] = failalert_records(failalert_dir)
    try:
        pa = rooms.price_alerts()
        out["price_alerts_fired"] = [{"id": a.get("id"), "symbol": a.get("symbol"), "direction": a.get("direction"),
                                      "price": a.get("price"), "fired_ts": a.get("fired_ts"), "note": a.get("note")}
                                     for a in pa.get("alerts") or [] if a.get("fired_ts")][:50]
    except Exception:  # noqa: BLE001
        out["price_alerts_fired"] = []
    return out


# ---------------------------------------------------------------- ② risk-reward and drawdown
def risk_view(paper_db: str, now_ms: int) -> dict:
    """The strategy accounts and the coin flips: payoff, breakeven win rate, gap, give-back, exit mix
    (agents/riskreward.py) and drawdown now / deepest, P(bust), P(-50%) (agents/survival.py; no sizing search)."""
    from ..agents import riskreward as RR
    from ..agents import survival as SV
    from ..agents.roster3 import STRATEGY_KO
    c = ro_connect(paper_db)
    if c is None:
        return {"error": "paper3.db 없음"}
    try:
        lad = RR.ladder()
        rt = RR.round_trip_of(c)
        rows = RR.closed(c, 0, now_ms, round_trip=rt)
        tab = RR.table(rows, lad["first_trigger"])
        # the 36's coin flips only (the v4 5m flips run the reel's exits: the reel's yardstick, not the 36's)
        flips = RR.stats([t for _s, tf, t in RR.closed(c, 0, now_ms, kinds=("random",), round_trip=rt) if tf != "5m"],
                         lad["first_trigger"])
        sv = SV.table(c, now_ms, sizing_on=False)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    finally:
        _close(c)

    def rr(s: dict) -> dict:
        if not s.get("trades"):
            return {"trades": 0, "small": True}
        out = RR.compact(s)
        g = s.get("giveback") or {}
        out["giveback"] = {k: g.get(k) for k in ("winners", "mean_best_roe", "mean_roe", "kept_share")}
        out["losers_reached_first_lock"] = (s.get("losers_reached_first_lock") or {}).get("n")
        out["exits"] = s.get("exits")
        return out

    strategies = []
    for s, e in tab["strategies"].items():
        g = SV.compact_group(sv["strategies"].get(s))
        strategies.append({"strategy": s, "name_ko": STRATEGY_KO.get(s, s), **{k: v for k, v in RR.compact(e["all"]).items()
                                                                              if k != "exit_share"},
                           "max_dd_pct": g.get("max_dd_pct"), "dd_now_pct": g.get("dd_now_pct"),
                           "p_bust_max": g.get("p_bust_max"), "busted": g.get("busted")})
    strategies.sort(key=lambda r: -(r.get("trades") or 0))
    sims = [r for r in sv["accounts"].values() if r.get("kind") == "strategy" and "p_bust" in (r.get("mc") or {})]
    too_few = sum(1 for r in sv["accounts"].values() if r.get("kind") == "strategy" and (r.get("mc") or {}).get("too_few"))
    return {"rules": {k: lad.get(k) for k in ("first_lock", "first_trigger", "stop_atr", "leverage")},
            "trades": tab["all"].get("trades", 0), "flip_trades": flips.get("trades", 0),
            "all": rr(tab["all"]), "coin_flips": rr(flips),
            "drawdown": {"timeframes": {tf: SV.compact_group(g) for tf, g in sv["timeframes"].items()},
                         "coin_flips": SV.compact_group(sv["coin_flips"]),
                         "simulated": len(sims), "too_few": too_few, "min_trades": SV.MIN_TRADES,
                         "paths": SV.PATHS, "horizon_days": SV.HORIZON_DAYS,
                         "p_bust_over_5pct": sum(1 for r in sims if r["mc"]["p_bust"] >= 0.05),
                         "p_dd50_over_10pct": sum(1 for r in sims if r["mc"]["p_dd50"] >= 0.10),
                         "busted": [a for a in sv["busted"] if sv["accounts"][a]["kind"] == "strategy"][:50]},
            "strategies": strategies[:60], "small_n": RR.SMALL_N, "label": SV.LABEL}


# ---------------------------------------------------------------- ③ readiness
def readiness_view(paper_db: str, checkpoint_db: Optional[str], now_ms: int, next_cp: Any = None) -> dict:
    from ..agents import readiness as RD
    c = ro_connect(paper_db)
    if c is None:
        return {"error": "paper3.db 없음", "label": RD.LABEL}
    try:
        cp = RD.checkpoint_view(checkpoint_db if checkpoint_db and os.path.exists(checkpoint_db) else None)
        if next_cp and isinstance(next_cp, dict) and next_cp.get("ts"):
            nd = time.strftime("%Y-%m-%d", time.gmtime(int(next_cp["ts"]) / 1000 + 9 * 3600))
            cp = {**cp, "next": nd}
        full = RD.evaluate(c, now_ms, cp)
    finally:
        _close(c)
    if full.get("error"):
        return full
    order = [cid for cid, *_x in RD.CONDITIONS]
    accounts = []
    for r in full["accounts"][:READINESS_ROWS]:
        accounts.append({"account": r["account"], "name_ko": r["name_ko"], "timeframe": r["timeframe"],
                         "trades": r["trades"], "pnl": r["pnl"], "marks": r["marks"], "met": r["met"], "of": r["of"],
                         "bust": r.get("bust", False),
                         "conditions": {cid: {"status": v.get("status"), "why": str(v.get("why") or "")[:120]}
                                        for cid, v in r["conditions"].items()}})
    return {"label": full["label"], "summary": full["summary"], "conditions": full["conditions"], "notes": full["notes"],
            "order": order, "legend": full["legend"], "accounts": accounts,
            "accounts_total": len(full["accounts"]),
            "strategies": [{"name_ko": e["name_ko"], "accounts": e["accounts"], "all_met": e["all_met"],
                            "best": e["best"]} for e in full["strategies"]][:40]}


# ---------------------------------------------------------------- ④ shock
def shock_view(paper_db: str) -> dict:
    from ..agents import shock as SH
    c = ro_connect(paper_db)
    if c is None:
        return {"error": "paper3.db 없음"}
    try:
        v = SH.dash_view(c)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    finally:
        _close(c)
    if isinstance(v.get("rows"), list):
        v["rows"] = v["rows"][:80]
    return v


# ---------------------------------------------------------------- ⑤ coin / regime / weekday map
def map_view(data) -> dict:
    """The latest ``MAP_CARDS`` closed strategy trades (and coin-flip trades) by coin, side, timeframe, session,
    weekday/weekend and market regime at entry (agents/compare.win_loss_compare)."""
    from ..agents.compare import win_loss_compare
    try:
        st = _cards(data, "strategy")
        flips = _cards(data, "random", tfs=CORE_FLIP_TFS)       # the 36's coin flips (the 5m ones are the reel's)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    keep =("trades", "all", "by_coin", "by_side", "by_timeframe", "by_session", "by_weekday", "by_regime", "note")
    a = win_loss_compare(st)
    f = win_loss_compare(flips)
    return {"strategy": {k: a.get(k) for k in keep if k in a}, "coin_flips": {k: f.get(k) for k in keep if k in f},
            "cap": MAP_CARDS, "small_n": 10}


CORE_FLIP_TFS = ("15m", "30m", "1h", "4h")   # the coin flips the 36 are compared with (G21: not the reel's 5m flips)


def _cards(data, kind: str, tfs: Optional[tuple] = None) -> list:
    """The latest ``MAP_CARDS`` closed trades of one account kind as cards (no stop what-ifs: not needed here); with
    ``tfs`` only those timeframes' accounts (the latest MAP_CARDS over them, newest first)."""
    from ..cards import cards_from_db
    c = data.conn()
    try:
        rt = data._round_trip(c)
        if tfs is None:
            return cards_from_db(c, rt, losses_only=False, limit=MAP_CARDS, kinds=(kind,))
        out = [x for tf in tfs for x in cards_from_db(c, rt, timeframe=tf, losses_only=False, limit=MAP_CARDS,
                                                       kinds=(kind,))]
        return sorted(out, key=lambda x: -int(x.get("exit_time") or 0))[:MAP_CARDS]
    finally:
        c.close()


# ---------------------------------------------------------------- ⑥ moment of entry
def entry_view(paper_db: str, daily_db: Optional[str], now_ms: int) -> dict:
    try:
        import importlib
        EM = importlib.import_module("..agents.entrymoment", __package__)
        from ..agents.roster3 import STRATEGY_KO
    except Exception as exc:  # noqa: BLE001  (the module may still be in the making)
        return {"unavailable": True, "note": f"준비 중 ({type(exc).__name__})"}
    if not hasattr(EM, "dash_view"):
        return {"unavailable": True, "note": "준비 중"}
    c = ro_connect(paper_db)
    if c is None:
        return {"error": "paper3.db 없음"}
    d = ro_connect(daily_db)
    side = os.path.dirname(os.path.abspath(paper_db))
    p = lambda n: os.path.join(side, n) if os.path.exists(os.path.join(side, n)) else None  # noqa: E731
    try:
        v = EM.dash_view(c, now_ms, 0, daily_ro=d, liq_path=p("liq.db"), flow_path=p("flow.db"),
                         market_path=p("market.db"), names_ko=dict(STRATEGY_KO))
    finally:
        _close(c, d)
    return v if isinstance(v, dict) else {"unavailable": True, "note": "준비 중"}


# ---------------------------------------------------------------- 조합 시너지
def synergy_view(paper_db: str, now_ms: int) -> dict:
    from ..agents import synergy as SY
    c = ro_connect(paper_db)
    if c is None:
        return {"error": "paper3.db 없음"}
    try:
        return SY.dash_view(c, now_ms)
    finally:
        _close(c)


# ---------------------------------------------------------------- 좋은 자리 vs 보통 (rule B, docs/levrule-eval.md)
def levrule_view(paper_db: str, now_ms: int) -> dict:
    """The pre-registered evaluation of leverage rule B (agents/leveval.dash_view): per group trades, win rate, mean
    ROE, mean P&L on equity, return per unit exposure, the leverage mix and why, the coin-flip baseline at the same
    mix, and the status ('30일 판정 전 결론 없음' until the day-30 checkpoint)."""
    from ..agents import leveval as LV
    c = ro_connect(paper_db)
    if c is None:
        return {"error": "paper3.db 없음", "doc": LV.DOC}
    try:
        return LV.dash_view(c, now_ms)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}", "doc": LV.DOC}
    finally:
        _close(c)


# ---------------------------------------------------------------- 그림자 비교 (every shadow vs base, new run)
SHADOW_GROUPS = (("lock", "청산 잠금", ("lock15", "lock20", "lock30")),
                 ("time", "시간 청산", ("timestop",)),
                 ("stop", "손절 폭", ("stopw1.5", "stopw2.5", "stopw3")),
                 ("tp", "고정 익절", ("tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R")),
                 ("lev", "레버리지 고정(티어 비중)", ("lev10", "lev20", "lev30", "lev40", "lev50")),
                 ("levm", "레버리지 = 비중", ("lev20m20", "lev30m30", "lev40m40", "lev50m50")))
SHADOW_KEYS = ("trades", "mean_eq", "base_mean_eq", "vs_base_eq", "better_share", "worse_share", "liq", "base_liq",
               "not_entered", "open", "tp", "small")
EXITSTYLE_JSON = os.path.join(os.path.dirname(os.path.dirname(HERE)), "research", "exitstyle", "out", "exitstyle.json")
CURVE_ACCOUNT_DAYS = 400
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_]+@[0-9a-z]+$")         # a strategy account id ("N17_KC_RSI@15m")


def _pct(x: Optional[float], d: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def five_year_refs(exitstyle_path: str = EXITSTYLE_JSON) -> dict:
    """One 5-year reference line per shadow group, from the committed results (research/levstop/out/levstop.json,
    research/exitstyle/out/exitstyle.json); a group without a 5-year comparison says so."""
    from ..agents import levstop as LS
    from ..agents.riskreward import TP_FIVE_YEAR
    out = {"lock": "5년 비교 없음: 첫 잠금 15·20·30%는 5년 시험 lock_start로만 확인",
           "time": "5년 비교 없음"}
    doc = LS.load()
    arms = ((doc or {}).get("summary") or {}).get("by_arm") or {}
    fr = (doc or {}).get("margin_frac") or {}

    def arm(k):
        a = arms.get(k) or {}
        return a.get("pooled_mean_eq"), a.get("busts"), a.get("accounts")
    if arms:
        st = [(k, *arm(f"tiers|{k}")) for k in ("1.5", "2.0", "2.5", "3.0")]
        out["stop"] = ("5년(research/levstop, 지금 단계 50→20배): 거래당 자금 대비 " + " · ".join(
            f"손절 {k} ATR {_pct(m)}" for k, m, _b, _a in st) + " · 파산 " + "·".join(
            f"{b}" for _k, _m, b, _a in st) + f"/{st[0][3]} (2 ATR이 지금 규칙)")
        lv = [(k, *arm(f"{k}|2.0")) for k in ("10", "20", "30", "40", "50")]
        out["lev"] = ("5년(research/levstop, 손절 2 ATR, 증거금 " + "·".join(
            f"{int(round(float(fr.get(k, 0)) * 100))}" for k, *_x in lv) + "%): 거래당 자금 대비 " + " · ".join(
            f"{k}배 {_pct(m)}" for k, m, _b, _a in lv) + " · 파산 " + "·".join(f"{b}" for _k, _m, b, _a in lv)
            + f"/{lv[0][3]}")
        out["levm"] = ("5년에 같은 비교(증거금 = 레버리지 %)는 없음. 가장 가까운 것은 위 고정 배수(50배만 증거금 40%): "
                       + " · ".join(f"{k}배 {_pct(m)}" for k, m, _b, _a in lv[1:]))
    else:
        out["stop"] = out["lev"] = out["levm"] = "5년 결과 파일 없음 (research/levstop/out/levstop.json)"
    try:
        with open(exitstyle_path, encoding="utf-8") as fh:
            ex = json.load(fh)
        prim = ((ex.get("summary") or {}).get("primary") or {})
        names = (("ladder", "계단 잠금"), ("tp1R", "1R"), ("tp1.5R", "1.5R"), ("tp2R", "2R"), ("tp3R", "3R"),
                 ("ladder_tp2R", "잠금+2R"))
        rec = ((ex.get("summary") or {}).get("decision") or {}).get("recommend")
        out["tp"] = ("5년(research/exitstyle): 거래당 자금 대비 " + " · ".join(
            f"{ko} {_pct((prim.get(k) or {}).get('pooled_mean_eq'), 3)}" for k, ko in names if k in prim)
            + (" · 미리 정한 조건을 통과한 익절 없음 → 계단 잠금 유지" if rec == "ladder" else ""))
    except (OSError, ValueError, AttributeError):
        out["tp"] = TP_FIVE_YEAR
    return out


def report_key(daily_db: Optional[str]) -> str:
    """The newest daily3 report ('<day>@<ts>', '' when none or unreadable): what the shadows view is cached by."""
    d = ro_connect(daily_db)
    if d is None:
        return ""
    try:
        r = d.execute("SELECT day, ts FROM reports ORDER BY ts DESC LIMIT 1").fetchone()
        return f"{r[0]}@{r[1]}" if r else ""
    except sqlite3.Error:
        return ""
    finally:
        _close(d)


def shadows_view(paper_db: str, daily_db: Optional[str], now_ms: int, account: Optional[str] = None) -> dict:
    """Every nightly shadow variant against the base for the new run (since the run start, strategy accounts;
    agents/riskreward.shadow_summary), grouped, with each group's 5-year reference line, and the leverage variants'
    equity curves (obsshadows.curve_view: median strategy-account equity per day, busts so far; one account's
    curves when ``account`` is a strategy account)."""
    from ..agents import riskreward as RR
    from ..obsshadows import curve_view
    c = ro_connect(paper_db)
    d = ro_connect(daily_db)
    try:
        start = 0
        accounts: list = []
        if c is not None:
            try:
                from ..checkpoint import run_facts
                start = run_facts(c).get("start_ts") or 0
                accounts = [r[0] for r in c.execute("SELECT account_id FROM accounts WHERE kind = 'strategy' "
                                                    "ORDER BY rowid")]
            except sqlite3.Error:
                start, accounts = 0, []
        sh = RR.shadow_summary(d, c, int(start), int(now_ms)) if d is not None else {"error": "daily3.db 없음"}
        cv = curve_view(d, account=account if account in set(accounts) else None,
                        accounts=accounts if c is not None else None) if d is not None else {}
    finally:
        _close(c, d)
    allc = (sh.get("all") or {}) if isinstance(sh, dict) else {}
    ko = {**RR.SHADOW_KO, **RR.SHADOW_KO3, **RR.SHADOW_KO4, **RR.SHADOW_KO_M4}
    groups = []
    refs = five_year_refs()
    for key, title, variants in SHADOW_GROUPS:
        rows = []
        for v in variants:
            cell = allc.get(v) or {"trades": 0}
            rows.append({"variant": v, "ko": ko.get(v, v), **{k: cell.get(k) for k in SHADOW_KEYS if k in cell}})
        groups.append({"key": key, "title": title, "rows": rows, "five_year": refs.get(key)})
    curves: dict = {}
    if cv:
        curves = {"variants": cv.get("variants") or [], "days": (cv.get("days") or [])[-CURVE_ACCOUNT_DAYS:],
                  "start": cv.get("start"), "bust_below": cv.get("bust_below"),
                  "by_variant": {v: {"accounts": b.get("accounts"),
                                     "median": (b.get("median") or [])[-CURVE_ACCOUNT_DAYS:],
                                     "busts": (b.get("busts") or [])[-CURVE_ACCOUNT_DAYS:],
                                     "bust_accounts": (b.get("bust_accounts") or [])[:50]}
                                 for v, b in (cv.get("by_variant") or {}).items()}}
        if cv.get("error"):
            curves["error"] = cv["error"]
        if isinstance(cv.get("account"), dict):
            a = cv["account"]
            curves["account"] = {"account_id": a.get("account_id"),
                                 "curves": {v: (x or [])[-CURVE_ACCOUNT_DAYS:] for v, x in (a.get("curves") or {}).items()},
                                 "bust_day": a.get("bust_day"), "n_trades": a.get("n_trades")}
    return {"label": RR.SHADOW_LABEL, "since": int(start or 0), "base": allc.get("base") or {"trades": 0},
            "groups": groups, "curves": curves, "accounts": accounts[:400],
            "account": account if account in set(accounts) else None,
            **({"error": sh["error"]} if isinstance(sh, dict) and sh.get("error") else {}),
            "note": ("밤 점검이 새 실행(시작 뒤) 매매법 계좌의 끝난 거래를 규칙 하나만 바꿔 다시 돌린 기록. 차이 = 그 그림자 평균 − "
                     "같은 거래 base 평균(자금 대비), 나음·나쁨 = 같은 거래끼리 비교한 비율. 10건 미만은 작음. 설명용, 판정 아님: "
                     "30일 규칙은 바뀌지 않음")}


# ---------------------------------------------------------------- ⑦ the 45 questions
STATUSES = ("done", "partial", "todo", "na")


def questions(path: str = QUESTIONS_FILE) -> dict:
    """The checklist: every question with its status (done / partial / todo / na), bounded and cleaned."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {"ready": False, "questions": [], "note": "45개 질문 점검표 원본이 아직 없습니다 (준비 중)"}
    qs = []
    for i, q in enumerate((raw.get("questions") if isinstance(raw, dict) else None) or []):
        if not isinstance(q, dict) or len(qs) >= QUESTIONS_MAX:
            continue
        st = q.get("status") if q.get("status") in STATUSES else "todo"
        qs.append({"n": q.get("n") if isinstance(q.get("n"), int) else i + 1, "q": str(q.get("q") or "")[:300],
                   "status": st, "where": str(q.get("where") or "")[:200], "note": str(q.get("note") or "")[:300],
                   "group": str(q.get("group") or "")[:60]})
    counts = {s: sum(1 for q in qs if q["status"] == s) for s in STATUSES}
    return {"ready": bool(qs), "source": str(raw.get("source") or "")[:200] if isinstance(raw, dict) else "",
            "updated": str(raw.get("updated") or "")[:20] if isinstance(raw, dict) else "",
            "questions": qs, "counts": counts, "total": len(qs),
            **({} if qs else {"note": "45개 질문 점검표가 아직 비어 있습니다 (준비 중)"})}


# ---------------------------------------------------------------- 24-hour debate room (read-only)
def debate(debate_db: Optional[str], limit: int = DEBATE_ROWS) -> dict:
    """The 24-hour debate room (paperbot/agents/debate.py, a separate paid-API service; docs/debate-room.md): its latest
    rounds (newest first, each with its turns), spend against the monthly cap, status (돌고 있음 / 멈춤 + reason /
    키 없음 / 꺼짐), hypotheses with their grading, ideas and per-speaker hit rates, all from debate.db opened read-only.
    ``messages`` (oldest first) keeps the old shape. No file or no table: ``ready: false``, ``state: "off"``."""
    from ..agents import debate as DB
    out = {"ready": False, "messages": [], "title": "24시간 토론방", "note": "24시간 토론방 — 꺼짐: 아직 시작한 적이 없습니다",
           "source": os.path.basename(debate_db) if debate_db else None, "state": "off", "state_ko": DB.STATE_KO["off"],
           "reason": "서비스가 켜져 있지 않거나 아직 시작한 적이 없습니다", "rounds": [], "hypotheses": [], "ideas": [],
           "caution": DB.CAUTION_KO}
    c = ro_connect(debate_db)
    if c is None:
        return out
    try:
        rows = [{"id": int(r["id"]), "ts": int(r["ts"] or 0), "speaker": str(r["speaker"] or "")[:40],
                 "stance": str(r["stance"] or "")[:20], "topic": str(r["topic"] or "")[:120],
                 "text": str(r["text"] or "")[:1000]}
                for r in c.execute("SELECT id, ts, speaker, stance, topic, text FROM debate_messages "
                                   "ORDER BY id DESC LIMIT ?", (min(max(int(limit), 1), 200),))]
    except sqlite3.Error:
        return out
    finally:
        _close(c)
    out.update(ready=True, messages=rows[::-1], note="" if rows else "아직 토론 글이 없습니다")
    s = DB.summary(debate_db, rounds=15)
    if s.get("ready"):
        out.update({k: v for k, v in s.items() if k not in ("ready", "caution")})
    return out


# ---------------------------------------------------------------- routes
def register(app, data, rooms, db: str, daily_db: Optional[str], checkpoint_db: Optional[str],
             debate_db: Optional[str], heavy: Optional[Heavy] = None, failalert_dir: str = FAILALERT_DIR) -> Heavy:
    """Add the routes above to the dashboard app (create_app calls this)."""
    side = os.path.dirname(os.path.abspath(db))
    daily = daily_db or os.path.join(side, "daily3.db")
    liq = os.path.join(side, "liq.db")
    heavy = heavy or Heavy()
    small = Cached()

    @app.get("/api/time")
    def get_time():
        return {"now": _now()}

    @app.get("/api/analysis/health")
    def get_health():
        return small.get("health", HEALTH_TTL_S,
                         lambda: health(data, rooms, daily, checkpoint_db, liq, failalert_dir=failalert_dir))

    @app.get("/api/analysis/alerts")
    def get_alert_history(level: Optional[str] = None, exclude_info: int = 0, limit: int = 200):
        asked = set((level or "").upper().split(","))
        lv = ",".join(x for x in ALERT_LEVELS if x in asked)
        n = min(max(int(limit), 1), 500)
        return small.get(f"alerts:{lv}:{int(bool(exclude_info))}:{n}", ALERTS_TTL_S,
                         lambda: alert_history(data, rooms, daily, checkpoint_db, limit=n, failalert_dir=failalert_dir,
                                               level=lv or None, exclude_info=bool(exclude_info)))

    @app.get("/api/analysis/risk")
    def get_risk():
        return heavy.get("risk", RISK_TTL_S, lambda: risk_view(db, _now()))

    @app.get("/api/analysis/readiness")
    def get_readiness():
        def make():
            try:
                nxt = data.summary().get("next_checkpoint")
            except Exception:  # noqa: BLE001
                nxt = None
            return readiness_view(db, checkpoint_db, _now(), nxt)
        return heavy.get("readiness", READINESS_TTL_S, make)

    @app.get("/api/analysis/shock")
    def get_shock():
        return heavy.get("shock", SHOCK_TTL_S, lambda: shock_view(db))

    @app.get("/api/analysis/entry")
    def get_entry():
        return heavy.get("entry", ENTRY_TTL_S, lambda: entry_view(db, daily, _now()))

    @app.get("/api/analysis/map")
    def get_map():
        out = heavy.get("map", MAP_TTL_S, lambda: map_view(data))
        em = heavy.peek("entry")         # the entry view's volatility and weekday buckets, when already computed
        if isinstance(em, dict) and isinstance(em.get("all"), dict):
            out = {**out, "entry_buckets": {k: em["all"].get(k) for k in ("volatility", "weekday") if k in em["all"]},
                   "entry_trades": em.get("trades")}
        return out

    @app.get("/api/analysis/synergy")
    def get_synergy():
        return heavy.get("synergy", SYNERGY_TTL_S, lambda: synergy_view(db, _now()))

    @app.get("/api/analysis/levrule")
    def get_levrule():
        return heavy.get("levrule", LEVRULE_TTL_S, lambda: levrule_view(db, _now()))

    @app.get("/api/analysis/shadows")
    def get_shadows(account: Optional[str] = None):
        acct = account if account and len(account) <= 80 and ACCOUNT_RE.match(account) else None
        return heavy.get(f"shadows:{acct or ''}:{report_key(daily)}", SHADOWS_TTL_S,
                         lambda: shadows_view(db, daily, _now(), acct))

    @app.get("/api/analysis/questions")
    def get_questions():
        return small.get("questions", 60, questions)

    @app.get("/api/debate")
    def get_debate():
        return small.get("debate", 10, lambda: debate(debate_db))

    return heavy
