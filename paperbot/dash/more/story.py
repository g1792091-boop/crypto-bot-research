"""오늘의 하이라이트 (#/story, v4 additions): one Korea-time day of the run as seven small story pages. Read-only.

    GET /api/v4/story?day=YYYY-MM-DD        (default: today in Korea time; a day of the run only)

One answer is small (counts, medians and a few named accounts, never a list of every account):

- trades: the day's closed trades per group (count, wins, liquidations); summed P&L for core / reel / extra only (the
  DeepSeek and coin-flip groups are counted, owners' D10 / D11).
- groups: per group the accounts that went up / down / stayed flat that day and the median day change. Closed trades
  only: an account's day change = the day's P&L over its wallet before the day's first trade (equity_after - pnl of
  that trade); an account without a trade that day is flat (0); an account already bust before the day is left out.
  "flip_same" = the coin flips on the 36's timeframes (15m-4h, the same-bar comparison), "flip5" = the three 5m flips
  (the reel's comparison).
- best / worst: the account that made / lost the most that day among core / reel / extra (MAIN_GROUPS), with its group
  (one day is mostly luck; the page says so). DeepSeek and coin-flip accounts are never named with money (D10 / D11,
  CONTRACT rule 3): they are counted in groups / ds / reel.flips only.
- reel: the 5m reel's day (trades, P&L, win / loss pips) and its three 5m coin flips.
- ds: DeepSeek at count level only: up / flat / down, the median, the families' medians (참고), no account numbers.
- busts: liquidations per group and the accounts that went bust that day (named for core / reel / extra, counted for
  DeepSeek and the coin flips).
- meetings: the day's meetings (agents3.db rounds, read-only, what 회의 요약 lists): count, finished, decisions and the
  two conclusions to show (the lead's first summary line, else the code summary's first line).
- run: D+n of that day and now, the first verdict (dash.app.restart_banner); days: the run's days for the picker.

Cost: one indexed range query over the day's trades (trades_acct), the accounts table, one state row and a few rows of
agents3.db. Cached: today 60 s, an earlier day 30 minutes.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
import sqlite3
import statistics
import threading
import time
from typing import Any, Optional

from fastapi import HTTPException

DAY_MS = 86_400_000
KST_MS = 9 * 3_600_000
TODAY_TTL_S = 60.0
PAST_TTL_S = 1800.0
CACHE_MAX = 48
MAX_DAYS = 60                 # the picker lists the run's last 60 days at most
PIPS_MAX = 48                 # the reel's win / loss marks of one day
FLAT_EPS = 0.005              # |day P&L| under half a cent: flat
MAIN_GROUPS = ("core", "reel", "extra")       # groups shown with money per account (D10 / D11)
LINE_MAX = 160
_LEAD = re.compile(r"^\s*(📣\s*회의 시작:\s*|🧾\s*)")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------- days (Korea time)
def kst_day(ms: int) -> str:
    """'2026-10-05': the Korea-time calendar day of a ms timestamp."""
    return time.strftime("%Y-%m-%d", time.gmtime((int(ms) + KST_MS) / 1000))


def day_start(day: str) -> int:
    """00:00 KST of 'YYYY-MM-DD' in ms; ValueError for anything else."""
    if not isinstance(day, str) or not _DAY.fullmatch(day):
        raise ValueError(day)
    d = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000) - KST_MS


def day_n(start: int, ms: int) -> int:
    """D+n at ``ms`` on the checkpoint clock (whole days since 00:00 UTC of the start day; dash.app.restart_banner)."""
    return max(0, (int(ms) - (int(start) - int(start) % DAY_MS)) // DAY_MS)


def run_days(start: int, now: int, limit: int = MAX_DAYS) -> list[dict]:
    """The run's Korea-time days, oldest first (the last ``limit``): [{day, n, dn}] with n = the Korea-time day number
    (1 = the start day, the same count as 흐름 'N일째', so 오늘 and 어제 always differ) and dn = D+n at the day's end
    (now for today; the checkpoint clock moves at 09:00 KST)."""
    out, t = [], day_start(kst_day(start))
    while t <= now:
        out.append({"day": kst_day(t), "n": len(out) + 1, "dn": day_n(start, min(now, t + DAY_MS - 1))})
        t += DAY_MS
    return out[-limit:]


# ---------------------------------------------------------------- small readers (all read-only)
def _loads(s: Any) -> Any:
    try:
        return json.loads(s) if isinstance(s, (str, bytes)) else s
    except (TypeError, ValueError):
        return None


def run_start(c: sqlite3.Connection) -> Optional[int]:
    """The run start: the first original account's creation (checkpoint.run_facts, the verdict job's own clock)."""
    from ...checkpoint import run_facts
    try:
        return run_facts(c).get("start_ts")
    except (sqlite3.Error, TypeError, ValueError):
        return None


def accounts(c: sqlite3.Connection) -> list[dict]:
    """Every account with its v4 group and DeepSeek family (paperbot/groups.py, the single source)."""
    from ... import groups as G
    rows = [dict(zip(("account_id", "strategy", "timeframe", "kind", "created_ts", "data"), r)) for r in c.execute(
        "SELECT account_id, strategy, timeframe, kind, created_ts, data FROM accounts ORDER BY rowid")]
    for r in rows:
        r["group"] = G.group_of(r)
        r["family"] = G.family_of(r)
        r.pop("data", None)
    return rows


def busts(c: sqlite3.Connection) -> dict:
    """{account_id: last exit time} of the accounts the runner marks bust (state 'accounts'), the last exit from the
    trades index (a bust account trades no more: its last exit is when it went bust)."""
    r = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    eng = (_loads(r[0]) or {}).get("engines", {}) if r else {}
    out = {}
    for aid, e in (eng.items() if isinstance(eng, dict) else ()):
        if isinstance(e, dict) and e.get("bust"):
            x = c.execute("SELECT MAX(exit_time) FROM trades WHERE account_id = ?", (aid,)).fetchone()
            out[aid] = int(x[0]) if x and x[0] is not None else None
    return out


def window_trades(c: sqlite3.Connection, t0: int, t1: int) -> list[tuple]:
    """(account_id, pnl, exit_reason, exit_time, equity_after) of the trades closed in [t0, t1), oldest first. The
    accounts sub-select makes SQLite walk trades_acct (account_id, exit_time) per account instead of the whole table."""
    return c.execute(
        "SELECT account_id, pnl, exit_reason, exit_time, equity_after FROM trades "
        "WHERE account_id IN (SELECT account_id FROM accounts) AND exit_time >= ? AND exit_time < ? "
        "ORDER BY exit_time, id", (int(t0), int(t1))).fetchall()


def _strip(text: Any) -> str:
    first = str(text or "").strip().split("\n", 1)[0]
    return _LEAD.sub("", first).strip()[:LINE_MAX]


def _action(decision: dict) -> Optional[str]:
    final = decision.get("final") if isinstance(decision.get("final"), dict) else {}
    return final.get("action") or decision.get("action")


def _lead_line(a: sqlite3.Connection, room_id: str, round_id: int) -> str:
    """The lead's first summary line of one meeting (agents/digest.day_digest: the 'summary' turn's answer.summary),
    found through the room's index (messages_room), newest first."""
    try:
        r = a.execute("SELECT data FROM messages WHERE room_id = ? AND round_id = ? AND kind = 'summary' "
                      "ORDER BY id DESC LIMIT 1", (room_id, round_id)).fetchone()
    except sqlite3.Error:
        return ""
    ans = (_loads(r[0]) or {}).get("answer") if r else None
    lines = ans.get("summary") if isinstance(ans, dict) else None
    return _strip(lines[0]) if isinstance(lines, list) and lines else ""


def meetings(a: Optional[sqlite3.Connection], t0: int, t1: int, pick: int = 2, by: str = "started") -> dict:
    """Meetings of agents3.db in a window (``by`` 'started': started in [t0, t1); 'ended': finished in [t0, t1)): count,
    finished, decisions (status 'done'), running, and ``pick`` conclusions to show (decisions with an action first,
    then the newest): {round_id, room_id, title, ts, status, action, trigger, trigger_ko, line, code}."""
    out = {"n": 0, "finished": 0, "decided": 0, "running": 0, "lines": []}
    if a is None:
        out["error"] = "agents3.db 없음"
        return out
    col = "r.started_ts" if by == "started" else "r.ended_ts"
    try:
        rows = a.execute(
            "SELECT r.round_id, r.room_id, r.trigger, r.started_ts, r.ended_ts, r.status, r.decision, m.title "
            f"FROM rounds r LEFT JOIN rooms m ON m.room_id = r.room_id WHERE {col} >= ? AND {col} < ? "
            "ORDER BY r.round_id", (int(t0), int(t1))).fetchall()
    except sqlite3.Error as exc:
        out["error"] = f"agents3.db를 읽지 못함: {type(exc).__name__}"
        return out
    from ..app import _trigger_ko           # the meeting kinds in Korean (the office and the digest use the same table)
    tko = _trigger_ko()
    done = []
    for rid, room, trig, st_ts, en_ts, status, dec, title in rows:
        out["n"] += 1
        if status == "running":
            out["running"] += 1
            continue
        out["finished"] += 1
        out["decided"] += status == "done"
        d = _loads(dec) or {}
        d = d if isinstance(d, dict) else {}
        act = _action(d)
        done.append({"round_id": rid, "room_id": room, "title": title or room, "ts": en_ts or st_ts, "status": status,
                     "action": act, "trigger": trig, "trigger_ko": tko.get(trig, trig), "code": _strip(d.get("summary_ko")),
                     "_rank": (status == "done" and act not in (None, "no_action"), status == "done", en_ts or st_ts or 0)})
    done.sort(key=lambda m: m["_rank"], reverse=True)
    for m in done[:pick]:
        m.pop("_rank")
        m["line"] = _lead_line(a, m["room_id"], m["round_id"]) or m["code"] or m["trigger_ko"]
        out["lines"].append(m)
    return out


# ---------------------------------------------------------------- the day
def _acct_day(rows: list[tuple], reel_ids: set) -> dict:
    per: dict = {}
    for aid, pnl, reason, _ts, eq_after in rows:
        pnl = float(pnl or 0.0)
        p = per.get(aid)
        if p is None:
            per[aid] = p = {"n": 0, "wins": 0, "pnl": 0.0, "liq": 0, "start": float(eq_after or 0.0) - pnl}
            if aid in reel_ids:
                p["pips"] = []
        p["n"] += 1
        p["wins"] += pnl > 0
        p["pnl"] += pnl
        p["liq"] += reason == "LIQ"
        if "pips" in p and len(p["pips"]) < PIPS_MAX:
            p["pips"].append(1 if pnl > FLAT_EPS else -1 if pnl < -FLAT_EPS else 0)
    for p in per.values():
        p["change"] = p["pnl"] / p["start"] if p["start"] > 1e-9 else None
    return per


def _r(x: Optional[float], n: int) -> Optional[float]:
    return None if x is None else round(float(x), n)


def group_stats(accts: list[dict], per: dict) -> dict:
    """Up / down / flat, the median day change and the day's trades of a set of accounts. ``median``: every account
    (an idle one counts as 0, so it is often 0 when most accounts did not trade); ``median_active``: the accounts that
    traded that day only (the same rule for every group, the coin flips included)."""
    ch, act, up, down, n, trades, wins, liq, pnl, active = [], [], 0, 0, 0, 0, 0, 0, 0.0, 0
    for a in accts:
        n += 1
        p = per.get(a["account_id"])
        if p is None:
            ch.append(0.0)
            continue
        active += 1
        trades += p["n"]
        wins += p["wins"]
        liq += p["liq"]
        pnl += p["pnl"]
        up += p["pnl"] > FLAT_EPS
        down += p["pnl"] < -FLAT_EPS
        if p["change"] is not None:
            ch.append(p["change"])
            act.append(p["change"])
    return {"n": n, "up": up, "down": down, "flat": n - up - down, "active": active, "trades": trades, "wins": wins,
            "liq": liq, "pnl": round(pnl, 2), "median": _r(statistics.median(ch), 6) if ch else None,
            "median_active": _r(statistics.median(act), 6) if act else None}


def _named(a: dict, p: Optional[dict]) -> dict:
    out = {k: a[k] for k in ("account_id", "strategy", "timeframe", "kind", "group")}
    if p is not None:
        out.update(trades=p["n"], wins=p["wins"], pnl=round(p["pnl"], 2), change=_r(p["change"], 6), liq=p["liq"])
        if "pips" in p:
            out["pips"] = p["pips"]
    else:
        out.update(trades=0, wins=0, pnl=0.0, change=0.0, liq=0)
    return out


def story(c: sqlite3.Connection, agents: Optional[sqlite3.Connection], day: Optional[str], now: int,
          ledger: Optional[dict] = None) -> dict:
    """The story of one Korea-time day (see the module docstring). ValueError when the day is not a day of the run.
    ``ledger``: verdictday.read_ledger(checkpoint.db), so the verdict named is the verdict-day clock's."""
    from ..app import restart_banner
    from ...groups import DS_FAMILY_KO
    start = run_start(c)
    today = kst_day(now)
    day = day or today
    t0 = day_start(day)
    if start is None:
        return {"ready": False, "day": day, "today": day == today, "now": now, "days": []}
    if day > today or t0 + DAY_MS <= day_start(kst_day(start)):
        raise ValueError("그날은 실험 기간 밖입니다")
    t1 = t0 + DAY_MS
    end = min(now, t1)
    accts = [a for a in accounts(c) if a["created_ts"] < end]
    dead = busts(c)
    # an account already bust before the day is out of the day's counts; a bust that day is in (it lost that day)
    alive = [a for a in accts if not (a["account_id"] in dead and (dead[a["account_id"]] or 0) < t0)]
    reel_ids = {a["account_id"] for a in alive if a["group"] == "reel"}
    rows = window_trades(c, t0, t1)
    per = _acct_day(rows, reel_ids)
    by = {}
    for g in ("core", "ds200", "reel", "flip", "extra"):
        xs = [a for a in alive if a["group"] == g]
        if xs:
            by[g] = group_stats(xs, per)
    flips = [a for a in alive if a["group"] == "flip"]
    core_tfs = {a["timeframe"] for a in alive if a["group"] == "core"}
    flip_same = [a for a in flips if a["timeframe"] in core_tfs]
    flip5 = [a for a in flips if a["timeframe"] == "5m"]
    if flip_same:
        by["flip_same"] = group_stats(flip_same, per)
    if flip5:
        by["flip5"] = group_stats(flip5, per)
    trades = {"total": len(rows), "groups": {}}
    for g, st in by.items():
        if g in ("flip_same", "flip5"):
            continue
        t = {"trades": st["trades"], "wins": st["wins"], "liq": st["liq"]}
        if g in MAIN_GROUPS:
            t["pnl"] = st["pnl"]
        trades["groups"][g] = t
    # the day's biggest winner and loser of core / reel / extra (the page names the group and says one day is mostly
    # luck); DeepSeek and the coin flips are never named with money per account (D10 / D11)
    traded = [(per[a["account_id"]]["pnl"], a) for a in alive if a["account_id"] in per and a["group"] in MAIN_GROUPS]
    best = max(traded, key=lambda x: x[0], default=None)
    worst = min(traded, key=lambda x: x[0], default=None)
    # the reel and its three 5m coin flips
    reel = {"accounts": [_named(a, per.get(a["account_id"])) for a in alive if a["group"] == "reel"],
            "flips": [_named(a, per.get(a["account_id"])) for a in sorted(flip5, key=lambda x: x["strategy"])],
            "flips_median": by.get("flip5", {}).get("median"), "flips_median_active": by.get("flip5", {}).get("median_active")}
    for f in reel["flips"]:
        f.pop("pnl", None)               # coin flips: the change only (the yardstick, not a money story)
    # DeepSeek at count level: the group and its families (no account numbers)
    ds_accts = [a for a in alive if a["group"] == "ds200"]
    fams = {}
    for a in ds_accts:
        fams.setdefault(a["family"] or "?", []).append(a)
    families = []
    for f, xs in fams.items():
        st = group_stats(xs, per)
        families.append({"family": f, "ko": DS_FAMILY_KO.get(f, f), "n": st["n"], "up": st["up"], "down": st["down"],
                         "active": st["active"], "median": st["median"], "median_active": st["median_active"]})
    families.sort(key=lambda x: (x["median_active"] if x["median_active"] is not None else -9, x["up"] - x["down"]), reverse=True)
    best_fam = next((x for x in families if x["n"] >= 3 and x["active"] >= 2), None)
    ds = {**(by.get("ds200") or {"n": 0, "up": 0, "down": 0, "flat": 0, "active": 0, "trades": 0, "median": None,
                               "median_active": None}),
          "families": families, "best_family": best_fam}
    ds.pop("pnl", None)
    # liquidations and busts of the day
    liq = {g: st["liq"] for g, st in by.items() if g not in ("flip_same", "flip5") and st["liq"]}
    went = [a for a in accts if a["account_id"] in dead and t0 <= (dead[a["account_id"]] or -1) < t1]
    bust_by: dict = {}
    for a in went:
        bust_by[a["group"]] = bust_by.get(a["group"], 0) + 1
    named = sorted((a for a in went if a["group"] in MAIN_GROUPS), key=lambda a: dead[a["account_id"]], reverse=True)
    bust = {"liquidations": sum(liq.values()), "liq_by_group": liq, "busts": len(went), "bust_by_group": bust_by,
            "named": [{**{k: a[k] for k in ("account_id", "strategy", "timeframe", "kind", "group")},
                       "ts": dead[a["account_id"]]} for a in named[:5]]}
    rs = restart_banner(start, now, ledger)
    out = {
        "ready": True, "day": day, "today": day == today, "now": now, "t0": t0, "t1": t1, "start": start,
        "dn": day_n(start, end - 1), "dn_now": day_n(start, now), "of": rs.get("of"),
        "verdict_ts": rs.get("verdict_ts"), "verdict_mmdd": rs.get("verdict_mmdd"),
        "verdict_k": rs.get("checkpoint"), "verdict_due": rs.get("due"), "line_ko": rs.get("line_ko"),
        "days_left": max(0, -(-(int(rs["verdict_ts"]) - now) // DAY_MS)) if rs.get("verdict_ts") else None,
        "days": run_days(start, now),
        "trades": trades, "groups": by,
        "best": _named(best[1], per[best[1]["account_id"]]) if best and best[0] > FLAT_EPS else None,
        "worst": _named(worst[1], per[worst[1]["account_id"]]) if worst and worst[0] < -FLAT_EPS else None,
        "reel": reel, "ds": ds, "busts": bust,
        "meetings": meetings(agents, t0, t1),
    }
    return out


# ---------------------------------------------------------------- the route
def register(app, ctx) -> dict:
    data, rooms = ctx.data, ctx.rooms
    cache: dict = {}
    lock = threading.Lock()

    def compute(day: Optional[str], now: int) -> dict:
        from .verdictday import read_ledger
        with contextlib.closing(data.conn()) as c:
            with rooms.ro(rooms.agents_db) as a:
                return story(c, a, day, now, read_ledger(getattr(ctx, "checkpoint_db", None)))

    @app.get("/api/v4/story")
    def get_story(day: Optional[str] = None):
        """One Korea-time day of the run for the 오늘의 하이라이트 pages (today when no day; cached 60 s / 30 min)."""
        from ..app import json_finite
        now = int(time.time() * 1000)
        today = kst_day(now)
        key = day or today
        if not _DAY.fullmatch(key):
            raise HTTPException(400, "day는 YYYY-MM-DD")
        hit = cache.get(key)
        ttl = TODAY_TTL_S if key == today else PAST_TTL_S
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        with lock:                                   # one computation at a time (two phones opening together)
            hit = cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            try:
                v = json_finite(compute(key, now))
            except ValueError as exc:
                raise HTTPException(400, str(exc) if str(exc).startswith("그날") else "day는 YYYY-MM-DD") from None
            except sqlite3.Error as exc:
                raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
            if len(cache) >= CACHE_MAX:
                cache.clear()
            cache[key] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/story"], "cache": cache}
