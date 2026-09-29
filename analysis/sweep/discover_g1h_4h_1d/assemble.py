"""Assemble gate_cells.csv (1h + 4h + 1d) and the top-15 tables.  No Holm is applied here
(PREREG 4.3: Holm once over the whole 6-TF family, by the Combine agent).
All harness columns are kept under their harness names (apply_gate() needs n, p, p_vn, fwd,
mu_star, symbols_pos, n_coins_ge10); the task's requested names are added as aliases."""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

OUT = os.path.join(HERE, "out")
SW = os.path.dirname(HERE)
g = pd.concat([pd.read_csv(os.path.join(OUT, f"gate_is_{tf}.csv")) for tf in ("1h", "4h", "1d")], ignore_index=True)

# requested aliases
g["fwd_pct"] = g["fwd"] * 100.0
g["p_one_sided"] = g["p"]
g["E_abs_rH"] = g["E_abs_r"]
g["previously_examined"] = g["prev_examined"]
g["fwd_minus_mu_star"] = g["fwd_minus_hurdle"]
for c in L.COINS:
    g[f"fwd_pct_{c}"] = g[f"fwd_{c}"] * 100.0

# PREREG section 9 'underpowered' label: n < n_req(tf, H) from the synthetic iid control
nreq = pd.read_csv(os.path.join(SW, "harness", "out", "controls_n_required.csv"))
g = g.merge(nreq[["tf", "H", "n_req_iid", "n_req_burst4"]], on=["tf", "H"], how="left")
g["underpowered"] = g["n"] < g["n_req_iid"]
# family candidate (PREREG 4.3 membership condition; the family itself is formed by Combine)
g["family_candidate"] = (g["n"] >= L.MIN_N) & np.isfinite(g["p"]) & np.isfinite(g["p_vn"])
g["sympos_ok"] = L.sympos_ok(g["symbols_pos"], g["n_coins_ge10"])
# INDICATIVE only (not a decision): p below alpha/666 is sufficient for the Holm part if m <= 666
thr = L.ALPHA / 666
g["p_lt_alpha_over_666"] = g["p"] < thr
g["p_vn_lt_alpha_over_666"] = g["p_vn"] < thr

front = ["strategy", "tf", "H", "group", "approx", "previously_examined", "n", "n_long", "n_short", "fwd_pct",
         "fwd", "fwd_long", "fwd_short"] + [f"fwd_{c}" for c in L.COINS] + [f"n_{c}" for c in L.COINS] + \
        ["symbols_pos", "n_coins_ge10", "null_mean", "null_sd", "z", "p_one_sided", "p", "fwd_vn", "z_vn", "p_vn",
         "p_emp600", "p_emp_all", "t_naive", "cost_H", "E_abs_rH", "E_abs_r", "mu_star", "net_time",
         "fwd_minus_mu_star", "fwd_minus_hurdle", "family_candidate", "sympos_ok", "n_req_iid", "n_req_burst4",
         "underpowered", "p_lt_alpha_over_666", "p_vn_lt_alpha_over_666"]
rest = [c for c in g.columns if c not in front]
g = g[front + rest]
g.to_csv(os.path.join(HERE, "gate_cells.csv"), index=False)

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)
show = ["strategy", "tf", "H", "n", "fwd_pct", "mu_star", "fwd_minus_mu_star", "z", "p", "z_vn", "p_vn",
        "p_emp_all", "symbols_pos", "n_coins_ge10", "approx", "previously_examined", "underpowered"]


def fmt(d):
    d = d[show].copy()
    d["mu_star"] = d["mu_star"] * 100
    d["fwd_minus_mu_star"] = d["fwd_minus_mu_star"] * 100
    d = d.rename(columns={"mu_star": "mu*_pct", "fwd_minus_mu_star": "fwd-mu*_pct"})
    return d


fam = g[g["family_candidate"]]
tabs = {
    "top15_by_z_n100": fam.sort_values("z", ascending=False).head(15),
    "top15_by_fwd_minus_mu_n100": fam.sort_values("fwd_minus_mu_star", ascending=False).head(15),
    "top15_by_z_all": g.sort_values("z", ascending=False).head(15),
    "top15_by_fwd_minus_mu_all": g.sort_values("fwd_minus_mu_star", ascending=False).head(15),
}
with open(os.path.join(HERE, "top15.txt"), "w") as f:
    for k, d in tabs.items():
        fmt(d).to_csv(os.path.join(HERE, f"{k}.csv"), index=False)
        s = f"== {k} ==\n" + fmt(d).to_string(index=False, float_format=lambda x: f"{x:.4g}") + "\n\n"
        f.write(s)
        print(s)

# summary counts
summ = []
for (tf, H), d in g.groupby(["tf", "H"]):
    f_ = d[d["family_candidate"]]
    summ.append(dict(tf=tf, H=H, cells=len(d), n_ge100=len(f_), mu_star_pct=d["mu_star"].iloc[0] * 100,
                     E_abs_r_pct=d["E_abs_r"].iloc[0] * 100, cost_H_pct=d["cost_H"].iloc[0] * 100,
                     fwd_ge_mu=int((f_["fwd"] >= f_["mu_star"]).sum()), net_time_pos=int((f_["net_time"] > 0).sum()),
                     fwd_pos=int((f_["fwd"] > 0).sum()), p05=int((f_["p"] < 0.05).sum()),
                     pvn05=int((f_["p_vn"] < 0.05).sum()), both05=int(((f_["p"] < 0.05) & (f_["p_vn"] < 0.05)).sum()),
                     p_lt_thr=int(f_["p_lt_alpha_over_666"].sum()), pvn_lt_thr=int(f_["p_vn_lt_alpha_over_666"].sum()),
                     z_mean=f_["z"].mean(), z_sd=f_["z"].std(ddof=1), zvn_mean=f_["z_vn"].mean(),
                     zvn_sd=f_["z_vn"].std(ddof=1), z_max=f_["z"].max(), zvn_max=f_["z_vn"].max(),
                     underpowered=int(f_["underpowered"].sum())))
summ = pd.DataFrame(summ)
summ.to_csv(os.path.join(HERE, "gate_summary_by_tf_H.csv"), index=False)
print(summ.round(4).to_string(index=False))
