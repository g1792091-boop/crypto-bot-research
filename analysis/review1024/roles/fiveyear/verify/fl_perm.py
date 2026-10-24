"""Verifier (luck / multiple testing) -- step 3: joint month sign-flip permutation of the whole with-family flip search.
For each permutation, one random +-1 per month (the SAME for every cell, so the overlap between cells is kept) multiplies
the monthly paired sums d_m = sum(w35 - w35_opposite) of every with-cell; month-clustered t as in fy_analyze.cluster_t;
then (a) SEL: how many of the 108,391 cells pass BH (q = 0.10) and the largest t, (b) CONF: for the 374 cells picked on the
REAL SEL data, the share with CONF flip mean > 0 and the 374-cell average CONF flip difference.
    python3 fl_perm.py <out_dir> [n_perm]"""
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
NPERM = int(sys.argv[2]) if len(sys.argv) > 2 else 400
Wf = pd.read_pickle(os.path.join(OUT, "Wf.pkl"))
meta = json.load(open(os.path.join(fy_common.SHM, "meta.json")))
nsid = len(meta["sid_name"])
AMr = np.load(os.path.join(fy_common.SHM, "accm.npy"), mmap_mode="r")
P, NS = AMr.shape[0], AMr.shape[1]
AM = np.asarray(AMr).reshape(P, NS, 3, nsid, NMON, 3)
pi, si, di = Wf.pair.to_numpy(), Wf.src.to_numpy(), Wf.sid.to_numpy()
X = AM[pi, si, 2, di]                      # [cells, months, (n, w, o)]
del AM
slS, slC = months_of("SEL"), months_of("CONF")
nS, dS = X[:, slS, 0], X[:, slS, 1] - X[:, slS, 2]
nC, dC = X[:, slC, 0], X[:, slC, 1] - X[:, slC, 2]
MS = (nS > 0).sum(1)


def ct(n, d, s):
    """cluster t of sum(s*d)/N for sign vector s over months (broadcast)."""
    N = n.sum(1)
    M = (n > 0).sum(1)
    sd = d * s[None, :]
    mu = sd.sum(1) / N
    u = (sd - mu[:, None] * n) / N[:, None]
    var = (u ** 2).sum(1) * M / np.maximum(M - 1, 1)
    return mu, mu / np.sqrt(var)


one = np.ones(nS.shape[1])
mu0, t0 = ct(nS, dS, one)
print("check: real SEL t equals study SEL_tFlip:", np.allclose(t0, Wf.SEL_tFlip.to_numpy(), equal_nan=True))
bh0 = bh(pval(t0, MS))
print("real SEL BH passes", int(bh0.sum()))
pick = Wf.bhS.to_numpy()
oneC = np.ones(nC.shape[1])
muC0, tC0 = ct(nC[pick], dC[pick], oneC)
real_share = float((muC0 > 0).mean())
real_avg = float(muC0.mean())
print("real CONF share>0", round(real_share, 4), "avg flip diff", round(real_avg, 5))
rng = np.random.default_rng(20261024)
rows = []
for b in range(NPERM):
    s = rng.choice([-1.0, 1.0], nS.shape[1])
    _m, t = ct(nS, dS, s)
    p = pval(t, MS)
    sC = rng.choice([-1.0, 1.0], nC.shape[1])
    mC, _t = ct(nC[pick], dC[pick], sC)
    rows.append({"perm": b, "sel_bh_pass": int(bh(p).sum()), "sel_max_t": float(np.nanmax(t)),
                 "sel_t_gt3": int((t > 3).sum()), "conf_share_pos_374": float((mC > 0).mean()),
                 "conf_avg_374": float(mC.mean())})
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "fl_perm.csv"), index=False)
print("perms", NPERM)
print("SEL BH passes under null: mean", R.sel_bh_pass.mean(), " q50/95/99", R.sel_bh_pass.quantile([.5, .95, .99]).tolist(),
      " max", R.sel_bh_pass.max(), " P(>=374)", (R.sel_bh_pass >= 374).mean())
print("SEL t>3 under null: mean", R.sel_t_gt3.mean(), "q95", R.sel_t_gt3.quantile(.95), " real", int((t0 > 3).sum()))
print("SEL max t under null: q50/95", R.sel_max_t.quantile([.5, .95]).round(2).tolist(), " real", round(np.nanmax(t0), 2))
print("CONF share>0 of the 374 under null: q50/95/99", R.conf_share_pos_374.quantile([.5, .95, .99]).round(3).tolist(),
      " P(>= real)", (R.conf_share_pos_374 >= real_share).mean())
print("CONF avg flip of the 374 under null: q50/95/99", R.conf_avg_374.quantile([.5, .95, .99]).round(5).tolist(),
      " P(>= real)", (R.conf_avg_374 >= real_avg).mean())
