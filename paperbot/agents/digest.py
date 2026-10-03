"""Code-only digests for the owners and the staff (owners' choice 2026-10-03). Read-only: nothing here changes an
account, a meeting or a cursor.

- ``tf_split(paper_ro, initial)``: every strategy's five timeframe accounts side by side (closed-trade P&L, trades,
  win rate, mean ROE, the price move before costs, fees and funding per trade, hold time, exits, long/short, coins)
  and the strategies whose timeframes disagree (one account up, another down, both with enough trades). The
  timeframe-split meeting (trigger 'tf_split', a strategy room) and the dashboard read it.
- ``day_digest(agents_ro, day)``: every meeting of one KST day with its code summary, the speakers, the lead's
  lines, who answered whom (``responds_to``) and the disagreement left open.
- ``staff_board(agents_ro, now_ms, days)``: per staff member: turns, meetings, replies given and received
  (agree / disagree / add), questions asked, unreadable answers, proposals by kind, devil's-advocate verdicts,
  facts vs hypotheses, and the graded predictions (scorecard.py) with the latest grades.
- ``week_report(paper_ro, agents_ro, now_ms, initial)``: the last 7 days against the 7 before (strategy accounts,
  coin flips, top and bottom strategies, timeframes, busts, meetings, AI use, hypotheses, tests), and
  ``compose_week`` for the Sunday Telegram report.

P&L here is the sum of CLOSED trades' net P&L (fees and funding included), i.e. the wallet's change without the
open positions. A strategy's 30-day verdict is the checkpoint's (coin flips x 2,000), never these numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any, Iterable, Optional

from ..cards import REASON_KO
from . import rooms_db as R

TFS = ("5m", "15m", "30m", "1h", "4h")
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
KST_MS = 9 * 3_600_000
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SPEAKING = ("analysis", "challenge", "expert", "revision", "verdict", "summary")
STANCES = ("agree", "disagree", "add")


# ---------------------------------------------------------------- small helpers
def _loads(s: Any) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def _f(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def _r(x: Optional[float], n: int = 2) -> Optional[float]:
    return None if x is None else round(float(x), n)


def day_start_ms(day: str) -> int:
    """00:00 KST of 'YYYY-MM-DD' in epoch ms."""
    d = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000) - KST_MS


def initial_equity(paper_ro: Optional[sqlite3.Connection]) -> float:
    """The run's starting equity per account (state 'run'.initial_equity, else config.V3_INITIAL)."""
    try:
        r = paper_ro.execute("SELECT data FROM state WHERE k = 'run'").fetchone() if paper_ro is not None else None
        v = _f((_loads(r[0]) or {}).get("initial_equity")) if r else 0.0
    except sqlite3.Error:
        v = 0.0
    if v > 0:
        return v
    from ..config import V3_INITIAL
    return float(V3_INITIAL)


def _names_ko() -> dict:
    try:
        from .roster3 import STRATEGY_KO
        return dict(STRATEGY_KO)
    except ImportError:  # pragma: no cover
        return {}


def _closed(paper_ro: sqlite3.Connection, since_ms: int = 0, until_ms: Optional[int] = None,
            kinds: Iterable[str] = ("strategy",)) -> list[tuple]:
    """(account_id, kind, strategy, timeframe, trade dict) of trades closed in [since, until), oldest first."""
    ks = list(kinds)
    sql = ("SELECT t.account_id, a.kind, a.strategy, a.timeframe, t.data FROM trades t JOIN accounts a "
           f"ON a.account_id = t.account_id WHERE a.kind IN ({','.join('?' * len(ks))}) AND t.exit_time >= ?")
    args: list = [*ks, int(since_ms)]
    if until_ms is not None:
        sql += " AND t.exit_time < ?"
        args.append(int(until_ms))
    out = []
    for aid, kind, strat, tf, data in paper_ro.execute(sql + " ORDER BY t.exit_time, t.id", args):
        d = _loads(data)
        if isinstance(d, dict) and "pnl" in d:
            out.append((aid, kind, strat, tf, d))
    return out


# ---------------------------------------------------------------- timeframe split
def tf_stats(trades: list[dict]) -> dict:
    """One account's closed trades in numbers (code). ``move_before_costs`` is the mean price move in the
    trade's direction; ``cost_per_trade`` the mean fees + funding; ``cost_vs_gross`` the costs against the
    gross P&L before them (above 1 = costs ate more than the moves made)."""
    n = len(trades)
    if not n:
        return {"trades": 0}
    pnl = [_f(t.get("pnl")) for t in trades]
    fees = [_f(t.get("fees")) for t in trades]
    fund = [_f(t.get("funding")) for t in trades]
    gross = [p + f + u for p, f, u in zip(pnl, fees, fund)]
    wins = sum(1 for p in pnl if p > 0)
    holds = [(_f(t.get("exit_time")) - _f(t.get("entry_time"))) / 60_000 for t in trades]
    exits: dict = {}
    for t in trades:
        k = REASON_KO.get(str(t.get("exit_reason")), str(t.get("exit_reason")))
        exits[k] = exits.get(k, 0) + 1
    sides: dict = {}
    coins: dict = {}
    for t, p in zip(trades, pnl):
        s = sides.setdefault("롱" if _f(t.get("side")) > 0 else "숏", {"trades": 0, "wins": 0, "pnl": 0.0})
        s["trades"] += 1
        s["wins"] += p > 0
        s["pnl"] += p
        c = coins.setdefault(str(t.get("symbol", "?")).replace("USDT", ""), {"trades": 0, "pnl": 0.0})
        c["trades"] += 1
        c["pnl"] += p
    g_abs = sum(abs(g) for g in gross)
    costs = sum(fees) + sum(fund)
    return {
        "trades": n, "wins": wins, "losses": sum(1 for p in pnl if p < 0), "win_rate": round(wins / n, 3),
        "pnl": round(sum(pnl), 2), "mean_pnl": round(sum(pnl) / n, 2),
        "mean_roe": round(sum(_f(t.get("roe")) for t in trades) / n, 4),
        "move_before_costs": round(sum(_f(t.get("price_move")) for t in trades) / n, 5),
        "gross_before_costs": round(sum(gross), 2), "costs": round(costs, 2),
        "cost_per_trade": round(costs / n, 3),
        "cost_vs_gross": round(costs / g_abs, 3) if g_abs > 0 else None,
        "mean_leverage": round(sum(_f(t.get("leverage")) for t in trades) / n, 1),
        "hold_min": round(sum(holds) / n, 1),
        "exits": dict(sorted(exits.items(), key=lambda kv: -kv[1])),
        "sides": {k: {"trades": v["trades"], "win_rate": round(v["wins"] / v["trades"], 3), "pnl": round(v["pnl"], 2)}
                  for k, v in sides.items()},
        "coins": {k: {"trades": v["trades"], "pnl": round(v["pnl"], 2)}
                  for k, v in sorted(coins.items(), key=lambda kv: kv[1]["pnl"])},
    }


def tf_split(paper_ro: Optional[sqlite3.Connection], initial: Optional[float] = None, strategy: Optional[str] = None,
             min_trades: int = 8, min_spread_pct: float = 0.10, since_ms: int = 0) -> dict:
    """Per strategy: its timeframe accounts (``tf_stats``), the best and worst timeframe, the spread between them
    and whether they disagree: best > 0 > worst, both with >= ``min_trades`` closed trades and a spread of at
    least ``min_spread_pct`` of the starting equity. ``split`` lists the disagreeing strategies, widest first."""
    if paper_ro is None:
        return {"error": "paper3.db 없음", "strategies": [], "split": []}
    init = float(initial) if initial else initial_equity(paper_ro)
    names = _names_ko()
    by: dict = {}
    try:
        rows = _closed(paper_ro, since_ms)
        accts = paper_ro.execute("SELECT account_id, strategy, timeframe FROM accounts WHERE kind = 'strategy'").fetchall()
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}", "strategies": [], "split": []}
    for _aid, s, tf in accts:
        if strategy is None or s == strategy:
            by.setdefault(s, {}).setdefault(tf, [])
    for _aid, _kind, s, tf, d in rows:
        if strategy is None or s == strategy:
            by.setdefault(s, {}).setdefault(tf, []).append(d)
    out = []
    for s, per in by.items():
        tfs = {tf: tf_stats(ts) for tf, ts in sorted(per.items(), key=lambda kv: TFS.index(kv[0]) if kv[0] in TFS else 9)}
        live = [(tf, v) for tf, v in tfs.items() if v["trades"]]
        row: dict = {"strategy": s, "name_ko": names.get(s, s), "timeframes": tfs,
                     "pnl": round(sum(v.get("pnl", 0.0) for v in tfs.values()), 2),
                     "trades": sum(v["trades"] for v in tfs.values()), "split": False}
        # the pair is chosen among the timeframes with enough trades (a one-trade outlier never hides a split);
        # with none of them, among all that traded (shown, never a split)
        ok = [(tf, v) for tf, v in live if v["trades"] >= min_trades]
        pool = ok or live
        if pool:
            best = max(pool, key=lambda kv: kv[1]["pnl"])
            worst = min(pool, key=lambda kv: kv[1]["pnl"])
            spread = best[1]["pnl"] - worst[1]["pnl"]
            row.update(best_tf=best[0], worst_tf=worst[0], best_pnl=best[1]["pnl"], worst_pnl=worst[1]["pnl"],
                       spread=round(spread, 2), spread_pct=round(spread / init, 4) if init else None)
            row["split"] = bool(ok and best[1]["pnl"] > 0 > worst[1]["pnl"] and init
                                and spread >= min_spread_pct * init)
        out.append(row)
    out.sort(key=lambda r: -(r.get("spread") or 0))
    return {"initial": init, "min_trades": min_trades, "min_spread_pct": min_spread_pct, "strategies": out,
            "split": [r["strategy"] for r in out if r["split"]],
            "note": "끝난 거래 기준(수수료·펀딩 포함, 열린 포지션 제외). 한 매매법의 봉별 성적이 갈리면 비용(거래당 비용 vs "
                    "비용 전 가격 움직임), 거래 수, 롱·숏, 코인, 청산 이유, 보유 시간에서 차이를 찾음. 거래 30건 미만이면 운일 수 있음"}


def tf_packet(paper_ro: Optional[sqlite3.Connection], strategy: str, initial: Optional[float] = None) -> dict:
    """The timeframe-split meeting's packet for one strategy (``tf_split`` limited to it, plus its wins vs
    losses by timeframe)."""
    got = tf_split(paper_ro, initial, strategy=strategy)
    row = next((r for r in got.get("strategies") or [] if r["strategy"] == strategy), None)
    if row is None:
        return {"error": got.get("error") or "이 매매법의 거래가 아직 없음"}
    return {**row, "note": got["note"],
            "how_to_read": ("timeframes.<봉>: trades·win_rate·pnl·mean_roe, move_before_costs(비용 전 거래당 가격 움직임, "
                            "0.002 = 0.2%), cost_per_trade(거래당 수수료+펀딩 $), cost_vs_gross(비용 ÷ 비용 전 손익 크기, "
                            "1 넘으면 비용이 움직임보다 큼), hold_min, exits, sides, coins")}


# ---------------------------------------------------------------- one day's meetings
def _round_rows(a: sqlite3.Connection, since: int, until: int) -> list[dict]:
    rows = R._dicts(a.execute(
        "SELECT r.round_id, r.room_id, r.trigger, r.trigger_data, r.started_ts, r.ended_ts, r.status, r.decision, "
        "r.calls, r.tokens, m.title FROM rounds r LEFT JOIN rooms m ON m.room_id = r.room_id "
        "WHERE r.started_ts >= ? AND r.started_ts < ? ORDER BY r.started_ts, r.round_id", (since, until)))
    for r in rows:
        r["trigger_data"] = _loads(r["trigger_data"]) or {}
        r["decision"] = _loads(r["decision"]) or {}
    return rows


def day_digest(agents_ro: Optional[sqlite3.Connection], day: str) -> dict:
    """Every meeting that started on KST ``day``: room, kind, status, its code summary, speakers in order, the
    lead's lines and the disagreement left open, replies (who answered whom), questions, and code results."""
    from .rooms import TRIGGER_KO  # the meeting kinds in Korean (one table for the room and here)
    t0 = day_start_ms(day)
    out: dict = {"day": day, "meetings": [], "by_trigger": {}, "calls": 0, "tokens": 0}
    if agents_ro is None:
        out["error"] = "agents3.db 없음"
        return out
    try:
        rounds = _round_rows(agents_ro, t0, t0 + DAY_MS)
        ids = [r["round_id"] for r in rounds]
        msgs: dict = {}
        if ids:
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                for m in R._dicts(agents_ro.execute(
                        f"SELECT id, ts, round_id, role, speaker_name, kind, text, data FROM messages WHERE round_id IN "
                        f"({','.join('?' * len(part))}) ORDER BY id", part)):
                    msgs.setdefault(m["round_id"], []).append(m)
    except sqlite3.Error as exc:
        out["error"] = f"agents3.db를 읽지 못함: {type(exc).__name__}"
        return out
    for r in rounds:
        ms = msgs.get(r["round_id"], [])
        speakers, replies, asks, lead, disagreement, results, verdict = [], [], [], [], "", [], None
        for m in ms:
            data = _loads(m["data"]) or {}
            ans = data.get("answer") if isinstance(data, dict) else None
            if m["kind"] in SPEAKING and m["role"] not in ("code", "system"):
                speakers.append({"role": m["role"], "name": R.role_name(m["role"]), "kind": m["kind"]})
                if isinstance(ans, dict):
                    rt = ans.get("responds_to")
                    if isinstance(rt, dict) and rt.get("stance") in STANCES:
                        replies.append({"from": m["role"], "from_name": R.role_name(m["role"]), "to": rt.get("role"),
                                        "to_name": R.role_name(str(rt.get("role"))), "stance": rt["stance"],
                                        "point": str(rt.get("point") or "")[:300]})
                    if ans.get("ask_next"):
                        asks.append({"from": m["role"], "from_name": R.role_name(m["role"]),
                                     "text": str(ans["ask_next"])[:200]})
                    if m["kind"] == "summary" and isinstance(ans.get("summary"), list):
                        lead = [str(x)[:300] for x in ans["summary"]][:3]
                        disagreement = str(ans.get("open_disagreement") or "")[:300]
                    if ans.get("verdict") in ("agree", "disagree", "needs_test") and m["kind"] == "challenge":
                        verdict = "unreadable" if ans.get("verdict_coerced") else ans["verdict"]
            elif m["kind"] == "code_result":
                results.append(str(m["text"] or "").split("\n", 1)[0][:300])
        dec = r["decision"]
        final = dec.get("final") if isinstance(dec.get("final"), dict) else {}
        out["meetings"].append({
            "round_id": r["round_id"], "room_id": r["room_id"], "title": r.get("title") or r["room_id"],
            "trigger": r["trigger"], "trigger_ko": TRIGGER_KO.get(r["trigger"], r["trigger"]),
            "why": str(r["trigger_data"].get("summary_ko") or "")[:300],
            "started_ts": r["started_ts"], "ended_ts": r["ended_ts"], "status": r["status"],
            "calls": int(r["calls"] or 0), "tokens": int(r["tokens"] or 0),
            "summary_ko": str(dec.get("summary_ko") or "")[:1500], "action": final.get("action") or dec.get("action"),
            "challenge": verdict or dec.get("challenge"), "speakers": speakers, "replies": replies, "asks": asks,
            "lead": lead, "open_disagreement": disagreement, "results": results[:5]})
        k = out["by_trigger"].setdefault(r["trigger"], {"trigger_ko": TRIGGER_KO.get(r["trigger"], r["trigger"]),
                                                       "meetings": 0})
        k["meetings"] += 1
        out["calls"] += int(r["calls"] or 0)
        out["tokens"] += int(r["tokens"] or 0)
    out["n"] = len(out["meetings"])
    out["disagreements"] = sum(1 for m in out["meetings"] for x in m["replies"] if x["stance"] == "disagree")
    return out


# ---------------------------------------------------------------- staff
def _team_of() -> dict:
    try:
        from .roster3 import ROLES, SPECIALISTS
        return {r[0]: r[2] for r in ROLES + SPECIALISTS}
    except ImportError:  # pragma: no cover
        return {}


def staff_board(agents_ro: Optional[sqlite3.Connection], now_ms: int, days: int = 7) -> dict:
    """Per staff member over the last ``days`` days (turns, meetings, replies, questions, unreadable answers,
    proposals, verdicts, facts vs hypotheses) and over the whole run (graded predictions)."""
    from .scorecard import describe_ko, scorecard
    since = int(now_ms) - int(days) * DAY_MS
    out: dict = {"days": days, "since": since, "staff": [], "recent_grades": []}
    if agents_ro is None:
        out["error"] = "agents3.db 없음"
        return out
    by: dict = {}

    def get(role: str) -> dict:
        return by.setdefault(role, {"role": role, "name": R.role_name(role), "team": _team_of().get(role, ""),
                                    "turns": 0, "meetings": set(), "facts": 0, "hypotheses_said": 0,
                                    "replies": {s: 0 for s in STANCES}, "replied_by": {s: 0 for s in STANCES},
                                    "asks": 0, "unreadable": 0, "proposals": {}, "verdicts": {},
                                    "last_ts": None})
    try:
        rows = R._dicts(agents_ro.execute(
            "SELECT ts, round_id, role, kind, text, data FROM messages WHERE ts >= ? AND kind IN "
            f"({','.join('?' * (len(SPEAKING) + 1))}) ORDER BY id", (since, *SPEAKING, "system")))
    except sqlite3.Error as exc:
        out["error"] = f"agents3.db를 읽지 못함: {type(exc).__name__}"
        return out
    for m in rows:
        data = _loads(m["data"]) or {}
        if m["kind"] == "system":
            who = data.get("role") if isinstance(data, dict) else None
            # the skipped turn ('…의 답을 읽을 수 없어 이번 차례는 건너뜁니다'), not a coerced verdict of a readable one
            if who and "답을 읽을 수 없어" in str(m["text"]) and not data.get("verdict_coerced"):
                get(who)["unreadable"] += 1
            continue
        if m["role"] in ("code", "system", "owner"):
            continue
        k = get(m["role"])
        k["turns"] += 1
        if m["round_id"] is not None:
            k["meetings"].add(m["round_id"])
        k["last_ts"] = max(k["last_ts"] or 0, int(m["ts"]))
        ans = data.get("answer") if isinstance(data, dict) else None
        if not isinstance(ans, dict):
            continue
        for f in ans.get("findings") or []:
            if isinstance(f, dict):
                if f.get("kind") == "fact":
                    k["facts"] += 1
                else:
                    k["hypotheses_said"] += 1
        rt = ans.get("responds_to")
        if isinstance(rt, dict) and rt.get("stance") in STANCES:
            k["replies"][rt["stance"]] += 1
            if rt.get("role"):
                get(str(rt["role"]))["replied_by"][rt["stance"]] += 1
        if ans.get("ask_next"):
            k["asks"] += 1
        for key in ("proposal", "suggestion"):
            p = ans.get(key)
            if isinstance(p, dict) and p.get("action"):
                a = str(p["action"])
                k["proposals"][a] = k["proposals"].get(a, 0) + 1
        if ans.get("verdict") in ("agree", "disagree", "needs_test") and not ans.get("verdict_coerced"):
            k["verdicts"][ans["verdict"]] = k["verdicts"].get(ans["verdict"], 0) + 1
    card = scorecard(agents_ro)
    graded = {r["role"]: r for r in card.get("roles") or []}
    for role in set(by) | {r for r in graded if r}:
        k = get(role)
        g = graded.get(role) or {}
        k["predictions"] = {f: g.get(f, 0) for f in ("graded", "correct", "waiting", "expired", "not_gradable")}
        k["predictions"]["hit_rate"] = g.get("hit_rate")
    staff = []
    for k in by.values():
        k["meetings"] = len(k["meetings"])
        staff.append(k)
    staff.sort(key=lambda k: (-k["turns"], k["name"]))
    out["staff"] = staff
    out["total"] = card.get("total")
    # the latest graded predictions (whole run), newest first
    try:
        rows = R._dicts(agents_ro.execute(
            "SELECT r.ts, r.status, r.result, t.id, t.strategy, t.spec FROM trial_results r JOIN trials t "
            "ON t.id = r.trial_id WHERE t.kind = 'hypothesis' AND r.status IN ('graded', 'expired') "
            "ORDER BY r.id DESC LIMIT 30"))
        for r in rows:
            spec = _loads(r["spec"]) or {}
            body = _loads(r["result"]) or {}
            p = spec.get("prediction") if isinstance(spec.get("prediction"), dict) else body.get("prediction")
            if not isinstance(p, dict):
                continue
            by_role = spec.get("by") or body.get("by") or ""
            out["recent_grades"].append({
                "trial_id": r["id"], "strategy": r["strategy"], "role": by_role, "name": R.role_name(by_role) if by_role else "",
                "text": str(spec.get("text") or "")[:300], "prediction_ko": describe_ko(p),
                "status": r["status"], "correct": body.get("correct"), "value": body.get("value"),
                "n": body.get("n"), "ts": r["ts"]})
    except (sqlite3.Error, KeyError, TypeError, ValueError):
        pass
    out["note"] = ("말한 횟수·반응은 최근 며칠의 방 기록(코드 집계). 예측 채점은 실험 전체: 예측이 붙은 가설만, 가설을 쓴 뒤 "
                   "들어간 거래로 코드가 한 번 판정")
    return out


# ---------------------------------------------------------------- the week
def _strategy_week(rows: list[tuple]) -> dict:
    by: dict = {}
    for _aid, _kind, s, _tf, d in rows:
        k = by.setdefault(s, {"pnl": 0.0, "trades": 0, "wins": 0})
        p = _f(d.get("pnl"))
        k["pnl"] += p
        k["trades"] += 1
        k["wins"] += p > 0
    return by


def _account_week(rows: list[tuple]) -> dict:
    by: dict = {}
    for aid, kind, s, tf, d in rows:
        k = by.setdefault(aid, {"kind": kind, "strategy": s, "timeframe": tf, "pnl": 0.0, "trades": 0})
        k["pnl"] += _f(d.get("pnl"))
        k["trades"] += 1
    return by


def _median(xs: list[float]) -> Optional[float]:
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def week_report(paper_ro: Optional[sqlite3.Connection], agents_ro: Optional[sqlite3.Connection], now_ms: int,
                initial: Optional[float] = None, k: int = 5) -> dict:
    """The 7 days before ``now_ms`` against the 7 before them (code)."""
    from .rooms import TRIGGER_KO
    now = int(now_ms)
    w0, p0 = now - 7 * DAY_MS, now - 14 * DAY_MS
    out: dict = {"from": w0, "to": now, "names_ko": None}
    names = _names_ko()
    if paper_ro is not None:
        try:
            out["initial"] = initial_equity(paper_ro) if not initial else float(initial)
            both = _closed(paper_ro, p0, now, kinds=("strategy", "random"))
            accts = paper_ro.execute("SELECT account_id, kind, strategy, timeframe, created_ts FROM accounts "
                                     "WHERE kind IN ('strategy', 'random')").fetchall()
            first = paper_ro.execute("SELECT MIN(created_ts) FROM accounts WHERE kind = 'strategy'").fetchone()
            busts = paper_ro.execute("SELECT ts, text FROM alerts WHERE ts >= ? AND ts < ? AND text LIKE '%BUST%' "
                                     "ORDER BY ts", (w0, now)).fetchall()
        except sqlite3.Error as exc:
            out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
            both, accts, first, busts = [], [], None, []
        out["run_start"] = int(first[0]) if first and first[0] else None
        cur = [r for r in both if _f(r[4].get("exit_time")) >= w0]
        prev = [r for r in both if _f(r[4].get("exit_time")) < w0]
        s_cur = [r for r in cur if r[1] == "strategy"]
        s_prev = [r for r in prev if r[1] == "strategy"]

        def tot(rows: list[tuple]) -> dict:
            n = len(rows)
            w = sum(1 for r in rows if _f(r[4].get("pnl")) > 0)
            return {"pnl": round(sum(_f(r[4].get("pnl")) for r in rows), 2), "trades": n, "wins": w,
                    "win_rate": round(w / n, 3) if n else None}
        out["strategies_total"] = tot(s_cur)
        out["strategies_total_prev"] = tot(s_prev)
        # per account this week: strategy accounts against the coin flips of the same timeframe
        acc = _account_week(cur)
        flips_by_tf: dict = {}
        for aid, kind, _s, tf, _st in accts:
            if kind == "random":
                flips_by_tf.setdefault(tf, []).append(acc.get(aid, {}).get("pnl", 0.0))
        flips = [x for xs in flips_by_tf.values() for x in xs]
        beat, n_strat = 0, 0
        for aid, kind, _s, tf, _st in accts:
            if kind != "strategy":
                continue
            n_strat += 1
            med = _median(flips_by_tf.get(tf, []))
            if med is not None and acc.get(aid, {}).get("pnl", 0.0) > med:
                beat += 1
        out["coin_flips"] = {"mean_pnl": round(sum(flips) / len(flips), 2) if flips else None,
                             "accounts": len(flips), "strategy_accounts_beating_median": beat,
                             "strategy_accounts": n_strat}
        # strategies: this week's rank against last week's
        wk, pw = _strategy_week(s_cur), _strategy_week(s_prev)
        all_s = sorted({s for _a, kind, s, _tf, _st in accts if kind == "strategy"})
        rank = sorted(all_s, key=lambda s: -(wk.get(s, {}).get("pnl", 0.0)))
        prank = {s: i + 1 for i, s in enumerate(sorted(all_s, key=lambda s: -(pw.get(s, {}).get("pnl", 0.0))))}

        def srow(s: str, i: int) -> dict:
            v = wk.get(s, {"pnl": 0.0, "trades": 0, "wins": 0})
            return {"strategy": s, "name_ko": names.get(s, s), "rank": i + 1, "of": len(rank),
                    "pnl": round(v["pnl"], 2), "trades": v["trades"],
                    "win_rate": round(v["wins"] / v["trades"], 3) if v["trades"] else None,
                    "prev_rank": prank.get(s) if s_prev else None}
        out["top"] = [srow(s, i) for i, s in enumerate(rank[:k])]
        out["bottom"] = [srow(s, len(rank) - 1 - i) for i, s in enumerate(reversed(rank[-k:]))] if len(rank) > k else []
        # timeframes
        tfw: dict = {}
        for _aid, _kind, _s, tf, d in s_cur:
            t = tfw.setdefault(tf, {"pnl": 0.0, "trades": 0, "wins": 0})
            t["pnl"] += _f(d.get("pnl"))
            t["trades"] += 1
            t["wins"] += _f(d.get("pnl")) > 0
        out["timeframes"] = {tf: {"pnl": round(v["pnl"], 2), "trades": v["trades"],
                                  "win_rate": round(v["wins"] / v["trades"], 3) if v["trades"] else None}
                             for tf, v in sorted(tfw.items(), key=lambda kv: TFS.index(kv[0]) if kv[0] in TFS else 9)}
        # the week's biggest single accounts
        sa = [dict(account=a, **v) for a, v in acc.items() if v["kind"] == "strategy"]
        sa.sort(key=lambda r: -r["pnl"])
        out["best_accounts"] = [{"account": r["account"], "pnl": round(r["pnl"], 2), "trades": r["trades"]} for r in sa[:3]]
        out["worst_accounts"] = [{"account": r["account"], "pnl": round(r["pnl"], 2), "trades": r["trades"]}
                                 for r in sa[-3:][::-1]] if len(sa) > 3 else []
        strat_ids = {a[0] for a in accts if a[1] == "strategy"}

        def bust_of(tx: str) -> Optional[str]:      # '[<account>] BUST: ...' (engine notifier, book = account id)
            tx = str(tx)
            return tx[1:tx.find("]")] if tx.startswith("[") and "]" in tx else None
        out["busts"] = [{"ts": int(ts), "account": bust_of(tx), "text": str(tx)[:160]} for ts, tx in busts
                        if bust_of(tx) in strat_ids]
    # the staff's week
    if agents_ro is not None:
        try:
            meet: dict = {}
            for trig, n in agents_ro.execute("SELECT trigger, COUNT(*) FROM rounds WHERE started_ts >= ? AND started_ts < ? "
                                             "AND status IN ('done', 'no_action') GROUP BY trigger", (w0, now)):
                meet[TRIGGER_KO.get(trig, trig)] = int(n)
            calls = agents_ro.execute("SELECT COUNT(*), COALESCE(SUM(tokens), 0) FROM agent_calls WHERE ts >= ? AND ts < ?",
                                      (w0, now)).fetchone()
            hyp = agents_ro.execute("SELECT COUNT(*) FROM trials WHERE kind = 'hypothesis' AND ts >= ? AND ts < ?",
                                    (w0, now)).fetchone()
            graded = R._dicts(agents_ro.execute(
                "SELECT r.status, r.result FROM trial_results r JOIN trials t ON t.id = r.trial_id WHERE t.kind = "
                "'hypothesis' AND r.ts >= ? AND r.ts < ?", (w0, now)))
            # one row per trial: its first result that is a test outcome (not a later 'proposed' / 'lapsed', not a
            # run that did not happen: 'no_data' / 'error'), counted in the week that result was written
            tests = R._dicts(agents_ro.execute(
                "SELECT t.kind, r.status FROM trials t JOIN trial_results r ON r.id = (SELECT MIN(x.id) FROM "
                "trial_results x WHERE x.trial_id = t.id AND x.status NOT IN ('proposed', 'lapsed', 'no_data', 'error')) "
                "WHERE t.kind IN ('test', 'newlab') AND r.ts >= ? AND r.ts < ?", (w0, now)))
        except sqlite3.Error as exc:
            out["agents_error"] = f"agents3.db를 읽지 못함: {type(exc).__name__}"
        else:
            ok = [_loads(g["result"]) or {} for g in graded if g["status"] == "graded"]
            out["staff"] = {
                "meetings": dict(sorted(meet.items(), key=lambda kv: -kv[1])), "meetings_total": sum(meet.values()),
                "ai_calls": int(calls[0]), "ai_tokens": int(calls[1]), "hypotheses": int(hyp[0]),
                "predictions_graded": len(ok), "predictions_correct": sum(1 for g in ok if g.get("correct")),
                "tests": sum(1 for t in tests if t["kind"] == "test"),
                "tests_passed": sum(1 for t in tests if t["kind"] == "test" and t["status"] == "passed"),
                "lab_tests": sum(1 for t in tests if t["kind"] == "newlab"),
                "lab_passed": sum(1 for t in tests if t["kind"] == "newlab" and t["status"] == "passed")}
    out["note"] = ("최근 7일(코드 계산, 끝난 거래 손익·수수료와 펀딩 포함). 7일 성적은 운이 큼: 30일 판정은 체크포인트"
                   "(동전 봇 2,000개 비교)가 함")
    return out


def _usd(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def compose_week(rep: dict, limit: int = 4000) -> str:
    """The Sunday Telegram report (silent): numbers by code only, no AI text."""
    d = dt.datetime.fromtimestamp((rep["to"] + KST_MS) / 1000, dt.timezone.utc)
    L = [f"📊 주간 성적표 ({d.month}/{d.day}, 지난 7일)"]
    if rep.get("run_start") and rep["run_start"] > rep["from"]:
        s = dt.datetime.fromtimestamp((rep["run_start"] + KST_MS) / 1000, dt.timezone.utc)
        L[0] = f"📊 주간 성적표 ({d.month}/{d.day}, 실험 시작 {s.month}/{s.day}부터)"
    if rep.get("error"):
        L.append(f"(거래 기록을 읽지 못함: {rep['error']})")
    t, tp = rep.get("strategies_total") or {}, rep.get("strategies_total_prev") or {}
    if t:
        prev = f" (지난주 {_usd(tp.get('pnl'))}, 승률 {_pct(tp.get('win_rate'))})" if tp.get("trades") else ""
        L += ["", "[매매법 계좌: 코드 계산]",
              f"- 손익 {_usd(t.get('pnl'))} · 거래 {t.get('trades', 0):,}건 · 승률 {_pct(t.get('win_rate'))}{prev}"]
        cf = rep.get("coin_flips") or {}
        if cf.get("strategy_accounts"):
            L.append(f"- 같은 봉 동전 봇 중간값보다 나은 계좌 {cf['strategy_accounts_beating_median']}/{cf['strategy_accounts']}"
                     f" · 동전 봇 평균 {_usd(cf.get('mean_pnl'))}")
        if rep.get("busts"):
            L.append(f"- 파산 {len(rep['busts'])}개")
    def line(r: dict) -> str:
        mv = ""
        if r.get("prev_rank"):
            dlt = r["prev_rank"] - r["rank"]
            mv = f" ▲{dlt}" if dlt > 0 else f" ▼{-dlt}" if dlt < 0 else " ="
        return (f"{r['rank']}. {r['name_ko']} {_usd(r['pnl'])} (승률 {_pct(r.get('win_rate'))}, {r['trades']}건){mv}")
    if rep.get("top"):
        L += ["", "[이번 주 상위]"] + [line(r) for r in rep["top"]]
    if rep.get("bottom"):
        L += ["", "[이번 주 하위]"] + [line(r) for r in rep["bottom"]]
    if rep.get("timeframes"):
        L += ["", "[봉별] " + " · ".join(f"{TF_KO.get(tf, tf)} {_usd(v['pnl'])}" for tf, v in rep["timeframes"].items())]
    st = rep.get("staff")
    if st:
        top_kinds = ", ".join(f"{k} {v}" for k, v in list(st["meetings"].items())[:4])
        L += ["", "[직원]",
              f"- 회의 {st['meetings_total']}번" + (f" ({top_kinds})" if top_kinds else "") + f" · AI 호출 {st['ai_calls']:,}번",
              f"- 가설 {st['hypotheses']}건 기록 · 예측 채점 {st['predictions_graded']}건 중 {st['predictions_correct']}건 맞음",
              f"- 5년 시험 {st['tests']}건(통과 {st['tests_passed']}) · 새 매매법 시험 {st['lab_tests']}건(통과 {st['lab_passed']})"]
    L += ["", "※ 7일 성적은 운이 큽니다. 30일 판정은 체크포인트(동전 봇 2,000개 비교)가 합니다. 자세히: 대시보드 '회의 요약' 탭"]
    return "\n".join(L)[:limit]
