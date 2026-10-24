"""Verifier: recompute the SEL whole-search multiplicity (t_abs, t_d, BH, day sign-flip max-T) from the per-day sums
(vstats.py), with an independent RNG seed, and count positive cells per period."""
import os, json
import numpy as np, pandas as pd
from scipy.stats import norm
HERE = os.path.dirname(os.path.abspath(__file__))
SHM = "/dev/shm/claude_verify_obvstoch"
V = pd.read_csv(os.path.join(HERE, "vcell.csv.gz"))
S = pd.read_csv("/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch/sel_cells.csv")


def bh(p):
    p = np.asarray(p, float); m = len(p); o = np.argsort(p)
    q = p[o] * m / (np.arange(m) + 1); q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(m); out[o] = np.minimum(q, 1); return out


out = {}
for per in ("SEL", "CONF", "FIVE"):
    z = np.load(os.path.join(SHM, f"vday_{per}.npz"))
    SW, NW, SWo = (z[k].astype(np.float64) for k in ("SW", "NW", "SWo"))
    q = V[V.period == per].reset_index(drop=True)
    n = NW.sum(1); m = SW.sum(1) / n
    act = NW > 0
    def cl_t(Sx, mx):
        s = Sx - NW * mx[:, None]
        G = act.sum(1)
        se = np.sqrt((s ** 2).sum(1) * G / (G - 1)) / n
        return mx / se
    t_abs = cl_t(SW, m)
    dsum = SW - SWo; md = dsum.sum(1) / n
    t_d = cl_t(dsum, md)
    ok = n >= 200
    pa = np.where(ok, norm.sf(t_abs), 1.0); pdd = np.where(ok, norm.sf(t_d), 1.0)
    r = {"cells_n_ge_200": int(ok.sum()), "pos_mean": int((ok & (m > 0)).sum()), "max_t_abs": float(t_abs[ok].max()),
         "bh_abs_pass_q10": int((bh(pa) <= 0.10).sum()), "bh_d_pass_q10": int((bh(pdd) <= 0.10).sum()),
         "max_t_d": float(t_d[ok].max()), "share_d_pos": float((md[ok] > 0).mean())}
    # day sign-flip, self-normalised (as the study) with my own seed; also centred-clustered t for comparison
    rng = np.random.default_rng(777)
    cols = np.where(act.any(0))[0]
    dm = dsum[:, cols]
    nrm = np.sqrt((dm ** 2).sum(1)); nrm[nrm == 0] = np.inf
    Tobs = dm.sum(1) / nrm; Tobs[~ok] = -np.inf
    mx = []
    for i in range(8):
        eps = rng.choice([-1.0, 1.0], size=(dm.shape[1], 250))
        Ts = (dm @ eps) / nrm[:, None]; Ts[~ok] = -np.inf
        mx.append(Ts.max(0))
    mx = np.concatenate(mx)
    r.update(obs_max_T_selfnorm=float(Tobs.max()), null95_max_T=float(np.quantile(mx, 0.95)),
             wy_pass05=int(sum((1 + (mx >= t).sum()) / (1 + len(mx)) <= 0.05 for t in Tobs)))
    # same for the absolute mean (H0: mean <= 0 is not a sign-flip null; skip) -- report the best cell
    best = int(np.argmax(np.where(ok, t_abs, -np.inf)))
    r["best_abs_cell"] = q.cell[best]; r["best_abs_mean"] = float(m[best]); r["best_abs_n"] = int(n[best])
    if per == "SEL":
        s = S.set_index("cell").loc[q.cell]
        r["max_abs_diff_t_abs_vs_study"] = float(np.nanmax(np.abs(t_abs - s.t_abs.values)))
        r["max_abs_diff_t_d_vs_study"] = float(np.nanmax(np.abs(t_d - s.t_d.values)))
        r["study_obs_max_T"] = float(s.T_perm.max())
    out[per] = r
    print(per, json.dumps(r, indent=1))
json.dump(out, open(os.path.join(HERE, "vsearch.json"), "w"), indent=1)
