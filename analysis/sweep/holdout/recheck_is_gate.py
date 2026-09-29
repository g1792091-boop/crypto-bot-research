"""Holdout agent: independent re-check of the Combine decision (reads only IS gate tables, no bars)."""
import glob, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import sweep_lib as L
S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fs = sorted(glob.glob(f"{S}/discover_*/out/gate_is_*.csv"))
print("raw IS tables:", [os.path.relpath(f, S) for f in fs])
g = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
k = ["strategy", "tf", "H"]
assert not g.duplicated(k).any(), "dup"
print("rows", len(g), "strategies", g.strategy.nunique(), "tfs", sorted(g.tf.unique()))
a = L.apply_gate(g)
print("m_family", int(a.m_family.iloc[0]), "gate_pass", int(a.gate_pass.sum()), "gate_pass_spec", int(a.gate_pass_spec.sum()))
fam = a[a.in_family]
print("min p", fam.p.min(), "min p_holm", fam.p_holm.min())
c = pd.read_csv(f"{S}/combine/out/gate_all_is_applied.csv")
m = a.merge(c[k + ["p_holm", "p_vn_holm", "gate_pass", "in_family"]], on=k, suffixes=("", "_c"))
print("max |p_holm diff|", np.nanmax(np.abs(m.p_holm - m.p_holm_c)), "gate_pass equal", bool((m.gate_pass == m.gate_pass_c).all()),
      "in_family equal", bool((m.in_family == m.in_family_c).all()))
a.to_csv("out/is_applied_recheck.csv", index=False)
