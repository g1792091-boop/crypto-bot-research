"""Verifier 5: robustness of the within-(side, day) gap to the cell weighting (n, harmonic n_w*n_g/(n_w+n_g), equal).
Run without -I: python3 v5_weights.py"""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
S = load("sig"); S = S[S.role != "trend"].reset_index(drop=True)
side = S.side.to_numpy(); tf = S.tf.to_numpy(); r = roe(S, "w35")
al = np.zeros(len(S), np.int8)
for t_, h_ in AUTO.items():
    m = tf == t_; al[m] = (state(S, "Jdir", h_) * side)[m]
for per, (a, b) in PERIOD.items():
    X = pd.DataFrame({"day": S.day, "side": side, "coin": S.coin, "al": al, "r": r, "t": S.t})
    X = X[np.isfinite(X.r) & (X.al != 0) & (X.t >= a) & (X.t < b)]
    for keys in (["day", "side"], ["day", "coin", "side"]):
        Y = X.groupby(keys + ["al"]).r.agg(["mean", "count"]).unstack("al").dropna()
        d = Y[("mean", 1)] - Y[("mean", -1)]
        nw, ng = Y[("count", 1)], Y[("count", -1)]
        h = nw * ng / (nw + ng)
        print(per, keys, "cells", len(Y), "n-weighted %.2f" % (100 * (d * (nw + ng)).sum() / (nw + ng).sum()),
              "harmonic %.2f" % (100 * (d * h).sum() / h.sum()), "equal %.2f" % (100 * d.mean()),
              "share cells aligned better %.2f" % (d > 0).mean())
