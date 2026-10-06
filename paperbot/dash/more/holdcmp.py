"""그냥 들고 있었다면 / 반대로 했다면 (ana7a, 분석 › 들고 있었다면): per group since the run start, the group's realized
return next to (a) simply holding each traded coin and an equal-weight basket of them, and (b) a rough mirror: every
closed trade taken the other way. Descriptive, read-only.

    GET /api/v4/holdcmp?group=core|ds200|reel       (dash/analysis.an_group; default core = the 36)

- group / coin flips  closed trades since the run start (exit at or after it; open positions are not in it): the sum of
                      net P&L over the group's starting money (number of accounts x the initial equity), its win share,
                      and the same for the group's coin flips (the 36 and DeepSeek: the 15m-4h coin flips; the reel: its
                      three 5m coin flips).
- 그냥 들고 있었다면    each of the six traded coins bought at the run start and held, 1x, no fees or funding: the price
                      change from the first 5-minute open at or after the run start to the latest close, and the equal-
                      weight basket (the mean of the six). Prices: the market recorder's market.db (5-minute bars, read-
                      only); a coin it does not cover is read from ``frames`` (1-hour closed bars; then the first price
                      is the close of the hour bar that ended at or before the run start, ``price_source`` says which).
- 반대로 했다면         a7kit.mirror_pnl: the same entry and exit times and prices, the other side; fees paid again (both
                      directions pay them), funding the other way, a loss capped at the margin. a7kit.mirror_book runs
                      one mirror account per real account: each mirrored trade sized on the mirror account's own money
                      the way the real trade was sized on the real account's money (equity_after - pnl), never losing
                      more than that money, and no trade after the bust line (``busts``, ``after_bust``). A plain sum of
                      same-size mirrors was not used: it can lose more than an account ever had (-178% of one
                      account's money in the 30-day fixture's reel). ROUGH: the other side would have had other stops
                      and lock steps, so it would have left at other times.
- curve               hourly points (at most ``MAX_POINTS``; a wider step on a long run) of the cumulative realized
                      return of the group, its mirror and its coin flips, and of the basket (``hold_curve``).

DeepSeek (owners' D10 / D11): no return, no curve and no money for the group, its mirror or its coin flips (counts and
win shares only); the coins' own price changes are market data and stay.
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from typing import Optional

import numpy as np

from . import a7kit as K

TTL_S = 600
WAIT_S = 3.0
MIN_TRADES = 20
HOUR = 3_600_000
FIVE_MIN = 300_000
MAX_POINTS = 240
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def accounts_of(c: sqlite3.Connection, kinds: tuple, tfs: tuple) -> int:
    r = c.execute(f"SELECT COUNT(*) FROM accounts WHERE kind IN ({','.join('?' * len(kinds))}) "
                  f"AND timeframe IN ({','.join('?' * len(tfs))})", (*kinds, *tfs)).fetchone()
    return int(r[0] or 0)


def initial_of(c: sqlite3.Connection) -> float:
    import json
    from ...config import V3_INITIAL
    try:
        r = c.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
        v = float((json.loads(r[0]) or {}).get("initial_equity")) if r else None
    except (sqlite3.Error, TypeError, ValueError):
        v = None
    return v if v and v > 0 else float(V3_INITIAL)


def prices(paper_db: str, start: int, now_ms: int, frames=None, symbols=SYMBOLS) -> dict:
    """{symbol: (t_close ms array, close array, first price, source)} from market.db 5-minute bars, else frames 1h."""
    from ..analysis import _close, ro_connect
    out: dict = {}
    m = ro_connect(os.path.join(os.path.dirname(os.path.abspath(paper_db)), "market.db"))
    try:
        for sym in symbols:
            rows = []
            if m is not None:
                try:
                    rows = m.execute("SELECT open_time, open, close FROM kline5m WHERE symbol = ? AND open_time >= ? "
                                     "AND open_time < ? ORDER BY open_time", (sym, int(start), int(now_ms))).fetchall()
                except sqlite3.Error:
                    rows = []
            # the recorder covers the run start (its first bar within 10 minutes of it) and reaches near now
            if rows and int(rows[0][0]) - start <= 2 * FIVE_MIN and now_ms - (int(rows[-1][0]) + FIVE_MIN) <= 2 * HOUR:
                a = np.array(rows, dtype=float)
                out[sym] = (a[:, 0].astype(np.int64) + FIVE_MIN, a[:, 2], float(a[0, 1]), "market_db")
                continue
            if frames is None:
                continue
            try:                    # (the fetcher answers the latest bars: count them from the real clock too)
                end = max(int(now_ms), int(time.time() * 1000))
                df = frames(sym, "1h", int(min(1500 * 4, (end - start) // HOUR + 4)))
            except Exception:  # noqa: BLE001  (no network: that coin reads as not known)
                df = None
            if df is None or not len(df):
                continue
            raw = np.asarray(df["ts"].values)
            t_open = raw.astype(np.int64) if np.issubdtype(raw.dtype, np.number) else \
                raw.astype("datetime64[ms]").astype(np.int64)
            t_close = t_open + HOUR
            close = df["close"].to_numpy(float)
            j = int(np.searchsorted(t_close, start, side="right")) - 1
            if j < 0:
                continue
            out[sym] = (t_close[j:], close[j:], float(close[j]), "frames")
    finally:
        _close(m)
    return out


def at(px: tuple, t: int) -> Optional[float]:
    """The latest close at or before ``t`` (None before the first one)."""
    tc, cl = px[0], px[1]
    j = int(np.searchsorted(tc, t, side="right")) - 1
    return float(cl[j]) if j >= 0 else None


def cum(trades: list, key: str, ts: list, capital: float) -> list:
    """Cumulative sum of ``key`` over trades exited at or before each point, as a share of ``capital`` (no trades, no
    capital: no line at all, never a flat zero)."""
    if not capital or not trades:
        return [None] * len(ts)
    ex = np.array([t["exit"] for t in trades], np.int64)
    v = np.array([t.get(key) or 0.0 for t in trades], float)
    o = np.argsort(ex, kind="stable")
    ex, cs = ex[o], np.cumsum(v[o])
    out = []
    for p in ts:
        j = int(np.searchsorted(ex, p, side="right"))
        out.append(K.r4((cs[j - 1] if j else 0.0) / capital, 5))
    return out


def part(trades: list, capital: float, initial: float, bust_below: float) -> dict:
    """realized return, win share, the mirror's return and win share of one set of trades (a7kit.mirror_book: one
    mirror account per real account, sized on its own money, stopped at the bust line)."""
    book = K.mirror_book(trades, initial, bust_below)
    mir = [t for t in trades if t.get("mpnl") is not None]
    n = len(trades)
    capped = 0
    for t in mir:
        m, mg = K.mirror_pnl(t), t.get("margin")
        capped += m is not None and mg is not None and m <= -mg + 1e-9
    return {"trades": n, "wr": K.r4(sum(1 for t in trades if t["pnl"] > 0) / n, 4) if n else None,
            "ret": K.r4(sum(t["pnl"] for t in trades) / capital, 5) if capital and n else None,   # no trade: not 0%
            "mirror": {"trades": len(mir), "wr": K.r4(sum(1 for t in mir if t["mpnl"] > 0) / len(mir), 4) if mir else None,
                       "mirror_ret": K.r4(sum(t["mpnl"] for t in mir) / capital, 5) if capital and mir else None,
                       "liq_capped": capped, "busts": book["busts"], "after_bust": book["after_bust"]}}


def view(paper_db: str, now_ms: int, group: str = "core", frames=None) -> dict:
    from ..analysis import NO_MONEY_GROUPS, _close, ro_connect
    out: dict = {"group": group, "label": K.LABEL, "min_trades": MIN_TRADES}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        start = K.run_start_of(c)
        kinds, tfs = K.scope(group)
        mine = K.closed_trades(c, kinds, tfs, start)
        flips = K.closed_trades(c, ("random",), tfs, start)
        n_acc, n_flip = accounts_of(c, kinds, tfs), accounts_of(c, ("random",), tfs)
        init = initial_of(c)
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    finally:
        _close(c)
    if not start:
        out["error"] = "실험 시작 시각을 찾지 못함"
        return out
    cap, fcap = n_acc * init, n_flip * init
    px = prices(paper_db, start, now_ms, frames)
    traded = {s: sum(1 for t in mine if t["symbol"] == s) for s in SYMBOLS}
    coins = []
    for s in SYMBOLS:
        p = px.get(s)
        last = float(p[1][-1]) if p is not None and len(p[1]) else None
        coins.append({"symbol": s, "traded": traded[s], "p0": p[2] if p else None, "p1": last,
                      "chg": K.r4(last / p[2] - 1, 5) if p and last and p[2] else None, "source": p[3] if p else None})
    known = [x for x in coins if x["chg"] is not None]
    span = max(0, now_ms - start)
    step = max(HOUR, int(math.ceil(span / MAX_POINTS / HOUR)) * HOUR)
    ts = list(range(int(start), int(now_ms), step))[:MAX_POINTS] + [int(now_ms)]
    basket = []
    for p in ts:
        v = [at(px[x["symbol"]], p) for x in known]
        ok = [(a / x["p0"] - 1) for a, x in zip(v, known) if a is not None and x["p0"]]
        if not known:                       # no coin's price: no basket line at all (not one dot at 0%)
            basket.append(None)
        else:
            basket.append(K.r4(sum(ok) / len(ok), 5) if len(ok) == len(known) else (0.0 if p == ts[0] else None))
    from ...config import v4_settings
    bust = float(v4_settings().bust_below or 0.0)
    p_mine, p_flips = part(mine, cap, init, bust), part(flips, fcap, init, bust)   # (sets each trade's mpnl for cum)
    out.update({
        "since": start, "now": now_ms, "accounts": n_acc, "flip_accounts": n_flip, "initial": init,
        "hold": {"coins": coins, "basket_chg": K.r4(sum(x["chg"] for x in known) / len(known), 5) if known else None,
                 "known": len(known), "price_source": sorted({x["source"] for x in known})},
        "mine": p_mine, "coin_flips": p_flips,
        "hold_curve": {"t": ts, "basket": basket},
        "curve": {"t": ts, "group": cum(mine, "pnl", ts, cap), "mirror": cum(mine, "mpnl", ts, cap),
                  "flips": cum(flips, "pnl", ts, fcap)},
    })
    if len(mine) < MIN_TRADES:
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
    frames = getattr(ctx, "frames", None)

    @app.get("/api/v4/holdcmp")
    def get_holdcmp(group: Optional[str] = None):
        """그냥 들고 있었다면 / 반대로 했다면 for one group (?group=core|ds200|reel); background + cached ``TTL_S``."""
        g = an_group(group)
        return heavy.get(f"holdcmp:{g}", TTL_S, lambda: view(ctx.db, int(time.time() * 1000), g, frames),
                         wait_s=WAIT_S)

    return {"routes": ["/api/v4/holdcmp"]}
