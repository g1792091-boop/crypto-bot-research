"""How much the paper v3 accounts overlap (read-only, descriptive).

The live bot may later run several strategies together in one exchange account.
Strategies that enter the same coin in the same direction at the same time win
and lose together, so a "portfolio" of them is really one bet. This module
measures that from paper3.db (opened read-only by the caller); it writes nothing.

    python -m paperbot.overlap --db paper3.db --days 7      # JSON report

Definitions (all over one time window, ``days`` back from the last equity sample):

- Grid: the 5-minute equity points (``equity`` table, sampled every 5 min).
  An account *holds* (symbol, side) at point t when a trade on it has
  entry_time <= t < exit_time (closed trades from ``trades``; the position still
  open is taken from the latest ``state['accounts']`` snapshot).
- Same-time exposure: at each point, per (symbol, side), the number of strategy
  accounts holding it. Coin-flip accounts (kind 'random') are not counted, nor are copy
  accounts (kind 'copy': one strategy with one rule changed, it repeats its parent's
  entries); new-strategy accounts (kind 'newlab') count as strategy accounts.
  "Crowding" at a point = the largest of those counts.
- Pair similarity (every pair of accounts):
  * ``corr``: Pearson correlation of hourly equity returns (equity at each full
    hour; a return is used only when both accounts have it);
  * ``same_time``: share of the common 5-minute points at which both hold the same
    symbol + side; ``same_of_busy``: the same count over the points where at least
    one of the two holds a position.
  A pair is *sufficient* only when the two share >= MIN_DAYS days of data
  (first to last common point, >= MIN_COVERAGE of those 5-minute points present)
  and each account closed >= MIN_TRADES trades in the window; otherwise it is
  reported as insufficient and never used for groups.
- Groups: complete-linkage clusters of strategy accounts: every pair inside a
  group is sufficient and has corr >= GROUP_CORR. Coin-flip accounts are left out
  of the clustering; their pair correlations are reported as a chance baseline. Copy
  accounts are left out too; ``copies`` gives each one's correlation with its parent.
- Combined what-if (per group, descriptive): every member keeps its own wallet and
  the equity curves are added up (equal weight). Max drawdown of that sum vs the
  members' average max drawdown (5-minute points), and the worst UTC day of the
  sum vs the members' worst days added up. Ratio near 1 = no spreading of risk.

Everything is vectorised with numpy (a 4-week window of 195 accounts takes well
under a second, see tests/test_overlap.py for the timing check).
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

STEP_MS = 300_000            # equity sampling (AccountBook.equity_every_ms in the live run)
HOUR_MS = 3_600_000
DAY_MS = 86_400_000

MIN_DAYS = 7.0               # common data a pair needs (first to last shared 5-minute point)
MIN_COVERAGE = 0.9           # ... with at least this share of those 5-minute points present
MIN_TRADES = 20              # closed trades each account needs in the window
GROUP_CORR = 0.7             # every pair inside a group: hourly-return correlation >= this
TOP_MOMENTS = 10
MOMENT_GAP_MS = HOUR_MS      # top moments of one coin+side at least this far apart
CROWD_BUCKETS = ((0, 0), (1, 1), (2, 4), (5, 9), (10, 19), (20, None))

RULES = {
    "grid_minutes": STEP_MS // 60_000,
    "return_freq": "1h",
    "min_days": MIN_DAYS,
    "min_coverage": MIN_COVERAGE,
    "min_trades": MIN_TRADES,
    "group_corr": GROUP_CORR,
    "group_rule": "complete linkage: every pair in a group is sufficient and has corr >= group_corr",
    "exposure_counts": "strategy and new-strategy accounts only (coin-flip accounts excluded; copy accounts "
                       "excluded too: a copy repeats its parent's entries)",
    "descriptive": True,
}


@dataclass
class Window:
    start: int                       # first grid point (ms, inclusive)
    end: int                         # last grid point (ms, inclusive)
    ts: np.ndarray                   # grid points, (T,)
    ids: list[str]                   # accounts, column order
    meta: list[dict]                 # strategy / timeframe / kind per column
    equity: np.ndarray               # (T, N) float, NaN where no sample
    pos: np.ndarray                  # (T, N) int16: 0 flat, else 1 + 2*symbol_idx + (side > 0)
    symbols: list[str]
    trades: np.ndarray               # (N,) closed trades with exit_time in the window
    is_random: np.ndarray            # (N,) bool
    first: np.ndarray = field(default=None)   # (N,) first / last grid index with data (-1 when none)
    last: np.ndarray = field(default=None)
    is_copy: np.ndarray = field(default=None)  # (N,) bool: copy accounts (kind 'copy'); None = none

    def excluded(self) -> np.ndarray:
        """Accounts left out of exposure and clustering: coin-flip and copy accounts."""
        return self.is_random | (self.is_copy if self.is_copy is not None else np.zeros_like(self.is_random))

    def code(self, symbol: str, side: int) -> int:
        return 1 + 2 * self.symbols.index(symbol) + (1 if side > 0 else 0)

    def decode(self, code: int) -> tuple[str, int]:
        return self.symbols[(code - 1) // 2], (1 if (code - 1) % 2 else -1)


# ---------------------------------------------------------------- loading
def _q(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> sqlite3.Cursor:
    """Plain tuples whatever row factory the caller's connection has (the dashboard uses sqlite3.Row)."""
    cur = conn.cursor()
    cur.row_factory = None
    return cur.execute(sql, args)


def last_equity_ts(conn: sqlite3.Connection) -> Optional[int]:
    r = _q(conn, "SELECT MAX(ts) FROM equity").fetchone()
    return None if r is None or r[0] is None else int(r[0])


def load_window(conn: sqlite3.Connection, days: float = 7, end: Optional[int] = None) -> Optional[Window]:
    """Equity and positions of every account on the 5-minute grid of the last ``days``
    days up to ``end`` (default: the last equity sample). None when there is no equity."""
    if end is None:
        end = last_equity_ts(conn)
        if end is None:
            return None
    end = int(end) // STEP_MS * STEP_MS
    start = end - int(round(days * DAY_MS))
    start = -(-start // STEP_MS) * STEP_MS
    ts = np.arange(start, end + 1, STEP_MS, dtype=np.int64)
    T = len(ts)

    accts = _q(conn, "SELECT account_id, strategy, timeframe, kind, parent FROM accounts ORDER BY rowid").fetchall()
    ids = [a[0] for a in accts]
    col = {a: j for j, a in enumerate(ids)}
    meta = [{"strategy": a[1], "timeframe": a[2], "kind": a[3], "parent": a[4]} for a in accts]
    N = len(ids)

    eq = np.full((T, N), np.nan)
    for j, aid in enumerate(ids):          # one indexed range scan per account (PRIMARY KEY account_id, ts)
        rows = _q(conn, "SELECT ts, equity FROM equity WHERE account_id = ? AND ts >= ? AND ts <= ? ORDER BY ts",
                  (aid, start, end)).fetchall()
        if rows:
            a = np.asarray(rows, dtype=np.float64)
            eq[((a[:, 0].astype(np.int64) - start) // STEP_MS), j] = a[:, 1]

    try:
        trows = _q(
            conn, "SELECT account_id, symbol, entry_time, exit_time, json_extract(data, '$.side') FROM trades "
            "WHERE exit_time > ? AND entry_time <= ?", (start, end)).fetchall()
    except sqlite3.OperationalError:       # no JSON1 in this SQLite build
        trows = [(a, s, e, x, json.loads(d).get("side")) for a, s, e, x, d in _q(
            conn, "SELECT account_id, symbol, entry_time, exit_time, data FROM trades "
            "WHERE exit_time > ? AND entry_time <= ?", (start, end))]
    intervals = [(r[0], r[1], int(r[2]), int(r[3]), int(r[4] or 0)) for r in trows]
    st = _q(conn, "SELECT data FROM state WHERE k = 'accounts'").fetchone()
    if st is not None:
        try:
            engines = json.loads(st[0]).get("engines", {})
        except (TypeError, ValueError):
            engines = {}
        for aid, e in engines.items():
            p = (e or {}).get("position")
            if p and p.get("entry_time") is not None and int(p["entry_time"]) <= end:
                intervals.append((aid, p["symbol"], int(p["entry_time"]), end + 1, int(p.get("side") or 0)))

    symbols = sorted({iv[1] for iv in intervals})
    sidx = {s: i for i, s in enumerate(symbols)}
    pos = np.zeros((T, N), dtype=np.int16)
    for aid, sym, t0, t1, side in intervals:
        j = col.get(aid)
        if j is None or side == 0:
            continue
        i0 = max(0, -(-(t0 - start) // STEP_MS))
        i1 = min(T, -(-(t1 - start) // STEP_MS))
        if i1 > i0:
            pos[i0:i1, j] = 1 + 2 * sidx[sym] + (1 if side > 0 else 0)

    trades = np.zeros(N, dtype=np.int64)
    for aid, n in _q(conn, "SELECT account_id, COUNT(*) FROM trades WHERE exit_time >= ? AND exit_time <= ? "
                        "GROUP BY account_id", (start, end)):
        if aid in col:
            trades[col[aid]] = n

    has = ~np.isnan(eq)
    anyd = has.any(0)
    first = np.where(anyd, has.argmax(0), -1)
    last = np.where(anyd, T - 1 - has[::-1].argmax(0), -1)
    is_random = np.array([m["kind"] == "random" for m in meta], dtype=bool)
    is_copy = np.array([m["kind"] == "copy" for m in meta], dtype=bool)
    return Window(start, end, ts, ids, meta, eq, pos, symbols, trades, is_random, first, last, is_copy)


# ---------------------------------------------------------------- same-time exposure
def _bucket_label(lo: int, hi: Optional[int]) -> str:
    return str(lo) if hi == lo else (f"{lo}+" if hi is None else f"{lo}-{hi}")


def exposure(w: Window, top: int = TOP_MOMENTS, gap_ms: int = MOMENT_GAP_MS) -> dict:
    """Per 5-minute point and (symbol, side): how many strategy accounts hold it (coin-flip and copy accounts
    are not counted)."""
    K = 1 + 2 * len(w.symbols)
    S = ~w.excluded()
    P = w.pos[:, S].astype(np.int64)
    T = len(w.ts)
    live = ~np.isnan(w.equity[:, S]).all(1) if S.any() else np.zeros(T, bool)   # bot was writing then
    counts = np.bincount((np.arange(T)[:, None] * K + P).ravel(), minlength=T * K).reshape(T, K)
    counts[:, 0] = 0                       # flat is not a position
    crowd = counts.max(1)
    pts = int(live.sum())
    out = {"points": pts, "strategy_accounts": int(S.sum()), "max": None, "distribution": [],
           "percentiles": {}, "by_symbol": [], "top": []}
    if pts == 0:
        return out
    c = crowd[live]
    for lo, hi in CROWD_BUCKETS:
        m = (c >= lo) if hi is None else ((c >= lo) & (c <= hi))
        out["distribution"].append({"bucket": _bucket_label(lo, hi), "share": float(m.mean())})
    out["percentiles"] = {f"p{q}": float(np.percentile(c, q)) for q in (50, 90, 99)}
    out["share_ge5"] = float((c >= 5).mean())
    out["holding_max"] = int((P != 0).sum(1)[live].max())
    for k in range(1, K):
        ck = counts[live, k]
        if ck.max() == 0:
            continue
        sym, side = w.decode(k)
        out["by_symbol"].append({"symbol": sym, "side": side, "max": int(ck.max()), "mean": float(ck.mean()),
                                 "share_ge5": float((ck >= 5).mean())})
    out["by_symbol"].sort(key=lambda r: (-r["max"], -r["mean"]))

    # top moments: highest counts, at most one per coin+side within gap_ms
    cl = counts.copy()
    cl[~live] = 0
    cand: list[tuple[int, int, int, int]] = []             # (count, t, k, episode minutes)
    for k in range(1, K):
        col = cl[:, k].copy()
        for _ in range(top):
            t = int(len(col) - 1 - np.argmax(col[::-1]))   # highest count, the latest such point
            if col[t] <= 0:
                break
            # the episode: the run around t while at least half that many accounts held it
            low = np.flatnonzero(cl[:, k] < max(1, -(-int(col[t]) // 2)))
            a = int(low[low < t].max()) + 1 if (low < t).any() else 0
            b = int(low[low > t].min()) if (low > t).any() else T
            cand.append((int(col[t]), t, k, (b - a) * STEP_MS // 60_000))
            col[a:b] = 0
            col[np.abs(w.ts - w.ts[t]) < gap_ms] = 0
    cand.sort(key=lambda c: (-c[0], -c[1]))
    sid = np.flatnonzero(S)
    for _, t, k, minutes in cand[:top]:
        sym, side = w.decode(k)
        members = [w.ids[j] for j in sid[w.pos[t, sid] == k]]
        strategies = sorted({w.meta[w.ids.index(a)]["strategy"] for a in members})
        out["top"].append({"ts": int(w.ts[t]), "symbol": sym, "side": side, "count": int(counts[t, k]),
                           "strategies": len(strategies), "minutes": int(minutes), "accounts": members})
    if out["top"]:
        m = out["top"][0]
        out["max"] = {k: m[k] for k in ("ts", "symbol", "side", "count")}
    return out


# ---------------------------------------------------------------- pair similarity
def _gram(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a.T @ b. The transposed operand is copied first: numpy sends ``x.T @ x`` to a
    symmetric BLAS routine that is several times slower than a plain product."""
    return np.ascontiguousarray(a.T) @ b


def hourly_returns(w: Window) -> np.ndarray:
    """(H-1, N) returns between full-hour equity samples; NaN where either end is missing."""
    e = w.equity[(w.ts % HOUR_MS) == 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = e[1:] / e[:-1] - 1.0
    r[~np.isfinite(r)] = np.nan
    r[(e[:-1] <= 0)] = np.nan
    return r


def pairwise_corr(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pearson correlation of every column pair over the rows where both are present
    (NaN = missing), plus the number of such rows. Constant columns give NaN."""
    m = (~np.isnan(x)).astype(np.float64)
    x0 = np.where(m > 0, x, 0.0)
    mu = x0.sum(0) / np.maximum(m.sum(0), 1)
    x0 = np.where(m > 0, x0 - mu, 0.0)       # centre first: fewer cancellation errors
    n = _gram(m, m)
    sx = _gram(x0, m)                        # sx[i, j] = sum of x_i where both present
    sxx = _gram(x0 * x0, m)
    sxy = _gram(x0, x0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cov = n * sxy - sx * sx.T
        var = (n * sxx - sx * sx) * (n * sxx - sx * sx).T
        c = cov / np.sqrt(var)
    c[(n < 3) | ~np.isfinite(c) | (var <= 1e-24 * np.maximum(n, 1) ** 4)] = np.nan
    return np.clip(c, -1.0, 1.0), n


def _cooccur(t: np.ndarray, j: np.ndarray, rows: np.ndarray, nrows: int, n: int) -> np.ndarray:
    """(n, n) counts of rows shared by two columns, from the (row, column) cells that are set.
    Sparse: no BLAS threads, so it stays fast on a busy server."""
    from scipy import sparse
    o = sparse.csr_matrix((np.ones(len(t), dtype=np.float64), (rows, j)), shape=(nrows, n))
    return (o.T @ o).toarray()


def same_side(w: Window) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per pair, numbers of 5-minute points where (both hold the same symbol+side,
    at least one holds a position, both have data). Only points with data count."""
    has = ~np.isnan(w.equity)
    P = np.where(has, w.pos, 0).astype(np.int64)
    T, N = P.shape
    K = 1 + 2 * len(w.symbols)
    t, j = np.nonzero(P)
    both = _cooccur(t, j, t * K + P[t, j], T * K, N)
    miss = ~has                                   # mostly empty: common = T - miss_i - miss_j + both missing
    t, j = np.nonzero(miss)
    m = miss.sum(0).astype(np.float64)
    common = T - m[:, None] - m[None, :] + _cooccur(t, j, t, T, N)
    flat = has & (P == 0)                         # both busy = common - flat_i - flat_j + both flat
    t, j = np.nonzero(flat)
    f = flat.sum(0).astype(np.float64)
    both_busy = common - f[:, None] - f[None, :] + _cooccur(t, j, t, T, N)
    nb = (P != 0).sum(0).astype(np.float64)
    either = nb[:, None] + nb[None, :] - both_busy
    return both, either, common


def similarity(w: Window, min_days: float = MIN_DAYS, min_trades: int = MIN_TRADES,
               min_coverage: float = MIN_COVERAGE) -> dict:
    """Pair matrices over all accounts (strategy and coin-flip). Keys: corr, n_returns,
    same_time, same_of_busy, common_days, sufficient (all (N, N))."""
    corr, nret = pairwise_corr(hourly_returns(w))
    both, either, common = same_side(w)
    with np.errstate(divide="ignore", invalid="ignore"):
        same_time = np.where(common > 0, both / common, np.nan)
        same_busy = np.where(either > 0, both / either, np.nan)
    f, l = w.first.astype(np.int64), w.last.astype(np.int64)
    lo = np.maximum(f[:, None], f[None, :])
    hi = np.minimum(l[:, None], l[None, :])
    span_pts = np.where((f[:, None] >= 0) & (f[None, :] >= 0) & (hi >= lo), hi - lo, -1)
    span_days = span_pts * STEP_MS / DAY_MS
    coverage = np.where(span_pts > 0, common / (span_pts + 1), 0.0)
    enough_t = w.trades >= min_trades
    ok = ((span_days >= min_days - 1e-9) & (coverage >= min_coverage) & enough_t[:, None] & enough_t[None, :]
          & np.isfinite(corr))
    np.fill_diagonal(ok, False)
    return {"corr": corr, "n_returns": nret, "same_time": same_time, "same_of_busy": same_busy,
            "common_days": np.maximum(span_days, 0.0), "sufficient": ok}


def account_sufficiency(w: Window, min_days: float = MIN_DAYS, min_trades: int = MIN_TRADES) -> list[dict]:
    """Why each account can or cannot be compared (data span and trade count in the window)."""
    out = []
    for j, aid in enumerate(w.ids):
        span = (w.last[j] - w.first[j]) * STEP_MS / DAY_MS if w.first[j] >= 0 else 0.0
        why = []
        if span < min_days - 1e-9:
            why.append("days")
        if w.trades[j] < min_trades:
            why.append("trades")
        out.append({"account_id": aid, "days": float(span), "trades": int(w.trades[j]), "missing": why})
    return out


# ---------------------------------------------------------------- groups
def complete_linkage(sim: np.ndarray, ok: np.ndarray, threshold: float = GROUP_CORR) -> list[list[int]]:
    """Merge clusters while the weakest pair between them is sufficient and >= threshold.
    Returns clusters of size >= 2 (column indices)."""
    n = sim.shape[0]
    if n < 2:
        return []
    d = np.where(ok, sim, -np.inf).astype(np.float64)
    np.fill_diagonal(d, -np.inf)
    members = {i: [i] for i in range(n)}
    active = np.ones(n, dtype=bool)
    while True:
        dd = np.where(active[:, None] & active[None, :], d, -np.inf)
        f = int(np.argmax(dd))
        a, b = divmod(f, n)
        if not np.isfinite(dd[a, b]) or dd[a, b] < threshold:
            break
        row = np.minimum(d[a], d[b])
        d[a], d[:, a] = row, row
        d[a, a] = -np.inf
        d[b], d[:, b] = -np.inf, -np.inf
        active[b] = False
        members[a] += members.pop(b)
    return [sorted(m) for m in members.values() if len(m) >= 2]


def _max_dd(e: np.ndarray) -> float:
    peak = np.maximum.accumulate(e)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, 1.0 - e / peak, 0.0)
    return float(np.nanmax(dd)) if len(dd) else 0.0


def combined(w: Window, cols: list[int]) -> Optional[dict]:
    """Equal-weight what-if of one group: member equity curves added up (each keeps its wallet)."""
    e = w.equity[:, cols]
    has = ~np.isnan(e)
    rows = has.all(1)
    if rows.sum() < 2:
        return None
    i0, i1 = int(np.argmax(rows)), len(rows) - 1 - int(np.argmax(rows[::-1]))
    e = e[i0:i1 + 1]
    # forward-fill single missing points inside the common span
    idx = np.where(~np.isnan(e), np.arange(len(e))[:, None], 0)
    np.maximum.accumulate(idx, axis=0, out=idx)
    e = e[idx, np.arange(e.shape[1])]
    tot = e.sum(1)
    ts = w.ts[i0:i1 + 1]
    day = (ts - 1) // DAY_MS             # equity ts is a close time: 00:00 closes the day before
    last_of_day = np.r_[day[1:] != day[:-1], True]
    ends = np.flatnonzero(last_of_day)
    closes = np.vstack([e[:1], e[ends[ends > 0]]])          # start, then each day's last point
    dp = np.diff(closes, axis=0)                            # (days, members)
    member_dd = [_max_dd(e[:, k]) for k in range(e.shape[1])]
    comb_dd = _max_dd(tot)
    avg_dd = float(np.mean(member_dd))
    worst_comb = float(dp.sum(1).min())
    worst_members = float(dp.min(0).sum())
    return {
        "from": int(ts[0]), "to": int(ts[-1]), "days": int(len(dp)),
        "pnl": float(tot[-1] - tot[0]), "return": float(tot[-1] / tot[0] - 1) if tot[0] > 0 else None,
        "max_dd": comb_dd, "avg_member_max_dd": avg_dd,
        "dd_ratio": comb_dd / avg_dd if avg_dd > 0 else None,
        "worst_day": worst_comb, "members_worst_days_sum": worst_members,
        "worst_day_ratio": worst_comb / worst_members if worst_members < 0 else None,
    }


# ---------------------------------------------------------------- report
def _stats(v: np.ndarray) -> dict:
    v = v[np.isfinite(v)]
    if not len(v):
        return {"pairs": 0}
    return {"pairs": int(len(v)), "median": float(np.median(v)), "p90": float(np.percentile(v, 90)),
            "max": float(v.max()), "share_ge_group": float((v >= GROUP_CORR).mean())}


def _acct(w: Window, j: int) -> dict:
    return {"account_id": w.ids[j], "strategy": w.meta[j]["strategy"], "timeframe": w.meta[j]["timeframe"]}


def _clean(x):
    if isinstance(x, float):
        return None if not math.isfinite(x) else round(x, 6)
    if isinstance(x, (np.floating,)):
        return _clean(float(x))
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def report(conn: sqlite3.Connection, days: float = 7, end: Optional[int] = None, top_pairs: int = 20,
           threshold: float = GROUP_CORR, min_days: Optional[float] = None, min_trades: int = MIN_TRADES) -> dict:
    """Everything above as one JSON-safe dict (NaN -> None)."""
    min_days = MIN_DAYS if min_days is None else min_days
    rules = {**RULES, "group_corr": threshold, "min_days": min_days, "min_trades": min_trades}
    w = load_window(conn, days, end)
    if w is None:
        return {"window": None, "rules": rules, "exposure": None, "pairs": None, "groups": [],
                "insufficient": [], "note": "no equity data"}
    sim = similarity(w, min_days, min_trades)
    excl = w.excluded()
    S = np.flatnonzero(~excl)
    R = np.flatnonzero(w.is_random)
    corr, ok = sim["corr"], sim["sufficient"]

    iu = np.triu_indices(len(S), 1)
    ss_ok = ok[np.ix_(S, S)][iu]
    ss_corr = corr[np.ix_(S, S)][iu]
    ir = np.triu_indices(len(R), 1)
    rr = corr[np.ix_(R, R)][ir][ok[np.ix_(R, R)][ir]]
    rs = corr[np.ix_(R, S)][ok[np.ix_(R, S)]]
    order = np.argsort(-np.where(ss_ok, ss_corr, -np.inf))[:top_pairs]
    top = []
    for k in order:
        if not ss_ok[k]:
            break
        a, b = S[iu[0][k]], S[iu[1][k]]
        top.append({"a": _acct(w, a), "b": _acct(w, b), "corr": corr[a, b], "same_time": sim["same_time"][a, b],
                    "same_of_busy": sim["same_of_busy"][a, b], "common_days": sim["common_days"][a, b],
                    "n_returns": int(sim["n_returns"][a, b])})

    groups = []
    for cl in complete_linkage(corr[np.ix_(S, S)], ok[np.ix_(S, S)], threshold):
        cols = [int(S[i]) for i in cl]
        sub = np.ix_(cols, cols)
        ju = np.triu_indices(len(cols), 1)
        c = corr[sub][ju]
        sb = sim["same_of_busy"][sub][ju]
        groups.append({"size": len(cols), "accounts": [_acct(w, j) for j in cols],
                       "strategies": len({w.meta[j]["strategy"] for j in cols}),
                       "min_corr": float(c.min()), "mean_corr": float(c.mean()),
                       "same_of_busy_mean": float(np.nanmean(sb)) if np.isfinite(sb).any() else None,
                       "combined": combined(w, cols)})
    groups.sort(key=lambda g: (-g["size"], -g["mean_corr"]))

    suff = account_sufficiency(w, min_days, min_trades)
    strat_ok = [s for j, s in enumerate(suff) if not excl[j] and not s["missing"]]
    copies = []
    for j in np.flatnonzero(excl & ~w.is_random):               # copy accounts: how close to their parent
        par = w.meta[j].get("parent")
        k = w.ids.index(par) if par in w.ids else None
        copies.append({"account_id": w.ids[j], "parent": par,
                       "corr_with_parent": None if k is None else corr[j, k],
                       "sufficient": None if k is None else bool(ok[j, k])})
    out = {
        "window": {"start": int(w.start), "end": int(w.end), "days": days, "points": int(len(w.ts))},
        "rules": rules,
        "accounts": {"strategy": int(len(S)), "random": int(len(R)), "copy": len(copies),
                     "strategy_enough_data": len(strat_ok)},
        "exposure": exposure(w),
        "pairs": {"strategy_pairs": int(len(ss_ok)), "sufficient": int(ss_ok.sum()),
                  "insufficient": int(len(ss_ok) - ss_ok.sum()),
                  "corr": _stats(ss_corr[ss_ok]),
                  "random_reference": {"random_pairs": _stats(rr), "random_vs_strategy": _stats(rs)},
                  "top": top},
        "groups": groups,
        "grouped_accounts": int(sum(g["size"] for g in groups)),
        "insufficient": [s for j, s in enumerate(suff) if not excl[j] and s["missing"]],
        "copies": copies,
    }
    return _clean(out)


def open_ro(path: str) -> sqlite3.Connection:
    import os
    import urllib.parse
    return sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True, timeout=5)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Overlap between paper v3 accounts (read-only).")
    ap.add_argument("--db", default="paper3.db")
    ap.add_argument("--days", type=float, default=7)
    a = ap.parse_args(argv)
    c = open_ro(a.db)
    try:
        print(json.dumps(report(c, a.days), ensure_ascii=False, indent=1))
    finally:
        c.close()


if __name__ == "__main__":
    main()
