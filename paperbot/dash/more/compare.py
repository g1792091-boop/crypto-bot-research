"""매매법 비교 (conv-b, 매매법 › 비교, #/compare): 2-4 strategies or accounts side by side. Read-only on paper3.db (the
dashboard's read-only connection) and the 5-year research cards; nothing is written, nothing here is a verdict.

    GET /api/v4/compare?ids=S5_DONCHIAN_MFI,S1_EMA_RSI_CHOP@1h,...     (at most 4, comma separated)

An id is a strategy name (its own timeframe accounts: kind strategy / ds200 / reel, summed) or one account id ("@").
Coin flips (kind random) are the yardstick, never a pick: they are dropped and named in ``dropped``. Per item:

- ``ret``      the summed realized wallet against the summed starting wallet (closed trades; the board's own wallet)
- ``curve``    the summed realized balance after every closed trade since the accounts started, as a return from the
               start (at most ``CURVE_MAX`` points, the last one = the board's wallets now); ``t`` in ms
- ``mdd``      the deepest fall of that summed curve from its running peak (every closed trade, and the last point: the
               wallets now, which already paid an open position's entry fee and funding); ``mdd_worst``
               the deepest engine drawdown of one of its accounts (mark price, open positions included)
- ``trades`` / ``wins`` / ``losses`` / ``win_rate``; ``payoff`` = average win / |average loss| (both needed);
               ``pf`` = gross win / |gross loss| (None without a loss); ``open`` positions now, ``bust`` accounts
- ``flip``     동전 봇 순위 (참고): the same-timeframe coin-flip seeds (RANDOM_k summed over the SAME timeframes as the
               item; the reel against its three 5m flips) and how many of them the item's return is above:
               {"n", "above", "tfs"}. None for late-started extras (never compared) and DeepSeek (no money here)
- ``by_tf``    per timeframe account: trades, return, win rate, engine drawdown, open, and (core / reel) the median
               return of that timeframe's coin flips and the difference (참고)
- ``y5``       the 5-year research rows of the strategy for the item's timeframes (more/vs5y.five_year: unit "roe" =
               mean ROE per trade on margin for the 36 under the v3 leverage rule, "1x" = net price % per trade for the
               reel; ``exit`` / ``same_exits_as_live`` when the research's exits are not the live ones); None for
               extras (another rule) and DeepSeek. NOT the live rules: the page says so (v3 배수, every signal taken)

HONESTY (CONTRACT section 1, D10/D11): a DeepSeek definition or account is compared by COUNTS ONLY on this mixed
screen: ``counts_only`` true and only trades, open positions and the timeframes are sent (no wallet, return, curve,
drawdown, win rate, payoff, profit factor, coin-flip rank or 5-year return). Every number is labelled 설명용, 판정 아님;
under ``SMALL`` closed trades the page says 표본 적음.

Cost: the board (cached by the dashboard) + one indexed read of the picked accounts' closed trades; computed in the
background (dash/analysis.Heavy, this module's own one-at-a-time worker so a long 조합 시너지 run never holds it),
answered within ``WAIT_S`` or ``{"pending": true}``, cached ``TTL_S`` per id list.
"""
from __future__ import annotations

import contextlib
import math
import re
import sqlite3
import statistics
import time
from typing import Optional

from fastapi import HTTPException

TTL_S = 60
WAIT_S = 3.0
MAX_IDS = 4
SMALL = 30                    # checkpoint.MIN_TRADES: under it the page says 표본 적음 (grid.SMALL, the same floor)
CURVE_MAX = 240
LABEL = "설명용, 판정 아님"
ID_RE = re.compile(r"^[A-Za-z0-9_.@~:\-]{1,80}$")
OWN_KINDS = ("strategy", "ds200", "reel")
TF_ORDER = ("5m", "15m", "30m", "1h", "4h")


def _r(x, n: int = 6):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None


def parse_ids(raw: Optional[str]) -> list:
    """The checked id list (order kept, duplicates dropped); a 400 for an empty, too long or malformed list."""
    out = []
    for x in (raw or "").split(","):
        x = x.strip()
        if not x:
            continue
        if not ID_RE.match(x):
            raise HTTPException(400, "비교할 매매법·계좌 이름이 올바르지 않습니다")
        if x not in out:
            out.append(x)
    if not out:
        raise HTTPException(400, "비교할 매매법이나 계좌를 1개 이상 골라 주세요")
    if len(out) > MAX_IDS:
        raise HTTPException(400, f"비교는 {MAX_IDS}개까지입니다")
    return out


def _tf_key(tf: str) -> int:
    return TF_ORDER.index(tf) if tf in TF_ORDER else 9


def _wallet(a: dict, init: float) -> float:
    w = a.get("wallet")
    return float(w) if w is not None else init


def realized_curve(events: list, start: dict, t0: int) -> tuple[list, list, float]:
    """The summed realized balance over time. events: (exit_time, account_id, equity_after) in exit-time order;
    start: {account_id: starting wallet}. Returns (t list, balance list, max drawdown from the running peak), the
    first point (t0, sum of starts)."""
    cur = dict(start)
    total = sum(cur.values())
    ts, vs = [t0], [total]
    peak, mdd = total, 0.0
    for t, aid, eq in events:
        if aid not in cur or eq is None:
            continue
        total += float(eq) - cur[aid]
        cur[aid] = float(eq)
        ts.append(int(t))
        vs.append(total)
        if total > peak:
            peak = total
        elif peak > 0:
            mdd = max(mdd, 1 - total / peak)
    return ts, vs, mdd


def max_drawdown(vs: list) -> float:
    """The deepest fall of a balance series from its running peak (0 for a series that never falls)."""
    peak, mdd = None, 0.0
    for v in vs:
        if peak is None or v > peak:
            peak = v
        elif peak > 0:
            mdd = max(mdd, 1 - v / peak)
    return mdd


def thin(ts: list, vs: list, n: int = CURVE_MAX) -> tuple[list, list]:
    """At most n points, evenly picked, the first and the last always kept."""
    if len(ts) <= n:
        return ts, vs
    idx = sorted({round(i * (len(ts) - 1) / (n - 1)) for i in range(n)})
    return [ts[i] for i in idx], [vs[i] for i in idx]


def flip_rank(item_ret: float, tfs: list, flips: list, init: float) -> Optional[dict]:
    """동전 봇 순위 (참고): each coin-flip seed (RANDOM_k) summed over the same timeframes; how many the item is above.
    flips: board rows of kind random. Seeds that miss one of the timeframes are left out."""
    seeds: dict = {}
    for f in flips:
        if f.get("timeframe") in tfs:
            seeds.setdefault(f.get("strategy"), {})[f["timeframe"]] = _wallet(f, init)
    rets = [sum(w.values()) / (init * len(tfs)) - 1 for w in seeds.values() if len(w) == len(tfs)]
    if not rets:
        return None
    return {"n": len(rets), "above": sum(1 for r in rets if item_ret > r), "tfs": list(tfs)}


def _flip_median(tf: str, flips: list, init: float) -> Optional[float]:
    xs = [_wallet(f, init) / init - 1 for f in flips if f.get("timeframe") == tf]
    return statistics.median(xs) if xs else None


def _y5(strategy: str, tfs: list) -> Optional[dict]:
    from .vs5y import five_year
    try:
        unit, rows, meta = five_year(strategy)
    except Exception:  # noqa: BLE001  (unreadable research files: no 5-year side, never a 500)
        return None
    if not unit:
        return None
    out = [{"tf": tf, **{k: _r(v) for k, v in (rows.get(tf) or {}).items()}} for tf in tfs if rows.get(tf)]
    m = meta or {}
    # the research's own exit when it is not the live accounts' (the page says so, like the strategy page's vs5y card)
    return {"unit": unit, "rows": out, "source": m.get("source"), "exit": m.get("exit"),
            "same_exits_as_live": m.get("same_exits_as_live")} if out else None


def item(c: sqlite3.Connection, key: str, board: dict, names: dict, now: int) -> dict:
    """One compared item (see the module note), or {"id", "unknown": True} / {"id", "dropped": "flip"}."""
    rows = board.get("accounts") or []
    init = float(board.get("initial") or 5000.0)
    if "@" in key:
        mine = [a for a in rows if a.get("account_id") == key]
        if not mine:
            return {"id": key, "unknown": True}
        kind = "account"
        if mine[0].get("kind") == "random":
            return {"id": key, "dropped": "flip"}
    else:
        mine = [a for a in rows if a.get("strategy") == key and a.get("kind") in OWN_KINDS]
        if not mine:
            if any(a.get("strategy") == key and a.get("kind") == "random" for a in rows):
                return {"id": key, "dropped": "flip"}
            return {"id": key, "unknown": True}
        kind = "strategy"
    mine.sort(key=lambda a: _tf_key(a.get("timeframe")))
    tfs = [a.get("timeframe") for a in mine]
    group = mine[0].get("group") or ("ds200" if mine[0].get("kind") == "ds200" else "core")
    strategy = mine[0].get("strategy")
    counts_only = any(a.get("kind") == "ds200" or a.get("group") == "ds200" for a in mine)
    base = {"id": key, "kind": kind, "group": group, "strategy": strategy,
            "name_ko": names.get(strategy) or strategy, "tfs": tfs, "accounts": len(mine),
            "trades": sum(int(a.get("trades") or 0) for a in mine),
            "open": sum(1 for a in mine if a.get("position")), "counts_only": counts_only,
            "small": sum(int(a.get("trades") or 0) for a in mine) < SMALL}
    if counts_only:
        # D10/D11: counts only on a mixed screen (no wallet, return, curve, rates or the 5-year return)
        return {**base, "by_tf": [{"tf": a.get("timeframe"), "account_id": a["account_id"], "trades": int(a.get("trades") or 0),
                                   "open": bool(a.get("position"))} for a in mine]}
    extra = group in ("extra", "other") or any(a.get("kind") in ("copy", "newlab") for a in mine)
    starts = {a["account_id"]: init for a in mine}
    t0 = min(int(a.get("created_ts") or now) for a in mine)
    ids = list(starts)
    q = (f"SELECT exit_time, account_id, equity_after FROM trades WHERE account_id IN ({','.join('?' * len(ids))}) "
         "ORDER BY exit_time, id")
    events = [(r[0], r[1], r[2]) for r in c.execute(q, ids)]
    ts, vs, _ = realized_curve(events, starts, t0)
    w0 = init * len(mine)
    w_now = sum(_wallet(a, init) for a in mine)
    ts.append(int(now))
    vs.append(w_now)
    # the drawdown of the line as drawn: its last point (the wallets now) counts too, so an entry fee or funding paid on
    # a position still open (already out of the wallet) is never a fall the chart shows and the number leaves out
    mdd = max_drawdown(vs)
    ts, vs = thin(ts, vs)
    wins = sum(int(a.get("wins") or 0) for a in mine)
    losses = sum(int(a.get("losses") or 0) for a in mine)
    gw = sum(float(a.get("gross_win") or 0.0) for a in mine)
    gl = sum(float(a.get("gross_loss") or 0.0) for a in mine)
    n = base["trades"]
    ret = w_now / w0 - 1
    flips = [a for a in rows if a.get("kind") == "random"]
    dds = [float(a["max_drawdown"]) for a in mine if a.get("max_drawdown") is not None]
    by_tf = []
    for a in mine:
        tn = int(a.get("trades") or 0)
        r_a = _wallet(a, init) / init - 1
        med = None if extra else _flip_median(a.get("timeframe"), [f for f in flips if (f.get("timeframe") == "5m") == (a.get("timeframe") == "5m")], init)
        by_tf.append({"tf": a.get("timeframe"), "account_id": a["account_id"], "trades": tn, "ret": _r(r_a),
                      "win_rate": _r((a.get("wins") or 0) / tn) if tn else None, "mdd": _r(a.get("max_drawdown")),
                      "open": bool(a.get("position")), "bust": bool(a.get("bust")),
                      "flip_med": _r(med), "vs": _r(r_a - med) if med is not None else None})
    return {**base, "ret": _r(ret), "w0": _r(w0, 2), "wallet": _r(w_now, 2), "pnl": _r(w_now - w0, 2),
            "curve": [_r(v / w0 - 1) for v in vs], "t": ts, "mdd": _r(mdd), "mdd_worst": _r(max(dds)) if dds else None,
            "wins": wins, "losses": losses, "win_rate": _r(wins / n) if n else None,
            "payoff": _r((gw / wins) / abs(gl / losses)) if wins and losses and gl else None,
            "pf": _r(gw / abs(gl)) if gl else None, "no_loss": n > 0 and not gl,
            "bust": sum(1 for a in mine if a.get("bust")), "extra": extra,
            "flip": None if extra else flip_rank(ret, tfs, [f for f in flips if (f.get("timeframe") == "5m") == ("5m" in tfs)], init),
            "y5": None if extra else _y5(strategy, tfs), "by_tf": by_tf}


def view(c: sqlite3.Connection, ids: list, board: dict, now: int) -> dict:
    names = {**(board.get("strategy_ko") or {}), **(board.get("names_ko") or {})}
    items = [item(c, k, board, names, now) for k in ids]
    return {"label": LABEL, "initial": board.get("initial") or 5000.0, "now": now, "small_n": SMALL, "max": MAX_IDS,
            "items": [x for x in items if not x.get("unknown") and not x.get("dropped")],
            "unknown": [x["id"] for x in items if x.get("unknown")],
            "dropped": [x["id"] for x in items if x.get("dropped")]}


def register(app, ctx) -> dict:
    from ..analysis import Heavy
    from ..app import json_finite
    heavy = Heavy(wait_s=WAIT_S)          # its own one-at-a-time worker: a long 조합 시너지 run never holds a comparison
    data = ctx.data

    def compute(ids: list) -> dict:
        with contextlib.closing(data.conn()) as c:
            return json_finite(view(c, ids, data.board(), int(time.time() * 1000)))

    @app.get("/api/v4/compare")
    def get_compare(ids: str = ""):
        """매매법 비교: 2-4 strategies / accounts side by side (background + cached TTL_S; DeepSeek counts only)."""
        picked = parse_ids(ids)
        try:
            return heavy.get("compare:" + ",".join(picked), TTL_S, lambda: compute(picked), wait_s=WAIT_S)
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None

    return {"routes": ["/api/v4/compare"], "heavy": heavy}
