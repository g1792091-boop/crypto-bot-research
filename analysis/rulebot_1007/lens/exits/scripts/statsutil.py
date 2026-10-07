"""Cluster bootstrap and BH helpers (no repo imports)."""
from __future__ import annotations

import math

import numpy as np


def cluster_boot(x, clusters, B: int = 4000, seed: int = 7) -> dict:
    """Mean of x with a cluster (block) bootstrap: resample whole clusters with replacement.
    Returns mean, se, 95% percentile CI, two-sided p (cluster-robust t with G-1 df, normal if G large), G."""
    x = np.asarray(x, float)
    c = np.asarray(clusters)
    ok = np.isfinite(x)
    x, c = x[ok], c[ok]
    n = len(x)
    if n == 0:
        return {"n": 0, "G": 0, "mean": np.nan, "se": np.nan, "lo": np.nan, "hi": np.nan, "p": np.nan}
    u, inv = np.unique(c, return_inverse=True)
    G = len(u)
    sums = np.bincount(inv, weights=x, minlength=G)
    cnts = np.bincount(inv, minlength=G).astype(float)
    m = x.mean()
    if G < 3:
        return {"n": n, "G": G, "mean": m, "se": np.nan, "lo": np.nan, "hi": np.nan, "p": np.nan}
    rng = np.random.default_rng(seed)
    w = rng.multinomial(G, np.full(G, 1.0 / G), size=B).astype(float)
    den = w @ cnts
    bm = (w @ sums) / np.where(den > 0, den, np.nan)
    bm = bm[np.isfinite(bm)]
    se = float(np.std(bm, ddof=1))
    lo, hi = np.percentile(bm, [2.5, 97.5])
    if se > 0:
        t = m / se
        p = 2 * _t_sf(abs(t), G - 1)
    else:
        p = np.nan if m == 0 else 0.0
    return {"n": n, "G": G, "mean": m, "se": se, "lo": float(lo), "hi": float(hi), "p": float(p)}


def _t_sf(t: float, df: int) -> float:
    """Survival function of Student t (regularized incomplete beta via continued fraction)."""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return 0.5 * _betainc(df / 2.0, 0.5, x)


def _betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbeta) * _cf(a, b, x) / a
    return 1 - math.exp(lbeta) * _cf(b, a, 1 - x) / b


def _cf(a, b, x, it=300, eps=1e-14):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / d if abs(d) > 1e-300 else 1e300
    h = d
    for m in range(1, it):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / d if abs(d) > 1e-300 else 1e300
        c = 1 + aa / c if abs(c) > 1e-300 else 1e300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / d if abs(d) > 1e-300 else 1e300
        c = 1 + aa / c if abs(c) > 1e-300 else 1e300
        de = d * c
        h *= de
        if abs(de - 1) < eps:
            break
    return h


def bh(p, q: float = 0.05):
    p = np.asarray(p, float)
    n = len(p)
    out = np.full(n, np.nan)
    ok = np.isfinite(p)
    if ok.sum() == 0:
        return np.zeros(n, bool), out
    pp = p[ok]
    k = len(pp)
    order = np.argsort(pp)
    ranked = pp[order] * k / np.arange(1, k + 1)
    qv = np.minimum.accumulate(ranked[::-1])[::-1]
    tmp = np.empty(k)
    tmp[order] = np.minimum(qv, 1.0)
    out[ok] = tmp
    return out <= q, out
