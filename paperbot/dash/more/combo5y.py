"""5년 조합 시험 + 5년 월별 (combo-5y). Read-only: the committed 5-year combination results (paperbot/dash/data/
combo5y.json, made offline by paperbot/dash/tools/combo5y.py; nothing is computed from the cache here) and, for the
monthly view, the paper run so far of the 36 (closed trades in paper3.db, read-only).

    GET /api/v4/combo5y           조합 시너지 › 5년 시험 / #/combo5y: portfolios, walk-forward, correlation, merged
                                  rules, one shared account, methods (the per-day month table is left out)
    GET /api/v4/combo5y/monthly   분석 › 5년 월별: per strategy (기존 36) the 5-year monthly returns (each month a fresh
                                  $5,000 account per timeframe, as the paper run) and where the paper run so far sits
                                  among the 5-year months after the same number of days

The JSON is read once and again only when its file changes (mtime); a missing or unreadable file answers
{"unavailable": true, "note"} (the page says 준비 중). The paper side is one indexed read of the 36's closed trades
since the run start (kind 'strategy', 15m-4h), cached ``TTL_S``. Only the 36 and their coin flips are in either answer:
DeepSeek is not part of the 5-year combination test (no DeepSeek number of any kind here).

Comparing "so far": the 5-year months start on the 1st with $5,000 per account, the paper run started on its own day.
Each 5-year month's realized P&L by the end of day ``d`` (d = the paper run's elapsed days, rounded up, 1..31) is the
yardstick for the paper run's realized P&L since its start (closed trades only, both sides; open positions are not
counted on either side). Under ``SMALL_N`` closed trades the page marks it 표본 적음. Not a verdict (설명용, 판정 아님).
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import sqlite3
import threading
import time
from typing import Optional

DATA_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "combo5y.json")
TTL_S = 60.0
DAY_MS = 86_400_000
SMALL_N = 20
CORE_TFS = ("15m", "30m", "1h", "4h")
LABEL = "설명용, 판정 아님"
UNAVAILABLE = {"unavailable": True,
               "note": "5년 조합 시험 결과 파일이 아직 없습니다 (paperbot/dash/data/combo5y.json). 만드는 법: docs/combo5y.md"}


def load(path: str) -> Optional[dict]:
    """The committed JSON, or None when missing / unreadable / another version."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("version") == 1 and doc.get("per") else None


def combo_view(doc: Optional[dict]) -> dict:
    """The combination screen's answer: everything except the per-strategy month tables (the 5년 월별 tab has them)."""
    if doc is None:
        return dict(UNAVAILABLE)
    per = {}
    for s, p in (doc.get("per") or {}).items():
        per[s] = {k: p.get(k) for k in ("n", "best", "worst", "median", "mean", "pos_share", "trades", "win_rate",
                                         "one")}
    keep = ("version", "generated", "label", "months", "strategies", "names", "tfs", "initial", "flips", "parity",
            "portfolio", "merged", "shared", "methods")
    out = {k: doc.get(k) for k in keep}
    out["per"] = per
    if isinstance(out.get("flips"), dict):
        out["flips"] = {k: v for k, v in out["flips"].items() if k != "tfs"}
    return out


def rank_among(x: float, vals: list) -> dict:
    """Where x stands among the 5-year months: rank 1 = above all; ``below`` = months under x."""
    v = [float(a) for a in vals if a is not None and math.isfinite(float(a))]
    above = sum(1 for a in v if a > x)
    below = sum(1 for a in v if a < x)
    return {"rank": above + 1, "of": len(v) + 1, "below": below, "n": len(v),
            "share_below": round(below / len(v), 4) if v else None}


def paper_so_far(c: sqlite3.Connection, now_ms: int) -> dict:
    """{"start", "strategies": {s: {"pnl", "trades", "wins", "accounts", "initial"}}} of the 36 since the run start."""
    from ...agents.triggers import run_start
    start = run_start(c)
    out: dict = {"start": start, "strategies": {}}
    q = ",".join("?" * len(CORE_TFS))
    accts = c.execute(f"SELECT account_id, strategy, timeframe FROM accounts WHERE kind = 'strategy' "
                      f"AND timeframe IN ({q})", CORE_TFS).fetchall()
    if not accts:
        return out
    try:
        from ...agents.digest import initial_equity
        init = float(initial_equity(c))
    except Exception:  # noqa: BLE001  (an old database: the run's own start)
        init = 5000.0
    by: dict = {}
    for aid, s, _tf in accts:
        d = by.setdefault(s, {"pnl": 0.0, "trades": 0, "wins": 0, "accounts": 0, "initial": 0.0})
        d["accounts"] += 1
        d["initial"] += init
        if start is None:
            continue
        r = c.execute("SELECT COUNT(*), COALESCE(SUM(pnl), 0), COALESCE(SUM(pnl > 0), 0) FROM trades "
                      "WHERE account_id = ? AND exit_time >= ? AND exit_time <= ?", (aid, int(start), int(now_ms))).fetchone()
        d["trades"] += int(r[0] or 0)
        d["pnl"] += float(r[1] or 0.0)
        d["wins"] += int(r[2] or 0)
    out["strategies"] = by
    return out


def monthly_view(doc: Optional[dict], paper: Optional[dict], now_ms: int) -> dict:
    """The 5년 월별 answer: per strategy its 5-year months (full months and per timeframe) and the paper run so far
    against the 5-year months after the same number of days (paper None: the 5-year side only)."""
    if doc is None:
        return dict(UNAVAILABLE)
    start = (paper or {}).get("start")
    elapsed = (now_ms - int(start)) / DAY_MS if start else None
    day = None if elapsed is None else max(1, min(31, int(math.ceil(max(elapsed, 1e-9)))))
    rows = []
    papers = (paper or {}).get("strategies") or {}
    for s in doc.get("strategies") or []:
        p = (doc.get("per") or {}).get(s) or {}
        row = {"strategy": s, "name": (doc.get("names") or {}).get(s, s), "m": p.get("m") or []}
        for k in ("n", "best", "worst", "median", "mean", "pos_share", "p10", "p25", "p75", "p90", "trades", "win_rate",
                  "liq", "bust_months", "one"):
            row[k] = p.get(k)
        row["tfs"] = {tf: {k: v for k, v in (t or {}).items()} for tf, t in (p.get("tfs") or {}).items()}
        pp = papers.get(s)
        if pp is not None and day is not None:
            el = [r[day - 1] / 10_000.0 for r in (p.get("elapsed_bp") or []) if len(r) >= day]
            ret = pp["pnl"] / pp["initial"] if pp["initial"] else None
            row["paper"] = {"pnl": round(pp["pnl"], 2), "ret": None if ret is None else round(ret, 6),
                            "trades": pp["trades"], "wins": pp["wins"], "accounts": pp["accounts"],
                            "capital": pp["initial"], "small": pp["trades"] < SMALL_N,
                            "same_day": [round(x, 4) for x in el],
                            "same_day_median": round(sorted(el)[len(el) // 2], 4) if el else None,
                            "rank": rank_among(ret, el) if (ret is not None and el) else None}
        rows.append(row)
    meth = doc.get("methods") or {}
    return {"ready": True, "label": LABEL, "generated": doc.get("generated"), "months": doc.get("months") or [],
            "tfs": doc.get("tfs") or list(CORE_TFS), "initial": doc.get("initial"), "rows": rows,
            "flips": {k: v for k, v in (doc.get("flips") or {}).items() if k in ("unit_months", "tfs", "units")},
            "now": now_ms, "run_start": start, "elapsed_days": None if elapsed is None else round(elapsed, 3),
            "day": day, "small_n": SMALL_N,
            "methods": {k: meth.get(k) for k in ("accounts", "sizing", "costs", "caveat", "period")},
            "note": ("5년 달은 매달 1일에 계좌마다 $5,000로 새로 시작. 지금 실험은 시작한 날부터 같은 날 수(올림)만큼 지난 5년 달들의 "
                     "닫힌 거래 손익과 비교 (열린 포지션은 양쪽 다 빼고)")}


def tf_month(doc: Optional[dict], strategy: str, tf: str) -> Optional[dict]:
    """One strategy x timeframe's 5-year monthly summary (for vs5y's rows), or None."""
    if doc is None:
        return None
    t = (((doc.get("per") or {}).get(strategy) or {}).get("tfs") or {}).get(tf)
    if not t:
        return None
    return {k: t.get(k) for k in ("n", "best", "worst", "median", "pos_share", "bust_months")}


_SHARED: dict = {"path": DATA_JSON, "hit": None}
_SHARED_LOCK = threading.Lock()


def doc_cached(path: Optional[str] = None) -> Optional[dict]:
    """The JSON, read again only when its mtime changes (shared by both routes and vs5y)."""
    path = path or _SHARED["path"]
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _SHARED["hit"]
    if hit and hit[0] == path and hit[1] == mt:
        return hit[2]
    with _SHARED_LOCK:
        hit = _SHARED["hit"]
        if hit and hit[0] == path and hit[1] == mt:
            return hit[2]
        doc = load(path)
        _SHARED["hit"] = (path, mt, doc)
        return doc


def register(app, ctx) -> dict:
    from fastapi import HTTPException
    data = ctx.data
    path = getattr(ctx, "combo5y_json", None) or DATA_JSON
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/combo5y")
    def get_combo5y():
        """The committed 5-year combination results (portfolios, walk-forward, correlation, merged rules, shared
        account, methods); {"unavailable": true} until the file exists."""
        from ..app import json_finite
        doc = doc_cached(path)
        key = ("combo", id(doc))
        hit = cache.get("combo")
        if hit and hit[0] == key:
            return hit[1]
        v = json_finite(combo_view(doc))
        cache["combo"] = (key, v)
        return v

    @app.get("/api/v4/combo5y/monthly")
    def get_combo5y_monthly():
        """5년 월별: the 36's 5-year monthly returns and where the paper run so far sits (cached 60 s)."""
        from ..app import json_finite
        doc = doc_cached(path)
        if doc is None:
            return dict(UNAVAILABLE)
        hit = cache.get("monthly")
        if hit and hit[0] == id(doc) and time.time() - hit[1] < TTL_S:
            return hit[2]
        with lock:
            hit = cache.get("monthly")
            if hit and hit[0] == id(doc) and time.time() - hit[1] < TTL_S:
                return hit[2]
            now = int(time.time() * 1000)
            try:
                with contextlib.closing(data.conn()) as c:
                    paper = paper_so_far(c, now)
            except sqlite3.Error as exc:
                raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
            v = json_finite(monthly_view(doc, paper, now))
            cache["monthly"] = (id(doc), time.time(), v)
        return v

    return {"routes": ["/api/v4/combo5y", "/api/v4/combo5y/monthly"], "cache": cache}
