"""The watch league's checkpoint numbers (research/fullgrid/WATCH_PREREG.md section 3), from the league's snapshot only.

The computation behind research/fullgrid/diag/watch_check.py (the script WATCH_PREREG 5 names; it calls ``check`` here)
and the dashboard's confirmed results after each checkpoint date (dash.py /api/checkpoints): the same numbers wherever
they are read. Only trades closed before 00:00 UTC of the checkpoint date count; each trade's result is taken from the
snapshot's equity line (P&L / wallet before). See watch_check.py's docstring for the rules.
"""

from __future__ import annotations

import numpy as np

from . import summary as SM

ROLES = ("cand", "quarter", "exitonly", "base", "flip")
FDR_Q = 0.10


def bh(pvals: list, q: float = FDR_Q) -> list:
    """Benjamini-Hochberg step-up (research/fullgrid/run.py bh)."""
    ix = [i for i, p in enumerate(pvals) if p is not None]
    m = len(ix)
    out = [False] * len(pvals)
    k = 0
    order = sorted(ix, key=lambda i: pvals[i])
    for r, i in enumerate(order, 1):
        if pvals[i] <= q * r / m:
            k = r
    for i in order[:k]:
        out[i] = True
    return out


def trades_from_equity(equity: list, before_ms: int) -> list:
    """[(exit ms, P&L / wallet before)] from an equity line [[start, 5000], [exit ms, wallet after], ...]."""
    out = []
    for (_t0, w0), (t1, w1) in zip(equity, equity[1:]):
        if int(t1) >= before_ms:
            break
        out.append((int(t1), (float(w1) - float(w0)) / float(w0) if float(w0) > 0 else 0.0))
    return out


def drawdown(equity: list, before_ms: int) -> tuple:
    """(wallet, max closed-trade drawdown) up to before_ms."""
    w = peak = float(equity[0][1])
    dd = 0.0
    for t, v in equity[1:]:
        if int(t) >= before_ms:
            break
        w = float(v)
        peak = max(peak, w)
        dd = max(dd, 1 - w / peak if peak > 0 else 0.0)
    return w, dd


def pool_stats(rets: list) -> dict:
    x = [r for _, r in rets]
    return {"n": len(x), "wins": sum(r > 0 for r in x), "mean": (sum(x) / len(x)) if x else None}


def boot_p(rets: list, name: str, date: str):
    if not rets:
        return None
    return SM.boot_mean_p(np.array([SM.week_of(t) for t, _ in rets]), np.array([r for _, r in rets]), SM.N_BOOT,
                          SM._seed("watch", name, date))


def check(league: dict, book: dict, date: str) -> dict:
    """The checkpoint numbers. ``complete`` is False while the league has not processed past 00:00 UTC of the date (the
    numbers are then not the checkpoint's: the command line refuses them, the dashboard marks them as not final).

    Per strategy (WATCH_PREREG 3.5, reading recorded in DEVIATIONS.md before C1): "the same three conditions" are C2's
    (mean > 0 with p < 0.05, > base and > flip, at least 300 closed cand trades) plus Benjamini-Hochberg 10% over all 16
    strategies; a strategy under 300 trades (or without trades) stays in the family with p = 1 (research/fullgrid/run.py
    does the same under its trade minimum). The strategy section needs both pools' money (a family of 16)."""
    before = SM.day_ms(date)
    accts = league["accounts"]
    which = next((c["id"] for c in SM.CHECKPOINTS if c["date"] == date), None)
    out = {"date": date, "checkpoint": which, "trades_before_utc": f"{date}T00:00:00Z", "pools": {}, "strategies": {},
           "complete": int(league.get("done_ms") or 0) >= before, "done_ms": league.get("done_ms")}
    rets, missing = {}, set()
    for a in accts:
        eq = (book.get(a["id"]) or {}).get("equity")
        if eq is None:
            missing.add(a["kind"])
            continue
        rets[a["id"]] = trades_from_equity(eq, before)
    for pool in ("core", "ds"):
        mine = [a for a in accts if a["kind"] == pool]
        if pool in missing:
            out["pools"][pool] = {"error": "이 스냅샷에 이 묶음의 금액이 없습니다 (CANDLEAGUE_DS_MONEY=1로 다시)"}
            continue
        by = {r: sorted(x for a in mine if a["role"] == r for x in rets[a["id"]]) for r in ROLES}
        st = {r: pool_stats(by[r]) for r in ROLES}
        c, b, f = st["cand"]["mean"], st["base"]["mean"], st["flip"]["mean"]
        p = boot_p(by["cand"], pool, date)
        res = {"roles": st, "weeks": len({SM.week_of(t) for t, _ in by["cand"]})}
        res["c1_stop"] = None if None in (c, b, f) else bool(c < b and c < f)
        res["c2"] = {"p": p, "positive_p": p is not None and c is not None and c > 0 and p < 0.05,
                     "beats_base": None if None in (c, b) else c > b, "beats_flip": None if None in (c, f) else c > f,
                     "trades_300": st["cand"]["n"] >= SM.POOL_MIN_TRADES}
        res["c2"]["pass"] = bool(all(res["c2"][k] for k in ("positive_p", "beats_base", "beats_flip", "trades_300")))
        res["cand_vs_exitonly"] = None if c is None or st["exitonly"]["mean"] is None else c - st["exitonly"]["mean"]
        res["size"] = []
        for a in mine:
            if a["role"] != "cand":
                continue
            q = next((x for x in mine if x["id"] == f"{a['id']}-q"), None)
            w, dd = drawdown(book[a["id"]]["equity"], before)
            row = {"id": a["id"], "cand_wallet": w, "cand_max_dd": dd}
            if q is not None:
                qw, qdd = drawdown(book[q["id"]]["equity"], before)
                row.update(quarter_wallet=qw, quarter_max_dd=qdd)
            res["size"].append(row)
        out["pools"][pool] = res
    if missing:
        out["strategies_error"] = "매매법별 판정은 16개 모두의 금액이 있어야 합니다 (CANDLEAGUE_DS_MONEY=1로 다시)"
        return out
    names = sorted({a["name"] for a in accts if a["role"] == "cand"})
    ps = []
    for name in names:
        mine = [a for a in accts if a["name"] == name]
        by = {r: sorted(x for a in mine if a["role"] == r for x in rets.get(a["id"], [])) for r in ("cand", "base", "flip")}
        st = {r: pool_stats(by[r]) for r in by}
        c, b, f = st["cand"]["mean"], st["base"]["mean"], st["flip"]["mean"]
        enough = st["cand"]["n"] >= SM.POOL_MIN_TRADES
        p = boot_p(by["cand"], name, date) if enough else 1.0
        ps.append(p)
        out["strategies"][name] = {"kind": mine[0]["kind"], "roles": st, "p": p, "trades_300": enough,
                                   "positive_p": bool(enough and c is not None and c > 0 and p < 0.05),
                                   "beats_base": None if None in (c, b) else c > b,
                                   "beats_flip": None if None in (c, f) else c > f, "positive": None if c is None else c > 0}
    for name, ok in zip(names, bh(ps)):
        s = out["strategies"][name]
        s["bh_10"] = bool(ok)
        s["pass"] = bool(ok and s["trades_300"] and s["positive_p"] and s["beats_base"] and s["beats_flip"])
    return out
