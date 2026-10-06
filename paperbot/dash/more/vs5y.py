"""5년 시험 vs 지금 vs 동전 봇 (v4 additions, wave 2 ⑨): one small table per timeframe on the strategy page. Read-only.

    GET /api/v4/vs5y/<strategy>        the 36, a DeepSeek definition or the reel

Per timeframe of the strategy's own accounts:

- y5: the 5-year numbers the strategy page already shows. The 36: agents/packets3.profile_card rows (signals per day,
  mean net ROE per trade on margin, win rate, median hold, lock-exit share; unit "roe"). DeepSeek and the reel:
  ds_profiles.card rows (the research's trades per day, net price % per trade with no leverage, win rate, hold; unit
  "1x": a live trade is compared as roe / leverage, the same 1x price unit).
- now: the live account of that timeframe (closed trades: count, days since the account started, per day, mean ROE and
  its spread, the same at 1x, win rate, median hold, lock-exit share). DeepSeek gets counts only (trades, per day; the
  owners' D10 / CONTRACT rule 3: no per-account numbers beyond a count).
- flips: the same-timeframe coin flips (the reel: its three 5m flips), each flip's numbers and their median (참고). None
  for DeepSeek (no per-account coin-flip comparison).
- words: per row a neutral word, never pass / fail: 'similar' (비슷), 'differs' (다름), 'fewer' (적음: live trades
  per day under half the research's; usual, a live account holds one position at a time), 'small' (표본 적음: under 20
  live trades, or under 2 days for the per-day row). Rules: per day ratio 0.5-2x; mean ROE within 2 standard errors of
  the live trades; win rate and lock share within max(5%p, 2 binomial standard errors); hold 0.5-2x.

Interim numbers (참고 until the day-30 verdict); fees, funding and slippage are inside every live trade's roe.
Cost: one indexed read of the strategy's and the same-timeframe flips' closed trades (trades_acct); cached 60 s.
"""
from __future__ import annotations

import contextlib
import math
import sqlite3
import statistics
import threading
import time
from typing import Optional

from fastapi import HTTPException

TTL_S = 60.0
CACHE_MAX = 64
MIN_N = 20
MIN_DAYS = 2.0
DAY_MS = 86_400_000


def _r(x, k: int = 4):
    return None if x is None or not math.isfinite(x) else round(float(x), k)


def stats(rows: list, start: int, now: int, counts_only: bool = False) -> dict:
    """rows: (roe, leverage, entry_time, exit_time, exit_reason) closed trades of one account since ``start``."""
    days = max((int(now) - int(start)) / DAY_MS, 1 / 24)
    n = len(rows)
    out = {"n": n, "days": _r(days, 2), "per_day": _r(n / days, 3)}
    if counts_only:
        return out
    if not n:
        return {**out, "roe": None, "roe_se": None, "roe_1x": None, "roe_1x_se": None, "win": None, "hold_h": None,
                "lock": None}
    roe = [float(r[0]) for r in rows]
    x1 = [float(r[0]) / float(r[1]) for r in rows if r[1]]
    se = (lambda v: statistics.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else None)
    return {**out, "roe": _r(statistics.fmean(roe)), "roe_se": _r(se(roe)),
            "roe_1x": _r(statistics.fmean(x1), 6) if x1 else None, "roe_1x_se": _r(se(x1), 6) if x1 else None,
            "win": _r(sum(1 for v in roe if v > 0) / n), "hold_h": _r(statistics.median((r[3] - r[2]) / 3.6e6 for r in rows), 3),
            "lock": _r(sum(1 for r in rows if r[4] == "LOCK") / n)}


def _median_of(xs: list, key: str):
    v = [x[key] for x in xs if x.get(key) is not None]
    return _r(statistics.median(v), 6) if v else None


def flips_stats(each: list) -> Optional[dict]:
    """The coin flips of one timeframe: the median of each number over the flips (n = their trades together)."""
    if not each:
        return None
    return {"accounts": len(each), "n": sum(x["n"] for x in each),
            **{k: _median_of(each, k) for k in ("per_day", "roe", "roe_1x", "win", "hold_h", "lock")}}


def _word_ratio(now, y5) -> Optional[str]:
    if now is None or not y5:
        return None
    r = now / y5
    return "similar" if 0.5 <= r <= 2 else "fewer" if r < 0.5 else "differs"


def words(y5: Optional[dict], now: dict, unit: str) -> dict:
    """A neutral word per row (see the module note); None where there is nothing to compare."""
    out: dict = {}
    if not y5:
        return out
    n = now.get("n") or 0
    out["per_day"] = "small" if (now.get("days") or 0) < MIN_DAYS else _word_ratio(now.get("per_day"), y5.get("per_day"))
    if "roe" not in now:                        # counts only (DeepSeek)
        return out
    if n < MIN_N:
        for k in ("roe", "win", "hold_h", "lock"):
            if y5.get(k) is not None:
                out[k] = "small"
        return out
    key, sek = ("roe", "roe_se") if unit == "roe" else ("roe_1x", "roe_1x_se")
    if y5.get("roe") is not None and now.get(key) is not None:
        se = now.get(sek) or 0.0
        out["roe"] = "similar" if abs(now[key] - y5["roe"]) <= 2 * se else "differs"
    for k in ("win", "lock"):
        p = y5.get(k)
        if p is not None and now.get(k) is not None:
            band = max(0.05, 2 * math.sqrt(max(p * (1 - p), 0.0) / n))
            out[k] = "similar" if abs(now[k] - p) <= band else "differs"
    if y5.get("hold_h") and now.get("hold_h") is not None:
        r = now["hold_h"] / y5["hold_h"]
        out["hold_h"] = "similar" if 0.5 <= r <= 2 else "differs"
    return out


def five_year(strategy: str) -> tuple[Optional[str], dict, Optional[dict]]:
    """(unit, {tf: y5 row}, card meta) from the strategy's 5-year card; ('roe'|'1x', ...) or (None, {}, None)."""
    from ...agents.packets3 import profile_card
    try:
        c = profile_card(strategy)
    except (OSError, ValueError, KeyError):  # an unreadable cards file: no 5-year side, never a 500
        c = None
    if c is not None:
        rows = {r["tf"]: {"per_day": r.get("signals_per_day"), "roe": r.get("mean_roe"), "win": r.get("win_rate"),
                          "hold_h": r.get("median_hold_hours"), "lock": r.get("lock_share")} for r in c.get("rows") or []}
        return "roe", rows, {"source": c.get("data_source")}
    try:
        from ... import ds_profiles
        d = ds_profiles.card(strategy)
    except Exception:  # noqa: BLE001  (missing or changed research files: no 5-year side, never a 500)
        d = None
    if d is None:
        return None, {}, None
    rows = {}
    for r in d.get("rows") or []:
        net = r.get("net_pct_is")
        rows[r["tf"]] = {"per_day": r.get("trades_per_day"), "roe": None if net is None else net / 100.0,
                         "win": r.get("win_rate"), "hold_h": r.get("hold_hours"), "lock": None}
    return "1x", rows, {"source": d.get("data_source"), "exit": d.get("exit"), "same_exits_as_live": d.get("same_exits_as_live")}


def compare(c: sqlite3.Connection, strategy: str, now: int) -> Optional[dict]:
    accts = c.execute("SELECT account_id, timeframe, kind, created_ts FROM accounts WHERE strategy = ? "
                      "AND kind IN ('strategy', 'ds200', 'reel') ORDER BY timeframe", (strategy,)).fetchall()
    if not accts:
        return None
    kind = accts[0][2]
    tfs = sorted({a[1] for a in accts})
    flips = c.execute(f"SELECT account_id, timeframe, created_ts FROM accounts WHERE kind = 'random' "
                      f"AND timeframe IN ({','.join('?' * len(tfs))})", tfs).fetchall() if kind != "ds200" else []
    unit, y5, meta = five_year(strategy)
    trades: dict = {}
    for aid in [a[0] for a in accts] + [f[0] for f in flips]:
        trades[aid] = c.execute("SELECT roe, leverage, entry_time, exit_time, exit_reason FROM trades "
                                "WHERE account_id = ? ORDER BY exit_time", (aid,)).fetchall()
    order = {"15m": 1, "30m": 2, "1h": 3, "4h": 4, "5m": 0}
    out_tfs = []
    for aid, tf, _k, created in sorted(accts, key=lambda a: order.get(a[1], 9)):
        nw = stats(trades[aid], created, now, counts_only=kind == "ds200")
        fl = None
        if kind != "ds200":
            fl = flips_stats([stats(trades[f[0]], f[2], now) for f in flips if f[1] == tf])
        row5 = y5.get(tf)
        out_tfs.append({"tf": tf, "account_id": aid, "y5": row5, "now": nw, "flips": fl,
                        "words": words(row5, nw, unit or "roe")})
    if kind == "strategy":
        # combo-5y: this timeframe's 5-year months (each a fresh $5,000 account, the committed combo5y.json); an extra
        # line only: a missing or unreadable file leaves the comparison as it was
        try:
            from . import combo5y as C5
            doc = C5.doc_cached()
            for r in out_tfs:
                r["month5y"] = C5.tf_month(doc, strategy, r["tf"])
        except Exception:  # noqa: BLE001
            pass
    return {"strategy": strategy, "kind": kind, "unit": unit, "y5_meta": meta, "tfs": out_tfs, "now": now,
            "min_n": MIN_N, "counts_only": kind == "ds200"}


def register(app, ctx) -> dict:
    data = ctx.data
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/vs5y/{strategy}")
    def get_vs5y(strategy: str):
        """The strategy's 5-year numbers next to its live accounts and the same-timeframe coin flips (cached 60 s)."""
        from ..app import json_finite
        if len(strategy) > 80:
            raise HTTPException(404, "unknown strategy")
        hit = cache.get(strategy)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get(strategy)
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            try:
                with contextlib.closing(data.conn()) as c:
                    v = compare(c, strategy, int(time.time() * 1000))
            except sqlite3.Error as exc:
                raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
            if v is None:
                raise HTTPException(404, "unknown strategy")
            v = json_finite(v)
            if len(cache) >= CACHE_MAX:
                cache.clear()
            cache[strategy] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/vs5y/{strategy}"], "cache": cache}
