"""Real-trading readiness check (실거래 조건 점검, owners approved 2026-10-04): the addendum's Q6 conditions (and the
Q3 conditions on when real trading may be reviewed), evaluated from the data for every strategy account and
strategy. Code only and read-only: paper3.db (opened read-only by the caller) and the 30-day verdict through
``paperbot.checkpoint``'s read functions (``dashboard_view`` of checkpoint.db).

This is a DISPLAY. Nothing here enables, starts, sizes or changes anything; no other code reads its result to
decide anything. docs/live-safety.md 5-9: "코드는 이 조건을 대신 판정하지 않습니다" - the owners confirm the
conditions themselves before any real trading.

Each condition quotes its document line (``CONDITIONS``: the text is looked up in the file, so the line number
is the current one) and comes out as ✅ (met), ❌ (not met) or '아직 판단 불가' (the data cannot say yet), with
its numbers:

- ``day30``         Q3: real trading is reviewed from day 30 of the run.
- ``trades200``     Q6-1: the account's paper trades >= 200.
- ``q1_fdr``        Q6-2: the Q1 luck test after FDR, i.e. the checkpoint's 1차 합격 or 2차 통과 (4h: observation
                    only, never judged: ❌; no verdict yet or 보류: 아직 판단 불가).
- ``second_check``  Q3: the 2nd check on the next 30 days (2차 통과; 1차 합격 waits for it: 아직 판단 불가).
- ``regimes2``      Q6-3: P&L > 0 in >= 2 different market regimes (the trade's regime at entry, cards.REGIME_KO;
                    a regime counts with >= ``MIN_REGIME_TRADES`` trades; under ``MIN_TRADES`` trades in all:
                    아직 판단 불가).
- ``neighbour_tf``  Q6-3: the neighbouring timeframe (15m-30m-1h-4h; 5m removed 2026-10-04) goes the same way: the account's P&L > 0
                    and a neighbour with >= ``MIN_TRADES`` trades also > 0.
- ``cost_ratio``    Q6-4: real cost / assumed cost <= 1.5, measured in a minimal real-money run. No such run yet,
                    and the executor's database is not readable by the agents: always 아직 판단 불가. The paper
                    order-book record (fill_costs, ``reference``) is shown as a hint only.
- ``testnet``       Q3: the testnet drill done before real trading (docs/live-safety.md 3-1). The executor's
                    records are not readable here: always 아직 판단 불가 (the owners confirm it).

``summary.met_all`` counts the accounts with every condition ✅ ('실거래 조건: 충족 N개'); ``data_met_all`` the
accounts with every condition the data can show ✅ (all but cost_ratio and testnet).
"""

from __future__ import annotations

import json
import os
import sqlite3
from functools import lru_cache
from typing import Any, Optional

from ..config import V3_TRADE_TFS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDENDUM = "docs/paper-v3-rules-addendum.md"
LIVE_SAFETY = "docs/live-safety.md"
DAY_MS = 86_400_000
TFS = V3_TRADE_TFS                   # the run's timeframes (5m removed 2026-10-04, docs/paper-v3-rules-change-1.md)
OK, NO, UNKNOWN = "✅", "❌", "아직 판단 불가"
MARK = {OK: "✅", NO: "❌", UNKNOWN: "?"}
MIN_TRADES = 30              # fewer closed trades: regimes and neighbours cannot say yet
MIN_REGIME_TRADES = 10       # a regime counts as 'plus' only with at least this many trades
NEED_DAYS = 30
NEED_TRADES = 200
NEED_COST_RATIO = 1.5
LABEL = "표시만: 아무것도 켜거나 바꾸지 않음"

# (id, short Korean label, document, the quoted text as it stands in the document)
CONDITIONS = (
    ("day30", "시작 후 30일", ADDENDUM, "실거래 검토는 시작 후 30일부터"),
    ("trades200", "거래 200건", ADDENDUM, "후보 계좌의 paper 거래가 **200건 이상**입니다."),
    ("q1_fdr", "우연 기준(FDR) 통과", ADDENDUM, "Q1 기준(보정 후)을 통과합니다."),
    ("second_check", "2차 통과", ADDENDUM, "2차는 그다음 30일입니다."),
    ("regimes2", "국면 2개 이상 플러스", ADDENDUM, "서로 다른 시장 국면 **2개 이상**에서 플러스입니다."),
    ("neighbour_tf", "옆 봉도 같은 방향", ADDENDUM, "옆 봉(예: 15분 → 30분)에서도 방향이 같습니다."),
    ("cost_ratio", "실제 비용 ÷ 가정 비용 ≤ 1.5", ADDENDUM, "실제 비용 ÷ 가정 비용이 **1.5 이하**여야 합니다."),
    ("testnet", "테스트넷 연습", ADDENDUM, "테스트넷 연습을 마친 경우에만"),
)
DATA_CONDITIONS = ("day30", "trades200", "q1_fdr", "second_check", "regimes2", "neighbour_tf")
NOTES = (
    (ADDENDUM, "그다음에 정한 금액으로, 매매법 1개부터 시작합니다."),
    (ADDENDUM, "**아무것도 합격하지 못하면 실거래는 하지 않습니다.**"),
    (LIVE_SAFETY, "코드는 이 조건을 대신 판정하지 않습니다"),
)


@lru_cache(maxsize=64)
def doc_line(rel: str, text: str) -> Optional[int]:
    """The first line of ``rel`` (repository path) that contains ``text``; None when it is not there."""
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if text in line:
                    return i
    except OSError:
        return None
    return None


def _plain(text: str) -> str:
    return text.replace("**", "")


def conditions() -> list[dict]:
    """Every condition with its quote and the document line it stands on."""
    return [{"id": cid, "label": label, "doc": doc, "line": doc_line(doc, quote), "quote": _plain(quote)}
            for cid, label, doc, quote in CONDITIONS]


def notes() -> list[dict]:
    return [{"doc": doc, "line": doc_line(doc, q), "quote": _plain(q)} for doc, q in NOTES]


def _f(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


# ---------------------------------------------------------------- reading paper3.db
def _accounts(paper_ro: sqlite3.Connection, kinds: tuple) -> list[tuple]:
    q = (f"SELECT account_id, strategy, timeframe FROM accounts WHERE kind IN ({','.join('?' * len(kinds))}) "
         "ORDER BY rowid")
    return [tuple(r) for r in paper_ro.execute(q, kinds)]


def _trade_cells(paper_ro: sqlite3.Connection, ids: set) -> dict:
    """{account: {regime: [n, pnl]}} of closed trades (regime: the chart context at entry; None = not recorded)."""
    out: dict = {}
    try:
        rows = paper_ro.execute("SELECT account_id, json_extract(data, '$.context.regime'), COUNT(*), SUM(pnl) "
                                "FROM trades GROUP BY 1, 2").fetchall()
    except sqlite3.OperationalError:          # no JSON1 in this SQLite build
        agg: dict = {}
        for aid, pnl, data in paper_ro.execute("SELECT account_id, pnl, data FROM trades"):
            try:
                ctx = (json.loads(data) or {}).get("context") or {}
            except (TypeError, ValueError, AttributeError):
                ctx = {}
            k = (aid, ctx.get("regime") if isinstance(ctx, dict) else None)
            e = agg.setdefault(k, [0, 0.0])
            e[0] += 1
            e[1] += _f(pnl)
        rows = [(a, r, n, p) for (a, r), (n, p) in agg.items()]
    for aid, reg, n, pnl in rows:
        if aid in ids:
            out.setdefault(aid, {})[reg] = [int(n), _f(pnl)]
    return out


def _book_costs(paper_ro: sqlite3.Connection, ids: set) -> dict:
    """{account: (orders, mean slip_best)} of the paper order-book record (fillcost.py; status 'ok')."""
    try:
        rows = paper_ro.execute("SELECT account_id, COUNT(*), AVG(slip_best) FROM fill_costs WHERE status = 'ok' "
                                "AND slip_best IS NOT NULL GROUP BY account_id").fetchall()
    except sqlite3.Error:
        return {}
    return {a: (int(n), _f(s)) for a, n, s in rows if a in ids}


def _engines(paper_ro: sqlite3.Connection) -> dict:
    try:
        r = paper_ro.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        return (json.loads(r[0]) or {}).get("engines", {}) if r else {}
    except (sqlite3.Error, TypeError, ValueError):
        return {}


def _costs() -> tuple[float, float]:
    from ..config import v3_settings
    s = v3_settings()
    return float(s.taker_fee), float(s.slippage_frac)


# ---------------------------------------------------------------- one account
def _c(status: str, **kw) -> dict:
    return {"status": status, **kw}


def _q1(row: Optional[dict], view: dict) -> tuple[dict, dict]:
    from ..checkpoint import FAIL, HOLD, OBSERVE, PASS1, PASS2
    if not view.get("ready"):
        why = "체크포인트 판정 전" + (f" (다음 {view['next']})" if view.get("next") else "")
        return _c(UNKNOWN, why=why), _c(UNKNOWN, why=why)
    if row is None:
        why = f"{view.get('date')} 판정에 이 계좌가 없음"
        return _c(UNKNOWN, why=why), _c(UNKNOWN, why=why)
    st = row.get("status")
    pq = {k: (round(row[k], 4) if isinstance(row.get(k), float) else row.get(k)) for k in ("p", "q")}
    base = {"verdict": st, "date": view.get("date"), **pq}
    if st in (PASS1, PASS2):
        q1 = _c(OK, **base)
    elif st == FAIL:
        q1 = _c(NO, **base, why=str(row.get("reason") or "")[:120])
    elif st == OBSERVE:
        q1 = _c(NO, **base, why="4시간봉은 관찰용: 판정하지 않음 (Q3)")
    else:                                    # 보류 (fewer than 30 trades) or a status code does not know
        q1 = _c(UNKNOWN, **base, why=str(row.get("reason") or "보류")[:120])
    if st == PASS2:
        sec = _c(OK, verdict=st, date=view.get("date"))
    elif st == PASS1:
        sec = _c(UNKNOWN, verdict=st, why="1차 합격: 2차 확인은 다음 체크포인트(그다음 30일)")
    elif st in (FAIL, OBSERVE):
        sec = _c(NO, verdict=st)
    else:
        sec = _c(UNKNOWN, verdict=st if st != HOLD else HOLD, why="1차 판정 전")
    return q1, sec


def _regimes(cells: dict) -> dict:
    from ..cards import REGIME_KO
    n_all = sum(n for n, _p in cells.values())
    shown = {}
    plus = []
    for reg, (n, pnl) in sorted(cells.items(), key=lambda kv: -kv[1][0]):
        name = REGIME_KO.get(reg) if reg not in (None, "unknown") else None
        if name is None:
            continue
        c = {"n": n, "pnl": round(pnl, 2)}
        if n < MIN_REGIME_TRADES:
            c["small"] = True
        elif pnl > 0:
            plus.append(name)
        shown[name] = c
    val = {"trades": n_all, "plus": plus, "by_regime": shown}
    if n_all < MIN_TRADES:
        return _c(UNKNOWN, **val, why=f"끝난 거래 {n_all}건 < {MIN_TRADES}건")
    return _c(OK if len(plus) >= 2 else NO, **val)


def _neighbours(tf: str, own: tuple, by_tf: dict) -> dict:
    n_own, pnl_own = own
    i = TFS.index(tf) if tf in TFS else -1
    nbs = [TFS[j] for j in (i - 1, i + 1) if 0 <= j < len(TFS)] if i >= 0 else []
    seen = {t: {"trades": by_tf.get(t, (0, 0.0))[0], "pnl": round(by_tf.get(t, (0, 0.0))[1], 2)} for t in nbs}
    val = {"pnl": round(pnl_own, 2), "neighbours": seen}
    usable = [t for t in nbs if seen[t]["trades"] >= MIN_TRADES]
    if n_own < MIN_TRADES:
        return _c(UNKNOWN, **val, why=f"이 계좌 거래 {n_own}건 < {MIN_TRADES}건")
    if not usable:
        return _c(UNKNOWN, **val, why=f"옆 봉 계좌 모두 거래 {MIN_TRADES}건 미만")
    if pnl_own <= 0:
        return _c(NO, **val, why="이 계좌가 플러스가 아님")
    return _c(OK if any(seen[t]["pnl"] > 0 for t in usable) else NO, **val)


def account_row(aid: str, strategy: str, tf: str, cells: dict, by_tf: dict, cp_row: Optional[dict], view: dict,
                days: float, book: Optional[tuple], taker: float, slip: float, name_ko: str = "",
                bust: bool = False) -> dict:
    n = sum(c[0] for c in cells.values())
    pnl = sum(c[1] for c in cells.values())
    cs: dict = {}
    cs["day30"] = _c(OK if days >= NEED_DAYS else NO, days=round(days, 1), need=NEED_DAYS)
    cs["trades200"] = _c(OK if n >= NEED_TRADES else NO, trades=n, need=NEED_TRADES)
    cs["q1_fdr"], cs["second_check"] = _q1(cp_row, view)
    cs["regimes2"] = _regimes(cells)
    cs["neighbour_tf"] = _neighbours(tf, (n, pnl), by_tf)
    ref = None
    if book and book[0]:
        ref = {"orders": book[0], "ratio": round((taker + book[1]) / (taker + slip), 3) if taker + slip > 0 else None}
    cs["cost_ratio"] = _c(UNKNOWN, need=NEED_COST_RATIO, why="최소 금액 실거래로 잰 실제 비용이 아직 없음(실행기 기록은 "
                          "에이전트가 읽지 않음)", reference=ref)
    cs["testnet"] = _c(UNKNOWN, why="테스트넷 연습 기록은 실행기 쪽에 있어 코드가 보지 않음: 두 분이 확인")
    marks = "".join(MARK[cs[c[0]]["status"]] for c in CONDITIONS)
    met = sum(1 for v in cs.values() if v["status"] == OK)
    data_met = sum(1 for k in DATA_CONDITIONS if cs[k]["status"] == OK)
    out = {"account": aid, "strategy": strategy, "name_ko": name_ko or strategy, "timeframe": tf, "trades": n,
           "pnl": round(pnl, 2), "conditions": cs, "marks": marks, "met": met, "of": len(CONDITIONS),
           "data_met": data_met, "all_met": met == len(CONDITIONS),
           "data_all_met": data_met == len(DATA_CONDITIONS)}
    if bust:
        out["bust"] = True
    return out


# ---------------------------------------------------------------- everything
def evaluate(paper_ro: Optional[sqlite3.Connection], now_ms: int, cp_view: Optional[dict] = None,
             names_ko: Optional[dict] = None, kinds: tuple = ("strategy",)) -> dict:
    """Every strategy account's conditions, the per-strategy view and the summary. ``cp_view``:
    ``paperbot.checkpoint.dashboard_view`` (+ ``next``), or None / {"ready": False} before the first verdict."""
    if paper_ro is None:
        return {"error": "paper3.db 없음", "label": LABEL}
    from .triggers import run_start
    if names_ko is None:
        from .roster3 import STRATEGY_KO
        names_ko = dict(STRATEGY_KO)
    view = cp_view or {"ready": False}
    try:
        accts = _accounts(paper_ro, kinds)
        ids = {a for a, _s, _t in accts}
        cells = _trade_cells(paper_ro, ids)
        book = _book_costs(paper_ro, ids)
        eng = _engines(paper_ro)
        start = run_start(paper_ro)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}", "label": LABEL}
    days = (now_ms - start) / DAY_MS if start else 0.0
    taker, slip = _costs()
    rows_cp = {r.get("account_id"): r for r in (view.get("rows") or [])} if view.get("ready") else {}
    tf_of: dict = {}
    for aid, s, tf in accts:
        c = cells.get(aid, {})
        tf_of.setdefault(s, {})[tf] = (sum(x[0] for x in c.values()), sum(x[1] for x in c.values()))
    rows = [account_row(aid, s, tf, cells.get(aid, {}), tf_of.get(s, {}), rows_cp.get(aid), view, days,
                        book.get(aid), taker, slip, names_ko.get(s, s), bool((eng.get(aid) or {}).get("bust")))
            for aid, s, tf in accts]
    by_cond = {cid: {OK: 0, NO: 0, UNKNOWN: 0} for cid, *_x in CONDITIONS}
    for r in rows:
        for cid, v in r["conditions"].items():
            by_cond[cid][v["status"]] += 1
    strategies = {}
    for r in rows:
        e = strategies.setdefault(r["strategy"], {"strategy": r["strategy"], "name_ko": r["name_ko"], "accounts": 0,
                                                  "all_met": 0, "data_all_met": 0, "best": None})
        e["accounts"] += 1
        e["all_met"] += r["all_met"]
        e["data_all_met"] += r["data_all_met"]
        if e["best"] is None or (r["met"], r["data_met"], r["trades"]) > (e["best"]["met"], e["best"]["data_met"],
                                                                         e["best"]["trades"]):
            e["best"] = {k: r[k] for k in ("account", "timeframe", "marks", "met", "data_met", "trades")}
    met_all = sum(r["all_met"] for r in rows)
    data_all = sum(r["data_all_met"] for r in rows)
    order = sorted(rows, key=lambda r: (-r["met"], -r["data_met"], -r["trades"], r["account"]))
    summary = {"accounts": len(rows), "met_all": met_all, "data_met_all": data_all,
               "headline": f"실거래 조건: 충족 {met_all}개",
               "days_running": round(days, 1), "checkpoint_ready": bool(view.get("ready")),
               "checkpoint_date": view.get("date"), "next_checkpoint": view.get("next"),
               "by_condition": by_cond}
    if met_all == 0:
        summary["q6_6"] = "아무것도 합격하지 못하면 실거래는 하지 않습니다 (Q6-6)"
    return {"label": LABEL, "now": int(now_ms), "conditions": conditions(), "notes": notes(), "summary": summary,
            "accounts": order, "strategies": sorted(strategies.values(), key=lambda e: (-e["best"]["met"],
                                                                                         -e["best"]["data_met"],
                                                                                         e["strategy"])),
            "legend": {"✅": "충족", "❌": "아님", "?": UNKNOWN, "order": [c[0] for c in CONDITIONS]}}


def _cond_counts(full: dict) -> dict:
    labels = {cid: label for cid, label, *_x in CONDITIONS}
    return {labels[cid]: {"✅": v[OK], "❌": v[NO], "?": v[UNKNOWN]}
            for cid, v in full["summary"]["by_condition"].items()}


def compact(full: dict, top: int = 5) -> dict:
    """The lead's daily view and the Friday risk packet: the headline, per condition how many accounts are
    ✅ / ❌ / ?, and the ``top`` accounts closest to all conditions (their marks in condition order)."""
    if full.get("error"):
        return {"error": full["error"], "label": LABEL}
    s = full["summary"]
    return {"headline": s["headline"], "data_met_all": s["data_met_all"], "accounts": s["accounts"],
            "days_running": s["days_running"], "checkpoint_ready": s["checkpoint_ready"],
            "by_condition": _cond_counts(full),
            "closest": [{"account": r["account"], "marks": r["marks"], "met": r["met"], "trades": r["trades"]}
                        for r in full["accounts"][:top]],
            "marks_order": [label for _c, label, *_x in CONDITIONS],
            "note": (f"{LABEL}. marks = 조건 순서대로 ✅ 충족 / ❌ 아님 / ? 아직 판단 불가. 실제 비용 비율과 테스트넷 연습은 "
                     "실거래 쪽 기록이라 코드가 판단하지 않음(두 분 확인). 판정은 체크포인트, 실거래는 두 분 결정")}


def meeting(full: dict, top: int = 8) -> dict:
    """The 30-day checkpoint meeting's view: the conditions with their quotes, the summary, every strategy's best
    account (marks), and the ``top`` closest accounts with their numbers."""
    if full.get("error"):
        return {"error": full["error"], "label": LABEL}
    acc = []
    for r in full["accounts"][:top]:
        cs = {}
        for cid, v in r["conditions"].items():
            cs[cid] = {k: v[k] for k in v if k not in ("by_regime", "neighbours")}
            if cid == "regimes2":
                cs[cid]["by_regime"] = v.get("by_regime")
            if cid == "neighbour_tf":
                cs[cid]["neighbours"] = v.get("neighbours")
        acc.append({k: r[k] for k in ("account", "name_ko", "trades", "pnl", "marks", "met")} | {"conditions": cs})
    return {"label": LABEL, "conditions": full["conditions"], "notes": full["notes"], "summary": full["summary"],
            "strategies": [{"name_ko": e["name_ko"], "best": e["best"]["account"], "marks": e["best"]["marks"],
                            "met": e["best"]["met"]} for e in full["strategies"]],
            "accounts": acc, "accounts_left_out": max(0, len(full["accounts"]) - top), "legend": full["legend"],
            "note": (f"{LABEL}. 코드가 자료로 계산한 조건 점검일 뿐 실거래 결정이 아님(docs/live-safety.md 5-9). "
                     "아직 판단 불가 = 자료가 아직 말하지 못함(거래 수 부족, 판정 전, 실거래 쪽 기록)")}


def line(full: Optional[dict]) -> str:
    """The Sunday report's one line."""
    if not isinstance(full, dict) or full.get("error") or "summary" not in full:
        return ""
    s = full["summary"]
    return (f"- {s['headline']} (계좌 {s['accounts']}개) · 자료로 볼 수 있는 조건을 모두 채운 계좌 {s['data_met_all']}개"
            " · 표시만, 아무것도 켜지 않음")


def checkpoint_view(checkpoint_db: Optional[str]) -> dict:
    """The newest verdict through the checkpoint's own read function (read-only), {"ready": False} without one."""
    if not checkpoint_db:
        return {"ready": False}
    from .. import checkpoint as CP
    try:
        return CP.dashboard_view(checkpoint_db)
    except Exception:  # noqa: BLE001  (a display never fails on a missing verdict)
        return {"ready": False}
