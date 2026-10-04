"""Drawdown and bust risk (낙폭·파산 위험) of the paper v3 accounts (owners' request 2026-10-04). Code only, read-only on
paper3.db (``equity``: the engine's mark-to-market equity sampled every 5 minutes by accounts.AccountBook; ``trades``;
``state`` 'accounts' for the wallet and the bust flag). The staff read these numbers and interpret them; nothing here
trades or changes an account, and nothing here is the 30-day verdict (that is paperbot/checkpoint.py).

- ``curve_stats``  one equity curve (an account, or the sum of several): current drawdown from the peak, the deepest
                   drawdown (percent and dollars, its peak and trough time), days since the last peak, the longest
                   stretch under water, and the deepest drawdown reached in the last 7 days (from the peak so far).
- ``losing_streak`` / ``worst_day``  the longest run of losing trades (and the one going on now), the worst KST day of
                   closed-trade P&L.
- ``simulate``     Monte Carlo from the account's own closed trades in EQUITY terms (each trade's P&L / the equity
                   before it, so it scales with the account): ``PATHS`` bootstrap paths (seeded per account, numpy) of N
                   trades, N = the account's trades per 30 days so far. Probability of busting (the engine's
                   ``bust_below`` line, config.v3_settings: 10 USDT), of -30% and -50% from the current wallet at any
                   point, median and 5th-percentile end equity. Accounts with fewer than ``MIN_TRADES`` closed trades
                   are marked too few (no simulation). Trades are drawn a block of 2-4 at a time from the table of
                   every block (exactly the same distribution, fewer random draws). Measured on a synthetic 30-day
                   paper3.db (156 accounts): ~0.3 s for the Monte Carlo at ~1,300 closed trades a week, ~1.7 s at
                   ~7,000 a week; reading the 5-minute equity samples and the drawdowns ~1.5-1.8 s on top.
- ``sizing``       the scale k of each trade's equity return (k < 1 = a smaller position, the same trades) at which
                   P(-50% within ``SIZING_TRADES`` trades) < 1% (``SIZING_PATHS`` paths, the same for every k; the
                   path minimum is concave in k, so bisection is exact and only the undecided paths are re-walked;
                   k is rounded down); and half-Kelly from the win rate and the payoff in equity terms (clip at 0,
                   'no edge' when Kelly <= 0). Both '설명용': the original accounts' sizing is fixed for the 30-day run.
- ``table``        everything per account, per strategy (the sum of its five timeframe accounts) and per timeframe
                   (the sum of that timeframe's strategy accounts), the coin flips apart.
- ``survival_packet``  the Friday 낙폭·파산 위험 회의 packet (team:risk, trigger risk_review), with the backtest gap
                   (agents/btgap.py).
- ``strategy_brief`` / ``brief_many`` / ``week_brief`` / ``dash_strategy``  compact numbers for a strategy specialist,
                   the 14:00 ranking review, the Sunday weekly report and the dashboard's strategy tab.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import time
import zlib
from typing import Any, Iterable, Optional

import numpy as np

from ..config import V3_TRADE_TFS

DAY_MS = 86_400_000
KST_MS = 9 * 3_600_000
TFS = V3_TRADE_TFS                   # the run's timeframes (5m removed 2026-10-04, docs/paper-v3-rules-change-1.md)
MIN_TRADES = 20                  # fewer closed trades: too few to simulate
PATHS = 10_000                   # bootstrap paths per account
SEED = 20261004                  # + crc32(account id): every account its own fixed stream (order does not matter)
HORIZON_DAYS = 30                # N = the account's trades per 30 days so far
MAX_TRADES = 3_000               # cap on N (an account trading faster than this is simulated over this many)
CHUNK = 2_000_000                # paths x trades handled at once (memory)
DD_LEVELS = (0.30, 0.50)
SIZING_TRADES = 100              # sizing: P(-50% within this many trades) ...
SIZING_DD = 0.50
SIZING_P = 0.01                  # ... below this
SIZING_PATHS = 4_000             # paths of the sizing search (the same paths for every k; 1% = 40 paths)
SIZING_K_MAX = 4.0               # reported as 'k >= 4' when even that stays below 1%
SIZING_STEPS = 9                 # bisection steps on k in (0, SIZING_K_MAX]
LABEL = "설명용, 판정 아님"


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _r(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), n)


def bust_line() -> float:
    """The engine's bust line (config.v3_settings().bust_below: the account stops for good below this wallet)."""
    from ..config import v3_settings
    return float(v3_settings().bust_below)


def kst_label(ms: Optional[int], fmt: str = "%m/%d %H시") -> Optional[str]:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, dt.timezone.utc).strftime(fmt)


def kst_day(ms: int) -> str:
    return dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- drawdown of one curve
def curve_stats(ts: Iterable[int], eq: Iterable[float], now_ms: Optional[int] = None,
                week_ms: int = 7 * DAY_MS) -> dict:
    """Drawdown numbers of one equity curve (time-ordered samples; the first is the start). Fractions (0.25 = 25%)
    and dollars; days are float days. ``week_max_dd_pct``: the deepest drawdown from the peak so far reached in the
    ``week_ms`` before ``now_ms`` (default: the last sample)."""
    t = np.asarray(list(ts), dtype=np.int64)
    e = np.asarray(list(eq), dtype=np.float64)
    if not len(e):
        return {"samples": 0}
    peak = np.maximum.accumulate(e)
    dd_usd = peak - e
    dd = np.where(peak > 0, dd_usd / np.where(peak > 0, peak, 1.0), 0.0)
    i = int(np.argmax(dd))
    j = int(np.argmax(e[: i + 1] >= peak[i] - 1e-9))          # the peak this drawdown fell from
    at = np.nonzero(e >= peak - 1e-9)[0]                      # samples at the peak so far
    last_peak = int(at[-1])
    gaps = np.diff(t[at]) if len(at) > 1 else np.zeros(0, dtype=np.int64)
    gaps = gaps[np.diff(at) > 1] if len(at) > 1 else gaps
    longest = max(int(gaps.max()) if len(gaps) else 0, int(t[-1] - t[last_peak]))
    end = int(t[-1]) if now_ms is None else int(now_ms)
    wk = t >= end - week_ms
    out = {"samples": int(len(e)), "start": _r(e[0], 2), "equity": _r(e[-1], 2), "peak": _r(peak[-1], 2),
           "dd_now_pct": _r(dd[-1]), "dd_now_usd": _r(dd_usd[-1], 2),
           "max_dd_pct": _r(dd[i]), "max_dd_usd": _r(float(dd_usd.max()), 2),
           "max_dd_peak_ts": int(t[j]), "max_dd_trough_ts": int(t[i]), "max_dd_at": kst_label(int(t[i])),
           "days_since_peak": _r((t[-1] - t[last_peak]) / DAY_MS, 2),
           "longest_under_water_days": _r(longest / DAY_MS, 2),
           "under_water_share": _r(float((dd > 1e-9).mean()), 3),
           "week_max_dd_pct": _r(float(dd[wk].max())) if wk.any() else None,
           "change_pct": _r(e[-1] / e[0] - 1.0) if e[0] > 0 else None}
    return out


def losing_streak(pnls: Iterable[float]) -> dict:
    """The longest run of losing trades (P&L <= 0) in exit order, and the run going on at the last trade."""
    best = cur = 0
    for p in pnls:
        if p is not None and p <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return {"longest": best, "now": cur}


def worst_day(rows: Iterable[tuple]) -> Optional[dict]:
    """rows: (exit_time ms, pnl). The KST day with the lowest closed-trade P&L sum, and its trades."""
    days: dict = {}
    for t, p in rows:
        d = days.setdefault(kst_day(int(t)), [0.0, 0])
        d[0] += float(p)
        d[1] += 1
    if not days:
        return None
    day, (pnl, n) = min(days.items(), key=lambda kv: kv[1][0])
    return {"day": day, "pnl": round(pnl, 2), "trades": n}


# ---------------------------------------------------------------- Monte Carlo in equity terms
def equity_returns(pnls: Iterable[float], equity_after: Iterable[float]) -> np.ndarray:
    """Each closed trade's P&L as a fraction of the wallet before it (equity_after - pnl). Trades without a positive
    wallet before them are left out; a loss is floored at -100%."""
    p = np.asarray(list(pnls), dtype=np.float64)
    a = np.asarray(list(equity_after), dtype=np.float64)
    before = a - p
    ok = before > 0
    return np.maximum(p[ok] / before[ok], -1.0 + 1e-9)


def account_seed(key: str, seed: int = SEED) -> int:
    return (int(seed) + zlib.crc32(str(key).encode())) % (2 ** 32)


BLOCK_TABLE = 1 << 16            # the Monte Carlo draws b trades at once from all n^b combinations up to this many


def block_tables(lr: np.ndarray, b: int) -> tuple:
    """For b trades in a row drawn from ``lr``: every combination's sum and lowest partial sum (index = the b draws
    in base n, first draw most significant). One uniform index over n^b = b independent uniform draws (exact)."""
    s, m = lr.astype(np.float64), lr.astype(np.float64)
    for _ in range(b - 1):
        s2 = (s[:, None] + lr[None, :]).ravel()
        m = np.minimum(m[:, None], s2.reshape(len(s), len(lr))).ravel()
        s = s2
    return s.astype(np.float32), m.astype(np.float32)


def _paths_min_end(lr: np.ndarray, n_trades: int, paths: int, rng: np.random.Generator) -> tuple:
    """Bootstrap ``paths`` paths of ``n_trades`` log-returns from ``lr``: (lowest cumulative log equity per path
    (0 = the start), last one). Drawn ``b`` trades at a time from the tables of every b-trade combination (exact,
    fewer random draws) and summed in place."""
    n = len(lr)
    b = max([1] + [x for x in (2, 3, 4) if n ** x <= BLOCK_TABLE and x <= n_trades])
    cur = np.zeros(paths, dtype=np.float32)
    low = np.zeros(paths, dtype=np.float32)
    tabs = {b: block_tables(lr, b)} if b > 1 else {}
    tabs[1] = (lr.astype(np.float32), lr.astype(np.float32))
    plan = [(b, n_trades // b), (1, n_trades % b)] if b > 1 else [(1, n_trades)]
    tmp = np.empty(paths, dtype=np.float32)
    for size, count in plan:
        ssum, smin = tabs[size]
        step = max(1, CHUNK // max(1, paths))
        for t0 in range(0, count, step):
            idx = rng.integers(0, len(ssum), size=(min(step, count - t0), paths), dtype=np.int32)
            gs = np.take(ssum, idx)
            gm = gs if size == 1 else np.take(smin, idx)
            if size == 1:
                for row_s in gs:
                    cur += row_s
                    np.minimum(low, cur, out=low)
                continue
            for row_s, row_m in zip(gs, gm):
                np.add(cur, row_m, out=tmp)
                np.minimum(low, tmp, out=low)
                cur += row_s
    return low.astype(np.float64), cur.astype(np.float64)


def simulate(returns: Iterable[float], n_trades: int, start: float, bust_below: Optional[float] = None,
             paths: int = PATHS, seed: int = SEED, min_trades: int = MIN_TRADES) -> dict:
    """``paths`` bootstrap paths of ``n_trades`` trades drawn (with replacement) from the account's own equity
    returns, starting from ``start``. Probability that the wallet falls below ``bust_below`` (the engine's line), and
    30% / 50% below ``start``, at any point; median and 5th-percentile end equity."""
    r = np.asarray(list(returns), dtype=np.float64)
    bb = bust_line() if bust_below is None else float(bust_below)
    if len(r) < min_trades:
        return {"too_few": True, "trades": int(len(r)), "min_trades": min_trades}
    if start <= bb:
        return {"busted": True, "trades": int(len(r))}
    n = int(min(max(1, n_trades), MAX_TRADES))
    lr = np.log1p(r).astype(np.float32)
    lows, ends = _paths_min_end(lr, n, paths, np.random.default_rng(seed))
    end_eq = start * np.exp(ends)
    out = {"paths": paths, "trades_drawn_from": int(len(r)), "n_trades": n, "start": _r(start, 2),
           "p_bust": _r(float((lows < math.log(bb / start)).mean())),
           **{f"p_dd{int(lv * 100)}": _r(float((lows <= math.log(1 - lv)).mean())) for lv in DD_LEVELS},
           "median_end": _r(float(np.median(end_eq)), 2), "p5_end": _r(float(np.percentile(end_eq, 5)), 2)}
    out["median_end_pct"] = _r(out["median_end"] / start - 1.0)
    out["p5_end_pct"] = _r(out["p5_end"] / start - 1.0)
    if n_trades > MAX_TRADES:
        out["capped"] = True
    return out


def _low(r: np.ndarray, k: float, idx_t: np.ndarray, cols: Optional[np.ndarray] = None) -> np.ndarray:
    """Per path (the columns of ``idx_t``: trades x paths, or only ``cols``): the lowest cumulative log wallet
    (0 = the start) with every equity return x k."""
    lr = np.log1p(np.maximum(k * r, -1.0 + 1e-9)).astype(np.float32)
    g = np.take(lr, idx_t if cols is None else idx_t[:, cols])
    cur = np.zeros(g.shape[1], dtype=np.float32)
    low = np.zeros(g.shape[1], dtype=np.float32)
    for row in g:
        cur += row
        np.minimum(low, cur, out=low)
    return low


def p_drop(returns: Iterable[float], k: float, idx_t: np.ndarray, level: float = SIZING_DD) -> float:
    """P(the wallet falls ``level`` below its start along the paths ``idx_t`` (trades x paths)) with every equity
    return x k."""
    r = np.asarray(list(returns), dtype=np.float64)
    return float((_low(r, k, idx_t) <= math.log(1 - level)).mean())


def kelly(returns: Iterable[float]) -> dict:
    """Kelly from the win rate p and the payoff b = average win / |average loss| in equity terms: f = p - (1-p)/b is
    the share of the wallet to lose on an average losing trade; half-Kelly = f / 2, also as a multiple of the size now
    (f / 2 / |average loss|). Clipped at 0; f <= 0 = 'no edge'."""
    r = np.asarray(list(returns), dtype=np.float64)
    if not len(r):
        return {"trades": 0}
    w, lo = r[r > 0], r[r <= 0]
    p = len(w) / len(r)
    out = {"trades": int(len(r)), "win_rate": _r(p), "avg_win_eq": _r(float(w.mean()) if len(w) else None, 5),
           "avg_loss_eq": _r(float(lo.mean()) if len(lo) else None, 5)}
    if not len(lo) or float(lo.mean()) == 0.0:
        return {**out, "kelly": None, "note": "진 거래가 없어 계산 안 됨"}
    if not len(w):
        return {**out, "kelly": None, "half_kelly": 0.0, "no_edge": True, "note": "no edge (이긴 거래 없음)"}
    L = abs(float(lo.mean()))
    b = float(w.mean()) / L
    f = p - (1 - p) / b
    out.update(payoff=_r(b, 3), kelly=_r(f))
    if f <= 0:
        return {**out, "half_kelly": 0.0, "no_edge": True, "note": "no edge (켈리 0 이하: 이 승률·손익비로는 걸 몫이 없음)"}
    return {**out, "half_kelly": _r(f / 2), "half_kelly_x_now": _r(f / 2 / L, 2),
            "note": f"반 켈리: 진 거래 한 번에 자금의 {f / 2 * 100:.1f}%를 잃는 크기(지금 평균 {L * 100:.1f}%)"}


def sizing(returns: Iterable[float], seed: int = SEED, paths: int = SIZING_PATHS, trades: int = SIZING_TRADES,
           p_max: float = SIZING_P, k_max: float = SIZING_K_MAX, steps: int = SIZING_STEPS,
           min_trades: int = MIN_TRADES) -> dict:
    """The largest k (each trade's equity return x k: a position k times the size now, the same trades) with
    P(-50% within ``trades`` trades) < ``p_max``, by bisection on the same bootstrap paths (common random numbers);
    plus half-Kelly. '설명용': the accounts' sizing is fixed for the 30-day run."""
    r = np.asarray(list(returns), dtype=np.float64)
    if len(r) < min_trades:
        return {"too_few": True, "trades": int(len(r)), "label": LABEL}
    idx_t = np.random.default_rng(seed + 1).integers(0, len(r), size=(trades, paths), dtype=np.int32)
    c = math.log(1 - SIZING_DD)
    need = p_max * paths                     # falls allowed: fewer than this
    # Per path, the lowest log wallet g(k) is concave in k with g(0) = 0 (a minimum of sums of log(1 + k r)), so
    # (1) a path that falls at k also falls at every bigger k: P(k) only grows, and bisection is exact; (2)
    # g(k) <= k g(1) for k >= 1 (a sure fall when k g(1) <= log 0.5) and g(k) >= k g(1) for k <= 1 (no fall when
    # k g(1) > log 0.5). So after one pass at k = 1 each step only re-walks the paths it cannot settle.
    m1 = _low(r, 1.0, idx_t)
    h1 = m1 <= c
    p_now = float(h1.mean())
    nothing = np.zeros(paths, dtype=bool)

    def check(k: float, hit_lo: np.ndarray, maybe_hi: np.ndarray) -> tuple:
        """(fewer than ``need`` falls at k?, the falls at k: exact when True, else a superset)."""
        cand = maybe_hi & ~hit_lo
        if k >= 1.0:
            sure = cand & (k * m1 <= c)
            cand &= ~sure
        else:
            sure = nothing
            cand &= (k * m1 <= c)
        if int(hit_lo.sum() + sure.sum()) >= need:
            return False, hit_lo | sure | cand
        cols = np.nonzero(cand)[0]
        fell = nothing.copy()
        if len(cols):
            fell[cols[_low(r, k, idx_t, cols) <= c]] = True
        hits = hit_lo | sure | fell
        return int(hits.sum()) < need, hits

    if int(h1.sum()) < need:
        lo, hi, hit_lo, maybe_hi = 1.0, k_max, h1, ~nothing
        ok, h = check(k_max, hit_lo, maybe_hi)
        capped = ok
        maybe_hi = h
    else:
        lo, hi, hit_lo, maybe_hi, capped = 0.0, 1.0, nothing, h1, False
    if capped:
        k = k_max
    else:
        for _ in range(steps):
            mid = (lo + hi) / 2
            ok, h = check(mid, hit_lo, maybe_hi)
            if ok:
                lo, hit_lo = mid, h
            else:
                hi, maybe_hi = mid, h
        k = math.floor(lo * 100) / 100       # rounded down: the k reported is itself below the 1% line
    out = {"k": _r(k, 2), "k_ko": (f"지금 크기의 {k:.1f}배 이상" if capped else f"지금 크기의 {k:.2f}배"),
           "smaller": k < 1.0, "p_dd50_100_now": _r(p_now), "paths": paths, "trades": trades,
           "kelly": kelly(r), "label": LABEL}
    if capped:
        out["capped"] = True
    return out


# ---------------------------------------------------------------- reading paper3.db
def _accounts(paper_ro: sqlite3.Connection, kinds: tuple, strategies: Optional[list]) -> dict:
    sql = (f"SELECT account_id, kind, strategy, timeframe, created_ts FROM accounts "
           f"WHERE kind IN ({','.join('?' * len(kinds))})")
    args: list = list(kinds)
    if strategies:
        sql += f" AND strategy IN ({','.join('?' * len(strategies))})"
        args += list(strategies)
    return {a: {"kind": k, "strategy": s, "timeframe": tf, "created_ts": int(c or 0)}
            for a, k, s, tf, c in paper_ro.execute(sql, args)}


def _engines(paper_ro: sqlite3.Connection) -> dict:
    try:
        r = paper_ro.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        return (json.loads(r[0]) or {}).get("engines", {}) if r else {}
    except (sqlite3.Error, TypeError, ValueError):
        return {}


def _equity(paper_ro: sqlite3.Connection, ids: list, since_ms: int = 0) -> dict:
    """{account: (ts array, equity array)} from the ``equity`` table, in time order. One row per account
    (group_concat, parsed by numpy): ~4x faster than a row per sample for the original accounts' 5-minute samples."""
    out: dict = {}
    if not ids:
        return out
    sql = (f"SELECT account_id, group_concat(ts), group_concat(equity) FROM equity WHERE account_id IN "
           f"({','.join('?' * len(ids))}) AND ts >= ? GROUP BY account_id")
    for aid, ts, eq in paper_ro.execute(sql, [*ids, int(since_ms)]):
        t = np.fromstring(ts, dtype=np.int64, sep=",")
        e = np.fromstring(eq, dtype=np.float64, sep=",")
        if len(t) != len(e):
            continue
        order = np.argsort(t, kind="stable")       # group_concat keeps no promised order: sort by time
        out[aid] = (t[order], e[order])
    return out


def _trades(paper_ro: sqlite3.Connection, ids: list, until_ms: int) -> dict:
    """{account: [(exit_time, pnl, equity_after), ...]} in exit order."""
    out: dict = {}
    if not ids:
        return out
    sql = (f"SELECT account_id, exit_time, pnl, equity_after FROM trades WHERE account_id IN "
           f"({','.join('?' * len(ids))}) AND exit_time < ? ORDER BY exit_time, id")
    for a, t, p, e in paper_ro.execute(sql, [*ids, int(until_ms)]):
        out.setdefault(a, []).append((int(t), float(p), float(e)))
    return out


def initial_of(paper_ro: Optional[sqlite3.Connection]) -> float:
    from .digest import initial_equity
    return float(initial_equity(paper_ro))


def _curve_with_start(ts: np.ndarray, eq: np.ndarray, t0: int, e0: float) -> tuple:
    """The samples with the starting wallet in front (the run starts at its peak)."""
    if len(ts) and ts[0] <= t0:
        return ts, eq
    return np.concatenate([[t0], ts]), np.concatenate([[e0], eq])


def _group_curve(curves: dict, members: list, initial: float, created: dict) -> Optional[tuple]:
    """The sum of the members' equity at the times every member with samples has one, with the summed start."""
    have = [a for a in members if a in curves and len(curves[a][0])]
    if not have:
        return None
    ts = np.concatenate([curves[a][0] for a in have])
    eq = np.concatenate([curves[a][1] for a in have])
    u, inv = np.unique(ts, return_inverse=True)
    tot = np.bincount(inv, weights=eq, minlength=len(u))
    cnt = np.bincount(inv, minlength=len(u))
    ok = cnt == len(have)
    t0 = min(created.get(a, int(u[0])) for a in have)
    return _curve_with_start(u[ok], tot[ok], t0, initial * len(have))


def account_row(aid: str, meta: dict, curve: Optional[tuple], trades: list, eng: dict, initial: float,
                now_ms: int, bust_below: float, mc: bool = True, sizing_on: bool = True,
                paths: int = PATHS, seed: int = SEED) -> dict:
    """One account's numbers: drawdown, streak, worst day, bust flag, the Monte Carlo and the sizing."""
    row: dict = {"account": aid, "strategy": meta["strategy"], "timeframe": meta["timeframe"], "kind": meta["kind"],
                 "trades": len(trades)}
    created = meta["created_ts"] or (int(curve[0][0]) if curve is not None and len(curve[0]) else now_ms)
    if curve is not None and len(curve[0]):
        ts, eq = _curve_with_start(curve[0], curve[1], created, initial)
        row["curve"] = curve_stats(ts, eq, now_ms)
    else:
        row["curve"] = {"samples": 0}
    row["losing_streak"] = losing_streak(p for _t, p, _e in trades)
    row["worst_day"] = worst_day((t, p) for t, p, _e in trades)
    wallet = _f(eng.get("wallet"))
    if wallet is None:
        wallet = trades[-1][2] if trades else initial
    row["wallet"] = _r(wallet, 2)
    row["bust"] = bool(eng.get("bust")) or wallet < bust_below
    days = max(1.0, (now_ms - created) / DAY_MS)
    n30 = int(round(len(trades) * HORIZON_DAYS / days))
    row["trades_per_30d"] = n30
    if not mc:
        return row
    r = equity_returns((p for _t, p, _e in trades), (e for _t, _p, e in trades))
    s = account_seed(aid, seed)
    if row["bust"]:
        row["mc"] = {"busted": True, "trades": len(trades)}
    else:
        row["mc"] = simulate(r, max(1, n30), wallet, bust_below, paths=paths, seed=s)
    if sizing_on and not row["bust"]:
        row["sizing"] = sizing(r, seed=s)
    return row


def table(paper_ro: sqlite3.Connection, now_ms: int, strategies: Optional[Iterable[str]] = None,
          kinds: tuple = ("strategy", "random"), mc: bool = True, sizing_on: bool = True, paths: int = PATHS,
          seed: int = SEED) -> dict:
    """{"accounts": {id: account_row}, "strategies": {s: group}, "timeframes": {tf: group}, "coin_flips": group,
    "busted": [ids], "runtime_s"}. A group = the summed equity curve's numbers, the combined trades' streak and worst
    day, its accounts' busts, and the Monte Carlo per account summarised (highest and mean P(bust), the
    lowest sizing k)."""
    t0 = time.perf_counter()
    ss = list(strategies) if strategies is not None else None
    acc = _accounts(paper_ro, kinds, ss)
    ids = sorted(acc)
    initial = initial_of(paper_ro)
    bb = bust_line()
    curves = _equity(paper_ro, ids)
    trades = _trades(paper_ro, ids, now_ms)
    eng = _engines(paper_ro)
    rows = {a: account_row(a, acc[a], curves.get(a), trades.get(a, []), eng.get(a) or {}, initial, now_ms, bb,
                           mc=mc, sizing_on=sizing_on, paths=paths, seed=seed) for a in ids}
    created = {a: acc[a]["created_ts"] for a in ids}

    def group(members: list) -> dict:
        cv = _group_curve(curves, members, initial, created)
        tr = sorted((t for a in members for t in trades.get(a, [])), key=lambda x: x[0])
        out = {"accounts": len(members), "trades": len(tr),
               "curve": curve_stats(cv[0], cv[1], now_ms) if cv is not None else {"samples": 0},
               "losing_streak": losing_streak(p for _t, p, _e in tr), "worst_day": worst_day((t, p) for t, p, _e in tr),
               "busted": sorted(a for a in members if rows[a]["bust"])}
        sims = [(rows[a]["timeframe"], rows[a].get("mc") or {}) for a in members]
        sims = [(tf, m) for tf, m in sims if "p_bust" in m]
        out["simulated"] = len(sims)
        out["too_few"] = sum(1 for a in members if (rows[a].get("mc") or {}).get("too_few"))
        if sims:
            tf, m = max(sims, key=lambda x: x[1]["p_bust"])
            out["p_bust_max"] = {"timeframe": tf, "p": m["p_bust"]}
            out["p_bust_mean"] = _r(sum(m["p_bust"] for _tf, m in sims) / len(sims))
            tf50, m50 = max(sims, key=lambda x: x[1]["p_dd50"])
            out["p_dd50_max"] = {"timeframe": tf50, "p": m50["p_dd50"]}
        ks = [(rows[a]["timeframe"], rows[a]["sizing"]["k"]) for a in members
              if (rows[a].get("sizing") or {}).get("k") is not None]
        if ks:
            tf, k = min(ks, key=lambda x: x[1])
            out["sizing_k_min"] = {"timeframe": tf, "k": k}
        return out

    by_s: dict = {}
    by_tf: dict = {}
    flips = []
    for a in ids:
        m = acc[a]
        if m["kind"] == "strategy":
            by_s.setdefault(m["strategy"], []).append(a)
            by_tf.setdefault(m["timeframe"], []).append(a)
        elif m["kind"] == "random":
            flips.append(a)
    tf_key = lambda tf: TFS.index(tf) if tf in TFS else 9   # noqa: E731
    out = {"now": int(now_ms), "initial": initial, "bust_below": bb, "accounts": rows,
           "strategies": {s: group(sorted(v, key=lambda a: tf_key(acc[a]["timeframe"])))
                          for s, v in sorted(by_s.items())},
           "timeframes": {tf: group(v) for tf, v in sorted(by_tf.items(), key=lambda kv: tf_key(kv[0]))},
           "coin_flips": group(flips) if flips else None,
           "busted": sorted(a for a in ids if rows[a]["bust"])}
    out["runtime_s"] = round(time.perf_counter() - t0, 3)
    return out


# ---------------------------------------------------------------- compact forms
def tiny_account(row: dict) -> dict:
    """An account in a packet: drawdown now / deepest, P(bust), P(-50%), sizing k (None when too few)."""
    c, m, z = row.get("curve") or {}, row.get("mc") or {}, row.get("sizing") or {}
    out = {"trades": row["trades"], "dd_now": c.get("dd_now_pct"), "max_dd": c.get("max_dd_pct")}
    if row.get("bust"):
        out["bust"] = True
    elif m.get("too_few"):
        out["too_few"] = True
    else:
        out.update(p_bust=m.get("p_bust"), p_dd50=m.get("p_dd50"), k=z.get("k"))
    return out


def compact_group(g: Optional[dict]) -> dict:
    if not g:
        return {}
    c = g.get("curve") or {}
    out = {"trades": g.get("trades"), "equity": c.get("equity"), "dd_now_pct": c.get("dd_now_pct"),
           "dd_now_usd": c.get("dd_now_usd"), "max_dd_pct": c.get("max_dd_pct"), "max_dd_usd": c.get("max_dd_usd"),
           "max_dd_at": c.get("max_dd_at"), "days_since_peak": c.get("days_since_peak"),
           "longest_under_water_days": c.get("longest_under_water_days"),
           "week_max_dd_pct": c.get("week_max_dd_pct"), "losing_streak": (g.get("losing_streak") or {}).get("longest"),
           "worst_day": g.get("worst_day"), "busted": len(g.get("busted") or []),
           "simulated": g.get("simulated"), "too_few": g.get("too_few")}
    for k in ("p_bust_max", "p_bust_mean", "p_dd50_max", "sizing_k_min"):
        if k in g:
            out[k] = g[k]
    return out


HOW_TO_READ = (
    "모두 코드 계산, 비율은 0.25 = 25%. 자금 곡선 = 엔진이 5분마다 남긴 평가 자금(열린 포지션 포함, paper3.db equity). "
    "dd_now = 지금 최고점 대비 낙폭, max_dd = 지금까지 가장 깊은 낙폭(_usd는 달러, max_dd_at = 그 바닥 시각, 한국 시간), "
    "days_since_peak = 마지막 최고점 뒤 지난 날, longest_under_water_days = 최고점 아래에 가장 오래 머문 날 수, "
    "week_max_dd_pct = 지난 7일 중 가장 깊었던 낙폭(최고점은 실험 시작부터). 매매법 = 4개 봉 계좌의 합. "
    "losing_streak = 가장 긴 연속 손실 거래 수, worst_day = 끝난 거래 손익이 가장 나빴던 날(한국 시간). "
    "p_bust_max·p_dd50_max = 그 매매법 계좌 중 가장 높은 값과 그 봉, sizing_k_min = 가장 작은 k와 그 봉. "
    "by_tf(봉 계좌): n = 끝난 거래 수, mdd = 가장 깊은 낙폭, pb = 파산 확률, p50 = -50% 확률, k = 크기 k, few = 20건 미만, "
    "bust = 파산(by_tf는 낙폭이 깊은 12개와 파산·파산 확률 5% 이상·백테스트보다 나쁜 매매법에만). "
    "bt = 실전 대 5년 백테스트 판정(worse·similar·better·too_few, backtest_gap). "
    "몬테카를로: 계좌마다 지금까지 끝난 거래의 '자금 대비 손익'(손익 ÷ 그 거래 전 자금)을 무작위로 다시 뽑아(복원 추출) "
    "앞으로 30일(지금까지의 30일당 거래 수만큼)을 10,000번 흉내 냄. p_bust = 자금이 엔진의 파산선(bust_below) 아래로 "
    "떨어진 비율, p_dd30·p_dd50 = 지금 자금에서 30%·50% 아래로 한 번이라도 내려간 비율, median_end·p5_end = 끝 자금의 "
    "중앙값·하위 5%. 거래 20건 미만 계좌는 too_few(흉내 내지 않음). 과거 거래가 앞으로도 같은 모양으로 나온다는 "
    "가정이라 실제 위험보다 작거나 클 수 있음. sizing.k = 같은 거래를 k배 크기로 했다면 100거래 안에 -50%가 될 확률이 "
    "1% 아래인 가장 큰 k(1보다 작으면 지금보다 작게). kelly = 승률과 손익비(자금 대비)로 계산한 켈리, half_kelly = 그 절반"
    "(0 이하면 no edge). 크기 숫자는 설명용: 156개 계좌의 크기 규칙은 30일 동안 고정이고 바꾸려면 두 분 결정과 규칙 "
    "v4가 필요")


def _r3(x: Any) -> Any:
    return round(x, 3) if isinstance(x, float) else x


def short_account(row: dict) -> dict:
    """An account in the meeting packet, shortest form: n = closed trades, mdd = deepest drawdown, pb = P(bust),
    p50 = P(-50%), k = sizing k; ``few`` = under MIN_TRADES (no simulation), ``bust`` = busted."""
    c, m, z = row.get("curve") or {}, row.get("mc") or {}, row.get("sizing") or {}
    out = {"n": row["trades"], "mdd": _r3(c.get("max_dd_pct"))}
    if row.get("bust"):
        out["bust"] = True
    elif m.get("too_few"):
        out["few"] = True
    else:
        out.update(pb=_r3(m.get("p_bust")), p50=_r3(m.get("p_dd50")), k=z.get("k"))
    return out


BY_TF_ROWS = 12
PACKET_KEYS = ("trades", "dd_now_pct", "max_dd_pct", "max_dd_usd", "max_dd_at", "days_since_peak", "week_max_dd_pct",
               "losing_streak", "worst_day", "busted", "p_bust_max", "p_dd50_max", "sizing_k_min")


def _group_rows(tab: dict, names_ko: dict, flags: Optional[dict] = None) -> list[dict]:
    """The meeting packet's strategy rows, deepest drawdown first: the four accounts' sum in short, each
    timeframe account in the shortest form, the backtest gap flag (``bt``)."""
    rows = []
    for s, g in tab["strategies"].items():
        cg = compact_group(g)
        row = {"strategy": s, "name_ko": names_ko.get(s, s), **{k: _r3(cg[k]) for k in PACKET_KEYS if k in cg}}
        if isinstance(row.get("worst_day"), dict):
            row["worst_day"] = {k: row["worst_day"][k] for k in ("day", "pnl")}
        tf_of = {a: r["timeframe"] for a, r in tab["accounts"].items() if r["strategy"] == s and r["kind"] == "strategy"}
        mine = sorted(tf_of, key=lambda a: TFS.index(tf_of[a]) if tf_of[a] in TFS else 9)
        row["by_tf"] = {tab["accounts"][a]["timeframe"]: short_account(tab["accounts"][a]) for a in mine}
        if flags and s in flags:
            row["bt"] = flags[s]["total"]
        rows.append(row)
    rows.sort(key=lambda r: (-(r.get("max_dd_pct") or 0.0), r["strategy"]))
    # the timeframe accounts only where they matter (packet size): the deepest ``BY_TF_ROWS`` strategies and any
    # with a bust, P(bust) >= 5% or a live record significantly worse than its backtest
    for i, r in enumerate(rows):
        hot = r.get("busted") or (r.get("p_bust_max") or {}).get("p", 0.0) >= 0.05 or r.get("bt") == "worse"
        if i >= BY_TF_ROWS and not hot:
            r.pop("by_tf", None)
    return rows


def _names(names_ko: Optional[dict]) -> dict:
    if names_ko is not None:
        return dict(names_ko)
    from .roster3 import STRATEGY_KO
    return dict(STRATEGY_KO)


def survival_packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, names_ko: Optional[dict] = None,
                    cards_path: Optional[str] = None) -> dict:
    """The Friday 낙폭·파산 위험 회의 packet: every strategy (worst deepest drawdown first) with its four accounts in
    short, the timeframes, the coin flips, the busted accounts, and the backtest gap (agents/btgap.py)."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    names = _names(names_ko)
    try:
        tab = table(paper_ro, now_ms)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    sims = [r for r in tab["accounts"].values() if r["kind"] == "strategy" and "p_bust" in (r.get("mc") or {})]
    from . import btgap as BG
    try:
        gap = BG.packet(paper_ro, now_ms, cards_path=cards_path, names_ko=names)
    except (sqlite3.Error, OSError, KeyError, TypeError, ValueError) as exc:
        gap = {"error": f"백테스트 비교를 만들지 못함: {type(exc).__name__}"}
    rows = _group_rows(tab, names, gap.pop("flags", None))
    return {"label": LABEL, "now": int(now_ms), "initial": tab["initial"], "bust_below": tab["bust_below"],
            "settings": {"paths": PATHS, "horizon_days": HORIZON_DAYS, "min_trades": MIN_TRADES,
                         "sizing": {"trades": SIZING_TRADES, "drop": SIZING_DD, "p_max": SIZING_P,
                                    "paths": SIZING_PATHS}},
            "summary": {"strategies": len(rows), "accounts_simulated": len(sims),
                        "accounts_too_few": sum(1 for r in tab["accounts"].values() if r["kind"] == "strategy"
                                                and (r.get("mc") or {}).get("too_few")),
                        "busted": len([a for a in tab["busted"] if tab["accounts"][a]["kind"] == "strategy"]),
                        "p_bust_over_5pct": sum(1 for r in sims if r["mc"]["p_bust"] >= 0.05),
                        "p_dd50_over_10pct": sum(1 for r in sims if r["mc"]["p_dd50"] >= 0.10),
                        "sizing_k_below_1": sum(1 for r in sims if (r.get("sizing") or {}).get("k") is not None
                                                and r["sizing"]["k"] < 1.0),
                        "kelly_no_edge": sum(1 for r in sims
                                             if ((r.get("sizing") or {}).get("kelly") or {}).get("no_edge"))},
            "strategies": rows,
            "timeframes": {tf: compact_group(g) for tf, g in tab["timeframes"].items()},
            "coin_flips": compact_group(tab["coin_flips"]),
            "busted_accounts": [a for a in tab["busted"] if tab["accounts"][a]["kind"] == "strategy"],
            "backtest_gap": gap, "how_to_read": HOW_TO_READ, "runtime_s": tab["runtime_s"],
            "note": ("모두 코드 계산(설명용, 판정 아님). 30일 판정은 체크포인트(paperbot/checkpoint.py)가 함. 계좌의 규칙·크기는 "
                     "30일 동안 고정이라 이 숫자로 바꾸지 않음")}


def strategy_brief(paper_ro: Optional[sqlite3.Connection], strategy: str, now_ms: int,
                   cards_path: Optional[str] = None) -> dict:
    """A strategy specialist's own numbers: its four accounts' sum (drawdown now and deepest), each account's
    drawdown, P(bust), P(-50%), sizing k and half-Kelly, and its backtest gap flag per timeframe."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    try:
        tab = table(paper_ro, now_ms, strategies=[strategy], kinds=("strategy",))
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    g = tab["strategies"].get(strategy)
    by_tf = {}
    for a, r in sorted(tab["accounts"].items()):
        t = tiny_account(r)
        kl = (r.get("sizing") or {}).get("kelly") or {}
        if kl.get("trades"):
            t["half_kelly"] = kl.get("half_kelly")
            if kl.get("no_edge"):
                t["no_edge"] = True
        by_tf[r["timeframe"]] = t
    from . import btgap as BG
    try:
        gap = BG.strategy_flags(paper_ro, strategy, now_ms, cards_path=cards_path)
    except (sqlite3.Error, OSError, KeyError, TypeError, ValueError) as exc:
        gap = {"error": f"백테스트 비교를 만들지 못함: {type(exc).__name__}"}
    return {"total": compact_group(g), "by_tf": by_tf, "backtest_gap": gap, "label": LABEL,
            "note": ("코드 계산: dd_now·max_dd = 최고점 대비 지금·가장 깊은 낙폭, p_bust = 지금까지 거래로 30일을 10,000번 "
                     "흉내 냈을 때 파산 비율(20건 미만은 too_few), k = 100거래 안에 -50% 확률이 1% 아래인 크기(지금의 k배), "
                     "half_kelly(no_edge면 걸 몫 없음). 크기 규칙은 30일 동안 고정: 설명용, 판정 아님")}


def brief_many(paper_ro: Optional[sqlite3.Connection], strategies: Iterable[str], now_ms: int) -> dict:
    """{strategy: deepest drawdown and P(bust)} for the 14:00 ranking review's picked strategies."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    ss = list(strategies)
    if not ss:
        return {"strategies": {}}
    try:
        tab = table(paper_ro, now_ms, strategies=ss, kinds=("strategy",), sizing_on=False)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    out = {}
    for s in ss:
        g = compact_group(tab["strategies"].get(s))
        out[s] = {k: g.get(k) for k in ("max_dd_pct", "max_dd_usd", "dd_now_pct", "p_bust_max", "p_bust_mean",
                                        "busted", "simulated", "too_few") if k in g}
    return {"strategies": out, "note": ("max_dd_pct = 4개 봉 계좌 합의 가장 깊은 낙폭, p_bust_max = 계좌별 30일 몬테카를로 "
                                        "파산 확률 중 가장 높은 것(거래 20건 이상 계좌만). 코드 계산, 설명용")}


def week_brief(paper_ro: Optional[sqlite3.Connection], now_ms: int, names_ko: Optional[dict] = None, k: int = 3,
               cards_path: Optional[str] = None) -> dict:
    """The Sunday report's line: the ``k`` strategies whose summed equity went deepest under its peak in the last 7
    days, and how many strategies are significantly worse than their 5-year backtest."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    names = _names(names_ko)
    tab = table(paper_ro, now_ms, kinds=("strategy",), mc=False)
    rows = [(s, (g.get("curve") or {}).get("week_max_dd_pct")) for s, g in tab["strategies"].items()]
    rows = sorted([x for x in rows if x[1]], key=lambda x: -x[1])[:k]
    out = {"deepest": [{"strategy": s, "name_ko": names.get(s, s), "week_max_dd_pct": v} for s, v in rows]}
    from . import btgap as BG
    try:
        sm = BG.packet(paper_ro, now_ms, cards_path=cards_path, names_ko=names)["summary"]
        out["backtest"] = {"tested": sm["strategies_tested"], "worse": sm["strategies_worse"]}
    except (sqlite3.Error, OSError, KeyError, TypeError, ValueError):
        pass
    return out


def dash_strategy(paper_ro: sqlite3.Connection, strategy: str, now_ms: int) -> dict:
    """The strategy tab's 최대 낙폭 and 파산 확률: the four accounts' summed curve and the highest account P(bust)
    among the accounts with >= ``MIN_TRADES`` closed trades (None when none has)."""
    tab = table(paper_ro, now_ms, strategies=[strategy], kinds=("strategy",), sizing_on=False)
    g = tab["strategies"].get(strategy) or {}
    c = g.get("curve") or {}
    out = {"max_dd_pct": c.get("max_dd_pct"), "max_dd_usd": c.get("max_dd_usd"), "max_dd_at": c.get("max_dd_at"),
           "dd_now_pct": c.get("dd_now_pct"), "busted": len(g.get("busted") or []),
           "simulated": g.get("simulated", 0), "min_trades": MIN_TRADES, "paths": PATHS, "horizon_days": HORIZON_DAYS}
    if g.get("p_bust_max"):
        out["p_bust"] = g["p_bust_max"]["p"]
        out["p_bust_tf"] = g["p_bust_max"]["timeframe"]
    return out
