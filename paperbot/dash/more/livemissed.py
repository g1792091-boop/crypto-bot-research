"""실거래 › 못 탄 신호 (#/livebots/missed, owners 10/19 "못 탄 신호들은 어땠나"): what the signals the paper bot could not
take (one position at a time, or another signal of the same minute went in) would have done, next to the trades it did
take. Read-only and view only: the one-position rule stays as it is.

    GET /api/v4/livebots/missed?span=7d|all     the two blocks (실제로 탄 거래 vs 못 탄 신호(가상)) and the rows, newest first
                                                (at most ROWS_KEEP), 5 s cache

Where it reads (the 실거래 tabs' own paths, dash/more/livebots.py ``paths`` / ``paths_more``):
    PAPERBOT_LIVE_CHECK_DB   /var/lib/paperbot/livecheck.db   table ``missed`` and ``missed_meta``, written by the 1-minute
                             watcher's pass (paperbot/livemissed.py ``missed_pass``: each skipped signal simulated on the
                             paper bot's own engine with the rule bot's 1m bars, paperbot/livesim.py)
    PAPERBOT_LIVE_PAPER_DB   /var/lib/paperbot/combo/live-ac.db  the paper account's closed trades and open position (the
                             trades it really took over the same span; the result of the trade that had the place, fresh)
Both ``mode=ro`` + ``query_only``, one snapshot each.

States (CONTRACT §1.6): the watcher's file or its table not there yet -> ``missing`` (수집 전: "1분 감시가 아직 기록 전"),
unreadable -> ``error`` (못 읽음 + why), never an empty list that reads as "nothing missed". The paper database unreadable
only blanks the left block (its own state). A pass that stopped: ``pass.stale``.
Numbers: ratios (0.112 = +11.2 % net ROE), times UTC ms. Funding is not in the virtual results (livesim FUNDING_NOTE_KO).
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Optional

from . import livebots as L

ROWS_KEEP = 300                          # rows sent (the page shows 10 a page)
PASS_STALE_MS = 10 * 60_000              # the watcher runs every minute
SPANS = (("7d", "최근 7일"), ("all", "기록 전체"))
MISSING_KO = "1분 감시가 아직 기록 전이에요 (못 탄 신호는 1분 감시가 매번 계산해요)"
NO_TABLE_KO = "점검 파일은 있지만 못 탄 신호 표가 아직 없어요 (1분 감시가 아직 기록 전)"
SMALL_KO = "20번 미만은 대부분 운이에요"


def _LM():
    from ... import livemissed as LM
    return LM


def read_missed(path: str, now: int, span: str) -> dict:
    """livecheck.db ``missed`` (rows of the span, ``livemissed.row_out`` shape, newest first) and the last pass."""
    LM = _LM()
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, MISSING_KO)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "missed" not in tables:
            return L._missing(path, NO_TABLE_KO)
        meta = {k: (L._i(ts), L._j(d)) for k, ts, d in conn.execute("SELECT k, ts, data FROM missed_meta")} \
            if "missed_meta" in tables else {}
        first = (meta.get("first") or (None, {}))[1].get("since")
        since = LM.window_start(now) if span == "7d" else (L._i(first) if first is not None else 0)
        rows = LM.read_rows(conn, since)
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    last_ts, last = meta.get("pass") or (None, {})
    return {"state": "ok", "path": path, "since_ms": since, "rows": rows,
            "pass": {"last_ms": last_ts, "stale": last_ts is None or now - last_ts > PASS_STALE_MS, "state": last.get("state"),
                     "left": L._i(last.get("left")) or 0, "capped": bool(last.get("capped")), "error": last.get("error"),
                     "rig_error": last.get("rig_error"), "config": last.get("config"), "funding": last.get("funding") or "excluded",
                     "first_ms": L._i(first)}}


def _fresh_taken(t: Optional[dict], by_id: dict, pos: Optional[dict]) -> Optional[dict]:
    """The trade that had the place, its result from the paper database now (closed since the watcher stored it, or its
    open position's net ROE at the last mark)."""
    if not t:
        return t
    out = dict(t)
    tr = by_id.get(L._i(t.get("id"))) if t.get("id") is not None else None
    if tr is None and t.get("state") == "open":
        tr = next((x for x in by_id.values() if x.get("entry_time") == L._i(t.get("entry_time")) and x.get("symbol") == t.get("symbol")), None)
    if tr is not None:
        out.update(id=tr["id"], state="closed", roe=tr["roe"], pnl=tr["pnl"], reason=tr["exit_reason"],
                   reason_ko=_LM().KO_EXIT.get(tr["exit_reason"], tr["exit_reason"]), exit_time=tr["exit_time"])
    elif t.get("state") == "open" and pos and pos.get("entry_time") == L._i(t.get("entry_time")) and pos.get("symbol") == t.get("symbol"):
        out["roe"] = pos.get("last_mark_roe_net")
    return out


def build(p: dict, more: dict, now: int, span: str = "7d") -> dict:
    """GET /api/v4/livebots/missed (module docstring)."""
    LM = _LM()
    from ...livesim import FUNDING_NOTE_KO
    span = span if span in dict(SPANS) else "7d"
    base = {"now_ms": now, "span": span, "spans": [{"id": k, "ko": ko} for k, ko in SPANS], "note_ko": LM.NOTE_KO,
            "funding_ko": FUNDING_NOTE_KO, "small_ko": SMALL_KO, "small_n": LM.SMALL}
    m = read_missed(more["check_db"], now, span)
    if m.get("state") != "ok":
        return {**base, **{k: m.get(k) for k in ("state", "reason_ko", "reason", "path")}, "rows": [], "n_rows": 0, "summary": None,
                "paper": None, "pass": None}
    paper = L.read_paper(p["paper"], [L.ACCOUNT], now)
    a = (paper.get("accounts") or {}).get(L.ACCOUNT) if paper.get("state") == "ok" else None
    trades = (a or {}).get("trades") or []
    pos = (a or {}).get("position")
    by_id = {t["id"]: t for t in trades}
    rows = m["rows"]
    for r in rows:
        r["taken"] = _fresh_taken(r.get("taken"), by_id, pos)
    s = LM.summary_of(rows, trades, (pos or {}).get("entry_time"), m["since_ms"])
    if a is None:
        s["taken"] = None
    paper_state = {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")} if paper.get("state") != "ok" else \
        ({"state": "ok"} if a is not None else {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요"})
    return {**base, "state": "ok", "path": m["path"], "since_ms": m["since_ms"], "pass": m["pass"], "summary": s, "paper": paper_state,
            "rows": rows[:ROWS_KEEP], "n_rows": len(rows),
            "funding_included": m["pass"].get("funding") == "included"}


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/missed")
    def get_livebots_missed(span: str = "7d"):
        """실거래 › 못 탄 신호: the skipped signals' virtual results next to the trades really taken (read-only, 5 s cache)."""
        p, more = L.paths(), L.paths_more()
        sp = span if span in dict(SPANS) else "7d"
        key = "missed:" + json.dumps([p, more, sp], sort_keys=True)
        return L._cached(key, lambda: json_finite(build(p, more, int(time.time() * 1000), sp)))

    return {"routes": ["/api/v4/livebots/missed"], "paths": L.paths}
