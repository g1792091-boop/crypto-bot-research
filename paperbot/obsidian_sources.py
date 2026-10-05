"""Read-only loaders for the Obsidian vault exporter (paperbot/obsidian_export.py).

Every database is opened with ``rooms_db.open_ro`` (``mode=ro`` + ``query_only``); a missing file, a missing table
or a half-written row is "nothing yet", never an error. Nothing here writes anywhere. Numbers that code computed
(trades, equity, shadows) are loaded as they are; AI-written text (messages, notes, hypotheses) is loaded with a
length cap and always marked as AI-written by the note builders.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from .agents import rooms_db as R
from .obsidian_util import DAY_MS, kst_day, mean, num

TFS = ("15m", "30m", "1h", "4h")          # = config.V3_TRADE_TFS (a test keeps them equal)
MSG_TEXT_CAP = 1500                       # characters of a message kept in memory (notes cut it again)
MAX_ROUNDS = 20_000
MAX_MESSAGES = 60_000


def _loads(s: Any) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def _all(conn: Optional[sqlite3.Connection], sql: str, args: tuple = ()) -> list:
    if conn is None:
        return []
    try:
        return conn.execute(sql, args).fetchall()
    except (sqlite3.Error, OverflowError):
        return []


def _one(conn: Optional[sqlite3.Connection], sql: str, args: tuple = ()) -> Optional[tuple]:
    rows = _all(conn, sql, args)
    return tuple(rows[0]) if rows else None


def split_account(aid: str) -> tuple[str, str]:
    s, _, tf = str(aid).partition("@")
    return s, tf


# ------------------------------------------------------------------ the bundle
@dataclass
class Data:
    paths: dict = field(default_factory=dict)
    present: dict = field(default_factory=dict)          # db name -> bool
    snapshot_ms: int = 0
    # paper3
    run_start_ms: Optional[int] = None
    run_info: dict = field(default_factory=dict)
    accounts: dict = field(default_factory=dict)          # account_id -> {strategy, timeframe, kind, created_ts, parent}
    shape: dict = field(default_factory=dict)             # groups.shape_from_db: the run shape the accounts table holds
    equity: dict = field(default_factory=dict)            # account_id -> (equity, drawdown)
    engines: dict = field(default_factory=dict)           # account_id -> engine state (bust, halted, max_drawdown...)
    trade_stats: dict = field(default_factory=dict)       # account_id -> stats dict (see load_trades)
    tier_stats: dict = field(default_factory=dict)        # (strategy, tier) -> stats
    day_trades: dict = field(default_factory=dict)        # KST day -> {n, pnl, wins}
    heartbeat_ms: Optional[int] = None
    # daily3
    daily: list = field(default_factory=list)             # compact per-day dicts, oldest first
    shadow_by_strategy: dict = field(default_factory=dict)   # strategy -> {variant: {n, mean, base, diff}}
    shadow_all: dict = field(default_factory=dict)        # variant -> {n, mean, base, diff} (strategy accounts)
    # checkpoint
    verdict: Optional[dict] = None
    verdict_rows: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    # agents3
    rooms: list = field(default_factory=list)
    rounds: list = field(default_factory=list)
    messages: dict = field(default_factory=dict)          # round_id -> [msg dicts]
    room_messages: dict = field(default_factory=dict)     # role -> [count, last_ts]
    notes: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    scorecard: dict = field(default_factory=dict)
    trials: list = field(default_factory=list)            # kind in test/newlab/copy_proposal with latest result
    trial_counts: dict = field(default_factory=dict)
    proposals: list = field(default_factory=list)
    committee: list = field(default_factory=list)
    calls_by_day: dict = field(default_factory=dict)      # day -> [calls, tokens]
    calls_by_role: dict = field(default_factory=dict)     # role -> [calls, tokens]
    restart: Optional[dict] = None
    # inbox
    owner_messages: list = field(default_factory=list)
    approvals: list = field(default_factory=list)


# ------------------------------------------------------------------ paper3
def _trade_row_stats() -> dict:
    return {"n": 0, "wins": 0, "sum_roe": 0.0, "sum_pnl": 0.0, "liq": 0, "lock": 0, "sl": 0, "first": None,
            "last": None, "lev": defaultdict(int), "sum_r": 0.0, "n_r": 0}


def _add_trade(st: dict, exit_ms: int, reason: str, lev: int, pnl: float, roe: float,
               margin: Optional[float]) -> None:
    st["n"] += 1
    st["wins"] += pnl > 0
    st["sum_roe"] += roe
    st["sum_pnl"] += pnl
    st["liq"] += reason == "LIQ"
    st["lock"] += reason == "LOCK"
    st["sl"] += reason == "SL"
    st["lev"][int(lev)] += 1
    if margin and lev:
        st["sum_r"] += pnl / (margin * lev)
        st["n_r"] += 1
    st["first"] = exit_ms if st["first"] is None else min(st["first"], exit_ms)
    st["last"] = exit_ms if st["last"] is None else max(st["last"], exit_ms)


def load_paper(conn: Optional[sqlite3.Connection], d: Data) -> None:
    if conn is None:
        return
    for aid, strat, tf, kind, created, parent in _all(
            conn, "SELECT account_id, strategy, timeframe, kind, created_ts, parent FROM accounts ORDER BY account_id"):
        d.accounts[aid] = {"strategy": strat, "timeframe": tf, "kind": kind, "created_ts": created, "parent": parent}
    try:                     # paper v4 (G9): per-group counts as the accounts table holds them (never config's numbers)
        from .groups import shape_from_db
        d.shape = shape_from_db(conn) if d.accounts else {}
    except (sqlite3.Error, TypeError, ValueError):
        d.shape = {}
    starts = [a["created_ts"] for a in d.accounts.values() if a["kind"] in ("strategy", "random")]
    if starts:
        d.run_start_ms = int(min(starts))
    else:
        r = _one(conn, "SELECT MIN(started_ts) FROM runs")
        d.run_start_ms = int(r[0]) if r and r[0] is not None else None
    r = _one(conn, "SELECT data FROM runs ORDER BY id DESC LIMIT 1")
    if r:
        d.run_info = _loads(r[0]) or {}
    r = _one(conn, "SELECT data FROM state WHERE k = 'run'")
    if r:
        d.run_info = {**(_loads(r[0]) or {}), **d.run_info}
    r = _one(conn, "SELECT ts, data FROM state WHERE k = 'heartbeat'")
    if r:
        d.heartbeat_ms = int(r[0])
    r = _one(conn, "SELECT data FROM state WHERE k = 'accounts'")
    if r:
        eng = (_loads(r[0]) or {}).get("engines")
        if isinstance(eng, dict):
            d.engines = {k: {f: v.get(f) for f in ("wallet", "peak_equity", "max_drawdown", "halted", "bust",
                                                   "halt_reason") if isinstance(v, dict)}
                         for k, v in eng.items()}
    for aid, eq, dd in _all(conn, "SELECT account_id, equity, drawdown FROM equity e WHERE ts = "
                                  "(SELECT MAX(ts) FROM equity WHERE account_id = e.account_id)"):
        d.equity[aid] = (num(eq), num(dd))
    # trades: light columns plus the two fields that live in the JSON (tier, margin)
    per = {}
    tier = {}
    days = defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0})
    for aid, exit_ms, reason, lev, pnl, roe, data in _all(
            conn, "SELECT account_id, exit_time, exit_reason, leverage, pnl, roe, data FROM trades "
                  "ORDER BY exit_time, id"):
        j = _loads(data) or {}
        margin = num(j.get("margin"))
        st = per.setdefault(aid, _trade_row_stats())
        _add_trade(st, int(exit_ms), reason, lev, float(pnl), float(roe), margin)
        strat = split_account(aid)[0]
        if aid in d.accounts and d.accounts[aid]["kind"] == "strategy":
            t = tier.setdefault((strat, str(j.get("tier") or "normal")), _trade_row_stats())
            _add_trade(t, int(exit_ms), reason, lev, float(pnl), float(roe), margin)
            dk = days[kst_day(int(exit_ms))]
            dk["n"] += 1
            dk["pnl"] += float(pnl)
            dk["wins"] += float(pnl) > 0
    d.trade_stats = per
    d.tier_stats = tier
    d.day_trades = dict(days)


# ------------------------------------------------------------------ daily3
def _day_summary(day: str, ts: int, rep: dict, mism: int) -> dict:
    par = rep.get("parity") or {}
    sh = rep.get("shadows") or {}
    tv = sh.get("trade_variants") or {}
    dq = rep.get("data_quality") or {}
    miss = zero = ext = 0
    for sym, v in dq.items():
        if isinstance(v, dict):
            miss += int(v.get("missing") or 0)
            zero += int(v.get("zero_volume") or 0)
            ext += int(v.get("extreme_ranges") or 0)
    fc = rep.get("fill_costs") or {}
    ss = rep.get("stop_slippage") or {}
    ov = ss.get("overall") or {}
    cur = (tv.get("curves") or {})
    variants = {}
    for k, v in tv.items():
        if isinstance(v, dict) and "mean_roe" in v and "trades" in v:
            variants[k] = {"trades": v.get("trades"), "resolved": v.get("resolved"), "mean_roe": num(v.get("mean_roe")),
                           "mean_eq": num(v.get("mean_pnl_equity"))}
    fills = [r for r in (fc.get("rows") or []) if isinstance(r, dict)]
    slips = [num(r.get("slip_median")) for r in fills if r.get("event") == "entry"]
    return {
        "day": day, "ts": ts, "data_day": rep.get("day"), "steps": rep.get("steps"),
        "parity_accounts": par.get("accounts"), "parity_mismatched": par.get("mismatched_accounts"),
        "bars": (par.get("live_bars") or {}).get("bars"), "bars_mismatched": (par.get("live_bars") or {}).get("mismatched"),
        "mismatch_rows": mism,
        "strength_checked": (rep.get("strength") or {}).get("checked"),
        "strength_failed": (rep.get("strength") or {}).get("failed"),
        "limit_signals": sh.get("limit_signals"), "limit_filled": sh.get("limit_filled"),
        "limit_mean_roe": num(sh.get("limit_mean_roe")), "skipped": sh.get("skipped"),
        "stop_variants": sh.get("stop_variants") or {}, "variants": variants,
        "closed": tv.get("closed"), "busts": (cur.get("busts") or []),
        "missing_minutes": miss, "zero_volume": zero, "extreme_ranges": ext,
        "max_abs_funding_pct": num(dq.get("max_abs_funding_pct")),
        "fills_recorded": fc.get("recorded"), "entry_slip_median": mean(slips),
        "assumed_slip": fc.get("assumed"),
        "stop_exits": ov.get("exits"), "stop_measured": ov.get("measured"),
        "stop_real_bps_median": num(ov.get("real_bps_median")), "stop_paper_bps_median": num(ov.get("paper_bps_median")),
    }


SHADOW_KINDS = ("lock15", "lock20", "lock30", "lev10", "lev20", "lev30", "lev40", "lev50", "stopw1.5", "stopw2.5",
                "stopw3", "tp1R", "tp1.5R", "tp2R", "tp3R", "timestop", "ladder_cap2R", "quality", "limit")


def load_daily(conn: Optional[sqlite3.Connection], d: Data) -> None:
    if conn is None:
        return
    mism = {}
    for day, n in _all(conn, "SELECT day, COUNT(*) FROM mismatches GROUP BY day"):
        mism[day] = int(n)
    for day, ts, data in _all(conn, "SELECT day, ts, data FROM reports ORDER BY day"):
        rep = _loads(data)
        if isinstance(rep, dict):
            d.daily.append(_day_summary(day, int(ts), rep, mism.get(day, 0)))
    # shadows: matched comparison with the 'base' shadow (= the actual trade under the rules) per strategy.
    # Metric: P&L on equity (pnl_equity) where the shadow has it (leverage changes the ROE scale, docs/observation-
    # shadows-3.md), else ROE (the limit-order shadow).
    base: dict = {}
    var: dict = defaultdict(dict)
    try:
        cur = conn.execute("SELECT account_id, kind, key, roe, data FROM shadows WHERE roe IS NOT NULL "
                           "AND (filled IS NULL OR filled = 1) AND kind IN (%s)" %
                           ",".join("'%s'" % k for k in ("base",) + SHADOW_KINDS))
        for aid, kind, key, roe, data in cur:
            if not aid or str(aid).startswith("RANDOM_") or d.accounts.get(aid, {}).get("kind", "strategy") != "strategy":
                continue
            ident = (aid, key.rsplit("|", 2)[-2] if key.count("|") >= 3 else key, key.rsplit("|", 1)[-1])
            pe = None
            if data and "pnl_equity" in data:
                pe = num((_loads(data) or {}).get("pnl_equity"))
            rec = (float(roe), pe)
            if kind == "base":
                base[ident] = rec
            else:
                var[kind][ident] = rec
    except sqlite3.Error:
        return
    by: dict = defaultdict(lambda: defaultdict(lambda: {"n": 0, "v": 0.0, "b": 0.0, "unit": "equity"}))
    allv: dict = defaultdict(lambda: {"n": 0, "v": 0.0, "b": 0.0, "unit": "equity"})
    for kind, rows in var.items():
        for ident, (r, pe) in rows.items():
            b = base.get(ident)
            if b is None:
                continue
            if pe is not None and b[1] is not None:
                v, bv, unit = pe, b[1], "equity"
            else:
                v, bv, unit = r, b[0], "roe"
            strat = split_account(ident[0])[0]
            for acc in (by[strat][kind], allv[kind]):
                acc["n"] += 1
                acc["v"] += v
                acc["b"] += bv
                acc["unit"] = unit
    for strat, kinds in by.items():
        d.shadow_by_strategy[strat] = {k: {"n": a["n"], "mean": a["v"] / a["n"], "base": a["b"] / a["n"],
                                           "diff": (a["v"] - a["b"]) / a["n"], "unit": a["unit"]}
                                       for k, a in kinds.items() if a["n"]}
    d.shadow_all = {k: {"n": a["n"], "mean": a["v"] / a["n"], "base": a["b"] / a["n"],
                        "diff": (a["v"] - a["b"]) / a["n"], "unit": a["unit"]} for k, a in allv.items() if a["n"]}


# ------------------------------------------------------------------ checkpoint
def load_checkpoint(conn: Optional[sqlite3.Connection], d: Data) -> None:
    if conn is None:
        return
    r = _one(conn, "SELECT date, ts, snapshot_sha256, data FROM verdicts ORDER BY date DESC LIMIT 1")
    if r:
        v = _loads(r[3])
        d.verdict = {"date": r[0], "ts": int(r[1]), "snapshot_sha256": r[2],
                     "summary": {k: x for k, x in (v or {}).items() if k != "accounts" and not isinstance(x, (dict, list))}
                     if isinstance(v, dict) else {}}
        for aid, status, stage, p, q, data in _all(
                conn, "SELECT account_id, status, stage, p, q, data FROM verdict_accounts WHERE date = ? "
                      "ORDER BY account_id", (r[0],)):
            j = _loads(data) or {}
            d.verdict_rows.append({"account_id": aid, "status": status, "stage": stage, "p": num(p), "q": num(q),
                                   "trades": j.get("trades_total", j.get("trades")), "pnl": num(j.get("pnl")),
                                   "equity": num(j.get("equity")), "reason": j.get("reason"),
                                   "bust": j.get("bust")})
    d.snapshots = [{"date": a, "cp_ts": int(b)} for a, b in _all(conn, "SELECT date, cp_ts FROM snapshots ORDER BY date")]


# ------------------------------------------------------------------ agents3
def load_agents(conn: Optional[sqlite3.Connection], d: Data) -> None:
    if conn is None:
        return
    d.rooms = [{"room_id": a, "kind": b, "strategy": c, "title": t} for a, b, c, t in
               _all(conn, "SELECT room_id, kind, strategy, title FROM rooms ORDER BY room_id")]
    for rid, room, trig, tdata, st, en, status, dec, calls, toks in reversed(_all(
            conn, "SELECT round_id, room_id, trigger, trigger_data, started_ts, ended_ts, status, decision, calls, tokens "
                  "FROM rounds ORDER BY round_id DESC LIMIT ?", (MAX_ROUNDS,))):
        td = _loads(tdata) or {}
        dj = _loads(dec) or {}
        d.rounds.append({"round_id": rid, "room_id": room, "trigger": trig, "kst_day": td.get("kst_day") or kst_day(st),
                         "summary_ko": td.get("summary_ko") or "", "started_ts": st, "ended_ts": en, "status": status,
                         "action": dj.get("action") if isinstance(dj, dict) else None,
                         "decision_summary": (dj.get("summary_ko") if isinstance(dj, dict) else "") or "",
                         "speakers": dj.get("speakers") if isinstance(dj, dict) else None,
                         "calls": calls, "tokens": toks})
    by_round = defaultdict(list)
    role_cnt = defaultdict(lambda: [0, 0])
    for mid, ts, room, rid, meeting, role, name, kind, text in reversed(_all(
            conn, "SELECT id, ts, room_id, round_id, meeting, role, speaker_name, kind, substr(text, 1, ?) "
                  "FROM messages ORDER BY id DESC LIMIT ?", (MSG_TEXT_CAP, MAX_MESSAGES))):
        by_round[rid].append({"id": mid, "ts": ts, "room_id": room, "role": role, "name": name, "kind": kind,
                              "text": text or ""})
        if kind in ("analysis", "challenge", "expert", "revision", "summary", "verdict"):
            role_cnt[role][0] += 1
            role_cnt[role][1] = max(role_cnt[role][1], ts)
    d.messages = dict(by_round)
    d.room_messages = dict(role_cnt)
    d.notes = [{"id": i, "ts": ts, "room_id": room, "strategy": s, "text": t or ""} for i, ts, room, s, t in
               _all(conn, "SELECT id, ts, room_id, strategy, substr(text, 1, ?) FROM notes ORDER BY id", (MSG_TEXT_CAP,))]
    try:
        from .agents import scorecard as SC
        d.hypotheses = SC.hypotheses(conn)
        d.scorecard = SC.scorecard(conn)
    except Exception:                                   # the exporter must survive a changed helper
        d.hypotheses, d.scorecard = [], {}
    d.trials = R.trial_history(conn, kinds=("test", "newlab", "copy_proposal"), limit=2000)[::-1]
    d.trial_counts = R.trial_counts(conn)
    d.proposals = list(reversed(R.list_proposals(conn, limit=500)))
    for r in _all(conn, "SELECT day, symbol, status, direction, confidence, move, correct FROM committee_calls "
                        "ORDER BY day, symbol"):
        d.committee.append({"day": r[0], "symbol": r[1], "status": r[2], "direction": r[3], "confidence": r[4],
                            "move": num(r[5]), "correct": r[6]})
    for day, n, tok in _all(conn, "SELECT day, COUNT(*), SUM(tokens) FROM agent_calls GROUP BY day ORDER BY day"):
        d.calls_by_day[day] = [int(n), int(tok or 0)]
    for role, n, tok in _all(conn, "SELECT role, COUNT(*), SUM(tokens) FROM agent_calls GROUP BY role"):
        d.calls_by_role[role] = [int(n), int(tok or 0)]
    r = _one(conn, "SELECT v FROM cursors WHERE k = 'run:restarted'")
    if r:
        d.restart = _loads(r[0])


# ------------------------------------------------------------------ inbox
def load_inbox(conn: Optional[sqlite3.Connection], d: Data) -> None:
    if conn is None:
        return
    d.owner_messages = [{"id": i, "ts": ts, "room_id": room, "author": a, "text": t or ""} for i, ts, room, a, t in
                        _all(conn, "SELECT id, ts, room_id, author, substr(text, 1, 600) FROM owner_messages "
                                   "ORDER BY id DESC LIMIT 200")][::-1]
    d.approvals = [{"id": i, "ts": ts, "proposal_id": p, "decision": dec, "author": a, "note": n or ""} for
                   i, ts, p, dec, a, n in _all(conn, "SELECT id, ts, proposal_id, decision, author, note FROM approvals "
                                                     "ORDER BY id")]


# ------------------------------------------------------------------ everything
def load_all(paper_db: Optional[str], daily_db: Optional[str], agents_db: Optional[str],
             checkpoint_db: Optional[str], inbox_db: Optional[str]) -> Data:
    d = Data(paths={"paper3": paper_db, "daily3": daily_db, "agents3": agents_db, "checkpoint": checkpoint_db,
                    "inbox": inbox_db})
    conns = {}
    try:
        for name, path in d.paths.items():
            conns[name] = R.open_ro(path)
            d.present[name] = conns[name] is not None
        load_paper(conns["paper3"], d)
        load_daily(conns["daily3"], d)
        load_checkpoint(conns["checkpoint"], d)
        load_agents(conns["agents3"], d)
        load_inbox(conns["inbox"], d)
    finally:
        for c in conns.values():
            if c is not None:
                c.close()
    mt = []
    for p in d.paths.values():
        if p and os.path.exists(p):
            mt.append(int(os.path.getmtime(p) * 1000))
    d.snapshot_ms = d.heartbeat_ms or (max(mt) if mt else 0)
    return d


# ------------------------------------------------------------------ the repo's documents (*.md only)
def read_text(path: str, cap: int = 400_000) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(cap)
    except OSError:
        return None


def sha256_file(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def recorded_hash(path: str) -> Optional[str]:
    """The first 64-hex token of a ``*.sha256`` file next to a document."""
    t = read_text(path, 4096)
    m = re.search(r"\b[0-9a-f]{64}\b", t or "")
    return m.group(0) if m else None


def split_sections(md: str) -> list[tuple[str, int, list[str]]]:
    """[(heading, level, body lines)] of a Markdown text; text before the first heading has heading ''."""
    out: list = [["", 0, []]]
    fence = False
    for ln in md.split("\n"):
        if ln.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.*?)\s*$", ln)
        if m:
            out.append([m.group(2), len(m.group(1)), []])
        else:
            out[-1][2].append(ln)
    return [(h, lv, b) for h, lv, b in out]
