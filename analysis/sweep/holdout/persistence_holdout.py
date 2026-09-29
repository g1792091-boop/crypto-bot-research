"""Holdout agent, PREREG 7.2/7.3 (DESCRIPTIVE ONLY).
 - verbatim sweep_lib.persistence(IS, OOS): Spearman of (fwd - mu*) over all common finite cells + top-10 IS cells by z
 - same on the n>=100-in-both subset; per-TF and within-(TF,H) Spearman; stratified permutation benchmark
 - share of IS 'sig' cells that stay positive in OOS (and FINAL), vs base rates
 - per-TF medians of fwd - mu* (IS / OOS / FINAL)
"""
import os, sys, json
import numpy as np, pandas as pd
from scipy.stats import spearmanr, fisher_exact
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
O = os.path.join(HERE, "out")
K = ["strategy", "tf", "H"]
TFO = {t: i for i, t in enumerate(L.TFS)}
S = os.path.dirname(HERE)
IS = pd.read_csv(os.path.join(S, "combine", "out", "gate_all_is_applied.csv"))
OOS = pd.read_csv(os.path.join(O, "gate_all_oos_applied.csv"))
FIN = pd.read_csv(os.path.join(O, "gate_all_final_applied.csv"))
res = {}

# ---------- 1. verbatim pre-registered persistence ----------
pv = L.persistence(IS, OOS, top=10)
res["verbatim"] = dict(n_cells=pv["n_cells"], spearman=pv["spearman"], spearman_p=pv["spearman_p"])
top = pv["top"].copy()
top = top.merge(IS[K + ["in_family", "approx", "prev_examined", "p_holm"]], on=K)
top = top.merge(OOS[K + ["z_vn", "p_vn", "symbols_pos", "n_coins_ge10", "cost_H", "net_time"]], on=K)
top.to_csv(os.path.join(O, "persistence_verbatim_top10.csv"), index=False)
print("VERBATIM persistence (sweep_lib.persistence, all common finite cells):", res["verbatim"])
print(top[K + ["n_is", "z_is", "fwd_minus_hurdle_is", "n_oos", "fwd", "mu_star", "fwd_minus_hurdle_oos", "z_oos", "p", "p_vn", "symbols_pos", "in_family"]].to_string())

# ---------- merged frame ----------
cols = ["n", "fwd", "mu_star", "cost_H", "fwd_minus_hurdle", "net_time", "z", "p", "z_vn", "p_vn", "symbols_pos", "n_coins_ge10", "in_family"]
M = IS[K + ["approx", "prev_examined", "group", "p_holm"] + cols].rename(columns={c: c + "_is" for c in cols})
M = M.merge(OOS[K + cols].rename(columns={c: c + "_oos" for c in cols}), on=K).merge(
    FIN[K + cols].rename(columns={c: c + "_fin" for c in cols}), on=K)
for s in ("is", "oos", "fin"):
    M[f"ratio_{s}"] = M[f"fwd_{s}"] / M[f"mu_star_{s}"]
M.to_csv(os.path.join(O, "persistence_merged_cells.csv"), index=False)

def sp(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return (np.nan, np.nan, int(ok.sum()))
    r, p = spearmanr(a[ok], b[ok])
    return (float(r), float(p), int(ok.sum()))

rows = []
def add(label, sub, x, y, sx="is", sy="oos"):
    r, p, n = sp(sub[f"{x}_{sx}"].to_numpy(float), sub[f"{y}_{sy}"].to_numpy(float))
    rows.append(dict(comparison=f"{sx.upper()} vs {sy.upper()}", subset=label, stat=x, n_cells=n, spearman=r, p=p))

fin_ok = lambda d, s: np.isfinite(d[f"fwd_minus_hurdle_{s}"])
allc = M[fin_ok(M, "is") & fin_ok(M, "oos")]
both100 = M[(M.n_is >= 100) & (M.n_oos >= 100)]
for lab, sub in (("all common finite", allc), ("n>=100 in both", both100)):
    for st in ("fwd_minus_hurdle", "z", "ratio", "net_time"):
        add(lab, sub, st, st)
for tf in L.TFS:
    sub = both100[both100.tf == tf]
    for st in ("fwd_minus_hurdle", "z"):
        add(f"n>=100 in both, tf={tf}", sub, st, st)
for (tf, H), sub in both100.groupby(["tf", "H"]):
    add(f"n>=100 in both, tf={tf} H={H}", sub, "fwd_minus_hurdle", "fwd_minus_hurdle")
# FINAL comparisons (descriptive)
bothF = M[(M.n_is >= 100) & (M.n_fin >= 100)]
bothOF = M[(M.n_oos >= 100) & (M.n_fin >= 100)]
for st in ("fwd_minus_hurdle", "z"):
    add("n>=100 in both", bothF, st, st, "is", "fin")
    add("n>=100 in both", bothOF, st, st, "oos", "fin")
SP = pd.DataFrame(rows)
SP.to_csv(os.path.join(O, "persistence_spearman.csv"), index=False)
print("\nSPEARMAN table:")
print(SP.to_string())

# ---------- stratified permutation benchmark for the verbatim statistic ----------
# Null: IS and OOS values unrelated WITHIN each (tf,H) stratum; keeps the between-stratum mu* structure.
rng = np.random.default_rng([L.SEED, 72])
def strat_perm(sub, x, y, B=5000):
    sub = sub.reset_index(drop=True)
    a = sub[x].to_numpy(float); b = sub[y].to_numpy(float)
    groups = [np.flatnonzero(((sub.tf == tf) & (sub.H == H)).to_numpy()) for (tf, H) in sub[["tf", "H"]].drop_duplicates().itertuples(index=False)]
    obs = spearmanr(a, b)[0]
    null = np.empty(B)
    for i in range(B):
        bb = b.copy()
        for g in groups:
            bb[g] = b[rng.permutation(g)]
        null[i] = spearmanr(a, bb)[0]
    return dict(obs=float(obs), null_mean=float(null.mean()), null_sd=float(null.std(ddof=1)),
                null_q025=float(np.quantile(null, 0.025)), null_q975=float(np.quantile(null, 0.975)),
                p_one_sided=float((1 + (null >= obs).sum()) / (B + 1)), B=B, n=len(sub))
res["strat_perm_all_common"] = strat_perm(allc, "fwd_minus_hurdle_is", "fwd_minus_hurdle_oos")
res["strat_perm_n100_both"] = strat_perm(both100, "fwd_minus_hurdle_is", "fwd_minus_hurdle_oos")
res["strat_perm_n100_both_z"] = strat_perm(both100, "z_is", "z_oos")
print("\nStratified (within tf x H) permutation benchmark:", json.dumps({k: res[k] for k in res if k.startswith("strat")}, indent=1))

# ---------- within-stratum average Spearman ----------
ws = SP[SP.subset.str.contains(" H=")]
res["within_tfH_mean_spearman_fwdmh"] = float(ws.spearman.mean())
res["within_tfH_median_spearman_fwdmh"] = float(ws.spearman.median())
res["within_tfH_n_strata_positive"] = f"{int((ws.spearman > 0).sum())}/{len(ws)}"

# ---------- top-10 family IS cells by z (supplement to the verbatim top-10) ----------
famtop = M[M.in_family_is].sort_values("z_is", ascending=False).head(10)
famtop.to_csv(os.path.join(O, "persistence_family_top10_by_is_z.csv"), index=False)
print("\nTop-10 FAMILY (n>=100) IS cells by z: IS vs OOS vs FINAL")
print(famtop[K + ["approx", "prev_examined", "n_is", "z_is", "ratio_is", "n_oos", "fwd_oos", "mu_star_oos", "ratio_oos", "z_oos", "p_oos", "p_vn_oos", "symbols_pos_oos", "n_fin", "ratio_fin", "z_fin"]].to_string())

# ---------- share of IS 'sig' cells that stay positive ----------
fam = M[M.in_family_is].copy()
defs = {"IS p<0.05 (family)": fam.p_is < 0.05, "IS z>2 (family)": fam.z_is > 2,
        "IS fwd>=mu* (family near-miss 15)": fam.fwd_is >= fam.mu_star_is,
        "IS p<0.05 & fwd>0 (family)": (fam.p_is < 0.05) & (fam.fwd_is > 0),
        "IS p<0.05 & p_vn<0.05 (family)": (fam.p_is < 0.05) & (fam.p_vn_is < 0.05)}
srows = []
for lab, msk in defs.items():
    for s, sl in (("oos", "OOS"), ("fin", "FINAL")):
        for grp, mm in (("IS-sig", msk), ("IS-not-sig (base)", ~msk)):
            d = fam[mm & np.isfinite(fam[f"fwd_{s}"])]
            srows.append(dict(definition=lab, split=sl, group=grp, cells=len(d),
                              fwd_pos=int((d[f"fwd_{s}"] > 0).sum()), share_fwd_pos=float((d[f"fwd_{s}"] > 0).mean()) if len(d) else np.nan,
                              z_pos=int((d[f"z_{s}"] > 0).sum()), share_z_pos=float((d[f"z_{s}"] > 0).mean()) if len(d) else np.nan,
                              p_lt_05=int((d[f"p_{s}"] < 0.05).sum()),
                              net_pos=int((d[f"net_time_{s}"] > 0).sum()),
                              fwd_ge_mu=int((d[f"fwd_{s}"] >= d[f"mu_star_{s}"]).sum()),
                              p_and_pvn_lt_05=int(((d[f"p_{s}"] < 0.05) & (d[f"p_vn_{s}"] < 0.05)).sum()),
                              n_ge100=int((d[f"n_{s}"] >= 100).sum())))
SH = pd.DataFrame(srows)
# Fisher exact: IS-sig vs base on OOS fwd>0 (descriptive; cells are not independent)
fis = []
for lab in defs:
    for sl in ("OOS", "FINAL"):
        a = SH[(SH.definition == lab) & (SH.split == sl)].set_index("group")
        t = [[a.loc["IS-sig", "fwd_pos"], a.loc["IS-sig", "cells"] - a.loc["IS-sig", "fwd_pos"]],
             [a.loc["IS-not-sig (base)", "fwd_pos"], a.loc["IS-not-sig (base)", "cells"] - a.loc["IS-not-sig (base)", "fwd_pos"]]]
        fis.append(dict(definition=lab, split=sl, fisher_p_greater=float(fisher_exact(t, alternative="greater")[1])))
SH = SH.merge(pd.DataFrame(fis), on=["definition", "split"])
SH.to_csv(os.path.join(O, "persistence_sig_share.csv"), index=False)
print("\nShare of IS-sig cells staying positive:")
print(SH.to_string())

# ---------- the 15 IS near-miss cells (fwd >= mu*, failed Holm): OOS and FINAL ----------
nm = M[M.in_family_is & (M.fwd_is >= M.mu_star_is)].sort_values("z_is", ascending=False)
nm.to_csv(os.path.join(O, "nearmiss15_is_oos_final.csv"), index=False)
print("\n15 IS near-miss cells:")
print(nm[K + ["approx", "prev_examined", "n_is", "fwd_is", "mu_star_is", "z_is", "n_oos", "fwd_oos", "mu_star_oos", "z_oos", "p_oos", "p_vn_oos", "symbols_pos_oos", "n_coins_ge10_oos", "n_fin", "fwd_fin", "mu_star_fin", "z_fin"]].to_string())

# ---------- per-TF medians: IS / OOS / FINAL ----------
def tf_table(df, s, label):
    out = []
    for tf in L.TFS:
        d = df[(df.tf == tf)]
        d = d[np.isfinite(d[f"fwd_{s}"])]
        out.append(dict(scope=label, split={"is": "IS", "oos": "OOS", "fin": "FINAL"}[s], tf=tf, cells=len(d),
                        median_fwd_minus_mu_pct=100 * d[f"fwd_minus_hurdle_{s}"].median(),
                        median_fwd_over_mu=d[f"ratio_{s}"].median(),
                        median_net_time_pct=100 * d[f"net_time_{s}"].median(),
                        median_fwd_pct=100 * d[f"fwd_{s}"].median(),
                        mean_z=d[f"z_{s}"].mean(), median_z=d[f"z_{s}"].median(),
                        share_fwd_pos=(d[f"fwd_{s}"] > 0).mean(), share_net_pos=(d[f"net_time_{s}"] > 0).mean(),
                        n_fwd_ge_mu=int((d[f"fwd_{s}"] >= d[f"mu_star_{s}"]).sum()),
                        max_fwd_over_mu=d[f"ratio_{s}"].max(),
                        median_mu_star_pct=100 * d[f"mu_star_{s}"].median()))
    return out
tr = []
for s in ("is", "oos", "fin"):
    tr += tf_table(M[M[f"n_{s}"] >= 100], s, "n>=100 in that split")
common = M[(M.n_is >= 100) & (M.n_oos >= 100)]
for s in ("is", "oos", "fin"):
    tr += tf_table(common, s, "common: n>=100 in IS and OOS")
common3 = M[(M.n_is >= 100) & (M.n_oos >= 100) & (M.n_fin >= 100)]
for s in ("is", "oos", "fin"):
    tr += tf_table(common3, s, "common3: n>=100 in IS, OOS and FINAL")
TT = pd.DataFrame(tr)
TT.to_csv(os.path.join(O, "tf_summary.csv"), index=False)
print("\nPer-TF summary:")
pd.set_option("display.width", 250)
print(TT.round(4).to_string())
# per TF x H (common set)
th = []
for (tf, H), d in common.groupby(["tf", "H"]):
    for s in ("is", "oos", "fin"):
        dd = d[np.isfinite(d[f"fwd_{s}"])]
        th.append(dict(tf=tf, H=H, split=s, cells=len(dd), median_fwd_minus_mu_pct=100 * dd[f"fwd_minus_hurdle_{s}"].median(),
                       median_fwd_over_mu=dd[f"ratio_{s}"].median(), median_net_time_pct=100 * dd[f"net_time_{s}"].median(),
                       share_fwd_pos=(dd[f"fwd_{s}"] > 0).mean(), n_fwd_ge_mu=int((dd[f"fwd_{s}"] >= dd[f"mu_star_{s}"]).sum()),
                       mu_star_pct=100 * dd[f"mu_star_{s}"].median()))
TH = pd.DataFrame(th)
TH["tfo"] = TH.tf.map(TFO)
TH = TH.sort_values(["tfo", "H", "split"]).drop(columns="tfo")
TH.to_csv(os.path.join(O, "tf_h_summary_common.csv"), index=False)
print(TH.round(4).to_string())
json.dump(res, open(os.path.join(O, "persistence_summary.json"), "w"), indent=1, default=float)
print(json.dumps(res, indent=1, default=float))
