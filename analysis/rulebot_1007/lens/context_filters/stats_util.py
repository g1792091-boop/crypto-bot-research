"""Cluster-aware difference-in-means with a time-block bootstrap, stratified by run.

d = sum_r w_r * (mean_in_r - mean_out_r) / sum_r w_r, w_r = n_r (signals of run r in the comparison) - the
within-run difference, so a run's overall level (v3a 50x ladder vs v4 30x) never leaks into a contrast.
SE: bootstrap over time blocks (run x floor(bar_close / H hours)), blocks resampled within each run.
p: t = d / SE against Student t with df = sum_r (G_r - 1) (conservative for few clusters).
MDE80 (two-sided 5%) = (t_.975 + t_.80) * SE.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

HOUR = 3_600_000


def bh(p, q=0.05):
    p = np.asarray(p, float)
    out_q = np.full(len(p), np.nan)
    ok = ~np.isnan(p)
    m = ok.sum()
    if m == 0:
        return out_q, np.zeros(len(p), bool)
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[ok])]
    ranked = p[order] * m / np.arange(1, m + 1)
    qv = np.minimum.accumulate(ranked[::-1])[::-1]
    out_q[order] = np.minimum(qv, 1)
    return out_q, out_q <= q


def prep_run(y, inb, bar_close, hours):
    """Per-cluster sums for one run. y: outcome; inb: bool in-bucket."""
    cl = (np.asarray(bar_close) // int(hours * HOUR))
    u, inv = np.unique(cl, return_inverse=True)
    G = len(u)
    y = np.asarray(y, float)
    inb = np.asarray(inb, bool)
    si = np.bincount(inv, weights=np.where(inb, y, 0.0), minlength=G)
    ni = np.bincount(inv, weights=inb.astype(float), minlength=G)
    so = np.bincount(inv, weights=np.where(~inb, y, 0.0), minlength=G)
    no = np.bincount(inv, weights=(~inb).astype(float), minlength=G)
    return si, ni, so, no


def cr_contrast(runs, hours=2.0, min_each=5):
    """Fast analytic version (CR1 cluster-robust SE of the within-run difference, runs pooled with n weights).
    Used inside null simulations where a bootstrap per draw would be too slow."""
    ds, ws, vs, df = [], [], [], 0
    for r in runs:
        y, inb = np.asarray(r["y"], float), np.asarray(r["inb"], bool)
        ok = ~np.isnan(y)
        y, inb, bc = y[ok], inb[ok], np.asarray(r["bc"])[ok]
        if inb.sum() < min_each or (~inb).sum() < min_each:
            continue
        si, ni, so, no = prep_run(y, inb, bc, hours)
        g = len(si)
        Ni, No = ni.sum(), no.sum()
        mi, mo = si.sum() / Ni, so.sum() / No
        infl = (si - mi * ni) / Ni - (so - mo * no) / No
        v = g / max(g - 1, 1) * float((infl ** 2).sum())
        ds.append(mi - mo); ws.append(len(y)); vs.append(v); df += g - 1
    if not ds:
        return np.nan, np.nan, 0
    ws = np.array(ws, float); W = ws.sum()
    d = float(np.dot(ws, ds) / W)
    se = float(np.sqrt(np.dot((ws / W) ** 2, vs)))
    return d, se, max(df, 1)


def contrast(runs, hours=2.0, B=2000, seed=0, min_each=5):
    """runs: list of dicts {y, inb, bc}. Uses only runs with >= min_each in and out.
    Returns n_in, n_out, mean_in, mean_out, d, se, df, t, p_two, mde80, G, runs_used."""
    rng = np.random.default_rng(seed)
    used = []
    for r in runs:
        y, inb = np.asarray(r["y"], float), np.asarray(r["inb"], bool)
        ok = ~np.isnan(y)
        y, inb, bc = y[ok], inb[ok], np.asarray(r["bc"])[ok]
        if inb.sum() >= min_each and (~inb).sum() >= min_each:
            used.append((y, inb, bc, r.get("name", "")))
    res = {"n_in": 0, "n_out": 0, "mean_in": np.nan, "mean_out": np.nan, "d": np.nan, "se": np.nan, "df": 0,
           "t": np.nan, "p_two": np.nan, "mde80": np.nan, "G": 0, "runs_used": ""}
    if not used:
        return res
    ws, ds, boots, G, df = [], [], [], 0, 0
    nin = nout = 0
    min_tot = 0.0
    mout_tot = 0.0
    for y, inb, bc, name in used:
        si, ni, so, no = prep_run(y, inb, bc, hours)
        g = len(si)
        G += g
        df += g - 1
        w = len(y)
        ws.append(w)
        mi, mo = si.sum() / ni.sum(), so.sum() / no.sum()
        ds.append(mi - mo)
        min_tot += w * mi
        mout_tot += w * mo
        nin += int(inb.sum())
        nout += int((~inb).sum())
        idx = rng.integers(0, g, size=(B, g))
        a, b, c, e = si[idx].sum(1), ni[idx].sum(1), so[idx].sum(1), no[idx].sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            boots.append(a / b - c / e)
    ws = np.array(ws, float)
    d = float(np.dot(ws, ds) / ws.sum())
    bm = np.vstack(boots)                     # runs x B
    bd = (ws[:, None] * bm).sum(0) / ws.sum()
    bd = bd[np.isfinite(bd)]
    se = float(np.std(bd, ddof=1)) if len(bd) > 10 else np.nan
    df = max(df, 1)
    t = d / se if se and se > 0 else np.nan
    p = float(2 * stats.t.sf(abs(t), df)) if t == t else np.nan
    mde = float((stats.t.ppf(0.975, df) + stats.t.ppf(0.80, df)) * se) if se == se else np.nan
    res.update(n_in=nin, n_out=nout, mean_in=min_tot / ws.sum(), mean_out=mout_tot / ws.sum(), d=d, se=se, df=df,
               t=t, p_two=p, mde80=mde, G=G, runs_used="+".join(u[3] for u in used))
    return res


def one_sided(t, df, sign):
    """P(T >= t*sign) in the expected direction."""
    if t != t:
        return np.nan
    return float(stats.t.sf(t * sign, df))
