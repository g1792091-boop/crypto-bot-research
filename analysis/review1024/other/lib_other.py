"""Shared helpers for the 10/24 review of the demo lab bot and the other server records (analysis only).

Nothing here reads a server or places orders. Every database is opened read-only (mode=ro, immutable=1).
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3

import numpy as np

KST = dt.timezone(dt.timedelta(hours=9))
GOAL_X = 6.0          # +500 % = x6
GOAL_DAYS = 30


def ro(path: str) -> sqlite3.Connection:
    """Read-only connection to an exported sqlite copy (never writes, never creates a WAL)."""
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def kst(ms) -> str:
    if ms is None:
        return ""
    return dt.datetime.fromtimestamp(int(ms) / 1000, KST).strftime("%m-%d %H:%M")


def kst_day(ms) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, KST).strftime("%Y-%m-%d")


def streak(pnls) -> int:
    """Longest run of losing trades (pnl < 0) in the given order."""
    best = cur = 0
    for p in pnls:
        cur = cur + 1 if p < 0 else 0
        best = max(best, cur)
    return best


def max_dd(equity) -> float:
    """Largest fall from a running peak, as a fraction (0.3 = -30 %)."""
    e = np.asarray(equity, float)
    if not len(e):
        return 0.0
    peak = np.maximum.accumulate(e)
    return float(np.max(1 - e / peak))


def basic(pnl, ret, side=None, t_exit=None, t_mid=None) -> dict:
    """Trade metrics. pnl: money per trade; ret: per-trade change of the account (0.02 = +2 %), same order (exit
    time). side: +1 long / -1 short. t_mid splits the trades into a first and second half by exit time."""
    pnl = np.asarray(pnl, float)
    ret = np.asarray(ret, float)
    n = len(pnl)
    out = dict(n=n)
    if not n:
        return out
    w = pnl > 0
    gw, gl = pnl[w].sum(), -pnl[~w].sum()
    out.update(wins=int(w.sum()), win_rate=float(w.mean()), pnl=float(pnl.sum()),
               avg_win=float(pnl[w].mean()) if w.any() else float("nan"),
               avg_loss=float(pnl[~w].mean()) if (~w).any() else float("nan"),
               avg_win_pct=float(ret[w].mean() * 100) if w.any() else float("nan"),
               avg_loss_pct=float(ret[~w].mean() * 100) if (~w).any() else float("nan"),
               pf=float(gw / gl) if gl > 0 else float("inf"),
               ret_mean_pct=float(ret.mean() * 100), ret_med_pct=float(np.median(ret) * 100),
               log_growth=float(np.sum(np.log1p(np.maximum(ret, -0.999)))),
               streak=streak(pnl))
    if side is not None:
        side = np.asarray(side)
        for nm, m in (("long", side > 0), ("short", side < 0)):
            out[f"{nm}_n"] = int(m.sum())
            out[f"{nm}_win"] = float(w[m].mean()) if m.any() else float("nan")
            out[f"{nm}_pnl"] = float(pnl[m].sum())
            out[f"{nm}_ret_pct"] = float(ret[m].mean() * 100) if m.any() else float("nan")
    if t_exit is not None and t_mid is not None:
        t_exit = np.asarray(t_exit)
        for nm, m in (("h1", t_exit < t_mid), ("h2", t_exit >= t_mid)):
            out[f"{nm}_n"] = int(m.sum())
            out[f"{nm}_pnl"] = float(pnl[m].sum())
            out[f"{nm}_ret_pct"] = float(ret[m].mean() * 100) if m.any() else float("nan")
    return out


def growth_at(ret, k) -> float:
    """Mean log growth per trade when the exposure is scaled by k (liquidation at -100 % of the account)."""
    r = np.asarray(ret, float) * k
    if np.any(r <= -1):
        return -np.inf
    return float(np.mean(np.log1p(r)))


def goal_need(ret, trades_per_day: float, days: int = GOAL_DAYS) -> dict:
    """How the measured per-trade returns would have to be scaled (exposure x k) to reach x6 in `days`.
    k = 1 is the measured setting. Returns the best possible 30-day multiple (at the k that maximises the log
    growth), that k, and the smallest k reaching x6 (None if no k does)."""
    ret = np.asarray(ret, float)
    N = trades_per_day * days
    if len(ret) < 2 or N <= 0:
        return dict(best_k=None, best_x=None, need_k=None)
    ks = np.concatenate([np.linspace(0.02, 1, 50), np.linspace(1.05, 20, 380)])
    g = np.array([growth_at(ret, k) for k in ks])
    i = int(np.argmax(g))
    best_x = math.exp(min(700, N * g[i])) if np.isfinite(g[i]) else 0.0
    need = None
    target = math.log(GOAL_X) / N
    ok = np.flatnonzero(g >= target)
    if len(ok):
        need = float(ks[ok[0]])
    g1 = growth_at(ret, 1.0)
    x1 = math.exp(min(700, N * g1)) if np.isfinite(g1) else 0.0
    return dict(best_k=float(ks[i]), best_x=float(best_x), need_k=need, x_at_1=float(x1))


def bootstrap_goal(ret, trades_per_day: float, days: int = GOAL_DAYS, sims: int = 20000, seed: int = 7) -> dict:
    """Resample the measured per-trade account returns (with replacement, trade count per day ~ Poisson) for `days`
    days. P(reach x6 at any time), P(-50 % first) and P(-90 % first) (whichever level comes first), median end."""
    ret = np.asarray(ret, float)
    if len(ret) < 2 or trades_per_day <= 0:
        return dict(p_x6=None, p_dd50=None, p_dd90=None, med_x=None)
    rng = np.random.default_rng(seed)
    n_tr = rng.poisson(trades_per_day * days, sims)
    nmax = int(n_tr.max()) if len(n_tr) else 0
    if nmax == 0:
        return dict(p_x6=0.0, p_dd50=0.0, p_dd90=0.0, med_x=1.0)
    draws = rng.choice(np.maximum(ret, -0.999), size=(sims, nmax), replace=True)
    mask = np.arange(nmax)[None, :] < n_tr[:, None]
    lg = np.where(mask, np.log1p(draws), 0.0)
    path = np.cumsum(lg, axis=1)
    big = nmax + 1

    def first(cond):
        hit = cond & mask
        return np.where(hit.any(axis=1), hit.argmax(axis=1), big)

    t6 = first(path >= math.log(GOAL_X))
    t50 = first(path <= math.log(0.5))
    t90 = first(path <= math.log(0.1))
    end = np.exp(path[np.arange(sims), np.maximum(n_tr - 1, 0)])
    end[n_tr == 0] = 1.0
    return dict(p_x6=float(np.mean(t6 < np.minimum(t50, big))), p_x6_any=float(np.mean(t6 < big)),
                p_dd50=float(np.mean(t50 < np.minimum(t6, big))), p_dd90=float(np.mean(t90 < np.minimum(t6, big))),
                med_x=float(np.median(end)))


def perm_p_mean(a, b, iters: int = 20000, seed: int = 3) -> float:
    """One-sided permutation p-value that mean(a) > mean(b) only by luck (labels shuffled)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if len(a) < 3 or len(b) < 3:
        return float("nan")
    rng = np.random.default_rng(seed)
    obs = a.mean() - b.mean()
    pool = np.concatenate([a, b])
    na = len(a)
    cnt = 0
    for _ in range(iters // 1000):
        idx = np.argsort(rng.random((1000, len(pool))), axis=1)
        sh = pool[idx]
        d = sh[:, :na].mean(axis=1) - sh[:, na:].mean(axis=1)
        cnt += int(np.sum(d >= obs))
    return (cnt + 1) / (iters + 1)


def fmt(x, nd=1, pct=False, sign=False) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "-"
    s = f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"
    return s + ("%" if pct else "")
