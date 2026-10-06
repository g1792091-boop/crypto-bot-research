"""지난번 본 뒤로 바뀐 것 (core/since.js, v4 additions): what happened after a viewer's last visit. Read-only.

    GET /api/v4/since?after=<ms>

``after`` is the viewer's own last-visit time (kept in that browser only). It is clamped to the run start and to the
last 7 days (``clamped: true`` then, ``clamped_by`` "start" or "week", and the page says so). The answer is small:

- trades: closed trades per group after ``after`` (count, wins, liquidations; summed P&L for core / reel / extra only,
  DeepSeek and the coin flips are counted, owners' D10 / D11); best / worst single trade of core / reel / extra.
- busts: accounts that went bust since (named for core / reel / extra, counted for DeepSeek and the coin flips).
- meetings: meetings that finished since (count, decisions, the two conclusions to show; see story.meetings).
- alerts: the bot's warnings since (count per level, the latest three; the page turns them into Korean).
- milestones: D+n changed, a verdict day passed (``judged``: its result is stored in checkpoint.db yet, verdictday.py),
  a verdict result stored since (its day passed before), the observation period ended. ``line_ko``: the countdown's
  one sentence (verdictday.texts), the same as every other screen.

Cost: one grouped index walk over trades_acct, two LIMIT 1 queries, the last alerts, a few agents3.db rows. Cached per
minute bucket of (after, now).
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from typing import Optional

from .story import DAY_MS, MAIN_GROUPS, _loads, accounts, busts, day_n, meetings, run_start
from .verdictday import read_ledger

WEEK_MS = 7 * DAY_MS
TTL_S = 60.0
CACHE_MAX = 64
ALERTS_SCAN = 500             # newest alert rows looked at (the table has no time index; rowid order is time order)
MAIN_KINDS = ("strategy", "reel", "copy", "newlab")


def clamp_after(after: int, start: Optional[int], now: int) -> tuple[int, bool]:
    """``after`` within [max(run start, now - 7 days), now]; True when it was moved up."""
    lo = max(int(start or 0), now - WEEK_MS)
    a = min(max(int(after), 0), now)
    return (lo, True) if a < lo else (a, False)


def _trade_row(c: sqlite3.Connection, after: int, order: str) -> Optional[dict]:
    q = ("SELECT t.id, t.account_id, t.symbol, t.pnl, t.roe, t.exit_reason, t.exit_time, t.leverage FROM trades t "
         "WHERE t.account_id IN (SELECT account_id FROM accounts WHERE kind IN (%s)) AND t.exit_time > ? "
         "ORDER BY t.pnl %s, t.id DESC LIMIT 1" % (",".join("?" * len(MAIN_KINDS)), order))
    r = c.execute(q, (*MAIN_KINDS, int(after))).fetchone()
    if r is None:
        return None
    return dict(zip(("id", "account_id", "symbol", "pnl", "roe", "exit_reason", "exit_time", "leverage"), r))


def since(c: sqlite3.Connection, agents: Optional[sqlite3.Connection], after: int, now: int,
          clamped: bool = False, ledger: Optional[dict] = None) -> dict:
    """What happened in (after, now] (see the module docstring); ``after`` already clamped (clamp_after). ``ledger``:
    verdictday.read_ledger(checkpoint.db): a verdict day that passed says whether its result is stored yet."""
    from ..app import restart_banner
    from ...checkpoint import NO_VERDICT_DAYS, PERIOD_DAYS, checkpoint_ts, day_str
    start = run_start(c)
    out: dict = {"after": after, "now": now, "clamped": clamped, "start": start,
                 "clamped_by": None if not clamped else "start" if start is not None and after <= start else "week"}
    accts = {a["account_id"]: a for a in accounts(c)}
    # closed trades per group: one grouped walk of trades_acct (account_id, exit_time)
    groups: dict = {}
    total = 0
    for aid, n, pnl, wins, liq in c.execute(
            "SELECT account_id, COUNT(*), SUM(pnl), SUM(pnl > 0), SUM(exit_reason = 'LIQ') FROM trades "
            "WHERE account_id IN (SELECT account_id FROM accounts) AND exit_time > ? GROUP BY account_id", (after,)):
        g = accts.get(aid, {}).get("group", "other")
        x = groups.setdefault(g, {"trades": 0, "wins": 0, "liq": 0, "pnl": 0.0})
        x["trades"] += n
        x["wins"] += wins or 0
        x["liq"] += liq or 0
        x["pnl"] += pnl or 0.0
        total += n
    for g, x in groups.items():
        if g in MAIN_GROUPS:
            x["pnl"] = round(x["pnl"], 2)
        else:
            x.pop("pnl")                       # DeepSeek and the coin flips: counted, not summed (D10 / D11)
    out["trades"] = {"total": total, "groups": groups, "liquidations": sum(x["liq"] for x in groups.values())}
    best, worst = _trade_row(c, after, "DESC"), _trade_row(c, after, "ASC")
    for key, t, ok in (("best", best, lambda p: p > 0), ("worst", worst, lambda p: p < 0)):
        if t and ok(t["pnl"]):
            a = accts.get(t["account_id"], {})
            out[key] = {**t, "pnl": round(t["pnl"], 2), "roe": round(t["roe"] or 0.0, 6), "strategy": a.get("strategy"),
                        "timeframe": a.get("timeframe"), "kind": a.get("kind"), "group": a.get("group")}
        else:
            out[key] = None
    # accounts that went bust since
    dead = busts(c)
    went = [(aid, ts) for aid, ts in dead.items() if ts is not None and ts > after and aid in accts]
    by: dict = {}
    for aid, _ts in went:
        g = accts[aid]["group"]
        by[g] = by.get(g, 0) + 1
    named = sorted(((aid, ts) for aid, ts in went if accts[aid]["group"] in MAIN_GROUPS), key=lambda x: -x[1])
    out["busts"] = {"n": len(went), "by_group": by,
                    "named": [{**{k: accts[aid][k] for k in ("account_id", "strategy", "timeframe", "kind", "group")},
                               "ts": ts} for aid, ts in named[:3]]}
    # meetings that finished since
    out["meetings"] = meetings(agents, after + 1, now + 1, pick=2, by="ended")
    # the bot's warnings since (newest first)
    rows = c.execute("SELECT ts, level, text FROM alerts ORDER BY rowid DESC LIMIT ?", (ALERTS_SCAN,)).fetchall()
    al = [{"ts": ts, "level": lv, "text": str(tx or "")[:300]} for ts, lv, tx in rows if ts > after and lv != "INFO"]
    lv: dict = {}
    for x in al:
        lv[x["level"]] = lv.get(x["level"], 0) + 1
    # capped: the newest ALERTS_SCAN rows are all after ``after`` (there may be more)
    out["alerts"] = {"n": len(al), "by_level": lv, "latest": al[:3],
                     "capped": len(rows) == ALERTS_SCAN and rows[-1][0] > after}
    # milestones: a new day of the run, a verdict day, the end of the observation period
    ms = []
    if start is not None:
        d0, d1 = day_n(start, after), day_n(start, now)
        if d1 > d0:
            ms.append({"kind": "day", "from": d0, "to": d1})
        # a verdict day that passed since: whether its result is stored (checkpoint.db; the job computes it from 09:35),
        # and a result stored since even when its day passed before (the 09:10 visit, back at 20:00)
        verdicts = (ledger or {}).get("verdicts") or {}
        k = 1
        while checkpoint_ts(start, k) <= now and k * PERIOD_DAYS <= NO_VERDICT_DAYS:
            cp = checkpoint_ts(start, k)
            stored = verdicts.get(day_str(cp))
            if cp > after:
                ms.append({"kind": "verdict", "k": k, "ts": cp, "judged": stored is not None, "stored_ts": stored})
            elif stored is not None and stored > after:
                ms.append({"kind": "verdict_result", "k": k, "ts": stored, "cp_ts": cp})
            k += 1
        r = c.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()
        xs = _loads(r[0]) if r else None
        obs = xs.get("observe_until") if isinstance(xs, dict) and xs.get("v") == 1 else None
        obs = obs if isinstance(obs, int) and not isinstance(obs, bool) else start + 21 * DAY_MS
        if after < obs <= now:
            ms.append({"kind": "observe_end", "ts": obs})
        rs = restart_banner(start, now, ledger)
        out.update(dn=d1, of=rs.get("of"), verdict_ts=rs.get("verdict_ts"), verdict_mmdd=rs.get("verdict_mmdd"),
                   verdict_k=rs.get("checkpoint"), verdict_due=rs.get("due"), line_ko=rs.get("line_ko"))
    out["milestones"] = ms
    out["empty"] = not (total or out["busts"]["n"] or out["meetings"]["finished"] or al or ms)
    return out


def register(app, ctx) -> dict:
    data, rooms = ctx.data, ctx.rooms
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/since")
    def get_since(after: int = 0):
        """What happened after ``after`` (ms; clamped to the run start and the last 7 days), cached per minute."""
        from fastapi import HTTPException
        from ..app import json_finite
        now = int(time.time() * 1000)
        try:
            with contextlib.closing(data.conn()) as c:
                start = run_start(c)
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
        a, clamped = clamp_after(after, start, now)
        key = (a // 60_000, now // 60_000)
        hit = cache.get(key)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get(key)
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            try:
                with contextlib.closing(data.conn()) as c:
                    with rooms.ro(rooms.agents_db) as ag:
                        v = json_finite(since(c, ag, a, now, clamped, read_ledger(getattr(ctx, "checkpoint_db", None))))
            except sqlite3.Error as exc:
                raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
            if len(cache) >= CACHE_MAX:
                cache.clear()
            cache[key] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/since"], "cache": cache}
