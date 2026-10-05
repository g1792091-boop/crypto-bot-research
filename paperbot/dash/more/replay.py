"""거래 다시보기 (#/replay/<trade id>) and the small equity lines of the 순위표 rows. Read-only over paper3.db.

    GET /api/v4/replay/<trade id>        one closed trade, the bars around it and the lines the exits used
    GET /api/v4/replay/sparks?ids=a,b    each account's equity over the run, 36 points (the 순위표 row lines)

Bars come from paper3.db ``live_bars`` first: the very 1m bars the accounts stepped on (fillcost.bar_rows), cut into
the display timeframe here, so the replay shows what the bot saw and nothing is fetched. When the table holds none for
the trade's window (an older database, a test world), ``ctx.candles`` (Binance klines on the real server; it only
gives the LAST n bars, at most 1,500) is asked once for that trade, and only when the window is inside those 1,500
bars. Either answer is cached per trade (a finished window for an hour, one that is still running for a minute).
``fit`` says whether the entry and exit prices lie inside their bars: false means the bars do not match the trade
(the page then says so instead of drawing a story on the wrong prices).

The display timeframe is the account's own; the reel and the 5m coin flips (the reel's own exits) are always 5m. A
trade longer than MAX_HOLD_BARS bars of its own timeframe is shown on the next larger one (``stepped``).

What the exits used (all from the trade's own record, ``trades.data`` = models.TradeRecord):
- house exits (engine.py: 2 ATR stop + the ladder lock): the first stop ``stop_initial``; the lock steps are rebuilt
  from the bars with ladder.LadderSpec (the record keeps only the last lock, ``lock_roe``, and its stop price
  ``stop_price``; the costs part of the lock price is taken from that last stop, so the last step is exactly the
  recorded one). Lock times are bar-level (the engine checks every 1m bar): ``steps[].rebuilt`` is always true.
- the reel's own exits (reel_engine.py): the fixed stop ``stop_initial``, the target = the previous 5m bar's upper
  Bollinger band (20, 2, population std) moved every bar, the 96-bar time exit; Bollinger(20, 2) and the 200-bar
  simple average are computed here from the same bars (with warm-up bars before the window), and the breach bar
  (close below the lower band) and the signal bar of the reel's entry are found on them (``rebuilt``: bar data).
Nothing here is a verdict: the page labels the replay as one trade's story (참고).
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Optional

from fastapi import HTTPException

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
         "1d": 86_400_000}
STEP_UP = ("5m", "15m", "30m", "1h", "4h", "1d")
PRE_BARS = {"5m": 30, "15m": 32, "30m": 30, "1h": 30, "4h": 24, "1d": 20}      # bars shown before the entry bar
POST_BARS = 12                                                                 # bars shown after the exit bar
MAX_HOLD_BARS = 240             # a longer trade is shown on the next larger timeframe
BB_LEN, BB_K, MA_LEN = 20, 2.0, 200          # reel_engine / PREREG_REEL5M section 5
REEL_WAIT = 12                  # bars a reel setup waits after its last breach
REEL_BARS = 96                  # reel_engine.MAX_HOLD_5M
FIT_TOL = 0.004                 # entry / exit price may sit this far outside its bar (slippage, mark-price fills)
CANDLE_LIMIT = 1_500            # Binance klines: the last 1,500 bars at most
CACHE_MAX = 64
DONE_TTL_S, LIVE_TTL_S = 3_600.0, 60.0
SPARK_POINTS = 36
SPARK_MAX_IDS = 40
SPARK_TTL_S = 120.0


def _fin(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x: Optional[float]) -> Optional[float]:
    """A price with 7 significant digits (small JSON; the page formats it with fmt.price)."""
    return None if x is None or not math.isfinite(x) else float(f"{x:.7g}")


def _ro(path: str) -> sqlite3.Connection:
    from ..app import _ro_uri
    c = sqlite3.connect(_ro_uri(path), uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------- bars
def bars_from_minutes(rows, tf_ms: int) -> list:
    """1m rows (ts, open, high, low, close), oldest first -> [[open ts ms, o, h, l, c, minutes]] per tf bucket."""
    out: list = []
    for ts, o, h, l, c in rows:
        b = (int(ts) // tf_ms) * tf_ms
        if out and out[-1][0] == b:
            cur = out[-1]
            cur[2] = max(cur[2], float(h))
            cur[3] = min(cur[3], float(l))
            cur[4] = float(c)
            cur[5] += 1
        else:
            out.append([b, float(o), float(h), float(l), float(c), 1])
    return out


def _live_bars(c, symbol: str, lo: int, hi: int, tf_ms: int) -> list:
    try:
        rows = c.execute("SELECT ts, open, high, low, close FROM live_bars WHERE ts >= ? AND ts < ? AND symbol = ? "
                         "ORDER BY ts", (int(lo), int(hi), symbol)).fetchall()
    except sqlite3.Error:                       # an older database without the table
        return []
    return bars_from_minutes([tuple(r) for r in rows], tf_ms)


def _candle_bars(candles, symbol: str, tf: str, lo: int, hi: int, now: int, lo_shown: Optional[int] = None) -> list:
    """ctx.candles gives the LAST n bars only: used when the shown window [lo_shown, now] fits in CANDLE_LIMIT bars
    (the warm-up bars before it, from lo, only as far as they still fit), else nothing. One call."""
    if candles is None:
        return []
    tf_ms = TF_MS[tf]
    if (now - (lo if lo_shown is None else lo_shown)) // tf_ms + 2 > CANDLE_LIMIT:
        return []
    need = min(CANDLE_LIMIT, (now - lo) // tf_ms + 2)
    try:
        rows = candles(symbol, tf, int(max(need, 2)))
    except Exception:  # noqa: BLE001  (Binance down: the page shows the trade without bars)
        return []
    out = []
    for k in rows or []:
        try:
            t = int(k["time"]) * 1000
            if lo <= t < hi:
                out.append([t, float(k["open"]), float(k["high"]), float(k["low"]), float(k["close"]), tf_ms // 60_000])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def bollinger(closes: list, n: int = BB_LEN, k: float = BB_K) -> tuple:
    """(up, mid, dn) per index; None until n closes (population std, as reel_engine.upper_band and ta.bb)."""
    up, mid, dn = [None] * len(closes), [None] * len(closes), [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        m = math.fsum(w) / n
        sd = math.sqrt(max(0.0, math.fsum((x - m) ** 2 for x in w) / n))
        up[i], mid[i], dn[i] = m + k * sd, m, m - k * sd
    return up, mid, dn


def sma(closes: list, n: int = MA_LEN) -> list:
    out: list = [None] * len(closes)
    s = 0.0
    for i, x in enumerate(closes):
        s += x
        if i >= n:
            s -= closes[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _idx(bars: list, t: Optional[int], tf_ms: int) -> Optional[int]:
    """Index of the bar containing time t (ms), None when no bar holds it (outside the window or in a gap)."""
    if t is None or not bars:
        return None
    for i in range(len(bars) - 1, -1, -1):
        if bars[i][0] <= t:
            return i if t < bars[i][0] + tf_ms else None
    return None


def _fits(bar: Optional[list], price: Optional[float]) -> Optional[bool]:
    if bar is None or price is None:
        return None
    return bar[3] * (1 - FIT_TOL) <= price <= bar[2] * (1 + FIT_TOL)


# ---------------------------------------------------------------- the exits, rebuilt on the bars
def lock_steps(side: int, entry: float, lev: float, bars: list, i0: int, i1: int, lock_roe: Optional[float],
               stop_final: Optional[float], spec) -> list:
    """The ladder lock steps of a house trade on bars i0..i1 (entry bar .. exit bar), ending exactly at the recorded
    last lock (lock_roe, stop_final). The costs part c (round trip + funding at the last lock) comes from that last
    stop: stop = entry * (1 + side * (lock / lev + c)). [] when the trade never locked."""
    if lock_roe is None or stop_final is None or not entry or not lev or i0 is None or i1 is None:
        return []
    c = side * (stop_final / entry - 1.0) - lock_roe / lev
    price = lambda L: entry * (1.0 + side * (L / lev + c))           # noqa: E731
    best, cur, out = entry, None, []
    for j in range(i0, i1 + 1):
        best = max(best, bars[j][2]) if side > 0 else min(best, bars[j][3])
        roe = lev * (side * (best / entry - 1.0) - c)
        L = spec.lock_for(roe)
        if L is None:
            continue
        L = min(L, lock_roe)
        if cur is None or L > cur + 1e-9:
            cur = L
            out.append({"bar": j, "level": round(L, 4), "price": _r(price(L)), "rebuilt": True})
    if cur is None or cur < lock_roe - 1e-9:      # the bars did not reach it (1m vs bar data): the record wins
        j = i1
        for k in range(i0, i1 + 1):               # the bar of the best price
            if (side > 0 and bars[k][2] >= bars[j][2]) or (side < 0 and bars[k][3] <= bars[j][3]):
                j = k
        out.append({"bar": j, "level": round(lock_roe, 4), "price": _r(stop_final), "rebuilt": True})
    out[-1]["price"] = _r(stop_final)
    return out


def reel_setup(bars: list, dn: list, up: list, mid: list, ma: list, s: int) -> dict:
    """The reel's setup before signal bar s (PREREG H1): breach = a close below the lower band while the middle line
    is above the 200 line; the setup starts at the first breach of a chain whose breaches are at most 12 bars apart
    and ends at s (a green bar closing inside the band). {"breach": first, "last_breach": last, "signal_ok": bool}."""
    out = {"breach": None, "last_breach": None, "signal_ok": None}
    if s is None or s < 1 or dn[s] is None:
        return out
    o, c = bars[s][1], bars[s][4]
    out["signal_ok"] = bool(c > o and dn[s] < c < (up[s] if up[s] is not None else float("inf")))

    def breach(i):
        return (dn[i] is not None and mid[i] is not None and ma[i] is not None and mid[i] > ma[i]
                and bars[i][4] < dn[i])
    last = None
    for i in range(s - 1, max(-1, s - 1 - REEL_WAIT), -1):
        if breach(i):
            last = i
            break
    if last is None:
        return out
    first = last
    i = last - 1
    while i >= 0 and first - i <= REEL_WAIT:
        if breach(i):
            first = i
        elif dn[i] is not None and bars[i][4] > bars[i][1] and dn[i] < bars[i][4] < (up[i] or float("inf")):
            break                                    # a signal bar here would have ended the earlier setup
        i -= 1
    out.update(breach=first, last_breach=last)
    return out


# ---------------------------------------------------------------- the answer
def build(data, c, trade_id: int, candles=None, now_ms: Optional[int] = None) -> Optional[dict]:
    """The replay answer for one closed trade (None when the id is unknown)."""
    from ...config import v3_settings
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    t = c.execute("SELECT t.id, t.account_id, t.symbol, t.entry_time, t.exit_time, t.exit_reason, t.leverage, t.pnl, "
                  "t.roe, t.equity_after, t.data, a.strategy, a.timeframe, a.kind, a.data AS adata, a.parent "
                  "FROM trades t LEFT JOIN accounts a ON a.account_id = t.account_id WHERE t.id = ?",
                  (int(trade_id),)).fetchone()
    if t is None:
        return None
    try:
        d = json.loads(t["data"] or "{}")
    except (TypeError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    acc = {"account_id": t["account_id"], "strategy": t["strategy"], "timeframe": t["timeframe"] or d.get("timeframe"),
           "kind": t["kind"], "data": t["adata"], "parent": t["parent"]}
    try:
        acc.update(data._group_fields(dict(acc)))
    except Exception:  # noqa: BLE001  (names are a nicety; the replay still works)
        acc.update(group=None, family=None, exits=None, name_ko=None)
    acc.pop("data", None)
    side = 1 if int(d.get("side") or 1) > 0 else -1
    entry, exit_px = _fin(d.get("entry_price")), _fin(d.get("exit_price"))
    lev = _fin(t["leverage"]) or _fin(d.get("leverage")) or 1.0
    stop_final, stop_init = _fin(d.get("stop_price")), _fin(d.get("stop_initial"))
    lock_roe = _fin(d.get("lock_roe"))
    reel = acc.get("exits") == "reel"
    own_tf = acc["timeframe"] if acc["timeframe"] in TF_MS else "15m"
    tf = "5m" if reel else own_tf
    et, xt = int(t["entry_time"]), int(t["exit_time"])
    while not reel and (xt - et) // TF_MS[tf] > MAX_HOLD_BARS and tf != STEP_UP[-1]:
        tf = STEP_UP[STEP_UP.index(tf) + 1] if tf in STEP_UP else "1h"
    tf_ms = TF_MS[tf]
    pre = PRE_BARS.get(tf, 30)
    lo = (et // tf_ms - pre) * tf_ms
    hi = min((xt // tf_ms + POST_BARS + 1) * tf_ms, (now // 60_000 + 1) * 60_000)
    warm = (MA_LEN + 1) * tf_ms if reel else 0      # the 200 line and the band need bars before the first shown
    bars = _live_bars(c, t["symbol"], lo - warm, hi, tf_ms)
    source = "live_bars" if bars else None
    if not bars:
        bars = _candle_bars(candles, t["symbol"], tf, lo - warm, hi, now, lo_shown=lo)
        source = "binance" if bars else None
    rt = v3_settings().round_trip_cost
    try:
        rt = data._round_trip(c)
    except Exception:  # noqa: BLE001
        pass
    closes = [b[4] for b in bars]
    lines: dict = {}
    if reel and bars:
        up, mid, dn = bollinger(closes)
        ma = sma(closes)
    first = next((i for i, b in enumerate(bars) if b[0] >= lo), len(bars))
    shown = bars[first:]
    if reel and bars:
        up, mid, dn, ma = up[first:], mid[first:], dn[first:], ma[first:]
    i_e, i_x = _idx(shown, et, tf_ms), _idx(shown, xt, tf_ms)
    sig_ts = _fin(d.get("signal_ts"))
    i_s = _idx(shown, int(sig_ts), tf_ms) if sig_ts is not None else None
    if i_s is None and i_e is not None and i_e > 0:
        i_s = i_e - 1
    fit = None
    if shown and i_e is not None and i_x is not None:
        fit = bool(_fits(shown[i_e], entry)) and (bool(_fits(shown[i_x], exit_px)) or t["exit_reason"] == "LIQ")
    events: list = []
    steps: list = []
    levels: dict = {"stop_initial": _r(stop_init if stop_init is not None else stop_final),
                    "stop_final": _r(stop_final), "liq": _r(_fin(d.get("liq_price"))), "entry": _r(entry),
                    "exit": _r(exit_px), "target_final": None, "lock_start": None, "time_exit_ts": None}
    if reel:
        levels["target_final"] = _r(_fin(d.get("tp_price")))
        levels["time_exit_ts"] = (et // TF_MS["5m"]) * TF_MS["5m"] + REEL_BARS * TF_MS["5m"]
        if shown:
            # the resting target of bar j at risk: the previous closed bar's upper band (the entry bar: the signal bar's)
            tgt = [None] * len(shown)
            if i_e is not None:
                for j in range(i_e, (i_x if i_x is not None else len(shown) - 1) + 1):
                    tgt[j] = _r(up[j - 1]) if j >= 1 and up[j - 1] is not None else None
            lines = {"bb_up": [_r(v) for v in up], "bb_dn": [_r(v) for v in dn], "ma200": [_r(v) for v in ma],
                     "target": tgt}
            if acc.get("kind") == "reel" and i_s is not None:
                st = reel_setup(shown, dn, up, mid, ma, i_s)
                if st["breach"] is not None:
                    events.append({"bar": st["breach"], "kind": "breach", "price": _r(shown[st["breach"]][4]),
                                   "band": _r(dn[st["breach"]]), "rebuilt": True})
                    if st["last_breach"] != st["breach"]:
                        events.append({"bar": st["last_breach"], "kind": "breach_again",
                                       "price": _r(shown[st["last_breach"]][4]), "rebuilt": True})
                events.append({"bar": i_s, "kind": "signal", "how": "reel", "ok": st["signal_ok"],
                               "filter": bool(mid[i_s] is not None and ma[i_s] is not None and mid[i_s] > ma[i_s]),
                               "rebuilt": True})
            elif i_s is not None:
                events.append({"bar": i_s, "kind": "signal", "how": "flip"})
    else:
        spec = v3_settings().ladder
        levels["lock_start"] = _r(entry * (1 + side * ((spec.first_lock + spec.trigger_gap) / lev + rt))) if entry else None
        if shown and i_e is not None and i_x is not None:
            steps = lock_steps(side, entry, lev, shown, i_e, i_x, lock_roe, stop_final, spec)
        if i_s is not None:
            events.append({"bar": i_s, "kind": "signal", "how": "flip" if acc.get("kind") == "random" else "house"})
    if i_e is not None:
        events.append({"bar": i_e, "kind": "entry", "price": _r(entry)})
    for s in steps:
        events.append({"bar": s["bar"], "kind": "lock", "level": s["level"], "price": s["price"]})
    if i_x is not None:
        events.append({"bar": i_x, "kind": "exit", "price": _r(exit_px), "reason": t["exit_reason"]})
    order = {"breach": 0, "breach_again": 1, "signal": 2, "entry": 3, "lock": 4, "exit": 5}
    events.sort(key=lambda e: (e["bar"], order.get(e["kind"], 9)))
    partial = bool(shown) and shown[-1][0] + tf_ms > now
    trade = {"id": int(t["id"]), "account_id": t["account_id"], "symbol": t["symbol"], "side": side, "leverage": lev,
             "entry_time": et, "exit_time": xt, "exit_reason": t["exit_reason"], "entry_price": _r(entry),
             "exit_price": _r(exit_px), "pnl": _fin(t["pnl"]), "roe": _fin(t["roe"]), "equity_after": _fin(t["equity_after"]),
             "fees": _fin(d.get("fees")), "funding": _fin(d.get("funding")), "margin": _fin(d.get("margin")),
             "qty": _fin(d.get("qty")), "tier": d.get("tier"), "lock_roe": lock_roe, "signal_ts": sig_ts,
             "mfe_price": _r(_fin(d.get("mfe_price"))), "mae_price": _r(_fin(d.get("mae_price"))),
             "price_move": _fin(d.get("price_move")), "hold_s": max(0, (xt - et) // 1000)}
    return {"trade": trade, "account": acc, "tf": tf, "tf_own": own_tf, "stepped": tf != (("5m" if reel else own_tf)),
            "exits": "reel" if reel else "house", "source": source, "fit": fit, "partial": partial,
            "bars": [[b[0] // 1000, _r(b[1]), _r(b[2]), _r(b[3]), _r(b[4])] for b in shown],
            "idx": {"signal": i_s, "entry": i_e, "exit": i_x}, "lines": lines, "steps": steps, "events": events,
            "levels": levels, "round_trip": rt, "reel_bars": REEL_BARS if reel else None,
            "ladder": None if reel else _ladder_of()}


def _ladder_of() -> dict:
    from ...config import v3_settings
    s = v3_settings()
    return {"first": s.ladder_first_lock, "step": s.ladder_step, "gap": s.ladder_trigger_gap}


# ---------------------------------------------------------------- equity lines for list rows
def sparks(c, ids: list, now_ms: Optional[int] = None, points: int = SPARK_POINTS) -> dict:
    """{"t0", "t1", "points", "initial", "series": {id: [equity at each of `points` times, None before its first]}}:
    one common time axis (the run's first account to now), so every row's line is on the same scale of time. Each
    point is the account's last equity row at or before that time (an indexed seek; equity is written every 5 min)."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    r = c.execute("SELECT MIN(created_ts) FROM accounts").fetchone()
    t0 = int(r[0]) if r and r[0] is not None else None
    out = {"t0": t0, "t1": now, "points": points, "series": {}}
    if t0 is None or now <= t0:
        return out
    grid = [t0 + (now - t0) * k // (points - 1) for k in range(points)]
    for aid in ids:
        vals = []
        for ts in grid:
            row = c.execute("SELECT equity FROM equity WHERE account_id = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                            (aid, ts)).fetchone()
            vals.append(None if row is None else round(float(row[0]), 2))
        out["series"][aid] = vals
    return out


# ---------------------------------------------------------------- routes
def register(app, ctx):
    cache: "OrderedDict[int, tuple]" = OrderedDict()
    spark_cache: dict = {}
    lock = threading.Lock()

    def conn():
        return _ro(ctx.db)

    @app.get("/api/v4/replay/sparks")
    def replay_sparks(ids: str = ""):
        """Equity lines of up to 40 accounts (the 순위표 page on screen asks for its rows only, never all 331)."""
        want = [x for x in dict.fromkeys(s.strip() for s in str(ids).split(",")) if x][:SPARK_MAX_IDS]
        now = time.time()
        bucket = int(now // SPARK_TTL_S)
        out_series, missing = {}, []
        with lock:
            for aid in want:
                hit = spark_cache.get(aid)
                if hit and hit[0] == bucket:
                    out_series[aid] = hit[1]
                else:
                    missing.append(aid)
        head = {"t0": None, "t1": int(now * 1000), "points": SPARK_POINTS}
        if missing:
            with conn() as c:
                v = sparks(c, missing, now_ms=bucket * int(SPARK_TTL_S * 1000))
            head.update(t0=v["t0"], t1=v["t1"])
            with lock:
                if len(spark_cache) > 2_000:
                    spark_cache.clear()
                for aid, vals in v["series"].items():
                    spark_cache[aid] = (bucket, vals, v["t0"], v["t1"])
                    out_series[aid] = vals
        else:
            any_hit = spark_cache.get(want[0]) if want else None
            if any_hit:
                head.update(t0=any_hit[2], t1=any_hit[3])
        try:
            initial = ctx.data.initial()
        except Exception:  # noqa: BLE001
            initial = None
        return {**head, "initial": initial, "series": out_series}

    @app.get("/api/v4/replay/{trade_id}")
    def replay_trade(trade_id: int):
        """One closed trade replayed on its bars (cached per trade)."""
        now = time.time()
        with lock:
            hit = cache.get(trade_id)
            if hit and now < hit[0]:
                cache.move_to_end(trade_id)
                return hit[1]
        with conn() as c:
            v = build(ctx.data, c, trade_id, candles=getattr(ctx, "candles", None))
        if v is None:
            raise HTTPException(404, "그런 거래가 없습니다")
        from ..app import json_finite
        v = json_finite(v)
        done = not v["partial"] and v["bars"] and v["source"]
        with lock:
            cache[trade_id] = (now + (DONE_TTL_S if done else LIVE_TTL_S), v)
            cache.move_to_end(trade_id)
            while len(cache) > CACHE_MAX:
                cache.popitem(last=False)
        return v

    return {"routes": ["/api/v4/replay/{trade_id}", "/api/v4/replay/sparks"]}
