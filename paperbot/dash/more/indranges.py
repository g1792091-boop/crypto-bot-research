"""좋은 수치 찾기 (ana7a, 분석 › 좋은 수치 찾기): which ranges of common market numbers at the entry went with better
results for the 36 (descriptive; nothing here changes a locked rule).

    GET /api/v4/indranges                    the 5-year result (committed paperbot/dash/data/indranges.json, written
                                             offline by tools/indranges.py): methods, ranges (edges per timeframe),
                                             all 36 pooled per number and range, per strategy its totals and number of
                                             marked cells, and the list of every marked cell (BH + 3 windows + 0.05 R)
    GET /api/v4/indranges/strategy?name=S    one strategy's cells (every number and range)
    GET /api/v4/indranges/paper              the same numbers at the paper run's own entries of the 36 (closed trades
                                             since the run start), bucketed with the 5-year edges of the trade's
                                             timeframe: per number and range trades, win share, mean net ROE, mean net R
                                             (R = |entry - first stop|). ``waiting`` below ``MIN_PAPER`` trades (a
                                             filling bar on the page). ``by_strategy``: each strategy's count, and
                                             its own ranges from ``MIN_PAPER_STRATEGY`` trades on (매매법별 card).
                                             Background + cached (dash/analysis.Heavy).

Paper candles: the market recorder's market.db (5-minute bars next to paper3.db, read-only) grouped into the trade's
timeframe (a bin counts only when every 5-minute bar is there); a coin and timeframe it does not cover are asked from
``frames`` (the dashboard's closed-bar fetcher, the same as /api/strategy uses). Funding at the entry: market.db
settlements, else the flow.db premium estimate (agents/entrymoment.load_funding / funding_at). A trade whose signal bar
is not in the bars counts in ``coverage.no_bars``, never a guessed number.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional

import numpy as np

from ..tools import indcore as IC
from . import a7kit as K

DATA_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "indranges.json")
TTL_S = 900
WAIT_S = 3.0
MIN_PAPER = 100                # closed trades of the 36 with their numbers known before the paper table is shown
MIN_BUCKET = 20                # a paper range under this many trades carries small: true
MIN_PAPER_STRATEGY = 30        # one strategy's paper entries with their numbers before its own ranges are sent
FIVE_MIN = 300_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
MAX_FRAME_BARS = 6000

_file_lock = threading.Lock()
_file: dict = {}


def load_five(path: str = DATA_JSON) -> Optional[dict]:
    """The committed 5-year JSON (re-read when the file changes); None when it is not there."""
    import json
    try:
        st = os.stat(path)
    except OSError:
        return None
    with _file_lock:
        hit = _file.get(path)
        if hit and hit[0] == (st.st_mtime_ns, st.st_size):
            return hit[1]
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        _file[path] = ((st.st_mtime_ns, st.st_size), d)
        return d


def marked(five: dict) -> list:
    """Every marked cell (``ok``), strongest difference first: {s ('' = all 36), k, j, n, wr, r, roe, d, q, w, ok}."""
    out = []
    scopes = [("", (five.get("pooled") or {}).get("cells") or {})]
    scopes += [(s, v.get("cells") or {}) for s, v in (five.get("strategies") or {}).items()]
    for s, cells in scopes:
        for k, row in cells.items():
            for j, c in enumerate(row):
                if c.get("ok"):
                    out.append({"s": s, "k": k, "j": j, **{x: c.get(x) for x in ("n", "wr", "r", "roe", "d", "q", "w", "ok")}})
    out.sort(key=lambda x: (-abs(x.get("d") or 0), x["s"], x["k"], x["j"]))
    return out


def five_view(path: str = DATA_JSON) -> dict:
    d = load_five(path)
    if d is None:
        return {"ready": False, "why": "5년 결과 파일이 없습니다 (paperbot/dash/data/indranges.json)"}
    keep = ("version", "label", "built_utc", "code_commit", "source", "span", "windows", "tfs", "k_stop", "indicators",
            "quint", "fixed", "edges", "rules", "trades", "per_tf", "pooled")
    out = {k: d.get(k) for k in keep}
    out["ready"] = True
    out["strategies"] = {s: {k: v.get(k) for k in ("n", "wr", "r", "roe", "passed")}
                         for s, v in (d.get("strategies") or {}).items()}
    out["marked"] = marked(d)
    out["min_paper"] = MIN_PAPER
    return out


def strategy_view(name: str, path: str = DATA_JSON) -> dict:
    d = load_five(path)
    if d is None:
        return {"ready": False, "why": "5년 결과 파일이 없습니다"}
    v = (d.get("strategies") or {}).get(name)
    if v is None:
        from fastapi import HTTPException
        raise HTTPException(404, "그런 매매법이 5년 결과에 없습니다")
    return {"ready": True, "name": name, **v}


# ---------------------------------------------------------------- paper-forward
def _market_bars(market: Optional[sqlite3.Connection], sym: str, tf: str, lo: int, hi: int) -> Optional[dict]:
    """market.db 5-minute bars in [lo, hi) grouped into ``tf`` bins (UTC-aligned, complete bins only)."""
    if market is None:
        return None
    try:
        rows = market.execute("SELECT open_time, open, high, low, close, volume FROM kline5m WHERE symbol = ? AND "
                              "open_time >= ? AND open_time < ? ORDER BY open_time", (sym, int(lo), int(hi))).fetchall()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    t = a[:, 0].astype(np.int64)
    step = TF_MS[tf]
    g = t // step
    starts = np.r_[0, np.nonzero(np.diff(g))[0] + 1]
    ends = np.r_[starts[1:], len(t)]
    full = (ends - starts) == step // FIVE_MIN
    if not full.any():
        return None
    s0, e0 = starts[full], ends[full]
    return {"t": g[s0] * step, "o": a[s0, 1], "h": np.maximum.reduceat(a[:, 2], starts)[full],
            "l": np.minimum.reduceat(a[:, 3], starts)[full], "c": a[e0 - 1, 4],
            "v": np.add.reduceat(a[:, 5], starts)[full]}


def _frame_bars(frames, sym: str, tf: str, lo: int, now_ms: int) -> Optional[dict]:
    if frames is None:
        return None
    end = max(int(now_ms), int(time.time() * 1000))       # the fetcher answers the latest bars
    n = int(min(MAX_FRAME_BARS, (end - lo) // TF_MS[tf] + 5))
    try:
        df = frames(sym, tf, max(n, 50))
    except Exception:  # noqa: BLE001  (no network: the trades of that coin read as no_bars)
        return None
    if df is None or not len(df):
        return None
    raw = np.asarray(df["ts"].values)
    t = raw.astype(np.int64) if np.issubdtype(raw.dtype, np.number) else raw.astype("datetime64[ms]").astype(np.int64)
    return {"t": t, "o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float), "l": df["low"].to_numpy(float),
            "c": df["close"].to_numpy(float), "v": df["volume"].to_numpy(float)}


def numbers_at(rows: list, bars: dict, tf: str, five: dict) -> list:
    """{indicator: bucket} per trade (same order as ``rows``) from ``bars`` (one coin, one timeframe); a trade whose
    signal bar is missing gets None."""
    ser = IC.series(bars["o"], bars["h"], bars["l"], bars["c"], bars["v"])
    edges = five.get("edges") or {}
    out = []
    for r in rows:
        open_ms = int(r["signal_ts"]) + 1 - TF_MS[tf]
        i = int(np.searchsorted(bars["t"], open_ms))
        if i >= len(bars["t"]) or int(bars["t"][i]) != open_ms:
            out.append(None)
            continue
        b = {}
        for k in IC.QUINT:
            x = IC.sided(k, np.array([ser[k][i]]), np.array([r["side"]]))
            b[k] = int(IC.q_idx(x, (edges.get(k) or {}).get(tf))[0])
        out.append(b)
    return out


def paper_cells(known: list) -> dict:
    """{indicator: [cell per range]} of (trade, buckets, net R) triples: trades, win share, mean net ROE, mean net R."""
    cells: dict = {}
    for k in IC.INDICATORS:
        nb = IC.N_Q if k in IC.QUINT else len(IC.FIXED[k])
        row = []
        for j in range(nb):
            sel = [(r, rn) for r, b, rn in known if b.get(k) == j]
            c0 = K.cell([r for r, _ in sel], MIN_BUCKET)
            rr = [rn for _, rn in sel if rn is not None]
            c0["mean_r"] = K.r4(sum(rr) / len(rr), 4) if rr else None
            row.append(c0)
        cells[k] = row
    return cells


def paper_view(paper_db: str, now_ms: int, frames=None, five_path: str = DATA_JSON) -> dict:
    from ...agents import entrymoment as EM
    from ..analysis import CORE_FLIP_TFS, _close, ro_connect
    five = load_five(five_path)
    out: dict = {"label": K.LABEL, "min_trades": MIN_PAPER, "min_bucket": MIN_BUCKET}
    if five is None:
        out["error"] = "5년 결과 파일이 없어 구간을 정할 수 없습니다"
        return out
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        start = K.run_start_of(c)
        rows = K.closed_trades(c, ("strategy",), CORE_FLIP_TFS, start)
    except sqlite3.Error as exc:
        return {**out, "error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    finally:
        _close(c)
    side_dir = os.path.dirname(os.path.abspath(paper_db))
    market_path = os.path.join(side_dir, "market.db")
    market = ro_connect(market_path)
    cov = {"trades": len(rows), "with_numbers": 0, "no_bars": 0, "market_db": 0, "frames": 0}
    per: dict = {}
    for r in rows:
        per.setdefault((r["symbol"], r["tf"]), []).append(r)
    buck: list = [None] * len(rows)
    pos = {id(r): i for i, r in enumerate(rows)}
    try:
        for (sym, tf), rs in per.items():
            if tf not in TF_MS:
                continue
            first = min(int(r["signal_ts"]) for r in rs)
            lo = first + 1 - TF_MS[tf] * (IC.WARMUP_BARS + 1)
            hi = max(int(r["signal_ts"]) for r in rs) + 1
            bars = _market_bars(market, sym, tf, lo, hi)
            src = "market_db"
            if bars is None or len(bars["t"]) < IC.EMA_N + 20 or int(bars["t"][0]) > first + 1 - TF_MS[tf] * (IC.EMA_N + 20):
                fb = _frame_bars(frames, sym, tf, lo, now_ms)
                if fb is not None and len(fb["t"]) >= IC.EMA_N + 20:
                    bars, src = fb, "frames"
            if bars is None:
                cov["no_bars"] += len(rs)
                continue
            for r, b in zip(rs, numbers_at(rs, bars, tf, five)):
                if b is None:
                    cov["no_bars"] += 1
                    continue
                cov[src] += 1
                buck[pos[id(r)]] = b
    finally:
        _close(market)
    if rows:
        syms = {r["symbol"] for r in rows}
        fund = EM.load_funding(market_path, os.path.join(side_dir, "flow.db"), syms,
                               min(r["entry"] for r in rows) - 86_400_000, now_ms)
    else:
        fund = {"settled": {}, "premium": {}}
    known = []
    for r, b in zip(rows, buck):
        if b is None:
            continue
        rate, _src = EM.funding_at(fund, r["symbol"], r["entry"])
        b["funding"] = int(IC.funding_idx(np.array([np.nan if rate is None else rate]))[0])
        b["session"] = int(IC.session_idx(np.array([r["entry"]]))[0])
        ep, st, lev = r.get("entry_price"), r.get("stop_initial"), r.get("lev")
        r_net = None
        if ep and st and lev and abs(ep - st) > 0 and r.get("roe") is not None:
            r_net = r["roe"] / lev / (abs(ep - st) / ep)
        known.append((r, b, r_net))
    cov["with_numbers"] = len(known)
    by_s: dict = {}
    for item in known:
        by_s.setdefault(item[0]["strategy"], []).append(item)
    out.update({"since": start, "coverage": cov, "cells": paper_cells(known),
                "all": {**K.cell([r for r, _b, _rn in known], MIN_BUCKET)}, "min_strategy": MIN_PAPER_STRATEGY,
                # each of the 36 on its own (매매법별): its count, and its ranges once it has MIN_PAPER_STRATEGY
                "by_strategy": {s: {"n": len(v), **({"cells": paper_cells(v)} if len(v) >= MIN_PAPER_STRATEGY else {})}
                                for s, v in sorted(by_s.items())}})
    if cov["with_numbers"] < MIN_PAPER:
        out["waiting"] = True
    return out


def register(app, ctx) -> dict:
    from ..analysis import Heavy
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):
        heavy = Heavy()
    frames = getattr(ctx, "frames", None)

    @app.get("/api/v4/indranges")
    def get_indranges():
        """좋은 수치 찾기: the committed 5-year result (methods, ranges, all 36 pooled, the marked cells)."""
        return five_view()

    @app.get("/api/v4/indranges/strategy")
    def get_indranges_strategy(name: str = ""):
        """One strategy's 5-year cells (?name=<strategy code>)."""
        return strategy_view(name[:64])

    @app.get("/api/v4/indranges/paper")
    def get_indranges_paper():
        """The same ranges at the paper run's entries of the 36 (background + cached)."""
        return heavy.get("indranges:paper", TTL_S, lambda: paper_view(ctx.db, int(time.time() * 1000), frames),
                         wait_s=WAIT_S)

    return {"routes": ["/api/v4/indranges", "/api/v4/indranges/strategy", "/api/v4/indranges/paper"]}
