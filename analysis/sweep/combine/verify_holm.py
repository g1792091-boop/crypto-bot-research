"""Independent re-check of the Combine gate decision (does not use sweep_lib.holm/apply_gate)."""
import numpy as np, pandas as pd, glob, os
g = pd.read_csv("out/gate_all_is_applied.csv")
# 5m subsets: same n_min / B / cost / E|r| per H (shifts depend only on tf,H,n_min)
r5 = pd.concat([pd.read_csv(f) for f in glob.glob("../discover_g5m/out/gate_is_5m_sub*.csv")])
print("5m per-H unique n_min / mu_star / E_abs_r across both subsets:")
print(r5.groupby("H")[["n_min", "mu_star", "E_abs_r", "B"]].nunique())
for tf in ["5m","15m","30m","1h","4h","1d"]:
    x = g[g.tf == tf]
    print(tf, "per-H unique n_min:", x.groupby("H")["n_min"].nunique().to_dict(), "mu*:", x.groupby("H")["mu_star"].first().round(5).to_dict())
fam = g[(g.n >= 100) & np.isfinite(g.p) & np.isfinite(g.p_vn)].copy()
m = len(fam)
def holm_indep(p):
    p = np.asarray(p, float); o = np.argsort(p, kind="mergesort"); m = len(p)
    adj_sorted = np.minimum(1.0, np.maximum.accumulate((m - np.arange(m)) * p[o]))
    out = np.empty(m); out[o] = adj_sorted; return out
ph = holm_indep(fam.p.values); pvh = holm_indep(fam.p_vn.values)
print("m =", m, "max |p_holm diff| =", np.max(np.abs(ph - fam.p_holm.values)), "max |p_vn_holm diff| =", np.max(np.abs(pvh - fam.p_vn_holm.values)))
try:
    from statsmodels.stats.multitest import multipletests
    print("statsmodels holm diff:", np.max(np.abs(multipletests(fam.p.values, method="holm")[1] - fam.p_holm.values)))
except Exception as e:
    print("statsmodels not available:", type(e).__name__)
sym = (fam.symbols_pos >= 4) | ((fam.n_coins_ge10 >= 1) & (fam.symbols_pos >= 0.6 * fam.n_coins_ge10))
dec = (ph < 0.05) & (pvh < 0.05) & (fam.fwd >= fam.mu_star) & sym & (fam.n >= 100)
dec_spec = (ph < 0.05) & (fam.fwd >= fam.mu_star) & sym & (fam.n >= 100)
print("independent gate_pass:", int(dec.sum()), "gate_pass_spec:", int(dec_spec.sum()))
# robustness of 'no survivor' to m: largest m at which the smallest p would pass Holm step 1
pmin = fam.p.min(); print("min p = %.3e -> would need m <= %d to pass Holm step 1" % (pmin, int(np.floor(0.05 / pmin))))
# Holm step 1 with c3&c4 cells only (what if family were restricted to hurdle-clearing cells?)
c34 = fam[(fam.fwd >= fam.mu_star) & sym]
print("cells with fwd>=mu* and symbols ok:", len(c34), "their min p = %.3e, min max(p,p_vn) = %.3e" % (c34.p.min(), np.maximum(c34.p, c34.p_vn).min()))
# what m would be needed for the best c3&c4 cell under max(p,p_vn)
print(c34.sort_values("p")[["strategy","tf","H","n","fwd","mu_star","z","p","z_vn","p_vn","symbols_pos","n_coins_ge10"]].to_string())
# the 15 p_vn_holm<0.05 cells
v = fam[fam.p_vn_holm < 0.05]
print("p_vn_holm<0.05 cells:", len(v)); print(v[["strategy","tf","H","n","fwd","mu_star","z","p","z_vn","p_vn_holm"]].to_string())
