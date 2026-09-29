"""Descriptive strategy x TF table: the IS best H (combine/out/is_best_h_long.csv, chosen on IS only) evaluated
at that SAME H on OOS and FINAL.  Out-of-sample honest for the H choice (H picked on IS only)."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
S = os.path.dirname(HERE); O = os.path.join(HERE, "out")
K = ["strategy", "tf", "H"]
B = pd.read_csv(os.path.join(S, "combine", "out", "is_best_h_long.csv"))
M = pd.read_csv(os.path.join(O, "persistence_merged_cells.csv"))

def code(n, fwd, mu, cost, z):
    if not np.isfinite(n) or n == 0: return "none"
    if n < 100: return "n<100"
    if fwd >= mu: return "HUR"
    if z > 2: return "z2<hur"
    if fwd > cost: return "cost<hur"
    if fwd > 0: return "g+<cost"
    return "g<=0"

rows = []
for _, b in B.iterrows():
    r = dict(strategy=b.strategy, tf=b.tf, is_best_H=b.best_H, is_verdict=b.verdict, approx=b.approx, prev_examined=b.prev_examined)
    if np.isfinite(b.best_H):
        m = M[(M.strategy == b.strategy) & (M.tf == b.tf) & (M.H == int(b.best_H))].iloc[0]
        for s, lab in (("is", "is"), ("oos", "oos"), ("fin", "final")):
            r.update({f"{lab}_n": m[f"n_{s}"], f"{lab}_fwd_pct": 100 * m[f"fwd_{s}"], f"{lab}_mu_pct": 100 * m[f"mu_star_{s}"],
                      f"{lab}_fwd_over_mu": m[f"ratio_{s}"], f"{lab}_net_time_pct": 100 * m[f"net_time_{s}"], f"{lab}_z": m[f"z_{s}"],
                      f"{lab}_p_vn": m[f"p_vn_{s}"], f"{lab}_symbols_pos": m[f"symbols_pos_{s}"],
                      f"{lab}_code": code(m[f"n_{s}"], m[f"fwd_{s}"], m[f"mu_star_{s}"], m[f"cost_H_{s}"], m[f"z_{s}"])})
    rows.append(r)
T = pd.DataFrame(rows)
T.to_csv(os.path.join(O, "oos_table_isbestH_long.csv"), index=False)

def fmt(r, lab):
    if not np.isfinite(r.get(f"{lab}_n", np.nan)) or r[f"{lab}_n"] == 0:
        return "none"
    return f"{r[f'{lab}_fwd_over_mu']:+.2f}/{r[f'{lab}_z']:+.1f} {r[f'{lab}_code']}"

lines = ["# OOS / FINAL strategy x timeframe table (descriptive)", "",
         "Each cell uses the best H chosen on IS only (`combine/out/is_best_h_long.csv`: largest IS fwd - mu* among n>=100 cells). "
         "It shows `IS ratio -> OOS ratio/z code | FINAL ratio`, where ratio = fwd / mu* (pooled signed H-bar forward return per signal, "
         "before costs, divided by the pre-registered hurdle mu* = cost_H + 0.091 E|r_H| of that split). ratio >= 1 clears the hurdle; "
         "ratio <= 0 means signals do no better than zero gross. z = common-shift-null z of that split (raw, not multiplicity-adjusted).",
         "", "OOS codes: HUR = fwd >= mu*; z2<hur = z > 2 but below hurdle; cost<hur = beats cost_H only; g+<cost = gross > 0 but below cost; "
         "g<=0 = gross <= 0; n<100 = fewer than 100 signals in that split; none = no signal.", "",
         "Nothing here is a confirmation: no cell passed the IS gate, so PREREG 6 had nothing to confirm.", "",
         "| strategy | " + " | ".join(L.TFS) + " |", "|---|" + "---|" * len(L.TFS)]
for s in L.NAMES:
    sub = T[T.strategy == s].set_index("tf")
    tag = " (approx)" if bool(sub.approx.iloc[0]) else ""
    tag += " (prev. examined)" if bool(sub.prev_examined.iloc[0]) else ""
    cells = []
    for tf in L.TFS:
        r = sub.loc[tf]
        if not np.isfinite(r.is_best_H):
            cells.append("none"); continue
        cells.append(f"H{int(r.is_best_H)}: {r.is_fwd_over_mu:+.2f} -> {fmt(r, 'oos')} \\| F {r.final_fwd_over_mu:+.2f}"
                     if np.isfinite(r.get('final_fwd_over_mu', np.nan)) else f"H{int(r.is_best_H)}: {r.is_fwd_over_mu:+.2f} -> {fmt(r, 'oos')} \\| F none")
    lines.append(f"| {s}{tag} | " + " | ".join(cells) + " |")
# counts per TF at IS-best-H
lines += ["", "## Counts at the IS-chosen H (cells with n >= 100 in both IS and OOS)", "",
          "| TF | cells | IS ratio>=1 | OOS ratio>=1 | OOS gross>0 | OOS net>0 (beats cost_H) | OOS z>2 | median IS ratio | median OOS ratio | median FINAL ratio |",
          "|---|---|---|---|---|---|---|---|---|---|"]
cnt = []
for tf in L.TFS:
    d = T[(T.tf == tf) & (T.is_n >= 100) & (T.oos_n >= 100)]
    c = dict(tf=tf, cells=len(d), is_ge1=int((d.is_fwd_over_mu >= 1).sum()), oos_ge1=int((d.oos_fwd_over_mu >= 1).sum()),
             oos_gross_pos=int((d.oos_fwd_pct > 0).sum()), oos_net_pos=int((d.oos_net_time_pct > 0).sum()),
             oos_z2=int((d.oos_z > 2).sum()), med_is=d.is_fwd_over_mu.median(), med_oos=d.oos_fwd_over_mu.median(),
             med_fin=d.final_fwd_over_mu.median())
    cnt.append(c)
    lines.append(f"| {tf} | {c['cells']} | {c['is_ge1']} | {c['oos_ge1']} | {c['oos_gross_pos']} | {c['oos_net_pos']} | {c['oos_z2']} | "
                 f"{c['med_is']:+.2f} | {c['med_oos']:+.2f} | {c['med_fin']:+.2f} |")
pd.DataFrame(cnt).to_csv(os.path.join(O, "oos_table_isbestH_counts.csv"), index=False)
open(os.path.join(HERE, "oos_table.md"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
