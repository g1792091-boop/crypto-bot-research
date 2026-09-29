"""HYPOTHETICAL what-if (NOT the pre-registered verdict; nothing was carried).
If the Combine agent's descriptive IS exit runs on the 15 near-miss cells had been fed to
sweep_lib.select_exits (i.e. if the Holm gate had been ignored), which (strategy, tf) combos would have
been selected, and would sweep_lib.holdout_confirm have passed them on OOS?  Also shows FINAL."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
S = os.path.dirname(HERE)
O = os.path.join(HERE, "out")
K = ["strategy", "tf", "H"]
e = pd.read_csv(os.path.join(S, "combine", "out", "exits_descriptive_nearmiss_all.csv"))
sel = L.select_exits(e.rename(columns={"exit_criteria_met_DESCRIPTIVE": "exit_pass"}))
print("Hypothetical IS selection (select_exits over descriptive near-miss exits):")
print(sel[K + ["exit", "trades", "pf", "exp_net", "symbols_pos", "p_max"]].to_string())
import glob
ex = {s: pd.concat([pd.read_csv(f) for f in glob.glob(os.path.join(O, f"exits_descriptive_{s}_*.csv"))], ignore_index=True)
      for s in ("oos", "final")}
g = {"oos": pd.read_csv(os.path.join(O, "gate_all_oos_applied.csv")), "final": pd.read_csv(os.path.join(O, "gate_all_final_applied.csv"))}
rows = []
for _, r in sel.iterrows():
    row = dict(strategy=r.strategy, tf=r.tf, H=int(r.H), exit=r.exit, is_trades=r.trades, is_pf=r.pf, is_exp_net=r.exp_net,
               is_symbols_pos=r.symbols_pos, is_p_max=r.p_max)
    for s in ("oos", "final"):
        xr = ex[s][(ex[s].strategy == r.strategy) & (ex[s].tf == r.tf) & (ex[s].H == r.H) & (ex[s].exit == r.exit)].iloc[0].to_dict()
        gc = g[s][(g[s].strategy == r.strategy) & (g[s].tf == r.tf) & (g[s].H == r.H)].iloc[0].to_dict()
        hc = L.holdout_confirm(xr, gc)
        row.update({f"{s}_trades": xr["trades"], f"{s}_pf": xr["pf"], f"{s}_exp_net": xr["exp_net"], f"{s}_sum_net": xr["sum_net"],
                    f"{s}_symbols_pos": xr["symbols_pos"], f"{s}_months_pos": xr["months_pos"], f"{s}_months": xr["months"],
                    f"{s}_p_max": xr["p_max"], f"{s}_gate_n": gc["n"], f"{s}_gate_fwd": gc["fwd"], f"{s}_gate_mu_star": gc["mu_star"],
                    f"{s}_gate_z": gc["z"], f"{s}_gate_p": gc["p"], f"{s}_gate_p_vn": gc["p_vn"],
                    **{f"{s}_{k}": v for k, v in hc.items()}})
    rows.append(row)
W = pd.DataFrame(rows)
W["label"] = "HYPOTHETICAL what-if; NOT carried; NOT a confirmation"
W.to_csv(os.path.join(O, "whatif_hypothetical_carry.csv"), index=False)
pd.set_option("display.width", 250)
print(W.T.to_string())
