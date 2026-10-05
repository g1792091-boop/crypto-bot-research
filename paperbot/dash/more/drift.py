"""진입 가격 차이 (entry drift, ana8B): how far the price the paper fill used had moved from the signal bar's close.

    GET /api/v4/drift

Every submitted signal row of paper3.db ``signal_log`` (status 'SUBMITTED', sigservice.py) stores the signal bar's
close (``data.close``), the reference price the paper fill used (``ref_price``: the ask for a long, the bid for a
short, read when the signal was ready) and the delay after the bar closed (``delay_ms``). The 5-year tests filled at
the next open plus 0.02% (config.Settings.slippage_frac); live pays

    drift (bps) = side x (ref_price / close - 1) x 10,000

on top: half the spread plus any run-away during the delay (plus = paid more than the close). Per group (기존 36 /
딥시크 / 5분 단타 / 동전 봇 / 추가 계좌) and timeframe: n, median, 90th percentile and mean in bps, split by delay
bucket (< 5 s, 5-20 s, 20-60 s, > 60 s); a strategy group minus the coin flips of the same timeframe (the flips draw
at the same bars, so the difference is the strategies' own run-away); ``over`` marks a median above 1.5 x the 0.02%
assumption (3 bps). Read-only SQL (the ``siglog_tf`` index, one timeframe at a time); cached ``TTL_S``. Descriptive,
not a verdict. Needs no trades: meaningful from day 1 for 15m and the coin flips, about a week for 4h per strategy.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional

TTL_S = 600.0
ASSUMED_BPS = 2.0                    # config.Settings.slippage_frac 0.0002 (the 5-year tests' entry slippage)
FLAG_X = 1.5
GROUPS = ("core", "ds200", "reel", "flip", "extra")
GROUP_KO = {"core": "기존 36", "ds200": "딥시크", "reel": "5분 단타", "flip": "동전 봇", "extra": "추가 계좌"}
TF_ORDER = ("5m", "15m", "30m", "1h", "4h")
BUCKETS = (("lt5", "5초 안", 0, 5_000), ("5to20", "5~20초", 5_000, 20_000), ("20to60", "20~60초", 20_000, 60_000),
           ("gt60", "60초 넘게", 60_000, None))
SMALL_N = 20
MAX_ROWS = 400_000                   # per timeframe, newest first (a month of every coin flip stays far under this)


def bucket_of(delay_ms: Optional[int]) -> Optional[str]:
    if delay_ms is None:
        return None
    for key, _ko, lo, hi in BUCKETS:
        if delay_ms >= lo and (hi is None or delay_ms < hi):
            return key
    return None


def drift_bps(side: int, ref: Optional[float], close: Optional[float]) -> Optional[float]:
    """side x (ref / close - 1) x 1e4; None when a price is missing or not positive."""
    try:
        ref, close = float(ref), float(close)
    except (TypeError, ValueError):
        return None
    if not (ref > 0 and close > 0) or side not in (1, -1):
        return None
    return side * (ref / close - 1.0) * 1e4


def _q(xs: list, p: float) -> Optional[float]:
    """The p-quantile (linear between the order statistics) of a sorted list."""
    if not xs:
        return None
    i = (len(xs) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def stats(xs: list) -> dict:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return {"n": 0}
    med = _q(xs, 0.5)
    out = {"n": n, "median": round(med, 3), "p90": round(_q(xs, 0.9), 3), "mean": round(sum(xs) / n, 3),
           "over": med > FLAG_X * ASSUMED_BPS}
    if n < SMALL_N:
        out["small"] = True
    return out


def rows_since(c: sqlite3.Connection, since_ms: int) -> list[tuple]:
    """(timeframe, strategy, side, ref_price, delay_ms, close) of the submitted signals since ``since_ms``."""
    out: list = []
    for tf in TF_ORDER:                  # 1d is record-only (status RECORD): never submitted
        q = ("SELECT timeframe, strategy, side, ref_price, delay_ms, data FROM signal_log "
             "WHERE timeframe = ? AND bar_close >= ? AND status = 'SUBMITTED' ORDER BY bar_close DESC LIMIT ?")
        for tf_, s, side, ref, delay, data in c.execute(q, (tf, int(since_ms), MAX_ROWS)):
            try:
                close = (json.loads(data) or {}).get("close") if data else None
            except (TypeError, ValueError):
                close = None
            out.append((tf_, s, int(side or 0), ref, delay, close))
    return out


def drift_view(paper_db: str, now_ms: int) -> dict:
    """Per group and timeframe the drift stats, by delay bucket, minus the same timeframe's coin flips."""
    from ..analysis import _close, ro_connect
    out: dict = {"groups": {}, "order": [g for g in GROUPS], "group_ko": GROUP_KO, "tf_order": list(TF_ORDER),
                 "buckets": [{"key": k, "ko": ko} for k, ko, _lo, _hi in BUCKETS], "assumed_bps": ASSUMED_BPS,
                 "flag_bps": FLAG_X * ASSUMED_BPS, "small_n": SMALL_N, "signals": 0, "label": "설명용, 판정 아님",
                 "note": ("드리프트 = 방향 × (체결 기준 가격 ÷ 신호 봉 종가 − 1), bp(0.01%) 단위. 플러스 = 종가보다 비싸게 산 것"
                          "(숏은 싸게 판 것). 5년 시험은 다음 봉 시가 + 0.02%(2bp)로 체결했다고 봄. 동전 봇은 같은 봉에서 "
                          "뽑으니, 매매법 − 동전 봇 = 매매법만의 차이. 중앙값이 3bp(가정의 1.5배)를 넘는 칸에 표시"),
                 "computed_at": int(now_ms)}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        from ...accounts import GROUP_OF_KIND
        try:
            from ...checkpoint import run_facts
            start = int(run_facts(c).get("start_ts") or 0)
        except (sqlite3.Error, ValueError, TypeError):
            start = 0
        kinds = {a: GROUP_OF_KIND.get(k, "other") for a, k in c.execute("SELECT account_id, kind FROM accounts")}
        rows = rows_since(c, start)
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    finally:
        _close(c)
    cells: dict = {}
    for tf, s, side, ref, delay, close in rows:
        g = kinds.get(f"{s}@{tf}")
        if g not in GROUPS:
            continue
        x = drift_bps(side, ref, close)
        if x is None:
            continue
        e = cells.setdefault(g, {}).setdefault(tf, {"all": [], "b": {}})
        e["all"].append(x)
        b = bucket_of(delay)
        if b:
            e["b"].setdefault(b, []).append(x)
    flip_med = {tf: stats(e["all"]).get("median") for tf, e in (cells.get("flip") or {}).items()}
    for g in GROUPS:
        tfs = {}
        allx: list = []
        for tf in sorted(cells.get(g) or {}, key=lambda t: TF_ORDER.index(t) if t in TF_ORDER else 99):
            e = cells[g][tf]
            st = stats(e["all"])
            fm = flip_med.get(tf)
            if g != "flip" and fm is not None and st.get("median") is not None:
                st["minus_flip"] = round(st["median"] - fm, 3)
            st["by_delay"] = {k: stats(e["b"].get(k, [])) for k, _ko, _lo, _hi in BUCKETS if e["b"].get(k)}
            tfs[tf] = st
            allx += e["all"]
        out["groups"][g] = {"all": stats(allx), "timeframes": tfs}
        out["signals"] += len(allx)
    out["since"] = start
    return out


def register(app, ctx) -> dict:
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/drift")
    def get_drift():
        """Entry drift per group and timeframe (cached ``TTL_S``; read-only)."""
        hit = cache.get("v")
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get("v")
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            v = drift_view(ctx.db, int(time.time() * 1000))
            cache["v"] = (time.time(), v)
            return v

    return {"routes": ["/api/v4/drift"]}
