"""좋은 수치 찾기 (5년): which ranges of common market numbers at the entry went with better results, for each of the
36 locked strategies and for all 36 together. Generated offline from the lab's 5-year signal cache and committed as one
JSON (paperbot/dash/data/indranges.json) that dash/more/indranges.py serves. Read-only research: nothing here trades,
touches a database or edits a research / trading file (labtests, the locked indicator code and profiles.py are
imported, never changed).

    python -m paperbot.dash.tools.indranges --signals <signal cache dir> --funding <funding csv dir> \
        [--out paperbot/dash/data/indranges.json] [--work <checkpoint dir>]

``--signals``: sig_<tf>_<COIN>.npz (ts [ns, bar open, UTC], o, h, l, c, v, atr, s__<strategy>; paperbot/agents/
labdata.py builds and checks them). ``--funding``: <SYMBOL>.csv (fundingTime, rate, interval_h) of the same archive.
``--work``: one checkpoint file per timeframe x coin (a killed run resumes).

What (every choice below was fixed before any result was looked at):

1. TRADES. Every signal of the 36 on 15m / 30m / 1h / 4h (config.V3_TRADE_TFS) and the six coins, signal bar from
   2021-08-01 to the cache's end (2026-09-30), with its outcome from paperbot/agents/labtests.signal_outcomes: the
   house exits (next-bar entry + slippage, 2 x ATR14 stop, the stepped profit lock, fees and funding, liquidation),
   one trade per signal, no account and no position limit. Only finished trades. Per trade: net ROE (on margin,
   after costs, at the lab's leverage tier), net R = (ROE / leverage) / (2 x ATR14 / entry price) (the price result
   in units of the first stop distance, so the leverage tier does not move it), and won = net ROE > 0.
2. NUMBERS AT THE ENTRY (tools/indcore.py): RSI(14) and EMA200 distance in ATR read in the trade's direction, ATR%,
   ADX(14), volume / its 20-bar mean, Bollinger width, funding at the entry, the Korea-time session.
3. RANGES. Quintiles with edges fixed per timeframe from all 36 strategies' entries on that timeframe (the same
   ranges for every strategy), three funding ranges, four sessions.
4. CELLS. Per strategy (and all 36 pooled) x number x range: trades, win share, mean net ROE, mean net R, and the
   difference in mean net R between the range and the strategy's other entries with that number known. Tested
   when both sides have >= ``MIN_CELL`` trades: a two-sided test of that difference with standard errors clustered
   by week (Monday 00:00 UTC: entries of one week move together), p from the normal curve.
5. MULTIPLE TESTING. Benjamini-Hochberg at ``FDR`` over EVERY tested cell (all strategies, all numbers, all
   ranges, and the pooled ones), then a 3-window check: 2021-08..2022, 2023-24, 2025-26 must each have
   >= ``MIN_WINDOW`` trades on both sides and a difference of the same sign. Only cells that pass both are marked
   (``ok``: +1 better, -1 worse); every other cell is shown plainly as no difference (차이 없음).
   ADDED AFTER THE FIRST RUN (stated in the JSON and on the page): with about 1.9 million trades a difference of
   0.02 R passed both checks, so a marked cell must also differ by at least ``MIN_EFFECT`` R (5% of a stop distance);
   a cell that passes the tests with a smaller difference carries ``tiny: 1`` and is shown as 차이 없음 too.
6. CAVEAT (written into the JSON and the page): descriptive only. Looking for good ranges after the fact overfits
   even with these guards, the 36 were themselves chosen on 5-year data, and nothing here changes a locked rule.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
from typing import Optional

import numpy as np

from . import indcore as IC

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "indranges.json")

VERSION = 1
LABEL = "설명용, 판정 아님"
TFS = ("15m", "30m", "1h", "4h")                 # config.V3_TRADE_TFS (checked at run time)
K_STOP = 2.0                                     # config.V3_STOP_ATR (checked at run time)
START = "2021-08-01"                             # labtests PERIODS 1 + 2 (the research's 5-year span)
WIN3 = (("2021-22", "2021-08-01", "2023-01-01"), ("2023-24", "2023-01-01", "2025-01-01"),
        ("2025-26", "2025-01-01", "2026-10-01"))
MIN_CELL = 30                                    # trades on each side of a tested cell
MIN_WINDOW = 10                                  # trades on each side in every window of a passing cell
MIN_EFFECT = 0.05                                # |difference in mean net R| of a marked cell (added after run 1)
FDR = 0.05
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
MONDAY0_MS = 4 * DAY_MS                          # 1970-01-05 00:00 UTC, a Monday
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def ms(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def load_funding(folder: Optional[str], symbol: str) -> tuple[np.ndarray, np.ndarray]:
    """(settlement times ms, rates) of one symbol from <folder>/<symbol>.csv, ascending; empty when missing."""
    p = os.path.join(folder, f"{symbol}.csv") if folder else None
    if not p or not os.path.exists(p):
        return np.zeros(0, np.int64), np.zeros(0)
    t, r = [], []
    with open(p) as fh:
        next(fh, None)
        for line in fh:
            parts = line.strip().split(",")
            if len(parts) >= 2:
                try:
                    t.append(int(parts[0]))
                    r.append(float(parts[1]))
                except ValueError:
                    continue
    o = np.argsort(np.asarray(t, np.int64), kind="stable")
    return np.asarray(t, np.int64)[o], np.asarray(r, float)[o]


# ---------------------------------------------------------------- 1-2: trades and their numbers (one tf x coin)
def tf_coin_trades(data, tf: str, coin: str, strategies: list, funding_dir: Optional[str]) -> Optional[dict]:
    """Every finished trade of the 36 on one timeframe and coin with its raw numbers (columns of equal length)."""
    from ...agents.labtests import signal_outcomes
    b = data.bars("main", tf, coin)
    if b is None:
        return None
    with np.load(data.path("main", tf, coin)) as z:
        v = np.asarray(z["v"], float)
    n = len(b["ts"])
    ser = IC.series(b["o"], b["h"], b["l"], b["c"], v, atr=b["atr"])
    ts_ms = np.asarray(b["ts"], np.int64) // 1_000_000
    lo = int(np.searchsorted(ts_ms, ms(START)))
    ft, fr = load_funding(funding_dir, coin + "T")
    cols: dict = {k: [] for k in ("s", "t", "side", "lev", "roe", "r", *IC.QUINT, "funding")}
    sizer = data.sizer(K_STOP)
    for si, s in enumerate(strategies):
        sg = data.signal("main", tf, coin, s)
        if sg is None:
            continue
        out = signal_outcomes(b, sg, lo, n, tf, k_stop=K_STOP, sizer=sizer)
        keep = np.asarray(out["done"], bool)
        idx = out["idx"][keep]
        if not len(idx):
            continue
        side = out["side"][keep].astype(np.int8)
        lev = out["lev"][keep].astype(float)
        roe = out["roe"][keep].astype(float)
        entry = b["o"][idx + 1]
        stop_frac = K_STOP * b["atr"][idx] / entry
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where((lev > 0) & (stop_frac > 0), roe / lev / stop_frac, np.nan)
        close_ms = ts_ms[idx] + TF_MS[tf]
        cols["s"].append(np.full(len(idx), si, np.int16))
        cols["t"].append(close_ms)
        cols["side"].append(side)
        cols["lev"].append(lev)
        cols["roe"].append(roe)
        cols["r"].append(r)
        for k in IC.QUINT:
            cols[k].append(IC.sided(k, ser[k][idx], side))
        cols["funding"].append(IC.funding_at(ft, fr, close_ms))
    if not cols["s"]:
        return None
    return {k: np.concatenate(v) for k, v in cols.items()}


def collect(signals: str, funding_dir: Optional[str], work: Optional[str], tfs=TFS) -> tuple[dict, list]:
    """All trades of the 36 (columns + tf index), from checkpoints where present."""
    from ...agents.labtests import LabData
    from ...agents.roster3 import STRATEGY_KO
    data = LabData(signals)
    have = data.strategies("1h")
    strategies = [s for s in STRATEGY_KO if s in have]
    if len(strategies) != 36:
        raise SystemExit(f"the cache has {len(strategies)} of the 36 strategies")
    parts = []
    for ti, tf in enumerate(tfs):
        for coin in data.coins("main", tf):
            cp = os.path.join(work, f"v{VERSION}_{tf}_{coin}.npz") if work else None
            if cp and os.path.exists(cp):
                with np.load(cp) as z:
                    part = {k: z[k] for k in z.files}
                log("cached", tf, coin, len(part["s"]))
            else:
                t0 = time.time()
                part = tf_coin_trades(data, tf, coin, strategies, funding_dir)
                if part is None:
                    continue
                if cp:
                    os.makedirs(work, exist_ok=True)
                    np.savez(cp + ".tmp.npz", **part)
                    os.replace(cp + ".tmp.npz", cp)
                log("done", tf, coin, len(part["s"]), f"{time.time() - t0:.1f}s")
            part["tf"] = np.full(len(part["s"]), ti, np.int8)
            parts.append(part)
    keys = parts[0].keys()
    return {k: np.concatenate([p[k] for p in parts]) for k in keys}, strategies


# ---------------------------------------------------------------- 3: ranges
def bucketize(tr: dict, tfs=TFS) -> tuple[dict, dict]:
    """({indicator: int8 bucket per trade}, {indicator: {tf: four edges}}). Quintile edges per timeframe over all the
    36's trades on it; funding and session fixed."""
    out, edges = {}, {}
    for k in IC.QUINT:
        b = np.full(len(tr["s"]), -1, np.int8)
        edges[k] = {}
        for ti, tf in enumerate(tfs):
            m = tr["tf"] == ti
            e = IC.edges_of(tr[k][m])
            edges[k][tf] = None if e is None else [IC.r4(x, 6) for x in e]
            b[m] = IC.q_idx(tr[k][m], e)
        out[k] = b
    out["funding"] = IC.funding_idx(tr["funding"])
    out["session"] = IC.session_idx(tr["t"])
    return out, edges


# ---------------------------------------------------------------- 4: one cell
def window_of(t_ms: np.ndarray) -> np.ndarray:
    w = np.full(len(t_ms), -1, np.int8)
    for i, (_name, a, b) in enumerate(WIN3):
        w[(t_ms >= ms(a)) & (t_ms < ms(b))] = i
    return w


def cluster_p(y: np.ndarray, d: np.ndarray, g: np.ndarray, n_g: int) -> Optional[float]:
    """Two-sided p of mean(y | d) - mean(y | not d) with week-clustered standard errors (g: cluster ids 0..n_g-1)."""
    n1, n0 = int(d.sum()), int((~d).sum())
    if n1 < 2 or n0 < 2 or n_g < 2:
        return None
    m1, m0 = float(y[d].mean()), float(y[~d].mean())
    infl = np.where(d, (y - m1) / n1, -(y - m0) / n0)
    S = np.bincount(g, weights=infl, minlength=n_g)
    G = int(np.count_nonzero(np.bincount(g, minlength=n_g)))
    if G < 2:
        return None
    var = G / (G - 1) * float((S ** 2).sum())
    if not var > 0:
        return None
    t = (m1 - m0) / math.sqrt(var)
    return float(math.erfc(abs(t) / math.sqrt(2)))


def cell(y_r, y_roe, won, win3, g, n_g, d) -> dict:
    """One range's numbers (d: in the range, among the trades with this number known)."""
    n1, n0 = int(d.sum()), int((~d).sum())
    c: dict = {"n": n1}
    if n1:
        c.update(wr=IC.r4(won[d].mean(), 4), r=IC.r4(np.nanmean(y_r[d]), 4), roe=IC.r4(np.nanmean(y_roe[d]), 4))
    if n1 and n0:
        c["d"] = IC.r4(float(y_r[d].mean() - y_r[~d].mean()), 4)
    w = []
    for i in range(len(WIN3)):
        m = win3 == i
        a, b = d & m, (~d) & m
        na, nb = int(a.sum()), int(b.sum())
        w.append([na, IC.r4(float(y_r[a].mean() - y_r[b].mean()), 4) if na and nb else None])
    c["w"] = w
    if n1 >= MIN_CELL and n0 >= MIN_CELL:
        c["p"] = cluster_p(y_r, d, g, n_g)
    return c


def scope_cells(tr: dict, bk: dict, sel: np.ndarray) -> dict:
    """{indicator: [cell per range]} for the trades in ``sel`` (bool mask)."""
    y_r_all, roe_all, t_all = tr["r"][sel], tr["roe"][sel], tr["t"][sel]
    ok_r = np.isfinite(y_r_all)
    out = {}
    for k in IC.INDICATORS:
        b = bk[k][sel]
        known = (b >= 0) & ok_r
        y_r, y_roe, t = y_r_all[known], roe_all[known], t_all[known]
        won = (y_roe > 0).astype(float)
        weeks = (t - MONDAY0_MS) // WEEK_MS
        _, g = np.unique(weeks, return_inverse=True)
        n_g = int(g.max()) + 1 if len(g) else 0
        win3 = window_of(t)
        bb = b[known]
        nb = IC.N_Q if k in IC.QUINT else len(IC.FIXED[k])
        out[k] = [cell(y_r, y_roe, won, win3, g, n_g, bb == j) for j in range(nb)]
    return out


def summary(tr: dict, sel: np.ndarray) -> dict:
    r, roe = tr["r"][sel], tr["roe"][sel]
    n = int(sel.sum())
    return {"n": n, "wr": IC.r4((roe > 0).mean(), 4) if n else None, "r": IC.r4(np.nanmean(r), 4) if n else None,
            "roe": IC.r4(np.nanmean(roe), 4) if n else None}


# ---------------------------------------------------------------- 5: Benjamini-Hochberg + the 3 windows
def bh(ps: list) -> list:
    """Benjamini-Hochberg q-values (same order)."""
    m = len(ps)
    if not m:
        return []
    o = sorted(range(m), key=lambda i: ps[i])
    q = [0.0] * m
    run = 1.0
    for rank in range(m, 0, -1):
        i = o[rank - 1]
        run = min(run, ps[i] * m / rank)
        q[i] = run
    return q


def judge(scopes: dict) -> dict:
    """Adds q and ok to every tested cell of every scope (in place); returns the counts."""
    tested = [c for cells in scopes.values() for row in cells.values() for c in row if c.get("p") is not None]
    qs = bh([c["p"] for c in tested])
    passed = better = tiny = 0
    for c, q in zip(tested, qs):
        c["q"] = IC.r4(q, 5)
        c["p"] = IC.r4(c["p"], 6)
        d = c.get("d")
        same = d is not None and d != 0 and all(
            na >= MIN_WINDOW and dw is not None and (dw > 0) == (d > 0) and dw != 0 and
            _rest_n(c, i) >= MIN_WINDOW for i, (na, dw) in enumerate(c["w"]))
        if q <= FDR and same:
            if abs(d) < MIN_EFFECT:
                c["tiny"] = 1
                tiny += 1
                continue
            c["ok"] = 1 if d > 0 else -1
            passed += 1
            better += d > 0
    return {"tests": len(tested), "passed": passed, "better": better, "worse": passed - better, "tiny": tiny}


def _rest_n(c: dict, i: int) -> int:
    return int(c.get("_rest", [MIN_WINDOW] * 3)[i])


def add_rest_counts(tr: dict, bk: dict, sel: np.ndarray, cells: dict) -> None:
    """Each cell's 'other entries' count per window (for the 3-window rule), kept out of the JSON."""
    t_all, ok_r = tr["t"][sel], np.isfinite(tr["r"][sel])
    win_all = window_of(t_all)
    for k, row in cells.items():
        b = bk[k][sel]
        known = (b >= 0) & ok_r
        for j, c in enumerate(row):
            rest = known & (b != j)
            c["_rest"] = [int((rest & (win_all == i)).sum()) for i in range(len(WIN3))]


def build(signals: str, funding_dir: Optional[str], work: Optional[str] = None) -> dict:
    from ...config import V3_STOP_ATR, V3_TRADE_TFS
    if tuple(V3_TRADE_TFS) != TFS:
        raise SystemExit(f"config.V3_TRADE_TFS is {V3_TRADE_TFS}, this generator says {TFS}")
    if abs(float(V3_STOP_ATR) - K_STOP) > 1e-9:
        raise SystemExit(f"config.V3_STOP_ATR is {V3_STOP_ATR}, this generator says {K_STOP}")
    t0 = time.time()
    tr, strategies = collect(signals, funding_dir, work)
    log("trades", len(tr["s"]))
    bk, edges = bucketize(tr)
    scopes: dict = {}
    every = np.ones(len(tr["s"]), bool)
    scopes["__all__"] = scope_cells(tr, bk, every)
    add_rest_counts(tr, bk, every, scopes["__all__"])
    for si, s in enumerate(strategies):
        sel = tr["s"] == si
        scopes[s] = scope_cells(tr, bk, sel)
        add_rest_counts(tr, bk, sel, scopes[s])
    counts = judge(scopes)
    for cells in scopes.values():
        for row in cells.values():
            for c in row:
                c.pop("_rest", None)
    per_tf = {tf: int((tr["tf"] == i).sum()) for i, tf in enumerate(TFS)}
    out_strats = {}
    for si, s in enumerate(strategies):
        sel = tr["s"] == si
        out_strats[s] = {**summary(tr, sel), "passed": sum(1 for row in scopes[s].values() for c in row if c.get("ok")),
                         "cells": scopes[s]}
    manifest = {}
    try:
        with open(os.path.join(signals, "labdata_manifest.json")) as fh:
            m = json.load(fh)
        main = [f for k, f in (m.get("files") or {}).items() if k.startswith("main/")]   # (pre-2021 is not used here)
        manifest = {"main_identical": bool(main) and all(f.get("status") == "identical" for f in main),
                    "main_files": len(main), "checked_utc": m.get("checked_utc")}
    except (OSError, ValueError):
        pass
    try:
        commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        commit = None
    t_last = int(tr["t"].max())
    return {
        "version": VERSION, "label": LABEL, "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "code_commit": commit, "seconds": round(time.time() - t0, 1),
        "source": {"cache": "lab 5-year signal cache (sig_<tf>_<COIN>.npz)", **manifest,
                   "funding": bool(funding_dir and os.path.isdir(funding_dir)),
                   "outcomes": "paperbot/agents/labtests.signal_outcomes (house exits, one trade per signal)"},
        "span": {"from": START, "to": dt.datetime.fromtimestamp(t_last / 1000, dt.timezone.utc).strftime("%Y-%m-%d")},
        "windows": [list(w) for w in WIN3], "tfs": list(TFS), "k_stop": K_STOP,
        "indicators": list(IC.INDICATORS), "quint": list(IC.QUINT), "fixed": {k: list(v) for k, v in IC.FIXED.items()},
        "edges": edges,
        "rules": {"min_cell": MIN_CELL, "min_window": MIN_WINDOW, "fdr": FDR, "min_effect_r": MIN_EFFECT,
                  "min_effect_added_after_first_run": True, "test": "week-clustered, two-sided, net R", **counts},
        "trades": int(len(tr["s"])), "per_tf": per_tf,
        "pooled": {**summary(tr, every), "cells": scopes["__all__"]},
        "strategies": out_strats,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.dash.tools.indranges")
    ap.add_argument("--signals", required=True)
    ap.add_argument("--funding", default=None)
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--work", default=None)
    a = ap.parse_args(argv)
    res = build(a.signals, a.funding, a.work)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, a.out)
    log("wrote", a.out, os.path.getsize(a.out), "bytes;", res["rules"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
