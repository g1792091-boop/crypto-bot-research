"""Combine step (PREREG section 4.3/4.4/11): concatenate all 6 TF gate tables, apply
sweep_lib.apply_gate ONCE over the whole family, list survivors.  IS only."""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.dirname(HERE)
os.environ.setdefault("SWEEP_DATA", os.path.join(HERE, "data"))   # exposes only is/
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as SL  # noqa: E402

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

# 1. raw harness tables (sweep_lib.gate output, untouched by the Discover agents' assembly)
raw_files = sorted(glob.glob(os.path.join(SWEEP, "discover_*", "out", "gate_is_*.csv")))
raw = pd.concat([pd.read_csv(f).assign(src_file=os.path.relpath(f, SWEEP)) for f in raw_files], ignore_index=True)
key = ["strategy", "tf", "H"]
dup = raw.duplicated(key).sum()
print("raw files:", len(raw_files), "rows:", len(raw), "dups:", dup)
assert dup == 0
assert set(raw["split"]) == {"is"}, raw["split"].unique()
exp = {(s, tf, H) for s in SL.NAMES for tf in SL.TFS for H in SL.HS}
got = set(map(tuple, raw[key].itertuples(index=False, name=None)))
missing = sorted(exp - got)
extra = sorted(got - exp)
print("expected cells:", len(exp), "present:", len(got & exp), "missing:", len(missing), "extra:", len(extra))

# 2. cross-check against the Discover agents' assembled gate_cells.csv
asm = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(SWEEP, "discover_*", "gate_cells.csv")))],
                ignore_index=True)
m = raw.merge(asm, on=key, suffixes=("", "_asm"))
xc = {}
for c in ["n", "fwd", "z", "p", "p_vn", "z_vn", "mu_star", "cost_H", "symbols_pos", "n_coins_ge10", "net_time",
          "fwd_minus_hurdle"]:
    a, b = m[c].to_numpy(float), m[c + "_asm"].to_numpy(float)
    both_nan = np.isnan(a) & np.isnan(b)
    diff = np.where(both_nan, 0.0, np.abs(a - b))
    xc[c] = float(np.nanmax(diff)) if len(diff) else np.nan
    xc[c + "_nan_mismatch"] = int((np.isnan(a) != np.isnan(b)).sum())
print("assembled rows:", len(asm), "merged:", len(m), "max abs diff raw vs assembled:", json.dumps(xc))

# 3. apply the pre-registered gate ONCE over the whole family
g = SL.apply_gate(raw)
g["fwd_minus_mu_star"] = g["fwd"] - g["mu_star"]
g = g.sort_values(["tf", "strategy", "H"], key=lambda s: s.map({t: i for i, t in enumerate(SL.TFS)})
                  if s.name == "tf" else s).reset_index(drop=True)
g.to_csv(os.path.join(OUT, "gate_all_is_applied.csv"), index=False)

fam = g[g["in_family"]]
mfam = int(g["m_family"].iloc[0])
print("family size m =", mfam, "(cells with n>=100 and finite p, p_vn)")
print("family by tf:", fam.groupby("tf").size().reindex(list(SL.TFS)).to_dict())
print("cells n<100 or non-finite p:", int((~g["in_family"]).sum()))
nf = g[(g["n"] >= SL.MIN_N) & ~(np.isfinite(g["p"]) & np.isfinite(g["p_vn"]))]
print("n>=100 but non-finite p/p_vn:", len(nf), nf[key].values.tolist())

# Holm first-step thresholds
print("Holm first step: p < %.3e (z > %.3f)" % (0.05 / mfam, SL.norm.isf(0.05 / mfam)))

surv = g[g["gate_pass"]]
surv_spec = g[g["gate_pass_spec"]]
print("gate_pass survivors:", len(surv))
print("gate_pass_spec survivors (descriptive):", len(surv_spec))
cond = pd.DataFrame({
    "c1_p_holm": fam["p_holm"] < SL.ALPHA,
    "c2_p_vn_holm": fam["p_vn_holm"] < SL.ALPHA,
    "c3_fwd_ge_mu": fam["fwd"] >= fam["mu_star"],
    "c4_sympos": fam["sympos_ok"],
})
print("family cells meeting each condition:", cond.sum().to_dict())
print("family cells meeting c3 & c4:", int((cond.c3_fwd_ge_mu & cond.c4_sympos).sum()))
print("smallest p_holm:", float(fam["p_holm"].min()), "smallest p_vn_holm:", float(fam["p_vn_holm"].min()))
top = fam.sort_values("p").head(10)[key + ["n", "fwd", "mu_star", "z", "p", "p_holm", "z_vn", "p_vn", "p_vn_holm",
                                           "symbols_pos", "n_coins_ge10"]]
print(top.to_string())

summary = dict(
    raw_files=[os.path.relpath(f, SWEEP) for f in raw_files], n_rows=int(len(raw)), expected_cells=len(exp),
    missing_cells=[list(x) for x in missing], extra_cells=[list(x) for x in extra], xcheck_max_abs_diff=xc,
    m_family=mfam, family_by_tf=fam.groupby("tf").size().reindex(list(SL.TFS)).fillna(0).astype(int).to_dict(),
    holm_first_step_p=0.05 / mfam, holm_first_step_z=float(SL.norm.isf(0.05 / mfam)),
    n_gate_pass=int(len(surv)), n_gate_pass_spec=int(len(surv_spec)),
    cond_counts={k: int(v) for k, v in cond.sum().items()},
    min_p=float(fam["p"].min()), min_p_holm=float(fam["p_holm"].min()), min_p_vn=float(fam["p_vn"].min()),
    min_p_vn_holm=float(fam["p_vn_holm"].min()),
    survivors=surv[key].values.tolist(), survivors_spec=surv_spec[key].values.tolist(),
)
with open(os.path.join(OUT, "combine_summary.json"), "w") as fh:
    json.dump(summary, fh, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
print("wrote", os.path.join(OUT, "gate_all_is_applied.csv"))
