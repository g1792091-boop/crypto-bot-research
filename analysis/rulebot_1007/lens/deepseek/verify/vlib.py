"""Verifier helpers (own code). Import after sys.path tweak in each script."""
import math
import numpy as np
import pandas as pd
from scipy import stats

S = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
OUT_REAL = S + "/rb_analyze/out_real"
EXP = S + "/export_1007"
REPO = "/home/user/crypto-bot-research"
TFMIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
H = 3_600_000


def crse(x, cl):
    """mean, cluster-robust SE (CR1), G, t, df; plain iid SE too"""
    x = np.asarray(x, float); cl = np.asarray(cl)
    n = len(x)
    m = x.mean()
    u, inv = np.unique(cl, return_inverse=True)
    G = len(u)
    if n < 2 or G < 2:
        return dict(n=n, mean=m, G=G)
    s = np.bincount(inv, weights=x - m)
    var = G / (G - 1) * (s ** 2).sum() / n ** 2
    se = math.sqrt(var)
    iid = x.std(ddof=1) / math.sqrt(n)
    t = m / se if se > 0 else np.nan
    tq = stats.t.ppf(0.975, G - 1)
    return dict(n=n, mean=m, G=G, se=se, se_iid=iid, deff=(se / iid) ** 2 if iid > 0 else np.nan,
                lo=m - tq * se, hi=m + tq * se, t=t,
                p_gt=stats.t.sf(t, G - 1), p_lt=stats.t.cdf(t, G - 1), sd=x.std(ddof=1))


def bhq(p):
    p = np.asarray(p, float); n = len(p)
    o = np.argsort(p)
    r = p[o] * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(r[::-1])[::-1]
    out = np.empty(n); out[o] = np.minimum(q, 1)
    return out


def load_replay(kind="ds200", run="current"):
    R = pd.read_csv(OUT_REAL + "/replay_signals.csv")
    if kind:
        R = R[R.kind == kind]
    if run:
        R = R[R.run == run]
    R = R.copy()
    blk = np.maximum(R.timeframe.map(TFMIN).to_numpy() * 60000, H)
    R["cl1h"] = R.bar_close.to_numpy() // blk
    R["cl4h"] = R.bar_close.to_numpy() // (4 * H)
    return R
