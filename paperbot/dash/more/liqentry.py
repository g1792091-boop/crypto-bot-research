"""강제청산 직후 진입 (ana7a, 분석 › 강제청산 직후 진입): how the paper entries did that came within 5 / 15 / 60 minutes
after a large liquidation burst on the same coin, split by whether we entered the SAME way as the positions that were
liquidated (e.g. long right after longs were liquidated) or the OPPOSITE way (short right after longs were liquidated),
next to every other entry and next to the group's coin flips split the same way. Descriptive, read-only.

    GET /api/v4/liqentry?group=core|ds200|reel      (dash/analysis.an_group; default core = the 36)

Liquidations: liq.db next to paper3.db (paperbot/liqstream.py, the public ``!forceOrder@arr`` stream; Binance sends at
most one order per coin per second, so bursts are undercounted). A burst is agents/entrymoment's definition (the same
as 진입 순간's 강제청산 dimension): a coin's 1-minute liquidated notional (filled qty x average price) at or above the
95th percentile of that coin's non-zero minutes on record, with at least 30 such minutes before anything is called a
burst. Its side is the larger of the two in that minute: SELL forced orders close longs, BUY orders close shorts.

Per window W: an entry is ``after`` a burst when a burst minute ended at or before the entry and began at most W
minutes before it; with several bursts, their sides are summed (a tie: the latest one's side). ``same`` / ``opposite``
as above; ``none``: covered and no burst in the window; not covered (no record W minutes before the entry, or too few
liquidation minutes for that coin yet): counted in ``uncovered`` and left out. The recorder was silent until the
2026-10-06 stream-path fix, so ``first_ts`` (기록 시작) is shown with every answer.

DeepSeek (owners' D10 / D11): counts and shares only, no ROE (the group's AND its coin flips' lines).
"""
from __future__ import annotations

import bisect
import os
import sqlite3
import time
from typing import Optional

from . import a7kit as K

TTL_S = 600
WAIT_S = 3.0
WINDOWS = (5, 15, 60)
MIN_COVERED = 20               # covered entries of the group before the comparison is shown (a filling bar before)
MIN = 60_000
STALE_MS = 2 * 3_600_000


def liq_meta(liq_path: str) -> dict:
    """First and last record time and row count of liq.db (read-only); {} when missing."""
    from ..analysis import _close, ro_connect
    c = ro_connect(liq_path)
    if c is None:
        return {}
    try:
        r = c.execute("SELECT MIN(trade_ts), MAX(trade_ts), COUNT(*) FROM liq").fetchone()
        return {"first_ts": r[0], "last_ts": r[1], "rows": int(r[2] or 0)}
    except sqlite3.Error:
        return {}
    finally:
        _close(c)


def push_before(liq: Optional[dict], sym: str, entry: int, window_min: int) -> str:
    """'up' (shorts were liquidated: their forced buys push the price up) | 'down' (longs were liquidated) | 'none'
    (covered, no burst in the window) | 'uncovered', for an entry at ``entry`` (see the module doc). ``liq`` is
    agents/entrymoment.load_liq's answer (its side +1 = shorts liquidated)."""
    from ...agents.entrymoment import LIQ_MIN_MINUTES
    e = (liq or {}).get(sym)
    if not e or e["start"] is None or e["nonzero"] < LIQ_MIN_MINUTES or e["start"] > entry - window_min * MIN:
        return "uncovered"
    mins = e["minutes"]
    j0 = bisect.bisect_left(mins, entry - window_min * MIN)
    j1 = bisect.bisect_right(mins, entry - MIN)
    push = [e["side"][j] for j in range(j0, j1) if e["burst"][j]]
    if not push:
        return "none"
    s = sum(push)
    if s == 0:
        s = push[-1]
    return "up" if s > 0 else "down"


def split(rows: list, liq: Optional[dict], window_min: int) -> dict:
    """{'same', 'opposite', 'none': [trades], 'uncovered': n} for one window."""
    out: dict = {"same": [], "opposite": [], "none": [], "uncovered": 0}
    for r in rows:
        p = push_before(liq, r["symbol"], r["entry"], window_min)
        if p == "uncovered":
            out["uncovered"] += 1
        elif p == "none":
            out["none"].append(r)
        else:
            liquidated = -1 if p == "up" else 1      # a push up came from shorts being liquidated
            out["same" if r["side"] == liquidated else "opposite"].append(r)
    return out


def view(paper_db: str, now_ms: int, group: str = "core") -> dict:
    from ...agents.entrymoment import LIQ_BURST_PCT, LIQ_MIN_MINUTES, load_liq
    from ..analysis import NO_MONEY_GROUPS, _close, ro_connect
    side_dir = os.path.dirname(os.path.abspath(paper_db))
    liq_path = os.path.join(side_dir, "liq.db")
    out: dict = {"group": group, "label": K.LABEL, "windows": list(WINDOWS), "min_covered": MIN_COVERED,
                 "burst_pct": LIQ_BURST_PCT, "min_minutes": LIQ_MIN_MINUTES,
                 "note_ko": "바이낸스는 코인마다 1초에 한 건만 알려 줘서, 몰릴 때는 실제보다 적게 잡힘"}
    meta = liq_meta(liq_path)
    if not meta:
        out.update(ready=False, why="liq.db 없음 (강제청산 기록기가 아직 돌지 않음)")
        return out
    out.update(ready=bool(meta.get("rows")), first_ts=meta.get("first_ts"), last_ts=meta.get("last_ts"),
               rows=meta.get("rows"), stale=meta.get("last_ts") is None or now_ms - int(meta["last_ts"]) > STALE_MS)
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        start = K.run_start_of(c)
        kinds, tfs = K.scope(group)
        mine = K.closed_trades(c, kinds, tfs, start)
        flips = K.closed_trades(c, ("random",), tfs, start)
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    finally:
        _close(c)
    syms = {r["symbol"] for r in mine + flips} | {"BTCUSDT"}
    liq = load_liq(liq_path, syms, int(meta["first_ts"] or 0), now_ms + MIN) if meta.get("rows") else None
    out["coins"] = {s: {"threshold_usd": K.r4((liq or {}).get(s, {}).get("threshold"), 0),
                        "minutes": (liq or {}).get(s, {}).get("nonzero", 0),
                        "bursts": sum((liq or {}).get(s, {}).get("burst", []) or [])}
                    for s in sorted(syms)}
    per_w = []
    for w in WINDOWS:
        a, f = split(mine, liq, w), split(flips, liq, w)
        per_w.append({"minutes": w,
                      "group": {k: K.cell(a[k]) for k in ("same", "opposite", "none")} | {"uncovered": a["uncovered"]},
                      "coin_flips": {k: K.cell(f[k]) for k in ("same", "opposite", "none")} | {"uncovered": f["uncovered"]}})
    covered = len(mine) - per_w[-1]["group"]["uncovered"]
    out.update({"since": start, "trades": len(mine), "flip_trades": len(flips), "covered": covered, "per_window": per_w})
    if covered < MIN_COVERED:
        out["waiting"] = True
    if group in NO_MONEY_GROUPS:
        out = K.strip(out)
        out["no_money"] = True
    return out


def register(app, ctx) -> dict:
    from ..analysis import Heavy, an_group
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):
        heavy = Heavy()

    @app.get("/api/v4/liqentry")
    def get_liqentry(group: Optional[str] = None):
        """강제청산 직후 진입 for one group (?group=core|ds200|reel); background + cached ``TTL_S``."""
        g = an_group(group)
        return heavy.get(f"liqentry:{g}", TTL_S, lambda: view(ctx.db, int(time.time() * 1000), g), wait_s=WAIT_S)

    return {"routes": ["/api/v4/liqentry"]}
