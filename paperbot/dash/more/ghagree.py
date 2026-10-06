"""GH Coin과 같은 방향일 때 (ana7a, 분석 › GH Coin과 같은 방향): our entries where the GH Coin recorder's latest call on
that coin pointed the same way, the opposite way, or where there was no call, with the group's coin flips split the
same way as the baseline. Descriptive, read-only; the page shows this tab only while the GH Coin recorder runs
(features.ghcoin, like the GH Coin tab).

    GET /api/v4/ghagree?group=core|ds200|reel       (dash/analysis.an_group; default core = the 36)

GH Coin calls: ``ghcoin/calls.jsonl`` next to paper3.db (ghcoin/recorder.mjs; read with paperbot/ghcoin.read_events).
A call is an ``open`` event that is not a mirror: coin, side (+1 long / -1 short), decision time ``t`` (the close of
the 5-minute bar it was made on). For an entry at E on a coin: the latest call on that coin with t < E and
E - t <= 24 hours (a call's own life: it expires after 24 hours) -> ``same`` (its side is ours), ``opposite``, or
``none``. Strictly before: an entry's time is its bar's open (engine entry_time = bar.open_time), and a call made on
the 5-minute bar that closed at that same moment is written by the recorder after it, so it was not out yet.
``open_at_entry`` counts the calls that were still running at E (not yet hit their stop / target / flip).
Entries before the recorder's first event are ``before`` (left out). Per bucket: trades, win share (net P&L > 0),
mean net ROE.

DeepSeek (owners' D10 / D11): counts and shares only, no ROE (the group's and its coin flips' lines).
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
LOOKBACK_MS = 24 * 3_600_000          # ghcoin/recorder.mjs EXPIRE_MS
MIN_WITH_CALL = 20                    # entries of the group with a call (same + opposite) before the comparison


def calls(directory: str) -> dict:
    """{"by_sym": {sym: ([t], [side], [end or None])}, "first_ts", "last_ts", "n"} of GH Coin's own calls."""
    from ...ghcoin import read_events
    ev = read_events(os.path.join(directory, "calls.jsonl"))
    opened, ended = {}, {}
    ts_all = []
    for e in ev:
        t = e.get("t")
        if isinstance(t, (int, float)):
            ts_all.append(int(t))
        if e.get("ev") == "open" and not e.get("mirror") and e.get("sym") and e.get("side") in (1, -1):
            opened[e.get("id")] = e
        elif e.get("ev") == "close" and not e.get("mirror"):
            ended[e.get("id")] = e.get("end")
    by: dict = {}
    for cid, e in sorted(opened.items(), key=lambda x: int(x[1]["t"])):
        ts, sides, ends = by.setdefault(str(e["sym"]), ([], [], []))
        end = ended.get(cid)
        ts.append(int(e["t"]))
        sides.append(int(e["side"]))
        ends.append(int(end) if isinstance(end, (int, float)) else None)
    return {"by_sym": by, "first_ts": min(ts_all) if ts_all else None, "last_ts": max(ts_all) if ts_all else None,
            "n": len(opened)}


def latest(gh: dict, sym: str, entry: int) -> tuple[str, bool]:
    """('same' | 'opposite' | 'none' relative to side +1, still open at the entry) — side applied by the caller."""
    x = gh["by_sym"].get(sym)
    if not x:
        return "none", False
    j = bisect.bisect_left(x[0], entry) - 1            # t < entry (a call at the entry's own bar close came after it)
    if j < 0 or entry - x[0][j] > LOOKBACK_MS:
        return "none", False
    end = x[2][j]
    return ("long" if x[1][j] > 0 else "short"), (end is None or end > entry)


def split(rows: list, gh: dict) -> dict:
    out: dict = {"same": [], "opposite": [], "none": [], "before": 0, "open_at_entry": 0}
    first = gh.get("first_ts")
    for r in rows:
        if first is None or r["entry"] < first:
            out["before"] += 1
            continue
        d, still = latest(gh, r["symbol"], r["entry"])
        if d == "none":
            out["none"].append(r)
            continue
        out["same" if (d == "long") == (r["side"] > 0) else "opposite"].append(r)
        out["open_at_entry"] += still
    return out


def view(paper_db: str, now_ms: int, group: str = "core") -> dict:
    from ..analysis import NO_MONEY_GROUPS, _close, ro_connect
    gdir = os.path.join(os.path.dirname(os.path.abspath(paper_db)), "ghcoin")
    out: dict = {"group": group, "label": K.LABEL, "lookback_h": LOOKBACK_MS // 3_600_000, "min_with_call": MIN_WITH_CALL}
    gh = calls(gdir)
    out.update(ready=gh["n"] > 0, calls=gh["n"], first_ts=gh["first_ts"], last_ts=gh["last_ts"])
    if not gh["n"]:
        out["why"] = "GH Coin 타점 기록이 아직 없습니다"
        return out
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
    a, f = split(mine, gh), split(flips, gh)
    with_call = len(a["same"]) + len(a["opposite"])
    out.update({"since": start, "trades": len(mine), "flip_trades": len(flips), "with_call": with_call,
                "mine": {k: K.cell(a[k]) for k in ("same", "opposite", "none")} | {"before": a["before"],
                                                                                   "open_at_entry": a["open_at_entry"]},
                "coin_flips": {k: K.cell(f[k]) for k in ("same", "opposite", "none")} | {"before": f["before"],
                                                                                         "open_at_entry": f["open_at_entry"]},
                "per_coin": {s: {"calls": len(v[0])} for s, v in sorted(gh["by_sym"].items())}})
    if with_call < MIN_WITH_CALL:
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

    @app.get("/api/v4/ghagree")
    def get_ghagree(group: Optional[str] = None):
        """GH Coin과 같은 방향일 때 for one group (?group=core|ds200|reel); background + cached ``TTL_S``."""
        g = an_group(group)
        return heavy.get(f"ghagree:{g}", TTL_S, lambda: view(ctx.db, int(time.time() * 1000), g), wait_s=WAIT_S)

    return {"routes": ["/api/v4/ghagree"]}
