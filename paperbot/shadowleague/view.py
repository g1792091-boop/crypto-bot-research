"""Read-only views of the shadow league's database for the dashboard: plain dicts, no writes, no side effects.

    overview(path)                -> {"state": "ok", "members": [card, ...], ...}
    member(path, member_id)       -> {"state": "ok", "card", "curve", "table", "trades", "comparison", "study", ...}

Every view starts with a ``state``: exactly {"state": "not_started"} (no database file yet, or no member row in it: the
switch was never on), exactly {"state": "error", "reason": ...} (the file exists but cannot be read: a failed load never
reads as 'nothing'), or "ok". Every dict that carries numbers also carries ``label_ko`` = "참고용, 판정 아님". Times are UTC milliseconds; percentages
are percent (1.5 = 1.5 %), at 1x leverage and after the study's costs unless the key says gross.

The shapes are listed in docs/shadow-league.md ('대시보드용 읽기 도우미') and fixed by tests/test_shadowleague_view.py.
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Optional

import numpy as np

from . import LABEL_KO
from . import account as AC
from .league import MEMBERS, STALE_MS, AccountSpec
from .store import open_ro, schema_version
from .study import STUDIES

DAY_MS = 86_400_000
TFS = ("15m", "30m", "1h", "4h")
STATUS_KO = {"off": "꺼짐", "waiting": "시작 전", "warming": "워밍업 중", "recording": "기록 중", "error": "오류",
             "halted": "멈춤(정의가 바뀜)"}
SIDE_KO = {1: "롱", -1: "숏"}
REASON_KO = {"TP": "목표 도달", "SL": "손절", "TIME": "48봉 시간 청산", "EOD": "자료 끝"}
SIGNAL_KO = {"candidate": "후보", "pending_entry": "다음 봉 시가 진입 대기", "taken": "진입함", "busy": "보유 중이라 건너뜀",
             "skip_entry": "시가가 이미 손절·목표 밖이라 건너뜀", "skip_no_target": "목표 구간 없음",
             "skip_stop_far": "손절이 3 ATR보다 멂", "skip_rr": "손익비 2 미만", "not_chosen": "같은 봉의 다른 신호가 우선"}
LAST_TRADES = 50


NOT_STARTED = {"state": "not_started"}


def _err(reason: str) -> dict:
    return {"state": "error", "reason": reason}


def _open(path: str):
    """(connection, None) or (None, state dict). A missing file is 'not_started'; anything unreadable is 'error'."""
    try:
        return open_ro(path), None
    except FileNotFoundError:
        return None, dict(NOT_STARTED)
    except (sqlite3.Error, OSError) as exc:             # damaged, not a database, or not allowed to read it
        return None, _err(f"{type(exc).__name__}: {exc}")


def _f(x: Any, nd: int = 4) -> Optional[float]:
    if x is None:
        return None
    x = float(x)
    return None if not math.isfinite(x) else round(x, nd)


def _pct(x: Any, nd: int = 4) -> Optional[float]:
    return None if x is None else _f(100.0 * float(x), nd)


def _spec(row: dict) -> dict:
    """The member's definition as it was stored (its 5-year study key, coins, timeframes, account)."""
    try:
        return json.loads(row["spec_json"])
    except (ValueError, TypeError):
        return {}


def _known(m_id: str):
    return next((m for m in MEMBERS if m.member_id == m_id), None)


# ------------------------------------------------------------------------------------------------------------ cards
def _status(row: dict, series: list[dict], now_ms: int) -> tuple[str, dict]:
    count = {"recording": 0, "warming": 0, "waiting": 0, "error": 0}
    for s in series:
        count[s["status"]] = count.get(s["status"], 0) + 1
    count["total"] = len(series)
    if row.get("halted"):
        return "halted", count
    if row.get("activated_ms") is None or row.get("last_tick_ms") is None or now_ms - int(row["last_tick_ms"]) > STALE_MS:
        return "off", count
    if count["recording"]:
        return "recording", count
    if count["error"] and not count["warming"] and not count["waiting"]:
        return "error", count
    if count["warming"] or not series:
        return "warming", count
    return "waiting", count


def _stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["status"] == "closed"]
    nets = np.array([t["net"] for t in closed], float)
    gross = np.array([t["gross_raw"] for t in closed], float)
    return {"open": sum(1 for t in trades if t["status"] == "open"), "closed": len(closed),
            "wins": int((nets > 0).sum()) if len(nets) else 0,
            "win_pct": _f(100.0 * float((nets > 0).mean())) if len(nets) else None,
            "avg_net_pct": _pct(nets.mean()) if len(nets) else None,
            "avg_gross_pct": _pct(gross.mean()) if len(gross) else None,
            "sum_net_pct": _pct(nets.sum()) if len(nets) else None}


def _card(c: sqlite3.Connection, row: dict, now_ms: int) -> dict:
    mid = row["member_id"]
    series = [dict(r) for r in c.execute("SELECT * FROM series_state WHERE member_id = ? ORDER BY coin, tf", (mid,))]
    status, count = _status(row, series, now_ms)
    trades = [dict(r) for r in c.execute("SELECT status, net, gross_raw FROM trades WHERE member_id = ?", (mid,))]
    sig = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM signals WHERE member_id = ? GROUP BY status", (mid,))}
    act = row.get("activated_ms")
    late = c.execute("SELECT COUNT(*) FROM signals WHERE member_id = ? AND ? IS NOT NULL AND bar_ms < ?",
                     (mid, act, act)).fetchone()[0] if act is not None else 0
    skipped = sum(v for k, v in sig.items() if k.startswith("skip_") or k in ("busy", "not_chosen"))
    start = int(row["start_ms"])
    m = _known(mid)
    study = STUDIES.get(_spec(row).get("study", ""))
    warm = [{"coin": s["coin"], "tf": s["tf"], "have": s["warm_have"], "need": s["warm_need"], "note": s["note"]}
            for s in series if s["status"] == "warming"]
    errs = [{"coin": s["coin"], "tf": s["tf"], "note": s["note"]} for s in series if s["status"] == "error"]
    return {
        "member_id": mid, "name_ko": row["name_ko"], "blurb_ko": m.blurb_ko if m else "", "label_ko": LABEL_KO,
        "status": status, "status_ko": STATUS_KO[status], "halted_ko": row.get("halted"),
        "started_at_ms": start, "activated_ms": act, "last_tick_ms": row.get("last_tick_ms"),
        "days": _f(max(0.0, (now_ms - start) / DAY_MS), 2) if now_ms >= start else 0.0,
        "series": count, "warming": warm, "errors": errs,
        "signals": {"total": sum(sig.values()), "taken": sig.get("taken", 0), "skipped": skipped,
                    "pending": sig.get("pending_entry", 0) + sig.get("candidate", 0), "late": int(late)},
        "trades": _stats(trades),
        "study": ({"verdict": study["verdict"], "verdict_ko": study["verdict_ko"], "one_line_ko": study["one_line_ko"],
                   "run_date": study["run_date"], "prereg_sha256": study["prereg_sha256"]} if study else None),
    }


def overview(path: str, now_ms: Optional[int] = None) -> dict:
    """All members' cards. {"state": "not_started"} when the switch was never on, {"state": "error", ...} when unreadable."""
    import time
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    c, bad = _open(path)
    if bad:
        return bad
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM members ORDER BY member_id")]
        if not rows:
            return dict(NOT_STARTED)
        meta = c.execute("SELECT v FROM league_meta WHERE k = 'last_tick'").fetchone()
        return {"state": "ok", "label_ko": LABEL_KO, "as_of_ms": now, "schema_version": schema_version(c),
                "last_tick": json.loads(meta[0]) if meta else None, "members": [_card(c, r, now) for r in rows]}
    except Exception as exc:  # noqa: BLE001  (whatever goes wrong while reading is an error with its reason, never an empty view)
        return _err(f"{type(exc).__name__}: {exc}")
    finally:
        c.close()


# ------------------------------------------------------------------------------------------------------------ detail
def _trade_row(t: dict, act: Optional[int]) -> dict:
    return {"trade_id": t["trade_id"], "coin": t["coin"], "tf": t["tf"], "side": int(t["side"]),
            "side_ko": SIDE_KO[int(t["side"])], "status": t["status"], "signal_ms": t["signal_ms"],
            "entry_ms": t["entry_ms"], "entry_px": _f(t["entry_px"], 8), "stop_px": _f(t["stop_px"], 8),
            "target_px": _f(t["target_px"], 8), "exit_ms": t["exit_ms"], "exit_px": _f(t["exit_px"], 8),
            "reason": t["reason"], "reason_ko": REASON_KO.get(t["reason"]) if t["reason"] else None,
            "hold_bars": t["hold"], "gross_pct": _pct(t["gross_raw"]), "net_pct": _pct(t["net"]),
            "stop_dist_pct": _pct(t["sl_dist"]), "target_dist_pct": _pct(t["tp_dist"]),
            "account": {"taken": bool(t["acct_taken"]) if t["acct_taken"] is not None else None,
                        "ret_pct": _pct(t["acct_ret"]), "equity": _f(t["acct_equity"], 2),
                        "liquidated": bool(t["acct_liq"]) if t["acct_liq"] is not None else None},
            "recorded_ms": t["recorded_ms"],
            "late": bool(act is not None and int(t["signal_ms"]) < int(act)),
            "label_ko": LABEL_KO}


def _table(c: sqlite3.Connection, member_id: str, coins: tuple, tfs: tuple) -> list[dict]:
    series = {(r["coin"], r["tf"]): dict(r) for r in c.execute("SELECT * FROM series_state WHERE member_id = ?", (member_id,))}
    trades = [dict(r) for r in c.execute("SELECT coin, tf, status, net FROM trades WHERE member_id = ?", (member_id,))]
    sig: dict = {}
    for r in c.execute("SELECT coin, tf, status, COUNT(*) FROM signals WHERE member_id = ? GROUP BY coin, tf, status", (member_id,)):
        sig.setdefault((r[0], r[1]), {})[r[2]] = r[3]
    out = []
    for coin in coins:
        for tf in tfs:
            s = series.get((coin, tf))
            ts = [t for t in trades if t["coin"] == coin and t["tf"] == tf]
            closed = [t["net"] for t in ts if t["status"] == "closed"]
            sg = sig.get((coin, tf), {})
            st = _status_row(s)
            out.append({"coin": coin, "tf": tf, "status": st, "status_ko": STATUS_KO[st], "note": s["note"] if s else None,
                        "last_bar_ms": s["last_bar_ms"] if s else None,
                        "warm_have": s["warm_have"] if s else 0, "warm_need": s["warm_need"] if s else 0,
                        "signals": sum(sg.values()), "taken": sg.get("taken", 0),
                        "open": sum(1 for t in ts if t["status"] == "open"), "closed": len(closed),
                        "wins": sum(1 for x in closed if x > 0),
                        "avg_net_pct": _pct(np.mean(closed)) if closed else None,
                        "sum_net_pct": _pct(np.sum(closed)) if closed else None})
    return out


def _status_row(s: Optional[dict]) -> str:
    return s["status"] if s else "waiting"


def _worlds(clones: list[dict], k: int) -> dict:
    """{trade_id: {k: clone}} for the first k clones of each trade."""
    out: dict = {}
    for cl in clones:
        if cl["k"] < k:
            out.setdefault(cl["trade_id"], {})[cl["k"]] = cl
    return out


def _quantiles(mat: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return np.percentile(mat, 10, axis=0), np.percentile(mat, 50, axis=0), np.percentile(mat, 90, axis=0)


def curves(trades: list[dict], clones: list[dict], series: list[dict], start_ms: int, acct) -> dict:
    """The member against its coin-flip clones.
    per_trade: closed trades with every clone decided, in exit order, cumulative net % at 1x: the member's sum and the
      10 / 50 / 90 % band of the K clone worlds (world k = the k-th clone of every trade).
    account: the owners'-style account per scope ('15m', ..., 'all'), the member's daily equity and the clone worlds'
      band, only up to the time T* before which every trade and clone that entered has been decided."""
    by_trade: dict = {}
    for cl in clones:
        by_trade.setdefault(cl["trade_id"], []).append(cl)
    for v in by_trade.values():
        v.sort(key=lambda x: x["k"])
    kmax = min([len(v) for v in by_trade.values()] or [0])
    # per trade -------------------------------------------------------------------------------------------------
    comp = [t for t in trades if t["status"] == "closed" and t["trade_id"] in by_trade and kmax > 0
            and all(x["status"] == "closed" for x in by_trade[t["trade_id"]])]
    comp.sort(key=lambda t: (int(t["exit_ms"]), t["trade_id"]))
    comp_ids = {t["trade_id"] for t in comp}
    awaiting = sum(1 for t in trades if t["status"] == "closed" and t["trade_id"] not in comp_ids)
    pts = []
    if comp and kmax:
        member_net = np.array([t["net"] for t in comp], float) * 100.0
        flip = np.array([[by_trade[t["trade_id"]][i]["net"] for i in range(kmax)] for t in comp], float) * 100.0
        cum_m = np.cumsum(member_net)
        cum_f = np.cumsum(flip, axis=0)                      # (n, kmax)
        p10, p50, p90 = _quantiles(cum_f.T)
        for i, t in enumerate(comp):
            pts.append({"n": i + 1, "ms": int(t["exit_ms"]), "member_cum_pct": _f(cum_m[i]), "flip_p10": _f(p10[i]),
                        "flip_p50": _f(p50[i]), "flip_p90": _f(p90[i]), "member_avg_pct": _f(cum_m[i] / (i + 1)),
                        "flip_avg_p50": _f(p50[i] / (i + 1))})
    per_trade = {"unit_ko": "거래 1회당 %를 더한 누적(1배, 비용 뒤)", "n": len(comp), "clones_per_trade": kmax,
                 "awaiting_clones": awaiting, "points": pts, "label_ko": LABEL_KO,
                 "note_ko": "동전 던지기 = 같은 코인·봉·방향·손절·목표 거리로 ±5일 안 무작위 봉에 들어간 것. 가운데 선은 중앙값, 띠는 10~90%."}
    # account ---------------------------------------------------------------------------------------------------
    acc = {}
    scopes = list(TFS) + ["all"]
    for scope in scopes:
        tr = [t for t in trades if scope == "all" or t["tf"] == scope]
        if not tr:
            acc[scope] = {"points": [], "asof_ms": None, "label_ko": LABEL_KO}
            continue
        fr = AC.frontier_ms(series, None if scope == "all" else scope)
        if fr is None:
            acc[scope] = {"points": [], "asof_ms": None, "label_ko": LABEL_KO}
            continue
        tstar = int(fr)
        tstar = min([tstar] + [int(t["entry_ms"]) for t in tr if t["status"] != "closed"]
                    + [int(x["entry_ms"]) for t in tr for x in by_trade.get(t["trade_id"], [])
                       if x["status"] != "closed" and x["entry_ms"] is not None])
        real = [t for t in tr if int(t["entry_ms"]) < tstar]
        res = AC.run_account(real, acct.start_equity, acct.exposure, acct.margin_frac, acct.liq_adverse)
        mem = AC.daily_equity(real, res, start_ms, tstar, acct.start_equity)
        worlds = []
        for k in range(kmax):
            wt = []
            for t in real:
                cl = by_trade.get(t["trade_id"], [])
                if len(cl) <= k:
                    continue
                x = cl[k]
                if x["status"] == "closed" and x["entry_ms"] is not None and int(x["entry_ms"]) < tstar:
                    wt.append({"trade_id": x["clone_id"], "coin": x["coin"], "tf": x["tf"], "entry_ms": x["entry_ms"],
                               "exit_ms": x["exit_ms"], "net": x["net"], "mae": x["mae"]})
            r = AC.run_account(wt, acct.start_equity, acct.exposure, acct.margin_frac, acct.liq_adverse)
            worlds.append(AC.daily_equity(wt, r, start_ms, tstar, acct.start_equity))
        points = []
        for i, row in enumerate(mem):
            eqs = np.array([w[i]["equity"] for w in worlds if len(w) > i], float)
            band = (np.percentile(eqs, [10, 50, 90]) if len(eqs) else [None, None, None])
            points.append({"day_ms": row["day_ms"], "member_equity": _f(row["equity"], 2), "member_ret_pct": _f(row["ret_pct"]),
                           "flip_p10": _f(band[0], 2), "flip_p50": _f(band[1], 2), "flip_p90": _f(band[2], 2),
                           "taken": row["taken"], "liquidated": row["liquidated"]})
        acc[scope] = {"points": points, "asof_ms": tstar, "start_equity": acct.start_equity, "label_ko": LABEL_KO,
                      "worlds": len(worlds)}
    account = {"unit_ko": "두 분 방식 가상 계좌: 5,000 USDT, 증거금 20% × 20배, 한 번에 1개, 4.5% 역행 시 강제 청산. 끝난 거래만 반영(열린 포지션은 평가하지 않음)",
               "scopes": acc, "label_ko": LABEL_KO}
    return {"per_trade": per_trade, "account": account}


def _comparison(trades: list[dict], study: Optional[dict]) -> list[dict]:
    """Per timeframe: the live record next to the study's three periods."""
    out = []
    for tf in TFS:
        closed = [t for t in trades if t["tf"] == tf and t["status"] == "closed"]
        nets = np.array([t["net"] for t in closed], float)
        gross = np.array([t["gross_raw"] for t in closed], float)
        live = {"trades": len(closed), "win_pct": _f(100.0 * float((nets > 0).mean())) if len(nets) else None,
                "net_pct": _pct(nets.mean()) if len(nets) else None, "gross_pct": _pct(gross.mean()) if len(gross) else None}
        out.append({"tf": tf, "live": live, "study": study["main"].get(tf) if study else None,
                    "study_p12": study["p12"].get(tf) if study else None,
                    "study_vs_flip": study["vs_flip"].get(tf) if study else None, "label_ko": LABEL_KO})
    return out


def member(path: str, member_id: str, now_ms: Optional[int] = None) -> dict:
    import time
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    c, bad = _open(path)
    if bad:
        return bad
    try:
        row = c.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
        if row is None:
            return dict(NOT_STARTED)
        row = dict(row)
        spec = _spec(row)
        study = STUDIES.get(spec.get("study", ""))
        trades = [dict(r) for r in c.execute("SELECT * FROM trades WHERE member_id = ? ORDER BY entry_ms, coin, tf", (member_id,))]
        clones = [dict(r) for r in c.execute("SELECT * FROM clones WHERE member_id = ? ORDER BY trade_id, k", (member_id,))]
        series = [dict(r) for r in c.execute("SELECT * FROM series_state WHERE member_id = ?", (member_id,))]
        acct = AccountSpec(**spec["account"])
        last = sorted(trades, key=lambda t: (int(t["entry_ms"]), t["trade_id"]), reverse=True)[:LAST_TRADES]
        act = row.get("activated_ms")
        sigs = [dict(r) for r in c.execute(
            "SELECT signal_id, coin, tf, side, bar_ms, plan_entry, stop, target, rr, touches, status FROM signals "
            "WHERE member_id = ? ORDER BY bar_ms DESC, signal_id LIMIT 50", (member_id,))]
        return {
            "state": "ok", "label_ko": LABEL_KO, "as_of_ms": now,
            "card": _card(c, row, now),
            "curve": curves(trades, clones, series, int(row["start_ms"]), acct),
            "table": _table(c, member_id, tuple(spec["coins"]), tuple(spec["tfs"])),
            "trades": [_trade_row(t, act) for t in last],
            "signals": [{"signal_id": s["signal_id"], "coin": s["coin"], "tf": s["tf"], "side": int(s["side"]),
                         "side_ko": SIDE_KO[int(s["side"])], "bar_ms": s["bar_ms"], "plan_entry": _f(s["plan_entry"], 8),
                         "stop": _f(s["stop"], 8), "target": _f(s["target"], 8), "rr": _f(s["rr"], 2),
                         "touches": s["touches"], "status": s["status"], "status_ko": SIGNAL_KO.get(s["status"], s["status"])}
                        for s in sigs],
            "comparison": _comparison(trades, study),
            "study": study,
        }
    except Exception as exc:  # noqa: BLE001  (whatever goes wrong while reading is an error with its reason, never an empty view)
        return _err(f"{type(exc).__name__}: {exc}")
    finally:
        c.close()
