"""장세 스위치 (regime5y, 분석 › 장세 스위치, the 36 only): does a locked strategy lose mainly because it runs in the
wrong kind of market? Read-only; descriptive, not a verdict (설명용, 판정 아님). Pre-registered in docs/regime5y.md.

    GET /api/v4/regime5y          the 5-year study: paperbot/dash/data/regime5y.json as committed (written offline by
                                  paperbot/dash/tools/regime5y.py; re-read only when the file changes)
    GET /api/v4/regime5y/live     the paper v4 run's own closed trades (the 36 and their coin flips, 15m-4h, since the
                                  run start) by the regime of their signal bar, once the 36 have ``LIVE_MIN`` of them

The live regimes use the study's formulas (tools/regime5y.indicators / label_codes) on Binance's public bars (the
dashboard's own candle fetcher, the last ``CANDLES_N`` bars of each coin and timeframe a trade needs; the first
``SETTLE_BARS`` of them only warm the averages up). The 급변장 line is the study's fixed ATR% threshold of each coin and
timeframe: the 80th percentile of the year before the signal cache's last day (``live_vol_q``, data from before any
live trade). A trade whose signal bar is no longer among the fetched bars counts as 모름 (unknown).

Heavy part (the candle fetches) runs in the background (dash/analysis.Heavy) and is cached ``TTL_S``; before the 36
have ``LIVE_MIN`` closed trades the answer is a cheap count (the page draws a filling bar) and nothing is fetched.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Callable, Optional

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "regime5y.json")
LABEL = "설명용, 판정 아님"
TTL_S = 1800
COUNT_TTL_S = 60
WAIT_S = 3.0
LIVE_MIN = 100                # closed trades of the 36 before the live table is shown (docs/regime5y.md)
LIVE_CELL_MIN = 20            # a regime row under this many trades is marked 표본 적음 on the page
CANDLES_N = 1500
SETTLE_BARS = 200
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
TFS = tuple(TF_MS)

_lock = threading.Lock()
_doc: dict = {"mtime": None, "doc": None}
_count: dict = {"at": 0.0, "val": None}


def _r(x: Any, n: int = 4) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None


def load_doc(path: str = DATA) -> dict:
    """The committed 5-year JSON (cached until the file changes); ``unavailable`` when it is not there or unreadable."""
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return {"unavailable": True, "note": "5년 계산 결과 파일이 아직 없습니다."}
    with _lock:
        if _doc["mtime"] == mtime and _doc["doc"] is not None:
            return _doc["doc"]
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {"unavailable": True, "note": "5년 계산 결과 파일을 읽지 못했습니다."}
    with _lock:
        _doc.update(mtime=mtime, doc=doc)
    return doc


def coin_of(symbol: str) -> str:
    """'LTCUSDT' -> 'LTCUSD' (the signal cache's coin names)."""
    s = str(symbol or "").upper()
    return s[:-1] if s.endswith("USDT") else s


def signal_open(d: dict, tf: str) -> Optional[int]:
    """Open time (ms) of the trade's signal bar: signal_ts is that bar's close - 1 ms; without it the bar before entry."""
    step = TF_MS.get(tf)
    if not step:
        return None
    try:
        if d.get("signal_ts") is not None:
            return (int(d["signal_ts"]) + 1) // step * step - step
        return int(d["entry_time"]) // step * step - step
    except (KeyError, TypeError, ValueError):
        return None


def read_trades(c: sqlite3.Connection, since_ms: int) -> list:
    """Closed trades of the 36 and the coin flips on 15m-4h since ``since_ms``: (kind, tf, symbol, bar open, roe, pnl)."""
    q = ("SELECT a.kind, a.timeframe, t.symbol, t.roe, t.pnl, t.data FROM trades t JOIN accounts a ON a.account_id = "
         f"t.account_id WHERE a.kind IN ('strategy', 'random') AND a.timeframe IN ({','.join('?' * len(TFS))}) "
         "AND t.exit_time >= ? AND t.pnl IS NOT NULL ORDER BY t.exit_time, t.id")
    out = []
    for kind, tf, sym, roe, pnl, data in c.execute(q, (*TFS, int(since_ms))):
        try:
            d = json.loads(data) if data else {}
        except (TypeError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        r = roe if roe is not None else d.get("roe")
        if r is None:
            continue
        out.append((str(kind), str(tf), str(sym or d.get("symbol") or ""), signal_open(d, str(tf)), float(r), float(pnl)))
    return out


def counts(paper_db: str) -> dict:
    """(the 36's closed trades, the coin flips') since the run start; cheap, cached ``COUNT_TTL_S``."""
    now = time.time()
    with _lock:
        if _count["val"] is not None and now - _count["at"] < COUNT_TTL_S and _count.get("db") == paper_db:
            return _count["val"]
    from ...agents.triggers import run_start
    from ..analysis import _close, ro_connect
    c = ro_connect(paper_db)
    if c is None:
        return {"error": "paper3.db 없음"}
    try:
        start = int(run_start(c) or 0)
        q = ("SELECT a.kind, COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id WHERE a.kind IN "
             f"('strategy', 'random') AND a.timeframe IN ({','.join('?' * len(TFS))}) AND t.exit_time >= ? "
             "AND t.pnl IS NOT NULL GROUP BY a.kind")
        got = dict(c.execute(q, (*TFS, start)).fetchall())
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    finally:
        _close(c)
    val = {"since": start, "trades": int(got.get("strategy", 0)), "flip_trades": int(got.get("random", 0))}
    with _lock:
        _count.update(at=now, val=val, db=paper_db)
    return val


def bar_codes(rows: list, vol_q: Optional[float]) -> dict:
    """{bar open ms: regime code} of fetched bars (dicts with time in s, high, low, close); the first ``SETTLE_BARS``
    are 모름 (the averages are still warming up), and so is everything when the coin has no fixed threshold."""
    from ..tools import regime5y as G
    import numpy as np
    if not rows:
        return {}
    h = np.array([float(r["high"]) for r in rows])
    lo = np.array([float(r["low"]) for r in rows])
    c = np.array([float(r["close"]) for r in rows])
    adx, slope, atrp = G.indicators(h, lo, c)
    code = G.label_codes(adx, slope, atrp, np.nan if vol_q is None else float(vol_q))
    code[:SETTLE_BARS] = G.UNKNOWN
    return {int(r["time"]) * 1000: int(k) for r, k in zip(rows, code)}


def summarize(vals: list) -> list:
    """[trades, win rate, mean net ROE, P&L sum] of (roe, pnl) pairs."""
    n = len(vals)
    if not n:
        return [0, None, None, 0.0]
    return [n, _r(sum(1 for r, _p in vals if r > 0) / n, 4), _r(sum(r for r, _p in vals) / n, 5), _r(sum(p for _r_, p in vals), 2)]


def live_view(paper_db: str, candles: Callable, doc: dict, now_ms: int) -> dict:
    from ...agents.triggers import run_start
    from ..analysis import _close, ro_connect
    from ..tools import regime5y as G
    out: dict = {"label": LABEL, "need": LIVE_MIN, "cell_min": LIVE_CELL_MIN, "candles_n": CANDLES_N,
                 "vol_q_asof": doc.get("live_vol_q_asof")}
    c = ro_connect(paper_db)
    if c is None:
        return {**out, "error": "paper3.db 없음"}
    try:
        start = int(run_start(c) or 0)
        rows = read_trades(c, start)
    except sqlite3.Error as exc:
        return {**out, "error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    finally:
        _close(c)
    mine = [r for r in rows if r[0] == "strategy"]
    out.update(since=start, trades=len(mine), flip_trades=len(rows) - len(mine))
    if len(mine) < LIVE_MIN:
        return {**out, "waiting": True}
    vq = doc.get("live_vol_q") or {}
    codes: dict = {}
    failed = []
    for sym, tf in sorted({(r[2], r[1]) for r in rows}):
        try:
            bars = candles(sym, tf, CANDLES_N)
            codes[(sym, tf)] = bar_codes(bars, (vq.get(tf) or {}).get(coin_of(sym)))
        except Exception:  # noqa: BLE001  (a bar fetch that fails leaves those trades 모름, never a 500)
            failed.append(f"{sym} {tf}")
            codes[(sym, tf)] = {}
    keys = [(G.TREND, "trend"), (G.RANGE, "range"), (G.SHOCK, "shock"), (G.NORMAL, "normal"), (G.UNKNOWN, "unknown")]
    split: dict = {(kind, k): [] for kind in ("strategy", "random") for k, _x in keys}
    for kind, tf, sym, t0, roe, pnl in rows:
        k = codes.get((sym, tf), {}).get(t0, G.UNKNOWN) if t0 is not None else G.UNKNOWN
        split[(kind, k)].append((roe, pnl))
    out["rows"] = [{"key": name, "ko": G.RKO[k], "group": summarize(split[("strategy", k)]),
                    "coin_flips": summarize(split[("random", k)])} for k, name in keys]
    out["fetch_failed"] = failed
    out["computed_for"] = now_ms
    return out


def register(app, ctx) -> dict:
    from ..analysis import Heavy
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):
        heavy = Heavy()

    @app.get("/api/v4/regime5y")
    def get_regime5y():
        """The 5-year 장세 스위치 study as committed (docs/regime5y.md)."""
        return load_doc()

    @app.get("/api/v4/regime5y/live")
    def get_regime5y_live():
        """The paper run's closed trades by regime at entry (the 36 vs the coin flips); a count until ``LIVE_MIN``."""
        n = counts(ctx.db)
        base = {"label": LABEL, "need": LIVE_MIN, "cell_min": LIVE_CELL_MIN}
        if "error" in n:
            return {**base, **n}
        if n["trades"] < LIVE_MIN:
            return {**base, **n, "waiting": True}
        return heavy.get("regime5y:live", TTL_S, lambda: live_view(ctx.db, ctx.candles, load_doc(), int(time.time() * 1000)),
                         wait_s=WAIT_S)

    return {"routes": ["/api/v4/regime5y", "/api/v4/regime5y/live"]}
