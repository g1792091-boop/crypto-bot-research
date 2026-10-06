"""The pure pieces of the 5-year combination generator (paperbot/dash/tools/combo5y.py): calendar, money per day and
month, the entry-quality group of a signal, the merged signal rules, the statistics and the portfolio numbers. Nothing
here loads the research engines or a cache, so tests/test_combo5y_core.py feeds them tiny hand-made arrays.

Time: every bar time is its OPEN time in ms (UTC). Days and months are Korea time (KST = UTC + 9 h), as everywhere on
the dashboard. A signal on bar t is known at that bar's CLOSE (open + bar length); its entry is the next bar's open.
"""
from __future__ import annotations

import calendar
import itertools
import math
from typing import Callable, Iterable, Optional, Sequence

import numpy as np

KST_MS = 9 * 3_600_000
DAY_MS = 86_400_000
TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
NEG = -(1 << 40)                 # "never fired" index


# ---------------------------------------------------------------- calendar (Korea time)
def kst_day(ms):
    """KST day number (days since 1970-01-01 KST) of a UTC ms time (scalar or array)."""
    return (np.asarray(ms, dtype=np.int64) + KST_MS) // DAY_MS


def kst_month_start(y: int, m: int) -> int:
    """UTC ms of YYYY-MM-01 00:00 KST."""
    return calendar.timegm((y, m, 1, 0, 0, 0)) * 1000 - KST_MS


def months(first: str, last: str) -> list[dict]:
    """KST calendar months first..last ('YYYY-MM', both included): [{label, start, end}] (UTC ms, end exclusive)."""
    y, m = (int(x) for x in first.split("-"))
    ly, lm = (int(x) for x in last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append({"label": f"{y:04d}-{m:02d}", "start": kst_month_start(y, m), "end": kst_month_start(ny, nm)})
        y, m = ny, nm
    return out


def day_axis(mons: list[dict]) -> np.ndarray:
    """Every KST day number from the first month's first day to the last month's last day."""
    return np.arange(int(kst_day(mons[0]["start"])), int(kst_day(mons[-1]["end"])), dtype=np.int64)


def month_day_slices(mons: list[dict], d0: int) -> list[tuple[int, int]]:
    """[(first day index, end day index)] of each month on the day axis that starts at KST day ``d0``."""
    return [(int(kst_day(m["start"])) - d0, int(kst_day(m["end"])) - d0) for m in mons]


def year_slices(mons: list[dict], d0: int) -> dict[int, tuple[int, int]]:
    """{year: (first day index, end day index)} of the KST calendar years the months cover."""
    out: dict = {}
    for m, (a, b) in zip(mons, month_day_slices(mons, d0)):
        y = int(m["label"][:4])
        lo, hi = out.get(y, (a, b))
        out[y] = (min(lo, a), max(hi, b))
    return out


def bounds_in(ts: np.ndarray, start: int, end: int, warmup: int = 0) -> tuple[int, int]:
    """(lo, n_end) of the bars whose open time is in [start, end): rules_bt.simulate's per-coin bounds (signals on
    [lo, n_end - 1), every exit inside the window)."""
    lo = max(int(np.searchsorted(ts, start, side="left")), int(warmup))
    return lo, int(np.searchsorted(ts, end, side="left"))


# ---------------------------------------------------------------- money of one account
def trade_pnl(R: np.ndarray, mf: np.ndarray, initial: float) -> np.ndarray:
    """Dollar P&L of each trade of a compounding account from rules_bt's trade table: R = P&L / margin and
    mf = margin / equity before the trade (equity_{n+1} = equity_n x (1 + R_n mf_n))."""
    g = np.asarray(R, float) * np.asarray(mf, float)
    if not len(g):
        return np.zeros(0)
    eq_before = initial * np.concatenate(([1.0], np.cumprod(1.0 + g)[:-1]))
    return eq_before * g


def daily_add(daily: np.ndarray, day_idx: np.ndarray, pnl: np.ndarray) -> None:
    """Add each trade's P&L to its exit day (indexes outside the axis are dropped)."""
    ok = (day_idx >= 0) & (day_idx < len(daily))
    np.add.at(daily, day_idx[ok], pnl[ok])


def month_sums(daily: np.ndarray, slices: Sequence[tuple[int, int]]) -> np.ndarray:
    return np.array([float(daily[a:b].sum()) for a, b in slices])


def elapsed_matrix(daily: np.ndarray, slices: Sequence[tuple[int, int]], days: int = 31) -> np.ndarray:
    """(months, days) cumulative P&L by the END of day 1..``days`` of each month (a shorter month keeps its total)."""
    out = np.zeros((len(slices), days))
    for j, (a, b) in enumerate(slices):
        c = np.cumsum(daily[a:b])
        if not len(c):
            continue
        k = min(days, len(c))
        out[j, :k] = c[:k]
        out[j, k:] = c[-1]
    return out


def curve_mdd(pnl_steps: np.ndarray, capital: float) -> tuple[float, float]:
    """(deepest fall in $, as a share of the peak) of the curve capital + cumsum(pnl_steps)."""
    eq = capital + np.cumsum(np.asarray(pnl_steps, float))
    peak = np.maximum(np.maximum.accumulate(eq), capital) if len(eq) else np.array([capital])
    if not len(eq):
        return 0.0, 0.0
    dd = peak - eq
    return float(max(dd.max(), 0.0)), float((dd / peak).max())


# ---------------------------------------------------------------- monthly distribution
def month_stats(m: Sequence[float]) -> dict:
    """best / worst / median / mean month, the share of months above 0, quartiles (returns as ratios)."""
    v = np.asarray([x for x in m if x is not None and np.isfinite(x)], float)
    if not len(v):
        return {"n": 0}
    q = np.quantile(v, [0.1, 0.25, 0.5, 0.75, 0.9])
    return {"n": int(len(v)), "best": float(v.max()), "worst": float(v.min()), "median": float(q[2]),
            "mean": float(v.mean()), "pos_share": float((v > 0).mean()), "p10": float(q[0]), "p25": float(q[1]),
            "p75": float(q[3]), "p90": float(q[4])}


def rank_of(x: float, m: Sequence[float]) -> dict:
    """Where ``x`` would stand among the months ``m``: rank 1 = above every month; ``below`` = months under x."""
    v = np.asarray(m, float)
    v = v[np.isfinite(v)]
    above = int((v > x).sum())
    return {"rank": above + 1, "of": int(len(v)) + 1, "below": int((v < x).sum()), "n": int(len(v)),
            "share_below": float((v < x).mean()) if len(v) else None}


# ---------------------------------------------------------------- the entry-quality group (levrule.quality_group, vectorised)
def quality_best(values: dict, cell: Optional[dict]) -> np.ndarray:
    """True where the signal is "best" under levrule.quality_group: the mean quintile of the strategy's features that
    have a finite value and edges is >= 4 (a value on an edge goes up: bisect_right). ``values``: {feature: array of
    the value on the side the signal trades}; ``cell``: quality_edges.json cells["<strategy>|<tf>"] (None: no edges ->
    every signal "normal")."""
    n = len(next(iter(values.values()))) if values else 0
    if not cell or not n:
        return np.zeros(n, bool)
    s = np.zeros(n)
    k = np.zeros(n)
    for name, e in cell.items():
        if name not in values:
            continue
        v = np.asarray(values[name], float)
        ok = np.isfinite(v)
        signed = np.where(ok, v if e["higher_is_stronger"] else -v, 0.0)
        q = 1 + np.searchsorted(np.asarray(e["edges"], float), signed, side="right")
        s += np.where(ok, q, 0)
        k += ok
    return (k > 0) & (s / np.maximum(k, 1) >= 4)


# ---------------------------------------------------------------- merged signal rules (sparse, no look-ahead)
def sig_idx(sig: np.ndarray, side: int) -> np.ndarray:
    return np.flatnonzero(np.asarray(sig) == side)


def _latest(ib: np.ndarray, t: np.ndarray) -> np.ndarray:
    """For each t: the latest index in sorted ``ib`` that is <= t (NEG when none)."""
    j = np.searchsorted(ib, t, side="right") - 1
    return np.where(j >= 0, ib[np.maximum(j, 0)] if len(ib) else NEG, NEG)


def and_idx(ia: np.ndarray, ib: np.ndarray, k: int) -> np.ndarray:
    """AND (one side): bars t where A fires and B fired on one of the bars t-k..t, or B fires and A fired on t-k..t.
    Both are known at t's close, so the entry is t + 1 (never a later bar's signal)."""
    if not len(ia) or not len(ib):
        return np.zeros(0, np.int64)
    a_ok = ia[(ia - _latest(ib, ia)) <= k]
    b_ok = ib[(ib - _latest(ia, ib)) <= k]
    return np.union1d(a_ok, b_ok).astype(np.int64)


def filter_idx(ia: np.ndarray, side: int, ib_any: np.ndarray, b_side: np.ndarray, n_bars: int) -> np.ndarray:
    """FILTER (one side of A): A's bars t where B's latest signal on bars t - n_bars .. t (B's own bar t included,
    nothing after t) is on the same side."""
    if not len(ia) or not len(ib_any):
        return np.zeros(0, np.int64)
    j = np.searchsorted(ib_any, ia, side="right") - 1
    jj = np.maximum(j, 0)
    ok = (j >= 0) & ((ia - ib_any[jj]) <= n_bars) & (b_side[jj] == side)
    return ia[ok].astype(np.int64)


def nonzero_with_side(sig: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    i = np.flatnonzero(np.asarray(sig) != 0)
    return i, np.asarray(sig)[i].astype(np.int64)


def vote_sides(stack: np.ndarray, k: int) -> np.ndarray:
    """VOTE: +1 where at least ``k`` of the rows are +1 on the bar (and fewer than k are -1), -1 the other way; a bar
    where both sides reach k is a conflict (0). ``stack``: (strategies, bars) int8."""
    up = (stack == 1).sum(axis=0)
    dn = (stack == -1).sum(axis=0)
    out = np.zeros(stack.shape[1], np.int8)
    out[(up >= k) & (dn < k)] = 1
    out[(dn >= k) & (up < k)] = -1
    return out


def closed_higher(ts_lo: np.ndarray, tf_lo: str, ts_hi: np.ndarray, tf_hi: str) -> np.ndarray:
    """For each lower-timeframe bar: the index of the last higher-timeframe bar that has CLOSED by the lower bar's
    close (higher open + its length <= lower open + its length); -1 when none."""
    c_lo = np.asarray(ts_lo, np.int64) + TF_MS[tf_lo]
    c_hi = np.asarray(ts_hi, np.int64) + TF_MS[tf_hi]
    return np.searchsorted(c_hi, c_lo, side="right") - 1


def mtf_idx(ia: np.ndarray, side: int, last_closed: np.ndarray, ih_any: np.ndarray, h_side: np.ndarray,
            max_age: Optional[int] = None) -> np.ndarray:
    """MTF (one side of the lower-timeframe signals ``ia``): kept when the latest higher-timeframe signal on a CLOSED
    higher bar (index <= last_closed[t]) is on the same side; ``max_age`` (higher bars) also asks it to be recent:
    last_closed - its bar <= max_age."""
    if not len(ia) or not len(ih_any):
        return np.zeros(0, np.int64)
    lc = last_closed[ia]
    j = np.searchsorted(ih_any, lc, side="right") - 1
    jj = np.maximum(j, 0)
    ok = (lc >= 0) & (j >= 0) & (h_side[jj] == side)
    if max_age is not None:
        ok &= (lc - ih_any[jj]) <= max_age
    return ia[ok].astype(np.int64)


def drop_conflicts(il: np.ndarray, is_: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A bar that would open both a long and a short: neither (the merged rule cannot pick a side)."""
    both = np.intersect1d(il, is_)
    if not len(both):
        return il, is_
    return np.setdiff1d(il, both), np.setdiff1d(is_, both)


def shift_idx(idx: np.ndarray, off: int, n: int) -> np.ndarray:
    """A circular shift in time (the shuffle null): every signal moves ``off`` bars, wrapping at ``n``; the signal's
    own spacing is kept, its timing against everything else is broken."""
    return np.sort((np.asarray(idx, np.int64) + int(off)) % int(n))


# ---------------------------------------------------------------- statistics of one merged rule
def cluster_t(vals: np.ndarray, groups: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    """(t, one-sided p for mean > 0): the mean of ``vals`` against 0 with a standard error clustered by ``groups``
    (weeks: trades of the same week on different coins move together). None with fewer than 2 groups."""
    v = np.asarray(vals, float)
    n = len(v)
    if n < 2:
        return None, None
    mean = v.mean()
    _, inv = np.unique(groups, return_inverse=True)
    G = int(inv.max()) + 1
    if G < 2:
        return None, None
    S = np.bincount(inv, weights=v - mean)
    se = math.sqrt(float((S ** 2).sum())) / n * math.sqrt(G / (G - 1))
    if se <= 0:
        return None, None
    t = mean / se
    return float(t), float(0.5 * math.erfc(t / math.sqrt(2)))


def bh(pvals: Sequence[Optional[float]], q: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg step-up at FDR ``q`` over the p-values that exist (None never passes and does not count)."""
    ix = [i for i, p in enumerate(pvals) if p is not None]
    m = len(ix)
    out = [False] * len(pvals)
    if not m:
        return out
    order = sorted(ix, key=lambda i: pvals[i])
    k = 0
    for r, i in enumerate(order, 1):
        if pvals[i] <= q * r / m:
            k = r
    for i in order[:k]:
        out[i] = True
    return out


def rank_p(real: float, null: Sequence[float]) -> Optional[float]:
    """(null runs >= real + 1) / (runs + 1): small = the real value is rarely reached by the shuffled ones."""
    v = np.asarray([x for x in null if x is not None and np.isfinite(x)], float)
    if not len(v) or real is None or not np.isfinite(real):
        return None
    return float((np.sum(v >= real - 1e-15) + 1) / (len(v) + 1))


# ---------------------------------------------------------------- portfolio numbers (daily P&L rows of the units)
def corr_matrix(U: np.ndarray) -> np.ndarray:
    """Pearson correlation of the rows (a row that never moves: NaN against everything)."""
    U = np.asarray(U, float)
    sd = U.std(axis=1)
    Z = np.where(sd[:, None] > 0, (U - U.mean(axis=1, keepdims=True)) / np.where(sd > 0, sd, 1)[:, None], np.nan)
    C = (Z @ Z.T) / U.shape[1] if U.shape[1] else np.full((len(U), len(U)), np.nan)
    np.fill_diagonal(C, 1.0)
    return C


def worst_days(x: np.ndarray, share: float) -> np.ndarray:
    """Indexes of the ceil(share x days) lowest days of x that were losses (< 0)."""
    k = int(math.ceil(share * len(x)))
    order = np.argsort(x, kind="stable")[:k]
    return order[x[order] < 0]


def tail_corr(U: np.ndarray, share: float = 0.05, min_days: int = 10) -> np.ndarray:
    """For every pair: the correlation of the two rows on the days that were among EITHER one's worst ``share`` of
    days (losses only). NaN with fewer than ``min_days`` such days or a row that does not move on them."""
    U = np.asarray(U, float)
    n = len(U)
    W = [set(worst_days(U[i], share).tolist()) for i in range(n)]
    out = np.full((n, n), np.nan)
    for i in range(n):
        out[i, i] = 1.0
        for j in range(i + 1, n):
            d = np.array(sorted(W[i] | W[j]), dtype=np.int64)
            if len(d) < min_days:
                continue
            a, b = U[i, d], U[j, d]
            if a.std() > 0 and b.std() > 0:
                out[i, j] = out[j, i] = float(np.corrcoef(a, b)[0, 1])
    return out


def coloss(U: np.ndarray) -> np.ndarray:
    """For every pair: days both lost / days at least one lost (NaN when neither ever lost)."""
    L = np.asarray(U, float) < 0
    both = L.astype(float) @ L.T.astype(float)
    cnt = L.sum(axis=1).astype(float)
    either = cnt[:, None] + cnt[None, :] - both
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(either > 0, both / np.where(either > 0, either, 1), np.nan)
    return out


def all_combos(n: int, kmin: int, kmax: int) -> Iterable[np.ndarray]:
    for k in range(kmin, min(kmax, n) + 1):
        yield np.array(list(itertools.combinations(range(n), k)), dtype=np.int64)


def all_scores(U: np.ndarray, cap: np.ndarray, kmin: int, kmax: int, curve_numbers: Callable,
               max_cells: int = 6_000_000) -> np.ndarray:
    """agents/synergy's score (``curve_numbers``) of EVERY equal-weight combination of kmin..kmax rows, chunked so a
    chunk holds at most ``max_cells`` numbers."""
    out = []
    D = U.shape[1]
    for combos in all_combos(len(U), kmin, kmax):
        k = combos.shape[1]
        step = max(1, max_cells // max(1, k * D))
        for a in range(0, len(combos), step):
            c = combos[a:a + step]
            out.append(curve_numbers(U[c].sum(axis=1), cap[c].sum(axis=1))[3])
    return np.concatenate(out) if out else np.zeros(0)


def walk_forward(U: np.ndarray, cap: np.ndarray, years: dict, search: Callable, curve_numbers: Callable,
                 kmin: int = 2, kmax: int = 5) -> list[dict]:
    """Calendar-year walk-forward: the best combination of year N (``search`` on year N's columns ONLY) scored on
    year N+1 alone (a fresh curve from the capital), against every combination's score in year N+1."""
    rows = []
    ys = sorted(years)
    for y, y2 in zip(ys, ys[1:]):
        a, b = years[y]
        a2, b2 = years[y2]
        best = search(U[:, a:b], cap)
        if not best:
            continue
        sc_in, combo = best[0]
        c = list(combo)
        nxt = curve_numbers(U[c][:, a2:b2].sum(axis=0)[None, :], np.array([cap[c].sum()]))
        allv = all_scores(U[:, a2:b2], cap, kmin, kmax, curve_numbers)
        s2 = float(nxt[3][0])
        rows.append({"pick_year": int(y), "test_year": int(y2), "combo": c, "score_in": float(sc_in), "score_next": s2,
                     "return_next": float(nxt[0][0] / cap[c].sum()), "median_next": float(np.median(allv)),
                     "p75_next": float(np.quantile(allv, 0.75)), "beat_share": float((allv < s2).mean()),
                     "n_combos": int(len(allv))})
    return rows


# ---------------------------------------------------------------- one shared account
def shared_month(cands: list, trade: Callable, initial: float, share_of: int, bust_below: float = 10.0) -> dict:
    """One shared account for one month, fed by several accounts' signals: at most one position per coin; a signal on
    a coin already held is skipped (``same`` if the same side, ``conflict`` if the opposite side). ``cands``: sorted
    (entry_time, coin_priority, tf_rank, member, coin, side, payload). ``trade(payload, sizing_equity)`` -> None
    (refused by the sizing rule) or (free_time, pnl[, book_time]): the coin is free again from ``free_time`` (the
    exit bar's close) and the P&L is booked at ``book_time`` (default free_time; the separate accounts book at the exit
    bar). Each position is sized on equity / ``share_of`` (one paper account's share); the equity changes only when a
    position has exited."""
    eq = float(initial)
    held: dict = {}                      # coin -> (free_time, side, pnl, book_time)
    out = {"signals": 0, "entries": 0, "same": 0, "conflict": 0, "refused": 0, "wins": 0, "bust": False, "booked": []}

    def settle(upto: Optional[int]) -> None:
        nonlocal eq
        for coin in sorted(held, key=lambda c: held[c][0]):
            ex, _s, pnl, bt = held[coin]
            if upto is None or ex <= upto:
                eq += pnl
                out["booked"].append((bt, pnl))
                out["wins"] += int(pnl > 0)
                del held[coin]

    for t, _p, _r, _m, coin, side, payload in cands:
        settle(t)
        if eq < bust_below:
            out["bust"] = True
            break
        out["signals"] += 1
        if coin in held:
            if held[coin][1] == side:
                out["same"] += 1
            else:
                out["conflict"] += 1
            continue
        r = trade(payload, eq / share_of)
        if r is None:
            out["refused"] += 1
            continue
        out["entries"] += 1
        held[coin] = (int(r[0]), side, float(r[1]), int(r[2]) if len(r) > 2 else int(r[0]))
    settle(None)
    out["final"] = eq
    return out


def r4(x, n: int = 4):
    """A JSON-safe rounded float (None for NaN / inf / None)."""
    if x is None:
        return None
    x = float(x)
    return round(x, n) if math.isfinite(x) else None
