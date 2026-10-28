"""Signal lights, month accounts and random-skip twins (PLAN.md 2, 4, 5), shared by the V3.9 and friend runs.
Research code: nothing here trades."""
from __future__ import annotations

import numpy as np

RULES = {"G0": None, "G1": ("sum", 20, None), "G2": ("win", 20, 0.75), "G3": ("sum", 10, None)}
NAMES = {"G0": "늘 따라감 (지금)", "G1": "최근 20거래 합 플러스", "G2": "최근 20거래 승률 75% 이상", "G3": "최근 10거래 합 플러스"}
TWINS = 200
START, BUST = 50.0, 1.0


def lights(exit_ms: np.ndarray, roe: np.ndarray, entry_ms: np.ndarray, rule) -> np.ndarray:
    """For each paper entry: follow it? From the paper trades closed before that entry (fewer than N closed: follow)."""
    out = np.ones(len(entry_ms), bool)
    if rule is None:
        return out
    kind, n, q = rule
    o = np.argsort(exit_ms, kind="stable")
    ex, r = exit_ms[o], roe[o]
    for i, t in enumerate(entry_ms):
        j = int(np.searchsorted(ex, t, side="left"))
        if j < n:
            continue
        last = r[j - n:j]
        out[i] = last.sum() > 0 if kind == "sum" else (last > 0).mean() >= q
    return out


def fast_months(months: list, fill: np.ndarray, exit_: np.ndarray, ret: np.ndarray, ok: np.ndarray,
                keep: np.ndarray) -> np.ndarray:
    """Month accounts from $50 on the kept paper entries (time order): a live trade's wallet return ``ret`` (from a
    run at $50), skipped while the live position from an earlier entry is still open, stopped below $1."""
    xs = np.empty(len(months))
    for m, (a, b) in enumerate(months):
        idx = np.flatnonzero((fill >= a) & (fill < b) & keep & ok)
        w, busy = START, -1
        for i in idx:
            if fill[i] <= busy:
                continue
            w *= 1.0 + ret[i]
            busy = exit_[i]
            if w < BUST:
                break
        xs[m] = w / START
    return xs


def month_read(xs: np.ndarray) -> dict:
    xs = np.asarray(xs, float)
    return {"months": int(len(xs)), "half": int((xs <= 0.5).sum()), "x2": int((xs >= 2).sum()), "x6": int((xs >= 6).sum()),
            "up": int((xs > 1).sum()), "median": round(float(np.median(xs)), 3),
            "geo": round(float(np.exp(np.mean(np.log(np.maximum(xs, 0.01))))), 3)}


def twins(months: list, fill, exit_, ret, ok, in_period: np.ndarray, keep_n: int, seed0: int = 401) -> np.ndarray:
    """Half-loss month counts of TWINS random-skip twins: keep_n of the period's paper entries kept at random."""
    idx = np.flatnonzero(in_period)
    out = np.empty(TWINS, int)
    for i in range(TWINS):
        rng = np.random.default_rng(seed0 + i)
        keep = np.zeros(len(fill), bool)
        keep[rng.choice(idx, size=min(keep_n, len(idx)), replace=False)] = True
        out[i] = int((fast_months(months, fill, exit_, ret, ok, keep) <= 0.5).sum())
    return out


def verdict(per: dict) -> dict:
    """PLAN 5: per[period] = {"G0": {...}, "G1": {...}, "twins_more_share": float}; both periods must pass."""
    tests = {}
    for p, d in per.items():
        g0, g1 = d["G0"], d["G1"]
        tests[p] = {"fewer_half_months": g1["half"] < g0["half"],
                    "better_mean_roe": g1["mean_roe"] > g0["mean_roe"],
                    "beats_95pct_twins": d["twins_more_share"] >= 0.95,
                    "higher_median_month": g1["median"] > g0["median"]}
    helps = all(t["fewer_half_months"] and t["better_mean_roe"] and t["beats_95pct_twins"] for t in tests.values())
    return {"tests": tests, "helps": helps, "recommend": helps and all(t["higher_median_month"] for t in tests.values())}
