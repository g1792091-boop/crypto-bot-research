"""Descriptive IS table (PREREG section 7.1) + carried.json.  Reads only combine/out/gate_all_is_applied.csv
(built from the Discover agents' raw harness gate tables) and harness/out/controls_n_required.csv."""
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.dirname(HERE)
os.environ.setdefault("SWEEP_DATA", os.path.join(HERE, "data"))
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as SL  # noqa: E402

OUT = os.path.join(HERE, "out")
g = pd.read_csv(os.path.join(OUT, "gate_all_is_applied.csv"))
nreq = pd.read_csv(os.path.join(SWEEP, "harness", "out", "controls_n_required.csv"))[["tf", "H", "n_req_iid", "n_req_burst4"]]
g = g.merge(nreq, on=["tf", "H"], how="left")
g["underpowered"] = g["n"] < g["n_req_iid"]          # PREREG section 9 label (synthetic iid n_req)
g["fwd_minus_mu_star"] = g["fwd"] - g["mu_star"]
TF_ORDER = list(SL.TFS)


def cell_code(r) -> str:
    """Verdict code of ONE (strategy, tf, H) cell (descriptive)."""
    if not np.isfinite(r["n"]) or r["n"] == 0:
        return "none"
    if r["n"] < SL.MIN_N:
        return "n<100"
    if bool(r["gate_pass"]):
        return "PASS"
    if r["fwd"] >= r["mu_star"]:
        return ">=hurdle, not sig"          # fwd >= mu* but Holm-adjusted p >= 0.05
    if r["p_holm"] < SL.ALPHA:
        return "sig but < hurdle"           # Holm-significant timing, fwd < mu*
    if r["z"] > 2:
        return "z>2 nominal, < hurdle"
    if r["fwd"] > r["cost_H"]:
        return "> cost, < hurdle"
    if r["fwd"] > 0:
        return "gross>0, < cost"
    return "gross<=0"


SHORT = {"PASS": "PASS", ">=hurdle, not sig": "HUR-ns", "sig but < hurdle": "SIG<hur",
         "z>2 nominal, < hurdle": "z2<hur", "> cost, < hurdle": "cost<hur", "gross>0, < cost": "g+<cost",
         "gross<=0": "g<=0", "n<100": "n<100", "none": "none"}
RANK = {"PASS": 8, ">=hurdle, not sig": 7, "sig but < hurdle": 6, "z>2 nominal, < hurdle": 5,
        "> cost, < hurdle": 4, "gross>0, < cost": 3, "gross<=0": 2, "n<100": 1, "none": 0}

g["verdict_cell"] = g.apply(cell_code, axis=1)
g["verdict_cell_short"] = g["verdict_cell"].map(SHORT)
g["pct"] = 100.0
long_cols = ["strategy", "tf", "H", "group", "approx", "prev_examined", "n", "n_long", "n_short", "fwd", "mu_star",
             "cost_H", "fwd_minus_mu_star", "net_time", "z", "p", "p_holm", "z_vn", "p_vn", "p_vn_holm",
             "symbols_pos", "n_coins_ge10", "sympos_ok", "in_family", "gate_pass", "gate_pass_spec", "n_req_iid",
             "underpowered", "verdict_cell"]
L = g[long_cols].copy()
for c in ["fwd", "mu_star", "cost_H", "fwd_minus_mu_star", "net_time"]:
    L[c + "_pct"] = 100 * L[c]
L.to_csv(os.path.join(HERE, "is_table_long.csv"), index=False)

# ---- best-H per (strategy, tf) ----------------------------------------------------------------
# Rule (descriptive, post hoc): among the cells with n >= 100, the H with the largest fwd - mu*;
# if no H has n >= 100, among cells with n > 0 (labelled n<100); if every H has n == 0 -> none.
rows = []
for (s, tf), grp in g.groupby(["strategy", "tf"]):
    fam = grp[grp["n"] >= SL.MIN_N]
    pos = grp[grp["n"] > 0]
    pick = fam if len(fam) else pos
    if len(pick):
        b = pick.sort_values(["fwd_minus_mu_star", "H"], ascending=[False, True]).iloc[0]
        best = dict(best_H=int(b["H"]), n=int(b["n"]), fwd_pct=100 * b["fwd"], z=b["z"], mu_star_pct=100 * b["mu_star"],
                    fwd_minus_mu_pct=100 * b["fwd_minus_mu_star"], net_time_pct=100 * b["net_time"],
                    p_holm=b["p_holm"], symbols_pos=int(b["symbols_pos"]), n_coins_ge10=int(b["n_coins_ge10"]),
                    underpowered=bool(b["underpowered"]), verdict=b["verdict_cell"])
    else:
        best = dict(best_H=np.nan, n=0, fwd_pct=np.nan, z=np.nan, mu_star_pct=np.nan, fwd_minus_mu_pct=np.nan,
                    net_time_pct=np.nan, p_holm=np.nan, symbols_pos=0, n_coins_ge10=0, underpowered=True,
                    verdict="none")
    # strongest status reached by ANY H (so a z>2 at another H is not hidden)
    any_v = max(grp["verdict_cell"], key=lambda v: RANK[v])
    best.update(strategy=s, tf=tf, verdict_anyH=any_v, max_z_anyH=float(grp.loc[grp["n"] >= SL.MIN_N, "z"].max())
                if (grp["n"] >= SL.MIN_N).any() else np.nan,
                group=grp["group"].iloc[0], approx=bool(grp["approx"].iloc[0]),
                prev_examined=bool(grp["prev_examined"].iloc[0]))
    rows.append(best)
B = pd.DataFrame(rows)
B["tf"] = pd.Categorical(B["tf"], TF_ORDER, ordered=True)
strat_order = list(SL.NAMES)
B["strategy"] = pd.Categorical(B["strategy"], strat_order, ordered=True)
B = B.sort_values(["strategy", "tf"]).reset_index(drop=True)
B.to_csv(os.path.join(OUT, "is_best_h_long.csv"), index=False)

# wide CSV: rows = strategy, columns = <tf>_<field>
fields = ["best_H", "n", "fwd_pct", "z", "fwd_minus_mu_pct", "net_time_pct", "verdict", "verdict_anyH", "underpowered"]
W = B.pivot(index="strategy", columns="tf", values=fields)
W.columns = [f"{tf}_{f}" for f, tf in W.columns]
W = W[[f"{tf}_{f}" for tf in TF_ORDER for f in fields]]
meta = B.groupby("strategy", observed=True)[["group", "approx", "prev_examined"]].first()
W = meta.join(W).reset_index()
for c in W.columns:
    if c.endswith(("_pct", "_z")):
        W[c] = pd.to_numeric(W[c]).round(4)
W.to_csv(os.path.join(HERE, "is_table.csv"), index=False)

# ---- counts -------------------------------------------------------------------------------------
def counts(df):
    nz = df[df["n"] > 0]
    fm = df[df["in_family"]]
    return dict(cells=len(df), cells_n_gt0=len(nz), family_n_ge100=len(fm),
                fwd_gt0_all=int((nz["fwd"] > 0).sum()), fwd_gt0_family=int((fm["fwd"] > 0).sum()),
                z_gt2_all=int((nz["z"] > 2).sum()), z_gt2_family=int((fm["z"] > 2).sum()),
                fwd_ge_mu_all=int((nz["fwd"] >= nz["mu_star"]).sum()), fwd_ge_mu_family=int((fm["fwd"] >= fm["mu_star"]).sum()),
                fwd_gt_cost_family=int((fm["fwd"] > fm["cost_H"]).sum()),
                p_lt05_family=int((fm["p"] < 0.05).sum()), p_vn_lt05_family=int((fm["p_vn"] < 0.05).sum()),
                holm_sig_p=int((fm["p_holm"] < 0.05).sum()), holm_sig_p_vn=int((fm["p_vn_holm"] < 0.05).sum()),
                gate_pass=int(df["gate_pass"].sum()), gate_pass_spec=int(df["gate_pass_spec"].sum()),
                underpowered_family=int(fm["underpowered"].sum()))


C = [dict(tf="ALL", **counts(g))] + [dict(tf=tf, **counts(g[g["tf"] == tf])) for tf in TF_ORDER]
C += [dict(tf=f"{tf}_H{H}", **counts(g[(g["tf"] == tf) & (g["H"] == H)])) for tf in TF_ORDER for H in SL.HS]
C = pd.DataFrame(C)
C.to_csv(os.path.join(HERE, "is_counts.csv"), index=False)
print(C.head(7).to_string())

# ---- markdown -------------------------------------------------------------------------------------
def fmt_cell(r):
    if r["verdict"] == "none":
        return "none"
    s = (f"{r['fwd_pct']:+.3f} / {r['z']:+.2f} / {r['fwd_minus_mu_pct']:+.3f} / {r['net_time_pct']:+.3f} "
         f"H{int(r['best_H'])} **{SHORT[r['verdict']]}**")
    if r["underpowered"] and r["verdict"] not in ("n<100", "none"):
        s += " (up)"
    if RANK[r["verdict_anyH"]] > RANK[r["verdict"]]:
        s += f" [any-H: {SHORT[r['verdict_anyH']]}]"
    return s


def label(s, m):
    t = s
    if m["approx"]:
        t += " (approx)"
    if m["prev_examined"]:
        t += " (prev. examined)"
    return t


sha_prereg = hashlib.sha256(open(os.path.join(SWEEP, "PREREG.md"), "rb").read()).hexdigest()
summ = json.load(open(os.path.join(OUT, "combine_summary.json")))
lines = []
lines.append("# IS gate table: strategy x timeframe (descriptive; PREREG section 7.1)\n")
lines.append(f"PREREG.md sha256 `{sha_prereg}`. IS window [2021-08-01, 2024-07-01), 7 coins, "
             f"37 strategies x 6 TF x H in {{4,16,64}} = 666 cells. Family (n >= 100, finite p and p_vn): "
             f"m = {summ['m_family']}. Holm first step needs p < {summ['holm_first_step_p']:.2e} "
             f"(z > {summ['holm_first_step_z']:.2f}). Smallest raw p in the family = {summ['min_p']:.2e} "
             f"(p_holm = {summ['min_p_holm']:.2f}).\n")
lines.append(f"**Decision: gate_pass survivors = {summ['n_gate_pass']}; gate_pass_spec (no A1, descriptive) = "
             f"{summ['n_gate_pass_spec']}. Nothing is carried to OOS.**\n")
lines.append("Cell = best H: `fwd% / z / (fwd - mu*)% / net_time% H<h> CODE`. fwd = pooled signed mean H-bar forward "
             "return per signal, before costs. net_time = fwd - cost_H. Best H = the H with the largest fwd - mu* "
             "among cells with n >= 100 (post hoc over 3 H, so it is biased upward; descriptive only). "
             "`(up)` = underpowered per PREREG section 9 (n < n_req iid). `[any-H: ...]` = a stronger code at another H.\n")
lines.append("Codes: PASS = gate_pass; HUR-ns = fwd >= mu* but Holm p >= 0.05; SIG<hur = Holm-significant but fwd < mu*; "
             "z2<hur = nominal z > 2, fwd < mu*; cost<hur = cost_H < fwd < mu*; g+<cost = 0 < fwd <= cost_H; "
             "g<=0 = fwd <= 0 (before costs); n<100 = best available H has 0 < n < 100; none = no signal at any H.\n")
hdr = "| strategy | " + " | ".join(TF_ORDER) + " |"
lines.append(hdr)
lines.append("|" + "---|" * (len(TF_ORDER) + 1))
metas = B.groupby("strategy", observed=True)[["approx", "prev_examined"]].first()
for s in strat_order:
    sub = B[B["strategy"] == s].set_index("tf")
    cells = [fmt_cell(sub.loc[tf]) if tf in sub.index else "" for tf in TF_ORDER]
    lines.append(f"| {label(s, metas.loc[s])} | " + " | ".join(cells) + " |")
lines.append("")
lines.append("## Counts (cells = strategy x TF x H)\n")
cc = C.set_index("tf")
lines.append("| scope | cells | n>0 | family (n>=100) | fwd>0 before costs (family / all n>0) | z>2 nominal (family / all) | "
             "fwd>cost_H (family) | fwd>=mu* (family / all) | p<0.05 raw (family) | Holm-sig p | Holm-sig p_vn | gate_pass | "
             "underpowered (family) |")
lines.append("|" + "---|" * 13)
for k in ["ALL"] + TF_ORDER:
    r = cc.loc[k]
    lines.append(f"| {k} | {r.cells} | {r.cells_n_gt0} | {r.family_n_ge100} | {r.fwd_gt0_family} / {r.fwd_gt0_all} | "
                 f"{r.z_gt2_family} / {r.z_gt2_all} | {r.fwd_gt_cost_family} | {r.fwd_ge_mu_family} / {r.fwd_ge_mu_all} | "
                 f"{r.p_lt05_family} | {r.holm_sig_p} | {r.holm_sig_p_vn} | {r.gate_pass} | {r.underpowered_family} |")
lines.append("")
lines.append("Per (tf, H) counts: `is_counts.csv`. All 666 cells with every statistic: `is_table_long.csv`. "
             "Wide CSV: `is_table.csv`.\n")
open(os.path.join(HERE, "is_table.md"), "w").write("\n".join(lines))

# ---- carried.json -----------------------------------------------------------------------------------
carried = dict(
    prereg_sha256=sha_prereg, stage="combine+IS exit", split_read="is only",
    m_family=summ["m_family"], holm_first_step_p=summ["holm_first_step_p"],
    n_gate_pass=summ["n_gate_pass"], n_gate_pass_spec=summ["n_gate_pass_spec"],
    gate_survivors=summ["survivors"], exit_stage_run_for=[], carried=[],
    note=("No (strategy, tf, H) cell passed the pre-registered gate (PREREG 4.4) over the whole family "
          f"(m={summ['m_family']}); smallest Holm-adjusted p = {summ['min_p_holm']:.3f}. Per PREREG section 5 the "
          "exit stage runs only for gate survivors, so no exit combo was selected and nothing is carried to OOS. "
          "The Holdout agent should still compute the full OOS gate table for persistence (PREREG 7.2)."),
)
json.dump(carried, open(os.path.join(HERE, "carried.json"), "w"), indent=2)
print("wrote is_table.csv/.md, is_table_long.csv, is_counts.csv, carried.json")
