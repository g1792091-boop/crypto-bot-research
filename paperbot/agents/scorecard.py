"""Graded hypotheses: did the staff's predictions come true on trades made after they wrote them?

A hypothesis may carry a ``prediction`` in a fixed form (``clean_prediction``):

    {"metric": "mean_roe" | "win_rate" | "lock_share" | "loss_tag_share",
     "tag": "<a loss-card tag>"       (loss_tag_share only),
     "timeframe": "15m" .. "4h" | null (all four accounts of the strategy; 5m removed 2026-10-04),
     "direction": "above" | "below", "value": number, "after_trades": 30 .. 300}

Code grades it once, on the first ``after_trades`` trades of that strategy (and timeframe) that were
ENTERED after the hypothesis was written: the metric over those trades is above / below ``value`` or
not. A prediction that does not get its trades within ``EXPIRE_DAYS`` is marked expired. The grade is
an append-only trial_results row (status 'graded' or 'expired'); a hypothesis without a prediction is
counted as 'not gradable'. ``scorecard`` sums it per role, so a staff member whose predictions keep
missing is visible to the others, the owners and the next meetings.

Metrics (over those trades): mean_roe = mean net ROE per trade; win_rate = share with pnl > 0;
lock_share = share that ended at a profit lock; loss_tag_share = share of the LOSING trades that carry
the tag (paperbot/cards.py), None when there is no losing trade.
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Optional

from ..config import V3_TRADE_TFS
from . import rooms_db as R

METRICS = {"mean_roe": ("거래당 평균 ROE", -1.0, 5.0), "win_rate": ("승률", 0.0, 1.0),
           "lock_share": ("익절 잠금으로 끝난 비율", 0.0, 1.0),
           "loss_tag_share": ("손실 중 그 특징이 있는 비율", 0.0, 1.0)}
TFS = V3_TRADE_TFS                   # the run's timeframes (5m removed 2026-10-04, docs/paper-v3-rules-change-1.md)
MIN_TRADES, MAX_TRADES = 30, 300
EXPIRE_DAYS = 120
DAY_MS = 86_400_000


def _tags() -> tuple:
    from ..cards import TAGS
    return tuple(name for name, _ in TAGS)


def clean_prediction(p: Any) -> tuple[Optional[dict], Optional[str]]:
    """(prediction, None) or (None, why it is not gradable)."""
    if p is None:
        return None, None
    if not isinstance(p, dict):
        return None, "prediction 형식이 아님"
    m = p.get("metric")
    if m not in METRICS:
        return None, f"metric은 {', '.join(METRICS)} 중 하나"
    out: dict = {"metric": m}
    if m == "loss_tag_share":
        if p.get("tag") not in _tags():
            return None, "tag는 손실 카드 특징 이름 중 하나"
        out["tag"] = p["tag"]
    tf = p.get("timeframe")
    if tf not in (None, *TFS):
        return None, f"timeframe은 {'·'.join(TFS)} 또는 null"
    out["timeframe"] = tf
    if p.get("direction") not in ("above", "below"):
        return None, "direction은 above 또는 below"
    out["direction"] = p["direction"]
    v = p.get("value")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return None, "value는 숫자"
    lo, hi = METRICS[m][1], METRICS[m][2]
    if not lo <= float(v) <= hi:
        return None, f"value는 {lo}~{hi} (비율은 0~1)"
    out["value"] = float(v)
    n = p.get("after_trades")
    if isinstance(n, bool) or not isinstance(n, int) or not MIN_TRADES <= n <= MAX_TRADES:
        return None, f"after_trades는 {MIN_TRADES}~{MAX_TRADES} 사이 정수"
    out["after_trades"] = n
    return out, None


def describe_ko(p: dict) -> str:
    what = METRICS[p["metric"]][0] + (f"('{p['tag']}')" if p.get("tag") else "")
    tf = p.get("timeframe") or f"{len(TFS)}개 봉 합계"
    return (f"앞으로 {tf} 거래 {p['after_trades']}건의 {what}이(가) {p['value']:g} "
            f"{'보다 높음' if p['direction'] == 'above' else '보다 낮음'}")


def _trades(paper_ro: sqlite3.Connection, strategy: str, tf: Optional[str], since_ms: int) -> list[tuple]:
    tfs = [tf] if tf else list(TFS)
    marks = ",".join("?" * len(tfs))
    return paper_ro.execute(
        f"SELECT account_id, data FROM trades WHERE account_id IN ({marks}) AND entry_time >= ? "
        "ORDER BY exit_time, id", (*[f"{strategy}@{t}" for t in tfs], since_ms)).fetchall()


def metric_value(rows: list[tuple], p: dict, round_trip: float) -> Optional[float]:
    ts = [json.loads(d) for _, d in rows]
    if p["metric"] == "mean_roe":
        return sum(float(t["roe"]) for t in ts) / len(ts)
    if p["metric"] == "win_rate":
        return sum(float(t["pnl"]) > 0 for t in ts) / len(ts)
    if p["metric"] == "lock_share":
        return sum(t.get("exit_reason") == "LOCK" for t in ts) / len(ts)
    from ..cards import card
    losses = [card(aid, json.loads(d), round_trip) for aid, d in rows if float(json.loads(d)["pnl"]) < 0]
    if not losses:
        return None
    return sum(p["tag"] in c["tags"] for c in losses) / len(losses)


def _loads(text: Any) -> Any:
    try:
        return json.loads(text) if text else None
    except (TypeError, ValueError):
        return None


def hypotheses(conn: Optional[sqlite3.Connection], strategy: Optional[str] = None,
               waiting_only: bool = False) -> list[dict]:
    """Every hypothesis in the ledger, oldest first (no page cap: the ledger keeps growing, and an old prediction
    must still be graded or expired): id, ts, strategy, spec and ``result`` (its latest result body, None while
    it waits). ``waiting_only``: only those with no result yet."""
    if conn is None:
        return []
    sql = ("SELECT t.id, t.ts, t.strategy, t.spec, r.id, r.result FROM trials t LEFT JOIN trial_results r ON r.id = "
           "(SELECT MAX(id) FROM trial_results WHERE trial_id = t.id) WHERE t.kind = 'hypothesis'")
    args: list = []
    if strategy is not None:
        sql += " AND t.strategy = ?"
        args.append(strategy)
    if waiting_only:
        sql += " AND r.id IS NULL"
    try:
        rows = conn.execute(sql + " ORDER BY t.id", args).fetchall()
    except sqlite3.Error:
        return []
    return [{"id": tid, "ts": ts, "strategy": s, "spec": _loads(spec),
             "result": None if rid is None else (_loads(res) or {})} for tid, ts, s, spec, rid, res in rows]


def grade_due(conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection], now_ms: int,
              round_trip: float) -> list[dict]:
    """Grade every ungraded hypothesis whose trades are in (or that has expired). Returns the grades."""
    done = []
    for t in hypotheses(conn, waiting_only=True):
        if not t.get("strategy"):
            continue
        p = (t.get("spec") or {}).get("prediction")
        if not isinstance(p, dict):
            continue
        rows = [] if paper_ro is None else _trades(paper_ro, t["strategy"], p.get("timeframe"), int(t["ts"]))
        if len(rows) >= p["after_trades"]:
            use = rows[:p["after_trades"]]
            v = metric_value(use, p, round_trip)
            if v is None:
                res = {"status": "graded", "correct": False, "value": None, "n": len(use),
                       "why": "손실 거래가 없어 비율을 계산할 수 없음(틀림으로 셈)"}
            else:
                ok = v > p["value"] if p["direction"] == "above" else v < p["value"]
                res = {"status": "graded", "correct": bool(ok), "value": v, "n": len(use)}
        elif now_ms - int(t["ts"]) > EXPIRE_DAYS * DAY_MS:
            res = {"status": "expired", "n": len(rows)}
        else:
            continue
        res.update(prediction=p, by=(t.get("spec") or {}).get("by") or "")
        R.add_trial_result(conn, t["id"], res["status"], res, ts=now_ms)
        done.append({"trial_id": t["id"], **res})
    return done


def scorecard(conn: Optional[sqlite3.Connection], strategy: Optional[str] = None) -> dict:
    """Per role (who proposed the hypothesis): graded, correct, hit rate, waiting, expired, not gradable. Every
    hypothesis counts (``hypotheses``), not only the newest page."""
    by: dict = {}
    for t in hypotheses(conn, strategy):
        spec = t.get("spec") if isinstance(t.get("spec"), dict) else {}
        k = by.setdefault(spec.get("by") or "", {"graded": 0, "correct": 0, "waiting": 0, "expired": 0,
                                                 "not_gradable": 0})
        res = t.get("result") or {}
        if not isinstance(spec.get("prediction"), dict):
            k["not_gradable"] += 1
        elif t.get("result") is None:
            k["waiting"] += 1
        elif res.get("status") == "expired":
            k["expired"] += 1
        else:
            k["graded"] += 1
            k["correct"] += bool(res.get("correct"))
    out = []
    for role, k in sorted(by.items()):
        out.append({"role": role, "name": R.role_name(role) if role else "", **k,
                    "hit_rate": k["correct"] / k["graded"] if k["graded"] else None})
    tot = {f: sum(r[f] for r in out) for f in ("graded", "correct", "waiting", "expired", "not_gradable")}
    tot["hit_rate"] = tot["correct"] / tot["graded"] if tot["graded"] else None
    return {"roles": out, "total": tot,
            "note": "예측이 붙은 가설만 채점: 가설을 쓴 뒤 들어간 거래로, 정해 둔 건수가 차면 코드가 한 번 판정"}
