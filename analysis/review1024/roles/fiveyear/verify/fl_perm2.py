"""Verifier (luck / multiple testing) -- step 3b: permutation of the WHOLE SELECT search, read on the real CONF.
Each permutation flips the sign of whole SELECT months (the same months for every cell), re-runs the SELECT pick
(top 374 cells by the permuted month-clustered paired t; also the permuted BH set when it is not empty), and reads
the REAL CONF numbers of what it picked: share of cells whose with side beats its coin-flip twin, cell-average
CONF flip difference, cell-average CONF with mean. Real pick: share 0.829, avg flip +0.01077.
Also: the difference statistic (374 average - others average) under joint CONF month sign flips.
    python3 fl_perm2.py <out_dir> [n_perm]"""
import os
import sys
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FY)
import fy_common
fy_common.SHM = "/dev/shm/claude_verify_fl"
import fy_analyze
fy_analyze.SHM = "/dev/shm/claude_verify_fl"
from fy_analyze import *          # noqa

OUT = sys.argv[1]
NPERM = int(sys.argv[2]) if len(sys.argv) > 2 else 300
Wf = pd.read_pickle(os.path.join(OUT, "Wf.pkl"))
meta = json.load(open(os.path.join(fy_common.SHM, "meta.json")))
nsid = len(meta["sid_name"])
AMr = np.load(os.path.join(fy_common.SHM, "accm.npy"), mmap_mode="r")
P, NS = AMr.shape[0], AMr.shape[1]
AM = np.asarray(AMr).reshape(P, NS, 3, nsid, NMON, 3)
X = AM[Wf.pair.to_numpy(), Wf.src.to_numpy(), 2, Wf.sid.to_numpy()]
del AM
slS, slC = months_of("SEL"), months_of("CONF")
nS, dS = X[:, slS, 0], X[:, slS, 1] - X[:, slS, 2]
MS = (nS > 0).sum(1)
confflip = (Wf.CONF_mW - Wf.CONF_mWo).to_numpy()
confW = Wf.CONF_mW.to_numpy()
okC = np.isfinite(confflip)


def ct(n, d, s):
    N = n.sum(1)
    M = (n > 0).sum(1)
    sd = d * s[None, :]
    mu = sd.sum(1) / N
    u = (sd - mu[:, None] * n) / N[:, None]
    var = (u ** 2).sum(1) * M / np.maximum(M - 1, 1)
    return mu, mu / np.sqrt(var)


def read(idx):
    idx = idx[okC[idx]]
    return float((confflip[idx] > 0).mean()), float(confflip[idx].mean()), float(np.nanmean(confW[idx]))


_m, t0 = ct(nS, dS, np.ones(nS.shape[1]))
t0 = np.where(np.isfinite(t0), t0, -np.inf)
top0 = np.argsort(-t0)[:374]
print("real top-374 by SEL t (= the BH set?)", set(top0) == set(np.flatnonzero(Wf.bhS.to_numpy())), "read", read(top0))
from scipy.stats import spearmanr
ok = np.isfinite(t0) & okC
print("rank corr SEL tFlip vs CONF flip diff, all with-cells:", round(spearmanr(t0[ok], confflip[ok]).correlation, 4))
rng = np.random.default_rng(7)
rows = []
for b in range(NPERM):
    s = rng.choice([-1.0, 1.0], nS.shape[1])
    if np.all(s == 1):
        continue
    _m, t = ct(nS, dS, s)
    t = np.where(np.isfinite(t), t, -np.inf)
    top = np.argsort(-t)[:374]
    sh, av, mw = read(top)
    pb = bh(pval(t, MS))
    r = {"perm": b, "top_share": sh, "top_avg_flip": av, "top_avg_mW": mw, "bh_n": int(pb.sum())}
    if pb.sum() > 0:
        r["bh_share"], r["bh_avg_flip"], r["bh_avg_mW"] = read(np.flatnonzero(pb))
    rows.append(r)
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "fl_perm2.csv"), index=False)
rs, ra, rw = read(top0)
print("perms", len(R))
print("null top-374 CONF share>0: q50/95/99", R.top_share.quantile([.5, .95, .99]).round(3).tolist(), "max",
      round(R.top_share.max(), 3), " P(>= real", round(rs, 3), ")", (R.top_share >= rs).mean())
print("null top-374 CONF avg flip: q50/95/99", R.top_avg_flip.quantile([.5, .95, .99]).round(5).tolist(), " P(>= real",
      round(ra, 5), ")", (R.top_avg_flip >= ra).mean())
print("null top-374 CONF avg with mean: q50/95", R.top_avg_mW.quantile([.5, .95]).round(5).tolist(), " real", round(rw, 5),
      " P(>=)", (R.top_avg_mW >= rw).mean())
z = R.dropna(subset=["bh_share"]) if "bh_share" in R else R.iloc[:0]
print("perms with a non-empty null BH set:", len(z), " their CONF share q50/95", z.bh_share.quantile([.5, .95]).round(3).tolist() if len(z) else None)
