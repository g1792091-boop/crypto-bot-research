"""Holdout agent: assemble the OOS and FINAL gate tables (same harness code as IS) and apply the
PREREG gate columns to each split's own cells.  The per-split Holm columns are DESCRIPTIVE ONLY:
under PREREG 6 only carried combos are confirmed, and carried = [] (combine/carried.json)."""
import glob, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
K = ["strategy", "tf", "H"]
out = {}
for split in ("oos", "final"):
    fs = sorted(glob.glob(os.path.join(HERE, "out", f"gate_{split}_*.csv")))
    g = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    assert not g.duplicated(K).any(), f"{split}: duplicate cells"
    exp = {(s, t, h) for s in L.NAMES for t in L.TFS for h in L.HS}
    got = set(map(tuple, g[K].itertuples(index=False)))
    print(f"{split}: {len(fs)} tables, {len(g)} rows; missing {len(exp - got)}; extra {len(got - exp)}")
    assert got == exp
    a = L.apply_gate(g)
    a = a.rename(columns={"gate_pass": "gate_pass_DESCRIPTIVE_own_family", "gate_pass_spec": "gate_pass_spec_DESCRIPTIVE_own_family"})
    fam = a[a["in_family"]]
    print(f"  {split}: family m={int(a['m_family'].iloc[0])}, min p={fam['p'].min():.3g}, min p_holm={fam['p_holm'].min():.3g}, "
          f"gate_pass(own family, descriptive)={int(a['gate_pass_DESCRIPTIVE_own_family'].sum())}, "
          f"spec={int(a['gate_pass_spec_DESCRIPTIVE_own_family'].sum())}, Holm-sig p_vn={int((fam['p_vn_holm'] < 0.05).sum())}")
    print("  n-range per tf:", a.groupby("tf")["n"].agg(["min", "median", "max"]).to_dict("index"))
    a.to_csv(os.path.join(HERE, "out", f"gate_all_{split}_applied.csv"), index=False)
    out[split] = a
is_ = pd.read_csv(os.path.join(os.path.dirname(HERE), "combine", "out", "gate_all_is_applied.csv"))
keep = K + ["group", "approx", "prev_examined", "n", "n_long", "n_short", "fwd", "fwd_long", "fwd_short", "mu_star",
            "cost_H", "E_abs_r", "fwd_minus_hurdle", "net_time", "z", "p", "z_vn", "p_vn", "symbols_pos",
            "n_coins_ge10", "in_family", "p_holm", "p_vn_holm"]
m = is_[keep + ["gate_pass", "gate_pass_spec"]].rename(columns={c: c + "_is" for c in keep[3:] + ["gate_pass", "gate_pass_spec"]})
for split in ("oos", "final"):
    b = out[split][keep].rename(columns={c: c + "_" + split for c in keep[3:]})
    m = m.merge(b, on=K, how="outer")
for c in ("group", "approx", "prev_examined"):
    assert (m[c + "_is"] == m[c + "_oos"]).all() and (m[c + "_is"] == m[c + "_final"]).all()
    m[c] = m[c + "_is"]
    m = m.drop(columns=[c + "_is", c + "_oos", c + "_final"])
m.to_csv(os.path.join(HERE, "out", "cells_is_oos_final_long.csv"), index=False)
print("wrote out/cells_is_oos_final_long.csv", m.shape)
