"""손실 거래 <-> 회의 (review addition 9): which loss meetings looked at which losing trades, both ways. Read-only over
agents3.db (the agents tick writes it) and paper3.db.

    GET /api/v4/losslinks?trades=12,13   {"trades": {"12": [meeting, ...]}}       (a page of trade rows, a replay)
    GET /api/v4/losslinks?rounds=5,6     {"rounds": {"5": {"stored", "trades": [trade, ...]}}}   (a decision card)

The loss meetings store the ids of the trades that opened them in ``rounds.trigger_data.trade_ids``
(agents/triggers.py: ``loss_cluster`` of a strategy room and of the lab, ``group_loss`` of the DeepSeek / reel group
rooms), together with the oldest and newest exit time of those trades. A trade id only counts as the same trade when
the trade exists in paper3.db, closed before the meeting started and inside that stored exit window (after a restored
or new paper3.db the ids restart, and a new trade with an old id is never linked to an old meeting); a round without
the window keeps the trades that closed in the 7 days before it.

meeting = {round_id, room_id, room_title, trigger, trigger_ko, started_ts, status, summary_ko}
trade   = {id, account_id, symbol, side, exit_time, exit_reason, count_only, pnl, roe} (DeepSeek and the coin flips are
          counted only: no pnl / roe, owners' D10 / D11)

The round index (trade id -> rounds) is rebuilt at most every ``TTL_S``; the trade checks are per request.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional

from fastapi import HTTPException

TTL_S = 60.0
LOSS_TRIGGERS = ("loss_cluster", "group_loss")
WINDOW_MS = 7 * 86_400_000          # a round without a stored exit window: trades closed in the 7 days before it
MAX_TRADES = 200
MAX_ROUNDS = 50
COUNT_ONLY_KINDS = ("ds200", "random")


def _ids(text: Optional[str], cap: int) -> list[int]:
    out: list[int] = []
    for part in str(text or "").split(","):
        part = part.strip()
        if part.isdigit() and 0 < int(part) < 2 ** 63 and int(part) not in out:
            out.append(int(part))
        if len(out) >= cap:
            break
    return out


def _int(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def load_rounds(agents_ro: Optional[sqlite3.Connection]) -> Optional[dict]:
    """{round_id: {room_id, trigger, started_ts, status, summary_ko, trade_ids, lo, hi}} of the loss meetings that
    stored trade ids; None when agents3.db could not be read (the caller keeps what it had and asks again)."""
    if agents_ro is None:
        return {}
    out: dict = {}
    try:
        rows = agents_ro.execute("SELECT round_id, room_id, trigger, trigger_data, started_ts, status, decision FROM rounds "
                                 f"WHERE trigger IN ({','.join('?' * len(LOSS_TRIGGERS))})", LOSS_TRIGGERS).fetchall()
    except sqlite3.Error:
        return None
    for r in rows:
        try:
            td = json.loads(r["trigger_data"] or "{}") or {}
        except (TypeError, ValueError):
            td = {}
        ids = [i for i in (_int(x) for x in (td.get("trade_ids") or []) if not isinstance(x, bool)) if i]
        if not ids:
            continue
        try:
            dec = json.loads(r["decision"] or "null")
        except (TypeError, ValueError):
            dec = None
        summary = (dec.get("summary_ko") if isinstance(dec, dict) else None) or td.get("summary_ko") or ""
        out[int(r["round_id"])] = {"room_id": r["room_id"], "trigger": r["trigger"], "started_ts": int(r["started_ts"]),
                                   "status": r["status"], "summary_ko": str(summary)[:200], "trade_ids": ids,
                                   "lo": _int(td.get("oldest_exit")), "hi": _int(td.get("newest_exit"))}
    return out


def index(rounds: dict) -> dict:
    """{trade id: [round ids]} (newest round first)."""
    out: dict = {}
    for rid in sorted(rounds, reverse=True):
        for t in rounds[rid]["trade_ids"]:
            out.setdefault(t, []).append(rid)
    return out


def same_trade(rnd: dict, exit_time: Optional[int]) -> bool:
    """Is a paper3 trade with this exit time the trade the meeting stored (not a later trade with a reused id)?"""
    if exit_time is None or exit_time > rnd["started_ts"]:
        return False
    if rnd["lo"] is not None and rnd["hi"] is not None:
        return rnd["lo"] <= exit_time <= rnd["hi"]
    return rnd["started_ts"] - exit_time <= WINDOW_MS


def _trades(paper_ro: sqlite3.Connection, ids: list[int]) -> dict:
    if not ids:
        return {}
    q = ("SELECT t.id, t.account_id, t.symbol, t.exit_time, t.exit_reason, t.pnl, t.roe, t.data, a.kind FROM trades t "
         "LEFT JOIN accounts a ON a.account_id = t.account_id WHERE t.id IN (%s)" % ",".join("?" * len(ids)))
    out = {}
    for r in paper_ro.execute(q, ids):
        try:
            side = int((json.loads(r["data"]) or {}).get("side") or 0)
        except (TypeError, ValueError):
            side = 0
        co = r["kind"] in COUNT_ONLY_KINDS
        t = {"id": int(r["id"]), "account_id": r["account_id"], "symbol": r["symbol"], "side": side,
             "exit_time": int(r["exit_time"]), "exit_reason": r["exit_reason"], "count_only": co}
        if not co:
            t.update(pnl=float(r["pnl"]), roe=float(r["roe"]))
        out[int(r["id"])] = t
    return out


def meeting(rid: int, rnd: dict, titles: dict, trigger_ko: dict) -> dict:
    return {"round_id": rid, "room_id": rnd["room_id"], "room_title": titles.get(rnd["room_id"], rnd["room_id"]),
            "trigger": rnd["trigger"], "trigger_ko": trigger_ko.get(rnd["trigger"], rnd["trigger"]),
            "started_ts": rnd["started_ts"], "status": rnd["status"], "summary_ko": rnd["summary_ko"]}


def for_trades(rounds: dict, idx: dict, paper_ro: sqlite3.Connection, ids: list[int], titles: dict, trigger_ko: dict) -> dict:
    want = [i for i in ids if i in idx]
    rows = _trades(paper_ro, want)
    out: dict = {str(i): [] for i in ids}
    for i in want:
        t = rows.get(i)
        if t is None:
            continue
        out[str(i)] = [meeting(rid, rounds[rid], titles, trigger_ko) for rid in idx[i] if same_trade(rounds[rid], t["exit_time"])]
    return out


def for_rounds(rounds: dict, paper_ro: sqlite3.Connection, rids: list[int], titles: dict, trigger_ko: dict) -> dict:
    out: dict = {}
    need = sorted({t for r in rids if r in rounds for t in rounds[r]["trade_ids"]})
    rows = _trades(paper_ro, need)
    for rid in rids:
        rnd = rounds.get(rid)
        if rnd is None:
            out[str(rid)] = {"stored": 0, "trades": []}
            continue
        got = [rows[t] for t in rnd["trade_ids"] if t in rows and same_trade(rnd, rows[t]["exit_time"])]
        out[str(rid)] = {"stored": len(rnd["trade_ids"]), "trades": got, "meeting": meeting(rid, rnd, titles, trigger_ko)}
    return out


def register(app, ctx) -> dict:
    from ...agents import rooms_db as R
    try:
        from ...agents.rooms import TRIGGER_KO
    except Exception:  # noqa: BLE001  (the rooms engine is optional for the dashboard)
        TRIGGER_KO = {"loss_cluster": "손실 묶음 복기", "group_loss": "그룹 손실 묶음 복기"}
    titles = {k: v.get("title") or k for k, v in (getattr(ctx.rooms, "specs", {}) or {}).items()}
    st: dict = {"at": 0.0, "rounds": {}, "idx": {}}
    lock = threading.Lock()

    def current() -> tuple[dict, dict]:
        with lock:
            if time.time() - st["at"] >= TTL_S:
                a = R.open_ro(getattr(ctx, "agents_db", None))
                try:
                    # a file that cannot be opened right now (a restore's stale -wal, a moment between files) after one
                    # that could: the last index stays (each link is still checked against the trade's exit time)
                    rounds = None if a is None and st["rounds"] else load_rounds(a)
                finally:
                    if a is not None:
                        a.close()
                if rounds is not None:          # a read error keeps the last index (never an empty one for a minute)
                    st.update(at=time.time(), rounds=rounds, idx=index(rounds))
            return st["rounds"], st["idx"]

    @app.get("/api/v4/losslinks")
    def get_losslinks(trades: str = "", rounds: str = ""):
        """Loss meetings of trade rows (?trades=) and the trades of loss meetings (?rounds=); read-only."""
        tids, rids = _ids(trades, MAX_TRADES), _ids(rounds, MAX_ROUNDS)
        rnds, idx = current()
        out: dict = {"ready": getattr(ctx, "agents_db", None) is not None}
        if not tids and not rids:
            return out
        from ..app import _ro_uri
        try:
            p = sqlite3.connect(_ro_uri(ctx.db), uri=True, timeout=5)
            p.row_factory = sqlite3.Row
        except sqlite3.Error:
            raise HTTPException(503, "paper3.db를 읽지 못했습니다")
        try:
            if tids:
                out["trades"] = for_trades(rnds, idx, p, tids, titles, TRIGGER_KO)
            if rids:
                out["rounds"] = for_rounds(rnds, p, rids, titles, TRIGGER_KO)
        except sqlite3.Error:
            raise HTTPException(503, "paper3.db를 읽지 못했습니다")
        finally:
            p.close()
        return out

    return {"routes": ["/api/v4/losslinks"], "state": st}
